"""Plan orders: creation, submission, review, confirmation, cancellation,
relocation and payments."""
from datetime import timedelta

from flask import Blueprint

import calc
from core import (D, ROLE_ADMIN, ROLE_HOLDER, ROLE_REVENUE, ROLE_SALES, READ_ROLES, apply_filters,
                  bad_request, body, bump, base_fields, days, db, endpoint, err, find_account,
                  find_order, find_plan, find_seat, new_id, now, ok, ok_page, opt_number, opt_str,
                  pagination, paginate, req_enum, req_id_list, req_int, req_str, rhu, sort_created)
from routes_accounts import gate_account_written_off, gate_holder_ownership, gate_rep_ownership
from routes_holds import release_hold, seat_free_for_account
from routes_setup import gate_selling, gate_status

bp = Blueprint("orders", __name__)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def gate_order_status(order, allowed):
    if order["order_status"] not in allowed:
        err("ERR_ORDER_STATE_INVALID", 409,
            "Order is %s; this operation requires %s." % (order["order_status"], " or ".join(allowed)))


def gate_not_delinquent(order):
    if order["payment_status"] == "DELINQUENT":
        err("ERR_ORDER_DELINQUENT", 409, "The order is delinquent.")


def check_seat_season(seat_ids, plan):
    for sid in seat_ids:
        seat = db.seats.get(sid)
        if seat is None or seat["season_id"] != plan["season_id"]:
            err("ERR_SEAT_SEASON_MISMATCH", 422, "Every seat must belong to the plan's season.")


def check_single_zone(seat_ids):
    zones = set(db.seats[sid]["price_zone"] for sid in seat_ids if sid in db.seats)
    if len(zones) > 1:
        err("ERR_ZONE_MISMATCH", 422, "All seats on one order must share a single price zone.")


def account_snapshot(account):
    return (account["billing_status"], account["service_status"], account["churn_risk_rolling"],
            account["loyalty_credit_cents"], account["lifetime_value_cents"],
            account["past_due_since_utc"], account["at_risk_since_utc"],
            account["renewal_priority_active"], account["transfer_count_season"])


def bump_if_changed(account, before):
    if account is not None and account_snapshot(account) != before:
        bump(account)


def other_delinquent_order(account_id, exclude_order_id):
    for order in db.orders.values():
        if order["id"] == exclude_order_id or order["account_id"] != account_id:
            continue
        if order["payment_status"] == "DELINQUENT":
            return True
    return False


def cure_billing(account, exclude_order_id):
    """PAST_DUE -> CURRENT once no order of the account remains DELINQUENT."""
    if account is None or account["billing_status"] != "PAST_DUE":
        return
    if other_delinquent_order(account["id"], exclude_order_id):
        return
    account["billing_status"] = "CURRENT"
    account["past_due_since_utc"] = None


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
@bp.route("/ticketing/plan-orders/<order_id>", methods=["GET"])
@endpoint(*READ_ROLES)
def get_order(caller, order_id):
    return ok(find_order(order_id))


