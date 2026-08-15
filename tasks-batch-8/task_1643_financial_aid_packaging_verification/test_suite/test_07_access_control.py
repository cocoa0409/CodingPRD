"""Access control: authentication, role authorization, exclusive director
operations, and student ownership (PRD §2.1, §2.7 rungs 1, 2, and 8)."""
from test_helpers import (
    SSN_SELECTED_A,
    SSN_SELECTED_B,
    SSN_SELECTED_C,
    TEST_USERS,
    ApiErrorId,
    accept_lines,
    create_pj_case,
    create_student_payload,
    find_verification_case,
    get_package,
    get_success_data,
    get_verification_case,
    import_isir,
    make_student_headers,
    register_student,
    setup_notified_package,
    setup_open_aid_year,
    validate_error,
    validate_success,
)

OFFICER = TEST_USERS["aid_officer_headers"]


class TestAuthentication:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the caller's operational capacity. A request missing either header, or presenting an `X-User-Role` value that is not one of the declared role names, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/unauthenticated_missing_headers
        """
        resp = api.list_students({})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleAuthorization:
    def test_student_role_cannot_register_students(self, api):
        """PRD §2.1: "An authenticated caller whose role is not listed among an endpoint's authorized roles is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4 (endpoint table): "| POST | `/api/students` | Register a student record | AidOfficer |".

        Design: Corner/validations/forbidden_role_student_cannot_create_student
        """
        caller = register_student("555667777", full_name="Caller",
                                  email="caller@example.edu")
        resp = api.create_student(
            create_student_payload("444556666", full_name="Target",
                                   email="target@example.edu"),
            make_student_headers(caller["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_officer_cannot_waive_verification(self, api):
        """PRD §2.1: "`AidDirector` — the senior financial aid director. Owns the aid-year lifecycle, fund setup and activation, professional judgment decisions, SAP appeals, verification waivers, revision decisions, over-award verification, reconciliation, and the logical clock."
        PRD §2.1: "An authenticated caller whose role is not listed among an endpoint's authorized roles is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/roles/officer_cannot_waive_verification_director_only
        """
        env = setup_open_aid_year()
        student = register_student(SSN_SELECTED_A, full_name="Waive Target",
                                   email="wt@example.edu")
        import_isir(student["id"], env["aid_year"]["id"], agi_cents=4500000,
                    asset_net_worth_cents=50000)
        case = find_verification_case(student["id"])
        assert case is not None and case["status"] == "DOCUMENTS_REQUESTED"

        resp = api.waive_verification_case(
            case["id"], "Officer attempting director action", OFFICER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert (get_verification_case(case["id"])["status"]
                == "DOCUMENTS_REQUESTED")

    def test_officer_cannot_approve_pj_case(self, api):
        """PRD §2.1: "`AidDirector` — the senior financial aid director. Owns the aid-year lifecycle, fund setup and activation, professional judgment decisions, SAP appeals, verification waivers, revision decisions, over-award verification, reconciliation, and the logical clock."
        PRD §2.1: "An authenticated caller whose role is not listed among an endpoint's authorized roles is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/roles/officer_cannot_approve_pj_director_only
        """
        env = setup_open_aid_year()
        student = register_student(SSN_SELECTED_B, full_name="PJ RBAC",
                                   email="prbac@example.edu")
        import_isir(student["id"], env["aid_year"]["id"], agi_cents=4500000)
        pj = create_pj_case(student["id"], env["aid_year"]["id"],
                            requested_delta_cents=-500000)
        validate_success(api.begin_review_pj_case(pj["id"], OFFICER))
        current = get_success_data(api.get_pj_case(pj["id"], OFFICER))

        resp = api.approve_pj_case(pj["id"], current["version"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert (get_success_data(api.get_pj_case(pj["id"], OFFICER))["status"]
                == "UNDER_REVIEW")


class TestStudentOwnership:
    def test_other_student_cannot_accept_package(self, api):
        """PRD §3.6: "Acceptance is the student's decision and always ownership-checked: a `Student`-role caller whose `X-User-ID` is not the package's `student_id` is refused with `ERR_NOT_RESOURCE_OWNER`."
        PRD §2.7 (rung 8): "a Student-role caller may act only on their own package or notification, meaning `X-User-ID` equals the package's `student_id` — otherwise `ERR_NOT_RESOURCE_OWNER` (403)."

        Design: Corner/errors/error_not_resource_owner_other_student_accept
        """
        env = setup_notified_package(ssn=SSN_SELECTED_B)
        intruder = register_student(SSN_SELECTED_C, full_name="Intruder B",
                                    email="ib@example.edu")
        line = env["lines"][0]
        resp = accept_lines(env["package"]["id"], intruder["id"],
                            [(line["id"], line["offered_cents"])])
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        assert get_package(env["package"]["id"])["status"] == "NOTIFIED"
