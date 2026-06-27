"""CheckItem routes: get, list-for-transaction, release, reject (PRD §3.5, §3.7).

Release and reject are StoreManager-only and both enforce segregation of duties
against the parent transaction's creating Teller. Validation order follows the
PRD §2.11 priority chain restricted to the rules that apply to each endpoint
(per SCAFFOLD §1.4 applies_to)."""
from flask import Blueprint

import errors
from auth import require_auth, BOTH, MANAGER_ONLY
from db import db, touch, serialize
from response import ok, listed
from helpers import parse_pagination, paginate, sort_by_creation
import lookups
from services import calculations as calc
from services import domain
from services import posting

bp = Blueprint("check_items", __name__)


@bp.route("/check-items/<cid>", methods=["GET"])
def get_check_item(cid):
    require_auth(BOTH)
    check_item = lookups.get_check_item(cid)
    return ok(serialize(check_item))


@bp.route("/transactions/<tid>/check-items", methods=["GET"])
def list_transaction_check_items(tid):
    require_auth(BOTH)
    lookups.get_transaction(tid)
    limit, offset = parse_pagination()
    items = [c for c in db.check_items.values() if c["transaction_id"] == tid]
    items = sort_by_creation(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return listed([serialize(c) for c in page], limit, offset, total)


@bp.route("/check-items/<cid>/release", methods=["POST"])
def release_check_item(cid):
    caller = require_auth(MANAGER_ONLY)
    check_item = lookups.get_check_item(cid)
    txn = lookups.get_transaction(check_item["transaction_id"])

    # priority 4: must be RISK_HELD
    if check_item["verification_state"] != "RISK_HELD":
        raise errors.err(errors.ERR_INVALID_STATE, "CheckItem is not RISK_HELD")

    # priority 5: segregation of duties
    if caller.user_id == txn["_creating_teller_id"]:
        raise errors.err(
            errors.ERR_SEGREGATION_OF_DUTIES,
            "Releasing manager must differ from the creating Teller",
        )

    customer = lookups.get_customer(txn["customer_id"])

    # priority 6: KYC gate
    if customer["kyc_status"] != "VERIFIED":
        raise errors.err(errors.ERR_KYC_NOT_VERIFIED, "Customer KYC is not VERIFIED")

    # priority 7: OFAC block
    if customer["kyc_status"] == "OFAC_BLOCKED":
        raise errors.err(errors.ERR_OFAC_BLOCKED, "Customer is OFAC blocked")

    # priority 9: drawer must be OPEN
    drawer = lookups.get_drawer(txn["drawer_id"])
    if drawer["status"] != "OPEN":
        raise errors.err(errors.ERR_DRAWER_NOT_OPEN, "Drawer is not OPEN")

    # transition CheckItem -> CLEARED
    check_item["verification_state"] = "CLEARED"
    touch(check_item)

    # parent transaction -> POSTED/SETTLED (fee already computed at creation),
    # customer velocity bumped, drawer recomputed.
    posting.post_transaction(txn, customer, drawer, compute=False)

    # confirmed hold-derived risk delta (PRD §3.7, §3.8)
    delta = calc.hold_derived_delta(check_item["maker_account_risk"], check_item["hold_reason"])
    domain.apply_risk_delta(customer, delta)

    return ok(serialize(check_item))


@bp.route("/check-items/<cid>/reject", methods=["POST"])
def reject_check_item(cid):
    caller = require_auth(MANAGER_ONLY)
    check_item = lookups.get_check_item(cid)
    txn = lookups.get_transaction(check_item["transaction_id"])

    # priority 4: must be RISK_HELD
    if check_item["verification_state"] != "RISK_HELD":
        raise errors.err(errors.ERR_INVALID_STATE, "CheckItem is not RISK_HELD")

    # priority 5: segregation of duties
    if caller.user_id == txn["_creating_teller_id"]:
        raise errors.err(
            errors.ERR_SEGREGATION_OF_DUTIES,
            "Rejecting manager must differ from the creating Teller",
        )

    # transition CheckItem -> REJECTED; parent transaction -> VOIDED (settlement
    # stays UNSETTLED). No cash moves, drawer untouched.
    check_item["verification_state"] = "REJECTED"
    touch(check_item)
    txn["lifecycle_state"] = "VOIDED"
    touch(txn)

    # confirmed hold-derived risk delta (PRD §3.7, §3.8)
    customer = lookups.get_customer(txn["customer_id"])
    delta = calc.hold_derived_delta(check_item["maker_account_risk"], check_item["hold_reason"])
    domain.apply_risk_delta(customer, delta)

    return ok(serialize(check_item))
