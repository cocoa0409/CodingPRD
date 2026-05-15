"""Temperature events, deviation lifecycle, zone posture — PRD §3.3,
§2.10.

Tests cover: classification kinds, deviation aggregation, classification
calculation thresholds, posture cascades, lot quarantine cascades, and
packed-shipment quarantine cascades.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock,
    assert_deviation,
    assert_temperature_event,
    create_warehouse,
    create_zone,
    create_bin,
    get_bin,
    get_lot,
    get_shipment,
    get_zone,
    list_deviations,
    list_external_events,
    list_lots,
    list_shipments,
    record_temperature_event,
    setup_accepted_lot,
    setup_basic_topology,
    setup_deviation_at_duration_boundary,
    setup_packed_shipment,
    temperature_event_payload,
    trigger_alarm_high_and_recover,
    validate_error,
    validate_success,
)


# ===========================================================================
# Temperature-event creation: timing window + classification.
# ===========================================================================
class TestTemperatureEventTiming:

    def test_event_before_clock_minus_one_returns_err_temp_event_time_invalid(
        self, api,
    ):
        """PRD §3.3: "The system rejects the reading with
        `ERR_TEMP_EVENT_TIME_INVALID` (HTTP 422) unless `at_minutes`
        is at least `clock_minutes` minus 1 and at most
        `clock_minutes` — that is, the event must have been recorded
        in the current logical minute or the immediately preceding
        one."

        Claim: at_minutes < clock_minutes - 1 → ERR_TEMP_EVENT_TIME_INVALID.
        Boundary: clock=10, post at_minutes=8 → invalid (8 < 9).
        """
        topology = setup_basic_topology()
        advance_clock(topology["warehouse"]["id"], 10)
        res = api.record_temperature_event(
            topology["zone"]["id"],
            temperature_event_payload(at_minutes=8, temp_c=5.0),
            TEST_USERS["warehouse_admin_headers"],
        )
        validate_error(res, ApiErrorId.ERR_TEMP_EVENT_TIME_INVALID.value)

    def test_event_after_clock_returns_err_temp_event_time_invalid(self, api):
        """PRD §3.3 same rule, upper bound. clock=10, post
        at_minutes=11 → at_minutes > clock_minutes → invalid.
        """
        topology = setup_basic_topology()
        advance_clock(topology["warehouse"]["id"], 10)
        res = api.record_temperature_event(
            topology["zone"]["id"],
            temperature_event_payload(at_minutes=11, temp_c=5.0),
            TEST_USERS["warehouse_admin_headers"],
        )
        validate_error(res, ApiErrorId.ERR_TEMP_EVENT_TIME_INVALID.value)


class TestTemperatureEventClassification:

    def test_in_range_reading_classifies_as_in_range(self, api):
        """PRD §3.3: "a reading inside `[target_temp_low_c,
        target_temp_high_c]` (inclusive) is classified `IN_RANGE`".

        Claim: REFRIGERATED 2..8 zone, reading 5.0 → kind == IN_RANGE.
        """
        topology = setup_basic_topology()
        res = api.record_temperature_event(
            topology["zone"]["id"],
            temperature_event_payload(at_minutes=0, temp_c=5.0),
            TEST_USERS["warehouse_admin_headers"],
        )
        data = validate_success(res, 201)
        assert data["kind"] == "IN_RANGE"
        assert_temperature_event(data)

    def test_alarm_high_reading_classifies_as_alarm_high(self, api):
        """PRD §3.3: "a reading at or above `alarm_high_c` is
        `ALARM_HIGH`".

        Claim: REFRIGERATED zone with alarm_high_c=10.0, reading 10.0
        → kind == ALARM_HIGH (inclusive boundary).
        """
        topology = setup_basic_topology()
        res = api.record_temperature_event(
            topology["zone"]["id"],
            temperature_event_payload(at_minutes=0, temp_c=10.0),
            TEST_USERS["warehouse_admin_headers"],
        )
        data = validate_success(res, 201)
        assert data["kind"] == "ALARM_HIGH"

    def test_warning_high_strictly_between_target_and_alarm(self, api):
        """PRD §3.3: "a reading strictly between `target_temp_high_c`
        and `alarm_high_c` is `WARNING_HIGH`".

        Claim: REFRIGERATED zone (target_high=8, alarm_high=10),
        reading 9.0 → kind == WARNING_HIGH.
        """
        topology = setup_basic_topology()
        res = api.record_temperature_event(
            topology["zone"]["id"],
            temperature_event_payload(at_minutes=0, temp_c=9.0),
            TEST_USERS["warehouse_admin_headers"],
        )
        data = validate_success(res, 201)
        assert data["kind"] == "WARNING_HIGH"

    def test_alarm_low_at_alarm_low_threshold(self, api):
        """PRD §3.3: "a reading at or below `alarm_low_c` is
        `ALARM_LOW`".

        Claim: REFRIGERATED alarm_low=0.0, reading 0.0 → kind ==
        ALARM_LOW (inclusive boundary).
        """
        topology = setup_basic_topology()
        res = api.record_temperature_event(
            topology["zone"]["id"],
            temperature_event_payload(at_minutes=0, temp_c=0.0),
            TEST_USERS["warehouse_admin_headers"],
        )
        data = validate_success(res, 201)
        assert data["kind"] == "ALARM_LOW"


# ===========================================================================
# Append-only TemperatureEvent contract — PRD §2.4
# ===========================================================================
class TestTemperatureEventAppendOnly:

    def test_temperature_event_has_no_updated_at_or_version(self, api):
        """PRD §2.4: "Three resource families are deliberately
        append-only and do not carry `updated_at` or `version`:
        temperature events (`TemperatureEvent`) ... For those four
        entities, only `id` and `created_at` are present."

        Claim: a temperature-event response carries id and created_at
        but does NOT carry updated_at or version.
        """
        topology = setup_basic_topology()
        res = api.record_temperature_event(
            topology["zone"]["id"],
            temperature_event_payload(at_minutes=0, temp_c=5.0),
            TEST_USERS["warehouse_admin_headers"],
        )
        data = validate_success(res, 201)
        assert "id" in data and "created_at" in data
        assert "updated_at" not in data, (
            f"TemperatureEvent must not expose updated_at; got "
            f"{data.get('updated_at')!r}"
        )
        assert "version" not in data, (
            f"TemperatureEvent must not expose version; got "
            f"{data.get('version')!r}"
        )


# ===========================================================================
# Zone posture cascades — PRD §2.10
# ===========================================================================
class TestZonePostureCascades:

    def test_alarm_high_flips_zone_to_frozen_and_bins_to_locked(self, api):
        """PRD §2.10: "Any alarm-level reading (whether `ALARM_LOW` or
        `ALARM_HIGH`) drives the zone to `FROZEN`; while a zone is
        `FROZEN`, every child bin's `status` flips to `LOCKED`".

        Claim: post an ALARM_HIGH reading; zone.current_posture
        becomes FROZEN and every bin.status becomes LOCKED.
        """
        topology = setup_basic_topology()
        record_temperature_event(
            topology["zone"]["id"], at_minutes=0, temp_c=12.0,
        )
        zone_after = get_zone(topology["zone"]["id"])
        assert zone_after["current_posture"] == "FROZEN"
        bin_after = get_bin(topology["zone"]["id"], topology["bin"]["id"])
        assert bin_after["status"] == "LOCKED"


# ===========================================================================
# Deviation classification — PRD §3.3 paragraph 3
# ===========================================================================
class TestDeviationClassification:

    def test_classification_critical_at_240_min_boundary(self, api):
        """PRD §3.3: "if `duration_minutes` is at least 240 minutes
        (4 hours), or if `max_magnitude_c` is at least 5.0, the
        deviation is `CRITICAL`".

        Claim: deviation lasting 240 minutes exactly → CRITICAL.
        """
        ctx = setup_deviation_at_duration_boundary(
            target_duration_minutes=240,
        )
        dev = ctx["deviation"]
        assert dev["duration_minutes"] == 240
        assert dev["classification"] == "CRITICAL"

    def test_classification_major_at_60_min_boundary(self, api):
        """PRD §3.3: "otherwise, if `duration_minutes` is at least 60
        minutes, or if `max_magnitude_c` is at least 2.0, the deviation
        is `MAJOR`".

        Difficulty-design: boundary_precision_check /
        deviation_classification_at_60min_boundary.

        # difficulty: boundary_precision_check/deviation_classification_at_60min_boundary

        Claim: deviation lasting exactly 60 minutes → MAJOR (inclusive
        lower bound).
        """
        ctx = setup_deviation_at_duration_boundary(
            target_duration_minutes=60,
        )
        dev = ctx["deviation"]
        assert dev["duration_minutes"] == 60
        assert dev["classification"] == "MAJOR"

    def test_classification_minor_below_60_min(self, api):
        """PRD §3.3: "otherwise the deviation is `MINOR`".

        Claim: deviation lasting 59 minutes with magnitude < 2.0 →
        MINOR.

        Difficulty-design: boundary_precision_check /
        deviation_classification_at_60min_boundary (matched MINOR side).
        # difficulty: boundary_precision_check/deviation_classification_at_60min_boundary
        """
        # Use a small magnitude (target 2..8, reading 9.5 → magnitude
        # 1.5, below MAJOR magnitude threshold 2.0).
        topology = setup_basic_topology()
        zone_id = topology["zone"]["id"]
        warehouse_id = topology["warehouse"]["id"]
        # Out-of-range (WARNING_HIGH at 9.5 — above target 8, below
        # alarm 10).
        record_temperature_event(zone_id, at_minutes=0, temp_c=9.5)
        advance_clock(warehouse_id, 58)
        record_temperature_event(zone_id, at_minutes=58, temp_c=9.5)
        advance_clock(warehouse_id, 1)
        record_temperature_event(zone_id, at_minutes=59, temp_c=5.0)
        deviations = list_deviations(warehouse_id)
        dev = deviations[-1]
        assert dev["duration_minutes"] == 59
        # Magnitude is 9.5-8.0=1.5, below MAJOR magnitude 2.0; duration
        # 59 < 60. So MINOR.
        assert dev["classification"] == "MINOR"


# ===========================================================================
# Cumulative stock-isolation cascade — PRD §3.3
# ===========================================================================
class TestStockIsolationCascade:

    def test_deviation_close_quarantines_released_lots_in_zone(self, api):
        """PRD §3.3: "At the same moment, every lot whose `bin_id`
        lies in the affected zone has its `cumulative_excursion_minutes`
        raised by the deviation's `duration_minutes`, and every such
        lot whose `quality_status` was `RELEASED` is moved to
        `QUARANTINED`."

        Claim: a RELEASED lot in a zone whose deviation has just
        closed (CLOSED_PENDING_QA) is moved to QUARANTINED.
        """
        ctx = setup_accepted_lot(quantity_units=5)
        # Open and close deviation on the storage zone via the helper.
        # (Use WARNING_HIGH so duration boundary doesn't escalate
        # zone posture beyond restricted; but per PRD §2.10 the test
        # uses ALARM events to drive FROZEN — either way the lot
        # cascade fires when the deviation closes.)
        trigger_alarm_high_and_recover(
            ctx["zone"]["id"], ctx["warehouse"]["id"],
            alarm_temp_c=12.0, in_range_temp_c=5.0,
            start_minutes=1,
        )
        # Refresh lot.
        lot_after = get_lot(ctx["lot"]["id"])
        assert lot_after["quality_status"] == "QUARANTINED"
        assert lot_after["cumulative_excursion_minutes"] >= 1, (
            f"cumulative_excursion_minutes should be incremented; got "
            f"{lot_after['cumulative_excursion_minutes']}"
        )


# ===========================================================================
# Difficulty-design coverage: depth-3 cascade from
# temperature-event ALARM_HIGH all the way to a PACKED OutboundShipment.
# # difficulty: transitive_cascade/temperature_event_alarm_cascades_to_packed_shipment_quarantine
# ===========================================================================
class TestTransitiveCascadeAlarmToShipment:

    def test_alarm_event_cascades_to_bin_lock_and_lot_quarantine(self, api):
        """PRD §2.10: "Any alarm-level reading (whether `ALARM_LOW`
        or `ALARM_HIGH`) drives the zone to `FROZEN`; while a zone
        is `FROZEN`, every child bin's `status` flips to `LOCKED`".
        PRD §3.3: "every lot whose `bin_id` lies in the affected
        zone has its `cumulative_excursion_minutes` raised by the
        deviation's `duration_minutes`, and every such lot whose
        `quality_status` was `RELEASED` is moved to `QUARANTINED`."

        Difficulty-design: transitive_cascade /
        temperature_event_alarm_cascades_to_packed_shipment_quarantine
        — the chain's intermediate hops (zone → bin → lot).
        # difficulty: transitive_cascade/temperature_event_alarm_cascades_to_packed_shipment_quarantine

        Claim: a single ALARM_HIGH event on the storage zone of a
        recently-accepted lot drives Zone→FROZEN, Bin→LOCKED,
        Lot→QUARANTINED — in one chain.
        """
        ctx = setup_accepted_lot(quantity_units=5)
        # Post one ALARM_HIGH; this both opens the deviation and
        # drives zone to FROZEN. We do not need to recover because the
        # cascade FROM the alarm to bin LOCKED is immediate per
        # PRD §2.10; the cascade FROM the deviation close to lot
        # QUARANTINED requires recovery, which we add below.
        record_temperature_event(
            ctx["zone"]["id"], at_minutes=0, temp_c=12.0,
        )
        zone_now = get_zone(ctx["zone"]["id"])
        assert zone_now["current_posture"] == "FROZEN"
        bin_now = get_bin(ctx["zone"]["id"], ctx["bin"]["id"])
        assert bin_now["status"] == "LOCKED"
        # Close the deviation so the lot-quarantine cascade fires.
        advance_clock(ctx["warehouse"]["id"], 1)
        record_temperature_event(
            ctx["zone"]["id"], at_minutes=1, temp_c=5.0,
        )
        lot_after = get_lot(ctx["lot"]["id"])
        assert lot_after["quality_status"] == "QUARANTINED"

    def test_alarm_event_cascades_through_zone_lot_to_packed_shipment(
        self, api,
    ):
        """PRD §3.3: "The cascade extends to outbound shipments: every
        shipment in `PACKED` whose `pick_lot_id` has just been
        quarantined is itself moved to `QUARANTINED` to freeze it
        pending QA."

        Difficulty-design: transitive_cascade /
        temperature_event_alarm_cascades_to_packed_shipment_quarantine.

        # difficulty: transitive_cascade/temperature_event_alarm_cascades_to_packed_shipment_quarantine

        Claim: a PACKED shipment whose pick_lot_id resides in a zone
        that has just had its deviation closed → shipment.status ==
        QUARANTINED.
        """
        ctx = setup_packed_shipment(
            quantity_units=5,
            accepted_quantity_units=10,
            packaging_kind="INSULATED_PCM",
            required_zone_type="REFRIGERATED",
        )
        # Trigger the cascade.
        trigger_alarm_high_and_recover(
            ctx["zone"]["id"], ctx["warehouse"]["id"],
            alarm_temp_c=12.0, in_range_temp_c=5.0,
            start_minutes=1,
        )
        # Refresh the shipment.
        shipment_after = get_shipment(ctx["shipment"]["id"])
        assert shipment_after["status"] == "QUARANTINED"
        # And the lot was quarantined.
        lot_after = get_lot(ctx["lot"]["id"])
        assert lot_after["quality_status"] == "QUARANTINED"
        # Zone posture is FROZEN.
        zone_after = get_zone(ctx["zone"]["id"])
        assert zone_after["current_posture"] == "FROZEN"


# ===========================================================================
# Difficulty-design coverage: Zone cyclic posture machine
# # difficulty: non_linear_state_machine/zone_posture_cyclic_open_restricted_frozen_open
# ===========================================================================
class TestZoneCyclicPosture:

    def test_bin_locked_flips_back_to_available_after_zone_reopens(self, api):
        """PRD §2.10: "bins that were `LOCKED` revert to `AVAILABLE`
        or `OCCUPIED` according to whether their `current_lot_id` is
        null."

        Difficulty-design: non_linear_state_machine /
        zone_posture_cyclic_open_restricted_frozen_open (the
        bin-status side of the cyclic posture machine).
        # difficulty: non_linear_state_machine/zone_posture_cyclic_open_restricted_frozen_open

        Claim: an empty bin in a zone that flipped FROZEN (and so
        the bin became LOCKED) reverts to AVAILABLE after the
        deviation reaches CLOSED_ASSESSED.
        """
        from test_helpers import assess_deviation
        topology = setup_basic_topology()
        dev = trigger_alarm_high_and_recover(
            topology["zone"]["id"], topology["warehouse"]["id"],
            alarm_temp_c=12.0, in_range_temp_c=5.0,
            start_minutes=1,
        )
        bin_during_frozen = get_bin(
            topology["zone"]["id"], topology["bin"]["id"],
        )
        assert bin_during_frozen["status"] == "LOCKED"
        assess_deviation(
            dev["id"], qa_decision="QUARANTINE",
            headers=TEST_USERS["qa_officer_headers"],
        )
        bin_after = get_bin(topology["zone"]["id"], topology["bin"]["id"])
        # Empty bin (no current_lot_id) reverts to AVAILABLE.
        assert bin_after["status"] == "AVAILABLE"
        assert bin_after.get("current_lot_id") is None

    def test_zone_returns_to_open_after_deviation_assessed(self, api):
        """PRD §2.10: "When the underlying deviation finally reaches
        `CLOSED_ASSESSED` and no other deviation on the zone is still
        open, the zone returns to `OPEN`".

        Difficulty-design: non_linear_state_machine /
        zone_posture_cyclic_open_restricted_frozen_open.

        # difficulty: non_linear_state_machine/zone_posture_cyclic_open_restricted_frozen_open

        Claim: zone OPEN → FROZEN (via ALARM) → OPEN (after QA assess
        of the linked deviation closes the loop).
        """
        from test_helpers import assess_deviation
        topology = setup_basic_topology()
        dev = trigger_alarm_high_and_recover(
            topology["zone"]["id"], topology["warehouse"]["id"],
            alarm_temp_c=12.0, in_range_temp_c=5.0,
            start_minutes=1,
        )
        # Zone is FROZEN now.
        zone_frozen = get_zone(topology["zone"]["id"])
        assert zone_frozen["current_posture"] == "FROZEN"
        # Assess the deviation as RELEASE (MINOR/no CAPA required since
        # duration 1 min, magnitude 4.0). The deviation duration is
        # ended_at-started_at+1 = 1-1+1 = 1 minute → magnitude 12-8=4.0
        # → MAJOR (magnitude>=2.0). MAJOR + RELEASE needs capa_id; use
        # QUARANTINE instead, which does not require CAPA.
        assess_deviation(
            dev["id"], qa_decision="QUARANTINE",
            headers=TEST_USERS["qa_officer_headers"],
        )
        # Zone should now return to OPEN.
        zone_open = get_zone(topology["zone"]["id"])
        assert zone_open["current_posture"] == "OPEN"
