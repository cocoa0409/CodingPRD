"""Cancellation earned-premium variants (flat / pro-rata / short-rate),
capacity and trust conservation under compensation, reinstatement window,
and run-daily expiry/withdrawal."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    bind_policy,
    collect_premium,
    create_issued_policy,
    get_policy_fresh,
    get_program_fresh,
    issue_policy,
    list_ledger,
    quote_policy,
    run_daily,
    set_clock,
    setup_active_program,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
UW = TEST_USERS["mga_underwriter_headers"]
FIN = TEST_USERS["mga_finance_headers"]

TERM_FROM = "2026-08-01T00:00:00Z"
TERM_TO = "2027-08-01T00:00:00Z"


def _issue_365k(program, name):
    """240 units @1500 + 5000 fee = 365000 gross, fully collected, ISSUED."""
    return create_issued_policy(
        program, insured_name=name, exposure_units=240,
        coverage_limit_cents=900000)


class TestEarnedPremiumVariants:
    def test_short_rate_vs_pro_rata_identical_dates(self, api):
        """PRD §3.4: "a cancellation requested by the insured
        (`cancellation_reason` of `INSURED_REQUEST`) that is not flat earns the
        pro-rata figure grossed up by a factor of 1.10 and rounded half-up to
        whole cents, a ten-percent penalty that leaves a smaller refund for
        identical dates; and every other basis — expiry, the earned basis of a
        loss evaluation, and cancellations for `CARRIER_REQUEST` or
        `NON_PAYMENT` — earns the plain pro-rata figure."

        Design: Difficulty/dual_variant_calc/earned_premium_pro_rata_vs_short_rate
        """
        _carrier, program, _g, _a, _f = setup_active_program(
            program_overrides={"aggregate_limit_cents": 2000000},
            allocation_overrides={"allocated_cents": 1500000},
            guideline_overrides={"max_policy_premium_cents": 500000})
        pol_a = _issue_365k(program, "A Co")   # will cancel INSURED_REQUEST
        pol_b = _issue_365k(program, "B Co")   # will cancel CARRIER_REQUEST

        set_clock("2026-11-09T00:00:00Z")  # 100 of 365 days elapsed
        validate_success(api.cancel_policy(
            pol_a["id"], {"cancellation_date": "2026-11-09T00:00:00Z",
                          "reason": "INSURED_REQUEST"}, UW))
        validate_success(api.cancel_policy(
            pol_b["id"], {"cancellation_date": "2026-11-09T00:00:00Z",
                          "reason": "CARRIER_REQUEST"}, UW))
        run_daily()

        pol_a = get_policy_fresh(pol_a["id"])
        pol_b = get_policy_fresh(pol_b["id"])
        assert pol_a["status"] == "CANCELLED"
        assert pol_b["status"] == "CANCELLED"
        # pro-rata: 365000*100/365 = 100000; short-rate: 110000.
        assert pol_a["earned_premium_cents"] == 110000
        assert pol_b["earned_premium_cents"] == 100000

        entries = list_ledger(program["id"])
        refunds = {e["policy_id"]: e for e in entries if e["entry_type"] == "REFUND"}
        # refund = collected - earned - 2500 fee.
        assert refunds[pol_a["id"]]["amount_cents"] == -(365000 - 110000 - 2500)
        assert refunds[pol_b["id"]]["amount_cents"] == -(365000 - 100000 - 2500)
        prog = get_program_fresh(program["id"])
        assert prog["trust_balance_cents"] == 730000 - 252500 - 262500

    def test_identical_dates_reason_alone_moves_refund(self, api):
        """PRD §3.4: "a ten-percent penalty that leaves a smaller refund for
        identical dates" — on the same policy shape and dates, the INSURED_REQUEST
        refund is exactly 10000 smaller than the CARRIER_REQUEST refund.

        Design: Difficulty/dual_variant_calc/earned_premium_pro_rata_vs_short_rate
        """
        _carrier, program, _g, _a, _f = setup_active_program(
            program_overrides={"aggregate_limit_cents": 2000000},
            allocation_overrides={"allocated_cents": 1500000},
            guideline_overrides={"max_policy_premium_cents": 500000})
        pol_a = _issue_365k(program, "Insured Cancel")
        pol_b = _issue_365k(program, "Carrier Cancel")
        set_clock("2026-11-09T00:00:00Z")
        for pol, reason in ((pol_a, "INSURED_REQUEST"), (pol_b, "CARRIER_REQUEST")):
            validate_success(api.cancel_policy(
                pol["id"], {"cancellation_date": "2026-11-09T00:00:00Z",
                            "reason": reason}, UW))
        run_daily()
        entries = list_ledger(program["id"])
        refunds = sorted(
            (e["amount_cents"] for e in entries if e["entry_type"] == "REFUND"))
        # -252500 (short-rate) and -262500 (pro-rata): delta exactly 10000.
        assert refunds == [-262500, -252500]


class TestCapacityConservation:
    def test_bind_then_flat_cancel_restores_capacity_counters(self, api):
        """PRD §3.4: "The released capacity, `capacity_released_cents`, is the
        gross premium minus the earned premium; the tranche's `consumed_cents`
        and the program's `consumed_aggregate_cents` each drop by that amount
        (the tranche floored at zero)." and "a flat cancel —
        `cancellation_date` on or before `effective_from` — earns zero and
        waives the fee."

        Design: Difficulty/compensating_invariant/capacity_conserved_under_bind_then_flat_cancel
        """
        _carrier, program, _g, allocation, _f = setup_active_program()
        policy = quote_policy(program, insured_name="Inv Co")
        policy = bind_policy(policy)
        prog = get_program_fresh(program["id"])
        tranche = validate_success(api.get_allocation(allocation["id"], UW))
        assert prog["consumed_aggregate_cents"] == 155000
        assert tranche["consumed_cents"] == 155000

        validate_success(api.cancel_policy(
            policy["id"], {"cancellation_date": TERM_FROM,
                           "reason": "CARRIER_REQUEST"}, UW))
        run_daily()

        policy = get_policy_fresh(policy["id"])
        assert policy["status"] == "CANCELLED"
        assert policy["earned_premium_cents"] == 0
        assert policy["capacity_released_cents"] == 155000
        prog = get_program_fresh(program["id"])
        tranche = validate_success(api.get_allocation(allocation["id"], UW))
        assert prog["consumed_aggregate_cents"] == 0
        assert tranche["consumed_cents"] == 0
        assert tranche["status"] == "ACTIVE"

    def test_exhausted_tranche_flips_back_to_active_on_release(self, api):
        """PRD §3.4: "the tranche's `consumed_cents` and the program's
        `consumed_aggregate_cents` each drop by that amount (the tranche
        floored at zero), and an `EXHAUSTED` tranche whose consumption falls
        below its allocation flips back to `ACTIVE`."

        Design: Difficulty/compensating_invariant/capacity_conserved_under_bind_then_flat_cancel
        """
        _carrier, program, _g, allocation, _f = setup_active_program(
            program_overrides={"aggregate_limit_cents": 500000},
            allocation_overrides={"allocated_cents": 155000})
        policy = quote_policy(program, insured_name="Flip Co")
        policy = bind_policy(policy)
        tranche = validate_success(api.get_allocation(allocation["id"], UW))
        assert tranche["status"] == "EXHAUSTED"

        validate_success(api.cancel_policy(
            policy["id"], {"cancellation_date": TERM_FROM,
                           "reason": "CARRIER_REQUEST"}, UW))
        run_daily()
        tranche = validate_success(api.get_allocation(allocation["id"], UW))
        assert tranche["status"] == "ACTIVE"
        assert tranche["consumed_cents"] == 0

    def test_collect_then_flat_cancel_refund_restores_trust(self, api):
        """PRD §2.8: "Each program's trust position, `trust_balance_cents`, is
        exactly the sum of `amount_cents` over all of its TrustLedgerEntry
        rows — no other field may diverge from that sum." PRD §3.4: "A
        positive refund posts a `REFUND` ledger entry for its negative amount
        against the policy" — and on a flat cancel "the fee is waived
        entirely", so the refund equals the full collection.

        Design: Difficulty/compensating_invariant/trust_balance_conserved_under_collect_then_refund
        """
        _carrier, program, _g, _a, _f = setup_active_program()
        policy = quote_policy(program, insured_name="Trust Co")
        policy = bind_policy(policy)
        entry1 = collect_premium(policy, 155000)
        assert entry1["running_balance_cents"] == 155000

        validate_success(api.cancel_policy(
            policy["id"], {"cancellation_date": TERM_FROM,
                           "reason": "CARRIER_REQUEST"}, UW))
        run_daily()

        entries = list_ledger(program["id"])
        assert len(entries) == 2
        refund = entries[-1]
        assert refund["entry_type"] == "REFUND"
        assert refund["amount_cents"] == -155000
        assert refund["running_balance_cents"] == 0
        prog = get_program_fresh(program["id"])
        assert prog["trust_balance_cents"] == 0

    def test_ledger_entry_signs_are_pinned(self, api):
        """PRD §2.8: "Four entry types exist, with pinned signs: a
        `COLLECTION` is positive (premium money in, with the contributing
        `policy_id` set); a `REFUND` is negative (money returned to an
        insured, with `policy_id` set)" and "Every entry also stores
        `running_balance_cents` — the program's trust balance immediately
        after that entry posts."

        Design: Difficulty/compensating_invariant/trust_balance_conserved_under_collect_then_refund
        """
        _carrier, program, _g, _a, _f = setup_active_program()
        policy = quote_policy(program, insured_name="Sign Co")
        policy = bind_policy(policy)
        collect_premium(policy, 155000)
        validate_success(api.cancel_policy(
            policy["id"], {"cancellation_date": TERM_FROM,
                           "reason": "CARRIER_REQUEST"}, UW))
        run_daily()

        entries = list_ledger(program["id"])
        assert entries[0]["entry_type"] == "COLLECTION"
        assert entries[0]["amount_cents"] > 0
        assert entries[0]["running_balance_cents"] == 155000
        assert entries[1]["entry_type"] == "REFUND"
        assert entries[1]["amount_cents"] < 0
        assert entries[1]["running_balance_cents"] == 0
        # The trust position is exactly the entry sum, with zero drift.
        total = sum(e["amount_cents"] for e in entries)
        assert get_program_fresh(program["id"])["trust_balance_cents"] == total == 0


class TestReinstatementWindow:
    def test_reinstate_after_thirty_days_rejected(self, api):
        """PRD §3.4: "A `CANCELLED` policy returns to its `pre_cancel_status`
        ... when ... no more than thirty days have passed since `cancelled_at`
        (`ERR_REINSTATE_WINDOW_CLOSED`)."

        Design: Corner/validations/reinstate_after_30_day_window_rejected
        """
        _carrier, program, _g, _a, _f = setup_active_program()
        policy = quote_policy(program, insured_name="Rein Co")
        policy = bind_policy(policy)
        validate_success(api.cancel_policy(
            policy["id"], {"cancellation_date": "2026-08-05T00:00:00Z",
                           "reason": "CARRIER_REQUEST"}, UW))
        set_clock("2026-08-05T00:00:00Z")
        run_daily()
        assert get_policy_fresh(policy["id"])["status"] == "CANCELLED"

        set_clock("2026-09-05T00:00:00Z")  # 31 days after cancelled_at
        resp = api.reinstate_policy(policy["id"], UW)
        validate_error(resp, ApiErrorId.ERR_REINSTATE_WINDOW_CLOSED)
        assert get_policy_fresh(policy["id"])["status"] == "CANCELLED"


class TestRunDailyExpiry:
    def test_run_daily_expires_issued_policy_and_lapses_quote(self, api):
        """PRD §2.5: "One invocation: completes every policy cancellation whose
        `cancellation_date` has been reached ...; expires every policy in
        `BOUND` or `ISSUED` whose `effective_to` has passed (moving it to
        `EXPIRED`); withdraws every quote in `QUOTED` whose `quote_valid_until`
        has lapsed (moving it to `WITHDRAWN`) ..." PRD §3.4: "a `BOUND` or
        `ISSUED` policy whose `effective_to` has passed becomes `EXPIRED`, with
        `earned_premium_cents` set to the full gross premium — the whole term
        is earned."

        Design: Corner/state_machines/policy_expiry_via_run_daily
        """
        _carrier, program, _g, _a, _f = setup_active_program()
        issued = create_issued_policy(program, insured_name="Expire Co")
        quoted = quote_policy(program, insured_name="Lapse Co", exposure_units=10,
                              coverage_limit_cents=100000)

        set_clock("2027-08-02T00:00:00Z")
        result = run_daily()
        assert issued["id"] in result["expired_policy_ids"]
        assert quoted["id"] in result["withdrawn_quote_ids"]

        issued = get_policy_fresh(issued["id"])
        assert issued["status"] == "EXPIRED"
        assert issued["earned_premium_cents"] == 155000, "full term earned at expiry"
        quoted = get_policy_fresh(quoted["id"])
        assert quoted["status"] == "WITHDRAWN"
