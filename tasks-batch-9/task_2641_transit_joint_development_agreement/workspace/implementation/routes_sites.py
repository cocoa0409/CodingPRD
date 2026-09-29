"""Site inventory, readiness assessment, developer registration and valuation."""

from flask import Blueprint

import authz
import calc
import common
import enums
import envelope
import shape
import store
from errors import fail

bp = Blueprint("sites", __name__)


# ---------------------------------------------------------------- inventory ---
@bp.post("/jda/sites")
def create_site():
    authz.authorize("RealEstateOfficer")
    body = shape.body()
    site_code = shape.as_str(body, "site_code", min_len=1, max_len=32)
    name = shape.as_str(body, "name")
    address_line = shape.as_str(body, "address_line")
    parcel_area_sqft = shape.as_int(body, "parcel_area_sqft", minimum=1)
    funding = shape.as_enum(body, "acquisition_funding_source", enums.FUNDING_SOURCE)
    federal_pct = shape.as_num(body, "federal_interest_pct", minimum=0, maximum=100)
    transit_facility_present = shape.as_bool(body, "transit_facility_present",
                                             required=False, default=False)
    # A parcel bought entirely with local money cannot carry a federal claim.
    if funding == "LOCAL_ONLY" and calc.dec(federal_pct) != calc.D("0"):
        fail("ERR_INVALID_REQUEST",
             "federal_interest_pct must be exactly 0 when acquisition_funding_source is LOCAL_ONLY")
    for existing in store.all_of("site"):
        if existing["site_code"] == site_code:
            fail("ERR_DUPLICATE_SITE_CODE", "site_code %s already exists" % site_code)
    site = store.create("site", {
        "site_code": site_code,
        "name": name,
        "address_line": address_line,
        "parcel_area_sqft": parcel_area_sqft,
        "acquisition_funding_source": funding,
        "federal_interest_pct": federal_pct,
        "transit_facility_present": transit_facility_present,
        "status": "INVENTORIED",
        "readiness_composite_score": None,
        "readiness_tier": None,
        "federal_interest_basis_cents": 0,
        "federal_interest_encumbered_cents": 0,
        "federal_interest_unencumbered_cents": 0,
    })
    return envelope.created(common.public(site))


@bp.post("/jda/sites/<site_id>/release-for-solicitation")
def release_for_solicitation(site_id):
    authz.authorize("RealEstateOfficer")
    site = store.require("site", site_id)
    if site["status"] != "ASSESSED":
        fail("ERR_INVALID_SITE_STATE", "Site must be ASSESSED to be released for solicitation")
    if site["readiness_tier"] != "READY":
        fail("ERR_SITE_NOT_READY", "Site readiness tier must be READY")
    site["status"] = "SOLICITATION_READY"
    store.touch(site)
    return envelope.ok(common.public(site))


@bp.post("/jda/sites/<site_id>/reopen-inventory")
def reopen_inventory(site_id):
    authz.authorize("RealEstateOfficer")
    body = shape.body()
    reason = shape.as_str(body, "reason")
    site = store.require("site", site_id)
    if site["status"] not in ("ASSESSED", "SOLICITATION_READY"):
        fail("ERR_INVALID_SITE_STATE",
             "Site must be ASSESSED or SOLICITATION_READY to be reopened")
    for solicitation in common.solicitations_of(site_id):
        if solicitation["status"] == "ISSUED":
            fail("ERR_INVALID_SITE_STATE",
                 "The site has an ISSUED solicitation and cannot be reopened")
    site["readiness_composite_score"] = None
    site["readiness_tier"] = None
    for assessment in store.by_seq(common.assessments_of(site_id)):
        if assessment["status"] == "CERTIFIED":
            assessment["status"] = "SUPERSEDED"
            store.touch(assessment)
    for solicitation in store.by_seq(common.solicitations_of(site_id)):
        if solicitation["status"] == "DRAFT":
            solicitation["status"] = "CANCELLED"
            store.touch(solicitation)
    site["status"] = "INVENTORIED"
    site["_reopen_reason"] = reason
    store.touch(site)
    return envelope.ok(common.public(site))


# --------------------------------------------------------------- assessments ---
@bp.post("/jda/sites/<site_id>/assessments")
def create_assessment(site_id):
    authz.authorize("RealEstateOfficer")
    body = shape.body()
    environmental = shape.as_int(body, "environmental_score", minimum=0, maximum=100)
    utility = shape.as_int(body, "utility_score", minimum=0, maximum=100)
    access = shape.as_int(body, "access_score", minimum=0, maximum=100)
    entitlement = shape.as_int(body, "entitlement_score", minimum=0, maximum=100)
    encumbrance_count = shape.as_int(body, "encumbrance_count", minimum=0)
    notes = shape.as_str(body, "assessment_notes", required=False, default="")
    site = store.require("site", site_id)
    assessment = store.create("assessment", {
        "site_id": site_id,
        "environmental_score": environmental,
        "utility_score": utility,
        "access_score": access,
        "entitlement_score": entitlement,
        "encumbrance_count": encumbrance_count,
        "assessment_notes": notes,
        "composite_score": None,
        "variant_applied": "PRELIMINARY",
        "tier": None,
        "status": "DRAFT",
        "certified_at": None,
    })
    score, tier = calc.readiness_preliminary(assessment)
    assessment["composite_score"] = score
    assessment["tier"] = tier
    # Creating an assessment bumps the parent site's version even though nothing
    # about the site itself changed.
    store.touch(site)
    return envelope.created(common.public(assessment))


