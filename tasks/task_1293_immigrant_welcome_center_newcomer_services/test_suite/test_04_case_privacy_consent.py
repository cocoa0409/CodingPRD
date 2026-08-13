"""Case privacy postures, consent lifecycles, cascades, and case-note
confidentiality (PRD §2.9, §3.2, §3.5)."""

from test_helpers import (
    api_client, TEST_USERS,
    validate_success, validate_error, ApiErrorId,
    create_case_note_payload, create_consent_payload,
    register_client, create_staff_member, open_case, grant_consent,
    create_partner_org, create_draft_referral, send_referral, create_sent_referral,
    create_appointment, confirm_appointment, transition_case, transition_plan,
    create_verified_assessment, create_plan_for_case, staff_headers,
    client_headers, get_case,
)

ADMIN = TEST_USERS["center_admin_headers"]


class TestParallelDimensions:
    def _setup_intake_case(self):
        mgr = create_staff_member()
        client = register_client()
        case = open_case(client, mgr)
        return mgr, client, case

    def test_privacy_move_leaves_service_status_untouched(self):
        """PRD §3.2: "The privacy dimension is orthogonal. A `CaseManager` or
        `CenterAdmin` may move `STANDARD` to `RESTRICTED` and back; a `RESTRICTED`
        case blocks referral sends with `ERR_PRIVACY_SEALED` but nothing else."

        Design: Difficulty/non_linear_state_machine/case_parallel_dimensions_move_independently
        """
        mgr, _client, case = self._setup_intake_case()
        moved = validate_success(api_client.set_case_privacy(
            case["id"], {"to_posture": "RESTRICTED", "reason": "sensitive employer dispute"},
            staff_headers(mgr)))
        assert moved["privacy_posture"] == "RESTRICTED"
        assert moved["service_status"] == "INTAKE", \
            "the privacy dimension moves independently of the service pipeline"

    def test_service_gate_still_applies_after_privacy_move(self):
        """PRD §3.2: "Moving from `INTAKE` to `ASSESSED` requires at least one of
        the case's assessments to be `VERIFIED`, failing with `ERR_INVALID_STATE`
        otherwise."
        PRD §3.2: "The privacy dimension is orthogonal."

        Design: Difficulty/non_linear_state_machine/case_parallel_dimensions_move_independently
        """
        mgr, _client, case = self._setup_intake_case()
        validate_success(api_client.set_case_privacy(
            case["id"], {"to_posture": "RESTRICTED", "reason": "sensitive"},
            staff_headers(mgr)))
        resp = api_client.transition_case(
            case["id"], {"to_status": "ASSESSED"}, staff_headers(mgr))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_case(case["id"], mgr)
        assert after["service_status"] == "INTAKE"
        assert after["privacy_posture"] == "RESTRICTED"


class TestSealCascade:
    def _setup_sealable_case(self):
        """STANDARD case + SENT referral (slot held) + CONFIRMED ACCOMPANIMENT
        appointment linked to the referral."""
        mgr = create_staff_member()
        client = register_client()
        grant_consent(client, "REFERRAL_SHARE")
        grant_consent(client, "ACCOMPANIMENT")
        case = open_case(client, mgr)
        org = create_partner_org(name="Org X", categories=("LEGAL",), capacity=5,
                                 email="x@org.test")
        ref = create_sent_referral(case, org, "LEGAL", mgr)
        appt = create_appointment(case, mgr, kind="ACCOMPANIMENT",
                                  starts_at="2026-08-10T10:00:00Z",
                                  ends_at="2026-08-10T11:00:00Z",
                                  referral_id=ref["id"])
        confirm_appointment(appt["id"], mgr)
        return mgr, client, case, org, ref, appt

    def test_seal_suspends_referrals_and_releases_slots(self):
        """PRD §3.2: "The case's `privacy_posture` becomes `SEALED` and its
        `version` increments (step one); every referral of the case in `DRAFT`,
        `SENT`, or `ACCEPTED` is suspended with `suspension_reason` set to
        `CASE_SEALED` (step two); for each referral that was holding a partner
        slot — those suspended out of `SENT` or `ACCEPTED` — the organization's
        `referral_slots_used` is decremented by 1, releasing the slot (step
        three)".

        Design: Difficulty/transitive_cascade/seal_cascade_case_referral_orgslot_appointment
        """
        mgr, _client, case, org, ref, _appt = self._setup_sealable_case()
        sealed = validate_success(api_client.set_case_privacy(
            case["id"], {"to_posture": "SEALED", "reason": "court order"}, ADMIN))
        assert sealed["privacy_posture"] == "SEALED"
        ref_now = validate_success(api_client.get_referral(ref["id"], staff_headers(mgr)))
        assert ref_now["status"] == "SUSPENDED"
        assert ref_now["suspension_reason"] == "CASE_SEALED"
        org_now = validate_success(api_client.get_organization(org["id"], staff_headers(mgr)))
        assert org_now["referral_slots_used"] == 0, "the suspension releases the partner slot"

    def test_seal_system_cancels_linked_appointments_and_blocks_resume(self):
        """PRD §3.2: "and for each suspended referral, every appointment whose
        `referral_id` names it and whose status is `REQUESTED` or `CONFIRMED` is
        cancelled with `cancelled_by_system` set to true (step four)."
        PRD §3.2: "A sealed case blocks referral sends, resumes, and reroutes,
        appointment creation, screening creation, and — for anyone other than a
        `CenterAdmin` — note creation, all with `ERR_PRIVACY_SEALED`."

        Design: Difficulty/transitive_cascade/seal_cascade_case_referral_orgslot_appointment
        """
        mgr, _client, case, _org, ref, appt = self._setup_sealable_case()
        validate_success(api_client.set_case_privacy(
            case["id"], {"to_posture": "SEALED", "reason": "court order"}, ADMIN))
        appt_now = validate_success(api_client.get_appointment(appt["id"], staff_headers(mgr)))
        assert appt_now["status"] == "CANCELLED"
        assert appt_now["cancelled_by_system"] is True
        # The seal continues to block a resume of the suspended referral.
        resp = api_client.resume_referral(ref["id"], staff_headers(mgr))
        validate_error(resp, ApiErrorId.ERR_PRIVACY_SEALED)


