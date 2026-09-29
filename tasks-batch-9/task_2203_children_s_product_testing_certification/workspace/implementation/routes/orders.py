"""Test order booking and execution (PRD 3.6)."""

from flask import Blueprint

import auth
import clock
import db
import paging
import refs
import response
import validation
from errors import ApiError
from routes.products import guard_not_archived
from services import calc, engine, gates

bp = Blueprint("orders", __name__)

ORDER_STATES = {
    "SCHEDULED",
    "IN_TESTING",
    "REPORTED_PASS",
    "REPORTED_FAIL",
    "CANCELLED",
    "INVALIDATED",
}
ORDER_READ_ROLES = (
    "ComplianceAdministrator",
    "TestCoordinator",
    "CertificationOfficer",
    "LaboratoryUser",
)
BOOKABLE_PRODUCT_STATES = (
    "SCOPED",
    "EVIDENCE_RELIANCE",
    "FULL_TEST_PROGRAM",
    "EVIDENCE_COMPLETE",
    "CERTIFIED",
    "REMEDIATION",
)


def price_order(rule, laboratory, sample_count, expedite_requested, evidence_path):
    accreditation = gates.find_covering_accreditation(
        laboratory["id"], rule["test_method_code"]
    )
    line_fee = calc.line_fee_cents(rule, laboratory, accreditation, sample_count)
    invoice_total = calc.invoice_total_cents(
        line_fee, expedite_requested, evidence_path
    )
    return line_fee, invoice_total


def product_outstanding_fees(product):
    total = 0
    for order in db.all_rows("test_orders"):
        if order["product_id"] != product["id"]:
            continue
        if order["order_state"] in calc.COMMITTING_ORDER_STATES:
            total += order["invoice_total_cents"]
    return total


def require_budget(product, candidate_invoice_total):
    if product_outstanding_fees(product) + candidate_invoice_total > product[
        "testing_budget_cents"
    ]:
        raise ApiError("ERR_PRODUCT_TESTING_BUDGET_EXCEEDED")


def commit_order(order, plan, laboratory):
    calc.recompute_plan_ledger(plan)
    engine.bump("sampling_plans", plan)
    laboratory["billed_fee_cents_total"] += order["invoice_total_cents"]
    engine.bump("laboratories", laboratory)


@bp.post("/test-orders")
def book_order():
    auth.require_roles("TestCoordinator")
    body = validation.json_body()
    product_id = validation.id_field(body, "product_id")
    sampling_plan_id = validation.id_field(body, "sampling_plan_id")
    laboratory_id = validation.id_field(body, "laboratory_id")
    rule_id = validation.id_field(body, "rule_id")
    sample_count = validation.int_field(body, "sample_count", minimum=1)
    window_start = validation.datetime_field(body, "window_start")
    window_end = validation.datetime_field(body, "window_end")
    expedite_requested = validation.bool_field(
        body, "expedite_requested", required=False, default=False
    )

    product = refs.product(product_id)
    plan = refs.require_child_of("sampling_plans", sampling_plan_id, product["id"])
    laboratory = refs.laboratory(laboratory_id)
    rule = refs.rule(rule_id)

    guard_not_archived(product)
    if product["certification_state"] not in BOOKABLE_PRODUCT_STATES:
        raise ApiError("ERR_PRODUCT_STATE_INVALID")
    if plan["plan_state"] not in ("ACTIVE", "RESAMPLE_DUE"):
        raise ApiError("ERR_PLAN_STATE_INVALID")

    gates.require_not_barred(laboratory)
    gates.require_attestation_current(laboratory)
    gates.require_method_accreditation(laboratory, rule)

    now = clock.now()
    if not window_end > window_start or window_start < now:
        raise ApiError("ERR_WINDOW_INVALID")
    if calc.slot_capacity_exceeded(laboratory, window_start, window_end):
        raise ApiError("ERR_LAB_SLOT_CAPACITY_EXCEEDED")
    if rule["id"] not in product["required_rule_ids"]:
        raise ApiError("ERR_RULE_NOT_APPLICABLE_TO_PRODUCT")
    if product["evidence_path"] == "COMPONENT_RELIANCE" and calc._rule_covered(
        product, rule["id"]
    ):
        raise ApiError("ERR_EVIDENCE_PATH_MISMATCH")
    if sample_count > plan["units_available"]:
        raise ApiError("ERR_SAMPLE_UNITS_EXHAUSTED")

    line_fee, invoice_total = price_order(
        rule, laboratory, sample_count, expedite_requested, product["evidence_path"]
    )
    require_budget(product, invoice_total)

    row = db.insert(
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
            "is_retest": False,
            "retest_case_id": None,
            "line_fee_cents": line_fee,
            "invoice_total_cents": invoice_total,
            "expedite_requested": expedite_requested,
            "measured_value": None,
            "result": None,
            "reported_at": None,
            "reported_by_user_id": None,
        },
    )
    commit_order(row, plan, laboratory)
    return response.object_response(db.serialize("test_orders", row), 201)


