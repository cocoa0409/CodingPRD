"""Client routes: register, fetch, list, dispute-no-show (PRD §3.2, §3.4)."""
from flask import Blueprint, request

import db
from errors import err
from lookups import get_or_404, get_salon
from response import success
from util import stamp_create, touch, public
import validate as v
from calculations import no_show_forfeit
from routes.common import auth, json_body, list_response, ALL_ROLES

bp = Blueprint("clients", __name__)

STATUSES = {"ACTIVE", "SUSPENDED", "ARCHIVED"}


def _email_taken(salon_id, email, exclude_id=None):
    """Email unique per salon, case-insensitive, among non-ARCHIVED clients."""
    lowered = email.strip().lower()
    for c in db.clients.values():
        if c["salon_id"] != salon_id:
            continue
        if c["id"] == exclude_id:
            continue
        if c["status"] == "ARCHIVED":
            continue
        if c["email"].strip().lower() == lowered:
            return True
    return False


@bp.post("/clients")
def create_client():
    auth(("SalonOwner", "FrontDesk", "Client"))
    body = json_body()
    v.require_object(body)

    salon_id = v.req_str(body, "salon_id")
    salon = get_salon(salon_id)

    full_name = v.req_str(body, "full_name")
    email = v.req_str(body, "email")
    status = v.opt_enum(body, "status", STATUSES, default="ACTIVE")

    if _email_taken(salon["id"], email):
        raise err("ERR_INVALID_REQUEST", "email already in use within this salon")

    client = {
        "salon_id": salon["id"],
        "full_name": full_name,
        "email": email,
        "status": status,
        "no_show_strikes": 0,
        "wallet_credit_cents": 0,
    }
    stamp_create(client)
    db.clients[client["id"]] = client
    return success(public(client), status=201)


@bp.get("/clients/<client_id>")
def get_client(client_id):
    auth(ALL_ROLES)
    client = get_or_404(db.clients, client_id)
    return success(public(client), status=200)


@bp.get("/clients")
def list_clients():
    auth(("SalonOwner", "FrontDesk"))
    salon_id = request.args.get("salon_id")
    status = request.args.get("status")

    def pred(c):
        if salon_id is not None and c["salon_id"] != salon_id:
            return False
        if status is not None:
            return c["status"] == status
        # archived excluded unless explicitly requested (PRD endpoint note)
        return c["status"] != "ARCHIVED"

    page, meta = list_response(db.clients, pred)
    return success(page, status=200, response_type="array", pagination=meta)


@bp.post("/clients/<client_id>/dispute-no-show")
def dispute_no_show(client_id):
    auth(("SalonOwner",))
    client = get_or_404(db.clients, client_id)
    body = json_body()
    v.require_object(body)

    appointment_id = v.req_str(body, "appointment_id")
    appointment = db.appointments.get(appointment_id)

    # ERR_DISPUTE_TARGET_INVALID: cited appointment must be a NO_SHOW belonging
    # to this client, and the client must have a strike to reverse (PRD §3.4).
    if (
        appointment is None
        or appointment["client_id"] != client["id"]
        or appointment["status"] != "NO_SHOW"
        or client["no_show_strikes"] <= 0
    ):
        raise err("ERR_DISPUTE_TARGET_INVALID", "no reversible no-show for this client")

    salon = db.salons[client["salon_id"]]

    # Decrement strike (never below zero).
    client["no_show_strikes"] = max(0, client["no_show_strikes"] - 1)
    # Lift auto-suspension if below threshold and currently suspended.
    if (
        client["no_show_strikes"] < salon["no_show_suspend_threshold"]
        and client["status"] == "SUSPENDED"
    ):
        client["status"] = "ACTIVE"
    # Credit back any forfeited no-show fee for the cited appointment.
    forfeited, _refund = no_show_forfeit(
        appointment["quoted_service_price_cents"],
        appointment["deposit_held_cents"],
        salon["no_show_fee_pct"],
    )
    client["wallet_credit_cents"] = client["wallet_credit_cents"] + forfeited
    touch(client)
    return success(public(client), status=200)
