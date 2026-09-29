"""The two-step approval chain: the state gate, then per-request identity rather than role set."""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId,
    setup_base, create_active_item, create_change_request, read_change_request,
    read_item, set_clock, make_analyst_headers, make_approver_headers,
    ANALYST2, ANALYST2_USER_ID, APPROVER, APPROVER_USER_ID, COMPLIANCE,
)

MERCY = dict(
    facility_overrides={
        "name": "Mercy General", "cms_certification_number": "CCN-2193-CHAIN",
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
PRICING = dict(cost_basis_cents=100000, medicare_rate_cents=50000,
               market_p75_cents=900000, effective_from="2026-09-01T00:00:00Z")
DUAL_USER_ID = "user-dual-1"
DUAL_ANALYST = make_analyst_headers(DUAL_USER_ID)
DUAL_APPROVER = make_approver_headers(DUAL_USER_ID)


def test_the_reviewer_of_record_cannot_approve_its_own_review_but_may_approve_a_sibling_request():
    """PRD §3.5: "Approval, `UNDER_REVIEW → APPROVED`, is reserved to the `PricingCommitteeApprover` and
    is the most heavily guarded transition in the system."
    PRD §3.5: "First — after the generic state admissibility check and before every business rule — the
    supplied `expected_charge_item_version` must equal the live `ChargeItem.version`, otherwise
    `ERR_STALE_ITEM_VERSION` (HTTP 412)."
    PRD §3.5: "Any decision, resubmit or implementation attempted from a state that does not declare it is
    `ERR_INVALID_REQUEST_STATE` (409)."
    PRD §3.5: "Second, `X-User-ID` must differ from `submitted_by_user_id` *and* from
    `reviewed_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`)."
    PRD §2.9: "18. Segregation of duties — `ERR_SEGREGATION_OF_DUTIES` (409)."
    PRD §2.1: "The server records it where a workflow demands an audit trail — as `approved_by_user_id` on
    a charge item or a change request, as `reviewed_by_user_id` or `submitted_by_user_id` on a change
    request, as `mapped_by_user_id` on a code-update entry, as `signed_off_by_user_id` on an impact
    analysis — and it compares recorded operator identifiers against each other to enforce segregation of
    duties, but it never compares them to any entity's `id`."

    Design: Corner/rbac/approval_chain_rejects_a_skipped_review_and_a_self_approval_by_the_reviewing_user
    """
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(**MERCY)
    first_item = create_active_item(base, cdm_number="CDM-1001",
                                    description="CARDIAC CATH BASIC", code_type="CPT",
                                    code_value="93458", **PRICING)
    second_item = create_active_item(base, cdm_number="CDM-1002",
                                     description="CARDIAC CATH COMPLEX", code_type="CPT",
                                     code_value="93460", **PRICING)
    assert first_item["version"] == 5 and second_item["version"] == 5

    request_a = create_change_request(base, first_item["id"], "PRICE_CHANGE",
                                      justification="Request A raises the tray cost basis",
                                      proposed_cost_basis_cents=150000)
    request_b = create_change_request(base, second_item["id"], "PRICE_CHANGE",
                                      justification="Request B raises the catheter cost basis",
                                      proposed_cost_basis_cents=160000)
    assert request_a["status"] == "SUBMITTED"
    assert request_b["projected_gross_charge_cents"] == 384000

    validate_error(
        api_client.approve_change_request(
            request_a["id"],
            {"expected_charge_item_version": 5,
             "decision_note": "Approving straight from SUBMITTED without a review"}, APPROVER),
        ApiErrorId.ERR_INVALID_REQUEST_STATE.value, 409,
    )

    reviewed_a = validate_success(api_client.change_request_decision(
        request_a["id"],
        {"decision": "REVIEW", "decision_note": "Cost documentation checked by the dual user"},
        DUAL_ANALYST), 200)
    assert reviewed_a["status"] == "UNDER_REVIEW"
    assert reviewed_a["reviewed_by_user_id"] == DUAL_USER_ID

    validate_error(
        api_client.approve_change_request(
            request_a["id"],
            {"expected_charge_item_version": 5,
             "decision_note": "The same user attempting to approve what it reviewed"},
            DUAL_APPROVER),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 409,
    )
    assert read_change_request(request_a["id"])["status"] == "UNDER_REVIEW", (
        "the refused approval left the request under review"
    )
    assert read_item(first_item["id"])["version"] == 5, "and left the item untouched"

    reviewed_b = validate_success(api_client.change_request_decision(
        request_b["id"],
        {"decision": "REVIEW", "decision_note": "Catheter invoice checked by another analyst"},
        ANALYST2), 200)
    assert reviewed_b["status"] == "UNDER_REVIEW"
    assert reviewed_b["reviewed_by_user_id"] == ANALYST2_USER_ID

    approved_b = validate_success(api_client.approve_change_request(
        request_b["id"],
        {"expected_charge_item_version": 5,
         "decision_note": "The dual user did not review this one, so it may approve it"},
        DUAL_APPROVER), 200)
    assert approved_b["status"] == "APPROVED", (
        "the very same identity approves the sibling request it did not review"
    )
    assert approved_b["approved_by_user_id"] == DUAL_USER_ID
    assert approved_b["pinned_charge_item_version"] == 6

    approved_a = validate_success(api_client.approve_change_request(
        request_a["id"],
        {"expected_charge_item_version": 5,
         "decision_note": "A different approver closes request A"}, APPROVER), 200)
    assert approved_a["status"] == "APPROVED"
    assert approved_a["approved_by_user_id"] == APPROVER_USER_ID
    assert approved_a["pinned_charge_item_version"] == 6

    final_a = validate_success(api_client.get_change_request(request_a["id"], COMPLIANCE), 200)
    assert final_a["reviewed_by_user_id"] == DUAL_USER_ID
    assert final_a["approved_by_user_id"] == APPROVER_USER_ID, (
        "the rule is pinned to per-request identity, not to the user's role set"
    )
    for item_id in (first_item["id"], second_item["id"]):
        moved = read_item(item_id)
        assert moved["price_status"] == "REPRICE_PENDING"
        assert moved["version"] == 6
