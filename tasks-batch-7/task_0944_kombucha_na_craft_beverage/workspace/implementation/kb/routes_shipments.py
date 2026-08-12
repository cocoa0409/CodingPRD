"""Shipments, lines and the commercial gates."""

from decimal import Decimal
from flask import Blueprint, g

from . import constants as C
from . import lookup
from .auth import authorize
from .calc import (
    credit_exposure,
    lot_units_available,
    recompute_outstanding_balance,
    recompute_self_dist_ledger,
    recompute_shipment_aging,
    recompute_shipment_totals,
    shipment_lines_of,
)
from .cascades import deplete_lot_if_empty
from .envelope import list_response, object_response
from .errors import ApiError
from .routes_recipes import require_id
from .store import base_record, collection_sorted, db, touch
from .util import add_days, dec, round2
from .validate import (
    body_dict,
    field,
    pagination,
    paginate,
    parse_body,
    query_enum,
    query_string,
)

bp = Blueprint("shipments", __name__)

SHIPMENT_ROLES = ("SalesRep", "ComplianceOfficer", "PlatformAdmin")
SHIPMENT_STATUSES = (
    "DRAFT",
    "CONFIRMED",
    "DELIVERED",
    "PAID",
    "CANCELLED",
    "RECALL_HOLD",
)
LINE_STATUSES = ("ACTIVE", "RECALLED", "CANCELLED")


@bp.post("/shipments")
def open_shipment():
    authorize("SalesRep", "PlatformAdmin")
    payload = body_dict()
    account = lookup.account(require_id(payload, "account_id"))
    parse_body(payload, [field("account_id", "string", required=True)])

    record = base_record()
    record.update(
        {
            "account_id": account["id"],
            "status": "DRAFT",
            "total_units": 0,
            "total_liters": Decimal("0.00"),
            "subtotal": Decimal("0.00"),
            "late_fee": Decimal("0.00"),
            "aging_bucket": "CURRENT",
            "days_past_due": 0,
            "confirmed_at": None,
            "delivered_on_date": None,
            "due_date": None,
            "paid_at": None,
            "created_by_user_id": g.user_id,
        }
    )
    db.shipments[record["id"]] = record
    return object_response(record, 201)


@bp.post("/shipments/<id>/lines")
def add_shipment_line(id):
    authorize("SalesRep", "PlatformAdmin")
    shipment = lookup.shipment(id)
    payload = body_dict()
    lot = lookup.finished_lot(require_id(payload, "finished_lot_id"))
    data = parse_body(
        payload,
        [
            field("finished_lot_id", "string", required=True),
            field("units", "integer", required=True),
            field("unit_price", "number", required=True),
            field("expected_finished_lot_version", "integer", required=True),
        ],
    )

    if shipment["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Lines are added to a DRAFT shipment only.")
    if int(data["expected_finished_lot_version"]) != int(lot["version"]):
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_finished_lot_version does not match the lot's current version.",
        )
    if lot["status"] != "RELEASED":
        raise ApiError("ERR_INVALID_STATE", "Only a RELEASED lot may back a line.")
    units = int(data["units"])
    unit_price = dec(data["unit_price"])
    if units <= 0 or unit_price <= 0:
        raise ApiError(
            "ERR_VALIDATION", "units and unit_price must both be strictly positive."
        )
    if lot_units_available(lot) < units:
        raise ApiError(
            "ERR_INSUFFICIENT_LOT_UNITS",
            "The lot has too few uncommitted units for this line.",
        )

    record = base_record()
    record.update(
        {
            "shipment_id": shipment["id"],
            "finished_lot_id": lot["id"],
            "units": units,
            "unit_price": round2(unit_price),
            "extended_price": round2(Decimal(units) * unit_price),
            "line_liters": round2(Decimal(units) * dec(lot["container_liters"])),
            "line_status": "ACTIVE",
        }
    )
    db.shipment_lines[record["id"]] = record

    lot["reserved_units"] = int(lot["reserved_units"]) + units
    touch(lot)

    recompute_shipment_totals(shipment)
    touch(shipment)

    return object_response(record, 201)


