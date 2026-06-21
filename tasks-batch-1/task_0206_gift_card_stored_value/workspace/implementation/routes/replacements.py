"""ReplacementRequest open/read/list/approve/reject (PRD §3.7)."""

from flask import Blueprint, request

from db import db
from core import (
    get_body, stamp_new, touch, paginate,
    check_str, check_int, check_enum,
    settled_balance, post_ledger,
)
from errors import err
from middleware import get_identity, require_role
from response import success
from lookups import get_replacement
import serialize

bp = Blueprint("replacements", __name__)


@bp.post("/v1/replacements")
def open_replacement():
    uid, role = get_identity()
    require_role(role, {"FraudAnalyst", "Customer"})
    body = get_body()
    old_card_id = check_str(body, "old_card_id")
    reason = check_enum(body, "reason", {"FRAUD", "LOST", "DAMAGED"})

    # Body FK existence (priority 5).
    old_card = db.cards.get(old_card_id)
    if old_card is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "old_card_id does not exist.")
    # Customer ownership: own card only.
    if role == "Customer" and old_card["owner_customer_id"] != uid:
        raise err("ERR_FORBIDDEN", "Customer may only replace own card.")
    # Already-replaced gate (priority 11).
    if old_card["replaced_by_card_id"] is not None:
        raise err("ERR_CARD_ALREADY_REPLACED", "Old card already has an approved replacement.")

    r = {
        "old_card_id": old_card_id,
        "new_card_id": None,
        "reason": reason,
        "transferred_amount_cents": None,
        "status": "OPEN",
    }
    stamp_new(r)
    db.replacements[r["id"]] = r
    return success(serialize.replacement(r), status=201)


@bp.get("/v1/replacements/<replacement_id>")
def read_replacement(replacement_id):
    uid, role = get_identity()
    require_role(role, {"FraudAnalyst", "ProgramAdmin", "Customer"})
    r = get_replacement(replacement_id)
    if role == "Customer":
        old_card = db.cards.get(r["old_card_id"])
        if old_card is None or old_card["owner_customer_id"] != uid:
            raise err("ERR_FORBIDDEN", "Not the owner of this replacement.")
    return success(serialize.replacement(r))


@bp.get("/v1/replacements")
def list_replacements():
    _uid, role = get_identity()
    require_role(role, {"FraudAnalyst", "ProgramAdmin"})
    items = list(db.replacements.values())
    for key in ("old_card_id", "new_card_id"):
        val = request.args.get(key)
        if val is not None:
            items = [r for r in items if r.get(key) == val]
    page, pg = paginate(items)
    return success([serialize.replacement(r) for r in page], pagination=pg)


@bp.post("/v1/replacements/<replacement_id>/approve")
def approve_replacement(replacement_id):
    _uid, role = get_identity()
    require_role(role, {"FraudAnalyst"})
    r = get_replacement(replacement_id)
    body = get_body()
    expected_version = check_int(body, "expected_old_card_version")
    old_card = db.cards[r["old_card_id"]]

    # Replacement must be OPEN (state, priority 8) before approval logic.
    if r["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Replacement is not OPEN.")
    # OCC on old card version (priority 7).
    if expected_version != old_card["version"]:
        raise err("ERR_STALE_VERSION", "Old card version is stale.")
    # Old card must be ACTIVE/EXHAUSTED (priority 8).
    if old_card["lifecycle_status"] not in ("ACTIVE", "EXHAUSTED"):
        raise err("ERR_INVALID_STATE", "Old card is not ACTIVE or EXHAUSTED.")

    # replacement_transfer (PRD §3.7).
    transferred = settled_balance(old_card["id"])

    new_card = {
        "program_id": old_card["program_id"],
        "owner_customer_id": old_card["owner_customer_id"],
        "form_factor": old_card["form_factor"],
        "state_code": old_card["state_code"],
        "lifecycle_status": "ACTIVE",
        "risk_status": "CLEAR",
        "replaced_by_card_id": None,
        "activated_at": None,
    }
    stamp_new(new_card)
    db.cards[new_card["id"]] = new_card

    # TRANSFER_OUT zeroes the old card; TRANSFER_IN credits the new card.
    post_ledger(old_card, "TRANSFER_OUT", -transferred, source_ref_id=r["id"])
    in_entry = post_ledger(new_card, "TRANSFER_IN", transferred, source_ref_id=r["id"])
    new_card["activated_at"] = in_entry["created_at"]

    old_card["lifecycle_status"] = "VOIDED"
    old_card["replaced_by_card_id"] = new_card["id"]
    touch(old_card)

    r["new_card_id"] = new_card["id"]
    r["transferred_amount_cents"] = transferred
    r["status"] = "APPROVED"
    touch(r)
    return success(serialize.replacement(r))


@bp.post("/v1/replacements/<replacement_id>/reject")
def reject_replacement(replacement_id):
    _uid, role = get_identity()
    require_role(role, {"FraudAnalyst"})
    r = get_replacement(replacement_id)
    if r["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Replacement is not OPEN.")
    r["status"] = "REJECTED"
    touch(r)
    return success(serialize.replacement(r))
