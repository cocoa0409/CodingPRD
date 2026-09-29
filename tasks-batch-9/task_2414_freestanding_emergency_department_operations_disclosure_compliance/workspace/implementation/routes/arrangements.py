"""Receiving-hospital transfer agreements and ambulance memoranda."""

from datetime import timedelta

from flask import Blueprint

import constants as C
from db import base_row, db, touch
from domain import (
    agreement_status,
    agreement_view,
    get_agreement,
    get_facility,
    get_mou,
    mou_status,
    mou_view,
    rows_of,
)
from errors import ApiError
from response import created, ok, ok_list, paginate
from validate import (
    auth,
    body,
    pagination,
    parse_date_str,
    query_enum,
    req_bool,
    req_date,
    req_datetime,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("arrangements", __name__)


@bp.post("/facilities/<fid>/transfer-agreements")
def create_agreement(fid):
    auth("FacilityAdministrator", "HospitalTransferCoordinator")
    data = body()
    destination = req_str(data, "destination_hospital_name", 1, 120)
    service_line = req_enum(data, "service_line", C.SERVICE_LINES)
    capability_tier = req_int(data, "capability_tier", minimum=1, maximum=4)
    accepts_unstable = req_bool(data, "accepts_unstable")
    start_date = req_date(data, "effective_start_date")
    end_date = req_date(data, "effective_end_date")
    if end_date < start_date:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "effective_end_date must not be earlier than effective_start_date",
        )

    facility = get_facility(fid)

    new_start = parse_date_str(start_date, "effective_start_date")
    new_end = parse_date_str(end_date, "effective_end_date")
    gap = timedelta(days=C.AGREEMENT_MIN_GAP_DAYS + 1)
    for existing in db.agreements.values():
        if existing["facility_id"] != facility["id"]:
            continue
        if existing["destination_hospital_name"] != destination:
            continue
        if existing["service_line"] != service_line:
            continue
        old_start = parse_date_str(existing["effective_start_date"], "effective_start_date")
        old_end = parse_date_str(existing["effective_end_date"], "effective_end_date")
        separated = new_start >= old_end + gap or new_end + gap <= old_start
        if not separated:
            raise ApiError("ERR_AGREEMENT_WINDOW_CONFLICT")

    agreement = base_row()
    agreement.update(
        {
            "facility_id": facility["id"],
            "destination_hospital_name": destination,
            "service_line": service_line,
            "capability_tier": capability_tier,
            "accepts_unstable": accepts_unstable,
            "effective_start_date": start_date,
            "effective_end_date": end_date,
        }
    )
    db.agreements[agreement["id"]] = agreement
    return created(agreement_view(agreement))


@bp.get("/facilities/<fid>/transfer-agreements")
def list_agreements(fid):
    auth(
        "FacilityAdministrator",
        "ComplianceOfficer",
        "EmergencyPhysician",
        "HospitalTransferCoordinator",
    )
    status = query_enum("status", C.AGREEMENT_STATUSES)
    service_line = query_enum("service_line", C.SERVICE_LINES)
    limit, offset = pagination()
    facility = get_facility(fid)
    rows = rows_of(db.agreements, facility_id=facility["id"])
    if status is not None:
        rows = [r for r in rows if agreement_status(r) == status]
    if service_line is not None:
        rows = [r for r in rows if r["service_line"] == service_line]
    page = paginate(rows, limit, offset)
    return ok_list([agreement_view(r) for r in page], limit, offset, len(rows))


@bp.get("/transfer-agreements/<aid>")
def read_agreement(aid):
    auth(
        "FacilityAdministrator",
        "ComplianceOfficer",
        "EmergencyPhysician",
        "HospitalTransferCoordinator",
    )
    return ok(agreement_view(get_agreement(aid)))


@bp.post("/facilities/<fid>/ambulance-mous")
def create_mou(fid):
    auth("FacilityAdministrator")
    data = body()
    carrier_name = req_str(data, "carrier_name", 1, 120)
    level_of_care = req_enum(data, "level_of_care", C.LEVELS_OF_CARE)
    coverage_start_at = req_datetime(data, "coverage_start_at")
    coverage_end_at = req_datetime(data, "coverage_end_at")
    if coverage_end_at <= coverage_start_at:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "coverage_end_at must be strictly later than coverage_start_at",
        )
    units_committed = req_int(data, "units_committed", minimum=0)

    facility = get_facility(fid)

    mou = base_row()
    mou.update(
        {
            "facility_id": facility["id"],
            "carrier_name": carrier_name,
            "level_of_care": level_of_care,
            "coverage_start_at": coverage_start_at,
            "coverage_end_at": coverage_end_at,
            "units_committed": units_committed,
        }
    )
    db.mous[mou["id"]] = mou
    touch(facility)
    return created(mou_view(mou))


@bp.get("/facilities/<fid>/ambulance-mous")
def list_mous(fid):
    auth("FacilityAdministrator", "ComplianceOfficer", "EmergencyPhysician")
    status = query_enum("status", C.MOU_STATUSES)
    saturation_state = query_enum("saturation_state", C.SATURATION_STATES)
    limit, offset = pagination()
    facility = get_facility(fid)
    rows = rows_of(db.mous, facility_id=facility["id"])
    if status is not None:
        rows = [r for r in rows if mou_status(r) == status]
    if saturation_state is not None:
        rows = [r for r in rows if mou_view(r)["saturation_state"] == saturation_state]
    page = paginate(rows, limit, offset)
    return ok_list([mou_view(r) for r in page], limit, offset, len(rows))


@bp.get("/ambulance-mous/<mid>")
def read_mou(mid):
    auth("FacilityAdministrator", "ComplianceOfficer", "EmergencyPhysician")
    return ok(mou_view(get_mou(mid)))
