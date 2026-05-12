"""Cross-entity cascades, archival, and posture frozen gating.

PRD §2.8, §2.9, §3.1.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    DEFAULT_NOW,
    add_days,
    add_minutes,
    advance_clock,
    api_client,
    create_time_entry_payload,
    log_time_entry,
    setup_closed_case,
    setup_three_lawyers_and_active_case,
    setup_paid_case,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# AWAITING_SETTLEMENT: locks SIGNED_OFF drafts
# ---------------------------------------------------------------------------
def test_await_settlement_locks_signed_off_drafts(api):
    """PRD §2.9: 'When a case transitions from ACTIVE to
    AWAITING_SETTLEMENT, every DocumentDraft on the case whose status is
    SIGNED_OFF is moved to LOCKED.'
    """
    from test_helpers import setup_three_lawyers_and_active_case, register_template, create_draft, get_success_data
    bundle = setup_three_lawyers_and_active_case()
    template = register_template(
        case_type="CIVIL", partner_headers=bundle["partner_headers"]
    )
    draft = create_draft(
        case_id=bundle["case"]["id"], template_id=template["id"],
        drafter_lawyer_id=bundle["junior"]["id"],
        actor_headers=bundle["junior_headers"],
    )
    get_success_data(api.submit_draft_for_review(
        draft["id"], bundle["junior_headers"]
    ))
    get_success_data(api.senior_pass(
        draft["id"], bundle["senior_headers"]
    ))
    get_success_data(api.submit_draft_for_review(
        draft["id"], bundle["junior_headers"]
    ))
    signed = get_success_data(api.partner_signoff(
        draft["id"], bundle["partner_headers"]
    ))
    assert signed["status"] == "SIGNED_OFF"
    awaiting = validate_success(
        api.await_settlement(bundle["case"]["id"],
                             bundle["partner_headers"]), 200,
    )
    assert awaiting["status"] == "AWAITING_SETTLEMENT"
    after = validate_success(
        api.get_draft(draft["id"], bundle["partner_headers"]), 200,
    )
    assert after["status"] == "LOCKED"


# ---------------------------------------------------------------------------
# CLOSE: stamps closed_at and computes settlement_total
# ---------------------------------------------------------------------------
def test_close_stamps_closed_at_and_computes_settlement(api):
    """PRD §3.1: 'closing stamps closed_at, computes settlement_total_cents
    chronologically (see §3.6), retires every non-terminal draft, and
    dismisses every open rebuttal.'
    """
    bundle = setup_closed_case()
    closed = bundle["case"]
    assert closed["status"] == "CLOSED"
    assert closed["closed_at"] is not None
    assert closed["settlement_total_cents"] is not None


# ---------------------------------------------------------------------------
# ARCHIVE: 30 days after CLOSED
# ---------------------------------------------------------------------------
def test_archive_after_30_days_via_clock_advance(api):
    """PRD §2.9: 'After a case has been closed for at least 30 days —
    measured against the server's logical clock, which advances either
    by real time or by the test-driving capability — the case is
    auto-transitioned to ARCHIVED.'
    """
    bundle = setup_closed_case()
    closed_at = bundle["case"]["closed_at"]
    advance_clock(add_days(closed_at, 31))
    after = validate_success(
        api.get_case(bundle["case"]["id"], bundle["partner_headers"]), 200,
    )
    assert after["status"] == "ARCHIVED"


def test_archived_case_rejects_mutations(api):
    """PRD §2.9: 'Once a case is ARCHIVED, every mutation against the case
    or any of its sub-resources is rejected with ERR_CASE_ARCHIVED,
    regardless of the immediate sub-resource's own state.'
    """
    bundle = setup_closed_case()
    closed_at = bundle["case"]["closed_at"]
    advance_clock(add_days(closed_at, 31))
    # Try to create a time entry (mutation against a Case-scoped sub-resource).
    payload = create_time_entry_payload(
        lawyer_id=bundle["partner"]["id"], minutes=30,
    )
    res = api.create_time_entry(
        bundle["case"]["id"], payload, bundle["partner_headers"]
    )
    validate_error(res, "ERR_CASE_ARCHIVED", expected_status=409)


# ---------------------------------------------------------------------------
# Posture FROZEN gates new sub-resources
# ---------------------------------------------------------------------------
def test_frozen_posture_rejects_time_entry_creation(api):
    """PRD §2.8: 'A FROZEN posture forbids creating new TimeEntry,
    Evidence, Hearing, or DocumentDraft rows on the case, and any such
    attempt is rejected with ERR_CASE_POSTURE_FROZEN.'
    """
    bundle = setup_three_lawyers_and_active_case()
    # Place the case ON_HOLD so posture cascades to FROZEN.
    held = validate_success(
        api.hold_case(bundle["case"]["id"], bundle["partner_headers"]), 200,
    )
    assert held["status"] == "ON_HOLD"
    # PRD §2.8: ON_HOLD with no rebutted evidence and no imminent hearing
    # → posture FROZEN.
    assert held["posture"] == "FROZEN"
    payload = create_time_entry_payload(
        lawyer_id=bundle["partner"]["id"], minutes=30,
    )
    res = api.create_time_entry(
        bundle["case"]["id"], payload, bundle["partner_headers"]
    )
    validate_error(res, "ERR_CASE_POSTURE_FROZEN", expected_status=409)
