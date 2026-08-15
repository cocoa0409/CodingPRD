"""Regulatory sweep routes: open, read (lazy escalation), evidence collection,
respond (deadline-toothed), escalate, close."""
from flask import Blueprint, request

from db import store, new_id, now_iso, touch
from clock import get_now
from errors import ApiError
from response import ok, ok_list
from services.consent import (
    parse_dt,
    fmt_dt,
    add_days,
    check_role,
    check_read_role,
    pagination_args,
    sort_created,
)
from services.sweep import escalate_sweep, recompute_posture
from services.expiry import evaluate_time_based_effects

bp = Blueprint("sweeps", __name__)
blueprint = bp


def _body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _get_sweep_or_404(sweep_id):
    sweep = store["regulatory_sweeps"].get(sweep_id)
    if sweep is None:
        raise ApiError("ERR_SWEEP_NOT_FOUND", "RegulatorySweep not found", 404)
    return sweep


# ---------------------------------------------------------------------------
# POST /v1/regulatory-sweeps — open a sweep (ComplianceAuditor)
# ---------------------------------------------------------------------------


@bp.post("/v1/regulatory-sweeps")
def create_sweep():
    check_role("ComplianceAuditor")
    body = _body()
    property_id = body.get("property_id")
    if not isinstance(property_id, str) or not property_id:
        raise ApiError("ERR_INVALID_REQUEST", "property_id is required", 400)
    regulator_ref = body.get("regulator_ref")
    if not isinstance(regulator_ref, str) or not regulator_ref:
        raise ApiError("ERR_INVALID_REQUEST", "regulator_ref is required", 400)
    jurisdiction_code = body.get("jurisdiction_code")
    if not isinstance(jurisdiction_code, str) or not jurisdiction_code:
        raise ApiError("ERR_INVALID_REQUEST", "jurisdiction_code is required", 400)
    deadline_days = body.get("deadline_days")
    if (
        isinstance(deadline_days, bool)
        or not isinstance(deadline_days, int)
        or deadline_days <= 0
    ):
        raise ApiError(
            "ERR_INVALID_REQUEST", "deadline_days must be an integer > 0", 400
        )
    if property_id not in store["properties"]:
        raise ApiError("ERR_PROPERTY_NOT_FOUND", "Property not found", 404)

    now = now_iso()
    sweep = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "property_id": property_id,
        "regulator_ref": regulator_ref,
        "jurisdiction_code": jurisdiction_code,
        "deadline_days": deadline_days,
        "response_due_at": fmt_dt(add_days(parse_dt(now), deadline_days)),
        "status": "OPEN",
        "escalated_at": None,
        "penalty_exposure_cents": None,
    }
    store["regulatory_sweeps"][sweep["id"]] = sweep
    return ok(sweep, status=201)


# ---------------------------------------------------------------------------
# Reads (lazy deadline escalation first)
# ---------------------------------------------------------------------------


@bp.get("/v1/regulatory-sweeps")
def list_sweeps():
    check_read_role()
    evaluate_time_based_effects()
    limit, offset = pagination_args()
    items = list(store["regulatory_sweeps"].values())
    property_id = request.args.get("property_id")
    if property_id is not None:
        items = [s for s in items if s.get("property_id") == property_id]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s.get("status") == status]
    items = sort_created(items)
    total = len(items)
    return ok_list(items[offset : offset + limit], total, limit, offset)


@bp.get("/v1/regulatory-sweeps/<sweep_id>")
def get_sweep(sweep_id):
    check_read_role()
    evaluate_time_based_effects()
    return ok(_get_sweep_or_404(sweep_id))


# ---------------------------------------------------------------------------
# POST /v1/regulatory-sweeps/{id}/begin-evidence-collection (ComplianceAuditor)
# ---------------------------------------------------------------------------


@bp.post("/v1/regulatory-sweeps/<sweep_id>/begin-evidence-collection")
def begin_evidence_collection(sweep_id):
    check_role("ComplianceAuditor")
    sweep = _get_sweep_or_404(sweep_id)
    evaluate_time_based_effects()
    if sweep.get("status") != "OPEN":
        raise ApiError(
            "ERR_SWEEP_INVALID_STATE",
            "Begin evidence collection requires the sweep to be OPEN",
            409,
        )
    sweep["status"] = "EVIDENCE_COLLECTION"
    touch(sweep)
    return ok(sweep)


# ---------------------------------------------------------------------------
# POST /v1/regulatory-sweeps/{id}/respond (PrivacyAdmin) — deadline-toothed
# ---------------------------------------------------------------------------


@bp.post("/v1/regulatory-sweeps/<sweep_id>/respond")
def respond_sweep(sweep_id):
    check_role("PrivacyAdmin")
    sweep = _get_sweep_or_404(sweep_id)
    due = parse_dt(sweep.get("response_due_at"))
    now = get_now()
    past_deadline = due is not None and now > due
    status = sweep.get("status")
    if status in ("OPEN", "EVIDENCE_COLLECTION"):
        if past_deadline:
            # late response: auto-escalate with the full cascade, then fail
            escalate_sweep(sweep)
            raise ApiError(
                "ERR_SWEEP_DEADLINE_PASSED",
                "Respond attempted after response_due_at; the sweep has auto-escalated",
                409,
            )
        sweep["status"] = "RESPONDED"
        touch(sweep)
        return ok(sweep)
    if status == "ESCALATED" and past_deadline:
        # The deadline already passed: lazy evaluation auto-escalated the sweep
        # before this handler ran; a late respond still fails DEADLINE_PASSED.
        raise ApiError(
            "ERR_SWEEP_DEADLINE_PASSED",
            "Respond attempted after response_due_at; the sweep has auto-escalated",
            409,
        )
    raise ApiError(
        "ERR_SWEEP_INVALID_STATE",
        "Respond requires the sweep to be OPEN or EVIDENCE_COLLECTION",
        409,
    )


# ---------------------------------------------------------------------------
# POST /v1/regulatory-sweeps/{id}/escalate (ComplianceAuditor)
# ---------------------------------------------------------------------------


@bp.post("/v1/regulatory-sweeps/<sweep_id>/escalate")
def escalate_sweep_endpoint(sweep_id):
    check_role("ComplianceAuditor")
    sweep = _get_sweep_or_404(sweep_id)
    evaluate_time_based_effects()
    if sweep.get("status") not in ("OPEN", "EVIDENCE_COLLECTION"):
        raise ApiError(
            "ERR_SWEEP_INVALID_STATE",
            "Escalate requires the sweep to be OPEN or EVIDENCE_COLLECTION",
            409,
        )
    escalate_sweep(sweep)
    return ok(sweep)


# ---------------------------------------------------------------------------
# POST /v1/regulatory-sweeps/{id}/close (PrivacyAdmin)
# ---------------------------------------------------------------------------


@bp.post("/v1/regulatory-sweeps/<sweep_id>/close")
def close_sweep(sweep_id):
    check_role("PrivacyAdmin")
    sweep = _get_sweep_or_404(sweep_id)
    evaluate_time_based_effects()
    if sweep.get("status") not in ("RESPONDED", "ESCALATED"):
        raise ApiError(
            "ERR_SWEEP_INVALID_STATE",
            "Close requires the sweep to be RESPONDED or ESCALATED",
            409,
        )
    sweep["status"] = "CLOSED"
    touch(sweep)
    # posture returns to NORMAL when no ESCALATED sweep remains on the property;
    # suppressed configs and disabled tag rules are NOT auto-restored
    recompute_posture(sweep.get("property_id"))
    return ok(sweep)
