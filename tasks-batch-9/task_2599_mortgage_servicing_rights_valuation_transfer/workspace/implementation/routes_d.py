"""Purchase agreements, agency/investor approvals, settlement, holdback money."""
from datetime import timedelta

from flask import Blueprint

import calcs
import cascades
import serial
from core import (DB, READ_AGR, READ_APR, R_APPROVER, R_COMPLIANCE, R_TXN, authenticate,
                  body_of, f_date, f_enum, f_id, f_int, f_str, fail, filter_eq, lookup,
                  new_row, no_body, now_date, now_iso, ok, paginate, rows, sort_created,
                  touch)

bp = Blueprint("group_d", __name__)

SETTLEABLE = ("PENDING_APPROVALS", "APPROVED", "CONDITIONALLY_APPROVED")


def agreement_requests(agreement_id):
    return sort_created([r for r in rows("approval_requests")
                         if r["purchase_agreement_id"] == agreement_id])


def agreement_portfolio(agreement):
    package = DB["bid_packages"][agreement["bid_package_id"]]
    return DB["portfolios"][package["portfolio_id"]]


def agreement_transfer(agreement_id):
    matches = [t for t in rows("transfers") if t["purchase_agreement_id"] == agreement_id]
    return sort_created(matches)[0] if matches else None


def recount_approvals(agreement):
    requests = agreement_requests(agreement["id"])
    agreement["approval_pending_count"] = len([r for r in requests if r["status"] == "PENDING"])
    agreement["condition_count"] = len([r for r in requests
                                        if r["status"] == "CONDITIONALLY_APPROVED"])


# ---------------------------------------------------------------- reads
@bp.get("/msr/purchase-agreements/<agr_id>")
def get_agreement(agr_id):
    authenticate(READ_AGR)
    row = lookup("agreements", agr_id, "ERR_PURCHASE_AGREEMENT_NOT_FOUND")
    return ok(serial.ser_agreement(row))


@bp.get("/msr/purchase-agreements")
def list_agreements():
    authenticate(READ_AGR)
    items = sort_created(rows("agreements"))
    items = filter_eq(items, "bid_package_id")
    items = filter_eq(items, "winning_bid_id")
    items = filter_eq(items, "buyer_id")
    items = filter_eq(items, "status")
    return paginate(items, serial.ser_agreement)


# ---------------------------------------------------------------- approvals
@bp.post("/msr/purchase-agreements/<agr_id>/approval-requests")
def create_approval_request(agr_id):
    authenticate(R_TXN)
    body = body_of("approver_type", "agency_type")
    approver_type = f_enum(body, "approver_type", ("AGENCY", "INVESTOR"))
    agency_type = f_enum(body, "agency_type", ("FNMA", "FHLMC", "GNMA"), required=False)
    if approver_type == "AGENCY" and agency_type is None:
        fail("ERR_INVALID_REQUEST", "agency_type is required for an AGENCY approval request")
    if approver_type == "INVESTOR" and agency_type is not None:
        fail("ERR_INVALID_REQUEST", "agency_type must be omitted for an INVESTOR request")

    agreement = lookup("agreements", agr_id, "ERR_PURCHASE_AGREEMENT_NOT_FOUND")
    if agreement["status"] != "DRAFTED":
        fail("ERR_AGREEMENT_INVALID_STATE",
             "approval requests may only be raised while the agreement is DRAFTED")
    if approver_type == "AGENCY":
        portfolio = agreement_portfolio(agreement)
        if agency_type != portfolio["agency_type"]:
            fail("ERR_INVALID_REQUEST",
                 "agency_type must equal the selling portfolio's agency_type")
    for existing in agreement_requests(agr_id):
        if (existing["approver_type"] == approver_type
                and existing["agency_type"] == agency_type):
            fail("ERR_DUPLICATE_APPROVAL_REQUEST",
                 "an approval request of that kind already exists on this agreement")

    row = new_row("approval_requests")
    row.update({"purchase_agreement_id": agr_id, "approver_type": approver_type,
                "agency_type": agency_type, "status": "PENDING", "condition_text": None,
                "decided_by_user_id": None, "decided_at": None})
    return ok(serial.ser_approval_request(row), 201)


@bp.get("/msr/purchase-agreements/<agr_id>/approval-requests")
def list_approval_requests(agr_id):
    authenticate(READ_AGR)
    lookup("agreements", agr_id, "ERR_PURCHASE_AGREEMENT_NOT_FOUND")
    items = agreement_requests(agr_id)
    items = filter_eq(items, "status")
    items = filter_eq(items, "approver_type")
    return paginate(items, serial.ser_approval_request)


@bp.get("/msr/approval-requests/<req_id>")
def get_approval_request(req_id):
    authenticate(READ_APR)
    row = lookup("approval_requests", req_id, "ERR_APPROVAL_REQUEST_NOT_FOUND")
    return ok(serial.ser_approval_request(row))


