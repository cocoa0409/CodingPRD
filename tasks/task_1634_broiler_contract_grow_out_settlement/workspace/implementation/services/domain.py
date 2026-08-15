"""Derived fields, cascades, and calculations.

Every computed value follows SCAFFOLD.yaml §1.3 and PRD §2/§3 exactly.
Monetary lines are whole-cent integers rounded half-up per line, then summed;
ratio quantities are stored at exactly 4 decimal places, round-half-up.
"""
from decimal import Decimal

import db
import utils
from utils import d4, q4

# Constants (SCAFFOLD §1.3, §1.2)
FEED_WASTE_CREDIT_LBS = 2000
DOWNTIME_DAYS = 14
CONDEMNED_LOSS_DOWNTIME_DAYS = 21
MIN_GROW_DAYS = 35
CONDEMNATION_LOSS_THRESHOLD = Decimal("0.30")
CONDEMNATION_ALLOWANCE = Decimal("0.005")
CONDEMNATION_RATE_CENTS = 40
RATING_WINDOW = 3

HOUSE_COUNT_STATUSES = ("ACTIVE", "PLACED")
ELIGIBLE_HOUSE_STATUSES = ("ACTIVE", "PLACED", "DOWNTIME")
IN_FLIGHT_FLOCK_STATUSES = ("PLANNED", "PLACED", "GROWING", "CATCH_SCHEDULED", "HARVESTED")
SCORED_FLOCK_STATUSES = ("HARVESTED", "SETTLED")

FEED_TYPES = ("STARTER", "GROWER", "FINISHER", "WITHDRAWAL")
LOAN_PURPOSES = ("CAPITAL_UPGRADE", "OPERATING")
AUDIT_RESULTS = ("PASS", "FAIL")


def bump(record):
    """Every mutation advances version by exactly one and refreshes updated_at."""
    record["version"] += 1
    record["updated_at"] = utils.now_iso()


# ------------------------------------------------------------------ lookups
def house_of_flock(flock):
    return db.houses.get(flock["house_id"])


def grower_of_flock(flock):
    house = house_of_flock(flock)
    return db.growers.get(house["grower_id"]) if house else None


def grower_id_of_flock(flock):
    house = house_of_flock(flock)
    return house["grower_id"] if house else None


def settlement_for_flock(flock_id):
    for s in db.settlements.values():
        if s["flock_id"] == flock_id:
            return s
    return None


def group_members(group_id):
    return [f for f in db.flocks.values() if f["settlement_group_id"] == group_id]


def scored_members(group_id):
    """Members counted in group averages and ranking: HARVESTED or SETTLED."""
    return [f for f in group_members(group_id) if f["status"] in SCORED_FLOCK_STATUSES]


def issued_loans(grower_id):
    """Grower's ISSUED loans, oldest first (created_at ASC, insertion tiebreak)."""
    rows = [
        l
        for l in db.loans.values()
        if l["grower_id"] == grower_id and l["status"] == "ISSUED"
    ]
    return utils.created_order(rows)


# ------------------------------------------------------------------ grower derived
def recompute_house_count(grower):
    """house_count = houses in ACTIVE or PLACED. Returns True when changed."""
    new = sum(
        1
        for h in db.houses.values()
        if h["grower_id"] == grower["id"] and h["house_status"] in HOUSE_COUNT_STATUSES
    )
    if new != grower["house_count"]:
        grower["house_count"] = new
        return True
    return False


def eligible_house_count(grower_id):
    """Houses in ACTIVE, PLACED, or DOWNTIME (contract activation/renewal gate)."""
    return sum(
        1
        for h in db.houses.values()
        if h["grower_id"] == grower_id and h["house_status"] in ELIGIBLE_HOUSE_STATUSES
    )


def recompute_loan_outstanding(grower):
    """loan_outstanding_cents = sum of outstanding over ISSUED loans."""
    new = sum(l["outstanding_cents"] for l in issued_loans(grower["id"]))
    if new != grower["loan_outstanding_cents"]:
        grower["loan_outstanding_cents"] = new
        return True
    return False


