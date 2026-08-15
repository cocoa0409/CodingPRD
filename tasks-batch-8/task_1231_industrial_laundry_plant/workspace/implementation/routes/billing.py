"""Invoice, billing-preview, and UtilityReading endpoints."""

from flask import Blueprint, request

import clock
import db
import services
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_CUSTOMER_SUSPENDED,
    ERR_CREDIT_LIMIT_EXCEEDED,
    ERR_STALE_VERSION,
    ERR_INVOICE_HAS_CREDITS,
    ERR_DUPLICATE,
)
from response import success, success_raw, list_response
from util import (
    authenticate,
    require_roles,
    cc_owns,
    body_json,
    field,
    path_get,
    filter_eq,
)

bp = Blueprint("billing", __name__)

CLERK = {"BillingClerk"}
INVOICE_READ = {"PlantAdmin", "CustomerServiceRep", "BillingClerk", "CustomerContact"}
PREVIEW_ROLES = {"PlantAdmin", "CustomerServiceRep", "BillingClerk"}
UTILITY_READ = {"PlantAdmin", "BillingClerk"}


def _period(data_start, data_end):
    start_d = clock.parse_date(data_start)
    end_d = clock.parse_date(data_end)
    if start_d is None or end_d is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid billing period dates")
    if not end_d > start_d:
        raise ApiError(ERR_INVALID_REQUEST, 400, "billing_period_end must be after billing_period_start")
    return start_d, end_d


def _build_invoice_components(customer, start_d, end_d, estimated_cog=False, override_par=None):
    plant = db.plants.get(customer["plant_id"])
    linen = services.linen_charges(
        customer, start_d, end_d, estimated=estimated_cog, override_par=override_par
    )
    month = "%04d-%02d" % (start_d.year, start_d.month)
    if plant:
        surcharge, variant = services.utility_surcharge(customer, plant, month)
    else:
        surcharge, variant = 0, "estimated"
    return linen, surcharge, variant, month


@bp.route("/customers/<cid>/invoices/generate", methods=["POST"])
def generate_invoice(cid):
    data = body_json()
    start_s = field(data, "billing_period_start", "date")
    end_s = field(data, "billing_period_end", "date")
    _period(start_s, end_s)
    auth = authenticate()
    require_roles(auth, CLERK)
    cust = path_get(db.customers, cid)
    start_d, end_d = clock.parse_date(start_s), clock.parse_date(end_s)
    linen, surcharge, variant, month = _build_invoice_components(cust, start_d, end_d)
    inv = db.new_entity()
    inv.update(
        {
            "customer_id": cust["id"],
            "billing_period_start": start_s,
            "billing_period_end": end_s,
            "linen_charges_cents": linen,
            "lost_item_charges_cents": 0,
            "utility_surcharge_cents": surcharge,
            "credits_cents": 0,
            "status": "DRAFT",
            "_surcharge_variant": variant,
            "_surcharge_month": month,
            "_trued_up": False,
        }
    )
    db.invoices[inv["id"]] = inv
    # Drain the unbilled lost-item queue into this invoice.
    inv["lost_item_charges_cents"] = services.drain_lost_charges(cust["id"], inv["id"])
    services.recompute_invoice_total(inv)
    return success(inv, 201)


@bp.route("/customers/<cid>/invoices", methods=["GET"])
def list_invoices(cid):
    auth = authenticate()
    require_roles(auth, INVOICE_READ)
    cust = path_get(db.customers, cid)
    cc_owns(auth, cust["id"])
    items = [i for i in db.sorted_all(db.invoices) if i["customer_id"] == cust["id"]]
    items = filter_eq(items, "status", "status")
    return list_response(items)


