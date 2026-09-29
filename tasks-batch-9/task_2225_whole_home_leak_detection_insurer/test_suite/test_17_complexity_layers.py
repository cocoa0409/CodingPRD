"""The three version guards and the inclusive edge of the volume gate.

Two write paths carry a device version and one carries a property version, and
each refuses a snapshot that a legitimate intervening write has superseded.  The
proof in every case is that the identical body, re-formed against the refreshed
version, is accepted.  The last family here is the volume gate itself, which
admits the exact figure and nothing a hundredth below it.
"""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    TEST_DEFAULTS,
    assert_device_transfer,
    get_success_data,
    validate_error,
    validate_paginated,
)
from test_helpers.factories import (
    device_transfer_payload,
    policy_payload,
    valve_command_payload,
)
from test_helpers.fixtures import (
    create_policy,
    ingest_reading,
    read_device,
    read_device_version,
    read_events,
    read_live_baseline,
    read_policy,
    read_property,
    read_property_version,
    read_telemetry,
    set_clock,
    setup_armed_device,
    setup_armed_device_with_buyer,
    snooze_device,
)
from test_helpers.test_users import (
    INSURER_ANALYST_USER_ID,
    SECOND_INSURER_ANALYST_USER_ID,
    make_homeowner_headers,
    make_insurer_analyst_headers,
)

SNOOZE_MINUTES = 30
OVERRIDE_REASON = "leaving for the weekend"


def _a_device_snapshot_a_mode_change_superseded(api: ApiClient) -> dict:
    """The homeowner read the device, then changed mode against that same row."""
    state = setup_armed_device(api)
    state["stale_version"] = read_device_version(
        api, state["device_id"], state["homeowner_headers"]
    )
    moded = snooze_device(
        api, state["device_id"], state["homeowner_id"], SNOOZE_MINUTES
    )
    state["fresh_version"] = moded["version"]
    return state


def _attempt_close(api: ApiClient, state: dict, version: int):
    return api.send_valve_command(
        state["device_id"],
        valve_command_payload("CLOSE", version, override_reason=OVERRIDE_REASON),
        make_homeowner_headers(state["homeowner_id"]),
    )


class TestValveCommandRefusesASupersededDeviceSnapshot:
    def test_a_close_formed_before_the_mode_change_is_refused(self, api: ApiClient):
        """The mode write moved the version, so the older snapshot no longer proves anything.

        "A valve command (`POST /devices/{id}/valve-commands`) likewise requires
        `expected_device_version` as a non-optional body field."
        "A command carrying a device version other than the device's current `version` is
        rejected with `ERR_STALE_DEVICE_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/occ_stale_device_version_on_valve_command
        """
        state = _a_device_snapshot_a_mode_change_superseded(api)
        assert state["fresh_version"] == state["stale_version"] + 1

        validate_error(
            _attempt_close(api, state, state["stale_version"]),
            ApiErrorId.ERR_STALE_DEVICE_VERSION,
            412,
        )

        device = read_device(api, state["device_id"])
        assert device["valve_state"] == "OPEN"
        assert device["close_count"] == 0
        assert device["reopen_count"] == 0
        assert device["last_shutoff_at"] is None
        assert device["version"] == state["fresh_version"]
        # The refused command left the mode change that superseded it standing.
        assert device["monitor_mode"] == "SNOOZE"

    def test_the_identical_body_at_the_refreshed_version_moves_the_water(
        self, api: ApiClient
    ):
        """Only the version field differs between the refusal and the closure.

        "The homeowner must prove the command was formed against the newest device snapshot
        before the server will move water."
        "A manual `CLOSE` behaves like the automatic one on the parts that matter:
        `close_count` increases by 1, `last_shutoff_at` is stamped, every `ACTIVE` irrigation
        window on the property moves to `SUSPENDED_BY_SHUTOFF`, and the device's `version`
        increases by 1."

        Design: Corner/complexity_layers/occ_stale_device_version_on_valve_command
        """
        state = _a_device_snapshot_a_mode_change_superseded(api)
        validate_error(
            _attempt_close(api, state, state["stale_version"]),
            ApiErrorId.ERR_STALE_DEVICE_VERSION,
            412,
        )

        closed = get_success_data(
            _attempt_close(api, state, state["fresh_version"])
        )
        assert closed["valve_state"] == "CLOSED"
        assert closed["close_count"] == 1
        assert closed["last_shutoff_at"].startswith("2026-08-01T06:05:00")
        assert closed["version"] == state["fresh_version"] + 1


