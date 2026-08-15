"""InspectionTest + DispositionCase endpoints (quality evidence and disposition)."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, g

import validation as v
from db import store, new_id, new_common, new_evidence, touch
from errors import ApiError
from middleware import ANY_ROLES, get_context, require_roles
from response import Paginator, created, ok
from services import domain

bp = Blueprint("inspections", __name__)


@bp.post("/inspection-tests")
def create_inspection_test():
    uid, _ = get_context()
    require_roles(["QualityEngineer"])
    body = v.get_body()
    # tier 4: body FK existence
    order = None
    if v.present(body, "work_order_id"):
        order = v.resolve_fk(store.work_orders, body.get("work_order_id"), "ERR_WORK_ORDER_NOT_FOUND")
    # tier 5: inspection requires PROCESSED + PENDING_TEST
    if order is not None and (order["processing_status"] != "PROCESSED"
                              or order["quality_status"] != "PENDING_TEST"):
        raise ApiError("ERR_WORK_ORDER_NOT_TESTABLE", 409,
                       "Inspection requires processing_status PROCESSED and quality_status PENDING_TEST")
    # tier 9: required fields; hardness_readings must be a non-empty array of numbers
    if order is None:
        v.req_string(body, "work_order_id")  # raises ERR_INVALID_REQUEST
    readings = v.req_list(body, "hardness_readings")
    if not readings or any(not v.is_number(r) for r in readings):
        raise ApiError("ERR_INVALID_REQUEST", 400, "hardness_readings must be a non-empty array of numbers")
    distortion = v.req_number(body, "measured_distortion_in")

    recipe = store.recipes.get(order["recipe_id"])
    total = sum(Decimal(str(r)) for r in readings)
    avg = total / Decimal(len(readings))
    avg = avg.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    passed = (Decimal(recipe["hardness_min_hrc"]) <= avg <= Decimal(recipe["hardness_max_hrc"])
              and Decimal(str(distortion)) <= Decimal(str(recipe["fixture_distortion_allowance_in"])))
    test = {
        "id": new_id(),
        "work_order_id": order["id"],
        "recorded_by_user_id": uid,
        "hardness_readings": list(readings),
        "measured_distortion_in": distortion,
        "avg_hardness_hrc": avg,
        "result": "PASS" if passed else "FAIL",
    }
    new_evidence(test)
    store.inspection_tests[test["id"]] = test
    # Cascade into the order's independent quality dimension.
    if passed:
        order["quality_status"] = "PASSED"
        touch(order)
    else:
        order["quality_status"] = "FAILED"
        touch(order)
        case = {
            "id": new_id(),
            "work_order_id": order["id"],
            "inspection_test_id": test["id"],
            "status": "OPEN",
            "decision": None,
            "decided_by_user_id": None,
        }
        new_common(case)
        store.disposition_cases[case["id"]] = case
    return created(test)


@bp.get("/inspection-tests")
def list_inspection_tests():
    get_context()
    require_roles(ANY_ROLES)
    pg = Paginator()
    rows = list(store.inspection_tests.values())
    rows = pg.filter(rows, "work_order_id")
    rows = pg.filter(rows, "result")
    return ok(pg(rows), rtype="array", pagination=pg)


@bp.get("/inspection-tests/<test_id>")
def get_inspection_test(test_id):
    get_context()
    require_roles(ANY_ROLES)
    return ok(v.resolve_path(store.inspection_tests, test_id, "ERR_INSPECTION_TEST_NOT_FOUND"))


@bp.get("/disposition-cases")
def list_disposition_cases():
    get_context()
    require_roles(ANY_ROLES)
    pg = Paginator()
    rows = list(store.disposition_cases.values())
    rows = pg.filter(rows, "work_order_id")
    rows = pg.filter(rows, "inspection_test_id")
    rows = pg.filter(rows, "status")
    return ok(pg(rows), rtype="array", pagination=pg)


@bp.get("/disposition-cases/<case_id>")
def get_disposition_case(case_id):
    get_context()
    require_roles(ANY_ROLES)
    return ok(v.resolve_path(store.disposition_cases, case_id, "ERR_DISPOSITION_CASE_NOT_FOUND"))


@bp.post("/disposition-cases/<case_id>/decide")
def decide_disposition_case(case_id):
    uid, _ = get_context()
    require_roles(["QualityEngineer"])
    body = v.get_body()
    case = v.resolve_path(store.disposition_cases, case_id, "ERR_DISPOSITION_CASE_NOT_FOUND")
    # tier 5: case must be OPEN
    if case["status"] != "OPEN":
        raise ApiError("ERR_DISPOSITION_NOT_OPEN", 409, "Disposition case is not OPEN")
    # tier 6 (safety): segregation of duties — decider must differ from the test recorder
    test = store.inspection_tests.get(case["inspection_test_id"])
    if test is not None and uid == test["recorded_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "The decider must differ from the inspection recorder")
    # tier 9: decision enum + re-treat ceiling
    decision = v.req_enum(body, "decision", domain.DECISIONS)
    order = store.work_orders.get(case["work_order_id"])
    recipe = store.recipes.get(order["recipe_id"]) if order else None
    if decision == "RE_TREAT" and order is not None and recipe is not None:
        if order["retreat_count"] >= recipe["max_retreats"]:
            raise ApiError("ERR_RETREAT_LIMIT_REACHED", 422,
                           "RE_TREAT requires retreat_count < recipe.max_retreats")

    # Per-decision cascades (state_machines.DispositionCase.OPEN_to_DECIDED).
    if decision == "RE_TREAT":
        order["processing_status"] = "AWAITING_RETREAT"
        order["retreat_count"] += 1
        order["quality_status"] = "PENDING_TEST"
        touch(order)
    elif decision == "SCRAP":
        order["processing_status"] = "SCRAPPED"
        touch(order)
        customer = store.customers.get(order["customer_id"])
        claim = {
            "id": new_id(),
            "work_order_id": order["id"],
            "customer_id": order["customer_id"],
            "payout_cents": domain.liability_payout(order, customer),
            "status": "PENDING",
        }
        new_common(claim)
        store.liability_claims[claim["id"]] = claim
        if customer is not None:
            domain.recompute_exposure(customer)
    else:  # RETURN_AS_IS — waive the failure; lot stays PROCESSED and shippable
        order["quality_status"] = "WAIVED"
        touch(order)

    case["status"] = "DECIDED"
    case["decision"] = decision
    case["decided_by_user_id"] = uid
    touch(case)
    return ok(case)
