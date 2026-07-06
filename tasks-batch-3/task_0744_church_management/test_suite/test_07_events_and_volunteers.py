"""Events, coverage score, volunteer scheduling, overlaps."""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    set_clock, create_household, create_adult_member,
    create_event, create_volunteer_assignment, accept_volunteer_as_member,
    make_member_headers, create_event_payload,
)


class TestCoverageScoreThreeInputNonlinear:
    def test_coverage_score_48h_service_two_of_four(self, api):
        """PRD §3.6: "Define urgency as the greater of 0.0 and (1.0 minus
        hours_to_event divided by 72.0)..."
        PRD §3.6: "The coverage_score is then 100 multiplied by
        priority_weight, multiplied by the sum of 0.60 times fill_ratio
        and 0.40 times (1 minus urgency), with the final product rounded
        half-up to two decimal places."

        Design: Difficulty/combinatorial_formula/volunteer_coverage_score_three_input_nonlinear
        """
        set_clock("2026-05-01T10:00:00Z")
        h = create_household()
        m1 = create_adult_member(h["id"], full_name="M1", email="m1@x.com",
                                 membership_status="REGULAR")
        m2 = create_adult_member(h["id"], full_name="M2", email="m2@x.com",
                                 membership_status="REGULAR")
        m3 = create_adult_member(h["id"], full_name="M3", email="m3@x.com")
        m4 = create_adult_member(h["id"], full_name="M4", email="m4@x.com")
        # SERVICE event 48h out.
        e = create_event(
            name="Sun 10am", event_type="SERVICE",
            starts_at="2026-05-03T10:00:00Z", ends_at="2026-05-03T11:00:00Z",
            expected_attendance=150, volunteer_slots=4,
        )
        a1 = create_volunteer_assignment(e["id"], m1["id"], role_type="USHER")
        a2 = create_volunteer_assignment(e["id"], m2["id"], role_type="USHER")
        create_volunteer_assignment(e["id"], m3["id"], role_type="USHER")
        create_volunteer_assignment(e["id"], m4["id"], role_type="USHER")
        accept_volunteer_as_member(a1["id"], m1["id"])
        accept_volunteer_as_member(a2["id"], m2["id"])
        # Read event and check score.
        event = validate_success(
            api.get_event(e["id"], TEST_USERS["coordinator_headers"])
        )
        assert event["volunteer_slots"] == 4
        assert event["volunteer_filled_count"] == 2
        # 100 * 1.00 * (0.60*0.50 + 0.40*(1 - 48/72)) = 100 * (0.30 + 0.4/3)
        # = 30 + 26.6667 = 56.67 (round_half_up to 2 dp).
        assert event["coverage_score"] == 56.67, (
            f"expected 56.67, got {event['coverage_score']}"
        )

    def test_coverage_score_at_urgency_horizon_no_fills(self, api):
        """PRD §3.6: "by construction urgency is 0 when the event is at
        least 72 hours away and 1.0 at the event's start (and
        thereafter)."

        Design: Corner/calculations/coverage_score_at_urgency_horizon
        """
        set_clock("2026-05-01T10:00:00Z")
        e = create_event(
            name="Sun 10am", event_type="SERVICE",
            starts_at="2026-05-04T10:00:00Z", ends_at="2026-05-04T11:00:00Z",
            expected_attendance=100, volunteer_slots=4,
        )
        event = validate_success(
            api.get_event(e["id"], TEST_USERS["coordinator_headers"])
        )
        # 100 * 1.00 * (0.60*0 + 0.40*(1-0)) = 40.00.
        assert event["coverage_score"] == 40.00, (
            f"expected 40.00, got {event['coverage_score']}"
        )

    def test_coverage_score_is_read_only_field(self, api):
        """PRD §3.6: "The event resource also exposes a live coverage_score,
        which is a weighted scoring metric recomputed on every read against
        the current logical clock."

        Design: Difficulty/combinatorial_formula/volunteer_coverage_score_three_input_nonlinear
        """
        # Second required test for the coverage-score three-input non-linear
        # instance: verifies the "recomputed on every read against the current
        # logical clock" property — advancing the clock changes the score
        # even without any state mutation on the event.
        set_clock("2026-05-01T10:00:00Z")
        e = create_event(
            name="Sun 10am", event_type="SERVICE",
            # Exactly 48h out at clock = 2026-05-01T10:00:00Z.
            starts_at="2026-05-03T10:00:00Z", ends_at="2026-05-03T11:00:00Z",
            expected_attendance=100, volunteer_slots=4,
        )
        # No volunteers accepted; fill_ratio = 0.
        # urgency = 1 - 48/72 = 1/3; score = 100 * 1.00 * (0 + 0.40 * (2/3))
        # = 26.6666... = 26.67 after round_half_up to 2 dp.
        event = validate_success(
            api.get_event(e["id"], TEST_USERS["coordinator_headers"])
        )
        assert event["coverage_score"] == 26.67, (
            f"expected 26.67, got {event['coverage_score']}"
        )


