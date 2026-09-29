"""Existence resolution helpers, applied in the order fixed by PRD 2.8 step 5."""

from db import db
from errors import ApiError


def _lookup(collection, identifier, error_id):
    if not isinstance(identifier, str):
        raise ApiError(error_id)
    row = collection.get(identifier)
    if row is None:
        raise ApiError(error_id)
    return row


def find_lessee(identifier):
    return _lookup(db.lessees, identifier, "ERR_LESSEE_NOT_FOUND")


def find_aircraft(identifier):
    return _lookup(db.aircraft, identifier, "ERR_AIRCRAFT_NOT_FOUND")


def find_lease(identifier):
    return _lookup(db.leases, identifier, "ERR_LEASE_NOT_FOUND")


def find_crew(identifier):
    return _lookup(db.crew_members, identifier, "ERR_CREW_MEMBER_NOT_FOUND")


def find_qualification(identifier):
    return _lookup(db.crew_qualifications, identifier, "ERR_QUALIFICATION_NOT_FOUND")


def find_approval(identifier):
    return _lookup(db.regulatory_approvals, identifier, "ERR_APPROVAL_NOT_FOUND")


def find_certificate(identifier):
    return _lookup(db.insurance_certificates, identifier, "ERR_CERTIFICATE_NOT_FOUND")


def find_leg(identifier):
    return _lookup(db.flight_legs, identifier, "ERR_FLIGHT_LEG_NOT_FOUND")


def find_substitution(identifier):
    return _lookup(db.substitutions, identifier, "ERR_SUBSTITUTION_NOT_FOUND")


def find_period(identifier):
    return _lookup(db.utilization_periods, identifier, "ERR_PERIOD_NOT_FOUND")


def find_invoice(identifier):
    return _lookup(db.settlement_invoices, identifier, "ERR_INVOICE_NOT_FOUND")


def find_report(identifier):
    return _lookup(db.reliability_reports, identifier, "ERR_REPORT_NOT_FOUND")


def find_return(identifier):
    return _lookup(db.return_conditions, identifier, "ERR_RETURN_CONDITION_NOT_FOUND")


def filtered(rows, args, spec):
    """Apply conjunctive foreign-key / status filters from the query string."""
    result = rows
    for param, field in spec.items():
        if param in args:
            wanted = args.get(param)
            result = [r for r in result if _matches(r.get(field), wanted)]
    return result


def _matches(value, wanted):
    if value is None:
        return wanted == "null" or wanted == ""
    return str(value) == wanted
