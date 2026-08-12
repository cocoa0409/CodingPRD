"""Routes: logical clock, seasons, hosts, sites."""
from flask import Blueprint

import db
import services as svc
from errors import (raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_NOT_RESOURCE_OWNER, ERR_OUTSTANDING_BALANCE, ERR_SEASON_NOT_CLOSABLE,
                    ERR_SITE_HAS_OPEN_INCIDENTS)
from middleware import auth, body, ALL_AUTHENTICATED
from response import success, paginate
from util import new_base, touch, pub, req_str, opt_int, req_int, req_bool, req_dt, iso

bp = Blueprint("core", __name__)


def _get(coll, rid):
    ent = coll.get(rid)
    if ent is None:
        raise_err(ERR_NOT_FOUND, "Resource %s not found" % rid)
    return ent


def pub_host(host):
    out = pub(host)
    out["balance_due_cents"] = svc.host_balance_cents(host["id"])
    return out


def pub_site(site):
    out = pub(site)
    out["effective_capacity_hives"] = svc.effective_capacity(site)
    return out


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.post("/api/_clock/set_current_utc")
def set_clock():
    auth(("PlatformOps",))
    b = body()
    to = req_dt(b, "to_iso8601")
    db.set_now(to)
    return success({}, 200)


# ---------------------------------------------------------------------------
# Seasons
# ---------------------------------------------------------------------------

@bp.post("/api/seasons")
def create_season():
    auth(("PlatformOps",))
    b = body()
    name = req_str(b, "name")
    frost = req_dt(b, "frost_date")
    if db.seasons:
        raise_err(ERR_SEASON_NOT_CLOSABLE, "A season already exists")
    season = new_base()
    season.update({"name": name, "frost_date": frost, "status": "OPEN",
                   "opened_at": db.now(), "closed_at": None})
    db.seasons[season["id"]] = season
    return success(pub(season), 201)


@bp.get("/api/seasons/<sid>")
def get_season(sid):
    auth(ALL_AUTHENTICATED)
    return success(pub(_get(db.seasons, sid)), 200)


@bp.post("/api/seasons/<sid>/rollover")
def rollover(sid):
    auth(("PlatformOps",))
    season = _get(db.seasons, sid)
    b = body()
    name = req_str(b, "name")
    frost = req_dt(b, "frost_date")
    if season["status"] != "OPEN":
        raise_err(ERR_SEASON_NOT_CLOSABLE, "Season is not OPEN")
    successor = svc.rollover_season(season, name, frost)
    return success(pub(successor), 201)


# ---------------------------------------------------------------------------
# Hosts
# ---------------------------------------------------------------------------

@bp.post("/api/hosts")
def create_host():
    auth(("Anonymous",))
    b = body()
    full_name = req_str(b, "full_name")
    email = req_str(b, "email")
    for h in db.hosts.values():
        if h["email"] == email:
            raise_err(ERR_INVALID_REQUEST, "email must be unique across hosts")
    host = new_base()
    host.update({"full_name": full_name, "email": email, "status": "APPLICANT",
                 "waiver_signed_at": None, "waiver_version": None,
                 "reputation_score": 100, "honey_credit_kg": 0, "balance_due_cents": 0})
    db.hosts[host["id"]] = host
    return success(pub_host(host), 201)


@bp.get("/api/hosts/<hid>")
def get_host(hid):
    auth(ALL_AUTHENTICATED)
    return success(pub_host(_get(db.hosts, hid)), 200)


@bp.post("/api/hosts/<hid>/sign-waiver")
def sign_waiver(hid):
    uid, _ = auth(("Host",))
    if hid != uid:
        raise_err(ERR_NOT_RESOURCE_OWNER, "Host may only sign their own waiver")
    host = _get(db.hosts, hid)
    b = body()
    waiver_version = req_str(b, "waiver_version")
    host["waiver_signed_at"] = db.now()
    host["waiver_version"] = waiver_version
    if host["status"] == "APPLICANT":
        host["status"] = "ACTIVE"
    elif svc.host_balance_cents(host["id"]) == 0:
        # Renewal clears SUSPENDED/LIMITED only when no unpaid invoices remain.
        host["status"] = "ACTIVE"
    touch(host)
    return success(pub_host(host), 200)


@bp.post("/api/hosts/<hid>/suspend")
def suspend_host(hid):
    auth(("PlatformOps",))
    host = _get(db.hosts, hid)
    if host["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Only an ACTIVE host can be suspended")
    host["status"] = "SUSPENDED"
    touch(host)
    return success(pub_host(host), 200)


@bp.post("/api/hosts/<hid>/reactivate")
def reactivate_host(hid):
    auth(("PlatformOps",))
    host = _get(db.hosts, hid)
    if host["status"] != "SUSPENDED":
        raise_err(ERR_INVALID_STATE, "Only a SUSPENDED host can be reactivated")
    if svc.host_balance_cents(host["id"]) != 0:
        raise_err(ERR_OUTSTANDING_BALANCE, "Host has unpaid invoices")
    host["status"] = "ACTIVE"
    touch(host)
    return success(pub_host(host), 200)


# ---------------------------------------------------------------------------
# Sites
# ---------------------------------------------------------------------------

@bp.post("/api/sites")
def create_site():
    uid, _ = auth(("Host",))
    b = body()
    host_id = b.get("host_id")
    if not isinstance(host_id, str) or not host_id:
        raise_err(ERR_INVALID_REQUEST, "Field 'host_id' is required")
    if host_id != uid:
        raise_err(ERR_NOT_RESOURCE_OWNER, "Host may only create sites for themselves")
    host = db.hosts.get(host_id)
    if host is None:
        raise_err(ERR_NOT_FOUND, "Host %s not found" % host_id)
    address = req_str(b, "address")
    water = req_bool(b, "water_source")
    setback = req_int(b, "setback_feet", minv=0)
    base_cap = opt_int(b, "base_capacity_hives", default=2, minv=1)
    site = new_base()
    site.update({"host_id": host_id, "address": address, "base_capacity_hives": base_cap,
                 "effective_capacity_hives": base_cap, "status": "CLEAR",
                 "water_source": water, "setback_feet": setback})
    site["effective_capacity_hives"] = svc.effective_capacity(site)
    db.sites[site["id"]] = site
    return success(pub_site(site), 201)


@bp.get("/api/sites/<sid>")
def get_site(sid):
    auth(ALL_AUTHENTICATED)
    return success(pub_site(_get(db.sites, sid)), 200)


@bp.get("/api/sites")
def list_sites():
    auth(ALL_AUTHENTICATED)
    items = svc.sorted_all(db.sites)
    host_id = __import__("flask").request.args.get("host_id")
    if host_id is not None:
        items = [s for s in items if s["host_id"] == host_id]
    page, meta = paginate(items)
    return success([pub_site(s) for s in page], 200, meta)


@bp.post("/api/sites/<sid>/unblock")
def unblock_site(sid):
    auth(("ApiaryManager",))
    site = _get(db.sites, sid)
    if site["status"] != "BLOCKED":
        raise_err(ERR_INVALID_STATE, "Site is not BLOCKED")
    for inc in db.incidents.values():
        if inc["site_id"] == site["id"] and inc["status"] == "REPORTED":
            raise_err(ERR_SITE_HAS_OPEN_INCIDENTS, "Site still has a REPORTED incident")
    site["status"] = "CLEAR"
    touch(site)
    return success(pub_site(site), 200)
