"""Enrollment state axes, manual adjustments, and OCC (PRD §2.7, §2.8, §3.3)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_enrollment,
    add_settled_points,
    assert_points_ledger_entry,
    create_adjustment_payload,
    create_enrollment,
    create_screening,
    post_adjustment,
    result_screening,
    setup_active_enrollment,
    setup_verified_enrollment,
    submit_hra,
    validate_error,
    validate_paginated,
    validate_success,
)

BA = TEST_USERS["benefits_admin_headers"]


class TestParallelStateDimensions:
    """Difficulty instance: verification axis evolves independently of participation."""

    def test_suspend_preserves_flagged_verification(self, api):
        """PRD §3.4: "a result meeting at most one target flags the enrollment, moving
        `verification_status` from `VERIFIED` to `FLAGGED`..."
        PRD §3.3: "Because the axes are independent, a `SUSPENDED` member can still
        become `VERIFIED`."

        Design: Difficulty/non_linear_state_machine/enrollment_parallel_state_dimensions
        """
        ctx = setup_verified_enrollment(answers=[2] * 10)
        enr = ctx["enrollment"]
        assert enr["verification_status"] == "VERIFIED"

        screening = create_screening(enr["id"], ctx["employee"]["id"])
        resulted = result_screening(
            screening["id"], bmi=35.0, systolic_bp=150, total_cholesterol=240, glucose=95
        )
        assert resulted["targets_met"] == 1, "only glucose < 100 is met"
        flagged = validate_success(api.get_enrollment(enr["id"], BA), 200)
        assert flagged["verification_status"] == "FLAGGED"

        suspended = validate_success(api.suspend_enrollment(enr["id"], BA), 200)
        assert suspended["participation_status"] == "SUSPENDED"
        assert suspended["verification_status"] == "FLAGGED", (
            "suspension must not touch the verification axis"
        )

    def test_reinstate_preserves_flagged_verification(self, api):
        """PRD §3.3: "A `BenefitsAdmin` may suspend an `ACTIVE` enrollment
        (`ACTIVE → SUSPENDED`) with no further precondition, and may reinstate a
        `SUSPENDED` enrollment back to `ACTIVE`, but reinstatement again requires
        the program to be `ACTIVE` (otherwise `ERR_PROGRAM_NOT_ACTIVE`)."
        PRD §3.3: "Because the axes are independent, a `SUSPENDED` member can still
        become `VERIFIED`."

        Design: Difficulty/non_linear_state_machine/enrollment_parallel_state_dimensions
        """
        ctx = setup_verified_enrollment(answers=[2] * 10)
        enr = ctx["enrollment"]
        screening = create_screening(enr["id"], ctx["employee"]["id"])
        result_screening(
            screening["id"], bmi=35.0, systolic_bp=150, total_cholesterol=240, glucose=95
        )
        validate_success(api.suspend_enrollment(enr["id"], BA), 200)

        reinstated = validate_success(api.reinstate_enrollment(enr["id"], BA), 200)
        assert reinstated["participation_status"] == "ACTIVE"
        assert reinstated["verification_status"] == "FLAGGED", (
            "reinstatement must not touch the verification axis"
        )


class TestTerminalStateLockdown:
    def test_terminated_enrollment_reinstate_rejected(self, api):
        """PRD §3.3: "The first axis, `participation_status`, begins at `INVITED` and
        is terminal at `TERMINATED`."
        PRD §2.6: "The target resource is in a valid from-state for the requested
        transition; otherwise the state-family error applies — `ERR_INVALID_STATE`
        generically..."

        Design: Corner/state_machines/terminated_enrollment_reinstate_rejected
        """
        ctx = setup_active_enrollment()
        enr_id = ctx["enrollment"]["id"]
        validate_success(api.terminate_enrollment(enr_id, BA), 200)

        res = api.reinstate_enrollment(enr_id, BA)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        after = validate_success(api.get_enrollment(enr_id, BA), 200)
        assert after["participation_status"] == "TERMINATED"


class TestManualAdjustmentCompensation:
    """Difficulty instance: balances are a pure function of the ledger; a
    +500/-500 ADJUSTED pair restores the pre-pair value."""

    def test_compensating_adjustments_restore_zero_balances(self, api):
        """PRD §2.8: "From this ledger two balances are recomputed on every entry
        creation or status transition affecting the enrollment. The
        `points_balance_settled` sums the `points_delta` of entries in `POSTED`
        status only... The `points_balance_provisional` sums entries in either
        `PROVISIONAL` or `POSTED` status..."
        PRD §3.3: "a successful adjustment creates an `ADJUSTED` ledger entry born
        directly in `POSTED` status, recomputes both balances, and increments the
        enrollment's `version`."

        Design: Difficulty/compensating_invariant/points_adjustment_compensation_invariant
        """
        ctx = setup_active_enrollment()
        enr_id = ctx["enrollment"]["id"]

        v1 = validate_success(api.get_enrollment(enr_id, BA), 200)["version"]
        entry_1 = validate_success(
            api.create_enrollment_adjustment(
                enr_id, create_adjustment_payload(500, "goodwill credit", v1), BA
            ),
            201,
        )
        assert_points_ledger_entry(entry_1)
        v2 = validate_success(api.get_enrollment(enr_id, BA), 200)["version"]
        validate_success(
            api.create_enrollment_adjustment(
                enr_id, create_adjustment_payload(-500, "reversal of goodwill credit", v2), BA
            ),
            201,
        )

        final = validate_success(api.get_enrollment(enr_id, BA), 200)
        assert final["points_balance_provisional"] == 0, (
            "+500 then -500 must restore the pre-pair provisional balance of 0"
        )
        assert final["points_balance_settled"] == 0, (
            "+500 then -500 must restore the pre-pair settled balance of 0"
        )

    def test_compensating_adjustments_record_two_posted_entries(self, api):
        """PRD §2.8: "`EARNED` and `BONUS` entries are always positive and begin life
        `PROVISIONAL`; `ADJUSTED` entries are signed and are created directly in
        `POSTED` status."
        PRD §2.8: "a signed `points_delta`, a free-text `reason` (required when the
        kind is `ADJUSTED`)..."

        Design: Difficulty/compensating_invariant/points_adjustment_compensation_invariant
        """
        ctx = setup_active_enrollment()
        enr_id = ctx["enrollment"]["id"]

        v1 = validate_success(api.get_enrollment(enr_id, BA), 200)["version"]
        post_adjustment(enr_id, 500, "goodwill credit", v1)
        v2 = validate_success(api.get_enrollment(enr_id, BA), 200)["version"]
        post_adjustment(enr_id, -500, "reversal of goodwill credit", v2)

        entries, meta = validate_paginated(
            api.list_enrollment_points_ledger_entries(enr_id, BA)
        )
        assert meta["total_count"] == 2, "exactly two ADJUSTED entries must exist"
        by_delta = {e["points_delta"]: e for e in entries}
        assert set(by_delta) == {500, -500}
        for entry in entries:
            assert entry["kind"] == "ADJUSTED"
            assert entry["status"] == "POSTED", (
                "ADJUSTED entries are created directly in POSTED status"
            )
            assert isinstance(entry["reason"], str) and entry["reason"]


class TestEnrollmentAdjustmentOcc:
    def test_occ_stale_enrollment_adjustment_rejected(self, api):
        """PRD §2.7: "Posting a manual points adjustment against an Enrollment
        requires `expected_enrollment_version` matching that enrollment's current
        `version`. If another writer has advanced the enrollment's version since the
        client last read it — by posting an adjustment of their own, or via any
        cascade that recomputed the enrollment's balances — the adjustment is
        rejected with `ERR_STALE_VERSION`."

        Design: Corner/cross_cutting_layers/occ_stale_enrollment_adjustment_rejected
        """
        ctx = setup_active_enrollment()
        enr_id = ctx["enrollment"]["id"]
        stale_version = ctx["enrollment"]["version"]

        first = api.create_enrollment_adjustment(
            enr_id, create_adjustment_payload(100, "first", stale_version), BA
        )
        validate_success(first, 201)

        second = api.create_enrollment_adjustment(
            enr_id, create_adjustment_payload(50, "second with stale version", stale_version), BA
        )
        validate_error(second, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        final = validate_success(api.get_enrollment(enr_id, BA), 200)
        assert final["points_balance_settled"] == 100, (
            "only the first adjustment may apply; the stale write must be dropped"
        )
