"""Billing calculations: modifier-adjusted monthly, capped-rental quote vs
chronological, audit recoupment totals, and immediate ledger consistency.
"""
from test_helpers import (
    validate_success,
    get_success_data,
    fixtures,
)
from test_helpers.test_users import make_supplier_headers, TEST_USERS

PAYER = TEST_USERS["payer_headers"]


# ─── Difficulty: dual_variant_calc ────────────────────
def test_rental_quote_projects_full_13_month_obligation(api):
    """PRD §3.7: "This forward-looking quote projects the full capped-rental
    obligation in one shot as 13 multiplied by the modifier-adjusted monthly amount
    computed at today's rate, assuming all 13 months will bill at that rate."
    PRD §3.7: "The quote response reports provisional_total_cents (the 13-month
    projection), monthly_allowed_cents (the single-month modifier-adjusted amount),
    and cap_months (the cap of 13)."

    Design: Difficulty/dual_variant_calc/capped_rental_provisional_vs_chronological
    """
    fixtures.set_clock("2026-01-01T00:00:00Z")
    order, supplier, item, _ = fixtures.setup_active_rental_order(
        item_overrides={"billing_category": "CAPPED_RENTAL", "monthly_rental_cents": 10000},
        modifier="KX", ordered_at_utc="2026-01-01T00:00:00Z",
    )
    sup_headers = make_supplier_headers(supplier["id"])
    resp = api.get_rental_quote(order["id"], sup_headers)
    data = validate_success(resp, 200)
    assert data["provisional_total_cents"] == 130000
    assert data["monthly_allowed_cents"] == 10000
    assert data["cap_months"] == 13


def test_chronological_total_differs_from_provisional_after_two_cycles(api):
    """PRD §3.7: "the realized rental total is the sum over the cycles actually
    posted." "the actual total is the sum over the months actually posted and
    therefore differs from the provisional projection whenever fewer than 13 months
    have been billed."

    Design: Difficulty/dual_variant_calc/capped_rental_provisional_vs_chronological
    """
    fixtures.set_clock("2026-01-01T00:00:00Z")
    order, supplier, item, cycles = fixtures.setup_rental_with_cycles(
        2, monthly_rental_cents=10000, modifier="KX",
    )
    sup_headers = make_supplier_headers(supplier["id"])
    order = get_success_data(api.get_order(order["id"], sup_headers))
    quote = validate_success(api.get_rental_quote(order["id"], sup_headers), 200)
    assert order["total_allowed_cents"] == 20000
    assert order["total_allowed_cents"] != quote["provisional_total_cents"]
    assert quote["provisional_total_cents"] == 130000


def test_audit_settled_only_basis_recoups_paid_cycle_only(api):
    """PRD §3.11: "For the proof-of-delivery basis — reason code
    NO_PROOF_OF_DELIVERY — only cycles in PAID status are recouped, since a missing
    proof of delivery claws back money that actually moved; cycles still in BILLED
    status are not recouped under this basis."

    Design: Difficulty/dual_variant_calc/audit_recoupment_billed_vs_settled_basis
    """
    order, supplier, item, cycles, audit = fixtures.setup_audit_ready(
        3, reason_code="NO_PROOF_OF_DELIVERY",
        monthly_rental_cents=10000, modifier="KX",
        paid_cycle_indices=[0],
    )
    resp = api.uphold_audit(audit["id"], PAYER)
    data = validate_success(resp, 200)
    assert data["recouped_total_cents"] == 10000
    assert data["recouped_cycle_count"] == 1


def test_audit_billed_basis_recoups_all_cycles(api):
    """PRD §3.11: "For the default audit basis — reason codes OVERBILLED_PAST_CAP,
    NO_VALID_CMN, and NO_PRIOR_AUTH — every cycle on the order in BILLED or PAID
    status is recouped, because the underlying certification or authorization defect
    invalidates the whole billing stream, including amounts not yet settled."

    Design: Difficulty/dual_variant_calc/audit_recoupment_billed_vs_settled_basis
    """
    order, supplier, item, cycles, audit = fixtures.setup_audit_ready(
        3, reason_code="OVERBILLED_PAST_CAP",
        monthly_rental_cents=10000, modifier="KX",
        paid_cycle_indices=[0],
    )
    resp = api.uphold_audit(audit["id"], PAYER)
    data = validate_success(resp, 200)
    assert data["recouped_total_cents"] == 30000
    assert data["recouped_cycle_count"] == 3


# ─── Difficulty: combinatorial_formula ────────────────
def test_oxygen_monthly_clamped_to_ceiling(api):
    """PRD §3.7: "A coverage percentage is selected first: if the modifier is KX,
    coverage is 100 percent; otherwise, if the item requires a certificate of
    medical necessity, coverage is capped at 80 percent; otherwise coverage is 100
    percent."
    PRD §3.7: "For items in the OXYGEN billing category, the raw amount is then
    clamped into a band: if it falls below the oxygen floor of 5000 cents it is
    raised to 5000 cents, and if it exceeds the oxygen ceiling of 20000 cents it is
    lowered to 20000 cents."

    Design: Difficulty/combinatorial_formula/modifier_adjusted_monthly_nonlinear_minmax
    """
    # OXYGEN must be ordered RENTAL; requires_cmn=true so a CMN is needed first.
    order, supplier, item, _ = fixtures.setup_active_rental_order(
        item_overrides={"billing_category": "OXYGEN", "monthly_rental_cents": 30000,
                        "requires_cmn": True},
        modifier="NONE", ordered_at_utc="2026-03-01T00:00:00Z",
        with_cmn=True,
    )
    sup_headers = make_supplier_headers(supplier["id"])
    resp = api.post_rental_cycle(order["id"], sup_headers)
    data = validate_success(resp, 201)
    # raw 30000*80/100=24000, clamped to ceiling 20000.
    assert data["billed_amount_cents"] == 20000


