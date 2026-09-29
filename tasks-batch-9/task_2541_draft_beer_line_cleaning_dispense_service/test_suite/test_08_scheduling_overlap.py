"""Two contended resources — the venue floor and the crew's day — held apart."""

from test_helpers import (
    AbandonReason,
    ApiErrorId,
    DISPATCH_HEADERS,
    WorkStatus,
    factories,
    fixtures,
    get_success_data,
    validate_error,
)


def _one_floor_three_crews(api):
    """A venue with a 540-660 job on 2026-08-05 and two more crews idle."""
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    venue = fixtures.onboard_venue(api, venue_name="Quarry Street Taproom", lines=())
    first = fixtures.create_technician(api, full_name="Dana Ruiz")
    second = fixtures.create_technician(
        api, full_name="Kem Adeyemi", certification_level="CERTIFIED", caustic_certified=False
    )
    third = fixtures.create_technician(
        api, full_name="Sol Vranken", certification_level="APPRENTICE", caustic_certified=False
    )
    booked = fixtures.book_visit(
        api,
        venue["account"]["id"],
        first["id"],
        scheduled_date="2026-08-05",
        scheduled_start_minute=540,
        scheduled_end_minute=660,
    )
    return venue["account"]["id"], (first, second, third), booked


def _book_on(api, account_id, technician_id, date, start, end):
    return api.create_service_visit(
        factories.service_visit_payload(
            account_id,
            technician_id,
            scheduled_date=date,
            scheduled_start_minute=start,
            scheduled_end_minute=end,
        ),
        DISPATCH_HEADERS,
    )


def test_rescheduling_frees_the_original_minutes_for_a_different_crew(api):
    """PRD §3.3: "On success the original visit advances `SCHEDULED → ABANDONED` with
    `abandon_reason` set to `RESCHEDULED`, and a brand-new visit is minted in `SCHEDULED`
    carrying `rescheduled_from_visit_id` equal to the original visit's `id`, the same
    `account_id` and the same `visit_kind`, and a `technician_id` that defaults to the
    original's when the payload omitted it."
    PRD §3.3: "**Venue slot exclusivity** compares the new slot against every existing visit
    on the *same* account and the *same* `scheduled_date` whose `work_status` is `SCHEDULED`
    or `IN_PROGRESS`; visits already `ABANDONED` or `WORK_COMPLETE` are ignored entirely."

    Design: Difficulty/resource_temporal_overlap/venue_floor_overlap_ignores_abandoned_visits_but_not_the_replacement
    """
    account_id, crews, booked = _one_floor_three_crews(api)

    replacement = get_success_data(
        api.reschedule_visit(
            booked["id"],
            factories.reschedule_payload(
                scheduled_date="2026-08-06", scheduled_start_minute=540, scheduled_end_minute=660
            ),
            DISPATCH_HEADERS,
        ),
        expected_status=201,
    )

    original = fixtures.read_visit(api, booked["id"])
    assert original["work_status"] == WorkStatus.ABANDONED
    assert original["abandon_reason"] == AbandonReason.RESCHEDULED
    assert replacement["rescheduled_from_visit_id"] == booked["id"]
    assert replacement["work_status"] == WorkStatus.SCHEDULED
    assert replacement["scheduled_date"] == "2026-08-06"
    assert replacement["technician_id"] == crews[0]["id"]

    reused = fixtures.book_visit(
        api,
        account_id,
        crews[1]["id"],
        scheduled_date="2026-08-05",
        scheduled_start_minute=540,
        scheduled_end_minute=660,
    )
    assert reused["scheduled_start_minute"] == 540, (
        "the abandoned original no longer holds the floor"
    )


