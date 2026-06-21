"""Order core lifecycle: create/read/list, line CRUD, quote, cancel."""
from datetime import datetime, timezone, timedelta

from flask import Blueprint, request, g

import clock
import serializers as S
import validators as V
from db import store
from errors import (
    err, ERR_NOT_FOUND, ERR_REFERENCE_NOT_FOUND, ERR_INVALID_STATE,
    ERR_OPTION_NOT_ALLOWED, ERR_DIETARY_CONFLICT, ERR_LINE_IMMUTABLE,
    ERR_LEAD_TIME_NOT_MET, ERR_PAST_ORDER_CUTOFF,
)
from middleware import require_auth
from response import success, list_response, parse_pagination
from services import calculations as calc
from services import dietary
from services.orders import (
    get_order_or_404, assert_owner, option_index, order_lines, recompute_estimate,
)

bp = Blueprint("orders", __name__)

EDITABLE_STATES = {"DRAFT", "QUOTED", "CHANGES_REQUESTED"}


def _sorted(values):
    return sorted(values, key=lambda o: (o["created_at"], o["id"]))


def _parse_date_start_utc(date_str):
    """Parse a YYYY-MM-DD into the UTC start-of-day datetime."""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return d.replace(tzinfo=timezone.utc)


def _parse_iso(value):
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---- create / read / list ----------------------------------------------

@bp.route("/orders", methods=["POST"])
@require_auth(["Customer"])
def create_order():
    data = V.body()
    customer_id = V.require_str(data, "customer_id")
    product_id = V.require_str(data, "product_id")
    production_day_id = V.require_str(data, "production_day_id")

    # ownership: a Customer creates an order for themselves.
    if g.role == "Customer" and g.user_id != customer_id:
        from errors import ERR_NOT_ORDER_OWNER
        raise err(ERR_NOT_ORDER_OWNER, "cannot create an order for another customer")

    # body FK existence (ERR_REFERENCE_NOT_FOUND)
    if customer_id not in store.customers:
        raise err(ERR_REFERENCE_NOT_FOUND, "customer_id does not resolve")
    if product_id not in store.products:
        raise err(ERR_REFERENCE_NOT_FOUND, "product_id does not resolve")
    if production_day_id not in store.production_days:
        raise err(ERR_REFERENCE_NOT_FOUND, "production_day_id does not resolve")

    obj = {
        "customer_id": customer_id,
        "product_id": product_id,
        "production_day_id": production_day_id,
        "placed_at": clock.iso_millis(),
        "production_status": "DRAFT",
        "payment_status": "UNPAID",
        "estimate_total_cents": 0,
        "final_total_cents": None,
        "deposit_due_cents": 0,
        "balance_due_cents": 0,
        "applied_credit_cents": 0,
        "peak_surcharge_cents": 0,
        "cancel_reason": None,
    }
    store.stamp_create(obj)
    store.orders[obj["id"]] = obj
    return success(S.order(obj), status=201)


@bp.route("/orders/<oid>", methods=["GET"])
@require_auth(["Customer", "BakeryStaff", "BakeryManager", "DeliveryDispatcher"])
def get_order(oid):
    obj = get_order_or_404(oid)
    assert_owner(obj)
    return success(S.order(obj), status=200)


@bp.route("/orders", methods=["GET"])
@require_auth(["Customer", "BakeryStaff", "BakeryManager", "DeliveryDispatcher"])
def list_orders():
    limit, offset = parse_pagination(request.args)
    items = list(store.orders.values())
    # Customers see only their own orders.
    if g.role == "Customer":
        items = [o for o in items if o["customer_id"] == g.user_id]
    for field in ("customer_id", "product_id", "production_day_id",
                  "production_status", "payment_status"):
        val = request.args.get(field)
        if val is not None:
            items = [o for o in items if o[field] == val]
    return list_response([S.order(o) for o in _sorted(items)], limit, offset)


# ---- lines --------------------------------------------------------------

def _build_line(order, units, selected_codes, dietary_codes):
    """Validate option allowance + dietary, compute derived fields. Returns the
    computed (line_surcharge_cents, effective_allergen_codes)."""
    product = store.products[order["product_id"]]
    opt_idx = option_index()

    # body reference existence: every selected_option_code must resolve to an option.
    for code in selected_codes:
        if code not in opt_idx:
            raise err(ERR_REFERENCE_NOT_FOUND, f"option_code {code} does not resolve")

    # dietary conflict (priority 8) is checked BEFORE option allowance (priority 9).
    effective = calc.compute_effective_allergens(product, selected_codes, opt_idx)
    if dietary.dietary_conflict(dietary_codes, selected_codes, opt_idx, effective):
        raise err(ERR_DIETARY_CONFLICT, "line violates a dietary requirement")

    # option allowance (priority 9)
    allowed = set(product.get("allowed_option_codes") or [])
    for code in selected_codes:
        if code not in allowed:
            raise err(ERR_OPTION_NOT_ALLOWED, f"option {code} not allowed for product")

    surcharge = calc.compute_line_surcharge(units, selected_codes, opt_idx)
    return surcharge, effective


