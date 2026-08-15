"""Leaf-lot lifecycle: sensory grading thresholds, residue verdict
boundaries, the ON_HOLD retest loop, and release gates.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_graded_lot,
    create_lab_submitted_lot,
    create_leaf_lot,
    create_supplier,
    get_lot,
    grade_lot,
    release_lot,
    submit_residue_test,
    validate_error,
    validate_paginated,
    validate_success,
)

PL = TEST_USERS["procurement_lead_headers"]
QA = TEST_USERS["qa_manager_headers"]


class TestSensoryGrading:
    def test_grade_boundary_85_is_A(self, api):
        """PRD §3.2: "The composite score weighs aroma at 0.40, briskness at
        0.35, and appearance at 0.25, sums the three weighted terms, and
        rounds half-up to one decimal place"
        PRD §3.2: "Grade thresholds are inclusive: a composite of at least
        85.0 earns `A`, at least 70.0 earns `B`, at least 55.0 earns `C`,
        and anything below 55.0 is a `REJECT`."

        Equal scores of 85 reproduce 85.0 because the weights sum to 1.0;
        85.0 >= 85.0 earns A.

        Design: Corner/calculations/grade_boundary_85_is_A
        """
        supplier = create_supplier(name="Grade Co")
        lot = create_leaf_lot(supplier["id"], leaf_type="WHITE",
                              cost_per_kg_cents=1500)
        res = api.create_grade_assessment(
            lot["id"],
            {"aroma_score": 85, "briskness_score": 85, "appearance_score": 85},
            TEST_USERS["sensory_grader_headers"])
        data = validate_success(res, 201)
        assert data["composite_score"] == 85.0
        assert data["composite_grade"] == "A"
        assert data["lot_id"] == lot["id"]
        assert data["grader_user_id"] == "gr-1"

    def test_terminal_lot_rejects_grading(self, api):
        """PRD §3.2: "`REJECTED` and `DEPLETED` are terminal for
        client-driven actions — acting on either is rejected with
        `ERR_ALREADY_TERMINAL`"

        Design: Corner/state_machines/terminal_lot_rejects_grading
        """
        supplier = create_supplier(name="Term Co")
        lot = create_leaf_lot(supplier["id"])
        # 50/50/50 -> composite 50.0 -> REJECT -> lot REJECTED
        grade_lot(lot["id"], 50, 50, 50)
        assert get_lot(lot["id"])["status"] == "REJECTED"

        res = api.create_grade_assessment(
            lot["id"],
            {"aroma_score": 90, "briskness_score": 90, "appearance_score": 90},
            TEST_USERS["sensory_grader_headers"])
        validate_error(res, ApiErrorId.ERR_ALREADY_TERMINAL)
        _, meta = validate_paginated(api.list_grade_assessments(lot["id"], QA))
        assert meta["total_count"] == 1, "rejected grading persists nothing"


class TestResidueBoundary:
    def test_residue_at_limit_passes(self, api):
        """PRD §3.2: "The verdict compares the single measurement against
        the 0.50 ppm residue limit: at most 0.50 ppm, inclusive, is a
        `PASS`; strictly more than 1.00 ppm — twice the limit — is a
        `FAIL_HARD`; anything in between is a `FAIL_SOFT`."
        PRD §3.2: "The boundaries behave exactly as written: a reading of
        0.50 passes, 1.00 is a soft fail, and 1.01 is a hard fail."
        PRD §3.2: "From `GRADED`, a `PASS` advances the lot to
        `LAB_SUBMITTED`"

        Design: Difficulty/boundary_precision_check/residue_limit_inclusive_boundary
        """
        supplier = create_supplier(name="Boundary Co")
        lot = create_graded_lot(supplier["id"], moisture_pct=5.5)
        test = submit_residue_test(lot["id"], measured_residue_ppm=0.50)
        assert test["verdict"] == "PASS"
        assert test["test_round"] == 1
        after = get_lot(lot["id"])
        assert after["status"] == "LAB_SUBMITTED"
        assert after["latest_residue_verdict"] == "PASS"

    def test_residue_one_cent_above_limit_soft_fails(self, api):
        """PRD §3.2: "at most 0.50 ppm, inclusive, is a `PASS`"
        PRD §3.2: "a `FAIL_SOFT` moves it to `ON_HOLD`"

        0.51 ppm sits strictly between the inclusive 0.50 pass bound and
        the exclusive 1.00 hard-fail bound, so it is FAIL_SOFT and the lot
        goes ON_HOLD.

        Design: Difficulty/boundary_precision_check/residue_limit_inclusive_boundary
        """
        supplier = create_supplier(name="Boundary Co 2")
        lot = create_graded_lot(supplier["id"], moisture_pct=5.5)
        test = submit_residue_test(lot["id"], measured_residue_ppm=0.51)
        assert test["verdict"] == "FAIL_SOFT"
        after = get_lot(lot["id"])
        assert after["status"] == "ON_HOLD"
        assert after["latest_residue_verdict"] == "FAIL_SOFT"

    def test_residue_soft_boundary_1_00(self, api):
        """PRD §3.2: "strictly more than 1.00 ppm — twice the limit — is a
        `FAIL_HARD`"
        PRD §3.2: "The boundaries behave exactly as written: a reading of
        0.50 passes, 1.00 is a soft fail, and 1.01 is a hard fail."

        1.00 is NOT strictly more than 1.00, so it is FAIL_SOFT (ON_HOLD).

        Design: Corner/calculations/residue_soft_boundary_1_00
        """
        supplier = create_supplier(name="Soft Co")
        lot = create_graded_lot(supplier["id"])
        test = submit_residue_test(lot["id"], measured_residue_ppm=1.00)
        assert test["verdict"] == "FAIL_SOFT"
        assert get_lot(lot["id"])["status"] == "ON_HOLD"

    def test_hard_fail_residue_auto_rejects_lot(self, api):
        """PRD §3.2: "a `FAIL_HARD` rejects the lot outright into
        `REJECTED`"
        PRD §3.2: "the system stamps `submitted_by_user_id` and assigns
        `test_round` as the 1-based chronological count of residue tests
        filed against that lot"

        Design: Corner/state_machines/hard_fail_residue_auto_rejects_lot
        """
        supplier = create_supplier(name="Hard Co")
        lot = create_graded_lot(supplier["id"])
        test = submit_residue_test(lot["id"], measured_residue_ppm=1.01)
        assert test["verdict"] == "FAIL_HARD"
        assert test["test_round"] == 1
        after = get_lot(lot["id"])
        assert after["status"] == "REJECTED"
        assert after["latest_residue_verdict"] == "FAIL_HARD"


class TestRetestCycle:
    def test_retest_cycle_pass_then_release(self, api):
        """PRD §3.2: "From `ON_HOLD` the loop repeats: a passing retest
        moves the lot to `LAB_SUBMITTED` with the incremented `test_round`
        recorded, a soft-failing retest leaves the lot `ON_HOLD`, and a
        hard-failing retest ends it in `REJECTED`."

        Design: Difficulty/non_linear_state_machine/leaf_lot_retest_cycle
        """
        supplier = create_supplier(name="Galle Co")
        lot = create_graded_lot(supplier["id"], moisture_pct=5.5)

        first = submit_residue_test(lot["id"], measured_residue_ppm=0.75)
        assert first["verdict"] == "FAIL_SOFT"
        assert first["test_round"] == 1
        assert get_lot(lot["id"])["status"] == "ON_HOLD"

        retest = submit_residue_test(lot["id"], measured_residue_ppm=0.30,
                                     lab_name="LabB", test_method="HPLC")
        assert retest["verdict"] == "PASS"
        assert retest["test_round"] == 2, "retest increments test_round"
        assert get_lot(lot["id"])["status"] == "LAB_SUBMITTED"

        released = release_lot(lot["id"])
        assert released["status"] == "RELEASED"

    def test_soft_failing_retest_leaves_lot_on_hold(self, api):
        """PRD §3.2: "a soft-failing retest leaves the lot `ON_HOLD`"
        PRD §3.2: "Whatever the outcome, the lot's `latest_residue_verdict`
        always reflects the newest test's `verdict`."

        Design: Difficulty/non_linear_state_machine/leaf_lot_retest_cycle
        """
        supplier = create_supplier(name="Galle Co 2")
        lot = create_graded_lot(supplier["id"], moisture_pct=5.5)

        submit_residue_test(lot["id"], measured_residue_ppm=0.75)
        assert get_lot(lot["id"])["status"] == "ON_HOLD"

        retest = submit_residue_test(lot["id"], measured_residue_ppm=0.80,
                                     lab_name="LabB", test_method="HPLC")
        assert retest["verdict"] == "FAIL_SOFT"
        assert retest["test_round"] == 2
        after = get_lot(lot["id"])
        assert after["status"] == "ON_HOLD"
        assert after["latest_residue_verdict"] == "FAIL_SOFT"


class TestLotReleaseGates:
    def test_release_from_graded_rejected(self, api):
        """PRD §3.2: "The lot must be `LAB_SUBMITTED` with a latest verdict
        of `PASS` — anything else is rejected with
        `ERR_LOT_NOT_RELEASABLE`."

        Design: Corner/state_machines/release_from_graded_rejected
        """
        supplier = create_supplier(name="Inv Co")
        lot = create_graded_lot(supplier["id"])
        res = api.release_lot(lot["id"], QA)
        validate_error(res, ApiErrorId.ERR_LOT_NOT_RELEASABLE)
        assert get_lot(lot["id"])["status"] == "GRADED", (
            "rejected release must not move the lot")

    def test_supplier_suspended_blocks_lot_release(self, api):
        """PRD §3.2: "Its supplier must be `ACTIVE`; a suspended supplier
        blocks release with `ERR_SUPPLIER_SUSPENDED`."
        PRD §2.8: "a held lot leaves `ON_HOLD` only through a fresh residue
        test that passes"

        Setup: lot reaches LAB_SUBMITTED, supplier is suspended (cascade
        link 1 moves LAB_SUBMITTED -> ON_HOLD), a passing retest returns
        the lot to LAB_SUBMITTED while the supplier stays SUSPENDED.

        Design: Corner/validations/supplier_suspended_blocks_lot_release
        """
        supplier = create_supplier(name="Susp Co")
        lot = create_lab_submitted_lot(supplier["id"],
                                       measured_residue_ppm=0.30)
        validate_success(api.suspend_supplier(supplier["id"], PL), 200)
        assert get_lot(lot["id"])["status"] == "ON_HOLD"

        retest = submit_residue_test(lot["id"], measured_residue_ppm=0.20,
                                     lab_name="LabB", test_method="HPLC")
        assert retest["verdict"] == "PASS"
        assert get_lot(lot["id"])["status"] == "LAB_SUBMITTED"

        res = api.release_lot(lot["id"], QA)
        validate_error(res, ApiErrorId.ERR_SUPPLIER_SUSPENDED)
        assert get_lot(lot["id"])["status"] == "LAB_SUBMITTED"
