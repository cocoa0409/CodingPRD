"""Leads: creation FK guard, status filtering, selector eligibility
boundaries, and the certification/approval dependency of distribution."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_active_program,
    create_contractor_with_cert,
    create_customer,
    create_lead,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = TEST_USERS["program_manager_headers"]


class TestLeadCreationFkGuard:
    def test_referenced_customer_not_found(self, api, pm_headers):
        """PRD 2.6: "every foreign key referenced in a request body —
        `customer_id`, `contractor_id`, `program_id`, `lead_id`, `project_id`,
        `work_order_id`, `inspector_id`, or `payee_id` — must resolve to an
        existing resource, or the request is rejected with
        `ERR_REFERENCED_NOT_FOUND` (HTTP 404)."

        Design: Corner/validations/referenced_customer_not_found
        """
        program = create_active_program(budget_cents=1000)
        resp = api.create_lead(
            {
                "customer_id": NON_EXISTENT_UUID,
                "program_id": program["id"],
                "measure_type": "HVAC",
                "estimated_annual_kwh_savings": 100,
                "source_channel": "WEB",
            },
            pm_headers,
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCED_NOT_FOUND)


class TestLeadListFiltering:
    def test_leads_list_filter_by_status(self, api, pm_headers):
        """PRD 3.3: "Lead lists may be filtered by `status`, `program_id`,
        `contractor_id`, `customer_id`, and `assigned_contractor_id`."

        Design: Corner/endpoints/leads_list_filter_by_status
        """
        program = create_active_program(budget_cents=100000)
        customer = create_customer()
        lead1 = create_lead(customer["id"], program["id"], estimated_annual_kwh_savings=100)
        lead2 = create_lead(customer["id"], program["id"], estimated_annual_kwh_savings=200)
        validate_success(api.withdraw_lead(lead2["id"], pm_headers), 200)

        resp = api.list_leads(pm_headers, params={"status": "NEW"})
        data, meta = validate_paginated(resp)
        ids = [lead["id"] for lead in data]
        assert lead1["id"] in ids
        assert lead2["id"] not in ids
        assert all(lead["status"] == "NEW" for lead in data)


class TestEmptyEligibleContractorSet:
    def test_distribute_rejected_when_no_contractor_covers_zip(self, api, pm_headers):
        """PRD 3.3: "when the full eligibility filter — contractor in
        `APPROVED` standing, contractor `sector` matching the program's sector,
        the customer's `service_zip` contained in the contractor's
        `service_zip_codes`, and an `ACTIVE` certification for the lead's
        `measure_type` — yields no candidate at all, the rejection is
        `ERR_NO_ELIGIBLE_CONTRACTOR`."
        Here the only contractor holds the right certification and sector but
        does not serve the customer's ZIP.

        Design: Difficulty/boundary_precision_check/empty_eligible_contractor_set
        """
        set_clock()
        program = create_active_program(budget_cents=100000)
        create_contractor_with_cert(contractor_overrides={"service_zip_codes": ["94110"]})
        customer = create_customer(service_zip="10001")
        lead = create_lead(customer["id"], program["id"], estimated_annual_kwh_savings=100)
        resp = api.distribute_lead(lead["id"], lead["version"], pm_headers)
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_CONTRACTOR)
        after = validate_success(api.get_lead(lead["id"], pm_headers))
        assert after["status"] == "NEW"

    def test_distribute_rejected_when_no_contractor_matches_sector(self, api, pm_headers):
        """PRD 3.3: "when the full eligibility filter — contractor in
        `APPROVED` standing, contractor `sector` matching the program's sector,
        the customer's `service_zip` contained in the contractor's
        `service_zip_codes`, and an `ACTIVE` certification for the lead's
        `measure_type` — yields no candidate at all, the rejection is
        `ERR_NO_ELIGIBLE_CONTRACTOR`."
        Here the only approved contractor holds an ACTIVE HVAC certification
        and covers the ZIP, but serves the COMMERCIAL sector while the program
        is RESIDENTIAL.

        Design: Difficulty/boundary_precision_check/empty_eligible_contractor_set
        """
        set_clock()
        program = create_active_program(budget_cents=100000, sector="RESIDENTIAL")
        create_contractor_with_cert(contractor_overrides={"sector": "COMMERCIAL"})
        customer = create_customer(sector="RESIDENTIAL")
        lead = create_lead(customer["id"], program["id"], estimated_annual_kwh_savings=100)
        resp = api.distribute_lead(lead["id"], lead["version"], pm_headers)
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_CONTRACTOR)


class TestLeadDistributeRequiresApprovedContractorWithCert:
    def test_distribute_rejected_when_certification_measure_mismatch(self, api, pm_headers):
        """PRD 3.3: "The certification dimension is then screened: when the
        candidate pool fails specifically because no approved contractor
        carries an `ACTIVE` certification for the lead's `measure_type`, the
        rejection is `ERR_CERTIFICATION_MISSING`."
        The sole approved contractor holds an ACTIVE HVAC certification; the
        lead proposes SOLAR.

        Design: Difficulty/cross_entity_state_dependency/lead_distribute_requires_contractor_approved_with_cert
        """
        set_clock()
        program = create_active_program(budget_cents=100000)
        create_contractor_with_cert(measure_type="HVAC")
        customer = create_customer()
        lead = create_lead(customer["id"], program["id"], measure_type="SOLAR",
                           estimated_annual_kwh_savings=100)
        resp = api.distribute_lead(lead["id"], lead["version"], pm_headers)
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_MISSING)

    def test_distribute_assigns_eligible_contractor_and_bumps_version(self, api, pm_headers):
        """PRD 3.3: "The winner is written into the lead's
        `assigned_contractor_id`, the decision is journaled into the lead's
        `distribution_decision` object — recording `candidate_count`, the
        `ranking_key` that decided the outcome, and the `tie_break_used` — and
        the lead's `version` increments."
        With exactly one eligible contractor (APPROVED, sector match, ZIP
        covered, ACTIVE certification for the measure type), distribution moves
        the lead NEW -> OFFERED and assigns that contractor.

        Design: Difficulty/cross_entity_state_dependency/lead_distribute_requires_contractor_approved_with_cert
        """
        set_clock()
        program = create_active_program(budget_cents=100000)
        bundle = create_contractor_with_cert()
        contractor = bundle["contractor"]
        customer = create_customer()
        lead = create_lead(customer["id"], program["id"], estimated_annual_kwh_savings=100)
        resp = api.distribute_lead(lead["id"], lead["version"], pm_headers)
        offered = validate_success(resp, expected_status=200)
        assert offered["status"] == "OFFERED"
        assert offered["assigned_contractor_id"] == contractor["id"]
        assert offered["version"] == lead["version"] + 1
