"""Entity resolution helpers.

``find_*`` returns ``None`` when absent (used for the scope pre-check, which
must not manufacture a 404 before shape validation runs). ``get_*`` raises the
entity's own NOT_FOUND error. Path ids resolve outermost first (step 8); a child
that exists but hangs off a different parent is reported with the child's own
NOT_FOUND error, never as a scope violation (step 10).
"""

from db import db
from errors import fail

_NOT_FOUND = {
    "facility": "ERR_FACILITY_NOT_FOUND",
    "unit": "ERR_UNIT_NOT_FOUND",
    "monitoring_system": "ERR_MONITORING_SYSTEM_NOT_FOUND",
    "daily_calibration": "ERR_DAILY_CALIBRATION_NOT_FOUND",
    "rata_test": "ERR_RATA_TEST_NOT_FOUND",
    "operating_hour": "ERR_OPERATING_HOUR_NOT_FOUND",
    "fuel_sample": "ERR_FUEL_SAMPLE_NOT_FOUND",
    "quarterly_report": "ERR_QUARTERLY_REPORT_NOT_FOUND",
    "certification": "ERR_CERTIFICATION_NOT_FOUND",
    "permit_limit": "ERR_PERMIT_LIMIT_NOT_FOUND",
    "excess_event": "ERR_EXCESS_EVENT_NOT_FOUND",
    "allowance_account": "ERR_ALLOWANCE_ACCOUNT_NOT_FOUND",
    "allowance_transaction": "ERR_ALLOWANCE_TRANSACTION_NOT_FOUND",
    "control_outage": "ERR_CONTROL_OUTAGE_NOT_FOUND",
}

_COLLECTION = {
    "facility": "facilities",
    "unit": "units",
    "monitoring_system": "monitoring_systems",
    "daily_calibration": "daily_calibrations",
    "rata_test": "rata_tests",
    "operating_hour": "operating_hours",
    "fuel_sample": "fuel_samples",
    "quarterly_report": "quarterly_reports",
    "certification": "certifications",
    "permit_limit": "permit_limits",
    "excess_event": "excess_events",
    "allowance_account": "allowance_accounts",
    "allowance_transaction": "allowance_transactions",
    "control_outage": "control_outages",
}


def find(kind, entity_id):
    if not isinstance(entity_id, str):
        return None
    return getattr(db, _COLLECTION[kind]).get(entity_id)


def get(kind, entity_id):
    record = find(kind, entity_id)
    if record is None:
        fail(_NOT_FOUND[kind], "%s not found." % kind.replace("_", " ").title())
    return record


def not_found_error(kind):
    return _NOT_FOUND[kind]


def require_child_of(kind, record, parent_field, parent_id):
    """Step 10 -- ownership mismatch reports the child's NOT_FOUND error."""
    if record.get(parent_field) != parent_id:
        fail(_NOT_FOUND[kind], "%s does not belong to the given parent." % kind)
    return record


# --- convenience navigation -------------------------------------------------

def facility_of_unit(unit):
    if unit is None:
        return None
    return db.facilities.get(unit.get("facility_id"))


def facility_of_monitoring_system(system):
    if system is None:
        return None
    return facility_of_unit(db.units.get(system.get("unit_id")))


def units_of_facility(facility_id):
    return [u for u in db.units.values() if u["facility_id"] == facility_id]


def systems_of_unit(unit_id):
    return [s for s in db.monitoring_systems.values() if s["unit_id"] == unit_id]


def hours_of_unit(unit_id):
    return [h for h in db.operating_hours.values() if h["unit_id"] == unit_id]


def reports_of_unit(unit_id):
    return [r for r in db.quarterly_reports.values() if r["unit_id"] == unit_id]


def limits_of_unit(unit_id):
    return [p for p in db.permit_limits.values() if p["unit_id"] == unit_id]


def accounts_of_facility(facility_id):
    return [a for a in db.allowance_accounts.values() if a["facility_id"] == facility_id]


def outages_of_unit(unit_id):
    return [o for o in db.control_outages.values() if o["unit_id"] == unit_id]


def certifications_of_report(report_id):
    return [c for c in db.certifications.values() if c["quarterly_report_id"] == report_id]


def rata_tests_of_system(system_id):
    return [r for r in db.rata_tests.values() if r["monitoring_system_id"] == system_id]


def calibrations_of_system(system_id):
    return [c for c in db.daily_calibrations.values() if c["monitoring_system_id"] == system_id]


def events_of_limit(limit_id):
    return [e for e in db.excess_events.values() if e["permit_limit_id"] == limit_id]
