"""Protest filing, the agency record, hearing scheduling, the decision,
withdrawal and the stay override (PRD §3.7 and §3.8)."""

from flask import Blueprint, g

import calc
import serializers
import services
import store
import validation as v
from errors import ApiError
from util import add_days, whole_minutes

bp = Blueprint("protests", __name__)

GROUNDS = (
    "SOLICITATION_IMPROPRIETY", "RESPONSIVENESS_DETERMINATION",
    "RESPONSIBILITY_DETERMINATION", "AWARD_IMPROPRIETY", "EVALUATION_ERROR",
)
GROUNDS_REQUIRING_BID = ("RESPONSIVENESS_DETERMINATION", "RESPONSIBILITY_DETERMINATION")
PROTESTABLE_STATUSES = (
    "ISSUED", "QUESTION_PERIOD_CLOSED", "BIDS_OPENED", "EVALUATION",
    "AWARD_PENDING", "AWARDED",
)
STAYABLE_STATUSES = (
    "ISSUED", "QUESTION_PERIOD_CLOSED", "BIDS_OPENED", "EVALUATION", "AWARD_PENDING",
)
OPEN_PROTEST_STATUSES = ("FILED", "UNDER_REVIEW", "HEARING_SCHEDULED")
ITEM_TYPES = (
    "SOLICITATION_DOCUMENT", "ADDENDUM", "BID_ABSTRACT", "RESPONSIVENESS_MEMO",
    "RESPONSIBILITY_MEMO", "PROTESTER_SUBMISSION", "AGENCY_REPORT",
)
REMEDIES = ("CORRECTIVE_ACTION", "CANCELLATION", "RESOLICITATION", "NONE")


def _standing_basis(solicitation, vendor, grounds_code):
    for bid in services.bids_of(solicitation):
        if bid["vendor_id"] != vendor["id"]:
            continue
        if bid["responsiveness_status"] in ("UNREVIEWED", "RESPONSIVE", "NONRESPONSIVE"):
            return "ACTUAL_BIDDER"
    if grounds_code == "SOLICITATION_IMPROPRIETY":
        for question in services.questions_of(solicitation):
            if question["vendor_id"] != vendor["id"]:
                continue
            if question["status"] in ("PENDING", "ANSWERED"):
                return "PROSPECTIVE_BIDDER"
    return None


def _trigger_and_deadline(solicitation, grounds_code, challenged_bid):
    """Returns (trigger_instant, deadline) or (None, None) when the trigger
    event the grounds require does not exist."""
    if grounds_code == "SOLICITATION_IMPROPRIETY":
        trigger = solicitation["effective_bid_due_utc"]
        if trigger is None:
            return None, None
        return trigger, add_days(trigger, -calc.PRE_BID_MARGIN_DAYS)

    if grounds_code == "RESPONSIVENESS_DETERMINATION":
        trigger = challenged_bid["responsiveness_decided_at_utc"]
        if trigger is None:
            return None, None
        return trigger, add_days(trigger, calc.STANDARD_WINDOW_DAYS)

    if grounds_code == "RESPONSIBILITY_DETERMINATION":
        operative = [
            r for r in services.reviews_of(challenged_bid)
            if r["superseded_at_utc"] is None
        ]
        if not operative:
            return None, None
        operative.sort(key=lambda r: (r["decided_at_utc"], r["created_at"], r["_seq"]))
        trigger = operative[-1]["decided_at_utc"]
        return trigger, add_days(trigger, calc.STANDARD_WINDOW_DAYS)

    if grounds_code == "AWARD_IMPROPRIETY":
        awards = [
            a for a in services.awards_of(solicitation)
            if a["status"] in ("PENDING_STAY", "EXECUTED")
        ]
        if not awards:
            return None, None
        awards.sort(key=lambda a: (a["created_at"], a["_seq"]))
        trigger = awards[-1]["created_at"]
        return trigger, add_days(trigger, calc.AWARD_WINDOW_DAYS)

    trigger = solicitation["bids_opened_at_utc"]
    if trigger is None:
        return None, None
    return trigger, add_days(trigger, calc.STANDARD_WINDOW_DAYS)


