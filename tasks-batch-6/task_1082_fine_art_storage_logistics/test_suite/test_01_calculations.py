"""Calculation rules: storage fees, appraisal valuation, insurance premium,
invoice totals, transport charge."""
from test_helpers import (
    validate_success, get_success_data,
    set_clock, make_client, make_vault, make_artwork, make_appraisal,
    make_crate, make_crew,
    placement_payload, appraisal_payload, policy_payload, invoice_payload,
    transport_job_payload,
    artwork_version,
    REG, COORD, BILL,
    api_client as api,
)


# ==========================================================================
# Storage fee — provisional vs final (dual variant)
# ==========================================================================
def test_storage_provisional_fee_projected_at_creation():
    """PRD §3.2: "It multiplies that day count by the vault's climate daily rate
    — 500 cents per day for an `AMBIENT` vault, 800 cents per day for `COOL`, and
    1,200 cents per day for `COLD` — and by the artwork's size multiplier — 1.0
    for `SMALL`, 1.5 for `MEDIUM`, and 2.0 for `LARGE` — and rounds the product
    half-up to whole cents, storing it as `provisional_fee_cents`."

    Design: Difficulty/dual_variant_calc/storage_fee_provisional_vs_final
    """
    set_clock("2026-05-01T00:00:00Z")
    c = make_client()
    v = make_vault(climate_class="AMBIENT", capacity_slots=5)
    a = make_artwork(c["id"], size_class="MEDIUM", climate_class="AMBIENT")
    resp = api.create_placement(
        placement_payload(a["id"], v["id"],
                          start_at="2026-05-01T00:00:00Z",
                          scheduled_end_at="2026-05-11T00:00:00Z"), REG)
    data = validate_success(resp, 201)
    # 10 days * 500 cents * 1.5 (MEDIUM) = 7500
    assert data["provisional_fee_cents"] == 7500, data
    assert data["status"] == "ACTIVE"


def test_storage_final_fee_on_early_release():
    """PRD §3.2: "Release sets `released_at` to the current logical-clock time and
    computes `final_fee_cents` by the same formula as the provisional fee, except
    the day count runs chronologically from `start_at` to `released_at` (again
    rounding any partial day up) rather than to the scheduled end."

    Design: Difficulty/dual_variant_calc/storage_fee_provisional_vs_final
    """
    set_clock("2026-05-01T00:00:00Z")
    c = make_client()
    v = make_vault(climate_class="AMBIENT", capacity_slots=5)
    a = make_artwork(c["id"], size_class="MEDIUM", climate_class="AMBIENT")
    p = get_success_data(api.create_placement(
        placement_payload(a["id"], v["id"],
                          start_at="2026-05-01T00:00:00Z",
                          scheduled_end_at="2026-05-11T00:00:00Z"), REG))
    set_clock("2026-05-06T00:00:00Z")
    data = validate_success(api.transition_placement(p["id"], {"to_status": "RELEASED"}, REG))
    # chronological 5 days * 500 * 1.5 = 3750
    assert data["final_fee_cents"] == 3750, data
    assert data["status"] == "RELEASED"


# ==========================================================================
# Appraisal value — fair market vs replacement (dual variant)
# ==========================================================================
def test_fair_market_appraisal_equals_comparable_base():
    """PRD §3.5: "Under the `FAIR_MARKET` method the appraised value equals
    `comparable_base_cents` outright, and the `replacement_multiplier` and
    `restoration_reserve_cents` inputs are ignored."

    Design: Difficulty/dual_variant_calc/appraisal_fair_market_vs_replacement
    """
    c = make_client()
    a = make_artwork(c["id"], size_class="SMALL", fragility_class="LOW", climate_class="COOL")
    v = artwork_version(a["id"])
    data = validate_success(api.create_appraisal(
        appraisal_payload(a["id"], v, method="FAIR_MARKET", comparable_base_cents=1000000), REG), 201)
    assert data["appraised_value_cents"] == 1000000, data


