"""Routes: customer orders and order lines."""
from flask import Blueprint, request

from mill.common import (
    ALL_ROLES,
    ApiError,
    D,
    endpoint,
    get_body,
    list_response,
    new_rec,
    now_iso,
    ok,
    pub,
    r0c,
    r3,
    req_enum,
    req_field,
    req_int,
    touch,
)
from mill.logic import (
    active_alloc_sum_line,
    allocs_of_line,
    bookings_of_line,
    eval_line,
    fefo_reserve,
    lines_of,
    plans_of_line,
    provisional_yards,
    recompute_cell_hours,
    recompute_lot,
    recompute_order_credit,
)
from mill.store import store

bp = Blueprint("orders", __name__)

WRITE_SALES = ["SalesRep"]
WRITE_QI = ["QualityInspector"]
DELIVERY_METHODS = ["LTL_FREIGHT", "WHITE_GLOVE"]
FABRIC_SOURCES = ["PLANT_STOCK", "COM"]


def _find_order(oid):
    rec = store.orders.get(oid)
    if not rec:
        raise ApiError("ERR_ORDER_NOT_FOUND", 404, "CustomerOrder not found")
    return rec


def _find_line(lid):
    rec = store.order_lines.get(lid)
    if not rec:
        raise ApiError("ERR_ORDER_LINE_NOT_FOUND", 404, "OrderLine not found")
    return rec


# ---------------------------------------------------------------------------
# CustomerOrder
# ---------------------------------------------------------------------------


@bp.post("/mill/customer-orders")
@endpoint(WRITE_SALES)
def create_order():
    b = get_body()
    order_number = req_field(b, "order_number")
    dealer_id = req_field(b, "dealer_id")
    ship_to_state = req_field(b, "ship_to_state")
    delivery_method = req_enum(b, "delivery_method", DELIVERY_METHODS)
    dealer = store.dealers.get(dealer_id)
    if not dealer:
        raise ApiError("ERR_DEALER_NOT_FOUND", 404, "DealerAccount not found")
    if any(o["order_number"] == order_number for o in store.orders.values()):
        raise ApiError("ERR_DUPLICATE_NATURAL_KEY", 409, f"order_number {order_number} already exists")
    if dealer["status"] != "ACTIVE":
        raise ApiError("ERR_DEALER_SUSPENDED", 409, "Dealer account is suspended")
    rec = new_rec()
    rec.update(
        {
            "order_number": order_number,
            "dealer_id": dealer_id,
            "ship_to_state": ship_to_state,
            "delivery_method": delivery_method,
            "status": "DRAFT",
            "common_flammability_standard": None,
            "subtotal_cents": 0,
            "com_credit_cents": 0,
            "total_cents": 0,
            "quality_result": "NONE",
            "confirmed_at": None,
        }
    )
    store.orders[rec["id"]] = rec
    return ok(pub(rec), 201)


@bp.get("/mill/customer-orders")
@endpoint(ALL_ROLES)
def list_orders():
    recs = list(store.orders.values())
    dealer_id = request.args.get("dealer_id")
    if dealer_id:
        recs = [o for o in recs if o["dealer_id"] == dealer_id]
    return list_response(recs)


@bp.get("/mill/customer-orders/<oid>")
@endpoint(ALL_ROLES)
def get_order(oid):
    return ok(pub(_find_order(oid)))


