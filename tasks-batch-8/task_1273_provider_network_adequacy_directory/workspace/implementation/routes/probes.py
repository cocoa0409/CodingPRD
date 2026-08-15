"""AvailabilityProbe endpoints: schedule, list, get, record."""

from flask import Blueprint

import db
import errors
import helpers
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services.ghost import recompute_ghost_strikes

bp = Blueprint("probes", __name__)

PROBE_STATUSES = {"SCHEDULED", "RECORDED"}
PROBE_RESULTS = {"PASS", "FAIL"}


def _find_standard(specialty, geo_class):
    for s in db.standards.values():
        if s["specialty"] == specialty and s["geo_class"] == geo_class:
            return s
    return None


@bp.route("/network/probes", methods=["POST"])
@require_roles("NetworkManager")
def create_probe(user_id, role):
    body = helpers.get_body()
    listing_id = helpers.req_str(body, "listing_id")
    probe_type = helpers.req_enum(body, "probe_type", helpers.PROBE_TYPES)
    requested_date = helpers.req_str(body, "requested_date")
    rd = helpers.parse_date(requested_date, "requested_date")
    listing = db.listings.get(listing_id)
    if listing is None:
        raise errors.err_listing_not_found()
    if listing["status"] == "REMOVED":
        raise errors.err_listing_removed()
    if listing["status"] != "LISTED":
        raise errors.err_listing_not_listed()
    if rd > helpers.clock_date():
        raise errors.err_probe_date_order()
    rec = {
        "listing_id": listing_id, "probe_type": probe_type,
        "requested_date": requested_date, "status": "SCHEDULED",
        "outcome": None, "offered_appointment_date": None,
        "days_to_appointment": None, "result": None, "recorded_at": None,
    }
    helpers.stamp_new(rec)
    db.probes[rec["id"]] = rec
    return success_object(helpers.ser_probe(rec), 201)


@bp.route("/network/probes", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_probes(user_id, role):
    limit, offset = helpers.get_pagination()
    listing_id = helpers.query_str("listing_id")
    result = helpers.query_enum("result", PROBE_RESULTS)
    items = list(db.probes.values())
    if listing_id is not None:
        items = [p for p in items if p["listing_id"] == listing_id]
    if result is not None:
        items = [p for p in items if p["result"] == result]
    page, total = helpers.paginate(items, limit, offset)
    return success_list([helpers.ser_probe(p) for p in page], limit, offset, total)


@bp.route("/network/probes/<pid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_probe(user_id, role, pid):
    rec = db.probes.get(pid)
    if rec is None:
        raise errors.err_probe_not_found()
    return success_object(helpers.ser_probe(rec))


@bp.route("/network/probes/<pid>/record", methods=["POST"])
@require_roles("NetworkManager")
def record_probe(user_id, role, pid):
    rec = db.probes.get(pid)
    if rec is None:
        raise errors.err_probe_not_found()
    if rec["status"] != "SCHEDULED":
        raise errors.err_probe_invalid_state()
    body = helpers.get_body()
    outcome = helpers.req_enum(body, "outcome", helpers.PROBE_OUTCOMES)
    requested = helpers.parse_date(rec["requested_date"], "requested_date")
    offered_str = None
    days = None
    if outcome == "KEPT":
        offered_str = helpers.req_str(body, "offered_appointment_date")
        offered = helpers.parse_date(offered_str, "offered_appointment_date")
        if offered < requested:
            raise errors.err_probe_date_order()
        days = (offered - requested).days
    else:
        if body.get("offered_appointment_date") is not None:
            # offered date only meaningful for KEPT
            raise errors.err_invalid("offered_appointment_date only allowed when outcome == KEPT")
    # compute result against the applicable standard
    listing = db.listings.get(rec["listing_id"])
    location = db.locations.get(listing["location_id"]) if listing else None
    region = db.regions.get(location["region_id"]) if location else None
    standard = _find_standard(listing["specialty"], region["geo_class"]) if region else None
    if outcome == "KEPT" and standard is not None:
        limit = (standard["max_wait_days_routine"] if rec["probe_type"] == "ROUTINE"
                 else standard["max_wait_days_urgent"])
        result = "PASS" if days <= limit else "FAIL"
    else:
        result = "FAIL"
    rec["outcome"] = outcome
    rec["offered_appointment_date"] = offered_str
    rec["days_to_appointment"] = days
    rec["result"] = result
    rec["recorded_at"] = helpers.now_iso()
    rec["status"] = "RECORDED"
    helpers.touch(rec)
    if listing is not None:
        recompute_ghost_strikes(listing)
    return success_object(helpers.ser_probe(rec))