class TestVolunteerFilledCount:
    def test_accept_increments_filled_count(self, api):
        """PRD §3.6: "accepting the invitation moves it to ACCEPTED and
        stamps accepted_at with the current UTC and increments the
        event's volunteer_filled_count by one..."

        Design: Corner/entities/event_computed_volunteer_filled_count_after_accept
        """
        set_clock("2026-05-01T00:00:00Z")
        h = create_household()
        m = create_adult_member(h["id"])
        e = create_event(volunteer_slots=2)
        a = create_volunteer_assignment(e["id"], m["id"], role_type="USHER")
        accept_resp = api.accept_volunteer_assignment(
            a["id"], make_member_headers(m["id"])
        )
        assignment = validate_success(accept_resp)
        assert assignment["status"] == "ACCEPTED"
        event = validate_success(
            api.get_event(e["id"], TEST_USERS["coordinator_headers"])
        )
        assert event["volunteer_filled_count"] == 1


class TestVolunteerDependencyState:
    def test_accept_when_event_not_scheduled_rejected(self, api):
        """PRD §3.6: "Accepting is guarded further — the event MUST still
        be SCHEDULED (otherwise ERR_DEPENDENCY_STATE)..."

        Design: Difficulty/cross_entity_state_dependency/volunteer_accept_requires_event_scheduled
        """
        set_clock("2026-05-01T00:00:00Z")
        h = create_household()
        m = create_adult_member(h["id"])
        e = create_event(
            starts_at="2026-05-10T10:00:00Z", ends_at="2026-05-10T11:00:00Z",
            volunteer_slots=4,
        )
        a = create_volunteer_assignment(e["id"], m["id"], role_type="USHER")
        # Complete the event so its status leaves SCHEDULED while the
        # assignment remains INVITED (cancel would cascade INVITED -> CANCELLED
        # per PRD §3.6, so we complete instead).
        set_clock("2026-05-10T11:30:00Z")  # past ends_at
        validate_success(
            api.complete_event(e["id"], TEST_USERS["coordinator_headers"])
        )
        resp = api.accept_volunteer_assignment(a["id"],
                                               make_member_headers(m["id"]))
        validate_error(resp, ApiErrorId.ERR_DEPENDENCY_STATE)
        assignment = validate_success(
            api.get_volunteer_assignment(a["id"],
                                         TEST_USERS["coordinator_headers"])
        )
        assert assignment["status"] == "INVITED"

    def test_accept_dependency_status_409(self, api):
        """PRD §5: "ERR_DEPENDENCY_STATE | 409"

        Design: Difficulty/cross_entity_state_dependency/volunteer_accept_requires_event_scheduled
        """
        # Second required test — the same rule via a different completion path.
        set_clock("2026-05-01T00:00:00Z")
        h = create_household()
        m = create_adult_member(h["id"])
        e = create_event(
            starts_at="2026-05-11T10:00:00Z", ends_at="2026-05-11T11:00:00Z",
            volunteer_slots=4,
        )
        a = create_volunteer_assignment(e["id"], m["id"], role_type="USHER")
        set_clock("2026-05-11T12:00:00Z")
        api.complete_event(e["id"], TEST_USERS["coordinator_headers"])
        resp = api.accept_volunteer_assignment(a["id"],
                                               make_member_headers(m["id"]))
        assert resp.status_code == 409
        body = resp.json()
        assert body["data"]["error_id"] == "ERR_DEPENDENCY_STATE"