@bp.post("/mill/customer-orders/<oid>/confirm")
@endpoint(WRITE_SALES)
def confirm_order(oid):
    order = _find_order(oid)
    if order["status"] != "DRAFT":
        raise ApiError("ERR_ORDER_NOT_DRAFT", 409, "Order is not in DRAFT")
    lines = lines_of(oid)
    if not lines:
        raise ApiError("ERR_ORDER_HAS_NO_LINES", 422, "Order has no lines")
    dealer = store.dealers.get(order["dealer_id"])
    if not dealer or dealer["status"] != "ACTIVE":
        raise ApiError("ERR_DEALER_SUSPENDED", 409, "Dealer account is suspended")

    # Pricing (pinned evaluation order: per line in created_at ASC, per-unit round first).
    priced = []
    subtotal = 0
    for line in lines:
        model = store.product_models[line["model_id"]]
        spec = store.fabric_specs[line["fabric_spec_id"]]
        unit = r0c(D(model["base_price_cents"]) * (1 + D(line["matched_surcharge_pct"])))
        line_total = unit * line["quantity"]
        prov = provisional_yards(model, spec, line["quantity"])
        priced.append((line, unit, line_total, prov))
        subtotal += line_total

    # COM credit is zero at confirm (no allocations can exist on PENDING lines),
    # but compute it from the order's allocations for fidelity.
    total = subtotal - 0
    if total > dealer["credit_limit_cents"]:
        raise ApiError(
            "ERR_CREDIT_LIMIT_EXCEEDED",
            402,
            "Order total exceeds the dealer credit limit",
        )

    # Commit: pricing + provisional yardage on lines.
    for line, unit, line_total, prov in priced:
        line["unit_price_cents"] = unit
        line["line_total_cents"] = line_total
        line["required_yards_provisional"] = prov
        touch(line)
    order["subtotal_cents"] = subtotal
    touch(order)

    # FEFO reservation for PLANT_STOCK lines; COM lines wait for their lots.
    for line in lines:
        if line["fabric_source"] == "PLANT_STOCK":
            fefo_reserve(line)

    # Per-line shortfall evaluation: PENDING -> ALLOCATED | MATERIAL_SHORTFALL.
    for line in lines:
        active = active_alloc_sum_line(line["id"])
        line["allocated_yards"] = r3(active)
        req = D(line["required_yards_provisional"])
        line["shortfall_yards"] = r3(max(D("0"), req - active))
        line["status"] = "ALLOCATED" if active >= req else "MATERIAL_SHORTFALL"
        touch(line)

    recompute_order_credit(order)
    order["confirmed_at"] = now_iso()
    order["status"] = (
        "MATERIAL_HOLD"
        if any(l["status"] == "MATERIAL_SHORTFALL" for l in lines)
        else "CONFIRMED"
    )
    touch(order)
    return ok(pub(order))


@bp.post("/mill/customer-orders/<oid>/cancel")
@endpoint(WRITE_SALES)
def cancel_order(oid):
    order = _find_order(oid)
    if order["status"] not in ("DRAFT", "CONFIRMED", "MATERIAL_HOLD"):
        raise ApiError(
            "ERR_ORDER_NOT_CANCELLABLE",
            409,
            "Only DRAFT, CONFIRMED, or MATERIAL_HOLD orders can be cancelled",
        )
    for line in lines_of(oid):
        if line["status"] in ("COMPLETED", "CANCELLED"):
            continue
        line["status"] = "CANCELLED"
        touch(line)
        for alloc in allocs_of_line(line["id"]):
            if alloc["status"] == "ACTIVE":
                alloc["status"] = "RELEASED"
                touch(alloc)
                lot = store.material_lots.get(alloc["lot_id"])
                if lot:
                    recompute_lot(lot)
        for rq in store.requisitions.values():
            if rq["order_line_id"] == line["id"] and rq["status"] in ("OPEN", "PLACED"):
                rq["status"] = "CANCELLED"
                touch(rq)
        for plan in plans_of_line(line["id"]):
            if plan["status"] in ("DRAFT", "APPROVED"):
                plan["status"] = "VOID"
                touch(plan)
        for bkg in bookings_of_line(line["id"]):
            if bkg["status"] == "BOOKED":
                bkg["status"] = "RELEASED"
                touch(bkg)
                cell = store.cells.get(bkg["cell_id"])
                if cell:
                    recompute_cell_hours(cell)
    for cert in store.certificates.values():
        if cert["order_id"] == oid and cert["status"] == "DRAFT":
            cert["status"] = "VOID"
            touch(cert)
    order["status"] = "CANCELLED"
    touch(order)
    return ok(pub(order))


@bp.post("/mill/customer-orders/<oid>/pass-quality")
@endpoint(WRITE_QI)
def pass_quality(oid):
    order = _find_order(oid)
    if order["status"] != "QUALITY_REVIEW":
        raise ApiError(
            "ERR_ORDER_NOT_IN_QUALITY_REVIEW", 409, "Order is not in QUALITY_REVIEW"
        )
    certified = any(
        c["order_id"] == oid and c["status"] == "CERTIFIED"
        for c in store.certificates.values()
    )
    if not certified:
        raise ApiError(
            "ERR_COMPLIANCE_NOT_CERTIFIED",
            409,
            "A CERTIFIED compliance certificate is required to pass quality",
        )
    order["quality_result"] = "PASSED"
    for line in lines_of(oid):
        if line["status"] == "UPHOLSTERED":
            line["status"] = "COMPLETED"
            touch(line)
    order["status"] = "READY_TO_SHIP"
    touch(order)
    return ok(pub(order))


