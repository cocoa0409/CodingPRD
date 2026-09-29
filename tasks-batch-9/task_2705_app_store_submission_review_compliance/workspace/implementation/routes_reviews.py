"""Behaviour findings, rejection reasons, appeals, expedites and capacity."""
from decimal import Decimal

from flask import Blueprint, g

import calc
import flows
from common import (APPEAL_WINDOW_DAYS, EXPEDITE_STANDING_FLOOR,
                    POOL_MAX_CONCURRENT_SLOTS, arg_bool, arg_filter, body_json,
                    d2, days, endpoint, fail, fmt_iso, get_row, jsonable,
                    new_row, now_dt, now_iso, ok, paginate, parse_iso, public,
                    resolve, rows, scope_rows, touch)
from valid import (check_unknown, opt_array, opt_str, req_array, req_bool,
                   req_id, req_int, req_iso, req_num, req_str)

bp = Blueprint("reviews", __name__)

DATA_TYPES = {"PRECISE_LOCATION", "CONTACTS", "DEVICE_ID", "EMAIL",
              "PURCHASE_HISTORY", "HEALTH", "USAGE_DATA"}
PURPOSES = {"ANALYTICS", "ADVERTISING", "APP_FUNCTIONALITY", "PERSONALIZATION",
            "THIRD_PARTY_SHARING"}
SEVERITIES = {"CRITICAL", "MAJOR", "MINOR"}
APPEAL_TYPES = {"GUIDELINE_INTERPRETATION", "FACTUAL_ERROR"}
JUSTIFICATION_CATEGORIES = {"CRITICAL_BUG", "SECURITY_FIX",
                            "TIME_SENSITIVE_EVENT"}
PLATFORMS = {"IOS", "ANDROID"}
FINDING_READ_ROLES = ["PublisherAdmin", "ReleaseManager", "ComplianceOfficer",
                      "PlatformReviewer", "PlatformPolicyAdmin", "Auditor"]
REASON_READ_ROLES = ["PublisherAdmin", "ReleaseManager", "ComplianceOfficer",
                     "PlatformReviewer", "PlatformAppealBoard",
                     "PlatformPolicyAdmin", "Auditor"]
EXPEDITE_READ_ROLES = ["PublisherAdmin", "ReleaseManager", "ComplianceOfficer",
                       "PlatformAppealBoard", "PlatformPolicyAdmin", "Auditor"]
WINDOW_ROLES = ["PlatformPolicyAdmin", "PlatformReviewer", "Auditor",
                "ReleaseManager"]


def _rescore(submission):
    calc.recompute_provisional_score(submission, bump=False)
    calc.recompute_final_score(submission, bump=False)
    touch(submission)


# --------------------------------------------------------------------------
# BehaviorFinding
# --------------------------------------------------------------------------
@bp.route("/behavior-findings", methods=["POST"])
@endpoint(["PlatformPolicyAdmin"])
def create_finding():
    body = body_json()
    check_unknown(body, {"submission_id", "data_type", "observed_purpose",
                         "observed_linked_to_user", "observed_tracking",
                         "endpoint_domain", "severity", "scanner_confidence",
                         "detected_at"})
    (submission,) = resolve([("submission", body.get("submission_id"))])
    req_id(body, "submission_id")
    data_type = req_str(body, "data_type", enum=DATA_TYPES)
    observed_purpose = req_str(body, "observed_purpose", enum=PURPOSES)
    linked = req_bool(body, "observed_linked_to_user")
    tracking = req_bool(body, "observed_tracking")
    endpoint_domain = req_str(body, "endpoint_domain", 1, 200)
    severity = req_str(body, "severity", enum=SEVERITIES)
    confidence = req_num(body, "scanner_confidence", 0, 1)
    detected_at = req_iso(body, "detected_at")
    row = new_row("behavior_finding", {
        "submission_id": submission["id"],
        "data_type": data_type,
        "observed_purpose": observed_purpose,
        "observed_linked_to_user": linked,
        "observed_tracking": tracking,
        "endpoint_domain": endpoint_domain,
        "severity": severity,
        "scanner_confidence": calc.d4(confidence),
        "detected_at": fmt_iso(detected_at),
        "status": "OPEN",
        "triaged_by_user_id": None,
        "triage_justification": None,
        "triaged_at": None,
    })
    # Filing a finding is a finding mutation, so it rewrites the provisional score only;
    # the final variant moves at the claim and again at the decision gate.
    calc.recompute_provisional_score(submission, bump=False)
    touch(submission)
    if severity == "CRITICAL":
        app = get_row("app_record", submission["app_record_id"])
        if app is not None:
            calc.recompute_app_posture(app)
    return ok(public(row), 201)


