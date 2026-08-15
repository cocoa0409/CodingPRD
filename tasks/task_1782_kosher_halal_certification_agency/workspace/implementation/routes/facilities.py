"""Facility endpoints (PRD §3.2)."""
from flask import Blueprint

from db import new_common, store, touch
from errors import err
from middleware import get_or_404, require_client_scope, require_roles
from response import Paginator, created, ok
from services.domain import bubble_client_on_cert_loss, suspend_facility_cascade
from validation import body_json, opt_enum, req_str

bp = Blueprint("facilities", __name__)

FACILITY_ROLES = ("OWNED", "CO_PACKER")
OPEN_MAJOR_FINDING_STATUSES = ("OPEN", "REMEDIATION_SUBMITTED", "REOPENED", "ESCALATED")


def _open_major_findings_exist(facility_id):
    return any(f for f in store.findings.values()
               if f["facility_id"] == facility_id
               and f["severity"] in ("MAJOR", "CRITICAL")
               and f["status"] in OPEN_MAJOR_FINDING_STATUSES)


@bp.post("/facilities")
def create_facility():
    data = body_json()
    client_id = req_str(data, "client_id")
    name = req_str(data, "name")
    address = req_str(data, "address")
    facility_role = opt_enum(data, "facility_role", FACILITY_ROLES, default="OWNED")
    require_roles("ClientContact", "AccountManager")
    require_client_scope(client_id)
    get_or_404(store.clients, client_id, "Client")
    facility = new_common({
        "client_id": client_id,
        "name": name,
        "address": address,
        "facility_role": facility_role,
        "status": "PENDING_REVIEW",
    })
    store.facilities[facility["id"]] = facility
    return created(facility)


@bp.get("/facilities")
def list_facilities():
    p = Paginator()
    rows = list(store.facilities.values())
    rows = p.filter(rows, "client_id")
    rows = p.filter(rows, "status")
    rows = p.filter(rows, "facility_role")
    return ok(p(rows), rtype="array", pagination=p)


@bp.get("/facilities/<facility_id>")
def get_facility(facility_id):
    return ok(get_or_404(store.facilities, facility_id, "Facility"))


@bp.post("/facilities/<facility_id>/approve")
def approve_facility(facility_id):
    require_roles("CertificationReviewer")
    facility = get_or_404(store.facilities, facility_id, "Facility")
    if facility["status"] != "PENDING_REVIEW":
        err("ERR_FACILITY_INVALID_STATE",
            "approve requires facility status PENDING_REVIEW")
    if not any(v for v in store.visits.values()
               if v["facility_id"] == facility_id
               and v["visit_type"] == "INITIAL" and v["status"] == "COMPLETED"):
        err("ERR_INITIAL_VISIT_REQUIRED",
            "Facility approval requires a COMPLETED INITIAL supervision visit")
    if _open_major_findings_exist(facility_id):
        err("ERR_OPEN_MAJOR_FINDINGS",
            "Facility has MAJOR/CRITICAL findings in an open status")
    for line in store.equipment_lines.values():
        if line["facility_id"] != facility_id:
            continue
        if (line["dedication_status"] == "UNASSESSED"
                or line["kosherization_state"] not in ("NONE", "VALID")):
            err("ERR_EQUIPMENT_UNASSESSED",
                "Every line must be assessed and have kosherization NONE or VALID")
    facility["status"] = "APPROVED"
    touch(facility)
    return ok(facility)


@bp.post("/facilities/<facility_id>/suspend")
def suspend_facility(facility_id):
    require_roles("CertificationReviewer")
    facility = get_or_404(store.facilities, facility_id, "Facility")
    if facility["status"] != "APPROVED":
        err("ERR_FACILITY_INVALID_STATE",
            "suspend requires facility status APPROVED")
    suspend_facility_cascade(facility)
    return ok(facility)


@bp.post("/facilities/<facility_id>/reinstate")
def reinstate_facility(facility_id):
    require_roles("CertificationReviewer")
    facility = get_or_404(store.facilities, facility_id, "Facility")
    if facility["status"] != "SUSPENDED":
        err("ERR_FACILITY_INVALID_STATE",
            "reinstate requires facility status SUSPENDED")
    if _open_major_findings_exist(facility_id):
        err("ERR_OPEN_MAJOR_FINDINGS",
            "Facility has MAJOR/CRITICAL findings in an open status")
    if any(line for line in store.equipment_lines.values()
           if line["facility_id"] == facility_id
           and line["kosherization_state"] == "COMPROMISED"):
        err("ERR_EQUIPMENT_UNASSESSED",
            "Facility has a line with kosherization COMPROMISED")
    facility["status"] = "APPROVED"
    touch(facility)
    return ok(facility)


@bp.post("/facilities/<facility_id>/decommission")
def decommission_facility(facility_id):
    require_roles("ClientContact")
    facility = get_or_404(store.facilities, facility_id, "Facility")
    require_client_scope(facility["client_id"])
    if facility["status"] not in ("PENDING_REVIEW", "APPROVED", "SUSPENDED"):
        err("ERR_FACILITY_INVALID_STATE",
            "decommission requires facility status PENDING_REVIEW, APPROVED or SUSPENDED")
    facility["status"] = "DECOMMISSIONED"
    touch(facility)
    # Scope shrink on every live certificate; an ACTIVE certificate whose scope
    # becomes empty suspends (DRAFT keeps its empty scope; SUSPENDED stays).
    affected_clients = set()
    for cert in store.certificates.values():
        if facility_id not in cert["facility_ids"]:
            continue
        if cert["status"] not in ("DRAFT", "ACTIVE", "SUSPENDED"):
            continue
        cert["facility_ids"] = [fid for fid in cert["facility_ids"] if fid != facility_id]
        if cert["status"] == "ACTIVE" and not cert["facility_ids"]:
            cert["status"] = "SUSPENDED"
            affected_clients.add(cert["client_id"])
        touch(cert)
    for cid in affected_clients:
        client = store.clients.get(cid)
        if client is not None:
            bubble_client_on_cert_loss(client)
    return ok(facility)