def _lift_stay(protest):
    if protest["stay_status"] in ("ACTIVE", "OVERRIDDEN"):
        v.set_field(protest, "stay_status", "LIFTED")


def _refund(protest, solicitation):
    amount = protest["filing_fee_cents"]
    v.set_field(protest, "fee_refunded_cents", amount)
    solicitation["protest_escrow_cents"] -= amount
    v.touch(solicitation)
    vendor = store.get("vendors", protest["protester_vendor_id"])
    if vendor is not None:
        vendor["protest_fee_balance_cents"] += amount
        v.touch(vendor)


# --------------------------------------------------------------------------- #
# filing, reading and listing
# --------------------------------------------------------------------------- #

@bp.post("/procurement/protests")
@v.endpoint(["Vendor"])
def file_protest():
    data = v.body()
    solicitation_id = v.req_str(data, "solicitation_id")
    protester_vendor_id = v.req_str(data, "protester_vendor_id")
    grounds_code = v.req_enum(data, "grounds_code", GROUNDS)
    narrative = v.req_str(data, "narrative")
    challenged_bid_id = v.opt_str(data, "challenged_bid_id")

    if grounds_code in GROUNDS_REQUIRING_BID and challenged_bid_id is None:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "field 'challenged_bid_id' is required for grounds %s" % grounds_code,
        )
    if grounds_code not in GROUNDS_REQUIRING_BID and challenged_bid_id is not None:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "field 'challenged_bid_id' must be null for grounds %s" % grounds_code,
        )

    solicitation = services.must("solicitations", solicitation_id)
    vendor = services.must("vendors", protester_vendor_id)
    challenged_bid = None
    if challenged_bid_id is not None:
        challenged_bid = services.must("bids", challenged_bid_id)

    if g.user_id != vendor["id"]:
        raise ApiError("ERR_VENDOR_IDENTITY_MISMATCH")

    if solicitation["status"] not in PROTESTABLE_STATUSES:
        raise ApiError("ERR_SOLICITATION_NOT_PROTESTABLE")

    standing_basis = _standing_basis(solicitation, vendor, grounds_code)
    if standing_basis is None:
        raise ApiError("ERR_PROTESTER_LACKS_STANDING")

    foreign_bid = (
        challenged_bid is not None
        and challenged_bid["solicitation_id"] != solicitation["id"]
    )

    trigger, deadline = _trigger_and_deadline(solicitation, grounds_code, challenged_bid)
    if trigger is None:
        if foreign_bid:
            raise ApiError("ERR_BID_NOT_ON_SOLICITATION")
        raise ApiError("ERR_PROTEST_TRIGGER_EVENT_MISSING")

    if store.now() > deadline:
        raise ApiError("ERR_PROTEST_UNTIMELY")

    if foreign_bid:
        raise ApiError("ERR_BID_NOT_ON_SOLICITATION")

    fee = calc.filing_fee_cents(solicitation["estimated_value_cents"], grounds_code)
    if vendor["protest_fee_balance_cents"] < fee:
        raise ApiError("ERR_INSUFFICIENT_FEE_BALANCE")

    executed = any(a["status"] == "EXECUTED" for a in services.awards_of(solicitation))
    stay_status = "NONE"
    if solicitation["status"] in STAYABLE_STATUSES and not executed:
        stay_status = "ACTIVE"

    protest = store.insert("protests", store.row("protests", {
        "solicitation_id": solicitation["id"],
        "protester_vendor_id": vendor["id"],
        "challenged_bid_id": challenged_bid["id"] if challenged_bid else None,
        "grounds_code": grounds_code,
        "narrative": narrative,
        "filed_at_utc": store.now(),
        "status": "FILED",
        "stay_status": stay_status,
        "filing_fee_cents": fee,
        "timeliness_deadline_utc": deadline,
        "standing_basis": standing_basis,
        "decision_outcome": None,
        "remedy_code": None,
        "decided_at_utc": None,
        "record_item_count": 0,
        "fee_refunded_cents": 0,
    }))

    vendor["protest_fee_balance_cents"] -= fee
    v.touch(vendor)
    solicitation["protest_escrow_cents"] += fee
    v.touch(solicitation)
    return ("obj", protest, serializers.protest, 201)


