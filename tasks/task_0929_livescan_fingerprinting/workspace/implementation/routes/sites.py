from flask import Blueprint, request

import cardsvc
import constants as C
import derive
import fees
import serializers
import validation as V
from envelope import object_response, paginate
from lookups import body_row, path_row, require_record_state
from store import db

bp = Blueprint("sites", __name__)

_MOBILE_ONLY_FIELDS = (
    "host_agency_id",
    "event_window_start",
    "event_window_end",
    "min_billable_prints",
)


@bp.post("/livescan/sites")
def create_site():
    data = V.body()
    host_agency = None
    if data.get("host_agency_id") is not None:
        host_agency = body_row("agencies", data.get("host_agency_id"))

    site_kind = V.req_string(data, "site_kind")
    name = V.req_string(data, "name")
    capacity = V.req_int(data, "concurrent_capacity", minimum=1, maximum=50)
    window_start = V.opt_instant(data, "event_window_start")
    window_end = V.opt_instant(data, "event_window_end")
    min_prints = V.opt_int(data, "min_billable_prints", minimum=1, maximum=500)

    if site_kind == "MOBILE_EVENT":
        for field in _MOBILE_ONLY_FIELDS:
            if data.get(field) is None:
                V.bad_request("%s is required for a MOBILE_EVENT site" % field)
        if window_end <= window_start:
            V.bad_request("event_window_end must be strictly after event_window_start")
    elif site_kind == "FIXED":
        for field in _MOBILE_ONLY_FIELDS:
            if data.get(field) is not None:
                V.bad_request("%s may not be supplied for a FIXED site" % field)

    V.enum_value("site_kind", site_kind, C.SITE_KINDS)

    row = db.create(
        "sites",
        {
            "site_kind": site_kind,
            "name": name,
            "concurrent_capacity": capacity,
            "walkin_usable_capacity": derive.walkin_usable_capacity(capacity),
            "host_agency_id": host_agency["id"] if host_agency else None,
            "event_window_start": window_start,
            "event_window_end": window_end,
            "min_billable_prints": min_prints,
            "billable_print_count": 0,
            "reconciliation_status": "PENDING" if site_kind == "MOBILE_EVENT" else "NOT_APPLICABLE",
            "shortfall_charge_cents": 0,
        },
    )
    return object_response(serializers.site(row), 201)


@bp.get("/livescan/sites/<id>")
def read_site(id):
    return object_response(serializers.site(path_row("sites", id)))


@bp.get("/livescan/sites")
def list_sites():
    rows = list(db.sites.values())
    host_agency_id = request.args.get("host_agency_id")
    site_kind = request.args.get("site_kind")
    if host_agency_id is not None:
        rows = [r for r in rows if r["host_agency_id"] == host_agency_id]
    if site_kind is not None:
        rows = [r for r in rows if r["site_kind"] == site_kind]
    return paginate(rows, serializers.site)


@bp.post("/livescan/sites/<id>/event-reconciliation")
def reconcile_event(id):
    site = path_row("sites", id)
    require_record_state(site["site_kind"] == "MOBILE_EVENT", "site is not a MOBILE_EVENT")
    require_record_state(
        site["event_window_end"] is not None and db.now() >= site["event_window_end"],
        "the event window has not ended",
    )
    require_record_state(site["reconciliation_status"] == "PENDING", "event already reconciled")

    cardsvc.recompute_site_billable(site)
    shortfall_prints = max(0, site["min_billable_prints"] - site["billable_print_count"])
    site["shortfall_charge_cents"] = shortfall_prints * C.ONSITE_SHORTFALL_RATE_CENTS
    site["reconciliation_status"] = "RECONCILED"
    db.touch(site)

    if site["shortfall_charge_cents"] > 0:
        agency = db.agencies.get(site["host_agency_id"])
        if agency is not None:
            fees.create_shortfall_assessment(agency, site["shortfall_charge_cents"])

    for assignment in db.device_assignments.values():
        if assignment["site_id"] != site["id"]:
            continue
        if derive.assignment_status(assignment) not in ("SCHEDULED", "ACTIVE"):
            continue
        assignment["status"] = "RELEASED"
        db.touch(assignment)

    return object_response(serializers.site(site))
