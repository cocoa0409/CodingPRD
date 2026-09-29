"""Operator safety scoring (PRD 3.2)."""

from fractions import Fraction

from db import db
from util import round_half_up

AUDIT_WINDOW = 3
BASE_WEIGHTS = (Fraction(1, 2), Fraction(3, 10), Fraction(1, 5))
CRITICAL_FINDING_PENALTY = 8
ADVERSE_CLAIM_PENALTY = 5
SAFETY_SCORE_FLOOR = 60
ADVERSE_CLAIM_STATUSES = ("ADJUDICATED_UPHELD", "SETTLED")


def operator_audits(operator_id):
    """Audits newest first: conducted_on DESC then created_at DESC."""
    rows = [a for a in db.audits.values() if a["operator_id"] == operator_id]
    rows.sort(key=lambda a: (a["conducted_on"], a["created_at"], a["_seq"]), reverse=True)
    return rows


def latest_auditor_user_id(operator_id):
    rows = operator_audits(operator_id)
    if not rows:
        return None
    return rows[0]["auditor_user_id"]


def adverse_claim_count(operator_id):
    return len([c for c in db.claims.values()
                if c["operator_id"] == operator_id and c["status"] in ADVERSE_CLAIM_STATUSES])


def compute_safety_score(operator):
    window = operator_audits(operator["id"])[:AUDIT_WINDOW]
    if not window:
        return 0
    weights = BASE_WEIGHTS[:len(window)]
    weight_sum = sum(weights)
    average = Fraction(0)
    for audit, weight in zip(window, weights):
        average += Fraction(audit["raw_score"]) * (weight / weight_sum)
    critical = sum(a["critical_finding_count"] for a in window)
    score = average - CRITICAL_FINDING_PENALTY * critical
    score -= ADVERSE_CLAIM_PENALTY * adverse_claim_count(operator["id"])
    rounded = round_half_up(score)
    return max(0, min(100, rounded))
