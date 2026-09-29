"""Credential recommendations and articulation (crosswalk) rules."""
from flask import Blueprint, request

from db import (assignments_of_claim, claims_of_rule, db, invoice_of_claim,
                new_row, order_rows, rules_of_recommendation)
from errors import ApiError
from middleware import ALL_ROLES, ROLE_OFFICER, authenticate, find_or_404
from response import created, ok, ok_list, read_pagination
from serializers import recommendation_out, rule_out
from services import invoice as invoice_service
from services.sla import revoke_open_assignments
from util import (COURSE_LEVELS, CREDENTIAL_SOURCE_TYPES, as_dt, as_enum, as_int,
                  as_str, dtv, json_body, present, put_dt, require, touch)

bp = Blueprint("articulation", __name__)


# ---------------------------------------------------------------- recommendations
@bp.post("/credential-recommendations")
def create_recommendation():
    authenticate([ROLE_OFFICER])
    body = json_body()
    source_type = as_enum(require(body, "source_type"), "source_type", CREDENTIAL_SOURCE_TYPES)
    credential_code = as_str(require(body, "credential_code"), "credential_code", 1, 32)
    title = as_str(require(body, "title"), "title", 1)
    issuing_body = as_str(require(body, "issuing_body"), "issuing_body", 1)
    credits = as_int(require(body, "recommended_credits"), "recommended_credits", 1, 12)
    level = as_enum(require(body, "recommended_level"), "recommended_level", COURSE_LEVELS)
    from_raw, from_dt = as_dt(require(body, "effective_from"), "effective_from")
    to_raw, to_dt = (None, None)
    if present(body, "effective_to"):
        to_raw, to_dt = as_dt(body["effective_to"], "effective_to")
    for existing in db.recommendations.values():
        if existing["source_type"] == source_type and existing["credential_code"] == credential_code:
            raise ApiError("ERR_INVALID_REQUEST", "credential_code already exists for this source_type")

    row = new_row("CredentialRecommendation")
    row.update({
        "source_type": source_type,
        "credential_code": credential_code,
        "title": title,
        "issuing_body": issuing_body,
        "recommended_credits": credits,
        "recommended_level": level,
        "status": "DRAFT",
        "approved_rule_count": 0,
        "terms_version": 1,
        "retire_reason": None,
    })
    put_dt(row, "effective_from", from_dt, from_raw)
    put_dt(row, "effective_to", to_dt, to_raw)
    db.recommendations[row["id"]] = row
    return created(recommendation_out(row))


@bp.get("/credential-recommendations/<recommendation_id>")
def read_recommendation(recommendation_id):
    authenticate(ALL_ROLES)
    row = find_or_404("recommendations", recommendation_id, "ERR_RECOMMENDATION_NOT_FOUND")
    return ok(recommendation_out(row))


@bp.patch("/credential-recommendations/<recommendation_id>")
def amend_recommendation(recommendation_id):
    authenticate([ROLE_OFFICER])
    row = find_or_404("recommendations", recommendation_id, "ERR_RECOMMENDATION_NOT_FOUND")
    body = json_body()
    if row["status"] not in ("DRAFT", "PUBLISHED"):
        raise ApiError("ERR_RECOMMENDATION_NOT_PUBLISHED")
    if present(body, "recommended_credits"):
        row["recommended_credits"] = as_int(body["recommended_credits"], "recommended_credits", 1, 12)
    if present(body, "recommended_level"):
        row["recommended_level"] = as_enum(body["recommended_level"], "recommended_level", COURSE_LEVELS)
    if present(body, "title"):
        row["title"] = as_str(body["title"], "title", 1)
    if "effective_to" in body:
        value = body["effective_to"]
        if value is None:
            put_dt(row, "effective_to", None)
        else:
            raw, parsed = as_dt(value, "effective_to")
            put_dt(row, "effective_to", parsed, raw)
    row["terms_version"] += 1
    touch(row)
    return ok(recommendation_out(row))


@bp.post("/credential-recommendations/<recommendation_id>/publish")
def publish_recommendation(recommendation_id):
    authenticate([ROLE_OFFICER])
    row = find_or_404("recommendations", recommendation_id, "ERR_RECOMMENDATION_NOT_FOUND")
    if row["status"] != "DRAFT":
        raise ApiError("ERR_RECOMMENDATION_NOT_DRAFT")
    end = dtv(row, "effective_to")
    if end is not None and end <= dtv(row, "effective_from"):
        raise ApiError("ERR_INVALID_REQUEST", "effective_to must be later than effective_from")
    row["status"] = "PUBLISHED"
    touch(row)
    return ok(recommendation_out(row))


