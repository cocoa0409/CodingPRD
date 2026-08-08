"""Service areas, protected-site registry, trap sites, larval dips, weather,
risk assessments, and the surveillance report."""
from decimal import Decimal

from flask import Blueprint

import calc
import domain
import store
import views
from common import (
    ALL_DISTRICT_READERS, ApiError, D, auth, created, get_body, logical_today,
    ok, ok_list, opt_bool, opt_decimal, opt_int, pagination, paginate,
    parse_date, q1, q2, query_bool, query_enum, query_str, req_decimal,
    req_enum, req_int, req_present, req_string, validation, logical_now,
)

bp = Blueprint("area", __name__)

CODE_PATTERN = r"^[A-Z0-9]{2,8}$"
SITE_TYPES = ("APIARY", "ORGANIC_FARM", "AQUACULTURE", "SCHOOL")
TRAP_TYPES = ("CDC_LIGHT", "GRAVID", "BG_SENTINEL")
TRAP_HABITATS = ("URBAN", "WETLAND", "AGRICULTURAL", "STORMWATER")
LARVAL_HABITATS = ("CATCH_BASIN", "DITCH", "MARSH", "CONTAINER")
ASSESSMENT_STATUSES = ("OPEN", "CONFIRMED", "SUPERSEDED")


def duplicate(message):
    return ApiError("ERR_DUPLICATE_RESOURCE", 409, message)


# --------------------------------------------------------------------------
# Service areas
# --------------------------------------------------------------------------


@bp.post("/service-areas")
def create_service_area():
    auth(("DistrictAdmin",))
    body = get_body()
    name = req_string(body, "name", 1, 120)
    code = req_string(body, "code", 2, 8, pattern=CODE_PATTERN)
    season_start_date = parse_date(req_present(body, "season_start_date"),
                                   "season_start_date")
    population = req_int(body, "population", minimum=0)

    for existing in store.SERVICE_AREAS.values():
        if existing["code"] == code:
            raise duplicate("Service area code '%s' is already in use." % code)

    record = store.new_record()
    record.update({
        "name": name,
        "code": code,
        "season_start_date": season_start_date,
        "population": population,
        "risk_posture": "NORMAL",
        "posture_source": "NO_ASSESSMENT",
        "latest_confirmed_vector_index": q2(0),
        "seasonal_application_count": 0,
        "request_total_count": 0,
        "request_open_count": 0,
        "request_resolved_count": 0,
        "request_closed_count": 0,
    })
    store.SERVICE_AREAS[record["id"]] = record
    return created(views.area_view(record))


@bp.get("/service-areas/<area_id>")
def get_service_area(area_id):
    auth(ALL_DISTRICT_READERS)
    area = store.fetch("ServiceArea", area_id)
    return ok(views.area_view(area))


# --------------------------------------------------------------------------
# Protected-site registry
# --------------------------------------------------------------------------


@bp.post("/service-areas/<area_id>/sensitive-sites")
def create_sensitive_site(area_id):
    auth(("DistrictAdmin",))
    area = store.fetch("ServiceArea", area_id)
    body = get_body()
    site_type = req_enum(body, "site_type", SITE_TYPES)
    operator_name = req_string(body, "operator_name", 1, 120)
    contact_email = req_string(body, "contact_email", 1)
    if "@" not in contact_email:
        raise validation("contact_email must contain '@'.")
    x_m = req_int(body, "x_m")
    y_m = req_int(body, "y_m")
    override = opt_int(body, "buffer_meters_override", minimum=0, default=None)

    buffer_meters = override if override is not None else calc.SENSITIVE_SITE_BUFFER_METERS[site_type]

    record = store.new_record()
    record.update({
        "service_area_id": area["id"],
        "site_type": site_type,
        "operator_name": operator_name,
        "contact_email": contact_email,
        "x_m": x_m,
        "y_m": y_m,
        "buffer_meters_override": override,
        "buffer_meters": buffer_meters,
        "registered_on": logical_today(),
    })
    store.SENSITIVE_SITES[record["id"]] = record
    return created(views.sensitive_site_view(record))


