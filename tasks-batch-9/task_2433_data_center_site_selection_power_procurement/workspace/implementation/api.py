"""All 41 endpoints.

Every handler evaluates its admission conditions in the fixed ladder order:
headers, role, utility identity binding, request shape, interval ordering, option
backdating, path existence, body reference existence, site version, then the
state, cross-entity, safety, referential, uniqueness and fiscal gates.

Because request shape (step 4) precedes path existence (step 7), handlers parse
and validate their body BEFORE resolving path identifiers.
"""

import functools
from decimal import Decimal

from flask import Blueprint, g, request

import auth
import calc
import constants as K
import derive
import response
import validation as V
from db import store
from errors import ApiError
from rounding import dec, q2, q3
from timeutil import parse_dt, plus_days
from validation import Field as F

bp = Blueprint("api", __name__)

ZERO = Decimal("0")
LIVE_SITE_STATUSES = ("DRAFT", "SCREENED", "COMMITTED")


# --------------------------------------------------------------------------- #
# plumbing
# --------------------------------------------------------------------------- #
def public(row):
    return {key: value for key, value in row.items() if not key.startswith("_")}


class Out:
    def __init__(self, row=None, rows=None, status=200, meta=None, empty=False):
        self.row = row
        self.rows = rows
        self.status = status
        self.meta = meta
        self.empty = empty

    def render(self):
        if self.rows is not None:
            return response.success(
                [public(row) for row in self.rows], "array", self.status, self.meta
            )
        if self.empty or self.row is None:
            return response.success({}, "object", self.status)
        return response.success(public(self.row), "object", self.status)


def endpoint(roles, mutating=True):
    def decorator(handler):
        @functools.wraps(handler)
        def wrapper(**kwargs):
            with store.lock:
                user_id, role = auth.authenticate(roles)
                g.user_id = user_id
                g.role = role
                snapshot = store.snapshot() if mutating else None
                out = handler(**kwargs)
                if mutating:
                    derive.reconcile()
                    store.apply_versions(snapshot)
                return out.render()

        return wrapper

    return decorator


def new_row(**fields):
    stamp = store.now_iso()
    row = {"id": store.new_id()}
    row.update(fields)
    row["created_at"] = stamp
    row["updated_at"] = stamp
    row["version"] = 1
    row["_seq"] = store.next_seq()
    return row


def find(collection, row_id, error_id):
    row = store.coll(collection).get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def page(rows, limit, offset):
    total = len(rows)
    window = rows[offset : offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }
    return Out(rows=window, meta=meta)


def require_window(start, end):
    if parse_dt(end) <= parse_dt(start):
        raise ApiError("ERR_INVALID_WINDOW")


def program_of_site(site):
    return store.programs.get(site["program_id"])


# --------------------------------------------------------------------------- #
# siting programs
# --------------------------------------------------------------------------- #
PROGRAM_FIELDS = [
    F("name", "string"),
    F("target_load_mw", "number", gt=0),
    F("required_energization_date", "datetime"),
    F("capital_budget_usd", "number", ge=0),
]


@bp.post("/siting-programs")
@endpoint(["PortfolioDirector"])
def create_program():
    data = V.validate(PROGRAM_FIELDS)
    row = new_row(
        name=data["name"],
        target_load_mw=data["target_load_mw"],
        required_energization_date=data["required_energization_date"],
        capital_budget_usd=data["capital_budget_usd"],
        program_annual_load_mwh=calc.program_annual_load(data["target_load_mw"]),
        program_status="SCREENING",
        committed_load_mw=q3(ZERO),
        renewable_coverage_pct=q2(ZERO),
        option_exposure_usd=q2(ZERO),
        forfeited_premium_usd=q2(ZERO),
        capitalized_premium_usd=q2(ZERO),
        premium_committed_total_usd=q2(ZERO),
        full_land_control_site_count=0,
    )
    store.programs[row["id"]] = row
    return Out(row=row, status=201)


@bp.get("/siting-programs/<program_id>")
@endpoint(
    ["PortfolioDirector", "SiteScreeningAnalyst", "CapitalCommitteeChair"],
    mutating=False,
)
def read_program(program_id):
    return Out(row=find("programs", program_id, "ERR_PROGRAM_NOT_FOUND"))


@bp.get("/siting-programs/<program_id>/power-purchase-agreements")
@endpoint(["PortfolioDirector", "CapitalCommitteeChair"], mutating=False)
def list_program_ppas(program_id):
    limit, offset = V.pagination()
    find("programs", program_id, "ERR_PROGRAM_NOT_FOUND")
    rows = derive.ppas_of_program(program_id)
    status = request.args.get("status")
    if status:
        rows = [row for row in rows if row["status"] == status]
    return page(rows, limit, offset)


@bp.post("/siting-programs/<program_id>/option-expiry-sweep")
@endpoint(["PortfolioDirector"])
def option_expiry_sweep(program_id):
    program = find("programs", program_id, "ERR_PROGRAM_NOT_FOUND")
    derive.expire_options(program)
    return Out(row=program)


# --------------------------------------------------------------------------- #
# utilities
# --------------------------------------------------------------------------- #
UTILITY_FIELDS = [
    F("name", "string"),
    F("state_code", "string", state_code=True),
    F("balancing_authority", "string"),
    F("total_transmission_capacity_mw", "number", gt=0),
    F("interconnect_study_fee_per_mw_usd", "number", ge=0),
    F("network_upgrade_rate_usd_per_mw", "number", ge=0),
    F("commissioning_buffer_days", "integer", required=False, default=90, ge=0),
    F("energization_lead_days", "integer", ge=0),
    F(
        "queue_policy",
        "enum",
        required=False,
        default="FIRST_COME_FIRST_SERVED",
        enum=K.QUEUE_POLICIES,
    ),
]


