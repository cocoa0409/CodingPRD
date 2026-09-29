"""Calculation rules and shared derived-state services (PRD 2.7, 2.10, 3.4, 3.9,
3.10, 3.11).

All money is integer cents; every rounding step is round-half-up.
"""
from decimal import Decimal

from core import (D, db, bump, days, floor_days_between, now, rhu, rhu2)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ZONE_BASE_PRICE_CENTS = {"ZONE_A": 12000, "ZONE_B": 8000, "ZONE_C": 5000, "ZONE_D": 3000}
OPPONENT_TIER_MULTIPLIER = {"MARQUEE": "1.60", "PREMIUM": "1.25", "STANDARD": "1.00", "VALUE": "0.85"}
DAY_BUCKET_MULTIPLIER = {"WEEKEND": "1.15", "WEEKDAY": "1.00"}

TENURE_CREDIT_PER_YEAR_CENTS = 500
TENURE_CREDIT_CAP_CENTS = 5000
SERVICE_FEE_RATE = "0.06"
MAX_REP_DISCOUNT_PCT = "0.25"

HOSPITALITY_BASE_FEE_CENTS = {"MARQUEE": 25000, "PREMIUM": 18000, "STANDARD": 14000, "VALUE": 11000}
FNB_PER_HEAD_CENTS = 4500
HOSPITALITY_SERVICE_FEE_RATE = "0.08"

UPGRADE_CREDIT_CAP_CENTS = 10000
RELOCATION_FEE_CENTS = 2500
DOWNGRADE_REFUND_RATE = "0.50"

RESALE_FLOOR_RATE = "0.60"
RESALE_CREDIT_RATE = "0.85"
MARQUEE_TRANSFER_MIN_TENURE_YEARS = 3
MAX_TRANSFERS_PER_ACCOUNT_PER_SEASON = 2

ORDER_HOLD_DURATION_HOURS = 72
INSTALLMENT_COUNT_ALLOWED = (1, 3, 6)
INSTALLMENT_INTERVAL_DAYS = 30
PAYMENT_GRACE_DAYS = 10

TOUCHPOINT_CADENCE_DAYS = 14
CHURN_DECLARATION_DAYS = 30
LAPSE_AFTER_DAYS = 45
WRITE_OFF_AFTER_DAYS = 90
SEASON_ARCHIVE_GRACE_DAYS = 7
HOSPITALITY_RELEASE_LEAD_DAYS = 7
HOSPITALITY_TURNOVER_MINUTES = 30
MIN_PARTIAL_PLAN_GAMES = 2
AT_RISK_SCORE_THRESHOLD = 50

SELLING_STATUSES = ("RENEWAL_OPEN", "GENERAL_ONSALE")


# ---------------------------------------------------------------------------
# calculations.game_seat_line_price
# ---------------------------------------------------------------------------
def demand_multiplier(demand_index, mode):
    if mode == "BALANCED":
        if demand_index >= 80:
            return D("1.15")
        if demand_index >= 60:
            return D("1.08")
        if demand_index >= 40:
            return D("1.00")
        return D("0.95")
    if demand_index >= 80:
        return D("1.30")
    if demand_index >= 60:
        return D("1.15")
    if demand_index >= 40:
        return D("1.00")
    return D("0.90")


def line_cents(seat, game, mode):
    base = D(ZONE_BASE_PRICE_CENTS[seat["price_zone"]])
    opp = D(OPPONENT_TIER_MULTIPLIER[game["opponent_tier"]])
    day = D(DAY_BUCKET_MULTIPLIER[game["day_bucket"]])
    dem = demand_multiplier(game["demand_index"], mode)
    return rhu(base * opp * day * dem)


# ---------------------------------------------------------------------------
# calculations.plan_order_total
# ---------------------------------------------------------------------------
def volume_discount_pct(seat_count):
    if seat_count >= 20:
        return D("0.12")
    if seat_count >= 10:
        return D("0.07")
    if seat_count >= 4:
        return D("0.03")
    return D("0.00")


