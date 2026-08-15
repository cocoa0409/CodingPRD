"""Termination expense allocation: the two method variants, pinned rounding
order with remainder assignment, and the fiscal guards."""
from test_helpers import (
    ApiErrorId,
    assert_expense_allocation,
    assert_fund_conservation,
    create_accepted_payout,
    create_cleared_rollover,
    get_case,
    get_participant,
    setup_case_in_distribution,
    setup_case_through_effectuation,
    validate_error,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]


def _allocate(api, case_id, method, total_expense_cents, description="Final recordkeeper invoice"):
    return api.create_expense_allocation(
        {
            "termination_case_id": case_id,
            "method": method,
            "total_expense_cents": total_expense_cents,
            "description": description,
        },
        ADMIN,
    )


class TestExpenseMethodVariants:
    def test_expense_prorata_shares(self, api):
        """PRD §3.7: "Under `PRO_RATA_BY_BALANCE`, each share is the total
        expense multiplied by the participant's `vested_balance_cents`, divided
        by the sum of `vested_balance_cents` over the eligible set, rounded half
        up to whole cents."
        PRD §3.7: "On the case ledger, `expense_paid_cents` increases by
        `total_expense_cents` and `remaining_undistributed_cents` decreases by
        it."

        Design: Difficulty/dual_variant_calc/expense_allocation_prorata_vs_percapita
        """
        case, plist = setup_case_through_effectuation(
            participants=[(600000, 100), (400000, 100)],
            plan_name="ProRata Co 401k", plan_number="010",
        )
        allocation = validate_success(
            _allocate(api, case["id"], "PRO_RATA_BY_BALANCE", 10000), 201
        )
        assert_expense_allocation(allocation)
        p1 = get_participant(plist[0]["id"])
        p2 = get_participant(plist[1]["id"])
        assert p1["termination_expense_share_cents"] == 6000
        assert p1["net_distributable_cents"] == 594000
        assert p2["termination_expense_share_cents"] == 4000
        assert p2["net_distributable_cents"] == 396000
        case = get_case(case["id"])
        assert case["expense_paid_cents"] == 10000
        assert case["remaining_undistributed_cents"] == 990000
        assert_fund_conservation(case)

    def test_expense_per_capita_shares(self, api):
        """PRD §3.7: "Under `EQUAL_PER_CAPITA`, each share is the total expense
        divided by the number of eligible participants, rounded half up —
        identical inputs thereby produce different per-participant cents than
        the pro-rata variant."

        Design: Difficulty/dual_variant_calc/expense_allocation_prorata_vs_percapita
        """
        case, plist = setup_case_through_effectuation(
            participants=[(600000, 100), (400000, 100)],
            plan_name="PerCapita Co 401k", plan_number="011",
        )
        allocation = validate_success(
            _allocate(api, case["id"], "EQUAL_PER_CAPITA", 10000), 201
        )
        assert_expense_allocation(allocation)
        p1 = get_participant(plist[0]["id"])
        p2 = get_participant(plist[1]["id"])
        assert p1["termination_expense_share_cents"] == 5000, (
            "per-capita splits evenly regardless of balance"
        )
        assert p1["net_distributable_cents"] == 595000
        assert p2["termination_expense_share_cents"] == 5000
        assert p2["net_distributable_cents"] == 395000
        case = get_case(case["id"])
        assert case["expense_paid_cents"] == 10000
        assert case["remaining_undistributed_cents"] == 990000


