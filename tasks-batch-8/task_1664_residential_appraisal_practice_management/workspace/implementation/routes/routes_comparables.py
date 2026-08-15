"""Comparable endpoints (PRD 3.5): adjustment discipline and eligibility."""

from flask import request

import webbase as base
import services
import store
from errors import ApiError
from timeutil import parse_date

_PATCHABLE = (
    "sale_price_cents", "distance_miles",
    "site_adjustment_cents", "gla_adjustment_cents",
    "condition_adjustment_cents", "other_adjustment_cents",
)


def _require_assigned_appraiser(order):
    if base.auth.user_id != order["assigned_appraiser_id"]:
        raise ApiError("ERR_NOT_ASSIGNED_APPRAISER")


def register(app):
    @app.route("/appraisal/comparables", methods=["POST"])
    def create_comparable():
        base.auth.require_roles("Appraiser")
        body = base.read_body()
        services.require_fields(
            body,
            ["order_id", "address", "sale_price_cents", "sale_date", "distance_miles",
             "site_adjustment_cents", "gla_adjustment_cents", "condition_adjustment_cents"],
        )
        address = services.require_string(body, "address")
        sale_price = services.require_int(body, "sale_price_cents", strictly_positive=True)
        sale_date = services.require_date(body, "sale_date")
        distance = services.require_number(body, "distance_miles", minimum=0)
        site = services.require_int(body, "site_adjustment_cents")
        gla = services.require_int(body, "gla_adjustment_cents")
        condition = services.require_int(body, "condition_adjustment_cents")
        other = 0
        if "other_adjustment_cents" in body and body["other_adjustment_cents"] is not None:
            other = services.require_int(body, "other_adjustment_cents")
        order = services.get_order(body["order_id"])
        # Comparable research happens while the order is IN_ANALYSIS (PRD 3.5).
        if order["status"] != "IN_ANALYSIS":
            raise ApiError("ERR_INVALID_STATE")
        _require_assigned_appraiser(order)
        row = store.new_row(
            store.comparables,
            order_id=order["id"],
            address=address,
            sale_price_cents=sale_price,
            sale_date=sale_date,
            distance_miles=distance,
            site_adjustment_cents=site,
            gla_adjustment_cents=gla,
            condition_adjustment_cents=condition,
            other_adjustment_cents=other,
            adjusted_price_cents=None,
            net_adjustment_pct=None,
            gross_adjustment_pct=None,
            is_eligible=None,
            ineligible_reasons=[],
            status="DRAFT",
            _sale_date_obj=parse_date(sale_date),
        )
        # comparable_adjustment runs at creation, on every edit, and at verify.
        services.recompute_comp(row)
        return base.obj(row, 201)

    @app.route("/appraisal/comparables/<comp_id>", methods=["GET"])
    def get_comparable(comp_id):
        base.auth.require_roles("FirmAdmin", "Appraiser")
        return base.obj(services.get_comparable(comp_id))

    @app.route("/appraisal/comparables", methods=["GET"])
    def list_comparables():
        base.auth.require_roles("FirmAdmin", "Appraiser")
        order_id = request.args.get("order_id")
        status = request.args.get("status")
        rows = store.comparables.values()
        if order_id is not None:
            rows = [r for r in rows if r["order_id"] == order_id]
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        return base.listing(rows, request.args)

    @app.route("/appraisal/comparables/<comp_id>", methods=["PATCH"])
    def patch_comparable(comp_id):
        base.auth.require_roles("Appraiser")
        comp = services.get_comparable(comp_id)
        if comp["status"] not in ("DRAFT", "VERIFIED"):
            raise ApiError("ERR_INVALID_STATE")
        order = services.get_order(comp["order_id"])
        _require_assigned_appraiser(order)
        body = base.read_body()
        changed = False
        for field in _PATCHABLE:
            if field in body:
                if field == "distance_miles":
                    comp[field] = services.require_number(body, field, minimum=0)
                elif field == "sale_price_cents":
                    comp[field] = services.require_int(body, field, strictly_positive=True)
                else:
                    comp[field] = services.require_int(body, field)
                changed = True
        if changed:
            services.recompute_comp(comp)
            store.touch(comp)
        return base.obj(comp)

    @app.route("/appraisal/comparables/<comp_id>/verify", methods=["POST"])
    def verify_comparable(comp_id):
        base.auth.require_roles("Appraiser")
        comp = services.get_comparable(comp_id)
        if comp["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE")
        order = services.get_order(comp["order_id"])
        if order["status"] not in ("IN_ANALYSIS", "IN_REVISION"):
            raise ApiError("ERR_INVALID_STATE")
        _require_assigned_appraiser(order)
        services.recompute_comp(comp)
        services.evaluate_eligibility(comp)
        comp["status"] = "VERIFIED"
        store.touch(comp)
        return base.obj(comp)

    @app.route("/appraisal/comparables/<comp_id>/lock", methods=["POST"])
    def lock_comparable(comp_id):
        base.auth.require_roles("Appraiser")
        comp = services.get_comparable(comp_id)
        if comp["status"] != "VERIFIED":
            raise ApiError("ERR_INVALID_STATE")
        order = services.get_order(comp["order_id"])
        if order["status"] not in ("IN_ANALYSIS", "DRAFTING", "IN_REVISION"):
            raise ApiError("ERR_INVALID_STATE")
        _require_assigned_appraiser(order)
        if not comp["is_eligible"]:
            raise ApiError("ERR_COMP_INELIGIBLE")
        comp["status"] = "LOCKED"
        store.touch(comp)
        return base.obj(comp)

    @app.route("/appraisal/comparables/<comp_id>/exclude", methods=["POST"])
    def exclude_comparable(comp_id):
        base.auth.require_roles("Appraiser")
        comp = services.get_comparable(comp_id)
        if comp["status"] not in ("DRAFT", "VERIFIED"):
            raise ApiError("ERR_INVALID_STATE")
        order = services.get_order(comp["order_id"])
        _require_assigned_appraiser(order)
        comp["status"] = "EXCLUDED"
        store.touch(comp)
        return base.obj(comp)
