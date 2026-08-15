"""SparePartsPackage endpoints (PRD §3.7)."""
from flask import Blueprint, request

from db import children, store
from errors import invalid_state, not_found
from middleware import authenticate
from middleware import ROLE_FINANCE_ADMIN as FA
from middleware import ROLE_PROJECT_ENGINEER as PE
from middleware import ROLE_SITE_SUPERVISOR as SS
from middleware import ROLE_SERVICE_MANAGER as SM
from response import success, success_list
from services.domain import common_fields, compute_forecast, pub, pubs, site_of_project, touch
from validation import as_int, as_str, body, paginate, pagination, req

bp = Blueprint("packages", __name__)

READ_ROLES = {FA, PE, SS, SM}


def get_package(package_id):
    p = store.packages.get(package_id)
    if p is None:
        raise not_found("Spare parts package not found")
    return p


@bp.post("/robotics/cell-projects/<project_id>/spare-parts-packages")
def create_package(project_id):
    authenticate({SM})
    project = store.projects.get(project_id)
    if project is None:
        raise not_found("Cell project not found")
    b = body()
    package = {
        **common_fields(),
        "cell_project_id": project_id,
        "package_code": as_str(req(b, "package_code"), "package_code"),
        "list_price_cents": as_int(req(b, "list_price_cents"), "list_price_cents", min_v=0),
        "recommended_coverage_months": as_int(req(b, "recommended_coverage_months"),
                                              "recommended_coverage_months", 1, 60),
        "forecast_consumption_months": None,
        "package_status": "QUOTED",
    }
    # quoted_forecast variant: current shift_windows_per_day snapshot.
    compute_forecast(package, site_of_project(project))
    store.packages[package["id"]] = package
    return success(pub(package), 201)


@bp.get("/robotics/cell-projects/<project_id>/spare-parts-packages")
def list_packages(project_id):
    authenticate(READ_ROLES)
    if project_id not in store.projects:
        raise not_found("Cell project not found")
    limit, offset = pagination()
    items = children("packages", "cell_project_id", project_id)
    status_filter = request.args.get("package_status")
    if status_filter is not None:
        items = [p for p in items if p["package_status"] == status_filter]
    page, total = paginate(items, limit, offset)
    return success_list(pubs(page), limit, offset, total)


@bp.get("/robotics/spare-parts-packages/<package_id>")
def get_one_package(package_id):
    authenticate(READ_ROLES)
    return success(pub(get_package(package_id)))


@bp.post("/robotics/spare-parts-packages/<package_id>/order")
def order_package(package_id):
    authenticate({SM})
    p = get_package(package_id)
    if p["package_status"] != "QUOTED":
        raise invalid_state("Only a QUOTED package can be ordered")
    p["package_status"] = "ORDERED"
    touch(p)
    return success(pub(p))


@bp.post("/robotics/spare-parts-packages/<package_id>/deliver")
def deliver_package(package_id):
    authenticate({SM})
    p = get_package(package_id)
    if p["package_status"] != "ORDERED":
        raise invalid_state("Only an ORDERED package can be delivered")
    p["package_status"] = "DELIVERED"
    # delivered_forecast variant: re-derive with the then-current shift count.
    compute_forecast(p, site_of_project(store.projects[p["cell_project_id"]]))
    touch(p)
    return success(pub(p))
