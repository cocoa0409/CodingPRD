"""Certification programs (immutable reference data)."""

from flask import Blueprint

import calc
from db import new_row, store
from errors import fail
from middleware import authenticate
from refs import apply_filters, get_program
from response import created_response, list_response, object_response
from validate import body, bool_field, dec_field, int_field, str_field

bp = Blueprint("programs", __name__)

READ_ROLES = ("CorporateOps", "QualityEngineer", "CertificationOfficer", "ChannelManager")

CONFORMANCE_BASES = ("PER_SPECIMEN", "LOT_MEAN")


@bp.post("/certification-programs")
def create_program():
    authenticate(("CorporateOps",))
    payload = body()
    code = str_field(payload, "code")
    basis = str_field(payload, "conformance_basis", allowed=CONFORMANCE_BASES)
    tolerance = dec_field(payload, "r_value_tolerance", ge=0)
    min_specimen_count = int_field(payload, "min_specimen_count", minimum=1)
    max_concurrent = int_field(payload, "max_concurrent_lab_tests", minimum=1)
    retest_limit = int_field(payload, "retest_limit", minimum=1)
    derate_allowed = bool_field(payload, "derate_allowed")
    for existing in store.programs.values():
        if existing["code"] == code:
            fail("ERR_INVALID_REQUEST", "code %s is already registered" % code)

    row = new_row(common=False)
    row.update({
        "code": code,
        "conformance_basis": basis,
        "r_value_tolerance": calc.q2(tolerance),
        "min_specimen_count": min_specimen_count,
        "max_concurrent_lab_tests": max_concurrent,
        "retest_limit": retest_limit,
        "derate_allowed": derate_allowed,
    })
    store.programs[row["id"]] = row
    return created_response(row)


@bp.get("/certification-programs/<program_id>")
def read_program(program_id):
    authenticate(READ_ROLES)
    return object_response(get_program(program_id))


@bp.get("/certification-programs")
def list_programs():
    authenticate(READ_ROLES)
    rows = apply_filters(store.programs.values(), {"conformance_basis": ("conformance_basis", "str")})
    return list_response(rows)
