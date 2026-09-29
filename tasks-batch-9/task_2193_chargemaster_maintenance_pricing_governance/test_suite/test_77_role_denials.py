"""The same payloads the owning roles used, replayed by the wrong role and refused before anything else."""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId, factories,
    setup_base, create_priced_item, item_lifecycle, create_change_request,
    read_facility, set_clock,
    ADMIN, ANALYST, APPROVER, COMPLIANCE,
)

MERCY = dict(
    facility_overrides={
        "name": "Mercy General", "cms_certification_number": "CCN-2193-RBACNEG",
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

DENIED = ApiErrorId.ERR_ROLE_NOT_PERMITTED.value


def test_the_wrong_role_is_refused_on_every_exclusive_operation_before_any_other_check():
    """PRD §2.1: "The six roles are `SystemAdmin`, `RevenueIntegrityAnalyst`,
    `PricingCommitteeApprover`, `ComplianceOfficer`, `ContractManager` and `DepartmentManager`.
    Immediately after authentication, the server checks that the acting role appears in the
    authorized-role list for the endpoint being called (see the table in §4); a role that is not listed
    receives `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §2.9: "2. Endpoint role admission — `ERR_ROLE_NOT_PERMITTED` (403)."
    PRD §3.3: "`PENDING_REVIEW → APPROVED` is a `PricingCommitteeApprover` action, and here the two
    dimensions finally meet."
    PRD §4: "| POST | `/chargemaster/charge-items` | Create a chargemaster item in `DRAFT` /
    `PRICE_STALE`. | RevenueIntegrityAnalyst |"
    PRD §4: "| POST | `/chargemaster/change-requests/{change_request_id}/decisions` | Non-approval
    decisions (`REVIEW`, `REQUEST_CHANGES`, `REJECT`, `WITHDRAW`). | RevenueIntegrityAnalyst,
    PricingCommitteeApprover, DepartmentManager |"
    PRD §4: "| POST | `/chargemaster/payer-contracts` | Create a payer contract term with closed-interval
    overlap and notice-buffer enforcement. | ContractManager |"
    PRD §4: "| POST | `/chargemaster/transparency-files` | Build a machine-readable transparency file for
    a facility. | ComplianceOfficer |"

    Design: Corner/rbac/analyst_cannot_approve_and_approver_cannot_author_and_admin_cannot_decide
    """
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(**MERCY)
    facility_id = base["facility"]["id"]
    item = create_priced_item(base, cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
                              code_type="CPT", code_value="93458", cost_basis_cents=100000,
                              medicare_rate_cents=50000, market_p75_cents=900000,
                              effective_from="2026-09-01T00:00:00Z")
    pending = item_lifecycle(item["id"], "SUBMIT_FOR_REVIEW", ANALYST)
    assert pending["lifecycle_status"] == "PENDING_REVIEW"
    assert pending["price_status"] == "PRICED_CURRENT"
    version_before = pending["version"]
    facility_version = read_facility(facility_id)["version"]

    request = create_change_request(base, item["id"], "PRICE_CHANGE",
                                    justification="Cost basis rose after the renewal",
                                    proposed_cost_basis_cents=150000)
    assert request["status"] == "SUBMITTED"

    validate_error(
        api_client.charge_item_lifecycle(item["id"], {"action": "APPROVE"}, ANALYST),
        DENIED, 403,
    )

    duplicate_payload = factories.create_charge_item_payload(
        facility_id, base["department"]["id"], base["revenue_code"]["id"],
        cdm_number="CDM-2002", description="CARDIAC CATH COMPLEX", code_type="CPT",
        code_value="93460", cost_basis_cents=100000, medicare_rate_cents=50000,
        market_p75_cents=900000, effective_from="2026-09-01T00:00:00Z")
    validate_error(api_client.create_charge_item(duplicate_payload, APPROVER), DENIED, 403)
    validate_error(api_client.reprice_charge_item(item["id"], APPROVER), DENIED, 403)

    validate_error(
        api_client.change_request_decision(
            request["id"],
            {"decision": "REVIEW", "decision_note": "Admin attempting an analyst review"},
            ADMIN),
        DENIED, 403,
    )
    validate_error(
        api_client.create_facility(
            factories.create_facility_payload(name="Saint Elsewhere",
                                             cms_certification_number="CCN-2193-RBACNEG2"),
            ANALYST),
        DENIED, 403,
    )
    validate_error(
        api_client.create_transparency_file(
            factories.create_transparency_file_payload(facility_id, facility_version,
                                                       file_format="CSV"), ANALYST),
        DENIED, 403,
    )
    validate_error(
        api_client.create_payer_contract(
            factories.create_payer_contract_payload(
                facility_id, payer_code="BCBS", product_line="COMMERCIAL",
                reimbursement_method="PERCENT_OF_CHARGE", percent_of_charge_bp=6000,
                term_start_date="2026-09-01T00:00:00Z", term_end_date="2027-08-31T23:59:59Z",
                renegotiation_notice_days=30, trailing_units=100), COMPLIANCE),
        DENIED, 403,
    )

    after = validate_success(api_client.get_charge_item(item["id"], ADMIN), 200)
    assert after["lifecycle_status"] == "PENDING_REVIEW", (
        "the analyst's APPROVE was refused on the header, not on the item's state"
    )
    assert after["version"] == version_before, "no refused call incremented the version"
    assert after["cdm_number"] == "CDM-1001"
    facility = read_facility(facility_id)
    assert facility["version"] == facility_version, "no refused write touched the facility"
    assert facility["chargemaster_posture"] == "OPEN", "the refused build never froze anything"
