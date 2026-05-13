"""Complaint flow + four corrective actions. Covers PRD §3.10.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    api_client,
    accept_complaint,
    decide_award,
    file_complaint,
    file_complaint_payload,
    make_supplier_headers,
    setup_award_published,
    setup_awarded,
    setup_complaint_under_review_on_awarded,
    setup_evaluating,
    uphold_complaint,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Complaint lifecycle (SUBMITTED -> UNDER_REVIEW -> UPHELD/DISMISSED)
# ===========================================================================
def test_file_complaint_starts_submitted(api):
    """PRD §3.10: "The complaint enters SUBMITTED." """
    ctx = setup_awarded()
    losing = next(b for b in ctx["bids"] if b["id"] != ctx["award"]["winning_bid_id"])
    complainant_id = losing["supplier_id"]
    res = api.file_complaint(
        ctx["project"]["id"],
        file_complaint_payload(
            complainant_supplier_id=complainant_id,
            subject="EVALUATION",
            narrative="Scoring is inconsistent.",
        ),
        make_supplier_headers(complainant_id),
    )
    data = validate_success(res, 201)
    assert data["complaint_status"] == "SUBMITTED"


def test_withdraw_complaint_by_owner_succeeds(api):
    """PRD §3.10: "The complainant supplier may withdraw a SUBMITTED
    complaint themselves (the X-User-ID must match
    complainant_supplier_id), transitioning to WITHDRAWN."
    """
    ctx = setup_awarded()
    losing = next(b for b in ctx["bids"] if b["id"] != ctx["award"]["winning_bid_id"])
    complainant_id = losing["supplier_id"]
    complaint = file_complaint(ctx["project"]["id"], complainant_id)
    res = api.withdraw_complaint(
        complaint["id"], make_supplier_headers(complainant_id),
    )
    data = validate_success(res)
    assert data["complaint_status"] == "WITHDRAWN"


def test_withdraw_complaint_by_other_supplier_rejected(api):
    """PRD §3.10: "the X-User-ID must match complainant_supplier_id."
    Claim: a different supplier cannot withdraw someone else's complaint.
    """
    ctx = setup_awarded()
    losing = next(b for b in ctx["bids"] if b["id"] != ctx["award"]["winning_bid_id"])
    complainant_id = losing["supplier_id"]
    other = next(
        b["supplier_id"] for b in ctx["bids"]
        if b["supplier_id"] != complainant_id
    )
    assert other != complainant_id
    complaint = file_complaint(ctx["project"]["id"], complainant_id)
    res = api.withdraw_complaint(
        complaint["id"], make_supplier_headers(other),
    )
    assert 400 <= res.status_code < 500


def test_accept_complaint_transitions_to_under_review(api, regulator_headers):
    """PRD §3.10: "The regulator accepts the complaint, transitioning
    SUBMITTED → UNDER_REVIEW, which appends an AuditLog entry with
    target_type COMPLAINT and action "COMPLAINT_ACCEPTED"."
    """
    ctx = setup_awarded()
    losing = next(b for b in ctx["bids"] if b["id"] != ctx["award"]["winning_bid_id"])
    complainant_id = losing["supplier_id"]
    complaint = file_complaint(ctx["project"]["id"], complainant_id)
    res = api.accept_complaint(complaint["id"], regulator_headers)
    data = validate_success(res)
    assert data["complaint_status"] == "UNDER_REVIEW"
    # Audit log entry exists.
    logs_res = api.list_audit_logs(
        regulator_headers,
        params={"target_type": "COMPLAINT", "limit": 100},
    )
    entries, _ = validate_paginated(logs_res)
    assert any(
        e.get("action") == "COMPLAINT_ACCEPTED" for e in entries
    ), "missing COMPLAINT_ACCEPTED audit entry"


def test_dismiss_complaint_sets_decision_at(api, regulator_headers):
    """PRD §3.10: "Dismissal — UNDER_REVIEW → DISMISSED — sets
    decision_at to the server clock and appends a COMPLAINT_DECIDED
    audit entry."
    """
    ctx = setup_complaint_under_review_on_awarded()
    res = api.dismiss_complaint(ctx["complaint"]["id"], regulator_headers)
    data = validate_success(res)
    assert data["complaint_status"] == "DISMISSED"
    assert data.get("decision_at") is not None


def test_uphold_requires_corrective_action_non_null(api, regulator_headers):
    """PRD §3.10: "Upholding — UNDER_REVIEW → UPHELD — requires
    corrective_action to be non-null and one of REOPEN_PRESCREEN,
    REOPEN_EVALUATION, REVOKE_AWARD, or FREEZE_PROJECT."
    """
    ctx = setup_complaint_under_review_on_awarded()
    res = api.uphold_complaint(
        ctx["complaint"]["id"], {"corrective_action": None},
        regulator_headers,
    )
    assert 400 <= res.status_code < 500


# ===========================================================================
# Corrective action: FREEZE_PROJECT
# ===========================================================================
def test_uphold_with_freeze_project_flips_status_and_reason(api, officer_headers):
    """PRD §3.10: "FREEZE_PROJECT flips the project to FROZEN with no
    further cascades."
    PRD §3.9: "A complaint upheld with corrective_action of
    REVOKE_AWARD or FREEZE_PROJECT flips the project from AWARDED →
    FROZEN and sets frozen_reason to COMPLAINT_UPHELD."
    """
    ctx = setup_complaint_under_review_on_awarded()
    uphold_complaint(ctx["complaint"]["id"], "FREEZE_PROJECT")
    proj = validate_success(api.get_project(ctx["project"]["id"], officer_headers))
    assert proj["project_status"] == "FROZEN"
    assert proj["frozen_reason"] == "COMPLAINT_UPHELD"


# ===========================================================================
# Corrective action: REVOKE_AWARD (cascade)
# ===========================================================================
def test_uphold_with_revoke_award_cascades(api, officer_headers):
    """PRD §3.9: "Under REVOKE_AWARD, the award is additionally moved
    to REVOKED and the winning bid is moved to DISQUALIFIED."
    PRD §3.10: "REVOKE_AWARD flips the project to FROZEN, moves the
    award to REVOKED, moves the winning bid to DISQUALIFIED."
    """
    ctx = setup_complaint_under_review_on_awarded()
    uphold_complaint(ctx["complaint"]["id"], "REVOKE_AWARD")
    proj = validate_success(api.get_project(ctx["project"]["id"], officer_headers))
    assert proj["project_status"] == "FROZEN"
    assert proj["frozen_reason"] == "COMPLAINT_UPHELD"
    # Re-read bids; winning must be DISQUALIFIED.
    listed = api.list_project_bids(
        ctx["project"]["id"], officer_headers, params={"limit": 100},
    )
    bids, _ = validate_paginated(listed)
    winning_id = ctx["award"]["winning_bid_id"]
    winning = next(b for b in bids if b["id"] == winning_id)
    assert winning["bid_status"] == "DISQUALIFIED"


# ===========================================================================
# Corrective action: REOPEN_EVALUATION
# ===========================================================================
def test_uphold_with_reopen_evaluation_only_when_evaluating(api, regulator_headers):
    """PRD §3.10: "REOPEN_EVALUATION returns the evaluation committee
    to EVALUATING and is valid only when the project is currently in
    EVALUATING."
    """
    # Stage 1: project in AWARDED — reopen_evaluation must NOT apply
    # (PRD says "valid only when ... EVALUATING").
    ctx = setup_complaint_under_review_on_awarded()
    res = api.uphold_complaint(
        ctx["complaint"]["id"],
        {"corrective_action": "REOPEN_EVALUATION"},
        regulator_headers,
    )
    validate_error(res, "ERR_INVALID_STATE")


def test_uphold_with_reopen_evaluation_when_in_evaluating_succeeds(api, officer_headers, regulator_headers):
    """PRD §3.10: same — valid only when project is EVALUATING."""
    ctx = setup_evaluating()
    losing_bid = ctx["bids"][0]
    complainant_id = losing_bid["supplier_id"]
    complaint = file_complaint(
        ctx["project"]["id"], complainant_id, subject="EVALUATION",
    )
    accept_complaint(complaint["id"])
    res = api.uphold_complaint(
        complaint["id"],
        {"corrective_action": "REOPEN_EVALUATION"},
        regulator_headers,
    )
    data = validate_success(res)
    assert data["complaint_status"] == "UPHELD"
