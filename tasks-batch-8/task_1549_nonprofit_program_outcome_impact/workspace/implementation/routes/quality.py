"""Data quality audits and audit findings."""
from decimal import Decimal

from flask import Blueprint, g, request

from db import db, new_entity, now_iso
from errors import ApiError
from middleware import require_roles
from response import ok_object, ok_list
from util import (
    get_body,
    req_str,
    opt_str,
    req_enum,
    get_or_404,
    page_of,
    serialize,
    touch,
    round2,
)
import services

bp = Blueprint("quality", __name__)

QUALITY_READ_ROLES = ("ProgramDirector", "EvaluationLead", "DataSteward")
FINDING_TYPES = ("MISSING_DATA", "OUTLIER", "UNCERTIFIED_COLLECTOR", "CONSENT_LAPSE", "LATE_DATA")


# ------------------------------------------------------------------- audits
@bp.post("/cycles/<cid>/audits")
@require_roles("DataSteward")
def open_audit(cid):
    cycle = get_or_404(db.cycles, cid)
    get_body()
    if cycle["status"] not in ("DATA_CLOSED", "UNDER_REVIEW"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "An audit can open only on a DATA_CLOSED or UNDER_REVIEW cycle.",
        )
    if any(a["program_cycle_id"] == cid and a["status"] == "OPEN" for a in db.audits.values()):
        raise ApiError(
            "ERR_AUDIT_ALREADY_OPEN", 409, "An OPEN audit already exists for this cycle."
        )
    # Snapshots at open: a null completeness is snapshotted as 0.00.
    completeness = cycle["data_completeness_pct"]
    completeness_snapshot = completeness if completeness is not None else Decimal("0.00")
    total = cycle["total_observation_count"]
    validated_pct = (
        round2(Decimal(100) * Decimal(cycle["validated_observation_count"]) / Decimal(total))
        if total
        else Decimal("0.00")
    )
    ent = new_entity(
        db.audits,
        {
            "program_cycle_id": cid,
            "status": "OPEN",
            "opened_by_id": g.user_id,
            "completeness_pct": completeness_snapshot,
            "validated_pct": validated_pct,
            "dq_score": None,
            "open_finding_count": 0,
            "closed_at": None,
        },
    )
    # Compute dq_score at open and refresh the cycle's latest_dq_score.
    services.refresh_cycle_dq(cycle, audit=ent)
    return ok_object(serialize(ent), 201)


