"""Logical clock, parcels, mortgage liens, catalog products, contractors."""

from flask import Blueprint

import calc
import db
import response
import services
import validation as v
from errors import fail
from middleware import (
    ALL_ROLES,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_COUNTY_OFFICER,
    ROLE_PROGRAM_ADMIN,
    authorize,
)

bp = Blueprint("reference", __name__)


def _list(rows, limit, offset):
    window, total = response.paginate(rows, limit, offset)
    return response.listing([db.public(row) for row in window], limit, offset, total)


# ---------------------------------------------------------------- clock ------
@bp.post("/_clock/set_current_utc")
def set_clock():
    authorize([ROLE_PROGRAM_ADMIN])
    payload = v.body()
    raw = v.req_str(payload, "current_utc")
    instant = db.parse_instant(raw)
    if instant is None:
        fail("ERR_VALIDATION", "current_utc must be an ISO 8601 instant")
    previous = db.set_now(instant)
    return response.ok(
        {"current_utc": db.iso(instant), "previous_utc": db.iso(previous)}
    )


# ------------------------------------------------------------- properties ----
@bp.post("/pace/properties")
def create_property():
    authorize([ROLE_PROGRAM_ADMIN, ROLE_COUNTY_OFFICER])
    payload = v.body()
    apn = v.req_str(payload, "apn", min_len=1, max_len=32)
    county_code = v.req_enum(payload, "county_code", v.COUNTY_CODES)
    owner_full_name = v.req_str(payload, "owner_full_name")
    owner_birth_date = v.req_date(payload, "owner_birth_date")
    owner_email = v.req_str(payload, "owner_email")
    occupancy_type = v.req_enum(payload, "occupancy_type", v.OCCUPANCY_TYPES)
    assessed_value_cents = v.req_int(payload, "assessed_value_cents", minimum=1)
    annual_property_tax_cents = v.req_int(payload, "annual_property_tax_cents", minimum=0)
    preferred_language = v.opt_enum(payload, "preferred_language", v.LANGUAGES, "EN")
    market_value_cents = v.opt_int(payload, "market_value_cents", None, minimum=0)
    appraisal_effective_on = v.opt_date(payload, "appraisal_effective_on")
    tax_delinquency_count_36m = v.opt_int(
        payload, "tax_delinquency_count_36m", 0, minimum=0
    )
    in_bankruptcy = v.opt_bool(payload, "in_bankruptcy", False)
    if market_value_cents is not None and appraisal_effective_on is None:
        fail("ERR_VALIDATION", "market_value_cents requires appraisal_effective_on")
    for row in db.rows("properties"):
        if row["county_code"] == county_code and row["apn"] == apn:
            fail("ERR_VALIDATION", "apn must be unique within its county")
    prop = db.create(
        "properties",
        {
            "apn": apn,
            "county_code": county_code,
            "owner_full_name": owner_full_name,
            "owner_birth_date": owner_birth_date,
            "owner_email": owner_email,
            "preferred_language": preferred_language,
            "occupancy_type": occupancy_type,
            "assessed_value_cents": assessed_value_cents,
            "market_value_cents": market_value_cents,
            "appraisal_effective_on": appraisal_effective_on,
            "annual_property_tax_cents": annual_property_tax_cents,
            "tax_delinquency_count_36m": tax_delinquency_count_36m,
            "in_bankruptcy": in_bankruptcy,
            "senior_lien_balance_cents": 0,
            "equity_ratio_bps": 10000,
            "recorded_pace_principal_cents": 0,
            "committed_pace_principal_cents": 0,
        },
    )
    return response.created(db.public(prop))


@bp.get("/pace/properties/<row_id>")
def read_property(row_id):
    authorize(ALL_ROLES)
    return response.ok(db.public(services.get_property(row_id)))


@bp.patch("/pace/properties/<row_id>/valuation")
def patch_valuation(row_id):
    authorize([ROLE_PROGRAM_ADMIN, ROLE_COUNTY_OFFICER])
    payload = v.body()
    assessed_value_cents = v.opt_int(payload, "assessed_value_cents", None, minimum=1)
    market_value_cents = v.opt_int(payload, "market_value_cents", None, minimum=0)
    appraisal_effective_on = v.opt_date(payload, "appraisal_effective_on")
    if market_value_cents is not None and appraisal_effective_on is None:
        fail("ERR_VALIDATION", "market_value_cents requires appraisal_effective_on")
    prop = services.get_property(row_id)
    if assessed_value_cents is not None:
        prop["assessed_value_cents"] = assessed_value_cents
    if market_value_cents is not None:
        prop["market_value_cents"] = market_value_cents
    if appraisal_effective_on is not None:
        prop["appraisal_effective_on"] = appraisal_effective_on
    services.recompute_property_rollups(prop, bump=False)
    db.touch(prop)
    return response.ok(db.public(prop))


