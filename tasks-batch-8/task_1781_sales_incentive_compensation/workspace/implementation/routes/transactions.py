"""Transaction routes: create, get, list, cancel."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_SPLIT_TOTAL_INVALID,
    ERR_SPLIT_REP_INELIGIBLE,
    ERR_DUPLICATE_TRANSACTION_REF,
    ERR_TRANSACTION_ALREADY_CANCELLED,
)
from middleware import authorized
from response import success_object, success_list
from util import new_entity, new_id, now_ts, touch, serialize
from validate import (
    get_body, req_str, req_int, req_date,
    parse_pagination, require_path_resource,
)
from services.calculations import (
    split_credit_allocation,
    recompute_assignment_indicators,
)
from services.crediting import post_credit_entry, reverse_credit_entry

bp = Blueprint("transactions", __name__)

ANALYST_ONLY = ["CompAnalyst"]
ALL_ROLES = ["CompAdmin", "CompAnalyst", "CompManager", "Rep"]


def _find_active_assignment_for_rep(rep_id, program_id):
    """Find a rep's ACTIVE assignment in the given program."""
    for a in db["assignments"].values():
        if (a["rep_id"] == rep_id
                and a["program_id"] == program_id
                and a["status"] == "ACTIVE"):
            return a
    return None


@bp.route("/transactions", methods=["POST"])
def create_transaction():
    caller = authorized(ANALYST_ONLY)
    body = get_body()

    # Basic field validation
    program_id = req_str(body, "program_id")
    external_ref = req_str(body, "external_ref")
    amount_cents = req_int(body, "amount_cents")
    transaction_date = req_date(body, "transaction_date")

    splits_raw = body.get("splits")
    if splits_raw is None:
        raise_error(ERR_INVALID_REQUEST, "missing required field: splits")
    if not isinstance(splits_raw, list):
        raise_error(ERR_INVALID_REQUEST, "splits must be an array")
    splits = []
    for s in splits_raw:
        if not isinstance(s, dict):
            raise_error(ERR_INVALID_REQUEST, "each split must be an object")
        rep_id = s.get("rep_id")
        split_bps = s.get("split_bps")
        if not rep_id or not isinstance(rep_id, str):
            raise_error(ERR_INVALID_REQUEST, "split rep_id must be a non-empty string")
        if split_bps is None or isinstance(split_bps, bool) or not isinstance(split_bps, int):
            raise_error(ERR_INVALID_REQUEST, "split split_bps must be an integer")
        if split_bps <= 0:
            raise_error(ERR_INVALID_REQUEST, "split split_bps must be > 0")
        splits.append({"rep_id": rep_id, "split_bps": split_bps})

    if amount_cents <= 0:
        raise_error(ERR_INVALID_REQUEST, "amount_cents must be > 0")

    # Priority 3: program exists
    program = db["programs"].get(program_id)
    if program is None:
        raise_error(ERR_NOT_FOUND, f"program not found: {program_id}")

    # Priority 7: split total == 10000
    total_bps = sum(s["split_bps"] for s in splits)
    if total_bps != 10000:
        raise_error(ERR_SPLIT_TOTAL_INVALID,
                    f"split_bps sum is {total_bps}, must be exactly 10000")

    # Priority 7: external_ref unique per program
    for t in db["transactions"].values():
        if t["program_id"] == program_id and t["external_ref"] == external_ref:
            raise_error(ERR_DUPLICATE_TRANSACTION_REF,
                        f"external_ref {external_ref} already exists in program")

    # Priority 8: every split rep has ACTIVE assignment in program
    split_assignments = {}
    for s in splits:
        asg = _find_active_assignment_for_rep(s["rep_id"], program_id)
        if asg is None:
            raise_error(ERR_SPLIT_REP_INELIGIBLE,
                        f"rep {s['rep_id']} has no ACTIVE assignment in program")
        split_assignments[s["rep_id"]] = asg

    # Create transaction
    transaction = new_entity({
        "program_id": program_id,
        "external_ref": external_ref,
        "amount_cents": amount_cents,
        "transaction_date": transaction_date,
        "splits": splits,
        "booked_period_index": program["current_period_index"],
        "status": "BOOKED",
    })
    db["transactions"][transaction["id"]] = transaction

    # Allocate credits per split
    credit_amounts = split_credit_allocation(amount_cents, splits)

    for i, split in enumerate(splits):
        asg = split_assignments[split["rep_id"]]
        plan = db["plans"][asg["plan_id"]]

        # Determine initial status: POSTED if ACTIVE+ACCEPTED+PUBLISHED, else PENDING
        can_post = (
            asg["status"] == "ACTIVE"
            and asg["acceptance_status"] == "ACCEPTED"
            and plan["status"] == "PUBLISHED"
        )

        ts = now_ts()
        entry = {
            "id": new_id(),
            "transaction_id": transaction["id"],
            "assignment_id": asg["id"],
            "rep_id": split["rep_id"],
            "parent_credit_id": None,
            "credit_type": "DIRECT",
            "credit_amount_cents": credit_amounts[i],
            "posted_period_index": None,
            "status": "PENDING",
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        db["credit_entries"][entry["id"]] = entry

        if can_post:
            post_credit_entry(entry, program)
        else:
            # PENDING park is still a credit change: refresh the live
            # indicators so provisional payout includes the held credit.
            recompute_assignment_indicators(asg)

    return success_object(serialize(transaction), 201)


@bp.route("/transactions/<transactionId>", methods=["GET"])
def get_transaction(transactionId):
    caller = authorized(ALL_ROLES)
    txn = require_path_resource("transactions", transactionId)
    return success_object(serialize(txn))


@bp.route("/transactions", methods=["GET"])
def list_transactions():
    caller = authorized(ALL_ROLES)
    limit, offset = parse_pagination()

    items = list(db["transactions"].values())

    program_id = request.args.get("program_id")
    status_filter = request.args.get("status")

    if program_id:
        items = [t for t in items if t["program_id"] == program_id]
    if status_filter:
        items = [t for t in items if t["status"] == status_filter]

    items.sort(key=lambda t: (t["created_at"], t["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(t) for t in page], total, limit, offset)


@bp.route("/transactions/<transactionId>/cancel", methods=["POST"])
def cancel_transaction(transactionId):
    caller = authorized(ANALYST_ONLY)
    txn = require_path_resource("transactions", transactionId)

    # Priority 4: state — must be BOOKED
    if txn["status"] == "CANCELLED":
        raise_error(ERR_TRANSACTION_ALREADY_CANCELLED,
                    "transaction is already CANCELLED")

    program = db["programs"][txn["program_id"]]

    # Reverse all credits of this transaction in {PENDING, POSTED, LOCKED}
    entries = [
        c for c in db["credit_entries"].values()
        if c["transaction_id"] == transactionId
        and c["status"] in ("PENDING", "POSTED", "LOCKED")
    ]
    # Sort to process parents before children (deterministic)
    entries.sort(key=lambda c: (c["created_at"], c["id"]))

    for entry in entries:
        if entry["status"] in ("PENDING", "POSTED", "LOCKED"):
            reverse_credit_entry(entry, program)

    txn["status"] = "CANCELLED"
    touch(txn)

    return success_object(serialize(txn))
