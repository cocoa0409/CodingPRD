"""Domain logic: derived fields, calculations, sweeps, resolvers, serializers.

Constants and formulas trace to SCAFFOLD section 1.3 and PRD section 3.
All monetary math uses Decimal with ROUND_HALF_UP; per-show projected figures
are rounded half-up to integer cents BEFORE the tour-level sum (PRD 2.7/3.8).
"""
from datetime import datetime, time as dtime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from db import store, clock, new_entity, touch
from errors import ApiError
from middleware import parse_date, parse_dt, fmt_dt

# --- Calculation constants (SCAFFOLD 1.3) ---
PRE_SALE_SELLOUT_FACTOR = Decimal("0.65")
POST_SALE_DECAY = Decimal("0.35")
PER_TICKET_VARIABLE_COST_CENTS = 350
AVG_SPEED_MPH = 55
MAX_DRIVE_MINUTES_BEFORE_REST = 480
MIN_ON_SALE_LEAD_DAYS = 14
HOLD_TTL_HOURS = 72
COUNTER_EXTENSION_HOURS = 24
MAX_COUNTER_ROUNDS = 3
VARIANCE_THRESHOLD_CENTS = 50000
MATERIAL_VARIANCE_CENTS = 500000

# Shows in the forward projection set (SCAFFOLD 1.3 projected_show_pnl,
# Tour entity field descriptions, PRD 3.8).
PROJECTION_SET = ("CONFIRMED", "ADVANCED", "PERFORMED", "SETTLED")

# Show statuses from which cancellation is allowed (SCAFFOLD 1.2).
CANCELLABLE_SHOW_STATES = ("HOLD_REQUESTED", "HOLD_PLACED", "CONFIRMED")

SECTION_FIELDS = {
    "tech_rider": "tech_rider_status",
    "hospitality": "hospitality_status",
    "immigration": "immigration_status",
}

BUDGET_CATEGORIES = (
    "VENUE_RENT", "CREW", "TRANSPORT", "BACKLINE",
    "MARKETING", "HOSPITALITY", "INSURANCE", "MISC",
)
MARKETING_CHANNELS = ("RADIO", "SOCIAL", "OOH", "PRINT", "INFLUENCER")
HOLD_KINDS = (
    "RADIUS_CONFLICT", "VENUE_DOUBLE_BOOK", "REST_VIOLATION",
    "BUDGET_OVERRUN", "ADVANCE_OVERDUE",
)
HOLD_SEVERITIES = ("STANDARD", "CRITICAL")


def rhu(dec):
    """Round half-up to a whole integer (cents/minutes)."""
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Resolvers: nested path params validated strictly left-to-right (PRD 2.9);
# the first unresolvable identifier produces ERR_NOT_FOUND.
# ---------------------------------------------------------------------------

def resolve_tour(tour_id):
    t = store["tours"].get(tour_id)
    if t is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Tour not found")
    return t


def _resolve_child(collection, child_id, parent_key, parent_id, label):
    c = store[collection].get(child_id)
    if c is None or c[parent_key] != parent_id:
        raise ApiError("ERR_NOT_FOUND", 404, f"{label} not found")
    return c


def resolve_market(tour, market_id):
    return _resolve_child("markets", market_id, "tour_id", tour["id"], "Market")


def resolve_venue(tour, venue_id):
    return _resolve_child("venues", venue_id, "tour_id", tour["id"], "Venue")


def resolve_leg(tour, leg_id):
    return _resolve_child("legs", leg_id, "tour_id", tour["id"], "RoutingLeg")


def resolve_show(tour, show_id):
    return _resolve_child("shows", show_id, "tour_id", tour["id"], "Show")


def resolve_hold(show, hold_id):
    return _resolve_child("holds", hold_id, "show_id", show["id"], "PromoterHold")


def resolve_budget_line(show, line_id):
    return _resolve_child("budget_lines", line_id, "show_id", show["id"], "BudgetLine")


def resolve_spend(show, spend_id):
    return _resolve_child("spends", spend_id, "show_id", show["id"], "MarketingSpend")


