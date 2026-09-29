"""Allocation offers, claims, inventory lots and the append-only depletion ledger."""
from flask import Blueprint

from core import (
    ALL_ROLES,
    API_PREFIX,
    D,
    authorize,
    check_distributor_scope,
    check_venue_scope,
    fail,
    get_bin,
    get_body,
    get_claim,
    get_depletion_entry,
    get_distributor,
    get_lot,
    get_offer,
    get_venue,
    get_wine,
    new_record,
    now,
    paginate,
    parse_iso,
    q,
    respond_list,
    respond_object,
    serialize,
    sort_default,
    store,
    touch,
    validate_body,
)
from calc import claim_state_for, waterfall
from cascade import recompute_bin, refresh_availability

bp = Blueprint("alloc", __name__)

CELLAR_READ_ROLES = ["BeverageDirector", "VenueSommelier", "Controller", "ComplianceOfficer"]

OFFER_SPEC = [
    {"name": "distributor_id", "type": "string", "required": True},
    {"name": "wine_id", "type": "string", "required": True},
    {"name": "offered_bottles", "type": "int", "required": True, "min": 1},
    {"name": "unit_cost_cents", "type": "int", "required": True, "min": 1},
    {"name": "response_deadline", "type": "datetime", "required": True},
]


@bp.post(API_PREFIX + "/allocation-offers")
def create_offer():
    user_id, role = authorize("DistributorRep")
    body = get_body()
    check_distributor_scope(role, user_id, body.get("distributor_id"))
    distributor = None
    if body.get("distributor_id") is not None:
        distributor = get_distributor(body["distributor_id"])
    if body.get("wine_id") is not None:
        get_wine(body["wine_id"])
    validate_body(body, OFFER_SPEC)

    if distributor["compliance_state"] == "HOLD":
        fail("ERR_DISTRIBUTOR_COMPLIANCE_HOLD", "This distributor's licence is on hold.")

    rec = new_record(
        {
            "distributor_id": body["distributor_id"],
            "wine_id": body["wine_id"],
            "offered_bottles": body["offered_bottles"],
            "unit_cost_cents": body["unit_cost_cents"],
            "response_deadline": parse_iso(body["response_deadline"]),
            "fulfillment_state": "OPEN",
            "compliance_state": (
                "CLEARED" if distributor["compliance_state"] == "CLEARED" else "PENDING_LICENSE_CHECK"
            ),
            "unallocated_bottles": body["offered_bottles"],
            "claim_count": 0,
            "allocated_at": None,
        }
    )
    store.allocation_offers[rec["id"]] = rec
    return respond_object(serialize(rec), 201)


@bp.get(API_PREFIX + "/allocation-offers/<offer_id>")
def read_offer(offer_id):
    authorize(ALL_ROLES)
    return respond_object(serialize(get_offer(offer_id)))


