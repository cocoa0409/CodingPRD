"""A pre-census withdrawal recovers every cent that was accrued.

Two accruals total 256113 cents, one of them already paid out.  A withdrawal
before the enrollment census reverses all of it at a proration of 1.0000, and the
paid portion alone survives as a recoverable liability.  Both net figures read
the accrual side over ACCRUED, APPROVED and PAID only, so once each parent has
moved to CLAWED_BACK the accrual side is empty and the reversal total stands
alone.
"""

import pytest

from test_helpers import constants as C
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_cents, assert_projection, one_entry


@pytest.fixture()
def withdrawn_before_census(client):
    """One paid deposit accrual, one merely accrued enrollment accrual, then a withdrawal."""
    partner = fx.build_active_partner(client)
    admitted = fx.build_admitted_application(
        client,
        partner,
        student_ref="STU-8001",
        passport_hash="hash-passport-8001",
        applicant_user_id="applicant-8001",
    )

    fx.set_clock(client, "2026-09-05T00:00:00Z")
    after_deposit = fx.register_milestone(
        client,
        admitted["application_id"],
        C.MILESTONE_DEPOSIT_PAID,
        "2026-09-05",
        admitted["version"],
    )

    entries = fx.read_entries(
        client,
        application_id=admitted["application_id"],
        kind=C.ENTRY_KIND_ACCRUAL,
        milestone=C.MILESTONE_DEPOSIT_PAID,
    )
    deposit_entry_id = entries[0]["id"]
    fx.approve_entry(client, deposit_entry_id)
    fx.pay_entry(client, deposit_entry_id)

    fx.set_clock(client, "2026-09-10T00:00:00Z")
    fx.register_milestone(
        client,
        admitted["application_id"],
        C.MILESTONE_ENROLLED,
        "2026-09-10",
        after_deposit["version"],
    )

    fx.set_clock(client, "2026-09-20T00:00:00Z")

    return {
        "partner": partner,
        "agency_id": partner["agency_id"],
        "application_id": admitted["application_id"],
        "deposit_entry_id": deposit_entry_id,
    }


@pytest.fixture()
def after_withdrawal(client, withdrawn_before_census):
    """Record the withdrawal that runs the clawback ledger."""
    fx.withdraw_application(
        client,
        withdrawn_before_census["application_id"],
        "2026-09-20",
        "Visa refused before census",
    )
    return withdrawn_before_census


class TestWithdrawalRestoresZeroNet:
    def test_a_pre_census_withdrawal_reverses_both_accruals_in_full(
        self, client, after_withdrawal
    ):
        """The proration is the whole of it, so each reversal equals its parent.

        "If the `withdrawal_date` falls strictly before the program's
        `census_date`, the percentage is the whole of it — 1.0000 — because a
        student who leaves before the enrollment census was never really
        enrolled."

        "The reversible set is that application's `ACCRUAL` entries whose `state`
        is `ACCRUED`, `APPROVED` or `PAID`"

        Design: Difficulty/compensating_invariant/withdrawal_clawback_restores_zero_net_with_paid_liability
        """
        env = after_withdrawal
        entries = fx.read_entries(client, application_id=env["application_id"])

        deposit_reversal = one_entry(
            entries, C.ENTRY_KIND_CLAWBACK, C.MILESTONE_DEPOSIT_PAID
        )
        assert_cents(deposit_reversal["amount_cents"], 113828, "deposit reversal")
        assert deposit_reversal["parent_entry_id"] == env["deposit_entry_id"]

        enrollment_reversal = one_entry(
            entries, C.ENTRY_KIND_CLAWBACK, C.MILESTONE_ENROLLED
        )
        assert_cents(enrollment_reversal["amount_cents"], 142285, "enrollment reversal")

        paid_parent = one_entry(
            entries, C.ENTRY_KIND_ACCRUAL, C.MILESTONE_DEPOSIT_PAID
        )
        assert paid_parent["state"] == C.ENTRY_CLAWED_BACK, (
            "an already-paid accrual is still reversible"
        )

    def test_the_net_returns_to_zero_while_the_paid_portion_remains_a_liability(
        self, client, after_withdrawal
    ):
        """Only money that actually left the institution is recoverable.

        "If the parent accrual's `state` was `PAID` — meaning the money had
        already left the institution — the reversal amount is added to the
        agency's `clawback_liability_cents`."

        "`net_earned_commission_cents` is the sum of `amount_cents` over every
        `ACCRUAL` entry reachable from the agency through its contracts whose
        `state` is `ACCRUED`, `APPROVED` or `PAID`, minus the sum of
        `amount_cents` over every such `CLAWBACK` entry whose `state` is
        `CLAWED_BACK`"

        Design: Difficulty/compensating_invariant/withdrawal_clawback_restores_zero_net_with_paid_liability
        """
        env = after_withdrawal

        # Both parents moved to CLAWED_BACK, which is outside the ACCRUED /
        # APPROVED / PAID window the accrual side of the formula reads, so the
        # figures carry the negated reversal total.
        application = fx.read_application(client, env["application_id"])
        assert_cents(
            application["net_commission_cents"], -256113, "net_commission_cents"
        )
        assert application["status"] == C.APPLICATION_WITHDRAWN

        agency = fx.read_agency(client, env["agency_id"])
        assert_cents(
            agency["net_earned_commission_cents"], -256113, "net_earned_commission_cents"
        )
        assert_cents(
            agency["clawback_liability_cents"], 113828, "clawback_liability_cents"
        )

    def test_the_projection_view_keeps_the_frozen_variant_beside_the_zero_outcome(
        self, client, after_withdrawal
    ):
        """The provisional figure never moves; only the realised one does.

        "Both figures are readable side by side on a per-application computed view,
        which reports `provisional_projection_cents` mirroring
        `projected_commission_cents`, `final_net_cents` mirroring
        `net_commission_cents`, and `variant_delta_cents` as the provisional projection
        minus the final net."

        "if the agency's total clawback amount divided by its total lifetime
        accrual amount reaches 0.25 — a quarter of everything ever accrued having
        been reversed — and its integrity standing is `GOOD_STANDING`, that
        standing escalates to `WATCH`"

        Design: Difficulty/compensating_invariant/withdrawal_clawback_restores_zero_net_with_paid_liability
        """
        env = after_withdrawal

        projection = fx.read_projection(client, env["application_id"])
        assert_projection(
            projection,
            provisional_projection_cents=355713,
            final_net_cents=-256113,
            variant_delta_cents=611826,
            accrued_entry_count=2,
            clawback_entry_count=2,
        )

        agency = fx.read_agency(client, env["agency_id"])
        assert agency["compliance_posture"] == C.POSTURE_WATCH

    def test_the_pre_withdrawal_position_is_the_undisturbed_sum_of_both_accruals(
        self, client, withdrawn_before_census
    ):
        """256113 cents stood on the books, with nothing recoverable yet.

        "Both agency aggregates are always recomputed in full from ledger rows,
        never adjusted incrementally."

        Design: Difficulty/compensating_invariant/withdrawal_clawback_restores_zero_net_with_paid_liability
        """
        env = withdrawn_before_census

        agency = fx.read_agency(client, env["agency_id"])
        assert_cents(
            agency["net_earned_commission_cents"],
            256113,
            "net_earned_commission_cents",
        )
        assert_cents(agency["clawback_liability_cents"], 0, "clawback_liability_cents")
        assert agency["compliance_posture"] == C.POSTURE_GOOD_STANDING
