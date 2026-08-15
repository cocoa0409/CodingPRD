"""Opportunity endpoints (PRD 3.3)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_ARTIST_ARCHIVED,
    ERR_OFFER_EXPIRED,
    ERR_ARTIST_APPROVAL_REQUIRED,
    ERR_STALE_OPPORTUNITY_VERSION,
    ERR_ENGAGEMENT_WINDOW_PAST,
)
from response import success_object
from routes.helpers import get_one, list_response, public, scoped_mutation_auth
from services.calculations import (
    evaluate_opportunity,
    has_approved_artist_request,
    maybe_create_artist_approval,
)
from services.core import new_record, touch, cancel_pending_approvals_for, confirm_cascade
from util import CLOCK, parse_datetime
from validate import (
    get_body, opt_int, req_date, req_datetime, req_enum, req_int, req_str,
    require_path_resource, require_ref,
)

bp = Blueprint("opportunities", __name__)

INCOME_TYPES = {"TOURING", "RECORDING", "PUBLISHING", "ENDORSEMENT"}
OPEN_STATES = ("RECEIVED", "UNDER_EVALUATION", "NEGOTIATING")


def _requires_approval(opp):
    return opp["current_value_cents"] > 10000000


@bp.post("/opportunities")
def create_opportunity():
    body = get_body()
    artist_id = req_str(body, "artist_id")
    caller = scoped_mutation_auth(["Agent"], body_artist_id=artist_id)
    income_type = req_enum(body, "income_type", INCOME_TYPES)
    counterparty_name = req_str(body, "counterparty_name")
    proposed_value = req_int(body, "proposed_value_cents", positive=True)
    offer_expiry = req_date(body, "offer_expiry_date")
    window_start = req_datetime(body, "proposed_window_start")
    window_end = req_datetime(body, "proposed_window_end")
    if parse_datetime(window_end) <= parse_datetime(window_start):
        raise_error(ERR_INVALID_REQUEST, "proposed_window_end must be later than proposed_window_start")
    fit_score = req_int(body, "fit_score", minimum=0, maximum=100)

    artist = require_ref("artists", artist_id, "artist_id")
    if artist["status"] == "ARCHIVED":
        raise_error(ERR_ARTIST_ARCHIVED, "artist is ARCHIVED")

    rec = new_record("opportunities", {
        "artist_id": artist_id,
        "income_type": income_type,
        "counterparty_name": counterparty_name,
        "proposed_value_cents": proposed_value,
        "current_value_cents": proposed_value,
        "offer_expiry_date": offer_expiry,
        "proposed_window_start": window_start,
        "proposed_window_end": window_end,
        "fit_score": fit_score,
        "evaluation_score": None,
        "recommendation": None,
        "requires_artist_approval": proposed_value > 10000000,
        "round_number": 0,
        "status": "RECEIVED",
        "converted_engagement_id": None,
    })
    return success_object(public(rec), status=201)


@bp.get("/opportunities/<rid>")
def get_opportunity(rid):
    return get_one("opportunities", rid)


@bp.get("/opportunities")
def list_opportunities():
    filters = {
        "artist_id": request.args.get("artist_id"),
        "status": request.args.get("status"),
        "income_type": request.args.get("income_type"),
        "converted_engagement_id": request.args.get("converted_engagement_id"),
    }
    return list_response("opportunities", filters)


@bp.post("/opportunities/<rid>/evaluate")
def evaluate(rid):
    caller = scoped_mutation_auth(["Agent", "BusinessManager"], "opportunities", rid)
    opp = require_path_resource("opportunities", rid)
    if opp["status"] not in ("RECEIVED", "UNDER_EVALUATION"):
        raise_error(ERR_INVALID_STATE, f"cannot evaluate from {opp['status']}")
    score, recommendation = evaluate_opportunity(opp, CLOCK.today())
    opp["evaluation_score"] = score
    opp["recommendation"] = recommendation
    opp["status"] = "UNDER_EVALUATION"
    touch(opp)
    return success_object(public(opp))


@bp.post("/opportunities/<rid>/negotiate")
def negotiate(rid):
    caller = scoped_mutation_auth(["Agent"], "opportunities", rid)
    opp = require_path_resource("opportunities", rid)
    if opp["status"] != "UNDER_EVALUATION":
        raise_error(ERR_INVALID_STATE, "negotiate requires UNDER_EVALUATION")
    from util import parse_date
    if CLOCK.today() > parse_date(opp["offer_expiry_date"]):
        raise_error(ERR_OFFER_EXPIRED, "offer has lapsed")
    opp["status"] = "NEGOTIATING"
    touch(opp)
    maybe_create_artist_approval(opp, caller.user_id)
    return success_object(public(opp))


@bp.post("/opportunities/<rid>/counter-offer")
def counter_offer(rid):
    caller = scoped_mutation_auth(["Agent"], "opportunities", rid)
    body = get_body()
    opp = require_path_resource("opportunities", rid)
    new_value = req_int(body, "new_value_cents", positive=True)
    expected_version = opt_int(body, "expected_opportunity_version")
    if opp["status"] != "NEGOTIATING":
        raise_error(ERR_INVALID_STATE, "counter-offer requires NEGOTIATING")
    if expected_version is not None and expected_version != opp["version"]:
        raise_error(ERR_STALE_OPPORTUNITY_VERSION,
                    "expected_opportunity_version does not match the opportunity's current version")
    from util import parse_date
    if CLOCK.today() > parse_date(opp["offer_expiry_date"]):
        raise_error(ERR_OFFER_EXPIRED, "offer has lapsed")

    was_required = _requires_approval(opp)
    current = opp["current_value_cents"]
    # 10% band (inclusive on the stay side): |new-current|*10 <= current stays NEGOTIATING
    delta = abs(new_value - current)
    stays_negotiating = (delta * 10) <= current

    opp["current_value_cents"] = new_value
    opp["round_number"] += 1
    opp["requires_artist_approval"] = new_value > 10000000
    if not stays_negotiating:
        opp["status"] = "UNDER_EVALUATION"
        # evaluation_score and recommendation deliberately NOT recomputed
    touch(opp)
    if not was_required and _requires_approval(opp):
        maybe_create_artist_approval(opp, caller.user_id)
    return success_object(public(opp))


@bp.post("/opportunities/<rid>/accept")
def accept(rid):
    caller = scoped_mutation_auth(["Agent"], "opportunities", rid)
    opp = require_path_resource("opportunities", rid)
    if opp["status"] not in ("UNDER_EVALUATION", "NEGOTIATING"):
        raise_error(ERR_INVALID_STATE, f"cannot accept from {opp['status']}")
    if opp["evaluation_score"] is None:
        raise_error(ERR_INVALID_STATE, "must evaluate before accepting")
    from util import parse_date
    if CLOCK.today() > parse_date(opp["offer_expiry_date"]):
        raise_error(ERR_OFFER_EXPIRED, "offer has lapsed")
    if _requires_approval(opp) and not has_approved_artist_request(opp["id"]):
        raise_error(ERR_ARTIST_APPROVAL_REQUIRED,
                    "an APPROVED ARTIST approval request is required for high-value accept")
    opp["status"] = "ACCEPTED"
    touch(opp)
    return success_object(public(opp))


def _exit_pipeline(opp, target_status):
    if opp["status"] not in OPEN_STATES:
        raise_error(ERR_INVALID_STATE, f"cannot move to {target_status} from {opp['status']}")
    opp["status"] = target_status
    touch(opp)
    cancel_pending_approvals_for("OPPORTUNITY", opp["id"])


@bp.post("/opportunities/<rid>/decline")
def decline(rid):
    caller = scoped_mutation_auth(["Agent"], "opportunities", rid)
    opp = require_path_resource("opportunities", rid)
    _exit_pipeline(opp, "DECLINED")
    return success_object(public(opp))


@bp.post("/opportunities/<rid>/withdraw")
def withdraw(rid):
    caller = scoped_mutation_auth(["Agent"], "opportunities", rid)
    opp = require_path_resource("opportunities", rid)
    _exit_pipeline(opp, "WITHDRAWN")
    return success_object(public(opp))


@bp.post("/opportunities/<rid>/convert")
def convert(rid):
    caller = scoped_mutation_auth(["Agent"], "opportunities", rid)
    opp = require_path_resource("opportunities", rid)
    if opp["status"] != "ACCEPTED":
        raise_error(ERR_INVALID_STATE, "convert requires ACCEPTED")
    if parse_datetime(opp["proposed_window_end"]) <= CLOCK.now():
        raise_error(ERR_ENGAGEMENT_WINDOW_PAST,
                    "the engagement would be born CONFIRMED with its window already past")

    eng = new_record("engagements", {
        "artist_id": opp["artist_id"],
        "opportunity_id": opp["id"],
        "income_type": opp["income_type"],
        "counterparty_name": opp["counterparty_name"],
        "start_datetime": opp["proposed_window_start"],
        "end_datetime": opp["proposed_window_end"],
        "travel_buffer_hours": 24,
        "guarantee_cents": opp["current_value_cents"],
        "status": "CONFIRMED",
        "confirmed_at": CLOCK.now_iso(),
    })
    # Overlap check + hold-release cascade (raises ERR_ENGAGEMENT_OVERLAP)
    confirm_cascade(opp["artist_id"], eng, exclude_id=eng["id"])

    opp["status"] = "CONVERTED"
    opp["converted_engagement_id"] = eng["id"]
    touch(opp)
    return success_object(public(eng), status=201)