@bp.route("/behavior-findings", methods=["GET"])
@endpoint(FINDING_READ_ROLES)
def list_findings():
    items = rows("behavior_finding")
    for field in ("submission_id", "data_type", "status", "severity"):
        wanted = arg_filter(field)
        if wanted is not None:
            items = [r for r in items if r.get(field) == wanted]
    tracking = arg_bool("observed_tracking")
    if tracking is not None:
        items = [r for r in items if bool(r["observed_tracking"]) is tracking]
    return paginate(scope_rows(items))


@bp.route("/behavior-findings/<finding_id>", methods=["GET"])
@endpoint(FINDING_READ_ROLES)
def read_finding(finding_id):
    (finding,) = resolve([("behavior_finding", finding_id)])
    return ok(public(finding))


@bp.route("/behavior-findings/<finding_id>/triage", methods=["POST"])
@endpoint(["ComplianceOfficer", "PlatformPolicyAdmin"])
def triage_finding(finding_id):
    (finding,) = resolve([("behavior_finding", finding_id)])
    body = body_json()
    check_unknown(body, {"action", "justification"})
    action = req_str(body, "action", enum={"DISPUTE", "RECONCILE", "DISMISS"})
    justification = opt_str(body, "justification", 1, 1000)
    if action == "DISPUTE" and g.role != "ComplianceOfficer":
        fail("ERR_ROLE_NOT_PERMITTED", "only a ComplianceOfficer may dispute")
    if action in ("RECONCILE", "DISMISS") and g.role != "PlatformPolicyAdmin":
        fail("ERR_ROLE_NOT_PERMITTED",
             "only a PlatformPolicyAdmin may reconcile or dismiss")
    allowed = {"DISPUTE": ("OPEN",),
               "RECONCILE": ("OPEN", "DISPUTED"),
               "DISMISS": ("OPEN", "DISPUTED")}[action]
    if finding["status"] not in allowed:
        fail("ERR_INVALID_FINDING_STATE",
             "action %s is not declared for status %s" % (action, finding["status"]))
    submission = get_row("submission", finding["submission_id"])
    if action == "RECONCILE":
        declared = submission.get("declared_privacy_items") or []
        if not calc._matched(declared, finding):
            fail("ERR_DISCLOSURE_STILL_MISSING",
                 "declared_privacy_items still lacks a matching tuple")
        finding["status"] = "RECONCILED"
    elif action == "DISMISS":
        if finding["severity"] == "CRITICAL":
            fail("ERR_WAIVER_NOT_PERMITTED",
                 "a CRITICAL finding may never be dismissed")
        finding["status"] = "DISMISSED"
    else:
        finding["status"] = "DISPUTED"
    finding["triaged_by_user_id"] = g.user_id
    finding["triage_justification"] = justification
    finding["triaged_at"] = now_iso()
    touch(finding)
    _rescore(submission)
    if finding["severity"] == "CRITICAL":
        app = get_row("app_record", submission["app_record_id"])
        if app is not None:
            calc.recompute_app_posture(app)
    return ok(public(finding))


# --------------------------------------------------------------------------
# RejectionReason
# --------------------------------------------------------------------------
@bp.route("/rejection-reasons", methods=["GET"])
@endpoint(REASON_READ_ROLES)
def list_reasons():
    items = rows("rejection_reason")
    for field in ("submission_id", "guideline_rule_id", "severity",
                  "disposition", "appeal_disposition", "reason_code"):
        wanted = arg_filter(field)
        if wanted is not None:
            items = [r for r in items if r.get(field) == wanted]
    return paginate(scope_rows(items))


@bp.route("/rejection-reasons/<reason_id>", methods=["GET"])
@endpoint(REASON_READ_ROLES)
def read_reason(reason_id):
    (reason,) = resolve([("rejection_reason", reason_id)])
    return ok(public(reason))


