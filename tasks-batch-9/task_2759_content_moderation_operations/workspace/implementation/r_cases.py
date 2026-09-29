"""Case opening, assignment, decision, escalation and return (PRD §3.4, §3.5)."""

from flask import Blueprint

import ser
from case_ops import create_legal_case, create_queued_case, record_decision, routing_posture
from core import (
    CASE_ORIGINS, CASE_STATUSES, ESCALATION_REASONS, ESCALATION_SLA_MINUTES,
    OUTCOMES, UPPER2, body, created, db, enum_filter, fail, listing, ok,
    opt_id_array, opt_str, paginate_args, req_enum, req_int, req_str, require,
    str_filter, touch,
)
from svc import (
    category_of_case, certification_target, content_of, exposure_charge, find,
    plus_minutes, select_queue, select_reviewer, sla_minutes,
    vet_directed_reviewer,
)
from core import now

bp = Blueprint("cases", __name__)

HAND_OPENED_ORIGINS = ["LEGAL_REQUEST", "MANUAL_REPORT"]


@bp.post("/moderation-cases")
def open_case():
    actor = require("LegalCounsel", "TrustSafetyAdmin")
    payload = body()

    # PRD §2.8 tier 2: the role-scoped restriction on origin precedes
    # well-formedness, so the raw origin is inspected before anything else.
    raw_origin = payload.get("origin")
    if raw_origin == "LEGAL_REQUEST" and actor.role != "LegalCounsel":
        fail("ERR_UNAUTHORIZED", "Only LegalCounsel may open a LEGAL_REQUEST case.")
    if raw_origin == "MANUAL_REPORT" and actor.role != "TrustSafetyAdmin":
        fail("ERR_UNAUTHORIZED", "Only a TrustSafetyAdmin may open a MANUAL_REPORT case.")

    content_item_id = req_str(payload, "content_item_id", 1, None)
    category_code = req_str(payload, "policy_category_code", 1, None)
    origin = req_enum(payload, "origin", HAND_OPENED_ORIGINS)
    legal_jurisdiction = opt_str(payload, "legal_jurisdiction", 1, None)
    if legal_jurisdiction is not None and not UPPER2.match(legal_jurisdiction):
        fail("ERR_INVALID_REQUEST",
             "legal_jurisdiction must be exactly two uppercase letters.")
    legal_reference = opt_str(payload, "legal_reference", 1, None)

    content = find(db.content_items, content_item_id, "ERR_CONTENT_NOT_FOUND")
    category = None
    for candidate in db.policy_categories.values():
        if candidate["code"] == category_code:
            category = candidate
            break
    if category is None:
        fail("ERR_CATEGORY_NOT_FOUND", "No policy category carries this code.")

    if content["visibility_status"] == "REMOVED":
        fail("ERR_CONTENT_NOT_LIVE", "A removed content item cannot take new cases.")
    if category["status"] != "ACTIVE" or not category.get("active_version_id"):
        fail("ERR_NO_ACTIVE_POLICY_VERSION",
             "The resolved category has no ACTIVE policy version.")

    version = db.policy_versions[category["active_version_id"]]
    account = db.accounts[content["account_id"]]

    if origin == "LEGAL_REQUEST" and (legal_jurisdiction is None or legal_reference is None):
        fail("ERR_LEGAL_CASE_REQUIRES_JURISDICTION",
             "A LEGAL_REQUEST case requires legal_jurisdiction and legal_reference.")

    queue = select_queue(category["id"], content["language"])
    if queue is None:
        fail("ERR_NO_ELIGIBLE_QUEUE",
             "No review queue serves this category and language.")

    if origin == "LEGAL_REQUEST":
        case = create_legal_case(content, category, version,
                                 legal_jurisdiction, legal_reference, queue)
    else:
        escalation_tier, escalation_reason = routing_posture(category, account)
        case = create_queued_case(content, category, version, "MANUAL_REPORT", None,
                                  queue, escalation_tier, escalation_reason)
    return created(ser.moderation_case(case))