def recompute_performance_rating(grower):
    """Mean performance_score over the grower's 3 most recent SETTLED flocks.

    Ordering: placed_date DESC, then later settled date (updated_at DESC proxy),
    then created_at ASC (insertion order). Null when no SETTLED flocks.
    """
    house_ids = {h["id"] for h in db.houses.values() if h["grower_id"] == grower["id"]}
    settled = [
        f
        for f in db.flocks.values()
        if f["house_id"] in house_ids and f["status"] == "SETTLED"
    ]
    if not settled:
        new = None
    else:
        s = sorted(settled, key=lambda f: f["_seq"])  # created_at ASC
        s = sorted(s, key=lambda f: f["updated_at"], reverse=True)  # later settled
        s = sorted(s, key=lambda f: f["placed_date"] or "", reverse=True)
        window = s[:RATING_WINDOW]
        total = sum(d4(f["performance_score"]) for f in window)
        new = float(q4(total / Decimal(len(window))))
    if grower["performance_rating"] != new:
        grower["performance_rating"] = new
        return True
    return False


# ------------------------------------------------------------------ flock derived
def recompute_flock_ratios(flock):
    """livability_pct and condemnation_pct from current counters (PRD §3.3)."""
    placed = flock["placed_head"]
    if placed > 0:
        flock["livability_pct"] = float(
            q4(Decimal(placed - flock["mortality_head"]) / Decimal(placed))
        )
    denom = max(1, placed - flock["mortality_head"])
    flock["condemnation_pct"] = float(
        q4(Decimal(flock["condemnation_head"]) / Decimal(denom))
    )


def compute_adj_fcr(flock):
    """(feed_delivered_lbs - FEED_WASTE_CREDIT_LBS) / live_weight_lbs, 4dp half-up."""
    return q4(
        (Decimal(flock["feed_delivered_lbs"]) - Decimal(FEED_WASTE_CREDIT_LBS))
        / Decimal(flock["live_weight_lbs"])
    )


def apply_feed_delivery(flock, feed_lbs):
    flock["feed_delivered_lbs"] += feed_lbs
    if flock["status"] == "PLACED":
        # First delivery flips PLACED -> GROWING.
        flock["status"] = "GROWING"
    bump(flock)


def apply_mortality_report(flock, dead_head, condemned_head):
    flock["mortality_head"] += dead_head
    flock["condemnation_head"] += condemned_head
    recompute_flock_ratios(flock)
    bump(flock)


def apply_weight_ticket(flock, live_weight_lbs):
    flock["live_weight_lbs"] += live_weight_lbs
    if flock["adj_fcr"] is not None and flock["live_weight_lbs"] > 0:
        # Post-harvest ticket: keep the harvest-time ratio consistent with the
        # new weight so settlement recomputation sees fresh inputs (§2.7).
        flock["adj_fcr"] = float(compute_adj_fcr(flock))
        refresh_group_averages(db.settlement_groups.get(flock["settlement_group_id"]))
    bump(flock)


# ------------------------------------------------------------------ group averages
def compute_group_averages(group_id):
    """(avg_fcr, avg_livability, avg_condemnation) as 4dp Decimals over the
    HARVESTED+SETTLED members, or (None, None, None) when none have harvested."""
    members = scored_members(group_id)
    if not members:
        return None, None, None
    n = Decimal(len(members))
    avg_fcr = q4(sum(d4(m["adj_fcr"]) for m in members) / n)
    avg_liv = q4(sum(d4(m["livability_pct"]) for m in members) / n)
    avg_cond = q4(sum(d4(m["condemnation_pct"]) for m in members) / n)
    return avg_fcr, avg_liv, avg_cond


def refresh_group_averages(group):
    """Store the current averages on the group; bump when changed."""
    if group is None:
        return
    avg_fcr, avg_liv, avg_cond = compute_group_averages(group["id"])
    new = (
        float(avg_fcr) if avg_fcr is not None else None,
        float(avg_liv) if avg_liv is not None else None,
        float(avg_cond) if avg_cond is not None else None,
    )
    old = (
        group["group_avg_fcr"],
        group["group_avg_livability_pct"],
        group["group_avg_condemnation_pct"],
    )
    if old != new:
        group["group_avg_fcr"], group["group_avg_livability_pct"], group[
            "group_avg_condemnation_pct"
        ] = new
        bump(group)


