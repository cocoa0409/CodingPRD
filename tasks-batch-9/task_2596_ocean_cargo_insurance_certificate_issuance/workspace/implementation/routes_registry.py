"""Open policies, commodity classes, vessels, ports, the panel and the logical clock."""
from decimal import Decimal

from flask import Blueprint

import clock
import serialize
import services
from errors import ApiError, require_state
from response import array_response, object_response
from store import db, new_row, ordered, touch
from validation import (D, authenticate, body, get_bool, get_decimal, get_dt, get_enum,
                        get_int, get_str, get_str_array, pagination, paginate, q2,
                        query_enum, query_str)

bp = Blueprint("registry", __name__)

ALL_ROLES = ("Underwriter", "Assured", "ComplianceOfficer", "PremiumAuditor",
             "ClaimsAdjuster", "Surveyor", "PlatformAdmin")


def _unique(table, field, value, ):
    for row in table.values():
        if row[field] == value:
            raise ApiError("ERR_DUPLICATE_REFERENCE")


# ============================== OpenPolicy ================================= #
@bp.post("/open-policies")
def create_open_policy():
    authenticate(("Underwriter",))
    payload = body()
    policy_number = get_str(payload, "policy_number", min_len=1, max_len=32)
    assured_name = get_str(payload, "assured_name")
    inception_at = get_dt(payload, "inception_at")
    expiry_at = get_dt(payload, "expiry_at")
    freight_basis = get_enum(payload, "freight_basis", ("PREPAID", "COLLECT"))
    per_certificate = get_decimal(payload, "per_certificate_limit_amount", gt=0)
    conveyance = get_decimal(payload, "conveyance_limit_amount", minimum=0)
    annual = get_decimal(payload, "annual_aggregate_limit_amount", minimum=0)
    premium_rate = get_decimal(payload, "premium_rate_per_mille", gt=0)
    war_rate = get_decimal(payload, "war_rate_per_mille", minimum=0)
    strikes_rate = get_decimal(payload, "strikes_rate_per_mille", minimum=0)
    warehouse = get_bool(payload, "warehouse_to_warehouse", default=True)
    markup = get_decimal(payload, "markup_pct", required=False, default=Decimal("0.10"),
                         minimum=0, maximum=Decimal("0.30"))
    deductible = get_decimal(payload, "deductible_amount", required=False,
                             default=Decimal("0"), minimum=0)

    _unique(db.open_policies, "policy_number", policy_number)

    row = new_row()
    row.update({
        "policy_number": policy_number,
        "assured_name": assured_name,
        "inception_at": inception_at,
        "expiry_at": expiry_at,
        "warehouse_to_warehouse": warehouse,
        "freight_basis": freight_basis,
        "markup_pct": markup,
        "per_certificate_limit_amount": per_certificate,
        "conveyance_limit_amount": conveyance,
        "annual_aggregate_limit_amount": annual,
        "deductible_amount": deductible,
        "premium_rate_per_mille": premium_rate,
        "war_rate_per_mille": war_rate,
        "strikes_rate_per_mille": strikes_rate,
        "status": "DRAFT",
        "war_cover_status": "ATTACHED",
        "war_terminated_at": None,
        "war_termination_port_unlocode": None,
        "reinstatement_rate_per_mille": None,
        "aggregate_insured_value_booked": Decimal("0.00"),
        "aggregate_premium_booked": Decimal("0.00"),
        "aggregate_return_premium": Decimal("0.00"),
        "security_deposit_held_amount": Decimal("0.00"),
        "certificates_issued_count": 0,
    })
    db.open_policies[row["id"]] = row
    return object_response(serialize.open_policy(row), 201)


@bp.get("/open-policies/<policy_id>")
def read_open_policy(policy_id):
    authenticate(("Underwriter", "Assured", "ComplianceOfficer", "PremiumAuditor",
                  "ClaimsAdjuster", "PlatformAdmin"))
    policy = services.find(db.open_policies, policy_id, "ERR_POLICY_NOT_FOUND")
    return object_response(serialize.open_policy(policy))


