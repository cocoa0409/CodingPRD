"""Distribution request endpoints."""
from flask import Blueprint, request

import db
from errors import (
    ERR_PLAN_NOT_ACTIVE,
    ERR_ACCOUNT_CLOSED,
    ERR_EVENT_TYPE_NOT_PERMITTED,
    ERR_EVENT_NOT_CONFIRMED,
    ERR_DISTRIBUTION_STATE_INVALID,
    ERR_DISTRIBUTION_NOT_PAYABLE,
    ERR_PLAN_DOCUMENT_LAPSED,
    ERR_INSUFFICIENT_VESTED,
    ERR_EXCEEDS_EMERGENCY,
    ERR_CROSS_PLAN_REFERENCE,
    raise_err,
)
from middleware import user_context, require_role, check_participant_ownership
from response import ok_object
from routes.plans import _list_response
from services.core import (
    body,
    req_string,
    req_enum,
    opt_int,
    opt_date,
    req_date,
    get_or_404,
    stamp_new,
    touch,
    recompute_account_balances,
    compute_scheduled_payment_date,
    account_close_cascade,
    recompute_trust,
)
from util import CLOCK, fmt_date, parse_date

bp = Blueprint("distribution_requests", __name__)

EVENT_TYPES = {
    "SEPARATION",
    "DEATH",
    "DISABILITY",
    "FIXED_TIME",
    "UNFORESEEABLE_EMERGENCY",
    "CHANGE_IN_CONTROL",
}


def request_view(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "account_id": r["account_id"],
        "participant_id": r["participant_id"],
        "separation_case_id": r["separation_case_id"],
        "change_in_control_event_id": r["change_in_control_event_id"],
        "event_type": r["event_type"],
        "requested_amount_cents": r["requested_amount_cents"],
        "fixed_date": r["fixed_date"],
        "emergency_need_cents": r["emergency_need_cents"],
        "locked_amount_cents": r["locked_amount_cents"],
        "scheduled_payment_date": r["scheduled_payment_date"],
        "status": r["status"],
        "denial_reason": r["denial_reason"],
        "verified_at": r["verified_at"],
        "paid_at": r["paid_at"],
    }


def make_request(account_id, participant_id, event_type, requested, fixed_date, emergency_need, case_id, cic_id, status="REQUESTED", verified_at=None):
    req = stamp_new(
        {
            "account_id": account_id,
            "participant_id": participant_id,
            "separation_case_id": case_id,
            "change_in_control_event_id": cic_id,
            "event_type": event_type,
            "requested_amount_cents": requested,
            "fixed_date": fixed_date,
            "emergency_need_cents": emergency_need,
            "locked_amount_cents": None,
            "scheduled_payment_date": None,
            "status": status,
            "denial_reason": None,
            "verified_at": verified_at,
            "paid_at": None,
        }
    )
    db.distribution_requests[req["id"]] = req
    return req


