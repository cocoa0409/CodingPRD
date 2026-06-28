from flask import Blueprint, request

from db import db
from middleware import require_auth, require_role
from response import object_response, array_response
from services.common import (
    stamp_create, get_json_body, require_fields, require_enum,
    require_nonneg_int, require_string, parse_pagination, paginate,
)
from services.lookups import get_model
from services.serialize import bike_model_view, bike_view

bike_models_bp = Blueprint("bike_models", __name__)

MODEL_CLASSES = {"STANDARD", "EBIKE", "CARGO_EBIKE"}
ALL_ROLES = {"OpsAdmin", "Subscriber", "FleetManager", "FieldTech"}


@bike_models_bp.route("/bike-models", methods=["POST"])
def create_bike_model():
    # PRD §4 endpoint table: POST /bike-models is OpsAdmin-only.
    require_role({"OpsAdmin"})
    body = get_json_body()
    require_fields(body, [
        "name", "model_class", "monthly_fee_cents", "daily_rate_cents",
        "purchase_price_cents", "deposit_cents", "fleet_size",
    ])
    require_string(body["name"], "name")
    require_enum(body["model_class"], MODEL_CLASSES, "model_class")
    require_nonneg_int(body["monthly_fee_cents"], "monthly_fee_cents")
    require_nonneg_int(body["daily_rate_cents"], "daily_rate_cents")
    require_nonneg_int(body["purchase_price_cents"], "purchase_price_cents")
    require_nonneg_int(body["deposit_cents"], "deposit_cents")
    require_nonneg_int(body["fleet_size"], "fleet_size")

    rec = {
        "name": body["name"],
        "model_class": body["model_class"],
        "monthly_fee_cents": body["monthly_fee_cents"],
        "daily_rate_cents": body["daily_rate_cents"],
        "purchase_price_cents": body["purchase_price_cents"],
        "deposit_cents": body["deposit_cents"],
        "fleet_size": body["fleet_size"],
        "total_bikes": 0,
        "available_count": 0,
        "status": "ACTIVE",
    }
    with db.lock:
        stamp_create(rec)
        db.bike_models[rec["id"]] = rec
    return object_response(bike_model_view(rec), 201)


@bike_models_bp.route("/bike-models/<model_id>", methods=["GET"])
def fetch_bike_model(model_id):
    require_role(ALL_ROLES)
    model = get_model(model_id)
    return object_response(bike_model_view(model), 200)


@bike_models_bp.route("/bike-models", methods=["GET"])
def list_bike_models():
    require_role(ALL_ROLES)
    limit, offset = parse_pagination()
    records = list(db.bike_models.values())
    model_class = request.args.get("model_class")
    if model_class:
        records = [r for r in records if r["model_class"] == model_class]
    page, total = paginate(records, limit, offset)
    return array_response([bike_model_view(r) for r in page], limit, offset, total)


@bike_models_bp.route("/bike-models/<model_id>/bikes", methods=["GET"])
def list_model_bikes(model_id):
    require_role({"OpsAdmin", "FieldTech"})
    get_model(model_id)
    limit, offset = parse_pagination()
    records = [b for b in db.bikes.values() if b["model_id"] == model_id]
    bike_status = request.args.get("bike_status")
    if bike_status:
        records = [r for r in records if r["bike_status"] == bike_status]
    page, total = paginate(records, limit, offset)
    return array_response([bike_view(r) for r in page], limit, offset, total)
