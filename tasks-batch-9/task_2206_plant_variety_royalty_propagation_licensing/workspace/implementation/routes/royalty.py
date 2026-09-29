"""Royalty reporting: the reported basis, the audited basis and settlement."""

from decimal import Decimal

from flask import Blueprint

from calculations import late_fee_cents
from common import (check_occ, filtered, require_agreement_active,
                    require_distinct_actor, require_owner,
                    require_quota_not_frozen, resolve, terminal, transition)
from derive import (apply, children, price_report_audited_basis,
                    price_report_reported_basis, recompute_ledger,
                    refresh_after_accept)
from errors import ApiError
from middleware import (ALL_ROLES, LICENSING_OFFICER, PROPAGATOR, endpoint)
from response import collection, created, ok
from store import new_id, parse_dt, store
from validation import ID, DateTime, Int, Str

bp = Blueprint("royalty", __name__)

REPORT_SCHEMA = [
    ("agreement_id", ID, True),
    ("period_code", Str(4, 10), True),
    ("period_start", DateTime(), True),
    ("period_end", DateTime(), True),
    ("due_at", DateTime(), True),
]

LINE_SCHEMA = [
    ("quota_id", ID, True),
    ("reported_units", Int(0), True),
    ("expected_report_version", Int(0), True),
]

DISPUTE_SCHEMA = [("dispute_note", Str(1, 500), False)]
REVERSE_SCHEMA = [("reversal_note", Str(1, 500), False)]


@endpoint(bp, "POST", "/royalty-reports", [PROPAGATOR], REPORT_SCHEMA)
def create_report(actor, body):
    agreement = resolve("agreement_id", body["agreement_id"])
    require_owner(actor, agreement["propagator_id"])
    for other in children("reports", "agreement_id", agreement["id"]):
        if other["period_code"] == body["period_code"]:
            raise ApiError("ERR_DUPLICATE_REPORT_PERIOD")
    period_start = parse_dt(body["period_start"])
    period_end = parse_dt(body["period_end"])
    due_at = parse_dt(body["due_at"])
    if period_end <= period_start or due_at < period_end:
        raise ApiError("ERR_INVALID_INTERVAL")
    if (period_start < parse_dt(agreement["term_start"])
            or period_end > parse_dt(agreement["term_end"])):
        raise ApiError("ERR_PERIOD_OUTSIDE_TERM")
    record = {
        "id": new_id(),
        "agreement_id": agreement["id"],
        "period_code": body["period_code"],
        "period_start": body["period_start"],
        "period_end": body["period_end"],
        "due_at": body["due_at"],
        "review_status": "DRAFT",
        "settlement_status": "UNSETTLED",
        "submitted_at": None,
        "accepted_at": None,
        "is_late": False,
        "provisional_total_cents": 0,
        "final_total_cents": 0,
        "late_fee_cents": 0,
        "booked_amount_cents": 0,
        "revision_no": 0,
        "accepted_by_user_id": None,
        "settled_by_user_id": None,
    }
    store.stamp_new(record)
    store.reports[record["id"]] = record
    return created(record)


@endpoint(bp, "GET", "/royalty-reports", ALL_ROLES)
def list_reports(actor):
    records, limit, offset, total = filtered(
        "reports", "agreement_id", "review_status", "settlement_status",
        "period_code")
    return collection(records, limit, offset, total)


@endpoint(bp, "GET", "/royalty-reports/<report_id>", ALL_ROLES)
def get_report(actor, report_id):
    return ok(resolve("report_id", report_id))


@endpoint(bp, "POST", "/royalty-reports/<report_id>/line-items", [PROPAGATOR],
          LINE_SCHEMA)
def create_line_item(actor, body, report_id):
    report = resolve("report_id", report_id)
    quota = resolve("quota_id", body["quota_id"])
    agreement = store.agreements[report["agreement_id"]]
    require_owner(actor, agreement["propagator_id"])
    check_occ(body, "expected_report_version", report, "ERR_STALE_REPORT_VERSION")
    transition(report["review_status"] == "DRAFT")
    require_quota_not_frozen(quota)
    require_agreement_active(agreement)
    if quota["agreement_id"] != report["agreement_id"]:
        raise ApiError("ERR_QUOTA_AGREEMENT_MISMATCH")
    for other in children("line_items", "report_id", report["id"]):
        if other["quota_id"] == quota["id"]:
            raise ApiError("ERR_DUPLICATE_LINE_ITEM_QUOTA")
    record = {
        "id": new_id(),
        "report_id": report["id"],
        "quota_id": quota["id"],
        "reported_units": body["reported_units"],
        "effective_rate_cents": Decimal("0.0000"),
        "billable_units": 0,
        "provisional_amount_cents": 0,
        "final_amount_cents": 0,
        "overrun_flagged": False,
    }
    store.stamp_new(record)
    store.line_items[record["id"]] = record
    apply(report, None, force=True)
    return created(record)


