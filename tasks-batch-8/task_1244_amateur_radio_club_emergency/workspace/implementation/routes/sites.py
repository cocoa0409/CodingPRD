"""Antenna site agreement endpoints (PRD §3.2): negotiation, activation,
termination, renewal; closed-interval overlap rule on site_name."""
from flask import Blueprint, request

import db
import services as svc
from errors import ERR_INVALID_STATE, ERR_SITE_WINDOW_CONFLICT, ApiError
from middleware import auth_context, require_role
from response import paginate, success
from util import (
    as_dt, as_enum, as_str, bad_request, body_json, need, reject_unknown_fields,
)

bp = Blueprint("sites", __name__)

SITE_STATUSES = {"NEGOTIATION", "ACTIVE", "EXPIRED", "TERMINATED"}
ADMIN = {"ClubAdmin"}


def _auth(allowed):
    user_id, role = auth_context()
    require_role(role, allowed)
    return user_id, role


def _window_conflicts(site_name, lease_start, lease_end, exclude_id=None):
    """Closed-interval [lease_start, lease_end] overlap vs same-site agreements
    in {NEGOTIATION, ACTIVE}; touching endpoints count as overlap."""
    for o in db.STORE["site_agreements"].values():
        if o["site_name"] != site_name or o["id"] == exclude_id:
            continue
        if o["status"] not in ("NEGOTIATION", "ACTIVE"):
            continue
        if lease_start <= o["lease_end"] and o["lease_start"] <= lease_end:
            return True
    return False


@bp.post("/antenna-site-agreements")
def create_site():
    _auth(ADMIN)
    body = body_json(request)
    reject_unknown_fields(body, {"site_name", "owner_name", "lease_start",
                                 "lease_end"})
    site_name = as_str(need(body, "site_name"), "site_name")
    owner_name = as_str(need(body, "owner_name"), "owner_name")
    lease_start = as_dt(need(body, "lease_start"), "lease_start")
    lease_end = as_dt(need(body, "lease_end"), "lease_end")
    if _window_conflicts(site_name, lease_start, lease_end):
        raise ApiError(ERR_SITE_WINDOW_CONFLICT, 409,
                       "lease window overlaps an existing agreement on %s"
                       % site_name)
    site = {
        "site_name": site_name,
        "owner_name": owner_name,
        "lease_start": lease_start,
        "lease_end": lease_end,
        "status": "NEGOTIATION",
        "renewal_count": 0,
    }
    svc.stamp_new(site)
    db.STORE["site_agreements"][site["id"]] = site
    return success(svc.ser_site(site), "object", 201)


@bp.get("/antenna-site-agreements")
def list_sites():
    _auth(ADMIN)
    status = request.args.get("status")
    site_name = request.args.get("site_name")
    items = []
    for s in svc.sorted_records("site_agreements"):
        if status is not None and s["status"] != status:
            continue
        if site_name is not None and s["site_name"] != site_name:
            continue
        items.append(svc.ser_site(s))
    page, meta = paginate(items, request.args)
    return success(page, "array", 200, meta)


@bp.get("/antenna-site-agreements/<sid>")
def get_site(sid):
    _auth(ADMIN)
    return success(svc.ser_site(svc.get_site(sid)), "object", 200)


@bp.post("/antenna-site-agreements/<sid>/set-status")
def set_site_status(sid):
    _auth(ADMIN)
    site = svc.get_site(sid)
    body = body_json(request)
    reject_unknown_fields(body, {"to", "lease_start", "lease_end"})
    to = as_enum(need(body, "to"), "to", SITE_STATUSES)
    current = site["status"]
    if to == "ACTIVE":
        if current != "NEGOTIATION":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "cannot activate from %s" % current)
        if site["lease_end"] <= db.now():
            raise ApiError(ERR_INVALID_STATE, 409,
                           "lease_end must be in the future to activate")
        if _window_conflicts(site["site_name"], site["lease_start"],
                             site["lease_end"], exclude_id=site["id"]):
            raise ApiError(ERR_SITE_WINDOW_CONFLICT, 409,
                           "lease window overlaps an existing agreement on %s"
                           % site["site_name"])
        site["status"] = "ACTIVE"
        svc.touch(site)
    elif to == "TERMINATED":
        if current not in ("NEGOTIATION", "ACTIVE"):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "cannot terminate from %s" % current)
        was_active = current == "ACTIVE"
        site["status"] = "TERMINATED"
        svc.touch(site)
        if was_active:
            svc.site_leaving_active_cascade(site)
    elif to == "NEGOTIATION":
        # Renewal: EXPIRED -> NEGOTIATION requires fresh lease bounds.
        if current != "EXPIRED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "only an EXPIRED agreement can be renewed")
        if "lease_start" not in body or body.get("lease_start") is None:
            bad_request("lease_start is required for renewal")
        if "lease_end" not in body or body.get("lease_end") is None:
            bad_request("lease_end is required for renewal")
        lease_start = as_dt(body["lease_start"], "lease_start")
        lease_end = as_dt(body["lease_end"], "lease_end")
        if lease_end <= db.now():
            raise ApiError(ERR_INVALID_STATE, 409,
                           "lease_end must be in the future to renew")
        if _window_conflicts(site["site_name"], lease_start, lease_end,
                             exclude_id=site["id"]):
            raise ApiError(ERR_SITE_WINDOW_CONFLICT, 409,
                           "lease window overlaps an existing agreement on %s"
                           % site["site_name"])
        site["lease_start"] = lease_start
        site["lease_end"] = lease_end
        site["renewal_count"] += 1
        site["status"] = "NEGOTIATION"
        svc.touch(site)
    else:  # EXPIRED is system-only
        raise ApiError(ERR_INVALID_STATE, 409,
                       "cannot move site agreement from %s to %s"
                       % (current, to))
    return success(svc.ser_site(site), "object", 200)
