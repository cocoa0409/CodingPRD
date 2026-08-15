"""Business logic: rate resolution, event tax determination, return aggregation,
deposit schedules, settlement waterfall, claim eligibility, bond requirement,
registrant rollup, audit holds, cascades, and the daily clock sweep."""
import math
from datetime import timedelta
from decimal import Decimal

from store import DB
from utiltime import (
    now_dt, now_iso, fmt_dt, rhu, rhu_div_1000, period_bounds,
    period_end_exclusive, prev_period, period_month_buckets, month_bucket_range,
    due_date_for_return, add_years_safe, months_ago, period_of_date,
)
from auth import touch, touch_if_changed, new_entity

# ------------------------------------------------------------------ constants
MILLICENTS_PER_CENT = 1000
PUNITIVE_RATE_NUM = 3   # 1.5 == 3/2 exactly
PUNITIVE_RATE_DEN = 2
MIN_DEPOSIT_FLOOR_CENTS = 10000
CLAIM_CAP_CENTS = 5000000
MIN_AGE_DAYS = 183
MAX_AGE_DAYS = 731
FLOOR_STANDARD_CENTS = 1000000
FLOOR_AGGRAVATED_CENTS = 2500000
STANDARD_WINDOW = 6
STANDARD_MULTIPLIER = 3
AGGRAVATED_WINDOW = 12
AGGRAVATED_MULTIPLIER = 5
RETENTION_YEARS = 7
BOND_DEFICIENCY_SUSPEND_DAYS = 30

HOLD_STATUSES = {"OPENED", "DOCUMENTS_REQUESTED", "UNDER_REVIEW"}
LIVE_CLAIM_STATUSES = {"SUBMITTED", "APPROVED", "APPLIED"}
INCLUDED_EVENT_STATUSES = {"RATED", "RETURNED", "ADJUSTED"}


# ===================================================================
# Rate schedule
# ===================================================================
def rate_status_for(effective_from, effective_to, at=None):
    at = at or now_dt()
    if effective_from > at:
        return "SCHEDULED"
    if effective_to is not None and at >= effective_to:
        return "RETIRED"
    return "ACTIVE"


def resolve_rate(jurisdiction_id, product_class_id, when):
    """Half-open window containment; status is NOT consulted."""
    for r in DB.tax_rates.values():
        if r["jurisdiction_id"] != jurisdiction_id or r["product_class_id"] != product_class_id:
            continue
        if r["_effective_from"] <= when and (r["_effective_to"] is None or when < r["_effective_to"]):
            return r
    return None


def any_rate_for_pair(jurisdiction_id, product_class_id):
    for r in DB.tax_rates.values():
        if r["jurisdiction_id"] == jurisdiction_id and r["product_class_id"] == product_class_id:
            return True
    return False


def rates_overlap(a_from, a_to, b_from, b_to):
    """Half-open [from, to) overlap test (adjacency allowed)."""
    if a_to is not None and a_to <= b_from:
        return False
    if b_to is not None and b_to <= a_from:
        return False
    return True


# ===================================================================
# Registrations / bonds
# ===================================================================
def recompute_bond_coverage(reg):
    total = sum(
        b["principal_amount_cents"]
        for b in DB.bonds.values()
        if b["registration_id"] == reg["id"] and b["status"] == "ACTIVE"
    )
    touch_if_changed(reg, {"bond_coverage_cents": total})
    return total


def _filed_original_returns(reg):
    """Original returns (never amendments) with filing_status == FILED,
    newest period first."""
    rows = [
        r for r in DB.returns.values()
        if r["registration_id"] == reg["id"]
        and r["amendment_of_id"] is None
        and r["filing_status"] == "FILED"
    ]
    rows.sort(key=lambda r: (period_bounds(r["period"], r["_frequency"])[0], r["_seq"]),
              reverse=True)
    return rows


