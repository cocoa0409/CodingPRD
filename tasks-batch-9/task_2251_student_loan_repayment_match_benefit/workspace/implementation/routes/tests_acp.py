"""ACP nondiscrimination testing and corrective forfeitures (PRD 3.9)."""

from flask import Blueprint, request

import db
from errors import fail
from middleware import auth, body, opt_bool, req_enum, req_str
from response import object_response, paginated
from services import calc, effects, lookup, serialize

bp = Blueprint("tests_acp", __name__)

TEST_METHODS = ("CURRENT_YEAR", "PRIOR_YEAR")
CORRECTION_METHODS = ("QNEC", "CORRECTIVE_FORFEITURE")


@bp.post("/nondiscrimination-tests")
def create_test():
    auth("ComplianceAuditor")
    payload = body()
    plan_year_id = req_str(payload, "plan_year_id")
    test_method = req_enum(payload, "test_method", TEST_METHODS)
    plan_year = lookup.plan_year(plan_year_id)

    row = {
        "plan_year_id": plan_year["id"],
        "test_method": test_method,
        "include_qslp_match": True,
        "status": "PENDING",
        "hce_acp": 0,
        "nhce_acp": 0,
        "limit_acp": 0,
        "hce_count": 0,
        "nhce_count": 0,
        "computed_at": None,
        "correction_method": None,
    }
    db.stamp_new(row)
    db.db.nondiscrimination_tests[row["id"]] = row
    return object_response(serialize.nondiscrimination_test(row), 201)


@bp.get("/nondiscrimination-tests")
def list_tests():
    auth("ComplianceAuditor", "BenefitsAdministrator")
    rows = db.rows("nondiscrimination_tests")
    for name in ("plan_year_id", "status"):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r[name] == value]
    return paginated(rows, serialize.nondiscrimination_test)


@bp.get("/nondiscrimination-tests/<test_id>")
def get_test(test_id):
    auth("ComplianceAuditor", "BenefitsAdministrator")
    return object_response(serialize.nondiscrimination_test(
        lookup.test(test_id)))


@bp.post("/nondiscrimination-tests/<test_id>/compute")
def compute_test(test_id):
    auth("ComplianceAuditor")
    payload = body()
    include_qslp_match = opt_bool(payload, "include_qslp_match", True)
    test = lookup.test(test_id)

    if test["status"] not in ("PENDING", "STALE"):
        fail("ERR_TEST_ALREADY_FINAL",
             "a test in %s may not be recomputed" % test["status"])

    plan_year = db.db.plan_years.get(test["plan_year_id"])
    if plan_year is None or plan_year["status"] not in ("OPEN", "LOCKED"):
        fail("ERR_PLAN_YEAR_LOCKED",
             "the plan year does not accept nondiscrimination testing")

    result = calc.acp_test(plan_year, test["test_method"], include_qslp_match)
    if result.get("error"):
        fail(result["error"],
             "the plan year has no non-highly-compensated participant")

    test["include_qslp_match"] = include_qslp_match
    test["hce_acp"] = result["hce_acp"]
    test["nhce_acp"] = result["nhce_acp"]
    test["limit_acp"] = result["limit_acp"]
    test["hce_count"] = result["hce_count"]
    test["nhce_count"] = result["nhce_count"]
    test["computed_at"] = db.now_iso()
    test["status"] = "PASSED" if result["passed"] else "FAILED"
    db.touch(test)
    return object_response(serialize.nondiscrimination_test(test))


@bp.post("/nondiscrimination-tests/<test_id>/correction")
def correct_test(test_id):
    user_id, _role = auth("ComplianceAuditor")
    payload = body()
    correction_method = req_enum(payload, "correction_method",
                                 CORRECTION_METHODS)
    test = lookup.test(test_id)

    if test["status"] != "FAILED":
        fail("ERR_TEST_ALREADY_FINAL",
             "only a FAILED test may be corrected (this one is %s)"
             % test["status"])

    plan_year = db.db.plan_years.get(test["plan_year_id"])
    limit_acp = calc.rhu4(test["limit_acp"])
    participants = calc.acp_participants(plan_year,
                                         test["include_qslp_match"])
    excesses = []
    for participant in participants:
        if not participant["hce"]:
            continue
        if participant["ratio"] <= limit_acp:
            continue
        excess = calc.rhu_cents(
            (participant["ratio"] - limit_acp)
            * calc.dec(participant["denominator"]))
        if excess != 0:
            excesses.append((participant["employee"], excess))

    for employee, excess in excesses:
        effects.create_adjustment(
            reason_code="ACP_CORRECTIVE_FORFEITURE",
            amount_cents=-excess,
            employee_id=employee["id"],
            plan_year_id=plan_year["id"],
            created_by_user_id=user_id,
            nondiscrimination_test_id=test["id"],
        )

    test["correction_method"] = correction_method
    test["status"] = "CORRECTED"
    db.touch(test)
    db.touch(plan_year)
    return object_response(serialize.nondiscrimination_test(test))
