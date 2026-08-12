"""Logical clock, clients and engagements."""

from flask import Blueprint

import calc
import constants as K
import derive
import gates
import services
import store
from errors import ApiError
from routes.helpers import one, raw, listing, filtered
from util import shift_hours, parse_dt, num, D

bp = Blueprint("core", __name__)

ALL_READ_ROLES = ["MOVE_MANAGER", "BILLING_ADMIN", "PLATFORM_ADMIN", "CLIENT",
                  "FAMILY_MEMBER", "POWER_OF_ATTORNEY"]


# ---------------------------------------------------------------------------
# logical clock
# ---------------------------------------------------------------------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    req = gates.preflight(["PLATFORM_ADMIN", "MOVE_MANAGER"],
                          required=[("to_iso8601", "datetime")])
    current = store.set_clock(req.body["to_iso8601"])
    return raw({"current_utc": current})


# ---------------------------------------------------------------------------
# clients
# ---------------------------------------------------------------------------

@bp.route("/clients", methods=["POST"])
def create_client():
    req = gates.preflight(["MOVE_MANAGER"],
                          required=[("full_name", "string"), ("phone", "string")],
                          optional=[("email", "string")])
    record = store.base_record()
    record.update({
        "full_name": req.body["full_name"],
        "phone": req.body["phone"],
        "email": req.body.get("email"),
    })
    store.insert("clients", record)
    return one("clients", record, 201)


@bp.route("/clients/<cid>", methods=["GET"])
def read_client(cid):
    req = gates.preflight(["MOVE_MANAGER", "BILLING_ADMIN", "CLIENT"])
    record = gates.path_record("clients", cid)
    gates.gate4_ownership(req, client_id=record["id"])
    return one("clients", record)


# ---------------------------------------------------------------------------
# engagements
# ---------------------------------------------------------------------------

@bp.route("/engagements", methods=["POST"])
def create_engagement():
    req = gates.preflight(
        ["MOVE_MANAGER"],
        required=[("client_id", "string"), ("billing_mode", "string"),
                  ("home_tier", "string"), ("scheduled_move_start_utc", "datetime"),
                  ("mileage_miles", "number"), ("origin_stairs_flights", "int"),
                  ("origin_long_carry_feet", "int")],
        optional=[("package_tier", "string")])
    fks = gates.resolve_body_fks(req.body)
    client = fks["client_id"]

    # rung 67 - the single rung at which the two pipelines diverge at creation
    package_tier = req.body.get("package_tier")
    if req.body["billing_mode"] == "PACKAGE":
        if package_tier is None:
            raise ApiError("ERR_PACKAGE_TIER_REQUIRED")
    elif package_tier is not None:
        raise ApiError("ERR_PACKAGE_TIER_REQUIRED")

    record = store.base_record()
    record.update({
        "client_id": client["id"],
        "status": "ACTIVE",
        "billing_mode": req.body["billing_mode"],
        "home_tier": req.body["home_tier"],
        "package_tier": package_tier,
        "scheduled_move_start_utc": req.body["scheduled_move_start_utc"],
        "move_freeze_at_utc": shift_hours(req.body["scheduled_move_start_utc"],
                                          -K.MOVE_FREEZE_HOURS),
        "mileage_miles": req.body["mileage_miles"],
        "origin_stairs_flights": req.body["origin_stairs_flights"],
        "origin_long_carry_feet": req.body["origin_long_carry_feet"],
        "hold_reason": None,
        "hold_count": 0,
        "cancel_reason": None,
        "closed_at_utc": None,
        "ops_run_seq": 0,
    })
    store.insert("engagements", record)
    services.create_engagement_children(record, req.role)
    return one("engagements", record, 201)


@bp.route("/engagements", methods=["GET"])
def list_engagements():
    req = gates.preflight(ALL_READ_ROLES, is_list=True)
    rows = filtered(store.all_of("engagements"), req.args, ["client_id", "status"])
    if "phase" in req.args:
        rows = [r for r in rows if derive.engagement_phase(r) == req.args.get("phase")]
    return listing("engagements", req, rows)


