"""Configuration: Customers, CutTypes, PricingPolicies (PRD §3.1)."""
from flask import request

import db
import errors
import response
import serializers
import validation as v
from middleware import authenticate, require_role
from routes._helpers import list_response
from services import common

SPECIES = {"BEEF", "PORK", "LAMB", "POULTRY"}
LOYALTY_TIERS = {"STANDARD", "PREFERRED", "WHOLESALE"}


def register(app):
    # ---- Customer ----
    @app.route("/customers", methods=["POST"])
    def create_customer():
        _uid, role = authenticate()
        require_role(role, {"CounterClerk", "ShiftManager"})
        body = v.get_body()
        full_name = v.as_str(v.require(body, "full_name"), "full_name")
        phone = v.as_str(v.require(body, "phone"), "phone")
        loyalty_tier = v.opt(body, "loyalty_tier", "STANDARD")
        v.as_enum(loyalty_tier, "loyalty_tier", LOYALTY_TIERS)

        record = {
            "full_name": full_name,
            "phone": phone,
            "loyalty_tier": loyalty_tier,
            "store_credit_cents": 0,
        }
        db.stamp_create(record)
        db.customers[record["id"]] = record
        return response.object_response(serializers.customer(record), 201)

    @app.route("/customers/<rid>", methods=["GET"])
    def get_customer(rid):
        _uid, role = authenticate()
        require_role(role, {"CounterClerk", "ShiftManager", "Customer"})
        record = common.get_or_404(db.customers, rid)
        return response.object_response(serializers.customer(record))

    # ---- CutType ----
    @app.route("/cut-types", methods=["POST"])
    def create_cut_type():
        _uid, role = authenticate()
        require_role(role, {"ShiftManager"})
        body = v.get_body()
        code = v.as_str(v.require(body, "code"), "code")
        species = v.as_enum(v.require(body, "species"), "species", SPECIES)
        base_price = v.as_int(
            v.require(body, "base_price_cents_per_kg"),
            "base_price_cents_per_kg", minimum=1)
        is_grind = v.as_bool(v.opt(body, "is_grind", False), "is_grind")
        requires_dry_age = v.as_bool(
            v.opt(body, "requires_dry_age", False), "requires_dry_age")

        # code uniqueness (PRD §3.1)
        for ct in db.cut_types.values():
            if ct["code"] == code:
                errors.fail(errors.ERR_INVALID_REQUEST,
                            "CutType code must be unique: %s" % code)

        record = {
            "code": code,
            "species": species,
            "base_price_cents_per_kg": base_price,
            "is_grind": is_grind,
            "requires_dry_age": requires_dry_age,
        }
        db.stamp_create(record)
        db.cut_types[record["id"]] = record
        return response.object_response(serializers.cut_type(record), 201)

    @app.route("/cut-types/<rid>", methods=["GET"])
    def get_cut_type(rid):
        _uid, role = authenticate()
        require_role(role, {"CounterClerk", "ShiftManager", "Butcher", "Customer"})
        record = common.get_or_404(db.cut_types, rid)
        return response.object_response(serializers.cut_type(record))

    @app.route("/cut-types", methods=["GET"])
    def list_cut_types():
        _uid, role = authenticate()
        require_role(role, {"CounterClerk", "ShiftManager", "Butcher", "Customer"})
        species = request.args.get("species")
        records = list(db.cut_types.values())
        if species is not None:
            records = [r for r in records if r["species"] == species]
        return list_response(records, request.args, serializers.cut_type)

    # ---- PricingPolicy ----
    @app.route("/pricing-policies", methods=["POST"])
    def create_pricing_policy():
        _uid, role = authenticate()
        require_role(role, {"ShiftManager"})
        body = v.get_body()
        shrink_whole = v.as_number(
            v.require(body, "shrink_pct_whole_cut"), "shrink_pct_whole_cut",
            minimum=0, maximum=1, min_inclusive=True, max_inclusive=False)
        shrink_grind = v.as_number(
            v.require(body, "shrink_pct_grind"), "shrink_pct_grind",
            minimum=0, maximum=1, min_inclusive=True, max_inclusive=False)
        preferred = v.as_number(
            v.require(body, "preferred_discount_pct"), "preferred_discount_pct",
            minimum=0, maximum=1, min_inclusive=True, max_inclusive=False)
        wholesale = v.as_number(
            v.require(body, "wholesale_discount_pct"), "wholesale_discount_pct",
            minimum=0, maximum=1, min_inclusive=True, max_inclusive=False)
        bulk_threshold = v.as_int(
            v.require(body, "bulk_threshold_g"), "bulk_threshold_g", minimum=1)
        bulk_extra = v.as_number(
            v.require(body, "bulk_extra_discount_pct"), "bulk_extra_discount_pct",
            minimum=0, maximum=1, min_inclusive=True, max_inclusive=False)

        # Deactivate the previously active policy (PRD §3.1).
        for p in db.pricing_policies.values():
            if p.get("is_active"):
                p["is_active"] = False
                db.touch(p)

        record = {
            "shrink_pct_whole_cut": shrink_whole,
            "shrink_pct_grind": shrink_grind,
            "preferred_discount_pct": preferred,
            "wholesale_discount_pct": wholesale,
            "bulk_threshold_g": bulk_threshold,
            "bulk_extra_discount_pct": bulk_extra,
            "is_active": True,
        }
        db.stamp_create(record)
        db.pricing_policies[record["id"]] = record
        return response.object_response(serializers.pricing_policy(record), 201)

    @app.route("/pricing-policies/<rid>", methods=["GET"])
    def get_pricing_policy(rid):
        _uid, role = authenticate()
        require_role(role, {"ShiftManager", "CounterClerk", "Butcher"})
        record = common.get_or_404(db.pricing_policies, rid)
        return response.object_response(serializers.pricing_policy(record))
