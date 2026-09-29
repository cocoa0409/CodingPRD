"""Catalogue and platform configuration."""
from flask import Blueprint

from db import base_record, db, ordered, paginate
from errors import invalid
from middleware import require
from response import collection, single
from serialize import (DISPOSITION_PARTNER, MATTRESS_MODEL, PROMOTION_BUNDLE,
                       RETAIL_PARTNER, dump, dump_many)
from services import calc
from util import iso
from validate import Fields, Query

bp = Blueprint("catalog", __name__)

FIRMNESS = ("SOFT", "MEDIUM", "FIRM")
SIZES = ("TWIN", "QUEEN", "KING")
UNWIND_POLICIES = ("DEDUCT_RETAIL", "DEDUCT_PRORATED", "FORFEIT_NONE")
PRICE_MATCH_POLICIES = ("MATCH_TO_LOWEST", "MATCH_TO_ADVERTISED", "NO_MATCH")
PARTNER_TYPES = ("CHARITY", "RECYCLER")
SOIL_POLICIES = ("REJECT_SOILED", "ACCEPT_SOILED")
PARTNER_STATUSES = ("ACTIVE", "SUSPENDED")


@bp.route("/mattress-models", methods=["POST"])
@require("PlatformAdmin")
def create_mattress_model():
    fields = Fields("sku", "name", "firmness", "size", "list_price_cents",
                    "break_in_nights", "trial_nights",
                    "indentation_warranty_threshold_mm", "warranty_years",
                    "donation_eligible")
    sku = fields.string("sku")
    name = fields.string("name")
    firmness = fields.enum("firmness", FIRMNESS)
    size = fields.enum("size", SIZES)
    list_price_cents = fields.integer("list_price_cents", minimum=1)
    break_in_nights = fields.integer("break_in_nights", required=False,
                                     default=21, minimum=0)
    trial_nights = fields.integer("trial_nights", required=False, default=100,
                                  minimum=1)
    threshold = fields.number("indentation_warranty_threshold_mm",
                              required=False, default=25,
                              exclusive_minimum=0)
    warranty_years = fields.integer("warranty_years", required=False,
                                    default=10, minimum=1)
    donation_eligible = fields.boolean("donation_eligible", required=False,
                                       default=True)
    if trial_nights <= break_in_nights:
        raise invalid("trial_nights must be greater than break_in_nights")
    if any(m["sku"] == sku for m in db.mattress_models.values()):
        raise invalid("sku must be unique across the catalogue")
    record = base_record()
    record.update({
        "sku": sku,
        "name": name,
        "firmness": firmness,
        "size": size,
        "list_price_cents": list_price_cents,
        "break_in_nights": break_in_nights,
        "trial_nights": trial_nights,
        "indentation_warranty_threshold_mm": threshold,
        "warranty_years": warranty_years,
        "donation_eligible": donation_eligible,
    })
    db.mattress_models[record["id"]] = record
    return single(dump(record, MATTRESS_MODEL), 201)


@bp.route("/promotion-bundles", methods=["POST"])
@require("PlatformAdmin")
def create_promotion_bundle():
    fields = Fields("code", "accessory_retail_cents", "percent_off_bps",
                    "gift_card_cents", "unwind_policy",
                    "requires_accessory_return")
    code = fields.string("code")
    unwind_policy = fields.enum("unwind_policy", UNWIND_POLICIES)
    accessory_retail_cents = fields.integer("accessory_retail_cents",
                                            required=False, default=0,
                                            minimum=0)
    percent_off_bps = fields.integer("percent_off_bps", required=False,
                                     default=0, minimum=0, maximum=5000)
    gift_card_cents = fields.integer("gift_card_cents", required=False,
                                     default=0, minimum=0)
    requires_accessory_return = fields.boolean("requires_accessory_return",
                                               required=False, default=False)
    if any(b["code"] == code for b in db.promotion_bundles.values()):
        raise invalid("code must be unique across promotion bundles")
    record = base_record()
    record.update({
        "code": code,
        "accessory_retail_cents": accessory_retail_cents,
        "percent_off_bps": percent_off_bps,
        "gift_card_cents": gift_card_cents,
        "unwind_policy": unwind_policy,
        "requires_accessory_return": requires_accessory_return,
    })
    db.promotion_bundles[record["id"]] = record
    return single(dump(record, PROMOTION_BUNDLE), 201)