def test_audit_recoupment_rounds_per_cycle_then_sums(api):
    """PRD §2.6: "each recouped cycle is rounded to whole cents first and the
    rounded per-cycle amounts are then summed, rather than summing first and
    rounding once at the end."
    PRD §3.11: "each recouped cycle's billed_amount_cents rounded half up to whole
    cents first, then summed (the system rounds per cycle and then sums, never the
    reverse)."

    Design: Difficulty/combinatorial_formula/audit_recoupment_round_per_cycle_then_sum
    """
    # monthly 10000, modifier NONE, requires_cmn=true -> 80% -> 8000/cycle.
    order, supplier, item, cycles, audit = fixtures.setup_audit_ready(
        3, reason_code="OVERBILLED_PAST_CAP",
        monthly_rental_cents=10000, modifier="NONE",
        item_overrides={"billing_category": "CAPPED_RENTAL", "requires_cmn": True},
        with_cmn=True,
    )
    resp = api.uphold_audit(audit["id"], PAYER)
    data = validate_success(resp, 200)
    assert data["recouped_total_cents"] == 24000
    assert data["recouped_cycle_count"] == 3


def test_recoupment_lines_negate_each_cycle_rounded_amount(api):
    """PRD §3.11: "one system-created claim line of type RECOUPMENT is created whose
    allowed_amount_cents is the negation of that cycle's already-rounded
    billed_amount_cents and whose audit_id is the upholding audit's id."

    Design: Difficulty/combinatorial_formula/audit_recoupment_round_per_cycle_then_sum
    """
    from test_helpers import validate_paginated
    # monthly 10000, modifier NONE, requires_cmn=true -> 8000/cycle (already rounded).
    order, supplier, item, cycles, audit = fixtures.setup_audit_ready(
        3, reason_code="OVERBILLED_PAST_CAP",
        monthly_rental_cents=10000, modifier="NONE",
        item_overrides={"billing_category": "CAPPED_RENTAL", "requires_cmn": True},
        with_cmn=True,
    )
    get_success_data(api.uphold_audit(audit["id"], PAYER))
    lines, _ = validate_paginated(
        api.list_claim_lines(
            PAYER, params={"order_id": order["id"], "line_type": "RECOUPMENT", "limit": 100}
        )
    )
    assert len(lines) == 3
    # Each RECOUPMENT line is the negation of one cycle's rounded amount (-8000).
    assert all(cl["allowed_amount_cents"] == -8000 for cl in lines)
    assert all(cl["audit_id"] == audit["id"] for cl in lines)


def test_modifier_adjusted_per_cycle_amount_at_80pct_coverage(api):
    """PRD §3.7: "if the modifier is KX, coverage is 100 percent; otherwise, if the
    item requires a certificate of medical necessity, coverage is capped at 80
    percent; otherwise coverage is 100 percent. The raw amount is the base
    multiplied by the coverage percentage and divided by 100."

    Design: Difficulty/combinatorial_formula/modifier_adjusted_monthly_nonlinear_minmax
    """
    order, supplier, item, _ = fixtures.setup_active_rental_order(
        item_overrides={"billing_category": "CAPPED_RENTAL", "monthly_rental_cents": 10000,
                        "requires_cmn": True},
        modifier="NONE", ordered_at_utc="2026-04-01T00:00:00Z",
        with_cmn=True,
    )
    sup_headers = make_supplier_headers(supplier["id"])
    resp = api.post_rental_cycle(order["id"], sup_headers)
    data = validate_success(resp, 201)
    assert data["billed_amount_cents"] == 8000  # 10000 * 80 / 100


# ─── Corner: §consistency_model ───────────────────────
def test_rental_cycle_post_immediately_visible_on_order_read(api):
    """PRD §2.7: "This total is recomputed every time a claim line is created or
    voided, every time a rental cycle is billed or recouped, and every time an audit
    is upheld."
    PRD §3.7: "recomputes the order's rental_months_billed and total_allowed_cents."

    Design: Corner/consistency_model/rental_cycle_post_immediately_visible_on_order_read
    """
    order, supplier, item, _ = fixtures.setup_active_rental_order(
        item_overrides={"billing_category": "CAPPED_RENTAL", "monthly_rental_cents": 10000},
        modifier="KX",
    )
    sup_headers = make_supplier_headers(supplier["id"])
    get_success_data(api.post_rental_cycle(order["id"], sup_headers))
    order = get_success_data(api.get_order(order["id"], sup_headers))
    assert order["total_allowed_cents"] == 10000
