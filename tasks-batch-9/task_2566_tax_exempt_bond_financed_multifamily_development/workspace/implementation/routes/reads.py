"""Read endpoints: fourteen single-resource fetches and eleven lists."""

from flask import Blueprint, request

import calc
import domain
import serialize
from auth import guard, own_delivery, own_developer, own_investor, own_project
from envelope import apply_list, object_response
from store import db

bp = Blueprint("reads", __name__)


# --------------------------------------------------------------------------
# single-resource reads
# --------------------------------------------------------------------------

@bp.get("/developers/<row_id>")
def get_developer(row_id):
    caller = guard("GET /developers/{id}")
    row = domain.soft_get(db.developers, row_id)
    own_developer(caller, row)
    row = domain.get_or_404(db.developers, row_id, "ERR_DEVELOPER_NOT_FOUND")
    return object_response(serialize.developer(row))


@bp.get("/investors/<row_id>")
def get_investor(row_id):
    caller = guard("GET /investors/{id}")
    row = domain.soft_get(db.investors, row_id)
    own_investor(caller, row)
    row = domain.get_or_404(db.investors, row_id, "ERR_INVESTOR_NOT_FOUND")
    return object_response(serialize.investor(row))


@bp.get("/cap-pools/<row_id>")
def get_cap_pool(row_id):
    guard("GET /cap-pools/{id}")
    row = domain.get_or_404(db.cap_pools, row_id, "ERR_CAP_POOL_NOT_FOUND")
    return object_response(serialize.cap_pool(row))


@bp.get("/projects/<row_id>")
def get_project(row_id):
    caller = guard("GET /projects/{id}")
    own_project(caller, domain.soft_get(db.projects, row_id))
    row = domain.get_or_404(db.projects, row_id, "ERR_PROJECT_NOT_FOUND")
    return object_response(serialize.project(row))


@bp.get("/volume-cap-allocations/<row_id>")
def get_allocation(row_id):
    caller = guard("GET /volume-cap-allocations/{id}")
    row = domain.soft_get(db.allocations, row_id)
    own_project(caller, domain.project_of_row(row))
    row = domain.get_or_404(db.allocations, row_id, "ERR_ALLOCATION_NOT_FOUND")
    return object_response(serialize.allocation(row))


@bp.get("/bond-issues/<row_id>")
def get_bond_issue(row_id):
    caller = guard("GET /bond-issues/{id}")
    row = domain.soft_get(db.bond_issues, row_id)
    own_project(caller, domain.project_of_row(row))
    row = domain.get_or_404(db.bond_issues, row_id, "ERR_BOND_ISSUE_NOT_FOUND")
    return object_response(serialize.bond_issue(row))


@bp.get("/draw-requests/<row_id>")
def get_draw(row_id):
    caller = guard("GET /draw-requests/{id}")
    row = domain.soft_get(db.draws, row_id)
    own_project(caller, domain.project_of_draw(row))
    row = domain.get_or_404(db.draws, row_id, "ERR_DRAW_REQUEST_NOT_FOUND")
    return object_response(serialize.draw(row))


@bp.get("/unit-restrictions/<row_id>")
def get_unit(row_id):
    caller = guard("GET /unit-restrictions/{id}")
    row = domain.soft_get(db.units, row_id)
    own_project(caller, domain.project_of_row(row))
    row = domain.get_or_404(db.units, row_id, "ERR_UNIT_RESTRICTION_NOT_FOUND")
    return object_response(serialize.unit(row))


@bp.get("/regulatory-agreements/<row_id>")
def get_agreement(row_id):
    caller = guard("GET /regulatory-agreements/{id}")
    row = domain.soft_get(db.agreements, row_id)
    own_project(caller, domain.project_of_row(row))
    row = domain.get_or_404(db.agreements, row_id, "ERR_REG_AGREEMENT_NOT_FOUND")
    return object_response(serialize.agreement(row))


@bp.get("/cost-certifications/<row_id>")
def get_cost_cert(row_id):
    caller = guard("GET /cost-certifications/{id}")
    row = domain.soft_get(db.cost_certs, row_id)
    own_project(caller, domain.project_of_row(row))
    row = domain.get_or_404(db.cost_certs, row_id, "ERR_COST_CERT_NOT_FOUND")
    return object_response(serialize.cost_cert(row))


@bp.get("/credit-allocations/<row_id>")
def get_credit_allocation(row_id):
    caller = guard("GET /credit-allocations/{id}")
    row = domain.soft_get(db.credit_allocations, row_id)
    own_project(caller, domain.project_of_row(row))
    row = domain.get_or_404(db.credit_allocations, row_id, "ERR_CREDIT_ALLOCATION_NOT_FOUND")
    return object_response(serialize.credit_allocation(row))