class TestClientExit:
    def _drive_case_to_closed(self, mgr, client):
        case = open_case(client, mgr)
        create_verified_assessment(case, mgr, create_staff_member(full_name="Verifier"))
        transition_case(case["id"], "ASSESSED", mgr)
        transition_case(case["id"], "PLANNING", mgr)
        plan = create_plan_for_case(case["id"], mgr)
        transition_plan(plan["id"], "ACTIVE", mgr)
        transition_case(case["id"], "ACTIVE", mgr)
        transition_plan(plan["id"], "COMPLETED", mgr)
        transition_case(case["id"], "OUTCOME_REVIEW", mgr)
        return transition_case(case["id"], "CLOSED", mgr, closed_reason="goals met")

    def test_exited_client_blocks_new_case(self):
        """PRD §3.1: "Once `EXITED` — the client's only terminal state — no new
        case may be opened for that client, and no new consent may be granted for
        them either; both attempts fail with `ERR_CLIENT_EXITED`."
        PRD §3.1: "Exit requires that every case of the client has reached
        `CLOSED`; if any case is still open the request fails with
        `ERR_INVALID_STATE`."

        Design: Corner/errors/exited_client_blocks_new_case
        """
        mgr = create_staff_member()
        client = register_client()
        self._drive_case_to_closed(mgr, client)
        exited = validate_success(api_client.exit_client(client["id"], staff_headers(mgr)))
        assert exited["status"] == "EXITED"

        resp = api_client.create_case(
            {"client_id": client["id"], "assigned_manager_id": mgr["id"]},
            staff_headers(mgr))
        validate_error(resp, ApiErrorId.ERR_CLIENT_EXITED)

    def test_exit_blocked_while_case_open(self):
        """PRD §3.1: "Exit requires that every case of the client has reached
        `CLOSED`; if any case is still open the request fails with
        `ERR_INVALID_STATE`."

        Design: Corner/errors/exited_client_blocks_new_case
        """
        mgr = create_staff_member()
        client = register_client()
        open_case(client, mgr)
        resp = api_client.exit_client(client["id"], staff_headers(mgr))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestConsentCascade:
    def test_consent_revocation_cascade_to_referral_and_appointment(self):
        """PRD §3.5: "When the revoked consent's scope is `REFERRAL_SHARE`, the
        same three-step cascade as a privacy seal follows: every referral of the
        client's cases in `SENT` or `ACCEPTED` is suspended with
        `suspension_reason` set to `CONSENT_REVOKED`, each such suspension
        decrements the partner's `referral_slots_used` by 1, and each suspended
        referral cancels its linked `REQUESTED` or `CONFIRMED` appointments with
        `cancelled_by_system` true."
        PRD §2.1: "When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the
        acting `Client`; the client may read only its own record, its own cases,
        and its own consents, and may revoke a consent only when that consent's
        `client_id` equals `X-User-ID`."

        Design: Corner/cross_cutting_layers/consent_revocation_cascade_to_referral_and_appointment
        """
        mgr = create_staff_member()
        client = register_client()
        share = grant_consent(client, "REFERRAL_SHARE")
        grant_consent(client, "ACCOMPANIMENT")
        case = open_case(client, mgr)
        org = create_partner_org(name="Org V", categories=("LEGAL",), capacity=5,
                                 email="v@org.test")
        ref = create_sent_referral(case, org, "LEGAL", mgr)
        appt = create_appointment(case, mgr, kind="ACCOMPANIMENT",
                                  starts_at="2026-08-12T10:00:00Z",
                                  ends_at="2026-08-12T11:00:00Z",
                                  referral_id=ref["id"])
        confirm_appointment(appt["id"], mgr)

        # The client revokes its own consent.
        revoked = validate_success(api_client.revoke_consent(
            share["id"], {"revoked_reason": "client withdrew sharing consent"},
            client_headers(client)))
        assert revoked["status"] == "REVOKED"

        ref_now = validate_success(api_client.get_referral(ref["id"], staff_headers(mgr)))
        assert ref_now["status"] == "SUSPENDED"
        assert ref_now["suspension_reason"] == "CONSENT_REVOKED"
        appt_now = validate_success(api_client.get_appointment(appt["id"], staff_headers(mgr)))
        assert appt_now["status"] == "CANCELLED"
        assert appt_now["cancelled_by_system"] is True
        org_now = validate_success(api_client.get_organization(org["id"], staff_headers(mgr)))
        assert org_now["referral_slots_used"] == 0

        # A fresh consent unblocks an explicit resume back to SENT.
        grant_consent(client, "REFERRAL_SHARE")
        resumed = validate_success(api_client.resume_referral(ref["id"], staff_headers(mgr)))
        assert resumed["status"] == "SENT"
        assert resumed["suspension_reason"] is None

    def test_derived_reportable_flag_reconciles_on_consent_changes(self):
        """PRD §2.9: "a client's `reportable` is true exactly when that client
        holds a consent with `scope` equal to `DATA_REPORTING` in status
        `GRANTED`, and false otherwise."

        Design: Corner/cross_cutting_layers/derived_reportable_flag_reconciles_on_consent_changes
        """
        mgr = create_staff_member()
        client = register_client()
        assert client["reportable"] is False, "reportable is false at registration"

        consent = grant_consent(client, "DATA_REPORTING")
        after_grant = validate_success(api_client.get_client(client["id"], staff_headers(mgr)))
        assert after_grant["reportable"] is True

        validate_success(api_client.revoke_consent(consent["id"], {}, ADMIN))
        after_revoke = validate_success(api_client.get_client(client["id"], staff_headers(mgr)))
        assert after_revoke["reportable"] is False


