"""Business logic: logical clock, lazy resolution, lookups with ownership
masking, computed aggregates, serializers, cascades, selectors, calculations."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import DB, STATE, new_id, next_seq
from errors import ApiError
from util import fmt_dt, parse_dt

# ---------------------------------------------------------------------------
# Constants (scaffold calculations)
# ---------------------------------------------------------------------------

CATEGORIES = ("COLD_HELD", "HOT_HELD", "PRODUCE", "SHELF_STABLE")
COLD_CHAIN_CATEGORIES = ("COLD_HELD", "HOT_HELD")

DANGER_ZONE_LIMIT_MINUTES = 240
COLD_HELD_DANGER_ABOVE = Decimal("41.0")
COLD_HELD_KILL_AT_PICKUP = Decimal("70.0")
HOT_HELD_DANGER_BELOW = Decimal("135.0")
HOT_HELD_KILL_AT_PICKUP = Decimal("100.0")

DONOR_STRIKE_LIMIT = 3
RELIABILITY_START = 100
COMPLETION_BONUS = 5
STRIKE_PENALTY = 50
SUSPEND_THRESHOLD = 60
REINSTATE_SCORE = 80

RETURN_ALLOWANCE_MINUTES = 90
CLEANING_BUFFER_MINUTES = 45
QUARANTINE_DEEP_CLEAN_MINUTES = 240
BLOCKED_TAIL_MINUTES = RETURN_ALLOWANCE_MINUTES + CLEANING_BUFFER_MINUTES  # 135

OFFER_STATUSES = (
    "DRAFT", "OPEN", "MATCHED", "SCHEDULED", "PICKED_UP",
    "DELIVERED", "CLOSED", "CANCELLED", "EXPIRED", "DISCARDED",
)
OFFER_IN_FLIGHT = ("DRAFT", "OPEN", "MATCHED", "SCHEDULED", "PICKED_UP", "DELIVERED")
FAIL_REASONS = (
    "DONOR_NO_SHOW", "DRIVER_NO_SHOW", "SAFETY_REJECTED",
    "AGENCY_CLOSED", "OVER_CAPACITY", "SAFETY_DISPOSAL", "OTHER",
)
FAULT_PARTIES = ("DONOR", "DRIVER", "AGENCY", "NONE")


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

def clock_dt():
    return parse_dt(STATE["clock"])


def clock_iso():
    return fmt_dt(clock_dt())


def set_clock(to_iso8601):
    STATE["clock"] = to_iso8601
    resolve_lazy()


# ---------------------------------------------------------------------------
# Common field helpers
# ---------------------------------------------------------------------------

def stamp(rec):
    t = clock_iso()
    rec["created_at"] = t
    rec["updated_at"] = t
    rec["version"] = 1
    rec["_seq"] = next_seq()


def touch(rec):
    rec["updated_at"] = clock_iso()
    rec["version"] += 1


# ---------------------------------------------------------------------------
# Lazy state resolution (PRD 2.4)
# ---------------------------------------------------------------------------

def resolve_lazy():
    """Expire past-window OPEN/MATCHED offers; release CLEANING/QUARANTINED
    coolers whose deadline has been reached. Runs before any state check."""
    now = clock_dt()
    for offer in list(DB["offers"].values()):
        if offer["status"] in ("OPEN", "MATCHED") and now > parse_dt(
            offer["pickup_window_end"]
        ):
            was_matched = offer["status"] == "MATCHED"
            offer["status"] = "EXPIRED"
            touch(offer)
            if was_matched:
                run = DB["runs"].get(offer.get("current_run_id") or "")
                if run is not None and run["run_status"] == "PROPOSED":
                    _cancel_run(run)
    for cooler in list(DB["coolers"].values()):
        if cooler["status"] in ("CLEANING", "QUARANTINED") and cooler.get(
            "cleaning_ends_at"
        ):
            if now >= parse_dt(cooler["cleaning_ends_at"]):
                was_quarantined = cooler["status"] == "QUARANTINED"
                cooler["status"] = "AVAILABLE"
                cooler["cleaning_ends_at"] = None
                touch(cooler)
                if was_quarantined:
                    for res in DB["reservations"].values():
                        if (
                            res["cooler_id"] == cooler["id"]
                            and res["status"] == "QUARANTINED_HOLD"
                        ):
                            res["status"] = "RETURNED"
                            touch(res)


# ---------------------------------------------------------------------------
# Lookups (existence, then ownership masking — same 404 family)
# ---------------------------------------------------------------------------

def get_donor(rid, user_id=None, role=None):
    rec = DB["donor_sites"].get(rid)
    if rec is None:
        raise ApiError("ERR_DONOR_NOT_FOUND", 404, "Donor site not found")
    if role == "DonorCoordinator" and rec["id"] != user_id:
        raise ApiError("ERR_DONOR_NOT_FOUND", 404, "Donor site not found")
    return rec


def get_agency(rid, user_id=None, role=None):
    rec = DB["agencies"].get(rid)
    if rec is None:
        raise ApiError("ERR_AGENCY_NOT_FOUND", 404, "Recipient agency not found")
    if role == "AgencyCoordinator" and rec["id"] != user_id:
        raise ApiError("ERR_AGENCY_NOT_FOUND", 404, "Recipient agency not found")
    return rec


def get_driver(rid, user_id=None, role=None):
    rec = DB["drivers"].get(rid)
    if rec is None:
        raise ApiError("ERR_DRIVER_NOT_FOUND", 404, "Volunteer driver not found")
    if role == "VolunteerDriver" and rec["id"] != user_id:
        raise ApiError("ERR_DRIVER_NOT_FOUND", 404, "Volunteer driver not found")
    return rec


def get_cooler(rid):
    rec = DB["coolers"].get(rid)
    if rec is None:
        raise ApiError("ERR_COOLER_NOT_FOUND", 404, "Cooler not found")
    return rec


def get_offer(rid, user_id=None, role=None):
    rec = DB["offers"].get(rid)
    if rec is None:
        raise ApiError("ERR_OFFER_NOT_FOUND", 404, "Donation offer not found")
    if role == "DonorCoordinator" and rec["donor_site_id"] != user_id:
        raise ApiError("ERR_OFFER_NOT_FOUND", 404, "Donation offer not found")
    return rec


def get_run(rid, user_id=None, role=None):
    rec = DB["runs"].get(rid)
    if rec is None:
        raise ApiError("ERR_RUN_NOT_FOUND", 404, "Rescue run not found")
    if role == "VolunteerDriver" and rec["driver_id"] != user_id:
        raise ApiError("ERR_RUN_NOT_FOUND", 404, "Rescue run not found")
    if role == "AgencyCoordinator" and rec["agency_id"] != user_id:
        raise ApiError("ERR_RUN_NOT_FOUND", 404, "Rescue run not found")
    return rec


def get_strike(rid):
    rec = DB["strikes"].get(rid)
    if rec is None:
        raise ApiError("ERR_STRIKE_REPORT_NOT_FOUND", 404, "Strike report not found")
    return rec


# ---------------------------------------------------------------------------
# Computed aggregates
# ---------------------------------------------------------------------------

def donor_pending_estimated_lbs(donor_id):
    total = 0
    for offer in DB["offers"].values():
        if offer["donor_site_id"] == donor_id and offer["status"] in (
            "MATCHED", "SCHEDULED", "PICKED_UP", "DELIVERED",
        ):
            total += offer["estimated_weight_lbs"]
    return total


def donor_lifetime_weight_lbs(donor_id):
    total = 0
    for run in DB["runs"].values():
        if run["run_status"] != "VERIFIED":
            continue
        offer = DB["offers"].get(run["offer_id"])
        if offer is not None and offer["donor_site_id"] == donor_id:
            total += run["actual_weight_lbs"] or 0
    return total


def donor_lifetime_tax_value_cents(donor_id):
    total = 0
    for receipt in DB["receipts"].values():
        if receipt["donor_site_id"] == donor_id and receipt["status"] == "ISSUED":
            total += receipt["deductible_value_cents"]
    return total


def agency_committed_lbs(agency_id, category):
    total = 0
    for run in DB["runs"].values():
        if run["agency_id"] != agency_id:
            continue
        if run["run_status"] not in ("PROPOSED", "CONFIRMED", "PICKED_UP"):
            continue
        offer = DB["offers"].get(run["offer_id"])
        if offer is not None and offer["food_category"] == category:
            total += run["estimated_weight_snapshot"]
    return total


def agency_received_total_lbs(agency_id):
    total = 0
    for run in DB["runs"].values():
        if run["agency_id"] == agency_id and run["run_status"] in (
            "DELIVERED", "VERIFIED",
        ):
            total += run["actual_weight_lbs"] or 0
    return total


def driver_completed_run_count(driver_id):
    return sum(
        1
        for run in DB["runs"].values()
        if run["driver_id"] == driver_id and run["run_status"] == "VERIFIED"
    )


def driver_upheld_strike_count(driver_id):
    return sum(
        1
        for s in DB["strikes"].values()
        if s["subject_type"] == "DRIVER"
        and s["subject_id"] == driver_id
        and s["status"] == "UPHELD"
    )


def capacity_field(category):
    return "capacity_" + category.lower() + "_lbs"


def committed_field(category):
    return "committed_" + category.lower() + "_lbs"


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def ser_donor(d):
    out = _public(d)
    out["pending_estimated_lbs"] = donor_pending_estimated_lbs(d["id"])
    out["lifetime_weight_lbs"] = donor_lifetime_weight_lbs(d["id"])
    out["lifetime_tax_value_cents"] = donor_lifetime_tax_value_cents(d["id"])
    return out


def ser_agency(a):
    out = _public(a)
    for cat in CATEGORIES:
        out[committed_field(cat)] = agency_committed_lbs(a["id"], cat)
    out["received_total_lbs"] = agency_received_total_lbs(a["id"])
    return out


def ser_driver(d):
    out = _public(d)
    out["completed_run_count"] = driver_completed_run_count(d["id"])
    out["upheld_strike_count"] = driver_upheld_strike_count(d["id"])
    return out


def ser_window(w):
    return _public(w)


def ser_cooler(c):
    return _public(c)


def ser_reservation(r):
    return _public(r)


def ser_offer(o):
    return _public(o)


def ser_run(r):
    return _public(r)


def ser_temp_log(t):
    return _public(t)


def ser_strike(s):
    return _public(s)


def ser_receipt(r):
    return _public(r)


def ser_rate_card(r):
    return _public(r)


# ---------------------------------------------------------------------------
# Strike filing
# ---------------------------------------------------------------------------

def file_strike(run_id, reporter_role, reporter_user_id, subject_type, subject_id, reason):
    rec = {
        "id": new_id(),
        "rescue_run_id": run_id,
        "reporter_role": reporter_role,
        "reporter_user_id": reporter_user_id if reporter_role != "SYSTEM" else None,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "reason": reason,
        "status": "FILED",
        "adjudicated_by_user_id": None,
        "adjudicated_at": None,
    }
    stamp(rec)
    DB["strikes"][rec["id"]] = rec
    return rec


# ---------------------------------------------------------------------------
# Run teardown cascades
# ---------------------------------------------------------------------------

def _release_window(run):
    """Return the run's booked window to OPEN (idempotent)."""
    for w in DB["windows"].values():
        if w.get("booked_run_id") == run["id"] and w["status"] == "BOOKED":
            w["status"] = "OPEN"
            w["booked_run_id"] = None
            touch(w)


