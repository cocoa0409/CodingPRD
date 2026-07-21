"""Arbitration endpoints (§3.4)."""
from flask import Blueprint, request

import errors
import serialize
import validate as v
from auth import authorize
from envelope import success
from helpers import lookup_or_404, respond_list
from store import db, stamp, touch, clock_now, HEARING_BUFFER_DAYS
from timeutil import parse_iso, days

bp = Blueprint("arbitrations", __name__)

LIVE = {"FILED", "AWAITING_RESPONSE", "RESPONSE_FILED"}


@bp.route("/subro/claims/<claim_id>/arbitrations", methods=["POST"])
def file_arbitration(claim_id):
    authorize(request, {"RecoverySpecialist"})
    claim = lookup_or_404(db.claims, claim_id)
    body = v.get_body(request)
    forum = v.req_str(body, "forum")

    # (7) state
    if claim["status"] != "DEMAND_ISSUED":
        raise errors.invalid_state()
    # (8) referential: eligibility, then a disputed demand
    adverse = db.adverse_parties[claim["adverse_party_id"]]
    if not adverse["is_arbitration_eligible"]:
        raise errors.adverse_not_arbitrable()
    disputed = [d for d in db.demands.values()
                if d["claim_id"] == claim_id and d["status"] == "DISPUTED"]
    if not disputed:
        raise errors.demand_not_disputed()
    # (9) arbitration window (against the most recently disputed demand), then statute
    now = clock_now()
    latest = max(disputed, key=lambda d: d["disputed_at"])
    if now >= latest["arbitration_window_due_at"]:
        raise errors.arbitration_window_closed()
    if now >= parse_iso(claim["statute_deadline"]):
        raise errors.statute_expired()

    arb = stamp({
        "claim_id": claim_id,
        "forum": forum,
        "filed_at": now,
        "hearing_start": None,
        "hearing_end": None,
        "rounds": [],
        "round_count": 0,
        "award_amount_cents": None,
        "status": "FILED",
    })
    db.arbitrations[arb["id"]] = arb
    claim["status"] = "ARBITRATION"
    touch(claim)
    return success(serialize.arbitration(arb), "object", 201)


@bp.route("/subro/arbitrations/<arbitration_id>", methods=["GET"])
def get_arbitration(arbitration_id):
    authorize(request, None)
    arb = lookup_or_404(db.arbitrations, arbitration_id)
    return success(serialize.arbitration(arb), "object", 200)


@bp.route("/subro/arbitrations", methods=["GET"])
def list_arbitrations():
    authorize(request, None)
    claim_id = request.args.get("claim_id")
    status = request.args.get("status")
    items = []
    for a in db.arbitrations.values():
        if claim_id is not None and a["claim_id"] != claim_id:
            continue
        if status is not None and a["status"] != status:
            continue
        items.append(a)
    return respond_list(request, items, serialize.arbitration)


def _windows_conflict(new_start, new_end, other_start, other_end):
    buffer = days(HEARING_BUFFER_DAYS)
    # Exactly-buffer-apart is accepted; only a strictly smaller gap conflicts.
    if new_end + buffer <= other_start:
        return False
    if other_end + buffer <= new_start:
        return False
    return True


@bp.route("/subro/arbitrations/<arbitration_id>/schedule-hearing", methods=["POST"])
def schedule_hearing(arbitration_id):
    authorize(request, {"RecoverySpecialist"})
    arb = lookup_or_404(db.arbitrations, arbitration_id)
    body = v.get_body(request)
    hearing_start = v.req_datetime(body, "hearing_start")
    hearing_end = v.req_datetime(body, "hearing_end")
    hs = parse_iso(hearing_start)
    he = parse_iso(hearing_end)
    # (5) well-formedness: start strictly before end
    if hs >= he:
        raise errors.invalid_request("hearing_start must be strictly before hearing_end")
    # (7) state
    if arb["status"] != "FILED":
        raise errors.invalid_state()
    # (9) buffer overlap with other hearings on the same adverse party
    claim = db.claims[arb["claim_id"]]
    adverse_party_id = claim["adverse_party_id"]
    for other in db.arbitrations.values():
        if other["id"] == arb["id"]:
            continue
        if other["hearing_start"] is None or other["status"] == "WITHDRAWN":
            continue
        oclaim = db.claims[other["claim_id"]]
        if oclaim["adverse_party_id"] != adverse_party_id:
            continue
        if _windows_conflict(hs, he, parse_iso(other["hearing_start"]), parse_iso(other["hearing_end"])):
            raise errors.hearing_window_conflict()

    arb["hearing_start"] = hearing_start
    arb["hearing_end"] = hearing_end
    arb["status"] = "AWAITING_RESPONSE"
    touch(arb)
    return success(serialize.arbitration(arb), "object", 200)


@bp.route("/subro/arbitrations/<arbitration_id>/rounds", methods=["POST"])
def file_round(arbitration_id):
    uid, role = authorize(request, {"RecoverySpecialist"})
    arb = lookup_or_404(db.arbitrations, arbitration_id)
    body = v.get_body(request)
    note = v.req_str(body, "note", allow_empty=True)
    # (7) state
    if arb["status"] not in {"AWAITING_RESPONSE", "RESPONSE_FILED"}:
        raise errors.invalid_state()

    round_no = arb["round_count"] + 1
    arb["rounds"].append({
        "round_no": round_no,
        "filer": uid,
        "filed_at": clock_now(),
        "note": note,
    })
    arb["round_count"] = round_no
    arb["status"] = "RESPONSE_FILED" if arb["status"] == "AWAITING_RESPONSE" else "AWAITING_RESPONSE"
    touch(arb)
    return success(serialize.arbitration(arb), "object", 200)


@bp.route("/subro/arbitrations/<arbitration_id>/decide", methods=["POST"])
def decide_arbitration(arbitration_id):
    authorize(request, {"RecoveryManager"})
    arb = lookup_or_404(db.arbitrations, arbitration_id)
    body = v.get_body(request)
    award = v.req_int(body, "award_amount_cents", min=0)
    # (7) state
    if arb["status"] not in {"AWAITING_RESPONSE", "RESPONSE_FILED"}:
        raise errors.invalid_state()
    arb["award_amount_cents"] = award
    arb["status"] = "DECIDED"
    touch(arb)
    return success(serialize.arbitration(arb), "object", 200)
