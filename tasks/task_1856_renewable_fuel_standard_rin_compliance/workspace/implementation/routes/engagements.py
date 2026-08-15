"""AttestEngagement endpoints: create, get, list, begin-fieldwork, issue-findings, remediate, close."""
from flask import Blueprint, request

import db
from errors import (
    invalid_request, not_found, reference_not_found, invalid_state,
    forbidden, engagement_window_overlap,
)
from middleware import require_roles, json_body
from response import ok_object, ok_list, parse_pagination, paginate
from serializers import engagement_view

bp = Blueprint("engagements", __name__)


def _get_engagement(engagement_id):
    eng = db.attest_engagements.get(engagement_id)
    if eng is None:
        raise not_found("Attest engagement not found")
    return eng


def _require_auditor_identity(user_id, eng):
    if user_id != eng["auditor_user_id"]:
        raise forbidden("Caller is not the engagement's auditor")


@bp.route("/rfs/attest-engagements", methods=["POST"])
def create_engagement():
    require_roles("ComplianceManager")
    body = json_body()

    obligation_year_id = body.get("obligation_year_id")
    auditor_user_id = body.get("auditor_user_id")
    fieldwork_start_raw = body.get("fieldwork_start")
    fieldwork_end_raw = body.get("fieldwork_end")

    # --- Request shape (priority 5) ---
    for field, value in (("obligation_year_id", obligation_year_id),
                         ("auditor_user_id", auditor_user_id),
                         ("fieldwork_start", fieldwork_start_raw),
                         ("fieldwork_end", fieldwork_end_raw)):
        if value is None:
            raise invalid_request(f"{field} is required")
    if not isinstance(auditor_user_id, str):
        raise invalid_request("auditor_user_id must be a string")
    try:
        fieldwork_start = db.parse_iso(fieldwork_start_raw)
        fieldwork_end = db.parse_iso(fieldwork_end_raw)
    except (ValueError, TypeError):
        raise invalid_request("fieldwork_start and fieldwork_end must be valid ISO 8601 datetimes")
    if not fieldwork_end > fieldwork_start:
        raise invalid_request("fieldwork_end must be strictly later than fieldwork_start")

    # --- Referential integrity (priority 6) ---
    if db.obligation_years.get(obligation_year_id) is None:
        raise reference_not_found("Referenced obligation year does not exist")

    # --- Overlap (priority 10): half-open [start, end); touching windows allowed;
    #     only engagements that have not reached CLOSED_CLEAN conflict ---
    for eng in db.attest_engagements.values():
        if eng["auditor_user_id"] != auditor_user_id:
            continue
        if eng["status"] == "CLOSED_CLEAN":
            continue
        # Half-open overlap: new_start < existing_end AND existing_start < new_end
        if fieldwork_start < eng["fieldwork_end"] and eng["fieldwork_start"] < fieldwork_end:
            raise engagement_window_overlap("Fieldwork window overlaps another engagement for the same auditor")

    now = db.now_utc()
    eng = {
        "id": db.new_id(),
        "obligation_year_id": obligation_year_id,
        "auditor_user_id": auditor_user_id,
        "fieldwork_start": fieldwork_start,
        "fieldwork_end": fieldwork_end,
        "status": "ENGAGED",
        "findings": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.attest_engagements[eng["id"]] = eng
    return ok_object(engagement_view(eng), status=201)


@bp.route("/rfs/attest-engagements/<engagement_id>", methods=["GET"])
def get_engagement(engagement_id):
    require_roles("OpsAdmin", "ComplianceManager", "Auditor")
    return ok_object(engagement_view(_get_engagement(engagement_id)))


@bp.route("/rfs/attest-engagements", methods=["GET"])
def list_engagements():
    require_roles("OpsAdmin", "ComplianceManager", "Auditor")
    limit, offset = parse_pagination(request.args)
    obligation_year_id = request.args.get("obligation_year_id")
    rows = list(db.attest_engagements.values())
    if obligation_year_id is not None:
        rows = [r for r in rows if r["obligation_year_id"] == obligation_year_id]
    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    return ok_list([engagement_view(r) for r in page], limit, offset, total)


@bp.route("/rfs/attest-engagements/<engagement_id>/begin-fieldwork", methods=["POST"])
def begin_fieldwork(engagement_id):
    user_id, _ = require_roles("Auditor")
    eng = _get_engagement(engagement_id)
    _require_auditor_identity(user_id, eng)
    if eng["status"] not in ("ENGAGED", "REMEDIATION"):
        raise invalid_state("Engagement must be ENGAGED or REMEDIATION to begin fieldwork")
    eng["status"] = "FIELDWORK"
    eng["version"] += 1
    eng["updated_at"] = db.now_utc()
    return ok_object(engagement_view(eng))


@bp.route("/rfs/attest-engagements/<engagement_id>/issue-findings", methods=["POST"])
def issue_findings(engagement_id):
    user_id, _ = require_roles("Auditor")
    eng = _get_engagement(engagement_id)
    _require_auditor_identity(user_id, eng)
    body = json_body()
    findings = body.get("findings")
    if findings not in ("CLEAN", "ADVERSE"):
        raise invalid_request("findings must be CLEAN or ADVERSE")
    if eng["status"] != "FIELDWORK":
        raise invalid_state("Engagement is not in FIELDWORK")
    eng["status"] = "FINDINGS_ISSUED"
    eng["findings"] = findings
    eng["version"] += 1
    eng["updated_at"] = db.now_utc()
    return ok_object(engagement_view(eng))


@bp.route("/rfs/attest-engagements/<engagement_id>/remediate", methods=["POST"])
def remediate(engagement_id):
    require_roles("ComplianceManager")
    eng = _get_engagement(engagement_id)
    if eng["status"] != "FINDINGS_ISSUED":
        raise invalid_state("Engagement is not in FINDINGS_ISSUED")
    if eng["findings"] != "ADVERSE":
        raise invalid_state("Remediation requires ADVERSE findings")
    eng["status"] = "REMEDIATION"
    eng["version"] += 1
    eng["updated_at"] = db.now_utc()
    return ok_object(engagement_view(eng))


@bp.route("/rfs/attest-engagements/<engagement_id>/close", methods=["POST"])
def close_engagement(engagement_id):
    user_id, _ = require_roles("Auditor")
    eng = _get_engagement(engagement_id)
    _require_auditor_identity(user_id, eng)
    if eng["status"] != "FINDINGS_ISSUED":
        raise invalid_state("Engagement is not in FINDINGS_ISSUED")
    if eng["findings"] != "CLEAN":
        raise invalid_state("Close requires CLEAN findings; remediate first")
    eng["status"] = "CLOSED_CLEAN"
    eng["version"] += 1
    eng["updated_at"] = db.now_utc()
    return ok_object(engagement_view(eng))
