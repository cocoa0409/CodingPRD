"""Point disputes, manual adjustment authority and separation of duties."""
from flask import Blueprint

import clock
import db
import middleware
import response
import shape
from errors import ApiError, bad_request
from routes._helpers import invalid_state, listing
from services import core, serializers

bp = Blueprint("disputes", __name__)

REASON_CODES = ("MISSING_ACCRUAL", "WRONG_MULTIPLIER", "UNAUTHORIZED_REDEMPTION", "EXPIRY_ERROR")
AUTHORITY_TIERS = ("TIER1", "TIER2", "TIER3")
DISPUTE_STATUSES = ("FILED", "INVESTIGATING", "ADJUSTMENT_PROPOSED",
                    "RESOLVED_UPHELD", "RESOLVED_DENIED")
TIER_CEILINGS = {"TIER1": 500, "TIER2": 5000, "TIER3": None}
MAX_SUPERSEDE_CHAIN = 3


@bp.route("/point-disputes", methods=["POST"])
def create_point_dispute():
    ctx = middleware.require(("Member", "LoyaltyAnalyst", "ProgramAdmin"))
    payload = shape.body()
    member_id = shape.req_str(payload, "member_id")
    disputed_ledger_entry_id = shape.req_str(payload, "disputed_ledger_entry_id")
    claimed_points = shape.req_int(payload, "claimed_points", 1, 1000000)
    reason_code = shape.req_enum(payload, "reason_code", REASON_CODES)
    supersedes_dispute_id = shape.opt_str(payload, "supersedes_dispute_id")

    member = core.fetch("members", member_id)
    entry = core.fetch("ledger_entries", disputed_ledger_entry_id)
    superseded = None
    if supersedes_dispute_id is not None:
        superseded = core.fetch("point_disputes", supersedes_dispute_id)

    middleware.own_member(ctx, member["id"])

    core.assert_no_frozen_household(member["id"])

    if entry["member_id"] != member["id"]:
        raise ApiError("ERR_DISPUTE_ENTRY_MEMBER_MISMATCH",
                       "ledger entry %s does not belong to member %s"
                       % (entry["id"], member["id"]))

    if superseded is not None:
        if superseded["status"] != "RESOLVED_DENIED":
            raise ApiError("ERR_SUPERSEDE_CHAIN_TOO_LONG",
                           "only a RESOLVED_DENIED dispute may be superseded")
        if core.dispute_chain_length(superseded) + 1 > MAX_SUPERSEDE_CHAIN:
            raise ApiError("ERR_SUPERSEDE_CHAIN_TOO_LONG",
                           "a supersede chain may hold at most %d disputes" % MAX_SUPERSEDE_CHAIN)

    dispute = core.new_entity()
    dispute.update({
        "member_id": member["id"],
        "disputed_ledger_entry_id": entry["id"],
        "supersedes_dispute_id": superseded["id"] if superseded is not None else None,
        "applied_ledger_entry_id": None,
        "claimed_points": claimed_points,
        "reason_code": reason_code,
        "status": "FILED",
        "proposed_points_delta": None,
        "authority_tier": None,
        "proposed_by_user_id": None,
        "approved_by_user_id": None,
        "resolved_at": None,
    })
    db.point_disputes[dispute["id"]] = dispute
    return response.object_response(serializers.point_dispute(dispute), 201)


@bp.route("/point-disputes/<dispute_id>", methods=["GET"])
def get_point_dispute(dispute_id):
    middleware.require(("ProgramAdmin", "LoyaltyAnalyst", "LoyaltySupervisor", "Member"))
    dispute = core.fetch("point_disputes", dispute_id)
    return response.object_response(serializers.point_dispute(dispute))


@bp.route("/point-disputes", methods=["GET"])
def list_point_disputes():
    middleware.require(("ProgramAdmin", "LoyaltyAnalyst", "LoyaltySupervisor", "Member"))
    shape.pagination()
    member_id = shape.arg_str("member_id")
    disputed_ledger_entry_id = shape.arg_str("disputed_ledger_entry_id")
    supersedes_dispute_id = shape.arg_str("supersedes_dispute_id")
    applied_ledger_entry_id = shape.arg_str("applied_ledger_entry_id")
    status = shape.arg_enum("status", DISPUTE_STATUSES)
    rows = list(db.point_disputes.values())
    if member_id is not None:
        rows = [d for d in rows if d["member_id"] == member_id]
    if disputed_ledger_entry_id is not None:
        rows = [d for d in rows if d["disputed_ledger_entry_id"] == disputed_ledger_entry_id]
    if supersedes_dispute_id is not None:
        rows = [d for d in rows if d["supersedes_dispute_id"] == supersedes_dispute_id]
    if applied_ledger_entry_id is not None:
        rows = [d for d in rows if d["applied_ledger_entry_id"] == applied_ledger_entry_id]
    if status is not None:
        rows = [d for d in rows if d["status"] == status]
    return listing(rows, serializers.point_dispute, order=core.order_key)


