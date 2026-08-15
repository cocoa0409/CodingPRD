"""Bin capacity accounting, variety locking, drying runs, fumigation windows,
and food-safety holds on bins (PRD §2.9, §3.5, §3.7)."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    assert_cwt,
    assert_bin_capacity_invariant,
    ApiErrorId,
    TEST_USERS,
    create_open_season,
    create_grower,
    create_bin,
    get_bin,
    create_spot_lot,
    grade_lot,
    store_lot,
    get_lot,
    create_drying_run,
    get_drying_run,
    complete_drying_run,
    cancel_drying_run,
    create_fumigation_event,
    create_hold,
    set_clock,
    create_fumigation_event_payload,
)

ADMIN = TEST_USERS["mill_admin_headers"]
MERCH = TEST_USERS["merchandiser_headers"]
SCALE = TEST_USERS["scale_operator_headers"]
LAB = TEST_USERS["quality_lab_tech_headers"]
DRYER = TEST_USERS["dryer_operator_headers"]
FUMTECH = TEST_USERS["fumigation_tech_headers"]
SAFETY = TEST_USERS["safety_officer_headers"]


def _open_season_with_grower():
    season = create_open_season()
    grower = create_grower(season["id"])
    return season, grower


def _graded_spot_288_lot(season_id, grower_id):
    """SPOT lot net 300.00 graded at M 16.0 -> dry 288.16."""
    lot = create_spot_lot(season_id, grower_id, gross_weight_lbs=42000,
                          tare_weight_lbs=12000, moisture_pct_handheld=16.0)
    return grade_lot(lot["id"], moisture_pct_official=16.0,
                     foreign_matter_pct=0.4, damage_pct=0.4, broken_pct=2.0)


# ---------------------------------------------------------------------------
# Boundary: bin exact capacity fit
# ---------------------------------------------------------------------------

def _exact_fit_scenario():
    """Bin B-04 cap 100.00; lot 1 net 100.00 (dry 100.00); lot 2 net 0.01."""
    season, grower = _open_season_with_grower()
    bin_ = create_bin(season["id"], bin_code="B-04", capacity_cwt=100.00)
    lot1 = create_spot_lot(season["id"], grower["id"], gross_weight_lbs=22000,
                           tare_weight_lbs=12000, scheduled_date="2026-08-10")
    grade_lot(lot1["id"])
    lot2 = create_spot_lot(season["id"], grower["id"], gross_weight_lbs=12001,
                           tare_weight_lbs=12000, scheduled_date="2026-08-11")
    graded2 = grade_lot(lot2["id"])
    return bin_, lot1, graded2


def test_bin_exact_capacity_fit_admitted(api, scale_operator_headers):
    """PRD §2.9: "Capacity checks throughout the system compare against
    `available_cwt` with an at-most rule: an allocation that exactly fills the
    bin is allowed."

    Design: Difficulty/boundary_precision_check/bin_exact_capacity_fit
    """
    bin_, lot1, _ = _exact_fit_scenario()
    stored = validate_success(
        api.store_lot(lot1["id"], {"bin_id": bin_["id"]}, scale_operator_headers)
    )
    assert stored["status"] == "BINNED"
    bin_after = get_bin(bin_["id"])
    assert_cwt(bin_after["stock_cwt"], 100.00, "stock after exact-fit store")
    assert_cwt(bin_after["available_cwt"], 0.00, "available after exact-fit store")
    assert_bin_capacity_invariant(bin_after)


def test_bin_one_cent_over_capacity_rejected(api, scale_operator_headers):
    """PRD §3.5: "the bin must have room — the lot's `dry_weight_cwt` must not
    exceed `available_cwt`, with an exact fit allowed
    (`ERR_BIN_CAPACITY_EXCEEDED`)."

    Design: Difficulty/boundary_precision_check/bin_exact_capacity_fit
    """
    bin_, lot1, graded2 = _exact_fit_scenario()
    assert_cwt(graded2["dry_weight_cwt"], 0.01, "second lot dry weight")
    store_lot(lot1["id"], bin_["id"])  # fills the bin exactly

    resp = api.store_lot(graded2["id"], {"bin_id": bin_["id"]}, scale_operator_headers)
    validate_error(resp, ApiErrorId.ERR_BIN_CAPACITY_EXCEEDED)


# ---------------------------------------------------------------------------
# Compensating invariant: drying reserve / cancel preserves bin capacity
# ---------------------------------------------------------------------------

def test_drying_reserve_consumes_available_capacity(api, dryer_operator_headers):
    """PRD §3.5: "Planning computes `expected_output_cwt` as the sum of the
    referenced lots' dry weights and reserves that amount against the
    destination bin"
    PRD §2.9: "The derived `available_cwt` is always the capacity minus the
    stock minus the reservation, carried at 2 decimal places."

    Design: Difficulty/compensating_invariant/drying_reserve_cancel_preserves_bin_capacity
    """
    season, grower = _open_season_with_grower()
    bin_ = create_bin(season["id"], bin_code="B-07", capacity_cwt=500.00)
    assert_cwt(bin_["available_cwt"], 500.00, "available before any allocation")
    lot = _graded_spot_288_lot(season["id"], grower["id"])

    run = create_drying_run(season["id"], [lot["id"]], bin_["id"])
    assert_cwt(run["expected_output_cwt"], 288.16, "expected_output_cwt")
    bin_mid = get_bin(bin_["id"])
    assert_cwt(bin_mid["reserved_cwt"], 288.16, "reserved after planning")
    assert_cwt(bin_mid["available_cwt"], 211.84, "available after planning")
    assert_bin_capacity_invariant(bin_mid)


def test_drying_cancel_restores_bin_capacity(api, dryer_operator_headers):
    """PRD §3.5: "Cancelling a `PLANNED` run instead releases the reservation,
    clears each lot's `drying_run_id` back to null, and leaves the lots in
    `GRADED`."
    PRD §2.9: "The derived `available_cwt` is always the capacity minus the
    stock minus the reservation, carried at 2 decimal places."

    Design: Difficulty/compensating_invariant/drying_reserve_cancel_preserves_bin_capacity
    """
    season, grower = _open_season_with_grower()
    bin_ = create_bin(season["id"], bin_code="B-07", capacity_cwt=500.00)
    lot = _graded_spot_288_lot(season["id"], grower["id"])
    run = create_drying_run(season["id"], [lot["id"]], bin_["id"])

    cancelled = cancel_drying_run(run["id"])
    assert cancelled["status"] == "CANCELLED"
    bin_end = get_bin(bin_["id"])
    assert_cwt(bin_end["reserved_cwt"], 0, "reserved after cancel")
    assert_cwt(bin_end["stock_cwt"], 0, "stock after cancel")
    assert_cwt(bin_end["available_cwt"], 500.00, "available after cancel")
    assert_bin_capacity_invariant(bin_end)

    lot_after = get_lot(lot["id"])
    assert lot_after["status"] == "GRADED"
    assert lot_after["drying_run_id"] is None


# ---------------------------------------------------------------------------
# Transitive cascade: fumigation cancels PLANNED drying runs
# ---------------------------------------------------------------------------

def _planned_run_scenario():
    """Bin B-02 with a PLANNED drying run holding a 288.16 reservation."""
    season, grower = _open_season_with_grower()
    bin_ = create_bin(season["id"], bin_code="B-02", capacity_cwt=500.00)
    lot = _graded_spot_288_lot(season["id"], grower["id"])
    run = create_drying_run(season["id"], [lot["id"]], bin_["id"],
                            fuel_cost_cents=5000)
    return season, bin_, lot, run


def test_fumigation_moves_bin_and_cancels_planned_runs(api, fumigation_tech_headers):
    """PRD §3.7: "Recording the treatment moves the bin `AVAILABLE` →
    `FUMIGATING` with a version increment — and, critically, automatically
    cancels every `PLANNED` drying run destined for that bin, releasing its
    reservation and clearing its lots' `drying_run_id` references exactly as a
    manual cancellation would."

    Design: Difficulty/transitive_cascade/fumigation_cancels_planned_drying_runs
    """
    season, bin_, lot, run = _planned_run_scenario()
    bin_before = get_bin(bin_["id"])
    assert_cwt(bin_before["reserved_cwt"], 288.16, "reservation in place")
    assert_cwt(bin_before["available_cwt"], 211.84, "available with reservation")

    validate_success(
        api.create_fumigation_event(
            create_fumigation_event_payload(season["id"], bin_["id"]),
            fumigation_tech_headers,
        ),
        expected_status=201,
    )
    assert get_bin(bin_["id"])["status"] == "FUMIGATING"
    assert get_drying_run(run["id"])["status"] == "CANCELLED"


def test_fumigation_cascade_releases_reservation_and_lot(api, fumigation_tech_headers):
    """PRD §3.7: "automatically cancels every `PLANNED` drying run destined for
    that bin, releasing its reservation and clearing its lots' `drying_run_id`
    references exactly as a manual cancellation would."
    PRD §3.5: "Cancelling a `PLANNED` run instead releases the reservation,
    clears each lot's `drying_run_id` back to null, and leaves the lots in
    `GRADED`."

    Design: Difficulty/transitive_cascade/fumigation_cancels_planned_drying_runs
    """
    season, bin_, lot, run = _planned_run_scenario()
    validate_success(
        api.create_fumigation_event(
            create_fumigation_event_payload(season["id"], bin_["id"]),
            fumigation_tech_headers,
        ),
        expected_status=201,
    )
    bin_after = get_bin(bin_["id"])
    assert_cwt(bin_after["reserved_cwt"], 0, "reservation fully released")
    assert_cwt(bin_after["available_cwt"], 500.00, "capacity restored")
    assert_bin_capacity_invariant(bin_after)

    lot_after = get_lot(lot["id"])
    assert lot_after["status"] == "GRADED"
    assert lot_after["drying_run_id"] is None


# ---------------------------------------------------------------------------
# Boundary: fumigation clearance at the exact second
# ---------------------------------------------------------------------------

def _active_fumigation(bin_code="B-05"):
    """Bin + ACTIVE fumigation started 2026-08-01T00:00:00Z, exposure 48h,
    aeration 24h (exposure ends 2026-08-03T00:00:00Z, clearance
    2026-08-04T00:00:00Z). Season clock starts at the fixed default."""
    season = create_open_season()
    bin_ = create_bin(season["id"], bin_code=bin_code, capacity_cwt=500.00)
    event = create_fumigation_event(season["id"], bin_["id"])
    return season, bin_, event


def test_fumigation_begin_aeration_and_early_clear(api, fumigation_tech_headers):
    """PRD §3.7: "Beginning aeration requires the event to stand `ACTIVE`
    (`ERR_FUMIGATION_INVALID_STATE`) and the season clock to have reached
    `exposure_ends_at` — an early attempt draws `ERR_EXPOSURE_INCOMPLETE`,
    though a clock reading exactly at the exposure end is sufficient."
    PRD §3.7: "Clearing the treatment requires the event in `AERATING` and the
    clock at or past `clearance_at` (`ERR_AERATION_INCOMPLETE` otherwise)"

    Design: Difficulty/boundary_precision_check/fumigation_clearance_at_exact_second
    """
    season, _, event = _active_fumigation()
    assert event["exposure_ends_at"].replace(".000Z", "Z") == "2026-08-03T00:00:00Z"
    assert event["clearance_at"].replace(".000Z", "Z") == "2026-08-04T00:00:00Z"

    set_clock(season["id"], "2026-08-03T00:00:00Z")
    aerating = validate_success(api.begin_aeration(event["id"], fumigation_tech_headers))
    assert aerating["status"] == "AERATING", (
        "begin-aeration at exactly exposure_ends_at must be allowed"
    )

    set_clock(season["id"], "2026-08-03T23:59:00Z")  # 60 seconds before clearance
    resp = api.clear_fumigation(event["id"], fumigation_tech_headers)
    validate_error(resp, ApiErrorId.ERR_AERATION_INCOMPLETE)


def test_fumigation_clear_at_exact_clearance_second(api, fumigation_tech_headers):
    """PRD §3.7: "Clearing the treatment requires the event in `AERATING` and
    the clock at or past `clearance_at` (`ERR_AERATION_INCOMPLETE` otherwise);
    the event moves to the terminal `CLEARED` and the bin returns to
    `AVAILABLE`, ready to receive grain again."

    Design: Difficulty/boundary_precision_check/fumigation_clearance_at_exact_second
    """
    season, bin_, event = _active_fumigation()
    set_clock(season["id"], "2026-08-03T00:00:00Z")
    begin_aeration_event = api.begin_aeration(event["id"], fumigation_tech_headers)
    validate_success(begin_aeration_event)

    set_clock(season["id"], "2026-08-04T00:00:00Z")  # exactly clearance_at
    cleared = validate_success(api.clear_fumigation(event["id"], fumigation_tech_headers))
    assert cleared["status"] == "CLEARED"
    assert get_bin(bin_["id"])["status"] == "AVAILABLE"


# ---------------------------------------------------------------------------
# Temporal overlap: half-open fumigation windows
# ---------------------------------------------------------------------------

def _cleared_fumigation_on_b06():
    """F1 on bin B-06 started 2026-08-10T08:00:00Z (48h+24h, clearance
    2026-08-13T08:00:00Z), progressed to CLEARED via the season clock."""
    season = create_open_season()
    set_clock(season["id"], "2026-08-10T08:00:00Z")
    bin_ = create_bin(season["id"], bin_code="B-06", capacity_cwt=500.00)
    event = create_fumigation_event(season["id"], bin_["id"],
                                    started_at="2026-08-10T08:00:00Z")
    set_clock(season["id"], "2026-08-12T08:00:00Z")
    validate_success(api_client.begin_aeration(event["id"], FUMTECH))
    set_clock(season["id"], "2026-08-13T08:00:00Z")
    cleared = validate_success(api_client.clear_fumigation(event["id"], FUMTECH))
    assert cleared["status"] == "CLEARED"
    return season, bin_


def test_fumigation_window_overlap_inside_window_rejected(api, fumigation_tech_headers):
    """PRD §3.7: "And the window must not overlap any other fumigation event
    ever recorded on the same bin in the same season, history included: an
    overlap exists when the new start falls before the other's clearance and the
    other's start falls before the new clearance"
    PRD §3.7: "An overlapping record is rejected with
    `ERR_FUMIGATION_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/fumigation_half_open_adjacency_allowed
    """
    season, bin_ = _cleared_fumigation_on_b06()
    # Back-dated start 2026-08-12T08:00:00Z lies inside F1's historical window.
    resp = api.create_fumigation_event(
        create_fumigation_event_payload(
            season["id"], bin_["id"], started_at="2026-08-12T08:00:00Z",
            exposure_hours=24, aeration_hours=12,
        ),
        fumigation_tech_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FUMIGATION_WINDOW_CONFLICT)


def test_fumigation_back_to_back_at_clearance_allowed(api, fumigation_tech_headers):
    """PRD §3.7: "back-to-back treatments whose start exactly equals the
    predecessor's clearance are allowed."
    PRD §3.7: "Recording the treatment moves the bin `AVAILABLE` → `FUMIGATING`
    with a version increment"

    Design: Difficulty/resource_temporal_overlap/fumigation_half_open_adjacency_allowed
    """
    season, bin_ = _cleared_fumigation_on_b06()
    successor = validate_success(
        api.create_fumigation_event(
            create_fumigation_event_payload(
                season["id"], bin_["id"], started_at="2026-08-13T08:00:00Z",
                exposure_hours=24, aeration_hours=12,
            ),
            fumigation_tech_headers,
        ),
        expected_status=201,
    )
    assert successor["status"] == "ACTIVE"
    assert get_bin(bin_["id"])["status"] == "FUMIGATING"


# ---------------------------------------------------------------------------
# Priority pair: bin state beats fumigation window overlap
# ---------------------------------------------------------------------------

def _fumigating_bin_with_history():
    """Bin B-03 under ACTIVE fumigation F1 (window
    [2026-08-01T00:00Z, 2026-08-04T00:00Z)); clock at 2026-08-02T00:00:00Z."""
    season = create_open_season()
    bin_ = create_bin(season["id"], bin_code="B-03", capacity_cwt=500.00)
    event = create_fumigation_event(season["id"], bin_["id"])
    set_clock(season["id"], "2026-08-02T00:00:00Z")
    return season, bin_, event


def test_bin_state_beats_fumigation_window_overlap(api, fumigation_tech_headers):
    """PRD §2.7: "Every request is validated in a fixed order, and a request
    that fails several checks surfaces the error from the earliest failing
    category."
    PRD §3.7: "The bin must stand `AVAILABLE` — a bin already `FUMIGATING` or
    `AERATING` rejects the new record with `ERR_BIN_FUMIGATION_ACTIVE`."

    Design: Difficulty/priority_pair_validation_conflict/bin_state_beats_fumigation_window_overlap
    """
    season, bin_, _ = _fumigating_bin_with_history()
    # Both violations at once: bin FUMIGATING (state) and the new window
    # overlaps F1's window (temporal). The state error must win.
    resp = api.create_fumigation_event(
        create_fumigation_event_payload(
            season["id"], bin_["id"], started_at="2026-08-02T00:00:00Z"),
        fumigation_tech_headers,
    )
    validate_error(resp, ApiErrorId.ERR_BIN_FUMIGATION_ACTIVE)


def test_fumigation_window_overlap_with_history_after_clear(api, fumigation_tech_headers):
    """PRD §3.7: "And the window must not overlap any other fumigation event
    ever recorded on the same bin in the same season, history included"
    PRD §3.7: "An overlapping record is rejected with
    `ERR_FUMIGATION_WINDOW_CONFLICT`."

    Design: Difficulty/priority_pair_validation_conflict/bin_state_beats_fumigation_window_overlap
    """
    season, bin_, event = _fumigating_bin_with_history()
    # Progress F1 to CLEARED so the bin is AVAILABLE again (state check passes).
    set_clock(season["id"], "2026-08-03T00:00:00Z")
    validate_success(api.begin_aeration(event["id"], fumigation_tech_headers))
    set_clock(season["id"], "2026-08-04T00:00:00Z")
    validate_success(api.clear_fumigation(event["id"], fumigation_tech_headers))

    # Back-dated record overlapping F1's historical window: only the temporal
    # guard can fire now.
    resp = api.create_fumigation_event(
        create_fumigation_event_payload(
            season["id"], bin_["id"], started_at="2026-08-02T00:00:00Z"),
        fumigation_tech_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FUMIGATION_WINDOW_CONFLICT)


# ---------------------------------------------------------------------------
# Corner: bin and drying-run violations
# ---------------------------------------------------------------------------

def test_bin_duplicate_code_rejected(api, mill_admin_headers):
    """PRD §3.5: "A `MillAdmin` commissions storage by creating bins with a
    `bin_code` (unique within the season — duplicates meet
    `ERR_DUPLICATE_BIN_CODE`) and a `capacity_cwt`."

    Design: Corner/entities/bin_duplicate_code_rejected
    """
    season = create_open_season()
    create_bin(season["id"], bin_code="B-01", capacity_cwt=500.00)
    resp = api.create_bin(
        {"season_id": season["id"], "bin_code": "B-01", "capacity_cwt": 300.00},
        mill_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_BIN_CODE)


def test_variety_lock_mismatch_rejected(api, scale_operator_headers):
    """PRD §3.5: "the bin's `variety_lock` must be null or equal to the lot's
    variety (`ERR_BIN_VARIETY_MISMATCH`, HTTP 422)"
    PRD §2.9: "The lock is null on an empty bin, is set to the incoming variety
    the first time stock is credited, and forbids subsequent credits of the
    other variety."

    Design: Corner/validations/variety_lock_mismatch_rejected
    """
    season, grower = _open_season_with_grower()
    bin1 = create_bin(season["id"], bin_code="B-01", capacity_cwt=500.00)
    bin2 = create_bin(season["id"], bin_code="B-02", capacity_cwt=500.00)
    long_lot = create_spot_lot(season["id"], grower["id"], gross_weight_lbs=22000,
                               tare_weight_lbs=12000, scheduled_date="2026-08-10")
    grade_lot(long_lot["id"])
    store_lot(long_lot["id"], bin1["id"])  # locks B-01 to LONG_GRAIN

    medium_lot = create_spot_lot(season["id"], grower["id"], gross_weight_lbs=17000,
                                 tare_weight_lbs=12000, scheduled_date="2026-08-11",
                                 variety="MEDIUM_GRAIN", spot_price_cents_per_cwt=1350)
    grade_lot(medium_lot["id"])

    resp = api.store_lot(medium_lot["id"], {"bin_id": bin1["id"]}, scale_operator_headers)
    validate_error(resp, ApiErrorId.ERR_BIN_VARIETY_MISMATCH)

    stored = validate_success(
        api.store_lot(medium_lot["id"], {"bin_id": bin2["id"]}, scale_operator_headers)
    )
    assert stored["status"] == "BINNED"
    assert get_bin(bin2["id"])["variety_lock"] == "MEDIUM_GRAIN"


def test_store_into_fumigating_bin_rejected(api, scale_operator_headers):
    """PRD §3.5: "the bin must be `AVAILABLE`, since a bin in `FUMIGATING` or
    `AERATING` can neither receive nor release grain
    (`ERR_BIN_NOT_RECEIVE_READY`)"

    Design: Corner/validations/store_into_fumigating_bin_rejected
    """
    season, grower = _open_season_with_grower()
    bin_ = create_bin(season["id"], bin_code="B-01", capacity_cwt=500.00)
    create_fumigation_event(season["id"], bin_["id"])  # bin -> FUMIGATING

    lot = create_spot_lot(season["id"], grower["id"], gross_weight_lbs=22000,
                          tare_weight_lbs=12000)
    grade_lot(lot["id"])
    resp = api.store_lot(lot["id"], {"bin_id": bin_["id"]}, scale_operator_headers)
    validate_error(resp, ApiErrorId.ERR_BIN_NOT_RECEIVE_READY)


def test_lot_in_two_drying_runs_rejected(api, dryer_operator_headers):
    """PRD §3.5: "A `DryerOperator` plans a **DryingRun** by naming a
    `destination_bin_id` and a set of `lot_ids`, each of which must stand in
    `GRADED` and be unclaimed by any other non-terminal run
    (`ERR_LOT_ALREADY_IN_DRYING_RUN`)"
    PRD §3.5: "Cancelling a `PLANNED` run instead releases the reservation,
    clears each lot's `drying_run_id` back to null, and leaves the lots in
    `GRADED`."

    Design: Corner/validations/lot_in_two_drying_runs_rejected
    """
    season, grower = _open_season_with_grower()
    bin1 = create_bin(season["id"], bin_code="B-01", capacity_cwt=500.00)
    bin2 = create_bin(season["id"], bin_code="B-02", capacity_cwt=500.00)
    lot = _graded_spot_288_lot(season["id"], grower["id"])
    run1 = create_drying_run(season["id"], [lot["id"]], bin1["id"])

    resp = api.create_drying_run(
        {"season_id": season["id"], "lot_ids": [lot["id"]],
         "destination_bin_id": bin2["id"]},
        dryer_operator_headers,
    )
    validate_error(resp, ApiErrorId.ERR_LOT_ALREADY_IN_DRYING_RUN)

    cancel_drying_run(run1["id"])
    run2 = validate_success(
        api.create_drying_run(
            {"season_id": season["id"], "lot_ids": [lot["id"]],
             "destination_bin_id": bin2["id"]},
            dryer_operator_headers,
        ),
        expected_status=201,
    )
    assert run2["status"] == "PLANNED", "a lot released by cancel is re-plannable"


def test_drying_complete_commits_actual_output(api, dryer_operator_headers):
    """PRD §3.5: "Completion releases the reservation (the bin's `reserved_cwt`
    falls by `expected_output_cwt`), adds the actual output to `stock_cwt`,
    moves every referenced lot `GRADED` → `BINNED` with `bin_id` set to the
    destination, and keeps each lot's `drying_run_id` in place for
    traceability; the bin's `version` increments."

    Design: Corner/endpoints/drying_complete_commits_actual_output
    """
    season, grower = _open_season_with_grower()
    bin_ = create_bin(season["id"], bin_code="B-01", capacity_cwt=500.00)
    lot = _graded_spot_288_lot(season["id"], grower["id"])
    run = create_drying_run(season["id"], [lot["id"]], bin_["id"])

    completed = validate_success(
        api.complete_drying_run(run["id"], {"actual_output_cwt": 285.00},
                                dryer_operator_headers)
    )
    assert completed["status"] == "COMPLETED"

    bin_after = get_bin(bin_["id"])
    assert_cwt(bin_after["stock_cwt"], 285.00, "actual output committed, not expected")
    assert_cwt(bin_after["reserved_cwt"], 0, "reservation released")
    assert_cwt(bin_after["available_cwt"], 215.00, "available after completion")
    assert bin_after["variety_lock"] == "LONG_GRAIN"

    lot_after = get_lot(lot["id"])
    assert lot_after["status"] == "BINNED"
    assert lot_after["bin_id"] == bin_["id"]


# ---------------------------------------------------------------------------
# Corner: fumigation clock gates and hold release
# ---------------------------------------------------------------------------

def test_fumigation_exposure_gate(api, fumigation_tech_headers):
    """PRD §3.7: "Beginning aeration requires the event to stand `ACTIVE`
    (`ERR_FUMIGATION_INVALID_STATE`) and the season clock to have reached
    `exposure_ends_at` — an early attempt draws `ERR_EXPOSURE_INCOMPLETE`"
    PRD §3.7: "Clearing the treatment requires the event in `AERATING`"

    Design: Corner/state_machines/fumigation_exposure_gate
    """
    season, _, event = _active_fumigation(bin_code="B-01")
    set_clock(season["id"], "2026-08-02T00:00:00Z")  # 24h into a 48h exposure

    resp = api.begin_aeration(event["id"], fumigation_tech_headers)
    validate_error(resp, ApiErrorId.ERR_EXPOSURE_INCOMPLETE)

    resp = api.clear_fumigation(event["id"], fumigation_tech_headers)
    validate_error(resp, ApiErrorId.ERR_FUMIGATION_INVALID_STATE)


def test_hold_double_release_rejected(api, safety_officer_headers):
    """PRD §3.7: "Releasing a hold requires it to stand `ACTIVE` — a second
    release meets `ERR_HOLD_ALREADY_RELEASED` — and records the officer's
    `resolution_note` as the hold moves to `RELEASED`."

    Design: Corner/state_machines/hold_double_release_rejected
    """
    season = create_open_season()
    bin_ = create_bin(season["id"], bin_code="B-01", capacity_cwt=500.00)
    hold = create_hold(season["id"], "BIN", bin_["id"], reason_code="PEST_ACTIVITY")

    released = validate_success(
        api.release_hold(hold["id"], {"resolution_note": "inspected clean"},
                         safety_officer_headers)
    )
    assert released["status"] == "RELEASED"

    resp = api.release_hold(hold["id"], {"resolution_note": "again"},
                            safety_officer_headers)
    validate_error(resp, ApiErrorId.ERR_HOLD_ALREADY_RELEASED)
