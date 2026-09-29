"""The cutting-test bench: yield lines, metrics, revision cycle and approval.

PRD §3.2, §3.3.
"""

from flask import Blueprint

import errors
import middleware as mw
import validation as v
from calc import REVISION_LIMIT, UNACCOUNTED_TOLERANCE_LB, rhu
from db import db, make, mark, sort_rows
from errors import ApiError
from response import list_response, object_response
from services import cutting

bp = Blueprint("cutting_tests", __name__)

DISPOSITIONS = ("SALABLE_CUT", "GRIND_TRIM", "FAT_BONE_LOSS")

TEST_ACTION_ROLES = {
    "SUBMIT": (mw.MEAT_CUTTER,),
    "REVISE": (mw.MEAT_CUTTER,),
    "APPROVE": (mw.MEAT_MANAGER,),
    "REJECT": (mw.MEAT_MANAGER,),
}

DECLARED_TRANSITIONS = {
    "SUBMIT": ("DRAFT",),
    "APPROVE": ("SUBMITTED",),
    "REJECT": ("SUBMITTED",),
    "REVISE": ("REJECTED",),
}


@bp.route("/meat-ops/cutting-tests", methods=["POST"])
def create_cutting_test():
    mw.authenticate((mw.MEAT_CUTTER,))
    payload = v.body()

    purchase_id = v.field_id(payload, "primal_purchase_id", required=True)
    test_weight_lb = v.field_num(payload, "test_weight_lb", required=True, gt=0,
                                 places=2)
    expected_version = v.field_int(payload, "expected_primal_purchase_version",
                                   required=True)

    purchase = v.resolve("primal_purchase", purchase_id)

    if expected_version != purchase["version"]:
        raise ApiError(errors.ERR_STALE_PARENT_VERSION, 412,
                       "expected_primal_purchase_version does not match the purchase")

    if purchase["status"] == "RECONCILED":
        raise ApiError(errors.ERR_INVALID_STATE_TRANSITION, 409,
                       "A RECONCILED purchase is read-only")

    if test_weight_lb != purchase["net_weight_lb"]:
        raise ApiError(errors.ERR_YIELD_NOT_RECONCILED, 422,
                       "test_weight_lb must equal the purchase's net_weight_lb")

    if cutting.supersede_existing_tests(purchase):
        mark(purchase)

    test = make("CuttingTest", {
        "primal_purchase_id": purchase_id,
        "test_weight_lb": test_weight_lb,
        "total_yield_weight_lb": rhu(0, 2),
        "unaccounted_lb": rhu(0, 2),
        "salable_yield_pct": rhu(0, 4),
        "trim_yield_pct": rhu(0, 4),
        "loss_pct": rhu(0, 4),
        "submitted_by_user_id": None,
        "approved_by_user_id": None,
        "rejection_reason": None,
        "revision_count": 0,
        "status": "DRAFT",
    })
    db.cutting_tests[test["id"]] = test
    return object_response(test, 201)


@bp.route("/meat-ops/cutting-tests/<test_id>", methods=["GET"])
def get_cutting_test(test_id):
    mw.authenticate(mw.NO_SERVICE_CLERK)
    return object_response(v.resolve("cutting_test", test_id))


@bp.route("/meat-ops/primal-purchases/<purchase_id>/cutting-tests", methods=["GET"])
def list_purchase_tests(purchase_id):
    mw.authenticate(mw.NO_SERVICE_CLERK)
    v.resolve("primal_purchase", purchase_id)
    limit, offset = v.pagination()
    status = v.query_filter("status")
    rows = [row for row in db.cutting_tests.values()
            if row["primal_purchase_id"] == purchase_id
            and (status is None or row["status"] == status)]
    return list_response(sort_rows(rows), limit, offset)


# --------------------------------------------------------------------------
# yield lines
# --------------------------------------------------------------------------

@bp.route("/meat-ops/cutting-tests/<test_id>/lines", methods=["POST"])
def create_line(test_id):
    mw.authenticate((mw.MEAT_CUTTER,))
    test = v.resolve("cutting_test", test_id)
    payload = v.body()

    line_seq = v.field_int(payload, "line_seq", required=True, minimum=1, maximum=40)
    subprimal_code = v.field_str(payload, "subprimal_code", required=True,
                                 min_len=1, max_len=60)
    disposition = v.field_enum(payload, "disposition", DISPOSITIONS, required=True)
    yield_weight_lb = v.field_num(payload, "yield_weight_lb", required=True,
                                  minimum=0, places=2)
    market_value = v.field_int(payload, "market_value_per_lb_cents", required=True,
                               minimum=0)
    if disposition == "FAT_BONE_LOSS":
        if market_value != 0:
            v.bad("'market_value_per_lb_cents' must be 0 on a FAT_BONE_LOSS line")
    elif market_value <= 0:
        v.bad("'market_value_per_lb_cents' must be greater than 0")

    if disposition == "GRIND_TRIM":
        lean_pct = v.field_num(payload, "lean_pct", required=True,
                               minimum=50, maximum=99, places=1)
    else:
        v.field_num(payload, "lean_pct", forbidden=True,
                    forbidden_msg="'lean_pct' is only permitted on a GRIND_TRIM line")
        lean_pct = None

    if disposition == "SALABLE_CUT":
        retail_item_id = v.field_id(payload, "retail_item_id", required=True)
    else:
        if "retail_item_id" in payload and payload["retail_item_id"] is not None:
            v.bad("'retail_item_id' is only permitted on a SALABLE_CUT line")
        retail_item_id = None

    if retail_item_id is not None:
        v.resolve("retail_item", retail_item_id)

    if test["status"] != "DRAFT":
        raise ApiError(errors.ERR_INVALID_STATE_TRANSITION, 409,
                       "Lines may only be added while the test is DRAFT")

    for existing in cutting.lines_of_test(test["id"]):
        if existing["line_seq"] == line_seq:
            raise ApiError(errors.ERR_DUPLICATE_RESOURCE, 409,
                           "line_seq is already used on this test")

    line = make("CuttingTestLine", {
        "cutting_test_id": test["id"],
        "line_seq": line_seq,
        "subprimal_code": subprimal_code,
        "disposition": disposition,
        "yield_weight_lb": yield_weight_lb,
        "market_value_per_lb_cents": market_value,
        "lean_pct": lean_pct,
        "retail_item_id": retail_item_id,
        "allocated_cost_cents": 0,
        "allocated_cost_per_lb_cents": rhu(0, 4),
    })
    db.cutting_test_lines[line["id"]] = line

    cutting.recompute_metrics(test)
    return object_response(line, 201)


