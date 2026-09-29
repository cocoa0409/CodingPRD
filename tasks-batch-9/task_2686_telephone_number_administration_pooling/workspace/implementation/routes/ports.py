"""Number portability: port requests, concurrence, activation and snapback (PRD 3.8)."""

from flask import Blueprint

from db import base_record, by_created, db, now, touch
from errors import fail
from middleware import (
    ROLE_ADMIN,
    ROLE_APPROVER,
    ROLE_CARRIER,
    ROLE_PORTING,
    body,
    check_action_role,
    opt_str,
    req_dt,
    req_enum,
    req_id,
    req_str,
    require_roles,
)
from response import object_response, paginate
from routes.common import LRN_PATTERN, TN_PATTERN, field, filter_rows
from services import constants as C
from services import core, serialize, workflows

bp = Blueprint("ports", __name__)

READERS = (ROLE_ADMIN, ROLE_APPROVER, ROLE_CARRIER, ROLE_PORTING)

PORT_ACTION_ROLES = {
    "CONCUR": (ROLE_CARRIER,),
    "REJECT": (ROLE_CARRIER,),
    "ACTIVATE": (ROLE_PORTING,),
    "CANCEL": (ROLE_PORTING,),
}


def _number_inside_block(telephone_number, block, npa):
    prefix = npa["npa_code"] + block["nxx_code"]
    if telephone_number[:6] != prefix:
        return False
    return telephone_number[6] == str(block["thousands_digit"])


def _block_is_portable(block, from_carrier_id):
    if block["allocation_status"] != "ASSIGNED":
        return False
    if block["routing_status"] != "LERG_PUBLISHED":
        return False
    return block.get("holder_carrier_id") == from_carrier_id