@bp.get("/service-areas/<area_id>/sensitive-sites")
def list_sensitive_sites(area_id):
    auth(ALL_DISTRICT_READERS + ("SensitiveSiteOperator",))
    area = store.fetch("ServiceArea", area_id)
    limit, offset = pagination()
    site_type = query_enum("site_type", SITE_TYPES)
    rows = [s for s in store.SENSITIVE_SITES.values()
            if s["service_area_id"] == area["id"]
            and (site_type is None or s["site_type"] == site_type)]
    page, total = paginate(store.ordered(rows), limit, offset)
    return ok_list([views.sensitive_site_view(r) for r in page], limit, offset, total)


# --------------------------------------------------------------------------
# Trap sites
# --------------------------------------------------------------------------


@bp.post("/service-areas/<area_id>/trap-sites")
def create_trap_site(area_id):
    auth(("DistrictAdmin",))
    area = store.fetch("ServiceArea", area_id)
    body = get_body()
    site_code = req_string(body, "site_code", 1, 16)
    trap_type = req_enum(body, "trap_type", TRAP_TYPES)
    habitat = req_enum(body, "habitat", TRAP_HABITATS)
    x_m = req_int(body, "x_m")
    y_m = req_int(body, "y_m")
    is_active = opt_bool(body, "is_active", default=True)

    for existing in store.TRAP_SITES.values():
        if existing["service_area_id"] == area["id"] and existing["site_code"] == site_code:
            raise duplicate("Trap site code '%s' already exists in this area." % site_code)

    record = store.new_record()
    record.update({
        "service_area_id": area["id"],
        "site_code": site_code,
        "trap_type": trap_type,
        "habitat": habitat,
        "x_m": x_m,
        "y_m": y_m,
        "is_active": is_active,
        "season_positive_count": 0,
        "last_positive_at": None,
    })
    store.TRAP_SITES[record["id"]] = record
    return created(views.trap_site_view(record))


@bp.get("/service-areas/<area_id>/trap-sites")
def list_trap_sites(area_id):
    auth(ALL_DISTRICT_READERS)
    area = store.fetch("ServiceArea", area_id)
    limit, offset = pagination()
    is_active = query_bool("is_active")
    rows = [t for t in store.TRAP_SITES.values()
            if t["service_area_id"] == area["id"]
            and (is_active is None or t["is_active"] == is_active)]
    page, total = paginate(store.ordered(rows), limit, offset)
    return ok_list([views.trap_site_view(r) for r in page], limit, offset, total)


@bp.get("/trap-sites/<trap_site_id>")
def get_trap_site(trap_site_id):
    auth(ALL_DISTRICT_READERS)
    site = store.fetch("TrapSite", trap_site_id)
    return ok(views.trap_site_view(site))


# --------------------------------------------------------------------------
# Larval inspections (append-only)
# --------------------------------------------------------------------------


@bp.post("/service-areas/<area_id>/larval-inspections")
def create_larval_inspection(area_id):
    auth(("FieldTech",))
    area = store.fetch("ServiceArea", area_id)
    body = get_body()
    inspection_date = parse_date(req_present(body, "inspection_date"), "inspection_date")
    dips = req_int(body, "dips", minimum=1)
    larvae_count = req_int(body, "larvae_count", minimum=0)
    habitat = req_enum(body, "habitat", LARVAL_HABITATS)
    treated_on_site = opt_bool(body, "treated_on_site", default=False)

    record = store.new_record(with_version=False)
    record.update({
        "service_area_id": area["id"],
        "inspection_date": inspection_date,
        "dips": dips,
        "larvae_count": larvae_count,
        "habitat": habitat,
        "treated_on_site": treated_on_site,
    })
    store.LARVAL_INSPECTIONS[record["id"]] = record
    return created(views.larval_inspection_view(record))


@bp.get("/service-areas/<area_id>/larval-inspections")
def list_larval_inspections(area_id):
    auth(ALL_DISTRICT_READERS)
    area = store.fetch("ServiceArea", area_id)
    limit, offset = pagination()
    habitat = query_enum("habitat", LARVAL_HABITATS)
    rows = [i for i in store.LARVAL_INSPECTIONS.values()
            if i["service_area_id"] == area["id"]
            and (habitat is None or i["habitat"] == habitat)]
    page, total = paginate(store.ordered(rows), limit, offset)
    return ok_list([views.larval_inspection_view(r) for r in page], limit, offset, total)


