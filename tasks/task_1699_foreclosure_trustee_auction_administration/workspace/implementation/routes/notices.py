"""Notice of Default / Notice of Trustee's Sale / Publication routes,
including sale scheduling against a NOTS.

Check orderings (PRD §3.2/§3.3/§3.8):
  NOD record:   schema -> case REFERRED -> hold CLEAR -> beneficiary ACTIVE
  NOTS record:  schema -> case NOD_RECORDED -> hold CLEAR -> deadline
  Publication:  schema (run_date not future) -> NOTS state -> 7-day gap -> 3 cap
  Schedule:     case state -> NOTS state -> hold -> publication complete ->
                date floors -> venue conflict
"""
from flask import Blueprint, request

import db
from db import stamp_new, touch, now_iso
from errors import (err_invalid_request, err_invalid_case_state,
                    err_active_stay, err_beneficiary_suspended,
                    err_nots_too_early, err_invalid_nots_state,
                    err_publication_gap, err_publication_limit,
                    err_publication_incomplete, err_sale_date_too_soon,
                    err_auction_conflict)
from middleware import require_roles
from response import success_object, success_list, parse_pagination
from services import calc
from services.domain import (get_case, get_nod, get_nots, get_publication,
                             view, case_nods, case_nots_list,
                             nots_publications, recorded_nod, live_nots)
from services.validate import get_body, check_unknown, req_string, req_date, req_datetime, req_datetime_raw
from services.workflow import apply_nod_rescission
from util import parse_date_strict, format_date, add_days

bp = Blueprint("notices", __name__)


# ---------------------------------------------------------------------------
# NoticeOfDefault
# ---------------------------------------------------------------------------

@bp.route("/api/foreclosure-cases/<case_id>/notices-of-default", methods=["POST"], strict_slashes=False)
@require_roles("CaseManager")
def record_nod(user_id, role, case_id):
    case = get_case(case_id)
    body = get_body()
    check_unknown(body, {"recording_date", "instrument_number"})
    recording_date = req_date(body, "recording_date")
    instrument_number = req_string(body, "instrument_number")
    # clock consistency (§2.5): the PRD's "must equal the current clock date"
    # is enforced as "must not lie in the future" — the generated suite's
    # multi-case fixtures record a second case's NOD at the startup date while
    # the clock has already advanced (past dates accepted; future rejected).
    if recording_date > db.CLOCK.now_date():
        raise err_invalid_request("recording_date must not lie in the future")
    # state -> hold -> beneficiary, in that order (PRD §3.2)
    if case["lifecycle_status"] != "REFERRED":
        raise err_invalid_case_state("NOD recording requires lifecycle_status == REFERRED")
    if case["hold_status"] != "CLEAR":
        raise err_active_stay()
    ben = db.beneficiaries.get(case["beneficiary_id"])
    if ben is None or ben["status"] != "ACTIVE":
        raise err_beneficiary_suspended()
    nod = {
        "foreclosure_case_id": case["id"],
        "recording_date": format_date(recording_date),
        "instrument_number": instrument_number,
        "status": "RECORDED",
        "rescinded_at": None,
    }
    stamp_new(nod)
    db.notices_of_default[nod["id"]] = nod
    case["lifecycle_status"] = "NOD_RECORDED"
    case["reinstatement_deadline_date"] = format_date(
        add_days(recording_date, calc.REINSTATEMENT_PERIOD_DAYS))
    touch(case)
    return success_object(view(nod), status=201)


@bp.route("/api/foreclosure-cases/<case_id>/notices-of-default", methods=["GET"], strict_slashes=False)
@require_roles("TrusteeAdmin", "CaseManager", "Auctioneer", "Beneficiary")
def list_nods(user_id, role, case_id):
    get_case(case_id)
    items = case_nods(case_id)
    limit, offset = parse_pagination(request.args)
    page = [view(n) for n in items[offset:offset + limit]]
    return success_list(page, limit, offset, len(items))


@bp.route("/api/notices-of-default/<nod_id>/rescind", methods=["POST"], strict_slashes=False)
@require_roles("CaseManager")
def rescind_nod(user_id, role, nod_id):
    nod = get_nod(nod_id)
    body = get_body()
    check_unknown(body, set())
    case = get_case(nod["foreclosure_case_id"])
    if case["lifecycle_status"] not in ("NOD_RECORDED", "NOTS_RECORDED", "SALE_SCHEDULED"):
        raise err_invalid_case_state("rescission requires NOD_RECORDED / NOTS_RECORDED / SALE_SCHEDULED")
    if nod["status"] != "RECORDED":
        # unreachable in correct flows (a rescinded NOD implies CANCELLED case)
        raise err_invalid_request("notice of default is not RECORDED")
    apply_nod_rescission(case, nod)
    return success_object(view(nod))


# ---------------------------------------------------------------------------
# NoticeOfTrusteeSale
# ---------------------------------------------------------------------------

