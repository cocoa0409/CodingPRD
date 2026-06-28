"""Approval preconditions, validation-priority pairs, cross-entity dependencies,
and lifetime/funding/account guards.

Difficulty queue A: priority_pair_validation_conflict, cross_entity_state_dependency.
Corner queue B: validations (lifetime, unverified-account).
"""
from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    fixtures,
    ApiErrorId,
    factories,
)

_ADMIN = TEST_USERS["benefits_admin_headers"]
_ADJUSTER = TEST_USERS["claims_adjuster_headers"]


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict / approve_fiscal_beats_funding_on_dual_failure
# ---------------------------------------------------------------------------
def test_approve_dual_failure_reports_benefit_exhausted_before_funding(api):
    """PRD §2.10: "the lifetime-occurrence rule (`ERR_LIFETIME_MAX_REACHED`,
    priority 10), the annual-cap rule (`ERR_BENEFIT_EXHAUSTED`, priority 11), the
    funding rule (`ERR_ENROLLMENT_NOT_FUNDED`, priority 12)" ... "Lower priority
    numbers are evaluated first; the first failing check determines the response."

    Design: Difficulty/priority_pair_validation_conflict/approve_fiscal_beats_funding_on_dual_failure
    """
    emp, prod, period, employee, enr, acct, items = (
        fixtures.setup_funded_enrollment_with_account(
            schedule_items=[
                {"event_code": "HEART", "flat_benefit_cents": 300000},
                {"event_code": "BIGEVENT", "flat_benefit_cents": 500000},
            ]
        )
    )
    # Exhaust the cap (remaining 0) with one approved BIGEVENT(500000).
    fixtures.file_review_approve_claim(
        enr["id"], acct["id"], "BIGEVENT", "2026-03-20T00:00:00Z"
    )
    # Now lapse funding (3 consecutive FAILED starting index 1).
    fixtures.lapse_enrollment(enr["id"], start_index=1)
    # File HEART and move UNDER_REVIEW; both cap (11) and funding (12) fail.
    claim = fixtures.file_and_review_claim(
        enr["id"], acct["id"], "HEART", "2026-03-21T00:00:00Z"
    )
    validate_error(
        api.approve_claim(claim["id"], _ADJUSTER),
        ApiErrorId.ERR_BENEFIT_EXHAUSTED,
    )


def test_approve_dual_failure_leaves_enrollment_state_intact(api):
    """PRD §2.10: "the annual-cap rule (`ERR_BENEFIT_EXHAUSTED`, priority 11), the
    funding rule (`ERR_ENROLLMENT_NOT_FUNDED`, priority 12)"

    Design: Difficulty/priority_pair_validation_conflict/approve_fiscal_beats_funding_on_dual_failure
    """
    emp, prod, period, employee, enr, acct, items = (
        fixtures.setup_funded_enrollment_with_account(
            schedule_items=[
                {"event_code": "HEART", "flat_benefit_cents": 300000},
                {"event_code": "BIGEVENT", "flat_benefit_cents": 500000},
            ]
        )
    )
    fixtures.file_review_approve_claim(
        enr["id"], acct["id"], "BIGEVENT", "2026-03-20T00:00:00Z"
    )
    fixtures.lapse_enrollment(enr["id"], start_index=1)
    claim = fixtures.file_and_review_claim(
        enr["id"], acct["id"], "HEART", "2026-03-21T00:00:00Z"
    )
    api.approve_claim(claim["id"], _ADJUSTER)
    data = validate_success(api.get_enrollment(enr["id"], _ADMIN))
    assert data["benefit_remaining_cents"] == 0
    assert data["funding_status"] == "LAPSED"


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict / claim_temporal_beats_coverage_event
# ---------------------------------------------------------------------------
def test_claim_temporal_beats_coverage_on_dual_failure(api):
    """PRD §2.10: "the claim temporal-coverage rule (`ERR_EVENT_BEFORE_COVERAGE`,
    priority 7), the covered-event rule (`ERR_EVENT_NOT_COVERED`, priority 8)"
    ... "Lower priority numbers are evaluated first; the first failing check
    determines the response."

    Design: Difficulty/priority_pair_validation_conflict/claim_temporal_beats_coverage_event_on_dual_failure
    """
    emp, prod, period, employee, enr, items = fixtures.create_active_enrollment()
    acct = fixtures.create_verified_account(employee["id"])
    # event_code UNLISTED is not on schedule AND event_date precedes coverage.
    payload = factories.create_claim_payload(
        enr["id"], acct["id"], "UNLISTED", "2026-03-01T00:00:00Z"
    )
    validate_error(
        api.create_claim(payload, _ADMIN),
        ApiErrorId.ERR_EVENT_BEFORE_COVERAGE,
    )


