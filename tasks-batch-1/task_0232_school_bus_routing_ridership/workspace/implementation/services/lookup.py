"""Path-resource existence lookups (PRD §2.7: 404 before body work)."""

from db import DB
from errors import err, ERR_NOT_FOUND


def get_district(district_id):
    rec = DB.districts.get(district_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "District not found")
    return rec


def get_route(route_id):
    rec = DB.routes.get(route_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Route not found")
    return rec


def get_stop(stop_id):
    rec = DB.stops.get(stop_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Stop not found")
    return rec


def get_student(student_id):
    rec = DB.students.get(student_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Student not found")
    return rec


def get_application(application_id):
    rec = DB.ridership_applications.get(application_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "RidershipApplication not found")
    return rec


def get_driver(driver_id):
    rec = DB.drivers.get(driver_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Driver not found")
    return rec


def get_assignment(assignment_id):
    rec = DB.driver_assignments.get(assignment_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "DriverAssignment not found")
    return rec


def get_bus_trip(bus_trip_id):
    rec = DB.bus_trips.get(bus_trip_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "BusTrip not found")
    return rec


def get_tap_event(tap_event_id):
    rec = DB.tap_events.get(tap_event_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "TapEvent not found")
    return rec


def get_notification(notification_id):
    rec = DB.parent_notifications.get(notification_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "ParentNotification not found")
    return rec


def get_missed_report(report_id):
    rec = DB.missed_bus_reports.get(report_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "MissedBusReport not found")
    return rec
