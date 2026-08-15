"""Education campaigns, outreach budgeting, zone buffers, and the clock."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_campaign,
    create_campaign_payload,
    create_outreach_event_payload,
    get_campaign,
    get_success_data,
    record_outreach_event,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]


class TestCampaignZoneBuffer:
    def test_campaign_zone_fourteen_day_buffer(self, api):
        """PRD: "To keep outreach efforts from cannibalizing one another, a
        new campaign is rejected with `ERR_CAMPAIGN_WINDOW_CONFLICT` (HTTP
        409) when its window overlaps another campaign in the same
        `outreach_zone` — or even sits within 14 days of one."

        Design: Difficulty/resource_temporal_overlap/campaign_zone_fourteen_day_buffer
        """
        c1 = create_campaign(name="C1 Fall Kickoff", outreach_zone="NORTHSIDE",
                             start_date="2026-09-01T00:00:00Z",
                             end_date="2026-09-30T00:00:00Z",
                             budget_cents=10000)

        # Gap 2026-09-30 -> 2026-10-14 is exactly 14 days: allowed.
        c2 = create_campaign(name="C2 Mid October", outreach_zone="NORTHSIDE",
                             start_date="2026-10-14T00:00:00Z",
                             end_date="2026-11-01T00:00:00Z",
                             budget_cents=10000)
        assert c2["outreach_zone"] == "NORTHSIDE"

        # Gap 2026-09-30 -> 2026-10-10 is only 10 days: within 14, rejected.
        resp = api.create_campaign(
            create_campaign_payload(name="C3 Too Soon",
                                    outreach_zone="NORTHSIDE",
                                    start_date="2026-10-10T00:00:00Z",
                                    end_date="2026-10-20T00:00:00Z",
                                    budget_cents=5000),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_WINDOW_CONFLICT, 409)

        first = get_campaign(c1["id"])
        second = get_campaign(c2["id"])
        assert first["start_date"].startswith("2026-09-01")
        assert second["start_date"].startswith("2026-10-14")

    def test_campaign_overlap_rejected_and_other_zone_allowed(self, api):
        """PRD: "a new campaign is rejected with
        `ERR_CAMPAIGN_WINDOW_CONFLICT` (HTTP 409) when its window overlaps
        another campaign in the same `outreach_zone` — or even sits within 14
        days of one."

        Design: Difficulty/resource_temporal_overlap/campaign_zone_fourteen_day_buffer
        """
        create_campaign(name="Z1 Anchor", outreach_zone="Z1",
                        start_date="2026-09-01T00:00:00Z",
                        end_date="2026-09-30T00:00:00Z", budget_cents=10000)

        # Direct overlap in the same zone.
        resp = api.create_campaign(
            create_campaign_payload(name="Z1 Overlap", outreach_zone="Z1",
                                    start_date="2026-09-15T00:00:00Z",
                                    end_date="2026-10-15T00:00:00Z",
                                    budget_cents=5000),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_WINDOW_CONFLICT, 409)

        # The same window in a different zone is allowed.
        other = create_campaign(name="Z2 Free", outreach_zone="Z2",
                                start_date="2026-09-15T00:00:00Z",
                                end_date="2026-10-15T00:00:00Z",
                                budget_cents=5000)
        assert other["outreach_zone"] == "Z2"


class TestCampaignBudget:
    def test_campaign_budget_exact_fit_allowed(self, api):
        """PRD: "The fiscal check runs after the temporal one: `cost_cents`
        must not exceed the campaign's `remaining_budget_cents`, though a cost
        exactly equal to the remaining budget is permitted; anything larger is
        rejected with `ERR_CAMPAIGN_BUDGET_EXCEEDED` (HTTP 422)."
        PRD: "the campaign's `remaining_budget_cents` is initialized to the
        full `budget_cents`"

        Design: Difficulty/boundary_precision_check/campaign_budget_exact_fit_allowed
        """
        campaign = create_campaign(name="Grease Wipe Week",
                                   outreach_zone="ZBOUND", budget_cents=50000)
        assert campaign["remaining_budget_cents"] == 50000

        event = record_outreach_event(campaign["id"],
                                      event_date="2026-09-15T00:00:00Z",
                                      venue_name="County Fair",
                                      attendance_count=100, cost_cents=50000)
        assert event["status"] == "RECORDED", (
            "cost exactly equal to the remaining budget is permitted"
        )
        assert get_campaign(campaign["id"])["remaining_budget_cents"] == 0

        resp = api.create_outreach_event(
            campaign["id"],
            create_outreach_event_payload(event_date="2026-09-16T00:00:00Z",
                                          venue_name="School Gym",
                                          attendance_count=50, cost_cents=1),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_BUDGET_EXCEEDED, 422)

    def test_campaign_budget_one_cent_over_rejected(self, api):
        """PRD: "`cost_cents` must not exceed the campaign's
        `remaining_budget_cents`, though a cost exactly equal to the remaining
        budget is permitted; anything larger is rejected with
        `ERR_CAMPAIGN_BUDGET_EXCEEDED` (HTTP 422)."
        PRD: "A recorded event starts in `RECORDED` status, and the campaign's
        remaining budget drops by its `cost_cents`"

        Design: Difficulty/boundary_precision_check/campaign_budget_exact_fit_allowed
        """
        campaign = create_campaign(name="Overdraw Week", outreach_zone="ZOVER",
                                   budget_cents=10000)
        resp = api.create_outreach_event(
            campaign["id"],
            create_outreach_event_payload(event_date="2026-09-10T00:00:00Z",
                                          venue_name="Mall", attendance_count=10,
                                          cost_cents=10001),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_BUDGET_EXCEEDED, 422)
        assert get_campaign(campaign["id"])["remaining_budget_cents"] == 10000, (
            "The rejected event debits nothing"
        )


class TestCampaignEventVoidInvariant:
    def test_campaign_event_void_restores_budget(self, api):
        """PRD: "Voiding is a compensating credit: the event's `cost_cents`
        returns to the campaign's `remaining_budget_cents`, so a
        recorded-then-voided event leaves the budget exactly where it stood
        before the event."
        PRD: "If an event was logged in error, a `ProgramAdmin` voids it,
        moving it from `RECORDED` to the terminal `VOIDED` status."

        Design: Difficulty/compensating_invariant/campaign_event_void_restores_budget
        """
        campaign = create_campaign(name="Invariant Drive", outreach_zone="ZSOUTH",
                                   budget_cents=50000)
        assert campaign["remaining_budget_cents"] == 50000

        event = record_outreach_event(campaign["id"],
                                      event_date="2026-09-10T00:00:00Z",
                                      venue_name="Library", attendance_count=40,
                                      cost_cents=30000)
        assert event["status"] == "RECORDED"
        assert get_campaign(campaign["id"])["remaining_budget_cents"] == 20000

        voided = validate_success(api.void_outreach_event(event["id"], ADMIN))
        assert voided["status"] == "VOIDED"
        after = get_campaign(campaign["id"])
        assert after["remaining_budget_cents"] == 50000 == after["budget_cents"], (
            "record + void conserves remaining_budget_cents"
        )

    def test_campaign_budget_sum_excludes_voided_events(self, api):
        """PRD: "`remaining_budget_cents` is always the budget minus the
        summed costs of the campaign's `RECORDED` events."
        PRD: "`VOIDED` events are excluded from the budget sum."

        Design: Difficulty/compensating_invariant/campaign_event_void_restores_budget
        """
        campaign = create_campaign(name="Sum Drive", outreach_zone="ZSUM",
                                   budget_cents=40000)
        e1 = record_outreach_event(campaign["id"], cost_cents=10000,
                                   event_date="2026-09-05T00:00:00Z")
        record_outreach_event(campaign["id"], cost_cents=5000,
                              event_date="2026-09-06T00:00:00Z")
        assert get_campaign(campaign["id"])["remaining_budget_cents"] == 25000

        get_success_data(api.void_outreach_event(e1["id"], ADMIN))
        # 40000 - 5000 (only the still-RECORDED event counts).
        assert get_campaign(campaign["id"])["remaining_budget_cents"] == 35000


class TestOutreachEventWindow:
    def test_event_outside_campaign_window_rejected(self, api):
        """PRD: "Each event carries an `event_date` that must fall within the
        campaign's inclusive window from `start_date` to `end_date`
        (`ERR_OUTSIDE_CAMPAIGN_WINDOW`, HTTP 422)"
        PRD: "A recorded event starts in `RECORDED` status, and the campaign's
        remaining budget drops by its `cost_cents`"

        Design: Corner/validations/c_event_outside_campaign_window_rejected
        """
        campaign = create_campaign(name="Window Week", outreach_zone="ZEAST",
                                   budget_cents=10000)
        resp = api.create_outreach_event(
            campaign["id"],
            create_outreach_event_payload(event_date="2026-08-20T00:00:00Z",
                                          venue_name="Mall", attendance_count=30,
                                          cost_cents=1000),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_CAMPAIGN_WINDOW, 422)

        event = record_outreach_event(campaign["id"],
                                      event_date="2026-09-10T00:00:00Z",
                                      venue_name="Mall", attendance_count=30,
                                      cost_cents=1000)
        assert event["status"] == "RECORDED"
        assert get_campaign(campaign["id"])["remaining_budget_cents"] == 9000


class TestLogicalClock:
    def test_clock_regression_rejected(self, api):
        """PRD: "The new value must be strictly after the current value; a
        proposed reading at or before the current clock is rejected with
        `ERR_CLOCK_REGRESSION` (HTTP 422). A successful call returns the new
        reading as `current_utc`."

        Design: Corner/validations/c_clock_regression_rejected
        """
        set_clock("2026-08-02T00:00:00Z")

        resp = api.set_clock("2026-08-01T12:00:00Z", ADMIN)
        validate_error(resp, ApiErrorId.ERR_CLOCK_REGRESSION, 422)

        advanced = set_clock("2026-08-03T00:00:00Z")
        assert advanced["current_utc"].startswith("2026-08-03"), (
            "The monotone rule only rejects backward moves"
        )

    def test_clock_rejects_equal_value(self, api):
        """PRD: "The new value must be strictly after the current value; a
        proposed reading at or before the current clock is rejected with
        `ERR_CLOCK_REGRESSION` (HTTP 422)."
        PRD: "Before any clock-setting call has been made, the logical clock
        reads exactly 2026-08-01T00:00:00Z."

        Design: Corner/validations/c_clock_regression_rejected
        """
        # Equal to the current reading: not strictly after.
        resp = api.set_clock("2026-08-01T00:00:00Z", ADMIN)
        validate_error(resp, ApiErrorId.ERR_CLOCK_REGRESSION, 422)

        advanced = set_clock("2026-08-01T00:00:01Z")
        assert advanced["current_utc"].startswith("2026-08-01")
