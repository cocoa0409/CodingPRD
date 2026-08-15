"""Funding-source lifecycle: exhaustion/revival auto-transitions, deposits,
closure guards, and the budget-partition conservation invariant."""
from test_helpers import (
    ApiErrorId,
    assert_source_balance_invariant,
    clear_payment,
    create_funding_source,
    create_household,
    create_vendor,
    create_active_policy,
    deposit,
    drive_application_to_approved,
    get_application,
    issue_payment,
    setup_approved,
    TEST_USERS,
    validate_error,
    validate_success,
)

PM1 = TEST_USERS["program_manager_headers"]


class TestSourceExhaustionCycle:
    def test_reservation_to_exact_zero_exhausts_source(self, api):
        """PRD §3.1: "A source whose `available_cents` reaches exactly zero after
        any reservation or budget mutation automatically transitions `ACTIVE →
        EXHAUSTED`, and a source whose `available_cents` rises above zero again —
        through a deposit or an allocation release — automatically returns
        `EXHAUSTED → ACTIVE`; both automatic transitions bump the source's
        `version`."

        Design: Difficulty/non_linear_state_machine/funding_source_exhaustion_cycle
        """
        ctx = setup_approved(
            requested_amount_cents=25000,
            source_overrides={
                "name": "E", "funder_name": "Funder E",
                "source_type": "GRANT_RESTRICTED", "total_budget_cents": 25000,
            },
        )
        source = validate_success(api.get_funding_source(ctx["source"]["id"], PM1), 200)
        assert source["status"] == "EXHAUSTED"
        assert source["available_cents"] == 0
        assert source["reserved_cents"] == 25000
        assert_source_balance_invariant(source)

    def test_deposit_revives_exhausted_source_to_active(self, api):
        """PRD §3.1: "A `ProgramManager` may deposit additional budget into any
        non-`CLOSED` source by supplying `amount_cents`; the deposit increases
        `total_budget_cents`, recomputes `available_cents`, revives an
        `EXHAUSTED` source to `ACTIVE` when availability rises above zero, and
        bumps `version`."

        Design: Difficulty/non_linear_state_machine/funding_source_exhaustion_cycle
        """
        ctx = setup_approved(
            requested_amount_cents=25000,
            source_overrides={
                "name": "E", "funder_name": "Funder E",
                "source_type": "GRANT_RESTRICTED", "total_budget_cents": 25000,
            },
        )
        source_id = ctx["source"]["id"]
        assert validate_success(api.get_funding_source(source_id, PM1), 200)["status"] == "EXHAUSTED"
        revived = deposit(source_id, 10000)
        assert revived["status"] == "ACTIVE"
        assert revived["total_budget_cents"] == 35000
        assert revived["available_cents"] == 10000
        assert revived["reserved_cents"] == 25000
        assert_source_balance_invariant(revived)


class TestSourceCloseAndDepositGuards:
    def test_deposit_and_close_on_closed_source_rejected(self, api):
        """PRD §3.1: "Deposits into a `CLOSED` source fail with
        `ERR_INVALID_SOURCE_STATE`."
        PRD §3.1: "Closing a source — permitted from `ACTIVE` or `EXHAUSTED`,
        otherwise `ERR_INVALID_SOURCE_STATE` — requires `reserved_cents` to be
        exactly zero, failing with `ERR_RESERVED_FUNDS_OUTSTANDING` otherwise; an
        `EXHAUSTED` source therefore closes only when its entire budget has been
        committed, since closure demands zero reserved funds on top of zero
        availability."

        Design: Corner/validations/deposit_and_close_on_closed_source_rejected
        """
        ctx = setup_approved(requested_amount_cents=10000)
        # A live reservation blocks closure.
        resp1 = api.close_funding_source(ctx["source"]["id"], PM1)
        validate_error(resp1, ApiErrorId.ERR_RESERVED_FUNDS_OUTSTANDING)
        # An empty source closes cleanly; after that it is terminal.
        empty = create_funding_source(name="MT", funder_name="Funder MT",
                                      total_budget_cents=5000)
        closed = validate_success(api.close_funding_source(empty["id"], PM1), 200)
        assert closed["status"] == "CLOSED"
        resp2 = api.deposit_funding_source(empty["id"], {"amount_cents": 1000}, PM1)
        validate_error(resp2, ApiErrorId.ERR_INVALID_SOURCE_STATE)
        resp3 = api.close_funding_source(empty["id"], PM1)
        validate_error(resp3, ApiErrorId.ERR_INVALID_SOURCE_STATE)