@bp.route("/rejection-reasons/<reason_id>/response", methods=["POST"])
@endpoint(["ComplianceOfficer"])
def respond_to_reason(reason_id):
    (reason,) = resolve([("rejection_reason", reason_id)])
    body = body_json()
    check_unknown(body, {"disposition", "developer_response"})
    disposition = req_str(body, "disposition", enum={"ACCEPTED", "CONTESTED"})
    developer_response = req_str(body, "developer_response", 1, 2000)
    submission = get_row("submission", reason["submission_id"])
    if submission is None or submission["state"] not in ("REJECTED",
                                                         "METADATA_REJECTED"):
        fail("ERR_INVALID_SUBMISSION_STATE",
             "the submission is not awaiting a rejection response")
    reason["disposition"] = disposition
    reason["developer_response"] = developer_response
    touch(reason)
    return ok(public(reason))


# --------------------------------------------------------------------------
# AppealRequest
# --------------------------------------------------------------------------
def _live_appeal(submission_id, exclude_id=None):
    for appeal in rows("appeal_request"):
        if appeal["submission_id"] != submission_id:
            continue
        if exclude_id is not None and appeal["id"] == exclude_id:
            continue
        if appeal["state"] in ("SUBMITTED", "BOARD_REVIEW"):
            return appeal
    return None


@bp.route("/appeal-requests", methods=["POST"])
@endpoint(["ComplianceOfficer"])
def file_appeal():
    body = body_json()
    check_unknown(body, {"submission_id", "appeal_type", "argument",
                         "cited_rejection_reason_ids"})
    (submission,) = resolve([("submission", body.get("submission_id"))])
    cited_raw = body.get("cited_rejection_reason_ids")
    if isinstance(cited_raw, list):
        resolve([("rejection_reason", value) for value in cited_raw
                 if isinstance(value, str)])
    req_id(body, "submission_id")
    appeal_type = req_str(body, "appeal_type", enum=APPEAL_TYPES)
    argument = req_str(body, "argument", 20, 2000)
    cited = req_array(body, "cited_rejection_reason_ids", min_items=1,
                      member_type=str, unique=True)
    flows.program_gate(calc.account_of_app(
        get_row("app_record", submission["app_record_id"])))
    if _live_appeal(submission["id"]) is not None:
        fail("ERR_APPEAL_ALREADY_OPEN",
             "an appeal of this submission is already live")
    if submission["state"] != "REJECTED":
        fail("ERR_INVALID_SUBMISSION_STATE",
             "only a REJECTED build may be appealed")
    rejected_at = parse_iso(submission.get("rejected_at"))
    if rejected_at is None or now_dt() > rejected_at + days(APPEAL_WINDOW_DAYS):
        fail("ERR_APPEAL_WINDOW_EXPIRED",
             "the %d-day appeal window has closed" % APPEAL_WINDOW_DAYS)
    for reason_id in cited:
        reason = get_row("rejection_reason", reason_id)
        if (reason is None or reason["submission_id"] != submission["id"]
                or reason.get("disposition") != "CONTESTED"
                or reason.get("appeal_disposition") not in (None, "PENDING")):
            fail("ERR_REJECTION_NOT_CONTESTED",
                 "cited reason %s is not a contested reason of this build"
                 % reason_id)
    row = new_row("appeal_request", {
        "submission_id": submission["id"],
        "appeal_type": appeal_type,
        "argument": argument,
        "cited_rejection_reason_ids": list(cited),
        "state": "SUBMITTED",
        "filed_at": now_iso(),
        "filed_by_user_id": g.user_id,
        "board_started_at": None,
        "decided_by_user_id": None,
        "decided_at": None,
        "rationale": None,
        "overturned_rejection_reason_ids": [],
        "overturn_ratio": None,
    })
    submission["state"] = "APPEAL_PENDING"
    touch(submission)
    window = get_row("review_capacity_window", submission.get("review_window_id"))
    if window is not None:
        calc.sync_window(window, bump=True)
    return ok(public(row), 201)


@bp.route("/appeal-requests", methods=["GET"])
@endpoint(REASON_READ_ROLES)
def list_appeals():
    items = rows("appeal_request")
    for field in ("submission_id", "state", "appeal_type"):
        wanted = arg_filter(field)
        if wanted is not None:
            items = [r for r in items if r.get(field) == wanted]
    return paginate(scope_rows(items))


@bp.route("/appeal-requests/<appeal_id>", methods=["GET"])
@endpoint(REASON_READ_ROLES)
def read_appeal(appeal_id):
    (appeal,) = resolve([("appeal_request", appeal_id)])
    return ok(public(appeal))


