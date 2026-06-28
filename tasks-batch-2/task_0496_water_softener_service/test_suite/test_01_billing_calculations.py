"""Billing-domain calculations: rental proration, early-termination fees, claim
settlements, and the ledger cascades and compensations they drive.

Each test builds its own world via test_helpers fixtures and asserts literal,
PRD-derived monetary outcomes.
"""
from test_helpers import (
    validate_success,
    validate_paginated,
    get_success_data,
    TEST_USERS,
    setup_active_rental_contract,
    setup_active_system,
    setup_triaged_claim,
    setup_account_with_accepted_test,
    set_clock,
    create_system_payload,
)

BILLING = TEST_USERS["billing_clerk_headers"]
SM = TEST_USERS["service_manager_headers"]


# ===========================================================================
# Dual-variant calc: RENTAL_CYCLE flat vs PRORATION daily on the same contract
# ===========================================================================
def test_proration_full_cycle_vs_daily_diverge_on_same_contract(api):
    """PRD §3.10: "For a `RENTAL_CYCLE` invoice the amount is the flat
    `monthly_rate_cents` for a whole month, regardless of partial occupancy."
    PRD §3.10: "For a `PRORATION` invoice the amount is a daily rate times the
    billable days, where the daily rate is the `monthly_rate_cents` divided by 30
    days per billing month, rounded half up to whole cents first, and only then
    multiplied by the billable-day count — the rounding happens before the
    multiplication, never after."

    Design: Difficulty/dual_variant_calc/proration_full_cycle_vs_daily_on_rental_contract
    """
    ctx = setup_active_rental_contract(monthly_rate_cents=4500, term_months=12,
                                       start_date="2026-06-13T00:00:00Z")
    set_clock("2026-07-05T00:00:00Z", BILLING)

    full = validate_success(api.create_invoice({
        "account_id": ctx["account"]["id"], "contract_id": ctx["contract"]["id"],
        "invoice_kind": "RENTAL_CYCLE",
        "period_start": "2026-06-13T00:00:00Z", "period_end": "2026-07-01T00:00:00Z",
    }, BILLING), 201)
    pro = validate_success(api.create_invoice({
        "account_id": ctx["account"]["id"], "contract_id": ctx["contract"]["id"],
        "invoice_kind": "PRORATION",
        "period_start": "2026-06-13T00:00:00Z", "period_end": "2026-07-01T00:00:00Z",
    }, BILLING), 201)

    assert full["amount_cents"] == 4500, f"RENTAL_CYCLE flat month, got {full['amount_cents']}"
    assert pro["amount_cents"] == 2700, f"PRORATION 18 days * 150c/day, got {pro['amount_cents']}"
    assert full["amount_cents"] != pro["amount_cents"]


# ===========================================================================
# Dual-variant calc: covered claim settles at 0, out-of-warranty settles charged
# ===========================================================================
def test_claim_settlement_covered_zero_vs_out_of_warranty_charged(api):
    """PRD §3.9: "when the claim is covered the settlement is 0 regardless of
    defect class; when it is not covered the customer pays the parts-plus-labor
    cost reduced by an age-based goodwill discount."
    PRD §3.9: "The parts base is keyed to the defect class — 18000 cents for a
    valve failure, 12000 for resin fouling, 26000 for a control board, 8000 for a
    leak, and 9000 for a UV ballast — and labor is a flat 9000 cents."

    Design: Difficulty/dual_variant_calc/claim_settlement_covered_vs_out_of_warranty_on_warrantyclaim
    """
    # Covered: fresh VALVE_FAILURE (installed 2026-01-01, reported 2026-06-01 -> 151d <= 1825)
    covered = setup_triaged_claim(defect_class="VALVE_FAILURE", install_at="2026-01-01T00:00:00Z",
                                  reported_at="2026-06-01T00:00:00Z", triage_at="2026-06-01T00:00:00Z")
    assert covered["claim"]["covered"] is True
    cov_resolved = validate_success(
        api.resolve_warranty_claim(covered["claim"]["id"], {"resolution": "REPAIR"}, SM), 200)
    assert cov_resolved["settlement_cents"] == 0

    # Out-of-warranty: CONTROL_BOARD (window 730d) on a 2-year-old system.
    # install 2024-01-01, now 2026-06-01 -> age ~882d > 730 -> not covered.
    # goodwill: floor(882/365)=2 steps * 5% = 10%; (26000+9000)*(1-0.10)=31500.
    oow = setup_triaged_claim(defect_class="CONTROL_BOARD", install_at="2024-01-01T00:00:00Z",
                              reported_at="2026-06-01T00:00:00Z", triage_at="2026-06-01T00:00:00Z")
    assert oow["claim"]["covered"] is False
    oow_resolved = validate_success(
        api.resolve_warranty_claim(oow["claim"]["id"], {"resolution": "REPAIR"}, SM), 200)
    assert oow_resolved["settlement_cents"] == 31500, \
        f"(26000+9000)*(1-0.10)=31500, got {oow_resolved['settlement_cents']}"


