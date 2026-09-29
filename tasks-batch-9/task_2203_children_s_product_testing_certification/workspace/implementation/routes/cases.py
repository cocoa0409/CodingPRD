"""Noncompliance response: stop-distribution, retests, closure (PRD 3.9)."""

from flask import Blueprint

import auth
import clock
import db
import paging
import refs
import response
import validation
from errors import ApiError
from routes.orders import commit_order, price_order, require_budget
from routes.products import guard_not_archived
from services import calc, engine, gates

bp = Blueprint("cases", __name__)

CASE_STATES = {
    "OPEN",
    "STOP_DISTRIBUTION_ISSUED",
    "RETEST_ORDERED",
    "RETEST_FAILED",
    "RETEST_PASSED",
    "CORRECTIVE_ACTION_APPROVED",
    "CLOSED",
    "ESCALATED_RECALL",
}
SCOPE_VARIANTS = {"BATCH_SCOPED", "LOT_TRACEBACK"}
CASE_READ_ROLES = (
    "ComplianceAdministrator",
    "TestCoordinator",
    "CertificationOfficer",
    "DistributionManager",
)


@bp.get("/noncompliance-cases/<case_id>")
def get_case(case_id):
    auth.require_roles(*CASE_READ_ROLES)
    row = refs.case(case_id)
    return response.object_response(db.serialize("noncompliance_cases", row))


@bp.get("/noncompliance-cases")
def list_cases():
    auth.require_roles(*CASE_READ_ROLES)
    product_id = validation.query_string("product_id")
    triggering_test_order_id = validation.query_string("triggering_test_order_id")
    failed_rule_id = validation.query_string("failed_rule_id")
    active_retest_order_id = validation.query_string("active_retest_order_id")
    case_state = validation.query_enum("case_state", CASE_STATES)
    return paging.build(
        "noncompliance_cases",
        [
            paging.eq_filter("product_id", product_id),
            paging.eq_filter("triggering_test_order_id", triggering_test_order_id),
            paging.eq_filter("failed_rule_id", failed_rule_id),
            paging.eq_filter("active_retest_order_id", active_retest_order_id),
            paging.eq_filter("case_state", case_state),
        ],
    )


@bp.post("/noncompliance-cases/<case_id>/issue-stop-distribution")
def issue_stop_distribution(case_id):
    auth.require_roles("DistributionManager")
    body = validation.json_body()
    scope_variant = validation.enum_field(body, "scope_variant", SCOPE_VARIANTS)
    case = refs.case(case_id)
    product = refs.product(case["product_id"])
    guard_not_archived(product)
    if case["case_state"] != "OPEN":
        raise ApiError("ERR_CASE_STATE_INVALID")
    batches = db.find("production_batches", product_id=product["id"])
    if not any(b["distribution_state"] in ("HELD", "RELEASED") for b in batches):
        raise ApiError("ERR_CASE_STATE_INVALID")

    failing_order = db.get("test_orders", case["triggering_test_order_id"])
    case["case_state"] = "STOP_DISTRIBUTION_ISSUED"
    case["scope_variant"] = scope_variant
    case["scope_units"] = calc.corrective_scope_units(
        product, case, failing_order, scope_variant
    )
    engine.bump("noncompliance_cases", case)

    cutoff_batches = _in_scope_batches(product, case, failing_order, scope_variant)
    for batch in cutoff_batches:
        if batch["distribution_state"] in ("HELD", "RELEASED"):
            batch["distribution_state"] = "STOP_DISTRIBUTION"
            engine.bump("production_batches", batch)
    engine.recompute_distribution(product)
    engine.bump("products", product)
    return response.object_response(db.serialize("noncompliance_cases", case))


def _in_scope_batches(product, case, failing_order, scope_variant):
    if scope_variant == "BATCH_SCOPED":
        cutoff = failing_order["window_start"] if failing_order else product["created_at"]
    else:
        cutoff = None
        for order in db.all_rows("test_orders"):
            if (
                order["product_id"] == product["id"]
                and order["rule_id"] == case["failed_rule_id"]
                and order["order_state"] == "REPORTED_PASS"
                and order["reported_at"] is not None
                and failing_order is not None
                and failing_order["reported_at"] is not None
                and order["reported_at"] < failing_order["reported_at"]
            ):
                if cutoff is None or order["reported_at"] > cutoff:
                    cutoff = order["reported_at"]
        if cutoff is None:
            cutoff = product["created_at"]
    out = []
    for batch in db.find("production_batches", product_id=product["id"]):
        if batch["distribution_state"] == "DESTROYED":
            continue
        if batch["produced_on"] >= cutoff:
            out.append(batch)
    return out


