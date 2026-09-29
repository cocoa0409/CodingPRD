"""Slot exchanges and transfers: a fork-join negotiation with two independent gates."""
from flask import Blueprint

import cascades
import db
import derive
import reqval as rv
from db import mark, store
from errors import ApiError
from middleware import acting_user, authenticate, require_ownership
from response import ok, written
from routes.common import READ_ROLES, decision_of, list_response, read_one, require_season_open
from routes.slots import _new_holding
from util import dt_of, fmt_dt

bp = Blueprint("slot_transactions", __name__)

PLANNER = ("NetworkPlanner",)
OPEN_STATUSES = ("PROPOSED", "COUNTERPARTY_ACCEPTED")


def _involved(transaction):
    """Every holding the negotiation encumbers, in a stable order."""
    ids = [transaction["offered_slot_holding_id"]]
    if transaction["counter_slot_holding_id"]:
        ids.append(transaction["counter_slot_holding_id"])
    return ids


def _versions_backed_by(holding_ids):
    """Schedule versions with a leg currently backed by one of these series."""
    versions = []
    for leg in store.values("flight_legs"):
        if leg["status"] not in ("SLOT_BACKED", "FILED"):
            continue
        if leg["departure_slot_holding_id"] in holding_ids or (
            leg["arrival_slot_holding_id"] in holding_ids
        ):
            version = store.get("schedule_versions", leg["schedule_version_id"])
            if version is not None and version not in versions:
                versions.append(version)
    return versions


def _flag_resync(versions):
    """The distribution systems now hold a plan the airline has no slots for."""
    for version in versions:
        for submission in derive.submissions_of_version(version["id"]):
            if submission["status"] == "ACKNOWLEDGED" and not submission["resync_required"]:
                submission["resync_required"] = True
                mark(submission)


def _historic_protected(transaction, offered):
    return transaction["kind"] == "TRANSFER" and offered["historic_precedence"]


@bp.post("/slot-transactions")
def propose_transaction():
    authenticate(PLANNER)
    payload = rv.body()
    kind = rv.req_enum(payload, "kind", "transaction_kind")
    counterparty_id = rv.req_str(payload, "counterparty_carrier_id", 1)
    offered_id = rv.req_str(payload, "offered_slot_holding_id", 1)
    deadline = rv.req_dt(payload, "response_deadline_utc")
    expected = rv.req_int(payload, "expected_slot_holding_version", 0)
    counter_id = rv.opt_str(payload, "counter_slot_holding_id", 1)

    store.require("carriers", counterparty_id)
    offered = store.require("slot_holdings", offered_id)
    counter = store.require("slot_holdings", counter_id) if counter_id else None
    season = store.get("seasons", offered["season_id"])
    if season is not None and dt_of(deadline) > dt_of(season["slot_return_deadline_utc"]):
        rv.bad("response_deadline_utc may not fall after the season's slot_return_deadline_utc.")

    initiating_id = offered["carrier_id"]
    require_ownership(initiating_id)
    if expected != offered["version"]:
        raise ApiError("ERR_STALE_SLOT_HOLDING")
    require_season_open(season)
    if offered["holding_status"] != "HELD":
        raise ApiError("ERR_SLOT_HOLDING_STATE_INVALID")
    if offered["pending_transaction_id"] is not None:
        raise ApiError("ERR_SLOT_ENCUMBERED")
    if counterparty_id == initiating_id:
        raise ApiError("ERR_SELF_TRANSACTION_NOT_ALLOWED")
    if kind == "EXCHANGE":
        if counter is None or counter["carrier_id"] != counterparty_id:
            raise ApiError("ERR_COUNTER_SLOT_REQUIRED")
    elif counter is not None:
        raise ApiError("ERR_COUNTER_SLOT_REQUIRED")
    if kind == "TRANSFER" and offered["historic_precedence"]:
        raise ApiError("ERR_HISTORIC_PRECEDENCE_PROTECTED")

    row = store.insert("slot_transactions", {
        "kind": kind,
        "initiating_carrier_id": initiating_id,
        "counterparty_carrier_id": counterparty_id,
        "offered_slot_holding_id": offered_id,
        "counter_slot_holding_id": counter_id,
        "successor_slot_holding_id": None,
        "response_deadline_utc": deadline,
        "status": "PROPOSED",
        "proposed_by_user_id": acting_user(),
        "responded_by_user_id": None,
        "approved_by_user_id": None,
        "executed_at_utc": None,
        "decision_reason": None,
    })
    for holding_id in _involved(row):
        holding = store.get("slot_holdings", holding_id)
        holding["pending_transaction_id"] = row["id"]
        mark(holding)
    return written(row, 201)


@bp.get("/slot-transactions/<slot_transaction_id>")
def get_transaction(slot_transaction_id):
    return ok(read_one("slot_transactions", slot_transaction_id))


@bp.get("/slot-transactions")
def list_transactions():
    authenticate(READ_ROLES)
    return list_response("slot_transactions", [
        ("initiating_carrier_id", rv.q_str("initiating_carrier_id")),
        ("counterparty_carrier_id", rv.q_str("counterparty_carrier_id")),
        ("offered_slot_holding_id", rv.q_str("offered_slot_holding_id")),
        ("counter_slot_holding_id", rv.q_str("counter_slot_holding_id")),
        ("successor_slot_holding_id", rv.q_str("successor_slot_holding_id")),
        ("kind", rv.q_enum("kind", "transaction_kind")),
        ("status", rv.q_enum("status", "transaction_status")),
    ])


