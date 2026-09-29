"""Signature confidence, escalation quorum, and the reviewer selector (PRD 3.5)."""
from decimal import ROUND_HALF_UP, Decimal

import db
import lookups
from constants import (
    REVIEWER_MAX_OPEN_REVIEWS,
    SIGNATURE_AUTO_ACCEPT_THRESHOLD,
    SIGNATURE_LEAD_BONUS,
    SIGNATURE_ON_FILE_CAP,
    SIGNATURE_ON_FILE_STEP,
    SIGNATURE_REJECT_FLOOR,
    SIGNATURE_STALENESS_DAYS,
    SIGNATURE_STALENESS_PENALTY,
)
from errors import ApiError
from services import logbook

FOUR_PLACES = Decimal("0.0001")


# ------------------------------------------------------------------ confidence
def confidence_score(decision, similarity_score, env, voter_rec, reviewer_rec):
    if decision in ("MISSING_SIGNATURE", "ABSTAIN"):
        return None
    if similarity_score is None:
        return None
    elapsed = (env["received_at"] - voter_rec["last_signature_update_at"]).total_seconds()
    age_days = int(elapsed // 86400)

    on_file_count = voter_rec["signature_on_file_count"] or 1
    on_file = SIGNATURE_ON_FILE_STEP * Decimal(on_file_count - 1)
    if on_file > SIGNATURE_ON_FILE_CAP:
        on_file = SIGNATURE_ON_FILE_CAP

    staleness = (
        SIGNATURE_STALENESS_PENALTY if age_days > SIGNATURE_STALENESS_DAYS else Decimal("0")
    )
    lead = (
        SIGNATURE_LEAD_BONUS
        if reviewer_rec["training_status"] == "CERTIFIED_LEAD"
        else Decimal("0")
    )
    raw = (Decimal(similarity_score) / Decimal(100)) * (
        Decimal(1) + on_file + lead
    ) - staleness
    if raw < Decimal("0"):
        raw = Decimal("0")
    if raw > Decimal("1"):
        raw = Decimal("1")
    return raw.quantize(FOUR_PLACES, rounding=ROUND_HALF_UP)


# ------------------------------------------------------------------ review sets
def reviews_of_envelope(env):
    return db.ordered(
        [
            r for r in db.signature_reviews.values()
            if r["return_envelope_id"] == env["id"]
        ]
    )


def submitted_reviews(env):
    rows = [r for r in reviews_of_envelope(env) if r["status"] == "SUBMITTED"]
    return sorted(rows, key=lambda r: (r["review_round"], r["created_at"], r["_seq"]))


def dispositive_review(env):
    rows = submitted_reviews(env)
    return rows[-1] if rows else None


# ------------------------------------------------------------------ quorum
def _outcome(env, current_round):
    """Returns (outcome, reason_code) with outcome in
    ACCEPT | ESCALATE | ESCALATE_LEAD | CURE_REQUIRED."""
    rows = submitted_reviews(env)
    by_round = {}
    for row in rows:
        by_round[row["review_round"]] = row

    # One rule overrides every round.
    for row in rows:
        if row["decision"] == "MISSING_SIGNATURE":
            return "CURE_REQUIRED", "MISSING_SIGNATURE"

    if current_round == 1:
        first = by_round.get(1)
        if first is None:
            return "ESCALATE_LEAD", None
        decision = first["decision"]
        conf = first["confidence_score"]
        if decision == "MATCH":
            if conf is not None and conf >= SIGNATURE_AUTO_ACCEPT_THRESHOLD:
                return "ACCEPT", None
            if conf is not None and conf >= SIGNATURE_REJECT_FLOOR:
                return "ESCALATE", None
            return "ESCALATE_LEAD", None
        if decision == "NO_MATCH":
            return "ESCALATE", None
        return "ESCALATE", None  # ABSTAIN

    if current_round == 2:
        d1 = by_round.get(1, {}).get("decision")
        d2 = by_round.get(2, {}).get("decision")
        pair = [d1, d2]
        if pair.count("MATCH") == 2:
            return "ACCEPT", None
        if pair.count("NO_MATCH") == 2:
            return "CURE_REQUIRED", "SIGNATURE_MISMATCH"
        if pair.count("ABSTAIN") == 1 and "MATCH" in pair:
            return "ACCEPT", None
        if pair.count("ABSTAIN") == 1 and "NO_MATCH" in pair:
            return "ESCALATE_LEAD", None
        if "MATCH" in pair and "NO_MATCH" in pair:
            return "ESCALATE_LEAD", None
        return "ESCALATE_LEAD", None

    third = by_round.get(3)
    decision = third["decision"] if third else None
    if decision == "MATCH":
        return "ACCEPT", None
    return "CURE_REQUIRED", "SIGNATURE_MISMATCH"


def resolve(env, review, election_rec, actor):
    """Apply the round outcome to the envelope's signature dimension."""
    outcome, reason = _outcome(env, review["review_round"])
    dispositive = dispositive_review(env) or review

    # The one situation in which a mismatch does not earn a cure.
    if (
        outcome == "CURE_REQUIRED"
        and reason == "SIGNATURE_MISMATCH"
        and env.get("remade_from_envelope_id") is not None
        and review["review_round"] >= 2
    ):
        env["signature_status"] = "REJECTED"
        env["resolved_signature_confidence"] = dispositive["confidence_score"]
        env["_cure_reason_code"] = None
        if env["custody_status"] == "SEALED":
            env["custody_status"] = "SEQUESTERED"
        db.touch(env)
        voter_rec = lookups.voter_of_envelope(env)
        if voter_rec is not None:
            voter_rec["provisional_ballot_eligible"] = True
            db.touch(voter_rec)
        if election_rec is not None:
            election_rec["provisional_referral_count"] += 1
            db.touch(election_rec)
        return "REJECT_NO_CURE"

    if outcome == "ACCEPT":
        env["signature_status"] = "ACCEPTED"
        env["resolved_signature_confidence"] = dispositive["confidence_score"]
        db.touch(env)
        return outcome

    if outcome == "CURE_REQUIRED":
        env["signature_status"] = "CURE_REQUIRED"
        env["resolved_signature_confidence"] = dispositive["confidence_score"]
        env["_cure_reason_code"] = reason
        db.touch(env)
        return outcome

    # Plain or lead-restricted escalation: no review row is created here.
    env["signature_status"] = "ESCALATED"
    env["_lead_required_next"] = outcome == "ESCALATE_LEAD"
    db.touch(env)
    logbook.append(
        election_rec,
        "SIGNATURE_ESCALATION",
        actor.role,
        actor.user_id,
        "ReturnEnvelope",
        env["id"],
        "Signature review round %d escalated%s."
        % (review["review_round"], " to a certified lead" if outcome == "ESCALATE_LEAD" else ""),
    )
    return outcome


# ------------------------------------------------------------------ selector
def select_reviewer(env, target_round):
    lead_required = target_round == 3 or bool(env.get("_lead_required_next"))
    now = db.now()
    excluded = {r["reviewer_id"] for r in reviews_of_envelope(env)}

    candidates = []
    for reviewer_rec in db.reviewers.values():
        if reviewer_rec["training_status"] not in ("TRAINED", "CERTIFIED_LEAD"):
            continue
        expires = reviewer_rec["training_expires_at"]
        if expires is None or not expires > now:
            continue
        if reviewer_rec["active_review_count"] >= REVIEWER_MAX_OPEN_REVIEWS:
            continue
        if reviewer_rec["id"] in excluded:
            continue
        if lead_required and reviewer_rec["training_status"] != "CERTIFIED_LEAD":
            continue
        candidates.append(reviewer_rec)

    if not candidates:
        raise ApiError("ERR_NO_ELIGIBLE_REVIEWER")

    candidates.sort(
        key=lambda r: (
            r["active_review_count"],
            r["completed_review_count"],
            r["created_at"],
            r["_seq"],
        )
    )
    return candidates[0]
