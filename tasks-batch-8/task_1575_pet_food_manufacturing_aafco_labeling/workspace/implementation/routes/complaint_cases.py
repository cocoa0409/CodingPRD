"""ComplaintCase endpoints."""

from flask import Blueprint, request

import errors
from db import store
from middleware import (require_roles, get_json_body, require_string,
                        require_enum, optional_field, optional_bool,
                        parse_pagination, paginate)
from response import success_object, success_list
from services.calculations import (stamp_new, touch, serialize, serialize_list,
                                   compute_triage_score,
                                   compute_brand_complaint_score,
                                   ESCALATION_THRESHOLD)

bp = Blueprint("complaint_cases", __name__)

SEVERITIES = {"MINOR", "SERIOUS", "LIFE_THREATENING", "DEATH"}
CATEGORIES = {"PALATABILITY", "FOREIGN_MATERIAL", "ILLNESS", "LABEL_DEFECT", "PACKAGING"}
CASE_TERMINAL = {"RESOLVED", "ESCALATED_RECALL", "CLOSED_NO_ACTION"}


@bp.route("/complaint-cases", methods=["POST"])
def create_case():
    require_roles("QualityAnalyst")
    body = get_json_body()
    brand_owner_id = require_string(body, "brand_owner_id")
    formula_id = require_string(body, "formula_id")
    batch_id = optional_field(body, "batch_id")
    severity = require_enum(body, "severity", SEVERITIES)
    category = require_enum(body, "category", CATEGORIES)
    adverse_event_flag = optional_bool(body, "adverse_event_flag", False)

    if store.brand_owners.get(brand_owner_id) is None:
        raise errors.not_found("BrandOwner not found")
    if store.formulas.get(formula_id) is None:
        raise errors.not_found("Formula not found")
    if batch_id is not None and store.production_batches.get(batch_id) is None:
        raise errors.not_found("ProductionBatch not found")

    provisional_score = compute_triage_score(severity, category, adverse_event_flag,
                                             provisional=True)
    case = {
        "brand_owner_id": brand_owner_id,
        "formula_id": formula_id,
        "batch_id": batch_id,
        "severity": severity,
        "category": category,
        "status": "INTAKE",
        "triage_score": provisional_score,
        "adverse_event_flag": adverse_event_flag,
    }
    stamp_new(case)
    store.complaint_cases[case["id"]] = case
    return success_object(serialize(case), 201)


def _get_case(id):
    c = store.complaint_cases.get(id)
    if c is None:
        raise errors.not_found("ComplaintCase not found")
    return c


def _check_case_not_terminal(c):
    if c["status"] in CASE_TERMINAL:
        raise errors.already_terminal("ComplaintCase is in a terminal state")


def _recompute_brand_score(brand_owner_id):
    brand = store.brand_owners.get(brand_owner_id)
    if brand is None:
        return
    brand["complaint_score"] = compute_brand_complaint_score(brand_owner_id)


@bp.route("/complaint-cases/<id>", methods=["GET"])
def get_case(id):
    require_roles("PlatformAdmin", "QualityAnalyst", "QAApprover")
    case = _get_case(id)
    return success_object(serialize(case), 200)


@bp.route("/formulas/<id>/complaint-cases", methods=["GET"])
def list_cases_for_formula(id):
    require_roles("PlatformAdmin", "QualityAnalyst", "QAApprover")
    formula = store.formulas.get(id)
    if formula is None:
        raise errors.not_found("Formula not found")
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    items = [c for c in store.complaint_cases.values() if c["formula_id"] == id]
    items.sort(key=lambda e: (e["_created_at_dt"], e["id"]))
    if status_filter is not None:
        items = [c for c in items if c["status"] == status_filter]
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total, 200)


@bp.route("/complaint-cases/<id>/triage", methods=["POST"])
def triage_case(id):
    require_roles("QualityAnalyst")
    case = _get_case(id)
    _check_case_not_terminal(case)
    if case["status"] != "INTAKE":
        raise errors.invalid_state("Only INTAKE cases can be triaged")
    body = get_json_body()
    confirm_flag = optional_bool(body, "confirm_adverse_event_flag", None)
    if confirm_flag is not None:
        case["adverse_event_flag"] = confirm_flag

    final_score = compute_triage_score(case["severity"], case["category"],
                                       case["adverse_event_flag"], provisional=False)
    case["triage_score"] = final_score
    if final_score >= ESCALATION_THRESHOLD:
        case["status"] = "ESCALATED_RECALL"
    else:
        case["status"] = "TRIAGED"
    touch(case, status_changed=True)
    _recompute_brand_score(case["brand_owner_id"])
    return success_object(serialize(case), 200)


@bp.route("/complaint-cases/<id>/open-investigation", methods=["POST"])
def open_investigation(id):
    require_roles("QualityAnalyst")
    case = _get_case(id)
    _check_case_not_terminal(case)
    if case["status"] != "TRIAGED":
        raise errors.invalid_state("Only TRIAGED cases can open an investigation")
    case["status"] = "INVESTIGATING"
    touch(case, status_changed=True)
    return success_object(serialize(case), 200)


@bp.route("/complaint-cases/<id>/resolve", methods=["POST"])
def resolve_case(id):
    require_roles("QualityAnalyst")
    case = _get_case(id)
    _check_case_not_terminal(case)
    if case["status"] != "INVESTIGATING":
        raise errors.invalid_state("Only INVESTIGATING cases can be resolved")
    case["status"] = "RESOLVED"
    touch(case, status_changed=True)
    _recompute_brand_score(case["brand_owner_id"])
    return success_object(serialize(case), 200)


@bp.route("/complaint-cases/<id>/escalate", methods=["POST"])
def escalate_case(id):
    require_roles("QAApprover")
    case = _get_case(id)
    _check_case_not_terminal(case)
    if case["status"] != "INVESTIGATING":
        raise errors.invalid_state("Only INVESTIGATING cases can be escalated")
    case["status"] = "ESCALATED_RECALL"
    touch(case, status_changed=True)
    return success_object(serialize(case), 200)


@bp.route("/complaint-cases/<id>/close-no-action", methods=["POST"])
def close_no_action(id):
    require_roles("QualityAnalyst")
    case = _get_case(id)
    _check_case_not_terminal(case)
    if case["status"] != "TRIAGED":
        raise errors.invalid_state("Only TRIAGED cases can be closed with no action")
    if case.get("adverse_event_flag"):
        raise errors.adverse_close_forbidden()
    case["status"] = "CLOSED_NO_ACTION"
    touch(case, status_changed=True)
    _recompute_brand_score(case["brand_owner_id"])
    return success_object(serialize(case), 200)
