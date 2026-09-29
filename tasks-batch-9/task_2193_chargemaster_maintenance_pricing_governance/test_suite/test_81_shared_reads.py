"""The control group for every denial: shared reads succeed for each declared role, identically."""
from test_helpers import (
    api_client, validate_success, validate_paginated,
    setup_base, create_active_item, create_change_request, create_payer_contract, set_clock,
    make_manager_headers, ADMIN, ANALYST, APPROVER, COMPLIANCE, CONTRACT, MANAGER_USER_ID,
)

MERCY = dict(
    facility_overrides={
        "name": "Mercy General", "cms_certification_number": "CCN-2193-SHAREDREAD",
        "rounding_mode": "NEAREST_CENT", "aggregate_markup_limit_bp": 40000,
    },
    revenue_code_overrides={
        "code": "0300", "description": "Laboratory - general", "requires_hcpcs": False,
        "allowed_code_types": ["CPT", "HCPCS", "REV_ONLY", "CDM_INTERNAL"],
        "pricing_class": "PROCEDURE", "status": "ACTIVE",
    },
    department_overrides={"name": "Cardiac Cath Lab", "cost_center_code": "CC-100",
                         "allowed_revenue_code_values": []},
    price_rule_overrides={"effective_from": "2026-01-01T00:00:00Z"},
)


def test_every_role_that_declares_a_read_gets_the_same_computed_snapshot():
    """PRD §4: "| GET | `/chargemaster/facilities/{facility_id}` | Read a facility including derived
    posture, aggregates and `version`. | SystemAdmin, RevenueIntegrityAnalyst, PricingCommitteeApprover,
    ComplianceOfficer, ContractManager, DepartmentManager |"
    PRD §4: "| GET | `/chargemaster/charge-items/{charge_item_id}` | Read one item including both state
    dimensions, pricing outputs and `version`. | SystemAdmin, RevenueIntegrityAnalyst,
    PricingCommitteeApprover, ComplianceOfficer, ContractManager, DepartmentManager |"
    PRD §4: "| GET | `/chargemaster/price-rules/{price_rule_id}` | Read one price rule including its
    applied item count. | SystemAdmin, RevenueIntegrityAnalyst, PricingCommitteeApprover,
    ComplianceOfficer |"
    PRD §4: "| GET | `/chargemaster/payer-contracts/{payer_contract_id}` | Read one payer contract. |
    SystemAdmin, ContractManager, ComplianceOfficer, RevenueIntegrityAnalyst, PricingCommitteeApprover |"
    PRD §4: "| GET | `/chargemaster/change-requests/{change_request_id}` | Read one change request
    including its pin and actor fields. | SystemAdmin, RevenueIntegrityAnalyst, PricingCommitteeApprover,
    ComplianceOfficer, DepartmentManager |"
    PRD §4: "| GET | `/chargemaster/departments/{department_id}` | Read one department including its
    leakage counters and capture hold. | SystemAdmin, RevenueIntegrityAnalyst, PricingCommitteeApprover,
    ComplianceOfficer, ContractManager, DepartmentManager |"
    PRD §4: "| GET | `/chargemaster/revenue-codes/{revenue_code_id}` | Read one revenue code. |
    SystemAdmin, RevenueIntegrityAnalyst, PricingCommitteeApprover, ComplianceOfficer, ContractManager,
    DepartmentManager |"
    PRD §2.1: "A mismatch is `ERR_DEPARTMENT_SCOPE_VIOLATION` (HTTP 403), evaluated third — after
    authentication and role admission, and before any resource is looked up."

    Design: Corner/rbac/shared_read_operations_succeed_for_every_role_that_declares_them
    """
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(**MERCY)
    facility_id = base["facility"]["id"]
    manager = make_manager_headers(MANAGER_USER_ID)
    item = create_active_item(base, cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
                              code_type="CPT", code_value="93458", cost_basis_cents=100000,
                              medicare_rate_cents=50000, market_p75_cents=900000,
                              effective_from="2026-09-01T00:00:00Z")
    assert item["gross_charge_cents"] == 240000
    contract = create_payer_contract(
        facility_id, payer_code="BCBS", product_line="COMMERCIAL",
        reimbursement_method="PERCENT_OF_CHARGE", percent_of_charge_bp=6000,
        term_start_date="2026-09-01T00:00:00Z", term_end_date="2027-08-31T23:59:59Z",
        renegotiation_notice_days=30, trailing_units=100)
    request = create_change_request(base, item["id"], "PRICE_CHANGE",
                                   justification="Vendor cost increase in the renewal packet",
                                   proposed_cost_basis_cents=150000)

    facility_reads = [
        validate_success(api_client.get_facility(facility_id, headers), 200)
        for headers in (ADMIN, ANALYST, APPROVER, COMPLIANCE, CONTRACT, manager)
    ]
    for snapshot in facility_reads:
        assert snapshot["chargemaster_posture"] == "OPEN"
        assert snapshot["aggregate_gross_charge_cents"] == 240000
        assert snapshot["active_item_count"] == 1
    assert all(snapshot == facility_reads[0] for snapshot in facility_reads), (
        "the derived snapshot does not depend on which role asked for it"
    )

    item_reads = [
        validate_success(api_client.get_charge_item(item["id"], headers), 200)
        for headers in (ADMIN, ANALYST, APPROVER, COMPLIANCE, CONTRACT, manager)
    ]
    for snapshot in item_reads:
        assert snapshot["gross_charge_cents"] == 240000
        assert snapshot["lifecycle_status"] == "ACTIVE"
        assert snapshot["price_status"] == "PRICED_CURRENT"
    assert all(snapshot == item_reads[0] for snapshot in item_reads)

    for headers in (ADMIN, ANALYST, APPROVER, COMPLIANCE):
        rule = validate_success(api_client.get_price_rule(base["price_rule"]["id"], headers), 200)
        assert rule["status"] == "ACTIVE"
    for headers in (ADMIN, CONTRACT, COMPLIANCE, ANALYST, APPROVER):
        seen = validate_success(api_client.get_payer_contract(contract["id"], headers), 200)
        assert seen["status"] == "ACTIVE"
        assert seen["payer_code"] == "BCBS"
    for headers in (ADMIN, ANALYST, APPROVER, COMPLIANCE, manager):
        seen = validate_success(api_client.get_change_request(request["id"], headers), 200)
        assert seen["status"] == "SUBMITTED", (
            "the owning DepartmentManager may read its own department's request"
        )
    for headers in (ADMIN, ANALYST, APPROVER, COMPLIANCE, CONTRACT, manager):
        department = validate_success(
            api_client.get_department(base["department"]["id"], headers), 200)
        assert department["capture_hold"] is False
        assert department["open_request_count"] == 1
        revenue_code = validate_success(
            api_client.get_revenue_code(base["revenue_code"]["id"], headers), 200)
        assert revenue_code["status"] == "ACTIVE"
        assert revenue_code["code"] == "0300"

    for headers in (ADMIN, ANALYST, APPROVER, COMPLIANCE, CONTRACT, manager):
        rows, meta = validate_paginated(api_client.list_charge_items(
            headers, {"facility_id": facility_id, "lifecycle_status": "ACTIVE"}))
        assert meta["total_count"] == 1
        assert rows[0]["id"] == item["id"]
        assert rows[0]["gross_charge_cents"] == 240000