@bp.get("/procurement/protests/<protest_id>")
@v.endpoint(v.ALL_ROLES)
def read_protest(protest_id):
    return ("obj", services.must("protests", protest_id), serializers.protest, 200)


@bp.get("/procurement/protests")
@v.endpoint(v.ALL_ROLES)
def list_protests():
    limit, offset = v.pagination()
    filters = {
        "solicitation_id": v.query("solicitation_id"),
        "protester_vendor_id": v.query("protester_vendor_id"),
        "challenged_bid_id": v.query("challenged_bid_id"),
        "status": v.query("status"),
        "stay_status": v.query("stay_status"),
    }
    rows = [r for r in store.ordered(store.values("protests")) if v.match_filters(r, filters)]
    page, total = v.paginate(rows, limit, offset)
    return ("list", page, serializers.protest, limit, offset, total)


# --------------------------------------------------------------------------- #
# the agency record
# --------------------------------------------------------------------------- #

@bp.post("/procurement/protests/<protest_id>/record-items")
@v.endpoint(["ProcurementOfficer", "HearingOfficer", "Vendor"])
def file_record_item(protest_id):
    data = v.body()
    item_type = v.req_enum(data, "item_type", ITEM_TYPES)
    document_ref = v.req_str(data, "document_ref")

    protest = services.must("protests", protest_id)
    if protest["status"] not in OPEN_PROTEST_STATUSES:
        raise ApiError("ERR_INVALID_PROTEST_STATE")

    item = store.insert("record_items", store.row("record_items", {
        "protest_id": protest["id"],
        "sequence_number": protest["record_item_count"] + 1,
        "item_type": item_type,
        "document_ref": document_ref,
        "submitted_by_role": g.user_role,
        "submitted_at_utc": store.now(),
    }, versioned=False))

    services.recompute_record_item_count(protest)
    if (item_type == "AGENCY_REPORT" and g.user_role == "ProcurementOfficer"
            and protest["status"] == "FILED"):
        v.set_field(protest, "status", "UNDER_REVIEW")
    v.touch(protest)
    return ("obj", item, serializers.record_item, 201)


@bp.get("/procurement/protests/<protest_id>/record-items")
@v.endpoint(v.ALL_ROLES)
def list_record_items(protest_id):
    limit, offset = v.pagination()
    protest = services.must("protests", protest_id)
    item_type = v.query("item_type")
    rows = [
        i for i in services.record_items_of(protest)
        if item_type is None or i["item_type"] == item_type
    ]
    page, total = v.paginate(rows, limit, offset)
    return ("list", page, serializers.record_item, limit, offset, total)


# --------------------------------------------------------------------------- #
# hearings on a protest
# --------------------------------------------------------------------------- #

@bp.post("/procurement/protests/<protest_id>/hearings")
@v.endpoint(["HearingOfficer"])
def schedule_hearing(protest_id):
    data = v.body()
    officer_user_id = v.req_str(data, "hearing_officer_user_id")
    start = v.req_dt(data, "scheduled_start_utc")
    end = v.req_dt(data, "scheduled_end_utc")
    room_code = v.req_str(data, "room_code")
    if whole_minutes(start, end) is None:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "the hearing window must end strictly after it starts and span a whole "
            "number of minutes",
        )

    protest = services.must("protests", protest_id)
    solicitation = services.must("solicitations", protest["solicitation_id"])

    if protest["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_PROTEST_STATE")

    if officer_user_id == solicitation["issued_by_user_id"]:
        raise ApiError("ERR_HEARING_OFFICER_CONFLICT")

    if protest["record_item_count"] < 1:
        raise ApiError("ERR_AGENCY_RECORD_INCOMPLETE")

    services.check_hearing_capacity(None, officer_user_id, start, end, room_code)

    hearing = store.insert("hearings", store.row("hearings", {
        "protest_id": protest["id"],
        "hearing_officer_user_id": officer_user_id,
        "scheduled_start_utc": start,
        "scheduled_end_utc": end,
        "room_code": room_code,
        "status": "SCHEDULED",
        "continuance_count": 0,
        "convened_at_utc": None,
        "concluded_at_utc": None,
        "record_items_reviewed_count": 0,
    }))
    v.set_field(protest, "status", "HEARING_SCHEDULED")
    v.touch(protest)
    return ("obj", hearing, serializers.hearing, 201)


