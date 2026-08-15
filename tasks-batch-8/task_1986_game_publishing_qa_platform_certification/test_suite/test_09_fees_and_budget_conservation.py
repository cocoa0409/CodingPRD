"""Submission fee tiers and multipliers (PRD §3.5), the cert-budget
conservation invariant across submit/decide/withdraw (PRD §2.7), and the
default-clock weekend uplift (PRD §2.4)."""
from test_helpers import (
    TEST_USERS,
    api_client,
    assert_budget_invariant,
    assert_clock_instant,
    create_submission_package,
    decide_package,
    get_checklist_id_for_package,
    get_title,
    review_package,
    set_clock,
    setup_submittable_package,
    submit_package,
    validate_success,
    verify_checklist_pass_sequence,
)

CL_HEADERS = TEST_USERS["certification_lead_headers"]
MONDAY_AM = "2026-08-03T10:00:00Z"


class TestSubmissionFeeTiers:
    def _setup_round2_expedited_package(self):
        """Round-2 expedited package ready to submit: round 1 submitted on a
        Monday then REJECTED; round 2 assembled on the same CANDIDATE build
        with its checklist fully verified."""
        set_clock("2026-08-03T09:00:00Z")
        ctx = setup_submittable_package(title_code="COMB-FEE",
                                        cert_budget_total_cents=2_000_000)
        set_clock(MONDAY_AM)
        submit_package(ctx["package"]["id"])
        review_package(ctx["package"]["id"])
        decide_package(ctx["package"]["id"], "REJECTED")
        # The rejected round leaves the build CANDIDATE; the new assembly for
        # the same (title, platform) computes round 2.
        pkg2 = create_submission_package(
            ctx["title"]["id"], "PS5", ctx["build"]["id"], ctx["plan"]["id"],
            expedited=True,
        )
        checklist_id = get_checklist_id_for_package(pkg2["id"])
        verify_checklist_pass_sequence(checklist_id, "PS5")
        set_clock("2026-08-08T10:00:00Z")  # a Saturday
        return ctx, pkg2

    def test_round_two_expedited_weekend_fee(self, api):
        """PRD §3.5: "The base fee is 120000 cents for `PS5`, 120000 for
        `XSX`, 90000 for `SWITCH2`, and 60000 for `PC`. The base is multiplied
        by a round factor — 1.00 on round one, 0.50 on round two, and 0.25 on
        round three and every later round — then by an expedite factor of 1.75
        when `expedited` is true (1.00 otherwise), then by a weekend factor of
        1.20 when the submit instant falls on a Saturday or Sunday in UTC
        (1.00 otherwise). The product is rounded half-up to whole cents
        exactly once, after all multipliers have been applied, and the charged
        `fee_cents` is the lesser of that rounded product and the platform cap
        — 250000 cents for `PS5`, 250000 for `XSX`, 200000 for `SWITCH2`, and
        150000 for `PC`."
        PRD §3.5: "The new package starts `ASSEMBLING` with its `round`
        computed as one plus the count of prior non-superseded packages for
        the same title and platform."

        Design: Difficulty/combinatorial_formula/submission_fee_tiered_expedited_weekend
        """
        _ctx, pkg2 = self._setup_round2_expedited_package()
        assert pkg2["round"] == 2
        pkg2 = submit_package(pkg2["id"])
        # round_half_up(120000 x 0.50 x 1.75 x 1.20) = 126000; cap 250000 not
        # binding.
        assert pkg2["fee_cents"] == 126000

    def test_round_two_fee_moves_into_escrow_over_spent(self, api):
        """PRD §2.7: "`cert_budget_escrow_cents` holds fees provisionally
        committed — the sum of `fee_cents` over the title's submission
        packages currently in `SUBMITTED` or `IN_REVIEW`;
        `cert_budget_spent_cents` accumulates irrevocable charges — decided
        package fees (whether the package was approved or rejected),
        age-rating fees charged at filing, release-window fees charged at
        confirmation, and expedited hotfix certification fees charged when a
        hotfix enters expedited review"

        Design: Difficulty/combinatorial_formula/submission_fee_tiered_expedited_weekend
        """
        ctx, pkg2 = self._setup_round2_expedited_package()
        submit_package(pkg2["id"])
        title = get_title(ctx["title"]["id"])
        assert title["cert_budget_escrow_cents"] == 126000
        # 120000 rejected round-1 fee + 40000 ESRB filing fee.
        assert title["cert_budget_spent_cents"] == 160000
        assert_budget_invariant(title)


