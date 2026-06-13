"""Draw pipeline: request, approve, reject, pay (with escrow ledger moves)."""
from flask import Blueprint, request

import db
import errors
import response
from middleware import require_roles
from services import common, lookups, calculations

bp = Blueprint("draws", __name__)


def _owner_check_draw(draw, user_id, role):
    if role == "Contractor" and draw["contractor_id"] != user_id:
        raise errors.not_owner("Contractor does not own this draw.")


@bp.route("/draws", methods=["POST"])
def request_draw():
    user_id, role = require_roles("Contractor")
    body = common.get_body()
    project_id = common.as_str(common.require_field(body, "project_id"), "project_id")
    milestone_id = common.as_str(common.require_field(body, "milestone_id"), "milestone_id")
    waiver_amount = common.as_int(
        common.require_field(body, "conditional_waiver_amount_cents"),
        "conditional_waiver_amount_cents")

    # existence (priority 4)
    project = lookups.get_project(project_id)
    milestone = lookups.get_milestone(milestone_id)
    if milestone["project_id"] != project_id:
        raise errors.not_found("Milestone does not belong to the project.")

    # ownership (priority 3): the contractor must be the project's awarded-bid contractor
    awarded_bid = None
    if project["awarded_bid_id"]:
        awarded_bid = lookups.get_bid(project["awarded_bid_id"])
    if role == "Contractor":
        if awarded_bid is None or awarded_bid["contractor_id"] != user_id:
            raise errors.not_owner("Only the awarded contractor may request draws.")

    # state (priority 5): project IN_PROGRESS; milestone PENDING
    if project["status"] != "IN_PROGRESS":
        raise errors.invalid_state("Project must be IN_PROGRESS to request a draw.")
    if milestone["status"] != "PENDING":
        raise errors.invalid_state("Milestone is not in a drawable (PENDING) state.")

    # sequential ordering (priority 12): must be lowest-sequence PENDING milestone
    all_ms = lookups.milestones_for_project(project_id)
    pending = [m for m in all_ms if m["status"] == "PENDING"]
    lowest_pending = min(pending, key=lambda m: m["sequence"])
    if milestone["id"] != lowest_pending["id"]:
        raise errors.ApiError(errors.ERR_MILESTONE_OUT_OF_ORDER, 409,
                              "Draws must be requested for the lowest-sequence PENDING milestone.")

    # compute frozen amounts
    max_seq = max(m["sequence"] for m in all_ms)
    is_final = milestone["sequence"] == max_seq
    gross, retainage, net = calculations.draw_amounts(
        project["contract_value_cents"], milestone["release_pct"], is_final)

    # lien-waiver requirement (priority 11): conditional amount must equal net_release
    if waiver_amount != net:
        raise errors.ApiError(errors.ERR_LIEN_WAIVER_REQUIRED, 422,
                              "conditional_waiver_amount_cents must equal the draw net_release_cents.")

    # ---- create draw, conditional waiver, advance milestone ----
    contractor_id = awarded_bid["contractor_id"]
    draw = {
        "project_id": project_id,
        "milestone_id": milestone_id,
        "contractor_id": contractor_id,
        "gross_amount_cents": gross,
        "retainage_cents": retainage,
        "net_release_cents": net,
        "lien_waiver_id": None,
        "status": "REQUESTED",
    }
    common.stamp_new(draw)
    db.draws[draw["id"]] = draw

    waiver = {
        "project_id": project_id,
        "contractor_id": contractor_id,
        "draw_id": draw["id"],
        "waiver_type": "CONDITIONAL",
        "amount_cents": net,
        "status": "COLLECTED",
    }
    common.stamp_new(waiver)
    db.lien_waivers[waiver["id"]] = waiver

    draw["lien_waiver_id"] = waiver["id"]
    common.touch(draw)

    milestone["status"] = "DRAW_REQUESTED"
    common.touch(milestone)

    return response.success(common.public(draw), 201)


@bp.route("/draws/<rid>", methods=["GET"])
def get_draw(rid):
    require_roles("Contractor", "Homeowner", "EscrowAgent", "PlatformAdmin")
    rec = lookups.get_draw(rid)
    return response.success(common.public(rec), 200)


