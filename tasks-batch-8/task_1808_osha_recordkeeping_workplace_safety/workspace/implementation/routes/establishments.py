"""Establishment endpoints (PRD §3.1, §3.7 rates read-out)."""
from flask import Blueprint

from db import STORE
from errors import raise_error, ERR_INVALID_REQUEST
from middleware import get_auth, require_roles, ALL_ROLES, RATES_READ_ROLES
from response import success_object, success_list
from services.core import (get_body, req_str, opt_bool, req_enum, base_fields,
                           serialize, serialize_case, lookup, paginated,
                           query_str, query_int, live_rates)

bp = Blueprint("establishments", __name__)

SIZE_CLASSES = ("SMALL", "STANDARD", "LARGE")


@bp.post("/safety/establishments")
def create_establishment():
    auth = get_auth()
    require_roles(auth, ("PlatformAdmin",))
    data = get_body()
    company_id = req_str(data, "company_id")
    site_name = req_str(data, "site_name", non_empty=True)
    naics_code = req_str(data, "naics_code")
    if not (len(naics_code) == 6 and naics_code.isdigit()):
        raise_error(ERR_INVALID_REQUEST,
                    "naics_code must be exactly 6 digits")
    state_code = req_str(data, "state_code")
    if not (len(state_code) == 2 and state_code.isalpha()):
        raise_error(ERR_INVALID_REQUEST,
                    "state_code must be a 2-letter US state code")
    size_class = req_enum(data, "size_class", SIZE_CLASSES)
    is_partially_exempt = opt_bool(data, "is_partially_exempt", False)
    lookup(STORE.companies, company_id)
    est = base_fields()
    est.update({
        "company_id": company_id,
        "site_name": site_name,
        "naics_code": naics_code,
        "state_code": state_code,
        "size_class": size_class,
        "is_partially_exempt": is_partially_exempt,
        "posture": "CLEAR",
        "risk_score": 0,
        "current_year_hours": 0,
        "_seq_num": STORE.next_establishment_seq(),
    })
    STORE.establishments[est["id"]] = est
    return success_object(serialize(est), status=201)


@bp.get("/safety/establishments/<establishmentId>")
def get_establishment(establishmentId):
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    est = lookup(STORE.establishments, establishmentId)
    return success_object(serialize(est))


@bp.get("/safety/establishments/<establishmentId>/rates")
def get_establishment_rates(establishmentId):
    auth = get_auth()
    require_roles(auth, RATES_READ_ROLES)
    lookup(STORE.establishments, establishmentId)
    year = query_int("year")
    if year is None:
        raise_error(ERR_INVALID_REQUEST, "year query parameter is required")
    trir, dart, n_rec, n_dart, hours = live_rates(establishmentId, year)
    return success_object({
        "trir": trir,
        "dart_rate": dart,
        "total_recordable_cases": n_rec,
        "total_dart_cases": n_dart,
        "total_hours_worked": hours,
    })


@bp.get("/safety/establishments/<establishmentId>/cases")
def list_establishment_cases(establishmentId):
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    lookup(STORE.establishments, establishmentId)
    status = query_str("status")
    log_year = query_int("log_year")
    items = [c for c in STORE.cases.values()
             if c["establishment_id"] == establishmentId
             and (status is None or c["status"] == status)
             and (log_year is None or c["log_year"] == log_year)]
    page, limit, offset, total = paginated(items)
    return success_list([serialize_case(c) for c in page], limit, offset, total)


@bp.get("/safety/establishments/<establishmentId>/summaries")
def list_establishment_summaries(establishmentId):
    auth = get_auth()
    require_roles(auth, RATES_READ_ROLES)
    lookup(STORE.establishments, establishmentId)
    year = query_int("year")
    status = query_str("status")
    items = [s for s in STORE.summaries.values()
             if s["establishment_id"] == establishmentId
             and (year is None or s["year"] == year)
             and (status is None or s["status"] == status)]
    page, limit, offset, total = paginated(items)
    return success_list([serialize(s) for s in page], limit, offset, total)


@bp.get("/safety/establishments/<establishmentId>/hour-logs")
def list_establishment_hour_logs(establishmentId):
    auth = get_auth()
    require_roles(auth, RATES_READ_ROLES)
    lookup(STORE.establishments, establishmentId)
    year = query_int("year")
    status = query_str("status")
    items = [h for h in STORE.hour_logs.values()
             if h["establishment_id"] == establishmentId
             and (year is None or h["year"] == year)
             and (status is None or h["status"] == status)]
    page, limit, offset, total = paginated(items)
    return success_list([serialize(h) for h in page], limit, offset, total)


@bp.get("/safety/establishments/<establishmentId>/inspections")
def list_establishment_inspections(establishmentId):
    auth = get_auth()
    require_roles(auth, RATES_READ_ROLES)
    lookup(STORE.establishments, establishmentId)
    status = query_str("status")
    items = [i for i in STORE.inspections.values()
             if i["establishment_id"] == establishmentId
             and (status is None or i["status"] == status)]
    page, limit, offset, total = paginated(items)
    return success_list([serialize(i) for i in page], limit, offset, total)


@bp.get("/safety/establishments/<establishmentId>/corrective-actions")
def list_establishment_corrective_actions(establishmentId):
    auth = get_auth()
    require_roles(auth, RATES_READ_ROLES)
    lookup(STORE.establishments, establishmentId)
    status = query_str("status")
    items = [a for a in STORE.corrective_actions.values()
             if a["establishment_id"] == establishmentId
             and (status is None or a["status"] == status)]
    page, limit, offset, total = paginated(items)
    return success_list([serialize(a) for a in page], limit, offset, total)