def test_claim_event_before_coverage_alone_rejected(api):
    """PRD §3.8: "The `event_date` must fall on or after the enrollment's
    `enrolled_at` and the enrollment must be `ACTIVE` at filing time, or the
    claim is rejected with `ERR_EVENT_BEFORE_COVERAGE`."

    Design: Difficulty/priority_pair_validation_conflict/claim_temporal_beats_coverage_event_on_dual_failure
    """
    emp, prod, period, employee, enr, items = fixtures.create_active_enrollment(
        schedule_items=[{"event_code": "FRACTURE", "flat_benefit_cents": 200000}]
    )
    acct = fixtures.create_verified_account(employee["id"])
    # FRACTURE IS covered, so only the temporal rule fails.
    payload = factories.create_claim_payload(
        enr["id"], acct["id"], "FRACTURE", "2026-03-01T00:00:00Z"
    )
    validate_error(
        api.create_claim(payload, _ADMIN),
        ApiErrorId.ERR_EVENT_BEFORE_COVERAGE,
    )


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / claim_approve_requires_enrollment_funded
# ---------------------------------------------------------------------------
def test_approve_rejected_when_enrollment_unfunded(api):
    """PRD §3.8: "The enrollment's `funding_status` must be `CURRENT`, or approval
    is rejected with `ERR_ENROLLMENT_NOT_FUNDED`."

    Design: Difficulty/cross_entity_state_dependency/claim_approve_requires_enrollment_funded
    """
    # ACTIVE but never funded (no POSTED deduction).
    emp, prod, period, employee, enr, items = fixtures.create_active_enrollment(
        schedule_items=[{"event_code": "FRACTURE", "flat_benefit_cents": 200000}]
    )
    acct = fixtures.create_verified_account(employee["id"])
    claim = fixtures.file_and_review_claim(
        enr["id"], acct["id"], "FRACTURE", "2026-03-20T00:00:00Z"
    )
    validate_error(
        api.approve_claim(claim["id"], _ADJUSTER),
        ApiErrorId.ERR_ENROLLMENT_NOT_FUNDED,
    )


def test_approve_unfunded_leaves_claim_under_review(api):
    """PRD §3.8: "The enrollment's `funding_status` must be `CURRENT`, or approval
    is rejected with `ERR_ENROLLMENT_NOT_FUNDED`."

    Design: Difficulty/cross_entity_state_dependency/claim_approve_requires_enrollment_funded
    """
    emp, prod, period, employee, enr, items = fixtures.create_active_enrollment(
        schedule_items=[{"event_code": "FRACTURE", "flat_benefit_cents": 200000}]
    )
    acct = fixtures.create_verified_account(employee["id"])
    claim = fixtures.file_and_review_claim(
        enr["id"], acct["id"], "FRACTURE", "2026-03-20T00:00:00Z"
    )
    api.approve_claim(claim["id"], _ADJUSTER)
    cdata = validate_success(api.get_claim(claim["id"], _ADMIN))
    assert cdata["status"] == "UNDER_REVIEW"
    edata = validate_success(api.get_enrollment(enr["id"], _ADMIN))
    assert edata["funding_status"] == "UNFUNDED"


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / enrollment_activate_requires_product_open
# ---------------------------------------------------------------------------
def test_activate_rejected_when_product_not_open(api):
    """PRD §3.6: "the product must be `OPEN` (otherwise `ERR_PRODUCT_NOT_OPEN`)"

    Design: Difficulty/cross_entity_state_dependency/enrollment_activate_requires_product_open
    """
    emp, prod, period, employee, enr, items = fixtures.create_pending_enrollment(
        schedule_items=[{"event_code": "FRACTURE", "flat_benefit_cents": 200000}]
    )
    # Close the product after the (PENDING) enrollment exists.
    fixtures.api_client.close_plan_product(prod["id"], _ADMIN)
    validate_error(
        api.activate_enrollment(enr["id"], _ADMIN),
        ApiErrorId.ERR_PRODUCT_NOT_OPEN,
    )


