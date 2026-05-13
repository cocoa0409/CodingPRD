"""Reader registration, blacklist, and card lifecycle routes."""
from flask import Blueprint, request, g

import db
from errors import err
from response import success
from middleware import require_auth
from services import validation as V
from services.common import get_reader, get_card, check_version, assert_reader_ownership
from services.serialize import serialize_reader, serialize_card
from services.reader_status import recompute_reader
from services.money import CARD_PROFILE
from clock import parse_iso, iso, now


bp = Blueprint("readers", __name__)

ALL_ROLES = {"Reader", "Librarian", "FineOfficer", "ILLCoordinator", "Admin"}


# ---------- Reader ----------

@bp.route("/library/readers", methods=["POST"])
@require_auth(roles={"Librarian"})
def create_reader():
    body = V.require_dict(request.get_json(silent=True) or {})
    nid = V.require_sha256(V.require_str(body, "national_id_hash"))
    full_name = V.require_str(body, "full_name")
    for r in db.readers.values():
        if r["national_id_hash"] == nid:
            raise err("ERR_INVALID_INPUT", "national_id_hash already exists")
    entity = {
        "national_id_hash": nid,
        "full_name": full_name,
        "identity_verified": False,
        "identity_verified_at": None,
        "status": "NORMAL",
        "active_loan_count": 0,
        "unpaid_fine_cents": 0,
    }
    db.stamp_create(entity)
    db.readers[entity["id"]] = entity
    return success(serialize_reader(entity), status=201)


@bp.route("/library/readers/<rid>", methods=["GET"])
@require_auth(roles=ALL_ROLES)
def get_reader_endpoint(rid):
    r = get_reader(rid)
    assert_reader_ownership(r["id"])
    return success(serialize_reader(r))


# ---------- Cards ----------

@bp.route("/library/readers/<rid>/cards", methods=["POST"])
@require_auth(roles={"Librarian"})
def issue_card(rid):
    reader = get_reader(rid)
    body = V.require_dict(request.get_json(silent=True) or {})
    card_type = V.require_enum(body, "card_type", V.CARD_TYPES)
    valid_from_str = V.require_str(body, "valid_from")
    valid_until_str = V.require_str(body, "valid_until")
    try:
        vf = parse_iso(valid_from_str)
        vu = parse_iso(valid_until_str)
    except Exception:
        raise err("ERR_INVALID_INPUT", "valid_from / valid_until must be ISO 8601")
    if not (vf < vu):
        raise err("ERR_INVALID_INPUT", "valid_from must be strictly earlier than valid_until")

    if not reader.get("identity_verified"):
        raise err("ERR_IDENTITY_NOT_VERIFIED",
                  "Reader identity must be verified before issuing a card")

    profile = CARD_PROFILE[card_type]
    year = now().year
    card_number = db.next_card_number(year)

    card = {
        "reader_id": reader["id"],
        "card_number": card_number,
        "card_type": card_type,
        "max_loans": profile["max_loans"],
        "loan_duration_days": profile["loan_duration_days"],
        "max_renewals": profile["max_renewals"],
        "valid_from": valid_from_str,
        "valid_until": valid_until_str,
        "status": "ACTIVE",
        "replaced_by_card_id": None,
    }
    db.stamp_create(card)
    db.cards[card["id"]] = card
    return success(serialize_card(card), status=201)


@bp.route("/library/cards/<cid>/freeze", methods=["POST"])
@require_auth(roles={"Librarian"})
def freeze_card(cid):
    card = get_card(cid)
    body = V.require_dict(request.get_json(silent=True) or {})
    check_version(card, body)
    if card["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", f"Card is {card['status']}; can only freeze ACTIVE")
    card["status"] = "FROZEN"
    db.stamp_update(card)
    recompute_reader(card["reader_id"])
    return success(serialize_card(card))


@bp.route("/library/cards/<cid>/unfreeze", methods=["POST"])
@require_auth(roles={"Librarian"})
def unfreeze_card(cid):
    card = get_card(cid)
    body = V.require_dict(request.get_json(silent=True) or {})
    check_version(card, body)
    if card["status"] != "FROZEN":
        raise err("ERR_INVALID_STATE", f"Card is {card['status']}; can only unfreeze FROZEN")
    card["status"] = "ACTIVE"
    db.stamp_update(card)
    recompute_reader(card["reader_id"])
    return success(serialize_card(card))