@bp.route("/engagements/<eid>", methods=["GET"])
def read_engagement(eid):
    req = gates.preflight(ALL_READ_ROLES + ["CREW_LEAD"])
    record = gates.path_record("engagements", eid)
    gates.gate4_ownership(req, engagement=record)
    return one("engagements", record)


@bp.route("/engagements/<eid>", methods=["PATCH"])
def patch_engagement(eid):
    req = gates.preflight(
        ["MOVE_MANAGER"],
        optional=[("scheduled_move_start_utc", "datetime"), ("mileage_miles", "number"),
                  ("origin_stairs_flights", "int"), ("origin_long_carry_feet", "int"),
                  ("package_tier", "string")])
    record = gates.path_record("engagements", eid)
    gates.gate3(record)

    resulting_tier = req.body["package_tier"] if "package_tier" in req.body \
        else record["package_tier"]
    if record["billing_mode"] == "PACKAGE":
        if resulting_tier is None:
            raise ApiError("ERR_PACKAGE_TIER_REQUIRED")
    elif resulting_tier is not None:
        raise ApiError("ERR_PACKAGE_TIER_REQUIRED")

    for field in ("scheduled_move_start_utc", "mileage_miles", "origin_stairs_flights",
                  "origin_long_carry_feet"):
        if field in req.body and req.body[field] is not None:
            record[field] = req.body[field]
    if "package_tier" in req.body:
        record["package_tier"] = req.body["package_tier"]
    record["move_freeze_at_utc"] = shift_hours(record["scheduled_move_start_utc"],
                                               -K.MOVE_FREEZE_HOURS)
    store.touch(record)
    return one("engagements", record)


@bp.route("/engagements/<eid>/hold", methods=["POST"])
def hold_engagement(eid):
    req = gates.preflight(["MOVE_MANAGER"], required=[("reason", "nes")])
    record = gates.path_record("engagements", eid)
    gates.gate3(record)
    gates.gate10_state(record["status"], ["ACTIVE"], ["CLOSED", "CANCELLED"])
    record["status"] = "ON_HOLD"
    record["hold_reason"] = req.body["reason"]
    record["hold_count"] = record["hold_count"] + 1
    store.touch(record)
    return one("engagements", record)


@bp.route("/engagements/<eid>/resume", methods=["POST"])
def resume_engagement(eid):
    gates.preflight(["MOVE_MANAGER"])
    record = gates.path_record("engagements", eid)
    gates.gate3(record, on_hold_exempt=True)
    gates.gate10_state(record["status"], ["ON_HOLD"], ["CLOSED", "CANCELLED"])
    record["status"] = "ACTIVE"
    record["hold_reason"] = None
    store.touch(record)
    return one("engagements", record)


@bp.route("/engagements/<eid>/cancel", methods=["POST"])
def cancel_engagement(eid):
    req = gates.preflight(["MOVE_MANAGER"], required=[("reason", "nes")])
    record = gates.path_record("engagements", eid)
    gates.gate3(record, on_hold_exempt=True)
    gates.gate10_state(record["status"], ["ACTIVE", "ON_HOLD"], ["CLOSED", "CANCELLED"])
    if record["status"] == "ACTIVE":
        plan = derive.move_day_plan_of(record["id"])
        gates.require_state(plan is None or plan["status"] != "IN_PROGRESS")

    record["status"] = "CANCELLED"
    record["cancel_reason"] = req.body["reason"]
    for assignment in store.where("vendor_assignments", engagement_id=record["id"]):
        if assignment["status"] in ("REQUESTED", "ACCEPTED", "SCHEDULED", "COI_BLOCKED"):
            assignment["status"] = "CANCELLED"
            store.touch(assignment)
    for session in store.where("unpack_sessions", engagement_id=record["id"]):
        if session["status"] == "SCHEDULED":
            session["status"] = "COMPLETED"
            store.touch(session)
    store.touch(record)
    return one("engagements", record)


