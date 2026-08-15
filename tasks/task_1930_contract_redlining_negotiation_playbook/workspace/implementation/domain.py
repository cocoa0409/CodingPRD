"""Business logic: tiering, routing, risk scoring, approver resolution,
approval-status derivation, obligation extraction, packet expiry."""
from datetime import timedelta

from core import (
    db, now, parse_iso, fmt, fmt_sec, seconds_between,
    stamp_audit, touch, new_id, next_seq,
)

# --------------------------------------------------------------------------
# Value tiering and routing (PRD 3.3)
# --------------------------------------------------------------------------


def compute_value_tier(ct, v):
    if v <= ct["low_value_threshold_cents"]:
        return "LOW"
    if v <= ct["mid_value_threshold_cents"]:
        return "MID"
    if v <= ct["high_value_threshold_cents"]:
        return "HIGH"
    return "VERY_HIGH"


def compute_routing_bucket(tier, risk, v, ct):
    """First-match-wins cascade, evaluated in exactly this order."""
    if risk == "SANCTIONED":
        return None  # refused at triage guard
    if risk == "HIGH_RISK":
        return "EXECUTIVE"
    if tier == "VERY_HIGH":
        return "EXECUTIVE"
    if tier == "HIGH":
        return "ELEVATED"
    if tier == "MID":
        return "STANDARD"
    if tier == "LOW" and v < ct["auto_approve_below_cents"]:
        return "SELF_SERVE"
    return "STANDARD"


OVERRIDE_UP = {
    "SELF_SERVE": "STANDARD",
    "STANDARD": "ELEVATED",
    "ELEVATED": "EXECUTIVE",
}

# --------------------------------------------------------------------------
# Deviation severity / risk scoring / approver resolution (PRD 3.5)
# --------------------------------------------------------------------------

SEV_SCORE = {"STANDARD": 0, "FALLBACK": 10, "NON_STANDARD": 30}
CAT_SCORE = {"OPERATIONAL": 0, "COMMERCIAL": 5, "REGULATORY": 15, "RISK": 20}
TIER_SCORE = {"LOW": 0, "MID": 5, "HIGH": 15, "VERY_HIGH": 25}
RISK_SCORE_CTPY = {"LOW": 0, "STANDARD": 5, "HIGH_RISK": 15}
SEV_CAP = {"LOW": 30, "MEDIUM": 60, "HIGH": 100}


def compute_risk_score(severity, category, tier, cp_risk, current_round_index, cap):
    base = (
        SEV_SCORE[severity]
        + CAT_SCORE[category]
        + TIER_SCORE[tier]
        + RISK_SCORE_CTPY.get(cp_risk, 0)
        + (current_round_index - 1) * 2
    )
    return min(SEV_CAP[cap], base)


def compute_required_role(clause, severity, value_cents, ct):
    """Ordered ladder of raises. Returns (role, escalated_flag)."""
    role = clause["approver_role_required"]
    escalated = False
    if severity == "NON_STANDARD" and clause["deviation_severity_cap"] == "HIGH":
        role = "CHIEF_COUNSEL"
        escalated = True
    if value_cents >= ct["requires_chief_counsel_above_cents"]:
        role = "CHIEF_COUNSEL"
        escalated = True
    if (
        severity != "STANDARD"
        and value_cents >= ct["high_value_threshold_cents"]
        and clause["category"] == "COMMERCIAL"
    ):
        if role != "CHIEF_COUNSEL":
            role = "FINANCE_CONTROLLER"
    if (
        clause["category"] == "OPERATIONAL"
        and severity == "FALLBACK"
        and role == "LEGAL_COUNSEL"
    ):
        role = "BUSINESS_OWNER"
    return role, escalated


def open_load(user_id):
    return sum(
        1
        for d in db.deviations.values()
        if d.get("assigned_approver_id") == user_id
        and d["status"] in ("OPEN", "IN_REVIEW", "ESCALATED")
    )


def pick_approver(role):
    """Active user holding role with the lowest active deviation load;
    ties broken in favor of the earliest-created user account."""
    cands = [
        u
        for u in db.users.values()
        if u["primary_role"] == role and u["status"] == "ACTIVE"
    ]
    if not cands:
        return None
    cands.sort(key=lambda u: (open_load(u["id"]), u["created_at"], u["_seq"]))
    return cands[0]["id"]


# --------------------------------------------------------------------------
# Negotiation derived counters + approval dimension (PRD 2.11, 3.6)
# --------------------------------------------------------------------------


