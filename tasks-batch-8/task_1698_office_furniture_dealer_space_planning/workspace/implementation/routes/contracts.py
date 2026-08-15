"""PricingContract routes: draft, activate (SoD + pricing compliance), terminate,
OCC-guarded amend, and the supersede cascade."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_INVALID_DATE_RANGE,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    ERR_SOD_VIOLATION,
    ERR_CONTRACT_PRICING_VIOLATION,
)
from middleware import ALL_ROLES
from response import success_object
from routes.helpers import authorize, list_response, get_response
from serialize import public
from services.core import get_or_404, new_entity, touch
from services.pricing import MAX_DISCOUNT_PCT
from util import parse_date
from validate import body_dict, req_str, req_enum, req_int, opt_int, req_list, is_int

bp = Blueprint("contracts", __name__)

CONTRACT_TYPES = {"STATE", "COOP", "NEGOTIATED"}
CATEGORIES = {"SEATING", "SYSTEMS", "CASEGOODS", "TABLES", "STORAGE"}


def validate_tiers(tiers):
    """pricing_tiers shape (priority 8a): array of {category, min_qty, discount_pct}."""
    for t in tiers:
        if not isinstance(t, dict):
            raise_error(ERR_INVALID_REQUEST, "each pricing_tiers entry must be an object")
        cat = t.get("category")
        if not isinstance(cat, str) or cat not in CATEGORIES:
            raise_error(ERR_INVALID_REQUEST, f"pricing_tiers category must be one of {sorted(CATEGORIES)}")
        if not is_int(t.get("min_qty")) or t["min_qty"] < 0:
            raise_error(ERR_INVALID_REQUEST, "pricing_tiers min_qty must be an integer >= 0")
        if not is_int(t.get("discount_pct")) or t["discount_pct"] < 0:
            raise_error(ERR_INVALID_REQUEST, "pricing_tiers discount_pct must be an integer >= 0")
    return tiers


def validate_window(effective_from, effective_to):
    """Date format is 8a; ordering (from <= to) is 8b."""
    from_d = parse_date(effective_from)
    to_d = parse_date(effective_to)
    if from_d is None or to_d is None:
        raise_error(ERR_INVALID_REQUEST, "effective_from / effective_to must be YYYY-MM-DD dates")
    if from_d > to_d:
        raise_error(ERR_INVALID_DATE_RANGE, "effective_from must be on or before effective_to")
    return effective_from, effective_to


@bp.route("/api/pricing-contracts", methods=["POST"])
def create_contract():
    caller = authorize(["AccountExecutive"])
    body = body_dict()
    customer_id = req_str(body, "customer_id")
    contract_type = req_enum(body, "contract_type", CONTRACT_TYPES)
    tiers = validate_tiers(req_list(body, "pricing_tiers"))
    default_discount_pct = req_int(body, "default_discount_pct", minv=0)
    effective_from = req_str(body, "effective_from")
    effective_to = req_str(body, "effective_to")
    labor_rate = opt_int(body, "labor_rate_cents_per_hour", minv=0)
    multiplier_bp = opt_int(body, "after_hours_multiplier_bp", minv=0)
    supersedes_contract_id = body.get("supersedes_contract_id")
    if supersedes_contract_id is not None and not isinstance(supersedes_contract_id, str):
        raise_error(ERR_INVALID_REQUEST, "supersedes_contract_id must be a string")
    # priority 3: FK existence
    get_or_404("customers", customer_id)
    if supersedes_contract_id is not None:
        get_or_404("pricing_contracts", supersedes_contract_id)
    # priority 8b: window ordering
    validate_window(effective_from, effective_to)
    contract = new_entity("pricing_contracts", {
        "customer_id": customer_id,
        "contract_type": contract_type,
        "pricing_tiers": tiers,
        "default_discount_pct": default_discount_pct,
        "labor_rate_cents_per_hour": labor_rate,
        "after_hours_multiplier_bp": multiplier_bp,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "supersedes_contract_id": supersedes_contract_id,
        "created_by_user_id": caller.user_id,
        "activated_by_user_id": None,
        "status": "DRAFT",
    })
    return success_object(public(contract), status=201)


@bp.route("/api/pricing-contracts", methods=["GET"])
def list_contracts():
    authorize(ALL_ROLES)
    return list_response("pricing_contracts", ["customer_id", "status", "supersedes_contract_id"])


@bp.route("/api/pricing-contracts/<contract_id>", methods=["GET"])
def get_contract(contract_id):
    authorize(ALL_ROLES)
    return get_response("pricing_contracts", contract_id)


@bp.route("/api/pricing-contracts/<contract_id>/activate", methods=["POST"])
def activate_contract(contract_id):
    caller = authorize(["ContractsOfficer"])
    contract = get_or_404("pricing_contracts", contract_id)
    # priority 4: transition exists only from DRAFT
    if contract["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, f"cannot activate a contract in status {contract['status']}")
    # priority 5a: segregation of duties
    if caller.user_id == contract["created_by_user_id"]:
        raise_error(ERR_SOD_VIOLATION, "the contract activator must differ from its creator")
    # priority 8b: window ordering
    validate_window(contract["effective_from"], contract["effective_to"])
    # priority 9: pricing compliance (tiers and default at most MAX_DISCOUNT_PCT)
    for t in contract.get("pricing_tiers") or []:
        if int(t.get("discount_pct", 0)) > MAX_DISCOUNT_PCT:
            raise_error(ERR_CONTRACT_PRICING_VIOLATION,
                        f"tier discount_pct {t['discount_pct']} exceeds the {MAX_DISCOUNT_PCT}% maximum")
    if contract["default_discount_pct"] > MAX_DISCOUNT_PCT:
        raise_error(ERR_CONTRACT_PRICING_VIOLATION,
                    f"default_discount_pct {contract['default_discount_pct']} exceeds the {MAX_DISCOUNT_PCT}% maximum")
    contract["status"] = "ACTIVE"
    contract["activated_by_user_id"] = caller.user_id
    touch(contract)
    # supersede cascade: ACTIVE predecessor -> SUPERSEDED
    pred_id = contract.get("supersedes_contract_id")
    if pred_id:
        predecessor = db["pricing_contracts"].get(pred_id)
        if predecessor is not None and predecessor["status"] == "ACTIVE":
            predecessor["status"] = "SUPERSEDED"
            touch(predecessor)
    return success_object(public(contract))


@bp.route("/api/pricing-contracts/<contract_id>/terminate", methods=["POST"])
def terminate_contract(contract_id):
    authorize(["ContractsOfficer"])
    contract = get_or_404("pricing_contracts", contract_id)
    if contract["status"] not in ("DRAFT", "ACTIVE"):
        raise_error(ERR_INVALID_STATE, f"cannot terminate a contract in status {contract['status']}")
    contract["status"] = "TERMINATED"
    touch(contract)
    return success_object(public(contract))


@bp.route("/api/pricing-contracts/<contract_id>/amend", methods=["POST"])
def amend_contract(contract_id):
    caller = authorize(["ContractsOfficer"])
    contract = get_or_404("pricing_contracts", contract_id)
    # priority 4: amendment against a terminal contract does not exist
    if contract["status"] not in ("DRAFT", "ACTIVE"):
        raise_error(ERR_INVALID_STATE, f"cannot amend a contract in status {contract['status']}")
    body = body_dict()
    # OCC (concurrency rule contract-amend-stale-version)
    expected = body.get("expected_contract_version")
    if not is_int(expected):
        raise_error(ERR_INVALID_REQUEST, "field 'expected_contract_version' is required and must be an integer")
    if expected != contract["version"]:
        raise_error(ERR_STALE_VERSION,
                    f"expected_contract_version {expected} does not match current version {contract['version']}")
    # priority 8a/8b on the replacement values
    tiers = contract["pricing_tiers"]
    if "pricing_tiers" in body and body["pricing_tiers"] is not None:
        tiers = validate_tiers(req_list(body, "pricing_tiers"))
    default_discount_pct = contract["default_discount_pct"]
    if "default_discount_pct" in body and body["default_discount_pct"] is not None:
        default_discount_pct = req_int(body, "default_discount_pct", minv=0)
    labor_rate = contract["labor_rate_cents_per_hour"]
    if "labor_rate_cents_per_hour" in body:
        labor_rate = opt_int(body, "labor_rate_cents_per_hour", minv=0)
    multiplier_bp = contract["after_hours_multiplier_bp"]
    if "after_hours_multiplier_bp" in body:
        multiplier_bp = opt_int(body, "after_hours_multiplier_bp", minv=0)
    effective_from = contract["effective_from"]
    if "effective_from" in body and body["effective_from"] is not None:
        effective_from = req_str(body, "effective_from")
    effective_to = contract["effective_to"]
    if "effective_to" in body and body["effective_to"] is not None:
        effective_to = req_str(body, "effective_to")
    validate_window(effective_from, effective_to)
    # the amended contract's version advances (fork prevention)
    touch(contract)
    successor = new_entity("pricing_contracts", {
        "customer_id": contract["customer_id"],
        "contract_type": contract["contract_type"],
        "pricing_tiers": tiers,
        "default_discount_pct": default_discount_pct,
        "labor_rate_cents_per_hour": labor_rate,
        "after_hours_multiplier_bp": multiplier_bp,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "supersedes_contract_id": contract["id"],
        "created_by_user_id": caller.user_id,
        "activated_by_user_id": None,
        "status": "DRAFT",
    })
    return success_object(public(successor), status=201)
