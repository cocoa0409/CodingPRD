"""CoreEnterprise onboarding, approval, suspension (PRD §3.1).

State transitions: PENDING → APPROVED, PENDING → REJECTED,
APPROVED → SUSPENDED, SUSPENDED → APPROVED.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    approve_core_enterprise_payload,
    assert_core_enterprise,
    assert_credit_line_invariants,
    create_core_enterprise_payload,
    register_core_enterprise,
    setup_approved_core_enterprise,
    suspend_core_enterprise_payload,
    validate_error,
    validate_success,
)


def test_onboard_core_enterprise_starts_in_pending_with_zero_counters(
    api, credit_officer_headers,
):
    """PRD §3.1: "The new resource is created with onboarding_status of
    PENDING, credit_line_total_cents of zero, credit_line_reserved_cents
    of zero, and credit_line_consumed_cents of zero."
    """
    res = api.create_core_enterprise(create_core_enterprise_payload(),
                                     credit_officer_headers)
    ce = validate_success(res, expected_status=201)
    assert_core_enterprise(ce)
    assert ce["onboarding_status"] == "PENDING"
    assert ce["credit_line_total_cents"] == 0
    assert ce["credit_line_reserved_cents"] == 0
    assert ce["credit_line_consumed_cents"] == 0
    assert ce["version"] == 1


def test_onboard_with_default_joint_liability_flag_true(
    api, credit_officer_headers,
):
    """PRD §3.1: "optionally joint_liability_flag (defaulting to true)."
    Omit the field on creation and assert the default."""
    payload = create_core_enterprise_payload()
    payload.pop("joint_liability_flag", None)
    res = api.create_core_enterprise(payload, credit_officer_headers)
    ce = validate_success(res, expected_status=201)
    assert ce["joint_liability_flag"] is True


def test_onboard_with_default_risk_rating_bbb(
    api, credit_officer_headers,
):
    """PRD §3.1: "optionally risk_rating (one of AAA, AA, A, BBB, BB,
    defaulting to BBB)."
    """
    payload = create_core_enterprise_payload()
    payload.pop("risk_rating", None)
    res = api.create_core_enterprise(payload, credit_officer_headers)
    ce = validate_success(res, expected_status=201)
    assert ce["risk_rating"] == "BBB"


def test_approve_core_enterprise_sets_credit_line(
    api, credit_officer_headers,
):
    """PRD §3.1: "Approval requires credit_line_total_cents in the
    request body to be an integer strictly greater than zero and
    requires the current onboarding_status to be PENDING; on success
    the approved limit is written, the two utilisation counters remain
    at zero."
    """
    ce = register_core_enterprise()
    res = api.approve_core_enterprise(
        ce["id"],
        approve_core_enterprise_payload(credit_line_total_cents=5_000_000),
        credit_officer_headers,
    )
    approved = validate_success(res)
    assert approved["onboarding_status"] == "APPROVED"
    assert approved["credit_line_total_cents"] == 5_000_000
    assert approved["credit_line_reserved_cents"] == 0
    assert approved["credit_line_consumed_cents"] == 0
    assert_credit_line_invariants(approved)


def test_approve_rejects_zero_or_negative_credit_line(
    api, credit_officer_headers,
):
    """PRD §3.1: "Approval requires credit_line_total_cents in the
    request body to be an integer strictly greater than zero."
    """
    ce = register_core_enterprise()
    res = api.approve_core_enterprise(
        ce["id"],
        approve_core_enterprise_payload(credit_line_total_cents=0),
        credit_officer_headers,
    )
    validate_error(res, ApiErrorId.ERR_AMOUNT_NON_POSITIVE.value)


def test_approve_rejects_already_approved(
    api, credit_officer_headers,
):
    """PRD §3.1: "requires the current onboarding_status to be
    PENDING."
    """
    ce = setup_approved_core_enterprise()
    res = api.approve_core_enterprise(
        ce["id"],
        approve_core_enterprise_payload(credit_line_total_cents=1_000_000),
        credit_officer_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_reject_from_pending(api, credit_officer_headers):
    """PRD §3.1: "The status transitions are PENDING → APPROVED, PENDING
    → REJECTED, APPROVED → SUSPENDED, and SUSPENDED → APPROVED."
    """
    ce = register_core_enterprise()
    res = api.reject_core_enterprise(ce["id"], credit_officer_headers)
    rejected = validate_success(res)
    assert rejected["onboarding_status"] == "REJECTED"


def test_suspend_approved_core_enterprise(
    api, compliance_officer_headers,
):
    """PRD §3.1: "A ComplianceOfficer can suspend a core enterprise that
    is currently APPROVED; the suspend request carries a reason
    string."
    """
    ce = setup_approved_core_enterprise()
    res = api.suspend_core_enterprise(
        ce["id"], suspend_core_enterprise_payload(),
        compliance_officer_headers,
    )
    suspended = validate_success(res)
    assert suspended["onboarding_status"] == "SUSPENDED"


def test_reinstate_suspended_core_enterprise(
    api, compliance_officer_headers,
):
    """PRD §3.1: "Reinstatement by a compliance officer returns the
    enterprise from SUSPENDED to APPROVED and lifts the upload block."
    """
    ce = setup_approved_core_enterprise()
    susp_res = api.suspend_core_enterprise(
        ce["id"], suspend_core_enterprise_payload(),
        compliance_officer_headers,
    )
    validate_success(susp_res)
    reinstated_res = api.reinstate_core_enterprise(
        ce["id"], compliance_officer_headers,
    )
    reinstated = validate_success(reinstated_res)
    assert reinstated["onboarding_status"] == "APPROVED"


def test_suspend_from_pending_is_invalid_state(
    api, compliance_officer_headers,
):
    """PRD §3.1: suspend requires APPROVED → SUSPENDED — a PENDING
    record cannot be suspended directly (the only outbound transitions
    from PENDING are APPROVED and REJECTED per PRD §3.1).
    """
    ce = register_core_enterprise()
    res = api.suspend_core_enterprise(
        ce["id"], suspend_core_enterprise_payload(),
        compliance_officer_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
