"""Client (intake step 1) endpoints."""
from __future__ import annotations

from datetime import date, datetime, timezone

from flask import Blueprint

from config import ROLE_ATTORNEY, ROLE_MANAGING_PARTNER, ROLE_PARALEGAL
from db import store
from errors import raise_error
from middleware import require_auth
from response import success
from routes._helpers import get_json_body, require_field
from services.case_engine import new_common_fields
from services.serializers import client_to_dict
from utils import is_valid_email, is_valid_state_code, new_uuid, parse_iso_date


bp = Blueprint("clients", __name__)

ALL_ROLES = [ROLE_PARALEGAL, ROLE_ATTORNEY, ROLE_MANAGING_PARTNER]


@bp.post("/clients")
@require_auth(ALL_ROLES)
def create_client():
    body = get_json_body()

    full_name = require_field(body, "full_name")
    if not isinstance(full_name, str) or len(full_name) > 200:
        raise_error("ERR_VALIDATION", "full_name must be a non-empty string up to 200 chars.")

    dob_raw = require_field(body, "date_of_birth")
    dob = parse_iso_date(dob_raw)
    if dob is None:
        raise_error("ERR_VALIDATION", "date_of_birth must be a valid ISO 8601 date (YYYY-MM-DD).")
    today_utc = datetime.now(timezone.utc).date()
    if dob >= today_utc:
        raise_error("ERR_VALIDATION", "date_of_birth must be in the past.")

    contact_email = require_field(body, "contact_email")
    if not is_valid_email(contact_email):
        raise_error("ERR_VALIDATION", "contact_email is not a valid email address.")

    state_of_residence = require_field(body, "state_of_residence")
    if not is_valid_state_code(state_of_residence):
        raise_error("ERR_VALIDATION", "state_of_residence must be a two-letter uppercase state code.")

    with store.lock:
        row = {
            "id": new_uuid(),
            **new_common_fields(),
            "full_name": full_name,
            "date_of_birth": dob_raw,
            "is_minor_at_incident": None,
            "contact_email": contact_email,
            "state_of_residence": state_of_residence,
        }
        store.clients[row["id"]] = row

    return success(client_to_dict(row), 201)


@bp.get("/clients/<cid>")
@require_auth(ALL_ROLES)
def fetch_client(cid):
    row = store.clients.get(cid)
    if not row:
        raise_error("ERR_NOT_FOUND", f"Client {cid} not found.")
    return success(client_to_dict(row), 200)
