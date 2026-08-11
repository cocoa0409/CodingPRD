"""Domain services: calculations, posture derivation, lazy expiry, cascades, rollover sweep."""
from datetime import timedelta
from decimal import Decimal

import db
from util import new_base, touch, round_half_up

FEES = {"BASIC": 2999, "PLUS": 4999, "PREMIUM": 7999}
TIER_BONUS_BPS = {"BASIC": 0, "PLUS": 250, "PREMIUM": 500}
EDU_BONUS_BPS = 200
SHARE_CAP_BPS = 6000
MOISTURE_LIMIT_PCT = Decimal("18.6")
MOISTURE_PENALTY_FACTOR = Decimal("2.0")
OVERWINTER_CREDIT_PER_HIVE_CENTS = 4000
CANCELLATION_FEE_CENTS = 7500


# ---------------------------------------------------------------------------
# Generic lookups
# ---------------------------------------------------------------------------

def sorted_all(coll):
    return sorted(coll.values(), key=lambda e: (e["created_at"], e["_seq"]))


def open_season():
    for s in db.seasons.values():
        if s["status"] == "OPEN":
            return s
    return None


def host_sites(host_id):
    return [s for s in db.sites.values() if s["host_id"] == host_id]


def host_hives(host_id):
    site_ids = {s["id"] for s in host_sites(host_id)}
    return [h for h in db.hives.values() if h["site_id"] in site_ids]


def host_subscriptions(host_id):
    return [s for s in db.subscriptions.values() if s["host_id"] == host_id]


def active_subscription(host_id):
    subs = [s for s in host_subscriptions(host_id) if s["status"] != "CANCELLED"]
    return subs[0] if subs else None


def completed_enrollment(host_id, course_code, before=None):
    for e in db.enrollments.values():
        if e["host_id"] == host_id and e["course_code"] == course_code and e["status"] == "COMPLETED":
            if before is None or (e["completed_at"] is not None and e["completed_at"] <= before):
                return True
    return False


def host_balance_cents(host_id):
    total = 0
    for sub in host_subscriptions(host_id):
        for inv in db.invoices.values():
            if inv["subscription_id"] == sub["id"] and inv["status"] in ("OPEN", "OVERDUE"):
                total += inv["total_cents"]
    return total


def waiver_current(host):
    signed = host.get("waiver_signed_at")
    return signed is not None and db.now() <= signed + timedelta(days=365)


def site_occupancy(site_id):
    return sum(1 for h in db.hives.values()
               if h["site_id"] == site_id and h["lifecycle_status"] in ("ACTIVE", "QUARANTINED"))


def effective_capacity(site):
    cap = site["base_capacity_hives"]
    sub = active_subscription(site["host_id"])
    if sub is not None and sub["plan"] == "PREMIUM":
        cap += 1
    if completed_enrollment(site["host_id"], "ADV-201"):
        cap += 1
    return cap


# ---------------------------------------------------------------------------
# Lazy expiry (PRD §2.5)
# ---------------------------------------------------------------------------

def lazy_expire_agreement(ag):
    if ag["status"] in ("ACTIVE", "AMENDMENT_PENDING") and db.now() > ag["term_end_date"]:
        ag["status"] = "EXPIRED"
        ag["pending_host_share_base_bps"] = None
        touch(ag)


def lazy_expire_swarm(ev):
    if ev["status"] in ("REPORTED", "DISPATCHED") and db.now() > ev["reported_at"] + timedelta(hours=72):
        ev["status"] = "EXPIRED"
        touch(ev)


# ---------------------------------------------------------------------------
# Posture derivation (calculations.hive_posture_derivation)
# ---------------------------------------------------------------------------

def _posture_ladder(insp):
    if insp["disease_flag"]:
        return "QUARANTINED"
    m = insp["mite_load_per_100"]
    if m >= Decimal("9.00"):
        return "QUARANTINED"
    if m >= Decimal("3.00"):
        return "TREATMENT_REQUIRED"
    if m >= Decimal("2.00"):
        return "WATCH"
    if insp["brood_score"] < 6 or insp["stores_kg"] < Decimal("8"):
        return "WATCH"
    if insp["queen_seen"] and insp["brood_score"] >= 8 and m < Decimal("1.00"):
        return "THRIVING"
    return "STABLE"