@bp.post("/jda/assessments/<assessment_id>/certify")
def certify_assessment(assessment_id):
    authz.authorize("RealEstateOfficer")
    assessment = store.require("assessment", assessment_id)
    site = store.require("site", assessment["site_id"])
    if site["status"] not in ("INVENTORIED", "ASSESSED"):
        fail("ERR_INVALID_SITE_STATE",
             "Site must be INVENTORIED or ASSESSED to certify an assessment")
    if assessment["status"] != "DRAFT":
        fail("ERR_ASSESSMENT_NOT_DRAFT", "Assessment is not in DRAFT")
    score, tier = calc.readiness_certified(assessment, site["federal_interest_pct"])
    assessment["composite_score"] = score
    assessment["tier"] = tier
    assessment["variant_applied"] = "CERTIFIED"
    assessment["status"] = "CERTIFIED"
    assessment["certified_at"] = store.now_iso()
    store.touch(assessment)
    common.supersede_other_certified(common.assessments_of(site["id"]), assessment["id"])
    site["readiness_composite_score"] = score
    site["readiness_tier"] = tier
    if site["status"] == "INVENTORIED":
        site["status"] = "ASSESSED"
    store.touch(site)
    return envelope.ok(common.public(assessment))


# ---------------------------------------------------------------- developers ---
@bp.post("/jda/developers")
def register_developer():
    authz.authorize("RealEstateOfficer")
    body = shape.body()
    legal_name = shape.as_str(body, "legal_name")
    contact_email = shape.as_str(body, "contact_email")
    prequalified = shape.as_bool(body, "prequalified", required=False, default=False)
    debarment_status = shape.as_enum(body, "debarment_status", enums.DEBARMENT_STATUS,
                                     required=False, default="CLEAR")
    developer = store.create("developer", {
        "legal_name": legal_name,
        "contact_email": contact_email,
        "prequalified": prequalified,
        "debarment_status": debarment_status,
    })
    return envelope.created(common.public(developer))


# ---------------------------------------------------------------- valuations ---
def _apply_floor(valuation, site):
    credit, federal_floor, floor = calc.permissible_floor(
        valuation["appraised_value_cents"], valuation["transit_supportive_use_pct"],
        valuation["affordable_units_pct"], valuation["transfer_basis"],
        site["federal_interest_pct"])
    valuation["transit_supportive_credit_cents"] = credit
    valuation["federal_interest_floor_cents"] = federal_floor
    valuation["permissible_floor_cents"] = floor


@bp.post("/jda/sites/<site_id>/valuations")
def create_valuation(site_id):
    authz.authorize("ValuationOfficer")
    body = shape.body()
    method = shape.as_enum(body, "method", enums.VALUATION_METHOD)
    appraised = shape.as_int(body, "appraised_value_cents", minimum=1)
    tsu_pct = shape.as_num(body, "transit_supportive_use_pct", minimum=0, maximum=100)
    affordable_pct = shape.as_num(body, "affordable_units_pct", minimum=0, maximum=100)
    transfer_basis = shape.as_enum(body, "transfer_basis", enums.TRANSFER_BASIS)
    effective_date = shape.as_date(body, "effective_date")
    expected_site_version = shape.as_int(body, "expected_site_version")
    site = store.require("site", site_id)
    # Optimistic concurrency on the parent site's version (PRD 2.10).
    if expected_site_version != site["version"]:
        fail("ERR_STALE_SITE_VERSION",
             "expected_site_version %s does not match the site's current version %s"
             % (expected_site_version, site["version"]))
    valuation = store.create("valuation", {
        "site_id": site_id,
        "method": method,
        "appraised_value_cents": appraised,
        "transit_supportive_use_pct": tsu_pct,
        "affordable_units_pct": affordable_pct,
        "transfer_basis": transfer_basis,
        "effective_date": effective_date,
        "transit_supportive_credit_cents": 0,
        "federal_interest_floor_cents": 0,
        "permissible_floor_cents": 0,
        "status": "DRAFT",
        "certified_at": None,
    })
    _apply_floor(valuation, site)
    common.pin_federal_basis(site, appraised)
    return envelope.created(common.public(valuation))


@bp.post("/jda/valuations/<valuation_id>/certify")
def certify_valuation(valuation_id):
    authz.authorize("ValuationOfficer")
    valuation = store.require("valuation", valuation_id)
    site = store.require("site", valuation["site_id"])
    if site["status"] not in ("ASSESSED", "SOLICITATION_READY", "UNDER_AGREEMENT"):
        fail("ERR_INVALID_SITE_STATE",
             "Site must be ASSESSED, SOLICITATION_READY or UNDER_AGREEMENT to certify a valuation")
    if valuation["status"] != "DRAFT":
        fail("ERR_VALUATION_NOT_CERTIFIED", "Valuation determination is not in DRAFT")
    valuation["status"] = "CERTIFIED"
    valuation["certified_at"] = store.now_iso()
    _apply_floor(valuation, site)
    store.touch(valuation)
    common.supersede_other_certified(common.valuations_of(site["id"]), valuation["id"])
    common.pin_federal_basis(site, valuation["appraised_value_cents"])
    return envelope.ok(common.public(valuation))