def test_replacement_appraisal_scales_and_adds_reserve():
    """PRD §3.5: "Under the `REPLACEMENT` method the appraised value is
    `comparable_base_cents` multiplied by the `replacement_multiplier` (which
    defaults to 1.0), rounded half-up to whole cents, with the
    `restoration_reserve_cents` reserve (defaulting to 0) then added."

    Design: Difficulty/dual_variant_calc/appraisal_fair_market_vs_replacement
    """
    c = make_client()
    a = make_artwork(c["id"], size_class="SMALL", fragility_class="LOW", climate_class="COOL")
    v = artwork_version(a["id"])
    data = validate_success(api.create_appraisal(
        appraisal_payload(a["id"], v, method="REPLACEMENT", comparable_base_cents=1000000,
                          replacement_multiplier=1.25, restoration_reserve_cents=50000), REG), 201)
    # round(1000000 * 1.25) + 50000 = 1300000
    assert data["appraised_value_cents"] == 1300000, data


# ==========================================================================
# Insurance premium — tiered, non-linear combination
# ==========================================================================
def test_premium_tiered_combination_on_creation():
    """PRD §3.5: "That figure is then scaled by the coverage multiplier — 1.0 for
    `STORAGE_ONLY`, 1.5 for `TRANSIT`, 2.0 for `ALL_RISK` — by the artwork's
    fragility multiplier — 1.0 for `LOW`, 1.25 for `MEDIUM`, 1.5 for `HIGH` — and
    by the coverage duration expressed as a fraction of a year, namely the number
    of days from `effective_start` to `effective_end` divided by 365."

    Design: Difficulty/combinatorial_formula/insurance_premium_tiered_nonlinear
    """
    c = make_client(client_type="DEALER")
    a = make_artwork(c["id"], size_class="LARGE", fragility_class="MEDIUM", climate_class="AMBIENT")
    v = artwork_version(a["id"])
    data = validate_success(api.create_policy(
        policy_payload(a["id"], v, coverage_type="ALL_RISK", insured_value_cents=1300000,
                       effective_start="2026-05-01T00:00:00Z",
                       effective_end="2027-05-01T00:00:00Z"), REG), 201)
    # rate 150bps (1.3M in mid band): 1300000*150/10000 = 19500;
    # *2.0(ALL_RISK)*1.25(MEDIUM)*(365/365) = 48750; above 5000 floor.
    assert data["premium_cents"] == 48750, data


def test_premium_tiered_value_persisted_on_get():
    """PRD §3.5: "First a rate in basis points is selected from the insured value:
    200 basis points when `insured_value_cents` is at most 500,000, otherwise 150
    basis points when it is at most 5,000,000, otherwise 100 basis points."

    Design: Difficulty/combinatorial_formula/insurance_premium_tiered_nonlinear
    """
    c = make_client(client_type="DEALER")
    a = make_artwork(c["id"], size_class="LARGE", fragility_class="MEDIUM", climate_class="AMBIENT")
    v = artwork_version(a["id"])
    created = get_success_data(api.create_policy(
        policy_payload(a["id"], v, coverage_type="ALL_RISK", insured_value_cents=1300000,
                       effective_start="2026-05-01T00:00:00Z",
                       effective_end="2027-05-01T00:00:00Z"), REG))
    data = validate_success(api.get_policy(created["id"], REG))
    assert data["premium_cents"] == 48750, data


