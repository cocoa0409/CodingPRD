"""Fee studies, their statutory lifecycle, nexus components and schedule lines."""

from decimal import Decimal
from flask import Blueprint, g

import clock
import db
import helpers
import response
import serializers
from errors import raise_error
from middleware import ANY, guard
from services import calc, cascade, derive
from util import add_days, dec

bp = Blueprint("studies", __name__)

REVISABLE_STUDY_STATUSES = ("DRAFT", "NEXUS_CERTIFIED", "NOTICE_PUBLISHED")
NOTICE_OCCUPYING_STATUSES = ("NOTICE_PUBLISHED", "PROTEST_CLEARED", "ADOPTED")
COMPONENT_INPUT_FIELDS = (
    "horizon_start_year",
    "horizon_end_year",
    "projected_new_dwelling_units",
    "projected_new_nonres_sqft",
    "demand_units_per_dwelling",
    "demand_units_per_1000_nonres_sqft",
    "planned_facility_cost_cents",
    "planned_growth_share_bp",
    "planned_capacity_demand_units",
    "planned_other_funding_cents",
    "existing_tax_credit_per_unit_cents",
)


# --------------------------------------------------------------------------- #
# Fee studies
# --------------------------------------------------------------------------- #


@bp.get("/fee-studies")
@guard(*ANY)
def list_fee_studies():
    filters = {
        "fee_program_id": helpers.arg_string("fee_program_id"),
        "status": helpers.arg_enum("status", helpers.STUDY_STATUSES),
        "methodology": helpers.arg_enum("methodology", helpers.METHODOLOGIES),
        "superseded_by_fee_study_id": helpers.arg_string("superseded_by_fee_study_id"),
    }
    rows = [s for s in db.ordered(db.fee_studies) if helpers.matches(s, filters)]
    return response.paginated(rows, serializers.fee_study)


@bp.get("/fee-studies/<study_id>")
@guard(*ANY)
def read_fee_study(study_id):
    study = helpers.get_study(study_id)
    return response.object_response(serializers.fee_study(study))


@bp.post("/fee-studies")
@guard("NexusAnalyst")
def create_fee_study():
    body = helpers.json_body()
    body.forbid_versions("expected_fee_program_version")
    program_id = body.string("fee_program_id", required=True)
    title = body.string("title", required=True, min_len=1, max_len=200)
    methodology = body.enum("methodology", helpers.METHODOLOGIES, required=True)
    expected = body.integer("expected_fee_program_version", required=True)

    program = db.fee_programs.get(program_id)
    if program is None:
        raise_error("ERR_INVALID_REFERENCE")
    if expected != program["version"]:
        raise_error("ERR_STALE_PROGRAM_VERSION")

    study = db.new_record(
        fee_program_id=program_id,
        title=title,
        methodology=methodology,
        status="DRAFT",
        revision_round=0,
        certified_by_user_id=None,
        certified_at=None,
        notice_method=None,
        notice_days=None,
        notice_published_at=None,
        protest_window_ends_at=None,
        protest_weight_bp=0,
        protest_count=0,
        adopted_at=None,
        adopted_by_user_id=None,
        effective_at=None,
        activated_at=None,
        superseded_by_fee_study_id=None,
    )
    db.fee_studies[study["id"]] = study
    db.touch(program)
    return response.object_response(serializers.fee_study(study), 201)


@bp.post("/fee-studies/<study_id>/certify-nexus")
@guard("NexusAnalyst")
def certify_nexus(study_id):
    study = helpers.get_study(study_id)
    helpers.json_body().forbid_versions()

    if study["status"] != "DRAFT":
        raise_error("ERR_STUDY_INVALID_STATE")
    components = derive.components_of_study(study["id"])
    for component in components:
        if component["allocation_status"] != "VALID":
            raise_error("ERR_COMPONENT_ALLOCATION_STALE")
        if not derive.items_of_component(component["id"]):
            raise_error("ERR_COMPONENT_ALLOCATION_STALE")
    if not components:
        raise_error("ERR_STUDY_HAS_NO_COMPONENTS")
    for component in components:
        ratio = component.get("nexus_ratio")
        if ratio is None or dec(ratio) < Decimal(1):
            raise_error("ERR_NEXUS_RATIO_INSUFFICIENT")

    study["status"] = "NEXUS_CERTIFIED"
    study["certified_by_user_id"] = g.user_id
    study["certified_at"] = clock.now()
    db.touch(study)
    return response.object_response(serializers.fee_study(study))


