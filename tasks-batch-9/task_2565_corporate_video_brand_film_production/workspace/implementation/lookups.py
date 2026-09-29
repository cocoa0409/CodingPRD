"""Existence resolution (precedence priorities 6-15).

Identifier families each carry their own 404 code and are resolved strictly
left to right / in family order (PRD 2.11).
"""

from errors import ApiError
from store import db


def find_project(project_id):
    row = db["projects"].get(project_id) if isinstance(project_id, str) else None
    if row is None:
        raise ApiError("ERR_PROJECT_NOT_FOUND", "No project matches id %r." % project_id)
    return row


def find_deliverable(deliverable_id):
    row = db["deliverables"].get(deliverable_id) if isinstance(deliverable_id, str) else None
    if row is None:
        raise ApiError("ERR_DELIVERABLE_NOT_FOUND", "No deliverable matches id %r." % deliverable_id)
    return row


def find_version(version_id):
    row = db["deliverable_versions"].get(version_id) if isinstance(version_id, str) else None
    if row is None:
        raise ApiError("ERR_DELIVERABLE_VERSION_NOT_FOUND",
                       "No deliverable version matches id %r." % version_id)
    return row


def find_change_order(change_order_id):
    row = db["change_orders"].get(change_order_id) if isinstance(change_order_id, str) else None
    if row is None:
        raise ApiError("ERR_CHANGE_ORDER_NOT_FOUND",
                       "No change order matches id %r." % change_order_id)
    return row


def find_shoot_day(shoot_day_id):
    row = db["shoot_days"].get(shoot_day_id) if isinstance(shoot_day_id, str) else None
    if row is None:
        raise ApiError("ERR_SHOOT_DAY_NOT_FOUND", "No shoot day matches id %r." % shoot_day_id)
    return row


def find_location(location_id):
    row = db["locations"].get(location_id) if isinstance(location_id, str) else None
    if row is None:
        raise ApiError("ERR_LOCATION_NOT_FOUND", "No location matches id %r." % location_id)
    return row


def find_crew_member(crew_member_id):
    row = db["crew_members"].get(crew_member_id) if isinstance(crew_member_id, str) else None
    if row is None:
        raise ApiError("ERR_CREW_MEMBER_NOT_FOUND",
                       "No crew member matches id %r." % crew_member_id)
    return row


def find_crew_booking(booking_id):
    row = db["crew_bookings"].get(booking_id) if isinstance(booking_id, str) else None
    if row is None:
        raise ApiError("ERR_CREW_BOOKING_NOT_FOUND",
                       "No crew booking matches id %r." % booking_id)
    return row


def find_compliance_cert(cert_id):
    row = db["compliance_certs"].get(cert_id) if isinstance(cert_id, str) else None
    if row is None:
        raise ApiError("ERR_COMPLIANCE_CERT_NOT_FOUND",
                       "No compliance certificate matches id %r." % cert_id)
    return row


def find_engagement(engagement_id):
    row = db["talent_engagements"].get(engagement_id) if isinstance(engagement_id, str) else None
    if row is None:
        raise ApiError("ERR_TALENT_ENGAGEMENT_NOT_FOUND",
                       "No talent engagement matches id %r." % engagement_id)
    return row
