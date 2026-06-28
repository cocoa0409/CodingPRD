"""Provider and Chair endpoints (PRD §3.1)."""

from flask import Blueprint

from db import db, lock
from helpers import get_json_body, require_str, require_bool, require_int, stamp_new
from lookups import get_or_404
from middleware import require_roles
from response import success
from serializers import public

bp = Blueprint("providers_chairs", __name__)


# ---- Provider ----

@bp.post("/providers")
@require_roles("ClinicAdmin")
def create_provider():
    body = get_json_body()
    provider_user_id = require_str(body, "provider_user_id")
    full_name = require_str(body, "full_name")
    npi = require_str(body, "npi")
    active = require_bool(body, "active", default=True)
    with lock:
        rec = {
            "provider_user_id": provider_user_id,
            "full_name": full_name,
            "npi": npi,
            "active": active,
        }
        stamp_new(rec)
        db.providers[rec["id"]] = rec
        return success(public(rec), 201)


@bp.get("/providers/<provider_id>")
@require_roles("FrontDesk", "ClinicAdmin", "Orthodontist")
def get_provider(provider_id):
    with lock:
        rec = get_or_404(db.providers, provider_id)
        return success(public(rec), 200)


# ---- Chair ----

@bp.post("/chairs")
@require_roles("ClinicAdmin")
def create_chair():
    body = get_json_body()
    label = require_str(body, "label")
    turnover = body.get("turnover_buffer_minutes")
    if turnover is None:
        turnover = 10
    else:
        turnover = require_int(body, "turnover_buffer_minutes", non_negative=True)
    active = require_bool(body, "active", default=True)
    with lock:
        rec = {
            "label": label,
            "turnover_buffer_minutes": turnover,
            "active": active,
        }
        stamp_new(rec)
        db.chairs[rec["id"]] = rec
        return success(public(rec), 201)


@bp.get("/chairs/<chair_id>")
@require_roles("FrontDesk", "ClinicAdmin", "Orthodontist")
def get_chair(chair_id):
    with lock:
        rec = get_or_404(db.chairs, chair_id)
        return success(public(rec), 200)