@bp.post("/shipments/<id>/confirm")
def confirm_shipment(id):
    authorize("SalesRep", "PlatformAdmin")
    shipment = lookup.shipment(id)
    body_dict()

    if shipment["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT shipment may be confirmed.")
    active_lines = [
        line for line in shipment_lines_of(shipment["id"]) if line["line_status"] == "ACTIVE"
    ]
    if not active_lines:
        raise ApiError("ERR_VALIDATION", "The shipment carries no ACTIVE line.")

    account = db.accounts.get(shipment["account_id"])
    if account is None or account["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "The account is not ACTIVE.")

    recompute_shipment_totals(shipment)

    for line in active_lines:
        lot = db.finished_lots.get(line["finished_lot_id"])
        if lot is not None and lot["abv_class"] == "ALCOHOLIC":
            if not account["alcoholic_license_on_file"]:
                raise ApiError(
                    "ERR_ALCOHOLIC_CHANNEL_RESTRICTED",
                    "The account has no alcoholic licence on file.",
                )
            break

    if account["channel"] == "SELF_DISTRIBUTION":
        recompute_self_dist_ledger(account)
        projected = round2(
            dec(account["ytd_self_dist_liters"]) + dec(shipment["total_liters"])
        )
        if projected > C.SELF_DIST_ANNUAL_LITER_CEILING:
            raise ApiError(
                "ERR_SELF_DIST_CEILING_EXCEEDED",
                "The annual self-distribution ceiling would be exceeded.",
            )

    exposure = credit_exposure(account, shipment)
    if exposure > dec(account["credit_limit"]):
        raise ApiError(
            "ERR_CREDIT_LIMIT_EXCEEDED",
            "The credit exposure exceeds the account's credit_limit.",
        )

    shipment["confirmed_at"] = db.clock
    shipment["status"] = "CONFIRMED"
    touch(shipment)
    return object_response(shipment)


@bp.post("/shipments/<id>/deliver")
def deliver_shipment(id):
    authorize("SalesRep", "PlatformAdmin")
    shipment = lookup.shipment(id)
    body_dict()
    if shipment["status"] != "CONFIRMED":
        raise ApiError(
            "ERR_INVALID_STATE", "Only a CONFIRMED shipment may be delivered."
        )
    account = db.accounts.get(shipment["account_id"])

    shipment["delivered_on_date"] = db.clock
    shipment["due_date"] = add_days(
        db.clock, int(account["credit_terms_days"]) if account else 0
    )
    shipment["status"] = "DELIVERED"

    for line in shipment_lines_of(shipment["id"]):
        if line["line_status"] != "ACTIVE":
            continue
        lot = db.finished_lots.get(line["finished_lot_id"])
        if lot is None:
            continue
        units = int(line["units"])
        lot["reserved_units"] = int(lot["reserved_units"]) - units
        lot["on_hand_units"] = int(lot["on_hand_units"]) - units
        lot["shipped_units"] = int(lot["shipped_units"]) + units
        deplete_lot_if_empty(lot)
        touch(lot)

    recompute_shipment_aging(shipment)
    touch(shipment)

    if account is not None:
        recompute_outstanding_balance(account)
        recompute_self_dist_ledger(account)
        touch(account)

    return object_response(shipment)


@bp.post("/shipments/<id>/cancel")
def cancel_shipment(id):
    authorize("SalesRep", "PlatformAdmin")
    shipment = lookup.shipment(id)
    payload = body_dict()
    parse_body(payload, [field("reason", "string")])
    if shipment["status"] not in ("DRAFT", "CONFIRMED", "RECALL_HOLD"):
        raise ApiError("ERR_INVALID_STATE", "This shipment may no longer be cancelled.")

    for line in shipment_lines_of(shipment["id"]):
        if line["line_status"] != "ACTIVE":
            continue
        lot = db.finished_lots.get(line["finished_lot_id"])
        line["line_status"] = "CANCELLED"
        touch(line)
        if lot is not None:
            lot["reserved_units"] = max(
                0, int(lot["reserved_units"]) - int(line["units"])
            )
            touch(lot)

    shipment["status"] = "CANCELLED"
    recompute_shipment_totals(shipment)
    recompute_shipment_aging(shipment)
    touch(shipment)
    return object_response(shipment)


@bp.get("/shipments/<id>")
def read_shipment(id):
    authorize(*SHIPMENT_ROLES)
    shipment = lookup.shipment(id)
    recompute_shipment_aging(shipment)
    return object_response(shipment)


@bp.get("/shipments")
def list_shipments():
    authorize(*SHIPMENT_ROLES)
    account_id = query_string("account_id")
    status = query_enum("status", SHIPMENT_STATUSES)
    limit, offset = pagination()

    def keep(s):
        if account_id is not None and s["account_id"] != account_id:
            return False
        if status is not None and s["status"] != status:
            return False
        return True

    rows = collection_sorted(db.shipments, keep)
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


@bp.get("/shipments/<id>/lines")
def list_shipment_lines(id):
    authorize(*SHIPMENT_ROLES)
    shipment = lookup.shipment(id)
    line_status = query_enum("line_status", LINE_STATUSES)
    limit, offset = pagination()
    rows = collection_sorted(
        db.shipment_lines,
        lambda l: l["shipment_id"] == shipment["id"]
        and (line_status is None or l["line_status"] == line_status),
    )
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)
