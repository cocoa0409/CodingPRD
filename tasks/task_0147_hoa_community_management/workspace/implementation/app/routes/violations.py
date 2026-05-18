"""Violation endpoints."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, g, jsonify

from ..auth import require_roles
from ..calculations import VIOLATION_CURE_DAYS
from ..envelope import success_object
from ..errors import APIError, err_invalid_state
from ..serializers import serialize_violation
from ..services.clock_sweep import run_sweep
from ..services.common import (
    bump_member_overdue,
    bump_version,
    check_version,
    require,
)
from ..store import store
from ..util import new_uuid
from ._helpers import get_json_body, get_version, require_field

bp = Blueprint("violations", __name__)


@bp.route("/hoa/violations/<violation_id>", methods=["GET"])
@require_roles(["Member", "SecretaryRole", "TreasurerRole", "PresidentRole", "DirectorRole"])
def get_violation(violation_id: str):
    run_sweep()
    v = require("violations", violation_id)
    return jsonify(success_object(serialize_violation(v))), 200


@bp.route("/hoa/violations", methods=["POST"])
@require_roles(["SecretaryRole", "PresidentRole"])
def open_violation():
    body = get_json_body()
    unit_id = require_field(body, "unit_id")
    description = require_field(body, "description")

    unit = require("units", unit_id)

    s = store()
    now = s.now()
    # Compute occurrence_index from prior violations in {FINED, CURED, WAIVED}
    prior = [
        v
        for v in s.violations.values()
        if v["unit_id"] == unit_id and v["status"] in {"FINED", "CURED", "WAIVED"}
    ]
    occurrence_index = len(prior) + 1

    v = {
        "id": new_uuid(),
        "unit_id": unit_id,
        "opened_by_member_id": g.user_id,
        "description": description,
        "opened_at": now,
        "cure_deadline": now + timedelta(days=VIOLATION_CURE_DAYS),
        "occurrence_index": occurrence_index,
        "fine_cents": 0,
        "status": "OPEN",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    s.insert("violations", v)
    return jsonify(success_object(serialize_violation(v))), 201


@bp.route("/hoa/violations/<violation_id>/cure", methods=["POST"])
@require_roles(["SecretaryRole"])
def cure_violation(violation_id: str):
    v = require("violations", violation_id)
    body = get_json_body()
    version = get_version(body)
    check_version(v, version)

    s = store()
    now = s.now()
    if v["status"] != "OPEN":
        raise err_invalid_state(f"Violation is {v['status']}, cannot cure")
    if now > v["cure_deadline"]:
        raise err_invalid_state("Cure deadline has passed")

    v["status"] = "CURED"
    v["fine_cents"] = 0
    bump_version(v, now)

    unit = s.units.get(v["unit_id"])
    if unit is not None:
        owner = s.members.get(unit["owner_member_id"])
        if owner is not None:
            bump_member_overdue(owner)

    return jsonify(success_object(serialize_violation(v))), 200


@bp.route("/hoa/violations/<violation_id>/waive", methods=["POST"])
@require_roles(["SecretaryRole"])
def waive_violation(violation_id: str):
    v = require("violations", violation_id)
    body = get_json_body()
    resolution_id = require_field(body, "resolution_id")
    version = get_version(body)
    check_version(v, version)

    # Bring lazy state up-to-date so timing-driven FINED transitions register
    run_sweep()
    v = require("violations", violation_id)

    if v["status"] not in {"OPEN", "FINED"}:
        raise err_invalid_state(f"Violation is {v['status']}, cannot waive")

    s = store()
    resolution = s.board_resolutions.get(resolution_id)
    if resolution is None:
        raise err_invalid_state("resolution_id does not resolve")
    if (
        resolution["status"] != "PASSED"
        or resolution["subject"] != "FINE_WAIVER"
        or resolution["target_id"] != violation_id
    ):
        raise err_invalid_state("Resolution is not a PASSED FINE_WAIVER for this violation")

    if v["status"] == "FINED" and v.get("fine_paid", False):
        raise err_invalid_state("Fine has already been paid; cannot waive")

    now = s.now()
    previously_fined = v["status"] == "FINED"
    v["status"] = "WAIVED"
    v["fine_cents"] = 0
    bump_version(v, now)

    resolution["status"] = "EXECUTED"
    bump_version(resolution, now)

    if previously_fined:
        unit = s.units.get(v["unit_id"])
        if unit is not None:
            owner = s.members.get(unit["owner_member_id"])
            if owner is not None:
                bump_member_overdue(owner)

    return jsonify(success_object(serialize_violation(v))), 200