# ----------------------------------------------------------- mortgage liens --
@bp.post("/pace/mortgage-liens")
def create_lien():
    authorize([ROLE_PROGRAM_ADMIN, ROLE_COMPLIANCE_OFFICER])
    payload = v.body()
    property_id = v.req_id(payload, "property_id")
    holder_name = v.req_str(payload, "holder_name")
    lien_position = v.req_int(payload, "lien_position", minimum=1)
    current_balance_cents = v.req_int(payload, "current_balance_cents", minimum=0)
    recorded_on = v.req_date(payload, "recorded_on")
    status = v.opt_enum(payload, "status", v.LIEN_STATUSES, "ACTIVE")
    prop = services.get_property(property_id)
    if status == "ACTIVE":
        for row in services.active_liens_of(prop["id"]):
            if int(row["lien_position"]) == lien_position:
                fail(
                    "ERR_VALIDATION",
                    "lien_position must be unique among the parcel's ACTIVE liens",
                )
    lien = db.create(
        "liens",
        {
            "property_id": prop["id"],
            "holder_name": holder_name,
            "lien_position": lien_position,
            "current_balance_cents": current_balance_cents,
            "recorded_on": recorded_on,
            "status": status,
            "consent_application_id": None,
            "notified_at": None,
            "consent_deadline_at": None,
            "consent_response": "NOT_NOTIFIED",
            "consent_responded_at": None,
        },
    )
    services.recompute_property_rollups(prop)
    return response.created(db.public(lien))


@bp.get("/pace/mortgage-liens/<row_id>")
def read_lien(row_id):
    authorize(ALL_ROLES)
    return response.ok(db.public(services.get_lien(row_id)))


@bp.get("/pace/mortgage-liens")
def list_liens():
    authorize(ALL_ROLES)
    limit, offset = v.pagination()
    property_id = v.filter_value("property_id")
    consent_application_id = v.filter_value("consent_application_id")
    status = v.filter_value("status")
    consent_response = v.filter_value("consent_response")
    rows = db.by_created_at(db.rows("liens"))
    if property_id:
        rows = [row for row in rows if row["property_id"] == property_id]
    if consent_application_id:
        rows = [
            row for row in rows if row.get("consent_application_id") == consent_application_id
        ]
    if status:
        rows = [row for row in rows if row["status"] == status]
    if consent_response:
        rows = [row for row in rows if row["consent_response"] == consent_response]
    return _list(rows, limit, offset)


@bp.post("/pace/mortgage-liens/<row_id>/consent-response")
def lien_consent_response(row_id):
    authorize([ROLE_COMPLIANCE_OFFICER])
    payload = v.body()
    decision = v.req_enum(payload, "response", ("CONSENT", "DECLINE"))
    v.opt_str(payload, "note")
    lien = services.get_lien(row_id)
    application_id = lien.get("consent_application_id")
    if not application_id:
        fail("ERR_LIEN_NOT_NOTIFIED", "This lien has not been notified")
    application = db.get("applications", application_id)
    if application is None or application["status"] != "CONSENT_PENDING":
        fail("ERR_APPLICATION_STATE_INVALID", "Application is not CONSENT_PENDING")
    instant = db.now()
    lien["consent_response"] = "CONSENTED" if decision == "CONSENT" else "DECLINED"
    lien["consent_responded_at"] = db.iso(instant)
    db.touch(lien)
    if decision == "DECLINE":
        application["status"] = "DECLINED"
        application["decline_reason_code"] = "LENDER_DECLINED"
        application["consent_posture"] = "VETOED"
        db.touch(application)
        for measure in services.measures_of(application["id"]):
            if measure["status"] == "APPROVED":
                measure["status"] = "INELIGIBLE"
                db.touch(measure)
    else:
        posture = services.derive_consent_posture(application)
        if application["consent_posture"] != posture:
            application["consent_posture"] = posture
            db.touch(application)
    return response.ok(db.public(lien))


# ----------------------------------------------------------------- products --
@bp.post("/pace/products")
def create_product():
    authorize([ROLE_PROGRAM_ADMIN])
    payload = v.body()
    product_code = v.req_str(payload, "product_code")
    category = v.req_enum(payload, "category", v.PRODUCT_CATEGORIES)
    useful_life_years = v.req_int(payload, "useful_life_years", minimum=1, maximum=40)
    max_annual_savings_cents = v.req_int(payload, "max_annual_savings_cents", minimum=1)
    requires_permit = v.opt_bool(payload, "requires_permit", True)
    status = v.opt_enum(payload, "status", v.PRODUCT_STATUSES, "ACTIVE")
    for row in db.rows("products"):
        if row["product_code"] == product_code:
            fail("ERR_VALIDATION", "product_code must be unique across the catalog")
    product = db.create(
        "products",
        {
            "product_code": product_code,
            "category": category,
            "useful_life_years": useful_life_years,
            "max_annual_savings_cents": max_annual_savings_cents,
            "requires_permit": requires_permit,
            "status": status,
        },
    )
    return response.created(db.public(product))


@bp.get("/pace/products/<row_id>")
def read_product(row_id):
    authorize(ALL_ROLES)
    return response.ok(db.public(services.get_product(row_id)))


@bp.get("/pace/products")
def list_products():
    authorize(ALL_ROLES)
    limit, offset = v.pagination()
    category = v.filter_value("category")
    status = v.filter_value("status")
    rows = db.by_created_at(db.rows("products"))
    if category:
        rows = [row for row in rows if row["category"] == category]
    if status:
        rows = [row for row in rows if row["status"] == status]
    return _list(rows, limit, offset)


