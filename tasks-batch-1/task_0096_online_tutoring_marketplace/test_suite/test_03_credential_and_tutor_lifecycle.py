"""Credential verification, tutor verification machine, subject-tag gating,
and the cascades that link them.

Covers the credential-expiry suspension cascade, the cross-entity guards
(deliver requires VERIFIED tutor; tag approval requires a VERIFIED credential),
and the active_subject_count conservation across approve + revoke.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_credential_payload,
    create_subject_payload,
    create_subject_tag_payload,
    create_tutor_payload,
    create_verified_tutor,
    make_tutor_headers,
    propose_and_approve_tag,
    setup_marketplace,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OFFICER = TEST_USERS["trust_officer_headers"]


def _set_clock(api, iso):
    return validate_success(api.set_clock({"to_iso8601": iso}, ADMIN))


class TestCredentialExpiryCascade:
    def test_expiry_suspends_tutor_and_revokes_gated_tags(self, api):
        """PRD §3.2: "A verified credential may later be expired by the officer,
        advancing it from `VERIFIED` to `EXPIRED`; if the tutor is left with zero
        `VERIFIED` credentials as a result, the tutor falls from `VERIFIED` to
        `SUSPENDED` and every `APPROVED` subject tag whose subject requires a
        credential is revoked as a cascade."

        Design: Difficulty/transitive_cascade/credential_expiry_suspends_tutor_revokes_tags
        """
        _set_clock(api, "2026-06-01T00:00:00Z")
        subject = validate_success(api.create_subject(create_subject_payload(requires_credential=True), ADMIN), 201)
        tutor, cred = create_verified_tutor(subject["id"], base_hourly_rate_cents=7000, kind="TEACHING_LICENSE")
        tag = propose_and_approve_tag(tutor["id"], subject["id"])

        validate_success(api.expire_credential(cred["id"], OFFICER))

        cred_after = validate_success(api.get_credential(cred["id"], OFFICER))
        assert cred_after["status"] == "EXPIRED"  # hop 1
        tutor_after = validate_success(api.get_tutor(tutor["id"], ADMIN))
        assert tutor_after["verification_status"] == "SUSPENDED"  # hop 2
        tag_after = validate_success(api.get_subject_tag(tag["id"], OFFICER))
        assert tag_after["status"] == "REVOKED"  # hop 3
        assert tutor_after["active_subject_count"] == 0

    def test_expiry_marks_credential_terminal_expired(self, api):
        """PRD §3.2: "A verified credential may later be expired by the officer,
        advancing it from `VERIFIED` to `EXPIRED` ... The states `VERIFIED`,
        `REJECTED`, and `EXPIRED` are terminal for a credential."

        Design: Difficulty/transitive_cascade/credential_expiry_suspends_tutor_revokes_tags
        """
        _set_clock(api, "2026-06-01T00:00:00Z")
        subject = validate_success(api.create_subject(create_subject_payload(requires_credential=True), ADMIN), 201)
        tutor, cred = create_verified_tutor(subject["id"], base_hourly_rate_cents=7000, kind="TEACHING_LICENSE")
        propose_and_approve_tag(tutor["id"], subject["id"])
        expired = validate_success(api.expire_credential(cred["id"], OFFICER))
        assert expired["status"] == "EXPIRED"
        # Re-expiring a terminal credential is no longer a valid transition.
        resp = api.expire_credential(cred["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_credential_reject_drops_tutor_to_rejected(self, api):
        """PRD §3.2: "Rejecting advances the credential from `UNDER_REVIEW` to
        `REJECTED`, stores the supplied `rejection_reason`, and — if the tutor then
        holds zero `VERIFIED` credentials and has no other credential still
        `UNDER_REVIEW` — drops the tutor from `PENDING_REVIEW` to `REJECTED`."

        Design: Corner/state_machines/credential_reject_marks_tutor_rejected
        """
        _set_clock(api, "2026-06-01T00:00:00Z")
        subject = validate_success(api.create_subject(create_subject_payload(), ADMIN), 201)
        tutor = validate_success(api.create_tutor(create_tutor_payload(), ADMIN), 201)
        t_headers = make_tutor_headers(tutor["id"])
        cred = validate_success(
            api.create_credential(create_credential_payload(tutor["id"], subject["id"]), t_headers), 201
        )
        validate_success(api.start_review_credential(cred["id"], OFFICER))

        rejected = validate_success(api.reject_credential(cred["id"], {"rejection_reason": "Illegible scan"}, OFFICER))
        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_reason"] == "Illegible scan"
        tutor_after = validate_success(api.get_tutor(tutor["id"], ADMIN))
        assert tutor_after["verification_status"] == "REJECTED"


class TestCrossEntityGuards:
    def test_deliver_requires_tutor_verified(self, api):
        """PRD §3.7: "Delivering is allowed only when the booking is `SCHEDULED`,
        when the current clock is at or past `scheduled_start`, and when the
        tutor's `verification_status` is `VERIFIED`."
        PRD §2.5: "an operation that needs a `VERIFIED` tutor but finds one that is
        not is rejected with `ERR_TUTOR_NOT_VERIFIED`."

        Design: Difficulty/cross_entity_state_dependency/booking_deliver_requires_tutor_verified
        """
        mk = setup_marketplace(base_hourly_rate_cents=6000)
        from test_helpers import create_booking, get_success_data
        booking = get_success_data(
            api.create_booking(
                {
                    "parent_account_id": mk["parent"]["id"],
                    "student_id": mk["student"]["id"],
                    "tutor_id": mk["tutor"]["id"],
                    "subject_id": mk["subject"]["id"],
                    "scheduled_start": "2026-06-02T10:00:00Z",
                    "planned_minutes": 30,
                },
                mk["parent_headers"],
            )
        )
        # Suspend the tutor after the booking exists.
        validate_success(api.suspend_tutor(mk["tutor"]["id"], OFFICER))
        _set_clock(api, "2026-06-02T11:00:00Z")

        resp = api.deliver_booking(booking["id"], {"actual_minutes": 30}, mk["tutor_headers"])
        validate_error(resp, ApiErrorId.ERR_TUTOR_NOT_VERIFIED.value)
        booking_after = validate_success(api.get_booking(booking["id"], mk["parent_headers"]))
        assert booking_after["status"] == "SCHEDULED"

    def test_deliver_by_verified_tutor_creates_session(self, api):
        """PRD §3.7: "Delivering is allowed only when the booking is `SCHEDULED`,
        when the current clock is at or past `scheduled_start`, and when the
        tutor's `verification_status` is `VERIFIED`."
        PRD §3.7: "moves the booking from `SCHEDULED` to `DELIVERED`, and creates a
        `Session` that records its `booking_id`".

        Design: Difficulty/cross_entity_state_dependency/booking_deliver_requires_tutor_verified
        """
        mk = setup_marketplace(base_hourly_rate_cents=6000)
        from test_helpers import create_booking, deliver_booking
        booking = create_booking(mk, "2026-06-02T10:00:00Z", planned_minutes=30)
        # Tutor stays VERIFIED -> deliver succeeds.
        session = deliver_booking(mk, booking["id"], 30, "2026-06-02T11:00:00Z")
        assert session["booking_id"] == booking["id"]
        booking_after = validate_success(api.get_booking(booking["id"], mk["parent_headers"]))
        assert booking_after["status"] == "DELIVERED"

    def test_tag_approval_requires_verified_credential(self, api):
        """PRD §3.3: "if the subject carries `requires_credential` set to true —
        the tutor must hold a `VERIFIED` credential for that same subject ... the
        credential gap, specifically, is rejected with
        `ERR_SUBJECT_REQUIRES_CREDENTIAL`."
        PRD §3.3: "On approval the tag advances from `PROPOSED` to `APPROVED`".

        Design: Difficulty/cross_entity_state_dependency/tag_approval_requires_verified_credential_for_subject

        PRD §3.3 evaluates the three approval conditions in order — tag PROPOSED,
        tutor VERIFIED, then the gated-subject credential — and surfaces the
        *verification* gap as ERR_TUTOR_NOT_VERIFIED, only the *credential* gap as
        ERR_SUBJECT_REQUIRES_CREDENTIAL. To isolate the credential gap the tutor
        must already be VERIFIED (via a credential on a different, non-gated
        subject) while still lacking a VERIFIED credential for the gated subject.
        """
        _set_clock(api, "2026-06-01T00:00:00Z")
        subj_free = validate_success(api.create_subject(create_subject_payload(requires_credential=False), ADMIN), 201)
        subject = validate_success(api.create_subject(create_subject_payload(requires_credential=True), ADMIN), 201)
        # Tutor becomes VERIFIED via a credential on the non-gated subject, so the
        # verification gate (condition 2) is satisfied.
        tutor, _ = create_verified_tutor(subj_free["id"], base_hourly_rate_cents=6000)
        t_headers = make_tutor_headers(tutor["id"])
        # An UNDER_REVIEW (not yet VERIFIED) credential for the gated subject.
        cred = validate_success(
            api.create_credential(create_credential_payload(tutor["id"], subject["id"], kind="CERTIFICATION"), t_headers), 201
        )
        validate_success(api.start_review_credential(cred["id"], OFFICER))
        tag = validate_success(
            api.create_subject_tag(create_subject_tag_payload(tutor["id"], subject["id"]), t_headers), 201
        )

        # Credential for the gated subject still UNDER_REVIEW -> credential gap.
        resp_before = api.approve_subject_tag(tag["id"], OFFICER)
        validate_error(resp_before, ApiErrorId.ERR_SUBJECT_REQUIRES_CREDENTIAL.value)

        # Verify the gated-subject credential, then approval succeeds.
        validate_success(api.verify_credential(cred["id"], OFFICER))
        approved = validate_success(api.approve_subject_tag(tag["id"], OFFICER))
        assert approved["status"] == "APPROVED"

    def test_tag_stays_proposed_when_credential_not_verified(self, api):
        """PRD §3.3: "the credential gap, specifically, is rejected with
        `ERR_SUBJECT_REQUIRES_CREDENTIAL`."
        PRD §3.3: "A new tag begins in `PROPOSED` status."

        Design: Difficulty/cross_entity_state_dependency/tag_approval_requires_verified_credential_for_subject

        Per PRD §3.3 the verification gate (condition 2) precedes the credential
        gate (condition 3), so the tutor is made VERIFIED via a credential on a
        non-gated subject; only then does the missing gated-subject credential
        surface ERR_SUBJECT_REQUIRES_CREDENTIAL rather than ERR_TUTOR_NOT_VERIFIED.
        """
        _set_clock(api, "2026-06-01T00:00:00Z")
        subj_free = validate_success(api.create_subject(create_subject_payload(requires_credential=False), ADMIN), 201)
        subject = validate_success(api.create_subject(create_subject_payload(requires_credential=True), ADMIN), 201)
        tutor, _ = create_verified_tutor(subj_free["id"], base_hourly_rate_cents=6000)
        t_headers = make_tutor_headers(tutor["id"])
        cred = validate_success(
            api.create_credential(create_credential_payload(tutor["id"], subject["id"], kind="CERTIFICATION"), t_headers), 201
        )
        validate_success(api.start_review_credential(cred["id"], OFFICER))
        tag = validate_success(
            api.create_subject_tag(create_subject_tag_payload(tutor["id"], subject["id"]), t_headers), 201
        )
        resp = api.approve_subject_tag(tag["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_SUBJECT_REQUIRES_CREDENTIAL.value)
        # The failed approval leaves the tag in its PROPOSED state.
        tag_after = validate_success(api.get_subject_tag(tag["id"], OFFICER))
        assert tag_after["status"] == "PROPOSED"


class TestSubjectTagCountConservation:
    def test_approve_then_revoke_returns_count_to_zero(self, api):
        """PRD §3.3: "On approval the tag advances from `PROPOSED` to `APPROVED`,
        the system snapshots `effective_hourly_rate_cents` ... and the tutor's
        `active_subject_count` is incremented."
        PRD §3.3: "Revoking an `APPROVED` tag moves it to `REVOKED`, decrements the
        tutor's `active_subject_count`".

        Design: Difficulty/compensating_invariant/active_subject_count_conserved_across_approve_revoke
        """
        _set_clock(api, "2026-06-01T00:00:00Z")
        subject = validate_success(api.create_subject(create_subject_payload(), ADMIN), 201)
        tutor, cred = create_verified_tutor(subject["id"], base_hourly_rate_cents=6000)
        tag = propose_and_approve_tag(tutor["id"], subject["id"])

        tutor_before = validate_success(api.get_tutor(tutor["id"], ADMIN))
        assert tutor_before["active_subject_count"] == 1

        revoked = validate_success(api.revoke_subject_tag(tag["id"], OFFICER))
        assert revoked["status"] == "REVOKED"
        tutor_after = validate_success(api.get_tutor(tutor["id"], ADMIN))
        assert tutor_after["active_subject_count"] == 0

    def test_approve_increments_active_subject_count(self, api):
        """PRD §3.3: "On approval the tag advances from `PROPOSED` to `APPROVED`,
        the system snapshots `effective_hourly_rate_cents` ... and the tutor's
        `active_subject_count` is incremented."

        Design: Difficulty/compensating_invariant/active_subject_count_conserved_across_approve_revoke
        """
        _set_clock(api, "2026-06-01T00:00:00Z")
        subject = validate_success(api.create_subject(create_subject_payload(), ADMIN), 201)
        tutor, cred = create_verified_tutor(subject["id"], base_hourly_rate_cents=6000)
        tutor_before = validate_success(api.get_tutor(tutor["id"], ADMIN))
        assert tutor_before["active_subject_count"] == 0
        propose_and_approve_tag(tutor["id"], subject["id"])
        tutor_after = validate_success(api.get_tutor(tutor["id"], ADMIN))
        assert tutor_after["active_subject_count"] == 1


class TestTutorReinstatement:
    def test_reinstate_suspended_tutor_with_verified_credential(self, api):
        """PRD §3.2: "Reinstating moves a tutor from `SUSPENDED` back to
        `VERIFIED`, but only when the tutor currently holds at least one
        `VERIFIED` credential".

        Design: Corner/state_machines/tutor_reinstate_from_suspended
        """
        _set_clock(api, "2026-06-01T00:00:00Z")
        subject = validate_success(api.create_subject(create_subject_payload(), ADMIN), 201)
        tutor, cred = create_verified_tutor(subject["id"], base_hourly_rate_cents=6000)
        validate_success(api.suspend_tutor(tutor["id"], OFFICER))
        reinstated = validate_success(api.reinstate_tutor(tutor["id"], OFFICER))
        assert reinstated["verification_status"] == "VERIFIED"


class TestCredentialCreation:
    def test_new_credential_starts_submitted(self, api):
        """PRD §3.2: "A submitted credential begins in `SUBMITTED` status."

        Design: Corner/state_machines/new_credential_initial_state_submitted
        """
        _set_clock(api, "2026-06-01T00:00:00Z")
        subject = validate_success(api.create_subject(create_subject_payload(), ADMIN), 201)
        tutor = validate_success(api.create_tutor(create_tutor_payload(), ADMIN), 201)
        t_headers = make_tutor_headers(tutor["id"])
        cred = validate_success(
            api.create_credential(create_credential_payload(tutor["id"], subject["id"]), t_headers), 201
        )
        assert cred["status"] == "SUBMITTED"

    def test_list_credentials_by_tutor_id(self, api):
        """PRD §4 (GET /credentials): "List/filter credentials".
        PRD §2.3: "List results are returned sorted by `created_at` in ascending
        order — oldest first."

        Design: Corner/cross_cutting/credential_reverse_reachable_by_filtered_list
        """
        _set_clock(api, "2026-06-01T00:00:00Z")
        subj1 = validate_success(api.create_subject(create_subject_payload(), ADMIN), 201)
        subj2 = validate_success(api.create_subject(create_subject_payload(), ADMIN), 201)
        tutor = validate_success(api.create_tutor(create_tutor_payload(), ADMIN), 201)
        t_headers = make_tutor_headers(tutor["id"])
        c1 = validate_success(api.create_credential(create_credential_payload(tutor["id"], subj1["id"]), t_headers), 201)
        c2 = validate_success(api.create_credential(create_credential_payload(tutor["id"], subj2["id"]), t_headers), 201)

        resp = api.list_credentials(OFFICER, params={"tutor_id": tutor["id"]})
        data = validate_success(resp)
        returned_ids = {c["id"] for c in data}
        assert c1["id"] in returned_ids
        assert c2["id"] in returned_ids


class TestCredentialGatedTagApproval:
    def test_approve_gated_tag_with_zero_verified_credentials_rejected(self, api):
        """PRD §3.3: "if the subject carries `requires_credential` set to true —
        the tutor must hold a `VERIFIED` credential for that same subject ... the
        credential gap, specifically, is rejected with
        `ERR_SUBJECT_REQUIRES_CREDENTIAL`."

        Design: Difficulty/boundary_precision_check/subject_tag_approve_zero_verified_credentials_empty_set
        """
        _set_clock(api, "2026-06-01T00:00:00Z")
        # Tutor is VERIFIED via a credential on a DIFFERENT (non-gated) subject.
        subj_free = validate_success(api.create_subject(create_subject_payload(requires_credential=False), ADMIN), 201)
        subj_gated = validate_success(api.create_subject(create_subject_payload(requires_credential=True), ADMIN), 201)
        tutor, _ = create_verified_tutor(subj_free["id"], base_hourly_rate_cents=6000)
        t_headers = make_tutor_headers(tutor["id"])
        # Propose a tag on the gated subject for which the tutor holds NO verified credential.
        gated_tag = validate_success(
            api.create_subject_tag(create_subject_tag_payload(tutor["id"], subj_gated["id"]), t_headers), 201
        )
        resp = api.approve_subject_tag(gated_tag["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_SUBJECT_REQUIRES_CREDENTIAL.value)

    def test_approve_gated_tag_succeeds_once_credential_for_subject_verified(self, api):
        """PRD §3.3: "if the subject carries `requires_credential` set to true —
        the tutor must hold a `VERIFIED` credential for that same subject".
        PRD §3.3: "On approval the tag advances from `PROPOSED` to `APPROVED`".

        Design: Difficulty/boundary_precision_check/subject_tag_approve_zero_verified_credentials_empty_set
        """
        _set_clock(api, "2026-06-01T00:00:00Z")
        subj_gated = validate_success(api.create_subject(create_subject_payload(requires_credential=True), ADMIN), 201)
        # Verify the tutor via a VERIFIED credential ON the gated subject itself.
        tutor, _ = create_verified_tutor(subj_gated["id"], base_hourly_rate_cents=6000, kind="CERTIFICATION")
        approved = propose_and_approve_tag(tutor["id"], subj_gated["id"])
        assert approved["status"] == "APPROVED"
