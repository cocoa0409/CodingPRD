"""AssessmentCycle and AssessmentCharge endpoints."""
from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, jsonify

from ..auth import require_roles
from ..calculations import allocate_assessment_principal
from ..envelope import success_object
from ..errors import (
    APIError,
    err_invalid_state,
    err_levy_too_small,
    err_share_factor,
)
from ..serializers import serialize_assessment_charge, serialize_assessment_cycle
from ..services.clock_sweep import run_sweep
from ..services.common import (
    bump_member_overdue,
    bump_version,
    check_version,
    require,
    sum_share_factors,
)
from ..store import store
from ..util import new_uuid, parse_iso8601
from ._helpers import as_int, get_json_body, get_version, require_field

bp = Blueprint("assessments", __name__)


# ---------------- AssessmentCycle ----------------


@bp.route("/hoa/assessment-cycles", methods=["POST"])
@require_roles(["TreasurerRole"])
def create_cycle():
    body = get_json_body()
    cycle_type = require_field(body, "cycle_type")
    if cycle_type not in {"REGULAR", "SPECIAL"}:
        raise APIError("ERR_INVALID_STATE", "cycle_type must be REGULAR or SPECIAL", 409)

    period_start = parse_iso8601(require_field(body, "period_start"))
    due_date = parse_iso8601(require_field(body, "due_date"))
    total_levy_cents = as_int(require_field(body, "total_levy_cents"), "total_levy_cents")
    approval_resolution_id = body.get("approval_resolution_id")

    if total_levy_cents < 100:
        raise err_levy_too_small()

    if approval_resolution_id is not None and not isinstance(approval_resolution_id, str):
        raise APIError("ERR_INVALID_STATE", "approval_resolution_id must be string or null", 409)

    s = store()
    now = s.now()
    cycle = {
        "id": new_uuid(),
        "cycle_type": cycle_type,
        "period_start": period_start,
        "due_date": due_date,
        "total_levy_cents": total_levy_cents,
        "approval_resolution_id": approval_resolution_id,
        "status": "DRAFT",
        "created_at": now,
    }
    s.insert("assessment_cycles", cycle)
    return jsonify(success_object(serialize_assessment_cycle(cycle))), 201


@bp.route("/hoa/assessment-cycles/<cycle_id>/issue", methods=["POST"])
@require_roles(["TreasurerRole"])
def issue_cycle(cycle_id: str):
    cycle = require("assessment_cycles", cycle_id)
    body = get_json_body()
    _ = get_version(body)  # cycles have no version, accept silently

    if cycle["status"] != "DRAFT":
        raise err_invalid_state(f"Cycle is in {cycle['status']}, cannot issue")

    # SPECIAL requires PASSED resolution
    if cycle["cycle_type"] == "SPECIAL":
        resolution_id = cycle.get("approval_resolution_id")
        if not resolution_id:
            raise err_invalid_state("SPECIAL cycle requires approval_resolution_id")
        resolution = store().board_resolutions.get(resolution_id)
        if resolution is None:
            raise err_invalid_state("approval_resolution_id does not resolve")
        if resolution["status"] != "PASSED" or resolution["subject"] != "SPECIAL_ASSESSMENT":
            raise err_invalid_state("approval_resolution must be PASSED SPECIAL_ASSESSMENT")
        if resolution["target_id"] != cycle["id"]:
            raise err_invalid_state("approval_resolution targets a different cycle")

    # Total levy minimum re-check
    if cycle["total_levy_cents"] < 100:
        raise err_levy_too_small()

    # Share factor sum invariant
    total = sum_share_factors()
    if total.quantize(Decimal("0.0001")) != Decimal("1.0000"):
        raise err_share_factor(f"Sum of share_factor is {total} (must be 1.0000)")

    s = store()
    units = list(s.units.values())
    if not units:
        raise err_invalid_state("No units to issue charges to")

    now = s.now()
    unit_shares = [(u["id"], Decimal(str(u["share_factor"]))) for u in units]
    principals = allocate_assessment_principal(cycle["total_levy_cents"], unit_shares)

    with s.lock:
        for u in units:
            charge = {
                "id": new_uuid(),
                "cycle_id": cycle["id"],
                "unit_id": u["id"],
                "principal_cents": principals[u["id"]],
                "late_fee_cents": 0,
                "paid_cents": 0,
                "status": "OPEN",
                "created_at": now,
                "updated_at": now,
                "version": 1,
            }
            s.insert("assessment_charges", charge)

        cycle["status"] = "ISSUED"
        # If SPECIAL, consume the resolution
        if cycle["cycle_type"] == "SPECIAL":
            resolution = s.board_resolutions[cycle["approval_resolution_id"]]
            resolution["status"] = "EXECUTED"
            bump_version(resolution, now)

    return jsonify(success_object(serialize_assessment_cycle(cycle))), 200


