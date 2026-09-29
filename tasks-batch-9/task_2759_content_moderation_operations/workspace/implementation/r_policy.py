"""Policy taxonomy and versioned enforcement rules (PRD §3.2)."""

from flask import Blueprint, g

import ser
from core import (
    CATEGORY_CODE, CATEGORY_STATUSES, ENFORCEMENT_ACTIONS,
    MAX_BACKTEST_DIVERGENCE, POLICY_VERSION_STATUSES, SEVERITY_TIERS,
    SPECIALTIES, base_fields, body, created, db, div4, enum_filter, fail,
    listing, now_iso, ok, opt_bool, opt_enum, opt_int, opt_num, opt_str,
    paginate_args, present, req_enum, req_num, req_str, require, round4,
    str_filter, touch,
)
from svc import find, sort_key

bp = Blueprint("policy", __name__)

SEVERITY_RANK = {"T1": 1, "T2": 2, "T3": 3, "T4": 4}


@bp.post("/policy-categories")
def create_category():
    require("PolicyManager")
    payload = body()
    code = req_str(payload, "code", 3, 40)
    if not CATEGORY_CODE.match(code):
        fail("ERR_INVALID_REQUEST",
             "code must be 3..40 uppercase letters and underscores beginning with a letter.")
    name = req_str(payload, "name", 1, 120)
    severity_tier = req_enum(payload, "severity_tier", SEVERITY_TIERS)
    specialty = req_enum(payload, "specialty", SPECIALTIES)
    parent_id = opt_str(payload, "parent_category_id", 1, None)

    parent = None
    if parent_id is not None:
        parent = find(db.policy_categories, parent_id, "ERR_CATEGORY_NOT_FOUND")

    # PRD §2.8 tier 10 fixes the inner order of the business rules:
    # ERR_CHILD_SEVERITY_EXCEEDS_PARENT is evaluated before "the uniqueness and
    # clock rules ERR_DUPLICATE_CATEGORY_CODE, ERR_DUPLICATE_HANDLE and
    # ERR_CLOCK_NOT_MONOTONIC", so severity outranks the code collision.
    if parent is not None and SEVERITY_RANK[severity_tier] < SEVERITY_RANK[parent["severity_tier"]]:
        fail("ERR_CHILD_SEVERITY_EXCEEDS_PARENT",
             "A child category may not be more severe than its parent.")

    for existing in db.policy_categories.values():
        if existing["code"] == code:
            fail("ERR_DUPLICATE_CATEGORY_CODE", "A category with this code already exists.")

    record = {
        "code": code,
        "name": name,
        "parent_category_id": parent_id,
        "severity_tier": severity_tier,
        "specialty": specialty,
        "status": "DRAFT",
        "active_version_id": None,
    }
    base_fields(record)
    db.policy_categories[record["id"]] = record
    return created(ser.policy_category(record))


@bp.get("/policy-categories/<category_id>")
def get_category(category_id):
    require("TrustSafetyAdmin", "PolicyManager", "QAAuditor", "Reviewer", "LegalCounsel")
    record = find(db.policy_categories, category_id, "ERR_CATEGORY_NOT_FOUND")
    return ok(ser.policy_category(record))


@bp.get("/policy-categories")
def list_categories():
    require("TrustSafetyAdmin", "PolicyManager", "QAAuditor", "Reviewer", "LegalCounsel")
    limit, offset = paginate_args()
    parent_id = str_filter("parent_category_id")
    status = enum_filter("status", CATEGORY_STATUSES)
    specialty = enum_filter("specialty", SPECIALTIES)
    records = []
    for record in db.policy_categories.values():
        if parent_id is not None and record["parent_category_id"] != parent_id:
            continue
        if status is not None and record["status"] != status:
            continue
        if specialty is not None and record["specialty"] != specialty:
            continue
        records.append(record)
    return listing(records, limit, offset, ser.policy_category)


