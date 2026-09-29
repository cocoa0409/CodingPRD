"""Classifier signals: effective confidence, routing and case minting (PRD §3.3)."""

from flask import Blueprint

import ser
from case_ops import create_auto_action_case, create_queued_case, routing_posture
from core import (
    REPEAT_BONUS_CAP_POINTS, REPEAT_BONUS_PER_POINT, TIER_CONFIDENCE_MULTIPLIER,
    base_fields, body, created, db, dec, fail, now_iso, ok, req_num, req_str,
    require, round4,
)
from svc import find, select_queue


def effective_confidence(raw_confidence, account):
    """calculations.effective_confidence: dampen by tier, add the repeat bonus,
    clamp at 1.0, and only then round half up to four places -- exactly once."""
    multiplier = TIER_CONFIDENCE_MULTIPLIER[account["tier"]]
    bonus = REPEAT_BONUS_PER_POINT * dec(
        min(int(account["strike_points"]), REPEAT_BONUS_CAP_POINTS))
    value = dec(raw_confidence) * multiplier + bonus
    if value > dec(1):
        value = dec(1)
    return round4(value)


def routing_disposition(confidence, category, account, version):
    if confidence < version["review_floor"]:
        return "DISCARDED"
    if category["severity_tier"] == "T1":
        return "HUMAN_REVIEW"
    if account["tier"] != "STANDARD":
        return "HUMAN_REVIEW"
    if confidence >= version["auto_action_threshold"]:
        return "AUTO_ACTION"
    return "HUMAN_REVIEW"


bp = Blueprint("detection", __name__)


@bp.post("/detection-signals")
def submit_signal():
    require("TrustSafetyAdmin")
    payload = body()
    content_item_id = req_str(payload, "content_item_id", 1, None)
    category_code = req_str(payload, "policy_category_code", 1, None)
    classifier_id = req_str(payload, "classifier_id", 1, 40)
    classifier_confidence = req_num(payload, "classifier_confidence", 0, 1)

    content = find(db.content_items, content_item_id, "ERR_CONTENT_NOT_FOUND")
    category = None
    for candidate in db.policy_categories.values():
        if candidate["code"] == category_code:
            category = candidate
            break
    if category is None:
        fail("ERR_CATEGORY_NOT_FOUND", "No policy category carries this code.")

    if content["visibility_status"] == "REMOVED":
        fail("ERR_CONTENT_NOT_LIVE", "Removed content cannot be scanned again.")
    if category["status"] != "ACTIVE" or not category.get("active_version_id"):
        fail("ERR_NO_ACTIVE_POLICY_VERSION",
             "The resolved category has no ACTIVE policy version.")

    version = db.policy_versions[category["active_version_id"]]
    account = db.accounts[content["account_id"]]

    confidence = effective_confidence(classifier_confidence, account)
    disposition = routing_disposition(confidence, category, account, version)

    escalation_tier, escalation_reason = 0, None
    queue = None
    if disposition == "HUMAN_REVIEW":
        escalation_tier, escalation_reason = routing_posture(category, account)
        queue = select_queue(category["id"], content["language"])
        if queue is None:
            # Nothing is persisted -- not even the signal row (PRD §2.7, §3.3).
            fail("ERR_NO_ELIGIBLE_QUEUE",
                 "No review queue serves this category and language.")

    signal = {
        "content_item_id": content_item_id,
        "policy_category_code": category_code,
        "classifier_id": classifier_id,
        "classifier_confidence": round4(classifier_confidence),
        "effective_confidence": confidence,
        "disposition": disposition,
        "resulting_case_id": None,
        "pinned_policy_version_label": None,
    }
    base_fields(signal)
    signal["created_at"] = now_iso()
    db.detection_signals[signal["id"]] = signal

    if disposition == "AUTO_ACTION":
        case = create_auto_action_case(content, category, version, signal["id"])
        signal["resulting_case_id"] = case["id"]
        signal["pinned_policy_version_label"] = version["version_label"]
    elif disposition == "HUMAN_REVIEW":
        case = create_queued_case(content, category, version, "CLASSIFIER",
                                  signal["id"], queue, escalation_tier,
                                  escalation_reason)
        signal["resulting_case_id"] = case["id"]
        signal["pinned_policy_version_label"] = version["version_label"]

    return created(ser.detection_signal(signal))


@bp.get("/detection-signals/<signal_id>")
def get_signal(signal_id):
    require("TrustSafetyAdmin", "PolicyManager", "QAAuditor", "Reviewer")
    record = find(db.detection_signals, signal_id, "ERR_DETECTION_SIGNAL_NOT_FOUND")
    return ok(ser.detection_signal(record))
