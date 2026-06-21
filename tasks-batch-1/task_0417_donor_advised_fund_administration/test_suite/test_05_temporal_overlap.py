"""Resource temporal-overlap tests: NavPeriod half-open windows (adjacency OK) versus
recurring-grant closed windows (adjacency collides).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    fixtures, factories,
)
from test_helpers.fixtures import (
    SPONSOR_ADMIN, COMPLIANCE, advisor_headers, officer_headers,
)


# ===========================================================================
# Half-open NavPeriod: adjacency does NOT collide, real overlap does
# ===========================================================================
def test_nav_period_adjacent_half_open_accepted(api):
    """PRD 3.1: "Because the interval is half-open, two windows that merely touch at a boundary — where one window's `to_quarter` equals the other's `from_quarter` — do **not** collide."

    Design: Difficulty/resource_temporal_overlap/nav_period_half_open_adjacency_does_not_collide
    """
    sponsor = fixtures.create_sponsor()
    pool = fixtures.create_pool(sponsor["id"], nav_per_unit_cents=2500, fee_bps=50)
    get_success_data(api.create_nav_period(
        factories.create_nav_period_payload(pool["id"], 0, 4, nav_per_unit_cents=2500), SPONSOR_ADMIN))
    adjacent = validate_success(api.create_nav_period(
        factories.create_nav_period_payload(pool["id"], 4, 8, nav_per_unit_cents=2600), SPONSOR_ADMIN),
        expected_status=201)
    assert adjacent["status"] == "ACTIVE"


def test_nav_period_real_overlap_rejected(api):
    """PRD 3.1: "a new window running from `from_quarter` (call it the new start) up to its `to_quarter` (the new end) overlaps an existing `ACTIVE` period only if the existing start is strictly less than the new end **and** the new start is strictly less than the existing end"
    PRD (cont.): "When a genuine overlap with any `ACTIVE` NAV period on the same pool is detected, the create is rejected with `ERR_NAV_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/nav_period_half_open_adjacency_does_not_collide
    """
    sponsor = fixtures.create_sponsor()
    pool = fixtures.create_pool(sponsor["id"], nav_per_unit_cents=2500, fee_bps=50)
    get_success_data(api.create_nav_period(
        factories.create_nav_period_payload(pool["id"], 0, 4, nav_per_unit_cents=2500), SPONSOR_ADMIN))
    # [3,8) overlaps [0,4): 0 < 8 and 3 < 4
    validate_error(api.create_nav_period(
        factories.create_nav_period_payload(pool["id"], 3, 8, nav_per_unit_cents=2700), SPONSOR_ADMIN),
        ApiErrorId.ERR_NAV_PERIOD_OVERLAP.value)


# ===========================================================================
# Closed recurring-grant window: adjacency DOES collide
# ===========================================================================
def test_recurring_grant_closed_adjacency_collides(api):
    """PRD 3.6: "The new window collides with an existing `SCHEDULED` `RECURRING` grant to the same charity from the same account when the existing window's start is at most the new window's end **and** the new window's start is at most the existing window's end — so, because the interval is closed, windows that merely touch at a boundary (for example one ending at quarter 5 and another beginning at quarter 5) **do** collide"
    PRD (cont.): "On such a collision scheduling is rejected with `ERR_RECURRING_GRANT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/recurring_grant_closed_adjacency_collides
    """
    sponsor, charity, account = fixtures.setup_funded_account_with_vetted_charity(
        cash_amount_cents=1000000, advisor_user_id="adv-14")
    # First recurring grant [3,5] scheduled.
    fixtures.create_scheduled_grant(
        account["id"], charity["id"], 100000, "adv-14", officer_user_id="officer-8",
        recurrence="RECURRING", effective_from_quarter=3, effective_to_quarter=5)
    # Second recurring grant [5,7] approved, awaiting schedule.
    grant_b = fixtures.create_approved_grant(
        account["id"], charity["id"], 100000, "adv-14", officer_user_id="officer-8",
        recurrence="RECURRING", effective_from_quarter=5, effective_to_quarter=7)

    validate_error(api.schedule_grant(grant_b["id"], officer_headers("officer-8")),
                   ApiErrorId.ERR_RECURRING_GRANT_OVERLAP.value)
    refreshed = get_success_data(api.get_grant(grant_b["id"], SPONSOR_ADMIN))
    assert refreshed["status"] == "APPROVED"


def test_recurring_grant_overlap_first_schedules_cleanly(api):
    """PRD 3.6: "A `GrantOfficer` schedules an `APPROVED` grant, advancing its `status` to `SCHEDULED`."

    Design: Difficulty/resource_temporal_overlap/recurring_grant_closed_adjacency_collides
    """
    sponsor, charity, account = fixtures.setup_funded_account_with_vetted_charity(
        cash_amount_cents=1000000, advisor_user_id="adv-14b")
    first = fixtures.create_scheduled_grant(
        account["id"], charity["id"], 100000, "adv-14b", officer_user_id="officer-8b",
        recurrence="RECURRING", effective_from_quarter=3, effective_to_quarter=5)
    assert first["status"] == "SCHEDULED"