def test_activate_rejected_when_product_not_open_keeps_pending(api):
    """PRD §3.6: "Activation moves `lifecycle_status` from `PENDING` to `ACTIVE`
    and is allowed only when the enrollment is `PENDING`; the product must be
    `OPEN` (otherwise `ERR_PRODUCT_NOT_OPEN`)"

    Design: Difficulty/cross_entity_state_dependency/enrollment_activate_requires_product_open
    """
    emp, prod, period, employee, enr, items = fixtures.create_pending_enrollment(
        schedule_items=[{"event_code": "FRACTURE", "flat_benefit_cents": 200000}]
    )
    fixtures.api_client.close_plan_product(prod["id"], _ADMIN)
    api.activate_enrollment(enr["id"], _ADMIN)
    data = validate_success(api.get_enrollment(enr["id"], _ADMIN))
    assert data["lifecycle_status"] == "PENDING"


# ---------------------------------------------------------------------------
# Corner: validations / lifetime_max_reached_on_third_fracture
# ---------------------------------------------------------------------------
def test_lifetime_max_reached_on_third_occurrence(api):
    """PRD §3.8: "for a schedule line whose `lifetime_max_occurrences` is greater
    than 0, the system counts the prior claims on this enrollment for the same
    `event_code` whose `status` is `APPROVED` or `PAID`; if that count is already
    at or above `lifetime_max_occurrences`, approval is rejected with
    `ERR_LIFETIME_MAX_REACHED`."

    Design: Corner/validations/lifetime_max_reached_on_third_fracture
    """
    emp, prod, period, employee, enr, acct, items = (
        fixtures.setup_funded_enrollment_with_account(
            schedule_items=[
                {"event_code": "FRACTURE", "flat_benefit_cents": 200000,
                 "lifetime_max_occurrences": 2},
            ]
        )
    )
    fixtures.file_approve_disburse_claim(
        enr["id"], acct["id"], "FRACTURE", "2026-03-20T00:00:00Z"
    )
    fixtures.file_approve_disburse_claim(
        enr["id"], acct["id"], "FRACTURE", "2026-03-21T00:00:00Z"
    )
    third = fixtures.file_and_review_claim(
        enr["id"], acct["id"], "FRACTURE", "2026-03-22T00:00:00Z"
    )
    validate_error(
        api.approve_claim(third["id"], _ADJUSTER),
        ApiErrorId.ERR_LIFETIME_MAX_REACHED,
    )
    edata = validate_success(api.get_enrollment(enr["id"], _ADMIN))
    assert edata["benefit_paid_cents"] == 400000


# ---------------------------------------------------------------------------
# Corner: validations / disburse_to_unverified_account_rejected
# ---------------------------------------------------------------------------
def test_disburse_to_unverified_account_rejected(api):
    """PRD §3.9: "Disbursing requires the claim to be `APPROVED` and the target
    `DisbursementAccount` to be `VERIFIED`; disbursing to an unverified account is
    rejected with `ERR_ACCOUNT_NOT_VERIFIED`."

    Design: Corner/validations/disburse_to_unverified_account_rejected
    """
    emp, prod, period, employee, enr, items = fixtures.create_funded_enrollment(
        schedule_items=[{"event_code": "FRACTURE", "flat_benefit_cents": 200000}]
    )
    acct = fixtures.create_unverified_account(employee["id"])
    claim = fixtures.file_review_approve_claim(
        enr["id"], acct["id"], "FRACTURE", "2026-03-20T00:00:00Z"
    )
    validate_error(
        api.disburse_claim(claim["id"], _ADJUSTER),
        ApiErrorId.ERR_ACCOUNT_NOT_VERIFIED,
    )
    cdata = validate_success(api.get_claim(claim["id"], _ADMIN))
    assert cdata["status"] == "APPROVED"