TRANSFER_NOTE = "closing 2026-08-01"
TRANSFER_EXPIRES_AT = "2026-08-08T06:05:00"


def _a_seller_snapshot_a_mode_change_superseded(api: ApiClient) -> dict:
    """A buyer waits at closing while the seller's snapshot goes out of date."""
    state = setup_armed_device_with_buyer(api)
    state["stale_version"] = read_device_version(
        api, state["device_id"], state["homeowner_headers"]
    )
    moded = snooze_device(
        api, state["device_id"], state["homeowner_id"], SNOOZE_MINUTES
    )
    state["fresh_version"] = moded["version"]
    return state


def _attempt_transfer(api: ApiClient, state: dict, version: int):
    return api.create_device_transfer(
        device_transfer_payload(
            state["device_id"],
            state["buyer_id"],
            version,
            transfer_note=TRANSFER_NOTE,
        ),
        make_homeowner_headers(state["homeowner_id"]),
    )


class TestTransferCreationRefusesTheSameSupersededSnapshot:
    def test_the_stale_seller_is_refused_and_no_transfer_row_appears(
        self, api: ApiClient
    ):
        """The same guard on a different write leaves the transfer table empty instead.

        "Creating a device transfer (`POST /device-transfers`) requires
        `expected_device_version` as a non-optional body field carrying the client's last
        observed `version` of the target `Device`."
        "If that value does not equal the device's current `version`, the request is rejected
        with `ERR_STALE_DEVICE_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/occ_stale_device_version_on_transfer_create
        """
        state = _a_seller_snapshot_a_mode_change_superseded(api)

        validate_error(
            _attempt_transfer(api, state, state["stale_version"]),
            ApiErrorId.ERR_STALE_DEVICE_VERSION,
            412,
        )

        _, meta = validate_paginated(
            api.list_device_transfers(
                state["homeowner_headers"], {"device_id": state["device_id"]}
            )
        )
        assert meta["total_count"] == 0

        # The freeze is a side effect of a successful create only.
        assert read_device(api, state["device_id"])["lifecycle_state"] == "ARMED"
        assert read_property(api, state["property_id"])["property_state"] == "ACTIVE"

    def test_the_refreshed_create_opens_the_week_long_window_and_freezes_both_rows(
        self, api: ApiClient
    ):
        """What the refusal withheld is exactly what the accepted create performs.

        "The row is created in `status` `INITIATED` with `from_homeowner_id` recording the
        property's current owner, `initiated_at` stamped at the clock, and `expires_at` set to
        168 hours — a full week — after initiation; `accepted_at`, `accepted_by_user_id`, and
        `cancel_reason` all begin null."
        "The device moves from `ARMED` or `LEARNING` to `TRANSFER_PENDING` with its `version`
        incremented by 1, and the property moves `ACTIVE → TRANSFER_PENDING` with its
        `version` incremented by 1."

        Design: Corner/complexity_layers/occ_stale_device_version_on_transfer_create
        """
        state = _a_seller_snapshot_a_mode_change_superseded(api)
        validate_error(
            _attempt_transfer(api, state, state["stale_version"]),
            ApiErrorId.ERR_STALE_DEVICE_VERSION,
            412,
        )

        transfer = get_success_data(
            _attempt_transfer(api, state, state["fresh_version"]), 201
        )
        assert_device_transfer(transfer)
        assert transfer["status"] == "INITIATED"
        assert transfer["from_homeowner_id"] == state["homeowner_id"]
        assert transfer["initiated_at"].startswith("2026-08-01T06:05:00")
        assert transfer["expires_at"].startswith(TRANSFER_EXPIRES_AT)

        device = read_device(api, state["device_id"])
        assert device["lifecycle_state"] == "TRANSFER_PENDING"
        assert device["version"] == state["fresh_version"] + 1
        assert read_property(api, state["property_id"])["property_state"] == (
            "TRANSFER_PENDING"
        )


