"""Opening inspections, bay reservation, temporal overlap, and the reinspection cycle.

Difficulty translations: screening-referred gate, bay half-open window overlap, the
reserved-minutes conservation invariant, state-beats-temporal precedence, and the
OOS reinspection cycle. Corner translations: reinspect-from-CLEARED, out-of-order bay,
and end-before-start validation.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    api_client,
    setup_domain,
    setup_referred_overweight_screening,
    setup_inspection_finalized_oos,
    create_screening,
    create_inspection,
    add_violation,
    finalize,
)

ADMIN = TEST_USERS["compliance_admin_headers"]
SCREENER = TEST_USERS["screener_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]


def _bay_reserved_minutes(station_id, bay_id):
    resp = api_client.list_bays(station_id, ADMIN)
    data, _ = validate_paginated(resp)
    for bay in data:
        if bay["id"] == bay_id:
            return bay["reserved_minutes"]
    raise AssertionError("bay not found in listing")


# --- Corner: screening-referred gate (inspection create) ---

def test_inspect_cleared_screening_rejected(api):
    """PRD §3.4: "Only a `REFERRED` screening can be inspected."
    PRD §3.4: "Attempting to inspect a screening that is not in `REFERRED` status is
    rejected with `ERR_SCREENING_NOT_REFERRED`."

    Design: Difficulty/cross_entity_state_dependency/inspection_create_gated_by_screening_referred
    """
    d = setup_domain(carrier_overrides={"usdot_number": "DOT-844-N", "legal_name": "November Nav"},
                     station_overrides={"name": "I-64", "state_code": "KY"})
    cleared = create_screening(d["station"]["id"], d["carrier"]["id"], d["driver"]["id"],
                               vehicle_plate="PLT-14", gross_weight_lbs=79000,
                               heaviest_axle_lbs=19000)
    assert cleared["status"] == "CLEARED"
    resp = api.create_inspection(
        {"screening_id": cleared["id"], "bay_id": d["bay"]["id"], "level": "LEVEL_I",
         "scheduled_start": "2026-03-02T10:00:00Z", "scheduled_end": "2026-03-02T11:00:00Z"},
        INSPECTOR)
    validate_error(resp, ApiErrorId.ERR_SCREENING_NOT_REFERRED)


def test_referred_screening_can_be_inspected(api):
    """PRD §3.4: "Only a `REFERRED` screening can be inspected."
    PRD §3.4: "The inspection copies its `driver_id` from the screening, starts in
    `status` `IN_PROGRESS` with `result` `NONE`, `oos_flag` false, `reinspection_count`
    zero, and `oos_points_applied` zero."

    Design: Difficulty/cross_entity_state_dependency/inspection_create_gated_by_screening_referred
    """
    d = setup_referred_overweight_screening(
        carrier_overrides={"usdot_number": "DOT-844-N2", "legal_name": "November Nav"},
        station_overrides={"name": "I-64", "state_code": "KY"})
    assert d["screening"]["status"] == "REFERRED"
    resp = api.create_inspection(
        {"screening_id": d["screening"]["id"], "bay_id": d["bay"]["id"], "level": "LEVEL_I",
         "scheduled_start": "2026-03-02T10:00:00Z", "scheduled_end": "2026-03-02T11:00:00Z"},
        INSPECTOR)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "IN_PROGRESS"


# --- Corner: reinspect-from-cleared, out-of-order bay, end-before-start ---

def test_reinspect_cleared_inspection_rejected(api):
    """PRD §3.5: "`CLEARED` and `CANCELLED` are the inspection's terminal states."
    PRD §2.6: "the target resource is in a status that admits the requested transition;
    otherwise `ERR_SCREENING_NOT_REFERRED`, `ERR_INSPECTION_INVALID_STATE`, or
    `ERR_CITATION_INVALID_STATE` (409)."

    Design: Corner/state_machines/inspection_reinspect_from_cleared_returns_invalid_state
    """
    d = setup_referred_overweight_screening(
        carrier_overrides={"usdot_number": "DOT-C5", "legal_name": "Corner Five"},
        station_overrides={"name": "S5", "state_code": "ID"})
    inspection = create_inspection(d["screening"]["id"], d["bay"]["id"])
    finalize(inspection["id"], "CLEAR")
    resp = api.reinspect(inspection["id"], INSPECTOR)
    validate_error(resp, ApiErrorId.ERR_INSPECTION_INVALID_STATE)


def test_inspection_on_out_of_order_bay_rejected(api):
    """PRD §3.4: "A bay whose `status` is `OUT_OF_ORDER` cannot host an inspection and
    yields `ERR_BAY_UNAVAILABLE`."

    Design: Corner/validations/inspection_create_on_out_of_order_bay_rejected
    """
    d = setup_domain(carrier_overrides={"usdot_number": "DOT-C7", "legal_name": "Corner Seven"},
                     station_overrides={"name": "S7", "state_code": "MT"})
    ooo_bay = validate_success(
        api.create_bay(d["station"]["id"], {"label": "Bay X", "status": "OUT_OF_ORDER"}, ADMIN),
        expected_status=201)
    screening = create_screening(d["station"]["id"], d["carrier"]["id"], d["driver"]["id"],
                                 vehicle_plate="PLT-C7", gross_weight_lbs=86000,
                                 heaviest_axle_lbs=21000)
    resp = api.create_inspection(
        {"screening_id": screening["id"], "bay_id": ooo_bay["id"], "level": "LEVEL_I",
         "scheduled_start": "2026-03-02T10:00:00Z", "scheduled_end": "2026-03-02T11:00:00Z"},
        INSPECTOR)
    validate_error(resp, ApiErrorId.ERR_BAY_UNAVAILABLE)


def test_inspection_end_before_start_rejected(api):
    """PRD §3.4: "the CVSA `level` (one of `LEVEL_I`, `LEVEL_II`, or `LEVEL_III`), and
    the occupancy window `scheduled_start` and `scheduled_end` (which must be strictly
    after `scheduled_start`)."
    PRD §2.6: "Field and constraint validity — required fields, enum membership,
    ranges, USDOT uniqueness, and bay availability; otherwise `ERR_VALIDATION`,
    `ERR_DUPLICATE_USDOT`, or `ERR_BAY_UNAVAILABLE` (422 for the first, 409 for the
    latter two)."

    Design: Corner/validations/inspection_scheduled_end_before_start_returns_422
    """
    d = setup_referred_overweight_screening(
        carrier_overrides={"usdot_number": "DOT-C13", "legal_name": "Corner Thirteen"},
        station_overrides={"name": "S13", "state_code": "CA"})
    resp = api.create_inspection(
        {"screening_id": d["screening"]["id"], "bay_id": d["bay"]["id"], "level": "LEVEL_I",
         "scheduled_start": "2026-03-02T11:00:00Z", "scheduled_end": "2026-03-02T10:00:00Z"},
        INSPECTOR)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


# --- Difficulty: bay half-open window overlap ---

def _setup_bay_with_two_windows(usdot, name):
    """Bay holds inspection A [10:00,11:00) and adjacent B [11:00,12:00); returns
    dict(station, bay, carrier, driver) plus a fresh REFERRED screening_c for the
    trigger window."""
    d = setup_domain(carrier_overrides={"usdot_number": usdot, "legal_name": name},
                     station_overrides={"name": "I-44", "state_code": "MO"})
    sa = create_screening(d["station"]["id"], d["carrier"]["id"], d["driver"]["id"],
                          vehicle_plate="PLT-15A", gross_weight_lbs=86000, heaviest_axle_lbs=21000)
    ia = create_inspection(sa["id"], d["bay"]["id"],
                           scheduled_start="2026-03-02T10:00:00Z", scheduled_end="2026-03-02T11:00:00Z")
    d["inspection_a"] = ia
    return d


def test_adjacent_bay_window_is_accepted(api):
    """PRD §3.4: "The requested window must not overlap any other active window already
    reserved on that same bay; overlap is judged on a half-open basis (two windows
    conflict when one starts strictly before the other ends and vice versa, so a window
    that begins exactly when another ends does not conflict), and a conflict is rejected
    with `ERR_BAY_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/bay_window_halfopen_adjacency_allowed
    """
    d = _setup_bay_with_two_windows("DOT-844-O", "Oscar Ops")
    sb = create_screening(d["station"]["id"], d["carrier"]["id"], d["driver"]["id"],
                          vehicle_plate="PLT-15B", gross_weight_lbs=86000, heaviest_axle_lbs=21000)
    resp = api.create_inspection(
        {"screening_id": sb["id"], "bay_id": d["bay"]["id"], "level": "LEVEL_I",
         "scheduled_start": "2026-03-02T11:00:00Z", "scheduled_end": "2026-03-02T12:00:00Z"},
        INSPECTOR)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "IN_PROGRESS"


def test_interior_overlap_bay_window_rejected(api):
    """PRD §3.4: "The requested window must not overlap any other active window already
    reserved on that same bay; overlap is judged on a half-open basis (two windows
    conflict when one starts strictly before the other ends and vice versa, so a window
    that begins exactly when another ends does not conflict), and a conflict is rejected
    with `ERR_BAY_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/bay_window_halfopen_adjacency_allowed
    """
    d = _setup_bay_with_two_windows("DOT-844-O2", "Oscar Ops")
    sc = create_screening(d["station"]["id"], d["carrier"]["id"], d["driver"]["id"],
                          vehicle_plate="PLT-15C", gross_weight_lbs=86000, heaviest_axle_lbs=21000)
    resp = api.create_inspection(
        {"screening_id": sc["id"], "bay_id": d["bay"]["id"], "level": "LEVEL_I",
         "scheduled_start": "2026-03-02T10:30:00Z", "scheduled_end": "2026-03-02T11:30:00Z"},
        INSPECTOR)
    validate_error(resp, ApiErrorId.ERR_BAY_WINDOW_CONFLICT)


# --- Difficulty: reserved-minutes conservation (create + cancel) ---

def test_open_then_cancel_restores_reserved_minutes(api):
    """PRD §3.4: "Releasing that reservation — on clear, out-of-service finalize, or
    cancellation — subtracts exactly the same window minutes back, so that an
    open-then-cancel or open-then-finalize pair leaves the bay's `reserved_minutes`
    unchanged from where it began."
    PRD §3.5: "An `IN_PROGRESS` inspection may instead be cancelled by an `Inspector`,
    moving it `IN_PROGRESS → CANCELLED` and releasing its bay reservation; the screening
    remains `REFERRED` so it can be inspected again."

    Design: Difficulty/compensating_invariant/bay_reserved_minutes_create_cancel
    """
    d = setup_referred_overweight_screening(
        carrier_overrides={"usdot_number": "DOT-844-Q", "legal_name": "Quebec Cargo"},
        station_overrides={"name": "I-24", "state_code": "TN"})
    inspection = create_inspection(d["screening"]["id"], d["bay"]["id"],
                                   scheduled_start="2026-03-02T10:00:00Z",
                                   scheduled_end="2026-03-02T11:00:00Z")
    cancelled = validate_success(api.cancel_inspection(inspection["id"], INSPECTOR))
    assert cancelled["status"] == "CANCELLED"
    assert _bay_reserved_minutes(d["station"]["id"], d["bay"]["id"]) == 0


def test_reserved_minutes_added_on_open_then_released_on_cancel(api):
    """PRD §3.4: "When the inspection is opened, the bay's `reserved_minutes` is
    increased by the window's length in minutes (the difference between `scheduled_end`
    and `scheduled_start`)."
    PRD §3.4: "Releasing that reservation — on clear, out-of-service finalize, or
    cancellation — subtracts exactly the same window minutes back, so that an
    open-then-cancel or open-then-finalize pair leaves the bay's `reserved_minutes`
    unchanged from where it began."

    Design: Difficulty/compensating_invariant/bay_reserved_minutes_create_cancel
    """
    d = setup_referred_overweight_screening(
        carrier_overrides={"usdot_number": "DOT-844-Q2", "legal_name": "Quebec Cargo"},
        station_overrides={"name": "I-24", "state_code": "TN"})
    inspection = create_inspection(d["screening"]["id"], d["bay"]["id"],
                                   scheduled_start="2026-03-02T10:00:00Z",
                                   scheduled_end="2026-03-02T11:00:00Z")
    assert _bay_reserved_minutes(d["station"]["id"], d["bay"]["id"]) == 60
    api.cancel_inspection(inspection["id"], INSPECTOR)
    assert _bay_reserved_minutes(d["station"]["id"], d["bay"]["id"]) == 0


# --- Difficulty: state precedence over temporal ---

def _setup_busy_bay_and_cleared_screening(usdot, name):
    d = setup_referred_overweight_screening(
        carrier_overrides={"usdot_number": usdot, "legal_name": name},
        station_overrides={"name": "I-70", "state_code": "CO"})
    busy = create_inspection(d["screening"]["id"], d["bay"]["id"],
                             scheduled_start="2026-03-02T10:00:00Z",
                             scheduled_end="2026-03-02T11:00:00Z")
    d["busy_inspection"] = busy
    cleared = create_screening(d["station"]["id"], d["carrier"]["id"], d["driver"]["id"],
                               vehicle_plate="PLT-9", gross_weight_lbs=79000, heaviest_axle_lbs=19000)
    d["cleared_screening"] = cleared
    return d


def test_state_error_preempts_bay_window_conflict(api):
    """PRD §2.6: "When more than one rule could reject a request, the checks run in a
    fixed order, and the first failing check determines the error returned."
    PRD §2.6: "A rule that sits lower in this list never masks a rule above it: for
    example, a request that would both fail the state check and the fiscal check
    surfaces the state error, because state precedes fiscal."

    Design: Difficulty/priority_pair_validation_conflict/inspection_state_beats_bay_temporal
    """
    d = _setup_busy_bay_and_cleared_screening("DOT-844-I", "India Freight")
    # Targets a CLEARED (non-REFERRED) screening AND overlaps the busy [10:00,11:00) window.
    resp = api.create_inspection(
        {"screening_id": d["cleared_screening"]["id"], "bay_id": d["bay"]["id"], "level": "LEVEL_I",
         "scheduled_start": "2026-03-02T10:30:00Z", "scheduled_end": "2026-03-02T11:30:00Z"},
        INSPECTOR)
    validate_error(resp, ApiErrorId.ERR_SCREENING_NOT_REFERRED)


def test_state_precedence_leaves_busy_inspection_untouched(api):
    """PRD §2.6: "A rule that sits lower in this list never masks a rule above it: for
    example, a request that would both fail the state check and the fiscal check
    surfaces the state error, because state precedes fiscal."
    PRD §3.4: "Attempting to inspect a screening that is not in `REFERRED` status is
    rejected with `ERR_SCREENING_NOT_REFERRED`."

    Design: Difficulty/priority_pair_validation_conflict/inspection_state_beats_bay_temporal
    """
    d = _setup_busy_bay_and_cleared_screening("DOT-844-I2", "India Freight")
    resp = api.create_inspection(
        {"screening_id": d["cleared_screening"]["id"], "bay_id": d["bay"]["id"], "level": "LEVEL_I",
         "scheduled_start": "2026-03-02T10:30:00Z", "scheduled_end": "2026-03-02T11:30:00Z"},
        INSPECTOR)
    validate_error(resp, ApiErrorId.ERR_SCREENING_NOT_REFERRED)
    busy = validate_success(api.get_inspection(d["busy_inspection"]["id"], INSPECTOR))
    assert busy["status"] == "IN_PROGRESS"


# --- Difficulty: OOS reinspection cycle ---

def test_reinspect_reenters_reinspection_and_increments_count(api):
    """PRD §3.5: "An `OOS_ISSUED` inspection may be reopened by an `Inspector`, moving
    it `OOS_ISSUED → REINSPECTION`, incrementing its `reinspection_count`, and
    re-reserving the same bay window (the window must again be free, and the bay's
    `reserved_minutes` grows by the window minutes)."

    Design: Difficulty/non_linear_state_machine/inspection_oos_reinspection_cycle
    """
    d = setup_inspection_finalized_oos(
        severity_weight=5, carrier_overrides={"usdot_number": "DOT-844-E", "legal_name": "Echo Freight"},
        station_overrides={"name": "I-15", "state_code": "CA"})
    reopened = validate_success(api.reinspect(d["inspection"]["id"], INSPECTOR))
    assert reopened["status"] == "REINSPECTION"
    assert reopened["reinspection_count"] == 1


def test_reinspect_then_reissue_oos_returns_to_oos_issued(api):
    """PRD §3.5: "Finalizing a `REINSPECTION` as `OOS` again requires at least one
    out-of-service violation (else `ERR_NO_OOS_BASIS`), sets `result` `OOS` and
    `oos_flag` true, and releases the bay reservation — but does not re-add points
    already applied, since the original `oos_points_applied` remains booked."

    Design: Difficulty/non_linear_state_machine/inspection_oos_reinspection_cycle
    """
    d = setup_inspection_finalized_oos(
        severity_weight=5, carrier_overrides={"usdot_number": "DOT-844-E2", "legal_name": "Echo Freight"},
        station_overrides={"name": "I-15", "state_code": "CA"})
    api.reinspect(d["inspection"]["id"], INSPECTOR)
    reissued = validate_success(api.finalize_inspection(d["inspection"]["id"], {"result": "OOS"}, INSPECTOR))
    assert reissued["status"] == "OOS_ISSUED"
    assert reissued["reinspection_count"] == 1
