"""SettlementOffer endpoints (PRD §3.6)."""
from __future__ import annotations

from flask import Blueprint, request

from config import OFFER_PARTIES, ROLE_ATTORNEY, ROLE_MANAGING_PARTNER, ROLE_PARALEGAL
from db import store
from errors import raise_error
from middleware import require_auth
from response import list_success, success
from routes._helpers import (
    get_json_body,
    get_pagination_args,
    paginate,
    require_field,
)
from services.case_engine import (
    assert_case_not_closed,
    check_version_match,
    find_active_demand_letter,
    get_case_or_404,
    has_any_defendant_offer,
    now,
    touch,
)
from services.serializers import settlement_offer_to_dict
from utils import new_uuid, parse_iso_datetime


bp = Blueprint("settlement_offers", __name__)

ALL_ROLES = [ROLE_PARALEGAL, ROLE_ATTORNEY, ROLE_MANAGING_PARTNER]


def _get_offer_or_404(cid: str, oid: str) -> dict:
    get_case_or_404(cid)
    offer = store.settlement_offers.get(oid)
    if not offer or offer["case_id"] != cid:
        raise_error("ERR_NOT_FOUND", f"SettlementOffer {oid} not found on case {cid}.")
    return offer


@bp.post("/pi-cases/<cid>/settlement-offers")
@require_auth([ROLE_ATTORNEY])
def create_offer(cid):
    body = get_json_body()
    case_row = get_case_or_404(cid)
    assert_case_not_closed(case_row)

    offer_party = require_field(body, "offer_party")
    if offer_party not in OFFER_PARTIES:
        raise_error("ERR_VALIDATION", f"offer_party must be one of {sorted(OFFER_PARTIES)}.")

    if "amount_cents" not in body:
        raise_error("ERR_VALIDATION", "amount_cents is required.")
    amount = body["amount_cents"]
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        raise_error("ERR_VALIDATION", "amount_cents must be a positive integer.")

    expires_raw = require_field(body, "expires_at")
    expires = parse_iso_datetime(expires_raw)
    if expires is None:
        raise_error("ERR_VALIDATION", "expires_at must be a valid ISO 8601 timestamp.")

    predecessor_id = body.get("predecessor_offer_id")
    is_counter = predecessor_id is not None

    if is_counter:
        predecessor = store.settlement_offers.get(predecessor_id)
        if not predecessor:
            raise_error("ERR_REFERENCE_NOT_FOUND", f"Predecessor offer {predecessor_id} not found.")
        if predecessor["case_id"] != cid:
            raise_error(
                "ERR_OFFER_PARTY_INVALID",
                "Predecessor offer is on a different case.",
            )
        if predecessor["status"] != "PENDING":
            raise_error("ERR_OFFER_NOT_PENDING", "Predecessor offer is not PENDING.")
        if predecessor["expires_at"] <= now():
            raise_error("ERR_OFFER_NOT_PENDING", "Predecessor offer has expired.")
        if predecessor["offer_party"] == offer_party:
            raise_error(
                "ERR_OFFER_PARTY_INVALID",
                "Counter offer party must differ from predecessor's party.",
            )
        # Case must be NEGOTIATING or LITIGATION for a counter offer.
        if case_row["status"] not in ("NEGOTIATING", "LITIGATION"):
            raise_error(
                "ERR_INVALID_STATE",
                f"Counter offers require Case in NEGOTIATING/LITIGATION (was {case_row['status']}).",
            )
        round_number = int(predecessor["round_number"]) + 1
    else:
        # Round-1 offer: case must be DEMAND_SENT (first defendant offer) or
        # NEGOTIATING (additional first-defendant scenario doesn't really
        # exist in this scaffold; first defendant offer is the trigger).
        if case_row["status"] not in ("DEMAND_SENT", "NEGOTIATING", "LITIGATION"):
            raise_error(
                "ERR_INVALID_STATE",
                f"Case must be DEMAND_SENT to begin offers (was {case_row['status']}).",
            )
        round_number = 1

    with store.lock:
        row = {
            "id": new_uuid(),
            "case_id": cid,
            "created_at": now(),
            "updated_at": now(),
            "version": 1,
            "predecessor_offer_id": predecessor_id if is_counter else None,
            "offer_party": offer_party,
            "amount_cents": int(amount),
            "status": "PENDING",
            "expires_at": expires,
            "round_number": round_number,
        }
        store.settlement_offers[row["id"]] = row

        # Counter offer: flip predecessor PENDING → COUNTERED.
        if is_counter:
            predecessor = store.settlement_offers[predecessor_id]
            predecessor["status"] = "COUNTERED"
            touch(predecessor)

        # First DEFENDANT offer cascades DemandLetter SENT→RESPONDED and
        # Case DEMAND_SENT→NEGOTIATING.
        if (
            not is_counter
            and offer_party == "DEFENDANT"
            and case_row["status"] == "DEMAND_SENT"
        ):
            active_letter = find_active_demand_letter(cid)
            if active_letter and active_letter["status"] == "SENT":
                active_letter["status"] = "RESPONDED"
                touch(active_letter)
            case_row["status"] = "NEGOTIATING"
            touch(case_row)

    return success(settlement_offer_to_dict(row), 201)


