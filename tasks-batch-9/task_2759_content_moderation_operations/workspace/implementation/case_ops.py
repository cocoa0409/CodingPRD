"""ModerationCase creation and the decision cascade (PRD §3.3, §3.5)."""

from core import (
    ESCALATION_SLA_MINUTES, LEGAL_SLA_MINUTES, base_fields, db, now, now_iso,
    parse_iso, touch,
)
from svc import (
    account_of_case, content_of, plus_minutes, recompute_account, select_queue,
    sla_minutes, strike_points_applied,
)


def _blank_case(content, version, origin, detection_signal_id):
    case = {
        "content_item_id": content["id"],
        "detection_signal_id": detection_signal_id,
        "policy_version_id": version["id"] if version else None,
        "queue_id": None,
        "assigned_reviewer_id": None,
        "decided_by_reviewer_id": None,
        "origin": origin,
        "escalation_reason": None,
        "escalation_tier": 0,
        "legal_jurisdiction": None,
        "legal_reference": None,
        "sla_due_at": None,
        "sla_breached": False,
        "decision_outcome": None,
        "decision_source": None,
        "decided_at": None,
        "strike_points_applied": 0,
        "is_overturned": False,
        "appeal_deadline_at": None,
        "exposure_points_charged": 0,
        "requires_recertified_review": False,
        "reassignment_count": 0,
        "status": "PENDING_ASSIGNMENT",
    }
    base_fields(case)
    return case


def routing_posture(category, account):
    """escalation_tier / escalation_reason as fixed by calculations.routing_disposition."""
    if category["severity_tier"] == "T1":
        return 1, "IMMINENT_HARM"
    if account["tier"] in ("HIGH_PROFILE", "GOVERNMENT"):
        return 1, "HIGH_PROFILE"
    return 0, None


def create_queued_case(content, category, version, origin, detection_signal_id,
                       queue, escalation_tier, escalation_reason):
    """A human-review case: PENDING_ASSIGNMENT, both queue counters incremented
    BEFORE the SLA congestion read (PRD §3.3 steps 1-5)."""
    case = _blank_case(content, version, origin, detection_signal_id)
    case["status"] = "PENDING_ASSIGNMENT"
    case["queue_id"] = queue["id"]
    case["escalation_tier"] = escalation_tier
    case["escalation_reason"] = escalation_reason

    # step 1
    queue["open_case_count"] += 1
    queue["unassigned_case_count"] += 1
    touch(queue)

    if escalation_tier >= 1:
        case["sla_due_at"] = plus_minutes(now(), ESCALATION_SLA_MINUTES)
    else:
        case["sla_due_at"] = plus_minutes(now(), sla_minutes(queue, version, category))

    content["review_status"] = "UNDER_REVIEW"
    content["open_case_count"] += 1
    touch(content)

    db.moderation_cases[case["id"]] = case
    return case


def create_legal_case(content, category, version, jurisdiction, reference, queue):
    """A LEGAL_REQUEST case opens directly in ESCALATED at escalation_tier 2; the
    queue's open_case_count rises but unassigned_case_count does NOT."""
    case = _blank_case(content, version, "LEGAL_REQUEST", None)
    case["status"] = "ESCALATED"
    case["queue_id"] = queue["id"]
    case["escalation_reason"] = "LEGAL_REQUEST"
    case["escalation_tier"] = 2
    case["legal_jurisdiction"] = jurisdiction
    case["legal_reference"] = reference

    queue["open_case_count"] += 1
    touch(queue)

    case["sla_due_at"] = plus_minutes(now(), LEGAL_SLA_MINUTES)

    content["review_status"] = "UNDER_REVIEW"
    content["open_case_count"] += 1
    touch(content)

    db.moderation_cases[case["id"]] = case
    return case


def apply_enforcement_to_content(content, outcome):
    if outcome == "REMOVE":
        content["visibility_status"] = "REMOVED"
    elif outcome == "AGE_GATE":
        content["visibility_status"] = "AGE_GATED"
    # WARN and NO_ACTION leave visibility_status exactly as it is.


def create_auto_action_case(content, category, version, detection_signal_id):
    """An AUTO_ACTION signal mints a case born in DECIDED (PRD §3.3)."""
    case = _blank_case(content, version, "CLASSIFIER", detection_signal_id)
    case["status"] = "DECIDED"
    case["queue_id"] = None
    case["decision_source"] = "AUTO"
    case["decision_outcome"] = version["enforcement_action"]
    case["decided_at"] = now_iso()
    case["sla_breached"] = False

    account = db.accounts[content["account_id"]]
    case["strike_points_applied"] = strike_points_applied(
        category, case["decision_outcome"], account["lifetime_removed_count"])
    case["appeal_deadline_at"] = plus_minutes(
        now(), int(version["appeal_window_hours"]) * 60)

    apply_enforcement_to_content(content, case["decision_outcome"])
    content["review_status"] = "ACTIONED"
    touch(content)

    db.moderation_cases[case["id"]] = case
    recompute_account(account)
    return case


def record_decision(case, outcome, source, decider_id):
    """The shared ASSIGNED->DECIDED / ESCALATED->DECIDED cascade (PRD §3.5)."""
    category = None
    version = db.policy_versions.get(case.get("policy_version_id"))
    if version is not None:
        category = db.policy_categories.get(version["policy_category_id"])
    content = content_of(case)
    account = db.accounts.get(content["account_id"])

    case["decision_source"] = source
    case["decided_by_reviewer_id"] = decider_id
    case["decided_at"] = now_iso()
    due = parse_iso(case.get("sla_due_at")) if case.get("sla_due_at") else None
    case["sla_breached"] = bool(due is not None and now() > due)
    case["decision_outcome"] = outcome
    case["strike_points_applied"] = strike_points_applied(
        category, outcome, account["lifetime_removed_count"])
    case["appeal_deadline_at"] = plus_minutes(
        now(), int(version["appeal_window_hours"]) * 60)
    case["status"] = "DECIDED"

    holder_id = case.get("assigned_reviewer_id")
    if holder_id:
        holder = db.reviewers.get(holder_id)
        if holder is not None:
            holder["open_case_count"] = max(0, holder["open_case_count"] - 1)
            # exposure_points_today is deliberately NOT refunded.
            touch(holder)

    queue = db.review_queues.get(case.get("queue_id"))
    if queue is not None:
        queue["open_case_count"] = max(0, queue["open_case_count"] - 1)
        touch(queue)

    apply_enforcement_to_content(content, outcome)
    content["review_status"] = "CLEAR" if outcome == "NO_ACTION" else "ACTIONED"
    content["open_case_count"] = max(0, content["open_case_count"] - 1)
    touch(content)

    touch(case)
    recompute_account(account)
    return case