def test_the_replacement_booking_holds_the_freed_floor_against_a_third_crew(api):
    """PRD §3.3: "The new booking is rejected with `ERR_VENUE_SLOT_CONFLICT` when its start
    is at or before the existing visit's end **and** its end is at or after the existing
    visit's start."
    PRD §3.3: "The replacement slot is then re-screened against all five scheduling rules
    exactly as a fresh booking would be: past date, lead limit, access-window containment,
    venue slot exclusivity and technician route feasibility."

    Design: Difficulty/resource_temporal_overlap/venue_floor_overlap_ignores_abandoned_visits_but_not_the_replacement
    """
    account_id, crews, booked = _one_floor_three_crews(api)
    get_success_data(
        api.reschedule_visit(
            booked["id"],
            factories.reschedule_payload(
                scheduled_date="2026-08-06", scheduled_start_minute=540, scheduled_end_minute=660
            ),
            DISPATCH_HEADERS,
        ),
        expected_status=201,
    )
    fixtures.book_visit(
        api,
        account_id,
        crews[1]["id"],
        scheduled_date="2026-08-05",
        scheduled_start_minute=540,
        scheduled_end_minute=660,
    )

    refused = _book_on(api, account_id, crews[2]["id"], "2026-08-05", 600, 700)
    validate_error(refused, ApiErrorId.VENUE_SLOT_CONFLICT, 409)

    later = fixtures.book_visit(
        api,
        account_id,
        crews[2]["id"],
        scheduled_date="2026-08-05",
        scheduled_start_minute=690,
        scheduled_end_minute=780,
    )
    assert later["scheduled_start_minute"] == 690


def _one_crew_two_venues(api):
    """Two venues on opposite sides of town sharing a single crew."""
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    north = fixtures.onboard_venue(api, venue_name="Northgate Bierhaus", lines=())
    south = fixtures.onboard_venue(
        api,
        venue_name="Southgate Bierhaus",
        cleaning_frequency_days=14,
        contracted_line_count=3,
        per_line_rate_cents=3000,
        visit_base_fee_cents=5000,
        lines=(),
    )
    technician = fixtures.create_technician(api, full_name="Dana Ruiz")
    morning = fixtures.book_visit(
        api,
        north["account"]["id"],
        technician["id"],
        scheduled_date="2026-08-05",
        scheduled_start_minute=540,
        scheduled_end_minute=660,
    )
    return north["account"]["id"], south["account"]["id"], technician, morning


def test_a_crews_day_is_contended_even_across_two_different_venues(api):
    """PRD §3.3: "**Technician route feasibility** compares the new slot against every
    existing visit for the *same* `technician_id` on the *same* `scheduled_date`, again only
    those `SCHEDULED` or `IN_PROGRESS`, and adds a half-hour travel allowance to each side."
    PRD §3.3: "The booking is rejected with `ERR_TECHNICIAN_ROUTE_CONFLICT` when the new
    slot's start is strictly earlier than the existing visit's end plus 30 minutes **and**
    the existing visit's start is strictly earlier than the new slot's end plus 30 minutes."

    Design: Difficulty/resource_temporal_overlap/technician_route_conflict_crosses_accounts_but_not_calendar_days
    """
    _north_id, south_id, technician, _morning = _one_crew_two_venues(api)

    refused = _book_on(api, south_id, technician["id"], "2026-08-05", 600, 700)
    validate_error(refused, ApiErrorId.TECHNICIAN_ROUTE_CONFLICT, 409)

    afternoon = fixtures.book_visit(
        api,
        south_id,
        technician["id"],
        scheduled_date="2026-08-05",
        scheduled_start_minute=700,
        scheduled_end_minute=800,
    )
    assert afternoon["account_id"] == south_id, (
        "the second venue's floor was never in contention — only the van's day was"
    )
    assert afternoon["scheduled_start_minute"] == 700


def test_the_same_minutes_on_the_next_calendar_day_are_free(api):
    """PRD §3.3: "Both comparisons here are strict, so a gap of exactly 30 minutes between
    two jobs is accepted while a gap of 29 minutes is rejected — the opposite convention
    from the venue rule, on purpose, because a van needs half an hour to cross town but a
    floor cannot be shared for even a minute."

    Design: Difficulty/resource_temporal_overlap/technician_route_conflict_crosses_accounts_but_not_calendar_days
    """
    _north_id, south_id, technician, morning = _one_crew_two_venues(api)
    validate_error(
        _book_on(api, south_id, technician["id"], "2026-08-05", 600, 700),
        ApiErrorId.TECHNICIAN_ROUTE_CONFLICT,
        409,
    )

    tomorrow = fixtures.book_visit(
        api,
        south_id,
        technician["id"],
        scheduled_date="2026-08-06",
        scheduled_start_minute=600,
        scheduled_end_minute=700,
    )

    assert tomorrow["scheduled_date"] == "2026-08-06"
    assert tomorrow["work_status"] == WorkStatus.SCHEDULED
    assert fixtures.read_visit(api, morning["id"])["work_status"] == WorkStatus.SCHEDULED