def plan_order_total(plan, seat_ids, account, discount_pct, mode, variant):
    """QUOTED prices every plan game; FINAL only games strictly after the clock."""
    game_ids = list(plan["game_ids"])
    games = []
    for gid in game_ids:
        game = db.games.get(gid)
        if game is None:
            continue
        if variant == "FINAL" and not (game["game_date_utc"] > now()):
            continue
        games.append(game)

    seats = [db.seats[sid] for sid in seat_ids if sid in db.seats]

    subtotal = 0
    for game in games:
        for seat in seats:
            subtotal += line_cents(seat, game, mode)

    volume_pct = volume_discount_pct(len(seat_ids))
    after_volume = rhu(D(subtotal) * (D(1) - volume_pct))
    after_rep = rhu(D(after_volume) * (D(1) - D(discount_pct)))
    tenure_credit = min(TENURE_CREDIT_CAP_CENTS, account["tenure_years"] * TENURE_CREDIT_PER_YEAR_CENTS)
    net_cents = max(0, after_rep - tenure_credit)
    service_fee = rhu(D(net_cents) * D(SERVICE_FEE_RATE))
    return net_cents + service_fee


# ---------------------------------------------------------------------------
# calculations.hospitality_package_fee
# ---------------------------------------------------------------------------
def partner_discount_tier(gross_fee_cents):
    if gross_fee_cents >= 1000000:
        return D("0.10")
    if gross_fee_cents >= 500000:
        return D("0.05")
    return D("0.00")


def hospitality_fee(game, headcount):
    gross = (HOSPITALITY_BASE_FEE_CENTS[game["opponent_tier"]] + FNB_PER_HEAD_CENTS) * headcount
    pct = partner_discount_tier(gross)
    discounted = rhu(D(gross) * (D(1) - pct))
    service_fee = rhu(D(discounted) * D(HOSPITALITY_SERVICE_FEE_RATE))
    return {
        "gross_fee_cents": gross,
        "partner_discount_pct": float(pct),
        "service_fee_cents": service_fee,
        "total_due_cents": discounted + service_fee,
    }


# ---------------------------------------------------------------------------
# calculations.seat_occupancy_and_season_census
# ---------------------------------------------------------------------------
def holds_on_seat(seat_id):
    return [h for h in db.holds.values() if h["seat_id"] == seat_id]


def effective_seat_status(seat):
    if seat.get("assigned_account_id") is not None:
        return "ASSIGNED"
    instant = now()
    for hold in db.holds.values():
        if hold["seat_id"] != seat["id"] or hold["hold_status"] != "ACTIVE":
            continue
        if hold["hold_window_start_utc"] <= instant < hold["hold_window_end_utc"]:
            return "HELD"
    return "AVAILABLE"


def season_seats(season_id):
    return [s for s in db.seats.values() if s["season_id"] == season_id]


def run_census(season):
    """Rewrites stored seat_status for the season's seats and the four counters."""
    if season is None:
        return
    seats = season_seats(season["id"])
    available = held = assigned = 0
    for seat in seats:
        status = effective_seat_status(seat)
        seat["seat_status"] = status
        if status == "AVAILABLE":
            available += 1
        elif status == "HELD":
            held += 1
        else:
            assigned += 1
    season["total_seat_count"] = len(seats)
    season["available_seat_count"] = available
    season["held_seat_count"] = held
    season["assigned_seat_count"] = assigned


# ---------------------------------------------------------------------------
# Entitlement helpers
# ---------------------------------------------------------------------------
def plan_of(order):
    return db.plans.get(order["plan_id"])


def season_of_order(order):
    plan = plan_of(order)
    if plan is None:
        return None
    return db.seasons.get(plan["season_id"])


def season_of_seat(seat):
    return db.seasons.get(seat["season_id"])


def season_of_game(game):
    return db.seasons.get(game["season_id"])


def confirmed_order_for(seat_id, game_id):
    for order in db.orders.values():
        if order["order_status"] != "CONFIRMED":
            continue
        if seat_id not in order["seat_ids"]:
            continue
        plan = plan_of(order)
        if plan is not None and game_id in plan["game_ids"]:
            return order
    return None


