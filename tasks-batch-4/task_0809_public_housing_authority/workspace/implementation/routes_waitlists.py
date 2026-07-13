"""Waitlists, enrollment, lottery draw, and stale purge."""
from flask import Blueprint

import db
import domain
from core import (
    ApiError, authenticate, authorize, get_or_404, json_body, need_str,
    need_int_in, opt_enum, pagination, ok, ok_list,
)

bp = Blueprint("waitlists", __name__)


def _paged(records):
    limit, offset = pagination()
    ordered = db.sorted_by_created(records)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [db.serialize(r) for r in page], limit, offset, total


@bp.route("/pha/waitlists", methods=["POST"])
def create_waitlist():
    uid, role = authenticate()
    authorize(role, {"IntakeClerk"})
    body = json_body()
    site_name = need_str(body, "site_name")
    bedroom_size = need_int_in(body, "bedroom_size", 0, 6)
    status = opt_enum(body, "status", {"OPEN", "CLOSED"}, "OPEN")
    waitlist = db.create(
        db.waitlists,
        site_name=site_name,
        bedroom_size=bedroom_size,
        status=status,
        lottery_drawn=False,
    )
    return ok(db.serialize(waitlist), 201)


@bp.route("/pha/waitlists/<wid>", methods=["GET"])
def get_waitlist(wid):
    uid, role = authenticate()
    authorize(role, {"IntakeClerk", "HousingSpecialist", "PropertyManager", "Applicant"})
    waitlist = get_or_404(db.waitlists, wid, "ERR_WAITLIST_NOT_FOUND")
    return ok(db.serialize(waitlist))


@bp.route("/pha/waitlists/<wid>/entries", methods=["POST"])
def enroll(wid):
    uid, role = authenticate()
    authorize(role, {"IntakeClerk"})
    waitlist = get_or_404(db.waitlists, wid, "ERR_WAITLIST_NOT_FOUND")
    body = json_body()
    applicant_id = need_str(body, "applicant_id")
    applicant = get_or_404(db.applicants, applicant_id, "ERR_APPLICANT_NOT_FOUND")
    if waitlist["status"] != "OPEN":
        raise ApiError("ERR_WAITLIST_CLOSED", "waitlist is closed")
    entry = db.create(
        db.waitlist_entries,
        applicant_id=applicant["id"],
        waitlist_id=waitlist["id"],
        status="PENDING",
        lottery_number=None,
        total_points=domain.applicant_total_points(applicant["id"]),
        effective_rank=None,
        refusal_count=0,
        last_contact_at=db.now(),
    )
    if applicant["status"] == "APPLIED":
        db.touch(applicant, status="WAITLISTED")
    domain.recompute_ranks(waitlist)
    return ok(db.serialize(entry), 201)


@bp.route("/pha/waitlists/<wid>/entries", methods=["GET"])
def list_entries(wid):
    uid, role = authenticate()
    authorize(role, {"IntakeClerk", "HousingSpecialist", "PropertyManager", "Applicant"})
    waitlist = get_or_404(db.waitlists, wid, "ERR_WAITLIST_NOT_FOUND")
    records = [e for e in db.waitlist_entries.values() if e["waitlist_id"] == wid]
    items, limit, offset, total = _paged(records)
    return ok_list(items, limit, offset, total)


@bp.route("/pha/waitlists/<wid>/lottery-draw", methods=["POST"])
def lottery_draw(wid):
    uid, role = authenticate()
    authorize(role, {"IntakeClerk"})
    waitlist = get_or_404(db.waitlists, wid, "ERR_WAITLIST_NOT_FOUND")
    if waitlist["status"] != "OPEN":
        raise ApiError("ERR_WAITLIST_CLOSED", "waitlist is closed")
    now = db.now()
    pending = [
        e for e in db.waitlist_entries.values()
        if e["waitlist_id"] == wid and e["status"] == "PENDING"
    ]
    pending.sort(key=lambda e: (db.applicants[e["applicant_id"]]["application_date"], e["_seq"]))
    for i, e in enumerate(pending):
        db.touch(
            e,
            status="ACTIVE",
            lottery_number=i + 1,
            total_points=domain.applicant_total_points(e["applicant_id"]),
            last_contact_at=now,
        )
    db.touch(waitlist, lottery_drawn=True)
    domain.recompute_ranks(waitlist)
    return ok(db.serialize(waitlist))


@bp.route("/pha/waitlists/<wid>/purge", methods=["POST"])
def purge(wid):
    uid, role = authenticate()
    authorize(role, {"IntakeClerk"})
    waitlist = get_or_404(db.waitlists, wid, "ERR_WAITLIST_NOT_FOUND")
    now = db.now()
    affected = set()
    for e in db.waitlist_entries.values():
        if e["waitlist_id"] != wid or e["status"] != "ACTIVE":
            continue
        if (now - e["last_contact_at"]).days >= domain.PURGE_STALE_DAYS:
            db.touch(e, status="PURGED")
            affected.add(e["applicant_id"])
    domain.recompute_ranks(waitlist)
    for aid in affected:
        domain.maybe_withdraw_applicant(aid)
    return ok(db.serialize(waitlist))
