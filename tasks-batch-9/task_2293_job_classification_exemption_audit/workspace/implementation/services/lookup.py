"""Existence resolution (PRD 2.7 ranks 3 and 5) and cascade version bookkeeping."""
import db
from errors import fail
from services import derive


def _get(collection, entity_id, error_id):
    if not isinstance(entity_id, str):
        fail(error_id)
    row = collection.get(entity_id)
    if row is None:
        fail(error_id)
    return row


def project(entity_id):
    return _get(db.audit_projects, entity_id, "ERR_AUDIT_PROJECT_NOT_FOUND")


def family(entity_id):
    return _get(db.job_families, entity_id, "ERR_JOB_FAMILY_NOT_FOUND")


def position(entity_id):
    return _get(db.positions, entity_id, "ERR_POSITION_NOT_FOUND")


def interview(entity_id):
    return _get(db.interviews, entity_id, "ERR_INTERVIEW_NOT_FOUND")


def analysis(entity_id):
    return _get(db.exemption_analyses, entity_id, "ERR_ANALYSIS_NOT_FOUND")


def case(entity_id):
    return _get(db.reclassification_cases, entity_id, "ERR_RECLASS_CASE_NOT_FOUND")


def correction(entity_id):
    return _get(db.voluntary_corrections, entity_id, "ERR_CORRECTION_NOT_FOUND")


def contractor_review(entity_id):
    return _get(db.contractor_reviews, entity_id, "ERR_CONTRACTOR_REVIEW_NOT_FOUND")


# ------------------------------------------------------------------- cascades
def touch_position_chain(position_row, include_project=True, include_family=True):
    """PRD 2.8: recomputation is transitive and ordered — position, then its
    family, then the engagement. Each row touched is a real mutation."""
    db.touch(position_row)
    family_row = derive.family_of_position(position_row)
    if family_row is not None and include_family:
        db.touch(family_row)
    if family_row is not None and include_project:
        project_row = derive.project_of_family(family_row)
        if project_row is not None:
            db.touch(project_row)
