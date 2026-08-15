"""Consent grants, third-party verification requests, FERPA checks, SoD."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_verification_request,
    create_consent_grant,
    create_student,
    create_verification_in_consent_check,
    create_verification_request,
    get_success_data,
    make_student_headers,
    reset_clock,
    set_clock,
    validate_error,
    validate_success,
)


def _reviewer():
    return TEST_USERS["reviewer_headers"]


def _operator():
    return TEST_USERS["operator_headers"]


def _requester():
    return TEST_USERS["requester_headers"]


def _admin():
    return TEST_USERS["admin_headers"]


class TestConsentGrantCreation:
    def test_consent_grant_past_expiry_rejected(self, api):
        """PRD §3.9: "A `Student` creates one by supplying `student_id`,
        `grantee_name`, `scope`, and `expires_at`; the expiry must lie strictly
        in the future at creation, otherwise the request is rejected with
        `ERR_CONSENT_EXPIRED` (HTTP 422)."

        Design: Corner/validations/consent_grant_past_expiry_rejected
        """
        reset_clock()
        student = create_student(
            student_number="SC002101", full_name="CG T",
            date_of_birth="2000-01-01", email="cg@x.edu",
        )
        resp = api.create_consent_grant(
            {
                "student_id": student["id"],
                "grantee_name": "X",
                "scope": "DEGREE_ONLY",
                "expires_at": "2026-07-01T00:00:00Z",
            },
            make_student_headers(student["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CONSENT_EXPIRED)


class TestClockDrivenConsentExpiry:
    def test_scheduled_action_clock_drives_consent_expiry(self, api):
        """PRD §2.4: "setting the clock re-evaluates every `ConsentGrant` whose
        `expires_at` is at or before the new instant (transitioning each such
        grant from `ACTIVE` to `EXPIRED`)".
        PRD §3.9: "When the logical clock reaches a grant's `expires_at`, the
        grant moves from `ACTIVE` to `EXPIRED`".

        Design: Corner/cross_cutting_layers/scheduled_action_clock_drives_consent_expiry
        """
        reset_clock()
        student = create_student(
            student_number="SC006201", full_name="Sched T",
            date_of_birth="2000-01-01", email="sch@x.edu",
        )
        grant = create_consent_grant(
            student["id"],
            grantee_name="Emp",
            scope="DEGREE_ONLY",
            expires_at="2026-08-15T00:00:00Z",
        )
        assert grant["status"] == "ACTIVE"
        set_clock("2026-08-16T00:00:00Z")
        resp = api.get_consent_grant(grant["id"], _admin())
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "EXPIRED"


class TestConsentRevocationCascade:
    def test_consent_revoke_to_verification_denied_depth2(self, api):
        """PRD §3.9: "A student may revoke only their own grant — the caller's
        `X-User-ID` must equal the grant's `student_id` — and revocation moves it
        from `ACTIVE` to `REVOKED` and cascades: every `VerificationRequest`
        referencing that grant and currently sitting in `CONSENT_CHECK` is denied
        with `denial_reason` set to `CONSENT_REVOKED`."

        Design: Difficulty/transitive_cascade/consent_revoke_to_verification_denied_depth2
        """
        reset_clock()
        student = create_student(
            student_number="S5000002", full_name="Ivy Chen",
            date_of_birth="1999-12-01", email="ivy@example.edu",
        )
        grant = create_consent_grant(
            student["id"],
            grantee_name="Employer Inc",
            scope="DEGREE_ONLY",
            expires_at="2027-08-01T00:00:00Z",
        )
        vr = create_verification_request(
            student["id"],
            requester_name="Employer Inc",
            scope="DEGREE_ONLY",
            consent_grant_id=grant["id"],
        )
        vr = get_success_data(api.begin_review_verification_request(vr["id"], _reviewer()))
        assert vr["status"] == "CONSENT_CHECK"

        # Hop 1: ConsentGrant ACTIVE -> REVOKED.
        revoked = get_success_data(
            api.revoke_consent_grant(grant["id"], make_student_headers(student["id"]))
        )
        assert revoked["status"] == "REVOKED"

        # Hop 2: referencing VerificationRequest in CONSENT_CHECK -> DENIED.
        vr_after = get_success_data(api.get_verification_request(vr["id"], _reviewer()))
        assert vr_after["status"] == "DENIED"
        assert vr_after["denial_reason"] == "CONSENT_REVOKED"

    def test_consent_revoke_only_affects_requests_in_consent_check(self, api):
        """PRD §3.9: "revocation moves it from `ACTIVE` to `REVOKED` and
        cascades: every `VerificationRequest` referencing that grant and
        currently sitting in `CONSENT_CHECK` is denied with `denial_reason` set
        to `CONSENT_REVOKED`."

        Design: Difficulty/transitive_cascade/consent_revoke_to_verification_denied_depth2
        """
        reset_clock()
        student = create_student(
            student_number="S5000102", full_name="Ivy Chen B",
            date_of_birth="1999-12-01", email="ivyb@example.edu",
        )
        grant = create_consent_grant(
            student["id"],
            grantee_name="Employer Inc",
            scope="DEGREE_ONLY",
            expires_at="2027-08-01T00:00:00Z",
        )
        # This request stays in RECEIVED (never enters CONSENT_CHECK).
        vr = create_verification_request(
            student["id"],
            requester_name="Employer Inc",
            scope="DEGREE_ONLY",
            consent_grant_id=grant["id"],
        )
        get_success_data(
            api.revoke_consent_grant(grant["id"], make_student_headers(student["id"]))
        )
        vr_after = get_success_data(api.get_verification_request(vr["id"], _reviewer()))
        # The cascade names only requests "currently sitting in CONSENT_CHECK".
        assert vr_after["status"] == "RECEIVED"


class TestVerificationApprovalFerpa:
    def test_verification_approve_blocked_by_revoked_consent_grant(self, api):
        """PRD §3.9: "First, FERPA consent: if the subject student's
        `ferpa_restricted` flag is true, or the requested `scope` is anything
        other than `ENROLLMENT_ONLY`, then an `ACTIVE` `ConsentGrant` must exist
        whose `grantee_name` equals the request's `requester_name`, whose `scope`
        covers the requested scope, and whose `expires_at` is strictly later than
        the current logical clock; failing this yields
        `ERR_FERPA_CONSENT_REQUIRED` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/verification_approve_blocked_by_revoked_consent_grant
        """
        reset_clock()
        student = create_student(
            student_number="S8000002", full_name="Omar Ray",
            date_of_birth="2000-06-30", email="omar@example.edu",
            ferpa_restricted=True,
        )
        grant = create_consent_grant(
            student["id"],
            grantee_name="Employer Inc",
            scope="DEGREE_ONLY",
            expires_at="2027-08-01T00:00:00Z",
        )
        # Revoke the grant before the request under test reaches approval.
        get_success_data(
            api.revoke_consent_grant(grant["id"], make_student_headers(student["id"]))
        )
        vr2 = create_verification_request(
            student["id"],
            requester_name="Employer Inc",
            scope="DEGREE_ONLY",
            consent_grant_id=grant["id"],
        )
        vr2 = get_success_data(api.begin_review_verification_request(vr2["id"], _reviewer()))
        resp = api.approve_verification_request(vr2["id"], _reviewer())
        validate_error(resp, ApiErrorId.ERR_FERPA_CONSENT_REQUIRED)
        vr2_after = get_success_data(api.get_verification_request(vr2["id"], _reviewer()))
        assert vr2_after["status"] == "CONSENT_CHECK"

    def test_verification_approve_succeeds_with_active_covering_grant(self, api):
        """PRD §3.9: "then an `ACTIVE` `ConsentGrant` must exist whose
        `grantee_name` equals the request's `requester_name`, whose `scope`
        covers the requested scope, and whose `expires_at` is strictly later than
        the current logical clock".
        PRD §3.9: "On success the server computes `fee_cents` and moves the
        request from `CONSENT_CHECK` to `APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/verification_approve_blocked_by_revoked_consent_grant
        """
        reset_clock()
        student = create_student(
            student_number="S8000102", full_name="Omar Ray B",
            date_of_birth="2000-06-30", email="omarb@example.edu",
            ferpa_restricted=True,
        )
        grant = create_consent_grant(
            student["id"],
            grantee_name="Employer Inc",
            scope="DEGREE_ONLY",
            expires_at="2027-08-01T00:00:00Z",
        )
        vr = create_verification_in_consent_check(
            student["id"],
            requester_name="Employer Inc",
            scope="DEGREE_ONLY",
            consent_grant_id=grant["id"],
        )
        resp = api.approve_verification_request(vr["id"], _reviewer())
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "APPROVED"


class TestVerificationFeeArchiveVariant:
    def test_verification_fee_non_archived_subject(self, api):
        """PRD §3.9: "The verification fee is a flat 500-cent base, plus 300
        cents when the scope is `DEGREE_ONLY` or 700 cents when it is
        `FULL_RECORD` (no scope surcharge for `ENROLLMENT_ONLY`), plus a
        1500-cent historical-lookup surcharge when the subject student's
        `archived_record_flag` is true."

        Design: Difficulty/dual_variant_calc/verification_fee_archived_vs_non_archived_subject_diverge
        """
        reset_clock()
        student = create_student(
            student_number="S2000001", full_name="Bob Smith",
            date_of_birth="1999-05-20", email="bob@example.edu",
            archived_record_flag=False,
        )
        grant = create_consent_grant(
            student["id"],
            grantee_name="Employer Inc",
            scope="DEGREE_ONLY",
            expires_at="2027-08-01T00:00:00Z",
        )
        vr = create_verification_in_consent_check(
            student["id"],
            requester_name="Employer Inc",
            scope="DEGREE_ONLY",
            consent_grant_id=grant["id"],
        )
        data = validate_success(
            api.approve_verification_request(vr["id"], _reviewer()), expected_status=200
        )
        assert_verification_request(data)
        # 500 base + 300 DEGREE_ONLY + 0 archive = 800
        assert data["fee_cents"] == 800, f"expected 800, got {data['fee_cents']}"

    def test_verification_fee_archived_subject(self, api):
        """PRD §3.9: "The verification fee is a flat 500-cent base, plus 300
        cents when the scope is `DEGREE_ONLY` or 700 cents when it is
        `FULL_RECORD` (no scope surcharge for `ENROLLMENT_ONLY`), plus a
        1500-cent historical-lookup surcharge when the subject student's
        `archived_record_flag` is true."

        Design: Difficulty/dual_variant_calc/verification_fee_archived_vs_non_archived_subject_diverge
        """
        reset_clock()
        student = create_student(
            student_number="S2000002", full_name="Carol Jones",
            date_of_birth="1975-03-11", email="carol@example.edu",
            archived_record_flag=True,
        )
        grant = create_consent_grant(
            student["id"],
            grantee_name="Employer Inc",
            scope="DEGREE_ONLY",
            expires_at="2027-08-01T00:00:00Z",
        )
        vr = create_verification_in_consent_check(
            student["id"],
            requester_name="Employer Inc",
            scope="DEGREE_ONLY",
            consent_grant_id=grant["id"],
        )
        data = validate_success(
            api.approve_verification_request(vr["id"], _reviewer()), expected_status=200
        )
        # 500 base + 300 DEGREE_ONLY + 1500 archive = 2300
        assert data["fee_cents"] == 2300, f"expected 2300, got {data['fee_cents']}"


class TestVerificationRbac:
    def test_registrar_operator_cannot_approve_verification(self, api):
        """PRD §2.1: "A request whose role is not on the endpoint's authorized
        list is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: POST /registrar/verification-requests/{id}/approve is authorized
        for "RegistrarReviewer".

        Design: Corner/rbac/registrar_operator_cannot_approve_verification
        """
        reset_clock()
        student = create_student(
            student_number="SC005101", full_name="RB2 T",
            date_of_birth="2000-01-01", email="rb2@x.edu",
        )
        grant = create_consent_grant(
            student["id"], grantee_name="Emp", scope="DEGREE_ONLY",
            expires_at="2027-08-01T00:00:00Z",
        )
        vr = create_verification_in_consent_check(
            student["id"],
            requester_name="Emp",
            scope="DEGREE_ONLY",
            consent_grant_id=grant["id"],
        )
        resp = api.approve_verification_request(vr["id"], _operator())
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        vr_after = get_success_data(api.get_verification_request(vr["id"], _reviewer()))
        assert vr_after["status"] == "CONSENT_CHECK"

    def test_verification_requester_can_create_request(self, api):
        """PRD §3.9: "A `VerificationRequester` — an employer, a background-check
        firm — opens a `VerificationRequest` by supplying `requester_name`,
        `subject_student_id`, and `scope` (`ENROLLMENT_ONLY`, `DEGREE_ONLY`, or
        `FULL_RECORD`), plus an optional `consent_grant_id`. The request lands in
        `RECEIVED`."

        Design: Corner/rbac/verification_requester_can_create_request
        """
        reset_clock()
        student = create_student(
            student_number="SC005201", full_name="VR T",
            date_of_birth="2000-01-01", email="vr@x.edu",
        )
        resp = api.create_verification_request(
            {
                "requester_name": "Emp",
                "subject_student_id": student["id"],
                "scope": "ENROLLMENT_ONLY",
            },
            _requester(),
        )
        data = validate_success(resp, expected_status=201)
        assert_verification_request(data)
        assert data["status"] == "RECEIVED"
