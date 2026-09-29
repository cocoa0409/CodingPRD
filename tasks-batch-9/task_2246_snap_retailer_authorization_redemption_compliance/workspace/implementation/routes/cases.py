"""SanctionCase, CmpElection and PenaltyLedgerEntry endpoints."""
from flask import Blueprint

import calc
import serial
import services
from core import (actor, add_days, add_months, db, ensure_object, fail,
                  filter_str, get_body, mark, now, ok, ok_list, opt_bool,
                  opt_enum, ordered, paginate, req_enum, req_int, req_str,
                  require_auth, resolve_body_ref, resolve_path, stamp_new)
from guards import ADMIN, ALL_READ, OWNER_ADMIN, check_store_scope, store_of_case

bp = Blueprint("cases", __name__)

VIOLATION_TYPES = ("TRAFFICKING", "INELIGIBLE_ITEMS_HARDSHIP", "STOCK_FAILURE")
SANCTION_TYPES = ("WARNING", "TEMPORARY_DISQUALIFICATION",
                  "PERMANENT_DISQUALIFICATION", "CMP_IN_LIEU")
REVIEW_OUTCOMES = ("SUSTAINED", "REVERSED", "REMANDED")
REVIEW_REASON_CODES = ("EVIDENCE_SUFFICIENT", "EVIDENCE_INSUFFICIENT",
                       "PROCEDURAL_DEFECT", "NEW_EVIDENCE")
LEDGER_ENTRY_TYPES = ("CMP_ASSESSED", "CMP_PAYMENT", "CMP_ABATEMENT")
FINAL_STATUSES = ("SANCTION_FINAL", "ENFORCED")
DISQUALIFICATIONS = ("PERMANENT_DISQUALIFICATION", "TEMPORARY_DISQUALIFICATION")
WINDOW_DAYS = 10
EFFECTIVE_DATE_DAYS = 30


def _predecessor_case(store_id, exclude_id=None):
    rows = [c for c in db.sanction_cases.values()
            if c["store_id"] == store_id and c["status"] in FINAL_STATUSES
            and c["id"] != exclude_id]
    if not rows:
        return None
    return ordered(rows)[-1]


@bp.post("/sanction-cases")
def create_case():
    require_auth(ADMIN)
    body = get_body()
    ensure_object(body)
    investigation = resolve_body_ref(body, "investigation_id",
                                    db.investigations,
                                    "ERR_INVESTIGATION_NOT_FOUND")
    violation_type = req_enum(body, "violation_type", VIOLATION_TYPES)
    if investigation is None:
        req_str(body, "investigation_id")
    if investigation["status"] != "SUBSTANTIATED":
        fail("ERR_INVESTIGATION_NOT_SUBSTANTIATED")
    if investigation["opened_reason"] == "ANOMALY_FLAG_L3":
        period = db.redemption_periods.get(investigation.get("trigger_period_id"))
        if period is None or period["status"] != "CLOSED" \
                or period.get("flag_level") != "FLAG_L3":
            fail("ERR_TRIGGER_PERIOD_NOT_FLAGGED")
    store = db.stores.get(investigation["store_id"])
    predecessor = _predecessor_case(investigation["store_id"])
    row = stamp_new({
        "store_id": investigation["store_id"],
        "investigation_id": investigation["id"],
        "predecessor_case_id": None if predecessor is None else predecessor["id"],
        "violation_type": violation_type,
        "charge_summary": None,
        "charge_letter_sent_at": None,
        "charge_issued_by_user_id": None,
        "reply_due_at": None,
        "cmp_election_due_at": None,
        "reply_text": None,
        "reply_received_at": None,
        "prior_final_sanction_count": 0,
        "sanction_type": None,
        "disqualification_months": None,
        "cmp_basis_variant": None,
        "cmp_basis_period_ids": None,
        "avg_monthly_redemption_cents": None,
        "monthly_penalty_cents": None,
        "cmp_amount_cents": None,
        "cmp_capped": None,
        "cmp_outstanding_cents": 0,
        "determined_at": None,
        "determined_by_user_id": None,
        "admin_review_due_at": None,
        "grounds_text": None,
        "admin_review_requested_at": None,
        "admin_review_outcome": None,
        "admin_review_decided_by_user_id": None,
        "admin_review_decided_at": None,
        "remand_count": 0,
        "final_decision_at": None,
        "effective_date": None,
        "enforced_at": None,
        "reason_code": None,
        "status": "CHARGE_DRAFT",
    })
    if store is not None:
        row["prior_final_sanction_count"] = calc.prior_final_sanction_count(
            row, store)
    db.sanction_cases[row["id"]] = row
    return ok(serial.sanction_case(row), 201)


