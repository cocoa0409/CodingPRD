"""External event payloads (signature, court-filing) and audit log access.

PRD §3.7, §2.10, §4.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    api_client,
    court_filing_event_payload,
    setup_draft_locked,
    setup_submitted_evidence,
    signature_event_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Document signature event (priority 22)
# ---------------------------------------------------------------------------
def test_signature_event_invalid_kind_rejected(api, system_integrator_headers):
    """PRD §3.7: 'A document signature event (carrying draft_id,
    signature_kind, and external_signature_id) records that an external
    signature service has signed a SIGNED_OFF or LOCKED draft;
    signature_kind must be one of DRAFT_LOCKED or BILL_ISSUED, and a
    payload missing a required field or carrying an invalid
    signature_kind is rejected with ERR_EVENT_PAYLOAD_INVALID.'
    """
    bundle = setup_draft_locked()
    payload = signature_event_payload(
        draft_id=bundle["draft"]["id"], signature_kind="WRONG_KIND",
    )
    res = api.emit_signature(payload, system_integrator_headers)
    validate_error(res, "ERR_EVENT_PAYLOAD_INVALID",
                   expected_status=422)


def test_signature_event_locked_draft_succeeds(api, system_integrator_headers):
    """PRD §3.7: 'records that an external signature service has signed
    a SIGNED_OFF or LOCKED draft.'
    """
    bundle = setup_draft_locked()
    payload = signature_event_payload(
        draft_id=bundle["draft"]["id"], signature_kind="DRAFT_LOCKED",
    )
    res = api.emit_signature(payload, system_integrator_headers)
    # PRD §4 returns HTTP 200 for these events.
    validate_success(res, 200)


# ---------------------------------------------------------------------------
# Court filing event
# ---------------------------------------------------------------------------
def test_court_filing_event_for_submitted_evidence(api, system_integrator_headers):
    """PRD §3.7: 'A court-filing event (carrying evidence_id and
    court_filing_id) records that the court has acknowledged an evidence
    submission. The signature and court-filing events both produce audit
    log rows but do not themselves move state machines.'
    """
    bundle = setup_submitted_evidence()
    payload = court_filing_event_payload(
        evidence_id=bundle["evidence"]["id"]
    )
    res = api.emit_court_filing(payload, system_integrator_headers)
    validate_success(res, 200)


# ---------------------------------------------------------------------------
# Audit log: partner-only access
# ---------------------------------------------------------------------------
def test_non_partner_cannot_read_audit_log(api, intake_clerk_headers):
    """PRD §2.10: 'The audit log is append-only and queryable only by a
    partner.' Combined with §2.1: 'When the headers are present but the
    supplied role is not authorized for the requested endpoint per the
    matrix in §4, the request is rejected with ERR_FORBIDDEN.'
    """
    res = api.list_audit_logs(intake_clerk_headers)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_partner_can_read_audit_log(api):
    """PRD §2.10: 'The audit log is append-only and queryable only by a
    partner.' Combined with §2.10's audited mutations list, the audit
    log produced by a draft creation should be readable by a partner.
    """
    bundle = setup_draft_locked()
    data, meta = validate_paginated(api.list_audit_logs(
        bundle["partner_headers"]
    ))
    # PRD §2.10 names the audited subjects: DOCUMENT_DRAFT is one. We
    # don't pin a specific audit row count (PRD doesn't pin one), only
    # that the endpoint is reachable and returns the paginated envelope.
    assert isinstance(data, list)
    assert "total_count" in meta