def recompute_bond_requirement(reg):
    now = now_dt()
    horizon = months_ago(now, 12)
    aggravated = False
    for m in DB.movements.values():
        if (m["registration_id"] == reg["id"]
                and m["status"] in ("DEFAULTED", "PARTIAL_DEFAULT")
                and m.get("_defaulted_at") is not None
                and m["_defaulted_at"] >= horizon):
            aggravated = True
            break
    if not aggravated:
        for c in DB.claims.values():
            if (c["registration_id"] == reg["id"]
                    and c["status"] == "REVERSED"
                    and c.get("_reversed_at") is not None
                    and c["_reversed_at"] >= horizon):
                aggravated = True
                break

    filed = _filed_original_returns(reg)
    if aggravated:
        window, mult, floor, variant = (
            filed[:AGGRAVATED_WINDOW], AGGRAVATED_MULTIPLIER, FLOOR_AGGRAVATED_CENTS, "AGGRAVATED")
    else:
        window, mult, floor, variant = (
            filed[:STANDARD_WINDOW], STANDARD_MULTIPLIER, FLOOR_STANDARD_CENTS, "STANDARD")
    n = len(window)
    if n == 0:
        required = floor
    else:
        avg = rhu(Decimal(sum(r["taxable_tax_cents"] for r in window)) / Decimal(n))
        required = max(mult * avg, floor)
    touch_if_changed(reg, {"bond_required_cents": required, "requirement_variant": variant})
    return required


def refresh_deficiency(reg):
    """Flip ACTIVE <-> BOND_DEFICIENT based on coverage vs requirement."""
    if reg["status"] == "ACTIVE" and reg["bond_coverage_cents"] < reg["bond_required_cents"]:
        reg["status"] = "BOND_DEFICIENT"
        reg["_bond_deficient_since"] = now_dt()
        touch(reg)
    elif reg["status"] == "BOND_DEFICIENT" and reg["bond_coverage_cents"] >= reg["bond_required_cents"]:
        reg["status"] = "ACTIVE"
        reg["_bond_deficient_since"] = None
        touch(reg)


def check_registrant_recovery(registrant):
    """When no registration remains BOND_DEFICIENT the registrant returns to
    ACTIVE, and its SUSPENDED registrations with sufficient coverage reactivate."""
    regs = [r for r in DB.registrations.values() if r["registrant_id"] == registrant["id"]]
    if any(r["status"] == "BOND_DEFICIENT" for r in regs):
        return
    if registrant["status"] != "SUSPENDED":
        check_registrant_cancellation(registrant)
        return
    registrant["status"] = "ACTIVE"
    touch(registrant)
    for r in regs:
        if r["status"] == "SUSPENDED" and r["bond_coverage_cents"] >= r["bond_required_cents"]:
            r["status"] = "ACTIVE"
            r["_bond_deficient_since"] = None
            touch(r)


def check_registrant_cancellation(registrant):
    if registrant["status"] not in ("ACTIVE", "SUSPENDED"):
        return
    regs = [r for r in DB.registrations.values() if r["registrant_id"] == registrant["id"]]
    if not regs:
        return
    if all(r["status"] == "REVOKED" for r in regs) and registrant["aggregate_open_liability_cents"] == 0:
        registrant["status"] = "CANCELLED"
        touch(registrant)


# ===================================================================
# Returns: aggregation, rollup, deposit schedules
# ===================================================================
def return_frequency(ret):
    return ret.get("_frequency") or DB.jurisdictions[ret["jurisdiction_id"]]["return_frequency"]


def recompute_return(ret):
    included = [
        e for e in DB.events.values()
        if e.get("return_id") == ret["id"] and e["status"] in INCLUDED_EVENT_STATUSES
    ]
    gross = sum(e["gross_tax_cents"] for e in included)
    taxable = sum(e["tax_cents"] for e in included)
    touch_if_changed(ret, {
        "event_count": len(included),
        "gross_tax_cents": gross,
        "taxable_tax_cents": taxable,
        "exempted_cents": gross - taxable,
    })


def recompute_rollup(registrant_id):
    registrant = DB.registrants.get(registrant_id)
    if registrant is None:
        return
    reg_ids = {r["id"] for r in DB.registrations.values() if r["registrant_id"] == registrant_id}
    total = 0
    for r in DB.returns.values():
        if r["registration_id"] not in reg_ids:
            continue
        if r["filing_status"] in ("DRAFT", "SUBMITTED"):
            total += r["taxable_tax_cents"]
        elif r["filing_status"] == "FILED" and r["settlement_status"] == "AWAITING_PAYMENT":
            total += r["net_due_cents"]
    touch_if_changed(registrant, {"aggregate_open_liability_cents": total})


