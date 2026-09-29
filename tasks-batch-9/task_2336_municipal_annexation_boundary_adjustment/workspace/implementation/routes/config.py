"""Logical clock, statute profiles, municipalities, service providers, property owners."""

from decimal import Decimal

from flask import Blueprint

import validate as v
from auth import ANY_ROLE, check_municipality_scope, prelude
from clockutil import iso3, parse_datetime
from db import base_record, db
from errors import ApiError
from response import object_response, paginate
from services import domain

bp = Blueprint("config", __name__)

METHODS = ("PETITION_100", "PETITION_MAJORITY", "REFERENDUM", "INVOLUNTARY_ORDINANCE")
SERVICE_TYPES = ("POLICE", "FIRE", "WATER", "SEWER")


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    prelude(("StateLawAdmin",))
    body = v.get_body()
    if "to_iso8601" not in body or body["to_iso8601"] is None:
        v.bad("to_iso8601 is required.")
    instant = parse_datetime(body["to_iso8601"])
    if instant is None:
        v.bad("to_iso8601 must be a well formed ISO 8601 timestamp.")
    db.clock = instant
    return object_response({"current_utc": iso3(db.clock)})


# ---------------------------------------------------------------------------
# Statute profiles (PRD §2.6, §3.1)
# ---------------------------------------------------------------------------

@bp.post("/statute-profiles")
def create_statute_profile():
    prelude(("StateLawAdmin",))
    body = v.get_body()

    state_code = v.state_code_field(body, "state_code")
    authorized_methods = v.enum_array_field(body, "authorized_methods", METHODS)
    record = base_record()
    record.update(
        {
            "state_code": state_code,
            "authorized_methods": authorized_methods,
            "signature_basis": v.enum_field(
                body, "signature_basis", ("ASSESSED_VALUE", "OWNER_COUNT"),
                required=False, default="ASSESSED_VALUE",
            ),
            "signature_threshold_pct": v.num_field(
                body, "signature_threshold_pct", required=False, default=Decimal("50.00"),
                exclusive_minimum=0, maximum=100, places=2,
            ),
            "protest_basis": v.enum_field(
                body, "protest_basis", ("ASSESSED_VALUE", "OWNER_COUNT"),
                required=False, default="ASSESSED_VALUE",
            ),
            "protest_threshold_pct": v.num_field(
                body, "protest_threshold_pct", required=False, default=Decimal("20.00"),
                exclusive_minimum=0, maximum=100, places=2,
            ),
            "contiguity_min_ratio": v.num_field(
                body, "contiguity_min_ratio", required=False, default=Decimal("0.1250"),
                exclusive_minimum=0, maximum=1, places=4,
            ),
            "urban_density_min_units_per_acre": v.num_field(
                body, "urban_density_min_units_per_acre", required=False, default=Decimal("2.00"),
                exclusive_minimum=0,
            ),
            "subdivision_test_min_developed_ratio": v.num_field(
                body, "subdivision_test_min_developed_ratio", required=False, default=Decimal("0.60"),
                exclusive_minimum=0, maximum=1,
            ),
            "min_qualification_index": v.num_field(
                body, "min_qualification_index", required=False, default=Decimal("60.00"),
                minimum=0, maximum=100, places=2,
            ),
            "notice_min_days": v.int_field(body, "notice_min_days", required=False, default=30, minimum=0),
            "hearing_to_ordinance_min_days": v.int_field(
                body, "hearing_to_ordinance_min_days", required=False, default=10, minimum=0
            ),
            "required_service_types": v.enum_array_field(
                body, "required_service_types", SERVICE_TYPES,
                required=False, default=list(SERVICE_TYPES),
            ),
            "police_fire_timeline_max_days": v.int_field(
                body, "police_fire_timeline_max_days", required=False, default=60, minimum=1
            ),
            "water_sewer_timeline_max_days": v.int_field(
                body, "water_sewer_timeline_max_days", required=False, default=730, minimum=1
            ),
            "fiscal_method": v.enum_field(
                body, "fiscal_method", ("AVERAGE_COST", "MARGINAL_COST"),
                required=False, default="AVERAGE_COST",
            ),
            "per_capita_shared_revenue_cents": v.int_field(
                body, "per_capita_shared_revenue_cents", required=False, default=12000, minimum=0
            ),
            "referendum_required_methods": v.enum_array_field(
                body, "referendum_required_methods", METHODS,
                required=False, default=[], non_empty=False,
            ),
            "boundary_commission_required": v.bool_field(
                body, "boundary_commission_required", default=False
            ),
            "de_annexation_allowed": v.bool_field(body, "de_annexation_allowed", default=True),
            "de_annexation_refund_basis": v.enum_field(
                body, "de_annexation_refund_basis", ("DAILY_PRORATION", "WHOLE_QUARTER"),
                required=False, default="DAILY_PRORATION",
            ),
            "msd_alternative_allowed": v.bool_field(body, "msd_alternative_allowed", default=True),
            "msd_cost_recovery_pct": v.num_field(
                body, "msd_cost_recovery_pct", required=False, default=Decimal("0.75"),
                exclusive_minimum=0, maximum=1,
            ),
            "effective_date_rule": v.enum_field(
                body, "effective_date_rule",
                ("IMMEDIATE", "NEXT_QUARTER_START", "NEXT_FISCAL_YEAR"),
                required=False, default="IMMEDIATE",
            ),
            "fiscal_year_end_month_day": v.month_day_field(
                body, "fiscal_year_end_month_day", default="12-31"
            ),
        }
    )

    for existing in db.statute_profiles.values():
        if existing["state_code"] == state_code:
            v.bad("A statute profile already exists for state %s." % state_code)

    db.statute_profiles[record["id"]] = record
    return object_response(record, 201)