@bp.route("/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    auth = authenticate()
    require_roles(auth, INVOICE_READ)
    inv = path_get(db.invoices, iid)
    cc_owns(auth, inv["customer_id"])
    return success(inv)


@bp.route("/invoices/<iid>/issue", methods=["POST"])
def issue_invoice(iid):
    data = body_json()
    expected_version = field(data, "expected_customer_version", "i")
    auth = authenticate()
    require_roles(auth, CLERK)
    inv = path_get(db.invoices, iid)
    if inv["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "Invoice is not DRAFT")
    cust = db.customers.get(inv["customer_id"])
    if not cust or cust["status"] != "ACTIVE":
        raise ApiError(ERR_CUSTOMER_SUSPENDED, 409, "Customer is not ACTIVE")
    if inv["total_due_cents"] != 0 and (
        cust["account_balance_cents"] + inv["total_due_cents"] > cust["credit_limit_cents"]
    ):
        raise ApiError(ERR_CREDIT_LIMIT_EXCEEDED, 402, "Issue would exceed credit limit")
    if expected_version != cust["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "Customer version has advanced")
    inv["status"] = "ISSUED"
    db.touch(inv)
    cust["account_balance_cents"] += inv["total_due_cents"]
    db.touch(cust)
    return success(inv)


@bp.route("/invoices/<iid>/mark-paid", methods=["POST"])
def mark_paid_invoice(iid):
    auth = authenticate()
    require_roles(auth, CLERK)
    inv = path_get(db.invoices, iid)
    if inv["status"] != "ISSUED":
        raise ApiError(ERR_INVALID_STATE, 409, "Invoice is not ISSUED")
    inv["status"] = "PAID"
    db.touch(inv)
    cust = db.customers.get(inv["customer_id"])
    if cust:
        cust["account_balance_cents"] -= inv["total_due_cents"]
        db.touch(cust)
    return success(inv)


@bp.route("/invoices/<iid>/void", methods=["POST"])
def void_invoice(iid):
    auth = authenticate()
    require_roles(auth, CLERK)
    inv = path_get(db.invoices, iid)
    if inv["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "Invoice is not DRAFT")
    if any(
        x["status"] == "CREDITED" and x.get("_invoice_id") == inv["id"]
        for x in db.discrepancies.values()
    ):
        raise ApiError(ERR_INVOICE_HAS_CREDITS, 409, "Invoice has CREDITED discrepancies")
    services.release_lost_charges(inv["id"])
    inv["status"] = "VOID"
    db.touch(inv)
    return success(inv)


@bp.route("/customers/<cid>/billing-preview", methods=["GET"])
def billing_preview(cid):
    auth = authenticate()
    require_roles(auth, PREVIEW_ROLES)
    cust = path_get(db.customers, cid)
    start_s = request.args.get("billing_period_start")
    end_s = request.args.get("billing_period_end")
    if start_s is None or end_s is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "billing_period_start and billing_period_end are required")
    start_d, end_d = _period(start_s, end_s)
    override = None
    raw_override = request.args.get("override_par_pieces")
    if raw_override is not None:
        try:
            override = int(raw_override)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "override_par_pieces must be an integer")
        if override < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "override_par_pieces must be non-negative")
    linen, surcharge, _variant, _month = _build_invoice_components(
        cust, start_d, end_d, estimated_cog=True, override_par=override
    )
    lost = services.unbilled_lost_charges(cust["id"])
    credits = 0
    total = max(0, linen + lost + surcharge - credits)
    return success_raw(
        {
            "linen_charges_cents": linen,
            "lost_item_charges_cents": lost,
            "utility_surcharge_cents": surcharge,
            "credits_cents": credits,
            "total_due_cents": total,
        }
    )


@bp.route("/plants/<pid>/utility-readings", methods=["POST"])
def create_utility_reading(pid):
    data = body_json()
    period_month = field(data, "period_month", "month")
    kwh_used = field(data, "kwh_used", "n", minv=0)
    gallons_used = field(data, "gallons_used", "n", minv=0)
    clean_lbs = field(data, "clean_lbs_processed", "n", minv=0)
    kwh_rate = field(data, "kwh_rate_cents", "i", minv=0)
    gal_rate = field(data, "gallon_rate_cents", "i", minv=0)
    auth = authenticate()
    require_roles(auth, CLERK)
    plant = path_get(db.plants, pid)
    if services.find_reading(plant["id"], period_month) is not None:
        raise ApiError(ERR_DUPLICATE, 409, "A reading already exists for this plant and period_month")
    reading = db.new_entity(common=False)
    reading.update(
        {
            "plant_id": plant["id"],
            "period_month": period_month,
            "kwh_used": kwh_used,
            "gallons_used": gallons_used,
            "clean_lbs_processed": clean_lbs,
            "kwh_rate_cents": kwh_rate,
            "gallon_rate_cents": gal_rate,
        }
    )
    db.utility_readings[reading["id"]] = reading
    services.true_up_reading(reading)
    return success(reading, 201)


@bp.route("/plants/<pid>/utility-readings", methods=["GET"])
def list_utility_readings(pid):
    auth = authenticate()
    require_roles(auth, UTILITY_READ)
    plant = path_get(db.plants, pid)
    items = [r for r in db.sorted_all(db.utility_readings) if r["plant_id"] == plant["id"]]
    items = filter_eq(items, "period_month", "period_month")
    return list_response(items)


@bp.route("/utility-readings/<uid>", methods=["GET"])
def get_utility_reading(uid):
    auth = authenticate()
    require_roles(auth, UTILITY_READ)
    return success(path_get(db.utility_readings, uid))
