"""Consignments and lots (PRD 3.1, 3.2, 3.4)."""
from routes.common import (
    ANY_ROLE, ApiError, Blueprint, C, collection_response, db, endpoint,
    field_bool, field_enum, field_int, field_str, fetch, invalid_state,
    json_body, new_entity, object_response, pagination, query_enum, query_str,
    require_owner, touch,
)
from services.derive import (
    knock_down, recompute_auction, recompute_consignment, recompute_consignor,
)

bp = Blueprint("intake", __name__)


def _consignor_of(consignment):
    return db.consignors[consignment["consignor_id"]]


# --------------------------------------------------------------------------
# consignments
# --------------------------------------------------------------------------
@bp.post("/consignments")
@endpoint("Consignor")
def create_consignment(actor):
    body = json_body()
    consignor_id = field_str(body, "consignor_id", required=True)
    agreement_type = field_enum(body, "agreement_type", C.AGREEMENT_TYPES,
                                required=True)
    schedule = field_enum(body, "commission_schedule_code",
                          C.COMMISSION_SCHEDULE_CODES, required=True)
    cap = field_int(body, "refurb_authorization_cap_cents", required=True,
                    min_value=0, max_value=100000000)
    advance = field_int(body, "advance_paid_cents", min_value=0,
                        max_value=100000000, default=0)

    consignor = fetch(db.consignors, consignor_id, "ERR_CONSIGNOR_NOT_FOUND")

    consignment = new_entity()
    consignment.update({
        "consignor_id": consignor["id"],
        "agreement_type": agreement_type,
        "commission_schedule_code": schedule,
        "refurb_authorization_cap_cents": cap,
        "advance_paid_cents": advance,
        "advance_outstanding_cents": advance,
        "status": "DRAFT",
        "correction_note": None,
        "unsold_lot_count": 0,
        "reoffer_lot_count": 0,
    })
    db.consignments[consignment["id"]] = consignment
    recompute_consignor(consignor)
    return object_response(consignment, 201)


@bp.get("/consignments/<consignment_id>")
@endpoint("PlatformAdmin", "Consignor", "IntakeInspector", "AuctionOperator",
          "SettlementOfficer")
def get_consignment(actor, consignment_id):
    return object_response(
        fetch(db.consignments, consignment_id, "ERR_CONSIGNMENT_NOT_FOUND"))


@bp.post("/consignments/<consignment_id>/submit")
@endpoint("Consignor")
def submit_consignment(actor, consignment_id):
    json_body()
    consignment = fetch(db.consignments, consignment_id,
                        "ERR_CONSIGNMENT_NOT_FOUND")
    require_owner(actor, consignment["consignor_id"])
    if consignment["status"] != "DRAFT":
        raise invalid_state("Only a DRAFT consignment may be submitted.")
    lots = [l for l in db.lots.values()
            if l["consignment_id"] == consignment["id"]]
    if not lots:
        raise invalid_state("A consignment needs at least one lot before submission.")
    if consignment["agreement_type"] == "UNRESERVED":
        consignor = _consignor_of(consignment)
        if not consignor["unreserved_policy_ack"]:
            raise ApiError("ERR_UNRESERVED_POLICY_NOT_ACK")
    consignment["status"] = "SUBMITTED"
    touch(consignment)
    recompute_consignor(_consignor_of(consignment))
    return object_response(consignment)


@bp.post("/consignments/<consignment_id>/intake-decision")
@endpoint("AuctionOperator")
def intake_decision(actor, consignment_id):
    body = json_body()
    decision = field_enum(body, "decision", ("ACCEPT", "RETURN"), required=True)
    correction_note = field_str(body, "correction_note", nullable=True)

    consignment = fetch(db.consignments, consignment_id,
                        "ERR_CONSIGNMENT_NOT_FOUND")
    if consignment["status"] != "SUBMITTED":
        raise invalid_state("Only a SUBMITTED consignment may be decided.")

    lots = [l for l in db.lots.values()
            if l["consignment_id"] == consignment["id"]]

    if decision == "RETURN":
        if not correction_note:
            raise invalid_state("A RETURN decision requires a correction_note.")
        consignment["status"] = "DRAFT"
        consignment["correction_note"] = correction_note
    else:
        allowed = ("INTAKE", "INSPECTED", "WITHDRAWN")
        if any(l["lifecycle_status"] not in allowed for l in lots):
            raise invalid_state(
                "Every lot must be INTAKE, INSPECTED or WITHDRAWN to accept intake.")
        consignment["status"] = "INTAKE_ACCEPTED"
    touch(consignment)
    recompute_consignor(_consignor_of(consignment))
    return object_response(consignment)


@bp.get("/consignments/<consignment_id>/lots")
@endpoint("PlatformAdmin", "Consignor", "IntakeInspector", "ComplianceOfficer",
          "AuctionOperator", "SettlementOfficer")
