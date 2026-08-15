"""Supplier/BU registration, auth header precedence, and role-based access."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_business_unit,
    assert_supplier,
    create_business_unit,
    create_business_unit_payload,
    create_draft_goal,
    create_supplier,
    create_supplier_payload,
    create_tier2_report,
    get_success_data,
    make_prime_contact_headers,
    replace_lines_payload,
    submit_certification,
    submit_tier2_report,
    tier2_line,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN1 = TEST_USERS["admin_1_headers"]
ANALYST1 = TEST_USERS["analyst_1_headers"]
LEAD1 = TEST_USERS["lead_1_headers"]
LEAD2 = TEST_USERS["lead_2_headers"]
AUDITOR9 = TEST_USERS["auditor_9_headers"]


class TestRegistrationDefaults:
    def test_business_unit_creation_defaults(self, api):
        """PRD §3.1: "The unit's `inclusion_min_diverse_bidders` — an integer
        between 0 and 10 inclusive, defaulting to 1 — supplies the default
        inclusion threshold for events that do not override it, and its two
        lifetime spend counters start at 0."
        PRD §2.4: "an integer `version` that starts at 1 on creation and
        increments by 1 on every mutation of that resource."

        Design: Corner/entities/business_unit_creation_defaults
        """
        resp = api.create_business_unit(
            create_business_unit_payload(name="Avionics", code="AVIO",
                                         lead_user_id="lead-7"),
            ADMIN1,
        )
        bu = validate_success(resp, 201)
        assert_business_unit(bu)
        assert bu["inclusion_min_diverse_bidders"] == 1, (
            "Omitted inclusion_min_diverse_bidders defaults to 1"
        )
        assert bu["lifetime_imported_spend_cents"] == 0
        assert bu["lifetime_voided_spend_cents"] == 0
        assert bu["version"] == 1

    def test_supplier_creation_initial_state(self, api):
        """PRD §3.1: "A newly registered supplier starts in `REGISTERED`
        status with `diverse_eligible` set to false and both
        `risk_score_standard` and `risk_score_conservative` at 0."

        Design: Corner/entities/supplier_creation_initial_state
        """
        resp = api.create_supplier(
            create_supplier_payload(legal_name="Fresh Co", tax_id="T-FRESH",
                                    kind="BOTH", contact_email="f@x.com"),
            ANALYST1,
        )
        supplier = validate_success(resp, 201)
        assert_supplier(supplier)
        assert supplier["status"] == "REGISTERED"
        assert supplier["diverse_eligible"] is False
        assert supplier["risk_score_standard"] == 0
        assert supplier["risk_score_conservative"] == 0

    def test_supplier_get_not_found_returns_404(self, api):
        """PRD §2.9: "A mismatch or missing resource at any step yields
        `ERR_NOT_FOUND`."

        Design: Corner/entities/supplier_get_not_found_returns_404
        """
        resp = api.get_supplier(NON_EXISTENT_UUID, ADMIN1)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_spend_record_create_missing_amount_returns_invalid_request(
            self, api):
        """PRD §3.3: "A `DiversityAnalyst` imports spend by supplying
        `supplier_id`, `business_unit_id`, `amount_cents`, `transaction_date`,
        `payment_date`, and optionally `po_number`."
        PRD §3.3: "The `amount_cents` must be greater than 0, otherwise
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/spend_record_create_missing_amount_returns_invalid_request
        """
        bu = create_business_unit()
        supplier = create_supplier(legal_name="Req Co", tax_id="T-REQ")
        payload = {
            "supplier_id": supplier["id"],
            "business_unit_id": bu["id"],
            "transaction_date": "2026-02-01",
            "payment_date": "2026-02-10",
        }
        resp = api.create_spend_record(payload, ANALYST1)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        _rows, meta = validate_paginated(api.list_spend_records(ANALYST1))
        assert meta["total_count"] == 0, (
            "No spend record may be persisted by the rejected import"
        )

    def test_supplier_create_invalid_enum_kind_rejected(self, api):
        """PRD §3.1: "The `kind` is one of `DIVERSE`, `PRIME`, or `BOTH`;
        only `PRIME` and `BOTH` suppliers may file tier-2 reports."

        Design: Corner/entities/supplier_create_invalid_enum_kind_rejected
        """
        resp = api.create_supplier(
            create_supplier_payload(legal_name="Alien Co", tax_id="T-ALIEN",
                                    kind="ALIEN", contact_email="a@x.com"),
            ANALYST1,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_certification_system_field_input_ignored(self, api):
        """PRD §3.2: "On submission the certification enters `SUBMITTED` and
        the server stamps `submitted_by_user_id` from the caller's
        `X-User-ID`."

        Design: Corner/entities/certification_system_field_input_ignored
        """
        supplier = create_supplier(legal_name="Spoof Co", tax_id="T-SPF")
        payload = {
            "cert_type": "MBE",
            "certifying_body": "NMSDC",
            "certificate_number": "M-SPF",
            "valid_from": "2026-01-01",
            "valid_to": "2026-12-31",
            "submitted_by_user_id": "spoofed-user",
            "verified_by_user_id": "spoofed-user",
        }
        resp = api.create_certification(supplier["id"], payload, ANALYST1)
        cert = validate_success(resp, 201)
        assert cert["submitted_by_user_id"] == "analyst-1", (
            "The server stamps the header identity; client-supplied "
            "submitted_by_user_id is ignored"
        )
        assert cert.get("verified_by_user_id") is None, (
            "verified_by_user_id is unset until verification"
        )
        assert cert["status"] == "SUBMITTED"


class TestAuthPrecedence:
    def test_request_missing_auth_header_returns_400(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role
        value not in the declared set, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400) before any
        other check runs."

        Design: Corner/validations/request_missing_auth_header_returns_400
        """
        resp = api.get_supplier(NON_EXISTENT_UUID, {})
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestRbacDenials:
    def test_rbac_analyst_cannot_publish_goal_forbidden(self, api):
        """PRD §2.1: "a caller whose role is not on the endpoint's permitted
        list, or who violates an ownership or scope clause attached to that
        endpoint, receives `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §4 permits only DiversityAdmin on POST /api/v1/goals/{id}/publish.

        Design: Corner/rbac/rbac_analyst_cannot_publish_goal_forbidden
        """
        bu = create_business_unit()
        goal = create_draft_goal(bu, headers=ADMIN1)
        resp = api.publish_goal(goal["id"], ANALYST1)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        goals, _meta = validate_paginated(api.list_goals(bu["id"], ADMIN1))
        assert goals[0]["status"] == "DRAFT", (
            "The rejected publish leaves the goal DRAFT"
        )

    def test_rbac_lead_cannot_verify_certification_forbidden(self, api):
        """PRD §2.1: "a caller whose role is not on the endpoint's permitted
        list, or who violates an ownership or scope clause attached to that
        endpoint, receives `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §4 permits only DiversityAdmin and DiversityAnalyst on
        POST /api/v1/certifications/{id}/verify.

        Design: Corner/rbac/rbac_lead_cannot_verify_certification_forbidden
        """
        supplier = create_supplier(legal_name="Gate Co", tax_id="T-GTE")
        cert = submit_certification(supplier["id"], certificate_number="M-G")
        get_success_data(
            api.begin_review_certification(cert["id"], ANALYST1))
        resp = api.verify_certification(cert["id"], LEAD1)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        certs, _meta = validate_paginated(
            api.list_certifications(supplier["id"], ADMIN1))
        assert certs[0]["status"] == "UNDER_REVIEW", (
            "The rejected verify leaves the certification UNDER_REVIEW"
        )

    def test_rbac_prime_cannot_approve_report_forbidden(self, api):
        """PRD §2.1: "a caller whose role is not on the endpoint's permitted
        list, or who violates an ownership or scope clause attached to that
        endpoint, receives `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §4 permits only DiversityAdmin on
        POST /api/v1/tier-2-reports/{id}/approve.

        Design: Corner/rbac/rbac_prime_cannot_approve_report_forbidden
        """
        bu = create_business_unit()
        prime = create_supplier(legal_name="Prime Build Inc", tax_id="T-PB",
                                kind="PRIME", contact_email="p@x.com")
        diverse = create_supplier(legal_name="Diverse Parts Co", tax_id="T-DP")
        report = create_tier2_report(
            prime["id"], bu["id"],
            lines=[tier2_line(diverse["id"], 10000, 100.00)])
        submit_tier2_report(report["id"], prime["id"])
        resp = api.approve_tier2_report(
            report["id"], make_prime_contact_headers(prime["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        stored = validate_success(api.get_tier2_report(report["id"], ADMIN1))
        assert stored["status"] == "SUBMITTED", (
            "The rejected approve leaves the report SUBMITTED"
        )

    def test_rbac_auditor_cannot_import_spend_forbidden(self, api):
        """PRD §2.1: "a caller whose role is not on the endpoint's permitted
        list, or who violates an ownership or scope clause attached to that
        endpoint, receives `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §4 permits only DiversityAnalyst on POST /api/v1/spend-records.

        Design: Corner/rbac/rbac_auditor_cannot_import_spend_forbidden
        """
        bu = create_business_unit()
        supplier = create_supplier(legal_name="Audit Target", tax_id="T-AT")
        payload = {
            "supplier_id": supplier["id"],
            "business_unit_id": bu["id"],
            "amount_cents": 5000,
            "transaction_date": "2026-02-01",
            "payment_date": "2026-02-01",
        }
        resp = api.create_spend_record(payload, AUDITOR9)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_rbac_lead_cannot_open_other_bus_event_forbidden(self, api):
        """PRD §2.1: "a `BusinessUnitLead` caller opening, awarding,
        cancelling, or inviting on a sourcing event must present an
        `X-User-ID` equal to the `lead_user_id` recorded on the event's
        `BusinessUnit`"

        Design: Corner/rbac/rbac_lead_cannot_open_other_bus_event_forbidden
        """
        bu1 = create_business_unit(lead_user_id="lead-1")
        create_business_unit(name="Marine", code="MAR", lead_user_id="lead-2")
        event = get_success_data(api.create_sourcing_event(
            {"business_unit_id": bu1["id"], "title": "Avionics cables",
             "estimated_value_cents": 100000, "required_diverse_bidders": 0},
            LEAD1))
        resp = api.open_sourcing_event(event["id"], LEAD2)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        stored = validate_success(api.get_sourcing_event(event["id"], LEAD1))
        assert stored["status"] == "DRAFT", (
            "The scope-rejected open leaves the event DRAFT"
        )


class TestOwnershipAndUniqueness:
    def test_tier2_edit_by_other_prime_forbidden(self, api):
        """PRD §2.1: "a `PrimeContact` may only create a tier-2 report whose
        `prime_supplier_id` equals their `X-User-ID`, and may only edit or
        submit a report whose `prime_supplier_id` equals their `X-User-ID`."
        PRD §3.4: "The `prime_supplier_id` must equal the caller's `X-User-ID`
        — a `PrimeContact` filing for any other prime receives
        `ERR_FORBIDDEN_FOR_ROLE`"

        Design: Corner/validations/tier2_edit_by_other_prime_forbidden
        """
        bu = create_business_unit()
        prime_a = create_supplier(legal_name="Prime A", tax_id="T-PA",
                                  kind="PRIME", contact_email="a@x.com")
        prime_b = create_supplier(legal_name="Prime B", tax_id="T-PB",
                                  kind="PRIME", contact_email="b@x.com")
        diverse = create_supplier(legal_name="Diverse Parts Co", tax_id="T-DP")
        report = create_tier2_report(
            prime_a["id"], bu["id"],
            lines=[tier2_line(diverse["id"], 10000, 100.00)])
        resp = api.replace_tier2_lines(
            report["id"],
            replace_lines_payload(
                [tier2_line(diverse["id"], 20000, 100.00)]),
            make_prime_contact_headers(prime_b["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_duplicate_tax_id_rejected(self, api):
        """PRD §3.1: "The `tax_id` must be unique across all suppliers; a
        duplicate is rejected with `ERR_DUPLICATE_TAX_ID`."

        Design: Corner/validations/duplicate_tax_id_rejected
        """
        create_supplier(legal_name="First Co", tax_id="T-DUP")
        resp = api.create_supplier(
            create_supplier_payload(legal_name="Second Co", tax_id="T-DUP",
                                    kind="PRIME", contact_email="s@x.com"),
            ANALYST1,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_TAX_ID)