@bp.get("/test-orders/<order_id>")
def get_order(order_id):
    auth.require_roles(*ORDER_READ_ROLES)
    row = refs.order(order_id)
    return response.object_response(db.serialize("test_orders", row))


@bp.get("/test-orders")
def list_orders():
    auth.require_roles(*ORDER_READ_ROLES)
    product_id = validation.query_string("product_id")
    sampling_plan_id = validation.query_string("sampling_plan_id")
    laboratory_id = validation.query_string("laboratory_id")
    rule_id = validation.query_string("rule_id")
    order_state = validation.query_enum("order_state", ORDER_STATES)
    is_retest = validation.query_bool("is_retest")
    return paging.build(
        "test_orders",
        [
            paging.eq_filter("product_id", product_id),
            paging.eq_filter("sampling_plan_id", sampling_plan_id),
            paging.eq_filter("laboratory_id", laboratory_id),
            paging.eq_filter("rule_id", rule_id),
            paging.eq_filter("order_state", order_state),
            paging.eq_filter("is_retest", is_retest),
        ],
    )


@bp.post("/test-orders/<order_id>/start-testing")
def start_testing(order_id):
    auth.require_roles("LaboratoryUser")
    early = db.get("test_orders", order_id)
    if early is not None:
        auth.require_assigned_lab(early)
    order = refs.order(order_id)
    product = refs.product(order["product_id"])
    laboratory = refs.laboratory(order["laboratory_id"])
    rule = refs.rule(order["rule_id"])

    guard_not_archived(product)
    if order["order_state"] != "SCHEDULED":
        raise ApiError("ERR_ORDER_STATE_INVALID")
    gates.require_not_barred(laboratory)
    gates.require_attestation_current(laboratory)
    gates.require_method_accreditation(laboratory, rule)

    order["order_state"] = "IN_TESTING"
    engine.bump("test_orders", order)
    return response.object_response(db.serialize("test_orders", order))


@bp.post("/test-orders/<order_id>/report-result")
def report_result(order_id):
    auth.require_roles("LaboratoryUser")
    early = db.get("test_orders", order_id)
    if early is not None:
        auth.require_assigned_lab(early)
    body = validation.json_body()
    measured_value = validation.number_field(body, "measured_value")
    order = refs.order(order_id)
    product = refs.product(order["product_id"])
    rule = refs.rule(order["rule_id"])

    guard_not_archived(product)
    if order["order_state"] != "IN_TESTING":
        raise ApiError("ERR_ORDER_STATE_INVALID")

    result = calc.test_result(rule, measured_value)
    order["measured_value"] = measured_value
    order["result"] = result
    order["reported_at"] = clock.now()
    order["reported_by_user_id"] = auth.current_user_id()
    order["order_state"] = "REPORTED_PASS" if result == "PASS" else "REPORTED_FAIL"
    engine.bump("test_orders", order)

    if result == "PASS":
        if order["is_retest"] and order["retest_case_id"] is not None:
            case = db.get("noncompliance_cases", order["retest_case_id"])
            if (
                case is not None
                and case["active_retest_order_id"] == order["id"]
                and case["case_state"] == "RETEST_ORDERED"
            ):
                case["case_state"] = "RETEST_PASSED"
                case["active_retest_order_id"] = None
                engine.bump("noncompliance_cases", case)
        plan = db.get("sampling_plans", order["sampling_plan_id"])
        if plan is not None:
            plan["last_verified_at"] = clock.now()
            if plan["plan_state"] == "RESAMPLE_DUE":
                plan["plan_state"] = "ACTIVE"
                plan["resample_trigger"] = "NONE"
            engine.stamp_periodic_due(plan, product)
            calc.recompute_plan_ledger(plan)
            engine.bump("sampling_plans", plan)
        engine.recompute_product_derived(product)
        if (
            product["certification_state"] == "FULL_TEST_PROGRAM"
            and product["risk_weighted_gap_score"] == 0
        ):
            product["certification_state"] = "EVIDENCE_COMPLETE"
            product["compliance_posture"] = "CLEARED"
        engine.bump("products", product)
    else:
        engine.cascade_failed_test(order, product, auth.current_user_id())

    return response.object_response(db.serialize("test_orders", order))


@bp.post("/test-orders/<order_id>/cancel")
def cancel_order(order_id):
    auth.require_roles("TestCoordinator")
    order = refs.order(order_id)
    product = refs.product(order["product_id"])
    guard_not_archived(product)
    if order["order_state"] not in ("SCHEDULED", "IN_TESTING"):
        raise ApiError("ERR_ORDER_STATE_INVALID")

    order["order_state"] = "CANCELLED"
    engine.bump("test_orders", order)
    engine.release_order_commitments(order)
    return response.object_response(db.serialize("test_orders", order))
