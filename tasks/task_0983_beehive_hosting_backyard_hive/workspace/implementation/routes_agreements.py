"""Routes: agreements and hives."""
from flask import Blueprint, request

import db
import services as svc
from errors import (raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_NOT_RESOURCE_OWNER, ERR_STALE_VERSION, ERR_AGREEMENT_NOT_ACTIVE,
                    ERR_AGREEMENT_WINDOW_OVERLAP, ERR_AGREEMENT_HAS_LIVE_HIVES,
                    ERR_OUTSTANDING_BALANCE, ERR_HOST_NOT_ACTIVE, ERR_HOST_REPUTATION_TOO_LOW,
                    ERR_WAIVER_CURRENT_REQUIRED, ERR_SITE_BLOCKED, ERR_SITE_CAPACITY_EXCEEDED,
                    ERR_HIVE_NOT_OPERABLE, ERR_HIVE_QUARANTINED)
from middleware import auth, body, ALL_AUTHENTICATED
from response import success, paginate
from util import new_base, touch, pub, req_int, req_dt
from routes_core import _get, pub_site

bp = Blueprint("agreements", __name__)

LIVE_AGREEMENT_STATES = ("PENDING_SIGNATURE", "ACTIVE", "AMENDMENT_PENDING")


def pub_agreement(ag):
    svc.lazy_expire_agreement(ag)
    return pub(ag)


def pub_hive(hive):
    svc.refresh_hive_postures(hive)
    return pub(hive)


def _terms_overlap(a_start, a_end, b_start, b_end):
    # Closed-interval overlap.
    return a_start <= b_end and b_start <= a_end


def _check_site_overlap(site_id, term_start, term_end, exclude_id=None):
    for other in db.agreements.values():
        if other["site_id"] != site_id or other["id"] == exclude_id:
            continue
        svc.lazy_expire_agreement(other)
        if other["status"] in LIVE_AGREEMENT_STATES and _terms_overlap(
                term_start, term_end, other["term_start_date"], other["term_end_date"]):
            raise_err(ERR_AGREEMENT_WINDOW_OVERLAP,
                      "Term overlaps another live agreement on the same site")


# ---------------------------------------------------------------------------
# Agreements
# ---------------------------------------------------------------------------

@bp.post("/api/agreements")
def create_agreement():
    auth(("PlatformOps",))
    b = body()
    host_id = b.get("host_id")
    site_id = b.get("site_id")
    if not isinstance(host_id, str) or not host_id:
        raise_err(ERR_INVALID_REQUEST, "Field 'host_id' is required")
    if not isinstance(site_id, str) or not site_id:
        raise_err(ERR_INVALID_REQUEST, "Field 'site_id' is required")
    host = db.hosts.get(host_id)
    if host is None:
        raise_err(ERR_NOT_FOUND, "Host %s not found" % host_id)
    site = db.sites.get(site_id)
    if site is None:
        raise_err(ERR_NOT_FOUND, "Site %s not found" % site_id)
    term_start = req_dt(b, "term_start_date")
    term_end = req_dt(b, "term_end_date")
    if term_end <= term_start:
        raise_err(ERR_INVALID_REQUEST, "term_end_date must be after term_start_date")
    bps = req_int(b, "host_share_base_bps", minv=0, maxv=6000)
    # Business constraint (step 8): closed-interval overlap.
    _check_site_overlap(site_id, term_start, term_end)
    # Fiscal standing (step 11).
    if host["status"] != "ACTIVE":
        raise_err(ERR_HOST_NOT_ACTIVE, "Host is not ACTIVE")
    if host["reputation_score"] < 50:
        raise_err(ERR_HOST_REPUTATION_TOO_LOW, "Host reputation_score below 50")
    ag = new_base()
    ag.update({"host_id": host_id, "site_id": site_id,
               "term_start_date": term_start, "term_end_date": term_end,
               "host_share_base_bps": bps, "pending_host_share_base_bps": None,
               "liability_clause_version": None, "status": "PENDING_SIGNATURE",
               "signed_at": None})
    db.agreements[ag["id"]] = ag
    return success(pub(ag), 201)


@bp.get("/api/agreements/<aid>")
def get_agreement(aid):
    auth(ALL_AUTHENTICATED)
    return success(pub_agreement(_get(db.agreements, aid)), 200)


@bp.get("/api/agreements")
def list_agreements():
    auth(ALL_AUTHENTICATED)
    items = svc.sorted_all(db.agreements)
    host_id = request.args.get("host_id")
    site_id = request.args.get("site_id")
    if host_id is not None:
        items = [a for a in items if a["host_id"] == host_id]
    if site_id is not None:
        items = [a for a in items if a["site_id"] == site_id]
    page, meta = paginate(items)
    return success([pub_agreement(a) for a in page], 200, meta)