@bp.post("/fee-studies/<study_id>/publish-notice")
@guard("CouncilClerk")
def publish_notice(study_id):
    study = helpers.get_study(study_id)
    body = helpers.json_body()
    body.forbid_versions()
    notice_method = body.enum("notice_method", helpers.NOTICE_METHODS, required=True)
    notice_days = body.integer("notice_days", required=True, minimum=1)

    if study["status"] != "NEXUS_CERTIFIED":
        raise_error("ERR_STUDY_INVALID_STATE")

    moment = clock.now()
    for other in db.ordered(db.fee_studies):
        if other["id"] == study["id"] or other["fee_program_id"] != study["fee_program_id"]:
            continue
        if other["status"] not in NOTICE_OCCUPYING_STATUSES:
            continue
        start = other.get("notice_published_at")
        end = other.get("protest_window_ends_at")
        if start is None or end is None:
            continue
        if start <= moment < end:
            raise_error("ERR_NOTICE_WINDOW_OVERLAP")

    program = derive.program_of_study(study)
    if notice_days < program["notice_min_days"]:
        raise_error("ERR_NOTICE_PERIOD_TOO_SHORT")

    study["status"] = "NOTICE_PUBLISHED"
    study["notice_method"] = notice_method
    study["notice_days"] = notice_days
    study["notice_published_at"] = moment
    study["protest_window_ends_at"] = add_days(moment, notice_days)
    db.touch(study)
    return response.object_response(serializers.fee_study(study))


@bp.post("/fee-studies/<study_id>/close-protest-window")
@guard("CouncilClerk")
def close_protest_window(study_id):
    study = helpers.get_study(study_id)
    helpers.json_body().forbid_versions()

    if study["status"] != "NOTICE_PUBLISHED":
        raise_error("ERR_STUDY_INVALID_STATE")
    if study.get("protest_window_ends_at") is None or clock.now() < study["protest_window_ends_at"]:
        raise_error("ERR_PROTEST_WINDOW_OPEN")

    program = derive.program_of_study(study)
    if study["protest_weight_bp"] < program["protest_threshold_bp"]:
        study["status"] = "PROTEST_CLEARED"
        db.touch(study)
    else:
        cascade.sustain_protest(study)
    return response.object_response(serializers.fee_study(study))


@bp.post("/fee-studies/<study_id>/adopt")
@guard("CouncilClerk")
def adopt_study(study_id):
    study = helpers.get_study(study_id)
    helpers.json_body().forbid_versions()

    certifier = study.get("certified_by_user_id")
    if certifier is not None and certifier == g.user_id:
        raise_error("ERR_SEGREGATION_OF_DUTIES")
    if study["status"] != "PROTEST_CLEARED":
        raise_error("ERR_STUDY_INVALID_STATE")

    program = derive.program_of_study(study)
    moment = clock.now()
    study["status"] = "ADOPTED"
    study["adopted_at"] = moment
    study["adopted_by_user_id"] = g.user_id
    study["effective_at"] = add_days(moment, program["effective_delay_days"])
    db.touch(study)
    return response.object_response(serializers.fee_study(study))


@bp.post("/fee-studies/<study_id>/activate")
@guard("ProgramAdministrator")
def activate_study(study_id):
    study = helpers.get_study(study_id)
    helpers.json_body().forbid_versions()

    if study["status"] != "ADOPTED":
        raise_error("ERR_STUDY_INVALID_STATE")
    if study.get("effective_at") is None or clock.now() < study["effective_at"]:
        raise_error("ERR_EFFECTIVE_DATE_NOT_REACHED")

    program = derive.program_of_study(study)
    cascade.activate_study(study, program)
    return response.object_response(serializers.fee_study(study))


# --------------------------------------------------------------------------- #
# Protest filings
# --------------------------------------------------------------------------- #


@bp.get("/fee-studies/<study_id>/protest-filings")
@guard(*ANY)
def list_protest_filings(study_id):
    study = helpers.get_study(study_id)
    status = helpers.arg_enum("status", helpers.PROTEST_STATUSES)
    rows = [f for f in derive.filings_of_study(study["id"])
            if status is None or f["status"] == status]
    return response.paginated(rows, serializers.protest_filing)


