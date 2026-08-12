"""Subscription endpoints (PRD §3.2, §3.5)."""

from flask import Blueprint, request

from db import STORE
from errors import (ApiError, ERR_HOUSEHOLD_NOT_FOUND, ERR_SUBSCRIPTION_NOT_FOUND,
                    ERR_DUPLICATE_SUBSCRIPTION, ERR_ENROLLMENT_WINDOW_CLOSED,
                    ERR_PAYMENT_NOT_REQUIRED, ERR_STALE_VERSION,
                    err_invalid_request, err_invalid_state, err_not_found,
                    err_resident_not_owner, err_stale_version)
from middleware import require_roles
from response import success_list, success_object, parse_pagination
from services.core import (base_record, touch, subscription_out, zone_status,
                           compute_base_fee_cents, recompute_total_due,
                           cancel_subscription_cascade, TERMINAL_SUB_STATUSES,
                           recompute_credit_balance)
from services.validate import (require_body, check_unknown_fields, req_str, req_int,
                               opt_bool)

bp = Blueprint("subscriptions", __name__)

READ_ROLES = ("Resident", "ProgramAdmin", "BillingClerk", "RouteSupervisor")


def _get_sub_or_404(sid):
    s = STORE.subscriptions.get(sid)
    if not s:
        raise err_not_found(ERR_SUBSCRIPTION_NOT_FOUND, "Subscription not found")
    return s


@bp.post("/subscriptions")
def create_subscription():
    user_id, role = require_roles("Resident")
    data = require_body(request.get_json(silent=True))
    check_unknown_fields(data, {"household_id", "season_year", "expected_household_version"})
    household_id = req_str(data, "household_id")
    season_year = req_int(data, "season_year")
    expected_version = req_int(data, "expected_household_version")

    # Resident ownership (priority 3)
    if user_id != household_id:
        raise err_resident_not_owner()

    # Body FK existence (priority 6)
    hh = STORE.households.get(household_id)
    if not hh:
        raise err_not_found(ERR_HOUSEHOLD_NOT_FOUND, "Household not found")
    zone = STORE.zones.get(hh["zone_id"])

    # OCC (priority 7)
    if expected_version != hh["version"]:
        raise err_stale_version("expected_household_version does not match household version")

    # Uniqueness: one non-terminal subscription per (household, season_year) (priority 9)
    for s in STORE.subscriptions.values():
        if (s["household_id"] == household_id and s["season_year"] == season_year
                and s["status"] not in TERMINAL_SUB_STATUSES):
            raise ApiError(ERR_DUPLICATE_SUBSCRIPTION,
                           "Household already has a non-terminal subscription for this season_year", 409)

    # Temporal: signup only while OPEN_ENROLLMENT or IN_SEASON (priority 10)
    zs = zone_status(zone)
    if zs == "OFF_SEASON":
        raise ApiError(ERR_ENROLLMENT_WINDOW_CLOSED,
                       "Zone is OFF_SEASON; enrollment closed", 422)

    signup_date = STORE.clock_date()
    model = zone["service_model"]  # pinned snapshot
    base_fee = compute_base_fee_cents(zone, model, signup_date)

    s = base_record()
    s.update({
        "household_id": household_id,
        "season_year": season_year,
        "service_model": model,
        "status": "ACTIVE" if model == "UNIVERSAL" else "PENDING_PAYMENT",
        "base_fee_cents": base_fee,
        "cart_fees_cents": 0,
        "surcharge_cents": 0,
        "total_due_cents": base_fee,
        "paid_cents": 0,
        "strikes_this_season": 0,
        "suspended_reason": None,
    })
    STORE.subscriptions[s["id"]] = s
    # creation increments Household.version
    touch(hh)
    return success_object(subscription_out(s), 201)


