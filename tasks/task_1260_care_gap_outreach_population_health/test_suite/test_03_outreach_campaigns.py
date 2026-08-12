"""Outreach campaign lifecycle and attempt-liveness claims (PRD §3.4)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, NOON_DAY1_ISO,
    setup_panel_scenario, create_campaign, schedule_campaign, launch_campaign,
    setup_active_campaign, advance_clock, get_care_gap, create_attempt_payload,
    make_admin_headers, make_panel_manager_headers, make_quality_reviewer_headers,
)


class TestCampaignLifecycle:
    def test_campaign_invalid_transition_draft_to_active(self, api):
        """PRD §3.4: "The campaign lifecycle runs `DRAFT` → `SCHEDULED` → `ACTIVE`,
        with a pause loop and two endings."
        PRD §2.8: "then whether the target resource is in a state that permits the
        action (failure yields `ERR_INVALID_STATE`, HTTP 409)".

        Design: Corner/state_machines/campaign_invalid_transition_draft_to_active
        """
        scenario = setup_panel_scenario(num_members=1)
        campaign = create_campaign(scenario["registry"]["id"], scenario["panel"]["id"],
                                   scenario["measure"]["id"])
        # Launch straight from DRAFT, skipping SCHEDULED.
        resp = api.launch_campaign(campaign["id"], make_admin_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_err_campaign_not_yet_open_triggerable(self, api):
        """PRD §3.4: "Launching — performed manually by an administrator, or
        automatically by the system when the clock reaches `starts_at` — requires
        that the clock has reached `starts_at` (otherwise `ERR_CAMPAIGN_NOT_YET_OPEN`)
        and that the linked panel is `ACTIVE` (otherwise `ERR_PANEL_NOT_ACTIVE`)".

        Design: Corner/errors/err_campaign_not_yet_open_triggerable
        """
        scenario = setup_panel_scenario(num_members=1)
        campaign = create_campaign(
            scenario["registry"]["id"], scenario["panel"]["id"],
            scenario["measure"]["id"],
            starts_at="2026-06-01T00:00:00Z", ends_at="2026-12-31T23:59:59Z")
        schedule_campaign(campaign["id"])
        # Clock is still the default 2026-05-01, before starts_at 2026-06-01.
        resp = api.launch_campaign(campaign["id"], make_admin_headers())
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_NOT_YET_OPEN)

    def test_err_panel_not_active_triggerable(self, api):
        """PRD §3.4: "Launching — performed manually by an administrator, or
        automatically by the system when the clock reaches `starts_at` — requires
        that the clock has reached `starts_at` (otherwise `ERR_CAMPAIGN_NOT_YET_OPEN`)
        and that the linked panel is `ACTIVE` (otherwise `ERR_PANEL_NOT_ACTIVE`)".
        PRD §3.2: "the panel is born in `BUILDING` status."

        Design: Corner/errors/err_panel_not_active_triggerable
        """
        from test_helpers import (create_published_measure, create_active_cohort,
                                  create_panel, create_registry)
        registry = create_registry(name="R-PANEL")
        measure = create_published_measure(registry["id"])
        cohort = create_active_cohort(registry["id"])
        panel = create_panel(registry["id"], cohort["id"], measure["id"])  # BUILDING
        campaign = create_campaign(registry["id"], panel["id"], measure["id"])
        schedule_campaign(campaign["id"])
        resp = api.launch_campaign(campaign["id"], make_admin_headers())
        validate_error(resp, ApiErrorId.ERR_PANEL_NOT_ACTIVE)


class TestCampaignPauseResumeCycle:
    def test_campaign_pause_resume_cycle_returns_to_active(self, api):
        """PRD §3.4: "An `ACTIVE` campaign can be paused, and a `PAUSED` campaign can
        be resumed provided `ends_at` has not yet passed — resuming after the window
        closed fails with `ERR_CAMPAIGN_WINDOW_PAST`."

        Design: Difficulty/non_linear_state_machine/campaign_pause_resume_cycle
        """
        scenario = setup_panel_scenario(num_members=1)
        campaign = setup_active_campaign(scenario)
        paused = get_success_data(api.pause_campaign(campaign["id"], make_admin_headers()))
        assert paused["status"] == "PAUSED", f"Expected PAUSED, got {paused['status']}"
        resumed = get_success_data(api.resume_campaign(campaign["id"], make_admin_headers()))
        assert resumed["status"] == "ACTIVE", (
            f"Expected ACTIVE after pause->resume cycle, got {resumed['status']}")

    def test_paused_campaign_blocks_attempts_resume_reenables(self, api):
        """PRD §3.4: "An `ACTIVE` campaign can be paused, and a `PAUSED` campaign can
        be resumed provided `ends_at` has not yet passed".
        PRD §3.4: "and finally campaign liveness, which rejects with
        `ERR_CAMPAIGN_NOT_ACTIVE` unless the referenced campaign is `ACTIVE`."

        Design: Difficulty/non_linear_state_machine/campaign_pause_resume_cycle
        """
        scenario = setup_panel_scenario(num_members=1)
        campaign = setup_active_campaign(scenario)  # clock now at noon, waking hours
        gap = scenario["gaps"][0]
        get_success_data(api.pause_campaign(campaign["id"], make_admin_headers()))
        gap_now = get_care_gap(gap["id"])
        resp = api.create_outreach_attempt(
            gap["id"],
            create_attempt_payload(campaign_id=campaign["id"],
                                   expected_care_gap_version=gap_now["version"]),
            make_panel_manager_headers(scenario["panel_manager_id"]))
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_NOT_ACTIVE)
        # Resume re-enables attempts without changing the campaign window.
        get_success_data(api.resume_campaign(campaign["id"], make_admin_headers()))
        gap_now = get_care_gap(gap["id"])
        resp = api.create_outreach_attempt(
            gap["id"],
            create_attempt_payload(campaign_id=campaign["id"],
                                   expected_care_gap_version=gap_now["version"]),
            make_panel_manager_headers(scenario["panel_manager_id"]))
        validate_success(resp, 201)


class TestAttemptRequiresCampaignActive:
    def test_attempt_rejected_when_campaign_paused(self, api):
        """PRD §3.4: "and finally campaign liveness, which rejects with
        `ERR_CAMPAIGN_NOT_ACTIVE` unless the referenced campaign is `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/attempt_requires_campaign_active
        """
        scenario = setup_panel_scenario(num_members=1)
        campaign = setup_active_campaign(scenario)
        gap = scenario["gaps"][0]
        get_success_data(api.pause_campaign(campaign["id"], make_admin_headers()))
        gap_now = get_care_gap(gap["id"])
        resp = api.create_outreach_attempt(
            gap["id"],
            create_attempt_payload(campaign_id=campaign["id"],
                                   expected_care_gap_version=gap_now["version"]),
            make_panel_manager_headers(scenario["panel_manager_id"]))
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_NOT_ACTIVE)

    def test_attempt_rejected_when_campaign_cancelled(self, api):
        """PRD §3.4: "Cancellation is available from `DRAFT`, `SCHEDULED`, `ACTIVE`,
        or `PAUSED` and moves the campaign to `CANCELLED`, after which no further
        attempts are accepted."
        PRD §3.4: "and finally campaign liveness, which rejects with
        `ERR_CAMPAIGN_NOT_ACTIVE` unless the referenced campaign is `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/attempt_requires_campaign_active
        """
        scenario = setup_panel_scenario(num_members=1)
        campaign = setup_active_campaign(scenario)
        gap = scenario["gaps"][0]
        get_success_data(api.cancel_campaign(campaign["id"], make_admin_headers()))
        gap_now = get_care_gap(gap["id"])
        resp = api.create_outreach_attempt(
            gap["id"],
            create_attempt_payload(campaign_id=campaign["id"],
                                   expected_care_gap_version=gap_now["version"]),
            make_panel_manager_headers(scenario["panel_manager_id"]))
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_NOT_ACTIVE)
