from flask import Blueprint

from constants import ALL_ROLES, GIFT_TYPES
from db import store, stamp_new, bump, pub
from errors import raise_err
from middleware import authenticate
from response import success
from services import calc
from services.domain import get_or_404, list_response, pool_gate
from util import new_id, parse_body, req_str, req_int, req_enum

bp = Blueprint("gifts", __name__)


def _terminated_gate(fund):
    pool = store.pools.get(fund["pool_id"])
    if pool is not None and pool["pool_status"] == "TERMINATED":
        raise_err(
            "ERR_POOL_SUSPENDED",
            "Pool is TERMINATED and read-only; all mutations are rejected",
        )
    return pool


@bp.route("/endowment/gifts", methods=["POST"])
def create_gift():
    authenticate(["DevelopmentOfficer"])
    body = parse_body(required=True)
    fund_id = req_str(body, "fund_id")
    # donor_id is null only for system-created sweep reinvestments; client
    # gifts must carry a donor.
    donor_id = req_str(body, "donor_id")
    external_ref = req_str(body, "external_ref")
    gift_type = req_enum(body, "gift_type", GIFT_TYPES)
    amount = req_int(body, "amount_cents", minv=1)

    fund = get_or_404(store.funds, fund_id, "Fund")
    get_or_404(store.donors, donor_id, "Donor")

    if fund["fund_status"] == "TERMINATED":
        raise_err(
            "ERR_INVALID_STATE_TRANSITION",
            "Cannot record a gift against a TERMINATED fund",
        )
    _terminated_gate(fund)

    duplicate = any(
        g["fund_id"] == fund_id
        and g["external_ref"] == external_ref
        and g["gift_status"] != "CANCELLED"
        for g in store.gifts.values()
    )
    if duplicate:
        raise_err(
            "ERR_DUPLICATE_RECORD",
            f"A non-CANCELLED gift with external_ref {external_ref} already "
            "exists for this fund",
        )

    rec = {
        "id": new_id(),
        "fund_id": fund_id,
        "donor_id": donor_id,
        "external_ref": external_ref,
        "gift_type": gift_type,
        "amount_cents": amount,
        "gift_status": "PLEDGED",
        "received_quarter_index": None,
        "provisional_units_estimate_micro": None,
        "unitized_quarter_index": None,
        "units_purchased_micro": None,
        "source_payout_id": None,
        "version": 1,
    }
    stamp_new(rec)
    store.gifts[rec["id"]] = rec
    if gift_type == "CORPUS":
        fund["pledged_corpus_cents"] += amount
        bump(fund)
    return success(pub(rec), status=201)


@bp.route("/endowment/gifts", methods=["GET"])
def list_gifts():
    authenticate(ALL_ROLES)
    return list_response(
        store.gifts,
        [
            ("fund_id", "fund_id", "str"),
            ("donor_id", "donor_id", "str"),
            ("source_payout_id", "source_payout_id", "str"),
            ("gift_status", "gift_status", "str"),
            ("gift_type", "gift_type", "str"),
        ],
    )


@bp.route("/endowment/gifts/<gift_id>", methods=["GET"])
def get_gift(gift_id):
    authenticate(ALL_ROLES)
    return success(pub(get_or_404(store.gifts, gift_id, "GiftContribution")))


@bp.route("/endowment/gifts/<gift_id>/receive", methods=["POST"])
def receive_gift(gift_id):
    authenticate(["DevelopmentOfficer"])
    gift = get_or_404(store.gifts, gift_id, "GiftContribution")
    if gift["gift_status"] != "PLEDGED":
        raise_err(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot receive a gift in state {gift['gift_status']}",
        )
    fund = store.funds.get(gift["fund_id"])
    if fund is None or fund["fund_status"] != "ACTIVE":
        raise_err(
            "ERR_INVALID_STATE_TRANSITION",
            "Gift receive requires the fund to be ACTIVE",
        )
    pool = store.pools.get(fund["pool_id"])
    pool_gate(pool, "gift_receive")

    gift["gift_status"] = "RECEIVED"
    gift["received_quarter_index"] = pool["current_quarter_index"] + 1
    gift["provisional_units_estimate_micro"] = calc.units_for_amount(
        gift["amount_cents"], pool["current_unit_price_millicents"]
    )
    bump(gift)
    if gift.get("donor_id"):
        donor = store.donors.get(gift["donor_id"])
        if donor is not None:
            donor["total_contributed_cents"] += gift["amount_cents"]
            bump(donor)
    return success(pub(gift))


@bp.route("/endowment/gifts/<gift_id>/cancel", methods=["POST"])
def cancel_gift(gift_id):
    authenticate(["DevelopmentOfficer"])
    gift = get_or_404(store.gifts, gift_id, "GiftContribution")
    if gift["gift_status"] != "PLEDGED":
        raise_err(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot cancel a gift in state {gift['gift_status']}",
        )
    fund = store.funds.get(gift["fund_id"])
    _terminated_gate(fund)
    gift["gift_status"] = "CANCELLED"
    bump(gift)
    if gift["gift_type"] == "CORPUS" and fund is not None:
        fund["pledged_corpus_cents"] -= gift["amount_cents"]
        bump(fund)
    return success(pub(gift))


@bp.route("/endowment/gifts/<gift_id>/rescind", methods=["POST"])
def rescind_gift(gift_id):
    authenticate(["DevelopmentOfficer"])
    gift = get_or_404(store.gifts, gift_id, "GiftContribution")
    if gift["gift_status"] != "RECEIVED":
        raise_err(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot rescind a gift in state {gift['gift_status']}",
        )
    fund = store.funds.get(gift["fund_id"])
    _terminated_gate(fund)
    gift["gift_status"] = "RETURNED"
    bump(gift)
    if gift["gift_type"] == "CORPUS" and fund is not None:
        fund["pledged_corpus_cents"] -= gift["amount_cents"]
        bump(fund)
    if gift.get("donor_id"):
        donor = store.donors.get(gift["donor_id"])
        if donor is not None:
            donor["total_contributed_cents"] -= gift["amount_cents"]
            bump(donor)
    return success(pub(gift))
