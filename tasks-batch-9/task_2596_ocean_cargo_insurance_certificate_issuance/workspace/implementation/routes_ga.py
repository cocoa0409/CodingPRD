"""General average: declaration, contribution allocation, security and release."""
from decimal import Decimal

from flask import Blueprint

import clock
import serialize
import services
from errors import ApiError, require_state
from response import array_response, object_response
from store import db, new_row, ordered, touch
from validation import (D, authenticate, body, get_decimal, get_dt, get_int, get_str,
                        pagination, paginate, q2, query_enum, query_str)

bp = Blueprint("ga", __name__)

GA_STATUSES = ("DECLARED", "SECURITY_COLLECTING", "SECURITY_COMPLETE", "ADJUSTED")
POSTING_STATUSES = ("REQUIRED", "POSTED", "RELEASED")
GA_READ_ROLES = ("ClaimsAdjuster", "Underwriter", "Assured", "ComplianceOfficer",
                 "PlatformAdmin")


@bp.post("/ga-events")
def create_ga_event():
    authenticate(("ClaimsAdjuster",))
    payload = body()
    vessel_id = get_str(payload, "vessel_id")
    voyage_sailing_date = get_dt(payload, "voyage_sailing_date")
    declaration_date = get_dt(payload, "declaration_date")
    average_adjuster_name = get_str(payload, "average_adjuster_name")
    sacrifice_amount = get_decimal(payload, "sacrifice_amount", minimum=0)
    salvage_award_amount = get_decimal(payload, "salvage_award_amount", required=False,
                                       default=Decimal("0.00"), minimum=0)
    vessel = services.find(db.vessels, vessel_id, "ERR_VESSEL_NOT_FOUND")

    row = new_row()
    row.update({
        "vessel_id": vessel["id"],
        "voyage_sailing_date": voyage_sailing_date,
        "declaration_date": declaration_date,
        "average_adjuster_name": average_adjuster_name,
        "sacrifice_amount": sacrifice_amount,
        "salvage_award_amount": salvage_award_amount,
        "adjuster_fee_amount": None,
        "total_allowance_amount": None,
        "total_contributory_value": None,
        "contribution_rate": None,
        "postings_required_count": 0,
        "postings_posted_count": 0,
        "status": "DECLARED",
    })
    db.ga_events[row["id"]] = row

    vessel["open_ga_event_count"] += 1
    if vessel["status"] in ("APPROVED", "OVERAGE_SURCHARGED"):
        vessel["status"] = "GA_HOLD"
    touch(vessel)
    return object_response(serialize.ga_event(row), 201)


@bp.get("/ga-events/<event_id>")
def read_ga_event(event_id):
    authenticate(GA_READ_ROLES)
    event = services.find(db.ga_events, event_id, "ERR_GA_EVENT_NOT_FOUND")
    return object_response(serialize.ga_event(event))


@bp.get("/ga-events")
def list_ga_events():
    authenticate(GA_READ_ROLES)
    limit, offset = pagination()
    vessel_id = query_str("vessel_id")
    status = query_enum("status", GA_STATUSES)
    rows = [r for r in db.ga_events.values()
            if (vessel_id is None or r["vessel_id"] == vessel_id)
            and (status is None or r["status"] == status)]
    page, limit, offset, total = paginate(ordered(rows), limit, offset, serialize.ga_event)
    return array_response(page, limit, offset, total)


@bp.post("/ga-events/<event_id>/issue-security-calls")
def issue_security_calls(event_id):
    authenticate(("ClaimsAdjuster",))
    event = services.find(db.ga_events, event_id, "ERR_GA_EVENT_NOT_FOUND")
    require_state("GeneralAverageEvent", "status", event["status"], ("DECLARED",))
    contributors = services.ga_contributors(event)
    if not contributors:
        raise ApiError("ERR_NO_CONTRIBUTING_CERTIFICATES")
    amounts = services.allocate_ga_contributions(event, contributors)
    postings = services.create_ga_postings(event, contributors, amounts)
    event["postings_required_count"] = len(postings)
    event["postings_posted_count"] = 0
    event["status"] = "SECURITY_COLLECTING"
    touch(event)
    return object_response(serialize.ga_event(event))


