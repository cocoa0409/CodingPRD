"""Incidents, alert escalation, mutual-aid agreements/requests."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_active_agreement,
    create_controlled_incident,
    create_incident_payload,
    create_mutual_aid_agreement_payload,
    create_mutual_aid_request_payload,
    get_success_data,
    open_oos_event,
    set_clock,
    setup_compliant_index_c_airport,
    setup_profile_only,
    validate_error,
    validate_success,
)

AM = TEST_USERS["airport_manager_headers"]
AC = TEST_USERS["arff_chief_headers"]


class TestIncidentTerminalLockdown:
    def test_closed_incident_respond_and_patch_rejected(self, api):
        """PRD §3.8: "Response is gated on capability. The incident must
        currently be `REPORTED` (otherwise `ERR_INCIDENT_NOT_OPEN`), and the
        profile's `effective_index` must be at-or-above the alert level's
        required index: `A` for `ALERT_1`, `B` for `ALERT_2`, `C` for
        `ALERT_3`." and PRD §3.8: "Alert level can escalate in place while
        the incident is open. The escalation is a self-transition allowed
        from either `REPORTED` or `RESPONDING` (attempts from other states
        are rejected with `ERR_INCIDENT_NOT_OPEN`), and the new `alert_level`
        must be strictly higher than the current value — a same-level or
        downgrade patch is rejected with `ERR_ALERT_LEVEL_NOT_ESCALATION`."

        Design: Corner/state_machines/sm_incident_terminal_lockdown_rejected
        """
        setup_compliant_index_c_airport()
        inc = create_controlled_incident(alert_level="ALERT_1",
                                         location="Taxiway A")
        resp = api.close_incident(inc["id"], AC)
        closed = validate_success(resp)
        assert closed["status"] == "CLOSED"

        r1 = api.respond_incident(inc["id"], AC)
        validate_error(r1, ApiErrorId.ERR_INCIDENT_NOT_OPEN)
        r2 = api.patch_incident_alert_level(inc["id"], {"alert_level": "ALERT_3"}, AC)
        validate_error(r2, ApiErrorId.ERR_INCIDENT_NOT_OPEN)


class TestMutualAidRequestRequiresIncidentOpen:
    def test_request_create_on_reported_incident_succeeds(self, api):
        """PRD §3.9: "The incident must currently be `REPORTED` or
        `RESPONDING`; otherwise `ERR_INCIDENT_NOT_RESPONDING`."

        Design: Difficulty/cross_entity_state_dependency/ce_mutual_aid_request_requires_incident_open
        """
        setup_compliant_index_c_airport()
        ag = create_active_agreement(partner_airport_code="KCTY",
                                     max_alert_level="ALERT_2")
        inc1 = validate_success(
            api.create_incident(
                create_incident_payload(alert_level="ALERT_1",
                                        location="Runway 09L"),
                AC,
            ),
            expected_status=201,
        )
        resp = api.create_mutual_aid_request(
            inc1["id"],
            create_mutual_aid_request_payload(ag["id"], units_requested=2),
            AC,
        )
        req = validate_success(resp, expected_status=201)
        assert req["status"] == "REQUESTED"

    def test_request_create_on_controlled_incident_rejected(self, api):
        """PRD §3.9: "The incident must currently be `REPORTED` or
        `RESPONDING`; otherwise `ERR_INCIDENT_NOT_RESPONDING`."

        Design: Difficulty/cross_entity_state_dependency/ce_mutual_aid_request_requires_incident_open
        """
        setup_compliant_index_c_airport()
        ag = create_active_agreement(partner_airport_code="KCTY",
                                     max_alert_level="ALERT_2")
        inc2 = create_controlled_incident(alert_level="ALERT_1",
                                          location="Runway 27R")
        resp = api.create_mutual_aid_request(
            inc2["id"],
            create_mutual_aid_request_payload(ag["id"], units_requested=1),
            AC,
        )
        validate_error(resp, ApiErrorId.ERR_INCIDENT_NOT_RESPONDING)


class TestRequestDeclineBranchRejectsDeploy:
    def test_declined_request_deploy_rejected(self, api):
        """PRD §3.9: "Deploy moves `REQUESTED` to `DEPLOYED`; release moves
        `DEPLOYED` to `RELEASED`; decline moves `REQUESTED` to `DECLINED`.
        Each is gated on the request being in the required source state —
        deploy or decline on a non-`REQUESTED` request, or release on a
        non-`DEPLOYED` request, is rejected with
        `ERR_REQUEST_NOT_ACTIONABLE`."

        Design: Corner/state_machines/sm_request_decline_branch_rejects_deploy
        """
        setup_compliant_index_c_airport()
        ag = create_active_agreement(partner_airport_code="KCTY",
                                     max_alert_level="ALERT_3")
        inc = validate_success(
            api.create_incident(
                create_incident_payload(alert_level="ALERT_2",
                                        location="Runway 09L"),
                AC,
            ),
            expected_status=201,
        )
        req = validate_success(
            api.create_mutual_aid_request(
                inc["id"],
                create_mutual_aid_request_payload(ag["id"], units_requested=2),
                AC,
            ),
            expected_status=201,
        )
        resp = api.decline_mutual_aid_request(req["id"], AC)
        declined = validate_success(resp)
        assert declined["status"] == "DECLINED"
        resp = api.deploy_mutual_aid_request(req["id"], AC)
        validate_error(resp, ApiErrorId.ERR_REQUEST_NOT_ACTIONABLE)


class TestIncidentCloseBlockedByOpenRequest:
    def test_close_blocked_by_requested_request(self, api):
        """PRD §3.8: "Closure moves `CONTROLLED` to `CLOSED` and is blocked
        when any mutual-aid request for the incident sits in `REQUESTED` or
        `DEPLOYED` — such a close is rejected with
        `ERR_OPEN_REQUESTS_EXIST`."

        Design: Corner/state_machines/sm_incident_close_blocked_by_open_request
        """
        setup_compliant_index_c_airport()
        ag = create_active_agreement(partner_airport_code="KCTY",
                                     max_alert_level="ALERT_3")
        inc = validate_success(
            api.create_incident(
                create_incident_payload(alert_level="ALERT_2",
                                        location="Runway 09L"),
                AC,
            ),
            expected_status=201,
        )
        req = validate_success(
            api.create_mutual_aid_request(
                inc["id"],
                create_mutual_aid_request_payload(ag["id"], units_requested=1),
                AC,
            ),
            expected_status=201,
        )
        api.respond_incident(inc["id"], AC)
        api.control_incident(inc["id"], AC)
        resp = api.close_incident(inc["id"], AC)
        validate_error(resp, ApiErrorId.ERR_OPEN_REQUESTS_EXIST)
        # After decline, close succeeds
        api.decline_mutual_aid_request(req["id"], AC)
        resp = api.close_incident(inc["id"], AC)
        closed = validate_success(resp)
        assert closed["status"] == "CLOSED"


class TestAgreementWindowClosedInterval:
    def test_touching_window_conflicts_closed_semantics(self, api):
        """PRD §3.9: "The window is closed — so a new agreement whose
        `start_date` equals an existing agreement's `end_date` for the same
        partner conflicts."

        Design: Difficulty/resource_temporal_overlap/ro_agreement_window_closed_interval_touch_conflicts
        """
        setup_profile_only()
        ag1 = validate_success(
            api.create_mutual_aid_agreement(
                create_mutual_aid_agreement_payload(
                    partner_airport_code="KCTY", max_alert_level="ALERT_2",
                    start_date="2026-01-01", end_date="2026-06-30",
                ),
                AM,
            ),
            expected_status=201,
        )
        api.activate_mutual_aid_agreement(ag1["id"], AM)
        # Touching at 2026-06-30 conflicts under closed semantics
        resp = api.create_mutual_aid_agreement(
            create_mutual_aid_agreement_payload(
                partner_airport_code="KCTY", max_alert_level="ALERT_3",
                start_date="2026-06-30", end_date="2026-12-31",
            ),
            AM,
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_WINDOW_OVERLAP)

    def test_strictly_after_window_accepted(self, api):
        """PRD §3.9: "A new agreement whose closed window overlaps another
        `DRAFT` or `ACTIVE` agreement for the same partner is rejected with
        `ERR_AGREEMENT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/ro_agreement_window_closed_interval_touch_conflicts
        """
        setup_profile_only()
        ag1 = validate_success(
            api.create_mutual_aid_agreement(
                create_mutual_aid_agreement_payload(
                    partner_airport_code="KCTY", max_alert_level="ALERT_2",
                    start_date="2026-01-01", end_date="2026-06-30",
                ),
                AM,
            ),
            expected_status=201,
        )
        api.activate_mutual_aid_agreement(ag1["id"], AM)
        # 2026-07-01 > 2026-06-30 -> clear
        resp = api.create_mutual_aid_agreement(
            create_mutual_aid_agreement_payload(
                partner_airport_code="KCTY", max_alert_level="ALERT_3",
                start_date="2026-07-01", end_date="2026-12-31",
            ),
            AM,
        )
        ag3 = validate_success(resp, expected_status=201)
        assert ag3["status"] == "DRAFT"
        # Original agreement unchanged
        ag1_after = get_success_data(
            api.get_mutual_aid_agreement(ag1["id"], AM)
        )
        assert ag1_after["status"] == "ACTIVE"


class TestAgreementAutoExpiry:
    def test_active_agreement_expires_on_clock_advance(self, api):
        """PRD §3.9: "Independently, whenever the logical clock advances past
        `end_date`, an agreement in `DRAFT` or `ACTIVE` auto-transitions to
        `EXPIRED`."

        Design: Corner/state_machines/sm_agreement_auto_expires_on_clock_advance
        """
        set_clock("2026-05-01T00:00:00Z")
        setup_profile_only()
        ag = validate_success(
            api.create_mutual_aid_agreement(
                create_mutual_aid_agreement_payload(
                    partner_airport_code="KCTY", max_alert_level="ALERT_2",
                    start_date="2026-01-01", end_date="2026-05-10",
                ),
                AM,
            ),
            expected_status=201,
        )
        api.activate_mutual_aid_agreement(ag["id"], AM)
        set_clock("2026-05-11T00:00:00Z")
        ag_after = get_success_data(api.get_mutual_aid_agreement(ag["id"], AM))
        assert ag_after["status"] == "EXPIRED"


class TestAgreementCoverageGate:
    def test_request_under_draft_agreement_rejected(self, api):
        """PRD §3.9: "The named agreement must currently be `ACTIVE`;
        otherwise `ERR_AGREEMENT_NOT_ACTIVE`."

        Design: Corner/errors/err_operations_misc_error_battery
        """
        setup_compliant_index_c_airport()
        # Create DRAFT agreement (not activated)
        ag = validate_success(
            api.create_mutual_aid_agreement(
                create_mutual_aid_agreement_payload(
                    partner_airport_code="KCTY", max_alert_level="ALERT_1",
                    start_date="2026-01-01", end_date="2026-12-31",
                ),
                AM,
            ),
            expected_status=201,
        )
        inc = validate_success(
            api.create_incident(
                create_incident_payload(alert_level="ALERT_2",
                                        location="Runway 09L"),
                AC,
            ),
            expected_status=201,
        )
        resp = api.create_mutual_aid_request(
            inc["id"],
            create_mutual_aid_request_payload(ag["id"], units_requested=1),
            AC,
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)


class TestAlertLevelEscalation:
    def test_alert_level_deescalation_rejected(self, api):
        """PRD §3.8: "the new `alert_level` must be strictly higher than the
        current value — a same-level or downgrade patch is rejected with
        `ERR_ALERT_LEVEL_NOT_ESCALATION`."

        Design: Corner/errors/err_operations_misc_error_battery
        """
        setup_compliant_index_c_airport()
        inc = validate_success(
            api.create_incident(
                create_incident_payload(alert_level="ALERT_2",
                                        location="Runway 09L"),
                AC,
            ),
            expected_status=201,
        )
        resp = api.patch_incident_alert_level(
            inc["id"], {"alert_level": "ALERT_1"}, AC,
        )
        validate_error(resp, ApiErrorId.ERR_ALERT_LEVEL_NOT_ESCALATION)

    def test_close_on_reported_incident_rejected(self, api):
        """PRD §3.8: "A close attempt on a non-`CONTROLLED` incident is
        rejected with `ERR_INCIDENT_NOT_CONTROLLED`."

        Design: Corner/errors/err_operations_misc_error_battery
        """
        setup_compliant_index_c_airport()
        inc = validate_success(
            api.create_incident(
                create_incident_payload(alert_level="ALERT_1",
                                        location="Runway 09L"),
                AC,
            ),
            expected_status=201,
        )
        resp = api.close_incident(inc["id"], AC)
        validate_error(resp, ApiErrorId.ERR_INCIDENT_NOT_CONTROLLED)


class TestAgreementWindowInvalid:
    def test_inverted_window_rejected(self, api):
        """PRD §3.9: "`start_date` must be at-or-before `end_date`, otherwise
        `ERR_AGREEMENT_WINDOW_INVALID`."

        Design: Corner/errors/err_operations_misc_error_battery
        """
        setup_profile_only()
        resp = api.create_mutual_aid_agreement(
            create_mutual_aid_agreement_payload(
                partner_airport_code="KBAD", max_alert_level="ALERT_1",
                start_date="2026-12-31", end_date="2026-01-01",
            ),
            AM,
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_WINDOW_INVALID)


class TestRespondIndexSafety:
    def test_respond_with_degraded_index_rejected(self, api):
        """PRD §3.8: "The incident must currently be `REPORTED` (otherwise
        `ERR_INCIDENT_NOT_OPEN`), and the profile's `effective_index` must be
        at-or-above the alert level's required index: `A` for `ALERT_1`, `B`
        for `ALERT_2`, `C` for `ALERT_3`. A profile below that floor is
        rejected with `ERR_INDEX_INSUFFICIENT_FOR_ALERT`."

        Design: Corner/errors/err_operations_misc_error_battery
        """
        ctx = setup_compliant_index_c_airport()
        inc = validate_success(
            api.create_incident(
                create_incident_payload(alert_level="ALERT_2",
                                        location="Runway 09L"),
                AC,
            ),
            expected_status=201,
        )
        # Drop equipment to A via OOS on RED-1
        open_oos_event(ctx["veh1"]["id"], "Pump")
        resp = api.respond_incident(inc["id"], AC)
        validate_error(resp, ApiErrorId.ERR_INDEX_INSUFFICIENT_FOR_ALERT)


class TestRespondStateBeatsSafety:
    def test_respond_controlled_incident_yields_state_error(self, api):
        """PRD §2.10: "(4) state-machine preconditions (the various
        `ERR_*_NOT_*` 409 errors); (5) safety and regulatory gates (the 422
        family — `ERR_INDEX_INSUFFICIENT_FOR_ALERT`, ...)"

        Design: Difficulty/priority_pair_validation_conflict/pp_respond_state_beats_index_safety
        """
        ctx = setup_compliant_index_c_airport()
        inc = validate_success(
            api.create_incident(
                create_incident_payload(alert_level="ALERT_3",
                                        location="Runway 09L departure end"),
                AC,
            ),
            expected_status=201,
        )
        api.respond_incident(inc["id"], AC)
        api.control_incident(inc["id"], AC)
        # Drop effective index to A so the safety gate is also violated
        open_oos_event(ctx["veh1"]["id"], "Crash tender engine failure")
        resp = api.respond_incident(inc["id"], AC)
        # State (priority 4) must beat safety (priority 5)
        validate_error(resp, ApiErrorId.ERR_INCIDENT_NOT_OPEN)

    def test_respond_controlled_incident_does_not_leak_safety_error(self, api):
        """PRD §2.10: "When multiple rules could fire on the same request,
        the system applies them in priority order so that earlier errors mask
        later ones."

        Design: Difficulty/priority_pair_validation_conflict/pp_respond_state_beats_index_safety
        """
        ctx = setup_compliant_index_c_airport()
        inc = validate_success(
            api.create_incident(
                create_incident_payload(alert_level="ALERT_3",
                                        location="Runway 09L"),
                AC,
            ),
            expected_status=201,
        )
        api.respond_incident(inc["id"], AC)
        api.control_incident(inc["id"], AC)
        open_oos_event(ctx["veh1"]["id"], "Engine failure")
        resp = api.respond_incident(inc["id"], AC)
        # Assert specifically that the safety error does NOT surface
        body = resp.json()
        assert body["data"]["error_id"] == "ERR_INCIDENT_NOT_OPEN"
        assert body["data"]["error_id"] != "ERR_INDEX_INSUFFICIENT_FOR_ALERT"
