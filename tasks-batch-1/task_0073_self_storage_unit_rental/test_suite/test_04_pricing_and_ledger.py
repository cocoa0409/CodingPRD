"""Dual-variant balance/redemption, per-component rounding, proration, reversal.

Queue A (Difficulty) translations: dual_variant_calc, combinatorial_formula,
compensating_invariant (money conservation).
"""
import pytest
from test_helpers import (
    validate_success, validate_paginated,
    TEST_USERS, make_tenant_headers,
    setup_activated, setup_base, setup_auction_opened,
    set_clock, pay, create_facility, create_unit, create_tenant, create_lease,
    create_insurance_policy,
    api_client,
)

FM = TEST_USERS["facility_manager_headers"]
LIEN = TEST_USERS["lien_administrator_headers"]


# ─── dual_variant_calc / dual_lease_balance_denormalized_vs_ledger_replay ───

def test_lease_balance_denormalized_equals_ledger_replay(api):
    """PRD §2.6: "this denormalized value is the authoritative figure the API returns on
    the lease."
    PRD §2.6: "a reconciliation read is offered that replays the ledger: it sums the
    signed `amount_cents` over every `LedgerEntry` for the lease, processed in
    `created_at` ascending order, and returns the resulting figure. When the system is
    internally consistent this replayed balance equals the denormalized `balance_cents`."

    Design: Difficulty/dual_variant_calc/dual_lease_balance_denormalized_vs_ledger_replay
    """
    # Climate unit @10000, 0.20 premium -> first full-month invoice 12000; pay 5000.
    ctx = setup_activated(unit_overrides={"climate_controlled": True,
                                          "monthly_rate_cents": 10000})
    pay(ctx["lease"]["id"], 5000, ctx["tenant"]["id"])
    denorm = validate_success(api.get_lease(ctx["lease"]["id"], FM), 200)
    replay = validate_success(api.get_ledger_balance(ctx["lease"]["id"], FM), 200)
    assert denorm["balance_cents"] == 7000, "12000 CHARGE - 5000 PAYMENT"
    assert replay["balance_cents"] == 7000
    assert denorm["balance_cents"] == replay["balance_cents"]


def test_ledger_replay_sums_signed_amounts(api):
    """PRD §2.6: "it sums the signed `amount_cents` over every `LedgerEntry` for the
    lease, processed in `created_at` ascending order, and returns the resulting figure."

    Design: Difficulty/dual_variant_calc/dual_lease_balance_denormalized_vs_ledger_replay
    """
    ctx = setup_activated(unit_overrides={"climate_controlled": True,
                                          "monthly_rate_cents": 10000})
    pay(ctx["lease"]["id"], 5000, ctx["tenant"]["id"])
    entries, _ = validate_paginated(
        api.list_ledger_entries(FM, params={"lease_id": ctx["lease"]["id"]}))
    total = sum(e["amount_cents"] for e in entries)
    assert total == 7000, f"signed sum of ledger must be 7000, entries={entries}"
    replay = validate_success(api.get_ledger_balance(ctx["lease"]["id"], FM), 200)
    assert replay["balance_cents"] == total


# ─── combinatorial_formula / monthly_charge per-component rounding (mode b) ───

def test_monthly_charge_rounds_each_component_before_summing(api):
    """PRD §3.3: "when it is climate-controlled, it is the snapshot `monthly_rate_cents`
    multiplied by the facility's `climate_premium_pct`, rounded half-up to whole cents."
    PRD §3.3: "The full monthly total is the sum of these three already-rounded
    components — the components are each rounded first, then added, never summed as
    fractions and rounded once."

    Design: Difficulty/combinatorial_formula/combinatorial_monthly_charge_rounding_order_mode_b
    """
    # climate_premium_pct=0.155, base 10033, STANDARD insurance 1500.
    fac = create_facility(name="F3", state_code="TX", climate_premium_pct=0.155)
    unit = create_unit(fac["id"], unit_number="A-3", size_class="SIZE_10X20",
                       monthly_rate_cents=10033, climate_controlled=True)
    ten = create_tenant(email="t3@x.com", full_name="T Three", state_code="TX")
    set_clock("2026-05-01T00:00:00Z")
    lease = create_lease(unit["id"], ten["id"], start_date="2026-05-01T00:00:00Z",
                         insurance_required=True)
    create_insurance_policy(lease["id"], coverage_tier="STANDARD",
                            coverage_start="2026-05-01T00:00:00Z")
    validate_success(api.activate_lease(lease["id"], FM), 200)
    # The first invoice's base is the prorated full monthly total (PRD §3.3 line
    # "The prorated base is the full monthly total ... "). The three-component
    # breakdown of a *full* monthly charge surfaces on a regular billing-cycle
    # invoice, so advance to the next billing day and run a cycle.
    set_clock("2026-06-01T00:00:00Z")
    validate_success(api.run_billing_cycle(fac["id"], FM), 200)
    invoices, _ = validate_paginated(api.list_invoices(FM, params={"lease_id": lease["id"]}))
    monthly = next(i for i in invoices if i["period_start"].startswith("2026-06-01"))
    # round_half_up(10033 * 0.155) = round_half_up(1555.115) = 1555.
    assert monthly["climate_amount_cents"] == 1555
    assert monthly["insurance_amount_cents"] == 1500
    assert monthly["total_amount_cents"] == 13088, "10033 + 1555 + 1500 (per-component round)"


