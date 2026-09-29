"""Placement requests: creation, unit assignment, site confirmation, permits,
withdrawal and decommissioning."""

from flask import Blueprint

import constants as C
from clock import clock
from db import db, new_record, public, touch
from errors import fail
from middleware import require
from response import created, ok
from routes.common import list_response, query_enum
from services import cascade
from services.cost import (
    alternatives, recompute_request_costs, relocation_estimate,
    required_permit_types,
)
from services.feasibility import fire_access_ok, pad_admits
from services.selection import select_unit
from validation import (
    get_body, lookup, need_date, need_int, need_string, opt_string,
    resolve_body_fk,
)

bp = Blueprint("requests", __name__)


def _require_serviceable(unit):
    """Rule 15."""
    if unit is not None and unit["condition_status"] != "SERVICEABLE":
        fail("ERR_UNIT_NOT_SERVICEABLE",
             "The assigned portable unit is %s, not SERVICEABLE."
             % unit["condition_status"])


def _require_relocation_headroom(unit):
    """Rule 29."""
    if unit is not None and unit["lifetime_relocation_count"] >= C.MAX_LIFETIME_RELOCATIONS:
        fail("ERR_UNIT_RELOCATION_LIMIT",
             "That unit has already been relocated %d times."
             % unit["lifetime_relocation_count"])


@bp.post("/placement-requests")
def create_request():
    require(["FacilitiesPlanner"])
    body = get_body()
    # rule 5: entity-declaration order
    study = resolve_body_fk("study", body, "capacity_study_id")
    site = resolve_body_fk("site", body, "placement_site_id")
    unit = resolve_body_fk("unit", body, "portable_unit_id")
    budget = resolve_body_fk("budget", body, "capital_budget_id")
    # rule 6
    if study is None:
        need_string(body, "capacity_study_id")
    if site is None:
        need_string(body, "placement_site_id")
    if budget is None:
        need_string(body, "capital_budget_id")
    window_start, start_date = need_date(body, "requested_window_start")
    window_end, end_date = need_date(body, "requested_window_end")
    haul_miles = need_int(body, "haul_miles", 0, 500)
    expected = need_int(body, "expected_study_version", minimum=0)
    # rule 9
    if expected != study["version"]:
        fail("ERR_STALE_STUDY_VERSION",
             "Study version is %d, not %d." % (study["version"], expected))
    # rule 10: the reservation gate on the unit's own allocation dimension
    if unit is not None and unit["allocation_status"] != "IN_STORAGE":
        fail("ERR_UNIT_STATE_INVALID",
             "A unit in %s cannot be reserved." % unit["allocation_status"])
    # rule 15
    _require_serviceable(unit)
    # rule 16
    if unit is not None and unit["condition_grade"] == "D":
        fail("ERR_UNIT_GRADE_NOT_PLACEABLE",
             "A grade D unit is never placeable.")
    # rule 20
    if site["school_id"] != study["school_id"]:
        fail("ERR_SITE_SCHOOL_MISMATCH",
             "The pad belongs to a campus other than the one the study measured.")
    # rule 29
    _require_relocation_headroom(unit)
    # rule 30
    if unit is not None and not pad_admits(site, unit["size_class"]):
        fail("ERR_PAD_TOO_SMALL",
             "The pad does not admit a %s with its clearance." % unit["size_class"])
    # rule 31
    if site["occupied_by_unit_id"] is not None:
        fail("ERR_SITE_OCCUPIED", "That pad is already occupied.")
    # rule 34
    if end_date < start_date:
        fail("ERR_INVALID_WINDOW",
             "requested_window_end must not be earlier than requested_window_start.")

    rec = new_record({
        "capacity_study_id": study["id"],
        "school_id": study["school_id"],
        "placement_site_id": site["id"],
        "portable_unit_id": unit["id"] if unit else None,
        "capital_budget_id": budget["id"],
        "status": "DRAFT",
        "requested_window_start": window_start,
        "requested_window_end": window_end,
        "haul_miles": haul_miles,
        "required_permit_count": 0,
        "estimated_relocation_cost_cents": 0,
        "encumbered_cost_cents": 0,
        "cost_recommendation": None,
        "rejection_reason": None,
    })
    db.requests[rec["id"]] = rec

    touch(study)
    if unit is not None:
        cascade.reserve_unit(unit)
    recompute_request_costs(rec)
    return created(public(rec))