def _safe_harbor_amount(reg, jurisdiction, period):
    prior_period = prev_period(period, jurisdiction["return_frequency"])
    candidates = [
        r for r in DB.returns.values()
        if r["registration_id"] == reg["id"]
        and r["jurisdiction_id"] == jurisdiction["id"]
        and r["period"] == prior_period
        and r["filing_status"] == "FILED"
    ]
    if not candidates:
        return MIN_DEPOSIT_FLOOR_CENTS
    latest = max(candidates, key=lambda r: (r["amendment_sequence"], r["_seq"]))
    return rhu(Decimal(latest["taxable_tax_cents"]) * Decimal("0.5"))


def deposit_windows(jurisdiction, period):
    """Return list of dicts: window, due_dt, close_dt (exclusive end of window),
    win_start, win_end_exclusive."""
    freq = jurisdiction["return_frequency"]
    start, end = period_bounds(period, freq)
    out = []
    if jurisdiction["deposit_frequency"] == "SEMI_MONTHLY":
        y, m = start.year, start.month
        from utiltime import _add_months
        ny, nm = _add_months(y, m, 1)
        a_end = start.replace(day=16)
        b_end = start.replace(year=ny, month=nm, day=1)
        out.append({
            "window": "A",
            "win_start": start,
            "win_end": a_end,
            "due_dt": start.replace(day=25),
            "close_dt": a_end,
        })
        out.append({
            "window": "B",
            "win_start": a_end,
            "win_end": b_end,
            "due_dt": b_end.replace(day=10),
            "close_dt": b_end,
        })
    else:
        end_exclusive = period_end_exclusive(period, freq)
        out.append({
            "window": "M",
            "win_start": start,
            "win_end": end_exclusive,
            "due_dt": due_date_for_return(period, freq),
            "close_dt": end_exclusive,
        })
    return out


def create_deposit_schedule(ret):
    """Create the period's deposit rows when a return is created. Skipped for
    amendments and when rows already exist for (registration, jurisdiction, period)."""
    if ret["amendment_of_id"] is not None:
        return
    existing = [
        d for d in DB.deposits.values()
        if d["registration_id"] == ret["registration_id"]
        and d["jurisdiction_id"] == ret["jurisdiction_id"]
        and d["period"] == ret["period"]
    ]
    if existing:
        return
    reg = DB.registrations[ret["registration_id"]]
    jurisdiction = DB.jurisdictions[ret["jurisdiction_id"]]
    for w in deposit_windows(jurisdiction, ret["period"]):
        if reg["deposit_method"] == "SAFE_HARBOR":
            scheduled = _safe_harbor_amount(reg, jurisdiction, ret["period"])
        else:
            scheduled = 0
        dep = new_entity({
            "registration_id": ret["registration_id"],
            "jurisdiction_id": ret["jurisdiction_id"],
            "period": ret["period"],
            "window": w["window"],
            "scheduled_amount_cents": scheduled,
            "due_date": fmt_dt(w["due_dt"]),
            "paid_amount_cents": None,
            "paid_at": None,
            "penalty_cents": 0,
            "applied_amount_cents": 0,
            "applied_return_id": None,
            "status": "SCHEDULED",
            "_due_dt": w["due_dt"],
            "_win_start": w["win_start"],
            "_win_end": w["win_end"],
            "_close_dt": w["close_dt"],
        })
        DB.deposits[dep["id"]] = dep


def recompute_actual_deposits(registration_id, jurisdiction_id, period):
    """ACTUAL-method deposits of the period: scheduled = sum of tax_cents of the
    window's RATED/RETURNED/ADJUSTED events."""
    for d in DB.deposits.values():
        if (d["registration_id"] != registration_id
                or d["jurisdiction_id"] != jurisdiction_id
                or d["period"] != period
                or d["status"] not in ("SCHEDULED", "LATE")):
            continue
        reg = DB.registrations.get(registration_id)
        if reg is None or reg["deposit_method"] != "ACTUAL":
            continue
        total = sum(
            e["tax_cents"]
            for e in DB.events.values()
            if e["registration_id"] == registration_id
            and e["jurisdiction_id"] == jurisdiction_id
            and e["status"] in INCLUDED_EVENT_STATUSES
            and d["_win_start"] <= e["_event_dt"] < d["_win_end"]
        )
        touch_if_changed(d, {"scheduled_amount_cents": total})


