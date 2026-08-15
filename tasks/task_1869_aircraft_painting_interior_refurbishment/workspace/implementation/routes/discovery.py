"""DiscoveryItem endpoints (OPEN -> ESTIMATED -> APPROVED/REJECTED/DEFERRED -> COMPLETED)."""
from flask import Blueprint, request

import calc
from db import STORE, now_dt
from domain import (new_entity, bump, bump_program, regen_draft_invoices,
                    get_or_404, by_created, serialize_discovery)
from errors import (ApiError, ref_integrity, invalid_state, bad_request,
                    ERR_FORBIDDEN_OWNERSHIP, ERR_STALE_PROGRAM_VERSION,
                    ERR_SAFETY_DEFERRAL_FORBIDDEN, ERR_DELIVERY_WINDOW_PASSED,
                    ERR_DEFER_REASON_REQUIRED)
from middleware import auth
from response import success
from validation import get_body, field, paginate

bp = Blueprint("discovery", __name__)

LOGGABLE_PHASES = ("INDUCTED", "SURFACE_REVIEW", "IN_WORK", "IN_INSPECTION")


def _ownership_check(user_id, prog):
    if user_id != prog["customer_id"]:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403,
                       "X-User-ID does not match the program's customer_id")


@bp.post("/discovery-items")
def create_discovery_item():
    auth("ShopTechnician")
    data = get_body(required=True)
    program_id = field(data, "program_id", "str")
    description = field(data, "description", "str")
    assessment_id = field(data, "assessment_id", "str", required=False, default=None)
    safety_linked = field(data, "safety_linked", "bool", required=False, default=False)
    prog = STORE.programs.get(program_id)
    if prog is None:
        raise ref_integrity("program_id does not reference an existing program")
    if prog["status"] not in LOGGABLE_PHASES:
        raise invalid_state(
            "Discovery items may be logged only in INDUCTED, SURFACE_REVIEW, "
            "IN_WORK or IN_INSPECTION")
    if assessment_id is not None:
        assessment = STORE.surface_assessments.get(assessment_id)
        if assessment is None or assessment["program_id"] != program_id:
            raise ref_integrity(
                "assessment_id must reference an assessment of the same program")
    item = new_entity()
    item.update({
        "program_id": program_id,
        "assessment_id": assessment_id,
        "source": "MANUAL",
        "description": description,
        "safety_linked": safety_linked,
        "status": "OPEN",
        "est_cost_cents": None,
        "est_hours": None,
        "actual_cost_cents": None,
        "defer_reason": None,
    })
    STORE.discovery_items[item["id"]] = item
    return success(serialize_discovery(item), status=201)


@bp.get("/discovery-items/<did>")
def get_discovery_item(did):
    auth()
    item = get_or_404(STORE.discovery_items, did, "DiscoveryItem")
    return success(serialize_discovery(item))


@bp.get("/discovery-items")
def list_discovery_items():
    auth()
    items = by_created(list(STORE.discovery_items.values()))
    for key in ("program_id", "assessment_id", "status"):
        value = request.args.get(key)
        if value is not None:
            items = [d for d in items if d[key] == value]
    return paginate(items, serialize_discovery)


@bp.post("/discovery-items/<did>/estimate")
def estimate_discovery_item(did):
    auth("ProgramManager")
    data = get_body(required=True)
    est_cost_cents = field(data, "est_cost_cents", "int")
    est_hours = field(data, "est_hours", "int")
    item = get_or_404(STORE.discovery_items, did, "DiscoveryItem")
    if item["status"] != "OPEN":
        raise invalid_state("Only an OPEN discovery item can be estimated")
    item["est_cost_cents"] = est_cost_cents
    item["est_hours"] = est_hours
    item["status"] = "ESTIMATED"
    bump(item)
    return success(serialize_discovery(item))


@bp.post("/discovery-items/<did>/approve")
def approve_discovery_item(did):
    user_id, _ = auth("CustomerRep")
    data = get_body(required=True)
    expected = field(data, "expected_program_version", "int")
    item = get_or_404(STORE.discovery_items, did, "DiscoveryItem")
    prog = STORE.programs[item["program_id"]]
    _ownership_check(user_id, prog)
    if expected != prog["version"]:
        raise ApiError(ERR_STALE_PROGRAM_VERSION, 412,
                       "expected_program_version does not match the program version")
    if item["status"] != "ESTIMATED":
        raise invalid_state("Only an ESTIMATED discovery item can be approved")
    item["status"] = "APPROVED"
    bump(item)
    bump_program(prog)
    regen_draft_invoices(prog["id"])
    return success(serialize_discovery(item))


@bp.post("/discovery-items/<did>/reject")
def reject_discovery_item(did):
    user_id, _ = auth("CustomerRep")
    item = get_or_404(STORE.discovery_items, did, "DiscoveryItem")
    prog = STORE.programs[item["program_id"]]
    _ownership_check(user_id, prog)
    if item["status"] != "ESTIMATED":
        raise invalid_state("Only an ESTIMATED discovery item can be rejected")
    item["status"] = "REJECTED"
    bump(item)
    return success(serialize_discovery(item))


@bp.post("/discovery-items/<did>/defer")
def defer_discovery_item(did):
    user_id, _ = auth("CustomerRep")
    data = get_body()
    if "defer_reason" in data and data["defer_reason"] is not None \
            and not isinstance(data["defer_reason"], str):
        raise bad_request("defer_reason must be a string")
    defer_reason = data.get("defer_reason")
    item = get_or_404(STORE.discovery_items, did, "DiscoveryItem")
    prog = STORE.programs[item["program_id"]]
    _ownership_check(user_id, prog)
    if item["status"] != "ESTIMATED":
        raise invalid_state("Only an ESTIMATED discovery item can be deferred")
    if item["safety_linked"]:
        raise ApiError(ERR_SAFETY_DEFERRAL_FORBIDDEN, 409,
                       "A safety_linked discovery item may never be deferred")
    committed = calc.committed_delivery_date(prog)
    if now_dt().date() > committed.date():
        raise ApiError(ERR_DELIVERY_WINDOW_PASSED, 409,
                       "The committed delivery window has passed")
    if not defer_reason:
        raise ApiError(ERR_DEFER_REASON_REQUIRED, 422,
                       "A non-empty defer_reason is required")
    item["defer_reason"] = defer_reason
    item["status"] = "DEFERRED"
    bump(item)
    return success(serialize_discovery(item))


@bp.post("/discovery-items/<did>/complete")
def complete_discovery_item(did):
    auth("ShopTechnician")
    data = get_body(required=True)
    actual_cost_cents = field(data, "actual_cost_cents", "int")
    item = get_or_404(STORE.discovery_items, did, "DiscoveryItem")
    if item["status"] != "APPROVED":
        raise invalid_state("Only an APPROVED discovery item can be completed")
    item["actual_cost_cents"] = actual_cost_cents
    item["status"] = "COMPLETED"
    bump(item)
    prog = STORE.programs[item["program_id"]]
    bump_program(prog)
    regen_draft_invoices(prog["id"])
    return success(serialize_discovery(item))
