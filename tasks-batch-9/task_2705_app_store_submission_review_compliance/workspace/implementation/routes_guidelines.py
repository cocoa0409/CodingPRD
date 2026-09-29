"""The guideline corpus, feature mappings and impact assessments."""
from decimal import Decimal

from flask import Blueprint, g

import calc
import flows
from common import (arg_bool, arg_filter, body_json, d2, endpoint, fail, fmt_iso,
                    get_row, new_row, now_dt, now_iso, ok, paginate, parse_iso,
                    public, resolve, rows, scope_rows, touch)
from valid import (check_unknown, opt_bool, opt_num, opt_str, req_id, req_iso,
                   req_str)

bp = Blueprint("guidelines", __name__)

CATEGORIES = {"SAFETY", "PRIVACY", "COMMERCE", "LEGAL", "DESIGN"}
OUTCOMES = {"START", "PASS", "FAIL"}
ACTIONS = {"START", "REQUIRE_REMEDIATION", "ACCEPT_NO_CHANGE", "MARK_REMEDIATED"}


# --------------------------------------------------------------------------
# GuidelineRule
# --------------------------------------------------------------------------
@bp.route("/guideline-rules", methods=["POST"])
@endpoint(["PlatformPolicyAdmin"])
def draft_rule():
    body = body_json()
    check_unknown(body, {"rule_code", "title", "category", "version_label",
                         "effective_from", "supersedes_rule_id",
                         "requires_feature_mapping"})
    (superseded,) = resolve([("guideline_rule", body.get("supersedes_rule_id"))])
    rule_code = req_str(body, "rule_code", 1, 60)
    title = req_str(body, "title", 1, 200)
    category = req_str(body, "category", enum=CATEGORIES)
    version_label = req_str(body, "version_label", 1, 40)
    effective_from = req_iso(body, "effective_from")
    requires_mapping = opt_bool(body, "requires_feature_mapping", default=True)
    for existing in rows("guideline_rule"):
        if (existing["rule_code"] == rule_code
                and existing["version_label"] == version_label):
            fail("ERR_VALIDATION",
                 "rule_code and version_label must be unique together")
    row = new_row("guideline_rule", {
        "rule_code": rule_code,
        "title": title,
        "category": category,
        "severity_weight": calc.SEVERITY_WEIGHTS[category],
        "remediation_grace_days": calc.GRACE_DAYS[category],
        "version_label": version_label,
        "effective_from": fmt_iso(effective_from),
        "status": "DRAFT",
        "supersedes_rule_id": superseded["id"] if superseded is not None else None,
        "requires_feature_mapping": requires_mapping,
        "published_at": None,
        "impacted_app_count": 0,
    })
    return ok(public(row), 201)


@bp.route("/guideline-rules", methods=["GET"])
@endpoint(["PublisherAdmin", "ReleaseManager", "ComplianceOfficer",
           "PlatformReviewer", "PlatformAppealBoard", "PlatformPolicyAdmin",
           "Auditor"])
def list_rules():
    items = rows("guideline_rule")
    for field in ("supersedes_rule_id", "status", "category", "version_label"):
        wanted = arg_filter(field)
        if wanted is not None:
            items = [r for r in items if r.get(field) == wanted]
    requires = arg_bool("requires_feature_mapping")
    if requires is not None:
        items = [r for r in items if r["requires_feature_mapping"] is requires]
    return paginate(items)


@bp.route("/guideline-rules/<rule_id>", methods=["GET"])
@endpoint(["PublisherAdmin", "ReleaseManager", "ComplianceOfficer",
           "PlatformReviewer", "PlatformAppealBoard", "PlatformPolicyAdmin",
           "Auditor"])
def read_rule(rule_id):
    (rule,) = resolve([("guideline_rule", rule_id)])
    return ok(public(rule))