def latest_non_superseded_return(registration_id, jurisdiction_id, period):
    rows = [
        r for r in DB.returns.values()
        if r["registration_id"] == registration_id
        and r["jurisdiction_id"] == jurisdiction_id
        and r["period"] == period
        and r["filing_status"] != "SUPERSEDED"
    ]
    if not rows:
        return None
    return max(rows, key=lambda r: (r["amendment_sequence"], r["_seq"]))


def open_amendment_of(return_id):
    for r in DB.returns.values():
        if (r["amendment_of_id"] == return_id
                and r["filing_status"] in ("DRAFT", "SUBMITTED")):
            return r
    return None


def period_open_target(registration_id, jurisdiction_id, period):
    """The return that accepts newly rated events for the period:
    an open (DRAFT/SUBMITTED) non-superseded return (deepest amendment first),
    or None if the period is locked / no return exists."""
    latest = latest_non_superseded_return(registration_id, jurisdiction_id, period)
    if latest is None:
        return None, True
    if latest["filing_status"] in ("DRAFT", "SUBMITTED"):
        return latest, True
    # latest is FILED: an open amendment makes the period open
    amend = open_amendment_of(latest["id"])
    if amend is not None:
        return amend, True
    return latest, False


def get_or_create_open_return(registration_id, jurisdiction_id, period):
    """Auto-include target for newly rated events. Creates a DRAFT return with
    deposit schedule when none exists. Returns (return, locked)."""
    latest = latest_non_superseded_return(registration_id, jurisdiction_id, period)
    if latest is None:
        ret = create_return_record(registration_id, jurisdiction_id, period)
        return ret, False
    if latest["filing_status"] in ("DRAFT", "SUBMITTED"):
        return latest, False
    amend = open_amendment_of(latest["id"])
    if amend is not None:
        return amend, False
    return latest, True


def create_return_record(registration_id, jurisdiction_id, period, amendment_of=None,
                         amendment_sequence=0):
    jurisdiction = DB.jurisdictions[jurisdiction_id]
    due = due_date_for_return(period, jurisdiction["return_frequency"])
    ret = new_entity({
        "registration_id": registration_id,
        "jurisdiction_id": jurisdiction_id,
        "period": period,
        "amendment_of_id": amendment_of,
        "amendment_sequence": amendment_sequence,
        "prepared_by_user_id": None,
        "filed_by_user_id": None,
        "due_date": fmt_dt(due),
        "filed_at": None,
        "event_count": 0,
        "gross_tax_cents": 0,
        "exempted_cents": 0,
        "taxable_tax_cents": 0,
        "credits_cents": 0,
        "deposits_applied_cents": 0,
        "penalty_cents": 0,
        "net_due_cents": 0,
        "pinned_rate_snapshot": [],
        "filing_status": "DRAFT",
        "settlement_status": "UNFILED",
        "_frequency": jurisdiction["return_frequency"],
        "_due_dt": due,
    })
    DB.returns[ret["id"]] = ret
    create_deposit_schedule(ret)
    return ret


# ===================================================================
# Event tax determination
# ===================================================================
def compute_event_tax(event):
    """STANDARD determination: resolve the rate window for the event's own
    class; gross = round_half_up(qty * rate / 1000); tax = 0 when exempt or
    in-bond, else gross."""
    rate = resolve_rate(event["jurisdiction_id"], event["product_class_id"], event["_event_dt"])
    if rate is None:
        return None
    gross = rhu_div_1000(event["quantity_units"] * rate["rate_millicents_per_unit"])
    if event.get("bonded_movement_id") or event.get("exemption_certificate_id"):
        tax = 0
    else:
        tax = gross
    return rate, gross, tax


