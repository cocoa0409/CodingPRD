"""Business logic: calculations, cascades, state-machine side effects (SCAFFOLD §1.2/§1.3)."""

import hashlib
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
import errors
import helpers

MAX_REFUSALS = 2
OFFER_RESPONSE_DAYS = 10
CERTIFICATION_VALID_DAYS = 180
ROLLING_WINDOW_DAYS = 90


# ---------- provisional eligibility screen (at application submit) ----------

def provisional_screen(application, campaign):
    row = _ami_limit_for(
        campaign["property_id"], application["household_size"], campaign["target_ami_tier"]
    )
    if row is None:
        return "UNASSESSED"
    if application["self_reported_annual_income_cents"] <= row["annual_limit_cents"]:
        return "PROVISIONALLY_ELIGIBLE"
    return "PROVISIONALLY_OVER_INCOME"


def _ami_limit_for(property_id, household_size, ami_tier):
    for r in db.store.ami_limits.values():
        if (
            r["property_id"] == property_id
            and r["household_size"] == household_size
            and r["ami_tier"] == ami_tier
        ):
            return r
    return None


def _occupancy_for(property_id, bedroom_count):
    for r in db.store.occupancy_standards.values():
        if r["property_id"] == property_id and r["bedroom_count"] == bedroom_count:
            return r
    return None


# ---------- certification calculations ----------

