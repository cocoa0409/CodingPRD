"""Keg assets, the taproom leg and the deposit ledger."""

from decimal import Decimal
from flask import Blueprint

from . import constants as C
from . import lookup
from .auth import authorize
from .calc import keg_deposit_settlement, lot_units_available
from .cascades import deplete_lot_if_empty
from .envelope import list_response, object_response
from .errors import ApiError
from .routes_recipes import require_id
from .store import base_record, collection_sorted, db, touch
from .util import add_minutes, dec, round2, whole_days_between
from .validate import (
    body_dict,
    field,
    pagination,
    paginate,
    parse_body,
    query_enum,
    query_string,
)

bp = Blueprint("kegs", __name__)

READ_ROLES = (
    "ProductionOperator",
    "TaproomStaff",
    "SalesRep",
    "ComplianceOfficer",
    "PlatformAdmin",
)
KEG_STATUSES = (
    "IN_STOCK",
    "FILLED",
    "ON_TAP",
    "EMPTY",
    "ON_DEPOSIT",
    "RETURNED",
    "SCRAPPED",
)
DEPOSIT_STATES = ("NONE", "CHARGED", "REFUNDED", "FORFEITED")
FILL_STATUSES = ("REQUESTED", "INSPECTED", "POURED")


@bp.post("/kegs")
def register_keg():
    authorize("ProductionOperator", "PlatformAdmin")
    payload = body_dict()
    data = parse_body(
        payload,
        [
            field("asset_code", "string", required=True),
            field("capacity_liters", "number", required=True, positive=True),
        ],
    )
    record = base_record()
    record.update(
        {
            "asset_code": data["asset_code"],
            "capacity_liters": round2(data["capacity_liters"]),
            "finished_lot_id": None,
            "account_id": None,
            "status": "IN_STOCK",
            "fill_liters": Decimal("0.00"),
            "remaining_liters": Decimal("0.00"),
            "deposit_state": "NONE",
            "deposit_amount": Decimal("0.00"),
            "deposit_refund_amount": Decimal("0.00"),
            "deposit_forfeit_amount": Decimal("0.00"),
            "issued_at": None,
            "returned_at": None,
            "tapped_at": None,
            "last_untapped_at": None,
        }
    )
    db.kegs[record["id"]] = record
    return object_response(record, 201)


@bp.post("/kegs/<id>/fill")
def fill_keg(id):
    authorize("ProductionOperator", "PlatformAdmin")
    keg = lookup.keg(id)
    payload = body_dict()
    lot = lookup.finished_lot(require_id(payload, "finished_lot_id"))
    data = parse_body(
        payload,
        [
            field("finished_lot_id", "string", required=True),
            field("fill_liters", "number", required=True, positive=True),
        ],
    )

    if lot["status"] != "RELEASED":
        raise ApiError("ERR_INVALID_STATE", "Only a RELEASED lot may fill a keg.")
    if keg["status"] not in ("IN_STOCK", "EMPTY", "RETURNED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only an IN_STOCK, EMPTY or RETURNED keg may be filled.",
        )
    fill_liters = round2(data["fill_liters"])
    if lot["format"] != "KEG":
        raise ApiError("ERR_VALIDATION", "The lot's format is not KEG.")
    if fill_liters > dec(keg["capacity_liters"]):
        raise ApiError("ERR_VALIDATION", "fill_liters exceeds the keg's capacity.")
    if lot_units_available(lot) < 1:
        raise ApiError(
            "ERR_INSUFFICIENT_LOT_UNITS",
            "The lot has no uncommitted unit left to fill this keg.",
        )

    keg["status"] = "FILLED"
    keg["finished_lot_id"] = lot["id"]
    keg["fill_liters"] = fill_liters
    keg["remaining_liters"] = Decimal("0.00")
    keg["deposit_state"] = "NONE"
    keg["deposit_amount"] = Decimal("0.00")
    touch(keg)

    lot["on_hand_units"] = int(lot["on_hand_units"]) - 1
    lot["poured_units"] = int(lot["poured_units"]) + 1
    deplete_lot_if_empty(lot)
    touch(lot)

    return object_response(keg)


@bp.post("/kegs/<id>/tap")
def tap_keg(id):
    authorize("TaproomStaff", "PlatformAdmin")
    keg = lookup.keg(id)
    body_dict()
    if keg["status"] != "FILLED":
        raise ApiError("ERR_INVALID_STATE", "Only a FILLED keg may be tapped.")
    if keg["deposit_state"] != "NONE":
        raise ApiError(
            "ERR_INVALID_STATE", "A keg out on deposit may not be tapped in house."
        )
    if keg.get("last_untapped_at") is not None:
        if db.clock <= add_minutes(keg["last_untapped_at"], C.KEG_RETAP_BUFFER_MINUTES):
            raise ApiError(
                "ERR_KEG_RETAP_BUFFER",
                "The %d-minute re-tap buffer has not elapsed."
                % C.KEG_RETAP_BUFFER_MINUTES,
            )

    keg["status"] = "ON_TAP"
    keg["tapped_at"] = db.clock
    keg["remaining_liters"] = round2(
        dec(keg["fill_liters"]) - C.KEG_BLOWOFF_ALLOWANCE_LITERS
    )
    touch(keg)
    return object_response(keg)