@bp.post("/open-policies/<policy_id>/activate")
def activate_open_policy(policy_id):
    authenticate(("Underwriter",))
    policy = services.find(db.open_policies, policy_id, "ERR_POLICY_NOT_FOUND")
    require_state("OpenPolicy", "status", policy["status"], ("DRAFT",))
    if not (policy["expiry_at"] > policy["inception_at"]):
        raise ApiError("ERR_INVALID_STATE")
    if D(policy["conveyance_limit_amount"]) < D(policy["per_certificate_limit_amount"]):
        raise ApiError("ERR_INVALID_STATE")
    if D(policy["annual_aggregate_limit_amount"]) < D(policy["conveyance_limit_amount"]):
        raise ApiError("ERR_INVALID_STATE")
    policy["status"] = "ACTIVE"
    touch(policy)
    return object_response(serialize.open_policy(policy))


@bp.post("/open-policies/<policy_id>/reinstate-war-cover")
def reinstate_war_cover(policy_id):
    authenticate(("ComplianceOfficer",))
    payload = body()
    rate = get_decimal(payload, "reinstatement_rate_per_mille", minimum=0)
    policy = services.find(db.open_policies, policy_id, "ERR_POLICY_NOT_FOUND")
    require_state("OpenPolicy", "war_cover_status", policy["war_cover_status"], ("TERMINATED",))
    if policy["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")
    if rate <= Decimal("0"):
        raise ApiError("ERR_INVALID_STATE")
    listed = policy["war_termination_port_unlocode"]
    if listed:
        for port in db.ports.values():
            if port["unlocode"] == listed and port["war_risk_tier"] == "LISTED_AREA":
                raise ApiError("ERR_WAR_COVER_TERMINATED")
    policy["war_cover_status"] = "REINSTATED"
    policy["reinstatement_rate_per_mille"] = rate
    policy["war_terminated_at"] = None
    policy["war_termination_port_unlocode"] = None
    services.reinstate_cascade(policy)
    touch(policy)
    return object_response(serialize.open_policy(policy))


@bp.post("/open-policies/<policy_id>/run-transit-sweep")
def run_transit_sweep(policy_id):
    authenticate(("Underwriter", "ComplianceOfficer"))
    policy = services.find(db.open_policies, policy_id, "ERR_POLICY_NOT_FOUND")
    services.run_transit_sweep(policy)
    touch(policy)
    return object_response(serialize.open_policy(policy))


# ============================ CommodityClass =============================== #
@bp.post("/commodity-classes")
def create_commodity_class():
    authenticate(("Underwriter",))
    payload = body()
    code = get_str(payload, "code")
    description = get_str(payload, "description")
    rating = get_enum(payload, "susceptibility_rating", ("S1", "S2", "S3", "S4"))
    packaging = get_enum(payload, "required_packaging_code",
                         ("STD", "EXPORT_CRATE", "IBC_LINED", "REEFER_SEALED"))
    loading = get_decimal(payload, "rate_loading_pct", minimum=0, maximum=Decimal("2.00"))
    share = get_decimal(payload, "max_conveyance_share_pct", required=False,
                        default=Decimal("0.50"), gt=0, maximum=Decimal("1.00"))
    survey_above = get_decimal(payload, "survey_required_above_amount", required=False,
                               default=Decimal("0"), minimum=0)
    _unique(db.commodity_classes, "code", code)
    row = new_row()
    row.update({
        "code": code,
        "description": description,
        "susceptibility_rating": rating,
        "required_packaging_code": packaging,
        "rate_loading_pct": loading,
        "max_conveyance_share_pct": share,
        "survey_required_above_amount": survey_above,
    })
    db.commodity_classes[row["id"]] = row
    return object_response(serialize.commodity_class(row), 201)


