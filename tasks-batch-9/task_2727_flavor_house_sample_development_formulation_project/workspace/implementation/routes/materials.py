"""RawMaterial and SubstantiationRecord endpoints (PRD §3.2)."""

from flask import Blueprint, request

import constants as K
import serializers as S
from db import base_entity, db, now_logical, touch
from errors import fail
from middleware import ALL_ROLES, auth
from response import created, ok
from routes.common import list_response, need
from services import cascade, graph
from validate import (as_code_subset, as_datetime, as_enum, as_int, as_str,
                      body_json, optional, require)

bp = Blueprint("materials", __name__)


def _material(material_id):
    return need(db.materials, material_id, "ERR_MATERIAL_NOT_FOUND",
                "raw material")


def _record(record_id):
    return need(db.records, record_id, "ERR_SUBSTANTIATION_NOT_FOUND",
                "substantiation record")


@bp.post("/raw-materials")
def create_material():
    auth(["PurchasingManager"])
    body = body_json()
    material_code = as_str(require(body, "material_code"), "material_code", 1, 40)
    name = as_str(require(body, "name"), "name", 1, 120)
    cost = as_int(require(body, "cost_per_kg_cents"), "cost_per_kg_cents",
                  minimum=1)
    natural_status = as_enum(require(body, "natural_status"), "natural_status",
                             K.NATURAL_STATUSES)
    potency_class = as_enum(require(body, "potency_class"), "potency_class",
                            K.POTENCY_CLASSES)
    max_use_ppm = as_int(require(body, "max_use_ppm"), "max_use_ppm",
                         minimum=1, maximum=1000000)
    allergens = as_code_subset(optional(body, "allergen_codes", []),
                               "allergen_codes", K.ALLERGEN_CODES)

    for existing in db.materials.values():
        if existing["material_code"] == material_code:
            fail("ERR_DUPLICATE_CODE",
                 "material_code %s already exists" % material_code)

    material = base_entity()
    material.update({
        "material_code": material_code,
        "name": name,
        "cost_per_kg_cents": cost,
        "natural_status": natural_status,
        "potency_class": potency_class,
        "max_use_ppm": max_use_ppm,
        "allergen_codes": allergens,
    })
    db.materials[material["id"]] = material
    return created(S.material_out(material))


@bp.get("/raw-materials")
def list_materials():
    auth(ALL_ROLES)
    claim_status = request.args.get("claim_status")
    natural_status = request.args.get("natural_status")
    potency_class = request.args.get("potency_class")
    rows = []
    for material in db.materials.values():
        if natural_status is not None and material["natural_status"] != natural_status:
            continue
        if potency_class is not None and material["potency_class"] != potency_class:
            continue
        if claim_status is not None and \
                graph.material_claim_status(material["id"]) != claim_status:
            continue
        rows.append(material)
    return list_response(rows, S.material_out)


@bp.get("/raw-materials/<material_id>")
def get_material(material_id):
    auth(ALL_ROLES)
    return ok(S.material_out(_material(material_id)))


@bp.patch("/raw-materials/<material_id>")
def reprice_material(material_id):
    auth(["PurchasingManager"])
    body = body_json()
    cost = as_int(require(body, "cost_per_kg_cents"), "cost_per_kg_cents",
                  minimum=1)
    material = _material(material_id)
    material["cost_per_kg_cents"] = cost
    touch(material)
    cascade.reprice_cascade(material)
    return ok(S.material_out(material))


# --- SubstantiationRecord ---------------------------------------------------

@bp.post("/substantiation-records")
def create_record():
    auth(["RegulatoryAffairs"])
    body = body_json()
    raw_material_id = as_str(require(body, "raw_material_id"), "raw_material_id")
    claim_type = as_enum(require(body, "claim_type"), "claim_type", K.CLAIM_TYPES)
    issuing_body = as_str(require(body, "issuing_body"), "issuing_body", 1, 120)
    document_ref = as_str(require(body, "document_ref"), "document_ref", 1, 80)
    valid_until = as_datetime(require(body, "valid_until"), "valid_until")
    _material(raw_material_id)

    record = base_entity()
    record.update({
        "raw_material_id": raw_material_id,
        "claim_type": claim_type,
        "issuing_body": issuing_body,
        "document_ref": document_ref,
        "valid_until": valid_until,
        "status": "PENDING",
        "verified_at": None,
        "revocation_reason": None,
    })
    db.records[record["id"]] = record
    return created(S.record_out(record))


@bp.get("/substantiation-records")
def list_records():
    auth(ALL_ROLES)
    raw_material_id = request.args.get("raw_material_id")
    claim_type = request.args.get("claim_type")
    status = request.args.get("status")
    rows = []
    for record in db.records.values():
        if raw_material_id is not None and record["raw_material_id"] != raw_material_id:
            continue
        if claim_type is not None and record["claim_type"] != claim_type:
            continue
        if status is not None and record["status"] != status:
            continue
        rows.append(record)
    return list_response(rows, S.record_out)


@bp.get("/substantiation-records/<record_id>")
def get_record(record_id):
    auth(ALL_ROLES)
    return ok(S.record_out(_record(record_id)))


@bp.post("/substantiation-records/<record_id>/verify")
def verify_record(record_id):
    auth(["RegulatoryAffairs"])
    body_json()
    record = _record(record_id)
    if record["status"] not in ("PENDING", "REVOKED"):
        fail("ERR_SUBSTANTIATION_STATE_INVALID",
             "cannot verify a record in status %s" % record["status"])
    was_revoked = record["status"] == "REVOKED"
    record["status"] = "VERIFIED"
    record["verified_at"] = now_logical()
    touch(record)
    if was_revoked:
        # §3.8: the pinned certificate's version advanced, so every document
        # pinned to it becomes STALE.
        cascade.staleify_documents_for_record(record)
    return ok(S.record_out(record))


@bp.post("/substantiation-records/<record_id>/revoke")
def revoke_record(record_id):
    auth(["RegulatoryAffairs"])
    body = body_json()
    reason = as_str(require(body, "revocation_reason"), "revocation_reason")
    record = _record(record_id)
    if record["status"] != "VERIFIED":
        fail("ERR_SUBSTANTIATION_STATE_INVALID",
             "cannot revoke a record in status %s" % record["status"])
    record["status"] = "REVOKED"
    record["revocation_reason"] = reason
    touch(record)
    cascade.revocation_cascade(record)
    return ok(S.record_out(record))
