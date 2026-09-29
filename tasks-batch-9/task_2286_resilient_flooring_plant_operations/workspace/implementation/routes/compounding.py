"""Formulations and their components (PRD 3.2)."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import cascades
from calc import d
from db import db, new_row, now, ordered, serialize as _ser, touch
from errors import ApiError
from middleware import authorize, find, user_id
from response import enum_filter, list_response, object_response, string_filter
from support import STATUS_CREATED, body, unique
from validate import field as F
from validate import validate

bp = Blueprint("compounding", __name__)

FORMULATION_STATUS = ("DRAFT", "UNDER_REVIEW", "APPROVED", "REJECTED", "SUPERSEDED", "RETIRED")
INDENTATION_CLASS = ("CLASS_23_31", "CLASS_33_42", "CLASS_34_43")
FORMULATION_READERS = ("PlantAdmin", "Formulator", "TechnicalDirector", "QaTechnician",
                       "ProductionPlanner")

EDITABLE = ("DRAFT", "REJECTED")


def _new_formulation(code, supersedes_id, revision):
    row = new_row()
    row.update({
        "formulation_code": code,
        "revision": revision,
        "supersedes_formulation_id": supersedes_id,
        "status": "DRAFT",
        "authored_by_user_id": user_id(),
        "submitted_by_user_id": None,
        "approved_by_user_id": None,
        "approved_at": None,
        "rejection_count": 0,
        "open_revision_count": 0,
        "cost_basis": "LIVE",
    })
    db.formulations[row["id"]] = row
    calc.apply_blend_metrics(row)
    return row


def _materials_active(formulation, extra_material=None):
    """Band 14 (V-REF-2)."""
    if extra_material is not None and extra_material["status"] != "ACTIVE":
        raise ApiError("ERR_RAW_MATERIAL_NOT_ACTIVE")
    for component in calc.components_of(formulation["id"]):
        material = db.raw_materials.get(component["raw_material_id"])
        if material is None or material["status"] != "ACTIVE":
            raise ApiError("ERR_RAW_MATERIAL_NOT_ACTIVE")


def _state_guard(formulation, allowed):
    """Band 7 (V-STATE-1)."""
    if formulation["status"] not in allowed:
        raise ApiError("ERR_INVALID_FORMULATION_STATE")


# ---------------------------------------------------------------------------
# Formulation
# ---------------------------------------------------------------------------

@bp.post("/formulations")
def create_formulation():
    authorize("Formulator")
    data = validate([
        F("formulation_code", "string", required=True),
        F("supersedes_formulation_id", "string"),
    ], body())
    if data["supersedes_formulation_id"] is not None:
        find("formulations", data["supersedes_formulation_id"])
    unique("formulations", "formulation_code", data["formulation_code"])
    row = _new_formulation(data["formulation_code"], data["supersedes_formulation_id"], 1)
    return object_response(_ser(row), STATUS_CREATED)


@bp.get("/formulations")
def list_formulations():
    authorize(*FORMULATION_READERS)
    status = enum_filter(request.args, "status", FORMULATION_STATUS)
    parent = string_filter(request.args, "supersedes_formulation_id")
    cls = enum_filter(request.args, "indentation_resistance_class", INDENTATION_CLASS)
    rows = [r for r in db.formulations.values()
            if (status is None or r["status"] == status)
            and (parent is None or r["supersedes_formulation_id"] == parent)
            and (cls is None or r["indentation_resistance_class"] == cls)]
    return list_response(rows, request.args, _ser)


@bp.get("/formulations/<row_id>")
def read_formulation(row_id):
    authorize(*FORMULATION_READERS)
    return object_response(_ser(find("formulations", row_id)))


@bp.get("/formulations/<row_id>/components")
def list_components(row_id):
    authorize("PlantAdmin", "Formulator", "TechnicalDirector", "QaTechnician")
    formulation = find("formulations", row_id)
    rows = [c for c in db.formulation_components.values()
            if c["formulation_id"] == formulation["id"]]
    return list_response(rows, request.args, _ser)


# ---------------------------------------------------------------------------
# FormulationComponent
# ---------------------------------------------------------------------------

@bp.post("/formulations/<row_id>/components")
def add_component(row_id):
    authorize("Formulator")
    data = validate([
        F("raw_material_id", "string", required=True),
        F("phr", "number", required=True, exclusive_min=0, decimals=2),
    ], body())
    formulation = find("formulations", row_id)
    material = find("raw_materials", data["raw_material_id"])
    _state_guard(formulation, EDITABLE)
    for existing in calc.components_of(formulation["id"]):
        if existing["raw_material_id"] == material["id"]:
            raise ApiError("ERR_DUPLICATE_CODE")
    if data["phr"] > d(material["max_phr"]):
        raise ApiError("ERR_PHR_EXCEEDS_MATERIAL_MAX")
    _materials_active(formulation, material)

    component = new_row()
    component.update({
        "formulation_id": formulation["id"],
        "raw_material_id": material["id"],
        "phr": data["phr"],
        "material_cost_snapshot_cents": None,
        "snapshot_at": None,
    })
    db.formulation_components[component["id"]] = component
    formulation["status"] = "DRAFT"
    calc.apply_blend_metrics(formulation)
    touch(formulation)
    return object_response(_ser(component), STATUS_CREATED)


@bp.delete("/formulations/<row_id>/components/<component_id>")
def remove_component(row_id, component_id):
    authorize("Formulator")
    formulation = find("formulations", row_id)
    component = find("formulation_components", component_id)
    if component["formulation_id"] != formulation["id"]:
        raise ApiError("ERR_FORMULATION_COMPONENT_NOT_FOUND")
    _state_guard(formulation, EDITABLE)
    del db.formulation_components[component["id"]]
    formulation["status"] = "DRAFT"
    calc.apply_blend_metrics(formulation)
    touch(formulation)
    return object_response(_ser(formulation))


# ---------------------------------------------------------------------------
# review workflow
# ---------------------------------------------------------------------------

@bp.post("/formulations/<row_id>/submit")
def submit_formulation(row_id):
    authorize("Formulator")
    formulation = find("formulations", row_id)
    _state_guard(formulation, ("DRAFT",))
    components = calc.components_of(formulation["id"])
    metrics = calc.formulation_blend_metrics(formulation)
    if not components or d(metrics["resin_phr"]) != Decimal("100.00"):
        raise ApiError("ERR_RESIN_PHR_NOT_NORMALIZED")
    _materials_active(formulation)
    formulation.update(metrics)
    formulation["status"] = "UNDER_REVIEW"
    formulation["submitted_by_user_id"] = user_id()
    touch(formulation)
    return object_response(_ser(formulation))


@bp.post("/formulations/<row_id>/review-decision")
def review_formulation(row_id):
    authorize("TechnicalDirector")
    data = validate([
        F("decision", "string", required=True, enum=("APPROVE", "REJECT")),
        F("review_note", "string"),
    ], body())
    formulation = find("formulations", row_id)
    _state_guard(formulation, ("UNDER_REVIEW",))
    if user_id() == formulation["authored_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if data["decision"] == "APPROVE":
        metrics = calc.formulation_blend_metrics(formulation)
        score = metrics["performance_score"]
        if score is None or d(score) < Decimal("60.00"):
            raise ApiError("ERR_PERFORMANCE_SCORE_BELOW_MINIMUM")
        if metrics["indentation_resistance_class"] == "CLASS_23_31":
            raise ApiError("ERR_INDENTATION_CLASS_TOO_LOW")
        _materials_active(formulation)

        stamp = now()
        for component in calc.components_of(formulation["id"]):
            material = db.raw_materials[component["raw_material_id"]]
            component["material_cost_snapshot_cents"] = material["cost_per_kg_cents"]
            component["snapshot_at"] = stamp
            touch(component)
        formulation["status"] = "APPROVED"
        formulation["cost_basis"] = "PINNED"
        calc.apply_blend_metrics(formulation)
        formulation["approved_by_user_id"] = user_id()
        formulation["approved_at"] = stamp
        touch(formulation)

        predecessor_id = formulation["supersedes_formulation_id"]
        predecessor = db.formulations.get(predecessor_id) if predecessor_id else None
        if predecessor is not None and predecessor["status"] == "APPROVED":
            predecessor["status"] = "SUPERSEDED"
            touch(predecessor)
            cascades.refresh_pin_stale(predecessor)
        cascades.refresh_pin_stale(formulation)
    else:
        _materials_active(formulation)
        formulation["status"] = "REJECTED"
        formulation["rejection_count"] = formulation["rejection_count"] + 1
        touch(formulation)
    return object_response(_ser(formulation))


@bp.post("/formulations/<row_id>/revisions")
def create_revision(row_id):
    authorize("Formulator")
    data = validate([
        F("formulation_code", "string", required=True),
        F("expected_formulation_version", "integer", required=True),
    ], body())
    parent = find("formulations", row_id)
    _state_guard(parent, ("APPROVED",))
    if data["expected_formulation_version"] != parent["version"]:
        raise ApiError("ERR_STALE_FORMULATION_VERSION")
    unique("formulations", "formulation_code", data["formulation_code"])

    revision = _new_formulation(data["formulation_code"], parent["id"], parent["revision"] + 1)
    for component in ordered([c for c in db.formulation_components.values()
                              if c["formulation_id"] == parent["id"]]):
        copy = new_row()
        copy.update({
            "formulation_id": revision["id"],
            "raw_material_id": component["raw_material_id"],
            "phr": component["phr"],
            "material_cost_snapshot_cents": None,
            "snapshot_at": None,
        })
        db.formulation_components[copy["id"]] = copy
    calc.apply_blend_metrics(revision)
    parent["open_revision_count"] = parent["open_revision_count"] + 1
    touch(parent)
    # PRD 3.5: "or its `version` ceases to equal the SKU's
    # `pinned_formulation_version`, `pin_stale` becomes true."
    cascades.refresh_pin_stale(parent)
    return object_response(_ser(revision), STATUS_CREATED)


__all__ = ["bp"]