@bp.post("/msr/purchase-agreements/<agr_id>/submit-for-approval")
def submit_for_approval(agr_id):
    authenticate(R_TXN)
    no_body()
    agreement = lookup("agreements", agr_id, "ERR_PURCHASE_AGREEMENT_NOT_FOUND")
    if agreement["status"] != "DRAFTED":
        fail("ERR_AGREEMENT_INVALID_STATE", "only a DRAFTED agreement can be submitted")
    requests = agreement_requests(agr_id)
    if not requests or any(r["status"] != "PENDING" for r in requests):
        fail("ERR_AGREEMENT_INVALID_STATE",
             "submission requires at least one approval request, all still PENDING")
    recount_approvals(agreement)
    agreement["status"] = "PENDING_APPROVALS"
    touch(agreement)
    return ok(serial.ser_agreement(agreement))


@bp.post("/msr/approval-requests/<req_id>/decide")
def decide_approval(req_id):
    user_id, _ = authenticate(R_APPROVER)
    body = body_of("decision", "condition_text")
    decision = f_enum(body, "decision", ("APPROVED", "CONDITIONALLY_APPROVED", "DENIED"))
    condition_text = f_str(body, "condition_text", required=False, max_len=None)
    if decision == "CONDITIONALLY_APPROVED" and condition_text is None:
        fail("ERR_INVALID_REQUEST",
             "condition_text is required for a CONDITIONALLY_APPROVED decision")
    if decision != "CONDITIONALLY_APPROVED" and condition_text is not None:
        fail("ERR_INVALID_REQUEST", "condition_text is only permitted with a conditional approval")

    request_row = lookup("approval_requests", req_id, "ERR_APPROVAL_REQUEST_NOT_FOUND")
    agreement = DB["agreements"][request_row["purchase_agreement_id"]]
    if agreement["status"] != "PENDING_APPROVALS":
        fail("ERR_AGREEMENT_INVALID_STATE",
             "decisions are only accepted while the agreement is PENDING_APPROVALS")
    if request_row["status"] != "PENDING":
        fail("ERR_APPROVAL_ALREADY_DECIDED", "this approval request has already been decided")
    for sibling in agreement_requests(agreement["id"]):
        if sibling["id"] == req_id or sibling["decided_by_user_id"] is None:
            continue
        if sibling["decided_by_user_id"] == user_id:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "this operator has already decided an approval on this agreement")

    request_row["status"] = decision
    request_row["condition_text"] = condition_text
    request_row["decided_by_user_id"] = user_id
    request_row["decided_at"] = now_iso()
    touch(request_row)

    recount_approvals(agreement)
    requests = agreement_requests(agreement["id"])
    if any(r["status"] == "DENIED" for r in requests):
        cascades.terminate_agreement_cascade(agreement)
        return ok(serial.ser_approval_request(request_row))

    if agreement["approval_pending_count"] == 0:
        if agreement["condition_count"] == 0:
            agreement["status"] = "APPROVED"
        else:
            agreement["status"] = "CONDITIONALLY_APPROVED"
            calcs.resize_holdback_conditional(agreement)
        touch(agreement)
    else:
        touch(agreement)
    return ok(serial.ser_approval_request(request_row))


# ---------------------------------------------------------------- settlement
@bp.post("/msr/purchase-agreements/<agr_id>/settle")
def settle(agr_id):
    authenticate(R_TXN)
    body = body_of("sale_date", "transfer_date", "condition_waiver_reference")
    sale_date = f_date(body, "sale_date")
    transfer_date = f_date(body, "transfer_date")
    waiver = f_str(body, "condition_waiver_reference", required=False, max_len=None)

    agreement = lookup("agreements", agr_id, "ERR_PURCHASE_AGREEMENT_NOT_FOUND")
    if agreement["status"] not in SETTLEABLE:
        fail("ERR_AGREEMENT_INVALID_STATE", "this agreement cannot be settled from its state")
    if agreement["approval_pending_count"] > 0:
        fail("ERR_AGENCY_APPROVAL_PENDING", "approval decisions are still outstanding")
    if agreement["status"] == "CONDITIONALLY_APPROVED":
        if waiver is None or waiver.strip() == "":
            fail("ERR_CONDITION_WAIVER_REQUIRED",
                 "a conditionally approved sale requires a condition_waiver_reference")
    elif waiver is not None:
        fail("ERR_INVALID_REQUEST",
             "condition_waiver_reference is only permitted on a conditionally approved sale")

    if transfer_date < now_date() + timedelta(days=15) or sale_date > transfer_date:
        fail("ERR_TRANSFER_DATE_TOO_SOON",
             "transfer_date must be at least 15 days out and not precede sale_date")

    window_start = transfer_date - timedelta(days=30)
    window_end = transfer_date + timedelta(days=30)
    for other in rows("transfers"):
        if other["status"] != "IN_PROGRESS":
            continue
        other_agreement = DB["agreements"].get(other["purchase_agreement_id"])
        if other_agreement is None or other_agreement["buyer_id"] != agreement["buyer_id"]:
            continue
        if (window_start <= other["onboarding_window_end"]
                and other["onboarding_window_start"] <= window_end):
            fail("ERR_ONBOARDING_CAPACITY_EXCEEDED",
                 "the buyer already onboards a transfer in this window")

    agreement["sale_date"] = sale_date
    agreement["transfer_date"] = transfer_date
    agreement["holdback_release_eligible_at"] = (
        transfer_date + timedelta(days=agreement["rep_warrant_days"]))
    agreement["condition_waiver_reference"] = waiver
    agreement["holdback_retained_cents"] = agreement["holdback_cents"]
    agreement["holdback_released_cents"] = 0
    agreement["holdback_applied_cents"] = 0
    agreement["settlement_wire_cents"] = (agreement["purchase_price_cents"]
                                          - agreement["holdback_cents"])
    agreement["status"] = "SETTLED"
    touch(agreement)

    transfer = new_row("transfers")
    transfer.update({"purchase_agreement_id": agr_id, "transfer_date": transfer_date,
                     "notice_status": "NOT_STARTED", "data_status": "NOT_STARTED",
                     "pipeline_status": "NOT_STARTED", "readiness": "NOT_READY",
                     "status": "IN_PROGRESS", "mapping_scheme": None,
                     "escrow_transferred_cents": 0, "suspense_transferred_cents": 0,
                     "loss_mit_pipeline_count": 0, "transferred_loan_count": 0,
                     "onboarding_window_start": window_start,
                     "onboarding_window_end": window_end,
                     "notice_count": 0, "late_notice_count": 0,
                     "notice_attested_at": None, "reconciled_at": None,
                     "notice_attested_by_user_id": None, "completed_at": None})
    return ok(serial.ser_agreement(agreement))


