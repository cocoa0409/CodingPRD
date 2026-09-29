"""Augmentation consignments: disclosure, the cap, receipt and return."""

from flask import Blueprint

import auth
import calc
import clock
import db
import helpers
import response
import serializers
import shape
from errors import ApiError
from money import dec

bp = Blueprint("augmentation", __name__)


@bp.post("/stores/<store_id>/augmentation-consignments")
def create_consignment(store_id):
    auth.begin(("LiquidationConsultant",))
    body = shape.json_body()
    supplier_name = shape.field_str(body, "supplier_name")
    category = shape.field_enum(body, "category", calc.CATEGORIES)
    units_supplied = shape.field_int(body, "units_supplied", minimum=1)
    unit_cost_cents = shape.field_int(body, "unit_cost_cents", minimum=1)
    unit_retail_cents = shape.field_int(body, "unit_retail_cents", minimum=1)
    if unit_retail_cents < unit_cost_cents:
        shape.bad("Field 'unit_retail_cents' may not be below 'unit_cost_cents'")
    window_start = shape.field_date(body, "delivery_window_start_date")
    window_end = shape.field_date(body, "delivery_window_end_date")
    if window_end < window_start:
        raise ApiError("ERR_INVALID_DATE_RANGE")

    store = helpers.require("stores", store_id)
    helpers.store_open_for_children(store)
    engagement = helpers.engagement_of_store(store)
    if engagement is not None:
        helpers.deny_frozen(engagement)
    jurisdiction = helpers.jurisdiction_of_store(store)
    if jurisdiction is not None and jurisdiction["augmentation_prohibited"]:
        raise ApiError("ERR_AUGMENTATION_PROHIBITED")
    if not calc.delivery_slot_available(store["id"], window_start, window_end):
        raise ApiError("ERR_DELIVERY_SLOT_CAPACITY")

    row = db.insert(
        "consignments",
        {
            "store_id": store["id"],
            "supplier_name": supplier_name,
            "category": category,
            "units_supplied": units_supplied,
            "unit_cost_cents": unit_cost_cents,
            "unit_retail_cents": unit_retail_cents,
            "cost_value_cents": units_supplied * unit_cost_cents,
            "delivery_window_start_date": window_start.isoformat(),
            "delivery_window_end_date": window_end.isoformat(),
            "consignment_status": "PROPOSED",
            "disclosure_reference": None,
            "disclosure_filed_at": None,
            "units_returned": 0,
        },
    )
    return response.ok(serializers.consignment(row), 201)


@bp.get("/stores/<store_id>/augmentation-consignments")
def list_consignments(store_id):
    auth.begin(
        ("LiquidationConsultant", "RetailerController", "ComplianceOfficer")
    )
    limit, offset = shape.pagination()
    consignment_status = shape.query_enum(
        "consignment_status", calc.CONSIGNMENT_STATUSES
    )
    store = helpers.require("stores", store_id)
    rows = db.consignments_of_store(store["id"])
    if consignment_status is not None:
        rows = [r for r in rows if r["consignment_status"] == consignment_status]
    return helpers.paginate(rows, serializers.consignment, limit, offset)


@bp.get("/augmentation-consignments/<row_id>")
def read_consignment(row_id):
    auth.begin(
        ("LiquidationConsultant", "RetailerController", "ComplianceOfficer")
    )
    row = helpers.require("consignments", row_id)
    return response.ok(serializers.consignment(row))


@bp.get("/augmentation-consignments/<row_id>/inventory-lots")
def list_consignment_lots(row_id):
    user_id, role = auth.begin(
        ("LiquidationConsultant", "RetailerController", "StoreManager")
    )
    limit, offset = shape.pagination()
    lot_status = shape.query_enum("lot_status", calc.LOT_STATUSES)
    consignment = db.get("consignments", row_id)
    auth.scope_child(user_id, role, consignment)
    if consignment is None:
        raise ApiError("ERR_CONSIGNMENT_NOT_FOUND")
    rows = [
        lot
        for lot in db.lots_of_store(consignment["store_id"])
        if lot["consignment_id"] == consignment["id"]
    ]
    if lot_status is not None:
        rows = [r for r in rows if r["lot_status"] == lot_status]
    return helpers.paginate(rows, serializers.lot, limit, offset)


@bp.post("/augmentation-consignments/<row_id>/file-disclosure")
def file_disclosure(row_id):
    auth.begin(("ComplianceOfficer",))
    body = shape.json_body()
    reference = shape.field_str(body, "disclosure_reference")
    consignment = helpers.require("consignments", row_id)
    if consignment["consignment_status"] != "PROPOSED":
        raise ApiError("ERR_CONSIGNMENT_STATE_INVALID")

    consignment["consignment_status"] = "DISCLOSURE_FILED"
    consignment["disclosure_reference"] = reference
    consignment["disclosure_filed_at"] = clock.iso_now()
    db.touch(consignment)
    return response.ok(serializers.consignment(consignment))


