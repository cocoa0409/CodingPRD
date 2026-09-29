"""Well inventory and the production ledger (PRD 3.1, 3.2)."""
from flask import Blueprint

import calc
import validate as v
from auth import (AWARD_AUTHORITY, DETERMINATION_REVIEWER, FIELD_INSPECTOR,
                  FUNDING_OFFICER, OPERATOR, PROCUREMENT_OFFICER,
                  PROGRAM_ADMIN, endpoint, not_owner, role, user_id)
from envelope import filter_value, float_filter, object_response, paginated
from errors import ApiError, invalid
from lookup import collect, get_operator, get_well
from store import clock, db, new_row, touch

bp = Blueprint("wells", __name__)

WELL_STATUSES = ("PRODUCING", "INACTIVE", "ORPHAN_CANDIDATE", "ORPHAN_CONFIRMED",
                 "PLUGGING_SCHEDULED", "PLUGGED", "RECLAIMED")
ACCESS_STATUSES = ("NO_ACCESS_REQUESTED", "ACCESS_PENDING", "AGREEMENT_EXECUTED",
                   "ENTRY_ORDERED", "ACCESS_DENIED")

WELL_READERS = (PROGRAM_ADMIN, FIELD_INSPECTOR, DETERMINATION_REVIEWER,
                PROCUREMENT_OFFICER, AWARD_AUTHORITY, FUNDING_OFFICER, OPERATOR)
PRODUCTION_READERS = (PROGRAM_ADMIN, FIELD_INSPECTOR, DETERMINATION_REVIEWER,
                      FUNDING_OFFICER, OPERATOR)


@bp.route("/wells", methods=["POST"])
@endpoint((PROGRAM_ADMIN, FIELD_INSPECTOR))
def create_well():
    data = v.body()

    # Step 6: the operator_id foreign key resolves before schema validation.
    if v.present(data, "operator_id") and isinstance(data["operator_id"], str):
        get_operator(data["operator_id"])

    api_well_number = v.str_field(data, "api_well_number")
    operator_id = v.str_field(data, "operator_id")
    spud_year = v.int_field(data, "spud_year")
    total_depth_ft = v.int_field(data, "total_depth_ft", exclusive_minimum=0)
    casing_strings = v.int_field(data, "casing_strings", minimum=0)
    methane_scfd = v.num_field(data, "methane_scfd", minimum=0)
    groundwater_depth_ft = v.int_field(data, "groundwater_depth_ft",
                                      exclusive_minimum=0)
    population = v.int_field(data, "population_within_1000ft", minimum=0)
    surface_acres = v.num_field(data, "surface_disturbance_acres", minimum=0)
    last_production_month = v.month_field(data, "last_production_month",
                                          required=False)

    for existing in db.wells.values():
        if existing["api_well_number"] == api_well_number:
            raise invalid("api_well_number %s is already in the inventory."
                          % api_well_number)

    operator = get_operator(operator_id)

    row = new_row()
    row.update({
        "api_well_number": api_well_number,
        "operator_id": operator_id,
        "spud_year": spud_year,
        "total_depth_ft": total_depth_ft,
        "casing_strings": casing_strings,
        "methane_scfd": methane_scfd,
        "groundwater_depth_ft": groundwater_depth_ft,
        "population_within_1000ft": population,
        "surface_disturbance_acres": surface_acres,
        "last_production_month": last_production_month,
        "status": "PRODUCING",
        "access_status": "NO_ACCESS_REQUESTED",
        "screening_score": None,
        "remediation_score": None,
        "idle_months": calc.IDLE_MONTHS_SENTINEL,
        "cumulative_boe_60mo": None,
        "orphan_confirmed_at": None,
    })
    calc.recompute_scores(row)
    calc.recompute_criteria(row)
    db.wells[row["id"]] = row

    calc.recompute_operator(operator)
    return object_response(row, 201)


@bp.route("/wells/<well_id>", methods=["GET"])
@endpoint(WELL_READERS)
def fetch_well(well_id):
    well = get_well(well_id)
    if role() == OPERATOR and well["operator_id"] != user_id():
        raise not_owner("This well belongs to another operator.")
    return object_response(well)


@bp.route("/wells", methods=["GET"])
@endpoint(WELL_READERS)
def list_wells():
    operator_id = filter_value("operator_id")
    status = filter_value("status")
    access_status = filter_value("access_status")
    min_screening_score = float_filter("min_screening_score")

    if role() == OPERATOR:
        if operator_id is not None and operator_id != user_id():
            raise not_owner("An operator may only list its own wells.")
        operator_id = user_id()

    def keep(row):
        if operator_id is not None and row["operator_id"] != operator_id:
            return False
        if status is not None and row["status"] != status:
            return False
        if access_status is not None and row["access_status"] != access_status:
            return False
        if min_screening_score is not None:
            if float(row["screening_score"]) < min_screening_score:
                return False
        return True

    return paginated(collect(db.wells, keep))


@bp.route("/wells/<well_id>/production-records", methods=["POST"])
@endpoint((PROGRAM_ADMIN, FIELD_INSPECTOR, OPERATOR), needs_user_id=True)
def create_production_record(well_id):
    well = get_well(well_id)
    # PRD 3.1: production is filed "by the `Operator` itself for its own wells",
    # and PRD 2.10 step 3 reports an Operator-scoped caller reaching outside its
    # own data with ERR_NOT_RESOURCE_OWNER.
    if role() == OPERATOR and well["operator_id"] != user_id():
        raise not_owner("This well belongs to another operator.")
    data = v.body()
    month = v.month_field(data, "month")
    oil_bbl = v.num_field(data, "oil_bbl", minimum=0)
    gas_mcf = v.num_field(data, "gas_mcf", minimum=0)

    for existing in db.production_records.values():
        if existing["well_id"] == well_id and existing["month"] == month:
            raise ApiError(
                "ERR_DUPLICATE_PRODUCTION_MONTH",
                "Month %s has already been reported for this well." % month,
            )

    row = new_row(common=False)
    row.update({
        "well_id": well_id,
        "month": month,
        "oil_bbl": oil_bbl,
        "gas_mcf": gas_mcf,
        "boe": calc.row_boe(oil_bbl, gas_mcf),
        "reported_by_user_id": user_id(),
    })
    db.production_records[row["id"]] = row

    stored = well.get("last_production_month")
    if stored is None or month > stored:
        well["last_production_month"] = month
    calc.recompute_criteria(well)
    touch(well)

    return object_response(row, 201)


@bp.route("/wells/<well_id>/production-records", methods=["GET"])
@endpoint(PRODUCTION_READERS)
def list_production_records(well_id):
    get_well(well_id)
    rows = collect(
        db.production_records,
        lambda r: r["well_id"] == well_id,
        sort_key=lambda r: r["month"],
    )
    return paginated(rows)