def resolve_compliance_hold(tour, hold_id):
    return _resolve_child(
        "compliance_holds", hold_id, "tour_id", tour["id"], "ComplianceHold"
    )


def packet_for_show(show_id):
    for p in store["packets"].values():
        if p["show_id"] == show_id:
            return p
    return None


def settlement_for_show(show_id):
    for s in store["settlements"].values():
        if s["show_id"] == show_id:
            return s
    return None


def accepted_hold_for_show(show_id):
    for h in store["holds"].values():
        if h["show_id"] == show_id and h["status"] == "ACCEPTED":
            return h
    return None


# ---------------------------------------------------------------------------
# Derived state
# ---------------------------------------------------------------------------

def packet_sections_complete(p):
    """All sections APPROVED; immigration NOT_REQUIRED satisfies completeness
    exactly as APPROVED does (PRD 3.5)."""
    return (
        p["tech_rider_status"] == "APPROVED"
        and p["hospitality_status"] == "APPROVED"
        and p["immigration_status"] in ("APPROVED", "NOT_REQUIRED")
    )


def compute_daysheet_issued(p, show):
    """true iff all sections complete AND Show.status == ADVANCED (SCAFFOLD 1.1)."""
    return packet_sections_complete(p) and show["status"] == "ADVANCED"


def compute_show_posture(show):
    """GATED while any required packet section is not APPROVED or while
    Tour.posture != OPEN (SCAFFOLD 1.1 Show.posture, PRD 2.6)."""
    tour = store["tours"].get(show["tour_id"])
    p = packet_for_show(show["id"])
    complete = p is not None and packet_sections_complete(p)
    if tour is not None and tour["posture"] == "OPEN" and complete:
        return "OPEN"
    return "GATED"


def recompute_tour_posture(tour):
    """Posture from active ComplianceHolds (PRD 2.6):
    any ACTIVE CRITICAL -> FROZEN; else >=1 ACTIVE STANDARD -> RESTRICTED;
    else OPEN. Returns True when the value changed."""
    active = [
        h
        for h in store["compliance_holds"].values()
        if h["tour_id"] == tour["id"] and h["status"] == "ACTIVE"
    ]
    if any(h["severity"] == "CRITICAL" for h in active):
        new = "FROZEN"
    elif active:
        new = "RESTRICTED"
    else:
        new = "OPEN"
    if new != tour["posture"]:
        tour["posture"] = new
        return True
    return False


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

def compute_drive_minutes(drive_miles):
    """routing_leg_drive_time: round(drive_miles * 60 / 55), round-half-up."""
    return rhu(Decimal(drive_miles) * 60 / Decimal(AVG_SPEED_MPH))


def compute_crew_rest_required(drive_minutes):
    """Strictly greater than 480 minutes; at exactly 480 it is false."""
    return drive_minutes > MAX_DRIVE_MINUTES_BEFORE_REST


def recompute_show_projection(show):
    """projected_show_pnl (SCAFFOLD 1.3 / PRD 3.8). Only applies to shows in
    the projection set. Returns True when a stored value changed."""
    if show["status"] not in PROJECTION_SET:
        return False
    cap = show["capacity"]
    price = show["avg_ticket_price_cents"]
    sold = show["tickets_sold"]
    committed_est = sum(
        b["estimated_cents"]
        for b in store["budget_lines"].values()
        if b["show_id"] == show["id"] and b["is_committed"]
    )
    on_sale_at = parse_dt(show["on_sale_at"])
    if clock["now"] < on_sale_at:
        # PRE_ON_SALE variant
        gross = rhu(Decimal(cap) * Decimal(price) * PRE_SALE_SELLOUT_FACTOR)
        cost = committed_est + cap * PER_TICKET_VARIABLE_COST_CENTS
    else:
        # POST_ON_SALE variant
        gross = rhu(
            Decimal(sold) * Decimal(price)
            + Decimal(cap - sold) * Decimal(price) * POST_SALE_DECAY
        )
        cost = committed_est + sold * PER_TICKET_VARIABLE_COST_CENTS
    if gross != show["projected_gross_cents"] or cost != show["projected_cost_cents"]:
        show["projected_gross_cents"] = gross
        show["projected_cost_cents"] = cost
        return True
    return False