POLICY_YEAR_START = "2026-08-01T00:00:00Z"
SECOND_PREMIUM_CENTS = 180000
SECOND_DEDUCTIBLE_CENTS = 50000
FIRST_ANALYST = make_insurer_analyst_headers(INSURER_ANALYST_USER_ID)
SECOND_ANALYST = make_insurer_analyst_headers(SECOND_INSURER_ANALYST_USER_ID)


def _a_property_version_a_rival_policy_superseded(api: ApiClient) -> dict:
    """Both carriers read the property; the first one to write moved its version."""
    state = setup_armed_device(api)
    state["stale_version"] = read_property_version(
        api, state["property_id"], FIRST_ANALYST
    )
    first = create_policy(
        api,
        state["property_id"],
        POLICY_YEAR_START,
        state["stale_version"],
        INSURER_ANALYST_USER_ID,
    )
    state["first_policy_id"] = first["id"]
    return state


def _attempt_second_policy(api: ApiClient, state: dict, version: int):
    return api.create_policy(
        policy_payload(
            state["property_id"],
            version,
            POLICY_YEAR_START,
            insurer_code=TEST_DEFAULTS["SECOND_INSURER_CODE"],
            policy_number=TEST_DEFAULTS["SECOND_POLICY_NUMBER"],
            annual_premium_cents=SECOND_PREMIUM_CENTS,
            deductible_cents=SECOND_DEDUCTIBLE_CENTS,
        ),
        SECOND_ANALYST,
    )


class TestPolicyCreationGuardsTheParentPropertyVersion:
    def test_the_rival_analyst_carrying_the_pre_policy_version_is_refused(
        self, api: ApiClient
    ):
        """A different parent entity, a different code, the same 412 discipline.

        "Creating an insurance policy (`POST /policies`) requires `expected_property_version`
        as a non-optional body field carrying the client's last observed `version` of the
        target `Property`."
        "A mismatch with the property's current `version` is rejected with
        `ERR_STALE_PROPERTY_VERSION` (HTTP 412), meaning the analyst never saw the policy that
        already superseded theirs."

        Design: Corner/complexity_layers/occ_stale_property_version_on_policy_create
        """
        state = _a_property_version_a_rival_policy_superseded(api)

        validate_error(
            _attempt_second_policy(api, state, state["stale_version"]),
            ApiErrorId.ERR_STALE_PROPERTY_VERSION,
            412,
        )

        policies, meta = validate_paginated(
            api.list_property_policies(state["property_id"], FIRST_ANALYST)
        )
        assert meta["total_count"] == 1
        assert policies[0]["id"] == state["first_policy_id"]

        fresh = read_property_version(api, state["property_id"], SECOND_ANALYST)
        assert fresh == state["stale_version"] + 1

    def test_the_refreshed_retry_enrols_the_new_carrier_and_terminates_the_old(
        self, api: ApiClient
    ):
        """The supersede side effect runs only on the create the guard let through.

        "The new row is created with `credit_state` `PENDING_ENROLLMENT`,
        `current_credit_tier_pct` at 0, `credited_cents_total`, `clawback_cents_total`,
        `true_up_cents`, and `paid_payout_cents_total` all at 0, `finalized_period_count` at 0,
        `avg_uptime_pct` and `last_attestation_end_at` and `suspended_reason` all null, and
        `version` at 1."
        "Every prior policy on the same property that is not already `TERMINATED` is driven to
        `TERMINATED` with its own `version` incremented by 1, and the property's `version` is
        incremented by 1 as well — which is exactly what makes a second analyst's stale
        `expected_property_version` detectable."

        Design: Corner/complexity_layers/occ_stale_property_version_on_policy_create
        """
        state = _a_property_version_a_rival_policy_superseded(api)
        validate_error(
            _attempt_second_policy(api, state, state["stale_version"]),
            ApiErrorId.ERR_STALE_PROPERTY_VERSION,
            412,
        )

        fresh = read_property_version(api, state["property_id"], SECOND_ANALYST)
        second = get_success_data(_attempt_second_policy(api, state, fresh), 201)
        assert second["credit_state"] == "PENDING_ENROLLMENT"
        assert second["credited_cents_total"] == 0
        assert second["paid_payout_cents_total"] == 0
        assert second["version"] == 1

        assert read_policy(api, state["first_policy_id"])["credit_state"] == "TERMINATED"
        assert read_property_version(api, state["property_id"], SECOND_ANALYST) == (
            state["stale_version"] + 2
        )