# ------------------------------------------------------------------ scoring
def transient_score(adj_fcr, livability_pct, condemnation_pct, avgs):
    """performance_score formula (SCAFFOLD §1.3), 4dp half-up."""
    avg_fcr, avg_liv, avg_cond = avgs
    score = Decimal(100)
    if avg_fcr:
        score += Decimal(50) * (avg_fcr - adj_fcr) / avg_fcr
    score += Decimal(20) * (livability_pct - avg_liv)
    score -= Decimal(100) * (condemnation_pct - avg_cond)
    return q4(score)


def flock_score(flock, avgs):
    """SETTLED flocks use their stored final score; HARVESTED flocks are scored
    transiently against the current group averages (provisional preview)."""
    if flock["status"] == "SETTLED" and flock["performance_score"] is not None:
        return d4(flock["performance_score"])
    return transient_score(
        d4(flock["adj_fcr"]),
        d4(flock["livability_pct"]),
        d4(flock["condemnation_pct"]),
        avgs,
    )


def rank_members(members, scores):
    """Best-first ordering: score DESC, live_weight_lbs DESC, placed_date ASC,
    then insertion order."""
    return sorted(
        members,
        key=lambda m: (
            -scores[m["id"]],
            -m["live_weight_lbs"],
            m["placed_date"] or "",
            m["_seq"],
        ),
    )


# ------------------------------------------------------------------ settlement math
def compute_settlement_amounts(flock):
    """Full settlement_amounts calculation (SCAFFOLD §1.3 / PRD §3.8)."""
    group = db.settlement_groups[flock["settlement_group_id"]]
    contract = db.contracts[flock["contract_id"]]
    grower = grower_of_flock(flock)

    members = scored_members(group["id"])
    avgs = compute_group_averages(group["id"])
    scores = {m["id"]: flock_score(m, avgs) for m in members}
    ordered = rank_members(members, scores)
    rank_position = next(
        i + 1 for i, m in enumerate(ordered) if m["id"] == flock["id"]
    )
    group_size = len(members)
    rank_pct = Decimal(group_size - rank_position) / Decimal(group_size)

    if rank_pct >= Decimal("0.75"):
        uplift = Decimal("1.5")
    elif rank_pct >= Decimal("0.50"):
        uplift = Decimal("0.8")
    elif rank_pct >= Decimal("0.25"):
        uplift = Decimal("0.2")
    else:
        uplift = Decimal("0")
    base_rate = Decimal(contract["base_pay_cents_per_lb"]) + uplift

    live_weight = Decimal(flock["live_weight_lbs"])
    base_amount_cents = utils.round_cents(live_weight * base_rate)

    adj_fcr = d4(flock["adj_fcr"])
    avg_fcr = avgs[0]
    if avg_fcr is not None and adj_fcr <= avg_fcr * Decimal("0.98"):
        bonus_rate = Decimal("0.5")
    elif avg_fcr is not None and adj_fcr <= avg_fcr:
        bonus_rate = Decimal("0.25")
    else:
        bonus_rate = Decimal("0")
    fcr_bonus_cents = utils.round_cents(live_weight * bonus_rate)

    condemnation_pct = d4(flock["condemnation_pct"])
    excess = condemnation_pct - CONDEMNATION_ALLOWANCE
    if excess < 0:
        excess = Decimal(0)
    condemnation_deduction_cents = utils.round_cents(
        live_weight * Decimal(CONDEMNATION_RATE_CENTS) * excess
    )

    positive_subtotal = base_amount_cents + fcr_bonus_cents - condemnation_deduction_cents

    loans = issued_loans(grower["id"])
    outstanding_sum = sum(l["outstanding_cents"] for l in loans)
    if positive_subtotal <= 0 or not loans:
        loan_repayment_cents = 0
    else:
        recovery_pct = loans[0]["recovery_pct"]  # oldest ISSUED loan's terms
        share = utils.round_cents(
            Decimal(positive_subtotal) * Decimal(recovery_pct) / Decimal(100)
        )
        loan_repayment_cents = min(share, outstanding_sum)

    net_amount_cents = positive_subtotal - loan_repayment_cents
    variant = "PROVISIONAL" if group["status"] == "OPEN" else "FINAL"

    return {
        "rank_position": rank_position,
        "base_amount_cents": base_amount_cents,
        "fcr_bonus_cents": fcr_bonus_cents,
        "condemnation_deduction_cents": condemnation_deduction_cents,
        "loan_repayment_cents": loan_repayment_cents,
        "net_amount_cents": net_amount_cents,
        "variant": variant,
    }