@bp.get("/investor-deliveries/<row_id>")
def get_delivery(row_id):
    caller = guard("GET /investor-deliveries/{id}")
    row = domain.soft_get(db.deliveries, row_id)
    own_delivery(caller, row, domain.project_of_delivery(row))
    row = domain.get_or_404(db.deliveries, row_id, "ERR_DELIVERY_NOT_FOUND")
    return object_response(serialize.delivery(row))


@bp.get("/compliance-reports/<row_id>")
def get_report(row_id):
    caller = guard("GET /compliance-reports/{id}")
    row = domain.soft_get(db.reports, row_id)
    own_project(caller, domain.project_of_row(row))
    row = domain.get_or_404(db.reports, row_id, "ERR_COMPLIANCE_REPORT_NOT_FOUND")
    return object_response(serialize.report(row))


@bp.get("/physical-inspections/<row_id>")
def get_inspection(row_id):
    caller = guard("GET /physical-inspections/{id}")
    row = domain.soft_get(db.inspections, row_id)
    own_project(caller, domain.project_of_row(row))
    row = domain.get_or_404(db.inspections, row_id, "ERR_INSPECTION_NOT_FOUND")
    return object_response(serialize.inspection(row))


# --------------------------------------------------------------------------
# list reads
# --------------------------------------------------------------------------

def _matches(row, filters):
    for field, raw in filters.items():
        value = row.get(field)
        if value is None:
            return False
        if str(value) != raw:
            return False
    return True


def _collect(rows, fields, sort_key):
    filters = {}
    for field in fields:
        raw = request.args.get(field)
        if raw is not None:
            filters[field] = raw
    selected = [r for r in rows if _matches(r, filters)]
    selected.sort(key=sort_key)
    return selected


def _created_order(row):
    return (row.get("created_at") or "", row.get("_seq") or 0)


@bp.get("/projects")
def list_projects():
    guard("GET /projects")
    rows = _collect(list(db.projects.values()),
                    ("developer_id", "development_status"), _created_order)
    return apply_list([serialize.project(r) for r in rows])


@bp.get("/volume-cap-allocations")
def list_allocations():
    guard("GET /volume-cap-allocations")
    rows = _collect(list(db.allocations.values()),
                    ("project_id", "cap_pool_id", "status"), _created_order)
    return apply_list([serialize.allocation(r) for r in rows])


@bp.get("/bond-issues")
def list_bond_issues():
    guard("GET /bond-issues")
    rows = _collect(list(db.bond_issues.values()),
                    ("project_id", "volume_cap_allocation_id", "status"), _created_order)
    return apply_list([serialize.bond_issue(r) for r in rows])


@bp.get("/draw-requests")
def list_draws():
    guard("GET /draw-requests")
    rows = _collect(
        list(db.draws.values()), ("bond_issue_id", "status"),
        lambda r: (r.get("period_start") or "", r.get("draw_number") or 0))
    return apply_list([serialize.draw(r) for r in rows])


@bp.get("/unit-restrictions")
def list_units():
    guard("GET /unit-restrictions")
    rows = _collect(list(db.units.values()),
                    ("project_id", "designation", "status"), calc.unit_sort_key)
    return apply_list([serialize.unit(r) for r in rows])


@bp.get("/regulatory-agreements")
def list_agreements():
    guard("GET /regulatory-agreements")
    rows = _collect(list(db.agreements.values()), ("project_id", "status"), _created_order)
    return apply_list([serialize.agreement(r) for r in rows])


@bp.get("/cost-certifications")
def list_cost_certs():
    guard("GET /cost-certifications")
    rows = _collect(list(db.cost_certs.values()), ("project_id", "status"), _created_order)
    return apply_list([serialize.cost_cert(r) for r in rows])


@bp.get("/credit-allocations")
def list_credit_allocations():
    guard("GET /credit-allocations")
    rows = _collect(list(db.credit_allocations.values()),
                    ("project_id", "cost_certification_id", "status"), _created_order)
    return apply_list([serialize.credit_allocation(r) for r in rows])


@bp.get("/investor-deliveries")
def list_deliveries():
    guard("GET /investor-deliveries")
    rows = _collect(list(db.deliveries.values()),
                    ("credit_allocation_id", "investor_id", "status"), _created_order)
    return apply_list([serialize.delivery(r) for r in rows])


@bp.get("/compliance-reports")
def list_reports():
    guard("GET /compliance-reports")
    rows = _collect(
        list(db.reports.values()), ("project_id", "reporting_year", "status"),
        lambda r: (r.get("reporting_year") or 0, r.get("created_at") or "",
                   r.get("_seq") or 0))
    return apply_list([serialize.report(r) for r in rows])


@bp.get("/physical-inspections")
def list_inspections():
    guard("GET /physical-inspections")
    rows = _collect(
        list(db.inspections.values()), ("project_id", "status"),
        lambda r: (r.get("window_start") or "", r.get("created_at") or "",
                   r.get("_seq") or 0))
    return apply_list([serialize.inspection(r) for r in rows])