@bp.get("/placement-requests/<request_id>")
def read_request(request_id):
    require(C.ALL_EXCEPT_CREW_LEAD)
    return ok(public(lookup("request", request_id)))


@bp.get("/placement-requests")
def list_requests():
    require(C.ALL_EXCEPT_CREW_LEAD)
    return list_response(db.requests, [
        "capacity_study_id", "school_id", "portable_unit_id",
        "placement_site_id", "capital_budget_id", "status",
    ])


@bp.get("/placement-requests/<request_id>/cost-model")
def cost_model(request_id):
    require(["DistrictAdmin", "FacilitiesPlanner", "CapacityCertifier"])
    req = lookup("request", request_id)
    basis = query_enum("basis", C.COST_BASES, "LIFECYCLE_20YR")
    estimate = relocation_estimate(req)
    alts = alternatives(req, estimate["estimated_relocation_cost_cents"], basis)
    return ok({
        "basis": basis,
        "mobilisation_cents": estimate["mobilisation_cents"],
        "site_work_cents": estimate["site_work_cents"],
        "rehab_cents": estimate["rehab_cents"],
        "permit_fee_cents": estimate["permit_fee_cents"],
        "direct_cost_cents": estimate["direct_cost_cents"],
        "contingency_cents": estimate["contingency_cents"],
        "off_summer_applied": estimate["off_summer_applied"],
        "estimated_relocation_cost_cents": estimate["estimated_relocation_cost_cents"],
        "relocation_direct_cents": alts["relocation_direct_cents"],
        "relocation_soft_cost_cents": alts["relocation_soft_cost_cents"],
        "relocation_total_program_cost_cents": alts["relocation_total_program_cost_cents"],
        "boundary_change_direct_cents": alts["boundary_change_direct_cents"],
        "boundary_change_total_program_cost_cents": alts["boundary_change_total_program_cost_cents"],
        "permanent_addition_direct_cents": alts["permanent_addition_direct_cents"],
        "permanent_addition_soft_cost_cents": alts["permanent_addition_soft_cost_cents"],
        "permanent_addition_total_program_cost_cents": alts["permanent_addition_total_program_cost_cents"],
        "relocate_excluded_for_reliance": alts["relocate_excluded_for_reliance"],
        "cost_recommendation": alts["cost_recommendation"],
    })


@bp.post("/placement-requests/<request_id>/auto-assign-unit")
def auto_assign_unit(request_id):
    require(["FacilitiesPlanner"])
    req = lookup("request", request_id)
    # rule 10
    if req["status"] != "DRAFT":
        fail("ERR_REQUEST_STATE_INVALID",
             "A request in %s cannot have a unit auto-assigned." % req["status"])
    existing = db.units.get(req.get("portable_unit_id"))
    # rules 15 and 29 against any unit already on the request
    _require_serviceable(existing)
    _require_relocation_headroom(existing)

    site = db.sites[req["placement_site_id"]]
    chosen = select_unit(site)
    if chosen is None:
        fail("ERR_NO_ELIGIBLE_UNIT",
             "No portable unit in the district satisfies the selection rule.")

    if existing is not None and existing["id"] != chosen["id"]:
        cascade.release_unit(existing)
    req["portable_unit_id"] = chosen["id"]
    cascade.reserve_unit(chosen)
    recompute_request_costs(req)
    touch(req)
    return ok(public(req))


@bp.post("/placement-requests/<request_id>/assess-site")
def confirm_site(request_id):
    require(["FacilitiesPlanner"])
    req = lookup("request", request_id)
    # rule 10
    if req["status"] != "DRAFT":
        fail("ERR_REQUEST_STATE_INVALID",
             "A request in %s cannot be site-confirmed." % req["status"])
    study = db.studies[req["capacity_study_id"]]
    # rule 11
    if study["status"] != "CERTIFIED":
        fail("ERR_STUDY_NOT_CERTIFIED",
             "The justifying study is %s, not CERTIFIED." % study["status"])
    unit = db.units.get(req.get("portable_unit_id"))
    if unit is None:
        fail("ERR_REQUEST_STATE_INVALID",
             "No portable unit has been assigned to this request yet.")
    # rule 15
    _require_serviceable(unit)
    site = db.sites[req["placement_site_id"]]
    school = db.schools[req["school_id"]]
    # rule 17, deliberately ahead of rule 18
    if not fire_access_ok(site, school):
        fail("ERR_FIRE_ACCESS_NONCOMPLIANT",
             "The pad or the campus fire lane fails the fire-access rule.")
    # rule 18
    if (site["feasibility_status"] not in ("FEASIBLE", "FEASIBLE_WITH_MITIGATION")
            or site["assessed_for_size_class"] != unit["size_class"]):
        fail("ERR_SITE_NOT_FEASIBLE",
             "The pad is not cleared for a %s." % unit["size_class"])

    req["status"] = "SITE_ASSESSED"
    touch(req)
    return ok(public(req))


