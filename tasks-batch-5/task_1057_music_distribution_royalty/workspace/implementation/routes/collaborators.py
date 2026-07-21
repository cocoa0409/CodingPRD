"""Collaborators (payees) — PRD §3.4."""

from flask import Blueprint, request

from db import db, common_fields, touch
from errors import ApiError
from middleware import auth, require_ownership
from response import created, ok, ok_list, paginate, read_pagination
from services import calc, core
import validation as v

bp = Blueprint("collaborators", __name__)

TAX_FORM_STATUSES = {"MISSING", "SUBMITTED", "VERIFIED", "EXPIRED"}
PAYOUT_METHODS = {"PAYPAL", "BANK_TRANSFER"}


def owned_collaborator(user_id, role, collaborator_id):
    row = db.collaborators.get(collaborator_id)
    if row is not None:
        if role == "Artist":
            require_ownership(user_id == row["artist_id"])
        elif role == "Collaborator":
            require_ownership(user_id == row["id"])
    return core.find_collaborator(collaborator_id)


@bp.post("/api/collaborators")
def create_collaborator():
    user_id, role = auth("Artist")
    data = v.body()
    if isinstance(data.get("artist_id"), str):
        require_ownership(user_id == data["artist_id"])

    artist_id = v.req_id(data, "artist_id")
    name = v.req_string(data, "name")
    email = v.req_string(data, "email")
    country_code = v.check_country(v.req_string(data, "country_code"))
    tax_form_status, has_tfs = v.opt_enum(data, "tax_form_status", TAX_FORM_STATUSES)
    payout_method, has_pm = v.opt_enum(data, "payout_method", PAYOUT_METHODS)

    core.find_artist(artist_id)

    if any(
        c["artist_id"] == artist_id and c["email"] == email
        for c in db.collaborators.values()
    ):
        raise ApiError("ERR_DUPLICATE_IDENTIFIER", "email already registered for this artist.")

    row = common_fields()
    row.update({
        "artist_id": artist_id,
        "name": name,
        "email": email,
        "country_code": country_code,
        "tax_form_status": tax_form_status if has_tfs else "MISSING",
        "payout_method": payout_method if has_pm else "PAYPAL",
        "withholding_bps": 0,
        "pending_payout_cents": 0,
        "lifetime_paid_cents": 0,
        "reversed_payout_cents": 0,
        "status": "ACTIVE",
    })
    row["withholding_bps"] = calc.withholding_bps(row)
    db.collaborators[row["id"]] = row
    return created(row)


@bp.get("/api/collaborators/<collaborator_id>")
def read_collaborator(collaborator_id):
    user_id, role = auth("Artist", "Collaborator", "FinanceOps", "PlatformAdmin")
    return ok(owned_collaborator(user_id, role, collaborator_id))


@bp.get("/api/collaborators")
def list_collaborators():
    user_id, role = auth("Artist", "FinanceOps", "PlatformAdmin")
    limit, offset = read_pagination(request.args)
    rows = list(db.collaborators.values())
    if role == "Artist":
        rows = [c for c in rows if c["artist_id"] == user_id]
    artist_id = request.args.get("artist_id")
    if artist_id is not None:
        rows = [c for c in rows if c["artist_id"] == artist_id]
    status = request.args.get("status")
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.patch("/api/collaborators/<collaborator_id>")
def update_collaborator(collaborator_id):
    user_id, role = auth("Artist", "FinanceOps")
    data = v.body()
    tax_form_status, has_tfs = v.opt_enum(data, "tax_form_status", TAX_FORM_STATUSES)
    payout_method, has_pm = v.opt_enum(data, "payout_method", PAYOUT_METHODS)
    country_code, has_cc = v.opt_string(data, "country_code", nullable=False)
    if has_cc:
        v.check_country(country_code)
    status, has_status = v.opt_enum(data, "status", {"ACTIVE", "ARCHIVED"})

    collaborator = owned_collaborator(user_id, role, collaborator_id)

    if has_tfs:
        collaborator["tax_form_status"] = tax_form_status
    if has_pm:
        collaborator["payout_method"] = payout_method
    if has_cc:
        collaborator["country_code"] = country_code
    if has_status:
        collaborator["status"] = status
    collaborator["withholding_bps"] = calc.withholding_bps(collaborator)
    touch(collaborator)
    return ok(collaborator)
