"""PunchItem routes: deficiency workflow with the CRITICAL verification cascade
(auto manufacturer claim + series quality hold)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_CLAIM_NOT_SETTLED,
)
from middleware import ALL_ROLES
from response import success_object
from routes.helpers import authorize, list_response, get_response
from serialize import public
from services.core import (
    get_or_404, new_entity, touch, claims_of_punch, recompute_install_posture,
)
from validate import body_dict, req_str, req_enum, req_int, opt_int, req_bool

bp = Blueprint("punch_items", __name__)

SEVERITIES = {"STANDARD", "CRITICAL"}
TERMINAL_CLAIM_STATUSES = {"SETTLED", "DENIED", "WITHDRAWN"}


@bp.route("/api/punch-items", methods=["POST"])
def create_punch_item():
    authorize(["ProjectManager"])
    body = body_dict()
    order_id = req_str(body, "order_id")
    # priority 3: FK existence
    order = get_or_404("project_orders", order_id)
    order_line_id = body.get("order_line_id")
    install_event_id = body.get("install_event_id")
    if order_line_id is not None:
        if not isinstance(order_line_id, str):
            raise_error(ERR_INVALID_REQUEST, "order_line_id must be a string")
        get_or_404("order_lines", order_line_id)
    if install_event_id is not None:
        if not isinstance(install_event_id, str):
            raise_error(ERR_INVALID_REQUEST, "install_event_id must be a string")
        get_or_404("install_events", install_event_id)
    # priority 4: punch items cannot be opened on a CANCELLED or CLOSED order
    if order["status"] in ("CANCELLED", "CLOSED"):
        raise_error(ERR_INVALID_STATE, f"cannot open a punch item on a {order['status']} order")
    # priority 8a
    severity = req_enum(body, "severity", SEVERITIES)
    description = req_str(body, "description")
    affected_units = opt_int(body, "affected_units", minv=1)
    punch = new_entity("punch_items", {
        "order_id": order_id,
        "order_line_id": order_line_id,
        "install_event_id": install_event_id,
        "severity": severity,
        "description": description,
        "source": "INSTALL",
        "affected_units": 1 if affected_units is None else affected_units,
        "status": "OPEN",
    })
    # a new CRITICAL item typically drives install_posture to BLOCKED
    recompute_install_posture(order)
    return success_object(public(punch), status=201)


@bp.route("/api/punch-items", methods=["GET"])
def list_punch_items():
    authorize(ALL_ROLES)
    return list_response("punch_items", ["order_id", "order_line_id", "install_event_id", "status", "severity"])


@bp.route("/api/punch-items/<punch_id>", methods=["GET"])
def get_punch_item(punch_id):
    authorize(ALL_ROLES)
    return get_response("punch_items", punch_id)


@bp.route("/api/punch-items/<punch_id>/ready_for_verify", methods=["POST"])
def ready_for_verify(punch_id):
    authorize(["ProjectManager"])
    punch = get_or_404("punch_items", punch_id)
    if punch["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE, f"cannot mark ready a punch item in status {punch['status']}")
    punch["status"] = "READY_FOR_VERIFY"
    touch(punch)
    return success_object(public(punch))


@bp.route("/api/punch-items/<punch_id>/verify", methods=["POST"])
def verify_punch_item(punch_id):
    authorize(["ClaimsCoordinator"])
    punch = get_or_404("punch_items", punch_id)
    if punch["status"] != "READY_FOR_VERIFY":
        raise_error(ERR_INVALID_STATE, f"cannot verify a punch item in status {punch['status']}")
    body = body_dict()
    passed = req_bool(body, "passed")
    if not passed:
        punch["status"] = "OPEN"
        touch(punch)
    else:
        punch["status"] = "VERIFIED"
        touch(punch)
        # CRITICAL cascade: auto manufacturer claim + series quality hold, once
        if punch["severity"] == "CRITICAL" and not claims_of_punch(punch["id"]):
            line = db["order_lines"].get(punch.get("order_line_id") or "")
            series_id = line["series_id"] if line is not None else None
            unit_net = line["unit_net_price_cents"] if line is not None else 0
            claim = new_entity("manufacturer_claims", {
                "punch_item_id": punch["id"],
                "series_id": series_id,
                "claim_type": "DEFECT",
                "remedy_requested": "REPLACE",
                "claimed_amount_cents": unit_net * punch.get("affected_units", 1),
                "settlement_amount_cents": None,
                "settled_amount_cents": None,
                "replacement_order_line_id": None,
                "origin": "AUTO_CRITICAL_PUNCH",
                "status": "DRAFT",
            })
            if series_id is not None:
                series = db["product_series"].get(series_id)
                if series is not None and not series.get("quality_hold"):
                    series["quality_hold"] = True
                    touch(series)
    order = db["project_orders"].get(punch["order_id"])
    if order is not None:
        recompute_install_posture(order)
    return success_object(public(punch))


@bp.route("/api/punch-items/<punch_id>/close", methods=["POST"])
def close_punch_item(punch_id):
    authorize(["ProjectManager"])
    punch = get_or_404("punch_items", punch_id)
    if punch["status"] != "VERIFIED":
        raise_error(ERR_INVALID_STATE, f"cannot close a punch item in status {punch['status']}")
    # priority 7g: every linked claim must be terminal
    for claim in claims_of_punch(punch["id"]):
        if claim["status"] not in TERMINAL_CLAIM_STATUSES:
            raise_error(ERR_CLAIM_NOT_SETTLED, f"claim {claim['id']} is {claim['status']}, not terminal")
    punch["status"] = "CLOSED"
    touch(punch)
    order = db["project_orders"].get(punch["order_id"])
    if order is not None:
        recompute_install_posture(order)
    return success_object(public(punch))
