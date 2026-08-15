"""Authentication, role authorization, entity-backed ownership, and the
retirement segregation of duties."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    approve_retirement,
    create_directive,
    create_lessee,
    create_lessee_payload,
    create_railcar,
    create_railcar_payload,
    create_retrofit,
    generate_statements,
    get_statement,
    get_success_data,
    make_compliance_officer_headers,
    make_fleet_planner_headers,
    make_lessee_rep_headers,
    propose_retirement,
    appraise_retirement,
    setup_provisional_statement,
    submit_mileage_report,
    validate_error,
    validate_success,
    setup_active_lease_scenario,
    create_lease,
)

ADMIN = TEST_USERS["system_admin_headers"]
LEASE_ADMIN = TEST_USERS["lease_admin_headers"]
PLANNER = TEST_USERS["fleet_planner_headers"]
MAINT = TEST_USERS["maintenance_controller_headers"]
BILLING = TEST_USERS["billing_analyst_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


class TestAuthentication:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role
        string the system does not recognize, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.6: "1. **Authentication** — `X-User-Role` and `X-User-ID`
        present, and the role is one of the seven declared roles; failure
        yields `ERR_UNAUTHENTICATED` (401)."

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        resp = api.list_railcars(headers=None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


class TestRoleAuthorization:
    def test_lesseerep_cannot_register_railcar(self, api):
        """PRD §2.1: "A request whose role is recognized but not listed among
        the roles authorized for the target endpoint is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4 lists POST /railcars as authorized for FleetPlanner only.

        Design: Corner/rbac/lesseerep_cannot_register_railcar
        """
        lessee = create_lessee(company_name="L", credit_limit_cents=1000000)
        resp = api.create_railcar(
            create_railcar_payload(car_mark="GATX1701", car_type="BOX",
                                   built_year=2020),
            make_lessee_rep_headers(lessee["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    def test_maintenance_cannot_certify_retrofit(self, api):
        """PRD §2.1: "A request whose role is recognized but not listed among
        the roles authorized for the target endpoint is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §3.11: "certification (`COMPLETED → CERTIFIED`) is a
        `ComplianceOfficer` action supplying `certification_ref`."

        Design: Corner/rbac/maintenance_cannot_certify_retrofit
        """
        car = create_railcar(car_mark="GATX1702", car_type="TANK_GENERAL",
                             built_year=2014)
        directive = create_directive(
            directive_code="DOT-117Q", description="d",
            applies_to_car_types=["TANK_GENERAL"],
            retrofit_deadline="2026-12-31", grace_days=30,
            daily_penalty_cents=10000, penalty_cap_cents=300000,
        )
        order = create_retrofit(car["id"], directive["id"], "2026-08-10")
        get_success_data(api.start_retrofit(order["id"], MAINT))
        completed = get_success_data(api.complete_retrofit(order["id"], MAINT))
        assert completed["status"] == "COMPLETED"

        resp = api.certify_retrofit(order["id"], "CERT-X", MAINT)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
        after = get_success_data(api.get_retrofit_order(order["id"], MAINT))
        assert after["status"] == "COMPLETED", (
            "A rejected certification leaves the order COMPLETED"
        )

    def test_billing_analyst_cannot_approve_lease(self, api):
        """PRD §2.1: "A request whose role is recognized but not listed among
        the roles authorized for the target endpoint is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §3.3: "A `ComplianceOfficer` then approves or rejects. Approval
        moves the lease to `ACTIVE` and is guarded by two checks: the lease's
        `end_date` must be strictly after its `start_date`
        (`ERR_INVALID_DATE_RANGE`, 422), and the lessee must still be
        `ACTIVE` (`ERR_LESSEE_NOT_ACTIVE`, 409)."

        Design: Corner/rbac/billing_analyst_cannot_approve_lease
        """
        lessee = create_lessee(company_name="L", credit_limit_cents=1000000)
        lease = create_lease(lessee["id"], lease_type="NET",
                             authorized_repair_cap_cents=1000)
        get_success_data(api.submit_lease_agreement(lease["id"], LEASE_ADMIN))
        resp = api.approve_lease_agreement(lease["id"], BILLING)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
        after = get_success_data(api.get_lease_agreement(lease["id"], LEASE_ADMIN))
        assert after["status"] == "PENDING_APPROVAL"


class TestOwnership:
    def test_lessee_cannot_dispute_other_lessees_statement(self, api):
        """PRD §2.1: "A `LesseeRep` attempting to dispute a statement whose
        `lessee_id` names a different lessee, to resubmit a mileage report
        whose assignment's lease belongs to a different lessee, to dispute a
        damage assessment under another lessee's lease, or to pre-authorize a
        repair tied to another lessee's assignment is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/lessee_cannot_dispute_other_lessees_statement
        """
        scenario = setup_active_lease_scenario(
            car_mark="GATX1703", company_name="A", credit_limit_cents=10000000,
            deliver=True,
        )
        lessee_a = scenario["lessee"]
        lessee_b = create_lessee(company_name="B", credit_limit_cents=10000000)
        submit_mileage_report(
            scenario["railcar"]["id"], scenario["assignment"]["id"],
            lessee_a["id"], "2026-08", 100, 0,
        )
        stmt = generate_statements("2026-08")[0]

        resp = api.dispute_statement(
            stmt["id"], "not mine", make_lessee_rep_headers(lessee_b["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
        after = get_statement(stmt["id"])
        assert after["status"] == "PROVISIONAL", (
            "Ownership mismatch must not move the statement"
        )


class TestRetirementSegregationOfDuties:
    def test_retirement_approve_by_proposer_rejected_sod(self, api):
        """PRD §2.8: "Approval of that case must come from a
        `ComplianceOfficer` whose `X-User-ID` is different from the recorded
        `proposer_user_id`; an approval attempt by the same identifier is
        rejected with `ERR_SOD_VIOLATION` (HTTP 403)."

        Design: Corner/state_machines/retirement_approve_by_proposer_rejected_sod
        """
        car = create_railcar(car_mark="GATX1206", car_type="GONDOLA",
                             built_year=1972)
        case = propose_retirement(car["id"], reason="DAMAGE_BEYOND_REPAIR",
                                  proposer_id="fp-9")
        appraise_retirement(case["id"], salvage_value_cents=100000,
                            book_value_cents=400000)
        # Approver carries the SAME operator id as the proposer.
        resp = api.approve_retirement(
            case["id"], make_compliance_officer_headers("fp-9")
        )
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION, 403)
        after = get_success_data(
            api.get_retirement_case(case["id"], make_fleet_planner_headers("fp-9"))
        )
        assert after["status"] == "APPRAISED"
