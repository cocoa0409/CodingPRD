"""Concurrency guarantees from PRD §2.9.

Each scenario is a race that PRD explicitly names with both a winner
and a named loser error. Each test uses run_race + the PRD-named loser
error_id where stated.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    api_client,
    apply_to_activity,
    apply_to_activity_payload,
    approve_application,
    assert_exactly_one_succeeds,
    create_point_mall_item,
    create_redemption_order,
    create_verified_volunteer,
    file_hour_adjustment,
    get_activity,
    get_volunteer,
    make_organizer_headers,
    make_skilladmin_headers,
    make_volunteer_headers,
    run_race,
    setup_completed_application,
    setup_recruiting_activity,
    validate_error_is_one_of,
    validate_success,
)


class TestQuotaRace:
    """PRD §2.9: 'When two organizers simultaneously try to approve the
    last available position on the same activity, an atomic
    compare-and-increment on Activity.filled_positions admits at most
    Activity.position_quota approvals; the loser receives
    ERR_QUOTA_EXCEEDED.'
    """

    def test_two_simultaneous_approvals_for_last_position(self, api):
        """PRD §2.9: 'an atomic compare-and-increment on
        Activity.filled_positions admits at most Activity.position_quota
        approvals; the loser receives ERR_QUOTA_EXCEEDED.'"""
        organizer, activity, _ = setup_recruiting_activity(position_quota=1)
        v1 = create_verified_volunteer()
        v2 = create_verified_volunteer()
        a1 = apply_to_activity(volunteer=v1, activity=activity)
        a2 = apply_to_activity(volunteer=v2, activity=activity)

        results = run_race(
            lambda: api.approve_application(
                a1["id"], make_organizer_headers(organizer["id"])
            ),
            lambda: api.approve_application(
                a2["id"], make_organizer_headers(organizer["id"])
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        # PRD names the loser error explicitly.
        loser = outcome["failures"][0]
        validate_error_is_one_of(loser, ["ERR_QUOTA_EXCEEDED"])
        # filled_positions converged at 1 (the quota).
        fresh = get_activity(activity["id"])
        assert fresh["filled_positions"] == 1


class TestApproveVsWithdrawRace:
    """PRD §2.9: 'When an organizer's approve and a volunteer's withdraw
    arrive at the same Application simultaneously while it is still
    APPLIED, first-writer-wins on Application.status admits exactly
    one transition; the loser receives ERR_INVALID_STATE.'
    """

    def test_concurrent_approve_and_withdraw(self, api):
        """PRD §2.9: 'first-writer-wins on Application.status admits
        exactly one transition; the loser receives ERR_INVALID_STATE.'"""
        organizer, activity, _ = setup_recruiting_activity(position_quota=2)
        v = create_verified_volunteer()
        application = apply_to_activity(volunteer=v, activity=activity)
        results = run_race(
            lambda: api.approve_application(
                application["id"], make_organizer_headers(organizer["id"])
            ),
            lambda: api.withdraw_application(
                application["id"], make_volunteer_headers(v["id"])
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error_is_one_of(loser, ["ERR_INVALID_STATE"])


class TestInsufficientStockRace:
    """PRD §2.9: 'When two SkillAdmins simultaneously fulfill two
    RedemptionOrder rows for the same PointMallItem and the combined
    quantity exceeds available PointMallItem.stock, the atomic
    compare-and-decrement on PointMallItem.stock allows the first to
    commit and the second's stock check fails with
    ERR_INSUFFICIENT_STOCK.'
    """

    def test_two_fulfillments_combined_exceed_stock(self, api):
        """PRD §2.9: 'the second's stock check fails with
        ERR_INSUFFICIENT_STOCK.'"""
        s1 = setup_completed_application(role_label="LEAD")
        s2 = setup_completed_application(role_label="LEAD")
        item = create_point_mall_item(point_cost=1, stock=1)
        # Two orders for same item, combined quantity exceeds stock=1.
        o1 = create_redemption_order(
            volunteer=s1["volunteer"], item_id=item["id"], quantity=1
        )
        o2 = create_redemption_order(
            volunteer=s2["volunteer"], item_id=item["id"], quantity=1
        )
        results = run_race(
            lambda: api.fulfill_redemption_order(o1["id"], make_skilladmin_headers()),
            lambda: api.fulfill_redemption_order(o2["id"], make_skilladmin_headers()),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error_is_one_of(loser, ["ERR_INSUFFICIENT_STOCK"])


class TestInsufficientPointsRace:
    """PRD §2.9: 'When two RedemptionOrder fulfillments for the same
    volunteer race and the combined total_points would drive
    Volunteer.points_balance below zero, the atomic
    compare-and-decrement on Volunteer.points_balance admits one and
    the loser receives ERR_INSUFFICIENT_POINTS.'
    """

    def test_two_volunteer_fulfillments_combined_exceed_balance(self, api):
        """PRD §2.9: 'the loser receives ERR_INSUFFICIENT_POINTS.'"""
        # Volunteer with 36 points (MEDIUM/LEAD setup).
        scenario = setup_completed_application(role_label="LEAD")
        volunteer = scenario["volunteer"]
        # Two items each costing 30 points (combined 60 > 36).
        item_a = create_point_mall_item(point_cost=30, stock=5)
        item_b = create_point_mall_item(point_cost=30, stock=5)
        o1 = create_redemption_order(
            volunteer=volunteer, item_id=item_a["id"], quantity=1
        )
        # Order creation rechecks balance (PRD §3.7), but at creation
        # time the volunteer has 36 >= 30. Second order is also created
        # with snapshot 30 — at creation time balance still 36 >= 30.
        # The race happens at fulfill time.
        o2 = create_redemption_order(
            volunteer=volunteer, item_id=item_b["id"], quantity=1
        )
        results = run_race(
            lambda: api.fulfill_redemption_order(o1["id"], make_skilladmin_headers()),
            lambda: api.fulfill_redemption_order(o2["id"], make_skilladmin_headers()),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error_is_one_of(loser, ["ERR_INSUFFICIENT_POINTS"])


class TestHourAdjustmentRace:
    """PRD §2.9: 'When two SkillAdmins simultaneously approve and
    reject the same HourAdjustment, first-writer-wins on
    HourAdjustment.status admits one transition and the loser receives
    ERR_INVALID_STATE.'
    """

    def test_concurrent_approve_and_reject(self, api):
        """PRD §2.9: 'first-writer-wins on HourAdjustment.status admits
        one transition and the loser receives ERR_INVALID_STATE.'"""
        scenario = setup_completed_application(role_label="LEAD")
        adj = file_hour_adjustment(
            application=scenario["application"],
            organizer=scenario["organizer"],
            delta_hours=0.50,
        )
        results = run_race(
            lambda: api.approve_hour_adjustment(adj["id"], make_skilladmin_headers()),
            lambda: api.reject_hour_adjustment(adj["id"], make_skilladmin_headers()),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error_is_one_of(loser, ["ERR_INVALID_STATE"])
