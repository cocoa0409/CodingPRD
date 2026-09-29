"""Two scarce resources contested over time: the hall, which admits exactly one
engagement per buffer-extended interval, and the stagehand local, whose roster is
pooled across every engagement that calls it.
"""

from test_helpers import (
    TEST_USERS,
    api_client,
    book_rental_engagement,
    call_crew,
    read_engagement,
    register_hall,
    register_rental_client,
    register_union_department,
    validate_error,
    validate_paginated,
    validate_success,
)

RENTAL_MANAGER = TEST_USERS["rental_manager_headers"]
TECH_DIRECTOR = TEST_USERS["technical_director_headers"]


def _two_back_to_back_rentals_in_one_hall() -> dict:
    """Two rentals in the same hall, the second loading in at exactly the instant
    the first hall's changeover buffer expires."""
    space = register_hall()
    client = register_rental_client(org_name="Civic Opera Workshop",
                                  contact_email="stage@civicopera.example",
                                  credit_rating="A", is_nonprofit=True,
                                  outstanding_balance_cents=0)
    first = book_rental_engagement(
        space["id"], client["id"],
        title="Civic Opera Workshop: Recital Week",
        load_in_start_utc="2026-09-28T08:00:00Z",
        performance_start_utc="2026-09-29T19:00:00Z",
        performance_end_utc="2026-09-30T00:00:00Z",
        load_out_end_utc="2026-09-30T02:00:00Z",
        performance_day_count=2, load_in_day_count=1)
    second = book_rental_engagement(
        space["id"], client["id"],
        title="Civic Opera Workshop: Mainstage",
        load_in_start_utc="2026-09-30T04:00:00Z",
        performance_start_utc="2026-10-01T19:00:00Z",
        performance_end_utc="2026-10-02T22:00:00Z",
        load_out_end_utc="2026-10-03T02:00:00Z",
        performance_day_count=2, load_in_day_count=1)
    return {"space": space, "client": client, "first": first, "second": second}


def _late_add_payload(space_id: str, client_id: str,
                      load_in_start_utc: str) -> dict:
    return {"engagement_type": "RENTAL", "space_id": space_id,
            "rental_client_id": client_id,
            "title": "Civic Opera Workshop: Late Add",
            "load_in_start_utc": load_in_start_utc,
            "performance_start_utc": "2026-10-03T19:00:00Z",
            "performance_end_utc": "2026-10-03T22:00:00Z",
            "load_out_end_utc": "2026-10-04T02:00:00Z",
            "performance_day_count": 1, "load_in_day_count": 1}


def _one_local_shared_by_two_halls() -> dict:
    """One stagehand local of ten and two same-week rentals in different halls,
    already carrying three calls against that single roster."""
    grand = register_hall()
    studio = register_hall(name="Studio Theatre", seat_capacity=400,
                          base_facility_fee_cents=300_000,
                          load_in_day_fee_cents=120_000,
                          changeover_buffer_minutes=60,
                          rigging_capacity_kg=2_000, house_power_amps=200,
                          dmx_universes=2)
    client = register_rental_client(org_name="Rivertown Arts Festival",
                                  contact_email="prod@rivertown.example",
                                  credit_rating="A", is_nonprofit=True,
                                  outstanding_balance_cents=0)
    department = register_union_department(department="STAGEHANDS",
                                          roster_size=10,
                                          straight_hourly_rate_cents=5_000)
    main_stage = book_rental_engagement(
        grand["id"], client["id"], title="Rivertown Festival: Main Stage")
    studio_stage = book_rental_engagement(
        studio["id"], client["id"], title="Rivertown Festival: Studio Stage")

    morning = call_crew(main_stage["id"], department["id"], crew_size=6,
                        call_start_utc="2026-10-01T08:00:00Z",
                        call_end_utc="2026-10-01T12:00:00Z")
    touching = call_crew(studio_stage["id"], department["id"], crew_size=4,
                         call_start_utc="2026-10-01T12:00:00Z",
                         call_end_utc="2026-10-01T16:00:00Z")
    saturating = call_crew(studio_stage["id"], department["id"], crew_size=4,
                           call_start_utc="2026-10-01T11:00:00Z",
                           call_end_utc="2026-10-01T11:30:00Z")
    return {"department": department, "main_stage": main_stage,
            "studio_stage": studio_stage, "morning": morning,
            "touching": touching, "saturating": saturating}


