"""Cardholder routes."""
from __future__ import annotations

import re

from flask import Blueprint, g, request

from auth import is_cardholder, require_roles
from constants import ROLE_CARDHOLDER, ROLE_PLATFORM_ADMIN
from errors import err
from response import ok_object
from serializers import cardholder_view
from store import store
from utils import get_body, require_str

bp = Blueprint("cardholders", __name__)

# Permissive RFC 5322 sanity check (not the full grammar). Lowercase enforcement
# is the responsibility of the create endpoint.
_EMAIL_RE = re.compile(r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$")


@bp.post("/cardholders")
@require_roles(ROLE_PLATFORM_ADMIN)
def create_cardholder():
    body = get_body(request)
    email = require_str(body, "email")
    display_name = require_str(body, "display_name")

    if email != email.lower():
        raise err("ERR_VALIDATION", "email must be lowercase")
    if not _EMAIL_RE.match(email):
        raise err("ERR_VALIDATION", "email must be a valid RFC 5322 address")
    if email in store.cardholder_emails:
        raise err("ERR_VALIDATION", "email already registered")

    with store.lock:
        if email in store.cardholder_emails:
            raise err("ERR_VALIDATION", "email already registered")
        cid = store.new_id()
        iso = store.now_iso()
        rec = {
            "id": cid,
            "email": email,
            "display_name": display_name,
            "created_at": iso,
            "updated_at": iso,
            "version": 1,
        }
        store.cardholders[cid] = rec
        store.cardholder_emails.add(email)

    return ok_object(cardholder_view(rec), status=201)


@bp.get("/cardholders/<cardholder_id>")
@require_roles(ROLE_CARDHOLDER, ROLE_PLATFORM_ADMIN)
def get_cardholder(cardholder_id: str):
    rec = store.cardholders.get(cardholder_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Cardholder not found")

    if is_cardholder() and g.user_id != cardholder_id:
        raise err("ERR_FORBIDDEN", "Cardholder may only view their own profile")

    return ok_object(cardholder_view(rec))
