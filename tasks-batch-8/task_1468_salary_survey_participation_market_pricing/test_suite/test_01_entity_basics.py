"""Entity basics: creation defaults, required fields, enum constraints, audit shape."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_audit_event,
    create_active_vendor,
    create_job_payload,
    create_org,
    bootstrap_org,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

VENDOR_ADMIN = TEST_USERS["vendor_admin_headers"]
BOOTSTRAP_MGR = {"X-User-ID": "emp_mgr_bootstrap", "X-User-Role": "CompManager"}


class TestEntityBasics:
    def test_organization_creation_applies_defaults(self, api):
        """PRD §3.1: "an optional `fiscal_year_start_month` (an integer from 1
        to 12, defaulting to 1 when omitted)".

        Design: Corner/entities/organization_creation_applies_defaults
        """
        org = get_success_data(api.create_org(
            {"name": "Acme", "base_currency": "USD",
             "market_as_of_date": "2026-08-01"}, VENDOR_ADMIN), )
        fetched = validate_success(api.get_org(org["id"], VENDOR_ADMIN))
        assert fetched["fiscal_year_start_month"] == 1, (
            f"fiscal_year_start_month must default to 1 when omitted, "
            f"got {fetched['fiscal_year_start_month']}")

    def test_employee_creation_missing_email_returns_invalid_request(self, api):
        """PRD §2.6: "request well-formedness — the body parses, required input
        fields are present, enum fields carry declared values, and date fields
        are valid ISO dates — failing as `ERR_INVALID_REQUEST`".

        Design: Corner/entities/employee_creation_missing_email_returns_invalid_request
        """
        bundle = bootstrap_org()
        payload = {
            "full_name": "NoEmail",
            "job_id": bundle["job"]["id"],
            "geo_code": "US-SF",
            "base_salary_annual_cents": 100000,
            "hire_date": "2024-01-01",
        }
        resp = api.create_employee(bundle["org"]["id"], payload, BOOTSTRAP_MGR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_job_current_market_composite_id_initially_null(self, api):
        """PRD §3.2: "A job's `current_market_composite_id` is system-maintained:
        it starts null and is repointed to the job's latest `PUBLISHED` composite
        each time one is published (§3.6)."

        Design: Corner/entities/job_current_market_composite_id_initially_null
        """
        bundle = bootstrap_org()
        job = validate_success(api.get_job(bundle["job"]["id"], BOOTSTRAP_MGR))
        assert job["current_market_composite_id"] is None, (
            "Newly created Job must carry current_market_composite_id null")

    def test_employee_status_defaults_to_active(self, api):
        """PRD §3.2: "Each employee carries a system-managed `status` of
        `ACTIVE`, `LEAVE`, or `TERMINATED`; several downstream rules admit only
        `ACTIVE` employees."

        Design: Corner/entities/employee_status_defaults_to_active
        """
        bundle = bootstrap_org()
        emp = validate_success(api.get_employee(bundle["subject"]["id"],
                                                BOOTSTRAP_MGR))
        assert emp["status"] == "ACTIVE", (
            f"Newly created Employee must be ACTIVE, got {emp['status']}")

    def test_enum_field_rejects_undeclared_value(self, api):
        """PRD §3.2: "a `career_level` drawn from `IC1`, `IC2`, `IC3`, `IC4`,
        `IC5`, `M1`, `M2`, or `M3`".
        PRD §2.6: "request well-formedness — the body parses, required input
        fields are present, enum fields carry declared values, and date fields
        are valid ISO dates — failing as `ERR_INVALID_REQUEST`".

        Design: Corner/entities/enum_field_rejects_undeclared_value
        """
        org = create_org()
        resp = api.create_job(org["id"], create_job_payload(career_level="IC9"),
                              BOOTSTRAP_MGR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_audit_event_immutable_no_update_endpoint(self, api):
        """PRD §3.3: "A successful activation emits a `VENDOR_ACTIVATE` audit
        event."
        PRD §2.5: "AuditEvent resources are the deliberate exception: because
        they are immutable once written, they carry only `id` and `created_at`
        — both `updated_at` and `version` are absent from an AuditEvent."

        Design: Corner/entities/audit_event_immutable_no_update_endpoint
        """
        bundle = bootstrap_org()
        create_active_vendor(bundle)
        events, meta = validate_paginated(api.list_org_audit_events(
            bundle["org"]["id"], VENDOR_ADMIN))
        activate_events = [e for e in events if e["action"] == "VENDOR_ACTIVATE"]
        assert len(activate_events) >= 1, (
            "Vendor activation must emit a VENDOR_ACTIVATE audit event")
        assert_audit_event(activate_events[0])