@bp.route("/numbering/port-requests", methods=["POST"])
def create_port_request():
    actor = require_roles(ROLE_CARRIER)
    payload = body()
    telephone_number = req_str(payload, "telephone_number", 10, 10, TN_PATTERN)
    block_id = req_id(payload, "number_block_id")
    from_carrier_id = req_id(payload, "from_carrier_id")
    to_carrier_id = req_id(payload, "to_carrier_id")
    requested_lrn = req_str(payload, "requested_lrn", 10, 10, LRN_PATTERN)
    desired_due_at = req_dt(payload, "desired_due_at")

    block = core.get_block(block_id)
    from_carrier = core.get_carrier(from_carrier_id)
    to_carrier = core.get_carrier(to_carrier_id)

    if actor.user_id != to_carrier["id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "the gaining carrier files the port request")

    if from_carrier["id"] == to_carrier["id"]:
        fail("ERR_INVALID_REQUEST", "from_carrier_id and to_carrier_id must differ")
    if desired_due_at <= now():
        fail("ERR_INVALID_REQUEST", "desired_due_at must be after the logical clock")

    if core.eligibility_status(to_carrier) not in ("ELIGIBLE", "PROBATION"):
        fail("ERR_CARRIER_NOT_ELIGIBLE", "the gaining carrier is not eligible")

    npa = core.get_npa(block["npa_id"])
    if not _number_inside_block(telephone_number, block, npa):
        fail("ERR_NUMBER_OUTSIDE_BLOCK", "the number does not live in that block")

    if not _block_is_portable(block, from_carrier["id"]):
        fail("ERR_PORT_BLOCK_NOT_ROUTED", "the block is not assigned and routed")

    record = base_record(
        telephone_number=telephone_number,
        number_block_id=block["id"],
        from_carrier_id=from_carrier["id"],
        to_carrier_id=to_carrier["id"],
        requested_lrn=requested_lrn,
        desired_due_at=desired_due_at,
        status="SUBMITTED",
        concurred_at=None,
        activated_at=None,
        closed_at=None,
        reject_reason=None,
        npac_db_version_at_activation=None,
        supersedes_port_request_id=None,
    )

    open_rows = [
        p
        for p in db.port_requests.values()
        if p["telephone_number"] == telephone_number
        and p["to_carrier_id"] == to_carrier["id"]
        and p["status"] == "SUBMITTED"
    ]
    if open_rows:
        earlier = by_created(open_rows)[-1]
        record["supersedes_port_request_id"] = earlier["id"]

    db.port_requests[record["id"]] = record
    return object_response(serialize.port_request(record), 201)


@bp.route("/numbering/port-requests", methods=["GET"])
def list_port_requests():
    require_roles(*READERS)
    rows = by_created(db.port_requests.values())
    rows = filter_rows(
        rows,
        [
            ("number_block_id", field("number_block_id")),
            ("from_carrier_id", field("from_carrier_id")),
            ("to_carrier_id", field("to_carrier_id")),
            ("supersedes_port_request_id", field("supersedes_port_request_id")),
            ("status", field("status")),
        ],
    )
    return paginate(rows, serialize.port_request)


@bp.route("/numbering/port-requests/<port_request_id>", methods=["GET"])
def get_port_request(port_request_id):
    require_roles(*READERS)
    return object_response(
        serialize.port_request(core.get_port_request(port_request_id))
    )


def _prior_record(block, open_record):
    """The record the open published row superseded, i.e. the pre-port routing."""
    prior = None
    for record in core.routing_records_of_block(block["id"]):
        if record["id"] == open_record["id"]:
            break
        prior = record
    return prior


@bp.route("/numbering/port-requests/<port_request_id>/transitions", methods=["POST"])
def transition_port_request(port_request_id):
    actor = require_roles(ROLE_CARRIER, ROLE_PORTING)
    payload = body()
    action = req_enum(payload, "action", C.PORT_ACTIONS)
    reject_reason = opt_str(payload, "reject_reason", 1, 500)

    port = core.get_port_request(port_request_id)

    if actor.role == ROLE_CARRIER and actor.user_id != port["from_carrier_id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "only the losing carrier may answer the port")

    check_action_role(actor, action, PORT_ACTION_ROLES)

    if port["status"] in C.PORT_TERMINAL:
        fail("ERR_TERMINAL_STATE", "the port request is already closed")

    status = port["status"]
    instant = now()
    block = db.blocks.get(port["number_block_id"])

    if action == "CONCUR":
        if status != "SUBMITTED":
            fail("ERR_INVALID_STATE_TRANSITION", "CONCUR is not available")
        if port["desired_due_at"] is not None and instant > port["desired_due_at"]:
            fail("ERR_INVALID_STATE_TRANSITION", "the desired due date has passed")
        port["status"] = "CONCURRED"
        port["concurred_at"] = instant
        touch(port)
    elif action == "REJECT":
        if status != "SUBMITTED":
            fail("ERR_INVALID_STATE_TRANSITION", "REJECT is not available")
        port["status"] = "REJECTED"
        port["closed_at"] = instant
        if reject_reason is not None:
            port["reject_reason"] = reject_reason
        touch(port)
    elif action == "ACTIVATE":
        if status != "CONCURRED":
            fail("ERR_INVALID_STATE_TRANSITION", "ACTIVATE is not available")
        if block is None or not _block_is_portable(block, port["from_carrier_id"]):
            fail("ERR_PORT_BLOCK_NOT_ROUTED", "the block is no longer assigned and routed")
        _activate(port, block, instant)
    else:
        if status not in ("SUBMITTED", "CONCURRED", "ACTIVATED"):
            fail("ERR_INVALID_STATE_TRANSITION", "CANCEL is not available")
        if reject_reason is not None:
            port["reject_reason"] = reject_reason
        if status == "ACTIVATED":
            _snap_back(port, block, instant)
        else:
            port["status"] = "CANCELLED"
            port["closed_at"] = instant
            touch(port)

    return object_response(serialize.port_request(port))


def _activate(port, block, instant):
    outgoing = core.open_routing_record(block["id"])
    switch_clli = outgoing["switch_clli"] if outgoing is not None else None
    holder = db.carriers.get(block.get("holder_carrier_id"))
    ocn = holder["ocn"] if holder is not None else None

    workflows.supersede_open_record(block, instant)
    workflows.publish_routing_record(
        block, port["requested_lrn"], switch_clli, instant, ocn
    )

    block["current_lrn"] = port["requested_lrn"]
    block["routing_status"] = "PORT_LOCKED"
    touch(block)

    port["status"] = "ACTIVATED"
    port["activated_at"] = instant
    port["npac_db_version_at_activation"] = block["npac_db_version"]
    touch(port)


def _snap_back(port, block, instant):
    port["status"] = "SNAPPED_BACK"
    port["closed_at"] = instant
    touch(port)

    if block is None:
        return

    outgoing = core.open_routing_record(block["id"])
    if outgoing is None:
        return
    prior = _prior_record(block, outgoing)
    lrn = prior["lrn"] if prior is not None else outgoing["lrn"]
    switch_clli = prior["switch_clli"] if prior is not None else outgoing["switch_clli"]
    holder = db.carriers.get(block.get("holder_carrier_id"))
    ocn = holder["ocn"] if holder is not None else None

    workflows.supersede_open_record(block, instant)
    workflows.publish_routing_record(block, lrn, switch_clli, instant, ocn)

    block["current_lrn"] = lrn
    if block["routing_status"] == "PORT_LOCKED":
        block["routing_status"] = "LERG_PUBLISHED"
    touch(block)
