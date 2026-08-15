"""Service purchase endpoints: request / get / quote / accept / payments /
cancel / list payments — with lazy quote expiry and OCC on payment."""

from datetime import date, timedelta
from decimal import Decimal

from flask import Blueprint

from db import store, make_entity, touch, public, sort_key, now, fmt_dt
from errors import (
    err_not_found,
    err_invalid_request,
    err_invalid_state,
    err_member_deceased,
    err_quote_expired,
    err_plan_not_active,
    err_stale_version,
    err_purchase_period_overlap,
)
from middleware import (
    auth,
    require_roles,
    body,
    req_field,
    as_int,
    as_number,
    as_enum,
    pagination,
    check_member_path,
    check_member_resource,
)
from response import ok, ok_list
from services import calcs, cascades
from utils import parse_date, dec

bp = Blueprint("purchases", __name__)

PURCHASE_TYPES = {"MILITARY", "PRIOR_SERVICE"}
PURCHASE_VIEW_ROLES = {"FundAdmin", "MemberServicesAnalyst", "Member"}
CANCELLABLE_STATES = ("REQUESTED", "QUOTED", "PLAN_ACTIVE")


def get_purchase(purchase_id):
    p = store.purchases.get(purchase_id)
    if p is None:
        raise err_not_found("Service purchase not found")
    return p


def serialize_purchase(p):
    out = public(p)
    out["years_purchased"] = float(p["years_purchased"])
    return out


def _credited_year_overlaps(member_id, start, end):
    """Closed-interval overlap: any shared day between [start, end] and a
    fiscal year already credited (ACCEPTED line) to the member."""
    for line in calcs.member_lines(member_id, ("ACCEPTED",)):
        fy_start = date(line["fiscal_year"], 1, 1)
        fy_end = date(line["fiscal_year"], 12, 31)
        if start <= fy_end and fy_start <= end:
            return True
    return False


@bp.post("/members/<member_id>/service-purchases")
def create_purchase(member_id):
    ctx = auth()
    require_roles(ctx, {"Member", "MemberServicesAnalyst"})
    check_member_path(ctx, member_id)
    member = store.members.get(member_id)
    if member is None:
        raise err_not_found("Member not found")
    # Member lifecycle gate: a DECEASED member's account is frozen.
    if member["status"] == "DECEASED":
        raise err_member_deceased()
    data = body()
    purchase_type = as_enum(req_field(data, "purchase_type"), "purchase_type", PURCHASE_TYPES)
    start = parse_date(req_field(data, "service_period_start"))
    if start is None:
        raise err_invalid_request("service_period_start must be an ISO date")
    end = parse_date(req_field(data, "service_period_end"))
    if end is None:
        raise err_invalid_request("service_period_end must be an ISO date")
    if end < start:
        raise err_invalid_request("service_period_end must not precede service_period_start")
    years_raw = as_number(req_field(data, "years_purchased"), "years_purchased")
    years = calcs.round_half_up_2dp(dec(years_raw))
    if _credited_year_overlaps(member_id, start, end):
        raise err_purchase_period_overlap()
    purchase = make_entity(
        {
            "member_id": member_id,
            "purchase_type": purchase_type,
            "service_period_start": start.isoformat(),
            "service_period_end": end.isoformat(),
            "years_purchased": years,
            "status": "REQUESTED",
            "flat_cost_cents": None,
            "actuarial_cost_cents": None,
            "cost_variant": None,
            "quoted_cost_cents": None,
            "quote_expires_at": None,
            "installment_count": None,
            "balance_due_cents": None,
            "refunded_total_cents": 0,
        }
    )
    store.purchases[purchase["id"]] = purchase
    return ok(serialize_purchase(purchase), 201)


@bp.get("/service-purchases/<purchase_id>")
def read_purchase(purchase_id):
    ctx = auth()
    require_roles(ctx, PURCHASE_VIEW_ROLES)
    purchase = get_purchase(purchase_id)
    check_member_resource(ctx, purchase["member_id"])
    return ok(serialize_purchase(purchase))


@bp.post("/service-purchases/<purchase_id>/quote")
def quote_purchase(purchase_id):
    ctx = auth()
    require_roles(ctx, {"MemberServicesAnalyst"})
    purchase = get_purchase(purchase_id)
    if purchase["status"] != "REQUESTED":
        raise err_invalid_state("Only a REQUESTED purchase can be quoted")
    member = store.members.get(purchase["member_id"])
    if member is None or member["current_annual_salary_cents"] is None:
        # Pricing needs a salary: at least one ACCEPTED contribution line.
        raise err_invalid_state("Member has no ACCEPTED contribution line")
    flat, actuarial, variant, quoted, expires_at = calcs.purchase_quote(
        member, purchase["years_purchased"]
    )
    purchase["flat_cost_cents"] = flat
    purchase["actuarial_cost_cents"] = actuarial
    purchase["cost_variant"] = variant
    purchase["quoted_cost_cents"] = quoted
    purchase["quote_expires_at"] = fmt_dt(expires_at)
    purchase["_quote_expires_dt"] = expires_at
    purchase["status"] = "QUOTED"
    touch(purchase)
    return ok(serialize_purchase(purchase))


