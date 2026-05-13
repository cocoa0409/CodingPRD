"""Loan creation, renewal, recall, return routes."""
from datetime import timedelta
from flask import Blueprint, request, g

import db
from errors import err
from response import success
from middleware import require_auth
from services import validation as V
from services.common import (
    get_loan, get_copy, get_card, get_book_title, get_reservation,
    check_version, assert_reader_ownership,
)
from services.serialize import serialize_loan
from services.reader_status import recompute_reader
from services.aggregates import recompute_title_aggregates
from services import reservations as reservations_svc
from services import audit
from services.money import RECALL_GRACE_DAYS
from services.fines import compute_final_fine_amount
from clock import parse_iso, iso, now


bp = Blueprint("loans", __name__)


ACTIVE_LOAN_STATUSES = {"BORROWED", "RENEWED", "RECALL_PENDING"}


def _strict_quota_remaining(card):
    committed = sum(1 for l in db.loans.values()
                    if l["card_id"] == card["id"] and l["status"] in ACTIVE_LOAN_STATUSES)
    reserved = sum(1 for r in db.reservations.values()
                   if r["reader_id"] == card["reader_id"]
                   and r["status"] in {"QUEUED", "READY_FOR_PICKUP"})
    return max(0, card["max_loans"] - committed - reserved)


@bp.route("/library/loans", methods=["POST"])
@require_auth(roles={"Reader", "Librarian"})
def create_loan():
    body = V.require_dict(request.get_json(silent=True) or {})
    copy_id = V.require_str(body, "copy_id")
    card_id = V.require_str(body, "card_id")
    channel = V.require_enum(body, "channel", V.LOAN_CHANNELS)
    reservation_id = body.get("reservation_id")

    # Existence checks for FKs (body)
    copy = get_copy(copy_id)
    card = get_card(card_id)
    reservation = None
    if reservation_id is not None:
        reservation = get_reservation(reservation_id)

    reader = db.readers.get(card["reader_id"])
    if reader is None:
        raise err("ERR_NOT_FOUND", "Card's reader does not exist")

    # Reader ownership (if acting Reader, must own the card)
    if g.user_role == "Reader":
        if g.user_id != card["reader_id"]:
            raise err("ERR_FORBIDDEN", "Reader can borrow only with their own card")

    # State: copy must be in correct state
    if reservation is not None:
        # Reservation pickup path
        if reservation["status"] != "READY_FOR_PICKUP":
            raise err("ERR_INVALID_STATE",
                      f"Reservation is {reservation['status']}, not READY_FOR_PICKUP")
        # Acting card.reader_id must match reservation.reader_id
        if card["reader_id"] != reservation["reader_id"]:
            raise err("ERR_FORBIDDEN",
                      "Acting card's reader does not own this reservation")
        if reservation.get("held_copy_id") != copy["id"]:
            raise err("ERR_COPY_NOT_AVAILABLE",
                      "Copy does not match the reservation's held copy")
        if copy["status"] != "RESERVED":
            raise err("ERR_COPY_NOT_AVAILABLE",
                      f"Copy is {copy['status']}, not RESERVED")
        # Hold expiry: hold_expires_at must be strictly later than now
        hold_exp = parse_iso(reservation["hold_expires_at"])
        if hold_exp <= now():
            raise err("ERR_HOLD_EXPIRED",
                      "Reservation hold has already expired")
    else:
        if copy["status"] != "AVAILABLE":
            raise err("ERR_COPY_NOT_AVAILABLE",
                      f"Copy is {copy['status']}, not AVAILABLE")

    # Card must be ACTIVE
    if card["status"] != "ACTIVE":
        raise err("ERR_CARD_NOT_ACTIVE", f"Card is {card['status']}, not ACTIVE")

    # Reader posture
    if reader["status"] == "BLACKLISTED":
        raise err("ERR_READER_BLACKLISTED", "Reader is BLACKLISTED")

    # Recompute fiscal posture live to be safe
    from services.reader_status import reader_unpaid_fine_cents
    if reader_unpaid_fine_cents(reader["id"]) > 0:
        raise err("ERR_UNPAID_FINE", "Reader has unpaid fines")

    # Quota check (strict mode)
    if _strict_quota_remaining(card) <= 0:
        raise err("ERR_QUOTA_EXCEEDED", "Borrowing quota exhausted")

    # Create loan
    duration_days = card["loan_duration_days"]
    borrowed_at_dt = now()
    due_at_dt = borrowed_at_dt + timedelta(days=duration_days)

    loan = {
        "copy_id": copy["id"],
        "card_id": card["id"],
        "reader_id": card["reader_id"],
        "borrowed_at": iso(borrowed_at_dt),
        "due_at": iso(due_at_dt),
        "returned_at": None,
        "renewals_used": 0,
        "is_recalled": False,
        "recall_due_at": None,
        "channel": channel,
        "status": "BORROWED",
    }
    db.stamp_create(loan)
    db.loans[loan["id"]] = loan

    # Side effects
    copy["status"] = "ON_LOAN"
    db.stamp_update(copy)

    if reservation is not None:
        reservation["status"] = "FULFILLED"
        db.stamp_update(reservation)
        audit.append("RESERVATION_FULFILLED", "Reservation", reservation["id"],
                     {"after": {"status": "FULFILLED", "loan_id": loan["id"]}})

    recompute_title_aggregates(copy["book_title_id"])
    recompute_reader(reader["id"])
    audit.append("LOAN_CREATED", "Loan", loan["id"],
                 {"after": {"copy_id": copy["id"], "card_id": card["id"],
                            "reader_id": reader["id"], "due_at": loan["due_at"]}})

    return success(serialize_loan(loan), status=201)