@bp.post("/placement-requests/<request_id>/submit-permits")
def submit_permits(request_id):
    require(["PermitCoordinator"])
    req = lookup("request", request_id)
    # rule 10
    if req["status"] != "SITE_ASSESSED":
        fail("ERR_REQUEST_STATE_INVALID",
             "A request in %s cannot have its permit set filed." % req["status"])
    unit = db.units.get(req.get("portable_unit_id"))
    if unit is None:
        fail("ERR_REQUEST_STATE_INVALID",
             "No portable unit has been assigned to this request yet.")
    # rule 15
    _require_serviceable(unit)

    site = db.sites[req["placement_site_id"]]
    for permit_type in required_permit_types(unit, site):
        permit = new_record({
            "placement_request_id": req["id"],
            "permit_type": permit_type,
            "status": "SUBMITTED",
            "review_cycle_count": 0,
            "submitted_on": clock.iso(),
            "approved_on": None,
            "correction_note": None,
        })
        db.permits[permit["id"]] = permit

    req["required_permit_count"] = len(required_permit_types(unit, site))
    req["status"] = "PERMIT_PENDING"
    touch(req)
    return ok(public(req))


@bp.post("/placement-requests/<request_id>/withdraw")
def withdraw(request_id):
    require(["FacilitiesPlanner"])
    req = lookup("request", request_id)
    body = get_body()
    reason = need_string(body, "reason", 1, 2000)
    if req["status"] not in C.NON_TERMINAL_REQUEST_STATUSES_FOR_WITHDRAW:
        fail("ERR_REQUEST_STATE_INVALID",
             "A request in %s cannot be withdrawn." % req["status"])
    cascade.withdraw_request(req, reason, "REQUEST_WITHDRAWN")
    return ok(public(req))


@bp.post("/placement-requests/<request_id>/request-decommission")
def request_decommission(request_id):
    require(["AssetManager"])
    req = lookup("request", request_id)
    body = get_body()
    opt_string(body, "reason", None, 1, 2000)
    if req["status"] != "INSTALLED":
        fail("ERR_REQUEST_STATE_INVALID",
             "A request in %s cannot open decommissioning." % req["status"])
    unit = db.units.get(req.get("portable_unit_id"))
    if unit is None or unit["allocation_status"] != "INSTALLED":
        fail("ERR_UNIT_STATE_INVALID",
             "The unit is not INSTALLED and cannot move to PENDING_REMOVAL.")

    req["status"] = "DECOMMISSION_REQUESTED"
    touch(req)
    unit["allocation_status"] = "PENDING_REMOVAL"
    touch(unit)
    return ok(public(req))


@bp.post("/placement-requests/<request_id>/complete-decommission")
def complete_decommission(request_id):
    require(["AssetManager"])
    req = lookup("request", request_id)
    if req["status"] != "DECOMMISSION_REQUESTED":
        fail("ERR_REQUEST_STATE_INVALID",
             "A request in %s cannot complete decommissioning." % req["status"])
    unit = db.units.get(req.get("portable_unit_id"))
    if unit is None or unit["allocation_status"] != "PENDING_REMOVAL":
        fail("ERR_UNIT_STATE_INVALID",
             "The unit is not PENDING_REMOVAL.")
    budget = db.budgets.get(req.get("capital_budget_id"))
    removal = C.REMOVAL_CENTS_BY_SIZE[unit["size_class"]]
    # rule 40
    if budget is not None and budget["uncommitted_cents"] < removal:
        fail("ERR_BUDGET_INSUFFICIENT",
             "The appropriation has %d uncommitted cents; %d are needed."
             % (budget["uncommitted_cents"], removal))

    cascade.decommission_complete(req, unit, budget, removal)
    return ok(public(req))
