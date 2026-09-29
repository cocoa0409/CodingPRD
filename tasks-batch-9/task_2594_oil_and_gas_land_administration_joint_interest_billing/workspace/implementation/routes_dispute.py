"""Audit rights, the dispute exchange and the fate of a bill (PRD 3.7)."""
from flask import Blueprint

from calc import (DISPUTE_REBUTTAL_DAYS, DISPUTE_RESPONSE_DAYS,
                  LIVE_DISPUTE_STATUSES, MAX_DISPUTE_ROUNDS, active_position,
                  add_billed, db, get_dispute, get_owner, get_statement,
                  guard_terminal, has_live_dispute, statement_disputes,
                  statement_line_items)
from common import add_days, now_ts, ok, ok_list, today, touch
from errors import fail
from jib_engine import create_draft_statement, revision_number
from store import by_created, insert, out_dispute, rows
from validate import (READ_ALL, ROLE_AUDIT, ROLE_JIA, ROLE_PARTNER,
                      acting_user, authenticate, authorize, body, filt,
                      is_partner, pagination, present, require, v_cents,
                      v_enum, v_id, v_str, window)

bp = Blueprint("disputes", __name__)

DISPUTE_KINDS = ("AUDIT_EXCEPTION", "BILLING_DISPUTE")
EXCHANGE_TYPES = ("OPERATOR_RESPONSE", "PARTNER_REBUTTAL", "PARTNER_ESCALATION")
OUTCOMES = ("UPHELD", "ADJUSTED")


def release_statement_if_clear(statement, exclude_id=None):
    """A statement returns DISPUTED -> ISSUED once no live dispute remains."""
    if statement["statement_status"] != "DISPUTED":
        return
    if has_live_dispute(statement["id"], exclude_id=exclude_id):
        return
    statement["statement_status"] = "ISSUED"
    touch(statement)


@bp.route("/jib-statements/<statement_id>/disputes", methods=["POST"])
def file_dispute(statement_id):
    authenticate()
    authorize(ROLE_PARTNER, ROLE_AUDIT)
    data = body()
    require(data, ["owner_id", "dispute_kind", "disputed_amount_cents",
                   "basis_note"])
    owner_id = v_id(data, "owner_id")
    dispute_kind = v_enum(data, "dispute_kind", DISPUTE_KINDS)
    disputed_amount_cents = v_cents(data, "disputed_amount_cents")
    basis_note = v_str(data, "basis_note", 1, 500)

    statement = get_statement(statement_id)
    owner = get_owner(owner_id)
    if is_partner() and acting_user() != owner["id"]:
        fail("ERR_OWNER_MISMATCH")
    guard_terminal("statement", statement)

    if statement["statement_status"] not in ("ISSUED", "DISPUTED"):
        fail("ERR_STATEMENT_NOT_DISPUTABLE")

    now_date = today()
    if dispute_kind == "AUDIT_EXCEPTION":
        issued_at = statement.get("issued_at")
        limit_date = (add_days(issued_at.date(), owner["audit_window_days"])
                      if issued_at is not None else None)
        if limit_date is None or now_date > limit_date:
            fail("ERR_AUDIT_WINDOW_EXPIRED")
    else:
        due = statement.get("payment_due_date")
        if due is None or now_date > due:
            fail("ERR_DISPUTE_WINDOW_EXPIRED")

    for existing in statement_disputes(statement["id"]):
        if existing["owner_id"] == owner["id"] \
                and existing["dispute_status"] in LIVE_DISPUTE_STATUSES:
            fail("ERR_DUPLICATE_OPEN_DISPUTE")

    if active_position(statement["well_id"], owner["id"]) is None:
        fail("ERR_NOT_AN_INTEREST_HOLDER")

    billed = None
    for line in statement_line_items(statement["id"]):
        if line["owner_id"] == owner["id"]:
            billed = line["total_billed_cents"]
            break
    if disputed_amount_cents <= 0 or billed is None \
            or disputed_amount_cents > billed:
        fail("ERR_DISPUTE_AMOUNT_EXCEEDS_BILL")

    filed_at = now_ts()
    response_due = add_days(filed_at.date(), DISPUTE_RESPONSE_DAYS)
    dispute = insert("disputes", {
        "statement_id": statement["id"],
        "owner_id": owner["id"],
        "dispute_kind": dispute_kind,
        "disputed_amount_cents": disputed_amount_cents,
        "basis_note": basis_note,
        "filed_at": filed_at,
        "response_due_date": response_due,
        "rebuttal_due_date": add_days(response_due, DISPUTE_REBUTTAL_DAYS),
        "operator_responded_at": None,
        "round_count": 0,
        "dispute_status": "OPEN",
        "adjustment_amount_cents": 0,
        "resolved_by_user_id": None,
        "deemed_in_favor_of_partner": False,
    })
    if statement["statement_status"] != "DISPUTED":
        statement["statement_status"] = "DISPUTED"
        touch(statement)
    return ok(out_dispute(dispute), 201)


@bp.route("/disputes", methods=["GET"])
def list_disputes():
    authenticate()
    authorize(*READ_ALL)
    limit, offset = pagination()
    found = rows("disputes")
    for name in ("statement_id", "owner_id", "dispute_status", "dispute_kind"):
        value = filt(name)
        if value is not None:
            found = [d for d in found if d[name] == value]
    found = by_created(found)
    page, total = window(found, limit, offset)
    return ok_list([out_dispute(d) for d in page], limit, offset, total)


