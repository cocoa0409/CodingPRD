"""Routes: yacht listings and the availability calendar (PRD §3.2)."""

from flask import g, request
from flask import Blueprint

from httpkit import (api_err, as_date, as_enum, as_int, as_nonneg_int,
                     as_pos_int, as_str, body_json, get_or_404, req_field,
                     require_roles, respond_object, respond_paginated,
                     sort_created)
from serializers import ser_block, ser_yacht
from services import LIVE_AGREEMENT_STATES, LIVE_REQUEST_STATES, calendar_check
from store import db, mutate, new_record

bp = Blueprint("yachts", __name__)

CHARTER_TYPES = ("BAREBOAT", "CREWED")
RESUME_CLASSES = ("NONE", "COASTAL", "OFFSHORE", "OCEAN")
PRICING_MODES = ("PRO_RATA", "WEEKLY_PLUS_DAILY")
MANUAL_BLOCK_TYPES = ("MAINTENANCE", "OPERATOR_HOLD")


def _owning_operator(yacht):
    return db["operators"].get(yacht["operator_id"])


def _own_yacht_or_403(yacht):
    if yacht["operator_id"] != g.user_id:
        raise api_err("ERR_FORBIDDEN", "Caller does not own this yacht")


@bp.route("/yachts", methods=["POST"])
def create_yacht():
    require_roles("Operator")
    body = body_json()
    name = as_str(req_field(body, "name"), "name")
    charter_type = as_enum(req_field(body, "charter_type"), CHARTER_TYPES, "charter_type")
    home_port = as_str(req_field(body, "home_port"), "home_port")
    capacity = as_pos_int(req_field(body, "capacity_berths"), "capacity_berths")
    weekly = as_pos_int(
        req_field(body, "weekly_base_rate_cents"), "weekly_base_rate_cents"
    )
    min_days = as_pos_int(req_field(body, "min_charter_days"), "min_charter_days")
    required_class = as_enum(
        req_field(body, "required_resume_class"), RESUME_CLASSES, "required_resume_class"
    )
    deposit = as_nonneg_int(
        req_field(body, "security_deposit_cents"), "security_deposit_cents"
    )
    pricing_mode = as_enum(
        req_field(body, "pricing_mode"), PRICING_MODES, "pricing_mode"
    )
    central_id = as_str(
        req_field(body, "listing_central_agent_id"), "listing_central_agent_id"
    )
    broker = db["brokers"].get(central_id)
    if broker is None:
        raise api_err(
            "ERR_NOT_FOUND", f"Broker not found: {central_id}"
        )
    # PRD §2.1 role admittance: the CentralAgent role admits CENTRAL_AGENT or
    # BOTH; §3.1 lets a BOTH broker "wear either hat across the marketplace".
    if broker["broker_type"] not in ("CENTRAL_AGENT", "BOTH"):
        raise api_err(
            "ERR_INVALID_REQUEST",
            "listing_central_agent_id must reference a CENTRAL_AGENT broker",
        )
    y = new_record()
    y.update({
        "operator_id": g.user_id,  # from the authenticated operator, never payload
        "listing_central_agent_id": central_id,
        "name": name,
        "charter_type": charter_type,
        "home_port": home_port,
        "capacity_berths": capacity,
        "weekly_base_rate_cents": weekly,
        "min_charter_days": min_days,
        "required_resume_class": required_class,
        "security_deposit_cents": deposit,
        "pricing_mode": pricing_mode,
        "status": "DRAFT",
    })
    db["yachts"][y["id"]] = y
    return respond_object(ser_yacht(y), 201)


@bp.route("/yachts/<yid>", methods=["GET"])
def get_yacht(yid):
    y = get_or_404("yachts", yid, "Yacht")
    return respond_object(ser_yacht(y))


@bp.route("/yachts", methods=["GET"])
def list_yachts():
    items = list(db["yachts"].values())
    for f in ("operator_id", "status", "pricing_mode", "listing_central_agent_id"):
        v = request.args.get(f)
        if v is not None:
            items = [y for y in items if y[f] == v]
    return respond_paginated([ser_yacht(y) for y in sort_created(items)])


