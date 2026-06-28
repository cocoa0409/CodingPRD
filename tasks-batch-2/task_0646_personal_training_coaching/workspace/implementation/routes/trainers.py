"""Trainer endpoints (PRD §3.1)."""

from flask import Blueprint, g

import errors
from db import db, new_id, now_ts
from helpers import get_json_body, require_fields, require_string
from middleware import require_roles
from response import success
from serializers import trainer_view
from services import domain

bp = Blueprint("trainers", __name__)


@bp.route("/trainers", methods=["POST"])
@require_roles("PlatformAdmin")
def create_trainer():
    body = get_json_body()
    require_fields(body, "full_name", "email")
    full_name = require_string(body["full_name"], "full_name")
    email = require_string(body["email"], "email")
    timezone = body.get("timezone", "UTC")
    if timezone is None:
        timezone = "UTC"
    if not isinstance(timezone, str) or not timezone.strip():
        raise errors.invalid_request("timezone must be a non-empty string")

    tid = new_id()
    ts = now_ts()
    trainer = {
        "id": tid,
        "full_name": full_name,
        "email": email,
        "timezone": timezone,
        "status": "ACTIVE",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.trainers[tid] = trainer
    return success(trainer_view(trainer), 201)


@bp.route("/trainers/<trainer_id>", methods=["GET"])
@require_roles("PlatformAdmin", "Trainer")
def get_trainer(trainer_id):
    trainer = domain.get_trainer(trainer_id)
    # A Trainer may only read its own record; PlatformAdmin reads any.
    if g.user_role == "Trainer" and trainer["id"] != g.user_id:
        raise errors.forbidden_role("Trainer may only read its own record")
    return success(trainer_view(trainer), 200)