@bp.post("/policy-versions")
def create_version():
    actor = require("PolicyManager")
    payload = body()
    category_id = req_str(payload, "policy_category_id", 1, None)
    version_label = req_str(payload, "version_label", 1, 16)
    auto_action_threshold = req_num(payload, "auto_action_threshold", 0, 1)
    review_floor = req_num(payload, "review_floor", 0, 1)
    enforcement_action = req_enum(payload, "enforcement_action", ENFORCEMENT_ACTIONS)
    appeal_window_hours = opt_int(payload, "appeal_window_hours", 1, 8760, 72)
    review_sla_minutes = opt_int(payload, "review_sla_minutes", 5, 10080, 240)
    requires_recertification = opt_bool(payload, "requires_recertification", True)

    find(db.policy_categories, category_id, "ERR_CATEGORY_NOT_FOUND")

    if review_floor > auto_action_threshold:
        fail("ERR_THRESHOLD_ORDER_INVALID",
             "review_floor must be less than or equal to auto_action_threshold.")

    record = {
        "policy_category_id": category_id,
        "supersedes_version_id": None,
        "version_label": version_label,
        "auto_action_threshold": round4(auto_action_threshold),
        "review_floor": round4(review_floor),
        "enforcement_action": enforcement_action,
        "appeal_window_hours": appeal_window_hours,
        "review_sla_minutes": review_sla_minutes,
        "requires_recertification": requires_recertification,
        "backtest_sample_size": 0,
        "backtest_divergence_rate": None,
        "backtest_completed_at": None,
        "authored_by_user_id": actor.user_id,
        "activated_by_user_id": None,
        "activated_at": None,
        "status": "DRAFT",
    }
    base_fields(record)
    db.policy_versions[record["id"]] = record
    return created(ser.policy_version(record))


@bp.post("/policy-versions/<version_id>/back-test")
def back_test(version_id):
    require("PolicyManager")
    version = find(db.policy_versions, version_id, "ERR_POLICY_VERSION_NOT_FOUND")
    if version["status"] != "DRAFT":
        fail("ERR_POLICY_VERSION_NOT_DRAFT", "Only a DRAFT version can be back-tested.")

    category = db.policy_categories.get(version["policy_category_id"])
    baseline_id = category.get("active_version_id") if category else None
    sample = []
    if baseline_id is not None:
        sample = [mc for mc in db.moderation_cases.values()
                  if mc.get("policy_version_id") == baseline_id
                  and mc["status"] == "DECIDED"
                  and mc.get("detection_signal_id")]
        sample.sort(key=sort_key)

    divergent = 0
    for case in sample:
        historical = "AUTO_ACTION" if case.get("decision_source") == "AUTO" else "HUMAN_REVIEW"
        signal = db.detection_signals.get(case["detection_signal_id"])
        confidence = signal["effective_confidence"]
        content = db.content_items.get(case["content_item_id"])
        account = db.accounts.get(content["account_id"]) if content else None
        if confidence < version["review_floor"]:
            predicted = "DISCARDED"
        elif category["severity_tier"] == "T1":
            predicted = "HUMAN_REVIEW"
        elif account is not None and account["tier"] != "STANDARD":
            predicted = "HUMAN_REVIEW"
        elif confidence >= version["auto_action_threshold"]:
            predicted = "AUTO_ACTION"
        else:
            predicted = "HUMAN_REVIEW"
        if predicted != historical:
            divergent += 1

    version["backtest_sample_size"] = len(sample)
    version["backtest_divergence_rate"] = (
        div4(divergent, len(sample)) if sample else round4(0)
    )
    version["backtest_completed_at"] = now_iso()
    version["status"] = "BACKTESTING"
    touch(version)
    return ok(ser.policy_version(version))


@bp.post("/policy-versions/<version_id>/revise")
def revise(version_id):
    require("PolicyManager")
    payload = body()
    auto_action_threshold = opt_num(payload, "auto_action_threshold", 0, 1)
    review_floor = opt_num(payload, "review_floor", 0, 1)
    review_sla_minutes = opt_int(payload, "review_sla_minutes", 5, 10080)
    appeal_window_hours = opt_int(payload, "appeal_window_hours", 1, 8760)
    requires_recertification = (
        opt_bool(payload, "requires_recertification") if present(payload, "requires_recertification")
        else None
    )

    version = find(db.policy_versions, version_id, "ERR_POLICY_VERSION_NOT_FOUND")
    if version["status"] != "BACKTESTING":
        fail("ERR_POLICY_VERSION_NOT_DRAFT", "Only a BACKTESTING version can be revised.")

    new_ceiling = version["auto_action_threshold"] if auto_action_threshold is None \
        else round4(auto_action_threshold)
    new_floor = version["review_floor"] if review_floor is None else round4(review_floor)
    if new_floor > new_ceiling:
        fail("ERR_THRESHOLD_ORDER_INVALID",
             "review_floor must be less than or equal to auto_action_threshold.")

    version["auto_action_threshold"] = new_ceiling
    version["review_floor"] = new_floor
    if review_sla_minutes is not None:
        version["review_sla_minutes"] = review_sla_minutes
    if appeal_window_hours is not None:
        version["appeal_window_hours"] = appeal_window_hours
    if requires_recertification is not None:
        version["requires_recertification"] = requires_recertification
    version["backtest_sample_size"] = 0
    version["backtest_divergence_rate"] = None
    version["backtest_completed_at"] = None
    version["status"] = "DRAFT"
    touch(version)
    return ok(ser.policy_version(version))


