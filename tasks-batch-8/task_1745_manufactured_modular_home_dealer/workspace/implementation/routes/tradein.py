"""TradeInAppraisal intake, inspection, offer, customer decision, and the
reconditioning pipeline (PRD 3.9)."""

from flask import Blueprint, request

import calc
from db import bump, clock, create_record, store
from errors import fail
from middleware import ALL_ROLES, require
from response import ok, ok_list
from services import accept_trade_in, get_or_404, ser
from validate import Shape, get_body, pagination_params

bp = Blueprint("tradein", __name__)

DECLARED_CONDITIONS = ["A", "B", "C"]
DECISIONS = ["ACCEPT", "DECLINE"]
BLOCKING_APP_STATUSES = ("CONDITIONALLY_APPROVED", "APPROVED", "FUNDED")


def _list(rows, filters):
    limit, offset = pagination_params()
    rows = [r for r in rows if all(r.get(k) == v for k, v in filters.items())]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    return ok_list([ser(r) for r in rows[offset:offset + limit]], total, limit, offset)


@bp.post("/sales-orders/<rid>/trade-in-appraisals")
@require("SalesConsultant")
def create_trade_in_appraisal(rid, actor_id, actor_role):
    order = get_or_404(store.sales_orders, rid, "ERR_SALES_ORDER_NOT_FOUND", "Sales order")
    shape = Shape(get_body())
    shape.req_int("declared_model_year")
    shape.req_enum("declared_condition", DECLARED_CONDITIONS)
    shape.req_str("model_id")
    shape.opt_str("supersedes_appraisal_id")
    # (5) body foreign-key existence
    model = None
    if shape.ok("model_id"):
        model = store.home_models.get(shape.value("model_id"))
        if model is None:
            fail("ERR_HOME_MODEL_NOT_FOUND", "Home model not found")
    prior = None
    if shape.ok("supersedes_appraisal_id") and shape.value("supersedes_appraisal_id") is not None:
        prior = store.trade_in_appraisals.get(shape.value("supersedes_appraisal_id"))
        if prior is None:
            fail("ERR_TRADE_IN_APPRAISAL_NOT_FOUND", "Superseded appraisal not found")
        if prior["sales_order_id"] != order["id"]:
            shape._err("supersedes_appraisal_id", "must reference an appraisal of this order")
        elif prior["status"] != "OFFERED":
            fail("ERR_INVALID_STATE", "Only an OFFERED appraisal can be superseded")
    shape.raise_if_errors()
    provisional = calc.provisional_credit_cents(
        clock.now().year, shape.value("declared_model_year"),
        shape.value("declared_condition"))
    rec = create_record(store.trade_in_appraisals, {
        "sales_order_id": order["id"],
        "model_id": model["id"],
        "declared_model_year": shape.value("declared_model_year"),
        "declared_condition": shape.value("declared_condition"),
        "provisional_credit_cents": provisional,
        "appraised_value_cents": None,
        "reconditioning_cost_cents": None,
        "condition_grade": None,
        "final_credit_cents": None,
        "supersedes_appraisal_id": prior["id"] if prior is not None else None,
        "trade_in_unit_id": None,
        "status": "DRAFT",
    })
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        bump(prior)
    return ok(ser(rec), 201)


@bp.get("/sales-orders/<rid>/trade-in-appraisals")
@require(*ALL_ROLES)
def list_order_appraisals(rid, actor_id, actor_role):
    order = get_or_404(store.sales_orders, rid, "ERR_SALES_ORDER_NOT_FOUND", "Sales order")
    return _list([a for a in store.trade_in_appraisals.values()
                  if a["sales_order_id"] == order["id"]], {})


@bp.get("/trade-in-appraisals/<rid>")
@require(*ALL_ROLES)
def get_appraisal(rid, actor_id, actor_role):
    return ok(ser(get_or_404(store.trade_in_appraisals, rid,
                             "ERR_TRADE_IN_APPRAISAL_NOT_FOUND", "Trade-in appraisal")))


@bp.get("/trade-in-appraisals")
@require(*ALL_ROLES)
def list_appraisals(actor_id, actor_role):
    filters = {}
    for k in ("supersedes_appraisal_id", "model_id", "status"):
        if request.args.get(k) is not None:
            filters[k] = request.args.get(k)
    return _list(store.trade_in_appraisals.values(), filters)


@bp.get("/home-units/<rid>/trade-in-appraisals")
@require(*ALL_ROLES)
def list_unit_appraisals(rid, actor_id, actor_role):
    unit = get_or_404(store.home_units, rid, "ERR_HOME_UNIT_NOT_FOUND", "Home unit")
    return _list([a for a in store.trade_in_appraisals.values()
                  if a["trade_in_unit_id"] == unit["id"]], {})


