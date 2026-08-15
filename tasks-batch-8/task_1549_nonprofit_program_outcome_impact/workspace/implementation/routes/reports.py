"""Reports: creation under cycle OCC, gated generation, funder judgement loop."""
from flask import Blueprint, g, request

from db import db, new_entity, now_iso
from errors import ApiError
from middleware import require_roles
from response import ok_object, ok_list
from util import (
    get_body,
    req_str,
    req_enum,
    req_int,
    get_or_404,
    page_of,
    serialize,
    touch,
)
import services

bp = Blueprint("reports", __name__)

REPORT_READ_ROLES = ("ProgramDirector", "EvaluationLead", "DataSteward", "FunderViewer")
REPORT_TYPES = ("FUNDER_STANDARD", "FUNDER_CUSTOM", "INTERNAL_DASHBOARD")


def _funder_scope_check(report_id):
    """FunderViewer record scoping: fails closed (ERR_SCOPE_DENIED) whenever the
    target is not verifiably the caller's own report (SCAFFOLD 1.4 priority 4)."""
    if g.role != "FunderViewer":
        return
    report = db.reports.get(report_id)
    if report is None or report["funder_id"] != g.user_id:
        raise ApiError("ERR_SCOPE_DENIED", 403, "Report does not belong to the caller's funder.")


# ------------------------------------------------------------------ create
@bp.post("/cycles/<cid>/reports")
@require_roles("EvaluationLead")
def create_report(cid):
    cycle = get_or_404(db.cycles, cid)
    body = get_body()
    funder_id = req_str(body, "funder_id")
    report_type = req_enum(body, "report_type", REPORT_TYPES)
    expected_version = req_int(body, "expected_program_cycle_version")
    funder = db.funders.get(funder_id)
    if funder is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Funder not found: {funder_id}")
    if cycle["status"] not in ("UNDER_REVIEW", "REPORTED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Reports can be created only on an UNDER_REVIEW or REPORTED cycle.",
        )
    if funder["status"] != "ACTIVE":
        raise ApiError("ERR_FUNDER_INACTIVE", 422, "An INACTIVE funder cannot receive new reports.")
    # OCC is the last check in the validation order (SCAFFOLD 1.4 priority 23).
    if expected_version != cycle["version"]:
        raise ApiError(
            "ERR_STALE_CYCLE_VERSION",
            412,
            "expected_program_cycle_version does not match the cycle's current version.",
        )
    # Replacement semantics: supersede existing DRAFT/GENERATED for the triple.
    for r in db.reports.values():
        if (
            r["program_cycle_id"] == cid
            and r["funder_id"] == funder_id
            and r["report_type"] == report_type
            and r["status"] in ("DRAFT", "GENERATED")
        ):
            r["status"] = "SUPERSEDED"
            touch(db.reports, r)
    ent = new_entity(
        db.reports,
        {
            "program_cycle_id": cid,
            "funder_id": funder_id,
            "report_type": report_type,
            "status": "DRAFT",
            "snapshot_overall_impact_index": None,
            "snapshot_data_completeness_pct": None,
            "snapshot_dq_score": None,
            "generated_at": None,
            "delivered_at": None,
        },
    )
    # Report creation advances the parent cycle's version by one.
    touch(db.cycles, cycle)
    return ok_object(serialize(ent), 201)


# ------------------------------------------------------------------- reads
@bp.get("/cycles/<cid>/reports")
@require_roles(*REPORT_READ_ROLES)
def list_cycle_reports(cid):
    get_or_404(db.cycles, cid)
    items = [r for r in db.reports.values() if r["program_cycle_id"] == cid]
    if g.role == "FunderViewer":
        # The report list is forcibly restricted to the caller's own funder.
        items = [r for r in items if r["funder_id"] == g.user_id]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    data, limit, offset, total = page_of(items)
    return ok_list(data, limit, offset, total)


@bp.get("/reports/<rid>")
@require_roles(*REPORT_READ_ROLES)
def get_report(rid):
    _funder_scope_check(rid)
    return ok_object(serialize(get_or_404(db.reports, rid)))


@bp.get("/reports")
@require_roles(*REPORT_READ_ROLES)
def list_reports():
    items = list(db.reports.values())
    if g.role == "FunderViewer":
        items = [r for r in items if r["funder_id"] == g.user_id]
    else:
        funder_id = request.args.get("funder_id")
        if funder_id is not None:
            items = [r for r in items if r["funder_id"] == funder_id]
    cycle_id = request.args.get("program_cycle_id")
    if cycle_id is not None:
        items = [r for r in items if r["program_cycle_id"] == cycle_id]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    data, limit, offset, total = page_of(items)
    return ok_list(data, limit, offset, total)


# --------------------------------------------------------------- lifecycle
def _generate(report, from_state):
    if report["status"] != from_state:
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Report in state {report['status']} cannot be generated from {from_state}.",
        )
    cycle = db.cycles.get(report["program_cycle_id"])
    # The data-quality gate applies to funder report types only.
    if report["report_type"] in ("FUNDER_STANDARD", "FUNDER_CUSTOM"):
        dq = cycle["latest_dq_score"] if cycle else None
        if dq is None or dq < services.DQ_GATE:
            raise ApiError(
                "ERR_DQ_GATE_NOT_MET",
                422,
                "cycle.latest_dq_score must be present and >= 80.00 to generate.",
            )
    # Pin the three snapshots at this instant.
    report["snapshot_overall_impact_index"] = (
        services.overall_impact_index(cycle) if cycle else None
    )
    report["snapshot_data_completeness_pct"] = (
        cycle["data_completeness_pct"] if cycle else None
    )
    report["snapshot_dq_score"] = cycle["latest_dq_score"] if cycle else None
    report["generated_at"] = now_iso()
    report["status"] = "GENERATED"
    touch(db.reports, report)
    return ok_object(serialize(report))


@bp.post("/reports/<rid>/generate")
@require_roles("EvaluationLead")
def generate_report(rid):
    report = get_or_404(db.reports, rid)
    get_body()
    return _generate(report, "DRAFT")


@bp.post("/reports/<rid>/regenerate")
@require_roles("EvaluationLead")
def regenerate_report(rid):
    report = get_or_404(db.reports, rid)
    get_body()
    return _generate(report, "RETURNED")


@bp.post("/reports/<rid>/deliver")
@require_roles("EvaluationLead")
def deliver_report(rid):
    report = get_or_404(db.reports, rid)
    get_body()
    if report["status"] != "GENERATED":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Report in state {report['status']} cannot be delivered.",
        )
    report["status"] = "DELIVERED"
    report["delivered_at"] = now_iso()
    touch(db.reports, report)
    return ok_object(serialize(report))


@bp.post("/reports/<rid>/accept")
@require_roles("FunderViewer")
def accept_report(rid):
    _funder_scope_check(rid)
    report = get_or_404(db.reports, rid)
    get_body()
    if report["status"] != "DELIVERED":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Report in state {report['status']} cannot be accepted.",
        )
    report["status"] = "ACCEPTED"
    touch(db.reports, report)
    return ok_object(serialize(report))


@bp.post("/reports/<rid>/return")
@require_roles("FunderViewer")
def return_report(rid):
    _funder_scope_check(rid)
    report = get_or_404(db.reports, rid)
    body = get_body()
    req_str(body, "reason")
    if report["status"] != "DELIVERED":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Report in state {report['status']} cannot be returned.",
        )
    report["status"] = "RETURNED"
    touch(db.reports, report)
    return ok_object(serialize(report))