@bp.route("/appeal-requests/<appeal_id>/board-review", methods=["POST"])
@endpoint(["PlatformAppealBoard"])
def board_review(appeal_id):
    (appeal,) = resolve([("appeal_request", appeal_id)])
    if appeal["state"] != "SUBMITTED":
        fail("ERR_INVALID_APPEAL_STATE",
             "a %s appeal cannot be taken into board review" % appeal["state"])
    submission = get_row("submission", appeal["submission_id"])
    if submission is None or submission["state"] != "APPEAL_PENDING":
        fail("ERR_INVALID_SUBMISSION_STATE",
             "the submission under appeal is not APPEAL_PENDING")
    flows.sod_must_differ(submission.get("reviewed_by_user_id"))
    appeal["state"] = "BOARD_REVIEW"
    appeal["board_started_at"] = now_iso()
    touch(appeal)
    return ok(public(appeal))


def _restore_mappings(app, reason_ids):
    """Return mappings driven to FAILED by the overturned reasons to IN_PROGRESS."""
    rule_ids = set()
    for reason_id in reason_ids:
        reason = get_row("rejection_reason", reason_id)
        if reason is not None:
            rule_ids.add(reason["guideline_rule_id"])
    for mapping in calc.mappings_of_app(app["id"]):
        if (mapping["guideline_rule_id"] in rule_ids
                and mapping["self_review_status"] == "FAILED"):
            mapping["self_review_status"] = "IN_PROGRESS"
            touch(mapping)


def _approve_after_appeal(submission, app):
    """The APPEAL_PENDING -> APPROVED side effects of §3.9."""
    others = [s for s in calc.submissions_of_app(app["id"])
              if s["id"] != submission["id"] and s["state"] == "APPROVED"]
    submission["state"] = "APPROVED"
    submission["decided_at"] = now_iso()
    touch(submission)
    for other in others:
        other["state"] = "SUPERSEDED"
        touch(other)
        for plan in calc.plans_of_app(app["id"]):
            if (plan["submission_id"] == other["id"]
                    and plan["state"] == "SCHEDULED"):
                plan["state"] = "CANCELLED"
                plan["terminated_at"] = now_iso()
                touch(plan)


@bp.route("/appeal-requests/<appeal_id>/decide", methods=["POST"])
@endpoint(["PlatformAppealBoard"])
def decide_appeal(appeal_id):
    (appeal,) = resolve([("appeal_request", appeal_id)])
    body = body_json()
    check_unknown(body, {"outcome", "rationale",
                         "overturned_rejection_reason_ids"})
    outcome = req_str(body, "outcome", enum={"OVERTURNED", "PARTIALLY_OVERTURNED",
                                             "UPHELD"})
    rationale = req_str(body, "rationale", 1, 2000)
    overturned = opt_array(body, "overturned_rejection_reason_ids",
                           member_type=str, unique=True)
    if appeal["state"] != "BOARD_REVIEW":
        fail("ERR_INVALID_APPEAL_STATE",
             "a %s appeal cannot be decided" % appeal["state"])
    cited = list(appeal["cited_rejection_reason_ids"])
    if outcome == "PARTIALLY_OVERTURNED":
        subset = list(overturned or [])
        if (not subset or not set(subset).issubset(set(cited))
                or len(set(subset)) == len(set(cited))):
            fail("ERR_VALIDATION",
                 "overturned_rejection_reason_ids must be a non-empty strict "
                 "subset of cited_rejection_reason_ids")
    elif outcome == "OVERTURNED":
        subset = list(cited)
    else:
        subset = []
    submission = get_row("submission", appeal["submission_id"])
    flows.sod_must_differ(submission.get("reviewed_by_user_id"))
    app = get_row("app_record", submission["app_record_id"])
    account = calc.account_of_app(app)
    for reason_id in cited:
        reason = get_row("rejection_reason", reason_id)
        if reason is None:
            continue
        reason["appeal_disposition"] = ("OVERTURNED" if reason_id in subset
                                        else "UPHELD")
        touch(reason)
    appeal["state"] = outcome
    appeal["overturned_rejection_reason_ids"] = list(subset)
    appeal["overturn_ratio"] = d2(Decimal(len(subset)) / Decimal(len(cited)))
    appeal["rationale"] = rationale
    appeal["decided_by_user_id"] = g.user_id
    appeal["decided_at"] = now_iso()
    touch(appeal)
    if outcome == "UPHELD":
        submission["state"] = "REJECTED_FINAL"
        submission["decided_at"] = now_iso()
        touch(submission)
    elif outcome == "PARTIALLY_OVERTURNED":
        _restore_mappings(app, subset)
        submission["state"] = "REJECTED"
        submission["decided_at"] = now_iso()
        touch(submission)
        calc.recompute_app_posture(app)
    else:
        _restore_mappings(app, subset)
        calc.recompute_app_posture(app)
        _approve_after_appeal(submission, app)
    window = get_row("review_capacity_window", submission.get("review_window_id"))
    if window is not None:
        calc.sync_window(window, bump=True)
    if account is not None:
        calc.recompute_account_standing(account)
    return ok(public(appeal))