# --------------------------------------------------------------------------
# Weather observations (append-only)
# --------------------------------------------------------------------------


@bp.post("/service-areas/<area_id>/weather-observations")
def create_weather_observation(area_id):
    auth(("DistrictAdmin", "FieldTech"))
    area = store.fetch("ServiceArea", area_id)
    body = get_body()
    obs_date = parse_date(req_present(body, "obs_date"), "obs_date")
    tmax_c = req_decimal(body, "tmax_c", minimum="-50.0", maximum="60.0")
    tmin_c = req_decimal(body, "tmin_c", minimum="-50.0", maximum="60.0")
    if tmin_c > tmax_c:
        raise validation("tmin_c must not exceed tmax_c.")
    rainfall_mm = opt_decimal(body, "rainfall_mm", minimum=0, default=D("0.0"))

    for existing in store.WEATHER_OBSERVATIONS.values():
        if existing["service_area_id"] == area["id"] and existing["obs_date"] == obs_date:
            raise duplicate("A weather observation already exists for that date.")

    record = store.new_record(with_version=False)
    record.update({
        "service_area_id": area["id"],
        "obs_date": obs_date,
        "tmax_c": tmax_c,
        "tmin_c": tmin_c,
        "rainfall_mm": rainfall_mm,
        "degree_day": calc.observation_degree_day(tmax_c, tmin_c),
    })
    store.WEATHER_OBSERVATIONS[record["id"]] = record
    return created(views.weather_observation_view(record))


@bp.get("/service-areas/<area_id>/weather-observations")
def list_weather_observations(area_id):
    auth(ALL_DISTRICT_READERS)
    area = store.fetch("ServiceArea", area_id)
    limit, offset = pagination()
    rows = [o for o in store.WEATHER_OBSERVATIONS.values()
            if o["service_area_id"] == area["id"]]
    page, total = paginate(store.ordered(rows), limit, offset)
    return ok_list([views.weather_observation_view(r) for r in page], limit, offset, total)


# --------------------------------------------------------------------------
# Risk assessments
# --------------------------------------------------------------------------


@bp.post("/service-areas/<area_id>/risk-assessments")
def create_risk_assessment(area_id):
    auth(("VectorEcologist",))
    area = store.fetch("ServiceArea", area_id)
    body = get_body()
    as_of_date = parse_date(req_present(body, "as_of_date"), "as_of_date")
    expected_version = req_int(body, "expected_service_area_version")

    if expected_version != area["version"]:
        raise ApiError("ERR_STALE_SERVICE_AREA_VERSION", 412,
                       "expected_service_area_version does not match.")

    for assessment in store.RISK_ASSESSMENTS.values():
        if assessment["service_area_id"] != area["id"]:
            continue
        if assessment["status"] == "OPEN":
            assessment["status"] = "SUPERSEDED"
            store.touch(assessment)

    abundance_index = calc.trap_abundance_index(area["id"], as_of_date)
    larval_index = calc.larval_index(area["id"], as_of_date)
    degree_days = calc.degree_day_accumulation(area, as_of_date)
    mir_provisional = calc.minimum_infection_rate(area["id"], as_of_date, "PROVISIONAL")
    vector_index_provisional = calc.vector_index(
        abundance_index, mir_provisional, larval_index, degree_days)

    record = store.new_record()
    record.update({
        "service_area_id": area["id"],
        "as_of_date": as_of_date,
        "status": "OPEN",
        "is_stale": False,
        "stale_reason": None,
        "abundance_index": abundance_index,
        "larval_index": larval_index,
        "degree_days": degree_days,
        "mir_provisional": mir_provisional,
        "mir_confirmed": None,
        "vector_index_provisional": vector_index_provisional,
        "vector_index_confirmed": None,
        "posture_at_confirm": None,
        "confirmed_at": None,
    })
    store.RISK_ASSESSMENTS[record["id"]] = record
    store.touch(area)
    return created(views.risk_assessment_view(record))


