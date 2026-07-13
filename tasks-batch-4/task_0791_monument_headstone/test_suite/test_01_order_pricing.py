"""Order pricing: provisional vs final variants, tiered size multiplier, per-line
engraving rounding, and the computed contract/deposit fields at creation."""
import test_helpers as th


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / order_provisional_vs_final_merchandise
# ---------------------------------------------------------------------------
def test_approve_reprices_merchandise_under_final_variant(api):
    """PRD §3.3: "Approving a proof re-prices the marker under the **final variant**: the
    engraving charge is recomputed exactly as in §3.2 but drawing its line character counts from
    the approved proof's `line_char_counts` rather than the order's estimate, and the result is
    written to `merchandise_price_cents`."

    Design: Difficulty/dual_variant_calc/order_provisional_vs_final_merchandise
    """
    ctx = th.setup_deposit_paid_submitted_proof(
        deposit_cents=33880, proof_lines=[21, 31],
        cemetery_over={"allowed_materials": ["GRANITE", "BRONZE"], "permit_fee_cents": 12000},
    )
    th.validate_success(api.approve_design_proof(ctx["proof"]["id"], ctx["customer_headers"]))
    order = th.validate_success(api.get_order(ctx["order"]["id"], ctx["customer_headers"]))
    assert order["provisional_merchandise_cents"] == 27700, order
    assert order["merchandise_price_cents"] == 30251, order


def test_approve_final_merchandise_differs_and_recomputes_contract(api):
    """PRD §3.3: "The contract is then re-assembled — `contract_total_cents`,
    `deposit_amount_cents`, and `balance_amount_cents` recomputed from the new merchandise price
    by the same rules — and the order's `version` is incremented."

    Design: Difficulty/dual_variant_calc/order_provisional_vs_final_merchandise
    """
    ctx = th.setup_deposit_paid_submitted_proof(
        deposit_cents=33880, proof_lines=[21, 31],
        cemetery_over={"allowed_materials": ["GRANITE", "BRONZE"], "permit_fee_cents": 12000},
    )
    th.validate_success(api.approve_design_proof(ctx["proof"]["id"], ctx["customer_headers"]))
    order = th.validate_success(api.get_order(ctx["order"]["id"], ctx["customer_headers"]))
    assert order["contract_total_cents"] == 87251, order
    assert order["merchandise_price_cents"] != order["provisional_merchandise_cents"], order
    th.assert_order_money_invariant(order)


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / order_tiered_size_multiplier_pricing
# ---------------------------------------------------------------------------
def _large_marker_ctx():
    cem = th.make_cemetery(name="Grand Lawn", allowed_materials=["GRANITE"],
                           max_height_cm=120, max_width_cm=120, max_base_width_cm=120,
                           requires_permit=False, permit_fee_cents=0)
    cust = th.make_customer(full_name="Sam Roe", email="sam@example.com")
    return cem, cust


def test_large_size_tier_applies_125_percent_multiplier(api):
    """PRD §3.2: "A size tier multiplier is then applied based on face area: a face area of at
    least 6000 square centimetres takes a 125 percent multiplier, a face area of at least 3000
    but under 6000 takes a 110 percent multiplier, and anything below 3000 takes a 100 percent
    multiplier (no uplift)."

    Design: Difficulty/combinatorial_formula/order_tiered_size_multiplier_pricing
    """
    cem, cust = _large_marker_ctx()
    payload = th.create_order_payload(cust["id"], cem["id"], height_cm=80, width_cm=80,
                                      base_width_cm=60, estimated_line_char_counts=[21, 31])
    order = th.validate_success(
        api.create_order(payload, th.make_customer_headers(cust["id"])), 201
    )
    assert order["provisional_merchandise_cents"] == 75051, order


def test_large_size_tier_price_persisted_on_order(api):
    """PRD §3.2: "The raw material component multiplied by the tier percentage and divided by
    one hundred is rounded half up to whole cents to give the priced material figure. The
    merchandise price is that priced material figure plus the summed engraving charge."

    Design: Difficulty/combinatorial_formula/order_tiered_size_multiplier_pricing
    """
    cem, cust = _large_marker_ctx()
    payload = th.create_order_payload(cust["id"], cem["id"], height_cm=80, width_cm=80,
                                      base_width_cm=60, estimated_line_char_counts=[21, 31])
    created = th.validate_success(
        api.create_order(payload, th.make_customer_headers(cust["id"])), 201
    )
    order = th.validate_success(api.get_order(created["id"], th.make_customer_headers(cust["id"])))
    assert order["provisional_merchandise_cents"] == 75051, order


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / engraving_per_line_rounding_charge
# ---------------------------------------------------------------------------
def _per_line_ctx():
    cem = th.make_cemetery(name="Restful Pines", allowed_materials=["GRANITE"],
                           max_height_cm=90, max_width_cm=75, max_base_width_cm=80,
                           requires_permit=False, permit_fee_cents=0)
    cust = th.make_customer(full_name="Sam Roe", email="sam@example.com")
    return cem, cust


