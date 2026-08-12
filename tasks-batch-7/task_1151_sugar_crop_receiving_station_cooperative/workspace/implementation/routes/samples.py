from flask import Blueprint

import db
import response
import serializers
from errors import raise_err
from middleware import require_roles
from routes._common import as_decimal, as_enum, body, req_field
from services.calc import D, adjusted_net_tons, payment_factor_provisional, provisional_value_cents

bp = Blueprint("samples", __name__)

SAMPLE_TYPES = {"STATION_QUICK", "LAB_VERIFY"}


@bp.post("/api/samples")
def create_sample():
    require_roles(["QUALITY_TECH"])
    data = body()
    ticket_id = req_field(data, "ticket_id")
    sample_type = as_enum(req_field(data, "sample_type"), "sample_type", SAMPLE_TYPES)
    t = db.tickets.get(ticket_id)
    if not t:
        raise_err("ERR_NOT_FOUND", "Ticket not found")
    s = db.stamp_new({
        "ticket_id": ticket_id,
        "sample_type": sample_type,
        "sugar_pct": None,
        "trash_pct": None,
        "recorded_by_user_id": None,
        "status": "COLLECTED",
    })
    db.samples[s["id"]] = s
    return response.success(serializers.sample(s), 201)


@bp.post("/api/samples/<sample_id>/record-result")
def record_result(sample_id):
    user_id, role = require_roles(["QUALITY_TECH"])
    data = body()
    sugar = as_decimal(req_field(data, "sugar_pct"), "sugar_pct")
    trash = as_decimal(req_field(data, "trash_pct"), "trash_pct")
    if not (sugar > 0 and sugar <= 30):
        raise_err("ERR_INVALID_REQUEST", "sugar_pct must be > 0 and <= 30")
    if not (trash >= 0 and trash <= 100):
        raise_err("ERR_INVALID_REQUEST", "trash_pct must be >= 0 and <= 100")
    s = db.samples.get(sample_id)
    if not s:
        raise_err("ERR_NOT_FOUND", "Sample not found")
    if s["status"] != "COLLECTED":
        raise_err("ERR_INVALID_STATE", "Sample is not COLLECTED")
    t = db.tickets.get(s["ticket_id"])
    if t["status"] not in ("WEIGHED", "SAMPLED"):
        raise_err("ERR_INVALID_STATE", "Ticket must be WEIGHED or SAMPLED to record a result")

    s["sugar_pct"] = sugar
    s["trash_pct"] = trash
    s["recorded_by_user_id"] = user_id
    s["status"] = "RESULT_RECORDED"
    db.touch(s)

    if t["status"] == "WEIGHED":
        # first RESULT_RECORDED sample triggers SAMPLED + provisional computation
        t["provisional_trash_pct"] = trash
        t["provisional_sugar_pct"] = sugar
        prov_factor = payment_factor_provisional(sugar)
        prov_adjusted = adjusted_net_tons(t["net_weight_lbs"], trash)
        b = db.bookings.get(t["booking_id"])
        campaign = db.campaigns.get(b["campaign_id"])
        prov_value = provisional_value_cents(prov_adjusted, campaign["base_price_cents_per_ton"], prov_factor)
        t["provisional_factor"] = prov_factor
        t["provisional_adjusted_net_tons"] = prov_adjusted
        t["provisional_value_cents"] = prov_value
        t["status"] = "SAMPLED"
        db.touch(t)

    return response.success(serializers.sample(s), 200)


@bp.post("/api/samples/<sample_id>/verify")
def verify_sample(sample_id):
    user_id, role = require_roles(["QUALITY_TECH"])
    s = db.samples.get(sample_id)
    if not s:
        raise_err("ERR_NOT_FOUND", "Sample not found")
    if s["status"] != "RESULT_RECORDED":
        raise_err("ERR_INVALID_STATE", "Sample is not RESULT_RECORDED")
    if s["sample_type"] != "LAB_VERIFY":
        raise_err("ERR_INVALID_STATE", "Only LAB_VERIFY samples may be verified")
    if user_id == s["recorded_by_user_id"]:
        raise_err("ERR_SOD_VIOLATION", "Verifier must differ from recorder")
    s["status"] = "VERIFIED"
    db.touch(s)
    return response.success(serializers.sample(s), 200)


@bp.post("/api/samples/<sample_id>/invalidate")
def invalidate_sample(sample_id):
    require_roles(["QUALITY_TECH"])
    s = db.samples.get(sample_id)
    if not s:
        raise_err("ERR_NOT_FOUND", "Sample not found")
    if s["status"] != "RESULT_RECORDED":
        raise_err("ERR_INVALID_STATE", "Sample is not RESULT_RECORDED")
    s["sugar_pct"] = None
    s["trash_pct"] = None
    s["recorded_by_user_id"] = None
    s["status"] = "COLLECTED"
    db.touch(s)

    t = db.tickets.get(s["ticket_id"])
    if t and t["status"] == "SAMPLED":
        remaining = [
            x for x in db.samples.values()
            if x["ticket_id"] == t["id"] and x["status"] in ("RESULT_RECORDED", "VERIFIED")
        ]
        if not remaining:
            t["status"] = "WEIGHED"
            t["provisional_trash_pct"] = None
            t["provisional_sugar_pct"] = None
            t["provisional_factor"] = None
            t["provisional_adjusted_net_tons"] = None
            t["provisional_value_cents"] = None
            db.touch(t)

    return response.success(serializers.sample(s), 200)


@bp.get("/api/tickets/<ticket_id>/samples")
def list_ticket_samples(ticket_id):
    require_roles(["COOP_ADMIN", "STATION_OPERATOR", "QUALITY_TECH", "POOL_ACCOUNTANT", "MEMBER"])
    t = db.tickets.get(ticket_id)
    if not t:
        raise_err("ERR_NOT_FOUND", "Ticket not found")
    items = [s for s in db.samples.values() if s["ticket_id"] == ticket_id]
    items.sort(key=lambda s: (s["created_at"], s["id"]))
    return response.success_list([serializers.sample(s) for s in items], len(items), len(items), 0, 200)