# ===========================================================================
# Combinatorial: PRORATION round-then-multiply (mode b)
# ===========================================================================
def test_proration_rounds_daily_rate_before_multiplying(api):
    """PRD §3.10: "the daily rate is the `monthly_rate_cents` divided by 30 days
    per billing month, rounded half up to whole cents first, and only then
    multiplied by the billable-day count — the rounding happens before the
    multiplication, never after."

    Design: Difficulty/combinatorial_formula/proration_round_then_multiply_order_mode_b
    """
    ctx = setup_active_rental_contract(monthly_rate_cents=4505, term_months=12,
                                       start_date="2026-06-13T00:00:00Z")
    set_clock("2026-07-05T00:00:00Z", BILLING)
    pro = validate_success(api.create_invoice({
        "account_id": ctx["account"]["id"], "contract_id": ctx["contract"]["id"],
        "invoice_kind": "PRORATION",
        "period_start": "2026-06-13T00:00:00Z", "period_end": "2026-07-01T00:00:00Z",
    }, BILLING), 201)
    # round_half_up(4505/30)=150; 150*18=2700 (NOT 4505/30*18=2703).
    assert pro["amount_cents"] == 2700, f"round-then-multiply -> 2700, got {pro['amount_cents']}"


# ===========================================================================
# Combinatorial: tiered ETF rate with cap (mode a)
# ===========================================================================
def test_early_termination_fee_tier3_rate_uncapped(api):
    """PRD §3.8: "if the months remaining are 3 or fewer the rate is the full rate
    of 1.0; if they are more than 3 but 6 or fewer the rate is 0.6; if they exceed
    6 the rate is 0.4. The raw fee is the months remaining multiplied by
    `monthly_rate_cents` multiplied by that rate; the stored
    `early_termination_fee_cents` is that raw amount rounded half up to whole cents
    and then capped at 50000 cents, with the cap applied after rounding."

    Design: Difficulty/combinatorial_formula/early_termination_fee_tiered_rate_with_cap_mode_a
    """
    ctx = setup_active_rental_contract(monthly_rate_cents=4500, term_months=12,
                                       start_date="2026-01-01T00:00:00Z")
    set_clock("2026-03-02T00:00:00Z", BILLING)  # 60 days -> 2 months elapsed, 10 remaining
    rc_v = ctx["contract"]["version"]
    result = validate_success(api.terminate_rental_contract(
        ctx["contract"]["id"], {"expected_rentalcontract_version": rc_v}, BILLING), 200)
    # months_remaining=10 (>6 -> tier3 0.4): 10*4500*0.4 = 18000, < cap 50000.
    assert result["early_termination_fee_cents"] == 18000, \
        f"10*4500*0.4=18000, got {result['early_termination_fee_cents']}"
    assert result["status"] == "TERMINATED"


# ===========================================================================
# Transitive cascade depth-3: terminate -> fee invoice -> ledger debit
# ===========================================================================
def test_terminate_fee_invoice_debits_account_ledger(api):
    """PRD §3.8: "When the computed fee is greater than 0, termination creates a
    termination invoice for that amount, and that invoice debits the account's
    `credit_balance_cents` ledger — termination to fee invoice to ledger debit is a
    three-level cascade."
    PRD §3.10: "The amount applied is the smaller of the invoice's `amount_cents`
    and the account's `credit_balance_cents` before the debit; the ledger is
    reduced by that applied amount, leaving any remainder owed on the open invoice
    itself, and `credit_balance_cents` is floored at 0 and never goes negative."

    Design: Difficulty/transitive_cascade/terminate_to_fee_invoice_to_ledger_debit_depth3
    """
    ctx = setup_active_rental_contract(monthly_rate_cents=4500, term_months=12,
                                       start_date="2026-01-01T00:00:00Z")
    get_success_data(api.credit_account(ctx["account"]["id"], {"amount_cents": 5000}, BILLING))
    set_clock("2026-03-02T00:00:00Z", BILLING)  # 10 months remaining -> fee 18000

    rc_v = get_success_data(api.get_rental_contract(ctx["contract"]["id"], BILLING))["version"]
    result = validate_success(api.terminate_rental_contract(
        ctx["contract"]["id"], {"expected_rentalcontract_version": rc_v}, BILLING), 200)
    assert result["early_termination_fee_cents"] == 18000

    acct = validate_success(api.get_account(ctx["account"]["id"], SM), 200)
    assert acct["credit_balance_cents"] == 0, "applied=min(18000,5000)=5000 -> balance floor 0"

    invoices, meta = validate_paginated(api.list_invoices(BILLING, params={"account_id": ctx["account"]["id"]}))
    term = [i for i in invoices if i["invoice_kind"] == "TERMINATION"
            and i.get("contract_id") == ctx["contract"]["id"]]
    assert len(term) == 1, f"exactly one TERMINATION invoice expected, got {len(term)}"
    assert term[0]["amount_cents"] == 18000


