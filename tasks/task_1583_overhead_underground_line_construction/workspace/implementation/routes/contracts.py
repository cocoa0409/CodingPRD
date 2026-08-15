"""Contract endpoints: create, get, transition, bid-item and work-package
creation under a contract (PRD 3.1, 3.2; Contract state machine)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_BID_ITEMS_LOCKED,
    ERR_SAFETY_EVENT_OPEN, ERR_OPEN_WORK_PACKAGES, ERR_FORBIDDEN,
)
from middleware import authorized, ALL_ROLES
from response import success_object
from routes.helpers import serialize
from services.core import new_record, touch
from util import parse_datetime
from validate import (
    get_body, req_str, req_num, opt_num, req_enum,
    req_datetime, require_path_resource,
)

bp = Blueprint("contracts", __name__)

UNITS = {"EACH", "LF", "CY", "HR"}


@bp.post("/contracts")
def create_contract():
    authorized(["CONTRACTOR_PM"])
    body = get_body()
    utility_name = req_str(body, "utility_name")
    contract_number = req_str(body, "contract_number")
    effective_start = req_datetime(body, "effective_start")
    effective_end = req_datetime(body, "effective_end")
    retainage_pct = opt_num(body, "retainage_pct", 0.10)
    overrun_threshold_pct = opt_num(body, "overrun_threshold_pct", 1.10)
    quantity_cap_pct = opt_num(body, "quantity_cap_pct", 1.25)
    if not (0 <= retainage_pct < 1):
        raise_error(ERR_INVALID_REQUEST, "retainage_pct must satisfy 0 <= retainage_pct < 1")
    if parse_datetime(effective_end) < parse_datetime(effective_start):
        raise_error(ERR_INVALID_REQUEST, "effective_end must be >= effective_start")
    # contract_number unique across all contracts
    for c in db["contracts"].values():
        if c["contract_number"] == contract_number:
            raise_error(ERR_INVALID_REQUEST,
                        f"contract_number already exists: {contract_number}")
    rec = new_record("contracts", {
        "utility_name": utility_name,
        "contract_number": contract_number,
        "effective_start": effective_start,
        "effective_end": effective_end,
        "retainage_pct": retainage_pct,
        "overrun_threshold_pct": overrun_threshold_pct,
        "quantity_cap_pct": quantity_cap_pct,
        "status": "DRAFT",
    })
    return success_object(serialize("contracts", rec), status=201)


@bp.get("/contracts/<contract_id>")
def get_contract(contract_id):
    authorized(list(ALL_ROLES))
    rec = require_path_resource("contracts", contract_id)
    return success_object(serialize("contracts", rec))


@bp.post("/contracts/<contract_id>/transition")
def transition_contract(contract_id):
    """DRAFT->ACTIVE (CONTRACTOR_PM, needs >= 1 bid item);
    SUSPENDED->ACTIVE resume (UTILITY_DISPATCHER, gated on open incidents);
    ACTIVE->CLOSED (CONTRACTOR_PM, gated on terminal work packages)."""
    role = authorized(["CONTRACTOR_PM", "UTILITY_DISPATCHER"])
    body = get_body()
    to = req_enum(body, "to", {"ACTIVE", "CLOSED"})
    contract = require_path_resource("contracts", contract_id)
    cur = contract["status"]

    defined = {
        ("DRAFT", "ACTIVE"): "CONTRACTOR_PM",
        ("SUSPENDED", "ACTIVE"): "UTILITY_DISPATCHER",
        ("ACTIVE", "CLOSED"): "CONTRACTOR_PM",
    }
    actor = defined.get((cur, to))
    if actor is None:
        raise_error(ERR_INVALID_STATE,
                    f"cannot transition contract from {cur} to {to}")
    if role != actor:
        raise_error(ERR_FORBIDDEN,
                    f"transition {cur}->{to} requires role {actor}")

    if cur == "DRAFT" and to == "ACTIVE":
        has_bid_item = any(b["contract_id"] == contract["id"]
                           for b in db["bid_items"].values())
        if not has_bid_item:
            raise_error(ERR_INVALID_STATE,
                        "contract activation requires at least one bid item")
    elif cur == "SUSPENDED" and to == "ACTIVE":
        # Resume gate: no INCIDENT safety event OPEN or UNDER_REVIEW anywhere
        # on the contract's work packages.
        wp_ids = {w["id"] for w in db["work_packages"].values()
                  if w["contract_id"] == contract["id"]}
        for ev in db["safety_events"].values():
            if (ev["work_package_id"] in wp_ids
                    and ev["kind"] == "INCIDENT"
                    and ev["status"] in ("OPEN", "UNDER_REVIEW")):
                raise_error(ERR_SAFETY_EVENT_OPEN,
                            "an INCIDENT safety event is still OPEN or UNDER_REVIEW")
    elif cur == "ACTIVE" and to == "CLOSED":
        for w in db["work_packages"].values():
            if (w["contract_id"] == contract["id"]
                    and w["status"] not in ("COMPLETED", "CANCELLED")):
                raise_error(ERR_OPEN_WORK_PACKAGES,
                            "non-terminal work packages remain on this contract")

    contract["status"] = to
    touch(contract)
    return success_object(serialize("contracts", contract))


@bp.post("/contracts/<contract_id>/bid-items")
def create_bid_item(contract_id):
    authorized(["CONTRACTOR_PM"])
    body = get_body()
    item_code = req_str(body, "item_code")
    description = req_str(body, "description")
    unit = req_enum(body, "unit", UNITS)
    unit_price = req_num(body, "unit_price", positive=True)
    estimated_quantity = req_num(body, "estimated_quantity", positive=True)
    overrun_rate = opt_num(body, "overrun_rate", None, positive=True)
    contract = require_path_resource("contracts", contract_id)
    # item_code unique within the contract
    for b in db["bid_items"].values():
        if b["contract_id"] == contract["id"] and b["item_code"] == item_code:
            raise_error(ERR_INVALID_REQUEST,
                        f"item_code already exists in this contract: {item_code}")
    if contract["status"] != "DRAFT":
        raise_error(ERR_BID_ITEMS_LOCKED,
                    "bid item schedule is immutable once the contract has left DRAFT")
    rec = new_record("bid_items", {
        "contract_id": contract["id"],
        "item_code": item_code,
        "description": description,
        "unit": unit,
        "unit_price": unit_price,
        "estimated_quantity": estimated_quantity,
        "overrun_rate": overrun_rate,
    })
    return success_object(serialize("bid_items", rec), status=201)


@bp.post("/contracts/<contract_id>/work-packages")
def create_work_package(contract_id):
    from routes.work_packages import create_work_package_impl
    return create_work_package_impl(contract_id)
