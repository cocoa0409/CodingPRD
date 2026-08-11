"""Rung 3 (path existence), rung 4 (body foreign keys), rung 7 (agency billing
freeze), rung 8 (ORI authority) and rung 9 (parent version) helpers."""

from flask import g

import derive
from authz import is_frozen_operation
from errors import ApiError
from store import db

# rung 3 -- a missing FingerprintCard raises ERR_CARD_NOT_FOUND, a missing
# Submission raises ERR_SUBMISSION_NOT_FOUND, every other missing path resource
# raises ERR_REFERENCE_NOT_FOUND.
_PATH_ERRORS = {"cards": "ERR_CARD_NOT_FOUND", "submissions": "ERR_SUBMISSION_NOT_FOUND"}


def path_row(collection, row_id):
    row = getattr(db, collection).get(row_id)
    if row is None:
        raise ApiError(
            _PATH_ERRORS.get(collection, "ERR_REFERENCE_NOT_FOUND"),
            "%s %s does not exist" % (collection, row_id),
        )
    return row


def body_row(collection, row_id):
    """Rung 4 -- every foreign key supplied in the request body resolves."""
    if not isinstance(row_id, str):
        raise ApiError("ERR_REFERENCE_NOT_FOUND", "referenced row does not exist")
    row = getattr(db, collection).get(row_id)
    if row is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", "referenced row %s does not exist" % row_id)
    return row


def optional_body_row(collection, data, field):
    if field not in data or data[field] is None:
        return None
    return body_row(collection, data[field])


# -- resolution chains -------------------------------------------------------

def service_type_of_appointment(appointment):
    return db.service_types[appointment["service_type_id"]]


def ori_of_service_type(service_type):
    return db.oris[service_type["ori_id"]]


def agency_of_ori(ori):
    return db.agencies[ori["agency_id"]]


def ori_of_appointment(appointment):
    return ori_of_service_type(service_type_of_appointment(appointment))


def agency_of_appointment(appointment):
    return agency_of_ori(ori_of_appointment(appointment))


def ori_of_card(card):
    return ori_of_appointment(db.appointments[card["appointment_id"]])


def ori_of_submission(submission):
    return db.oris[submission["ori_id"]]


def host_agency_of_site(site):
    if site.get("host_agency_id"):
        return db.agencies.get(site["host_agency_id"])
    return None


# -- rung 7 ------------------------------------------------------------------

def check_billing_freeze(*agencies):
    """The gate closes over every ORI the agency owns and every mobile event it
    hosts; the thirteen frozen operations are enumerated in authz."""
    if not is_frozen_operation():
        return
    for agency in agencies:
        if agency is not None and agency["billing_status"] == "SUSPENDED":
            raise ApiError(
                "ERR_AGENCY_BILLING_SUSPENDED",
                "agency %s is billing suspended" % agency["id"],
            )


def freeze_for_site(site):
    if site is not None and site["site_kind"] == "MOBILE_EVENT":
        return host_agency_of_site(site)
    return None


# -- rung 8 ------------------------------------------------------------------

def check_ori_authority(ori):
    if ori["authority_status"] != "ACTIVE":
        raise ApiError("ERR_ORI_AUTHORITY_SUSPENDED", "ORI %s is suspended" % ori["ori_code"])


# -- rung 9 ------------------------------------------------------------------

def check_parent_version(parent, expected):
    if parent["version"] != expected:
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected version %s but the row is at %s" % (expected, parent["version"]),
        )


# -- rung 10 -----------------------------------------------------------------

def state_error(code, message):
    raise ApiError(code, message)


def require_appointment_state(appointment, allowed):
    if appointment["status"] not in allowed:
        raise ApiError(
            "ERR_APPOINTMENT_STATE_INVALID",
            "appointment is %s" % appointment["status"],
        )


def require_card_state(card, allowed):
    if card["status"] not in allowed:
        raise ApiError("ERR_CARD_STATE_INVALID", "card is %s" % card["status"])


def require_record_state(condition, message):
    if not condition:
        raise ApiError("ERR_RECORD_STATE_INVALID", message)


# -- rung 11 -----------------------------------------------------------------

def check_segregation(recorded_actor):
    if recorded_actor is not None and recorded_actor == g.user_id:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "the acting principal recorded the first action",
        )


# -- misc --------------------------------------------------------------------

def position_of_card(card, position_code):
    for position in db.positions.values():
        if position["card_id"] == card["id"] and position["position_code"] == position_code:
            return position
    raise ApiError("ERR_REFERENCE_NOT_FOUND", "position %s does not exist" % position_code)


def unique_or_400(collection, field, value, scope_field=None, scope_value=None, predicate=None):
    for row in getattr(db, collection).values():
        if row.get(field) != value:
            continue
        if scope_field is not None and row.get(scope_field) != scope_value:
            continue
        if predicate is not None and not predicate(row):
            continue
        raise ApiError("ERR_INVALID_REQUEST", "%s must be unique" % field)


def derived_device_status(device):
    return derive.device_status(device)
