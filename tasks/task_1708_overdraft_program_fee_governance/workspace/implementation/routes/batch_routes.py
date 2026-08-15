from flask import Blueprint, request

import db
from errors import (ApiError, ERR_NOT_FOUND, ERR_INVALID_STATE,
                    ERR_NON_BUSINESS_DAY, ERR_BATCH_EXISTS, ERR_EARLIER_UNSETTLED)
from helpers import (auth, require_role, require_body, ok, ok_list, v_str,
                     v_date, parse_date_str, ALL_ROLES, sort_created)
from serializers import batch_to_dict
from services import seal_batch, settle_batch, parse_d

bp = Blueprint("batches", __name__)


def get_batch_or_404(bid):
    b = db.store["batches"].get(bid)
    if b is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Batch %s not found" % bid)
    return b


@bp.post("/v1/batches")
def create_batch():
    _, role = auth()
    require_role(role, ["OperationsClerk"])
    body = require_body()
    program_id = v_str(body, "program_id")
    business_date = v_date(body, "business_date")
    program = db.store["programs"].get(program_id)
    if program is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Program %s not found" % program_id)
    # Tier 9: Monday-Friday only (422).
    if parse_date_str(business_date).weekday() >= 5:
        raise ApiError(ERR_NON_BUSINESS_DAY, 422,
                       "business_date must be a Monday-Friday date")
    # Tier 10: one non-CANCELLED batch per program per business date.
    for b in db.store["batches"].values():
        if (b["program_id"] == program_id and b["business_date"] == business_date
                and b["status"] != "CANCELLED"):
            raise ApiError(ERR_BATCH_EXISTS, 409,
                           "A non-CANCELLED batch already exists for this program and date")
    b = db.new_entity({
        "program_id": program_id,
        "business_date": business_date,
        "status": "OPEN",
        "items_posted_count": 0,
        "items_returned_count": 0,
        "fees_assessed_count": 0,
        "fees_assessed_cents": 0,
    })
    db.store["batches"][b["id"]] = b
    return ok(batch_to_dict(b), status=201)


@bp.get("/v1/batches")
def list_batches():
    _, role = auth()
    require_role(role, ALL_ROLES)
    items = list(db.store["batches"].values())
    program_id = request.args.get("program_id")
    business_date = request.args.get("business_date")
    status = request.args.get("status")
    if program_id is not None:
        items = [b for b in items if b["program_id"] == program_id]
    if business_date is not None:
        items = [b for b in items if b["business_date"] == business_date]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    return ok_list([batch_to_dict(b) for b in sort_created(items)])


@bp.get("/v1/batches/<bid>")
def get_batch(bid):
    _, role = auth()
    require_role(role, ALL_ROLES)
    return ok(batch_to_dict(get_batch_or_404(bid)))


@bp.post("/v1/batches/<bid>/seal")
def seal(bid):
    _, role = auth()
    require_role(role, ["OperationsClerk"])
    b = get_batch_or_404(bid)
    if b["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an OPEN batch can be sealed")
    seal_batch(b)
    return ok(batch_to_dict(b))


@bp.post("/v1/batches/<bid>/settle")
def settle(bid):
    _, role = auth()
    require_role(role, ["OperationsClerk"])
    b = get_batch_or_404(bid)
    if b["status"] != "SEALED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a SEALED batch can be settled")
    bd = parse_d(b["business_date"])
    for other in db.store["batches"].values():
        if (other["program_id"] == b["program_id"] and other["id"] != b["id"]
                and parse_d(other["business_date"]) < bd
                and other["status"] not in ("SETTLED", "CANCELLED")):
            raise ApiError(ERR_EARLIER_UNSETTLED, 409,
                           "An earlier-dated batch of this program is not settled/cancelled")
    settle_batch(b)
    return ok(batch_to_dict(b))


@bp.post("/v1/batches/<bid>/cancel")
def cancel(bid):
    _, role = auth()
    require_role(role, ["OperationsClerk"])
    b = get_batch_or_404(bid)
    if b["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an OPEN batch can be cancelled")
    for t in db.store["transactions"].values():
        if t["batch_id"] == b["id"]:
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Batch already has assigned transactions")
    b["status"] = "CANCELLED"
    db.touch(b)
    return ok(batch_to_dict(b))
