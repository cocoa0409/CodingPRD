"""Path and foreign-key resolution (PRD §2.8).

Path segments resolve strictly left to right; body foreign keys resolve after
every path segment, in declaration order.
"""

import db
from errors import (
    ApiError,
    ERR_AUDIT_CASE_NOT_FOUND,
    ERR_MARKET_REPORT_NOT_FOUND,
    ERR_METHODOLOGY_CHANGE_NOT_FOUND,
    ERR_PENALTY_ASSESSMENT_NOT_FOUND,
    ERR_PLANT_NOT_FOUND,
    ERR_REGISTRATION_NOT_FOUND,
    ERR_REPORTING_ENTITY_NOT_FOUND,
    ERR_REPORTING_WINDOW_NOT_FOUND,
    ERR_SUBMISSION_NOT_FOUND,
)


def _resolve(collection, identifier, error_id, label):
    rec = collection.get(identifier) if isinstance(identifier, str) else None
    if rec is None:
        raise ApiError(error_id, "%s %s was not found." % (label, identifier))
    return rec


def reporting_entity(identifier):
    return _resolve(db.reporting_entities, identifier, ERR_REPORTING_ENTITY_NOT_FOUND, "Reporting entity")


def plant(identifier):
    return _resolve(db.plants, identifier, ERR_PLANT_NOT_FOUND, "Plant")


def registration(identifier):
    return _resolve(db.registrations, identifier, ERR_REGISTRATION_NOT_FOUND, "Registration")


def reporting_window(identifier):
    return _resolve(db.reporting_windows, identifier, ERR_REPORTING_WINDOW_NOT_FOUND, "Reporting window")


def submission(identifier):
    return _resolve(db.submissions, identifier, ERR_SUBMISSION_NOT_FOUND, "Submission")


def market_report(identifier):
    return _resolve(db.market_reports, identifier, ERR_MARKET_REPORT_NOT_FOUND, "Market report")


def audit_case(identifier):
    return _resolve(db.audit_cases, identifier, ERR_AUDIT_CASE_NOT_FOUND, "Audit case")


def penalty_assessment(identifier):
    return _resolve(db.penalty_assessments, identifier, ERR_PENALTY_ASSESSMENT_NOT_FOUND, "Penalty assessment")


def methodology_change(identifier):
    return _resolve(db.methodology_changes, identifier, ERR_METHODOLOGY_CHANGE_NOT_FOUND, "Methodology change")
