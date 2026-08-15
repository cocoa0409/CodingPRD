"""PreclearanceRequest endpoints: submit (gauntlet), review, decision, withdraw."""
from flask import Blueprint, g, request

from db import STORE
from errors import (err, ERR_COMPLIANCE_HOLD, ERR_INVALID_STATE,
                    ERR_OVERLAPPING_APPROVAL, ERR_POLICY_ACK_REQUIRED,
                    ERR_QUANTITY_EXCEEDS_APPROVED, ERR_SECURITY_RESTRICTED,
                    ERR_SELF_ACTION_FORBIDDEN, ERR_STALE_VERSION,
                    ERR_TRADE_IN_BLACKOUT, ERR_TRAINING_OVERDUE)
from middleware import require_roles, insider_owns
from response import success, paginate
from services.core import (new_entity, touch, serialize, sort_created, get_or_404,
                           compute_flags, ticker_restricted, exception_bypass,
                           blackout_blocked, TRADE_SIDES)
from util import Body, fmt_ts, dec

bp = Blueprint("preclearance", __name__)

READ_ROLES = ("Insider", "ComplianceOfficer", "LegalAdmin")


def _check_submission_screens(person, ticker, proposed_dt, quantity, exception):
    """The submission gauntlet (PRD section 3.4, ladder order): restricted ->
    hold -> blackout (with exception bypass) -> policy ack -> training.
    Overlap / quantity-cap checks run only at submission. Checks whose inputs
    are missing (malformed body) are skipped so the pending schema error can
    surface only as the sole failure."""
    if ticker is not None and ticker_restricted(ticker):
        raise err(ERR_SECURITY_RESTRICTED, "ticker has an ACTIVE RestrictedListEntry")
    ack = training = None
    if person is not None:
        ack, training, hold = compute_flags(person)
        if hold:
            raise err(ERR_COMPLIANCE_HOLD, "subject has an open ViolationCase")
    if ticker is not None and proposed_dt is not None \
            and blackout_blocked(ticker, proposed_dt) \
            and not _bypass_for(ticker, quantity, exception):
        raise err(ERR_TRADE_IN_BLACKOUT,
                  "proposed trade date is covered by a SCHEDULED/ACTIVE blackout window")
    if person is not None:
        if not ack:
            raise err(ERR_POLICY_ACK_REQUIRED, "policy acknowledgment is not current")
        if not training:
            raise err(ERR_TRAINING_OVERDUE, "annual training is not current")


def _bypass_for(ticker, quantity, exception):
    if exception is None:
        return False
    if exception["status"] != "APPROVED" or exception["security_ticker"] != ticker:
        return False
    if quantity is None:
        return True
    return dec(exception["quantity"]) >= dec(quantity)


@bp.post("/preclearance-requests")
def create_request():
    require_roles("Insider")
    body = Body()
    person_id = body.get_str("covered_person_id")
    ticker = body.get_str("security_ticker")
    side = body.get_enum("trade_side", TRADE_SIDES)
    quantity = body.get_num("quantity", positive=True, max_dp=4)
    proposed_dt = body.get_dt("proposed_trade_date")
    exception_id = body.get_str("exception_id", required=False)

    # Authorization: an Insider submits only for themselves (ladder step 2).
    if person_id is not None:
        insider_owns(person_id)
    # Existence of body foreign keys (step 4).
    person = None
    if person_id is not None:
        person = get_or_404("covered_persons", person_id, "covered person")
    exception = None
    if exception_id is not None:
        exception = get_or_404("exception_requests", exception_id, "exception request")
    # Business screens in ladder order.
    _check_submission_screens(person, ticker, proposed_dt, quantity, exception)
    # Overlapping approval lane (conflict check).
    if person_id is not None and ticker is not None and proposed_dt is not None:
        for r in STORE.preclearance_requests.values():
            if r["covered_person_id"] == person_id and r["security_ticker"] == ticker \
                    and r["status"] == "APPROVED" \
                    and r["_decided_dt"] <= proposed_dt <= r["_approval_valid_until_dt"]:
                raise err(ERR_OVERLAPPING_APPROVAL,
                          "proposed_trade_date falls inside an existing APPROVED approval window")
    # Exception quantity cap (only when an exception is cited).
    if exception is not None and quantity is not None \
            and dec(quantity) > dec(exception["quantity"]):
        raise err(ERR_QUANTITY_EXCEEDS_APPROVED,
                  "request quantity exceeds the exception's covered quantity")
    body.flush()
    r = new_entity()
    r.update({
        "covered_person_id": person_id,
        "security_ticker": ticker,
        "trade_side": side,
        "quantity": quantity,
        "proposed_trade_date": fmt_ts(proposed_dt),
        "exception_id": exception_id,
        "status": "SUBMITTED",
        "denial_reason": None,
        "decided_by": None,
        "decided_at": None,
        "approval_valid_until": None,
        "matched_quantity": 0,
        "remaining_quantity": None,
        "_proposed_dt": proposed_dt,
        "_decided_dt": None,
        "_approval_valid_until_dt": None,
    })
    STORE.preclearance_requests[r["id"]] = r
    return success(serialize(r), 201)


