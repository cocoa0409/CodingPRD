"""Dispute endpoints and the arbitration resolution cascade (PRD 3.7)."""
from flask import Blueprint

import db
from errors import err
from middleware import require_auth, require_role
from response import success
from services import common, derive, escrow

bp = Blueprint("disputes", __name__)


@bp.get("/disputes/<did>")
def get_dispute(did):
    _, role = require_auth()
    require_role(role, ["PlatformAdmin", "Client", "Freelancer", "Arbitrator"])
    d = common.get_dispute(did)
    return success(derive.dispute_view(d))


@bp.post("/disputes/<did>/assign-arbitration")
def assign_arbitration(did):
    _, role = require_auth()
    require_role(role, ["Arbitrator"])
    d = common.get_dispute(did)
    if d["status"] != "OPEN":
        raise err("ERR_INVALID_DISPUTE_STATE", "Dispute must be OPEN to assign arbitration")
    d["status"] = "UNDER_ARBITRATION"
    db.touch(d)
    return success(derive.dispute_view(d))


@bp.post("/disputes/<did>/resolve")
def resolve(did):
    _, role = require_auth()
    require_role(role, ["Arbitrator"])
    d = common.get_dispute(did)
    body = common.get_body()
    award = common.require_int(body, "arbitrator_award_cents")
    contract = db.contracts[d["contract_id"]]
    milestone = db.milestones[d["milestone_id"]]
    if d["status"] != "UNDER_ARBITRATION":
        raise err("ERR_INVALID_DISPUTE_STATE", "Dispute must be UNDER_ARBITRATION to resolve")
    funded = derive.milestone_funded_cents(milestone["id"])
    if award < 0 or award > funded:
        raise err("ERR_AWARD_OUT_OF_RANGE", "award outside [0, funded_cents]")

    # resolution classification (PRD 3.7)
    if award == funded:
        resolution = "FREELANCER_FAVOR"
    elif award == 0:
        resolution = "CLIENT_FAVOR"
    else:
        resolution = "SPLIT"
    d["arbitrator_award_cents"] = award
    d["resolution"] = resolution
    d["status"] = "RESOLVED"
    db.touch(d)

    freelancer = db.freelancers[contract["freelancer_id"]]
    if award > 0:
        # milestone -> RELEASED; release award, refund remainder; create payout
        escrow.release_award(contract, milestone, award)
        if resolution == "SPLIT":
            # loss outcome: reputation recomputed (dispute_loss derived)
            derive.recompute_freelancer_reputation(freelancer)
    else:
        # CLIENT_FAVOR: full refund, milestone -> REFUNDED, loss recorded
        milestone["status"] = "REFUNDED"
        db.touch(milestone)
        escrow.refund_full(contract, milestone)
        derive.recompute_freelancer_reputation(freelancer)
    return success(derive.dispute_view(d))


@bp.post("/disputes/<did>/withdraw")
def withdraw(did):
    user_id, role = require_auth()
    require_role(role, ["Client", "Freelancer"])
    d = common.get_dispute(did)
    body = common.get_body()
    actor_role = common.require_enum(body, "actor_role", {"CLIENT", "FREELANCER"})
    contract = db.contracts[d["contract_id"]]
    # ownership of the acting side
    if role == "Client":
        common.check_client_owns(role, user_id, contract["client_id"])
    else:
        common.check_freelancer_owns(role, user_id, contract["freelancer_id"])
    if d["status"] != "OPEN":
        raise err("ERR_INVALID_DISPUTE_STATE", "Dispute must be OPEN to withdraw")
    # acting party must equal raised_by
    if actor_role != d["raised_by"]:
        raise err("ERR_FORBIDDEN_ROLE", "Only the raiser may withdraw the dispute")
    d["status"] = "WITHDRAWN"
    db.touch(d)
    milestone = db.milestones[d["milestone_id"]]
    milestone["status"] = "SUBMITTED"
    db.touch(milestone)
    return success(derive.dispute_view(d))
