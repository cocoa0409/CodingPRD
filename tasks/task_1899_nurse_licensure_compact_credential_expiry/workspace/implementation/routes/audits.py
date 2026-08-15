from decimal import ROUND_HALF_UP, Decimal

from flask import Blueprint, request

import db
from errors import (
    ERR_AUDIT_FINDINGS_OPEN,
    ERR_INVALID_AUDIT_STATE,
    ERR_INVALID_DATE_RANGE,
    ERR_INVALID_FINDING_STATE,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ApiError,
)
from middleware import auth_context, get_body, pagination_params, require_role, validate_body
from response import success_list, success_object
from services.core import all_entities, create_entity, get_or_404, serialize, touch
from util import parse_date_loose, parse_time_loose

bp = Blueprint("audits", __name__)

CREATE_SCHEMA = {
    "window_start": ("date", True, None),
    "window_end": ("date", True, None),
    "per_unit_sample_size": ("int", True, None),
}


def _run_or_404(run_id):
    return get_or_404("audit_runs", run_id, ERR_NOT_FOUND, "Audit run not found")


def _finding_or_404(finding_id):
    return get_or_404("audit_findings", finding_id, ERR_NOT_FOUND, "Audit finding not found")


@bp.route("/credentialing/audit-runs", methods=["POST"])
def create_audit_run():
    user_id, role = auth_context()
    require_role(role, {"ComplianceOfficer"})
    body = validate_body(get_body(), CREATE_SCHEMA)
    if body["per_unit_sample_size"] < 1:
        raise ApiError(ERR_INVALID_REQUEST, "per_unit_sample_size must be at least 1", 400)
    window_start = body["window_start"]
    window_end = body["window_end"]
    if window_start >= window_end or window_end > db.current_date():
        raise ApiError(ERR_INVALID_DATE_RANGE, "window_start must be strictly before window_end and window_end must not lie in the future", 422)
    run = create_entity("audit_runs", {
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "per_unit_sample_size": body["per_unit_sample_size"],
        "status": "INITIATED",
        "sampled_nurse_ids": [],
        "point_in_time_rate": None,
        "shift_incidence_rate": None,
        "projected_deficiency_count": None,
        "created_by_user_id": user_id,
    })
    return success_object(serialize("audit_runs", run), 201)


@bp.route("/credentialing/audit-runs", methods=["GET"])
def list_audit_runs():
    auth_context()
    limit, offset = pagination_params()
    rows = all_entities("audit_runs")
    value = request.args.get("status")
    if value is not None:
        rows = [r for r in rows if r["status"] == value]
    total = len(rows)
    return success_list([serialize("audit_runs", r) for r in rows[offset:offset + limit]], limit, offset, total)


@bp.route("/credentialing/audit-runs/<runId>", methods=["GET"])
def get_audit_run(runId):
    auth_context()
    run = _run_or_404(runId)
    return success_object(serialize("audit_runs", run))


@bp.route("/credentialing/audit-runs/<runId>/begin-fieldwork", methods=["POST"])
def begin_fieldwork(runId):
    user_id, role = auth_context()
    require_role(role, {"ComplianceOfficer"})
    run = _run_or_404(runId)
    if run["status"] != "INITIATED":
        raise ApiError(ERR_INVALID_AUDIT_STATE, "Only an INITIATED run can begin fieldwork", 409)
    window_start = parse_date_loose(run["window_start"])
    window_end = parse_date_loose(run["window_end"])
    nurses = db.STORES["nurses"]
    sampled = []
    strata = []
    for unit in all_entities("units"):  # creation order
        counts = {}
        for shift in all_entities("shifts"):
            if shift["unit_id"] != unit["id"] or shift["status"] != "COMPLETED":
                continue
            shift_date = parse_time_loose(shift["starts_at"]).date()
            if window_start <= shift_date <= window_end:
                counts[shift["nurse_id"]] = counts.get(shift["nurse_id"], 0) + 1
        # Rank: completed-shift-count DESC, tie-break nurse.created_at ASC
        # (insertion sequence breaks identical instants).
        candidates = sorted(
            counts.keys(),
            key=lambda nid: (-counts[nid], nurses[nid]["created_at"], nurses[nid]["_seq"]),
        )
        taken = candidates[:run["per_unit_sample_size"]]
        strata.append({"unit_id": unit["id"], "candidates": len(candidates), "sampled": taken})
        sampled.extend(taken)
    run["sampled_nurse_ids"] = sampled
    run["_strata"] = strata
    run["status"] = "FIELD_WORK"
    touch(run)
    return success_object(serialize("audit_runs", run))


