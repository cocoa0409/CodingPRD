"""Instruments, the two status axes, pitch assessment and tuning recalls
(PRD 3.2, 3.3, 3.4)."""

from flask import Blueprint, jsonify, request

import calc
import serialize
import services
from core import (
    CLOCK, CONDITION_STATUSES, CUSTODY_STATUSES, DB, INSTRUMENT_CLASSES, LOCK,
    OVERDUE_TIERS, RECALL_STATUSES, USAGE_TIERS, Ctx, by_created, date_str,
    fail, make_row, need_client, need_instrument, need_location, need_other,
    not_terminal, ok, page, parse_date, touch,
)

bp = Blueprint("instruments", __name__)

CUSTODY_TERMINAL = ("SOLD",)
RECALL_TERMINAL = ("FULFILLED", "LAPSED")

CONDITION_EDGES = {
    ("NEEDS_ASSESSMENT", "SERVICEABLE"),
    ("NEEDS_ASSESSMENT", "NEEDS_REGULATION"),
    ("NEEDS_ASSESSMENT", "REBUILD_REQUIRED"),
    ("SERVICEABLE", "NEEDS_REGULATION"),
    ("RESTORED", "NEEDS_REGULATION"),
}
CUSTODY_EDGES = {
    ("AT_CLIENT_SITE", "IN_TRANSIT"),
    ("IN_SHOP", "IN_TRANSIT"),
    ("IN_TRANSIT", "IN_SHOP"),
    ("IN_TRANSIT", "AT_CLIENT_SITE"),
}


# ---------------------------------------------------------------------------
# Instruments
# ---------------------------------------------------------------------------

@bp.post("/instruments")
def create_instrument():
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager"])
        body = ctx.read_body(["client_id", "current_location_id", "make", "model",
                              "serial_number", "instrument_class", "usage_tier"])
        ctx.enum("instrument_class", INSTRUMENT_CLASSES)
        ctx.enum("usage_tier", USAGE_TIERS)
        ctx.number("target_pitch_hz", lo=calc.PITCH_HZ_MIN, hi=calc.PITCH_HZ_MAX)
        client = need_client(body["client_id"])
        location = need_location(body["current_location_id"])
        serial = body["serial_number"]
        if any(i["serial_number"] == serial for i in DB.instruments.values()):
            fail("ERR_DUPLICATE_SERIAL_NUMBER",
                 "serial_number %s already exists." % serial)
        if location["client_id"] != client["id"]:
            fail("ERR_OWNERSHIP_MISMATCH",
                 "The location is owned by a different client.")
        row = make_row(
            client_id=client["id"],
            current_location_id=location["id"],
            consignment_agreement_id=None,
            make=body["make"],
            model=body["model"],
            serial_number=serial,
            instrument_class=body["instrument_class"],
            usage_tier=body["usage_tier"],
            target_pitch_hz=(body["target_pitch_hz"]
                             if body.get("target_pitch_hz") is not None else 440.0),
            last_tuning_date=body.get("last_tuning_date"),
            pitch_deviation_cents=None,
            raw_pitch_tier=None,
            pitch_raise_tier=None,
            planned_visit_count=1,
            condition_status="NEEDS_ASSESSMENT",
            custody_status="AT_CLIENT_SITE",
            unauthorized_move_flag=False,
            tuning_cycle_interval_days=None,
        )
        DB.instruments[row["id"]] = row
        payload, status = ok(serialize.instrument(row), 201)
        return jsonify(payload), status


@bp.get("/instruments")
def list_instruments():
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager", "Technician", "Client",
                   "MoveCoordinator", "ShowroomAgent"])
        client_filter = request.args.get("client_id")
        if client_filter:
            ctx.scope_client(client_filter)
        custody = ctx.enum_q("custody_status", CUSTODY_STATUSES)
        condition = ctx.enum_q("condition_status", CONDITION_STATUSES)
        limit, offset = ctx.pagination()
        rows = by_created(DB.rows("instruments"))
        if client_filter:
            rows = [r for r in rows if r["client_id"] == client_filter]
        loc = request.args.get("current_location_id")
        if loc:
            rows = [r for r in rows if r["current_location_id"] == loc]
        agreement = request.args.get("consignment_agreement_id")
        if agreement:
            rows = [r for r in rows if r["consignment_agreement_id"] == agreement]
        if custody:
            rows = [r for r in rows if r["custody_status"] == custody]
        if condition:
            rows = [r for r in rows if r["condition_status"] == condition]
        if ctx.is_client:
            rows = [r for r in rows if r["client_id"] == ctx.user_id]
        payload, http = page(rows, limit, offset, serialize.instrument)
        return jsonify(payload), http


@bp.get("/instruments/<iid>")
def read_instrument(iid):
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager", "Technician", "Client",
                   "MoveCoordinator", "ShowroomAgent"])
        existing = DB.instruments.get(iid)
        if existing is not None:
            ctx.scope_client(existing["client_id"])
        row = need_instrument(iid)
        payload, status = ok(serialize.instrument(row))
        return jsonify(payload), status


