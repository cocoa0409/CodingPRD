"""AttestationCycle endpoints: schedule, list, get, advance (3-step machine)."""

from flask import Blueprint

import db
import errors
import helpers
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services.cascades import recompute_cycle_counters

bp = Blueprint("cycles", __name__)

CYCLE_STATUSES = {"SCHEDULED", "OPEN", "OUTREACH", "CLOSED"}


@bp.route("/network/attestation-cycles", methods=["POST"])
@require_roles("NetworkManager")
def create_cycle(user_id, role):
    body = helpers.get_body()
    cycle_label = helpers.req_str(body, "cycle_label")
    open_date = helpers.req_str(body, "open_date")
    due_date = helpers.req_str(body, "due_date")
    outreach_close_date = helpers.req_str(body, "outreach_close_date")
    od = helpers.parse_date(open_date, "open_date")
    dd = helpers.parse_date(due_date, "due_date")
    ocd = helpers.parse_date(outreach_close_date, "outreach_close_date")
    if not (od < dd < ocd):
        raise errors.err_invalid("Cycle dates must satisfy open_date < due_date < outreach_close_date")
    # half-open window [open_date, outreach_close_date) non-overlap across ALL cycles
    for c in db.cycles.values():
        c_od = helpers.parse_date(c["open_date"], "open_date")
        c_ocd = helpers.parse_date(c["outreach_close_date"], "outreach_close_date")
        if od < c_ocd and c_od < ocd:
            raise errors.err_cycle_window_overlap()
    rec = {
        "cycle_label": cycle_label, "open_date": open_date, "due_date": due_date,
        "outreach_close_date": outreach_close_date, "status": "SCHEDULED",
        "total_records": 0, "pending_count": 0, "responded_count": 0,
        "non_responsive_count": 0,
    }
    helpers.stamp_new(rec)
    db.cycles[rec["id"]] = rec
    return success_object(helpers.ser_cycle(rec), 201)


@bp.route("/network/attestation-cycles", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_cycles(user_id, role):
    limit, offset = helpers.get_pagination()
    status = helpers.query_enum("status", CYCLE_STATUSES)
    items = list(db.cycles.values())
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, total = helpers.paginate(items, limit, offset)
    return success_list([helpers.ser_cycle(c) for c in page], limit, offset, total)


@bp.route("/network/attestation-cycles/<cid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_cycle(user_id, role, cid):
    rec = db.cycles.get(cid)
    if rec is None:
        raise errors.err_cycle_not_found()
    return success_object(helpers.ser_cycle(rec))


@bp.route("/network/attestation-cycles/<cid>/advance", methods=["POST"])
@require_roles("NetworkManager")
def advance_cycle(user_id, role, cid):
    rec = db.cycles.get(cid)
    if rec is None:
        raise errors.err_cycle_not_found()
    cdate = helpers.clock_date()
    if rec["status"] == "SCHEDULED":
        # temporal check precedes the singleton constraint check (PRD §3.4)
        od = helpers.parse_date(rec["open_date"], "open_date")
        if cdate < od:
            raise errors.err_cycle_not_advanceable()
        for c in db.cycles.values():
            if c["id"] != rec["id"] and c["status"] in ("OPEN", "OUTREACH"):
                raise errors.err_cycle_already_active()
        rec["status"] = "OPEN"
        helpers.touch(rec)
        # bulk-create PENDING records for every LISTED listing at this instant
        for lst in db.listings.values():
            if lst["status"] != "LISTED":
                continue
            record = {
                "cycle_id": rec["id"], "listing_id": lst["id"],
                "status": "PENDING", "outreach_attempts": 0, "responded_at": None,
            }
            helpers.stamp_new(record)
            db.records[record["id"]] = record
        recompute_cycle_counters(rec)
    elif rec["status"] == "OPEN":
        dd = helpers.parse_date(rec["due_date"], "due_date")
        if cdate < dd:
            raise errors.err_cycle_not_advanceable()
        rec["status"] = "OUTREACH"
        helpers.touch(rec)
        for r in db.records.values():
            if r["cycle_id"] == rec["id"] and r["status"] == "PENDING":
                r["outreach_attempts"] += 1
                helpers.touch(r)
        recompute_cycle_counters(rec)
    elif rec["status"] == "OUTREACH":
        ocd = helpers.parse_date(rec["outreach_close_date"], "outreach_close_date")
        if cdate < ocd:
            raise errors.err_cycle_not_advanceable()
        rec["status"] = "CLOSED"
        helpers.touch(rec)
        # link 1: PENDING -> NON_RESPONSIVE
        swept = [r for r in db.records.values()
                 if r["cycle_id"] == rec["id"] and r["status"] == "PENDING"]
        for r in swept:
            r["status"] = "NON_RESPONSIVE"
            helpers.touch(r)
        # link 2: each such record's listing, if still LISTED, -> SUPPRESSED
        for r in swept:
            lst = db.listings.get(r["listing_id"])
            if lst is not None and lst["status"] == "LISTED":
                lst["status"] = "SUPPRESSED"
                lst["suppress_reason"] = "ATTESTATION_FAILURE"
                lst["suppressed_at"] = helpers.now_iso()
                helpers.touch(lst)
        # link 3
        recompute_cycle_counters(rec)
    else:
        raise errors.err_cycle_invalid_state()
    return success_object(helpers.ser_cycle(rec))