@bp.get("/sanction-cases/<case_id>")
def get_case(case_id):
    require_auth(ALL_READ)
    row = resolve_path(db.sanction_cases, case_id, "ERR_SANCTION_CASE_NOT_FOUND")
    return ok(serial.sanction_case(row))


@bp.get("/sanction-cases")
def list_cases():
    require_auth(ALL_READ)
    rows = ordered(list(db.sanction_cases.values()))
    for name in ("store_id", "investigation_id", "predecessor_case_id",
                 "status", "sanction_type", "violation_type"):
        value = filter_str(name)
        if value is not None:
            rows = [r for r in rows if r.get(name) == value]
    data, pagination = paginate(rows, serial.sanction_case)
    return ok_list(data, pagination)


@bp.post("/sanction-cases/<case_id>/charge-letter")
def charge_letter(case_id):
    require_auth(ADMIN)
    case = resolve_path(db.sanction_cases, case_id,
                        "ERR_SANCTION_CASE_NOT_FOUND")
    body = get_body()
    ensure_object(body)
    charge_summary = req_str(body, "charge_summary")
    if case["status"] != "CHARGE_DRAFT":
        fail("ERR_INVALID_STATE")
    sent_at = now()
    case.update({
        "charge_summary": charge_summary,
        "charge_letter_sent_at": sent_at,
        "charge_issued_by_user_id": actor(),
        "reply_due_at": add_days(sent_at, WINDOW_DAYS),
        "cmp_election_due_at": add_days(sent_at, WINDOW_DAYS),
        "status": "CHARGE_ISSUED",
    })
    mark(case)
    store = store_of_case(case)
    if store is not None:
        services.update_row(store, {"sanction_status": "CHARGED"})
    services.commit()
    return ok(serial.sanction_case(case))


@bp.post("/sanction-cases/<case_id>/reply")
def case_reply(case_id):
    require_auth(OWNER_ADMIN)
    case = resolve_path(db.sanction_cases, case_id,
                        "ERR_SANCTION_CASE_NOT_FOUND")
    store = store_of_case(case)
    if store is not None:
        check_store_scope(store)
    body = get_body()
    ensure_object(body)
    reply_text = req_str(body, "reply_text")
    if case["status"] != "CHARGE_ISSUED":
        fail("ERR_INVALID_STATE")
    due = case.get("reply_due_at")
    if due is None or now() >= due:
        fail("ERR_REPLY_WINDOW_CLOSED")
    case.update({
        "reply_text": reply_text,
        "reply_received_at": now(),
        "status": "REPLY_RECEIVED",
    })
    mark(case)
    services.commit()
    return ok(serial.sanction_case(case))


