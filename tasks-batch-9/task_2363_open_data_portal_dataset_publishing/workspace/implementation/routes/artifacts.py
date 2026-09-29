"""Publication artefacts: metadata records and privacy assessments."""

from flask import Blueprint, request

import calc
import services
from common import bad_state, dept_scope, find
from core import (
    body,
    caller,
    db,
    err,
    new_row,
    now,
    ok,
    opt_enum,
    opt_int,
    opt_str,
    page,
    req_enum,
    req_int,
    req_str,
    touch,
)

bp = Blueprint("artifacts", __name__)

METADATA_STATUSES = ("DRAFT", "SUBMITTED", "ACCEPTED", "RETURNED")
ASSESSMENT_STATUSES = ("DRAFT", "SUBMITTED", "CLEARED", "BLOCKED")


def _bool_filter(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    err("ERR_INVALID_REQUEST", "%s must be a boolean." % name)


# --------------------------------------------------------------------------
# Metadata records
# --------------------------------------------------------------------------
def rescore_metadata(record):
    dataset = db.datasets.get(record["dataset_id"])
    license_row = db.licenses.get(record["license_id"])
    contributions, score = calc.metadata_completeness(record, dataset, license_row)
    record["component_contributions"] = contributions
    record["completeness_score"] = score


@bp.post("/metadata-records")
def create_metadata():
    role, user_id = caller("DataCoordinator")
    data = body()
    dataset_id = req_str(data, "dataset_id")
    license_id = req_str(data, "license_id")
    dictionary_fields = req_int(data, "data_dictionary_field_count", 0)
    provenance_lines = req_int(data, "provenance_detail_lines", 0)
    contact_email = req_str(data, "contact_email")
    declared_frequency = req_enum(data, "declared_update_frequency", calc.UPDATE_FREQUENCIES)
    attribution_elements = opt_int(data, "attribution_element_count", 0, 6, 0)
    dataset = find("datasets", dataset_id)
    find("licenses", license_id)
    dept_scope(user_id, dataset["department_id"])
    for existing in services.metadata_of_dataset(dataset_id, ("DRAFT", "SUBMITTED", "ACCEPTED")):
        err(
            "ERR_METADATA_RECORD_EXISTS",
            "The dataset already holds an open metadata record.",
        )
    row = new_row()
    row.update(
        {
            "dataset_id": dataset_id,
            "license_id": license_id,
            "data_dictionary_field_count": dictionary_fields,
            "provenance_detail_lines": provenance_lines,
            "contact_email": contact_email,
            "declared_update_frequency": declared_frequency,
            "attribution_element_count": attribution_elements,
            "component_contributions": [],
            "completeness_score": calc.ZERO,
            "returned_reason": None,
            "status": "DRAFT",
        }
    )
    rescore_metadata(row)
    db.metadata_records[row["id"]] = row
    return ok(services.metadata_out(row), 201)


@bp.get("/metadata-records")
def list_metadata():
    caller()
    dataset_id = request.args.get("dataset_id")
    license_id = request.args.get("license_id")
    status = request.args.get("status")
    if status is not None and status not in METADATA_STATUSES:
        err("ERR_INVALID_REQUEST", "status must be one of %s." % ", ".join(METADATA_STATUSES))
    rows = list(db.metadata_records.values())
    if dataset_id is not None:
        rows = [r for r in rows if r["dataset_id"] == dataset_id]
    if license_id is not None:
        rows = [r for r in rows if r["license_id"] == license_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return page(rows, services.metadata_out)


@bp.get("/metadata-records/<metadata_record_id>")
def get_metadata(metadata_record_id):
    caller()
    return ok(services.metadata_out(find("metadata_records", metadata_record_id)))


@bp.patch("/metadata-records/<metadata_record_id>")
def patch_metadata(metadata_record_id):
    role, user_id = caller("DataCoordinator")
    record = find("metadata_records", metadata_record_id)
    data = body()
    license_id = opt_str(data, "license_id")
    dictionary_fields = opt_int(data, "data_dictionary_field_count", 0)
    provenance_lines = opt_int(data, "provenance_detail_lines", 0)
    contact_email = opt_str(data, "contact_email")
    declared_frequency = opt_enum(data, "declared_update_frequency", calc.UPDATE_FREQUENCIES)
    attribution_elements = opt_int(data, "attribution_element_count", 0, 6)
    dataset = db.datasets.get(record["dataset_id"])
    dept_scope(user_id, dataset["department_id"] if dataset else None)
    if license_id is not None:
        find("licenses", license_id)
    if record["status"] not in ("DRAFT", "RETURNED"):
        bad_state("Only a DRAFT or RETURNED metadata record may be revised.")
    if license_id is not None:
        record["license_id"] = license_id
    if dictionary_fields is not None:
        record["data_dictionary_field_count"] = dictionary_fields
    if provenance_lines is not None:
        record["provenance_detail_lines"] = provenance_lines
    if contact_email is not None:
        record["contact_email"] = contact_email
    if declared_frequency is not None:
        record["declared_update_frequency"] = declared_frequency
    if attribution_elements is not None:
        record["attribution_element_count"] = attribution_elements
    if record["status"] == "RETURNED":
        record["status"] = "DRAFT"
        record["returned_reason"] = None
    rescore_metadata(record)
    touch(record)
    return ok(services.metadata_out(record))


@bp.post("/metadata-records/<metadata_record_id>/submit")
def submit_metadata(metadata_record_id):
    role, user_id = caller("DataCoordinator")
    record = find("metadata_records", metadata_record_id)
    dataset = db.datasets.get(record["dataset_id"])
    dept_scope(user_id, dataset["department_id"] if dataset else None)
    if record["status"] != "DRAFT":
        bad_state("Only a DRAFT metadata record may be submitted.")
    if dataset is None or dataset["publication_status"] != "SCREENING":
        bad_state("The dataset must be in SCREENING to submit its metadata record.")
    record["status"] = "SUBMITTED"
    rescore_metadata(record)
    touch(record)
    return ok(services.metadata_out(record))


@bp.post("/metadata-records/<metadata_record_id>/decide")
def decide_metadata(metadata_record_id):
    caller("PortalAdmin")
    record = find("metadata_records", metadata_record_id)
    data = body()
    decision = req_enum(data, "decision", ("ACCEPT", "RETURN"))
    returned_reason = opt_str(data, "returned_reason")
    if decision == "RETURN" and (returned_reason is None or not returned_reason.strip()):
        err("ERR_INVALID_REQUEST", "returned_reason is required when returning a record.")
    if record["status"] != "SUBMITTED":
        bad_state("Only a SUBMITTED metadata record may be decided.")
    if decision == "ACCEPT":
        license_row = db.licenses.get(record["license_id"])
        if license_row is not None and license_row["retired"]:
            err("ERR_LICENSE_RETIRED", "The backing licence has been retired.")
        if calc.D(record["completeness_score"]) < calc.METADATA_ACCEPT_MIN:
            err(
                "ERR_METADATA_INCOMPLETE",
                "completeness_score must be at least 85.00 to accept the record.",
            )
        if (
            license_row is not None
            and license_row["attribution_required"]
            and record["attribution_element_count"] < 1
        ):
            err(
                "ERR_ATTRIBUTION_MISSING",
                "The licence requires attribution but no attribution element is filled in.",
            )
        record["status"] = "ACCEPTED"
    else:
        record["status"] = "RETURNED"
        record["returned_reason"] = returned_reason
    touch(record)
    return ok(services.metadata_out(record))


# --------------------------------------------------------------------------
# Privacy assessments
# --------------------------------------------------------------------------
def rescore_assessment(assessment, variant):
    dataset = db.datasets.get(assessment["dataset_id"])
    sensitivity = dataset["sensitivity_class"] if dataset else "SENSITIVE"
    verified = assessment["verified_smallest_cell_size"]
    declared = assessment["declared_smallest_cell_size"]
    if variant == "SCREENING":
        cell_size = declared
    else:
        cell_size = verified if verified is not None else declared
    score = calc.reidentification_risk(
        assessment["declared_quasi_identifier_count"],
        cell_size,
        assessment["population_size"],
        sensitivity,
        variant,
    )
    if variant == "SCREENING":
        assessment["screening_risk_score"] = score
    else:
        assessment["clearance_risk_score"] = score
    refresh_derived(assessment)
    return score


def refresh_derived(assessment):
    verified = assessment["verified_smallest_cell_size"]
    assessment["k_anonymity_k"] = (
        verified if verified is not None else assessment["declared_smallest_cell_size"]
    )
    if assessment["status"] == "DRAFT" or assessment["clearance_risk_score"] is None:
        current = assessment["screening_risk_score"]
    else:
        current = assessment["clearance_risk_score"]
    assessment["risk_score"] = current
    assessment["aggregation_required"] = calc.aggregation_required(current)
    assessment["min_aggregation_geography"] = calc.min_aggregation_geography(current)


@bp.post("/privacy-assessments")
def create_assessment():
    role, user_id = caller("PrivacyReviewer")
    data = body()
    dataset_id = req_str(data, "dataset_id")
    qi_count = req_int(data, "declared_quasi_identifier_count", 0, 20)
    declared_cell = req_int(data, "declared_smallest_cell_size", 1)
    population = req_int(data, "population_size", 1)
    find("datasets", dataset_id)
    for existing in services.assessments_of_dataset(
        dataset_id, ("DRAFT", "SUBMITTED", "CLEARED")
    ):
        err("ERR_ASSESSMENT_EXISTS", "The dataset already holds an open privacy assessment.")
    row = new_row()
    row.update(
        {
            "dataset_id": dataset_id,
            "assessor_user_id": user_id,
            "decided_by_user_id": None,
            "declared_quasi_identifier_count": qi_count,
            "declared_smallest_cell_size": declared_cell,
            "verified_smallest_cell_size": None,
            "population_size": population,
            "k_anonymity_k": declared_cell,
            "screening_risk_score": calc.ZERO,
            "clearance_risk_score": None,
            "risk_score": calc.ZERO,
            "aggregation_required": False,
            "min_aggregation_geography": "BLOCK",
            "block_reason": None,
            "status": "DRAFT",
        }
    )
    rescore_assessment(row, "SCREENING")
    db.assessments[row["id"]] = row
    return ok(services.assessment_out(row), 201)


@bp.get("/privacy-assessments")
def list_assessments():
    caller("DataCoordinator", "PrivacyReviewer", "PortalAdmin")
    dataset_id = request.args.get("dataset_id")
    status = request.args.get("status")
    if status is not None and status not in ASSESSMENT_STATUSES:
        err("ERR_INVALID_REQUEST", "status must be one of %s." % ", ".join(ASSESSMENT_STATUSES))
    aggregation = _bool_filter("aggregation_required")
    rows = list(db.assessments.values())
    if dataset_id is not None:
        rows = [r for r in rows if r["dataset_id"] == dataset_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if aggregation is not None:
        rows = [r for r in rows if r["aggregation_required"] == aggregation]
    return page(rows, services.assessment_out)


@bp.get("/privacy-assessments/<assessment_id>")
def get_assessment(assessment_id):
    caller("DataCoordinator", "PrivacyReviewer", "PortalAdmin")
    return ok(services.assessment_out(find("assessments", assessment_id)))


@bp.patch("/privacy-assessments/<assessment_id>")
def patch_assessment(assessment_id):
    caller("PrivacyReviewer")
    assessment = find("assessments", assessment_id)
    data = body()
    verified = opt_int(data, "verified_smallest_cell_size", 1)
    qi_count = opt_int(data, "declared_quasi_identifier_count", 0, 20)
    declared_cell = opt_int(data, "declared_smallest_cell_size", 1)
    population = opt_int(data, "population_size", 1)
    if assessment["status"] != "DRAFT":
        bad_state("Only a DRAFT privacy assessment may be revised.")
    if verified is not None:
        assessment["verified_smallest_cell_size"] = verified
    if qi_count is not None:
        assessment["declared_quasi_identifier_count"] = qi_count
    if declared_cell is not None:
        assessment["declared_smallest_cell_size"] = declared_cell
    if population is not None:
        assessment["population_size"] = population
    rescore_assessment(assessment, "SCREENING")
    touch(assessment)
    return ok(services.assessment_out(assessment))


@bp.post("/privacy-assessments/<assessment_id>/submit")
def submit_assessment(assessment_id):
    caller("PrivacyReviewer")
    assessment = find("assessments", assessment_id)
    dataset = db.datasets.get(assessment["dataset_id"])
    if assessment["status"] != "DRAFT":
        bad_state("Only a DRAFT privacy assessment may be submitted.")
    if dataset is None or dataset["publication_status"] != "SCREENING":
        bad_state("The dataset must be in SCREENING to submit its privacy assessment.")
    if assessment["verified_smallest_cell_size"] is None:
        err(
            "ERR_VERIFIED_CELL_SIZE_MISSING",
            "verified_smallest_cell_size must be measured before submission.",
        )
    assessment["status"] = "SUBMITTED"
    rescore_assessment(assessment, "CLEARANCE")
    touch(assessment)
    return ok(services.assessment_out(assessment))


@bp.post("/privacy-assessments/<assessment_id>/decide")
def decide_assessment(assessment_id):
    role, user_id = caller("PrivacyReviewer")
    assessment = find("assessments", assessment_id)
    data = body()
    decision = req_enum(data, "decision", ("CLEAR", "BLOCK"))
    block_reason = opt_enum(data, "block_reason", calc.BLOCK_REASONS)
    if decision == "BLOCK" and block_reason is None:
        err("ERR_INVALID_REQUEST", "block_reason is required when blocking an assessment.")
    if user_id == assessment["assessor_user_id"]:
        err(
            "ERR_SEGREGATION_OF_DUTIES",
            "The assessment's author may not decide its clearance.",
        )
    if assessment["status"] != "SUBMITTED":
        bad_state("Only a SUBMITTED privacy assessment may be decided.")
    if decision == "CLEAR":
        score = assessment["clearance_risk_score"]
        if score is None or calc.D(score) >= calc.CLEARANCE_RISK_MAX:
            err(
                "ERR_REIDENTIFICATION_RISK_TOO_HIGH",
                "clearance_risk_score must be below 60.00 to clear the assessment.",
            )
        assessment["status"] = "CLEARED"
    else:
        assessment["status"] = "BLOCKED"
        assessment["block_reason"] = block_reason
    assessment["decided_by_user_id"] = user_id
    refresh_derived(assessment)
    touch(assessment)
    return ok(services.assessment_out(assessment))


@bp.post("/privacy-assessments/<assessment_id>/reopen")
def reopen_assessment(assessment_id):
    caller("PrivacyReviewer")
    assessment = find("assessments", assessment_id)
    dataset = db.datasets.get(assessment["dataset_id"])
    if assessment["status"] != "BLOCKED":
        bad_state("Only a BLOCKED privacy assessment may be reopened.")
    if dataset is None or dataset["publication_status"] != "SCREENING":
        bad_state("The dataset must still be in SCREENING to reopen the assessment.")
    assessment["status"] = "DRAFT"
    assessment["block_reason"] = None
    assessment["clearance_risk_score"] = None
    assessment["decided_by_user_id"] = None
    refresh_derived(assessment)
    touch(assessment)
    return ok(services.assessment_out(assessment))
