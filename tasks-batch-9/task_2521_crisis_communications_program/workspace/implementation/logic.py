"""Calculations (PRD 2.7, 3.x / SCAFFOLD 1.3) and derived-field recomputation.

Every conserved ledger and every counter here is recomputed from scratch out of
the current store contents - never incrementally patched - so a forward action
followed by its compensating action lands the ledger exactly where it started
(PRD 2.7).
"""

from datetime import timedelta
from decimal import Decimal

from core import (
    D,
    fail,
    floor_days,
    floor_minutes,
    round2,
    round4,
    store,
    touch,
    sort_key,
)

# --- pinned constants (SCAFFOLD 1.3 `constants`) ----------------------------
CREDIBILITY_MULTIPLIER = {"A": D("1.00"), "B": D("0.85"), "C": D("0.60")}
CHANNEL_BUMP = {"MEDIA": D(8), "SOCIAL": D(4), "REGULATORY": D(15)}
SENTIMENT_SCALE = D(30)
REGULATORY_FLAG_BUMP = D(12)
ESCALATION_THRESHOLD = D("70.00")

TIER_BOUNDARIES = (("SEV1", D("90.00")), ("SEV2", D("70.00")), ("SEV3", D("50.00")))
PEAK_WEIGHT = D("0.6")
AVERAGE_WEIGHT = D("0.4")

HOLDING_SLA_MINUTES = {"SEV1": 30, "SEV2": 60, "SEV3": 180, "SEV4": 480}
REVIEW_SLA_MINUTES = {"SEV1": 15, "SEV2": 30, "SEV3": 90, "SEV4": 240}

TIER_POINTS = {"SEV1": D(100), "SEV2": D(75), "SEV3": D(50), "SEV4": D(25)}
SEVERITY_WEIGHT = D("0.70")
EXPOSURE_WEIGHT = D("0.30")
AMP_RATE = {"HIGH": D("0.20"), "MEDIUM": D("0.10"), "LOW": D("0.05")}
CONTAINMENT_CAP = D("150.00")
EXPOSURE_CAP = D("100.00")

AUDIENCE_WEIGHT = {
    "EMPLOYEE": D("1.00"),
    "CUSTOMER": D("1.25"),
    "REGULATOR": D("1.50"),
    "INVESTOR": D("1.75"),
    "MEDIA": D("2.00"),
}
AUDIENCE_SEQUENCE_RANK = {"EMPLOYEE": 1, "CUSTOMER": 2, "REGULATOR": 3, "INVESTOR": 4, "MEDIA": 5}
REACH_DIVISOR = D(1000)
REGULATORY_OVERRIDE_WINDOW_MINUTES = 120

EFFICACY_MAX = D("2.50")
EXPOSURE_FACTOR_CAP = D("0.50")

DECAY_PER_DAY = D("2.50")
READY_THRESHOLD = D("60.00")

AUTHORITY_RANK = {"FULL": 2, "LIMITED": 1}
INTERVIEW_BUFFER_MINUTES = 30
VIRALITY_ESCALATION_THRESHOLD = D("60.00")
QUESTION_PACK_MIN_QUESTIONS = 8
QUESTION_PACK_MIN_HIGH_RISK = 3
MAX_REVISION_ROUNDS = 3

OPEN_CLAIM_STATES = ("DETECTED", "TRIAGED", "PLATFORM_ESCALATED", "CORRECTION_ISSUED")

# enum vocabularies
SCENARIO_CODES = ("PRODUCT_RECALL", "DATA_BREACH", "EXEC_MISCONDUCT", "PLANT_INCIDENT", "REGULATORY_PROBE")
MATERIAL_TYPES = ("DARK_SITE_PAGE", "FAQ", "HOLDING_TEMPLATE", "EXEC_BRIEF")
CHANNEL_TYPES = ("MEDIA", "SOCIAL", "REGULATORY")
CREDIBILITY_TIERS = ("A", "B", "C")
TEAM_ROLES = ("INCIDENT_LEAD", "LEGAL_COUNSEL", "COMMS_LEAD", "SPOKESPERSON", "SOCIAL_LISTENER", "EXEC_SPONSOR")
DECISION_AUTHORITIES = ("FULL", "LIMITED")
STATEMENT_TYPES = ("HOLDING", "UPDATE", "CORRECTION", "FINAL")
AUDIENCES = ("EMPLOYEE", "CUSTOMER", "REGULATOR", "INVESTOR", "MEDIA")
SEVERITY_TIERS = ("SEV1", "SEV2", "SEV3", "SEV4")
POSTURES = ("OPEN", "RESTRICTED", "FROZEN")
RESPONSE_STATES = ("MONITORING", "ACTIVATED", "RESOLVED")
PRIVILEGE_STATES = ("NON_PRIVILEGED", "PRIVILEGED_ASSERTED", "PRIVILEGE_WAIVED")


