"""Paddy-lot intake, shrink/drying-charge computation, grading, regrade, and
quality rejection (PRD §3.3, §3.4)."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    assert_cwt,
    ApiErrorId,
    TEST_USERS,
    create_open_season,
    create_grower,
    create_contract,
    create_bin,
    create_spot_lot,
    create_contract_lot,
    grade_lot,
    store_lot,
    get_lot,
    setup_binned_contract_lots,
    settlement_reaching,
    create_spot_lot_payload,
    grade_lot_payload,
)

ADMIN = TEST_USERS["mill_admin_headers"]
MERCH = TEST_USERS["merchandiser_headers"]
SCALE = TEST_USERS["scale_operator_headers"]
LAB = TEST_USERS["quality_lab_tech_headers"]


def _open_season_with_grower():
    season = create_open_season()
    grower = create_grower(season["id"])
    return season, grower


# ---------------------------------------------------------------------------
# Dual-variant dry weight: handheld (provisional) vs official (final)
# ---------------------------------------------------------------------------

def _provisioned_363_lot():
    """SPOT lot, net 363.00 cwt, handheld 18.0 — the shared preamble for the
    shrink dual-variant pair."""
    season, grower = _open_season_with_grower()
    lot = create_spot_lot(season["id"], grower["id"], gross_weight_lbs=48300,
                          tare_weight_lbs=12000, moisture_pct_handheld=18.0)
    return season, lot


def test_provisional_dry_weight_uses_handheld_reading(api):
    """PRD §3.3: "It then computes a **provisional dry weight**, stored on
    `provisional_dry_weight_cwt`, using the handheld moisture reading."
    PRD §3.3: "The moisture-shrink percentage is one hundred times the amount by
    which the moisture reading exceeds the base, divided by eighty-seven (the
    span from the 13.0 base to one hundred); when the reading is above base, a
    flat 0.5 percent handling loss is added; at or below the base both
    components are zero."

    Design: Difficulty/dual_variant_calc/shrink_handheld_vs_official_moisture
    """
    _, lot = _provisioned_363_lot()
    assert_cwt(lot["net_wet_cwt"], 363.00, "net_wet_cwt")
    # Handheld 18.0: shrink 100*5.0/87 = 5.7471264% plus 0.5% handling.
    assert_cwt(lot["provisional_dry_weight_cwt"], 340.32, "provisional_dry_weight_cwt")
    assert lot["status"] == "WEIGHED"


def test_official_dry_weight_supersedes_but_provisional_retained(api):
    """PRD §3.4: "The official moisture replaces the handheld figure and drives
    the **final dry weight**, stored on `dry_weight_cwt`, through the same
    drying model as the provisional variant"
    PRD §3.3: "This scale-house number is a courtesy estimate only — it is
    superseded at grading by the laboratory-based figure and never drives
    money."

    Design: Difficulty/dual_variant_calc/shrink_handheld_vs_official_moisture
    """
    season, lot = _provisioned_363_lot()
    graded = grade_lot(lot["id"], moisture_pct_official=18.5,
                       foreign_matter_pct=0.4, damage_pct=0.4, broken_pct=2.0)
    # Official 18.5: shrink 100*5.5/87 = 6.3218391% plus 0.5% handling.
    assert_cwt(graded["dry_weight_cwt"], 338.24, "dry_weight_cwt (official 18.5)")
    assert_cwt(graded["grade_score"], 4.0, "grade_score")
    assert graded["grade"] == "US_NO_2"
    # Drying charge: 5.5 points -> 3*4 + 2.5*7 = 29.5 cents/cwt x 363.00 cwt.
    assert graded["drying_charge_cents"] == 10709

    reread = get_lot(lot["id"])
    assert_cwt(reread["provisional_dry_weight_cwt"], 340.32,
               "provisional variant retained after grading")
    assert_cwt(reread["dry_weight_cwt"], 338.24, "final variant after grading")


# ---------------------------------------------------------------------------
# Boundary: moisture exactly at the 13.0% base
# ---------------------------------------------------------------------------

def test_moisture_exactly_at_base_yields_zero_shrink(api):
    """PRD §3.4: "above the 13.0 percent base, the moisture-shrink percentage is
    one hundred times the excess over base divided by eighty-seven, plus the
    flat 0.5 percent handling loss; at or below base, nothing shrinks."

    Design: Difficulty/boundary_precision_check/moisture_exactly_base_zero_shrink
    """
    season, grower = _open_season_with_grower()
    lot = create_spot_lot(season["id"], grower["id"], gross_weight_lbs=48300,
                          tare_weight_lbs=12000, moisture_pct_handheld=13.0)
    graded = grade_lot(lot["id"], moisture_pct_official=13.0)
    assert_cwt(graded["dry_weight_cwt"], 363.00, "dry_weight_cwt at exactly base")
    assert_cwt(graded["moisture_shrink_cwt"], 0, "moisture_shrink_cwt at base")
    assert_cwt(graded["handling_loss_cwt"], 0, "handling_loss_cwt at base")
    assert graded["drying_charge_cents"] == 0


def test_moisture_one_tenth_over_base_triggers_full_handling_cliff(api):
    """PRD §3.4: "Wet paddy also pays for its drying: the lot's
    `drying_charge_cents` is a tiered charge on the net wet hundredweight, where
    the moisture points are the amount by which the official moisture exceeds
    the 13.0 base (never below zero)."
    PRD §3.4: "above the 13.0 percent base, the moisture-shrink percentage is
    one hundred times the excess over base divided by eighty-seven, plus the
    flat 0.5 percent handling loss"

    Design: Difficulty/boundary_precision_check/moisture_exactly_base_zero_shrink
    """
    season, grower = _open_season_with_grower()
    lot = create_spot_lot(season["id"], grower["id"], gross_weight_lbs=48300,
                          tare_weight_lbs=12000, scheduled_date="2026-08-11",
                          moisture_pct_handheld=13.1)
    graded = grade_lot(lot["id"], moisture_pct_official=13.1)
    # 0.1 point: 0.1149425% moisture shrink + the full 0.5% handling cliff.
    assert_cwt(graded["dry_weight_cwt"], 360.77, "dry_weight_cwt at 13.1")
    # 363.00 cwt * (0.1 point * 4 cents/point) = 145.2 -> round half-up 145.
    assert graded["drying_charge_cents"] == 145


# ---------------------------------------------------------------------------
# Combinatorial: tiered marginal drying rates
# ---------------------------------------------------------------------------

def test_drying_charge_exactly_three_points_stays_in_tier_one(api):
    """PRD §3.4: "The first 3.0 points are billed at 4 cents per cwt per point,
    the next 3.0 points at 7 cents, and any points beyond 6.0 at 12 cents — so a
    reading of exactly 3.0 points lies entirely in the first tier and exactly
    6.0 points fills the first two tiers precisely. The summed rate is
    multiplied by `net_wet_cwt` and the result rounded half-up to whole cents."

    Design: Difficulty/combinatorial_formula/drying_charge_tiered_marginal_rates
    """
    season, grower = _open_season_with_grower()
    lot = create_spot_lot(season["id"], grower["id"], gross_weight_lbs=48300,
                          tare_weight_lbs=12000, moisture_pct_handheld=16.0)
    graded = grade_lot(lot["id"], moisture_pct_official=16.0,
                       foreign_matter_pct=0.4, damage_pct=0.4, broken_pct=2.0)
    # Exactly 3.0 points: rate 3*4 = 12 cents/cwt; 363.00 * 12 = 4356.
    assert graded["drying_charge_cents"] == 4356


def test_drying_charge_six_and_a_half_points_straddles_all_tiers(api):
    """PRD §3.4: "The first 3.0 points are billed at 4 cents per cwt per point,
    the next 3.0 points at 7 cents, and any points beyond 6.0 at 12 cents"
    PRD §3.4: "the moisture-shrink percentage is one hundred times the excess
    over base divided by eighty-seven, plus the flat 0.5 percent handling loss"

    Design: Difficulty/combinatorial_formula/drying_charge_tiered_marginal_rates
    """
    season, grower = _open_season_with_grower()
    lot = create_spot_lot(season["id"], grower["id"], gross_weight_lbs=48300,
                          tare_weight_lbs=12000, moisture_pct_handheld=19.5)
    graded = grade_lot(lot["id"], moisture_pct_official=19.5,
                       foreign_matter_pct=0.4, damage_pct=0.4, broken_pct=2.0)
    # 6.5 points: 3*4 + 3*7 + 0.5*12 = 39 cents/cwt; 363.00 * 39 = 14157.
    assert graded["drying_charge_cents"] == 14157
    # Shrink 100*6.5/87 = 7.4712644% + 0.5 handling; 363.00 * 0.9202874.
    assert_cwt(graded["dry_weight_cwt"], 334.06, "dry_weight_cwt at 19.5")


# ---------------------------------------------------------------------------
# Non-linear machine: the GRADED -> GRADED regrade self-loop
# ---------------------------------------------------------------------------

REGRADE_ADJUSTMENTS = {"US_NO_1": 0, "US_NO_2": -25, "US_NO_3": -60,
                       "US_NO_4": -110, "US_NO_5": -175, "SAMPLE": -300}


def _regrade_scenario():
    """Contract lot net 363.00, graded at M 18.5 -> US_NO_2 on a 1500-base
    contract with grade adjustments."""
    season, grower = _open_season_with_grower()
    contract = create_contract(season["id"], grower["id"], contracted_cwt=400.00,
                               base_price_cents_per_cwt=1500,
                               grade_adjustments=dict(REGRADE_ADJUSTMENTS))
    lot = create_contract_lot(season["id"], grower["id"], contract["id"],
                              gross_weight_lbs=48300, tare_weight_lbs=12000,
                              moisture_pct_handheld=18.0)
    graded = grade_lot(lot["id"], moisture_pct_official=18.5,
                       foreign_matter_pct=0.4, damage_pct=0.4, broken_pct=2.0)
    return season, lot, graded


def test_regrade_self_loop_initial_grade_and_price(api):
    """PRD §3.4: "For a contract lot, `price_cents_per_cwt` is the contract's
    base price plus the `grade_adjustments` delta for the assigned grade"
    PRD §3.4: "Either way, `line_value_cents` is the dry hundredweight
    multiplied by the price, rounded half-up to whole cents."

    Design: Difficulty/non_linear_state_machine/lot_regrade_self_loop_cycle
    """
    _, _, graded = _regrade_scenario()
    assert graded["grade"] == "US_NO_2"
    assert graded["price_cents_per_cwt"] == 1475  # 1500 - 25
    # 338.24 cwt * 1475 cents/cwt = 498904.0
    assert graded["line_value_cents"] == 498904


def test_regrade_self_loop_keeps_state_and_reprices(api, quality_lab_tech_headers):
    """PRD §3.4: "Regrading is permitted while a lot stands in `GRADED` or
    `BINNED`, takes the same four laboratory inputs, and recomputes every
    grading-derived field — dry weight, shrink and handling components, score,
    grade, drying charge, price, and line value — with a fresh `graded_date`."

    Design: Difficulty/non_linear_state_machine/lot_regrade_self_loop_cycle
    """
    _, lot, _ = _regrade_scenario()
    regraded = validate_success(
        api.regrade_lot(
            lot["id"],
            grade_lot_payload(moisture_pct_official=18.5, foreign_matter_pct=0.6,
                              damage_pct=0.6, broken_pct=4.0),
            quality_lab_tech_headers,
        )
    )
    assert regraded["status"] == "GRADED", "regrade self-loop must keep status GRADED"
    # score = 0.6*2 + 0.6*3 + 4.0*1 = 7.0 -> US_NO_3.
    assert_cwt(regraded["grade_score"], 7.0, "grade_score after regrade")
    assert regraded["grade"] == "US_NO_3"
    assert regraded["price_cents_per_cwt"] == 1440  # 1500 - 60
    # round_half_up(338.24 * 1440) = round_half_up(487065.6) = 487066.
    assert regraded["line_value_cents"] == 487066


# ---------------------------------------------------------------------------
# Corner: intake request-shape and intake-window violations
# ---------------------------------------------------------------------------

def test_lot_create_ignores_client_computed_fields(api, scale_operator_headers):
    """PRD §3.3: "A created lot stands in `WEIGHED`."
    PRD §3.3: "From the two scale weights the system derives the net wet weight:
    the difference between gross and tare in pounds, divided by one hundred to
    express it in hundredweight, rounded half-up to 2 decimal places and stored
    as `net_wet_cwt`. It then computes a **provisional dry weight**, stored on
    `provisional_dry_weight_cwt`, using the handheld moisture reading."

    Design: Corner/entities/lot_create_computed_fields_input_ignored
    """
    season, grower = _open_season_with_grower()
    payload = create_spot_lot_payload(
        season["id"], grower["id"], gross_weight_lbs=48300, tare_weight_lbs=12000,
        moisture_pct_handheld=18.0,
    )
    payload["dry_weight_cwt"] = 1.00  # system-managed input must be ignored
    payload["status"] = "SETTLED"
    lot = validate_success(api.create_lot(payload, scale_operator_headers),
                           expected_status=201)
    assert_cwt(lot["net_wet_cwt"], 363.00, "server-computed net_wet_cwt")
    assert_cwt(lot["provisional_dry_weight_cwt"], 340.32, "server-computed provisional")
    assert lot["status"] == "WEIGHED"


def test_lot_create_tare_not_less_than_gross_rejected(api, scale_operator_headers):
    """PRD §3.3: "The tare must be strictly less than the gross, or the ticket
    fails shape validation with `ERR_INVALID_REQUEST`."

    Design: Corner/validations/lot_create_tare_not_less_than_gross_rejected
    """
    season, grower = _open_season_with_grower()
    payload = create_spot_lot_payload(
        season["id"], grower["id"], gross_weight_lbs=12000, tare_weight_lbs=12000,
    )
    resp = api.create_lot(payload, scale_operator_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_scheduled_date_outside_intake_window_rejected(api, scale_operator_headers):
    """PRD §3.3: "The appointment date must lie within the season's intake
    window, both bounds inclusive; a date outside it is rejected with
    `ERR_OUTSIDE_INTAKE_WINDOW`."

    Design: Corner/validations/scheduled_date_outside_intake_window_rejected
    """
    season, grower = _open_season_with_grower()
    payload = create_spot_lot_payload(
        season["id"], grower["id"], scheduled_date="2026-11-15",
    )
    resp = api.create_lot(payload, scale_operator_headers)
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_INTAKE_WINDOW)


def test_spot_cap_boundary_and_rejection_relief(api, scale_operator_headers,
                                                quality_lab_tech_headers):
    """PRD §3.3: "the number of non-rejected spot lots already booked for the
    same `scheduled_date` must be strictly below the season's `spot_daily_cap`,
    so the truck that brings the count to exactly the cap is admitted and the
    next one is rejected with `ERR_SPOT_CAP_REACHED`. Contract lots never count
    against the cap and are never blocked by it."

    Design: Corner/validations/spot_cap_boundary_and_rejection_relief
    """
    season = create_open_season(spot_daily_cap=2)
    grower = create_grower(season["id"])
    contract = create_contract(season["id"], grower["id"], contracted_cwt=400.00)

    first = create_spot_lot(season["id"], grower["id"], scheduled_date="2026-08-10")
    create_spot_lot(season["id"], grower["id"], scheduled_date="2026-08-10")

    # Third SPOT lot on the same date: count == cap -> rejected.
    payload = create_spot_lot_payload(season["id"], grower["id"],
                                      scheduled_date="2026-08-10")
    resp = api.create_lot(payload, scale_operator_headers)
    validate_error(resp, ApiErrorId.ERR_SPOT_CAP_REACHED)

    # A CONTRACT lot on the same capped date is never blocked by the cap.
    contract_lot = create_contract_lot(season["id"], grower["id"], contract["id"],
                                       scheduled_date="2026-08-10")
    assert contract_lot["status"] == "WEIGHED"

    # Rejecting a WEIGHED spot lot removes it from the count, freeing a slot.
    validate_success(
        api.reject_lot(first["id"], {"reject_reason": "off-spec truck"},
                       quality_lab_tech_headers)
    )
    fourth = validate_success(api.create_lot(payload, scale_operator_headers),
                              expected_status=201)
    assert fourth["status"] == "WEIGHED"


def test_grade_score_threshold_inclusive_boundaries(api, quality_lab_tech_headers):
    """PRD §3.4: "the `grade` is assigned by inclusive thresholds: a score of at
    most 2.0 earns `US_NO_1`; at most 5.0, `US_NO_2`; at most 10.0, `US_NO_3`;
    at most 15.0, `US_NO_4`; at most 20.0, `US_NO_5`; anything above 20.0 is
    `SAMPLE`."

    Design: Corner/calculations/grade_score_threshold_inclusive_boundaries
    """
    season, grower = _open_season_with_grower()
    lot1 = create_spot_lot(season["id"], grower["id"], scheduled_date="2026-08-10")
    lot2 = create_spot_lot(season["id"], grower["id"], scheduled_date="2026-08-11")

    # 0.5*2 + 0.2*3 + 0.4 = 2.0 -> US_NO_1 (inclusive).
    g1 = validate_success(
        api.grade_lot(lot1["id"],
                      grade_lot_payload(foreign_matter_pct=0.5, damage_pct=0.2,
                                        broken_pct=0.4),
                      quality_lab_tech_headers)
    )
    assert_cwt(g1["grade_score"], 2.0, "score at the US_NO_1 boundary")
    assert g1["grade"] == "US_NO_1"

    # 0.5*2 + 0.2*3 + 0.5 = 2.1 -> US_NO_2.
    g2 = validate_success(
        api.grade_lot(lot2["id"],
                      grade_lot_payload(foreign_matter_pct=0.5, damage_pct=0.2,
                                        broken_pct=0.5),
                      quality_lab_tech_headers)
    )
    assert_cwt(g2["grade_score"], 2.1, "score one tick above the boundary")
    assert g2["grade"] == "US_NO_2"


def test_spot_lot_price_ignores_grade_grid(api, quality_lab_tech_headers):
    """PRD §3.4: "for a spot lot it is simply the agreed
    `spot_price_cents_per_cwt`, unchanged by grade. Either way,
    `line_value_cents` is the dry hundredweight multiplied by the price, rounded
    half-up to whole cents."

    Design: Corner/calculations/spot_lot_price_ignores_grade_grid
    """
    season, grower = _open_season_with_grower()
    lot = create_spot_lot(season["id"], grower["id"], gross_weight_lbs=22000,
                          tare_weight_lbs=12000, moisture_pct_handheld=13.0)
    # score = 3.0*2 + 4.0*3 + 5.0 = 23.0 -> SAMPLE.
    graded = validate_success(
        api.grade_lot(lot["id"],
                      grade_lot_payload(moisture_pct_official=13.0,
                                        foreign_matter_pct=3.0, damage_pct=4.0,
                                        broken_pct=5.0),
                      quality_lab_tech_headers)
    )
    assert graded["grade"] == "SAMPLE"
    assert graded["price_cents_per_cwt"] == 1300
    assert graded["line_value_cents"] == 130000  # 100.00 cwt * 1300


def test_lot_invalid_transitions_from_each_state(api, quality_lab_tech_headers,
                                                 scale_operator_headers):
    """PRD §3.4: "A `QualityLabTech` grades a `WEIGHED` lot — any other status
    yields `ERR_INVALID_LOT_STATE`"
    PRD §3.5: "Five guards stand at that door: the lot must be `GRADED`
    (`ERR_INVALID_LOT_STATE`)"
    PRD §3.4: "Rejecting a lot — permitted from `WEIGHED` or `GRADED`, never
    later — requires a `reject_reason` and moves the lot to the terminal
    `REJECTED` state."

    Design: Corner/state_machines/lot_invalid_transitions_from_each_state
    """
    season, grower = _open_season_with_grower()
    bin_ = create_bin(season["id"])
    lot1 = create_spot_lot(season["id"], grower["id"], gross_weight_lbs=48300,
                           tare_weight_lbs=12000, scheduled_date="2026-08-10",
                           moisture_pct_handheld=15.0)
    grade_lot(lot1["id"], moisture_pct_official=15.0, foreign_matter_pct=0.4,
              damage_pct=0.4, broken_pct=2.0)
    lot2 = create_spot_lot(season["id"], grower["id"], gross_weight_lbs=48300,
                           tare_weight_lbs=12000, scheduled_date="2026-08-11",
                           moisture_pct_handheld=15.0)

    # grade on an already-GRADED lot.
    resp = api.grade_lot(lot1["id"], grade_lot_payload(moisture_pct_official=15.0),
                         quality_lab_tech_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_LOT_STATE)

    # store on a WEIGHED lot.
    resp = api.store_lot(lot2["id"], {"bin_id": bin_["id"]}, scale_operator_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_LOT_STATE)

    # reject moves WEIGHED -> REJECTED (terminal).
    rejected = validate_success(
        api.reject_lot(lot2["id"], {"reject_reason": "wet load refused"},
                       quality_lab_tech_headers)
    )
    assert rejected["status"] == "REJECTED"

    # regrade on terminal REJECTED.
    resp = api.regrade_lot(lot2["id"], grade_lot_payload(moisture_pct_official=14.0),
                           quality_lab_tech_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_LOT_STATE)


def test_terminal_settled_lot_lockdown(api, quality_lab_tech_headers):
    """PRD §3.4: "Regrading is permitted while a lot stands in `GRADED` or
    `BINNED`"
    PRD §3.4: "Rejecting a lot — permitted from `WEIGHED` or `GRADED`, never
    later"
    PRD §3.8: "Approval also moves every member lot `BINNED` → `SETTLED`."

    Design: Corner/state_machines/terminal_settled_lot_lockdown
    """
    scenario = setup_binned_contract_lots(
        [{"gross": 22010, "tare": 12000}],
        contracted_cwt=250.00, base_price_cents_per_cwt=1000,
    )
    lot = scenario["lots"][0]
    settlement_reaching(scenario, "approved")
    settled_lot = get_lot(lot["id"])
    assert settled_lot["status"] == "SETTLED"

    resp = api.regrade_lot(settled_lot["id"],
                           grade_lot_payload(moisture_pct_official=14.0),
                           quality_lab_tech_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_LOT_STATE)

    resp = api.reject_lot(settled_lot["id"], {"reject_reason": "late rejection attempt"},
                          quality_lab_tech_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_LOT_STATE)


def test_grower_duplicate_farm_code_rejected(api, merchandiser_headers):
    """PRD §3.2: "The farm code must be unique within the season; a duplicate is
    rejected with `ERR_DUPLICATE_FARM_CODE`."

    Design: Corner/entities/grower_duplicate_farm_code_rejected
    """
    season = create_open_season()
    create_grower(season["id"], farm_code="FARM-001", legal_name="Delta Farms")
    resp = api.create_grower(
        {"season_id": season["id"], "farm_code": "FARM-001",
         "legal_name": "Copycat Farms"},
        merchandiser_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_FARM_CODE)


def test_fk_reverse_reachability_filtered_lists(api, scale_operator_headers):
    """PRD §3.3: "The lot collection is filterable by `season_id`, `grower_id`,
    `contract_id`, `bin_id`, `drying_run_id`, `settlement_id`, `variety`,
    `source`, `status`, and `scheduled_date`, so the scale house can always
    reconstruct a day's traffic."

    Design: Corner/entities/fk_reverse_reachability_filtered_lists
    """
    season, grower1 = _open_season_with_grower()
    grower2 = create_grower(season["id"], farm_code="FARM-002",
                            legal_name="Bayou Grain")
    lot1 = create_spot_lot(season["id"], grower1["id"], gross_weight_lbs=48300,
                           tare_weight_lbs=12000, scheduled_date="2026-08-10",
                           moisture_pct_handheld=15.0)
    lot2 = create_spot_lot(season["id"], grower2["id"], gross_weight_lbs=40000,
                           tare_weight_lbs=12000, scheduled_date="2026-08-10",
                           moisture_pct_handheld=15.0)

    data1 = validate_success(
        api.list_lots(scale_operator_headers,
                      params={"season_id": season["id"], "grower_id": grower1["id"]})
    )
    assert [row["id"] for row in data1] == [lot1["id"]]

    data2 = validate_success(
        api.list_lots(scale_operator_headers,
                      params={"season_id": season["id"], "grower_id": grower2["id"]})
    )
    assert [row["id"] for row in data2] == [lot2["id"]]

    both = validate_success(
        api.list_lots(scale_operator_headers,
                      params={"season_id": season["id"], "status": "WEIGHED"})
    )
    assert {row["id"] for row in both} == {lot1["id"], lot2["id"]}