@bp.post("/fee-studies/<study_id>/protest-filings")
@guard("CouncilClerk")
def create_protest_filing(study_id):
    study = helpers.get_study(study_id)
    body = helpers.json_body()
    body.forbid_versions()
    protester_name = body.string("protester_name", required=True, min_len=1, max_len=200)
    parcel_count = body.integer("parcel_count", required=True, minimum=1)
    weight_bp = body.integer("weight_bp", required=True, minimum=1, maximum=10000)

    if study["status"] != "NOTICE_PUBLISHED":
        raise_error("ERR_STUDY_INVALID_STATE")

    filing = db.new_record(
        fee_study_id=study["id"],
        protester_name=protester_name,
        parcel_count=parcel_count,
        weight_bp=weight_bp,
        status="RECORDED",
        filed_at=clock.now(),
    )
    db.protest_filings[filing["id"]] = filing
    derive.sync_study_tally(study)
    db.touch(study)
    return response.object_response(serializers.protest_filing(filing), 201)


@bp.post("/protest-filings/<filing_id>/withdraw")
@guard("CouncilClerk")
def withdraw_protest_filing(filing_id):
    filing = helpers.get_filing(filing_id)
    helpers.json_body().forbid_versions()

    study = db.fee_studies.get(filing["fee_study_id"])
    if filing["status"] != "RECORDED" or study is None or study["status"] != "NOTICE_PUBLISHED":
        raise_error("ERR_PROTEST_INVALID_STATE")

    filing["status"] = "WITHDRAWN"
    db.touch(filing)
    derive.sync_study_tally(study)
    db.touch(study)
    return response.object_response(serializers.protest_filing(filing))


# --------------------------------------------------------------------------- #
# Nexus components
# --------------------------------------------------------------------------- #


def _check_horizon(study, facility_category_id, start_year, end_year, component_id=None):
    program_id = study["fee_program_id"]
    effective = derive.effective_study(program_id)
    if effective is None:
        return
    for other in derive.components_of_study(effective["id"]):
        if other["facility_category_id"] != facility_category_id:
            continue
        if component_id is not None and other["id"] == component_id:
            continue
        if start_year <= other["horizon_end_year"] and other["horizon_start_year"] <= end_year:
            raise_error("ERR_HORIZON_OVERLAP")


@bp.get("/nexus-components")
@guard(*ANY)
def list_nexus_components():
    filters = {
        "fee_study_id": helpers.arg_string("fee_study_id"),
        "facility_category_id": helpers.arg_string("facility_category_id"),
        "allocation_status": helpers.arg_enum("allocation_status", helpers.ALLOCATION_STATUSES),
    }
    rows = [c for c in db.ordered(db.nexus_components) if helpers.matches(c, filters)]
    return response.paginated(rows, serializers.nexus_component)


@bp.get("/nexus-components/<component_id>")
@guard(*ANY)
def read_nexus_component(component_id):
    component = helpers.get_component(component_id)
    return response.object_response(serializers.nexus_component(component))


