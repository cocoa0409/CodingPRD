"""Refund claims: intake, adjudication, settlement and reversal (PRD section 3.9)."""

from flask import Blueprint

import calc
import db
import middleware as mw
import response
import services as svc
import validators as v
from errors import fail
from middleware import (
    ROLE_ADVERTISER,
    ROLE_DISPUTE_OFFICER,
    ROLE_PLATFORM_ADMIN,
    ROLE_PUBLISHER,
)
from routes.helpers import build_filters, filtered, respond_list

bp = Blueprint("claims", __name__)

CLAIM_READERS = (ROLE_PLATFORM_ADMIN, ROLE_ADVERTISER, ROLE_PUBLISHER, ROLE_DISPUTE_OFFICER)
CLAIM_BATCH_IDS_MAX = 20
CLAIMABLE_SCORING = ("QUARANTINED", "DECERTIFIED")
LIVE_APPEAL_STATES = ("FILED", "MORE_EVIDENCE_REQUIRED")


def _own_claim(caller, claim):
    if claim is None:
        return
    mw.own_publisher(caller, claim["publisher_id"])
    mw.own_campaign(caller, db.campaigns.get(claim["campaign_id"]))


@bp.post("/refund-claims")
def create_claim():
    caller = mw.require(ROLE_ADVERTISER)
    payload = mw.body()
    # priority 3 then priority 5
    campaign = svc.find(db.campaigns, payload.get("campaign_id"))
    mw.own_campaign(caller, campaign)
    if campaign is None:
        fail("ERR_CAMPAIGN_NOT_FOUND")
    publisher = svc.require_ref(
        db.publishers, payload.get("publisher_id"), "ERR_PUBLISHER_NOT_FOUND"
    )
    raw_ids = payload.get("batch_ids")
    if isinstance(raw_ids, list):
        for candidate in raw_ids:
            if isinstance(candidate, str) and candidate not in db.measurement_batches:
                fail("ERR_MEASUREMENT_BATCH_NOT_FOUND")
    # priority 6 -- request well-formedness
    batch_ids = v.req_str_list(
        payload, "batch_ids", min_items=1, max_items=CLAIM_BATCH_IDS_MAX, distinct=True
    )
    expected_campaign_version = v.req_int(payload, "expected_campaign_version", minimum=0)
    # priority 9 -- campaign version
    if expected_campaign_version != int(campaign["version"]):
        fail("ERR_STALE_CAMPAIGN_VERSION")
    batches = [db.measurement_batches[bid] for bid in batch_ids]
    # priority 15 -- batch scope
    for batch in batches:
        if batch["campaign_id"] != campaign["id"] or batch["publisher_id"] != publisher["id"]:
            fail("ERR_BATCH_SCOPE_MISMATCH")
    # priority 16 -- batch claimability
    for batch in batches:
        if batch["scoring_status"] not in CLAIMABLE_SCORING:
            fail("ERR_BATCH_NOT_CLAIMABLE")
    # priority 17 -- batch availability
    for batch in batches:
        if batch["settlement_status"] != "UNBILLED":
            fail("ERR_BATCH_ALREADY_CLAIMED")
    # priority 33 -- the 30 day claim filing window
    latest_end = None
    for batch in batches:
        window_end = db.parse_dt(batch["window_end"])
        if window_end is not None and (latest_end is None or window_end > latest_end):
            latest_end = window_end
    if latest_end is not None and db.clock_now() > latest_end + db.days(
        calc.CLAIM_FILING_WINDOW_DAYS
    ):
        fail("ERR_CLAIM_WINDOW_CLOSED")
    record = db.new_record(
        {
            "campaign_id": campaign["id"],
            "publisher_id": publisher["id"],
            "batch_ids": list(batch_ids),
            "claim_state": "SUBMITTED",
            "claimed_impressions": 0,
            "provisional_credit_cents": 0,
            "credited_impressions": None,
            "gross_credit_cents": None,
            "admin_fee_rate": None,
            "admin_fee_cents": None,
            "net_credit_cents": None,
            "decided_by_user_id": None,
            "decision_note": None,
            "reject_reason_code": None,
            "reversal_reason": None,
        }
    )
    db.refund_claims[record["id"]] = record
    svc.refresh_provisional(record)
    for batch in svc.cited_batches(record):
        batch["settlement_status"] = "CLAIMED"
        db.touch(batch)
    campaign["open_claim_count"] = int(campaign["open_claim_count"]) + 1
    db.touch(campaign)
    return response.object_response(record, 201)


