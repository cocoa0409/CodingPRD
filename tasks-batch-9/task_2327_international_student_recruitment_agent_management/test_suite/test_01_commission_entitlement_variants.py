"""The two commission entitlement figures diverge when the tier drops.

A student file is submitted while the agency holds the top performance tier and
then reaches its first enrollment milestone after a fresh scorecard has knocked
the agency down to the bottom tier.  The frozen projection keeps pricing all
four milestones at the submission tier, while the ledger prices the one
milestone actually reached at the tier resolved on that milestone's own date.
"""

import pytest

from test_helpers import constants as C
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_accrual_entry,
    assert_cents,
    assert_projection,
    assert_rate_4dp,
    one_entry,
)


@pytest.fixture()
def tier_drop_environment(client):
    """A top-tier submission followed by a tier drop and one milestone.

    The first cohort runs a perfect chain on a non-commissionable foundation
    programme, so the closed window scores the maximum composite and no ledger
    rows exist yet.  The second student file is submitted on the day after that
    window closes, and only then is a second, deliberately barren window scored.
    """
    partner = fx.build_platinum_history(client)

    fx.set_clock(client, "2026-08-12T00:00:00Z")
    ready = fx.build_submission_ready_application(
        client,
        partner,
        student_ref="STU-1001",
        passport_hash="hash-passport-1001",
        applicant_user_id="applicant-1001",
        program_id=partner["masters_program_id"],
    )
    submitted = fx.submit_application(
        client, partner["agency_id"], ready["application_id"]
    )

    fx.set_clock(client, "2026-08-14T00:00:00Z")
    watch_scorecard = fx.run_scorecard(
        client, partner["agency_id"], "2026-08-12", "2026-08-13"
    )
    admitted = fx.admit_application(client, ready["application_id"])

    fx.set_clock(client, "2026-08-20T00:00:00Z")
    fx.register_milestone(
        client,
        ready["application_id"],
        C.MILESTONE_DEPOSIT_PAID,
        "2026-08-20",
        admitted["version"],
    )

    return {
        "partner": partner,
        "application_id": ready["application_id"],
        "submitted": submitted,
        "platinum_scorecard": partner["platinum_scorecard"],
        "watch_scorecard": watch_scorecard,
    }


class TestCommissionEntitlementVariants:
    def test_provisional_projection_freezes_the_submission_tier_for_all_four_milestones(
        self, client, tier_drop_environment
    ):
        """The projection is computed once at submission and never recomputed.

        "`projected_commission_cents` is the *provisional forward-looking*
        figure, frozen at submission and never recomputed: it is the sum of the
        four milestone amounts for `DEPOSIT_PAID`, `ENROLLED`,
        `CENSUS_CONFIRMED` and `PERSISTED`, each priced by the rule above using
        the pinned rate card and the single frozen
        `tier_snapshot_at_submission`, each rounded independently before being
        added."

        "It resolves the agency's performance tier as of `submitted_on` and
        freezes it into `tier_snapshot_at_submission`."

        Design: Difficulty/dual_variant_calc/commission_projection_versus_final_net_after_tier_drop
        """
        env = tier_drop_environment
        platinum = env["platinum_scorecard"]
        assert platinum["tier"] == C.TIER_PLATINUM
        assert_rate_4dp(platinum["composite_score"], 1.0000, "composite_score")

        submitted = env["submitted"]
        assert submitted["tier_snapshot_at_submission"] == C.TIER_PLATINUM
        assert_cents(
            submitted["projected_commission_cents"],
            484971,
            "projected_commission_cents at submission",
        )

        # The accrual that follows the tier drop must not disturb the frozen figure.
        after = fx.read_application(client, env["application_id"])
        assert after["tier_snapshot_at_submission"] == C.TIER_PLATINUM
        assert_cents(
            after["projected_commission_cents"],
            484971,
            "projected_commission_cents after the accrual",
        )

    def test_final_net_prices_the_reached_milestone_at_its_own_event_date_tier(
        self, client, tier_drop_environment
    ):
        """The accrual reads the tier resolved at the milestone's own date.

        "`tier_snapshot` set to the tier resolved by the rule above *at that
        entry's own `milestone_event_date`* — not at the submission date."

        "`WATCH` *subtracts* 100"

        "`variant_delta_cents` as the provisional projection minus the final
        net."

        Design: Difficulty/dual_variant_calc/commission_projection_versus_final_net_after_tier_drop
        """
        env = tier_drop_environment
        watch = env["watch_scorecard"]
        assert watch["submitted_count"] == 1
        assert_rate_4dp(watch["yield_rate"], 0.0000, "yield_rate")
        assert_rate_4dp(watch["composite_score"], 0.2000, "composite_score")
        assert watch["tier"] == C.TIER_WATCH
        assert watch["posture_action_applied"] == C.POSTURE_ACTION_ESCALATED_TO_WATCH

        agency = fx.read_agency(client, env["partner"]["agency_id"])
        assert agency["compliance_posture"] == C.POSTURE_WATCH

        entries = fx.read_entries(client, application_id=env["application_id"])
        deposit = one_entry(entries, C.ENTRY_KIND_ACCRUAL, C.MILESTONE_DEPOSIT_PAID)
        assert_accrual_entry(
            deposit,
            milestone=C.MILESTONE_DEPOSIT_PAID,
            tier_snapshot=C.TIER_WATCH,
            effective_bps=300,
            amount_cents=85371,
        )

        application = fx.read_application(client, env["application_id"])
        assert_cents(
            application["net_commission_cents"], 85371, "net_commission_cents"
        )

        projection = fx.read_projection(client, env["application_id"])
        assert_projection(
            projection,
            provisional_projection_cents=484971,
            final_net_cents=85371,
            variant_delta_cents=399600,
            accrued_entry_count=1,
            clawback_entry_count=0,
        )
        assert projection["tier_snapshot_at_submission"] == C.TIER_PLATINUM
