"""Project endpoints, including the two computed reads."""

from flask import Blueprint

import auth
import serialize
import services
import validate
from envelope import created, ok, ok_list, paginate
from store import base_row, db, now, sorted_rows, touch

bp = Blueprint("projects", __name__)

SET_SEQUENCE_POLICIES = ("STRICT_ASCENDING", "PAIRED_FIRST")
PHASES = (
    "PRECONSTRUCTION",
    "DESIGN_FROZEN",
    "IN_PRODUCTION",
    "SHIPPING",
    "SETTING",
    "CLOSEOUT",
)
POSTURES = (
    "DUAL_BLOCKED",
    "STATE_CLEARED_ONLY",
    "SITE_CLEARED_ONLY",
    "SET_CLEARED",
    "OCCUPANCY_CLEARED",
)


def _state_code(data, name):
    value = validate.field_str(data, name)
    if len(value) != 2 or value != value.upper():
        raise validate.bad("%s must be a 2-character uppercase state code" % name)
    return value


@bp.post("/modular/projects")
@auth.endpoint("ProgramAdmin")
def create_project():
    data = validate.body(optional=False)
    name = validate.field_str(data, "name")
    factory_id = validate.field_id(data, "factory_id")
    state_code = _state_code(data, "state_code")
    ahj_code = validate.field_str(data, "ahj_code")
    planned_module_count = validate.field_int(data, "planned_module_count", minimum=1)
    contract_price_cents = validate.field_int(data, "contract_price_cents", minimum=0)
    crane_capacity_chart = validate.field_crane_chart(data, "crane_capacity_chart")
    deposit_pct = validate.field_num(
        data, "deposit_pct", required=False, default=0.20, exclusive_min=0, maximum=1
    )
    retainage_pct = validate.field_num(
        data, "retainage_pct", required=False, default=0.05, minimum=0, exclusive_max=1
    )
    crane_rigging_buffer_minutes = validate.field_int(
        data, "crane_rigging_buffer_minutes", required=False, default=45, minimum=0
    )
    set_sequence_policy = validate.field_enum(
        data,
        "set_sequence_policy",
        SET_SEQUENCE_POLICIES,
        required=False,
        default="STRICT_ASCENDING",
    )
    weather_exposure_limit_hours = validate.field_num(
        data, "weather_exposure_limit_hours", required=False, default=8.0, exclusive_min=0
    )
    forecast_precip_probability_pct = validate.field_num(
        data,
        "forecast_precip_probability_pct",
        required=False,
        default=0,
        minimum=0,
        maximum=100,
    )
    forecast_wind_gust_mph = validate.field_num(
        data, "forecast_wind_gust_mph", required=False, default=0, minimum=0
    )

    # rank 5 — body foreign key
    services.get_factory(factory_id)

    row = base_row()
    row.update(
        {
            "name": name,
            "factory_id": factory_id,
            "state_code": state_code,
            "ahj_code": ahj_code,
            "planned_module_count": planned_module_count,
            "contract_price_cents": contract_price_cents,
            "deposit_pct": deposit_pct,
            "retainage_pct": retainage_pct,
            "crane_capacity_chart": crane_capacity_chart,
            "crane_rigging_buffer_minutes": crane_rigging_buffer_minutes,
            "set_sequence_policy": set_sequence_policy,
            "weather_exposure_limit_hours": weather_exposure_limit_hours,
            "forecast_precip_probability_pct": forecast_precip_probability_pct,
            "forecast_wind_gust_mph": forecast_wind_gust_mph,
            "last_weather_observed_at": None,
            "permit_posture": "DUAL_BLOCKED",
            "phase": "PRECONSTRUCTION",
            "wip_certified_cents": 0,
            "funded_to_date_cents": 0,
            "modules_set_count": 0,
            "modules_connected_count": 0,
        }
    )
    db.projects[row["id"]] = row
    return created(serialize.project(row))


@bp.get("/modular/projects/<project_id>")
@auth.endpoint(
    "ProgramAdmin",
    "SiteSuperintendent",
    "FactoryProductionManager",
    "LenderDrawAdministrator",
    "StateProgramOfficer",
    "AuthorityHavingJurisdiction",
    "WarrantyAdjudicator",
)
def read_project(project_id):
    row = services.get_project(project_id)
    # a pure derivation refresh — never a version bump
    services.refresh_project(row)
    return ok(serialize.project(row))


@bp.get("/modular/projects")
@auth.endpoint(
    "ProgramAdmin",
    "SiteSuperintendent",
    "LenderDrawAdministrator",
    "StateProgramOfficer",
)
def list_projects():
    factory_id = validate.field_str_query("factory_id")
    state_code = validate.field_str_query("state_code")
    ahj_code = validate.field_str_query("ahj_code")
    phase = validate.enum_query("phase", PHASES)
    permit_posture = validate.enum_query("permit_posture", POSTURES)
    rows = sorted_rows(list(db.projects.values()))
    for row in rows:
        services.refresh_project(row)
    if factory_id is not None:
        rows = [r for r in rows if r["factory_id"] == factory_id]
    if state_code is not None:
        rows = [r for r in rows if r["state_code"] == state_code]
    if ahj_code is not None:
        rows = [r for r in rows if r["ahj_code"] == ahj_code]
    if phase is not None:
        rows = [r for r in rows if r["phase"] == phase]
    if permit_posture is not None:
        rows = [r for r in rows if r["permit_posture"] == permit_posture]
    page, meta = paginate(rows)
    return ok_list([serialize.project(r) for r in page], meta)


@bp.get("/modular/projects/<project_id>/set-readiness")
@auth.endpoint("ProgramAdmin", "SiteSuperintendent", "AuthorityHavingJurisdiction")
def set_readiness(project_id):
    row = services.get_project(project_id)
    for module in services.modules_of_project(row["id"]):
        services.refresh_exposure(module)
    services.refresh_project(row)
    return ok(serialize.project(row))


@bp.post("/modular/projects/<project_id>/weather-observations")
@auth.endpoint("SiteSuperintendent", "ProgramAdmin")
def weather_observation(project_id):
    data = validate.body(optional=False)
    precip = validate.field_num(
        data, "forecast_precip_probability_pct", minimum=0, maximum=100
    )
    gust = validate.field_num(data, "forecast_wind_gust_mph", minimum=0)
    observed_at = validate.field_dt(data, "observed_at", required=False)

    row = services.get_project(project_id)
    auth.own_project(row)

    row["forecast_precip_probability_pct"] = precip
    row["forecast_wind_gust_mph"] = gust
    row["last_weather_observed_at"] = observed_at if observed_at is not None else now()
    services.refresh_project(row)
    touch(row)
    return ok(serialize.project(row))