@bp.get("/refund-claims/<claim_id>")
def read_claim(claim_id):
    caller = mw.require(*CLAIM_READERS)
    record = svc.find(db.refund_claims, claim_id)
    _own_claim(caller, record)
    if record is None:
        fail("ERR_REFUND_CLAIM_NOT_FOUND")
    return response.object_response(record)


@bp.get("/refund-claims")
def list_claims():
    caller = mw.require(*CLAIM_READERS)
    predicates = build_filters(
        {
            "campaign_id": "campaign_id",
            "publisher_id": "publisher_id",
            "claim_state": "claim_state",
            "reject_reason_code": "reject_reason_code",
        }
    )
    cited = mw.query("batch_id") or mw.query("batch_ids")
    if cited is not None:
        predicates.append(lambda record: cited in record["batch_ids"])
    if caller.is_publisher:
        predicates.append(lambda record: record["publisher_id"] == caller.user_id)
    if caller.is_advertiser:
        owned = set(
            campaign["id"]
            for campaign in db.campaigns.values()
            if campaign["advertiser_id"] == caller.user_id
        )
        predicates.append(lambda record: record["campaign_id"] in owned)
    return respond_list(filtered(db.refund_claims, predicates))


# --------------------------------------------------------------------------- #
# adjudication                                                                #
# --------------------------------------------------------------------------- #
def _live_appeal_on_cited_page(claim):
    pages = set()
    for batch in svc.cited_batches(claim):
        pages.add(batch["page_id"])
    if not pages:
        return False
    for appeal in db.appeals.values():
        if appeal["appeal_state"] not in LIVE_APPEAL_STATES:
            continue
        classification = db.page_classifications.get(appeal["classification_id"])
        if classification is not None and classification["page_id"] in pages:
            return True
    return False


@bp.post("/refund-claims/<claim_id>/review")
def review_claim(claim_id):
    caller = mw.require(ROLE_DISPUTE_OFFICER)
    record = svc.require_path(db.refund_claims, claim_id, "ERR_REFUND_CLAIM_NOT_FOUND")
    mw.body()
    # priority 7 -- state reachability
    if record["claim_state"] != "SUBMITTED":
        fail("ERR_INVALID_CLAIM_STATE")
    # the tier that decides the defect test must not be under dispute
    if _live_appeal_on_cited_page(record):
        fail("ERR_APPEAL_PENDING")
    record["claim_state"] = "UNDER_REVIEW"
    svc.refresh_provisional(record)
    db.touch(record)
    return response.object_response(record)


@bp.post("/refund-claims/<claim_id>/approve")
def approve_claim(claim_id):
    caller = mw.require(ROLE_DISPUTE_OFFICER)
    record = svc.require_path(db.refund_claims, claim_id, "ERR_REFUND_CLAIM_NOT_FOUND")
    payload = mw.body()
    decision_note = v.opt_string(payload, "decision_note")
    # priority 7 -- state reachability
    if record["claim_state"] != "UNDER_REVIEW":
        fail("ERR_INVALID_CLAIM_STATE")
    advertiser_id = None
    campaign = db.campaigns.get(record["campaign_id"])
    if campaign is not None:
        advertiser_id = campaign["advertiser_id"]
    advertiser = db.advertisers.get(advertiser_id)
    publisher = db.publishers.get(record["publisher_id"])
    # the pinned evaluation order: credited_impressions, gross, rate, fee, net
    credited_impressions, gross_credit_cents = svc.compute_basis(record, "net")
    admin_fee_rate, admin_fee_cents, net_credit_cents = calc.admin_fee(gross_credit_cents)
    # priority 34 -- the advertiser's lifetime credit cap
    if advertiser is not None:
        projected = int(advertiser["credit_received_cents_total"]) + net_credit_cents
        if projected > int(advertiser["credit_cap_cents"]):
            fail("ERR_CREDIT_CAP_EXCEEDED")
    # priority 35 -- a claim with no creditable impressions must be rejected
    if credited_impressions == 0:
        fail("ERR_NO_CREDITABLE_IMPRESSIONS")
    record["credited_impressions"] = credited_impressions
    record["gross_credit_cents"] = gross_credit_cents
    record["admin_fee_rate"] = calc.plain(admin_fee_rate)
    record["admin_fee_cents"] = admin_fee_cents
    record["net_credit_cents"] = net_credit_cents
    record["claim_state"] = "APPROVED"
    record["decided_by_user_id"] = caller.user_id
    record["decision_note"] = decision_note
    db.touch(record)
    # the double-entry credit ledger
    if advertiser is not None:
        advertiser["credit_received_cents_total"] = int(
            advertiser["credit_received_cents_total"]
        ) + net_credit_cents
        advertiser["settled_claim_count"] = int(advertiser["settled_claim_count"]) + 1
        db.touch(advertiser)
    if publisher is not None:
        publisher["credit_issued_cents_total"] = int(
            publisher["credit_issued_cents_total"]
        ) + net_credit_cents
        db.touch(publisher)
    for batch in svc.cited_batches(record):
        if batch["settlement_status"] == "CLAIMED":
            batch["settlement_status"] = "CREDITED"
            db.touch(batch)
    if campaign is not None:
        campaign["open_claim_count"] = max(0, int(campaign["open_claim_count"]) - 1)
        db.touch(campaign)
    return response.object_response(record)


