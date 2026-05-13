"""Damage assessment endpoints."""

from flask import Blueprint, request

from clock import clock
from db import db, new_id
from errors import err
from middleware import require_roles
from response import object_response
from serializers import damage_assessment as ser_da
from services.damage import compute_damage_amount_cents
from validators import (
    require_dict,
    require_enum,
    require_int,
    require_list,
    require_number,
    require_str,
)


bp = Blueprint("damage_assessments", __name__)


DAMAGE_CLASSES = {"MINOR", "MODERATE", "TOTAL_LOSS"}
CAUSES = {"TEMPERATURE_DEVIATION", "DURATION", "CARGO_SENSITIVITY", "OTHER"}
VARIANTS = {"INSURED_VALUE", "INVOICE_VALUE"}


def _bump(row):
    row["updated_at"] = clock.now_iso()
    row["version"] = row.get("version", 0) + 1


def _validate_evidence(task_id: str, evidence_alert_ids: list):
    """Validate evidence_alert_ids per ERR_EVIDENCE_REQUIRED."""
    if not isinstance(evidence_alert_ids, list) or len(evidence_alert_ids) < 1:
        err("ERR_EVIDENCE_REQUIRED", "evidence_alert_ids must be non-empty.")
    # Existence (REFERENCE_NOT_FOUND first)
    for aid in evidence_alert_ids:
        if not isinstance(aid, str) or not db.alerts.exists(aid):
            err("ERR_REFERENCE_NOT_FOUND", "evidence_alert_id not found.")
    # Same-task + status in {RESOLVED, CLOSED}
    for aid in evidence_alert_ids:
        a = db.alerts.get(aid)
        if a["task_id"] != task_id:
            err("ERR_EVIDENCE_REQUIRED", "Evidence alert is on a different task.")
        if a["status"] not in {"RESOLVED", "CLOSED"}:
            err("ERR_EVIDENCE_REQUIRED", "Evidence alert is not RESOLVED or CLOSED.")


def _validate_quantity_for_task(task: dict, damaged_quantity):
    if not isinstance(damaged_quantity, int) or isinstance(damaged_quantity, bool):
        err("ERR_VALIDATION", "damaged_quantity must be an integer.")
    if damaged_quantity < 1 or damaged_quantity > task["cargo_quantity"]:
        err("ERR_QUANTITY_INVALID", "damaged_quantity out of bounds.")


def _validate_variant_inputs(variant: str, invoice_unit_value_cents):
    if variant == "INVOICE_VALUE":
        if invoice_unit_value_cents is None:
            err("ERR_INVOICE_VALUE_REQUIRED", "invoice_unit_value_cents required.")
        if (not isinstance(invoice_unit_value_cents, int)
                or isinstance(invoice_unit_value_cents, bool)
                or invoice_unit_value_cents <= 0):
            err("ERR_INVOICE_VALUE_REQUIRED",
                "invoice_unit_value_cents must be a positive integer.")


@bp.post("/damage-assessments")
@require_roles("COMPLIANCE_OFFICER")
def create_assessment():
    body = require_dict(request.get_json(silent=True) or {})
    task_id = require_str(body.get("task_id"), field="task_id", min_len=1)
    task = db.tasks.get(task_id)
    if task is None:
        err("ERR_REFERENCE_NOT_FOUND", "task_id not found.")
    if task["status"] not in {"DELIVERED", "CLOSED"}:
        err("ERR_INVALID_STATE", "Task must be DELIVERED or CLOSED.")

    # Schema-level basics for fields used in downstream business checks
    damage_class = require_enum(body.get("damage_class"), DAMAGE_CLASSES, field="damage_class")
    salvage_pct = body.get("salvage_pct")
    require_number(salvage_pct, field="salvage_pct", min_val=0.00, max_val=0.99)
    cause_primary = require_enum(body.get("cause_primary"), CAUSES, field="cause_primary")
    variant = require_enum(body.get("variant"), VARIANTS, field="variant")

    # Validations in priority order:
    # Priority 9 (ERR_EVIDENCE_REQUIRED) before priority 10 (ERR_INVOICE_VALUE_REQUIRED)
    _validate_evidence(task_id, body.get("evidence_alert_ids"))
    _validate_variant_inputs(variant, body.get("invoice_unit_value_cents"))
    # Priority 16 (ERR_QUANTITY_INVALID) afterwards (lower priority than evidence/invoice)
    _validate_quantity_for_task(task, body.get("damaged_quantity"))

    vehicle = db.vehicles.get(task.get("vehicle_id"))
    if vehicle is None:
        err("ERR_INVALID_STATE", "Vehicle missing for task.")

    now_iso = clock.now_iso()
    row = {
        "id": new_id(),
        "task_id": task_id,
        "damaged_quantity": int(body["damaged_quantity"]),
        "damage_class": damage_class,
        "salvage_pct": float(salvage_pct),
        "cause_primary": cause_primary,
        "evidence_alert_ids": list(body["evidence_alert_ids"]),
        "damage_amount_cents": 0,
        "variant": variant,
        "invoice_unit_value_cents": (
            int(body["invoice_unit_value_cents"])
            if variant == "INVOICE_VALUE"
            else 0
        ),
        "status": "DRAFT",
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
    }
    row["damage_amount_cents"] = compute_damage_amount_cents(row, task, vehicle)
    db.assessments.put(row)
    return object_response(ser_da(row), status_code=201)


