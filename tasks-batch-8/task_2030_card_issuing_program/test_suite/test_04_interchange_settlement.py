"""Interchange qualification tiers, rate application, commercial uplift, and
settlement partial-release semantics."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_settlement,
    create_active_card,
    create_approved_auth,
    create_open_account,
    create_program_with_bin_and_publish,
    get_success_data,
    set_clock,
    setup_active_card_scenario,
    validate_error,
    validate_success,
)

PM = TEST_USERS["program_manager_headers"]
FC = TEST_USERS["finance_controller_headers"]
PA = TEST_USERS["platform_admin_headers"]


class TestInterchangeQualification:
    def test_interchange_qualified_visa_consumer_debit(self, api):
        """PRD §3.6: "`VISA` pays 145 at `QUALIFIED`, 185 at `MID_QUALIFIED`,
        and 230 at `NON_QUALIFIED`" and "when the gap is at most 86,400 seconds
        (24 hours, inclusive) and the card is EMV capable, the tier is
        `QUALIFIED`" and "10 cents for `VISA`, 11 for `MASTERCARD`, and 5 each
        for `STAR` and `PULSE`".

        floor(10000*145/10000) + 10 = 155.

        Design: Corner/calculations/interchange_qualified_visa_consumer_debit
        """
        sc = setup_active_card_scenario(
            "P-IQ1",
            product_class="DEBIT_CONSUMER",
            network="VISA",
            program_daily_cap_cents=10_000_000,
            account_daily_cap_cents=100_000,
            fund_cents=100_000,
        )
        auth = create_approved_auth(sc["card"]["id"], amount_cents=10000, mcc="5411")
        # Settle 3600s after auth — within the 86400s inclusive QUALIFIED window.
        set_clock("2026-08-01T01:00:00Z")
        resp = api.settle_authorization(auth["id"], 10000, FC)
        settlement = validate_success(resp, expected_status=201)
        assert_settlement(settlement)
        assert settlement["qualification_tier"] == "QUALIFIED", (
            f"Expected QUALIFIED (elapsed 3600s <= 86400s, EMV-capable PHYSICAL card), "
            f"got {settlement['qualification_tier']}"
        )
        assert settlement["interchange_cents"] == 155, (
            f"floor(10000*145/10000)+10 = 155, got {settlement['interchange_cents']}"
        )

    def test_interchange_non_qualified_visa_blocked_mcc(self, api):
        """PRD §3.6: "If the settlement's `mcc` appears on the network's blocked
        list — `7995` and `6012` for `VISA`, `7995` alone for `MASTERCARD`, and
        empty lists for `STAR` and `PULSE` — the tier is `NON_QUALIFIED`." and
        "`VISA` pays 145 at `QUALIFIED`, 185 at `MID_QUALIFIED`, and 230 at
        `NON_QUALIFIED`".

        floor(10000*230/10000) + 10 = 240.

        Design: Corner/calculations/interchange_non_qualified_visa_blocked_mcc
        """
        sc = setup_active_card_scenario(
            "P-IQ2",
            product_class="DEBIT_CONSUMER",
            network="VISA",
            program_daily_cap_cents=10_000_000,
            account_daily_cap_cents=100_000,
            fund_cents=100_000,
        )
        auth = create_approved_auth(sc["card"]["id"], amount_cents=10000, mcc="7995")
        # Settle immediately (same clock instant) — blocked mcc forces NON_QUALIFIED
        # regardless of timing.
        resp = api.settle_authorization(auth["id"], 10000, FC)
        settlement = validate_success(resp, expected_status=201)
        assert_settlement(settlement)
        assert settlement["qualification_tier"] == "NON_QUALIFIED", (
            f"Blocked mcc 7995 on VISA must yield NON_QUALIFIED, got "
            f"{settlement['qualification_tier']}"
        )
        assert settlement["interchange_cents"] == 240, (
            f"floor(10000*230/10000)+10 = 240, got {settlement['interchange_cents']}"
        )

    def test_interchange_commercial_credit_uplift_applied(self, api):
        """PRD §3.6: "When the program's `product_class` is `COMMERCIAL_CREDIT`
        or `CORPORATE_FLEET`, a commercial uplift of 65 basis points is added to
        the chosen rate before any multiplication."

        floor(10000*(145+65)/10000) + 10 = 220.

        Design: Corner/calculations/interchange_commercial_credit_uplift_applied
        """
        sc = setup_active_card_scenario(
            "P-IQ3",
            product_class="COMMERCIAL_CREDIT",
            network="VISA",
            program_daily_cap_cents=10_000_000,
            account_daily_cap_cents=100_000,
            account_class="BUSINESS",
            credit_limit_cents=100_000,
            fund_cents=100_000,
        )
        auth = create_approved_auth(sc["card"]["id"], amount_cents=10000, mcc="5411")
        set_clock("2026-08-01T01:00:00Z")  # within 24h → QUALIFIED
        resp = api.settle_authorization(auth["id"], 10000, FC)
        settlement = validate_success(resp, expected_status=201)
        assert settlement["qualification_tier"] == "QUALIFIED"
        assert settlement["interchange_cents"] == 220, (
            f"floor(10000*210/10000)+10 = 220 (145bp + 65bp uplift), got "
            f"{settlement['interchange_cents']}"
        )


class TestSettlementPartialRelease:
    def test_settlement_partial_release_returns_difference(self, api):
        """PRD §3.6: "When the settled amount falls short of the authorized
        amount, the remainder is released back to the account's
        `available_balance_cents`."

        Design: Corner/calculations/settlement_partial_release_returns_difference
        """
        sc = setup_active_card_scenario(
            "P-PS",
            product_class="DEBIT_CONSUMER",
            network="VISA",
            program_daily_cap_cents=10_000_000,
            account_daily_cap_cents=100_000,
            fund_cents=100_000,
        )
        acct_id = sc["account"]["id"]
        auth = create_approved_auth(sc["card"]["id"], amount_cents=10000, mcc="5411")
        settle = api.settle_authorization(auth["id"], 6000, FC)
        validate_success(settle, expected_status=201)
        acct = get_success_data(api.get_account(acct_id, PM))
        # 100000 - 10000 (auth) + 4000 (released remainder = 10000-6000) = 94000
        assert acct["available_balance_cents"] == 94000, (
            f"Expected 94000 after partial settle (100000-10000+4000), got "
            f"{acct['available_balance_cents']}"
        )


class TestDualVariantInterchange:
    def test_interchange_provisional_vs_final_differs_when_tier_mid(self, api):
        """PRD §3.6: "A provisional variant of the same figure is computed
        advisory-only at authorization time, optimistically assuming the
        authorization's merchant category will settle at `QUALIFIED` and within
        a day; it is never booked, and the final settlement figure differs from
        it whenever the real tier is not `QUALIFIED` or the commercial uplift
        applies." and "Otherwise, if the gap between `authorized_at` and
        `settled_at` exceeds 172,800 seconds (48 hours), the tier is
        `NON_QUALIFIED`; the boundary is exclusive, so a gap of exactly 172,800
        seconds falls through to the next test." and "Every remaining case is
        `MID_QUALIFIED`."

        final = floor(10000*185/10000)+10 = 195; provisional-as-if-QUALIFIED
        would have been floor(10000*145/10000)+10 = 155.

        Design: Difficulty/dual_variant_calc/interchange_provisional_vs_final_on_settlement_domain
        """
        sc = setup_active_card_scenario(
            "P-VISA-1",
            product_class="DEBIT_CONSUMER",
            network="VISA",
            program_daily_cap_cents=10_000_000,
            account_daily_cap_cents=100_000,
            fund_cents=100_000,
        )
        # Authorize at a pinned clock instant.
        set_clock("2026-08-10T00:00:00Z")
        auth = create_approved_auth(sc["card"]["id"], amount_cents=10000, mcc="5411")
        assert auth["decision"] == "APPROVED"
        # Settle 100000s later: 86400 < 100000 <= 172800 → MID_QUALIFIED.
        set_clock("2026-08-11T03:46:40Z")
        resp = api.settle_authorization(auth["id"], 10000, FC)
        settlement = validate_success(resp, expected_status=201)
        assert settlement["qualification_tier"] == "MID_QUALIFIED", (
            f"Elapsed 100000s with EMV-capable card must be MID_QUALIFIED, got "
            f"{settlement['qualification_tier']}"
        )
        # Final differs from the provisional-as-if-QUALIFIED figure (155).
        assert settlement["interchange_cents"] == 195, (
            f"floor(10000*185/10000)+10 = 195 (final), differs from provisional 155; "
            f"got {settlement['interchange_cents']}"
        )

    def test_interchange_final_equals_qualified_formula_when_tier_qualified(self, api):
        """PRD §3.6: "when the gap is at most 86,400 seconds (24 hours,
        inclusive) and the card is EMV capable, the tier is `QUALIFIED`" and
        "`VISA` pays 145 at `QUALIFIED`" plus the per-item "10 cents for
        `VISA`, 11 for `MASTERCARD`, and 5 each for `STAR` and `PULSE`".

        floor(10000*145/10000)+10 = 155 — the same figure the provisional
        variant assumes, confirming the two variants coincide exactly when the
        real tier is QUALIFIED and no uplift applies.

        Design: Difficulty/dual_variant_calc/interchange_provisional_vs_final_on_settlement_domain
        """
        sc = setup_active_card_scenario(
            "P-VISA-1B",
            product_class="DEBIT_CONSUMER",
            network="VISA",
            program_daily_cap_cents=10_000_000,
            account_daily_cap_cents=100_000,
            fund_cents=100_000,
        )
        auth = create_approved_auth(sc["card"]["id"], amount_cents=10000, mcc="5411")
        # Settle within 24h on an EMV-capable PHYSICAL card → QUALIFIED.
        set_clock("2026-08-01T12:00:00Z")
        resp = api.settle_authorization(auth["id"], 10000, FC)
        settlement = validate_success(resp, expected_status=201)
        assert settlement["qualification_tier"] == "QUALIFIED"
        assert settlement["interchange_cents"] == 155, (
            f"QUALIFIED final must equal the provisional-assumed figure of 155; "
            f"got {settlement['interchange_cents']}"
        )