@bp.route("/library/loans/<lid>", methods=["GET"])
@require_auth(roles={"Reader", "Librarian", "FineOfficer", "Admin"})
def get_loan_endpoint(lid):
    loan = get_loan(lid)
    assert_reader_ownership(loan["reader_id"])
    return success(serialize_loan(loan))


@bp.route("/library/loans/<lid>/renew", methods=["POST"])
@require_auth(roles={"Reader", "Librarian"})
def renew_loan(lid):
    loan = get_loan(lid)
    body = V.require_dict(request.get_json(silent=True) or {})
    check_version(loan, body)

    # Reader ownership
    assert_reader_ownership(loan["reader_id"])

    card = db.cards.get(loan["card_id"])
    if card is None:
        raise err("ERR_NOT_FOUND", "Card for loan no longer exists")
    reader = db.readers.get(loan["reader_id"])
    if reader is None:
        raise err("ERR_NOT_FOUND", "Reader for loan no longer exists")
    copy = db.copies.get(loan["copy_id"])
    if copy is None:
        raise err("ERR_NOT_FOUND", "Copy for loan no longer exists")

    # State: loan must be BORROWED for renewal (RENEWED conceptually re-enters BORROWED,
    # so the test for a fresh renewal cycle accepts both BORROWED and the conceptual cycle)
    if loan["status"] not in {"BORROWED", "RENEWED"}:
        # RECALL_PENDING etc. are not declared transitions
        raise err("ERR_INVALID_STATE",
                  f"Renew not declared from status={loan['status']}")

    # Card must be ACTIVE
    if card["status"] != "ACTIVE":
        raise err("ERR_CARD_NOT_ACTIVE", f"Card is {card['status']}, not ACTIVE")

    # Reader posture
    if reader["status"] == "BLACKLISTED":
        raise err("ERR_READER_BLACKLISTED", "Reader is BLACKLISTED")

    from services.reader_status import reader_unpaid_fine_cents
    if reader_unpaid_fine_cents(reader["id"]) > 0:
        raise err("ERR_UNPAID_FINE", "Reader has unpaid fines")

    # Renewal limit
    if loan["renewals_used"] >= card["max_renewals"]:
        raise err("ERR_RENEWAL_LIMIT_REACHED",
                  f"Loan has reached the renewal limit ({card['max_renewals']})")

    # No active reservation may exist for the loan's underlying BookTitle
    if reservations_svc.active_reservation_exists_for_title(copy["book_title_id"]):
        raise err("ERR_RESERVATION_BLOCKS_RENEWAL",
                  "An active reservation exists for the loan's title")

    # Recall flag
    if loan.get("is_recalled"):
        raise err("ERR_LOAN_RECALLED", "Loan has been recalled; cannot renew")

    # Compute new due_at = max(now, current due_at) + loan_duration_days
    current_due = parse_iso(loan["due_at"])
    base = max(current_due, now())
    new_due = base + timedelta(days=card["loan_duration_days"])

    loan["renewals_used"] = loan["renewals_used"] + 1
    loan["due_at"] = iso(new_due)
    loan["status"] = "BORROWED"  # conceptual cycle back to BORROWED for next renewal
    db.stamp_update(loan)
    recompute_reader(reader["id"])
    audit.append("LOAN_RENEWED", "Loan", loan["id"],
                 {"after": {"renewals_used": loan["renewals_used"],
                            "due_at": loan["due_at"]}})
    return success(serialize_loan(loan))


