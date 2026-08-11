"""Syndication exclusivity claims: half-open window overlap.

Covers difficulty exclusivity_window_half_open_adjacency.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    get_success_data,
    setup_basic_scenario,
    validate_error,
    validate_success,
)
from test_helpers import api_client
from test_helpers.factories import (
    create_exclusivity_claim_payload,
    create_station_payload,
    create_territory_payload,
)
from test_helpers.fixtures import create_program, create_exclusivity_claim
from test_helpers.test_users import make_nar_headers


def _setup_two_stations_one_territory(api):
    """Two stations in the same DMA; the first holds the territory's
    exclusivity (via ACTIVE agreement). Returns the scenario dict + second
    station id."""
    scenario = setup_basic_scenario(
        clock_iso="2026-05-01T00:00:00Z",
        leverage_tier="MID",
    )
    nar = scenario["nar_headers"]
    # Second station in the SAME dma_code (DMA-001). It has no agreement;
    # it's the respondent.
    st2 = get_success_data(
        api_client.create_station(
            scenario["network"]["id"],
            create_station_payload(
                station_group_id=scenario["group"]["id"],
                call_sign="WPBN",
                dma_code=scenario["station"]["dma_code"],
            ),
            nar,
        )
    )
    # Syndicated program.
    program = create_program(
        scenario["network"]["id"],
        title="Syndicated Show",
        scheduled_start_utc="2026-06-01T20:00:00Z",
        scheduled_end_utc="2026-06-01T22:00:00Z",
        avail_minutes_total=10,
        avail_minutes_local_allocatable=5,
        is_syndicated=True,
    )
    return scenario, st2, program


class TestHalfOpenWindowOverlap:
    def test_adjacent_window_does_not_overlap(self, api):
        """PRD §3.10: "Adjacent windows — where the alleged end equals the
        protection start — do **not** overlap, because the intersection is
        zero-length. Failure to overlap is rejected with
        `ERR_NO_WINDOW_OVERLAP` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/exclusivity_window_half_open_adjacency
        """
        scenario, st2, program = _setup_two_stations_one_territory(api)
        nid = scenario["network"]["id"]
        sgo = scenario["sgo_headers"]
        nar = scenario["nar_headers"]
        territory = scenario["territory"]
        # Recreate territory with a specific 20:00-22:00 protection window.
        terr_resp = api_client.create_territory(
            nid,
            create_territory_payload(
                dma_code="DMA-002",
                protection_window_start_utc="2026-06-01T20:00:00Z",
                protection_window_end_utc="2026-06-01T22:00:00Z",
            ),
            nar,
        )
        terr2 = get_success_data(terr_resp)
        # Claim alleging [19:00, 20:00) — adjacent, zero-length intersection.
        claim = get_success_data(
            api_client.create_exclusivity_claim(
                nid, terr2["id"],
                create_exclusivity_claim_payload(
                    program_id=program["id"],
                    claimant_station_id=scenario["station"]["id"],
                    respondent_station_id=st2["id"],
                    alleged_window_start_utc="2026-06-01T19:00:00Z",
                    alleged_window_end_utc="2026-06-01T20:00:00Z",
                ),
                sgo,
            )
        )
        resp = api_client.validate_exclusivity_claim(nid, terr2["id"], claim["id"], nar)
        validate_error(resp, ApiErrorId.ERR_NO_WINDOW_OVERLAP)

    def test_one_second_overlap_validates(self, api):
        """PRD §3.10: "an overlap exists exactly when the alleged start is
        strictly before the protection end **and** the alleged end is
        strictly after the protection start."

        Design: Difficulty/resource_temporal_overlap/exclusivity_window_half_open_adjacency
        """
        scenario, st2, program = _setup_two_stations_one_territory(api)
        nid = scenario["network"]["id"]
        sgo = scenario["sgo_headers"]
        nar = scenario["nar_headers"]
        # Territory held by scenario["station"] covering dma_code DMA-001.
        # Use the existing territory's protection window (default
        # 2026-05-01..2026-06-30); claim a window that overlaps by 1 second
        # into the protection start.
        terr_id = scenario["territory"]["id"]
        # Protection window: 2026-05-01T00:00:00Z .. 2026-06-30T00:00:00Z.
        # Claim window: 2026-04-30T23:59:59Z .. 2026-05-01T00:00:01Z
        # -> end strictly after start of protection by 1 second.
        claim = get_success_data(
            api_client.create_exclusivity_claim(
                nid, terr_id,
                create_exclusivity_claim_payload(
                    program_id=program["id"],
                    claimant_station_id=scenario["station"]["id"],
                    respondent_station_id=st2["id"],
                    alleged_window_start_utc="2026-04-30T23:59:59Z",
                    alleged_window_end_utc="2026-05-01T00:00:01Z",
                ),
                sgo,
            )
        )
        resp = api_client.validate_exclusivity_claim(nid, terr_id, claim["id"], nar)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "VALIDATED", (
            f"1-second intersection must overlap; got {data['status']!r}"
        )
