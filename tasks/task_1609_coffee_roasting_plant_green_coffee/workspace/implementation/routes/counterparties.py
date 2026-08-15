"""Counterparty endpoints (PRD §3.1)."""

from flask import Blueprint

from db import DB
from errors import ERR_NOT_FOUND, err
from middleware import (
    COMMON_SYS, base_fields, check_unknown_fields, get_json_body, paginate,
    pub, require_fields, require_role, sort_created, v_enum, v_num, v_string,
)
from response import success_list, success_object

bp = Blueprint("counterparties", __name__)

ALLOWED_FIELDS = {
    "counterparty_ref", "legal_name", "counterparty_kind", "credit_limit_usd",
    "counterparty_status", "open_exposure_usd",
} | COMMON_SYS

COUNTERPARTY_KINDS = {"SUPPLIER", "IMPORTER", "CUSTOMER"}
READ_ROLES = ("Trader", "RiskManager", "HeadRoaster", "FulfillmentPlanner")


@bp.post("/roastery/counterparties")
def create_counterparty():
    require_role("Trader")
    body = get_json_body()
    check_unknown_fields(body, ALLOWED_FIELDS)
    require_fields(body, ["counterparty_ref", "legal_name", "counterparty_kind", "credit_limit_usd"])
    ref = v_string(body, "counterparty_ref")
    name = v_string(body, "legal_name")
    kind = v_enum(body, "counterparty_kind", COUNTERPARTY_KINDS)
    limit = v_num(body, "credit_limit_usd")
    cp = base_fields()
    cp.update({
        "counterparty_ref": ref,
        "legal_name": name,
        "counterparty_kind": kind,
        "credit_limit_usd": limit,
        "counterparty_status": "ACTIVE",
        "open_exposure_usd": 0.0,
    })
    DB.counterparties[cp["id"]] = cp
    return success_object(pub(cp), status=201)


@bp.get("/roastery/counterparties/<cp_id>")
def get_counterparty(cp_id):
    require_role(*READ_ROLES)
    cp = DB.counterparties.get(cp_id)
    if cp is None:
        raise err(ERR_NOT_FOUND, "Counterparty id does not exist")
    return success_object(pub(cp))


@bp.get("/roastery/counterparties")
def list_counterparties():
    require_role(*READ_ROLES)
    items = sort_created(DB.counterparties.values())
    from flask import request
    kind = request.args.get("counterparty_kind")
    if kind is not None:
        items = [c for c in items if c["counterparty_kind"] == kind]
    page, limit, offset, total = paginate(items)
    return success_list([pub(c) for c in page], limit, offset, total)
