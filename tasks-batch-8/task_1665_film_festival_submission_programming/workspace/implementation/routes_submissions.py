"""Routes: submissions (create/read/list/patch/checkout/withdraw/eligibility/
resubmit) and fee payments (read/list/refund)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import domain as D
from errors import (err409, err_invalid_state, err_not_found, err_phase,
                    err_referential, err_validation)
from store import DB
from util import (AUTHENTICATED_ROLES, auth, check_ownership, created_key,
                  get_body, get_or_404, ok, paginate, require_role, v_date,
                  v_enum, v_int, v_str)

bp = Blueprint("submissions", __name__)

NON_TERMINAL_PROGRAM_STATUSES = [
    "DRAFT", "SUBMITTED", "NEEDS_INFO", "ELIGIBLE", "IN_SCREENING", "ADVANCED",
    "INVITED", "WAITLISTED", "CONFIRMED", "PROGRAMMED",
]


def _validate_eligibility_fields(config, runtime, completion_date):
    if runtime < config["min_runtime_minutes"] or runtime > config["max_runtime_minutes"]:
        raise err409("ERR_INELIGIBLE_RUNTIME",
                     "Runtime outside the category's inclusive window")
    if completion_date < config["completion_cutoff"]:
        raise err409("ERR_INELIGIBLE_COMPLETION_DATE",
                     "Completion date earlier than the category cutoff")


# --------------------------------------------------------------- submissions
@bp.post("/festival/submissions")
def create_submission():
    body = get_body()
    edition_id = v_str(body, "edition_id")
    category = v_enum(body, "category", D.CATEGORIES)
    title = v_str(body, "title")
    runtime = v_int(body, "runtime_minutes")
    completion_date = v_date(body, "completion_date")
    premiere_status = v_enum(body, "premiere_status", D.PREMIERE_STATUSES)
    production_company = v_str(body, "production_company")
    fmt = v_enum(body, "format", D.FORMATS)
    uid, role = auth()
    require_role(role, ["FILMMAKER"])
    edition = DB.editions.get(edition_id)
    if edition is None:
        raise err_referential("Edition not found")
    if edition["status"] != "INTAKE_OPEN":
        raise err_phase("Submission intake is not open for this edition")
    if D.now() < edition["intake_open_at"]:
        raise err409("ERR_INTAKE_NOT_YET_OPEN", "Intake has not opened yet")
    config = D.category_config_for(edition_id, category)
    if config is None:
        raise err409("ERR_NO_CATEGORY_CONFIG",
                     "No category config for this edition and category")
    if any(s["edition_id"] == edition_id and s["submitter_id"] == uid
           and s["title"] == title for s in DB.submissions.values()):
        raise err409("ERR_DUPLICATE_SUBMISSION",
                     "This submitter already used this title in this edition")
    _validate_eligibility_fields(config, runtime, completion_date)
    rec = D.new_rec({
        "edition_id": edition_id, "submitter_id": uid, "category": category,
        "title": title, "runtime_minutes": runtime,
        "completion_date": completion_date, "premiere_status": premiere_status,
        "production_company": production_company, "format": fmt,
        "status": "DRAFT", "payment_status": "UNPAID",
        "needs_info_resolved": False,
        "provisional_score": None, "composite_score": None, "award_names": [],
    })
    DB.submissions[rec["id"]] = rec
    return ok(D.ser_submission(rec), 201)


@bp.get("/festival/submissions/<sid>")
def get_submission(sid):
    uid, role = auth()
    require_role(role, AUTHENTICATED_ROLES)
    rec = get_or_404(DB.submissions, sid)
    if role == "FILMMAKER":
        check_ownership(rec["submitter_id"] == uid)
    return ok(D.ser_submission(rec))


@bp.get("/festival/submissions")
def list_submissions():
    uid, role = auth()
    require_role(role, AUTHENTICATED_ROLES)
    items = list(DB.submissions.values())
    if role == "FILMMAKER":
        items = [s for s in items if s["submitter_id"] == uid]
    edition_id = request.args.get("edition_id")
    submitter_id = request.args.get("submitter_id")
    status = request.args.get("status")
    category = request.args.get("category")
    if edition_id is not None:
        items = [s for s in items if s["edition_id"] == edition_id]
    if submitter_id is not None:
        items = [s for s in items if s["submitter_id"] == submitter_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    if category is not None:
        items = [s for s in items if s["category"] == category]
    items.sort(key=created_key)
    page, meta = paginate(items)
    return ok([D.ser_submission(s) for s in page], pagination=meta)


@bp.patch("/festival/submissions/<sid>")
def patch_submission(sid):
    body = get_body()
    title = v_str(body, "title", required=False)
    runtime = v_int(body, "runtime_minutes", required=False)
    completion_date = v_date(body, "completion_date", required=False)
    premiere_status = v_enum(body, "premiere_status", D.PREMIERE_STATUSES,
                             required=False)
    production_company = v_str(body, "production_company", required=False)
    fmt = v_enum(body, "format", D.FORMATS, required=False)
    uid, role = auth()
    require_role(role, ["FILMMAKER"])
    rec = get_or_404(DB.submissions, sid)
    check_ownership(rec["submitter_id"] == uid)
    if rec["status"] not in ("DRAFT", "NEEDS_INFO"):
        raise err_invalid_state(
            "Only DRAFT or NEEDS_INFO submissions may be amended")
    new_runtime = runtime if runtime is not None else rec["runtime_minutes"]
    new_completion = (completion_date if completion_date is not None
                      else rec["completion_date"])
    config = D.category_config_for(rec["edition_id"], rec["category"])
    if config is not None:
        _validate_eligibility_fields(config, new_runtime, new_completion)
    if title is not None:
        rec["title"] = title
    if runtime is not None:
        rec["runtime_minutes"] = runtime
    if completion_date is not None:
        rec["completion_date"] = completion_date
    if premiere_status is not None:
        rec["premiere_status"] = premiere_status
    if production_company is not None:
        rec["production_company"] = production_company
    if fmt is not None:
        rec["format"] = fmt
    if rec["status"] == "NEEDS_INFO":
        rec["needs_info_resolved"] = True
    D.touch(rec)
    return ok(D.ser_submission(rec))


@bp.post("/festival/submissions/<sid>/checkout")
def checkout(sid):
    get_body()
    uid, role = auth()
    require_role(role, ["FILMMAKER"])
    rec = get_or_404(DB.submissions, sid)
    check_ownership(rec["submitter_id"] == uid)
    if rec["status"] != "DRAFT":
        raise err_invalid_state("Only DRAFT submissions may check out")
    edition = DB.editions.get(rec["edition_id"])
    if edition is None or edition["status"] != "INTAKE_OPEN":
        raise err_phase("Submission intake is not open for this edition")
    if D.now() < edition["intake_open_at"]:
        raise err409("ERR_INTAKE_NOT_YET_OPEN", "Intake has not opened yet")
    # Repeated checkout while INITIATED returns the same payment unchanged.
    for p in DB.fee_payments.values():
        if p["submission_id"] == sid and p["status"] == "INITIATED":
            return ok(D.ser_payment(p), 201)
    config = D.category_config_for(rec["edition_id"], rec["category"])
    if config is None:
        raise err409("ERR_NO_CATEGORY_CONFIG",
                     "No category config for this edition and category")
    # Tier selection against the logical clock (§3.2).
    current = D.now()
    if current <= edition["early_deadline_at"]:
        tier, base = "EARLY", config["early_fee_cents"]
    elif current <= edition["regular_deadline_at"]:
        tier, base = "REGULAR", config["regular_fee_cents"]
    else:
        tier, base = "LATE", config["late_fee_cents"]
    submitter = DB.submitters.get(rec["submitter_id"])
    is_student = bool(submitter["is_student"]) if submitter else False
    is_member = bool(submitter["is_member"]) if submitter else False
    # Pinned stacking order: student discount computed and rounded FIRST
    # against base; member discount SECOND against (base - student).
    student_discount = (D.round_half_up_cents(
        Decimal(base) * D.STUDENT_DISCOUNT_PCT) if is_student else 0)
    member_discount = (D.round_half_up_cents(
        Decimal(base - student_discount) * D.MEMBER_DISCOUNT_PCT)
        if is_member else 0)
    amount = base - student_discount - member_discount
    payment = D.new_rec({
        "submission_id": sid, "tier_applied": tier, "base_fee_cents": base,
        "student_discount_applied": is_student,
        "member_discount_applied": is_member,
        "student_discount_cents": student_discount,
        "member_discount_cents": member_discount,
        "amount_cents": amount, "status": "INITIATED", "paid_at": None,
        "refunded_amount_cents": 0,
    })
    DB.fee_payments[payment["id"]] = payment
    D.recompute_edition_ledger(edition)
    return ok(D.ser_payment(payment), 201)


@bp.post("/festival/submissions/<sid>/withdraw")
def withdraw(sid):
    get_body()
    uid, role = auth()
    require_role(role, ["FILMMAKER"])
    rec = get_or_404(DB.submissions, sid)
    check_ownership(rec["submitter_id"] == uid)
    if rec["status"] not in NON_TERMINAL_PROGRAM_STATUSES:
        raise err_invalid_state("Submission is already in a terminal state")
    edition = DB.editions.get(rec["edition_id"])

    entries = D.entries_of_submission(sid)
    active_entry = next(
        (e for e in entries
         if e["status"] in ("NOMINATED", "INVITED", "CONFIRMED", "PROGRAMMED")),
        None)

    # Slot unwind: HELD -> OPEN (entry cleared); CONFIRMED -> CANCELLED with
    # the agreement's used_screening_count decremented per slot.
    entry_ids = {e["id"] for e in entries}
    agreement = D.agreement_for_submission(sid)
    for slot in DB.slots.values():
        if slot["slate_entry_id"] not in entry_ids:
            continue
        if slot["status"] == "HELD":
            slot["status"] = "OPEN"
            slot["slate_entry_id"] = None
            D.touch(slot)
        elif slot["status"] == "CONFIRMED":
            slot["status"] = "CANCELLED"
            D.touch(slot)
            if agreement is not None:
                agreement["used_screening_count"] -= 1
                D.touch(agreement)

    # Slate-entry drop + waitlist promotion cascade.
    if active_entry is not None:
        slate = DB.slates.get(active_entry["slate_id"])
        active_entry["status"] = "DROPPED"
        D.touch(active_entry)
        if slate is not None:
            D.touch(slate)
            D.promotion_cascade(slate)

    # Refund policy (§3.2): half refund only when a SUCCEEDED payment exists
    # and no slot ever reached HELD/CONFIRMED/PLAYED for the film's entry.
    ever_occupied = any(e.get("_ever_held") for e in entries)
    payments = sorted((p for p in DB.fee_payments.values()
                       if p["submission_id"] == sid), key=created_key)
    succeeded = next((p for p in payments if p["status"] == "SUCCEEDED"), None)
    ledger_touched = False
    if succeeded is not None and not ever_occupied:
        refund = D.round_half_up_cents(
            Decimal(succeeded["amount_cents"]) * D.WITHDRAWAL_REFUND_PCT)
        succeeded["status"] = "PARTIALLY_REFUNDED"
        succeeded["refunded_amount_cents"] = refund
        D.touch(succeeded)
        rec["payment_status"] = "PARTIALLY_REFUNDED"
        ledger_touched = True
    else:
        # A DRAFT film whose only payment is INITIATED has it voided.
        for p in payments:
            if p["status"] == "INITIATED":
                p["status"] = "FAILED"
                D.touch(p)
                ledger_touched = True
    rec["status"] = "WITHDRAWN"
    D.touch(rec)
    if ledger_touched and edition is not None:
        D.recompute_edition_ledger(edition)
    return ok(D.ser_submission(rec))


@bp.post("/festival/submissions/<sid>/eligibility-decision")
def eligibility_decision(sid):
    body = get_body()
    decision = v_enum(body, "decision", ["ELIGIBLE", "INELIGIBLE", "NEEDS_INFO"])
    reason = v_str(body, "reason", required=False)
    if decision in ("INELIGIBLE", "NEEDS_INFO") and reason is None:
        raise err_validation("reason is required for this decision")
    uid, role = auth()
    require_role(role, ["FESTIVAL_ADMIN"])
    rec = get_or_404(DB.submissions, sid)
    if rec["status"] != "SUBMITTED":
        raise err_invalid_state("Only SUBMITTED submissions may be ruled on")
    edition = DB.editions.get(rec["edition_id"])
    if edition is None or edition["status"] not in (
            "INTAKE_OPEN", "INTAKE_CLOSED", "SCREENING"):
        raise err_phase("Eligibility rulings are not accepted in this phase")
    if decision == "ELIGIBLE":
        config = D.category_config_for(rec["edition_id"], rec["category"])
        requirement = config["premiere_requirement"] if config else "NONE"
        if rec["premiere_status"] not in D.PREMIERE_SATISFACTION[requirement]:
            raise err409("ERR_INELIGIBLE_PREMIERE",
                         "Premiere status does not satisfy the requirement")
        rec["status"] = ("IN_SCREENING" if edition["status"] == "SCREENING"
                         else "ELIGIBLE")
    elif decision == "INELIGIBLE":
        rec["status"] = "INELIGIBLE"
    else:
        rec["status"] = "NEEDS_INFO"
        rec["needs_info_resolved"] = False
    D.touch(rec)
    return ok(D.ser_submission(rec))


@bp.post("/festival/submissions/<sid>/resubmit")
def resubmit(sid):
    get_body()
    uid, role = auth()
    require_role(role, ["FILMMAKER"])
    rec = get_or_404(DB.submissions, sid)
    check_ownership(rec["submitter_id"] == uid)
    if rec["status"] != "NEEDS_INFO":
        raise err_invalid_state("Only NEEDS_INFO submissions may be resubmitted")
    if not rec["needs_info_resolved"]:
        raise err409("ERR_UNRESOLVED_INFO_REQUEST",
                     "The information request has not been resolved")
    rec["status"] = "SUBMITTED"
    D.touch(rec)
    return ok(D.ser_submission(rec))


# --------------------------------------------------------------- fee payments
@bp.get("/festival/fee-payments/<pid>")
def get_payment(pid):
    uid, role = auth()
    require_role(role, ["FESTIVAL_ADMIN", "FILMMAKER"])
    rec = get_or_404(DB.fee_payments, pid)
    if role == "FILMMAKER":
        sub = DB.submissions.get(rec["submission_id"])
        check_ownership(sub is not None and sub["submitter_id"] == uid)
    return ok(D.ser_payment(rec))


@bp.get("/festival/fee-payments")
def list_payments():
    uid, role = auth()
    require_role(role, ["FESTIVAL_ADMIN", "FILMMAKER"])
    items = list(DB.fee_payments.values())
    if role == "FILMMAKER":
        own = {s["id"] for s in DB.submissions.values()
               if s["submitter_id"] == uid}
        items = [p for p in items if p["submission_id"] in own]
    submission_id = request.args.get("submission_id")
    status = request.args.get("status")
    if submission_id is not None:
        items = [p for p in items if p["submission_id"] == submission_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items.sort(key=created_key)
    page, meta = paginate(items)
    return ok([D.ser_payment(p) for p in page], pagination=meta)


@bp.post("/festival/fee-payments/<pid>/refund")
def refund_payment(pid):
    body = get_body()
    v_str(body, "reason")
    uid, role = auth()
    require_role(role, ["FESTIVAL_ADMIN"])
    rec = get_or_404(DB.fee_payments, pid)
    sub = DB.submissions.get(rec["submission_id"])
    if rec["status"] == "SUCCEEDED":
        # Temporal cooling window: no later than 48h after paid_at.
        if D.now() > rec["paid_at"] + timedelta(
                hours=D.FULL_REFUND_WINDOW_HOURS):
            raise err409("ERR_REFUND_WINDOW_CLOSED",
                         "More than 48 hours have passed since payment")
    if rec["status"] != "SUCCEEDED":
        raise err409("ERR_PAYMENT_NOT_REFUNDABLE",
                     "Only a SUCCEEDED payment may be refunded")
    if sub is None or sub["status"] != "SUBMITTED":
        raise err409("ERR_REFUND_NOT_ALLOWED",
                     "The submission is no longer SUBMITTED")
    rec["status"] = "REFUNDED"
    rec["refunded_amount_cents"] = rec["amount_cents"]
    D.touch(rec)
    sub["payment_status"] = "REFUNDED"
    D.touch(sub)
    edition = DB.editions.get(sub["edition_id"])
    if edition is not None:
        D.recompute_edition_ledger(edition)
    return ok(D.ser_payment(rec))
