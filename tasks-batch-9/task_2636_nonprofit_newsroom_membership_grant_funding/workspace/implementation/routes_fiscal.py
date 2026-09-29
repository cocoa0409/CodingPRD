"""Fiscal period endpoints (§3.1, §3.9) and the logical clock / daily sweep."""

from flask import Blueprint

import calc
import derive
import guards
from core import (
    DB, ROLE_BOARD_OVERSIGHT, ROLE_DEVELOPMENT_OFFICER, ROLE_EDITORIAL_DIRECTOR,
    ROLE_FINANCE_CONTROLLER, STATE, apply_changes, authenticate, body,
    check_date_order, clock_date, fail, iso_date, iso_ms, list_response, lookup,
    new_row, now_clock, object_response, pagination, paginate, parse_date,
    parse_instant, public, q_enum, rows, touch, v_date, v_enum, v_int, v_str,
)

bp = Blueprint("fiscal", __name__)

READ_ROLES = (ROLE_FINANCE_CONTROLLER, ROLE_BOARD_OVERSIGHT,
              ROLE_EDITORIAL_DIRECTOR, ROLE_DEVELOPMENT_OFFICER)


def finalize_create(row):
    """A create is one mutation: version 1 with updated_at == created_at, even
    when the computed fields were derived by a recompute pass."""
    row["version"] = 1
    row["updated_at"] = row["created_at"]
    return row


def get_period(period_id):
    return lookup("fiscal_periods", period_id, "ERR_FISCAL_PERIOD_NOT_FOUND")


@bp.post("/fiscal-periods")
def create_fiscal_period():
    authenticate(ROLE_FINANCE_CONTROLLER)
    data = body()
    label = v_str(data, "label", min_len=1, max_len=32)
    guards.require_unique("fiscal_periods", "label", label, "label must be unique")
    start_date = v_date(data, "start_date")
    end_date = v_date(data, "end_date")
    monthly_expense_base_cents = v_int(data, "monthly_expense_base_cents", minimum=1)
    reserve_balance_cents = v_int(data, "reserve_balance_cents", required=False,
                                 minimum=0, default=0)
    check_date_order(start_date, end_date, strict=True)

    period = new_row("fiscal_periods", {
        "label": label,
        "start_date": iso_date(start_date),
        "end_date": iso_date(end_date),
        "status": "OPEN",
        "monthly_expense_base_cents": monthly_expense_base_cents,
        "reserve_balance_cents": reserve_balance_cents,
        "recognized_revenue_cents": 0,
        "stream_shares_bps": {key: 0 for key in calc.STREAM_KEYS},
        "concentration_hhi": 0,
        "top_source_share_bps": 0,
        "reserve_months_target": calc.RESERVE_MONTHS_BASE,
        "operating_reserve_target_cents": 0,
        "reserve_months_ratio_bps": 0,
        "sustainability_posture": "HEALTHY",
        "restricted_release_cap_pct_bps": 10000,
        "board_override_active": False,
        "board_override_justification": None,
        "locked_at": None,
    })
    derive.recompute_period(period)
    return object_response(public(finalize_create(period)), 201)


@bp.get("/fiscal-periods/<period_id>")
def read_fiscal_period(period_id):
    authenticate(*READ_ROLES)
    return object_response(public(get_period(period_id)))


@bp.get("/fiscal-periods")
def list_fiscal_periods():
    authenticate(*READ_ROLES)
    status = q_enum("status", calc.PERIOD_STATUSES)
    limit, offset = pagination()
    items = [p for p in rows("fiscal_periods")
             if status is None or p.get("status") == status]
    # Newest start_date first.
    items.sort(key=lambda p: (p.get("start_date") or "",), reverse=True)
    page, total = paginate(items, limit, offset)
    return list_response([public(p) for p in page], total, limit, offset)


@bp.post("/fiscal-periods/<period_id>/status-actions")
def fiscal_period_status_actions(period_id):
    authenticate(ROLE_FINANCE_CONTROLLER)
    period = get_period(period_id)
    data = body()
    action = v_enum(data, "action", ("LOCK", "UNLOCK", "CLOSE"))

    guards.require_not_terminal(period["status"], calc.PERIOD_TERMINAL, "fiscal period")
    if action == "LOCK":
        guards.require_state(period["status"], ("OPEN",), "fiscal period")
    elif action == "UNLOCK":
        guards.require_state(period["status"], ("REVIEW_LOCKED",), "fiscal period")
    else:
        guards.require_state(period["status"], ("REVIEW_LOCKED",), "fiscal period")

    if action == "CLOSE":
        for contribution in DB["contributions"].values():
            if (contribution.get("fiscal_period_id") == period["id"]
                    and contribution.get("settlement_status") == "INITIATED"):
                fail("ERR_UNSETTLED_CONTRIBUTIONS",
                     "a contribution of this period is still INITIATED")
        if (int(period["reserve_months_ratio_bps"]) < 10000
                and not period.get("board_override_active")):
            fail("ERR_RESERVE_FLOOR_BREACH",
                 "the reserve holds less than one month of the expense base")
        apply_changes(period, {"status": "CLOSED"})
    elif action == "UNLOCK":
        apply_changes(period, {"status": "OPEN", "locked_at": None})
    else:
        total, shares, hhi, top_source = calc.revenue_diversification_index(
            period, "RECOGNIZED")
        if (hhi >= calc.CONCENTRATION_BOARD_FLOOR_HHI
                and not period.get("board_override_active")):
            fail("ERR_CONCENTRATION_BOARD_REVIEW_REQUIRED",
                 "concentration_hhi %s requires a board override before locking" % hhi)
        derive.recompute_period(period, extra={
            "status": "REVIEW_LOCKED",
            "locked_at": iso_ms(now_clock()),
        })
    return object_response(public(period))


