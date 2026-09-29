"""JIB statements: drafting, issuance, revision, void and settlement
(PRD 3.5, 3.6, 3.7)."""
from flask import Blueprint

from calc import (BILLED_STATEMENT_STATUSES, db, get_statement, get_well,
                  guard_terminal, has_live_dispute, recompute_statement_totals,
                  reverse_issued_statement, statement_cost_pool,
                  statement_line_items, well_statements)
from common import ok, ok_list, today, touch
from errors import fail
from jib_engine import create_draft_statement, issue_statement
from store import by_created, out_line_item, out_statement, rows
from validate import (READ_ALL, ROLE_JIA, acting_user, authenticate, authorize,
                      body, filt, pagination, present, require, v_date, v_enum,
                      v_int, v_str, window)

bp = Blueprint("statements", __name__)

COST_BASES = ("ACCRUAL", "CASH")
ACTIVITY_CLASSES = ("DRILLING", "PRODUCING")
OVERHEAD_RATE_CLASSES = ("FIXED_RATE", "PERCENTAGE_BASIS")

PRODUCING_POSTURES = ("PRODUCING", "SHUT_IN", "TEMPORARILY_ABANDONED")


def periods_intersect(start_a, end_a, start_b, end_b):
    """Closed intervals: touching endpoints collide."""
    return start_a <= end_b and start_b <= end_a


@bp.route("/wells/<well_id>/jib-statements", methods=["POST"])
def open_statement(well_id):
    authenticate()
    authorize(ROLE_JIA)
    data = body()
    require(data, ["statement_number", "billing_period_start",
                   "billing_period_end", "cost_basis", "activity_class",
                   "overhead_rate_class"])
    statement_number = v_str(data, "statement_number", 1, 32)
    period_start = v_date(data, "billing_period_start")
    period_end = v_date(data, "billing_period_end")
    cost_basis = v_enum(data, "cost_basis", COST_BASES)
    activity_class = v_enum(data, "activity_class", ACTIVITY_CLASSES)
    overhead_rate_class = v_enum(data, "overhead_rate_class", OVERHEAD_RATE_CLASSES)

    well = get_well(well_id)
    guard_terminal("well", well)

    if period_start > period_end:
        fail("ERR_PERIOD_INVALID")
    for existing in well_statements(well["id"]):
        if existing["statement_status"] == "VOID":
            continue
        if periods_intersect(period_start, period_end,
                             existing["billing_period_start"],
                             existing["billing_period_end"]):
            fail("ERR_STATEMENT_PERIOD_OVERLAP")

    statement = create_draft_statement(well["id"], statement_number, period_start,
                                       period_end, cost_basis, activity_class,
                                       overhead_rate_class, acting_user())
    return ok(out_statement(statement), 201)


@bp.route("/jib-statements", methods=["GET"])
def list_statements():
    authenticate()
    authorize(*READ_ALL)
    limit, offset = pagination()
    found = rows("statements")
    for name in ("well_id", "superseded_statement_id", "statement_status",
                 "cost_basis"):
        value = filt(name)
        if value is not None:
            found = [s for s in found if s[name] == value]
    found = by_created(found)
    page, total = window(found, limit, offset)
    return ok_list([out_statement(s) for s in page], limit, offset, total)


@bp.route("/jib-statements/<statement_id>", methods=["GET"])
def read_statement(statement_id):
    authenticate()
    authorize(*READ_ALL)
    return ok(out_statement(get_statement(statement_id)))


@bp.route("/jib-statements/<statement_key>/line-items", methods=["GET"])
def list_line_items(statement_key):
    authenticate()
    authorize(*READ_ALL)
    limit, offset = pagination()
    statement = get_statement(statement_key)
    found = statement_line_items(statement["id"])
    owner_id = filt("owner_id")
    if owner_id is not None:
        found = [l for l in found if l["owner_id"] == owner_id]
    page, total = window(found, limit, offset)
    return ok_list([out_line_item(l) for l in page], limit, offset, total)


