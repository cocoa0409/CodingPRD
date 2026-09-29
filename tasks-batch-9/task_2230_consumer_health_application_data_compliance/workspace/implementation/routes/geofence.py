"""Geofence zones and location campaigns (PRD 3.8)."""

from flask import Blueprint

import clock
import db
import response
import validators as V
from errors import fail
from middleware import STAFF, require
from routes.common import check_state, filter_rows, load
from services import posture
from services.calc import (campaign_standoff, intervals_touch, within_cooldown,
                           zone_min_standoff, zone_prohibition_rule)
from validators import F, no_body, parse

zones_bp = Blueprint("geofence_zones", __name__, url_prefix="/health-data/geofence-zones")
campaigns_bp = Blueprint("geofence_campaigns", __name__,
                         url_prefix="/health-data/geofence-campaigns")

ZONES = "geofence_zones"
CAMPAIGNS = "geofence_campaigns"

_SEATED = ("PLANNED", "ACTIVE", "PAUSED")


# ------------------------------------------------------------------------ zones

@zones_bp.post("")
def create_zone():
    require("PlatformAdmin")
    body = parse("GeofenceZone", {
        "app_product_id": F("string"),
        "zone_name": F("string"),
        "state_code": F("enum", members=V.STATE_CODES),
        "facility_kind": F("enum", members=V.FACILITY_KINDS),
        "center_label": F("string"),
        "radius_meters": F("int", minimum=1, maximum=5000),
    })
    product = load("app_products", body["app_product_id"])
    rule = zone_prohibition_rule(body["state_code"], body["facility_kind"])
    row = db.new_row(ZONES, {
        "app_product_id": product["id"],
        "zone_name": body["zone_name"],
        "state_code": body["state_code"],
        "facility_kind": body["facility_kind"],
        "center_label": body["center_label"],
        "radius_meters": body["radius_meters"],
        "prohibition_rule": rule,
        "min_standoff_meters": zone_min_standoff(rule),
        "last_campaign_activated_at": None,
    })
    return response.created(db.serialize(row))


@zones_bp.get("")
def list_zones():
    require(STAFF)
    rows = filter_rows(ZONES, {"app_product_id": "app_product_id",
                               "prohibition_rule": "prohibition_rule"})
    return response.paginate(rows, db.serialize)


@zones_bp.get("/<row_id>")
def read_zone(row_id):
    require(STAFF)
    return response.ok(db.serialize(load(ZONES, row_id)))


# -------------------------------------------------------------------- campaigns

@campaigns_bp.post("")
def create_campaign():
    require("DataSteward")
    body = parse("GeofenceCampaign", {
        "geofence_zone_id": F("string"),
        "processing_purpose_id": F("string"),
        "campaign_name": F("string"),
        "target_radius_meters": F("int", minimum=1, maximum=5000),
        "distance_to_zone_center_meters": F("int", minimum=0),
        "window_start_at": F("datetime"),
        "window_end_at": F("datetime"),
    })
    purpose = load("processing_purposes", body["processing_purpose_id"])
    zone = load(ZONES, body["geofence_zone_id"])

    # check 6.
    if purpose.get("app_product_id") != zone.get("app_product_id"):
        fail("ERR_CROSS_PRODUCT_REFERENCE")

    # check 37.
    if body["window_end_at"] <= body["window_start_at"]:
        fail("ERR_WINDOW_END_BEFORE_START")

    row = db.new_row(CAMPAIGNS, {
        "geofence_zone_id": zone["id"],
        "processing_purpose_id": purpose["id"],
        "campaign_name": body["campaign_name"],
        "target_radius_meters": body["target_radius_meters"],
        "distance_to_zone_center_meters": body["distance_to_zone_center_meters"],
        "standoff_meters": campaign_standoff(body["distance_to_zone_center_meters"],
                                             body["target_radius_meters"],
                                             zone["radius_meters"]),
        "window_start_at": body["window_start_at"],
        "window_end_at": body["window_end_at"],
        "state": "PLANNED",
        "pause_reason": None,
    })
    return response.created(db.serialize(row))


@campaigns_bp.get("")
def list_campaigns():
    require(STAFF)
    rows = filter_rows(CAMPAIGNS, {"geofence_zone_id": "geofence_zone_id",
                                   "processing_purpose_id": "processing_purpose_id",
                                   "state": "state"})
    return response.paginate(rows, db.serialize)


@campaigns_bp.get("/<row_id>")
def read_campaign(row_id):
    require(STAFF)
    return response.ok(db.serialize(load(CAMPAIGNS, row_id)))


@campaigns_bp.post("/<row_id>/activate")
def activate(row_id):
    require("DataSteward")
    row = load(CAMPAIGNS, row_id)
    no_body("GeofenceCampaign")
    previous = row.get("state")
    check_state(row, CAMPAIGNS, ("PLANNED", "PAUSED"))

    zone = load(ZONES, row["geofence_zone_id"])
    # check 11.
    if zone.get("prohibition_rule") == "PROHIBITED_ALL":
        fail("ERR_GEOFENCE_PROHIBITED")
    # check 12.
    if row.get("standoff_meters", 0) < zone.get("min_standoff_meters", 0):
        fail("ERR_GEOFENCE_STANDOFF_VIOLATION")
    # check 34.
    product = posture.product_of_campaign(row)
    if product is not None and product.get("policy_compliance_state") == "LAPSED":
        fail("ERR_POLICY_LAPSED")

    if previous == "PLANNED":
        # check 38: closed-interval window exclusivity on the zone.
        for other in db.rows_of(CAMPAIGNS):
            if other["id"] == row["id"] or other.get("geofence_zone_id") != zone["id"]:
                continue
            if other.get("state") not in _SEATED:
                continue
            if intervals_touch(row["window_start_at"], row["window_end_at"],
                               other["window_start_at"], other["window_end_at"]):
                fail("ERR_CAMPAIGN_WINDOW_CONFLICT")
        # check 39: the zone cooldown is not re-checked on resume.
        if within_cooldown(zone.get("last_campaign_activated_at")):
            fail("ERR_ZONE_COOLDOWN_ACTIVE")

    row["state"] = "ACTIVE"
    row["pause_reason"] = None
    db.touch(row)
    zone["last_campaign_activated_at"] = clock.now()
    db.touch(zone)
    return response.ok(db.serialize(row))


@campaigns_bp.post("/<row_id>/pause")
def pause(row_id):
    require("DataSteward")
    row = load(CAMPAIGNS, row_id)
    body = parse("GeofenceCampaign", {"pause_reason": F("string")},
                 extra_allowed=("pause_reason",))
    check_state(row, CAMPAIGNS, ("ACTIVE",))
    row["state"] = "PAUSED"
    row["pause_reason"] = body["pause_reason"]
    db.touch(row)
    return response.ok(db.serialize(row))


@campaigns_bp.post("/<row_id>/end")
def end(row_id):
    require("DataSteward")
    row = load(CAMPAIGNS, row_id)
    no_body("GeofenceCampaign")
    check_state(row, CAMPAIGNS, _SEATED)
    row["state"] = "ENDED"
    db.touch(row)
    return response.ok(db.serialize(row))