@bp.get("/preclearance-requests/<rid>")
def get_request(rid):
    require_roles(*READ_ROLES)
    r = get_or_404("preclearance_requests", rid, "preclearance request")
    insider_owns(r["covered_person_id"])
    return success(serialize(r))


@bp.get("/preclearance-requests")
def list_requests():
    require_roles(*READ_ROLES)
    items = sort_created(STORE.preclearance_requests.values())
    person_id = request.args.get("covered_person_id")
    status = request.args.get("status")
    if person_id is not None:
        items = [r for r in items if r["covered_person_id"] == person_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return paginate([serialize(r) for r in items])


@bp.post("/preclearance-requests/<rid>/review")
def review_request(rid):
    require_roles("ComplianceOfficer")
    r = get_or_404("preclearance_requests", rid, "preclearance request")
    if r["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "only a SUBMITTED request can move to UNDER_REVIEW")
    r["status"] = "UNDER_REVIEW"
    touch(r)
    return success(serialize(r))


@bp.post("/preclearance-requests/<rid>/decision")
def decide_request(rid):
    require_roles("ComplianceOfficer")
    r = get_or_404("preclearance_requests", rid, "preclearance request")
    # State validity, then OCC (rides with the state group per PRD 2.9),
    # then segregation of duties, then the APPROVE-only business screens.
    if r["status"] != "UNDER_REVIEW":
        raise err(ERR_INVALID_STATE, "only an UNDER_REVIEW request can be decided")
    body = Body()
    outcome = body.get_enum("outcome", {"APPROVE", "DENY"})
    body.get_enum("denial_reason", {"RESTRICTED_LIST", "OFFICER_DISCRETION"}, required=False)
    expected = body.get_int("expected_preclearance_version")
    if expected is not None and expected != r["version"]:
        raise err(ERR_STALE_VERSION,
                  "expected_preclearance_version does not match the request's current version")
    if g.user_id == r["covered_person_id"]:
        raise err(ERR_SELF_ACTION_FORBIDDEN, "an officer may not decide their own request")
    if outcome == "APPROVE":
        if ticker_restricted(r["security_ticker"]):
            raise err(ERR_SECURITY_RESTRICTED, "ticker has an ACTIVE RestrictedListEntry")
        if blackout_blocked(r["security_ticker"], r["_proposed_dt"]) and not exception_bypass(r):
            raise err(ERR_TRADE_IN_BLACKOUT,
                      "proposed trade date is covered by a SCHEDULED/ACTIVE blackout window")
    body.flush()
    now = STORE.clock
    r["decided_by"] = g.user_id
    r["decided_at"] = fmt_ts(now)
    r["_decided_dt"] = now
    if outcome == "APPROVE":
        from datetime import timedelta
        valid_until = now + timedelta(hours=48)
        r["status"] = "APPROVED"
        r["approval_valid_until"] = fmt_ts(valid_until)
        r["_approval_valid_until_dt"] = valid_until
        r["remaining_quantity"] = r["quantity"]
    else:
        r["status"] = "DENIED"
        r["denial_reason"] = "OFFICER_DISCRETION"
    touch(r)
    return success(serialize(r))


@bp.post("/preclearance-requests/<rid>/withdraw")
def withdraw_request(rid):
    require_roles("Insider")
    r = get_or_404("preclearance_requests", rid, "preclearance request")
    insider_owns(r["covered_person_id"])
    if r["status"] not in ("SUBMITTED", "UNDER_REVIEW"):
        raise err(ERR_INVALID_STATE, "only a SUBMITTED or UNDER_REVIEW request can be withdrawn")
    r["status"] = "WITHDRAWN"
    touch(r)
    return success(serialize(r))


@bp.get("/preclearance-requests/<rid>/trade-confirmations")
def request_confirmations(rid):
    require_roles(*READ_ROLES)
    r = get_or_404("preclearance_requests", rid, "preclearance request")
    insider_owns(r["covered_person_id"])
    items = [c for c in sort_created(STORE.trade_confirmations.values())
             if c["match_preclearance_id"] == rid]
    return paginate([serialize(c) for c in items])
