"""Contended resources: one member's half-open duty intervals, and one company's
aggregate seat count.
"""

from test_helpers import ApiErrorId, fixtures as fx
from test_helpers import validate_error, validate_success


# ---------------------------------------------------------------------------
# One member, two touching intervals
# ---------------------------------------------------------------------------
def _member_holding_one_tour_with_the_next_day_published(api):
    """A member on the 08-11 tour, with the 08-12 tour published and open."""
    station = fx.create_station(
        api,
        name="Station 56",
        battalion_code="C1",
        minimum_staffing_floor=1,
        fiscal_ot_budget_cents=9_000_000,
        fiscal_period_start_date="2026-08-01",
        fiscal_period_end_date="2026-09-30",
    )
    engine = fx.create_apparatus(
        api,
        station["id"],
        unit_designation="ENGINE-56",
        minimum_crew_size=2,
        required_certifications=[],
        closure_priority=10,
    )
    member = fx.create_firefighter(
        api,
        station["id"],
        full_name="G Guo",
        platoon="C",
        seniority_rank=1,
        kelly_day_cycle_position=1,
        certifications=[],
        hourly_rate_cents=4000,
    )
    first_shift = fx.published_shift(api, station["id"], "2026-08-11", "C")
    first_seat = fx.seat_member(
        api, first_shift["id"], member["id"], engine["id"], member["id"]
    )
    second_shift = fx.published_shift(api, station["id"], "2026-08-12", "D")
    return {
        "station": station,
        "engine": engine,
        "member": member,
        "first_shift": fx.read_shift(api, first_shift["id"]),
        "second_shift": second_shift,
        "first_seat": first_seat,
    }


class TestHalfOpenAdjacentTours:
    """A tour ending at 08:00 and a tour starting at 08:00 do not overlap."""

    def test_back_to_back_tours_are_both_permitted(self, api):
        """Adjacent intervals touching at the shared instant are accepted.

        PRD 3.3: "Then **double booking**: the member must hold no other
        `SCHEDULED` seat whose half-open interval overlaps this one, else
        `ERR_DOUBLE_BOOKED_SHIFT`; because the intervals are half-open, a seat
        ending at 08:00 and a seat starting at 08:00 do not overlap and are both
        permitted."

        Design: Difficulty/resource_temporal_overlap/firefighter_half_open_adjacent_tours_allowed_overlap_rejected
        """
        world = _member_holding_one_tour_with_the_next_day_published(api)

        adjacent = validate_success(
            api.create_shift_assignment(
                {
                    "duty_shift_id": world["second_shift"]["id"],
                    "firefighter_id": world["member"]["id"],
                    "apparatus_id": world["engine"]["id"],
                    "assignment_type": "CALLBACK",
                    "seat_certification": "NONE",
                    "scheduled_hours": 24,
                    "expected_duty_shift_version": world["second_shift"]["version"],
                },
                fx.make_company_officer_headers(world["member"]["id"]),
            ),
            201,
        )

        assert adjacent["status"] == "SCHEDULED"
        assert adjacent["scheduled_hours"] == 24

        # Two consecutive tours merge into a single forty-eight-hour block, which
        # does not exceed the forty-eight-hour ceiling.
        period = fx.work_period_of(api, world["member"]["id"])
        assert period["scheduled_hours"] == 48

    def test_a_twelve_hour_seat_inside_the_existing_tour_is_double_booked(self, api):
        """A genuinely overlapping interval reports double booking, not fatigue.

        PRD 2.6: "12. **Rest-period ceiling** — `ERR_REST_PERIOD_VIOLATION`
        (422). It runs after the overlap check because merging intervals into a
        continuous tour is only meaningful once they are known not to overlap."

        Design: Difficulty/resource_temporal_overlap/firefighter_half_open_adjacent_tours_allowed_overlap_rejected
        """
        world = _member_holding_one_tour_with_the_next_day_published(api)
        fx.seat_member(
            api,
            world["second_shift"]["id"],
            world["member"]["id"],
            world["engine"]["id"],
            world["member"]["id"],
            assignment_type="CALLBACK",
        )
        before = fx.read_shift(api, world["first_shift"]["id"])

        response = api.create_shift_assignment(
            {
                "duty_shift_id": world["first_shift"]["id"],
                "firefighter_id": world["member"]["id"],
                "apparatus_id": world["engine"]["id"],
                "assignment_type": "CALLBACK",
                "seat_certification": "NONE",
                "scheduled_hours": 12,
                "expected_duty_shift_version": before["version"],
            },
            fx.make_company_officer_headers(world["member"]["id"]),
        )

        error = validate_error(response, ApiErrorId.DOUBLE_BOOKED_SHIFT.value, 422)
        assert error["error_id"] != ApiErrorId.REST_PERIOD_VIOLATION.value

        seats = fx.list_assignments(api, firefighter_id=world["member"]["id"])
        assert len(seats) == 2

        after = fx.read_shift(api, world["first_shift"]["id"])
        assert after["assigned_headcount"] == 1
        assert after["version"] == before["version"]


