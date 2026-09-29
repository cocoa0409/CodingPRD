"""Audit findings: manual raise, resolution, reads."""

from flask import Blueprint

import db
import validate
from errors import fail
from middleware import AIRLINE_REP, COMPLIANCE_OFFICER, actor, authenticate, require_scope
from routes.helpers import created, guard_scope, one, resolve, simple_list
from services import cascade

bp = Blueprint("audit", __name__)

FINDING_TYPES = ["SPEC_DEVIATION", "HACCP_BREACH", "SEAL_MISMATCH", "LATE_DELIVERY"]
SEVERITIES = ["MINOR", "MAJOR", "CRITICAL"]
FINDING_STATUSES = ["OPEN", "DISPUTED", "ACCEPTED", "WITHDRAWN"]
SOURCES = ["SYSTEM", "AIRLINE"]


@bp.route("/audit-findings", methods=["POST"])
def raise_finding():
    authenticate(AIRLINE_REP, COMPLIANCE_OFFICER)
    data = validate.body([
        ("airline_id", {"type": "id", "required": True}),
        ("flight_id", {"type": "id", "required": True}),
        ("finding_type", {"type": "enum", "required": True, "values": FINDING_TYPES}),
        ("severity", {"type": "enum", "required": True, "values": SEVERITIES}),
        ("evidence_ref", {"type": "string", "nullable": True}),
    ])

    # band 50 — a rep may only raise findings against its own airline
    require_scope(data["airline_id"])

    # band 60 — referenced rows must exist
    airline = resolve("airlines", data["airline_id"])
    flight = resolve("flights", data["flight_id"], "ERR_FLIGHT_NOT_FOUND")

    act = actor()
    finding = cascade.raise_finding(
        airline["id"],
        flight["id"],
        data["finding_type"],
        data["severity"],
        "AIRLINE" if act is not None and act.is_rep else "SYSTEM",
        data.get("evidence_ref"),
    )
    return created("audit_findings", finding)


@bp.route("/audit-findings/<finding_id>/resolution", methods=["POST"])
def resolve_finding(finding_id):
    authenticate(COMPLIANCE_OFFICER, AIRLINE_REP)
    data = validate.body([
        ("action", {"type": "enum", "required": True,
                    "values": ["DISPUTE", "ACCEPT", "WITHDRAW"]}),
        ("note", {"type": "string", "nullable": True}),
    ])
    action = data["action"]
    act = actor()
    is_rep = act is not None and act.is_rep

    # band 20 — DISPUTE/ACCEPT belong to the officer, WITHDRAW to the rep
    if action == "WITHDRAW":
        if not is_rep:
            fail("ERR_FORBIDDEN_ROLE")
    elif is_rep:
        fail("ERR_FORBIDDEN_ROLE")

    finding = resolve("audit_findings", finding_id)
    guard_scope("audit_findings", finding)

    status = finding["status"]
    if action == "DISPUTE":
        if status != "OPEN":
            fail("ERR_INVALID_RESOURCE_STATE")
        finding["status"] = "DISPUTED"
    elif action == "ACCEPT":
        if status not in ("OPEN", "DISPUTED"):
            fail("ERR_INVALID_RESOURCE_STATE")
        finding["status"] = "ACCEPTED"
    else:
        if status not in ("OPEN", "DISPUTED", "ACCEPTED"):
            fail("ERR_INVALID_RESOURCE_STATE")
        finding["status"] = "WITHDRAWN"

    db.touch(finding)
    # open_finding_count and penalty_accrued_cents are derived, so only the
    # suspension threshold has to be re-evaluated.
    cascade.refresh_airline_status(db.get("airlines", finding["airline_id"]))
    return one("audit_findings", finding)


@bp.route("/audit-findings", methods=["GET"])
def list_findings():
    authenticate()
    return simple_list("audit_findings", {
        "airline_id": {"type": "string"},
        "flight_id": {"type": "string"},
        "finding_type": {"type": "enum", "values": FINDING_TYPES},
        "severity": {"type": "enum", "values": SEVERITIES},
        "source": {"type": "enum", "values": SOURCES},
        "status": {"type": "enum", "values": FINDING_STATUSES},
    })


@bp.route("/audit-findings/<finding_id>", methods=["GET"])
def read_finding(finding_id):
    authenticate()
    finding = resolve("audit_findings", finding_id)
    guard_scope("audit_findings", finding)
    return one("audit_findings", finding)