def _release_reserved_equipment(run):
    """RESERVED reservations -> RELEASED; their coolers -> AVAILABLE."""
    for res in DB["reservations"].values():
        if res["rescue_run_id"] == run["id"] and res["status"] == "RESERVED":
            res["status"] = "RELEASED"
            touch(res)
            cooler = DB["coolers"].get(res["cooler_id"])
            if cooler is not None and cooler["status"] == "RESERVED":
                cooler["status"] = "AVAILABLE"
                touch(cooler)


def _cancel_run(run):
    """PROPOSED/CONFIRMED -> CANCELLED with the full release cascade."""
    run["run_status"] = "CANCELLED"
    touch(run)
    _release_window(run)
    _release_reserved_equipment(run)


def _decline_run(run):
    """PROPOSED -> DECLINED with the full release cascade; offer reopens."""
    run["run_status"] = "DECLINED"
    touch(run)
    _release_window(run)
    _release_reserved_equipment(run)
    offer = DB["offers"].get(run["offer_id"])
    if offer is not None and offer["status"] == "MATCHED":
        offer["status"] = "OPEN"
        touch(offer)


def _fail_pickup_cascade(run, fault_party, reason):
    """CONFIRMED -> FAILED_PICKUP (system cascade path: driver suspension)."""
    run["run_status"] = "FAILED_PICKUP"
    run["fault_party"] = fault_party
    run["failure_reason"] = reason
    touch(run)
    _release_window(run)
    _release_reserved_equipment(run)
    offer = DB["offers"].get(run["offer_id"])
    if offer is not None and offer["status"] == "SCHEDULED":
        offer["failed_attempts"] += 1
        offer["status"] = "OPEN" if offer["failed_attempts"] < 3 else "EXPIRED"
        touch(offer)
    if fault_party in ("DONOR", "DRIVER"):
        subject_type = "DONOR_SITE" if fault_party == "DONOR" else "DRIVER"
        subject_id = (
            offer["donor_site_id"] if fault_party == "DONOR" else run["driver_id"]
        )
        file_strike(run["id"], "SYSTEM", None, subject_type, subject_id, reason)


