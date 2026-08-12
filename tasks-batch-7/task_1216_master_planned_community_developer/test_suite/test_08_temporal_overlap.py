"""Resource temporal overlap: half-open venue occupation vs aggregate
sales-center capacity."""
from test_helpers import (
    api_client,
    create_active_community,
    create_appointment_payload,
    create_event_payload,
    get_success_data,
    validate_error,
    ApiErrorId,
    TEST_USERS,
)

LIFESTYLE = TEST_USERS["lifestyle_coordinator_headers"]


class TestEventVenueHalfOpenAdjacency:
    """An event starting exactly at another's end_at is NOT an overlap
    (half-open intervals); an interior intersection is."""

    def _setup(self):
        community = create_active_community("Adjacency Alley", 50)
        event_a = get_success_data(
            api_client.create_event(
                create_event_payload(
                    community_id=community["id"], title="Morning Tour",
                    start_at="2026-05-20T10:00:00Z", end_at="2026-05-20T12:00:00Z",
                ),
                LIFESTYLE,
            )
        )
        get_success_data(api_client.schedule_event(event_a["id"], LIFESTYLE))
        event_b = get_success_data(
            api_client.create_event(
                create_event_payload(
                    community_id=community["id"], title="Afternoon Tour",
                    start_at="2026-05-20T12:00:00Z", end_at="2026-05-20T14:00:00Z",
                ),
                LIFESTYLE,
            )
        )
        event_c = get_success_data(
            api_client.create_event(
                create_event_payload(
                    community_id=community["id"], title="Overlapping Mixer",
                    start_at="2026-05-20T11:00:00Z", end_at="2026-05-20T13:00:00Z",
                ),
                LIFESTYLE,
            )
        )
        return event_b["id"], event_c["id"]

    def test_back_to_back_adjacency_allowed(self):
        """PRD §3.8: "Then overlap: no other `SCHEDULED` event may occupy the same venue over a half-open interval overlap with the new event's start-to-end span — back-to-back adjacency is allowed (`ERR_VENUE_OVERLAP`). Finally the fiscal gate for costed events: the charged budget must be `ADOPTED`, and its `EVENTS_PROGRAMMING` line (zero when the line is absent) minus the `cost_cents` of events already `SCHEDULED` or `COMPLETED` against that budget must leave room for this `cost_cents` (`ERR_EVENT_BUDGET_EXCEEDED`); a cost exactly equal to the remaining room passes."

        Design: Difficulty/resource_temporal_overlap/event_venue_half_open_adjacency
        """
        event_b_id, _ = self._setup()
        scheduled = get_success_data(api_client.schedule_event(event_b_id, LIFESTYLE))
        assert scheduled["status"] == "SCHEDULED", (
            f"adjacent (start == other's end) must schedule, got {scheduled['status']}"
        )

    def test_interior_overlap_rejected(self):
        """PRD §3.8: "Then overlap: no other `SCHEDULED` event may occupy the same venue over a half-open interval overlap with the new event's start-to-end span — back-to-back adjacency is allowed (`ERR_VENUE_OVERLAP`). Finally the fiscal gate for costed events: the charged budget must be `ADOPTED`, and its `EVENTS_PROGRAMMING` line (zero when the line is absent) minus the `cost_cents` of events already `SCHEDULED` or `COMPLETED` against that budget must leave room for this `cost_cents` (`ERR_EVENT_BUDGET_EXCEEDED`); a cost exactly equal to the remaining room passes."

        Design: Difficulty/resource_temporal_overlap/event_venue_half_open_adjacency
        """
        _, event_c_id = self._setup()
        resp = api_client.schedule_event(event_c_id, LIFESTYLE)
        validate_error(resp, ApiErrorId.ERR_VENUE_OVERLAP)


class TestSalesCenterAggregateCapacityOverlap:
    """Aggregate capacity semantics: up to 3 overlapping BOOKED tours; the 4th
    fails; completing one frees capacity."""

    def _setup(self):
        community = create_active_community("Tour Terrace", 50)
        appointments = []
        for agent, visitor, start, end in (
            ("Agent A", "V1", "2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z"),
            ("Agent B", "V2", "2026-05-02T10:15:00Z", "2026-05-02T11:15:00Z"),
            ("Agent C", "V3", "2026-05-02T10:30:00Z", "2026-05-02T11:30:00Z"),
        ):
            appointments.append(
                get_success_data(
                    api_client.create_appointment(
                        create_appointment_payload(
                            community_id=community["id"], agent_name=agent,
                            visitor_name=visitor, start_at=start, end_at=end,
                        ),
                        LIFESTYLE,
                    )
                )
            )
        return community, appointments

    def test_third_overlapping_succeeds_fourth_rejected(self):
        """PRD §3.8: "A `LifestyleCoordinator` books a `SalesCenterAppointment` with an `agent_name`, a `visitor_name`, and a `start_at` strictly before `end_at`; at most three `BOOKED` tours may overlap at once, so a fourth overlapping booking is rejected `ERR_TOUR_CAPACITY_REACHED`. Tours are completed or cancelled from `BOOKED`."

        Design: Difficulty/resource_temporal_overlap/sales_center_aggregate_capacity_overlap
        """
        community, appointments = self._setup()
        assert all(a["status"] == "BOOKED" for a in appointments)
        resp = api_client.create_appointment(
            create_appointment_payload(
                community_id=community["id"], agent_name="Agent D", visitor_name="V4",
                start_at="2026-05-02T10:45:00Z", end_at="2026-05-02T11:45:00Z",
            ),
            LIFESTYLE,
        )
        validate_error(resp, ApiErrorId.ERR_TOUR_CAPACITY_REACHED)

    def test_completing_one_frees_capacity(self):
        """PRD §3.8: "A `LifestyleCoordinator` books a `SalesCenterAppointment` with an `agent_name`, a `visitor_name`, and a `start_at` strictly before `end_at`; at most three `BOOKED` tours may overlap at once, so a fourth overlapping booking is rejected `ERR_TOUR_CAPACITY_REACHED`. Tours are completed or cancelled from `BOOKED`. Resident records begin at registration: a `LifestyleCoordinator` registers a `Resident` with a `full_name` and an `email` unique within the community (duplicates are `ERR_VALIDATION`), starting as `PROSPECT`."

        Design: Difficulty/resource_temporal_overlap/sales_center_aggregate_capacity_overlap
        """
        community, appointments = self._setup()
        resp = api_client.create_appointment(
            create_appointment_payload(
                community_id=community["id"], agent_name="Agent D", visitor_name="V4",
                start_at="2026-05-02T10:45:00Z", end_at="2026-05-02T11:45:00Z",
            ),
            LIFESTYLE,
        )
        validate_error(resp, ApiErrorId.ERR_TOUR_CAPACITY_REACHED)
        get_success_data(api_client.complete_appointment(appointments[0]["id"], LIFESTYLE))
        retried = get_success_data(
            api_client.create_appointment(
                create_appointment_payload(
                    community_id=community["id"], agent_name="Agent D", visitor_name="V4",
                    start_at="2026-05-02T10:45:00Z", end_at="2026-05-02T11:45:00Z",
                ),
                LIFESTYLE,
            )
        )
        assert retried["status"] == "BOOKED", (
            f"after one tour completes, the retried booking must succeed, got {retried['status']}"
        )
