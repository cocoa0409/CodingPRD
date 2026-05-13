"""Project + TenderDocument lifecycle."""

from clock import clock, parse_iso
from db import bump_version, common_fields_create, db, touch
from errors import (
    ERR_INVALID_STATE,
    ERR_INVALID_TIME_WINDOW,
    ERR_NOT_FOUND,
    ERR_PLAN_ITEM_NOT_PUBLISHED,
    ERR_REFERENCE_NOT_FOUND,
    ERR_VALIDATION,
    ERR_WEIGHTS_INVALID,
    raise_error,
)
from services.plan import get_plan_item_or_ref_404, recompute_total_budget
from services.supplier import prescreen_eligibility


EPSILON = 1.0e-9


def get_project_or_404(project_id: str) -> dict:
    p = db.projects.get(project_id)
    if not p:
        raise_error(ERR_NOT_FOUND, f"project '{project_id}' not found")
    return p


def get_project_or_ref_404(project_id: str) -> dict:
    p = db.projects.get(project_id)
    if not p:
        raise_error(ERR_REFERENCE_NOT_FOUND, f"project '{project_id}' not found")
    return p


def get_tender_doc_or_404(doc_id: str) -> dict:
    d = db.tender_documents.get(doc_id)
    if not d:
        raise_error(ERR_NOT_FOUND, f"tender_document '{doc_id}' not found")
    return d


def _validate_time_window(qwc: str, deadline: str, opening: str):
    try:
        qwc_dt = parse_iso(qwc)
        deadline_dt = parse_iso(deadline)
        opening_dt = parse_iso(opening)
    except Exception:
        raise_error(ERR_INVALID_TIME_WINDOW, "invalid ISO timestamp in time window")
    if not (qwc_dt < deadline_dt):
        raise_error(ERR_INVALID_TIME_WINDOW, "query_window_close_at must be < bid_submission_deadline")
    if not (deadline_dt < opening_dt):
        raise_error(ERR_INVALID_TIME_WINDOW, "bid_submission_deadline must be < bid_opening_at")


def create_project(body: dict):
    plan_item_id = body.get("plan_item_id")
    if not isinstance(plan_item_id, str) or not plan_item_id:
        raise_error(ERR_VALIDATION, "plan_item_id is required")
    title = body.get("title")
    if not isinstance(title, str) or not title:
        raise_error(ERR_VALIDATION, "title must be non-empty string")
    em = body.get("evaluation_method")
    if em not in {"LOWEST_PRICE", "COMPREHENSIVE_SCORING"}:
        raise_error(ERR_VALIDATION, "evaluation_method invalid")
    deadline = body.get("bid_submission_deadline")
    qwc = body.get("query_window_close_at")
    opening = body.get("bid_opening_at")
    if not (isinstance(deadline, str) and isinstance(qwc, str) and isinstance(opening, str)):
        raise_error(ERR_VALIDATION, "time fields must be ISO strings")
    _validate_time_window(qwc, deadline, opening)
    est = body.get("estimated_value_cents")
    if isinstance(est, bool) or not isinstance(est, int) or est <= 0:
        raise_error(ERR_VALIDATION, "estimated_value_cents must be positive integer")
    rq = body.get("required_qualifications", [])
    if not isinstance(rq, list):
        raise_error(ERR_VALIDATION, "required_qualifications must be array")
    # Resolve plan item (reference not found if missing)
    item = get_plan_item_or_ref_404(plan_item_id)
    if item["item_status"] != "PUBLISHED":
        raise_error(ERR_PLAN_ITEM_NOT_PUBLISHED, "plan item not PUBLISHED")
    p = {
        "id": db.new_id(),
        **common_fields_create(),
        "plan_item_id": plan_item_id,
        "title": title,
        "project_status": "DRAFT",
        "evaluation_method": em,
        "bid_submission_deadline": deadline,
        "query_window_close_at": qwc,
        "bid_opening_at": opening,
        "estimated_value_cents": int(est),
        "required_qualifications": list(rq),
        "frozen_reason": None,
    }
    db.projects[p["id"]] = p
    return p


def _validate_evaluation_criteria(em: str, ec):
    if not isinstance(ec, dict):
        raise_error(ERR_VALIDATION, "evaluation_criteria must be object")
    if em == "LOWEST_PRICE":
        if ec.get("tie_break") != "earliest_bid":
            raise_error(ERR_VALIDATION, "tie_break must be 'earliest_bid'")
        return
    if em == "COMPREHENSIVE_SCORING":
        wp = ec.get("weight_price")
        wt = ec.get("weight_technical")
        wq = ec.get("weight_qualification")
        for name, v in (("weight_price", wp), ("weight_technical", wt), ("weight_qualification", wq)):
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                raise_error(ERR_WEIGHTS_INVALID, f"{name} missing or non-numeric")
            if not (0.0 < float(v) < 1.0):
                raise_error(ERR_WEIGHTS_INVALID, f"{name} must be strictly between 0 and 1")
        total = float(wp) + float(wt) + float(wq)
        if abs(total - 1.0) > EPSILON:
            raise_error(ERR_WEIGHTS_INVALID, "weights must sum to 1.0 within 1e-9")
        mts = ec.get("max_technical_score")
        if mts is None or isinstance(mts, bool) or not isinstance(mts, (int, float)) or mts <= 0:
            raise_error(ERR_VALIDATION, "max_technical_score must be positive number")
        mqs = ec.get("max_qualification_score")
        if mqs is None or isinstance(mqs, bool) or not isinstance(mqs, (int, float)) or mqs <= 0:
            raise_error(ERR_VALIDATION, "max_qualification_score must be positive number")


