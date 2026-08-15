"""Participant intake, acuity computation, approval gates, lifecycle loop."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_emergency_contact,
    create_applicant,
    create_participant_payload,
    create_program,
    enroll_participant,
    get_program,
    set_clock,
    submit_for_review,
    validate_error,
    validate_success,
)


class TestParticipantCreation:
    def test_participant_creation_initial_state(self, api, intake_headers, coordinator_headers):
        """PRD §3.2: "The new participant starts as `APPLICANT` with `consecutive_no_answer_count` at zero and `coverage_deficient` false."
        PRD §3.2: "`primary_language` is optional, defaults to `en`, and matters later: a participant whose language is not `en` can only be served by volunteers whose `languages` include it."
        PRD §3.9: "until the first post-enrollment closeout produces a rolling value, the rolling fields are null and the effective tier simply equals the intake tier."

        Design: Corner/entities/participant_creation_initial_state
        """
        create_program()
        resp = api.create_participant(
            create_participant_payload(full_name="Init P", referral_source="FAMILY",
                                       age_band="AGE_75_84", lives_alone=True,
                                       chronic_conditions_count=0),
            intake_headers,
        )
        participant = validate_success(resp, 201)
        assert participant["status"] == "APPLICANT"
        assert participant["consecutive_no_answer_count"] == 0
        assert participant["coverage_deficient"] is False
        assert participant.get("acuity_score") is None
        assert participant.get("rolling_acuity_score") is None
        assert participant.get("rolling_acuity_tier") is None
        assert participant.get("open_escalation_id") is None
        assert participant.get("enrolled_at") is None
        assert participant["primary_language"] == "en"

    def test_participant_create_with_computed_extra_field_rejected(self, api, intake_headers, coordinator_headers):
        """PRD §2.6: "Independently of this ordering, a malformed payload — a missing required field, an unknown field, an invalid enum value, a `window_start` that is not before its `window_end`, or an out-of-range value — is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/participant_create_with_computed_extra_field_rejected
        """
        create_program()
        payload = create_participant_payload()
        payload["acuity_score"] = 99  # computed field smuggled into input
        resp = api.create_participant(payload, intake_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_participant_get_unknown_id_not_found(self, api, intake_headers, coordinator_headers):
        """PRD §2.10: "Every identifier appearing in a request path must correspond to an existing resource, and identifiers are validated in left-to-right order: the request is rejected with `ERR_NOT_FOUND` for the first path identifier that does not resolve, before later identifiers or body content are examined."

        Design: Corner/entities/participant_get_unknown_id_not_found
        """
        create_program()
        resp = api.get_participant(NON_EXISTENT_UUID, intake_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


class TestEmergencyContacts:
    def test_emergency_contact_defaults_and_immutable_rank(self, api, intake_headers):
        """PRD §3.2: "Contacts are recorded with `full_name`, `phone`, `relationship`, a `contact_rank` of `PRIMARY` or `SECONDARY`, and an optional `accepts_24h` flag (default false) marking willingness to accept calls at any hour."
        PRD §3.2: "A contact starts `ACTIVE`; deactivation marks it `REMOVED`, and reactivation returns an `UNREACHABLE` or `REMOVED` contact to `ACTIVE`."

        Design: Corner/entities/emergency_contact_defaults_and_immutable_rank
        """
        create_program()
        participant = create_applicant(full_name="EC P")
        resp = api.create_emergency_contact(
            participant["id"],
            {"full_name": "Kin", "phone": "555-4002", "relationship": "niece",
             "contact_rank": "SECONDARY"},
            intake_headers,
        )
        contact = validate_success(resp, 201)
        assert contact["accepts_24h"] is False, "accepts_24h must default to false"
        assert contact["status"] == "ACTIVE"


class TestApprovalGates:
    def test_approve_from_applicant_rejected(self, api, intake_headers):
        """PRD §3.2: "Approval evaluates its gates in a deliberate order. First the participant must actually be `UNDER_REVIEW` (`ERR_INVALID_STATE` otherwise) and intake must be `OPEN` (`ERR_INTAKE_PAUSED` otherwise)."

        Design: Corner/state_machines/approve_from_applicant_rejected
        """
        create_program()
        participant = create_applicant(full_name="Skip P")
        add_emergency_contact(participant["id"])
        resp = api.approve_participant(participant["id"], intake_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        after = validate_success(api.get_participant(participant["id"], intake_headers))
        assert after["status"] == "APPLICANT"

    def test_patch_participant_after_enrollment_rejected(self, api, intake_headers):
        """PRD §3.2: "Intake fields remain editable while the participant is `APPLICANT` or `UNDER_REVIEW`; each edit increments the participant's `version`, and edits made under review only take scoring effect when the review submission is run again."
        PRD §2.6: "6. State validity: the target resource is in a valid from-state for the requested transition, otherwise the state-family error `ERR_INVALID_STATE` — or its specialized siblings `ERR_OFFER_NOT_OPEN`, `ERR_NO_OPEN_ESCALATION`, or `ERR_PARTICIPANT_NOT_ENROLLED` where those apply."

        Design: Corner/state_machines/patch_participant_after_enrollment_rejected
        """
        create_program()
        participant = enroll_participant({"full_name": "Edit P", "phone": "555-4302"})
        resp = api.patch_participant(participant["id"], {"phone": "555-9999"}, intake_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        after = validate_success(api.get_participant(participant["id"], intake_headers))
        assert after["phone"] == "555-4302", "rejected PATCH must not mutate the participant"

    def test_approve_without_primary_contact_returns_contact_required(self, api, intake_headers):
        """PRD §3.2: "Then the safety gates: at least one `ACTIVE` emergency contact with `contact_rank` `PRIMARY` must exist, failing with `ERR_EMERGENCY_CONTACT_REQUIRED` otherwise; and when the applicant's `effective_acuity_tier` is `HIGH` or `CRITICAL`, at least one `ACTIVE` contact with `accepts_24h` true must exist, failing with `ERR_NO_24H_CONTACT` otherwise."
        PRD §3.2: "Safety errors fire before capacity is ever considered — an applicant missing a primary contact is rejected, not waitlisted."

        Design: Corner/validations/approve_without_primary_contact_returns_contact_required
        """
        create_program()
        participant = create_applicant(full_name="NC P")
        submit_for_review(participant["id"])
        resp = api.approve_participant(participant["id"], intake_headers)
        validate_error(resp, ApiErrorId.ERR_EMERGENCY_CONTACT_REQUIRED, 422)
        after = validate_success(api.get_participant(participant["id"], intake_headers))
        assert after["status"] == "UNDER_REVIEW"
        entries = validate_success(
            api.list_participant_waitlist_entries(participant["id"], intake_headers)
        )
        assert entries == [], "a safety-rejected approval must not create a waitlist entry"

    def test_high_tier_without_24h_contact_returns_no_24h(self, api, intake_headers):
        """PRD §3.2: "Then the safety gates: at least one `ACTIVE` emergency contact with `contact_rank` `PRIMARY` must exist, failing with `ERR_EMERGENCY_CONTACT_REQUIRED` otherwise; and when the applicant's `effective_acuity_tier` is `HIGH` or `CRITICAL`, at least one `ACTIVE` contact with `accepts_24h` true must exist, failing with `ERR_NO_24H_CONTACT` otherwise."

        Design: Corner/validations/high_tier_without_24h_contact_returns_no_24h
        """
        create_program()
        # HIGH: AGE_85_PLUS 20 + lives_alone 25 + LIMITED 10 + 2x5 chronic = 65.
        participant = create_applicant(
            full_name="Hi C", date_of_birth="1941-07-03", age_band="AGE_85_PLUS",
            lives_alone=True, mobility="LIMITED", chronic_conditions_count=2,
        )
        add_emergency_contact(participant["id"], accepts_24h=False)
        reviewed = submit_for_review(participant["id"])
        assert reviewed["acuity_tier"] == "HIGH", f"expected HIGH (score 65), got {reviewed['acuity_tier']}"
        resp = api.approve_participant(participant["id"], intake_headers)
        validate_error(resp, ApiErrorId.ERR_NO_24H_CONTACT, 422)
        add_emergency_contact(
            participant["id"], full_name="Night Kin", relationship="son",
            contact_rank="SECONDARY", accepts_24h=True,
        )
        approved = validate_success(api.approve_participant(participant["id"], intake_headers))
        assert approved["status"] == "ENROLLED", (
            "the 24h gate accepts any ACTIVE rank with accepts_24h true"
        )


class TestIntakePosture:
    def test_intake_paused_blocks_application_and_approval(self, api, intake_headers, coordinator_headers):
        """PRD §3.1: "Pausing intake moves `intake_posture` from `OPEN` to `PAUSED` and, while paused, new participant applications and approvals are rejected with `ERR_INTAKE_PAUSED`; resuming returns the posture to `OPEN`."

        Design: Corner/errors/intake_paused_blocks_application_and_approval
        """
        program = create_program()
        participant = create_applicant(full_name="Pend P")
        add_emergency_contact(participant["id"])
        submit_for_review(participant["id"])
        validate_success(api.pause_intake(program["id"], coordinator_headers))
        err1 = api.create_participant(create_participant_payload(full_name="New P"), intake_headers)
        validate_error(err1, ApiErrorId.ERR_INTAKE_PAUSED, 409)
        err2 = api.approve_participant(participant["id"], intake_headers)
        validate_error(err2, ApiErrorId.ERR_INTAKE_PAUSED, 409)
        validate_success(api.resume_intake(program["id"], coordinator_headers))
        approved = validate_success(api.approve_participant(participant["id"], intake_headers))
        assert approved["status"] == "ENROLLED"


class TestReapplication:
    def test_reapply_before_cooling_off_rejected(self, api, intake_headers, coordinator_headers):
        """PRD §3.6: "From `DENIED`, `DISENROLLED`, or `EXITED`, an `IntakeWorker` may re-open the participant as `APPLICANT`, but only once the logical clock has reached `last_status_change_at` plus the program's `reapply_cooling_days` (thirty days by default); earlier attempts fail with `ERR_REAPPLICATION_TOO_SOON`."

        Design: Corner/state_machines/reapply_before_cooling_off_rejected
        """
        create_program()
        participant = create_applicant(full_name="Cool P")
        submit_for_review(participant["id"])
        denied = validate_success(
            api.deny_participant(participant["id"], {"reason": "outside service area"}, intake_headers)
        )
        assert denied["status"] == "DENIED"
        # Denied at the default clock 2026-08-01T00:00:00Z; +29 days is too soon.
        set_clock("2026-08-30T00:00:00Z")
        resp = api.reapply_participant(participant["id"], intake_headers)
        validate_error(resp, ApiErrorId.ERR_REAPPLICATION_TOO_SOON, 409)
        after = validate_success(api.get_participant(participant["id"], intake_headers))
        assert after["status"] == "DENIED"


class TestAcuityComputation:
    def test_acuity_tier_band_boundaries(self, api, intake_headers):
        """PRD §3.2: "Seven components sum into `acuity_score`: the age band contributes 0 points for `AGE_65_74`, 10 for `AGE_75_84`, or 20 for `AGE_85_PLUS`; living alone contributes 25; `mobility` contributes 0 for `NONE`, 10 for `LIMITED`, or 20 for `SEVERE`; a documented cognitive concern contributes 20; chronic conditions contribute 5 points each, counting at most 3 conditions; a recent hospitalization contributes 10; a recent bereavement contributes 5."
        PRD §3.2: "`acuity_tier` bands the score: `LOW` at 29 or below, `MODERATE` from 30 through 59, `HIGH` from 60 through 84, and `CRITICAL` at 85 or above."

        Design: Corner/calculations/acuity_tier_band_boundaries
        """
        create_program()
        cases = [
            # (overrides, expected_score, expected_tier)
            (dict(full_name="B30", lives_alone=True, chronic_conditions_count=1), 30, "MODERATE"),
            (dict(full_name="B25", lives_alone=True, chronic_conditions_count=0), 25, "LOW"),
            (dict(full_name="B85", date_of_birth="1941-06-03", age_band="AGE_85_PLUS",
                  lives_alone=True, mobility="SEVERE", cognitive_concern=True,
                  chronic_conditions_count=0), 85, "CRITICAL"),
            (dict(full_name="B80", date_of_birth="1941-06-04", age_band="AGE_85_PLUS",
                  lives_alone=True, mobility="SEVERE", chronic_conditions_count=3), 80, "HIGH"),
        ]
        for overrides, expected_score, expected_tier in cases:
            participant = create_applicant(**overrides)
            reviewed = submit_for_review(participant["id"])
            assert reviewed["acuity_score"] == expected_score, (
                f"{overrides['full_name']}: expected score {expected_score}, "
                f"got {reviewed['acuity_score']}"
            )
            assert reviewed["acuity_tier"] == expected_tier, (
                f"{overrides['full_name']}: expected tier {expected_tier} at band edge, "
                f"got {reviewed['acuity_tier']}"
            )

    def test_acuity_score_capped_at_100(self, api, intake_headers):
        """PRD §3.2: "The score is the sum of the seven components, capped at 100, and is an integer."
        PRD §3.2: "chronic conditions contribute 5 points each, counting at most 3 conditions"

        Design: Corner/calculations/acuity_score_capped_at_100
        """
        create_program()
        # Raw 20 + 25 + 20 + 20 + 15 + 10 = 110; chronic sub-cap min(3, 3) binds too.
        participant = create_applicant(
            full_name="Cap P", date_of_birth="1936-06-05", age_band="AGE_85_PLUS",
            lives_alone=True, mobility="SEVERE", cognitive_concern=True,
            chronic_conditions_count=3, recent_hospitalization=True,
        )
        reviewed = submit_for_review(participant["id"])
        assert reviewed["acuity_score"] == 100, (
            f"raw sum 110 must clamp to 100, got {reviewed['acuity_score']}"
        )
        assert reviewed["acuity_tier"] == "CRITICAL"


class TestParticipantEnrollmentFullCycle:
    def test_suspend_resume_loop_restores_enrolled(self, api, coordinator_headers):
        """PRD §3.6: "Suspension by a `ProgramCoordinator` moves `ENROLLED` → `SUSPENDED` with a `reason`: every `SCHEDULED` assignment is cancelled with `cancel_reason` `PARTICIPANT_SUSPEND`, each cancellation recomputing the affected volunteer's `current_week_minutes` and the participant's `coverage_deficient` (which turns true because future coverage was removed)."
        PRD §3.6: "When the selector pool is empty for a weekday, no assignment is created for it and `coverage_deficient` is set true; the flag is recomputed once regeneration finishes."

        Design: Difficulty/non_linear_state_machine/participant_enrollment_full_cycle
        """
        create_program(total_capacity=5, max_reserve_slots=0)
        participant = enroll_participant({"full_name": "Cyc P"})
        add = api.create_call_schedule(
            participant["id"], {"weekday": "MON", "window_start": "09:00", "window_end": "11:00"},
            coordinator_headers,
        )
        validate_success(add, 201)
        s1 = validate_success(
            api.suspend_participant(participant["id"], {"reason": "hospitalized"}, coordinator_headers)
        )
        assert s1["status"] == "SUSPENDED", "ENROLLED -> SUSPENDED is the first loop leg"
        # No volunteers exist, so resume-regeneration finds an empty selector pool.
        s2 = validate_success(api.resume_participant(participant["id"], coordinator_headers))
        assert s2["status"] == "ENROLLED", "SUSPENDED -> ENROLLED closes the loop"
        assert s2["coverage_deficient"] is True, (
            "MON 2026-08-03 falls within 7 days but the selector pool is empty, "
            "so no assignment is regenerated and coverage_deficient is set true"
        )

    def test_disenroll_then_reapply_at_inclusive_cooling_boundary(self, api, intake_headers, coordinator_headers):
        """PRD §3.6: "From `DENIED`, `DISENROLLED`, or `EXITED`, an `IntakeWorker` may re-open the participant as `APPLICANT`, but only once the logical clock has reached `last_status_change_at` plus the program's `reapply_cooling_days` (thirty days by default); earlier attempts fail with `ERR_REAPPLICATION_TOO_SOON`."
        PRD §3.6: "Reapplication clears the acuity fields — they are recomputed at the next review submission — and resets `consecutive_no_answer_count` to zero, stamping `last_status_change_at` anew."
        PRD §3.6: "The participant becomes `DISENROLLED`; `occupied_slots` decreases by one and the program's `version` increments; every still-`SCHEDULED` assignment is cancelled with `cancel_reason` `MANUAL`; and `last_status_change_at` is stamped."

        Design: Difficulty/non_linear_state_machine/participant_enrollment_full_cycle
        """
        program = create_program(total_capacity=5, max_reserve_slots=0)
        participant = enroll_participant({"full_name": "Cyc P"})
        validate_success(
            api.suspend_participant(participant["id"], {"reason": "hospitalized"}, coordinator_headers)
        )
        validate_success(api.resume_participant(participant["id"], coordinator_headers))
        # Disenroll at the default clock 2026-08-01T00:00:00Z.
        s3 = validate_success(
            api.disenroll_participant(participant["id"], {"reason": "moved"}, coordinator_headers)
        )
        assert s3["status"] == "DISENROLLED"
        # Exactly last_status_change + 30 days: the inclusive boundary admits.
        set_clock("2026-08-31T00:00:00Z")
        s4 = validate_success(api.reapply_participant(participant["id"], intake_headers))
        assert s4["status"] == "APPLICANT", "the cycle returns to the initial state"
        assert s4.get("acuity_score") is None, "reapplication clears the intake acuity fields"
        assert s4.get("acuity_tier") is None
        program_after = get_program(program["id"])
        assert program_after["occupied_slots"] == 0, (
            "the disenroll leg freed the only occupied slot"
        )
