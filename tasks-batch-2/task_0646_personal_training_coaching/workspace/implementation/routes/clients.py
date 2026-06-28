"""Client intake endpoints + intake state machine (PRD §3.1)."""

from flask import Blueprint, g

import errors
from db import db, new_id, now_ts
from helpers import (get_json_body, require_fields, require_string,
                     require_positive_int, require_enum, pagination_params, paginate)
from middleware import require_roles
from response import success, list_success
from serializers import client_view
from services import domain

bp = Blueprint("clients", __name__)

SEX_VALUES = {"MALE", "FEMALE"}


@bp.route("/clients", methods=["POST"])
@require_roles("Trainer")
def create_client():
    body = get_json_body()
    require_fields(body, "trainer_id", "full_name", "email", "sex", "birth_year", "height_cm")

    trainer_id = body["trainer_id"]
    # Priority 4: FK existence.
    trainer = domain.get_trainer(trainer_id)
    # Ownership: a Trainer may only create clients under its own trainer_id.
    if trainer["id"] != g.user_id:
        raise errors.forbidden_role("Trainer may only create clients for itself")

    # Priority 5: body well-formedness.
    full_name = require_string(body["full_name"], "full_name")
    email = require_string(body["email"], "email")
    sex = require_enum(body["sex"], SEX_VALUES, "sex")
    birth_year = body["birth_year"]
    if isinstance(birth_year, bool) or not isinstance(birth_year, int):
        raise errors.invalid_request("birth_year must be an integer")
    height_cm = body["height_cm"]
    if isinstance(height_cm, bool) or not isinstance(height_cm, (int, float)) or height_cm <= 0:
        raise errors.invalid_request("height_cm must be a positive number")

    cid = new_id()
    ts = now_ts()
    client = {
        "id": cid,
        "trainer_id": trainer_id,
        "full_name": full_name,
        "email": email,
        "sex": sex,
        "birth_year": birth_year,
        "height_cm": height_cm,
        "intake_status": "DRAFT",
        "latest_weight_kg": None,
        "no_show_strikes": 0,
        "booking_privilege": "ALLOWED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.clients[cid] = client
    return success(client_view(client), 201)


@bp.route("/clients/<client_id>", methods=["GET"])
@require_roles("Trainer", "Client")
def get_client(client_id):
    client = domain.get_client(client_id)
    domain.assert_owns_client(client)
    return success(client_view(client), 200)


@bp.route("/clients", methods=["GET"])
@require_roles("Trainer", "PlatformAdmin")
def list_clients():
    from flask import request
    limit, offset = pagination_params()
    trainer_filter = request.args.get("trainer_id")

    items = list(db.clients.values())
    if trainer_filter is not None:
        items = [c for c in items if c["trainer_id"] == trainer_filter]
    # A Trainer only sees its own clients.
    if g.user_role == "Trainer":
        items = [c for c in items if c["trainer_id"] == g.user_id]

    items.sort(key=lambda c: (c["created_at"], c["_seq"]))
    page, total = paginate(items, limit, offset)
    return list_success([client_view(c) for c in page], limit, offset, total, 200)


@bp.route("/clients/<client_id>/submit-intake", methods=["POST"])
@require_roles("Client")
def submit_intake(client_id):
    client = domain.get_client(client_id)
    domain.assert_client_is_self(client)
    if client["intake_status"] != "DRAFT":
        raise errors.invalid_state(errors.ERR_INVALID_STATE, "Intake is not in DRAFT")
    client["intake_status"] = "SUBMITTED"
    domain.touch(client)
    return success(client_view(client), 200)


@bp.route("/clients/<client_id>/assess", methods=["POST"])
@require_roles("Trainer")
def assess_intake(client_id):
    client = domain.get_client(client_id)
    domain.assert_trainer_owns_client(client)
    if client["intake_status"] != "SUBMITTED":
        raise errors.invalid_state(errors.ERR_INTAKE_NOT_SUBMITTED, "Intake is not SUBMITTED")
    client["intake_status"] = "ASSESSED"
    domain.touch(client)
    return success(client_view(client), 200)


@bp.route("/clients/<client_id>/return-intake", methods=["POST"])
@require_roles("Trainer")
def return_intake(client_id):
    client = domain.get_client(client_id)
    domain.assert_trainer_owns_client(client)
    if client["intake_status"] != "SUBMITTED":
        raise errors.invalid_state(errors.ERR_INVALID_STATE, "Intake is not SUBMITTED")
    client["intake_status"] = "DRAFT"
    domain.touch(client)
    return success(client_view(client), 200)
