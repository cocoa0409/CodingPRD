"""Licensee endpoints (PRD §3.4)."""

from flask import Blueprint, request

import errors
import serialize
from common import (
    get_json_body,
    require_string,
    parse_pagination,
    paginate,
)
from db import db
from middleware import require_roles
from models import new_full_record
from response import success_object, success_list
from routes.license_boards import get_board_or_404

bp = Blueprint("licensees", __name__)


def get_licensee_or_404(licensee_id):
    l = db.licensees.get(licensee_id)
    if l is None:
        raise errors.not_found(f"Licensee '{licensee_id}' not found.")
    return l


@bp.route("/licensees", methods=["POST"])
@require_roles("BoardAdmin")
def create_licensee():
    body = get_json_body()
    full_name = require_string(body, "full_name")
    home_board_id = require_string(body, "home_board_id")
    license_number = require_string(body, "license_number")
    get_board_or_404(home_board_id)

    with db.lock:
        # license_number unique together with home_board_id.
        for l in db.licensees.values():
            if (l["home_board_id"] == home_board_id
                    and l["license_number"] == license_number):
                raise errors.validation_range(
                    "license_number must be unique within home_board_id."
                )

        rec = new_full_record()
        rec.update({
            "full_name": full_name,
            "home_board_id": home_board_id,
            "license_number": license_number,
            "audit_risk_score": 0,
        })
        db.licensees[rec["id"]] = rec

    return success_object(serialize.licensee(rec), status=201)


@bp.route("/licensees/<licensee_id>", methods=["GET"])
@require_roles("BoardAdmin", "Licensee", "Auditor")
def get_licensee(licensee_id):
    l = get_licensee_or_404(licensee_id)
    return success_object(serialize.licensee(l), status=200)


@bp.route("/licensees", methods=["GET"])
@require_roles("BoardAdmin", "Auditor")
def list_licensees():
    limit, offset = parse_pagination()
    home_board_id = request.args.get("home_board_id")
    items = list(db.licensees.values())
    if home_board_id is not None:
        items = [l for l in items if l["home_board_id"] == home_board_id]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list(
        [serialize.licensee(l) for l in page], limit, offset, total, status=200,
    )