@bp.route("/engagements/<eid>/close-out", methods=["POST"])
def close_out_engagement(eid):
    req = gates.preflight(["MOVE_MANAGER"],
                          required=[("signed_off_by_party_id", "string")])
    record = gates.path_record("engagements", eid)
    gates.resolve_body_fks(req.body)
    gates.gate3(record)
    gates.gate4_party_membership(record, [req.body["signed_off_by_party_id"]])

    close_out = derive.milestone_by_key(record["id"], "CLOSE_OUT")
    blocked = close_out is None or close_out["status"] != "COMPLETE"
    if not blocked:
        for punch in store.where("punch_list_items", engagement_id=record["id"]):
            if punch["status"] in ("OPEN", "REOPENED"):
                blocked = True
                break
    if not blocked and derive.billing_hold(record):
        blocked = True
    if blocked:
        raise ApiError("ERR_CLOSE_OUT_BLOCKED")

    gates.gate10_state(record["status"], ["ACTIVE"], ["CLOSED", "CANCELLED"])

    record["status"] = "CLOSED"
    record["closed_at_utc"] = store.now_iso()
    for assignment in store.where("vendor_assignments", engagement_id=record["id"]):
        if assignment["status"] == "SIGNED_OFF":
            assignment["holdback_released"] = True
            assignment["paid_cents"] = assignment["quoted_cents"]
            store.touch(assignment)
    invoice = derive.invoice_of(record["id"])
    if invoice is not None and invoice["status"] == "ISSUED":
        invoice["status"] = "FINALIZED"
        invoice["finalized_at_utc"] = store.now_iso()
        store.touch(invoice)
    store.touch(record)
    return one("engagements", record)


@bp.route("/engagements/<eid>/ops-run", methods=["POST"])
def engagement_ops_run(eid):
    gates.preflight(["MOVE_MANAGER", "PLATFORM_ADMIN"])
    record = gates.path_record("engagements", eid)
    gates.gate3(record)
    flagged, expired, blocked = services.ops_run(record)
    return raw({
        "engagement_id": record["id"],
        "milestones_flagged_overdue": flagged,
        "authorities_expired": expired,
        "vendor_assignments_blocked": blocked,
        "ops_run_seq": record["ops_run_seq"],
    })


@bp.route("/engagements/<eid>/summary", methods=["GET"])
def engagement_summary(eid):
    req = gates.preflight(["MOVE_MANAGER", "BILLING_ADMIN", "CLIENT", "FAMILY_MEMBER",
                           "POWER_OF_ATTORNEY"])
    record = gates.path_record("engagements", eid)
    gates.gate4_ownership(req, engagement=record)

    item_count = derive.inventory_item_count(record["id"])
    if item_count == 0:
        variant = "ASSESSMENT_HEURISTIC"
        estimate = calc.engagement_volume_estimate_heuristic(record["home_tier"])
    else:
        variant = "INVENTORY_ROLLUP"
        estimate = derive.total_inventory_volume_cft(record["id"])
    session = derive.next_unpack_session(record["id"])
    return raw({
        "engagement_id": record["id"],
        "phase": derive.engagement_phase(record),
        "billing_mode": record["billing_mode"],
        "accrued_labor_cents": derive.accrued_labor_cents(record["id"]),
        "billing_hours_total": num(derive.billing_hours_total(record["id"]), 2),
        "volume_estimate_variant": variant,
        "volume_estimate_cft": num(estimate, 2),
        "projected_total_cents": services.projected_total_cents(record),
        "open_hold_count": derive.open_hold_count(record["id"]),
        "progress_pct": calc.progress_pct(derive.milestones_of(record["id"])),
        "next_unpack_session_id": session["id"] if session else None,
    })
