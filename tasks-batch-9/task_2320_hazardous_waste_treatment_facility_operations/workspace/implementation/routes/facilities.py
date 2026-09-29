"""Facility, permit lifecycle, assurance summary and the biennial report."""

from decimal import Decimal

from flask import Blueprint, g

import schema
from db import db, insert, now
from errors import fail
from middleware import endpoint
from response import created, ok
from routes.common import check_generator_scope, load, respond_list, by_created_at
from services import calc, cascade, derive
from services.tracking import touch
from util import D, iso, new_id, q, qd, year_of

bp = Blueprint("facilities", __name__)

READERS = ["PlatformAdmin", "ComplianceManager", "ReceivingClerk", "WasteApprovalChemist",
           "TreatmentOperator", "RegulatoryInspector"]
SUMMARY_READERS = ["PlatformAdmin", "ComplianceManager", "RegulatoryInspector"]

CREATE_SPEC = {
    "name": {"type": "string", "required": True, "min_len": 1, "max_len": 120},
    "epa_id": {"type": "string", "required": True, "non_empty": True},
    "permit_number": {"type": "string", "required": True, "non_empty": True},
    "permit_expires_at": {"type": "datetime", "required": True},
    "permitted_methods": {"type": "array", "required": True, "non_empty": True,
                          "items": {"type": "string", "enum": calc.TREATMENT_METHODS}},
    "max_concurrent_treatment_batches": {"type": "int", "required": True, "ge": 1},
    "post_closure_cost_cents": {"type": "int", "required": True, "ge": 0},
}


@bp.post("/tsdf/facilities")
@endpoint(roles=["PlatformAdmin"], mutating=True)
def create_facility():
    body = schema.body(CREATE_SPEC)
    if any(f["epa_id"] == body["epa_id"] for f in db.facilities.values()):
        fail("ERR_DUPLICATE_MANIFEST_NUMBER", "A facility with this epa_id already exists")
    stamp = now()
    row = {
        "id": new_id(),
        "name": body["name"],
        "epa_id": body["epa_id"],
        "permit_number": body["permit_number"],
        "permit_expires_at": body["permit_expires_at"],
        "permitted_methods": body["permitted_methods"],
        "max_concurrent_treatment_batches": body["max_concurrent_treatment_batches"],
        "post_closure_cost_cents": body["post_closure_cost_cents"],
        "permit_status": "ACTIVE",
        "renewal_requested_at": None,
        "requested_permit_expires_at": None,
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
    }
    insert("facilities", row)
    return created(derive.project_facility(row))


@bp.get("/tsdf/facilities/<fid>")
@endpoint(roles=READERS)
def get_facility(fid):
    return ok(derive.project_facility(load("facilities", fid)))


@bp.get("/tsdf/facilities")
@endpoint(roles=READERS)
def list_facilities():
    filters, limit, offset = schema.listing(
        filters=["permit_status", "epa_id"],
        enums={"permit_status": calc.PERMIT_STATUSES})
    rows = by_created_at(list(db.facilities.values()))
    if "permit_status" in filters:
        rows = [f for f in rows if derive.permit_status(f) == filters["permit_status"]]
    if "epa_id" in filters:
        rows = [f for f in rows if f["epa_id"] == filters["epa_id"]]
    return respond_list(rows, derive.project_facility, limit, offset)


@bp.post("/tsdf/facilities/<fid>/permit-renewal-request")
@endpoint(roles=["ComplianceManager"], mutating=True)
def permit_renewal_request(fid):
    body = schema.body({"requested_permit_expires_at": {"type": "datetime", "required": True}})
    f = load("facilities", fid)
    status = derive.permit_status(f)
    if status not in ("ACTIVE", "EXPIRED"):
        fail("ERR_INVALID_STATE", "Permit is not in a renewable state")
    # priority 26 then priority 35
    for finding in derive.findings_of_facility(fid):
        if finding["finding_class"] == "SNC" and derive.finding_overdue(finding):
            fail("ERR_CORRECTIVE_ACTION_OVERDUE")
    if derive.facility_shortfall(f) != 0:
        fail("ERR_FINANCIAL_ASSURANCE_SHORTFALL")

    f["permit_status"] = "RENEWAL_PENDING"
    f["renewal_requested_at"] = now()
    f["requested_permit_expires_at"] = body["requested_permit_expires_at"]
    touch("facilities", f)
    return ok(derive.project_facility(f))