@bp.get("/service-areas/<area_id>/risk-assessments")
def list_risk_assessments(area_id):
    auth(ALL_DISTRICT_READERS)
    area = store.fetch("ServiceArea", area_id)
    limit, offset = pagination()
    status = query_enum("status", ASSESSMENT_STATUSES)
    rows = [a for a in store.RISK_ASSESSMENTS.values()
            if a["service_area_id"] == area["id"]
            and (status is None or a["status"] == status)]
    page, total = paginate(store.ordered(rows), limit, offset)
    return ok_list([views.risk_assessment_view(r) for r in page], limit, offset, total)


@bp.get("/risk-assessments/<assessment_id>")
def get_risk_assessment(assessment_id):
    auth(ALL_DISTRICT_READERS)
    assessment = store.fetch("RiskAssessment", assessment_id)
    return ok(views.risk_assessment_view(assessment))


@bp.post("/risk-assessments/<assessment_id>/confirm")
def confirm_risk_assessment(assessment_id):
    auth(("VectorEcologist",))
    assessment = store.fetch("RiskAssessment", assessment_id)
    if assessment["status"] != "OPEN":
        raise ApiError("ERR_ASSESSMENT_NOT_OPEN", 409,
                       "Only an OPEN assessment may be confirmed.")
    area = store.SERVICE_AREAS[assessment["service_area_id"]]

    mir_confirmed = calc.minimum_infection_rate(
        area["id"], assessment["as_of_date"], "CONFIRMED")
    vector_index_confirmed = calc.vector_index(
        assessment["abundance_index"], mir_confirmed,
        assessment["larval_index"], assessment["degree_days"])

    for other in store.RISK_ASSESSMENTS.values():
        if other["id"] == assessment["id"]:
            continue
        if other["service_area_id"] != area["id"]:
            continue
        if other["status"] == "CONFIRMED":
            other["status"] = "SUPERSEDED"
            store.touch(other)

    assessment["mir_confirmed"] = mir_confirmed
    assessment["vector_index_confirmed"] = vector_index_confirmed
    assessment["confirmed_at"] = logical_now()
    assessment["status"] = "CONFIRMED"

    area["latest_confirmed_vector_index"] = vector_index_confirmed
    store.touch(area)
    posture = domain.recompute_posture(area)
    assessment["posture_at_confirm"] = posture
    store.touch(assessment)
    return ok(views.risk_assessment_view(assessment))


# --------------------------------------------------------------------------
# Surveillance report (computed read; persists nothing)
# --------------------------------------------------------------------------


@bp.get("/service-areas/<area_id>/surveillance-report")
def surveillance_report(area_id):
    auth(ALL_DISTRICT_READERS)
    area = store.fetch("ServiceArea", area_id)
    raw = query_str("as_of_date")
    as_of_date = parse_date(raw, "as_of_date") if raw is not None else logical_today()

    abundance_index = calc.trap_abundance_index(area["id"], as_of_date)
    larval_index = calc.larval_index(area["id"], as_of_date)
    degree_days = calc.degree_day_accumulation(area, as_of_date)
    mir_provisional = calc.minimum_infection_rate(area["id"], as_of_date, "PROVISIONAL")
    mir_confirmed = calc.minimum_infection_rate(area["id"], as_of_date, "CONFIRMED")
    vector_index_provisional = calc.vector_index(
        abundance_index, mir_provisional, larval_index, degree_days)

    return ok({
        "as_of_date": as_of_date,
        "abundance_index": abundance_index,
        "larval_index": larval_index,
        "degree_days": degree_days,
        "mir_provisional": mir_provisional,
        "mir_confirmed": mir_confirmed,
        "vector_index_provisional": vector_index_provisional,
        "risk_posture": area["risk_posture"],
        "posture_source": area["posture_source"],
        "seasonal_application_count": area["seasonal_application_count"],
        "request_total_count": area["request_total_count"],
        "request_open_count": area["request_open_count"],
        "request_resolved_count": area["request_resolved_count"],
        "request_closed_count": area["request_closed_count"],
    })
