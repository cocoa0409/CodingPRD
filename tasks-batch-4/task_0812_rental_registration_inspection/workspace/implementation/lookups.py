"""Entity lookup helpers that raise the correct not-found error."""
from store import store
from errors import err


def get_landlord(i):
    e = store.landlords.get(i)
    if e is None:
        raise err("ERR_LANDLORD_NOT_FOUND", "Landlord not found")
    return e


def get_inspector(i):
    e = store.inspectors.get(i)
    if e is None:
        raise err("ERR_INSPECTOR_NOT_FOUND", "Inspector not found")
    return e


def get_property(i):
    e = store.properties.get(i)
    if e is None:
        raise err("ERR_PROPERTY_NOT_FOUND", "Property not found")
    return e


def get_license(i):
    e = store.licenses.get(i)
    if e is None:
        raise err("ERR_LICENSE_NOT_FOUND", "License not found")
    return e


def get_complaint(i):
    e = store.complaints.get(i)
    if e is None:
        raise err("ERR_COMPLAINT_NOT_FOUND", "Complaint not found")
    return e


def get_inspection(i):
    e = store.inspections.get(i)
    if e is None:
        raise err("ERR_INSPECTION_NOT_FOUND", "Inspection not found")
    return e


def get_violation(i):
    e = store.violations.get(i)
    if e is None:
        raise err("ERR_VIOLATION_NOT_FOUND", "Violation not found")
    return e


def get_notice(i):
    e = store.notices.get(i)
    if e is None:
        raise err("ERR_NOTICE_NOT_FOUND", "Tenant notice not found")
    return e


def get_condemnation(i):
    e = store.condemnation_orders.get(i)
    if e is None:
        raise err("ERR_CONDEMNATION_NOT_FOUND", "Condemnation order not found")
    return e


def sorted_by_creation(items):
    return sorted(items, key=lambda x: x["_seq"])
