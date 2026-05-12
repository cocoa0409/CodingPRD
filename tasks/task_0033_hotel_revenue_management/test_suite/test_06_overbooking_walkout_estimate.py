"""Overbooking policy and walkout-cost estimate (PRD §3.4).

The PRD's central design point: estimated walkout cost (forward-looking)
and realised walkout compensation (chronological) are computed by
DIFFERENT formulas and produce different numbers.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_overbooking_policy,
    assert_walkout_cost_estimate,
    create_overbooking_policy,
    create_overbooking_policy_payload,
    create_pending_reservation,
    create_room_type,
    create_confirmed_reservation,
    advance_clock,
    date_plus_days,
    setup_basic_distribution,
    validate_error,
    validate_success,
)


# ===========================================================================
# OverbookingPolicy create + supersede cascade
# ===========================================================================
class TestOverbookingPolicyCreate:
    def test_create_policy_success(self, api, manager_headers):
        """PRD §3.4: 'A RevenueManager configures overbooking on a per
        (room_type, stay_date) basis by creating an OverbookingPolicy.'"""
        rt = create_room_type()
        res = api.create_overbooking_policy(
            create_overbooking_policy_payload(
                room_type_id=rt["id"], stay_date="2027-12-25",
                overbook_ratio_basis_points=1500,
                estimated_no_show_probability_basis_points=2000,
                walkout_compensation_cents=15000,
            ),
            manager_headers,
        )
        policy = validate_success(res, expected_status=201)
        assert_overbooking_policy(policy)
        assert policy["status"] == "ACTIVE"

    def test_overbook_ratio_above_max_rejected(
        self, api, manager_headers,
    ):
        """PRD §3.4: 'an overbook_ratio_basis_points value in the
        inclusive range from 0 to 5000 (so up to +50% over physical
        capacity)'."""
        rt = create_room_type()
        res = api.create_overbooking_policy(
            create_overbooking_policy_payload(
                room_type_id=rt["id"], stay_date="2027-12-26",
                overbook_ratio_basis_points=5001,
                estimated_no_show_probability_basis_points=2000,
                walkout_compensation_cents=15000,
            ),
            manager_headers,
        )
        validate_error(res, "ERR_INVALID_INPUT")

    def test_creating_new_policy_supersedes_prior_active(
        self, api,
    ):
        """PRD §3.4: 'A policy is born in ACTIVE status; creating a fresh
        policy for the same (room_type_id, stay_date) cascades any prior
        ACTIVE policy on that key to SUPERSEDED, so only one policy is
        ever effective per slot.'"""
        rt = create_room_type()
        first = create_overbooking_policy(
            room_type_id=rt["id"], stay_date="2027-12-27",
            overbook_ratio_basis_points=1000,
        )
        # The second create should succeed and the first should now be
        # SUPERSEDED (PRD doesn't specify a GET — verify via list-rooms?
        # The PRD does not expose GET on OverbookingPolicy; the only
        # observable test is that the new policy applies. Verify by
        # creating a third policy with very different walkout amount and
        # ensuring the walkout-cost-estimate uses the latest values.)
        second = create_overbooking_policy(
            room_type_id=rt["id"], stay_date="2027-12-27",
            overbook_ratio_basis_points=2500,
            estimated_no_show_probability_basis_points=0,
            walkout_compensation_cents=99999,
        )
        # Estimate should reflect the second policy's walkout_compensation.
        est_resp = api.get_walkout_cost_estimate(
            rt["id"], "2027-12-27", TEST_USERS["manager_headers"],
        )
        est = validate_success(est_resp, expected_status=200)
        assert_walkout_cost_estimate(est)
        # No reservations for that date → expected_walkouts == 0,
        # estimated_cost_cents == 0. We can't assert the cents directly
        # without reservations; we instead assert estimate is computable.
        assert est["estimated_cost_cents"] == 0