@bp.post("/kegs/<id>/untap")
def untap_keg(id):
    authorize("TaproomStaff", "PlatformAdmin")
    keg = lookup.keg(id)
    body_dict()
    if keg["status"] != "ON_TAP":
        raise ApiError("ERR_INVALID_STATE", "Only an ON_TAP keg may be untapped.")
    keg["status"] = "FILLED"
    keg["last_untapped_at"] = db.clock
    keg["tapped_at"] = None
    touch(keg)
    return object_response(keg)


@bp.post("/kegs/<id>/issue")
def issue_keg(id):
    authorize("SalesRep", "PlatformAdmin")
    keg = lookup.keg(id)
    payload = body_dict()
    account = lookup.account(require_id(payload, "account_id"))
    parse_body(payload, [field("account_id", "string", required=True)])

    if keg["status"] != "FILLED" or keg["deposit_state"] != "NONE":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a FILLED keg with no deposit charged may be issued.",
        )
    if account["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "The account must be ACTIVE.")
    lot = db.finished_lots.get(keg.get("finished_lot_id"))
    if (
        lot is not None
        and lot["abv_class"] == "ALCOHOLIC"
        and not account["alcoholic_license_on_file"]
    ):
        raise ApiError(
            "ERR_ALCOHOLIC_CHANNEL_RESTRICTED",
            "The account has no alcoholic licence on file.",
        )

    keg["status"] = "ON_DEPOSIT"
    keg["account_id"] = account["id"]
    keg["issued_at"] = db.clock
    keg["deposit_state"] = "CHARGED"
    keg["deposit_amount"] = C.KEG_DEPOSIT_AMOUNT
    touch(keg)

    account["keg_deposit_balance"] = round2(
        dec(account["keg_deposit_balance"]) + C.KEG_DEPOSIT_AMOUNT
    )
    account["kegs_charged_lifetime"] = int(account["kegs_charged_lifetime"]) + 1
    touch(account)

    return object_response(keg)


@bp.post("/kegs/<id>/return")
def return_keg(id):
    authorize("SalesRep", "PlatformAdmin")
    keg = lookup.keg(id)
    payload = body_dict()
    data = parse_body(
        payload,
        [
            field(
                "condition", "enum", required=True, members=C.KEG_RETURN_CONDITIONS
            )
        ],
    )
    if keg["status"] != "ON_DEPOSIT" or keg["deposit_state"] != "CHARGED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a keg ON_DEPOSIT with a charged deposit may be returned.",
        )

    returned_at = db.clock
    days_out = whole_days_between(keg["issued_at"], returned_at)
    refund, forfeit = keg_deposit_settlement(data["condition"], days_out)

    account = db.accounts.get(keg.get("account_id"))
    keg["returned_at"] = returned_at
    keg["deposit_refund_amount"] = refund
    keg["deposit_forfeit_amount"] = forfeit
    keg["deposit_state"] = "REFUNDED" if forfeit == Decimal("0.00") else "FORFEITED"
    keg["status"] = "SCRAPPED" if data["condition"] == "DAMAGED" else "RETURNED"
    keg["account_id"] = None
    keg["deposit_amount"] = Decimal("0.00")
    touch(keg)

    if account is not None:
        account["keg_deposit_balance"] = round2(
            dec(account["keg_deposit_balance"]) - C.KEG_DEPOSIT_AMOUNT
        )
        account["deposit_refunded_total"] = round2(
            dec(account["deposit_refunded_total"]) + refund
        )
        account["deposit_forfeited_total"] = round2(
            dec(account["deposit_forfeited_total"]) + forfeit
        )
        touch(account)

    return object_response(keg)


@bp.get("/kegs/<id>")
def read_keg(id):
    authorize(*READ_ROLES)
    return object_response(lookup.keg(id))


@bp.get("/kegs")
def list_kegs():
    authorize(*READ_ROLES)
    finished_lot_id = query_string("finished_lot_id")
    account_id = query_string("account_id")
    status = query_enum("status", KEG_STATUSES)
    deposit_state = query_enum("deposit_state", DEPOSIT_STATES)
    limit, offset = pagination()

    def keep(keg):
        if finished_lot_id is not None and keg["finished_lot_id"] != finished_lot_id:
            return False
        if account_id is not None and keg["account_id"] != account_id:
            return False
        if status is not None and keg["status"] != status:
            return False
        if deposit_state is not None and keg["deposit_state"] != deposit_state:
            return False
        return True

    rows = collection_sorted(db.kegs, keep)
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


@bp.get("/kegs/<id>/fills")
def list_keg_fills(id):
    authorize("TaproomStaff", "PlatformAdmin")
    keg = lookup.keg(id)
    fill_status = query_enum("fill_status", FILL_STATUSES)
    limit, offset = pagination()
    rows = collection_sorted(
        db.taproom_fills,
        lambda f: f["keg_id"] == keg["id"]
        and (fill_status is None or f["fill_status"] == fill_status),
    )
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)