@bp.post("/tsdf/facilities/<fid>/permit-decision")
@endpoint(roles=["RegulatoryInspector"], mutating=True)
def permit_decision(fid):
    body = schema.body({
        "decision": {"type": "string", "required": True, "enum": ["GRANT", "DENY", "TERMINATE"]},
        "new_permit_expires_at": {"type": "datetime"},
        "reason_code": {"type": "string"},
    })
    decision = body["decision"]
    if decision == "GRANT":
        if body["new_permit_expires_at"] is None:
            fail("ERR_INVALID_REQUEST", "new_permit_expires_at is required to grant a renewal")
        if body["new_permit_expires_at"] <= now():
            fail("ERR_INVALID_REQUEST", "new_permit_expires_at must be in the future")

    f = load("facilities", fid)
    status = derive.permit_status(f)

    if decision == "GRANT":
        if status != "RENEWAL_PENDING":
            fail("ERR_INVALID_STATE", "No renewal application is pending")
        f["permit_expires_at"] = body["new_permit_expires_at"]
        f["permit_status"] = "ACTIVE"
        f["renewal_requested_at"] = None
        f["requested_permit_expires_at"] = None
    elif decision == "DENY":
        if status != "RENEWAL_PENDING":
            fail("ERR_INVALID_STATE", "No renewal application is pending")
        f["permit_status"] = "EXPIRED"
        f["requested_permit_expires_at"] = None
    else:
        if status != "EXPIRED":
            fail("ERR_INVALID_STATE", "Only an expired permit may be terminated")
        f["permit_status"] = "TERMINATED"
        cascade.permit_termination_cascade(f)

    touch("facilities", f)
    return ok(derive.project_facility(f))


@bp.get("/tsdf/facilities/<fid>/financial-assurance-summary")
@endpoint(roles=SUMMARY_READERS)
def assurance_summary(fid):
    return ok(derive.project_facility(load("facilities", fid)))


@bp.get("/tsdf/facilities/<fid>/biennial-report")
@endpoint(roles=SUMMARY_READERS)
def biennial_report(fid):
    schema.listing(filters=[], extra=["report_year"])
    report_year = schema.required_int_query("report_year")
    f = load("facilities", fid)

    in_scope = [m for m in derive.manifests_of_facility(fid)
                if m["arrived_at"] is not None and year_of(m["arrived_at"]) == report_year]
    in_scope.sort(key=lambda m: (m["arrived_at"], m["created_at"], m["_seq"]))

    received = Decimal(0)
    accepted = Decimal(0)
    returned = Decimal(0)
    code_totals = {}
    for m in in_scope:
        for ln in derive.lines_of(m["id"]):
            received += D(ln["received_quantity_kg"] or 0)
            accepted += D(ln["accepted_quantity_kg"] or 0)
            returned += D(ln["returned_quantity_kg"] or 0)
            p = derive.profile(ln["waste_profile_id"]) if ln["waste_profile_id"] else None
            if p is not None:
                for code in p["waste_codes"]:
                    code_totals[code] = code_totals.get(code, Decimal(0)) + D(ln["received_quantity_kg"] or 0)

    residue = Decimal(0)
    for b in derive.batches_of_facility(fid):
        if b["status"] in calc.RESIDUE_BATCH_STATUSES and year_of(b["window_start"]) == report_year:
            residue += D(b["residue_mass_kg"] or 0)

    return ok({
        "facility_id": f["id"],
        "report_year": report_year,
        "manifest_count": len(in_scope),
        "generator_count": len({m["generator_id"] for m in in_scope}),
        "total_received_kg": q(qd(received, 3), 3),
        "total_accepted_kg": q(qd(accepted, 3), 3),
        "total_returned_kg": q(qd(returned, 3), 3),
        "total_residue_kg": q(qd(residue, 3), 3),
        "waste_code_totals": {code: q(qd(code_totals[code], 3), 3) for code in sorted(code_totals)},
    })
