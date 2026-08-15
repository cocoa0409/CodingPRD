"""Fundraising requirement variants, rank score, and threshold boundaries
(PRD §3.2, §3.3)."""
import pytest

from test_helpers import (
    TEST_USERS,
    create_contribution_payload,
    create_waitlisted_applicant,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
COORD_B = TEST_USERS["coordinator_b_headers"]
ADMIN = TEST_USERS["program_admin_headers"]


class TestFundraisingProvisionalVsFinal:
    """Difficulty/dual_variant_calc/fundraising_provisional_vs_final_requirement."""

    def test_provisional_requirement_written_at_approval(self, api):
        """PRD §3.2: "if gross is at least 1,000,000 cents the subsidy is 10
        percent, otherwise 15 percent; the subsidy is gross multiplied by that
        percentage, rounded half-up to a whole cent; and the requirement written
        to `requirement_provisional_cents` is gross minus income credit minus
        subsidy."

        MOBILITY gross 1,500,000 with income 4,500,000 (40% bracket):
        credit 600,000, subsidy 150,000 -> provisional 750,000.

        Design: Difficulty/dual_variant_calc/fundraising_provisional_vs_final_requirement
        """
        applicant, entry = create_waitlisted_applicant(
            track="MOBILITY", income_cents=4_500_000
        )
        assert entry["requirement_provisional_cents"] == 750_000, (
            f"provisional must be 750000, got {entry['requirement_provisional_cents']}"
        )
        assert entry["requirement_final_cents"] is None
        assert entry["effective_requirement_cents"] == 750_000
        assert entry["status"] == "PENDING"

    def test_final_requirement_diverges_after_recalculate(self, api):
        """PRD §3.2: "In the **final** variant — computed when an
        `IntakeCoordinator` recalculates an entry from verified income — the
        subsidy tier is keyed on the provisional net (the post-credit figure):
        provisional net of at least 1,000,000 cents yields 10 percent, otherwise
        15 percent; the subsidy is provisional net multiplied by that percentage,
        rounded half-up; and the requirement written to `requirement_final_cents`
        is provisional net minus subsidy."
        PRD §3.2: "Recalculation also copies the payload income onto the
        applicant as `verified_income_cents` and then re-evaluates eligibility
        exactly as a contribution receive or refund would."

        MOBILITY @ 4,500,000: provisional_net 900,000 < 1,000,000 -> 15% ->
        final 900,000 - 135,000 = 765,000; provisional stays 750,000.

        Design: Difficulty/dual_variant_calc/fundraising_provisional_vs_final_requirement
        """
        applicant, entry = create_waitlisted_applicant(
            track="MOBILITY", income_cents=4_500_000
        )
        updated = validate_success(
            api.recalculate_waitlist_entry(
                entry["id"], {"verified_income_cents": 4_500_000}, COORD
            )
        )
        assert updated["requirement_provisional_cents"] == 750_000
        assert updated["requirement_final_cents"] == 765_000
        assert updated["effective_requirement_cents"] == 765_000
        assert updated["status"] == "PENDING"
        reloaded = validate_success(api.get_applicant(applicant["id"], COORD))
        assert reloaded["verified_income_cents"] == 4_500_000


class TestFundraisingFinalVariantPinnedOrder:
    """Difficulty/combinatorial_formula/fundraising_final_variant_pinned_evaluation_order."""

    def test_provisional_variant_for_ptsd_low_income(self, api):
        """PRD §3.2: "Both then compute an income credit from the applicable
        income figure — the applicant's self-reported `household_income_cents`
        in the provisional variant, the payload `verified_income_cents` in the
        final variant. The credit percentage brackets, with inclusive lower
        boundaries, are: income below 3,000,000 cents earns a credit of 60
        percent of gross."

        PTSD gross 1,800,000 @ 2,000,000 income: credit 1,080,000; provisional
        subsidy keyed on gross >= 1,000,000 -> 10%: 1,800,000 - 1,080,000 -
        180,000 = 540,000.

        Design: Difficulty/combinatorial_formula/fundraising_final_variant_pinned_evaluation_order
        """
        _applicant, entry = create_waitlisted_applicant(
            track="PTSD", income_cents=2_000_000
        )
        assert entry["requirement_provisional_cents"] == 540_000

    def test_final_variant_uses_post_credit_net_for_tier(self, api):
        """PRD §3.2: "provisional net of at least 1,000,000 cents yields 10
        percent, otherwise 15 percent; the subsidy is provisional net multiplied
        by that percentage, rounded half-up; and the requirement written to
        `requirement_final_cents` is provisional net minus subsidy."

        PTSD @ 2,000,000: provisional_net 720,000 < 1,000,000 -> 15% ->
        720,000 - 108,000 = 612,000.

        Design: Difficulty/combinatorial_formula/fundraising_final_variant_pinned_evaluation_order
        """
        _applicant, entry = create_waitlisted_applicant(
            track="PTSD", income_cents=2_000_000
        )
        updated = validate_success(
            api.recalculate_waitlist_entry(
                entry["id"], {"verified_income_cents": 2_000_000}, COORD
            )
        )
        assert updated["requirement_provisional_cents"] == 540_000
        assert updated["requirement_final_cents"] == 612_000
        assert updated["effective_requirement_cents"] == 612_000


class TestWaitlistRankScore:
    """Difficulty/combinatorial_formula/waitlist_rank_score_weighted_caps_and_branches."""

    def test_rank_score_at_creation_has_no_wait_points(self, api):
        """PRD §3.2: "The wait component is the number of whole days between
        `listed_at` and the current logical time — partial days discarded —
        multiplied by 0.5 points per day, capped at 40 points. The urgency
        component is drawn from the `task_urgency_tier` of the applicant's
        latest `FINALIZED_ACCEPTED` assessment: 10 points for `STANDARD`, 25
        for `HIGH`, 40 for `CRITICAL`."

        At creation (clock == listed_at): 0 wait days -> CRITICAL 40 + home
        10*2 = 20 (capped 20) + no bonus -> 60.0.

        Design: Difficulty/combinatorial_formula/waitlist_rank_score_weighted_caps_and_branches
        """
        _applicant, entry = create_waitlisted_applicant(
            track="PTSD",
            income_cents=12_000_000,
            region="SW",
            required_tasks=("INTERRUPT_ANXIETY",),
            urgency="CRITICAL",
            home_score=10,
        )
        assert entry["status"] == "PENDING"
        assert entry["rank_score"] == pytest.approx(60.0, abs=0.01), (
            f"0 wait + 40 urgency + 20 home = 60.0, got {entry['rank_score']}"
        )

    def test_rank_score_with_caps_after_clock_advance(self, api):
        """PRD §3.2: "The wait component is the number of whole days between
        `listed_at` and the current logical time — partial days discarded —
        multiplied by 0.5 points per day, capped at 40 points. ... The
        fundraising bonus is 15 points while the entry is `ELIGIBLE`, zero
        otherwise. Finally, 10 points are subtracted for each dissolved match
        — the penalty is `dissolved_match_count` multiplied by 10."

        100 wait-days x 0.5 capped at 40; home 10x2 capped at 20; CRITICAL 40;
        PENDING adds no bonus; 0 dissolves -> 100.0.

        Design: Difficulty/combinatorial_formula/waitlist_rank_score_weighted_caps_and_branches
        """
        _applicant, entry = create_waitlisted_applicant(
            track="PTSD",
            income_cents=12_000_000,
            region="SW",
            required_tasks=("INTERRUPT_ANXIETY",),
            urgency="CRITICAL",
            home_score=10,
        )
        validate_success(
            api.set_clock({"to_iso8601": "2026-11-09T00:00:00Z"}, ADMIN)
        )
        updated = validate_success(api.get_waitlist_entry(entry["id"], COORD))
        assert updated["rank_score"] == pytest.approx(100.0, abs=0.01), (
            f"40 capped wait + 40 urgency + 20 capped home = 100.0, got "
            f"{updated['rank_score']}"
        )
        assert updated["status"] == "PENDING"


class TestFundraisingExactThreshold:
    """Difficulty/boundary_precision_check/fundraising_exact_threshold_crossing."""

    def test_one_cent_below_requirement_stays_pending(self, api):
        """PRD §3.2: "Whenever a receive or a recalculation leaves
        `raised_cents` at least equal to `effective_requirement_cents` — the
        boundary is inclusive — a `PENDING` entry flips to `ELIGIBLE`, and its
        applicant mirrors from `WAITLISTED` to `MATCH_ELIGIBLE`."

        FACILITY @ 12,000,000 -> requirement 765,000; 764,900 raised stays
        PENDING.

        Design: Difficulty/boundary_precision_check/fundraising_exact_threshold_crossing
        """
        applicant, entry = create_waitlisted_applicant(
            track="FACILITY", income_cents=12_000_000
        )
        assert entry["effective_requirement_cents"] == 765_000
        contribution = validate_success(
            api.create_contribution(
                applicant["id"],
                create_contribution_payload(amount_cents=764_900),
                COORD,
            ),
            expected_status=201,
        )
        validate_success(api.receive_contribution(contribution["id"], COORD_B))
        updated = validate_success(api.get_waitlist_entry(entry["id"], COORD))
        assert updated["raised_cents"] == 764_900
        assert updated["status"] == "PENDING", (
            "764,900 < 765,000 must leave the entry PENDING"
        )

    def test_exact_requirement_flips_to_eligible(self, api):
        """PRD §3.2: "Whenever a receive or a recalculation leaves
        `raised_cents` at least equal to `effective_requirement_cents` — the
        boundary is inclusive — a `PENDING` entry flips to `ELIGIBLE`, and its
        applicant mirrors from `WAITLISTED` to `MATCH_ELIGIBLE`."

        764,900 already received; adding exactly 100 cents reaches 765,000 ==
        requirement -> ELIGIBLE and applicant MATCH_ELIGIBLE.

        Design: Difficulty/boundary_precision_check/fundraising_exact_threshold_crossing
        """
        applicant, entry = create_waitlisted_applicant(
            track="FACILITY", income_cents=12_000_000
        )
        c1 = validate_success(
            api.create_contribution(
                applicant["id"],
                create_contribution_payload(amount_cents=764_900),
                COORD,
            ),
            expected_status=201,
        )
        validate_success(api.receive_contribution(c1["id"], COORD_B))
        c2 = validate_success(
            api.create_contribution(
                applicant["id"],
                create_contribution_payload(amount_cents=100),
                COORD,
            ),
            expected_status=201,
        )
        validate_success(api.receive_contribution(c2["id"], COORD_B))
        updated = validate_success(api.get_waitlist_entry(entry["id"], COORD))
        assert updated["raised_cents"] == 765_000
        assert updated["status"] == "ELIGIBLE", (
            "765,000 >= 765,000 — inclusive boundary flips to ELIGIBLE"
        )
        applicant_now = validate_success(api.get_applicant(applicant["id"], COORD))
        assert applicant_now["application_status"] == "MATCH_ELIGIBLE"


class TestRefundClawbackCascade:
    """Difficulty/transitive_cascade/refund_clawback_revert_chain."""

    def _funded_facility_entry(self, api):
        applicant, entry = create_waitlisted_applicant(
            track="FACILITY", income_cents=12_000_000
        )
        c1 = validate_success(
            api.create_contribution(
                applicant["id"],
                create_contribution_payload(amount_cents=500_000),
                COORD,
            ),
            expected_status=201,
        )
        validate_success(api.receive_contribution(c1["id"], COORD_B))
        c2 = validate_success(
            api.create_contribution(
                applicant["id"],
                create_contribution_payload(amount_cents=300_000),
                COORD,
            ),
            expected_status=201,
        )
        validate_success(api.receive_contribution(c2["id"], COORD_B))
        return applicant, entry, c1, c2

    def test_refund_reverts_entry_and_applicant(self, api):
        """PRD §3.3: "An allowed refund moves the contribution to `REFUNDED`
        and runs the clawback: the entry's `raised_cents` is reduced by the
        refunded `amount_cents`; if the entry was `ELIGIBLE` and the reduced
        total is now strictly below `effective_requirement_cents`, the entry
        reverts to `PENDING` and the applicant mirrors from `MATCH_ELIGIBLE`
        to `WAITLISTED`, with `rank_score` recomputed without the bonus."

        Design: Difficulty/transitive_cascade/refund_clawback_revert_chain
        """
        applicant, entry, _c1, c2 = self._funded_facility_entry(api)
        pre = validate_success(api.get_waitlist_entry(entry["id"], COORD))
        assert pre["status"] == "ELIGIBLE" and pre["raised_cents"] == 800_000
        refunded = validate_success(api.refund_contribution(c2["id"], COORD))
        assert refunded["status"] == "REFUNDED"
        post = validate_success(api.get_waitlist_entry(entry["id"], COORD))
        assert post["raised_cents"] == 500_000
        assert post["status"] == "PENDING", "500,000 < 765,000 reverts entry"
        applicant_now = validate_success(api.get_applicant(applicant["id"], COORD))
        assert applicant_now["application_status"] == "WAITLISTED"

    def test_refund_that_stays_above_threshold_keeps_eligible(self, api):
        """PRD §3.3: "if the entry was `ELIGIBLE` and the reduced total is now
        strictly below `effective_requirement_cents`, the entry reverts to
        `PENDING` and the applicant mirrors from `MATCH_ELIGIBLE` to
        `WAITLISTED`, with `rank_score` recomputed without the bonus."

        Refunding only 35,000 of 800,000 leaves 765,000 >= 765,000 — the entry
        must stay ELIGIBLE (the flip fires only strictly below).

        Design: Difficulty/transitive_cascade/refund_clawback_revert_chain
        """
        applicant, entry = create_waitlisted_applicant(
            track="FACILITY", income_cents=12_000_000
        )
        c1 = validate_success(
            api.create_contribution(
                applicant["id"],
                create_contribution_payload(amount_cents=765_000),
                COORD,
            ),
            expected_status=201,
        )
        validate_success(api.receive_contribution(c1["id"], COORD_B))
        c2 = validate_success(
            api.create_contribution(
                applicant["id"],
                create_contribution_payload(amount_cents=35_000),
                COORD,
            ),
            expected_status=201,
        )
        validate_success(api.receive_contribution(c2["id"], COORD_B))
        validate_success(api.refund_contribution(c2["id"], COORD))
        post = validate_success(api.get_waitlist_entry(entry["id"], COORD))
        assert post["raised_cents"] == 765_000
        assert post["status"] == "ELIGIBLE", (
            "765,000 >= 765,000 — entry must stay ELIGIBLE"
        )
        applicant_now = validate_success(api.get_applicant(applicant["id"], COORD))
        assert applicant_now["application_status"] == "MATCH_ELIGIBLE"


class TestFundraisingLedgerConservation:
    """Difficulty/compensating_invariant/fundraising_ledger_conservation."""

    def test_raised_cents_tracks_received_sum_forward(self, api):
        """PRD §3.2: "The entry's `raised_cents` is at all times the sum of
        `amount_cents` over the applicant's contributions in `RECEIVED` status
        — this ledger invariant is maintained on every receive, refund, and
        withdrawal."

        Receive 400,000 + 200,000 -> raised 600,000 (still PENDING, below
        765,000).

        Design: Difficulty/compensating_invariant/fundraising_ledger_conservation
        """
        applicant, entry = create_waitlisted_applicant(
            track="FACILITY", income_cents=12_000_000
        )
        c1 = validate_success(
            api.create_contribution(
                applicant["id"],
                create_contribution_payload(amount_cents=400_000),
                COORD,
            ),
            expected_status=201,
        )
        c2 = validate_success(
            api.create_contribution(
                applicant["id"],
                create_contribution_payload(amount_cents=200_000),
                COORD,
            ),
            expected_status=201,
        )
        validate_success(api.receive_contribution(c1["id"], COORD_B))
        validate_success(api.receive_contribution(c2["id"], COORD_B))
        mid = validate_success(api.get_waitlist_entry(entry["id"], COORD))
        assert mid["raised_cents"] == 600_000
        assert mid["status"] == "PENDING"

    def test_raised_cents_settles_to_zero_after_refunds(self, api):
        """PRD §3.2: "The entry's `raised_cents` is at all times the sum of
        `amount_cents` over the applicant's contributions in `RECEIVED` status
        — this ledger invariant is maintained on every receive, refund, and
        withdrawal."

        600,000 received; refund 400,000 -> 200,000; refund 200,000 -> 0 with
        no drift at any step; entry never leaves PENDING.

        Design: Difficulty/compensating_invariant/fundraising_ledger_conservation
        """
        applicant, entry = create_waitlisted_applicant(
            track="FACILITY", income_cents=12_000_000
        )
        c1 = validate_success(
            api.create_contribution(
                applicant["id"],
                create_contribution_payload(amount_cents=400_000),
                COORD,
            ),
            expected_status=201,
        )
        c2 = validate_success(
            api.create_contribution(
                applicant["id"],
                create_contribution_payload(amount_cents=200_000),
                COORD,
            ),
            expected_status=201,
        )
        validate_success(api.receive_contribution(c1["id"], COORD_B))
        validate_success(api.receive_contribution(c2["id"], COORD_B))
        validate_success(api.refund_contribution(c1["id"], COORD))
        post = validate_success(api.get_waitlist_entry(entry["id"], COORD))
        assert post["raised_cents"] == 200_000
        validate_success(api.refund_contribution(c2["id"], COORD))
        zero = validate_success(api.get_waitlist_entry(entry["id"], COORD))
        assert zero["raised_cents"] == 0
        assert zero["status"] == "PENDING"
