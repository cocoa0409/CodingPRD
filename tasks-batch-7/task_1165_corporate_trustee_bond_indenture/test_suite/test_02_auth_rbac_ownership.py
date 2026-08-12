"""Authentication, authorization, ownership, and segregation of duties
(PRD §2.1, §2.8 rules 1–6)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId, NON_EXISTENT_UUID,
    create_indenture_payload, create_default_case_payload,
    create_endorsement_payload, create_ballot_payload,
    create_active_indenture_with_tranche, setup_indenture_with_positions,
    register_account, register_position, create_interest_run, fund_run,
    create_obligation, submit_certificate, declare_default, create_direction,
    create_annual_invoice, setup_collateral_scenario, verify_release_request,
    create_release_request,
    make_platform_admin_headers, make_trust_officer_headers,
    make_trust_manager_headers, make_issuer_headers, make_noteholder_headers,
)

ADMIN = make_platform_admin_headers("admin-1")


class TestAuthentication:
    def test_missing_role_header_unauthenticated(self, api):
        """PRD §2.1: "A request whose `X-User-Role` header is missing or does
        not name one of these five roles is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/missing_role_header_unauthenticated
        """
        headers_no_role = {"X-User-ID": "admin-1", "Content-Type": "application/json"}
        resp = api.create_indenture(create_indenture_payload(name="I1"), headers_no_role)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_authorization_checked_before_existence(self, api):
        """PRD §2.8: "Every request is validated against an ordered rule
        stack, and when several rules are violated at once the rejection
        carries the error of the **earliest** rule in the stack."
        PRD §2.8: "2. Authorization: the role is permitted on the endpoint —
        `ERR_FORBIDDEN`."
        PRD §2.8: "4. Existence: every path identifier and every referenced
        `*_id` in the payload resolves to an existing resource —
        `ERR_NOT_FOUND`."

        Design: Corner/validations/authorization_beats_not_found
        """
        headers = make_noteholder_headers("00000000-0000-0000-0000-000000000001")
        resp = api.confirm_default_case(NON_EXISTENT_UUID, headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestRolePermissions:
    def test_noteholder_cannot_execute_payment_run(self, api):
        """PRD §4: the `POST /payment-runs/{id}/execute` row authorizes
        TrustOfficer only.
        PRD §2.1: "A request whose role is valid but not permitted on the
        target endpoint per §4 is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/noteholder_cannot_execute_payment_run
        """
        ctx = setup_indenture_with_positions(amounts=(400000000,), holder_prefixes=("H-A",))
        run = create_interest_run(ctx["tranche"]["id"])
        fund_run(run["id"], 10166667, issuer_ref="issuer-1")

        resp = api.execute_payment_run(
            run["id"], make_noteholder_headers(ctx["accounts"][0]["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        from test_helpers import get_payment_run
        run_after = get_payment_run(run["id"])
        assert run_after["distribution_status"] == "SCHEDULED", "run unchanged"

    def test_issuer_cannot_review_certificate(self, api):
        """PRD §4: the `POST /covenant-certificates/{id}/review` row
        authorizes TrustOfficer only.
        PRD §2.1: "A request whose role is valid but not permitted on the
        target endpoint per §4 is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/issuer_cannot_review_certificate
        """
        indenture, tranche = create_active_indenture_with_tranche()
        obligation = create_obligation(indenture["id"])
        certificate = submit_certificate(obligation["id"], issuer_ref="issuer-1")

        resp = api.review_covenant_certificate(
            certificate["id"], {"decision": "ACCEPT"}, make_issuer_headers("issuer-1"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        from test_helpers import get_success_data
        cert_after = get_success_data(api.get_covenant_certificate(certificate["id"], ADMIN))
        assert cert_after["status"] == "SUBMITTED", "certificate unchanged"

    def test_trust_officer_cannot_confirm_default(self, api):
        """PRD §4: the `POST /default-cases/{id}/confirm` row authorizes
        TrustManager only.
        PRD §2.1: "A request whose role is valid but not permitted on the
        target endpoint per §4 is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/trust_officer_cannot_confirm_default
        """
        indenture, tranche = create_active_indenture_with_tranche()
        case = declare_default(indenture["id"], officer_id="officer-1")

        # A different officer id attempts the confirm: the role gate fires
        # before any segregation-of-duties comparison.
        resp = api.confirm_default_case(case["id"], make_trust_officer_headers("officer-2"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestOwnership:
    def test_noteholder_endorsement_for_other_account_rejected(self, api):
        """PRD §2.1: "When `X-User-Role` is `Noteholder`, `X-User-ID` is the
        `id` of the acting `NoteholderAccount`; ownership checks on any
        operation that names a `noteholder_account_id` compare that value to
        `X-User-ID`, and a mismatch is rejected with `ERR_OWNERSHIP_VIOLATION`
        (HTTP 403)."

        Design: Corner/validations/ownership_noteholder_endorse_for_other_account_rejected
        """
        ctx = setup_indenture_with_positions(amounts=(400000000, 600000000),
                                             holder_prefixes=("H-A", "H-B"))
        case = declare_default(ctx["indenture"]["id"], officer_id="officer-1")
        from test_helpers import confirm_default
        case = confirm_default(case["id"])
        direction = create_direction(case["id"], "ACCELERATE")

        account_a, account_b = ctx["accounts"]
        # Caller is account A but names account B in the payload.
        resp = api.endorse_direction(
            direction["id"], create_endorsement_payload(account_b["id"]),
            make_noteholder_headers(account_a["id"]))
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_VIOLATION)

    def test_issuer_funding_foreign_indenture_rejected(self, api):
        """PRD §2.1: "the issuer owns exactly those indentures whose
        `issuer_ref` equals `X-User-ID`, and issuer-scoped operations on an
        indenture the caller does not own are rejected with
        `ERR_OWNERSHIP_VIOLATION` (HTTP 403)."
        PRD §2.1: "Ownership enforcement applies to every operation where an
        `Issuer` or `Noteholder` acts on scoped resources: submitting a
        covenant certificate, funding a payment run, creating or revoking a
        consent solicitation, requesting a collateral release, paying or
        disputing a fee invoice, endorsing a direction, withdrawing an
        endorsement, and casting a ballot."

        Design: Corner/validations/ownership_issuer_fund_foreign_indenture_rejected
        """
        ctx = setup_indenture_with_positions(amounts=(400000000,), holder_prefixes=("H-A",))
        run = create_interest_run(ctx["tranche"]["id"])

        resp = api.fund_payment_run(
            run["id"], {"amount_cents": 10166667}, make_issuer_headers("issuer-9"))
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_VIOLATION)

        from test_helpers import get_payment_run
        run_after = get_payment_run(run["id"])
        assert run_after["funded_amount_cents"] == 0, "no funds deposited"


class TestSegregationOfDuties:
    def test_declarer_cannot_confirm_own_default(self, api):
        """PRD §3.5: "A `TrustManager` confirms an `ALLEGED` case, and the
        confirming `X-User-ID` must differ from `declared_by_user_id`; the
        same individual attempting both halves is rejected with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/sod_declare_confirm_same_user_rejected
        """
        indenture, tranche = create_active_indenture_with_tranche()
        case = declare_default(indenture["id"], officer_id="officer-1")
        assert case["declared_by_user_id"] == "officer-1"

        # Same X-User-ID, but wearing the TrustManager role.
        resp = api.confirm_default_case(case["id"], make_trust_manager_headers("officer-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        from test_helpers import get_default_case
        case_after = get_default_case(case["id"])
        assert case_after["status"] == "ALLEGED", "case unchanged"

    def test_verifier_cannot_decide_own_release_request(self, api):
        """PRD §3.7: "segregation of duties first — the decider's `X-User-ID`
        must differ from `verified_by_user_id`, else
        `ERR_SEGREGATION_OF_DUTIES`"

        Design: Corner/validations/sod_verify_decide_same_user_rejected
        """
        ctx = setup_collateral_scenario(
            item1_type="SECURITIES", item1_value=1000000000,
            item2_type="REAL_ESTATE", item2_value=500000000,
            request_type="RELEASE")
        request = verify_release_request(ctx["request"]["id"], officer_id="officer-1")
        assert request["verified_by_user_id"] == "officer-1"

        resp = api.decide_collateral_release_request(
            request["id"], {"decision": "APPROVE"}, make_trust_manager_headers("officer-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        from test_helpers import get_release_request
        request_after = get_release_request(request["id"])
        assert request_after["status"] == "VERIFIED", "request unchanged"

    def test_drafter_cannot_issue_own_invoice(self, api):
        """PRD §3.8: "a `TrustManager` issues a `DRAFT` — or, later, an
        `AMENDED` — invoice, and the issuer's `X-User-ID` must differ from
        `drafted_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`"

        Design: Corner/validations/sod_draft_issue_same_user_rejected
        """
        indenture, tranche = create_active_indenture_with_tranche()
        invoice = create_annual_invoice(indenture["id"], officer_id="officer-1")
        assert invoice["drafted_by_user_id"] == "officer-1"

        resp = api.issue_fee_invoice(invoice["id"], make_trust_manager_headers("officer-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        from test_helpers import get_fee_invoice
        invoice_after = get_fee_invoice(invoice["id"])
        assert invoice_after["status"] == "DRAFT", "invoice unchanged"
