"""Existence resolution (ladder rungs 5 and 6), ownership (rung 7) and
optimistic concurrency (rung 8)."""

import db
from errors import ApiError
from middleware import DEVELOPER, RESIDENT

_STORES = {
    "ordinance": (lambda: db.ordinances, "ERR_ORDINANCE_NOT_FOUND"),
    "ami_schedule": (lambda: db.ami_schedules, "ERR_AMI_SCHEDULE_NOT_FOUND"),
    "project": (lambda: db.projects, "ERR_PROJECT_NOT_FOUND"),
    "unit": (lambda: db.units, "ERR_UNIT_NOT_FOUND"),
    "marketing_plan": (lambda: db.marketing_plans, "ERR_MARKETING_PLAN_NOT_FOUND"),
    "lottery_event": (lambda: db.lottery_events, "ERR_LOTTERY_EVENT_NOT_FOUND"),
    "household": (lambda: db.households, "ERR_HOUSEHOLD_NOT_FOUND"),
    "certification": (lambda: db.certifications, "ERR_CERTIFICATION_NOT_FOUND"),
    "agreement": (lambda: db.agreements, "ERR_AGREEMENT_NOT_FOUND"),
    "monitoring_review": (lambda: db.monitoring_reviews, "ERR_MONITORING_REVIEW_NOT_FOUND"),
    "resale_transaction": (lambda: db.resale_transactions, "ERR_RESALE_TRANSACTION_NOT_FOUND"),
    "fee": (lambda: db.in_lieu_fees, "ERR_FEE_NOT_FOUND"),
    "disbursement": (lambda: db.disbursements, "ERR_DISBURSEMENT_NOT_FOUND"),
}


def fetch(kind, identifier):
    store_fn, error_id = _STORES[kind]
    row = store_fn().get(identifier) if isinstance(identifier, str) else None
    if row is None:
        raise ApiError(error_id)
    return row


def maybe(kind, identifier):
    store_fn, _ = _STORES[kind]
    if not isinstance(identifier, str):
        return None
    return store_fn().get(identifier)


# --- rung 7: ownership ----------------------------------------------------
def require_project_owner(project, user_id, role):
    """A Developer may only act on projects whose developer_user_id matches."""
    if role != DEVELOPER:
        return
    if project.get("developer_user_id") != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def require_unit_owner_developer(unit, user_id, role):
    if role != DEVELOPER:
        return
    project = maybe("project", unit.get("project_id"))
    if project is None or project.get("developer_user_id") != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def require_household_self(household, user_id, role):
    """A Resident's X-User-ID is the Household id it speaks for."""
    if role != RESIDENT:
        return
    if household.get("id") != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def require_unit_occupant(unit, user_id, role):
    """A Resident may only file a resale on the unit it currently occupies."""
    if role != RESIDENT:
        return
    if unit.get("occupant_household_id") != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


# --- rung 8: optimistic concurrency --------------------------------------
def check_project_version(project, expected):
    if expected is None:
        return
    if int(project.get("version") or 0) != int(expected):
        raise ApiError("ERR_STALE_PROJECT_VERSION")


def check_unit_version(unit, expected):
    if expected is None:
        return
    if int(unit.get("version") or 0) != int(expected):
        raise ApiError("ERR_STALE_UNIT_VERSION")


# --- convenience child collections ---------------------------------------
def project_units(project_id):
    return [row for row in db.all_rows(db.units) if row.get("project_id") == project_id]


def project_fees(project_id):
    return [row for row in db.all_rows(db.in_lieu_fees) if row.get("project_id") == project_id]


def project_agreements(project_id):
    return [row for row in db.all_rows(db.agreements) if row.get("project_id") == project_id]


def project_plans(project_id):
    return [row for row in db.all_rows(db.marketing_plans) if row.get("project_id") == project_id]


def unit_certifications(unit_id):
    return [row for row in db.all_rows(db.certifications) if row.get("unit_id") == unit_id]


def unit_reviews(unit_id):
    return [row for row in db.all_rows(db.monitoring_reviews) if row.get("unit_id") == unit_id]


def unit_resales(unit_id):
    return [row for row in db.all_rows(db.resale_transactions) if row.get("unit_id") == unit_id]


def event_households(event_id):
    return [row for row in db.all_rows(db.households) if row.get("lottery_event_id") == event_id]


def fee_disbursements(fee_id):
    return [row for row in db.all_rows(db.disbursements) if row.get("source_fee_id") == fee_id]
