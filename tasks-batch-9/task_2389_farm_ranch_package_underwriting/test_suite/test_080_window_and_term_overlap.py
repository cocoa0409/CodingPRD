"""Two overlap rules with different edge conventions: the inspector's half-open
buffered calendar window and the closed-closed policy term."""

from test_helpers import (
    ADMIN,
    ApiErrorId,
    add_scheduled_item,
    get_success_data,
    open_policy,
    rate_policy,
    rate_policy_ok,
    read_ledger,
    read_policy,
    read_pool,
    read_reservations,
    reservation_by_peril,
    schedule_inspection,
    schedule_inspection_ok,
    setup_rated_dwelling_policy,
    setup_rated_policy_with_inspector,
    validate_error,
)


def test_a_visit_starting_inside_the_travel_buffer_collides(api):
    """"The requested window collides with an existing one when the requested
    start falls strictly before the existing window's buffered end, and the
    requested buffered end falls strictly after the existing window's start."
    The 09:00 visit of two hours runs to 11:00 and buffers to 12:30, so a
    12:00 start is strictly inside the buffer and is refused even though the two
    visits themselves would not overlap.

    Design: Difficulty/resource_temporal_overlap/inspector_half_open_window_with_travel_buffer
    """
    scenario = setup_rated_policy_with_inspector()

    response = schedule_inspection(
        scenario.policy_id,
        scenario.inspector_id,
        inspection_type="LOSS_TRIGGERED",
        scheduled_for="2026-08-16T12:00:00Z",
        duration_minutes=60,
    )

    validate_error(response, ApiErrorId.ERR_INSPECTOR_WINDOW_CONFLICT.value, 409)

    booked = get_success_data(
        api.list_inspections(ADMIN, params={"inspector_id": scenario.inspector_id, "limit": 100})
    )
    assert len(booked) == 1
    assert booked[0]["id"] == scenario.inspection["id"]


def test_a_visit_touching_exactly_at_the_buffer_edge_is_accepted(api):
    """"Touching exactly at a buffer edge is allowed." A 12:30 start is not
    strictly before the 12:30 buffered end of the earlier visit, so the booking
    stands, and the day now carries 180 of the inspector's 480 minutes — "the sum
    of `duration_minutes` across the inspector's `SCHEDULED` inspections whose
    `scheduled_for` falls on the same UTC calendar date as the requested window,
    plus the requested `duration_minutes`, must not exceed the inspector's
    `daily_capacity_minutes`".

    Design: Difficulty/resource_temporal_overlap/inspector_half_open_window_with_travel_buffer
    """
    scenario = setup_rated_policy_with_inspector()

    second = schedule_inspection_ok(
        scenario.policy_id,
        scenario.inspector_id,
        inspection_type="LOSS_TRIGGERED",
        scheduled_for="2026-08-16T12:30:00Z",
        duration_minutes=60,
    )

    assert second["status"] == "SCHEDULED"
    assert second["inspection_type"] == "LOSS_TRIGGERED"
    assert second["duration_minutes"] == 60
    assert second["hazard_score"] == 0
    assert second["recommendation_count"] == 0

    booked = get_success_data(
        api.list_inspections(ADMIN, params={"inspector_id": scenario.inspector_id, "limit": 100})
    )
    assert len(booked) == 2
    assert sum(row["duration_minutes"] for row in booked) == 180
    assert scenario.inspector["daily_capacity_minutes"] == 480


def test_two_terms_sharing_one_boundary_date_overlap(api):
    """"Policy terms are closed-closed date intervals with no buffer, so two
    terms overlap when this policy's `term_start_date` is on or before the
    sibling's `term_end_date` and this policy's `term_end_date` is on or after the
    sibling's `term_start_date`. Terms that merely share a single boundary date
    therefore do overlap and draw `ERR_OVERLAPPING_POLICY_TERM`." A renewal
    starting on 2027-08-31 — the very day the rated sibling expires — is refused,
    and the refusal leaves it without reservations or ledger rows.

    Design: Difficulty/resource_temporal_overlap/policy_term_closed_closed_overlap_on_account
    """
    scenario = setup_rated_dwelling_policy()
    touching = open_policy(
        scenario.agent_headers,
        scenario.account_id,
        term_start_date="2027-08-31",
        term_end_date="2028-08-30",
    )
    add_scheduled_item(scenario.agent_headers, touching["id"])

    response = rate_policy(touching["id"])

    validate_error(response, ApiErrorId.ERR_OVERLAPPING_POLICY_TERM.value, 409)

    still_draft = read_policy(touching["id"])
    assert still_draft["uw_status"] == "DRAFT"
    assert still_draft["exposed_tiv_cents"] == 0
    assert still_draft["total_premium_cents"] == 0
    assert read_reservations(touching["id"]) == []
    assert read_ledger(touching["id"]) == []
    assert read_pool(scenario.hail_pool["id"])["reserved_cents"] == 20_000_000


def test_a_term_starting_the_day_after_expiry_rates_cleanly(api):
    """"No sibling policy on the same `account_id` whose `uw_status` is `RATED`,
    `REFERRED` or `BOUND` may have a term overlapping this one." Shifting the
    renewal to 2027-09-01 clears the expiring term by one day, so it rates on its
    own account alongside the sibling and draws its own reservations from the
    zone's pools.

    Design: Difficulty/resource_temporal_overlap/policy_term_closed_closed_overlap_on_account
    """
    scenario = setup_rated_dwelling_policy()
    renewal = open_policy(
        scenario.agent_headers,
        scenario.account_id,
        term_start_date="2027-09-01",
        term_end_date="2028-08-31",
    )
    add_scheduled_item(scenario.agent_headers, renewal["id"])

    rated = rate_policy_ok(renewal["id"])

    assert rated["uw_status"] == "RATED"
    assert rated["property_premium_cents"] == 144_000
    assert rated["cat_load_cents"] == 125_200
    assert rated["total_premium_cents"] == 269_200

    hail = reservation_by_peril(renewal["id"])["HAIL"]
    assert hail["amount_cents"] == 20_000_000
    assert float(hail["utilization_at_rating"]) == 0.200000
    assert float(hail["scarcity_factor"]) == 1.00
    assert read_pool(scenario.hail_pool["id"])["reserved_cents"] == 40_000_000
