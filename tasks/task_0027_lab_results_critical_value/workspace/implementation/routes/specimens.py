"""Specimen CRUD + chain-of-custody actions."""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

from flask import Blueprint, request

import db
from errors import (
    APIError, ERR_INVALID_STATE, ERR_INVALID_REQUEST,
    ERR_CLINICIAN_ROLE_MISMATCH, ERR_UNAUTHORIZED,
    ERR_COLLECTOR_BUSY, ERR_RELEASED_RESULT_BLOCKS_REJECT,
)
from middleware import require_auth, get_json_body, current_user_id
from response import ok_object, ok_array, paginate_params, slice_page
from services.validation import (
    require_fields, require_string, require_enum, lookup_or_404,
)
from services.calculations import recompute_order_counters
from services.cascades import (
    cascade_specimen_to_lab_order,
)


bp = Blueprint("specimens", __name__)

CONTAINERS = {"RED", "LAVENDER", "GREEN", "GRAY"}
REJECT_REASONS = {"HEMOLYZED", "CLOTTED", "INSUFFICIENT_VOLUME", "MISLABELED"}


# ---------- POST /lab-orders/{order_id}/specimens -------------------------

@bp.post("/lab-orders/<oid>/specimens")
def create_specimen(oid):
    require_auth(["Phlebotomist", "LabTech"])()
    body = get_json_body()
    require_fields(body, ["collector_clinician_id", "container_code"])
    collector_id = body["collector_clinician_id"]
    container = body["container_code"]

    require_string(collector_id, "collector_clinician_id")
    require_enum(container, CONTAINERS, "container_code")

    order = lookup_or_404(db.lab_orders, oid, "LabOrder")
    collector = lookup_or_404(db.clinicians, collector_id, "Clinician")
    if collector.get("role_type") != "PHLEBOTOMIST":
        raise APIError(ERR_CLINICIAN_ROLE_MISMATCH, 422,
                       "collector_clinician_id must reference a PHLEBOTOMIST")

    spec = {
        "lab_order_id": oid,
        "collector_clinician_id": collector_id,
        "container_code": container,
        "status": "DRAFT",
        "collected_at": None,
        "accessioned_at": None,
        "reject_reason": None,
    }
    db.stamp_common(spec)
    db.specimens[spec["id"]] = spec

    # Recompute counters on the parent.
    recompute_order_counters(order)
    return ok_object(spec, http_status=201)


# ---------- GET /specimens/{id} -------------------------------------------

@bp.get("/specimens/<sid>")
def get_specimen(sid):
    require_auth(["LabTech", "LabDirector", "OrderingProvider", "Phlebotomist"])()
    s = lookup_or_404(db.specimens, sid, "Specimen")
    return ok_object(s)


# ---------- GET /specimens ------------------------------------------------

@bp.get("/specimens")
def list_specimens():
    require_auth(["LabTech", "LabDirector", "OrderingProvider", "Phlebotomist"])()
    limit, offset = paginate_params(request.args)
    order_filter = request.args.get("lab_order_id")
    coll_filter = request.args.get("collector_clinician_id")
    status_filter = request.args.get("status")
    items = list(db.specimens.values())
    if order_filter is not None:
        items = [s for s in items if s.get("lab_order_id") == order_filter]
    if coll_filter is not None:
        items = [s for s in items if s.get("collector_clinician_id") == coll_filter]
    if status_filter is not None:
        items = [s for s in items if s.get("status") == status_filter]
    items.sort(key=lambda x: x["created_at"])
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total)


# ---------- POST /specimens/{id}/collect ----------------------------------

