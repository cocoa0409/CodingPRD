"""Transfer partner agreements and promotional bonus events (PRD 3.7)."""

from flask import Blueprint, request

from auth import caller_id, endpoint, require_sod
from core import (
    DB,
    add_hours,
    clock_iso,
    fmt_dt,
    must_find,
    new_row,
    ok,
    ordered,
    parse_dt,
    store,
    touch,
)
from errors import ApiError, invalid
from rhelp import require_agreement_active, require_state
from shapes import body, req_dt, req_int, req_string
from views import ADMIN, APPROVER, OPS_CARD, listing, plain

bp = Blueprint("agreements", __name__)

RESERVED_STATUSES = ("PENDING_APPROVAL", "ACTIVE", "SUSPENDED")
LIVE_EVENT_STATUSES = ("SCHEDULED", "RUNNING")


@bp.post("/partner-agreements")
@endpoint(ADMIN)
def create_agreement():
    data = body()
    row = store(
        "agreements",
        new_row(
            "agreements",
            {
                "partner_name": req_string(data, "partner_name"),
                "partner_program_code": req_string(data, "partner_program_code"),
                "ratio_points_out": req_int(
                    data, "ratio_points_out", minimum=1, multiple_of=1000
                ),
                "ratio_partner_units_in": req_int(data, "ratio_partner_units_in", minimum=1),
                "min_transfer_points": req_int(data, "min_transfer_points", minimum=1),
                "transfer_increment_points": req_int(
                    data, "transfer_increment_points", minimum=1
                ),
                "transfer_latency_hours": req_int(data, "transfer_latency_hours", minimum=0),
                "reversal_window_hours": req_int(data, "reversal_window_hours", minimum=0),
                "settlement_cost_cents_per_1k": req_int(
                    data, "settlement_cost_cents_per_1k", minimum=1
                ),
                "status": "DRAFT",
                "submitted_by_user_id": None,
                "approved_by_user_id": None,
                "activated_at": None,
                "suspension_reason": None,
            },
        ),
    )
    return ok(plain(row), 201)


@bp.get("/partner-agreements/<agreement_id>")
@endpoint(OPS_CARD)
def read_agreement(agreement_id):
    return ok(plain(must_find("agreements", agreement_id)))


@bp.get("/partner-agreements")
@endpoint(OPS_CARD)
def list_agreements():
    args = request.args
    filters = {
        "status": args.get("status"),
        "partner_program_code": args.get("partner_program_code"),
    }
    return listing("agreements", args, filters)


@bp.post("/partner-agreements/<agreement_id>/submit")
@endpoint(ADMIN)
def submit_agreement(agreement_id):
    agreement = must_find("agreements", agreement_id)
    require_state(agreement, ("DRAFT",))
    for other in DB["agreements"].values():
        if other["id"] == agreement_id:
            continue
        if other["partner_program_code"] != agreement["partner_program_code"]:
            continue
        if other["status"] in RESERVED_STATUSES:
            raise ApiError(
                "ERR_DUPLICATE_PROGRAM_CODE",
                "Partner program code '%s' is already reserved."
                % agreement["partner_program_code"],
            )
    agreement["status"] = "PENDING_APPROVAL"
    agreement["submitted_by_user_id"] = caller_id()
    touch(agreement)
    return ok(plain(agreement))


@bp.post("/partner-agreements/<agreement_id>/revise")
@endpoint(APPROVER)
def revise_agreement(agreement_id):
    agreement = must_find("agreements", agreement_id)
    require_state(agreement, ("PENDING_APPROVAL",))
    agreement["status"] = "DRAFT"
    agreement["submitted_by_user_id"] = None
    touch(agreement)
    return ok(plain(agreement))


@bp.post("/partner-agreements/<agreement_id>/approve")
@endpoint(APPROVER)
def approve_agreement(agreement_id):
    agreement = must_find("agreements", agreement_id)
    require_sod(agreement["submitted_by_user_id"])
    require_state(agreement, ("PENDING_APPROVAL",))
    agreement["status"] = "ACTIVE"
    agreement["approved_by_user_id"] = caller_id()
    agreement["activated_at"] = clock_iso()
    touch(agreement)
    return ok(plain(agreement))


@bp.post("/partner-agreements/<agreement_id>/suspend")
@endpoint(ADMIN)
def suspend_agreement(agreement_id):
    agreement = must_find("agreements", agreement_id)
    reason = req_string(body(), "suspension_reason")
    require_state(agreement, ("ACTIVE",))
    agreement["status"] = "SUSPENDED"
    agreement["suspension_reason"] = reason
    touch(agreement)
    events = ordered(
        "bonus_events",
        [
            e
            for e in DB["bonus_events"].values()
            if e["partner_agreement_id"] == agreement_id and e["status"] in LIVE_EVENT_STATUSES
        ],
    )
    for event in events:
        event["status"] = "CANCELLED"
        event["cancelled_reason"] = "AGREEMENT_SUSPENDED"
        touch(event)
    return ok(plain(agreement))