@bp.get("/statute-profiles/<profile_id>")
def read_statute_profile(profile_id):
    prelude(ANY_ROLE)
    return object_response(domain.path_record("statute_profiles", profile_id))


# ---------------------------------------------------------------------------
# Municipalities (PRD §3.1)
# ---------------------------------------------------------------------------

@bp.post("/municipalities")
def create_municipality():
    prelude(("StateLawAdmin",))
    body = v.get_body()

    profile_id = v.id_field(body, "statute_profile_id")
    profile = domain.body_ref("statute_profiles", profile_id)

    name = v.str_field(body, "name", min_len=1, max_len=200)
    state_code = v.state_code_field(body, "state_code")
    population = v.int_field(body, "population", minimum=0)
    citywide_cost = v.int_field(body, "citywide_annual_service_cost_cents", minimum=0)
    citywide_population = v.int_field(body, "citywide_population", minimum=1)
    millage = v.num_field(body, "general_fund_millage_rate", minimum=0, places=4)
    perimeter = v.num_field(body, "corporate_boundary_perimeter_feet", exclusive_minimum=0)
    tolerance = v.num_field(
        body, "fiscal_deficit_tolerance_pct", required=False, default=Decimal("5.00"),
        minimum=0, maximum=100, places=2,
    )
    buffer_minutes = v.int_field(
        body, "hearing_changeover_buffer_minutes", required=False, default=30, minimum=0
    )
    surcharge = v.num_field(
        body, "utility_outside_surcharge_pct", required=False, default=Decimal("0.50"),
        minimum=0, maximum=2,
    )

    if state_code != profile["state_code"]:
        v.bad("state_code must equal the referenced statute profile's state_code.")

    record = base_record()
    record.update(
        {
            "statute_profile_id": profile_id,
            "name": name,
            "state_code": state_code,
            "population": population,
            "citywide_annual_service_cost_cents": citywide_cost,
            "citywide_population": citywide_population,
            "general_fund_millage_rate": millage,
            "taxable_assessed_value_cents": 0,
            "corporate_boundary_perimeter_feet": perimeter,
            "fiscal_deficit_tolerance_pct": tolerance,
            "hearing_changeover_buffer_minutes": buffer_minutes,
            "utility_outside_surcharge_pct": surcharge,
        }
    )
    db.municipalities[record["id"]] = record
    return object_response(record, 201)


@bp.get("/municipalities/<municipality_id>")
def read_municipality(municipality_id):
    prelude(ANY_ROLE)
    return object_response(domain.path_record("municipalities", municipality_id))


@bp.get("/municipalities")
def list_municipalities():
    prelude(ANY_ROLE)
    return paginate(domain.rows("municipalities"), ("statute_profile_id", "state_code"))


# ---------------------------------------------------------------------------
# Service providers (PRD §3.1)
# ---------------------------------------------------------------------------

@bp.post("/municipalities/<municipality_id>/service-providers")
def create_service_provider(municipality_id):
    user_id, role = prelude(("MunicipalPlanner",))
    # The path parameter *is* the municipality, so the scope check needs no resolution.
    check_municipality_scope(role, user_id, municipality_id)
    domain.path_record("municipalities", municipality_id)

    body = v.get_body()
    record = base_record()
    record.update(
        {
            "municipality_id": municipality_id,
            "provider_name": v.str_field(body, "provider_name", min_len=1, max_len=200),
            "service_types": v.enum_array_field(body, "service_types", SERVICE_TYPES),
            "concurrent_project_capacity": v.int_field(
                body, "concurrent_project_capacity", required=False, default=1, minimum=1
            ),
            "encumbered_capacity_days": 0,
        }
    )
    db.service_providers[record["id"]] = record
    return object_response(record, 201)


@bp.get("/service-providers/<provider_id>")
def read_service_provider(provider_id):
    prelude(ANY_ROLE)
    return object_response(domain.path_record("service_providers", provider_id))


@bp.get("/service-providers")
def list_service_providers():
    prelude(ANY_ROLE)
    return paginate(domain.rows("service_providers"), ("municipality_id",))


# ---------------------------------------------------------------------------
# Property owners (PRD §3.1)
# ---------------------------------------------------------------------------

@bp.post("/property-owners")
def create_property_owner():
    prelude(("CityClerk", "StateLawAdmin"))
    body = v.get_body()
    record = base_record()
    record.update(
        {
            "owner_name": v.str_field(body, "owner_name", min_len=1, max_len=200),
            "contact_email": v.email_field(body, "contact_email"),
        }
    )
    db.property_owners[record["id"]] = record
    return object_response(record, 201)


@bp.get("/property-owners/<owner_id>")
def read_property_owner(owner_id):
    prelude(ANY_ROLE)
    return object_response(domain.path_record("property_owners", owner_id))