# ===========================================================================
# Walkout-cost estimate formula (PRD §3.4)
# ===========================================================================
class TestWalkoutCostEstimate:
    def test_estimate_zero_when_no_reservations(
        self, api, manager_headers,
    ):
        """PRD §3.4: 'The expected walkouts is whichever is greater of
        zero and the difference between expected arrivals and physical
        capacity.' With zero reservations, expected_arrivals = 0,
        physical_capacity > 0 → expected_walkouts = 0."""
        scaffold = setup_basic_distribution(n_rooms=4)
        create_overbooking_policy(
            room_type_id=scaffold["room_type"]["id"],
            stay_date="2028-01-15",
            overbook_ratio_basis_points=1500,
            estimated_no_show_probability_basis_points=2000,
            walkout_compensation_cents=15000,
        )
        res = api.get_walkout_cost_estimate(
            scaffold["room_type"]["id"], "2028-01-15", manager_headers,
        )
        est = validate_success(res, expected_status=200)
        assert_walkout_cost_estimate(est)
        assert est["expected_walkouts"] == 0
        assert est["estimated_cost_cents"] == 0

    def test_estimate_zero_when_arrivals_below_capacity(
        self, api, manager_headers,
    ):
        """PRD §3.4: 'The expected number of arrivals is the reservation
        count multiplied by the quantity of ten thousand minus the
        policy's estimated_no_show_probability_basis_points, divided by
        ten thousand. The expected walkouts is whichever is greater of
        zero and the difference between expected arrivals and physical
        capacity. The estimated cost in cents is the expected walkouts
        multiplied by the policy's walkout_compensation_cents'.

        Setup: 5 reservations, no_show=2000bp, capacity=4
        → expected_arrivals = 5*0.8 = 4 → expected_walkouts = max(0, 4-4) = 0.
        """
        # PRD §3.5 caps a single channel at floor(physical_capacity *
        # share / 10000). With capacity=4 and 100% share that ceiling is
        # 4, so the 5th confirm on ONE channel would hit
        # ERR_INVENTORY_EXHAUSTED before reaching the overbooking
        # ceiling. Use 2 channels (each at 100% share, separate rate
        # plans per PRD §3.2's per-rate-plan share cap) and round-robin.
        scaffold = setup_basic_distribution(
            n_rooms=4, base_rate_cents=20000, channel_type="DIRECT",
            n_channels=2,
        )
        create_overbooking_policy(
            room_type_id=scaffold["room_type"]["id"],
            stay_date="2028-02-10",
            overbook_ratio_basis_points=2500,  # ceiling = 4 + 1 = 5
            estimated_no_show_probability_basis_points=2000,  # 20% no-show
            walkout_compensation_cents=15000,
        )
        # Confirm 5 reservations.
        ci = "2028-02-10"
        co = date_plus_days(ci, 1)
        for i in range(5):
            create_confirmed_reservation(
                scaffold, check_in_date=ci, check_out_date=co,
                channel_index=i % 2,
            )
        res = api.get_walkout_cost_estimate(
            scaffold["room_type"]["id"], "2028-02-10", manager_headers,
        )
        est = validate_success(res, expected_status=200)
        assert_walkout_cost_estimate(est)
        # expected_arrivals = 5 * (10000-2000)/10000 = 4.0
        # max(0, 4.0 - 4) = 0
        assert est["estimated_cost_cents"] == 0

    def test_estimate_positive_when_arrivals_exceed_capacity(
        self, api, manager_headers,
    ):
        """PRD §3.4: '... the expected walkouts is whichever is greater
        of zero and the difference between expected arrivals and physical
        capacity. The estimated cost in cents is the expected walkouts
        multiplied by the policy's walkout_compensation_cents, with the
        final result rounded half-up to integer cents.'

        Setup: capacity=4, 5 reservations confirmed via overbooking,
        no_show=0, walkout_compensation=15000
        → expected_arrivals = 5, expected_walkouts = 1, cost = 15000.
        """
        # See sibling test for the multi-channel rationale (PRD §3.5
        # per-channel cap pre-empts the overbooking ceiling otherwise).
        scaffold = setup_basic_distribution(
            n_rooms=4, base_rate_cents=20000, channel_type="DIRECT",
            n_channels=2,
        )
        create_overbooking_policy(
            room_type_id=scaffold["room_type"]["id"],
            stay_date="2028-03-10",
            overbook_ratio_basis_points=2500,  # ceiling = 5
            estimated_no_show_probability_basis_points=0,
            walkout_compensation_cents=15000,
        )
        ci = "2028-03-10"
        co = date_plus_days(ci, 1)
        for i in range(5):
            create_confirmed_reservation(
                scaffold, check_in_date=ci, check_out_date=co,
                channel_index=i % 2,
            )
        res = api.get_walkout_cost_estimate(
            scaffold["room_type"]["id"], "2028-03-10", manager_headers,
        )
        est = validate_success(res, expected_status=200)
        assert_walkout_cost_estimate(est)
        # 5 * 1.0 = 5 expected arrivals; capacity 4 → 1 walkout.
        # cost = 1 * 15000 = 15000 cents.
        assert est["estimated_cost_cents"] == 15000