def punitive_rate_for(jurisdiction_id, when):
    """DEFAULT_ASSESSMENT: round_half_up(1.5 * max rate) over all rates of the
    jurisdiction whose window contains `when` (any class); if none contain it,
    max over all rates of the jurisdiction."""
    containing = [
        r for r in DB.tax_rates.values()
        if r["jurisdiction_id"] == jurisdiction_id
        and r["_effective_from"] <= when
        and (r["_effective_to"] is None or when < r["_effective_to"])
    ]
    pool = containing or [r for r in DB.tax_rates.values() if r["jurisdiction_id"] == jurisdiction_id]
    if not pool:
        return None, 0
    top = max(pool, key=lambda r: r["rate_millicents_per_unit"])
    punitive = rhu(Decimal(top["rate_millicents_per_unit"]) * Decimal(3) / Decimal(2))
    return top, punitive


# ===================================================================
# Settlement (filing) and post-filing settlement updates
# ===================================================================
def _chain_ids(ret):
    """All return ids in the amendment chain containing `ret`."""
    root = ret
    while root["amendment_of_id"] is not None:
        root = DB.returns[root["amendment_of_id"]]
    ids = set()
    frontier = [root["id"]]
    while frontier:
        rid = frontier.pop()
        if rid in ids:
            continue
        ids.add(rid)
        frontier.extend(
            r["id"] for r in DB.returns.values() if r["amendment_of_id"] == rid
        )
    return ids


def chain_credits(ret):
    ids = _chain_ids(ret)
    total = 0
    for c in DB.claims.values():
        if c["return_id"] in ids and c["status"] in ("APPLIED", "REVERSED"):
            total += c["applied_cents"] - c["reversed_cents"]
    return total


def _apply_settlement(ret, registrant):
    """Recompute net_due/settlement for a FILED return, with overpayment
    accounting on OVERPAID transitions."""
    if ret["filing_status"] != "FILED":
        return
    old_status = ret["settlement_status"]
    old_net = ret["net_due_cents"]
    new_net = (ret["taxable_tax_cents"] - ret["credits_cents"]
               - ret["deposits_applied_cents"] + ret["penalty_cents"])
    new_status = ("AWAITING_PAYMENT" if new_net > 0
                  else "SETTLED" if new_net == 0 else "OVERPAID")
    overpayment = registrant["overpayment_balance_cents"]
    if old_status == "OVERPAID":
        overpayment -= -old_net
    if new_status == "OVERPAID":
        overpayment += -new_net
    touch_if_changed(registrant, {"overpayment_balance_cents": overpayment})
    ret["net_due_cents"] = new_net
    ret["settlement_status"] = new_status
    touch(ret)


def late_deposit_penalty(scheduled_amount_cents, due_dt, paid_dt):
    days_late = (paid_dt.date() - due_dt.date()).days
    if days_late <= 0:
        return 0
    base = scheduled_amount_cents
    if days_late <= 5:
        return rhu(Decimal(base) * Decimal("0.02"))
    if days_late <= 15:
        return rhu(Decimal(base) * Decimal("0.05"))
    return (rhu(Decimal(base) * Decimal("0.10"))
            + rhu(Decimal(base) * Decimal("0.0005") * Decimal(days_late)))


def file_return_settlement(ret, registrant):
    """Pinned order: (1) taxable_tax, (2) credits, (3) deposit waterfall,
    (4) penalties, (5) net_due."""
    # (1) taxable_tax_cents is the current aggregate — already maintained.
    # (2) credits carried on the chain
    ret["credits_cents"] = chain_credits(ret)

    # (3) deposit waterfall
    carried = 0
    if ret["amendment_of_id"] is not None:
        parent = DB.returns[ret["amendment_of_id"]]
        carried = parent["deposits_applied_cents"]
    eligible = [
        d for d in DB.deposits.values()
        if d["registration_id"] == ret["registration_id"]
        and d["jurisdiction_id"] == ret["jurisdiction_id"]
        and d["period"] == ret["period"]
        and d["status"] == "PAID"
    ]
    eligible.sort(key=lambda d: (d["_due_dt"], d["created_at"], d["_seq"]))
    remaining_need = ret["taxable_tax_cents"] - ret["credits_cents"]
    applied_total = carried
    for d in eligible:
        take = min(d["paid_amount_cents"], remaining_need) if remaining_need > 0 else 0
        excess = d["paid_amount_cents"] - take
        if excess > 0:
            touch_if_changed(registrant, {
                "overpayment_balance_cents": registrant["overpayment_balance_cents"] + excess})
        d["applied_amount_cents"] = take
        d["applied_return_id"] = ret["id"]
        d["status"] = "APPLIED"
        touch(d)
        remaining_need -= take
        applied_total += take
    ret["deposits_applied_cents"] = applied_total

    # (4) penalties
    underpayment = 0
    taxable = ret["taxable_tax_cents"]
    if taxable > 0:
        safe_harbor = math.ceil(Decimal("0.9") * Decimal(taxable))
        if ret["deposits_applied_cents"] < safe_harbor:
            underpayment = rhu(Decimal("0.10")
                               * Decimal(taxable - ret["deposits_applied_cents"]))
    late = 0
    filed_dt = now_dt()
    if filed_dt.date() > ret["_due_dt"].date():
        days_late = (filed_dt.date() - ret["_due_dt"].date()).days
        months_started = (days_late + 29) // 30
        monthly = rhu(Decimal("0.05") * Decimal(taxable))
        cap = rhu(Decimal("0.25") * Decimal(taxable))
        late = min(monthly * months_started, cap)
    ret["penalty_cents"] = underpayment + late

    # (5) net due + settlement
    ret["filing_status"] = "FILED"
    ret["filed_at"] = now_iso()
    ret["_filed_dt"] = now_dt()
    _apply_settlement(ret, registrant)  # bumps version once
    return ret


