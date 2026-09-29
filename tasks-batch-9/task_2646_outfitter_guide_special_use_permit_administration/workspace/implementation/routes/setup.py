"""Use areas, outfitters and needs assessments (PRD 3.1)."""
from flask import Blueprint

import calc
import envelope
import security
import serialize
import shapes
import store
from errors import ApiError
from routes.common import match, qint, qstr
from security import ADMIN, ANY_ROLE, OFFICER, SPECIALIST

bp = Blueprint("setup", __name__)

POSTURES = ("OPEN", "CONSTRAINED", "EXHAUSTED")
FINDINGS = ("NEED_EXISTS", "NO_NEED")
ASSESSMENT_STATUSES = ("DRAFT", "PUBLISHED", "SUPERSEDED")
OUTFITTER_STATUSES = ("APPLICANT", "PERMITTED", "SUSPENDED")


# ---------------------------------------------------------------- use areas
@bp.post("/osup/use-areas")
def create_use_area():
    security.authenticate((ADMIN,))
    data = shapes.body()
    area_code = shapes.req_str(data, "area_code")
    name = shapes.req_str(data, "name")
    total = shapes.req_int(data, "total_allocated_service_days", minimum=1, maximum=3650)
    season_year = shapes.req_int(data, "season_year", minimum=1900, maximum=9999)
    season_open = shapes.req_date(data, "season_open_date")
    season_close = shapes.req_date(data, "season_close_date")
    party_size_max = shapes.req_int(data, "party_size_max", minimum=1)
    max_clients = shapes.req_int(data, "max_clients_per_guide", minimum=1)
    reserved = shapes.opt_int(data, "reserved_admin_service_days", minimum=0, default=0)
    min_liability = shapes.opt_int(
        data, "min_liability_coverage_cents", minimum=0, default=100000000
    )
    if reserved >= total:
        shapes.bad(
            "reserved_admin_service_days",
            "must be strictly less than total_allocated_service_days",
        )
    if store.as_date(season_close) < store.as_date(season_open):
        shapes.bad("season_close_date", "must not fall before season_open_date")
    for existing in store.all_of("use_areas"):
        if existing["area_code"] == area_code:
            shapes.bad("area_code", "must be unique across use areas")

    area = store.insert(
        "use_areas",
        {
            "area_code": area_code,
            "name": name,
            "total_allocated_service_days": total,
            "reserved_admin_service_days": reserved,
            "season_year": season_year,
            "season_open_date": season_open,
            "season_close_date": season_close,
            "party_size_max": party_size_max,
            "max_clients_per_guide": max_clients,
            "min_liability_coverage_cents": min_liability,
            "allocatable_service_days": total - reserved,
            "committed_service_days": 0,
            "pending_service_days": 0,
            "available_service_days": 0,
            "demand_ratio": None,
            "allocation_posture": None,
        },
    )
    calc.recompute_area(area, bump=False)
    return envelope.ok(serialize.use_area(area), 201)


@bp.get("/osup/use-areas/<area_id>")
def read_use_area(area_id):
    security.authenticate(ANY_ROLE, mutating=False)
    area = store.get_or_404("use_areas", area_id, "ERR_USE_AREA_NOT_FOUND")
    return envelope.ok(serialize.use_area(area))


@bp.get("/osup/use-areas")
def list_use_areas():
    security.authenticate(ANY_ROLE, mutating=False)
    season_year = qint("season_year")
    posture = qstr("allocation_posture")
    rows = [
        a
        for a in store.all_of("use_areas")
        if match(a, season_year=season_year, allocation_posture=posture)
    ]
    return envelope.paginate(store.sort_created(rows, descending=True), serialize.use_area)


@bp.get("/osup/use-areas/<area_id>/allocation-summary")
def allocation_summary(area_id):
    security.authenticate(ANY_ROLE, mutating=False)
    area = store.get_or_404("use_areas", area_id, "ERR_USE_AREA_NOT_FOUND")
    led = calc.area_ledger(area)
    return envelope.ok(
        {
            "use_area_id": area["id"],
            "allocatable_service_days": led["allocatable_service_days"],
            "committed_service_days": led["committed_service_days"],
            "pending_service_days": led["pending_service_days"],
            "available_service_days": led["available_service_days"],
            "demand_ratio": calc.num(led["demand_ratio"]),
            "allocation_posture": led["allocation_posture"],
        }
    )


