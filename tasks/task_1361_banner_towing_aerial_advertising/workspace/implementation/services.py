"""Business logic: counters, cascades, selectors, billing (PRD section 3).

Records are stored as plain dicts in db.DB. Public fields serialize verbatim;
private bookkeeping keys are prefixed with "_" and stripped at serialization.
"""
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal

from db import DB, clock_now, new_id, next_seq, now_iso
from errors import ApiError
from util import dec, round_half_up_cents, round_tenth_hour

# ---------------------------------------------------------------------------
# Constants (PRD 3.x / scaffold calculations)
# ---------------------------------------------------------------------------
VFR_MIN_VISIBILITY_SM = Decimal("3.0")
VFR_MIN_CEILING_FT = 1000
MAX_WIND_KTS = 25
MARGINAL_VISIBILITY_SM = Decimal("5.0")
MARGINAL_CEILING_FT = 1500
MARGINAL_WIND_KTS = 18

TIER1_MAX_HOURS = Decimal(20)
TIER2_MAX_HOURS = Decimal(50)
TIER2_DISCOUNT_PCT = 5
TIER3_DISCOUNT_PCT = 10

FULL_NOTICE_HOURS = 72
PARTIAL_NOTICE_HOURS = 24
PARTIAL_PENALTY = Decimal("0.25")
LATE_PENALTY = Decimal("0.50")

AIRCRAFT_SEASON_HARD_CAP_HOURS = 600
PILOT_SEASON_HARD_CAP_HOURS = 500
SUSPENSION_THRESHOLD = 3

ENDORSEMENT_RANK = {"TRAINEE": 0, "STANDARD": 1, "STADIUM_QUALIFIED": 2}

SLOT_TERMINAL = {"FLOWN", "CANCELLED_CLIENT", "CANCELLED_WEATHER", "CANCELLED_TFR"}
SLOT_OPEN = {"BOOKED", "SCHEDULED", "WEATHER_HOLD"}
# Statuses contributing to SeasonalCapacity.hours_committed (PRD 2.8).
SLOT_CONTRIBUTING = {"BOOKED", "SCHEDULED", "WEATHER_HOLD", "FLOWN"}


# ---------------------------------------------------------------------------
# Record plumbing
# ---------------------------------------------------------------------------
def new_record():
    """Common system-managed fields (PRD 2.4); version starts at 1."""
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def new_evidence_record():
    """Immutable evidentiary records (WeatherAssessment / ProofOfFlight):
    id and created_at only (PRD 2.4)."""
    return {"id": new_id(), "created_at": now_iso(), "_seq": next_seq()}


def touch(rec):
    """Every mutation refreshes updated_at and increments version by one."""
    rec["updated_at"] = now_iso()
    rec["version"] += 1