@bp.post("/moderation-cases/<case_id>/assign")
def assign_case(case_id):
    require("TrustSafetyAdmin", "QAAuditor")
    payload = body()
    expected_case_version = req_int(payload, "expected_case_version", 0, None)
    target_reviewer_id = opt_str(payload, "target_reviewer_id", 1, None)
    exclude_reviewer_ids = opt_id_array(payload, "exclude_reviewer_ids")

    case = find(db.moderation_cases, case_id, "ERR_CASE_NOT_FOUND")
    target = None
    if target_reviewer_id is not None:
        target = find(db.reviewers, target_reviewer_id, "ERR_REVIEWER_NOT_FOUND")
    for excluded in exclude_reviewer_ids:
        find(db.reviewers, excluded, "ERR_REVIEWER_NOT_FOUND")

    if case["status"] == "DECIDED":
        fail("ERR_CASE_ALREADY_DECIDED", "A decided case cannot be assigned.")

    content = content_of(case)
    queue = db.review_queues.get(case.get("queue_id"))
    charge = exposure_charge(content)
    require_senior = case["status"] == "ESCALATED"

    if target is not None:
        vet_directed_reviewer(target, case, queue, charge, require_senior)
        if target["id"] in exclude_reviewer_ids or target["id"] == case.get("assigned_reviewer_id"):
            fail("ERR_NO_ELIGIBLE_REVIEWER",
                 "The named reviewer is excluded from this assignment.")
        chosen = target
    else:
        chosen = select_reviewer(case, queue, charge, exclude_reviewer_ids, require_senior)
        if chosen is None:
            fail("ERR_NO_ELIGIBLE_REVIEWER",
                 "No reviewer satisfies every eligibility predicate.")

    # PRD §2.8 tier 11 / §2.9: optimistic concurrency is evaluated last of all.
    if expected_case_version != case["version"]:
        fail("ERR_STALE_CASE_VERSION",
             "expected_case_version does not match the case's current version.")

    prior_status = case["status"]
    prior_holder_id = case.get("assigned_reviewer_id")

    if prior_status == "PENDING_ASSIGNMENT":
        if queue is not None:
            queue["unassigned_case_count"] = max(0, queue["unassigned_case_count"] - 1)
            touch(queue)
    else:
        case["reassignment_count"] = int(case.get("reassignment_count") or 0) + 1
        if prior_holder_id:
            prior = db.reviewers.get(prior_holder_id)
            if prior is not None:
                prior["open_case_count"] = max(0, prior["open_case_count"] - 1)
                prior["exposure_points_today"] = max(
                    0, prior["exposure_points_today"] - int(case.get("exposure_points_charged") or 0))
                touch(prior)

    case["assigned_reviewer_id"] = chosen["id"]
    case["exposure_points_charged"] = charge
    case["status"] = "ASSIGNED"
    touch(case)

    chosen["open_case_count"] += 1
    chosen["exposure_points_today"] += charge
    touch(chosen)

    return ok(ser.moderation_case(case))


@bp.post("/moderation-cases/<case_id>/decide")
def decide_case(case_id):
    actor = require("Reviewer", "LegalCounsel")

    # PRD §2.8 tier 2: a LegalCounsel decision is only permitted on a case whose
    # escalation_reason is LEGAL_REQUEST, and that restriction outranks
    # well-formedness whenever the case can be resolved at all.
    peek = db.moderation_cases.get(case_id)
    if (actor.role == "LegalCounsel" and peek is not None
            and peek.get("escalation_reason") != "LEGAL_REQUEST"):
        fail("ERR_UNAUTHORIZED",
             "LegalCounsel may only decide a case escalated for LEGAL_REQUEST.")

    payload = body()
    outcome = req_enum(payload, "outcome", OUTCOMES)
    opt_str(payload, "rationale", 0, None)

    case = find(db.moderation_cases, case_id, "ERR_CASE_NOT_FOUND")

    if actor.role == "Reviewer" and case.get("assigned_reviewer_id") != actor.user_id:
        fail("ERR_NOT_CASE_OWNER", "Only the case's assigned reviewer may decide it.")

    if case["status"] == "DECIDED":
        fail("ERR_CASE_ALREADY_DECIDED", "This case has already been decided.")

    if actor.role == "Reviewer":
        if case["status"] != "ASSIGNED":
            fail("ERR_CASE_NOT_ASSIGNED", "Only an ASSIGNED case can be decided.")
        reviewer = db.reviewers.get(actor.user_id)
        if reviewer is None or reviewer["status"] != "ACTIVE":
            fail("ERR_REVIEWER_NOT_ACTIVE", "The deciding reviewer is not ACTIVE.")
        target = certification_target(case)
        if target is None or target not in (reviewer.get("certified_policy_version_ids") or []):
            fail("ERR_REVIEWER_NOT_CERTIFIED",
                 "The deciding reviewer is not certified on the governing policy version.")
        record_decision(case, outcome, "HUMAN", reviewer["id"])
    else:
        if case["status"] != "ESCALATED":
            fail("ERR_CASE_NOT_ASSIGNED",
                 "A legal decision requires the case to be ESCALATED.")
        record_decision(case, outcome, "LEGAL", None)

    return ok(ser.moderation_case(case))


