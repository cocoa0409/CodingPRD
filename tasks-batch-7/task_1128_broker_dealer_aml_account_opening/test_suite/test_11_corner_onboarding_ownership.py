"""Corner queue: reps, customers, CIP documents, suspended reps, ownership content rules."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_owner,
    api_client,
    create_certification,
    create_customer,
    create_rep,
    get_account,
    is_valid_uuid,
    run_daily_sweep,
    set_clock,
    setup_open_account,
    submit_and_verify_document,
    submit_document,
    validate_error,
    validate_success,
)
from test_helpers.test_users import make_rep_headers


class TestRepCreationAppliesDefaults:
    def test_rep_created_active_with_server_id(self, api):
        """PRD §3.1: "A rep starts `ACTIVE`."
        PRD §2.4: "`id` (string): a server-minted UUID, with no type prefix."

        Design: Corner/entities/rep_creation_applies_defaults
        """
        rep = create_rep(full_name="Default Rep", crd_number="CRD-ENT1")
        assert rep["status"] == "ACTIVE"
        assert is_valid_uuid(rep["id"])
        resp = api_client.get_rep(rep["id"], TEST_USERS["admin_headers"])
        reread = validate_success(resp)
        assert reread["status"] == "ACTIVE"


class TestCustomerCreationMissingRequiredTaxId:
    def test_missing_tax_id_rejected_invalid_request(self, api):
        """PRD §3.1: "A `RegisteredRep` opens a customer by providing `customer_type`
        (`INDIVIDUAL` or `LEGAL_ENTITY`), `full_name`, `tax_id`, and
        `country_risk_tier`" — `tax_id` is a required input.
        PRD §2.9: "21. Request body shape — malformed bodies, missing required fields,
        and wrong types yield `ERR_INVALID_REQUEST` (400)".

        Design: Corner/entities/customer_creation_missing_required_tax_id
        """
        rep = create_rep(full_name="Rep E2", crd_number="CRD-ENT2")
        resp = api_client.create_customer(
            {
                "customer_type": "INDIVIDUAL",
                "full_name": "No Tin",
                "country_risk_tier": "LOW",
            },
            make_rep_headers(rep["id"]),
        )
        error = validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert error["error_id"] == "ERR_INVALID_REQUEST"
        assert resp.status_code == 400


class TestCustomerInvalidEnumCustomerTypeRejected:
    def test_customer_type_outside_declared_set_rejected(self, api):
        """PRD §3.1: customer_type is "`INDIVIDUAL` or `LEGAL_ENTITY`".
        PRD §2.9: "15. Cross-reference validity — wrong-type customers, non-draft
        certifications, mismatched origin alerts, invalid prior filings, and
        out-of-set enum values yield the referential errors of §3
        (`ERR_CERTIFICATION_REQUIRES_LEGAL_ENTITY`, `ERR_CERTIFICATION_NOT_DRAFT`,
        `ERR_ALERT_ACCOUNT_MISMATCH`, `ERR_PRIOR_FILING_CASE_MISMATCH`,
        `ERR_INVALID_ENUM`, all 400)."
        `TRUST` is outside the declared set and is rejected ERR_INVALID_ENUM (400).

        Design: Corner/entities/customer_invalid_enum_customer_type_rejected
        """
        rep = create_rep(full_name="Rep E3", crd_number="CRD-ENT3")
        resp = api_client.create_customer(
            {
                "customer_type": "TRUST",
                "full_name": "Bad Enum",
                "tax_id": "TIN-ENT3",
                "country_risk_tier": "LOW",
            },
            make_rep_headers(rep["id"]),
        )
        error = validate_error(resp, ApiErrorId.ERR_INVALID_ENUM)
        assert error["error_id"] == "ERR_INVALID_ENUM"
        assert resp.status_code == 400


class TestSuspendedRepCannotCreateCustomer:
    def test_suspended_rep_refused_until_reinstated(self, api):
        """PRD §3.1: "a rep who is not `ACTIVE` cannot create customers, accounts,
        identification documents, or certifications — the attempt is refused with
        `ERR_REP_SUSPENDED` before any target-side validation runs."
        After reinstate (`SUSPENDED` back to `ACTIVE`, §3.1) the same create succeeds.

        Design: Corner/rbac/suspended_rep_cannot_create_customer
        """
        rep = create_rep(full_name="Rep B7", crd_number="CRD-B07")
        resp = api_client.suspend_rep(rep["id"], TEST_USERS["admin_headers"])
        validate_success(resp)

        resp = api_client.create_customer(
            {
                "customer_type": "INDIVIDUAL",
                "full_name": "B7",
                "tax_id": "TIN-B07",
                "country_risk_tier": "LOW",
            },
            make_rep_headers(rep["id"]),
        )
        error = validate_error(resp, ApiErrorId.ERR_REP_SUSPENDED)
        assert error["error_id"] == "ERR_REP_SUSPENDED"
        assert resp.status_code == 409

        resp = api_client.reinstate_rep(rep["id"], TEST_USERS["admin_headers"])
        validate_success(resp)
        customer = create_customer(
            rep, customer_type="INDIVIDUAL", full_name="B7", tax_id="TIN-B07",
            country_risk_tier="LOW",
        )
        assert is_valid_uuid(customer["id"])


class TestDocumentVerifySupersedesPriorSameType:
    def test_verifying_replacement_supersedes_prior_verified_document(self, api):
        """PRD §3.1: "Verification carries two cascades: every other document of the
        same customer and same `doc_type` currently `VERIFIED` or `EXPIRED` becomes
        `SUPERSEDED`, and the AML posture of every account belonging to that customer
        is recomputed".

        Design: Corner/state_machines/document_verify_supersedes_prior_same_type
        """
        set_clock("2026-05-01T00:00:00Z")
        rep = create_rep(full_name="Rep S4", crd_number="CRD-S04")
        customer = create_customer(
            rep, customer_type="INDIVIDUAL", full_name="S4", tax_id="TIN-S04",
            country_risk_tier="LOW",
        )
        doc1 = submit_and_verify_document(
            customer["id"], rep, document_number="P-S04a", expiry_date="2030-01-01"
        )
        doc2 = submit_document(
            customer["id"], rep, document_number="P-S04b", expiry_date="2031-01-01"
        )
        resp = api_client.verify_document(doc2["id"], TEST_USERS["analyst_headers"])
        verified2 = validate_success(resp)
        assert verified2["status"] == "VERIFIED"

        resp = api_client.get_document(doc1["id"], TEST_USERS["analyst_headers"])
        doc1_after = validate_success(resp)
        assert doc1_after["status"] == "SUPERSEDED", (
            f"prior VERIFIED same-type document must be SUPERSEDED, got {doc1_after['status']}"
        )


class TestDocumentExpirySweepAndRejectedTerminal:
    def test_sweep_expires_verified_doc_and_rejected_doc_not_verifiable(self, api):
        """PRD §2.5: "any identification document in `VERIFIED` whose `expiry_date` is
        earlier than the clock date becomes `EXPIRED`".
        PRD §3.1: "Verification moves `SUBMITTED` → `VERIFIED` and is only defined from
        `SUBMITTED` — anything else draws `ERR_DOCUMENT_NOT_VERIFIABLE`."
        `REJECTED` is terminal (PRD §3.1): the rejected W9 cannot later be verified.

        Design: Corner/state_machines/document_expiry_sweep_and_rejected_terminal
        """
        set_clock("2026-05-01T00:00:00Z")
        rep = create_rep(full_name="Rep S5", crd_number="CRD-S05")
        customer = create_customer(
            rep, customer_type="INDIVIDUAL", full_name="S5", tax_id="TIN-S05",
            country_risk_tier="LOW",
        )
        doc1 = submit_and_verify_document(
            customer["id"], rep, document_number="P-S05a", expiry_date="2026-05-03"
        )
        doc2 = submit_document(
            customer["id"], rep, doc_type="W9", document_number="W-S05",
            expiry_date="2030-01-01",
        )
        resp = api_client.reject_document(
            doc2["id"], {"reason": "illegible"}, TEST_USERS["analyst_headers"]
        )
        validate_success(resp)

        set_clock("2026-05-04T00:00:00Z")
        sweep = run_daily_sweep()
        assert sweep["documents_expired"] == 1, (
            f"exactly one VERIFIED document is past expiry, got {sweep['documents_expired']}"
        )
        resp = api_client.get_document(doc1["id"], TEST_USERS["analyst_headers"])
        assert validate_success(resp)["status"] == "EXPIRED"

        resp = api_client.verify_document(doc2["id"], TEST_USERS["analyst_headers"])
        error = validate_error(resp, ApiErrorId.ERR_DOCUMENT_NOT_VERIFIABLE)
        assert error["error_id"] == "ERR_DOCUMENT_NOT_VERIFIABLE"


class TestPostureReconcilesAfterDocumentReplacement:
    def test_posture_elevated_on_expiry_then_standard_on_replacement(self, api):
        """PRD §3.4: "Elevation from `STANDARD` to `ELEVATED` occurs when any of four
        triggers is present: a `VERIFIED` identification document on the customer has
        expired and not yet been superseded; ...".
        PRD §3.4: "An `ELEVATED` posture driven purely by an expired document relaxes
        to `STANDARD` once the expired document is `SUPERSEDED` by a newly `VERIFIED`
        replacement and no other elevation trigger exists."

        Design: Corner/cross_cutting_layers/posture_reconciles_after_document_replacement
        """
        ctx = setup_open_account(doc_expiry="2026-05-03")
        account_id = ctx["account"]["id"]
        rep = ctx["rep"]
        customer = ctx["customer"]
        old_doc = ctx["doc"]

        set_clock("2026-05-04T00:00:00Z")
        run_daily_sweep()
        elevated = get_account(account_id)
        assert elevated["aml_posture"] == "ELEVATED", (
            f"expired document must elevate posture, got {elevated['aml_posture']}"
        )

        submit_and_verify_document(
            customer["id"], rep, document_number="P-X05b", expiry_date="2030-01-01"
        )
        reconciled = get_account(account_id)
        assert reconciled["aml_posture"] == "STANDARD", (
            f"verified replacement removes the trigger, got {reconciled['aml_posture']}"
        )
        resp = api_client.get_document(old_doc["id"], TEST_USERS["officer_headers"])
        assert validate_success(resp)["status"] == "SUPERSEDED"


class TestExcessiveOwnershipTotalRejected:
    def test_owner_percentages_over_100_rejected_at_certify(self, api):
        """PRD §3.2: "The `total_ownership_pct` — the sum of `ownership_pct` across all
        owner rows — must not exceed 100.0, or the attempt is rejected with
        `ERR_EXCESSIVE_OWNERSHIP_TOTAL`."
        Owners 60.00 + 50.00 total 110.00: certification fails with 422.

        Design: Corner/validations/excessive_ownership_total_rejected
        """
        set_clock("2026-05-01T00:00:00Z")
        rep = create_rep(full_name="Rep V6", crd_number="CRD-V06")
        customer = create_customer(
            rep, customer_type="LEGAL_ENTITY", full_name="V6 Corp",
            tax_id="EIN-V06", country_risk_tier="LOW",
        )
        cert = create_certification(customer["id"], rep)
        add_owner(cert["id"], rep, full_name="O60", ownership_pct=60.00,
                  is_control_person=True, tax_id="TIN-O60",
                  date_of_birth="1960-01-01", address="60 St")
        add_owner(cert["id"], rep, full_name="O50", ownership_pct=50.00,
                  is_control_person=False, tax_id="TIN-O50",
                  date_of_birth="1961-01-01", address="50 St")
        resp = api_client.certify(cert["id"], TEST_USERS["officer_headers"])
        error = validate_error(resp, ApiErrorId.ERR_EXCESSIVE_OWNERSHIP_TOTAL)
        assert error["error_id"] == "ERR_EXCESSIVE_OWNERSHIP_TOTAL"
        assert resp.status_code == 422


class TestControlPersonRequiredAtCertify:
    def test_no_control_person_rejected_at_certify(self, api):
        """PRD §3.2: "At least one owner must have `is_control_person` set, else
        `ERR_CONTROL_PERSON_REQUIRED`."
        A fully-KYC 30.00 owner with is_control_person false fails certification (422).

        Design: Corner/validations/control_person_required_at_certify
        """
        set_clock("2026-05-01T00:00:00Z")
        rep = create_rep(full_name="Rep V7", crd_number="CRD-V07")
        customer = create_customer(
            rep, customer_type="LEGAL_ENTITY", full_name="V7 Corp",
            tax_id="EIN-V07", country_risk_tier="LOW",
        )
        cert = create_certification(customer["id"], rep)
        add_owner(cert["id"], rep, full_name="O30", ownership_pct=30.00,
                  is_control_person=False, tax_id="TIN-O30",
                  date_of_birth="1962-01-01", address="30 St")
        resp = api_client.certify(cert["id"], TEST_USERS["officer_headers"])
        error = validate_error(resp, ApiErrorId.ERR_CONTROL_PERSON_REQUIRED)
        assert error["error_id"] == "ERR_CONTROL_PERSON_REQUIRED"
        assert resp.status_code == 422
