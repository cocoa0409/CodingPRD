"""Customer endpoints and customer sub-collections."""
from flask import Blueprint, g, request

import errors
import services
from db import db
from middleware import (body_json, check_transition, f_enum, f_int, f_str,
                        require_owner, require_roles)
from response import list_response, ok_object
from services import (base_record, bump, ser_addon, ser_customer, ser_ledger,
                      ser_rental, ser_invoice, ser_skip_credit, ser_work_order)

bp = Blueprint("customers", __name__)

CUSTOMER_TERMINAL = ("CLOSED",)


def _get_customer(cid):
    c = db.customers.get(cid)
    if c is None:
        raise errors.not_found("customer not found")
    return c


@bp.post("/customers")
@require_roles("OpsAdmin")
def create_customer():
    d = body_json()
    # Stage 5: presence / types / enum membership.
    account_type = f_enum(d, "account_type", {"OFFICE", "HOME"})
    business_name = f_str(d, "business_name")
    billing_email = f_str(d, "billing_email")
    service_address = f_str(d, "service_address")
    delivery_zone_id = f_str(d, "delivery_zone_id")
    service_mode = f_enum(d, "service_mode", {"AUTO", "WILL_CALL"},
                          required=False, default="AUTO")
    par_level_bottles = f_int(d, "par_level_bottles", required=False,
                              default=2, min_value=0)
    pricing_tier = f_enum(d, "pricing_tier", {"STANDARD", "SILVER", "GOLD"},
                          required=False, default="STANDARD")
    # Stage 6: foreign keys resolve.
    if db.zones.get(delivery_zone_id) is None:
        raise errors.invalid_reference("delivery_zone_id does not resolve")
    rec = base_record()
    rec.update({
        "account_type": account_type,
        "business_name": business_name,
        "billing_email": billing_email,
        "service_address": service_address,
        "delivery_zone_id": delivery_zone_id,
        "service_mode": service_mode,
        "par_level_bottles": par_level_bottles,
        "pricing_tier": pricing_tier,
        "account_status": "ACTIVE",
        "overdue_since": None,
    })
    with db.lock:
        db.customers[rec["id"]] = rec
    return ok_object(ser_customer(rec), 201)


@bp.get("/customers")
@require_roles("OpsAdmin", "Dispatcher", "BillingAdmin")
def list_customers():
    items = list(db.customers.values())
    account_status = request.args.get("account_status")
    if account_status is not None:
        items = [c for c in items if c["account_status"] == account_status]
    zone_id = request.args.get("delivery_zone_id")
    if zone_id is not None:
        items = [c for c in items if c["delivery_zone_id"] == zone_id]
    return list_response(items, ser_customer)


@bp.get("/customers/<cid>")
@require_roles("OpsAdmin", "Dispatcher", "BillingAdmin", "CustomerSelf")
def get_customer(cid):
    c = _get_customer(cid)
    require_owner(c["id"])
    return ok_object(ser_customer(c))


@bp.patch("/customers/<cid>")
@require_roles("OpsAdmin")
def update_customer(cid):
    c = _get_customer(cid)
    check_transition(c, "account_status", ("ACTIVE", "SUSPENDED"),
                     CUSTOMER_TERMINAL, "Customer")
    d = body_json()
    expected = f_int(d, "expected_customer_version")
    business_name = f_str(d, "business_name", required=False)
    service_address = f_str(d, "service_address", required=False)
    par_level_bottles = f_int(d, "par_level_bottles", required=False,
                              min_value=0)
    pricing_tier = f_enum(d, "pricing_tier", {"STANDARD", "SILVER", "GOLD"},
                          required=False)
    service_mode = f_enum(d, "service_mode", {"AUTO", "WILL_CALL"},
                          required=False)
    # Priority 17: optimistic concurrency.
    if expected != c["version"]:
        raise errors.ApiError(errors.ERR_STALE_VERSION, 412,
                              "expected_customer_version does not match current version")
    with db.lock:
        if business_name is not None:
            c["business_name"] = business_name
        if service_address is not None:
            c["service_address"] = service_address
        if par_level_bottles is not None:
            c["par_level_bottles"] = par_level_bottles
        if pricing_tier is not None:
            c["pricing_tier"] = pricing_tier
        if service_mode is not None:
            c["service_mode"] = service_mode
        bump(c)
    return ok_object(ser_customer(c))


@bp.post("/customers/<cid>/suspend")
@require_roles("OpsAdmin")
def suspend_customer(cid):
    c = _get_customer(cid)
    check_transition(c, "account_status", ("ACTIVE",), CUSTOMER_TERMINAL,
                     "Customer")
    if services.outstanding_balance(cid) <= 0:
        raise errors.ApiError(
            errors.ERR_OUTSTANDING_BALANCE, 422,
            "suspend requires a positive outstanding balance (non-payment)")
    with db.lock:
        # Cascade: cancel PENDING work orders.
        for w in db.work_orders.values():
            if w["customer_id"] == cid and w["order_status"] == "PENDING":
                w["order_status"] = "CANCELLED"
                bump(w)
        # Cascade: cancel PLANNED stops on future routes, releasing commit.
        touched_routes = set()
        today = services.today()
        for s in db.stops.values():
            if s["customer_id"] != cid or s["stop_status"] != "PLANNED":
                continue
            r = db.routes.get(s["route_id"])
            if r is None:
                continue
            if services.parse_date(r["service_date"]) >= today:
                s["stop_status"] = "CANCELLED"
                bump(s)
                touched_routes.add(r["id"])
        for rid in touched_routes:
            bump(db.routes[rid])
        c["account_status"] = "SUSPENDED"
        bump(c)
    return ok_object(ser_customer(c))