@bp.route("/guideline-rules/<rule_id>/publish", methods=["POST"])
@endpoint(["PlatformPolicyAdmin"])
def publish_rule(rule_id):
    (rule,) = resolve([("guideline_rule", rule_id)])
    if rule["status"] != "DRAFT":
        fail("ERR_INVALID_GUIDELINE_STATE",
             "a %s rule cannot be published" % rule["status"])
    if parse_iso(rule["effective_from"]) > now_dt():
        fail("ERR_RULE_NOT_YET_EFFECTIVE",
             "effective_from is later than the current logical instant")
    superseded = None
    if rule.get("supersedes_rule_id"):
        superseded = get_row("guideline_rule", rule["supersedes_rule_id"])
        if superseded is None or superseded["status"] != "EFFECTIVE":
            fail("ERR_GUIDELINE_RULE_NOT_EFFECTIVE",
                 "the superseded rule is not currently EFFECTIVE")
    rule["status"] = "EFFECTIVE"
    rule["published_at"] = now_iso()
    if superseded is not None:
        superseded["status"] = "SUPERSEDED"
        touch(superseded)
    flows.publish_cascade(rule, superseded)
    touch(rule)
    return ok(public(rule))


# --------------------------------------------------------------------------
# FeatureMapping
# --------------------------------------------------------------------------
@bp.route("/feature-mappings", methods=["POST"])
@endpoint(["ComplianceOfficer"])
def create_mapping():
    body = body_json()
    check_unknown(body, {"app_record_id", "guideline_rule_id", "feature_code",
                         "evidence_ref", "risk_weight"})
    app, rule = resolve([
        ("app_record", body.get("app_record_id")),
        ("guideline_rule", body.get("guideline_rule_id")),
    ])
    req_id(body, "app_record_id")
    req_id(body, "guideline_rule_id")
    feature_code = req_str(body, "feature_code", 1, 80)
    risk_weight = opt_num(body, "risk_weight", minimum=0, maximum=10)
    if risk_weight is None:
        risk_weight = Decimal("1.00")
    risk_weight = d2(risk_weight)
    evidence_ref = opt_str(body, "evidence_ref", 1, 300)
    for existing in calc.mappings_of_app(app["id"]):
        if (existing["guideline_rule_id"] == rule["id"]
                and existing["feature_code"] == feature_code):
            fail("ERR_VALIDATION",
                 "this app already maps feature_code %s to that rule" % feature_code)
    # Creating a mapping is not one of the sixteen posture-blocked operations of §2.8, so
    # its "the app it names must not be frozen" rule sits in the business bands, below the
    # account's program status on rung 9.
    flows.program_gate(calc.account_of_app(app))
    flows.posture_gate(app)
    if rule["status"] != "EFFECTIVE":
        fail("ERR_GUIDELINE_RULE_NOT_EFFECTIVE",
             "a mapping may only cite an EFFECTIVE guideline rule")
    row = new_row("feature_mapping", {
        "app_record_id": app["id"],
        "guideline_rule_id": rule["id"],
        "feature_code": feature_code,
        "self_review_status": "NOT_STARTED",
        "risk_weight": risk_weight,
        "evidence_ref": evidence_ref,
        "attested_by_user_id": None,
        "attested_at": None,
        "staled_by_rule_id": None,
        "waiver_reason": None,
    })
    calc.recompute_app_posture(app)
    return ok(public(row), 201)


@bp.route("/feature-mappings", methods=["GET"])
@endpoint(["PublisherAdmin", "ReleaseManager", "ComplianceOfficer",
           "PlatformReviewer", "PlatformPolicyAdmin", "Auditor"])
def list_mappings():
    items = rows("feature_mapping")
    for field in ("app_record_id", "guideline_rule_id", "staled_by_rule_id",
                  "attested_by_user_id", "self_review_status", "feature_code"):
        wanted = arg_filter(field)
        if wanted is not None:
            items = [r for r in items if r.get(field) == wanted]
    return paginate(scope_rows(items))


