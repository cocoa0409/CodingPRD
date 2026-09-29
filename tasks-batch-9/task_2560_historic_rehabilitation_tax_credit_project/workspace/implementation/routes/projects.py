"""Projects: opening, revising, placing in service, and the read-only roll-ups."""

from flask import Blueprint

import calc
import services
from auth import own_project, require
from db import base_record, ordered, public, store, touch
from errors import ApiError
from response import created_response, object_response
from support import fetch, filter_eq, respond_list
from validate import (
    bad,
    body,
    pagination,
    query_int,
    query_str,
    req_date,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("projects", __name__)

STRUCTURE_TYPES = ("MASTER_LEASE", "SINGLE_TIER")
MEASURING_MONTHS = (24, 60)

ALL_READ_ROLES = (
    "PlatformAdmin",
    "Developer",
    "ShpoReviewer",
    "NpsReviewer",
    "ComplianceMonitor",
    "InvestorAdmin",
)
COST_READ_ROLES = ("PlatformAdmin", "Developer", "ComplianceMonitor", "ShpoReviewer", "NpsReviewer")
LEDGER_READ_ROLES = ("PlatformAdmin", "Developer", "InvestorAdmin", "ComplianceMonitor")

OPEN_CERT_STATES = ("PRE_CERTIFICATION", "PART1_CERTIFIED", "PART2_APPROVED", "PART3_CERTIFIED")


def _overlap_conflict(property_id, start, end, exclude_id=None):
    """Half-open overlap against every non-DECERTIFIED project on the property."""
    for other in store.projects.values():
        if other["property_id"] != property_id or other["id"] == exclude_id:
            continue
        if other["certification_status"] == "DECERTIFIED":
            continue
        other_start = calc.date.fromisoformat(other["measuring_period_start_date"])
        other_end = calc.date.fromisoformat(other["measuring_period_end_date"])
        if calc.half_open_overlap(start, end, other_start, other_end):
            return True
    return False


# --------------------------------------------------------------------------
# create / read / list
# --------------------------------------------------------------------------


@bp.post("/projects")
def create_project():
    uid, _role = require("Developer")
    data = body()
    developer_id = req_str(data, "developer_id")
    property_id = req_str(data, "property_id")
    project_name = req_str(data, "project_name", min_len=1, max_len=120)
    structure_type = req_enum(data, "structure_type", STRUCTURE_TYPES)
    adjusted_basis = req_int(data, "adjusted_basis_cents", min_v=0)
    months = req_int(data, "measuring_period_months", allowed=MEASURING_MONTHS)
    start = req_date(data, "measuring_period_start_date")

    fetch(store.developers, developer_id, "ERR_DEVELOPER_NOT_FOUND")
    prop = fetch(store.properties, property_id, "ERR_PROPERTY_NOT_FOUND")

    if developer_id != uid:
        raise ApiError("ERR_UNAUTHORIZED", "A developer may not open a project for another taxpayer.")

    end = services.measuring_period_end(start, months)
    if _overlap_conflict(property_id, start, end):
        raise ApiError("ERR_PROPERTY_MEASURING_PERIOD_OVERLAP")

    record = base_record()
    record.update(
        {
            "property_id": property_id,
            "developer_id": developer_id,
            "project_name": project_name,
            "structure_type": structure_type,
            "adjusted_basis_cents": adjusted_basis,
            "measuring_period_months": months,
            "measuring_period_start_date": start.isoformat(),
            "measuring_period_end_date": end.isoformat(),
            "certification_status": "PRE_CERTIFICATION",
            "compliance_status": "NOT_MONITORED",
            "qre_total_final_cents": 0,
            "qre_total_provisional_cents": 0,
            "nonqualified_total_cents": 0,
            "classified_cost_total_cents": 0,
            "developer_fee_disallowed_cents": 0,
            "substantial_test_threshold_cents": calc.substantial_threshold(adjusted_basis),
            "substantial_test_status": "NOT_MET",
            "placed_in_service_date": None,
            "annual_credit_cents": 0,
            "total_claimable_credit_cents": 0,
            "credit_claimed_to_date_cents": 0,
            "credit_recaptured_cents": 0,
            "credit_unclaimed_cents": 0,
            "recapture_balance_cents": 0,
            "max_investor_risk_score": 0,
            "frozen_at_certification": False,
        }
    )
    store.projects[record["id"]] = record
    # Property.open_project_count is derived on read from the project set.
    return created_response(public(record))


@bp.get("/projects")
def list_projects():
    require(*ALL_READ_ROLES)
    limit, offset = pagination()
    rows = ordered(store.projects.values())
    rows = filter_eq(rows, "developer_id", query_str("developer_id"))
    rows = filter_eq(rows, "property_id", query_str("property_id"))
    rows = filter_eq(rows, "certification_status", query_str("certification_status"))
    rows = filter_eq(rows, "compliance_status", query_str("compliance_status"))
    return respond_list(rows, limit, offset)


@bp.get("/projects/<project_id>")
def read_project(project_id):
    require(*ALL_READ_ROLES)
    project = fetch(store.projects, project_id, "ERR_PROJECT_NOT_FOUND")
    return object_response(public(project))


# --------------------------------------------------------------------------
# revise basis / measuring period
# --------------------------------------------------------------------------


@bp.patch("/projects/<project_id>")
def patch_project(project_id):
    uid, _role = require("Developer")
    data = body()
    expected = req_int(data, "expected_project_version", min_v=0)
    adjusted_basis = req_int(data, "adjusted_basis_cents", min_v=0, required=False)
    start = req_date(data, "measuring_period_start_date", required=False)
    months = req_int(data, "measuring_period_months", allowed=MEASURING_MONTHS, required=False)

    project = fetch(store.projects, project_id, "ERR_PROJECT_NOT_FOUND")
    own_project(project, uid)

    if project["certification_status"] in ("PART3_CERTIFIED", "DECERTIFIED"):
        raise ApiError(
            "ERR_PROJECT_INVALID_STATE",
            "The basis and the measuring period freeze at certification of completed work.",
        )

    if expected != project["version"]:
        raise ApiError("ERR_STALE_PROJECT_VERSION")

    new_start = start if start is not None else calc.date.fromisoformat(
        project["measuring_period_start_date"]
    )
    new_months = months if months is not None else project["measuring_period_months"]
    new_end = services.measuring_period_end(new_start, new_months)

    if _overlap_conflict(project["property_id"], new_start, new_end, exclude_id=project["id"]):
        raise ApiError("ERR_PROPERTY_MEASURING_PERIOD_OVERLAP")

    if adjusted_basis is not None:
        project["adjusted_basis_cents"] = adjusted_basis
    project["measuring_period_start_date"] = new_start.isoformat()
    project["measuring_period_months"] = new_months
    project["measuring_period_end_date"] = new_end.isoformat()

    # Fixed ripple order: window -> item flags -> segregation -> test -> schedule.
    services.reevaluate_cost_windows(project)
    services.recompute_financials(project)
    touch(project)
    return object_response(public(project))


# --------------------------------------------------------------------------
# placed in service
# --------------------------------------------------------------------------


@bp.post("/projects/<project_id>/place-in-service")
def place_in_service(project_id):
    uid, _role = require("Developer")
    data = body()
    pis = req_date(data, "placed_in_service_date")

    project = fetch(store.projects, project_id, "ERR_PROJECT_NOT_FOUND")
    own_project(project, uid)

    if (
        project["certification_status"] in ("PART3_CERTIFIED", "DECERTIFIED")
        or project["placed_in_service_date"] is not None
    ):
        raise ApiError(
            "ERR_PROJECT_INVALID_STATE",
            "The placed-in-service date may be declared only once, before Part 3 certification.",
        )
    if project["certification_status"] not in ("PART2_APPROVED", "PART3_CERTIFIED"):
        raise ApiError("ERR_PROJECT_NOT_CERTIFIED")

    project["placed_in_service_date"] = pis.isoformat()
    if project["compliance_status"] == "NOT_MONITORED":
        project["compliance_status"] = "IN_SERVICE_MONITORING"
    services.rescore_in_service(project)
    touch(project)
    return object_response(public(project))


# --------------------------------------------------------------------------
# computed QRE summary
# --------------------------------------------------------------------------


@bp.get("/projects/<project_id>/qre-summary")
def qre_summary(project_id):
    require(*ALL_READ_ROLES)
    variant = query_str("variant") or "PROVISIONAL"
    if variant not in ("PROVISIONAL", "FINAL"):
        raise bad("Query parameter 'variant' must be PROVISIONAL or FINAL.")

    project = fetch(store.projects, project_id, "ERR_PROJECT_NOT_FOUND")
    items = services.project_costs(project_id)
    totals = calc.qre_totals(items, variant)
    threshold = calc.substantial_threshold(project["adjusted_basis_cents"])
    return object_response(
        {
            "variant_applied": variant,
            "qre_total_cents": totals["qre_total"],
            "hard_qre_cents": totals["hard_qre"],
            "developer_fee_claimed_cents": totals["fee_claimed"],
            "developer_fee_allowed_cents": totals["fee_allowed"],
            "developer_fee_disallowed_cents": totals["fee_disallowed"],
            "nonqualified_total_cents": totals["nonqualified_total"],
            "classified_cost_total_cents": totals["classified_cost_total"],
            "substantial_test_threshold_cents": threshold,
            "substantial_test_status_under_variant": calc.substantial_status(
                totals["qre_total"], threshold
            ),
            "in_period_item_count": totals["in_period_item_count"],
            "pending_classification_item_count": totals["pending_classification_item_count"],
        }
    )


# --------------------------------------------------------------------------
# sub-resource listings
# --------------------------------------------------------------------------


@bp.get("/projects/<project_id>/cost-line-items")
def list_project_costs(project_id):
    require(*COST_READ_ROLES)
    limit, offset = pagination()
    classification = query_str("classification")
    category = query_str("category")
    project = fetch(store.projects, project_id, "ERR_PROJECT_NOT_FOUND")
    rows = services.project_costs(project["id"])
    rows = filter_eq(rows, "classification", classification)
    rows = filter_eq(rows, "category", category)
    return respond_list(rows, limit, offset)


@bp.get("/projects/<project_id>/investor-interests")
def list_project_interests(project_id):
    require(*LEDGER_READ_ROLES)
    limit, offset = pagination()
    kind = query_str("kind")
    status = query_str("status")
    project = fetch(store.projects, project_id, "ERR_PROJECT_NOT_FOUND")
    rows = services.project_interests(project["id"])
    rows = filter_eq(rows, "kind", kind)
    rows = filter_eq(rows, "status", status)
    return respond_list(rows, limit, offset)


@bp.get("/projects/<project_id>/credit-claims")
def list_project_claims(project_id):
    require(*LEDGER_READ_ROLES)
    limit, offset = pagination()
    status = query_str("status")
    tax_year = query_int("tax_year")
    project = fetch(store.projects, project_id, "ERR_PROJECT_NOT_FOUND")
    rows = services.project_claims(project["id"])
    rows = filter_eq(rows, "status", status)
    rows = filter_eq(rows, "tax_year", tax_year)
    return respond_list(rows, limit, offset)


@bp.get("/projects/<project_id>/recapture-events")
def list_project_events(project_id):
    require(*LEDGER_READ_ROLES)
    limit, offset = pagination()
    event_type = query_str("event_type")
    status = query_str("status")
    project = fetch(store.projects, project_id, "ERR_PROJECT_NOT_FOUND")
    rows = services.project_events(project["id"])
    rows = filter_eq(rows, "event_type", event_type)
    rows = filter_eq(rows, "status", status)
    return respond_list(rows, limit, offset)


@bp.get("/projects/<project_id>/compliance-covenants")
def list_project_covenants(project_id):
    require(*LEDGER_READ_ROLES)
    limit, offset = pagination()
    covenant_type = query_str("covenant_type")
    status = query_str("status")
    project = fetch(store.projects, project_id, "ERR_PROJECT_NOT_FOUND")
    rows = services.project_covenants(project["id"])
    rows = filter_eq(rows, "covenant_type", covenant_type)
    rows = filter_eq(rows, "status", status)
    return respond_list(rows, limit, offset)