# ---------------------------------------------------------------------------
# collection helpers
# ---------------------------------------------------------------------------
def incident_signals(incident_id):
    return [s for s in store.signals.values() if s["incident_id"] == incident_id]


def incident_statements(incident_id):
    return [s for s in store.statements.values() if s["incident_id"] == incident_id]


def incident_notices(incident_id):
    return [n for n in store.notices.values() if n["incident_id"] == incident_id]


def incident_claims(incident_id):
    return [c for c in store.claims.values() if c["incident_id"] == incident_id]


def incident_interviews(incident_id):
    return [i for i in store.interviews.values() if i["incident_id"] == incident_id]


def incident_assignments(incident_id):
    return [a for a in store.assignments.values() if a["incident_id"] == incident_id]


def statement_tasks(statement_id):
    return [t for t in store.tasks.values() if t["statement_id"] == statement_id]


def round_tasks(statement):
    return [
        t
        for t in statement_tasks(statement["id"])
        if t["revision_round"] == statement["revision_round"]
    ]


# ---------------------------------------------------------------------------
# calculations.signal_escalation_score
# ---------------------------------------------------------------------------
def signal_escalation_score(reach_score, sentiment_score, credibility_tier, channel_type, regulatory_flag):
    multiplier = CREDIBILITY_MULTIPLIER[credibility_tier]
    base = round2(D(reach_score) * multiplier)
    negative = -D(sentiment_score)
    if negative < 0:
        negative = D(0)
    sentiment_penalty = round2(negative * SENTIMENT_SCALE)
    bump = CHANNEL_BUMP[channel_type]
    regulatory_bump = REGULATORY_FLAG_BUMP if regulatory_flag else D(0)
    raw = base + sentiment_penalty + bump + regulatory_bump
    score = round2(raw)
    if score > D("100.00"):
        score = D("100.00")
    return round2(score)


# ---------------------------------------------------------------------------
# calculations.incident_severity_tier
# ---------------------------------------------------------------------------
def tier_of(score):
    for tier, boundary in TIER_BOUNDARIES:
        if score >= boundary:
            return tier
    return "SEV4"


def provisional_severity(incident):
    """Candidate set: signals in LINKED or ESCALATED; score = max escalation_score."""
    candidates = [
        s for s in incident_signals(incident["id"]) if s["state"] in ("LINKED", "ESCALATED")
    ]
    if not candidates:
        return None, None
    score = max(D(s["escalation_score"]) for s in candidates)
    score = round2(score)
    return tier_of(score), score


def final_severity(incident):
    """Candidate set: ESCALATED signals only, ordered by detected_at then created_at."""
    candidates = [s for s in incident_signals(incident["id"]) if s["state"] == "ESCALATED"]
    if not candidates:
        return None, None
    candidates.sort(key=lambda s: (s["detected_at"], s["created_at"], s["_seq"]))
    scores = [D(s["escalation_score"]) for s in candidates]
    peak = max(scores)
    average = round2(sum(scores) / D(len(scores)))
    score = round2(peak * PEAK_WEIGHT + average * AVERAGE_WEIGHT)
    return tier_of(score), score


# ---------------------------------------------------------------------------
# calculations.holding_statement_due_at
# ---------------------------------------------------------------------------
def holding_statement_due_at(incident):
    if incident["activated_at"] is None or incident["severity_tier"] is None:
        return None
    return incident["activated_at"] + timedelta(minutes=HOLDING_SLA_MINUTES[incident["severity_tier"]])


def evaluate_sla_breach(incident):
    """sla_breached latches true once current_utc >= due while no HOLDING published."""
    due = incident["holding_statement_due_at"]
    if due is None:
        return
    if incident["holding_statement_published_at"] is None and store.now() >= due:
        incident["sla_breached"] = True


