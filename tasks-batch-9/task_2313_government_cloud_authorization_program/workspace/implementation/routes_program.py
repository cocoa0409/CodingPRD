"""Agencies, control baselines, offerings, data categories, control implementations."""
from decimal import Decimal

from flask import Blueprint

import calc
import services as svc
from core import (
    AGENCY_CODE_RE,
    AGENCY_OFFICIAL,
    ANY_ROLE,
    BOARD,
    LEAD,
    authenticate,
    body,
    db,
    fail,
    lookup,
    new_record,
    now,
    ok,
    created,
    listing,
    opt_bool,
    opt_enum,
    opt_int,
    opt_str,
    pagination,
    paginate,
    query_bool,
    query_enum,
    query_str,
    r2,
    req_bool,
    req_enum,
    req_instant,
    req_int,
    req_money,
    req_str,
    rows,
    touch,
    uid,
)

bp = Blueprint("program", __name__)

IMPACT_LEVELS = ("LOW", "MODERATE", "HIGH")
SERVICE_MODELS = ("IAAS", "PAAS", "SAAS")
DEPLOYMENT_MODELS = ("GOV_COMMUNITY", "PUBLIC", "HYBRID", "PRIVATE")
OFFERING_STATUSES = (
    "DRAFT",
    "CATEGORIZED",
    "PATH_SELECTED",
    "IN_ASSESSMENT",
    "PACKAGE_SUBMITTED",
    "AUTHORIZED",
    "CHANGE_UNDER_REVIEW",
    "SUSPENDED",
)
PATHS = ("AGENCY_SPONSORED", "PROGRAM_BOARD")
CATEGORY_STATUSES = ("DECLARED", "CONFIRMED", "WITHDRAWN")
IMPL_STATUSES = (
    "IMPLEMENTED",
    "PARTIALLY_IMPLEMENTED",
    "PLANNED",
    "ALTERNATIVE_IMPLEMENTATION",
    "NOT_APPLICABLE",
)


def refresh_preliminary(offering):
    offering["preliminary_impact_level"] = calc.preliminary_impact_level(offering["id"])


# ---------------------------------------------------------------------------
# Agencies
# ---------------------------------------------------------------------------


@bp.post("/agencies")
def create_agency():
    authenticate((BOARD,))
    b = body()
    name = req_str(b, "name")
    code = req_str(b, "agency_code")
    if not AGENCY_CODE_RE.match(code):
        fail("ERR_INVALID_REQUEST", "Field 'agency_code' must be 2-8 uppercase letters.")
    status = opt_enum(b, "status", ("ACTIVE", "INACTIVE"), "ACTIVE")
    capacity = opt_int(b, "sponsorship_capacity", 3, minimum=0)
    for existing in rows("agencies"):
        if existing["agency_code"] == code:
            fail("ERR_INVALID_REQUEST", "Field 'agency_code' must be unique across agencies.")
    rec = new_record()
    rec.update(
        {
            "name": name,
            "agency_code": code,
            "status": status,
            "sponsorship_capacity": capacity,
            "sponsored_offering_count": 0,
            "reuse_grant_count": 0,
            "open_notice_count": 0,
        }
    )
    db.agencies[rec["id"]] = rec
    return created(rec)


@bp.get("/agencies/<ident>")
def read_agency(ident):
    authenticate(ANY_ROLE)
    return ok(lookup("agencies", ident))


# ---------------------------------------------------------------------------
# Control baselines
# ---------------------------------------------------------------------------


@bp.post("/control-baselines")
def create_baseline():
    authenticate((BOARD,))
    b = body()
    impact_level = req_enum(b, "impact_level", IMPACT_LEVELS)
    version_label = req_str(b, "version_label")
    effective_from = req_instant(b, "effective_from")
    families_raw = b.get("families")
    if families_raw is None:
        fail("ERR_INVALID_REQUEST", "Field 'families' is required.")
    if not isinstance(families_raw, list) or not families_raw:
        fail("ERR_INVALID_REQUEST", "Field 'families' must be a non-empty array.")
    families = []
    seen = set()
    total = 0
    for element in families_raw:
        if not isinstance(element, dict):
            fail("ERR_INVALID_REQUEST", "Each 'families' element must be an object.")
        code = req_str(element, "family_code")
        required = req_int(element, "required_control_count", minimum=0)
        rank = req_int(element, "priority_rank", minimum=1)
        if code in seen:
            fail("ERR_INVALID_REQUEST", "Field 'families' must not repeat a family_code.")
        seen.add(code)
        total += required
        families.append(
            {
                "family_code": code,
                "required_control_count": required,
                "priority_rank": rank,
            }
        )
    retired = opt_bool(b, "retired", False)
    rec = new_record(audit=False)
    rec.update(
        {
            "impact_level": impact_level,
            "version_label": version_label,
            "effective_from": effective_from,
            "retired": retired,
            "families": families,
            "total_required_controls": total,
        }
    )
    db.baselines[rec["id"]] = rec
    return created(rec)


