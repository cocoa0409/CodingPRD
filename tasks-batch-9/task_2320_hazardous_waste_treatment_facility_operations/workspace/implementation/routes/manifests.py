"""Manifests: creation, the receipt fork, discrepancy resolution, certification."""

from decimal import Decimal

from flask import Blueprint

import schema
from db import db, insert, now
from errors import fail
from middleware import endpoint
from response import created, ok
from routes.common import (by_created_at, check_generator_scope, check_assurance,
                           check_generator_active, check_permit_active, check_profile_acceptable,
                           load, reference, respond_list, scope_filter_generator)
from services import calc, cascade, derive
from services.tracking import touch
from util import D, add_days, new_id, qd

bp = Blueprint("manifests", __name__)

READERS = ["PlatformAdmin", "ComplianceManager", "ReceivingClerk", "RegulatoryInspector", "Generator"]
LINE_READERS = ["PlatformAdmin", "ComplianceManager", "ReceivingClerk", "TreatmentOperator",
                "RegulatoryInspector", "Generator"]

CREATE_SPEC = {
    "generator_id": {"type": "string", "required": True},
    "facility_id": {"type": "string", "required": True},
    "manifest_tracking_number": {"type": "string", "required": True, "non_empty": True},
    "transporter_epa_id": {"type": "string", "required": True, "non_empty": True},
    "shipped_on": {"type": "date", "required": True},
    "lines": {"type": "array", "required": True, "non_empty": True,
              "element_fields": {
                  "waste_profile_id": {"type": "string", "required": True},
                  "declared_quantity_kg": {"type": "number", "required": True, "ge": 0},
                  "declared_container_count": {"type": "int", "required": True, "ge": 0},
                  "is_bulk": {"type": "bool", "required": True},
              }},
}

RECEIVE_SPEC = {
    "received_lines": {"type": "array", "required": True,
                       "element_fields": {
                           "line_number": {"type": "int", "required": True, "ge": 1},
                           "received_quantity_kg": {"type": "number", "required": True, "ge": 0},
                           "received_container_count": {"type": "int", "required": True, "ge": 0},
                       }},
}

RESOLUTION_SPEC = {
    "resolution_type": {"type": "string", "required": True,
                        "enum": ["ACCEPT_ADJUSTED", "PARTIAL_REJECT", "REJECT_RETURN"]},
    "discrepancy_report_filed": {"type": "bool"},
    "adjusted_lines": {"type": "array",
                       "element_fields": {
                           "line_number": {"type": "int", "required": True, "ge": 1},
                           "accepted_quantity_kg": {"type": "number", "required": True, "ge": 0},
                       }},
    "rejected_line_numbers": {"type": "array", "items": {"type": "int", "ge": 1}},
}


def _lines_by_number(manifest_id):
    return sorted(derive.lines_of(manifest_id), key=lambda ln: ln["line_number"])


def _charge(m, variant):
    """calculations.acceptance_charge -- per-line rounding before summation."""
    included = ("RECEIVED",) if variant == "PROVISIONAL" else ("RECEIVED", "ACCEPTED", "ADJUSTED")
    quantity_field = "received_quantity_kg" if variant == "PROVISIONAL" else "accepted_quantity_kg"
    total = 0
    per_line = {}
    for ln in _lines_by_number(m["id"]):
        if ln["line_status"] not in included:
            per_line[ln["id"]] = 0
            continue
        p = derive.profile(ln["waste_profile_id"]) if ln["waste_profile_id"] else None
        cents = calc.line_charge_cents(ln[quantity_field] or 0, ln["received_container_count"] or 0, p)
        per_line[ln["id"]] = cents
        total += cents
    return total, per_line


