"""Outage events, outage-credit waterfall, DARK threshold, posture cascades.

Covers difficulty outage_credit_cause_dependent_tiers,
outage_dark_threshold_240_minutes, outage_confirm_to_network_posture_chain,
and corner outage_credit_tier_boundaries, future_outage_rejected,
invalid_time_range_end_before_start, cascading_side_effects_outage_counter_propagates.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    create_outage_event_payload,
    get_success_data,
    make_nar_headers,
    make_platform_admin_headers,
    make_station_group_owner_headers,
    setup_basic_scenario,
    setup_clock,
    validate_error,
    validate_success,
)
from test_helpers import api_client
from test_helpers.fixtures import (
    create_active_agreement,
    create_outage_event,
    create_territory,
    confirm_outage_event,
    create_draft_agreement,
)
from test_helpers.factories import (
    create_network_payload,
    create_station_group_payload,
    create_station_payload,
)


def _list_credits_for_event(nid, sid, event_id, nar):
    """Return outage credits whose outage_event_id matches (list endpoint)."""
    data = validate_success(
        api_client.list_outage_credits(
            nid, sid, nar, params={"outage_event_id": event_id}
        ),
        expected_status=200,
    )
    items = data if isinstance(data, list) else data.get("data") or []
    return items


class TestOutageCreditTierBoundaries:
    def test_thirty_minute_outage_yields_15000(self, api):
        """PRD §3.7: "an outage of exactly 30 minutes yields 30 times 1.0
        times 500, or 15,000 cents."

        Design: Corner/calculations/outage_credit_tier_boundaries
        """
        scenario = setup_basic_scenario(clock_iso="2026-05-10T00:00:00Z")
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        sgo = scenario["sgo_headers"]
        nar = scenario["nar_headers"]
        oe = create_outage_event(
            nid, sid, sgo,
            started_at_utc="2026-05-05T01:00:00Z",
            ended_at_utc="2026-05-05T01:30:00Z",
            cause="POWER_LOSS",
        )
        confirm_outage_event(nid, sid, oe["id"], nar)
        credits = _list_credits_for_event(nid, sid, oe["id"], nar)
        assert len(credits) == 1, f"Expected 1 credit; got {len(credits)}"
        assert credits[0]["credit_cents"] == 15000, (
            f"30 minutes * 1.0 * 500 = 15000; got {credits[0]['credit_cents']}"
        )

    def test_thirty_one_minute_outage_yields_15750(self, api):
        """PRD §3.7: "an outage of exactly 31 minutes yields 30 times 500
        plus 1 times 750, or 15,750 cents."

        Design: Corner/calculations/outage_credit_tier_boundaries
        """
        scenario = setup_basic_scenario(clock_iso="2026-05-10T00:00:00Z")
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        sgo = scenario["sgo_headers"]
        nar = scenario["nar_headers"]
        oe = create_outage_event(
            nid, sid, sgo,
            started_at_utc="2026-05-06T01:00:00Z",
            ended_at_utc="2026-05-06T01:31:00Z",
            cause="POWER_LOSS",
        )
        confirm_outage_event(nid, sid, oe["id"], nar)
        credits = _list_credits_for_event(nid, sid, oe["id"], nar)
        assert credits[0]["credit_cents"] == 15750, (
            f"30*500 + 1*750 = 15750; got {credits[0]['credit_cents']}"
        )


class TestOutageCreditCauseMultiplier:
    def test_satellite_jam_uses_one_and_half_multiplier(self, api):
        """PRD §3.7: "That raw subtotal is then scaled by a cause multiplier:
        zero for `PLANNED_MAINTENANCE` (planned work earns no credit),
        one-and-a-half for `SATELLITE_JAM` (an aggravated cause), and one for
        every other cause."

        Design: Difficulty/dual_variant_calc/outage_credit_cause_dependent_tiers
        """
        scenario = setup_basic_scenario(clock_iso="2026-05-10T00:00:00Z")
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        sgo = scenario["sgo_headers"]
        nar = scenario["nar_headers"]
        # 200 minutes SATELLITE_JAM.
        # tier1 = 30, tier2 = 90, tier3 = 80
        # raw = (30*1.0 + 90*1.5 + 80*2.0) * 500 = 325 * 500 = 162500
        # scaled = 162500 * 1.5 = 243750
        oe = create_outage_event(
            nid, sid, sgo,
            started_at_utc="2026-05-05T01:00:00Z",
            ended_at_utc="2026-05-05T04:20:00Z",
            cause="SATELLITE_JAM",
        )
        confirm_outage_event(nid, sid, oe["id"], nar)
        credits = _list_credits_for_event(nid, sid, oe["id"], nar)
        assert credits[0]["credit_cents"] == 243750, (
            f"SATELLITE_JAM multiplier 1.5x applied: expected 243750; got "
            f"{credits[0]['credit_cents']}"
        )

    def test_planned_maintenance_zeroes_credit(self, api):
        """PRD §3.7: cause multiplier "zero for `PLANNED_MAINTENANCE`
        (planned work earns no credit)".

        Design: Difficulty/dual_variant_calc/outage_credit_cause_dependent_tiers
        """
        scenario = setup_basic_scenario(clock_iso="2026-05-10T00:00:00Z")
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        sgo = scenario["sgo_headers"]
        nar = scenario["nar_headers"]
        oe = create_outage_event(
            nid, sid, sgo,
            started_at_utc="2026-05-06T01:00:00Z",
            ended_at_utc="2026-05-06T04:20:00Z",
            cause="PLANNED_MAINTENANCE",
        )
        confirm_outage_event(nid, sid, oe["id"], nar)
        credits = _list_credits_for_event(nid, sid, oe["id"], nar)
        assert credits[0]["credit_cents"] == 0, (
            f"PLANNED_MAINTENANCE must zero credit; got "
            f"{credits[0]['credit_cents']}"
        )


class TestDarkThreshold:
    def test_240_minutes_does_not_dark(self, api):
        """PRD §2.9: "A station is `DARK` when its
        `monthly_outage_minutes_current_period` strictly exceeds 240 minutes."

        Design: Difficulty/boundary_precision_check/outage_dark_threshold_240_minutes
        """
        scenario = setup_basic_scenario(clock_iso="2026-05-10T00:00:00Z")
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        sgo = scenario["sgo_headers"]
        nar = scenario["nar_headers"]
        oe = create_outage_event(
            nid, sid, sgo,
            started_at_utc="2026-05-05T00:00:00Z",
            ended_at_utc="2026-05-05T04:00:00Z",  # exactly 240 min
            cause="POWER_LOSS",
        )
        confirm_outage_event(nid, sid, oe["id"], nar)
        station = validate_success(api_client.get_station(nid, sid, nar))
        assert station["monthly_outage_minutes_current_period"] == 240
        assert station["posture"] != "DARK", (
            f"Strictly-greater-than 240 means 240 is NOT DARK; got "
            f"{station['posture']!r}"
        )

    def test_241_minutes_goes_dark(self, api):
        """PRD §2.9: "A station is `DARK` when its
        `monthly_outage_minutes_current_period` strictly exceeds 240 minutes."

        Design: Difficulty/boundary_precision_check/outage_dark_threshold_240_minutes
        """
        scenario = setup_basic_scenario(clock_iso="2026-05-10T00:00:00Z")
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        sgo = scenario["sgo_headers"]
        nar = scenario["nar_headers"]
        # 240-minute event
        oe1 = create_outage_event(
            nid, sid, sgo,
            started_at_utc="2026-05-05T00:00:00Z",
            ended_at_utc="2026-05-05T04:00:00Z",
            cause="POWER_LOSS",
        )
        confirm_outage_event(nid, sid, oe1["id"], nar)
        # Additional 1-minute event pushes to 241.
        oe2 = create_outage_event(
            nid, sid, sgo,
            started_at_utc="2026-05-06T00:00:00Z",
            ended_at_utc="2026-05-06T00:01:00Z",
            cause="POWER_LOSS",
        )
        confirm_outage_event(nid, sid, oe2["id"], nar)
        station = validate_success(api_client.get_station(nid, sid, nar))
        assert station["monthly_outage_minutes_current_period"] == 241
        assert station["posture"] == "DARK", (
            f"241 > 240 must drive DARK; got {station['posture']!r}"
        )


class TestOutageCascade:
    def test_outage_confirm_bumps_station_outage_counter(self, api):
        """PRD §3.7: "Confirmation is the cascade point: an `OutageCredit` is
        created in `PENDING` with `credit_cents` computed per the
        outage-credit formula; the station's
        `monthly_outage_minutes_current_period` is incremented by
        `duration_minutes`".

        Design: Corner/cross_cutting_layers/cascading_side_effects_outage_counter_propagates
        """
        scenario = setup_basic_scenario(clock_iso="2026-05-10T00:00:00Z")
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        sgo = scenario["sgo_headers"]
        nar = scenario["nar_headers"]
        oe = create_outage_event(
            nid, sid, sgo,
            started_at_utc="2026-05-05T01:00:00Z",
            ended_at_utc="2026-05-05T02:00:00Z",  # 60 minutes
            cause="POWER_LOSS",
        )
        confirm_outage_event(nid, sid, oe["id"], nar)
        station = validate_success(api_client.get_station(nid, sid, nar))
        assert station["monthly_outage_minutes_current_period"] == 60

    def test_dark_station_blocks_agreement_submit(self, api):
        """PRD §3.2: "The submit is permitted only when the station's posture
        is not `DARK`". PRD §2.10 step 4 surfaces this as ERR_INVALID_STATE
        for state-admissibility failures.
        PRD §3.7: "the station's posture is recomputed (and becomes `DARK` if
        the new total strictly exceeds 240 minutes)".

        Design: Difficulty/transitive_cascade/outage_confirm_to_network_posture_chain
        """
        # Setup: station S1 with ACTIVE agreement; drive S1 DARK via two
        # 130-minute outages; also create station S2 with a DRAFT agreement
        # as a control that submission still works for non-DARK stations.
        setup_clock("2026-05-10T00:00:00Z")
        admin = make_platform_admin_headers()
        nar = make_nar_headers()
        net = get_success_data(api_client.create_network(create_network_payload(), admin))
        grp = get_success_data(
            api_client.create_station_group(create_station_group_payload(), admin)
        )
        sgo = make_station_group_owner_headers(grp["id"])
        st1 = get_success_data(
            api_client.create_station(
                net["id"],
                create_station_payload(
                    station_group_id=grp["id"], call_sign="KPBN", dma_code="DMA-001"
                ),
                nar,
            )
        )
        st2 = get_success_data(
            api_client.create_station(
                net["id"],
                create_station_payload(
                    station_group_id=grp["id"], call_sign="WPBN", dma_code="DMA-002"
                ),
                nar,
            )
        )
        create_territory(net["id"], dma_code="DMA-001")
        create_territory(net["id"], dma_code="DMA-002")
        create_active_agreement(net["id"], st1["id"])
        # Two 130-minute outages on st1.
        oe1 = create_outage_event(
            net["id"], st1["id"], sgo,
            started_at_utc="2026-05-05T01:00:00Z",
            ended_at_utc="2026-05-05T03:10:00Z",
            cause="TRANSMITTER_FAILURE",
        )
        confirm_outage_event(net["id"], st1["id"], oe1["id"], nar)
        oe2 = create_outage_event(
            net["id"], st1["id"], sgo,
            started_at_utc="2026-05-06T01:00:00Z",
            ended_at_utc="2026-05-06T03:10:00Z",
            cause="FIBER_CUT",
        )
        confirm_outage_event(net["id"], st1["id"], oe2["id"], nar)
        # Verify DARK.
        st1_after = validate_success(api_client.get_station(net["id"], st1["id"], nar))
        assert st1_after["posture"] == "DARK", (
            f"130+130=260 > 240 must drive DARK; got {st1_after['posture']!r}"
        )
        # Control: a new agreement on st2 submits fine.
        ag2 = create_draft_agreement(net["id"], st2["id"])
        resp_ok = api_client.submit_agreement(net["id"], st2["id"], ag2["id"], nar)
        ok_data = validate_success(resp_ok, expected_status=200)
        assert ok_data["status"] == "PENDING_ACTIVATION"
        # S1 (DARK): submit must fail with ERR_INVALID_STATE.
        ag_dark = create_draft_agreement(net["id"], st1["id"])
        resp = api_client.submit_agreement(net["id"], st1["id"], ag_dark["id"], nar)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestDarkStationCascadeSecondWitness:
    def test_dark_station_does_not_block_other_stations_agreement_submit(self, api):
        """PRD §3.2: "The submit is permitted only when the station's posture
        is not `DARK`". The block is per-station; a sibling station under the
        same network is unaffected.

        Design: Difficulty/transitive_cascade/outage_confirm_to_network_posture_chain
        """
        # Build scenario: st1 driven DARK; st2 (unaffected) can still submit.
        setup_clock("2026-05-10T00:00:00Z")
        admin = make_platform_admin_headers()
        nar = make_nar_headers()
        net = get_success_data(api_client.create_network(create_network_payload(), admin))
        grp = get_success_data(
            api_client.create_station_group(create_station_group_payload(), admin)
        )
        sgo = make_station_group_owner_headers(grp["id"])
        st1 = get_success_data(
            api_client.create_station(
                net["id"],
                create_station_payload(
                    station_group_id=grp["id"], call_sign="KPBN", dma_code="DMA-001"
                ),
                nar,
            )
        )
        st2 = get_success_data(
            api_client.create_station(
                net["id"],
                create_station_payload(
                    station_group_id=grp["id"], call_sign="WPBN", dma_code="DMA-002"
                ),
                nar,
            )
        )
        create_territory(net["id"], dma_code="DMA-001")
        create_territory(net["id"], dma_code="DMA-002")
        create_active_agreement(net["id"], st1["id"])
        # Drive st1 DARK with 241 minutes.
        oe = create_outage_event(
            net["id"], st1["id"], sgo,
            started_at_utc="2026-05-05T00:00:00Z",
            ended_at_utc="2026-05-05T04:01:00Z",  # 241 min
            cause="TRANSMITTER_FAILURE",
        )
        confirm_outage_event(net["id"], st1["id"], oe["id"], nar)
        # Control: a new DRAFT agreement on st2 must still submit cleanly.
        ag2 = create_draft_agreement(net["id"], st2["id"])
        resp = api_client.submit_agreement(net["id"], st2["id"], ag2["id"], nar)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "PENDING_ACTIVATION", (
            "DARK posture on st1 must not block st2's submit"
        )


class TestOutageValidation:
    def test_invalid_time_range_rejected(self, api):
        """PRD §2.10 step 8: "every (start, end) pair in the payload has end
        strictly greater than start (else `ERR_INVALID_TIME_RANGE`)."
        PRD §3.7: "the `started_at_utc` and `ended_at_utc` (end strictly
        after start, ...)".

        Design: Corner/validations/invalid_time_range_end_before_start
        """
        scenario = setup_basic_scenario(clock_iso="2026-05-10T00:00:00Z")
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        sgo = scenario["sgo_headers"]
        resp = api_client.create_outage_event(
            nid, sid,
            create_outage_event_payload(
                started_at_utc="2026-05-05T02:00:00Z",
                ended_at_utc="2026-05-05T01:00:00Z",
                cause="POWER_LOSS",
            ),
            sgo,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_TIME_RANGE)

    def test_future_outage_rejected(self, api):
        """PRD §3.7: "the end must not lie in the future relative to
        `current_utc` — future outages are rejected with `ERR_FUTURE_OUTAGE`
        (HTTP 422)".

        Design: Corner/validations/future_outage_rejected
        """
        scenario = setup_basic_scenario(clock_iso="2026-05-10T00:00:00Z")
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        sgo = scenario["sgo_headers"]
        resp = api_client.create_outage_event(
            nid, sid,
            create_outage_event_payload(
                started_at_utc="2026-05-11T01:00:00Z",
                ended_at_utc="2026-05-11T02:00:00Z",
                cause="POWER_LOSS",
            ),
            sgo,
        )
        validate_error(resp, ApiErrorId.ERR_FUTURE_OUTAGE)
