"""Completion events: publish/unpublish cycle, terminal lockdown, the budget
ledger, fiscal-vs-temporal precedence, and the venue buffer
(PRD §2.9, §3.1, §3.7)."""
from test_helpers import (
    ApiErrorId,
    add_senior,
    assert_budget_invariants,
    coord,
    create_event,
    get_campaign,
    get_event,
    grant_consent,
    publish_event,
    register_senior,
    set_clock,
    setup_campaign_with_school,
    complete_running_event,
    validate_error,
    validate_success,
)


class TestPublishUnpublishCycle:
    def _setup(self, api):
        campaign, school = setup_campaign_with_school(
            campaign_overrides={"total_budget_cents": 100_000}
        )
        senior = add_senior(school)
        grant_consent(school, senior["id"], ["OUTREACH"])
        event = create_event(
            school,
            title="FAFSA Night",
            start_time="2026-09-10T15:00:00Z",
            end_time="2026-09-10T18:00:00Z",
            capacity=5,
            cost_estimate_cents=20_000,
        )
        return campaign, school, senior, event

    def test_unpublish_releases_budget_and_cancels_registrations(self, api):
        """PRD §3.7: "Unpublishing returns a `PUBLISHED` event to `DRAFT`
        (`ERR_EVENT_NOT_PUBLISHED` otherwise): the budget commitment is
        released and the campaign's `version` increments again, all
        `REGISTERED` registrations are cancelled, and staff assignments are
        left unchanged."

        Design: Difficulty/non_linear_state_machine/event_draft_publish_unpublish_cycle
        """
        campaign, school, senior, event = self._setup(api)
        resp = api.publish_event(event["id"], coord(school))
        assert validate_success(resp, 200)["status"] == "PUBLISHED"
        assert get_campaign(campaign["id"])["committed_budget_cents"] == 20_000

        registration = register_senior(school, event["id"], senior["id"])
        assert registration["status"] == "REGISTERED"

        resp = api.unpublish_event(event["id"], coord(school))
        assert validate_success(resp, 200)["status"] == "DRAFT"
        campaign = get_campaign(campaign["id"])
        assert campaign["committed_budget_cents"] == 0, (
            "unpublishing must release the budget commitment"
        )
        assert_budget_invariants(campaign)
        resp = api.get_event_registration(registration["id"], coord(school))
        assert validate_success(resp, 200)["status"] == "CANCELLED"

    def test_republish_recommits_but_never_restores_registrations(self, api):
        """PRD §3.7: "On success, the campaign's `committed_budget_cents` rises
        by the estimate, and the campaign's `version` increments."
        PRD §3.6: "Cancelled event registrations, however, are not restored —
        a family that was signed up must be registered again."

        Design: Difficulty/non_linear_state_machine/event_draft_publish_unpublish_cycle
        """
        campaign, school, senior, event = self._setup(api)
        publish_event(school, event["id"])
        registration = register_senior(school, event["id"], senior["id"])
        api.unpublish_event(event["id"], coord(school))

        resp = api.publish_event(event["id"], coord(school))
        assert validate_success(resp, 200)["status"] == "PUBLISHED", (
            "DRAFT -> PUBLISHED -> DRAFT -> PUBLISHED: the cycle is legal"
        )
        assert get_campaign(campaign["id"])["committed_budget_cents"] == 20_000
        resp = api.get_event_registration(registration["id"], coord(school))
        assert validate_success(resp, 200)["status"] == "CANCELLED", (
            "re-publish must not resurrect the cancelled registration"
        )


class TestEventInvalidTransitions:
    def test_window_publish_and_cancel_invalid_from_rejections(self, api):
        """PRD §3.7: "a half-open window from `start_time` to `end_time`" —
        "the end must be strictly after the start, else
        `ERR_EVENT_WINDOW_INVALID`".
        PRD §3.7: "the event is `DRAFT` (`ERR_EVENT_NOT_DRAFT`)" for publish.
        PRD §3.7: "Cancelling is allowed from `DRAFT` or `PUBLISHED` (anything
        else is `ERR_EVENT_NOT_CANCELLABLE`)".

        Design: Corner/state_machines/event_invalid_transitions_and_terminal_lockdown
        """
        _campaign, school = setup_campaign_with_school()
        ev1 = create_event(school, title="E1")
        ev2 = create_event(
            school,
            title="E2",
            start_time="2026-09-12T10:00:00Z",
            end_time="2026-09-12T12:00:00Z",
        )
        publish_event(school, ev1["id"])
        complete_running_event(school, ev1["id"], 900, "2026-09-10T11:00:00Z")
        api.cancel_event(ev2["id"], coord(school))

        # end_time <= start_time at creation.
        resp = api.create_event(
            {
                "school_id": school["id"],
                "title": "BAD",
                "start_time": "2027-09-10T12:00:00Z",
                "end_time": "2027-09-10T10:00:00Z",
                "capacity": 10,
                "cost_estimate_cents": 1000,
                "required_expert_count": 0,
                "supported_languages": [],
            },
            coord(school),
        )
        validate_error(resp, ApiErrorId.ERR_EVENT_WINDOW_INVALID)

        # Publish a CANCELLED event.
        resp = api.publish_event(ev2["id"], coord(school))
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_DRAFT)

        # Cancel a COMPLETED (terminal) event.
        resp = api.cancel_event(ev1["id"], coord(school))
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_CANCELLABLE)