@bp.post("/tsdf/manifests")
@endpoint(roles=["Generator", "ReceivingClerk"], mutating=True)
def create_manifest():
    raw = schema.raw_body()
    if isinstance(raw.get("generator_id"), str):
        check_generator_scope(raw["generator_id"])
    body = schema.validate(raw, CREATE_SPEC)

    gen = reference("generators", body["generator_id"])
    fac = reference("facilities", body["facility_id"])
    profiles = [reference("profiles", element["waste_profile_id"]) for element in body["lines"]]

    # Priority 8: every line's profile must belong to the designated facility.
    for p in profiles:
        if p["facility_id"] != fac["id"]:
            fail("ERR_FACILITY_SCOPE_MISMATCH")
    # Priority 12, then 14 across all lines, then 15 across all lines.
    check_generator_active(gen)
    for p in profiles:
        if derive.profile_status(p) not in ("APPROVED", "EXPIRED"):
            fail("ERR_PROFILE_NOT_APPROVED")
    for p in profiles:
        check_profile_acceptable(p)
    # Priority 30.
    if any(m["manifest_tracking_number"] == body["manifest_tracking_number"] for m in db.manifests.values()):
        fail("ERR_DUPLICATE_MANIFEST_NUMBER")

    stamp = now()
    m = {
        "id": new_id(),
        "generator_id": gen["id"],
        "facility_id": fac["id"],
        "manifest_tracking_number": body["manifest_tracking_number"],
        "transporter_epa_id": body["transporter_epa_id"],
        "shipped_on": body["shipped_on"],
        "status": "EN_ROUTE",
        "arrived_at": None,
        "discrepancy_type": "NONE",
        "discrepancy_report_due_at": None,
        "discrepancy_report_filed": False,
        "discrepancy_resolved_at": None,
        "resolution_type": "NONE",
        "provisional_charge_cents": 0,
        "final_charge_cents": None,
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
    }
    insert("manifests", m)
    for index, element in enumerate(body["lines"], start=1):
        insert("lines", {
            "id": new_id(),
            "manifest_id": m["id"],
            "waste_profile_id": element["waste_profile_id"],
            "line_number": index,
            "declared_quantity_kg": element["declared_quantity_kg"],
            "declared_container_count": element["declared_container_count"],
            "is_bulk": element["is_bulk"],
            "received_quantity_kg": 0,
            "received_container_count": 0,
            "accepted_quantity_kg": 0,
            "returned_quantity_kg": 0,
            "line_status": "DECLARED",
            "variance_pct": None,
            "significance": "NONE",
            "provisional_line_charge_cents": 0,
            "final_line_charge_cents": None,
            "created_at": stamp,
            "updated_at": stamp,
            "version": 1,
        })
    return created(derive.project_manifest(m))


@bp.get("/tsdf/manifests/<mid>")
@endpoint(roles=READERS)
def get_manifest(mid):
    m = load("manifests", mid)
    check_generator_scope(m["generator_id"])
    return ok(derive.project_manifest(m))


@bp.get("/tsdf/manifests")
@endpoint(roles=READERS)
def list_manifests():
    filters, limit, offset = schema.listing(
        filters=["generator_id", "facility_id", "status", "discrepancy_type"],
        enums={"status": calc.MANIFEST_STATUSES, "discrepancy_type": calc.DISCREPANCY_TYPES})
    generator_id = scope_filter_generator(filters)
    rows = by_created_at(list(db.manifests.values()))
    if generator_id is not None:
        rows = [m for m in rows if m["generator_id"] == generator_id]
    for key in ("facility_id", "status", "discrepancy_type"):
        if key in filters:
            rows = [m for m in rows if m[key] == filters[key]]
    return respond_list(rows, derive.project_manifest, limit, offset)


@bp.get("/tsdf/manifests/<mid>/lines")
@endpoint(roles=LINE_READERS)
def list_manifest_lines(mid):
    filters, limit, offset = schema.listing(
        filters=["line_status"], enums={"line_status": calc.LINE_STATUSES})
    m = load("manifests", mid)
    check_generator_scope(m["generator_id"])
    # The documented exception to created_at ordering: lines always come back in
    # line_number ascending order.
    rows = _lines_by_number(mid)
    if "line_status" in filters:
        rows = [ln for ln in rows if ln["line_status"] == filters["line_status"]]
    return respond_list(rows, derive.project_line, limit, offset)


