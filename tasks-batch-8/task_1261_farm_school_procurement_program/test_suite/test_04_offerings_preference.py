"""Offerings: computed geography fields, season containment, lifecycle guards,
and the LINEAR/TIERED preference-model variants."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_offering,
    create_agreement,
    create_approved_farm,
    create_farm,
    create_offering,
    create_product,
    create_program_year,
    create_verified_offering,
    make_farm_manager_headers,
    sign_agreement,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["admin_headers"]


def _two_model_years():
    yr_linear = create_program_year(
        school_year_label="YL", preference_model="LINEAR"
    )
    yr_tiered = create_program_year(
        school_year_label="YT", preference_model="TIERED"
    )
    return yr_linear, yr_tiered


def test_preference_model_linear_vs_tiered_divergence(api):
    """PRD section 3.3: "The two models legitimately disagree: a farm 30 miles
    out under a 100-mile radius scores 70 under `LINEAR` and 75 under
    `TIERED`."

    Design: Difficulty/dual_variant_calc/preference_model_linear_vs_tiered_divergence
    """
    yr_linear, yr_tiered = _two_model_years()
    product = create_product()
    farm = create_approved_farm(distance_miles_to_hub=30)

    off_l = validate_success(
        create_offering(farm["id"], yr_linear["id"], product["id"]), 201
    )
    off_t = validate_success(
        create_offering(farm["id"], yr_tiered["id"], product["id"]), 201
    )
    assert_offering(off_l)
    assert_offering(off_t)
    assert off_l["preference_points"] == 70, (
        f"LINEAR: 100 - 30 = 70 expected, got {off_l['preference_points']}"
    )
    assert off_t["preference_points"] == 75, (
        f"TIERED: 25 < 30 <= 50 band gives 75 expected, got {off_t['preference_points']}"
    )


def test_preference_model_both_variants_mark_local_eligible(api):
    """PRD section 3.3: "The `is_local_eligible` flag records whether the
    farm's `distance_miles_to_hub` is at most the program year's
    `local_radius_miles`."
    PRD section 3.3: "Both pinned values are immutable snapshots of the farm
    and year as they stood at creation."

    Design: Difficulty/dual_variant_calc/preference_model_linear_vs_tiered_divergence
    """
    yr_linear, yr_tiered = _two_model_years()
    product = create_product()
    farm = create_approved_farm(distance_miles_to_hub=30)

    off_l = validate_success(
        create_offering(farm["id"], yr_linear["id"], product["id"]), 201
    )
    off_t = validate_success(
        create_offering(farm["id"], yr_tiered["id"], product["id"]), 201
    )
    # Re-read: the pinned snapshot must persist on later reads.
    read_l = validate_success(api.get_offering(off_l["id"], ADMIN), 200)
    read_t = validate_success(api.get_offering(off_t["id"], ADMIN), 200)
    assert read_l["is_local_eligible"] is True
    assert read_t["is_local_eligible"] is True
    assert read_l["preference_points"] == 70
    assert read_t["preference_points"] == 75


def test_tiered_band_edge_inclusive_at_25_miles(api):
    """PRD section 3.3: "`TIERED` instead scores by fixed bands: at most 25
    miles earns 100 points, more than 25 and at most 50 miles earns 75, more
    than 50 and at most 100 miles earns 50, and more than 100 miles but still
    within the radius earns 25."

    Design: Difficulty/combinatorial_formula/tiered_band_selection_mode_a
    """
    year = create_program_year(preference_model="TIERED")
    product = create_product()
    farm25 = create_approved_farm(legal_name="Farm25", distance_miles_to_hub=25)
    farm26 = create_approved_farm(legal_name="Farm26", distance_miles_to_hub=26)

    off25 = validate_success(
        create_offering(farm25["id"], year["id"], product["id"]), 201
    )
    off26 = validate_success(
        create_offering(farm26["id"], year["id"], product["id"]), 201
    )
    assert off25["preference_points"] == 100, (
        "at most 25 miles earns 100 points (band edge inclusive)"
    )
    assert off26["preference_points"] == 75, (
        "more than 25 and at most 50 miles earns 75"
    )


def test_tiered_band_edge_points_pinned_on_read(api):
    """PRD section 3.3: "Both pinned values are immutable snapshots of the farm
    and year as they stood at creation."

    Design: Difficulty/combinatorial_formula/tiered_band_selection_mode_a
    """
    year = create_program_year(preference_model="TIERED")
    product = create_product()
    farm25 = create_approved_farm(legal_name="Farm25", distance_miles_to_hub=25)
    farm26 = create_approved_farm(legal_name="Farm26", distance_miles_to_hub=26)

    off25 = validate_success(
        create_offering(farm25["id"], year["id"], product["id"]), 201
    )
    off26 = validate_success(
        create_offering(farm26["id"], year["id"], product["id"]), 201
    )
    read25 = validate_success(api.get_offering(off25["id"], ADMIN), 200)
    read26 = validate_success(api.get_offering(off26["id"], ADMIN), 200)
    assert read25["preference_points"] == 100
    assert read26["preference_points"] == 75
    assert read25["is_local_eligible"] is True
    assert read26["is_local_eligible"] is True


def test_offering_beyond_radius_not_local_zero_points(api):
    """PRD section 3.3: "When the farm lies beyond the radius, the flag is
    false and the score is zero under both models."

    Design: Corner/entities/ent_offering_computed_fields_server_side
    """
    year = create_program_year()
    product = create_product()
    farm = create_approved_farm(legal_name="Far Away", distance_miles_to_hub=150)
    offering = validate_success(
        create_offering(farm["id"], year["id"], product["id"]), 201
    )
    assert_offering(offering)
    assert offering["is_local_eligible"] is False
    assert offering["preference_points"] == 0


def test_offering_window_outside_season_rejected(api):
    """PRD section 3.3: "The harvest window must lie entirely inside the
    product's season under the same containment rule, failing which creation is
    rejected with `ERR_HARVEST_WINDOW_OUTSIDE_SEASON`."
    PRD section 2.8: "for a window from a start week to an end week, a given
    week lies inside the window either when the start does not exceed the end
    and the week falls between them inclusively, or — in the wraparound case,
    when the start exceeds the end — when the week is at least the start or at
    most the end."

    Design: Corner/entities/ent_offering_window_outside_season_rejected
    """
    year = create_program_year()
    prod1 = create_product(name="Tomato", season_start_week=1, season_end_week=20)
    prod2 = create_product(name="Kale", season_start_week=48, season_end_week=8)
    farm = create_approved_farm()

    resp = create_offering(
        farm["id"], year["id"], prod1["id"],
        harvest_start_week=21, harvest_end_week=25,
    )
    validate_error(resp, ApiErrorId.ERR_HARVEST_WINDOW_OUTSIDE_SEASON)

    # Wraparound season 48..8 contains the wraparound window 50..5.
    offering = validate_success(
        create_offering(
            farm["id"], year["id"], prod2["id"],
            harvest_start_week=50, harvest_end_week=5,
        ),
        201,
    )
    assert_offering(offering)


def test_offering_state_family_errors(api):
    """PRD section 3.3: "Creation is gated on all three parents: the program
    year must be `OPEN`, the farm must be `APPROVED` (`ERR_FARM_NOT_APPROVED`),
    and the product must be `ACTIVE` (`ERR_PRODUCT_NOT_ACTIVE`)."
    PRD section 3.3: "both demand the offering currently be `SUBMITTED`,
    failing which `ERR_OFFERING_NOT_VERIFIABLE`."
    PRD section 3.3: "The farm's `FarmManager` submits it (`DRAFT` →
    `SUBMITTED`), which fails with `ERR_OFFERING_NOT_SUBMITTABLE` from any
    other state"
    PRD section 3.3: "The farm may also withdraw an offering from `DRAFT`,
    `SUBMITTED`, or `VERIFIED` — any other state draws
    `ERR_OFFERING_NOT_WITHDRAWABLE`"

    Design: Corner/state_machines/sm_offering_state_family_errors
    """
    year = create_program_year()
    product = create_product()
    farm1 = create_approved_farm(legal_name="Farm1")
    farm2 = create_farm(legal_name="Farm2")  # stays APPLIED

    # Offering creation requires an APPROVED farm.
    resp = create_offering(farm2["id"], year["id"], product["id"])
    validate_error(resp, ApiErrorId.ERR_FARM_NOT_APPROVED)

    offering = validate_success(
        create_offering(farm1["id"], year["id"], product["id"]), 201
    )
    headers1 = make_farm_manager_headers(farm1["id"])

    # Verify requires SUBMITTED.
    resp = api.verify_offering(offering["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_OFFERING_NOT_VERIFIABLE)

    # Submit is single-shot.
    validate_success(api.submit_offering(offering["id"], headers1), 200)
    resp = api.submit_offering(offering["id"], headers1)
    validate_error(resp, ApiErrorId.ERR_OFFERING_NOT_SUBMITTABLE)

    # Withdraw from terminal REJECTED fails.
    validate_success(
        api.reject_offering(offering["id"], ADMIN, reason="price too high"), 200
    )
    resp = api.withdraw_offering(offering["id"], headers1)
    validate_error(resp, ApiErrorId.ERR_OFFERING_NOT_WITHDRAWABLE)

    # Only an ACTIVE product may anchor a new offering.
    validate_success(api.discontinue_product(product["id"], ADMIN), 200)
    resp = create_offering(farm1["id"], year["id"], product["id"])
    validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_ACTIVE)


def test_offering_withdraw_blocked_by_active_agreement(api):
    """PRD section 3.3: "withdrawal from `VERIFIED` is blocked with
    `ERR_OFFERING_HAS_ACTIVE_AGREEMENTS` whenever a planting agreement
    referencing the offering stands in `PROPOSED`, `SIGNED`,
    `AMENDMENT_PROPOSED`, or `FULFILLING`."

    Design: Corner/state_machines/sm_offering_withdraw_blocked_by_active_agreement
    """
    from test_helpers import setup_procurement_chain

    chain = setup_procurement_chain(sign=False)  # agreement stays PROPOSED
    resp = api.withdraw_offering(
        chain.offering["id"], make_farm_manager_headers(chain.farm["id"])
    )
    validate_error(resp, ApiErrorId.ERR_OFFERING_HAS_ACTIVE_AGREEMENTS)
    offering = validate_success(api.get_offering(chain.offering["id"], ADMIN), 200)
    assert offering["status"] == "VERIFIED"
