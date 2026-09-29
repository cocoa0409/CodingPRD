"""Every role drives its own exclusive endpoints once, in the order the domain requires."""
from test_helpers import (
    api_client, validate_success, factories, read_facility, set_clock,
    make_manager_headers, ADMIN, ANALYST, ANALYST2, APPROVER, COMPLIANCE, CONTRACT,
    MANAGER_USER_ID, ANALYST2_USER_ID, APPROVER_USER_ID,
)


def test_admin_configures_analyst_prices_manager_requests_approver_decides_and_compliance_builds():
    """PRD §2.1: "A `SystemAdmin` configures the environment — facilities, the national revenue-code
    reference table, departments, and the logical clock — and never touches item pricing or approvals."
    PRD §2.1: "A `RevenueIntegrityAnalyst` owns day-to-day chargemaster maintenance: drafting items,
    repricing them, authoring price rules, retiring duplicates and inactive items, reviewing department
    requests, mapping annual code-update entries, and reconciling charge capture batches."
    PRD §2.1: "A `PricingCommitteeApprover` holds the approval authority: item approval, item activation
    and reactivation, change-request approval, and annual crosswalk approval."
    PRD §2.1: "A `ComplianceOfficer` owns price-transparency publication, impact-analysis sign-off, and
    the activation, rollback and cancellation of annual code update cycles."
    PRD §2.1: "A `ContractManager` owns payer contract terms and may run payer impact analyses of
    proposed price changes."
    PRD §2.1: "A `DepartmentManager` speaks for exactly one department: requesting chargemaster changes
    for it and submitting its charge capture batches."
    PRD §4: "Endpoints that bring a new resource into existence answer 201 Created; every other
    successful call answers 200 OK."

    Design: Corner/rbac/each_role_exercises_its_own_exclusive_operations_end_to_end
    """
    set_clock("2026-09-01T00:00:00Z")
    facility = validate_success(api_client.create_facility(
        factories.create_facility_payload(name="Mercy General",
                                          cms_certification_number="CCN-2193-RBACPOS",
                                          rounding_mode="NEAREST_CENT"), ADMIN), 201)
    revenue_code = validate_success(api_client.create_revenue_code(
        factories.create_revenue_code_payload(code="0300", description="Laboratory",
                                              requires_hcpcs=False,
                                              allowed_code_types=["CPT"],
                                              pricing_class="PROCEDURE"), ADMIN), 201)
    department = validate_success(api_client.create_department(
        factories.create_department_payload(facility["id"], MANAGER_USER_ID,
                                            name="Cardiac Cath Lab",
                                            cost_center_code="CC-100"), ADMIN), 201)

    rule = validate_success(api_client.create_price_rule(
        factories.create_price_rule_payload(
            facility["id"], revenue_code["id"], pricing_method="COST_PLUS_MARKUP",
            effective_from="2026-01-01T00:00:00Z",
            markup_tiers=[{"min_cost_basis_cents": 0, "markup_bp": 32000},
                          {"min_cost_basis_cents": 50000, "markup_bp": 24000}]), ANALYST), 201)
    assert rule["status"] == "ACTIVE"

    item = validate_success(api_client.create_charge_item(
        factories.create_charge_item_payload(
            facility["id"], department["id"], revenue_code["id"], cdm_number="CDM-1001",
            description="CARDIAC CATH BASIC", code_type="CPT", code_value="93458",
            cost_basis_cents=100000, medicare_rate_cents=50000, market_p75_cents=900000,
            effective_from="2026-09-01T00:00:00Z"), ANALYST), 201)
    priced = validate_success(api_client.reprice_charge_item(item["id"], ANALYST), 200)
    assert priced["gross_charge_cents"] == 240000
    assert priced["price_status"] == "PRICED_CURRENT"

    pending = validate_success(api_client.charge_item_lifecycle(
        item["id"], {"action": "SUBMIT_FOR_REVIEW"}, ANALYST), 200)
    assert pending["lifecycle_status"] == "PENDING_REVIEW"
    approved_item = validate_success(api_client.charge_item_lifecycle(
        item["id"], {"action": "APPROVE"}, APPROVER), 200)
    assert approved_item["lifecycle_status"] == "APPROVED"
    assert approved_item["approved_by_user_id"] == APPROVER_USER_ID
    active = validate_success(api_client.charge_item_lifecycle(
        item["id"], {"action": "ACTIVATE"}, APPROVER), 200)
    assert active["lifecycle_status"] == "ACTIVE"
    assert active["version"] == 5

    manager = make_manager_headers(MANAGER_USER_ID)
    request = validate_success(api_client.create_change_request(
        factories.create_change_request_payload(
            department["id"], item["id"], "PRICE_CHANGE",
            justification="Cost basis rose after the vendor contract renewal",
            proposed_cost_basis_cents=150000), manager), 201)
    assert request["status"] == "SUBMITTED"
    assert request["submitted_by_user_id"] == MANAGER_USER_ID

    reviewed = validate_success(api_client.change_request_decision(
        request["id"], {"decision": "REVIEW",
                        "decision_note": "Cost documentation attached and verified"},
        ANALYST2), 200)
    assert reviewed["status"] == "UNDER_REVIEW"
    assert reviewed["reviewed_by_user_id"] == ANALYST2_USER_ID
    request_approved = validate_success(api_client.approve_change_request(
        request["id"], {"expected_charge_item_version": 5,
                        "decision_note": "Committee approved the new cost basis"},
        APPROVER), 200)
    assert request_approved["status"] == "APPROVED"
    assert request_approved["approved_by_user_id"] == APPROVER_USER_ID

    contract = validate_success(api_client.create_payer_contract(
        factories.create_payer_contract_payload(
            facility["id"], payer_code="BCBS", product_line="COMMERCIAL",
            reimbursement_method="PERCENT_OF_CHARGE", percent_of_charge_bp=6000,
            term_start_date="2026-09-01T00:00:00Z", term_end_date="2027-08-31T23:59:59Z",
            renegotiation_notice_days=30, trailing_units=100), CONTRACT), 201)
    assert contract["status"] == "ACTIVE"

    live_version = read_facility(facility["id"])["version"]
    transparency_file = validate_success(api_client.create_transparency_file(
        factories.create_transparency_file_payload(facility["id"], live_version,
                                                   file_format="CSV"), COMPLIANCE), 201)
    assert transparency_file["status"] == "BUILDING"
    assert transparency_file["facility_id"] == facility["id"]
    assert read_facility(facility["id"])["chargemaster_posture"] == "FROZEN"