@bp.get("/subscriptions")
def list_subscriptions():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(STORE.subscriptions.values())
    hid = request.args.get("household_id")
    st = request.args.get("status")
    sy = request.args.get("season_year")
    if hid is not None:
        items = [s for s in items if s["household_id"] == hid]
    if st is not None:
        items = [s for s in items if s["status"] == st]
    if sy is not None:
        try:
            syi = int(sy)
        except ValueError:
            raise err_invalid_request("season_year must be an integer")
        items = [s for s in items if s["season_year"] == syi]
    items.sort(key=lambda s: (s["created_at"], s["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([subscription_out(s) for s in page], limit, offset, total)


@bp.get("/subscriptions/<sid>")
def get_subscription(sid):
    user_id, role = require_roles(*READ_ROLES)
    s = _get_sub_or_404(sid)
    if role == "Resident" and user_id != s["household_id"]:
        raise err_resident_not_owner()
    return success_object(subscription_out(s))


@bp.post("/subscriptions/<sid>/pay")
def pay_subscription(sid):
    user_id, role = require_roles("Resident")
    s = _get_sub_or_404(sid)
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise err_invalid_request("Request body must be a JSON object")
    check_unknown_fields(data, {"use_credit_balance", "payment_cents"})
    use_credit = opt_bool(data, "use_credit_balance", False)
    # optional explicit cash amount; default = whatever remains after credits
    payment_cents = data.get("payment_cents")

    # Resident ownership
    if user_id != s["household_id"]:
        raise err_resident_not_owner()

    # State: must be PENDING_PAYMENT or ACTIVE
    if s["status"] not in ("PENDING_PAYMENT", "ACTIVE"):
        raise err_invalid_state("Subscription is not payable in its current state")

    outstanding = s["total_due_cents"] - s["paid_cents"]
    if outstanding <= 0:
        raise ApiError(ERR_PAYMENT_NOT_REQUIRED, "No outstanding balance", 409)

    hh = STORE.households.get(s["household_id"])
    covered = 0

    # Apply GRANTED credits oldest created_at first when use_credit_balance=true
    if use_credit:
        credits = [c for c in STORE.credits.values()
                   if c["household_id"] == s["household_id"] and c["status"] == "GRANTED"]
        credits.sort(key=lambda c: (c["created_at"], c["id"]))
        for c in credits:
            if covered >= outstanding:
                break
            c["status"] = "APPLIED"
            s["paid_cents"] += c["amount_cents"]
            covered += c["amount_cents"]
            recompute_credit_balance(hh["id"], bump_version=True)

    remaining = s["total_due_cents"] - s["paid_cents"]
    if payment_cents is None:
        cash = remaining
    else:
        if isinstance(payment_cents, bool) or not isinstance(payment_cents, int) or payment_cents < 0:
            raise err_invalid_request("payment_cents must be a non-negative integer")
        cash = payment_cents

    # Payment must cover full outstanding: paid_cents reaches exactly total_due_cents
    if cash < remaining:
        raise err_invalid_request("Payment does not cover the full outstanding balance")
    if cash > remaining:
        raise err_invalid_request("Payment exceeds the outstanding balance")

    s["paid_cents"] += cash
    if s["status"] == "PENDING_PAYMENT" and s["paid_cents"] >= s["total_due_cents"]:
        s["status"] = "ACTIVE"
    touch(s)
    return success_object(subscription_out(s))


@bp.post("/subscriptions/<sid>/cancel")
def cancel_subscription(sid):
    user_id, role = require_roles("Resident", "ProgramAdmin")
    s = _get_sub_or_404(sid)

    if role == "Resident" and user_id != s["household_id"]:
        raise err_resident_not_owner()

    if s["status"] in TERMINAL_SUB_STATUSES:
        raise err_invalid_state("Subscription is already terminal")

    s["status"] = "CANCELLED"
    s["suspended_reason"] = None
    cancel_subscription_cascade(s)
    touch(s)
    return success_object(subscription_out(s))


@bp.post("/subscriptions/<sid>/cure")
def cure_subscription(sid):
    user_id, role = require_roles("Resident")
    s = _get_sub_or_404(sid)
    data = require_body(request.get_json(silent=True))
    check_unknown_fields(data, {"payment_cents"})
    payment_cents = req_int(data, "payment_cents")
    if payment_cents < 0:
        raise err_invalid_request("payment_cents must be >= 0")

    if user_id != s["household_id"]:
        raise err_resident_not_owner()

    if s["status"] != "SUSPENDED":
        raise err_invalid_state("Subscription is not SUSPENDED")

    outstanding = s["total_due_cents"] - s["paid_cents"]
    if payment_cents < outstanding:
        raise err_invalid_request("payment_cents does not cover the outstanding balance")

    s["strikes_this_season"] = 0
    s["suspended_reason"] = None
    s["paid_cents"] += payment_cents
    s["status"] = "ACTIVE"
    touch(s)
    return success_object(subscription_out(s))