@bp.post("/ga-events/<event_id>/finalize-adjustment")
def finalize_adjustment(event_id):
    authenticate(("ClaimsAdjuster",))
    event = services.find(db.ga_events, event_id, "ERR_GA_EVENT_NOT_FOUND")
    require_state("GeneralAverageEvent", "status", event["status"], ("SECURITY_COMPLETE",))
    event["status"] = "ADJUSTED"
    for posting in ordered(list(db.ga_postings.values())):
        if posting["ga_event_id"] != event["id"] or posting["status"] != "POSTED":
            continue
        posting["status"] = "RELEASED"
        touch(posting)
        deposit = D(posting["cash_deposit_amount"] or 0)
        cert = db.certificates.get(posting["certificate_id"])
        if cert is not None and deposit:
            policy = services.policy_of(cert)
            policy["security_deposit_held_amount"] = q2(
                D(policy["security_deposit_held_amount"]) - deposit)
            touch(policy)
    vessel = db.vessels.get(event["vessel_id"])
    if vessel is not None:
        vessel["open_ga_event_count"] = max(0, vessel["open_ga_event_count"] - 1)
        if vessel["open_ga_event_count"] == 0 and vessel["status"] == "GA_HOLD":
            vessel["status"] = ("OVERAGE_SURCHARGED"
                                if D(vessel["overage_surcharge_pct"]) > 0
                                else "APPROVED")
        touch(vessel)
    touch(event)
    return object_response(serialize.ga_event(event))


# ========================== GaSecurityPosting ============================== #
@bp.get("/ga-security-postings")
def list_ga_postings():
    authenticate(GA_READ_ROLES)
    limit, offset = pagination()
    ga_event_id = query_str("ga_event_id")
    certificate_id = query_str("certificate_id")
    status = query_enum("status", POSTING_STATUSES)
    rows = [r for r in db.ga_postings.values()
            if (ga_event_id is None or r["ga_event_id"] == ga_event_id)
            and (certificate_id is None or r["certificate_id"] == certificate_id)
            and (status is None or r["status"] == status)]
    page, limit, offset, total = paginate(ordered(rows), limit, offset, serialize.ga_posting)
    return array_response(page, limit, offset, total)


@bp.get("/ga-security-postings/<posting_id>")
def read_ga_posting(posting_id):
    authenticate(GA_READ_ROLES)
    posting = services.find(db.ga_postings, posting_id, "ERR_GA_POSTING_NOT_FOUND")
    return object_response(serialize.ga_posting(posting))


@bp.post("/ga-security-postings/<posting_id>/post")
def post_security(posting_id):
    user_id, _role = authenticate(("Assured",))
    payload = body()
    expected_version = get_int(payload, "expected_ga_event_version", minimum=0)
    guarantee_amount = get_decimal(payload, "guarantee_amount", minimum=0)
    cash_deposit_amount = get_decimal(payload, "cash_deposit_amount", minimum=0)
    posting = services.find(db.ga_postings, posting_id, "ERR_GA_POSTING_NOT_FOUND")
    cert = db.certificates[posting["certificate_id"]]
    policy = services.policy_of(cert)
    if user_id != policy["id"]:
        raise ApiError("ERR_OWNERSHIP_MISMATCH")

    event = db.ga_events[posting["ga_event_id"]]
    require_state("GaSecurityPosting", "status", posting["status"], ("REQUIRED",))
    if event["status"] != "SECURITY_COLLECTING":
        raise ApiError("ERR_INVALID_STATE")
    if expected_version != event["version"]:
        raise ApiError("ERR_STALE_GA_EVENT_VERSION")
    if guarantee_amount < D(posting["contribution_amount"]):
        raise ApiError("ERR_SECURITY_AMOUNT_INSUFFICIENT")
    if cash_deposit_amount < D(posting["cash_deposit_expected_amount"]):
        raise ApiError("ERR_SECURITY_AMOUNT_INSUFFICIENT")

    posting["status"] = "POSTED"
    posting["guarantee_amount"] = guarantee_amount
    posting["cash_deposit_amount"] = cash_deposit_amount
    touch(posting)

    policy["security_deposit_held_amount"] = q2(
        D(policy["security_deposit_held_amount"]) + cash_deposit_amount)
    touch(policy)

    event["postings_posted_count"] += 1
    if event["postings_posted_count"] >= event["postings_required_count"]:
        event["status"] = "SECURITY_COMPLETE"
    touch(event)
    return object_response(serialize.ga_posting(posting))
