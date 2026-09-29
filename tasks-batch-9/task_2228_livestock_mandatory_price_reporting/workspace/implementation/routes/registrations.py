"""Threshold determination, appeal, activation and suspension (PRD §3.2)."""

from flask import Blueprint, g

import clock
import constants
import db
import lookup
import response
import serializers
import validators as V
from errors import (
    ApiError,
    ERR_APPEAL_LIMIT_REACHED,
    ERR_DUPLICATE_REGISTRATION_YEAR,
    ERR_ENTITY_EXEMPT,
    ERR_FOREIGN_REPORTING_ENTITY,
    ERR_INVALID_REGISTRATION_STATE,
    ERR_OUTSTANDING_PENALTY_BLOCKS_ACTIVATION,
)
from middleware import (
    ROLE_COMPLIANCE_AUDITOR,
    ROLE_MARKET_ANALYST,
    ROLE_PENALTY_OFFICER,
    ROLE_PROGRAM_ADMIN,
    ROLE_REPORTER_AGENT,
    roles,
)
from services import calculations, cascades

bp = Blueprint("registrations", __name__)

READ_ROLES = (
    ROLE_PROGRAM_ADMIN,
    ROLE_MARKET_ANALYST,
    ROLE_COMPLIANCE_AUDITOR,
    ROLE_PENALTY_OFFICER,
    ROLE_REPORTER_AGENT,
)


def _require_status(registration, *allowed):
    if registration["status"] not in allowed:
        raise ApiError(
            ERR_INVALID_REGISTRATION_STATE,
            "Registration in status %s does not permit this action." % registration["status"],
        )


@bp.post("/registrations")
@roles(ROLE_PROGRAM_ADMIN)
def create_registration():
    payload = V.body()
    entity_id = V.get_string(payload, "reporting_entity_id")
    year = V.get_int(payload, "determination_year", minimum=2000, maximum=2100)
    basis = V.get_enum(
        payload, "basis_variant", V.BASIS_VARIANTS, required=False, default="FIVE_YEAR_AVERAGE"
    )

    lookup.reporting_entity(entity_id)

    clash = any(
        r["reporting_entity_id"] == entity_id
        and r["determination_year"] == year
        and r["status"] != "REVOKED"
        for r in db.registrations.values()
    )
    if clash:
        raise ApiError(
            ERR_DUPLICATE_REGISTRATION_YEAR,
            "A non-revoked registration already exists for that firm and determination year.",
        )

    rec = db.insert(
        db.registrations,
        {
            "reporting_entity_id": entity_id,
            "determination_year": year,
            "basis_variant": basis,
            "measured_head": 0,
            "threshold_head": 0,
            "determination_outcome": None,
            "registration_number": None,
            "status": "DRAFT",
            "appeal_count": 0,
            "suspended_reason": None,
            "effective_from": None,
        },
    )
    return response.object_response(serializers.registration(rec), 201)


@bp.post("/registrations/<registration_id>/determine")
@roles(ROLE_PROGRAM_ADMIN)
def determine(registration_id):
    rec = lookup.registration(registration_id)
    _require_status(rec, "DRAFT")

    entity = db.reporting_entities[rec["reporting_entity_id"]]
    measured, threshold, outcome = calculations.run_threshold_determination(rec, entity)

    rec["measured_head"] = measured
    rec["threshold_head"] = threshold
    rec["determination_outcome"] = outcome
    rec["status"] = "DETERMINED"
    db.touch(rec)
    return response.object_response(serializers.registration(rec))


@bp.post("/registrations/<registration_id>/appeal")
@roles(ROLE_REPORTER_AGENT)
def appeal(registration_id):
    payload = V.body()
    V.get_string(payload, "appeal_reason", min_len=1, max_len=4000)

    rec = lookup.registration(registration_id)

    if g.user_id != rec["reporting_entity_id"]:
        raise ApiError(
            ERR_FOREIGN_REPORTING_ENTITY,
            "Only the firm itself may appeal its determination.",
        )

    _require_status(rec, "DETERMINED")

    if int(rec["appeal_count"] or 0) >= constants.APPEAL_LIMIT:
        raise ApiError(ERR_APPEAL_LIMIT_REACHED, "The appeal ceiling has already been reached.")

    rec["appeal_count"] = int(rec["appeal_count"] or 0) + 1
    rec["status"] = "UNDER_APPEAL"
    db.touch(rec)
    return response.object_response(serializers.registration(rec))