def suspend_donor_cascade(donor):
    """Donor ACTIVE -> SUSPENDED: cancel DRAFT/OPEN offers outright, tear down
    MATCHED/SCHEDULED offers and their current runs; in-flight untouched."""
    donor["status"] = "SUSPENDED"
    touch(donor)
    for offer in list(DB["offers"].values()):
        if offer["donor_site_id"] != donor["id"]:
            continue
        if offer["status"] in ("DRAFT", "OPEN"):
            offer["status"] = "CANCELLED"
            touch(offer)
        elif offer["status"] in ("MATCHED", "SCHEDULED"):
            offer["status"] = "CANCELLED"
            touch(offer)
            run = DB["runs"].get(offer.get("current_run_id") or "")
            if run is not None and run["run_status"] in ("PROPOSED", "CONFIRMED"):
                _cancel_run(run)


def suspend_driver_cascade(driver):
    """Driver ACTIVE -> SUSPENDED: PROPOSED runs DECLINED (offer reopens),
    CONFIRMED runs FAILED_PICKUP with a SYSTEM strike against the driver."""
    driver["status"] = "SUSPENDED"
    touch(driver)
    for run in list(DB["runs"].values()):
        if run["driver_id"] != driver["id"]:
            continue
        if run["run_status"] == "PROPOSED":
            _decline_run(run)
        elif run["run_status"] == "CONFIRMED":
            _fail_pickup_cascade(run, "DRIVER", "DRIVER_NO_SHOW")