def pin_rate_snapshot(ret):
    included = [
        e for e in DB.events.values()
        if e.get("return_id") == ret["id"] and e["status"] in INCLUDED_EVENT_STATUSES
    ]
    included.sort(key=lambda e: (e["_event_dt"], e["created_at"], e["_seq"]))
    snapshot = []
    seen = set()
    for e in included:
        pc = e["product_class_id"]
        if pc in seen:
            continue
        seen.add(pc)
        snapshot.append({
            "product_class_id": pc,
            "tax_rate_id": e.get("_tax_rate_id"),
            "rate_millicents_per_unit": e.get("_rate_millicents_used"),
        })
    ret["pinned_rate_snapshot"] = snapshot


# ===================================================================
# Audit holds / retention
# ===================================================================
def audit_hold_blocks(registration_id, jurisdiction_id, period, frequency):
    buckets = set(period_month_buckets(period, frequency))
    for case in DB.audit_cases.values():
        if case["registration_id"] != registration_id:
            continue
        if case["jurisdiction_id"] != jurisdiction_id:
            continue
        if case["status"] not in HOLD_STATUSES:
            continue
        covered = set(month_bucket_range(case["period_start"], case["period_end"]))
        if buckets & covered:
            return True
    return False


# ===================================================================
# Default-assessment cascade (bonded movement default)
# ===================================================================
def run_default_cascade(movement, defaulted_qty, default_dt):
    """3-link cascade: create DEFAULT_ASSESSMENT event (RATED), auto-include
    into the period return, recompute ACTUAL deposits + bond requirement."""
    reg = DB.registrations[movement["registration_id"]]
    jurisdiction = DB.jurisdictions[reg["jurisdiction_id"]]
    rate_row, punitive = punitive_rate_for(jurisdiction["id"], default_dt)
    qty = defaulted_qty
    gross = rhu_div_1000(qty * punitive)
    period = period_of_date(jurisdiction["return_frequency"], default_dt)
    ev = new_entity({
        "registration_id": reg["id"],
        "jurisdiction_id": jurisdiction["id"],
        "product_class_id": movement["product_class_id"],
        "event_date": fmt_dt(default_dt),
        "quantity_units": qty,
        "customer_reference": None,
        "is_export": False,
        "period": period,
        "determination": "DEFAULT_ASSESSMENT",
        "exemption_certificate_id": None,
        "bonded_movement_id": movement["id"],
        "gross_tax_cents": gross,
        "tax_cents": gross,
        "return_id": None,
        "status": "RATED",
        "_event_dt": default_dt,
        "_tax_rate_id": rate_row["id"] if rate_row else None,
        "_rate_millicents_used": punitive,
    })
    DB.events[ev["id"]] = ev

    # link 2: auto-include into the period return (created if missing); if the
    # period is locked the event stays RATED with return_id null
    target, locked = get_or_create_open_return(reg["id"], jurisdiction["id"], period)
    if not locked and target is not None:
        ev["return_id"] = target["id"]
        touch(ev)
        recompute_return(target)

    # link 3: ACTUAL deposits recomputed; bond requirement recomputed
    recompute_actual_deposits(reg["id"], jurisdiction["id"], period)
    recompute_bond_requirement(reg)
    refresh_deficiency(reg)
    recompute_rollup(reg["registrant_id"])
    check_registrant_recovery(DB.registrants[reg["registrant_id"]])
    check_registrant_cancellation(DB.registrants[reg["registrant_id"]])
    return ev


