"""Disputes: open (freezes disbursements) and resolve."""

from db import store, now
from errors import ApiError
from helpers import (
    get_body, check_allowed_fields, req_string, req_enum, req_int,
    get_dispute_or_404, get_holdback_or_404, file_of_holdback,
    new_entity, touch, refresh_holdback_derived, ser_dispute,
)
from middleware import authenticate, authorize
from response import success

from . import bp

CATEGORIES = {"WORK_QUALITY", "DRAW_DENIAL", "DEADLINE", "EXPENSE_RESPONSIBILITY", "OTHER"}
RESOLUTIONS = {"FOR_BUYER", "FOR_SELLER", "SPLIT"}

_RESOLUTION_STATUS = {
    "FOR_BUYER": "RESOLVED_BUYER",
    "FOR_SELLER": "RESOLVED_SELLER",
    "SPLIT": "RESOLVED_SPLIT",
}

_RESOLUTION_OVERRIDE = {
    "FOR_BUYER": "RELEASE_TO_BUYER",
    "FOR_SELLER": "RETURN_TO_SELLER",
    "SPLIT": "SPLIT_EQUAL",
}


@bp.post("/escrow/disputes")
def create_dispute():
    uid, role = authenticate()
    authorize(role, ["Buyer", "Seller"])
    data = get_body()
    raw_hid = data.get("holdback_id")
    if isinstance(raw_hid, str) and raw_hid not in store.holdbacks:
        raise ApiError("ERR_NOT_FOUND", "Holdback not found: %s" % raw_hid)
    check_allowed_fields(data, {"holdback_id", "category", "claimed_amount_cents", "statement"})
    hid = req_string(data, "holdback_id")
    hb = get_holdback_or_404(hid)
    category = req_enum(data, "category", CATEGORIES)
    claimed = req_int(data, "claimed_amount_cents", lo=0)
    statement = req_string(data, "statement")

    # Rung 5: the initiator must be the file's buyer or seller.
    f = file_of_holdback(hb)
    if f is None or uid not in (f["buyer_user_id"], f["seller_user_id"]):
        raise ApiError("ERR_NOT_FILE_PARTY", "Only the file's buyer or seller may open a dispute")
    # Rung 10: one OPEN dispute at a time.
    for d in store.disputes.values():
        if d["holdback_id"] == hid and d["status"] == "OPEN":
            raise ApiError("ERR_DISPUTE_ALREADY_OPEN", "An OPEN dispute already exists")

    d = new_entity()
    d.update({
        "holdback_id": hid,
        "initiator_role": "BUYER" if role == "Buyer" else "SELLER",
        "initiator_user_id": uid,
        "category": category,
        "claimed_amount_cents": claimed,
        "statement": statement,
        "status": "OPEN",
        "resolution_note": None,
        "resolved_at": None,
    })
    store.disputes[d["id"]] = d
    # The freeze recomputes immediately.
    if refresh_holdback_derived(hb):
        touch(hb)
    return success(ser_dispute(d), response_type="object", status=201)


@bp.post("/escrow/disputes/<did>/resolve")
def resolve_dispute(did):
    _uid, role = authenticate()
    authorize(role, ["EscrowOfficer"])
    d = get_dispute_or_404(did)
    data = get_body()
    check_allowed_fields(data, {"resolution", "resolution_note"})
    resolution = req_enum(data, "resolution", RESOLUTIONS)
    resolution_note = req_string(data, "resolution_note")

    hb = get_holdback_or_404(d["holdback_id"])
    # Rung 7: only an OPEN dispute can be resolved.
    if d["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Dispute is not OPEN")

    d["status"] = _RESOLUTION_STATUS[resolution]
    d["resolution_note"] = resolution_note
    d["resolved_at"] = now()
    touch(d)

    hb_mutated = False
    # On an EXPIRED holdback the resolution overrides the expiration terms.
    if hb["status"] == "EXPIRED":
        override = _RESOLUTION_OVERRIDE[resolution]
        if hb["disposition_override"] != override:
            hb["disposition_override"] = override
            hb_mutated = True
    if refresh_holdback_derived(hb):
        hb_mutated = True
    if hb_mutated:
        touch(hb)

    return success(ser_dispute(d), response_type="object", status=200)