@bp.route("/point-disputes/<dispute_id>/investigate", methods=["POST"])
def investigate_point_dispute(dispute_id):
    middleware.require(("LoyaltyAnalyst", "ProgramAdmin"))
    dispute = core.fetch("point_disputes", dispute_id)
    if dispute["status"] != "FILED":
        raise invalid_state("only a FILED dispute may be taken into investigation (current %s)"
                            % dispute["status"])
    dispute["status"] = "INVESTIGATING"
    core.bump(dispute)
    return response.object_response(serializers.point_dispute(dispute))


@bp.route("/point-disputes/<dispute_id>/propose-adjustment", methods=["POST"])
def propose_point_adjustment(dispute_id):
    ctx = middleware.require(("LoyaltyAnalyst", "ProgramAdmin"))
    payload = shape.body()
    proposed_points_delta = shape.req_int(payload, "proposed_points_delta")
    if proposed_points_delta == 0:
        raise bad_request("'proposed_points_delta' must be non-zero")
    authority_tier = shape.req_enum(payload, "authority_tier", AUTHORITY_TIERS)

    dispute = core.fetch("point_disputes", dispute_id)

    ceiling = TIER_CEILINGS[authority_tier]
    if ceiling is not None and abs(proposed_points_delta) > ceiling:
        raise ApiError("ERR_ADJUSTMENT_EXCEEDS_AUTHORITY",
                       "a %s proposal may not exceed a magnitude of %d"
                       % (authority_tier, ceiling))

    if dispute["status"] != "INVESTIGATING":
        raise invalid_state("only an INVESTIGATING dispute may carry a proposal (current %s)"
                            % dispute["status"])

    dispute["proposed_points_delta"] = proposed_points_delta
    dispute["authority_tier"] = authority_tier
    dispute["proposed_by_user_id"] = ctx.user_id
    dispute["status"] = "ADJUSTMENT_PROPOSED"
    core.bump(dispute)
    return response.object_response(serializers.point_dispute(dispute))


@bp.route("/point-disputes/<dispute_id>/approve-adjustment", methods=["POST"])
def approve_point_adjustment(dispute_id):
    ctx = middleware.require(("LoyaltySupervisor", "ProgramAdmin"))
    dispute = core.fetch("point_disputes", dispute_id)

    if dispute["proposed_by_user_id"] is not None \
            and ctx.user_id == dispute["proposed_by_user_id"]:
        raise ApiError("ERR_SELF_APPROVAL_FORBIDDEN",
                       "the proposer of an adjustment may not approve it")

    if dispute["authority_tier"] == "TIER3" and ctx.role != "ProgramAdmin":
        raise ApiError("ERR_TIER_AUTHORITY_REQUIRED",
                       "a TIER3 adjustment requires a ProgramAdmin")

    if dispute["status"] != "ADJUSTMENT_PROPOSED":
        raise invalid_state("only an ADJUSTMENT_PROPOSED dispute may be approved (current %s)"
                            % dispute["status"])

    member = db.members[dispute["member_id"]]
    cycle = core.require_open_cycle(member["banner_id"])
    next_cycle = core.require_next_cycle(cycle)

    delta = dispute["proposed_points_delta"]
    entry = core.add_entry(member["id"], cycle["id"], "ADJUSTMENT", delta,
                           "POINT_DISPUTE", dispute["id"],
                           lot_expires_at=next_cycle["closes_at"] if delta > 0 else None)
    if entry is not None:
        core.bump(member)

    dispute["applied_ledger_entry_id"] = entry["id"] if entry is not None else None
    dispute["approved_by_user_id"] = ctx.user_id
    dispute["resolved_at"] = clock.now()
    dispute["status"] = "RESOLVED_UPHELD"
    core.bump(dispute)
    return response.object_response(serializers.point_dispute(dispute))


@bp.route("/point-disputes/<dispute_id>/deny", methods=["POST"])
def deny_point_dispute(dispute_id):
    middleware.require(("LoyaltySupervisor", "ProgramAdmin"))
    dispute = core.fetch("point_disputes", dispute_id)
    if dispute["status"] not in ("INVESTIGATING", "ADJUSTMENT_PROPOSED"):
        raise invalid_state("only an INVESTIGATING or ADJUSTMENT_PROPOSED dispute may be denied "
                            "(current %s)" % dispute["status"])
    dispute["status"] = "RESOLVED_DENIED"
    dispute["resolved_at"] = clock.now()
    core.bump(dispute)
    return response.object_response(serializers.point_dispute(dispute))
