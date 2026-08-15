"""Campaign and school lifecycle: creation defaults, the deadline calendar,
the close cascade, and school enrollment state rules (PRD §2.5, §3.1, §3.2)."""
import pytest

from test_helpers import (
    ApiErrorId,
    coord,
    create_campaign_payload,
    create_event,
    create_open_campaign,
    get_campaign,
    get_event,
    add_school,
    enroll_school,
    set_clock,
    setup_campaign_with_school,
    add_senior,
    publish_event,
    complete_running_event,
    assert_budget_invariants,
    validate_error,
    validate_success,
)

TOTAL = 50_000


class TestCampaignCreation:
    def test_campaign_creation_applies_documented_defaults(self, api, admin_headers):
        """PRD §3.1: "Five tuning knobs ship with documented defaults and may be
        overridden at creation: `auto_confirm_threshold` (default 0.90) and
        `review_floor` (default 0.60) govern the matching bands of §3.3;
        `min_subgroup_size` (default 5) is the k-anonymity floor for report rows;
        `max_caseload` (default 25) is the specialist overload threshold;
        `no_show_limit` (default 3) is the staffing suspension threshold; and
        `min_recognition_seniors` (default 10) is the minimum senior base for
        school recognition."
        PRD §3.1: "A new campaign is `DRAFT` with all budget counters at zero."

        Design: Corner/entities/campaign_create_applies_threshold_defaults
        """
        resp = api.create_campaign(
            create_campaign_payload(name="C27", total_budget_cents=TOTAL),
            admin_headers,
        )
        created = validate_success(resp, 201)
        resp = api.get_campaign(created["id"], admin_headers)
        campaign = validate_success(resp, 200)

        assert campaign["status"] == "DRAFT"
        assert campaign["auto_confirm_threshold"] == pytest.approx(0.90)
        assert campaign["review_floor"] == pytest.approx(0.60)
        assert campaign["min_subgroup_size"] == 5
        assert campaign["max_caseload"] == 25
        assert campaign["no_show_limit"] == 3
        assert campaign["min_recognition_seniors"] == 10
        assert campaign["committed_budget_cents"] == 0
        assert campaign["spent_budget_cents"] == 0
        assert campaign["budget_balance_cents"] == TOTAL


class TestCampaignClockTransitions:
    def test_state_grace_at_state_deadline_still_admits_child_writes(
        self, api, admin_headers
    ):
        """PRD §2.5: "A campaign in `OPEN` moves to `STATE_GRACE` once the clock
        reaches or passes its `state_grant_deadline`, provided the clock has not
        yet reached its `federal_deadline`."
        PRD §3.3: "With a school `ENROLLED` and the campaign `OPEN` or
        `STATE_GRACE`, the school's coordinator builds the senior list."

        Design: Corner/state_machines/campaign_clock_transitions_and_close_cascade
        """
        campaign, school = setup_campaign_with_school()

        set_clock("2027-05-01T00:00:00Z")
        campaign = get_campaign(campaign["id"])
        assert campaign["status"] == "STATE_GRACE", (
            f"expected STATE_GRACE after the state grant deadline passed, got "
            f"{campaign['status']}"
        )

        # STATE_GRACE still admits senior-list writes.
        senior = add_senior(school, student_ref="S1")
        assert senior["match_status"] == "UNMATCHED"

    def test_federal_deadline_closes_campaign_with_close_cascade(
        self, api, admin_headers
    ):
        """PRD §2.5: "A campaign in `OPEN` or `STATE_GRACE` moves to `CLOSED`
        once the clock reaches or passes its `federal_deadline`, firing the full
        close cascade described in §3.1."
        PRD §3.1: "the close cascade fires: every `DRAFT` or `PUBLISHED`
        completion event of the campaign is cancelled" and "a `CLOSED` campaign
        blocks all child writes."

        Design: Corner/state_machines/campaign_clock_transitions_and_close_cascade
        """
        campaign, school = setup_campaign_with_school()
        event = create_event(school, title="E1")

        set_clock("2028-07-01T00:00:00Z")
        campaign = get_campaign(campaign["id"])
        assert campaign["status"] == "CLOSED"

        # CLOSE CASCADE: the DRAFT event is cancelled.
        event = get_event(event["id"])
        assert event["status"] == "CANCELLED", (
            f"DRAFT event must be cancelled by the close cascade, got "
            f"{event['status']}"
        )

        # A CLOSED campaign blocks all child writes.
        resp = api.create_senior_record(
            {
                "school_id": school["id"],
                "student_ref": "S2",
                "full_name": "A Two",
                "dob": "2009-01-02",
                "home_language": "en",
            },
            coord(school),
        )
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_NOT_OPEN)