class TestBudgetLedger:
    def test_publishes_accumulate_commitments(self, api):
        """PRD §3.1: "A campaign exposes three computed budget readings at all
        times: `committed_budget_cents`, the sum of `cost_estimate_cents` over
        its events currently `PUBLISHED` or `IN_PROGRESS`; `spent_budget_cents`,
        the sum of `actual_cost_cents` over its `COMPLETED` events; and
        `budget_balance_cents`, the remainder of `total_budget_cents` after
        subtracting committed and spent."

        Design: Difficulty/compensating_invariant/budget_commit_cancel_roundtrip
        """
        campaign, school = setup_campaign_with_school(
            campaign_overrides={"total_budget_cents": 100_000}
        )
        ev1 = create_event(school, title="E1", cost_estimate_cents=30_000)
        ev2 = create_event(
            school,
            title="E2",
            start_time="2026-09-11T10:00:00Z",
            end_time="2026-09-11T12:00:00Z",
            cost_estimate_cents=15_000,
        )
        publish_event(school, ev1["id"])
        publish_event(school, ev2["id"])

        campaign = get_campaign(campaign["id"])
        assert campaign["committed_budget_cents"] == 45_000
        assert campaign["budget_balance_cents"] == 55_000
        assert_budget_invariants(campaign)

    def test_publish_then_cancel_returns_balance_exactly(self, api):
        """PRD §3.7: "the publish-then-cancel round trip returns
        `budget_balance_cents` to its exact pre-publish value."

        Design: Difficulty/compensating_invariant/budget_commit_cancel_roundtrip
        """
        campaign, school = setup_campaign_with_school(
            campaign_overrides={"total_budget_cents": 100_000}
        )
        ev1 = create_event(school, title="E1", cost_estimate_cents=30_000)
        ev2 = create_event(
            school,
            title="E2",
            start_time="2026-09-11T10:00:00Z",
            end_time="2026-09-11T12:00:00Z",
            cost_estimate_cents=15_000,
        )
        publish_event(school, ev1["id"])
        publish_event(school, ev2["id"])

        api.cancel_event(ev1["id"], coord(school))

        campaign = get_campaign(campaign["id"])
        assert campaign["committed_budget_cents"] == 15_000, (
            "cancelling E1 must release exactly its 30000 commitment, leaving "
            "E2's 15000 untouched"
        )
        assert campaign["budget_balance_cents"] == 85_000
        assert_budget_invariants(campaign)

    def test_completion_moves_estimate_from_committed_to_spent(self, api):
        """PRD §3.7: "On success the ledger shifts — `committed_budget_cents`
        falls by the estimate while `spent_budget_cents` rises by the actual".

        Design: Corner/complexity_layers/actual_cost_reconciles_budget_on_complete
        """
        campaign, school = setup_campaign_with_school(
            campaign_overrides={"total_budget_cents": 50_000}
        )
        event = create_event(school, title="E1", cost_estimate_cents=30_000)
        publish_event(school, event["id"])

        campaign = get_campaign(campaign["id"])
        assert campaign["committed_budget_cents"] == 30_000
        assert campaign["budget_balance_cents"] == 20_000

        complete_running_event(school, event["id"], 28_500, "2026-09-10T11:00:00Z")

        campaign = get_campaign(campaign["id"])
        assert campaign["committed_budget_cents"] == 0
        assert campaign["spent_budget_cents"] == 28_500, (
            "the ledger books the ACTUAL cost, not the 30000 estimate"
        )
        assert campaign["budget_balance_cents"] == 21_500
        assert_budget_invariants(campaign)


