"""ExpenseReport routes: create, get, list, submit, decision, reopen.

Decision branches APPROVE / REJECT / RETURN with cascades (PRD 3.8).
"""
from flask import Blueprint, request, g

from common import (get_json_body, require_fields, require_string,
                    require_enum, paginate, list_response)
from db import store, base_fields, touch
from errors import err
from middleware import require_roles
from response import success
from services import (get_or_404, report_lines, recompute_report_totals,
                      recompute_card, recompute_trip_ledger)

bp = Blueprint("reports", __name__)

PER_DIEM_METHODS = {"PER_DIEM", "ITEMIZED"}


def _report_view(r):
    return dict(r)


def _report_trip(report):
    return store.trip_requests.get(report["trip_request_id"])


def _owns_report(report):
    trip = _report_trip(report)
    return trip is not None and trip["traveler_id"] == g.user_id


def _approver_manages(report):
    trip = _report_trip(report)
    if trip is None:
        return False
    traveler = store.travelers.get(trip["traveler_id"])
    return traveler is not None and traveler["manager_id"] == g.user_id


@bp.route("/expense-reports", methods=["POST"])
@require_roles("Traveler")
def create_report():
    body = get_json_body()
    require_fields(body, ["trip_request_id", "title"])
    trip_request_id = require_string(body, "trip_request_id")
    # FK existence
    trip = get_or_404(store.trip_requests, trip_request_id)
    # ownership: acting Traveler owns the trip
    if trip["traveler_id"] != g.user_id:
        raise err("ERR_NOT_OWNER", "Traveler does not own this trip")
    title = require_string(body, "title")
    per_diem_method = "PER_DIEM"
    if "per_diem_method" in body and body["per_diem_method"] is not None:
        per_diem_method = require_enum(body, "per_diem_method", PER_DIEM_METHODS)
    r = base_fields()
    r.update({
        "trip_request_id": trip_request_id,
        "title": title,
        "per_diem_method": per_diem_method,
        "meal_reimbursable_cents": None,
        "total_reimbursable_cents": None,
        "return_reason": None,
        "status": "DRAFT",
    })
    store.expense_reports[r["id"]] = r
    return success(_report_view(r), status=201)


@bp.route("/expense-reports/<report_id>", methods=["GET"])
@require_roles("FinanceAdmin", "Traveler", "Approver")
def get_report(report_id):
    r = get_or_404(store.expense_reports, report_id)
    return success(_report_view(r))


@bp.route("/expense-reports", methods=["GET"])
@require_roles("FinanceAdmin", "Traveler", "Approver")
def list_reports():
    limit, offset = paginate()
    items = list(store.expense_reports.values())
    trip_request_id = request.args.get("trip_request_id")
    if trip_request_id is not None:
        items = [r for r in items if r["trip_request_id"] == trip_request_id]
    page, pagination = list_response(items, limit, offset)
    return success([_report_view(r) for r in page], pagination=pagination)


@bp.route("/expense-reports/<report_id>/submit", methods=["POST"])
@require_roles("Traveler")
def submit_report(report_id):
    report = get_or_404(store.expense_reports, report_id)
    # ownership
    if not _owns_report(report):
        raise err("ERR_NOT_OWNER", "Traveler does not own this report")
    # state: must be DRAFT
    if report["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Report is not DRAFT")
    trip = _report_trip(report)
    # business preconditions (PRD 3.8) in order:
    # 1. trip APPROVED
    if trip["status"] != "APPROVED":
        raise err("ERR_TRIP_NOT_APPROVED", "Trip is not APPROVED")
    # 2. at least one line
    lines = report_lines(report_id)
    if len(lines) == 0:
        raise err("ERR_REPORT_EMPTY", "Report has no expense lines")
    # 3. receipt requirement: every line with reimbursable >= threshold has VERIFIED receipt
    policy = store.travel_policies.get(trip["policy_id"])
    threshold = policy["receipt_required_threshold_cents"] if policy else None
    if threshold is not None:
        for line in lines:
            if line["reimbursable_amount_cents"] >= threshold:
                verified = any(
                    rc["expense_line_id"] == line["id"] and rc["status"] == "VERIFIED"
                    for rc in store.receipts.values()
                )
                if not verified:
                    raise err("ERR_RECEIPT_REQUIRED", "Material line lacks a VERIFIED receipt")
    # recompute totals and transition
    recompute_report_totals(report, trip)
    report["status"] = "SUBMITTED"
    touch(report)
    return success(_report_view(report))