class TestExpenseRoundingOrder:
    def _rounding_case(self, api):
        return setup_case_through_effectuation(
            participants=[(333333, 100), (333333, 100), (333334, 100)],
            plan_name="Rounding Co 401k", plan_number="031",
        )

    def test_expense_rounding_order_remainder(self, api):
        """PRD §3.7: "Rounding order is pinned: each participant's share is
        rounded first, and the remainder is reconciled second; the
        implementation must never sum-then-round."
        PRD §3.7: "The remainder, computed as the total expense minus the sum of
        the rounded shares (it may be positive or negative), is added to the
        share of the eligible participant with the largest
        `vested_balance_cents`, ties broken by earliest `created_at`; that
        participant is recorded as the computed
        `remainder_recipient_participant_id`."

        Design: Difficulty/combinatorial_formula/expense_allocation_rounding_order
        """
        case, plist = self._rounding_case(api)
        allocation = validate_success(
            _allocate(api, case["id"], "PRO_RATA_BY_BALANCE", 10000,
                      "Termination audit"),
            201,
        )
        # round_half_up(10000 * 333333 / 1000000) = 3333 for the first two;
        # round_half_up(10000 * 333334 / 1000000) = 3333; sum 9999 leaves a
        # 1-cent remainder that lands on the largest balance.
        assert get_participant(plist[0]["id"])["termination_expense_share_cents"] == 3333
        assert get_participant(plist[1]["id"])["termination_expense_share_cents"] == 3333
        assert get_participant(plist[2]["id"])["termination_expense_share_cents"] == 3334
        assert allocation["remainder_recipient_participant_id"] == plist[2]["id"]

    def test_expense_rounding_preserves_total(self, api):
        """PRD §3.7: "On the case ledger, `expense_paid_cents` increases by
        `total_expense_cents` and `remaining_undistributed_cents` decreases by
        it."

        Design: Difficulty/combinatorial_formula/expense_allocation_rounding_order
        """
        case, plist = self._rounding_case(api)
        allocation = validate_success(
            _allocate(api, case["id"], "PRO_RATA_BY_BALANCE", 10000,
                      "Termination audit"),
            201,
        )
        assert allocation["eligible_participant_count"] == 3
        shares = [
            get_participant(p["id"])["termination_expense_share_cents"] for p in plist
        ]
        assert sum(shares) == 10000, "pinned rounding leaves no drift"
        case = get_case(case["id"])
        assert case["expense_paid_cents"] == 10000
        assert case["remaining_undistributed_cents"] == 990000
        assert_fund_conservation(case)

    def test_expense_per_capita_tiebreak_earliest_created(self, api):
        """PRD §3.7: "The remainder, computed as the total expense minus the sum
        of the rounded shares (it may be positive or negative), is added to the
        share of the eligible participant with the largest
        `vested_balance_cents`, ties broken by earliest `created_at`; that
        participant is recorded as the computed
        `remainder_recipient_participant_id`."

        Design: Corner/calculations/expense_per_capita_tiebreak_earliest_created
        """
        case, plist = setup_case_through_effectuation(
            participants=[(100000, 100), (100000, 100), (100000, 100)],
            plan_name="Tie Co 401k", plan_number="134",
        )
        allocation = validate_success(
            _allocate(api, case["id"], "EQUAL_PER_CAPITA", 10000,
                      "Final filing fee"),
            201,
        )
        # round_half_up(10000 / 3) = 3333 each (sum 9999); the 1-cent remainder
        # ties on balance and lands on the earliest-created participant.
        assert get_participant(plist[0]["id"])["termination_expense_share_cents"] == 3334
        assert get_participant(plist[1]["id"])["termination_expense_share_cents"] == 3333
        assert get_participant(plist[2]["id"])["termination_expense_share_cents"] == 3333
        assert allocation["remainder_recipient_participant_id"] == plist[0]["id"]
        assert allocation["eligible_participant_count"] == 3


