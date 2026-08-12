"""Lost-shipment claims (PRD 3.5)."""

from flask import Blueprint

import auth
import calc
import constants as K
import derive
import envelope
import ledger
import listing
import lookup
import serialize
import shape
import store
import timeutil
from errors import ApiError

bp = Blueprint("claims", __name__)


def _lost_units_on(shipment_id):
    units = []
    for item in store.all_rows("box_items"):
        if item["return_shipment_id"] != shipment_id:
            continue
        unit = store.get("units", item["unit_id"])
        if unit is not None and unit["state"] == "LOST_IN_TRANSIT":
            units.append(unit)
    return sorted(units, key=store.order_key)


@bp.post("/kidswear/lost-shipment-claims")
def file_claim():
    caller = auth.gate("Member", "LogisticsCoordinator")
    body = shape.body_json()
    shipment_id = shape.id_string(body, "shipment_id")
    shipment = lookup.shipment(shipment_id)
    auth.own(caller, shipment["member_id"])
    member = lookup.member(shipment["member_id"])
    lookup.standing(member)
    if shipment["status"] != "LOST":
        raise ApiError("ERR_CLAIM_SHIPMENT_NOT_LOST")
    base = shipment["shipped_at"] if shipment["shipped_at"] is not None else shipment["created_at"]
    deadline_at = timeutil.add_days(base, K.LOST_CLAIM_FILING_WINDOW_DAYS)
    clock = timeutil.now()
    if clock > deadline_at:
        raise ApiError("ERR_CLAIM_WINDOW_CLOSED")
    row = store.insert("claims", {
        "shipment_id": shipment_id,
        "member_id": shipment["member_id"],
        "status": "OPENED",
        "variant": None,
        "assessed_value_cents": 0,
        "member_liability_pct": 0,
        "member_liability_cents": 0,
        "filed_at": clock,
        "deadline_at": deadline_at,
        "info_note": None,
        "denial_reason": None,
    })
    return envelope.created(serialize.claim(row))


@bp.get("/kidswear/lost-shipment-claims")
def list_claims():
    caller = auth.gate("LogisticsCoordinator", "Member", "PlatformAdmin", "BillingAgent")
    rows = store.all_rows("claims")
    rows = listing.scope_to_member(caller, rows, lambda r: r["member_id"])
    rows = listing.eq(rows, "shipment_id", shape.query_str("shipment_id"))
    rows = listing.eq(rows, "member_id", shape.query_str("member_id"))
    rows = listing.eq(rows, "status", shape.query_member("status", K.CLAIM_STATUSES))
    return envelope.listing(rows, serialize.claim)


@bp.get("/kidswear/lost-shipment-claims/<claim_id>")
def read_claim(claim_id):
    caller = auth.gate("LogisticsCoordinator", "Member", "PlatformAdmin", "BillingAgent")
    row = lookup.claim(claim_id)
    auth.own(caller, row["member_id"])
    return envelope.ok(serialize.claim(row))


@bp.post("/kidswear/lost-shipment-claims/<claim_id>/investigate")
def investigate(claim_id):
    auth.gate("LogisticsCoordinator")
    claim = lookup.claim(claim_id)
    shipment = lookup.shipment(claim["shipment_id"])
    if claim["status"] != "OPENED":
        raise ApiError("ERR_INVALID_STATE")
    if shipment["status"] != "LOST":
        raise ApiError("ERR_CLAIM_SHIPMENT_NOT_LOST")
    pairs = []
    for unit in _lost_units_on(shipment["id"]):
        style = store.get("styles", unit["style_id"])
        if style is not None:
            pairs.append((unit, style))
    assessed = calc.lost_assessed_value(pairs)
    pct, liability = calc.lost_liability(assessed, shipment["ever_scanned"])
    claim["variant"] = "SCANNED" if shipment["ever_scanned"] else "NEVER_SCANNED"
    claim["assessed_value_cents"] = assessed
    claim["member_liability_pct"] = pct
    claim["member_liability_cents"] = liability
    claim["status"] = "INVESTIGATING"
    store.touch(claim)
    return envelope.ok(serialize.claim(claim))


@bp.post("/kidswear/lost-shipment-claims/<claim_id>/request-info")
def request_info(claim_id):
    auth.gate("LogisticsCoordinator")
    claim = lookup.claim(claim_id)
    if claim["status"] != "INVESTIGATING":
        raise ApiError("ERR_INVALID_STATE")
    claim["status"] = "AWAITING_MEMBER_INFO"
    store.touch(claim)
    return envelope.ok(serialize.claim(claim))


@bp.post("/kidswear/lost-shipment-claims/<claim_id>/provide-info")
def provide_info(claim_id):
    caller = auth.gate("Member")
    body = shape.body_json()
    info_note = shape.string(body, "info_note")
    claim = lookup.claim(claim_id)
    auth.own(caller, claim["member_id"])
    if claim["status"] != "AWAITING_MEMBER_INFO":
        raise ApiError("ERR_INVALID_STATE")
    if claim["info_note"]:
        claim["info_note"] = claim["info_note"] + "\n" + info_note
    else:
        claim["info_note"] = info_note
    claim["status"] = "INVESTIGATING"
    store.touch(claim)
    return envelope.ok(serialize.claim(claim))


@bp.post("/kidswear/lost-shipment-claims/<claim_id>/approve")
def approve_claim(claim_id):
    auth.gate("LogisticsCoordinator")
    claim = lookup.claim(claim_id)
    if claim["status"] != "INVESTIGATING":
        raise ApiError("ERR_INVALID_STATE")
    _, liability = calc.lost_liability(
        claim["assessed_value_cents"], claim["variant"] == "SCANNED")
    claim["member_liability_cents"] = liability
    claim["status"] = "APPROVED"
    store.touch(claim)
    return envelope.ok(serialize.claim(claim))


@bp.post("/kidswear/lost-shipment-claims/<claim_id>/deny")
def deny_claim(claim_id):
    auth.gate("LogisticsCoordinator")
    body = shape.body_json()
    denial_reason = shape.string(body, "denial_reason")
    claim = lookup.claim(claim_id)
    if claim["status"] != "INVESTIGATING":
        raise ApiError("ERR_INVALID_STATE")
    claim["status"] = "DENIED"
    claim["denial_reason"] = denial_reason
    store.touch(claim)
    return envelope.ok(serialize.claim(claim))


@bp.post("/kidswear/lost-shipment-claims/<claim_id>/settle")
def settle_claim(claim_id):
    auth.gate("BillingAgent")
    claim = lookup.claim(claim_id)
    member = lookup.member(claim["member_id"])
    if claim["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE")
    target = None
    for charge in derive.member_charges(member["id"]):
        if charge["charge_type"] != "LOST_LIABILITY":
            continue
        if charge["amount_cents"] == claim["assessed_value_cents"]:
            target = charge
        elif target is None:
            target = charge
    if target is not None:
        target["amount_cents"] = claim["member_liability_cents"]
        ledger.recompute_charge(target)
        store.touch(target)
    for unit in _lost_units_on(claim["shipment_id"]):
        unit["state"] = "RETIRED"
        unit["retired_reason"] = "LOST_WRITE_OFF"
        unit["retirement_eligible"] = True
        store.touch(unit)
    claim["status"] = "SETTLED"
    store.touch(claim)
    ledger.refresh_standing(member)
    return envelope.ok(serialize.claim(claim))
