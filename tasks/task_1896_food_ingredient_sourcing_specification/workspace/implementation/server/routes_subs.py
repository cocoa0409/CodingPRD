"""Substitution requests and formula impact assessment (PRD §3.8)."""
from decimal import Decimal

from flask import Blueprint, g, request

from .envelope import (
    ERR_CROSS_REFERENCE_MISMATCH,
    ERR_IMPACT_DELTA_EXCEEDS_THRESHOLD,
    ERR_INVALID_STATE,
    ERR_REGULATORY_SIGNOFF_NOT_REQUIRED,
    ERR_REGULATORY_SIGNOFF_REQUIRED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_SOURCE_NOT_ACTIVE,
    ERR_SPEC_NOT_EFFECTIVE,
    body,
    err,
    invalid,
    is_number,
    list_page,
    not_found,
    pagination_params,
    require_roles,
    require_str,
    respond_object,
)
from .services import (
    AUTO_APPROVE_MAX_ABS_DELTA,
    REASON_CODES,
    dec,
    recompute_dual_source,
    run_assessment,
)
from .store import STORE, new_record, ser_assessment, ser_substitution, touch

bp = Blueprint("substitutions", __name__)

READERS_NO_AUTHOR = (
    "ProcurementManager",
    "QualityManager",
    "SupplierQualityEngineer",
    "RegulatoryAffairs",
    "PlatformAdmin",
)


def get_ingredient_or_404(ingredient_id):
    ing = STORE.ingredients.get(ingredient_id)
    if ing is None:
        not_found("ingredient not found")
    return ing


def get_request_or_404(ingredient_id, request_id):
    rec = STORE.substitutions.get(request_id)
    if rec is None or rec["ingredient_id"] != ingredient_id:
        not_found("substitution request not found")
    return rec


# ---------------------------------------------------------------------------
# Substitution requests
# ---------------------------------------------------------------------------

@bp.post("/sourcing/ingredients/<ingredient_id>/substitution-requests")
@require_roles("ProcurementManager")
def create_substitution(ingredient_id):
    ing = get_ingredient_or_404(ingredient_id)
    data = body()

    # Body-FK existence (4) then cross-reference coherence (5).
    from_id = data.get("from_approved_source_id")
    to_id = data.get("to_approved_source_id")
    from_src = None
    to_src = None
    if isinstance(from_id, str):
        from_src = STORE.sources.get(from_id)
        if from_src is None:
            not_found("from_approved_source_id does not reference an existing source")
    if isinstance(to_id, str):
        to_src = STORE.sources.get(to_id)
        if to_src is None:
            not_found("to_approved_source_id does not reference an existing source")
    for label, src in (("from_approved_source_id", from_src), ("to_approved_source_id", to_src)):
        if src is not None and src["ingredient_id"] != ing["id"]:
            err(ERR_CROSS_REFERENCE_MISMATCH, 422, f"{label} must belong to the path ingredient")

    # Basic request shape (23).
    if not isinstance(from_id, str) or from_id == "":
        invalid("from_approved_source_id is required")
    if not isinstance(to_id, str) or to_id == "":
        invalid("to_approved_source_id is required")
    reason = data.get("reason_code")
    if reason not in REASON_CODES:
        invalid("reason_code must be a valid reason code")
    sensitivities = data.get("formula_unit_cost_sensitivities")
    if not isinstance(sensitivities, list):
        invalid("formula_unit_cost_sensitivities is required and must be an array")
    for item in sensitivities:
        if not isinstance(item, dict) or not isinstance(item.get("parameter_name"), str):
            invalid("each sensitivity must carry parameter_name")
        if not is_number(item.get("cost_per_unit_delta")):
            invalid("each sensitivity must carry a numeric cost_per_unit_delta")

    rec = new_record()
    rec.update(
        {
            "ingredient_id": ing["id"],
            "from_approved_source_id": from_id,
            "to_approved_source_id": to_id,
            "reason_code": reason,
            "formula_unit_cost_sensitivities": sensitivities,
            "requested_by_user_id": g.user_id,
            "impact_delta_per_unit": None,
            "requires_regulatory_signoff": False,
            "status": "REQUESTED",
            "_regulatory_signoff": False,
        }
    )
    STORE.substitutions[rec["id"]] = rec
    return respond_object(ser_substitution(rec), 201)


