"""Payment milestones: overdue auto-transition, cure compensation, default
grace gate, and deal posture evolving in parallel with deal status."""
import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock,
    get_deal,
    get_milestone,
    pay_milestone_on_time,
    setup_executed_deal,
    validate_error,
    validate_success,
)

RM = TEST_USERS["rights_manager_headers"]
FC = TEST_USERS["finance_controller_headers"]


class TestParallelPostureAndStatus:
    def test_first_overdue_warns_while_deal_stays_executed(self, api):
        """PRD §2.10: "a deal is `WARNING` when its
        `payment_delinquency_count` is exactly 1 or 2".
        PRD §3.5: "Once the clock passes the `due_date` of a milestone still
        sitting `INVOICED`, the system moves it to `OVERDUE` automatically:
        the deal's `payment_delinquency_count` rises by one".

        Design: Difficulty/non_linear_state_machine/deal_parallel_posture_and_status_dimensions
        """
        bundle = setup_executed_deal(
            milestone_specs=[(1, 1, "2026-09-01T00:00:00Z", 1.0)]
        )
        deal_id = bundle["deal"]["id"]
        ms1 = bundle["milestones"][0]
        validate_success(api.invoice_milestone(deal_id, ms1["id"], FC), 200)

        advance_clock("2026-09-15T00:00:00Z")

        milestone = get_milestone(deal_id, ms1["id"])
        assert milestone["status"] == "OVERDUE"
        deal = get_deal(deal_id)
        assert deal["payment_delinquency_count"] == 1
        assert deal["posture"] == "WARNING"
        assert deal["status"] == "EXECUTED"

    def test_second_overdue_keeps_warning_while_status_unchanged(self, api):
        """PRD §2.10: "a deal is `WARNING` when its
        `payment_delinquency_count` is exactly 1 or 2".
        PRD §3.5: "the deal's `payment_delinquency_count` rises by one".

        Design: Difficulty/non_linear_state_machine/deal_parallel_posture_and_status_dimensions
        """
        bundle = setup_executed_deal(
            milestone_specs=[
                (1, 1, "2026-09-01T00:00:00Z", 0.5),
                (1, 2, "2026-10-01T00:00:00Z", 0.5),
            ]
        )
        deal_id = bundle["deal"]["id"]
        for m in bundle["milestones"]:
            validate_success(api.invoice_milestone(deal_id, m["id"], FC), 200)

        advance_clock("2026-10-15T00:00:00Z")

        deal = get_deal(deal_id)
        assert deal["payment_delinquency_count"] == 2
        assert deal["posture"] == "WARNING"
        # No milestone was ever paid, so the deal never left EXECUTED even
        # while posture moved CLEAN -> WARNING: the two dimensions are
        # independent.
        assert deal["status"] == "EXECUTED"


class TestCureCompensation:
    def test_overdue_transition_increments_delinquency(self, api):
        """PRD §3.5: "Once the clock passes the `due_date` of a milestone
        still sitting `INVOICED`, the system moves it to `OVERDUE`
        automatically: the deal's `payment_delinquency_count` rises by one".

        Design: Difficulty/compensating_invariant/payment_cure_conserves_delinquency_count
        """
        bundle = setup_executed_deal(
            milestone_specs=[(1, 1, "2026-09-01T00:00:00Z", 1.0)]
        )
        deal_id = bundle["deal"]["id"]
        ms1 = bundle["milestones"][0]
        assert get_deal(deal_id)["payment_delinquency_count"] == 0
        validate_success(api.invoice_milestone(deal_id, ms1["id"], FC), 200)

        advance_clock("2026-09-02T00:00:00Z")

        assert get_milestone(deal_id, ms1["id"])["status"] == "OVERDUE"
        deal = get_deal(deal_id)
        assert deal["payment_delinquency_count"] == 1
        assert deal["posture"] == "WARNING"

    def test_record_payment_cures_and_restores_count(self, api):
        """PRD §3.5: "Payment recorded against an `OVERDUE` milestone moves
        it to `CURED`: `paid_at` is stamped, the late fee is finalized as the
        number of days between `due_date` and the payment instant multiplied
        by `escalated_amount_cents` and by the daily rate of 0.0005, the
        deal's `payment_delinquency_count` falls by one, and posture is
        re-evaluated."

        One day late on a 1000000-cent milestone: 1 * 1000000 * 0.0005 = 500.

        Design: Difficulty/compensating_invariant/payment_cure_conserves_delinquency_count
        """
        bundle = setup_executed_deal(
            milestone_specs=[(1, 1, "2026-09-01T00:00:00Z", 1.0)],
            bid_overrides={"offered_fee_cents": 1000000, "fee_cap_cents": 2000000},
        )
        deal_id = bundle["deal"]["id"]
        ms1 = bundle["milestones"][0]
        validate_success(api.invoice_milestone(deal_id, ms1["id"], FC), 200)
        advance_clock("2026-09-02T00:00:00Z")
        assert get_deal(deal_id)["payment_delinquency_count"] == 1

        cured = validate_success(api.record_payment(deal_id, ms1["id"], FC), 200)
        assert cured["status"] == "CURED"
        assert cured["late_fee_cents"] == 500
        deal = get_deal(deal_id)
        assert deal["payment_delinquency_count"] == 0
        assert deal["posture"] == "CLEAN"