@bp.post("/api/distribution-requests")
def create_request():
    data = body()
    from errors import ERR_INVALID_REQUEST, ERR_INVALID_DATE_RANGE

    account_id = data.get("account_id")
    if not isinstance(account_id, str) or not account_id:
        raise_err(ERR_INVALID_REQUEST, "account_id is required and must be a string")
    event_type = req_enum(data, "event_type", EVENT_TYPES)
    requested = opt_int(data, "requested_amount_cents", lo=1)
    fixed_date = opt_date(data, "fixed_date")
    emergency_need = opt_int(data, "emergency_need_cents", lo=1)
    case_id = data.get("separation_case_id")
    cic_id = data.get("change_in_control_event_id")
    if case_id is not None and (not isinstance(case_id, str) or not case_id):
        raise_err(ERR_INVALID_REQUEST, "separation_case_id must be a string")
    if cic_id is not None and (not isinstance(cic_id, str) or not cic_id):
        raise_err(ERR_INVALID_REQUEST, "change_in_control_event_id must be a string")

    # Type-driven linkage / money field shape
    if event_type == "SEPARATION" and case_id is None:
        raise_err(ERR_INVALID_REQUEST, "separation_case_id is required for SEPARATION")
    if event_type != "SEPARATION" and case_id is not None:
        raise_err(ERR_INVALID_REQUEST, "separation_case_id must be null for non-SEPARATION events")
    if event_type == "CHANGE_IN_CONTROL" and cic_id is None:
        raise_err(ERR_INVALID_REQUEST, "change_in_control_event_id is required for CHANGE_IN_CONTROL")
    if event_type != "CHANGE_IN_CONTROL" and cic_id is not None:
        raise_err(ERR_INVALID_REQUEST, "change_in_control_event_id must be null for non-CIC events")
    if event_type == "UNFORESEEABLE_EMERGENCY":
        if requested is None:
            raise_err(ERR_INVALID_REQUEST, "requested_amount_cents is required for UNFORESEEABLE_EMERGENCY")
        if emergency_need is None:
            raise_err(ERR_INVALID_REQUEST, "emergency_need_cents is required for UNFORESEEABLE_EMERGENCY")
    else:
        if emergency_need is not None:
            raise_err(ERR_INVALID_REQUEST, "emergency_need_cents must be null for this event type")
    if event_type == "FIXED_TIME":
        if fixed_date is None:
            raise_err(ERR_INVALID_REQUEST, "fixed_date is required for FIXED_TIME")
        if fixed_date <= CLOCK.date():
            raise_err(ERR_INVALID_DATE_RANGE, "fixed_date must fall after the creation clock date")
    else:
        if fixed_date is not None:
            raise_err(ERR_INVALID_REQUEST, "fixed_date must be null for this event type")

    user_id, role = user_context()
    require_role(role, {"Participant"})

    account = get_or_404(db.accounts, account_id, "Account")
    check_participant_ownership(user_id, role, account["participant_id"])
    plan = db.plans[account["plan_id"]]

    if plan["status"] != "ACTIVE":
        raise_err(ERR_PLAN_NOT_ACTIVE, "Plan must be ACTIVE to create a distribution request")
    if account["status"] == "CLOSED":
        raise_err(ERR_ACCOUNT_CLOSED, "Account is CLOSED")

    # Body-referenced link existence
    case = None
    if case_id is not None:
        case = get_or_404(db.separation_cases, case_id, "SeparationCase")
    cic = None
    if cic_id is not None:
        cic = get_or_404(db.change_in_control_events, cic_id, "ChangeInControlEvent")

    # Event type permitted
    if event_type not in plan["distribution_events_allowed"]:
        raise_err(ERR_EVENT_TYPE_NOT_PERMITTED, "event_type is not permitted by the plan")

    # Cross-aggregate integrity
    if case is not None and case["participant_id"] != account["participant_id"]:
        raise_err(ERR_CROSS_PLAN_REFERENCE, "separation_case does not belong to the account's participant")
    if cic is not None and cic["plan_id"] != account["plan_id"]:
        raise_err(ERR_CROSS_PLAN_REFERENCE, "change_in_control_event does not belong to the account's plan")

    # Fiscal: requested <= vested balance
    recompute_account_balances(account)
    if requested is not None and requested > account["vested_balance_cents"]:
        raise_err(ERR_INSUFFICIENT_VESTED, "requested_amount_cents exceeds the vested balance")

    req = make_request(
        account_id=account_id,
        participant_id=account["participant_id"],
        event_type=event_type,
        requested=requested,
        fixed_date=fmt_date(fixed_date) if fixed_date else None,
        emergency_need=emergency_need,
        case_id=case_id,
        cic_id=cic_id,
    )
    return ok_object(request_view(req), 201)


@bp.get("/api/distribution-requests")
def list_requests():
    user_context()
    items = list(db.distribution_requests.values())
    for f in ("account_id", "participant_id", "separation_case_id", "change_in_control_event_id"):
        v = request.args.get(f)
        if v is not None:
            items = [r for r in items if r[f] == v]
    return _list_response([request_view(r) for r in items], request.args)


@bp.get("/api/distribution-requests/<requestId>")
def get_request(requestId):
    user_context()
    r = get_or_404(db.distribution_requests, requestId, "DistributionRequest")
    return ok_object(request_view(r))


@bp.post("/api/distribution-requests/<requestId>/verify-event")
def verify_event(requestId):
    body()
    user_id, role = user_context()
    require_role(role, {"ComplianceOfficer"})
    req = get_or_404(db.distribution_requests, requestId, "DistributionRequest")

    if req["status"] != "REQUESTED":
        raise_err(ERR_DISTRIBUTION_STATE_INVALID, "verify-event requires REQUESTED")

    account = db.accounts[req["account_id"]]
    participant = db.participants[req["participant_id"]]
    et = req["event_type"]

    if et == "SEPARATION":
        case = db.separation_cases.get(req["separation_case_id"])
        if case is None or case["status"] != "DETERMINED_SEPARATED" or case["participant_id"] != account["participant_id"]:
            raise_err(ERR_EVENT_NOT_CONFIRMED, "Linked separation case is not DETERMINED_SEPARATED for this participant")
    elif et == "CHANGE_IN_CONTROL":
        cic = db.change_in_control_events.get(req["change_in_control_event_id"])
        if cic is None or cic["status"] != "VERIFIED" or cic["plan_id"] != account["plan_id"]:
            raise_err(ERR_EVENT_NOT_CONFIRMED, "Linked change-in-control event is not VERIFIED for this plan")
    elif et == "DEATH":
        if participant["status"] != "DECEASED":
            raise_err(ERR_EVENT_NOT_CONFIRMED, "Participant is not DECEASED")
    elif et == "DISABILITY":
        if participant["status"] != "DISABLED":
            raise_err(ERR_EVENT_NOT_CONFIRMED, "Participant is not DISABLED")
    elif et == "FIXED_TIME":
        pass  # always verifiable
    elif et == "UNFORESEEABLE_EMERGENCY":
        if req["requested_amount_cents"] > req["emergency_need_cents"]:
            raise_err(ERR_EXCEEDS_EMERGENCY, "Requested amount exceeds the documented emergency need")

    req["status"] = "EVENT_VERIFIED"
    req["verified_at"] = fmt_date(CLOCK.date())
    touch(req)
    return ok_object(request_view(req))