def pub(rec):
    """Serialized view: strip private '_' keys."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def sorted_created(recs):
    """Default list ordering: created_at ascending (PRD 2.3), stable on ties."""
    return sorted(recs, key=lambda r: (r["created_at"], r["_seq"]))


def _get(coll, rid):
    rec = DB[coll].get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced resource does not exist")
    return rec


def get_base(rid):
    return _get("bases", rid)


def get_aircraft(rid):
    return _get("aircraft", rid)


def get_pilot(rid):
    return _get("pilots", rid)


def get_route(rid):
    return _get("routes", rid)


def get_client(rid):
    return _get("clients", rid)


def get_campaign(rid):
    return _get("campaigns", rid)


def get_approval(rid):
    return _get("airspace_approvals", rid)


def get_tfr(rid):
    return _get("tfr_restrictions", rid)


def get_banner(rid):
    return _get("banners", rid)


def get_revision(rid):
    return _get("banner_revisions", rid)


def get_capacity(rid):
    return _get("seasonal_capacities", rid)


def get_slot(rid):
    return _get("flight_slots", rid)


def get_assessment(rid):
    return _get("weather_assessments", rid)


def get_log(rid):
    return _get("flight_logs", rid)


def get_credit(rid):
    return _get("make_good_credits", rid)


def get_proof(rid):
    return _get("proof_of_flights", rid)


def get_invoice(rid):
    return _get("invoices", rid)


def campaign_of_banner(banner):
    return DB["campaigns"].get(banner["campaign_id"])


def campaign_of_slot(slot):
    return DB["campaigns"].get(slot["campaign_id"])


def log_of_slot(slot_id):
    for log in DB["flight_logs"].values():
        if log["slot_id"] == slot_id:
            return log
    return None


def proof_of_slot(slot_id):
    for p in DB["proof_of_flights"].values():
        if p["slot_id"] == slot_id:
            return p
    return None


def slot_month(slot):
    """Seasonal-capacity month key: the month of date_local (YYYY-MM)."""
    return slot["date_local"][:7]


# ---------------------------------------------------------------------------
# Derived counters (PRD 2.11 / 3.2)
# ---------------------------------------------------------------------------
def recompute_campaign(camp):
    """Recompute the four campaign counters; any change is a modification
    (version +1, updated_at refreshed)."""
    slots = [s for s in DB["flight_slots"].values() if s["campaign_id"] == camp["id"]]
    booked = sum(1 for s in slots if s["status"] in ("BOOKED", "SCHEDULED"))
    flown = sum(1 for s in slots if s["status"] == "FLOWN")
    cancelled_weather = sum(1 for s in slots if s["status"] == "CANCELLED_WEATHER")
    unapplied = sum(
        c["remaining_cents"]
        for c in DB["make_good_credits"].values()
        if c["campaign_id"] == camp["id"] and c["status"] == "OPEN"
    )
    changed = (
        camp["booked_flight_count"] != booked
        or camp["flown_flight_count"] != flown
        or camp["cancelled_weather_count"] != cancelled_weather
        or camp["unapplied_make_good_cents"] != unapplied
    )
    camp["booked_flight_count"] = booked
    camp["flown_flight_count"] = flown
    camp["cancelled_weather_count"] = cancelled_weather
    camp["unapplied_make_good_cents"] = unapplied
    if changed:
        touch(camp)


def recompute_client_balance(client):
    """outstanding_balance_cents = sum of balance_due over non-PAID invoices."""
    total = 0
    for inv in DB["invoices"].values():
        camp = DB["campaigns"].get(inv["campaign_id"])
        if camp and camp["client_id"] == client["id"] and inv["status"] != "PAID":
            total += inv["balance_due_cents"]
    if client["outstanding_balance_cents"] != total:
        client["outstanding_balance_cents"] = total
        touch(client)


def maybe_complete_campaign(camp):
    """IN_FLIGHT -> COMPLETE when every slot is terminal and every invoice is
    PAID or VOID (PRD 3.2)."""
    if camp["status"] != "IN_FLIGHT":
        return
    slots = [s for s in DB["flight_slots"].values() if s["campaign_id"] == camp["id"]]
    if not slots:
        return
    if not all(s["status"] in SLOT_TERMINAL for s in slots):
        return
    invoices = [i for i in DB["invoices"].values() if i["campaign_id"] == camp["id"]]
    if not all(i["status"] in ("PAID", "VOID") for i in invoices):
        return
    camp["status"] = "COMPLETE"
    touch(camp)


# ---------------------------------------------------------------------------
# Seasonal capacity (PRD 2.8)
# ---------------------------------------------------------------------------
def capacity_for(base_id, month):
    for c in DB["seasonal_capacities"].values():
        if c["base_id"] == base_id and c["month_yyyy_mm"] == month:
            return c
    return None


def hours_remaining(cap):
    return cap["aircraft_hour_quota"] - cap["hours_committed"]


def consume_capacity(slot):
    cap = capacity_for(DB["routes"][slot["route_id"]]["base_id"], slot_month(slot))
    if cap is not None:
        cap["hours_committed"] += slot["planned_duration_hours"]
        touch(cap)


def release_capacity(slot):
    cap = capacity_for(DB["routes"][slot["route_id"]]["base_id"], slot_month(slot))
    if cap is not None:
        cap["hours_committed"] -= slot["planned_duration_hours"]
        touch(cap)


# ---------------------------------------------------------------------------
# Slot cancellation helpers
# ---------------------------------------------------------------------------
def _release_if_contributing(slot):
    if slot["status"] in SLOT_CONTRIBUTING and slot["status"] != "FLOWN":
        release_capacity(slot)


def cancel_slot_by_client(slot):
    """BOOKED/SCHEDULED -> CANCELLED_CLIENT: release capacity, record the
    cancellation instant for the penalty computation (PRD 3.6)."""
    _release_if_contributing(slot)
    slot["status"] = "CANCELLED_CLIENT"
    slot["cancelled_at_utc"] = now_iso()
    slot["_cancelled_dt"] = clock_now()
    touch(slot)
    camp = campaign_of_slot(slot)
    recompute_campaign(camp)
    maybe_complete_campaign(camp)


def cancel_slot_by_tfr(slot):
    """Approval-revocation cascade (PRD 3.4)."""
    _release_if_contributing(slot)
    slot["status"] = "CANCELLED_TFR"
    touch(slot)
    camp = campaign_of_slot(slot)
    recompute_campaign(camp)
    maybe_complete_campaign(camp)


def cancel_slot_by_weather(slot):
    """NO_GO-driven cancellation: never billed; creates a MakeGoodCredit whose
    value is planned_duration_hours * aircraft hourly rate, expiring 30 days
    after the slot's date_local (PRD 3.6)."""
    _release_if_contributing(slot)
    slot["status"] = "CANCELLED_WEATHER"
    touch(slot)
    aircraft = DB["aircraft"].get(slot.get("assigned_aircraft_id") or "")
    rate = aircraft["hourly_rate_cents"] if aircraft else 0
    original = slot["planned_duration_hours"] * rate
    expires = slot["_date_local_date"] + timedelta(days=30)
    credit = new_record()
    credit.update(
        {
            "campaign_id": slot["campaign_id"],
            "source_slot_id": slot["id"],
            "original_cents": original,
            "remaining_cents": original,
            "expires_on_local": expires.isoformat(),
            "status": "OPEN",
            "_expires_date": expires,
        }
    )
    DB["make_good_credits"][credit["id"]] = credit
    camp = campaign_of_slot(slot)
    recompute_campaign(camp)
    maybe_complete_campaign(camp)