def test_engraving_rounds_per_line_before_summation(api):
    """PRD §3.2: "The rounding happens on each line before summation, not once on the total;
    summing the character counts first and rounding once would yield a different, incorrect
    figure."

    Design: Difficulty/combinatorial_formula/engraving_per_line_rounding_charge
    """
    cem, cust = _per_line_ctx()
    payload = th.create_order_payload(cust["id"], cem["id"], height_cm=60, width_cm=40,
                                      base_width_cm=50, estimated_line_char_counts=[21, 31])
    order = th.validate_success(
        api.create_order(payload, th.make_customer_headers(cust["id"])), 201
    )
    assert order["provisional_merchandise_cents"] == 30251, order


def test_engraving_per_line_rounding_persisted(api):
    """PRD §3.2: "Each engraving line is priced by multiplying its character count by that rate
    and then applying a 15 percent volume discount — that is, retaining 85 percent of the line's
    gross — and rounding the result half up to whole cents."

    Design: Difficulty/combinatorial_formula/engraving_per_line_rounding_charge
    """
    cem, cust = _per_line_ctx()
    payload = th.create_order_payload(cust["id"], cem["id"], height_cm=60, width_cm=40,
                                      base_width_cm=50, estimated_line_char_counts=[21, 31])
    created = th.validate_success(
        api.create_order(payload, th.make_customer_headers(cust["id"])), 201
    )
    order = th.validate_success(api.get_order(created["id"], th.make_customer_headers(cust["id"])))
    assert order["provisional_merchandise_cents"] == 30251, order


# ---------------------------------------------------------------------------
# Corner: entities / order_create_returns_computed_pricing
# ---------------------------------------------------------------------------
def test_order_create_returns_computed_pricing_and_initial_states(api):
    """PRD §3.2: "The `deposit_amount_cents` is 40 percent of the contract total, rounded half up
    to whole cents in a single rounding step. The `balance_amount_cents` is the exact remainder —
    the contract total minus the deposit — with no independent rounding, so that deposit plus
    balance always equals the contract total exactly."
    PRD §3.2: "The order is born with `production_status` at `DRAFTING` and `payment_status` at
    `UNPAID`."

    Design: Corner/entities/order_create_returns_computed_pricing
    """
    cem = th.make_cemetery(allowed_materials=["GRANITE"], requires_permit=True, permit_fee_cents=12000)
    cust = th.make_customer()
    payload = th.create_order_payload(cust["id"], cem["id"])
    order = th.validate_success(
        api.create_order(payload, th.make_customer_headers(cust["id"])), 201
    )
    th.assert_order(order)
    assert order["production_status"] == "DRAFTING", order
    assert order["payment_status"] == "UNPAID", order
    assert order["provisional_merchandise_cents"] == 27700, order
    assert order["contract_total_cents"] == 84700, order
    assert order["deposit_amount_cents"] == 33880, order
    assert order["balance_amount_cents"] == 50820, order


# ---------------------------------------------------------------------------
# Corner: calculations / pet_marble_provisional_pricing_correct
# ---------------------------------------------------------------------------
def test_pet_marble_provisional_pricing_correct(api):
    """PRD §3.2: "That face area is multiplied by the per-square-centimetre material rate — 8
    cents for `GRANITE`, 15 cents for `BRONZE`, and 11 cents for `MARBLE` — to give a raw
    material component."

    Design: Corner/calculations/pet_marble_provisional_pricing_correct
    """
    cem = th.make_cemetery(name="Quiet Meadow", allowed_materials=["MARBLE"],
                           requires_permit=False, permit_fee_cents=0)
    cust = th.make_customer(full_name="Pat Fox", email="pat@example.com")
    payload = th.create_order_payload(cust["id"], cem["id"], subject_type="PET", material="MARBLE",
                                      height_cm=50, width_cm=40, base_width_cm=45,
                                      estimated_line_char_counts=[10, 15])
    order = th.validate_success(
        api.create_order(payload, th.make_customer_headers(cust["id"])), 201
    )
    assert order["provisional_merchandise_cents"] == 25825, order
    assert order["contract_total_cents"] == 70825, order
    assert order["deposit_amount_cents"] == 28330, order
