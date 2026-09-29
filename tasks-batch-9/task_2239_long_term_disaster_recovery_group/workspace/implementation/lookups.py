"""Path-parameter and body foreign-key resolution (PRD 2.11 steps 4 and 5)."""

import db
from errors import ApiError


def _get(store, record_id, error_id):
    record = store.get(record_id) if isinstance(record_id, str) else None
    if record is None:
        raise ApiError(error_id)
    return record


def survivor(record_id):
    return _get(db.survivors, record_id, "ERR_SURVIVOR_NOT_FOUND")


def case(record_id):
    return _get(db.recovery_cases, record_id, "ERR_CASE_NOT_FOUND")


def damage_item(record_id):
    return _get(db.damage_items, record_id, "ERR_DAMAGE_ITEM_NOT_FOUND")


def assessment(record_id):
    return _get(db.assessments, record_id, "ERR_ASSESSMENT_NOT_FOUND")


def member_org(record_id):
    return _get(db.member_orgs, record_id, "ERR_MEMBER_ORG_NOT_FOUND")


def session(record_id):
    return _get(db.table_sessions, record_id, "ERR_SESSION_NOT_FOUND")


def presentation(record_id):
    return _get(db.presentations, record_id, "ERR_PRESENTATION_NOT_FOUND")


def commitment(record_id):
    return _get(db.commitments, record_id, "ERR_COMMITMENT_NOT_FOUND")


def funding_source(record_id):
    return _get(db.funding_sources, record_id, "ERR_FUNDING_SOURCE_NOT_FOUND")


def disbursement(record_id):
    return _get(db.disbursements, record_id, "ERR_DISBURSEMENT_NOT_FOUND")


def project(record_id):
    return _get(db.projects, record_id, "ERR_PROJECT_NOT_FOUND")


def volunteer_group(record_id):
    return _get(db.volunteer_groups, record_id, "ERR_VOLUNTEER_GROUP_NOT_FOUND")


def deployment(record_id):
    return _get(db.deployments, record_id, "ERR_DEPLOYMENT_NOT_FOUND")


def lodging_site(record_id):
    return _get(db.lodging_sites, record_id, "ERR_LODGING_SITE_NOT_FOUND")


def housing_assignment(record_id):
    return _get(db.housing_assignments, record_id, "ERR_HOUSING_ASSIGNMENT_NOT_FOUND")
