"""Rights inventory: slots (PRD §3.2)."""
from flask import Blueprint, request

from auth import (
    require_roles,
    ROLE_RIGHTS_MANAGER,
    ROLE_FINANCE_ANALYST,
    ROLE_FINANCE_CONTROLLER,
)
from domain import WINDOW_TYPES, block_lines_on_slot, list_page, ser_slot
from errors import (
    err,
    ERR_TITLE_NOT_FOUND,
    ERR_HOLDER_NOT_FOUND,
    ERR_SLOT_NOT_FOUND,
    ERR_TERRITORY_EMBARGOED,
    ERR_DUPLICATE_SLOT,
    ERR_SLOT_NOT_WITHDRAWABLE,
)
from response import ok_list, ok_object
from store import DB, mutate
from validate import check_window_order, field_dt, field_enum, field_str, json_body

bp = Blueprint("slots", __name__)

_READERS = (ROLE_RIGHTS_MANAGER, ROLE_FINANCE_ANALYST, ROLE_FINANCE_CONTROLLER)


@bp.route("/licensing/rights-slots", methods=["POST"])
def create_slot():
    require_roles(ROLE_RIGHTS_MANAGER)
    body = json_body()
    title_id = field_str(body, "title_id")
    rights_holder_id = field_str(body, "rights_holder_id")
    territory_code = field_str(body, "territory_code")
    language_code = field_str(body, "language_code")
    window_type = field_enum(body, "window_type", WINDOW_TYPES)
    sellable_from = field_dt(body, "sellable_from")
    sellable_to = field_dt(body, "sellable_to")
    check_window_order(sellable_from, sellable_to, "rights period")

    # Existence, body ids in declaration order.
    title = DB.get("titles", title_id)
    if title is None:
        err(ERR_TITLE_NOT_FOUND, "referenced title does not exist")
    holder = DB.get("holders", rights_holder_id)
    if holder is None:
        err(ERR_HOLDER_NOT_FOUND, "referenced rights holder does not exist")

    # Business-safety: compliance embargo.
    if territory_code in title["embargoed_territories"]:
        err(ERR_TERRITORY_EMBARGOED, "slot territory is embargoed for this title")

    # Business-constraint: tuple uniqueness among AVAILABLE/ENCUMBERED slots.
    for s in DB.all("slots"):
        if (
            s["title_id"] == title_id
            and s["territory_code"] == territory_code
            and s["language_code"] == language_code
            and s["window_type"] == window_type
            and s["slot_status"] in ("AVAILABLE", "ENCUMBERED")
        ):
            err(ERR_DUPLICATE_SLOT, "an AVAILABLE/ENCUMBERED slot already exists for this tuple")

    rec = DB.insert(
        "slots",
        {
            "title_id": title_id,
            "rights_holder_id": rights_holder_id,
            "territory_code": territory_code,
            "language_code": language_code,
            "window_type": window_type,
            "sellable_from": sellable_from,
            "sellable_to": sellable_to,
            "slot_status": "AVAILABLE",
        },
    )
    return ok_object(ser_slot(rec), status=201)


@bp.route("/licensing/rights-slots", methods=["GET"])
def list_slots():
    require_roles(*_READERS)
    records = DB.all("slots")
    for param in ("title_id", "rights_holder_id", "slot_status", "territory_code", "window_type"):
        v = request.args.get(param)
        if v is not None:
            records = [s for s in records if s[param] == v]
    page, limit, offset, total = list_page(records, request.args)
    return ok_list([ser_slot(s) for s in page], limit, offset, total)


@bp.route("/licensing/rights-slots/<sid>", methods=["GET"])
def get_slot(sid):
    require_roles(*_READERS)
    rec = DB.get("slots", sid)
    if rec is None:
        err(ERR_SLOT_NOT_FOUND, "referenced rights slot does not exist")
    return ok_object(ser_slot(rec))


@bp.route("/licensing/rights-slots/<sid>/withdraw", methods=["POST"])
def withdraw_slot(sid):
    require_roles(ROLE_RIGHTS_MANAGER)
    rec = DB.get("slots", sid)
    if rec is None:
        err(ERR_SLOT_NOT_FOUND, "referenced rights slot does not exist")
    if rec["slot_status"] != "AVAILABLE":
        err(ERR_SLOT_NOT_WITHDRAWABLE, "only an AVAILABLE slot can be withdrawn")
    rec["slot_status"] = "WITHDRAWN"
    mutate(rec)
    # Blocked-line cascade: OFFERED-package lines on this slot -> BLOCKED,
    # all-blocked OFFERED packages -> EXPIRED, their lines -> NOT_SELECTED.
    block_lines_on_slot(sid)
    return ok_object(ser_slot(rec))