def approved_transfer_for(seat_id, game_id, statuses=("APPROVED",)):
    for tr in db.transfers.values():
        if tr["seat_id"] == seat_id and tr["game_id"] == game_id and tr["transfer_status"] in statuses:
            return tr
    return None


def entitled_account_id(seat_id, game_id):
    """The account that holds the gate entitlement for one (seat, game) pair."""
    tr = approved_transfer_for(seat_id, game_id, ("APPROVED", "COMPLETED"))
    if tr is not None and tr["transfer_type"] == "TRANSFER" and tr.get("to_account_id"):
        return tr["to_account_id"]
    order = confirmed_order_for(seat_id, game_id)
    if order is not None:
        return order["account_id"]
    if tr is not None:
        return tr.get("to_account_id") or tr.get("from_account_id")
    return None


def entitled_seat_ids(game_id):
    """Seats entitled to a game through some CONFIRMED plan order."""
    out = []
    seen = set()
    for order in db.orders.values():
        if order["order_status"] != "CONFIRMED":
            continue
        plan = plan_of(order)
        if plan is None or game_id not in plan["game_ids"]:
            continue
        for sid in order["seat_ids"]:
            if sid not in seen:
                seen.add(sid)
                out.append(sid)
    return out


# ---------------------------------------------------------------------------
# calculations.attendance_and_no_show
# ---------------------------------------------------------------------------
def recompute_attendance(game):
    if game is None:
        return
    entitled = entitled_seat_ids(game["id"])
    heads = 0
    for pkg in db.packages.values():
        if pkg["game_id"] == game["id"] and pkg["package_status"] in ("CONFIRMED", "SETTLED"):
            heads += pkg["headcount"]
    expected = len(entitled) + heads
    scanned = game.get("scanned_count", 0)
    no_show = max(0, expected - scanned)
    game["expected_attendance"] = expected
    game["no_show_count"] = no_show
    if expected == 0:
        game["no_show_rate_pct"] = 0.0
    else:
        game["no_show_rate_pct"] = rhu2(D(no_show) * D(100) / D(expected))


def recompute_booked_headcount(game):
    if game is None:
        return
    total = 0
    for pkg in db.packages.values():
        if pkg["game_id"] == game["id"] and pkg["package_status"] in ("HELD", "CONFIRMED", "SETTLED"):
            total += pkg["headcount"]
    game["hospitality_booked_headcount"] = total