@bp.post("/api/agreements/<aid>/sign")
def sign_agreement(aid):
    uid, _ = auth(("Host",))
    ag = _get(db.agreements, aid)
    svc.lazy_expire_agreement(ag)
    if ag["host_id"] != uid:
        raise_err(ERR_NOT_RESOURCE_OWNER, "Host does not own this agreement")
    if ag["status"] != "PENDING_SIGNATURE":
        raise_err(ERR_INVALID_STATE, "Agreement is not PENDING_SIGNATURE")
    host = db.hosts.get(ag["host_id"])
    site = db.sites.get(ag["site_id"])
    # Safety (step 7): waiver currency.
    if host is None or not svc.waiver_current(host):
        raise_err(ERR_WAIVER_CURRENT_REQUIRED, "Host waiver is missing or older than 365 days")
    # Business constraints (step 8).
    if site is not None and site["status"] != "CLEAR":
        raise_err(ERR_SITE_BLOCKED, "Site is BLOCKED")
    _check_site_overlap(ag["site_id"], ag["term_start_date"], ag["term_end_date"], exclude_id=ag["id"])
    # Fiscal (step 11).
    if host["status"] != "ACTIVE":
        raise_err(ERR_HOST_NOT_ACTIVE, "Host is not ACTIVE")
    ag["liability_clause_version"] = host["waiver_version"]
    ag["signed_at"] = db.now()
    ag["status"] = "ACTIVE"
    touch(ag)
    return success(pub(ag), 200)


