"""Expulsion hearings and evidence packets (PRD §3.5)."""
from datetime import timedelta

from flask import Blueprint, request

from db import db, stamp, touch, serialize, clock
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_OWNERSHIP_MISMATCH,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_INVALID_STATE,
    ERR_HEARING_WINDOW_PASSED,
    ERR_HEARING_ALREADY_OPEN,
    ERR_HEARING_OVERLAP,
    ERR_EVIDENCE_DEADLINE_PASSED,
    ERR_EVIDENCE_PACKET_EMPTY,
)
from middleware import endpoint
from response import success
from routes.common import get_or_404, render_list
from services.cascade import hearing_decision_cascade
from util import parse_dt

bp = Blueprint("hearings", __name__)

HEARING_STATUSES = {"SCHEDULED", "EVIDENCE_SERVED", "HELD", "EXPULSION_ORDERED", "NOT_EXPELLED"}
OPEN_HEARING_STATUSES = {"SCHEDULED", "EVIDENCE_SERVED", "HELD"}
ITEM_TYPES = {"WITNESS_STATEMENT", "DOCUMENT", "VIDEO", "OTHER"}


def _officer_or_403(ctx, hearing):
    if ctx.user_id != hearing["hearing_officer_id"]:
        raise_err(ERR_OWNERSHIP_MISMATCH, "only the assigned hearing officer may act")


@bp.post("/hearings")
@endpoint("DistrictAdmin")
def create_hearing(ctx):
    b = ctx.body
    case_id = b.get("case_id")
    if isinstance(case_id, str) and case_id not in db.cases:
        raise_err(ERR_NOT_FOUND, f"case not found: {case_id}")
    if not isinstance(case_id, str):
        raise_err(ERR_INVALID_REQUEST, "case_id is required")
    officer_id = b.get("hearing_officer_id")
    if not isinstance(officer_id, str) or not officer_id:
        raise_err(ERR_INVALID_REQUEST, "hearing_officer_id is required")
    start = parse_dt(b.get("scheduled_start"))
    end = parse_dt(b.get("scheduled_end"))
    if start is None or end is None:
        raise_err(ERR_INVALID_REQUEST, "scheduled_start and scheduled_end must be valid ISO 8601")
    if end <= start:
        raise_err(ERR_INVALID_REQUEST, "scheduled_end must be strictly after scheduled_start")

    case = db.cases[case_id]
    if case["status"] != "EXPULSION_REFERRED":
        raise_err(ERR_INVALID_STATE, "case must be EXPULSION_REFERRED to schedule a hearing")
    # Ten-day scheduling window (rung 10) before uniqueness/overlap (rung 11)
    if start > case["referred_to_expulsion_at"] + timedelta(days=10):
        raise_err(ERR_HEARING_WINDOW_PASSED, "hearing start exceeds referral + 10 days")
    if any(
        h["case_id"] == case_id and h["status"] in OPEN_HEARING_STATUSES
        for h in db.hearings.values()
    ):
        raise_err(ERR_HEARING_ALREADY_OPEN, "case already has an open hearing")
    # Officer calendar, half-open interval overlap: start < other.end AND other.start < end
    for h in db.hearings.values():
        if (
            h["hearing_officer_id"] == officer_id
            and h["status"] in OPEN_HEARING_STATUSES
            and start < h["scheduled_end"]
            and h["scheduled_start"] < end
        ):
            raise_err(ERR_HEARING_OVERLAP, "hearing officer has an overlapping open hearing")

    hearing = stamp(
        {
            "case_id": case_id,
            "hearing_officer_id": officer_id,
            "scheduled_start": start,
            "scheduled_end": end,
            "packet_served_at": None,
            "status": "SCHEDULED",
            "decided_at": None,
            "decision_rationale": None,
        }
    )
    db.hearings[hearing["id"]] = hearing
    return success(serialize(hearing), 201)


@bp.get("/hearings/<hid>")
@endpoint("DistrictAdmin", "HearingOfficer", "SchoolAdministrator")
def get_hearing(ctx, hid):
    return success(serialize(get_or_404(db.hearings, hid, "hearing")))


@bp.get("/hearings")
@endpoint("DistrictAdmin", "HearingOfficer")
def list_hearings(ctx):
    case_id = request.args.get("case_id")
    officer_id = request.args.get("hearing_officer_id")
    status = request.args.get("status")
    if status is not None and status not in HEARING_STATUSES:
        raise_err(ERR_INVALID_REQUEST, "status filter is not a declared value")
    return render_list(
        db.hearings,
        {"case_id": case_id, "hearing_officer_id": officer_id, "status": status},
    )