def list_consignment_lots(actor, consignment_id):
    limit, offset = pagination()
    lifecycle = query_enum("lifecycle_status", C.LOT_LIFECYCLE_STATUSES)
    consignment = fetch(db.consignments, consignment_id,
                        "ERR_CONSIGNMENT_NOT_FOUND")
    rows = [l for l in db.lots.values()
            if l["consignment_id"] == consignment["id"]]
    if lifecycle is not None:
        rows = [l for l in rows if l["lifecycle_status"] == lifecycle]
    return collection_response(rows, limit, offset)


# --------------------------------------------------------------------------
# lots
# --------------------------------------------------------------------------
@bp.post("/lots")
@endpoint("Consignor")
def create_lot(actor):
    body = json_body()
    consignment_id = field_str(body, "consignment_id", required=True)
    replacement_of = field_str(body, "replacement_of_lot_id", nullable=True,
                               default=None)
    make = field_str(body, "make", required=True, min_len=1, max_len=60)
    model = field_str(body, "model", required=True, min_len=1, max_len=60)
    model_year = field_int(body, "model_year", required=True, min_value=1960,
                           max_value=2030)
    serial_number = field_str(body, "serial_number", required=True, min_len=4,
                              max_len=40)
    hour_meter = field_int(body, "hour_meter_reading", required=True,
                           min_value=0, max_value=200000)
    weight_kg = field_int(body, "weight_kg", required=True, min_value=500,
                          max_value=200000)
    title_required = field_bool(body, "title_required", default=False)
    reserve_price = field_int(body, "reserve_price_cents", nullable=True,
                              min_value=1, max_value=1000000000, default=None)
    hours_unverified = field_bool(body, "sold_as_hours_unverified", default=False)

    consignment = fetch(db.consignments, consignment_id,
                        "ERR_CONSIGNMENT_NOT_FOUND")
    if replacement_of is not None:
        fetch(db.lots, replacement_of, "ERR_LOT_NOT_FOUND")

    for existing in db.lots.values():
        if existing["serial_number"] == serial_number:
            raise ApiError("ERR_DUPLICATE_SERIAL_NUMBER")

    lot = new_entity()
    lot.update({
        "consignment_id": consignment["id"],
        "replacement_of_lot_id": replacement_of,
        "auction_id": None,
        "make": make,
        "model": model,
        "model_year": model_year,
        "serial_number": serial_number,
        "hour_meter_reading": hour_meter,
        "weight_kg": weight_kg,
        "title_required": title_required,
        "reserve_price_cents": reserve_price,
        "sold_as_hours_unverified": hours_unverified,
        "lifecycle_status": "INTAKE",
        "title_status": "TITLE_PENDING",
        "lien_search_reference": None,
        "lienholder_name": None,
        "withdrawal_reason": None,
        "high_bid_cents": 0,
    })
    db.lots[lot["id"]] = lot
    recompute_consignment(consignment)
    return object_response(lot, 201)


@bp.get("/lots/<lot_id>")
@endpoint(*ANY_ROLE)
def get_lot(actor, lot_id):
    return object_response(fetch(db.lots, lot_id, "ERR_LOT_NOT_FOUND"))


@bp.get("/lots")
@endpoint(*ANY_ROLE)
def list_lots(actor):
    limit, offset = pagination()
    consignment_id = query_str("consignment_id")
    auction_id = query_str("auction_id")
    replacement_of = query_str("replacement_of_lot_id")
    lifecycle = query_enum("lifecycle_status", C.LOT_LIFECYCLE_STATUSES)
    title_status = query_enum("title_status", C.LOT_TITLE_STATUSES)
    rows = list(db.lots.values())
    if consignment_id is not None:
        rows = [l for l in rows if l["consignment_id"] == consignment_id]
    if auction_id is not None:
        rows = [l for l in rows if l["auction_id"] == auction_id]
    if replacement_of is not None:
        rows = [l for l in rows if l["replacement_of_lot_id"] == replacement_of]
    if lifecycle is not None:
        rows = [l for l in rows if l["lifecycle_status"] == lifecycle]
    if title_status is not None:
        rows = [l for l in rows if l["title_status"] == title_status]
    return collection_response(rows, limit, offset)


