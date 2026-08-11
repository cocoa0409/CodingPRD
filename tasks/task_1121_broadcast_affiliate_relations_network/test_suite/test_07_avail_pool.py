"""Avail allocation waterfall: aggregate capacity semantics and pool conservation.

Covers difficulty instances avail_pool_exhaustion_exact_fit,
avail_pool_aggregate_capacity, avail_pool_conservation_under_revoke.
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
from test_helpers.fixtures import (
    create_avail_allocation,
    confirm_avail_allocation,
    create_program,
)


class TestAvailPoolBoundary:
    def test_exact_fit_confirms(self, api):
        """PRD §3.8: "the sum of `local_minutes_claimed` across every
        already-`CONFIRMED` allocation for the same program, plus this claim,
        does not exceed the program's `avail_minutes_local_allocatable`."

        Design: Difficulty/boundary_precision_check/avail_pool_exhaustion_exact_fit
        """
        scenario = setup_basic_scenario()
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        sgo = scenario["sgo_headers"]
        nar = scenario["nar_headers"]
        program = create_program(nid, avail_minutes_total=20,
                                 avail_minutes_local_allocatable=10,
                                 is_syndicated=False)
        aa1 = create_avail_allocation(nid, sid, program["id"], sgo,
                                      local_minutes_claimed=4)
        confirm_avail_allocation(nid, sid, aa1["id"], nar)
        aa2 = create_avail_allocation(nid, sid, program["id"], sgo,
                                      local_minutes_claimed=6)
        resp = api_client.confirm_avail_allocation(nid, sid, aa2["id"], nar)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "CONFIRMED", (
            f"4+6=10 == pool cap 10 must confirm; got {data['status']!r}"
        )

    def test_one_minute_over_pool_rejected(self, api):
        """PRD §3.8: "Exceeding that pool is rejected with
        `ERR_AVAIL_POOL_EXHAUSTED` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/avail_pool_exhaustion_exact_fit
        """
        scenario = setup_basic_scenario()
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        sgo = scenario["sgo_headers"]
        nar = scenario["nar_headers"]
        program = create_program(nid, avail_minutes_total=20,
                                 avail_minutes_local_allocatable=10,
                                 is_syndicated=False)
        aa1 = create_avail_allocation(nid, sid, program["id"], sgo,
                                      local_minutes_claimed=4)
        confirm_avail_allocation(nid, sid, aa1["id"], nar)
        aa2 = create_avail_allocation(nid, sid, program["id"], sgo,
                                      local_minutes_claimed=6)
        confirm_avail_allocation(nid, sid, aa2["id"], nar)
        # Pool now exhausted; one more minute must fail.
        aa3 = create_avail_allocation(nid, sid, program["id"], sgo,
                                      local_minutes_claimed=1)
        resp = api_client.confirm_avail_allocation(nid, sid, aa3["id"], nar)
        validate_error(resp, ApiErrorId.ERR_AVAIL_POOL_EXHAUSTED)


class TestAvailPoolAggregateSemantics:
    def test_aggregate_capacity_not_pairwise_overlap(self, api):
        """PRD §3.8: "This is aggregate capacity semantics, not pairwise
        interval overlap; two claims against the same program can perfectly
        well coexist as long as their minutes fit under the cap."
        PRD §3.8: "Exceeding that pool is rejected with
        `ERR_AVAIL_POOL_EXHAUSTED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/avail_pool_aggregate_capacity
        """
        scenario = setup_basic_scenario()
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        sgo = scenario["sgo_headers"]
        nar = scenario["nar_headers"]
        program = create_program(nid, avail_minutes_total=20,
                                 avail_minutes_local_allocatable=10,
                                 is_syndicated=False)
        # Two claims (4 + 6) coexist fine under the cap.
        aa1 = create_avail_allocation(nid, sid, program["id"], sgo,
                                      local_minutes_claimed=4)
        confirm_avail_allocation(nid, sid, aa1["id"], nar)
        aa2 = create_avail_allocation(nid, sid, program["id"], sgo,
                                      local_minutes_claimed=6)
        confirm_avail_allocation(nid, sid, aa2["id"], nar)
        # 4 + 6 + 1 = 11 > 10 → ERR_AVAIL_POOL_EXHAUSTED.
        aa3 = create_avail_allocation(nid, sid, program["id"], sgo,
                                      local_minutes_claimed=1)
        resp = api_client.confirm_avail_allocation(nid, sid, aa3["id"], nar)
        validate_error(resp, ApiErrorId.ERR_AVAIL_POOL_EXHAUSTED)


class TestAvailPoolAggregateCoexistence:
    def test_two_claims_coexist_under_cap(self, api):
        """PRD §3.8: "two claims against the same program can perfectly well
        coexist as long as their minutes fit under the cap."

        Design: Difficulty/resource_temporal_overlap/avail_pool_aggregate_capacity
        """
        scenario = setup_basic_scenario()
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        sgo = scenario["sgo_headers"]
        nar = scenario["nar_headers"]
        program = create_program(nid, avail_minutes_total=20,
                                 avail_minutes_local_allocatable=10,
                                 is_syndicated=False)
        aa1 = create_avail_allocation(nid, sid, program["id"], sgo,
                                      local_minutes_claimed=3)
        aa2 = create_avail_allocation(nid, sid, program["id"], sgo,
                                      local_minutes_claimed=7)
        d1 = validate_success(
            api_client.confirm_avail_allocation(nid, sid, aa1["id"], nar),
            expected_status=200,
        )
        d2 = validate_success(
            api_client.confirm_avail_allocation(nid, sid, aa2["id"], nar),
            expected_status=200,
        )
        assert d1["status"] == "CONFIRMED" and d2["status"] == "CONFIRMED", (
            "3+7=10 fits under cap 10; both must confirm"
        )


class TestAvailAdvancePeriod:
    def test_claimed_avail_expires_on_period_advance(self, api):
        """PRD §2.8: "Advancing the period rolls every station's
        `monthly_outage_minutes_current_period` back to 0, expires any
        `CLAIMED` avail allocations whose `period_index` is earlier than the
        new period, and recomputes both `Network.posture` and every station's
        `posture`."

        Design: Corner/endpoints/advance_period_expires_claimed_avail
        """
        scenario = setup_basic_scenario()
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        sgo = scenario["sgo_headers"]
        nar = scenario["nar_headers"]
        admin = scenario["admin_headers"]
        program = create_program(nid, avail_minutes_total=20,
                                 avail_minutes_local_allocatable=10,
                                 is_syndicated=False)
        aa = create_avail_allocation(
            nid, sid, program["id"], sgo,
            period_index=0, local_minutes_claimed=5,
        )
        # Advance the period.
        get_success_data(api_client.advance_period(nid, admin))
        aa_after = validate_success(
            api_client.get_avail_allocation(nid, sid, aa["id"], nar),
            expected_status=200,
        )
        assert aa_after["status"] == "EXPIRED", (
            f"CLAIMED avail must expire when its period falls behind; got "
            f"{aa_after['status']!r}"
        )