@bp.post("/api/agreements/<aid>/propose-amendment")
def propose_amendment(aid):
    auth(("PlatformOps",))
    ag = _get(db.agreements, aid)
    svc.lazy_expire_agreement(ag)
    b = body()
    proposed = req_int(b, "proposed_host_share_base_bps", minv=0, maxv=6000)
    expected = b.get("expected_agreement_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_err(ERR_INVALID_REQUEST, "Field 'expected_agreement_version' is required")
    if ag["status"] not in ("ACTIVE", "AMENDMENT_PENDING"):
        raise_err(ERR_INVALID_STATE, "Agreement is not ACTIVE or AMENDMENT_PENDING")
    if expected != ag["version"]:
        raise_err(ERR_STALE_VERSION, "expected_agreement_version does not match current version")
    ag["status"] = "AMENDMENT_PENDING"
    ag["pending_host_share_base_bps"] = proposed
    touch(ag)
    return success(pub(ag), 200)


@bp.post("/api/agreements/<aid>/accept-amendment")
def accept_amendment(aid):
    uid, _ = auth(("Host",))
    ag = _get(db.agreements, aid)
    svc.lazy_expire_agreement(ag)
    if ag["host_id"] != uid:
        raise_err(ERR_NOT_RESOURCE_OWNER, "Host does not own this agreement")
    if ag["status"] != "AMENDMENT_PENDING":
        raise_err(ERR_INVALID_STATE, "Agreement is not AMENDMENT_PENDING")
    ag["host_share_base_bps"] = ag["pending_host_share_base_bps"]
    ag["pending_host_share_base_bps"] = None
    ag["status"] = "ACTIVE"
    touch(ag)
    return success(pub(ag), 200)


@bp.post("/api/agreements/<aid>/reject-amendment")
def reject_amendment(aid):
    uid, _ = auth(("Host",))
    ag = _get(db.agreements, aid)
    svc.lazy_expire_agreement(ag)
    if ag["host_id"] != uid:
        raise_err(ERR_NOT_RESOURCE_OWNER, "Host does not own this agreement")
    if ag["status"] != "AMENDMENT_PENDING":
        raise_err(ERR_INVALID_STATE, "Agreement is not AMENDMENT_PENDING")
    ag["pending_host_share_base_bps"] = None
    ag["status"] = "ACTIVE"
    touch(ag)
    return success(pub(ag), 200)


@bp.post("/api/agreements/<aid>/terminate")
def terminate_agreement(aid):
    uid, role = auth(("Host", "PlatformOps"))
    ag = _get(db.agreements, aid)
    svc.lazy_expire_agreement(ag)
    if role == "Host" and ag["host_id"] != uid:
        raise_err(ERR_NOT_RESOURCE_OWNER, "Host does not own this agreement")
    if ag["status"] not in ("ACTIVE", "AMENDMENT_PENDING"):
        raise_err(ERR_INVALID_STATE, "Agreement is not ACTIVE or AMENDMENT_PENDING")
    # Referential (step 9): no live hives, no in-flight removal jobs.
    hive_ids = {h["id"] for h in db.hives.values() if h["agreement_id"] == ag["id"]}
    for h in db.hives.values():
        if h["agreement_id"] == ag["id"] and h["lifecycle_status"] in ("ACTIVE", "QUARANTINED"):
            raise_err(ERR_AGREEMENT_HAS_LIVE_HIVES, "Agreement still has live hives")
    for job in db.removal_jobs.values():
        if job["hive_id"] in hive_ids and job["status"] in ("REQUESTED", "APPROVED", "SCHEDULED"):
            raise_err(ERR_AGREEMENT_HAS_LIVE_HIVES, "Agreement has in-flight removal jobs")
    # Fiscal (step 11).
    if svc.host_balance_cents(ag["host_id"]) != 0:
        raise_err(ERR_OUTSTANDING_BALANCE, "Host has unpaid invoices")
    ag["pending_host_share_base_bps"] = None
    ag["status"] = "TERMINATED"
    touch(ag)
    return success(pub(ag), 200)


# ---------------------------------------------------------------------------
# Hives
# ---------------------------------------------------------------------------

def _capacity_check(site):
    if svc.site_occupancy(site["id"]) >= svc.effective_capacity(site):
        raise_err(ERR_SITE_CAPACITY_EXCEEDED, "Site occupancy has reached effective capacity")


@bp.post("/api/hives")
def install_hive():
    auth(("ApiaryManager",))
    b = body()
    site_id = b.get("site_id")
    agreement_id = b.get("agreement_id")
    if not isinstance(site_id, str) or not site_id:
        raise_err(ERR_INVALID_REQUEST, "Field 'site_id' is required")
    if not isinstance(agreement_id, str) or not agreement_id:
        raise_err(ERR_INVALID_REQUEST, "Field 'agreement_id' is required")
    site = db.sites.get(site_id)
    if site is None:
        raise_err(ERR_NOT_FOUND, "Site %s not found" % site_id)
    ag = db.agreements.get(agreement_id)
    if ag is None:
        raise_err(ERR_NOT_FOUND, "Agreement %s not found" % agreement_id)
    svc.lazy_expire_agreement(ag)
    # State (step 6): agreement must be ACTIVE and cover this site.
    if ag["status"] != "ACTIVE" or ag["site_id"] != site_id:
        raise_err(ERR_AGREEMENT_NOT_ACTIVE, "Agreement is not ACTIVE for this site")
    host = db.hosts.get(ag["host_id"])
    # Safety (step 7): waiver currency.
    if host is None or not svc.waiver_current(host):
        raise_err(ERR_WAIVER_CURRENT_REQUIRED, "Host waiver is missing or older than 365 days")
    # Business constraints (step 8).
    if site["status"] != "CLEAR":
        raise_err(ERR_SITE_BLOCKED, "Site is BLOCKED")
    _capacity_check(site)
    # Temporal (step 10): current date within the agreement term.
    now = db.now()
    if not (ag["term_start_date"] <= now <= ag["term_end_date"]):
        raise_err(ERR_AGREEMENT_NOT_ACTIVE, "Current date is outside the agreement term")
    # Fiscal (step 11).
    if host["status"] != "ACTIVE":
        raise_err(ERR_HOST_NOT_ACTIVE, "Host is not ACTIVE")
    hive = new_base()
    hive.update({"site_id": site_id, "agreement_id": agreement_id,
                 "parent_hive_id": None, "source_swarm_event_id": None,
                 "installed_at": now, "lifecycle_status": "ACTIVE",
                 "posture": "STABLE", "provisional_posture": "STABLE",
                 "last_verified_inspection_at": None})
    db.hives[hive["id"]] = hive
    return success(pub_hive(hive), 201)


@bp.get("/api/hives/<hid>")
def get_hive(hid):
    auth(ALL_AUTHENTICATED)
    return success(pub_hive(_get(db.hives, hid)), 200)


@bp.get("/api/hives")
def list_hives():
    auth(ALL_AUTHENTICATED)
    items = svc.sorted_all(db.hives)
    for f in ("site_id", "agreement_id", "parent_hive_id", "source_swarm_event_id"):
        v = request.args.get(f)
        if v is not None:
            items = [h for h in items if h.get(f) == v]
    page, meta = paginate(items)
    return success([pub_hive(h) for h in page], 200, meta)


@bp.post("/api/hives/<hid>/split")
def split_hive(hid):
    auth(("ApiaryManager",))
    hive = _get(db.hives, hid)
    if hive["lifecycle_status"] in ("DEAD", "REMOVED"):
        raise_err(ERR_HIVE_NOT_OPERABLE, "Hive is DEAD or REMOVED")
    if hive["lifecycle_status"] == "QUARANTINED":
        raise_err(ERR_HIVE_QUARANTINED, "Quarantined hive may not be split")
    site = db.sites.get(hive["site_id"])
    if site is not None and site["status"] != "CLEAR":
        raise_err(ERR_SITE_BLOCKED, "Site is BLOCKED")
    if site is not None:
        _capacity_check(site)
    child = new_base()
    child.update({"site_id": hive["site_id"], "agreement_id": hive["agreement_id"],
                  "parent_hive_id": hive["id"], "source_swarm_event_id": None,
                  "installed_at": db.now(), "lifecycle_status": "ACTIVE",
                  "posture": "STABLE", "provisional_posture": "STABLE",
                  "last_verified_inspection_at": None})
    db.hives[child["id"]] = child
    return success(pub_hive(child), 201)


@bp.post("/api/hives/<hid>/mark-dead")
def mark_dead(hid):
    auth(("ApiaryManager",))
    hive = _get(db.hives, hid)
    if hive["lifecycle_status"] not in ("ACTIVE", "QUARANTINED"):
        raise_err(ERR_INVALID_STATE, "Hive is not ACTIVE or QUARANTINED")
    hive["lifecycle_status"] = "DEAD"
    touch(hive)
    return success(pub_hive(hive), 200)
