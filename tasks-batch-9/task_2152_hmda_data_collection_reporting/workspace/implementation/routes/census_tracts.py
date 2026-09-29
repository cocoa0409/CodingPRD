"""Census tract reference data (PRD 3.4).  Tract rows are immutable: they carry
only id and created_at, with no updated_at and no version."""

from flask import Blueprint

import constants as C
import serializers as S
import store
from auth import authenticate
from response import array_response, object_response
from validate import (Field, bool_filter, check, json_body, lookup, paginate,
                      pagination)

bp = Blueprint("census_tracts", __name__)

CREATE_FIELDS = [
    Field("tract_code", "string", required=True),
    Field("county_fips", "string", required=True),
    Field("state_code", "string", required=True),
    Field("msa_md_code", "string", required=True),
    Field("minority_population_pct", "number", required=True),
    Field("tract_to_msa_income_pct", "number", required=True),
    Field("owner_occupied_units", "integer", required=True),
    Field("median_family_income_cents", "integer", required=True),
]


@bp.route("/hmda/census-tracts", methods=["POST"])
def create_census_tract():
    authenticate(["SystemAdmin"])
    body = check(json_body(), CREATE_FIELDS)
    row = store.new_row(versioned=False)
    row.update({
        "tract_code": body["tract_code"],
        "county_fips": body["county_fips"],
        "state_code": body["state_code"],
        "msa_md_code": body["msa_md_code"],
        "minority_population_pct": body["minority_population_pct"],
        "tract_to_msa_income_pct": body["tract_to_msa_income_pct"],
        "owner_occupied_units": body["owner_occupied_units"],
        "median_family_income_cents": body["median_family_income_cents"],
    })
    store.census_tracts[row["id"]] = row
    return object_response(S.census_tract(row), 201)


@bp.route("/hmda/census-tracts/<tract_id>", methods=["GET"])
def get_census_tract(tract_id):
    authenticate(C.ALL_ROLES)
    row = lookup(store.census_tracts, tract_id, "ERR_CENSUS_TRACT_NOT_FOUND")
    return object_response(S.census_tract(row))


@bp.route("/hmda/census-tracts/<tract_id>/geocode-assignments", methods=["GET"])
def list_tract_assignments(tract_id):
    authenticate(["SystemAdmin", "InstitutionAdmin", "ComplianceAnalyst",
                  "ComplianceOfficer", "Examiner"])
    lookup(store.census_tracts, tract_id, "ERR_CENSUS_TRACT_NOT_FOUND")
    limit, offset = pagination()
    is_current = bool_filter("is_current")
    rows = [g for g in store.ordered(store.geocode_assignments.values())
            if g["census_tract_id"] == tract_id
            and (is_current is None or g["is_current"] is is_current)]
    items, total = paginate(rows, limit, offset, S.geocode_assignment)
    return array_response(items, limit, offset, total)