# ===================================================================
# Daily sweep (logical clock advance)
# ===================================================================
def run_sweep():
    now = now_dt()

    # Tax rates: derive informational status from window vs clock.
    for r in DB.tax_rates.values():
        if r["status"] == "SUPERSEDED":
            continue
        new_status = rate_status_for(r["_effective_from"], r["_effective_to"], now)
        if new_status != r["status"]:
            r["status"] = new_status
            touch(r)

    # Exemption certificates: ACTIVE -> EXPIRED once now passes valid_to.
    for c in DB.certificates.values():
        if c["status"] == "ACTIVE" and now > c["_valid_to"]:
            c["status"] = "EXPIRED"
            touch(c)

    # Bonds: ACTIVE -> EXPIRED once now passes effective_to; coverage recompute.
    affected_regs = set()
    for b in DB.bonds.values():
        if b["status"] == "ACTIVE" and now > b["_effective_to"]:
            b["status"] = "EXPIRED"
            touch(b)
            affected_regs.add(b["registration_id"])
    for reg_id in affected_regs:
        reg = DB.registrations.get(reg_id)
        if reg is None:
            continue
        recompute_bond_coverage(reg)
        recompute_bond_requirement(reg)
        refresh_deficiency(reg)

    # Bonded movements: IN_TRANSIT past deadline -> DEFAULTED with cascade.
    for m in list(DB.movements.values()):
        if (m["status"] == "IN_TRANSIT" and m.get("_dispatched_dt") is not None
                and now > m["_dispatched_dt"] + timedelta(days=m["transit_deadline_days"])):
            m["status"] = "DEFAULTED"
            m["defaulted_quantity_units"] = m["quantity_units"]
            m["_defaulted_at"] = now
            touch(m)
            run_default_cascade(m, m["quantity_units"], now)

    # Deposits: SCHEDULED past due -> LATE.
    for d in DB.deposits.values():
        if d["status"] == "SCHEDULED" and now > d["_due_dt"]:
            d["status"] = "LATE"
            touch(d)

    # ACTUAL-method deposit window-close computation.
    for d in DB.deposits.values():
        if d["status"] in ("SCHEDULED", "LATE") and now >= d["_close_dt"]:
            reg = DB.registrations.get(d["registration_id"])
            if reg is None or reg["deposit_method"] != "ACTUAL":
                continue
            total = sum(
                e["tax_cents"]
                for e in DB.events.values()
                if e["registration_id"] == d["registration_id"]
                and e["jurisdiction_id"] == d["jurisdiction_id"]
                and e["status"] in INCLUDED_EVENT_STATUSES
                and d["_win_start"] <= e["_event_dt"] < d["_win_end"]
            )
            touch_if_changed(d, {"scheduled_amount_cents": total})

    # Registrant suspension: registration BOND_DEFICIENT > 30 consecutive days.
    for registrant in DB.registrants.values():
        if registrant["status"] != "ACTIVE":
            continue
        regs = [r for r in DB.registrations.values() if r["registrant_id"] == registrant["id"]]
        prolonged = any(
            r["status"] == "BOND_DEFICIENT"
            and r.get("_bond_deficient_since") is not None
            and (now - r["_bond_deficient_since"]) > timedelta(days=BOND_DEFICIENCY_SUSPEND_DAYS)
            for r in regs
        )
        if prolonged:
            registrant["status"] = "SUSPENDED"
            touch(registrant)
            for r in regs:
                if r["status"] == "ACTIVE":
                    r["status"] = "SUSPENDED"
                    touch(r)

    # Registrant recovery / cancellation checks.
    for registrant in DB.registrants.values():
        check_registrant_recovery(registrant)
        check_registrant_cancellation(registrant)
