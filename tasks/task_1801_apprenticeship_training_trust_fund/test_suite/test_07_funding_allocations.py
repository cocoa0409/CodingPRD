"""Funding allocations: proposal, committee approval gates (OCC, posture,
segregation of duties, fiscal), rejection, and RBAC (PRD §3.7, §2.8, §2.9,
§2.10)."""
from test_helpers import (
    ADMIN,
    CM1,
    CM2,
    ApiErrorId,
    approve_allocation,
    approve_allocation_payload,
    assert_allocation_ledger,
    create_employer,
    create_fund,
    get_allocation,
    get_fund,
    make_committee_member_headers,
    make_employer_rep_headers,
    make_trust_admin_headers,
    propose_allocation,
    setup_active_allocation,
    setup_paid_report,
    validate_error,
    validate_success,
)


def test_self_approval_wins_over_insufficient_funds(api):
    """PRD §2.10: "When several checks could reject the same request, the
    server evaluates them in a fixed order, and a request failing several
    checks surfaces the error from the earliest tier."
    PRD §2.10: "Seventh, compliance and safety gates: registration
    requirements, fund posture, segregation of duties, and certification
    prerequisites."
    PRD §2.10: "Ninth and last, the fiscal checks: tender-equals-due,
    allocation-fits-fund, and purchase-fits-allocation."
    PRD §2.8: "Approving a funding allocation requires the approver's
    `X-User-ID` to differ from the allocation's `proposed_by_user_id`;
    approving an equipment purchase requires the decider's `X-User-ID` to
    differ from the purchase's `requested_by_user_id`. A violation of either
    rule is rejected with `ERR_SELF_APPROVAL_FORBIDDEN` (HTTP 403)."

    Design: Difficulty/priority_pair_validation_conflict/priority_sod_vs_fiscal_allocation_approve
    """
    fund = create_fund()
    assert get_fund(fund["id"])["available_cents"] == 0, (
        "no contributions: the fiscal gate would also fail"
    )
    allocation = propose_allocation(
        fund["id"], 1000000,
        proposer_headers=make_trust_admin_headers("admin-1"),
    )
    assert allocation["proposed_by_user_id"] == "admin-1"
    fund_version = get_fund(fund["id"])["version"]

    resp = api.approve_funding_allocation(
        allocation["id"],
        approve_allocation_payload(fund_version),
        make_committee_member_headers("admin-1"),
    )
    validate_error(resp, ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN)
    assert resp.status_code == 403
    assert get_allocation(allocation["id"])["status"] == "PROPOSED"


def test_self_approval_rejected_even_when_funded(api):
    """PRD §3.7: "The approver's `X-User-ID` must differ from the allocation's
    `proposed_by_user_id` (else `ERR_SELF_APPROVAL_FORBIDDEN`, HTTP 403)."

    Design: Difficulty/priority_pair_validation_conflict/priority_sod_vs_fiscal_allocation_approve
    """
    fund, _employer, _apprentice, _report = setup_paid_report(
        hours=1000, rate=500,
    )
    assert get_fund(fund["id"])["available_cents"] == 500000, (
        "the fiscal gate is satisfied; only segregation of duties fails"
    )
    allocation = propose_allocation(
        fund["id"], 100000,
        proposer_headers=make_trust_admin_headers("admin-1"),
    )
    fund_version = get_fund(fund["id"])["version"]

    resp = api.approve_funding_allocation(
        allocation["id"],
        approve_allocation_payload(fund_version),
        make_committee_member_headers("admin-1"),
    )
    validate_error(resp, ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN)
    assert get_allocation(allocation["id"])["status"] == "PROPOSED"


def test_allocation_approve_at_exact_available_boundary(api):
    """PRD §3.7: "And the `amount_cents` must not exceed the fund's
    `available_cents` (else `ERR_INSUFFICIENT_FUND_AVAILABLE`, HTTP 402)."
    PRD §3.7: "An approved allocation becomes `ACTIVE`: the fund's
    `allocated_remaining_cents` grows by the allocation amount,
    `available_cents` is recomputed, the fund's `version` advances by exactly
    one, and `approved_by_user_id` — null until now — is stamped."

    Design: Corner/validations/allocation_approve_exact_available_boundary
    """
    fund, _employer, _apprentice, _report = setup_paid_report(
        hours=200, rate=500,
    )
    assert get_fund(fund["id"])["available_cents"] == 100000
    allocation = propose_allocation(fund["id"], 100000)
    fund_version = get_fund(fund["id"])["version"]

    resp = api.approve_funding_allocation(
        allocation["id"], approve_allocation_payload(fund_version), CM1,
    )
    data = validate_success(resp, 200)
    assert data["status"] == "ACTIVE", "amount equal to available does not exceed it"
    assert data["approved_by_user_id"] is not None
    assert_allocation_ledger(data)

    fund_after = get_fund(fund["id"])
    assert fund_after["available_cents"] == 0
    assert fund_after["allocated_remaining_cents"] == 100000


