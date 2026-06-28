"""Resource CRUD, computed reads, FK reverse-reachability, RBAC, and the loan
optimistic-concurrency guard.

Translates the entities, endpoints, rbac and cross_cutting (OCC) corner sections
(queue B). The two excluded_because stubs
(occ_stale_policy_version_on_loan_excluded, issue_response_reflects_all_pinned_
fields_immediately) are NOT translated; their assertions are owned by the cited
difficulty instances.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    is_valid_uuid,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    make_policyholder_headers,
    build_user_headers,
    assert_product_plan,
    issue_active_policy,
    issue_active_policy_only,
    issue_vested_policy,
    create_plan,
    create_applicant,
    create_draft_application_with_questionnaire,
    set_clock,
    submit_application,
    disburse_loan,
)
from test_helpers.factories import (
    create_product_plan_payload,
    create_simple_plan_payload,
)
from test_helpers.api_client import api_client

PA = TEST_USERS["policy_admin_headers"]
UW = TEST_USERS["underwriter_headers"]
CE = TEST_USERS["claims_examiner_headers"]


# ===========================================================================
# Corner / entities
# ===========================================================================
def test_create_product_plan_returns_201(api):
    """PRD §3.1: "Everything begins with a ProductPlan, created by a PolicyAdmin.
    A plan carries a display name and a benefit_type (GUARANTEED_ISSUE,
    GRADED_BENEFIT, or LEVEL_BENEFIT)."
    PRD §2.5: "The id is a server-minted UUID with no type prefix."

    Design: Corner/entities/create_product_plan_returns_201_with_fields
    """
    payload = create_simple_plan_payload(name="Heritage Graded", benefit_type="GRADED_BENEFIT")
    plan = validate_success(api.create_product_plan(payload, PA), expected_status=201)

    assert plan["benefit_type"] == "GRADED_BENEFIT", plan
    assert is_valid_uuid(plan["id"]), "id must be a non-prefixed UUID"
    assert_product_plan(plan)


def test_get_nonexistent_policy_returns_not_found(api):
    """PRD §2.6: "any applicant_id, product_plan_id, policy_id, application_id, or
    claim_id named in a request body must resolve to a real resource, and a
    dangling reference yields ERR_NOT_FOUND."

    Design: Corner/entities/get_nonexistent_policy_returns_not_found
    """
    resp = api.get_policy(NON_EXISTENT_UUID, PA)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_application_missing_face_amount_validation(api):
    """PRD §3.2: "They then open an Application against a chosen plan, supplying
    the applicant_id, the product_plan_id, and the requested_face_amount_cents -
    the death benefit being applied for."

    Design: Corner/entities/create_application_missing_required_field_returns_validation
    """
    plan = create_plan(simple=True)
    applicant = create_applicant(full_name="A")
    resp = api.create_application({"applicant_id": applicant["id"], "product_plan_id": plan["id"]}, UW)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_new_policy_reports_zero_cash_value(api):
    """PRD §3.9: "it is the plan's cash_value_factor_per_1000_cents multiplied by
    the number of $1000 face units (face amount in cents divided by 100000)
    multiplied by the vested years, where vested years is the larger of zero and
    the whole policy-years in force minus cash_value_vesting_years."

    Design: Corner/entities/policy_computed_fields_ignored_on_issue
    """
    policy = issue_active_policy_only(simple=True, issue_clock="2026-02-01T00:00:00Z", policyholder_user_id="ph_cv")
    assert policy["gross_cash_value_cents"] == 0, policy["gross_cash_value_cents"]
    assert policy["net_cash_value_cents"] == 0, policy["net_cash_value_cents"]


def test_list_policies_filtered_by_applicant(api):
    """PRD §3.5: "Policies are readable individually and listable, filterable by
    application_id, product_plan_id, applicant_id, policyholder_user_id, or
    coverage_status."

    Design: Corner/entities/list_policies_filtered_by_applicant_fk
    """
    plan = create_plan(simple=True)
    applicant = create_applicant(full_name="Filt X")
    app = create_draft_application_with_questionnaire(plan["id"], applicant["id"], face_cents=1000000)
    set_clock("2026-02-01T00:00:00Z")
    submit_application(app["id"])
    policy = validate_success(api.issue_application(app["id"], {"policyholder_user_id": "ph_filt"}, PA), expected_status=201)

    data, meta = validate_paginated(api.list_policies(PA, params={"applicant_id": applicant["id"]}))
    assert meta["total_count"] == 1, meta
    assert len(data) == 1 and data[0]["id"] == policy["id"], data


# ===========================================================================
# Corner / endpoints
# ===========================================================================
def test_premium_payment_advances_paid_through_date(api):
    """PRD §3.6: "A successful post records status POSTED and a posted_date at the
    current clock, recomputes the policy's paid_through_date, due_date, and
    total_premiums_paid_cents, and appends a PREMIUM_POSTED ledger entry."

    Design: Corner/endpoints/premium_payment_advances_paid_through_date
    """
    policy = issue_active_policy_only(simple=True, issue_clock="2026-02-01T00:00:00Z", policyholder_user_id="ph_pt")
    validate_success(api.create_premium_payment({"policy_id": policy["id"], "amount_cents": 6000, "coverage_start": "2026-02-01T00:00:00Z", "coverage_end": "2026-03-01T00:00:00Z"}, PA), expected_status=201)

    fresh = validate_success(api.get_policy(policy["id"], PA))
    assert fresh["paid_through_date"].startswith("2026-03-01"), fresh["paid_through_date"]
    assert fresh["total_premiums_paid_cents"] == 6000, fresh["total_premiums_paid_cents"]


def test_ledger_entries_reverse_reachable_by_policy(api):
    """PRD §3.9: "increments the policy's version by one, recomputes the policy's
    outstanding_loan_balance_cents and net_cash_value_cents, and appends a
    LOAN_DISBURSED ledger entry."
    PRD §2.5: "Each entry records a signed amount_cents (credits positive, debits
    negative)"

    Design: Corner/endpoints/ledger_entries_reverse_reachable_by_policy
    """
    policy = issue_vested_policy(simple=True, issue_clock="2026-02-01T00:00:00Z", vested_clock="2031-02-01T00:00:00Z", policyholder_user_id="ph_le")
    disburse_loan(policy["id"], principal_cents=20000)

    data, meta = validate_paginated(api.list_ledger_entries(PA, params={"policy_id": policy["id"], "entry_type": "LOAN_DISBURSED"}))
    disbursed = [e for e in data if e["entry_type"] == "LOAN_DISBURSED"]
    assert disbursed, "a LOAN_DISBURSED ledger entry must exist after a loan"
    assert any(abs(e["amount_cents"]) == 20000 for e in disbursed), [e["amount_cents"] for e in disbursed]


# ===========================================================================
# Corner / rbac
# ===========================================================================
def test_policyholder_cannot_issue_application(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    ERR_FORBIDDEN_ROLE."

    Design: Corner/rbac/policyholder_cannot_issue_application
    """
    plan = create_plan(simple=True)
    applicant = create_applicant(full_name="Rb Ac")
    app = create_draft_application_with_questionnaire(plan["id"], applicant["id"], face_cents=1000000)
    set_clock("2026-02-01T00:00:00Z")
    submit_application(app["id"])

    resp = api.issue_application(app["id"], {"policyholder_user_id": "ph_rb"}, make_policyholder_headers("ph_rb"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_missing_auth_header_returns_401(api):
    """PRD §2.1: "A request missing or malformed in either header is rejected with
    ERR_MISSING_AUTH."

    Design: Corner/rbac/missing_auth_header_returns_401
    """
    resp = api.create_product_plan(create_simple_plan_payload(name="NoAuth"), {})
    validate_error(resp, ApiErrorId.ERR_MISSING_AUTH.value)


def test_policyholder_not_owner_cannot_take_loan(api):
    """PRD §2.1: "on any owner-scoped mutation performed under the Policyholder
    role - surrendering a policy, disbursing a loan, or repaying a loan - the
    server compares the caller's X-User-ID against the policy's stored
    policyholder_user_id; if they differ, the request is rejected with
    ERR_NOT_POLICY_OWNER."

    Design: Corner/rbac/policyholder_not_owner_cannot_take_loan
    """
    policy = issue_vested_policy(simple=True, issue_clock="2026-02-01T00:00:00Z", vested_clock="2031-02-01T00:00:00Z", policyholder_user_id="ph_owner")
    intruder = make_policyholder_headers("ph_intruder")

    resp = api.create_policy_loan({"policy_id": policy["id"], "expected_policy_version": policy["version"], "principal_cents": 5000}, intruder)
    validate_error(resp, ApiErrorId.ERR_NOT_POLICY_OWNER.value)


# ===========================================================================
# Corner / cross_cutting_complexity_layers / occ_stale_policy_version_loan_rejected
# ===========================================================================
def test_stale_policy_version_on_second_loan_rejected(api):
    """PRD §2.8: "If that value does not match the policy's current version -
    because some other writer has advanced the policy since the client last read
    it - the disbursement is rejected with ERR_STALE_POLICY_VERSION (HTTP 412)"
    PRD §2.8: "A successful disbursement increments the policy's version by one,
    so a second disbursement carrying the now-superseded version will itself be
    rejected until the client re-reads."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_policy_version_loan_rejected
    """
    policy = issue_vested_policy(simple=True, issue_clock="2026-02-01T00:00:00Z", vested_clock="2031-02-01T00:00:00Z", policyholder_user_id="ph_oc")
    stale_version = policy["version"]
    # First loan succeeds and bumps the policy version.
    validate_success(api.create_policy_loan({"policy_id": policy["id"], "expected_policy_version": stale_version, "principal_cents": 5000}, PA), expected_status=201)

    # Second loan still carrying the now-superseded version is rejected.
    resp = api.create_policy_loan({"policy_id": policy["id"], "expected_policy_version": stale_version, "principal_cents": 5000}, PA)
    validate_error(resp, ApiErrorId.ERR_STALE_POLICY_VERSION.value)
