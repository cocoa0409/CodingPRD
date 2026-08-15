"""CDI query endpoints: draft, edit, send (lint + OCC), cancel, responses."""
from flask import Blueprint, request

import db
from calc import (
    compute_priority,
    lint_query,
    recompute_review_deltas,
    record_education,
)
from errors import raise_error
from helpers import (
    body_ref,
    get_or_404,
    list_page,
    make_record,
    require_program_active,
    touch,
    validate_weight,
)
from middleware import (
    check_known_fields,
    get_json_body,
    require_fields,
    require_roles,
    validate_enum,
    validate_int_range,
    validate_integer,
    validate_string,
    validate_string_list,
)
from response import success_list, success_object
from serializers import query_out, response_out

bp = Blueprint("queries", __name__)

ROLES = {"CDIManager", "CDISpecialist", "HIMCoder", "ComplianceAuditor", "Provider"}
RESPONSE_TYPES = {"AGREE", "DISAGREE", "CLARIFICATION_REQUESTED", "CLINICALLY_UNSUPPORTED"}
EDITABLE = {
    "query_text", "clinical_indicators", "proposed_drg_code",
    "proposed_drg_weight", "proposed_soi", "proposed_rom",
    "provider_id", "escalation_policy_id",
}


def _check_provider_membership(query_program_id, provider_id):
    """ERR_PROVIDER_NOT_IN_PROGRAM when the addressee is unknown to the program."""
    provider = db.providers.get(provider_id)
    if provider is None or provider["cdi_program_id"] != query_program_id:
        raise_error(
            "ERR_PROVIDER_NOT_IN_PROGRAM",
            "provider_id does not belong to the case's program",
        )
    return provider


def _check_policy(policy_id, program_id):
    policy = db.policies.get(policy_id)
    if policy is None:
        raise_error(
            "ERR_INVALID_REQUEST",
            "escalation_policy_id does not reference an existing escalation policy",
        )
    if policy["cdi_program_id"] != program_id:
        raise_error(
            "ERR_INVALID_REQUEST",
            "escalation_policy_id belongs to a different program",
        )
    return policy


@bp.route("/api/cdi-queries", methods=["POST"])
def create_query():
    require_roles({"CDISpecialist"})
    body = get_json_body()
    check_known_fields(body, {
        "cdi_review_id", "provider_id", "escalation_policy_id", "query_text",
        "clinical_indicators", "proposed_drg_code", "proposed_drg_weight",
        "proposed_soi", "proposed_rom",
    })
    require_fields(body, [
        "cdi_review_id", "provider_id", "escalation_policy_id", "query_text",
        "clinical_indicators", "proposed_drg_code", "proposed_drg_weight",
        "proposed_soi", "proposed_rom",
    ])
    review = body_ref(body, "cdi_review_id", db.reviews, "review")
    query_text = validate_string(body["query_text"], "query_text")
    indicators = validate_string_list(body["clinical_indicators"], "clinical_indicators")
    proposed_drg_code = validate_string(body["proposed_drg_code"], "proposed_drg_code")
    proposed_drg_weight = validate_weight(body["proposed_drg_weight"], "proposed_drg_weight")
    proposed_soi = validate_int_range(body["proposed_soi"], "proposed_soi", 1, 4)
    proposed_rom = validate_int_range(body["proposed_rom"], "proposed_rom", 1, 4)
    provider_id = body["provider_id"]
    if not isinstance(provider_id, str) or not provider_id:
        raise_error("ERR_INVALID_REQUEST", "provider_id is required and must be a string")
    policy_id = body["escalation_policy_id"]
    if not isinstance(policy_id, str) or not policy_id:
        raise_error(
            "ERR_INVALID_REQUEST",
            "escalation_policy_id is required and must be a string",
        )
    program = db.programs.get(review["cdi_program_id"])
    require_program_active(program)
    # PRD 3.4 attaches ERR_PROVIDER_NOT_IN_PROGRAM to the SEND path only; a
    # draft may name any recipient and is "freely edited" while a draft.
    _check_policy(policy_id, review["cdi_program_id"])
    query = make_record(db.queries, {
        "cdi_review_id": review["id"],
        "patient_case_id": review["patient_case_id"],
        "cdi_program_id": review["cdi_program_id"],
        "provider_id": provider_id,
        "escalation_policy_id": policy_id,
        "query_text": query_text,
        "clinical_indicators": indicators,
        "proposed_drg_code": proposed_drg_code,
        "proposed_drg_weight": proposed_drg_weight,
        "proposed_soi": proposed_soi,
        "proposed_rom": proposed_rom,
        "compliant_language": None,
        "lint_findings": [],
        "sent_period": None,
        "due_period": None,
        "escalation_stage": 0,
        "last_escalated_period": None,
        "response_id": None,
        "status": "DRAFT",
    })
    # A new DRAFT query opens the provisional priority variant on the case.
    case = db.cases.get(query["patient_case_id"])
    if case is not None:
        compute_priority(case)
    return success_object(query_out(query), status=201)


