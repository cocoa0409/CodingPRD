"""Existence resolution (entity-specific 404s) and ownership scoping."""

import store
from util import ApiError
from auth import deny


def _get(coll, _id, err):
    obj = coll.get(_id)
    if obj is None:
        raise ApiError(err, 404, f"{err}")
    return obj


def get_connection(_id):
    return _get(store.connections, _id, "ERR_CONNECTION_NOT_FOUND")


def get_device(_id):
    return _get(store.devices, _id, "ERR_DEVICE_NOT_FOUND")


def get_tester(_id):
    return _get(store.testers, _id, "ERR_TESTER_NOT_FOUND")


def get_appointment(_id):
    return _get(store.appointments, _id, "ERR_APPOINTMENT_NOT_FOUND")


def get_report(_id):
    return _get(store.reports, _id, "ERR_REPORT_NOT_FOUND")


def get_survey(_id):
    return _get(store.surveys, _id, "ERR_SURVEY_NOT_FOUND")


def get_notice(_id):
    return _get(store.notices, _id, "ERR_NOTICE_NOT_FOUND")


def get_repair_order(_id):
    return _get(store.repair_orders, _id, "ERR_REPAIR_ORDER_NOT_FOUND")


def get_reminder(_id):
    # No reminder-specific not-found appears in the catalog; use a 404.
    obj = store.reminders.get(_id)
    if obj is None:
        raise ApiError("ERR_REMINDER_NOT_FOUND", 404, "reminder not found")
    return obj


def connection_of_device(device):
    return store.connections.get(device["service_connection_id"])


# ---------------------------------------------------------------------------
# Ownership scoping for PremisesOwner
# ---------------------------------------------------------------------------
def owns_connection(conn, user_id):
    return conn is not None and conn["owner_user_id"] == user_id


def ensure_owner_conn(conn, role, user_id):
    if role == "PremisesOwner" and not owns_connection(conn, user_id):
        deny()


def ensure_owner_device(device, role, user_id):
    if role == "PremisesOwner":
        conn = connection_of_device(device)
        if not owns_connection(conn, user_id):
            deny()
