"""Study intake: required fields, enum validation, computed due_at, routing."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_instant_equals,
    assert_study,
    create_active_hospital,
    create_assignment_payload,
    create_routing_policy,
    create_study,
    create_study_payload,
    get_success_data,
    make_hospital_user_headers,
    set_clock,
    setup_assignment_ready,
    setup_routing_ready_hospital,
    validate_error,
    validate_success,
)
from test_helpers.constants import NONEXISTENT_UUID

ADMIN = TEST_USERS["admin_headers"]
DISPATCH = TEST_USERS["dispatch_headers"]


class TestStudyCreationValidation:
    def test_study_create_missing_accession_number_rejected(self, api):
        """PRD section 2.8: "Fourth (priority 4), payload shape: required fields
        must be present, enum fields must hold declared members, and types must
        be correct, else `ERR_VALIDATION` (HTTP 400); unknown or extra payload
        fields are ignored, never rejected."
        PRD section 3.4: "Studies enter the platform when a `ClientHospitalUser`
        registers one with the ordering `hospital_id` (which must equal their own
        `X-User-ID`), an `accession_number`, the `modality`, the
        `body_part_group`, the read `priority`, and an opaque `patient_ref`
        carrying no PHI semantics."

        Design: Corner/entities/study_create_missing_required_field_returns_validation
        """
        hosp = create_active_hospital(name="Hosp Req", state_code="CA")
        payload = {
            "hospital_id": hosp["id"],
            "modality": "CT",
            "body_part_group": "NEURO",
            "priority": "ROUTINE",
            "patient_ref": "P1",
        }
        resp = api.create_study(payload, make_hospital_user_headers(hosp["id"]))
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)

    def test_study_create_with_invalid_enum_modality_rejected(self, api):
        """PRD section 2.8: "Fourth (priority 4), payload shape: required fields
        must be present, enum fields must hold declared members, and types must
        be correct, else `ERR_VALIDATION` (HTTP 400); unknown or extra payload
        fields are ignored, never rejected."
        PRD section 3.2 names the modality members: "drawn from `CT`, `MR`,
        `XR`, `US`, `NM`, and `MG`."

        Design: Corner/entities/study_create_with_invalid_enum_modality
        """
        hosp = create_active_hospital(name="Hosp Enum", state_code="CA")
        payload = create_study_payload(hosp["id"], "ACC-E", modality="PT")
        resp = api.create_study(payload, make_hospital_user_headers(hosp["id"]))
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)


class TestStudyComputedDueAt:
    def test_study_due_at_computed_and_extra_field_ignored(self, api):
        """PRD section 3.4: "At creation the system copies the hospital's
        `state_code` onto the study as its licensure scope, stamps `received_at`
        from the logical clock, and computes `due_at` by adding the hospital's
        configured turnaround minutes for the study's priority to `received_at`
        — an exact instant at second precision."
        PRD section 2.8: "unknown or extra payload fields are ignored, never
        rejected."

        Design: Corner/entities/study_due_at_computed_and_extra_field_ignored
        """
        hosp = create_active_hospital(name="Hosp Due", state_code="CA")
        set_clock("2026-05-10T10:00:00Z")
        payload = create_study_payload(hosp["id"], "ACC-DUE", priority="STAT")
        payload["due_at"] = "1999-01-01T00:00:00Z"  # extra field must be ignored
        data = validate_success(api.create_study(
            payload, make_hospital_user_headers(hosp["id"])), 201)
        # PRD pins the instant values (received_at = logical clock; due_at =
        # received_at + 60 STAT minutes), not the fractional-second rendering.
        assert_instant_equals(data["received_at"], "2026-05-10T10:00:00Z")
        assert_instant_equals(data["due_at"], "2026-05-10T11:00:00Z")
        assert data["due_at"] != "1999-01-01T00:00:00Z"

    def test_study_due_at_uses_hospital_tat_override(self, api):
        """PRD section 3.1: "Turnaround and penalty terms are configured per
        hospital at registration. The `tat_stat_minutes`, `tat_urgent_minutes`,
        and `tat_routine_minutes` fields hold the turnaround targets for `STAT`,
        `URGENT`, and `ROUTINE` studies respectively, defaulting to 60, 240, and
        1440 minutes."
        PRD section 3.4: "...computes `due_at` by adding the hospital's
        configured turnaround minutes for the study's priority to `received_at`
        — an exact instant at second precision."

        Design: Corner/calculations/tat_deadline_uses_hospital_override
        """
        hosp = create_active_hospital(name="Hosp TAT30", state_code="CA",
                                      tat_stat_minutes=30)
        set_clock("2026-05-10T10:00:00Z")
        data = validate_success(api.create_study(
            create_study_payload(hosp["id"], "ACC-T30", priority="STAT"),
            make_hospital_user_headers(hosp["id"])), 201)
        assert_instant_equals(data["due_at"], "2026-05-10T10:30:00Z")


class TestStudyInitialState:
    def test_study_created_with_initial_state_received(self, api):
        """PRD section 3.4: "The study begins in `RECEIVED` status with
        `routing_policy_id` and `assigned_radiologist_id` null,
        `excluded_radiologist_ids` empty, `addendum_count` zero,
        `first_final_signed_at` null, `tat_breached` false, and `breach_minutes`
        zero."

        Design: Corner/state_machines/study_created_with_initial_state_received
        """
        hosp = create_active_hospital(name="Hosp Init", state_code="CA")
        data = validate_success(api.create_study(
            create_study_payload(hosp["id"], "ACC-I"),
            make_hospital_user_headers(hosp["id"])), 201)
        assert_study(data)
        assert data["status"] == "RECEIVED"
        assert data["addendum_count"] == 0
        assert data["tat_breached"] is False
        assert data["routing_policy_id"] is None


class TestRouting:
    def test_route_already_queued_study_rejected(self, api):
        """PRD section 3.4: "Routing is performed by `DispatchOps` and moves
        `RECEIVED → QUEUED`."
        PRD section 2.8: "Sixth (priority 6), state-machine legality: the target
        resource's state must permit the requested transition, else
        `ERR_INVALID_STATE` (HTTP 409)..."

        Design: Corner/state_machines/route_already_queued_study_rejected
        """
        hosp = setup_routing_ready_hospital(name="Hosp RR", clock=None)
        study = create_study(hosp["id"], "ACC-RR")
        validate_success(api.route_study(study["id"], DISPATCH), 200)
        resp = api.route_study(study["id"], DISPATCH)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        assert get_success_data(api.get_study(study["id"], DISPATCH))["status"] == "QUEUED"

    def test_route_without_matching_policy_rejected(self, api):
        """PRD section 3.4: "It resolves the hospital's single `ACTIVE` routing
        policy matching the study's modality, body-part group, and priority; if
        none matches, the route is rejected with `ERR_NO_ROUTING_POLICY`."

        Design: Corner/validations/route_without_matching_policy_rejected
        """
        hosp = setup_routing_ready_hospital(name="Hosp NP", modality="CT",
                                            body_part_group="NEURO",
                                            priority="ROUTINE", clock=None)
        study = create_study(hosp["id"], "ACC-NP", modality="MG",
                             body_part_group="CHEST", priority="ROUTINE")
        resp = api.route_study(study["id"], DISPATCH)
        validate_error(resp, ApiErrorId.ERR_NO_ROUTING_POLICY, 422)
        after = get_success_data(api.get_study(study["id"], DISPATCH))
        assert after["status"] == "RECEIVED"
        assert after["routing_policy_id"] is None


class TestDuplicateAccession:
    def test_duplicate_accession_rejected(self, api):
        """PRD section 3.4: "Registration requires the hospital to be `ACTIVE`
        (else `ERR_HOSPITAL_NOT_ACTIVE`), and the accession number must be
        unique per hospital among studies that have not been `CANCELLED`; a
        duplicate is rejected with `ERR_DUPLICATE_ACCESSION`."

        Design: Corner/validations/duplicate_accession_rejected
        """
        hosp = create_active_hospital(name="Hosp Dup", state_code="CA")
        hdrs = make_hospital_user_headers(hosp["id"])
        validate_success(api.create_study(
            create_study_payload(hosp["id"], "ACC-DUP"), hdrs), 201)
        resp = api.create_study(
            create_study_payload(hosp["id"], "ACC-DUP", modality="MR",
                                 body_part_group="BODY", priority="STAT",
                                 patient_ref="D2"), hdrs)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACCESSION, 409)


class TestAssignmentExistence:
    def test_assignment_create_rejects_unknown_study(self, api):
        """PRD section 2.8: "Third (priority 3), existence: every identifier in
        the path is resolved left to right, and every body-referenced identifier
        — `study_id`, `radiologist_id`, `assignment_id`, `hospital_id`,
        `prelim_report_id`, `final_report_id` — must resolve to an existing row.
        Each missing resource raises its own domain-specific error:
        `ERR_HOSPITAL_NOT_FOUND`, ... `ERR_STUDY_NOT_FOUND`, ... (all HTTP 404)."

        Design: Corner/entities/assignment_create_rejects_unknown_study
        """
        hosp = create_active_hospital(name="Hosp FK", state_code="CA")
        study = create_study(hosp["id"], "ACC-FK")
        resp = api.create_assignment(
            create_assignment_payload(NONEXISTENT_UUID, study["version"]), DISPATCH)
        validate_error(resp, ApiErrorId.ERR_STUDY_NOT_FOUND, 404)


class TestStudyCancellation:
    def test_cancel_cancelled_study_terminal_lockdown(self, api):
        """PRD section 3.6: "Cancellation is the study's terminal exit: from
        `RECEIVED`, `QUEUED`, `ASSIGNED`, or `IN_PROGRESS`, the owning
        `ClientHospitalUser` (or `DispatchOps`) may cancel, moving the study to
        `CANCELLED`. ... an attempt against any impermissible state rejects with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/cancel_cancelled_study_terminal_lockdown
        """
        hosp = create_active_hospital(name="Hosp TL", state_code="CA")
        study = create_study(hosp["id"], "ACC-TL")
        hdrs = make_hospital_user_headers(hosp["id"])
        validate_success(api.cancel_study(study["id"], hdrs), 200)
        resp = api.cancel_study(study["id"], hdrs)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        assert get_success_data(api.get_study(study["id"], DISPATCH))["status"] == "CANCELLED"

    def test_cancel_assigned_study_releases_assignment_and_rvu(self, api):
        """PRD section 3.6: "Cancelling from `ASSIGNED` or `IN_PROGRESS`
        cascades: the active assignment transitions to `RELEASED`, and the
        radiologist's `reserved_rvu` and `stat_active_count` are recomputed to
        return the reservation."

        Design: Corner/state_machines/cancel_assigned_study_releases_assignment_and_rvu
        """
        ctx = setup_assignment_ready(hospital_name="Hosp CX")
        hosp, rad = ctx["hospital"], ctx["radiologist"]
        study = create_study(hosp["id"], "ACC-CX")
        validate_success(api.route_study(study["id"], DISPATCH), 200)
        from test_helpers import assign_study
        asg = assign_study(study["id"], rad["id"])
        assert asg["reserved_rvu"] == 1.5

        data = validate_success(api.cancel_study(
            study["id"], make_hospital_user_headers(hosp["id"])), 200)
        assert data["status"] == "CANCELLED"
        asg_after = get_success_data(api.get_assignment(asg["id"], DISPATCH))
        assert asg_after["status"] == "RELEASED"
        rad_after = get_success_data(api.get_radiologist(rad["id"], ADMIN))
        assert rad_after["reserved_rvu"] == 0.0
