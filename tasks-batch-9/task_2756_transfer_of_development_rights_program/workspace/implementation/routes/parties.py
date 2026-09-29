"""Party endpoints (PRD 3.3)."""

from flask import Blueprint

import serializers
from core import db, new_record, respond_object, touch
from errors import fail
from listing import match, paged
from middleware import ADMIN, ALL_ROLES, STAFF_ROLES, require_roles
from services.derive import recompute_party_holdings
from validators import body, field_cents, field_enum, field_int, field_str, filter_enum

bp = Blueprint("parties", __name__)

KINDS = ("LANDOWNER", "DEVELOPER", "MUNICIPAL_BANK")
STATUSES = ("ACTIVE", "SUSPENDED")
ACTIONS = ("CREDIT", "DEBIT", "SUSPEND", "REINSTATE")


def get_party_or_404(party_id):
    party = db.parties.get(party_id)
    if party is None:
        fail("ERR_PARTY_NOT_FOUND", "party %s does not exist" % party_id)
    return party


@bp.post("/tdr/parties")
def create_party():
    require_roles(ADMIN)
    data = body()
    kind = field_enum(data, "kind", KINDS)
    legal_name = field_str(data, "legal_name", min_len=1, max_len=120)
    contact_email = field_str(data, "contact_email", min_len=1)
    if "@" not in contact_email:
        fail("ERR_INVALID_REQUEST", "contact_email must contain '@'")
    neighborhood_code = field_str(data, "neighborhood_code", required=False, min_len=1, max_len=24)
    if kind == "MUNICIPAL_BANK":
        for existing in db.parties.values():
            if existing["kind"] == "MUNICIPAL_BANK":
                fail("ERR_INVALID_REQUEST", "a MUNICIPAL_BANK party already exists")

    rec = new_record(
        {
            "kind": kind,
            "legal_name": legal_name,
            "contact_email": contact_email,
            "neighborhood_code": neighborhood_code,
            "cash_balance_cents": 0,
            "fee_revenue_cents": 0,
            "units_held": 0,
            "certificates_held_count": 0,
            "status": "ACTIVE",
        }
    )
    db.parties[rec["id"]] = rec
    return respond_object(serializers.party(rec), 201)


@bp.get("/tdr/parties/<party_id>")
def get_party(party_id):
    require_roles(*ALL_ROLES)
    return respond_object(serializers.party(get_party_or_404(party_id)))


@bp.get("/tdr/parties")
def list_parties():
    require_roles(*STAFF_ROLES)
    rows = match(list(db.parties.values()), kind=filter_enum("kind", KINDS), status=filter_enum("status", STATUSES))
    return paged(rows, serializers.party)


@bp.post("/tdr/parties/<party_id>/account-actions")
def account_action(party_id):
    require_roles(ADMIN)
    party = get_party_or_404(party_id)
    data = body()
    action = field_enum(data, "action", ACTIONS)
    amount_cents = field_cents(data, "amount_cents", required=False)
    expected_version = field_int(data, "expected_party_version")
    field_str(data, "note", required=False)

    if action in ("CREDIT", "DEBIT") and amount_cents is None:
        fail("ERR_INVALID_REQUEST", "amount_cents is required for %s" % action)
    if action in ("SUSPEND", "REINSTATE") and amount_cents is not None:
        fail("ERR_INVALID_REQUEST", "amount_cents must be omitted for %s" % action)

    if expected_version != party["version"]:
        fail("ERR_STALE_PARENT_VERSION", "party version is %s" % party["version"])

    if action == "CREDIT":
        party["cash_balance_cents"] = int(party["cash_balance_cents"]) + int(amount_cents)
    elif action == "DEBIT":
        if int(party["cash_balance_cents"]) - int(amount_cents) < 0:
            fail("ERR_INSUFFICIENT_FUNDS", "debit would drive the balance below zero")
        party["cash_balance_cents"] = int(party["cash_balance_cents"]) - int(amount_cents)
    elif action == "SUSPEND":
        party["status"] = "SUSPENDED"
    else:
        party["status"] = "ACTIVE"

    recompute_party_holdings(party)
    touch(party)
    return respond_object(serializers.party(party))