# ---------------------------------------------------------------- holdback money
@bp.post("/msr/purchase-agreements/<agr_id>/holdback-releases")
def release_holdback(agr_id):
    user_id, _ = authenticate(R_COMPLIANCE)
    body = body_of("expected_purchase_agreement_version")
    expected = f_int(body, "expected_purchase_agreement_version", minimum=0)

    agreement = lookup("agreements", agr_id, "ERR_PURCHASE_AGREEMENT_NOT_FOUND")
    if agreement["status"] not in ("SETTLED", "HOLDBACK_RELEASED"):
        fail("ERR_AGREEMENT_INVALID_STATE",
             "holdback releases require a SETTLED or HOLDBACK_RELEASED agreement")
    if expected != agreement["version"]:
        fail("ERR_STALE_AGREEMENT_VERSION",
             "expected_purchase_agreement_version does not match the stored version")

    transfer = agreement_transfer(agr_id)
    if transfer is not None and transfer["notice_attested_by_user_id"] == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "the officer who attested the notices may not release the holdback")

    eligible_at = agreement["holdback_release_eligible_at"]
    if (transfer is None or transfer["status"] != "COMPLETED"
            or eligible_at is None or now_date() < eligible_at):
        fail("ERR_HOLDBACK_NOT_ELIGIBLE",
             "the transfer is not complete or the rep-and-warrant period has not elapsed")

    outcome = calcs.complaint_release(agreement, transfer)
    if agreement["holdback_retained_cents"] <= 0:
        fail("ERR_HOLDBACK_EXHAUSTED", "no holdback remains to release")

    agreement["holdback_retained_cents"] -= outcome["gross"]
    agreement["holdback_released_cents"] += outcome["net"]
    agreement["holdback_applied_cents"] += outcome["charge"]

    terminal = (agreement["holdback_retained_cents"] == 0
                and agreement["transfer_date"] is not None
                and now_date() >= agreement["transfer_date"]
                + timedelta(days=agreement["indemnification_days"]))
    agreement["status"] = "CLOSED" if terminal else "HOLDBACK_RELEASED"
    touch(agreement)
    return ok(serial.ser_agreement(agreement))


@bp.post("/msr/purchase-agreements/<agr_id>/holdback-clawbacks")
def clawback_holdback(agr_id):
    authenticate(R_COMPLIANCE)
    body = body_of("amount_cents", "reason")
    amount = f_int(body, "amount_cents")
    f_str(body, "reason", max_len=None)

    agreement = lookup("agreements", agr_id, "ERR_PURCHASE_AGREEMENT_NOT_FOUND")
    if agreement["status"] != "HOLDBACK_RELEASED":
        fail("ERR_AGREEMENT_INVALID_STATE",
             "clawbacks require a HOLDBACK_RELEASED agreement")
    if amount <= 0 or amount > agreement["holdback_released_cents"]:
        fail("ERR_CLAWBACK_EXCEEDS_RELEASED",
             "clawback amount must be positive and no greater than the released holdback")

    agreement["holdback_released_cents"] -= amount
    agreement["holdback_retained_cents"] += amount
    if agreement["holdback_released_cents"] == 0:
        agreement["status"] = "SETTLED"
    touch(agreement)
    return ok(serial.ser_agreement(agreement))