def annualize_income(income_sources):
    """Per-source: round_half_up(amount_per_period_cents * periods_per_year / 100) dollars,
    then *100 cents; sum."""
    total_cents = 0
    for s in income_sources:
        amount = Decimal(str(s["amount_per_period_cents"]))
        periods = Decimal(str(s["periods_per_year"]))
        dollars = (amount * periods / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        total_cents += int(dollars) * 100
    return total_cents


def ami_percentage_bp(certified_cents, limit_cents):
    v = (Decimal(certified_cents) * Decimal(10000) / Decimal(limit_cents)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(v)


# ---------- lottery execution ----------

def execute_lottery(run):
    """Generate waitlist entries from SEAL snapshot: applications VERIFIED at SEAL time."""
    campaign_id = run["campaign_id"]
    seed = run["seed"]
    # Draw from the SEAL-time frozen snapshot, not the live VERIFIED set —
    # applications verified after sealing are excluded (PRD §3.5).
    snapshot_ids = db.store.lottery_snapshots.get(run["id"])
    if snapshot_ids is None:
        snapshot_ids = [
            a["id"]
            for a in db.store.applications.values()
            if a["campaign_id"] == campaign_id and a["status"] == "VERIFIED"
        ]
    apps = [db.store.applications[aid] for aid in snapshot_ids]

    # base_rank: ascending sha256_hex(seed + ':' + confirmation_code), tie-break created_at ASC
    def key_of(a):
        return hashlib.sha256((seed + ":" + a["confirmation_code"]).encode("utf-8")).hexdigest()

    by_hash = sorted(apps, key=lambda a: (key_of(a), a["created_at"]))
    base_rank = {a["id"]: i + 1 for i, a in enumerate(by_hash)}

    # preference_tier per application
    tier = {}
    for a in apps:
        claims = [
            c
            for c in db.store.preference_claims.values()
            if c["application_id"] == a["id"] and c["status"] == "VERIFIED"
        ]
        cats = {c["category"] for c in claims}
        if "LOCAL_RESIDENT" in cats:
            tier[a["id"]] = 1
        elif "VETERAN" in cats:
            tier[a["id"]] = 2
        elif "ACCESSIBILITY" in cats:
            tier[a["id"]] = 3
        else:
            tier[a["id"]] = 4

    # effective_rank: (preference_tier ASC, base_rank ASC, created_at ASC)
    ordered = sorted(apps, key=lambda a: (tier[a["id"]], base_rank[a["id"]], a["created_at"]))

    entries = []
    for i, a in enumerate(ordered):
        rec = db.new_record()
        rec.update(
            {
                "lottery_run_id": run["id"],
                "campaign_id": campaign_id,
                "application_id": a["id"],
                "base_rank": base_rank[a["id"]],
                "preference_tier": tier[a["id"]],
                "effective_rank": i + 1,
                "refusal_count": 0,
                "last_confirmed_at": None,
                "removal_reason": None,
                "removed_at": None,
                "status": "RANKED",
            }
        )
        db.store.waitlist_entries[rec["id"]] = rec
        entries.append(rec)

    run["entries_generated"] = len(entries)
    return entries


# ---------- offer unit selection ----------

def offer_unit_selection(campaign):
    """Walk AVAILABLE units in (created_at ASC, unit_number ASC) order; per unit, pick
    from still-RANKED entries. Returns (offers_created, units_considered)."""
    now = db.now_dt()
    campaign_id = campaign["id"]
    property_id = campaign["property_id"]

    published = [
        r
        for r in db.store.lottery_runs.values()
        if r["campaign_id"] == campaign_id and r["status"] == "PUBLISHED"
    ]
    if not published:
        raise errors.err(errors.ERR_INVALID_STATE, "no PUBLISHED lottery run for campaign")
    run = published[0]

    units = [
        u
        for u in db.store.units.values()
        if u["property_id"] == property_id and u["status"] == "AVAILABLE"
    ]
    units.sort(key=lambda u: (u["created_at"], u["unit_number"]))

    def ranked_entries():
        es = [
            e
            for e in db.store.waitlist_entries.values()
            if e["campaign_id"] == campaign_id and e["status"] == "RANKED"
        ]
        return es

    offers_created = []
    units_considered = len(units)

    for unit in units:
        occ = _occupancy_for(property_id, unit["bedroom_count"])
        if occ is None:
            continue  # unit skipped entirely

        pool = []
        for e in ranked_entries():
            app = db.store.applications[e["application_id"]]
            # (1) occupancy
            if not (occ["min_occupants"] <= app["household_size"] <= occ["max_occupants"]):
                continue
            # (2) income vs unit's ami_tier
            limit_row = _ami_limit_for(property_id, app["household_size"], unit["ami_tier"])
            if limit_row is None:
                continue
            # (3) certification CERTIFIED and valid
            cert = _current_certification(app["id"])
            if cert is None:
                continue
            if db.parse_iso(cert["valid_until"]) < now:
                continue
            if cert["certified_annual_income_cents"] > limit_row["annual_limit_cents"]:
                continue
            # (4) exclusion on retry: no prior DECLINED/EXPIRED offer for THIS unit
            prior = [
                o
                for o in db.store.unit_offers.values()
                if o["entry_id"] == e["id"]
                and o["unit_id"] == unit["id"]
                and o["status"] in ("DECLINED", "EXPIRED")
            ]
            if prior:
                continue
            pool.append(e)

        if not pool:
            continue  # empty-pool fallback

        def boost(entry):
            app = db.store.applications[entry["application_id"]]
            if (
                unit["accessibility_feature"] != "NONE"
                and "ACCESSIBILITY" in app.get("verified_preference_categories", [])
            ):
                return 1
            return 0

        # pick min by (boost DESC, effective_rank ASC, entry.created_at ASC)
        chosen = min(pool, key=lambda e: (-boost(e), e["effective_rank"], e["created_at"]))

        offered_at = db.now_iso()
        rec = db.new_record()
        rec.update(
            {
                "campaign_id": campaign_id,
                "entry_id": chosen["id"],
                "unit_id": unit["id"],
                "offered_at": offered_at,
                "response_deadline": db.format_iso(now + timedelta(days=OFFER_RESPONSE_DAYS)),
                "responded_at": None,
                "status": "PENDING",
            }
        )
        db.store.unit_offers[rec["id"]] = rec
        offers_created.append(rec)

        # entry RANKED -> OFFERED
        chosen["status"] = "OFFERED"
        db.touch(chosen)

        # unit AVAILABLE -> RESERVED
        unit["status"] = "RESERVED"
        db.touch(unit)
        helpers.recompute_property_counters(property_id)

    return offers_created, units_considered


def _current_certification(application_id):
    certs = [
        c
        for c in db.store.income_certifications.values()
        if c["application_id"] == application_id and c["status"] == "CERTIFIED"
    ]
    if not certs:
        return None
    certs.sort(key=lambda c: c["certified_at"] or "", reverse=True)
    return certs[0]


# ---------- offer response cascades ----------

def accept_offer(offer):
    now = db.now_iso()
    offer["status"] = "ACCEPTED"
    offer["responded_at"] = now
    db.touch(offer)

    entry = db.store.waitlist_entries[offer["entry_id"]]
    unit = db.store.units[offer["unit_id"]]
    campaign = db.store.campaigns[offer["campaign_id"]]

    # entry OFFERED -> LEASED
    entry["status"] = "LEASED"
    db.touch(entry)

    # unit RESERVED -> LEASED
    unit["status"] = "LEASED"
    db.touch(unit)

    helpers.recompute_property_counters(unit["property_id"])
    helpers.recompute_campaign_counters(campaign["id"])


def decline_or_expire_offer(offer, final_status):
    """Shared refusal cascade for DECLINED and EXPIRED."""
    now = db.now_iso()
    offer["status"] = final_status
    if final_status == "DECLINED":
        offer["responded_at"] = now
    db.touch(offer)

    entry = db.store.waitlist_entries[offer["entry_id"]]
    unit = db.store.units[offer["unit_id"]]
    campaign = db.store.campaigns[offer["campaign_id"]]

    entry["refusal_count"] += 1
    if entry["refusal_count"] >= MAX_REFUSALS:
        entry["status"] = "REMOVED"
        entry["removal_reason"] = "MAX_REFUSALS"
        entry["removed_at"] = now
    else:
        entry["status"] = "RANKED"
    db.touch(entry)

    # unit RESERVED -> AVAILABLE
    if unit["status"] == "RESERVED":
        unit["status"] = "AVAILABLE"
        db.touch(unit)

    helpers.recompute_property_counters(unit["property_id"])
    helpers.recompute_campaign_counters(campaign["id"])


def void_offer(offer):
    """Lottery VOID cascade: no refusal increment; unit released."""
    offer["status"] = "VOIDED"
    db.touch(offer)
    unit = db.store.units[offer["unit_id"]]
    if unit["status"] == "RESERVED":
        unit["status"] = "AVAILABLE"
        db.touch(unit)
        helpers.recompute_property_counters(unit["property_id"])


# ---------- lottery VOID cascade ----------

def void_lottery_cascade(run):
    now = db.now_iso()
    campaign_id = run["campaign_id"]
    entries = [
        e
        for e in db.store.waitlist_entries.values()
        if e["lottery_run_id"] == run["id"] and e["status"] in ("RANKED", "OFFERED")
    ]
    for e in entries:
        # PENDING offers of these entries -> VOIDED
        pendings = [
            o
            for o in db.store.unit_offers.values()
            if o["entry_id"] == e["id"] and o["status"] == "PENDING"
        ]
        for o in pendings:
            void_offer(o)
        e["status"] = "REMOVED"
        e["removal_reason"] = "LOTTERY_VOIDED"
        e["removed_at"] = now
        db.touch(e)
    helpers.recompute_campaign_counters(campaign_id)


# ---------- purge execution ----------

def execute_purge(purge):
    now = db.now_iso()
    campaign_id = purge["campaign_id"]
    notice_sent_at = purge["notice_sent_at"]
    removed = 0
    for e in db.store.waitlist_entries.values():
        if e["campaign_id"] != campaign_id or e["status"] != "RANKED":
            continue
        lca = e.get("last_confirmed_at")
        if lca is None or lca < notice_sent_at:
            e["status"] = "REMOVED"
            e["removal_reason"] = "PURGED"
            e["removed_at"] = now
            db.touch(e)
            removed += 1
    purge["entries_removed_count"] = removed
    purge["executed_at"] = now
    helpers.recompute_campaign_counters(campaign_id)
    return removed


# ---------- compliance aggregation ----------

def compute_report_aggregates(report):
    campaign_id = report["campaign_id"]
    mode = report["period_mode"]
    period_start = db.parse_iso(report["period_start"])
    period_end = db.parse_iso(report["period_end"])

    if mode == "CALENDAR_QUARTER":
        win_start = period_start
        win_end = _quarter_end_exclusive(period_start)
        end_inclusive = False
    else:  # ROLLING_90_DAY
        win_start = (period_end - timedelta(days=ROLLING_WINDOW_DAYS)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        win_end = period_end.replace(hour=23, minute=59, second=59, microsecond=999000)
        end_inclusive = True

    def inside(ts):
        if ts is None:
            return False
        t = db.parse_iso(ts)
        if t < win_start:
            return False
        if end_inclusive:
            return t <= win_end
        return t < win_end

    apps = [a for a in db.store.applications.values() if a["campaign_id"] == campaign_id]
    app_ids = {a["id"] for a in apps}
    claims = [
        c
        for c in db.store.preference_claims.values()
        if c["application_id"] in app_ids
    ]
    runs = [r for r in db.store.lottery_runs.values() if r["campaign_id"] == campaign_id]
    offers = [o for o in db.store.unit_offers.values() if o["campaign_id"] == campaign_id]
    entries = [e for e in db.store.waitlist_entries.values() if e["campaign_id"] == campaign_id]

    applications_received_count = sum(1 for a in apps if inside(a["created_at"]))
    applications_verified_count = sum(1 for a in apps if inside(a.get("verified_at")))
    decided = [c for c in claims if inside(c.get("decided_at"))]
    preference_claims_decided_count = len(decided)
    preference_claims_verified_count = sum(1 for c in decided if c["status"] == "VERIFIED")
    lottery_runs_executed_count = sum(1 for r in runs if inside(r.get("executed_at")))
    offers_made_count = sum(1 for o in offers if inside(o["created_at"]))
    offers_accepted_count = sum(
        1 for o in offers if o["status"] == "ACCEPTED" and inside(o.get("responded_at"))
    )
    entries_removed_count = sum(1 for e in entries if inside(e.get("removed_at")))

    if preference_claims_decided_count == 0:
        preference_verification_rate_bp = 0
    else:
        preference_verification_rate_bp = int(
            (
                Decimal(preference_claims_verified_count)
                * Decimal(10000)
                / Decimal(preference_claims_decided_count)
            ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
    if offers_made_count == 0:
        lease_up_rate_bp = 0
    else:
        lease_up_rate_bp = int(
            (
                Decimal(offers_accepted_count) * Decimal(10000) / Decimal(offers_made_count)
            ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )

    report["applications_received_count"] = applications_received_count
    report["applications_verified_count"] = applications_verified_count
    report["preference_claims_decided_count"] = preference_claims_decided_count
    report["preference_claims_verified_count"] = preference_claims_verified_count
    report["preference_verification_rate_bp"] = preference_verification_rate_bp
    report["lottery_runs_executed_count"] = lottery_runs_executed_count
    report["offers_made_count"] = offers_made_count
    report["offers_accepted_count"] = offers_accepted_count
    report["entries_removed_count"] = entries_removed_count
    report["lease_up_rate_bp"] = lease_up_rate_bp


def _quarter_end_exclusive(period_start):
    month = period_start.month
    if month == 1:
        nxt = period_start.replace(month=4)
    elif month == 4:
        nxt = period_start.replace(month=7)
    elif month == 7:
        nxt = period_start.replace(month=10)
    else:  # 10
        nxt = period_start.replace(year=period_start.year + 1, month=1)
    return nxt


def validate_calendar_quarter(period_start, period_end):
    """period_start must be first day of a calendar quarter at 00:00:00 UTC;
    period_end the last day of the same quarter."""
    if period_start.month not in (1, 4, 7, 10):
        return False
    if period_start.day != 1:
        return False
    if (period_start.hour, period_start.minute, period_start.second, period_start.microsecond) != (0, 0, 0, 0):
        return False
    # expected end date
    end_excl = _quarter_end_exclusive(period_start)
    last_day = (end_excl - timedelta(days=1)).date()
    return period_end.date() == last_day
