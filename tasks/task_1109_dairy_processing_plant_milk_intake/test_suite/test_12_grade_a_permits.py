"""Grade A permit inspection lifecycle: the UNDER_REVIEW fork (suspend /
reinstate), the suspension cascade onto scheduled runs, and the violation
thresholds on suspend and revoke."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    get_permit,
    get_run,
    get_success_data,
    make_batch,
    make_permit,
    make_run,
    set_clock,
    setup_running_run,
    setup_under_review_permit,
    validate_error,
    validate_success,
)

SI = TEST_USERS["state_inspector_headers"]
OP = TEST_USERS["pasteurizer_operator_headers"]


class TestPermitReviewLoop:
    def test_suspend_from_under_review_cancels_scheduled_runs(self, api):
        """PRD §3.9: "Suspending the permit requires `violation_count_12mo` to
        be at least 3, otherwise `ERR_INSUFFICIENT_VIOLATIONS`; on suspension
        the permit transitions to `SUSPENDED`, every `SCHEDULED`
        `PasteurizerRun` transitions to `CANCELLED`, and `ProducerSettlement`
        approvals are blocked until reinstatement."

        Design: Difficulty/non_linear_state_machine/grade_a_permit_review_loop
        """
        set_clock()
        permit = make_permit()
        run = make_run()  # stays SCHEDULED — never started
        assert run["status"] == "SCHEDULED"

        reviewed = get_success_data(
            api.record_inspection(
                permit["id"], {"inspection_score": 75, "violations_found": 3}, SI
            )
        )
        assert reviewed["status"] == "UNDER_REVIEW"
        assert reviewed["violation_count_12mo"] == 3

        suspended = validate_success(api.suspend_permit(permit["id"], {}, SI), 200)
        assert suspended["status"] == "SUSPENDED"
        assert get_run(run["id"])["status"] == "CANCELLED"

    def test_reinstate_from_under_review(self, api):
        """PRD §3.9: "Reinstating the permit requires `violation_count_12mo` to
        be below 3 after corrective action, otherwise
        `ERR_VIOLATIONS_OUTSTANDING`; on reinstatement the permit transitions
        to `REINSTATED`."

        Design: Difficulty/non_linear_state_machine/grade_a_permit_review_loop
        """
        set_clock()
        permit = make_permit()
        reviewed = get_success_data(
            api.record_inspection(
                permit["id"], {"inspection_score": 85, "violations_found": 2}, SI
            )
        )
        assert reviewed["status"] == "UNDER_REVIEW"
        assert reviewed["violation_count_12mo"] == 2

        reinstated = validate_success(api.reinstate_permit(permit["id"], {}, SI), 200)
        assert reinstated["status"] == "REINSTATED"


class TestPermitSuspendCascade:
    def test_suspend_cascades_only_to_scheduled_runs(self, api):
        """PRD §3.9: "on suspension the permit transitions to `SUSPENDED`,
        every `SCHEDULED` `PasteurizerRun` transitions to `CANCELLED`" — the
        cascade is enumerated over `SCHEDULED` runs only.

        Design: Difficulty/transitive_cascade/permit_suspend_cancels_runs_scraps_batches
        """
        set_clock()
        permit = make_permit()
        scheduled_run = make_run(
            scheduled_start_at="2026-05-11T08:00:00Z",
            scheduled_end_at="2026-05-11T12:00:00Z",
        )
        running_run = setup_running_run(with_permit=False)

        get_success_data(
            api.record_inspection(
                permit["id"], {"inspection_score": 75, "violations_found": 3}, SI
            )
        )
        suspended = validate_success(api.suspend_permit(permit["id"], {}, SI), 200)
        assert suspended["status"] == "SUSPENDED"
        assert get_run(scheduled_run["id"])["status"] == "CANCELLED"
        # Only SCHEDULED runs are named by the cascade; the RUNNING run stays.
        assert get_run(running_run["id"])["status"] == "RUNNING"

    def test_suspend_with_batches_present_still_cancels_run(self, api):
        """PRD §3.9: "on suspension the permit transitions to `SUSPENDED`,
        every `SCHEDULED` `PasteurizerRun` transitions to `CANCELLED`, and
        `ProducerSettlement` approvals are blocked until reinstatement."

        Design: Difficulty/transitive_cascade/permit_suspend_cancels_runs_scraps_batches
        """
        set_clock()
        permit = make_permit()
        run = make_run()
        make_batch(run["id"], product_code="WHOLE_MILK", shelf_life_days=14)
        make_batch(run["id"], product_code="HEAVY_CREAM", shelf_life_days=25)

        get_success_data(
            api.record_inspection(
                permit["id"], {"inspection_score": 75, "violations_found": 3}, SI
            )
        )
        validate_success(api.suspend_permit(permit["id"], {}, SI), 200)
        assert get_permit(permit["id"])["status"] == "SUSPENDED"
        assert get_run(run["id"])["status"] == "CANCELLED"


def test_suspend_with_two_violations_rejected(api):
    """PRD §3.9: "Suspending the permit requires `violation_count_12mo` to be
    at least 3, otherwise `ERR_INSUFFICIENT_VIOLATIONS`".

    Design: Corner/errors/err_insufficient_violations_on_suspend
    """
    set_clock()
    permit = setup_under_review_permit(score=85, violations=2)
    assert permit["violation_count_12mo"] == 2

    res = api.suspend_permit(permit["id"], {}, SI)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_VIOLATIONS)


def test_revoke_with_three_violations_rejected(api):
    """PRD §3.9: "Revoking the permit requires `violation_count_12mo` to be at
    least 5, otherwise `ERR_VIOLATIONS_BELOW_REVOCATION`".

    Design: Corner/errors/err_violations_below_revocation
    """
    set_clock()
    permit = setup_under_review_permit(score=70, violations=3)
    assert permit["violation_count_12mo"] == 3

    res = api.revoke_permit(permit["id"], {}, SI)
    validate_error(res, ApiErrorId.ERR_VIOLATIONS_BELOW_REVOCATION)