@endpoint(bp, "GET", "/royalty-line-items", ALL_ROLES)
def list_line_items(actor):
    records, limit, offset, total = filtered(
        "line_items", "report_id", "quota_id", "overrun_flagged")
    return collection(records, limit, offset, total)


@endpoint(bp, "GET", "/royalty-line-items/<line_item_id>", ALL_ROLES)
def get_line_item(actor, line_item_id):
    return ok(resolve("line_item_id", line_item_id))


@endpoint(bp, "POST", "/royalty-reports/<report_id>/submit", [PROPAGATOR], [])
def submit_report(actor, body, report_id):
    report = resolve("report_id", report_id)
    agreement = store.agreements[report["agreement_id"]]
    require_owner(actor, agreement["propagator_id"])
    transition(report["review_status"] == "DRAFT")
    require_agreement_active(agreement)
    if not children("line_items", "report_id", report["id"]):
        raise ApiError("ERR_REPORT_HAS_NO_LINES")
    submitted_at = store.now
    provisional_total = price_report_reported_basis(report)
    apply(report, {
        "review_status": "SUBMITTED",
        "submitted_at": store.now_iso(),
        "is_late": submitted_at > parse_dt(report["due_at"]),
        "provisional_total_cents": provisional_total,
    }, force=True)
    return ok(report)


@endpoint(bp, "POST", "/royalty-reports/<report_id>/accept", [LICENSING_OFFICER], [])
def accept_report(actor, body, report_id):
    report = resolve("report_id", report_id)
    transition(report["review_status"] == "SUBMITTED")
    agreement = store.agreements[report["agreement_id"]]
    require_agreement_active(agreement)
    require_distinct_actor(actor, agreement["countersigned_by_user_id"])
    final_total = price_report_audited_basis(report)
    fee = late_fee_cents(final_total) if report["is_late"] else 0
    apply(report, {
        "review_status": "ACCEPTED",
        "accepted_at": store.now_iso(),
        "accepted_by_user_id": actor.user_id,
        "final_total_cents": final_total,
        "late_fee_cents": fee,
        "booked_amount_cents": final_total + fee,
    }, force=True)
    refresh_after_accept(store.propagators[agreement["propagator_id"]])
    return ok(report)


@endpoint(bp, "POST", "/royalty-reports/<report_id>/dispute", [LICENSING_OFFICER],
          DISPUTE_SCHEMA)
def dispute_report(actor, body, report_id):
    report = resolve("report_id", report_id)
    transition(report["review_status"] == "ACCEPTED"
               and report["settlement_status"] == "UNSETTLED")
    apply(report, {"review_status": "DISPUTED", "booked_amount_cents": 0}, force=True)
    agreement = store.agreements[report["agreement_id"]]
    recompute_ledger(store.propagators[agreement["propagator_id"]], force=True)
    return ok(report)


@endpoint(bp, "POST", "/royalty-reports/<report_id>/revise", [PROPAGATOR], [])
def revise_report(actor, body, report_id):
    report = resolve("report_id", report_id)
    agreement = store.agreements[report["agreement_id"]]
    require_owner(actor, agreement["propagator_id"])
    transition(report["review_status"] == "DISPUTED"
               and report["settlement_status"] == "UNSETTLED")
    apply(report, {
        "review_status": "DRAFT",
        "revision_no": int(report["revision_no"]) + 1,
        "submitted_at": None,
        "accepted_at": None,
        "accepted_by_user_id": None,
        "is_late": False,
        "final_total_cents": 0,
        "late_fee_cents": 0,
        "booked_amount_cents": 0,
    }, force=True)
    return ok(report)


@endpoint(bp, "POST", "/royalty-reports/<report_id>/settle", [LICENSING_OFFICER], [])
def settle_report(actor, body, report_id):
    report = resolve("report_id", report_id)
    terminal(report["settlement_status"] == "REVERSED")
    transition(report["settlement_status"] == "UNSETTLED"
               and report["review_status"] == "ACCEPTED")
    require_distinct_actor(actor, report["accepted_by_user_id"])
    if int(report["booked_amount_cents"]) <= 0:
        raise ApiError("ERR_NOTHING_TO_SETTLE")
    apply(report, {
        "settlement_status": "SETTLED",
        "settled_by_user_id": actor.user_id,
    }, force=True)
    agreement = store.agreements[report["agreement_id"]]
    recompute_ledger(store.propagators[agreement["propagator_id"]], force=True)
    return ok(report)


@endpoint(bp, "POST", "/royalty-reports/<report_id>/reverse", [LICENSING_OFFICER],
          REVERSE_SCHEMA)
def reverse_report(actor, body, report_id):
    report = resolve("report_id", report_id)
    terminal(report["settlement_status"] == "REVERSED")
    transition(report["settlement_status"] == "SETTLED"
               and report["review_status"] == "ACCEPTED")
    apply(report, {
        "settlement_status": "REVERSED",
        "settled_by_user_id": None,
    }, force=True)
    agreement = store.agreements[report["agreement_id"]]
    recompute_ledger(store.propagators[agreement["propagator_id"]], force=True)
    return ok(report)