def recompute_tour_financials(tour):
    """Tour rollups. Projected: integer-cent sums over the projection set.
    Settled: sums over shows whose settlement is PAID (PRD 3.8).
    Returns True when a stored value changed."""
    shows = [s for s in store["shows"].values() if s["tour_id"] == tour["id"]]
    proj_gross = sum(
        s["projected_gross_cents"] for s in shows if s["status"] in PROJECTION_SET
    )
    proj_cost = sum(
        s["projected_cost_cents"] for s in shows if s["status"] in PROJECTION_SET
    )
    settled_gross = 0
    settled_cost = 0
    for s in shows:
        st = settlement_for_show(s["id"])
        if st is not None and st["status"] == "PAID":
            settled_gross += st["box_office_gross_cents"]
            settled_cost += sum(
                b["actual_cents"] or 0
                for b in store["budget_lines"].values()
                if b["show_id"] == s["id"]
            )
    changed = (
        proj_gross != tour["projected_gross_cents"]
        or proj_cost != tour["projected_cost_cents"]
        or settled_gross != tour["settled_gross_cents"]
        or settled_cost != tour["settled_cost_cents"]
    )
    if changed:
        tour["projected_gross_cents"] = proj_gross
        tour["projected_cost_cents"] = proj_cost
        tour["settled_gross_cents"] = settled_gross
        tour["settled_cost_cents"] = settled_cost
    return changed


def on_sale_lead_satisfied(show_date, on_sale_dt):
    """on_sale_lead_check: (show_date as UTC midnight - on_sale_at) >= 14 days.
    Exactly 14 days is allowed (>=, not >)."""
    midnight = datetime.combine(show_date, dtime.min, tzinfo=timezone.utc)
    return (midnight - on_sale_dt).total_seconds() >= MIN_ON_SALE_LEAD_DAYS * 86400


def confirm_lead_satisfied(show_date):
    """Confirm-time gate: logical clock + 14 days must not fall after show_date."""
    midnight = datetime.combine(show_date, dtime.min, tzinfo=timezone.utc)
    return (midnight - clock["now"]).total_seconds() >= MIN_ON_SALE_LEAD_DAYS * 86400


def radius_conflicts(tour, show):
    """radius_clause_check (SCAFFOLD 1.3 / PRD 3.4).

    Markets carry no geo coordinates in the entity model, so the distance
    predicate distance(m1, m2) <= min(radius_miles) cannot be evaluated from
    stored data; two markets of the same tour are treated as within range,
    leaving the exclusivity-window test as the operative check.

    Half-open boundary: date_diff == window IS a conflict (graded STANDARD at
    exactly the edge); date_diff == window + 1 is OK; strictly inside is
    CRITICAL. Returns a list of (other_show, severity).
    """
    m = store["markets"][show["market_id"]]
    d = parse_date(show["show_date"])
    out = []
    for s2 in store["shows"].values():
        if s2["tour_id"] != tour["id"] or s2["id"] == show["id"]:
            continue
        if s2["status"] not in PROJECTION_SET:
            continue
        if s2["market_id"] == show["market_id"]:
            continue
        m2 = store["markets"][s2["market_id"]]
        window = min(m["exclusivity_window_days"], m2["exclusivity_window_days"])
        date_diff = abs((parse_date(s2["show_date"]) - d).days)
        if date_diff <= window:
            severity = "STANDARD" if date_diff == window else "CRITICAL"
            out.append((s2, severity))
    return out