# ---------------------------------------------------------------- outfitters
@bp.post("/osup/outfitters")
def register_outfitter():
    security.authenticate((SPECIALIST, ADMIN))
    data = shapes.body()
    legal_name = shapes.req_str(data, "legal_name")
    ein = shapes.req_str(data, "ein")
    contact_email = shapes.req_str(data, "contact_email")
    verified = shapes.opt_bool(data, "prequalification_insurance_verified", default=False)
    if len(ein) != 9 or not ein.isdigit():
        shapes.bad("ein", "must be exactly nine digits")
    for existing in store.all_of("outfitters"):
        if existing["ein"] == ein:
            shapes.bad("ein", "must be unique across outfitters")

    outfitter = store.insert(
        "outfitters",
        {
            "legal_name": legal_name,
            "ein": ein,
            "contact_email": contact_email,
            "prequalification_insurance_verified": verified,
            "status": "APPLICANT",
            "prior_permit_count": 0,
            "active_permit_count": 0,
        },
    )
    return envelope.ok(serialize.outfitter(outfitter), 201)


@bp.get("/osup/outfitters/<outfitter_id>")
def read_outfitter(outfitter_id):
    security.authenticate(ANY_ROLE, mutating=False)
    outfitter = store.get_or_404("outfitters", outfitter_id, "ERR_OUTFITTER_NOT_FOUND")
    return envelope.ok(serialize.outfitter(outfitter))


@bp.post("/osup/outfitters/<outfitter_id>/prequalification")
def record_prequalification(outfitter_id):
    security.authenticate((SPECIALIST, ADMIN))
    outfitter = store.get_or_404("outfitters", outfitter_id, "ERR_OUTFITTER_NOT_FOUND")
    data = shapes.body()
    verified = shapes.req_bool(data, "verified")
    outfitter["prequalification_insurance_verified"] = verified
    store.touch(outfitter)
    return envelope.ok(serialize.outfitter(outfitter))


# ------------------------------------------------------- needs assessments
@bp.post("/osup/use-areas/<area_id>/needs-assessments")
def draft_needs_assessment(area_id):
    security.authenticate((SPECIALIST, ADMIN))
    area = store.get_or_404("use_areas", area_id, "ERR_USE_AREA_NOT_FOUND")
    data = shapes.body()
    year = shapes.req_int(data, "assessment_year", minimum=1900, maximum=9999)
    finding = shapes.req_str(data, "public_need_finding", allowed=FINDINGS)
    determined = shapes.req_int(
        data, "determined_capacity_service_days", minimum=0, maximum=3650
    )
    allocated = shapes.req_int(data, "allocated_service_days", minimum=0, maximum=3650)
    allocatable = (
        area["total_allocated_service_days"] - area["reserved_admin_service_days"]
    )
    if determined > allocatable:
        shapes.bad(
            "determined_capacity_service_days",
            "must not exceed the area's allocatable total",
        )

    assessment = store.insert(
        "needs_assessments",
        {
            "use_area_id": area["id"],
            "assessment_year": year,
            "public_need_finding": finding,
            "determined_capacity_service_days": determined,
            "allocated_service_days": allocated,
            "unallocated_service_days": 0,
            "prospectus_required": False,
            "status": "DRAFT",
            "published_at": None,
        },
    )
    calc.recompute_assessment_fields(assessment, allocated)
    return envelope.ok(serialize.needs_assessment(assessment), 201)


@bp.post("/osup/needs-assessments/<assessment_id>/publish")
def publish_needs_assessment(assessment_id):
    security.authenticate((OFFICER, ADMIN))
    assessment = store.get_or_404(
        "needs_assessments", assessment_id, "ERR_NEEDS_ASSESSMENT_NOT_FOUND"
    )
    if assessment["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_ASSESSMENT_STATE", "assessment is not DRAFT")

    prior = calc.published_assessment(
        assessment["use_area_id"], assessment["assessment_year"]
    )
    if prior is not None and prior["id"] != assessment["id"]:
        prior["status"] = "SUPERSEDED"
        store.touch(prior)

    area = store.get("use_areas", assessment["use_area_id"])
    assessment["status"] = "PUBLISHED"
    assessment["published_at"] = store.now_str()
    led = calc.area_ledger(area)
    calc.recompute_assessment_fields(
        assessment, led["committed_service_days"] + led["pending_service_days"]
    )
    store.touch(assessment)
    return envelope.ok(serialize.needs_assessment(assessment))


@bp.get("/osup/use-areas/<area_id>/needs-assessments")
def list_needs_assessments(area_id):
    security.authenticate(ANY_ROLE, mutating=False)
    area = store.get_or_404("use_areas", area_id, "ERR_USE_AREA_NOT_FOUND")
    year = qint("assessment_year")
    status = qstr("status")
    rows = [
        a
        for a in store.all_of("needs_assessments")
        if a["use_area_id"] == area["id"]
        and match(a, assessment_year=year, status=status)
    ]
    return envelope.paginate(store.sort_created(rows), serialize.needs_assessment)
