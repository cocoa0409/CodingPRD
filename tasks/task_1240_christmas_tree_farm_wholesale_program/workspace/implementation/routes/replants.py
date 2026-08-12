"""ReplantPlan endpoints: propose, read, list, approve, reject, execute
(PRD 3.1). Segregation of duties: the approver/rejector must differ from the
proposer (ERR_SOD_VIOLATION, priority 3)."""
from flask import Blueprint, request

from authz import require_role
from db import store
from errors import block_occupied, invalid_state, sod_violation
from helpers import (body, get_or_404, new_record, paginate, req_enum,
                     req_field, req_int, req_str, touch)
from respond import success
from serialize import replant_out
from routes.lots import create_lot_on_block
from services import HEIGHT_CLASSES, SPECIES

bp = Blueprint("replants", __name__)


@bp.post("/api/replant-plans")
def propose_replant():
    user_id, _role = require_role("FarmManager")
    data = body()
    block_id = req_field(data, "block_id")
    if isinstance(block_id, str):
        get_or_404(store.blocks, block_id, "block_id does not exist")
    block_id = req_str(data, "block_id")
    species = req_enum(data, "species", SPECIES)
    planned_count = req_int(data, "planned_count", minimum=1)
    # Referential (priority 12): the block must be HARVESTED at propose time.
    block = store.blocks[block_id]
    if block["rotation_state"] != "HARVESTED":
        raise block_occupied("Replant proposals require a HARVESTED block")
    rec = new_record({
        "block_id": block_id,
        "species": species,
        "planned_count": planned_count,
        "proposed_by_user_id": user_id,
        "approved_by_user_id": None,
        "created_crop_lot_id": None,
        "status": "PROPOSED",
    })
    store.replant_plans[rec["id"]] = rec
    return success(replant_out(rec), status=201)


@bp.get("/api/replant-plans/<rid>")
def get_replant(rid):
    require_role("Owner", "FarmManager")
    return success(replant_out(get_or_404(store.replant_plans, rid)))


@bp.get("/api/replant-plans")
def list_replants():
    require_role("Owner", "FarmManager")
    items = sorted(store.replant_plans.values(), key=lambda r: r["_seq"])
    block_id = request.args.get("block_id")
    if block_id is not None:
        items = [r for r in items if r["block_id"] == block_id]
    page, meta = paginate(items)
    return success([replant_out(r) for r in page], response_type="array",
                   pagination=meta)


def _decide(rid, approve):
    user_id, _role = require_role("Owner")
    plan = get_or_404(store.replant_plans, rid)
    # Segregation of duties (priority 3): the decider must differ from the
    # proposer. Evaluated before the state check.
    if user_id == plan["proposed_by_user_id"]:
        raise sod_violation("The decider must differ from the proposer")
    if plan["status"] != "PROPOSED":
        raise invalid_state("Only a PROPOSED plan can be decided")
    if approve:
        plan["approved_by_user_id"] = user_id
        plan["status"] = "APPROVED"
    else:
        plan["status"] = "REJECTED"
    touch(plan)
    return success(replant_out(plan))


@bp.post("/api/replant-plans/<rid>/approve")
def approve_replant(rid):
    return _decide(rid, approve=True)


@bp.post("/api/replant-plans/<rid>/reject")
def reject_replant(rid):
    return _decide(rid, approve=False)


@bp.post("/api/replant-plans/<rid>/execute")
def execute_replant(rid):
    require_role("FarmManager")
    plan = get_or_404(store.replant_plans, rid)
    if plan["status"] != "APPROVED":
        raise invalid_state("Only an APPROVED plan can be executed")
    block = store.blocks[plan["block_id"]]
    # Referential (priority 12): the block must still be HARVESTED.
    if block["rotation_state"] != "HARVESTED":
        raise block_occupied("The block has been re-occupied since approval")
    season = store.seasons[block["season_id"]]
    counts = {hc: 0 for hc in HEIGHT_CLASSES}
    counts["H_4_5"] = plan["planned_count"]
    lot = create_lot_on_block(block, plan["species"], season["year"], counts)
    plan["created_crop_lot_id"] = lot["id"]
    plan["status"] = "EXECUTED"
    touch(plan)
    return success(replant_out(plan))