def test_allocation_approve_stale_version_rejected(api):
    """PRD §2.9: "If that value does not equal the trust fund's current
    `version`, the approval is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.9: "The fund's version advances by exactly one on each of five
    events — a remittance posting, an allocation approval, an allocation
    closure, a claim payment, and a purchase execution."

    Design: Corner/cross_cutting_layers/allocation_approve_stale_version_rejected
    """
    fund, _employer, _apprentice, _report = setup_paid_report(
        hours=1000, rate=500,
    )
    version_pre = get_fund(fund["id"])["version"]
    alloc1 = propose_allocation(fund["id"], 100000)
    alloc2 = propose_allocation(fund["id"], 50000, category="INSTRUCTION")

    approve_allocation(alloc1["id"], approver_headers=CM1,
                       expected_trust_fund_version=version_pre)
    version_post = get_fund(fund["id"])["version"]
    assert version_post == version_pre + 1, "allocation approval advanced the fund version"

    resp = api.approve_funding_allocation(
        alloc2["id"], approve_allocation_payload(version_pre), CM1,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert resp.status_code == 412

    retried = validate_success(
        api.approve_funding_allocation(
            alloc2["id"], approve_allocation_payload(version_post), CM1,
        ),
        200,
    )
    assert retried["status"] == "ACTIVE"
    assert get_fund(fund["id"])["allocated_remaining_cents"] == 150000


def test_approve_active_allocation_rejected(api):
    """PRD §3.7: "The allocation must be `PROPOSED` (else
    `ERR_ALLOCATION_NOT_ACTIVABLE`)."

    Design: Corner/errors/error_allocation_not_activable_on_active
    """
    fund, _employer, allocation = setup_active_allocation(
        amount_cents=1000, funded_hours=1000, rate=500,
    )
    assert allocation["status"] == "ACTIVE"
    fund_version = get_fund(fund["id"])["version"]

    resp = api.approve_funding_allocation(
        allocation["id"], approve_allocation_payload(fund_version), CM2,
    )
    validate_error(resp, ApiErrorId.ERR_ALLOCATION_NOT_ACTIVABLE)


def test_purchase_on_proposed_allocation_rejected(api):
    """PRD §3.7: "Against an `ACTIVE` allocation — purchase requests against
    an allocation in any other status are rejected with
    `ERR_ALLOCATION_NOT_ACTIVE` — a `TrustAdmin` requests an equipment
    purchase with `allocation_id`, a `description`, and an `amount_cents` of
    at least 1."

    Design: Corner/errors/error_allocation_not_active_on_purchase_create
    """
    fund = create_fund()
    allocation = propose_allocation(fund["id"], 1000)
    resp = api.create_equipment_purchase(
        {"allocation_id": allocation["id"], "description": "Multimeters",
         "amount_cents": 100},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_ALLOCATION_NOT_ACTIVE)


def test_allocation_reject_by_proposer_allowed(api):
    """PRD §3.7: "Rejection simply moves `PROPOSED` → `REJECTED`, guarded by
    state and role alone."
    PRD §2.8: "These are the only two operations with a proposer/requester
    relationship to police: pay-claim approval has no such anchor and is gated
    by fund posture alone."

    Design: Corner/state_machines/allocation_reject_sovereign
    """
    fund = create_fund()
    allocation = propose_allocation(
        fund["id"], 5000,
        proposer_headers=make_trust_admin_headers("cm-self"),
    )
    resp = api.reject_funding_allocation(
        allocation["id"], make_committee_member_headers("cm-self"),
    )
    data = validate_success(resp, 200)
    assert data["status"] == "REJECTED", (
        "segregation of duties constrains approvals, not rejections"
    )


def test_allocation_approve_by_employer_rep_forbidden(api):
    """PRD §2.1: "A request whose authenticated role is not permitted on the
    targeted endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4 maps `POST /funding-allocations/{id}/approve` to the
    CommitteeMember role only.

    Design: Corner/roles/allocation_approve_by_employer_rep_forbidden
    """
    fund = create_fund()
    employer = create_employer(fund["id"], rate=500)
    allocation = propose_allocation(fund["id"], 1000)
    fund_version = get_fund(fund["id"])["version"]

    resp = api.approve_funding_allocation(
        allocation["id"],
        approve_allocation_payload(fund_version),
        make_employer_rep_headers(employer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert resp.status_code == 403
    assert get_allocation(allocation["id"])["status"] == "PROPOSED"