@bp.post("/specimens/<sid>/collect")
def collect_specimen(sid):
    require_auth(["Phlebotomist"])()
    s = lookup_or_404(db.specimens, sid, "Specimen")

    if s.get("status") != "DRAFT":
        raise APIError(ERR_INVALID_STATE, 409, "Specimen.status is not DRAFT")

    order = lookup_or_404(db.lab_orders, s["lab_order_id"], "LabOrder")
    if order.get("status") != "DRAFT":
        raise APIError(ERR_INVALID_STATE, 409, "LabOrder.status is not DRAFT")

    # Ownership: acting Phlebotomist's id MUST equal collector_clinician_id.
    if current_user_id() != s.get("collector_clinician_id"):
        raise APIError(ERR_UNAUTHORIZED, 403,
                       "Acting clinician must be the named collector")

    now_dt = db.get_current_utc_dt()
    # Collector busy check: any non-rejected specimen of the same collector whose
    # collected_at is within 5 minutes of now.
    five = timedelta(minutes=5)
    for other in db.specimens.values():
        if other["id"] == s["id"]:
            continue
        if other.get("collector_clinician_id") != s["collector_clinician_id"]:
            continue
        if other.get("status") not in ("COLLECTED", "IN_TRANSIT", "ACCESSIONED"):
            continue
        other_collected = other.get("collected_at")
        if not other_collected:
            continue
        other_dt = db.parse_iso_dt(other_collected)
        if other_dt is None:
            continue
        diff = abs((now_dt - other_dt).total_seconds())
        if diff < five.total_seconds():
            raise APIError(ERR_COLLECTOR_BUSY, 409,
                           "Collector has another active specimen within 5 minutes")

    s["status"] = "COLLECTED"
    s["collected_at"] = db.get_current_utc_iso()
    db.bump(s)
    recompute_order_counters(order)
    return ok_object(s)


# ---------- POST /specimens/{id}/transit ----------------------------------

@bp.post("/specimens/<sid>/transit")
def transit_specimen(sid):
    require_auth(["Phlebotomist"])()
    s = lookup_or_404(db.specimens, sid, "Specimen")

    if s.get("status") != "COLLECTED":
        raise APIError(ERR_INVALID_STATE, 409, "Specimen.status is not COLLECTED")

    s["status"] = "IN_TRANSIT"
    db.bump(s)
    return ok_object(s)


# ---------- POST /specimens/{id}/accession --------------------------------

@bp.post("/specimens/<sid>/accession")
def accession_specimen(sid):
    require_auth(["LabTech"])()
    s = lookup_or_404(db.specimens, sid, "Specimen")

    if s.get("status") != "IN_TRANSIT":
        raise APIError(ERR_INVALID_STATE, 409, "Specimen.status is not IN_TRANSIT")
    order = lookup_or_404(db.lab_orders, s["lab_order_id"], "LabOrder")
    if order.get("status") not in ("DRAFT", "ACCESSIONED"):
        raise APIError(ERR_INVALID_STATE, 409,
                       "LabOrder is not in a state that accepts accessioning")

    s["status"] = "ACCESSIONED"
    s["accessioned_at"] = db.get_current_utc_iso()
    db.bump(s)

    # Recompute counters BEFORE the cascade reads them.
    recompute_order_counters(order)
    # Cascade DRAFT -> ACCESSIONED if applicable.
    cascade_specimen_to_lab_order(order)
    return ok_object(s)


# ---------- POST /specimens/{id}/reject -----------------------------------

@bp.post("/specimens/<sid>/reject")
def reject_specimen(sid):
    require_auth(["LabTech"])()
    s = lookup_or_404(db.specimens, sid, "Specimen")
    body = get_json_body()
    require_fields(body, ["reject_reason"])
    reason = body["reject_reason"]
    require_enum(reason, REJECT_REASONS, "reject_reason")

    prior = s.get("status")
    if prior not in ("COLLECTED", "IN_TRANSIT", "ACCESSIONED"):
        raise APIError(ERR_INVALID_STATE, 409,
                       f"Specimen.status '{prior}' cannot be rejected")

    # Safety rule: ACCESSIONED specimen with a RELEASED Result cannot be rejected.
    if prior == "ACCESSIONED":
        for r in db.results.values():
            if r.get("specimen_id") == sid and r.get("status") == "RELEASED":
                raise APIError(
                    ERR_RELEASED_RESULT_BLOCKS_REJECT, 409,
                    "Specimen has a RELEASED Result; invalidate the Result first",
                )

    s["status"] = "REJECTED"
    s["reject_reason"] = reason
    db.bump(s)

    order = db.lab_orders.get(s["lab_order_id"])
    if order:
        recompute_order_counters(order)
        cascade_specimen_to_lab_order(order)

    return ok_object(s)
