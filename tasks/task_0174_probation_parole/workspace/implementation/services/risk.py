"""Risk-assessment creation and adoption cascade (PRD §3.2)."""
import db
from calculations import (
    LSI_R_DOMAINS,
    LEVEL_ORDER,
    effective_level,
    level_ge,
    lsi_r_derived_level,
    lsi_r_total,
)
from errors import (
    ApiError,
    ERR_INCOMPLETE_LSIR_DOMAINS,
    ERR_INVALID_OVERRIDE,
    ERR_INVALID_STATE,
)

LEVELS = set(LEVEL_ORDER.keys())


def validate_domain_scores(domain_scores):
    """ERR_INCOMPLETE_LSIR_DOMAINS (422): exactly the ten keys, each value >= 0
    and integer."""
    if not isinstance(domain_scores, dict):
        raise ApiError(*ERR_INCOMPLETE_LSIR_DOMAINS, "domain_scores must be an object.")
    if set(domain_scores.keys()) != set(LSI_R_DOMAINS):
        raise ApiError(*ERR_INCOMPLETE_LSIR_DOMAINS, "domain_scores must contain exactly the ten LSI-R domains.")
    for d in LSI_R_DOMAINS:
        v = domain_scores[d]
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise ApiError(*ERR_INCOMPLETE_LSIR_DOMAINS, "domain sub-scores must be non-negative integers.")


def validate_override(override_level, override_reason, derived_level):
    """ERR_INVALID_OVERRIDE (422): override may only raise; reason required."""
    if override_level is None:
        return
    if override_level not in LEVELS:
        # Invalid enum -> ERR_INVALID_REQUEST handled by caller; here treat as override error per priority.
        raise ApiError(*ERR_INVALID_OVERRIDE, "override_level is not a valid level.")
    if not level_ge(override_level, derived_level):
        raise ApiError(*ERR_INVALID_OVERRIDE, "override_level may only raise, not lower.")
    if not override_reason or not isinstance(override_reason, str):
        raise ApiError(*ERR_INVALID_OVERRIDE, "override_reason is required when override_level is supplied.")


def compute_preview(domain_scores, override_level, override_reason):
    """Compute (total_score, derived_level) and validate override at create time."""
    total = lsi_r_total(domain_scores)
    derived = lsi_r_derived_level(total)
    validate_override(override_level, override_reason, derived)
    return total, derived


def adopt(supervisee, assessment):
    """Adopt a DRAFT assessment, recompute posture, run the cascade (PRD §3.2)."""
    if assessment["assessment_status"] != "DRAFT":
        raise ApiError(*ERR_INVALID_STATE, "Assessment is not DRAFT.")
    if supervisee["status"] not in ("INTAKE", "ACTIVE", "ABSCONDED"):
        raise ApiError(*ERR_INVALID_STATE, "Supervisee status does not permit adoption.")

    # Recompute total_score and derived_level from domain_scores at adoption.
    total = lsi_r_total(assessment["domain_scores"])
    derived = lsi_r_derived_level(total)
    assessment["total_score"] = total
    assessment["derived_level"] = derived

    # Supersede any other ADOPTED assessment for the same supervisee (depth-1).
    for ra in db.risk_assessments.values():
        if (
            ra["id"] != assessment["id"]
            and ra.get("supervisee_id") == supervisee["id"]
            and ra["assessment_status"] == "ADOPTED"
        ):
            ra["assessment_status"] = "SUPERSEDED"
            db.touch(ra)

    # Recompute supervisee.supervision_level from THIS assessment's effective
    # level (override if set, else derived) — depth-2 bubble to root posture.
    new_level = effective_level(derived, assessment.get("override_level"))
    supervisee["supervision_level"] = new_level

    # Force-suspend ACTIVE conditions whose minimum_level_required now exceeds
    # the new supervision level (depth-3 cascade down).
    for c in db.conditions.values():
        if c.get("supervisee_id") != supervisee["id"]:
            continue
        if c["status"] == "ACTIVE" and not level_ge(new_level, c["minimum_level_required"]):
            c["status"] = "SUSPENDED"
            db.touch(c)

    assessment["assessment_status"] = "ADOPTED"
    db.touch(assessment)
    db.touch(supervisee)
    return assessment