@bp.post("/mill/customer-orders/<oid>/fail-quality")
@endpoint(WRITE_QI)
def fail_quality(oid):
    # Cascade order: well-formedness (3) -> existence of path+body ids (4) -> state (5).
    b = get_body()
    rework_ids = b.get("rework_line_ids")
    if not isinstance(rework_ids, list) or not rework_ids:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "rework_line_ids must be a non-empty array"
        )
    order = _find_order(oid)
    targets = []
    for lid in rework_ids:
        line = store.order_lines.get(lid)
        if not line or line["order_id"] != oid:
            raise ApiError(
                "ERR_ORDER_LINE_NOT_FOUND", 404, f"OrderLine {lid} not found on this order"
            )
        targets.append(line)
    if order["status"] != "QUALITY_REVIEW":
        raise ApiError(
            "ERR_ORDER_NOT_IN_QUALITY_REVIEW", 409, "Order is not in QUALITY_REVIEW"
        )
    for line in targets:
        if line["status"] != "UPHOLSTERED":
            raise ApiError(
                "ERR_LINE_STAGE_MISMATCH",
                409,
                f"Line {line['id']} is not UPHOLSTERED",
            )
    order["quality_result"] = "FAILED"
    for line in targets:
        line["status"] = "SEWN"
        touch(line)
    order["status"] = "IN_PRODUCTION"
    touch(order)
    return ok(pub(order))


# ---------------------------------------------------------------------------
# OrderLine
# ---------------------------------------------------------------------------


@bp.post("/mill/order-lines")
@endpoint(WRITE_SALES)
def create_order_line():
    b = get_body()
    order_id = req_field(b, "order_id")
    model_id = req_field(b, "model_id")
    fabric_spec_id = req_field(b, "fabric_spec_id")
    fabric_source = req_enum(b, "fabric_source", FABRIC_SOURCES)
    finish_code = req_field(b, "finish_code")
    quantity = req_int(b, "quantity", minimum=1)

    order = store.orders.get(order_id)
    if not order:
        raise ApiError("ERR_ORDER_NOT_FOUND", 404, "CustomerOrder not found")
    model = store.product_models.get(model_id)
    if not model:
        raise ApiError("ERR_PRODUCT_MODEL_NOT_FOUND", 404, "ProductModel not found")
    spec = store.fabric_specs.get(fabric_spec_id)
    if not spec:
        raise ApiError("ERR_FABRIC_SPEC_NOT_FOUND", 404, "FabricSpec not found")

    if order["status"] != "DRAFT":
        raise ApiError("ERR_ORDER_NOT_DRAFT", 409, "Order is not in DRAFT")
    if model["status"] != "ACTIVE":
        raise ApiError("ERR_MODEL_NOT_ACTIVE", 409, "ProductModel is not ACTIVE")

    # Flammability standard pinning (business safety).
    if order["common_flammability_standard"] is None:
        order["common_flammability_standard"] = model["flammability_standard"]
        touch(order)
    elif order["common_flammability_standard"] != model["flammability_standard"]:
        raise ApiError(
            "ERR_FLAMMABILITY_STANDARD_MISMATCH",
            422,
            "Line model flammability standard differs from the order common standard",
        )

    # Option matrix: exact finish row beats the ANY wildcard row.
    grade = spec["grade"]
    exact = [
        r
        for r in model["option_rules"]
        if r.get("fabric_grade") == grade and r.get("finish_code") == finish_code
    ]
    wild = [
        r
        for r in model["option_rules"]
        if r.get("fabric_grade") == grade and r.get("finish_code") == "ANY"
    ]
    row = exact[0] if exact else (wild[0] if wild else None)
    if row is None or not row.get("allowed", False):
        raise ApiError(
            "ERR_OPTION_COMBO_RESTRICTED",
            422,
            "No allowed option-matrix row matches this fabric grade and finish code",
        )
    surcharge = row.get("surcharge_pct", 0)
    unit = r0c(D(model["base_price_cents"]) * (1 + D(surcharge)))
    line_total = unit * quantity

    rec = new_rec()
    rec.update(
        {
            "order_id": order_id,
            "model_id": model_id,
            "fabric_spec_id": fabric_spec_id,
            "fabric_source": fabric_source,
            "finish_code": finish_code,
            "quantity": quantity,
            "matched_surcharge_pct": surcharge,
            "unit_price_cents": unit,
            "line_total_cents": line_total,
            "required_yards_provisional": None,
            "required_yards_final": None,
            "allocated_yards": 0,
            "shortfall_yards": 0,
            "status": "PENDING",
        }
    )
    store.order_lines[rec["id"]] = rec
    return ok(pub(rec), 201)


@bp.get("/mill/order-lines")
@endpoint(ALL_ROLES)
def list_order_lines():
    recs = list(store.order_lines.values())
    for param in ("order_id", "model_id", "fabric_spec_id"):
        v = request.args.get(param)
        if v:
            recs = [l for l in recs if l[param] == v]
    return list_response(recs)


@bp.get("/mill/order-lines/<lid>")
@endpoint(ALL_ROLES)
def get_order_line(lid):
    return ok(pub(_find_line(lid)))
