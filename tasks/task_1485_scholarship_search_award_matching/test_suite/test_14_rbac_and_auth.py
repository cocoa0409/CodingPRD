"""Authentication, role gating, and entity-backed ownership."""
from test_helpers import (
    ApiErrorId,
    COORDINATOR_USER_ID,
    TEST_USERS,
    create_cycle,
    create_disbursement_payload,
    create_donor,
    create_draft_application,
    create_fund,
    create_open_program,
    create_report,
    create_student,
    get_success_data,
    make_coordinator_headers,
    make_donor_headers,
    make_reviewer_headers,
    make_student_headers,
    setup_accepted_award,
    submit_score_for,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]


class TestAuthentication:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying an
        unrecognized role, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.8: "**Authentication** — the `X-User-Role` and `X-User-ID`
        headers are present and the role is known; otherwise
        `ERR_UNAUTHENTICATED`. This applies to every endpoint."

        Design: Corner/validations/validation_missing_auth_headers_returns_unauthenticated
        """
        resp = api.create_student(
            {
                "full_name": "No Auth",
                "email": "na@test.example",
                "grade_level": 12,
                "gpa_hundredths": 300,
                "residency_state": "CA",
                "intended_major": "STEM",
                "household_income_cents": 5000000,
                "efc_cents": 0,
                "cost_of_attendance_cents": 3000000,
                "institution_name": "State U",
            },
            {},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleGating:
    def test_student_cannot_publish_program(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target
        endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: `POST /api/scholarship-programs/{id}/publish` is authorized
        for `ScholarshipCoordinator` only.

        Design: Corner/rbac/rbac_student_cannot_publish_program
        """
        student = create_student()
        donor = create_donor()
        fund = create_fund()
        program = validate_success(
            api.create_program(
                {
                    "name": "Rk Award",
                    "donor_id": donor["id"],
                    "fund_id": fund["id"],
                    "program_type": "MERIT",
                    "match_policy": "HOLISTIC",
                    "stacking_scope": "ANNUAL",
                    "award_amount_cents": 500000,
                    "max_recipients": 1,
                    "min_gpa_hundredths": 300,
                    "required_residency_state": "CA",
                    "max_household_income_cents": 10000000,
                    "application_open_at": "2026-08-01T00:00:00Z",
                    "application_close_at": "2026-09-15T00:00:00Z",
                },
                COORD,
            ),
            expected_status=201,
        )
        assert program["status"] == "DRAFT"

        resp = api.publish_program(
            program["id"], make_student_headers(student["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert validate_success(api.get_program(program["id"], COORD))["status"] == "DRAFT"

    def test_reviewer_cannot_finalize_cycle(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target
        endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: `POST /api/review-cycles/{id}/finalize` is authorized for
        `ScholarshipCoordinator` only.
        PRD §2.1: "When `X-User-Role` is `CommitteeReviewer`, `X-User-ID` is
        an opaque operator identifier not tied to any persisted entity."

        Design: Corner/rbac/rbac_reviewer_cannot_finalize_cycle
        """
        student = create_student()
        donor = create_donor()
        fund = create_fund()
        program = create_open_program(donor["id"], fund["id"])
        app = create_draft_application(student["id"], program["id"])
        get_success_data(api.submit_application(app["id"], COORD))
        cycle = create_cycle(program["id"], quorum_count=1)
        get_success_data(api.open_scoring(cycle["id"], COORD))
        submit_score_for(cycle["id"], app["id"], reviewer_id="rev_1")
        deliberating = validate_success(api.open_deliberation(cycle["id"], COORD))
        assert deliberating["status"] == "DELIBERATION"

        resp = api.finalize_cycle(cycle["id"], make_reviewer_headers("rev_1"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert validate_success(api.get_cycle(cycle["id"], COORD))["status"] == "DELIBERATION"

    def test_coordinator_cannot_confirm_disbursement(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target
        endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: `POST /api/disbursements/{id}/confirm` is authorized for
        `FinancialAidOfficer` only.
        PRD §2.10: "a disbursement is sent by a `ScholarshipCoordinator` and
        confirmed by a `FinancialAidOfficer`".

        Design: Corner/rbac/rbac_coordinator_cannot_confirm_disbursement
        """
        ctx = setup_accepted_award(amount_cents=500000)
        disb = get_success_data(api.create_disbursement(
            create_disbursement_payload(ctx["award"]["id"], amount_cents=500000),
            COORD,
        ))
        get_success_data(
            api.send_disbursement(
                disb["id"], make_coordinator_headers(COORDINATOR_USER_ID)
            )
        )

        # Even a fresh coordinator id lacks the role for confirm.
        resp = api.confirm_disbursement(
            disb["id"], make_coordinator_headers("coord_2")
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        current = validate_success(api.get_disbursement(disb["id"], COORD))
        assert current["status"] == "SENT"


class TestOwnership:
    def test_donor_cannot_acknowledge_others_report(self, api):
        """PRD §2.1: "When `X-User-Role` is `Donor`, `X-User-ID` is the `id`
        of the acting `Donor`. Ownership checks on a donor report compare the
        report's `donor_id` to `X-User-ID`."
        PRD §3.9: "the donor — and only that donor, with `X-User-ID` equal to
        the report's `donor_id` (otherwise `ERR_FORBIDDEN_OWNERSHIP`) — moves
        the report from `SENT` to `ACKNOWLEDGED`, its terminal state."
        PRD §3.9: "`thank_you_complete` is true exactly when every included
        award's letter sits in `DELIVERED` or `WAIVED`."

        Design: Corner/rbac/rbac_donor_cannot_acknowledge_others_report
        """
        donor_a = create_donor()
        donor_b = create_donor()
        # Donor B's window covers no awards: the empty inclusion set is
        # vacuously complete, so the report can be generated and sent.
        report = create_report(
            donor_b["id"], period_start="2026-01-01", period_end="2026-12-31"
        )
        generated = validate_success(api.generate_report(report["id"], COORD))
        assert generated["total_awards_count"] == 0
        assert generated["total_disbursed_cents"] == 0
        assert generated["thank_you_complete"] is True
        sent = validate_success(api.send_report(report["id"], COORD))
        assert sent["status"] == "SENT"

        resp = api.acknowledge_report(
            report["id"], make_donor_headers(donor_a["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)

        acknowledged = validate_success(
            api.acknowledge_report(
                report["id"], make_donor_headers(donor_b["id"])
            )
        )
        assert acknowledged["status"] == "ACKNOWLEDGED"

    def test_student_cannot_submit_others_application(self, api):
        """PRD §2.1: "When `X-User-Role` is `Student`, `X-User-ID` is the `id`
        of the acting `Student`. Ownership checks on any resource that
        references a student — an application, an award, a thank-you letter —
        compare the resource's student foreign key to `X-User-ID`."
        PRD §2.1: "a mismatch between the caller's identity and the
        resource's owner is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP
        403)."

        Design: Corner/rbac/rbac_student_cannot_submit_others_application
        """
        s_a = create_student()
        s_b = create_student()
        donor = create_donor()
        fund = create_fund()
        program = create_open_program(donor["id"], fund["id"])
        app_a = create_draft_application(s_a["id"], program["id"])

        resp = api.submit_application(
            app_a["id"], make_student_headers(s_b["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)
        assert validate_success(api.get_application(app_a["id"], COORD))["status"] == "DRAFT"

        # The owner submits fine.
        submitted = validate_success(
            api.submit_application(
                app_a["id"], make_student_headers(s_a["id"])
            )
        )
        assert submitted["status"] == "SUBMITTED"