@bp.post("/utilities")
@endpoint(["PortfolioDirector"])
def create_utility():
    data = V.validate(UTILITY_FIELDS)
    row = new_row(
        name=data["name"],
        state_code=data["state_code"],
        balancing_authority=data["balancing_authority"],
        total_transmission_capacity_mw=data["total_transmission_capacity_mw"],
        reserved_capacity_mw=q3(ZERO),
        available_capacity_mw=q3(dec(data["total_transmission_capacity_mw"])),
        interconnect_study_fee_per_mw_usd=data["interconnect_study_fee_per_mw_usd"],
        network_upgrade_rate_usd_per_mw=data["network_upgrade_rate_usd_per_mw"],
        commissioning_buffer_days=data["commissioning_buffer_days"],
        energization_lead_days=data["energization_lead_days"],
        queue_policy=data["queue_policy"],
    )
    store.utilities[row["id"]] = row
    return Out(row=row, status=201)


@bp.get("/utilities/<utility_id>")
@endpoint(
    ["PortfolioDirector", "SiteScreeningAnalyst", "UtilityPlanner"], mutating=False
)
def read_utility(utility_id):
    return Out(row=find("utilities", utility_id, "ERR_UTILITY_NOT_FOUND"))


@bp.post("/utilities/<utility_id>/capacity-revisions")
@endpoint(["UtilityPlanner"])
def revise_utility_capacity(utility_id):
    # Ladder step 3: the utility named in the path must be the caller's own.
    if g.user_id != utility_id:
        raise ApiError("ERR_UTILITY_IDENTITY_MISMATCH")
    data = V.validate(
        [F("revised_total_capacity_mw", "number", ge=0), F("reason", "string")]
    )
    utility = find("utilities", utility_id, "ERR_UTILITY_NOT_FOUND")
    derive.revise_capacity(utility, data["revised_total_capacity_mw"])
    store.touch(utility)
    return Out(row=utility)


# --------------------------------------------------------------------------- #
# water sources
# --------------------------------------------------------------------------- #
@bp.post("/water-sources")
@endpoint(["PermittingAuthority"])
def create_water_source():
    data = V.validate(
        [
            F("name", "string"),
            F("basin_code", "string"),
            F("state_code", "string", state_code=True),
            F("annual_permitted_mgal", "number", gt=0),
        ]
    )
    row = new_row(
        name=data["name"],
        basin_code=data["basin_code"],
        state_code=data["state_code"],
        annual_permitted_mgal=data["annual_permitted_mgal"],
        drought_stage="NORMAL",
        stage_curtailment_pct=q2(ZERO),
        effective_supply_mgal=calc.effective_supply(
            data["annual_permitted_mgal"], "NORMAL"
        ),
        committed_annual_demand_mgal=q3(ZERO),
        last_declaration_effective_date=None,
    )
    store.water_sources[row["id"]] = row
    return Out(row=row, status=201)


@bp.get("/water-sources/<source_id>")
@endpoint(
    ["PortfolioDirector", "SiteScreeningAnalyst", "PermittingAuthority"],
    mutating=False,
)
def read_water_source(source_id):
    return Out(row=find("water_sources", source_id, "ERR_WATER_SOURCE_NOT_FOUND"))


@bp.post("/water-sources/<source_id>/drought-declarations")
@endpoint(["PermittingAuthority"])
def declare_drought(source_id):
    data = V.validate(
        [
            F("drought_stage", "enum", enum=K.DROUGHT_STAGES),
            F("effective_date", "datetime"),
        ]
    )
    source = find("water_sources", source_id, "ERR_WATER_SOURCE_NOT_FOUND")

    # A declaration must move the basin, and may not be backdated behind the
    # previous declaration; neither is a legal declaration.
    if data["drought_stage"] == source["drought_stage"]:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "The requested drought stage is already the basin's current stage.",
        )
    previous = source["last_declaration_effective_date"]
    if previous is not None and parse_dt(data["effective_date"]) < parse_dt(previous):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "effective_date may not fall earlier than the last declaration.",
        )

    source["drought_stage"] = data["drought_stage"]
    source["stage_curtailment_pct"] = q2(K.STAGE_CURTAILMENT[data["drought_stage"]])
    source["effective_supply_mgal"] = calc.effective_supply(
        source["annual_permitted_mgal"], data["drought_stage"]
    )
    source["last_declaration_effective_date"] = data["effective_date"]
    derive.refresh_water_feasibility(source["id"])
    return Out(row=source)


# --------------------------------------------------------------------------- #
# candidate sites
# --------------------------------------------------------------------------- #
@bp.post("/candidate-sites")
@endpoint(["SiteScreeningAnalyst"])
def create_site():
    data = V.validate(
        [
            F("program_id", "string"),
            F("utility_id", "string"),
            F("water_source_id", "string"),
            F("name", "string"),
            F("state_code", "string", state_code=True),
            F("county", "string"),
            F("gross_acres", "number", gt=0),
        ]
    )
    # Body references resolve in declaration order.
    find("programs", data["program_id"], "ERR_PROGRAM_NOT_FOUND")
    find("utilities", data["utility_id"], "ERR_UTILITY_NOT_FOUND")
    find("water_sources", data["water_source_id"], "ERR_WATER_SOURCE_NOT_FOUND")

    row = new_row(
        program_id=data["program_id"],
        utility_id=data["utility_id"],
        water_source_id=data["water_source_id"],
        name=data["name"],
        state_code=data["state_code"],
        county=data["county"],
        gross_acres=data["gross_acres"],
        status="DRAFT",
        transmission_headroom_mw=None,
        fiber_route_count=None,
        seismic_hazard_index=None,
        flood_hazard_index=None,
        wind_hazard_index=None,
        craft_labor_supply_index=None,
        construction_peak_headcount=None,
        wage_premium_pct=None,
        cooling_type=None,
        annual_water_demand_mgal=None,
        hazard_tier=None,
        workforce_availability_ratio=None,
        water_headroom_mgal=None,
        water_feasible=False,
        screening_score=None,
        energization_risk_tier="ON_TRACK",
        land_control_pct=q2(ZERO),
        land_control_status="NONE",
        site_capital_commitment_usd=q2(ZERO),
        screened_by_user_id=None,
        committed_by_user_id=None,
        disqualification_reason=None,
    )
    store.sites[row["id"]] = row
    return Out(row=row, status=201)


