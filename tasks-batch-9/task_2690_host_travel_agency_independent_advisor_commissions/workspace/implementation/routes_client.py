"""Clients, client ownership and the append-only trust ledger (PRD 3.4)."""

from flask import Blueprint

import calc
from envelope import created, ok
from errors import ApiError
from guards import (authenticate, field_enum, field_int, field_state_code,
                    field_str, read_body)
from listing import list_response
from lookup import get_advisor, get_booking, get_client
from store import new_row, serialize, store, touch

bp = Blueprint("client", __name__)

READ_ROLES = ("HostOperations", "HostController", "ComplianceOfficer", "Advisor")


@bp.post("/clients")
def create_client():
    caller = authenticate(("Advisor", "HostOperations"))
    body = read_body(("owner_advisor_id", "full_name", "home_state_code",
                      "ownership_mode", "max_concurrent_trips"))
    owner_id = field_str(body, "owner_advisor_id")
    full_name = field_str(body, "full_name", max_len=200)
    state_code = field_state_code(body, "home_state_code")
    ownership_mode = field_enum(body, "ownership_mode",
                                ("HOST_OWNED", "ADVISOR_OWNED"),
                                required=False, default="HOST_OWNED")
    max_trips = field_int(body, "max_concurrent_trips", required=False, default=1,
                          minimum=1)

    advisor = get_advisor(owner_id)
    if caller.is_advisor and advisor["id"] != caller.user_id:
        raise ApiError("ERR_OWNERSHIP_VIOLATION")
    if advisor["status"] != "ACTIVE":
        raise ApiError("ERR_ADVISOR_NOT_ACTIVE")

    row = new_row({
        "owner_advisor_id": advisor["id"],
        "full_name": full_name,
        "home_state_code": state_code,
        "ownership_mode": ownership_mode,
        "portability_status": "RETAINED",
        "trust_balance_cents": 0,
        "max_concurrent_trips": max_trips,
    })
    store.clients[row["id"]] = row
    return created(serialize(row))


@bp.get("/clients/<client_id>")
def read_client(client_id):
    authenticate(READ_ROLES)
    client = get_client(client_id)
    calc.recompute_client_balance(client)
    return ok(serialize(client))


@bp.get("/clients")
def list_clients():
    authenticate(READ_ROLES)
    for client in store.clients.values():
        calc.recompute_client_balance(client)
    return list_response(store.clients.values(),
                         (("owner_advisor_id", "owner_advisor_id"),
                          ("ownership_mode", "ownership_mode"),
                          ("portability_status", "portability_status")))


# --------------------------------------------------------------------------
# trust ledger
# --------------------------------------------------------------------------

def append_trust_entry(client, direction, amount_cents, memo, booking_id,
                       recorded_by):
    """Append one immutable line and refresh the client's balance."""
    signed = amount_cents if direction == "DEPOSIT" else -amount_cents
    running = calc.recompute_client_balance(client)
    row = new_row({
        "client_id": client["id"],
        "booking_id": booking_id,
        "direction": direction,
        "amount_cents": amount_cents,
        "signed_amount_cents": signed,
        "balance_after_cents": running + signed,
        "memo": memo,
        "recorded_by_user_id": recorded_by,
    }, versioned=False)
    store.trust_entries[row["id"]] = row
    calc.recompute_client_balance(client)
    touch(client)
    return row


@bp.post("/clients/<client_id>/trust-ledger-entries")
def create_trust_entry(client_id):
    caller = authenticate(("Advisor", "HostController"))
    body = read_body(("direction", "amount_cents", "memo", "booking_id",
                      "expected_client_version"))
    direction = field_enum(body, "direction",
                           ("DEPOSIT", "DISBURSEMENT", "REFUND"))
    amount_cents = field_int(body, "amount_cents", minimum=1)
    memo = field_str(body, "memo", allow_empty=True, max_len=2000)
    booking_id = field_str(body, "booking_id", required=False)
    expected_version = field_int(body, "expected_client_version")

    client = get_client(client_id)
    if booking_id is not None:
        get_booking(booking_id)

    if caller.is_advisor and client["owner_advisor_id"] != caller.user_id:
        raise ApiError("ERR_OWNERSHIP_VIOLATION")

    if expected_version != client["version"]:
        raise ApiError("ERR_CLIENT_VERSION_STALE")

    if caller.is_advisor and direction != "DEPOSIT":
        raise ApiError("ERR_TRUST_DIRECTION_FORBIDDEN")

    running = calc.recompute_client_balance(client)
    if direction != "DEPOSIT" and running - amount_cents < 0:
        raise ApiError("ERR_TRUST_FUNDS_INSUFFICIENT")

    row = append_trust_entry(client, direction, amount_cents, memo, booking_id,
                             caller.user_id)
    return created(serialize(row))


@bp.get("/clients/<client_id>/trust-ledger-entries")
def list_client_trust_entries(client_id):
    authenticate(READ_ROLES)
    client = get_client(client_id)
    calc.recompute_client_balance(client)
    rows = [e for e in store.trust_entries.values() if e["client_id"] == client["id"]]
    return list_response(rows)


@bp.get("/bookings/<booking_id>/trust-ledger-entries")
def list_booking_trust_entries(booking_id):
    authenticate(READ_ROLES)
    booking = get_booking(booking_id)
    client = store.clients.get(booking["client_id"])
    if client is not None:
        calc.recompute_client_balance(client)
    rows = [e for e in store.trust_entries.values()
            if e["booking_id"] == booking["id"]]
    return list_response(rows)
