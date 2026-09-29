"""Stale-view protection on the three version-guarded writes, plus the pest-alert
counter ladder that walks a compartment from NORMAL through SCOUT_ALERT to LOCKED.
"""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_climate_strategy,
    create_climate_strategy_payload,
    create_posture_override_payload,
    create_scout_worker,
    create_zone,
    file_observation,
    grade_harvest_lot_payload,
    make_harvest_supervisor_headers,
    read_lot,
    read_zone,
    regrade_lot,
    set_clock,
    setup_graded_lot,
    setup_scout_alert_zone,
    setup_transplanted_cycle,
    validate_error,
    validate_paginated,
    validate_success,
)

GM = TEST_USERS["grower_manager_headers"]


def test_stale_zone_version_on_a_second_climate_window_is_rejected(api):
    """PRD §2.8: "If that value does not equal the compartment's current `version`, the create is rejected with `ERR_STALE_ZONE_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/stale_zone_version_on_climate_strategy_create_is_rejected
    """
    set_clock("2026-08-06T00:00:00Z")
    zone = create_zone(code="ZC-80")
    assert zone["version"] == 1, f"a new compartment reads version 1, got {zone['version']}"

    day_window = create_climate_strategy(zone["id"], zone["version"])
    fresh = read_zone(zone["id"])
    assert fresh["version"] == 2, (
        f"an accepted window is a mutation of the compartment, got version {fresh['version']}"
    )

    # A non-overlapping NIGHT window carrying the pre-create view of the compartment.
    stale_payload = create_climate_strategy_payload(
        zone["id"],
        zone["version"],
        regime="NIGHT",
        window_start="2026-08-07T18:00:00Z",
        window_end="2026-08-08T06:00:00Z",
        temp_setpoint_c=17.5,
        rh_setpoint_pct=85,
        co2_setpoint_ppm=420,
        lighting_hours=0,
        screen_position_pct=100,
    )

    response = api.create_climate_strategy(stale_payload, GM)

    validate_error(response, ApiErrorId.ERR_STALE_ZONE_VERSION.value)

    rows, meta = validate_paginated(
        api.list_climate_strategies(GM, params={"zone_id": zone["id"]})
    )
    assert meta["total_count"] == 1, (
        f"the rejected create must mint no window, got {meta['total_count']}"
    )
    assert rows[0]["id"] == day_window["id"], "the surviving window is the accepted one"
    assert rows[0]["status"] == "ACTIVE", (
        f"the accepted window stays ACTIVE, got {rows[0]['status']}"
    )
    assert read_zone(zone["id"])["version"] == 2, (
        "a rejected write leaves the compartment's version alone"
    )


def test_stale_zone_version_on_a_posture_override_is_rejected(api):
    """PRD §2.8: "A posture override likewise requires `expected_zone_version` as a non-optional input field carrying the client's last observed compartment `version`, and a mismatch is rejected with `ERR_STALE_ZONE_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/stale_zone_version_on_a_posture_override_is_rejected
    """
    state = setup_scout_alert_zone(clock="2026-08-06T00:00:00Z")
    zone_id = state["zone"]["id"]
    version_at_registration = state["zone"]["version"]
    assert version_at_registration == 1, (
        f"a new compartment reads version 1, got {version_at_registration}"
    )

    alerted = read_zone(zone_id)
    assert alerted["ipm_posture"] == "SCOUT_ALERT", (
        f"one at-or-above observation raises the pest gate, got {alerted['ipm_posture']}"
    )
    assert alerted["version"] > version_at_registration, (
        "the observation cascade is a mutation of the compartment, so the cached view is stale"
    )

    stale = create_posture_override_payload(override_reason="Stale client view")
    stale["expected_zone_version"] = version_at_registration

    response = api.create_posture_override(zone_id, stale, GM)

    validate_error(response, ApiErrorId.ERR_STALE_ZONE_VERSION.value)

    unchanged = read_zone(zone_id)
    assert unchanged["ipm_posture"] == "SCOUT_ALERT", (
        f"the rejected override changes nothing, got {unchanged['ipm_posture']}"
    )
    assert unchanged["open_pest_alert_count"] == 1, (
        f"the open alert survives the rejected override, got {unchanged['open_pest_alert_count']}"
    )

    # Re-reading the compartment and retrying succeeds: the guard is on the version.
    retry = create_posture_override_payload(override_reason="Re-read then override")
    retry["expected_zone_version"] = unchanged["version"]
    overridden = validate_success(
        api.create_posture_override(zone_id, retry, GM), 200
    )
    assert overridden["ipm_posture"] == "NORMAL", (
        f"an ipm_posture override forces NORMAL, got {overridden['ipm_posture']}"
    )
    assert overridden["open_pest_alert_count"] == 0, (
        f"the override clears open_pest_alert_count to 0, got {overridden['open_pest_alert_count']}"
    )


