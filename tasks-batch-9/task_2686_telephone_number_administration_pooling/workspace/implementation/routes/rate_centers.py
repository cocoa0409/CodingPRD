"""Rate centers and the pooling machine (PRD 3.2 / 3.6)."""

from flask import Blueprint

from db import base_record, by_created, db, now, touch
from errors import fail
from middleware import (
    ROLE_ADMIN,
    ROLE_APPROVER,
    ROLE_CARRIER,
    ROLE_PORTING,
    body,
    opt_dt,
    req_enum,
    req_id,
    req_str,
    require_roles,
)
from response import object_response, paginate
from routes.common import LATA_PATTERN, STATE_PATTERN, field, filter_rows
from services import constants as C
from services import core, serialize, workflows

bp = Blueprint("rate_centers", __name__)

READERS = (ROLE_ADMIN, ROLE_APPROVER, ROLE_CARRIER, ROLE_PORTING)


def pool_rank(block):
    return (
        block["contaminated_count"],
        block["nxx_code"],
        block["thousands_digit"],
        block["created_at"],
        block["_seq"],
    )


@bp.route("/numbering/rate-centers", methods=["POST"])
def create_rate_center():
    require_roles(ROLE_ADMIN)
    payload = body()
    npa_id = req_id(payload, "npa_id")
    name = req_str(payload, "name", 1, 64)
    state_code = req_str(payload, "state_code", 2, 2, STATE_PATTERN)
    lata_code = req_str(payload, "lata_code", 3, 3, LATA_PATTERN)

    npa = core.get_npa(npa_id)

    if state_code != npa["state_code"]:
        fail(
            "ERR_JURISDICTION_MISMATCH",
            "rate center state_code must match its area code",
        )

    for existing in core.rate_centers_of_npa(npa["id"]):
        if existing["name"] == name:
            fail("ERR_INVALID_REQUEST", "name must be unique within the area code")

    record = base_record(
        npa_id=npa["id"],
        name=name,
        state_code=state_code,
        lata_code=lata_code,
        pooling_status="NON_POOLED",
        pooling_effective_at=None,
        jeopardy_flag=npa["status"] == "JEOPARDY",
        pending_request_count=0,
        last_donation_block_count=0,
        donation_shortfall_count=0,
    )
    db.rate_centers[record["id"]] = record
    return object_response(serialize.rate_center(record), 201)


@bp.route("/numbering/rate-centers", methods=["GET"])
def list_rate_centers():
    require_roles(*READERS)
    rows = by_created(db.rate_centers.values())
    rows = filter_rows(
        rows,
        [
            ("npa_id", field("npa_id")),
            ("state_code", field("state_code")),
            ("lata_code", field("lata_code")),
            ("pooling_status", field("pooling_status")),
        ],
    )
    return paginate(rows, serialize.rate_center)


@bp.route("/numbering/rate-centers/<rate_center_id>", methods=["GET"])
def get_rate_center(rate_center_id):
    require_roles(*READERS)
    return object_response(serialize.rate_center(core.get_rate_center(rate_center_id)))


@bp.route("/numbering/rate-centers/<rate_center_id>/blocks", methods=["GET"])
def list_rate_center_blocks(rate_center_id):
    require_roles(*READERS)
    rate_center = core.get_rate_center(rate_center_id)
    rows = sorted(core.blocks_of_rate_center(rate_center["id"]), key=pool_rank)
    rows = filter_rows(
        rows,
        [
            ("allocation_status", field("allocation_status")),
            ("routing_status", field("routing_status")),
        ],
    )
    return paginate(rows, serialize.block)


@bp.route("/numbering/rate-centers/<rate_center_id>/pooling-transitions", methods=["POST"])
def pooling_transition(rate_center_id):
    require_roles(ROLE_ADMIN)
    payload = body()
    action = req_enum(payload, "action", C.POOLING_ACTIONS)
    effective_at = opt_dt(payload, "pooling_effective_at")

    rate_center = core.get_rate_center(rate_center_id)
    status = rate_center["pooling_status"]

    if action == "BEGIN_POOLING":
        if status != "NON_POOLED":
            fail("ERR_INVALID_STATE_TRANSITION", "BEGIN_POOLING is not available")
        rate_center["pooling_status"] = "TRANSITIONAL"
    elif action == "REVERT":
        if status != "TRANSITIONAL":
            fail("ERR_INVALID_STATE_TRANSITION", "REVERT is not available")
        rate_center["pooling_status"] = "NON_POOLED"
    else:
        if status != "TRANSITIONAL":
            fail("ERR_INVALID_STATE_TRANSITION", "COMPLETE_POOLING is not available")
        if rate_center["pending_request_count"] != 0:
            fail(
                "ERR_INVALID_STATE_TRANSITION",
                "pooling cannot complete over an open request queue",
            )
        rate_center["pooling_status"] = "POOLED"
        rate_center["pooling_effective_at"] = effective_at or now()
        workflows.complete_pooling_donations(rate_center)

    touch(rate_center)
    return object_response(serialize.rate_center(rate_center))