@bp.post("/nexus-components")
@guard("NexusAnalyst")
def create_nexus_component():
    body = helpers.json_body()
    body.forbid_versions()
    study_id = body.string("fee_study_id", required=True)
    category_id = body.string("facility_category_id", required=True)
    start_year = body.integer("horizon_start_year", required=True, minimum=1900, maximum=2200)
    end_year = body.integer("horizon_end_year", required=True, minimum=1900, maximum=2200)
    if end_year < start_year:
        raise_error("ERR_INVALID_REQUEST")
    dwellings = body.integer("projected_new_dwelling_units", default=0, minimum=0)
    nonres_sqft = body.integer("projected_new_nonres_sqft", default=0, minimum=0)
    per_dwelling = body.number("demand_units_per_dwelling", default=0, ge=0)
    per_1000 = body.number("demand_units_per_1000_nonres_sqft", default=0, ge=0)
    facility_cost = body.integer("planned_facility_cost_cents", required=True, minimum=0)
    growth_share = body.integer("planned_growth_share_bp", default=10000, minimum=0, maximum=10000)
    capacity = body.number("planned_capacity_demand_units", required=True, ge=0)
    other_funding = body.integer("planned_other_funding_cents", default=0, minimum=0)
    tax_credit = body.integer("existing_tax_credit_per_unit_cents", default=0, minimum=0)

    study = db.fee_studies.get(study_id)
    category = db.facility_categories.get(category_id)
    if study is None or category is None:
        raise_error("ERR_INVALID_REFERENCE")
    if study["fee_program_id"] != category["fee_program_id"]:
        raise_error("ERR_PROGRAM_SCOPE_MISMATCH")
    if study["status"] != "DRAFT":
        raise_error("ERR_STUDY_INVALID_STATE")
    for existing in db.nexus_components.values():
        if existing["fee_study_id"] == study_id and existing["facility_category_id"] == category_id:
            raise_error("ERR_DUPLICATE_NEXUS_COMPONENT")
    _check_horizon(study, category_id, start_year, end_year)

    component = db.new_record(
        fee_study_id=study_id,
        facility_category_id=category_id,
        horizon_start_year=start_year,
        horizon_end_year=end_year,
        projected_new_dwelling_units=dwellings,
        projected_new_nonres_sqft=nonres_sqft,
        demand_units_per_dwelling=per_dwelling,
        demand_units_per_1000_nonres_sqft=per_1000,
        planned_facility_cost_cents=facility_cost,
        planned_other_funding_cents=other_funding,
        planned_growth_share_bp=growth_share,
        planned_capacity_demand_units=capacity,
        existing_tax_credit_per_unit_cents=tax_credit,
        growth_demand_units=Decimal(0),
        plan_based_cost_per_unit_cents=None,
        standard_based_cost_per_unit_cents=None,
        adopted_cost_per_unit_cents=None,
        nexus_ratio=None,
        allocation_status="PENDING",
        allocated_at=None,
    )
    component["growth_demand_units"] = calc.growth_demand_units(component)
    db.nexus_components[component["id"]] = component
    return response.object_response(serializers.nexus_component(component), 201)


@bp.patch("/nexus-components/<component_id>")
@guard("NexusAnalyst")
def revise_nexus_component(component_id):
    component = helpers.get_component(component_id)
    body = helpers.json_body()
    body.forbid_versions()
    if not body.any_present(COMPONENT_INPUT_FIELDS):
        raise_error("ERR_INVALID_REQUEST")

    updates = {}
    if body.present("horizon_start_year"):
        updates["horizon_start_year"] = body.integer(
            "horizon_start_year", minimum=1900, maximum=2200)
    if body.present("horizon_end_year"):
        updates["horizon_end_year"] = body.integer(
            "horizon_end_year", minimum=1900, maximum=2200)
    if body.present("projected_new_dwelling_units"):
        updates["projected_new_dwelling_units"] = body.integer(
            "projected_new_dwelling_units", minimum=0)
    if body.present("projected_new_nonres_sqft"):
        updates["projected_new_nonres_sqft"] = body.integer(
            "projected_new_nonres_sqft", minimum=0)
    if body.present("demand_units_per_dwelling"):
        updates["demand_units_per_dwelling"] = body.number("demand_units_per_dwelling", ge=0)
    if body.present("demand_units_per_1000_nonres_sqft"):
        updates["demand_units_per_1000_nonres_sqft"] = body.number(
            "demand_units_per_1000_nonres_sqft", ge=0)
    if body.present("planned_facility_cost_cents"):
        updates["planned_facility_cost_cents"] = body.integer(
            "planned_facility_cost_cents", minimum=0)
    if body.present("planned_growth_share_bp"):
        updates["planned_growth_share_bp"] = body.integer(
            "planned_growth_share_bp", minimum=0, maximum=10000)
    if body.present("planned_capacity_demand_units"):
        updates["planned_capacity_demand_units"] = body.number(
            "planned_capacity_demand_units", ge=0)
    if body.present("planned_other_funding_cents"):
        updates["planned_other_funding_cents"] = body.integer(
            "planned_other_funding_cents", minimum=0)
    if body.present("existing_tax_credit_per_unit_cents"):
        updates["existing_tax_credit_per_unit_cents"] = body.integer(
            "existing_tax_credit_per_unit_cents", minimum=0)

    start_year = updates.get("horizon_start_year", component["horizon_start_year"])
    end_year = updates.get("horizon_end_year", component["horizon_end_year"])
    if end_year < start_year:
        raise_error("ERR_INVALID_REQUEST")

    study = derive.study_of_component(component)
    if study is None or study["status"] not in REVISABLE_STUDY_STATUSES:
        raise_error("ERR_STUDY_INVALID_STATE")
    _check_horizon(study, component["facility_category_id"], start_year, end_year,
                   component_id=component["id"])

    was_valid = component["allocation_status"] == "VALID"
    component.update(updates)
    component["growth_demand_units"] = calc.growth_demand_units(component)
    if was_valid:
        component["allocation_status"] = "STALE"
        component["plan_based_cost_per_unit_cents"] = None
        component["standard_based_cost_per_unit_cents"] = None
        component["adopted_cost_per_unit_cents"] = None
        component["nexus_ratio"] = None
    db.touch(component)
    if was_valid:
        cascade.decertify_from_component(component)
    return response.object_response(serializers.nexus_component(component))


