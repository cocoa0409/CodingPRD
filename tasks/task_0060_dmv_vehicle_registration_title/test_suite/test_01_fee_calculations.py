"""Fee assessment calculations: use tax, registration fee, REAL ID surcharge, total."""
from test_helpers import (
    api_client,
    validate_success,
    TEST_USERS,
    create_owner_payload,
    create_vehicle_payload,
    create_registration_payload,
    create_fee_assessment_payload,
    set_clock,
    create_owner,
    issue_clear_title,
)

CLERK = TEST_USERS["clerk_headers"]


def _assess_for(owner_overrides, vehicle_overrides, registration_overrides):
    """Create owner + vehicle + registration and assess fees. Returns the FeeAssessment data."""
    owner = validate_success(
        api_client.create_owner(create_owner_payload(**owner_overrides), CLERK), 201
    )
    veh = validate_success(
        api_client.create_vehicle(
            create_vehicle_payload(owner["id"], **vehicle_overrides), CLERK
        ),
        201,
    )
    reg = validate_success(
        api_client.create_registration(
            create_registration_payload(veh["id"], owner["id"], **registration_overrides), CLERK
        ),
        201,
    )
    return validate_success(
        api_client.create_fee_assessment(create_fee_assessment_payload(reg["id"]), CLERK), 201
    )


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc/use_tax_initial_vs_transfer_cap_divergence
# ---------------------------------------------------------------------------
def test_use_tax_initial_full_rate_no_cap():
    """PRD §3.5: "Multiply the basis by this combined rate and round that single product
    to the nearest integer cent, half-up. Then apply the transfer cap: if the registration's
    `registration_type` is `TRANSFER`, the use tax is the smaller of the rounded amount and
    the private-party cap of 150000 cents; an `INITIAL` registration is taxed at the full
    rounded amount with no cap."

    KING combined rate 0.090 on 5,000,000c basis = 450000; INITIAL is uncapped.

    Design: Difficulty/dual_variant_calc/use_tax_initial_vs_transfer_cap_divergence
    """
    fa = _assess_for(
        {"residence_county_code": "KING"},
        {"purchase_price_cents": 5000000, "msrp_cents": 5000000, "model_year": 2024},
        {"registration_type": "INITIAL"},
    )
    assert fa["use_tax_cents"] == 450000, f"expected 450000, got {fa['use_tax_cents']}"


