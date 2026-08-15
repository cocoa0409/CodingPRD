"""Spot routes: placement, preemption, and the make-good cycle
(PRD §3.5/§3.6). Validation pipeline order per PRD §2.10."""

from flask import Blueprint

from domain import (
    EARLY_PENALTY_PCT, PREEMPT_REASONS, bucket_for, covering_log_finalized,
    headroom_check, line_of_spot, order_of_spot, post_discrepancy_credit,
    separation_check,
)
from helpers import (
    auth, fail, json_body, list_response, new_record, ok_object,
    opt_version_field, query_filter, touch,
)
from serializers import ser_as_run_entry, ser_spot
from store import db

bp = Blueprint("spots", __name__)

READERS_OPS = ("SalesRep", "TrafficManager", "BillingClerk", "StationAdmin")


def get_spot_or_404(spot_id):
    rec = db.spots.get(spot_id)
    if rec is None:
        fail("ERR_NOT_FOUND", "spot %s not found" % spot_id)
    return rec


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

@bp.get("/traffic/spots/<spot_id>")
def get_spot(spot_id):
    auth(*READERS_OPS)
    return ok_object(ser_spot(get_spot_or_404(spot_id)))


@bp.get("/traffic/spots/<spot_id>/make-goods")
def list_make_goods(spot_id):
    auth(*READERS_OPS)
    get_spot_or_404(spot_id)
    items = [s for s in db.spots.values() if s["make_good_of_spot_id"] == spot_id]
    status = query_filter("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return list_response(items, ser_spot)


@bp.get("/traffic/spots/<spot_id>/as-run-entries")
def list_spot_as_run_entries(spot_id):
    auth("TrafficManager", "BillingClerk", "StationAdmin")
    get_spot_or_404(spot_id)
    items = [e for e in db.as_run_entries.values() if e["spot_id"] == spot_id]
    return list_response(items, ser_as_run_entry)


# ---------------------------------------------------------------------------
# Placement (PRD §3.5)
# ---------------------------------------------------------------------------

@bp.post("/traffic/spots/<spot_id>/place")
def place_spot(spot_id):
    auth("TrafficManager")
    spot = get_spot_or_404(spot_id)  # path id first (PRD §2.9)
    data = json_body()
    avail_unit_id = data.get("avail_unit_id")
    unit = None
    if avail_unit_id is not None:
        unit = db.avail_units.get(avail_unit_id)
        if unit is None:
            fail("ERR_NOT_FOUND", "avail unit %s not found" % avail_unit_id)
    # State legality (priority 4): spot transition, order APPROVED, week OPEN.
    if spot["status"] not in ("PENDING_PLACEMENT", "MAKE_GOOD_OFFERED"):
        fail(
            "ERR_INVALID_STATE",
            "spot in status %s cannot be placed" % spot["status"],
        )
    line = line_of_spot(spot)
    order = db.orders[line["order_id"]]
    if order["status"] != "APPROVED":
        fail(
            "ERR_INVALID_STATE",
            "owning order in status %s does not allow placement" % order["status"],
        )
    if unit is not None:
        week = db.avail_weeks[unit["avail_week_id"]]
        if week["status"] != "OPEN":
            fail(
                "ERR_INVALID_STATE",
                "avail week in status %s is locked against new placements" % week["status"],
            )
        # Date-window coherence (priority 5): air date inside the order flight.
        if not (order["flight_start_date"] <= unit["air_date"] <= order["flight_end_date"]):
            fail(
                "ERR_DATE_WINDOW",
                "avail unit air_date lies outside the order flight window",
            )
        # Cross-reference coherence (priority 6): same program; plus the
        # make-good comparable-or-better rating rule (PRD §3.6).
        if unit["program_id"] != line["program_id"]:
            fail(
                "ERR_REFERENCE_MISMATCH",
                "avail unit program does not match the order line program",
            )
        origin_id = spot["make_good_of_spot_id"]
        if origin_id:
            original = db.spots[origin_id]
            if original["avail_unit_id"]:
                original_unit = db.avail_units[original["avail_unit_id"]]
                original_program = db.programs[original_unit["program_id"]]
                target_program = db.programs[unit["program_id"]]
                if target_program["rating_estimate"] < original_program["rating_estimate"]:
                    fail(
                        "ERR_REFERENCE_MISMATCH",
                        "make-good target program rating is below the original",
                    )
        # Political inventory protection (7) and capacity (8).
        headroom_check(spot, unit)
        # Commercial separation (9).
        separation_check(spot, unit)
    # Field sanity (13): the OCC guard field is a non-optional input (PRD §2.8).
    if avail_unit_id is None:
        fail("ERR_INVALID_REQUEST", "avail_unit_id is required")
    expected = opt_version_field(data, "expected_avail_unit_version")
    if expected is None:
        fail("ERR_INVALID_REQUEST", "expected_avail_unit_version is required")
    # OCC (15): checked last, surfaces only on an otherwise-valid request.
    if expected != unit["version"]:
        fail(
            "ERR_STALE_AVAIL_VERSION",
            "avail unit version has advanced since the client's last read",
        )
    # Apply: commit the spot to the break and hold its seconds.
    spot["avail_unit_id"] = unit["id"]
    spot["scheduled_air_date"] = unit["air_date"]
    spot["status"] = "SCHEDULED"
    unit[bucket_for(spot)] += line["spot_length_seconds"]
    touch(unit)
    touch(spot)
    return ok_object(ser_spot(spot))


# ---------------------------------------------------------------------------
# Preemption (PRD §3.6)
# ---------------------------------------------------------------------------

@bp.post("/traffic/spots/<spot_id>/preempt")
def preempt_spot(spot_id):
    auth("TrafficManager")
    spot = get_spot_or_404(spot_id)
    data = json_body()
    # State legality (4): SCHEDULED only, and not locked into a finalized log.
    if spot["status"] != "SCHEDULED":
        fail(
            "ERR_INVALID_STATE",
            "spot in status %s cannot be preempted" % spot["status"],
        )
    if covering_log_finalized(spot["scheduled_air_date"]):
        fail(
            "ERR_INVALID_STATE",
            "spot is locked into a finalized log and cannot be preempted",
        )
    reason = data.get("preempt_reason")
    # Political inventory protection (7): political-priority preemption may
    # target COMMERCIAL spots only.
    if reason == "POLITICAL_PRIORITY" and spot["spot_class"] == "POLITICAL":
        fail(
            "ERR_POLITICAL_RESERVE",
            "political spots cannot be preempted for political priority",
        )
    # Field sanity (13): reason must be one of the declared values.
    if reason not in PREEMPT_REASONS:
        fail(
            "ERR_INVALID_REQUEST",
            "preempt_reason must be one of %s" % sorted(PREEMPT_REASONS),
        )
    line = line_of_spot(spot)
    unit = db.avail_units[spot["avail_unit_id"]]
    unit[bucket_for(spot)] -= line["spot_length_seconds"]
    touch(unit)
    spot["status"] = "PREEMPTED"
    spot["preempt_reason"] = reason
    touch(spot)
    # Provisional discrepancy credit at the early tier — base price with no
    # penalty, posted immediately against the order's ledger (PRD §3.6).
    order = db.orders[line["order_id"]]
    post_discrepancy_credit(order["id"], spot, EARLY_PENALTY_PCT)
    return ok_object(ser_spot(spot))


# ---------------------------------------------------------------------------
# Make-good cycle (PRD §3.6)
# ---------------------------------------------------------------------------

@bp.post("/traffic/spots/<spot_id>/offer-make-good")
def offer_make_good(spot_id):
    auth("TrafficManager")
    spot = get_spot_or_404(spot_id)
    if spot["status"] != "PREEMPTED":
        fail(
            "ERR_INVALID_STATE",
            "spot in status %s cannot be offered a make-good" % spot["status"],
        )
    # Capacity (8): only one outstanding make-good per preempted spot.
    for other in db.spots.values():
        if (
            other["make_good_of_spot_id"] == spot["id"]
            and other["status"] in ("MAKE_GOOD_OFFERED", "SCHEDULED")
        ):
            fail(
                "ERR_AVAIL_OVERFLOW",
                "an outstanding make-good already exists for this spot",
            )
    make_good = new_record()
    make_good.update(
        {
            "order_line_id": spot["order_line_id"],
            "avail_unit_id": None,
            "copy_instruction_id": None,
            "spot_class": spot["spot_class"],
            "scheduled_air_date": None,
            "status": "MAKE_GOOD_OFFERED",
            "preempt_reason": "NONE",
            "make_good_of_spot_id": spot["id"],
        }
    )
    db.spots[make_good["id"]] = make_good
    touch(spot)
    return ok_object(ser_spot(make_good), 201)


@bp.post("/traffic/spots/<spot_id>/decline-make-good")
def decline_make_good(spot_id):
    auth("SalesRep")
    spot = get_spot_or_404(spot_id)
    if spot["status"] != "MAKE_GOOD_OFFERED":
        fail(
            "ERR_INVALID_STATE",
            "spot in status %s cannot be declined" % spot["status"],
        )
    spot["status"] = "CANCELLED"
    touch(spot)
    # The originating preempted spot remains PREEMPTED until the order
    # completion sweep (PRD §3.6) — no further action here.
    return ok_object(ser_spot(spot))
