"""Presented lots and the inspector's ownership finding."""

from flask import Blueprint, request

from db import base_row, by_created_at, db, insert, now, touch
from errors import ApiError
from middleware import caller_id, endpoint, require_assigned_inspector
from response import object_response, paginate
from routes import lookup
from services import aggregates, cascades, constants as C
from services.calculations import facility_capacity_exceeded
from util import days
from validation import FINDINGS, body, opt_id, req_enum

bp = Blueprint("animal_lots", __name__)

READ_ROLES = ("FieldInspector", "BoardAdmin", "LivestockOwner", "TheftInvestigator")


@bp.get("/animal-lots/<lot_id>")
@endpoint(*READ_ROLES)
def read_lot(lot_id):
    return object_response(lookup.lot(lot_id))


@bp.get("/animal-lots")
@endpoint(*READ_ROLES)
def list_lots():
    rows = lookup.filtered(
        db.lots,
        {
            "inspection_order_id": request.args.get("inspection_order_id"),
            "brand_registration_id": request.args.get("brand_registration_id"),
            "bill_of_sale_id": request.args.get("bill_of_sale_id"),
            "match_status": request.args.get("match_status"),
            "lot_status": request.args.get("lot_status"),
        },
    )
    return paginate(by_created_at(rows))


@bp.post("/animal-lots/<lot_id>/finding")
@endpoint("FieldInspector")
def record_finding(lot_id):
    payload = body()
    finding = req_enum(payload, "finding", FINDINGS)
    bill_of_sale_id = opt_id(payload, "bill_of_sale_id")

    lot = lookup.lot(lot_id)
    bill = lookup.bill_of_sale(bill_of_sale_id) if bill_of_sale_id is not None else None

    order = db.orders.get(lot["inspection_order_id"])
    if order is None:
        raise ApiError("ERR_ORDER_NOT_FOUND", "The parent order does not resolve.")

    require_assigned_inspector(order)

    if order["schedule_status"] != "IN_FIELD":
        raise ApiError("ERR_ORDER_INVALID_STATE", "Findings may only be entered while the order is IN_FIELD.")
    if lot["match_status"] != "UNCHECKED" or lot["lot_status"] != "PRESENTED":
        raise ApiError("ERR_ORDER_INVALID_STATE", "The lot already carries a finding.")

    registration = db.registrations.get(lot["brand_registration_id"]) if lot["brand_registration_id"] else None

    if finding == "MATCH_CONFIRMED":
        return _match_confirmed(lot, order, registration, bill, bill_of_sale_id)
    if finding == "BRAND_MISMATCH":
        return _brand_mismatch(lot, order, registration)
    return _no_legible_brand(lot, order)


def _match_confirmed(lot, order, registration, bill, bill_of_sale_id):
    if lot["brand_registration_id"] is None or registration is None:
        raise ApiError("ERR_ORDER_INVALID_STATE", "The lot names no recorded mark.")
    if registration["status"] not in C.REGISTRATION_GROUP_STATUSES:
        raise ApiError("ERR_ORDER_INVALID_STATE", "The mark read on the lot is not a live record.")

    if bill is not None:
        if (
            bill["head_count"] != lot["head_count"]
            or bill["species_class"] != lot["species_class"]
            or bill["buyer_owner_id"] != order["owner_id"]
        ):
            raise ApiError("ERR_BILL_OF_SALE_MISMATCH", "The instrument disagrees with the lot.")

    lot["match_status"] = "MATCHED"
    lot["lot_status"] = "VERIFIED"
    lot["disposition"] = "CLEARED"
    if bill_of_sale_id is not None:
        lot["bill_of_sale_id"] = bill_of_sale_id
    touch(lot)

    if aggregates.recompute_head_count_presented(order):
        touch(order)
    return object_response(lot)


def _brand_mismatch(lot, order, registration):
    if lot["brand_registration_id"] is None or registration is None:
        raise ApiError("ERR_ORDER_INVALID_STATE", "The lot names no recorded mark.")

    # hop 1
    lot["match_status"] = "MISMATCHED"
    lot["lot_status"] = "HELD"
    lot["disposition"] = "THEFT_REFERRAL"
    touch(lot)

    # hop 2
    investigation = base_row()
    investigation.update(
        {
            "animal_lot_id": lot["id"],
            "brand_registration_id": registration["id"],
            "opened_at": now(),
            "status": "OPENED",
            "outcome": "PENDING",
            "referral_agency": None,
            "reopen_count": 0,
            "opened_by_user_id": caller_id(),
            "closed_by_user_id": None,
        }
    )
    insert(db.investigations, investigation)
    cascades.set_order_hold(order, True)

    # hops 3 and 4
    cascades.encumber_registration(registration)

    if aggregates.recompute_head_count_presented(order):
        touch(order)
    return object_response(lot)


def _no_legible_brand(lot, order):
    if lot["brand_registration_id"] is not None:
        raise ApiError("ERR_ORDER_INVALID_STATE", "A recorded mark was read on this lot.")

    territory = db.territories.get(order["territory_id"])
    if territory is None:
        raise ApiError("ERR_TERRITORY_NOT_FOUND", "The order's district does not resolve.")

    if territory["intake_status"] != "OPEN":
        raise ApiError("ERR_FACILITY_INTAKE_RESTRICTED", "The district facility is not accepting intake.")

    if facility_capacity_exceeded(territory, lot["head_count"]):
        raise ApiError("ERR_FACILITY_CAPACITY_EXCEEDED", "The impound facility would exceed capacity.")

    # hop 1
    lot["match_status"] = "UNMATCHED"
    lot["lot_status"] = "HELD"
    lot["disposition"] = "ESTRAY_HOLD"
    touch(lot)

    # hop 2
    impounded_at = now()
    case = base_row()
    case.update(
        {
            "animal_lot_id": lot["id"],
            "territory_id": territory["id"],
            "claimant_owner_id": None,
            "head_count": lot["head_count"],
            "impounded_at": impounded_at,
            "statutory_release_on": impounded_at + days(C.STATUTORY_HOLD_DAYS),
            "status": "IMPOUNDED",
            "estimated_gross_cents": None,
            "gross_proceeds_cents": None,
            "sale_at": None,
            "care_cost_cents": 0,
            "handling_fee_cents": 0,
            "claimant_residual_cents": 0,
            "board_forfeiture_cents": 0,
            "distribution_variant": "NONE",
            "claim_denied_count": 0,
        }
    )
    insert(db.estrays, case)

    # hop 3
    aggregates.recompute_territory(territory)

    if aggregates.recompute_head_count_presented(order):
        touch(order)
    return object_response(lot)
