from decimal import Decimal

from flask import Blueprint

import auth
import calc
import common
import response
import shape
import store
from errors import err
from shape import D, q

bp = Blueprint("fiber", __name__)
ZERO = Decimal("0")


# --------------------------------------------------- purchase orders ---
@bp.post("/fiber-purchase-orders")
def create_po():
    auth.require_roles("FiberBuyer")
    data = shape.body()
    shape.reject_unexpected_version(data)
    supplier_id = shape.get_str(data, "supplier_id")
    grade_code = shape.get_str(data, "fiber_grade_code")
    contracted = shape.get_num(data, "contracted_tons", exclusive_min=0, maximum=5000, places=2)
    basis = shape.get_enum(data, "index_basis", ["PRIOR_MONTH", "CURRENT_MONTH"])
    month = shape.get_str(data, "priced_for_month", pattern=r"[0-9]{4}-(0[1-9]|1[0-2])")
    delta = shape.get_num(data, "negotiated_delta_per_ton", minimum=-80, maximum=80, places=2)
    sup = store.get("suppliers", supplier_id)
    if sup is None:
        raise err("ERR_PARTY_NOT_FOUND", "supplier_id does not resolve")
    common.need_grade(grade_code)
    if sup["qualification_status"] == "SUSPENDED":
        raise err("ERR_SUPPLIER_SUSPENDED", "supplier is SUSPENDED")
    row = {
        "supplier_id": supplier_id,
        "fiber_grade_code": grade_code,
        "contracted_tons": contracted,
        "index_basis": basis,
        "priced_for_month": month,
        "negotiated_delta_per_ton": delta,
        "quoted_unit_price_per_ton": None,
        "fuel_surcharge_per_ton": None,
        "extended_contract_value": None,
        "index_quote_month_used": None,
        "pricing_revision_count": 0,
        "received_net_tons": 0.0,
        "status": "DRAFT",
    }
    store.insert("fiber_purchase_orders", row)
    return response.ok(common.view(row), 201)


def _need_po(pid):
    po = common.need("fiber_purchase_orders", pid, "ERR_PURCHASE_ORDER_NOT_FOUND")
    auth.own_supplier_or_403(po["supplier_id"])
    return po


@bp.get("/fiber-purchase-orders/<pid>")
def get_po(pid):
    auth.require_roles("FiberBuyer", "MillPlanner", "Supplier")
    return response.ok(common.view(_need_po(pid)))


@bp.get("/fiber-purchase-orders")
def list_po():
    auth.require_roles("FiberBuyer", "MillPlanner", "Supplier")
    limit, offset = shape.pagination()
    rows = common.filtered("fiber_purchase_orders", {
        "supplier_id": "supplier_id",
        "fiber_grade_code": "fiber_grade_code",
        "status": "status",
    })
    rows = common.scope_supplier(rows)
    return response.ok_list(common.views(shape.paginate(rows, limit, offset)), limit, offset, len(rows))


@bp.post("/fiber-purchase-orders/<pid>/price")
def price_po(pid):
    auth.require_roles("FiberBuyer")
    po = _need_po(pid)
    data = shape.body()
    expected = shape.get_version(data, "expected_purchase_order_version")
    if expected != po["version"]:
        raise err("ERR_STALE_PURCHASE_ORDER_VERSION", "expected_purchase_order_version is stale")
    if po["status"] != "DRAFT":
        raise err("ERR_PURCHASE_ORDER_INVALID_STATE", "purchase order is not DRAFT")
    sup = store.get("suppliers", po["supplier_id"])
    if sup["qualification_status"] == "SUSPENDED":
        raise err("ERR_SUPPLIER_SUSPENDED", "supplier is SUSPENDED")
    grade = common.need_grade(po["fiber_grade_code"])
    month = po["priced_for_month"] if po["index_basis"] == "CURRENT_MONTH" \
        else common.prior_month(po["priced_for_month"])
    quote = common.current_quote(grade["index_symbol"], month)
    if quote is None:
        raise err("ERR_INDEX_QUOTE_MISSING",
                  "no non-superseded quote for %s %s" % (grade["index_symbol"], month))
    res = calc.indexed_fiber_unit_price(quote["published_price_per_ton"],
                                        po["negotiated_delta_per_ton"],
                                        po["contracted_tons"],
                                        sup["freight_per_ton"])
    po["quoted_unit_price_per_ton"] = float(res["quoted_unit_price_per_ton"])
    po["fuel_surcharge_per_ton"] = float(res["fuel_surcharge_per_ton"])
    po["extended_contract_value"] = float(res["extended_contract_value"])
    po["index_quote_month_used"] = month
    po["status"] = "PRICED"
    store.touch("fiber_purchase_orders", po)
    return response.ok(common.view(po))