def _candidate_inspections(hive_id, statuses):
    cands = [i for i in db.inspections.values()
             if i["hive_id"] == hive_id and i["status"] in statuses]
    cands.sort(key=lambda i: (i["inspected_at"], i["created_at"], i["_seq"]), reverse=True)
    return cands


def compute_posture(hive_id, authoritative=True):
    statuses = ("VERIFIED",) if authoritative else ("VERIFIED", "SUBMITTED")
    cands = _candidate_inspections(hive_id, statuses)
    if not cands:
        return "STABLE"
    return _posture_ladder(cands[0])


def refresh_hive_postures(hive):
    hive["posture"] = compute_posture(hive["id"], authoritative=True)
    hive["provisional_posture"] = compute_posture(hive["id"], authoritative=False)


def latest_verified_inspection(hive_id):
    cands = _candidate_inspections(hive_id, ("VERIFIED",))
    return cands[0] if cands else None


# ---------------------------------------------------------------------------
# Calculations: mite load, harvest net, honey share, pool/reserve
# ---------------------------------------------------------------------------

def compute_mite_load(mites_counted, bees_sampled):
    return round_half_up(Decimal(mites_counted) / Decimal(bees_sampled) * Decimal(100), 2)


def compute_net_kg(gross_kg, moisture_pct):
    excess = moisture_pct - MOISTURE_LIMIT_PCT
    if excess < 0:
        excess = Decimal("0")
    penalty = gross_kg * (excess / Decimal(100)) * MOISTURE_PENALTY_FACTOR
    return round_half_up(gross_kg - penalty, 3)


def _share_inputs(host_id, agreement, at_close=None):
    """(base_bps, tier_bonus, edu_bonus). at_close pins plan/enrollment reads for the final variant."""
    base = agreement["host_share_base_bps"]
    sub = active_subscription(host_id)
    tier = TIER_BONUS_BPS[sub["plan"]] if sub is not None else 0
    edu = EDU_BONUS_BPS if completed_enrollment(host_id, "HOST-101", before=at_close) else 0
    return base, tier, edu


def find_allocation(season_id, hive_id):
    for a in db.allocations.values():
        if a["season_id"] == season_id and a["hive_id"] == hive_id:
            return a
    return None


def allocation_harvests(alloc, statuses):
    return [h for h in db.harvests.values()
            if h["hive_id"] == alloc["hive_id"]
            and h.get("_season_id") == alloc["season_id"]
            and h["status"] in statuses]


def recompute_allocation_projected(alloc):
    hive = db.hives.get(alloc["hive_id"])
    if hive is None:
        return
    agreement = db.agreements.get(hive["agreement_id"])
    site = db.sites.get(hive["site_id"])
    host_id = site["host_id"] if site else None
    included = allocation_harvests(alloc, ("RECORDED", "APPROVED"))
    pool = sum((h["net_kg"] for h in included), Decimal("0"))
    if agreement is not None and host_id is not None:
        base, tier, edu = _share_inputs(host_id, agreement)
    else:
        base, tier, edu = 0, 0, 0
    eff = min(base + tier + edu, SHARE_CAP_BPS)
    host_kg = sum((round_half_up(h["net_kg"] * eff / Decimal(10000), 3) for h in included), Decimal("0"))
    alloc["projected_pool_net_kg"] = pool
    alloc["projected_host_kg"] = host_kg
    touch(alloc)


