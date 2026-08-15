"""Restructure plans: the revision cycle, withdraw, the distress gate, DISASTER
prerequisites, segregation of duties on approval, and OCC on the loan version
(PRD sections 2.6, 3.8).
"""
from test_helpers import (
    ApiErrorId, TEST_USERS, api_client, create_plan, create_plan_payload,
    fresh_loan_version, get_loan, get_success_data, make_committee_headers,
    make_officer_headers, setup_active_loan, setup_distressed_loan,
    setup_distressed_loan_with_plan, validate_error, validate_success,
)

OFFICER = TEST_USERS["loan_officer_headers"]    # opaque id "officer-1"
OFFICER2 = TEST_USERS["loan_officer2_headers"]  # opaque id "officer-2"
COMMITTEE = TEST_USERS["committee_headers"]     # opaque id "committee-1"


def test_restructure_plan_revision_cycle(api):
    """PRD section 3.8: "or rejects it with an optional `reason`, moving it to
    `REJECTED` and returning the loan `RESTRUCTURING` → `ACTIVE` when no other
    non-terminal plan exists for the loan. Rejection is not the end: resubmitting
    a `REJECTED` plan sends it back to `COMMITTEE_REVIEW` and reopens the loan's
    restructuring, moving the loan `ACTIVE` → `RESTRUCTURING` again." PRD section
    3.8: "then `base_balance_cents` is frozen as the `outstanding_principal_cents`
    plus, when `capitalize_interest` is true, the `accrued_interest_cents`, and
    `new_installment_cents` is computed from those frozen figures."

    Design: Difficulty/non_linear_state_machine/restructure_plan_revision_cycle
    """
    ctx = setup_distressed_loan(draw_cents=10_000_000,
                                projected_revenue_cents=10_000_000,
                                projected_expenses_cents=8_000_000)
    plan = create_plan(ctx, amortization_style="EQUAL_INSTALLMENT",
                       extension_months=12, new_rate_bps=600,
                       capitalize_interest=False)
    assert plan["base_balance_cents"] == 10_000_000, \
        "capitalize_interest false: accrued interest is excluded from the frozen base"
    assert plan["status"] == "PROPOSED"
    assert get_loan(ctx["loan"]["id"])["status"] == "RESTRUCTURING"

    data = validate_success(api.submit_restructure_plan(plan["id"], OFFICER), 200)
    assert data["status"] == "COMMITTEE_REVIEW"
    data = validate_success(api.reject_restructure_plan(
        plan["id"], COMMITTEE, reason="terms too lenient"), 200)
    assert data["status"] == "REJECTED"
    assert get_loan(ctx["loan"]["id"])["status"] == "ACTIVE", \
        "rejection returns the loan to ACTIVE when no other open plan exists"

    data = validate_success(api.submit_restructure_plan(plan["id"], OFFICER), 200)
    assert data["status"] == "COMMITTEE_REVIEW", "the revision cycle revisits review"
    assert get_loan(ctx["loan"]["id"])["status"] == "RESTRUCTURING", \
        "resubmission reopens the restructuring"

    data = validate_success(api.approve_restructure_plan(plan["id"], COMMITTEE), 200)
    assert data["status"] == "APPROVED"


def test_restructure_plan_withdraw_returns_loan_active(api):
    """PRD section 3.8: "The officer may also withdraw a `PROPOSED` plan to
    `WITHDRAWN`, which likewise returns the loan to `ACTIVE` when no other
    non-terminal plan remains."

    Design: Difficulty/non_linear_state_machine/restructure_plan_revision_cycle
    """
    ctx = setup_distressed_loan_with_plan()
    assert get_loan(ctx["loan"]["id"])["status"] == "RESTRUCTURING"
    data = validate_success(api.withdraw_restructure_plan(ctx["plan"]["id"], OFFICER), 200)
    assert data["status"] == "WITHDRAWN"
    assert get_loan(ctx["loan"]["id"])["status"] == "ACTIVE"