@bp.post("/sanction-cases/<case_id>/cmp-elections")
def create_election(case_id):
    require_auth(OWNER_ADMIN)
    case = resolve_path(db.sanction_cases, case_id,
                        "ERR_SANCTION_CASE_NOT_FOUND")
    store = store_of_case(case)
    if store is not None:
        check_store_scope(store)
    body = get_body()
    ensure_object(body)
    expected = req_int(body, "expected_sanction_case_version")
    hardship_pending = opt_bool(body, "hardship_ownership_change_pending",
                                default=False)
    if expected != case["version"]:
        fail("ERR_STALE_SANCTION_CASE_VERSION")
    due = case.get("cmp_election_due_at")
    if due is None:
        fail("ERR_INVALID_STATE")
    if now() >= due:
        fail("ERR_CMP_ELECTION_WINDOW_CLOSED")
    multiplier = calc.cmp_month_multiplier(
        case["violation_type"],
        calc.disqualification_months(case["violation_type"], "CMP_IN_LIEU",
                                     case.get("prior_final_sanction_count") or 0))
    quote = calc.cmp_quote(store, case["charge_letter_sent_at"], multiplier)
    if quote is None:
        fail("ERR_NO_REDEMPTION_HISTORY")
    for previous in services.case_elections(case["id"]):
        if previous["status"] == "ELECTED":
            services.update_row(previous, {"status": "SUPERSEDED"})
    row = stamp_new({
        "sanction_case_id": case["id"],
        "hardship_ownership_change_pending": hardship_pending,
        "elected_at": now(),
        "quoted_amount_cents": quote["cmp_amount_cents"],
        "quoted_basis_variant": quote["cmp_basis_variant"],
        "status": "ELECTED",
    })
    db.cmp_elections[row["id"]] = row
    mark(case)
    services.commit()
    return ok(serial.cmp_election(row), 201)


@bp.get("/sanction-cases/<case_id>/cmp-elections")
def list_elections(case_id):
    require_auth(ALL_READ)
    case = resolve_path(db.sanction_cases, case_id,
                        "ERR_SANCTION_CASE_NOT_FOUND")
    rows = services.case_elections(case["id"])
    status = filter_str("status")
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    data, pagination = paginate(rows, serial.cmp_election)
    return ok_list(data, pagination)


@bp.post("/sanction-cases/<case_id>/determination")
def determination(case_id):
    require_auth(ADMIN)
    case = resolve_path(db.sanction_cases, case_id,
                        "ERR_SANCTION_CASE_NOT_FOUND")
    body = get_body()
    ensure_object(body)
    sanction_type = req_enum(body, "sanction_type", SANCTION_TYPES)
    if case["status"] not in ("CHARGE_ISSUED", "REPLY_RECEIVED", "REMANDED"):
        fail("ERR_INVALID_STATE")
    if case["status"] == "CHARGE_ISSUED":
        due = case.get("reply_due_at")
        if due is not None and now() < due:
            fail("ERR_REPLY_WINDOW_OPEN")
    if sanction_type not in calc.ALLOWED_SANCTIONS.get(case["violation_type"], ()):
        fail("ERR_SANCTION_TYPE_NOT_ALLOWED")
    store = store_of_case(case)
    prior = (calc.prior_final_sanction_count(case, store)
             if store is not None else 0)
    months = calc.disqualification_months(case["violation_type"], sanction_type,
                                          prior)
    quote = None
    if sanction_type == "CMP_IN_LIEU":
        if store is None or not calc.cmp_in_lieu_available(case, store):
            fail("ERR_CMP_NOT_AVAILABLE")
        multiplier = calc.cmp_month_multiplier(case["violation_type"], months)
        quote = calc.cmp_quote(store, case.get("charge_letter_sent_at"),
                               multiplier)
        if quote is None:
            fail("ERR_NO_REDEMPTION_HISTORY")
    determined_at = now()
    case.update({
        "sanction_type": sanction_type,
        "prior_final_sanction_count": prior,
        "disqualification_months": months,
        "determined_at": determined_at,
        "determined_by_user_id": actor(),
        "admin_review_due_at": add_days(determined_at, WINDOW_DAYS),
        "status": "DETERMINED",
    })
    if quote is not None:
        case.update(quote)
    mark(case)
    election = services.elected_election(case["id"])
    if election is not None:
        services.update_row(election, {
            "status": "APPROVED" if sanction_type == "CMP_IN_LIEU" else "REJECTED",
        })
    if quote is not None:
        calc.append_ledger_entry(case, "CMP_ASSESSED", quote["cmp_amount_cents"],
                                 "DETERMINATION")
        services.rederive_case_balance(case)
        services.rederive_owner_of_store(store)
    services.commit()
    return ok(serial.sanction_case(case))


