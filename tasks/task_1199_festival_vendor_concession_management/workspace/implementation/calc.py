"""Business logic: calculations, cascades, sweeps, promotions."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from store import db
from util import new_id, stamp_new, touch

ACTIVE_ASSIGNMENT_STATES = ("RESERVED", "CONFIRMED", "ACTIVE")

TIER1_CEILING_CENTS = 500000
TIER2_CEILING_CENTS = 2000000
TIER1_MULTIPLIER_BP = 10000
TIER2_MULTIPLIER_BP = 15000
TIER3_MULTIPLIER_BP = 20000

CHECKIN_GRACE_MINUTES = 30
SLOT_LOCK_MINUTES = 120
NO_SHOW_FINE_CENTS = 25000
STRIKE_SUSPENSION_THRESHOLD = 3

SALES_WEIGHT = 40
COMPLIANCE_WEIGHT = 30
OPERATIONS_WEIGHT = 30
FINE_PENALTY = 15
WAIVED_FINE_PENALTY = 8
NO_SHOW_PENALTY_POINTS = 30
RETURN_THRESHOLD = 70


def rhu(numerator, denominator=1):
    """round_half_up(numerator / denominator) to an integer."""
    return int((Decimal(int(numerator)) / Decimal(int(denominator))).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Computed aggregates (calculations.zone_utility_reservation / load_in_capacity)
# ---------------------------------------------------------------------------

def zone_reserved(zone_id, exclude_assignment_id=None):
    power = 0
    water = 0
    for a in db.assignments.values():
        if a["zone_id"] != zone_id or a["status"] not in ACTIVE_ASSIGNMENT_STATES:
            continue
        if exclude_assignment_id is not None and a["id"] == exclude_assignment_id:
            continue
        power += a["power_draw_amps"]
        if a["requires_water"]:
            water += 1
    return power, water


def slot_reserved(slot_id):
    return sum(
        r["vehicle_count"]
        for r in db.reservations.values()
        if r["slot_id"] == slot_id and r["status"] in ("BOOKED", "CHECKED_IN")
    )


# ---------------------------------------------------------------------------
# calculations.festival_share_tiered / hybrid_fee / per_transaction_rounding_policy
# ---------------------------------------------------------------------------

def _chronological(txs):
    return sorted(txs, key=lambda t: (t["occurred_at"], t["_seq"]))


def _effective_bp(pct_bp, multiplier_bp):
    return rhu(pct_bp * multiplier_bp, 10000)


def _tier_portions(start, end):
    """Split the ladder span (start, end] into per-tier portions."""
    portions = []
    prev = 0
    for bound in (TIER1_CEILING_CENTS, TIER2_CEILING_CENTS):
        if end > prev and start < bound:
            portions.append(min(end, bound) - max(start, prev))
        else:
            portions.append(0)
        prev = bound
    portions.append(max(0, end - max(start, TIER2_CEILING_CENTS)))
    return portions


def tiered_share(txs, pct_bp, tier_mode):
    running = 0
    total = 0
    for tx in _chronological(txs):
        amount = tx["amount_cents"]
        if tier_mode == "WHOLE_TIER":
            new_running = running + amount
            if new_running <= TIER1_CEILING_CENTS:
                mult = TIER1_MULTIPLIER_BP
            elif new_running <= TIER2_CEILING_CENTS:
                mult = TIER2_MULTIPLIER_BP
            else:
                mult = TIER3_MULTIPLIER_BP
            total += rhu(amount * _effective_bp(pct_bp, mult), 10000)
            running = new_running
        else:  # MARGINAL
            start = running
            end = running + amount
            portions = _tier_portions(start, end)
            tx_share = 0
            for portion, mult in zip(portions, (TIER1_MULTIPLIER_BP,
                                                TIER2_MULTIPLIER_BP,
                                                TIER3_MULTIPLIER_BP)):
                if portion > 0:
                    tx_share += rhu(portion * _effective_bp(pct_bp, mult), 10000)
            total += tx_share
            running = end
    return total


def festival_share(snapshot, gross, txs):
    """Festival share over the included transactions per pinned fee terms."""
    model = snapshot.get("fee_model")
    if model == "FLAT_FEE":
        return snapshot.get("flat_fee_cents") or 0
    if model == "REVENUE_SHARE":
        return tiered_share(txs, snapshot.get("revenue_share_pct_bp") or 0,
                            snapshot.get("tier_mode") or "MARGINAL")
    if model == "HYBRID":
        allowance = snapshot.get("free_allowance_cents") or 0
        variable = rhu((snapshot.get("revenue_share_pct_bp") or 0)
                       * max(0, gross - allowance), 10000)
        return max(snapshot.get("minimum_guarantee_cents") or 0,
                   (snapshot.get("flat_fee_cents") or 0) + variable)
    return 0


# ---------------------------------------------------------------------------
# calculations.settlement_financials (provisional / final variants)
# ---------------------------------------------------------------------------

def compute_provisional(settlement):
    assignment = db.assignments[settlement["assignment_id"]]
    txs = _chronological([
        t for t in db.transactions.values()
        if t["assignment_id"] == assignment["id"] and t["status"] == "REPORTED"
    ])
    gross = sum(t["amount_cents"] for t in txs)
    share = festival_share(assignment, gross, txs)
    settlement["provisional_gross_cents"] = gross
    settlement["provisional_share_cents"] = share
    settlement["provisional_payout_cents"] = max(0, gross - share)


def compute_final(settlement):
    assignment = db.assignments[settlement["assignment_id"]]
    festival = db.festivals[assignment["festival_id"]]
    txs = _chronological([
        t for t in db.transactions.values()
        if t["assignment_id"] == assignment["id"]
        and t["status"] != "VOIDED"
        and festival["event_start"] <= t["occurred_at"] <= festival["event_end"]
    ])
    gross = sum(t["amount_cents"] for t in txs)
    share = festival_share(assignment, gross, txs)
    fine_deduction = sum(
        f["amount_cents"] for f in db.fines.values()
        if f["assignment_id"] == assignment["id"] and f["status"] == "ACKNOWLEDGED"
    )
    net_after_share = gross - share
    deductions_applied = min(fine_deduction, max(0, net_after_share))
    settlement["gross_sales_cents"] = gross
    settlement["festival_share_cents"] = share
    settlement["fine_deduction_cents"] = fine_deduction
    settlement["vendor_payout_cents"] = max(0, net_after_share) - deductions_applied
    settlement["vendor_balance_due_cents"] = max(0, share + fine_deduction - gross)


# ---------------------------------------------------------------------------
# Side effects / cascades
# ---------------------------------------------------------------------------

def issue_system_fine(assignment_id, fine_type, amount_cents, description=None):
    assignment = db.assignments[assignment_id]
    fine = stamp_new({
        "id": new_id(),
        "_seq": db.next_seq(),
        "assignment_id": assignment_id,
        "festival_id": assignment["festival_id"],
        "type": fine_type,
        "amount_cents": amount_cents,
        "description": description,
        "status": "ISSUED",
        "created_by_user_id": "system",
        "waived_by_user_id": None,
    })
    db.fines[fine["id"]] = fine
    return fine


def run_waitlist_promotion(festival_id, zone_id):
    """calculations.waitlist_promotion — returns promoted application id or None."""
    festival = db.festivals[festival_id]
    zone = db.zones[zone_id]
    reserved_power, reserved_water = zone_reserved(zone_id)
    candidates = []
    for app in db.applications.values():
        if app["festival_id"] != festival_id or app["status"] != "WAITLISTED":
            continue
        # category exclusivity within the freed zone
        conflict = any(
            a["zone_id"] == zone_id
            and a["status"] in ACTIVE_ASSIGNMENT_STATES
            and db.applications[a["application_id"]]["category"] == app["category"]
            for a in db.assignments.values()
        )
        if conflict:
            continue
        # per-category cap across the festival
        accepted = sum(
            1 for q in db.applications.values()
            if q["festival_id"] == festival_id
            and q["category"] == app["category"]
            and q["status"] == "ACCEPTED"
        )
        if accepted >= festival["category_cap_per_category"]:
            continue
        # power headroom (post-release)
        if app["power_needed_amps"] > zone["power_capacity_amps"] - reserved_power:
            continue
        # water availability (post-release)
        if app["requires_water"] and not reserved_water < zone["water_hookup_total"]:
            continue
        candidates.append(app)
    if not candidates:
        return None
    candidates.sort(key=lambda a: (
        a["created_at"],
        db.vendors[a["vendor_id"]]["legal_name"],
        a["_seq"],
    ))
    top = candidates[0]
    top["status"] = "UNDER_REVIEW"
    touch(top)
    return top["id"]


def _release_hold(assignment, target_status):
    """Shared release/forfeit cascade: booth + zone + waitlist promotion."""
    assignment["status"] = target_status
    touch(assignment)
    booth = db.booths[assignment["booth_id"]]
    booth["status"] = "AVAILABLE"
    touch(booth)
    return run_waitlist_promotion(assignment["festival_id"], assignment["zone_id"])


def release_assignment(assignment):
    return _release_hold(assignment, "RELEASED")


def forfeit_assignment(assignment):
    return _release_hold(assignment, "FORFEITED")


# ---------------------------------------------------------------------------
# calculations.no_show_marking — the sweep-operations checkpoint
# ---------------------------------------------------------------------------

def sweep_festival(festival):
    clock = db.clock
    grace = timedelta(minutes=CHECKIN_GRACE_MINUTES)
    no_shows_marked = 0
    forfeited_ids = []
    promoted_ids = []

    reservations = sorted(
        (r for r in db.reservations.values() if r["festival_id"] == festival["id"]),
        key=lambda r: r["_seq"],
    )
    for r in reservations:
        slot = db.slots[r["slot_id"]]
        if not clock > slot["window_end"] + grace:
            continue
        if r["status"] == "BOOKED":
            r["status"] = "NO_SHOW"
            touch(r)
            no_shows_marked += 1
            issue_system_fine(r["assignment_id"], "NO_SHOW_PENALTY",
                              NO_SHOW_FINE_CENTS, "No-show penalty")
            assignment = db.assignments[r["assignment_id"]]
            if assignment["status"] == "CONFIRMED" and clock > festival["event_start"]:
                promoted = forfeit_assignment(assignment)
                forfeited_ids.append(assignment["id"])
                if promoted:
                    promoted_ids.append(promoted)
        elif r["status"] == "CHECKED_IN":
            r["status"] = "COMPLETED"
            touch(r)

    confirmed = sorted(
        (a for a in db.assignments.values()
         if a["festival_id"] == festival["id"] and a["status"] == "CONFIRMED"),
        key=lambda a: a["_seq"],
    )
    for assignment in confirmed:
        if clock > festival["event_start"]:
            promoted = forfeit_assignment(assignment)
            forfeited_ids.append(assignment["id"])
            if promoted:
                promoted_ids.append(promoted)

    return {
        "no_shows_marked": no_shows_marked,
        "forfeited_assignment_ids": forfeited_ids,
        "promoted_application_ids": promoted_ids,
    }


# ---------------------------------------------------------------------------
# calculations.strike_contagion
# ---------------------------------------------------------------------------

def apply_strike_contagion(vendor):
    vendor["compliance_strikes"] += 1
    touch(vendor)
    if vendor["compliance_strikes"] >= STRIKE_SUSPENSION_THRESHOLD:
        vendor["status"] = "SUSPENDED"
        touch(vendor)
        for app in db.applications.values():
            if app["vendor_id"] == vendor["id"] and app["status"] in (
                    "SUBMITTED", "UNDER_REVIEW", "CHANGES_REQUESTED", "WAITLISTED"):
                app["status"] = "REJECTED"
                touch(app)


# ---------------------------------------------------------------------------
# calculations.sales_percentile / performance_score
# ---------------------------------------------------------------------------

def compute_review_scores(review):
    assignment = db.assignments[review["assignment_id"]]
    festival_id = assignment["festival_id"]

    population = [
        s["gross_sales_cents"]
        for s in db.settlements.values()
        if s["festival_id"] == festival_id and s["status"] in ("FINALIZED", "PAID")
    ]
    own_settlement = next(
        (s for s in db.settlements.values() if s["assignment_id"] == assignment["id"]),
        None,
    )
    self_gross = own_settlement["gross_sales_cents"] if own_settlement else 0
    if population:
        below = sum(1 for g in population if g < self_gross)
        sales_percentile = rhu(100 * below, len(population))
    else:
        sales_percentile = 0

    fines = [f for f in db.fines.values() if f["assignment_id"] == assignment["id"]]
    counted = sum(1 for f in fines if f["status"] in ("ISSUED", "ACKNOWLEDGED", "PAID"))
    waived = sum(1 for f in fines if f["status"] == "WAIVED")
    fine_base = max(0, 100 - FINE_PENALTY * counted)

    if assignment["status"] == "FORFEITED":
        ops_base = 0
    else:
        no_shows = sum(
            1 for r in db.reservations.values()
            if r["assignment_id"] == assignment["id"] and r["status"] == "NO_SHOW"
        )
        ops_base = max(0, 100 - NO_SHOW_PENALTY_POINTS * no_shows)

    official = rhu(SALES_WEIGHT * sales_percentile
                   + COMPLIANCE_WEIGHT * fine_base
                   + OPERATIONS_WEIGHT * ops_base, 100)
    strict = rhu(SALES_WEIGHT * sales_percentile
                 + COMPLIANCE_WEIGHT * max(0, fine_base - WAIVED_FINE_PENALTY * waived)
                 + OPERATIONS_WEIGHT * ops_base, 100)

    review["sales_percentile"] = sales_percentile
    review["compliance_component"] = fine_base
    review["operations_component"] = ops_base
    review["official_score"] = official
    review["strict_score"] = strict
    review["status"] = "INELIGIBLE" if official < RETURN_THRESHOLD else "SCORED"
    touch(review)
