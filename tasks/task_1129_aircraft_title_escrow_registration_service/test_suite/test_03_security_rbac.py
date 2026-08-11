"""Authentication, authorization, entity-backed identity, and segregation of
duties (PRD §2.1, §3.6)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_escrow_file_payload,
    draft_disbursement,
    make_lender_headers,
    make_manager_headers,
    request_lien_release,
    setup_cleared_file,
    setup_file_with_lien,
    validate_error,
    validate_success,
)

OFFICER = TEST_USERS["officer_headers"]
MANAGER = TEST_USERS["manager_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


class TestAuthentication:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role the
        system does not know, is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/v_missing_auth_headers_returns_unauthenticated
        """
        res = api.get_aircraft(
            "00000000-0000-4000-8000-0000000000aa", headers={},
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestRoleAuthorization:
    def test_auditor_cannot_create_party(self, api, auditor_headers):
        """PRD §2.1: "A request whose role is known but is not on the endpoint's
        authorized list is rejected with `ERR_UNAUTHORIZED_ROLE`."
        PRD §2.1: "`Auditor` reads everything and writes nothing."

        Design: Corner/validations/v_auditor_create_party_returns_unauthorized
        """
        res = api.create_party(
            {"party_type": "BUYER", "legal_name": "Buyer Co"}, auditor_headers
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)

    def test_lender_cannot_approve_disbursement(self, api):
        """PRD §2.1: "A request whose role is known but is not on the endpoint's
        authorized list is rejected with `ERR_UNAUTHORIZED_ROLE`."
        PRD §3.6: "Approval is reserved to an `EscrowManager`."

        Design: Corner/rbac/r_lender_cannot_approve
        """
        ctx = setup_cleared_file(with_lender=True)
        instruction = draft_disbursement(
            ctx["file"]["id"], ctx["lender"]["id"], 1_000, "OTHER",
        )
        assert instruction["status"] == "PENDING_APPROVAL"
        res = api.approve_disbursement(
            instruction["id"], make_lender_headers(ctx["lender"]["id"])
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)
        after = validate_success(api.get_disbursement(instruction["id"], OFFICER), 200)
        assert after["status"] == "PENDING_APPROVAL"

    def test_manager_cannot_quote_release(self, api, manager_headers):
        """PRD §2.1: "A request whose role is known but is not on the endpoint's
        authorized list is rejected with `ERR_UNAUTHORIZED_ROLE`."
        PRD §3.4: "A `LenderRep` then submits a payoff quote, but only when
        `X-User-ID` equals the lien's `lienor_party_id`; any other identity is
        rejected with `ERR_FORBIDDEN_IDENTITY`."

        Design: Corner/rbac/r_manager_cannot_quote
        """
        ctx = setup_file_with_lien(amount_cents=100_000, filed_at="2025-05-05")
        release = request_lien_release(ctx["lien"]["id"])
        res = api.quote_release(
            release["id"],
            {
                "payoff_basis": "FLAT",
                "quoted_payoff_cents": 100_000,
                "good_through_date": "2026-06-30",
            },
            manager_headers,
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)
        after = validate_success(
            api.list_lien_releases(ctx["lien"]["id"], OFFICER), 200
        )
        assert after[0]["status"] == "REQUESTED"

    def test_officer_cannot_accept_trust(self, api, officer_headers):
        """PRD §2.1: "A request whose role is known but is not on the endpoint's
        authorized list is rejected with `ERR_UNAUTHORIZED_ROLE`."
        PRD §3.7: "Acceptance is an `EscrowManager` action and carries the
        trust-overlap guard: there must be no other `ACCEPTED` `TrustAgreement`
        for the same aircraft whose `[effective_date, expiry_date]` interval
        strictly overlaps the candidate's interval."

        Design: Corner/rbac/r_officer_cannot_accept_trust
        """
        from test_helpers import (
            create_aircraft,
            create_party,
            create_trust_agreement,
            submit_trust_agreement,
        )

        aircraft = create_aircraft(n_number="N172OA", serial_number="S-45")
        trustee = create_party("TRUSTEE", "Trustee Co", is_citizenship_verified=True)
        trust = create_trust_agreement(aircraft["id"], trustee["id"])
        submit_trust_agreement(trust["id"])
        res = api.accept_trust_agreement(trust["id"], officer_headers)
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)
        after = validate_success(api.get_trust_agreement(trust["id"], OFFICER), 200)
        assert after["status"] == "SUBMITTED"