@bp.route("/expense-reports/<report_id>/decision", methods=["POST"])
@require_roles("Approver")
def decide_report(report_id):
    report = get_or_404(store.expense_reports, report_id)
    # ownership: acting approver is report traveler's manager
    if not _approver_manages(report):
        raise err("ERR_NOT_OWNER", "Approver is not the traveler's manager")
    body = get_json_body()
    require_fields(body, ["decision"])
    decision = require_enum(body, "decision", {"APPROVE", "REJECT", "RETURN"})
    # state: must be SUBMITTED
    if report["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Report is not SUBMITTED")
    trip = _report_trip(report)

    if decision == "RETURN":
        return_reason = body.get("return_reason")
        if not isinstance(return_reason, str) or return_reason == "":
            raise err("ERR_RETURN_REASON_REQUIRED", "return_reason is required for RETURN")
        report["return_reason"] = return_reason
        report["status"] = "RETURNED"
        touch(report)
        return success(_report_view(report))

    lines = report_lines(report_id)

    if decision == "REJECT":
        _cascade_reject(report, lines)
        report["status"] = "REJECTED"
        touch(report)
        return success(_report_view(report))

    # decision == APPROVE
    # gate 1: OOP chain complete if any out-of-policy line exists
    has_oop_line = any(not line["in_policy"] for line in lines)
    if has_oop_line:
        steps = [s for s in store.approval_steps.values() if s["report_id"] == report_id]
        if not steps or any(s["decision"] != "APPROVED" for s in steps):
            raise err("ERR_OOP_CHAIN_INCOMPLETE", "Out-of-policy approval chain incomplete")
    # gate 2: budget
    # recompute totals defensively so the budget check uses current figures
    recompute_report_totals(report, trip)
    if trip["remaining_budget_cents"] < report["total_reimbursable_cents"]:
        raise err("ERR_BUDGET_EXCEEDED", "Report total exceeds trip remaining budget")
    _cascade_approve(report, lines, trip)
    report["status"] = "APPROVED"
    touch(report)
    return success(_report_view(report))


def _cascade_approve(report, lines, trip):
    """CASCADE-1: lines -> APPROVED; PENDING settlement -> SETTLED; cards recompute;
    trip ledger advances."""
    affected_cards = set()
    for line in lines:
        if line["status"] == "PENDING_REVIEW":
            line["status"] = "APPROVED"
            if line["settlement_status"] == "PENDING":
                line["settlement_status"] = "SETTLED"
                if line.get("virtual_card_id"):
                    affected_cards.add(line["virtual_card_id"])
            touch(line)
    for card_id in affected_cards:
        card = store.virtual_cards.get(card_id)
        if card is not None:
            recompute_card(card, bump=True)
    # trip ledger: commit (report already APPROVED-marked by caller after this? )
    # PRD: committed += total; recompute. Set status first so ledger sum includes it.
    report["status"] = "APPROVED"
    recompute_trip_ledger(trip, bump=True)


def _cascade_reject(report, lines):
    """CASCADE-2: PENDING_REVIEW lines -> REJECTED; PENDING settlement -> VOID;
    cards recompute (release holds)."""
    affected_cards = set()
    for line in lines:
        if line["status"] == "PENDING_REVIEW":
            line["status"] = "REJECTED"
            if line["settlement_status"] == "PENDING":
                line["settlement_status"] = "VOID"
                if line.get("virtual_card_id"):
                    affected_cards.add(line["virtual_card_id"])
            touch(line)
    for card_id in affected_cards:
        card = store.virtual_cards.get(card_id)
        if card is not None:
            recompute_card(card, bump=True)


@bp.route("/expense-reports/<report_id>/reopen", methods=["POST"])
@require_roles("Traveler")
def reopen_report(report_id):
    report = get_or_404(store.expense_reports, report_id)
    if not _owns_report(report):
        raise err("ERR_NOT_OWNER", "Traveler does not own this report")
    if report["status"] != "RETURNED":
        raise err("ERR_INVALID_STATE", "Report is not RETURNED")
    report["status"] = "DRAFT"
    report["return_reason"] = None
    touch(report)
    return success(_report_view(report))