@bp.patch("/lots/<lot_id>")
@endpoint("Consignor")
def patch_lot(actor, lot_id):
    body = json_body()
    reserve_present = "reserve_price_cents" in body
    reserve_price = field_int(body, "reserve_price_cents", nullable=True,
                              min_value=1, max_value=1000000000, default=None)
    hours_present = "sold_as_hours_unverified" in body
    hours_unverified = field_bool(body, "sold_as_hours_unverified", default=None)
    weight_present = "weight_kg" in body
    weight_kg = field_int(body, "weight_kg", min_value=500, max_value=200000,
                          default=None)

    lot = fetch(db.lots, lot_id, "ERR_LOT_NOT_FOUND")
    if lot["lifecycle_status"] not in ("INTAKE", "INSPECTED"):
        raise invalid_state(
            "A lot may only be edited while INTAKE or INSPECTED.")
    if reserve_present:
        lot["reserve_price_cents"] = reserve_price
    if hours_present:
        lot["sold_as_hours_unverified"] = hours_unverified
    if weight_present:
        lot["weight_kg"] = weight_kg
    touch(lot)
    return object_response(lot)


@bp.post("/lots/<lot_id>/withdraw")
@endpoint("AuctionOperator")
def withdraw_lot(actor, lot_id):
    body = json_body()
    reason = field_str(body, "withdrawal_reason", required=True)
    lot = fetch(db.lots, lot_id, "ERR_LOT_NOT_FOUND")
    if lot["lifecycle_status"] not in ("INTAKE", "INSPECTED", "CATALOG_READY",
                                      "ASSIGNED"):
        raise invalid_state("This lot may no longer be withdrawn.")
    for sale in db.sales.values():
        if sale["lot_id"] == lot["id"]:
            raise invalid_state("A lot with a sale may not be withdrawn.")

    lot["lifecycle_status"] = "WITHDRAWN"
    lot["withdrawal_reason"] = reason
    for bid in db.bids.values():
        if bid["lot_id"] == lot["id"] and bid["status"] == "ACTIVE":
            bid["status"] = "LOSING"
    touch(lot)
    if lot["auction_id"]:
        auction = db.auctions.get(lot["auction_id"])
        if auction:
            recompute_auction(auction)
    recompute_consignment(db.consignments[lot["consignment_id"]])
    return object_response(lot)


@bp.post("/lots/<lot_id>/lien-search")
@endpoint("ComplianceOfficer")
def lien_search(actor, lot_id):
    body = json_body()
    reference = field_str(body, "lien_search_reference", required=True)
    lot = fetch(db.lots, lot_id, "ERR_LOT_NOT_FOUND")
    if lot["lifecycle_status"] == "WITHDRAWN":
        raise invalid_state("A withdrawn lot has no title workflow.")
    if lot["title_status"] != "TITLE_PENDING":
        raise invalid_state("A lien search may only be ordered while TITLE_PENDING.")
    lot["title_status"] = "LIEN_SEARCH_ORDERED"
    lot["lien_search_reference"] = reference
    touch(lot)
    return object_response(lot)


@bp.post("/lots/<lot_id>/lien-result")
@endpoint("ComplianceOfficer")
def lien_result(actor, lot_id):
    body = json_body()
    found = field_bool(body, "encumbrance_found", required=True)
    lienholder_name = field_str(body, "lienholder_name", nullable=True)
    lot = fetch(db.lots, lot_id, "ERR_LOT_NOT_FOUND")
    if lot["title_status"] != "LIEN_SEARCH_ORDERED":
        raise invalid_state("No lien search is outstanding for this lot.")
    if found:
        if not lienholder_name:
            raise invalid_state(
                "An encumbrance result requires a lienholder_name.")
        lot["title_status"] = "LIEN_ENCUMBERED"
        lot["lienholder_name"] = lienholder_name
    else:
        lot["title_status"] = "LIEN_CLEAR"
    touch(lot)
    return object_response(lot)


@bp.post("/lots/<lot_id>/lien-release")
@endpoint("ComplianceOfficer")
def lien_release(actor, lot_id):
    body = json_body()
    field_str(body, "release_document_ref", required=True)
    lot = fetch(db.lots, lot_id, "ERR_LOT_NOT_FOUND")
    if lot["title_status"] != "LIEN_ENCUMBERED":
        raise invalid_state("Only an encumbered lot may record a lien release.")
    lot["title_status"] = "LIEN_RELEASED"
    touch(lot)
    return object_response(lot)


@bp.post("/lots/<lot_id>/hammer")
@endpoint("AuctionOperator")
def hammer_lot(actor, lot_id):
    json_body()
    lot = fetch(db.lots, lot_id, "ERR_LOT_NOT_FOUND")
    if lot["lifecycle_status"] != "ASSIGNED":
        raise invalid_state("Only an ASSIGNED lot may be knocked down.")
    auction = db.auctions.get(lot["auction_id"]) if lot["auction_id"] else None
    if auction is None:
        raise ApiError("ERR_LOT_AUCTION_MISMATCH")
    if auction["status"] != "OPEN":
        raise ApiError("ERR_AUCTION_NOT_OPEN")
    if (lot["high_bid_cents"] or 0) <= 0:
        raise invalid_state("The lot has no live bid to knock down.")
    sale = knock_down(lot, auction)
    return object_response(sale, 201)