@bp.patch("/pace/products/<row_id>")
def patch_product(row_id):
    authorize([ROLE_PROGRAM_ADMIN])
    payload = v.body()
    status = v.req_enum(payload, "status", v.PRODUCT_STATUSES)
    product = services.get_product(row_id)
    product["status"] = status
    db.touch(product)
    return response.ok(db.public(product))


# -------------------------------------------------------------- contractors --
@bp.post("/pace/contractors")
def create_contractor():
    authorize([ROLE_PROGRAM_ADMIN])
    payload = v.body()
    legal_name = v.req_str(payload, "legal_name")
    license_number = v.req_str(payload, "license_number")
    license_expires_on = v.req_date(payload, "license_expires_on")
    workmanship_warranty_years = v.req_int(
        payload, "workmanship_warranty_years", minimum=0
    )
    counties_served = v.req_str_array(payload, "counties_served", allowed=v.COUNTY_CODES)
    for row in db.rows("contractors"):
        if row["license_number"] == license_number:
            fail("ERR_DUPLICATE_LICENSE_NUMBER", "license_number is already registered")
    contractor = db.create(
        "contractors",
        {
            "legal_name": legal_name,
            "license_number": license_number,
            "license_expires_on": license_expires_on,
            "workmanship_warranty_years": workmanship_warranty_years,
            "counties_served": counties_served,
            "enrollment_status": "PENDING_REVIEW",
            "workmanship_score": 10000,
            "lifetime_workmanship_score": 10000,
            "upheld_open_remedy_count": 0,
            "net_disbursed_cents": 0,
            "gross_disbursed_cents": 0,
            "clawed_back_total_cents": 0,
            "suspension_reason": None,
        },
    )
    return response.created(db.public(contractor))


@bp.get("/pace/contractors/<row_id>")
def read_contractor(row_id):
    authorize(ALL_ROLES)
    return response.ok(db.public(services.get_contractor(row_id)))


@bp.get("/pace/contractors")
def list_contractors():
    authorize(ALL_ROLES)
    limit, offset = v.pagination()
    enrollment_status = v.filter_value("enrollment_status")
    county_code = v.filter_value("county_code")
    rows = db.by_created_at(db.rows("contractors"))
    if enrollment_status:
        rows = [row for row in rows if row["enrollment_status"] == enrollment_status]
    if county_code:
        rows = [row for row in rows if county_code in (row["counties_served"] or [])]
    return _list(rows, limit, offset)


@bp.post("/pace/contractors/<row_id>/enroll")
def enroll_contractor(row_id):
    authorize([ROLE_PROGRAM_ADMIN])
    v.body()
    contractor = services.get_contractor(row_id)
    if contractor["enrollment_status"] != "PENDING_REVIEW":
        fail("ERR_CONTRACTOR_STATE_INVALID", "Contractor is not PENDING_REVIEW")
    if calc.date_from_iso(contractor["license_expires_on"]) <= db.today():
        fail("ERR_LICENSE_EXPIRED", "Contractor licence has expired")
    if int(contractor["workmanship_warranty_years"]) < 5:
        fail("ERR_WARRANTY_TOO_SHORT", "workmanship_warranty_years must be at least 5")
    if not contractor["counties_served"]:
        fail("ERR_VALIDATION", "counties_served must be non-empty")
    contractor["enrollment_status"] = "ENROLLED"
    contractor["suspension_reason"] = None
    db.touch(contractor)
    return response.ok(db.public(contractor))


@bp.post("/pace/contractors/<row_id>/reinstate")
def reinstate_contractor(row_id):
    authorize([ROLE_PROGRAM_ADMIN])
    payload = v.body()
    v.opt_str(payload, "note")
    contractor = services.get_contractor(row_id)
    if contractor["enrollment_status"] not in ("PROBATION", "SUSPENDED"):
        fail("ERR_CONTRACTOR_STATE_INVALID", "Contractor is not on probation or suspension")
    if calc.date_from_iso(contractor["license_expires_on"]) <= db.today():
        fail("ERR_LICENSE_EXPIRED", "Contractor licence has expired")
    scores = services.fresh_scores(contractor)
    if scores["workmanship_score"] < 9000 or scores["lifetime_workmanship_score"] < 8000:
        fail("ERR_WORKMANSHIP_GATE_NOT_MET", "Workmanship score gates are not met")
    if scores["upheld_open_remedy_count"] != 0:
        fail("ERR_OPEN_REMEDY_OUTSTANDING", "An upheld remedy is still outstanding")
    contractor["workmanship_score"] = scores["workmanship_score"]
    contractor["lifetime_workmanship_score"] = scores["lifetime_workmanship_score"]
    contractor["upheld_open_remedy_count"] = scores["upheld_open_remedy_count"]
    contractor["enrollment_status"] = "ENROLLED"
    contractor["suspension_reason"] = None
    db.touch(contractor)
    services.apply_reinstatement_cascade(contractor)
    return response.ok(db.public(contractor))
