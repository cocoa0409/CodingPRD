"""TripTrade routes (PRD §3.5, §3.6)."""
from flask import Blueprint, request

import db
from errors import (
    not_found, forbidden, invalid_state, cross_entity_state,
    faa_duty_cap, faa_flight_cap, crew_rest_violation,
    rank_seat_mismatch, pairing_overlap, stale_version, invalid_request,
)
from middleware import require_roles, ROLE_PLANNER, ROLE_OPS, ROLE_CREW
from response import success, paginated
from routes.common import (
    get_json_body, parse_pagination, sort_by_created_at, slice_page,
)
from services.constants import rank_seat_compatible
from services import validate
from services.calc import (
    faa_preview_violations, crew_rest_passes,
)
from services.entity import stamp_new, touch
from services.timeutil import parse_iso


bp = Blueprint("trip_trades", __name__)


TRADE_REQUIRED = ("initiator_assignment_id", "counterparty_assignment_id")
TRADE_ALLOWED = set(TRADE_REQUIRED)


@bp.route("/trip-trades", methods=["POST"])
def create_trip_trade():
    user_id, role = require_roles({ROLE_CREW})
    body = validate.ensure_dict(get_json_body())
    validate.require_fields(body, TRADE_REQUIRED)
    validate.reject_extra(body, TRADE_ALLOWED)
    init_aid = validate.check_string(body, "initiator_assignment_id")
    cnt_aid = validate.check_string(body, "counterparty_assignment_id")

    init_a = db.assignments.get(init_aid)
    if init_a is None:
        raise not_found("initiator_assignment_id does not resolve")
    cnt_a = db.assignments.get(cnt_aid)
    if cnt_a is None:
        raise not_found("counterparty_assignment_id does not resolve")

    # Ownership: caller must be the initiator's crew member.
    if init_a["crew_member_id"] != user_id:
        raise forbidden("CrewMember can only propose trip-trades on their own initiator assignment")

    record = {
        "initiator_assignment_id": init_aid,
        "counterparty_assignment_id": cnt_aid,
        "initiator_id": init_a["crew_member_id"],
        "counterparty_id": cnt_a["crew_member_id"],
        "state": "PROPOSED",
        "rejection_reason": None,
    }
    stamp_new(record)
    db.trip_trades[record["id"]] = record
    return success(record, status=201)


@bp.route("/trip-trades", methods=["GET"])
def list_trip_trades():
    user_id, role = require_roles({ROLE_PLANNER, ROLE_OPS, ROLE_CREW})
    limit, offset = parse_pagination()
    rows = list(db.trip_trades.values())
    initiator_id = request.args.get("initiator_id")
    counterparty_id = request.args.get("counterparty_id")
    initiator_assignment_id = request.args.get("initiator_assignment_id")
    counterparty_assignment_id = request.args.get("counterparty_assignment_id")
    state = request.args.get("state")
    if initiator_id:
        rows = [r for r in rows if r["initiator_id"] == initiator_id]
    if counterparty_id:
        rows = [r for r in rows if r["counterparty_id"] == counterparty_id]
    if initiator_assignment_id:
        rows = [r for r in rows if r["initiator_assignment_id"] == initiator_assignment_id]
    if counterparty_assignment_id:
        rows = [r for r in rows if r["counterparty_assignment_id"] == counterparty_assignment_id]
    if state:
        rows = [r for r in rows if r["state"] == state]
    if role == ROLE_CREW:
        rows = [r for r in rows if r["initiator_id"] == user_id or r["counterparty_id"] == user_id]
    rows = sort_by_created_at(rows)
    page, total = slice_page(rows, limit, offset)
    return paginated(page, limit, offset, total)


@bp.route("/trip-trades/<trade_id>", methods=["GET"])
def get_trip_trade(trade_id):
    require_roles({ROLE_PLANNER, ROLE_OPS, ROLE_CREW})
    t = db.trip_trades.get(trade_id)
    if t is None:
        raise not_found("TripTrade not found")
    return success(t, status=200)