def _hold_claim(claim):
    """Institutional articulation hold: no revision budget is charged."""
    claim["assessment_status"] = "REVISION_REQUESTED"
    claim["hold_reason"] = "ARTICULATION_SUSPENDED"
    touch(claim)
    revoke_open_assignments(claim, "REVISION_REQUESTED")


def _waive_for_hold(claim, statuses, whole_total):
    invoice = invoice_of_claim(claim["id"])
    if invoice is None or claim["fee_status"] not in statuses:
        return
    student = db.students.get(claim["student_id"])
    invoice_service.waive(claim, invoice, student, whole_total=whole_total)


@bp.post("/credential-recommendations/<recommendation_id>/retire")
def retire_recommendation(recommendation_id):
    authenticate([ROLE_OFFICER])
    row = find_or_404("recommendations", recommendation_id, "ERR_RECOMMENDATION_NOT_FOUND")
    body = json_body()
    retire_reason = as_str(require(body, "retire_reason"), "retire_reason", 1)
    if row["status"] != "PUBLISHED":
        raise ApiError("ERR_RECOMMENDATION_NOT_PUBLISHED")
    row["retire_reason"] = retire_reason
    row["status"] = "RETIRED"
    just_suspended = []
    for rule in order_rows(rules_of_recommendation(recommendation_id), [(lambda r: r["created_at"], False)]):
        if rule["status"] == "APPROVED":
            rule["status"] = "SUSPENDED"
            rule["suspend_reason"] = "RECOMMENDATION_RETIRED"
            touch(rule)
            just_suspended.append(rule)
        elif rule["status"] == "SUSPENDED":
            rule["status"] = "RETIRED"
            touch(rule)
    row["approved_rule_count"] = 0
    touch(row)
    for rule in just_suspended:
        for claim in order_rows(claims_of_rule(rule["id"]), [(lambda c: c["created_at"], False)]):
            if claim["assessment_status"] not in ("SUBMITTED", "UNDER_ASSESSMENT"):
                continue
            _hold_claim(claim)
            _waive_for_hold(claim, ("INVOICED", "PARTIALLY_PAID", "PAID"), True)
    return ok(recommendation_out(row))


# ---------------------------------------------------------------- rules
def _windows_overlap(a_from, a_to, b_from, b_to):
    left = a_to is None or b_from < a_to
    right = b_to is None or a_from < b_to
    return left and right


def _check_window_exclusivity(rule):
    for other in db.rules.values():
        if other["id"] == rule["id"]:
            continue
        if other["status"] != "APPROVED":
            continue
        if other["recommendation_id"] != rule["recommendation_id"]:
            continue
        if other["course_id"] != rule["course_id"]:
            continue
        if _windows_overlap(dtv(rule, "effective_from"), dtv(rule, "effective_to"),
                            dtv(other, "effective_from"), dtv(other, "effective_to")):
            raise ApiError("ERR_ARTICULATION_WINDOW_OVERLAP")


@bp.post("/articulation-rules")
def create_rule():
    authenticate([ROLE_OFFICER])
    body = json_body()
    recommendation_id = require(body, "recommendation_id")
    recommendation = db.recommendations.get(recommendation_id)
    if recommendation is None:
        raise ApiError("ERR_RECOMMENDATION_NOT_FOUND")
    course_id = require(body, "course_id")
    course = db.courses.get(course_id)
    if course is None:
        raise ApiError("ERR_COURSE_NOT_FOUND")
    awarded = as_int(require(body, "awarded_credits"), "awarded_credits", 1, 12)
    if awarded > recommendation["recommended_credits"]:
        raise ApiError("ERR_INVALID_REQUEST", "awarded_credits exceeds recommended_credits")
    from_raw, from_dt = as_dt(require(body, "effective_from"), "effective_from")
    to_raw, to_dt = (None, None)
    if present(body, "effective_to"):
        to_raw, to_dt = as_dt(body["effective_to"], "effective_to")

    rule = new_row("ArticulationRule")
    rule.update({
        "recommendation_id": recommendation_id,
        "course_id": course_id,
        "awarded_credits": awarded,
        "status": "DRAFT",
        "pinned_recommendation_version": None,
        "reviewed_by_user_id": None,
        "approved_by_user_id": None,
        "suspend_reason": None,
    })
    put_dt(rule, "effective_from", from_dt, from_raw)
    put_dt(rule, "effective_to", to_dt, to_raw)
    db.rules[rule["id"]] = rule
    return created(rule_out(rule))