@bp.get("/candidate-sites")
@endpoint(
    ["SiteScreeningAnalyst", "PortfolioDirector", "CapitalCommitteeChair"],
    mutating=False,
)
def list_sites():
    limit, offset = V.pagination()
    rows = derive.ordered(list(store.sites.values()))
    for key in ("program_id", "utility_id", "water_source_id", "status"):
        wanted = request.args.get(key)
        if wanted:
            rows = [row for row in rows if row[key] == wanted]
    return page(rows, limit, offset)


@bp.get("/candidate-sites/<site_id>")
@endpoint(
    ["SiteScreeningAnalyst", "PortfolioDirector", "CapitalCommitteeChair"],
    mutating=False,
)
def read_site(site_id):
    return Out(row=find("sites", site_id, "ERR_SITE_NOT_FOUND"))


SCREEN_FIELDS = [
    F("transmission_headroom_mw", "number", ge=0),
    F("fiber_route_count", "integer", ge=0),
    F("seismic_hazard_index", "number", ge=0, le=1),
    F("flood_hazard_index", "number", ge=0, le=1),
    F("wind_hazard_index", "number", ge=0, le=1),
    F("craft_labor_supply_index", "integer", ge=0),
    F("construction_peak_headcount", "integer", gt=0),
    F("wage_premium_pct", "number", ge=0),
    F("cooling_type", "enum", enum=K.COOLING_TYPES),
    F("annual_water_demand_mgal", "number", ge=0),
]


@bp.post("/candidate-sites/<site_id>/screen")
@endpoint(["SiteScreeningAnalyst"])
def screen_site(site_id):
    data = V.validate(SCREEN_FIELDS)
    # An air-cooled campus must declare exactly zero cooling water.
    if data["cooling_type"] == "AIR_COOLED" and dec(data["annual_water_demand_mgal"]) != 0:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "An AIR_COOLED campus must declare an annual water demand of exactly 0.",
        )
    site = find("sites", site_id, "ERR_SITE_NOT_FOUND")
    if site["status"] != "DRAFT":
        raise ApiError("ERR_SITE_INVALID_STATE")

    program = program_of_site(site)
    for key in SCREEN_FIELDS:
        site[key.name] = data[key.name]

    site["hazard_tier"] = calc.hazard_tier(
        data["seismic_hazard_index"],
        data["flood_hazard_index"],
        data["wind_hazard_index"],
    )
    site["workforce_availability_ratio"] = calc.workforce_ratio(
        data["craft_labor_supply_index"], data["construction_peak_headcount"]
    )
    site["status"] = "SCREENED"
    site["screened_by_user_id"] = g.user_id

    # Headroom and feasibility for this site and for every sibling on the basin.
    derive.refresh_water_feasibility(site["water_source_id"])

    site["screening_score"] = calc.screening_score(
        site["transmission_headroom_mw"],
        program["target_load_mw"],
        site["fiber_route_count"],
        site["annual_water_demand_mgal"],
        site["water_headroom_mgal"],
        site["workforce_availability_ratio"],
        site["wage_premium_pct"],
        site["gross_acres"],
        site["hazard_tier"],
    )
    return Out(row=site)