@bp.route("/appeal-requests/<appeal_id>/withdraw", methods=["POST"])
@endpoint(["ComplianceOfficer"])
def withdraw_appeal(appeal_id):
    (appeal,) = resolve([("appeal_request", appeal_id)])
    body = body_json()
    check_unknown(body, {"reason_code"})
    opt_str(body, "reason_code", 1, 80)
    if appeal["state"] != "SUBMITTED":
        fail("ERR_INVALID_APPEAL_STATE",
             "a %s appeal cannot be withdrawn" % appeal["state"])
    appeal["state"] = "WITHDRAWN"
    touch(appeal)
    submission = get_row("submission", appeal["submission_id"])
    if submission is not None and submission["state"] == "APPEAL_PENDING":
        submission["state"] = "REJECTED"
        touch(submission)
    return ok(public(appeal))


# --------------------------------------------------------------------------
# ExpediteRequest
# --------------------------------------------------------------------------
@bp.route("/expedite-requests", methods=["POST"])
@endpoint(["ReleaseManager", "ComplianceOfficer"])
def create_expedite():
    body = body_json()
    check_unknown(body, {"submission_id", "justification_category",
                         "justification"})
    (submission,) = resolve([("submission", body.get("submission_id"))])
    req_id(body, "submission_id")
    category = req_str(body, "justification_category",
                       enum=JUSTIFICATION_CATEGORIES)
    justification = req_str(body, "justification", 20, 1000)
    app = get_row("app_record", submission["app_record_id"])
    account = calc.account_of_app(app)
    flows.posture_gate(app, release_advancing=True)
    flows.program_gate(account)
    calc.recompute_account_standing(account)
    if account["standing_score_rolling_365"] < EXPEDITE_STANDING_FLOOR:
        fail("ERR_STANDING_TOO_LOW",
             "standing_score_rolling_365 is below the expedite floor")
    row = new_row("expedite_request", {
        "submission_id": submission["id"],
        "publisher_account_id": account["id"],
        "justification_category": category,
        "justification": justification,
        "state": "REQUESTED",
        "requested_at": now_iso(),
        "granted_at": None,
        "decided_by_user_id": None,
        "decision_rationale": None,
        "consumed_at": None,
        "refunded_at": None,
    })
    return ok(public(row), 201)


@bp.route("/expedite-requests", methods=["GET"])
@endpoint(EXPEDITE_READ_ROLES)
def list_expedites():
    items = rows("expedite_request")
    for field in ("submission_id", "publisher_account_id", "state",
                  "justification_category"):
        wanted = arg_filter(field)
        if wanted is not None:
            items = [r for r in items if r.get(field) == wanted]
    return paginate(scope_rows(items))


@bp.route("/expedite-requests/<expedite_id>", methods=["GET"])
@endpoint(EXPEDITE_READ_ROLES)
def read_expedite(expedite_id):
    (expedite,) = resolve([("expedite_request", expedite_id)])
    return ok(public(expedite))