# ---------------------------------------------------------------------------
# One company, an aggregate seat count
# ---------------------------------------------------------------------------
def _one_seat_company_already_carrying_its_extra_rider(api):
    """A minimum-crew-one company holding two riders, its ceiling."""
    station = fx.create_station(
        api,
        name="Station 57",
        battalion_code="C1",
        minimum_staffing_floor=1,
        fiscal_ot_budget_cents=9_000_000,
        fiscal_period_start_date="2026-08-01",
        fiscal_period_end_date="2026-09-30",
    )
    engine = fx.create_apparatus(
        api,
        station["id"],
        unit_designation="ENGINE-57",
        minimum_crew_size=1,
        required_certifications=[],
        closure_priority=10,
    )
    riders = [
        fx.create_firefighter(
            api,
            station["id"],
            full_name=name,
            platoon="C",
            seniority_rank=rank,
            kelly_day_cycle_position=kelly,
            certifications=[],
            hourly_rate_cents=4000,
        )
        for name, rank, kelly in (
            ("H Hoang", 1, 1),
            ("I Ives", 2, 2),
            ("J Joshi", 3, 4),
        )
    ]
    shift = fx.published_shift(api, station["id"], "2026-08-11", "C")
    first_seat = fx.seat_member(
        api, shift["id"], riders[0]["id"], engine["id"], riders[0]["id"]
    )
    second_seat = fx.seat_member(
        api,
        shift["id"],
        riders[1]["id"],
        engine["id"],
        riders[0]["id"],
        assignment_type="OVERTIME",
    )
    return {
        "station": station,
        "engine": engine,
        "riders": riders,
        "shift": fx.read_shift(api, shift["id"]),
        "seats": [first_seat, second_seat],
    }


class TestCompanySeatCapacity:
    """The ceiling is an aggregate count on the vehicle, not a pairwise clash."""

    def test_third_rider_on_a_one_body_company_is_refused(self, api):
        """A company carries one rider above its minimum crew and no more.

        PRD 3.3: "Count the `SCHEDULED` assignments already on that company for
        that shift; if adding one more would put the total above
        `minimum_crew_size` plus one, the request is refused with
        `ERR_APPARATUS_SEAT_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/apparatus_aggregate_seat_capacity_rejects_third_rider_on_two_seat_company
        """
        world = _one_seat_company_already_carrying_its_extra_rider(api)

        response = api.create_shift_assignment(
            {
                "duty_shift_id": world["shift"]["id"],
                "firefighter_id": world["riders"][2]["id"],
                "apparatus_id": world["engine"]["id"],
                "assignment_type": "OVERTIME",
                "seat_certification": "NONE",
                "scheduled_hours": 24,
                "expected_duty_shift_version": world["shift"]["version"],
            },
            fx.make_company_officer_headers(world["riders"][0]["id"]),
        )

        error = validate_error(
            response, ApiErrorId.APPARATUS_SEAT_CAPACITY_EXCEEDED.value, 422
        )
        # The third rider holds no seat of their own, so nothing double-books.
        assert error["error_id"] != ApiErrorId.DOUBLE_BOOKED_SHIFT.value

    def test_the_refused_rider_is_charged_nothing_and_the_company_keeps_two_seats(
        self, api
    ):
        """The collective breach leaves the company and the newcomer untouched.

        PRD 3.3: "Then **seat capacity**, an aggregate constraint in which each
        individual seat request is perfectly valid and only the collective
        breaches the ceiling."

        Design: Difficulty/resource_temporal_overlap/apparatus_aggregate_seat_capacity_rejects_third_rider_on_two_seat_company
        """
        world = _one_seat_company_already_carrying_its_extra_rider(api)

        api.create_shift_assignment(
            {
                "duty_shift_id": world["shift"]["id"],
                "firefighter_id": world["riders"][2]["id"],
                "apparatus_id": world["engine"]["id"],
                "assignment_type": "OVERTIME",
                "seat_certification": "NONE",
                "scheduled_hours": 24,
                "expected_duty_shift_version": world["shift"]["version"],
            },
            fx.make_company_officer_headers(world["riders"][0]["id"]),
        )

        seated = fx.list_assignments(
            api,
            duty_shift_id=world["shift"]["id"],
            apparatus_id=world["engine"]["id"],
            status="SCHEDULED",
        )
        assert len(seated) == 2
        assert {seat["id"] for seat in seated} == {
            world["seats"][0]["id"],
            world["seats"][1]["id"],
        }

        shift = fx.read_shift(api, world["shift"]["id"])
        assert shift["assigned_headcount"] == 2
        assert shift["version"] == world["shift"]["version"]

        newcomer_period = fx.work_period_of(api, world["riders"][2]["id"])
        assert newcomer_period["scheduled_hours"] == 0
