"""Routes: logical clock, operators, brokers, clients (+ resume workflow)."""

from flask import Blueprint, g

from httpkit import (api_err, as_enum, as_nonneg_int, as_str, body_json,
                     get_or_404, req_field, require_roles, respond_object)
from serializers import ser_broker, ser_client, ser_operator
from services import clock_sweep
from store import clock, db, mutate, new_record
from util import fmt_ts, parse_dt

bp = Blueprint("core", __name__)

RESUME_CLASSES = ("NONE", "COASTAL", "OFFSHORE", "OCEAN")
BROKER_TYPES = ("CENTRAL_AGENT", "RETAIL_BROKER", "BOTH")


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.5)
# ---------------------------------------------------------------------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles("PlatformAdmin")
    body = body_json()
    raw = req_field(body, "to_iso8601")
    dt = parse_dt(raw)
    if dt is None:
        raise api_err(
            "ERR_INVALID_REQUEST", "to_iso8601 must be a valid ISO 8601 timestamp"
        )
    clock.set(dt)
    clock_sweep()  # GRANTED permits past valid_until -> EXPIRED (+ leg roll-up)
    return respond_object({"current_utc": fmt_ts(clock.now())})


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

@bp.route("/operators", methods=["POST"])
def create_operator():
    require_roles("PlatformAdmin")
    body = body_json()
    name = as_str(req_field(body, "name"), "name")
    home_port = as_str(req_field(body, "home_port"), "home_port")
    op = new_record()
    op.update({"name": name, "home_port": home_port, "status": "ACTIVE"})
    db["operators"][op["id"]] = op
    return respond_object(ser_operator(op), 201)


@bp.route("/operators/<oid>/suspend", methods=["POST"])
def suspend_operator(oid):
    require_roles("PlatformAdmin")
    op = get_or_404("operators", oid, "Operator")
    if op["status"] != "ACTIVE":
        raise api_err("ERR_INVALID_STATE", "Operator is not ACTIVE")
    op["status"] = "SUSPENDED"
    mutate(op)
    return respond_object(ser_operator(op))


@bp.route("/operators/<oid>/reactivate", methods=["POST"])
def reactivate_operator(oid):
    require_roles("PlatformAdmin")
    op = get_or_404("operators", oid, "Operator")
    if op["status"] != "SUSPENDED":
        raise api_err("ERR_INVALID_STATE", "Operator is not SUSPENDED")
    op["status"] = "ACTIVE"
    mutate(op)
    return respond_object(ser_operator(op))


# ---------------------------------------------------------------------------
# Brokers
# ---------------------------------------------------------------------------

@bp.route("/brokers", methods=["POST"])
def create_broker():
    require_roles("PlatformAdmin")
    body = body_json()
    display_name = as_str(req_field(body, "display_name"), "display_name")
    broker_type = as_enum(req_field(body, "broker_type"), BROKER_TYPES, "broker_type")
    license_no = as_str(req_field(body, "license_no"), "license_no")
    b = new_record()
    b.update({
        "display_name": display_name,
        "broker_type": broker_type,
        "license_no": license_no,
    })
    db["brokers"][b["id"]] = b
    return respond_object(ser_broker(b), 201)


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------

@bp.route("/clients", methods=["POST"])
def create_client():
    require_roles("PlatformAdmin")
    body = body_json()
    full_name = as_str(req_field(body, "full_name"), "full_name")
    email = as_str(req_field(body, "email"), "email")
    c = new_record()
    c.update({
        "full_name": full_name,
        "email": email,
        "qualification_status": "UNVERIFIED",
        "resume_class": None,
        "skippered_hours": None,
        "resume_submitted_at": None,
    })
    db["clients"][c["id"]] = c
    return respond_object(ser_client(c), 201)


@bp.route("/clients/<cid>", methods=["GET"])
def get_client(cid):
    c = get_or_404("clients", cid, "Client")
    return respond_object(ser_client(c))


@bp.route("/clients/<cid>/resume/submit", methods=["POST"])
def submit_resume(cid):
    require_roles("Client")
    c = get_or_404("clients", cid, "Client")
    if g.user_id != c["id"]:
        raise api_err("ERR_FORBIDDEN", "Only the client may submit their resume")
    if c["qualification_status"] not in ("UNVERIFIED", "REJECTED"):
        raise api_err(
            "ERR_INVALID_STATE",
            "Resume submission requires UNVERIFIED or REJECTED status",
        )
    body = body_json()
    resume_class = as_enum(
        req_field(body, "resume_class"), RESUME_CLASSES, "resume_class"
    )
    hours = as_nonneg_int(req_field(body, "skippered_hours"), "skippered_hours")
    c["resume_class"] = resume_class
    c["skippered_hours"] = hours
    c["resume_submitted_at"] = clock.now()
    c["qualification_status"] = "PENDING_REVIEW"
    mutate(c)
    return respond_object(ser_client(c))


@bp.route("/clients/<cid>/resume/review", methods=["POST"])
def review_resume(cid):
    require_roles("PlatformAdmin")
    c = get_or_404("clients", cid, "Client")
    if c["qualification_status"] != "PENDING_REVIEW":
        raise api_err("ERR_INVALID_STATE", "Client is not PENDING_REVIEW")
    body = body_json()
    outcome = as_enum(req_field(body, "outcome"), ("QUALIFIED", "REJECTED"), "outcome")
    c["qualification_status"] = outcome
    mutate(c)
    return respond_object(ser_client(c))