def _get_appraisal(rid):
    return get_or_404(store.trade_in_appraisals, rid, "ERR_TRADE_IN_APPRAISAL_NOT_FOUND",
                      "Trade-in appraisal")


@bp.post("/trade-in-appraisals/<rid>/inspect")
@require("Appraiser")
def inspect_appraisal(rid, actor_id, actor_role):
    appraisal = _get_appraisal(rid)
    if appraisal["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Only a DRAFT appraisal can be inspected")
    shape = Shape(get_body())
    shape.req_int("appraised_value_cents", minimum=0)
    shape.req_int("reconditioning_cost_cents", minimum=0)
    shape.req_enum("condition_grade", DECLARED_CONDITIONS)
    shape.raise_if_errors()
    appraisal["appraised_value_cents"] = shape.value("appraised_value_cents")
    appraisal["reconditioning_cost_cents"] = shape.value("reconditioning_cost_cents")
    appraisal["condition_grade"] = shape.value("condition_grade")
    appraisal["final_credit_cents"] = calc.final_credit_cents(
        shape.value("appraised_value_cents"), shape.value("reconditioning_cost_cents"))
    appraisal["status"] = "INSPECTED"
    bump(appraisal)
    return ok(ser(appraisal))


@bp.post("/trade-in-appraisals/<rid>/offer")
@require("Appraiser")
def offer_appraisal(rid, actor_id, actor_role):
    appraisal = _get_appraisal(rid)
    if appraisal["status"] != "INSPECTED":
        fail("ERR_INVALID_STATE", "Only an INSPECTED appraisal can be offered")
    appraisal["status"] = "OFFERED"
    bump(appraisal)
    return ok(ser(appraisal))


@bp.post("/trade-in-appraisals/<rid>/decide")
@require("Customer")
def decide_appraisal(rid, actor_id, actor_role):
    appraisal = _get_appraisal(rid)
    # (3) ownership: only the order's own customer decides
    order = store.sales_orders.get(appraisal["sales_order_id"])
    if order is None or order["customer_id"] != actor_id:
        fail("ERR_UNAUTHORIZED", "Customers may act only on their own orders")
    # (7) state precondition
    if appraisal["status"] != "OFFERED":
        fail("ERR_INVALID_STATE", "Only an OFFERED appraisal can be decided")
    shape = Shape(get_body())
    shape.req_enum("decision", DECISIONS)
    shape.raise_if_errors()
    if shape.value("decision") == "DECLINE":
        appraisal["status"] = "DECLINED"
        bump(appraisal)
        return ok(ser(appraisal))
    # ACCEPT is blocked while credit terms are locked
    if any(a["sales_order_id"] == order["id"] and a["status"] in BLOCKING_APP_STATUSES
           for a in store.financing_applications.values()):
        fail("ERR_INVALID_STATE",
             "A financing application with locked credit terms blocks acceptance")
    accept_trade_in(appraisal)
    return ok(ser(appraisal))


@bp.post("/trade-in-appraisals/<rid>/start-reconditioning")
@require("Appraiser")
def start_reconditioning(rid, actor_id, actor_role):
    appraisal = _get_appraisal(rid)
    if appraisal["status"] != "ACCEPTED":
        fail("ERR_INVALID_STATE", "Only an ACCEPTED appraisal can enter reconditioning")
    unit = store.home_units.get(appraisal["trade_in_unit_id"])
    if unit is None or unit["unit_kind"] != "TRADE_IN" or unit["status"] != "AT_DEALER":
        fail("ERR_INVALID_STATE", "Trade-in unit is not AT_DEALER")
    appraisal["status"] = "RECONDITIONING"
    bump(appraisal)
    unit["status"] = "RECONDITIONING"
    bump(unit)
    return ok(ser(appraisal))


@bp.post("/trade-in-appraisals/<rid>/complete-reconditioning")
@require("Appraiser")
def complete_reconditioning(rid, actor_id, actor_role):
    appraisal = _get_appraisal(rid)
    if appraisal["status"] != "RECONDITIONING":
        fail("ERR_INVALID_STATE", "Only a RECONDITIONING appraisal can be completed")
    unit = store.home_units.get(appraisal["trade_in_unit_id"])
    if unit is None or unit["status"] != "RECONDITIONING":
        fail("ERR_INVALID_STATE", "Trade-in unit is not RECONDITIONING")
    appraisal["status"] = "RETAIL_READY"
    bump(appraisal)
    unit["status"] = "RETAIL_READY"
    bump(unit)
    return ok(ser(appraisal))
