"""Severity score composition and notification lifecycle/auto-notify
idempotence (PRD §3.5, §3.8)."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId,
    setup_territory, setup_territory_technician, intake_call, triage, dispatch,
    arrive, set_clock, get_incident, record_reading,
    TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]


def _fixture_multi_family_p2_with_symptoms():
    """MULTI_FAMILY inside-odor incident whose call reports symptoms; triaged
    P2, dispatched, arrived at 00:20. (Implied P1 via symptoms means the
    AUTO_PRIORITY rule already fired at intake.)"""
    terr, tech = setup_territory_technician()
    call = intake_call(
        terr["id"], address_line="5 Elm St", caller_name="Cara",
        caller_phone="555-0102", location_context="INSIDE_STRUCTURE",
        occupancy_type="MULTI_FAMILY", odor_reported=True,
        symptoms_reported=True, hissing_reported=False)
    inc_id = call["incident_id"]
    triage(inc_id, "P2")
    disp = dispatch(inc_id, tech["id"])
    set_clock("2026-08-01T00:20:00Z")
    arrive(disp["id"], tech["id"])
    return terr, tech, call, disp


class TestSeverityScoreMultiFactorBranches:
    def test_severity_score_combines_all_four_factors(self, api):
        """PRD §3.5: "The score is forty times the LEL factor, plus
        twenty-five times the CO factor, plus twenty times the occupancy
        factor, plus fifteen times the symptom factor, rounded half up to an
        integer and clamped so it never falls below zero nor exceeds one
        hundred." With pct_lel 12.0 (LEL factor 1.0), co_ppm 80 (CO factor
        1.0), MULTI_FAMILY (0.6), symptoms (1.0): 40 + 25 + 12 + 15 = 92.

        Design: Difficulty/combinatorial_formula/severity_score_multi_factor_branches
        """
        terr, tech, call, disp = _fixture_multi_family_p2_with_symptoms()
        record_reading(call["incident_id"], tech["id"], pct_lel=12.0, co_ppm=80,
                       reading_context="INSIDE")
        incident = get_incident(call["incident_id"])
        assert incident["severity_score"] == 92
        assert incident["evacuation_required"] is True, (
            "pct_lel 12.0 >= 10.0 sets evacuation_required (PRD §3.5)")

    def test_auto_notification_idempotence_across_rules(self, api):
        """PRD §3.8: "The `AUTO_PRIORITY` rule fires whenever an incident's
        priority reaches `P1` — at primary-call creation, at triage, at
        reclassification, at duplicate-call escalation, or through a merge —
        provided the incident's `auto_notification_created` flag is still
        false; it creates a draft notification on the `PUBLIC_ALERT` channel
        and sets the flag." and "The flag enforces idempotence across both
        rules: at most one automatic notification ever exists per incident."

        Design: Difficulty/combinatorial_formula/severity_score_multi_factor_branches
        """
        terr, tech, call, disp = _fixture_multi_family_p2_with_symptoms()
        record_reading(call["incident_id"], tech["id"], pct_lel=12.0, co_ppm=80,
                       reading_context="INSIDE")

        data, meta = validate_paginated(api_client.list_notifications(
            call["incident_id"], SUPERVISOR))
        # The intake-time AUTO_PRIORITY notification (implied P1 via symptoms)
        # already consumed the flag; severity 92 >= 80 creates no second one.
        assert meta["total_count"] == 1
        assert data[0]["origin"] == "AUTO_PRIORITY"
        assert data[0]["channel"] == "PUBLIC_ALERT"
        assert data[0]["status"] == "DRAFT"


class TestNotificationIssueAndRetract:
    def test_issue_and_retract_conditional_actions(self, api):
        """PRD §3.8: "Issuing requires a `DRAFT` notification — otherwise
        `ERR_NOTIFICATION_NOT_DRAFT` (HTTP 409) — stamps `issued_at`, and
        moves it to `ISSUED`. Retracting requires `ISSUED` — otherwise
        `ERR_NOTIFICATION_NOT_ISSUED` (HTTP 409) — accepts an optional
        `reason`, stamps `retracted_at`, and moves it to `RETRACTED`,
        terminal."

        Design: Corner/endpoints/notification_issue_and_retract_conditional_actions
        """
        terr = setup_territory()
        call = intake_call(terr["id"], address_line="5 Note St",
                           caller_name="Z5", caller_phone="555-0229",
                           location_context="OUTSIDE_STRUCTURE")
        notif = validate_success(api_client.create_notification(
            call["incident_id"],
            {"channel": "MEDIA", "headline": "Gas odor reported",
             "body": "Crews responding"},
            SUPERVISOR), expected_status=201)
        assert notif["status"] == "DRAFT"
        assert notif["origin"] == "MANUAL"

        # Retract from DRAFT fails.
        resp = api_client.retract_notification(notif["id"], SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_NOTIFICATION_NOT_ISSUED)

        # Issue from DRAFT succeeds.
        issued = validate_success(api_client.issue_notification(notif["id"],
                                                                SUPERVISOR))
        assert issued["status"] == "ISSUED"
        assert issued["issued_at"] is not None

        # Retract from ISSUED succeeds.
        retracted = validate_success(api_client.retract_notification(
            notif["id"], SUPERVISOR, {"reason": "all clear"}))
        assert retracted["status"] == "RETRACTED"
        assert retracted["retracted_at"] is not None

        # Issue from RETRACTED fails (terminal lockdown).
        resp = api_client.issue_notification(notif["id"], SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_NOTIFICATION_NOT_DRAFT)
