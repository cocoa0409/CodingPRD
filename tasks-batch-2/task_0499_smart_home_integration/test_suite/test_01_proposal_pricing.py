"""Proposal pricing and contract-balance calculations.

Covers the dual-variant calculation rule (proposal estimate vs. final-after-
change-order; contract balance provisional vs. drawn-down), the combinatorial
pricing formula (volume/loyalty/cap/labor-matrix and the pinned discount-then-tax
order), and corner calculation claims (small-subtotal no-discount, removed-item
input filtering, IP pool derivation, overage balance floor).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    factories as f, fixtures as fx,
)
from test_helpers.fixtures import (
    ADMIN, DESIGNER, PM, SUPPORT,
    create_client, create_project, create_rack, create_proposal,
    setup_draft_proposal_with_items, accept_proposal, project_version,
)
from test_helpers.api_client import api_client


# ===========================================================================
# Difficulty / dual_variant_calc / proposal_total_estimate_vs_final_after_change_order
# ===========================================================================

def _build_accepted_proposal_652174(region="WEST", billing="RESIDENTIAL"):
    """Residential WEST proposal {CONTROLLER 1x250000, AUDIO 4x80000}, labor 6.0:
    subtotal 570000, discount 28500, taxable 541500, tax 44674,
    labor 6*11000=66000, grand_total = 541500 + 66000 + 44674 = 652174.
    Returns (client, project_id, proposal_id)."""
    client = create_client(billing_tier=billing)
    project = create_project(client["id"], region_code=region)
    create_rack(project["id"])
    proposal, _ = setup_draft_proposal_with_items(
        project["id"],
        line_items=[
            dict(sku="C4-CTRL", category="CONTROLLER", qty=1, unit_price_cents=250000),
            dict(sku="C4-SPK", category="AUDIO", qty=4, unit_price_cents=80000),
        ],
        labor_hours_estimate=6.0,
    )
    get_success_data(api_client.send_proposal(project["id"], proposal["id"], DESIGNER))
    accept_proposal(project["id"], proposal["id"], client["id"])
    return client, project["id"], proposal["id"]


def test_proposal_grand_total_is_estimate_before_change_order_applied():
    """PRD §3.2: "grand_total_cents is the equipment subtotal minus the discount,
    plus the labor cost, plus the tax."

    Design: Difficulty/dual_variant_calc/proposal_total_estimate_vs_final_after_change_order
    """
    _, project_id, proposal_id = _build_accepted_proposal_652174()
    data = validate_success(api_client.get_proposal(proposal_id, PM))
    assert data["grand_total_cents"] == 652174, (
        f"estimate variant: expected 652174, got {data['grand_total_cents']}")
    assert data["labor_hours_estimate"] == 6.0


def test_proposal_grand_total_after_change_order_adds_delta_authoritatively():
    """PRD §3.3: "the applied delta_cents is added to the accepted proposal's
    grand_total_cents, and this applied delta is authoritative for the running
    total — the equipment subtotal, discount, and tax are not re-summed."
    PRD §3.3: "The change order's added_labor_hours is added to the proposal's
    labor_hours_estimate, and labor_cost_cents is recomputed from the new labor
    hours purely for record-keeping; the recomputed labor cost is not re-added
    into the grand total, because the delta already accounts for any labor impact."

    Design: Difficulty/dual_variant_calc/proposal_total_estimate_vs_final_after_change_order
    """
    client, project_id, proposal_id = _build_accepted_proposal_652174()
    co = get_success_data(api_client.create_change_order(
        project_id, f.create_change_order_payload(
            description="Add subwoofer", delta_cents=50000, added_labor_hours=1.0), PM))
    get_success_data(api_client.approve_change_order(
        project_id, co["id"], fx.make_client_headers(client["id"])))
    pre = project_version(project_id)
    validate_success(api_client.apply_change_order(
        project_id, co["id"], f.apply_change_order_payload(pre), PM))
    data = validate_success(api_client.get_proposal(proposal_id, PM))
    assert data["grand_total_cents"] == 702174, (
        f"final variant: expected 652174+50000=702174, got {data['grand_total_cents']}")
    assert data["labor_hours_estimate"] == 7.0


# ===========================================================================
# Difficulty / dual_variant_calc / contract_balance_provisional_vs_drawn_down
# ===========================================================================

def _project_with_pending_contract(prepaid_hours=10, hourly_rate_cents=12000, plan="PLUS"):
    # PRD §3.9: activating a PENDING contract requires the project to be
    # COMMISSIONED or ACTIVE, so drive the project to COMMISSIONED first.
    ctx = fx.setup_commissioned_project(region_code="WEST", billing_tier="RESIDENTIAL")
    project_id = ctx["project"]["id"]
    fx.create_contract(project_id, plan=plan, prepaid_hours=prepaid_hours,
                       hourly_rate_cents=hourly_rate_cents)
    return project_id


def test_contract_balance_provisional_at_activation():
    """PRD §3.9: "At activation, before any consumption, this reduces to
    prepaid_hours multiplied by hourly_rate_cents, rounded half up."

    Design: Difficulty/dual_variant_calc/contract_balance_provisional_vs_drawn_down
    """
    project_id = _project_with_pending_contract(prepaid_hours=10, hourly_rate_cents=12000)
    data = validate_success(api_client.activate_contract(project_id, SUPPORT))
    assert data["balance_cents"] == 120000, (
        f"provisional variant: expected 10*12000=120000, got {data['balance_cents']}")


def test_contract_balance_drawn_down_after_consume():
    """PRD §3.9: "the remaining hours are prepaid_hours minus consumed_hours; if
    the remaining hours are zero or less, the balance is 0; otherwise the balance
    is the remaining hours multiplied by hourly_rate_cents, rounded half up to
    whole cents."

    Design: Difficulty/dual_variant_calc/contract_balance_provisional_vs_drawn_down
    """
    project_id = _project_with_pending_contract(prepaid_hours=10, hourly_rate_cents=12000)
    validate_success(api_client.activate_contract(project_id, SUPPORT))
    data = validate_success(api_client.consume_contract(project_id, f.consume_payload(3.5), SUPPORT))
    assert data["consumed_hours"] == 3.5
    assert data["balance_cents"] == 78000, (
        f"drawn_down variant: expected (10-3.5)*12000=78000, got {data['balance_cents']}")


# ===========================================================================
# Difficulty / combinatorial_formula / proposal_total_tiered_volume_loyalty_labor_matrix
# ===========================================================================

def test_commercial_east_proposal_volume_loyalty_cap_and_labor_matrix():
    """PRD §3.2: "If the client's billing_tier is COMMERCIAL, an additional loyalty
    rate of 0.02 is added to the volume rate. The combined discount rate is then
    capped at 0.12, so it may never exceed that ceiling."
    PRD §3.2: "a subtotal of 2,000,000 cents or more earns a rate of 0.10."
    PRD §3.2: "for COMMERCIAL, 15,000 in NORTH, 13,000 in SOUTH, 16,000 in EAST,
    and 14,000 in WEST."
    PRD §3.2: "the tax rate is 0 for a COMMERCIAL client".

    Design: Difficulty/combinatorial_formula/proposal_total_tiered_volume_loyalty_labor_matrix
    """
    client = create_client(billing_tier="COMMERCIAL")
    project = create_project(client["id"], region_code="EAST")
    create_rack(project["id"], rack_units_total=20)
    proposal, _ = setup_draft_proposal_with_items(
        project["id"],
        line_items=[dict(sku="C4-SW", category="NETWORK", qty=10, unit_price_cents=200000)],
        labor_hours_estimate=20.0,
    )
    data = validate_success(api_client.send_proposal(project["id"], proposal["id"], DESIGNER))
    assert data["equipment_subtotal_cents"] == 2000000
    # tier2 0.10 + commercial loyalty 0.02 = 0.12 (at cap); 2000000*0.12
    assert data["discount_cents"] == 240000
    # commercial EAST labor rate 16000 * 20h
    assert data["labor_cost_cents"] == 320000
    assert data["tax_cents"] == 0
    # (2000000-240000) + 320000 + 0
    assert data["grand_total_cents"] == 2080000


def test_commercial_discount_rate_clamped_at_cap():
    """PRD §3.2: "The combined discount rate is then capped at 0.12, so it may
    never exceed that ceiling."
    PRD §3.2: "a subtotal of 2,000,000 cents or more earns a rate of 0.10."

    A COMMERCIAL client at the tier-2 subtotal would compute 0.10+0.02=0.12, which
    is exactly the cap; discount_cents = round_half_up(2000000*0.12) = 240000.

    Design: Difficulty/combinatorial_formula/proposal_total_tiered_volume_loyalty_labor_matrix
    """
    client = create_client(billing_tier="COMMERCIAL")
    project = create_project(client["id"], region_code="EAST")
    create_rack(project["id"], rack_units_total=20)
    proposal, _ = setup_draft_proposal_with_items(
        project["id"],
        line_items=[dict(sku="C4-SW", category="NETWORK", qty=10, unit_price_cents=200000)],
        labor_hours_estimate=20.0,
    )
    data = validate_success(api_client.send_proposal(project["id"], proposal["id"], DESIGNER))
    assert data["equipment_subtotal_cents"] == 2000000
    assert data["discount_cents"] == 240000, "0.10 volume + 0.02 loyalty = 0.12 cap"


# ===========================================================================
# Difficulty / combinatorial_formula / proposal_total_pinned_eval_order_discount_then_tax
# ===========================================================================

def test_pinned_eval_order_tax_computed_on_post_discount_base():
    """PRD §3.2: "the taxable base is the equipment subtotal minus the discount —
    labor is never taxed — and the tax rate is 0 for a COMMERCIAL client and
    0.0825 for a RESIDENTIAL client; tax_cents is the taxable base multiplied by
    the applicable tax rate, rounded half up to whole cents."
    PRD §3.2: "a subtotal from 500,000 cents up to but not including 2,000,000
    cents earns a rate of 0.05; a subtotal of 2,000,000 cents or more earns a rate
    of 0.10."

    Design: Difficulty/combinatorial_formula/proposal_total_pinned_eval_order_discount_then_tax
    """
    client = create_client(billing_tier="RESIDENTIAL")
    project = create_project(client["id"], region_code="WEST")
    create_rack(project["id"])
    proposal, _ = setup_draft_proposal_with_items(
        project["id"],
        line_items=[
            dict(sku="C4-CTRL", category="CONTROLLER", qty=1, unit_price_cents=250000),
            dict(sku="C4-SPK", category="AUDIO", qty=4, unit_price_cents=80000),
        ],
        labor_hours_estimate=6.0,
    )
    data = validate_success(api_client.send_proposal(project["id"], proposal["id"], DESIGNER))
    # subtotal 570000 -> 0.05 discount -> 28500
    assert data["discount_cents"] == 28500
    # taxable_base = 570000-28500 = 541500; tax = round_half_up(541500*0.0825) = 44674
    # (NOT 0.0825*570000 = 47025)
    assert data["tax_cents"] == 44674
    assert data["grand_total_cents"] == 652174


def test_grand_total_composes_post_discount_base_plus_labor_plus_tax():
    """PRD §3.2: "grand_total_cents is the equipment subtotal minus the discount,
    plus the labor cost, plus the tax."
    PRD §3.2: "labor_cost_cents is labor_hours_estimate multiplied by the labor
    rate for the project's region_code and the client's billing_tier".

    Residential WEST: labor 6h * 11000 = 66000; grand_total = (570000-28500) +
    66000 + 44674 = 652174 — the labor enters the total but is excluded from the
    taxable base, confirming the pinned discount-then-tax ordering.

    Design: Difficulty/combinatorial_formula/proposal_total_pinned_eval_order_discount_then_tax
    """
    client = create_client(billing_tier="RESIDENTIAL")
    project = create_project(client["id"], region_code="WEST")
    create_rack(project["id"])
    proposal, _ = setup_draft_proposal_with_items(
        project["id"],
        line_items=[
            dict(sku="C4-CTRL", category="CONTROLLER", qty=1, unit_price_cents=250000),
            dict(sku="C4-SPK", category="AUDIO", qty=4, unit_price_cents=80000),
        ],
        labor_hours_estimate=6.0,
    )
    data = validate_success(api_client.send_proposal(project["id"], proposal["id"], DESIGNER))
    assert data["labor_cost_cents"] == 66000  # 6 * 11000 (WEST residential)
    # (570000-28500) + 66000 + 44674
    assert data["grand_total_cents"] == 652174


# ===========================================================================
# Corner / calculations / proposal_small_subtotal_no_volume_discount
# ===========================================================================

def test_small_subtotal_earns_no_volume_discount():
    """PRD §3.2: "a subtotal below 5,000 dollars (that is, below 500,000 cents)
    earns no volume discount".
    PRD §3.2: "for RESIDENTIAL, 12,000 in NORTH, 10,000 in SOUTH, 13,000 in EAST,
    and 11,000 in WEST; for COMMERCIAL, 15,000 in NORTH, 13,000 in SOUTH, 16,000 in
    EAST, and 14,000 in WEST."

    Design: Corner/calculations/proposal_small_subtotal_no_volume_discount
    """
    client = create_client(billing_tier="RESIDENTIAL")
    project = create_project(client["id"], region_code="SOUTH")
    proposal, _ = setup_draft_proposal_with_items(
        project["id"],
        line_items=[dict(sku="C4-ACC", category="ACCESSORY", qty=1, unit_price_cents=100000)],
        labor_hours_estimate=2.5,
    )
    data = validate_success(api_client.send_proposal(project["id"], proposal["id"], DESIGNER))
    assert data["discount_cents"] == 0
    # SOUTH residential labor rate 10000 * 2.5h
    assert data["labor_cost_cents"] == 25000
    # tax = round_half_up(100000 * 0.0825) = 8250
    assert data["tax_cents"] == 8250
    # 100000 + 25000 + 8250
    assert data["grand_total_cents"] == 133250


# ===========================================================================
# Corner / calculations / line_item_remove_recomputes_subtotal_input_filtering
# ===========================================================================

def test_removed_line_item_excluded_from_subtotal():
    """PRD §3.2: "equipment_subtotal_cents is the sum, over every line item whose
    removed flag is false, of that item's qty multiplied by its unit_price_cents."
    PRD §3.2: "a designer may soft-remove a line item from a DRAFT proposal, which
    sets removed to true and excludes it from the equipment subtotal."

    Design: Corner/calculations/line_item_remove_recomputes_subtotal_input_filtering
    """
    client = create_client(billing_tier="RESIDENTIAL")
    project = create_project(client["id"], region_code="WEST")
    proposal, items = setup_draft_proposal_with_items(
        project["id"],
        line_items=[
            dict(sku="C4-CTRL", category="CONTROLLER", qty=1, unit_price_cents=250000),
            dict(sku="C4-SPK", category="AUDIO", qty=1, unit_price_cents=80000),
        ],
        labor_hours_estimate=1.0,
    )
    get_success_data(api_client.remove_line_item(
        project["id"], proposal["id"], items[1]["id"], DESIGNER))
    data = validate_success(api_client.send_proposal(project["id"], proposal["id"], DESIGNER))
    assert data["equipment_subtotal_cents"] == 250000


# ===========================================================================
# Corner / calculations / ip_pool_size_derived_for_slash24
# ===========================================================================

def test_ip_pool_size_derived_from_slash24_subnet():
    """PRD §3.4: "taking the prefix length after the slash in subnet_cidr, the pool
    size is two raised to the power of thirty-two minus that prefix length, then
    reduced by two to exclude the network address and the broadcast address."

    Design: Corner/calculations/ip_pool_size_derived_for_slash24
    """
    client = create_client()
    project = create_project(client["id"], region_code="WEST")
    data = validate_success(api_client.create_rack(
        project["id"], f.create_rack_payload(rack_units_total=10, subnet_cidr="10.20.0.0/24"),
        PM), expected_status=201)
    assert data["ip_pool_size"] == 254  # 2^8 - 2
    assert data["rack_units_used"] == 0


# ===========================================================================
# Corner / calculations / contract_consume_overage_floors_balance_at_zero
# ===========================================================================

def test_consume_overage_floors_balance_at_zero():
    """PRD §3.9: "The balance is floored at 0 and never goes negative, so overage
    hours beyond the prepaid bundle do not push the balance below zero."

    Design: Corner/calculations/contract_consume_overage_floors_balance_at_zero
    """
    project_id = _project_with_pending_contract(prepaid_hours=10, hourly_rate_cents=12000)
    validate_success(api_client.activate_contract(project_id, SUPPORT))
    data = validate_success(api_client.consume_contract(project_id, f.consume_payload(12), SUPPORT))
    assert data["consumed_hours"] == 12
    assert data["balance_cents"] == 0
