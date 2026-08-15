"""Escrow ledger entries: record, clear, void, release, refund, forfeit."""
from flask import Blueprint
from db import db, clock, parse_iso
from errors import (err_invalid_state, err_invalid_request,
                    err_escrow_not_cleared, err_deposit_excessive,
                    err_deposit_insufficient)
from middleware import (get_caller, require_roles, get_json_body, require_fields,
                        check_enum, check_int, check_str)
from response import success_object, success_list
from services.calculations import required_deposit_cents, provisional_interest, MAX_DEPOSIT_MULTIPLE
from services.common import new_entity, touch, get_or_404, serialize_escrow_entry

bp = Blueprint("escrow", __name__)

ENTRY_TYPES = {"DEPOSIT", "RELEASE", "REFUND", "FORFEIT"}


@bp.route("/yacht/offers/<oid>/escrow-entries", methods=["POST"])
def create_entry(oid):
    caller = get_caller()
    require_roles(caller, ["EscrowOfficer"])
    offer = get_or_404(db.offers, oid, "Offer")
    body = get_json_body()
    require_fields(body, ["entry_type", "amount_cents", "value_date"])
    check_enum(body, "entry_type", ENTRY_TYPES)
    check_int(body, "amount_cents", min_v=1)
    check_str(body, "value_date")
    try:
        parse_iso(body["value_date"])
    except (ValueError, TypeError):
        raise err_invalid_request("value_date must be an ISO-8601 datetime")

    if body["entry_type"] == "DEPOSIT":
        required = required_deposit_cents(offer["offer_price_cents"], offer["deposit_pct_basis"])
        # Priority 7: anti-structuring ceiling BEFORE sufficiency floor (priority 16)
        if body["amount_cents"] > MAX_DEPOSIT_MULTIPLE * required:
            raise err_deposit_excessive()
        if body["amount_cents"] < required:
            raise err_deposit_insufficient()

    e = new_entity()
    e["offer_id"] = offer["id"]
    e["entry_type"] = body["entry_type"]
    e["amount_cents"] = body["amount_cents"]
    e["status"] = "PENDING"
    e["value_date"] = body["value_date"]
    e["provisional_interest_cents"] = 0
    db.escrow_entries[e["id"]] = e
    return success_object(serialize_escrow_entry(e), 201)


@bp.route("/yacht/offers/<oid>/escrow-entries", methods=["GET"])
def list_entries(oid):
    caller = get_caller()
    require_roles(caller, ["PlatformAdmin", "ListingAgent", "SellingAgent",
                           "ClosingOfficer", "EscrowOfficer"])
    offer = get_or_404(db.offers, oid, "Offer")
    items = sorted([e for e in db.escrow_entries.values() if e["offer_id"] == offer["id"]],
                   key=lambda x: x["created_at"])
    return success_list([serialize_escrow_entry(e) for e in items],
                        len(items) or 10, 0, len(items))


def _get_entry(eid):
    return get_or_404(db.escrow_entries, eid, "EscrowLedgerEntry")


@bp.route("/yacht/escrow-entries/<eid>/clear", methods=["POST"])
def clear_entry(eid):
    caller = get_caller()
    require_roles(caller, ["EscrowOfficer"])
    e = _get_entry(eid)
    get_json_body()
    if e["status"] != "PENDING":
        raise err_invalid_state("Entry must be PENDING to clear")
    if e["entry_type"] != "DEPOSIT":
        raise err_invalid_state("Only DEPOSIT entries may be cleared")
    if clock.now() < parse_iso(e["value_date"]):
        raise err_invalid_state("value_date has not been reached")
    e["status"] = "CLEARED"
    # Provisional interest accrual (ACT/360 at PROV_RATE), per entry
    e["provisional_interest_cents"] = provisional_interest(e["amount_cents"], e["value_date"])
    touch(e)
    return success_object(serialize_escrow_entry(e))


@bp.route("/yacht/escrow-entries/<eid>/void", methods=["POST"])
def void_entry(eid):
    caller = get_caller()
    require_roles(caller, ["EscrowOfficer"])
    e = _get_entry(eid)
    get_json_body()
    if e["status"] != "PENDING":
        raise err_invalid_state("Entry must be PENDING to void")
    if clock.now() >= parse_iso(e["value_date"]):
        raise err_invalid_state("Entry is no longer voidable at/after value_date")
    e["status"] = "VOIDED"
    touch(e)
    return success_object(serialize_escrow_entry(e))


@bp.route("/yacht/escrow-entries/<eid>/release", methods=["POST"])
def release_entry(eid):
    caller = get_caller()
    require_roles(caller, ["ClosingOfficer"])
    e = _get_entry(eid)
    get_json_body()
    # Priority 17: entry must be CLEARED
    if e["status"] != "CLEARED":
        raise err_escrow_not_cleared()
    offer = db.offers.get(e["offer_id"])
    if offer is None or offer["status"] != "ACCEPTED":
        raise err_invalid_state("Parent offer must be ACCEPTED")
    stmt = next((s for s in db.statements.values() if s["offer_id"] == offer["id"]
                 and s["status"] != "VOIDED"), None)
    if stmt is None or stmt["status"] != "APPROVED":
        raise err_invalid_state("Closing statement must be APPROVED")
    e["status"] = "DISBURSED"
    touch(e)
    return success_object(serialize_escrow_entry(e))


@bp.route("/yacht/escrow-entries/<eid>/refund", methods=["POST"])
def refund_entry(eid):
    caller = get_caller()
    require_roles(caller, ["EscrowOfficer"])
    e = _get_entry(eid)
    get_json_body()
    if e["status"] != "CLEARED":
        raise err_escrow_not_cleared()
    offer = db.offers.get(e["offer_id"])
    if offer is None or offer["status"] not in ("FAILED", "WITHDRAWN", "EXPIRED", "REJECTED"):
        raise err_invalid_state("Parent offer must be FAILED, WITHDRAWN, EXPIRED, or REJECTED")
    e["status"] = "REFUNDED"
    touch(e)
    return success_object(serialize_escrow_entry(e))


@bp.route("/yacht/escrow-entries/<eid>/forfeit", methods=["POST"])
def forfeit_entry(eid):
    caller = get_caller()
    require_roles(caller, ["ListingAgent"])
    e = _get_entry(eid)
    get_json_body()
    if e["status"] != "CLEARED":
        raise err_escrow_not_cleared()
    offer = db.offers.get(e["offer_id"])
    if offer is None or offer["status"] != "FAILED":
        raise err_invalid_state("Parent offer must be FAILED")
    # Every contingency on the offer must be SATISFIED or WAIVED
    for c in db.contingencies.values():
        if c["offer_id"] == offer["id"] and c["status"] not in ("SATISFIED", "WAIVED"):
            raise err_invalid_state("A live contingency blocks forfeiture")
    e["status"] = "FORFEITED"
    touch(e)
    return success_object(serialize_escrow_entry(e))
