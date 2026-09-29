"""Path/body resolution helpers shared by the route modules.

Ownership (ladder step 2) is evaluated before the not-found report (step 4), so
a resource that resolves is scope-checked first and an unresolved id falls
through to its own 404 code.
"""
import auth
import calc
from db import db
from errors import ApiError


def _resolve(table, record_id, not_found_error, scope_getter=None):
    record = table.get(record_id) if isinstance(record_id, str) else None
    if record is not None and scope_getter is not None:
        auth.require_association_scope(scope_getter(record))
    if record is None:
        raise ApiError(not_found_error)
    return record


def association_or_404(association_id, scoped=False):
    return _resolve(
        db.associations,
        association_id,
        "ERR_ASSOCIATION_NOT_FOUND",
        (lambda record: record["id"]) if scoped else None,
    )


def turnover_case_or_404(case_id, scoped=False):
    return _resolve(
        db.turnover_cases,
        case_id,
        "ERR_TURNOVER_CASE_NOT_FOUND",
        (lambda record: record["association_id"]) if scoped else None,
    )


def lot_or_404(lot_id, scoped=False):
    return _resolve(
        db.lots,
        lot_id,
        "ERR_LOT_NOT_FOUND",
        (lambda record: record["association_id"]) if scoped else None,
    )


def component_or_404(component_id, scoped=False):
    return _resolve(
        db.components,
        component_id,
        "ERR_COMPONENT_NOT_FOUND",
        (lambda record: record["association_id"]) if scoped else None,
    )


def reserve_study_or_404(study_id, scoped=False):
    return _resolve(
        db.reserve_studies,
        study_id,
        "ERR_RESERVE_STUDY_NOT_FOUND",
        (lambda record: record["association_id"]) if scoped else None,
    )


def subsidy_entry_or_404(entry_id, scoped=False):
    return _resolve(
        db.subsidy_entries,
        entry_id,
        "ERR_SUBSIDY_ENTRY_NOT_FOUND",
        (lambda record: record["association_id"]) if scoped else None,
    )


def audit_engagement_or_404(engagement_id, scoped=False):
    return _resolve(
        db.audit_engagements,
        engagement_id,
        "ERR_AUDIT_ENGAGEMENT_NOT_FOUND",
        (lambda record: record["association_id"]) if scoped else None,
    )


def defect_claim_or_404(claim_id, scoped=False):
    return _resolve(
        db.defect_claims,
        claim_id,
        "ERR_DEFECT_CLAIM_NOT_FOUND",
        (lambda record: record["association_id"]) if scoped else None,
    )


def vendor_contract_or_404(contract_id, scoped=False):
    return _resolve(
        db.vendor_contracts,
        contract_id,
        "ERR_VENDOR_CONTRACT_NOT_FOUND",
        (lambda record: record["association_id"]) if scoped else None,
    )


def records_item_or_404(item_id, scoped=False):
    def association_of(record):
        case = db.turnover_cases.get(record["turnover_case_id"])
        return case["association_id"] if case else None

    return _resolve(
        db.records_items,
        item_id,
        "ERR_RECORDS_ITEM_NOT_FOUND",
        association_of if scoped else None,
    )


def director_or_404(director_id, scoped=False):
    def association_of(record):
        case = db.turnover_cases.get(record["turnover_case_id"])
        return case["association_id"] if case else None

    return _resolve(
        db.directors,
        director_id,
        "ERR_DIRECTOR_NOT_FOUND",
        association_of if scoped else None,
    )


def assessment_schedule_or_404(schedule_id, scoped=False):
    return _resolve(
        db.assessment_schedules,
        schedule_id,
        "ERR_ASSESSMENT_SCHEDULE_NOT_FOUND",
        (lambda record: record["association_id"]) if scoped else None,
    )


def body_association_or_404(association_id):
    """Body foreign key resolution (ladder step 5)."""
    if association_id is None:
        return None
    association = db.associations.get(association_id)
    if association is None:
        raise ApiError("ERR_ASSOCIATION_NOT_FOUND")
    auth.require_association_scope(association["id"])
    return association


def body_turnover_case_or_404(case_id):
    if case_id is None:
        return None
    case = db.turnover_cases.get(case_id)
    if case is None:
        raise ApiError("ERR_TURNOVER_CASE_NOT_FOUND")
    auth.require_association_scope(case["association_id"])
    return case


def body_component_or_404(component_id, association_id):
    """A component that resolves to another association is ERR_COMPONENT_NOT_FOUND."""
    if component_id is None:
        return None
    component = db.components.get(component_id)
    if component is None:
        raise ApiError("ERR_COMPONENT_NOT_FOUND")
    if association_id is not None and component["association_id"] != association_id:
        raise ApiError("ERR_COMPONENT_NOT_FOUND")
    return component


def case_of_association(association_id):
    return calc.case_for_association(association_id)
