"""Dispensary products, lots and dispenses."""

from flask import Blueprint

import config
import ladder
from clock import clock, parse_date, render_date
from errors import ApiError
from store import db, bump, make_row, ordered, touch
from services import serializers
from services.dispensary import (
    apply_reversal,
    lot_is_expired,
    price_dispense,
    product_stock,
    select_lot_fefo,
)

bp = Blueprint("dispensary", __name__)


def _item_protocol(item):
    return db.protocols.get(item["protocol_id"])


def _item_patient(item):
    protocol = _item_protocol(item)
    return db.patients.get(protocol["patient_id"]) if protocol else None


# ------------------------------------------------------------------- products


@bp.route("/dispensary-products", methods=["POST"])
def create_product():
    def handler(ctx):
        row = make_row(
            sku=ctx.body["sku"],
            name=ctx.body["name"],
            supplement_class=ctx.body["supplement_class"],
            retail_price_cents=ctx.body["retail_price_cents"],
            practitioner_cost_cents=ctx.body["practitioner_cost_cents"],
            interacts_with_med_classes=ctx.body.get("interacts_with_med_classes") or [],
            interaction_severity=ctx.body.get("interaction_severity") or "NONE",
            stock_on_hand=0,
        )
        db.products[row["id"]] = row
        return serializers.product(row)

    return ladder.run(
        {
            "roles": [config.ROLE_PRACTICE_ADMIN],
            "shape": [
                ("sku", "string", True),
                ("name", "string", True),
                ("supplement_class", "string", True),
                ("retail_price_cents", "int", True, {"min": 0}),
                ("practitioner_cost_cents", "int", True, {"min": 0}),
                ("interacts_with_med_classes", "array", False, {"of": "string"}),
                ("interaction_severity", "string", False),
            ],
            "enums": {
                "supplement_class": config.SUPPLEMENT_CLASSES,
                "interaction_severity": config.INTERACTION_SEVERITIES,
            },
            "handler": handler,
            "status": 201,
        }
    )


@bp.route("/dispensary-products/<pid>", methods=["GET"])
def get_product(pid):
    return ladder.run(
        {
            "roles": [
                config.ROLE_PRACTICE_ADMIN,
                config.ROLE_ND,
                config.ROLE_HEALTH_COACH,
                config.ROLE_DISPENSARY_TECH,
            ],
            "path": [("product", pid)],
            "handler": lambda ctx: serializers.product(ctx.path["product"]),
        }
    )


# ----------------------------------------------------------------------- lots


@bp.route("/dispensary-products/<pid>/lots", methods=["POST"])
def create_lot(pid):
    def handler(ctx):
        product = ctx.path["product"]
        quantity = ctx.body["quantity_initial"]
        row = make_row(
            product_id=product["id"],
            lot_code=ctx.body["lot_code"],
            quantity_initial=quantity,
            quantity_on_hand=quantity,
            expiry_date=render_date(parse_date(ctx.body["expiry_date"])),
            is_quarantined=bool(ctx.body.get("is_quarantined", False)),
        )
        db.lots[row["id"]] = row
        product["stock_on_hand"] = product_stock(product["id"])
        touch(product)
        return serializers.lot(row)

    return ladder.run(
        {
            "roles": [config.ROLE_PRACTICE_ADMIN, config.ROLE_DISPENSARY_TECH],
            "path": [("product", pid)],
            "shape": [
                ("lot_code", "string", True),
                ("quantity_initial", "int", True, {"positive": True}),
                ("expiry_date", "date", True),
                ("is_quarantined", "bool", False),
            ],
            "handler": handler,
            "status": 201,
        }
    )


@bp.route("/product-lots/<lid>", methods=["GET"])
def get_lot(lid):
    return ladder.run(
        {
            "roles": [
                config.ROLE_PRACTICE_ADMIN,
                config.ROLE_ND,
                config.ROLE_DISPENSARY_TECH,
            ],
            "path": [("lot", lid)],
            "handler": lambda ctx: serializers.lot(ctx.path["lot"]),
        }
    )


@bp.route("/product-lots", methods=["GET"])
def list_lots():
    def handler(ctx):
        rows = ordered(db.lots.values())
        product_id = ctx.args_get("product_id")
        if product_id is not None:
            rows = [r for r in rows if r["product_id"] == product_id]
        quarantined = ctx.args_bool("is_quarantined")
        if quarantined is not None:
            rows = [r for r in rows if r["is_quarantined"] == quarantined]
        return ladder.list_result(ctx, rows, serializers.lot)

    return ladder.run(
        {
            "roles": [
                config.ROLE_PRACTICE_ADMIN,
                config.ROLE_ND,
                config.ROLE_DISPENSARY_TECH,
            ],
            "paginated": True,
            "handler": handler,
        }
    )


# ------------------------------------------------------------------ dispenses