@bp.route("/trip-trades/<trade_id>/countersign", methods=["POST"])
def countersign_trip_trade(trade_id):
    user_id, role = require_roles({ROLE_CREW})
    t = db.trip_trades.get(trade_id)
    if t is None:
        raise not_found("TripTrade not found")
    if t["counterparty_id"] != user_id:
        raise forbidden("Only the counterparty may countersign")
    if t["state"] != "PROPOSED":
        raise invalid_state(f"Cannot countersign TripTrade in state {t['state']!r}")
    # Both Assignments must still be in SCHEDULED or CONFIRMED.
    a_init = db.assignments.get(t["initiator_assignment_id"])
    a_cnt = db.assignments.get(t["counterparty_assignment_id"])
    if a_init is None or a_cnt is None:
        raise not_found("Referenced Assignment missing")
    if a_init["state"] not in {"SCHEDULED", "CONFIRMED"} or a_cnt["state"] not in {"SCHEDULED", "CONFIRMED"}:
        raise cross_entity_state("Both Assignments must be SCHEDULED or CONFIRMED")
    t["state"] = "COUNTERSIGNED"
    touch(t)
    return success(t, status=200)


@bp.route("/trip-trades/<trade_id>/reject", methods=["POST"])
def reject_trip_trade(trade_id):
    user_id, role = require_roles({ROLE_CREW})
    t = db.trip_trades.get(trade_id)
    if t is None:
        raise not_found("TripTrade not found")
    body = validate.ensure_dict(get_json_body())
    reason = body.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise invalid_request("reason must be a string if supplied")
    if t["counterparty_id"] != user_id:
        raise forbidden("Only the counterparty may reject")
    if t["state"] != "PROPOSED":
        raise invalid_state(f"Cannot reject TripTrade in state {t['state']!r}")
    t["state"] = "REJECTED"
    t["rejection_reason"] = reason
    touch(t)
    return success(t, status=200)


@bp.route("/trip-trades/<trade_id>/withdraw", methods=["POST"])
def withdraw_trip_trade(trade_id):
    user_id, role = require_roles({ROLE_CREW})
    t = db.trip_trades.get(trade_id)
    if t is None:
        raise not_found("TripTrade not found")
    if t["initiator_id"] != user_id:
        raise forbidden("Only the initiator may withdraw")
    if t["state"] not in {"PROPOSED", "COUNTERSIGNED"}:
        raise invalid_state(f"Cannot withdraw TripTrade in state {t['state']!r}")
    t["state"] = "WITHDRAWN"
    touch(t)
    return success(t, status=200)


def _pairing_overlap(window_a, others) -> bool:
    """Half-open interval overlap test (PRD §3.6).
    window_a: (start, end). others: list of (start, end). Returns True on conflict.
    """
    a_start, a_end = window_a
    for o_start, o_end in others:
        # half-open: conflict iff a_start < o_end AND o_start < a_end.
        if a_start < o_end and o_start < a_end:
            return True
    return False


@bp.route("/trip-trades/<trade_id>/approve", methods=["POST"])
def approve_trip_trade(trade_id):
    require_roles({ROLE_OPS})
    t = db.trip_trades.get(trade_id)
    if t is None:
        raise not_found("TripTrade not found")
    if t["state"] != "COUNTERSIGNED":
        raise invalid_state(f"Cannot approve TripTrade in state {t['state']!r}")

    a_init = db.assignments.get(t["initiator_assignment_id"])
    a_cnt = db.assignments.get(t["counterparty_assignment_id"])
    if a_init is None or a_cnt is None:
        raise not_found("Referenced Assignment missing")
    if a_init["state"] not in {"SCHEDULED", "CONFIRMED"} or a_cnt["state"] not in {"SCHEDULED", "CONFIRMED"}:
        raise cross_entity_state("Both Assignments must be SCHEDULED or CONFIRMED")

    cm_a = db.crew_members.get(t["initiator_id"])
    cm_b = db.crew_members.get(t["counterparty_id"])
    if cm_a is None or cm_b is None:
        raise not_found("CrewMember referenced by trade not found")

    p_init = db.pairings.get(a_init["pairing_id"])
    p_cnt = db.pairings.get(a_cnt["pairing_id"])
    if p_init is None or p_cnt is None:
        raise not_found("Pairing referenced by Assignment not found")

    # After swap: cm_a will be on p_cnt, cm_b will be on p_init.
    # Business-safety FAA/rest preview against the candidate pairing.
    duty_a, flight_a = faa_preview_violations(cm_a, p_cnt)
    duty_b, flight_b = faa_preview_violations(cm_b, p_init)
    if duty_a or duty_b:
        raise faa_duty_cap()
    if flight_a or flight_b:
        raise faa_flight_cap()
    if not crew_rest_passes(cm_a, p_cnt) or not crew_rest_passes(cm_b, p_init):
        raise crew_rest_violation()

    # Rank-seat: each crew's rank must match the seat they inherit (the
    # seat of the assignment they would now own).
    if not rank_seat_compatible(cm_a["rank"], a_cnt["seat"]):
        raise rank_seat_mismatch(
            f"Initiator rank {cm_a['rank']!r} cannot fill seat {a_cnt['seat']!r}"
        )
    if not rank_seat_compatible(cm_b["rank"], a_init["seat"]):
        raise rank_seat_mismatch(
            f"Counterparty rank {cm_b['rank']!r} cannot fill seat {a_init['seat']!r}"
        )

    # Pairing-overlap check (PRD §3.6, half-open intervals).
    # For each crew member, the new pairing must not overlap their existing
    # CONFIRMED (or SCHEDULED) Assignments' duty windows. The originals being
    # released are excluded.
    def _other_windows(crew_id, exclude_aid):
        windows = []
        for asn in db.assignments.values():
            if asn["crew_member_id"] != crew_id:
                continue
            if asn["id"] == exclude_aid:
                continue
            if asn["state"] not in {"SCHEDULED", "CONFIRMED", "ACTIVE"}:
                continue
            par = db.pairings.get(asn["pairing_id"])
            if par is None:
                continue
            windows.append(
                (parse_iso(par["scheduled_start_utc"]),
                 parse_iso(par["scheduled_end_utc"]))
            )
        return windows

    cand_a = (parse_iso(p_cnt["scheduled_start_utc"]), parse_iso(p_cnt["scheduled_end_utc"]))
    cand_b = (parse_iso(p_init["scheduled_start_utc"]), parse_iso(p_init["scheduled_end_utc"]))
    if _pairing_overlap(cand_a, _other_windows(cm_a["id"], a_init["id"])):
        raise pairing_overlap("Initiator post-swap pairing overlaps existing duty windows")
    if _pairing_overlap(cand_b, _other_windows(cm_b["id"], a_cnt["id"])):
        raise pairing_overlap("Counterparty post-swap pairing overlaps existing duty windows")

    t["state"] = "APPROVED"
    touch(t)
    return success(t, status=200)