# ---------------------------------------------------------------------------
# Selectors (PRD 3.5)
# ---------------------------------------------------------------------------
def select_aircraft(route, banner, planned_duration_hours):
    """aircraft_selector: eligibility filter then weighted score; lower score
    wins, ties break by earliest created_at (never id)."""
    cands = []
    for a in DB["aircraft"].values():
        if a["base_id"] != route["base_id"]:
            continue
        if a["status"] != "ACTIVE":
            continue
        if a["max_tow_weight_lbs"] < banner["banner_weight_lbs"]:
            continue
        if a["_season_hours"] + dec(planned_duration_hours) > dec(
            AIRCRAFT_SEASON_HARD_CAP_HOURS
        ):
            continue
        score = a["_season_hours"] * 100 + dec(a["hourly_rate_cents"]) / dec(1000)
        cands.append((score, a["created_at"], a["_seq"], a))
    if not cands:
        raise ApiError(
            "ERR_NO_ELIGIBLE_AIRCRAFT", 409, "No eligible aircraft for this slot"
        )
    cands.sort(key=lambda t: (t[0], t[1], t[2]))
    return cands[0][3]


def select_pilot(route, planned_duration_hours):
    """pilot_selector (runs after aircraft_selector)."""
    cands = []
    for p in DB["pilots"].values():
        if p["base_id"] != route["base_id"]:
            continue
        if p["status"] != "ACTIVE":
            continue
        if p["season_pickup_failure_count"] >= SUSPENSION_THRESHOLD:
            continue
        if route["kind"] == "STADIUM" and p["tow_endorsement_level"] != "STADIUM_QUALIFIED":
            continue
        if p["_season_hours"] + dec(planned_duration_hours) > dec(
            PILOT_SEASON_HARD_CAP_HOURS
        ):
            continue
        score = p["_season_hours"] * 100 - ENDORSEMENT_RANK[p["tow_endorsement_level"]] * 50
        cands.append((score, p["created_at"], p["_seq"], p))
    if not cands:
        raise ApiError("ERR_NO_ELIGIBLE_PILOT", 409, "No eligible pilot for this slot")
    cands.sort(key=lambda t: (t[0], t[1], t[2]))
    return cands[0][3]