@bp.post("/sanction-cases/<case_id>/administrative-review")
def administrative_review(case_id):
    require_auth(OWNER_ADMIN)
    case = resolve_path(db.sanction_cases, case_id,
                        "ERR_SANCTION_CASE_NOT_FOUND")
    store = store_of_case(case)
    if store is not None:
        check_store_scope(store)
    body = get_body()
    ensure_object(body)
    grounds_text = req_str(body, "grounds_text")
    if case["status"] != "DETERMINED":
        fail("ERR_INVALID_STATE")
    due = case.get("admin_review_due_at")
    if due is None or now() >= due:
        fail("ERR_ADMIN_REVIEW_WINDOW_CLOSED")
    case.update({
        "grounds_text": grounds_text,
        "admin_review_requested_at": now(),
        "status": "ADMIN_REVIEW_REQUESTED",
    })
    mark(case)
    if store is not None:
        services.update_row(store, {"sanction_status": "UNDER_ADMIN_REVIEW"})
    services.commit()
    return ok(serial.sanction_case(case))


@bp.post("/sanction-cases/<case_id>/administrative-review-decision")
def administrative_review_decision(case_id):
    require_auth(("AdminReviewOfficer",))
    case = resolve_path(db.sanction_cases, case_id,
                        "ERR_SANCTION_CASE_NOT_FOUND")
    if actor() in (case.get("charge_issued_by_user_id"),
                   case.get("determined_by_user_id")):
        fail("ERR_SEGREGATION_OF_DUTIES")
    body = get_body()
    ensure_object(body)
    outcome = req_enum(body, "outcome", REVIEW_OUTCOMES)
    reason_code = opt_enum(body, "reason_code", REVIEW_REASON_CODES)
    if case["status"] != "ADMIN_REVIEW_REQUESTED":
        fail("ERR_INVALID_STATE")
    if outcome == "REMANDED" and (case.get("remand_count") or 0) >= 1:
        fail("ERR_REMAND_LIMIT_REACHED")
    store = store_of_case(case)
    case.update({
        "admin_review_outcome": outcome,
        "admin_review_decided_by_user_id": actor(),
        "admin_review_decided_at": now(),
        "reason_code": reason_code,
    })
    mark(case)
    if outcome == "REVERSED":
        case["status"] = "SANCTION_REVERSED"
        services.abate_outstanding(case)
        if store is not None:
            changes = {"sanction_status": "SANCTION_REVERSED"}
            if store["authorization_status"] == "SUSPENDED":
                changes["authorization_status"] = "AUTHORIZED"
            services.update_row(store, changes)
    elif outcome == "REMANDED":
        case["status"] = "REMANDED"
        case["remand_count"] = (case.get("remand_count") or 0) + 1
        case["sanction_type"] = None
        case["disqualification_months"] = None
        for field in services.CMP_FIGURE_FIELDS:
            case[field] = None
        services.abate_outstanding(case)
    services.commit()
    return ok(serial.sanction_case(case))


