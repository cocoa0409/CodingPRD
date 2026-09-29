"""Fraud cases and benefit entitlements (PRD 3.9)."""

from flask import Blueprint, request

from auth import caller_id, endpoint, require_ownership, require_sod
from core import clock_iso, find, fmt_dt, must_find, new_row, ok, store, touch
from errors import ApiError, invalid
from rhelp import require_account_open, require_not_locked, require_state
from shapes import body, opt_bool, opt_string, req_bool, req_dt, req_enum, req_enum_array, req_int, req_string
from svc_ledger import refresh_account
from svc_posture import (
    CASE_TYPES,
    SIGNAL_MEMBERS,
    compute_review_score,
    instant_score,
    recompute_posture,
    sync_risk_score,
)
from views import ADMIN, ANALYST, APPROVER, CARDHOLDER, OPS, OPS_CARD, case_view, entitlement_view, listing, plain

bp = Blueprint("fraud", __name__)

BENEFIT_TYPES = ("TRAVEL_INSURANCE", "LOUNGE_ACCESS", "BAGGAGE_FEE_CREDIT")


@bp.post("/fraud-cases")
@endpoint(ANALYST)
def create_case():
    data = body()
    account_id = data.get("account_id")
    if not isinstance(account_id, str) or account_id.strip() == "":
        raise invalid("'account_id' is required")
    account = must_find("accounts", account_id)

    case_type = req_enum(data, "case_type", CASE_TYPES)
    signals = req_enum_array(data, "signals", SIGNAL_MEMBERS)
    device_changed = req_bool(data, "device_fingerprint_changed")

    row = store(
        "fraud_cases",
        new_row(
            "fraud_cases",
            {
                "account_id": account_id,
                "case_type": case_type,
                "signals": signals,
                "device_fingerprint_changed": device_changed,
                "instant_score": instant_score(signals),
                "review_score": None,
                "risk_score": 0,
                "status": "OPEN",
                "opened_by_user_id": caller_id(),
                "reviewed_at": None,
                "resolved_by_user_id": None,
                "resolution_note": None,
            },
        ),
    )
    sync_risk_score(row)
    recompute_posture(account)
    return ok(case_view(row), 201)


@bp.get("/fraud-cases/<case_id>")
@endpoint(OPS)
def read_case(case_id):
    return ok(case_view(must_find("fraud_cases", case_id)))


@bp.get("/fraud-cases")
@endpoint(OPS)
def list_cases():
    args = request.args
    filters = {
        "account_id": args.get("account_id"),
        "case_type": args.get("case_type"),
        "status": args.get("status"),
    }
    return listing("fraud_cases", args, filters, case_view)


@bp.post("/fraud-cases/<case_id>/review")
@endpoint(ANALYST)
def review_case(case_id):
    case = must_find("fraud_cases", case_id)
    account = must_find("accounts", case["account_id"])
    require_state(case, ("OPEN",))
    case["status"] = "UNDER_REVIEW"
    case["reviewed_at"] = clock_iso()
    case["review_score"] = compute_review_score(case)
    sync_risk_score(case)
    touch(case)
    recompute_posture(account)
    return ok(case_view(case))


@bp.post("/fraud-cases/<case_id>/confirm")
@endpoint(APPROVER)
def confirm_case(case_id):
    case = must_find("fraud_cases", case_id)
    require_sod(case["opened_by_user_id"])
    account = must_find("accounts", case["account_id"])
    resolution_note = req_string(body(), "resolution_note")
    require_state(case, ("UNDER_REVIEW",))
    case["status"] = "CONFIRMED"
    case["resolution_note"] = resolution_note
    case["resolved_by_user_id"] = caller_id()
    sync_risk_score(case)
    touch(case)
    recompute_posture(account)
    refresh_account(account)
    return ok(case_view(case))