@bp.route("/hoa/assessment-cycles/<cycle_id>/close", methods=["POST"])
@require_roles(["TreasurerRole"])
def close_cycle(cycle_id: str):
    cycle = require("assessment_cycles", cycle_id)
    body = get_json_body()
    _ = get_version(body)

    if cycle["status"] != "ISSUED":
        raise err_invalid_state(f"Cycle is in {cycle['status']}, cannot close")

    s = store()
    children = [c for c in s.assessment_charges.values() if c["cycle_id"] == cycle_id]
    if not children:
        raise err_invalid_state("No charges exist on this cycle")
    for ch in children:
        if ch["status"] not in {"PAID", "WRITTEN_OFF"}:
            raise err_invalid_state(f"Charge {ch['id']} not in terminal state")

    cycle["status"] = "CLOSED"
    return jsonify(success_object(serialize_assessment_cycle(cycle))), 200


@bp.route("/hoa/assessment-cycles/<cycle_id>/void", methods=["POST"])
@require_roles(["TreasurerRole"])
def void_cycle(cycle_id: str):
    cycle = require("assessment_cycles", cycle_id)
    body = get_json_body()
    _ = get_version(body)

    if cycle["status"] != "DRAFT":
        raise err_invalid_state(f"Cycle is in {cycle['status']}, cannot void")

    s = store()
    charges = [c for c in s.assessment_charges.values() if c["cycle_id"] == cycle_id]
    if charges:
        raise err_invalid_state("Cannot void a cycle with existing charges")

    cycle["status"] = "VOIDED"
    return jsonify(success_object(serialize_assessment_cycle(cycle))), 200


# ---------------- AssessmentCharge ----------------


@bp.route("/hoa/assessment-charges/<charge_id>", methods=["GET"])
@require_roles(["Member", "SecretaryRole", "TreasurerRole", "PresidentRole", "DirectorRole"])
def get_charge(charge_id: str):
    charge = require("assessment_charges", charge_id)
    # Lazy late-fee recompute
    run_sweep()
    charge = require("assessment_charges", charge_id)
    return jsonify(success_object(serialize_assessment_charge(charge))), 200


@bp.route("/hoa/assessment-charges/<charge_id>/write-off", methods=["POST"])
@require_roles(["TreasurerRole"])
def write_off_charge(charge_id: str):
    charge = require("assessment_charges", charge_id)
    body = get_json_body()
    version = get_version(body)
    check_version(charge, version)

    # Refresh status first
    run_sweep()
    charge = require("assessment_charges", charge_id)

    if charge["status"] != "OVERDUE":
        raise err_invalid_state(f"Charge is in {charge['status']}, cannot write off")

    s = store()
    unit = s.units.get(charge["unit_id"])
    # Find an active Lien in RELEASED status whose released_at >= charge.created_at
    liens = [
        l
        for l in s.liens.values()
        if l["unit_id"] == charge["unit_id"]
        and l["status"] == "RELEASED"
        and l.get("released_at") is not None
        and l["released_at"] >= charge["created_at"]
    ]
    if not liens:
        raise err_invalid_state("Unit lacks a RELEASED lien post-charge")

    now = s.now()
    charge["status"] = "WRITTEN_OFF"
    bump_version(charge, now)

    if unit is not None:
        owner = s.members.get(unit["owner_member_id"])
        if owner is not None:
            bump_member_overdue(owner)

    return jsonify(success_object(serialize_assessment_charge(charge))), 200
