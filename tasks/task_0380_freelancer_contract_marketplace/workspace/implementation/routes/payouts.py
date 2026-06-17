"""Payout endpoints and settlement (PRD 3.6)."""
from flask import Blueprint

import db
from errors import err
from middleware import require_auth, require_role
from response import success
from services import common, derive

bp = Blueprint("payouts", __name__)


@bp.get("/payouts/<pid>")
def get_payout(pid):
    user_id, role = require_auth()
    require_role(role, ["PlatformAdmin", "Freelancer", "Client"])
    p = common.get_payout(pid)
    common.check_freelancer_owns(role, user_id, p["freelancer_id"])
    if role == "Client":
        # a Client may read a payout on one of its own contracts' milestones
        milestone = db.milestones.get(p["milestone_id"])
        contract = db.contracts.get(milestone["contract_id"]) if milestone else None
        if contract and contract["client_id"] != user_id:
            raise err("ERR_FORBIDDEN_ROLE", "Client does not own this payout")
    return success(derive.payout_view(p))


@bp.post("/payouts/<pid>/settle")
def settle(pid):
    _, role = require_auth()
    require_role(role, ["PlatformAdmin"])
    p = common.get_payout(pid)
    if p["status"] not in ("PENDING", "HELD_NO_TAX_ID"):
        raise err("ERR_INVALID_PAYOUT_STATE", "Payout not in a settle-eligible state")
    freelancer = db.freelancers[p["freelancer_id"]]
    if freelancer["tax_id_on_file"]:
        p["status"] = "PAID"
        db.touch(p)
        freelancer["lifetime_earnings_cents"] += p["net_cents"]
        derive.recompute_freelancer_reputation(freelancer)
    else:
        # blocked for missing tax identity; no lifetime update
        p["status"] = "HELD_NO_TAX_ID"
        db.touch(p)
    return success(derive.payout_view(p))