@bp.post("/policy-versions/<version_id>/activate")
def activate(version_id):
    actor = require("PolicyManager")
    version = find(db.policy_versions, version_id, "ERR_POLICY_VERSION_NOT_FOUND")

    # PRD §2.8: segregation of duties (tier 8) is evaluated before lifecycle state.
    if actor.user_id == version.get("authored_by_user_id"):
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The activating manager must differ from the version's author.")
    if version["status"] != "BACKTESTING" or version.get("backtest_divergence_rate") is None:
        fail("ERR_POLICY_VERSION_NOT_BACKTESTED",
             "Only a back-tested BACKTESTING version can be activated.")
    if version["backtest_divergence_rate"] > MAX_BACKTEST_DIVERGENCE:
        fail("ERR_BACKTEST_DIVERGENCE_EXCEEDED",
             "The recorded back-test divergence exceeds 0.2500.")

    category = db.policy_categories[version["policy_category_id"]]
    superseded_id = category.get("active_version_id")

    version["status"] = "ACTIVE"
    version["activated_by_user_id"] = actor.user_id
    version["activated_at"] = now_iso()
    version["supersedes_version_id"] = superseded_id
    touch(version)

    # Cascade 1: the category's prior ACTIVE version moves to SUPERSEDED.
    if superseded_id is not None:
        prior = db.policy_versions.get(superseded_id)
        if prior is not None:
            prior["status"] = "SUPERSEDED"
            touch(prior)

    decertified_ids = set()
    if version["requires_recertification"] and superseded_id is not None:
        # Cascade 2: decertify and enrol in retraining on the NEW version's id.
        for reviewer in sorted(db.reviewers.values(), key=sort_key):
            certified = reviewer.get("certified_policy_version_ids") or []
            if superseded_id not in certified:
                continue
            reviewer["certified_policy_version_ids"] = [
                vid for vid in certified if vid != superseded_id]
            pending = reviewer.get("pending_retraining_version_ids") or []
            if version["id"] not in pending:
                pending = pending + [version["id"]]
            reviewer["pending_retraining_version_ids"] = pending
            decertified_ids.add(reviewer["id"])
            touch(reviewer)

        # Cascade 3: flag the live cases that now need a recertified decider.
        for case in sorted(db.moderation_cases.values(), key=sort_key):
            flag = False
            if case["status"] == "ASSIGNED" and case.get("assigned_reviewer_id") in decertified_ids:
                flag = True
            if (case.get("policy_version_id") == superseded_id
                    and case["status"] in ("ASSIGNED", "PENDING_ASSIGNMENT")):
                flag = True
            if flag and not case.get("requires_recertified_review"):
                case["requires_recertified_review"] = True
                touch(case)

    # Cascade 4: repoint the parent category and bubble its status up.
    category["active_version_id"] = version["id"]
    if category["status"] == "DRAFT":
        category["status"] = "ACTIVE"
    touch(category)

    return ok(ser.policy_version(version))


@bp.get("/policy-versions/<version_id>")
def get_version(version_id):
    require("TrustSafetyAdmin", "PolicyManager", "QAAuditor", "Reviewer", "LegalCounsel")
    record = find(db.policy_versions, version_id, "ERR_POLICY_VERSION_NOT_FOUND")
    return ok(ser.policy_version(record))


@bp.get("/policy-versions")
def list_versions():
    require("TrustSafetyAdmin", "PolicyManager", "QAAuditor", "Reviewer", "LegalCounsel")
    limit, offset = paginate_args()
    category_id = str_filter("policy_category_id")
    supersedes = str_filter("supersedes_version_id")
    status = enum_filter("status", POLICY_VERSION_STATUSES)
    records = []
    for record in db.policy_versions.values():
        if category_id is not None and record["policy_category_id"] != category_id:
            continue
        if supersedes is not None and record["supersedes_version_id"] != supersedes:
            continue
        if status is not None and record["status"] != status:
            continue
        records.append(record)
    return listing(records, limit, offset, ser.policy_version)
