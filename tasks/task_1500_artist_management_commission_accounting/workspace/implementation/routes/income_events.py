"""IncomeEvent endpoints (PRD 3.5)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_ARTIST_ARCHIVED,
    ERR_NO_COVERING_AGREEMENT,
    ERR_AGREEMENT_NOT_ACTIVE,
    ERR_EVENT_ALREADY_SETTLED,
    ERR_AMOUNT_OUT_OF_RANGE,
    ERR_ADJUSTMENT_PARENT_INVALID,
    ERR_SEGREGATION_OF_DUTIES,
)
from response import success_object
from routes.helpers import get_one, list_response, public, scoped_mutation_auth
from services.calculations import (
    COMMISSIONABLE_POSTURES,
    compute_commission_amount,
    resolve_commission,
    run_recoupment_waterfall,
)
from services.core import new_record, touch, recompute_artist
from util import parse_date
from validate import (
    get_body, opt_enum, opt_str, req_date, req_enum, req_int, req_str,
    require_path_resource, require_ref,
)

bp = Blueprint("income_events", __name__)

INCOME_TYPES = {"TOURING", "RECORDING", "PUBLISHING", "ENDORSEMENT"}
EVENT_KINDS = {"ORIGINAL", "ADJUSTMENT"}


def _resolve_agreement(artist_id, recognition_date):
    """Among the artist's agreements with term_start_date <= recognition_date, the
    one with the greatest term_start_date wins; ties broken by created_at ASC.
    Status is ignored entirely."""
    recog = parse_date(recognition_date)
    candidates = [
        a for a in db["agreements"].values()
        if a["artist_id"] == artist_id and parse_date(a["term_start_date"]) <= recog
    ]
    if not candidates:
        raise_error(ERR_NO_COVERING_AGREEMENT,
                    "no agreement of the artist covers the recognition date")
    candidates.sort(key=lambda a: a["created_at"])  # ties: earliest created_at
    best = max(candidates, key=lambda a: parse_date(a["term_start_date"]))
    # max() with ties keeps the first encountered among equal keys only if stable:
    # re-derive deterministically
    best_start = max(parse_date(a["term_start_date"]) for a in candidates)
    tied = [a for a in candidates if parse_date(a["term_start_date"]) == best_start]
    tied.sort(key=lambda a: (a["created_at"], a["id"]))
    return tied[0]


@bp.post("/income-events")
def create_income_event():
    body = get_body()
    artist_id = req_str(body, "artist_id")
    caller = scoped_mutation_auth(["Agent", "BusinessManager"], body_artist_id=artist_id)
    income_type = req_enum(body, "income_type", INCOME_TYPES)
    gross = req_int(body, "gross_amount_cents", positive=True)
    recognition_date = req_date(body, "recognition_date")
    source_name = req_str(body, "source_name")
    kind = opt_enum(body, "kind", EVENT_KINDS, "ORIGINAL")
    linked_engagement_id = opt_str(body, "linked_engagement_id")
    parent_event_id = opt_str(body, "parent_event_id")

    artist = require_ref("artists", artist_id, "artist_id")
    if linked_engagement_id is not None:
        require_ref("engagements", linked_engagement_id, "linked_engagement_id")
    parent = None
    if parent_event_id is not None:
        parent = require_ref("income_events", parent_event_id, "parent_event_id")

    # Priority 12: archived artist blocks new income
    if artist["status"] == "ARCHIVED":
        raise_error(ERR_ARTIST_ARCHIVED, "artist is ARCHIVED")

    # Adjustment-kind rules (priority 12 gate)
    if kind == "ADJUSTMENT":
        if parent_event_id is None:
            raise_error(ERR_ADJUSTMENT_PARENT_INVALID,
                        "kind=ADJUSTMENT requires parent_event_id")
        if parent["status"] not in ("SETTLED", "POSTED"):
            raise_error(ERR_ADJUSTMENT_PARENT_INVALID,
                        "adjustment parent must be SETTLED or POSTED")

    agreement = _resolve_agreement(artist_id, recognition_date)

    rec = new_record("income_events", {
        "artist_id": artist_id,
        "agreement_id": agreement["id"],
        "linked_engagement_id": linked_engagement_id,
        "parent_event_id": parent_event_id,
        "kind": kind,
        "income_type": income_type,
        "source_name": source_name,
        "gross_amount_cents": gross,
        "recognition_date": recognition_date,
        "received_date": None,
        "received_amount_cents": None,
        "status": "REPORTED",
        "term_relation": None,
        "applied_schedule_id": None,
        "applied_rate_bps": None,
        "commission_amount_cents": None,
        "artist_net_cents": None,
        "recouped_amount_cents": 0,
        "artist_payable_cents": None,
        "statement_id": None,
        "recoup_statement_id": None,
        "reported_by_user_id": caller.user_id,
    })
    recompute_artist(artist_id, bump=True)
    return success_object(public(rec), status=201)


@bp.get("/income-events/<rid>")
def get_income_event(rid):
    return get_one("income_events", rid)


@bp.get("/income-events")
def list_income_events():
    filters = {
        "artist_id": request.args.get("artist_id"),
        "agreement_id": request.args.get("agreement_id"),
        "linked_engagement_id": request.args.get("linked_engagement_id"),
        "parent_event_id": request.args.get("parent_event_id"),
        "statement_id": request.args.get("statement_id"),
        "recoup_statement_id": request.args.get("recoup_statement_id"),
        "applied_schedule_id": request.args.get("applied_schedule_id"),
        "status": request.args.get("status"),
        "income_type": request.args.get("income_type"),
    }
    return list_response("income_events", filters)


@bp.post("/income-events/<rid>/verify")
def verify_income_event(rid):
    caller = scoped_mutation_auth(["BusinessManager"], "income_events", rid)
    ev = require_path_resource("income_events", rid)
    # Priority 8: state precondition
    if ev["status"] != "REPORTED":
        raise_error(ERR_INVALID_STATE, "only a REPORTED event can be verified")
    # Priority 10: segregation of duties
    if caller.user_id == ev["reported_by_user_id"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES, "verifier must differ from reporter")
    # Priority 12: agreement posture
    agreement = db["agreements"].get(ev["agreement_id"])
    if agreement is None or agreement["status"] not in COMMISSIONABLE_POSTURES:
        raise_error(ERR_AGREEMENT_NOT_ACTIVE,
                    "resolved agreement is not in a commissionable posture")
    # Pins rate + commission (raises ERR_NO_RATE_SCHEDULE inside)
    resolve_commission(ev, agreement)
    compute_commission_amount(ev, agreement)
    ev["status"] = "VERIFIED"
    touch(ev)
    recompute_artist(ev["artist_id"], bump=True)
    return success_object(public(ev))


@bp.post("/income-events/<rid>/settle")
def settle_income_event(rid):
    caller = scoped_mutation_auth(["BusinessManager"], "income_events", rid)
    body = get_body()
    ev = require_path_resource("income_events", rid)
    received_date = req_date(body, "received_date")
    received_amount = req_int(body, "received_amount_cents")
    # Priority 8: state precondition
    if ev["status"] not in ("VERIFIED", "POSTED"):
        if ev["status"] in ("SETTLED",):
            raise_error(ERR_INVALID_STATE, "event is already SETTLED")
        raise_error(ERR_INVALID_STATE, f"cannot settle from {ev['status']}")
    # Priority 14: amount range
    if not (received_amount > 0
            and received_amount <= ev["gross_amount_cents"]
            and received_amount >= (ev["commission_amount_cents"] or 0)):
        raise_error(ERR_AMOUNT_OUT_OF_RANGE,
                    "received_amount_cents must be > 0, <= gross, and >= commission")

    ev["received_date"] = received_date
    ev["received_amount_cents"] = received_amount

    agreement = db["agreements"].get(ev["agreement_id"])
    run_recoupment_waterfall(ev, agreement)

    # POSTED is a latch: status remains POSTED after settlement
    if ev["status"] == "VERIFIED":
        ev["status"] = "SETTLED"
    touch(ev)

    recompute_artist(ev["artist_id"], bump=True)

    # Linked COMPLETED engagement -> SETTLED
    if ev.get("linked_engagement_id"):
        eng = db["engagements"].get(ev["linked_engagement_id"])
        if eng is not None and eng["status"] == "COMPLETED":
            eng["status"] = "SETTLED"
            touch(eng)
    return success_object(public(ev))


@bp.post("/income-events/<rid>/void")
def void_income_event(rid):
    caller = scoped_mutation_auth(["BusinessManager"], "income_events", rid)
    ev = require_path_resource("income_events", rid)
    if ev["status"] in ("SETTLED", "POSTED"):
        raise_error(ERR_EVENT_ALREADY_SETTLED,
                    "SETTLED/POSTED events are never voided; file an ADJUSTMENT child")
    if ev["status"] != "REPORTED" and ev["status"] != "VERIFIED":
        raise_error(ERR_INVALID_STATE, f"cannot void from {ev['status']}")
    ev["status"] = "VOIDED"
    touch(ev)
    recompute_artist(ev["artist_id"], bump=True)
    return success_object(public(ev))