# ---------------------------------------------------------------------------
# Offerings
# ---------------------------------------------------------------------------


@bp.post("/offerings")
def create_offering():
    authenticate((LEAD,))
    b = body()
    name = req_str(b, "name")
    provider_name = req_str(b, "provider_name")
    service_model = req_enum(b, "service_model", SERVICE_MODELS)
    deployment_model = req_enum(b, "deployment_model", DEPLOYMENT_MODELS)
    budget = req_money(b, "assessment_budget_usd")
    external = opt_enum(b, "external_dependency_impact_level", IMPACT_LEVELS, "LOW")
    rec = new_record()
    rec.update(
        {
            "name": name,
            "provider_name": provider_name,
            "owner_user_id": uid(),
            "service_model": service_model,
            "deployment_model": deployment_model,
            "external_dependency_impact_level": external,
            "assessment_budget_usd": budget,
            "authorization_path": None,
            "sponsor_agency_id": None,
            "baseline_id": None,
            "preliminary_impact_level": None,
            "final_impact_level": None,
            "status": "DRAFT",
            "boundary_version": 1,
            "included_service_count": 0,
            "open_package_count": 0,
            "superseded_package_count": 0,
        }
    )
    db.offerings[rec["id"]] = rec
    return created(rec)


@bp.get("/offerings/<ident>")
def read_offering(ident):
    authenticate(ANY_ROLE)
    return ok(lookup("offerings", ident))


