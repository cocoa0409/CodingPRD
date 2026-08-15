from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from core import ApiError, db, now, round6f, touch

STRIKE_LIMIT = 2
WASHOUT_DAYS = 7
CONTACT_CAP = 3
CONTACT_WINDOW_DAYS = 7
REMINDER_CAP = 2
REMINDER_GAP_HOURS = 48
SPEEDER_MIN_SECONDS = 120
LOW_EFFORT_MIN_PCT = 50
LOCALE_BONUS_PCT = Decimal("0.10")
MAX_AWARD_CENTS = 10000
TRIM_MULT = Decimal("5.0")
UPTAKE_ASSUMPTION = Decimal("0.5")

WAVE_TERMINAL = ("PUBLISHED", "CANCELLED")


# ---------------------------------------------------------------------------
# Cells
# ---------------------------------------------------------------------------

def cell_touch(cell):
    """Re-derive saturation status and record the mutation on the cell."""
    cell["status"] = "SATURATED" if cell["active_count"] >= cell["target_size"] else "OPEN"
    touch(cell)


def find_cell_by_triple(age_band, district, tenure_bucket):
    for c in db.cells.values():
        if (c["age_band"] == age_band and c["district"] == district
                and c["tenure_bucket"] == tenure_bucket):
            return c
    return None


# ---------------------------------------------------------------------------
# Privacy holds
# ---------------------------------------------------------------------------

def active_hold_for(panelist_id):
    for h in db.holds.values():
        if h["panelist_id"] == panelist_id and h["status"] == "ACTIVE":
            return h
    return None


# ---------------------------------------------------------------------------
# Invitations / streaks
# ---------------------------------------------------------------------------

def panelist_invitations(panelist_id):
    return [i for i in db.invitations.values() if i["panelist_id"] == panelist_id]


def compute_streak(panelist):
    """Leading EXPIRED count walking wave closes_at DESC, invitation
    created_at DESC; SUPPRESSED skipped, anything else breaks the run."""
    invs = panelist_invitations(panelist["id"])
    invs.sort(
        key=lambda i: (db.waves[i["wave_id"]]["closes_at"], i["created_at"], i["_seq"]),
        reverse=True,
    )
    streak = 0
    for inv in invs:
        s = inv["status"]
        if s == "EXPIRED":
            streak += 1
        elif s == "SUPPRESSED":
            continue
        else:
            break
    return streak


def recompute_streak(panelist):
    s = compute_streak(panelist)
    if s != panelist["missed_streak"]:
        panelist["missed_streak"] = s
        touch(panelist)
    return s


def suppress_live_invitations(panelist):
    for inv in panelist_invitations(panelist["id"]):
        if inv["status"] == "SENT":
            inv["status"] = "SUPPRESSED"
            touch(inv)
            cell = db.cells.get(panelist["home_cell_id"])
            if cell is not None:
                cell["reserved_count"] -= 1
                cell_touch(cell)


# ---------------------------------------------------------------------------
# Incentives
# ---------------------------------------------------------------------------

