"""Application lifecycle helpers: priority_date, term_expiration, recompute totals."""

from db import db
from services.dateutil import add_months, add_years


# Application status sets ----------------------------------------------------
APP_TERMINAL_STATES = {"ABANDONED", "EXPIRED", "CONVERTED"}
CONTINUATION_TYPES = {"CONTINUATION", "CIP"}


def compute_priority_date(parent_application_id, continuation_type, this_filing_date):
    """§1.3 PRIORITY_DATE."""
    if parent_application_id is None:
        return this_filing_date
    parent = db.applications.get(parent_application_id)
    if continuation_type == "CONTINUATION":
        return parent["filing_date"]
    if continuation_type == "CIP":
        return this_filing_date
    # Conversion (parent set, continuation_type null) — inherits parent's filing_date
    return parent["filing_date"]


def compute_term_expiration(application: dict):
    """§1.3 TERM_EXPIRATION — call at ISSUED transition (or on demand for PROVISIONAL)."""
    app_type = application["application_type"]
    if app_type in ("UTILITY", "PCT_NATIONAL"):
        return add_years(application["priority_date"], 20)
    if app_type == "DESIGN":
        if application.get("issue_date") is None:
            return None
        return add_years(application["issue_date"], 15)
    if app_type == "PROVISIONAL":
        return add_months(application["filing_date"], 12)
    return None


def recompute_total_fees(application_id: str):
    """Sum POSTED FeePayment.amount_cents for the application."""
    total = 0
    for fp in db.fee_payments.values():
        if fp["application_id"] == application_id and fp["payment_status"] == "POSTED":
            total += int(fp["amount_cents"])
    return total


def bump_application(application: dict):
    application["updated_at"] = db.current_utc_dt()
    application["version"] = int(application["version"]) + 1


def bump_office_action(oa: dict):
    oa["updated_at"] = db.current_utc_dt()
    oa["version"] = int(oa["version"]) + 1


def bump_maintenance_fee(mf: dict):
    mf["updated_at"] = db.current_utc_dt()
    mf["version"] = int(mf["version"]) + 1