BELOW_GATE_AT = "2026-08-01T06:10:00Z"
AT_GATE_AT = "2026-08-01T06:20:00Z"
GATE_FLOW_GPM = 9.0
GATE_DURATION_MINUTES = 3
JUST_BELOW_GALLONS = 29.99
AT_GATE_GALLONS = 30.0
BURST_PRESSURE_PSI = 30.0


def _one_reading_a_hundredth_below_the_volume_gate(api: ApiClient) -> dict:
    """Flow and duration both clear their gates; only the volume falls short."""
    state = setup_armed_device(api)
    set_clock(api, BELOW_GATE_AT)
    state["below_reading"] = ingest_reading(
        api,
        state["device_id"],
        BELOW_GATE_AT,
        BURST_PRESSURE_PSI,
        GATE_FLOW_GPM,
        GATE_DURATION_MINUTES,
        JUST_BELOW_GALLONS,
    )
    return state


def _then_one_reading_exactly_at_it(api: ApiClient, state: dict) -> dict:
    """The very next sample raises the volume by a single hundredth."""
    set_clock(api, AT_GATE_AT)
    state["at_gate_reading"] = ingest_reading(
        api,
        state["device_id"],
        AT_GATE_AT,
        BURST_PRESSURE_PSI,
        GATE_FLOW_GPM,
        GATE_DURATION_MINUTES,
        AT_GATE_GALLONS,
    )
    return state