@bp.get(API_PREFIX + "/allocation-offers")
def list_offers():
    user_id, role = authorize(ALL_ROLES)
    check_distributor_scope(role, user_id, q("distributor_id"))
    rows = list(store.allocation_offers.values())
    for field in ("distributor_id", "wine_id", "fulfillment_state", "compliance_state"):
        value = q(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    page, meta = paginate(sort_default(rows))
    return respond_list([serialize(r) for r in page], meta)


CLAIM_SPEC = [
    {"name": "venue_id", "type": "string", "required": True},
    {"name": "requested_bottles", "type": "int", "required": True, "min": 1},
    {"name": "expected_offer_version", "type": "int", "required": True},
]


@bp.post(API_PREFIX + "/allocation-offers/<offer_id>/claims")
def create_claim(offer_id):
    user_id, role = authorize("VenueSommelier")
    body = get_body()
    check_venue_scope(role, user_id, body.get("venue_id"))
    offer = get_offer(offer_id)
    if body.get("venue_id") is not None:
        get_venue(body["venue_id"])
    validate_body(body, CLAIM_SPEC)

    if any(
        c["offer_id"] == offer_id and c["venue_id"] == body["venue_id"]
        for c in store.allocation_claims.values()
    ):
        fail("ERR_DUPLICATE_CLAIM", "This venue already holds a claim on this offer.")
    if int(body["expected_offer_version"]) != int(offer["version"]):
        fail("ERR_STALE_VERSION", "The offer has moved on since it was last read.")
    if offer["fulfillment_state"] != "OPEN":
        fail("ERR_OFFER_NOT_OPEN", "The offer is no longer open for claims.")
    distributor = store.distributors.get(offer["distributor_id"])
    if distributor is not None and distributor["compliance_state"] == "HOLD":
        fail("ERR_DISTRIBUTOR_COMPLIANCE_HOLD", "This distributor's licence is on hold.")
    if now() >= offer["response_deadline"]:
        fail("ERR_OFFER_DEADLINE_PASSED", "The response deadline has passed.")
    if int(body["requested_bottles"]) > int(offer["offered_bottles"]):
        fail("ERR_REQUEST_EXCEEDS_OFFER", "The request exceeds the offered pool.")

    rec = new_record(
        {
            "offer_id": offer_id,
            "venue_id": body["venue_id"],
            "requested_bottles": body["requested_bottles"],
            "granted_bottles": 0,
            "raw_share": D("0.0000"),
            "remainder_awarded": False,
            "state": "REQUESTED",
        }
    )
    store.allocation_claims[rec["id"]] = rec
    offer["claim_count"] = int(offer["claim_count"]) + 1
    touch(offer)
    return respond_object(serialize(rec), 201)


@bp.post(API_PREFIX + "/allocation-offers/<offer_id>/allocate")
def allocate_offer(offer_id):
    authorize("BeverageDirector")
    offer = get_offer(offer_id)
    if offer["fulfillment_state"] != "OPEN":
        fail("ERR_OFFER_NOT_OPEN", "Only an open offer may be allocated.")
    if offer["compliance_state"] == "BLOCKED":
        fail("ERR_OFFER_COMPLIANCE_BLOCKED", "This offer is blocked on licence compliance.")
    claims = sorted(
        [
            c
            for c in store.allocation_claims.values()
            if c["offer_id"] == offer_id and c["state"] == "REQUESTED"
        ],
        key=lambda c: (c["created_at"], c["_seq"]),
    )
    if not claims:
        fail("ERR_NO_ELIGIBLE_CLAIMS", "No claim on this offer is awaiting allocation.")

    awards, unallocated = waterfall(offer["offered_bottles"], claims)
    for claim in claims:
        granted, raw_share, remainder_awarded = awards[claim["id"]]
        claim["granted_bottles"] = granted
        claim["raw_share"] = raw_share
        claim["remainder_awarded"] = remainder_awarded
        claim["state"] = claim_state_for(granted, int(claim["requested_bottles"]))
        touch(claim)

    offer["fulfillment_state"] = "ALLOCATED"
    offer["allocated_at"] = now()
    offer["unallocated_bottles"] = unallocated
    touch(offer)
    return respond_object(serialize(offer))


@bp.get(API_PREFIX + "/allocation-claims/<claim_id>")
def read_claim(claim_id):
    authorize(ALL_ROLES)
    return respond_object(serialize(get_claim(claim_id)))


@bp.get(API_PREFIX + "/allocation-claims")
def list_claims():
    authorize(ALL_ROLES)
    rows = list(store.allocation_claims.values())
    for field in ("offer_id", "venue_id", "state"):
        value = q(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    page, meta = paginate(sort_default(rows))
    return respond_list([serialize(r) for r in page], meta)


def _close_offer_if_settled(offer):
    """An ALLOCATED offer with no claim left in GRANTED or PARTIALLY_GRANTED closes."""
    if offer["fulfillment_state"] != "ALLOCATED":
        return
    for claim in store.allocation_claims.values():
        if claim["offer_id"] == offer["id"] and claim["state"] in (
            "GRANTED",
            "PARTIALLY_GRANTED",
        ):
            return
    offer["fulfillment_state"] = "CLOSED"
    touch(offer)


@bp.post(API_PREFIX + "/allocation-claims/<claim_id>/withdraw")
def withdraw_claim(claim_id):
    user_id, role = authorize("VenueSommelier")
    claim = get_claim(claim_id)
    check_venue_scope(role, user_id, claim["venue_id"])
    if claim["state"] not in ("REQUESTED", "GRANTED", "PARTIALLY_GRANTED"):
        fail("ERR_CLAIM_NOT_WITHDRAWABLE", "This claim can no longer be withdrawn.")
    offer = store.allocation_offers.get(claim["offer_id"])
    if claim["state"] in ("GRANTED", "PARTIALLY_GRANTED") and offer is not None:
        offer["unallocated_bottles"] = int(offer["unallocated_bottles"]) + int(
            claim["granted_bottles"]
        )
        claim["granted_bottles"] = 0
    claim["state"] = "WITHDRAWN"
    touch(claim)
    if offer is not None:
        offer["claim_count"] = int(offer["claim_count"]) - 1
        touch(offer)
        _close_offer_if_settled(offer)
    return respond_object(serialize(claim))


RECEIVE_SPEC = [
    {"name": "bin_id", "type": "string", "required": True},
    {"name": "received_at", "type": "datetime", "required": True},
]

LOT_SPEC = [
    {"name": "venue_id", "type": "string", "required": True},
    {"name": "wine_id", "type": "string", "required": True},
    {"name": "bin_id", "type": "string", "required": True},
    {"name": "bottles_received", "type": "int", "required": True, "min": 1},
    {"name": "unit_cost_cents", "type": "int", "required": True, "min": 1},
    {"name": "received_at", "type": "datetime", "required": True},
]


def _receipt_checks(bin_rec, venue_id, wine, bottles, received_at):
    if received_at > now():
        fail("ERR_RECEIVED_AT_IN_FUTURE", "received_at is later than the logical clock.")
    if bin_rec["venue_id"] != venue_id:
        fail("ERR_LOT_VENUE_MISMATCH", "The nominated bin belongs to another venue.")
    if bin_rec["zone"] == "RESERVE" and not wine["is_allocated"]:
        fail("ERR_BIN_ZONE_MISMATCH", "Only an allocated wine may be stored in a reserve bin.")
    if int(bin_rec["bottles_stored"]) + int(bottles) > int(bin_rec["capacity_bottles"]):
        fail("ERR_BIN_CAPACITY_EXCEEDED", "The bin cannot hold that many bottles.")


def _create_lot(venue_id, wine_id, bin_id, bottles, unit_cost_cents, received_at, source_claim_id):
    rec = new_record(
        {
            "venue_id": venue_id,
            "wine_id": wine_id,
            "bin_id": bin_id,
            "source_claim_id": source_claim_id,
            "bottles_received": int(bottles),
            "bottles_on_hand": int(bottles),
            "bottles_committed": 0,
            "unit_cost_cents": int(unit_cost_cents),
            "received_at": received_at,
            "state": "ON_HAND",
        }
    )
    store.inventory_lots[rec["id"]] = rec
    return rec


@bp.post(API_PREFIX + "/allocation-claims/<claim_id>/receive")
def receive_claim(claim_id):
    user_id, role = authorize("VenueSommelier")
    claim = get_claim(claim_id)
    check_venue_scope(role, user_id, claim["venue_id"])
    body = get_body()
    bin_rec = None
    if body.get("bin_id") is not None:
        bin_rec = get_bin(body["bin_id"])
    validate_body(body, RECEIVE_SPEC)

    if claim["state"] not in ("GRANTED", "PARTIALLY_GRANTED"):
        fail("ERR_CLAIM_NOT_GRANTED", "Only a granted claim may be received.")
    offer = store.allocation_offers.get(claim["offer_id"])
    # PRD 2.8 rung 18 fixes the order of the two compliance-safety checks:
    # "Compliance safety: distributor hold, offer block, prohibited
    # by-your-own-bottle category." Section 5 makes that ladder the
    # tie-breaker whenever several errors could apply to one request.
    distributor = store.distributors.get(offer["distributor_id"])
    if distributor is not None and distributor["compliance_state"] == "HOLD":
        fail("ERR_DISTRIBUTOR_COMPLIANCE_HOLD", "This distributor's licence is on hold.")
    if offer["compliance_state"] == "BLOCKED":
        fail("ERR_OFFER_COMPLIANCE_BLOCKED", "This offer is blocked on licence compliance.")
    wine = store.wines.get(offer["wine_id"])
    received_at = parse_iso(body["received_at"])
    bottles = int(claim["granted_bottles"])
    _receipt_checks(bin_rec, claim["venue_id"], wine, bottles, received_at)

    lot = _create_lot(
        claim["venue_id"],
        offer["wine_id"],
        bin_rec["id"],
        bottles,
        offer["unit_cost_cents"],
        received_at,
        claim["id"],
    )
    claim["state"] = "RECEIVED"
    touch(claim)
    recompute_bin(bin_rec)
    refresh_availability(claim["venue_id"], offer["wine_id"])
    _close_offer_if_settled(offer)
    return respond_object(serialize(lot), 201)


@bp.post(API_PREFIX + "/inventory-lots")
def create_lot():
    user_id, role = authorize("VenueSommelier")
    body = get_body()
    check_venue_scope(role, user_id, body.get("venue_id"))
    if body.get("venue_id") is not None:
        get_venue(body["venue_id"])
    wine = None
    if body.get("wine_id") is not None:
        wine = get_wine(body["wine_id"])
    bin_rec = None
    if body.get("bin_id") is not None:
        bin_rec = get_bin(body["bin_id"])
    validate_body(body, LOT_SPEC)

    received_at = parse_iso(body["received_at"])
    _receipt_checks(bin_rec, body["venue_id"], wine, body["bottles_received"], received_at)

    lot = _create_lot(
        body["venue_id"],
        body["wine_id"],
        body["bin_id"],
        body["bottles_received"],
        body["unit_cost_cents"],
        received_at,
        None,
    )
    recompute_bin(bin_rec)
    refresh_availability(body["venue_id"], body["wine_id"], direction="restock")
    return respond_object(serialize(lot), 201)


@bp.get(API_PREFIX + "/inventory-lots/<lot_id>")
def read_lot(lot_id):
    authorize(CELLAR_READ_ROLES)
    return respond_object(serialize(get_lot(lot_id)))


@bp.get(API_PREFIX + "/inventory-lots")
def list_lots():
    authorize(CELLAR_READ_ROLES)
    source_claim_id = q("source_claim_id")
    if source_claim_id is not None:
        get_claim(source_claim_id)
    rows = list(store.inventory_lots.values())
    for field in ("venue_id", "wine_id", "bin_id", "source_claim_id", "state"):
        value = q(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    rows = sorted(rows, key=lambda r: (r["received_at"], r["created_at"], r["_seq"]))
    page, meta = paginate(rows)
    return respond_list([serialize(r) for r in page], meta)


@bp.get(API_PREFIX + "/depletion-entries/<depletion_entry_id>")
def read_depletion_entry(depletion_entry_id):
    authorize(CELLAR_READ_ROLES)
    return respond_object(serialize(get_depletion_entry(depletion_entry_id)))


@bp.get(API_PREFIX + "/depletion-entries")
def list_depletion_entries():
    authorize(CELLAR_READ_ROLES)
    rows = list(store.depletion_entries.values())
    for field in (
        "venue_id",
        "wine_id",
        "lot_id",
        "list_entry_id",
        "btg_slot_id",
        "event_id",
        "write_off_id",
        "reason",
    ):
        value = q(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    rows = sorted(rows, key=lambda r: (r["occurred_at"], r["created_at"], r["_seq"]))
    page, meta = paginate(rows)
    return respond_list([serialize(r) for r in page], meta)
