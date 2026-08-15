"""RBAC and authentication: role denial, ownership, auth headers (PRD §2.1)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    build_user_headers,
    create_customer,
    create_aircraft,
    create_engagement,
    create_invoice,
    create_scheme,
    get_program,
    issue_invoice,
    make_customer_rep_headers,
    setup_booked_program,
    submit_scheme,
    validate_error,
)
from test_helpers.factories import create_customer_payload, create_program_payload


class TestAuthentication:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "Requests missing either header, or presenting a role the
        system does not recognize, are rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/validations/missing_auth_header_returns_401
        """
        resp = api.create_customer(create_customer_payload(), headers=None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleDenial:
    def test_design_lead_cannot_advance_program(self, api, design_lead_headers):
        """PRD §2.1: "an attempt to perform an action outside of the caller's
        designated role is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: POST /completion/programs/{id}/advance is ProgramManager-only.

        Design: Corner/rbac/design_lead_cannot_advance_program
        """
        ctx = create_engagement()
        resp = api.advance_program(
            ctx["program"]["id"], {"to_phase": "BOOKED"}, design_lead_headers
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert get_program(ctx["program"]["id"])["status"] == "QUOTED"

    def test_customer_rep_cannot_create_program(self, api):
        """PRD §2.1: "an attempt to perform an action outside of the caller's
        designated role is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: POST /completion/programs is ProgramManager-only — the
        entity-backed CustomerRep role is denied even for its own customer.

        Design: Corner/rbac/customer_cannot_create_program
        """
        ctx = create_engagement()
        # A second aircraft so only the role check can fail.
        aircraft = create_aircraft(ctx["customer"]["id"], tail_number="N777QQ")
        resp = api.create_program(
            create_program_payload(
                aircraft_id=aircraft["id"], customer_id=ctx["customer"]["id"]
            ),
            make_customer_rep_headers(ctx["customer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_finance_clerk_cannot_pay_invoice(self, api, finance_clerk_headers):
        """PRD §2.1: "an attempt to perform an action outside of the caller's
        designated role is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: POST /completion/invoices/{id}/pay is CustomerRep-only;
        PRD §3.12: "The customer pays an `ISSUED` invoice — ownership-checked".

        Design: Corner/rbac/finance_clerk_cannot_pay_invoice
        """
        ctx = setup_booked_program()
        invoice = create_invoice(ctx["program"]["id"], "DEPOSIT")
        issue_invoice(invoice["id"])
        resp = api.pay_invoice(invoice["id"], finance_clerk_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestCustomerRepOwnership:
    def test_other_customers_rep_cannot_approve_scheme(self, api):
        """PRD §2.1: "When `X-User-Role` is `CustomerRep`, `X-User-ID` is the
        `id` of the acting Customer; ownership checks on any resource that
        references a Customer compare the program's `customer_id` field to
        `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN_OWNERSHIP`
        (HTTP 403)."

        Design: Corner/rbac/customer_rep_ownership_enforced
        """
        customer_a = create_customer(
            name="Apex Aviation LLC", contact_email="ops@apex.example"
        )
        customer_b = create_customer(name="Borealis Air",
                                     contact_email="ops@borealis.example")
        aircraft = create_aircraft(customer_a["id"])
        from test_helpers import create_program
        program = create_program(aircraft["id"], customer_a["id"])
        scheme = create_scheme(program["id"])
        submit_scheme(scheme["id"])

        resp = api.approve_paint_scheme(
            scheme["id"],
            {"expected_program_version": get_program(program["id"])["version"]},
            make_customer_rep_headers(customer_b["id"]),  # right role, wrong owner
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)
        from test_helpers import validate_success
        scheme_after = validate_success(
            api.get_paint_scheme(scheme["id"], TEST_USERS["design_lead_headers"])
        )
        assert scheme_after["status"] == "SUBMITTED"