# ===========================================================================
# Compensating invariant #1: visit confirm/void conserves credit_balance_cents
# ===========================================================================
def test_visit_confirm_then_void_conserves_account_credit(api):
    """PRD §3.6: "If the visit's `billable_cents` is greater than 0, confirmation
    creates a service-repair invoice that debits the account ledger as a cascade."
    PRD §3.6: "If a service-repair invoice was created when the visit was confirmed
    and that invoice is still open, voiding the visit voids that invoice and credits
    the account ledger back, compensating the confirm cascade so the account's
    credit balance nets back to its pre-confirm value."

    Design: Difficulty/compensating_invariant/visit_confirm_void_conserves_account_credit_balance
    """
    ctx = setup_active_system()
    get_success_data(api.credit_account(ctx["account"]["id"], {"amount_cents": 5000}, BILLING))

    visit = get_success_data(api.create_service_visit({
        "system_id": ctx["system"]["id"], "visit_type": "REPAIR",
        "gallons_treated_reading": 0, "billable_cents": 9000,
    }, ctx["tech_headers"]))
    get_success_data(api.confirm_service_visit(visit["id"], ctx["tech_headers"]))

    acct_after_confirm = validate_success(api.get_account(ctx["account"]["id"], SM), 200)
    assert acct_after_confirm["credit_balance_cents"] == 0, "applied=min(9000,5000)=5000 -> 0"

    voided = validate_success(api.void_service_visit(visit["id"], SM), 200)
    assert voided["status"] == "VOIDED"
    acct_after_void = validate_success(api.get_account(ctx["account"]["id"], SM), 200)
    assert acct_after_void["credit_balance_cents"] == 5000, "void credits back exactly 5000"


# ===========================================================================
# Compensating invariant #2: rental invoice issue/void conserves months_billed
# ===========================================================================
def test_rental_invoice_issue_then_void_conserves_months_billed(api):
    """PRD §3.10: "For a `RENTAL_CYCLE` invoice, issuing also increments the
    contract's `months_billed` by 1."
    PRD §3.10: "If the voided invoice was a `RENTAL_CYCLE` invoice, the void also
    decrements the contract's `months_billed` by 1, so that issuing and then voiding
    a rental-cycle invoice leaves both the ledger and `months_billed` exactly where
    they were."

    Design: Difficulty/compensating_invariant/rental_invoice_issue_void_conserves_months_billed
    """
    ctx = setup_active_rental_contract(monthly_rate_cents=4500, term_months=12,
                                       start_date="2026-01-01T00:00:00Z")
    invoice = get_success_data(api.create_invoice({
        "account_id": ctx["account"]["id"], "contract_id": ctx["contract"]["id"],
        "invoice_kind": "RENTAL_CYCLE",
        "period_start": "2026-01-01T00:00:00Z", "period_end": "2026-02-01T00:00:00Z",
    }, BILLING))

    rc_after_issue = validate_success(api.get_rental_contract(ctx["contract"]["id"], BILLING), 200)
    assert rc_after_issue["months_billed"] == 1

    voided = validate_success(api.void_invoice(invoice["id"], BILLING), 200)
    assert voided["status"] == "VOID"
    rc_after_void = validate_success(api.get_rental_contract(ctx["contract"]["id"], BILLING), 200)
    assert rc_after_void["months_billed"] == 0