def test_monthly_charge_full_month_components_sum(api):
    """PRD §3.3: "The base component is the lease's snapshot `monthly_rate_cents`."
    PRD §3.3: "The insurance component is the `monthly_premium_cents` of the lease's
    active insurance policy when one exists, and zero otherwise."

    Design: Difficulty/combinatorial_formula/combinatorial_monthly_charge_rounding_order_mode_b
    """
    fac = create_facility(name="F3b", state_code="TX", climate_premium_pct=0.155)
    unit = create_unit(fac["id"], unit_number="A-3b", size_class="SIZE_10X20",
                       monthly_rate_cents=10033, climate_controlled=True)
    ten = create_tenant(email="t3b@x.com", full_name="T Three B", state_code="TX")
    set_clock("2026-05-01T00:00:00Z")
    lease = create_lease(unit["id"], ten["id"], start_date="2026-05-01T00:00:00Z",
                         insurance_required=True)
    create_insurance_policy(lease["id"], coverage_tier="STANDARD",
                            coverage_start="2026-05-01T00:00:00Z")
    validate_success(api.activate_lease(lease["id"], FM), 200)
    # Full-month component breakout surfaces on a regular billing-cycle invoice
    # (the first invoice's base is the prorated full monthly total per PRD §3.3).
    set_clock("2026-06-01T00:00:00Z")
    validate_success(api.run_billing_cycle(fac["id"], FM), 200)
    invoices, _ = validate_paginated(api.list_invoices(FM, params={"lease_id": lease["id"]}))
    monthly = next(i for i in invoices if i["period_start"].startswith("2026-06-01"))
    assert monthly["base_amount_cents"] == 10033
    assert (monthly["total_amount_cents"]
            == monthly["base_amount_cents"] + monthly["climate_amount_cents"]
            + monthly["insurance_amount_cents"] + monthly["late_fee_cents"])


# ─── combinatorial_formula / prorated first charge (mode a) ───

def test_prorated_first_invoice_mid_month(api):
    """PRD §3.3: "the days occupied be that day count minus the day-of-month of
    `start_date` plus one, so the move-in day itself counts as occupied. The prorated
    base is the full monthly total multiplied by the days occupied, divided by the days in
    the month, with a single round-half-up applied to whole cents after that day-fraction
    multiply."

    Design: Difficulty/combinatorial_formula/combinatorial_prorated_first_charge_conditional_mode_a
    """
    # Climate @10000, 0.20 -> monthly_total 12000; start 2026-04-21 (April 30d, day 21
    # -> 10 occupied days) -> round_half_up(12000 * 10/30) = 4000.
    ctx = setup_base(unit_overrides={"climate_controlled": True, "monthly_rate_cents": 10000},
                     start_date="2026-04-21T00:00:00Z")
    activated = validate_success(api.activate_lease(ctx["lease"]["id"], FM), 200)
    assert activated["balance_cents"] == 4000
    invoices, _ = validate_paginated(
        api.list_invoices(FM, params={"lease_id": ctx["lease"]["id"]}))
    assert invoices[0]["total_amount_cents"] == 4000


def test_prorated_first_invoice_base_component(api):
    """PRD §3.3: "A first invoice is generated covering occupancy from the `start_date`
    to the next billing day, with its base rent prorated to the move-in day."

    Design: Difficulty/combinatorial_formula/combinatorial_prorated_first_charge_conditional_mode_a
    """
    ctx = setup_base(unit_overrides={"climate_controlled": True, "monthly_rate_cents": 10000},
                     start_date="2026-04-21T00:00:00Z")
    validate_success(api.activate_lease(ctx["lease"]["id"], FM), 200)
    invoices, _ = validate_paginated(
        api.list_invoices(FM, params={"lease_id": ctx["lease"]["id"]}))
    # The prorated invoice total is 4000 (the single round applies to the full total).
    assert invoices[0]["total_amount_cents"] == 4000


# ─── compensating_invariant / payment reversal conserves balance (money) ───

def test_payment_reversal_restores_pre_payment_balance(api):
    """PRD §3.6: "Reversal moves the payment `APPLIED → REVERSED`, appends a `REVERSAL`
    ledger entry that re-adds the payment amount, raises the lease's `balance_cents` back
    to its pre-payment value, and reverts the invoices the payment had covered from `PAID`
    or `PARTIAL` back to `OPEN` or `PARTIAL` as appropriate."

    Design: Difficulty/compensating_invariant/invariant_payment_reversal_conserves_lease_balance
    """
    ctx = setup_activated(unit_overrides={"climate_controlled": True,
                                          "monthly_rate_cents": 10000})
    payment = pay(ctx["lease"]["id"], 12000, ctx["tenant"]["id"])
    after_pay = validate_success(api.get_lease(ctx["lease"]["id"], FM), 200)
    assert after_pay["balance_cents"] == 0
    reversed_pay = validate_success(api.reverse_payment(payment["id"], FM), 200)
    assert reversed_pay["status"] == "REVERSED"
    after_rev = validate_success(api.get_lease(ctx["lease"]["id"], FM), 200)
    assert after_rev["balance_cents"] == 12000, "restored to pre-payment value"


def test_payment_reversal_ledger_replay_consistent(api):
    """PRD §2.6: "a `REVERSAL` re-adds the amount of a previously recorded payment."
    PRD §2.6: "When the system is internally consistent this replayed balance equals the
    denormalized `balance_cents`."

    Design: Difficulty/compensating_invariant/invariant_payment_reversal_conserves_lease_balance
    """
    ctx = setup_activated(unit_overrides={"climate_controlled": True,
                                          "monthly_rate_cents": 10000})
    payment = pay(ctx["lease"]["id"], 12000, ctx["tenant"]["id"])
    validate_success(api.reverse_payment(payment["id"], FM), 200)
    replay = validate_success(api.get_ledger_balance(ctx["lease"]["id"], FM), 200)
    # CHARGE +12000, PAYMENT -12000, REVERSAL +12000 = 12000.
    assert replay["balance_cents"] == 12000
