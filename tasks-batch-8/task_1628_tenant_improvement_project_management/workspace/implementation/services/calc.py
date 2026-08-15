"""Calculation rules per scaffold §1.3. Each function implements one named calc."""

from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

from db import store
from services.util import parse_iso8601, to_iso_z, round_half_up_cents


# ---------------------------------------------------------------------------
# change_order_markup
# ---------------------------------------------------------------------------
MARKUP_PCT = Decimal("0.10")


def compute_change_order_markup(lines):
    """Per-line round_half_up(amount * 0.10), then sum. Returns (total_cost, markup, total_with_markup)."""
    total_cost = 0
    markup = 0
    for line in lines:
        amt = line["amount_cents"]
        total_cost += amt
        line_markup = round_half_up_cents(Decimal(amt) * MARKUP_PCT)
        markup += line_markup
    return total_cost, markup, total_cost + markup


# ---------------------------------------------------------------------------
# change_order_overage_share
# ---------------------------------------------------------------------------
def compute_overage_share(project, this_co):
    """Chronological headroom sweep. Returns tenant_overage_share_cents."""
    headroom = project["allowance_total_cents"] - project["base_contract_cents"]

    # Collect other APPROVED COs, sorted by approved_at ASC, created_at ASC
    others = [
        co for co in store.change_orders.values()
        if co["project_id"] == project["id"]
        and co["status"] == "APPROVED"
        and co["id"] != this_co["id"]
    ]
    others.sort(key=lambda co: (co.get("approved_at") or "", co["created_at"]))

    cum_before = sum(co["total_with_markup_cents"] for co in others)
    cum_after = cum_before + this_co["total_with_markup_cents"]
    return max(0, cum_after - headroom) - max(0, cum_before - headroom)


# ---------------------------------------------------------------------------
# allowance_consumption
# ---------------------------------------------------------------------------
def recompute_allowance(project):
    """Recompute consumed / provisional / remaining from the project's draws."""
    draws = [
        d for d in store.disbursement_requests.values()
        if d["project_id"] == project["id"]
    ]
    consumed = sum(
        d["approved_amount_cents"]
        for d in draws
        if d["status"] in ("APPROVED", "PAID")
    )
    provisional = consumed + sum(
        d["requested_amount_cents"]
        for d in draws
        if d["status"] in ("SUBMITTED", "ON_HOLD")
    )
    project["allowance_consumed_cents"] = consumed
    project["provisional_allowance_consumed_cents"] = provisional
    project["allowance_remaining_cents"] = project["allowance_total_cents"] - consumed


def recompute_total_cost(project):
    """total_cost_cents = base_contract_cents + sum(APPROVED CO total_with_markup)."""
    approved_cos = [
        co for co in store.change_orders.values()
        if co["project_id"] == project["id"] and co["status"] == "APPROVED"
    ]
    project["total_cost_cents"] = project["base_contract_cents"] + sum(
        co["total_with_markup_cents"] for co in approved_cos
    )
    project["overage_cents"] = max(
        0, project["total_cost_cents"] - project["allowance_total_cents"]
    )


def recompute_retainage(project):
    """Recompute project-level retainage_held_cents from draws."""
    draws = [
        d for d in store.disbursement_requests.values()
        if d["project_id"] == project["id"]
    ]
    # Sum of retainage held across non-VOIDED approved/paid draws
    held = sum(
        d["retainage_held_cents"]
        for d in draws
        if d["status"] in ("APPROVED", "PAID")
    )
    project["retainage_held_cents"] = held


# ---------------------------------------------------------------------------
# project_posture
# ---------------------------------------------------------------------------
def recompute_posture(project):
    """Derive posture and run cascade side-effects on flip."""
    from services.util import bump_version

    draws = [
        d for d in store.disbursement_requests.values()
        if d["project_id"] == project["id"]
    ]

    old_posture = project["posture"]
    exhausted = (
        project["allowance_total_cents"] > 0
        and project["allowance_consumed_cents"] >= project["allowance_total_cents"]
    )

    if exhausted:
        new_posture = "ALLOWANCE_EXHAUSTED"
    elif old_posture == "ALLOWANCE_EXHAUSTED":
        # PRD 3.6: leaving ALLOWANCE_EXHAUSTED back to OPEN returns every
        # ON_HOLD draw to SUBMITTED. ON_HOLD draws exist only as products of
        # the exhaustion cascade, so once exhaustion ends the release cascade
        # runs and the posture settles at OPEN.
        new_posture = "OPEN"
    elif any(d["status"] == "ON_HOLD" for d in draws):
        new_posture = "ON_HOLD"
    else:
        new_posture = "OPEN"

    project["posture"] = new_posture

    # Cascade on flip INTO exhausted
    if new_posture == "ALLOWANCE_EXHAUSTED" and old_posture != "ALLOWANCE_EXHAUSTED":
        for d in draws:
            if d["status"] == "SUBMITTED":
                d["status"] = "ON_HOLD"
                bump_version(d)

    # Cascade on flip OUT of exhausted back to OPEN
    if old_posture == "ALLOWANCE_EXHAUSTED" and new_posture == "OPEN":
        for d in draws:
            if d["status"] == "ON_HOLD":
                d["status"] = "SUBMITTED"
                bump_version(d)


