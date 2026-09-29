"""Safe commissioning, the time-delay cycle and the safe ledger (PRD sections 2.6-2.9, 3.3)."""
from flask import Blueprint

import clock
import db
import domain
import response
import serializers
import validation
from auth import endpoint, user_id
from errors import err
from routes.common import list_collection

bp = Blueprint("safes", __name__)

SAFE_TYPES = ("MANUAL", "SMART")
READ_ROLES = ["CashOfficeClerk", "StoreManager", "TreasuryAnalyst", "LossPreventionInvestigator"]


@bp.post("/cash-ops/safes")
@endpoint(["TreasuryAnalyst"])
def create_safe():
    data = validation.body()
    store_id = validation.req_str(data, "store_id")
    safe_code = validation.req_str(data, "safe_code")
    safe_type = validation.req_enum(data, "safe_type", SAFE_TYPES)
    opening_balance_cents = validation.req_int(data, "opening_balance_cents", minimum=0)
    store = domain.get_store(store_id)
    for existing in db.safes.values():
        if existing["store_id"] == store["id"] and existing["safe_code"] == safe_code:
            raise err("ERR_INVALID_REQUEST", "safe_code %s already exists at this store" % safe_code)
    record = db.base_record()
    record.update(
        {
            "store_id": store["id"],
            "safe_code": safe_code,
            "safe_type": safe_type,
            "open_state": "LOCKED",
            "posture": "OPEN",
            "open_requested_at": None,
            "open_requested_by_user_id": None,
            "unlocked_at": None,
        }
    )
    db.safes[record["id"]] = record
    domain.write_txn(
        safe_id=record["id"],
        txn_type="OPENING_BALANCE",
        declared_amount_cents=opening_balance_cents,
        actor_user_id=user_id(),
        memo="opening balance for safe %s" % record["safe_code"],
    )
    return response.object_response(serializers.safe(record), 201)


@bp.post("/cash-ops/safes/<safe_id>/open-requests")
@endpoint(["CashOfficeClerk", "StoreManager"])
def arm_open_request(safe_id):
    data = validation.body()
    validation.opt_str(data, "reason")
    safe = domain.get_safe(safe_id)
    if safe["open_state"] != "LOCKED":
        raise err("ERR_SAFE_OPEN_REQUEST_ACTIVE", "the safe already has an open request or is unlocked")
    if safe["posture"] == "FROZEN":
        raise err("ERR_SAFE_FROZEN", "the safe is frozen by an investigation")
    safe["open_state"] = "OPEN_REQUESTED"
    safe["open_requested_at"] = clock.now()
    safe["open_requested_by_user_id"] = user_id()
    db.touch(safe)
    return response.object_response(serializers.safe(safe))


@bp.post("/cash-ops/safes/<safe_id>/open")
@endpoint(["CashOfficeClerk", "StoreManager"])
def open_safe(safe_id):
    safe = domain.get_safe(safe_id)
    if safe["open_state"] != "OPEN_REQUESTED":
        raise err("ERR_SAFE_NOT_UNLOCKED", "the safe has no pending open request")
    store = domain.store_of_safe(safe)
    if store["dual_control_required"] and user_id() == safe["open_requested_by_user_id"]:
        raise err(
            "ERR_DUAL_CONTROL_VIOLATION",
            "the operator who armed the request may not execute the open",
        )
    delay_end = clock.plus_minutes(safe["open_requested_at"], store["safe_time_delay_minutes"])
    window_end = clock.plus_minutes(delay_end, store["safe_open_window_minutes"])
    now = clock.now()
    if now < delay_end:
        raise err("ERR_TIME_DELAY_NOT_ELAPSED", "the time delay has not yet elapsed")
    if now >= window_end:
        # The single place where a rejected request still advances state.
        safe["open_state"] = "LOCKED"
        safe["open_requested_at"] = None
        safe["open_requested_by_user_id"] = None
        db.touch(safe)
        raise err("ERR_SAFE_OPEN_REQUEST_EXPIRED", "the open window has lapsed")
    safe["open_state"] = "UNLOCKED"
    safe["unlocked_at"] = now
    db.touch(safe)
    return response.object_response(serializers.safe(safe))


@bp.post("/cash-ops/safes/<safe_id>/restore-posture")
@endpoint(["LossPreventionInvestigator"])
def restore_posture(safe_id):
    data = validation.body()
    validation.opt_str(data, "investigation_note")
    safe = domain.get_safe(safe_id)
    if domain.store_has_escalated_case(safe["store_id"]):
        raise err(
            "ERR_VARIANCE_CASE_INVALID_STATE",
            "an escalated variance case still remains for this store",
        )
    domain.restore_store_safes(safe["store_id"])
    return response.object_response(serializers.safe(safe))


@bp.get("/cash-ops/safes/<safe_id>")
@endpoint(READ_ROLES)
def read_safe(safe_id):
    return response.object_response(serializers.safe(domain.get_safe(safe_id)))


@bp.get("/cash-ops/safes")
@endpoint(READ_ROLES)
def list_safes():
    return list_collection(
        db.safes, [("store_id", "store_id"), ("safe_type", "safe_type")], serializers.safe
    )


@bp.get("/cash-ops/safe-transactions/<txn_id>")
@endpoint(READ_ROLES)
def read_txn(txn_id):
    return response.object_response(serializers.safe_transaction(domain.get_txn(txn_id)))


@bp.get("/cash-ops/safe-transactions")
@endpoint(READ_ROLES)
def list_txns():
    return list_collection(
        db.safe_transactions,
        [
            ("safe_id", "safe_id"),
            ("till_session_id", "till_session_id"),
            ("deposit_id", "deposit_id"),
            ("change_order_id", "change_order_id"),
            ("txn_type", "txn_type"),
        ],
        serializers.safe_transaction,
    )