@bp.get("/offerings")
def list_offerings():
    authenticate(ANY_ROLE)
    status = query_enum("status", OFFERING_STATUSES)
    path = query_enum("authorization_path", PATHS)
    baseline_id = query_str("baseline_id")
    agency_id = query_str("sponsor_agency_id")
    limit, offset = pagination()
    if baseline_id is not None:
        lookup("baselines", baseline_id)
    if agency_id is not None:
        lookup("agencies", agency_id)
    result = rows("offerings")
    if status is not None:
        result = [o for o in result if o["status"] == status]
    if path is not None:
        result = [o for o in result if o["authorization_path"] == path]
    if baseline_id is not None:
        result = [o for o in result if o["baseline_id"] == baseline_id]
    if agency_id is not None:
        result = [o for o in result if o["sponsor_agency_id"] == agency_id]
    page, total = paginate(result, limit, offset)
    return listing(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Data categories
# ---------------------------------------------------------------------------


@bp.post("/offerings/<ident>/data-categories")
def create_data_category(ident):
    authenticate((LEAD,))
    b = body()
    code = req_str(b, "category_code")
    conf = req_enum(b, "confidentiality_impact", IMPACT_LEVELS)
    integ = req_enum(b, "integrity_impact", IMPACT_LEVELS)
    avail = req_enum(b, "availability_impact", IMPACT_LEVELS)
    offering = lookup("offerings", ident)
    svc.require_offering_owner(offering, uid())
    # PRD 3.2: "While the offering is `DRAFT`, the lead declares the information
    # types inside its boundary." — tier 11 of the precedence list.
    if offering["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Data categories may only be declared while the offering is DRAFT.")
    for existing in calc.categories_of(offering["id"]):
        if existing["category_code"] == code:
            fail(
                "ERR_DUPLICATE_CONTROL_IMPLEMENTATION",
                "category_code must be unique per offering.",
            )
    rec = new_record()
    rec.update(
        {
            "offering_id": offering["id"],
            "category_code": code,
            "confidentiality_impact": conf,
            "integrity_impact": integ,
            "availability_impact": avail,
            "status": "DECLARED",
            "confirmed_by_user_id": None,
        }
    )
    db.data_categories[rec["id"]] = rec
    refresh_preliminary(offering)
    touch(offering)
    return created(rec)


@bp.get("/offerings/<ident>/data-categories")
def list_data_categories(ident):
    authenticate(ANY_ROLE)
    status = query_enum("status", CATEGORY_STATUSES)
    limit, offset = pagination()
    offering = lookup("offerings", ident)
    result = calc.categories_of(offering["id"])
    if status is not None:
        result = [c for c in result if c["status"] == status]
    page, total = paginate(result, limit, offset)
    return listing(page, limit, offset, total)


@bp.post("/data-categories/<ident>/confirm")
def confirm_data_category(ident):
    authenticate((BOARD, AGENCY_OFFICIAL))
    b = body()
    decision = req_enum(b, "decision", ("CONFIRM", "WITHDRAW"))
    category = lookup("data_categories", ident)
    offering = db.offerings.get(category["offering_id"])
    if category["status"] != "DECLARED":
        fail("ERR_INVALID_STATE", "The data category is no longer DECLARED.")
    if offering is None or offering["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "The offering is no longer in DRAFT.")
    category["status"] = "CONFIRMED" if decision == "CONFIRM" else "WITHDRAWN"
    category["confirmed_by_user_id"] = uid()
    touch(category)
    refresh_preliminary(offering)
    touch(offering)
    return ok(category)


# ---------------------------------------------------------------------------
# Impact determination and path selection
# ---------------------------------------------------------------------------


@bp.post("/offerings/<ident>/impact-determination")
def impact_determination(ident):
    authenticate((BOARD,))
    body()
    offering = lookup("offerings", ident)
    if offering["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Impact determination requires the offering to be in DRAFT.")
    level = calc.final_impact_level(offering)
    baseline = calc.select_baseline(level)
    offering["final_impact_level"] = level
    offering["baseline_id"] = baseline["id"]
    offering["status"] = "CATEGORIZED"
    touch(offering)
    return ok(offering)


@bp.post("/offerings/<ident>/path-selection")
def path_selection(ident):
    authenticate((LEAD,))
    b = body()
    path = req_enum(b, "authorization_path", PATHS)
    sponsor_id = b.get("sponsor_agency_id")
    if path == "AGENCY_SPONSORED":
        sponsor_id = req_str(b, "sponsor_agency_id")
    else:
        if sponsor_id is not None:
            fail(
                "ERR_INVALID_REQUEST",
                "Field 'sponsor_agency_id' must be absent on the PROGRAM_BOARD path.",
            )
    offering = lookup("offerings", ident)
    agency = None
    if sponsor_id is not None:
        agency = lookup("agencies", sponsor_id)
    svc.require_offering_owner(offering, uid())
    if offering["status"] != "CATEGORIZED":
        fail("ERR_INVALID_STATE", "Path selection requires the offering to be CATEGORIZED.")
    if path == "AGENCY_SPONSORED":
        if agency["status"] != "ACTIVE":
            fail(
                "ERR_SPONSORSHIP_CAPACITY_EXCEEDED",
                "The sponsoring agency is not ACTIVE.",
            )
        if int(agency["sponsored_offering_count"]) >= int(agency["sponsorship_capacity"]):
            fail(
                "ERR_SPONSORSHIP_CAPACITY_EXCEEDED",
                "The sponsoring agency has no sponsorship capacity left.",
            )
    offering["authorization_path"] = path
    offering["sponsor_agency_id"] = agency["id"] if agency is not None else None
    offering["status"] = "PATH_SELECTED"
    touch(offering)
    if agency is not None:
        svc.sync_agency(agency)
        touch(agency)
    return ok(offering)


@bp.get("/offerings/<ident>/crm-coverage")
def crm_coverage_read(ident):
    authenticate(ANY_ROLE)
    offering = lookup("offerings", ident)
    result = calc.crm_coverage(offering)
    result["evaluated_at"] = now()
    return ok(result)


# ---------------------------------------------------------------------------
# Control implementations
# ---------------------------------------------------------------------------


def _check_inheritance(inherited_id):
    if inherited_id is None:
        return
    source = db.offerings.get(inherited_id)
    if source is None or source["status"] != "AUTHORIZED":
        fail(
            "ERR_INHERITED_OFFERING_NOT_AUTHORIZED",
            "Inheritance is only legal from an AUTHORIZED offering.",
        )


def _check_crm_pair(crm_documented, text):
    if crm_documented and (text is None or not str(text).strip()):
        fail(
            "ERR_CRM_TEXT_REQUIRED",
            "customer_responsibility_text is required when crm_documented is true.",
        )


@bp.post("/control-implementations")
def create_control_implementation():
    authenticate((LEAD,))
    b = body()
    offering_id = req_str(b, "offering_id")
    control_id = req_str(b, "control_id")
    family_code = req_str(b, "family_code")
    impl_status = opt_enum(b, "implementation_status", IMPL_STATUSES, "PLANNED")
    crm_documented = opt_bool(b, "crm_documented", False)
    text = opt_str(b, "customer_responsibility_text", None)
    inherited_id = opt_str(b, "inherited_from_offering_id", None)
    offering = lookup("offerings", offering_id)
    if inherited_id is not None:
        lookup("offerings", inherited_id)
    svc.require_offering_owner(offering, uid())
    _check_inheritance(inherited_id)
    _check_crm_pair(crm_documented, text)
    for existing in rows("control_implementations"):
        if existing["offering_id"] == offering["id"] and existing["control_id"] == control_id:
            fail(
                "ERR_DUPLICATE_CONTROL_IMPLEMENTATION",
                "control_id must be unique per offering.",
            )
    rec = new_record()
    rec.update(
        {
            "offering_id": offering["id"],
            "inherited_from_offering_id": inherited_id,
            "control_id": control_id,
            "family_code": family_code,
            "implementation_status": impl_status,
            "crm_documented": crm_documented,
            "customer_responsibility_text": text,
        }
    )
    db.control_implementations[rec["id"]] = rec
    return created(rec)


@bp.patch("/control-implementations/<ident>")
def update_control_implementation(ident):
    authenticate((LEAD,))
    b = body()
    impl_status = opt_enum(b, "implementation_status", IMPL_STATUSES, None)
    crm_documented = None
    if "crm_documented" in b and b.get("crm_documented") is not None:
        crm_documented = req_bool(b, "crm_documented")
    text_supplied = "customer_responsibility_text" in b
    text = opt_str(b, "customer_responsibility_text", None) if text_supplied else None
    inherited_supplied = "inherited_from_offering_id" in b
    inherited_id = opt_str(b, "inherited_from_offering_id", None) if inherited_supplied else None
    rec = lookup("control_implementations", ident)
    if inherited_supplied and inherited_id is not None:
        lookup("offerings", inherited_id)
    offering = db.offerings.get(rec["offering_id"])
    if offering is not None:
        svc.require_offering_owner(offering, uid())
    effective_inherited = inherited_id if inherited_supplied else rec["inherited_from_offering_id"]
    _check_inheritance(effective_inherited)
    effective_crm = rec["crm_documented"] if crm_documented is None else crm_documented
    effective_text = text if text_supplied else rec["customer_responsibility_text"]
    _check_crm_pair(effective_crm, effective_text)
    if impl_status is not None:
        rec["implementation_status"] = impl_status
    if crm_documented is not None:
        rec["crm_documented"] = crm_documented
    if text_supplied:
        rec["customer_responsibility_text"] = text
    if inherited_supplied:
        rec["inherited_from_offering_id"] = inherited_id
    touch(rec)
    return ok(rec)


@bp.get("/control-implementations/<ident>")
def read_control_implementation(ident):
    authenticate(ANY_ROLE)
    return ok(lookup("control_implementations", ident))


@bp.get("/control-implementations")
def list_control_implementations():
    authenticate(ANY_ROLE)
    offering_id = query_str("offering_id")
    inherited_id = query_str("inherited_from_offering_id")
    family_code = query_str("family_code")
    impl_status = query_enum("implementation_status", IMPL_STATUSES)
    crm_documented = query_bool("crm_documented")
    limit, offset = pagination()
    result = rows("control_implementations")
    if offering_id is not None:
        result = [c for c in result if c["offering_id"] == offering_id]
    if inherited_id is not None:
        result = [c for c in result if c["inherited_from_offering_id"] == inherited_id]
    if family_code is not None:
        result = [c for c in result if c["family_code"] == family_code]
    if impl_status is not None:
        result = [c for c in result if c["implementation_status"] == impl_status]
    if crm_documented is not None:
        result = [c for c in result if c["crm_documented"] is crm_documented]
    page, total = paginate(result, limit, offset)
    return listing(page, limit, offset, total)