@bp.route("/meat-ops/cutting-test-lines/<line_id>", methods=["GET"])
def get_line(line_id):
    mw.authenticate(mw.NO_SERVICE_CLERK)
    return object_response(v.resolve("cutting_test_line", line_id))


@bp.route("/meat-ops/cutting-test-lines", methods=["GET"])
def list_lines():
    mw.authenticate(mw.NO_SERVICE_CLERK)
    limit, offset = v.pagination()
    cutting_test_id = v.query_filter("cutting_test_id")
    retail_item_id = v.query_filter("retail_item_id")
    disposition = v.query_filter("disposition")
    rows = []
    for row in db.cutting_test_lines.values():
        if cutting_test_id is not None and row["cutting_test_id"] != cutting_test_id:
            continue
        if retail_item_id is not None and row.get("retail_item_id") != retail_item_id:
            continue
        if disposition is not None and row["disposition"] != disposition:
            continue
        rows.append(row)
    return list_response(sort_rows(rows), limit, offset)


# --------------------------------------------------------------------------
# transitions
# --------------------------------------------------------------------------

@bp.route("/meat-ops/cutting-tests/<test_id>/transitions", methods=["POST"])
def test_transition(test_id):
    user_id, role = mw.authenticate((mw.MEAT_CUTTER, mw.MEAT_MANAGER))
    test = v.resolve("cutting_test", test_id)
    payload = v.body()

    action = v.field_enum(payload, "action", tuple(TEST_ACTION_ROLES), required=True)
    rejection_reason = v.field_str(payload, "rejection_reason",
                                   required=(action == "REJECT"),
                                   min_len=1, max_len=280)

    mw.check_action_role(role, action, TEST_ACTION_ROLES)

    if test["status"] not in DECLARED_TRANSITIONS[action]:
        raise ApiError(errors.ERR_INVALID_STATE_TRANSITION, 409,
                       "%s is not a declared transition out of %s"
                       % (action, test["status"]))

    purchase = db.primal_purchases.get(test["primal_purchase_id"])

    if action == "SUBMIT":
        cutting.recompute_metrics(test)
        if (purchase is not None
                and test["test_weight_lb"] != purchase["net_weight_lb"]):
            raise ApiError(errors.ERR_YIELD_NOT_RECONCILED, 422,
                           "test_weight_lb no longer equals the purchase net weight")
        if abs(test["unaccounted_lb"]) > UNACCOUNTED_TOLERANCE_LB:
            raise ApiError(errors.ERR_YIELD_NOT_RECONCILED, 422,
                           "unaccounted_lb is outside the reconciliation tolerance")
        lines = cutting.lines_of_test(test["id"])
        if not any(line["disposition"] == "SALABLE_CUT" for line in lines):
            raise ApiError(errors.ERR_NO_SALABLE_YIELD, 422,
                           "The test carries no SALABLE_CUT line")
        if (cutting.has_zero_valued_candidate(test)
                or cutting.market_value_base(test) == 0):
            raise ApiError(errors.ERR_NO_MARKET_VALUE_BASIS, 422,
                           "The value-bearing lines carry no market-value base")
        test["submitted_by_user_id"] = user_id
        test["status"] = "SUBMITTED"
        mark(test)

    elif action == "APPROVE":
        if purchase is None or purchase["status"] != "RECEIVED":
            raise ApiError(errors.ERR_INVALID_STATE_TRANSITION, 409,
                           "The parent purchase is no longer RECEIVED")
        if test["submitted_by_user_id"] == user_id:
            raise ApiError(errors.ERR_SEGREGATION_OF_DUTIES, 403,
                           "The approver must differ from the submitter")
        if cutting.market_value_base(test) == 0:
            raise ApiError(errors.ERR_NO_MARKET_VALUE_BASIS, 422,
                           "The value-bearing lines carry no market-value base")
        test["approved_by_user_id"] = user_id
        test["status"] = "APPROVED"
        mark(test)
        cutting.allocate(test, purchase)
        cutting.approval_cascade(test, purchase)

    elif action == "REJECT":
        if test["submitted_by_user_id"] == user_id:
            raise ApiError(errors.ERR_SEGREGATION_OF_DUTIES, 403,
                           "The reviewer must differ from the submitter")
        test["rejection_reason"] = rejection_reason
        test["status"] = "REJECTED"
        mark(test)

    else:                                          # REVISE
        if test["revision_count"] >= REVISION_LIMIT:
            raise ApiError(errors.ERR_REVISION_LIMIT_REACHED, 422,
                           "The revision budget is exhausted")
        test["revision_count"] = test["revision_count"] + 1
        test["rejection_reason"] = None
        test["submitted_by_user_id"] = None
        test["status"] = "DRAFT"
        mark(test)

    return object_response(test)
