"""Retest verification and the five-link closure cascade (PRD 3.8)."""
from flask import Blueprint, g, request

import calc
import core
import serialize
from auth import authorize
from core import new_record, touch
from envelope import object_response
from errors import ApiError
from resolve import filtered, get_remediation, get_retest, paginate
from store import store
from util import add_days
from validate import body, get_enum, get_str

bp = Blueprint("retests", __name__)

OUTCOMES = ("PASS", "FAIL", "PARTIAL")
READ_ROLES = (
    "ProgramManager",
    "ComplianceOfficer",
    "PlatformAdmin",
    "RemediationOwner",
    "Tester",
)


@bp.post("/retest-verifications")
def record_verification():
    authorize("Tester", "ComplianceOfficer")
    data = body()
    remediation_id = get_str(data, "remediation_id")
    evidence_uri = get_str(data, "evidence_uri", min_len=1, max_len=500)
    outcome = get_enum(data, "outcome", OUTCOMES)
    residual_note = get_str(data, "residual_note", required=False)
    remediation = get_remediation(remediation_id)
    if remediation["status"] != "SUBMITTED":
        raise ApiError("ERR_REMEDIATION_NOT_SUBMITTED")
    finding = store.findings.get(remediation["finding_id"])
    if g.role == "Tester":
        if finding is not None and g.user_id == finding["discovered_by_tester_id"]:
            raise ApiError("ERR_SOD_VERIFIER_CONFLICT")
    if remediation["validation_requirement"] == "RETEST_REQUIRED" and g.role != "Tester":
        raise ApiError("ERR_VERIFIER_ROLE_NOT_PERMITTED")
    if outcome in ("FAIL", "PARTIAL"):
        if residual_note is None or not residual_note.strip():
            raise ApiError("ERR_RESIDUAL_NOTE_REQUIRED")
    now = store.now()
    record = new_record(
        remediation_id=remediation["id"],
        verifier_tester_id=g.user_id if g.role == "Tester" else None,
        evidence_uri=evidence_uri,
        outcome=outcome,
        residual_note=residual_note,
        state="VERIFIED",
        verified_at=now,
        days_late=calc.days_late(now, remediation["due_at"]),
        signed_off_by_user_id=None,
        signed_off_at=None,
        closure_note=None,
    )
    store.retests[record["id"]] = record
    if outcome == "PASS":
        remediation["status"] = "VALIDATED"
        touch(remediation)
        if finding is not None:
            finding["status"] = "RETEST_PASSED"
            touch(finding)
    else:
        # FAIL and PARTIAL both reject and immediately re-open for another attempt.
        remediation["status"] = "ASSIGNED"
        remediation["evidence_uri"] = None
        remediation["submitted_at"] = None
        if outcome == "PARTIAL":
            remediation["due_at"] = add_days(remediation["due_at"], calc.PARTIAL_GRACE_DAYS)
        touch(remediation)
        if finding is not None:
            finding["status"] = "REMEDIATION_ASSIGNED"
            touch(finding)
    return object_response(serialize.retest(record), 201)


@bp.get("/retest-verifications/<retest_id>")
def read_verification(retest_id):
    authorize(*READ_ROLES)
    return object_response(serialize.retest(get_retest(retest_id)))


@bp.get("/retest-verifications")
def list_verifications():
    authorize(*READ_ROLES)
    rows = filtered(
        list(store.retests.values()),
        remediation_id=request.args.get("remediation_id"),
        verifier_tester_id=request.args.get("verifier_tester_id"),
        outcome=request.args.get("outcome"),
        state=request.args.get("state"),
    )
    return paginate(rows, serialize.retest)


@bp.post("/retest-verifications/<retest_id>/sign-off")
def sign_off(retest_id):
    authorize("ComplianceOfficer")
    retest = get_retest(retest_id)
    data = body()
    closure_note = get_str(data, "closure_note", min_len=1)
    if retest["state"] != "VERIFIED":
        raise ApiError("ERR_RETEST_ALREADY_SIGNED_OFF")
    remediation = store.remediations.get(retest["remediation_id"])
    if retest["outcome"] != "PASS" or remediation is None or remediation["status"] != "VALIDATED":
        raise ApiError("ERR_REMEDIATION_NOT_VALIDATED")
    if g.user_id == remediation["owner_user_id"]:
        raise ApiError("ERR_SOD_SIGNOFF_CONFLICT")
    now = store.now()
    retest["state"] = "SIGNED_OFF"
    retest["signed_off_by_user_id"] = g.user_id
    retest["signed_off_at"] = now
    retest["closure_note"] = closure_note
    touch(retest)
    remediation["status"] = "CLOSED"
    touch(remediation)
    finding = store.findings.get(remediation["finding_id"])
    if finding is not None:
        core.cascade_close_finding(finding)
    return object_response(serialize.retest(retest))