# ---------------------------------------------------------------------------
# calculations.containment_priority_score
# ---------------------------------------------------------------------------
def exposure_component(incident):
    total = D(0)
    for claim in incident_claims(incident["id"]):
        if claim["state"] in OPEN_CLAIM_STATES:
            total += D(claim["virality_score"])
    total = round2(total)
    if total > EXPOSURE_CAP:
        total = EXPOSURE_CAP
    return total


def recompute_containment(incident):
    tier = incident["severity_tier"]
    if tier is None:
        return
    exposure = exposure_component(incident)
    base = round2(SEVERITY_WEIGHT * TIER_POINTS[tier] + EXPOSURE_WEIGHT * exposure)
    if base >= D("80.00"):
        band = "HIGH"
    elif base >= D("55.00"):
        band = "MEDIUM"
    else:
        band = "LOW"
    rate = AMP_RATE[band]
    fee = round2(base * rate)
    total = round2(base + fee)
    if total > CONTAINMENT_CAP:
        total = CONTAINMENT_CAP
    incident["base_containment_score"] = base
    incident["amplification_rate_applied"] = rate
    incident["containment_priority_score"] = round2(total)


# ---------------------------------------------------------------------------
# calculations.stakeholder_reach_index
# ---------------------------------------------------------------------------
def notice_reach_contribution(notice):
    weight = AUDIENCE_WEIGHT[notice["audience"]]
    return round2(weight * D(notice["estimated_reach"]) / REACH_DIVISOR)


def recompute_reach_index(incident):
    released = [n for n in incident_notices(incident["id"]) if n["state"] == "RELEASED"]
    released.sort(key=lambda n: (n["released_at"], n["created_at"], n["_seq"]))
    total = D(0)
    for notice in released:
        total += round2(D(notice["reach_contribution"]))
    incident["stakeholder_reach_index"] = round2(total)


# ---------------------------------------------------------------------------
# calculations.reputation_delta
# ---------------------------------------------------------------------------
def reputation_deltas(review):
    raw = round2(D(review["reputation_index_after"]) - D(review["reputation_index_before"]))
    exposure = D(review["exposure_factor"])
    if review["total_claim_count"] == 0:
        ratio = D("0.0000")
    else:
        ratio = round4(D(review["corrected_claim_count"]) / D(review["total_claim_count"]))
    bonus = round2(EFFICACY_MAX * ratio)
    adjusted = round2(raw * (D(1) - exposure) + bonus)
    return raw, adjusted


def exposure_factor_for(incident):
    value = D(incident["stakeholder_reach_index"]) / D(100)
    if value > EXPOSURE_FACTOR_CAP:
        value = EXPOSURE_FACTOR_CAP
    return round4(value)


# ---------------------------------------------------------------------------
# calculations.material_readiness_score
# ---------------------------------------------------------------------------
def material_readiness(material, now=None):
    now = now or store.now()
    days = floor_days(material["last_reviewed_at"], now)
    score = round2(D("100.00") - DECAY_PER_DAY * D(days))
    if score < D("0.00"):
        score = D("0.00")
    state = "READY" if score >= READY_THRESHOLD else "STALE"
    return score, state


# ---------------------------------------------------------------------------
# calculations.approval_quorum_requirement / approval_task_routing
# ---------------------------------------------------------------------------
def required_approver_roles(incident, statement):
    roles = ["INCIDENT_LEAD"]
    if incident["severity_tier"] in ("SEV1", "SEV2") or statement["privilege_marked"]:
        roles.append("LEGAL_COUNSEL")
    if incident["severity_tier"] == "SEV1":
        roles.append("EXEC_SPONSOR")
    return roles


def route_approver(incident, statement, team_role):
    candidates = []
    for assignment in incident_assignments(incident["id"]):
        if assignment["team_role"] != team_role or assignment["state"] != "ACKNOWLEDGED":
            continue
        if statement["privilege_marked"]:
            member = store.members.get(assignment["member_id"])
            if not (member and member["privilege_cleared"]):
                continue
        candidates.append(assignment)
    if not candidates:
        return None
    candidates.sort(
        key=lambda a: (-AUTHORITY_RANK[a["decision_authority"]], a["created_at"], a["_seq"])
    )
    return candidates[0]