class TestSchoolStateRules:
    def test_enroll_requires_invited_and_reinstate_requires_suspended(
        self, api, admin_headers
    ):
        """PRD §3.2: "enrollment moves it to `ENROLLED` and is only valid while
        the school is `INVITED` (otherwise `ERR_SCHOOL_NOT_INVITED`)" and
        "reinstatement requires the school to be `SUSPENDED`
        (`ERR_SCHOOL_NOT_SUSPENDED`) and the campaign `OPEN`."

        Design: Corner/state_machines/school_invalid_transitions
        """
        campaign = create_open_campaign()
        school = enroll_school(add_school(campaign))

        resp = api.enroll_school(school["id"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_SCHOOL_NOT_INVITED)

        resp = api.reinstate_school(school["id"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_SCHOOL_NOT_SUSPENDED)

    def test_school_suspend_cancels_only_nonterminal_events(self, api, admin_headers):
        """PRD §3.2: "suspending an `ENROLLED` school (any other state draws
        `ERR_SCHOOL_NOT_ENROLLED`) cancels every `DRAFT` or `PUBLISHED` event of
        that school with the full assignment, registration, and budget cascades
        of §3.6, while `COMPLETED` and `IN_PROGRESS` events are untouched."

        Design: Corner/state_machines/school_suspend_cancels_only_nonterminal_events
        """
        campaign, school = setup_campaign_with_school(
            campaign_overrides={"total_budget_cents": TOTAL}
        )
        # E_C: published, run, completed with actual cost 4000.
        ev_completed = create_event(
            school,
            title="EC",
            start_time="2026-09-01T10:00:00Z",
            end_time="2026-09-01T12:00:00Z",
            cost_estimate_cents=5_000,
        )
        publish_event(school, ev_completed["id"])
        complete_running_event(
            school, ev_completed["id"], 4_000, "2026-09-01T11:00:00Z"
        )
        # E_D: stays DRAFT. E_P: PUBLISHED with a 5000 commitment.
        ev_draft = create_event(
            school,
            title="ED",
            start_time="2026-10-01T10:00:00Z",
            end_time="2026-10-01T12:00:00Z",
            cost_estimate_cents=5_000,
        )
        ev_published = create_event(
            school,
            title="EP",
            start_time="2026-10-02T10:00:00Z",
            end_time="2026-10-02T12:00:00Z",
            cost_estimate_cents=5_000,
        )
        publish_event(school, ev_published["id"])

        resp = api.suspend_school(school["id"], admin_headers)
        school = validate_success(resp, 200)
        assert school["status"] == "SUSPENDED"

        assert get_event(ev_draft["id"])["status"] == "CANCELLED"
        assert get_event(ev_published["id"])["status"] == "CANCELLED"
        assert get_event(ev_completed["id"])["status"] == "COMPLETED", (
            "COMPLETED events must be untouched by the suspend cascade"
        )

        campaign = get_campaign(campaign["id"])
        assert campaign["committed_budget_cents"] == 0, (
            f"the PUBLISHED event's 5000 commitment must be released, got "
            f"{campaign['committed_budget_cents']}"
        )
        assert campaign["spent_budget_cents"] == 4_000
        assert_budget_invariants(campaign)