@bp.post("/hearings/<hid>/evidence")
@endpoint("SchoolAdministrator")
def submit_evidence(ctx, hid):
    hearing = get_or_404(db.hearings, hid, "hearing")
    b = ctx.body
    item_type = b.get("item_type")
    description = b.get("description")
    if item_type not in ITEM_TYPES:
        raise_err(ERR_INVALID_REQUEST, "item_type is not a declared value")
    if not isinstance(description, str):
        raise_err(ERR_INVALID_REQUEST, "description is required")
    if hearing["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "evidence may be added only while the hearing is SCHEDULED")

    item = stamp(
        {
            "hearing_id": hid,
            "item_type": item_type,
            "description": description,
            "submitted_by": ctx.user_id,
            "status": "SUBMITTED",
        }
    )
    db.evidence_items[item["id"]] = item
    return success(serialize(item), 201)


@bp.get("/hearings/<hid>/evidence")
@endpoint("DistrictAdmin", "HearingOfficer", "SchoolAdministrator")
def list_evidence(ctx, hid):
    hearing = get_or_404(db.hearings, hid, "hearing")
    items = {k: v for k, v in db.evidence_items.items() if v["hearing_id"] == hearing["id"]}
    return render_list(items)


@bp.post("/evidence-items/<eid>/rule")
@endpoint("HearingOfficer")
def rule_evidence(ctx, eid):
    item = get_or_404(db.evidence_items, eid, "evidence item")
    hearing = db.hearings[item["hearing_id"]]
    _officer_or_403(ctx, hearing)
    ruling = ctx.body.get("ruling")
    if ruling not in ("ADMITTED", "EXCLUDED"):
        raise_err(ERR_INVALID_REQUEST, "ruling must be ADMITTED or EXCLUDED")
    if hearing["status"] != "SCHEDULED" or item["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "evidence may be ruled on only while the hearing is SCHEDULED")
    item["status"] = ruling
    touch(item)
    return success(serialize(item))


@bp.post("/hearings/<hid>/serve-packet")
@endpoint("SchoolAdministrator")
def serve_packet(ctx, hid):
    hearing = get_or_404(db.hearings, hid, "hearing")
    if hearing["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "hearing must be SCHEDULED to serve the packet")
    # Evidence-service deadline (rung 10) precedes packet non-empty (rung 11) per PRD §2.9
    if clock() > hearing["scheduled_start"] - timedelta(days=2):
        raise_err(ERR_EVIDENCE_DEADLINE_PASSED, "packet service is later than start - 2 days")
    if not any(
        e["hearing_id"] == hid and e["status"] == "ADMITTED"
        for e in db.evidence_items.values()
    ):
        raise_err(ERR_EVIDENCE_PACKET_EMPTY, "no ADMITTED evidence items in the packet")
    hearing["packet_served_at"] = clock()
    hearing["status"] = "EVIDENCE_SERVED"
    touch(hearing)
    return success(serialize(hearing))


@bp.post("/hearings/<hid>/convene")
@endpoint("HearingOfficer")
def convene_hearing(ctx, hid):
    hearing = get_or_404(db.hearings, hid, "hearing")
    _officer_or_403(ctx, hearing)
    if hearing["status"] != "EVIDENCE_SERVED":
        raise_err(ERR_INVALID_STATE, "hearing must be EVIDENCE_SERVED to convene")
    if clock() < hearing["scheduled_end"]:
        raise_err(ERR_INVALID_STATE, "hearing cannot convene before its scheduled end")
    hearing["status"] = "HELD"
    touch(hearing)
    return success(serialize(hearing))


@bp.post("/hearings/<hid>/decision")
@endpoint("HearingOfficer")
def decide_hearing(ctx, hid):
    hearing = get_or_404(db.hearings, hid, "hearing")
    _officer_or_403(ctx, hearing)
    case = db.cases[hearing["case_id"]]
    # Segregation of duties (rung 4): officer must not be referrer or classifier
    if hearing["hearing_officer_id"] in (case["referrer_id"], case["classified_by"]):
        raise_err(ERR_SEGREGATION_OF_DUTIES, "hearing officer participated in an earlier step of this case")
    b = ctx.body
    outcome = b.get("outcome")
    rationale = b.get("rationale")
    if outcome not in ("EXPULSION_ORDERED", "NOT_EXPELLED"):
        raise_err(ERR_INVALID_REQUEST, "outcome must be EXPULSION_ORDERED or NOT_EXPELLED")
    if rationale is not None and not isinstance(rationale, str):
        raise_err(ERR_INVALID_REQUEST, "rationale must be a string")
    if hearing["status"] != "HELD":
        raise_err(ERR_INVALID_STATE, "hearing must be HELD to decide")

    hearing["status"] = outcome
    hearing["decided_at"] = clock()
    hearing["decision_rationale"] = rationale
    touch(hearing)
    hearing_decision_cascade(case, expulsion_ordered=(outcome == "EXPULSION_ORDERED"))
    return success(serialize(hearing))