def test_premium_min_floor_applied():
    """PRD §3.5: "The scaled amount is rounded half-up to whole cents, and the
    stored `premium_cents` is the greater of that rounded amount and the floor
    premium of 5,000 cents."

    Design: Corner/calculations/insurance_premium_min_floor_applied
    """
    c = make_client(client_type="INDIVIDUAL")
    a = make_artwork(c["id"], size_class="SMALL", fragility_class="LOW", climate_class="AMBIENT")
    v = artwork_version(a["id"])
    data = validate_success(api.create_policy(
        policy_payload(a["id"], v, coverage_type="STORAGE_ONLY", insured_value_cents=100000,
                       effective_start="2026-05-01T00:00:00Z",
                       effective_end="2026-05-02T00:00:00Z"), REG), 201)
    # 100000*200/10000=2000; *1*1*(1/365) ~= 5.48 -> 5; floored to 5000.
    assert data["premium_cents"] == 5000, data


# ==========================================================================
# Invoice total — pinned sum-then-tax rounding order
# ==========================================================================
def test_invoice_subtotal_sums_line_items():
    """PRD §3.8: "The `subtotal_cents` is the sum of the whole-cent `amount_cents`
    of every line item."

    Design: Difficulty/combinatorial_formula/invoice_tax_rounding_order
    """
    c = make_client()
    data = validate_success(api.create_invoice(
        invoice_payload(c["id"], manual_line_items=[
            {"description": "Storage", "amount_cents": 7505},
            {"description": "Handling", "amount_cents": 3003}]), BILL), 201)
    assert data["subtotal_cents"] == 10508, data


def test_invoice_tax_computed_once_on_subtotal():
    """PRD §3.8: "The `tax_cents` is the subtotal multiplied by the tax rate of
    8.75 percent, rounded half-up to whole cents once, on the summed subtotal —
    tax is never computed or rounded per line item."

    Design: Difficulty/combinatorial_formula/invoice_tax_rounding_order
    """
    c = make_client()
    data = validate_success(api.create_invoice(
        invoice_payload(c["id"], manual_line_items=[
            {"description": "Storage", "amount_cents": 7505},
            {"description": "Handling", "amount_cents": 3003}]), BILL), 201)
    # round(10508 * 0.0875) = 919 (sum-then-tax), NOT 657+263=920 (per-line).
    assert data["tax_cents"] == 919, data
    assert data["total_cents"] == 11427, data


# ==========================================================================
# Transport charge — estimated at schedule with rigging surcharge
# ==========================================================================
def test_transport_charge_estimated_with_rigging_surcharge():
    """PRD §3.4: "the estimated labor cost is `estimated_hours` multiplied by the
    crew hourly rate of 9,000 cents per hour, rounded half-up to whole cents, and
    then a flat rigging surcharge of 25,000 cents is added when `requires_rigging`
    is true (and nothing is added when it is false)."

    Design: Corner/calculations/transport_charge_estimated_with_rigging_surcharge
    """
    c = make_client(client_type="DEALER")
    a = make_artwork(c["id"])
    crate = make_crate(a["id"])
    crew = make_crew(certification_level="STANDARD", crew_size=2)
    data = validate_success(api.create_transport_job(
        transport_job_payload(a["id"], crate["id"], crew["id"],
                              scheduled_start="2026-06-01T09:00:00Z",
                              scheduled_end="2026-06-01T12:00:00Z",
                              requires_rigging=True, estimated_hours=3), COORD), 201)
    # round(3*9000)+25000 = 52000
    assert data["transport_charge_cents"] == 52000, data


# ==========================================================================
# Derived-field reconciliation: artwork.appraised_value_cents
# ==========================================================================
def test_artwork_appraised_value_reconciles_from_appraisal():
    """PRD §3.5: "any prior `FINALIZED` appraisal for the same artwork transitions
    to `SUPERSEDED`; and the artwork's own `appraised_value_cents` is set to the
    new value while its `version` is incremented by one".

    Design: Corner/entities/artwork_appraised_value_reconciles_from_appraisal
    """
    c = make_client()
    a = make_artwork(c["id"], size_class="SMALL", fragility_class="LOW")
    make_appraisal(a["id"], method="FAIR_MARKET", comparable_base_cents=750000)
    data = validate_success(api.get_artwork(a["id"], REG))
    assert data["appraised_value_cents"] == 750000, data