@bp.route("/library/loans/<lid>/recall", methods=["POST"])
@require_auth(roles={"Librarian"})
def recall_loan(lid):
    loan = get_loan(lid)
    body = V.require_dict(request.get_json(silent=True) or {})
    check_version(loan, body)

    V.require_str(body, "reason")

    if loan["status"] not in {"BORROWED", "RENEWED"}:
        raise err("ERR_INVALID_STATE",
                  f"Recall not declared from status={loan['status']}")

    copy = db.copies.get(loan["copy_id"])
    if copy is None:
        raise err("ERR_NOT_FOUND", "Copy for loan no longer exists")

    # Precondition: an active reservation exists for the title OR the loan is overdue
    has_reservation = reservations_svc.active_reservation_exists_for_title(copy["book_title_id"])
    due_at_dt = parse_iso(loan["due_at"])
    overdue = now() > due_at_dt
    if not (has_reservation or overdue):
        raise err("ERR_INVALID_STATE",
                  "Recall requires either an active reservation on the title or an overdue loan")

    loan["is_recalled"] = True
    proposed = now() + timedelta(days=RECALL_GRACE_DAYS)
    loan["recall_due_at"] = iso(min(due_at_dt, proposed))
    loan["status"] = "RECALL_PENDING"
    db.stamp_update(loan)
    recompute_reader(loan["reader_id"])
    audit.append("LOAN_RECALLED", "Loan", loan["id"],
                 {"after": {"is_recalled": True,
                            "recall_due_at": loan["recall_due_at"]}})
    return success(serialize_loan(loan))


@bp.route("/library/loans/<lid>/return", methods=["POST"])
@require_auth(roles={"Reader", "Librarian"})
def return_loan(lid):
    loan = get_loan(lid)
    body = V.require_dict(request.get_json(silent=True) or {})
    check_version(loan, body)

    assert_reader_ownership(loan["reader_id"])

    if loan["status"] not in {"BORROWED", "RENEWED", "RECALL_PENDING"}:
        raise err("ERR_INVALID_STATE",
                  f"Return not declared from status={loan['status']}")

    returned_at_raw = body.get("returned_at")
    if returned_at_raw is not None:
        try:
            returned_dt = parse_iso(returned_at_raw)
        except Exception:
            raise err("ERR_INVALID_INPUT", "returned_at must be ISO 8601")
    else:
        returned_dt = now()

    copy = db.copies.get(loan["copy_id"])
    if copy is None:
        raise err("ERR_NOT_FOUND", "Copy for loan no longer exists")
    bt = db.book_titles.get(copy["book_title_id"])
    if bt is None:
        raise err("ERR_NOT_FOUND", "BookTitle for copy no longer exists")

    # Effective due
    if loan.get("is_recalled") and loan.get("recall_due_at"):
        effective_due = parse_iso(loan["recall_due_at"])
    else:
        effective_due = parse_iso(loan["due_at"])

    days, accrued, daily, cap = compute_final_fine_amount(loan, bt, returned_dt)

    if returned_dt <= effective_due:
        loan["status"] = "RETURNED"
    else:
        loan["status"] = "OVERDUE_CLOSED"

    loan["returned_at"] = iso(returned_dt)
    db.stamp_update(loan)

    fine_created = None
    if accrued > 0:
        fine = {
            "loan_id": loan["id"],
            "reader_id": loan["reader_id"],
            "subject_category": bt["subject_category"],
            "daily_rate_cents": daily,
            "fine_cap_cents": cap,
            "accrued_cents": accrued,
            "waived_cents": 0,
            "paid_cents": 0,
            "outstanding_cents": accrued,
            "settlement_status": "PENDING",
        }
        db.stamp_create(fine)
        db.fines[fine["id"]] = fine
        fine_created = fine
        audit.append("FINE_ACCRUED", "Fine", fine["id"],
                     {"after": {"loan_id": loan["id"],
                                "accrued_cents": accrued,
                                "days_overdue": days}})

    # Copy: ON_LOAN -> AVAILABLE, then cascade to RESERVED if QUEUED head exists
    copy["status"] = "AVAILABLE"
    db.stamp_update(copy)
    reservations_svc.promote_next_head_for_copy(copy)

    recompute_title_aggregates(copy["book_title_id"])
    recompute_reader(loan["reader_id"])
    audit.append("LOAN_RETURNED", "Loan", loan["id"],
                 {"after": {"status": loan["status"],
                            "returned_at": loan["returned_at"],
                            "fine_id": fine_created["id"] if fine_created else None}})

    return success(serialize_loan(loan))