def finalize_allocation(alloc, at_time):
    """Final variant + season pool/reserve waterfall (calculations.season_pool_and_reserve)."""
    hive = db.hives.get(alloc["hive_id"])
    agreement = db.agreements.get(hive["agreement_id"]) if hive else None
    site = db.sites.get(hive["site_id"]) if hive else None
    host_id = site["host_id"] if site else None
    included = allocation_harvests(alloc, ("APPROVED",))
    # (1) pool
    pool = sum((h["net_kg"] for h in included), Decimal("0"))
    # (2) host share — inputs pinned at close
    if agreement is not None and host_id is not None:
        base, tier, edu = _share_inputs(host_id, agreement, at_close=at_time)
    else:
        base, tier, edu = 0, 0, 0
    eff = min(base + tier + edu, SHARE_CAP_BPS)
    host_kg = sum((round_half_up(h["net_kg"] * eff / Decimal(10000), 3) for h in included), Decimal("0"))
    # (3) edu bonus mass
    edu_kg = round_half_up(pool * Decimal(200) / Decimal(10000), 3) if edu else Decimal("0")
    # (4) reserve percentage by pool size
    pct = Decimal("0.06") if pool >= Decimal("100") else Decimal("0.03")
    # (5) reserve
    reserve = round_half_up(pool * pct, 3) + edu_kg
    # (6) operator remainder
    operator = pool - host_kg - reserve
    alloc["pool_net_kg"] = pool
    alloc["effective_bps"] = eff
    alloc["host_kg"] = host_kg
    alloc["reserve_kg"] = reserve
    alloc["operator_kg"] = operator
    alloc["edu_bonus_kg"] = edu_kg
    alloc["status"] = "FINALIZED"
    alloc["finalized_at"] = at_time
    touch(alloc)


# ---------------------------------------------------------------------------
# Inspection verify cascades (quarantine in/out)
# ---------------------------------------------------------------------------

def apply_verify_cascade(hive):
    refresh_hive_postures(hive)
    latest = latest_verified_inspection(hive["id"])
    hive["last_verified_inspection_at"] = latest["inspected_at"] if latest else None
    if hive["posture"] == "QUARANTINED" and hive["lifecycle_status"] == "ACTIVE":
        hive["lifecycle_status"] = "QUARANTINED"
        # Void every RECORDED harvest of this hive; recompute its projected allocation.
        for h in db.harvests.values():
            if h["hive_id"] == hive["id"] and h["status"] == "RECORDED":
                h["status"] = "VOIDED"
                touch(h)
        for a in db.allocations.values():
            if a["hive_id"] == hive["id"] and a["status"] == "PROJECTED":
                recompute_allocation_projected(a)
    elif hive["posture"] != "QUARANTINED" and hive["lifecycle_status"] == "QUARANTINED":
        hive["lifecycle_status"] = "ACTIVE"
    touch(hive)


# ---------------------------------------------------------------------------
# Overwinter credit
# ---------------------------------------------------------------------------

def overwinter_credit_cents(host_id, frost_date):
    count = 0
    for h in host_hives(host_id):
        if h["installed_at"] <= frost_date and h["lifecycle_status"] in ("ACTIVE", "QUARANTINED"):
            count += 1
    return OVERWINTER_CREDIT_PER_HIVE_CENTS * count


def projected_overwinter_credit_cents(subscription):
    season = open_season()
    if season is None:
        return 0
    return overwinter_credit_cents(subscription["host_id"], season["frost_date"])


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------

def make_invoice(sub, fee_cents, carried_cents, late_cents, credit_cents, at_time):
    inv = new_base()
    total = fee_cents + carried_cents + late_cents - credit_cents
    if total < 0:
        total = 0
    inv.update({
        "subscription_id": sub["id"],
        "period_label": "%04d-%02d" % (at_time.year, at_time.month),
        "fee_cents": fee_cents,
        "carried_balance_cents": carried_cents,
        "late_fee_cents": late_cents,
        "overwinter_credit_cents": credit_cents,
        "total_cents": total,
        "status": "OPEN",
        "issued_at": at_time,
        "due_at": at_time + timedelta(days=7),
        "paid_at": None,
    })
    db.invoices[inv["id"]] = inv
    return inv


def cure_cascade(subscription):
    """After an invoice becomes non-unpaid: subscription/host standing recovery."""
    unpaid = [i for i in db.invoices.values()
              if i["subscription_id"] == subscription["id"] and i["status"] in ("OPEN", "OVERDUE")]
    if not unpaid and subscription["status"] in ("PAST_DUE", "SUSPENDED"):
        subscription["status"] = "ACTIVE"
        touch(subscription)
    host = db.hosts.get(subscription["host_id"])
    if host is not None and host["status"] == "LIMITED" and host_balance_cents(host["id"]) == 0:
        host["status"] = "ACTIVE"
        touch(host)