@bp.get("/cycles/<cid>/audits")
@require_roles(*QUALITY_READ_ROLES)
def list_cycle_audits(cid):
    get_or_404(db.cycles, cid)
    items = [a for a in db.audits.values() if a["program_cycle_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    data, limit, offset, total = page_of(items)
    return ok_list(data, limit, offset, total)


@bp.get("/audits/<aid>")
@require_roles(*QUALITY_READ_ROLES)
def get_audit(aid):
    return ok_object(serialize(get_or_404(db.audits, aid)))


@bp.post("/audits/<aid>/close")
@require_roles("DataSteward")
def close_audit(aid):
    audit = get_or_404(db.audits, aid)
    get_body()
    if audit["status"] != "OPEN":
        raise ApiError(
            "ERR_INVALID_STATE", 409, f"Audit in state {audit['status']} cannot be closed."
        )
    if audit["open_finding_count"] != 0:
        raise ApiError(
            "ERR_INVALID_STATE", 409, "An audit cannot close while findings remain OPEN."
        )
    audit["status"] = "CLOSED"
    audit["closed_at"] = now_iso()
    touch(db.audits, audit)
    cycle = db.cycles.get(audit["program_cycle_id"])
    if cycle is not None:
        # Final recompute; the score copies to the cycle's latest_dq_score.
        dq = services.compute_dq(cycle, "STANDARD")
        if audit["dq_score"] != dq:
            audit["dq_score"] = dq
            touch(db.audits, audit)
        if cycle["latest_dq_score"] != dq:
            cycle["latest_dq_score"] = dq
            touch(db.cycles, cycle)
    return ok_object(serialize(audit))


# ----------------------------------------------------------------- findings
@bp.post("/audits/<aid>/findings")
@require_roles("DataSteward")
def record_finding(aid):
    audit = get_or_404(db.audits, aid)
    body = get_body()
    finding_type = req_enum(body, "finding_type", FINDING_TYPES)
    participant_id = req_str(body, "participant_id")
    indicator_id = opt_str(body, "indicator_id")
    observation_id = opt_str(body, "observation_id")
    description = opt_str(body, "description", "") or ""
    if db.participants.get(participant_id) is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Participant not found: {participant_id}")
    if indicator_id is not None and db.indicators.get(indicator_id) is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Indicator not found: {indicator_id}")
    if observation_id is not None and db.observations.get(observation_id) is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Observation not found: {observation_id}")
    if audit["status"] != "OPEN":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Findings can be recorded only under an OPEN audit."
        )
    ent = new_entity(
        db.findings,
        {
            "audit_id": aid,
            "finding_type": finding_type,
            "participant_id": participant_id,
            "indicator_id": indicator_id,
            "observation_id": observation_id,
            "description": description,
            "status": "OPEN",
            "resolution_note": None,
        },
    )
    cycle = db.cycles.get(audit["program_cycle_id"])
    if cycle is not None:
        # Each new open finding drags the score down by the per-finding penalty.
        services.refresh_cycle_dq(cycle, audit=audit)
    return ok_object(serialize(ent), 201)


@bp.get("/audits/<aid>/findings")
@require_roles(*QUALITY_READ_ROLES)
def list_audit_findings(aid):
    get_or_404(db.audits, aid)
    items = [f for f in db.findings.values() if f["audit_id"] == aid]
    status = request.args.get("status")
    if status is not None:
        items = [f for f in items if f["status"] == status]
    ftype = request.args.get("finding_type")
    if ftype is not None:
        items = [f for f in items if f["finding_type"] == ftype]
    data, limit, offset, total = page_of(items)
    return ok_list(data, limit, offset, total)


@bp.get("/participants/<pid>/findings")
@require_roles(*QUALITY_READ_ROLES)
def list_participant_findings(pid):
    get_or_404(db.participants, pid)
    items = [f for f in db.findings.values() if f["participant_id"] == pid]
    status = request.args.get("status")
    if status is not None:
        items = [f for f in items if f["status"] == status]
    data, limit, offset, total = page_of(items)
    return ok_list(data, limit, offset, total)


@bp.get("/findings/<fid>")
@require_roles(*QUALITY_READ_ROLES)
def get_finding(fid):
    return ok_object(serialize(get_or_404(db.findings, fid)))


@bp.get("/findings")
@require_roles(*QUALITY_READ_ROLES)
def list_findings():
    items = list(db.findings.values())
    for param in ("audit_id", "observation_id", "participant_id", "indicator_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [f for f in items if f[param] == v]
    data, limit, offset, total = page_of(items)
    return ok_list(data, limit, offset, total)


def _resolve_finding(fid, note_key):
    finding = get_or_404(db.findings, fid)
    body = get_body()
    note = req_str(body, note_key)
    if finding["status"] != "OPEN":
        raise ApiError(
            "ERR_INVALID_STATE", 409, f"Finding in state {finding['status']} cannot be resolved."
        )
    audit = db.audits.get(finding["audit_id"])
    if audit is None or audit["status"] != "OPEN":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Findings can be resolved only under an OPEN audit."
        )
    # Segregation of duties for observation-linked findings.
    if finding["observation_id"] is not None:
        obs = db.observations.get(finding["observation_id"])
        if obs is not None and obs["collected_by_id"] == g.user_id:
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTY",
                422,
                "A steward cannot resolve a finding on their own collection.",
            )
    return finding, audit, note


@bp.post("/findings/<fid>/waive")
@require_roles("DataSteward")
def waive_finding(fid):
    finding, audit, reason = _resolve_finding(fid, "reason")
    finding["status"] = "WAIVED"
    finding["resolution_note"] = reason
    touch(db.findings, finding)
    cycle = db.cycles.get(audit["program_cycle_id"]) if audit else None
    if cycle is not None:
        services.refresh_cycle_dq(cycle, audit=audit)
    return ok_object(serialize(finding))


@bp.post("/findings/<fid>/remediate")
@require_roles("DataSteward")
def remediate_finding(fid):
    finding, audit, note = _resolve_finding(fid, "note")
    finding["status"] = "REMEDIATED"
    finding["resolution_note"] = note
    touch(db.findings, finding)
    cycle = db.cycles.get(audit["program_cycle_id"]) if audit else None
    if cycle is not None:
        services.refresh_cycle_dq(cycle, audit=audit)
    return ok_object(serialize(finding))
