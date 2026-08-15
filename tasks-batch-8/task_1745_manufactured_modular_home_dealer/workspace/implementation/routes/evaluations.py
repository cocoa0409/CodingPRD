"""SiteEvaluation scheduling, findings, approval/rejection (PRD 3.4).
Creation is OCC-guarded on SalesOrder.version (PRD 2.7)."""

from flask import Blueprint

from db import bump, clock, create_record, store
from errors import fail
from middleware import ALL_ROLES, require
from response import ok, ok_list
from services import (bubble_evaluation_approved, bubble_evaluation_rejected,
                      get_or_404, ser)
from validate import Shape, get_body, pagination_params

bp = Blueprint("evaluations", __name__)

FOUNDATION_TYPES = ["SLAB", "CRAWL_SPACE", "PIERS", "BASEMENT"]
FINDINGS_RESULTS = ["PASS", "CONDITIONAL", "FAIL"]
EVALUATOR_DAILY_CAP = 3


def _list(rows):
    limit, offset = pagination_params()
    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    return ok_list([ser(r) for r in rows[offset:offset + limit]], total, limit, offset)


@bp.post("/sales-orders/<rid>/site-evaluations")
@require("SalesConsultant")
def create_site_evaluation(rid, actor_id, actor_role):
    order = get_or_404(store.sales_orders, rid, "ERR_SALES_ORDER_NOT_FOUND", "Sales order")
    shape = Shape(get_body())
    shape.req_dt("scheduled_date")
    shape.req_str("evaluator_id")
    shape.req_int("expected_sales_order_version")
    # (6) optimistic concurrency on the parent order
    if shape.ok("expected_sales_order_version"):
        if shape.value("expected_sales_order_version") != order["version"]:
            fail("ERR_STALE_VERSION",
                 "expected_sales_order_version does not match the order's current version")
    # (16) evaluator capacity: at most 3 open evaluations per calendar date
    if shape.ok("scheduled_date") and shape.ok("evaluator_id"):
        target_date = shape.value("scheduled_date").date()
        held = sum(
            1 for e in store.site_evaluations.values()
            if e["evaluator_id"] == shape.value("evaluator_id")
            and e["status"] in ("SCHEDULED", "FINDINGS_RECORDED")
            and e["scheduled_date"].date() == target_date)
        if held >= EVALUATOR_DAILY_CAP:
            fail("ERR_EVALUATOR_CAPACITY_EXCEEDED",
                 "Evaluator already holds 3 open evaluations on that date")
    # (22) no past scheduling against the logical clock date
    if shape.ok("scheduled_date"):
        if shape.value("scheduled_date").date() < clock.now().date():
            fail("ERR_SCHEDULE_IN_PAST", "scheduled_date precedes the current clock date")
    shape.raise_if_errors()
    # supersede the order's prior non-terminal evaluations
    for e in store.site_evaluations.values():
        if (e["sales_order_id"] == order["id"]
                and e["status"] in ("SCHEDULED", "FINDINGS_RECORDED")):
            e["status"] = "SUPERSEDED"
            bump(e)
    rec = create_record(store.site_evaluations, {
        "sales_order_id": order["id"],
        "evaluator_id": shape.value("evaluator_id"),
        "scheduled_date": shape.value("scheduled_date"),
        "foundation_type": None,
        "utilities_verified": None,
        "permit_number": None,
        "findings_result": None,
        "install_estimate_cents": None,
        "status": "SCHEDULED",
        "evaluated_by": None,
    })
    bump(order)
    return ok(ser(rec), 201)


@bp.get("/sales-orders/<rid>/site-evaluations")
@require(*ALL_ROLES)
def list_site_evaluations(rid, actor_id, actor_role):
    order = get_or_404(store.sales_orders, rid, "ERR_SALES_ORDER_NOT_FOUND", "Sales order")
    return _list([e for e in store.site_evaluations.values()
                  if e["sales_order_id"] == order["id"]])


@bp.get("/site-evaluations/<rid>")
@require(*ALL_ROLES)
def get_site_evaluation(rid, actor_id, actor_role):
    return ok(ser(get_or_404(store.site_evaluations, rid,
                             "ERR_SITE_EVALUATION_NOT_FOUND", "Site evaluation")))


@bp.post("/site-evaluations/<rid>/record-findings")
@require("SiteEvaluator")
def record_findings(rid, actor_id, actor_role):
    ev = get_or_404(store.site_evaluations, rid, "ERR_SITE_EVALUATION_NOT_FOUND",
                    "Site evaluation")
    # (3) ownership: only the assigned evaluator may record findings
    if actor_id != ev["evaluator_id"]:
        fail("ERR_UNAUTHORIZED", "Findings may be recorded only by the assigned evaluator")
    # (7) state precondition: SCHEDULED evaluation on a PENDING_SITE_EVAL order
    order = store.sales_orders.get(ev["sales_order_id"])
    if ev["status"] != "SCHEDULED" or order is None or order["deal_status"] != "PENDING_SITE_EVAL":
        fail("ERR_INVALID_STATE",
             "Evaluation is not SCHEDULED or the order is not PENDING_SITE_EVAL")
    shape = Shape(get_body())
    shape.req_enum("foundation_type", FOUNDATION_TYPES)
    shape.req_bool("utilities_verified")
    shape.opt_str("permit_number")
    shape.req_enum("findings_result", FINDINGS_RESULTS)
    shape.req_int("install_estimate_cents", minimum=0)
    shape.raise_if_errors()
    ev["foundation_type"] = shape.value("foundation_type")
    ev["utilities_verified"] = shape.value("utilities_verified")
    ev["permit_number"] = shape.value("permit_number")
    ev["findings_result"] = shape.value("findings_result")
    ev["install_estimate_cents"] = shape.value("install_estimate_cents")
    ev["evaluated_by"] = actor_id
    ev["status"] = "FINDINGS_RECORDED"
    bump(ev)
    return ok(ser(ev))


@bp.post("/site-evaluations/<rid>/approve")
@require("InstallationManager")
def approve_evaluation(rid, actor_id, actor_role):
    ev = get_or_404(store.site_evaluations, rid, "ERR_SITE_EVALUATION_NOT_FOUND",
                    "Site evaluation")
    if ev["status"] != "FINDINGS_RECORDED":
        fail("ERR_INVALID_STATE", "Evaluation is not FINDINGS_RECORDED")
    if ev["findings_result"] not in ("PASS", "CONDITIONAL"):
        fail("ERR_INVALID_STATE", "A FAIL evaluation cannot be approved")
    ev["status"] = "APPROVED"
    bump(ev)
    bubble_evaluation_approved(ev)
    return ok(ser(ev))


@bp.post("/site-evaluations/<rid>/reject")
@require("InstallationManager")
def reject_evaluation(rid, actor_id, actor_role):
    ev = get_or_404(store.site_evaluations, rid, "ERR_SITE_EVALUATION_NOT_FOUND",
                    "Site evaluation")
    if ev["status"] != "FINDINGS_RECORDED":
        fail("ERR_INVALID_STATE", "Evaluation is not FINDINGS_RECORDED")
    ev["status"] = "REJECTED"
    bump(ev)
    bubble_evaluation_rejected(ev)
    return ok(ser(ev))