# ===========================================================================
# Calculation corner: term-complete termination yields zero fee, no invoice
# ===========================================================================
def test_term_complete_termination_zero_fee_no_invoice(api):
    """PRD §3.8: "the months remaining is the committed `term_months` minus that
    elapsed count, floored at 0. If no months remain, the fee is 0 and no
    termination invoice is created."

    Design: Corner/calculations/term_complete_termination_zero_fee_no_invoice
    """
    ctx = setup_active_rental_contract(monthly_rate_cents=4500, term_months=12,
                                       start_date="2026-01-01T00:00:00Z")
    set_clock("2026-12-31T00:00:00Z", BILLING)  # 12 months elapsed -> 0 remaining
    rc_v = get_success_data(api.get_rental_contract(ctx["contract"]["id"], BILLING))["version"]
    result = validate_success(api.terminate_rental_contract(
        ctx["contract"]["id"], {"expected_rentalcontract_version": rc_v}, BILLING), 200)
    assert result["early_termination_fee_cents"] == 0
    assert result["status"] == "TERMINATED"

    invoices, _ = validate_paginated(api.list_invoices(BILLING, params={"contract_id": ctx["contract"]["id"]}))
    assert not [i for i in invoices if i["invoice_kind"] == "TERMINATION"], \
        "no TERMINATION invoice should exist when fee is 0"


# ===========================================================================
# Calculation corner: tier1 rate (full) on small remaining months
# ===========================================================================
def test_termination_fee_tier1_full_rate(api):
    """PRD §3.8: "if the months remaining are 3 or fewer the rate is the full rate
    of 1.0 ... The raw fee is the months remaining multiplied by `monthly_rate_cents`
    multiplied by that rate."

    Design: Corner/calculations/termination_fee_tier1_rate_full_remaining
    """
    ctx = setup_active_rental_contract(monthly_rate_cents=4500, term_months=12,
                                       start_date="2026-01-01T00:00:00Z")
    set_clock("2026-11-01T00:00:00Z", BILLING)  # 304 days -> 10 months elapsed -> 2 remaining
    rc_v = get_success_data(api.get_rental_contract(ctx["contract"]["id"], BILLING))["version"]
    result = validate_success(api.terminate_rental_contract(
        ctx["contract"]["id"], {"expected_rentalcontract_version": rc_v}, BILLING), 200)
    # 2 remaining (<=3 -> tier1 1.0): 2*4500*1.0 = 9000.
    assert result["early_termination_fee_cents"] == 9000


# ===========================================================================
# Calculation corner: partial-apply floors credit balance at zero
# ===========================================================================
def test_invoice_partial_apply_floors_credit_at_zero(api):
    """PRD §3.10: "The amount applied is the smaller of the invoice's `amount_cents`
    and the account's `credit_balance_cents` before the debit; the ledger is reduced
    by that applied amount, leaving any remainder owed on the open invoice itself,
    and `credit_balance_cents` is floored at 0 and never goes negative."

    Design: Corner/calculations/invoice_partial_apply_floors_credit_balance_at_zero
    """
    # Build an aged (2-year-old) PURCHASE system so an uncovered CONTROL_BOARD claim
    # close emits a 31500-cent SERVICE_REPAIR invoice against an account credited 10000.
    ctx = setup_account_with_accepted_test()
    get_success_data(api.credit_account(ctx["account"]["id"], {"amount_cents": 10000}, BILLING))

    set_clock("2024-01-01T00:00:00Z")
    sys = get_success_data(api.create_system(
        create_system_payload(ctx["account"]["id"], ctx["water_test"]["id"],
                              acquisition_mode="PURCHASE", grain_capacity=32000), SM))
    get_success_data(api.install_system(sys["id"], ctx["tech_headers"]))
    get_success_data(api.activate_system(sys["id"], ctx["tech_headers"]))

    set_clock("2026-01-01T00:00:00Z")
    claim = get_success_data(api.create_warranty_claim({
        "system_id": sys["id"], "defect_class": "CONTROL_BOARD",
        "reported_at": "2026-01-01T00:00:00Z"}, ctx["tech_headers"]))
    get_success_data(api.triage_warranty_claim(claim["id"], ctx["tech_headers"]))
    get_success_data(api.resolve_warranty_claim(claim["id"], {"resolution": "REPAIR"}, SM))
    get_success_data(api.close_warranty_claim(claim["id"], SM))

    acct = validate_success(api.get_account(ctx["account"]["id"], BILLING), 200)
    assert acct["credit_balance_cents"] == 0, "applied=min(31500,10000)=10000 -> floor 0"

    invoices, _ = validate_paginated(api.list_invoices(BILLING, params={"account_id": ctx["account"]["id"]}))
    repair = [i for i in invoices if i["invoice_kind"] == "SERVICE_REPAIR" and i["amount_cents"] == 31500]
    assert len(repair) == 1, f"one 31500-cent SERVICE_REPAIR invoice expected, got {len(repair)}"