def recompute_deviation_counters(neg):
    devs = [d for d in db.deviations.values() if d["negotiation_id"] == neg["id"]]
    neg["open_deviation_count"] = sum(
        1 for d in devs if d["status"] in ("OPEN", "IN_REVIEW", "ESCALATED")
    )
    neg["blocking_deviation_count"] = sum(
        1 for d in devs if d["status"] in ("OPEN", "ESCALATED")
    )
    if not devs:
        neg["approval_status"] = "NO_DEVIATIONS"
    elif any(d["status"] == "REJECTED" for d in devs):
        neg["approval_status"] = "BLOCKED"
    elif any(d["status"] in ("OPEN", "IN_REVIEW", "ESCALATED") for d in devs):
        neg["approval_status"] = "DEVIATIONS_PENDING"
    elif any(d["status"] == "APPROVED" for d in devs):
        neg["approval_status"] = "APPROVED_WITH_DEVIATIONS"
    else:
        neg["approval_status"] = "NO_DEVIATIONS"


def current_open_round(neg_id):
    for r in db.rounds.values():
        if r["negotiation_id"] == neg_id and r["status"] == "OPEN":
            return r
    return None


def close_round(rnd, actor_id):
    ts = now()
    rnd["closed_at"] = fmt(ts)
    rnd["closed_by_user_id"] = actor_id
    rnd["round_duration_seconds"] = seconds_between(parse_iso(rnd["opened_at"]), ts)
    rnd["status"] = "CLOSED"


# --------------------------------------------------------------------------
# Signature packet expiry sweep (PRD 2.5, 3.8)
# --------------------------------------------------------------------------


def expire_packets():
    n = now()
    for p in db.packets.values():
        if p["status"] in ("ROUTING", "PARTIALLY_SIGNED"):
            try:
                closes = parse_iso(p["signature_window_closes_at"])
            except ValueError:
                continue
            if n > closes:
                p["status"] = "EXPIRED"
                touch(p)
                neg = db.negotiations.get(p["negotiation_id"])
                if neg is not None and neg["signature_status"] in (
                    "ROUTING",
                    "PARTIALLY_SIGNED",
                ):
                    neg["signature_status"] = "NOT_STARTED"
                    touch(neg)


# --------------------------------------------------------------------------
# Obligation extraction (PRD 3.9)
# --------------------------------------------------------------------------

OWNER_ROLE_BY_CATEGORY = {
    "OPERATIONAL": "BUSINESS_OWNER",
    "COMMERCIAL": "FINANCE_CONTROLLER",
    "REGULATORY": "LEGAL_COUNSEL",
    "RISK": "LEGAL_COUNSEL",
}


def extract_obligations(neg, offsets, default_offset):
    intake = db.intakes.get(neg["intake_request_id"])
    effective = parse_iso(intake["effective_date"]) if intake else now()
    items = []
    devs = [d for d in db.deviations.values() if d["negotiation_id"] == neg["id"]]
    for d in sorted(devs, key=lambda d: (d["created_at"], d["_seq"])):
        if d["status"] != "APPROVED":
            continue
        clause = db.clauses.get(d["clause_template_id"])
        if clause is None:
            continue
        if d["severity"] == "FALLBACK":
            text = clause["fallback_positions"][d["fallback_index"]]
            source = "FALLBACK_POSITION"
        else:
            text = d["proposed_text"]
            source = "APPROVED_DEVIATION"
        items.append((clause, text, source))
    deviated = {d["clause_template_id"] for d in devs}
    playbook_clauses = [
        c for c in db.clauses.values() if c["playbook_id"] == neg["playbook_id"]
    ]
    for clause in sorted(playbook_clauses, key=lambda c: (c["created_at"], c["_seq"])):
        if clause["id"] in deviated:
            continue
        items.append((clause, clause["standard_text"], "STANDARD_TEXT"))
    ts = fmt(now())
    for clause, text, source in items:
        offset = offsets.get(clause["id"], default_offset)
        try:
            offset = int(offset)
        except (TypeError, ValueError):
            offset = 0
        due = effective + timedelta(days=offset)
        if clause["category"] == "REGULATORY":
            cap = effective + timedelta(days=30)
            if due > cap:
                due = cap
        ob = {
            "id": new_id(),
            "negotiation_id": neg["id"],
            "clause_template_id": clause["id"],
            "obligation_text": text,
            "extraction_source": source,
            "owner_role": OWNER_ROLE_BY_CATEGORY[clause["category"]],
            "due_offset_days": offset,
            "due_date": fmt_sec(due),
            "extracted_at": ts,
        }
        stamp_audit(ob)
        db.obligations[ob["id"]] = ob
