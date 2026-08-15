"""RiskAssessment endpoints (PRD 3.1): OCC-guarded creation, pinned dual-variant
scoring, finalize with entity ledger sync."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_AUDITABLE_ENTITY_RETIRED,
    ERR_RISK_ASSESSMENT_ALREADY_FINALIZED,
    ERR_RISK_ASSESSMENT_DRAFT_EXISTS,
    ERR_RISK_ASSESSMENT_INVALID_STATE,
    ERR_STALE_ENTITY_VERSION,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, query_int, query_str
from services.calculations import compute_risk_score
from services.cascades import sync_entity_risk_on_finalize
from services.core import new_record, public, touch
from util import CLOCK
from validate import (
    body_ref,
    check_score_range,
    check_unknown_fields,
    get_body,
    req_int,
    req_str,
    require_path,
)

bp = Blueprint("risk_assessments", __name__)

CREATE_FIELDS = {
    "auditable_entity_id", "fiscal_year", "likelihood", "impact",
    "expected_auditable_entity_version",
}


@bp.post("/audit/risk-assessments")
def create_assessment():
    caller = authorized(["AuditManager"])
    body = get_body()
    # Stage 4: body FK existence (declared input order)
    body_ref(body, "auditable_entity_id", "auditable_entities")
    # Stage 5: shape, then score ranges
    check_unknown_fields(body, CREATE_FIELDS)
    entity_id = req_str(body, "auditable_entity_id")
    fiscal_year = req_int(body, "fiscal_year")
    likelihood = req_int(body, "likelihood")
    impact = req_int(body, "impact")
    expected_version = req_int(body, "expected_auditable_entity_version")
    check_score_range(likelihood, "likelihood")
    check_score_range(impact, "impact")
    entity = db["auditable_entities"][entity_id]
    # Stage 6: OCC on the parent entity version
    if expected_version != entity["version"]:
        raise_error(ERR_STALE_ENTITY_VERSION,
                    f"expected_auditable_entity_version {expected_version} != current {entity['version']}")
    # Stage 9: (entity, fiscal_year) uniqueness — DRAFT first, then FINALIZED
    for ra in db["risk_assessments"].values():
        if ra["auditable_entity_id"] == entity_id and ra["fiscal_year"] == fiscal_year:
            if ra["status"] == "DRAFT":
                raise_error(ERR_RISK_ASSESSMENT_DRAFT_EXISTS,
                            "a DRAFT assessment already exists for this entity and fiscal year")
            if ra["status"] == "FINALIZED":
                raise_error(ERR_RISK_ASSESSMENT_ALREADY_FINALIZED,
                            "a FINALIZED assessment already exists for this entity and fiscal year")
    # Stage 11: entity must be ACTIVE
    if entity["status"] != "ACTIVE":
        raise_error(ERR_AUDITABLE_ENTITY_RETIRED, "entity is RETIRED")
    variant, score = compute_risk_score(likelihood, impact, entity["regulatory_scrutiny"])
    rec = new_record("risk_assessments", {
        "auditable_entity_id": entity_id,
        "fiscal_year": fiscal_year,
        "likelihood": likelihood,
        "impact": impact,
        "scoring_variant": variant,
        "inherent_risk_score": score,
        "status": "DRAFT",
        "finalized_at": None,
    })
    # Creation mutates the entity (version advances) — PRD 3.1
    touch(entity)
    return success_object(public(rec), status=201)


@bp.get("/audit/risk-assessments")
def list_assessments():
    filters = {
        "auditable_entity_id": query_str("auditable_entity_id"),
        "fiscal_year": query_int("fiscal_year"),
        "status": query_str("status"),
    }
    return list_response("risk_assessments", filters)


@bp.get("/audit/risk-assessments/<rid>")
def get_assessment(rid):
    return get_one("risk_assessments", rid)


@bp.post("/audit/risk-assessments/<rid>/finalize")
def finalize_assessment(rid):
    authorized(["AuditManager"])
    ra = require_path("risk_assessments", rid)
    # Stage 7: must be DRAFT
    if ra["status"] != "DRAFT":
        raise_error(ERR_RISK_ASSESSMENT_INVALID_STATE, "assessment is not DRAFT")
    # Stage 9: no other FINALIZED assessment for the same (entity, fiscal_year)
    for other in db["risk_assessments"].values():
        if (other["id"] != ra["id"]
                and other["auditable_entity_id"] == ra["auditable_entity_id"]
                and other["fiscal_year"] == ra["fiscal_year"]
                and other["status"] == "FINALIZED"):
            raise_error(ERR_RISK_ASSESSMENT_ALREADY_FINALIZED,
                        "another FINALIZED assessment exists for this entity and fiscal year")
    ra["status"] = "FINALIZED"
    ra["finalized_at"] = CLOCK.now_iso()
    touch(ra)
    sync_entity_risk_on_finalize(ra)
    return success_object(public(ra))