@bp.get("/procurement/protests/<protest_id>/hearings")
@v.endpoint(v.ALL_ROLES)
def list_hearings(protest_id):
    limit, offset = v.pagination()
    protest = services.must("protests", protest_id)
    status = v.query("status")
    rows = [
        h for h in services.hearings_of(protest)
        if status is None or h["status"] == status
    ]
    page, total = v.paginate(rows, limit, offset)
    return ("list", page, serializers.hearing, limit, offset, total)


# --------------------------------------------------------------------------- #
# decision, withdrawal and stay override
# --------------------------------------------------------------------------- #

@bp.post("/procurement/protests/<protest_id>/decision")
@v.endpoint(["HearingOfficer"])
def decide_protest(protest_id):
    data = v.body()
    outcome = v.req_enum(data, "outcome", ("SUSTAINED", "DENIED"))
    rationale = v.req_str(data, "rationale")
    remedy_code = v.opt_enum(data, "remedy_code", REMEDIES)
    if outcome == "SUSTAINED" and remedy_code is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", "field 'remedy_code' is required for a sustained protest"
        )

    protest = services.must("protests", protest_id)
    solicitation = services.must("solicitations", protest["solicitation_id"])

    if protest["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_PROTEST_STATE")

    if g.user_id == solicitation["issued_by_user_id"]:
        raise ApiError("ERR_HEARING_OFFICER_CONFLICT")

    if protest["record_item_count"] < 2:
        raise ApiError("ERR_AGENCY_RECORD_INCOMPLETE")

    if not any(h["status"] == "CONCLUDED" for h in services.hearings_of(protest)):
        raise ApiError("ERR_HEARING_NOT_CONCLUDED")

    v.set_field(protest, "status", outcome)
    v.set_field(protest, "decision_outcome", outcome)
    v.set_field(protest, "decided_at_utc", store.now())
    _lift_stay(protest)
    v.touch(protest)

    if outcome == "DENIED":
        v.set_field(protest, "remedy_code", "NONE")
    else:
        v.set_field(protest, "remedy_code", remedy_code)
        _refund(protest, solicitation)
        services.sustained_protest_cascade(solicitation, remedy_code)

    return ("obj", protest, serializers.protest, 200)


@bp.post("/procurement/protests/<protest_id>/withdraw")
@v.endpoint(["Vendor"])
def withdraw_protest(protest_id):
    data = v.body()
    v.opt_str(data, "withdrawal_reason")

    protest = services.must("protests", protest_id)
    if g.user_id != protest["protester_vendor_id"]:
        raise ApiError("ERR_VENDOR_IDENTITY_MISMATCH")
    if protest["status"] not in OPEN_PROTEST_STATUSES:
        raise ApiError("ERR_INVALID_PROTEST_STATE")

    solicitation = services.must("solicitations", protest["solicitation_id"])

    v.set_field(protest, "status", "WITHDRAWN")
    _lift_stay(protest)
    _refund(protest, solicitation)
    for hearing in services.hearings_of(protest):
        if hearing["status"] == "SCHEDULED":
            v.set_field(hearing, "status", "CANCELLED")
    v.touch(protest)
    return ("obj", protest, serializers.protest, 200)


@bp.post("/procurement/protests/<protest_id>/stay-override")
@v.endpoint(["ProcurementOfficer"])
def override_stay(protest_id):
    data = v.body()
    v.req_str(data, "urgency_justification")

    protest = services.must("protests", protest_id)
    if protest["status"] not in OPEN_PROTEST_STATUSES:
        raise ApiError("ERR_INVALID_PROTEST_STATE")
    if protest["stay_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_PROTEST_STATE", "the protest carries no active stay")

    v.set_field(protest, "stay_status", "OVERRIDDEN")
    v.touch(protest)
    return ("obj", protest, serializers.protest, 200)