@bp.post("/api/distribution-requests/<requestId>/schedule")
def schedule_request(requestId):
    body()
    user_id, role = user_context()
    require_role(role, {"BenefitsAdministrator"})
    req = get_or_404(db.distribution_requests, requestId, "DistributionRequest")

    if req["status"] != "EVENT_VERIFIED":
        raise_err(ERR_DISTRIBUTION_STATE_INVALID, "schedule requires EVENT_VERIFIED")

    account = db.accounts[req["account_id"]]
    if account["status"] not in ("ACTIVE", "FLAGGED_FOR_INCLUSION"):
        raise_err(ERR_ACCOUNT_CLOSED, "Account is CLOSED")
    recompute_account_balances(account)
    vested = account["vested_balance_cents"]
    if vested <= 0:
        raise_err(ERR_INSUFFICIENT_VESTED, "Vested balance must be positive to schedule")

    requested = req["requested_amount_cents"]
    req["locked_amount_cents"] = min(requested if requested is not None else vested, vested)
    req["scheduled_payment_date"] = fmt_date(compute_scheduled_payment_date(req))
    req["status"] = "SCHEDULED"
    touch(req)
    return ok_object(request_view(req))


@bp.post("/api/distribution-requests/<requestId>/pay")
def pay_request(requestId):
    body()
    user_id, role = user_context()
    require_role(role, {"BenefitsAdministrator"})
    req = get_or_404(db.distribution_requests, requestId, "DistributionRequest")

    if req["status"] != "PAYABLE":
        raise_err(ERR_DISTRIBUTION_NOT_PAYABLE, "pay requires PAYABLE")

    account = db.accounts[req["account_id"]]
    plan = db.plans[account["plan_id"]]
    if plan["document_posture"] == "LAPSED_FAILURE":
        raise_err(ERR_PLAN_DOCUMENT_LAPSED, "Plan document posture is LAPSED_FAILURE")

    recompute_account_balances(account)
    if account["settled_balance_cents"] < req["locked_amount_cents"]:
        raise_err(ERR_INSUFFICIENT_VESTED, "Settled balance does not cover the locked amount")

    # Cascade link 1: DISTRIBUTION_DEBIT
    ts = CLOCK.stamp()
    entry = {
        "id": db.new_id(),
        "created_at": ts,
        "account_id": account["id"],
        "entry_type": "DISTRIBUTION_DEBIT",
        "amount_cents": -req["locked_amount_cents"],
        "fund_id": None,
        "crediting_run_id": None,
        "election_id": None,
        "distribution_request_id": req["id"],
        "entry_status": "POSTED",
        "entry_date": fmt_date(CLOCK.date()),
    }
    db.ledger_entries[entry["id"]] = entry

    # Cascade link 2: recompute balances
    recompute_account_balances(account)

    # Cascade link 3+4: account close cascade
    has_debit = any(
        e["account_id"] == account["id"] and e["entry_type"] == "DISTRIBUTION_DEBIT"
        for e in db.ledger_entries.values()
    )
    if account["settled_balance_cents"] == 0 and has_debit:
        account_close_cascade(account)

    # Trust drawdown
    for trust in db.rabbi_trusts.values():
        if trust["plan_id"] == plan["id"]:
            recompute_trust(trust)
            if trust["assets_cents"] > 0:
                draw = min(req["locked_amount_cents"], trust["assets_cents"])
                trust["funding_events"].append(
                    {
                        "event_type": "TRUST_DISTRIBUTION",
                        "amount_cents": -draw,
                        "recorded_at": CLOCK.stamp(),
                    }
                )
                recompute_trust(trust)
                touch(trust)

    req["status"] = "PAID"
    req["paid_at"] = CLOCK.stamp()
    touch(req)
    return ok_object(request_view(req))


@bp.post("/api/distribution-requests/<requestId>/deny")
def deny_request(requestId):
    data = body()
    reason = req_string(data, "reason")

    user_id, role = user_context()
    require_role(role, {"ComplianceOfficer"})
    req = get_or_404(db.distribution_requests, requestId, "DistributionRequest")

    if req["status"] not in ("REQUESTED", "EVENT_VERIFIED"):
        raise_err(ERR_DISTRIBUTION_STATE_INVALID, "deny requires REQUESTED or EVENT_VERIFIED")

    req["status"] = "DENIED"
    req["denial_reason"] = reason
    touch(req)
    return ok_object(request_view(req))