@bp.route("/expedite-requests/<expedite_id>/decide", methods=["POST"])
@endpoint(["PlatformAppealBoard"])
def decide_expedite(expedite_id):
    (expedite,) = resolve([("expedite_request", expedite_id)])
    body = body_json()
    check_unknown(body, {"outcome", "decision_rationale"})
    outcome = req_str(body, "outcome", enum={"GRANT", "DENY"})
    rationale = req_str(body, "decision_rationale", 1, 1000)
    if expedite["state"] != "REQUESTED":
        fail("ERR_INVALID_EXPEDITE_STATE",
             "a %s expedite request cannot be decided" % expedite["state"])
    submission = get_row("submission", expedite["submission_id"])
    account = get_row("publisher_account", expedite["publisher_account_id"])
    # §3.6 pins the whole refusal set for a decision: ERR_INVALID_EXPEDITE_STATE off
    # REQUESTED, ERR_EXPEDITE_QUOTA_EXHAUSTED, ERR_STANDING_TOO_LOW and the
    # segregation-of-duties distinction from the cited submission's reviewed_by_user_id.
    # It puts no state requirement on the cited submission itself, and §2.7 evaluates the
    # duty split "after the posture and program-status rungs but before any business rule".
    if submission is not None:
        flows.sod_must_differ(submission.get("reviewed_by_user_id"))
    if outcome == "GRANT":
        calc.recompute_account_standing(account)
        if account["expedite_credits_remaining"] < 1:
            fail("ERR_EXPEDITE_QUOTA_EXHAUSTED",
                 "no expedite credit remains in the rolling window")
        if account["standing_score_rolling_365"] < EXPEDITE_STANDING_FLOOR:
            fail("ERR_STANDING_TOO_LOW",
                 "standing_score_rolling_365 is below the expedite floor")
        expedite["state"] = "GRANTED"
        expedite["granted_at"] = now_iso()
    else:
        expedite["state"] = "DENIED"
    expedite["decided_by_user_id"] = g.user_id
    expedite["decision_rationale"] = rationale
    touch(expedite)
    if account is not None:
        calc.recompute_account_standing(account)
    return ok(public(expedite))


# --------------------------------------------------------------------------
# ReviewCapacityWindow — outside tenancy scope entirely
# --------------------------------------------------------------------------
@bp.route("/review-capacity-windows", methods=["POST"])
@endpoint(["PlatformPolicyAdmin"])
def create_window():
    body = body_json()
    check_unknown(body, {"platform", "reviewer_pool_code", "starts_at",
                         "ends_at", "capacity_slots"})
    platform = req_str(body, "platform", enum=PLATFORMS)
    pool_code = req_str(body, "reviewer_pool_code", 1, 40)
    starts_at = req_iso(body, "starts_at")
    ends_at = req_iso(body, "ends_at")
    capacity_slots = req_int(body, "capacity_slots", 1)
    if ends_at <= starts_at:
        fail("ERR_VALIDATION", "ends_at must be strictly later than starts_at")
    concurrent = capacity_slots
    for other in rows("review_capacity_window"):
        if (other["platform"] != platform
                or other["reviewer_pool_code"] != pool_code
                or other["status"] != "OPEN"):
            continue
        if (parse_iso(other["starts_at"]) < ends_at
                and starts_at < parse_iso(other["ends_at"])):
            concurrent += other["capacity_slots"]
    if concurrent > POOL_MAX_CONCURRENT_SLOTS:
        fail("ERR_REVIEW_POOL_OVERSUBSCRIBED",
             "aggregate concurrent capacity %d exceeds the pool ceiling"
             % concurrent)
    row = new_row("review_capacity_window", {
        "platform": platform,
        "reviewer_pool_code": pool_code,
        "starts_at": fmt_iso(starts_at),
        "ends_at": fmt_iso(ends_at),
        "capacity_slots": capacity_slots,
        "status": "OPEN",
        "slots_reserved": 0,
        "slots_consumed": 0,
        "slots_available": capacity_slots,
    })
    return ok(public(row), 201)


@bp.route("/review-capacity-windows", methods=["GET"])
@endpoint(WINDOW_ROLES)
def list_windows():
    items = rows("review_capacity_window")
    for field in ("platform", "reviewer_pool_code", "status"):
        wanted = arg_filter(field)
        if wanted is not None:
            items = [r for r in items if r.get(field) == wanted]
    for window in items:
        calc.sync_window(window, bump=False)
    return paginate(items)


@bp.route("/review-capacity-windows/<window_id>", methods=["GET"])
@endpoint(WINDOW_ROLES)
def read_window(window_id):
    (window,) = resolve([("review_capacity_window", window_id)])
    calc.sync_window(window, bump=False)
    return ok(public(window))


@bp.route("/review-capacity-windows/<window_id>/close", methods=["POST"])
@endpoint(["PlatformPolicyAdmin"])
def close_window(window_id):
    (window,) = resolve([("review_capacity_window", window_id)])
    if window["status"] != "OPEN":
        fail("ERR_REVIEW_WINDOW_CLOSED", "the window is already CLOSED")
    window["status"] = "CLOSED"
    calc.sync_window(window, bump=False)
    touch(window)
    return ok(public(window))
