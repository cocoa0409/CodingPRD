"""Producer CRUD (PRD 3.1)."""
from flask import Blueprint, request

from db import STORE, base_record
from errors import bad_input, not_found
from helpers import body, req_int, req_str, sort_and_paginate
from middleware import require_roles
from response import success_list, success_object
from services import ser_producer

bp = Blueprint("producers", __name__)

_READ_ROLES = ("PlantController", "QualityAssuranceManager", "StateInspector")


@bp.route("/dairy/producers", methods=["POST"])
def create_producer():
    require_roles("PlantController")
    data = body()
    producer_code = req_str(data, "producer_code")
    farm_name = req_str(data, "farm_name")
    rate = req_int(data, "base_hauling_rate_cents_per_cwt")
    rec = base_record()
    rec.update({
        "producer_code": producer_code,
        "farm_name": farm_name,
        "base_hauling_rate_cents_per_cwt": rate,
        "quality_flag": "STANDARD",
        "rolling_rejection_count_30d": 0,
        "status": "ACTIVE",
    })
    STORE["producers"][rec["id"]] = rec
    return success_object(ser_producer(rec), 201)


@bp.route("/dairy/producers", methods=["GET"])
def list_producers():
    require_roles(*_READ_ROLES)
    quality_flag = request.args.get("quality_flag")
    status = request.args.get("status")
    records = list(STORE["producers"].values())
    if quality_flag is not None:
        records = [p for p in records if p["quality_flag"] == quality_flag]
    if status is not None:
        records = [p for p in records if p["status"] == status]
    page, pagination = sort_and_paginate(records)
    return success_list([ser_producer(p) for p in page], pagination)


@bp.route("/dairy/producers/<pid>", methods=["GET"])
def get_producer(pid):
    require_roles(*_READ_ROLES)
    producer = STORE["producers"].get(pid)
    if producer is None:
        raise not_found("Producer not found")
    return success_object(ser_producer(producer))