@bp.post("/customers/<cid>/reinstate")
@require_roles("OpsAdmin")
def reinstate_customer(cid):
    c = _get_customer(cid)
    check_transition(c, "account_status", ("SUSPENDED",), CUSTOMER_TERMINAL,
                     "Customer")
    if services.outstanding_balance(cid) != 0:
        raise errors.ApiError(
            errors.ERR_OUTSTANDING_BALANCE, 422,
            "reinstate requires outstanding balance to be zero")
    with db.lock:
        c["account_status"] = "ACTIVE"
        bump(c)
    return ok_object(ser_customer(c))


@bp.post("/customers/<cid>/close")
@require_roles("OpsAdmin")
def close_customer(cid):
    c = _get_customer(cid)
    check_transition(c, "account_status", ("ACTIVE", "SUSPENDED"),
                     CUSTOMER_TERMINAL, "Customer")
    from_state = c["account_status"]
    # Priority 11: zero-balance gate.
    if services.outstanding_balance(cid) != 0:
        raise errors.ApiError(errors.ERR_OUTSTANDING_BALANCE, 422,
                              "customer close blocked by outstanding balance")
    # Priority 12: zero-bottle-custody gate.
    if services.bottles_on_site(cid) != 0:
        raise errors.ApiError(errors.ERR_BOTTLES_OUTSTANDING, 422,
                              "customer close blocked by bottles on site")
    if from_state == "ACTIVE":
        for r in db.rentals.values():
            if (r["customer_id"] == cid and r["rental_status"]
                    in ("INSTALLED", "SUSPENDED", "RETURN_REQUESTED")):
                raise errors.invalid_state(
                    "customer has a cooler rental still standing")
    with db.lock:
        for a in db.addons.values():
            if (a["customer_id"] == cid
                    and a["addon_status"] in ("ACTIVE", "PAUSED")):
                a["addon_status"] = "CANCELLED"
                bump(a)
        if from_state == "ACTIVE":
            for inv in db.invoices.values():
                if (inv["customer_id"] == cid
                        and inv["invoice_status"] in ("DRAFT", "OPEN")):
                    inv["invoice_status"] = "VOID"
                    inv["balance_due_cents"] = 0
                    bump(inv)
        c["account_status"] = "CLOSED"
        bump(c)
    return ok_object(ser_customer(c))


# ------------------------------------------------------- sub-collections

@bp.get("/customers/<cid>/cooler-rentals")
@require_roles("OpsAdmin", "Dispatcher", "BillingAdmin", "Driver",
               "CustomerSelf")
def list_customer_rentals(cid):
    _get_customer(cid)
    require_owner(cid)
    items = [r for r in db.rentals.values() if r["customer_id"] == cid]
    return list_response(items, ser_rental)


@bp.get("/customers/<cid>/addons")
@require_roles("OpsAdmin", "BillingAdmin", "CustomerSelf")
def list_customer_addons(cid):
    _get_customer(cid)
    require_owner(cid)
    items = [a for a in db.addons.values() if a["customer_id"] == cid]
    return list_response(items, ser_addon)


@bp.get("/customers/<cid>/invoices")
@require_roles("OpsAdmin", "BillingAdmin", "CustomerSelf")
def list_customer_invoices(cid):
    _get_customer(cid)
    require_owner(cid)
    items = [i for i in db.invoices.values() if i["customer_id"] == cid]
    status = request.args.get("invoice_status")
    if status is not None:
        items = [i for i in items if i["invoice_status"] == status]
    return list_response(items, ser_invoice)


@bp.get("/customers/<cid>/work-orders")
@require_roles("OpsAdmin", "Dispatcher", "CustomerSelf", "Driver")
def list_customer_work_orders(cid):
    _get_customer(cid)
    require_owner(cid)
    items = [w for w in db.work_orders.values() if w["customer_id"] == cid]
    status = request.args.get("order_status")
    if status is not None:
        items = [w for w in items if w["order_status"] == status]
    return list_response(items, ser_work_order)


@bp.get("/customers/<cid>/bottle-custody-ledger")
@require_roles("OpsAdmin", "BillingAdmin", "CustomerSelf")
def list_customer_ledger(cid):
    _get_customer(cid)
    require_owner(cid)
    items = [e for e in db.ledger.values() if e["customer_ref"] == cid]
    return list_response(items, ser_ledger)


@bp.get("/customers/<cid>/skip-credits")
@require_roles("OpsAdmin", "BillingAdmin", "CustomerSelf")
def list_customer_skip_credits(cid):
    _get_customer(cid)
    require_owner(cid)
    items = [s for s in db.skip_credits.values() if s["customer_id"] == cid]
    return list_response(items, ser_skip_credit)
