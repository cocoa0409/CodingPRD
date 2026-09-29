"""Host site agreements, power upgrades and access governance (PRD §3.1)."""
from flask import Blueprint

import db
import lookup
import serialize
import validation
from errors import err
from middleware import endpoint, current_user_id, current_role
from response import array_response, object_response, paginate

bp = Blueprint("host_sites", __name__)

AGREEMENT_STATUSES = ("DRAFT", "EXECUTED", "TERMINATED")
POWER_UPGRADE_STATUSES = ("NOT_REQUIRED", "REQUESTED", "IN_PROGRESS", "ENERGIZED")
ACCESS_HOURS_MODES = ("TWENTY_FOUR_SEVEN", "RESTRICTED")
PARKING_ENFORCEMENT_MODES = ("NONE", "SIGNAGE_ONLY", "TOWING_ENFORCED")


def _check_access_window(mode, open_minute, close_minute):
    if mode == "RESTRICTED" and not open_minute < close_minute:
        raise err("ERR_INVALID_ACCESS_WINDOW",
                  "access_open_minute must be strictly earlier than access_close_minute.")


@bp.post("/host-sites")
@endpoint("NetworkOperator")
def register_host_site():
    body = validation.json_body()
    site_code = validation.as_string(body, "site_code")
    host_org_name = validation.as_string(body, "host_org_name")
    capacity = validation.as_number(body, "committed_service_capacity_kw",
                                   exclusive_minimum=0, places=2)
    agreement_status = validation.as_enum(body, "agreement_status", AGREEMENT_STATUSES,
                                          required=False, default="DRAFT")
    power_upgrade_status = validation.as_enum(body, "power_upgrade_status",
                                             POWER_UPGRADE_STATUSES,
                                             required=False, default="REQUESTED")
    access_hours_mode = validation.as_enum(body, "access_hours_mode", ACCESS_HOURS_MODES,
                                          required=False, default="TWENTY_FOUR_SEVEN")
    access_open_minute = validation.as_int(body, "access_open_minute", required=False,
                                          default=0, minimum=0, maximum=1439)
    access_close_minute = validation.as_int(body, "access_close_minute", required=False,
                                           default=1440, minimum=1, maximum=1440)
    parking_enforcement_mode = validation.as_enum(body, "parking_enforcement_mode",
                                                 PARKING_ENFORCEMENT_MODES,
                                                 required=False, default="NONE")

    for existing in db.host_sites.values():
        if existing["site_code"] == site_code:
            raise err("ERR_SITE_CODE_DUPLICATE", "site_code is already registered.")

    _check_access_window(access_hours_mode, access_open_minute, access_close_minute)

    row = db.base_record()
    row.update({
        "site_code": site_code,
        "host_org_name": host_org_name,
        "agreement_status": agreement_status,
        "power_upgrade_status": power_upgrade_status,
        "access_hours_mode": access_hours_mode,
        "access_open_minute": access_open_minute,
        "access_close_minute": access_close_minute,
        "parking_enforcement_mode": parking_enforcement_mode,
        "committed_service_capacity_kw": capacity,
    })
    db.host_sites[row["id"]] = row
    db.mark_fresh(row)
    return object_response(serialize.host_site(row), 201)


@bp.get("/host-sites")
@endpoint()
def list_host_sites():
    limit, offset = validation.pagination()
    rows = db.sort_rows(list(db.host_sites.values()))
    rows = validation.apply_filters(rows, validation.filters("agreement_status"))
    page, total = paginate(rows, limit, offset)
    return array_response([serialize.host_site(r) for r in page], limit, offset, total)


@bp.get("/host-sites/<host_site_id>")
@endpoint()
def get_host_site(host_site_id):
    row = lookup.host_site(host_site_id)
    return object_response(serialize.host_site(row))


@bp.get("/host-sites/<host_site_id>/stations")
@endpoint()
def list_stations_of_host_site(host_site_id):
    site = lookup.host_site(host_site_id)
    limit, offset = validation.pagination()
    rows = db.sort_rows([s for s in db.stations.values()
                         if s["host_site_id"] == site["id"]])
    rows = validation.apply_filters(rows, validation.filters("status"))
    page, total = paginate(rows, limit, offset)
    return array_response([serialize.station(r) for r in page], limit, offset, total)


@bp.patch("/host-sites/<host_site_id>")
@endpoint("NetworkOperator", "HostSiteManager")
def amend_host_site(host_site_id):
    row = lookup.host_site(host_site_id)

    if current_role() == "HostSiteManager" and current_user_id() != row["id"]:
        raise err("ERR_HOST_SITE_FORBIDDEN",
                  "A HostSiteManager may only amend their own host site.")

    body = validation.json_body()
    agreement_status = validation.as_enum(body, "agreement_status", AGREEMENT_STATUSES,
                                          required=False, default=None)
    power_upgrade_status = validation.as_enum(body, "power_upgrade_status",
                                             POWER_UPGRADE_STATUSES,
                                             required=False, default=None)
    access_hours_mode = validation.as_enum(body, "access_hours_mode", ACCESS_HOURS_MODES,
                                          required=False, default=None)
    access_open_minute = validation.as_int(body, "access_open_minute", required=False,
                                          default=None, minimum=0, maximum=1439)
    access_close_minute = validation.as_int(body, "access_close_minute", required=False,
                                           default=None, minimum=1, maximum=1440)
    parking_enforcement_mode = validation.as_enum(body, "parking_enforcement_mode",
                                                  PARKING_ENFORCEMENT_MODES,
                                                  required=False, default=None)
    capacity = validation.as_number(body, "committed_service_capacity_kw", required=False,
                                    default=None, exclusive_minimum=0, places=2)

    effective_mode = access_hours_mode if access_hours_mode is not None else row["access_hours_mode"]
    effective_open = (access_open_minute if access_open_minute is not None
                      else row["access_open_minute"])
    effective_close = (access_close_minute if access_close_minute is not None
                       else row["access_close_minute"])
    _check_access_window(effective_mode, effective_open, effective_close)

    updates = {
        "agreement_status": agreement_status,
        "power_upgrade_status": power_upgrade_status,
        "access_hours_mode": access_hours_mode,
        "access_open_minute": access_open_minute,
        "access_close_minute": access_close_minute,
        "parking_enforcement_mode": parking_enforcement_mode,
        "committed_service_capacity_kw": capacity,
    }
    for field, value in updates.items():
        if value is not None:
            row[field] = value
    db.touch(row)
    return object_response(serialize.host_site(row))