class TestTheVolumeGateIsInclusiveAtThirtyGallons:
    def test_a_hundredth_of_a_gallon_short_is_no_anomaly_at_all(self, api: ApiClient):
        """All three burst conditions are conjunctive, so one shortfall ends the rung.

        "If `flow_gpm` is at least the burst flow gate, **and** `duration_minutes` is at least
        3 minutes, **and** `total_gallons` is at least the burst volume gate, the verdict is
        `CATASTROPHIC_BURST`."
        "A verdict of `NONE` writes no anomaly event at all, leaves `anomaly_event_created`
        false, and — provided the sample came from `DEVICE` rather than `MANUAL_TEST` and was
        not suppressed by irrigation — marks the reading `baseline_eligible`."

        Design: Corner/complexity_layers/burst_gallon_gate_boundary_is_inclusive_at_thirty_gallons
        """
        state = _one_reading_a_hundredth_below_the_volume_gate(api)

        reading = state["below_reading"]
        assert reading["classification_at_ingest"] == "NONE"
        assert reading["anomaly_event_created"] is False
        assert reading["baseline_eligible"] is True
        assert reading["suppressed_by_irrigation"] is False
        assert reading["coverage_minutes"] == 120

        assert read_events(api, state["device_id"]) == []

    def test_it_does_not_fall_through_to_the_running_fixture_or_the_drip_rung(
        self, api: ApiClient
    ):
        """Its flow clears both lower flow gates, but three minutes clears neither duration.

        "Otherwise, if `flow_gpm` is at least the running-fixture flow gate **and**
        `duration_minutes` is at least 20 minutes, the verdict is `RUNNING_FIXTURE`."
        "Otherwise, if `flow_gpm` is at least the drip gate **and** `duration_minutes` is at
        least a full hour, the verdict is `DRIP`."

        Design: Corner/complexity_layers/burst_gallon_gate_boundary_is_inclusive_at_thirty_gallons
        """
        state = _one_reading_a_hundredth_below_the_volume_gate(api)
        assert state["below_reading"]["classification_at_ingest"] == "NONE"

        # 9.0 gpm is well past the 2.40 running gate and the 0.12 drip gate.
        assert read_live_baseline(api, state["device_id"])["drip_threshold_gpm"] == 0.12
        assert read_events(api, state["device_id"]) == []

    def test_the_completed_profile_is_not_relearned_by_that_reading(
        self, api: ApiClient
    ):
        """Recomputation belongs to the collecting phase, so the gates stay where they were.

        "On each accepted reading while the profile is still `COLLECTING`, three values are
        recomputed over exactly that eligible set: `baseline_static_pressure_psi` is the
        arithmetic mean of the readings' static pressures, rounded half up to one decimal
        place; `baseline_peak_flow_gpm` is the largest observed flow among them, carried to two
        decimal places; and `drip_threshold_gpm` is the greater of an absolute floor of 0.05
        gallons per minute and two percent of `baseline_peak_flow_gpm`, rounded half up to two
        decimal places."
        "Three gates are then derived, each rounded half up to two decimal places before any
        comparison is made."

        Design: Corner/complexity_layers/burst_gallon_gate_boundary_is_inclusive_at_thirty_gallons
        """
        state = _one_reading_a_hundredth_below_the_volume_gate(api)

        profile = read_live_baseline(api, state["device_id"])
        assert profile["learning_state"] == "COMPLETE"
        assert profile["baseline_version"] == 3
        assert profile["baseline_peak_flow_gpm"] == 6.00
        assert profile["baseline_static_pressure_psi"] == 60.0

    def test_the_reading_sitting_on_the_gate_mints_one_burst_scored_at_a_half(
        self, api: ApiClient
    ):
        """Every observed figure is exactly half its reference, so the weights cancel out.

        "A reading sitting exactly on the burst flow gate with exactly 3 minutes of duration
        and exactly the burst volume gate classifies as `CATASTROPHIC_BURST`."
        "The components are combined with fixed weights: flow contributes 0.50, duration
        contributes 0.30, and volume contributes 0.20."

        Design: Corner/complexity_layers/burst_gallon_gate_boundary_is_inclusive_at_thirty_gallons
        """
        state = _one_reading_a_hundredth_below_the_volume_gate(api)
        _then_one_reading_exactly_at_it(api, state)

        assert state["at_gate_reading"]["classification_at_ingest"] == (
            "CATASTROPHIC_BURST"
        )
        assert state["at_gate_reading"]["anomaly_event_created"] is True

        events = read_events(api, state["device_id"])
        assert len(events) == 1
        event = events[0]
        assert event["classification"] == "CATASTROPHIC_BURST"
        assert event["event_state"] == "ALERTED"
        assert event["observed_gallons"] == AT_GATE_GALLONS
        assert event["baseline_version_used"] == 3
        assert event["severity_score"] == 0.500

    def test_the_shutoff_ran_on_the_second_reading_only_and_the_verdicts_stay_frozen(
        self, api: ApiClient
    ):
        """One stream, two samples, two permanently different verdicts.

        "On the event, `auto_shutoff_executed` becomes true and `shutoff_latency_minutes` is
        set to the elapsed minutes between the event's `detected_at` and the closure, rounded
        half up to one decimal place — which, because detection and closure happen inside the
        same ingest, is 0.0."
        "Two consequences follow and are binding: the very reading that completes a learning
        cycle is itself never classified, and a stored reading's `classification_at_ingest` is
        permanent — later baseline recomputation never reclassifies history."

        Design: Corner/complexity_layers/burst_gallon_gate_boundary_is_inclusive_at_thirty_gallons
        """
        state = _one_reading_a_hundredth_below_the_volume_gate(api)
        device_before = read_device(api, state["device_id"])
        assert device_before["valve_state"] == "OPEN"
        assert device_before["close_count"] == 0

        _then_one_reading_exactly_at_it(api, state)

        event = read_events(api, state["device_id"])[0]
        assert event["auto_shutoff_executed"] is True
        assert event["shutoff_latency_minutes"] == 0.0

        device = read_device(api, state["device_id"])
        assert device["valve_state"] == "CLOSED"
        assert device["close_count"] == 1
        assert device["last_shutoff_at"].startswith("2026-08-01T06:20:00")

        readings = read_telemetry(api, state["device_id"])
        assert len(readings) == 5
        assert readings[3]["classification_at_ingest"] == "NONE"
        assert readings[4]["classification_at_ingest"] == "CATASTROPHIC_BURST"
