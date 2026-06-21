"""Laboratory testing PASS/FAIL branch and package release with segregation
of duties."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_cultivation_license, create_testing_license,
    create_cured_harvest, create_package, record_lab_result, release_package,
    cult_h, qa_h, cm_h,
)


def test_lab_pass_clears_hold_and_stamps_potency(api):
    """PRD §3.5: "On a `PASS`, the package transitions from `TESTING` to
    `PASSED`, its `lab_hold` is cleared to false, its `thc_pct` is set from the
    lab result's measured value, and its `version` increments."

    Design: Difficulty/non_linear_state_machine/package_testing_branch_pass_vs_fail
    """
    cul = create_cultivation_license()
    lab = create_testing_license()
    harvest = create_cured_harvest(cul["id"], dry_weight_grams=800)
    pkg = create_package(harvest["id"], quantity_grams=100, package_tag="PKG-F1")

    resp = api.create_lab_result({
        "package_id": pkg["id"], "testing_license_id": lab["id"],
        "thc_pct": 22.5, "pesticide_pass": True, "tested_at": "2026-05-01T00:00:00Z",
    }, qa_h("qa-1"))
    lr = validate_success(resp, 201)
    assert lr["overall_result"] == "PASS"

    data = validate_success(api.get_package(pkg["id"], cult_h()))
    assert data["status"] == "PASSED"
    assert data["lab_hold"] is False
    assert data["thc_pct"] == 22.5


def test_lab_fail_keeps_hold_and_stamps_nothing(api):
    """PRD §3.5: "On a `FAIL`, the package transitions from `TESTING` to
    `FAILED`, its `lab_hold` remains true, nothing is cleared, and its `version`
    increments."

    Design: Difficulty/non_linear_state_machine/package_testing_branch_pass_vs_fail
    """
    cul = create_cultivation_license()
    lab = create_testing_license()
    harvest = create_cured_harvest(cul["id"], dry_weight_grams=800)
    pkg = create_package(harvest["id"], quantity_grams=100, package_tag="PKG-F2")

    resp = api.create_lab_result({
        "package_id": pkg["id"], "testing_license_id": lab["id"],
        "thc_pct": 22.5, "pesticide_pass": False, "tested_at": "2026-05-01T00:00:00Z",
    }, qa_h("qa-1"))
    lr = validate_success(resp, 201)
    assert lr["overall_result"] == "FAIL"

    data = validate_success(api.get_package(pkg["id"], cult_h()))
    assert data["status"] == "FAILED"
    assert data["lab_hold"] is True
    assert data["thc_pct"] is None


def test_release_by_same_user_as_lab_pass_rejected(api):
    """PRD §2.6: "A package that has earned a passing laboratory result may be
    released into active inventory only by an operator whose `X-User-ID` differs
    from the `QALabUser` who recorded that passing result; if the same user
    attempts both, the release is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/errors/segregation_release_same_user
    """
    cul = create_cultivation_license()
    lab = create_testing_license()
    harvest = create_cured_harvest(cul["id"], dry_weight_grams=500)
    pkg = create_package(harvest["id"], quantity_grams=50, package_tag="PKG-ERR2")
    record_lab_result(pkg["id"], lab["id"], pesticide_pass=True, qa_user_id="shared-1")

    # Same X-User-ID releases as ComplianceManager.
    resp = api.release_package(pkg["id"], cm_h("shared-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    data = validate_success(api.get_package(pkg["id"], cult_h()))
    assert data["status"] == "PASSED", "package must stay PASSED after rejected release"