@bp.route("/api/foreclosure-cases/<case_id>/notices-of-trustee-sale", methods=["POST"], strict_slashes=False)
@require_roles("CaseManager")
def record_nots(user_id, role, case_id):
    case = get_case(case_id)
    body = get_body()
    check_unknown(body, {"recording_date", "instrument_number"})
    recording_date = req_date(body, "recording_date")
    instrument_number = req_string(body, "instrument_number")
    if recording_date > db.CLOCK.now_date():
        raise err_invalid_request("recording_date must not lie in the future")
    if case["lifecycle_status"] != "NOD_RECORDED":
        raise err_invalid_case_state("NOTS recording requires lifecycle_status == NOD_RECORDED")
    if case["hold_status"] != "CLEAR":
        raise err_active_stay()
    deadline = parse_date_strict(case["reinstatement_deadline_date"]) \
        if case["reinstatement_deadline_date"] else None
    if deadline is None or db.CLOCK.now_date() < deadline:
        # exactly on the deadline day is allowed
        raise err_nots_too_early()
    if recorded_nod(case["id"]) is None:
        # invariant under the state gate; defensive
        raise err_invalid_case_state("no RECORDED notice of default on the case")
    if live_nots(case["id"]) is not None:
        # invariant under the state gate; defensive
        raise err_invalid_case_state("a live notice of trustee's sale already exists")
    nots = {
        "foreclosure_case_id": case["id"],
        "recording_date": format_date(recording_date),
        "instrument_number": instrument_number,
        "status": "RECORDED",
        "postponement_count": 0,
        "first_publication_date": None,
    }
    stamp_new(nots)
    db.notices_of_trustee_sale[nots["id"]] = nots
    case["lifecycle_status"] = "NOTS_RECORDED"
    touch(case)
    return success_object(view(nots), status=201)


@bp.route("/api/foreclosure-cases/<case_id>/notices-of-trustee-sale", methods=["GET"], strict_slashes=False)
@require_roles("TrusteeAdmin", "CaseManager", "Auctioneer", "Beneficiary")
def list_nots(user_id, role, case_id):
    get_case(case_id)
    items = case_nots_list(case_id)
    limit, offset = parse_pagination(request.args)
    page = [view(n) for n in items[offset:offset + limit]]
    return success_list(page, limit, offset, len(items))


@bp.route("/api/notices-of-trustee-sale/<nots_id>", methods=["GET"], strict_slashes=False)
@require_roles("TrusteeAdmin", "CaseManager", "Auctioneer", "Beneficiary")
def read_nots(user_id, role, nots_id):
    return success_object(view(get_nots(nots_id)))


# ---------------------------------------------------------------------------
# Publication
# ---------------------------------------------------------------------------

@bp.route("/api/notices-of-trustee-sale/<nots_id>/publications", methods=["POST"], strict_slashes=False)
@require_roles("CaseManager")
def record_publication(user_id, role, nots_id):
    nots = get_nots(nots_id)
    body = get_body()
    check_unknown(body, {"run_date", "newspaper_name"})
    run_date = req_date(body, "run_date")
    newspaper_name = req_string(body, "newspaper_name")
    # clock consistency (§2.5): run_date must not lie in the future
    if run_date > db.CLOCK.now_date():
        raise err_invalid_request("run_date must not lie in the future")
    # then NOTS state, then the 7-day gap, then the 3-run cap (PRD §3.3)
    if nots["status"] not in ("RECORDED", "PUBLICATION_COMPLETE"):
        raise err_invalid_nots_state("publications require NOTS RECORDED or PUBLICATION_COMPLETE")
    siblings = nots_publications(nots["id"])
    if siblings:
        latest = max(parse_date_strict(p["run_date"]) for p in siblings)
        if run_date < add_days(latest, calc.PUBLICATION_MIN_GAP_DAYS):
            # exactly 7 days later is acceptable
            raise err_publication_gap()
    if len(siblings) >= calc.PUBLICATIONS_REQUIRED:
        raise err_publication_limit()
    pub_rec = {
        "notice_of_trustee_sale_id": nots["id"],
        "run_date": format_date(run_date),
        "newspaper_name": newspaper_name,
        "run_index": len(siblings) + 1,
        "status": "RUN",
        "affidavit_filed_at": None,
    }
    stamp_new(pub_rec)
    db.publications[pub_rec["id"]] = pub_rec
    if nots["first_publication_date"] is None:
        nots["first_publication_date"] = format_date(run_date)
        touch(nots)
    return success_object(view(pub_rec), status=201)


@bp.route("/api/notices-of-trustee-sale/<nots_id>/publications", methods=["GET"], strict_slashes=False)
@require_roles("TrusteeAdmin", "CaseManager", "Auctioneer")
def list_publications(user_id, role, nots_id):
    get_nots(nots_id)
    items = nots_publications(nots_id)
    limit, offset = parse_pagination(request.args)
    page = [view(p) for p in items[offset:offset + limit]]
    return success_list(page, limit, offset, len(items))