def test_stale_lot_version_on_a_second_regrade_is_rejected(api):
    """PRD §2.8: "Regrading a harvest lot requires `expected_lot_version` as a non-optional input field carrying the client's last observed `version` of that lot, and a mismatch is rejected with `ERR_STALE_LOT_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/stale_lot_version_on_a_second_regrade_is_rejected
    """
    state = setup_graded_lot()
    lot_id = state["lot"]["id"]
    grader_id = state["harvest_worker"]["id"]
    version_after_grading = state["lot"]["version"]

    restated = regrade_lot(
        lot_id,
        grader_id,
        version_after_grading,
        grade_a_lbs=1150.00,
        grade_b_lbs=750.00,
        cull_lbs=100.00,
    )
    assert restated["grade_a_lbs"] == 1150.00, (
        f"the first regrade restates grade A, got {restated['grade_a_lbs']}"
    )
    assert restated["version"] > version_after_grading, (
        "a successful regrade increments the lot's version"
    )

    # The second pass re-uses the view captured before the first regrade.
    stale_payload = grade_harvest_lot_payload(
        grade_a_lbs=1100.00, grade_b_lbs=800.00, cull_lbs=100.00
    )
    stale_payload["expected_lot_version"] = version_after_grading

    response = api.regrade_harvest_lot(
        lot_id, stale_payload, make_harvest_supervisor_headers(grader_id)
    )

    validate_error(response, ApiErrorId.ERR_STALE_LOT_VERSION.value)

    unchanged = read_lot(lot_id)
    assert unchanged["grade_a_lbs"] == 1150.00, (
        f"the rejected regrade leaves the split alone, got {unchanged['grade_a_lbs']}"
    )
    assert unchanged["available_a_lbs"] == 1150.00, (
        f"nothing is allocated, so grade A is fully available, got {unchanged['available_a_lbs']}"
    )
    assert unchanged["regrade_count"] == 1, (
        f"only one regrade has landed, got {unchanged['regrade_count']}"
    )
    assert unchanged["version"] == restated["version"], (
        "the rejected regrade must not move the lot's version"
    )


def _zone_with_one_quiet_scouting_round():
    """A TRANSPLANTED cycle, a SCOUT worker and one below-threshold whitefly round."""
    state = setup_transplanted_cycle(clock="2026-08-06T00:00:00Z")
    state["scout"] = create_scout_worker()
    state["quiet_round"] = file_observation(
        state["zone"]["id"],
        state["cycle"]["id"],
        state["scout"]["id"],
        observed_at="2026-08-06T06:00:00Z",
        pest_code="WHITEFLY",
        pest_count_per_plant=0.400,
    )
    return state


