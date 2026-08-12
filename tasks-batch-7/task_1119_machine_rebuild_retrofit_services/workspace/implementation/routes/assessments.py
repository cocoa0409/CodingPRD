"""Assessment endpoints (PRD §3.2)."""

from flask import Blueprint, request

from calc import compute_wear_index, recommended_path_for
from db import bump, new_record, sorted_records, store
from errors import ApiError, ERR_INVALID_STATE, ERR_STALE_MACHINE_VERSION
from middleware import forbidden, require_roles
from response import list_response, success
from serializers import serialize, serialize_list
from util import (
    get_body,
    pagination_params,
    paginate,
    req_int,
    req_number,
    req_str,
)
from routes.common import check_customer_ownership, customer_owns, get_or_404

bp = Blueprint("assessments", __name__)


def _validate_assessment_body(body):
    pd = req_number(body, "positioning_deviation_microns", minimum=0)
    sr = req_number(body, "spindle_runout_microns", minimum=0)
    bl = req_number(body, "backlash_microns", minimum=0)
    scope_notes = req_str(body, "scope_notes", non_empty=False)
    expected_version = req_int(body, "expected_machine_version")
    return pd, sr, bl, scope_notes, expected_version


@bp.post("/api/machines/<mid>/assessments")
@require_roles("Assessor")
def create_assessment(user_id, role, mid):
    body = get_body()
    # Gate 3 (body shape) before gate 4 (path existence).
    pd, sr, bl, scope_notes, expected_version = _validate_assessment_body(body)
    machine = get_or_404(store.machines, mid, "machine")
    # Gate 5: OCC on Machine.version (never optional on this endpoint).
    if expected_version != machine["version"]:
        raise ApiError(
            ERR_STALE_MACHINE_VERSION,
            "expected_machine_version does not match the machine's current version",
            412,
        )
    # Side effect 1: prior non-terminal assessment of this machine -> SUPERSEDED.
    for a in sorted_records(store.assessments):
        if a["machine_id"] == mid and a["status"] in ("DRAFT", "SUBMITTED", "RETURNED"):
            a["status"] = "SUPERSEDED"
            bump(a)
    wear_index = compute_wear_index(pd, sr, bl)
    rec = new_record(
        {
            "machine_id": mid,
            "assessor_id": user_id,
            "positioning_deviation_microns": pd,
            "spindle_runout_microns": sr,
            "backlash_microns": bl,
            "scope_notes": scope_notes,
            "wear_index": wear_index,
            "recommended_path": recommended_path_for(wear_index),
            "status": "DRAFT",
        }
    )
    store.assessments[rec["id"]] = rec
    # Side effect 2: Machine.version +1; first filing moves REGISTERED ->
    # UNDER_ASSESSMENT; later filings leave the machine status untouched.
    if machine["status"] == "REGISTERED":
        machine["status"] = "UNDER_ASSESSMENT"
    bump(machine)
    return success(serialize(rec), status=201)


@bp.get("/api/assessments/<aid>")
@require_roles("Assessor", "ProjectManager", "PlatformAdmin", "Customer")
def get_assessment(user_id, role, aid):
    rec = get_or_404(store.assessments, aid, "assessment")
    check_customer_ownership(user_id, role, "assessment", rec)
    return success(serialize(rec))


@bp.get("/api/assessments")
@require_roles("Assessor", "ProjectManager", "PlatformAdmin", "Customer")
def list_assessments(user_id, role):
    limit, offset = pagination_params()
    items = sorted_records(store.assessments)
    machine_filter = request.args.get("machine_id")
    if machine_filter is not None:
        items = [a for a in items if a["machine_id"] == machine_filter]
    if role == "Customer":
        items = [a for a in items if customer_owns(user_id, "assessment", a)]
    page, meta = paginate(items, limit, offset)
    return list_response(serialize_list(page), meta)


@bp.post("/api/assessments/<aid>/submit")
@require_roles("Assessor")
def submit_assessment(user_id, role, aid):
    rec = get_or_404(store.assessments, aid, "assessment")
    # Ownership: only the recording assessor may submit (PRD §3.2).
    if rec["assessor_id"] != user_id:
        raise forbidden("only the recording assessor may submit this assessment")
    if rec["status"] not in ("DRAFT", "RETURNED"):
        raise ApiError(
            ERR_INVALID_STATE,
            f"assessment in status {rec['status']} cannot be submitted",
            409,
        )
    rec["status"] = "SUBMITTED"
    bump(rec)
    return success(serialize(rec))


@bp.post("/api/assessments/<aid>/return")
@require_roles("ProjectManager")
def return_assessment(user_id, role, aid):
    rec = get_or_404(store.assessments, aid, "assessment")
    if rec["status"] != "SUBMITTED":
        raise ApiError(
            ERR_INVALID_STATE,
            f"assessment in status {rec['status']} cannot be returned",
            409,
        )
    rec["status"] = "RETURNED"
    bump(rec)
    return success(serialize(rec))


@bp.post("/api/assessments/<aid>/accept")
@require_roles("ProjectManager")
def accept_assessment(user_id, role, aid):
    rec = get_or_404(store.assessments, aid, "assessment")
    if rec["status"] != "SUBMITTED":
        raise ApiError(
            ERR_INVALID_STATE,
            f"assessment in status {rec['status']} cannot be accepted",
            409,
        )
    machine = store.machines[rec["machine_id"]]
    if machine["status"] != "UNDER_ASSESSMENT":
        raise ApiError(
            ERR_INVALID_STATE,
            "machine must be UNDER_ASSESSMENT to accept an assessment",
            409,
        )
    rec["status"] = "ACCEPTED"
    bump(rec)
    machine["status"] = "ASSESSED"
    bump(machine)
    # Auto-create the RebuildProject carrying the engagement.
    project = new_record(
        {
            "machine_id": machine["id"],
            "customer_id": machine["customer_id"],
            "assessment_id": rec["id"],
            "decision": "NONE",
            "decision_reason": None,
            "assigned_engineer_id": None,
            "work_status": "SCOPED",
            "commercial_status": "QUOTE_DRAFT",
            "quote_revision": 0,
            "quote_stale": False,
            "base_price_cents": 0,
            "parts_total_cents": 0,
            "labor_cents": 0,
            "discount_cents": 0,
            "applied_trade_in_credit_cents": 0,
            "quote_price_cents": 0,
            "rework_count": 0,
            "consecutive_fail_count": 0,
            "rework_cost_cents": 0,
            "escalation_count": 0,
            "accepted_positioning_microns": None,
            "delivery_date": None,
            "warranty_months": None,
            "warranty_end": None,
            "_warranty_end_dt": None,
        }
    )
    store.projects[project["id"]] = project
    return success(serialize(rec))
