"""Incident escalation side effects, safety holds, segregation of duties, and
the after-action report workflow (PRD §2.9, §3.7, §3.8)."""
from test_helpers import (
    ApiErrorId,
    assert_after_action_report,
    get_episode,
    get_site_activation,
    get_stay,
    get_success_data,
    list_stays,
    make_eoc_manager_headers,
    make_site_lead_headers,
    report_incident,
    resolve_incident,
    setup_deactivated_episode_with_aar,
    setup_deactivated_episode_with_open_incident,
    setup_deactivating_episode_with_aar,
    setup_ejection_scene,
    setup_medical_hold_at_full_site,
    setup_opening_site_with_incidents,
    submit_aar,
    validate_error,
    validate_success,
    INTAKE_HEADERS,
)


class TestBehavioralEjection:
    def test_behavioral_escalation_ejects_checked_in_guest(self, api):
        """PRD §3.7: "Escalating a `BEHAVIORAL` incident of severity 3, when
        the linked guest currently has a `CHECKED_IN` stay at that activation,
        ejects the guest: the stay moves to `CHECKED_OUT` with
        `checked_out_at` stamped, its final bed nights computed, and its bed,
        pet and locker usage released, exactly as a normal check-out."

        Design: Difficulty/transitive_cascade/behavioral_escalation_ejection_frees_bed
        """
        ws = setup_ejection_scene()
        resp = api.escalate_incident(ws["incident"]["id"], ws["lead2_headers"])
        assert validate_success(resp, 200)["status"] == "ESCALATED"

        stay = get_stay(ws["stay_occupant"]["id"])
        assert stay["status"] == "CHECKED_OUT"
        assert stay["checked_out_at"] is not None

    def test_behavioral_escalation_ejection_frees_bed(self, api):
        """PRD §3.7: "Escalating a `BEHAVIORAL` incident of severity 3, when
        the linked guest currently has a `CHECKED_IN` stay at that activation,
        ejects the guest: the stay moves to `CHECKED_OUT` with
        `checked_out_at` stamped, its final bed nights computed, and its bed,
        pet and locker usage released, exactly as a normal check-out."

        Design: Difficulty/transitive_cascade/behavioral_escalation_ejection_frees_bed
        """
        ws = setup_ejection_scene()
        sa_id = ws["site_activation"]["id"]
        assert get_site_activation(sa_id)["beds_free"] == 0

        validate_success(
            api.escalate_incident(ws["incident"]["id"], ws["lead2_headers"]),
            200)

        # The ejection released the only bed; the waiting guest is admitted.
        assert get_site_activation(sa_id)["beds_free"] == 1
        resp = api.create_stay(sa_id, {"guest_id": ws["guests"][1]["id"]},
                               INTAKE_HEADERS)
        assert validate_success(resp, 201)["status"] == "CHECKED_IN"


class TestMedicalHold:
    def test_medical_hold_outranks_no_bed_on_intake(self, api):
        """PRD §2.9: "Sixth are safety gates: an active guest medical hold and
        a missing shift skill." and "Ninth and last are the capacity pools,
        always checked in the pinned order beds, then pets, then lockers." —
        the safety gate is evaluated before the capacity pools.
        PRD §3.7: "While a hold is active it blocks three operations —
        walk-in intake, reservation check-in and transfer — each rejected with
        `ERR_GUEST_MEDICAL_HOLD`."

        Design: Difficulty/priority_pair_validation_conflict/medical_hold_outranks_no_bed_on_intake
        """
        # beds_free == 0 AND the arriving guest has an active medical hold:
        # both rules are violated; the safety gate must answer.
        ws = setup_medical_hold_at_full_site()
        held_guest = ws["guests"][1]
        resp = api.create_stay(ws["site_activation"]["id"],
                               {"guest_id": held_guest["id"]}, INTAKE_HEADERS)
        validate_error(resp, ApiErrorId.ERR_GUEST_MEDICAL_HOLD,
                       expected_status=409)

    def test_medical_hold_intake_creates_no_stay(self, api):
        """PRD §3.7: "While a hold is active it blocks three operations —
        walk-in intake, reservation check-in and transfer — each rejected with
        `ERR_GUEST_MEDICAL_HOLD`."

        Design: Difficulty/priority_pair_validation_conflict/medical_hold_outranks_no_bed_on_intake
        """
        ws = setup_medical_hold_at_full_site()
        held_guest = ws["guests"][1]
        validate_error(
            api.create_stay(ws["site_activation"]["id"],
                            {"guest_id": held_guest["id"]}, INTAKE_HEADERS),
            ApiErrorId.ERR_GUEST_MEDICAL_HOLD)
        assert list_stays({"guest_id": held_guest["id"]}) == []


