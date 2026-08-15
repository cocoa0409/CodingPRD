"""Letter of intent endpoints (PRD 3.4, 3.5, 3.6).

Validation pipeline order (PRD 2.8): auth -> role -> existence -> schema ->
state preconditions ((a) transition validity, (b) domain gates, (c) OCC) ->
referential coherence -> fiscal gates (create only: qualified -> budget ->
deposit minimum).
"""
from decimal import Decimal

from flask import Blueprint

import db as dbmod
from errors import (
    ERR_ALREADY_ACKNOWLEDGED,
    ERR_BUDGET_EXCEEDED,
    ERR_BUYER_NOT_FOUND,
    ERR_BUYER_NOT_QUALIFIED,
    ERR_DEPOSIT_BELOW_MINIMUM,
    ERR_DUAL_AGENCY_DISCLOSURE_PENDING,
    ERR_INVALID_STATE,
    ERR_LISTING_NOT_ACTIVE,
    ERR_LISTING_NOT_FOUND,
    ERR_LOI_NOT_FOUND,
    ERR_STALE_VERSION,
    ERR_VALIDATION,
    raise_error,
)
from middleware import ALL_ROLES, require_roles
from response import success_object
from services.core import list_page, new_record, serialize, touch
from services.settlement import deposit_minimum
from util import new_escrow_ref
from validate import body, opt_bool, req_int, req_money, req_str

bp = Blueprint("lois", __name__)

NEGOTIATING = ("SUBMITTED", "COUNTERED")


def _get_loi(loi_id):
    rec = dbmod.db["lois"].get(loi_id)
    if rec is None:
        raise_error(ERR_LOI_NOT_FOUND, "LOI id does not exist")
    return rec


@bp.post("/api/lois")
@require_roles(["BuyerAgent"])
def create_loi():
    b = body()
    # Priority 3: body-referenced ids that are present must exist.
    if isinstance(b.get("listing_id"), str):
        if b["listing_id"] not in dbmod.db["listings"]:
            raise_error(ERR_LISTING_NOT_FOUND, "listing id does not exist")
    if isinstance(b.get("buyer_id"), str):
        if b["buyer_id"] not in dbmod.db["buyers"]:
            raise_error(ERR_BUYER_NOT_FOUND, "buyer id does not exist")
    # Priority 4: request schema.
    listing_id = req_str(b, "listing_id")
    buyer_id = req_str(b, "buyer_id")
    offer = req_money(b, "offer_price_usd")
    deposit = req_money(b, "deposit_amount_usd")
    dual = opt_bool(b, "dual_agency", default=False)
    listing = dbmod.db["listings"].get(listing_id)
    buyer = dbmod.db["buyers"].get(buyer_id)
    if listing is None:
        raise_error(ERR_LISTING_NOT_FOUND, "listing id does not exist")
    if buyer is None:
        raise_error(ERR_BUYER_NOT_FOUND, "buyer id does not exist")
    # Priority 5(b): submission requires an ACTIVE listing.
    if listing["status"] != "ACTIVE":
        raise_error(
            ERR_LISTING_NOT_ACTIVE,
            "LOI submission requires an ACTIVE listing",
        )
    # Priority 10: fiscal gates, in order.
    if buyer["qualification_status"] != "QUALIFIED":
        raise_error(ERR_BUYER_NOT_QUALIFIED, "buyer is not QUALIFIED")
    if offer > buyer["qualified_budget_usd"]:
        raise_error(
            ERR_BUDGET_EXCEEDED,
            "offer_price_usd exceeds the buyer's qualified budget",
        )
    if deposit < deposit_minimum(offer):
        raise_error(
            ERR_DEPOSIT_BELOW_MINIMUM,
            "deposit_amount_usd is below 5% of offer_price_usd",
        )
    rec = new_record(
        "lois",
        {
            "listing_id": listing_id,
            "buyer_id": buyer_id,
            "offer_price_usd": offer,
            "current_price_usd": offer,
            "deposit_amount_usd": deposit,
            "dual_agency": dual,
            "disclosure_status": "PENDING" if dual else "NOT_REQUIRED",
            "buyer_acked": False,
            "seller_acked": False,
            "status": "SUBMITTED",
        },
    )
    return success_object(serialize("lois", rec), 201)


@bp.get("/api/lois")
@require_roles(ALL_ROLES)
def list_lois():
    return list_page("lois", ["listing_id", "buyer_id", "status"])


@bp.get("/api/lois/<loi_id>")
@require_roles(ALL_ROLES)
def get_loi(loi_id):
    return success_object(serialize("lois", _get_loi(loi_id)))