class TestSourceBudgetPartitionConservation:
    def _two_award_setup(self):
        create_active_policy(
            name="P1", max_annual_benefit_cents=100000, rent_cap_cents=60000,
            utility_cap_cents=40000, income_limit_cents=5000000,
        )
        vendor = create_vendor("LANDLORD")
        household1 = create_household(head_of_household_name="Yara Bell")
        household2 = create_household(head_of_household_name="Zeb Cole")
        source = create_funding_source(
            name="P", funder_name="Funder P", total_budget_cents=80000
        )
        first = drive_application_to_approved(
            household1["id"], vendor["id"], requested_amount_cents=50000,
            service_month="2026-08",
        )
        second = drive_application_to_approved(
            household2["id"], vendor["id"], requested_amount_cents=30000,
            service_month="2026-08",
        )
        return source, vendor, first, second

    def test_partition_conserved_through_approve_and_void(self, api):
        """PRD §3.1: "These three are recomputed after every mutation that
        touches the source — approval, payment clearing, award adjustment, award
        voiding, or deposit — and the invariant that committed plus reserved plus
        available always equals `total_budget_cents` holds at all times."
        PRD §3.6: "A successful void flips every `RESERVED` allocation of the
        award to `RELEASED`, reduces each affected source's `reserved_cents` by
        that allocation's `allocated_cents` minus its `consumed_cents`, revives
        any `EXHAUSTED` source whose availability rises above zero back to
        `ACTIVE`, moves the application `APPROVED → PENDING_DECISION` with its
        `active_award_id` cleared to empty, and increments the award's `version`."

        Design: Difficulty/compensating_invariant/source_budget_partition_conserved
        """
        source, _, first, _ = self._two_award_setup()
        after_approvals = validate_success(
            api.get_funding_source(source["id"], PM1), 200
        )
        assert after_approvals["reserved_cents"] == 80000
        assert after_approvals["committed_cents"] == 0
        assert after_approvals["available_cents"] == 0
        assert_source_balance_invariant(after_approvals)
        validate_success(api.void_award(first["award"]["id"], PM1), 200)
        after_void = validate_success(api.get_funding_source(source["id"], PM1), 200)
        assert after_void["reserved_cents"] == 30000
        assert after_void["committed_cents"] == 0
        assert after_void["available_cents"] == 50000
        assert_source_balance_invariant(after_void)
        assert (
            get_application(first["application"]["id"])["status"] == "PENDING_DECISION"
        )

    def test_partition_conserved_through_payment_clear(self, api):
        """PRD §3.1: "These three are recomputed after every mutation that
        touches the source — approval, payment clearing, award adjustment, award
        voiding, or deposit — and the invariant that committed plus reserved plus
        available always equals `total_budget_cents` holds at all times."
        PRD §3.7: "the source's `reserved_cents` decreases and its
        `committed_cents` increases by the amount"

        Design: Difficulty/compensating_invariant/source_budget_partition_conserved
        """
        source, vendor, first, second = self._two_award_setup()
        validate_success(api.void_award(first["award"]["id"], PM1), 200)
        fully_compensated = validate_success(api.get_funding_source(source["id"], PM1), 200)
        assert fully_compensated["reserved_cents"] == 30000
        assert fully_compensated["available_cents"] == 50000
        assert_source_balance_invariant(fully_compensated)
        payment = issue_payment(
            second["award"]["id"], vendor["id"], source["id"], 30000
        )
        clear_payment(payment["id"])
        after_clear = validate_success(api.get_funding_source(source["id"], PM1), 200)
        assert after_clear["reserved_cents"] == 0
        assert after_clear["committed_cents"] == 30000
        assert after_clear["available_cents"] == 50000
        assert after_clear["total_budget_cents"] == 80000
        assert_source_balance_invariant(after_clear)