@bp.route("/trip-trades/<trade_id>/execute", methods=["POST"])
def execute_trip_trade(trade_id):
    require_roles({ROLE_OPS})
    t = db.trip_trades.get(trade_id)
    if t is None:
        raise not_found("TripTrade not found")
    body = validate.ensure_dict(get_json_body())
    if "expected_trip_trade_version" not in body:
        raise invalid_request("expected_trip_trade_version is required")
    expected = body["expected_trip_trade_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise invalid_request("expected_trip_trade_version must be an integer")

    if t["state"] != "APPROVED":
        raise invalid_state(f"Cannot execute TripTrade in state {t['state']!r}")

    # OCC.
    if expected != t["version"]:
        raise stale_version("expected_trip_trade_version does not match current version")

    a_init = db.assignments.get(t["initiator_assignment_id"])
    a_cnt = db.assignments.get(t["counterparty_assignment_id"])
    if a_init is None or a_cnt is None:
        raise not_found("Referenced Assignment missing")
    if a_init["state"] not in {"SCHEDULED", "CONFIRMED"} or a_cnt["state"] not in {"SCHEDULED", "CONFIRMED"}:
        raise cross_entity_state("Both Assignments must be SCHEDULED or CONFIRMED")

    # Cascade swap.
    a_init["state"] = "RELEASED"
    touch(a_init)
    a_cnt["state"] = "RELEASED"
    touch(a_cnt)
    new_for_a = {
        "pairing_id": a_cnt["pairing_id"],
        "crew_member_id": t["initiator_id"],
        "seat": a_cnt["seat"],
        "source": "TRIP_TRADE",
        "state": "CONFIRMED",
        "actual_duty_start_utc": None,
        "actual_duty_end_utc": None,
        "flight_minutes_credited": 0,
        "duty_minutes_credited": 0,
    }
    new_for_b = {
        "pairing_id": a_init["pairing_id"],
        "crew_member_id": t["counterparty_id"],
        "seat": a_init["seat"],
        "source": "TRIP_TRADE",
        "state": "CONFIRMED",
        "actual_duty_start_utc": None,
        "actual_duty_end_utc": None,
        "flight_minutes_credited": 0,
        "duty_minutes_credited": 0,
    }
    stamp_new(new_for_a)
    stamp_new(new_for_b)
    db.assignments[new_for_a["id"]] = new_for_a
    db.assignments[new_for_b["id"]] = new_for_b
    t["state"] = "EXECUTED"
    touch(t)
    return success(t, status=200)
