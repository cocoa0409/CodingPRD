"""Reporting entities and plants (PRD §3.1)."""

from flask import Blueprint

import constants
import db
import lookup
import response
import serializers
import validators as V
from errors import ApiError, ERR_SPECIES_CLASS_MISMATCH
from middleware import (
    ROLE_COMPLIANCE_AUDITOR,
    ROLE_MARKET_ANALYST,
    ROLE_PENALTY_OFFICER,
    ROLE_PROGRAM_ADMIN,
    ROLE_REPORTER_AGENT,
    roles,
)

bp = Blueprint("entities", __name__)

READ_ROLES = (
    ROLE_PROGRAM_ADMIN,
    ROLE_MARKET_ANALYST,
    ROLE_COMPLIANCE_AUDITOR,
    ROLE_PENALTY_OFFICER,
    ROLE_REPORTER_AGENT,
)
ENTITY_LIST_ROLES = (
    ROLE_PROGRAM_ADMIN,
    ROLE_MARKET_ANALYST,
    ROLE_COMPLIANCE_AUDITOR,
    ROLE_PENALTY_OFFICER,
)


# ---------------------------------------------------------------------------
# ReportingEntity
# ---------------------------------------------------------------------------
@bp.post("/reporting-entities")
@roles(ROLE_PROGRAM_ADMIN)
def create_reporting_entity():
    payload = V.body()
    legal_name = V.get_string(payload, "legal_name", min_len=1, max_len=200)
    entity_type = V.get_enum(payload, "entity_type", V.ENTITY_TYPES)
    species_scope = V.get_enum(payload, "species_scope", V.SPECIES)

    rec = db.insert(
        db.reporting_entities,
        {
            "legal_name": legal_name,
            "entity_type": entity_type,
            "species_scope": species_scope,
            "delinquency_points": 0,
            "assessed_penalty_cents": 0,
            "paid_penalty_cents": 0,
            "waived_penalty_cents": 0,
            "outstanding_penalty_cents": 0,
        },
    )
    return response.object_response(serializers.reporting_entity(rec), 201)


@bp.get("/reporting-entities/<entity_id>")
@roles(*READ_ROLES)
def get_reporting_entity(entity_id):
    rec = lookup.reporting_entity(entity_id)
    return response.object_response(serializers.reporting_entity(rec))


@bp.get("/reporting-entities")
@roles(*ENTITY_LIST_ROLES)
def list_reporting_entities():
    limit, offset = V.pagination()
    entity_type = V.query_str("entity_type")
    species_scope = V.query_str("species_scope")

    records = db.ordered(db.reporting_entities.values())
    if entity_type is not None:
        records = [r for r in records if r["entity_type"] == entity_type]
    if species_scope is not None:
        records = [r for r in records if r["species_scope"] == species_scope]

    page, total = V.paginate(records, limit, offset)
    return response.array_response(
        [serializers.reporting_entity(r) for r in page], limit, offset, total
    )


# ---------------------------------------------------------------------------
# Plant
# ---------------------------------------------------------------------------
def _wholesale_required(volume_lbs):
    return int(volume_lbs or 0) >= constants.BOXED_BEEF_THRESHOLD_LBS


@bp.post("/plants")
@roles(ROLE_PROGRAM_ADMIN)
def create_plant():
    payload = V.body()
    entity_id = V.get_string(payload, "reporting_entity_id")
    plant_code = V.get_string(payload, "plant_code", min_len=1, max_len=200)
    species = V.get_enum(payload, "species", V.SPECIES)
    history = V.get_head_history(payload, "annual_head_history")
    boxed = V.get_int(payload, "boxed_beef_volume_lbs_prior_year", required=False, minimum=0, default=0)
    cap = V.get_int(payload, "forward_commitment_cap_head", required=False, minimum=0, default=0)
    status = V.get_enum(payload, "status", V.PLANT_STATUSES, required=False, default="ACTIVE")

    entity = lookup.reporting_entity(entity_id)

    if species != entity["species_scope"]:
        raise ApiError(
            ERR_SPECIES_CLASS_MISMATCH,
            "Plant species must equal the owning firm's species_scope.",
        )

    duplicate = any(
        p["reporting_entity_id"] == entity_id and p["plant_code"] == plant_code
        for p in db.plants.values()
    )
    if duplicate:
        raise V.bad("plant_code must be unique within the reporting entity.")

    rec = db.insert(
        db.plants,
        {
            "reporting_entity_id": entity_id,
            "plant_code": plant_code,
            "species": species,
            "annual_head_history": history,
            "boxed_beef_volume_lbs_prior_year": boxed,
            "forward_commitment_cap_head": cap,
            "status": status,
            "wholesale_reporting_required": _wholesale_required(boxed),
        },
    )
    return response.object_response(serializers.plant(rec), 201)


@bp.patch("/plants/<plant_id>")
@roles(ROLE_PROGRAM_ADMIN)
def patch_plant(plant_id):
    payload = V.body()
    status = V.get_enum(payload, "status", V.PLANT_STATUSES, required=False)
    history = V.get_head_history(payload, "annual_head_history", required=False)
    boxed = V.get_int(payload, "boxed_beef_volume_lbs_prior_year", required=False, minimum=0)
    cap = V.get_int(payload, "forward_commitment_cap_head", required=False, minimum=0)

    rec = lookup.plant(plant_id)

    if status is not None:
        rec["status"] = status
    if history is not None:
        rec["annual_head_history"] = history
    if boxed is not None:
        rec["boxed_beef_volume_lbs_prior_year"] = boxed
    if cap is not None:
        rec["forward_commitment_cap_head"] = cap
    rec["wholesale_reporting_required"] = _wholesale_required(
        rec["boxed_beef_volume_lbs_prior_year"]
    )
    db.touch(rec)
    return response.object_response(serializers.plant(rec))


@bp.get("/plants/<plant_id>")
@roles(*READ_ROLES)
def get_plant(plant_id):
    rec = lookup.plant(plant_id)
    return response.object_response(serializers.plant(rec))


@bp.get("/plants")
@roles(*READ_ROLES)
def list_plants():
    limit, offset = V.pagination()
    entity_id = V.query_str("reporting_entity_id")
    species = V.query_str("species")
    status = V.query_str("status")

    records = db.ordered(db.plants.values())
    if entity_id is not None:
        records = [r for r in records if r["reporting_entity_id"] == entity_id]
    if species is not None:
        records = [r for r in records if r["species"] == species]
    if status is not None:
        records = [r for r in records if r["status"] == status]

    page, total = V.paginate(records, limit, offset)
    return response.array_response([serializers.plant(r) for r in page], limit, offset, total)
