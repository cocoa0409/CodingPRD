"""Authentication, RBAC and resource lookup (PRD 2.1, 2.9; ladder gates 1, 2, 4, 5)."""

from flask import request

from errors import ApiError
from store import db

ROLES = (
    "UnitedFundAdmin",
    "CampaignCoordinator",
    "FinanceReviewer",
    "AgencyRepresentative",
    "VolunteerPanelist",
    "AllocationsDirector",
)

ALL_ROLES = list(ROLES)

# Roles whose identity is backed by a persisted entity; X-User-ID is mandatory
# for these and is compared against resource foreign keys.
ENTITY_BACKED = ("CampaignCoordinator", "AgencyRepresentative", "VolunteerPanelist")


def authenticate(allowed_roles):
    """Gate 1 (ERR_UNAUTHENTICATED) then gate 2 (ERR_ROLE_NOT_PERMITTED)."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role == "" or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "A valid X-User-Role header is required.")
    if role in ENTITY_BACKED and (user_id is None or user_id == ""):
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            "X-User-ID is required for the %s role." % role,
        )
    if role not in allowed_roles:
        raise ApiError(
            "ERR_ROLE_NOT_PERMITTED",
            "Role %s may not perform this operation." % role,
        )
    return role, user_id


# --------------------------------------------------------------------------- #
# existence resolution - left to right, first miss wins (PRD 2.9)
# --------------------------------------------------------------------------- #


def _resolve(table, identifier, error_id):
    row = table.get(identifier) if identifier is not None else None
    if row is None:
        raise ApiError(error_id)
    return row


def get_employer(employer_id):
    return _resolve(db.employers, employer_id, "ERR_EMPLOYER_NOT_FOUND")


def get_campaign(campaign_id):
    return _resolve(db.campaigns, campaign_id, "ERR_CAMPAIGN_NOT_FOUND")


def get_pledge(pledge_id):
    return _resolve(db.pledges, pledge_id, "ERR_PLEDGE_NOT_FOUND")


def get_agency(agency_id):
    return _resolve(db.agencies, agency_id, "ERR_AGENCY_NOT_FOUND")


def get_review(review_id):
    return _resolve(db.reviews, review_id, "ERR_AGENCY_REVIEW_NOT_FOUND")


def get_cycle(cycle_id):
    return _resolve(db.cycles, cycle_id, "ERR_CYCLE_NOT_FOUND")


def get_request(request_id):
    return _resolve(db.requests, request_id, "ERR_REQUEST_NOT_FOUND")


def get_panelist(panelist_id):
    return _resolve(db.panelists, panelist_id, "ERR_PANELIST_NOT_FOUND")


def get_report(report_id):
    return _resolve(db.reports, report_id, "ERR_OUTCOME_REPORT_NOT_FOUND")


# --------------------------------------------------------------------------- #
# ownership (gate 6, ERR_OWNERSHIP_VIOLATION)
# --------------------------------------------------------------------------- #


def ownership_violation():
    raise ApiError("ERR_OWNERSHIP_VIOLATION")


def coordinator_of_employer(user_id, employer_id):
    """The acting coordinator must be seated at the given employer."""
    coordinator = db.coordinators.get(user_id)
    if coordinator is None or coordinator.get("employer_id") != employer_id:
        ownership_violation()
    return coordinator


def require_agency_self(user_id, agency_id):
    if user_id != agency_id:
        ownership_violation()
