"""Clients, intakes, consent records (PRD §3.2)."""
import re

from flask import Blueprint, request

import clock
import db
import helpers as h
import response
import util
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_UNAUTHORIZED,
)
from middleware import authenticate, require_role

bp = Blueprint("clients", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------

@bp.post("/practice/clients")
def create_client():
    caller = authenticate()
    require_role(caller, {"PracticeAdmin", "FrontDesk"})
    body = h.get_body()

    full_name = h.as_str(h.require(body, "full_name"), "full_name")
    email = h.as_str(h.require(body, "email"), "email")
    if not EMAIL_RE.match(email):
        raise ApiError(*ERR_INVALID_REQUEST, message="email invalid")
    hsa_balance_cents = h.opt(body, "hsa_balance_cents", 0)
    hsa_balance_cents = h.as_int(hsa_balance_cents, "hsa_balance_cents", minimum=0)

    # email unique among non-archived clients
    for c in db.clients.values():
        if not c["archived"] and c["email"] == email:
            raise ApiError(*ERR_INVALID_REQUEST, message="email not unique")

    ent = h.new_entity({
        "full_name": full_name,
        "email": email,
        "hsa_balance_cents": hsa_balance_cents,
        "wallet_credit_cents": 0,
        "no_show_strikes": 0,
        "archived": False,
    })
    db.clients[ent["id"]] = ent
    return response.success(h.public(ent), status=201)


@bp.get("/practice/clients")
def list_clients():
    caller = authenticate()
    require_role(caller, {"PracticeAdmin", "FrontDesk"})
    limit, offset = h.get_pagination()
    items = list(db.clients.values())
    page, total = h.paginate(items, limit, offset)
    return response.list_success([h.public(c) for c in page], limit, offset, total)


@bp.get("/practice/clients/<id>")
def get_client(id):
    caller = authenticate()
    require_role(caller, {"PracticeAdmin", "FrontDesk", "Client"})
    ent = h.resolve(db.clients, id)
    # A Client may read only its own client record
    if caller.role == "Client" and caller.user_id != ent["id"]:
        raise ApiError(*ERR_UNAUTHORIZED, message="not owner")
    return response.success(h.public(ent))


@bp.post("/practice/clients/<id>/wallet-adjustments")
def adjust_wallet(id):
    caller = authenticate()
    require_role(caller, {"PracticeAdmin"})
    ent = h.resolve(db.clients, id)
    body = h.get_body()
    delta_cents = h.as_int(h.require(body, "delta_cents"), "delta_cents")
    new_balance = ent["wallet_credit_cents"] + delta_cents
    if new_balance < 0:
        new_balance = 0
    ent["wallet_credit_cents"] = new_balance
    h.touch(ent)
    return response.success(h.public(ent))


# ---------------------------------------------------------------------------
# Intakes
# ---------------------------------------------------------------------------

@bp.post("/practice/intakes")
def create_intake():
    caller = authenticate()
    require_role(caller, {"PracticeAdmin", "FrontDesk", "Client"})
    body = h.get_body()

    client_id = h.as_str(h.require(body, "client_id"), "client_id")
    client = h.resolve(db.clients, client_id)
    expires_at = util.parse_iso(h.require(body, "expires_at"))
    risk_flags = h.opt(body, "risk_flags", [])
    if not isinstance(risk_flags, list):
        raise ApiError(*ERR_INVALID_REQUEST, message="risk_flags must be a list")

    # A Client may create only against itself (entity-backed ownership).
    if caller.role == "Client" and caller.user_id != client_id:
        raise ApiError(*ERR_UNAUTHORIZED, message="not owner")

    ent = h.new_entity({
        "client_id": client_id,
        "expires_at": util.iso_format(expires_at),
        "risk_flags": list(risk_flags),
        "intake_status": "DRAFT",
        "signed_at": None,
    })
    db.intakes[ent["id"]] = ent
    return response.success(h.public(ent), status=201)


@bp.get("/practice/intakes")
def list_intakes():
    caller = authenticate()
    require_role(caller, {"PracticeAdmin", "FrontDesk", "Client"})
    limit, offset = h.get_pagination()
    client_id = request.args.get("client_id")
    items = list(db.intakes.values())
    if client_id is not None:
        items = [i for i in items if i["client_id"] == client_id]
    if caller.role == "Client":
        items = [i for i in items if i["client_id"] == caller.user_id]
    page, total = h.paginate(items, limit, offset)
    return response.list_success([h.public(i) for i in page], limit, offset, total)


@bp.get("/practice/intakes/<id>")
def get_intake(id):
    caller = authenticate()
    require_role(caller, {"PracticeAdmin", "FrontDesk", "Client"})
    ent = h.resolve(db.intakes, id)
    if caller.role == "Client" and caller.user_id != ent["client_id"]:
        raise ApiError(*ERR_UNAUTHORIZED, message="not owner")
    return response.success(h.public(ent))


@bp.post("/practice/intakes/<id>/sign")
def sign_intake(id):
    caller = authenticate()
    require_role(caller, {"Client", "FrontDesk"})
    ent = h.resolve(db.intakes, id)
    # The client signs their OWN intake.
    if caller.role == "Client" and caller.user_id != ent["client_id"]:
        raise ApiError(*ERR_UNAUTHORIZED, message="not owner")
    # allowed only while DRAFT
    if ent["intake_status"] != "DRAFT":
        raise ApiError(*ERR_INVALID_STATE, message="intake not DRAFT")

    # Supersede any prior ACTIVE intake the client had.
    for other in db.intakes.values():
        if (other["id"] != ent["id"] and other["client_id"] == ent["client_id"]
                and other["intake_status"] == "ACTIVE"):
            other["intake_status"] = "SUPERSEDED"
            h.touch(other)

    ent["intake_status"] = "ACTIVE"
    ent["signed_at"] = util.now_iso()
    h.touch(ent)
    return response.success(h.public(ent))


# ---------------------------------------------------------------------------
# Consent records
# ---------------------------------------------------------------------------

DRAPING = {"FULL_DRAPE", "PARTIAL_DRAPE", "DECLINE_TREATMENT"}


@bp.post("/practice/consent-records")
def create_consent():
    caller = authenticate()
    require_role(caller, {"PracticeAdmin", "FrontDesk", "Client"})
    body = h.get_body()

    client_id = h.as_str(h.require(body, "client_id"), "client_id")
    client = h.resolve(db.clients, client_id)
    draping_policy = h.require(body, "draping_policy")
    h.enum(draping_policy, "draping_policy", DRAPING)
    sensitive_area_consent = h.opt(body, "sensitive_area_consent", False)
    if not isinstance(sensitive_area_consent, bool):
        raise ApiError(*ERR_INVALID_REQUEST, message="sensitive_area_consent must be boolean")

    if caller.role == "Client" and caller.user_id != client_id:
        raise ApiError(*ERR_UNAUTHORIZED, message="not owner")

    ent = h.new_entity({
        "client_id": client_id,
        "draping_policy": draping_policy,
        "sensitive_area_consent": sensitive_area_consent,
        "consent_status": "ACTIVE",
    })
    db.consent_records[ent["id"]] = ent
    return response.success(h.public(ent), status=201)


@bp.get("/practice/consent-records")
def list_consent():
    caller = authenticate()
    require_role(caller, {"PracticeAdmin", "FrontDesk", "Client"})
    limit, offset = h.get_pagination()
    client_id = request.args.get("client_id")
    items = list(db.consent_records.values())
    if client_id is not None:
        items = [c for c in items if c["client_id"] == client_id]
    if caller.role == "Client":
        items = [c for c in items if c["client_id"] == caller.user_id]
    page, total = h.paginate(items, limit, offset)
    return response.list_success([h.public(c) for c in page], limit, offset, total)


@bp.get("/practice/consent-records/<id>")
def get_consent(id):
    caller = authenticate()
    require_role(caller, {"PracticeAdmin", "FrontDesk", "Client"})
    ent = h.resolve(db.consent_records, id)
    if caller.role == "Client" and caller.user_id != ent["client_id"]:
        raise ApiError(*ERR_UNAUTHORIZED, message="not owner")
    return response.success(h.public(ent))


@bp.post("/practice/consent-records/<id>/revoke")
def revoke_consent(id):
    caller = authenticate()
    require_role(caller, {"Client", "PracticeAdmin"})
    ent = h.resolve(db.consent_records, id)
    # revoke only own consent (for Client role)
    if caller.role == "Client" and caller.user_id != ent["client_id"]:
        raise ApiError(*ERR_UNAUTHORIZED, message="not owner")
    # allowed only from ACTIVE
    if ent["consent_status"] != "ACTIVE":
        raise ApiError(*ERR_INVALID_STATE, message="consent not ACTIVE")

    ent["consent_status"] = "REVOKED"
    h.touch(ent)

    # Cascade-cancel referencing appointments in SCHEDULED or CHECKED_IN.
    from services.appointments import cancel_for_consent_revoke
    for appt in db.appointments.values():
        if (appt.get("consent_id") == ent["id"]
                and appt["scheduling_status"] in ("SCHEDULED", "CHECKED_IN")):
            cancel_for_consent_revoke(appt)

    return response.success(h.public(ent))
