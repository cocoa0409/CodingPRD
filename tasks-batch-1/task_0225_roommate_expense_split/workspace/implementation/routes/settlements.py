"""Settlement endpoints and lifecycle: propose, confirm (OCC), repropose, cancel (PRD §3.7)."""
from flask import Blueprint, request

import models
import response
import validate
from db import db
from errors import err
from middleware import authenticate, require_roles, parse_pagination, paginate
from services import household as hh

bp = Blueprint("settlements", __name__)

ALL_ROLES = {"Roommate", "DisputeMediator", "PlatformOperator"}


@bp.route("/settlements", methods=["POST"])
def create_settlement():
    with db.lock:
        p = authenticate()
        require_roles(p, {"Roommate"})
        body = validate.get_json_body()
        household_id = validate.require_str(body, "household_id")
        from_id = validate.require_str(body, "from_profile_id")
        to_id = validate.require_str(body, "to_profile_id")
        amount = validate.require_int(body, "amount_cents", minimum=1)
        # existence left-to-right
        household = db.households.get(household_id)
        if not household:
            raise err("ERR_NOT_FOUND", "household_id does not exist.")
        if from_id not in db.roommate_profiles:
            raise err("ERR_NOT_FOUND", "from_profile_id does not exist.")
        if to_id not in db.roommate_profiles:
            raise err("ERR_NOT_FOUND", "to_profile_id does not exist.")
        # priority 8: both must be ACTIVE members
        if not hh.is_active_member(household_id, from_id):
            raise err("ERR_NOT_HOUSEHOLD_MEMBER", "from_profile_id is not an active member.")
        if not hh.is_active_member(household_id, to_id):
            raise err("ERR_NOT_HOUSEHOLD_MEMBER", "to_profile_id is not an active member.")
        # priority 9: self-settlement forbidden
        if from_id == to_id:
            raise err("ERR_SELF_SETTLEMENT", "from_profile_id and to_profile_id must differ.")
        st = {
            "household_id": household_id,
            "from_profile_id": from_id,
            "to_profile_id": to_id,
            "amount_cents": amount,
            "status": "PROPOSED",
        }
        models.stamp_create(st)
        db.settlements[st["id"]] = st
        return response.ok(models.serialize(st), 201)


@bp.route("/settlements", methods=["GET"])
def list_settlements():
    with db.lock:
        p = authenticate()
        require_roles(p, ALL_ROLES)
        limit, offset = parse_pagination()
        items = list(db.settlements.values())
        household_id = request.args.get("household_id")
        from_id = request.args.get("from_profile_id")
        to_id = request.args.get("to_profile_id")
        if household_id is not None:
            items = [x for x in items if x["household_id"] == household_id]
        if from_id is not None:
            items = [x for x in items if x["from_profile_id"] == from_id]
        if to_id is not None:
            items = [x for x in items if x["to_profile_id"] == to_id]
        items = models.sort_by_created(items)
        page, meta = paginate(items, limit, offset)
        return response.ok_list(models.serialize_list(page), pagination=meta)


@bp.route("/settlements/<sid>", methods=["GET"])
def get_settlement(sid):
    with db.lock:
        p = authenticate()
        require_roles(p, ALL_ROLES)
        st = db.settlements.get(sid)
        if not st:
            raise err("ERR_NOT_FOUND", "Settlement not found.")
        return response.ok(models.serialize(st))