@bp.route("/orders/<oid>/lines", methods=["POST"])
@require_auth(["Customer"])
def add_line(oid):
    order = get_order_or_404(oid)
    assert_owner(order)

    data = V.body()
    units = V.require_int(data, "units", minimum=1)
    selected_codes = V.optional_str_array(data, "selected_option_codes", default=[])
    dietary_codes = V.optional_str_array(data, "requested_dietary_codes", default=[])

    if order["production_status"] not in EDITABLE_STATES:
        raise err(ERR_LINE_IMMUTABLE, "order lines are immutable in this state")

    surcharge, effective = _build_line(order, units, selected_codes, dietary_codes)

    line = {
        "order_id": oid,
        "units": units,
        "selected_option_codes": selected_codes,
        "requested_dietary_codes": dietary_codes,
        "line_surcharge_cents": surcharge,
        "effective_allergen_codes": effective,
    }
    store.stamp_create(line)
    store.lines[line["id"]] = line

    if order["production_status"] == "QUOTED":
        recompute_estimate(order)
    store.touch(order)
    return success(S.line(line), status=201)


@bp.route("/orders/<oid>/lines", methods=["GET"])
@require_auth(["Customer", "BakeryStaff", "BakeryManager"])
def list_lines(oid):
    order = get_order_or_404(oid)
    assert_owner(order)
    limit, offset = parse_pagination(request.args)
    items = order_lines(oid)
    return list_response([S.line(l) for l in items], limit, offset)


@bp.route("/orders/<oid>/lines/<lid>", methods=["PATCH"])
@require_auth(["Customer"])
def edit_line(oid, lid):
    order = get_order_or_404(oid)
    assert_owner(order)
    line = store.lines.get(lid)
    if line is None or line["order_id"] != oid:
        raise err(ERR_NOT_FOUND, "line not found")

    data = V.body()
    units = line["units"]
    if "units" in data and data["units"] is not None:
        units = V.require_int(data, "units", minimum=1)
    selected_codes = line["selected_option_codes"]
    if "selected_option_codes" in data and data["selected_option_codes"] is not None:
        selected_codes = V.require_str_array(data, "selected_option_codes")
    dietary_codes = line["requested_dietary_codes"]
    if "requested_dietary_codes" in data and data["requested_dietary_codes"] is not None:
        dietary_codes = V.require_str_array(data, "requested_dietary_codes")

    if order["production_status"] not in EDITABLE_STATES:
        raise err(ERR_LINE_IMMUTABLE, "order lines are immutable in this state")

    surcharge, effective = _build_line(order, units, selected_codes, dietary_codes)

    line["units"] = units
    line["selected_option_codes"] = selected_codes
    line["requested_dietary_codes"] = dietary_codes
    line["line_surcharge_cents"] = surcharge
    line["effective_allergen_codes"] = effective
    store.touch(line)

    if order["production_status"] == "QUOTED":
        recompute_estimate(order)
    store.touch(order)
    return success(S.line(line), status=200)


@bp.route("/orders/<oid>/lines/<lid>", methods=["DELETE"])
@require_auth(["Customer"])
def delete_line(oid, lid):
    order = get_order_or_404(oid)
    assert_owner(order)
    line = store.lines.get(lid)
    if line is None or line["order_id"] != oid:
        raise err(ERR_NOT_FOUND, "line not found")

    if order["production_status"] not in EDITABLE_STATES:
        raise err(ERR_LINE_IMMUTABLE, "order lines are immutable in this state")

    del store.lines[lid]

    if order["production_status"] == "QUOTED":
        recompute_estimate(order)
    store.touch(order)
    return success({}, status=204)


# ---- quote --------------------------------------------------------------

