"""Water chemistry logging, classification boundaries, facility posture
cycles, and reopen criteria (PRD §3.3)."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    TEST_USERS, ApiErrorId,
    assert_chemistry_log, assert_facility,
    create_chemistry_log_payload,
    make_facility, make_lifeguard, make_chemistry_log, set_clock,
    make_lifeguard_headers, get_facility,
)

MANAGER = TEST_USERS["manager_headers"]
GATE = TEST_USERS["gate_headers"]


def test_chemistry_log_ph_at_upper_boundary_is_in_range(api):
    """PRD §3.3: "The reading is `OUT_OF_RANGE` when free chlorine is strictly
    below 1.0 ppm or strictly above 5.0 ppm, or when pH is strictly below 7.2
    or strictly above 7.8. A value sitting exactly on a boundary — free
    chlorine of exactly 1.0 or exactly 5.0, pH of exactly 7.2 or exactly 7.8 —
    is inside range."

    Design: Difficulty/boundary_precision_check/chemistry_ph_boundary_strict_inequality
    """
    facility = make_facility(max_bather_capacity=50, lap_lane_count=2)
    lifeguard = make_lifeguard(full_name="LG Chem", certification_id="RC-2")
    set_clock("2026-06-15T10:00:00Z")
    log = validate_success(
        api.create_chemistry_log(
            facility["id"],
            create_chemistry_log_payload(
                lifeguard["id"],
                recorded_at="2026-06-15T10:00:00Z",
                free_chlorine_ppm=2.5, ph=7.8, combined_chlorine_ppm=0.2,
            ),
            make_lifeguard_headers(lifeguard["id"]),
        ),
        expected_status=201,
    )
    assert_chemistry_log(log)
    assert log["classification"] == "IN_RANGE", (
        f"pH exactly 7.8 must be IN_RANGE, got {log['classification']}"
    )
    facility_after = get_facility(facility["id"])
    assert facility_after["operational_status"] == "OPEN"


def test_chemistry_log_ph_above_upper_boundary_closes_facility(api):
    """PRD §3.3: "A new `OUT_OF_RANGE` reading on an `OPEN` facility
    transitions the facility to `CLOSED_CHEMISTRY` and creates a
    `PoolClosureEvent` with `closure_reason` of `CHEMISTRY`."
    PRD §3.3: "A value sitting exactly on a boundary — free chlorine of
    exactly 1.0 or exactly 5.0, pH of exactly 7.2 or exactly 7.8 — is inside
    range."

    Design: Difficulty/boundary_precision_check/chemistry_ph_boundary_strict_inequality
    """
    facility = make_facility(max_bather_capacity=50, lap_lane_count=2)
    lifeguard = make_lifeguard(full_name="LG Chem", certification_id="RC-2")
    set_clock("2026-06-15T10:00:00Z")
    log = validate_success(
        api.create_chemistry_log(
            facility["id"],
            create_chemistry_log_payload(
                lifeguard["id"],
                recorded_at="2026-06-15T11:00:00Z",
                free_chlorine_ppm=2.5, ph=7.81, combined_chlorine_ppm=0.2,
            ),
            make_lifeguard_headers(lifeguard["id"]),
        ),
        expected_status=201,
    )
    assert_chemistry_log(log)
    assert log["classification"] == "OUT_OF_RANGE", (
        f"pH 7.81 must be OUT_OF_RANGE, got {log['classification']}"
    )
    facility_after = get_facility(facility["id"])
    assert facility_after["operational_status"] == "CLOSED_CHEMISTRY"


def test_facility_posture_cycle_out_of_range_then_reopen(api):
    """PRD §3.3: "A new `OUT_OF_RANGE` reading on an `OPEN` facility
    transitions the facility to `CLOSED_CHEMISTRY` and creates a
    `PoolClosureEvent` with `closure_reason` of `CHEMISTRY`."
    PRD §3.3: "An `AquaticsManager` may reopen a closed facility, which
    resolves every `ACTIVE` `PoolClosureEvent` for the facility (stamping
    `ended_at` with the current clock), returns the facility to `OPEN`, and
    increments the facility's `version`."

    Design: Difficulty/non_linear_state_machine/facility_posture_cycle_open_closed_open
    """
    facility = make_facility(max_bather_capacity=50, lap_lane_count=2)
    lifeguard = make_lifeguard(full_name="LG One", certification_id="RC-100")
    set_clock("2026-06-15T10:00:00Z")
    log1 = make_chemistry_log(
        facility["id"], lifeguard["id"],
        recorded_at="2026-06-15T10:00:00Z",
        free_chlorine_ppm=0.5, ph=7.5, combined_chlorine_ppm=0.2,
    )
    assert log1["classification"] == "OUT_OF_RANGE"
    assert get_facility(facility["id"])["operational_status"] == "CLOSED_CHEMISTRY"
    # A single IN_RANGE log clears a one-reading OUT_OF_RANGE streak.
    log2 = make_chemistry_log(
        facility["id"], lifeguard["id"],
        recorded_at="2026-06-15T12:00:00Z",
        free_chlorine_ppm=2.5, ph=7.4, combined_chlorine_ppm=0.2,
    )
    assert log2["classification"] == "IN_RANGE"
    reopened = validate_success(api.reopen_facility(facility["id"], MANAGER))
    assert_facility(reopened)
    assert reopened["operational_status"] == "OPEN"
    closures, meta = validate_paginated(
        api.list_facility_closures(facility["id"], MANAGER)
    )
    assert meta["total_count"] >= 1
    chem_closures = [c for c in closures if c["closure_reason"] == "CHEMISTRY"]
    assert len(chem_closures) == 1
    assert chem_closures[0]["status"] == "RESOLVED"
    assert chem_closures[0]["ended_at"] is not None


def test_facility_posture_cycle_warning_restricted_then_open(api):
    """PRD §3.3: "A `WARNING` reading on an `OPEN` facility transitions it to
    `RESTRICTED` and sets `chemistry_state` to `WARNING`; new lesson sessions
    cannot be started while restricted, but gate admissions continue. A
    subsequent `IN_RANGE` reading on a `RESTRICTED` facility returns it to
    `OPEN`."
    PRD §3.3: "If none of those out-of-range conditions hold and combined
    chlorine is strictly above 0.4 ppm, the reading is `WARNING`."

    Design: Difficulty/non_linear_state_machine/facility_posture_cycle_open_closed_open
    """
    facility = make_facility(max_bather_capacity=50, lap_lane_count=2)
    lifeguard = make_lifeguard()
    set_clock("2026-06-15T10:00:00Z")
    warn = make_chemistry_log(
        facility["id"], lifeguard["id"],
        recorded_at="2026-06-15T10:00:00Z",
        free_chlorine_ppm=2.5, ph=7.5, combined_chlorine_ppm=0.6,
    )
    assert warn["classification"] == "WARNING"
    restricted = get_facility(facility["id"])
    assert restricted["operational_status"] == "RESTRICTED"
    assert restricted["chemistry_state"] == "WARNING"
    ok = make_chemistry_log(
        facility["id"], lifeguard["id"],
        recorded_at="2026-06-15T11:00:00Z",
        free_chlorine_ppm=2.5, ph=7.5, combined_chlorine_ppm=0.2,
    )
    assert ok["classification"] == "IN_RANGE"
    reopened = get_facility(facility["id"])
    assert reopened["operational_status"] == "OPEN"
    assert reopened["chemistry_state"] == "IN_RANGE"


def test_reopen_chemistry_not_cleared_returns_409(api):
    """PRD §3.3: "Reopening is rejected with `ERR_REOPEN_CRITERIA_NOT_MET`
    (HTTP 409) when the chemistry-driven closure still has a most-recent
    `OUT_OF_RANGE` log or when the staffing shortage that triggered the
    closure is still present."

    Design: Corner/validations/reopen_chemistry_not_cleared_returns_409
    """
    facility = make_facility()
    lifeguard = make_lifeguard()
    set_clock("2026-06-15T10:00:00Z")
    make_chemistry_log(
        facility["id"], lifeguard["id"],
        recorded_at="2026-06-15T10:00:00Z",
        free_chlorine_ppm=0.5, ph=7.5, combined_chlorine_ppm=0.2,
    )
    resp = api.reopen_facility(facility["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_REOPEN_CRITERIA_NOT_MET)
    assert get_facility(facility["id"])["operational_status"] == "CLOSED_CHEMISTRY"


def test_chemistry_input_out_of_plausible_range_returns_422(api):
    """PRD §3.3: "Readings must sit inside plausible instrument bounds — free
    chlorine between 0 and 10 ppm, pH between 6.0 and 9.0, combined chlorine
    between 0 and 5 ppm — otherwise the request is rejected as malformed with
    `ERR_CHEMISTRY_INPUT_INVALID` (HTTP 422); these are not chemistry
    judgments, they are sanity limits on the instrument."

    Design: Corner/validations/chemistry_input_out_of_plausible_range_returns_422
    """
    facility = make_facility()
    lifeguard = make_lifeguard()
    set_clock("2026-06-15T10:00:00Z")
    resp = api.create_chemistry_log(
        facility["id"],
        create_chemistry_log_payload(
            lifeguard["id"],
            recorded_at="2026-06-15T10:00:00Z",
            free_chlorine_ppm=2.5, ph=10.0, combined_chlorine_ppm=0.2,
        ),
        make_lifeguard_headers(lifeguard["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CHEMISTRY_INPUT_INVALID)
