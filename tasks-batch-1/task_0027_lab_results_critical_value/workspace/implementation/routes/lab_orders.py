"""LabOrder CRUD + cancel."""
from __future__ import annotations

from typing import Optional

from flask import Blueprint, request

import db
from errors import (
    APIError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_CLINICIAN_ROLE_MISMATCH,
)
from middleware import require_auth, get_json_body
from response import ok_object, ok_array, paginate_params, slice_page
from services.validation import (
    require_fields, require_string, require_enum, lookup_or_404,
)
from services.calculations import compute_tat_lab_processing


bp = Blueprint("lab_orders", __name__)

PANEL_CODES = {"CMP", "CBC", "TROP", "GLUC"}
PRIORITIES = {"STAT", "ROUTINE"}
TAT_VARIANTS = {"clinical_chronology", "lab_processing"}


# ---------- POST /patients/{patient_id}/lab-orders --------------------------

@bp.post("/patients/<pid>/lab-orders")
def create_lab_order(pid):
    require_auth(["OrderingProvider"])()
    body = get_json_body()
    require_fields(body, ["ordering_clinician_id", "panel_code"])
    ordering_id = body["ordering_clinician_id"]
    panel = body["panel_code"]
    priority = body.get("priority", "ROUTINE")

    require_string(ordering_id, "ordering_clinician_id")
    require_enum(panel, PANEL_CODES, "panel_code")
    require_enum(priority, PRIORITIES, "priority")

    # Path-id existence first.
    patient = lookup_or_404(db.patients, pid, "Patient")
    # FK existence.
    clinician = lookup_or_404(db.clinicians, ordering_id, "Clinician")
    # Role-type pairing (§3.1).
    if clinician.get("role_type") != "ORDERING_PROVIDER":
        raise APIError(ERR_CLINICIAN_ROLE_MISMATCH, 422,
                       "ordering_clinician_id must reference an ORDERING_PROVIDER")

    order = {
        "patient_id": patient["id"],
        "ordering_clinician_id": ordering_id,
        "panel_code": panel,
        "priority": priority,
        "status": "DRAFT",
        "ordered_at": db.get_current_utc_iso(),
        "specimens_count": 0,
        "accessioned_count": 0,
        "turn_around_time_minutes": None,
        "compliance_incident": False,
    }
    db.stamp_common(order)
    db.lab_orders[order["id"]] = order
    return ok_object(order, http_status=201)


# ---------- GET /lab-orders/{id} -------------------------------------------

@bp.get("/lab-orders/<oid>")
def get_lab_order(oid):
    require_auth(["LabTech", "LabDirector", "OrderingProvider"])()
    o = lookup_or_404(db.lab_orders, oid, "LabOrder")
    tat_variant = request.args.get("tat_variant", "clinical_chronology")
    if tat_variant not in TAT_VARIANTS:
        raise APIError(ERR_INVALID_REQUEST, 400,
                       f"tat_variant must be one of: {sorted(TAT_VARIANTS)}")
    if tat_variant == "lab_processing":
        # Compute on demand; do not store on the order.
        view = dict(o)
        view["turn_around_time_minutes"] = compute_tat_lab_processing(o["id"])
        return ok_object(view)
    return ok_object(o)


# ---------- GET /lab-orders ------------------------------------------------

@bp.get("/lab-orders")
def list_lab_orders():
    require_auth(["LabTech", "LabDirector", "OrderingProvider"])()
    limit, offset = paginate_params(request.args)
    pid_filter = request.args.get("patient_id")
    clin_filter = request.args.get("ordering_clinician_id")
    status_filter = request.args.get("status")
    items = list(db.lab_orders.values())
    if pid_filter is not None:
        items = [o for o in items if o.get("patient_id") == pid_filter]
    if clin_filter is not None:
        items = [o for o in items if o.get("ordering_clinician_id") == clin_filter]
    if status_filter is not None:
        items = [o for o in items if o.get("status") == status_filter]
    items.sort(key=lambda x: x["created_at"])
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total)


# ---------- POST /lab-orders/{id}/cancel ----------------------------------

@bp.post("/lab-orders/<oid>/cancel")
def cancel_lab_order(oid):
    require_auth(["OrderingProvider"])()
    o = lookup_or_404(db.lab_orders, oid, "LabOrder")

    # State guard: only DRAFT may be cancelled by the OrderingProvider.
    if o.get("status") != "DRAFT":
        raise APIError(ERR_INVALID_STATE, 409,
                       f"LabOrder.status is '{o.get('status')}', not DRAFT")
    # Also forbidden if any specimen is ACCESSIONED.
    for s in db.specimens.values():
        if s.get("lab_order_id") == oid and s.get("status") == "ACCESSIONED":
            raise APIError(ERR_INVALID_STATE, 409,
                           "Cannot cancel: at least one specimen has been accessioned")

    o["status"] = "CANCELLED"
    db.bump(o)

    # Cascade: specimens in DRAFT, COLLECTED, IN_TRANSIT → REJECTED with reason=MISLABELED.
    for s in db.specimens.values():
        if s.get("lab_order_id") != oid:
            continue
        if s.get("status") in ("DRAFT", "COLLECTED", "IN_TRANSIT"):
            s["status"] = "REJECTED"
            s["reject_reason"] = "MISLABELED"
            db.bump(s)

    # Recompute counters after cascade.
    from services.calculations import recompute_order_counters
    recompute_order_counters(o)

    return ok_object(o)
