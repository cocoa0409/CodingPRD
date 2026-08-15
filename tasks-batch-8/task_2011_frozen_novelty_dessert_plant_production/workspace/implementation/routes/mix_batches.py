"""Mix batches (PRD §3.3): 72-hour pasteurization clock, segregation of duties."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import db
from errors import ApiError, ERR_INVALID_STATE, ERR_MIX_EXPIRED, ERR_SEGREGATION_OF_DUTIES
from middleware import authenticate, ALL_ROLES
from response import success_obj, success_list
from services import serialize, MIX_SHELF_HOURS, D
from util import (
    apply_filters,
    body_json,
    check_shape,
    exist_body_fks,
    paginate,
    pagination_params,
    parse_dt,
    path_entity,
)

bp = Blueprint("mix_batches", __name__)

MIX_BATCH_SPEC = {
    "batch_code": {"type": "string", "required": True},
    "product_id": {"type": "string", "required": True},
    "litres_produced": {"type": "number", "min": 0, "min_exclusive": True, "required": True},
}


@bp.route("/mix-batches", methods=["POST"])
def create_mix_batch():
    authenticate({"ProductionPlanner"})
    body = body_json()
    exist_body_fks(body, {"product_id": ("products", "product")})
    check_shape(body, MIX_BATCH_SPEC)
    batch = db.new_entity("mix_batches", {
        "batch_code": body["batch_code"],
        "product_id": body["product_id"],
        "litres_produced": D(body["litres_produced"]),
        "produced_at": None,
        "expires_at": None,
        "litres_consumed": Decimal(0),
        "litres_wasted": Decimal(0),
        "status": "PLANNED",
        "pasteurized_by": None,
        "released_by": None,
    })
    return success_obj(serialize("mix_batches", batch), 201)


@bp.route("/mix-batches", methods=["GET"])
def list_mix_batches():
    authenticate(ALL_ROLES)
    items = apply_filters(db.all_of("mix_batches"), ["product_id", "status"])
    limit, offset = pagination_params()
    page, total, has_more = paginate(items, limit, offset)
    return success_list([serialize("mix_batches", e) for e in page],
                        limit, offset, total, has_more)


@bp.route("/mix-batches/<batch_id>", methods=["GET"])
def get_mix_batch(batch_id):
    authenticate(ALL_ROLES)
    batch = path_entity("mix_batches", batch_id, "mix batch")
    return success_obj(serialize("mix_batches", batch))


@bp.route("/mix-batches/<batch_id>/pasteurize", methods=["POST"])
def pasteurize_mix_batch(batch_id):
    user_id, _role = authenticate({"LineOperator"})
    batch = path_entity("mix_batches", batch_id, "mix batch")
    if batch["status"] != "PLANNED":
        raise ApiError(ERR_INVALID_STATE, 409, "mix batch is not PLANNED")
    now = db.now()
    batch["produced_at"] = db.fmt_ts(now)
    batch["expires_at"] = db.fmt_ts(now + timedelta(hours=MIX_SHELF_HOURS))
    batch["pasteurized_by"] = user_id
    batch["status"] = "PASTEURIZED"
    db.touch(batch)
    return success_obj(serialize("mix_batches", batch))


@bp.route("/mix-batches/<batch_id>/release", methods=["POST"])
def release_mix_batch(batch_id):
    user_id, _role = authenticate({"QAManager"})
    batch = path_entity("mix_batches", batch_id, "mix batch")
    if batch["status"] != "PASTEURIZED":
        raise ApiError(ERR_INVALID_STATE, 409, "mix batch is not PASTEURIZED")
    # Segregation of duties (PRD §2.8): releaser != pasteurizer.
    if user_id == batch["pasteurized_by"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            403,
            "releaser must differ from the pasteurizer",
        )
    # Release must occur strictly before expiry.
    if db.now() >= parse_dt(batch["expires_at"]):
        raise ApiError(ERR_MIX_EXPIRED, 422, "mix batch has expired")
    batch["released_by"] = user_id
    batch["status"] = "RELEASED"
    db.touch(batch)
    return success_obj(serialize("mix_batches", batch))


@bp.route("/mix-batches/<batch_id>/reject", methods=["POST"])
def reject_mix_batch(batch_id):
    authenticate({"QAManager"})
    batch = path_entity("mix_batches", batch_id, "mix batch")
    if batch["status"] not in ("PASTEURIZED", "RELEASED"):
        raise ApiError(ERR_INVALID_STATE, 409, "mix batch cannot be rejected")
    # mix_litres_conservation: waste the unconsumed litres.
    batch["litres_wasted"] = batch["litres_produced"] - batch["litres_consumed"]
    batch["status"] = "REJECTED"
    db.touch(batch)
    return success_obj(serialize("mix_batches", batch))
