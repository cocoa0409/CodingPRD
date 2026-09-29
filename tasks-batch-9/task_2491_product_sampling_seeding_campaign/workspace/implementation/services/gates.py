"""Reusable ladder rungs (PRD 2.5)."""

from errors import ApiError
from middleware import acting_role, acting_user_id

NOT_FOUND = {
    "campaigns": "ERR_CAMPAIGN_NOT_FOUND",
    "kit_lines": "ERR_KIT_LINE_NOT_FOUND",
    "fulfillment_centers": "ERR_FULFILLMENT_CENTER_NOT_FOUND",
    "fulfillment_waves": "ERR_FULFILLMENT_WAVE_NOT_FOUND",
    "panelists": "ERR_PANELIST_NOT_FOUND",
    "enrollments": "ERR_ENROLLMENT_NOT_FOUND",
    "sample_shipments": "ERR_SHIPMENT_NOT_FOUND",
    "review_submissions": "ERR_REVIEW_NOT_FOUND",
    "retailers": "ERR_RETAILER_NOT_FOUND",
    "syndication_records": "ERR_SYNDICATION_RECORD_NOT_FOUND",
    "diversion_cases": "ERR_DIVERSION_CASE_NOT_FOUND",
    "purchase_matches": "ERR_PURCHASE_MATCH_NOT_FOUND",
    "lift_analyses": "ERR_LIFT_ANALYSIS_NOT_FOUND",
}


def must_exist(collection_name, row_id, label=None):
    """Rungs 7 and 8 — existence, checked left to right by the caller."""
    from db import db
    collection = getattr(db, collection_name)
    row = collection.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(NOT_FOUND[collection_name],
                       "%s '%s' does not exist" % (label or collection_name, row_id))
    return row


def require_owner(panelist_id):
    """Rung 9 — Panelist ownership by exact X-User-ID equality."""
    if acting_role() != "Panelist":
        return
    if acting_user_id() != panelist_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "The acting panelist does not own this resource")


def require_not_banned(panelist):
    """Rung 13."""
    if panelist["integrity_status"] == "BANNED":
        raise ApiError("ERR_PANELIST_BANNED", "The panelist is banned from the panel")


def require_not_flagged(panelist):
    """Rung 14 — external publication requires an unflagged panelist."""
    if panelist["integrity_status"] == "FLAGGED":
        raise ApiError("ERR_PANELIST_INTEGRITY_HOLD",
                       "The panelist is under an integrity hold")


def require_segregation(actor_forbidden_id, message):
    """Rung 15 — exact X-User-ID equality forbids the second action."""
    if actor_forbidden_id is not None and acting_user_id() == actor_forbidden_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", message)


def require_posture_not_frozen(campaign):
    """Rung 16."""
    if campaign["compliance_posture"] == "FROZEN":
        raise ApiError("ERR_CAMPAIGN_POSTURE_FROZEN",
                       "The campaign's compliance posture is FROZEN")


def require_posture_open(campaign):
    """Rungs 16 then 17 — publication requires an OPEN posture."""
    require_posture_not_frozen(campaign)
    if campaign["compliance_posture"] != "OPEN":
        raise ApiError("ERR_CAMPAIGN_POSTURE_RESTRICTED",
                       "The campaign's compliance posture is not OPEN")


def require_campaign_status(campaign, allowed):
    """Rung 11."""
    if campaign["status"] not in allowed:
        raise ApiError("ERR_CAMPAIGN_NOT_ACCEPTING_ENROLLMENTS",
                       "Campaign status '%s' does not permit this operation"
                       % campaign["status"])


def check_campaign_version(campaign, expected):
    """Rung 12."""
    if expected is None:
        return
    if campaign["version"] != expected:
        raise ApiError("ERR_STALE_CAMPAIGN_VERSION",
                       "Expected campaign version %s but found %s"
                       % (expected, campaign["version"]))


def check_enrollment_version(enrollment, expected):
    """Rung 12."""
    if expected is None:
        return
    if enrollment["version"] != expected:
        raise ApiError("ERR_STALE_ENROLLMENT_VERSION",
                       "Expected enrollment version %s but found %s"
                       % (expected, enrollment["version"]))


def state_error(error_id, message):
    raise ApiError(error_id, message)
