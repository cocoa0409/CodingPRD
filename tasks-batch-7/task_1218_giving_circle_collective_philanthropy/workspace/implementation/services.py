"""Business logic: derived-field recompute, state transitions, cascades, calculations."""

import math
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store
from response import new_id, iso3


# ---------------------------------------------------------------- clock helpers

def now_logical():
    return store.clock


def parse_iso(s):
    """Parse an ISO 8601 timestamp into an aware datetime (UTC if no offset)."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def round_half_up_cents(value):
    """value is a Decimal; round to integer cents, half up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def fee_on(base_cents, admin_fee_percent):
    return round_half_up_cents(Decimal(base_cents) * Decimal(admin_fee_percent) / Decimal(100))


# ---------------------------------------------------------------- common fields

def stamp_new(entity):
    ts = iso3(now_logical())
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    return entity


def touch(entity):
    entity["updated_at"] = iso3(now_logical())
    entity["version"] = entity.get("version", 1) + 1
    return entity


# ---------------------------------------------------------------- lookups

def get_or_404(table, key, message="Resource does not exist"):
    from errors import not_found
    obj = table.get(key)
    if obj is None:
        raise not_found(message)
    return obj


def memberships_of_circle(circle_id):
    return [m for m in store.memberships.values() if m["circle_id"] == circle_id]


def contributions_of_cycle(cycle_id):
    return [c for c in store.contributions.values() if c["cycle_id"] == cycle_id]


def nominations_of_cycle(cycle_id):
    return [n for n in store.nominations.values() if n["cycle_id"] == cycle_id]


def ballots_of_cycle(cycle_id):
    return [b for b in store.ballots.values() if b["cycle_id"] == cycle_id]


def payouts_of_award(award_id):
    return [p for p in store.payouts.values() if p["award_id"] == award_id]


def reports_of_award(award_id):
    return [r for r in store.reports.values() if r["award_id"] == award_id]


def awards_of_cycle(cycle_id):
    return [a for a in store.awards.values() if a["cycle_id"] == cycle_id]


# ---------------------------------------------------------------- derived fields

def recompute_circle_counts(circle):
    mems = memberships_of_circle(circle["id"])
    active = sum(1 for m in mems if m["status"] == "ACTIVE")
    renewed = sum(m.get("renewal_count", 0) for m in mems)
    changed = (circle["active_member_count"] != active or
               circle["renewed_member_count"] != renewed)
    circle["active_member_count"] = active
    circle["renewed_member_count"] = renewed
    if changed:
        touch(circle)


def recompute_cycle_ledger(cycle):
    """Recompute the six totals, pooled balance, budgets, and ballot count."""
    contributions = contributions_of_cycle(cycle["id"])
    received = sum(c["amount_cents"] for c in contributions
                   if c["status"] in ("RECEIVED", "REFUND_REQUESTED"))
    pledged = sum(c["amount_cents"] for c in contributions
                  if c["status"] == "PLEDGED")
    refunded = sum(c["amount_cents"] for c in contributions
                   if c["status"] == "REFUNDED")
    # released payouts: find via awards of this cycle
    released = 0
    for award in awards_of_cycle(cycle["id"]):
        for p in payouts_of_award(award["id"]):
            if p["status"] == "RELEASED":
                released += p["amount_cents"]

    cycle["received_total_cents"] = received
    cycle["pledged_outstanding_cents"] = pledged
    cycle["refunded_total_cents"] = refunded
    cycle["released_total_cents"] = released

    # PRD §2.6: pooled balance is what remains of the received funds (gross
    # inflow, i.e. received_total + refunded_total since refunded funds were
    # once received) after subtracting the refunded total, the released total,
    # and the transferred administration fee, then adding rollover funds
    # carried in and subtracting rollover funds carried out. The refunded
    # terms cancel, so the refund never double-subtracts.
    pooled = (received - released
              - cycle.get("admin_fee_transferred_cents", 0)
              + cycle.get("rollover_in_cents", 0)
              - cycle.get("rollover_out_cents", 0))
    cycle["pooled_balance_cents"] = pooled

    reserve = cycle.get("operating_reserve_cents", 0)
    fee_pct = cycle.get("admin_fee_percent", 0)
    provisional_base = received + pledged
    cycle["grant_budget_provisional_cents"] = (
        provisional_base - fee_on(provisional_base, fee_pct) - reserve)
    if not cycle.get("budget_locked", False):
        final_base = received
        cycle["grant_budget_final_cents"] = (
            final_base - fee_on(final_base, fee_pct) - reserve)

    cycle["ballots_cast_count"] = len(ballots_of_cycle(cycle["id"]))
    touch(cycle)


def recompute_award_payout_status(award):
    payouts = payouts_of_award(award["id"])
    total = len(payouts)
    released = sum(1 for p in payouts if p["status"] == "RELEASED")
    if released == 0:
        new = "UNPAID"
    elif released == total:
        new = "PAID"
    else:
        new = "PARTIALLY_PAID"
    if award["payout_status"] != new:
        award["payout_status"] = new
        touch(award)


def recompute_award_reporting_status(award):
    reports = reports_of_award(award["id"])
    if reports and all(r["status"] == "ACCEPTED" for r in reports):
        new = "REPORTS_COMPLETE"
    else:
        new = "AWAITING_REPORTS"
    if award["reporting_status"] != new:
        award["reporting_status"] = new
        touch(award)


