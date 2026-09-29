"""Coverage analyses, the immutable item grid, and the compliance review loop."""

from flask import Blueprint, request

import derive
import envelope
import lookup
import serializers
import store
import validation as v
from auth import ALL_ROLES, actor, require
from errors import ApiError

bp = Blueprint("coverage", __name__, url_prefix="/research-billing")

CLASSIFICATIONS = ("ROUTINE_CARE", "RESEARCH_PAID", "PROMOTIONAL")
MEDICARE_BASES = ("STANDARD_OF_CARE", "QCT_CONDITIONAL", "NOT_COVERED")
BUDGET_CATEGORIES = ("PER_PATIENT", "INVOICEABLE", "NOT_BUDGETED")
OPEN_STATUSES = ("DRAFT", "UNDER_REVIEW", "RETURNED")
EDITABLE_STATUSES = ("DRAFT", "RETURNED")


@bp.post("/coverage-analyses")
@require("CoverageAnalyst")
def create_analysis():
    body = v.body()
    study_id = v.req_id(body, "study_id")
    expected_version = v.req_int(body, "expected_study_version")
    supersedes_id = v.opt_id(body, "supersedes_analysis_id")

    study = lookup.study(study_id)
    predecessor = lookup.analysis(supersedes_id) if supersedes_id is not None else None

    if expected_version != study["version"]:
        raise ApiError("ERR_STALE_STUDY_VERSION")

    for existing in derive.analyses_of(study["id"]):
        if existing["status"] in OPEN_STATUSES:
            raise ApiError("ERR_OPEN_ANALYSIS_EXISTS")

    rec = store.base_record()
    rec.update({
        "study_id": study["id"],
        "supersedes_analysis_id": supersedes_id,
        "revision_number": 1 if predecessor is None else predecessor["revision_number"] + 1,
        "status": "DRAFT",
        "prepared_by_user_id": actor(),
        "returned_by_user_id": None,
        "approved_by_user_id": None,
        "return_reason": None,
        "return_count": 0,
        "approved_at": None,
    })
    store.analyses[rec["id"]] = rec

    if study["lifecycle_status"] == "DRAFT":
        study["lifecycle_status"] = "COVERAGE_PENDING"
        store.touch(study)
    return envelope.created(serializers.analysis(rec))


