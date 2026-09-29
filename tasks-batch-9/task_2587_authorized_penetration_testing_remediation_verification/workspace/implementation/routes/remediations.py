"""Remediation assignment, extensions and evidence submission (PRD 3.8)."""
from flask import Blueprint, g, request

import calc
import core
import serialize
from auth import authorize
from core import new_record, touch
from envelope import object_response
from errors import ApiError
from resolve import filtered, get_finding, get_remediation, paginate
from store import store
from util import add_days
from validate import body, get_enum, get_int, get_str

bp = Blueprint("remediations", __name__)

VALIDATION_REQUIREMENTS = ("RETEST_REQUIRED", "EVIDENCE_ONLY")
READ_ROLES = (
    "ProgramManager",
    "ComplianceOfficer",
    "PlatformAdmin",
    "RemediationOwner",
    "Tester",
)


@bp.post("/remediations")
def assign_remediation():
    authorize("ProgramManager")
    data = body()
    finding_id = get_str(data, "finding_id")
    owner_user_id = get_str(data, "owner_user_id", min_len=1, max_len=64)
    requirement = get_enum(data, "validation_requirement", VALIDATION_REQUIREMENTS)
    plan_text = get_str(data, "remediation_plan", min_len=1, max_len=2000)
    finding = get_finding(finding_id)
    if finding["status"] != "TRIAGED":
        raise ApiError("ERR_FINDING_NOT_TRIAGED")
    for existing in store.remediations.values():
        if existing["finding_id"] == finding["id"] and existing["status"] != "CLOSED":
            raise ApiError("ERR_REMEDIATION_ALREADY_EXISTS")
    now = store.now()
    asset = store.assets.get(finding["asset_id"])
    regimes = asset["compliance_regimes"] if asset is not None else []
    days = calc.sla_days(finding["severity_band"], regimes)
    record = new_record(
        finding_id=finding["id"],
        owner_user_id=owner_user_id,
        validation_requirement=requirement,
        remediation_plan=plan_text,
        sla_days=days,
        due_at=calc.due_at(now, days),
        extension_count=0,
        overdue_flag=False,
        status="ASSIGNED",
        submitted_at=None,
        evidence_uri=None,
    )
    store.remediations[record["id"]] = record
    finding["status"] = "REMEDIATION_ASSIGNED"
    touch(finding)
    return object_response(serialize.remediation(record), 201)


@bp.get("/remediations/<remediation_id>")
def read_remediation(remediation_id):
    authorize(*READ_ROLES)
    return object_response(serialize.remediation(get_remediation(remediation_id)))


@bp.get("/remediations")
def list_remediations():
    authorize(*READ_ROLES)
    rows = filtered(
        list(store.remediations.values()),
        finding_id=request.args.get("finding_id"),
        status=request.args.get("status"),
    )
    overdue = request.args.get("overdue_flag")
    if overdue is not None:
        wanted = str(overdue).strip().lower() == "true"
        now = store.now()
        rows = [row for row in rows if calc.is_overdue(row, now) == wanted]
    return paginate(rows, serialize.remediation)


@bp.post("/remediations/<remediation_id>/submit")
def submit_evidence(remediation_id):
    authorize("RemediationOwner")
    remediation = get_remediation(remediation_id)
    data = body()
    evidence_uri = get_str(data, "evidence_uri", min_len=1)
    if remediation["status"] != "ASSIGNED":
        raise ApiError("ERR_REMEDIATION_NOT_ASSIGNED")
    if g.user_id != remediation["owner_user_id"]:
        raise ApiError("ERR_ACTOR_NOT_OWNER")
    remediation["status"] = "SUBMITTED"
    remediation["submitted_at"] = store.now()
    remediation["evidence_uri"] = evidence_uri
    touch(remediation)
    finding = store.findings.get(remediation["finding_id"])
    if finding is not None and finding["status"] == "REMEDIATION_ASSIGNED":
        finding["status"] = "REMEDIATION_SUBMITTED"
        touch(finding)
    for retest in core.remediation_retests(remediation["id"]):
        if retest["state"] == "VERIFIED":
            retest["state"] = "SUPERSEDED"
            touch(retest)
    return object_response(serialize.remediation(remediation))


@bp.post("/remediations/<remediation_id>/extension")
def grant_extension(remediation_id):
    authorize("ProgramManager")
    remediation = get_remediation(remediation_id)
    data = body()
    additional_days = get_int(data, "additional_days", minimum=1)
    get_str(data, "reason", min_len=1)
    if remediation["status"] != "ASSIGNED":
        raise ApiError("ERR_REMEDIATION_NOT_ASSIGNED")
    if remediation["extension_count"] >= calc.MAX_EXTENSIONS:
        raise ApiError("ERR_EXTENSION_LIMIT_REACHED")
    remediation["due_at"] = add_days(remediation["due_at"], additional_days)
    remediation["extension_count"] = remediation["extension_count"] + 1
    remediation["overdue_flag"] = calc.is_overdue(remediation, store.now())
    touch(remediation)
    return object_response(serialize.remediation(remediation))
