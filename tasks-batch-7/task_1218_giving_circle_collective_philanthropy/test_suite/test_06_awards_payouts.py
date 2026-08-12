"""Award allocation, payout tranches under segregation of duties, the host
administration fee, tally tie-breaks, and the award's parallel lifecycle
dimensions (PRD §2.3, §2.7, §3.6, §3.7).
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    approve_and_release_payout,
    assert_award,
    get_ledger,
    get_success_data,
    make_finance_headers,
    setup_award,
    submit_and_accept_report,
    validate_error,
    validate_success,
)
from test_helpers.factories import submit_report_payload
from test_helpers.test_users import make_grantee_headers

ADMIN = TEST_USERS["admin_headers"]
FINANCE = TEST_USERS["finance_headers"]


class TestAwardAllocation:
    def test_award_allocation_nested_minmax_share(self, api):
        """PRD §3.7: "the winner's share is its `winner_points` divided by the
        `total_points_cast`, treated as an exact ratio; the raw amount is that
        share of `grant_budget_final_cents`, rounded half up to whole cents;
        and the awarded amount is the raw figure raised to a floor of 50000
        cents (five hundred dollars) when it falls short, capped at the final
        budget itself if the floor would exceed it."

        Final budget 190000 (received 200000 less fee 10000), winner share
        130/200: min(190000, max(50000, round_half_up(0.65 * 190000))) = 123500.

        Design: Difficulty/combinatorial_formula/award_allocation_nested_minmax_share
        """
        ctx = setup_award(
            "Circle CF1",
            num_members=2,
            funding=((0, 100000, True), (1, 100000, True)),
            num_finalists=2,
            ballot_points=[(0, [60, 40]), (1, [70, 30])],
        )
        award = ctx["award"]
        assert_award(award)
        assert award["winner_points"] == 130, (
            f"winner total is 60 + 70 = 130, got {award['winner_points']}"
        )
        assert award["amount_cents"] == 123500, (
            f"min(190000, max(50000, round(0.65*190000))) must be 123500, got {award['amount_cents']}"
        )

    def test_award_winner_and_loser_statuses(self, api):
        """PRD §3.7: "When the gates pass, the advance runs the tally and
        commits a chain of side effects in one motion. The winning finalist's
        nomination moves `FINALIST` → `AWARDED`; every other finalist moves
        `FINALIST` → `NOT_SELECTED`."

        Design: Difficulty/combinatorial_formula/award_allocation_nested_minmax_share
        """
        ctx = setup_award(
            "Circle CF1B",
            num_members=2,
            funding=((0, 100000, True), (1, 100000, True)),
            num_finalists=2,
            ballot_points=[(0, [60, 40]), (1, [70, 30])],
        )
        winner = get_success_data(api.get_nomination(ctx["nominations"][0]["id"], ADMIN))
        loser = get_success_data(api.get_nomination(ctx["nominations"][1]["id"], ADMIN))
        assert winner["status"] == "AWARDED"
        assert loser["status"] == "NOT_SELECTED"
        assert ctx["award"]["nomination_id"] == ctx["nominations"][0]["id"]


class TestTrancheSplit:
    def test_tranche_split_floor_then_remainder(self, api):
        """PRD §3.7: "Two payouts are created in `SCHEDULED` with
        `requested_by_user_id` recording the acting `CircleAdmin`'s `X-User-ID`:
        tranche 1 (the upfront tranche, `tranche` value 1) is the largest whole
        number of cents not exceeding seventy percent of the award amount, and
        tranche 2 is the remainder, so the two always sum exactly to
        `amount_cents` — the tranches are never rounded independently, and the
        second tranche absorbs any cent the floor leaves behind."

        Award 99751 (received 105001, fee round_half_up(5250.05) = 5250):
        floor(99751 * 70 / 100) = 69825; remainder 99751 - 69825 = 29926.

        Design: Difficulty/combinatorial_formula/tranche_split_floor_then_remainder
        """
        ctx = setup_award("Circle CF2", num_members=1, funding=((0, 105001, True),))
        award = ctx["award"]
        assert award["amount_cents"] == 99751
        t1, t2 = ctx["payouts"][0], ctx["payouts"][1]
        assert t1["tranche"] == 1 and t2["tranche"] == 2
        assert t1["amount_cents"] == 69825, (
            f"tranche 1 is floored: floor(99751*0.70) = 69825, got {t1['amount_cents']}"
        )
        assert t2["amount_cents"] == 29926, (
            f"tranche 2 is the exact remainder 29926, got {t2['amount_cents']}"
        )

    def test_tranches_sum_exactly_to_award_in_tranche_order(self, api):
        """PRD §3.7: "tranche 1 (the upfront tranche, `tranche` value 1) is the
        largest whole number of cents not exceeding seventy percent of the
        award amount, and tranche 2 is the remainder, so the two always sum
        exactly to `amount_cents` — the tranches are never rounded
        independently, and the second tranche absorbs any cent the floor leaves
        behind."
        PRD §2.3: "Two collections override this default: payouts list in
        `tranche` ascending order, and grantee reports list in `due_at`
        ascending order (which places the `INTERIM` report before the `FINAL`
        report of the same award)."

        Design: Difficulty/combinatorial_formula/tranche_split_floor_then_remainder
        """
        ctx = setup_award("Circle CF2B", num_members=1, funding=((0, 105001, True),))
        payouts = ctx["payouts"]
        assert [p["tranche"] for p in payouts] == [1, 2], (
            "payouts list in tranche ascending order"
        )
        total = payouts[0]["amount_cents"] + payouts[1]["amount_cents"]
        assert total == ctx["award"]["amount_cents"] == 99751
        # Independence-proof: round_half_up(99751 * 0.30) = 29925 != 29926.
        assert payouts[1]["amount_cents"] == 29926 != 29925


class TestAdminFeePrecision:
    def test_admin_fee_round_half_up_applied(self, api):
        """PRD §3.7: "The same advance settles the host organization:
        `admin_fee_transferred_cents` is set to the cycle's
        `received_total_cents` multiplied by its snapshotted
        `admin_fee_percent`, divided by one hundred, and rounded half up to
        whole cents, and the pooled balance is recomputed with that fee moved
        out."
        PRD §2.7: "Round-half-up appears in exactly the places that name it:
        the administration fee in both budget variants, the single
        administration-fee transfer at the award lock, the weighted
        `vetting_score` (rounded half up to a whole number), and the raw award
        amount (rounded half up to whole cents before clamping)."

        Received 100050 at 5 percent: 5002.5 rounds half up to 5003, never
        5002; final budget 100050 - 5003 - 0 = 95047.

        Design: Corner/calculations/admin_fee_round_half_up_applied
        """
        ctx = setup_award("Circle CA1", num_members=1, funding=((0, 100050, True),))
        ledger = get_ledger(ctx["cycle"]["id"])
        assert ledger["admin_fee_transferred_cents"] == 5003, (
            f"round_half_up(5002.5) must be 5003, got {ledger['admin_fee_transferred_cents']}"
        )
        assert ledger["grant_budget_final_cents"] == 95047
        assert ctx["award"]["amount_cents"] == 95047


class TestTallyTiebreak:
    def test_voting_tally_tiebreak_first_choice_then_created_at(self, api):
        """PRD §3.6: "The winner is the finalist with the highest
        `total_points`; ties break toward the higher `first_choice_count`, and
        further ties toward the finalist whose nomination has the earliest
        `created_at`."

        Totals tie 100-100; each finalist holds the strict maximum on exactly
        one ballot (first choice ties 1-1); the earlier-created nomination wins.

        Design: Corner/calculations/voting_tally_tiebreak_first_choice
        """
        ctx = setup_award(
            "Circle CA4",
            num_members=2,
            funding=((0, 100000, True), (1, 100000, True)),
            num_finalists=2,
            ballot_points=[(0, [60, 40]), (1, [40, 60])],
        )
        award = ctx["award"]
        assert award["nomination_id"] == ctx["nominations"][0]["id"], (
            "the earliest-created finalist wins the fully tied tally"
        )
        assert award["winner_points"] == 100
        assert award["amount_cents"] == 95000  # share 0.5 x final budget 190000
        loser = get_success_data(api.get_nomination(ctx["nominations"][1]["id"], ADMIN))
        assert loser["status"] == "NOT_SELECTED"


class TestAwardParallelDimensions:
    def test_first_release_moves_payout_status_only(self, api):
        """PRD §3.7: "A release moves the payout `APPROVED` → `RELEASED`, adds
        its `amount_cents` to the cycle's `released_total_cents`, recomputes
        the pooled balance, and recomputes the award's `payout_status` — the
        first release moves `UNPAID` → `PARTIALLY_PAID`, and when every payout
        of the award has been released the award becomes `PAID`."
        PRD §3.7: "The award begins life with `payout_status` `UNPAID` and
        `reporting_status` `AWAITING_REPORTS`."

        Design: Difficulty/non_linear_state_machine/award_parallel_payout_reporting_dims
        """
        ctx = setup_award("Circle NL2", num_members=1)
        approve_and_release_payout(ctx, ctx["payouts"][0])  # T1 66500
        award = get_success_data(api.get_award(ctx["award"]["id"], ADMIN))
        assert award["payout_status"] == "PARTIALLY_PAID"
        assert award["reporting_status"] == "AWAITING_REPORTS", (
            "reporting is untouched by the payout dimension"
        )
        ledger = get_ledger(ctx["cycle"]["id"])
        assert ledger["released_total_cents"] == 66500

    def test_reports_complete_leaves_payout_status(self, api):
        """PRD §3.8: "Accepting a `SUBMITTED` report moves it to `ACCEPTED`,
        the terminal state; if no `OVERDUE` reports remain for that nonprofit
        anywhere in the system, the nonprofit's `standing` is restored to
        `GOOD`, and when every report of the award has reached `ACCEPTED` the
        award's `reporting_status` recomputes from `AWAITING_REPORTS` to
        `REPORTS_COMPLETE`."

        Design: Difficulty/non_linear_state_machine/award_parallel_payout_reporting_dims
        """
        ctx = setup_award("Circle NL2B", num_members=1)
        approve_and_release_payout(ctx, ctx["payouts"][0])
        submit_and_accept_report(ctx, ctx["reports"][0], "interim", 30000)
        submit_and_accept_report(ctx, ctx["reports"][1], "final", 90000)
        award = get_success_data(api.get_award(ctx["award"]["id"], ADMIN))
        assert award["reporting_status"] == "REPORTS_COMPLETE"
        assert award["payout_status"] == "PARTIALLY_PAID", (
            "the payout dimension is untouched by report acceptance"
        )


class TestPayoutPipeline:
    def test_payout_failed_retry_returns_scheduled(self, api):
        """PRD §3.7: "When a transfer goes wrong, marking an `APPROVED` payout
        failed moves it to `FAILED`, and retrying a `FAILED` payout returns it
        to `SCHEDULED` with `approved_by_user_id` reset to null — the retry
        must win a fresh approval, and the segregation-of-duties check applies
        again."

        Design: Corner/state_machines/payout_failed_retry_returns_scheduled
        """
        ctx = setup_award("Circle SM7", num_members=1)
        t1 = ctx["payouts"][0]
        approved = validate_success(
            api.approve_payout(t1["id"], make_finance_headers("fin-9"))
        )
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "fin-9"
        failed = validate_success(
            api.mark_payout_failed(t1["id"], make_finance_headers("fin-9"))
        )
        assert failed["status"] == "FAILED"
        retried = validate_success(
            api.retry_payout(t1["id"], make_finance_headers("fin-9"))
        )
        assert retried["status"] == "SCHEDULED"
        assert not retried.get("approved_by_user_id"), (
            "retry resets approved_by_user_id so segregation of duties re-applies"
        )

    def test_payout_approve_by_requester_rejected(self, api):
        """PRD §3.7: "Approving a payout requires it in `SCHEDULED`
        (`ERR_INVALID_STATE`) and requires the acting `FinanceOfficer`'s
        `X-User-ID` to differ from the payout's `requested_by_user_id`
        (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403); approval moves the payout
        `SCHEDULED` → `APPROVED` and records the officer in
        `approved_by_user_id`."

        Design: Corner/rbac/payout_approve_by_requester_rejected
        """
        ctx = setup_award("Circle RB4", num_members=1)
        t1 = ctx["payouts"][0]
        assert t1["requested_by_user_id"] == "admin-1", (
            "the award advance ran as the shared administrator id"
        )
        resp = api.approve_payout(t1["id"], make_finance_headers("admin-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        after = get_success_data(api.get_payout(t1["id"], FINANCE))
        assert after["status"] == "SCHEDULED"

    def test_tranche2_release_before_interim_accepted_rejected(self, api):
        """PRD §3.7: "Release requires the payout in `APPROVED` and the cycle
        in `AWARD` or `REPORTING` (`ERR_CYCLE_PHASE`); releasing tranche 2
        additionally requires the award's `INTERIM` report to have reached
        `ACCEPTED`, failing with `ERR_INTERIM_REPORT_NOT_ACCEPTED` otherwise."

        Design: Corner/errors/tranche2_release_before_interim_accepted_rejected
        """
        ctx = setup_award("Circle ER11", num_members=1)
        t2 = ctx["payouts"][1]
        interim = ctx["reports"][0]
        # Interim merely SUBMITTED, never accepted.
        validate_success(
            api.submit_report(
                interim["id"],
                submit_report_payload("i", 1000),
                make_grantee_headers(ctx["award"]["nonprofit_id"]),
            )
        )
        validate_success(api.approve_payout(t2["id"], make_finance_headers("fin-1")))
        resp = api.release_payout(t2["id"], make_finance_headers("fin-1"))
        validate_error(resp, ApiErrorId.ERR_INTERIM_REPORT_NOT_ACCEPTED)
        after = get_success_data(api.get_payout(t2["id"], FINANCE))
        assert after["status"] == "APPROVED"
        ledger = get_ledger(ctx["cycle"]["id"])
        assert ledger["released_total_cents"] == 0
