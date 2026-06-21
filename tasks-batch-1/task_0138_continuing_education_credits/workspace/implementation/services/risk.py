"""Audit-risk-score calculation (PRD §3.9, SCAFFOLD §1.3 audit_risk_score).

Weighted, integer-valued, clamped to [0, 100]:
  score = min(100, W_LATE*late_count + W_REJECT*reject_count + W_RECIP*recip_count)

Two variants with different inclusion sets:
  - intake_estimate (on Completion reject): late completions counted in
      {PENDING_VERIFICATION, VERIFIED, REJECTED}; reject_count = all REJECTED.
  - review_final (on Attestation submit): late completions counted only in
      {VERIFIED}; rejections that were later resubmitted-and-verified are
      excluded (i.e. only completions still in REJECTED count toward reject_count).

Both variants count APPROVED reciprocity grants identically.
"""

from db import db

W_LATE = 3
W_REJECT = 5
W_RECIP = 2
SCORE_CEILING = 100


def _licensee_completions(licensee_id):
    return [c for c in db.completions.values() if c["licensee_id"] == licensee_id]


def _approved_recip_count(licensee_id):
    return sum(
        1 for g in db.reciprocity_grants.values()
        if g["licensee_id"] == licensee_id and g["status"] == "APPROVED"
    )


def _score(late_count, reject_count, recip_count):
    raw = W_LATE * late_count + W_REJECT * reject_count + W_RECIP * recip_count
    if raw < 0:
        raw = 0
    return min(SCORE_CEILING, raw)


def compute_intake(licensee_id):
    """Intake variant: pessimistic estimate computed at Completion reject time."""
    completions = _licensee_completions(licensee_id)
    late_count = sum(
        1 for c in completions
        if c["is_late"] and c["status"] in ("PENDING_VERIFICATION", "VERIFIED", "REJECTED")
    )
    reject_count = sum(1 for c in completions if c["status"] == "REJECTED")
    recip_count = _approved_recip_count(licensee_id)
    return _score(late_count, reject_count, recip_count)


def compute_review_final(licensee_id):
    """Review-final variant: settled figure computed at Attestation submit time.

    Late completions counted only among VERIFIED; reject_count counts only the
    completions still in REJECTED (rejections later resubmitted-and-verified are
    no longer REJECTED, so they fall out — the settled figure).
    """
    completions = _licensee_completions(licensee_id)
    late_count = sum(
        1 for c in completions
        if c["is_late"] and c["status"] == "VERIFIED"
    )
    reject_count = sum(1 for c in completions if c["status"] == "REJECTED")
    recip_count = _approved_recip_count(licensee_id)
    return _score(late_count, reject_count, recip_count)