@bp.route("/yachts/<yid>/list", methods=["POST"])
def list_yacht(yid):
    require_roles("Operator")
    y = get_or_404("yachts", yid, "Yacht")
    _own_yacht_or_403(y)
    if y["status"] not in ("DRAFT", "DELISTED"):
        raise api_err("ERR_INVALID_STATE", "Yacht is not DRAFT or DELISTED")
    op = _owning_operator(y)
    if op is None or op["status"] != "ACTIVE":
        raise api_err("ERR_OPERATOR_SUSPENDED", "Operator is SUSPENDED")
    y["status"] = "LISTED"
    mutate(y)
    return respond_object(ser_yacht(y))


@bp.route("/yachts/<yid>/delist", methods=["POST"])
def delist_yacht(yid):
    require_roles("Operator")
    y = get_or_404("yachts", yid, "Yacht")
    _own_yacht_or_403(y)
    if y["status"] != "LISTED":
        raise api_err("ERR_INVALID_STATE", "Yacht is not LISTED")
    # Delisting is deliberately asymmetric: operator standing is NOT checked.
    live_request = any(
        r["yacht_id"] == yid and r["status"] in LIVE_REQUEST_STATES - {"DRAFT"}
        for r in db["charter_requests"].values()
    )
    live_agreement = any(
        a["yacht_id"] == yid and a["status"] in LIVE_AGREEMENT_STATES
        for a in db["charter_agreements"].values()
    )
    if live_request or live_agreement:
        raise api_err(
            "ERR_INVALID_STATE",
            "Yacht is referenced by a live charter request or agreement",
        )
    y["status"] = "DELISTED"
    mutate(y)
    return respond_object(ser_yacht(y))


@bp.route("/yachts/<yid>/availability-blocks", methods=["GET"])
def list_blocks(yid):
    get_or_404("yachts", yid, "Yacht")
    items = [b for b in db["availability_blocks"].values() if b["yacht_id"] == yid]
    v = request.args.get("status")
    if v is not None:
        items = [b for b in items if b["status"] == v]
    return respond_paginated([ser_block(b) for b in sort_created(items)])


@bp.route("/yachts/<yid>/availability-blocks", methods=["POST"])
def create_block(yid):
    require_roles("Operator")
    y = get_or_404("yachts", yid, "Yacht")
    _own_yacht_or_403(y)
    op = _owning_operator(y)
    if op is None or op["status"] != "ACTIVE":
        raise api_err("ERR_OPERATOR_SUSPENDED", "Operator is SUSPENDED")
    body = body_json()
    block_type = req_field(body, "block_type")
    if block_type not in MANUAL_BLOCK_TYPES:
        # CHARTER is system-only; any other value is an invalid enum member
        raise api_err(
            "ERR_INVALID_REQUEST",
            "block_type must be MAINTENANCE or OPERATOR_HOLD",
        )
    start = as_date(req_field(body, "start_date"), "start_date")
    end = as_date(req_field(body, "end_date"), "end_date")
    if end <= start:
        raise api_err("ERR_INVALID_REQUEST", "end_date must be after start_date")
    expected = as_int(
        req_field(body, "expected_yacht_version"), "expected_yacht_version"
    )
    # OCC guard runs before the calendar rules (PRD §3.2)
    if expected != y["version"]:
        raise api_err("ERR_STALE_VERSION", "Yacht version has advanced; re-read")
    calendar_check(yid, start, end)
    b = new_record()
    b.update({
        "yacht_id": yid,
        "charter_agreement_id": None,
        "block_type": block_type,
        "start_date": start,
        "end_date": end,
        "status": "ACTIVE",
    })
    db["availability_blocks"][b["id"]] = b
    mutate(y)  # calendar changed
    return respond_object(ser_block(b), 201)


@bp.route("/availability-blocks/<bid>/release", methods=["POST"])
def release_block(bid):
    require_roles("Operator")
    b = get_or_404("availability_blocks", bid, "AvailabilityBlock")
    y = db["yachts"].get(b["yacht_id"])
    if y is None or y["operator_id"] != g.user_id:
        raise api_err("ERR_FORBIDDEN", "Caller does not own this block's yacht")
    if b["status"] != "ACTIVE":
        raise api_err("ERR_INVALID_STATE", "Block is not ACTIVE")
    if b["block_type"] == "CHARTER":
        raise api_err(
            "ERR_INVALID_STATE",
            "CHARTER blocks are released only by the cancellation cascade",
        )
    b["status"] = "RELEASED"
    mutate(b)
    mutate(y)  # calendar changed
    return respond_object(ser_block(b))