@bp.post("/service-purchases/<purchase_id>/accept")
def accept_purchase(purchase_id):
    ctx = auth()
    require_roles(ctx, {"Member", "MemberServicesAnalyst"})
    purchase = get_purchase(purchase_id)
    check_member_resource(ctx, purchase["member_id"])
    if purchase["status"] != "QUOTED":
        raise err_invalid_state("Only a QUOTED purchase can be accepted")
    # Temporal gate (priority 7) ahead of the installment-count constraint
    # (priority 8). Expiry is lazy: a late accept moves the purchase to
    # EXPIRED in the same stroke and then fails.
    if now() > purchase["_quote_expires_dt"]:
        purchase["status"] = "EXPIRED"
        purchase["balance_due_cents"] = 0
        touch(purchase)
        raise err_quote_expired()
    data = body()
    installment_count = as_int(req_field(data, "installment_count"), "installment_count")
    if installment_count < 1 or installment_count > 60:
        raise err_invalid_request("installment_count must be between 1 and 60")

    quoted = purchase["quoted_cost_cents"]
    amounts = calcs.installment_amounts(quoted, installment_count)
    accept_dt = now()
    for i, amount in enumerate(amounts, start=1):
        due = calcs.installment_due_date(accept_dt, i)
        payment = make_entity(
            {
                "purchase_id": purchase_id,
                "sequence_number": i,
                "amount_cents": amount,
                "due_date": due.isoformat(),
                "status": "PENDING",
                "applied_at": None,
            }
        )
        store.payments[payment["id"]] = payment
    purchase["installment_count"] = installment_count
    purchase["balance_due_cents"] = quoted
    purchase["status"] = "PLAN_ACTIVE"
    touch(purchase)
    return ok(serialize_purchase(purchase))


@bp.post("/service-purchases/<purchase_id>/payments")
def apply_payment(purchase_id):
    ctx = auth()
    require_roles(ctx, {"Member", "MemberServicesAnalyst"})
    purchase = get_purchase(purchase_id)
    check_member_resource(ctx, purchase["member_id"])
    data = body()
    payment_id = req_field(data, "payment_id")
    if not isinstance(payment_id, str):
        raise err_invalid_request("payment_id must be a string")
    payment = store.payments.get(payment_id)
    if payment is None or payment["purchase_id"] != purchase_id:
        raise err_not_found("Payment not found")
    # OCC (priority 3.5) ahead of the PLAN_ACTIVE state gate (priority 4.2).
    expected = data.get("expected_purchase_version")
    if expected is not None and as_int(expected, "expected_purchase_version") != purchase["version"]:
        raise err_stale_version("Purchase version has advanced; re-read before paying")
    if purchase["status"] != "PLAN_ACTIVE":
        raise err_plan_not_active()
    if payment["status"] != "PENDING":
        raise err_invalid_state("Payment is not PENDING")

    payment["status"] = "APPLIED"
    payment["applied_at"] = fmt_dt(now())
    touch(payment)
    purchase["balance_due_cents"] -= payment["amount_cents"]
    if purchase["balance_due_cents"] == 0:
        # Completion cascade: PLAN_ACTIVE -> COMPLETED and the purchased
        # service credit posts to the member in the same request.
        purchase["status"] = "COMPLETED"
        touch(purchase)
        member = store.members.get(purchase["member_id"])
        if member is not None and calcs.recompute_member(member):
            touch(member)
    else:
        touch(purchase)
    return ok(serialize_purchase(purchase))


@bp.post("/service-purchases/<purchase_id>/cancel")
def cancel_purchase(purchase_id):
    ctx = auth()
    require_roles(ctx, {"Member", "MemberServicesAnalyst"})
    purchase = get_purchase(purchase_id)
    check_member_resource(ctx, purchase["member_id"])
    if purchase["status"] not in CANCELLABLE_STATES:
        raise err_invalid_state("Purchase in %s cannot be cancelled" % purchase["status"])
    cascades.cancel_purchase(purchase)
    return ok(serialize_purchase(purchase))


@bp.get("/service-purchases/<purchase_id>/payments")
def list_payments(purchase_id):
    ctx = auth()
    require_roles(ctx, PURCHASE_VIEW_ROLES)
    purchase = get_purchase(purchase_id)
    check_member_resource(ctx, purchase["member_id"])
    limit, offset = pagination()
    payments = cascades.purchase_payments(purchase_id)
    page = payments[offset:offset + limit]
    return ok_list([public(p) for p in page], limit, offset, len(payments))