# ---------------------------------------------------------------------------
# calculations.conserved_ledger_recomputation
# All three conserved ledgers are rebuilt from scratch from the current rows.
# ---------------------------------------------------------------------------
def recompute_open_approval_task_count(incident):
    """PRD 2.7 ledger 1: PENDING tasks whose statement belongs to the incident."""
    statement_ids = {s["id"] for s in incident_statements(incident["id"])}
    incident["open_approval_task_count"] = sum(
        1
        for t in store.tasks.values()
        if t["statement_id"] in statement_ids and t["state"] == "PENDING"
    )


def recompute_reserved_correction_minutes(channel):
    """PRD 2.7 ledger 2: sum of correction_window_minutes over CORRECTION_ISSUED."""
    channel["reserved_correction_minutes"] = sum(
        c["correction_window_minutes"]
        for c in store.claims.values()
        if c["channel_id"] == channel["id"] and c["state"] == "CORRECTION_ISSUED"
    )


def recompute_scheduled_interview_minutes(member):
    """PRD 2.7 ledger 3: sum of duration_minutes over CONFIRMED interviews."""
    member["scheduled_interview_minutes"] = sum(
        i["duration_minutes"]
        for i in store.interviews.values()
        if i["spokesperson_member_id"] == member["id"] and i["state"] == "CONFIRMED"
    )


def recompute_active_assignment_count(member):
    member["active_assignment_count"] = sum(
        1
        for a in store.assignments.values()
        if a["member_id"] == member["id"] and a["state"] in ("ASSIGNED", "ACKNOWLEDGED")
    )


def recompute_open_escalation_count(channel):
    channel["open_escalation_count"] = sum(
        1
        for c in store.claims.values()
        if c["channel_id"] == channel["id"] and c["state"] == "PLATFORM_ESCALATED"
    )


def bump_member(member, recompute):
    """Recompute a member counter; bump version only when the value moves."""
    before = (member["scheduled_interview_minutes"], member["active_assignment_count"])
    recompute(member)
    after = (member["scheduled_interview_minutes"], member["active_assignment_count"])
    if before != after:
        touch(member)


def recompute_counts(incident):
    """Every query-derived counter on the incident (never latched fields)."""
    iid = incident["id"]
    signals = incident_signals(iid)
    incident["linked_signal_count"] = sum(1 for s in signals if s["state"] in ("LINKED", "ESCALATED"))
    incident["escalated_signal_count"] = sum(1 for s in signals if s["state"] == "ESCALATED")
    notices = incident_notices(iid)
    incident["blocked_notice_count"] = sum(1 for n in notices if n["state"] == "BLOCKED")
    incident["released_notice_count"] = sum(1 for n in notices if n["state"] == "RELEASED")
    incident["open_claim_count"] = sum(
        1 for c in incident_claims(iid) if c["state"] in OPEN_CLAIM_STATES
    )
    incident["confirmed_interview_count"] = sum(
        1 for i in incident_interviews(iid) if i["state"] == "CONFIRMED"
    )
    recompute_open_approval_task_count(incident)
    recompute_reach_index(incident)


def recompute_posture(incident):
    """PRD 2.6: three-rule precedence, first match wins."""
    if incident["legal_hold_active"] or incident["response_state"] == "RESOLVED":
        incident["comms_posture"] = "FROZEN"
    elif incident["sla_breached"] or incident["blocked_notice_count"] >= 1:
        incident["comms_posture"] = "RESTRICTED"
    else:
        incident["comms_posture"] = "OPEN"


def refresh(incident):
    """Recompute every counter then the posture. Safe to call after any change."""
    recompute_counts(incident)
    recompute_posture(incident)


# ---------------------------------------------------------------------------
# Gate helpers (PRD 2.9 steps 11 and 12)
# ---------------------------------------------------------------------------
def require_activated(incident):
    if incident["response_state"] == "RESOLVED":
        fail("ERR_INCIDENT_ALREADY_RESOLVED", "The incident has already been resolved.")
    if incident["response_state"] != "ACTIVATED":
        fail("ERR_INCIDENT_NOT_ACTIVATED", "The incident is not ACTIVATED.")


def require_not_resolved(incident):
    if incident["response_state"] == "RESOLVED":
        fail("ERR_INCIDENT_ALREADY_RESOLVED", "The incident has already been resolved.")


def require_not_frozen(incident):
    if incident["comms_posture"] == "FROZEN":
        fail("ERR_COMMS_POSTURE_FROZEN", "The incident communications posture is FROZEN.")


