"""Thousand-blocks: loading, activation and the routing ledger (PRD 3.2 / 3.7 / 3.8)."""

from flask import Blueprint

from db import base_record, by_created, days, db, now, touch
from errors import fail
from middleware import (
    ROLE_ADMIN,
    ROLE_APPROVER,
    ROLE_CARRIER,
    ROLE_PORTING,
    body,
    opt_bool,
    opt_id,
    opt_int,
    req_dt,
    req_id,
    req_int,
    req_str,
    require_roles,
)
from response import object_response, paginate
from routes.common import LRN_PATTERN, NXX_PATTERN, field, filter_rows
from services import constants as C
from services import core, serialize, workflows

bp = Blueprint("blocks", __name__)

READERS = (ROLE_ADMIN, ROLE_APPROVER, ROLE_CARRIER, ROLE_PORTING)


@bp.route("/numbering/blocks", methods=["POST"])
def load_block():
    require_roles(ROLE_ADMIN)
    payload = body()
    npa_id = req_id(payload, "npa_id")
    rate_center_id = req_id(payload, "rate_center_id")
    nxx_code = req_str(payload, "nxx_code", 3, 3, NXX_PATTERN)
    thousands_digit = req_int(payload, "thousands_digit", 0, 9)
    contaminated = opt_int(payload, "contaminated_count", 0, 1000, 0)
    holder_id = opt_id(payload, "holder_carrier_id")
    mark_activated = opt_bool(payload, "mark_activated", False)

    npa = core.get_npa(npa_id)
    rate_center = core.get_rate_center(rate_center_id)
    holder = core.get_carrier(holder_id) if holder_id is not None else None

    if rate_center["npa_id"] != npa["id"]:
        fail("ERR_INVALID_REQUEST", "rate center does not belong to the named area code")

    if holder is not None:
        if core.eligibility_status(holder) not in ("ELIGIBLE", "PROBATION"):
            fail(
                "ERR_INVALID_STATE_TRANSITION",
                "a block may only be loaded to an eligible carrier",
            )

    block_label = "%s-%s-%d" % (npa["npa_code"], nxx_code, thousands_digit)
    for existing in db.blocks.values():
        if existing["block_label"] == block_label:
            fail("ERR_DUPLICATE_BLOCK_LABEL", "block %s already exists" % block_label)

    instant = now()
    record = base_record(
        npa_id=npa["id"],
        rate_center_id=rate_center["id"],
        nxx_code=nxx_code,
        thousands_digit=thousands_digit,
        block_label=block_label,
        allocation_status="POOL_AVAILABLE",
        routing_status="UNROUTED",
        holder_carrier_id=None,
        assigned_at=None,
        activation_due_at=None,
        activated_at=None,
        aging_release_at=None,
        contaminated_count=contaminated,
        current_lrn=None,
        npac_db_version=0,
    )
    if holder is not None:
        record["holder_carrier_id"] = holder["id"]
        record["allocation_status"] = "RESERVED"
        record["assigned_at"] = instant
        record["activation_due_at"] = instant + days(C.ACTIVATION_WINDOW_DAYS)
        if mark_activated:
            record["allocation_status"] = "ASSIGNED"
            record["activated_at"] = instant
    db.blocks[record["id"]] = record

    touch(rate_center)
    if holder is not None:
        touch(holder)
    if not core.recompute_npa_posture(npa):
        touch(npa)

    return object_response(serialize.block(record), 201)


@bp.route("/numbering/blocks", methods=["GET"])
def list_blocks():
    require_roles(*READERS)
    rows = by_created(db.blocks.values())
    rows = filter_rows(
        rows,
        [
            ("npa_id", field("npa_id")),
            ("rate_center_id", field("rate_center_id")),
            ("holder_carrier_id", field("holder_carrier_id")),
            ("allocation_status", field("allocation_status")),
            ("routing_status", field("routing_status")),
        ],
    )
    return paginate(rows, serialize.block)


@bp.route("/numbering/blocks/<block_id>", methods=["GET"])
def get_block(block_id):
    require_roles(*READERS)
    return object_response(serialize.block(core.get_block(block_id)))


@bp.route("/numbering/blocks/<block_id>/activation-confirmations", methods=["POST"])
def confirm_activation(block_id):
    actor = require_roles(ROLE_CARRIER)
    payload = body()
    opt_int(payload, "activated_number_count", 0, 1000)

    block = core.get_block(block_id)

    if block.get("holder_carrier_id") != actor.user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "only the holding carrier may confirm activation")

    if block["allocation_status"] == "RETIRED":
        fail("ERR_TERMINAL_STATE", "the block is retired")
    if block["allocation_status"] != "RESERVED":
        fail("ERR_INVALID_STATE_TRANSITION", "only a RESERVED block may be activated")
    if block["activation_due_at"] is None or now() > block["activation_due_at"]:
        fail("ERR_ACTIVATION_WINDOW_EXPIRED", "the activation window has elapsed")

    block["activated_at"] = now()
    block["allocation_status"] = "ASSIGNED"
    touch(block)
    return object_response(serialize.block(block))


@bp.route("/numbering/blocks/<block_id>/routing-records", methods=["POST"])
def publish_routing(block_id):
    require_roles(ROLE_ADMIN)
    payload = body()
    lrn = req_str(payload, "lrn", 10, 10, LRN_PATTERN)
    switch_clli = req_str(payload, "switch_clli", 1, 11)
    effective_at = req_dt(payload, "effective_at")
    expected_version = req_int(payload, "expected_block_version", 0)

    block = core.get_block(block_id)

    if expected_version != block["version"]:
        fail("ERR_STALE_BLOCK_VERSION", "expected_block_version is stale")

    if block["allocation_status"] == "RETIRED":
        fail("ERR_TERMINAL_STATE", "the block is retired")

    if block["allocation_status"] not in ("RESERVED", "ASSIGNED", "RECLAMATION_PENDING"):
        fail("ERR_INVALID_STATE_TRANSITION", "a pooled block has nothing to route")
    if block["routing_status"] not in (
        "UNROUTED",
        "ROUTING_PENDING",
        "LERG_PUBLISHED",
        "ROUTING_WITHDRAWN",
    ):
        fail("ERR_INVALID_STATE_TRANSITION", "the block is locked by an active port")
    if block["routing_status"] == "LERG_PUBLISHED" and effective_at <= now():
        fail(
            "ERR_INVALID_STATE_TRANSITION",
            "a re-home of a published block must be future dated",
        )

    open_record = core.open_routing_record(block["id"])
    if open_record is not None and effective_at < open_record["effective_at"]:
        fail("ERR_ROUTING_INTERVAL_OVERLAP", "the new interval overlaps the open record")

    holder = db.carriers.get(block.get("holder_carrier_id"))
    ocn = holder["ocn"] if holder is not None else None

    workflows.supersede_open_record(block, effective_at)
    record = workflows.publish_routing_record(
        block, lrn, switch_clli, effective_at, ocn
    )

    if effective_at <= now():
        block["routing_status"] = "LERG_PUBLISHED"
        block["current_lrn"] = lrn
    else:
        block["routing_status"] = "ROUTING_PENDING"
        block["current_lrn"] = None
    touch(block)

    return object_response(serialize.routing_record(record), 201)


@bp.route("/numbering/blocks/<block_id>/routing-records", methods=["GET"])
def list_routing_records(block_id):
    require_roles(*READERS)
    block = core.get_block(block_id)
    rows = core.routing_records_of_block(block["id"])
    rows = filter_rows(rows, [("record_status", field("record_status"))])
    return paginate(rows, serialize.routing_record)
