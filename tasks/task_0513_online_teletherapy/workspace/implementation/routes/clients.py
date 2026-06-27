"""Client routes: registration, intake, clear-intake, and nested list endpoints."""
from flask import Blueprint, request

from db import db, common_create_fields, touch
from clock import clock, iso_millis
from errors import err, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from middleware import get_auth, require_role
from lookup import get_or_404, check_client_owner, paginate
from validate import (
    require_body, require_string, require_enum, require_int,
    require_string_array_subset, require_bool, STATE_CODES, SPECIALTIES,
)
import serialize
from response import success, list_success

bp = Blueprint("clients", __name__)


@bp.route("/clients", methods=["POST"])
def create_client():
    user_id, role = get_auth()
    require_role(role, {"Client"})
    data = require_body(request.get_json(silent=True))
    email = require_string(data, "email")
    full_name = require_string(data, "full_name")
    state_code = require_enum(data, "state_code", STATE_CODES)
    email_norm = email.lower()
    client = {
        **common_create_fields(),
        "email": email_norm,
        "full_name": full_name,
        "state_code": state_code,
        "status": "PENDING_INTAKE",
        "financial_aid_tier": "NONE",
        "wallet_credit_cents": 0,
        "risk_flag": "NONE",
    }
    db.clients[client["id"]] = client
    return success(serialize.client_out(client), status=201)


@bp.route("/clients/<cid>", methods=["GET"])
def get_client(cid):
    user_id, role = get_auth()
    require_role(role, {"Client", "Therapist", "ClinicalAdmin", "BillingAdmin"})
    client = get_or_404(db.clients, cid)
    check_client_owner(role, user_id, cid)
    return success(serialize.client_out(client))


@bp.route("/clients", methods=["GET"])
def list_clients():
    user_id, role = get_auth()
    require_role(role, {"ClinicalAdmin", "BillingAdmin"})
    status = request.args.get("status")
    items = [c for c in db.clients.values() if status is None or c["status"] == status]
    items.sort(key=lambda c: (c["created_at"], c["_seq"]))
    page, lim, off, total = paginate(items, request.args)
    return list_success([serialize.client_out(c) for c in page], lim, off, total)


@bp.route("/clients/<cid>/intake", methods=["POST"])
def submit_intake(cid):
    user_id, role = get_auth()
    require_role(role, {"Client"})
    client = get_or_404(db.clients, cid)
    check_client_owner(role, user_id, cid)
    data = require_body(request.get_json(silent=True))
    concerns = require_string_array_subset(data, "presenting_concerns", SPECIALTIES, non_empty=True)
    severity = require_int(data, "severity_score", minimum=0, maximum=10)
    crisis = require_bool(data, "crisis_indicator", default=False)
    # state check
    if client["status"] != "PENDING_INTAKE":
        raise err(ERR_INVALID_STATE, "Client not in PENDING_INTAKE")
    # one intake of record per client
    existing = [i for i in db.intakes.values() if i["client_id"] == cid]
    if existing:
        raise err(ERR_INVALID_STATE, "Intake already submitted for this client")
    intake = {
        **common_create_fields(),
        "client_id": cid,
        "presenting_concerns": concerns,
        "severity_score": severity,
        "crisis_indicator": crisis,
        "submitted_at": iso_millis(clock.now()),
    }
    db.intakes[intake["id"]] = intake
    # safety gate
    gate_fires = crisis or severity >= 8
    if not gate_fires:
        client["status"] = "AWAITING_MATCH"
    touch(client)
    return success(serialize.intake_out(intake), status=201)


@bp.route("/clients/<cid>/intake", methods=["GET"])
def get_intake(cid):
    user_id, role = get_auth()
    require_role(role, {"Client", "ClinicalAdmin"})
    get_or_404(db.clients, cid)
    check_client_owner(role, user_id, cid)
    items = [i for i in db.intakes.values() if i["client_id"] == cid]
    items.sort(key=lambda i: (i["created_at"], i["_seq"]))
    return success([serialize.intake_out(i) for i in items], response_type="array")


@bp.route("/clients/<cid>/clear-intake", methods=["POST"])
def clear_intake(cid):
    user_id, role = get_auth()
    require_role(role, {"ClinicalAdmin"})
    client = get_or_404(db.clients, cid)
    if client["status"] != "PENDING_INTAKE":
        raise err(ERR_INVALID_STATE, "Client not in PENDING_INTAKE")
    intake = [i for i in db.intakes.values() if i["client_id"] == cid]
    if not intake:
        raise err(ERR_INVALID_STATE, "No intake exists for this client")
    client["status"] = "AWAITING_MATCH"
    touch(client)
    return success(serialize.client_out(client))


@bp.route("/clients/<cid>/subscriptions", methods=["GET"])
def list_client_subscriptions(cid):
    user_id, role = get_auth()
    require_role(role, {"Client", "BillingAdmin"})
    get_or_404(db.clients, cid)
    check_client_owner(role, user_id, cid)
    items = [s for s in db.subscriptions.values() if s["client_id"] == cid]
    items.sort(key=lambda s: (s["created_at"], s["_seq"]))
    page, lim, off, total = paginate(items, request.args)
    return list_success([serialize.subscription_out(s) for s in page], lim, off, total)


@bp.route("/clients/<cid>/session-credits", methods=["GET"])
def list_client_credits(cid):
    user_id, role = get_auth()
    require_role(role, {"Client", "ClinicalAdmin", "BillingAdmin"})
    get_or_404(db.clients, cid)
    check_client_owner(role, user_id, cid)
    status = request.args.get("status")
    items = [c for c in db.session_credits.values()
             if c["client_id"] == cid and (status is None or c["status"] == status)]
    items.sort(key=lambda c: (c["created_at"], c["_seq"]))
    page, lim, off, total = paginate(items, request.args)
    return list_success([serialize.session_credit_out(c) for c in page], lim, off, total)


@bp.route("/clients/<cid>/crisis-escalations", methods=["GET"])
def list_client_escalations(cid):
    user_id, role = get_auth()
    require_role(role, {"Client", "Therapist", "ClinicalAdmin"})
    get_or_404(db.clients, cid)
    check_client_owner(role, user_id, cid)
    items = [e for e in db.crisis_escalations.values() if e["client_id"] == cid]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    page, lim, off, total = paginate(items, request.args)
    return list_success([serialize.crisis_out(e) for e in page], lim, off, total)


@bp.route("/clients/<cid>/financial-aid-applications", methods=["GET"])
def list_client_aid(cid):
    user_id, role = get_auth()
    require_role(role, {"Client", "BillingAdmin"})
    get_or_404(db.clients, cid)
    check_client_owner(role, user_id, cid)
    items = [a for a in db.aid_applications.values() if a["client_id"] == cid]
    items.sort(key=lambda a: (a["created_at"], a["_seq"]))
    page, lim, off, total = paginate(items, request.args)
    return list_success([serialize.aid_out(a) for a in page], lim, off, total)


@bp.route("/clients/<cid>/superbills", methods=["GET"])
def list_client_superbills(cid):
    user_id, role = get_auth()
    require_role(role, {"Client", "BillingAdmin"})
    get_or_404(db.clients, cid)
    check_client_owner(role, user_id, cid)
    items = [s for s in db.superbills.values() if s["client_id"] == cid]
    items.sort(key=lambda s: (s["created_at"], s["_seq"]))
    page, lim, off, total = paginate(items, request.args)
    return list_success([serialize.superbill_out(s) for s in page], lim, off, total)
