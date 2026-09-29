"""Temporal overlap: buffered hearing windows and closed drafter occupancy."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_instant,
    assign_payload,
    create_referral_payload,
    file_drafting_request,
    read_bill,
    read_committee,
    read_drafter,
    read_drafting_request,
    read_referral,
    setup_introduced_bill,
    setup_request_in_research,
    setup_world,
    validate_error,
    validate_success,
)

JUDICIARY = {
    "chamber": "HOUSE",
    "name": "House Judiciary",
    "is_fiscal_committee": True,
    "max_concurrent_referrals": 4,
}


def _three_bills_and_a_booked_committee():
    """Three introduced bills; the first already holds the 14:00-16:00 window."""
    world = setup_world(with_committee=True, committee_overrides=JUDICIARY)
    bills = []
    schedule = [
        ("Jury pool sourcing", "Broaden jury pool sourcing.", "2026-09-02T00:00:00Z", "2026-09-03T00:00:00Z"),
        ("Bail schedule review", "Require periodic bail schedule review.", "2026-09-04T00:00:00Z", "2026-09-05T00:00:00Z"),
        ("Court interpreter standards", "Set court interpreter standards.", "2026-09-06T00:00:00Z", "2026-09-07T00:00:00Z"),
    ]
    for subject, summary, start_utc, end_utc in schedule:
        _request, bill = setup_introduced_bill(
            world,
            affected_sections_count=2,
            requested_sections_count=2,
            subject=subject,
            summary=summary,
            target_code_chapter="Title 16",
            appropriation_requested_cents=0,
            engagement_start_utc=start_utc,
            engagement_end_utc=end_utc,
        )
        bills.append(bill)
    first = validate_success(
        api_client.create_referral(
            bills[0]["id"],
            create_referral_payload(
                world["committee"]["id"],
                hearing_window_start_utc="2026-10-05T14:00:00Z",
                hearing_window_end_utc="2026-10-05T16:00:00Z",
            ),
            world["clerk_headers"],
        ),
        201,
    )
    return world, bills, first


def _refer(world, bill, start_utc, end_utc):
    return api_client.create_referral(
        bill["id"],
        create_referral_payload(
            world["committee"]["id"],
            hearing_window_start_utc=start_utc,
            hearing_window_end_utc=end_utc,
        ),
        world["clerk_headers"],
    )


def test_a_back_to_back_hearing_window_is_refused_by_the_changeover_buffer():
    """PRD: "Before comparing, a thirty-minute changeover buffer is added to the
    end of every existing window belonging to the same committee whose referral
    is still `IN_COMMITTEE`." and "The practical consequence is that a truly
    back-to-back window is refused even though the raw half-open intervals do not
    overlap: against an existing window running from 14:00 to 16:00, a candidate
    starting at 16:00 is refused, while a candidate starting at 16:30 is
    accepted, because the buffered end boundary is itself exclusive."

    Design: Difficulty/resource_temporal_overlap/committee_hearing_windows_are_half_open_but_a_thirty_minute_changeover_buffer_refuses_adjacency
    """
    world, bills, first = _three_bills_and_a_booked_committee()

    refused = _refer(world, bills[1], "2026-10-05T16:00:00Z", "2026-10-05T17:00:00Z")

    validate_error(
        refused, ApiErrorId.ERR_COMMITTEE_HEARING_WINDOW_CONFLICT.value, 409
    )
    held = read_bill(world, bills[1]["id"])
    assert held["legislative_status"] == "INTRODUCED"
    assert held["referral_count"] == 0
    assert read_committee(world, world["committee"]["id"])["active_referral_count"] == 1
    assert_instant(read_referral(world, first["id"])["report_deadline_utc"], "2026-10-12T16:00:00Z")

    accepted = validate_success(
        _refer(world, bills[1], "2026-10-05T16:30:00Z", "2026-10-05T17:30:00Z"), 201
    )
    assert accepted["status"] == "IN_COMMITTEE"
    assert accepted["referral_order"] == 1
    assert_instant(accepted["report_deadline_utc"], "2026-10-12T17:30:00Z")


def test_a_window_ending_exactly_where_an_existing_window_starts_is_admitted():
    """PRD: "Hearing windows themselves are **half-open**: a window covers its
    start instant and every instant up to, but not including, its end." and "The
    candidate conflicts if its start falls strictly before that buffered end
    **and** the existing window's start falls strictly before the candidate's
    end." and "Its `report_deadline_utc` is the earlier of the hearing window's
    end plus seven days and the session's `committee_report_deadline_utc`."

    Design: Difficulty/resource_temporal_overlap/committee_hearing_windows_are_half_open_but_a_thirty_minute_changeover_buffer_refuses_adjacency
    """
    world, bills, _first = _three_bills_and_a_booked_committee()
    validate_success(
        _refer(world, bills[1], "2026-10-05T16:30:00Z", "2026-10-05T17:30:00Z"), 201
    )

    # The candidate ends at the instant the 14:00 window begins, so the second
    # limb of the conflict test is false and the booking stands.
    earlier = validate_success(
        _refer(world, bills[2], "2026-10-05T12:00:00Z", "2026-10-05T14:00:00Z"), 201
    )

    assert earlier["status"] == "IN_COMMITTEE"
    assert_instant(earlier["report_deadline_utc"], "2026-10-12T14:00:00Z")
    assert read_committee(world, world["committee"]["id"])["active_referral_count"] == 3
    assert read_bill(world, bills[1]["id"])["referral_count"] == 1
    assert read_bill(world, bills[2]["id"])["referral_count"] == 1


def _two_occupied_windows_and_a_spare_request():
    """One drafter with a cap of two holds [09-02, 09-10] and [09-10, 09-15]."""
    world = setup_world(
        member_overrides={"priority_slots_total": 3},
        drafter_overrides={"max_concurrent_engagements": 2},
    )
    common = {
        "requested_sections_count": 3,
        "target_code_chapter": "Title 25",
        "confidentiality": "PUBLIC",
        "priority_flag": False,
        "appropriation_requested_cents": 0,
    }
    first = setup_request_in_research(
        world,
        subject="Wetland permit consolidation",
        summary="Consolidate wetland permits.",
        engagement_start_utc="2026-09-02T00:00:00Z",
        engagement_end_utc="2026-09-10T00:00:00Z",
        **common,
    )
    second = setup_request_in_research(
        world,
        subject="Stormwater fee authority",
        summary="Grant stormwater fee authority.",
        engagement_start_utc="2026-09-10T00:00:00Z",
        engagement_end_utc="2026-09-15T00:00:00Z",
        **common,
    )
    third = file_drafting_request(
        world,
        subject="Brownfield cleanup credits",
        summary="Create brownfield cleanup credits.",
        **common,
    )
    return world, first, second, third


def test_a_third_engagement_touching_the_shared_instant_exceeds_the_pointwise_cap():
    """PRD: "Both kinds of interval are **closed at both ends**: two intervals
    that merely touch, where one ends at the very instant the other begins, do
    overlap and both count at that instant." and "A candidate interval is
    admitted only if, at every instant inside it, the number of existing
    occupancy intervals containing that instant plus one does not exceed the
    attorney's `max_concurrent_engagements`; equivalently, the maximum pointwise
    multiplicity of the existing intervals restricted to the candidate must be
    strictly below `max_concurrent_engagements`."

    Design: Difficulty/resource_temporal_overlap/drafter_occupancy_is_closed_at_both_ends_with_aggregate_capacity_two
    """
    world, _first, _second, third = _two_occupied_windows_and_a_spare_request()

    response = api_client.assign_drafting_request(
        third["id"],
        assign_payload(
            world["drafter"]["id"],
            engagement_start_utc="2026-09-10T00:00:00Z",
            engagement_end_utc="2026-09-11T00:00:00Z",
        ),
        world["counsel_headers"],
    )

    validate_error(
        response, ApiErrorId.ERR_DRAFTER_ENGAGEMENT_CAPACITY_EXCEEDED.value, 409
    )
    untouched = read_drafting_request(world, third["id"])
    assert untouched["status"] == "SUBMITTED"
    assert untouched["assigned_drafter_id"] is None
    assert untouched["engagement_start_utc"] is None
    assert untouched["engagement_end_utc"] is None
    assert read_drafter(world)["active_engagement_count"] == 2


def test_shifting_the_candidate_past_the_shared_instant_is_admitted():
    """PRD: "This is an aggregate capacity rather than a pairwise conflict rule:
    with a cap of two, a third simultaneously overlapping engagement is the first
    thing refused, and drafting requests and amendments compete for the same
    slots." and "The `active_engagement_count` on an attorney is simply the
    maintained size of that occupancy set."

    Design: Difficulty/resource_temporal_overlap/drafter_occupancy_is_closed_at_both_ends_with_aggregate_capacity_two
    """
    world, first, second, third = _two_occupied_windows_and_a_spare_request()
    api_client.assign_drafting_request(
        third["id"],
        assign_payload(
            world["drafter"]["id"],
            engagement_start_utc="2026-09-10T00:00:00Z",
            engagement_end_utc="2026-09-11T00:00:00Z",
        ),
        world["counsel_headers"],
    )

    assigned = validate_success(
        api_client.assign_drafting_request(
            third["id"],
            assign_payload(
                world["drafter"]["id"],
                engagement_start_utc="2026-09-11T00:00:00Z",
                engagement_end_utc="2026-09-13T00:00:00Z",
            ),
            world["counsel_headers"],
        ),
        200,
    )

    assert assigned["status"] == "RESEARCH"
    assert assigned["assigned_drafter_id"] == world["drafter"]["id"]
    assert_instant(assigned["engagement_start_utc"], "2026-09-11T00:00:00Z")
    assert_instant(assigned["engagement_end_utc"], "2026-09-13T00:00:00Z")
    # The occupancy set now holds three intervals even though the cap is two,
    # because the cap is pointwise rather than cardinal.
    assert read_drafter(world)["active_engagement_count"] == 3
    assert read_drafting_request(world, first["id"])["status"] == "RESEARCH"
    assert read_drafting_request(world, second["id"])["status"] == "RESEARCH"