class TestOverdueRecordPayment:
    def test_overdue_milestone_cures_not_pays_with_late_fee(self, api):
        """PRD §3.5: "Payment recorded against an `OVERDUE` milestone moves
        it to `CURED`".

        Twenty-eight days late on a 1000000-cent milestone:
        28 * 1000000 * 0.0005 = 14000.

        Design: Corner/state_machines/payment_milestone_overdue_to_paid_skipped
        """
        bundle = setup_executed_deal(
            milestone_specs=[(1, 1, "2026-09-01T00:00:00Z", 1.0)],
            bid_overrides={"offered_fee_cents": 1000000, "fee_cap_cents": 2000000},
        )
        deal_id = bundle["deal"]["id"]
        ms1 = bundle["milestones"][0]
        validate_success(api.invoice_milestone(deal_id, ms1["id"], FC), 200)
        advance_clock("2026-09-29T00:00:00Z")
        assert get_milestone(deal_id, ms1["id"])["status"] == "OVERDUE"

        cured = validate_success(api.record_payment(deal_id, ms1["id"], FC), 200)
        assert cured["status"] == "CURED"
        assert cured["late_fee_cents"] == 14000


class TestTemporalVsFiscalGates:
    def _setup_delinquent_active_deal(self, api):
        """ACTIVE deal with one OVERDUE milestone one hour past its due date.

        Season weights sum to 1.0 (0.5 + 0.5); the second milestone is paid
        on time so the deal reaches ACTIVE, then the clock passes the first
        milestone's due date.
        """
        bundle = setup_executed_deal(
            milestone_specs=[
                (1, 1, "2026-09-01T00:00:00Z", 0.5),
                (1, 2, "2026-12-01T00:00:00Z", 0.5),
            ]
        )
        deal_id = bundle["deal"]["id"]
        ms1, ms2 = bundle["milestones"]
        validate_success(api.invoice_milestone(deal_id, ms1["id"], FC), 200)
        pay_milestone_on_time(deal_id, ms2["id"])
        advance_clock("2026-09-01T01:00:00Z")
        return bundle, ms1

    def test_declare_default_before_grace_elapsed_rejected(self, api):
        """PRD §3.5: "the current logical clock must have reached `due_date`
        plus `DEFAULT_GRACE_DAYS`, failing which the request is rejected with
        `ERR_DEFAULT_GRACE_NOT_ELAPSED`."

        Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_fiscal_on_deal_termination
        """
        bundle, ms1 = self._setup_delinquent_active_deal(api)
        deal_id = bundle["deal"]["id"]
        assert get_milestone(deal_id, ms1["id"])["status"] == "OVERDUE"
        res = api.declare_default(deal_id, ms1["id"], FC)
        validate_error(res, "ERR_DEFAULT_GRACE_NOT_ELAPSED", expected_status=409)

    def test_terminate_convenience_with_delinquency_rejected(self, api):
        """PRD §3.9: "Termination for convenience is the `RightsManager`'s
        cleaner exit, available on an `ACTIVE` deal only while its
        `payment_delinquency_count` is zero (`ERR_OUTSTANDING_DELINQUENCY`
        otherwise)".

        Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_fiscal_on_deal_termination
        """
        bundle, _ms1 = self._setup_delinquent_active_deal(api)
        deal_id = bundle["deal"]["id"]
        deal = get_deal(deal_id)
        assert deal["status"] == "ACTIVE"
        assert deal["payment_delinquency_count"] == 1
        res = api.terminate_convenience(deal_id, RM)
        validate_error(res, "ERR_OUTSTANDING_DELINQUENCY", expected_status=409)