def compute_settlement_for_flock(flock):
    """Create the flock's settlement (PENDING) when missing, else recompute the
    existing row's amounts (SCAFFOLD §1.5 recompute-settlement)."""
    amounts = compute_settlement_amounts(flock)
    existing = settlement_for_flock(flock["id"])
    if existing is None:
        rec = utils.make_record(
            {
                "flock_id": flock["id"],
                "variant": amounts["variant"],
                "rank_position": amounts["rank_position"],
                "base_amount_cents": amounts["base_amount_cents"],
                "fcr_bonus_cents": amounts["fcr_bonus_cents"],
                "condemnation_deduction_cents": amounts["condemnation_deduction_cents"],
                "loan_repayment_cents": amounts["loan_repayment_cents"],
                "net_amount_cents": amounts["net_amount_cents"],
                "status": "PENDING",
            }
        )
        db.settlements[rec["id"]] = rec
        return rec
    for key, value in amounts.items():
        existing[key] = value
    bump(existing)
    return existing


def apply_repayment_waterfall(grower, amount):
    """Apply a settlement's repayment to the grower's ISSUED loans oldest-first;
    a loan reaching zero becomes REPAID (SCAFFOLD §1.3 loan_outstanding_recompute)."""
    loans = issued_loans(grower["id"])
    remaining = min(amount, sum(l["outstanding_cents"] for l in loans))
    for loan in loans:
        if remaining <= 0:
            break
        pay = min(loan["outstanding_cents"], remaining)
        loan["outstanding_cents"] -= pay
        remaining -= pay
        if loan["outstanding_cents"] == 0:
            loan["status"] = "REPAID"
        bump(loan)
    return recompute_loan_outstanding(grower)


# ------------------------------------------------------------------ big cascades
def confirm_placement(placement):
    """Placement SCHEDULED -> CONFIRMED; flock PLANNED -> PLACED; house -> PLACED."""
    flock = db.flocks[placement["flock_id"]]
    house = house_of_flock(flock)
    today = utils.today_str()

    placement["status"] = "CONFIRMED"
    placement["confirmed_date"] = today
    bump(placement)

    flock["status"] = "PLACED"
    flock["placed_head"] = placement["head_count"]
    flock["placed_date"] = today
    recompute_flock_ratios(flock)
    bump(flock)

    if house["house_status"] in ("ACTIVE", "PLACED", "DOWNTIME"):
        changed = house["house_status"] != "PLACED" or house["downtime_until"] is not None
        house["house_status"] = "PLACED"
        house["downtime_until"] = None
        if changed:
            bump(house)

    grower = db.growers.get(house["grower_id"])
    if grower is not None and recompute_house_count(grower):
        bump(grower)


def harvest_flock(schedule):
    """Catch completion cascade (PRD §3.5): schedule COMPLETED, flock HARVESTED
    with adj_fcr, house PLACED -> DOWNTIME (catch_date + 14), group averages."""
    flock = db.flocks[schedule["flock_id"]]
    house = house_of_flock(flock)

    schedule["status"] = "COMPLETED"
    bump(schedule)

    flock["status"] = "HARVESTED"
    flock["adj_fcr"] = float(compute_adj_fcr(flock))
    bump(flock)

    new_downtime = utils.add_days_str(schedule["catch_date"], DOWNTIME_DAYS)
    changed = False
    if house["house_status"] == "PLACED":
        house["house_status"] = "DOWNTIME"
        house["downtime_until"] = new_downtime
        changed = True
    elif house["house_status"] in ("DOWNTIME", "QUARANTINED"):
        if house["downtime_until"] is None or new_downtime > house["downtime_until"]:
            house["downtime_until"] = new_downtime
            changed = True
    if changed:
        bump(house)

    grower = db.growers.get(house["grower_id"])
    if grower is not None and recompute_house_count(grower):
        bump(grower)

    refresh_group_averages(db.settlement_groups.get(flock["settlement_group_id"]))