@bp.get("/sourcing/ingredients/<ingredient_id>/substitution-requests")
@require_roles(*READERS_NO_AUTHOR)
def list_substitutions(ingredient_id):
    get_ingredient_or_404(ingredient_id)
    limit, offset = pagination_params()
    status = request.args.get("status")
    rows = [r for r in STORE.substitutions.values() if r["ingredient_id"] == ingredient_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_page(rows, ser_substitution, limit, offset)


@bp.post("/sourcing/ingredients/<ingredient_id>/substitution-requests/<request_id>/assess")
@require_roles("SupplierQualityEngineer")
def assess_substitution(ingredient_id, request_id):
    get_ingredient_or_404(ingredient_id)
    rec = get_request_or_404(ingredient_id, request_id)
    if rec["status"] != "REQUESTED":
        err(ERR_INVALID_STATE, 409, "substitution request is not REQUESTED")
    if rec["from_approved_source_id"] == rec["to_approved_source_id"]:
        invalid("from_approved_source_id and to_approved_source_id must differ")
    to_src = STORE.sources.get(rec["to_approved_source_id"])
    if to_src is None or to_src["status"] != "ACTIVE":
        err(ERR_SOURCE_NOT_ACTIVE, 409, "to-source is not ACTIVE")
    to_spec = STORE.specs.get(to_src["pinned_spec_id"])
    if to_spec is None or to_spec["status"] != "EFFECTIVE":
        err(ERR_SPEC_NOT_EFFECTIVE, 409, "to-source pinned spec is not EFFECTIVE")
    run_assessment(rec)
    return respond_object(ser_substitution(rec))


def _assessment_of(request_id):
    for a in STORE.assessments.values():
        if a["substitution_request_id"] == request_id:
            return a
    return None


@bp.get("/sourcing/ingredients/<ingredient_id>/substitution-requests/<request_id>/assessment")
@require_roles(*READERS_NO_AUTHOR)
def get_assessment_nested(ingredient_id, request_id):
    get_ingredient_or_404(ingredient_id)
    rec = get_request_or_404(ingredient_id, request_id)
    limit, offset = pagination_params()
    rows = []
    assessment = _assessment_of(rec["id"])
    if assessment is not None:
        rows = [assessment]
    return list_page(rows, ser_assessment, limit, offset)


@bp.post("/sourcing/ingredients/<ingredient_id>/substitution-requests/<request_id>/route-regulatory")
@require_roles("SupplierQualityEngineer")
def route_regulatory(ingredient_id, request_id):
    get_ingredient_or_404(ingredient_id)
    rec = get_request_or_404(ingredient_id, request_id)
    if rec["status"] != "IMPACT_ASSESSED":
        err(ERR_INVALID_STATE, 409, "substitution request is not IMPACT_ASSESSED")
    if rec["requires_regulatory_signoff"] is not True:
        err(
            ERR_REGULATORY_SIGNOFF_NOT_REQUIRED,
            422,
            "request does not require regulatory sign-off",
        )
    rec["status"] = "PENDING_REGULATORY"
    touch(rec)
    return respond_object(ser_substitution(rec))


@bp.post("/sourcing/ingredients/<ingredient_id>/substitution-requests/<request_id>/regulatory-signoff")
@require_roles("RegulatoryAffairs")
def regulatory_signoff(ingredient_id, request_id):
    get_ingredient_or_404(ingredient_id)
    rec = get_request_or_404(ingredient_id, request_id)
    if rec["status"] != "PENDING_REGULATORY":
        err(ERR_INVALID_STATE, 409, "substitution request is not PENDING_REGULATORY")
    data = body()
    note = data.get("signoff_note")
    if not isinstance(note, str) or note == "":
        invalid("signoff_note is required")
    rec["_regulatory_signoff"] = True
    touch(rec)
    return respond_object(ser_substitution(rec))


@bp.post("/sourcing/ingredients/<ingredient_id>/substitution-requests/<request_id>/approve")
@require_roles("QualityManager")
def approve_substitution(ingredient_id, request_id):
    get_ingredient_or_404(ingredient_id)
    rec = get_request_or_404(ingredient_id, request_id)
    if rec["status"] not in ("IMPACT_ASSESSED", "PENDING_REGULATORY"):
        err(ERR_INVALID_STATE, 409, "substitution request is not approvable")
    if g.user_id == rec["requested_by_user_id"]:
        err(ERR_SEGREGATION_OF_DUTIES, 403, "requester cannot approve own request")
    if rec["status"] == "IMPACT_ASSESSED":
        # Fiscal gate (19) precedes the sign-off presence gate (20).
        delta = rec["impact_delta_per_unit"]
        if delta is not None and abs(dec(delta)) > AUTO_APPROVE_MAX_ABS_DELTA:
            err(
                ERR_IMPACT_DELTA_EXCEEDS_THRESHOLD,
                422,
                "|impact_delta_per_unit| exceeds 0.5000; route via PENDING_REGULATORY",
            )
        if rec["requires_regulatory_signoff"] is True:
            err(ERR_REGULATORY_SIGNOFF_REQUIRED, 422, "regulatory sign-off is required")
    else:  # PENDING_REGULATORY
        if rec.get("_regulatory_signoff") is not True:
            err(ERR_REGULATORY_SIGNOFF_REQUIRED, 422, "regulatory sign-off has not been recorded")
    rec["status"] = "APPROVED"
    touch(rec)
    return respond_object(ser_substitution(rec))


@bp.post("/sourcing/ingredients/<ingredient_id>/substitution-requests/<request_id>/reject")
@require_roles("QualityManager")
def reject_substitution(ingredient_id, request_id):
    get_ingredient_or_404(ingredient_id)
    rec = get_request_or_404(ingredient_id, request_id)
    if rec["status"] not in ("IMPACT_ASSESSED", "PENDING_REGULATORY"):
        err(ERR_INVALID_STATE, 409, "substitution request is not rejectable")
    if g.user_id == rec["requested_by_user_id"]:
        err(ERR_SEGREGATION_OF_DUTIES, 403, "requester cannot reject own request")
    rec["status"] = "REJECTED"
    touch(rec)
    return respond_object(ser_substitution(rec))


@bp.post("/sourcing/ingredients/<ingredient_id>/substitution-requests/<request_id>/execute")
@require_roles("ProcurementManager")
def execute_substitution(ingredient_id, request_id):
    ing = get_ingredient_or_404(ingredient_id)
    rec = get_request_or_404(ingredient_id, request_id)
    if rec["status"] != "APPROVED":
        err(ERR_INVALID_STATE, 409, "substitution request is not APPROVED")
    to_src = STORE.sources.get(rec["to_approved_source_id"])
    if to_src is None or to_src["status"] != "ACTIVE":
        err(ERR_SOURCE_NOT_ACTIVE, 409, "to-source is not ACTIVE")
    from_src = STORE.sources.get(rec["from_approved_source_id"])
    if from_src is not None and from_src["status"] == "ACTIVE":
        from_src["status"] = "SUSPENDED"
        from_src["suspension_reason"] = "MANUAL"
        touch(from_src)
    rec["status"] = "EXECUTED"
    touch(rec)
    recompute_dual_source(ing)
    return respond_object(ser_substitution(rec))


@bp.post("/sourcing/ingredients/<ingredient_id>/substitution-requests/<request_id>/cancel")
@require_roles("ProcurementManager")
def cancel_substitution(ingredient_id, request_id):
    get_ingredient_or_404(ingredient_id)
    rec = get_request_or_404(ingredient_id, request_id)
    if rec["status"] not in ("REQUESTED", "IMPACT_ASSESSED", "PENDING_REGULATORY"):
        err(ERR_INVALID_STATE, 409, "substitution request cannot be cancelled")
    if g.user_id != rec["requested_by_user_id"]:
        err(ERR_SEGREGATION_OF_DUTIES, 403, "only the requester may cancel the request")
    rec["status"] = "CANCELLED"
    touch(rec)
    return respond_object(ser_substitution(rec))


# ---------------------------------------------------------------------------
# Reverse-lookup lists
# ---------------------------------------------------------------------------

@bp.get("/sourcing/approved-sources/<source_id>/substitution-requests")
@require_roles(*READERS_NO_AUTHOR)
def list_substitutions_by_source(source_id):
    if STORE.sources.get(source_id) is None:
        not_found("approved source not found")
    limit, offset = pagination_params()
    status = request.args.get("status")
    rows = [
        r
        for r in STORE.substitutions.values()
        if r["from_approved_source_id"] == source_id or r["to_approved_source_id"] == source_id
    ]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_page(rows, ser_substitution, limit, offset)


@bp.get("/sourcing/substitution-requests/<request_id>")
@require_roles(*READERS_NO_AUTHOR)
def get_substitution_flat(request_id):
    rec = STORE.substitutions.get(request_id)
    if rec is None:
        not_found("substitution request not found")
    return respond_object(ser_substitution(rec))


@bp.get("/sourcing/substitution-requests/<request_id>/assessment")
@require_roles(*READERS_NO_AUTHOR)
def get_assessment_flat(request_id):
    rec = STORE.substitutions.get(request_id)
    if rec is None:
        not_found("substitution request not found")
    limit, offset = pagination_params()
    rows = []
    assessment = _assessment_of(rec["id"])
    if assessment is not None:
        rows = [assessment]
    return list_page(rows, ser_assessment, limit, offset)
