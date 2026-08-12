"""Care-team coordination requests."""

from datetime import timedelta

from flask import Blueprint

from core import constants as K
from core import serialize
from core.audit import set_client, set_subject
from core.envelope import object_response
from core.errors import fail
from core.gates import gate_client_active
from core.pipeline import audited, authorize, resolve, resolve_body_client
from core.store import bump, db, new_row

bp = Blueprint("coordination", __name__)


@bp.post("/dmm/coordination-requests")
@audited("CoordinationRequest")
def open_request():
    ctx = authorize("CareCoordinator", "FiduciaryManager")     # rungs 1-2
    client_row = resolve_body_client(ctx)                      # rung 3
    if client_row is not None:
        set_client(client_row["id"])
    ctx.check_shape([                                          # rung 4
        ("client_id", str, True),
        ("subject", str, True),
        ("tier", str, True),
        ("assigned_member_user_id", str, True),
    ])
    ctx.check_enum("tier", K.COORDINATION_TIER)                # rung 5

    gate_client_active(client_row)                             # rung 11

    tier = ctx.body["tier"]
    row = new_row("coordination_requests", {
        "client_id": client_row["id"],
        "subject": ctx.body["subject"],
        "tier": tier,
        "assigned_member_user_id": ctx.body["assigned_member_user_id"],
        "ack_due_at": db.now + timedelta(hours=K.COORD_ACK_SLA_HOURS[tier]),
        "acknowledged_at": None,
        "reroute_count": 0,
        "status": "OPEN",
        "disposition_note": None,
    })
    set_subject(row["id"])
    return object_response(serialize.coordination_request(row), 201)


@bp.post("/dmm/coordination-requests/<cid>/disposition")
@audited("CoordinationRequest", path_param="cid")
def dispose_request(cid):
    ctx = authorize("CareCoordinator", "FiduciaryManager")     # rungs 1-2

    # rung 2 continued - the assigned-member check on an acknowledgement is
    # raised at the role rung, above every business rung.
    if ctx.role == "CareCoordinator" and ctx.body.get("action") == "ACKNOWLEDGE":
        peek = db.coordination_requests.get(cid)
        if peek is not None and ctx.user_id != peek["assigned_member_user_id"]:
            fail("ERR_FORBIDDEN_ROLE", "This request is assigned to somebody else.")

    req = resolve("coordination_requests", cid)                # rung 3
    set_client(req["client_id"])
    ctx.check_shape([                                          # rung 4
        ("action", str, True),
        ("reassign_to_user_id", str, False),
        ("disposition_note", str, False),
    ])
    if ctx.body.get("action") == "DECLINE":
        ctx.require_conditional("reassign_to_user_id")
    ctx.check_enum("action", K.COORDINATION_ACTION)            # rung 5

    action = ctx.body["action"]
    current = req["status"]
    if action in ("ACKNOWLEDGE", "DECLINE"):                   # rung 12
        if current != "OPEN":
            fail("ERR_INVALID_STATE", "The request is no longer OPEN.")
    elif action == "COMPLETE":
        if current != "ACKNOWLEDGED":
            fail("ERR_INVALID_STATE", "Only an ACKNOWLEDGED request may be completed.")
    else:
        if current not in ("OPEN", "ACKNOWLEDGED"):
            fail("ERR_INVALID_STATE", "The request can no longer be escalated.")

    if action == "DECLINE":                                    # rung 15
        reassign = ctx.body["reassign_to_user_id"]
        if reassign.strip() == "" or reassign == req["assigned_member_user_id"]:
            fail("ERR_VALIDATION", "reassign_to_user_id must name somebody else.")
        if req["reroute_count"] >= K.COORD_REROUTE_MAX_COUNT:  # rung 25
            fail("ERR_REROUTE_LIMIT_REACHED", "The reroute cap is reached.")

    if ctx.body.get("disposition_note") is not None:
        req["disposition_note"] = ctx.body["disposition_note"]

    if action == "ACKNOWLEDGE":
        req["status"] = "ACKNOWLEDGED"
        req["acknowledged_at"] = db.now
    elif action == "DECLINE":
        req["assigned_member_user_id"] = ctx.body["reassign_to_user_id"]
        req["reroute_count"] += 1
        req["ack_due_at"] = db.now + timedelta(hours=K.COORD_ACK_SLA_HOURS[req["tier"]])
    elif action == "COMPLETE":
        req["status"] = "COMPLETED"
    else:
        req["status"] = "ESCALATED"

    bump(req)
    return object_response(serialize.coordination_request(req), 200)


@bp.get("/dmm/coordination-requests/<cid>")
def read_request(cid):
    authorize("FiduciaryManager", "CareCoordinator", "ComplianceOfficer", "PlatformAdmin")
    return object_response(
        serialize.coordination_request(resolve("coordination_requests", cid)), 200
    )