def _evaluate_slots(nurse, window_end):
    """Date-driven slot evaluation as of window_end (sweep-status independent).
    Returns list of (valid, finding_type, detail)."""
    results = []
    license_ok = any(
        lic for lic in all_entities("licenses")
        if lic["nurse_id"] == nurse["id"]
        and lic["status"] != "SURRENDERED"
        and parse_date_loose(lic["expires_on"]) >= window_end
    )
    results.append((license_ok, "LICENSE_NOT_CURRENT_IN_WINDOW", "practice_authority"))
    bls_ok = any(
        c for c in all_entities("certifications")
        if c["nurse_id"] == nurse["id"]
        and c["cert_type"] == "BLS"
        and c["status"] != "REVOKED"
        and parse_date_loose(c["expires_on"]) >= window_end
    )
    results.append((bls_ok, "CERTIFICATION_NOT_CURRENT_IN_WINDOW", "BLS"))
    for req in all_entities("requirements"):
        if req["mandatory"] and nurse["employment_type"] in req["applies_to"]:
            ok = any(
                cp for cp in all_entities("completions")
                if cp["nurse_id"] == nurse["id"]
                and cp["requirement_id"] == req["id"]
                and parse_date_loose(cp["expires_on"]) >= window_end
            )
            results.append((ok, "COMPETENCY_NOT_CURRENT_IN_WINDOW", req["code"]))
    return results


