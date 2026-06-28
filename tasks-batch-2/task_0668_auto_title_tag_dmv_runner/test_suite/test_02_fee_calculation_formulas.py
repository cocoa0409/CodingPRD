"""Fee-calculation formulas: nested taxable-base/expedite interaction, the
mandatory sum-then-round service-fee order, and the fleet-tier boundary.

Queue A (Difficulty) — rules combinatorial_formula and boundary_precision_check.
Queue B (Corner) — calculations and consistency_model sections.
"""
from test_helpers import (
    api_client, validate_success, get_success_data,
    setup_schedule_and_account, inject_ytd_count, inject_rejection_round,
    create_transaction, create_fee_schedule_payload, create_account, publish_fee_schedule,
    set_clock, create_transaction_verified_and_quoted,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ANALYST = TEST_USERS["fee_analyst_headers"]
CLERK = TEST_USERS["intake_clerk_headers"]


# ─── combinatorial_formula ────────────────────────────────────────────

def test_title_quote_taxable_base_with_tradein_and_expedite(api):
    """PRD §3.5: "When the governing schedule's trade_in_credit_allowed is true, the
    base is instead the declared price minus the trade_in_allowance_cents, floored at
    zero so it can never go negative; when trade-in credit is not allowed in that state,
    the trade-in allowance does not reduce the base."
    PRD §3.5: "If the transaction is expedited, add an expedite surcharge of 6,000 cents."

    Design: Difficulty/combinatorial_formula/title_quote_nested_minmax_with_tradein_and_expedite_mode_a
    """
    schedule, account = setup_schedule_and_account(
        account_type="RETAIL", state_code="CA",
        schedule_overrides={"use_tax_rate_bps": 625, "title_fee_cents": 2000,
                            "trade_in_credit_allowed": True})
    txn = create_transaction(
        account["id"], "TITLE", declared_price_cents=2000000,
        trade_in_allowance_cents=500000, expedite=True)

    quote = validate_success(api.quote_transaction(
        txn["id"], {"expected_transaction_version": txn["version"]}, ANALYST), 200)

    # base = max(0, 2000000-500000) = 1500000; tax = 1500000 * 625 / 10000 = 93750
    assert quote["tax_cents"] == 93750
    assert quote["state_fees_cents"] == 2000
    # service = 4500 base + 6000 expedite, no fleet discount (RETAIL)
    assert quote["service_fee_cents"] == 10500
    assert quote["total_cents"] == 106250


def test_title_quote_trade_in_floor_at_zero_with_expedite(api):
    """PRD §3.5: "the base is instead the declared price minus the trade_in_allowance_cents,
    floored at zero so it can never go negative"
    PRD §3.5: "If the transaction is expedited, add an expedite surcharge of 6,000 cents."

    Design: Difficulty/combinatorial_formula/title_quote_nested_minmax_with_tradein_and_expedite_mode_a
    """
    schedule, account = setup_schedule_and_account(
        account_type="RETAIL", state_code="CA",
        schedule_overrides={"use_tax_rate_bps": 625, "title_fee_cents": 2000,
                            "trade_in_credit_allowed": True})
    # trade-in (1500000) exceeds declared (1000000) -> base floors at 0, so tax is 0.
    txn = create_transaction(
        account["id"], "TITLE", declared_price_cents=1000000,
        trade_in_allowance_cents=1000000, expedite=True)
    quote = validate_success(api.quote_transaction(
        txn["id"], {"expected_transaction_version": txn["version"]}, ANALYST), 200)

    assert quote["tax_cents"] == 0  # max(0, 1000000-1000000) = 0
    assert quote["state_fees_cents"] == 2000
    assert quote["service_fee_cents"] == 10500  # 4500 + 6000 expedite, no discount
    assert quote["total_cents"] == 12500


def test_service_fee_sum_then_round_at_fractional_tier(api):
    """PRD §3.5: "These three components are summed first, while still undiscounted,
    into a single pre-discount service amount. The fleet volume discount (§3.6) is then
    applied to that whole sum as a single basis-point rate, and the discounted amount is
    rounded half-up to a whole cent exactly once."
    PRD §3.5: "This sum-then-round order is required: rounding each surcharge line
    separately and then summing is forbidden, because at fractional discount tiers it
    produces a different final cent."

    Design: Difficulty/combinatorial_formula/service_fee_sum_then_round_order_mode_b
    """
    schedule, fleet = setup_schedule_and_account(
        account_type="FLEET", state_code="CA",
        schedule_overrides={"use_tax_rate_bps": 625, "registration_fee_cents": 8500},
        account_overrides={"credit_terms": True, "credit_limit_cents": 100000000})
    inject_ytd_count(fleet["id"], 20)  # 1250 bps tier

    txn = create_transaction(fleet["id"], "REGISTRATION", declared_price_cents=0, expedite=True)
    txn = inject_rejection_round(txn["id"], 1)  # rework surcharge component = 2500

    quote = validate_success(api.quote_transaction(
        txn["id"], {"expected_transaction_version": txn["version"]}, ANALYST), 200)

    # pre-discount svc = 4500 + 6000 + 2500 = 13000; * (10000-1250)/10000 = 11375.0 -> 11375
    # round-each-then-sum would give 11376 (the trap).
    assert quote["service_fee_cents"] == 11375
    assert quote["state_fees_cents"] == 8500
    assert quote["total_cents"] == 19875


# ─── boundary_precision_check ─────────────────────────────────────────

def test_fleet_tier_boundary_ytd_4_no_discount(api):
    """PRD §3.6: "a count of at least 5 but below 20 earns 625 basis points (6.25%); and
    a count below 5 earns no discount. The thresholds are inclusive at their lower edge —
    a count of exactly 5 already qualifies for the first tier, while a count of 4 earns
    nothing"

    Design: Difficulty/boundary_precision_check/fleet_tier_boundary_ytd_5_inclusive_on_quote
    """
    schedule, fleet = setup_schedule_and_account(
        account_type="FLEET", state_code="CA",
        schedule_overrides={"registration_fee_cents": 8500},
        account_overrides={"credit_terms": True, "credit_limit_cents": 100000000})
    inject_ytd_count(fleet["id"], 4)
    txn = create_transaction(fleet["id"], "REGISTRATION", declared_price_cents=0)

    quote = validate_success(api.quote_transaction(
        txn["id"], {"expected_transaction_version": txn["version"]}, ANALYST), 200)
    assert quote["service_fee_cents"] == 4500  # ytd 4 -> no tier


def test_fleet_tier_boundary_ytd_5_inclusive(api):
    """PRD §3.6: "a count of at least 5 but below 20 earns 625 basis points (6.25%)"
    PRD §3.6: "The thresholds are inclusive at their lower edge — a count of exactly 5
    already qualifies for the first tier, while a count of 4 earns nothing"

    Design: Difficulty/boundary_precision_check/fleet_tier_boundary_ytd_5_inclusive_on_quote
    """
    schedule, fleet = setup_schedule_and_account(
        account_type="FLEET", state_code="CA",
        schedule_overrides={"registration_fee_cents": 8500},
        account_overrides={"credit_terms": True, "credit_limit_cents": 100000000})
    inject_ytd_count(fleet["id"], 5)
    txn = create_transaction(fleet["id"], "REGISTRATION", declared_price_cents=0)

    quote = validate_success(api.quote_transaction(
        txn["id"], {"expected_transaction_version": txn["version"]}, ANALYST), 200)
    # ytd 5 -> 625 bps tier: round(4500 * 9375/10000) = 4219
    assert quote["service_fee_cents"] == 4219


# ─── Corner: calculations ─────────────────────────────────────────────

def test_lien_quote_includes_lien_recording_fee(api):
    """PRD §3.5: "for a LIEN transaction — or for any transaction that has a lien packet
    associated with it — the schedule's lien_recording_fee_cents. Each transaction type
    contributes its single matching flat fee, with the lien recording fee added on top
    whenever a lien is in play."

    Design: Corner/calculations/lien_quote_state_fee_includes_lien_recording
    """
    schedule, account = setup_schedule_and_account(
        account_type="RETAIL", state_code="CA",
        schedule_overrides={"lien_recording_fee_cents": 1000})
    txn = create_transaction(account["id"], "LIEN", declared_price_cents=0)

    quote = validate_success(api.quote_transaction(
        txn["id"], {"expected_transaction_version": txn["version"]}, ANALYST), 200)
    assert quote["state_fees_cents"] == 1000
    assert quote["tax_cents"] == 0
    assert quote["service_fee_cents"] == 4500
    assert quote["total_cents"] == 5500


def test_tax_line_rounds_half_up(api):
    """PRD §3.5: "The tax line, tax_cents, is the base multiplied by the schedule's
    use_tax_rate_bps and divided by 10,000, with that single line rounded half-up to
    whole cents."

    Design: Corner/calculations/tax_rounds_half_up_on_fractional_cent
    """
    schedule, account = setup_schedule_and_account(
        account_type="RETAIL", state_code="CA",
        schedule_overrides={"use_tax_rate_bps": 625, "title_fee_cents": 2000})
    txn = create_transaction(account["id"], "TITLE",
                             declared_price_cents=120, trade_in_allowance_cents=0)

    quote = validate_success(api.quote_transaction(
        txn["id"], {"expected_transaction_version": txn["version"]}, ANALYST), 200)
    # 120 * 625 / 10000 = 7.5 -> round_half_up -> 8
    assert quote["tax_cents"] == 8
    assert quote["total_cents"] == 6508  # 8 + 2000 + 4500


def test_tradein_not_credited_when_schedule_disallows(api):
    """PRD §3.5: "when trade-in credit is not allowed in that state, the trade-in
    allowance does not reduce the base."

    Design: Corner/calculations/tradein_not_credited_when_schedule_disallows
    """
    set_clock()
    publish_fee_schedule(state_code="TX", use_tax_rate_bps=625, transfer_fee_cents=1500,
                         trade_in_credit_allowed=False)
    account = create_account(account_type="RETAIL", state_code="TX")
    txn = create_transaction(account["id"], "TRANSFER",
                             declared_price_cents=1000000, trade_in_allowance_cents=400000)

    quote = validate_success(api.quote_transaction(
        txn["id"], {"expected_transaction_version": txn["version"]}, ANALYST), 200)
    # Full 1000000 base taxed (trade-in not credited): 1000000 * 625 / 10000 = 62500
    assert quote["tax_cents"] == 62500
    assert quote["state_fees_cents"] == 1500
    assert quote["service_fee_cents"] == 4500
    # total = tax + state_fees + service = 62500 + 1500 + 4500 = 68500
    assert quote["total_cents"] == 68500


# ─── Corner: consistency_model ────────────────────────────────────────

def test_quote_immediately_visible_as_active_quote_id(api):
    """PRD §3.3: "Each quote computation produces a new FeeQuote whose variant is
    ESTIMATE and whose status is ACTIVE, sets any previously ACTIVE quote for that
    transaction to SUPERSEDED, and updates the transaction's active_quote_id to point
    at the new quote."

    Design: Corner/consistency_model/immediate_consistency_quote_visible_in_same_response
    """
    schedule, account = setup_schedule_and_account(account_type="RETAIL", state_code="CA")
    txn = create_transaction(account["id"], "REGISTRATION", declared_price_cents=0)
    quote = validate_success(api.quote_transaction(
        txn["id"], {"expected_transaction_version": txn["version"]}, ANALYST), 200)

    fetched = validate_success(api.get_transaction(txn["id"], ANALYST), 200)
    assert fetched["active_quote_id"] == quote["id"]
