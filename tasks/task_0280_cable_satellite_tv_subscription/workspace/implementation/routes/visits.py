"""Service-visit endpoints (PRD §3.9) and the test-driving clock (PRD §2.12)."""

from datetime import timedelta

from flask import Blueprint, request

import db
import errors
from clock import current_visit_clock, parse_iso8601, set_test_clock, to_iso8601
from middleware import get_identity, require_role
from response import object_response
from services import common
from services import calculations as calc

bp = Blueprint("visits", __name__)

TECH_BUFFER_MIN = 60
NON_TERMINAL = ("SCHEDULED", "DISPATCHED")


# ---------------------------------------------------------------------------
# Test-driving clock
# ---------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = get_identity()
    require_role(role, {"BillingAdmin"})
    body = common.get_json_body()
    raw = common.require_str(body, "to_iso8601")
    dt = parse_iso8601(raw)
    if dt is None:
        raise errors.validation("to_iso8601 must be a valid ISO 8601 timestamp")
    set_test_clock(dt)
    return object_response({"current_utc": to_iso8601(dt)}, 200)


# ---------------------------------------------------------------------------
# Schedule a visit
# ---------------------------------------------------------------------------
@bp.route("/accounts/<account_id>/service-visits", methods=["POST"])
def schedule_visit(account_id):
    user_id, role = get_identity()
    require_role(role, {"CustomerServiceAgent", "Subscriber"})
    acc = common.resolve_account(role, user_id, account_id)
    body = common.get_json_body()
    visit_type = common.require_str(body, "visit_type")
    if visit_type not in ("INSTALL", "SERVICE"):
        raise errors.validation("visit_type must be INSTALL or SERVICE")
    window_start_raw = common.require_str(body, "window_start")
    window_end_raw = common.require_str(body, "window_end")
    technician_id = common.require_str(body, "technician_id")
    # Technician must exist and be active (catalog reference).
    common.get_active_catalog(db.technicians, technician_id)

    start = parse_iso8601(window_start_raw)
    end = parse_iso8601(window_end_raw)
    if start is None or end is None:
        raise errors.invalid_visit_window("window_start/window_end must be ISO 8601")

    now = current_visit_clock()
    # Window must be well-formed and in the future.
    if not (start < end) or not (start > now):
        raise errors.invalid_visit_window()

    # Technician double-book: half-open [start, end) overlap with same tech's
    # non-terminal visits.
    for v in db.service_visits.values():
        if v["status"] not in NON_TERMINAL:
            continue
        if v["technician_id"] != technician_id:
            continue
        ex_start = parse_iso8601(v["window_start"])
        ex_end = parse_iso8601(v["window_end"])
        if start < ex_end and ex_start < end:  # strictly-positive overlap
            raise errors.technician_double_booked()

    # Account conflict: same account non-terminal visit, closed interval plus
    # a >= 60-minute buffer; gap < 60 min rejected.
    buffer = timedelta(minutes=TECH_BUFFER_MIN)
    for v in db.service_visits.values():
        if v["status"] not in NON_TERMINAL:
            continue
        if v["account_id"] != account_id:
            continue
        ex_start = parse_iso8601(v["window_start"])
        ex_end = parse_iso8601(v["window_end"])
        # Overlap or insufficient buffer: the two windows, each padded by the
        # buffer, must not intersect. Required gap >= 60 min between them.
        if start < ex_end + buffer and ex_start < end + buffer:
            raise errors.account_visit_conflict()

    created_at, updated_at, version = db.stamp_new()
    visit = {
        "id": db.new_id(),
        "account_id": account_id,
        "visit_type": visit_type,
        "window_start": window_start_raw,
        "window_end": window_end_raw,
        "technician_id": technician_id,
        "status": "SCHEDULED",
        "truck_roll_fee_cents": 0,
        "outcome_note": None,
        "billed_cycle_index": None,
        "created_at": created_at,
        "updated_at": updated_at,
        "version": version,
    }
    db.service_visits[visit["id"]] = visit
    return object_response(_view(visit), 201)