@bp.post("/articulation-rules/<rule_id>/submit-for-review")
def submit_rule(rule_id):
    ctx = authenticate([ROLE_OFFICER])
    rule = find_or_404("rules", rule_id, "ERR_ARTICULATION_RULE_NOT_FOUND")
    recommendation = db.recommendations.get(rule["recommendation_id"])
    course = db.courses.get(rule["course_id"])
    if rule["status"] != "DRAFT":
        raise ApiError("ERR_RULE_NOT_DRAFT")
    if recommendation["status"] != "PUBLISHED":
        raise ApiError("ERR_RECOMMENDATION_NOT_PUBLISHED")
    if rule["awarded_credits"] > recommendation["recommended_credits"]:
        raise ApiError("ERR_INVALID_REQUEST", "awarded_credits exceeds recommended_credits")
    if course["level"] == "UPPER" and recommendation["recommended_level"] != "UPPER":
        raise ApiError("ERR_LEVEL_MISMATCH")
    rule["status"] = "UNDER_REVIEW"
    rule["reviewed_by_user_id"] = ctx.user_id
    touch(rule)
    return ok(rule_out(rule))


@bp.post("/articulation-rules/<rule_id>/approve")
def approve_rule(rule_id):
    ctx = authenticate([ROLE_OFFICER])
    rule = find_or_404("rules", rule_id, "ERR_ARTICULATION_RULE_NOT_FOUND")
    body = json_body()
    expected = as_int(require(body, "expected_recommendation_version"), "expected_recommendation_version")
    recommendation = db.recommendations.get(rule["recommendation_id"])
    if recommendation["version"] != expected:
        raise ApiError("ERR_STALE_RECOMMENDATION_VERSION")
    if rule["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_RULE_NOT_UNDER_REVIEW")
    if recommendation["status"] != "PUBLISHED":
        raise ApiError("ERR_RECOMMENDATION_NOT_PUBLISHED")
    if ctx.user_id == rule["reviewed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    _check_window_exclusivity(rule)
    rule["status"] = "APPROVED"
    rule["approved_by_user_id"] = ctx.user_id
    rule["pinned_recommendation_version"] = recommendation["terms_version"]
    touch(rule)
    recommendation["approved_rule_count"] += 1
    touch(recommendation)
    return ok(rule_out(rule))


@bp.post("/articulation-rules/<rule_id>/suspend")
def suspend_rule(rule_id):
    authenticate([ROLE_OFFICER])
    rule = find_or_404("rules", rule_id, "ERR_ARTICULATION_RULE_NOT_FOUND")
    json_body()
    if rule["status"] != "APPROVED":
        raise ApiError("ERR_RULE_NOT_APPROVED")
    recommendation = db.recommendations.get(rule["recommendation_id"])
    rule["status"] = "SUSPENDED"
    rule["suspend_reason"] = "MANUAL_REVIEW"
    touch(rule)
    recommendation["approved_rule_count"] = max(0, recommendation["approved_rule_count"] - 1)
    touch(recommendation)
    for claim in order_rows(claims_of_rule(rule["id"]), [(lambda c: c["created_at"], False)]):
        if claim["assessment_status"] not in ("SUBMITTED", "UNDER_ASSESSMENT"):
            continue
        _hold_claim(claim)
        _waive_for_hold(claim, ("INVOICED", "PARTIALLY_PAID"), False)
    return ok(rule_out(rule))


@bp.post("/articulation-rules/<rule_id>/reinstate")
def reinstate_rule(rule_id):
    authenticate([ROLE_OFFICER])
    rule = find_or_404("rules", rule_id, "ERR_ARTICULATION_RULE_NOT_FOUND")
    if rule["status"] != "SUSPENDED":
        raise ApiError("ERR_RULE_NOT_SUSPENDED")
    recommendation = db.recommendations.get(rule["recommendation_id"])
    if recommendation["status"] != "PUBLISHED":
        raise ApiError("ERR_RECOMMENDATION_NOT_PUBLISHED")
    _check_window_exclusivity(rule)
    rule["status"] = "APPROVED"
    rule["suspend_reason"] = None
    rule["pinned_recommendation_version"] = recommendation["terms_version"]
    touch(rule)
    recommendation["approved_rule_count"] += 1
    touch(recommendation)
    for claim in claims_of_rule(rule["id"]):
        if claim["hold_reason"] == "ARTICULATION_SUSPENDED":
            claim["hold_reason"] = None
            touch(claim)
    return ok(rule_out(rule))


@bp.get("/articulation-rules/<rule_id>")
def read_rule(rule_id):
    authenticate(ALL_ROLES)
    rule = find_or_404("rules", rule_id, "ERR_ARTICULATION_RULE_NOT_FOUND")
    return ok(rule_out(rule))


@bp.get("/articulation-rules")
def list_rules():
    authenticate(ALL_ROLES)
    limit, offset = read_pagination()
    rows = list(db.rules.values())
    for key in ("recommendation_id", "course_id", "status"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    rows = order_rows(rows, [
        (lambda r: dtv(r, "effective_from"), False),
        (lambda r: r["created_at"], False),
    ])
    return ok_list(rows, rule_out, limit, offset)
