"""Existence lookups -> ERR_NOT_FOUND (404) when absent (PRD §2.5)."""
import db
import errors
from errors import err


def _get(table, rid):
    rec = table.get(rid)
    if rec is None:
        raise err(errors.ERR_NOT_FOUND, "Resource not found.")
    return rec


def doctor(rid):
    return _get(db.doctors, rid)


def material(rid):
    return _get(db.materials, rid)


def mill_machine(rid):
    return _get(db.mill_machines, rid)


def courier_route(rid):
    return _get(db.courier_routes, rid)


def case(rid):
    return _get(db.cases, rid)


def restoration(rid):
    return _get(db.restorations, rid)


def fabrication_unit(rid):
    return _get(db.fabrication_units, rid)


def mill_job(rid):
    return _get(db.mill_jobs, rid)


def route_stop(rid):
    return _get(db.route_stops, rid)


def invoice(rid):
    return _get(db.invoices, rid)


def credit_memo(rid):
    return _get(db.credit_memos, rid)


def remake_request(rid):
    return _get(db.remake_requests, rid)


# ---- Reverse-reachability helpers ----

def case_restorations(case_id):
    return [r for r in db.restorations.values() if r["case_id"] == case_id]


def restoration_units(restoration_id):
    return [u for u in db.fabrication_units.values() if u["restoration_id"] == restoration_id]


def case_units(case_id):
    rest_ids = {r["id"] for r in case_restorations(case_id)}
    return [u for u in db.fabrication_units.values() if u["restoration_id"] in rest_ids]


def case_invoice(case_id):
    return next((i for i in db.invoices.values() if i["case_id"] == case_id), None)


def case_route_stops(case_id):
    return [s for s in db.route_stops.values() if s["case_id"] == case_id]


def case_route_stops_on_route(route_id):
    return [s for s in db.route_stops.values() if s["courier_route_id"] == route_id]


def route_stops_on_route(route_id):
    return case_route_stops_on_route(route_id)


def unit_mill_jobs(unit_id):
    return [j for j in db.mill_jobs.values() if j["fabrication_unit_id"] == unit_id]


def machine_mill_jobs(machine_id):
    return [j for j in db.mill_jobs.values() if j["mill_machine_id"] == machine_id]
