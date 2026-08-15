"""Downtime billing: grace, daily cap, block rounding, and accrual."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    complete_field_work,
    create_downtime_payload,
    create_job_in_progress,
    get_success_data,
    open_and_close_downtime,
    validate_error,
    verify_containment,
)

PM = TEST_USERS["project_manager_headers"]
FS = TEST_USERS["field_supervisor_headers"]
PA = TEST_USERS["platform_admin_headers"]


class TestDowntimeGraceCapBlockFormula:
    def test_first_event_grace_subtracted_and_blocked(self, api):
        """PRD §3.5: "`grace_minutes_applied` depends only on the cause: thirty
        minutes for `CUSTOMER_DELAY` ... For every other cause, the raw billable
        time is the duration minus the grace, floored at zero ... `billed_blocks`
        counts the billable minutes in fifteen-minute blocks, any partial block
        rounding up to a whole block, and `billed_amount_cents` is the number of
        blocks multiplied by one quarter of the pinned schedule's
        `standby_rate_cents_per_hour`".

        Design: Difficulty/combinatorial_formula/downtime_grace_cap_block_formula
        """
        ctx = create_job_in_progress()
        job_id = ctx["job"]["id"]
        event = open_and_close_downtime(job_id, "2026-08-01T01:40:00Z")
        assert event["duration_minutes"] == 100
        assert event["grace_minutes_applied"] == 30
        assert event["billable_minutes"] == 70
        assert event["billed_blocks"] == 5
        assert event["billed_amount_cents"] == 15000

    def test_second_event_capped_by_daily_accrual(self, api):
        """PRD §3.5: "then the daily cap applies: sum the `billable_minutes` of
        the job's other `CLOSED` or `BILLED` events sharing the same
        `closure_day`, and bill only what fits within the room remaining toward
        the 480-minute daily ceiling — eight hours — never less than zero."
        PRD §3.5: "The job's `standby_accrued_cents` is the running total of all
        of this: the sum of `billed_amount_cents` over the job's events in
        `CLOSED` or `BILLED`, recomputed immediately whenever an event closes or
        reverts".

        Design: Difficulty/combinatorial_formula/downtime_grace_cap_block_formula
        """
        ctx = create_job_in_progress()
        job_id = ctx["job"]["id"]
        # E1: 100 min CUSTOMER_DELAY -> 70 billable -> 15000c.
        e1 = open_and_close_downtime(job_id, "2026-08-01T01:40:00Z")
        # E2: opened at 01:40, closed at 09:20 -> 460 min; 430 raw, capped to 410.
        e2 = get_success_data(
            api.create_downtime_event(
                create_downtime_payload(job_id, cause="CUSTOMER_DELAY"), FS
            )
        )
        get_success_data(api.set_clock("2026-08-01T09:20:00Z", PA))
        e2_closed = get_success_data(api.close_downtime_event(e2["id"], FS))
        assert e2_closed["duration_minutes"] == 460
        assert e2_closed["billable_minutes"] == 410
        assert e2_closed["billed_blocks"] == 28
        assert e2_closed["billed_amount_cents"] == 84000

        job_after = get_success_data(api.get_job(job_id, PM))
        assert job_after["standby_accrued_cents"] == 99000


class TestGraceBoundary:
    def test_duration_equal_to_grace_bills_zero(self, api):
        """PRD §3.5: "a duration exactly equal to the grace bills exactly zero
        minutes".

        Design: Difficulty/boundary_precision_check/downtime_duration_equal_to_grace_bills_zero
        """
        ctx = create_job_in_progress()
        event = open_and_close_downtime(ctx["job"]["id"], "2026-08-01T00:30:00Z")
        assert event["duration_minutes"] == 30
        assert event["grace_minutes_applied"] == 30
        assert event["billable_minutes"] == 0
        assert event["billed_blocks"] == 0
        assert event["billed_amount_cents"] == 0

    def test_zero_billing_event_closes_and_accrual_stays_zero(self, api):
        """PRD §3.5: "a duration exactly equal to the grace bills exactly zero
        minutes".
        PRD §3.5: "The job's `standby_accrued_cents` is the running total of all
        of this: the sum of `billed_amount_cents` over the job's events in
        `CLOSED` or `BILLED`".

        Design: Difficulty/boundary_precision_check/downtime_duration_equal_to_grace_bills_zero
        """
        ctx = create_job_in_progress()
        job_id = ctx["job"]["id"]
        event = open_and_close_downtime(job_id, "2026-08-01T00:30:00Z")
        assert event["status"] == "CLOSED"
        assert event["billed_amount_cents"] == 0
        job_after = get_success_data(api.get_job(job_id, PM))
        assert job_after["standby_accrued_cents"] == 0


class TestOpenDowntimeGate:
    def test_open_downtime_blocks_field_completion(self, api):
        """PRD §3.4: "no downtime event may still be `OPEN`
        (`ERR_DOWNTIME_OPEN`)".

        Design: Corner/validations/open_downtime_blocks_field_completion
        """
        ctx = create_job_in_progress()
        job_id = ctx["job"]["id"]
        verify_containment(job_id)
        get_success_data(
            api.create_downtime_event(
                create_downtime_payload(job_id, cause="CONTRACTOR_FAULT"), FS
            )
        )
        resp = api.complete_field_work(
            job_id, {"gallons_removed": 100, "feet_cleaned": 0}, PM
        )
        validate_error(resp, ApiErrorId.ERR_DOWNTIME_OPEN.value)
        assert resp.status_code == 422

    def test_closing_downtime_unblocks_and_contractor_fault_bills_zero(self, api):
        """PRD §3.5: "A `CONTRACTOR_FAULT` event never bills — its
        `billable_minutes` is always zero."
        PRD §3.4: "no downtime event may still be `OPEN` (`ERR_DOWNTIME_OPEN`)".

        Design: Corner/validations/open_downtime_blocks_field_completion
        """
        ctx = create_job_in_progress()
        job_id = ctx["job"]["id"]
        verify_containment(job_id)
        event = get_success_data(
            api.create_downtime_event(
                create_downtime_payload(job_id, cause="CONTRACTOR_FAULT"), FS
            )
        )
        closed = get_success_data(api.close_downtime_event(event["id"], FS))
        assert closed["billed_amount_cents"] == 0
        assert closed["billable_minutes"] == 0
        completed = complete_field_work(job_id, gallons=100, feet=0)
        assert completed["execution_status"] == "FIELD_COMPLETE"