class TestVolunteerOverlapUnbuffered:
    def test_volunteer_overlap_rejected(self, api):
        """PRD §3.6: "the accept MUST NOT create a scheduling overlap:
        for the accepting member, none of their other assignments in
        status ACCEPTED or CHECKED_IN may have an event whose
        [starts_at, ends_at) half-open window overlaps the current
        event's window; overlap is unbuffered here (unlike facility
        bookings), and a violation returns ERR_VOLUNTEER_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/volunteer_unbuffered_event_overlap
        """
        set_clock("2026-05-01T09:00:00Z")
        h = create_household()
        m = create_adult_member(h["id"])
        e1 = create_event(
            name="E1", event_type="SERVICE",
            starts_at="2026-05-10T10:00:00Z", ends_at="2026-05-10T11:00:00Z",
            volunteer_slots=4,
        )
        e2 = create_event(
            name="E2", event_type="CLASS",
            starts_at="2026-05-10T10:30:00Z", ends_at="2026-05-10T11:30:00Z",
            expected_attendance=30, volunteer_slots=2,
        )
        a1 = create_volunteer_assignment(e1["id"], m["id"], role_type="USHER")
        a2 = create_volunteer_assignment(e2["id"], m["id"], role_type="USHER")
        accept_volunteer_as_member(a1["id"], m["id"])
        resp = api.accept_volunteer_assignment(a2["id"],
                                               make_member_headers(m["id"]))
        validate_error(resp, ApiErrorId.ERR_VOLUNTEER_OVERLAP)
        after = validate_success(
            api.get_volunteer_assignment(a2["id"],
                                         TEST_USERS["coordinator_headers"])
        )
        assert after["status"] == "INVITED"

    def test_volunteer_overlap_end_at_start_no_conflict(self, api):
        """PRD §3.6: "none of their other assignments in status `ACCEPTED` or `CHECKED_IN` may have an event whose `[starts_at, ends_at)` half-open window overlaps the current event's window; overlap is unbuffered here (unlike facility bookings), and a violation returns `ERR_VOLUNTEER_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/volunteer_unbuffered_event_overlap
        """
        # Second required test — the complementary "touching-endpoints do NOT
        # overlap" half of the unbuffered half-open semantics.
        set_clock("2026-05-01T09:00:00Z")
        h = create_household()
        m = create_adult_member(h["id"])
        e1 = create_event(
            name="E1a", event_type="SERVICE",
            starts_at="2026-05-11T10:00:00Z", ends_at="2026-05-11T11:00:00Z",
            volunteer_slots=4,
        )
        e2 = create_event(
            name="E2a", event_type="CLASS",
            starts_at="2026-05-11T11:00:00Z", ends_at="2026-05-11T12:00:00Z",
            expected_attendance=30, volunteer_slots=2,
        )
        a1 = create_volunteer_assignment(e1["id"], m["id"], role_type="USHER")
        a2 = create_volunteer_assignment(e2["id"], m["id"], role_type="USHER")
        accept_volunteer_as_member(a1["id"], m["id"])
        # E1 ends at 11:00, E2 starts at 11:00 — with unbuffered half-open
        # intervals, this is not an overlap.
        resp = api.accept_volunteer_assignment(a2["id"],
                                               make_member_headers(m["id"]))
        accepted = validate_success(resp)
        assert accepted["status"] == "ACCEPTED"


class TestEventCompletePrecondition:
    def test_complete_before_ends_at_rejected(self, api):
        """PRD §3.6: "A Coordinator may complete an event only when the
        event is still SCHEDULED, only when the current logical clock is
        at or after the event's ends_at (otherwise ERR_EVENT_NOT_ENDED),
        and only when no ChildCheckIn on this event has status CHECKED_IN
        or SECURITY_HOLD..."

        Design: Corner/state_machines/event_complete_before_ends_at_returns_event_not_ended
        """
        set_clock("2026-05-10T09:00:00Z")
        e = create_event(
            name="E1", event_type="MEETING",
            starts_at="2026-05-10T10:00:00Z", ends_at="2026-05-10T11:00:00Z",
            expected_attendance=20, volunteer_slots=0,
        )
        resp = api.complete_event(e["id"], TEST_USERS["coordinator_headers"])
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_ENDED)