@bp.patch("/damage-assessments/<assessment_id>")
@require_roles("COMPLIANCE_OFFICER")
def patch_assessment(assessment_id):
    row = db.assessments.get(assessment_id)
    if row is None:
        err("ERR_NOT_FOUND", "DamageAssessment not found.")
    if row["status"] != "DRAFT":
        err("ERR_INVALID_STATE", "Assessment must be DRAFT to patch.")

    body = require_dict(request.get_json(silent=True) or {})

    # OCC check (priority 18, but per PRD OCC surfaces before ERR_VALIDATION)
    if "version" in body:
        if body["version"] != row["version"]:
            err("ERR_VERSION_CONFLICT", "version mismatch.")

    task = db.tasks.get(row["task_id"])
    vehicle = db.vehicles.get(task.get("vehicle_id"))

    # Apply candidate fields (no mutation yet) — clone the row
    candidate = dict(row)

    if "damage_class" in body:
        candidate["damage_class"] = require_enum(
            body["damage_class"], DAMAGE_CLASSES, field="damage_class"
        )
    if "salvage_pct" in body:
        require_number(body["salvage_pct"], field="salvage_pct", min_val=0.00, max_val=0.99)
        candidate["salvage_pct"] = float(body["salvage_pct"])
    if "cause_primary" in body:
        candidate["cause_primary"] = require_enum(
            body["cause_primary"], CAUSES, field="cause_primary"
        )
    if "variant" in body:
        candidate["variant"] = require_enum(body["variant"], VARIANTS, field="variant")
    if "invoice_unit_value_cents" in body:
        if (body["invoice_unit_value_cents"] is not None
                and (not isinstance(body["invoice_unit_value_cents"], int)
                     or isinstance(body["invoice_unit_value_cents"], bool))):
            err("ERR_VALIDATION", "invoice_unit_value_cents must be an integer.")
        if body["invoice_unit_value_cents"] is not None:
            candidate["invoice_unit_value_cents"] = int(body["invoice_unit_value_cents"])
    if "evidence_alert_ids" in body:
        candidate["evidence_alert_ids"] = body["evidence_alert_ids"]
    if "damaged_quantity" in body:
        candidate["damaged_quantity"] = body["damaged_quantity"]

    # Business validations in priority order
    _validate_evidence(candidate["task_id"], candidate.get("evidence_alert_ids", []))
    _validate_variant_inputs(candidate["variant"], candidate.get("invoice_unit_value_cents"))
    _validate_quantity_for_task(task, candidate.get("damaged_quantity"))

    # Recompute damage_amount_cents
    candidate["damage_amount_cents"] = compute_damage_amount_cents(candidate, task, vehicle)

    # Commit
    for k, v in candidate.items():
        row[k] = v
    _bump(row)
    return object_response(ser_da(row))


@bp.post("/damage-assessments/<assessment_id>/finalize")
@require_roles("COMPLIANCE_OFFICER")
def finalize_assessment(assessment_id):
    row = db.assessments.get(assessment_id)
    if row is None:
        err("ERR_NOT_FOUND", "DamageAssessment not found.")
    if row["status"] != "DRAFT":
        err("ERR_INVALID_STATE", "Assessment must be DRAFT to finalize.")
    if not row.get("evidence_alert_ids"):
        err("ERR_EVIDENCE_REQUIRED", "evidence_alert_ids required to finalize.")
    if row.get("damage_amount_cents") is None:
        err("ERR_INVALID_STATE", "damage_amount_cents must be computed.")
    row["status"] = "FINALIZED"
    _bump(row)
    return object_response(ser_da(row))


@bp.get("/damage-assessments/<assessment_id>")
@require_roles("SHIPPER", "CARRIER", "CONSIGNEE", "COMPLIANCE_OFFICER", "INSURANCE_ADJUSTER")
def get_assessment(assessment_id):
    row = db.assessments.get(assessment_id)
    if row is None:
        err("ERR_NOT_FOUND", "DamageAssessment not found.")
    return object_response(ser_da(row))
