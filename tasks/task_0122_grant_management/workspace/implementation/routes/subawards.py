"""Subaward endpoints (PRD §3.4)."""
from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success
from services import common as c

bp = Blueprint("subawards", __name__)

RISK_TIERS = {"LOW", "MEDIUM", "HIGH"}


def _serialize(sub):
    return c.serialize(sub)


def _load(sub_id):
    sub = db.subawards.get(sub_id)
    if sub is None:
        raise errors.not_found("Subaward not found.")
    return sub


@bp.route("/subawards", methods=["POST"])
@require_roles("ProgramManager")
def create_subaward(user_id, role):
    body = c.get_body()

    award_id = body.get("award_id")
    if award_id is None or not isinstance(award_id, str) or award_id == "":
        raise errors.invalid_request("award_id is required.")
    with db.LOCK:
        if award_id not in db.awards:
            raise errors.not_found("Award not found.")

        subrecipient_name = c.require_nonempty_string(body, "subrecipient_name")
        subaward_amount_cents = c.require_int(body, "subaward_amount_cents", minimum=1)
        risk_tier = c.optional_enum(body, "risk_tier", RISK_TIERS, "LOW")

        record = {
            "award_id": award_id,
            "subrecipient_name": subrecipient_name,
            "subaward_amount_cents": subaward_amount_cents,
            "risk_tier": risk_tier,
            "status": "PROPOSED",
        }
        db.stamp_create(record)
        db.subawards[record["id"]] = record
        return success(_serialize(record), status=201)


@bp.route("/subawards", methods=["GET"])
@require_roles("ProgramManager", "AgencyOfficer", "Auditor")
def list_subawards(user_id, role):
    limit, offset = c.parse_pagination()
    award_id = request.args.get("award_id")
    status = request.args.get("status")
    with db.LOCK:
        records = list(db.subawards.values())
    if award_id is not None:
        records = [r for r in records if r["award_id"] == award_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, pagination = c.paginate(records, limit, offset)
    return success([_serialize(r) for r in page], status=200, pagination=pagination)


@bp.route("/subawards/<sub_id>", methods=["GET"])
@require_roles("ProgramManager", "AgencyOfficer", "Auditor")
def get_subaward(sub_id, user_id, role):
    with db.LOCK:
        return success(_serialize(_load(sub_id)), status=200)


def _require_award_active(sub):
    award = db.awards.get(sub["award_id"])
    # FK was validated at creation; award must still exist.
    if award is None or award["status"] != "ACTIVE":
        raise errors.award_not_active()


@bp.route("/subawards/<sub_id>/approve", methods=["POST"])
@require_roles("ProgramManager")
def approve_subaward(sub_id, user_id, role):
    with db.LOCK:
        sub = _load(sub_id)
        if sub["status"] != "PROPOSED":
            raise errors.invalid_state("Only a PROPOSED subaward may be approved.")
        _require_award_active(sub)
        sub["status"] = "APPROVED"
        db.touch(sub)
        return success(_serialize(sub), status=200)


@bp.route("/subawards/<sub_id>/activate", methods=["POST"])
@require_roles("ProgramManager")
def activate_subaward(sub_id, user_id, role):
    with db.LOCK:
        sub = _load(sub_id)
        if sub["status"] != "APPROVED":
            raise errors.invalid_state("Only an APPROVED subaward may be activated.")
        _require_award_active(sub)
        sub["status"] = "ACTIVE"
        db.touch(sub)
        return success(_serialize(sub), status=200)


@bp.route("/subawards/<sub_id>/terminate", methods=["POST"])
@require_roles("ProgramManager")
def terminate_subaward(sub_id, user_id, role):
    with db.LOCK:
        sub = _load(sub_id)
        # Terminate available from ACTIVE or APPROVED (PRD §3.4).
        if sub["status"] not in ("ACTIVE", "APPROVED"):
            raise errors.invalid_state("Only an ACTIVE or APPROVED subaward may be terminated.")
        sub["status"] = "TERMINATED"
        db.touch(sub)
        return success(_serialize(sub), status=200)