@bp.route("/settlements/<sid>/confirm", methods=["POST"])
def confirm_settlement(sid):
    with db.lock:
        p = authenticate()
        require_roles(p, {"Roommate"})
        st = db.settlements.get(sid)
        if not st:
            raise err("ERR_NOT_FOUND", "Settlement not found.")
        household = db.households.get(st["household_id"])
        # ownership: acting roommate is the creditor (to_profile_id)
        if p.user_id != st["to_profile_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Only the creditor may confirm.")
        # state: must be PROPOSED
        if st["status"] != "PROPOSED":
            raise err("ERR_INVALID_STATE", "Settlement is not PROPOSED.")
        # frozen gate (priority 7)
        if household["status"] == "FROZEN":
            raise err("ERR_HOUSEHOLD_FROZEN", "Household is frozen.")
        # debtor membership must be ACTIVE or MOVED_OUT
        debtor_mem = hh.membership_for_profile(household["id"], st["from_profile_id"])
        if debtor_mem is None or debtor_mem["status"] not in ("ACTIVE", "MOVED_OUT"):
            raise err("ERR_INVALID_STATE", "Debtor membership is not ACTIVE or MOVED_OUT.")
        # OCC (priority 21): expected_household_version must match
        body = validate.get_json_body()
        expected = validate.require_int(body, "expected_household_version")
        if expected != household["version"]:
            raise err("ERR_STALE_HOUSEHOLD_VERSION", "Stale household version.")
        # fiscal: debtor must have outstanding debt
        debtor_net = hh.net_balance_of(st["from_profile_id"])
        if debtor_net >= 0:
            raise err("ERR_NO_OUTSTANDING_DEBT", "Debtor has no outstanding debt.")
        outstanding = -debtor_net
        if st["amount_cents"] > outstanding:
            raise err("ERR_SETTLEMENT_EXCEEDS_DEBT", "Amount exceeds outstanding debt.")

        # ---- transition + ledger effect ----
        st["status"] = "CONFIRMED"
        models.touch(st)
        # net balances recomputed from CONFIRMED settlements (debtor debt reduced, creditor credit reduced)
        hh.recompute_net_balances(household)
        household["version"] = household["version"] + 1
        household["updated_at"] = db.now()
        # cancel any SCHEDULED reminder for this settlement
        for r in db.payment_reminders.values():
            if r.get("settlement_id") == sid and r["status"] == "SCHEDULED":
                r["status"] = "CANCELLED"
                models.touch(r)
        return response.ok(models.serialize(st))


@bp.route("/settlements/<sid>/repropose", methods=["POST"])
def repropose_settlement(sid):
    with db.lock:
        p = authenticate()
        require_roles(p, {"Roommate"})
        st = db.settlements.get(sid)
        if not st:
            raise err("ERR_NOT_FOUND", "Settlement not found.")
        # ownership: creditor (to_profile_id)
        if p.user_id != st["to_profile_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Only the creditor may re-propose.")
        if st["status"] != "DISPUTED":
            raise err("ERR_INVALID_STATE", "Settlement is not DISPUTED.")
        # linked dispute must be RESOLVED or REJECTED
        linked = None
        for d in db.disputes.values():
            if d.get("settlement_id") == sid:
                linked = d
        if linked is None or linked["status"] not in ("RESOLVED", "REJECTED"):
            raise err("ERR_INVALID_STATE", "Linked dispute is not closed.")
        if linked["status"] == "RESOLVED" and linked.get("adjusted_amount_cents") is not None:
            st["amount_cents"] = linked["adjusted_amount_cents"]
        st["status"] = "PROPOSED"
        models.touch(st)
        return response.ok(models.serialize(st))


@bp.route("/settlements/<sid>/cancel", methods=["POST"])
def cancel_settlement(sid):
    with db.lock:
        p = authenticate()
        require_roles(p, {"Roommate"})
        st = db.settlements.get(sid)
        if not st:
            raise err("ERR_NOT_FOUND", "Settlement not found.")
        # ownership: debtor or creditor
        if p.user_id not in (st["from_profile_id"], st["to_profile_id"]):
            raise err("ERR_NOT_RESOURCE_OWNER", "Only a party may cancel.")
        if st["status"] != "PROPOSED":
            raise err("ERR_INVALID_STATE", "Settlement is not PROPOSED.")
        st["status"] = "CANCELLED"
        models.touch(st)
        return response.ok(models.serialize(st))