@bp.route("/feature-mappings/<mapping_id>", methods=["GET"])
@endpoint(["PublisherAdmin", "ReleaseManager", "ComplianceOfficer",
           "PlatformReviewer", "PlatformPolicyAdmin", "Auditor"])
def read_mapping(mapping_id):
    (mapping,) = resolve([("feature_mapping", mapping_id)])
    return ok(public(mapping))


@bp.route("/feature-mappings/<mapping_id>/self-review", methods=["POST"])
@endpoint(["ComplianceOfficer"])
def self_review(mapping_id):
    (mapping,) = resolve([("feature_mapping", mapping_id)])
    body = body_json()
    check_unknown(body, {"outcome", "evidence_ref"})
    outcome = req_str(body, "outcome", enum=OUTCOMES)
    evidence_ref = opt_str(body, "evidence_ref", 1, 300)
    status = mapping["self_review_status"]
    allowed = {"START": ("NOT_STARTED",),
               "PASS": ("IN_PROGRESS", "FAILED", "STALE"),
               "FAIL": ("IN_PROGRESS", "PASSED")}[outcome]
    if status not in allowed:
        fail("ERR_INVALID_MAPPING_STATE",
             "outcome %s is not declared for self_review_status %s"
             % (outcome, status))
    # Recording a self-review outcome is one of the sixteen frozen-blocked operations.
    flows.posture_gate(get_row("app_record", mapping["app_record_id"]))
    if evidence_ref is not None:
        mapping["evidence_ref"] = evidence_ref
    if outcome == "PASS":
        if not mapping.get("evidence_ref"):
            fail("ERR_EVIDENCE_REQUIRED",
                 "passing a self-review requires a non-empty evidence_ref")
        mapping["self_review_status"] = "PASSED"
    elif outcome == "FAIL":
        mapping["self_review_status"] = "FAILED"
    else:
        mapping["self_review_status"] = "IN_PROGRESS"
    if outcome in ("PASS", "FAIL"):
        mapping["attested_by_user_id"] = g.user_id
        mapping["attested_at"] = now_iso()
        mapping["staled_by_rule_id"] = None
    touch(mapping)
    app = get_row("app_record", mapping["app_record_id"])
    if app is not None:
        calc.recompute_app_posture(app)
    return ok(public(mapping))


@bp.route("/feature-mappings/<mapping_id>/waive", methods=["POST"])
@endpoint(["PlatformPolicyAdmin"])
def waive_mapping(mapping_id):
    (mapping,) = resolve([("feature_mapping", mapping_id)])
    body = body_json()
    check_unknown(body, {"waiver_reason"})
    waiver_reason = req_str(body, "waiver_reason", 1, 500)
    if mapping["self_review_status"] not in ("FAILED", "STALE"):
        fail("ERR_INVALID_MAPPING_STATE",
             "a %s mapping cannot be waived" % mapping["self_review_status"])
    flows.sod_must_differ(mapping.get("attested_by_user_id"))
    rule = get_row("guideline_rule", mapping["guideline_rule_id"])
    if rule is not None and rule["category"] == "SAFETY":
        fail("ERR_WAIVER_NOT_PERMITTED",
             "a SAFETY-category guideline may never be waived")
    if len(waiver_reason) < 20:
        fail("ERR_EVIDENCE_REQUIRED",
             "waiver_reason must be at least 20 characters")
    mapping["self_review_status"] = "WAIVED_BY_PLATFORM"
    mapping["waiver_reason"] = waiver_reason
    mapping["staled_by_rule_id"] = None
    mapping["attested_at"] = now_iso()
    touch(mapping)
    app = get_row("app_record", mapping["app_record_id"])
    if app is not None:
        calc.recompute_app_posture(app)
    return ok(public(mapping))