@bp.post("/registrations/<registration_id>/redetermine")
@roles(ROLE_PROGRAM_ADMIN)
def redetermine(registration_id):
    payload = V.body()
    basis = V.get_enum(payload, "basis_variant", V.BASIS_VARIANTS)

    rec = lookup.registration(registration_id)
    _require_status(rec, "UNDER_APPEAL")

    entity = db.reporting_entities[rec["reporting_entity_id"]]
    previous_basis = rec["basis_variant"]
    rec["basis_variant"] = basis
    try:
        measured, threshold, outcome = calculations.run_threshold_determination(rec, entity)
    except ApiError:
        rec["basis_variant"] = previous_basis
        raise

    rec["measured_head"] = measured
    rec["threshold_head"] = threshold
    rec["determination_outcome"] = outcome
    rec["status"] = "DETERMINED"
    db.touch(rec)
    return response.object_response(serializers.registration(rec))


@bp.post("/registrations/<registration_id>/activate")
@roles(ROLE_PROGRAM_ADMIN)
def activate(registration_id):
    rec = lookup.registration(registration_id)
    _require_status(rec, "DETERMINED")

    if rec["determination_outcome"] != "MANDATORY":
        raise ApiError(ERR_ENTITY_EXEMPT, "An exempt determination has no reporting obligation.")

    entity = db.reporting_entities[rec["reporting_entity_id"]]
    if int(entity["outstanding_penalty_cents"] or 0) > 0:
        raise ApiError(
            ERR_OUTSTANDING_PENALTY_BLOCKS_ACTIVATION,
            "The firm still owes outstanding penalties.",
        )

    minted = [
        r
        for r in db.registrations.values()
        if r["determination_year"] == rec["determination_year"]
        and r.get("registration_number") is not None
    ]
    sequence = 1 + len(minted)
    rec["registration_number"] = "MPR-%d-%04d" % (rec["determination_year"], sequence)
    rec["effective_from"] = clock.iso_now()
    rec["suspended_reason"] = None
    rec["status"] = "ACTIVE"
    db.touch(rec)
    return response.object_response(serializers.registration(rec))


@bp.post("/registrations/<registration_id>/suspend")
@roles(ROLE_PROGRAM_ADMIN)
def suspend(registration_id):
    payload = V.body()
    reason = V.get_string(payload, "suspended_reason")
    if reason != "ADMIN_ACTION":
        raise V.bad("suspended_reason must be ADMIN_ACTION for an administrative suspension.")

    rec = lookup.registration(registration_id)
    _require_status(rec, "ACTIVE")

    rec["status"] = "SUSPENDED"
    rec["suspended_reason"] = "ADMIN_ACTION"
    db.touch(rec)

    cascades.void_in_flight_submissions(rec["reporting_entity_id"])
    return response.object_response(serializers.registration(rec))


@bp.get("/registrations/<registration_id>")
@roles(*READ_ROLES)
def get_registration(registration_id):
    rec = lookup.registration(registration_id)
    return response.object_response(serializers.registration(rec))


@bp.get("/registrations")
@roles(*READ_ROLES)
def list_registrations():
    limit, offset = V.pagination()
    entity_id = V.query_str("reporting_entity_id")
    year = V.query_int("determination_year")
    status = V.query_str("status")
    outcome = V.query_str("determination_outcome")

    records = db.ordered(db.registrations.values())
    if entity_id is not None:
        records = [r for r in records if r["reporting_entity_id"] == entity_id]
    if year is not None:
        records = [r for r in records if r["determination_year"] == year]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if outcome is not None:
        records = [r for r in records if r["determination_outcome"] == outcome]

    page, total = V.paginate(records, limit, offset)
    return response.array_response(
        [serializers.registration(r) for r in page], limit, offset, total
    )