class TestPestAlertCounterLadder:
    """The pest gate walks NORMAL, SCOUT_ALERT and LOCKED off the alert counter alone."""

    def test_a_below_threshold_round_leaves_the_pest_gate_normal(self, api):
        """PRD §3.6: "A below-threshold observation is filed normally, sets `release_required` false, and leaves the compartment's posture entirely untouched."

        Design: Corner/complexity_layers/open_pest_alert_count_trips_the_lock_at_exactly_two_alerts
        """
        state = _zone_with_one_quiet_scouting_round()

        quiet = state["quiet_round"]
        assert quiet["threshold_status"] == "BELOW", (
            f"0.400 is below the whitefly threshold of 0.500, got {quiet['threshold_status']}"
        )
        assert quiet["release_required"] is False, (
            f"a quiet round demands no treatment, got {quiet['release_required']}"
        )

        zone = read_zone(state["zone"]["id"])
        assert zone["open_pest_alert_count"] == 0, (
            f"a quiet round opens no alert, got {zone['open_pest_alert_count']}"
        )
        assert zone["ipm_posture"] == "NORMAL", (
            f"the pest gate stays NORMAL, got {zone['ipm_posture']}"
        )

    def test_the_first_at_threshold_round_opens_a_single_alert(self, api):
        """PRD §3.6: "When the compartment's `open_pest_alert_count` was 0 before the observation and either its `reentry_clear_at` is null or the current logical clock has reached it, the counter rises to 1 and the compartment moves `NORMAL` → `SCOUT_ALERT`, with the compartment's `version` incrementing by one."

        Design: Corner/complexity_layers/open_pest_alert_count_trips_the_lock_at_exactly_two_alerts
        """
        state = _zone_with_one_quiet_scouting_round()

        # A whitefly count of exactly 0.500 sits on the action threshold.
        at_threshold = file_observation(
            state["zone"]["id"],
            state["cycle"]["id"],
            state["scout"]["id"],
            observed_at="2026-08-06T07:00:00Z",
            pest_code="WHITEFLY",
            pest_count_per_plant=0.500,
        )
        assert at_threshold["threshold_status"] == "AT", (
            f"a pressure equal to the threshold lands on AT, got {at_threshold['threshold_status']}"
        )
        assert at_threshold["release_required"] is True, (
            f"an AT round demands treatment, got {at_threshold['release_required']}"
        )

        zone = read_zone(state["zone"]["id"])
        assert zone["open_pest_alert_count"] == 1, (
            f"the counter rises to 1, got {zone['open_pest_alert_count']}"
        )
        assert zone["ipm_posture"] == "SCOUT_ALERT", (
            f"one open alert reads SCOUT_ALERT, got {zone['ipm_posture']}"
        )

    def test_the_second_alert_locks_the_compartment(self, api):
        """PRD §3.6: "When `open_pest_alert_count` was already 1 — one short of the lock count of 2 — the next at-or-above observation takes the compartment `SCOUT_ALERT` → `LOCKED`, and that crossing fires the deepest cascade in the system."

        Design: Corner/complexity_layers/open_pest_alert_count_trips_the_lock_at_exactly_two_alerts
        """
        state = _zone_with_one_quiet_scouting_round()
        file_observation(
            state["zone"]["id"],
            state["cycle"]["id"],
            state["scout"]["id"],
            observed_at="2026-08-06T07:00:00Z",
            pest_code="WHITEFLY",
            pest_count_per_plant=0.500,
        )

        # 0.760 sits just above the aphid threshold of 0.750.
        second_alert = file_observation(
            state["zone"]["id"],
            state["cycle"]["id"],
            state["scout"]["id"],
            observed_at="2026-08-06T08:00:00Z",
            pest_code="APHID",
            pest_count_per_plant=0.760,
        )
        assert second_alert["threshold_status"] == "ABOVE", (
            f"0.760 is above the aphid threshold, got {second_alert['threshold_status']}"
        )

        zone = read_zone(state["zone"]["id"])
        assert zone["open_pest_alert_count"] == 2, (
            f"the counter reaches 2, got {zone['open_pest_alert_count']}"
        )
        assert zone["ipm_posture"] == "LOCKED", (
            f"two open alerts lock the compartment, got {zone['ipm_posture']}"
        )
        assert zone["reentry_clear_at"] is None, (
            "no biological release has gone out, so the re-entry clock is unset, got "
            f"{zone['reentry_clear_at']}"
        )