@bp.post("/fiber-purchase-orders/<pid>/withdraw-pricing")
def withdraw_pricing(pid):
    auth.require_roles("FiberBuyer")
    po = _need_po(pid)
    data = shape.body()
    expected = shape.get_version(data, "expected_purchase_order_version")
    if expected != po["version"]:
        raise err("ERR_STALE_PURCHASE_ORDER_VERSION", "expected_purchase_order_version is stale")
    if po["status"] != "PRICED":
        raise err("ERR_PURCHASE_ORDER_INVALID_STATE", "purchase order is not PRICED")
    if int(po["pricing_revision_count"]) >= 2:
        raise err("ERR_REPRICE_LIMIT_REACHED", "reprice limit reached")
    po["pricing_revision_count"] = int(po["pricing_revision_count"]) + 1
    po["quoted_unit_price_per_ton"] = None
    po["fuel_surcharge_per_ton"] = None
    po["extended_contract_value"] = None
    po["index_quote_month_used"] = None
    po["status"] = "DRAFT"
    store.touch("fiber_purchase_orders", po)
    return response.ok(common.view(po))


@bp.post("/fiber-purchase-orders/<pid>/confirm")
def confirm_po(pid):
    auth.require_roles("Supplier")
    po = _need_po(pid)
    data = shape.body()
    shape.reject_unexpected_version(data)
    if po["status"] != "PRICED":
        raise err("ERR_PURCHASE_ORDER_INVALID_STATE", "purchase order is not PRICED")
    sup = store.get("suppliers", po["supplier_id"])
    posture = sup["qualification_status"]
    if posture == "SUSPENDED":
        raise err("ERR_SUPPLIER_NOT_QUALIFIED", "supplier is SUSPENDED")
    if posture == "PROBATION" and D(po["contracted_tons"]) > Decimal("500.00"):
        raise err("ERR_SUPPLIER_NOT_QUALIFIED", "supplier on probation cannot confirm above 500.00 tons")
    po["status"] = "CONFIRMED"
    store.touch("fiber_purchase_orders", po)
    return response.ok(common.view(po))


@bp.post("/fiber-purchase-orders/<pid>/cancel")
def cancel_po(pid):
    auth.require_roles("FiberBuyer")
    po = _need_po(pid)
    data = shape.body()
    shape.reject_unexpected_version(data)
    if po["status"] not in ("DRAFT", "PRICED", "CONFIRMED"):
        raise err("ERR_PURCHASE_ORDER_INVALID_STATE", "purchase order cannot be cancelled")
    if D(po["received_net_tons"]) != ZERO:
        raise err("ERR_TONNAGE_ALREADY_BOOKED", "purchase order has accepted tonnage")
    po["status"] = "CANCELLED"
    for r in store.all_rows("fiber_receipts"):
        if r["purchase_order_id"] == po["id"] and r["status"] == "SAMPLED":
            r["status"] = "REJECTED"
            r["accepted_grade_code"] = None
            store.touch("fiber_receipts", r)
    store.touch("fiber_purchase_orders", po)
    return response.ok(common.view(po))


# --------------------------------------------------------- receipts ---
def _validate_sublots(raw):
    entries = shape.get_list(raw, "sublots", 1, 12)
    seen = set()
    prev_no = None
    out = []
    for i, e in enumerate(entries):
        if not isinstance(e, dict):
            raise err("ERR_VALIDATION", "sublots[%d] must be an object" % i)
        no = shape.get_int(e, "sublot_no", minimum=1)
        if no in seen:
            raise err("ERR_VALIDATION", "sublot_no must be unique")
        if prev_no is not None and no <= prev_no:
            raise err("ERR_VALIDATION", "sublot_no must be ascending")
        seen.add(no)
        prev_no = no
        out.append({
            "sublot_no": no,
            "gross_tons": shape.get_num(e, "gross_tons", minimum=0, places=3),
            "tare_tons": shape.get_num(e, "tare_tons", minimum=0, places=3),
            "moisture_pct": shape.get_num(e, "moisture_pct", minimum=0, places=2),
            "contamination_pct": shape.get_num(e, "contamination_pct", minimum=0, places=2),
        })
    return out


