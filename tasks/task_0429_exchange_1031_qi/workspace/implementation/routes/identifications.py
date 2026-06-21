"""Identification & candidate endpoints (PRD §3.4)."""
from flask import Blueprint

import db
import errors
import response
import validate
from middleware import (
    require_auth, require_role,
    QI_COORDINATOR, SETTLEMENT_OFFICER, EXCHANGER,
)
from services import core

bp = Blueprint("identifications", __name__)

READ_ROLES = {QI_COORDINATOR, SETTLEMENT_OFFICER, EXCHANGER}

THREE_PROPERTY_MAX_COUNT = 3
TWO_HUNDRED_PCT_MULTIPLIER = 2


def _get_identification_or_404(identification_id):
    idn = db.identifications.get(identification_id)
    if idn is None:
        raise errors.not_found()
    return idn


def _check_identification_ownership(role, user_id, idn):
    if role != EXCHANGER:
        return
    ex = db.exchanges.get(idn["exchange_id"])
    if ex is None or ex["exchanger_id"] != user_id:
        raise errors.unauthorized()


@bp.get("/identifications/<identification_id>")
def get_identification(identification_id):
    user_id, role = require_auth()
    require_role(role, READ_ROLES)
    idn = _get_identification_or_404(identification_id)
    _check_identification_ownership(role, user_id, idn)
    return response.success_object(core.serialize_identification(idn))


@bp.post("/identifications/<identification_id>/candidates")
def add_candidate(identification_id):
    user_id, role = require_auth()
    require_role(role, {QI_COORDINATOR})
    idn = _get_identification_or_404(identification_id)
    data = validate.body()
    description = validate.require_str(data, "description", allow_empty=True)
    estimated_fmv = validate.require_number(data, "estimated_fmv", gt=0)
    # Added only to a DRAFT identification (PRD §3.4).
    if idn["status"] != "DRAFT":
        raise errors.invalid_state()
    # IdentifiedProperty carries only id + created_at (PRD §2.4) — with_version=False.
    record = core._stamp_new({
        "identification_id": identification_id,
        "description": description,
        "estimated_fmv": estimated_fmv,
        "status": "CANDIDATE",
    }, with_version=False)
    db.identified_properties[record["id"]] = record
    # parent aggregate_identified_fmv is recomputed lazily on read; the parent's
    # updated_at/version are not bumped (the candidate is the new resource).
    return response.success_object(core.serialize_candidate(record), status=201)


@bp.get("/identifications/<identification_id>/candidates")
def list_candidates(identification_id):
    user_id, role = require_auth()
    require_role(role, READ_ROLES)
    idn = _get_identification_or_404(identification_id)
    _check_identification_ownership(role, user_id, idn)
    rows = sorted(core.candidates_for(identification_id), key=lambda r: (r["created_at"], r["_seq"]))
    return response.success_array([core.serialize_candidate(r) for r in rows])


@bp.post("/identifications/<identification_id>/finalize")
def finalize_identification(identification_id):
    user_id, role = require_auth()
    require_role(role, {QI_COORDINATOR})
    idn = _get_identification_or_404(identification_id)
    ex = db.exchanges.get(idn["exchange_id"])
    core.apply_posture(ex)
    # state (priority 5): identification must be DRAFT and parent exchange ACTIVE.
    if idn["status"] != "DRAFT":
        raise errors.invalid_state()
    if ex["status"] != "ACTIVE":
        raise errors.invalid_state()
    # at least one CANDIDATE-status candidate must exist (PRD §3.4).
    candidates = core.candidate_rows(identification_id)
    if len(candidates) == 0:
        raise errors.invalid_state()
    # no other FINALIZED identification on this exchange (PRD §3.4).
    other_final = core.finalized_identification_for(ex["id"])
    if other_final is not None:
        raise errors.invalid_state()

    now = db.now_logical()
    # deadline gate (priority 7): on/before id_deadline_at, inclusive (PRD §3.4).
    if ex["id_deadline_at"] is not None and now > ex["id_deadline_at"]:
        raise errors.id_deadline_passed()

    # method-specific breadth rules (priority 9 / 10, PRD §3.4).
    if idn["method"] == "THREE_PROPERTY":
        if len(candidates) > THREE_PROPERTY_MAX_COUNT:
            raise errors.three_property_rule_violated()
    elif idn["method"] == "TWO_HUNDRED_PCT":
        rel = core.relinquished_for(ex["id"])
        cap = core.aggregate_identified_fmv(identification_id)
        relinquished_fmv = rel["fair_market_value"] if rel is not None else None
        if relinquished_fmv is None:
            raise errors.two_hundred_pct_rule_violated()
        if cap > TWO_HUNDRED_PCT_MULTIPLIER * relinquished_fmv:
            raise errors.two_hundred_pct_rule_violated()

    # apply: stamp finalized_at, status FINALIZED, cascade exchange posture IDENTIFIED.
    idn["finalized_at"] = now
    idn["status"] = "FINALIZED"
    core.touch(idn)
    ex["compliance_posture"] = "IDENTIFIED"
    core.touch(ex)
    return response.success_object(core.serialize_identification(idn))


@bp.post("/identifications/<identification_id>/revoke")
def revoke_identification(identification_id):
    user_id, role = require_auth()
    require_role(role, {QI_COORDINATOR})
    idn = _get_identification_or_404(identification_id)
    # permitted only while DRAFT (PRD §3.4).
    if idn["status"] != "DRAFT":
        raise errors.invalid_state()
    idn["status"] = "REVOKED"
    # cascade down: every CANDIDATE child -> WITHDRAWN (PRD §3.4).
    for c in core.candidates_for(identification_id):
        if c["status"] == "CANDIDATE":
            c["status"] = "WITHDRAWN"
    core.touch(idn)
    return response.success_object(core.serialize_identification(idn))
