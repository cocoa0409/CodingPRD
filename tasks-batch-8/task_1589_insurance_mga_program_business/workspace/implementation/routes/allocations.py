"""Capacity allocations: OCC-guarded create with supersede, and carrier
release (PRD sections 2.7, 2.9, 3.2)."""
from flask import Blueprint, request

import serialize
from db import STORE, new_entity, touch
from errors import raise_err, ERR_STALE_VERSION, ERR_INVALID_STATE
from middleware import require_roles, require_carrier_owner, ALL_ROLES
from response import success_object
from routes.common import get_or_404, render_list, filter_query
from routes.programs import require_program_not_terminal
from services import capacity
from validation import get_body, req_str, req_int, req_int_pos

bp = Blueprint("allocations", __name__)


@bp.post("/mga/programs/<programId>/capacity-allocations")
def create_allocation(programId):
    require_roles("CarrierUnderwriter")
    program = get_or_404(STORE.programs, programId, "Program")
    require_carrier_owner(program)
    body = get_body()
    period_label = req_str(body, "period_label")
    allocated_cents = req_int_pos(body, "allocated_cents")
    expected_program_version = req_int(body, "expected_program_version")
    # Stage 6 (OCC) before stage 7 (terminal check).
    if expected_program_version != program["version"]:
        raise_err(
            ERR_STALE_VERSION,
            "expected_program_version %s does not match current program version %s."
            % (expected_program_version, program["version"]),
        )
    require_program_not_terminal(program)
    # The incumbent non-terminal tranche is superseded; its unconsumed
    # remainder is reported as released to the carrier.
    incumbent = capacity.current_tranche(program["id"])
    if incumbent is not None:
        incumbent["status"] = "SUPERSEDED"
        touch(incumbent)
    a = new_entity()
    a.update({
        "program_id": program["id"],
        "period_label": period_label,
        "allocated_cents": allocated_cents,
        "consumed_cents": 0,
        "status": "ACTIVE",
    })
    STORE.capacity_allocations[a["id"]] = a
    touch(program)
    return success_object(serialize.allocation(a), status=201)


@bp.get("/mga/programs/<programId>/capacity-allocations")
def list_program_allocations(programId):
    require_roles(*ALL_ROLES)
    get_or_404(STORE.programs, programId, "Program")
    items = filter_query(
        [a for a in STORE.capacity_allocations.values() if a["program_id"] == programId],
        status=request.args.get("status"),
    )
    return render_list(items, serialize.allocation)


@bp.get("/mga/capacity-allocations/<allocationId>")
def get_allocation(allocationId):
    require_roles(*ALL_ROLES)
    a = get_or_404(STORE.capacity_allocations, allocationId, "CapacityAllocation")
    return success_object(serialize.allocation(a))


@bp.get("/mga/capacity-allocations")
def list_allocations():
    require_roles(*ALL_ROLES)
    items = filter_query(
        list(STORE.capacity_allocations.values()),
        program_id=request.args.get("program_id"),
        status=request.args.get("status"),
    )
    return render_list(items, serialize.allocation)


@bp.post("/mga/capacity-allocations/<allocationId>/release")
def release_allocation(allocationId):
    require_roles("CarrierUnderwriter")
    a = get_or_404(STORE.capacity_allocations, allocationId, "CapacityAllocation")
    program = STORE.programs[a["program_id"]]
    require_carrier_owner(program)
    if a["status"] not in ("ACTIVE", "EXHAUSTED"):
        raise_err(ERR_INVALID_STATE, "Only an ACTIVE or EXHAUSTED allocation can be released.")
    a["status"] = "RELEASED"
    touch(a)
    return success_object(serialize.allocation(a))
