"""Audit-event chain integrity — PRD §2.8, §2.11, §3.9.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    assert_audit_chain_links,
    assert_audit_event,
    criminal_raw_finding,
    get_success_data,
    setup_order_in_intake,
    setup_order_pre_adverse,
    setup_order_terminated_adverse,
    upsert_jurisdiction_policy,
    validate_success,
)


def _audit_events(api, order_id, headers):
    """Return the audit-trail list for an order."""
    resp = api.get_audit_trail(order_id, headers)
    body = resp.json()
    data = body.get("data", body)
    if isinstance(data, list):
        return data
    return data.get("items", [])


# ===========================================================================
# Audit trail read — PRD §3.9
# ===========================================================================
class TestAuditTrailRead:

    def test_audit_trail_contains_order_opened(
        self, api, recruiter_headers,
    ):
        """PRD §3.9: "Every order's audit chain is retrievable as an
        array of `AuditEvent` rows in chronological order. Each row
        carries the `event_type` (`CONSENT_RECORDED`, `CONSENT_REVOKED`,
        `ORDER_OPENED`, ...)".

        Claim: GET /fcra/orders/{id}/audit-trail after order open
        includes an event with event_type=ORDER_OPENED.
        """
        cand, cons, order = setup_order_in_intake(
            residence_jurisdiction="CA",
        )
        events = _audit_events(api, order["id"], recruiter_headers)
        assert len(events) > 0
        order_opened = [
            e for e in events if e.get("event_type") == "ORDER_OPENED"
        ]
        assert len(order_opened) >= 1, (
            f"Expected at least one ORDER_OPENED event, "
            f"got events={[e.get('event_type') for e in events]}"
        )

    def test_pre_adverse_event_appended(self, api, recruiter_headers):
        """PRD §3.6: "an `AuditEvent` of type `PRE_ADVERSE_SENT` is
        appended".

        Claim: after Pre-Adverse, audit-trail includes an event with
        event_type=PRE_ADVERSE_SENT.
        """
        cand, cons, order, items, flow = setup_order_pre_adverse(
            residence_jurisdiction="CA",
            jurisdiction_kwargs={"criminal_lookback_years": 7},
        )
        events = _audit_events(api, order["id"], recruiter_headers)
        types = [e.get("event_type") for e in events]
        assert "PRE_ADVERSE_SENT" in types, (
            f"Expected PRE_ADVERSE_SENT in audit trail, got {types}"
        )

    def test_final_adverse_event_appended(self, api, recruiter_headers):
        """PRD §3.8: "An `AuditEvent` of type `FINAL_ADVERSE_ISSUED` is
        appended".

        Claim: after Final Adverse, audit-trail includes an event with
        event_type=FINAL_ADVERSE_ISSUED.
        """
        cand, cons, order, items, flow = setup_order_terminated_adverse(
            residence_jurisdiction="CA",
            jurisdiction_kwargs={
                "criminal_lookback_years": 7,
                "adverse_action_waiting_business_days": 5,
            },
        )
        events = _audit_events(api, order["id"], recruiter_headers)
        types = [e.get("event_type") for e in events]
        assert "FINAL_ADVERSE_ISSUED" in types, (
            f"Expected FINAL_ADVERSE_ISSUED in audit trail, got {types}"
        )


# ===========================================================================
# AuditEvent shape — PRD §2.11
# ===========================================================================
class TestAuditEventShape:

    def test_event_carries_required_fields(self, api, recruiter_headers):
        """PRD §2.11: "each `AuditEvent` records the acting
        `actor_role`, the acting `actor_user_id`, the subject entity
        through `subject_entity` and `subject_id`, the `event_type`,
        the `previous_event_id` linking back to the prior event for
        that subject, and a `payload_hash` that is a SHA-256 over the
        concatenation of `subject_id`, `event_type`, `actor_user_id`,
        `created_at`, and `previous_event_id`."

        Claim: every event row carries the required fields and
        payload_hash is a 64-char lowercase hex string.
        """
        cand, cons, order = setup_order_in_intake(
            residence_jurisdiction="CA",
        )
        events = _audit_events(api, order["id"], recruiter_headers)
        assert len(events) > 0
        for e in events:
            assert_audit_event(e)


# ===========================================================================
# Audit chain integrity — PRD §2.8
# ===========================================================================
class TestAuditChainIntegrity:

    def test_first_event_per_subject_has_null_previous(
        self, api, recruiter_headers,
    ):
        """PRD §2.8: "The first event for any subject has
        `previous_event_id` of NULL; every subsequent event must
        reference the latest prior event for the subject".

        Claim: for each subject_id, the chronologically-first event
        has previous_event_id == None and subsequent events link via
        previous_event_id to the prior event's id.
        """
        cand, cons, order, items, flow = setup_order_pre_adverse(
            residence_jurisdiction="CA",
            jurisdiction_kwargs={"criminal_lookback_years": 7},
        )
        events = _audit_events(api, order["id"], recruiter_headers)
        # Re-arrange by subject_id and check the linked-list property.
        assert_audit_chain_links(events)