@bp.post("/nexus-components/<component_id>/allocate")
@guard("NexusAnalyst")
def allocate_nexus_component(component_id):
    component = helpers.get_component(component_id)
    helpers.json_body().forbid_versions()

    study = derive.study_of_component(component)
    if study is None or study["status"] != "DRAFT":
        raise_error("ERR_STUDY_INVALID_STATE")

    growth = dec(component["growth_demand_units"])
    capacity = dec(component["planned_capacity_demand_units"])
    smaller = growth if growth < capacity else capacity
    if growth <= 0 or smaller <= 0:
        raise_error("ERR_ZERO_DEMAND_UNITS")

    category = derive.category_of_component(component)
    program = derive.program_of_study(study)
    was_stale = component["allocation_status"] == "STALE"

    calc.allocate(component, study, category, program)
    component["allocation_status"] = "VALID"
    component["allocated_at"] = clock.now()
    db.touch(component)
    if was_stale:
        cascade.revalidate_schedule_items(component)
    return response.object_response(serializers.nexus_component(component))


# --------------------------------------------------------------------------- #
# Fee schedule lines
# --------------------------------------------------------------------------- #


@bp.get("/nexus-components/<component_id>/fee-schedule-items")
@guard(*ANY)
def list_fee_schedule_items(component_id):
    component = helpers.get_component(component_id)
    status = helpers.arg_enum("schedule_status", helpers.SCHEDULE_STATUSES)
    rows = [i for i in derive.items_of_component(component["id"])
            if status is None or i["schedule_status"] == status]
    rows.sort(key=lambda item: (item["land_use_category"], item["_seq"]))
    return response.paginated(rows, serializers.fee_schedule_item)


@bp.post("/nexus-components/<component_id>/fee-schedule-items")
@guard("NexusAnalyst")
def create_fee_schedule_item(component_id):
    component = helpers.get_component(component_id)
    body = helpers.json_body()
    body.forbid_versions()
    land_use_category = body.enum("land_use_category", helpers.LAND_USE_CATEGORIES, required=True)
    unit_basis = body.enum("unit_basis", helpers.UNIT_BASES, required=True)
    conversion_factor = body.number("conversion_factor", required=True, gt=0)

    study = derive.study_of_component(component)
    if study is None or study["status"] != "DRAFT":
        raise_error("ERR_STUDY_INVALID_STATE")
    if component["allocation_status"] != "VALID":
        raise_error("ERR_COMPONENT_ALLOCATION_STALE")
    for existing in derive.items_of_component(component["id"]):
        if existing["land_use_category"] == land_use_category:
            raise_error("ERR_DUPLICATE_SCHEDULE_ITEM")

    residential = land_use_category in ("SINGLE_FAMILY", "MULTI_FAMILY")
    required_basis = "PER_DWELLING" if residential else "PER_1000_SQFT"
    if unit_basis != required_basis:
        raise_error("ERR_UNIT_BASIS_MISMATCH")
    if unit_basis == "PER_DWELLING":
        if dec(component["demand_units_per_dwelling"]) <= 0:
            raise_error("ERR_UNIT_BASIS_MISMATCH")
    elif dec(component["demand_units_per_1000_nonres_sqft"]) <= 0:
        raise_error("ERR_UNIT_BASIS_MISMATCH")

    item = db.new_record(
        nexus_component_id=component["id"],
        land_use_category=land_use_category,
        unit_basis=unit_basis,
        conversion_factor=conversion_factor,
        fee_per_unit_cents=calc.fee_per_unit_cents(component, conversion_factor),
        schedule_status="VALID",
    )
    db.fee_schedule_items[item["id"]] = item
    return response.object_response(serializers.fee_schedule_item(item), 201)