def test_use_tax_transfer_clamped_to_private_party_cap():
    """PRD §3.5: "if the registration's `registration_type` is `TRANSFER`, the use tax is
    the smaller of the rounded amount and the private-party cap of 150000 cents".

    Same KING/5,000,000c inputs (uncapped 450000) but a TRANSFER registration clamps to 150000.
    Build a CLEAR title so the TRANSFER application/registration is legal.

    Design: Difficulty/dual_variant_calc/use_tax_initial_vs_transfer_cap_divergence
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = create_owner(residence_county_code="KING")
    veh = validate_success(
        api_client.create_vehicle(
            create_vehicle_payload(
                owner["id"], purchase_price_cents=5000000, msrp_cents=5000000, model_year=2024
            ),
            CLERK,
        ),
        201,
    )
    # Verify VIN and issue a CLEAR title so the vehicle.title_status is CLEAR for TRANSFER.
    from test_helpers import create_vin_verification_payload
    validate_success(
        api_client.create_vin_verification(
            create_vin_verification_payload(veh["id"], veh["vin"], "MATCH"), CLERK
        ),
        201,
    )
    issue_clear_title(veh["id"], owner["id"], "INITIAL")
    reg = validate_success(
        api_client.create_registration(
            create_registration_payload(veh["id"], owner["id"], "TRANSFER"), CLERK
        ),
        201,
    )
    fa = validate_success(
        api_client.create_fee_assessment(create_fee_assessment_payload(reg["id"]), CLERK), 201
    )
    assert fa["use_tax_cents"] == 150000, f"expected cap 150000, got {fa['use_tax_cents']}"


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/registration_fee_round_then_add_order
# ---------------------------------------------------------------------------
def test_registration_fee_round_then_add_passenger_band1():
    """PRD §3.5: "Multiply the vehicle's `msrp_cents` by the selected rate and round that
    product to the nearest integer cent, half-up, to obtain the depreciation component. Then
    add the flat weight fee chosen by `vehicle_class`: 4300 cents for `PASSENGER` ... The order
    is binding — the depreciation product is rounded first, and only then is the integer weight
    fee added."

    msrp 3,200,000c, age 2 (band rate 0.0090): round(28800.0)=28800 + 4300 = 33100.

    Design: Difficulty/combinatorial_formula/registration_fee_round_then_add_order
    """
    fa = _assess_for(
        {"residence_county_code": "KING"},
        {"msrp_cents": 3200000, "purchase_price_cents": 3000000, "model_year": 2024,
         "vehicle_class": "PASSENGER"},
        {"registration_type": "INITIAL"},
    )
    assert fa["registration_fee_cents"] == 33100, f"expected 33100, got {fa['registration_fee_cents']}"


def test_registration_fee_components_sum_into_total():
    """PRD §3.5: "Finally, `total_cents` is the plain integer sum of `use_tax_cents`,
    `registration_fee_cents`, and `real_id_surcharge_cents`, with no further rounding."

    The pinned round-then-add registration_fee (33100) is one summand of the integer total.

    Design: Difficulty/combinatorial_formula/registration_fee_round_then_add_order
    """
    fa = _assess_for(
        {"residence_county_code": "KING"},
        {"msrp_cents": 3200000, "purchase_price_cents": 3000000, "model_year": 2024,
         "vehicle_class": "PASSENGER"},
        {"registration_type": "INITIAL"},
    )
    assert fa["registration_fee_cents"] == 33100
    assert fa["total_cents"] == (
        fa["use_tax_cents"] + fa["registration_fee_cents"] + fa["real_id_surcharge_cents"]
    )


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/use_tax_three_input_nonlinear_cap_branch
# ---------------------------------------------------------------------------
def test_use_tax_pierce_county_combined_rate():
    """PRD §3.5: "The combined tax rate is the state base rate of 0.065 plus a county add-on
    selected from the owner's `residence_county_code`: 0.025 for county code `KING`, 0.014 for
    county code `PIERCE`, and 0.010 for any other county code."

    PIERCE combined rate 0.079 on 2,000,000c = 158000; INITIAL is below the cap so uncapped.

    Design: Difficulty/combinatorial_formula/use_tax_three_input_nonlinear_cap_branch
    """
    fa = _assess_for(
        {"residence_county_code": "PIERCE"},
        {"purchase_price_cents": 2000000, "msrp_cents": 2000000, "model_year": 2024},
        {"registration_type": "INITIAL"},
    )
    assert fa["use_tax_cents"] == 158000, f"expected 158000, got {fa['use_tax_cents']}"


def test_use_tax_initial_below_cap_uncapped():
    """PRD §3.5: "an `INITIAL` registration is taxed at the full rounded amount with no cap."

    PIERCE 2,000,000c yields 158000 (above 150000 cap) but INITIAL is uncapped, so it is NOT
    clamped — the cap branch is not taken for INITIAL.

    Design: Difficulty/combinatorial_formula/use_tax_three_input_nonlinear_cap_branch
    """
    fa = _assess_for(
        {"residence_county_code": "PIERCE"},
        {"purchase_price_cents": 2000000, "msrp_cents": 2000000, "model_year": 2024},
        {"registration_type": "INITIAL"},
    )
    assert fa["use_tax_cents"] == 158000


# ---------------------------------------------------------------------------
# Corner/calculations/registration_fee_age_band_boundary_band1_vs_band2
# ---------------------------------------------------------------------------
def test_registration_fee_age_band1_at_age_3():
    """PRD §3.5: "an age of at most 3 years uses 0.0090; an age of at most 7 years uses 0.0060".

    model_year 2023 -> age 3 -> band 0.0090: round(2,000,000*0.0090)=18000 + 4300 = 22300.

    Design: Corner/calculations/registration_fee_age_band_boundary_band1_vs_band2
    """
    fa = _assess_for(
        {"residence_county_code": "KING"},
        {"msrp_cents": 2000000, "purchase_price_cents": 2000000, "model_year": 2023,
         "vehicle_class": "PASSENGER"},
        {"registration_type": "INITIAL"},
    )
    assert fa["registration_fee_cents"] == 22300, f"expected 22300, got {fa['registration_fee_cents']}"


def test_registration_fee_age_band2_at_age_4():
    """PRD §3.5: "an age of at most 7 years uses 0.0060".

    model_year 2022 -> age 4 -> band 0.0060: round(2,000,000*0.0060)=12000 + 4300 = 16300.

    Design: Corner/calculations/registration_fee_age_band_boundary_band1_vs_band2
    """
    fa = _assess_for(
        {"residence_county_code": "KING"},
        {"msrp_cents": 2000000, "purchase_price_cents": 2000000, "model_year": 2022,
         "vehicle_class": "PASSENGER"},
        {"registration_type": "INITIAL"},
    )
    assert fa["registration_fee_cents"] == 16300, f"expected 16300, got {fa['registration_fee_cents']}"


# ---------------------------------------------------------------------------
# Corner/calculations/assessment_total_with_real_id_surcharge
# ---------------------------------------------------------------------------
def test_assessment_total_bundles_real_id_surcharge():
    """PRD §3.5: "`real_id_surcharge_cents` is 3000 cents when the registration's
    `bundle_real_id` is true, and 0 otherwise. Finally, `total_cents` is the plain integer
    sum of `use_tax_cents`, `registration_fee_cents`, and `real_id_surcharge_cents`, with no
    further rounding."

    KING 3,000,000c (use_tax 270000) + msrp 3,200,000c age 2 (reg_fee 33100) + surcharge 3000
    = total 306100.

    Design: Corner/calculations/assessment_total_with_real_id_surcharge
    """
    fa = _assess_for(
        {"residence_county_code": "KING"},
        {"purchase_price_cents": 3000000, "msrp_cents": 3200000, "model_year": 2024,
         "vehicle_class": "PASSENGER"},
        {"registration_type": "INITIAL", "bundle_real_id": True},
    )
    assert fa["use_tax_cents"] == 270000
    assert fa["registration_fee_cents"] == 33100
    assert fa["real_id_surcharge_cents"] == 3000
    assert fa["total_cents"] == 306100, f"expected 306100, got {fa['total_cents']}"


# ---------------------------------------------------------------------------
# Corner/consistency_model/immediate_consistency_fee_total_in_create_response
# ---------------------------------------------------------------------------
def test_fee_total_computed_in_create_response():
    """PRD §3.5: "A `FeeAssessment` is created for a registration by supplying its
    `registration_id`; on creation the system computes four monetary fields — `use_tax_cents`,
    `registration_fee_cents`, `real_id_surcharge_cents`, and `total_cents` — and sets `status`
    to `ASSESSED`."

    KING 3,000,000c (use_tax 270000) + reg_fee 33100 + no bundle = total 303100, returned in
    the POST response itself.

    Design: Corner/consistency_model/immediate_consistency_fee_total_in_create_response
    """
    fa = _assess_for(
        {"residence_county_code": "KING"},
        {"purchase_price_cents": 3000000, "msrp_cents": 3200000, "model_year": 2024,
         "vehicle_class": "PASSENGER"},
        {"registration_type": "INITIAL"},
    )
    assert fa["total_cents"] == 303100, f"expected 303100, got {fa['total_cents']}"
    assert fa["status"] == "ASSESSED"