def declare_condemned_loss(flock):
    """Flock GROWING -> CONDEMNED_LOSS; house -> DOWNTIME for 21 days (PRD §3.6)."""
    house = house_of_flock(flock)

    flock["status"] = "CONDEMNED_LOSS"
    bump(flock)

    new_downtime = utils.add_days_str(
        utils.today_str(), CONDEMNED_LOSS_DOWNTIME_DAYS
    )
    changed = False
    if house["house_status"] != "DECOMMISSIONED":
        if house["house_status"] != "DOWNTIME":
            house["house_status"] = "DOWNTIME"
            changed = True
        if house["downtime_until"] != new_downtime:
            house["downtime_until"] = new_downtime
            changed = True
    if changed:
        bump(house)

    grower = db.growers.get(house["grower_id"])
    if grower is not None and recompute_house_count(grower):
        bump(grower)


def apply_audit_fail(house, audit):
    """FAIL audit cascade (PRD §3.4): house -> QUARANTINED from ACTIVE or
    DOWNTIME; downtime_until extends to max(current, audit_date + days)."""
    quarantine_end = utils.add_days_str(audit["audit_date"], audit["quarantine_days"])
    changed = False
    status = house["house_status"]
    if status == "ACTIVE":
        house["house_status"] = "QUARANTINED"
        house["downtime_until"] = quarantine_end
        changed = True
    elif status in ("DOWNTIME", "QUARANTINED"):
        if status != "QUARANTINED":
            house["house_status"] = "QUARANTINED"
            changed = True
        current = house["downtime_until"]
        if current is None or quarantine_end > current:
            house["downtime_until"] = quarantine_end
            changed = True
    # PLACED / DECOMMISSIONED houses record the audit without a status change.
    if changed:
        bump(house)
        grower = db.growers.get(house["grower_id"])
        if grower is not None and recompute_house_count(grower):
            bump(grower)


def fail_quarantine_covers_now(house_id):
    """True when some FAIL audit's quarantine window covers the logical now."""
    now = db.get_clock()
    for a in db.audits.values():
        if a["house_id"] != house_id or a["result"] != "FAIL":
            continue
        start = utils.midnight_utc(a["audit_date"])
        end = utils.midnight_utc(utils.add_days_str(a["audit_date"], a["quarantine_days"]))
        if start <= now <= end:
            return True
    return False


def latest_fail_audit_date(house_id):
    """audit_date of the most recent FAIL audit (the one holding quarantine)."""
    fails = [
        a
        for a in db.audits.values()
        if a["house_id"] == house_id and a["result"] == "FAIL"
    ]
    if not fails:
        return None
    fails.sort(key=lambda a: (a["audit_date"], a["_seq"]))
    return fails[-1]["audit_date"]


def pass_since_fail_exists(house_id):
    """A PASS audit dated on or after the quarantine-triggering FAIL exists."""
    latest_fail = latest_fail_audit_date(house_id)
    if latest_fail is None:
        return False
    return any(
        a["house_id"] == house_id
        and a["result"] == "PASS"
        and a["audit_date"] >= latest_fail
        for a in db.audits.values()
    )


def approve_settlement(settlement):
    """PENDING -> APPROVED cascade (PRD §3.10): flock SETTLED with final score,
    loan repayment waterfall, grower rating recomputed."""
    flock = db.flocks[settlement["flock_id"]]
    group = db.settlement_groups[flock["settlement_group_id"]]
    grower = grower_of_flock(flock)

    settlement["status"] = "APPROVED"
    bump(settlement)

    refresh_group_averages(group)
    avgs = compute_group_averages(group["id"])
    flock["status"] = "SETTLED"
    flock["performance_score"] = float(
        transient_score(
            d4(flock["adj_fcr"]),
            d4(flock["livability_pct"]),
            d4(flock["condemnation_pct"]),
            avgs,
        )
    )
    bump(flock)

    changed = apply_repayment_waterfall(grower, settlement["loan_repayment_cents"])
    changed = recompute_performance_rating(grower) or changed
    if changed:
        bump(grower)


def lock_group(group):
    """OPEN -> LOCKED; every PENDING settlement in the group is recomputed and
    flipped to FINAL (PRD §3.7)."""
    group["status"] = "LOCKED"
    bump(group)
    member_ids = {f["id"] for f in group_members(group["id"])}
    for s in utils.created_order(
        [s for s in db.settlements.values() if s["flock_id"] in member_ids]
    ):
        if s["status"] != "PENDING":
            continue
        flock = db.flocks[s["flock_id"]]
        amounts = compute_settlement_amounts(flock)
        for key, value in amounts.items():
            s[key] = value
        bump(s)