@bp.route("/accounts/<account_id>/service-visits", methods=["GET"])
def list_account_visits(account_id):
    user_id, role = get_identity()
    require_role(role, {"BillingAdmin", "CustomerServiceAgent", "Subscriber", "FieldTechnician"})
    common.resolve_account(role, user_id, account_id)
    items = [v for v in db.service_visits.values() if v["account_id"] == account_id]
    status = request.args.get("status")
    if status is not None:
        items = [v for v in items if v["status"] == status]
    technician_id = request.args.get("technician_id")
    if technician_id is not None:
        items = [v for v in items if v["technician_id"] == technician_id]
    return common.paginate_and_respond([_view(v) for v in items])


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------
def _get_visit(account_id, vid):
    common.get_account_or_404(account_id)
    visit = db.service_visits.get(vid)
    if visit is None or visit["account_id"] != account_id:
        raise errors.subresource_not_found("Service visit not found under account")
    return visit


def _tech_ownership(user_id, visit):
    if visit["technician_id"] != user_id:
        raise errors.not_resource_owner()


@bp.route("/accounts/<account_id>/service-visits/<vid>/dispatch", methods=["POST"])
def dispatch_visit(account_id, vid):
    user_id, role = get_identity()
    require_role(role, {"FieldTechnician"})
    visit = _get_visit(account_id, vid)
    _tech_ownership(user_id, visit)
    if visit["status"] != "SCHEDULED":
        raise errors.invalid_state("Visit must be SCHEDULED to dispatch")
    visit["status"] = "DISPATCHED"
    db.touch(visit)
    return object_response(_view(visit), 200)


@bp.route("/accounts/<account_id>/service-visits/<vid>/complete", methods=["POST"])
def complete_visit(account_id, vid):
    user_id, role = get_identity()
    require_role(role, {"FieldTechnician"})
    visit = _get_visit(account_id, vid)
    _tech_ownership(user_id, visit)
    if visit["status"] != "DISPATCHED":
        raise errors.invalid_state("Visit must be DISPATCHED to complete")
    body = common.get_json_body()
    outcome_note = common.require_str(body, "outcome_note")
    visit["status"] = "COMPLETED"
    visit["outcome_note"] = outcome_note
    visit["truck_roll_fee_cents"] = calc.visit_fee_on_complete(visit["visit_type"])
    visit["billed_cycle_index"] = db.accounts[account_id]["tenure_months"]
    db.touch(visit)
    return object_response(_view(visit), 200)


@bp.route("/accounts/<account_id>/service-visits/<vid>/no-show", methods=["POST"])
def no_show_visit(account_id, vid):
    user_id, role = get_identity()
    require_role(role, {"FieldTechnician"})
    visit = _get_visit(account_id, vid)
    _tech_ownership(user_id, visit)
    if visit["status"] != "DISPATCHED":
        raise errors.invalid_state("Visit must be DISPATCHED to mark no-show")
    visit["status"] = "NO_SHOW"
    visit["truck_roll_fee_cents"] = calc.visit_fee_on_no_show()
    visit["billed_cycle_index"] = db.accounts[account_id]["tenure_months"]
    db.touch(visit)
    return object_response(_view(visit), 200)


@bp.route("/accounts/<account_id>/service-visits/<vid>/cancel", methods=["POST"])
def cancel_visit(account_id, vid):
    user_id, role = get_identity()
    require_role(role, {"CustomerServiceAgent", "Subscriber"})
    common.resolve_account(role, user_id, account_id)
    visit = db.service_visits.get(vid)
    if visit is None or visit["account_id"] != account_id:
        raise errors.subresource_not_found("Service visit not found under account")
    if visit["status"] != "SCHEDULED":
        raise errors.invalid_state("Visit must be SCHEDULED to cancel")
    visit["status"] = "CANCELLED"
    visit["truck_roll_fee_cents"] = 0
    db.touch(visit)
    return object_response(_view(visit), 200)


def _view(visit):
    return {k: v for k, v in visit.items() if k != "billed_cycle_index"}