class TestIncidentRoles:
    def test_incident_kind_role_mismatch_returns_forbidden(self, api):
        """PRD §2.1: "For incident escalation and resolution the caller's role
        must additionally match the incident's `kind` — a `MEDICAL` incident
        is handled only by a `MedicalResponder`, a `BEHAVIORAL` incident only
        by a `SiteLead` — and a role that mismatches the kind is rejected with
        `ERR_FORBIDDEN` even though that role may appear on the endpoint's
        authorized list."

        Design: Corner/validations/incident_kind_role_mismatch_returns_forbidden
        """
        ws = setup_opening_site_with_incidents()
        # MedicalResponder touching a BEHAVIORAL incident.
        resp_b = api.escalate_incident(ws["incident_behavioral"]["id"],
                                       ws["medic_headers"])
        validate_error(resp_b, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
        # SiteLead touching a MEDICAL incident.
        resp_m = api.escalate_incident(ws["incident_medical"]["id"],
                                       ws["lead1_headers"])
        validate_error(resp_m, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

        assert (get_success_data(api.get_incident(
            ws["incident_behavioral"]["id"], ws["eoc_headers"]))["status"]
            == "REPORTED")
        assert (get_success_data(api.get_incident(
            ws["incident_medical"]["id"], ws["eoc_headers"]))["status"]
            == "REPORTED")

    def test_incident_resolver_equals_reporter_segregation_rejected(self, api):
        """PRD §3.7: "The resolver must differ from the reporter — the
        caller's `X-User-ID` may not equal `reporter_user_id`, else
        `ERR_SEGREGATION_OF_DUTIES` — and resolution captures the resolver in
        `resolved_by_user_id` together with a free-text `resolution_note`."

        Design: Corner/validations/incident_resolver_equals_reporter_segregation_rejected
        """
        ws = setup_opening_site_with_incidents()
        # Report as lead1 (recorded in reporter_user_id), then attempt to
        # resolve with the same X-User-ID under the correct kind-role.
        incident = report_incident(
            ws["site_activation"]["id"], "BEHAVIORAL", 1,
            reporter_headers=make_site_lead_headers(ws["lead1"]["id"]))
        same_user = api.resolve_incident(
            incident["id"], {"resolution_note": "self-resolution attempt"},
            make_site_lead_headers(ws["lead1"]["id"]))
        validate_error(same_user, ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
                       expected_status=409)

        other_user = api.resolve_incident(
            incident["id"],
            {"resolution_note": "independent review: resolved"},
            make_site_lead_headers(ws["lead2"]["id"]))
        data = validate_success(other_user, 200)
        assert data["status"] == "RESOLVED"
        assert data["resolved_by_user_id"] == ws["lead2"]["id"]


class TestAfterActionReports:
    def test_aar_submit_blocked_by_open_incident(self, api):
        """PRD §3.8: "Submission moves the report from `DRAFT` to `SUBMITTED`
        and is gated on a clean ledger: every incident of the episode must be
        `RESOLVED`, else `ERR_OPEN_INCIDENTS_REMAIN`, and every site
        activation must be `CLOSED`, else `ERR_SITES_NOT_CLOSED`."
        PRD §3.8: "At creation the report stands in `DRAFT` and its aggregates
        are pinned once and for all: `total_unique_guests` counts the distinct
        `guest_id` values across all of the episode's stays regardless of
        status; `total_bed_nights` sums `bed_nights_final` across all of the
        episode's stays, using the final variant only".

        Design: Difficulty/cross_entity_state_dependency/aar_submit_blocked_by_open_incident
        """
        ws = setup_deactivated_episode_with_open_incident()
        aar = ws["aar"]
        assert_after_action_report(aar)
        assert aar["status"] == "DRAFT"
        # Aggregates pinned at creation: the only guest's 20:00-23:00 stay
        # crossed no midnight boundary; one severity-1 incident exists.
        assert aar["total_unique_guests"] == 1
        assert aar["total_bed_nights"] == 0
        assert aar["incidents_by_severity"] == {"1": 1, "2": 0, "3": 0}

        resp = api.submit_after_action_report(aar["id"], ws["eoc_headers"])
        validate_error(resp, ApiErrorId.ERR_OPEN_INCIDENTS_REMAIN,
                       expected_status=409)

    def test_aar_submit_succeeds_after_incident_resolved(self, api):
        """PRD §3.8: "Submission moves the report from `DRAFT` to `SUBMITTED`
        and is gated on a clean ledger: every incident of the episode must be
        `RESOLVED`, else `ERR_OPEN_INCIDENTS_REMAIN`, and every site
        activation must be `CLOSED`, else `ERR_SITES_NOT_CLOSED`."

        Design: Difficulty/cross_entity_state_dependency/aar_submit_blocked_by_open_incident
        """
        ws = setup_deactivated_episode_with_open_incident()
        validate_error(
            api.submit_after_action_report(ws["aar"]["id"], ws["eoc_headers"]),
            ApiErrorId.ERR_OPEN_INCIDENTS_REMAIN)

        # A different user (SiteLead lead2, not the reporter) resolves the
        # BEHAVIORAL incident.
        resolve_incident(ws["incident"]["id"], "guest calmed; no injury",
                         ws["lead2_headers"])
        resp = api.submit_after_action_report(ws["aar"]["id"],
                                              ws["eoc_headers"])
        assert validate_success(resp, 200)["status"] == "SUBMITTED"

    def test_aar_lifecycle_duplicate_and_activator_approval_segregation(
            self, api):
        """PRD §3.8: "each episode has at most one report, a duplicate
        creation likewise rejected with `ERR_INVALID_STATE`."
        PRD §3.8: "Approval moves the report from `SUBMITTED` to `APPROVED`
        under the final segregation of duties: the approver's `X-User-ID` must
        differ from the episode's `activated_by_user_id`, else
        `ERR_SEGREGATION_OF_DUTIES`. Approval stamps `approved_by_user_id`
        and, as its terminal side effect, closes the episode itself from
        `DEACTIVATED` to `CLOSED`."

        Design: Corner/validations/aar_lifecycle_duplicate_and_activator_approval_segregation
        """
        ws = setup_deactivated_episode_with_aar()
        ep_id = ws["episode"]["id"]
        aar_id = ws["aar"]["id"]

        dup = api.create_after_action_report(ep_id, ws["eoc_headers"])
        validate_error(dup, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        submit_aar(aar_id)

        # The episode was activated by eoc-activator-1, who may not approve.
        by_activator = api.approve_after_action_report(
            aar_id, make_eoc_manager_headers("eoc-activator-1"))
        validate_error(by_activator, ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
                       expected_status=409)

        by_other = api.approve_after_action_report(
            aar_id, make_eoc_manager_headers("eoc-approver-2"))
        data = validate_success(by_other, 200)
        assert data["status"] == "APPROVED"
        assert data["approved_by_user_id"] == "eoc-approver-2"
        assert get_episode(ep_id)["status"] == "CLOSED"

    def test_aar_submit_while_sites_not_closed_rejected(self, api):
        """PRD §3.8: "An `EOCManager` creates it while the episode is
        `DEACTIVATING` or `DEACTIVATED` — drafting during the drain is
        deliberate — and creation in any other episode state is rejected with
        `ERR_INVALID_STATE`" and "every site activation must be `CLOSED`, else
        `ERR_SITES_NOT_CLOSED`."

        Design: Corner/validations/aar_submit_while_sites_not_closed_rejected
        """
        ws = setup_deactivating_episode_with_aar()
        assert ws["aar"]["status"] == "DRAFT"
        resp = api.submit_after_action_report(ws["aar"]["id"],
                                              ws["eoc_headers"])
        validate_error(resp, ApiErrorId.ERR_SITES_NOT_CLOSED,
                       expected_status=409)