def create_tender_document(project_id: str, body: dict):
    project = get_project_or_404(project_id)
    if project["project_status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "project must be DRAFT")
    if project_id in db.tender_by_project:
        raise_error(ERR_INVALID_STATE, "tender document already exists for project")
    template_id = body.get("template_id")
    technical_spec = body.get("technical_spec")
    commercial_spec = body.get("commercial_spec")
    evaluation_criteria = body.get("evaluation_criteria")
    if not isinstance(template_id, str) or not template_id:
        raise_error(ERR_VALIDATION, "template_id must be non-empty string")
    if not isinstance(technical_spec, str) or not technical_spec:
        raise_error(ERR_VALIDATION, "technical_spec must be non-empty string")
    if not isinstance(commercial_spec, str) or not commercial_spec:
        raise_error(ERR_VALIDATION, "commercial_spec must be non-empty string")
    _validate_evaluation_criteria(project["evaluation_method"], evaluation_criteria)
    doc = {
        "id": db.new_id(),
        **common_fields_create(),
        "project_id": project_id,
        "template_id": template_id,
        "version": 1,
        "doc_status": "DRAFT",
        "technical_spec": technical_spec,
        "commercial_spec": commercial_spec,
        "qualification_requirements": [],
        "evaluation_criteria": evaluation_criteria,
        "pinned_at": None,
    }
    db.tender_documents[doc["id"]] = doc
    db.tender_by_project[project_id] = doc["id"]
    bump_version(project)
    return doc


def publish_tender_document(doc_id: str):
    doc = get_tender_doc_or_404(doc_id)
    project = get_project_or_404(doc["project_id"])
    if doc["doc_status"] == "DRAFT":
        if project["project_status"] != "DRAFT":
            raise_error(ERR_INVALID_STATE, "project must be DRAFT for initial publish")
        # Re-validate weights at publish per validation #13
        _validate_evaluation_criteria(project["evaluation_method"], doc["evaluation_criteria"])
        doc["doc_status"] = "PUBLISHED"
        doc["pinned_at"] = clock.now_iso()
        doc["qualification_requirements"] = list(project.get("required_qualifications") or [])
        project["project_status"] = "PRESCREEN_OPEN"
        bump_version(project)
        touch(doc)
        return doc
    if doc["doc_status"] == "AMENDING":
        if project["project_status"] != "PRESCREEN_OPEN":
            raise_error(ERR_INVALID_STATE, "project must be PRESCREEN_OPEN to re-publish amended tender")
        _validate_evaluation_criteria(project["evaluation_method"], doc["evaluation_criteria"])
        doc["doc_status"] = "PUBLISHED"
        doc["version"] = int(doc["version"]) + 1
        doc["pinned_at"] = clock.now_iso()
        touch(doc)
        return doc
    raise_error(ERR_INVALID_STATE, "cannot publish tender from current state")


def clarify_tender_document(doc_id: str, body: dict):
    doc = get_tender_doc_or_404(doc_id)
    if doc["doc_status"] != "PUBLISHED":
        raise_error(ERR_INVALID_STATE, "tender must be PUBLISHED to clarify")
    project = get_project_or_404(doc["project_id"])
    # Clock must be strictly before query_window_close_at
    try:
        qwc = parse_iso(project["query_window_close_at"])
    except Exception:
        raise_error(ERR_VALIDATION, "invalid project query_window_close_at")
    if not (clock.now() < qwc):
        raise_error(ERR_INVALID_STATE, "query window already closed")
    note = body.get("clarification_note", "")
    if note is not None and not isinstance(note, str):
        raise_error(ERR_VALIDATION, "clarification_note must be string")
    doc["doc_status"] = "CLARIFYING"
    touch(doc)
    return doc


def finalize_clarification(doc_id: str):
    doc = get_tender_doc_or_404(doc_id)
    if doc["doc_status"] != "CLARIFYING":
        raise_error(ERR_INVALID_STATE, "tender must be CLARIFYING to finalize")
    doc["doc_status"] = "PUBLISHED"
    doc["pinned_at"] = clock.now_iso()
    touch(doc)
    return doc


def begin_tender_amendment(doc_id: str):
    doc = get_tender_doc_or_404(doc_id)
    if doc["doc_status"] != "PUBLISHED":
        raise_error(ERR_INVALID_STATE, "tender must be PUBLISHED")
    project = get_project_or_404(doc["project_id"])
    if project["project_status"] not in {"PRESCREEN_OPEN", "BIDDING_OPEN"}:
        raise_error(ERR_INVALID_STATE, "project must be PRESCREEN_OPEN or BIDDING_OPEN")
    try:
        deadline = parse_iso(project["bid_submission_deadline"])
    except Exception:
        raise_error(ERR_VALIDATION, "invalid bid_submission_deadline")
    if not (clock.now() < deadline):
        raise_error(ERR_INVALID_STATE, "bid submission deadline already passed")
    doc["doc_status"] = "AMENDING"
    touch(doc)
    # If project was BIDDING_OPEN, revert to PRESCREEN_OPEN
    if project["project_status"] == "BIDDING_OPEN":
        project["project_status"] = "PRESCREEN_OPEN"
        bump_version(project)
    # Force all SUBMITTED bids on this project to WITHDRAWN
    for bid in db.bids.values():
        if bid["project_id"] == project["id"] and bid["bid_status"] == "SUBMITTED":
            bid["bid_status"] = "WITHDRAWN"
            bump_version(bid)
    return doc


def open_bidding(project_id: str):
    project = get_project_or_404(project_id)
    if project["project_status"] != "PRESCREEN_OPEN":
        raise_error(ERR_INVALID_STATE, "project must be PRESCREEN_OPEN")
    doc_id = db.tender_by_project.get(project_id)
    if not doc_id:
        raise_error(ERR_INVALID_STATE, "no tender document on project")
    doc = db.tender_documents[doc_id]
    if doc["doc_status"] != "PUBLISHED":
        raise_error(ERR_INVALID_STATE, "tender document must be PUBLISHED")
    try:
        deadline = parse_iso(project["bid_submission_deadline"])
    except Exception:
        raise_error(ERR_VALIDATION, "invalid bid_submission_deadline")
    if not (clock.now() < deadline):
        raise_error(ERR_INVALID_STATE, "bid submission deadline already passed")
    project["project_status"] = "BIDDING_OPEN"
    bump_version(project)
    return project


def close_bidding(project_id: str):
    project = get_project_or_404(project_id)
    if project["project_status"] != "BIDDING_OPEN":
        raise_error(ERR_INVALID_STATE, "project must be BIDDING_OPEN")
    try:
        deadline = parse_iso(project["bid_submission_deadline"])
    except Exception:
        raise_error(ERR_VALIDATION, "invalid bid_submission_deadline")
    if not (clock.now() >= deadline):
        raise_error(ERR_INVALID_STATE, "bid submission deadline not yet reached")
    project["project_status"] = "BIDDING_CLOSED"
    bump_version(project)
    # Re-check pre-screen on all SUBMITTED bids; failures -> DISQUALIFIED
    for bid in db.bids.values():
        if bid["project_id"] == project_id and bid["bid_status"] == "SUBMITTED":
            supplier = db.suppliers.get(bid["supplier_id"])
            passes = prescreen_eligibility(supplier, project) if supplier else False
            if not passes:
                bid["bid_status"] = "DISQUALIFIED"
                bump_version(bid)
    return project


def cancel_project(project_id: str):
    project = get_project_or_404(project_id)
    if project["project_status"] not in {"PRESCREEN_OPEN", "BIDDING_OPEN"}:
        raise_error(ERR_INVALID_STATE, "project must be PRESCREEN_OPEN or BIDDING_OPEN")
    was_bidding_open = project["project_status"] == "BIDDING_OPEN"
    project["project_status"] = "CANCELLED"
    bump_version(project)
    # TenderDocument -> SUPERSEDED
    doc_id = db.tender_by_project.get(project_id)
    if doc_id:
        doc = db.tender_documents[doc_id]
        doc["doc_status"] = "SUPERSEDED"
        touch(doc)
    if was_bidding_open:
        for bid in db.bids.values():
            if bid["project_id"] == project_id and bid["bid_status"] == "SUBMITTED":
                bid["bid_status"] = "WITHDRAWN"
                bump_version(bid)
    return project


def prescreen_results(project_id: str):
    """Returns a snapshot of suppliers currently eligible for this project."""
    project = get_project_or_404(project_id)
    if project["project_status"] not in {"PRESCREEN_OPEN", "BIDDING_OPEN", "BIDDING_CLOSED", "EVALUATING"}:
        raise_error(ERR_INVALID_STATE, "project not in a state where pre-screen can be published")
    qualifying = []
    for s in db.suppliers.values():
        if prescreen_eligibility(s, project):
            qualifying.append({
                "supplier_id": s["id"],
                "legal_name": s["legal_name"],
                "credit_score": s["credit_score"],
                "qualifications": list(s.get("qualifications") or []),
            })
    return {
        "project_id": project_id,
        "qualifying_suppliers": qualifying,
        "snapshot_at": clock.now_iso(),
    }