@bp.route("/draws", methods=["GET"])
def list_draws():
    require_roles("Contractor", "Homeowner", "EscrowAgent", "PlatformAdmin")
    items = list(db.draws.values())
    for field in ("project_id", "milestone_id", "contractor_id", "lien_waiver_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [d for d in items if d.get(field) == val]
    page, limit, offset, total = common.paginate(items)
    return response.success_list(page, limit, offset, total, 200)


def _project_owner_check(project, user_id, role):
    if role == "Homeowner" and project["homeowner_id"] != user_id:
        raise errors.not_owner("Homeowner does not own this draw's project.")


@bp.route("/draws/<rid>/approve", methods=["POST"])
def approve_draw(rid):
    user_id, role = require_roles("Homeowner")
    draw = lookups.get_draw(rid)
    project = lookups.get_project(draw["project_id"])
    _project_owner_check(project, user_id, role)
    if draw["status"] != "REQUESTED":
        raise errors.invalid_state("Only a REQUESTED draw can be approved.")
    escrow = lookups.escrow_for_project(draw["project_id"])
    if escrow is None or escrow["available_cents"] < draw["gross_amount_cents"]:
        raise errors.ApiError(errors.ERR_INSUFFICIENT_ESCROW, 409,
                              "Escrow available_cents is insufficient for the draw gross amount.")
    draw["status"] = "APPROVED"
    common.touch(draw)
    milestone = lookups.get_milestone(draw["milestone_id"])
    milestone["status"] = "APPROVED"
    common.touch(milestone)
    # move retainage from available to retained
    escrow["available_cents"] -= draw["retainage_cents"]
    escrow["retained_cents"] += draw["retainage_cents"]
    common.touch(escrow)
    return response.success(common.public(draw), 200)


@bp.route("/draws/<rid>/reject", methods=["POST"])
def reject_draw(rid):
    user_id, role = require_roles("Homeowner")
    draw = lookups.get_draw(rid)
    project = lookups.get_project(draw["project_id"])
    _project_owner_check(project, user_id, role)
    if draw["status"] != "REQUESTED":
        raise errors.invalid_state("Only a REQUESTED draw can be rejected.")
    draw["status"] = "REJECTED"
    common.touch(draw)
    milestone = lookups.get_milestone(draw["milestone_id"])
    milestone["status"] = "PENDING"
    common.touch(milestone)
    # void the conditional waiver
    if draw["lien_waiver_id"]:
        waiver = db.lien_waivers.get(draw["lien_waiver_id"])
        if waiver is not None:
            waiver["status"] = "VOIDED"
            common.touch(waiver)
    return response.success(common.public(draw), 200)


@bp.route("/draws/<rid>/pay", methods=["POST"])
def pay_draw(rid):
    require_roles("EscrowAgent")
    draw = lookups.get_draw(rid)
    if draw["status"] != "APPROVED":
        raise errors.invalid_state("Only an APPROVED draw can be paid.")
    # unconditional waiver requirement (priority 11)
    has_uncond = any(
        w["draw_id"] == draw["id"]
        and w["waiver_type"] == "UNCONDITIONAL"
        and w["status"] == "COLLECTED"
        and w["amount_cents"] == draw["net_release_cents"]
        for w in db.lien_waivers.values())
    if not has_uncond:
        raise errors.ApiError(errors.ERR_LIEN_WAIVER_REQUIRED, 422,
                              "An UNCONDITIONAL lien waiver matching net_release_cents is required to pay.")
    draw["status"] = "PAID"
    common.touch(draw)
    milestone = lookups.get_milestone(draw["milestone_id"])
    milestone["status"] = "PAID"
    common.touch(milestone)
    escrow = lookups.escrow_for_project(draw["project_id"])
    # move net_release from available to released
    escrow["available_cents"] -= draw["net_release_cents"]
    escrow["released_cents"] += draw["net_release_cents"]
    # final-sequence milestone: release accumulated retainage
    all_ms = lookups.milestones_for_project(draw["project_id"])
    max_seq = max(m["sequence"] for m in all_ms)
    if milestone["sequence"] == max_seq:
        escrow["released_cents"] += escrow["retained_cents"]
        escrow["retained_cents"] = 0
    common.touch(escrow)
    return response.success(common.public(draw), 200)
