"""VendorContract endpoints (propose/counter negotiation)."""
from flask import Blueprint, request

from db import db
from errors import validation, ApiError, ERR_CONTRACT_INVALID_STATE
from middleware import require_roles, require_read
from response import success_object, success_list
from serializers import contract_view
from services.core import make_record, touch, require_exists, get_pagination, paginate
from util import parse_date

bp = Blueprint("contracts", __name__)

VENDOR_KINDS = {"HANGAR", "FUEL"}
UNITS = {"MONTH", "GALLON"}


def _check_rate(value, field="rate_cents_per_unit"):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise validation(f"{field} must be a non-negative integer")


@bp.route("/contracts", methods=["POST"])
def create_contract():
    require_roles("ContractsManager")
    body = request.get_json(silent=True) or {}

    aircraft_id = body.get("aircraft_id")
    if aircraft_id is not None:
        require_exists(db.aircraft, aircraft_id, "aircraft_id does not resolve")
    if not isinstance(aircraft_id, str) or not aircraft_id:
        raise validation("aircraft_id is required")

    vendor_kind = body.get("vendor_kind")
    if vendor_kind not in VENDOR_KINDS:
        raise validation("vendor_kind must be HANGAR or FUEL")

    vendor_name = body.get("vendor_name")
    if not isinstance(vendor_name, str) or not vendor_name:
        raise validation("vendor_name is required")

    unit = body.get("unit")
    if unit not in UNITS:
        raise validation("unit must be MONTH or GALLON")

    rate = body.get("rate_cents_per_unit")
    _check_rate(rate)

    term_start = body.get("term_start")
    term_end = body.get("term_end")
    ts = parse_date(term_start, "term_start")
    te = parse_date(term_end, "term_end")
    if not ts < te:
        raise validation("term_start must be strictly earlier than term_end")

    rec = make_record({
        "aircraft_id": aircraft_id,
        "vendor_kind": vendor_kind,
        "vendor_name": vendor_name,
        "unit": unit,
        "rate_cents_per_unit": rate,
        "term_start": term_start,
        "term_end": term_end,
        "status": "DRAFT",
    })
    db.contracts[rec["id"]] = rec
    return success_object(contract_view(rec), 201)


@bp.route("/contracts/<contract_id>", methods=["GET"])
def get_contract(contract_id):
    require_read()
    rec = require_exists(db.contracts, contract_id)
    return success_object(contract_view(rec))


@bp.route("/aircraft/<aircraft_id>/contracts", methods=["GET"])
def list_contracts(aircraft_id):
    require_read()
    require_exists(db.aircraft, aircraft_id)
    limit, offset = get_pagination(request.args)
    records = [c for c in db.contracts.values() if c["aircraft_id"] == aircraft_id]
    page, total = paginate(records, limit, offset)
    return success_list([contract_view(r) for r in page], limit, offset, total)


@bp.route("/contracts/<contract_id>/propose", methods=["POST"])
def propose_contract(contract_id):
    require_roles("ContractsManager")
    rec = require_exists(db.contracts, contract_id)
    body = request.get_json(silent=True) or {}
    if "rate_cents_per_unit" in body and body["rate_cents_per_unit"] is not None:
        _check_rate(body["rate_cents_per_unit"])

    if rec["status"] not in ("DRAFT", "COUNTERED"):
        raise ApiError(ERR_CONTRACT_INVALID_STATE,
                       "Contract must be in DRAFT or COUNTERED", 409)

    if "rate_cents_per_unit" in body and body["rate_cents_per_unit"] is not None:
        rec["rate_cents_per_unit"] = body["rate_cents_per_unit"]
    rec["status"] = "PROPOSED"
    touch(rec, bump_version=True)
    return success_object(contract_view(rec))


@bp.route("/contracts/<contract_id>/counter", methods=["POST"])
def counter_contract(contract_id):
    require_roles("ContractsManager")
    rec = require_exists(db.contracts, contract_id)
    body = request.get_json(silent=True) or {}
    rate = body.get("rate_cents_per_unit")
    _check_rate(rate)  # required on counter

    if rec["status"] != "PROPOSED":
        raise ApiError(ERR_CONTRACT_INVALID_STATE, "Contract must be in PROPOSED", 409)

    rec["rate_cents_per_unit"] = rate
    rec["status"] = "COUNTERED"
    touch(rec, bump_version=True)
    return success_object(contract_view(rec))


@bp.route("/contracts/<contract_id>/execute", methods=["POST"])
def execute_contract(contract_id):
    require_roles("AccountExecutive")
    rec = require_exists(db.contracts, contract_id)
    if rec["status"] not in ("PROPOSED", "COUNTERED"):
        raise ApiError(ERR_CONTRACT_INVALID_STATE,
                       "Contract must be in PROPOSED or COUNTERED", 409)
    rec["status"] = "EXECUTED"
    touch(rec, bump_version=True)
    return success_object(contract_view(rec))


@bp.route("/contracts/<contract_id>/expire", methods=["POST"])
def expire_contract(contract_id):
    require_roles("ContractsManager")
    rec = require_exists(db.contracts, contract_id)
    if rec["status"] not in ("PROPOSED", "COUNTERED"):
        raise ApiError(ERR_CONTRACT_INVALID_STATE,
                       "Contract must be in PROPOSED or COUNTERED", 409)
    rec["status"] = "EXPIRED"
    touch(rec, bump_version=True)
    return success_object(contract_view(rec))
