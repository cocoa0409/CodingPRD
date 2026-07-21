"""Purchases: recording, tax split, capture and void."""
from flask import Blueprint

from core import (
    authenticate,
    clock_now,
    db,
    fail,
    filter_eq,
    get_body,
    iso,
    new_record,
    ok,
    ok_list,
    ordered,
    pagination,
    paginate,
    public,
    req_str,
    tax_from_inclusive,
    bps_of,
    touch,
)
from services import (
    jurisdiction_for,
    lookup,
    recompute_accrual,
    recompute_risk,
    select_tier,
    write_entry,
)

bp = Blueprint("purchases", __name__)


def _validate_line_items(body):
    items = body.get("line_items")
    if not isinstance(items, list) or len(items) == 0:
        fail("ERR_INVALID_REQUEST", "line_items must be a non-empty array.")
    normalised = []
    for item in items:
        if not isinstance(item, dict):
            fail("ERR_INVALID_REQUEST", "Each line item must be an object.")
        sku = item.get("sku")
        if not isinstance(sku, str) or not sku.strip():
            fail("ERR_INVALID_REQUEST", "Each line item requires a non-empty sku.")
        unit = item.get("unit_price_cents")
        if isinstance(unit, bool) or not isinstance(unit, int) or unit <= 0:
            fail("ERR_INVALID_REQUEST", "unit_price_cents must be an integer > 0.")
        qty = item.get("quantity")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
            fail("ERR_INVALID_REQUEST", "quantity must be an integer > 0.")
        normalised.append({"sku": sku, "unit_price_cents": unit, "quantity": qty})
    return normalised


@bp.post("/api/purchases")
def create_purchase():
    authenticate({"StorefrontService"})
    body = get_body()
    app_id = req_str(body, "app_id")
    pricing_plan_id = req_str(body, "pricing_plan_id")
    buyer_country_code = req_str(body, "buyer_country_code")
    external_order_ref = req_str(body, "external_order_ref")
    line_items = _validate_line_items(body)
    for existing in ordered(db.purchases):
        if existing["external_order_ref"] == external_order_ref:
            fail("ERR_INVALID_REQUEST", "external_order_ref must be unique.")

    app = lookup("apps", app_id)
    plan = lookup("pricing_plans", pricing_plan_id)

    if app["status"] != "LIVE" or plan["status"] != "ACTIVE":
        fail("ERR_APP_NOT_PURCHASABLE", "Listing or plan is not purchasable.")

    jurisdiction = jurisdiction_for(buyer_country_code)
    if jurisdiction is None:
        fail("ERR_JURISDICTION_NOT_CONFIGURED",
             "No jurisdiction registered for %s." % buyer_country_code)

    if plan["app_id"] != app["id"]:
        fail("ERR_PLAN_APP_MISMATCH", "Pricing plan does not belong to this listing.")

    rate = jurisdiction["vat_rate_bps"]
    gross_cents = 0
    tax_cents = 0
    for line in line_items:
        line_gross = line["unit_price_cents"] * line["quantity"]
        gross_cents += line_gross
        tax_cents += tax_from_inclusive(line_gross, rate)
    revenue_base_cents = gross_cents - tax_cents

    if jurisdiction["marketplace_facilitator"]:
        tax_remitter = "MARKETPLACE"
        developer_tax_remittance_cents = 0
    else:
        tax_remitter = "DEVELOPER"
        developer_tax_remittance_cents = tax_cents

    rec = new_record(
        app_id=app["id"],
        pricing_plan_id=plan["id"],
        developer_id=app["developer_id"],
        tax_jurisdiction_id=jurisdiction["id"],
        buyer_country_code=buyer_country_code,
        external_order_ref=external_order_ref,
        line_items=line_items,
        gross_cents=gross_cents,
        tax_cents=tax_cents,
        revenue_base_cents=revenue_base_cents,
        developer_tax_remittance_cents=developer_tax_remittance_cents,
        tax_remitter=tax_remitter,
        provisional_share_bps=None,
        provisional_developer_net_cents=None,
        platform_fee_cents=None,
        refunded_gross_cents=0,
        payment_status="AUTHORIZED",
        settlement_status="UNSETTLED",
        captured_at=None,
    )
    db.purchases[rec["id"]] = rec
    return ok(public(rec), 201)


@bp.get("/api/purchases")
def list_purchases():
    authenticate({"StorefrontService", "PlatformAdmin", "FinanceOps", "Developer"})
    limit, offset = pagination()
    rows = ordered(db.purchases)
    for field in ("app_id", "pricing_plan_id", "developer_id", "tax_jurisdiction_id",
                  "payment_status", "settlement_status"):
        rows = filter_eq(rows, field)
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)


@bp.get("/api/purchases/<purchase_id>")
def read_purchase(purchase_id):
    authenticate({"StorefrontService", "PlatformAdmin", "FinanceOps", "Developer"})
    rec = lookup("purchases", purchase_id)
    return ok(public(rec))


@bp.post("/api/purchases/<purchase_id>/capture")
def capture(purchase_id):
    authenticate({"StorefrontService"})
    rec = lookup("purchases", purchase_id)
    if rec["payment_status"] != "AUTHORIZED":
        fail("ERR_INVALID_STATE", "Purchase is not AUTHORIZED.")
    dev = db.developers.get(rec["developer_id"])

    share_bps = select_tier(dev["lifetime_revenue_base_cents"] if dev else 0)
    net = bps_of(rec["revenue_base_cents"], share_bps)
    rec["provisional_share_bps"] = share_bps
    rec["provisional_developer_net_cents"] = net
    rec["platform_fee_cents"] = rec["revenue_base_cents"] - net
    rec["payment_status"] = "CAPTURED"
    rec["settlement_status"] = "ACCRUED"
    rec["captured_at"] = iso(clock_now())
    touch(rec)

    if dev is not None:
        dev["lifetime_revenue_base_cents"] += rec["revenue_base_cents"]
        write_entry(dev["id"], "ACCRUAL", net,
                    "Provisional developer share accrual", purchase_id=rec["id"])
        if rec["tax_remitter"] == "DEVELOPER":
            write_entry(dev["id"], "TAX_PASSTHROUGH", rec["developer_tax_remittance_cents"],
                        "VAT pass-through to developer", purchase_id=rec["id"])
        recompute_accrual(dev)
        recompute_risk(dev)
        touch(dev)
    return ok(public(rec))


@bp.post("/api/purchases/<purchase_id>/void")
def void(purchase_id):
    authenticate({"StorefrontService"})
    rec = lookup("purchases", purchase_id)
    if rec["payment_status"] != "AUTHORIZED":
        fail("ERR_INVALID_STATE", "Purchase is not AUTHORIZED.")
    rec["payment_status"] = "VOIDED"
    touch(rec)
    return ok(public(rec))