class TestCaseNotes:
    def test_case_note_body_length_limit(self):
        """PRD §3.2: "The `body` runs from 1 to 10000 characters — anything
        outside that range is rejected with `ERR_NOTE_TOO_LONG`".

        Design: Corner/errors/case_note_body_length_limit
        """
        mgr = create_staff_member()
        client = register_client()
        case = open_case(client, mgr)
        resp = api_client.create_case_note(
            create_case_note_payload(case["id"], body="x" * 10001), staff_headers(mgr))
        validate_error(resp, ApiErrorId.ERR_NOTE_TOO_LONG, expected_status=422)
        ok = validate_success(api_client.create_case_note(
            create_case_note_payload(case["id"], body="x" * 10000),
            staff_headers(mgr)), expected_status=201)
        assert ok["redaction_status"] == "VISIBLE"

    def test_note_read_clearance_and_authorship(self):
        """PRD §2.9: "case notes carry a `sensitivity` of `STANDARD`,
        `CONFIDENTIAL`, or `SEALED`, read respectively by staff whose
        `clearance_level` is at least 1, at least 2, or exactly 3 — the author's
        own notes always remaining readable by their author regardless of
        clearance."
        PRD §3.2: "the chosen `sensitivity` may not exceed the author's own
        `clearance_level`, an overreach rejected with
        `ERR_CLEARANCE_INSUFFICIENT`."

        Design: Corner/rbac/note_read_clearance_and_authorship
        """
        admin = create_staff_member(role_level="ADMIN", clearance_level=3, full_name="Admin A")
        mgr2 = create_staff_member(clearance_level=2, full_name="Mgr Two")
        intake = create_staff_member(role_level="INTAKE", clearance_level=1, full_name="Intake I")
        client = register_client()
        case = open_case(client, admin)
        note = validate_success(api_client.create_case_note(
            create_case_note_payload(
                case["id"], body="sealed fact", sensitivity="SEALED"),
            staff_headers(admin)), expected_status=201)

        # Non-author with clearance 2 cannot read a SEALED note.
        resp = api_client.get_case_note(note["id"], staff_headers(mgr2))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        # The author reads it regardless.
        own = validate_success(api_client.get_case_note(note["id"], staff_headers(admin)))
        assert own["body"] == "sealed fact"
        # A clearance-1 author may not even create a SEALED note.
        resp2 = api_client.create_case_note(
            create_case_note_payload(
                case["id"], body="too sensitive for me", sensitivity="SEALED"),
            staff_headers(intake))
        validate_error(resp2, ApiErrorId.ERR_CLEARANCE_INSUFFICIENT)