# ---------------------------------------------------------------------------
# disbursement_retainage
# ---------------------------------------------------------------------------
RETAINAGE_PCT_EARLY = Decimal("0.10")
RETAINAGE_PCT_LATE = Decimal("0.05")
RETAINAGE_TIER_THRESHOLD_PCT = Decimal("0.50")


def compute_retainage(draw, project):
    """Set retainage_held_cents and net_payment_cents on the draw."""
    if draw["is_final_draw"]:
        draw["retainage_held_cents"] = 0
        draw["net_payment_cents"] = draw["approved_amount_cents"]
        return

    cum_before = sum(
        d["approved_amount_cents"]
        for d in store.disbursement_requests.values()
        if d["project_id"] == project["id"]
        and d["status"] in ("APPROVED", "PAID")
        and d["id"] != draw["id"]
    )
    threshold = RETAINAGE_TIER_THRESHOLD_PCT * Decimal(project["allowance_total_cents"])
    pct = RETAINAGE_PCT_EARLY if Decimal(cum_before) < threshold else RETAINAGE_PCT_LATE
    retainage = round_half_up_cents(Decimal(draw["approved_amount_cents"]) * pct)
    draw["retainage_held_cents"] = retainage
    draw["net_payment_cents"] = draw["approved_amount_cents"] - retainage


# ---------------------------------------------------------------------------
# rent_abatement
# ---------------------------------------------------------------------------
DAYS_PER_YEAR = Decimal("365")


def compute_rent_abatement(lease, substantial_completion_date_str):
    """Set lease.rent_abatement_credit_cents and actual_rent_commencement_date."""
    scheduled = parse_iso8601(lease["scheduled_rent_commencement_date"])
    sub_date = parse_iso8601(substantial_completion_date_str)
    daily_rent = round_half_up_cents(
        Decimal(lease["base_rent_annual_cents"]) / DAYS_PER_YEAR
    )

    if sub_date <= scheduled:
        delay_days = 0
    else:
        # period = (scheduled, sub_date] — exclusive start, inclusive end
        # count dates from scheduled+1day through sub_date inclusive
        period_start = scheduled.date() + timedelta(days=1)
        period_end = sub_date.date()
        if lease["abatement_basis"] == "CALENDAR":
            delay_days = (period_end - period_start).days + 1
        else:  # BUSINESS
            delay_days = 0
            d = period_start
            while d <= period_end:
                if d.weekday() < 5:  # Mon=0..Fri=4
                    delay_days += 1
                d += timedelta(days=1)

    responsibility = lease["delay_responsibility"]
    if responsibility == "LANDLORD":
        lease["rent_abatement_credit_cents"] = delay_days * daily_rent
        lease["actual_rent_commencement_date"] = substantial_completion_date_str
    elif responsibility == "TENANT":
        lease["rent_abatement_credit_cents"] = 0
        lease["actual_rent_commencement_date"] = lease["scheduled_rent_commencement_date"]
    else:  # NONE
        lease["rent_abatement_credit_cents"] = 0
        lease["actual_rent_commencement_date"] = lease["scheduled_rent_commencement_date"]


# ---------------------------------------------------------------------------
# property_construction_capacity
# ---------------------------------------------------------------------------
def check_property_capacity(project, requested_start_str, requested_end_str):
    """Returns True if allowed, False if capacity exceeded."""
    lease = store.leases[project["lease_id"]]
    space = store.lease_spaces[lease["space_id"]]
    prop = store.properties[space["property_id"]]
    max_concurrent = prop["max_concurrent_construction_projects"]

    req_start = parse_iso8601(requested_start_str)
    req_end = parse_iso8601(requested_end_str)

    conflicts = 0
    for p in store.ti_projects.values():
        if p["id"] == project["id"]:
            continue
        if p["status"] != "CONSTRUCTION":
            continue
        p_lease = store.leases.get(p["lease_id"])
        if not p_lease:
            continue
        p_space = store.lease_spaces.get(p_lease["space_id"])
        if not p_space:
            continue
        if p_space["property_id"] != prop["id"]:
            continue
        # Closed-interval intersection
        s = parse_iso8601(p["construction_start_date"])
        e = parse_iso8601(p["construction_end_date"])
        if s <= req_end and req_start <= e:
            conflicts += 1

    return conflicts < max_concurrent


# ---------------------------------------------------------------------------
# milestone_window_overlap
# ---------------------------------------------------------------------------
def check_milestone_overlap(engagement_id, new_start_str, new_end_str, exclude_id=None):
    """Half-open [start, end) overlap check. Returns True if NO overlap (allowed)."""
    ns = parse_iso8601(new_start_str)
    ne = parse_iso8601(new_end_str)
    for m in store.schedule_milestones.values():
        if m["engagement_id"] != engagement_id:
            continue
        if exclude_id and m["id"] == exclude_id:
            continue
        if m["status"] not in ("PLANNED", "CONFIRMED"):
            continue
        ms = parse_iso8601(m["window_start"])
        me = parse_iso8601(m["window_end"])
        # Overlap iff existing.start < new.end AND new.start < existing.end
        if ms < ne and ns < me:
            return False
    return True


# ---------------------------------------------------------------------------
# invoice_due_date
# ---------------------------------------------------------------------------
INVOICE_DUE_DAYS = 30


def compute_invoice_due_date(effective_issue_date_str):
    """Return ISO date string = effective_issue_date + 30 days."""
    dt = parse_iso8601(effective_issue_date_str)
    due = dt + timedelta(days=INVOICE_DUE_DAYS)
    return to_iso_z(due)
