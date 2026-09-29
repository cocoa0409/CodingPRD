"""Service address registration and duplicate-cohort adjudication."""
from flask import Blueprint

import db
import response
import validation as v
from errors import ApiError
from routes.common import (PROGRAM_ADMINISTRATOR, PROVIDER_AGENT, ROLES_ALL,
                           authenticate, get_address)
from services import calc, cascades, derive

bp = Blueprint("addresses", __name__)

RESOLUTIONS = ("MULTI_HOUSEHOLD", "SINGLE_HOUSEHOLD")
REFLAGGABLE = ("UNVERIFIED", "RESOLVED_MULTI_HOUSEHOLD", "RESOLVED_SINGLE_HOUSEHOLD")


@bp.post("/lifeline/addresses")
def create_address():
    authenticate((PROVIDER_AGENT, PROGRAM_ADMINISTRATOR))
    body = v.get_body()
    line1 = v.string_field(body, "address_line1", min_len=1, max_len=160)
    unit = v.string_field(body, "unit_designator", required=False, min_len=0,
                          max_len=16, default=None)
    city = v.string_field(body, "city", min_len=1, max_len=80)
    state_code = v.string_field(body, "state_code", pattern=r"^[A-Za-z]{2}$",
                                min_len=2, max_len=2)
    postal_code = v.string_field(body, "postal_code",
                                 pattern=r"^(\d{5}|\d{9})$", min_len=5, max_len=9)

    address_hash = calc.address_hash(line1, unit, city, state_code, postal_code)
    cohort = db.by_created(derive.addresses_with_hash(address_hash))

    row = db.base_row()
    row.update({
        "address_line1": line1,
        "unit_designator": unit,
        "city": city,
        "state_code": state_code,
        "postal_code": postal_code,
        "address_hash": address_hash,
        "status": "DUPLICATE_FLAGGED" if cohort else "UNVERIFIED",
        "declared_household_count": None,
        "independent_household_worksheet_ref": None,
    })
    db.db.addresses[row["id"]] = row

    # cohort_address_count is recomputed on every pre-existing row sharing the
    # hash; a cohort of two or more additionally flags every resolvable row.
    if cohort:
        for peer in cohort:
            if peer["status"] in REFLAGGABLE:
                peer["status"] = "DUPLICATE_FLAGGED"
            db.touch(peer)

    return response.ok(derive.address_json(row), 201)


@bp.get("/lifeline/addresses/<address_id>")
def read_address(address_id):
    authenticate(ROLES_ALL)
    address = get_address(address_id)
    return response.ok(derive.address_json(address))


@bp.post("/lifeline/addresses/<address_id>/duplicate-resolution")
def resolve_duplicate(address_id):
    caller = authenticate((PROGRAM_ADMINISTRATOR,))
    address = get_address(address_id)

    body = v.get_body()
    resolution = v.enum_field(body, "resolution", RESOLUTIONS)
    expected_version = v.int_field(body, "expected_address_version")
    v.string_field(body, "resolution_note", required=False, min_len=0, default=None)
    declared = None
    worksheet = None
    if resolution == "MULTI_HOUSEHOLD":
        declared = v.int_field(body, "declared_household_count", minimum=2)
        worksheet = v.string_field(body, "independent_household_worksheet_ref",
                                   min_len=1)

    if expected_version != address["version"]:
        raise ApiError("ERR_STALE_ADDRESS_VERSION",
                       "expected_address_version does not match the dwelling's version")

    if address["status"] != "DUPLICATE_FLAGGED":
        raise ApiError("ERR_ADDRESS_NOT_FLAGGED",
                       "Only a DUPLICATE_FLAGGED dwelling can be resolved")

    if resolution == "MULTI_HOUSEHOLD":
        address["declared_household_count"] = declared
        address["independent_household_worksheet_ref"] = worksheet
        address["status"] = "RESOLVED_MULTI_HOUSEHOLD"
        db.touch(address)
        cascades.release_duplicate_holds(address)
    else:
        cascades.clear_duplicate_flag(address)
        actives = sorted(
            [e for e in derive.enrollments_at_address(address["id"])
             if e["benefit_status"] == "ACTIVE"],
            key=lambda e: (e["benefit_start_date"], e["created_at"], e["_seq"]),
        )
        for enrollment in actives[1:]:
            cascades.de_enroll(enrollment, "DUPLICATE_HOUSEHOLD", caller.user_id,
                               skip_address_id=address["id"])
        address["status"] = "RESOLVED_SINGLE_HOUSEHOLD"
        db.touch(address)
        cascades.release_duplicate_holds(address)

    return response.ok(derive.address_json(address))