@bp.get("/commodity-classes")
def list_commodity_classes():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rating = query_enum("susceptibility_rating", ("S1", "S2", "S3", "S4"))
    rows = [r for r in db.commodity_classes.values()
            if rating is None or r["susceptibility_rating"] == rating]
    page, limit, offset, total = paginate(ordered(rows), limit, offset,
                                          serialize.commodity_class)
    return array_response(page, limit, offset, total)


# ================================ Vessel =================================== #
@bp.post("/vessels")
def create_vessel():
    authenticate(("Underwriter",))
    payload = body()
    name = get_str(payload, "name")
    imo = get_str(payload, "imo_number", exact_len=7)
    if not imo.isdigit():
        raise ApiError("ERR_INVALID_REQUEST", "Field 'imo_number' must be exactly 7 digits.")
    year_built = get_int(payload, "year_built", minimum=1900, maximum=2100)
    society = get_enum(payload, "classification_society",
                       ("LR", "ABS", "DNV", "BV", "NK", "CCS", "UNCLASSED"))
    flag_code = get_str(payload, "flag_code", exact_len=2)
    limit_amount = get_decimal(payload, "vessel_accumulation_limit_amount", gt=0)
    _unique(db.vessels, "imo_number", imo)
    row = new_row()
    row.update({
        "name": name,
        "imo_number": imo,
        "year_built": year_built,
        "classification_society": society,
        "flag_code": flag_code,
        "vessel_accumulation_limit_amount": limit_amount,
        "status": "PENDING_REVIEW",
        "overage_surcharge_pct": Decimal("0.00"),
        "accumulated_insured_value": Decimal("0.00"),
        "open_ga_event_count": 0,
    })
    db.vessels[row["id"]] = row
    return object_response(serialize.vessel(row), 201)


@bp.get("/vessels/<vessel_id>")
def read_vessel(vessel_id):
    authenticate(("Underwriter", "Assured", "ComplianceOfficer", "ClaimsAdjuster",
                  "PremiumAuditor", "PlatformAdmin"))
    vessel = services.find(db.vessels, vessel_id, "ERR_VESSEL_NOT_FOUND")
    return object_response(serialize.vessel(vessel))


@bp.post("/vessels/<vessel_id>/classification-review")
def classification_review(vessel_id):
    authenticate(("Underwriter",))
    vessel = services.find(db.vessels, vessel_id, "ERR_VESSEL_NOT_FOUND")
    require_state("Vessel", "status", vessel["status"], ("PENDING_REVIEW",))
    status, surcharge = services.classification_decision(vessel)
    vessel["status"] = status
    vessel["overage_surcharge_pct"] = surcharge
    touch(vessel)
    return object_response(serialize.vessel(vessel))


# ================================= Port ==================================== #
WAR_TIERS = ("GREEN", "AMBER", "LISTED_AREA")


@bp.post("/ports")
def create_port():
    authenticate(("Underwriter", "ComplianceOfficer"))
    payload = body()
    unlocode = get_str(payload, "unlocode", exact_len=5)
    name = get_str(payload, "name")
    country_code = get_str(payload, "country_code", exact_len=2)
    limit_amount = get_decimal(payload, "port_accumulation_limit_amount", gt=0)
    storage_free_days = get_int(payload, "storage_free_days", required=False, default=60,
                               minimum=1, maximum=60)
    tier = get_enum(payload, "war_risk_tier", WAR_TIERS, required=False, default="GREEN")
    _unique(db.ports, "unlocode", unlocode)
    row = new_row()
    row.update({
        "unlocode": unlocode,
        "name": name,
        "country_code": country_code,
        "port_accumulation_limit_amount": limit_amount,
        "storage_free_days": storage_free_days,
        "war_risk_tier": tier,
        "war_rate_multiplier": services.WAR_TIER_MULTIPLIER[tier],
        "accumulated_insured_value": Decimal("0.00"),
    })
    db.ports[row["id"]] = row
    return object_response(serialize.port(row), 201)


