"""Prescriptions — upload, get, approve, reject, revoke."""

from __future__ import annotations

import datetime as _dt

from flask import Blueprint, g, request

from db import (
    append_audit_log,
    db,
    emit_external_event,
    parse_iso,
    platform_clock,
    serialize,
    stamp_create,
    stamp_update,
)
from errors import err
from lookups import get_platform, get_prescription
from middleware import current_actor, require_roles
from response import success_object
from services.cascades import evaluate_prescription_archive, refund_if_paid
from services.calculations import VALIDITY_DAYS_CAP
from validate import occ_check, require_field, require_json, require_pos_int

bp = Blueprint("prescriptions", __name__)


def _validate_drug_items(pid: str, drug_items_raw):
    if not isinstance(drug_items_raw, list) or not drug_items_raw:
        raise err("ERR_INVALID_REQUEST", "drug_items must be a non-empty array.")
    out = []
    for item in drug_items_raw:
        if not isinstance(item, dict):
            raise err("ERR_INVALID_REQUEST", "drug_items entries must be objects.")
        drug_id = item.get("drug_id")
        qty = item.get("qty")
        if not isinstance(drug_id, str) or not isinstance(qty, int) or isinstance(qty, bool) or qty < 1:
            raise err("ERR_INVALID_REQUEST", "drug_items entry must have drug_id (str) and qty (int>=1).")
        out.append({"drug_id": drug_id, "qty": qty})
    return out


@bp.post("/pharma-platforms/<pid>/prescriptions")
@require_roles("Customer", "PrescriptionReviewer")
def upload_prescription(pid: str):
    platform = get_platform(pid)
    body = require_json(request.get_json(silent=True))
    customer_id = require_field(body, "customer_id", kind=str)
    if customer_id not in db.customers or db.customers[customer_id].get("platform_id") != pid:
        raise err("ERR_CUSTOMER_NOT_FOUND", f"Customer '{customer_id}' not found.")
    if g.user_role == "Customer" and g.user_id != customer_id:
        raise err("ERR_INSUFFICIENT_PERMISSIONS", "Customer can only upload for themselves.")
    prescriber_name = require_field(body, "prescriber_name", kind=str)
    prescriber_license = require_field(body, "prescriber_license_no", kind=str)
    image_url = require_field(body, "image_url", kind=str)
    issued_at = require_field(body, "issued_at", kind=str)
    try:
        parse_iso(issued_at)
    except Exception as exc:
        raise err("ERR_INVALID_REQUEST", f"Bad issued_at: {exc}")
    validity_days = require_pos_int(body, "validity_days", min_val=1)
    drug_items = _validate_drug_items(pid, body.get("drug_items"))
    row = {
        "platform_id": pid,
        "customer_id": customer_id,
        "prescriber_name": prescriber_name,
        "prescriber_license_no": prescriber_license,
        "image_url": image_url,
        "issued_at": issued_at,
        "validity_days": validity_days,
        "drug_items": drug_items,
        "reviewer_pharmacist_id": None,
        "archived_at": None,
        "status": "REVIEW_PENDING",  # auto-advance from UPLOADED on creation
    }
    stamp_create(row, platform)
    db.prescriptions[row["id"]] = row
    return success_object(serialize(row)), 201


@bp.get("/pharma-platforms/<pid>/prescriptions/<rx_id>")
@require_roles(
    "Customer",
    "PrescriptionReviewer",
    "PharmacistReReviewer",
    "RegulatoryGateway",
    "PlatformAdmin",
)
def get_prescription_route(pid: str, rx_id: str):
    _, rx = get_prescription(pid, rx_id)
    if g.user_role == "Customer" and g.user_id != rx.get("customer_id"):
        raise err("ERR_INSUFFICIENT_PERMISSIONS", "Customer can only view their own prescription.")
    return success_object(serialize(rx)), 200


def _denylist_has(platform_id: str, license_no: str) -> bool:
    for e in db.prescriber_denylist.values():
        if e.get("platform_id") == platform_id and e.get("prescriber_license_no") == license_no:
            return True
    return False