@bp.post("/tsdf/manifests/<mid>/receive")
@endpoint(roles=["ReceivingClerk"], mutating=True)
def receive_manifest(mid):
    body = schema.body(RECEIVE_SPEC)
    m = load("manifests", mid)

    if m["status"] != "EN_ROUTE":
        fail("ERR_INVALID_STATE", "Only an en-route manifest may be received")

    f = derive.facility(m["facility_id"])
    if f is None:
        fail("ERR_FACILITY_NOT_FOUND")
    check_permit_active(f)

    declared = {ln["line_number"]: ln for ln in _lines_by_number(mid)}
    reported = {}
    for element in body["received_lines"]:
        reported[element["line_number"]] = element

    # Priority 16: every received line's profile must still be APPROVED.
    for number in sorted(reported):
        ln = declared.get(number)
        if ln is None or not ln["waste_profile_id"]:
            continue
        p = derive.profile(ln["waste_profile_id"])
        if p is None or derive.profile_status(p) != "APPROVED":
            fail("ERR_ACCEPTANCE_CRITERIA_FAILED")

    check_assurance(f)

    stamp = now()
    m["arrived_at"] = stamp

    for number in sorted(reported):
        element = reported[number]
        ln = declared.get(number)
        if ln is None:
            continue
        ln["received_quantity_kg"] = element["received_quantity_kg"]
        ln["received_container_count"] = element["received_container_count"]
        ln["accepted_quantity_kg"] = element["received_quantity_kg"]
        ln["returned_quantity_kg"] = qd(Decimal(0), 3)
        ln["line_status"] = "RECEIVED"

    # An undocumented receipt is appended as a fresh line beyond the declared set.
    next_number = max(declared) + 1 if declared else 1
    for number in sorted(reported):
        if number in declared:
            continue
        element = reported[number]
        row = {
            "id": new_id(),
            "manifest_id": mid,
            "waste_profile_id": None,
            "line_number": next_number,
            "declared_quantity_kg": qd(Decimal(0), 3),
            "declared_container_count": 0,
            "is_bulk": False,
            "received_quantity_kg": element["received_quantity_kg"],
            "received_container_count": element["received_container_count"],
            "accepted_quantity_kg": element["received_quantity_kg"],
            "returned_quantity_kg": qd(Decimal(0), 3),
            "line_status": "RECEIVED",
            "variance_pct": None,
            "significance": "UNDOCUMENTED",
            "provisional_line_charge_cents": 0,
            "final_line_charge_cents": None,
            "_undocumented": True,
            "created_at": stamp,
            "updated_at": stamp,
            "version": 1,
        }
        insert("lines", row)
        next_number += 1

    # Classification, in line_number ascending order.
    for ln in _lines_by_number(mid):
        if ln.get("_undocumented"):
            ln["variance_pct"] = None
            ln["significance"] = "UNDOCUMENTED"
            continue
        ln["variance_pct"] = calc.variance_pct(ln["declared_quantity_kg"], ln["received_quantity_kg"])
        ln["significance"] = calc.line_significance(ln, ln["variance_pct"])

    discrepancy = calc.dominant_discrepancy([ln["significance"] for ln in _lines_by_number(mid)])
    m["discrepancy_type"] = discrepancy
    if discrepancy == "NONE":
        m["status"] = "VERIFIED"
    else:
        m["status"] = "DISCREPANT"
        m["discrepancy_report_due_at"] = add_days(stamp, calc.DISCREPANCY_REPORT_DAYS)

    total, per_line = _charge(m, "PROVISIONAL")
    for ln in _lines_by_number(mid):
        ln["provisional_line_charge_cents"] = per_line.get(ln["id"], 0)
    m["provisional_charge_cents"] = total

    gen = derive.generator(m["generator_id"])
    if gen is not None:
        gen["open_charge_cents"] += total

    touch("manifests", m)
    return ok(derive.project_manifest(m))


