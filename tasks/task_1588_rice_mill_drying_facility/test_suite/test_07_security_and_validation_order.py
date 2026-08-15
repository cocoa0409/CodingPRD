"""Authentication, RBAC, identity scoping, typed 404s, and the fixed request
validation order (PRD §2.1, §2.7)."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    assert_cwt,
    ApiErrorId,
    TEST_USERS,
    NON_EXISTENT_UUID,
    create_open_season,
    close_intake,
    create_grower,
    create_bin,
    create_spot_lot,
    grade_lot,
    store_lot,
    create_hold,
    release_hold,
    create_season_payload,
    create_spot_lot_payload,
    create_settlement_payload,
    make_grower_rep_headers,
    make_clerk_headers,
)

ADMIN = TEST_USERS["mill_admin_headers"]
MERCH = TEST_USERS["merchandiser_headers"]
SCALE = TEST_USERS["scale_operator_headers"]
LAB = TEST_USERS["quality_lab_tech_headers"]
DRYER = TEST_USERS["dryer_operator_headers"]


# ---------------------------------------------------------------------------
# Priority pair: season state beats spot-cap capacity
# ---------------------------------------------------------------------------

def _closed_season_with_cap_taken():
    """Season spot cap 1 with one SPOT lot already booked on 2026-08-10, then
    intake closed."""
    season = create_open_season(spot_daily_cap=1)
    grower = create_grower(season["id"])
    create_spot_lot(season["id"], grower["id"], gross_weight_lbs=42000,
                    tare_weight_lbs=12000, scheduled_date="2026-08-10",
                    moisture_pct_handheld=15.0)
    close_intake(season["id"])
    return season, grower


def test_season_state_beats_spot_cap_constraint(api, scale_operator_headers):
    """PRD §2.7: "Every request is validated in a fixed order, and a request
    that fails several checks surfaces the error from the earliest failing
    category."
    PRD §3.3: "Intake is possible only while the season stands in
    `INTAKE_OPEN`; a truck arriving against a closed season is turned away with
    `ERR_SEASON_INTAKE_NOT_OPEN`."

    Design: Difficulty/priority_pair_validation_conflict/season_state_beats_spot_cap_constraint
    """
    season, grower = _closed_season_with_cap_taken()
    # Both checks fail: season state (category 6) and the exhausted spot cap
    # (category 11). The earlier category must surface.
    resp = api.create_lot(
        create_spot_lot_payload(
            season["id"], grower["id"], gross_weight_lbs=41000,
            tare_weight_lbs=12000, scheduled_date="2026-08-10",
            moisture_pct_handheld=15.0),
        scale_operator_headers,
    )
    validate_error(resp, ApiErrorId.ERR_SEASON_INTAKE_NOT_OPEN)


def test_season_state_error_fires_alone_when_cap_not_exhausted(api, scale_operator_headers):
    """PRD §3.3: "Intake is possible only while the season stands in
    `INTAKE_OPEN`; a truck arriving against a closed season is turned away with
    `ERR_SEASON_INTAKE_NOT_OPEN`."

    Design: Difficulty/priority_pair_validation_conflict/season_state_beats_spot_cap_constraint
    """
    season, grower = _closed_season_with_cap_taken()
    # A different date leaves the spot cap untouched: only the state check can
    # fire, isolating it from the capacity rule.
    resp = api.create_lot(
        create_spot_lot_payload(
            season["id"], grower["id"], gross_weight_lbs=41000,
            tare_weight_lbs=12000, scheduled_date="2026-08-11",
            moisture_pct_handheld=15.0),
        scale_operator_headers,
    )
    validate_error(resp, ApiErrorId.ERR_SEASON_INTAKE_NOT_OPEN)


# ---------------------------------------------------------------------------
# Priority pair: food-safety hold beats variety constraint
# ---------------------------------------------------------------------------

def _held_locked_bin_scenario():
    """Bin B-01 locked LONG_GRAIN (100.00 stock) with an ACTIVE hold; a
    MEDIUM_GRAIN lot graded and waiting to be stored."""
    season = create_open_season()
    grower = create_grower(season["id"])
    bin_ = create_bin(season["id"], bin_code="B-01", capacity_cwt=500.00)
    lot1 = create_spot_lot(season["id"], grower["id"], gross_weight_lbs=22000,
                           tare_weight_lbs=12000, scheduled_date="2026-08-10")
    grade_lot(lot1["id"])
    store_lot(lot1["id"], bin_["id"])
    hold = create_hold(season["id"], "BIN", bin_["id"], reason_code="PEST_ACTIVITY")
    lot2 = create_spot_lot(season["id"], grower["id"], gross_weight_lbs=17000,
                           tare_weight_lbs=12000, scheduled_date="2026-08-11",
                           variety="MEDIUM_GRAIN", spot_price_cents_per_cwt=1350)
    grade_lot(lot2["id"])
    return season, bin_, hold, lot2


def test_hold_safety_beats_variety_constraint(api, scale_operator_headers):
    """PRD §2.7: "Because the order is fixed, a mid-flight hold surfaces as
    `ERR_ACTIVE_HOLD_BLOCKS_OPERATION` in preference to any later capacity or
    inventory failure, and an authentication failure masks everything behind
    it."
    PRD §3.5: "no `ACTIVE` hold may sit on the lot or the target bin
    (`ERR_ACTIVE_HOLD_BLOCKS_OPERATION`)"

    Design: Difficulty/priority_pair_validation_conflict/hold_safety_beats_variety_constraint
    """
    _, bin_, _, lot2 = _held_locked_bin_scenario()
    # Both violations at once: ACTIVE hold on the bin (category 8) and variety
    # mismatch against the LONG_GRAIN lock (category 10). Safety must win.
    resp = api.store_lot(lot2["id"], {"bin_id": bin_["id"]}, scale_operator_headers)
    validate_error(resp, ApiErrorId.ERR_ACTIVE_HOLD_BLOCKS_OPERATION)


def test_variety_mismatch_surfaces_once_hold_released(api, scale_operator_headers):
    """PRD §3.5: "the bin's `variety_lock` must be null or equal to the lot's
    variety (`ERR_BIN_VARIETY_MISMATCH`, HTTP 422)"

    Design: Difficulty/priority_pair_validation_conflict/hold_safety_beats_variety_constraint
    """
    _, bin_, hold, lot2 = _held_locked_bin_scenario()
    release_hold(hold["id"], resolution_note="inspected clean")
    # With the safety violation gone, the variety constraint fires alone.
    resp = api.store_lot(lot2["id"], {"bin_id": bin_["id"]}, scale_operator_headers)
    validate_error(resp, ApiErrorId.ERR_BIN_VARIETY_MISMATCH)


# ---------------------------------------------------------------------------
# Cross-entity dependency: grading gated by an active hold
# ---------------------------------------------------------------------------

def _lot_under_hold():
    season = create_open_season()
    grower = create_grower(season["id"])
    lot = create_spot_lot(season["id"], grower["id"], gross_weight_lbs=48300,
                          tare_weight_lbs=12000, moisture_pct_handheld=15.0)
    hold = create_hold(season["id"], "LOT", lot["id"],
                       reason_code="AFLATOXIN_SUSPECT")
    return season, lot, hold


def test_lot_grading_blocked_by_active_hold(api, quality_lab_tech_headers):
    """PRD §3.4: "No `ACTIVE` hold may target the lot, or the grading is refused
    with `ERR_ACTIVE_HOLD_BLOCKS_OPERATION`."
    PRD §3.7: "An active hold is a hard stop across the facility, always
    surfacing as `ERR_ACTIVE_HOLD_BLOCKS_OPERATION` (HTTP 422): it blocks
    grading, regrading, or storing a held lot"

    Design: Difficulty/cross_entity_state_dependency/lot_grading_gated_by_active_hold
    """
    _, lot, _ = _lot_under_hold()
    resp = api.grade_lot(
        lot["id"],
        {"moisture_pct_official": 15.0, "foreign_matter_pct": 0.4,
         "damage_pct": 0.4, "broken_pct": 2.0},
        quality_lab_tech_headers,
    )
    validate_error(resp, ApiErrorId.ERR_ACTIVE_HOLD_BLOCKS_OPERATION)


def test_lot_grading_succeeds_after_hold_release(api, quality_lab_tech_headers):
    """PRD §3.7: "Releasing a hold requires it to stand `ACTIVE` — a second
    release meets `ERR_HOLD_ALREADY_RELEASED` — and records the officer's
    `resolution_note` as the hold moves to `RELEASED`."
    PRD §3.4: "A `QualityLabTech` grades a `WEIGHED` lot — any other status
    yields `ERR_INVALID_LOT_STATE` — by supplying the laboratory readings
    `moisture_pct_official`, `foreign_matter_pct`, `damage_pct`, and
    `broken_pct`."

    Design: Difficulty/cross_entity_state_dependency/lot_grading_gated_by_active_hold
    """
    _, lot, hold = _lot_under_hold()
    release_hold(hold["id"], resolution_note="lab retest negative")
    graded = validate_success(
        api.grade_lot(
            lot["id"],
            {"moisture_pct_official": 15.0, "foreign_matter_pct": 0.4,
             "damage_pct": 0.4, "broken_pct": 2.0},
            quality_lab_tech_headers,
        )
    )
    assert graded["status"] == "GRADED"
    # M 15.0: shrink 100*2/87 = 2.2988506% + 0.5 handling; 363 * 0.9720115.
    assert_cwt(graded["dry_weight_cwt"], 352.84, "dry_weight_cwt after release")


# ---------------------------------------------------------------------------
# Corner: authentication and role authorization
# ---------------------------------------------------------------------------

def test_missing_auth_header_rejected(api):
    """PRD §2.1: "A request with a missing header or an unrecognized role is
    rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."
    PRD §2.7: "Because the order is fixed, a mid-flight hold surfaces as
    `ERR_ACTIVE_HOLD_BLOCKS_OPERATION` in preference to any later capacity or
    inventory failure, and an authentication failure masks everything behind
    it."

    Design: Corner/validations/missing_auth_header_rejected
    """
    resp = api_client.create_season(create_season_payload(name="NoAuth"), headers={})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_role_exclusive_operation_denials(api, scale_operator_headers,
                                          merchandiser_headers,
                                          quality_lab_tech_headers,
                                          dryer_operator_headers):
    """PRD §2.1: "A request whose role is recognized but not permitted for the
    target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4 assigns each endpoint its authorized role(s) (contracts and growers
    to `Merchandiser`, bins to `MillAdmin`, settlements to `SettlementClerk`,
    fumigation records to `FumigationTech`).

    Design: Corner/rbac/role_exclusive_operation_denials
    """
    season = create_open_season()
    grower = create_grower(season["id"])
    bin_ = create_bin(season["id"])

    # ScaleOperator may not create contracts (Merchandiser exclusive).
    resp = api.create_contract(
        {"season_id": season["id"], "grower_id": grower["id"],
         "variety": "LONG_GRAIN", "contracted_cwt": 100.00,
         "base_price_cents_per_cwt": 1500,
         "grade_adjustments": {"US_NO_1": 0, "US_NO_2": 0, "US_NO_3": 0,
                               "US_NO_4": 0, "US_NO_5": 0, "SAMPLE": 0}},
        scale_operator_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    # Merchandiser may not create bins (MillAdmin exclusive).
    resp = api.create_bin(
        {"season_id": season["id"], "bin_code": "B-99", "capacity_cwt": 100.00},
        merchandiser_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    # QualityLabTech may not create settlements (SettlementClerk exclusive).
    resp = api.create_settlement(
        create_settlement_payload(season["id"], grower["id"]),
        quality_lab_tech_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    # DryerOperator may not log fumigation events (FumigationTech exclusive).
    resp = api.create_fumigation_event(
        {"season_id": season["id"], "bin_id": bin_["id"], "fumigant_code": "PH3",
         "applicator_license": "LIC-0000", "started_at": "2026-08-01T00:00:00Z",
         "exposure_hours": 48, "aeration_hours": 24},
        dryer_operator_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_growerrep_identity_scope_enforcement(api):
    """PRD §2.1: "When `X-User-Role` is `GrowerRep`, `X-User-ID` is the `id` of
    the acting `Grower`; ownership checks on any resource that references a
    `Grower` compare the resource's `grower_id` field to `X-User-ID`, and a
    mismatch is rejected with `ERR_IDENTITY_SCOPE_VIOLATION` (HTTP 403)."

    Design: Corner/rbac/growerrep_identity_scope_enforcement
    """
    season = create_open_season()
    grower1 = create_grower(season["id"], farm_code="FARM-001",
                            legal_name="Delta Farms")
    grower2 = create_grower(season["id"], farm_code="FARM-002",
                            legal_name="Bayou Grain")
    lot = create_spot_lot(season["id"], grower1["id"])

    resp = api_client.get_lot(lot["id"], make_grower_rep_headers(grower2["id"]))
    validate_error(resp, ApiErrorId.ERR_IDENTITY_SCOPE_VIOLATION)

    own = validate_success(api_client.get_lot(lot["id"],
                                              make_grower_rep_headers(grower1["id"])))
    assert own["status"] == "WEIGHED"


# ---------------------------------------------------------------------------
# Corner: typed 404s for every resource
# ---------------------------------------------------------------------------

def test_not_found_gets_return_entity_specific_404s(api, mill_admin_headers):
    """PRD §2.7: "The not-found error is specific to the resource:
    `ERR_SEASON_NOT_FOUND`, `ERR_GROWER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`,
    `ERR_BIN_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_DRYING_RUN_NOT_FOUND`,
    `ERR_MILL_RUN_NOT_FOUND`, `ERR_PACKAGING_RUN_NOT_FOUND`,
    `ERR_BYPRODUCT_ORDER_NOT_FOUND`, `ERR_FUMIGATION_NOT_FOUND`,
    `ERR_HOLD_NOT_FOUND`, or `ERR_SETTLEMENT_NOT_FOUND` (all 404)."

    Design: Corner/errors/not_found_gets_return_entity_specific_404s
    """
    missing = NON_EXISTENT_UUID
    cases = [
        (api.get_season, ApiErrorId.ERR_SEASON_NOT_FOUND),
        (api.get_grower, ApiErrorId.ERR_GROWER_NOT_FOUND),
        (api.get_contract, ApiErrorId.ERR_CONTRACT_NOT_FOUND),
        (api.get_bin, ApiErrorId.ERR_BIN_NOT_FOUND),
        (api.get_lot, ApiErrorId.ERR_LOT_NOT_FOUND),
        (api.get_drying_run, ApiErrorId.ERR_DRYING_RUN_NOT_FOUND),
        (api.get_mill_run, ApiErrorId.ERR_MILL_RUN_NOT_FOUND),
        (api.get_packaging_run, ApiErrorId.ERR_PACKAGING_RUN_NOT_FOUND),
        (api.get_byproduct_order, ApiErrorId.ERR_BYPRODUCT_ORDER_NOT_FOUND),
        (api.get_fumigation_event, ApiErrorId.ERR_FUMIGATION_NOT_FOUND),
        (api.get_hold, ApiErrorId.ERR_HOLD_NOT_FOUND),
        (api.get_settlement, ApiErrorId.ERR_SETTLEMENT_NOT_FOUND),
    ]
    for getter, expected_error in cases:
        resp = getter(missing, mill_admin_headers)
        validate_error(resp, expected_error)