@bp.post("/moderation-cases/<case_id>/escalate")
def escalate_case(case_id):
    actor = require("Reviewer", "QAAuditor")
    payload = body()
    escalation_reason = req_enum(payload, "escalation_reason", ESCALATION_REASONS)

    case = find(db.moderation_cases, case_id, "ERR_CASE_NOT_FOUND")

    if case.get("assigned_reviewer_id") != actor.user_id:
        fail("ERR_NOT_CASE_OWNER", "Only the case's assigned reviewer may escalate it.")
    if case["status"] == "DECIDED":
        fail("ERR_CASE_ALREADY_DECIDED", "A decided case cannot be escalated.")
    if case["status"] != "ASSIGNED":
        fail("ERR_INVALID_CASE_TRANSITION", "Only an ASSIGNED case can be escalated.")

    reviewer = db.reviewers.get(actor.user_id)
    if reviewer is None or reviewer["status"] != "ACTIVE":
        fail("ERR_REVIEWER_NOT_ACTIVE", "The escalating reviewer is not ACTIVE.")

    case["escalation_reason"] = escalation_reason
    case["escalation_tier"] = 2
    case["assigned_reviewer_id"] = None
    # The case leaves undecided, so both workload and exposure are conserved.
    reviewer["open_case_count"] = max(0, reviewer["open_case_count"] - 1)
    reviewer["exposure_points_today"] = max(
        0, reviewer["exposure_points_today"] - int(case.get("exposure_points_charged") or 0))
    touch(reviewer)
    case["status"] = "ESCALATED"
    case["sla_due_at"] = plus_minutes(now(), ESCALATION_SLA_MINUTES)
    touch(case)
    return ok(ser.moderation_case(case))


@bp.post("/moderation-cases/<case_id>/return-to-queue")
def return_case_to_queue(case_id):
    require("QAAuditor", "TrustSafetyAdmin")
    payload = body()
    opt_str(payload, "reason", 0, None)

    case = find(db.moderation_cases, case_id, "ERR_CASE_NOT_FOUND")
    if case["status"] == "DECIDED":
        fail("ERR_CASE_ALREADY_DECIDED", "A decided case cannot be returned to queue.")
    if case["status"] != "ESCALATED":
        fail("ERR_INVALID_CASE_TRANSITION",
             "Only an ESCALATED case can be returned to its queue.")

    case["status"] = "PENDING_ASSIGNMENT"
    # escalation_reason is retained as history rather than cleared.
    case["escalation_tier"] = 1

    queue = db.review_queues.get(case.get("queue_id"))
    if queue is not None:
        # Only unassigned_case_count rises: the case has been counted as open
        # continuously since it was created (PRD §3.3).
        queue["unassigned_case_count"] += 1
        touch(queue)
        version = db.policy_versions.get(case.get("policy_version_id"))
        category = category_of_case(case)
        if version is not None and category is not None:
            case["sla_due_at"] = plus_minutes(now(), sla_minutes(queue, version, category))
    touch(case)
    return ok(ser.moderation_case(case))


@bp.get("/moderation-cases/<case_id>")
def get_case(case_id):
    require("TrustSafetyAdmin", "PolicyManager", "QAAuditor", "Reviewer", "LegalCounsel")
    record = find(db.moderation_cases, case_id, "ERR_CASE_NOT_FOUND")
    return ok(ser.moderation_case(record))


@bp.get("/moderation-cases")
def list_cases():
    require("TrustSafetyAdmin", "PolicyManager", "QAAuditor", "Reviewer", "LegalCounsel")
    limit, offset = paginate_args()
    filters = {
        "content_item_id": str_filter("content_item_id"),
        "detection_signal_id": str_filter("detection_signal_id"),
        "policy_version_id": str_filter("policy_version_id"),
        "queue_id": str_filter("queue_id"),
        "assigned_reviewer_id": str_filter("assigned_reviewer_id"),
        "decided_by_reviewer_id": str_filter("decided_by_reviewer_id"),
        "status": enum_filter("status", CASE_STATUSES),
        "origin": enum_filter("origin", CASE_ORIGINS),
    }
    records = []
    for record in db.moderation_cases.values():
        if any(value is not None and record.get(field) != value
               for field, value in filters.items()):
            continue
        records.append(record)
    return listing(records, limit, offset, ser.moderation_case)
