"""Ballast water event recording: voyage window, tank balance, capacity,
exchange plausibility, uptake attribution, OCC, and append-only shape."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_ballast_event,
    current_determination,
    get_voyage_version,
    list_ballast_events,
    post_ballast_event,
    post_ballast_event_ok,
    post_discharge,
    post_exchange_complete,
    post_uptake,
    setup_voyage_in_progress,
    validate_error,
    validate_success,
)
from test_helpers import api_client


class TestEventWindowContainment:
    def test_event_at_exact_window_lower_bound_accepted(self, api, vessel_master_headers):
        """PRD section 3.2: "The `occurred_at` must fall within the voyage window —
        from 6 hours before `departed_at` to 6 hours after `arrived_at` — and may not
        be in the future; a violation is rejected with `ERR_EVENT_OUT_OF_WINDOW`
        (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/voyage_event_window_buffered_containment
        """
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9000023", vessel_name="MV Wigeon", voyage_number="V9001"
        )
        # departed_at 2026-07-28T00:00:00Z; lower window edge 2026-07-27T18:00:00Z.
        resp = post_ballast_event(
            vessel["id"], voyage["id"], event_kind="UPTAKE",
            occurred_at="2026-07-27T18:00:00Z", tank_id="T1", volume_m3=100,
            salinity_ppt=31.0, source_port_locode="USNYC",
        )
        data = validate_success(resp, 201)
        assert_ballast_event(data)

    def test_event_one_second_before_window_lower_bound_rejected(self, api,
                                                                 vessel_master_headers):
        """PRD section 3.2: "The `occurred_at` must fall within the voyage window —
        from 6 hours before `departed_at` to 6 hours after `arrived_at` — and may not
        be in the future; a violation is rejected with `ERR_EVENT_OUT_OF_WINDOW`
        (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/voyage_event_window_buffered_containment
        """
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9000023", vessel_name="MV Wigeon", voyage_number="V9001"
        )
        post_uptake(vessel["id"], voyage["id"], tank_id="T1", volume_m3=100,
                    occurred_at="2026-07-27T18:00:00Z", salinity_ppt=31.0)

        resp = post_ballast_event(
            vessel["id"], voyage["id"], event_kind="UPTAKE",
            occurred_at="2026-07-27T17:59:59Z", tank_id="T2", volume_m3=100,
            salinity_ppt=31.0, source_port_locode="USNYC",
        )
        validate_error(resp, ApiErrorId.ERR_EVENT_OUT_OF_WINDOW)


class TestValidationPriorityPairs:
    def test_future_event_with_oversize_volume_reports_window_error(
            self, api, vessel_master_headers):
        """PRD section 2.10: "state-machine legality before segregation-of-duties and
        vessel-frozen business-safety checks, and those before temporal, constraint,
        referential, and fiscal checks on the request payload."
        PRD section 3.2: "The `occurred_at` must fall within the voyage window — from
        6 hours before `departed_at` to 6 hours after `arrived_at` — and may not be in
        the future; a violation is rejected with `ERR_EVENT_OUT_OF_WINDOW` (HTTP
        422)."

        Design: Difficulty/priority_pair_validation_conflict/event_window_beats_volume_capacity
        """
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9000012", vessel_name="MV Lark", voyage_number="V6002"
        )
        # occurred_at 2026-08-05 is after the logical clock 2026-08-01 (temporal
        # violation) AND volume 31000 exceeds capacity 30000 (fiscal violation).
        # The temporal check is the earlier priority family and wins.
        resp = post_ballast_event(
            vessel["id"], voyage["id"], event_kind="UPTAKE",
            occurred_at="2026-08-05T00:00:00Z", tank_id="T1", volume_m3=31000,
            salinity_ppt=32.0, source_port_locode="USNYC",
        )
        validate_error(resp, ApiErrorId.ERR_EVENT_OUT_OF_WINDOW)

    def test_rejected_event_is_not_persisted(self, api, vessel_master_headers):
        """PRD section 3.2: "The `occurred_at` must fall within the voyage window —
        from 6 hours before `departed_at` to 6 hours after `arrived_at` — and may not
        be in the future; a violation is rejected with `ERR_EVENT_OUT_OF_WINDOW`
        (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/event_window_beats_volume_capacity
        """
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9000012", vessel_name="MV Lark", voyage_number="V6002"
        )
        resp = post_ballast_event(
            vessel["id"], voyage["id"], event_kind="UPTAKE",
            occurred_at="2026-08-05T00:00:00Z", tank_id="T1", volume_m3=31000,
            salinity_ppt=32.0, source_port_locode="USNYC",
        )
        validate_error(resp, ApiErrorId.ERR_EVENT_OUT_OF_WINDOW)

        events = list_ballast_events(vessel["id"], voyage["id"])
        assert len(events) == 0, "rejected event must not be persisted"


class TestTankBalance:
    def test_tank_balance_may_land_on_exactly_zero(self, api, vessel_master_headers):
        """PRD section 3.2: "The chronological per-tank balance — cumulative uptake
        minus cumulative discharge on that tank — must never go negative at any point
        in the voyage's event timeline; a violation is rejected with
        `ERR_TANK_BALANCE_NEGATIVE` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/tank_balance_exactly_zero_then_overdraft
        """
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9000018", vessel_name="MV Shearwater", voyage_number="V7004"
        )
        post_uptake(vessel["id"], voyage["id"], tank_id="T5", volume_m3=500, salinity_ppt=32.0)
        # Zero is not negative: discharging exactly the uplifted volume is accepted.
        discharge = post_discharge(vessel["id"], voyage["id"], tank_id="T5", volume_m3=500,
                                   occurred_at="2026-07-29T06:00:00Z")
        assert_ballast_event(discharge)

        resp = post_ballast_event(
            vessel["id"], voyage["id"], event_kind="DISCHARGE",
            occurred_at="2026-07-30T06:00:00Z", tank_id="T5", volume_m3=0.001,
            latitude=35.0, longitude=-140.0, distance_from_shore_nm=250,
        )
        validate_error(resp, ApiErrorId.ERR_TANK_BALANCE_NEGATIVE)

    def test_one_thousandth_overdraft_rejected_and_not_persisted(self, api,
                                                                 vessel_master_headers):
        """PRD section 3.2: "The chronological per-tank balance — cumulative uptake
        minus cumulative discharge on that tank — must never go negative at any point
        in the voyage's event timeline; a violation is rejected with
        `ERR_TANK_BALANCE_NEGATIVE` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/tank_balance_exactly_zero_then_overdraft
        """
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9000018", vessel_name="MV Shearwater", voyage_number="V7004"
        )
        post_uptake(vessel["id"], voyage["id"], tank_id="T5", volume_m3=500, salinity_ppt=32.0)
        post_discharge(vessel["id"], voyage["id"], tank_id="T5", volume_m3=500,
                       occurred_at="2026-07-29T06:00:00Z")

        resp = post_ballast_event(
            vessel["id"], voyage["id"], event_kind="DISCHARGE",
            occurred_at="2026-07-30T06:00:00Z", tank_id="T5", volume_m3=0.001,
            latitude=35.0, longitude=-140.0, distance_from_shore_nm=250,
        )
        validate_error(resp, ApiErrorId.ERR_TANK_BALANCE_NEGATIVE)

        t5_events = [e for e in list_ballast_events(vessel["id"], voyage["id"])
                     if e.get("tank_id") == "T5"]
        assert len(t5_events) == 2, "rejected overdraft must not be persisted"


class TestTankBalanceInvariant:
    def test_compensating_pair_leaves_zero_balance_and_blocks_overdraft(
            self, api, vessel_master_headers):
        """PRD section 3.2: "The chronological per-tank balance — cumulative uptake
        minus cumulative discharge on that tank — must never go negative at any point
        in the voyage's event timeline; a violation is rejected with
        `ERR_TANK_BALANCE_NEGATIVE` (HTTP 422)."

        Design: Difficulty/compensating_invariant/tank_uptake_discharge_conserves_zero_balance
        """
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9000026", vessel_name="MV Zebra", voyage_number="V9101"
        )
        post_uptake(vessel["id"], voyage["id"], tank_id="T7", volume_m3=500, salinity_ppt=32.0)
        post_discharge(vessel["id"], voyage["id"], tank_id="T7", volume_m3=500,
                       occurred_at="2026-07-29T06:00:00Z")
        # Invariant conserved: sum(UPTAKE T7) - sum(DISCHARGE T7) == 0.
        t7_events = [e for e in list_ballast_events(vessel["id"], voyage["id"])
                     if e.get("tank_id") == "T7"]
        uptake_sum = sum(e["volume_m3"] for e in t7_events if e["event_kind"] == "UPTAKE")
        discharge_sum = sum(e["volume_m3"] for e in t7_events if e["event_kind"] == "DISCHARGE")
        assert uptake_sum - discharge_sum == pytest.approx(0.0)

        resp = post_ballast_event(
            vessel["id"], voyage["id"], event_kind="DISCHARGE",
            occurred_at="2026-07-30T06:00:00Z", tank_id="T7", volume_m3=0.001,
            latitude=35.0, longitude=-140.0, distance_from_shore_nm=250,
        )
        validate_error(resp, ApiErrorId.ERR_TANK_BALANCE_NEGATIVE)

    def test_only_accepted_discharges_count_in_determination(self, api, vessel_master_headers):
        """PRD section 3.3: "The `total_discharged_volume_m3` is the sum of all
        `DISCHARGE` event volumes."
        PRD section 3.3: "Each `DISCHARGE` is attributed to the most recent prior
        `UPTAKE` on the same `tank_id`; a discharge with no prior uptake on its tank
        is unattributed and counts toward `noncompliant_volume_m3`."

        Design: Difficulty/compensating_invariant/tank_uptake_discharge_conserves_zero_balance
        """
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9000026", vessel_name="MV Zebra", voyage_number="V9101"
        )
        post_uptake(vessel["id"], voyage["id"], tank_id="T7", volume_m3=500, salinity_ppt=32.0)
        post_discharge(vessel["id"], voyage["id"], tank_id="T7", volume_m3=500,
                       occurred_at="2026-07-29T06:00:00Z")

        resp = post_ballast_event(
            vessel["id"], voyage["id"], event_kind="DISCHARGE",
            occurred_at="2026-07-30T06:00:00Z", tank_id="T7", volume_m3=0.001,
            latitude=35.0, longitude=-140.0, distance_from_shore_nm=250,
        )
        validate_error(resp, ApiErrorId.ERR_TANK_BALANCE_NEGATIVE)

        determination = current_determination(vessel["id"], voyage["id"])
        assert determination["total_discharged_volume_m3"] == pytest.approx(500.0)
        # The single accepted discharge has no treatment/exchange path.
        assert determination["noncompliant_volume_m3"] == pytest.approx(500.0)


class TestUptakeAttributionAndPlausibility:
    def test_discharge_without_uptake_priority_over_tank_balance(
            self, api, vessel_master_headers):
        """PRD section 3.2: "A `DISCHARGE` on a tank must have at least one prior
        `UPTAKE` on the same `tank_id`; otherwise the request is rejected with
        `ERR_DISCHARGE_WITHOUT_UPTAKE` (HTTP 422)."
        PRD section 2.10: "and those before temporal, constraint, referential, and
        fiscal checks on the request payload."

        Design: Corner/validations/discharge_without_uptake_priority_over_tank_balance
        """
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9100039", vessel_name="MV Gyrfalcon", voyage_number="V9501"
        )
        # No events at all on tank T3: violates both the no-prior-uptake rule and
        # the chronological-balance rule; the temporal uptake check wins.
        resp = post_ballast_event(
            vessel["id"], voyage["id"], event_kind="DISCHARGE",
            occurred_at="2026-07-29T06:00:00Z", tank_id="T3", volume_m3=100,
            latitude=35.0, longitude=-140.0, distance_from_shore_nm=250,
        )
        validate_error(resp, ApiErrorId.ERR_DISCHARGE_WITHOUT_UPTAKE)

    def test_exchange_below_3nm_rejected_exactly_3nm_accepted(self, api, vessel_master_headers):
        """PRD section 3.2: "An `EXCHANGE_COMPLETE` whose `distance_from_shore_nm` is
        less than 3 nautical miles is physically implausible for inshore exchange and
        is rejected with `ERR_EXCHANGE_TOO_CLOSE` (HTTP 422)."

        Design: Corner/validations/exchange_below_3nm_rejected_exactly_3nm_accepted
        """
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9100040", vessel_name="MV Hobby", voyage_number="V9502",
            bwms_type="EXCHANGE_ONLY",
        )
        post_uptake(vessel["id"], voyage["id"], tank_id="T1", volume_m3=300, salinity_ppt=32.0)

        too_close = post_ballast_event(
            vessel["id"], voyage["id"], event_kind="EXCHANGE_COMPLETE",
            occurred_at="2026-07-29T06:00:00Z", tank_id="T1", volume_m3=100,
            latitude=40.5, longitude=-73.0, distance_from_shore_nm=2.999,
        )
        validate_error(too_close, ApiErrorId.ERR_EXCHANGE_TOO_CLOSE)

        accepted = post_ballast_event(
            vessel["id"], voyage["id"], event_kind="EXCHANGE_COMPLETE",
            occurred_at="2026-07-29T07:00:00Z", tank_id="T1", volume_m3=100,
            latitude=40.5, longitude=-73.9, distance_from_shore_nm=3.0,
        )
        data = validate_success(accepted, 201)
        assert_ballast_event(data)


class TestCapacityConstraint:
    def test_volume_exceeds_capacity_returns_422(self, api, vessel_master_headers):
        """PRD section 3.2: "And no single event's `volume_m3` may exceed the vessel's
        `ballast_capacity_m3`; a violation is rejected with
        `ERR_VOLUME_EXCEEDS_CAPACITY` (HTTP 422)."

        Design: Corner/validations/volume_exceeds_capacity_returns_422
        """
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9100046", vessel_name="MV Raven", voyage_number="V9504"
        )
        resp = post_ballast_event(
            vessel["id"], voyage["id"], event_kind="UPTAKE",
            occurred_at="2026-07-28T06:00:00Z", tank_id="T1", volume_m3=30000.001,
            salinity_ppt=32.0, source_port_locode="USNYC",
        )
        validate_error(resp, ApiErrorId.ERR_VOLUME_EXCEEDS_CAPACITY)

    def test_volume_equal_to_capacity_accepted(self, api, vessel_master_headers):
        """PRD section 3.2: "And no single event's `volume_m3` may exceed the vessel's
        `ballast_capacity_m3`; a violation is rejected with
        `ERR_VOLUME_EXCEEDS_CAPACITY` (HTTP 422)."

        Design: Corner/validations/volume_equal_to_capacity_accepted
        """
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9100047", vessel_name="MV Siskin", voyage_number="V9505"
        )
        # "exceed" is strict: exactly ballast_capacity_m3 is accepted.
        resp = post_ballast_event(
            vessel["id"], voyage["id"], event_kind="UPTAKE",
            occurred_at="2026-07-28T06:00:00Z", tank_id="T1", volume_m3=30000.0,
            salinity_ppt=32.0, source_port_locode="USNYC",
        )
        data = validate_success(resp, 201)
        assert_ballast_event(data)


class TestEventOptimisticConcurrency:
    def test_occ_ballast_event_stale_version_returns_412(self, api, vessel_master_headers):
        """PRD section 2.7: "Recording a ballast water event requires
        `expected_voyage_version` matching the target voyage's current `version`."
        PRD section 2.7: "In each case, if the supplied value does not match the
        parent entity's current `version` — because another writer has advanced that
        version since the client last read it — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_ballast_event_stale_version_returns_412
        """
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9100066", vessel_name="MV Quelea", voyage_number="V9805"
        )
        observed = get_voyage_version(vessel["id"], voyage["id"])
        # First event advances the voyage version past the observed value.
        post_ballast_event_ok(
            vessel["id"], voyage["id"], expected_voyage_version=observed,
            event_kind="UPTAKE", occurred_at="2026-07-28T06:00:00Z", tank_id="T1",
            volume_m3=100, salinity_ppt=32.0, source_port_locode="USNYC",
        )

        resp = post_ballast_event(
            vessel["id"], voyage["id"], expected_voyage_version=observed,
            event_kind="UPTAKE", occurred_at="2026-07-28T07:00:00Z", tank_id="T2",
            volume_m3=100, salinity_ppt=32.0, source_port_locode="USNYC",
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        events = list_ballast_events(vessel["id"], voyage["id"])
        assert len(events) == 1, "stale event write must not be persisted"


class TestEventAppendOnlyShape:
    def test_ballast_event_immutability_no_version_field(self, api, vessel_master_headers):
        """PRD section 2.4: "Two entity kinds — `BallastWaterEvent` and
        `RecordBookEntry` — are append-only ledger records and carry only `id` and
        `created_at`; `updated_at` and `version` are absent from these two entities."

        Design: Corner/entities/ballast_event_immutability_no_version_field
        """
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9100013", vessel_name="MV Cormorant", voyage_number="V9201"
        )
        event = post_uptake(vessel["id"], voyage["id"], tank_id="T1", volume_m3=100,
                            salinity_ppt=32.0)
        assert_ballast_event(event)
        assert "version" not in event
        assert "updated_at" not in event
        assert event["id"]
        assert event["created_at"]