@bp.post("/api/lois/<loi_id>/counter")
@require_roles(["ListingAgent", "BuyerAgent"])
def counter_loi(loi_id):
    loi = _get_loi(loi_id)
    b = body()
    new_price = req_money(b, "new_price_usd")
    expected = req_int(b, "expected_loi_version")
    if loi["status"] not in NEGOTIATING:
        raise_error(
            ERR_INVALID_STATE,
            "only a SUBMITTED or COUNTERED LOI can be countered",
        )
    if expected != loi["version"]:
        raise_error(
            ERR_STALE_VERSION,
            "expected_loi_version does not match the LOI's current version",
        )
    loi["current_price_usd"] = new_price
    loi["status"] = "COUNTERED" if loi["status"] == "SUBMITTED" else "SUBMITTED"
    touch(loi)
    return success_object(serialize("lois", loi))


@bp.post("/api/lois/<loi_id>/accept")
@require_roles(["ListingAgent"])
def accept_loi(loi_id):
    loi = _get_loi(loi_id)
    if loi["status"] not in NEGOTIATING:
        raise_error(
            ERR_INVALID_STATE,
            "only a SUBMITTED or COUNTERED LOI can be accepted",
        )
    listing = dbmod.db["listings"].get(loi["listing_id"])
    if listing is None or listing["status"] != "ACTIVE":
        raise_error(
            ERR_LISTING_NOT_ACTIVE,
            "acceptance requires the listing to be ACTIVE",
        )
    if loi["dual_agency"] and loi["disclosure_status"] != "FULLY_ACKED":
        raise_error(
            ERR_DUAL_AGENCY_DISCLOSURE_PENDING,
            "dual-agency disclosure is not FULLY_ACKED",
        )
    # Atomic acceptance cascade (PRD 3.6).
    loi["status"] = "ACCEPTED"
    touch(loi)
    tx = new_record(
        "transactions",
        {
            "loi_id": loi["id"],
            "listing_id": loi["listing_id"],
            "buyer_id": loi["buyer_id"],
            "agreed_price_usd": loi["current_price_usd"],
            "dual_agency": loi["dual_agency"],
            "status": "OPENED",
            "logbook_complete": False,
            "registration_docs_complete": False,
            "tax_planning_notes": None,
            "credits_total_usd": Decimal("0.00"),
            "commission_amount_usd": None,
            "settlement_buyer_due_usd": None,
            "settlement_seller_net_usd": None,
            "termination_reason": None,
        },
    )
    new_record(
        "escrows",
        {
            "transaction_id": tx["id"],
            "escrow_ref": new_escrow_ref(),
            "deposit_amount_usd": loi["deposit_amount_usd"],
            "status": "AWAITING_FUNDS",
            "funding_reference": None,
            "released_usd": Decimal("0.00"),
            "refunded_usd": Decimal("0.00"),
            "forfeited_usd": Decimal("0.00"),
        },
    )
    # Listing locks ACTIVE -> UNDER_CONTRACT and the auto-reject sweep runs.
    listing["status"] = "UNDER_CONTRACT"
    touch(listing)
    for other in dbmod.db["lois"].values():
        if (
            other["id"] != loi["id"]
            and other["listing_id"] == loi["listing_id"]
            and other["status"] in NEGOTIATING
        ):
            other["status"] = "REJECTED"
            touch(other)
    return success_object(serialize("lois", loi))


@bp.post("/api/lois/<loi_id>/withdraw")
@require_roles(["BuyerAgent"])
def withdraw_loi(loi_id):
    loi = _get_loi(loi_id)
    if loi["status"] not in NEGOTIATING:
        raise_error(
            ERR_INVALID_STATE,
            "only a SUBMITTED or COUNTERED LOI can be withdrawn",
        )
    loi["status"] = "WITHDRAWN"
    touch(loi)
    return success_object(serialize("lois", loi))


@bp.post("/api/lois/<loi_id>/disclosure/ack")
@require_roles(["BrokerPrincipal"])
def ack_disclosure(loi_id):
    loi = _get_loi(loi_id)
    b = body()
    party_raw = req_str(b, "party")
    party = party_raw.lower()
    if party not in ("buyer", "seller"):
        raise_error(
            ERR_VALIDATION, "party must select the buyer side or seller side"
        )
    if not loi["dual_agency"]:
        raise_error(
            ERR_ALREADY_ACKNOWLEDGED,
            "dual-agency disclosure is not required for this LOI",
        )
    flag = "buyer_acked" if party == "buyer" else "seller_acked"
    if loi[flag]:
        raise_error(
            ERR_ALREADY_ACKNOWLEDGED,
            f"the {party} side has already acknowledged the disclosure",
        )
    loi[flag] = True
    loi["disclosure_status"] = (
        "FULLY_ACKED"
        if loi["buyer_acked"] and loi["seller_acked"]
        else "PARTIAL"
    )
    touch(loi)
    return success_object(serialize("lois", loi))