@bp.post("/noncompliance-cases/<case_id>/order-retest")
def order_retest(case_id):
    auth.require_roles("TestCoordinator")
    body = validation.json_body()
    sampling_plan_id = validation.id_field(body, "sampling_plan_id")
    laboratory_id = validation.id_field(body, "laboratory_id")
    sample_count = validation.int_field(body, "sample_count", minimum=1)
    window_start = validation.datetime_field(body, "window_start")
    window_end = validation.datetime_field(body, "window_end")
    expedite_requested = validation.bool_field(
        body, "expedite_requested", required=False, default=False
    )

    case = refs.case(case_id)
    product = refs.product(case["product_id"])
    plan = refs.require_child_of("sampling_plans", sampling_plan_id, product["id"])
    laboratory = refs.laboratory(laboratory_id)
    guard_not_archived(product)
    if case["case_state"] not in ("STOP_DISTRIBUTION_ISSUED", "RETEST_FAILED"):
        raise ApiError("ERR_CASE_STATE_INVALID")

    if calc.retest_threshold_reached(case):
        return _escalate_to_recall(case, product)

    rule = refs.rule(case["failed_rule_id"])
    gates.require_not_manufacturer_owned(laboratory)
    now = clock.now()
    if not window_end > window_start or window_start < now:
        raise ApiError("ERR_WINDOW_INVALID")
    if calc.slot_capacity_exceeded(laboratory, window_start, window_end):
        raise ApiError("ERR_LAB_SLOT_CAPACITY_EXCEEDED")
    if sample_count > plan["units_available"]:
        raise ApiError("ERR_SAMPLE_UNITS_EXHAUSTED")
    line_fee, invoice_total = price_order(
        rule, laboratory, sample_count, expedite_requested, product["evidence_path"]
    )
    require_budget(product, invoice_total)

    first_round = case["retest_round_count"] == 0
    order = db.insert(
        "test_orders",
        {
            "product_id": product["id"],
            "sampling_plan_id": plan["id"],
            "laboratory_id": laboratory["id"],
            "rule_id": rule["id"],
            "sample_count": sample_count,
            "window_start": window_start,
            "window_end": window_end,
            "order_state": "SCHEDULED",
            "ordered_by_user_id": auth.current_user_id(),
            "is_retest": True,
            "retest_case_id": case["id"],
            "line_fee_cents": line_fee,
            "invoice_total_cents": invoice_total,
            "expedite_requested": expedite_requested,
            "measured_value": None,
            "result": None,
            "reported_at": None,
            "reported_by_user_id": None,
        },
    )
    commit_order(order, plan, laboratory)

    case["case_state"] = "RETEST_ORDERED"
    case["active_retest_order_id"] = order["id"]
    case["retest_round_count"] += 1
    engine.bump("noncompliance_cases", case)

    if first_round and product["certification_state"] == "SUSPENDED":
        product["certification_state"] = "REMEDIATION"
        engine.bump("products", product)
    return response.object_response(db.serialize("noncompliance_cases", case))


def _escalate_to_recall(case, product):
    failing_order = db.get("test_orders", case["triggering_test_order_id"])
    case["case_state"] = "ESCALATED_RECALL"
    case["scope_variant"] = "LOT_TRACEBACK"
    case["scope_units"] = calc.corrective_scope_units(
        product, case, failing_order, "LOT_TRACEBACK"
    )
    engine.bump("noncompliance_cases", case)

    for batch in db.find("production_batches", product_id=product["id"]):
        if batch["distribution_state"] in ("HELD", "RELEASED", "STOP_DISTRIBUTION"):
            batch["distribution_state"] = "DESTROYED"
            engine.bump("production_batches", batch)
    engine.recompute_distribution(product)
    engine.bump("products", product)
    return response.object_response(db.serialize("noncompliance_cases", case))


@bp.post("/noncompliance-cases/<case_id>/corrective-actions")
def record_corrective_action(case_id):
    auth.require_roles("CertificationOfficer")
    body = validation.json_body()
    expected_case_version = validation.int_field(
        body, "expected_case_version", minimum=1
    )
    corrective_action_ref = validation.string_field(
        body, "corrective_action_ref", min_len=1, max_len=200
    )
    case = refs.case(case_id)
    product = refs.product(case["product_id"])
    guard_not_archived(product)
    if case["case_state"] not in ("RETEST_PASSED", "CORRECTIVE_ACTION_APPROVED"):
        raise ApiError("ERR_CASE_STATE_INVALID")
    if expected_case_version != case["version"]:
        raise ApiError("ERR_STALE_CASE_VERSION")

    case["case_state"] = "CORRECTIVE_ACTION_APPROVED"
    case["corrective_action_ref"] = corrective_action_ref
    case["corrective_action_revision"] += 1
    engine.bump("noncompliance_cases", case)
    return response.object_response(db.serialize("noncompliance_cases", case))


@bp.post("/noncompliance-cases/<case_id>/close")
def close_case(case_id):
    auth.require_roles("CertificationOfficer")
    case = refs.case(case_id)
    product = refs.product(case["product_id"])
    guard_not_archived(product)
    if case["case_state"] != "CORRECTIVE_ACTION_APPROVED":
        raise ApiError("ERR_CASE_STATE_INVALID")
    for batch in db.find("production_batches", product_id=product["id"]):
        if batch["distribution_state"] != "STOP_DISTRIBUTION":
            continue
        if not batch["tracking_label_compliant"]:
            raise ApiError("ERR_TRACKING_LABEL_NONCOMPLIANT")
    if auth.current_user_id() == case["opened_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    engine.cascade_case_closure(case, product, auth.current_user_id())
    return response.object_response(db.serialize("noncompliance_cases", case))
