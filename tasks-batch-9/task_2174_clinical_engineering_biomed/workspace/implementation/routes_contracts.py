"""Vendor service contracts (PRD 3.5) and medical-device security findings (PRD 3.8)."""
from __future__ import annotations

from flask import Blueprint

import calc
import services
import util
import validate as v
from auth import authenticate, own_service_contract
from common import respond, respond_list
from errors import ApiError, bad_request
from store import store

bp = Blueprint("contracts", __name__)

CONTRACT_STATUSES = ("ACTIVE", "EXHAUSTED")
SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
FINDING_STATUSES = ("OPEN", "REMEDIATION_SCHEDULED", "MITIGATED", "ACCEPTED_RISK")
RESOLUTIONS = ("MITIGATED", "ACCEPTED_RISK")


@bp.post("/service-contracts")
def create_service_contract():
    authenticate(["CEManager"])
    payload = v.body(required=("vendor_id", "device_model_id", "coverage_start",
                               "coverage_end", "annual_premium_cents",
                               "deductible_cents", "covered_event_cap"))
    vendor_id = v.req_id(payload, "vendor_id")
    model_id = v.req_id(payload, "device_model_id")
    coverage_start, start_dt = v.req_dt(payload, "coverage_start")
    coverage_end, end_dt = v.req_dt(payload, "coverage_end")
    premium = v.req_int(payload, "annual_premium_cents", minimum=0)
    deductible = v.req_int(payload, "deductible_cents", minimum=0)
    cap = v.req_int(payload, "covered_event_cap", minimum=1)
    if not end_dt > start_dt:
        raise bad_request("coverage_end must be strictly after coverage_start.")

    store.require("Vendor", vendor_id)
    store.require("DeviceModel", model_id)

    # CLOSED intervals: two contracts that merely touch DO overlap.
    for other in store.all("ServiceContract"):
        if other["vendor_id"] != vendor_id or other["device_model_id"] != model_id:
            continue
        if other["status"] != "ACTIVE":
            continue
        other_start = util.parse_dt(other["coverage_start"])
        other_end = util.parse_dt(other["coverage_end"])
        if start_dt <= other_end and other_start <= end_dt:
            raise ApiError("ERR_CONTRACT_COVERAGE_OVERLAP",
                           "An active contract already covers an intersecting interval.")

    record = store.new_record("ServiceContract", {
        "vendor_id": vendor_id,
        "device_model_id": model_id,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "annual_premium_cents": premium,
        "deductible_cents": deductible,
        "covered_event_cap": cap,
        "covered_events_used": 0,
        "status": "ACTIVE",
    })
    return respond(record, 201)


@bp.get("/service-contracts/<cid>")
def read_service_contract(cid):
    authenticate(["CEManager", "VendorRep"])
    own_service_contract(store.get("ServiceContract", cid))
    return respond(store.require("ServiceContract", cid))


@bp.get("/service-contracts")
def list_service_contracts():
    authenticate(["CEManager", "VendorRep"])
    limit, offset = v.pagination()
    vendor_id = v.query_str("vendor_id")
    model_id = v.query_str("device_model_id")
    status = v.query_enum("status", CONTRACT_STATUSES)
    records = store.ordered([
        c for c in store.all("ServiceContract")
        if (vendor_id is None or c["vendor_id"] == vendor_id)
        and (model_id is None or c["device_model_id"] == model_id)
        and (status is None or c["status"] == status)
    ])
    return respond_list(records, limit, offset)


# ---------------------------------------------------------- SecurityFinding
@bp.post("/security-findings")
def create_security_finding():
    authenticate(["SecurityOfficer"])
    payload = v.body(required=("device_id", "severity", "advisory_reference"),
                     optional=("requires_downtime",))
    device_id = v.req_id(payload, "device_id")
    severity = v.req_enum(payload, "severity", SEVERITIES)
    advisory = v.req_str(payload, "advisory_reference")
    requires_downtime = v.opt_bool(payload, "requires_downtime", False)

    device = store.require("Device", device_id)

    discovered_at = store.now()
    due = util.add_days(discovered_at, calc.REMEDIATION_SLA_DAYS[severity])
    record = store.new_record("SecurityFinding", {
        "device_id": device_id,
        "severity": severity,
        "advisory_reference": advisory,
        "requires_downtime": requires_downtime,
        "discovered_at": util.format_dt(discovered_at),
        "remediation_due_at": util.format_dt(due),
        "status": "OPEN",
        "resolution_note": None,
        "resolved_at": None,
    })

    if severity == "CRITICAL":
        device["security_state"] = "QUARANTINED"
        services.quarantine_cascade(device)
        store.touch(device)
    elif severity == "HIGH":
        if device["security_state"] in ("UNASSESSED", "ASSESSED_OK"):
            device["security_state"] = "VULNERABLE"
            store.touch(device)
    return respond(record, 201)


@bp.get("/security-findings/<sid>")
def read_security_finding(sid):
    authenticate(["SecurityOfficer", "CEManager", "BiomedTech"])
    return respond(store.require("SecurityFinding", sid))


@bp.get("/security-findings")
def list_security_findings():
    authenticate(["SecurityOfficer", "CEManager", "BiomedTech"])
    limit, offset = v.pagination()
    device_id = v.query_str("device_id")
    status = v.query_enum("status", FINDING_STATUSES)
    severity = v.query_enum("severity", SEVERITIES)
    records = store.ordered([
        f for f in store.all("SecurityFinding")
        if (device_id is None or f["device_id"] == device_id)
        and (status is None or f["status"] == status)
        and (severity is None or f["severity"] == severity)
    ])
    return respond_list(records, limit, offset)


@bp.post("/security-findings/<sid>/resolve")
def resolve_security_finding(sid):
    authenticate(["SecurityOfficer", "CEManager"])
    finding = store.require("SecurityFinding", sid)
    payload = v.body(required=("resolution",), optional=("note",))
    resolution = v.req_enum(payload, "resolution", RESOLUTIONS)
    note = v.opt_str(payload, "note")
    if finding["status"] not in ("OPEN", "REMEDIATION_SCHEDULED"):
        raise ApiError("ERR_INVALID_SECURITY_STATE",
                       "A %s finding is terminal." % finding["status"])

    if resolution == "MITIGATED":
        finding["resolution_note"] = note
        services.mitigate_finding(finding)
    else:
        finding["status"] = "ACCEPTED_RISK"
        finding["resolved_at"] = store.now_iso()
        finding["resolution_note"] = note
        store.touch(finding)
    return respond(finding)