@bp.post("/partner-agreements/<agreement_id>/reinstate")
@endpoint(APPROVER)
def reinstate_agreement(agreement_id):
    agreement = must_find("agreements", agreement_id)
    require_sod(agreement["submitted_by_user_id"])
    require_state(agreement, ("SUSPENDED",))
    agreement["status"] = "ACTIVE"
    agreement["suspension_reason"] = None
    agreement["activated_at"] = clock_iso()
    touch(agreement)
    return ok(plain(agreement))


@bp.post("/partner-agreements/<agreement_id>/terminate")
@endpoint(APPROVER)
def terminate_agreement(agreement_id):
    agreement = must_find("agreements", agreement_id)
    require_state(agreement, ("SUSPENDED",))
    for transfer in DB["transfer_requests"].values():
        if transfer["partner_agreement_id"] != agreement_id:
            continue
        if transfer["status"] in ("SUBMITTED", "QUEUED", "HELD"):
            raise ApiError(
                "ERR_AGREEMENT_HAS_IN_FLIGHT_TRANSFERS",
                "Agreement '%s' still has transfers in flight." % agreement_id,
            )
    agreement["status"] = "TERMINATED"
    touch(agreement)
    return ok(plain(agreement))


# --------------------------------------------------------------------------
# promotional bonus events
# --------------------------------------------------------------------------
@bp.post("/bonus-events")
@endpoint(ADMIN)
def create_event():
    data = body()
    agreement_id = data.get("partner_agreement_id")
    if not isinstance(agreement_id, str) or agreement_id.strip() == "":
        raise invalid("'partner_agreement_id' is required")
    agreement = must_find("agreements", agreement_id)

    event_code = req_string(data, "event_code")
    bonus_bps = req_int(data, "bonus_bps", minimum=1, maximum=10000)
    window_start = req_dt(data, "window_start")
    window_end = req_dt(data, "window_end")
    if window_end <= window_start:
        raise invalid("'window_end' must be strictly later than 'window_start'")
    cap_points_per_account = req_int(data, "cap_points_per_account", minimum=1)

    require_agreement_active(agreement)

    for other in DB["bonus_events"].values():
        if other["partner_agreement_id"] != agreement_id:
            continue
        if other["status"] not in LIVE_EVENT_STATUSES:
            continue
        other_start = parse_dt(other["window_start"])
        other_end = parse_dt(other["window_end"])
        separated = window_start > add_hours(other_end, 24) or window_end < add_hours(
            other_start, -24
        )
        if not separated:
            raise ApiError(
                "ERR_BONUS_EVENT_WINDOW_CONFLICT",
                "Promotional window is not separated from event '%s' by a full day."
                % other["id"],
            )

    for other in DB["bonus_events"].values():
        if other["event_code"] == event_code:
            raise ApiError(
                "ERR_DUPLICATE_PROGRAM_CODE",
                "Event code '%s' is already in use." % event_code,
            )

    row = store(
        "bonus_events",
        new_row(
            "bonus_events",
            {
                "partner_agreement_id": agreement_id,
                "event_code": event_code,
                "bonus_bps": bonus_bps,
                "window_start": fmt_dt(window_start),
                "window_end": fmt_dt(window_end),
                "cap_points_per_account": cap_points_per_account,
                "status": "SCHEDULED",
                "opened_at": None,
                "closed_at": None,
                "cancelled_reason": None,
            },
        ),
    )
    return ok(plain(row), 201)


@bp.get("/bonus-events/<event_id>")
@endpoint(OPS_CARD)
def read_event(event_id):
    return ok(plain(must_find("bonus_events", event_id)))


@bp.get("/bonus-events")
@endpoint(OPS_CARD)
def list_events():
    args = request.args
    filters = {
        "partner_agreement_id": args.get("partner_agreement_id"),
        "status": args.get("status"),
        "event_code": args.get("event_code"),
    }
    return listing("bonus_events", args, filters)


@bp.post("/bonus-events/<event_id>/cancel")
@endpoint(ADMIN)
def cancel_event(event_id):
    event = must_find("bonus_events", event_id)
    reason = req_string(body(), "cancelled_reason")
    require_state(event, LIVE_EVENT_STATUSES)
    event["status"] = "CANCELLED"
    event["cancelled_reason"] = reason
    touch(event)
    return ok(plain(event))
