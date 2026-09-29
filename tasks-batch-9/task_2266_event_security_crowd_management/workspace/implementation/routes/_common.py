"""Shared route plumbing: entity fetch-or-404 and list pagination."""

from db import db, sorted_records
from errors import ApiError
from response import list_response
from valid import pagination

ALL_ROLES = (
    "SecurityDirector",
    "RiskAnalyst",
    "StaffingCoordinator",
    "CredentialAuditor",
    "PostSupervisor",
    "IncidentCommander",
    "SubcontractorLiaison",
    "SystemOperator",
)


def _fetch(collection, record_id, error_id):
    record = collection.get(record_id)
    if record is None:
        raise ApiError(error_id)
    return record


def get_venue(venue_id):
    return _fetch(db.venues, venue_id, "ERR_VENUE_NOT_FOUND")


def get_zone(zone_id):
    return _fetch(db.zones, zone_id, "ERR_ZONE_NOT_FOUND")


def get_event(event_id):
    return _fetch(db.events, event_id, "ERR_EVENT_NOT_FOUND")


def get_assessment(assessment_id):
    return _fetch(db.assessments, assessment_id, "ERR_RISK_ASSESSMENT_NOT_FOUND")


def get_plan(plan_id):
    return _fetch(db.plans, plan_id, "ERR_PLAN_NOT_FOUND")


def get_post(post_id):
    return _fetch(db.posts, post_id, "ERR_POST_NOT_FOUND")


def get_subcontractor(subcontractor_id):
    return _fetch(db.subcontractors, subcontractor_id, "ERR_SUBCONTRACTOR_NOT_FOUND")


def get_guard(guard_id):
    return _fetch(db.guards, guard_id, "ERR_GUARD_NOT_FOUND")


def get_assignment(assignment_id):
    return _fetch(db.assignments, assignment_id, "ERR_ASSIGNMENT_NOT_FOUND")


def get_lane(lane_id):
    return _fetch(db.lanes, lane_id, "ERR_LANE_NOT_FOUND")


def get_reading(reading_id):
    return _fetch(db.readings, reading_id, "ERR_READING_NOT_FOUND")


def get_incident(incident_id):
    return _fetch(db.incidents, incident_id, "ERR_INCIDENT_NOT_FOUND")


def get_review(review_id):
    return _fetch(db.reviews, review_id, "ERR_REVIEW_NOT_FOUND")


def paginated(records, serializer):
    """Sort ascending by created_at, apply limit/offset and build the envelope."""
    limit, offset = pagination()
    ordered = sorted_records(records)
    total = len(ordered)
    window = ordered[offset : offset + limit]
    return list_response([serializer(item) for item in window], limit, offset, total)


def match_filters(record, filters):
    for field, expected in filters.items():
        if expected is None:
            continue
        if record.get(field) != expected:
            return False
    return True
