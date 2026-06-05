"""ExpenseLine routes: create, get, list, delete."""
from flask import Blueprint, request, g

from common import (get_json_body, require_fields, require_string,
                    require_nonneg_int, optional_nonneg_int, require_enum,
                    parse_date, paginate, list_response, date_diff_days)
from db import store, base_fields, touch
from errors import err
from middleware import require_roles
from response import success
from services import (get_or_404, compute_line_reimbursable, recompute_card,
                      report_lines)

bp = Blueprint("lines", __name__)

LINE_TYPES = {"FLIGHT", "LODGING", "MEAL", "RENTAL_CDW", "MILEAGE"}
CABIN_CLASSES = {"ECONOMY", "BUSINESS"}


def _line_view(l):
    return dict(l)


def _owns_report(report):
    """Acting Traveler owns the report (= traveler of the report's trip)."""
    trip = store.trip_requests.get(report["trip_request_id"])
    if trip is None:
        return False
    return trip["traveler_id"] == g.user_id


def _intervals_overlap_halfopen(a_in, a_out, b_in, b_out):
    """Half-open [check_in, check_out) overlap; adjacent (out==in) allowed."""
    return a_in < b_out and b_in < a_out


@bp.route("/expense-lines", methods=["POST"])
@require_roles("Traveler")
def create_line():
    body = get_json_body()
    require_fields(body, ["report_id", "line_type", "claimed_amount_cents"])
    report_id = require_string(body, "report_id")
    # FK existence: report_id
    report = get_or_404(store.expense_reports, report_id)
    # optional FK: virtual_card_id resolved left-to-right after report
    virtual_card_id = body.get("virtual_card_id")
    card = None
    if virtual_card_id is not None:
        card = get_or_404(store.virtual_cards, virtual_card_id)
    # ownership: acting Traveler owns the report's trip
    if not _owns_report(report):
        raise err("ERR_NOT_OWNER", "Traveler does not own this report")
    # body well-formedness
    line_type = require_enum(body, "line_type", LINE_TYPES)
    claimed = require_nonneg_int(body, "claimed_amount_cents")

    # type-specific field validation (non-negative ints; enums; dates)
    cabin_class = None
    scheduled_hours = None
    advance_days = None
    check_in = None
    check_out = None
    rental_days = None
    miles = None

    if line_type == "FLIGHT":
        require_fields(body, ["cabin_class", "scheduled_hours", "advance_days"])
        cabin_class = require_enum(body, "cabin_class", CABIN_CLASSES)
        scheduled_hours = require_nonneg_int(body, "scheduled_hours")
        advance_days = require_nonneg_int(body, "advance_days")
    elif line_type == "LODGING":
        require_fields(body, ["check_in_date", "check_out_date"])
        check_in_s = require_string(body, "check_in_date")
        check_out_s = require_string(body, "check_out_date")
        parse_date(check_in_s, "check_in_date")
        parse_date(check_out_s, "check_out_date")
        check_in = check_in_s
        check_out = check_out_s
    elif line_type == "RENTAL_CDW":
        require_fields(body, ["rental_days"])
        rental_days = require_nonneg_int(body, "rental_days")
    elif line_type == "MILEAGE":
        require_fields(body, ["miles"])
        miles = require_nonneg_int(body, "miles")

    # state: report must be DRAFT to add lines
    if report["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Report is not DRAFT")

    trip = store.trip_requests.get(report["trip_request_id"])
    policy = store.travel_policies.get(trip["policy_id"]) if trip else None

    # lodging overlap check (priority 11) — vs other LODGING lines in same report
    if line_type == "LODGING":
        for other in report_lines(report_id):
            if other["line_type"] != "LODGING":
                continue
            o_in = parse_date(other["check_in_date"], "check_in_date")
            o_out = parse_date(other["check_out_date"], "check_out_date")
            n_in = parse_date(check_in, "check_in_date")
            n_out = parse_date(check_out, "check_out_date")
            if _intervals_overlap_halfopen(n_in, n_out, o_in, o_out):
                raise err("ERR_LODGING_OVERLAP", "Lodging interval overlaps another line")

    # build the line shell so reimbursable can be computed
    line = base_fields()
    line.update({
        "report_id": report_id,
        "virtual_card_id": virtual_card_id,
        "line_type": line_type,
        "claimed_amount_cents": claimed,
        "cabin_class": cabin_class,
        "scheduled_hours": scheduled_hours,
        "advance_days": advance_days,
        "check_in_date": check_in,
        "check_out_date": check_out,
        "rental_days": rental_days,
        "miles": miles,
        "reimbursable_amount_cents": 0,
        "in_policy": True,
        "settlement_status": "NONE",
        "status": "PENDING_REVIEW",
    })
    reimbursable, in_policy = compute_line_reimbursable(line, report, trip, policy)
    line["reimbursable_amount_cents"] = reimbursable
    line["in_policy"] = in_policy

    # card charging checks (priority 12 card active, 13 limit)
    if card is not None:
        if card["status"] != "ACTIVE":
            raise err("ERR_CARD_NOT_ACTIVE", "Card is not ACTIVE")
        recompute_card(card)
        if reimbursable > card["available_balance_cents"]:
            raise err("ERR_CARD_LIMIT_EXCEEDED", "Line exceeds card available balance")
        line["settlement_status"] = "PENDING"

    store.expense_lines[line["id"]] = line
    # reflect new hold on the card ledger (bump card version)
    if card is not None:
        recompute_card(card, bump=True)
    return success(_line_view(line), status=201)


@bp.route("/expense-lines/<line_id>", methods=["GET"])
@require_roles("FinanceAdmin", "Traveler", "Approver")
def get_line(line_id):
    l = get_or_404(store.expense_lines, line_id)
    return success(_line_view(l))


@bp.route("/expense-lines", methods=["GET"])
@require_roles("FinanceAdmin", "Traveler", "Approver")
def list_lines():
    limit, offset = paginate()
    items = list(store.expense_lines.values())
    report_id = request.args.get("report_id")
    virtual_card_id = request.args.get("virtual_card_id")
    if report_id is not None:
        items = [l for l in items if l["report_id"] == report_id]
    if virtual_card_id is not None:
        items = [l for l in items if l.get("virtual_card_id") == virtual_card_id]
    page, pagination = list_response(items, limit, offset)
    return success([_line_view(l) for l in page], pagination=pagination)


@bp.route("/expense-lines/<line_id>", methods=["DELETE"])
@require_roles("Traveler")
def delete_line(line_id):
    line = get_or_404(store.expense_lines, line_id)
    report = store.expense_reports.get(line["report_id"])
    # ownership
    if report is None or not _owns_report(report):
        raise err("ERR_NOT_OWNER", "Traveler does not own this line")
    # state: only from a DRAFT report
    if report["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Report is not DRAFT")
    card_id = line.get("virtual_card_id")
    held = line["settlement_status"] == "PENDING"
    del store.expense_lines[line_id]
    # release any provisional hold back to the card
    if card_id is not None and held:
        card = store.virtual_cards.get(card_id)
        if card is not None:
            recompute_card(card, bump=True)
    return success({}, status=204)
