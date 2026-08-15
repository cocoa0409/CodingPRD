"""Grant recommendation lifecycle: revision loop, approval gates, validation
ordering, OCC on the fund, and role segregation."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    create_active_fund,
    create_cleared_grantee,
    create_grantee_payload,
    create_draft_grant,
    create_grant_in_review,
    invite_and_accept_advisor,
    make_officer_headers,
    make_advisor_headers,
    submit_grant,
    get_fund,
    get_fund_version,
    assert_grant,
    assert_money_eq,
    is_iso8601_timestamp,
    ApiErrorId,
    TEST_USERS,
)

ADMIN = TEST_USERS["foundation_admin_headers"]
GIFT = TEST_USERS["gift_officer_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]


def _setup_daf_fund_with_advisor(seed=50000.00):
    bundle = create_active_fund(fund_type="DONOR_ADVISED", seed_amount=seed)
    advisor = invite_and_accept_advisor(bundle["fund"]["id"], advisor_kind="PRIMARY")
    return bundle["fund"], advisor


def test_third_return_auto_denies_grant(api):
    """PRD §3.6: "Returning the grant moves it from `COMPLIANCE_REVIEW` to
    `RETURNED` and increments `revision_count`; when that increment brings the
    count to 3, the grant immediately auto-transitions from `RETURNED` to
    `DENIED` with `decided_at` set, closing the revision loop — and since a
    `DENIED` grant is terminal, no further submission is possible from it."

    Design: Difficulty/non_linear_state_machine/grant_revision_loop_third_return_auto_denies
    """
    fund, advisor = _setup_daf_fund_with_advisor()
    grantee = create_cleared_grantee()
    grant = create_draft_grant(
        fund_id=fund["id"], grantee_id=grantee["id"], amount=1000.00,
        advisor_id=advisor["id"],
    )
    # Two full RETURNED -> SUBMITTED revision cycles.
    for _ in range(2):
        submit_grant(grant, advisor_id=advisor["id"])
        validate_success(api.claim_grant_review(grant["id"], COMPLIANCE))
        returned = validate_success(api.return_grant(grant["id"], COMPLIANCE))
        assert returned["status"] == "RETURNED"
    # Third cycle: the third return cascades to DENIED.
    submit_grant(grant, advisor_id=advisor["id"])
    validate_success(api.claim_grant_review(grant["id"], COMPLIANCE))
    final = validate_success(api.return_grant(grant["id"], COMPLIANCE))
    assert final["revision_count"] == 3
    assert final["status"] == "DENIED"
    assert final["decided_at"] is not None
    assert is_iso8601_timestamp(final["decided_at"])


def test_auto_denied_grant_rejects_further_submission(api):
    """PRD §3.6: "Returning the grant moves it from `COMPLIANCE_REVIEW` to
    `RETURNED` and increments `revision_count`; when that increment brings the
    count to 3, the grant immediately auto-transitions from `RETURNED` to
    `DENIED` with `decided_at` set, closing the revision loop — and since a
    `DENIED` grant is terminal, no further submission is possible from it."

    Design: Difficulty/non_linear_state_machine/grant_revision_loop_third_return_auto_denies
    """
    fund, advisor = _setup_daf_fund_with_advisor()
    grantee = create_cleared_grantee()
    grant = create_draft_grant(
        fund_id=fund["id"], grantee_id=grantee["id"], amount=1000.00,
        advisor_id=advisor["id"],
    )
    for _ in range(3):
        submit_grant(grant, advisor_id=advisor["id"])
        validate_success(api.claim_grant_review(grant["id"], COMPLIANCE))
        last = validate_success(api.return_grant(grant["id"], COMPLIANCE))
    assert last["status"] == "DENIED"
    resp = api.submit_grant(grant["id"], make_advisor_headers(advisor["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api.get_grant(grant["id"], COMPLIANCE))
    assert after["status"] == "DENIED"


def test_approve_rejected_while_grantee_in_review(api):
    """PRD §3.6: "Second, the grantee's `due_diligence_status` must be `CLEARED`
    at the decision instant — a grantee sitting in `UNVETTED`, `IN_REVIEW`,
    `REJECTED_DD`, or `EXPIRED` fails with `ERR_GRANTEE_NOT_CLEARED` (HTTP 422),
    which is how the twelve-month freshness window bites."

    Design: Difficulty/cross_entity_state_dependency/grant_approve_depends_on_grantee_cleared
    """
    bundle = create_active_fund(fund_type="DESIGNATED", seed_amount=50000.00)
    grantee = validate_success(
        api.create_grantee(create_grantee_payload(), COMPLIANCE), 201
    )
    validate_success(api.begin_grantee_review(grantee["id"], COMPLIANCE))
    grant = create_grant_in_review(
        fund_id=bundle["fund"]["id"], grantee_id=grantee["id"], amount=1000.00,
        claimer_id="co-1",
    )
    resp = api.approve_grant(
        grant["id"], {}, make_officer_headers("ComplianceOfficer", "co-2")
    )
    validate_error(resp, ApiErrorId.ERR_GRANTEE_NOT_CLEARED)
    after = validate_success(api.get_grant(grant["id"], COMPLIANCE))
    assert after["status"] == "COMPLIANCE_REVIEW"


def test_approve_succeeds_after_grantee_cleared(api):
    """PRD §3.6: "Second, the grantee's `due_diligence_status` must be `CLEARED`
    at the decision instant — a grantee sitting in `UNVETTED`, `IN_REVIEW`,
    `REJECTED_DD`, or `EXPIRED` fails with `ERR_GRANTEE_NOT_CLEARED` (HTTP 422),
    which is how the twelve-month freshness window bites."
    PRD §3.6: "Clearing moves the grantee from `IN_REVIEW` to `CLEARED` and
    stamps `cleared_at` from the logical clock; rejecting moves it to
    `REJECTED_DD`."

    Design: Difficulty/cross_entity_state_dependency/grant_approve_depends_on_grantee_cleared
    """
    bundle = create_active_fund(fund_type="DESIGNATED", seed_amount=50000.00)
    grantee = validate_success(
        api.create_grantee(create_grantee_payload(), COMPLIANCE), 201
    )
    validate_success(api.begin_grantee_review(grantee["id"], COMPLIANCE))
    grant = create_grant_in_review(
        fund_id=bundle["fund"]["id"], grantee_id=grantee["id"], amount=1000.00,
        claimer_id="co-1",
    )
    approver = make_officer_headers("ComplianceOfficer", "co-2")
    validate_error(
        api.approve_grant(grant["id"], {}, approver),
        ApiErrorId.ERR_GRANTEE_NOT_CLEARED,
    )
    cleared = validate_success(api.clear_grantee(grantee["id"], COMPLIANCE))
    assert cleared["due_diligence_status"] == "CLEARED"
    approved = validate_success(api.approve_grant(grant["id"], {}, approver), 200)
    assert approved["status"] == "APPROVED"


def test_submit_at_exact_250_minimum(api):
    """PRD §3.6: "The `amount` must be at least 250.00 dollars, failing with
    `ERR_GRANT_BELOW_MINIMUM` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/grant_minimum_amount_250_boundary
    """
    bundle = create_active_fund(fund_type="DESIGNATED", seed_amount=50000.00)
    grantee = create_cleared_grantee()
    grant = create_draft_grant(
        fund_id=bundle["fund"]["id"], grantee_id=grantee["id"], amount=250.00
    )
    resp = api.submit_grant(grant["id"], ADMIN)
    data = validate_success(resp, 200)
    # Exactly 250.00 satisfies the "at least" floor.
    assert data["status"] == "SUBMITTED"


def test_amount_below_250_rejected_at_creation(api):
    """PRD §3.6: "Grant amounts observe a floor of 250.00 dollars, enforced as
    a field constraint at creation with `ERR_FIELD_CONSTRAINT` and re-checked at
    submission with the more specific error below."

    Design: Difficulty/boundary_precision_check/grant_minimum_amount_250_boundary
    """
    bundle = create_active_fund(fund_type="DESIGNATED", seed_amount=50000.00)
    grantee = create_cleared_grantee()
    resp = api.create_grant(
        {
            "fund_id": bundle["fund"]["id"],
            "grantee_id": grantee["id"],
            "amount": 249.99,
            "purpose": "Below min",
            "expected_fund_version": get_fund_version(bundle["fund"]["id"]),
        },
        ADMIN,
    )
    # The floor rejects 249.99 at creation, so no sub-250 DRAFT can ever reach
    # the submission-time re-check.
    validate_error(resp, ApiErrorId.ERR_FIELD_CONSTRAINT)


def test_draft_grant_approve_reports_state_error_not_fiscal(api):
    """PRD §2.9: "When several checks could reject the same request, they are
    evaluated in a fixed order, and the earliest failing check determines the
    error returned."
    PRD §2.9: "(5) legality of the target resource's state for the requested
    transition, failing with `ERR_INVALID_STATE` or the more specific state
    error named in §3" precedes "(13) fiscal capacity checks against balances
    and holdings".

    Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_on_grant_approve
    """
    bundle = create_active_fund(
        fund_type="DESIGNATED", endowed=True, seed_amount=200000.00
    )
    grantee = create_cleared_grantee()
    # 99999.00 would exceed spendable at approve, but the grant is still DRAFT,
    # so the state check fails first.
    grant = create_draft_grant(
        fund_id=bundle["fund"]["id"], grantee_id=grantee["id"], amount=99999.00
    )
    resp = api.approve_grant(grant["id"], {}, COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api.get_grant(grant["id"], COMPLIANCE))
    assert after["status"] == "DRAFT"


def test_overspend_reported_when_state_legal(api):
    """PRD §3.5: "A fund's `current_spending_allowance` is 0.00 until its first
    run."
    PRD §3.6: "Fourth, the `amount` must not exceed the fund's
    `spendable_balance` at the decision instant — the allowance-aware figure of
    §3.5 — failing with `ERR_EXCEEDS_SPENDABLE` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_on_grant_approve
    """
    bundle = create_active_fund(
        fund_type="DESIGNATED", endowed=True, seed_amount=200000.00
    )
    grantee = create_cleared_grantee()
    grant = create_grant_in_review(
        fund_id=bundle["fund"]["id"], grantee_id=grantee["id"], amount=99999.00,
        claimer_id="co-1",
    )
    resp = api.approve_grant(
        grant["id"], {}, make_officer_headers("ComplianceOfficer", "co-2")
    )
    validate_error(resp, ApiErrorId.ERR_EXCEEDS_SPENDABLE)
    after = validate_success(api.get_grant(grant["id"], COMPLIANCE))
    assert after["status"] == "COMPLIANCE_REVIEW"


def test_self_approval_reports_sod_not_clearance(api):
    """PRD §3.6: "Approval is then the densest gate in the system, and its four
    checks are evaluated in order so that an early failure is never masked by a
    later one."
    PRD §3.6: "First, segregation of duties: the approving officer's `X-User-ID`
    must differ from the `X-User-ID` that claimed the review, failing with
    `ERR_SOD_SELF_APPROVAL` (HTTP 403)."

    Design: Difficulty/priority_pair_validation_conflict/sod_before_compliance_gate_on_approve
    """
    bundle = create_active_fund(fund_type="DESIGNATED", seed_amount=50000.00)
    grantee = validate_success(
        api.create_grantee(create_grantee_payload(), COMPLIANCE), 201
    )
    grant = create_grant_in_review(
        fund_id=bundle["fund"]["id"], grantee_id=grantee["id"], amount=1000.00,
        claimer_id="co-solo",
    )
    # Same officer claims and approves; the grantee is also not CLEARED, but
    # the segregation check is evaluated first.
    resp = api.approve_grant(
        grant["id"], {}, make_officer_headers("ComplianceOfficer", "co-solo")
    )
    validate_error(resp, ApiErrorId.ERR_SOD_SELF_APPROVAL)
    after = validate_success(api.get_grant(grant["id"], COMPLIANCE))
    assert after["status"] == "COMPLIANCE_REVIEW"


def test_uncleared_grantee_reported_when_sod_clean(api):
    """PRD §3.6: "Second, the grantee's `due_diligence_status` must be `CLEARED`
    at the decision instant — a grantee sitting in `UNVETTED`, `IN_REVIEW`,
    `REJECTED_DD`, or `EXPIRED` fails with `ERR_GRANTEE_NOT_CLEARED` (HTTP 422),
    which is how the twelve-month freshness window bites."

    Design: Difficulty/priority_pair_validation_conflict/sod_before_compliance_gate_on_approve
    """
    bundle = create_active_fund(fund_type="DESIGNATED", seed_amount=50000.00)
    grantee = validate_success(
        api.create_grantee(create_grantee_payload(), COMPLIANCE), 201
    )
    grant = create_grant_in_review(
        fund_id=bundle["fund"]["id"], grantee_id=grantee["id"], amount=1000.00,
        claimer_id="co-solo",
    )
    resp = api.approve_grant(
        grant["id"], {}, make_officer_headers("ComplianceOfficer", "co-other")
    )
    validate_error(resp, ApiErrorId.ERR_GRANTEE_NOT_CLEARED)


def test_disburse_draft_grant_invalid_state(api):
    """PRD §3.6: "A `FinanceOfficer` disburses an `APPROVED` grant under two
    checks in order: the disbursing officer's `X-User-ID` must differ from the
    approving officer's recorded identity, failing with
    `ERR_SOD_SELF_DISBURSE` (HTTP 403), and the `amount` must not exceed the
    fund's `cash_balance`, failing with `ERR_INSUFFICIENT_CASH`."
    PRD §2.9: "(5) legality of the target resource's state for the requested
    transition, failing with `ERR_INVALID_STATE` or the more specific state
    error named in §3"

    Design: Corner/state_machines/grant_invalid_transition_draft_to_disburse
    """
    bundle = create_active_fund(fund_type="DESIGNATED", seed_amount=50000.00)
    fund_id = bundle["fund"]["id"]
    grantee = create_cleared_grantee()
    grant = create_draft_grant(fund_id=fund_id, grantee_id=grantee["id"], amount=500.00)
    resp = api.disburse_grant(grant["id"], FINANCE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    fund = get_fund(fund_id)
    assert_money_eq(fund["cash_balance"], 50000.00, "cash unchanged")
    disbursements, _ = validate_paginated(api.list_fund_disbursements(fund_id, FINANCE))
    assert disbursements == []


def test_denied_grant_is_terminal(api):
    """PRD §3.6: "Denying outright moves the grant to `DENIED` with `decided_at`
    set."
    PRD §3.6: "Returning the grant moves it from `COMPLIANCE_REVIEW` to
    `RETURNED` and increments `revision_count`; when that increment brings the
    count to 3, the grant immediately auto-transitions from `RETURNED` to
    `DENIED` with `decided_at` set, closing the revision loop — and since a
    `DENIED` grant is terminal, no further submission is possible from it."

    Design: Corner/state_machines/terminal_state_lockdown_denied_grant
    """
    bundle = create_active_fund(fund_type="DESIGNATED", seed_amount=50000.00)
    grantee = create_cleared_grantee()
    grant = create_grant_in_review(
        fund_id=bundle["fund"]["id"], grantee_id=grantee["id"], amount=500.00
    )
    denied = validate_success(api.deny_grant(grant["id"], COMPLIANCE))
    assert denied["status"] == "DENIED"
    assert denied["decided_at"] is not None

    resp = api.submit_grant(grant["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    resp2 = api.approve_grant(grant["id"], {}, make_officer_headers("ComplianceOfficer", "co-2"))
    validate_error(resp2, ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api.get_grant(grant["id"], COMPLIANCE))
    assert after["status"] == "DENIED"


def test_stale_fund_version_on_grant_create(api):
    """PRD §2.8: "Creating a grant recommendation requires the request to carry
    `expected_fund_version`, holding the target fund's `version` as the client
    last observed it."
    PRD §2.8: "If `expected_fund_version` does not match the fund's current
    `version`, the creation is rejected with `ERR_STALE_FUND_VERSION`
    (HTTP 412)."

    Design: Corner/endpoints/occ_stale_fund_version_on_grant_create
    """
    bundle = create_active_fund(fund_type="DESIGNATED", seed_amount=50000.00)
    fund_id = bundle["fund"]["id"]
    grantee = create_cleared_grantee()
    observed_version = get_fund_version(fund_id)
    first = api.create_grant(
        {
            "fund_id": fund_id,
            "grantee_id": grantee["id"],
            "amount": 500.00,
            "purpose": "First",
            "expected_fund_version": observed_version,
        },
        ADMIN,
    )
    validate_success(first, 201)
    # The first creation advanced the fund's version; replaying the stale
    # observation is rejected.
    second = api.create_grant(
        {
            "fund_id": fund_id,
            "grantee_id": grantee["id"],
            "amount": 600.00,
            "purpose": "Second stale",
            "expected_fund_version": observed_version,
        },
        ADMIN,
    )
    validate_error(second, ApiErrorId.ERR_STALE_FUND_VERSION)


def test_gift_officer_cannot_approve(api):
    """PRD §2.1: "A `ComplianceOfficer` registers grantees, runs due diligence,
    and claims, approves, returns, denies, and cancels grants — with the
    constraint that the approving officer is never the officer who claimed the
    review."
    PRD §2.1: "A request whose role is not permitted on the target endpoint is
    rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/roles/gift_officer_cannot_approve_grant
    """
    bundle = create_active_fund(fund_type="DESIGNATED", seed_amount=50000.00)
    grantee = create_cleared_grantee()
    grant = create_grant_in_review(
        fund_id=bundle["fund"]["id"], grantee_id=grantee["id"], amount=500.00,
        claimer_id="co-1",
    )
    resp = api.approve_grant(grant["id"], {}, GIFT)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_advisor_from_other_fund_cannot_submit(api):
    """PRD §3.6: "Authorization then depends on fund type: on a `DONOR_ADVISED`
    fund, `recommended_by_advisor_id` must reference an `ACTIVE` advisor of that
    fund and the acting `X-User-ID` must equal it, failing with
    `ERR_ADVISOR_NOT_AUTHORIZED` (HTTP 403); on a `DESIGNATED` or `SCHOLARSHIP`
    fund the actor is a `FoundationAdmin` and `recommended_by_advisor_id` is
    null."

    Design: Corner/validations/cross_reference_advisor_wrong_fund
    """
    fund_a = create_active_fund(fund_type="DONOR_ADVISED", seed_amount=50000.00)["fund"]
    fund_b = create_active_fund(fund_type="DONOR_ADVISED", seed_amount=50000.00)["fund"]
    advisor = invite_and_accept_advisor(fund_b["id"], advisor_kind="PRIMARY")
    grantee = create_cleared_grantee()
    # Advisor is ACTIVE on fund B; the grant targets fund A.
    grant = create_draft_grant(
        fund_id=fund_a["id"], grantee_id=grantee["id"], amount=500.00,
        advisor_id=advisor["id"],
    )
    resp = api.submit_grant(grant["id"], make_advisor_headers(advisor["id"]))
    validate_error_is_one_of(
        resp,
        [ApiErrorId.ERR_ADVISOR_NOT_AUTHORIZED, ApiErrorId.ERR_CROSS_REFERENCE_MISMATCH],
    )
    after = validate_success(api.get_grant(grant["id"], COMPLIANCE))
    assert after["status"] == "DRAFT"