@bp.route("/retail-partners", methods=["POST"])
@require("PlatformAdmin")
def create_retail_partner():
    fields = Fields("name", "region_code", "commission_bps",
                    "price_match_policy", "attribution_window_days", "status")
    name = fields.string("name")
    region_code = fields.string("region_code")
    commission_bps = fields.integer("commission_bps", minimum=0, maximum=3000)
    price_match_policy = fields.enum("price_match_policy",
                                     PRICE_MATCH_POLICIES)
    attribution_window_days = fields.integer("attribution_window_days",
                                             required=False, default=30,
                                             minimum=1)
    status = fields.enum("status", PARTNER_STATUSES, required=False,
                         default="ACTIVE")
    record = base_record()
    record.update({
        "name": name,
        "region_code": region_code,
        "commission_bps": commission_bps,
        "price_match_policy": price_match_policy,
        "attribution_window_days": attribution_window_days,
        "status": status,
    })
    db.retail_partners[record["id"]] = record
    return single(dump(record, RETAIL_PARTNER), 201)


@bp.route("/disposition-partners", methods=["POST"])
@require("PlatformAdmin")
def create_disposition_partner():
    fields = Fields("name", "partner_type", "region_code",
                    "daily_intake_capacity_units", "accepts_condition_grades",
                    "soil_policy", "priority_rank",
                    "recycle_fee_cents_per_unit", "status")
    name = fields.string("name")
    partner_type = fields.enum("partner_type", PARTNER_TYPES)
    region_code = fields.string("region_code")
    capacity = fields.integer("daily_intake_capacity_units", minimum=1)
    grades = fields.enum_list("accepts_condition_grades",
                              calc.CONDITION_GRADES)
    soil_policy = fields.enum("soil_policy", SOIL_POLICIES)
    priority_rank = fields.integer("priority_rank", minimum=1)
    recycle_fee = fields.integer("recycle_fee_cents_per_unit", required=False,
                                 default=0, minimum=0)
    status = fields.enum("status", PARTNER_STATUSES, required=False,
                         default="ACTIVE")
    record = base_record()
    record.update({
        "name": name,
        "partner_type": partner_type,
        "region_code": region_code,
        "daily_intake_capacity_units": capacity,
        "accepts_condition_grades": grades,
        "soil_policy": soil_policy,
        "priority_rank": priority_rank,
        "recycle_fee_cents_per_unit": recycle_fee,
        "status": status,
    })
    db.disposition_partners[record["id"]] = record
    return single(dump(record, DISPOSITION_PARTNER), 201)


@bp.route("/disposition-partners", methods=["GET"])
@require("LogisticsCoordinator", "PlatformAdmin")
def list_disposition_partners():
    query = Query("region_code", "partner_type", "status")
    limit, offset = query.page()
    region_code = query.string("region_code")
    partner_type = query.enum("partner_type", PARTNER_TYPES)
    status = query.enum("status", PARTNER_STATUSES)
    matches = ordered([
        p for p in db.disposition_partners.values()
        if (region_code is None or p["region_code"] == region_code)
        and (partner_type is None or p["partner_type"] == partner_type)
        and (status is None or p["status"] == status)
    ])
    page, total = paginate(matches, limit, offset)
    return collection(dump_many(page, DISPOSITION_PARTNER), limit, offset,
                      total)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require("PlatformAdmin")
def set_clock():
    fields = Fields("to_iso8601")
    to_instant = fields.timestamp("to_iso8601")
    db.clock = to_instant
    return single({"current_utc": iso(db.clock)}, 200)
