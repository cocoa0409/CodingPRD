"""The statutory mandatory offer (PRD 3.1)."""

from flask import Blueprint

import calc
import envelope
import guards
import store
from errors import ApiError

bp = Blueprint("offers", __name__)


def _pending_exists(insurer_id, dwelling_id, exclude_id=None):
    for offer in store.DB["offers"].values():
        if exclude_id is not None and offer["id"] == exclude_id:
            continue
        if (offer["insurer_id"] == insurer_id
                and offer["dwelling_id"] == dwelling_id
                and offer["status"] == "PENDING"):
            return True
    return False


@bp.post("/mandatory-offers")
def create_offer():
    role = guards.auth(("ParticipatingInsurer", "ProgramAdmin"))
    body = guards.body()
    fks = guards.body_fks(body, ("insurer_id", "policyholder_id", "dwelling_id"))
    insurer = fks.get("insurer_id")
    if role == "ParticipatingInsurer" and insurer is not None:
        guards.owner_must_be(insurer["id"])
    guards.required(body, ("insurer_id", "policyholder_id", "dwelling_id"))
    campaign = guards.optional_string(body, "campaign_code", "NONE")
    policyholder = fks["policyholder_id"]
    dwelling = fks["dwelling_id"]
    # Rung 35 / 36: no new business through a sanctioned or withdrawn carrier.
    if insurer["compliance_status"] == "SANCTIONED":
        raise ApiError("ERR_INSURER_SANCTIONED")
    if insurer["status"] != "ACTIVE":
        raise ApiError("ERR_INSURER_WITHDRAWN")
    # Rung 46: the named recipient must own the covered structure.
    if dwelling["policyholder_id"] != policyholder["id"]:
        raise ApiError("ERR_DWELLING_OWNER_MISMATCH")
    # Rung 53: one PENDING offer per insurer-and-dwelling pair.
    if _pending_exists(insurer["id"], dwelling["id"]):
        raise ApiError("ERR_DUPLICATE_PENDING_OFFER")
    offered_at = store.clock_now()
    row = store.insert("offers", {
        "insurer_id": insurer["id"],
        "policyholder_id": policyholder["id"],
        "dwelling_id": dwelling["id"],
        "offered_at": store.iso(offered_at),
        "expires_at": store.iso(store.plus_days(offered_at, calc.OFFER_VALID_DAYS)),
        "status": "PENDING",
        "decline_documented": False,
        "offer_round": 1,
        "campaign_code": campaign,
        "responded_at": None,
    })
    insurer["offers_recorded_count"] += 1
    store.touch(insurer)
    return envelope.created(store.public(row))


@bp.post("/mandatory-offers/<row_id>/respond")
def respond_offer(row_id):
    guards.auth(("Policyholder",))
    offer = guards.path_row("offers", row_id)
    guards.owner_must_be(offer["policyholder_id"])
    body = guards.body()
    guards.required(body, ("response",))
    response = guards.enum(body, "response", "offer_response")
    documented = guards.optional_bool(body, "decline_documented", False)
    # Rung 16, then rung 65.
    if offer["status"] != "PENDING":
        raise ApiError("ERR_OFFER_ALREADY_RESPONDED")
    if store.clock_now() > store.dt_of(offer, "expires_at"):
        raise ApiError("ERR_OFFER_EXPIRED")
    offer["responded_at"] = store.now_iso()
    if response == "ACCEPT":
        offer["status"] = "ACCEPTED"
    else:
        offer["status"] = "DECLINED"
        offer["decline_documented"] = documented
        if not documented:
            insurer = store.DB["insurers"].get(offer["insurer_id"])
            if insurer is not None:
                insurer["undocumented_decline_count"] += 1
                store.touch(insurer)
    store.touch(offer)
    return envelope.object_response(store.public(offer))


@bp.post("/mandatory-offers/<row_id>/reoffer")
def reoffer(row_id):
    role = guards.auth(("ParticipatingInsurer", "ProgramAdmin"))
    offer = guards.path_row("offers", row_id)
    if role == "ParticipatingInsurer":
        guards.owner_must_be(offer["insurer_id"])
    # Rung 17: only a DECLINED or ACCEPTED offer may be re-extended.
    if offer["status"] not in ("DECLINED", "ACCEPTED"):
        raise ApiError("ERR_OFFER_NOT_REOFFERABLE")
    # Rung 53.
    if _pending_exists(offer["insurer_id"], offer["dwelling_id"], exclude_id=offer["id"]):
        raise ApiError("ERR_DUPLICATE_PENDING_OFFER")
    was_undocumented_decline = (offer["status"] == "DECLINED"
                                and not offer["decline_documented"])
    offered_at = store.clock_now()
    offer["status"] = "PENDING"
    offer["offer_round"] += 1
    offer["offered_at"] = store.iso(offered_at)
    offer["expires_at"] = store.iso(store.plus_days(offered_at, calc.OFFER_VALID_DAYS))
    offer["responded_at"] = None
    offer["decline_documented"] = False
    store.touch(offer)
    if was_undocumented_decline:
        insurer = store.DB["insurers"].get(offer["insurer_id"])
        if insurer is not None:
            insurer["undocumented_decline_count"] -= 1
            store.touch(insurer)
    return envelope.object_response(store.public(offer))


@bp.post("/mandatory-offers/<row_id>/expire")
def expire_offer(row_id):
    guards.auth(("ProgramAdmin",))
    offer = guards.path_row("offers", row_id)
    # Rung 16, then rung 66.
    if offer["status"] != "PENDING":
        raise ApiError("ERR_OFFER_ALREADY_RESPONDED")
    if not store.clock_now() > store.dt_of(offer, "expires_at"):
        raise ApiError("ERR_OFFER_STILL_VALID")
    offer["status"] = "EXPIRED"
    store.touch(offer)
    return envelope.object_response(store.public(offer))


@bp.get("/mandatory-offers/<row_id>")
def read_offer(row_id):
    role = guards.auth(("ProgramAdmin", "ParticipatingInsurer", "Policyholder"))
    offer = guards.path_row("offers", row_id)
    if role == "Policyholder":
        guards.owner_must_be(offer["policyholder_id"])
    elif role == "ParticipatingInsurer":
        guards.owner_must_be(offer["insurer_id"])
    return envelope.object_response(store.public(offer))


@bp.get("/mandatory-offers")
def list_offers():
    role = guards.auth(("ProgramAdmin", "ParticipatingInsurer", "Policyholder"))
    rows = store.all_rows("offers")
    acting = guards.acting_id()
    if role == "Policyholder":
        rows = [row for row in rows if row["policyholder_id"] == acting]
    elif role == "ParticipatingInsurer":
        rows = [row for row in rows if row["insurer_id"] == acting]
    rows = guards.filtered(rows, (("insurer_id", "insurer_id"),
                                  ("policyholder_id", "policyholder_id"),
                                  ("dwelling_id", "dwelling_id"),
                                  ("status", "status"),
                                  ("campaign_code", "campaign_code")))
    return envelope.list_response(rows)