def recompute_nonprofit_standing(nonprofit):
    """GOOD iff no OVERDUE GranteeReport anywhere references an award of this nonprofit."""
    has_overdue = False
    for award in store.awards.values():
        if award["nonprofit_id"] != nonprofit["id"]:
            continue
        for report in reports_of_award(award["id"]):
            if report["status"] == "OVERDUE":
                has_overdue = True
                break
        if has_overdue:
            break
    new = "SUSPENDED" if has_overdue else "GOOD"
    if nonprofit["standing"] != new:
        nonprofit["standing"] = new
        touch(nonprofit)


def recompute_vetting_score(nomination):
    fh = nomination.get("financial_health")
    ma = nomination.get("mission_alignment")
    oc = nomination.get("org_capacity")
    if fh is None or ma is None or oc is None:
        nomination["vetting_score"] = None
        return
    cycle = store.cycles.get(nomination["cycle_id"])
    circle = store.circles.get(cycle["circle_id"]) if cycle else None
    profile = circle["vetting_profile"] if circle else "BALANCED"
    if profile == "EQUITY_FIRST":
        w_fin, w_align, w_cap = Decimal("0.25"), Decimal("0.50"), Decimal("0.25")
    else:  # BALANCED
        w_fin, w_align, w_cap = Decimal("0.40"), Decimal("0.30"), Decimal("0.30")
    score = w_fin * Decimal(fh) + w_align * Decimal(ma) + w_cap * Decimal(oc)
    nomination["vetting_score"] = int(score.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------- tally

def compute_tally(cycle):
    """Return dict with ballots_cast_count, quorum_required, quorum_met,
    finalist_points (list of dicts), total_points_cast."""
    finalists = [n for n in nominations_of_cycle(cycle["id"])
                 if n["status"] == "FINALIST"]
    ballots = ballots_of_cycle(cycle["id"])
    points = {n["id"]: 0 for n in finalists}
    first_choice = {n["id"]: 0 for n in finalists}
    for b in ballots:
        allocs = b.get("allocations") or []
        # total points per finalist
        for entry in allocs:
            nid = entry.get("nomination_id")
            if nid in points:
                points[nid] += int(entry.get("points", 0))
        # first-choice: strictly greatest points on this ballot; ties -> nobody
        if allocs:
            max_pts = max(int(e.get("points", 0)) for e in allocs)
            leaders = [e.get("nomination_id") for e in allocs
                       if int(e.get("points", 0)) == max_pts]
            if len(leaders) == 1 and leaders[0] in first_choice:
                first_choice[leaders[0]] += 1

    finalist_points = []
    for n in finalists:
        finalist_points.append({
            "nomination_id": n["id"],
            "total_points": points[n["id"]],
            "first_choice_count": first_choice[n["id"]],
        })
    # deterministic ordering for output: total desc, first_choice desc, created_at asc
    created_of = {n["id"]: n["created_at"] for n in finalists}
    finalist_points.sort(key=lambda fp: (
        -fp["total_points"],
        -fp["first_choice_count"],
        created_of[fp["nomination_id"]],
    ))
    ballots_cast = len(ballots)
    total_points_cast = sum(fp["total_points"] for fp in finalist_points)
    snapshot = cycle.get("active_member_snapshot")
    quorum_percent = cycle.get("quorum_percent", 0)
    if snapshot is None:
        quorum_required = 0
    else:
        quorum_required = math.ceil(snapshot * quorum_percent / 100)
    quorum_met = ballots_cast >= quorum_required
    return {
        "ballots_cast_count": ballots_cast,
        "quorum_required": quorum_required,
        "quorum_met": quorum_met,
        "finalist_points": finalist_points,
        "total_points_cast": total_points_cast,
    }


def pick_winner(cycle, tally):
    finalists = [n for n in nominations_of_cycle(cycle["id"])
                 if n["status"] == "FINALIST"]
    if not finalists:
        return None
    by_id = {fp["nomination_id"]: fp for fp in tally["finalist_points"]}

    def key(n):
        fp = by_id[n["id"]]
        return (-fp["total_points"], -fp["first_choice_count"], n["created_at"])

    return sorted(finalists, key=key)[0]


# ---------------------------------------------------------------- clock-driven transitions

def evaluate_time_transitions():
    """Run after every clock advance: report OVERDUE cascade + visit NO_SHOW."""
    now = now_logical()

    # GranteeReport DUE -> OVERDUE
    for report in list(store.reports.values()):
        if report["status"] == "DUE":
            due = parse_iso(report["due_at"])
            if now > due:
                report["status"] = "OVERDUE"
                touch(report)
                award = store.awards.get(report["award_id"])
                if award:
                    nonprofit = store.nonprofits.get(award["nonprofit_id"])
                    if nonprofit and nonprofit["standing"] != "SUSPENDED":
                        nonprofit["standing"] = "SUSPENDED"
                        touch(nonprofit)
                        # cascade hop 2: reject in-flight nominations of this nonprofit
                        for nom in store.nominations.values():
                            if nom["nonprofit_id"] != nonprofit["id"]:
                                continue
                            if nom["status"] not in ("SUBMITTED", "VETTING", "NEEDS_INFO"):
                                continue
                            nom_cycle = store.cycles.get(nom["cycle_id"])
                            if nom_cycle and nom_cycle["phase"] in ("NOMINATION", "VETTING"):
                                nom["status"] = "REJECTED"
                                touch(nom)

    # SiteVisit SCHEDULED -> NO_SHOW when clock strictly past ends_at
    for visit in list(store.site_visits.values()):
        if visit["status"] == "SCHEDULED":
            ends = parse_iso(visit["ends_at"])
            if now > ends:
                visit["status"] = "NO_SHOW"
                touch(visit)


# ---------------------------------------------------------------- serializers

def public_circle(c):
    return dict(c)


def public_cycle(c):
    return dict(c)


def public_generic(e):
    return dict(e)
