"""Campaign-finance endpoints (PRD 3.4, 2.10 geometry B)."""
from datetime import timedelta

from flask import Blueprint

import auth
import calc
import constants
import db
import errors
import listing
import lookup
import response
import serialize
import validation

bp = Blueprint("campaign_expenses", __name__)

_BUFFER = timedelta(minutes=constants.TEARDOWN_BUFFER_MINUTES)


def _widen(start, end):
    return start - _BUFFER, end + _BUFFER


@bp.post("/campaign-expenses")
def create_expense():
    auth.require(constants.CANDIDATE)
    body = validation.get_body()

    # rule 4 — body foreign key
    candidacy = lookup.fk_candidacy(body)

    # rule 5 — schema
    validation.req_str(body, "candidacy_id")
    category = validation.req_enum(body, "category", constants.EXPENSE_CATEGORIES)
    amount_cents = validation.req_int(body, "amount_cents", minimum=0)
    incurred_at = validation.req_dt(body, "incurred_at")
    quantity = validation.opt_int(body, "quantity", default=0, minimum=0)
    shared_with_slate = validation.opt_bool(body, "shared_with_slate", default=False)
    if category == "EVENT":
        venue_code = validation.req_str(body, "venue_code")
        event_starts_at = validation.req_dt(body, "event_starts_at")
        event_ends_at = validation.req_dt(body, "event_ends_at")
    else:
        for field in ("venue_code", "event_starts_at", "event_ends_at"):
            if validation.present(body, field):
                errors.fail(errors.ERR_INVALID_REQUEST,
                            "%s is only permitted on an EVENT line." % field)
        venue_code = None
        event_starts_at = None
        event_ends_at = None

    # rule 7 — ownership
    auth.require_owner(candidacy["student_id"])

    election = db.store.elections[candidacy["election_id"]]

    # rule 9 — the referenced candidacy's posture
    if candidacy["status"] in constants.CANDIDACY_CLOSED_FOR_LEDGER:
        errors.fail(errors.ERR_INVALID_STATE,
                    "This candidacy may no longer report campaign spending.")

    # rule 15 — the pre-poll blackout, closed on both ends
    opens_at = election["voting_opens_at"]
    closes_at = election["voting_closes_at"]
    if opens_at is not None and closes_at is not None:
        blackout_start = opens_at - timedelta(hours=election["quiet_period_hours"])
        if blackout_start <= incurred_at <= closes_at:
            errors.fail(errors.ERR_QUIET_PERIOD_ACTIVE,
                        "The spend falls inside the pre-poll quiet period.")

    # rule 16 — venue collision, closed intervals widened by the teardown buffer
    if category == "EVENT":
        new_start, new_end = _widen(event_starts_at, event_ends_at)
        for other in db.store.campaign_expenses.values():
            if other["category"] != "EVENT" or other["venue_code"] != venue_code:
                continue
            if other["status"] not in ("REPORTED", "APPROVED"):
                continue
            other_candidacy = db.store.candidacies.get(other["candidacy_id"])
            if other_candidacy is None or other_candidacy["election_id"] != election["id"]:
                continue
            other_start, other_end = _widen(other["event_starts_at"], other["event_ends_at"])
            if new_start <= other_end and other_start <= new_end:
                errors.fail(errors.ERR_VENUE_DOUBLE_BOOKED,
                            "The venue is already booked for a colliding interval.")

    # rule 31 — the poster ceiling
    prospective_posters = calc.poster_count_of(candidacy["id"])
    if category == "POSTER":
        prospective_posters += quantity
    if prospective_posters > election["poster_cap"]:
        errors.fail(errors.ERR_POSTER_CAP_EXCEEDED,
                    "The poster cap would be exceeded.")

    # rule 32 — the spending ceiling, scoped to the reporting candidacy only
    if calc.provisional_committed(candidacy, amount_cents) > election["spending_cap_cents"]:
        errors.fail(errors.ERR_SPENDING_CAP_EXCEEDED,
                    "The spending cap would be exceeded.")

    row = db.new_row(db.store.campaign_expenses, {
        "candidacy_id": candidacy["id"],
        "category": category,
        "amount_cents": amount_cents,
        "quantity": quantity,
        "shared_with_slate": shared_with_slate,
        "incurred_at": incurred_at,
        "venue_code": venue_code,
        "event_starts_at": event_starts_at,
        "event_ends_at": event_ends_at,
        "status": "REPORTED",
        "approved_by_user_id": None,
    })
    calc.recompute_spend_group(candidacy)
    return response.object_response(serialize.expense(row), 201)


@bp.get("/campaign-expenses")
def list_expenses():
    auth.require_any()
    rows = listing.filtered(db.store.campaign_expenses, {
        "candidacy_id": ("candidacy_id", None),
        "status": ("status", None),
        "category": ("category", None),
    })
    return listing.list_response(rows, serialize.expense)


@bp.get("/campaign-expenses/<campaign_expense_id>")
def read_expense(campaign_expense_id):
    auth.require_any()
    row = lookup.expense(campaign_expense_id)
    return response.object_response(serialize.expense(row))


@bp.post("/campaign-expenses/<campaign_expense_id>/approve")
def approve_expense(campaign_expense_id):
    user_id, _role = auth.require(constants.ELECTION_COMMISSIONER)
    expense = lookup.expense(campaign_expense_id)
    candidacy = db.store.candidacies[expense["candidacy_id"]]

    if expense["status"] != "REPORTED":
        errors.fail(errors.ERR_INVALID_STATE,
                    "Only a REPORTED expense may be approved.")
    if candidacy["status"] in constants.CANDIDACY_CLOSED_FOR_LEDGER:
        errors.fail(errors.ERR_INVALID_STATE,
                    "This candidacy's ledger may no longer be approved against.")

    db.set_fields(expense, status="APPROVED", approved_by_user_id=user_id)
    db.touch(expense)
    calc.recompute_spend_group(candidacy)
    return response.object_response(serialize.expense(expense))


@bp.post("/campaign-expenses/<campaign_expense_id>/reverse")
def reverse_expense(campaign_expense_id):
    auth.require(constants.ELECTION_COMMISSIONER)
    expense = lookup.expense(campaign_expense_id)
    candidacy = db.store.candidacies[expense["candidacy_id"]]

    body = validation.get_body()
    validation.opt_text(body, "reason")

    # a candidacy in any posture may have its ledger corrected
    if expense["status"] not in ("REPORTED", "APPROVED"):
        errors.fail(errors.ERR_INVALID_STATE,
                    "Only a REPORTED or APPROVED expense may be reversed.")

    db.set_fields(expense, status="REVERSED")
    db.touch(expense)
    calc.recompute_spend_group(candidacy)
    return response.object_response(serialize.expense(expense))