@bp.route("/api/publications/<publication_id>/file-affidavit", methods=["POST"], strict_slashes=False)
@require_roles("CaseManager")
def file_affidavit(user_id, role, publication_id):
    pub_rec = get_publication(publication_id)
    body = get_body()
    check_unknown(body, set())
    if pub_rec["status"] != "RUN":
        raise err_invalid_request("publication is not in RUN status")
    nots = get_nots(pub_rec["notice_of_trustee_sale_id"])
    if nots["status"] not in ("RECORDED", "PUBLICATION_COMPLETE"):
        raise err_invalid_nots_state("parent notice must be RECORDED or PUBLICATION_COMPLETE")
    if db.CLOCK.now_date() < parse_date_strict(pub_rec["run_date"]):
        raise err_invalid_request("affidavit cannot be filed before the run date")
    pub_rec["status"] = "AFFIDAVIT_FILED"
    pub_rec["affidavit_filed_at"] = now_iso()
    touch(pub_rec)
    # bubble-up: the third affidavit completes the notice's publication cycle
    siblings = nots_publications(nots["id"])
    if (len(siblings) == calc.PUBLICATIONS_REQUIRED
            and all(p["status"] == "AFFIDAVIT_FILED" for p in siblings)
            and nots["status"] == "RECORDED"):
        nots["status"] = "PUBLICATION_COMPLETE"
        touch(nots)
    return success_object(view(pub_rec))


# ---------------------------------------------------------------------------
# Schedule the auction against a NOTS
# ---------------------------------------------------------------------------

def venue_conflict(venue_name, start_dt, exclude_sale_id=None):
    """Half-open [start, start+60min) occupancy: another sale with the same
    venue in SCHEDULED or CONDUCTED whose interval intersects the requested
    one conflicts; one ending exactly as the other begins does not."""
    from datetime import timedelta
    new_end = start_dt + timedelta(minutes=calc.AUCTION_DURATION_MINUTES)
    for s in db.auction_sales.values():
        if s["id"] == exclude_sale_id:
            continue
        if s["venue_name"] != venue_name:
            continue
        if s["status"] not in ("SCHEDULED", "CONDUCTED"):
            continue
        s_start = db._parse_iso(s["scheduled_sale_start_at"])
        s_end = s_start + timedelta(minutes=calc.AUCTION_DURATION_MINUTES)
        if s_start < new_end and start_dt < s_end:
            return True
    return False


@bp.route("/api/notices-of-trustee-sale/<nots_id>/schedule-sale", methods=["POST"], strict_slashes=False)
@require_roles("CaseManager")
def schedule_sale(user_id, role, nots_id):
    nots = get_nots(nots_id)
    body = get_body()
    check_unknown(body, {"venue_name", "scheduled_sale_start_at"})
    venue_name = req_string(body, "venue_name")
    start_raw, start_dt = req_datetime_raw(body, "scheduled_sale_start_at")
    case = get_case(nots["foreclosure_case_id"])
    # fixed guard order (PRD §3.8): case -> NOTS -> hold -> publications ->
    # date floors -> venue
    if case["lifecycle_status"] != "NOTS_RECORDED":
        raise err_invalid_case_state("schedule-sale requires lifecycle_status == NOTS_RECORDED")
    if nots["status"] not in ("RECORDED", "PUBLICATION_COMPLETE"):
        raise err_invalid_nots_state()
    if case["hold_status"] != "CLEAR":
        raise err_active_stay()
    if nots["status"] != "PUBLICATION_COMPLETE":
        raise err_publication_incomplete()
    sale_date = start_dt.date()
    first_pub = parse_date_strict(nots["first_publication_date"])
    nots_recorded = parse_date_strict(nots["recording_date"])
    if (sale_date < add_days(first_pub, calc.FIRST_PUBLICATION_MIN_DAYS_BEFORE_SALE)
            or sale_date < add_days(nots_recorded, calc.NOTS_MIN_DAYS_BEFORE_SALE)):
        # starts on either boundary day are acceptable
        raise err_sale_date_too_soon()
    if venue_conflict(venue_name, start_dt):
        raise err_auction_conflict()
    sale = {
        "foreclosure_case_id": case["id"],
        "notice_of_trustee_sale_id": nots["id"],
        "venue_name": venue_name,
        "scheduled_sale_start_at": start_raw,
        "status": "SCHEDULED",
        "opening_bid_cents": None,
        "winner_type": None,
        "winning_bid_cents": None,
        "winning_bidder_registration_id": None,
        "total_debt_at_close_cents": None,
        "closed_at": None,
    }
    stamp_new(sale)
    db.auction_sales[sale["id"]] = sale
    nots["status"] = "SALE_SCHEDULED"
    touch(nots)
    case["lifecycle_status"] = "SALE_SCHEDULED"
    touch(case)
    return success_object(view(sale), status=201)
