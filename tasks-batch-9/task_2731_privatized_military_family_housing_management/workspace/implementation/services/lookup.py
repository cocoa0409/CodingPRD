"""Existence resolution (ladder rungs 5-15) and optimistic concurrency (16-18)."""

from db import db
from errors import ApiError

_FAMILIES = (
    ("installations", "ERR_INSTALLATION_NOT_FOUND"),
    ("housing_units", "ERR_HOUSING_UNIT_NOT_FOUND"),
    ("service_members", "ERR_SERVICE_MEMBER_NOT_FOUND"),
    ("applications", "ERR_APPLICATION_NOT_FOUND"),
    ("leases", "ERR_LEASE_NOT_FOUND"),
    ("inspections", "ERR_INSPECTION_NOT_FOUND"),
    ("work_orders", "ERR_WORK_ORDER_NOT_FOUND"),
    ("hazard_cases", "ERR_HAZARD_CASE_NOT_FOUND"),
    ("lodgings", "ERR_LODGING_NOT_FOUND"),
    ("disputes", "ERR_DISPUTE_NOT_FOUND"),
    ("accounts", "ERR_ACCOUNT_NOT_FOUND"),
)


def _get(collection, error_id, ref):
    if ref is None:
        return None
    row = getattr(db, collection).get(ref) if isinstance(ref, str) else None
    if row is None:
        raise ApiError(error_id)
    return row


def installation(ref):
    return _get("installations", "ERR_INSTALLATION_NOT_FOUND", ref)


def housing_unit(ref):
    return _get("housing_units", "ERR_HOUSING_UNIT_NOT_FOUND", ref)


def service_member(ref):
    return _get("service_members", "ERR_SERVICE_MEMBER_NOT_FOUND", ref)


def application(ref):
    return _get("applications", "ERR_APPLICATION_NOT_FOUND", ref)


def lease(ref):
    return _get("leases", "ERR_LEASE_NOT_FOUND", ref)


def inspection(ref):
    return _get("inspections", "ERR_INSPECTION_NOT_FOUND", ref)


def work_order(ref):
    return _get("work_orders", "ERR_WORK_ORDER_NOT_FOUND", ref)


def hazard_case(ref):
    return _get("hazard_cases", "ERR_HAZARD_CASE_NOT_FOUND", ref)


def lodging(ref):
    return _get("lodgings", "ERR_LODGING_NOT_FOUND", ref)


def dispute(ref):
    return _get("disputes", "ERR_DISPUTE_NOT_FOUND", ref)


def account(ref):
    return _get("accounts", "ERR_ACCOUNT_NOT_FOUND", ref)


def maybe(collection, ref):
    if not isinstance(ref, str):
        return None
    return getattr(db, collection).get(ref)


# ------------------------------------------------------- optimistic concurrency

def check_lease_version(lease_row, expected):
    if expected is not None and int(lease_row.get("version", 1)) != int(expected):
        raise ApiError("ERR_STALE_LEASE_VERSION")


def check_application_version(app_row, expected):
    if expected is not None and int(app_row.get("version", 1)) != int(expected):
        raise ApiError("ERR_STALE_APPLICATION_VERSION")


def check_account_version(account_row, expected):
    if expected is not None and int(account_row.get("version", 1)) != int(expected):
        raise ApiError("ERR_STALE_ACCOUNT_VERSION")


# ------------------------------------------------------------------ navigation

def unit_installation(unit_row):
    return db.installations.get(unit_row["installation_id"])


def lease_unit(lease_row):
    return db.housing_units.get(lease_row["housing_unit_id"])


def lease_installation(lease_row):
    unit = lease_unit(lease_row)
    return db.installations.get(unit["installation_id"]) if unit else None


def dependents_of(service_member_id):
    rows = [d for d in db.dependents.values() if d["service_member_id"] == service_member_id]
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq", 0)))


def units_of(installation_id):
    rows = [u for u in db.housing_units.values() if u["installation_id"] == installation_id]
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq", 0)))


def leases_of_unit(unit_id):
    rows = [l for l in db.leases.values() if l["housing_unit_id"] == unit_id]
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq", 0)))


def leases_of_installation(installation_id):
    unit_ids = set(u["id"] for u in db.housing_units.values()
                   if u["installation_id"] == installation_id)
    rows = [l for l in db.leases.values() if l["housing_unit_id"] in unit_ids]
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq", 0)))


def transactions_of(lease_id):
    rows = [t for t in db.transactions.values() if t["lease_id"] == lease_id]
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq", 0)))


def inspections_of(lease_id):
    rows = [i for i in db.inspections.values() if i["lease_id"] == lease_id]
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq", 0)))


def lodgings_of_case(case_id):
    rows = [l for l in db.lodgings.values() if l["hazard_case_id"] == case_id]
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq", 0)))


def lodgings_of_lease(lease_id):
    rows = [l for l in db.lodgings.values() if l["lease_id"] == lease_id]
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq", 0)))


def disputes_of_lease(lease_id):
    rows = [d for d in db.disputes.values() if d["lease_id"] == lease_id]
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq", 0)))


def hazard_cases_of_unit(unit_id):
    rows = [h for h in db.hazard_cases.values() if h["housing_unit_id"] == unit_id]
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq", 0)))


def bah_rates_of(installation_id):
    rows = [b for b in db.bah_rates.values() if b["installation_id"] == installation_id]
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq", 0)))


def accounts_for(installation_id, fiscal_year):
    rows = [a for a in db.accounts.values()
            if a["installation_id"] == installation_id and int(a["fiscal_year"]) == int(fiscal_year)]
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq", 0)))


def work_orders_of_installation(installation_id):
    unit_ids = set(u["id"] for u in db.housing_units.values()
                   if u["installation_id"] == installation_id)
    rows = [w for w in db.work_orders.values() if w["housing_unit_id"] in unit_ids]
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq", 0)))
