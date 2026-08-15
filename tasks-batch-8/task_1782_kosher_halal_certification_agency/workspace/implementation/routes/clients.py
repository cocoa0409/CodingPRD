"""AgencyClient endpoints (PRD §3.1)."""
from flask import Blueprint, g

from db import new_common, store, touch
from errors import err
from middleware import get_or_404, require_roles
from response import created, list_response, ok
from services.domain import revoke_client_certificates
from validation import body_json, req_enum, req_str

bp = Blueprint("clients", __name__)

SCHEMES = ("KOSHER", "HALAL", "DUAL")
CLIENT_TERMINAL_EXIT_SOURCES = ("PROSPECT", "APPLICANT", "CERTIFIED", "SUSPENDED")


@bp.post("/clients")
def create_client():
    data = body_json()
    legal_name = req_str(data, "legal_name")
    scheme = req_enum(data, "certification_scheme", SCHEMES)
    contact_email = req_str(data, "contact_email")
    require_roles("AccountManager")
    client = new_common({
        "legal_name": legal_name,
        "certification_scheme": scheme,
        "contact_email": contact_email,
        "status": "PROSPECT",
        "open_nc_score": 0,
        "risk_tier": "LOW",
        "total_billed_cents": 0,
    })
    store.clients[client["id"]] = client
    return created(client)


@bp.get("/clients")
def list_clients():
    from response import Paginator
    p = Paginator()
    rows = list(store.clients.values())
    rows = p.filter(rows, "status")
    rows = p.filter(rows, "certification_scheme")
    return ok(p(rows), rtype="array", pagination=p)


@bp.get("/clients/<client_id>")
def get_client(client_id):
    return ok(get_or_404(store.clients, client_id, "Client"))


@bp.post("/clients/<client_id>/submit-application")
def submit_application(client_id):
    require_roles("ClientContact")
    # Scope: the ClientContact's X-User-ID IS the client id (PRD §2.1).
    if g.user_id != client_id:
        err("ERR_CLIENT_SCOPE_VIOLATION",
            "ClientContact may only submit its own application")
    client = get_or_404(store.clients, client_id, "Client")
    if client["status"] != "PROSPECT":
        err("ERR_CLIENT_INVALID_STATE",
            "submit-application requires client status PROSPECT")
    client["status"] = "APPLICANT"
    touch(client)
    return ok(client)


def _client_terminal_exit(client, target_status):
    for cert in store.certificates.values():
        if (cert["client_id"] == client["id"]
                and cert["status"] in ("DRAFT", "ACTIVE", "SUSPENDED")):
            cert["status"] = "REVOKED"
            touch(cert)
    client["status"] = target_status
    touch(client)


@bp.post("/clients/<client_id>/withdraw")
def withdraw_client(client_id):
    require_roles("ClientContact")
    if g.user_id != client_id:
        err("ERR_CLIENT_SCOPE_VIOLATION",
            "ClientContact may only withdraw its own client record")
    client = get_or_404(store.clients, client_id, "Client")
    if client["status"] not in CLIENT_TERMINAL_EXIT_SOURCES:
        err("ERR_CLIENT_INVALID_STATE",
            "withdraw requires client status PROSPECT, APPLICANT, CERTIFIED or SUSPENDED")
    _client_terminal_exit(client, "WITHDRAWN")
    return ok(client)


@bp.post("/clients/<client_id>/terminate")
def terminate_client(client_id):
    require_roles("CertificateOfficer")
    client = get_or_404(store.clients, client_id, "Client")
    if client["status"] not in CLIENT_TERMINAL_EXIT_SOURCES:
        err("ERR_CLIENT_INVALID_STATE",
            "terminate requires client status PROSPECT, APPLICANT, CERTIFIED or SUSPENDED")
    _client_terminal_exit(client, "TERMINATED")
    return ok(client)