# ---------------------------------------------------------------------------
# Cold-chain safety (danger_zone_compliance_verdict)
# ---------------------------------------------------------------------------

def temp_decimal(value):
    return Decimal(str(value))


def round_temp_1dp(value):
    """Temperatures are recorded with one decimal place (half-up)."""
    d = Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return float(d)


def kill_screen_tripped(category, temp_f):
    t = temp_decimal(temp_f)
    if category == "COLD_HELD":
        return t >= COLD_HELD_KILL_AT_PICKUP
    if category == "HOT_HELD":
        return t <= HOT_HELD_KILL_AT_PICKUP
    return False


def _is_dangerous(category, temp_f):
    t = temp_decimal(temp_f)
    if category == "COLD_HELD":
        return t > COLD_HELD_DANGER_ABOVE
    if category == "HOT_HELD":
        return t < HOT_HELD_DANGER_BELOW
    return False


def _span_minutes(t0, t1):
    """Exact elapsed minutes between two aware datetimes as a Decimal."""
    delta = t1 - t0
    total_us = (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds
    return Decimal(total_us) / Decimal(60_000_000)


def danger_zone_verdict(category, t0, T0, t1, T1):
    """Final variant: linear interpolation of danger minutes between the
    PICKUP log (t0, T0) and the ARRIVAL log (t1, T1). COMPLIANT iff the
    cumulative danger minutes are <= 240 (inclusive boundary)."""
    K = COLD_HELD_DANGER_ABOVE if category == "COLD_HELD" else HOT_HELD_DANGER_BELOW
    d0 = _is_dangerous(category, T0)
    d1 = _is_dangerous(category, T1)
    span = _span_minutes(t0, t1)
    T0d = temp_decimal(T0)
    T1d = temp_decimal(T1)
    if not d0 and not d1:
        danger = Decimal(0)
    elif d0 and d1:
        danger = span
    elif d1:
        danger = span * (T1d - K) / (T1d - T0d)
    else:
        danger = span * (K - T0d) / (T1d - T0d)
    return danger <= DANGER_ZONE_LIMIT_MINUTES


# ---------------------------------------------------------------------------
# Selectors (dispatch)
# ---------------------------------------------------------------------------

def covering_open_windows(driver_id, offer):
    """OPEN windows of the driver fully covering the offer pickup window."""
    pws = parse_dt(offer["pickup_window_start"])
    pwe = parse_dt(offer["pickup_window_end"])
    out = []
    for w in DB["windows"].values():
        if w["driver_id"] != driver_id or w["status"] != "OPEN":
            continue
        if parse_dt(w["window_start"]) <= pws and parse_dt(w["window_end"]) >= pwe:
            out.append(w)
    return out


def select_window(driver_id, offer):
    """Earliest-starting covering OPEN window; tie: earliest created_at."""
    cands = covering_open_windows(driver_id, offer)
    if not cands:
        return None
    return min(
        cands,
        key=lambda w: (parse_dt(w["window_start"]), parse_dt(w["created_at"]), w["_seq"]),
    )


def driver_eligible(driver, offer):
    if driver["status"] != "ACTIVE":
        return False
    if offer["requires_cold_chain"] and not driver["cold_chain_certified"]:
        return False
    if driver["vehicle_capacity_lbs"] < offer["estimated_weight_lbs"]:
        return False
    return select_window(driver["id"], offer) is not None


def select_driver(offer):
    """Rank: reliability_score DESC, covering window_start ASC, window
    created_at ASC. Returns (driver, window) or None."""
    scored = []
    for d in DB["drivers"].values():
        if not driver_eligible(d, offer):
            continue
        w = select_window(d["id"], offer)
        scored.append((d, w))
    if not scored:
        return None
    scored.sort(
        key=lambda dw: (
            -dw[0]["reliability_score"],
            parse_dt(dw[1]["window_start"]),
            parse_dt(dw[1]["created_at"]),
            dw[1]["_seq"],
            dw[0]["_seq"],
        )
    )
    return scored[0]


def agency_eligible(agency, offer):
    if offer["food_category"] not in agency["accepts_categories"]:
        return False
    cat = offer["food_category"]
    committed = agency_committed_lbs(agency["id"], cat)
    return committed + offer["estimated_weight_lbs"] <= agency[capacity_field(cat)]


def select_agency(offer):
    """Best fit: smallest non-negative slack first; tie: created_at ASC."""
    cands = [a for a in DB["agencies"].values() if agency_eligible(a, offer)]
    if not cands:
        return None
    cat = offer["food_category"]

    def slack(a):
        return (
            a[capacity_field(cat)]
            - agency_committed_lbs(a["id"], cat)
            - offer["estimated_weight_lbs"]
        )

    cands.sort(key=lambda a: (slack(a), parse_dt(a["created_at"]), a["_seq"]))
    return cands[0]


def required_cooler_liters(offer):
    """ceil(estimated_weight_lbs * 0.5)."""
    return (offer["estimated_weight_lbs"] + 1) // 2


def reservation_blocked_interval(offer):
    start = parse_dt(offer["pickup_window_start"])
    end = parse_dt(offer["pickup_window_end"]) + timedelta(minutes=BLOCKED_TAIL_MINUTES)
    return start, end


def _intervals_conflict(s1, e1, s2, e2):
    """Half-open overlap: conflict iff s1 < e2 AND s2 < e1 (adjacency allowed)."""
    return s1 < e2 and s2 < e1


def cooler_is_candidate(cooler, blocked_start, blocked_end):
    """PRD §3.3: candidate coolers are those lazily AVAILABLE with no
    reservation in RESERVED or CHECKED_OUT whose buffered blocked interval
    overlaps the new one. A RESERVED cooler whose existing reservation's
    interval does NOT overlap the new one remains a candidate — the
    availability check is fully expressed by the interval overlap test.
    Only hard out-of-cycle states (CLEANING, QUARANTINED not yet lazily
    resolved, or CHECKED_OUT) rule the cooler out on status alone."""
    if cooler["status"] in ("CLEANING", "QUARANTINED", "CHECKED_OUT"):
        return False
    for res in DB["reservations"].values():
        if res["cooler_id"] != cooler["id"]:
            continue
        if res["status"] not in ("RESERVED", "CHECKED_OUT"):
            continue
        if _intervals_conflict(
            blocked_start,
            blocked_end,
            parse_dt(res["blocked_start"]),
            parse_dt(res["blocked_end"]),
        ):
            return False
    return True


def select_coolers(offer, slot_count, blocked_start, blocked_end):
    """Waterfall: capacity_liters DESC, created_at ASC; accumulate while the
    total is below the requirement and slots remain. Returns list or None."""
    cands = [
        c
        for c in DB["coolers"].values()
        if cooler_is_candidate(c, blocked_start, blocked_end)
    ]
    cands.sort(key=lambda c: (-c["capacity_liters"], parse_dt(c["created_at"]), c["_seq"]))
    required = required_cooler_liters(offer)
    selected = []
    total = 0
    for c in cands:
        if total >= required or len(selected) >= slot_count:
            break
        selected.append(c)
        total += c["capacity_liters"]
    if total < required:
        return None
    return selected


# ---------------------------------------------------------------------------
# Tax substantiation (tax_substantiation_value)
# ---------------------------------------------------------------------------

def rate_card_for_period_end(period_end):
    pe = parse_dt(period_end)
    for card in DB["rate_cards"].values():
        if parse_dt(card["effective_start"]) <= pe < parse_dt(card["effective_end"]):
            return card
    return None


def verified_runs_in_period(donor_id, period_start, period_end):
    ps = parse_dt(period_start)
    pe = parse_dt(period_end)
    out = []
    for run in DB["runs"].values():
        if run["run_status"] != "VERIFIED" or run.get("verified_at") is None:
            continue
        offer = DB["offers"].get(run["offer_id"])
        if offer is None or offer["donor_site_id"] != donor_id:
            continue
        va = parse_dt(run["verified_at"])
        if ps <= va < pe:
            out.append(run)
    return out


def _round_half_up_whole(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_receipt_lines(runs, card):
    """Group runs by food_category; per line apply the pinned rounding order
    (per-lb enhanced rate rounded half-up BEFORE multiplying by weight)."""
    weights = {}
    for run in runs:
        offer = DB["offers"][run["offer_id"]]
        cat = offer["food_category"]
        weights[cat] = weights.get(cat, 0) + (run["actual_weight_lbs"] or 0)
    lines = []
    for cat in CATEGORIES:
        if cat not in weights:
            continue
        prefix = cat.lower()
        fmv = card[prefix + "_fmv_cents_per_lb"]
        basis = card[prefix + "_basis_cents_per_lb"]
        weight = weights[cat]
        standard = weight * fmv
        half_excess = _round_half_up_whole((Decimal(fmv) - Decimal(basis)) / 2)
        enhanced_rate = min(2 * basis, basis + half_excess)
        enhanced = weight * enhanced_rate
        lines.append(
            {
                "food_category": cat,
                "weight_lbs": weight,
                "fmv_cents_per_lb": fmv,
                "basis_cents_per_lb": basis,
                "standard_cents": standard,
                "enhanced_cents": enhanced,
            }
        )
    return lines


# ---------------------------------------------------------------------------
# Equipment and window lifecycle helpers (run-stage side effects)
# ---------------------------------------------------------------------------

def book_window(window, run_id):
    """Window OPEN -> BOOKED with booked_run_id set (dispatch)."""
    window["status"] = "BOOKED"
    window["booked_run_id"] = run_id
    touch(window)


def create_reservation(cooler, run, offer):
    """Create a RESERVED CoolerReservation with the buffered blocked interval
    and move the cooler AVAILABLE -> RESERVED (dispatch)."""
    blocked_start, blocked_end = reservation_blocked_interval(offer)
    rec = {
        "id": new_id(),
        "cooler_id": cooler["id"],
        "rescue_run_id": run["id"],
        "blocked_start": fmt_dt(blocked_start),
        "blocked_end": fmt_dt(blocked_end),
        "status": "RESERVED",
    }
    stamp(rec)
    DB["reservations"][rec["id"]] = rec
    cooler["status"] = "RESERVED"
    touch(cooler)
    return rec


def checkout_equipment(run):
    """record-pickup: reservations RESERVED -> CHECKED_OUT; coolers RESERVED ->
    CHECKED_OUT."""
    for res in DB["reservations"].values():
        if res["rescue_run_id"] == run["id"] and res["status"] == "RESERVED":
            res["status"] = "CHECKED_OUT"
            touch(res)
            cooler = DB["coolers"].get(res["cooler_id"])
            if cooler is not None and cooler["status"] == "RESERVED":
                cooler["status"] = "CHECKED_OUT"
                touch(cooler)


def return_equipment_cleaning(run):
    """Ordinary return: reservations CHECKED_OUT -> RETURNED; coolers
    CHECKED_OUT -> CLEANING with cleaning_ends_at = clock + 45 min."""
    ends = fmt_dt(clock_dt() + timedelta(minutes=CLEANING_BUFFER_MINUTES))
    for res in DB["reservations"].values():
        if res["rescue_run_id"] == run["id"] and res["status"] == "CHECKED_OUT":
            res["status"] = "RETURNED"
            touch(res)
            cooler = DB["coolers"].get(res["cooler_id"])
            if cooler is not None and cooler["status"] == "CHECKED_OUT":
                cooler["status"] = "CLEANING"
                cooler["cleaning_ends_at"] = ends
                touch(cooler)


def quarantine_equipment(run):
    """Safety disposal: reservations CHECKED_OUT -> QUARANTINED_HOLD; coolers
    CHECKED_OUT -> QUARANTINED with cleaning_ends_at = clock + 240 min."""
    ends = fmt_dt(clock_dt() + timedelta(minutes=QUARANTINE_DEEP_CLEAN_MINUTES))
    for res in DB["reservations"].values():
        if res["rescue_run_id"] == run["id"] and res["status"] == "CHECKED_OUT":
            res["status"] = "QUARANTINED_HOLD"
            touch(res)
            cooler = DB["coolers"].get(res["cooler_id"])
            if cooler is not None and cooler["status"] == "CHECKED_OUT":
                cooler["status"] = "QUARANTINED"
                cooler["cleaning_ends_at"] = ends
                touch(cooler)


# ---------------------------------------------------------------------------
# Temperature logs (immutable artifacts: id + created_at only)
# ---------------------------------------------------------------------------

def create_temp_log(run, point, temp_f, recorded_at, user_id):
    rec = {
        "id": new_id(),
        "rescue_run_id": run["id"],
        "point": point,
        "temp_f": round_temp_1dp(temp_f),
        "recorded_at": recorded_at,
        "recorded_by_user_id": user_id,
        "created_at": clock_iso(),
        "_seq": next_seq(),
    }
    DB["temp_logs"][rec["id"]] = rec
    return rec


def pickup_log(run):
    for t in DB["temp_logs"].values():
        if t["rescue_run_id"] == run["id"] and t["point"] == "PICKUP":
            return t
    return None


def latest_arrival_log(run):
    best = None
    for t in DB["temp_logs"].values():
        if t["rescue_run_id"] == run["id"] and t["point"] == "ARRIVAL":
            if best is None or (parse_dt(t["recorded_at"]), t["_seq"]) > (
                parse_dt(best["recorded_at"]),
                best["_seq"],
            ):
                best = t
    return best