@bp.route("/dispenses", methods=["POST"])
def create_dispense():
    def dependent_state(ctx):
        item = ctx.fk.get("protocol_item_id")
        if item is None:
            return
        protocol = _item_protocol(item)
        if protocol is None or protocol["status"] != "ACTIVE":
            raise ApiError("ERR_DEPENDENT_STATE_INVALID")
        if item["status"] not in ("ACTIVE", "HELD"):
            raise ApiError("ERR_DEPENDENT_STATE_INVALID")

    def named_lot_usable(ctx):
        lot = ctx.fk.get("product_lot_id")
        if lot is None:
            return
        if lot["is_quarantined"] or lot_is_expired(lot):
            raise ApiError("ERR_LOT_EXPIRED")

    def named_lot_stocked(ctx):
        lot = ctx.fk.get("product_lot_id")
        if lot is None:
            return
        if lot["quantity_on_hand"] < ctx.body["quantity"]:
            raise ApiError("ERR_INSUFFICIENT_STOCK")
        ctx.scratch["lot"] = lot

    def selector_pool(ctx):
        if ctx.fk.get("product_lot_id") is not None:
            return
        item = ctx.fk["protocol_item_id"]
        lot = select_lot_fefo(item["product_id"], ctx.body["quantity"])
        if lot is None:
            raise ApiError("ERR_NO_ELIGIBLE_LOT")
        ctx.scratch["lot"] = lot

    def handler(ctx):
        item = ctx.fk["protocol_item_id"]
        protocol = _item_protocol(item)
        patient = _item_patient(item)
        lot = ctx.scratch["lot"]
        product = db.products.get(lot["product_id"])
        quantity = ctx.body["quantity"]
        professional_sample = bool(ctx.body.get("professional_sample", False))

        variant, unit_price, total_price = price_dispense(
            product, patient["id"], quantity, professional_sample
        )

        row = make_row(
            patient_id=patient["id"],
            protocol_item_id=item["id"],
            product_lot_id=lot["id"],
            dispensed_by_practitioner_id=ctx.user_id,
            quantity=quantity,
            pricing_variant=variant,
            unit_price_cents=unit_price,
            total_price_cents=total_price,
            status="DISPENSED",
            dispensed_at=clock.stamp(),
            professional_sample=professional_sample,
            reversed_at=None,
            reversal_reason=None,
            reversal_authorized_by_user_id=None,
        )
        db.dispenses[row["id"]] = row

        lot["quantity_on_hand"] -= quantity
        touch(lot)
        if product is not None:
            product["stock_on_hand"] = product_stock(product["id"])
            touch(product)
        patient["cash_charged_total_cents"] += total_price
        touch(patient)
        bump(protocol)
        return serializers.dispense(row)

    return ladder.run(
        {
            "roles": [config.ROLE_DISPENSARY_TECH, config.ROLE_ND],
            "body_fks": ["protocol_item_id", "product_lot_id"],
            "gate": lambda ctx: _item_patient(ctx.fk["protocol_item_id"])
            if ctx.fk.get("protocol_item_id")
            else None,
            "dependent_state": dependent_state,
            "occ": (
                "expected_protocol_version",
                lambda ctx: _item_protocol(ctx.fk["protocol_item_id"])
                if ctx.fk.get("protocol_item_id")
                else None,
            ),
            "shape": [
                ("protocol_item_id", "string", True),
                ("quantity", "int", True, {"positive": True}),
                ("expected_protocol_version", "int", True),
                ("product_lot_id", "string", False),
                ("professional_sample", "bool", False),
            ],
            "business": [named_lot_usable, named_lot_stocked, selector_pool],
            "handler": handler,
            "status": 201,
        }
    )


@bp.route("/dispenses/<did>", methods=["GET"])
def get_dispense(did):
    return ladder.run(
        {
            "roles": [
                config.ROLE_PRACTICE_ADMIN,
                config.ROLE_ND,
                config.ROLE_DISPENSARY_TECH,
                config.ROLE_CLINICAL_DIRECTOR,
                config.ROLE_PATIENT,
            ],
            "path": [("dispense", did)],
            "owner": lambda ctx: ctx.path["dispense"]["patient_id"],
            "handler": lambda ctx: serializers.dispense(ctx.path["dispense"]),
        }
    )


@bp.route("/dispenses", methods=["GET"])
def list_dispenses():
    def handler(ctx):
        rows = ordered(db.dispenses.values())
        for field in (
            "patient_id",
            "protocol_item_id",
            "product_lot_id",
            "dispensed_by_practitioner_id",
            "status",
        ):
            value = ctx.args_get(field)
            if value is not None:
                rows = [r for r in rows if r[field] == value]
        return ladder.list_result(ctx, rows, serializers.dispense)

    return ladder.run(
        {
            "roles": [
                config.ROLE_PRACTICE_ADMIN,
                config.ROLE_ND,
                config.ROLE_DISPENSARY_TECH,
                config.ROLE_CLINICAL_DIRECTOR,
            ],
            "paginated": True,
            "handler": handler,
        }
    )


@bp.route("/dispenses/<did>/reverse", methods=["POST"])
def reverse_dispense(did):
    def segregation(ctx):
        dispense = ctx.path["dispense"]
        # The threshold is inclusive.
        if dispense["total_price_cents"] >= config.REVERSAL_AUTHORIZATION_THRESHOLD_CENTS:
            if ctx.user_id == dispense["dispensed_by_practitioner_id"]:
                raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    def own_state(ctx):
        if ctx.path["dispense"]["status"] != "DISPENSED":
            raise ApiError("ERR_INVALID_STATE")

    def handler(ctx):
        dispense = ctx.path["dispense"]
        apply_reversal(dispense, ctx.body["reason"], ctx.user_id)
        bump(dispense)
        return serializers.dispense(dispense)

    return ladder.run(
        {
            "roles": [config.ROLE_CLINICAL_DIRECTOR, config.ROLE_DISPENSARY_TECH],
            "path": [("dispense", did)],
            "segregation": segregation,
            "own_state": own_state,
            "shape": [("reason", "string", True)],
            "handler": handler,
        }
    )