@bp.route("/api/cdi-queries", methods=["GET"])
def list_queries():
    require_roles(ROLES)
    filters = (
        ("cdi_review_id", "cdi_review_id"),
        ("patient_case_id", "patient_case_id"),
        ("cdi_program_id", "cdi_program_id"),
        ("provider_id", "provider_id"),
        ("escalation_policy_id", "escalation_policy_id"),
        ("status", "status"),
    )
    items = list(db.queries.values())
    for param, field in filters:
        value = request.args.get(param)
        if value is not None:
            items = [q for q in items if q[field] == value]
    page, limit, offset, total = list_page(items)
    return success_list([query_out(q) for q in page], limit, offset, total)


@bp.route("/api/cdi-queries/<queryId>", methods=["GET"])
def get_query(queryId):
    require_roles(ROLES)
    query = get_or_404(db.queries, queryId, "query")
    return success_object(query_out(query))


@bp.route("/api/cdi-queries/<queryId>", methods=["PUT"])
def edit_query(queryId):
    require_roles({"CDISpecialist"})
    query = get_or_404(db.queries, queryId, "query")
    body = get_json_body()
    check_known_fields(body, EDITABLE)
    program = db.programs.get(query["cdi_program_id"])
    require_program_active(program)
    if query["status"] != "DRAFT":
        raise_error("ERR_INVALID_STATE", "Only a DRAFT query can be edited")
    if "query_text" in body:
        query["query_text"] = validate_string(body["query_text"], "query_text")
    if "clinical_indicators" in body:
        query["clinical_indicators"] = validate_string_list(
            body["clinical_indicators"], "clinical_indicators"
        )
    if "proposed_drg_code" in body:
        query["proposed_drg_code"] = validate_string(
            body["proposed_drg_code"], "proposed_drg_code"
        )
    if "proposed_drg_weight" in body:
        query["proposed_drg_weight"] = validate_weight(
            body["proposed_drg_weight"], "proposed_drg_weight"
        )
    if "proposed_soi" in body:
        query["proposed_soi"] = validate_int_range(body["proposed_soi"], "proposed_soi", 1, 4)
    if "proposed_rom" in body:
        query["proposed_rom"] = validate_int_range(body["proposed_rom"], "proposed_rom", 1, 4)
    if "provider_id" in body:
        provider_id = body["provider_id"]
        if not isinstance(provider_id, str) or not provider_id:
            raise_error("ERR_INVALID_REQUEST", "provider_id must be a non-empty string")
        # Membership is scrutinized at send time (PRD 3.4), not on draft edits.
        query["provider_id"] = provider_id
    if "escalation_policy_id" in body:
        policy_id = body["escalation_policy_id"]
        if not isinstance(policy_id, str) or not policy_id:
            raise_error(
                "ERR_INVALID_REQUEST",
                "escalation_policy_id must be a non-empty string",
            )
        _check_policy(policy_id, query["cdi_program_id"])
        query["escalation_policy_id"] = policy_id
    touch(query)
    # Proposed-weight edits shift the provisional base opportunity.
    case = db.cases.get(query["patient_case_id"])
    if case is not None:
        compute_priority(case)
    return success_object(query_out(query))


@bp.route("/api/cdi-queries/<queryId>/send", methods=["POST"])
def send_query(queryId):
    require_roles({"CDISpecialist"})
    query = get_or_404(db.queries, queryId, "query")
    program = db.programs.get(query["cdi_program_id"])
    require_program_active(program)
    if query["status"] != "DRAFT":
        raise_error("ERR_INVALID_STATE", "Only a DRAFT query can be sent")
    review = db.reviews.get(query["cdi_review_id"])
    if review is None or review["status"] != "ACTIVE":
        raise_error("ERR_REVIEW_NOT_ACTIVE", "Parent review is not ACTIVE")
    body = get_json_body()
    check_known_fields(body, {"expected_query_version"})
    # OCC (PRD 2.8): expected_query_version is non-optional.
    if "expected_query_version" not in body or body["expected_query_version"] is None:
        raise_error("ERR_INVALID_REQUEST", "expected_query_version is required")
    expected = validate_integer(body["expected_query_version"], "expected_query_version")
    if expected != query["version"]:
        raise_error(
            "ERR_STALE_VERSION",
            "expected_query_version does not match the query's current version",
        )
    # Non-leading lint (priority 6): outcome stored for audit either way.
    findings = lint_query(
        query["query_text"], query["clinical_indicators"], query["proposed_drg_code"]
    )
    query["compliant_language"] = len(findings) == 0
    query["lint_findings"] = findings
    if findings:
        raise_error(
            "ERR_LEADING_LANGUAGE",
            "Query failed the non-leading lint: " + ", ".join(findings),
        )
    # Provider program membership (priority 7).
    _check_provider_membership(query["cdi_program_id"], query["provider_id"])
    policy = db.policies.get(query["escalation_policy_id"])
    if policy is None:
        raise_error(
            "ERR_INVALID_REQUEST",
            "escalation_policy_id does not reference an existing escalation policy",
        )
    now_p = program["current_period_index"] if program is not None else 0
    query["status"] = "SENT"
    query["sent_period"] = now_p
    query["due_period"] = now_p + policy["response_due_periods"]
    touch(query)
    return success_object(query_out(query))


