"""CrisisAssessment routes (mounted under /practice/patients/{pid}/crisis-assessments)."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from flask import Blueprint

from ..auth import require_roles
from ..clock import now
from ..errors import (
    err_forbidden,
    err_not_found,
    err_reference_not_found,
    err_validation,
)
from ..helpers import (
    assert_integer,
    assert_string,
    new_uuid,
    paginate,
    parse_pagination,
    require_json_object,
)
from ..responses import created, listing
from ..services.calculations import (
    crisis_composite_score,
    crisis_risk_bucket,
)
from ..services.cascades import (
    bump,
    hold_future_for_patient_safety,
)
from ..services.serialize import serialize_crisis_assessment
from ..store import store

bp = Blueprint("crisis_assessments", __name__, url_prefix="/practice/patients")


@bp.post("/<pid>/crisis-assessments")
@require_roles("Therapist")
def create_assessment(pid: str, _caller_id: str, _caller_role: str, **_):
    body = require_json_object()
    s = store()
    with s.lock:
        if pid not in s.patients:
            raise err_not_found("Patient not found")
        therapist_id = assert_string(body.get("therapist_id"), "therapist_id")
        if therapist_id not in s.therapists:
            raise err_reference_not_found("therapist_id does not resolve")
        # Therapist may only finalize assessments under their own identity.
        if _caller_id != therapist_id:
            raise err_forbidden("Therapist may only finalize crisis assessments for themselves")

        si = assert_integer(body.get("si_score"), "si_score", minimum=0, maximum=4)
        pa = assert_integer(body.get("pa_score"), "pa_score", minimum=0, maximum=3)
        su = assert_integer(body.get("su_score"), "su_score", minimum=0, maximum=2)
        so = assert_integer(body.get("so_score"), "so_score", minimum=0, maximum=2)
        am = assert_integer(body.get("am_score"), "am_score", minimum=0, maximum=2)

        composite = crisis_composite_score(si, pa, su, so, am)
        risk = crisis_risk_bucket(composite)

        ts = now()
        aid = new_uuid()
        row: dict[str, Any] = {
            "id": aid,
            "patient_id": pid,
            "therapist_id": therapist_id,
            "si_score": si,
            "pa_score": pa,
            "su_score": su,
            "so_score": so,
            "am_score": am,
            "composite_score": composite,
            "risk_level": risk,
            "status": "FINALIZED",
            "assessed_at": ts,
            "created_at": ts,
        }
        s.crisis_assessments[aid] = row

        # Side effects on patient.
        patient = s.patients[pid]
        patient["latest_crisis_level"] = risk
        # Determine whether an active safety plan exists.
        has_active_plan = any(
            p["patient_id"] == pid and p["status"] == "ACTIVE"
            for p in s.safety_plans.values()
        )
        if risk == "HIGH" and not has_active_plan:
            if not patient["safety_plan_required"]:
                patient["safety_plan_required"] = True
                hold_future_for_patient_safety(s, pid)
        bump(patient)

        return created(serialize_crisis_assessment(row))


@bp.get("/<pid>/crisis-assessments")
@require_roles("Therapist", "PracticeAdmin")
def list_assessments(pid: str, **_):
    s = store()
    if pid not in s.patients:
        raise err_not_found("Patient not found")
    limit, offset = parse_pagination()
    rows = [r for r in s.crisis_assessments.values() if r["patient_id"] == pid]
    rows.sort(key=lambda r: r["created_at"])
    return listing([serialize_crisis_assessment(r) for r in paginate(rows, limit, offset)],
                   total_count=len(rows), limit=limit, offset=offset)