def compute_award_amount(wave, panelist, completeness_pct, speeder_flag):
    """Pinned evaluation order with per-component round-half-up."""
    base = Decimal(wave["base_incentive_cents"])
    pct = Decimal(str(completeness_pct))
    completion_bonus = (base * pct / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    if panelist["preferred_locale"] != "en":
        locale_bonus = (base * LOCALE_BONUS_PCT).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    else:
        locale_bonus = Decimal(0)
    subtotal = base + completion_bonus + locale_bonus
    if speeder_flag:
        subtotal = (subtotal / Decimal(2)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(min(subtotal, Decimal(MAX_AWARD_CENTS)))


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def representativeness_score():
    total_target = sum(c["target_size"] for c in db.cells.values())
    if total_target == 0:
        return 100.0
    T = Decimal(total_target)
    acc = Decimal(0)
    for c in db.cells.values():
        if c["target_size"] <= 0:
            continue
        deficit = max(0, c["target_size"] - c["active_count"])
        ratio = min(Decimal(deficit) / Decimal(c["target_size"]), Decimal(1))
        acc += (Decimal(c["target_size"]) / T) * ratio
    return round6f(Decimal(100) - Decimal(100) * acc)


def projected_response_rate(wave):
    invited = wave["invited_count"]
    completed = wave["completed_count"]
    if invited == 0:
        return 0.0
    if wave["status"] == "FIELDING":
        open_sent = sum(
            1 for i in db.invitations.values()
            if i["wave_id"] == wave["id"] and i["status"] == "SENT"
        )
        value = (Decimal(completed) + UPTAKE_ASSUMPTION * Decimal(open_sent)) / Decimal(invited)
    elif wave["status"] in ("CLOSED", "WEIGHTED", "PUBLISHED"):
        value = Decimal(completed) / Decimal(invited)
    else:
        value = Decimal(0)
    return round6f(value)


def final_response_rate(wave):
    if wave["status"] not in ("CLOSED", "WEIGHTED", "PUBLISHED"):
        return None
    invited = wave["invited_count"]
    if invited == 0:
        return 0.0
    return round6f(Decimal(wave["completed_count"]) / Decimal(invited))


# ---------------------------------------------------------------------------
# Weighting
# ---------------------------------------------------------------------------

def compute_weights(wave, method):
    accepted = [r for r in db.responses.values()
                if r["wave_id"] == wave["id"] and r["status"] == "ACCEPTED"]
    N = len(accepted)
    if N == 0:
        raise ApiError("ERR_WEIGHTS_NOT_COMPUTABLE", 422,
                       "No ACCEPTED responses exist for the wave")

    def cell_of(resp):
        return db.panelists[resp["panelist_id"]]["home_cell_id"]

    by_cell = {}
    for r in accepted:
        by_cell.setdefault(cell_of(r), []).append(r)

    weights = {}
    if method == "POST_STRAT":
        for cid, rs in by_cell.items():
            cell = db.cells[cid]
            raw = Decimal(cell["target_size"]) / Decimal(len(rs))
            for r in rs:
                weights[r["id"]] = raw
    else:  # RIM — single deterministic rake pass: age_band then tenure_bucket
        for r in accepted:
            weights[r["id"]] = Decimal(1)
        for margin_key in ("age_band", "tenure_bucket"):
            groups = {}
            for r in accepted:
                cell = db.cells[cell_of(r)]
                groups.setdefault(cell[margin_key], []).append(r)
            for grp, rs in groups.items():
                target = sum(Decimal(c["target_size"]) for c in db.cells.values()
                             if c[margin_key] == grp)
                current = sum(weights[r["id"]] for r in rs)
                if current != 0:
                    factor = target / current
                    for r in rs:
                        weights[r["id"]] *= factor

    # Common tail: normalize to mass N, trim at TRIM_MULT * mean(=1), renormalize once.
    total = sum(weights.values())
    if total != 0:
        f = Decimal(N) / total
        for k in weights:
            weights[k] *= f
    for k in weights:
        if weights[k] > TRIM_MULT:
            weights[k] = TRIM_MULT
    total2 = sum(weights.values())
    if total2 != 0:
        f = Decimal(N) / total2
        for k in weights:
            weights[k] *= f

    mass = sum(weights.values())
    shares = {}
    for cid in sorted(by_cell):
        s = sum(weights[r["id"]] for r in by_cell[cid])
        shares[cid] = round6f(s / mass) if mass != 0 else 0.0

    if mass != 0:
        mean = mass / Decimal(N)
        var = sum((w - mean) ** 2 for w in weights.values()) / Decimal(N)
        sd = var.sqrt()
        deff = Decimal(1) + (sd / mean) ** 2 if mean != 0 else Decimal(1)
    else:
        deff = Decimal(1)

    return {
        "weight_mass": round6f(mass),
        "accepted_count": N,
        "design_effect": round6f(deff),
        "weighted_cell_shares": shares,
    }