@bp.route("/orders/<oid>/quote", methods=["POST"])
@require_auth(["Customer"])
def quote_order(oid):
    order = get_order_or_404(oid)
    assert_owner(order)

    data = V.body()
    override_token = V.optional_str(data, "manager_override_token", default=None)
    has_override = override_token is not None and override_token in store.override_tokens

    # state: only DRAFT -> QUOTED defined
    if order["production_status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "quote only valid from DRAFT")

    lines = order_lines(oid)
    if len(lines) < 1:
        # at least one line required; no dedicated error in catalog -> invalid state
        raise err(ERR_INVALID_STATE, "order must have at least one line to quote")

    product = store.products[order["product_id"]]
    pday = store.production_days[order["production_day_id"]]

    # temporal gates (skipped with a valid manager override)
    if not has_override:
        # lead time: placed_at + base_lead_days whole days <= production_date 00:00:00Z
        placed = _parse_iso(order["placed_at"])
        earliest = placed + timedelta(days=product["base_lead_days"])
        prod_start = _parse_date_start_utc(pday["production_date"])
        if earliest > prod_start:
            raise err(ERR_LEAD_TIME_NOT_MET, "lead time not met")
        # cutoff: now <= order_cutoff_at
        cutoff = _parse_iso(pday["order_cutoff_at"])
        if clock.now() > cutoff:
            raise err(ERR_PAST_ORDER_CUTOFF, "past order cutoff")

    # transition + pricing
    order["production_status"] = "QUOTED"
    recompute_estimate(order)
    store.touch(order)
    return success(S.order(order), status=200)


# ---- cancel -------------------------------------------------------------

NON_TERMINAL_PRODUCTION = {
    "DRAFT", "QUOTED", "PROOF_PENDING", "CHANGES_REQUESTED",
    "PROOF_APPROVED", "IN_PRODUCTION", "READY",
}

CASCADE_STATES = {"PROOF_PENDING", "CHANGES_REQUESTED", "PROOF_APPROVED"}


@bp.route("/orders/<oid>/cancel", methods=["POST"])
@require_auth(["Customer"])
def cancel_order(oid):
    order = get_order_or_404(oid)
    assert_owner(order)

    data = V.body()
    cancel_reason = V.optional_str(data, "cancel_reason", default=None)

    status_at_cancel = order["production_status"]
    if status_at_cancel not in NON_TERMINAL_PRODUCTION:
        raise err(ERR_INVALID_STATE, "cannot cancel a terminal order")

    # Full cascade for the post-deposit-ish design states.
    if status_at_cancel in CASCADE_STATES:
        # release HELD/COMMITTED reservations
        for res in store.reservations.values():
            if res["order_id"] != oid:
                continue
            if res["status"] in ("HELD", "COMMITTED"):
                was_committed = res["status"] == "COMMITTED"
                res["status"] = "RELEASED"
                store.touch(res)
                if was_committed:
                    pday = store.production_days.get(order["production_day_id"])
                    if pday is not None:
                        units = sum(l["units"] for l in store.lines.values()
                                    if l["order_id"] == oid)
                        pday["units_committed"] -= units
                        store.touch(pday)
        # supersede non-terminal proofs
        for proof in store.proofs.values():
            if proof["order_id"] != oid:
                continue
            if proof["proof_status"] in ("AWAITING_REVIEW", "REJECTED"):
                proof["proof_status"] = "SUPERSEDED"
                store.touch(proof)

    # refund settlement (runs for QUOTED and all cascade states; DRAFT -> nothing)
    if status_at_cancel != "DRAFT":
        _refund_settlement(order, status_at_cancel)

    order["production_status"] = "CANCELLED"
    if cancel_reason is not None:
        order["cancel_reason"] = cancel_reason
    store.touch(order)
    return success(S.order(order), status=200)


def _refund_settlement(order, status_at_cancel):
    """Credit captured tender back per cancel-state policy; record REFUND payment."""
    captured = sum(
        p["amount_cents"] for p in store.payments.values()
        if p["order_id"] == order["id"] and p["kind"] in ("DEPOSIT", "BALANCE")
    )
    refund = calc.compute_refund(captured, status_at_cancel, order["deposit_due_cents"])

    if refund > 0:
        customer = store.customers.get(order["customer_id"])
        if customer is not None:
            customer["store_credit_cents"] += refund
            store.touch(customer)

    # When any capture is reversed, create a REFUND payment and move payment_status.
    if captured > 0:
        payment = {
            "order_id": order["id"],
            "kind": "REFUND",
            "amount_cents": refund,
            "credit_applied_cents": 0,
            "settled_at": clock.iso_millis(),
        }
        store.stamp_create(payment, common_fields=False)
        store.payments[payment["id"]] = payment
        order["payment_status"] = "REFUNDED"
