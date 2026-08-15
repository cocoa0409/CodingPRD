"""Certificate drafting and the issuance gate chain."""
from test_helpers import (
    ApiErrorId,
    assert_certificate,
    assert_instant_equals,
    complete_initial_visit,
    create_active_agreement,
    create_applicant_client,
    create_approved_facility,
    create_approved_ingredient,
    create_assessed_line,
    create_certificate_payload,
    create_certifiable_product,
    create_draft_product,
    create_annual_invoice,
    create_paid_annual_invoice,
    create_prospect_client,
    create_facility_for,
    get_client,
    make_client_contact_headers,
    make_officer_headers,
    setup_certified_client,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestIssuanceGateChain:
    def test_certificate_double_issue_rejected(self, api, officer_headers):
        """PRD section 3.7: "The certificate must be `DRAFT`
        (`ERR_CERTIFICATE_INVALID_STATE`)."

        Design: Corner/state_machines/certificate_double_issue_rejected
        """
        ctx = setup_certified_client(legal_name="SM7 Co")
        assert ctx["certificate"]["status"] == "ACTIVE"
        resp = api.issue_certificate(ctx["certificate"]["id"], officer_headers)
        validate_error(resp, ApiErrorId.ERR_CERTIFICATE_INVALID_STATE)

    def test_issue_with_empty_facility_scope_rejected(self, api,
                                                      officer_headers):
        """PRD section 3.7: "Every facility in scope must be `APPROVED`
        (`ERR_FACILITY_NOT_APPROVED`), and the scope must be non-empty
        (`ERR_CERTIFICATE_SCOPE_EMPTY`, HTTP 422)."

        Design: Corner/validations/issue_with_empty_facility_scope_rejected
        """
        client = create_applicant_client(legal_name="ES Co")
        create_active_agreement(client["id"])
        cert = validate_success(api.create_certificate(
            create_certificate_payload(client["id"], [], []), officer_headers),
            201)
        resp = api.issue_certificate(cert["id"],
                                     make_officer_headers("co-1"))
        validate_error(resp, ApiErrorId.ERR_CERTIFICATE_SCOPE_EMPTY)

    def test_certificate_issue_gated_on_facility_approved(
            self, api, officer_headers, reviewer_headers):
        """PRD section 3.7: "Every facility in scope must be `APPROVED`
        (`ERR_FACILITY_NOT_APPROVED`)". PRD section 3.1: "The transition from
        `APPLICANT` to `CERTIFIED` is never called directly: it happens as a
        bubble-up the first time one of the client's certificates reaches
        `ACTIVE` through issuance."

        Design: Difficulty/cross_entity_state_dependency/certificate_issue_gated_on_facility_approved
        """
        client = create_applicant_client(legal_name="Gate Co")
        cid = client["id"]
        # Facility has a COMPLETED initial visit and assessed line, but the
        # approval call is deliberately withheld.
        facility = create_facility_for(cid, name="G Plant")
        create_assessed_line(cid, facility["id"])
        complete_initial_visit(facility["id"])
        agreement = create_active_agreement(cid)
        create_paid_annual_invoice(cid, agreement["id"])
        ing = create_approved_ingredient(cid, name="IngG")
        product = create_certifiable_product(cid, [ing["id"]], name="PG")
        cert = validate_success(api.create_certificate(
            create_certificate_payload(cid, [facility["id"]], [product["id"]]),
            officer_headers), 201)

        resp = api.issue_certificate(cert["id"], make_officer_headers("co-1"))
        validate_error(resp, ApiErrorId.ERR_FACILITY_NOT_APPROVED)

        validate_success(api.approve_facility(facility["id"], reviewer_headers))
        issued = validate_success(api.issue_certificate(
            cert["id"], make_officer_headers("co-1")))
        assert issued["status"] == "ACTIVE"
        assert get_client(cid)["status"] == "CERTIFIED", (
            "first issuance bubbles the client APPLICANT -> CERTIFIED")

    def test_certificate_issue_gated_on_every_scope_facility(
            self, api, officer_headers, reviewer_headers):
        """PRD section 3.7: "Every facility in scope must be `APPROVED`
        (`ERR_FACILITY_NOT_APPROVED`)".

        Design: Difficulty/cross_entity_state_dependency/certificate_issue_gated_on_facility_approved
        """
        client = create_applicant_client(legal_name="Gate Co 2")
        cid = client["id"]
        approved, _line = create_approved_facility(cid, name="G2 Main")
        pending = create_facility_for(cid, name="G2 Annex")
        create_assessed_line(cid, pending["id"])
        complete_initial_visit(pending["id"])
        agreement = create_active_agreement(cid)
        create_paid_annual_invoice(cid, agreement["id"])
        ing = create_approved_ingredient(cid, name="IngG2")
        product = create_certifiable_product(cid, [ing["id"]], name="PG2")
        cert = validate_success(api.create_certificate(
            create_certificate_payload(
                cid, [approved["id"], pending["id"]], [product["id"]]),
            officer_headers), 201)

        resp = api.issue_certificate(cert["id"], make_officer_headers("co-1"))
        validate_error(resp, ApiErrorId.ERR_FACILITY_NOT_APPROVED, )

        validate_success(api.approve_facility(pending["id"], reviewer_headers))
        issued = validate_success(api.issue_certificate(
            cert["id"], make_officer_headers("co-1")))
        assert issued["status"] == "ACTIVE"

    def test_certificate_with_cross_client_facility_rejected(
            self, api, officer_headers):
        """PRD section 3.7: "Every referenced facility and product must belong
        to the same client (`ERR_CROSS_CLIENT_REFERENCE`)".

        Design: Corner/validations/certificate_with_cross_client_facility_rejected
        """
        client_a = create_applicant_client(legal_name="XA Co")
        client_b = create_prospect_client(legal_name="XB Co",
                                          contact_email="xb@x.com")
        facility_b = create_facility_for(client_b["id"], name="FB")
        resp = api.create_certificate(
            create_certificate_payload(client_a["id"], [facility_b["id"]], []),
            officer_headers)
        validate_error(resp, ApiErrorId.ERR_CROSS_CLIENT_REFERENCE)

    def test_issuer_who_recorded_payment_rejected_segregation(
            self, api, officer_headers):
        """PRD section 2.9: "issuance requires a fee invoice whose
        `paid_recorded_by` differs from the issuer's `X-User-ID`, else
        `ERR_SEGREGATION_OF_DUTIES_ISSUANCE` (HTTP 403)."

        Design: Corner/validations/issuer_who_recorded_payment_rejected_segregation
        """
        # The fee was recorded under the operator id "am-1"; an issuer
        # presenting that same user id hits the segregation wall.
        client = create_applicant_client(legal_name="RB4 Co")
        cid = client["id"]
        facility, _line = create_approved_facility(cid)
        agreement = create_active_agreement(cid)
        create_paid_annual_invoice(cid, agreement["id"], payer_id="am-1")
        ing = create_approved_ingredient(cid, name="IR4")
        product = create_certifiable_product(cid, [ing["id"]], name="PR4")
        cert = validate_success(api.create_certificate(
            create_certificate_payload(cid, [facility["id"]], [product["id"]]),
            officer_headers), 201)

        resp = api.issue_certificate(cert["id"], make_officer_headers("am-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_ISSUANCE)

        issued = validate_success(api.issue_certificate(
            cert["id"], make_officer_headers("co-9")))
        assert issued["status"] == "ACTIVE", (
            "a distinct issuer id passes the segregation wall")

    def test_issue_safety_product_not_certifiable_beats_fiscal_unpaid(
            self, api, officer_headers):
        """PRD section 3.7: "Every certificate entry must be `INCLUDED` and
        every listed product must be `CERTIFIABLE`
        (`ERR_PRODUCT_NOT_CERTIFIABLE`)." PRD section 2.8: "Only then are
        entity-state gates evaluated (the family of `ERR_*_INVALID_STATE`
        errors), then business-safety compliance gates (documentation, open
        findings, equipment, segregation, risk), then cross-entity referential
        integrity, then temporal-window rules, then uniqueness and cardinality
        constraints, and finally fiscal gates".

        Design: Difficulty/priority_pair_validation_conflict/issue_safety_product_not_certifiable_beats_fiscal_unpaid
        """
        client = create_applicant_client(legal_name="Prio1 Co")
        cid = client["id"]
        facility, _line = create_approved_facility(cid)
        agreement = create_active_agreement(cid)
        invoice = create_annual_invoice(cid, agreement["id"])
        assert invoice["status"] == "ISSUED", "the fiscal violation stays armed"
        ing = create_approved_ingredient(cid, name="IngP1")
        product = create_draft_product(cid, [ing["id"]], name="PP1")
        cc = make_client_contact_headers(cid)
        validate_success(api.submit_product_review(product["id"], cc))
        cert = validate_success(api.create_certificate(
            create_certificate_payload(cid, [facility["id"]], [product["id"]]),
            officer_headers), 201)

        resp = api.issue_certificate(cert["id"], make_officer_headers("co-1"))
        validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_CERTIFIABLE)

        reread_invoice = validate_success(api.get_invoice(invoice["id"],
                                                          officer_headers))
        assert reread_invoice["status"] == "ISSUED"
        reread_cert = validate_success(api.get_certificate(cert["id"],
                                                           officer_headers))
        assert reread_cert["status"] == "DRAFT", "no partial issue"

    def test_issue_fiscal_gate_fires_once_safety_passes(
            self, api, officer_headers):
        """PRD section 3.7: "Then the fiscal gate: for an initial certificate,
        an `ANNUAL_CERTIFICATION` invoice on that `ACTIVE` agreement must exist
        in `PAID` status; for a renewal child, a `RENEWAL` invoice with
        `related_certificate_id` naming this child must be `PAID`; failure is
        `ERR_CERTIFICATION_FEE_UNPAID` (HTTP 402)."

        Design: Difficulty/priority_pair_validation_conflict/issue_safety_product_not_certifiable_beats_fiscal_unpaid
        """
        client = create_applicant_client(legal_name="Prio1 Co B")
        cid = client["id"]
        facility, _line = create_approved_facility(cid)
        agreement = create_active_agreement(cid)
        invoice = create_annual_invoice(cid, agreement["id"])
        assert invoice["status"] == "ISSUED"
        ing = create_approved_ingredient(cid, name="IngP1B")
        product = create_certifiable_product(cid, [ing["id"]], name="PP1B")
        cert = validate_success(api.create_certificate(
            create_certificate_payload(cid, [facility["id"]], [product["id"]]),
            officer_headers), 201)

        resp = api.issue_certificate(cert["id"], make_officer_headers("co-1"))
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_FEE_UNPAID)


class TestIssuedCertificateReadModel:
    def test_certificate_computed_read_after_issue(self, api, officer_headers):
        """PRD section 3.7: "A successful issuance sets `issued_at` to the
        current logical instant and computes `valid_until` by term variant: an
        `ANNUAL` certificate is valid for exactly 365 days from `issued_at`".
        PRD section 3.7: "Issuance also sets `scope_status` to `FULL`,
        recomputes `active_product_count`".

        Design: Corner/endpoints/certificate_computed_read_after_issue
        """
        ctx = setup_certified_client(legal_name="CR Co",
                                     issue_clock="2026-08-02T10:00:00Z")
        cert = validate_success(api.get_certificate(ctx["certificate"]["id"],
                                                    officer_headers))
        assert_certificate(cert)
        assert_instant_equals(cert["issued_at"], "2026-08-02T10:00:00Z",
                              "issued_at")
        assert_instant_equals(cert["valid_until"], "2027-08-02T10:00:00Z",
                              "issued_at + 365 days")
        assert cert["scope_status"] == "FULL"
        assert cert["active_product_count"] == 1

    def test_issue_response_contains_derived_fields_immediately(
            self, api, officer_headers):
        """PRD section 2.2: "Unless otherwise noted, operations that create or
        modify a resource will return the created or updated resource object in
        the data field." PRD section 3.7: "A successful issuance sets
        `issued_at` to the current logical instant and computes `valid_until` by
        term variant".

        Design: Corner/consistency_model/issue_response_contains_derived_fields_immediately
        """
        ctx = setup_certified_client(legal_name="IM Co",
                                     issue_clock="2026-08-02T10:00:00Z")
        issued = ctx["certificate"]
        assert issued["status"] == "ACTIVE"
        assert_instant_equals(issued["issued_at"], "2026-08-02T10:00:00Z",
                              "issued_at in the issue response")
        assert_instant_equals(issued["valid_until"], "2027-08-02T10:00:00Z",
                              "valid_until in the issue response")
        assert issued["scope_status"] == "FULL"
        assert issued["active_product_count"] == 1
        assert get_client(ctx["client"]["id"])["status"] == "CERTIFIED", (
            "the client bubble-up is visible on the very next read")


class TestCertificateEntries:
    def test_certificate_product_double_delete_rejected(self, api,
                                                        officer_headers):
        """PRD section 3.7: "acting on an already-`REMOVED` entry yields
        `ERR_CERTIFICATE_PRODUCT_INVALID_STATE`."

        Design: Corner/state_machines/certificate_product_double_delete_rejected
        """
        client = create_applicant_client(legal_name="DD Co")
        cid = client["id"]
        ing = create_approved_ingredient(cid, name="ID")
        product = create_draft_product(cid, [ing["id"]], name="PD")
        cert = validate_success(api.create_certificate(
            create_certificate_payload(cid, [], [product["id"]]),
            officer_headers), 201)
        entries, _meta = validate_paginated(
            api.list_certificate_products(cert["id"], officer_headers))
        entry_id = entries[0]["id"]
        removed = validate_success(
            api.delete_certificate_product(entry_id, officer_headers))
        assert removed["status"] == "REMOVED"
        resp = api.delete_certificate_product(entry_id, officer_headers)
        validate_error(resp, ApiErrorId.ERR_CERTIFICATE_PRODUCT_INVALID_STATE)


class TestSuspendReinstateCycle:
    def _certified(self):
        return setup_certified_client(legal_name="Cyc Cert Co")

    def test_certificate_suspend_reinstate_cycle_terminal_lockdown(
            self, api, officer_headers):
        """PRD section 3.7: "suspension, revocation, and expiry all bubble up to
        recompute the client, dropping a `CERTIFIED` client with zero remaining
        `ACTIVE` certificates to `SUSPENDED`." PRD section 3.7: "A successful
        reinstate bubbles a `SUSPENDED` client back to `CERTIFIED`." PRD section
        3.7: "Revocation is allowed from `ACTIVE` or `SUSPENDED` (and, on the
        system cascade of client withdrawal or termination, from `DRAFT` as
        well) and is terminal".

        Design: Difficulty/non_linear_state_machine/certificate_suspend_reinstate_cycle_terminal_lockdown
        """
        ctx = self._certified()
        cert_id = ctx["certificate"]["id"]
        cid = ctx["client"]["id"]

        suspended = validate_success(api.suspend_certificate(cert_id,
                                                             officer_headers))
        assert suspended["status"] == "SUSPENDED"
        assert get_client(cid)["status"] == "SUSPENDED"

        reinstated = validate_success(api.reinstate_certificate(cert_id,
                                                                officer_headers))
        assert reinstated["status"] == "ACTIVE"
        assert get_client(cid)["status"] == "CERTIFIED", "cycle closed"

        validate_success(api.suspend_certificate(cert_id, officer_headers))
        revoked = validate_success(api.revoke_certificate(cert_id,
                                                          officer_headers))
        assert revoked["status"] == "REVOKED"
        assert get_client(cid)["status"] == "SUSPENDED"

        resp = api.reinstate_certificate(cert_id, officer_headers)
        validate_error(resp, ApiErrorId.ERR_CERTIFICATE_INVALID_STATE)

    def test_reinstate_does_not_extend_valid_until(self, api, officer_headers):
        """PRD section 3.7: "Downtime is never compensated: `valid_until` is
        unchanged by reinstatement."

        Design: Difficulty/non_linear_state_machine/certificate_suspend_reinstate_cycle_terminal_lockdown
        """
        ctx = setup_certified_client(legal_name="Cyc Cert Co 2",
                                     issue_clock="2026-08-15T10:00:00Z")
        cert_id = ctx["certificate"]["id"]
        original_valid_until = ctx["certificate"]["valid_until"]
        assert_instant_equals(original_valid_until, "2027-08-15T10:00:00Z",
                              "issued_at + 365 days")

        validate_success(api.suspend_certificate(cert_id, officer_headers))
        reinstated = validate_success(api.reinstate_certificate(cert_id,
                                                                officer_headers))
        assert reinstated["status"] == "ACTIVE"
        assert reinstated["valid_until"] == original_valid_until, (
            "reinstatement must not shift valid_until")
