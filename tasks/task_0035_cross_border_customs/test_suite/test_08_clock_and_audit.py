"""Test-driving clock advance, payment-notice expiry, audit-event listing.

PRD anchors: §2.7 (audit), §3.8 (notice expiry), §3.11 (clock & external
sync).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    TEST_USERS,
    PAYMENT_NOTICE_DUE_SECONDS,
    setup_approved_declaration,
    setup_released_declaration,
    confirm_payment_payload,
    fresh_idempotency_key,
    find_audit_events,
    assert_audit_event,
    emit_event_payload,
)


# ---------------------------------------------------------------------------
# Clock advance triggers PaymentNotice expiry
# ---------------------------------------------------------------------------
def test_clock_advance_past_due_at_expires_pending_notice(api):
    """PRD §3.8: "The system also auto-expires PENDING notices when the
    clock advances past their due_at: every time the test-driving
    clock-advance capability moves the system clock forward, any notice
    whose due_at has now passed transitions from PENDING to EXPIRED."

    Claim: advance the clock past due_at (168h + buffer); the notice's
    status changes to EXPIRED.
    """
    ctx = setup_approved_declaration()
    notice_id = ctx.payment_notice["id"]
    res_clock = api.advance_clock(
        PAYMENT_NOTICE_DUE_SECONDS + 60,
        TEST_USERS["customs_officer_headers"],
    )
    validate_success(res_clock)
    res = api.get_payment_notice(
        notice_id, TEST_USERS["finance_officer_headers"]
    )
    notice = validate_success(res)
    assert notice["status"] == "EXPIRED"


def test_confirm_after_expiry_rejected(api):
    """PRD §3.8: "A confirmation that arrives after the notice's due_at
    is rejected with ERR_PAYMENT_NOTICE_EXPIRED; the comparison is
    against the current clock at request time, with due_at exclusive —
    that is, a notice at exactly due_at is already expired."

    Claim: after clock advance past due_at, confirm_payment is rejected.

    Note on error precedence: PRD §3.8 names ERR_PAYMENT_NOTICE_EXPIRED
    for the temporal violation, but PRD §3.8 also says the clock-advance
    capability auto-flips PENDING notices to EXPIRED — so the confirm
    arrives against an EXPIRED-state notice. PRD §2.9 then declares
    state-transition validity precedes business-temporal checks, which
    would surface ERR_INVALID_STATE_TRANSITION instead. The PRD names a
    member of the set without uniquely pinning which one applies, so
    per the bench's relaxation rule we accept either.
    """
    ctx = setup_approved_declaration()
    api.advance_clock(
        PAYMENT_NOTICE_DUE_SECONDS + 60,
        TEST_USERS["customs_officer_headers"],
    )
    key = fresh_idempotency_key("ex")
    hdrs = dict(TEST_USERS["finance_officer_headers"])
    hdrs["Idempotency-Key"] = key
    body = confirm_payment_payload(
        payment_channel="ELECTRONIC_PAYMENT", idempotency_key=key,
    )
    res = api.confirm_payment(ctx.payment_notice["id"], body, hdrs)
    assert res.status_code == 409
    validate_error_is_one_of(
        res,
        ["ERR_PAYMENT_NOTICE_EXPIRED", "ERR_INVALID_STATE_TRANSITION"],
    )


# ---------------------------------------------------------------------------
# Audit-event listing & filtering
# ---------------------------------------------------------------------------
def test_audit_events_filtering_by_subject_id(api, customs_officer_headers):
    """PRD §3.11: "A subject_type?, subject_id?, or event_type? filter
    narrows the listing; the audit-event listing also accepts limit?
    and offset? for pagination per §2.3."

    Claim: filtering by subject_id returns only events for that subject.
    """
    ctx = setup_released_declaration()
    res = api.list_audit_events(
        customs_officer_headers,
        params={"subject_type": "DECLARATION",
                "subject_id": ctx.declaration["id"]},
    )
    data, meta = validate_paginated(res)
    for ev in data:
        assert_audit_event(ev)
        assert ev["subject_type"] == "DECLARATION"
        assert ev["subject_id"] == ctx.declaration["id"]


def test_audit_events_record_status_change(api, customs_officer_headers):
    """PRD §2.7: "the system writes AuditEvent rows for declaration
    status changes, declaration field changes, tax recomputations,
    payment confirmations and reversals, refund decisions, and
    external-system synchronization pushes."
    PRD §2.7: "Audit events are append-only; they are never updated or
    deleted, and the catalogue of event_type values is exactly
    DECLARATION_FIELD_CHANGE, DECLARATION_STATUS_CHANGE, TAX_RECOMPUTED,
    PAYMENT_CONFIRMED, REFUND_DECISION, and EXTERNAL_SYNC."

    Claim: the released declaration has at least one
    DECLARATION_STATUS_CHANGE event.
    """
    ctx = setup_released_declaration()
    res = api.list_audit_events(
        customs_officer_headers,
        params={"subject_type": "DECLARATION",
                "subject_id": ctx.declaration["id"], "limit": 100},
    )
    data, _meta = validate_paginated(res)
    matches = find_audit_events(
        data, event_type="DECLARATION_STATUS_CHANGE"
    )
    assert len(matches) >= 1


def test_audit_events_carry_actor_role(api, customs_officer_headers):
    """PRD §2.7: "Every audit event carries the actor_role and actor_id
    from the originating request, the subject_type ..., the subject_id,
    the event_type, and before_value and after_value JSON snapshots of
    the changed fields."

    Claim: every audit event in the listing carries actor_role and
    actor_id as strings.
    """
    ctx = setup_released_declaration()
    res = api.list_audit_events(
        customs_officer_headers,
        params={"subject_type": "DECLARATION",
                "subject_id": ctx.declaration["id"], "limit": 100},
    )
    data, _meta = validate_paginated(res)
    assert len(data) >= 1
    for ev in data:
        assert isinstance(ev.get("actor_role"), str)
        assert isinstance(ev.get("actor_id"), str)


# ---------------------------------------------------------------------------
# Synthetic event emission (PRD §3.11)
# ---------------------------------------------------------------------------
def test_emit_synthetic_external_sync_event(api, customs_officer_headers):
    """PRD §3.11: "The synthetic-event capability is also
    CustomsOfficer-only and lets a test simulate one of four counterparty
    pushes — 'CUSTOMS_SINGLE_WINDOW_ACK', 'PAYMENT_GATEWAY_PUSH',
    'LOGISTICS_PICKUP_ACK', or 'ERP_ORDER_UPDATE' — against a given
    subject_id, emitting a corresponding EXTERNAL_SYNC audit event that
    downstream tests can verify."
    """
    ctx = setup_released_declaration()
    res = api.emit_event(
        emit_event_payload("LOGISTICS_PICKUP_ACK", ctx.declaration["id"]),
        customs_officer_headers,
    )
    validate_success(res)
    # Verify the event landed in the audit log.
    audit_res = api.list_audit_events(
        customs_officer_headers,
        params={"event_type": "EXTERNAL_SYNC",
                "subject_id": ctx.declaration["id"], "limit": 100},
    )
    data, _meta = validate_paginated(audit_res)
    matches = find_audit_events(data, event_type="EXTERNAL_SYNC")
    assert len(matches) >= 1