@bp.post("/pharma-platforms/<pid>/prescriptions/<rx_id>/approve")
@require_roles("PrescriptionReviewer")
def approve_prescription(pid: str, rx_id: str):
    platform, rx = get_prescription(pid, rx_id)
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        occ_check(body, rx)

    if rx.get("status") != "REVIEW_PENDING":
        raise err("ERR_PRESCRIPTION_NOT_IN_REVIEW", "Prescription not in REVIEW_PENDING.")

    # Acting pharmacist must be ACTIVE
    actor = db.pharmacists.get(g.user_id)
    if not actor or actor.get("platform_id") != pid:
        raise err("ERR_PHARMACIST_NOT_ACTIVE", "Acting pharmacist not found or not on platform.")
    if actor.get("qualification_status") != "ACTIVE":
        raise err("ERR_PHARMACIST_NOT_ACTIVE", "Acting pharmacist must be ACTIVE.")

    # Validity check
    issued_at = parse_iso(rx["issued_at"])
    clock = parse_iso(platform_clock(platform))
    # The validity cap depends on the maximum control_category among items.
    # Determine the cap by looking up each drug's category.
    cap = max((VALIDITY_DAYS_CAP.values()))  # generous default
    for item in rx["drug_items"]:
        d = db.drugs.get(item["drug_id"])
        if d:
            cap = min(cap, VALIDITY_DAYS_CAP.get(d.get("control_category") or "NONE", cap))
    effective_days = min(int(rx["validity_days"]), cap)
    if clock >= issued_at + _dt.timedelta(days=effective_days):
        raise err("ERR_PRESCRIPTION_EXPIRED", "Prescription expired.")

    # Denylist check
    if _denylist_has(pid, rx["prescriber_license_no"]):
        raise err("ERR_PRESCRIBER_NOT_QUALIFIED", "Prescriber is on the denylist.")

    # Drugs prescribable
    customer = db.customers.get(rx["customer_id"])
    if customer is None:
        raise err("ERR_CUSTOMER_NOT_FOUND", "Customer missing for prescription.")
    for item in rx["drug_items"]:
        d = db.drugs.get(item["drug_id"])
        if not d or d.get("platform_id") != pid:
            raise err("ERR_DRUG_NOT_PRESCRIBABLE", f"Drug '{item['drug_id']}' not found.")
        if d.get("status") != "ON_SHELF" or d.get("classification") != "PRESCRIPTION":
            raise err(
                "ERR_DRUG_NOT_PRESCRIBABLE",
                f"Drug '{d['id']}' is not ON_SHELF + PRESCRIPTION.",
            )

    # Contraindications
    flags = set(customer.get("special_population_flags") or [])
    for item in rx["drug_items"]:
        d = db.drugs.get(item["drug_id"])
        if d is None:
            continue
        if set(d.get("contraindications") or []) & flags:
            raise err(
                "ERR_CONTRAINDICATION_VIOLATION",
                f"Drug '{d['id']}' contraindications intersect customer flags.",
            )

    # All preconditions satisfied — transition.
    rx["status"] = "APPROVED"
    rx["reviewer_pharmacist_id"] = g.user_id
    stamp_update(rx, platform)
    actor_id, actor_role = current_actor()
    append_audit_log(
        platform=platform,
        subject_type="PRESCRIPTION",
        subject_id=rx["id"],
        action="PRESCRIPTION_APPROVED",
        actor_role=actor_role,
        actor_id=actor_id,
        payload={"prescription_id": rx["id"], "version": rx["version"]},
    )
    emit_external_event(
        platform=platform,
        channel="E_PRESCRIPTION_PLATFORM",
        event_type="prescription.approved",
        subject_type="PRESCRIPTION",
        subject_id=rx["id"],
        payload={"prescription_id": rx["id"], "version": rx["version"]},
        idempotency_key=f"prescription.approved:{rx['id']}:{rx['version']}",
    )
    return success_object(serialize(rx)), 200


@bp.post("/pharma-platforms/<pid>/prescriptions/<rx_id>/reject")
@require_roles("PrescriptionReviewer")
def reject_prescription(pid: str, rx_id: str):
    platform, rx = get_prescription(pid, rx_id)
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        occ_check(body, rx)
    if rx.get("status") != "REVIEW_PENDING":
        raise err("ERR_PRESCRIPTION_NOT_IN_REVIEW", "Prescription not in REVIEW_PENDING.")
    rx["status"] = "REJECTED"
    stamp_update(rx, platform)
    actor_id, actor_role = current_actor()
    append_audit_log(
        platform=platform,
        subject_type="PRESCRIPTION",
        subject_id=rx["id"],
        action="PRESCRIPTION_REJECTED",
        actor_role=actor_role,
        actor_id=actor_id,
        payload={"prescription_id": rx["id"], "version": rx["version"]},
    )
    return success_object(serialize(rx)), 200


@bp.post("/pharma-platforms/<pid>/prescriptions/<rx_id>/revoke")
@require_roles("PrescriptionReviewer", "PlatformAdmin")
def revoke_prescription(pid: str, rx_id: str):
    platform, rx = get_prescription(pid, rx_id)
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        occ_check(body, rx)
    if rx.get("status") != "APPROVED":
        raise err("ERR_PRESCRIPTION_NOT_IN_REVIEW", "Prescription not in APPROVED.")

    # Block if any referencing order is in {PHARMACIST_REVIEWING, APPROVED, DISPENSED, SHIPPED, DELIVERED}
    BLOCKING = {"PHARMACIST_REVIEWING", "APPROVED", "DISPENSED", "SHIPPED", "DELIVERED"}
    for o in db.orders.values():
        if (
            o.get("platform_id") == pid
            and o.get("prescription_id") == rx["id"]
            and o.get("dispensing_status") in BLOCKING
        ):
            raise err("ERR_PRESCRIPTION_IN_USE", "Prescription is in use by an active order.")

    rx["status"] = "REVOKED"
    stamp_update(rx, platform)
    actor_id, actor_role = current_actor()
    append_audit_log(
        platform=platform,
        subject_type="PRESCRIPTION",
        subject_id=rx["id"],
        action="PRESCRIPTION_REVOKED",
        actor_role=actor_role,
        actor_id=actor_id,
        payload={"prescription_id": rx["id"], "version": rx["version"]},
    )
    emit_external_event(
        platform=platform,
        channel="E_PRESCRIPTION_PLATFORM",
        event_type="prescription.revoked",
        subject_type="PRESCRIPTION",
        subject_id=rx["id"],
        payload={"prescription_id": rx["id"], "version": rx["version"]},
        idempotency_key=f"prescription.revoked:{rx['id']}:{rx['version']}",
    )
    # Cascade: PENDING_REVIEW orders referencing this prescription → CANCELLED + refund cascade.
    for o in list(db.orders.values()):
        if (
            o.get("platform_id") == pid
            and o.get("prescription_id") == rx["id"]
            and o.get("dispensing_status") == "PENDING_REVIEW"
        ):
            o["dispensing_status"] = "CANCELLED"
            stamp_update(o, platform)
            refund_if_paid(platform, o)
    return success_object(serialize(rx)), 200