class TestLenderEntityBackedIdentity:
    def test_lender_quote_on_other_partys_lien_forbidden(self, api):
        """PRD §2.1: "Quoting or confirming receipt of a lien release compares the
        lien's `lienor_party_id` against `X-User-ID`; a mismatch is rejected with
        `ERR_FORBIDDEN_IDENTITY`."

        Design: Corner/validations/v_lender_quote_other_lien_returns_forbidden
        """
        ctx = setup_file_with_lien(amount_cents=100_000, filed_at="2025-05-05")
        release = request_lien_release(ctx["lien"]["id"])
        res = api.quote_release(
            release["id"],
            {
                "payoff_basis": "FLAT",
                "quoted_payoff_cents": 100_000,
                "good_through_date": "2026-06-30",
            },
            make_lender_headers(ctx["buyer"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_IDENTITY, expected_status=403)
        after = validate_success(
            api.list_lien_releases(ctx["lien"]["id"], OFFICER), 200
        )
        assert after[0]["status"] == "REQUESTED"


class TestSegregationOfDuties:
    def test_drafter_cannot_self_approve_but_other_manager_can(self, api):
        """PRD §3.6: "Segregation of duties is enforced structurally: the
        approver's `X-User-ID` must differ from the instruction's
        `created_by_user_id`, and an approval attempted by the drafter is rejected
        with `ERR_SEGREGATION_OF_DUTIES`."
        PRD §3.6: "A successful approval stamps `approved_by_user_id` and moves
        the instruction from `PENDING_APPROVAL` to `APPROVED`."

        Design: Corner/errors/er_segregation_of_duties_on_self_approve
        """
        ctx = setup_cleared_file()
        instruction = draft_disbursement(
            ctx["file"]["id"], ctx["seller"]["id"], 1_000, "SELLER_PROCEEDS",
            drafter_headers=make_manager_headers("mgr-1"),
        )
        assert instruction["created_by_user_id"] == "mgr-1"

        self_approve = api.approve_disbursement(
            instruction["id"], make_manager_headers("mgr-1")
        )
        validate_error(
            self_approve, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403
        )

        approved = validate_success(
            api.approve_disbursement(instruction["id"], make_manager_headers("mgr-2")),
            200,
        )
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "mgr-2"


class TestOfficerFullLifecycle:
    def test_officer_runs_full_file_lifecycle_to_closed(self, api, officer_headers):
        """PRD §2.1: "`EscrowOfficer` runs the day-to-day file: registering
        aircraft, opening files, ordering searches, recording deposits, drafting
        filings and documents, and coordinating releases."
        PRD §3.10: "A successful close stamps `closed_at` to the logical instant,
        freezes the live money figures, transitions the file from `FUNDED` to
        `CLOSED`, and increments the file's `version` by 1."

        Design: Corner/rbac/r_officer_can_run_full_file_lifecycle
        """
        from test_helpers import (
            close_escrow_file,
            create_deposit,
            get_escrow_file,
            get_statement,
            setup_cleared_file,
        )

        ctx = setup_cleared_file(file_overrides={"purchase_price_cents": 10_000_000})
        due = get_statement(ctx["file"]["id"])["buyer_amount_due_cents"]
        assert due == 10_150_000
        create_deposit(ctx["file"]["id"], ctx["buyer"]["id"], due)
        funded = get_escrow_file(ctx["file"]["id"])
        assert funded["status"] == "FUNDED"
        closed = close_escrow_file(ctx["file"]["id"])
        assert closed["status"] == "CLOSED"