def test_restructure_gate_on_healthy_loan_rejected(api):
    """PRD section 3.8: "A `LoanOfficer` proposes a plan for a distressed loan,
    and the creation is heavily gated: the loan must be `ACTIVE`, else
    `ERR_LOAN_NOT_ACTIVE`; the distress gate requires the posture to be
    `DELINQUENT` or `DEFAULT` or an `ISSUED` or `ESCALATED` margin call to exist
    for the loan, else `ERR_RESTRUCTURE_GATE_NOT_MET`".

    Design: Corner/validations/restructure_gate_on_healthy_loan_rejected
    """
    ctx = setup_active_loan()  # CURRENT posture, no margin calls
    resp = api.create_restructure_plan(
        create_plan_payload(loan_account_id=ctx["loan"]["id"],
                            expected_loan_version=fresh_loan_version(ctx["loan"]["id"])),
        OFFICER)
    validate_error(resp, ApiErrorId.ERR_RESTRUCTURE_GATE_NOT_MET)
    assert get_loan(ctx["loan"]["id"])["status"] == "ACTIVE"


def test_disaster_plan_without_declaration_rejected(api):
    """PRD section 3.8: "A `DISASTER` plan carries two further prerequisites: an
    active disaster declaration covering the borrower, and at least one `APPROVED`,
    `IN_EFFECT`, or `EXPIRED` deferral on the loan; missing either is rejected with
    `ERR_DISASTER_REQUIRED`."

    Design: Corner/validations/disaster_plan_without_declaration_rejected
    """
    ctx = setup_distressed_loan()  # DELINQUENT with an ISSUED margin call
    loan_id = ctx["loan"]["id"]
    v_pre = fresh_loan_version(loan_id)

    resp = api.create_restructure_plan(
        create_plan_payload(loan_account_id=loan_id, plan_type="DISASTER",
                            amortization_style="BALLOON", extension_months=24,
                            new_rate_bps=400, capitalize_interest=True,
                            expected_loan_version=v_pre),
        OFFICER)
    validate_error(resp, ApiErrorId.ERR_DISASTER_REQUIRED)
    assert fresh_loan_version(loan_id) == v_pre, "a rejected create mutates nothing"

    plan = validate_success(api.create_restructure_plan(
        create_plan_payload(loan_account_id=loan_id, plan_type="STANDARD",
                            expected_loan_version=v_pre),
        OFFICER), 201)
    assert plan["status"] == "PROPOSED", \
        "the same distressed loan accepts a STANDARD plan"


def test_plan_approve_by_creator_segregation_rejected(api):
    """PRD section 3.8: "The committee approves a plan in review — but the member
    whose `X-User-ID` equals the plan's `created_by_user_id` is barred by
    segregation of duties, rejected with `ERR_SEGREGATION_OF_DUTIES` — moving it to
    `APPROVED`".

    Design: Corner/validations/plan_approve_by_creator_segregation_rejected
    """
    ctx = setup_distressed_loan_with_plan(officer_headers=make_officer_headers("officer-1"))
    assert ctx["plan"]["created_by_user_id"] == "officer-1"
    get_success_data(api.submit_restructure_plan(ctx["plan"]["id"], OFFICER))

    resp = api.approve_restructure_plan(
        ctx["plan"]["id"], make_committee_headers("officer-1"))  # creator's id
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    data = validate_success(api.approve_restructure_plan(
        ctx["plan"]["id"], make_committee_headers("committee-1")), 200)
    assert data["status"] == "APPROVED", "a distinct committee user may approve"


def test_occ_plan_create_stale_version_returns_412(api):
    """PRD section 2.6: "Creating a restructure plan likewise requires
    `expected_loan_version` matching the loan's current `version`. A new plan
    legitimately supersedes the prior non-terminal plan and moves the loan to
    `RESTRUCTURING`, so a stale writer would unknowingly supersede terms it never
    saw; a version mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_plan_create_stale_version_returns_412
    """
    ctx = setup_distressed_loan()
    loan_id = ctx["loan"]["id"]
    v_pre = fresh_loan_version(loan_id)

    plan1 = validate_success(api.create_restructure_plan(
        create_plan_payload(loan_account_id=loan_id, amortization_style="BALLOON",
                            extension_months=12, new_rate_bps=600,
                            expected_loan_version=v_pre),
        make_officer_headers("officer-1")), 201)
    assert fresh_loan_version(loan_id) == v_pre + 1

    resp = api.create_restructure_plan(
        create_plan_payload(loan_account_id=loan_id,
                            amortization_style="EQUAL_INSTALLMENT",
                            extension_months=18, new_rate_bps=650,
                            expected_loan_version=v_pre),  # stale replay
        make_officer_headers("officer-2"))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert validate_success(api.get_restructure_plan(plan1["id"], OFFICER), 200)[
        "status"] == "PROPOSED", "the rejected create supersedes nothing"
