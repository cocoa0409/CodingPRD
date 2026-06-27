"""Client endpoints + ledger-entry reads (§3.1, §3.2, §2.8)."""

from flask import Blueprint, request

import db
import errors
from common import public, req_str, req_number, opt_number, opt_int, stamp_common, touch
from middleware import authenticate, authorize, ALL_ROLES
from response import success
from routes.helpers import get_body, lookup, list_response
from services import ledger
from services.views import client_view

bp = Blueprint("clients", __name__)


@bp.post("/factoring/clients")
def create_client():
    _, role = authenticate()
    authorize(role, ("PlatformAdmin", "UnderwritingOfficer"))
    body = get_body()
    program_id = req_str(body, "program_id")
    legal_name = req_str(body, "legal_name")
    # FK existence (priority 4) before structural rate range (priority 5).
    program = db.programs.get(program_id)
    if program is None:
        raise errors.not_found("program_id does not resolve")
    rate = req_number(body, "requested_advance_rate_pct")
    if not (0 < rate < 1):
        raise errors.invalid_request("requested_advance_rate_pct must be strictly between 0 and 1")

    client = {
        "program_id": program_id,
        "legal_name": legal_name,
        "requested_advance_rate_pct": rate,
        "approved_advance_rate_pct": None,
        "credit_limit_cents": None,
        "default_concentration_limit_pct": None,
        "reserve_balance_cents": 0,
        "funded_advance_outstanding_cents": 0,
        "credit_decision_user_id": None,
        "status": "PENDING",
    }
    stamp_common(client)
    db.clients[client["id"]] = client
    return success(public(client), status=201)


@bp.get("/factoring/clients")
def list_clients():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    records = []
    for c in db.clients.values():
        if program_id is not None and c["program_id"] != program_id:
            continue
        if status is not None and c["status"] != status:
            continue
        records.append(c)
    return list_response(records, view_fn=client_view)


@bp.get("/factoring/clients/<client_id>")
def read_client(client_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    client = lookup(db.clients, client_id)
    return success(client_view(client), status=200)


@bp.post("/factoring/clients/<client_id>/credit-decision")
def client_credit_decision(client_id):
    user_id, role = authenticate()
    authorize(role, ("UnderwritingOfficer",))
    client = lookup(db.clients, client_id)
    body = get_body()
    decision = req_str(body, "decision")
    if decision not in ("APPROVE", "REJECT"):
        raise errors.invalid_request("decision must be APPROVE or REJECT")

    if client["status"] != "PENDING":
        raise errors.invalid_state("Client is not PENDING")

    if decision == "APPROVE":
        program = db.programs.get(client["program_id"])
        # Structural checks (422) before state/business — program ACTIVE is a
        # business referential guard handled after structural validation.
        rate = req_number(body, "approved_advance_rate_pct")
        # credit_limit_cents and default_concentration_limit_pct required on approve.
        if "credit_limit_cents" not in body or body["credit_limit_cents"] is None:
            raise errors.invalid_request("credit_limit_cents is required on approve")
        limit = body["credit_limit_cents"]
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise errors.invalid_request("credit_limit_cents must be an integer")
        conc = req_number(body, "default_concentration_limit_pct")
        if not (0 < rate < 1):
            raise errors.invalid_request("approved_advance_rate_pct must be strictly between 0 and 1")
        if limit <= 0:
            raise errors.invalid_request("credit_limit_cents must be greater than zero")
        if not (0 < conc <= 1):
            raise errors.invalid_request("default_concentration_limit_pct must be > 0 and <= 1")
        if program is None or program["status"] != "ACTIVE":
            raise errors.invalid_state("Program is not ACTIVE")

        client["approved_advance_rate_pct"] = rate
        client["credit_limit_cents"] = limit
        client["default_concentration_limit_pct"] = conc
        client["credit_decision_user_id"] = user_id
        client["status"] = "APPROVED"
    else:
        client["status"] = "REJECTED"

    touch(client)
    return success(client_view(client), status=200)


@bp.post("/factoring/clients/<client_id>/suspend")
def suspend_client(client_id):
    _, role = authenticate()
    authorize(role, ("UnderwritingOfficer",))
    client = lookup(db.clients, client_id)
    if client["status"] != "APPROVED":
        raise errors.invalid_state("Client is not APPROVED")
    client["status"] = "SUSPENDED"
    touch(client)
    return success(client_view(client), status=200)


@bp.post("/factoring/clients/<client_id>/reinstate")
def reinstate_client(client_id):
    _, role = authenticate()
    authorize(role, ("UnderwritingOfficer",))
    client = lookup(db.clients, client_id)
    if client["status"] != "SUSPENDED":
        raise errors.invalid_state("Client is not SUSPENDED")
    client["status"] = "APPROVED"
    touch(client)
    return success(client_view(client), status=200)


@bp.post("/factoring/clients/<client_id>/close")
def close_client(client_id):
    _, role = authenticate()
    authorize(role, ("UnderwritingOfficer",))
    client = lookup(db.clients, client_id)
    if client["status"] not in ("APPROVED", "SUSPENDED"):
        raise errors.invalid_state("Client is not APPROVED or SUSPENDED")
    ledger.recompute_client_balances(client)
    if client["funded_advance_outstanding_cents"] != 0 or client["reserve_balance_cents"] != 0:
        raise errors.ApiError(errors.ERR_CLIENT_HAS_OUTSTANDING, 409,
                              "Client has nonzero outstanding advance or reserve")
    client["status"] = "CLOSED"
    touch(client)
    return success(client_view(client), status=200)


# --- LedgerEntry reads -----------------------------------------------------
@bp.get("/factoring/ledger-entries")
def list_ledger_entries():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    client_id = request.args.get("client_id")
    invoice_id = request.args.get("invoice_id")
    records = []
    for e in db.ledger_entries.values():
        if client_id is not None and e["client_id"] != client_id:
            continue
        if invoice_id is not None and e.get("invoice_id") != invoice_id:
            continue
        records.append(e)
    return list_response(records)


@bp.get("/factoring/ledger-entries/<ledger_entry_id>")
def read_ledger_entry(ledger_entry_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    entry = lookup(db.ledger_entries, ledger_entry_id)
    return success(public(entry), status=200)