# ---------------------------------------------------------------------------
# TFR / approval window helpers (PRD 3.4)
# ---------------------------------------------------------------------------
def slot_interval(start_dt, duration_hours):
    """Half-open interval [start, start + duration)."""
    return start_dt, start_dt + timedelta(hours=duration_hours)


def intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open overlap: start < other.end AND end > other.start; merely
    touching does not count."""
    return a_start < b_end and a_end > b_start


def tfr_blocks(route, slot_start, slot_end, approval):
    """Stadium slots overlapping a PUBLISHED TFR require a waiver."""
    if route["kind"] != "STADIUM":
        return False
    for t in DB["tfr_restrictions"].values():
        if t["route_id"] != route["id"] or t["status"] != "PUBLISHED":
            continue
        if intervals_overlap(slot_start, slot_end, t["_starts_dt"], t["_ends_dt"]):
            if not approval["stadium_tfr_waiver"]:
                return True
    return False


def window_contains(approval, slot_start, slot_end):
    return (
        approval["_window_start_dt"] <= slot_start
        and slot_end <= approval["_window_end_dt"]
    )


# ---------------------------------------------------------------------------
# Weather go/no-go (PRD 3.6)
# ---------------------------------------------------------------------------
def go_no_go_verdict(visibility_sm, ceiling_ft, wind_kts):
    vis = dec(visibility_sm)
    if vis < VFR_MIN_VISIBILITY_SM or ceiling_ft < VFR_MIN_CEILING_FT or wind_kts > MAX_WIND_KTS:
        return "NO_GO"
    if vis < MARGINAL_VISIBILITY_SM or ceiling_ft < MARGINAL_CEILING_FT or wind_kts > MARGINAL_WIND_KTS:
        return "MARGINAL"
    return "GO"


# ---------------------------------------------------------------------------
# Booking (PRD 3.5) — business rules fire in the pinned order.
# ---------------------------------------------------------------------------
def check_make_good_source(supersedes_slot_id):
    """supersedes_slot_id must name a CANCELLED_WEATHER slot whose credit is
    still OPEN or PARTIALLY_APPLIED."""
    src = DB["flight_slots"].get(supersedes_slot_id)
    if src is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced resource does not exist")
    if src["status"] != "CANCELLED_WEATHER":
        raise ApiError(
            "ERR_INVALID_MAKE_GOOD_SOURCE",
            409,
            "supersedes_slot_id is not a CANCELLED_WEATHER slot",
        )
    ok = any(
        c["source_slot_id"] == src["id"] and c["status"] in ("OPEN", "PARTIALLY_APPLIED")
        for c in DB["make_good_credits"].values()
    )
    if not ok:
        raise ApiError(
            "ERR_INVALID_MAKE_GOOD_SOURCE",
            409,
            "Source slot's make-good credit is not OPEN or PARTIALLY_APPLIED",
        )


def aircraft_double_booked(aircraft_id, slot_start, slot_end):
    """No two FlightSlots for the same aircraft may overlap in time
    (half-open interval)."""
    for s in DB["flight_slots"].values():
        if s.get("assigned_aircraft_id") != aircraft_id:
            continue
        if s["status"] not in SLOT_OPEN:
            continue
        s_start, s_end = slot_interval(s["_planned_start_dt"], s["planned_duration_hours"])
        if intervals_overlap(slot_start, slot_end, s_start, s_end):
            return True
    return False


# ---------------------------------------------------------------------------
# Billing (PRD 3.8)
# ---------------------------------------------------------------------------
def discount_pct(total_hours):
    """Tiered volume discount across the whole invoice."""
    if total_hours <= TIER1_MAX_HOURS:
        return 0
    if total_hours <= TIER2_MAX_HOURS:
        return TIER2_DISCOUNT_PCT
    return TIER3_DISCOUNT_PCT


def flight_subtotal(campaign_id, period, provisional):
    """Per-line round_half_up first, sum, then apply the volume discount and
    round again. The discount factor itself is never rounded."""
    rows = []
    for s in DB["flight_slots"].values():
        if s["campaign_id"] != campaign_id:
            continue
        if s["status"] == "FLOWN":
            log = log_of_slot(s["id"])
            if log is None:
                continue
            if log["filed_at_utc"][:7] != period:
                continue
            rows.append((log["filed_at_utc"], log["_seq"], s, log))
        elif provisional and s["status"] in ("BOOKED", "SCHEDULED"):
            if s["date_local"][:7] != period:
                continue
            rows.append((s["planned_start_utc"], s["_seq"], s, None))
    rows.sort(key=lambda r: (r[0], r[1]))
    line_sum = 0
    total_hours = Decimal(0)
    for _, _, s, log in rows:
        # FLOWN lines rate off the aircraft copied onto the FlightLog at filing.
        aircraft_ref = (
            log["aircraft_id"] if log is not None else s.get("assigned_aircraft_id")
        )
        aircraft = DB["aircraft"].get(aircraft_ref or "")
        rate = aircraft["hourly_rate_cents"] if aircraft else 0
        hours = log["_hobbs_hours"] if log is not None else dec(s["planned_duration_hours"])
        line_sum += round_half_up_cents(hours * dec(rate))
        total_hours += hours
    pct = discount_pct(total_hours)
    subtotal = round_half_up_cents(dec(line_sum) * (dec(100 - pct) / dec(100)))
    return subtotal


def cancellation_penalty(campaign_id, period):
    """weather_cancellation_penalty_rule: fraction of planned value by notice,
    round_half_up per slot. Period membership keyed by cancelled_at_utc."""
    total = 0
    for s in DB["flight_slots"].values():
        if s["campaign_id"] != campaign_id:
            continue
        if s["status"] != "CANCELLED_CLIENT" or not s.get("cancelled_at_utc"):
            continue
        if s["cancelled_at_utc"][:7] != period:
            continue
        aircraft = DB["aircraft"].get(s.get("assigned_aircraft_id") or "")
        rate = aircraft["hourly_rate_cents"] if aircraft else 0
        planned_value = dec(s["planned_duration_hours"]) * dec(rate)
        notice = s["_planned_start_dt"] - s["_cancelled_dt"]
        if notice >= timedelta(hours=FULL_NOTICE_HOURS):
            penalty = 0
        elif notice >= timedelta(hours=PARTIAL_NOTICE_HOURS):
            penalty = round_half_up_cents(planned_value * PARTIAL_PENALTY)
        else:
            penalty = round_half_up_cents(planned_value * LATE_PENALTY)
        total += penalty
    return total


def apply_make_good_credits(camp, period, available_cents):
    """Waterfall: eligible credits in expiry order then creation order; each
    applies min(remaining, uncovered pool). Exact integer cents, no rounding."""
    y, m = int(period[:4]), int(period[5:7])
    period_end = date(y, m, monthrange(y, m)[1])
    credits = [
        c
        for c in DB["make_good_credits"].values()
        if c["campaign_id"] == camp["id"]
        and c["status"] in ("OPEN", "PARTIALLY_APPLIED")
        and c["_expires_date"] >= period_end
    ]
    credits.sort(key=lambda c: (c["expires_on_local"], c["_seq"]))
    applied_total = 0
    applications = []
    for c in credits:
        headroom = available_cents - applied_total
        if headroom <= 0:
            break
        amt = min(c["remaining_cents"], headroom)
        if amt <= 0:
            continue
        c["remaining_cents"] -= amt
        c["status"] = "FULLY_APPLIED" if c["remaining_cents"] == 0 else "PARTIALLY_APPLIED"
        touch(c)
        applied_total += amt
        applications.append({"credit_id": c["id"], "applied_cents": amt})
        # The slot that consumed the credit records it (the make-good
        # replacement pointing at this credit's source slot).
        for s in sorted_created(
            [x for x in DB["flight_slots"].values() if x["campaign_id"] == camp["id"]]
        ):
            if s.get("supersedes_slot_id") == c["source_slot_id"] and not s.get(
                "consumed_make_good_credit_id"
            ):
                s["consumed_make_good_credit_id"] = c["id"]
                touch(s)
                break
    return applied_total, applications