@bp.route("/disputes/<dispute_id>", methods=["GET"])
def read_dispute(dispute_id):
    authenticate()
    authorize(*READ_ALL)
    return ok(out_dispute(get_dispute(dispute_id)))


@bp.route("/disputes/<dispute_id>/exchanges", methods=["POST"])
def record_exchange(dispute_id):
    authenticate()
    authorize(ROLE_JIA, ROLE_PARTNER, ROLE_AUDIT)
    data = body()
    require(data, ["exchange_type", "exchange_note"])
    exchange_type = v_enum(data, "exchange_type", EXCHANGE_TYPES)
    v_str(data, "exchange_note", 1, 500)
    restated = v_cents(data, "disputed_amount_cents")

    dispute = get_dispute(dispute_id)
    if is_partner() and acting_user() != dispute["owner_id"]:
        fail("ERR_OWNER_MISMATCH")
    guard_terminal("dispute", dispute)

    now_date = today()
    if exchange_type == "OPERATOR_RESPONSE":
        if dispute["dispute_status"] != "OPEN":
            fail("ERR_DISPUTE_NOT_OPEN")
        if now_date > dispute["response_due_date"]:
            fail("ERR_DISPUTE_DEADLINE_PASSED")
        responded_at = now_ts()
        dispute["operator_responded_at"] = responded_at
        dispute["rebuttal_due_date"] = add_days(responded_at.date(),
                                               DISPUTE_REBUTTAL_DAYS)
        dispute["dispute_status"] = "OPERATOR_RESPONDED"
    elif exchange_type == "PARTNER_REBUTTAL":
        if dispute["dispute_status"] != "OPERATOR_RESPONDED":
            fail("ERR_DISPUTE_NOT_RESOLVABLE")
        if now_date > dispute["rebuttal_due_date"]:
            fail("ERR_REBUTTAL_DEADLINE_PASSED")
        if dispute["round_count"] >= MAX_DISPUTE_ROUNDS:
            fail("ERR_MAX_DISPUTE_ROUNDS_EXCEEDED")
        dispute["dispute_status"] = "OPEN"
        dispute["round_count"] = dispute["round_count"] + 1
        dispute["operator_responded_at"] = None
        dispute["response_due_date"] = add_days(now_date, DISPUTE_RESPONSE_DAYS)
    else:
        if dispute["dispute_status"] != "OPERATOR_RESPONDED":
            fail("ERR_DISPUTE_NOT_RESOLVABLE")
        if now_date > dispute["rebuttal_due_date"]:
            fail("ERR_REBUTTAL_DEADLINE_PASSED")
        dispute["dispute_status"] = "ESCALATED"

    if restated is not None:
        dispute["disputed_amount_cents"] = restated
    touch(dispute)
    return ok(out_dispute(dispute))


@bp.route("/disputes/<dispute_id>/resolution", methods=["POST"])
def resolve(dispute_id):
    authenticate()
    authorize(ROLE_AUDIT)
    data = body()
    require(data, ["outcome", "adjustment_amount_cents"])
    outcome = v_enum(data, "outcome", OUTCOMES)
    adjustment = v_cents(data, "adjustment_amount_cents")

    dispute = get_dispute(dispute_id)
    statement = db.statements[dispute["statement_id"]]
    if acting_user() == statement["prepared_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")
    guard_terminal("dispute", dispute)

    if dispute["dispute_status"] not in ("OPERATOR_RESPONDED", "ESCALATED"):
        fail("ERR_DISPUTE_NOT_RESOLVABLE")
    if outcome == "UPHELD" and dispute["deemed_in_favor_of_partner"]:
        fail("ERR_DISPUTE_NOT_RESOLVABLE")

    if outcome == "UPHELD":
        if adjustment != 0:
            fail("ERR_ADJUSTMENT_EXCEEDS_DISPUTE")
    else:
        if adjustment <= 0 or adjustment > dispute["disputed_amount_cents"]:
            fail("ERR_ADJUSTMENT_EXCEEDS_DISPUTE")

    dispute["resolved_by_user_id"] = acting_user()
    if outcome == "UPHELD":
        dispute["dispute_status"] = "RESOLVED_UPHELD"
        dispute["adjustment_amount_cents"] = 0
        touch(dispute)
        release_statement_if_clear(statement, exclude_id=dispute["id"])
        return ok(out_dispute(dispute))

    dispute["dispute_status"] = "RESOLVED_ADJUSTED"
    dispute["adjustment_amount_cents"] = adjustment
    touch(dispute)

    well = db.wells[statement["well_id"]]
    add_billed(well, -statement["total_billed_cents"])

    statement["statement_status"] = "ADJUSTED"
    touch(statement)

    create_draft_statement(
        statement["well_id"],
        revision_number(statement["well_id"], statement["statement_number"]),
        statement["billing_period_start"], statement["billing_period_end"],
        statement["cost_basis"], statement["activity_class"],
        statement["overhead_rate_class"], acting_user(),
        superseded_statement_id=statement["id"])

    for other in statement_disputes(statement["id"]):
        if other["id"] == dispute["id"]:
            continue
        if other["dispute_status"] in LIVE_DISPUTE_STATUSES:
            other["dispute_status"] = "EXPIRED"
            other["deemed_in_favor_of_partner"] = True
            touch(other)
    return ok(out_dispute(dispute))