class TestBudgetConservation:
    def _setup_rejected_round1(self):
        """Chain with round 1 submitted on a Monday (fee 120000 in escrow),
        then REJECTED (escrow converts to spent)."""
        set_clock("2026-08-03T09:00:00Z")
        ctx = setup_submittable_package(title_code="INV-BGT",
                                        cert_budget_total_cents=1_000_000)
        # Baseline after the ESRB filing fee (40000) charged to spent.
        title = get_title(ctx["title"]["id"])
        assert title["cert_budget_available_cents"] == 960000
        assert title["cert_budget_escrow_cents"] == 0
        assert title["cert_budget_spent_cents"] == 40000
        assert_budget_invariant(title)
        set_clock(MONDAY_AM)
        return ctx

    def test_submit_and_decide_checkpoints_conserve_budget(self, api):
        """PRD §2.7: "The three partitions are defined so that available
        equals `cert_budget_total_cents` minus escrow minus spent, and the
        conserved invariant is that available, escrow, and spent always sum
        exactly to `cert_budget_total_cents`. A withdrawal refunds escrow to
        available in full; a review decision converts escrow to spent
        one-for-one; neither operation leaks cents."

        Design: Difficulty/compensating_invariant/cert_budget_submit_decide_withdraw_conservation
        """
        ctx = self._setup_rejected_round1()
        submit_package(ctx["package"]["id"])
        title = get_title(ctx["title"]["id"])
        assert (title["cert_budget_available_cents"],
                title["cert_budget_escrow_cents"],
                title["cert_budget_spent_cents"]) == (840000, 120000, 40000)
        assert_budget_invariant(title)
        review_package(ctx["package"]["id"])
        decide_package(ctx["package"]["id"], "REJECTED")
        title = get_title(ctx["title"]["id"])
        assert (title["cert_budget_available_cents"],
                title["cert_budget_escrow_cents"],
                title["cert_budget_spent_cents"]) == (840000, 0, 160000)
        assert_budget_invariant(title)

    def test_resubmit_and_withdraw_checkpoints_conserve_budget(self, api):
        """PRD §2.7: "A withdrawal refunds escrow to available in full; a
        review decision converts escrow to spent one-for-one; neither
        operation leaks cents."
        PRD §3.5: "The base is multiplied by a round factor — 1.00 on round
        one, 0.50 on round two, and 0.25 on round three and every later round"

        Design: Difficulty/compensating_invariant/cert_budget_submit_decide_withdraw_conservation
        """
        ctx = self._setup_rejected_round1()
        submit_package(ctx["package"]["id"])
        review_package(ctx["package"]["id"])
        decide_package(ctx["package"]["id"], "REJECTED")
        # Round 2 on the still-CANDIDATE build; Monday submit, not expedited.
        pkg2 = create_submission_package(
            ctx["title"]["id"], "PS5", ctx["build"]["id"], ctx["plan"]["id"]
        )
        verify_checklist_pass_sequence(
            get_checklist_id_for_package(pkg2["id"]), "PS5"
        )
        pkg2 = submit_package(pkg2["id"])
        assert pkg2["fee_cents"] == 60000  # 120000 x 0.50
        title = get_title(ctx["title"]["id"])
        assert (title["cert_budget_available_cents"],
                title["cert_budget_escrow_cents"],
                title["cert_budget_spent_cents"]) == (780000, 60000, 160000)
        assert_budget_invariant(title)
        validate_success(
            api_client.transition_submission_package(
                pkg2["id"], {"to_status": "WITHDRAWN"}, CL_HEADERS
            )
        )
        title = get_title(ctx["title"]["id"])
        # 100% escrow refund: back to the post-rejection partition.
        assert (title["cert_budget_available_cents"],
                title["cert_budget_escrow_cents"],
                title["cert_budget_spent_cents"]) == (840000, 0, 160000)
        assert_budget_invariant(title)


class TestDefaultClock:
    def test_default_clock_is_saturday_and_weekend_fee_applies(self, api):
        """PRD §2.4: "Before any call is made, the clock reads exactly
        2026-08-01T00:00:00Z — a fixed startup default; it never follows
        wall-clock time."
        PRD §3.5: "then by a weekend factor of 1.20 when the submit instant
        falls on a Saturday or Sunday in UTC (1.00 otherwise)."
        PRD §3.5: "On a successful submit, `fee_cents` is recorded (it is null
        until then), `submitted_at` — likewise null until this moment — is
        stamped from the logical clock"

        Design: Corner/cross_cutting_layers/default_clock_saturday_applies_weekend_fee
        """
        # No clock-set call anywhere: the fixed startup default (a Saturday)
        # is in force for the whole chain and the submit.
        ctx = setup_submittable_package(title_code="LYR-CLK",
                                        cert_budget_total_cents=1_000_000)
        package = submit_package(ctx["package"]["id"])
        # Stamped from the logical clock: the instant is pinned by §2.4; the
        # string representation is not (§2.5's millisecond format is scoped
        # to id/created_at/updated_at/version).
        assert_clock_instant(package["submitted_at"], "2026-08-01T00:00:00Z")
        assert package["fee_cents"] == 144000  # 120000 x 1.20