@bp.post("/tsdf/manifests/<mid>/discrepancy-resolution")
@endpoint(roles=["ComplianceManager"], mutating=True)
def resolve_discrepancy(mid):
    body = schema.body(RESOLUTION_SPEC)
    resolution = body["resolution_type"]
    if resolution in ("ACCEPT_ADJUSTED", "PARTIAL_REJECT") and body["discrepancy_report_filed"] is not True:
        fail("ERR_INVALID_REQUEST", "discrepancy_report_filed must be true for this resolution")

    m = load("manifests", mid)
    lines = _lines_by_number(mid)
    by_number = {ln["line_number"]: ln for ln in lines}

    adjusted = {}
    for element in (body["adjusted_lines"] or []):
        ln = by_number.get(element["line_number"])
        if ln is None:
            fail("ERR_INVALID_REQUEST", "adjusted_lines names a line_number that is not on this manifest")
        if D(element["accepted_quantity_kg"]) > D(ln["received_quantity_kg"] or 0):
            fail("ERR_INVALID_REQUEST", "accepted_quantity_kg may not exceed received_quantity_kg")
        adjusted[element["line_number"]] = element["accepted_quantity_kg"]
    rejected = set()
    for number in (body["rejected_line_numbers"] or []):
        if number not in by_number:
            fail("ERR_INVALID_REQUEST", "rejected_line_numbers names a line_number that is not on this manifest")
        rejected.add(number)

    if m["status"] == "DISCREPANT":
        if now() > m["discrepancy_report_due_at"]:
            fail("ERR_DISCREPANCY_REPORT_OVERDUE")
    elif m["status"] == "VERIFIED":
        if resolution != "REJECT_RETURN":
            fail("ERR_INVALID_STATE", "A verified manifest can only be rejected and returned")
        for ln in lines:
            for c in derive.containers_of_line(ln["id"]):
                if c["custody_state"] in ("STAGED", "EMPTIED"):
                    fail("ERR_INVALID_STATE", "A container of this manifest has already left storage")
    else:
        fail("ERR_INVALID_STATE", "The manifest has no open discrepancy to resolve")

    if resolution == "REJECT_RETURN":
        if body["discrepancy_report_filed"] is True:
            m["discrepancy_report_filed"] = True
        cascade.shipment_rejection_cascade(m)
        touch("manifests", m)
        return ok(derive.project_manifest(m))

    if resolution == "ACCEPT_ADJUSTED":
        for ln in lines:
            if ln["line_status"] != "RECEIVED":
                continue
            accepted = adjusted.get(ln["line_number"], ln["received_quantity_kg"])
            ln["accepted_quantity_kg"] = qd(D(accepted), 3)
            ln["returned_quantity_kg"] = qd(D(ln["received_quantity_kg"] or 0) - D(accepted), 3)
            ln["line_status"] = "ACCEPTED"
    else:
        for ln in lines:
            if ln["line_number"] in rejected:
                ln["accepted_quantity_kg"] = qd(Decimal(0), 3)
                ln["returned_quantity_kg"] = qd(D(ln["received_quantity_kg"] or 0), 3)
                ln["line_status"] = "RETURNED"
            elif ln["line_status"] == "RECEIVED":
                ln["accepted_quantity_kg"] = qd(D(ln["received_quantity_kg"] or 0), 3)
                ln["returned_quantity_kg"] = qd(Decimal(0), 3)
                ln["line_status"] = "ADJUSTED"

    m["status"] = "VERIFIED"
    m["resolution_type"] = resolution
    m["discrepancy_report_filed"] = True
    m["discrepancy_resolved_at"] = now()
    touch("manifests", m)
    return ok(derive.project_manifest(m))


@bp.post("/tsdf/manifests/<mid>/certify")
@endpoint(roles=["ReceivingClerk"], mutating=True)
def certify_manifest(mid):
    schema.body({"certifier_note": {"type": "string"}})
    m = load("manifests", mid)

    if m["status"] != "VERIFIED":
        fail("ERR_INVALID_STATE", "Only a verified manifest may be certified")
    if m["discrepancy_type"] != "NONE" and not m["discrepancy_report_filed"]:
        fail("ERR_DISCREPANCY_REPORT_OVERDUE")

    total, per_line = _charge(m, "FINAL")
    for ln in _lines_by_number(mid):
        ln["final_line_charge_cents"] = per_line.get(ln["id"], 0)
        if ln["line_status"] in ("RECEIVED", "ADJUSTED"):
            ln["line_status"] = "ACCEPTED"

    provisional = int(m["provisional_charge_cents"] or 0)
    m["final_charge_cents"] = total
    m["status"] = "CERTIFIED"

    gen = derive.generator(m["generator_id"])
    if gen is not None:
        gen["open_charge_cents"] -= provisional
        gen["settled_charge_cents"] += total
        gen["charge_adjustment_cents"] += total - provisional

    touch("manifests", m)
    return ok(derive.project_manifest(m))
