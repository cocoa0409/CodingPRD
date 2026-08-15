"""ExperienceRatingModel endpoints: create (computes the projection
immediately), get, and finalize with the three guards and employer OCC."""
from flask import Blueprint

from db import STORE
from errors import (
    err,
    ERR_CROSS_PARENT_REFERENCE,
    ERR_MODEL_INPUT_STALE,
    ERR_MODEL_NOT_DRAFT,
    ERR_MODEL_VARIANT_MISMATCH,
    ERR_STALE_VERSION,
)
from middleware import require_roles
from response import success
from services.core import find_or_404, new_record, serialize, sorted_created, touch
from services.rating import project, refresh_current_rate, snapshot_hash
from util import as_int, as_str, body_json, check_enum, req

bp = Blueprint("models", __name__)

VARIANTS = ("RESERVE_RATIO", "BENEFIT_RATIO")
KINDS = ("OFFICIAL", "WHAT_IF")


@bp.post("/ui/employers/<eid>/experience-rating-models")
def create_model(eid):
    require_roles("RatingAnalyst")
    body = body_json()
    model_year = as_int(req(body, "model_year"), "model_year")
    variant = check_enum(as_str(req(body, "variant"), "variant"), VARIANTS, "variant")
    kind = check_enum(as_str(req(body, "kind"), "kind"), KINDS, "kind")

    emp = find_or_404(STORE.employers, eid, "employer")
    rate, liability = project(emp, variant)
    rec = new_record({
        "employer_id": eid,
        "model_year": model_year,
        "variant": variant,
        "kind": kind,
        "projected_rate_bps": rate,
        "projected_liability_cents": liability,
        "input_snapshot_hash": snapshot_hash(emp, variant),
        "status": "DRAFT",
    })
    STORE.rating_models[rec["id"]] = rec
    # the projection's output refreshes the employer's current rate (§3.7)
    refresh_current_rate(emp)
    return success(serialize(rec), 201)


@bp.get("/ui/experience-rating-models/<rid>")
def get_model(rid):
    require_roles("PlatformAdmin", "RatingAnalyst")
    rec = find_or_404(STORE.rating_models, rid, "experience rating model")
    return success(serialize(rec))


@bp.post("/ui/employers/<eid>/experience-rating-models/<mid>/finalize")
def finalize_model(eid, mid):
    require_roles("RatingAnalyst")
    body = body_json()
    expected_employer_version = as_int(
        req(body, "expected_employer_version"), "expected_employer_version"
    )
    emp = find_or_404(STORE.employers, eid, "employer")
    model = find_or_404(STORE.rating_models, mid, "experience rating model")
    if model["employer_id"] != eid:
        raise err(
            ERR_CROSS_PARENT_REFERENCE,
            422,
            "model belongs to a different employer than the path scope",
        )
    # guard 1: the model must be DRAFT
    if model["status"] != "DRAFT":
        raise err(ERR_MODEL_NOT_DRAFT, 409, "model is not DRAFT")
    # guard 2: an OFFICIAL model's variant must match the employer's method
    if model["kind"] == "OFFICIAL" and model["variant"] != emp["merit_rating_method"]:
        raise err(ERR_MODEL_VARIANT_MISMATCH, 422, "OFFICIAL variant differs from employer merit_rating_method")
    # guard 3: stored snapshot must still match the current inputs
    if model["input_snapshot_hash"] != snapshot_hash(emp, model["variant"]):
        raise err(ERR_MODEL_INPUT_STALE, 409, "model inputs changed since computation")
    # OCC runs last so business errors surface first
    if expected_employer_version != emp["version"]:
        raise err(ERR_STALE_VERSION, 412, "expected_employer_version does not match the employer's current version")

    model["status"] = "FINALIZED"
    touch(model)
    # create-with-supersede: any prior FINALIZED OFFICIAL model for the same
    # employer+year is superseded, leaving exactly one
    if model["kind"] == "OFFICIAL":
        for other in STORE.rating_models.values():
            if (
                other["id"] != model["id"]
                and other["employer_id"] == eid
                and other["model_year"] == model["model_year"]
                and other["kind"] == "OFFICIAL"
                and other["status"] == "FINALIZED"
            ):
                other["status"] = "SUPERSEDED"
                touch(other)
    touch(emp)
    return success(serialize(model))