@bp.route("/ticketing/plan-orders", methods=["GET"])
@endpoint(*READ_ROLES)
def list_orders(caller):
    limit, offset = pagination()
    rows = apply_filters(list(db.orders.values()), [
        ("account_id", "account_id"), ("plan_id", "plan_id"),
        ("order_status", "order_status"), ("payment_status", "payment_status")])
    rows = sort_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_page(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------
@bp.route("/ticketing/plan-orders", methods=["POST"])
@endpoint(ROLE_SALES)
def create_order(caller):
    data = body()
    account_id = req_str(data, "account_id")
    plan_id = req_str(data, "plan_id")
    seat_ids = req_id_list(data, "seat_ids")
    discount_pct = opt_number(data, "discount_pct", default=0, minimum=0)

    for sid in seat_ids:
        find_seat(sid)
    plan = find_plan(plan_id)
    account = find_account(account_id)

    gate_rep_ownership(caller, account)

    season = db.seasons.get(plan["season_id"])
    gate_selling(season)

    if plan["plan_status"] != "PUBLISHED":
        err("ERR_PLAN_NOT_PUBLISHED", 409, "Orders may only be written against a PUBLISHED plan.")

    for sid in seat_ids:
        if not seat_free_for_account(db.seats[sid], account_id):
            err("ERR_SEAT_NOT_AVAILABLE", 409, "Seat %s is not available." % sid)

    gate_account_written_off(account)

    check_seat_season(seat_ids, plan)

    if not (plan["min_seats"] <= len(seat_ids) <= plan["max_seats"]):
        err("ERR_SEAT_COUNT_OUT_OF_RANGE", 422,
            "The plan requires between %d and %d seats." % (plan["min_seats"], plan["max_seats"]))

    check_single_zone(seat_ids)

    if D(discount_pct) > D(calc.MAX_REP_DISCOUNT_PCT):
        err("ERR_DISCOUNT_LIMIT_EXCEEDED", 422, "discount_pct may not exceed 0.25.")

    quoted = calc.plan_order_total(plan, seat_ids, account, discount_pct,
                                   season["dynamic_pricing_mode"], "QUOTED")

    order = {"id": new_id(), "account_id": account_id, "plan_id": plan_id,
             "seat_ids": list(seat_ids), "discount_pct": discount_pct,
             "order_status": "DRAFT", "payment_status": "NOT_STARTED",
             "quoted_total_cents": quoted, "final_total_cents": 0, "amount_paid_cents": 0,
             "installment_count": None, "installments": [], "submitted_by_user_id": None,
             "reviewed_by_user_id": None, "cancelled_reason": None}
    order.update(base_fields())
    db.orders[order["id"]] = order

    window_start = now()
    window_end = window_start + timedelta(hours=calc.ORDER_HOLD_DURATION_HOURS)
    for sid in seat_ids:
        already = None
        for hold in db.holds.values():
            if hold["seat_id"] == sid and hold["hold_status"] == "ACTIVE" and hold["account_id"] == account_id:
                already = hold
                break
        if already is not None:
            continue
        row = {"id": new_id(), "seat_id": sid, "account_id": account_id,
               "origin_order_id": order["id"], "hold_type": "ORDER_HOLD",
               "hold_window_start_utc": window_start, "hold_window_end_utc": window_end,
               "hold_status": "ACTIVE", "released_reason": None}
        row.update(base_fields())
        db.holds[row["id"]] = row

    calc.run_census(season)
    bump(season)
    return ok(order, 201)


# ---------------------------------------------------------------------------
# Submission and review (PRD 3.5)
# ---------------------------------------------------------------------------
@bp.route("/ticketing/plan-orders/<order_id>/submit", methods=["POST"])
@endpoint(ROLE_SALES)
def submit_order(caller, order_id):
    order = find_order(order_id)
    account = db.accounts.get(order["account_id"])
    gate_rep_ownership(caller, account)
    gate_selling(calc.season_of_order(order))
    gate_order_status(order, ("DRAFT",))

    order["submitted_by_user_id"] = caller.user_id
    if D(order["discount_pct"]) == D(0):
        order["order_status"] = "APPROVED"
    else:
        order["order_status"] = "PENDING_APPROVAL"
    bump(order)
    return ok(order)


@bp.route("/ticketing/plan-orders/<order_id>/review", methods=["POST"])
@endpoint(ROLE_REVENUE)
def review_order(caller, order_id):
    data = body()
    decision = req_enum(data, "decision", ("APPROVE", "REVISE"))
    opt_str(data, "decision_note")

    order = find_order(order_id)
    if order.get("submitted_by_user_id") is not None and caller.user_id == order["submitted_by_user_id"]:
        err("ERR_SEGREGATION_OF_DUTIES", 403,
            "The reviewer may not be the submitter of the order.")
    gate_order_status(order, ("PENDING_APPROVAL",))

    order["reviewed_by_user_id"] = caller.user_id
    if decision == "APPROVE":
        order["order_status"] = "APPROVED"
    else:
        order["order_status"] = "DRAFT"
        order["submitted_by_user_id"] = None
    bump(order)
    return ok(order)


# ---------------------------------------------------------------------------
# Confirmation (PRD 3.6)
# ---------------------------------------------------------------------------
@bp.route("/ticketing/plan-orders/<order_id>/confirm", methods=["POST"])
@endpoint(ROLE_SALES, ROLE_HOLDER)
def confirm_order(caller, order_id):
    data = body()
    installment_count = req_int(data, "installment_count")
    if installment_count not in calc.INSTALLMENT_COUNT_ALLOWED:
        bad_request("Field 'installment_count' must be one of 1, 3 or 6.")

    order = find_order(order_id)
    account = db.accounts.get(order["account_id"])
    gate_rep_ownership(caller, account)
    gate_holder_ownership(caller, order["account_id"])

    plan = calc.plan_of(order)
    season = calc.season_of_order(order)
    gate_selling(season)

    if plan["plan_status"] != "PUBLISHED":
        err("ERR_PLAN_NOT_PUBLISHED", 409, "The plan is not PUBLISHED.")

    gate_order_status(order, ("APPROVED",))

    for sid in order["seat_ids"]:
        seat = db.seats.get(sid)
        if seat is None or not seat_free_for_account(seat, order["account_id"]):
            err("ERR_SEAT_NOT_AVAILABLE", 409, "Seat %s is not available." % sid)

    if account["billing_status"] in ("LAPSED", "WRITTEN_OFF"):
        err("ERR_ACCOUNT_WRITTEN_OFF", 409,
            "The account is %s and may not confirm orders." % account["billing_status"])

    mode = season["dynamic_pricing_mode"]
    final_total = calc.plan_order_total(plan, order["seat_ids"], account,
                                        order["discount_pct"], mode, "FINAL")
    order["final_total_cents"] = final_total
    order["order_status"] = "CONFIRMED"
    order["installment_count"] = installment_count

    # Convert the account's ACTIVE holds over the order's seats.
    for hold in list(db.holds.values()):
        if (hold["hold_status"] == "ACTIVE" and hold["seat_id"] in order["seat_ids"]
                and hold["account_id"] == order["account_id"]):
            hold["hold_status"] = "CONVERTED"
            bump(hold)

    for sid in order["seat_ids"]:
        seat = db.seats[sid]
        seat["assigned_account_id"] = order["account_id"]
        seat["seat_status"] = "ASSIGNED"
        bump(seat)
    calc.run_census(season)

    order["payment_status"] = "SCHEDULED"
    order["installments"] = calc.build_installments(final_total, installment_count, now())
    order["amount_paid_cents"] = 0

    season["contracted_revenue_cents"] += final_total

    # Cascade link 1 + 2: hospitality packages held by this account for the plan's games.
    packages = [p for p in db.packages.values()
                if p["account_id"] == order["account_id"] and p["package_status"] == "HELD"
                and p["game_id"] in plan["game_ids"]]
    packages.sort(key=lambda p: (p["service_window_start_utc"], p["created_at"], p["id"]))
    for pkg in packages:
        pkg["package_status"] = "CONFIRMED"
        bump(pkg)
        season["contracted_revenue_cents"] += pkg["total_due_cents"]
        calc.recompute_attendance(db.games.get(pkg["game_id"]))

    # Cascade link 3: the revenue-goal check runs once, after every addition.
    calc.apply_revenue_goal_check(season)

    if account["service_status"] in ("PROSPECT", "WON_BACK"):
        account["service_status"] = "ACTIVE"
    elif account["service_status"] == "AT_RISK":
        account["service_status"] = "ACTIVE"
        account["at_risk_since_utc"] = None
    calc.refresh_renewal_priority(account)
    calc.recompute_lifetime_value(account)
    calc.recompute_rolling(account)
    bump(account)

    for gid in plan["game_ids"]:
        calc.recompute_attendance(db.games.get(gid))

    bump(order)
    bump(season)
    return ok(order)


# ---------------------------------------------------------------------------
# Cancellation (PRD 3.8)
# ---------------------------------------------------------------------------
@bp.route("/ticketing/plan-orders/<order_id>/cancel", methods=["POST"])
@endpoint(ROLE_SALES, ROLE_ADMIN)
def cancel_order(caller, order_id):
    data = body()
    cancel_reason = opt_str(data, "cancel_reason")

    order = find_order(order_id)
    if order["order_status"] == "CANCELLED":
        err("ERR_ORDER_STATE_INVALID", 409, "The order is already cancelled.")

    season = calc.season_of_order(order)
    plan = calc.plan_of(order)
    account = db.accounts.get(order["account_id"])
    was_confirmed = order["order_status"] == "CONFIRMED"

    if was_confirmed and season is not None and season["season_status"] == "ARCHIVED":
        err("ERR_SEASON_STATE_INVALID", 409, "A confirmed order cannot be cancelled once the season is ARCHIVED.")

    if cancel_reason is not None:
        order["cancelled_reason"] = cancel_reason

    if was_confirmed:
        season["contracted_revenue_cents"] -= order["final_total_cents"]
        for sid in order["seat_ids"]:
            seat = db.seats.get(sid)
            if seat is not None:
                seat["assigned_account_id"] = None
                bump(seat)
        for hold in list(db.holds.values()):
            if hold["hold_status"] not in ("ACTIVE", "CONVERTED"):
                continue
            own = hold.get("origin_order_id") == order["id"]
            converted_for_order = (hold["hold_status"] == "CONVERTED"
                                   and hold["account_id"] == order["account_id"]
                                   and hold["seat_id"] in order["seat_ids"])
            if own or converted_for_order:
                release_hold(hold, "ORDER_CANCELLED")
        was_delinquent = order["payment_status"] == "DELINQUENT"
        if account is not None:
            account["loyalty_credit_cents"] += order["amount_paid_cents"]
        order["payment_status"] = "REFUNDED"
        order["order_status"] = "CANCELLED"
        if was_delinquent:
            cure_billing(account, order["id"])
        calc.run_census(season)
        if account is not None:
            calc.refresh_renewal_priority(account)
            calc.recompute_lifetime_value(account)
            calc.recompute_rolling(account)
            bump(account)
        if plan is not None:
            for gid in plan["game_ids"]:
                calc.recompute_attendance(db.games.get(gid))
        bump(order)
        bump(season)
    else:
        touched_accounts = set()
        for hold in list(db.holds.values()):
            if hold.get("origin_order_id") == order["id"] and hold["hold_status"] == "ACTIVE":
                release_hold(hold, "ORDER_CANCELLED")
                touched_accounts.add(hold["account_id"])
        order["order_status"] = "CANCELLED"
        calc.run_census(season)
        for account_id in touched_accounts:
            acct = db.accounts.get(account_id)
            if acct is None:
                continue
            before = acct["renewal_priority_active"]
            calc.refresh_renewal_priority(acct)
            if before != acct["renewal_priority_active"]:
                bump(acct)
        bump(order)
    return ok(order)


# ---------------------------------------------------------------------------
# Relocation (PRD 3.8)
# ---------------------------------------------------------------------------
@bp.route("/ticketing/plan-orders/<order_id>/relocate", methods=["POST"])
@endpoint(ROLE_SALES)
def relocate_order(caller, order_id):
    data = body()
    new_seat_ids = req_id_list(data, "new_seat_ids")
    expected_order_version = req_int(data, "expected_order_version")

    order = find_order(order_id)
    for sid in new_seat_ids:
        find_seat(sid)

    account = db.accounts.get(order["account_id"])
    gate_rep_ownership(caller, account)

    plan = calc.plan_of(order)
    season = calc.season_of_order(order)
    gate_selling(season)

    gate_order_status(order, ("CONFIRMED",))

    for sid in new_seat_ids:
        if not seat_free_for_account(db.seats[sid], order["account_id"]):
            err("ERR_SEAT_NOT_AVAILABLE", 409, "Seat %s is not available." % sid)

    gate_not_delinquent(order)

    if expected_order_version != order["version"]:
        err("ERR_STALE_ORDER_VERSION", 412, "The order has been modified since it was read.")

    check_seat_season(new_seat_ids, plan)

    if len(new_seat_ids) != len(order["seat_ids"]):
        err("ERR_SEAT_COUNT_OUT_OF_RANGE", 422,
            "A relocation must keep exactly %d seats." % len(order["seat_ids"]))

    check_single_zone(new_seat_ids)

    mode = season["dynamic_pricing_mode"]
    remaining = [db.games[gid] for gid in plan["game_ids"]
                 if gid in db.games and db.games[gid]["game_date_utc"] > now()]
    old_total = 0
    new_total = 0
    for game in remaining:
        for sid in order["seat_ids"]:
            seat = db.seats.get(sid)
            if seat is not None:
                old_total += calc.line_cents(seat, game, mode)
        for sid in new_seat_ids:
            new_total += calc.line_cents(db.seats[sid], game, mode)
    delta = new_total - old_total

    signed = 0
    if delta > 0:
        credit_applied = min(account["loyalty_credit_cents"], calc.UPGRADE_CREDIT_CAP_CENTS, delta)
        fee = calc.RELOCATION_FEE_CENTS if season["season_status"] == "IN_SEASON" else 0
        charge = delta - credit_applied + fee
        account["loyalty_credit_cents"] -= credit_applied
        order["final_total_cents"] += charge
        signed = charge
    elif delta < 0:
        refund = min(rhu(D(abs(delta)) * D(calc.DOWNGRADE_REFUND_RATE)), order["amount_paid_cents"])
        order["final_total_cents"] -= refund
        account["loyalty_credit_cents"] += refund
        signed = -refund
    season["contracted_revenue_cents"] += signed

    old_seat_ids = list(order["seat_ids"])
    for sid in old_seat_ids:
        seat = db.seats.get(sid)
        if seat is not None and sid not in new_seat_ids:
            seat["assigned_account_id"] = None
            bump(seat)
    for sid in new_seat_ids:
        seat = db.seats[sid]
        if seat.get("assigned_account_id") != order["account_id"]:
            seat["assigned_account_id"] = order["account_id"]
            seat["seat_status"] = "ASSIGNED"
            bump(seat)
    order["seat_ids"] = list(new_seat_ids)

    calc.run_census(season)
    if account is not None:
        calc.recompute_lifetime_value(account)
        if signed != 0:
            bump(account)
    for gid in plan["game_ids"]:
        calc.recompute_attendance(db.games.get(gid))
    bump(order)
    bump(season)
    return ok(order)


# ---------------------------------------------------------------------------
# Payments (PRD 3.7)
# ---------------------------------------------------------------------------
@bp.route("/ticketing/plan-orders/<order_id>/payments", methods=["POST"])
@endpoint(ROLE_HOLDER, ROLE_SALES)
def pay_order(caller, order_id):
    data = body()
    amount_cents = req_int(data, "amount_cents", minimum=0)

    order = find_order(order_id)
    gate_holder_ownership(caller, order["account_id"])

    if order["payment_status"] not in ("SCHEDULED", "PARTIALLY_PAID", "DELINQUENT"):
        err("ERR_ORDER_STATE_INVALID", 409,
            "Payments require payment_status SCHEDULED, PARTIALLY_PAID or DELINQUENT.")

    balance = order["final_total_cents"] - order["amount_paid_cents"]
    if amount_cents > balance:
        err("ERR_PAYMENT_EXCEEDS_BALANCE", 422, "The payment exceeds the outstanding balance.")

    account = db.accounts.get(order["account_id"])
    before = account_snapshot(account) if account is not None else None
    was_delinquent = order["payment_status"] == "DELINQUENT"

    calc.apply_payment(order, amount_cents)
    paid = order["amount_paid_cents"]

    if was_delinquent:
        if calc.has_overdue_installment(order, now()) and paid < order["final_total_cents"]:
            order["payment_status"] = "DELINQUENT"
        elif paid >= order["final_total_cents"]:
            order["payment_status"] = "PAID_IN_FULL"
        else:
            order["payment_status"] = "PARTIALLY_PAID"
    else:
        if paid >= order["final_total_cents"]:
            order["payment_status"] = "PAID_IN_FULL"
        elif paid > 0:
            order["payment_status"] = "PARTIALLY_PAID"

    if order["payment_status"] != "DELINQUENT":
        cure_billing(account, order["id"])
    if account is not None:
        calc.recompute_rolling(account)
        bump_if_changed(account, before)
    bump(order)
    return ok(order)
