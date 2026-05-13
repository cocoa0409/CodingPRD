"""Device lifecycle, configuration validation, and reading ingest.

Covers PRD §3.4 (device PROVISIONED → ACTIVE → OFFLINE → DECOMMISSIONED),
PRD §3.4 reading validity classification, PRD §3.4 idempotency, and PRD
§3.4 timestamp-window check.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId, CO, CO_ALT, TA,
    advance_clock, create_and_activate_pressure_device,
    create_device, create_network, get_network, get_device,
    iso_from_epoch_ms,
    create_device_payload, post_reading_payload,
    patch_device_payload,
    setup_published_network_with_one_segment,
    validate_error, validate_success,
)


class TestDeviceConfigValidation:
    """PRD §3.4 ERR_DEVICE_CONFIG_INVALID."""

    @pytest.mark.parametrize("polling_s", [29, 3601])
    def test_polling_interval_out_of_range(self, api, polling_s):
        """PRD §3.4: "The polling interval must lie between 30 and 3600
        seconds inclusive ... violations are rejected with
        ERR_DEVICE_CONFIG_INVALID and HTTP 422."

        Boundary precision: 30 and 3600 are inclusive — 29 and 3601 are
        rejected.
        """
        base = setup_published_network_with_one_segment(api)
        payload = create_device_payload(
            mounted_on_node_code=base["node_from"]["node_code"],
            sensor_kind="PRESSURE",
            polling_interval_s=polling_s,
            valid_range_min=200.0, valid_range_max=600.0,
        )
        resp = api.create_device(base["network"]["id"], payload, CO)
        validate_error(resp, ApiErrorId.ERR_DEVICE_CONFIG_INVALID.value)

    def test_valid_range_min_not_less_than_max_rejected(self, api):
        """PRD §3.4: "the lower bound must be strictly less than the
        upper bound; violations are rejected with
        ERR_DEVICE_CONFIG_INVALID and HTTP 422."
        """
        base = setup_published_network_with_one_segment(api)
        payload = create_device_payload(
            mounted_on_node_code=base["node_from"]["node_code"],
            sensor_kind="PRESSURE",
            polling_interval_s=60,
            valid_range_min=500.0, valid_range_max=500.0,
        )
        resp = api.create_device(base["network"]["id"], payload, CO)
        validate_error(resp, ApiErrorId.ERR_DEVICE_CONFIG_INVALID.value)


class TestDeviceActivation:
    """PRD §3.4 PROVISIONED → ACTIVE preconditions."""

    def test_unmounted_device_cannot_activate(self, api):
        """PRD §3.4: "a device with no mount, or one whose mount no longer
        exists in the active version, is rejected with ERR_DEVICE_UNMOUNTED
        and HTTP 409."
        """
        base = setup_published_network_with_one_segment(api)
        # No mounted_on_node_code passed.
        payload = create_device_payload(
            sensor_kind="PRESSURE",
            polling_interval_s=60,
            valid_range_min=200.0, valid_range_max=600.0,
        )
        # Make payload truly omit mounted_on_node_code.
        payload.pop("mounted_on_node_code", None)
        dev = validate_success(
            api.create_device(base["network"]["id"], payload, CO),
            expected_status=201,
        )
        resp = api.activate_device(base["network"]["id"], dev["id"], CO)
        validate_error(resp, ApiErrorId.ERR_DEVICE_UNMOUNTED.value)

    def test_happy_path_activate(self, api):
        """PRD §3.4: "A device transitions from PROVISIONED to ACTIVE
        when an operator activates it. Activation requires that
        mounted_on_node_code is non-null and resolves to a node in the
        network's currently PUBLISHED topology version."
        """
        base = setup_published_network_with_one_segment(api)
        dev = create_and_activate_pressure_device(
            api, base["network"]["id"],
            mounted_on_node_code=base["node_from"]["node_code"],
        )
        assert dev["status"] == "ACTIVE"

    def test_device_mounted_on_superseded_node_cannot_activate(self, api):
        """PRD §3.4: "Activation requires that mounted_on_node_code is
        non-null and resolves to a node in the network's currently
        PUBLISHED topology version; a device with no mount, or one whose
        mount no longer exists in the active version, is rejected with
        ERR_DEVICE_UNMOUNTED and HTTP 409."

        # difficulty: cross_entity_state_dependency/device_activation_requires_active_topology_node
        Claim: a device whose mount existed in V1 but not in the now-
        active V2 → ERR_DEVICE_UNMOUNTED.
        """
        from test_helpers import (
            add_node, add_segment, approve_topology, create_draft_topology,
            submit_topology, TE,
        )
        base = setup_published_network_with_one_segment(api)
        net_id = base["network"]["id"]

        # Create PROVISIONED device mounted on J1 (does not activate yet).
        payload = create_device_payload(
            mounted_on_node_code=base["node_from"]["node_code"],
            sensor_kind="PRESSURE",
            polling_interval_s=60,
            valid_range_min=200.0, valid_range_max=600.0,
        )
        dev = validate_success(
            api.create_device(net_id, payload, CO),
            expected_status=201,
        )
        # Build V2 *without* J1 and publish it.
        v2 = create_draft_topology(api, net_id,
                                   parent_version_id=base["version"]["id"])
        n_from = add_node(api, net_id, v2["id"],
                          dma_id=base["dma"]["id"], kind="JUNCTION")
        n_to = add_node(api, net_id, v2["id"],
                        dma_id=base["dma"]["id"], kind="JUNCTION")
        add_segment(api, net_id, v2["id"],
                    from_node_code=n_from["node_code"],
                    to_node_code=n_to["node_code"])
        submit_topology(api, net_id, v2["id"])
        approve_topology(api, net_id, v2["id"])

        # Try to activate DV1; its mount no longer exists in the active
        # topology.
        resp = api.activate_device(net_id, dev["id"], CO)
        validate_error(resp, ApiErrorId.ERR_DEVICE_UNMOUNTED.value)


class TestDeviceOCC:
    """PRD §2.4 optimistic concurrency on PATCH endpoints."""

    def test_patch_stale_version_rejected(self, api):
        """PRD §2.4: "If the client supplies a version that no longer
        matches, the request is rejected with ERR_VERSION_CONFLICT and
        HTTP 409."
        """
        base = setup_published_network_with_one_segment(api)
        dev = create_and_activate_pressure_device(
            api, base["network"]["id"],
            mounted_on_node_code=base["node_from"]["node_code"],
        )
        # First patch successfully advances version.
        ok = validate_success(
            api.patch_device(
                base["network"]["id"], dev["id"],
                patch_device_payload(version=dev["version"],
                                     polling_interval_s=120),
                CO,
            )
        )
        # Second patch with the *original* version (stale) must fail.
        resp = api.patch_device(
            base["network"]["id"], dev["id"],
            patch_device_payload(version=dev["version"],
                                 polling_interval_s=180),
            CO,
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT.value)


class TestReadingTimestampWindow:
    """PRD §3.4 backdate / forward windows."""

    def test_observed_at_too_far_in_future_rejected(self, api):
        """PRD §3.4: "observed_at must fall within a backdate window of
        seven days behind the current clock_now and a forward window of
        60 seconds ahead ... or the reading is rejected with
        ERR_READING_TIMESTAMP_OUT_OF_RANGE and HTTP 422."

        Claim: observed_at = clock_now + 120s → reject.
        """
        base = setup_published_network_with_one_segment(api)
        net_id = base["network"]["id"]
        dev = create_and_activate_pressure_device(
            api, net_id,
            mounted_on_node_code=base["node_from"]["node_code"],
        )
        net = get_network(api, net_id)
        future = iso_from_epoch_ms(net["clock_epoch_ms"] + 120_000)
        resp = api.post_reading(net_id, dev["id"],
                                post_reading_payload(future, 400.0),
                                CO)
        validate_error(resp,
                       ApiErrorId.ERR_READING_TIMESTAMP_OUT_OF_RANGE.value)

    def test_observed_at_too_old_rejected(self, api):
        """PRD §3.4: "observed_at must fall within a backdate window of
        seven days behind the current clock_now and a forward window of
        60 seconds ahead ... or the reading is rejected with
        ERR_READING_TIMESTAMP_OUT_OF_RANGE and HTTP 422."

        Claim: observed_at older than 604800s ago → reject.
        """
        base = setup_published_network_with_one_segment(api)
        net_id = base["network"]["id"]
        dev = create_and_activate_pressure_device(
            api, net_id,
            mounted_on_node_code=base["node_from"]["node_code"],
        )
        net = get_network(api, net_id)
        too_old = iso_from_epoch_ms(net["clock_epoch_ms"] - 700_000_000)
        resp = api.post_reading(net_id, dev["id"],
                                post_reading_payload(too_old, 400.0),
                                CO)
        validate_error(resp,
                       ApiErrorId.ERR_READING_TIMESTAMP_OUT_OF_RANGE.value)


class TestReadingValidity:
    """PRD §3.4 reading validity classification."""

    def test_in_range_reading_accepted(self, api):
        """PRD §3.4: "a value strictly within the range (lower bound
        inclusive, upper bound inclusive) is ACCEPTED."

        Claim: mid-range value → validity=ACCEPTED.
        """
        base = setup_published_network_with_one_segment(api)
        net_id = base["network"]["id"]
        dev = create_and_activate_pressure_device(
            api, net_id,
            mounted_on_node_code=base["node_from"]["node_code"],
        )
        net = get_network(api, net_id)
        observed_at = iso_from_epoch_ms(net["clock_epoch_ms"] - 1000)
        reading = validate_success(
            api.post_reading(net_id, dev["id"],
                             post_reading_payload(observed_at, 400.0),
                             CO),
            expected_status=201,
        )
        assert reading["validity"] == "ACCEPTED"

    def test_out_of_range_non_strict_stored_as_abnormal(self, api):
        """PRD §3.4: "a value outside is normally stored with validity
        set to ABNORMAL_OUT_OF_RANGE but does not update the device's
        last_reading_at or last_reading_value."

        Claim: out-of-range without strict_mode → 201 with
        validity=ABNORMAL_OUT_OF_RANGE; device last_reading_at unchanged.
        """
        base = setup_published_network_with_one_segment(api)
        net_id = base["network"]["id"]
        dev = create_and_activate_pressure_device(
            api, net_id,
            mounted_on_node_code=base["node_from"]["node_code"],
        )
        net = get_network(api, net_id)
        observed_at = iso_from_epoch_ms(net["clock_epoch_ms"] - 1000)
        reading = validate_success(
            api.post_reading(net_id, dev["id"],
                             post_reading_payload(observed_at, 1000.0),
                             CO),
            expected_status=201,
        )
        assert reading["validity"] == "ABNORMAL_OUT_OF_RANGE"

        dev_after = get_device(api, net_id, dev["id"])
        assert dev_after.get("last_reading_at") in (None, "")
        assert dev_after.get("last_reading_value") in (None, 0, 0.0)

    def test_out_of_range_strict_mode_rejected(self, api):
        """PRD §3.4: "When the operator passes the strict_mode flag set
        to true, an out-of-range raw value is instead rejected with
        ERR_READING_OUT_OF_RANGE and HTTP 422."
        """
        base = setup_published_network_with_one_segment(api)
        net_id = base["network"]["id"]
        dev = create_and_activate_pressure_device(
            api, net_id,
            mounted_on_node_code=base["node_from"]["node_code"],
        )
        net = get_network(api, net_id)
        observed_at = iso_from_epoch_ms(net["clock_epoch_ms"] - 1000)
        resp = api.post_reading(
            net_id, dev["id"],
            post_reading_payload(observed_at, 1000.0),
            CO, params={"strict_mode": "true"},
        )
        validate_error(resp, ApiErrorId.ERR_READING_OUT_OF_RANGE.value)


class TestReadingIdempotency:
    """PRD §3.4 idempotency-key replays."""

    def test_replay_returns_original_reading_with_err_duplicate(self, api):
        """PRD §3.4: "the duplicate request returns the original Reading
        with the same id as the first, the response carries HTTP 200
        (not 201, because no new resource was created), and the response
        surfaces ERR_DUPLICATE_READING as the idempotency-replay signal."

        Claim: second POST with the same (device_id, idempotency_key)
        returns 200 with error_id=ERR_DUPLICATE_READING; the underlying
        Reading.id matches the original.
        """
        base = setup_published_network_with_one_segment(api)
        net_id = base["network"]["id"]
        dev = create_and_activate_pressure_device(
            api, net_id,
            mounted_on_node_code=base["node_from"]["node_code"],
        )
        net = get_network(api, net_id)
        observed_at = iso_from_epoch_ms(net["clock_epoch_ms"] - 1000)
        key = "idem-key-001"
        first = validate_success(
            api.post_reading(net_id, dev["id"],
                             post_reading_payload(observed_at, 400.0, key),
                             CO),
            expected_status=201,
        )

        # Replay — must be 200, with ERR_DUPLICATE_READING.
        resp2 = api.post_reading(net_id, dev["id"],
                                 post_reading_payload(observed_at, 400.0, key),
                                 CO)
        assert resp2.status_code == 200
        body = resp2.json()
        # Per PRD §3.4 / §5: idempotency replay carries ERR_DUPLICATE_READING.
        assert body["data"].get("error_id") == ApiErrorId.ERR_DUPLICATE_READING.value


class TestArchiveTier:
    """PRD §3.4 archive-tier thresholds."""

    def test_fresh_reading_is_hot(self, api):
        """PRD §3.4: "A reading with age strictly less than 86400 seconds
        is HOT."
        """
        base = setup_published_network_with_one_segment(api)
        net_id = base["network"]["id"]
        dev = create_and_activate_pressure_device(
            api, net_id,
            mounted_on_node_code=base["node_from"]["node_code"],
        )
        net = get_network(api, net_id)
        observed_at = iso_from_epoch_ms(net["clock_epoch_ms"] - 1000)
        reading = validate_success(
            api.post_reading(net_id, dev["id"],
                             post_reading_payload(observed_at, 400.0),
                             CO),
            expected_status=201,
        )
        assert reading["archive_tier"] == "HOT"

    def test_reading_advances_to_warm_after_one_day(self, api):
        """PRD §3.4: "from 86400 seconds (inclusive) to 2592000 seconds
        (exclusive) it is WARM."

        Claim: after a clock-advance of 86400000 ms, a reading transitions
        from HOT to WARM.
        """
        base = setup_published_network_with_one_segment(api)
        net_id = base["network"]["id"]
        dev = create_and_activate_pressure_device(
            api, net_id,
            mounted_on_node_code=base["node_from"]["node_code"],
            polling_interval_s=3600,
        )
        net = get_network(api, net_id)
        observed_at = iso_from_epoch_ms(net["clock_epoch_ms"] - 1000)
        validate_success(
            api.post_reading(net_id, dev["id"],
                             post_reading_payload(observed_at, 400.0),
                             CO),
            expected_status=201,
        )
        # Advance just past 86400 seconds.
        advance_clock(api, net_id, 86_400_000)

        # The most recent reading should be WARM now.
        resp = api.list_readings(net_id, dev["id"], CO)
        body = resp.json()
        readings = body["data"]
        assert any(r["archive_tier"] in ("WARM", "COLD") for r in readings), \
            f"Expected at least one reading to advance to WARM after 86400s, got tiers: " \
            f"{[r['archive_tier'] for r in readings]}"


class TestClockAdvance:
    """PRD §3.1 / §2.5 clock-advance semantics."""

    def test_advance_ms_must_be_positive(self, api):
        """PRD §3.1: "advance_ms body parameter, which must be strictly
        greater than zero."
        """
        net = create_network(api)
        resp = api.advance_clock(net["id"], {"advance_ms": 0}, CO)
        validate_error(resp, ApiErrorId.ERR_BAD_REQUEST.value)

    def test_advance_increments_clock(self, api):
        """PRD §2.5: "Advancing the clock triggers three sweeps in
        order"; PRD §3.1: clock "only advances through an explicit
        clock-advance capability."

        Claim: advance_ms=5000 increases clock_epoch_ms by 5000.
        """
        net = create_network(api)
        before = net["clock_epoch_ms"]
        after_net = advance_clock(api, net["id"], 5000)
        assert after_net["clock_epoch_ms"] == before + 5000
