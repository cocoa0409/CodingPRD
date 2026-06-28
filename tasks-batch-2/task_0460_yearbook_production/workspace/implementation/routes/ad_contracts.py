"""AdContract routes: create, get, list, sign, place, void."""
from flask import Blueprint, request

from db import db, stamp_create, touch, sorted_by_created
from middleware import authenticate, authorize
from validators import (
    get_json_body, require, as_str, as_enum, as_number, parse_pagination, invalid,
)
from lookups import get_contract_path, get_ref
from response import success_object, success_array
import serializers as ser
from services.calculations import ad_pricing
from services.derive import recompute_yearbook
from errors import (
    ApiError, ERR_INVALID_STATE, ERR_AD_PAGE_NOT_ADS_SECTION, ERR_AD_PAGE_NOT_APPROVED,
)

bp = Blueprint("ad_contracts", __name__)

SIZES = {"FULL", "HALF", "QUARTER"}


@bp.route("/yearbooks/ad-contracts", methods=["POST"])
def create_contract():
    _, role = authenticate()
    authorize(role, {"SalesRep"})
    body = get_json_body()

    yearbook_id = as_str(require(body, "yearbook_id"), "yearbook_id")
    get_ref(db.yearbooks, yearbook_id)
    ladder_page_id = as_str(require(body, "ladder_page_id"), "ladder_page_id")
    get_ref(db.ladder_pages, ladder_page_id)
    sponsor_name = as_str(require(body, "sponsor_name"), "sponsor_name")
    size = as_enum(require(body, "size"), "size", SIZES)

    discount_pct = body.get("discount_pct", 0)
    if discount_pct is None:
        discount_pct = 0
    discount_pct = as_number(discount_pct, "discount_pct")
    if discount_pct < 0 or discount_pct > 0.5:
        invalid("discount_pct must be between 0 and 0.5 inclusive")

    list_price_cents, net_price_cents = ad_pricing(size, discount_pct)

    contract = {
        "yearbook_id": yearbook_id,
        "ladder_page_id": ladder_page_id,
        "sponsor_name": sponsor_name,
        "size": size,
        "list_price_cents": list_price_cents,
        "discount_pct": discount_pct,
        "net_price_cents": net_price_cents,
        "status": "DRAFT",
    }
    stamp_create(contract)
    db.ad_contracts[contract["id"]] = contract
    return success_object(ser.ad_contract(contract), 201)


@bp.route("/yearbooks/ad-contracts/<contract_id>", methods=["GET"])
def get_contract(contract_id):
    _, role = authenticate()
    authorize(role, {"Adviser", "SalesRep"})
    contract = get_contract_path(contract_id)
    return success_object(ser.ad_contract(contract), 200)


@bp.route("/yearbooks/ad-contracts", methods=["GET"])
def list_contracts():
    _, role = authenticate()
    authorize(role, {"Adviser", "SalesRep"})
    limit, offset = parse_pagination()
    yearbook_id = request.args.get("yearbook_id")
    ladder_page_id = request.args.get("ladder_page_id")
    records = list(db.ad_contracts.values())
    if yearbook_id is not None:
        records = [r for r in records if r["yearbook_id"] == yearbook_id]
    if ladder_page_id is not None:
        records = [r for r in records if r["ladder_page_id"] == ladder_page_id]
    records = sorted_by_created(records)
    total = len(records)
    page = records[offset:offset + limit]
    return success_array([ser.ad_contract(r) for r in page], limit, offset, total, 200)


@bp.route("/yearbooks/ad-contracts/<contract_id>/sign", methods=["POST"])
def sign_contract(contract_id):
    _, role = authenticate()
    authorize(role, {"SalesRep"})
    contract = get_contract_path(contract_id)
    if contract["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "contract is not in DRAFT")
    page = db.ladder_pages.get(contract["ladder_page_id"])
    if page is None or page["section"] != "ADS":
        raise ApiError(ERR_AD_PAGE_NOT_ADS_SECTION, 409,
                       "referenced page is not in the ADS section")
    contract["status"] = "SIGNED"
    touch(contract)
    yb = db.yearbooks.get(contract["yearbook_id"])
    if yb is not None:
        recompute_yearbook(yb)
    return success_object(ser.ad_contract(contract), 200)


@bp.route("/yearbooks/ad-contracts/<contract_id>/place", methods=["POST"])
def place_contract(contract_id):
    _, role = authenticate()
    authorize(role, {"SalesRep"})
    contract = get_contract_path(contract_id)
    if contract["status"] != "SIGNED":
        raise ApiError(ERR_INVALID_STATE, 409, "contract is not SIGNED")
    page = db.ladder_pages.get(contract["ladder_page_id"])
    if page is None or page["status"] != "APPROVED":
        raise ApiError(ERR_AD_PAGE_NOT_APPROVED, 409,
                       "referenced page is not APPROVED")
    contract["status"] = "PLACED"
    touch(contract)
    yb = db.yearbooks.get(contract["yearbook_id"])
    if yb is not None:
        recompute_yearbook(yb)
    return success_object(ser.ad_contract(contract), 200)


@bp.route("/yearbooks/ad-contracts/<contract_id>/void", methods=["POST"])
def void_contract(contract_id):
    _, role = authenticate()
    authorize(role, {"SalesRep"})
    contract = get_contract_path(contract_id)
    if contract["status"] not in ("DRAFT", "SIGNED"):
        raise ApiError(ERR_INVALID_STATE, 409, "contract cannot be voided")
    contract["status"] = "VOIDED"
    touch(contract)
    yb = db.yearbooks.get(contract["yearbook_id"])
    if yb is not None:
        recompute_yearbook(yb)
    return success_object(ser.ad_contract(contract), 200)
