"""Logical clock, specialty tracks, referring providers, specialists."""

from flask import Blueprint

import clock
import db
import services
import util
from middleware import require_roles, ANY_ROLE
from response import ok, ok_list
from util import serialize, serialize_list

bp = Blueprint("admin", __name__)


# --- logical clock -----------------------------------------------------------

@bp.route("/econsult/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles("ProgramCoordinator")
    data = util.json_body()
    moment = util.req_datetime(data, "to_iso8601")
    clock.set_now(moment)
    services.run_expiry_sweep()
    return ok({}, 200)


# --- specialty tracks ----------------------------------------------------------

@bp.route("/econsult/specialty-tracks", methods=["POST"])
def create_track():
    require_roles("ProgramCoordinator")
    data = util.json_body()
    code = util.req_enum(data, "specialty_code", util.SPECIALTY_CODES)
    routine_hours = util.req_int(data, "response_time_target_hours", min_v=1)
    urgent_hours = util.req_int(data, "urgent_target_hours", min_v=1)
    if urgent_hours >= routine_hours:
        util.invalid("urgent_target_hours must be strictly smaller than response_time_target_hours")
    base_fee = util.req_int(data, "base_response_fee_cents", min_v=0)
    conversion_fee = util.req_int(data, "conversion_response_fee_cents", min_v=0)
    clarification_fee = util.req_int(data, "clarification_fee_cents", min_v=0)
    late_penalty = util.req_int(data, "late_penalty_cents", min_v=0)
    cap = util.req_int(data, "monthly_billing_cap_cents", min_v=1)
    for existing in db.store["specialty_tracks"].values():
        if existing["specialty_code"] == code:
            util.invalid("specialty_code must be unique across tracks")

    rec = services.base_record()
    rec.update({
        "specialty_code": code,
        "response_time_target_hours": routine_hours,
        "urgent_target_hours": urgent_hours,
        "base_response_fee_cents": base_fee,
        "conversion_response_fee_cents": conversion_fee,
        "clarification_fee_cents": clarification_fee,
        "late_penalty_cents": late_penalty,
        "monthly_billing_cap_cents": cap,
    })
    db.store["specialty_tracks"][rec["id"]] = rec
    return ok(serialize("specialty_track", rec), 201)


@bp.route("/econsult/specialty-tracks/<rid>", methods=["GET"])
def get_track(rid):
    require_roles(*ANY_ROLE)
    return ok(serialize("specialty_track", services.get_track(rid)), 200)


# --- referring providers -------------------------------------------------------

@bp.route("/econsult/referring-providers", methods=["POST"])
def create_provider():
    require_roles("ProgramCoordinator")
    data = util.json_body()
    full_name = util.req_str(data, "full_name")
    npi = util.req_npi(data, "npi")
    status = util.opt_enum(data, "status", util.PROVIDER_STATUSES, default="ACTIVE")
    for existing in db.store["referring_providers"].values():
        if existing["npi"] == npi:
            util.invalid("npi must be unique across referring providers")

    rec = services.base_record()
    rec.update({"full_name": full_name, "npi": npi, "status": status})
    db.store["referring_providers"][rec["id"]] = rec
    return ok(serialize("referring_provider", rec), 201)


@bp.route("/econsult/referring-providers/<rid>", methods=["GET"])
def get_provider(rid):
    require_roles(*ANY_ROLE)
    return ok(serialize("referring_provider", services.get_provider(rid)), 200)


# --- specialists ---------------------------------------------------------------

@bp.route("/econsult/specialists", methods=["POST"])
def create_specialist():
    require_roles("ProgramCoordinator")
    data = util.json_body()
    full_name = util.req_str(data, "full_name")
    npi = util.req_npi(data, "npi")
    status = util.opt_enum(data, "status", util.PROVIDER_STATUSES, default="ACTIVE")
    for existing in db.store["specialists"].values():
        if existing["npi"] == npi:
            util.invalid("npi must be unique across specialists")

    rec = services.base_record()
    rec.update({"full_name": full_name, "npi": npi, "status": status})
    db.store["specialists"][rec["id"]] = rec
    return ok(serialize("specialist", rec), 201)


@bp.route("/econsult/specialists/<rid>", methods=["GET"])
def get_specialist(rid):
    require_roles(*ANY_ROLE)
    return ok(serialize("specialist", services.get_specialist(rid)), 200)


@bp.route("/econsult/specialists/<rid>/consult-responses", methods=["GET"])
def list_specialist_responses(rid):
    require_roles(*ANY_ROLE)
    specialist = services.get_specialist(rid)
    records = [
        resp for resp in db.store["consult_responses"].values()
        if resp["specialist_id"] == specialist["id"]
    ]
    page, total, limit, offset = util.paginate(records)
    return ok_list(serialize_list("consult_response", page), total, limit, offset)
