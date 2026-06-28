"""Path and reference resolution (PRD 2.9).

Path identifiers are validated left to right: the parent is resolved before any
child, and a missing identifier anywhere produces ERR_RESOURCE_NOT_FOUND for the
first one that does not resolve. Body foreign keys that do not exist also produce
ERR_RESOURCE_NOT_FOUND (priority 3 — existence is checked before request-shape).
"""

from db import db
from errors import err


def _get_or_404(collection, rid, label):
    rec = collection.get(rid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND", f"{label} not found.")
    return rec


def get_customer(rid):
    return _get_or_404(db.customers, rid, "Customer")


def get_project(rid):
    return _get_or_404(db.projects, rid, "Project")


def get_transformer(rid):
    return _get_or_404(db.transformers, rid, "Transformer")


def get_zone(rid):
    return _get_or_404(db.zones, rid, "Zone")


def get_fixture(rid):
    return _get_or_404(db.fixtures, rid, "Fixture")


def get_quote(rid):
    return _get_or_404(db.quotes, rid, "Quote")


def get_quote_line(rid):
    return _get_or_404(db.quote_lines, rid, "QuoteLine")


def get_install_job(rid):
    return _get_or_404(db.install_jobs, rid, "InstallJob")


def get_schedule_program(rid):
    return _get_or_404(db.schedule_programs, rid, "ScheduleProgram")


def get_service_plan(rid):
    return _get_or_404(db.service_plans, rid, "ServicePlan")


def get_service_visit(rid):
    return _get_or_404(db.service_visits, rid, "ServiceVisit")


def get_crew_route(rid):
    return _get_or_404(db.crew_routes, rid, "CrewRoute")


def get_warranty_claim(rid):
    return _get_or_404(db.warranty_claims, rid, "WarrantyClaim")


def get_add_on(rid):
    return _get_or_404(db.add_ons, rid, "AddOnModule")
