"""Existence rungs 4-20 and the ownership chains rung 3 compares against."""

from core.auth import require_client_owner, require_farrier_owner
from core.errors import ApiError
from core.store import db

NOT_FOUND = {
    "barns": "ERR_BARN_NOT_FOUND",
    "clients": "ERR_CLIENT_NOT_FOUND",
    "horses": "ERR_HORSE_NOT_FOUND",
    "farriers": "ERR_FARRIER_NOT_FOUND",
    "shoe_skus": "ERR_SKU_NOT_FOUND",
    "inventory_buckets": "ERR_BUCKET_NOT_FOUND",
    "stock_transfers": "ERR_TRANSFER_NOT_FOUND",
    "shoe_reservations": "ERR_RESERVATION_NOT_FOUND",
    "rate_cards": "ERR_RATE_CARD_NOT_FOUND",
    "routes": "ERR_ROUTE_NOT_FOUND",
    "route_stops": "ERR_ROUTE_STOP_NOT_FOUND",
    "appointments": "ERR_APPOINTMENT_NOT_FOUND",
    "service_lines": "ERR_SERVICE_LINE_NOT_FOUND",
    "lameness_cases": "ERR_LAMENESS_CASE_NOT_FOUND",
    "vet_prescriptions": "ERR_PRESCRIPTION_NOT_FOUND",
    "invoices": "ERR_INVOICE_NOT_FOUND",
    "reminders": "ERR_REMINDER_NOT_FOUND",
}


def must(table, row_id):
    row = db.get(table, row_id)
    if row is None:
        raise ApiError(NOT_FOUND[table])
    return row


def must_ref(table, value):
    """Existence rung for a body foreign key.

    An absent or non-string value is not an existence failure: it is a payload
    shape problem, and rung 21 reports it further down the ladder.
    """
    if not isinstance(value, str) or not value:
        return None
    return must(table, value)


# --------------------------------------------------------------------------
# Ownership chains (PRD 2.1).
# --------------------------------------------------------------------------
def route_of_stop(stop):
    return db.get("routes", stop["route_id"]) if stop else None


def stop_of_appointment(appointment):
    if not appointment or not appointment.get("route_stop_id"):
        return None
    return db.get("route_stops", appointment["route_stop_id"])


def route_of_appointment(appointment):
    stop = stop_of_appointment(appointment)
    return route_of_stop(stop) if stop else None


def farrier_of_appointment(appointment):
    route = route_of_appointment(appointment)
    return db.get("farriers", route["farrier_id"]) if route else None


def horse_of_appointment(appointment):
    return db.get("horses", appointment["horse_id"]) if appointment else None


def client_of_horse(horse):
    return db.get("clients", horse["client_id"]) if horse else None


def client_of_appointment(appointment):
    return client_of_horse(horse_of_appointment(appointment))


def owning_client_id_of_appointment(appointment):
    horse = horse_of_appointment(appointment)
    return horse["client_id"] if horse else None


# --- rung 3 entry points ---------------------------------------------------
def guard_client_resource(client_id):
    require_client_owner(client_id)


def guard_horse(horse):
    require_client_owner(horse["client_id"])


def guard_appointment(appointment):
    """A ClientUser owns the visit through the horse; a Farrier through the route."""
    require_client_owner(owning_client_id_of_appointment(appointment))
    route = route_of_appointment(appointment)
    require_farrier_owner(route["farrier_id"] if route else None)


def guard_route(route):
    require_farrier_owner(route["farrier_id"])


def guard_stop(stop):
    route = route_of_stop(stop)
    require_farrier_owner(route["farrier_id"] if route else None)


def guard_invoice(invoice):
    require_client_owner(invoice["client_id"])


def guard_reminder(reminder):
    appointment = db.get("appointments", reminder["appointment_id"])
    require_client_owner(owning_client_id_of_appointment(appointment))


def guard_lameness_case(case):
    horse = db.get("horses", case["horse_id"])
    require_client_owner(horse["client_id"] if horse else None)


def guard_prescription(prescription):
    horse = db.get("horses", prescription["horse_id"])
    require_client_owner(horse["client_id"] if horse else None)