@bp.route("/library/cards/<cid>/reissue", methods=["POST"])
@require_auth(roles={"Librarian"})
def reissue_card(cid):
    old = get_card(cid)
    body = V.require_dict(request.get_json(silent=True) or {})
    check_version(old, body)
    if old["status"] not in {"ACTIVE", "FROZEN"}:
        raise err("ERR_INVALID_STATE",
                  f"Card is {old['status']}; can only reissue ACTIVE or FROZEN")

    card_type = V.require_enum(body, "card_type", V.CARD_TYPES)
    vf_str = V.require_str(body, "valid_from")
    vu_str = V.require_str(body, "valid_until")
    try:
        vf = parse_iso(vf_str)
        vu = parse_iso(vu_str)
    except Exception:
        raise err("ERR_INVALID_INPUT", "valid_from / valid_until must be ISO 8601")
    if not (vf < vu):
        raise err("ERR_INVALID_INPUT", "valid_from must be strictly earlier than valid_until")

    profile = CARD_PROFILE[card_type]
    year = now().year
    new_card = {
        "reader_id": old["reader_id"],
        "card_number": db.next_card_number(year),
        "card_type": card_type,
        "max_loans": profile["max_loans"],
        "loan_duration_days": profile["loan_duration_days"],
        "max_renewals": profile["max_renewals"],
        "valid_from": vf_str,
        "valid_until": vu_str,
        "status": "ACTIVE",
        "replaced_by_card_id": None,
    }
    db.stamp_create(new_card)
    db.cards[new_card["id"]] = new_card

    old["status"] = "REISSUED"
    old["replaced_by_card_id"] = new_card["id"]
    db.stamp_update(old)
    recompute_reader(old["reader_id"])

    return success(serialize_card(new_card), status=201)


# ---------- Blacklist / Unblacklist ----------

@bp.route("/library/readers/<rid>/blacklist", methods=["POST"])
@require_auth(roles={"Admin"})
def blacklist_reader(rid):
    reader = get_reader(rid)
    body = V.require_dict(request.get_json(silent=True) or {})
    check_version(reader, body)
    V.require_str(body, "reason")
    if reader["status"] == "BLACKLISTED":
        raise err("ERR_INVALID_STATE", "Reader is already BLACKLISTED")
    # Freeze all ACTIVE cards
    for c in db.cards.values():
        if c["reader_id"] == reader["id"] and c["status"] == "ACTIVE":
            c["status"] = "FROZEN"
            db.stamp_update(c)
    reader["status"] = "BLACKLISTED"
    db.stamp_update(reader)
    return success(serialize_reader(reader))


@bp.route("/library/readers/<rid>/unblacklist", methods=["POST"])
@require_auth(roles={"Admin"})
def unblacklist_reader(rid):
    reader = get_reader(rid)
    body = V.require_dict(request.get_json(silent=True) or {})
    check_version(reader, body)
    if reader["status"] != "BLACKLISTED":
        raise err("ERR_INVALID_STATE", "Reader is not currently BLACKLISTED")
    # Pre-conditions: zero unpaid fines AND no active overdue loans
    from services.reader_status import has_overdue_loan, reader_unpaid_fine_cents
    if reader_unpaid_fine_cents(reader["id"]) > 0:
        raise err("ERR_UNPAID_FINE",
                  "Reader has unpaid fines; cannot unblacklist")
    if has_overdue_loan(reader["id"]):
        raise err("ERR_INVALID_STATE",
                  "Reader has overdue active loans; cannot unblacklist")
    # Reset to NORMAL temporarily so recompute decides
    reader["status"] = "NORMAL"
    db.stamp_update(reader)
    recompute_reader(reader["id"])
    return success(serialize_reader(reader))


# ---------- Quota inspection ----------

@bp.route("/library/cards/<cid>/quota", methods=["GET"])
@require_auth(roles={"Reader", "Librarian"})
def card_quota(cid):
    card = get_card(cid)
    if g.user_role == "Reader":
        if g.user_id != card["reader_id"]:
            raise err("ERR_FORBIDDEN", "Reader can inspect quota only on their own cards")
    mode = request.args.get("mode", "strict")
    if mode not in {"strict", "chronological"}:
        raise err("ERR_INVALID_INPUT", "mode must be 'strict' or 'chronological'")

    active_statuses = {"BORROWED", "RENEWED", "RECALL_PENDING"}
    committed = sum(1 for l in db.loans.values()
                    if l["card_id"] == card["id"] and l["status"] in active_statuses)
    reserved = sum(1 for r in db.reservations.values()
                   if r["reader_id"] == card["reader_id"]
                   and r["status"] in {"QUEUED", "READY_FOR_PICKUP"})

    if mode == "strict":
        remaining = max(0, card["max_loans"] - committed - reserved)
    else:
        remaining = max(0, card["max_loans"] - committed)

    return success({
        "card_id": card["id"],
        "mode": mode,
        "max_loans": card["max_loans"],
        "committed_loans": committed,
        "active_reservations": reserved,
        "remaining": remaining,
    })