# ---------------------------------------------------------------------------
# calculations.account_churn_risk
# ---------------------------------------------------------------------------
def _shared_components(account):
    anchor = account.get("last_touchpoint_at_utc") or account["created_at"]
    days_silent = floor_days_between(now(), anchor)
    recency = min(20, (days_silent // 7) * 5)
    billing = account["billing_status"]
    if billing in ("LAPSED", "WRITTEN_OFF"):
        delinquency = 40
    elif billing == "PAST_DUE":
        delinquency = 25
    else:
        delinquency = 0
    tenure_relief = min(15, account["tenure_years"] * 3)
    return recency, delinquency, tenure_relief


def churn_rolling(account):
    recency, delinquency, tenure_relief = _shared_components(account)
    no_show = min(40, account["no_show_count"] * 8)
    return max(0, min(100, no_show + delinquency + recency - tenure_relief))


def has_confirmed_order_in_season(account_id, season_id):
    for order in db.orders.values():
        if order["account_id"] != account_id or order["order_status"] != "CONFIRMED":
            continue
        plan = plan_of(order)
        if plan is not None and plan["season_id"] == season_id:
            return True
    return False


def churn_campaign(account, season):
    recency, delinquency, tenure_relief = _shared_components(account)
    no_show = min(40, account["season_no_show_count"] * 8)
    if season is not None and has_confirmed_order_in_season(account["id"], season["id"]):
        intent = 0
    else:
        intent = 30
    relief = tenure_relief if (season is not None and season["season_status"] == "RENEWAL_OPEN") else 0
    return max(0, min(100, no_show + delinquency + recency + intent - relief))


def recompute_rolling(account):
    if account is not None:
        account["churn_risk_rolling"] = churn_rolling(account)


def recompute_campaign(account, season):
    if account is not None:
        account["churn_risk_campaign"] = churn_campaign(account, season)


def recompute_lifetime_value(account):
    if account is None:
        return
    total = 0
    for order in db.orders.values():
        if order["account_id"] == account["id"] and order["order_status"] == "CONFIRMED":
            total += order["final_total_cents"]
    for pkg in db.packages.values():
        if pkg["account_id"] == account["id"] and pkg["package_status"] in ("CONFIRMED", "SETTLED"):
            total += pkg["total_due_cents"]
    account["lifetime_value_cents"] = total


# ---------------------------------------------------------------------------
# Renewal priority flag (PRD 3.3)
# ---------------------------------------------------------------------------
def refresh_renewal_priority(account):
    if account is None:
        return
    for hold in db.holds.values():
        if (hold["account_id"] == account["id"] and hold["hold_status"] == "ACTIVE"
                and hold["hold_type"] == "RENEWAL_HOLD"):
            account["renewal_priority_active"] = True
            return
    account["renewal_priority_active"] = False


# ---------------------------------------------------------------------------
# calculations.installment_schedule_and_payment_application
# ---------------------------------------------------------------------------
def build_installments(total_cents, count, start_instant):
    base = total_cents // count
    remainder = total_cents - base * count
    rows = []
    for i in range(count):
        amount = base + remainder if i == 0 else base
        rows.append({
            "index": i,
            "due_date_utc": start_instant + days(i * INSTALLMENT_INTERVAL_DAYS),
            "amount_cents": amount,
            "paid_cents": 0,
        })
    return rows


def apply_payment(order, amount_cents):
    remaining = amount_cents
    schedule = sorted(order["installments"], key=lambda r: (r["due_date_utc"], r["index"]))
    for inst in schedule:
        if remaining <= 0:
            break
        room = inst["amount_cents"] - inst["paid_cents"]
        if room <= 0:
            continue
        take = min(room, remaining)
        inst["paid_cents"] += take
        remaining -= take
    order["amount_paid_cents"] = sum(i["paid_cents"] for i in order["installments"])


def has_overdue_installment(order, instant):
    for inst in order["installments"]:
        if inst["paid_cents"] < inst["amount_cents"] and inst["due_date_utc"] + days(PAYMENT_GRACE_DAYS) <= instant:
            return True
    return False


def earliest_unpaid(order):
    unpaid = [i for i in order["installments"] if i["paid_cents"] < i["amount_cents"]]
    if not unpaid:
        return None
    return sorted(unpaid, key=lambda r: (r["due_date_utc"], r["index"]))[0]


# ---------------------------------------------------------------------------
# calculations.service_rep_selection
# ---------------------------------------------------------------------------
def select_rep(account):
    candidates = []
    for rep in db.reps.values():
        if rep["rep_status"] != "ACTIVE":
            continue
        if rep["territory_code"] != account["territory_code"]:
            continue
        if rep["assigned_account_count"] >= rep["book_capacity"]:
            continue
        candidates.append(rep)
    if not candidates:
        return None
    def key(rep):
        ratio = (D(rep["assigned_account_count"]) / D(rep["book_capacity"])).quantize(D("0.0001"))
        return (ratio, -rep["book_capacity"], rep["created_at"], rep["id"])
    candidates.sort(key=key)
    return candidates[0]


# ---------------------------------------------------------------------------
# Season revenue ledger (PRD 2.10)
# ---------------------------------------------------------------------------
def apply_revenue_goal_check(season):
    if season["contracted_revenue_cents"] >= season["revenue_goal_cents"]:
        if not season["revenue_goal_met"]:
            season["revenue_goal_met"] = True
        if season["dynamic_pricing_mode"] == "AGGRESSIVE":
            season["dynamic_pricing_mode"] = "BALANCED"