@bp.post("/fraud-cases/<case_id>/clear")
@endpoint(APPROVER)
def clear_case(case_id):
    case = must_find("fraud_cases", case_id)
    require_sod(case["opened_by_user_id"])
    account = must_find("accounts", case["account_id"])
    resolution_note = req_string(body(), "resolution_note")
    require_state(case, ("UNDER_REVIEW",))
    case["status"] = "CLEARED"
    case["resolution_note"] = resolution_note
    case["resolved_by_user_id"] = caller_id()
    sync_risk_score(case)
    touch(case)
    recompute_posture(account)
    refresh_account(account)
    return ok(case_view(case))


# --------------------------------------------------------------------------
# benefit entitlements
# --------------------------------------------------------------------------
@bp.post("/benefit-entitlements")
@endpoint(ADMIN)
def create_entitlement():
    data = body()
    account_id = data.get("account_id")
    if not isinstance(account_id, str) or account_id.strip() == "":
        raise invalid("'account_id' is required")
    account = must_find("accounts", account_id)

    benefit_type = req_enum(data, "benefit_type", BENEFIT_TYPES)
    annual_allowance = req_int(data, "annual_allowance", minimum=1)
    expires_at = req_dt(data, "expires_at")
    requires_portal_booking = opt_bool(data, "requires_portal_booking", True)
    require_account_open(account)

    row = store(
        "entitlements",
        new_row(
            "entitlements",
            {
                "account_id": account_id,
                "benefit_type": benefit_type,
                "annual_allowance": annual_allowance,
                "used_count": 0,
                "remaining_allowance": annual_allowance,
                "requires_portal_booking": requires_portal_booking,
                "status": "ACTIVE",
                "expires_at": fmt_dt(expires_at),
                "last_consumed_at": None,
                "suspension_reason": None,
            },
        ),
    )
    return ok(entitlement_view(row), 201)


@bp.get("/benefit-entitlements/<entitlement_id>")
@endpoint(OPS_CARD)
def read_entitlement(entitlement_id):
    return ok(entitlement_view(must_find("entitlements", entitlement_id)))


@bp.get("/benefit-entitlements")
@endpoint(OPS_CARD)
def list_entitlements():
    args = request.args
    filters = {
        "account_id": args.get("account_id"),
        "benefit_type": args.get("benefit_type"),
        "status": args.get("status"),
    }
    return listing("entitlements", args, filters, entitlement_view)


@bp.post("/benefit-entitlements/<entitlement_id>/consume")
@endpoint(CARDHOLDER)
def consume_entitlement(entitlement_id):
    entitlement = must_find("entitlements", entitlement_id)
    require_ownership(entitlement["account_id"])
    account = must_find("accounts", entitlement["account_id"])
    data = body()
    order_id = opt_string(data, "redemption_order_id")
    order = None
    if order_id is not None:
        order = must_find("orders", order_id)

    require_account_open(account)
    require_not_locked(account)
    if entitlement["status"] != "ACTIVE":
        raise ApiError(
            "ERR_BENEFIT_NOT_CONSUMABLE",
            "Entitlement '%s' is %s and cannot be consumed."
            % (entitlement_id, entitlement["status"]),
        )
    if entitlement["requires_portal_booking"]:
        if (
            order is None
            or order["channel"] != "PORTAL_BOOKING"
            or order["fulfillment_status"] != "TICKETED"
        ):
            raise ApiError(
                "ERR_BENEFIT_REQUIRES_TICKETED_BOOKING",
                "This benefit requires a ticketed PORTAL_BOOKING order.",
            )
    if order is not None and order["account_id"] != entitlement["account_id"]:
        raise ApiError(
            "ERR_ORDER_ACCOUNT_MISMATCH",
            "Order '%s' belongs to another account." % order["id"],
        )
    remaining = entitlement["annual_allowance"] - entitlement["used_count"]
    if remaining < 1:
        raise ApiError(
            "ERR_BENEFIT_ALLOWANCE_EXHAUSTED",
            "Entitlement '%s' has no remaining allowance." % entitlement_id,
        )

    entitlement["used_count"] = entitlement["used_count"] + 1
    entitlement["remaining_allowance"] = max(
        entitlement["annual_allowance"] - entitlement["used_count"], 0
    )
    entitlement["last_consumed_at"] = clock_iso()
    touch(entitlement)
    return ok(entitlement_view(entitlement))
