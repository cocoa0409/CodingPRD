"""Investor-update endpoints + quiet period (PRD 3.8)."""
from datetime import timedelta

from flask import Blueprint, request

from clock import clock, parse_iso
from db import db, new_id, now_iso
from derive import touch
from errors import err
from middleware import get_auth, get_auth_optional, require_role
from pagination import paginate
from response import success
from serializers import investor_update_out
from validation import require_body, require_str, opt_str

bp = Blueprint("investor_updates", __name__)

QUIET_PERIOD_HOURS = 24

READ_ROLES = {"Anonymous", "Issuer", "Investor", "ComplianceOfficer"}


@bp.post("/investor-updates")
def create_investor_update():
    uid, role = get_auth()
    require_role(role, {"Issuer"})

    body = require_body()
    offering_id = require_str(body, "offering_id")
    title = require_str(body, "title")
    update_body = require_str(body, "body")
    supersedes_update_id = opt_str(body, "supersedes_update_id", None)

    offering = db.offerings.get(offering_id)
    if offering is None:
        raise err("ERR_NOT_FOUND", "Offering not found")
    # Ownership: issuer may publish updates only on its own offerings.
    if offering["issuer_id"] != uid:
        raise err("ERR_NOT_RESOURCE_OWNER", "Caller does not own this offering")
    if supersedes_update_id is not None and supersedes_update_id not in db.investor_updates:
        raise err("ERR_NOT_FOUND", "Superseded update not found")

    ts = now_iso()
    upid = new_id()
    rec = {
        "id": upid,
        "offering_id": offering_id,
        "title": title,
        "body": update_body,
        "supersedes_update_id": supersedes_update_id,
        "published_at": None,
        "status": "DRAFT",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.investor_updates[upid] = rec
    return success(investor_update_out(rec), status=201)


@bp.get("/investor-updates/<id>")
def get_investor_update(id):
    uid, role = get_auth_optional()
    if role is not None:
        require_role(role, READ_ROLES)
    rec = db.investor_updates.get(id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Investor update not found")
    return success(investor_update_out(rec))


@bp.get("/investor-updates")
def list_investor_updates():
    uid, role = get_auth_optional()
    if role is not None:
        require_role(role, READ_ROLES)
    rows = list(db.investor_updates.values())
    for field in ("offering_id", "supersedes_update_id", "status"):
        val = request.args.get(field)
        if val is not None:
            rows = [r for r in rows if r.get(field) == val]
    page, meta = paginate(rows)
    return success([investor_update_out(r) for r in page], pagination=meta)


@bp.post("/investor-updates/<id>/publish")
def publish_investor_update(id):
    uid, role = get_auth()
    require_role(role, {"Issuer"})
    rec = db.investor_updates.get(id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Investor update not found")
    offering = db.offerings.get(rec["offering_id"])
    if offering is None:
        raise err("ERR_NOT_FOUND", "Offering not found")
    if offering["issuer_id"] != uid:
        raise err("ERR_NOT_RESOURCE_OWNER", "Caller does not own this offering")
    if rec["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Only a DRAFT update may be published")
    if offering["status"] not in ("LIVE", "FUNDED"):
        raise err("ERR_INVALID_STATE", "Updates can only be published on a LIVE or FUNDED offering")

    now = clock.now()

    # Quiet-period gap for NON-superseding updates (PRD 3.8).
    if rec["supersedes_update_id"] is None:
        last_published = None
        for u in db.investor_updates.values():
            if u["offering_id"] == rec["offering_id"] and u["status"] == "PUBLISHED" and u["published_at"]:
                pub = parse_iso(u["published_at"])
                if last_published is None or pub > last_published:
                    last_published = pub
        if last_published is not None:
            # Admissible only if now is strictly more than 24h after the last publish.
            if not (now - last_published > timedelta(hours=QUIET_PERIOD_HOURS)):
                raise err("ERR_UPDATE_QUIET_PERIOD", "Publishing too soon after the prior update (quiet period)")

    rec["status"] = "PUBLISHED"
    rec["published_at"] = clock.now_iso()

    # Supersede cascade: the referenced prior PUBLISHED update -> SUPERSEDED.
    if rec["supersedes_update_id"] is not None:
        prior = db.investor_updates.get(rec["supersedes_update_id"])
        if prior is not None and prior["status"] == "PUBLISHED":
            prior["status"] = "SUPERSEDED"
            touch(prior)

    touch(rec)
    return success(investor_update_out(rec))