@bp.route("/credentialing/audit-runs/<runId>/issue-findings", methods=["POST"])
def issue_findings(runId):
    user_id, role = auth_context()
    require_role(role, {"ComplianceOfficer"})
    run = _run_or_404(runId)
    if run["status"] != "FIELD_WORK":
        raise ApiError(ERR_INVALID_AUDIT_STATE, "Only a FIELD_WORK run can issue findings", 409)
    window_start = parse_date_loose(run["window_start"])
    window_end = parse_date_loose(run["window_end"])
    sampled = run["sampled_nurse_ids"]
    strata = run.get("_strata", [])

    # Evaluate slots per sampled entry; one OPEN finding per deficient slot.
    slot_results = {}  # nurse_id -> list of slot tuples
    valid_slots = 0
    total_slots = 0
    for nurse_id in sampled:
        nurse = db.STORES["nurses"].get(nurse_id)
        if nurse is None:
            continue
        results = _evaluate_slots(nurse, window_end)
        slot_results[nurse_id] = results
        for valid, finding_type, detail in results:
            total_slots += 1
            if valid:
                valid_slots += 1
            else:
                create_entity("audit_findings", {
                    "audit_run_id": run["id"],
                    "nurse_id": nurse_id,
                    "finding_type": finding_type,
                    "detail": detail,
                    "status": "OPEN",
                })

    # POINT_IN_TIME (pooled); empty slot set -> 100.0.
    if total_slots == 0:
        run["point_in_time_rate"] = 100.0
    else:
        run["point_in_time_rate"] = float(
            (Decimal(100) * Decimal(valid_slots) / Decimal(total_slots)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        )

    # SHIFT_INCIDENCE over completed shifts of sampled nurses in the window.
    sample_set = set(sampled)
    window_shifts = [
        s for s in all_entities("shifts")
        if s["status"] == "COMPLETED"
        and s["nurse_id"] in sample_set
        and window_start <= parse_time_loose(s["starts_at"]).date() <= window_end
    ]
    if not window_shifts:
        run["shift_incidence_rate"] = 100.0
    else:
        clear_count = sum(1 for s in window_shifts if s["was_clear_at_start"] is True)
        run["shift_incidence_rate"] = float(
            (Decimal(100) * Decimal(clear_count) / Decimal(len(window_shifts))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        )

    # survey_deficiency_projection: per-stratum rounding FIRST (pinned order),
    # then integer round of the sum of rounded strata.
    projection_sum = Decimal("0")
    for stratum in strata:
        candidate_count = stratum["candidates"]
        if candidate_count == 0:
            continue
        sampled_in_unit = stratum["sampled"]
        s_u = len(sampled_in_unit)
        if s_u == 0:
            continue
        d_u = sum(
            1 for nid in sampled_in_unit
            if any(not valid for valid, _, _ in slot_results.get(nid, []))
        )
        proj_u = (Decimal(d_u) / Decimal(s_u) * Decimal(candidate_count)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        projection_sum += proj_u
    run["projected_deficiency_count"] = int(projection_sum.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    run["status"] = "FINDINGS_ISSUED"
    touch(run)
    return success_object(serialize("audit_runs", run))


@bp.route("/credentialing/audit-runs/<runId>/close", methods=["POST"])
def close_audit_run(runId):
    user_id, role = auth_context()
    require_role(role, {"ComplianceOfficer"})
    run = _run_or_404(runId)
    if run["status"] != "FINDINGS_ISSUED":
        raise ApiError(ERR_INVALID_AUDIT_STATE, "Only a FINDINGS_ISSUED run can be closed", 409)
    if any(f for f in all_entities("audit_findings") if f["audit_run_id"] == run["id"] and f["status"] == "OPEN"):
        raise ApiError(ERR_AUDIT_FINDINGS_OPEN, "Open findings remain for this audit run", 409)
    run["status"] = "CLOSED"
    touch(run)
    return success_object(serialize("audit_runs", run))


# --- Audit findings --------------------------------------------------------------

@bp.route("/credentialing/audit-findings", methods=["GET"])
def list_findings():
    auth_context()
    limit, offset = pagination_params()
    rows = all_entities("audit_findings")
    for param in ("audit_run_id", "nurse_id", "status"):
        value = request.args.get(param)
        if value is not None:
            rows = [f for f in rows if f[param] == value]
    total = len(rows)
    return success_list([serialize("audit_findings", f) for f in rows[offset:offset + limit]], limit, offset, total)


@bp.route("/credentialing/audit-findings/<findingId>", methods=["GET"])
def get_finding(findingId):
    auth_context()
    finding = _finding_or_404(findingId)
    return success_object(serialize("audit_findings", finding))


@bp.route("/credentialing/audit-findings/<findingId>/remediate", methods=["POST"])
def remediate_finding(findingId):
    user_id, role = auth_context()
    require_role(role, {"ComplianceOfficer"})
    finding = _finding_or_404(findingId)
    if finding["status"] != "OPEN":
        raise ApiError(ERR_INVALID_FINDING_STATE, "Only an OPEN finding can be remediated", 409)
    finding["status"] = "REMEDIATED"
    touch(finding)
    return success_object(serialize("audit_findings", finding))


@bp.route("/credentialing/audit-findings/<findingId>/accept-risk", methods=["POST"])
def accept_risk_finding(findingId):
    user_id, role = auth_context()
    require_role(role, {"ComplianceOfficer"})
    finding = _finding_or_404(findingId)
    if finding["status"] != "OPEN":
        raise ApiError(ERR_INVALID_FINDING_STATE, "Only an OPEN finding can be accepted as risk", 409)
    finding["status"] = "ACCEPTED_RISK"
    touch(finding)
    return success_object(serialize("audit_findings", finding))
