"""Participants, confidentiality agreements, and enrollment cascades (PRD §3.3, §3.4)."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    assert_confidentiality_agreement,
    confirm_enrollment,
    create_agreement_payload,
    get_success_data,
    make_active_group,
    make_active_participant,
    make_confirmed_enrollment,
    make_enrollment,
    make_participant,
    make_program,
    reset_clock,
    sign_agreement,
    validate_error,
    validate_success,
)


class TestAgreementImmutability:
    def test_agreement_carries_no_updated_at_or_version(self, api):
        """PRD §2.5: "Two resources are deliberately lighter:
        ConfidentialityAgreement and EvaluationSurvey are immutable once
        created. They carry only `id` and `created_at`; both `updated_at` and
        `version` are absent from them."

        Design: Corner/entities/confidentiality_agreement_immutable_no_update_endpoint
        """
        reset_clock()
        participant = make_participant(full_name="A")
        agreement = sign_agreement(participant["id"])
        assert_confidentiality_agreement(agreement)
        assert "updated_at" not in agreement
        assert "version" not in agreement
        fetched = validate_success(
            api.get_agreement(participant["id"], agreement["id"], ADMIN))
        assert fetched["id"] == agreement["id"]
        assert "updated_at" not in fetched
        assert "version" not in fetched


class TestAgreementVersioning:
    def test_agreement_version_regression_rejected(self, api):
        """PRD §3.3: "The `agreement_version` must be strictly greater than the
        version of any existing agreement for the same participant, otherwise
        the signature is rejected with `ERR_AGREEMENT_VERSION_REGRESSION`
        (HTTP 409); later versions supersede earlier ones."

        Design: Corner/validations/agreement_version_regression_rejected
        """
        reset_clock()
        participant = make_participant(full_name="A")
        sign_agreement(participant["id"], agreement_version=5)
        resp = api.create_agreement(
            participant["id"],
            create_agreement_payload(
                signed_at="2026-08-01T00:00:00Z",
                expires_at="2027-08-01T00:00:00Z",
                agreement_version=3),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_VERSION_REGRESSION)


class TestParticipantEmailUniqueness:
    def test_duplicate_email_participant_rejected(self, api):
        """PRD §3.3: "the email must be unique among participants, with
        duplicates rejected as `ERR_DUPLICATE_EMAIL`."

        Design: Corner/errors/error_duplicate_email_participant
        """
        reset_clock()
        make_participant(full_name="A", email="x@x.com")
        resp = api.create_participant(
            {"full_name": "B", "email": "x@x.com", "household_size": 2}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_EMAIL)


class TestEnrollmentAgreementDependency:
    def test_revoked_agreement_cancels_enrollment_and_blocks_confirm(self, api):
        """PRD §3.3: "An admin may also revoke a `SIGNED` agreement outright;
        revocation clears `current_agreement_id` when it references the revoked
        agreement and cancels all of that participant's enrollments in
        `RESERVED` or `CONFIRMED`."
        PRD §2.10: "A state-transition attempted from a state that does not
        permit it is always reported as `ERR_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/enrollment_confirm_depends_on_participant_agreement_signed
        """
        reset_clock()
        program = make_program(name="P")
        group = make_active_group(program["id"], modality="VIRTUAL", base_capacity=5)
        participant, agreement = make_active_participant(full_name="A")
        enrollment = make_enrollment(program["id"], group["id"], participant["id"])

        get_success_data(api.revoke_agreement(participant["id"], agreement["id"], ADMIN))

        participant_after = validate_success(api.get_participant(participant["id"], ADMIN))
        assert participant_after.get("current_agreement_id") is None, (
            "revocation must clear current_agreement_id")
        enrollment_after = validate_success(api.get_enrollment(
            program["id"], group["id"], enrollment["id"], ADMIN))
        assert enrollment_after["seat_status"] == "CANCELLED", (
            f"revocation must cancel RESERVED enrollments, got {enrollment_after['seat_status']}")

        version = validate_success(api.get_group(program["id"], group["id"], ADMIN))["version"]
        resp = api.confirm_enrollment(
            program["id"], group["id"], enrollment["id"],
            {"expected_group_version": version}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_agreement_expiry_clears_current_agreement(self, api):
        """PRD §2.4: "a `SIGNED` confidentiality agreement moves to `EXPIRED`
        once the clock passes its `expires_at`"
        PRD §3.3: "if it was the participant's current agreement,
        `current_agreement_id` is cleared and, while the participant's own
        status is unchanged, new enrollment confirmations for them are
        blocked."

        Design: Difficulty/cross_entity_state_dependency/enrollment_confirm_depends_on_participant_agreement_signed
        """
        reset_clock()
        participant = make_participant(full_name="A")
        agreement = sign_agreement(
            participant["id"], expires_at="2026-08-10T00:00:00Z")
        get_success_data(api.activate_participant(participant["id"], ADMIN))

        reset_clock("2026-08-11T00:00:00Z")
        fetched = validate_success(
            api.get_agreement(participant["id"], agreement["id"], ADMIN))
        assert fetched["status"] == "EXPIRED", (
            f"agreement must be EXPIRED once the clock passes expires_at, got {fetched['status']}")
        participant_after = validate_success(api.get_participant(participant["id"], ADMIN))
        assert participant_after.get("current_agreement_id") is None


class TestParticipantSuspensionCascade:
    def _setup_full_group_with_waitlist(self, api):
        """Capacity-1 group: A CONFIRMED in the seat, B WAITLISTED."""
        reset_clock()
        program = make_program(name="P", focus_area="PARENTING")
        group = make_active_group(program["id"], modality="VIRTUAL", base_capacity=1)
        participant_a, _ = make_active_participant(full_name="A")
        participant_b, _ = make_active_participant(full_name="B")
        enrollment_a = make_confirmed_enrollment(
            program["id"], group["id"], participant_a["id"])
        enrollment_b = make_enrollment(program["id"], group["id"], participant_b["id"])
        return program, group, participant_a, participant_b, enrollment_a, enrollment_b

    def test_suspend_cancels_enrollment_and_promotes_waitlist(self, api):
        """PRD §3.3: "Suspending an `ACTIVE` participant moves them to
        `SUSPENDED` and cancels every enrollment of theirs in `RESERVED` or
        `CONFIRMED`, releasing each affected seat and cascading the counter
        adjustments on the affected groups."
        PRD §3.4: "the first entry is promoted back to `RESERVED`, its
        `waitlist_position` is cleared, the group's `active_enrollment_count`
        is incremented because a reserved seat again occupies capacity"

        Design: Difficulty/transitive_cascade/participant_suspend_cascade_releases_enrollments_and_promotes_waitlist
        """
        program, group, pa, pb, ea, eb = self._setup_full_group_with_waitlist(api)
        assert eb["seat_status"] == "WAITLISTED", (
            "B enrolled while the single seat was occupied must be WAITLISTED")

        suspended = validate_success(api.suspend_participant(pa["id"], ADMIN))
        assert suspended["status"] == "SUSPENDED"

        ea_after = validate_success(
            api.get_enrollment(program["id"], group["id"], ea["id"], ADMIN))
        assert ea_after["seat_status"] == "CANCELLED"
        eb_after = validate_success(
            api.get_enrollment(program["id"], group["id"], eb["id"], ADMIN))
        assert eb_after["seat_status"] == "RESERVED", (
            f"waitlist promotion must move B to RESERVED, got {eb_after['seat_status']}")
        assert eb_after.get("waitlist_position") is None, (
            "promotion must clear waitlist_position")
        group_after = validate_success(api.get_group(program["id"], group["id"], ADMIN))
        assert group_after["active_enrollment_count"] == 1, (
            "cancel then promote must return the occupancy counter to 1")

    def test_suspend_cascade_releases_seat_counter_before_promotion(self, api):
        """PRD §3.4: "Separately, system cascades move `RESERVED` or
        `CONFIRMED` seats to the terminal `CANCELLED` — decrementing the
        counter — when the participant is suspended, when the participant's
        current agreement is revoked, or as part of group retirement."
        PRD §3.4: "Promotion only occurs while `active_enrollment_count` is
        below `base_capacity`."

        Design: Difficulty/transitive_cascade/participant_suspend_cascade_releases_enrollments_and_promotes_waitlist
        """
        program, group, pa, pb, ea, eb = self._setup_full_group_with_waitlist(api)
        # Sanity: full group before suspension.
        group_pre = validate_success(api.get_group(program["id"], group["id"], ADMIN))
        assert group_pre["active_enrollment_count"] == 1

        get_success_data(api.suspend_participant(pa["id"], ADMIN))
        ea_after = validate_success(
            api.get_enrollment(program["id"], group["id"], ea["id"], ADMIN))
        assert ea_after["seat_status"] == "CANCELLED"
        eb_after = validate_success(
            api.get_enrollment(program["id"], group["id"], eb["id"], ADMIN))
        assert eb_after["seat_status"] == "RESERVED"

        # B can now be confirmed from the promoted RESERVED seat.
        confirmed = confirm_enrollment(program["id"], group["id"], eb["id"])
        assert confirmed["seat_status"] == "CONFIRMED"