@bp.post("/fiscal-periods/<period_id>/board-override")
def fiscal_period_board_override(period_id):
    authenticate(ROLE_BOARD_OVERSIGHT)
    period = get_period(period_id)
    data = body()
    justification = v_str(data, "justification", min_len=1)

    guards.require_not_terminal(period["status"], calc.PERIOD_TERMINAL, "fiscal period")
    warranted = (int(period["concentration_hhi"]) >= calc.CONCENTRATION_BOARD_FLOOR_HHI
                 or period["sustainability_posture"] in ("CONSTRAINED", "CRITICAL"))
    if not warranted or period.get("board_override_active"):
        fail("ERR_BOARD_OVERRIDE_NOT_WARRANTED",
             "no override is warranted for this period, or one is already on file")
    apply_changes(period, {
        "board_override_active": True,
        "board_override_justification": justification,
    })
    return object_response(public(period))


@bp.get("/fiscal-periods/<period_id>/sustainability")
def fiscal_period_sustainability(period_id):
    authenticate(ROLE_FINANCE_CONTROLLER, ROLE_BOARD_OVERSIGHT, ROLE_EDITORIAL_DIRECTOR)
    period = get_period(period_id)
    basis = q_enum("basis", ("RECOGNIZED", "PIPELINE")) or "RECOGNIZED"
    return object_response(derive.sustainability_view(period, basis))


# ---------------------------------------------------------------------------
# Logical clock and the daily sweep
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate(ROLE_FINANCE_CONTROLLER, ROLE_EDITORIAL_DIRECTOR,
                 ROLE_DEVELOPMENT_OFFICER, ROLE_BOARD_OVERSIGHT)
    data = body()
    raw_value = data.get("current_utc")
    if raw_value is None:
        fail("ERR_INVALID_REQUEST", "current_utc is required")
    candidate = parse_instant(raw_value)
    if candidate is None:
        fail("ERR_INVALID_REQUEST", "current_utc must be an ISO 8601 UTC instant")
    previous = now_clock()
    if candidate < previous:
        fail("ERR_CLOCK_REWIND", "the logical clock may never move backwards")
    STATE["clock"] = candidate
    return object_response({
        "current_utc": iso_ms(candidate),
        "previous_utc": iso_ms(previous),
    })


@bp.post("/ops/daily-sweep")
def daily_sweep():
    authenticate(ROLE_FINANCE_CONTROLLER)
    counters = {
        "members_moved_to_grace": 0,
        "members_moved_to_lapsed": 0,
        "reports_moved_to_overdue": 0,
        "proposals_suspended": 0,
        "funders_restricted": 0,
    }
    today = clock_date()

    for member in rows("members"):
        if member.get("status") != "ACTIVE":
            continue
        next_renewal = parse_date(member.get("next_renewal_date"))
        if next_renewal is None or not today > next_renewal:
            continue
        tier = DB["membership_tiers"].get(member.get("tier_id"))
        _, grace_expires = calc.member_renewal_schedule(
            parse_date(member.get("cycle_start_date")),
            tier["renewal_cadence"] if tier else "ANNUAL",
            tier.get("grace_period_days") if tier else 0)
        apply_changes(member, {
            "status": "GRACE",
            "grace_expires_at": iso_ms(grace_expires),
        })
        counters["members_moved_to_grace"] += 1

    for member in rows("members"):
        if member.get("status") != "GRACE":
            continue
        grace_expires = parse_instant(member.get("grace_expires_at"))
        if grace_expires is None or now_clock() < grace_expires:
            continue
        apply_changes(member, {
            "status": "LAPSED",
            "consecutive_renewals": 0,
            "grace_expires_at": None,
        })
        counters["members_moved_to_lapsed"] += 1

    for report in rows("grant_reports"):
        if report.get("status") != "SCHEDULED":
            continue
        due_date = parse_date(report.get("due_date"))
        if due_date is None or not due_date < today:
            continue
        derive.report_delinquency_cascade(report, counters)

    result = {"swept_at": iso_ms(now_clock())}
    result.update(counters)
    return object_response(result)