@bp.post("/fiber-purchase-orders/<pid>/receipts")
def create_receipt(pid):
    auth.require_roles("QualityLab")
    po = common.need("fiber_purchase_orders", pid, "ERR_PURCHASE_ORDER_NOT_FOUND")
    data = shape.body()
    shape.reject_unexpected_version(data)
    truck = shape.get_str(data, "truck_reference", min_len=1, max_len=40)
    sublots = _validate_sublots(data)
    grade = common.need_grade(po["fiber_grade_code"])
    computed = calc.receipt_net_tons(sublots, grade["max_moisture_pct"])
    row = {
        "purchase_order_id": po["id"],
        "supplier_id": po["supplier_id"],
        "truck_reference": truck,
        "sublots": sublots,
        "declared_grade_code": po["fiber_grade_code"],
        "net_tons": computed["net_tons"],
        "weighted_contamination_pct": computed["weighted_contamination_pct"],
        "weighted_moisture_pct": computed["weighted_moisture_pct"],
        "moisture_deduction_tons": computed["moisture_deduction_tons"],
        "accepted_grade_code": None,
        "sampled_by_user_id": auth.user_id(),
        "dispositioned_by_user_id": None,
        "status": "SAMPLED",
    }
    store.insert("fiber_receipts", row)
    return response.ok(common.view(row), 201)


@bp.get("/fiber-receipts/<rid>")
def get_receipt(rid):
    auth.require_roles("QualityLab", "FiberBuyer", "Supplier", "MillPlanner")
    row = common.need("fiber_receipts", rid, "ERR_RECEIPT_NOT_FOUND")
    auth.own_supplier_or_403(row["supplier_id"])
    return response.ok(common.view(row))


@bp.get("/fiber-receipts")
def list_receipts():
    auth.require_roles("QualityLab", "FiberBuyer", "Supplier", "MillPlanner")
    limit, offset = shape.pagination()
    rows = common.filtered("fiber_receipts", {
        "purchase_order_id": "purchase_order_id",
        "supplier_id": "supplier_id",
        "status": "status",
    })
    rows = common.scope_supplier(rows)
    return response.ok_list(common.views(shape.paginate(rows, limit, offset)), limit, offset, len(rows))


def _make_lot(receipt, grade_code):
    lot = {
        "receipt_id": receipt["id"],
        "grade_code": grade_code,
        "contamination_pct": receipt["weighted_contamination_pct"],
        "tons_received": receipt["net_tons"],
        "tons_consumed": 0.0,
        "tons_available": float(q(D(receipt["net_tons"]), 3)),
        "status": "AVAILABLE",
    }
    store.insert("fiber_inventory_lots", lot)
    return lot