@bp.patch("/pi-cases/<cid>/settlement-offers/<oid>")
@require_auth([ROLE_ATTORNEY])
def patch_offer(cid, oid):
    body = get_json_body()
    case_row = get_case_or_404(cid)
    offer = _get_offer_or_404(cid, oid)
    assert_case_not_closed(case_row)

    if "status" not in body:
        raise_error("ERR_VALIDATION", "status is required.")
    new_status = body["status"]
    if new_status not in ("ACCEPTED", "REJECTED"):
        raise_error("ERR_VALIDATION", "status must be ACCEPTED or REJECTED.")

    check_version_match(offer, body.get("version"))

    if offer["status"] != "PENDING":
        raise_error("ERR_OFFER_NOT_PENDING", f"Offer is not PENDING (was {offer['status']}).")
    if offer["expires_at"] <= now():
        raise_error("ERR_OFFER_NOT_PENDING", "Offer has expired.")

    if new_status == "ACCEPTED":
        if case_row["status"] not in ("NEGOTIATING", "LITIGATION"):
            raise_error(
                "ERR_CASE_INVALID_STATE",
                f"Case must be NEGOTIATING or LITIGATION (was {case_row['status']}).",
            )

    with store.lock:
        # Re-check under lock for races.
        if offer["status"] != "PENDING":
            raise_error("ERR_OFFER_NOT_PENDING", "Offer is no longer PENDING.")

        if new_status == "ACCEPTED":
            offer["status"] = "ACCEPTED"
            touch(offer)
            case_row["gross_settlement_cents"] = int(offer["amount_cents"])
            # Cascade: all OTHER PENDING offers on the case → WITHDRAWN.
            for o in store.settlement_offers.values():
                if (
                    o["case_id"] == cid
                    and o["id"] != offer["id"]
                    and o["status"] == "PENDING"
                ):
                    o["status"] = "WITHDRAWN"
                    touch(o)
            case_row["status"] = "SETTLED"
            touch(case_row)
        else:  # REJECTED
            offer["status"] = "REJECTED"
            touch(offer)

    return success(settlement_offer_to_dict(offer), 200)


@bp.get("/pi-cases/<cid>/settlement-offers")
@require_auth(ALL_ROLES)
def list_offers(cid):
    get_case_or_404(cid)
    limit, offset = get_pagination_args()
    status_filter = request.args.get("status")

    rows = [o for o in store.settlement_offers.values() if o["case_id"] == cid]
    if status_filter:
        rows = [o for o in rows if o["status"] == status_filter]
    # PRD: ordered by round_number then created_at.
    rows.sort(key=lambda r: (r["round_number"], r["created_at"]))
    page, total = paginate(rows, limit, offset)
    return list_success([settlement_offer_to_dict(r) for r in page], limit, offset, total)