class TestPublishGatePrecedence:
    def test_past_start_beats_budget_exceeded(self, api):
        """PRD §2.9: "The server evaluates checks in the following fixed order,
        and the first failure wins" — "8. Temporal sanity and overlap: event
        window well-formedness (`ERR_EVENT_WINDOW_INVALID`), future-start
        requirements (`ERR_EVENT_IN_PAST`), staff double-booking
        (`ERR_STAFF_DOUBLE_BOOKED`), and the venue buffer
        (`ERR_EVENT_OVERLAP_BUFFER`)." runs before "10. Fiscal gates last:
        budget checks on publish and completion (`ERR_BUDGET_EXCEEDED`)."

        Design: Difficulty/priority_pair_validation_conflict/event_publish_past_beats_budget_fiscal
        """
        _campaign, school = setup_campaign_with_school(
            campaign_overrides={"total_budget_cents": 10_000}
        )
        event = create_event(
            school,
            title="E1",
            start_time="2026-09-01T10:00:00Z",
            end_time="2026-09-01T12:00:00Z",
            cost_estimate_cents=20_000,  # also breaches the 10000 budget
        )
        set_clock("2026-09-05T00:00:00Z")

        resp = api.publish_event(event["id"], coord(school))
        validate_error(resp, ApiErrorId.ERR_EVENT_IN_PAST)
        assert resp.status_code == 409, (
            "temporal (step 8) must beat fiscal (step 10): expected "
            "ERR_EVENT_IN_PAST, not ERR_BUDGET_EXCEEDED"
        )

    def test_budget_exceeded_fires_when_temporal_checks_pass(self, api):
        """PRD §3.7: "the budget check passes — committed budget plus this
        event's `cost_estimate_cents` must not exceed `total_budget_cents`
        (`ERR_BUDGET_EXCEEDED`, HTTP 402)."

        Design: Difficulty/priority_pair_validation_conflict/event_publish_past_beats_budget_fiscal
        """
        _campaign, school = setup_campaign_with_school(
            campaign_overrides={"total_budget_cents": 10_000}
        )
        event = create_event(school, title="E1", cost_estimate_cents=20_000)

        resp = api.publish_event(event["id"], coord(school))
        validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED)
        assert resp.status_code == 402
        assert get_event(event["id"])["status"] == "DRAFT", (
            "a fiscally rejected publish must not change the event"
        )


class TestVenueBuffer:
    def _setup(self, api):
        campaign, school = setup_campaign_with_school()
        ev1 = create_event(school, title="E1")  # 2026-09-10 10:00-12:00
        publish_event(school, ev1["id"])
        ev2 = create_event(
            school,
            title="E2",
            start_time="2026-09-10T12:15:00Z",
            end_time="2026-09-10T13:00:00Z",
        )
        ev3 = create_event(
            school,
            title="E3",
            start_time="2026-09-10T12:30:00Z",
            end_time="2026-09-10T13:30:00Z",
        )
        return school, ev1, ev2, ev3

    def test_gap_under_thirty_minutes_conflicts(self, api):
        """PRD §3.7: "no other `PUBLISHED` or `IN_PROGRESS` event at the same
        school sits within a thirty-minute venue buffer — windows that overlap
        or leave a gap of less than thirty minutes conflict, while a gap of
        exactly thirty minutes is allowed — (`ERR_EVENT_OVERLAP_BUFFER`)".

        Design: Difficulty/resource_temporal_overlap/school_venue_thirty_minute_buffer
        """
        school, _ev1, ev2, _ev3 = self._setup(api)
        resp = api.publish_event(ev2["id"], coord(school))
        validate_error(resp, ApiErrorId.ERR_EVENT_OVERLAP_BUFFER)
        assert get_event(ev2["id"])["status"] == "DRAFT", (
            "a 15-minute gap is inside the venue buffer; publish must fail"
        )

    def test_gap_of_exactly_thirty_minutes_is_allowed(self, api):
        """PRD §3.7: "no other `PUBLISHED` or `IN_PROGRESS` event at the same
        school sits within a thirty-minute venue buffer — windows that overlap
        or leave a gap of less than thirty minutes conflict, while a gap of
        exactly thirty minutes is allowed — (`ERR_EVENT_OVERLAP_BUFFER`)".

        Design: Difficulty/resource_temporal_overlap/school_venue_thirty_minute_buffer
        """
        school, _ev1, _ev2, ev3 = self._setup(api)
        resp = api.publish_event(ev3["id"], coord(school))
        assert validate_success(resp, 200)["status"] == "PUBLISHED", (
            "the 12:30 start leaves exactly a 30-minute gap after the 12:00 "
            "end — allowed by the inclusive buffer rule"
        )
