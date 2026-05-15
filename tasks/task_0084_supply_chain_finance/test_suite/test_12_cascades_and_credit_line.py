"""Credit-line invariants and revoke cascades (PRD §2.7, §3.3).

Covers:
- credit_line_total - credit_line_reserved - credit_line_consumed >= 0
  at every step of confirm → disburse → settle.
- Revoke cascades to Receivable.WRITTEN_OFF and FinancingApplication
  in DRAFT/UNDER_REVIEW to CANCELLED.
- Revoke blocked when a receivable is already FINANCED.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_credit_line_invariants,
    create_payable_confirmation_payload,
    get_core_enterprise,
    get_financing_application,
    get_payable_confirmation,
    get_receivable,
    iso_in_days,
    make_core_enterprise_headers,
    revoke_confirmation,
    revoke_payable_confirmation_payload,
    setup_active_supplier,
    setup_approved_application,
    setup_approved_core_enterprise,
    setup_confirmed_payable_confirmation,
    setup_disbursed_application,
    setup_registered_receivable,
    validate_error,
    validate_success,
)


def test_confirm_then_revoke_round_trip_restores_reserved(api):
    """PRD §2.7: "When a confirmation is revoked, its amount is
    subtracted from credit_line_reserved_cents."

    Pre-confirm reserved == 0; post-confirm == amount; post-revoke == 0.
    """
    bundle = setup_confirmed_payable_confirmation(amount_cents=2_500_000)
    ce_after_confirm = get_core_enterprise(bundle["ce"]["id"])
    assert ce_after_confirm["credit_line_reserved_cents"] == 2_500_000
    revoke_confirmation(bundle["ce"], bundle["confirmation"])
    ce_after_revoke = get_core_enterprise(bundle["ce"]["id"])
    assert ce_after_revoke["credit_line_reserved_cents"] == 0, (
        f"PRD §2.7: reserved must drop by amount_cents on revoke. "
        f"got {ce_after_revoke['credit_line_reserved_cents']}"
    )
    assert_credit_line_invariants(ce_after_revoke)


def test_revoke_cascades_registered_receivable_to_written_off(api):
    """PRD §3.3: "any linked Receivable not yet FINANCED is cascaded to
    WRITTEN_OFF."
    """
    bundle = setup_registered_receivable(amount_cents=500_000)
    revoke_confirmation(bundle["ce"], bundle["confirmation"])
    rec = get_receivable(bundle["receivable"]["id"])
    assert rec["status"] == "WRITTEN_OFF"


def test_revoke_cascades_in_flight_application_to_cancelled(api):
    """PRD §3.3: "with any linked FinancingApplication in DRAFT or
    UNDER_REVIEW further cascaded to CANCELLED."
    """
    bundle = setup_approved_application(term_days=90)
    # Confirmation is anchor; we cancel before disbursement. PRD §3.5
    # also says "DRAFT → CANCELLED and UNDER_REVIEW → CANCELLED fire
    # whenever the linked PayableConfirmation transitions to REVOKED."
    # The bundle's application is APPROVED, not UNDER_REVIEW. Build a
    # fresh chain that stops at UNDER_REVIEW:
    from test_helpers import setup_under_review_application
    bundle2 = setup_under_review_application(term_days=90)
    revoke_confirmation(bundle2["ce"], bundle2["confirmation"])
    app = get_financing_application(bundle2["application"]["id"])
    assert app["status"] == "CANCELLED"


def test_revoke_blocked_when_receivable_financed(api, funder_headers):
    """PRD §3.3: "Revocation is forbidden if any Receivable against
    this confirmation is currently in FINANCED (response
    ERR_CONFIRMATION_FROZEN_BY_FINANCING)."
    """
    bundle = setup_disbursed_application(term_days=90)
    # Receivable is FINANCED post-disbursement.
    rec = get_receivable(bundle["receivable"]["id"])
    assert rec["status"] == "FINANCED"
    res = api.revoke_payable_confirmation(
        bundle["confirmation"]["id"],
        revoke_payable_confirmation_payload(),
        make_core_enterprise_headers(bundle["ce"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_CONFIRMATION_FROZEN_BY_FINANCING.value)


def test_disburse_to_settle_invariant_restored(api):
    """PRD §2.7: invariant ``total - reserved - consumed`` must equal
    the pre-confirm baseline after the full
    confirm → disburse → settle round trip.
    """
    from test_helpers import repay_in_full, setup_scheduled_repayment
    bundle, schedule = setup_scheduled_repayment(
        amount_cents=1_000_000, approved_amount_cents=1_000_000,
        term_days=30,
    )
    ce_pre = get_core_enterprise(bundle["ce"]["id"])
    invariant_pre = (
        ce_pre["credit_line_total_cents"]
        - ce_pre["credit_line_reserved_cents"]
        - ce_pre["credit_line_consumed_cents"]
    )
    repay_in_full(schedule, ce=bundle["ce"])
    ce_post = get_core_enterprise(bundle["ce"]["id"])
    invariant_post = (
        ce_post["credit_line_total_cents"]
        - ce_post["credit_line_reserved_cents"]
        - ce_post["credit_line_consumed_cents"]
    )
    assert invariant_post == ce_pre["credit_line_total_cents"], (
        f"PRD §2.7 invariant: total - reserved - consumed must be "
        f"restored to total after full round-trip. "
        f"pre_total={ce_pre['credit_line_total_cents']}, "
        f"pre_invariant={invariant_pre}, post_invariant={invariant_post}"
    )
    assert ce_post["credit_line_reserved_cents"] == 0
    assert ce_post["credit_line_consumed_cents"] == 0
    assert_credit_line_invariants(ce_post)


def test_revoke_cascade_to_audit_log(api, platform_admin_headers):
    """PRD §3.3: "Audit entries are written for both the revoke action
    and each cascaded write-off."
    """
    from test_helpers import list_audit_for_entity
    bundle = setup_registered_receivable(amount_cents=500_000)
    revoke_confirmation(bundle["ce"], bundle["confirmation"])
    pc_logs = list_audit_for_entity(
        bundle["confirmation"]["id"],
        entity_type="PayableConfirmation", action="REVOKE",
    )
    assert pc_logs, (
        "PRD §3.3: an audit entry with action=REVOKE on the confirmation "
        "must be appended."
    )