@bp.post("/slot-transactions/<slot_transaction_id>/respond")
def respond_transaction(slot_transaction_id):
    authenticate(("PartnerCarrier",))
    transaction = store.require("slot_transactions", slot_transaction_id)
    payload = rv.body()
    decision = decision_of(payload, "decision", ("ACCEPT", "REJECT"))
    reason = rv.opt_str(payload, "rejection_reason", 1, 500)
    if decision == "REJECT" and reason is None:
        rv.bad("Field 'rejection_reason' is required when rejecting a proposal.")
    require_ownership(transaction["counterparty_carrier_id"])
    if transaction["status"] != "PROPOSED":
        raise ApiError("ERR_SLOT_TRANSACTION_STATE_INVALID")
    if db.now() > dt_of(transaction["response_deadline_utc"]):
        raise ApiError("ERR_SLOT_TRANSACTION_DEADLINE_PASSED")

    transaction["responded_by_user_id"] = acting_user()
    if decision == "ACCEPT":
        transaction["status"] = "COUNTERPARTY_ACCEPTED"
    else:
        transaction["status"] = "COUNTERPARTY_REJECTED"
        transaction["decision_reason"] = reason
        cascades.release_encumbrance(_involved(transaction))
    mark(transaction)
    return written(transaction)


@bp.post("/slot-transactions/<slot_transaction_id>/withdraw")
def withdraw_transaction(slot_transaction_id):
    authenticate(PLANNER)
    transaction = store.require("slot_transactions", slot_transaction_id)
    payload = rv.body()
    reason = rv.req_str(payload, "reason", 1, 500)
    require_ownership(transaction["initiating_carrier_id"])
    if transaction["status"] not in OPEN_STATUSES:
        raise ApiError("ERR_SLOT_TRANSACTION_STATE_INVALID")
    transaction["status"] = "WITHDRAWN"
    transaction["decision_reason"] = reason
    mark(transaction)
    cascades.release_encumbrance(_involved(transaction))
    return written(transaction)


def _execute_transfer(transaction, offered):
    """The transferor keeps the row and loses the claim; a successor is minted."""
    offered["holding_status"] = "TRANSFERRED_OUT"
    offered["retains_historic_precedence"] = False
    mark(offered)
    successor = _new_holding(
        offered["station_id"],
        offered["season_id"],
        transaction["counterparty_carrier_id"],
        offered["movement_type"],
        offered["slot_time_utc"],
        offered["days_of_week"],
        offered["series_weeks"],
        offered["historic_precedence"],
        offered["id"],
    )
    transaction["successor_slot_holding_id"] = successor["id"]
    return [offered]


def _execute_exchange(transaction, offered, counter):
    """Two rows swap holders in place; each keeps its own time and day mask."""
    offered["carrier_id"], counter["carrier_id"] = counter["carrier_id"], offered["carrier_id"]
    mark(offered)
    mark(counter)
    return [offered, counter]


@bp.post("/slot-transactions/<slot_transaction_id>/approve")
def approve_transaction(slot_transaction_id):
    authenticate(("SlotCoordinator",))
    transaction = store.require("slot_transactions", slot_transaction_id)
    payload = rv.body()
    decision = decision_of(payload, "decision", ("APPROVE", "DENY"))
    reason = rv.opt_str(payload, "denial_reason", 1, 500)
    if decision == "DENY" and reason is None:
        rv.bad("Field 'denial_reason' is required when denying a proposal.")

    offered = store.require("slot_holdings", transaction["offered_slot_holding_id"])
    counter = store.get("slot_holdings", transaction["counter_slot_holding_id"])
    require_season_open(store.get("seasons", offered["season_id"]))
    if transaction["status"] != "COUNTERPARTY_ACCEPTED":
        raise ApiError("ERR_SLOT_TRANSACTION_STATE_INVALID")
    if acting_user() == transaction["proposed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if _historic_protected(transaction, offered):
        raise ApiError("ERR_HISTORIC_PRECEDENCE_PROTECTED")

    transaction["approved_by_user_id"] = acting_user()
    if decision == "DENY":
        transaction["status"] = "COORDINATOR_DENIED"
        transaction["decision_reason"] = reason
        mark(transaction)
        cascades.release_encumbrance(_involved(transaction))
        return written(transaction)

    transaction["status"] = "EXECUTED"
    transaction["executed_at_utc"] = fmt_dt(db.now())
    if transaction["kind"] == "TRANSFER":
        moved = _execute_transfer(transaction, offered)
    else:
        moved = _execute_exchange(transaction, offered, counter)
    mark(transaction)

    moved_ids = [holding["id"] for holding in moved]
    affected_versions = _versions_backed_by(moved_ids)
    for holding in moved:
        cascades.detach_holding_from_legs(holding)
    _flag_resync(affected_versions)
    cascades.release_encumbrance(_involved(transaction))
    return written(transaction)