@bp.post("/augmentation-consignments/<row_id>/receive")
def receive_consignment(row_id):
    auth.begin(("LiquidationConsultant",))
    consignment = helpers.require("consignments", row_id)
    if consignment["consignment_status"] not in ("PROPOSED", "DISCLOSURE_FILED"):
        raise ApiError("ERR_CONSIGNMENT_STATE_INVALID")
    store = db.get("stores", consignment["store_id"])
    if store is None or store["store_status"] not in ("SELLING", "SUSPENDED"):
        raise ApiError("ERR_STORE_NOT_SELLING")
    engagement = helpers.engagement_of_store(store)
    if engagement is not None:
        helpers.deny_frozen(engagement)
        helpers.deny_restricted(engagement)

    jurisdiction = helpers.jurisdiction_of_store(store)
    if jurisdiction is not None:
        if dec(jurisdiction["max_augmentation_ratio"]) <= 0:
            raise ApiError("ERR_AUGMENTATION_PROHIBITED")
        if (
            jurisdiction["augmentation_disclosure_required"]
            and consignment["consignment_status"] != "DISCLOSURE_FILED"
        ):
            raise ApiError("ERR_AUGMENTATION_DISCLOSURE_MISSING")
        if jurisdiction["advertising_disclosure_required"]:
            declared = False
            for lic in db.licenses_of_store(store["id"]):
                if lic["license_status"] != "APPROVED":
                    continue
                if calc.DISCLOSURE_CLAIM in lic["advertising_claim_codes"]:
                    declared = True
                    break
            if not declared:
                raise ApiError("ERR_ADVERTISING_DISCLOSURE_REQUIRED")

        ratio = calc.augmentation_cap_ratio(store, consignment["cost_value_cents"])
        if ratio > dec(jurisdiction["max_augmentation_ratio"]):
            raise ApiError("ERR_AUGMENTATION_CAP_EXCEEDED")

    consignment["consignment_status"] = "RECEIVED"
    db.touch(consignment)
    db.insert(
        "lots",
        {
            "store_id": store["id"],
            "consignment_id": consignment["id"],
            "category": consignment["category"],
            "source": "AUGMENTATION",
            "units_initial": consignment["units_supplied"],
            "units_on_hand": consignment["units_supplied"],
            "units_sold": 0,
            "units_returned": 0,
            "unit_cost_cents": consignment["unit_cost_cents"],
            "unit_retail_cents": consignment["unit_retail_cents"],
            "cost_value_cents": consignment["units_supplied"] * consignment["unit_cost_cents"],
            "retail_value_cents": consignment["units_supplied"] * consignment["unit_retail_cents"],
            "lot_status": "ON_FLOOR",
            "projected_recovery_cents": 0,
        },
    )
    original_cost = store["original_cost_value_cents"]
    calc.recompute_store(store)
    store["original_cost_value_cents"] = original_cost
    db.touch(store)
    if engagement is not None:
        calc.recompute_engagement(engagement)
    return response.ok(serializers.consignment(consignment))


@bp.post("/augmentation-consignments/<row_id>/return-unsold")
def return_unsold(row_id):
    auth.begin(("LiquidationConsultant",))
    body = shape.json_body()
    declared = shape.field_int(body, "units_returned", minimum=1)
    consignment = helpers.require("consignments", row_id)
    store = db.get("stores", consignment["store_id"])

    lot = None
    if store is not None:
        for candidate in db.lots_of_store(store["id"]):
            if candidate["consignment_id"] == consignment["id"]:
                lot = candidate
                break
    on_hand = lot["units_on_hand"] if lot is not None else 0
    if consignment["consignment_status"] != "RECEIVED" or on_hand < 1:
        raise ApiError("ERR_CONSIGNMENT_STATE_INVALID")
    if declared > on_hand:
        raise ApiError("ERR_RETURN_UNITS_EXCEED_UNSOLD")

    returned = on_hand
    lot["units_returned"] += returned
    lot["units_on_hand"] = 0
    lot["lot_status"] = "RETURNED_TO_SUPPLIER"
    net_units = lot["units_initial"] - lot["units_returned"]
    lot["cost_value_cents"] = net_units * lot["unit_cost_cents"]
    lot["retail_value_cents"] = net_units * lot["unit_retail_cents"]
    db.touch(lot)

    consignment["consignment_status"] = "RETURNED"
    consignment["units_returned"] = returned
    db.touch(consignment)

    engagement = helpers.engagement_of_store(store)
    original_cost = store["original_cost_value_cents"]
    calc.recompute_store(store)
    store["original_cost_value_cents"] = original_cost
    db.touch(store)
    if engagement is not None:
        calc.recompute_engagement(engagement)
    return response.ok(serializers.consignment(consignment))