def compute_artist_share(hold, box_office_gross_cents, taxes_cents,
                         facility_fees_cents, promoter_expenses_cents):
    """settlement_artist_share: net floored at 0; artist share is
    max(guarantee, round_half_up(net * versus_pct/100))."""
    if hold is not None:
        guarantee = hold["guarantee_cents"]
        pct = hold["versus_pct"]
    else:
        guarantee = 0
        pct = 0
    net = (
        box_office_gross_cents
        - taxes_cents
        - facility_fees_cents
        - promoter_expenses_cents
    )
    if net < 0:
        net = 0
    versus_amount = rhu(Decimal(net) * Decimal(pct) / Decimal(100))
    return max(guarantee, versus_amount)


def compute_variance(box_office_gross_cents, tickets_sold, avg_ticket_price_cents):
    """settlement_variance_flag: MINOR at >= 50,000; MATERIAL at >= 500,000.
    Both boundaries inclusive."""
    variance = box_office_gross_cents - tickets_sold * avg_ticket_price_cents
    abs_v = abs(variance)
    if abs_v >= MATERIAL_VARIANCE_CENTS:
        flag = "MATERIAL"
    elif abs_v >= VARIANCE_THRESHOLD_CENTS:
        flag = "MINOR"
    else:
        flag = "NONE"
    return variance, flag


def compute_cpa_cents(spend_cents, attributed_ticket_sales):
    """marketing_cpa per line: round(spend / sales) half-up; null when 0 sales."""
    if attributed_ticket_sales == 0:
        return None
    return rhu(Decimal(spend_cents) / Decimal(attributed_ticket_sales))


# ---------------------------------------------------------------------------
# Sweeps
# ---------------------------------------------------------------------------

def sweep_hold(hold):
    """hold_expiry_check: at exactly hold_expires_at the hold is EXPIRED
    (>=, not >). Applies to PENDING/COUNTERED holds."""
    if hold["status"] in ("PENDING", "COUNTERED") and clock["now"] >= parse_dt(
        hold["hold_expires_at"]
    ):
        hold["status"] = "EXPIRED"
        touch(hold)
        return True
    return False


def sweep_all_holds():
    for h in store["holds"].values():
        sweep_hold(h)


def sweep_clock():
    """Sweeps that run in the wake of a logical-clock advance (PRD 2.5):
    hold expiry, the automatic ON_SALE -> IN_PROGRESS crossing (with
    post-on-sale re-projection), and rest-day rechecks on locked legs.

    Rest-day rechecks are vacuous here: locking enforces the rule, and the
    passage of time cannot create a rest violation between fixed travel
    dates, so the recheck never mutates state."""
    sweep_all_holds()
    for tour in store["tours"].values():
        tour_dirty = False
        tour_shows = [
            s for s in store["shows"].values() if s["tour_id"] == tour["id"]
        ]
        if tour["status"] == "ON_SALE":
            crossed = any(
                s["status"] == "CONFIRMED" and parse_dt(s["on_sale_at"]) <= clock["now"]
                for s in tour_shows
            )
            if crossed:
                tour["status"] = "IN_PROGRESS"
                tour_dirty = True
        for s in tour_shows:
            if recompute_show_projection(s):
                touch(s)
        if recompute_tour_financials(tour):
            tour_dirty = True
        if tour_dirty:
            touch(tour)


# ---------------------------------------------------------------------------
# Serializers (exactly the scaffold entity fields plus common fields;
# internal "_"-prefixed keys are never exposed)
# ---------------------------------------------------------------------------

def pub(e):
    return {k: v for k, v in e.items() if not k.startswith("_")}


def tour_json(t):
    return pub(t)


def market_json(m):
    return pub(m)


def venue_json(v):
    return pub(v)


def leg_json(l):
    return pub(l)


def show_json(s):
    d = pub(s)
    d["posture"] = compute_show_posture(s)
    return d


def hold_json(h):
    return pub(h)


def packet_json(p):
    d = pub(p)
    show = store["shows"].get(p["show_id"])
    d["daysheet_issued"] = (
        compute_daysheet_issued(p, show) if show is not None else False
    )
    return d


def budget_line_json(b):
    return pub(b)


def spend_json(m):
    return pub(m)


def settlement_json(s):
    return pub(s)


def compliance_hold_json(h):
    return pub(h)