@bp.patch("/instruments/<iid>")
def update_instrument(iid):
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager"])
        body = ctx.read_body([])
        ctx.enum("usage_tier", USAGE_TIERS)
        ctx.number("target_pitch_hz", lo=calc.PITCH_HZ_MIN, hi=calc.PITCH_HZ_MAX)
        location = None
        if body.get("current_location_id") is not None:
            location = need_location(body["current_location_id"])
        row = need_instrument(iid)
        for field in ("make", "model", "usage_tier", "target_pitch_hz",
                      "last_tuning_date"):
            if field in body and body[field] is not None:
                row[field] = body[field]
        if location is not None:
            row["current_location_id"] = location["id"]
        touch(row)
        payload, status = ok(serialize.instrument(row))
        return jsonify(payload), status


# ---------------------------------------------------------------------------
# Pitch assessment (PRD 3.3) -- mutate-then-reject at rung 46
# ---------------------------------------------------------------------------

@bp.post("/instruments/<iid>/pitch-assessments")
def pitch_assessment(iid):
    with LOCK:
        ctx = Ctx(["Technician", "ShopManager", "PlatformAdmin"])
        body = ctx.read_body(["reference_pitch_hz", "measured_deviation_cents"])
        ctx.number("measured_deviation_cents",
                   lo=calc.PITCH_DEVIATION_MIN_CENTS,
                   hi=calc.PITCH_DEVIATION_MAX_CENTS)
        ctx.number("reference_pitch_hz", lo=calc.PITCH_HZ_MIN,
                   hi=calc.PITCH_HZ_MAX)
        instrument = need_instrument(iid)

        from core import D
        if D(body["reference_pitch_hz"]) != D(instrument["target_pitch_hz"]):
            fail("ERR_PITCH_REFERENCE_MISMATCH",
                 "reference_pitch_hz must equal the instrument's target_pitch_hz.")

        previous_tier = instrument["pitch_raise_tier"]
        deviation = body["measured_deviation_cents"]
        raw = calc.raw_pitch_tier(deviation)
        recall = services.governing_recall(instrument["id"])
        effective = calc.bumped_tier(raw, recall)
        instrument["pitch_deviation_cents"] = deviation
        instrument["raw_pitch_tier"] = raw
        instrument["pitch_raise_tier"] = effective
        instrument["planned_visit_count"] = calc.planned_visits(effective)
        touch(instrument)

        if effective != previous_tier:
            conflicting = [o for o in DB.service_orders.values()
                           if o["instrument_id"] == instrument["id"]
                           and o["service_type"] == "TUNE"
                           and o["status"] == "IN_PROGRESS"]
            if conflicting:
                fail("ERR_PITCH_TIER_CONFLICT",
                     "An in-flight TUNE order forbids changing the effective tier.")
        payload, status = ok(serialize.instrument(instrument))
        return jsonify(payload), status


# ---------------------------------------------------------------------------
# Custody axis (PRD 3.2) -- CASCADE A
# ---------------------------------------------------------------------------

@bp.post("/instruments/<iid>/custody-transitions")
def custody_transition(iid):
    with LOCK:
        ctx = Ctx(["MoveCoordinator", "ShopManager", "PlatformAdmin"])
        body = ctx.read_body(["to_custody_status"])
        target = ctx.enum("to_custody_status", CUSTODY_STATUSES)
        instrument = need_instrument(iid)
        job = None
        if body.get("authorizing_move_job_id") is not None:
            job = need_other("move_jobs", body["authorizing_move_job_id"])

        current = instrument["custody_status"]
        not_terminal(current, CUSTODY_TERMINAL)

        # rung 22 -- the custody gate
        if target in ("IN_SHOP", "AT_CLIENT_SITE") and current != "IN_TRANSIT":
            fail("ERR_INVALID_CUSTODY_STATE",
                 "The instrument must be IN_TRANSIT to reach %s." % target)

        # rung 23 -- the edge must exist
        if (current, target) not in CUSTODY_EDGES:
            fail("ERR_INVALID_STATE",
                 "No custody edge from %s to %s." % (current, target))

        if current == "IN_SHOP" and target == "IN_TRANSIT":
            busy = [o for o in DB.service_orders.values()
                    if o["instrument_id"] == instrument["id"]
                    and o["status"] == "IN_PROGRESS"]
            if busy:
                fail("ERR_INVALID_STATE",
                     "A service order for this instrument is IN_PROGRESS.")

        # rung 40 -- the authorising move job
        if job is not None:
            if job["instrument_id"] != instrument["id"]:
                fail("ERR_INVALID_STATE",
                     "The authorising move job belongs to another instrument.")
            expected = "DISPATCHED" if target == "IN_TRANSIT" else "IN_TRANSIT"
            if job["status"] != expected:
                fail("ERR_INVALID_STATE",
                     "The authorising move job must be %s." % expected)

        instrument["custody_status"] = target
        if target == "IN_TRANSIT":
            if job is None:
                instrument["unauthorized_move_flag"] = True
                touch(instrument)
                services.cascade_a(instrument)
            else:
                job["status"] = "IN_TRANSIT"
                touch(job)
                touch(instrument)
        else:
            if job is not None:
                job["status"] = "DELIVERED"
                touch(job)
                instrument["current_location_id"] = job["destination_location_id"]
            touch(instrument)
        payload, status = ok(serialize.instrument(instrument))
        return jsonify(payload), status


