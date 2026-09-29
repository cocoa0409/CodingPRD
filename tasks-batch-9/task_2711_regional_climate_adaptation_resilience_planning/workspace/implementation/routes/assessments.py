"""PRD 3.3 -- vulnerability assessment across receptor classes."""

from flask import Blueprint

import calc
import envelope
import lookup
import serialize
import store
import validate
from auth import ROLE_HAZARD_ANALYST, guard
from core import clock
from errors import fail

bp = Blueprint("assessments", __name__)

SUBJECT_TYPES = ("INFRASTRUCTURE", "POPULATION", "ECONOMIC_SECTOR")
METHODS = ("COMPOSITE_MULTIPLICATIVE", "ADDITIVE_WEIGHTED")
PENDING_STATUSES = ("DRAFT", "STALE")


@bp.post("/resilience/vulnerability-assessments")
@guard(ROLE_HAZARD_ANALYST)
def create_assessment():
    body = validate.json_body()
    profile = lookup.need_ref("hazard_profile", body, "hazard_profile_id")
    if profile is None:
        validate.bad("hazard_profile_id", "is required.")
    asset = lookup.need_ref("asset", body, "asset_id")
    if asset is None:
        validate.bad("asset_id", "is required.")

    subject_type = validate.enum_field(body, "subject_type", SUBJECT_TYPES, required=True)
    sensitivity = validate.dec_field(
        body, "sensitivity_score", required=True, minimum=0, maximum=1
    )
    adaptive = validate.dec_field(
        body, "adaptive_capacity_score", required=True, minimum=0, maximum=1
    )
    method = validate.enum_field(body, "method", METHODS, required=True)
    overlay = validate.bool_field(body, "svi_overlay_applied", default=True)

    record = store.insert(store.assessments, {
        "hazard_profile_id": profile["id"],
        "asset_id": asset["id"],
        "subject_type": subject_type,
        "sensitivity_score": sensitivity,
        "adaptive_capacity_score": adaptive,
        "method": method,
        "svi_overlay_applied": overlay,
        "vulnerability_score": None,
        "vulnerability_band": None,
        "status": "DRAFT",
        "assessed_at": None,
        "assessed_profile_version": None,
    })
    return envelope.created(serialize.assessment(record))


@bp.get("/resilience/vulnerability-assessments")
@guard()
def list_assessments():
    rows = envelope.match(
        store.ordered(store.assessments),
        hazard_profile_id=envelope.str_filter("hazard_profile_id"),
        asset_id=envelope.str_filter("asset_id"),
        subject_type=envelope.str_filter("subject_type"),
        method=envelope.str_filter("method"),
        status=envelope.str_filter("status"),
    )
    return envelope.listing(rows, serialize.assessment)


@bp.get("/resilience/vulnerability-assessments/<assessment_id>")
@guard()
def get_assessment(assessment_id):
    row = lookup.need("assessment", assessment_id)
    return envelope.ok(serialize.assessment(row))


@bp.post("/resilience/vulnerability-assessments/<assessment_id>/assess")
@guard(ROLE_HAZARD_ANALYST)
def assess(assessment_id):
    assessment = lookup.need("assessment", assessment_id)
    profile = store.hazard_profiles.get(assessment["hazard_profile_id"])
    # the publication check runs FIRST, so a re-assess against a superseded profile
    # is told about the profile and not about the row
    if profile is None or profile["status"] != "PUBLISHED":
        fail(
            "ERR_HAZARD_PROFILE_NOT_PUBLISHED",
            "The referenced hazard projection is not PUBLISHED.",
        )
    if assessment["status"] not in PENDING_STATUSES:
        fail("ERR_ASSESSMENT_NOT_PENDING", "The assessment is not DRAFT or STALE.")

    asset = store.assets.get(assessment["asset_id"])
    owner = store.jurisdictions.get(asset["jurisdiction_id"]) if asset else None
    owner_tier = owner["svi_tier"] if owner else "LOW"

    score, band = calc.vulnerability(
        assessment["method"],
        profile["exposure_index"],
        assessment["sensitivity_score"],
        assessment["adaptive_capacity_score"],
        assessment["svi_overlay_applied"],
        owner_tier,
        assessment["subject_type"],
    )
    assessment["vulnerability_score"] = score
    assessment["vulnerability_band"] = band
    assessment["status"] = "ASSESSED"
    assessment["assessed_at"] = clock.now()
    assessment["assessed_profile_version"] = profile["published_version"]
    store.touch(assessment)
    return envelope.ok(serialize.assessment(assessment))
