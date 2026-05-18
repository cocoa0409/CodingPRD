"""Lien endpoints."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, jsonify, request

from ..auth import require_roles
from ..calculations import (
    LIEN_COOLING_OFF_DAYS,
    LIEN_OVERDUE_FLOOR_CENTS,
)
from ..envelope import paginate, parse_pagination, success_array, success_object
from ..errors import APIError, err_invalid_state, err_lien_cooling_off
from ..serializers import serialize_lien
from ..services.clock_sweep import run_sweep
from ..services.common import (
    bump_member_overdue,
    bump_version,
    check_version,
    require,
    unit_has_60d_overdue_charge,
)
from ..store import store
from ..util import new_uuid
from ._helpers import get_json_body, get_version, require_field

bp = Blueprint("liens", __name__)


@bp.route("/hoa/liens/<lien_id>", methods=["GET"])
@require_roles(["Member", "SecretaryRole", "TreasurerRole", "PresidentRole", "DirectorRole"])
def get_lien(lien_id: str):
    lien = require("liens", lien_id)
    return jsonify(success_object(serialize_lien(lien))), 200


@bp.route("/hoa/liens", methods=["POST"])
@require_roles(["SecretaryRole"])
def create_lien():
    body = get_json_body()
    unit_id = require_field(body, "unit_id")
    unit = require("units", unit_id)

    # Refresh lazy state first so overdue ages are correct
    run_sweep()

    s = store()
    owner = s.members.get(unit["owner_member_id"])
    if owner is None:
        raise err_invalid_state("Unit owner missing")

    bump_member_overdue(owner)
    if owner.get("total_overdue_amount_cents", 0) < LIEN_OVERDUE_FLOOR_CENTS:
        raise err_invalid_state(
            f"Owner overdue ({owner.get('total_overdue_amount_cents', 0)}) "
            f"below floor {LIEN_OVERDUE_FLOOR_CENTS}"
        )
    if not unit_has_60d_overdue_charge(unit_id):
        raise err_invalid_state("Unit has no charge OVERDUE >= 60 days")

    now = s.now()
    lien = {
        "id": new_uuid(),
        "unit_id": unit_id,
        "principal_cents_at_record": None,
        "mortgage_holder_at_record": None,
        "recorded_at": None,
        "released_at": None,
        "status": "NOTICE_SENT",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    s.insert("liens", lien)

    # Cascade Unit.lien_status — NOTICE_SENT means an active lien exists
    unit["lien_status"] = "NOTICE_SENT"
    bump_version(unit, now)

    return jsonify(success_object(serialize_lien(lien))), 201


@bp.route("/hoa/liens/<lien_id>/record", methods=["POST"])
@require_roles(["PresidentRole"])
def record_lien(lien_id: str):
    lien = require("liens", lien_id)
    body = get_json_body()
    resolution_id = require_field(body, "resolution_id")
    version = get_version(body)
    check_version(lien, version)

    s = store()
    now = s.now()

    # PRD §3.6: cooling-off precedes state check
    if (now - lien["created_at"]) < timedelta(days=LIEN_COOLING_OFF_DAYS):
        raise err_lien_cooling_off()

    if lien["status"] != "NOTICE_SENT":
        raise err_invalid_state(f"Lien is {lien['status']}, cannot record")

    resolution = s.board_resolutions.get(resolution_id)
    if resolution is None:
        raise err_invalid_state("resolution_id does not resolve")
    if (
        resolution["subject"] != "LIEN_RECORDATION"
        or resolution["status"] != "PASSED"
        or resolution["target_id"] != lien_id
    ):
        raise err_invalid_state("Resolution is not a PASSED LIEN_RECORDATION for this lien")

    unit = s.units.get(lien["unit_id"])
    if unit is None:
        raise err_invalid_state("Underlying unit missing")
    owner = s.members.get(unit["owner_member_id"])
    if owner is None:
        raise err_invalid_state("Unit owner missing")

    run_sweep()
    bump_member_overdue(owner)
    if owner.get("total_overdue_amount_cents", 0) < LIEN_OVERDUE_FLOOR_CENTS:
        raise err_invalid_state("Owner overdue dropped below floor before record")
    if not unit_has_60d_overdue_charge(lien["unit_id"]):
        raise err_invalid_state("No charge OVERDUE >= 60d at record time")

    lien["recorded_at"] = now
    lien["principal_cents_at_record"] = owner["total_overdue_amount_cents"]
    lien["mortgage_holder_at_record"] = unit.get("mortgage_holder")
    lien["status"] = "RECORDED"
    bump_version(lien, now)

    unit["lien_status"] = "RECORDED"
    bump_version(unit, now)

    resolution["status"] = "EXECUTED"
    bump_version(resolution, now)

    return jsonify(success_object(serialize_lien(lien))), 200


@bp.route("/hoa/liens/<lien_id>/release", methods=["POST"])
@require_roles(["PresidentRole"])
def release_lien(lien_id: str):
    lien = require("liens", lien_id)
    body = get_json_body()
    resolution_id = require_field(body, "resolution_id")
    version = get_version(body)
    check_version(lien, version)

    if lien["status"] != "RECORDED":
        raise err_invalid_state(f"Lien is {lien['status']}, cannot release")

    s = store()
    resolution = s.board_resolutions.get(resolution_id)
    if resolution is None:
        raise err_invalid_state("resolution_id does not resolve")
    if (
        resolution["subject"] != "LIEN_RELEASE"
        or resolution["status"] != "PASSED"
        or resolution["target_id"] != lien_id
    ):
        raise err_invalid_state("Resolution is not a PASSED LIEN_RELEASE for this lien")

    unit = s.units.get(lien["unit_id"])
    if unit is None:
        raise err_invalid_state("Underlying unit missing")
    owner = s.members.get(unit["owner_member_id"])
    if owner is None:
        raise err_invalid_state("Unit owner missing")

    run_sweep()
    bump_member_overdue(owner)
    if owner.get("total_overdue_amount_cents", 0) != 0:
        raise err_invalid_state("Owner still has overdue balance")

    now = s.now()
    lien["released_at"] = now
    lien["status"] = "RELEASED"
    bump_version(lien, now)

    unit["lien_status"] = "RELEASED"
    bump_version(unit, now)

    resolution["status"] = "EXECUTED"
    bump_version(resolution, now)

    return jsonify(success_object(serialize_lien(lien))), 200


@bp.route("/hoa/liens", methods=["GET"])
@require_roles(["Member", "SecretaryRole", "TreasurerRole", "PresidentRole", "DirectorRole"])
def list_liens():
    limit, offset = parse_pagination()
    unit_id = request.args.get("unit_id")
    status_filter = request.args.get("status")

    s = store()
    # Filter
    liens = [s.liens[id_] for id_ in s.insertion_order["liens"]]
    if unit_id is not None:
        liens = [l for l in liens if l["unit_id"] == unit_id]
    if status_filter is not None:
        liens = [l for l in liens if l["status"] == status_filter]

    # Sort by created_at ASC for stable pagination
    liens.sort(key=lambda l: l["created_at"])
    total_count = len(liens)
    page = paginate(liens, limit, offset)
    body = success_array(
        [serialize_lien(l) for l in page],
        limit=limit,
        offset=offset,
        total_count=total_count,
    )
    return jsonify(body), 200