class TestHallOccupancyWithChangeoverBuffer:

    def test_a_load_in_inside_the_changeover_buffer_collides_with_the_incumbent(self):
        """The late addition loads in an hour after the incumbent's load-out but an
        hour before its changeover buffer expires, and the buffer alone refuses
        it. Moving the same booking to the instant the buffer ends admits it,
        which localises the collision to the buffer window and nothing else.

        PRD: "An engagement occupies its hall over the half-open interval that
        begins at `load_in_start_utc` and ends at `load_out_end_utc` advanced by
        the hall's `changeover_buffer_minutes`; that buffer-extended interval may
        not overlap the same interval of any other engagement on the same hall
        whose `lifecycle_status` is `DRAFT`, `CONFIRMED`, `PERFORMED` or
        `SETTLED`."

        Design: Difficulty/resource_temporal_overlap/performance_space_occupancy_with_changeover_buffer_and_touching_boundary
        """
        scenario = _two_back_to_back_rentals_in_one_hall()
        space_id = scenario["space"]["id"]
        client_id = scenario["client"]["id"]

        validate_error(api_client.create_engagement(
            _late_add_payload(space_id, client_id, "2026-10-03T03:00:00Z"),
            RENTAL_MANAGER), "ERR_SPACE_OCCUPANCY_CONFLICT",
            expected_status=409)

        booked, meta = validate_paginated(api_client.list_engagements(
            RENTAL_MANAGER, {"space_id": space_id}))
        assert meta["total_count"] == 2
        assert {row["id"] for row in booked} == {scenario["first"]["id"],
                                                scenario["second"]["id"]}

        admitted = validate_success(api_client.create_engagement(
            _late_add_payload(space_id, client_id, "2026-10-03T04:00:00Z"),
            RENTAL_MANAGER), expected_status=201)
        assert admitted["lifecycle_status"] == "DRAFT"

    def test_a_draft_engagement_still_holds_the_hall_from_the_buffers_last_instant(self):
        """The second rental was admitted because its load-in fell on the exact
        instant the first hall's buffer expired, so the protected interval is
        half-open at its end. That engagement is still only a draft, yet it holds
        the hall against a colliding booking, and the refusal leaves its own
        derived money untouched.

        PRD: "Only a `CANCELLED` engagement releases its slot."

        Design: Difficulty/resource_temporal_overlap/performance_space_occupancy_with_changeover_buffer_and_touching_boundary
        """
        scenario = _two_back_to_back_rentals_in_one_hall()
        second = scenario["second"]
        assert second["lifecycle_status"] == "DRAFT"
        assert second["load_in_start_utc"] == "2026-09-30T04:00:00Z"
        assert second["facility_fee_cents"] == 960_000
        assert second["deposit_required_cents"] == 240_000

        validate_error(api_client.create_engagement(
            _late_add_payload(scenario["space"]["id"],
                              scenario["client"]["id"],
                              "2026-10-03T03:00:00Z"),
            RENTAL_MANAGER), "ERR_SPACE_OCCUPANCY_CONFLICT")

        still_there = read_engagement(second["id"])
        assert still_there["lifecycle_status"] == "DRAFT"
        assert still_there["facility_fee_cents"] == 960_000
        assert still_there["deposit_required_cents"] == 240_000
        assert still_there["version"] == second["version"]


class TestUnionRosterPooledAcrossEngagements:

    def test_the_roster_is_summed_across_every_overlapping_call_of_the_local(self):
        """The requested call belongs to one engagement while two of the three
        calls it overlaps belong to another in a different hall, and the local can
        supply ten bodies against a demand of nineteen. The refusal persists
        nothing on either engagement.

        PRD: "Because the check is department-scoped and not engagement-scoped, an
        overlapping call on a *different* engagement in a different hall still
        consumes the same local's roster."

        Design: Difficulty/resource_temporal_overlap/union_crew_aggregate_capacity_across_overlapping_calls_on_two_engagements
        """
        scenario = _one_local_shared_by_two_halls()
        department_id = scenario["department"]["id"]

        validate_error(api_client.create_labor_call(
            scenario["main_stage"]["id"],
            {"union_department_id": department_id, "crew_size": 5,
             "call_start_utc": "2026-10-01T11:00:00Z",
             "call_end_utc": "2026-10-01T13:00:00Z"},
            TECH_DIRECTOR), "ERR_CREW_CAPACITY_EXCEEDED", expected_status=409)

        pooled, pooled_meta = validate_paginated(
            api_client.list_department_labor_calls(department_id, TECH_DIRECTOR))
        assert pooled_meta["total_count"] == 3
        assert {row["id"] for row in pooled} == {scenario["morning"]["id"],
                                                scenario["touching"]["id"],
                                                scenario["saturating"]["id"]}

        own_calls, own_meta = validate_paginated(
            api_client.list_engagement_labor_calls(
                scenario["main_stage"]["id"], TECH_DIRECTOR))
        assert own_meta["total_count"] == 1
        assert own_calls[0]["id"] == scenario["morning"]["id"]

    def test_a_touching_call_makes_no_demand_and_the_roster_may_be_filled_exactly(self):
        """The four-hand call that begins at the very instant the six-hand call
        ends is admitted, so touching windows make no joint demand; the second
        four-hand call, which genuinely overlaps the first, is admitted at a
        demand of exactly ten. Both bill the four-hour call minimum, so the two
        engagements carry their own estimates separately.

        PRD: "Touching endpoints do not overlap — a call ending at 18:00 and
        another beginning at 18:00 make no demand on each other — and cancelled or
        reconciled calls do not count."

        Design: Difficulty/resource_temporal_overlap/union_crew_aggregate_capacity_across_overlapping_calls_on_two_engagements
        """
        scenario = _one_local_shared_by_two_halls()
        assert scenario["touching"]["status"] == "ESTIMATED"
        assert scenario["touching"]["estimated_cost_cents"] == 80_000
        assert scenario["saturating"]["status"] == "ESTIMATED"
        assert scenario["saturating"]["estimated_cost_cents"] == 80_000
        assert scenario["morning"]["estimated_cost_cents"] == 120_000

        assert read_engagement(scenario["main_stage"]["id"])[
            "labor_estimate_total_cents"] == 120_000
        assert read_engagement(scenario["studio_stage"]["id"])[
            "labor_estimate_total_cents"] == 160_000

        studio_calls, studio_meta = validate_paginated(
            api_client.list_engagement_labor_calls(
                scenario["studio_stage"]["id"], TECH_DIRECTOR))
        assert studio_meta["total_count"] == 2