@bp.get("/coverage-analyses")
@require(*ALL_ROLES)
def list_analyses():
    limit, offset = envelope.read_pagination(request.args)
    rows = store.by_created(store.analyses.values())
    for key in ("study_id", "supersedes_analysis_id", "status"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    page, total = envelope.page(rows, limit, offset)
    return envelope.listing([serializers.analysis(r) for r in page], limit, offset, total)


@bp.get("/coverage-analyses/<analysis_id>")
@require(*ALL_ROLES)
def get_analysis(analysis_id):
    return envelope.ok(serializers.analysis(lookup.analysis(analysis_id)))


@bp.get("/coverage-analyses/<analysis_id>/items")
@require(*ALL_ROLES)
def list_items(analysis_id):
    limit, offset = envelope.read_pagination(request.args)
    rec = lookup.analysis(analysis_id)
    rows = derive.items_of(rec["id"])
    classification = request.args.get("classification")
    if classification:
        rows = [r for r in rows if r["classification"] == classification]
    page, total = envelope.page(rows, limit, offset)
    return envelope.listing([serializers.coverage_item(r) for r in page],
                            limit, offset, total)


@bp.post("/coverage-items")
@require("CoverageAnalyst")
def create_item():
    body = v.body()
    analysis_id = v.req_id(body, "coverage_analysis_id")
    expected_version = v.req_int(body, "expected_coverage_analysis_version")
    item_code = v.req_str(body, "item_code")
    description = v.req_str(body, "description")
    classification = v.req_enum(body, "classification", CLASSIFICATIONS)
    medicare_basis = v.req_enum(body, "medicare_coverage_basis", MEDICARE_BASES)
    budget_category = v.req_enum(body, "budget_category", BUDGET_CATEGORIES)
    charge_master_unit_cents = v.req_int(body, "charge_master_unit_cents", minimum=0)
    negotiated_unit_cents = v.req_int(body, "negotiated_unit_cents", minimum=0)
    expected_occurrences = v.req_int(body, "expected_occurrences", minimum=0)
    units_per_occurrence = v.opt_int(body, "units_per_occurrence", default=1, minimum=1)

    analysis = lookup.analysis(analysis_id)

    if expected_version != analysis["version"]:
        raise ApiError("ERR_STALE_COVERAGE_ANALYSIS_VERSION")

    if analysis["status"] not in EDITABLE_STATUSES:
        raise ApiError("ERR_ANALYSIS_NOT_EDITABLE")

    study = store.studies.get(analysis["study_id"])

    if classification == "ROUTINE_CARE":
        if medicare_basis == "NOT_COVERED":
            raise ApiError("ERR_ROUTINE_CARE_REQUIRES_QCT")
        if (medicare_basis == "QCT_CONDITIONAL" and study is not None
                and study["qct_determination"] == "NON_QUALIFYING"):
            raise ApiError("ERR_ROUTINE_CARE_REQUIRES_QCT")

    for existing in derive.items_of(analysis["id"]):
        if existing["item_code"] == item_code:
            raise ApiError("ERR_DUPLICATE_ITEM_CODE")

    if classification == "PROMOTIONAL":
        if budget_category != "NOT_BUDGETED" or negotiated_unit_cents != 0:
            raise ApiError("ERR_PROMOTIONAL_MUST_BE_ZERO_COST")

    rec = store.base_record(versioned=False)
    rec.update({
        "coverage_analysis_id": analysis["id"],
        "item_code": item_code,
        "description": description,
        "classification": classification,
        "medicare_coverage_basis": medicare_basis,
        "billable_to": derive.BILLABLE_BY_CLASSIFICATION[classification],
        "budget_category": budget_category,
        "charge_master_unit_cents": charge_master_unit_cents,
        "negotiated_unit_cents": negotiated_unit_cents,
        "units_per_occurrence": units_per_occurrence,
        "expected_occurrences": expected_occurrences,
    })
    store.coverage_items[rec["id"]] = rec

    if analysis["status"] == "RETURNED":
        analysis["status"] = "DRAFT"
    store.touch(analysis)
    return envelope.created(serializers.coverage_item(rec))


@bp.post("/coverage-analyses/<analysis_id>/submit")
@require("CoverageAnalyst")
def submit_analysis(analysis_id):
    rec = lookup.analysis(analysis_id)
    if rec["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if not derive.items_of(rec["id"]):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    rec["status"] = "UNDER_REVIEW"
    store.touch(rec)
    return envelope.ok(serializers.analysis(rec))


@bp.post("/coverage-analyses/<analysis_id>/return")
@require("ComplianceReviewer")
def return_analysis(analysis_id):
    body = v.body()
    return_reason = v.req_str(body, "return_reason")

    rec = lookup.analysis(analysis_id)
    if rec["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_ANALYSIS_NOT_UNDER_REVIEW")
    if rec["return_count"] >= derive.ANALYSIS_MAX_RETURNS:
        raise ApiError("ERR_RETURN_LIMIT_EXCEEDED")

    rec["status"] = "RETURNED"
    rec["return_reason"] = return_reason
    rec["returned_by_user_id"] = actor()
    rec["return_count"] += 1
    store.touch(rec)
    return envelope.ok(serializers.analysis(rec))


@bp.post("/coverage-analyses/<analysis_id>/approve")
@require("ComplianceReviewer")
def approve_analysis(analysis_id):
    rec = lookup.analysis(analysis_id)
    if rec["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_ANALYSIS_NOT_UNDER_REVIEW")
    if actor() == rec["prepared_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    study = store.studies.get(rec["study_id"])
    counters = derive.analysis_counters(rec["id"])
    if counters["qct_conditional_item_count"] >= 1:
        if study is None or study["qct_determination"] == "UNDETERMINED":
            raise ApiError("ERR_QCT_DETERMINATION_REQUIRED")

    rec["status"] = "APPROVED"
    rec["approved_at"] = store.now()
    rec["approved_by_user_id"] = actor()
    store.touch(rec)

    if rec["supersedes_analysis_id"]:
        predecessor = store.analyses.get(rec["supersedes_analysis_id"])
        if predecessor is not None and predecessor["status"] == "APPROVED":
            predecessor["status"] = "SUPERSEDED"
            store.touch(predecessor)

    if study is not None:
        if study["lifecycle_status"] == "COVERAGE_PENDING":
            study["lifecycle_status"] = "COVERAGE_APPROVED"
        store.touch(study)
    return envelope.ok(serializers.analysis(rec))
