"""Factory and InspectionAgency endpoints."""

from flask import Blueprint

import auth
import serialize
import services
import validate
from envelope import created, ok, ok_list, paginate
from errors import ApiError
from store import base_row, db, sorted_rows, touch

bp = Blueprint("registry", __name__)

LINE_STATES = ("RUNNING", "PAUSED", "SHUTDOWN")
ACCREDITATION_STATES = ("ACCREDITED", "PROBATION", "SUSPENDED")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
@bp.post("/modular/factories")
@auth.endpoint("ProgramAdmin")
def create_factory():
    data = validate.body(optional=False)
    name = validate.field_str(data, "name")
    code = validate.field_str(data, "code")
    takt_minutes = validate.field_int(data, "takt_minutes", minimum=1)
    station_count = validate.field_int(data, "station_count", minimum=1)
    parallel_station_capacity = validate.field_int(
        data, "parallel_station_capacity", minimum=1
    )
    wip_unit_value_cents = validate.field_int(data, "wip_unit_value_cents", minimum=0)
    shift_start_minute_of_day = validate.field_int(
        data, "shift_start_minute_of_day", required=False, default=360, minimum=0, maximum=1439
    )
    shift_minutes_per_day = validate.field_int(
        data, "shift_minutes_per_day", required=False, default=1080, minimum=1, maximum=1440
    )
    line_state = validate.field_enum(
        data, "line_state", LINE_STATES, required=False, default="RUNNING"
    )

    # rank 73 — Factory.code is globally unique
    if any(row["code"] == code for row in db.factories.values()):
        raise ApiError("ERR_DUPLICATE_CODE", "factory code %s already exists" % code)

    row = base_row()
    row.update(
        {
            "name": name,
            "code": code,
            "takt_minutes": takt_minutes,
            "station_count": station_count,
            "parallel_station_capacity": parallel_station_capacity,
            "wip_unit_value_cents": wip_unit_value_cents,
            "shift_start_minute_of_day": shift_start_minute_of_day,
            "shift_minutes_per_day": shift_minutes_per_day,
            "line_state": line_state,
            "committed_line_minutes": 0,
        }
    )
    db.factories[row["id"]] = row
    return created(serialize.factory(row))


@bp.get("/modular/factories/<factory_id>")
@auth.endpoint(
    "ProgramAdmin",
    "FactoryProductionManager",
    "LenderDrawAdministrator",
    "StateProgramOfficer",
)
def read_factory(factory_id):
    return ok(serialize.factory(services.get_factory(factory_id)))


@bp.get("/modular/factories")
@auth.endpoint("ProgramAdmin", "FactoryProductionManager", "LenderDrawAdministrator")
def list_factories():
    code = validate.field_str_query("code")
    line_state = validate.enum_query("line_state", LINE_STATES)
    rows = sorted_rows(list(db.factories.values()))
    if code is not None:
        rows = [r for r in rows if r["code"] == code]
    if line_state is not None:
        rows = [r for r in rows if r["line_state"] == line_state]
    page, meta = paginate(rows)
    return ok_list([serialize.factory(r) for r in page], meta)


@bp.patch("/modular/factories/<factory_id>/line-state")
@auth.endpoint("ProgramAdmin", "FactoryProductionManager")
def patch_line_state(factory_id):
    data = validate.body(optional=False)
    line_state = validate.field_enum(data, "line_state", LINE_STATES)
    row = services.get_factory(factory_id)
    row["line_state"] = line_state
    touch(row)
    return ok(serialize.factory(row))


# ---------------------------------------------------------------------------
# InspectionAgency
# ---------------------------------------------------------------------------
@bp.post("/modular/agencies")
@auth.endpoint("ProgramAdmin")
def create_agency():
    data = validate.body(optional=False)
    name = validate.field_str(data, "name")
    agency_code = validate.field_str(data, "agency_code")
    accredited_state_codes = validate.field_state_codes(data, "accredited_state_codes")
    per_inspection_fee_cents = validate.field_int(
        data, "per_inspection_fee_cents", minimum=0
    )
    accreditation_state = validate.field_enum(
        data,
        "accreditation_state",
        ACCREDITATION_STATES,
        required=False,
        default="ACCREDITED",
    )
    hold_authority = validate.field_bool(
        data, "hold_authority", required=False, default=True
    )

    # rank 73 — InspectionAgency.agency_code is globally unique
    if any(row["agency_code"] == agency_code for row in db.agencies.values()):
        raise ApiError(
            "ERR_DUPLICATE_CODE", "agency code %s already exists" % agency_code
        )

    row = base_row()
    row.update(
        {
            "name": name,
            "agency_code": agency_code,
            "accreditation_state": accreditation_state,
            "accredited_state_codes": accredited_state_codes,
            "per_inspection_fee_cents": per_inspection_fee_cents,
            "hold_authority": hold_authority,
        }
    )
    db.agencies[row["id"]] = row
    return created(serialize.agency(row))


@bp.get("/modular/agencies/<agency_id>")
@auth.endpoint(
    "ProgramAdmin",
    "ThirdPartyInspector",
    "LenderDrawAdministrator",
    "StateProgramOfficer",
)
def read_agency(agency_id):
    return ok(serialize.agency(services.get_agency(agency_id)))


@bp.get("/modular/agencies")
@auth.endpoint("ProgramAdmin", "ThirdPartyInspector", "LenderDrawAdministrator")
def list_agencies():
    agency_code = validate.field_str_query("agency_code")
    accreditation_state = validate.enum_query(
        "accreditation_state", ACCREDITATION_STATES
    )
    rows = sorted_rows(list(db.agencies.values()))
    if agency_code is not None:
        rows = [r for r in rows if r["agency_code"] == agency_code]
    if accreditation_state is not None:
        rows = [r for r in rows if r["accreditation_state"] == accreditation_state]
    page, meta = paginate(rows)
    return ok_list([serialize.agency(r) for r in page], meta)


@bp.patch("/modular/agencies/<agency_id>/accreditation")
@auth.endpoint("ProgramAdmin", "StateProgramOfficer")
def patch_accreditation(agency_id):
    data = validate.body(optional=False)
    accreditation_state = validate.field_enum(
        data, "accreditation_state", ACCREDITATION_STATES
    )
    accredited_state_codes = validate.field_state_codes(
        data, "accredited_state_codes", required=False
    )
    row = services.get_agency(agency_id)
    row["accreditation_state"] = accreditation_state
    if accredited_state_codes is not None:
        row["accredited_state_codes"] = accredited_state_codes
    touch(row)
    return ok(serialize.agency(row))