@bp.post("/fiber-receipts/<rid>/disposition")
def disposition_receipt(rid):
    auth.require_roles("QualityLab")
    receipt = common.need("fiber_receipts", rid, "ERR_RECEIPT_NOT_FOUND")
    data = shape.body()
    shape.reject_unexpected_version(data)
    action = shape.get_enum(data, "disposition", ["ACCEPT", "DOWNGRADE", "REJECT"])
    if receipt["status"] != "SAMPLED":
        raise err("ERR_RECEIPT_INVALID_STATE", "receipt is not SAMPLED")
    if auth.user_id() == receipt["sampled_by_user_id"]:
        raise err("ERR_SOD_SAME_SAMPLER", "the sampler may not disposition the truck")
    grade = common.need_grade(receipt["declared_grade_code"])
    wc = D(receipt["weighted_contamination_pct"])
    wm = D(receipt["weighted_moisture_pct"])
    max_c = D(grade["max_contamination_pct"])
    max_m = D(grade["max_moisture_pct"])
    fallback_code = grade.get("downgrade_target_grade_code")
    fallback = common.grade_by_code(fallback_code) if fallback_code else None
    po = store.get("fiber_purchase_orders", receipt["purchase_order_id"])

    if action == "ACCEPT":
        if wc > max_c:
            raise err("ERR_DISPOSITION_NOT_PERMITTED", "contamination above the declared grade limit")
        if po["status"] not in ("CONFIRMED", "PARTIALLY_RECEIVED"):
            raise err("ERR_PURCHASE_ORDER_INVALID_STATE",
                      "purchase order is not CONFIRMED or PARTIALLY_RECEIVED")
        receipt["accepted_grade_code"] = receipt["declared_grade_code"]
        receipt["status"] = "ACCEPTED"
        receipt["dispositioned_by_user_id"] = auth.user_id()
        store.touch("fiber_receipts", receipt)
        _make_lot(receipt, receipt["accepted_grade_code"])
        common.advance_po_on_receipt(po)
        return response.ok(common.view(receipt))

    if action == "DOWNGRADE":
        if not (wc > max_c):
            raise err("ERR_DISPOSITION_NOT_PERMITTED", "contamination within the declared grade limit")
        if fallback is None:
            raise err("ERR_DISPOSITION_NOT_PERMITTED", "declared grade has no downgrade target")
        if wc > D(fallback["max_contamination_pct"]):
            raise err("ERR_DISPOSITION_NOT_PERMITTED", "contamination above the fallback grade limit")
        receipt["accepted_grade_code"] = fallback["grade_code"]
        receipt["status"] = "DOWNGRADED"
        receipt["dispositioned_by_user_id"] = auth.user_id()
        store.touch("fiber_receipts", receipt)
        _make_lot(receipt, fallback["grade_code"])
        common.advance_po_on_receipt(po)
        _strike_cascade(receipt)
        return response.ok(common.view(receipt))

    # REJECT
    contamination_route = wc > max_c and (fallback is None or wc > D(fallback["max_contamination_pct"]))
    moisture_route = wm > (max_m + Decimal("5.00"))
    if not (contamination_route or moisture_route):
        raise err("ERR_DISPOSITION_NOT_PERMITTED", "measured results do not justify rejection")
    receipt["accepted_grade_code"] = None
    receipt["status"] = "REJECTED"
    receipt["dispositioned_by_user_id"] = auth.user_id()
    store.touch("fiber_receipts", receipt)
    _strike_cascade(receipt)
    return response.ok(common.view(receipt))


def _strike_cascade(receipt):
    sup = store.get("suppliers", receipt["supplier_id"])
    posture, prev = common.recompute_supplier(sup)
    if posture == "SUSPENDED" and prev != "SUSPENDED":
        common.supplier_suspension_cascade(sup["id"])


# ---------------------------------------------------- inventory lots ---
@bp.get("/fiber-inventory-lots/<lid>")
def get_lot(lid):
    auth.require_roles("MachineOperator", "MillPlanner", "QualityLab")
    row = common.need("fiber_inventory_lots", lid, "ERR_INVENTORY_LOT_NOT_FOUND")
    return response.ok(common.view(row))


@bp.get("/fiber-inventory-lots")
def list_lots():
    auth.require_roles("MachineOperator", "MillPlanner", "QualityLab")
    limit, offset = shape.pagination()
    rows = common.filtered("fiber_inventory_lots", {
        "receipt_id": "receipt_id",
        "grade_code": "grade_code",
        "status": "status",
    })
    return response.ok_list(common.views(shape.paginate(rows, limit, offset)), limit, offset, len(rows))


# ------------------------------------------------------ fiber balance ---
@bp.get("/mill/fiber-balance")
def fiber_balance():
    auth.require_roles("MillPlanner", "FiberBuyer", "MachineOperator")
    recv = ZERO
    cons = ZERO
    avail = ZERO
    for lot in store.all_rows("fiber_inventory_lots"):
        recv += D(lot["tons_received"])
        cons += D(lot["tons_consumed"])
        avail += D(lot["tons_available"])
    recv = q(recv, 3)
    cons = q(cons, 3)
    avail = q(avail, 3)
    return response.ok({
        "total_received_tons": float(recv),
        "total_consumed_tons": float(cons),
        "total_available_tons": float(avail),
        "imbalance_tons": float(q(recv - cons - avail, 3)),
    })
