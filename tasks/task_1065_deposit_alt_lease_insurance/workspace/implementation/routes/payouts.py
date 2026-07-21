from flask import Blueprint
from db import db, touch, fmt_ts, now
from errors import err
from middleware import get_caller, require_role
from response import object_response
from validate import body, require_enum, require_str
import lookups
from services.recompute import recompute_policy_net, recompute_property_total_paid_claims

payouts_bp = Blueprint("payouts", __name__)


@payouts_bp.post("/payouts/<payout_id>/transition")
def payout_transition(payout_id):
    caller = get_caller()
    require_role(caller, {"ClaimsAdjuster", "PlatformAdmin"})
    b = body()
    action = require_enum(b, "action", {"DISBURSE", "REVERSE"})
    reversal_reason = require_str(b, "reversal_reason", required=False, default=None)

    if action == "DISBURSE" and caller.role != "ClaimsAdjuster":
        raise err("ERR_UNAUTHORIZED", "Only ClaimsAdjuster may disburse a payout.")
    if action == "REVERSE" and caller.role != "PlatformAdmin":
        raise err("ERR_UNAUTHORIZED", "Only PlatformAdmin may reverse a payout.")

    payout = lookups.get_payout(payout_id)
    claim = lookups.claim_for_payout(payout)
    policy = db.policies[claim["policy_id"]]
    prop = lookups.property_for_policy(policy)

    if action == "DISBURSE":
        if payout["status"] != "PENDING":
            raise err("ERR_INVALID_STATE", "Payout is not PENDING.")
        if caller.user_id == claim["reviewing_adjuster_id"]:
            raise err("ERR_SOD_VIOLATION", "Disbursing adjuster must differ from the reviewing adjuster.")

        payout["status"] = "DISBURSED"
        payout["disbursing_adjuster_id"] = caller.user_id
        payout["disbursed_at"] = fmt_ts(now())
        touch(payout)

        recompute_policy_net(policy)
        touch(policy)

        recompute_property_total_paid_claims(prop)
        touch(prop)

        if claim["status"] == "APPROVED":
            claim["status"] = "CLOSED"
            touch(claim)
    else:
        if payout["status"] != "DISBURSED":
            raise err("ERR_INVALID_STATE", "Payout is not DISBURSED.")

        payout["status"] = "REVERSED"
        payout["reversed_at"] = fmt_ts(now())
        payout["reversal_reason"] = reversal_reason
        touch(payout)

        recompute_policy_net(policy)
        touch(policy)

        recompute_property_total_paid_claims(prop)
        touch(prop)

    return object_response(payout)