@bp.route("/jib-statements/<statement_id>/issuance", methods=["POST"])
def issue(statement_id):
    authenticate()
    authorize(ROLE_JIA)
    statement = get_statement(statement_id)
    guard_terminal("statement", statement)
    well = db.wells[statement["well_id"]]

    if statement["statement_status"] != "DRAFT":
        fail("ERR_STATEMENT_NOT_DRAFT")
    if well["pooling_status"] != "POOLED_EFFECTIVE":
        fail("ERR_WELL_NOT_POOLED")
    if well["well_status"] in ("PROPOSED", "PLUGGED"):
        fail("ERR_WELL_INVALID_STATUS")
    if statement["activity_class"] == "DRILLING":
        if well["well_status"] != "DRILLING":
            fail("ERR_WELL_INVALID_STATUS")
    else:
        if well["well_status"] not in PRODUCING_POSTURES:
            fail("ERR_WELL_INVALID_STATUS")
    if not statement["billing_period_end"] < today():
        fail("ERR_PERIOD_NOT_CLOSED")
    for existing in well_statements(well["id"]):
        if existing["id"] == statement["id"]:
            continue
        if existing["statement_status"] not in BILLED_STATEMENT_STATUSES:
            continue
        if periods_intersect(statement["billing_period_start"],
                             statement["billing_period_end"],
                             existing["billing_period_start"],
                             existing["billing_period_end"]):
            fail("ERR_STATEMENT_PERIOD_OVERLAP")
    pool, _capital, _operating = statement_cost_pool(statement)
    if not pool:
        fail("ERR_NO_BILLABLE_COSTS")

    issue_statement(statement)
    return ok(out_statement(statement))


@bp.route("/jib-statements/<statement_id>/revisions", methods=["POST"])
def revise(statement_id):
    authenticate()
    authorize(ROLE_JIA)
    data = body()
    require(data, ["statement_number", "expected_jib_statement_version"])
    statement_number = v_str(data, "statement_number", 1, 32)
    expected_version = v_int(data, "expected_jib_statement_version")
    cost_basis = v_enum(data, "cost_basis", COST_BASES)
    activity_class = v_enum(data, "activity_class", ACTIVITY_CLASSES)
    overhead_rate_class = v_enum(data, "overhead_rate_class", OVERHEAD_RATE_CLASSES)

    statement = get_statement(statement_id)
    if expected_version != statement["version"]:
        fail("ERR_STALE_STATEMENT_VERSION")
    guard_terminal("statement", statement)
    if statement["statement_status"] not in ("DRAFT", "ISSUED"):
        fail("ERR_STATEMENT_NOT_VOIDABLE")

    was_issued = statement["statement_status"] == "ISSUED"
    if was_issued:
        reverse_issued_statement(statement)

    statement["statement_status"] = "ADJUSTED"
    touch(statement)

    replacement = create_draft_statement(
        statement["well_id"], statement_number,
        statement["billing_period_start"], statement["billing_period_end"],
        cost_basis or statement["cost_basis"],
        activity_class or statement["activity_class"],
        overhead_rate_class or statement["overhead_rate_class"],
        acting_user(), superseded_statement_id=statement["id"])
    return ok(out_statement(replacement), 201)


@bp.route("/jib-statements/<statement_id>/void", methods=["POST"])
def void(statement_id):
    authenticate()
    authorize(ROLE_JIA)
    data = body()
    require(data, ["void_reason"])
    v_str(data, "void_reason", 1)
    statement = get_statement(statement_id)
    guard_terminal("statement", statement)
    if statement["statement_status"] not in ("DRAFT", "ISSUED"):
        fail("ERR_STATEMENT_NOT_VOIDABLE")

    if statement["statement_status"] == "ISSUED":
        reverse_issued_statement(statement)
    statement["statement_status"] = "VOID"
    touch(statement)
    return ok(out_statement(statement))


@bp.route("/jib-statements/<statement_id>/settlement", methods=["POST"])
def settle(statement_id):
    authenticate()
    authorize(ROLE_JIA)
    data = body()
    require(data, ["settled_on"])
    settled_on = v_date(data, "settled_on")
    statement = get_statement(statement_id)
    guard_terminal("statement", statement)

    if statement["statement_status"] != "ISSUED" or has_live_dispute(statement["id"]):
        fail("ERR_STATEMENT_NOT_SETTLEABLE")
    if settled_on > today():
        fail("ERR_EFFECTIVE_DATE_OUT_OF_RANGE")

    statement["statement_status"] = "SETTLED"
    touch(statement)
    return ok(out_statement(statement))