# --------------------------------------------------------------------------
# ImpactAssessment — minted only by the publication cascade
# --------------------------------------------------------------------------
@bp.route("/impact-assessments", methods=["GET"])
@endpoint(["PublisherAdmin", "ReleaseManager", "ComplianceOfficer",
           "PlatformPolicyAdmin", "Auditor"])
def list_assessments():
    items = rows("impact_assessment")
    for field in ("app_record_id", "guideline_rule_id", "status"):
        wanted = arg_filter(field)
        if wanted is not None:
            items = [r for r in items if r.get(field) == wanted]
    return paginate(scope_rows(items))


@bp.route("/impact-assessments/<assessment_id>", methods=["GET"])
@endpoint(["PublisherAdmin", "ReleaseManager", "ComplianceOfficer",
           "PlatformPolicyAdmin", "Auditor"])
def read_assessment(assessment_id):
    (assessment,) = resolve([("impact_assessment", assessment_id)])
    return ok(public(assessment))


@bp.route("/impact-assessments/<assessment_id>/assess", methods=["POST"])
@endpoint(["ComplianceOfficer"])
def assess(assessment_id):
    (assessment,) = resolve([("impact_assessment", assessment_id)])
    body = body_json()
    check_unknown(body, {"action", "note"})
    action = req_str(body, "action", enum=ACTIONS)
    note = opt_str(body, "note", 1, 1000)
    status = assessment["status"]
    allowed = {"START": ("OPEN",),
               "REQUIRE_REMEDIATION": ("IN_ASSESSMENT",),
               "ACCEPT_NO_CHANGE": ("IN_ASSESSMENT",),
               "MARK_REMEDIATED": ("REMEDIATION_REQUIRED", "OVERDUE")}[action]
    if status not in allowed:
        fail("ERR_INVALID_IMPACT_STATE",
             "action %s is not declared for status %s" % (action, status))
    app = get_row("app_record", assessment["app_record_id"])
    rule = get_row("guideline_rule", assessment["guideline_rule_id"])
    codes = list(assessment.get("affected_feature_codes") or [])
    mappings = [m for m in calc.mappings_of_app(assessment["app_record_id"])
                if m["feature_code"] in codes]
    if action == "START":
        severity, factor = calc.impact_severity(rule, codes, app)
        assessment["exposure_factor"] = factor
        assessment["impact_severity"] = severity
        assessment["status"] = "IN_ASSESSMENT"
        assessment["assessed_by_user_id"] = g.user_id
        assessment["assessed_at"] = now_iso()
    elif action == "REQUIRE_REMEDIATION":
        assessment["status"] = "REMEDIATION_REQUIRED"
    elif action == "ACCEPT_NO_CHANGE":
        if rule is not None and rule["category"] == "SAFETY":
            fail("ERR_IMPACT_TOO_SEVERE",
                 "a SAFETY-category rule change may never be accepted unchanged")
        if assessment["impact_severity"] > calc.ACCEPT_NO_CHANGE_SEVERITY_CEILING:
            fail("ERR_IMPACT_TOO_SEVERE",
                 "impact_severity exceeds the acceptance ceiling")
        assessment["status"] = "ACCEPTED_NO_CHANGE"
        for mapping in mappings:
            if mapping["self_review_status"] == "STALE":
                mapping["self_review_status"] = "PASSED"
                mapping["staled_by_rule_id"] = None
                touch(mapping)
    else:
        for mapping in mappings:
            if mapping["self_review_status"] not in ("PASSED", "WAIVED_BY_PLATFORM"):
                fail("ERR_REMEDIATION_INCOMPLETE",
                     "feature mapping %s is still %s"
                     % (mapping["feature_code"], mapping["self_review_status"]))
        assessment["status"] = "REMEDIATED"
        assessment["remediated_at"] = now_iso()
    if note is not None:
        assessment["note"] = note
    touch(assessment)
    if app is not None:
        calc.recompute_app_posture(app)
    return ok(public(assessment))