# ---------------------------------------------------------------------------
# Season rollover checkpoint sweep (PRD §2.6 / §3.6 / §3.9)
# ---------------------------------------------------------------------------

def rollover_season(closing, name, frost_date):
    t = db.now()
    closing["status"] = "CLOSED"
    closing["closed_at"] = t
    touch(closing)

    successor = new_base()
    successor.update({"name": name, "frost_date": frost_date, "status": "OPEN",
                      "opened_at": t, "closed_at": None})
    db.seasons[successor["id"]] = successor

    # Allocation finalization for the closing season
    for alloc in list(db.allocations.values()):
        if alloc["season_id"] == closing["id"] and alloc["status"] == "PROJECTED":
            finalize_allocation(alloc, t)

    # Agreement expiry sweep
    for ag in list(db.agreements.values()):
        if ag["status"] in ("ACTIVE", "AMENDMENT_PENDING") and ag["term_end_date"] < t:
            ag["status"] = "EXPIRED"
            ag["pending_host_share_base_bps"] = None
            touch(ag)

    # Swarm expiry sweep
    for ev in list(db.swarm_events.values()):
        if ev["status"] in ("REPORTED", "DISPATCHED") and t > ev["reported_at"] + timedelta(hours=72):
            ev["status"] = "EXPIRED"
            touch(ev)

    # Billing sweep
    for sub in list(db.subscriptions.values()):
        if sub["status"] not in ("ACTIVE", "PAST_DUE"):
            continue
        entered = sub["status"]
        mutated = False
        # Pending plan change applies at rollover; fee is re-pinned.
        if sub["pending_plan"] is not None:
            sub["plan"] = sub["pending_plan"]
            sub["monthly_fee_cents"] = FEES[sub["plan"]]
            sub["pending_plan"] = None
            mutated = True
        # Age unpaid invoices
        for inv in db.invoices.values():
            if inv["subscription_id"] == sub["id"] and inv["status"] == "OPEN" and inv["due_at"] < t:
                inv["status"] = "OVERDUE"
                touch(inv)
        unpaid = [i for i in db.invoices.values()
                  if i["subscription_id"] == sub["id"] and i["status"] in ("OPEN", "OVERDUE")]
        carried = sum(i["total_cents"] for i in unpaid)
        late = 0
        for inv in unpaid:
            weeks = (t - inv["due_at"]).total_seconds() / (7 * 86400)
            weeks = int(weeks) if weeks >= 0 else 0
            if weeks < 0:
                weeks = 0
            if weeks > 0:
                late += weeks * int(round_half_up(Decimal(inv["total_cents"]) * Decimal("0.03"), 0))
        credit = overwinter_credit_cents(sub["host_id"], closing["frost_date"])
        make_invoice(sub, sub["monthly_fee_cents"], carried, late, credit, t)
        # Standing cascades
        has_overdue = any(i["status"] == "OVERDUE" for i in db.invoices.values()
                          if i["subscription_id"] == sub["id"])
        has_unpaid = any(i["status"] in ("OPEN", "OVERDUE") for i in db.invoices.values()
                         if i["subscription_id"] == sub["id"])
        if entered == "PAST_DUE" and has_unpaid:
            if sub["status"] != "SUSPENDED":
                sub["status"] = "SUSPENDED"
                mutated = True
        elif has_overdue and sub["status"] == "ACTIVE":
            sub["status"] = "PAST_DUE"
            mutated = True
        if mutated:
            touch(sub)
        if sub["status"] in ("PAST_DUE", "SUSPENDED"):
            host = db.hosts.get(sub["host_id"])
            if host is not None and host["status"] in ("ACTIVE", "LIMITED"):
                host["status"] = "LIMITED"
                touch(host)

    # Stand-alone adjustment invoices for outstanding cancellation fees
    for job in list(db.removal_jobs.values()):
        fee = job.get("cancellation_fee_cents")
        if job["status"] == "CANCELLED" and fee and not job.get("_fee_charged"):
            hive = db.hives.get(job["hive_id"])
            site = db.sites.get(hive["site_id"]) if hive else None
            sub = active_subscription(site["host_id"]) if site else None
            if sub is not None:
                make_invoice(sub, 0, fee, 0, 0, t)
            job["_fee_charged"] = True

    return successor