@bp.route("/api/cdi-queries/<queryId>/cancel", methods=["POST"])
def cancel_query(queryId):
    require_roles({"CDISpecialist"})
    query = get_or_404(db.queries, queryId, "query")
    get_json_body()
    program = db.programs.get(query["cdi_program_id"])
    require_program_active(program)
    if query["status"] not in ("DRAFT", "SENT", "ESCALATED"):
        raise_error(
            "ERR_INVALID_STATE",
            "Only a DRAFT, SENT, or ESCALATED query can be cancelled",
        )
    # Cancelling a SENT/ESCALATED query records no education event.
    query["status"] = "CANCELLED"
    touch(query)
    # The query leaves the open set: provisional -> residual base opportunity.
    case = db.cases.get(query["patient_case_id"])
    if case is not None:
        compute_priority(case)
    return success_object(query_out(query))


@bp.route("/api/cdi-queries/<queryId>/responses", methods=["POST"])
def create_response(queryId):
    user_id, _ = require_roles({"Provider"})
    query = get_or_404(db.queries, queryId, "query")
    program = db.programs.get(query["cdi_program_id"])
    require_program_active(program)
    if query["status"] not in ("SENT", "ESCALATED"):
        raise_error(
            "ERR_INVALID_STATE",
            "Only a SENT or ESCALATED query accepts a response",
        )
    body = get_json_body()
    check_known_fields(body, {"response_type", "response_text"})
    require_fields(body, ["response_type", "response_text"])
    response_type = validate_enum(body["response_type"], RESPONSE_TYPES, "response_type")
    response_text = validate_string(body["response_text"], "response_text")
    # Segregation of duties: only the addressed provider may respond.
    if user_id != query["provider_id"]:
        raise_error(
            "ERR_NOT_QUERY_RECIPIENT",
            "Only the addressed provider may respond to this query",
        )
    provider = db.providers.get(query["provider_id"])
    if (
        provider is not None
        and provider["education_flag"] == "INTENSIVE_REVIEW"
        and response_type != "CLARIFICATION_REQUESTED"
    ):
        raise_error(
            "ERR_PROVIDER_UNDER_INTENSIVE_REVIEW",
            "Provider under INTENSIVE_REVIEW may only request clarification",
        )
    now_p = program["current_period_index"] if program is not None else 0
    was_overdue = query["due_period"] is not None and now_p > query["due_period"]
    response = make_record(db.responses, {
        "cdi_query_id": query["id"],
        "patient_case_id": query["patient_case_id"],
        "responder_provider_id": user_id,
        "response_type": response_type,
        "response_text": response_text,
        "responded_period": now_p,
        "was_overdue": was_overdue,
    })
    query["status"] = "RESPONDED"
    query["response_id"] = response["id"]
    touch(query)
    if response_type == "AGREE":
        case = db.cases.get(query["patient_case_id"])
        if case is not None:
            case["working_drg_code"] = query["proposed_drg_code"]
            case["working_drg_weight"] = query["proposed_drg_weight"]
            case["working_soi"] = query["proposed_soi"]
            case["working_rom"] = query["proposed_rom"]
            compute_priority(case)
            touch(case)
        review = db.reviews.get(query["cdi_review_id"])
        if review is not None:
            recompute_review_deltas(review)
            touch(review)
    else:
        # Any response removes the query from the open set, so the case's
        # priority_score falls back to the residual base (system refresh; no
        # case version bump unless the AGREE branch rewrote working fields).
        case = db.cases.get(query["patient_case_id"])
        if case is not None:
            compute_priority(case)
    if response_type == "CLINICALLY_UNSUPPORTED" and provider is not None:
        record_education(provider, "CLINICALLY_UNSUPPORTED_PATTERN", 4, query["id"], "")
    if was_overdue and provider is not None:
        record_education(provider, "OVERDUE_PATTERN", 2, query["id"], "")
    return success_object(response_out(response), status=201)


@bp.route("/api/cdi-queries/<queryId>/responses", methods=["GET"])
def list_responses(queryId):
    require_roles(ROLES)
    get_or_404(db.queries, queryId, "query")
    items = [r for r in db.responses.values() if r["cdi_query_id"] == queryId]
    page, limit, offset, total = list_page(items)
    return success_list([response_out(r) for r in page], limit, offset, total)