@bp.get("/ports/<port_id>")
def read_port(port_id):
    authenticate(ALL_ROLES)
    port = services.find(db.ports, port_id, "ERR_PORT_NOT_FOUND")
    return object_response(serialize.port(port))


@bp.get("/ports")
def list_ports():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    tier = query_enum("war_risk_tier", WAR_TIERS)
    rows = [r for r in db.ports.values() if tier is None or r["war_risk_tier"] == tier]
    page, limit, offset, total = paginate(ordered(rows), limit, offset, serialize.port)
    return array_response(page, limit, offset, total)


@bp.post("/ports/<port_id>/war-risk-tier")
def set_war_risk_tier(port_id):
    authenticate(("ComplianceOfficer",))
    payload = body()
    tier = get_enum(payload, "war_risk_tier", WAR_TIERS)
    port = services.find(db.ports, port_id, "ERR_PORT_NOT_FOUND")
    port["war_risk_tier"] = tier
    port["war_rate_multiplier"] = services.WAR_TIER_MULTIPLIER[tier]
    if tier == "LISTED_AREA":
        services.listed_area_cascade(port)
    touch(port)
    return object_response(serialize.port(port))


@bp.get("/ports/<port_id>/surveyors")
def list_port_surveyors(port_id):
    authenticate(("ClaimsAdjuster", "ComplianceOfficer", "Underwriter", "PlatformAdmin"))
    limit, offset = pagination()
    status = query_enum("status", ("ACTIVE", "SUSPENDED"))
    port = services.find(db.ports, port_id, "ERR_PORT_NOT_FOUND")
    rows = [r for r in db.surveyors.values()
            if r["base_port_id"] == port["id"]
            and (status is None or r["status"] == status)]
    page, limit, offset, total = paginate(ordered(rows), limit, offset, serialize.surveyor)
    return array_response(page, limit, offset, total)


# =============================== Surveyor ================================== #
@bp.post("/surveyors")
def create_surveyor():
    authenticate(("ComplianceOfficer",))
    payload = body()
    name = get_str(payload, "name")
    panel_code = get_str(payload, "panel_code")
    base_port_id = get_str(payload, "base_port_id")
    ratings = get_str_array(payload, "certified_commodity_ratings", ("S1", "S2", "S3", "S4"))
    buffer_minutes = get_int(payload, "travel_buffer_minutes", required=False, default=45,
                             minimum=0, maximum=240)
    port = services.find(db.ports, base_port_id, "ERR_PORT_NOT_FOUND")
    _unique(db.surveyors, "panel_code", panel_code)
    row = new_row()
    row.update({
        "name": name,
        "panel_code": panel_code,
        "base_port_id": port["id"],
        "certified_commodity_ratings": ratings,
        "travel_buffer_minutes": buffer_minutes,
        "status": "ACTIVE",
        "booked_minutes_total": 0,
    })
    db.surveyors[row["id"]] = row
    return object_response(serialize.surveyor(row), 201)


@bp.get("/surveyors/<surveyor_id>")
def read_surveyor(surveyor_id):
    authenticate(("ClaimsAdjuster", "ComplianceOfficer", "Underwriter", "Surveyor",
                  "PlatformAdmin"))
    surveyor = services.find(db.surveyors, surveyor_id, "ERR_SURVEYOR_NOT_FOUND")
    return object_response(serialize.surveyor(surveyor))


@bp.post("/surveyors/<surveyor_id>/suspend")
def suspend_surveyor(surveyor_id):
    authenticate(("ComplianceOfficer",))
    surveyor = services.find(db.surveyors, surveyor_id, "ERR_SURVEYOR_NOT_FOUND")
    require_state("Surveyor", "status", surveyor["status"], ("ACTIVE",))
    surveyor["status"] = "SUSPENDED"
    touch(surveyor)
    return object_response(serialize.surveyor(surveyor))


# ============================= Logical clock =============================== #
@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(("PlatformAdmin",))
    payload = body()
    current_utc = get_dt(payload, "current_utc")
    clock.set_now(current_utc)
    return object_response({})
