"""Scoring and threshold calculations (§1.3): documentation assembly score,
protest evidence score, and the compliance-posture recompute."""
from db import STORE

# documentation_assembly_score constants
BASE_WEIGHTS = {
    "WRITTEN_WARNING": 25,
    "SIGNED_POLICY": 20,
    "FINAL_INCIDENT_REPORT": 30,
    "ATTENDANCE_RECORD": 15,
    "PERFORMANCE_REVIEW": 10,
    "RESIGNATION_LETTER": 25,
    "OTHER": 5,
}
SUBMIT_THRESHOLD = 40

# protest_evidence_score constants
BASIS_WEIGHT = {
    "CLAIMANT_NOT_SEPARATED": 50,
    "WRONG_EMPLOYER": 70,
    "ALREADY_PROTESTED": 30,
    "EXCEEDS_MAX_BENEFIT": 60,
    "DUPLICATE_LINE": 65,
}
SUSTAIN_THRESHOLD = 60


def doc_contribution(doc, claim):
    """A document's own contribution value == its weight_points."""
    v = BASE_WEIGHTS[doc["doc_category"]]
    if doc["authenticated"]:
        v += 10
    # post-hoc discount: document dated after the claim notice was received
    if doc["doc_date"] > claim["notice_received_at"]:
        v -= 5
    return v


def assembly_score(claim):
    """documentation_assembly_score: each category contributes once — the
    single best document in it; raw sum capped at 100."""
    best = {}
    for doc in STORE.evidence.values():
        if doc["claim_id"] != claim["id"]:
            continue
        c = doc_contribution(doc, claim)
        cat = doc["doc_category"]
        if cat not in best or c > best[cat]:
            best[cat] = c
    return min(100, sum(best.values()))


def latest_filed_response(claim_id):
    """Latest-filed response among adjudication-visible statuses; tie on
    filed_at breaks toward the later created_at (then creation sequence)."""
    cands = [
        r for r in STORE.responses.values()
        if r["claim_id"] == claim_id
        and r["status"] in {"SUBMITTED", "ACCEPTED", "REJECTED_INSUFFICIENT"}
        and r["filed_at"] is not None
    ]
    if not cands:
        return None
    return max(cands, key=lambda r: (r["filed_at"], r["created_at"], r["_seq"]))


def protest_evidence_score(claim, protest_basis):
    """protest_evidence_score (§1.3) — pinned order: basis -> DENIED
    determination -> latest response timeliness -> coding confidence ->
    clamp 0..100."""
    score = BASIS_WEIGHT[protest_basis]
    if any(
        d["claim_id"] == claim["id"] and d["outcome"] == "DENIED"
        for d in STORE.determinations.values()
    ):
        score += 20
    latest = latest_filed_response(claim["id"])
    if latest is not None and latest["timeliness"] == "LATE":
        score -= 25
    sep = STORE.separations.get(claim["separation_id"])
    if sep is not None:
        conf = sep["reason_coding_confidence"]
        if conf == "CONFIRMED":
            score += 10
        elif conf == "DISPUTED":
            score -= 10
    return max(0, min(100, score))


def denied_protest_count(employer_id):
    """Denied protests on statements of this employer (posture half-strikes)."""
    n = 0
    for p in STORE.charge_protests.values():
        if p["status"] != "DENIED":
            continue
        stmt = STORE.charge_statements.get(p["statement_id"])
        if stmt is not None and stmt["employer_id"] == employer_id:
            n += 1
    return n


def recompute_posture(emp):
    """posture_recompute (§1.3 / §2.10): effective strikes =
    late_response_strikes + 0.5 per denied protest; inclusive thresholds
    2.0 -> WATCH, 4.0 -> SANCTIONED."""
    effective = emp["late_response_strikes"] + 0.5 * denied_protest_count(emp["id"])
    if effective >= 4:
        emp["compliance_posture"] = "SANCTIONED"
    elif effective >= 2:
        emp["compliance_posture"] = "WATCH"
    else:
        emp["compliance_posture"] = "CLEAR"