@bp.post("/candidate-sites/<site_id>/commit")
@endpoint(["CapitalCommitteeChair"])
def commit_site(site_id):
    site = find("sites", site_id, "ERR_SITE_NOT_FOUND")
    if site["status"] != "SCREENED":
        raise ApiError("ERR_SITE_INVALID_STATE")

    program = program_of_site(site)

    # 21 - segregation of duties
    if g.user_id == site["screened_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    # 22 - hazard prohibition
    if site["hazard_tier"] == "SEVERE":
        raise ApiError("ERR_HAZARD_TIER_PROHIBITED")
    # 23 - zoning approval
    zoning = derive.zoning_of(site["id"])
    if zoning is None or zoning["status"] != "APPROVED_WITH_CONDITIONS":
        raise ApiError("ERR_ZONING_NOT_APPROVED")
    # 31 - one committed site per program
    for sibling in derive.sites_of_program(site["program_id"]):
        if sibling["id"] != site["id"] and sibling["status"] == "COMMITTED":
            raise ApiError("ERR_SITE_COMMITMENT_EXISTS")
    # 32 - complete land control
    if dec(site["land_control_pct"]) < 100:
        raise ApiError("ERR_LAND_CONTROL_INCOMPLETE")
    # 33 - ratified state incentives
    ratified = any(
        n["authority_level"] == "STATE" and n["status"] == "RATIFIED"
        for n in derive.negotiations_of(site["id"])
    )
    if not ratified:
        raise ApiError("ERR_INCENTIVES_NOT_RATIFIED")
    # 35 - water sufficiency
    if not site["water_feasible"]:
        raise ApiError("ERR_WATER_SUPPLY_INSUFFICIENT")
    # 36 - renewable coverage floor
    if dec(program["renewable_coverage_pct"]) < K.MIN_RENEWABLE_COVERAGE_PCT:
        raise ApiError("ERR_RENEWABLE_COVERAGE_INSUFFICIENT")
    # 38 - capital ceiling, deliberately the last gate of all
    capital = derive.site_capital_value(site)
    if capital > dec(program["capital_budget_usd"]):
        raise ApiError("ERR_CAPITAL_BUDGET_EXCEEDED")

    site["status"] = "COMMITTED"
    site["committed_by_user_id"] = g.user_id
    site["site_capital_commitment_usd"] = capital
    derive.mark_capital(site["id"])
    return Out(row=site)


@bp.post("/candidate-sites/<site_id>/disqualify")
@endpoint(["PortfolioDirector"])
def disqualify_site(site_id):
    data = V.validate([F("disqualification_reason", "string")])
    site = find("sites", site_id, "ERR_SITE_NOT_FOUND")
    if site["status"] == "DISQUALIFIED":
        raise ApiError("ERR_SITE_INVALID_STATE")
    derive.disqualify_site(site, data["disqualification_reason"])
    return Out(row=site)


@bp.get("/candidate-sites/<site_id>/incentive-negotiations")
@endpoint(
    ["IncentiveNegotiator", "PortfolioDirector", "CapitalCommitteeChair"],
    mutating=False,
)
def list_site_negotiations(site_id):
    limit, offset = V.pagination()
    find("sites", site_id, "ERR_SITE_NOT_FOUND")
    rows = derive.negotiations_of(site_id)
    for key in ("authority_level", "status"):
        wanted = request.args.get(key)
        if wanted:
            rows = [row for row in rows if row[key] == wanted]
    return page(rows, limit, offset)


@bp.get("/candidate-sites/<site_id>/zoning-applications")
@endpoint(
    ["SiteScreeningAnalyst", "PortfolioDirector", "PermittingAuthority"],
    mutating=False,
)
def list_site_zoning(site_id):
    limit, offset = V.pagination()
    find("sites", site_id, "ERR_SITE_NOT_FOUND")
    rows = derive.ordered(
        [row for row in store.zoning.values() if row["site_id"] == site_id]
    )
    wanted = request.args.get("status")
    if wanted:
        rows = [row for row in rows if row["status"] == wanted]
    return page(rows, limit, offset)


# --------------------------------------------------------------------------- #
# interconnection applications
# --------------------------------------------------------------------------- #
@bp.post("/interconnection-applications")
@endpoint(["SiteScreeningAnalyst"])
def create_application():
    data = V.validate(
        [
            F("site_id", "string"),
            F("utility_id", "string"),
            F("requested_mw", "number", gt=0),
            F("window_start", "datetime"),
            F("window_end", "datetime"),
        ]
    )
    require_window(data["window_start"], data["window_end"])
    # Declaration order puts utility_id ahead of site_id.
    utility = find("utilities", data["utility_id"], "ERR_UTILITY_NOT_FOUND")
    site = find("sites", data["site_id"], "ERR_SITE_NOT_FOUND")

    if site["status"] not in LIVE_SITE_STATUSES:
        raise ApiError("ERR_SITE_INVALID_STATE")
    if site["utility_id"] != utility["id"]:
        raise ApiError(
            "ERR_APPLICATION_SITE_UTILITY_MISMATCH",
            "The application's utility_id must equal the site's utility_id.",
        )
    if derive.live_app(site["id"]) is not None:
        raise ApiError("ERR_DUPLICATE_APPLICATION")

    row = new_row(
        site_id=site["id"],
        utility_id=utility["id"],
        requested_mw=data["requested_mw"],
        window_start=data["window_start"],
        window_end=data["window_end"],
        status="DRAFT",
        submitted_at=None,
        queue_position=0,
        study_round=0,
        diversified_peak_mw=None,
        study_fee_usd=q2(ZERO),
        network_upgrade_cost_usd=q2(ZERO),
        reserved_mw=q3(ZERO),
        committed_energization_date=None,
        delay_exposure_usd=q2(ZERO),
        withdrawal_reason=None,
    )
    store.applications[row["id"]] = row
    return Out(row=row, status=201)


@bp.get("/interconnection-applications")
@endpoint(
    ["SiteScreeningAnalyst", "PortfolioDirector", "UtilityPlanner"], mutating=False
)
def list_applications():
    limit, offset = V.pagination()
    rows = derive.ordered(list(store.applications.values()))
    for key in ("site_id", "utility_id", "status"):
        wanted = request.args.get(key)
        if wanted:
            rows = [row for row in rows if row[key] == wanted]
    return page(rows, limit, offset)


@bp.get("/interconnection-applications/<application_id>")
@endpoint(
    ["SiteScreeningAnalyst", "PortfolioDirector", "UtilityPlanner"], mutating=False
)
def read_application(application_id):
    return Out(row=find("applications", application_id, "ERR_APPLICATION_NOT_FOUND"))


@bp.post("/interconnection-applications/<application_id>/submit")
@endpoint(["SiteScreeningAnalyst"])
def submit_application(application_id):
    app = find("applications", application_id, "ERR_APPLICATION_NOT_FOUND")
    if app["status"] != "DRAFT":
        raise ApiError("ERR_APPLICATION_INVALID_STATE")
    site = store.sites.get(app["site_id"])
    if site is None or site["status"] != "SCREENED":
        raise ApiError("ERR_SITE_NOT_SCREENED")

    utility = store.utilities.get(app["utility_id"])
    app["status"] = "SUBMITTED"
    app["submitted_at"] = store.now_iso()
    app["study_fee_usd"] = q2(
        dec(app["requested_mw"]) * dec(utility["interconnect_study_fee_per_mw_usd"])
    )
    derive.mark_capital(site["id"])
    return Out(row=app)


def _bind_utility(application_id):
    """Ladder step 3 for the three application-scoped UtilityPlanner writes."""
    app = store.applications.get(application_id)
    if app is not None and app["utility_id"] != g.user_id:
        raise ApiError("ERR_UTILITY_IDENTITY_MISMATCH")


@bp.post("/interconnection-applications/<application_id>/load-studies")
@endpoint(["UtilityPlanner"])
def file_load_study(application_id):
    _bind_utility(application_id)
    data = V.validate(
        [
            F("it_load_mw", "number", ge=0),
            F("cooling_load_mw", "number", ge=0),
            F("ancillary_load_mw", "number", ge=0),
            F("diversity_factor", "number", gt=0, le=1),
        ]
    )
    app = find("applications", application_id, "ERR_APPLICATION_NOT_FOUND")
    if app["status"] not in ("SUBMITTED", "STUDY_COMPLETE"):
        raise ApiError("ERR_APPLICATION_INVALID_STATE")

    utility = store.utilities.get(app["utility_id"])
    site = store.sites.get(app["site_id"])
    nameplate, diversified, upgrade_required, cost = calc.load_study_figures(
        data["it_load_mw"],
        data["cooling_load_mw"],
        data["ancillary_load_mw"],
        data["diversity_factor"],
        utility["total_transmission_capacity_mw"],
        utility["network_upgrade_rate_usd_per_mw"],
        site["hazard_tier"] if site else None,
    )

    app["study_round"] = int(app["study_round"]) + 1
    app["status"] = "STUDY_COMPLETE"

    study = {
        "id": store.new_id(),
        "application_id": app["id"],
        "study_round": app["study_round"],
        "it_load_mw": data["it_load_mw"],
        "cooling_load_mw": data["cooling_load_mw"],
        "ancillary_load_mw": data["ancillary_load_mw"],
        "diversity_factor": data["diversity_factor"],
        "nameplate_peak_mw": nameplate,
        "diversified_peak_mw": diversified,
        "upgrade_required": upgrade_required,
        "network_upgrade_cost_usd": cost,
        "filed_by_user_id": g.user_id,
        "created_at": store.now_iso(),
        "_seq": store.next_seq(),
    }
    store.load_studies[study["id"]] = study
    if site is not None:
        derive.mark_capital(site["id"])
    return Out(row=study, status=201)


@bp.get("/interconnection-applications/<application_id>/load-studies")
@endpoint(
    ["UtilityPlanner", "SiteScreeningAnalyst", "PortfolioDirector"], mutating=False
)
def list_load_studies(application_id):
    limit, offset = V.pagination()
    find("applications", application_id, "ERR_APPLICATION_NOT_FOUND")
    return page(derive.studies_of(application_id), limit, offset)


@bp.post("/interconnection-applications/<application_id>/reserve-capacity")
@endpoint(["UtilityPlanner"])
def reserve_capacity(application_id):
    _bind_utility(application_id)
    app = find("applications", application_id, "ERR_APPLICATION_NOT_FOUND")
    if app["status"] != "STUDY_COMPLETE":
        raise ApiError("ERR_APPLICATION_NOT_STUDIED")

    utility = store.utilities.get(app["utility_id"])
    requested = dec(app["requested_mw"])
    diversified = dec(app["diversified_peak_mw"] or 0)

    # 30 - restudy tolerance precedes the aggregate capacity test.
    drift = abs(requested - diversified) / requested
    if drift > K.RESTUDY_TOLERANCE:
        raise ApiError("ERR_STUDY_LOAD_MISMATCH")

    # 34 - buffered overlap aggregate; equality with the ceiling is admissible.
    concurrent = derive.concurrent_mw(app, utility)
    if q3(concurrent + requested) > q3(dec(utility["total_transmission_capacity_mw"])):
        raise ApiError("ERR_TRANSMISSION_CAPACITY_EXCEEDED")

    app["status"] = "CAPACITY_RESERVED"
    app["reserved_mw"] = q3(requested)
    return Out(row=app)


@bp.post("/interconnection-applications/<application_id>/commit-energization")
@endpoint(["UtilityPlanner"])
def commit_energization(application_id):
    _bind_utility(application_id)
    data = V.validate([F("committed_energization_date", "datetime")])
    app = find("applications", application_id, "ERR_APPLICATION_NOT_FOUND")
    if app["status"] != "CAPACITY_RESERVED":
        raise ApiError("ERR_APPLICATION_INVALID_STATE")

    utility = store.utilities.get(app["utility_id"])
    site = store.sites.get(app["site_id"])
    program = program_of_site(site) if site else None
    committed = parse_dt(data["committed_energization_date"])

    if committed < parse_dt(app["window_start"]):
        raise ApiError("ERR_ENERGIZATION_DEADLINE_MISSED")
    if committed < plus_days(store.clock, utility["energization_lead_days"]):
        raise ApiError("ERR_ENERGIZATION_DEADLINE_MISSED")
    days = calc.delay_days(
        data["committed_energization_date"], program["required_energization_date"]
    )
    if days > K.MAX_ENERGIZATION_DELAY_DAYS:
        raise ApiError("ERR_ENERGIZATION_DEADLINE_MISSED")

    app["status"] = "ENERGIZATION_COMMITTED"
    app["committed_energization_date"] = data["committed_energization_date"]
    app["delay_exposure_usd"] = calc.delay_exposure(days, app["requested_mw"])
    return Out(row=app)


@bp.post("/interconnection-applications/<application_id>/withdraw")
@endpoint(["SiteScreeningAnalyst"])
def withdraw_application(application_id):
    data = V.validate([F("withdrawal_reason", "string")])
    app = find("applications", application_id, "ERR_APPLICATION_NOT_FOUND")
    if app["status"] == "WITHDRAWN":
        raise ApiError("ERR_APPLICATION_INVALID_STATE")

    app["status"] = "WITHDRAWN"
    app["withdrawal_reason"] = data["withdrawal_reason"]
    app["reserved_mw"] = q3(ZERO)
    app["queue_position"] = 0
    derive.mark_capital(app["site_id"])
    return Out(row=app)


# --------------------------------------------------------------------------- #
# incentive negotiations
# --------------------------------------------------------------------------- #
@bp.post("/incentive-negotiations")
@endpoint(["IncentiveNegotiator"])
def create_negotiation():
    data = V.validate(
        [
            F("site_id", "string"),
            F("authority_level", "enum", enum=K.AUTHORITY_LEVELS),
            F("counterparty_name", "string"),
        ]
    )
    site = find("sites", data["site_id"], "ERR_SITE_NOT_FOUND")
    if site["status"] not in LIVE_SITE_STATUSES:
        raise ApiError("ERR_SITE_INVALID_STATE")
    for existing in derive.negotiations_of(site["id"]):
        if existing["authority_level"] == data["authority_level"]:
            raise ApiError("ERR_DUPLICATE_NEGOTIATION")

    row = new_row(
        site_id=site["id"],
        authority_level=data["authority_level"],
        counterparty_name=data["counterparty_name"],
        status="DRAFT",
        round_count=0,
        last_party=None,
        sales_tax_exemption_pct=None,
        abatement_years=None,
        abatement_pct=None,
        jobs_commitment=None,
        capex_commitment_usd=None,
        npv_incentive_usd=q2(ZERO),
        sales_tax_benefit_usd=q2(ZERO),
        abatement_npv_usd=q2(ZERO),
        clawback_exposure_usd=q2(ZERO),
        signed_by_user_id=None,
        ratified_by_user_id=None,
    )
    store.negotiations[row["id"]] = row
    return Out(row=row, status=201)


@bp.post("/incentive-negotiations/<negotiation_id>/rounds")
@endpoint(["IncentiveNegotiator", "PermittingAuthority"])
def record_round(negotiation_id):
    data = V.validate(
        [
            F("submitted_by_party", "enum", enum=K.PARTIES),
            F("sales_tax_exemption_pct", "number", ge=0, le=1),
            F("abatement_years", "integer", ge=1, le=30),
            F("abatement_pct", "number", ge=0, le=1),
            F("jobs_commitment", "integer", ge=0),
            F("capex_commitment_usd", "number", gt=0),
        ]
    )
    negotiation = find("negotiations", negotiation_id, "ERR_NEGOTIATION_NOT_FOUND")

    # The opening round additionally requires the site to be DRAFT or SCREENED.
    if negotiation["status"] == "DRAFT":
        site = store.sites.get(negotiation["site_id"])
        if site is None or site["status"] not in ("DRAFT", "SCREENED"):
            raise ApiError("ERR_SITE_INVALID_STATE")

    if negotiation["status"] not in (
        "DRAFT",
        "AUTHORITY_COUNTER_PENDING",
        "COMPANY_OFFER_PENDING",
    ):
        raise ApiError("ERR_NEGOTIATION_INVALID_STATE")

    expected = (
        "AUTHORITY" if negotiation["status"] == "AUTHORITY_COUNTER_PENDING" else "COMPANY"
    )
    if data["submitted_by_party"] != expected:
        raise ApiError("ERR_WRONG_NEGOTIATION_PARTY")

    negotiation["sales_tax_exemption_pct"] = data["sales_tax_exemption_pct"]
    negotiation["abatement_years"] = data["abatement_years"]
    negotiation["abatement_pct"] = data["abatement_pct"]
    negotiation["jobs_commitment"] = data["jobs_commitment"]
    negotiation["capex_commitment_usd"] = data["capex_commitment_usd"]
    negotiation["round_count"] = int(negotiation["round_count"]) + 1
    negotiation["last_party"] = data["submitted_by_party"]
    negotiation["status"] = (
        "COMPANY_OFFER_PENDING"
        if data["submitted_by_party"] == "AUTHORITY"
        else "AUTHORITY_COUNTER_PENDING"
    )

    sales, abatement, npv, clawback = calc.incentive_money(
        data["capex_commitment_usd"],
        data["sales_tax_exemption_pct"],
        data["abatement_years"],
        data["abatement_pct"],
        data["jobs_commitment"],
    )
    negotiation["sales_tax_benefit_usd"] = sales
    negotiation["abatement_npv_usd"] = abatement
    negotiation["npv_incentive_usd"] = npv
    negotiation["clawback_exposure_usd"] = clawback
    return Out(row=negotiation)


@bp.post("/incentive-negotiations/<negotiation_id>/sign")
@endpoint(["IncentiveNegotiator"])
def sign_negotiation(negotiation_id):
    negotiation = find("negotiations", negotiation_id, "ERR_NEGOTIATION_NOT_FOUND")
    if (
        negotiation["status"] != "COMPANY_OFFER_PENDING"
        or int(negotiation["round_count"]) < K.MIN_NEGOTIATION_ROUNDS
    ):
        raise ApiError("ERR_NEGOTIATION_INVALID_STATE")
    negotiation["status"] = "SIGNED"
    negotiation["signed_by_user_id"] = g.user_id
    return Out(row=negotiation)


@bp.post("/incentive-negotiations/<negotiation_id>/ratify")
@endpoint(["CapitalCommitteeChair"])
def ratify_negotiation(negotiation_id):
    negotiation = find("negotiations", negotiation_id, "ERR_NEGOTIATION_NOT_FOUND")
    if negotiation["status"] != "SIGNED":
        raise ApiError("ERR_NEGOTIATION_INVALID_STATE")
    if g.user_id == negotiation["signed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    zoning = derive.zoning_of(negotiation["site_id"])
    if zoning is None or zoning["status"] != "APPROVED_WITH_CONDITIONS":
        raise ApiError("ERR_ZONING_NOT_APPROVED")
    negotiation["status"] = "RATIFIED"
    negotiation["ratified_by_user_id"] = g.user_id
    return Out(row=negotiation)


# --------------------------------------------------------------------------- #
# zoning
# --------------------------------------------------------------------------- #
@bp.post("/zoning-applications")
@endpoint(["SiteScreeningAnalyst"])
def create_zoning():
    data = V.validate(
        [
            F("site_id", "string"),
            F("jurisdiction", "string"),
            F("hearing_date", "datetime"),
            F("noise_limit_dba", "number", gt=0),
            F("projected_noise_dba", "number", gt=0),
            F("visual_mitigation_tier", "enum", enum=K.MITIGATION_TIERS),
        ]
    )
    site = find("sites", data["site_id"], "ERR_SITE_NOT_FOUND")
    if site["status"] not in LIVE_SITE_STATUSES:
        raise ApiError("ERR_SITE_INVALID_STATE")
    if derive.zoning_of(site["id"]) is not None:
        raise ApiError("ERR_DUPLICATE_ZONING_APPLICATION")

    row = new_row(
        site_id=site["id"],
        jurisdiction=data["jurisdiction"],
        hearing_date=data["hearing_date"],
        noise_limit_dba=data["noise_limit_dba"],
        projected_noise_dba=data["projected_noise_dba"],
        visual_mitigation_tier=data["visual_mitigation_tier"],
        status="SUBMITTED",
        continuance_count=0,
        objection_count=0,
        weighted_opposition_score=q2(ZERO),
        noise_excess_dba=ZERO,
        required_mitigation_tier="NONE",
        mitigation_cost_usd=q2(ZERO),
        conditions_escrow_usd=q2(ZERO),
        decision_note=None,
    )
    store.zoning[row["id"]] = row
    derive.zoning_price(row)
    return Out(row=row, status=201)


@bp.post("/zoning-applications/<zoning_id>/community-objections")
@endpoint(["PermittingAuthority"])
def record_objection(zoning_id):
    data = V.validate(
        [
            F("objection_type", "enum", enum=K.OBJECTION_TYPES),
            F("commenter_reference", "string"),
        ]
    )
    zoning = find("zoning", zoning_id, "ERR_ZONING_APPLICATION_NOT_FOUND")
    if zoning["status"] not in ("SUBMITTED", "CONTINUED"):
        raise ApiError("ERR_ZONING_INVALID_STATE")

    objection = {
        "id": store.new_id(),
        "zoning_id": zoning["id"],
        "objection_type": data["objection_type"],
        "commenter_reference": data["commenter_reference"],
        "created_at": store.now_iso(),
        "_seq": store.next_seq(),
    }
    store.objections[objection["id"]] = objection
    derive.zoning_price(zoning)
    return Out(row=zoning)


@bp.post("/zoning-applications/<zoning_id>/decide")
@endpoint(["PermittingAuthority"])
def decide_zoning(zoning_id):
    data = V.validate(
        [
            F("outcome", "enum", enum=K.ZONING_OUTCOMES),
            F("decision_note", "string", required=False),
        ]
    )
    zoning = find("zoning", zoning_id, "ERR_ZONING_APPLICATION_NOT_FOUND")
    if zoning["status"] not in ("SUBMITTED", "CONTINUED"):
        raise ApiError("ERR_ZONING_INVALID_STATE")

    outcome = data["outcome"]
    if outcome == "CONTINUED" and int(zoning["continuance_count"]) >= K.MAX_ZONING_CONTINUANCES:
        raise ApiError("ERR_ZONING_CONTINUANCE_EXHAUSTED")
    if outcome == "APPROVED_WITH_CONDITIONS":
        offered = K.MITIGATION_RANK[zoning["visual_mitigation_tier"]]
        demanded = K.MITIGATION_RANK[zoning["required_mitigation_tier"]]
        if offered < demanded:
            raise ApiError("ERR_MITIGATION_TIER_INSUFFICIENT")

    zoning["decision_note"] = data["decision_note"]
    site = store.sites.get(zoning["site_id"])

    if outcome == "APPROVED_WITH_CONDITIONS":
        zoning["status"] = "APPROVED_WITH_CONDITIONS"
        derive.zoning_price(zoning)
        if site is not None:
            derive.mark_capital(site["id"])
    elif outcome == "CONTINUED":
        zoning["status"] = "CONTINUED"
        zoning["continuance_count"] = int(zoning["continuance_count"]) + 1
        derive.zoning_price(zoning)
        if site is not None:
            derive.mark_capital(site["id"])
    else:
        # A denied campus is not priced: cost and escrow stay as they were.
        zoning["status"] = "DENIED"
        if site is not None and site["status"] != "DISQUALIFIED":
            derive.disqualify_site(site, "ZONING_DENIED")
    return Out(row=zoning)


# --------------------------------------------------------------------------- #
# power purchase agreements
# --------------------------------------------------------------------------- #
@bp.post("/power-purchase-agreements")
@endpoint(["PortfolioDirector"])
def create_ppa():
    data = V.validate(
        [
            F("program_id", "string"),
            F("counterparty_name", "string"),
            F("technology", "enum", enum=K.PPA_TECHNOLOGIES),
            F("contracted_capacity_mw", "number", gt=0),
            F("annual_generation_mwh", "number", gt=0),
            F("hourly_matched_mwh", "number", ge=0),
            F("strike_price_usd_per_mwh", "number", gt=0),
            F("matching_mode", "enum", enum=K.MATCHING_MODES),
            F("delivery_start", "datetime"),
            F("delivery_end", "datetime"),
        ]
    )
    if dec(data["hourly_matched_mwh"]) > dec(data["annual_generation_mwh"]):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "hourly_matched_mwh may not exceed annual_generation_mwh.",
        )
    require_window(data["delivery_start"], data["delivery_end"])
    program = find("programs", data["program_id"], "ERR_PROGRAM_NOT_FOUND")

    row = new_row(
        program_id=program["id"],
        counterparty_name=data["counterparty_name"],
        technology=data["technology"],
        contracted_capacity_mw=data["contracted_capacity_mw"],
        annual_generation_mwh=data["annual_generation_mwh"],
        hourly_matched_mwh=data["hourly_matched_mwh"],
        strike_price_usd_per_mwh=data["strike_price_usd_per_mwh"],
        matching_mode=data["matching_mode"],
        delivery_start=data["delivery_start"],
        delivery_end=data["delivery_end"],
        status="DRAFT",
        credited_coverage_mwh=q3(ZERO),
        annual_cost_usd=calc.annual_cost(
            data["annual_generation_mwh"], data["strike_price_usd_per_mwh"]
        ),
    )
    store.ppas[row["id"]] = row
    return Out(row=row, status=201)


@bp.post("/power-purchase-agreements/<ppa_id>/execute")
@endpoint(["PortfolioDirector"])
def execute_ppa(ppa_id):
    ppa = find("ppas", ppa_id, "ERR_PPA_NOT_FOUND")
    if ppa["status"] != "DRAFT":
        raise ApiError("ERR_PPA_INVALID_STATE")
    ppa["status"] = "EXECUTED"
    return Out(row=ppa)


# --------------------------------------------------------------------------- #
# land parcel options
# --------------------------------------------------------------------------- #
@bp.post("/parcel-options")
@endpoint(["SiteScreeningAnalyst"])
def create_option():
    data = V.validate(
        [
            F("site_id", "string"),
            F("parcel_apn", "string"),
            F("phase_index", "integer", ge=1),
            F("acres", "number", gt=0),
            F("option_premium_usd", "number", ge=0),
            F("purchase_price_usd", "number", gt=0),
            F(
                "premium_credit_pct",
                "number",
                required=False,
                default=Decimal("0.5"),
                ge=0,
                le=1,
            ),
            F("window_start", "datetime"),
            F("window_end", "datetime"),
            F("replaces_option_id", "string", required=False),
            F("expected_site_version", "integer"),
        ]
    )
    require_window(data["window_start"], data["window_end"])
    if parse_dt(data["window_start"]) < store.clock:
        raise ApiError("ERR_OPTION_WINDOW_BACKDATED")

    site = find("sites", data["site_id"], "ERR_SITE_NOT_FOUND")
    predecessor = None
    if data["replaces_option_id"] is not None:
        predecessor = find(
            "options", data["replaces_option_id"], "ERR_PARCEL_OPTION_NOT_FOUND"
        )

    # 9 - the site is the serialization point for land-control rewrites.
    if int(data["expected_site_version"]) != int(site["version"]):
        raise ApiError("ERR_STALE_SITE_VERSION")
    # 10 - site state
    if site["status"] not in LIVE_SITE_STATUSES:
        raise ApiError("ERR_SITE_INVALID_STATE")
    if predecessor is not None:
        # 18 - the superseded option must still be open
        if predecessor["status"] != "OPTIONED":
            raise ApiError("ERR_OPTION_INVALID_STATE")
        # 25 - and must belong to the same site and the same parcel
        if (
            predecessor["site_id"] != site["id"]
            or predecessor["parcel_apn"] != data["parcel_apn"]
        ):
            raise ApiError(
                "ERR_APPLICATION_SITE_UTILITY_MISMATCH",
                "The superseded option must belong to the same site and parcel.",
            )
    # 29 - exclusivity is per (site_id, parcel_apn) over half-open windows
    for other in derive.options_of(site["id"]):
        if predecessor is not None and other["id"] == predecessor["id"]:
            continue
        if other["parcel_apn"] != data["parcel_apn"]:
            continue
        if other["status"] not in ("OPTIONED", "EXERCISED"):
            continue
        if calc.half_open_overlap(
            data["window_start"],
            data["window_end"],
            other["window_start"],
            other["window_end"],
        ):
            raise ApiError("ERR_OPTION_WINDOW_CONFLICT")

    row = new_row(
        site_id=site["id"],
        replaces_option_id=data["replaces_option_id"],
        parcel_apn=data["parcel_apn"],
        phase_index=data["phase_index"],
        acres=data["acres"],
        option_premium_usd=data["option_premium_usd"],
        purchase_price_usd=data["purchase_price_usd"],
        premium_credit_pct=data["premium_credit_pct"],
        window_start=data["window_start"],
        window_end=data["window_end"],
        status="OPTIONED",
        premium_credited_usd=q2(ZERO),
        net_purchase_usd=q2(ZERO),
        exercised_at=None,
        lapsed_at=None,
    )
    store.options[row["id"]] = row

    if predecessor is not None:
        predecessor["status"] = "RELEASED"

    # Signing an option always advances the addressed site's version by one.
    store.touch(site)
    derive.mark_capital(site["id"])
    return Out(row=row, status=201)


@bp.get("/parcel-options")
@endpoint(["SiteScreeningAnalyst", "PortfolioDirector"], mutating=False)
def list_options():
    limit, offset = V.pagination()
    rows = derive.ordered(list(store.options.values()))
    for key in ("site_id", "replaces_option_id", "status"):
        wanted = request.args.get(key)
        if wanted:
            rows = [row for row in rows if row[key] == wanted]
    return page(rows, limit, offset)


@bp.get("/parcel-options/<option_id>")
@endpoint(["SiteScreeningAnalyst", "PortfolioDirector"], mutating=False)
def read_option(option_id):
    return Out(row=find("options", option_id, "ERR_PARCEL_OPTION_NOT_FOUND"))


@bp.post("/parcel-options/<option_id>/exercise")
@endpoint(["PortfolioDirector"])
def exercise_option(option_id):
    option = find("options", option_id, "ERR_PARCEL_OPTION_NOT_FOUND")
    if option["status"] != "OPTIONED":
        raise ApiError("ERR_OPTION_INVALID_STATE")
    # The window is half-open: a clock at or past window_end is unexercisable.
    if store.clock >= parse_dt(option["window_end"]):
        raise ApiError("ERR_OPTION_EXPIRED")
    app = derive.live_app(option["site_id"])
    if app is None or app["status"] not in K.LIVE_RESERVED_STATUSES:
        raise ApiError(
            "ERR_SITE_NOT_SCREENED",
            "The site's live interconnection application must already hold capacity.",
        )

    option["status"] = "EXERCISED"
    option["exercised_at"] = store.now_iso()
    option["premium_credited_usd"] = calc.premium_credited(
        option["option_premium_usd"], option["premium_credit_pct"]
    )
    option["net_purchase_usd"] = calc.net_purchase(
        option["purchase_price_usd"], option["premium_credited_usd"]
    )
    derive.mark_capital(option["site_id"])
    return Out(row=option)


# --------------------------------------------------------------------------- #
# logical clock
# --------------------------------------------------------------------------- #
@bp.post("/_clock/set_current_utc")
@endpoint(["PortfolioDirector"], mutating=False)
def set_clock():
    data = V.validate([F("to_iso8601", "datetime")])
    store.clock = parse_dt(data["to_iso8601"])
    # Repositioning the clock mutates no entity and runs no sweep.
    return Out(empty=True)