@bp.post("/sanction-cases/<case_id>/finalize")
def finalize(case_id):
    require_auth(ADMIN)
    case = resolve_path(db.sanction_cases, case_id,
                        "ERR_SANCTION_CASE_NOT_FOUND")
    status = case["status"]
    due = case.get("admin_review_due_at")
    if status == "DETERMINED":
        if due is None or now() < due:
            fail("ERR_INVALID_STATE")
    elif status == "ADMIN_REVIEW_REQUESTED":
        if case.get("admin_review_outcome") != "SUSTAINED":
            fail("ERR_INVALID_STATE")
    else:
        fail("ERR_INVALID_STATE")
    final_at = now()
    case["final_decision_at"] = final_at
    case["effective_date"] = (add_days(final_at, EFFECTIVE_DATE_DAYS)
                              if case.get("sanction_type") in DISQUALIFICATIONS
                              else None)
    case["status"] = "SANCTION_FINAL"
    mark(case)
    store = store_of_case(case)
    if store is not None:
        changes = {"sanction_status": "SANCTION_FINAL"}
        if case.get("sanction_type") in DISQUALIFICATIONS \
                and store["authorization_status"] == "AUTHORIZED":
            changes["authorization_status"] = "SUSPENDED"
        services.update_row(store, changes)
        # The owner rollup counts cases whose status is SANCTION_FINAL or
        # ENFORCED, and is re-derived whenever anything in the portfolio moves.
        services.rederive_owner_of_store(store)
    services.commit()
    return ok(serial.sanction_case(case))


@bp.post("/sanction-cases/<case_id>/enforce")
def enforce(case_id):
    require_auth(ADMIN)
    case = resolve_path(db.sanction_cases, case_id,
                        "ERR_SANCTION_CASE_NOT_FOUND")
    if case["status"] != "SANCTION_FINAL":
        fail("ERR_INVALID_STATE")
    if case.get("sanction_type") not in DISQUALIFICATIONS:
        fail("ERR_SANCTION_TYPE_NOT_ALLOWED")
    effective = case.get("effective_date")
    if effective is None or now() < effective:
        fail("ERR_ENFORCEMENT_NOT_DUE")
    enforced_at = now()
    case["enforced_at"] = enforced_at
    case["status"] = "ENFORCED"
    mark(case)
    store = store_of_case(case)
    if store is not None:
        changes = {"authorization_status": "DISQUALIFIED"}
        if case["sanction_type"] == "PERMANENT_DISQUALIFICATION":
            changes["permanently_disqualified"] = True
            changes["disqualified_until"] = None
        else:
            changes["disqualified_until"] = add_months(
                enforced_at, case.get("disqualification_months") or 0)
        services.update_row(store, changes)
        services.recall_active_deployments(store, "AUTHORIZATION_LOST")
        services.rederive_owner_of_store(store)
    services.commit()
    return ok(serial.sanction_case(case))


@bp.get("/sanction-cases/<case_id>/penalty-ledger")
def list_ledger(case_id):
    require_auth(ALL_READ)
    case = resolve_path(db.sanction_cases, case_id,
                        "ERR_SANCTION_CASE_NOT_FOUND")
    rows = calc.case_ledger_entries(case["id"])
    entry_type = filter_str("entry_type")
    if entry_type is not None:
        rows = [r for r in rows if r.get("entry_type") == entry_type]
    data, pagination = paginate(rows, serial.penalty_ledger_entry)
    return ok_list(data, pagination)


@bp.post("/sanction-cases/<case_id>/cmp-payments")
def cmp_payment(case_id):
    require_auth(OWNER_ADMIN)
    case = resolve_path(db.sanction_cases, case_id,
                        "ERR_SANCTION_CASE_NOT_FOUND")
    store = store_of_case(case)
    if store is not None:
        check_store_scope(store)
    body = get_body()
    ensure_object(body)
    amount = req_int(body, "amount_cents", minimum=0)
    outstanding = calc.case_outstanding(case["id"])
    if amount > outstanding:
        fail("ERR_CMP_OVERPAYMENT")
    entry = calc.append_ledger_entry(case, "CMP_PAYMENT", -amount,
                                     "RETAILER_REMITTANCE")
    services.rederive_case_balance(case)
    services.rederive_owner_of_store(store)
    if (case.get("cmp_outstanding_cents") or 0) == 0:
        election = services.approved_election(case["id"])
        if election is not None:
            services.update_row(election, {"status": "PAID"})
    services.commit()
    return ok(serial.penalty_ledger_entry(entry), 201)