class TestExpenseGuards:
    def test_expense_exceeds_remaining_returns_402(self, api):
        """PRD §3.7: "Two fiscal guards apply last, in §2.9 order: the total
        expense may not exceed the case's `remaining_undistributed_cents`
        (otherwise `ERR_INSUFFICIENT_REMAINING_BALANCE`, HTTP 402), and no
        computed share may exceed its participant's `vested_balance_cents`
        (otherwise `ERR_EXPENSE_EXCEEDS_PARTICIPANT_BALANCE`, HTTP 422)."

        Design: Corner/validations/expense_exceeds_remaining_returns_402
        """
        case, _ = setup_case_through_effectuation(
            participants=[(100000, 100)], plan_name="Overdraw Co 401k",
            plan_number="149",
        )
        resp = _allocate(api, case["id"], "PRO_RATA_BY_BALANCE", 100001,
                         "Invoice exceeding remaining assets")
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_REMAINING_BALANCE)
        assert get_case(case["id"])["expense_paid_cents"] == 0

    def test_expense_blocked_when_payout_committed(self, api):
        """PRD §3.7: "The case must be `TERMINATION_EFFECTIVE`,
        `DISTRIBUTION_IN_PROGRESS`, or `FINAL_RECONCILIATION` (otherwise
        `ERR_CASE_INVALID_STATE`); the expense is blocked while any participant
        of the case is `ELECTION_ACCEPTED`, because payout amounts are already
        committed (otherwise `ERR_PAYOUTS_ALREADY_COMMITTED`, HTTP 409); and the
        eligible set must be non-empty (otherwise `ERR_NO_ELIGIBLE_PARTICIPANTS`,
        HTTP 409)."

        Design: Corner/validations/expense_blocked_when_payout_committed
        """
        case, plist = setup_case_in_distribution(
            participants=[(200000, 100)], plan_name="Committed Co 401k",
            plan_number="150",
        )
        create_accepted_payout(plist[0]["id"], "DIRECT_ROLLOVER_IRA")
        assert (
            get_participant(plist[0]["id"])["distribution_status"]
            == "ELECTION_ACCEPTED"
        )
        resp = _allocate(api, case["id"], "EQUAL_PER_CAPITA", 1000, "Late invoice")
        validate_error(resp, ApiErrorId.ERR_PAYOUTS_ALREADY_COMMITTED)
        assert (
            get_participant(plist[0]["id"])["termination_expense_share_cents"] == 0
        )

    def test_expense_share_exceeds_vested_balance_rejected(self, api):
        """PRD §3.7: "Two fiscal guards apply last, in §2.9 order: the total
        expense may not exceed the case's `remaining_undistributed_cents`
        (otherwise `ERR_INSUFFICIENT_REMAINING_BALANCE`, HTTP 402), and no
        computed share may exceed its participant's `vested_balance_cents`
        (otherwise `ERR_EXPENSE_EXCEEDS_PARTICIPANT_BALANCE`, HTTP 422)."

        Design: Corner/validations/expense_share_exceeds_vested_balance_returns_error
        """
        case, plist = setup_case_through_effectuation(
            participants=[(100000, 100), (40000, 100)],
            plan_name="Cap Co 401k", plan_number="151",
        )
        # Per-capita share 50000 exceeds the second participant's 40000 vested
        # balance even though the 140000 remaining total covers the expense.
        resp = _allocate(api, case["id"], "EQUAL_PER_CAPITA", 100000,
                         "Per-capita invoice exceeding the small balance")
        validate_error(resp, ApiErrorId.ERR_EXPENSE_EXCEEDS_PARTICIPANT_BALANCE)
        for participant in plist:
            assert (
                get_participant(participant["id"])["termination_expense_share_cents"]
                == 0
            ), "the rejected allocation debits no participant"

    def test_expense_empty_eligible_set_rejected(self, api):
        """PRD §3.7: "The eligible set is the case's participants whose
        `distribution_status` is `PENDING_ELECTION`, `ELECTION_SUBMITTED`, or
        `RESTORED` at execution time — forfeited and terminally resolved
        participants are never debited — and its size is reported as the
        allocation's computed `eligible_participant_count`."
        PRD §3.7: "and the eligible set must be non-empty (otherwise
        `ERR_NO_ELIGIBLE_PARTICIPANTS`, HTTP 409)."

        Design: Corner/validations/expense_empty_eligible_set_returns_error
        """
        case, plist = setup_case_in_distribution(
            participants=[(200000, 100)], plan_name="EmptySet Co 401k",
            plan_number="152",
        )
        create_cleared_rollover(plist[0]["id"])  # participant -> AUTO_ROLLED_OVER
        resp = _allocate(api, case["id"], "EQUAL_PER_CAPITA", 1000,
                         "Post-settlement invoice")
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_PARTICIPANTS)
