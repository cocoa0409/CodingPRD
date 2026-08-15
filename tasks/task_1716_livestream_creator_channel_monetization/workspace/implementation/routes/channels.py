"""Channel onboarding, read, and OCC-guarded payout-settings patch."""

from flask import Blueprint

import db
import domain
from core import (ApiError, auth, body, err_invalid_request, err_not_found,
                  err_ownership, ok_obj, opt_enum, opt_int, req_enum, req_int,
                  req_str, require_role)

bp = Blueprint("channels", __name__)

HOME_PLATFORMS = ("TWITCH", "YOUTUBE")
PAYOUT_SCHEDULES = ("WEEKLY", "BIWEEKLY", "MONTHLY")
ALL_ROLES = ("PlatformAdmin", "Creator", "Moderator", "Sponsor", "TrustAgent", "AppealsOfficer")


@bp.post("/api/channels")
def create_channel():
    uid, role = auth()
    b = body()
    handle = req_str(b, "handle")
    display_name = req_str(b, "display_name")
    home_platform = req_enum(b, "home_platform", HOME_PLATFORMS)
    payout_schedule = opt_enum(b, "payout_schedule", PAYOUT_SCHEDULES, "MONTHLY")
    payout_threshold_cents = opt_int(b, "payout_threshold_cents", 10000, lo=0)
    require_role(role, ("PlatformAdmin",))
    # Uniqueness (priority 18): duplicate handle -> ERR_INVALID_REQUEST.
    if any(c["handle"] == handle for c in db.store.channels.values()):
        raise err_invalid_request("Channel handle already exists")
    ch = db.new_entity(
        handle=handle,
        display_name=display_name,
        home_platform=home_platform,
        payout_schedule=payout_schedule,
        payout_threshold_cents=payout_threshold_cents,
        tax_form_current_id=None,
    )
    db.store.channels[ch["id"]] = ch
    return ok_obj(domain.channel_json(ch), status=201)


@bp.get("/api/channels/<channel_id>")
def get_channel(channel_id):
    uid, role = auth()
    require_role(role, ALL_ROLES)
    ch = domain.get_channel(channel_id)
    if ch is None:
        raise err_not_found("Channel not found")
    return ok_obj(domain.channel_json(ch))


@bp.patch("/api/channels/<channel_id>/payout-settings")
def patch_payout_settings(channel_id):
    uid, role = auth()
    b = body()
    payout_schedule = opt_enum(b, "payout_schedule", PAYOUT_SCHEDULES, None)
    payout_threshold_cents = opt_int(b, "payout_threshold_cents", None, lo=0)
    expected_version = req_int(b, "expected_channel_version")
    require_role(role, ("Creator",))
    ch = domain.get_channel(channel_id)
    if ch is None:
        raise err_not_found("Channel not found")
    if uid != ch["id"]:
        raise err_ownership()
    # OCC (priority 17)
    if expected_version != ch["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_channel_version does not match the channel's current version")
    if payout_schedule is not None:
        ch["payout_schedule"] = payout_schedule
    if payout_threshold_cents is not None:
        ch["payout_threshold_cents"] = payout_threshold_cents
    db.touch(ch)
    return ok_obj(domain.channel_json(ch))
