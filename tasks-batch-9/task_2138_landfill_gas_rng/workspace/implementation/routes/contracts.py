"""OfftakeContract endpoints."""

from decimal import Decimal

from flask import Blueprint

import derived
import store
from auth import authenticate, require_owner, require_role
from common import r2
from envelope import object_response, paginate, pagination
from errors import fail
from helpers import arg, filter_equal, must_find
from serializers import contract_out
from validation import Field, parse_body, validate

bp = Blueprint("contracts", __name__)

ZERO = Decimal("0")

CONTRACT_FIELDS = [
    Field("site_id", "string", required=True),
    Field("counterparty_name", "string", required=True, max_len=120),
    Field("contract_mdq_dth_per_day", "number", required=True, gt=0),
    Field("price_usd_per_dth", "number", required=True, gt=0),
    Field("term_start", "datetime", required=True),
    Field("term_end", "datetime", required=True),
    Field("attribute_share_pct", "number", default=ZERO),
]


@bp.post("/offtake-contracts")
def create_contract():
    caller = authenticate()
    require_role(caller, ["ProjectAdmin", "CommercialScheduler"])
    body = parse_body()
    data = validate(body, CONTRACT_FIELDS)

    site = must_find("site", data["site_id"])

    # Priority 57 - interval direction.
    if data["term_end"] <= data["term_start"]:
        fail("ERR_INTERVAL_INVALID", "term_end must be strictly after term_start.")

    row = store.new_row(
        site_id=site["id"],
        counterparty_name=data["counterparty_name"],
        contract_mdq_dth_per_day=data["contract_mdq_dth_per_day"],
        price_usd_per_dth=data["price_usd_per_dth"],
        attribute_share_pct=data["attribute_share_pct"],
        term_start=data["term_start"],
        term_end=data["term_end"],
        status="PENDING",
        delivered_dth_mtd=r2(ZERO),
    )
    store.contracts[row["id"]] = row
    return object_response(contract_out(row), 201)


@bp.get("/offtake-contracts/<contract_id>")
def read_contract(contract_id):
    caller = authenticate()
    require_role(caller, ["ProjectAdmin", "CommercialScheduler", "Offtaker"])
    row = must_find("contract", contract_id)
    if caller.role == "Offtaker":
        require_owner(caller, row["id"])
    return object_response(contract_out(row))


@bp.get("/offtake-contracts")
def list_contracts():
    caller = authenticate()
    require_role(caller, ["ProjectAdmin", "CommercialScheduler"])
    limit, offset = pagination()
    rows = store.ordered(store.contracts.values())
    rows = filter_equal(rows, "site_id", arg("site_id"))
    rows = filter_equal(rows, "status", arg("status"))
    return paginate(rows, limit, offset, contract_out)


CONTRACT_STATUS_FIELDS = [
    Field(
        "to_status",
        "enum",
        required=True,
        values=("PENDING", "ACTIVE", "SUSPENDED", "TERMINATED"),
    ),
]

CONTRACT_TARGETS = ("ACTIVE", "SUSPENDED", "TERMINATED")


@bp.post("/offtake-contracts/<contract_id>/status")
def contract_status(contract_id):
    caller = authenticate()
    require_role(caller, ["ProjectAdmin", "CommercialScheduler"])
    contract = must_find("contract", contract_id)
    body = parse_body()
    data = validate(body, CONTRACT_STATUS_FIELDS)

    target = data["to_status"]
    current = contract["status"]

    # Priority 80 - state legality.
    if target not in CONTRACT_TARGETS or target == current:
        fail("ERR_INVALID_TRANSITION", "%s -> %s is not a declared transition." % (current, target))

    contract["status"] = target
    store.touch(contract)
    return object_response(contract_out(contract))


__all__ = ["bp", "derived"]
