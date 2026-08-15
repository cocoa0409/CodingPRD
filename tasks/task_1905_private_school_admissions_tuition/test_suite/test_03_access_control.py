"""Access control: authentication context, role gates, family scope, and the
segregation-of-duties rule (PRD §2.1, §2.7)."""
from test_helpers import (
    ApiErrorId,
    NO_AUTH_HEADERS,
    create_cycle_payload,
    get_aid,
    get_application,
    get_cycle,
    make_aid_application,
    make_fao_headers,
    make_open_world,
    make_parent_headers,
    pin_clock,
    set_clock,
    setup_offered_application,
    setup_submitted_application,
    validate_error,
    validate_success,
    verify_aid,
)


class TestAuthenticationContext:
    def test_request_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "A request missing either header, or carrying an empty
        value for either, is rejected with `ERR_MISSING_USER_CONTEXT`."
        PRD §2.7: "Every request is evaluated against a fixed pipeline of
        validation layers, and the first failing layer wins — later layers are
        never consulted once a rejection is issued."

        Design: Corner/validations/request_missing_auth_headers_rejected
        """
        pin_clock()
        # Malformed body AND no auth headers: the auth layer runs first.
        resp = api.create_cycle({"bogus": True}, NO_AUTH_HEADERS)
        validate_error(resp, ApiErrorId.ERR_MISSING_USER_CONTEXT, 400)


class TestRoleGates:
    def test_parent_cannot_create_cycle_role_rejected(self, api):
        """PRD §2.1: "Every endpoint authorizes a fixed list of roles; a
        caller whose role is not on that list is rejected with
        `ERR_FORBIDDEN_ROLE`."
        PRD §4: POST /admissions/cycles authorizes AdmissionDirector only.

        Design: Corner/validations/parent_cannot_create_cycle_role_rejected
        """
        pin_clock()
        resp = api.create_cycle(create_cycle_payload(),
                                make_parent_headers("fam-a"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    def test_officer_cannot_verify_income(self, api, officer_headers):
        """PRD §3.4: "Verification is performed by a `FinancialAidOfficer`".
        PRD §2.1: "Every endpoint authorizes a fixed list of roles; a caller
        whose role is not on that list is rejected with `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/officer_cannot_verify_income
        """
        ctx = setup_submitted_application("fam-a", with_session=False)
        aid = make_aid_application(ctx["application"]["id"], "fam-a")
        resp = api.verify_aid(aid["id"], 9_500_000, officer_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
        assert get_aid(aid["id"])["verification_status"] == "SUBMITTED"

    def test_fao_cannot_issue_contract(self, api, fao_1_headers):
        """PRD §3.6: "An offer becomes binding paper when an
        `AdmissionOfficer` issues an enrollment contract."
        PRD §2.1: "Every endpoint authorizes a fixed list of roles; a caller
        whose role is not on that list is rejected with `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/fao_cannot_issue_contract
        """
        ctx = setup_offered_application("fam-a")  # no aid; OFFERED at close
        assert ctx["application"]["status"] == "OFFERED"
        resp = api.issue_contract(ctx["application"]["id"], fao_1_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
        assert get_application(ctx["application"]["id"])["status"] == "OFFERED"

    def test_parent_cannot_list_evaluations(self, api):
        """PRD §2.1: "Entrance evaluations and test sessions are staff-only
        records: `Parent` callers cannot list or read them."

        Design: Corner/rbac/parent_cannot_list_evaluations
        """
        make_open_world()
        resp = api.list_evaluations(make_parent_headers("fam-a"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    def test_officer_cannot_close_round(self, api, officer_headers,
                                        director_headers):
        """PRD §3.1: "Closing a round is how decisions are made" — a director
        operation; PRD §4 authorizes only AdmissionDirector on close-round.
        PRD §2.1: "Every endpoint authorizes a fixed list of roles; a caller
        whose role is not on that list is rejected with `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/officer_cannot_close_round
        """
        world = make_open_world(with_session=False)
        set_clock("2026-11-02T00:00:00Z")  # past the early deadline
        resp = api.close_round(world["cycle"]["id"], "EARLY", officer_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
        assert get_cycle(world["cycle"]["id"])["status"] == "OPEN"


class TestFamilyScope:
    def test_parent_reading_other_family_forbidden(self, api):
        """PRD §2.1: "A `Parent` acting on a resource outside that family scope
        is rejected with `ERR_FAMILY_SCOPE_VIOLATION`, and list endpoints
        auto-filter a `Parent` caller's results to their own family."

        Design: Corner/validations/parent_reading_other_family_forbidden
        """
        ctx = setup_submitted_application("fam-a")
        resp = api.get_application(ctx["application"]["id"],
                                   make_parent_headers("fam-b"))
        validate_error(resp, ApiErrorId.ERR_FAMILY_SCOPE_VIOLATION, 403)


class TestSegregationOfDuties:
    def test_verifier_cannot_finalize_own_verification(self, api):
        """PRD §3.4: "Finalizing an award requires `verification_status`
        `VERIFIED` (`ERR_AID_NOT_VERIFIED` otherwise), `award_status`
        `PROVISIONAL` (`ERR_AWARD_LOCKED` otherwise), and a caller whose
        `X-User-ID` differs from the application's `verified_by_user_id`
        (`ERR_SEGREGATION_OF_DUTIES` otherwise — the officer who verified the
        income may not finalize that award)."

        Design: Corner/validations/verifier_cannot_finalize_own_verification
        """
        ctx = setup_submitted_application("fam-a", with_session=False)
        aid = make_aid_application(ctx["application"]["id"], "fam-a")
        # fao-1 verifies; the same user's finalize must be refused.
        verify_aid(aid["id"], 9_500_000, officer_id="fao-1")
        resp = api.finalize_award(aid["id"], make_fao_headers("fao-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
        assert get_aid(aid["id"])["award_status"] == "PROVISIONAL"
        # A different officer finalizes the same aid application.
        resp = api.finalize_award(aid["id"], make_fao_headers("fao-2"))
        data = validate_success(resp, 200)
        assert data["award_status"] == "OFFERED"
        # Verified 9,500,000 hh4 -> EFC 630,000 -> need 2,370,000 (< cap).
        assert data["final_award_cents"] == 2_370_000