def require_open_posture(incident):
    if incident["comms_posture"] != "OPEN":
        fail(
            "ERR_COMMS_POSTURE_FROZEN",
            "Interview confirmation requires a fully OPEN communications posture.",
        )


def require_privilege(caller):
    if not caller.privilege_cleared:
        fail("ERR_PRIVILEGE_NOT_CLEARED", "The acting member is outside the privilege circle.")


def acknowledged_seat(incident_id, team_role, member_id=None):
    for assignment in incident_assignments(incident_id):
        if assignment["team_role"] != team_role or assignment["state"] != "ACKNOWLEDGED":
            continue
        if member_id is not None and assignment["member_id"] != member_id:
            continue
        return assignment
    return None


# ---------------------------------------------------------------------------
# Shared cascades
# ---------------------------------------------------------------------------
def void_pending_round_tasks(statement, exclude_task_id=None):
    now = store.now()
    for task in round_tasks(statement):
        if task["state"] != "PENDING" or task["id"] == exclude_task_id:
            continue
        task["state"] = "VOIDED"
        task["decided_at"] = now
        touch(task)


def block_queued_notices(statement):
    """A QUEUED notice becomes BLOCKED when its statement enters REVISION_REQUESTED."""
    for notice in store.notices.values():
        if notice["statement_id"] == statement["id"] and notice["state"] == "QUEUED":
            notice["state"] = "BLOCKED"
            touch(notice)


def unblock_notices(statement):
    """A BLOCKED notice returns to QUEUED when its statement is approved again."""
    for notice in store.notices.values():
        if notice["statement_id"] == statement["id"] and notice["state"] == "BLOCKED":
            notice["state"] = "QUEUED"
            touch(notice)


def push_revision_requested(statement, incident, exclude_task_id=None):
    """Shared collapse used by rejection and by sweep expiry (PRD 3.5)."""
    statement["state"] = "REVISION_REQUESTED"
    touch(statement)
    void_pending_round_tasks(statement, exclude_task_id=exclude_task_id)
    block_queued_notices(statement)
    recompute_approvals_recorded(statement)


def recompute_approvals_recorded(statement):
    statement["approvals_recorded"] = sum(
        1 for t in round_tasks(statement) if t["state"] == "APPROVED"
    )


# ---------------------------------------------------------------------------
# Path / body identifier resolution (PRD 2.5, order-of-rejection steps 5 and 6)
# ---------------------------------------------------------------------------
def _resolve(collection, key, error_id, label):
    record = collection.get(key) if isinstance(key, str) else None
    if record is None:
        fail(error_id, "No %s with id '%s'." % (label, key))
    return record


def get_member(key):
    return _resolve(store.members, key, "ERR_TEAM_MEMBER_NOT_FOUND", "TeamMember")


def get_channel(key):
    return _resolve(store.channels, key, "ERR_CHANNEL_NOT_FOUND", "MonitoredChannel")


def get_incident(key):
    return _resolve(store.incidents, key, "ERR_INCIDENT_NOT_FOUND", "Incident")


def get_signal(key):
    return _resolve(store.signals, key, "ERR_SIGNAL_NOT_FOUND", "IssueSignal")


def get_assignment(key):
    return _resolve(store.assignments, key, "ERR_ASSIGNMENT_NOT_FOUND", "TeamAssignment")


def get_statement(key):
    return _resolve(store.statements, key, "ERR_STATEMENT_NOT_FOUND", "Statement")


def get_task(key):
    return _resolve(store.tasks, key, "ERR_APPROVAL_TASK_NOT_FOUND", "ApprovalTask")


def get_notice(key):
    return _resolve(store.notices, key, "ERR_NOTICE_NOT_FOUND", "StakeholderNotice")


def get_material(key):
    return _resolve(store.materials, key, "ERR_MATERIAL_NOT_FOUND", "PreparedMaterial")


def get_interview(key):
    return _resolve(store.interviews, key, "ERR_INTERVIEW_NOT_FOUND", "MediaInterview")


def get_claim(key):
    return _resolve(store.claims, key, "ERR_CLAIM_NOT_FOUND", "MisinformationClaim")


def get_review(key):
    return _resolve(store.reviews, key, "ERR_REVIEW_NOT_FOUND", "PostCrisisReview")
