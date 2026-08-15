"""Brewery sample endpoints (PRD §3.7)."""

from flask import Blueprint, request

from db import store
from middleware import require_roles, ALL_ROLES, ROLE_CONTRACT_MANAGER
from response import success_object, success_list, parse_pagination
from util import get_body, check_unknown_fields, req_str, req_enum
from errors import invalid_state
from services.core import (
    base_record, touch, public, get_sample, get_pellet_lot,
    filtered_sorted, SAMPLE_STATUSES,
)

bp = Blueprint("samples", __name__)

CM = [ROLE_CONTRACT_MANAGER]


@bp.route("/api/samples", methods=["POST"])
def create_sample():
    require_roles(CM)
    body = get_body()
    check_unknown_fields(body, {"pellet_lot_id", "brewery_name"})
    pellet_lot_id = req_str(body, "pellet_lot_id")
    brewery_name = req_str(body, "brewery_name")

    pellet = get_pellet_lot(pellet_lot_id)
    # a lot already SOLD or DELIVERED has left the channel
    if pellet["inventory_status"] not in ("AVAILABLE", "RESERVED"):
        raise invalid_state("Pellet lot is not AVAILABLE or RESERVED")

    prior = sum(1 for s in store.samples.values()
                if s["pellet_lot_id"] == pellet_lot_id and s["brewery_name"] == brewery_name)

    rec = base_record()
    rec.update({
        "pellet_lot_id": pellet_lot_id,
        "brewery_name": brewery_name,
        "sample_round": prior + 1,
        "status": "SENT",
    })
    store.samples[rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.route("/api/samples/<sample_id>", methods=["GET"])
def get_sample_endpoint(sample_id):
    require_roles(ALL_ROLES)
    return success_object(public(get_sample(sample_id)))


@bp.route("/api/samples", methods=["GET"])
def list_samples():
    require_roles(ALL_ROLES)
    records = filtered_sorted(list(store.samples.values()), request.args, {
        "pellet_lot_id": ("str", "pellet_lot_id"),
        "brewery_name": ("str", "brewery_name"),
        "status": ("enum", "status", SAMPLE_STATUSES),
    })
    limit, offset = parse_pagination(request.args)
    total = len(records)
    page = records[offset:offset + limit]
    return success_list([public(r) for r in page], limit, offset, total)


@bp.route("/api/samples/<sample_id>/decide", methods=["POST"])
def decide_sample(sample_id):
    require_roles(CM)
    body = get_body()
    check_unknown_fields(body, {"outcome"})
    outcome = req_enum(body, "outcome", {"SELECTED", "REJECTED"})

    sample = get_sample(sample_id)
    if sample["status"] != "SENT":
        raise invalid_state("Sample is not SENT")
    sample["status"] = outcome
    touch(sample)
    return success_object(public(sample))