# ---------------------------------------------------------------------------
# Condition axis (PRD 3.2)
# ---------------------------------------------------------------------------

@bp.post("/instruments/<iid>/condition-transitions")
def condition_transition(iid):
    with LOCK:
        ctx = Ctx(["Technician", "ShopManager", "PlatformAdmin"])
        body = ctx.read_body(["to_condition_status"])
        target = ctx.enum("to_condition_status", CONDITION_STATUSES)
        instrument = need_instrument(iid)

        # rung 22 -- the custody gate
        if instrument["custody_status"] not in ("AT_CLIENT_SITE", "IN_SHOP",
                                                "SHOWROOM_FLOOR"):
            fail("ERR_INVALID_CUSTODY_STATE",
                 "Custody %s does not permit a condition transition."
                 % instrument["custody_status"])

        current = instrument["condition_status"]
        if (current, target) not in CONDITION_EDGES:
            fail("ERR_INVALID_STATE",
                 "No condition edge from %s to %s." % (current, target))
        if target == "SERVICEABLE" and instrument["pitch_deviation_cents"] is None:
            fail("ERR_INVALID_STATE",
                 "A pitch assessment must be recorded before SERVICEABLE.")

        instrument["condition_status"] = target
        touch(instrument)
        payload, status = ok(serialize.instrument(instrument))
        return jsonify(payload), status


# ---------------------------------------------------------------------------
# Tuning recalls (PRD 3.4)
# ---------------------------------------------------------------------------

@bp.post("/tuning-recalls")
def create_recall():
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager"])
        body = ctx.read_body(["instrument_id", "cycle_start_date"])
        instrument = need_instrument(body["instrument_id"])
        start = parse_date(body["cycle_start_date"])
        if start is None:
            fail("ERR_VALIDATION", "cycle_start_date must be an ISO date.")
        location = DB.locations.get(instrument["current_location_id"])
        climate_controlled = bool(location and location.get("climate_controlled"))
        interval = calc.tuning_cycle_interval(instrument["usage_tier"],
                                              climate_controlled,
                                              instrument["instrument_class"])
        due = calc.recall_due_date(start, interval)
        instrument["tuning_cycle_interval_days"] = interval
        touch(instrument)
        row = make_row(
            instrument_id=instrument["id"],
            cycle_start_date=body["cycle_start_date"],
            interval_days=interval,
            due_date=date_str(due),
            days_overdue=0,
            overdue_tier="ON_TIME",
            status="PENDING",
            notified_at=None,
        )
        DB.tuning_recalls[row["id"]] = row
        payload, status = ok(serialize.tuning_recall(row), 201)
        return jsonify(payload), status


@bp.get("/instruments/<iid>/tuning-recalls")
def list_recalls(iid):
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager", "Technician", "Client"])
        existing = DB.instruments.get(iid)
        if existing is not None:
            ctx.scope_client(existing["client_id"])
        status_f = ctx.enum_q("status", RECALL_STATUSES)
        tier_f = ctx.enum_q("overdue_tier", OVERDUE_TIERS)
        limit, offset = ctx.pagination()
        instrument = need_instrument(iid)
        rows = by_created([r for r in DB.tuning_recalls.values()
                           if r["instrument_id"] == instrument["id"]])
        if status_f:
            rows = [r for r in rows if r["status"] == status_f]
        if tier_f:
            rows = [r for r in rows if r["overdue_tier"] == tier_f]
        payload, http = page(rows, limit, offset, serialize.tuning_recall)
        return jsonify(payload), http


@bp.post("/tuning-recalls/<rid>/notify")
def notify_recall(rid):
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager"])
        ctx.read_body([])
        recall = need_other("tuning_recalls", rid)
        instrument = DB.instruments.get(recall["instrument_id"])
        client = DB.clients.get(instrument["client_id"]) if instrument else None
        if client is not None and client["status"] != "ACTIVE":
            fail("ERR_CLIENT_NOT_ACTIVE", "The owning client is not ACTIVE.")
        not_terminal(recall["status"], RECALL_TERMINAL)
        if recall["status"] != "PENDING":
            fail("ERR_INVALID_STATE",
                 "No recall edge from %s to NOTIFIED." % recall["status"])
        recall["status"] = "NOTIFIED"
        recall["notified_at"] = CLOCK.stamp()
        touch(recall)
        payload, status = ok(serialize.tuning_recall(recall))
        return jsonify(payload), status