@bp.post("/refund-claims/<claim_id>/reject")
def reject_claim(claim_id):
    caller = mw.require(ROLE_DISPUTE_OFFICER)
    record = svc.require_path(db.refund_claims, claim_id, "ERR_REFUND_CLAIM_NOT_FOUND")
    payload = mw.body()
    reject_reason_code = v.req_enum(payload, "reject_reason_code", calc.REJECT_REASON_CLIENT)
    decision_note = v.opt_string(payload, "decision_note")
    # priority 7 -- state reachability
    if record["claim_state"] != "UNDER_REVIEW":
        fail("ERR_INVALID_CLAIM_STATE")
    record["claim_state"] = "REJECTED"
    record["reject_reason_code"] = reject_reason_code
    record["decided_by_user_id"] = caller.user_id
    record["decision_note"] = decision_note
    db.touch(record)
    for batch in svc.cited_batches(record):
        if batch["settlement_status"] == "CLAIMED":
            batch["settlement_status"] = "CLOSED_NO_CREDIT"
            db.touch(batch)
    campaign = db.campaigns.get(record["campaign_id"])
    if campaign is not None:
        campaign["open_claim_count"] = max(0, int(campaign["open_claim_count"]) - 1)
        db.touch(campaign)
    return response.object_response(record)


@bp.post("/refund-claims/<claim_id>/reverse")
def reverse_claim(claim_id):
    mw.require(ROLE_PLATFORM_ADMIN)
    record = svc.require_path(db.refund_claims, claim_id, "ERR_REFUND_CLAIM_NOT_FOUND")
    payload = mw.body()
    reversal_reason = v.req_string(payload, "reversal_reason", 1, 500)
    # priority 7 -- state reachability
    if record["claim_state"] != "APPROVED":
        fail("ERR_INVALID_CLAIM_STATE")
    net_credit_cents = int(record["net_credit_cents"] or 0)
    record["claim_state"] = "REVERSED"
    record["reversal_reason"] = reversal_reason
    db.touch(record)
    campaign = db.campaigns.get(record["campaign_id"])
    advertiser = db.advertisers.get(campaign["advertiser_id"]) if campaign else None
    publisher = db.publishers.get(record["publisher_id"])
    if advertiser is not None:
        advertiser["credit_received_cents_total"] = int(
            advertiser["credit_received_cents_total"]
        ) - net_credit_cents
        advertiser["settled_claim_count"] = max(0, int(advertiser["settled_claim_count"]) - 1)
        db.touch(advertiser)
    if publisher is not None:
        publisher["credit_issued_cents_total"] = int(
            publisher["credit_issued_cents_total"]
        ) - net_credit_cents
        db.touch(publisher)
    for batch in svc.cited_batches(record):
        if batch["settlement_status"] == "CREDITED":
            batch["settlement_status"] = "UNBILLED"
            db.touch(batch)
    # open_claim_count is deliberately left alone: it was decremented at approval
    return response.object_response(record)
