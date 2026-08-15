"""Shared entity helpers, serializers, derived-field recomputation, time
sweeps, and the auction/clearing engine.

Money is integer micros throughout; rates are integer basis points
(10000 bps = 100%). Every division that must land on integer micros rounds
half-up, and rounded components are summed only after each is individually
rounded (PRD §2.5).
"""

from decimal import Decimal, ROUND_HALF_UP

from db import store, fmt_ts, fmt_clock, new_id

# ---------------------------------------------------------------------------
# domain constants (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------

PAYMENT_TERMS = {"SEQUENTIAL_LIABILITY", "GUARANTEED"}
AD_FORMATS = {"DISPLAY", "VIDEO", "NATIVE", "AUDIO"}
DEAL_TYPES = {"PMP_STANDARD", "PMP_EXCLUSIVE", "PREFERRED", "PROGRAMMATIC_GUARANTEED"}
AUCTION_TYPES = {"FIRST_PRICE", "SECOND_PRICE"}
BLOCKLIST_SCOPES = {"EXCHANGE", "PUBLISHER", "DEAL"}
RULE_TYPES = {"ADVERTISER_DOMAIN", "CATEGORY"}
RESOLUTION_TYPES = {"ACCEPT_SSP", "ACCEPT_DSP", "MAKE_GOOD"}
EXCLUSIVE_DEAL_TYPES = {"PMP_EXCLUSIVE", "PROGRAMMATIC_GUARANTEED"}

NEUTRAL_MULTIPLIER_BPS = 10000
SECOND_PRICE_STEP_MICROS = 1000
DSP_FEE_BPS = 1000
TIER1_CAP_MICROS = 5_000_000
TIER2_CAP_MICROS = 20_000_000
TIER1_BPS = 1500
TIER2_BPS = 1000
TIER3_BPS = 500
MAX_CHAIN_HOPS = 10
MAX_CHAIN_FEE_BPS = 9000
DISCREPANCY_THRESHOLD_PCT = Decimal("2.000")

PUBLISHER_STATUSES = {"ACTIVE", "SUSPENDED"}
PARTNER_STATUSES = {"ACTIVE", "THROTTLED", "SUSPENDED"}
PACKAGE_STATUSES = {"ACTIVE", "PAUSED"}
DEAL_STATUSES = {"DRAFT", "PENDING_REVIEW", "ACTIVE", "RENEGOTIATING", "PAUSED", "EXPIRED"}
ENTRY_STATUSES = {"ACTIVE", "LIFTED"}
REPORT_STATUSES = {"OPEN", "ACKNOWLEDGED", "DISPUTED", "RESOLVED"}
BATCH_STATUSES = {"DRAFT", "PENDING_APPROVAL", "APPROVED", "RELEASED", "SETTLED"}
LINE_STATUSES = {"PENDING", "HELD", "ELIGIBLE", "PAID", "WRITTEN_OFF"}


# ---------------------------------------------------------------------------
# rounding (PRD §2.5: round half-up on every division-to-integer; components
# rounded individually before any sum)
# ---------------------------------------------------------------------------

def rhu_div(numerator, denominator):
    """round_half_up(numerator / denominator) for non-negative integers."""
    return (2 * numerator + denominator) // (2 * denominator)


def round_pct_3dp(numerator, denominator):
    """round_half_up to 3 decimal places; returns a JSON-safe float."""
    q = (Decimal(numerator) * Decimal(100) / Decimal(denominator)).quantize(
        Decimal("0.001"), rounding=ROUND_HALF_UP)
    return q


# ---------------------------------------------------------------------------
# record factories / mutation discipline (PRD §2.6)
# ---------------------------------------------------------------------------

def base_record():
    """Common fields: id, created_at, updated_at (3-fractional-digit ISO),
    version starting at 1 and +1 on every mutation."""
    ts = store.now_str()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }


def base_record_light():
    """SupplyChainNode and AuctionRecord carry only id + created_at."""
    return {
        "id": new_id(),
        "created_at": store.now_str(),
        "_seq": store.next_seq(),
    }


def touch(rec):
    """One mutation event on a versioned resource: version +1, updated_at
    refresh (logical clock)."""
    rec["updated_at"] = store.now_str()
    rec["version"] = rec.get("version", 1) + 1


def _sorted(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# serializers (exact public field sets; internal underscore keys never leak)
# ---------------------------------------------------------------------------

def serialize_publisher(p):
    active_pkgs = sum(1 for pkg in store.packages.values()
                      if pkg["publisher_id"] == p["id"] and pkg["status"] == "ACTIVE")
    return {
        "id": p["id"],
        "name": p["name"],
        "domain": p["domain"],
        "payment_terms": p["payment_terms"],
        "status": p["status"],
        "lifetime_net_micros": p["lifetime_net_micros"],
        "accrued_open_micros": p["accrued_open_micros"],
        "paid_out_micros": p["paid_out_micros"],
        "written_off_micros": p["written_off_micros"],
        "active_package_count": active_pkgs,
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_partner(p):
    return {
        "id": p["id"],
        "name": p["name"],
        "seat_id": p["seat_id"],
        "max_qps": p["max_qps"],
        "daily_cap_micros": p["daily_cap_micros"],
        "status": p["status"],
        "spend_today_micros": p["spend_today_micros"],
        "current_second_auction_count": p["current_second_auction_count"],
        "lifetime_spend_micros": p["lifetime_spend_micros"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_package(pkg):
    active_deals = sum(1 for d in store.deals.values()
                       if d["package_id"] == pkg["id"] and d["status"] == "ACTIVE")
    return {
        "id": pkg["id"],
        "publisher_id": pkg["publisher_id"],
        "name": pkg["name"],
        "ad_format": pkg["ad_format"],
        "category_tags": list(pkg["category_tags"]),
        "base_floor_cpm_micros": pkg["base_floor_cpm_micros"],
        "status": pkg["status"],
        "active_deal_count": active_deals,
        "current_seasonal_multiplier_bps": pkg["current_seasonal_multiplier_bps"],
        "effective_floor_cpm_micros": pkg["effective_floor_cpm_micros"],
        "created_at": pkg["created_at"],
        "updated_at": pkg["updated_at"],
        "version": pkg["version"],
    }


def serialize_window(w):
    today = store.now().date()
    return {
        "id": w["id"],
        "package_id": w["package_id"],
        "name": w["name"],
        "start_date": w["start_date"].isoformat(),
        "end_date": w["end_date"].isoformat(),
        "multiplier_bps": w["multiplier_bps"],
        "is_currently_applied": w["start_date"] <= today <= w["end_date"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


def serialize_deal(d):
    if d["deal_type"] == "PROGRAMMATIC_GUARANTEED":
        remaining = d["committed_impressions"] - d["delivered_impressions"]
    else:
        remaining = None
    return {
        "id": d["id"],
        "package_id": d["package_id"],
        "publisher_id": d["publisher_id"],
        "demand_partner_id": d["demand_partner_id"],
        "deal_type": d["deal_type"],
        "is_exclusive": d["is_exclusive"],
        "auction_type": d["auction_type"],
        "floor_cpm_micros": d["floor_cpm_micros"],
        "start_at": fmt_clock(d["_start_dt"]),
        "end_at": fmt_clock(d["_end_dt"]),
        "committed_impressions": d["committed_impressions"],
        "delivered_impressions": d["delivered_impressions"],
        "remaining_committed_impressions": remaining,
        "approved_floor_cpm_micros": d["approved_floor_cpm_micros"],
        "status": d["status"],
        "renegotiation_count": d["renegotiation_count"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def serialize_node(n):
    return {
        "id": n["id"],
        "package_id": n["package_id"],
        "parent_node_id": n["parent_node_id"],
        "seller_domain": n["seller_domain"],
        "fee_bps": n["fee_bps"],
        "hop_index": n["hop_index"],
        "is_tail": n["is_tail"],
        "created_at": n["created_at"],
    }


def serialize_entry(e):
    return {
        "id": e["id"],
        "scope": e["scope"],
        "publisher_id": e["publisher_id"],
        "deal_id": e["deal_id"],
        "rule_type": e["rule_type"],
        "value": e["value"],
        "status": e["status"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def serialize_record(r):
    return {
        "id": r["id"],
        "deal_id": r["deal_id"],
        "publisher_id": r["publisher_id"],
        "demand_partner_id": r["demand_partner_id"],
        "auction_type": r["auction_type"],
        "winning_bid_cpm_micros": r["winning_bid_cpm_micros"],
        "clearing_cpm_micros": r["clearing_cpm_micros"],
        "impressions": r["impressions"],
        "creative_domain": r["creative_domain"],
        "gross_micros": r["gross_micros"],
        "exchange_fee_micros": r["exchange_fee_micros"],
        "supply_fee_micros": r["supply_fee_micros"],
        "publisher_net_micros": r["publisher_net_micros"],
        "dsp_fee_micros": r["dsp_fee_micros"],
        "dsp_billed_micros": r["dsp_billed_micros"],
        "dsp_confirmed_at": fmt_clock(r["_confirmed_dt"]),
        "voided": r["voided"],
        "voided_at": fmt_clock(r["_voided_dt"]),
        "created_at": r["created_at"],
    }


def serialize_report(rep):
    return {
        "id": rep["id"],
        "deal_id": rep["deal_id"],
        "period_start": rep["period_start"].isoformat(),
        "period_end": rep["period_end"].isoformat(),
        "ssp_impressions": rep["ssp_impressions"],
        "ssp_spend_micros": rep["ssp_spend_micros"],
        "dsp_impressions": rep["dsp_impressions"],
        "dsp_billed_micros": rep["dsp_billed_micros"],
        "discrepancy_pct": float(rep["discrepancy_pct"]),
        "auto_flagged": rep["auto_flagged"],
        "status": rep["status"],
        "resolution_type": rep["resolution_type"],
        "adjustment_micros": rep["adjustment_micros"],
        "resolved_at": fmt_clock(rep["_resolved_dt"]),
        "created_at": rep["created_at"],
        "updated_at": rep["updated_at"],
        "version": rep["version"],
    }


def serialize_batch(b):
    return {
        "id": b["id"],
        "period_start": b["period_start"].isoformat(),
        "period_end": b["period_end"].isoformat(),
        "status": b["status"],
        "created_by_user_id": b["created_by_user_id"],
        "line_count": b["line_count"],
        "total_gross_micros": b["total_gross_micros"],
        "total_payable_micros": b["total_payable_micros"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def serialize_line(l):
    return {
        "id": l["id"],
        "batch_id": l["batch_id"],
        "publisher_id": l["publisher_id"],
        "status": l["status"],
        "gross_micros": l["gross_micros"],
        "confirmed_micros": l["confirmed_micros"],
        "unconfirmed_micros": l["unconfirmed_micros"],
        "adjustment_micros": l["adjustment_micros"],
        "payable_micros": l["payable_micros"],
        "paid_micros": l["paid_micros"],
        "written_off_amount_micros": l["written_off_amount_micros"],
        "write_off_reason": l["write_off_reason"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


# ---------------------------------------------------------------------------
# derived-field recomputation (PRD §2.10: recomputation is itself a mutation —
# version and updated_at move with any actual change)
# ---------------------------------------------------------------------------

def recompute_package_floor(pkg):
    """effective_floor per calculation effective_floor. Returns True when the
    stored derived values changed (caller decides on the version bump)."""
    today = store.now().date()
    mult = NEUTRAL_MULTIPLIER_BPS
    for w in store.windows.values():
        if w["package_id"] == pkg["id"] and w["start_date"] <= today <= w["end_date"]:
            mult = w["multiplier_bps"]
            break
    eff = rhu_div(pkg["base_floor_cpm_micros"] * mult, 10000)
    changed = (pkg["current_seasonal_multiplier_bps"] != mult
               or pkg["effective_floor_cpm_micros"] != eff)
    if changed:
        pkg["current_seasonal_multiplier_bps"] = mult
        pkg["effective_floor_cpm_micros"] = eff
    return changed


def recompute_publisher_accruals(pub):
    """publisher_accrual calculation + conservation invariant (PRD §2.10)."""
    lifetime = sum(r["publisher_net_micros"] for r in store.records.values()
                   if r["publisher_id"] == pub["id"] and not r["voided"])
    paid = sum(l["paid_micros"] for l in store.payout_lines.values()
               if l["publisher_id"] == pub["id"] and l["status"] == "PAID")
    written = sum(l["written_off_amount_micros"] for l in store.payout_lines.values()
                  if l["publisher_id"] == pub["id"] and l["status"] == "WRITTEN_OFF")
    adjustments = 0
    for rep in store.reports.values():
        if rep["status"] == "RESOLVED" and rep["resolution_type"] == "MAKE_GOOD":
            deal = store.deals.get(rep["deal_id"])
            if deal is not None and deal["publisher_id"] == pub["id"]:
                adjustments += rep["adjustment_micros"]
    accrued = lifetime - paid - written + adjustments
    if (pub["lifetime_net_micros"] != lifetime or pub["paid_out_micros"] != paid
            or pub["written_off_micros"] != written or pub["accrued_open_micros"] != accrued):
        pub["lifetime_net_micros"] = lifetime
        pub["paid_out_micros"] = paid
        pub["written_off_micros"] = written
        pub["accrued_open_micros"] = accrued
        touch(pub)


def recompute_spend_today(partner):
    """spend_today_micros = gross over the partner's non-voided records whose
    creation UTC date is the logical clock's current date."""
    today = store.now().date()
    s = sum(r["gross_micros"] for r in store.records.values()
            if r["demand_partner_id"] == partner["id"] and not r["voided"]
            and r["_created_dt"].date() == today)
    if partner["spend_today_micros"] != s:
        partner["spend_today_micros"] = s
        touch(partner)


# ---------------------------------------------------------------------------
# deal expiry (lazy on touch, eager on clock sets — PRD §2.4)
# ---------------------------------------------------------------------------

def expire_deal_if_due(deal):
    """ACTIVE -> EXPIRED when the logical clock is at or after end_at.
    EXPIRED is terminal."""
    if deal["status"] == "ACTIVE" and store.now() >= deal["_end_dt"]:
        deal["status"] = "EXPIRED"
        touch(deal)


def expire_deals_for_publisher(publisher_id):
    for d in store.deals.values():
        if d["publisher_id"] == publisher_id:
            expire_deal_if_due(d)


def expire_all_deals():
    for d in store.deals.values():
        expire_deal_if_due(d)


# ---------------------------------------------------------------------------
# logical-clock sweeps (PRD §2.4: fire on every POST /_clock/set_current_utc)
# ---------------------------------------------------------------------------

def run_clock_sweeps(old, new):
    old_sec = old.replace(microsecond=0)
    new_sec = new.replace(microsecond=0)

    # UTC-date change: recompute package floors and partner spend_today.
    if old.date() != new.date():
        for pkg in store.packages.values():
            if recompute_package_floor(pkg):
                touch(pkg)
        for p in store.partners.values():
            recompute_spend_today(p)

    # Later UTC second: reset per-second counters; auto-reactivate THROTTLED
    # partners whose throttle second has passed and whose recomputed
    # spend_today is below the daily cap.
    if new_sec > old_sec:
        for p in store.partners.values():
            if p["current_second_auction_count"] != 0:
                p["current_second_auction_count"] = 0
                touch(p)
        for p in store.partners.values():
            if (p["status"] == "THROTTLED" and p.get("_throttled_second") is not None
                    and new_sec > p["_throttled_second"]):
                recompute_spend_today(p)
                if p["spend_today_micros"] < p["daily_cap_micros"]:
                    p["status"] = "ACTIVE"
                    p["_throttled_second"] = None
                    touch(p)

    # Independent of both: deal-expiry sweep.
    expire_all_deals()


# ---------------------------------------------------------------------------
# fee calculations (SCAFFOLD §1.3, PRD §3.5)
# ---------------------------------------------------------------------------

def exchange_fee_micros(gross):
    """Marginal per-slab tiers over THIS record's gross; each slab rounded
    half-up individually, then summed (pinned order)."""
    fee = rhu_div(min(gross, TIER1_CAP_MICROS) * TIER1_BPS, 10000)
    if gross > TIER1_CAP_MICROS:
        fee += rhu_div((min(gross, TIER2_CAP_MICROS) - TIER1_CAP_MICROS) * TIER2_BPS, 10000)
    if gross > TIER2_CAP_MICROS:
        fee += rhu_div((gross - TIER2_CAP_MICROS) * TIER3_BPS, 10000)
    return fee


def supply_path_fee(package_id, remainder0):
    """Head-first waterfall over the package's supply chain on the amount
    remaining after the exchange fee. Returns (supply_fee_micros,
    publisher_net_micros == final remainder)."""
    nodes = sorted((n for n in store.nodes.values() if n["package_id"] == package_id),
                   key=lambda n: n["hop_index"])
    total = 0
    remainder = remainder0
    for n in nodes:
        hop_fee = rhu_div(remainder * n["fee_bps"], 10000)
        total += hop_fee
        remainder -= hop_fee
    return total, remainder


def dsp_billing(gross):
    fee = rhu_div(gross * DSP_FEE_BPS, 10000)
    return fee, gross + fee


# ---------------------------------------------------------------------------
# brand safety
# ---------------------------------------------------------------------------

def category_blocked(deal, pkg):
    """An ACTIVE CATEGORY entry gates the deal when its value appears in the
    package's tags at exchange, publisher, or deal scope."""
    tags = set(pkg["category_tags"])
    for e in store.blocklist.values():
        if e["status"] != "ACTIVE" or e["rule_type"] != "CATEGORY":
            continue
        if e["value"] not in tags:
            continue
        if (e["scope"] == "EXCHANGE"
                or (e["scope"] == "PUBLISHER" and e["publisher_id"] == deal["publisher_id"])
                or (e["scope"] == "DEAL" and e["deal_id"] == deal["id"])):
            return True
    return False


def domain_blocked(domain, deal):
    """An ACTIVE ADVERTISER_DOMAIN entry drops a bid at clearing time."""
    for e in store.blocklist.values():
        if e["status"] != "ACTIVE" or e["rule_type"] != "ADVERTISER_DOMAIN":
            continue
        if e["value"] != domain:
            continue
        if (e["scope"] == "EXCHANGE"
                or (e["scope"] == "PUBLISHER" and e["publisher_id"] == deal["publisher_id"])
                or (e["scope"] == "DEAL" and e["deal_id"] == deal["id"])):
            return True
    return False


# ---------------------------------------------------------------------------
# the auction engine (PRD §3.5)
# ---------------------------------------------------------------------------

def execute_auction(publisher_id, bids):
    """Run one auction. Returns (outcome, record_or_none, throttled_deal_count).

    Pipeline: lazy deal expiry -> per-partner capacity gates (budget, then QPS
    position walk) -> eligibility -> ranking -> first filling deal clears ->
    counters and accruals move on a fill -> deferred QPS throttles apply.
    """
    now = store.now()
    now_sec = now.replace(microsecond=0)
    pub = store.publishers[publisher_id]

    # lazy expiry sweep on this publisher's deals (auction candidacy touch)
    expire_deals_for_publisher(publisher_id)

    # ---- capacity gates, per demand partner with live deals on this publisher
    admitted_deal_ids = set()
    throttled_deal_count = 0
    qps_throttle_marks = []  # partners to throttle after the auction completes
    for p in _sorted(store.partners.values()):
        if p["status"] != "ACTIVE":
            continue  # THROTTLED / SUSPENDED partners are out of candidacy
        candidates = [d for d in store.deals.values()
                      if d["demand_partner_id"] == p["id"]
                      and d["publisher_id"] == publisher_id
                      and d["status"] == "ACTIVE"]
        if not candidates:
            continue
        # budget gate, evaluated once per request per partner: at the cap
        # (>=) blocks; one micro below does not.
        if p["spend_today_micros"] >= p["daily_cap_micros"]:
            p["status"] = "THROTTLED"
            p["_throttled_second"] = now_sec
            touch(p)
            continue
        # QPS position gate: k-th candidate (1-based, pinned order) takes part
        # iff current_second_auction_count + k <= max_qps.
        candidates.sort(key=lambda d: (d["approved_floor_cpm_micros"],
                                       d["_start_dt"], d["created_at"], d["_seq"]))
        excluded = 0
        for k, d in enumerate(candidates, start=1):
            if p["current_second_auction_count"] + k <= p["max_qps"]:
                admitted_deal_ids.add(d["id"])
            else:
                excluded += 1
        if excluded:
            throttled_deal_count += excluded
            qps_throttle_marks.append(p)

    # ---- deal eligibility (deal_selection calculation)
    def eligible(d):
        if d["id"] not in admitted_deal_ids:
            return False
        if d["status"] != "ACTIVE":
            return False
        if not (d["_start_dt"] <= now < d["_end_dt"]):
            return False
        pkg = store.packages[d["package_id"]]
        if pkg["status"] != "ACTIVE":
            return False
        if pub["status"] != "ACTIVE":
            return False
        if store.partners[d["demand_partner_id"]]["status"] != "ACTIVE":
            return False
        if d["deal_type"] == "PROGRAMMATIC_GUARANTEED":
            if d["committed_impressions"] - d["delivered_impressions"] <= 0:
                return False
        if category_blocked(d, pkg):
            return False
        return True

    ranked = sorted(
        (d for d in store.deals.values()
         if d["publisher_id"] == publisher_id and eligible(d)),
        key=lambda d: (not d["is_exclusive"], -d["approved_floor_cpm_micros"],
                       d["_start_dt"], d["created_at"], d["_seq"]))

    # ---- clearing (clearing_price steps 1-3 per deal; first winner fills)
    def evaluate(deal):
        floor = deal["approved_floor_cpm_micros"]
        surviving = [b for b in bids if not domain_blocked(b["creative_domain"], deal)]
        elig = [b for b in surviving if b["bid_cpm_micros"] >= floor]
        if not elig:
            return None
        # winner: highest bid; tie -> fewer impressions; then earliest index
        best_i, best = max(enumerate(elig),
                           key=lambda ib: (ib[1]["bid_cpm_micros"],
                                           -ib[1]["impression_count"], -ib[0]))
        if deal["auction_type"] == "FIRST_PRICE":
            clearing = best["bid_cpm_micros"]
        else:
            second = max((b["bid_cpm_micros"] for i, b in enumerate(elig) if i != best_i),
                         default=floor - SECOND_PRICE_STEP_MICROS)
            clearing = max(floor, second + SECOND_PRICE_STEP_MICROS)
        gross = rhu_div(clearing * best["impression_count"], 1000)
        return best, clearing, gross

    fill_deal = fill_bid = None
    fill_clearing = fill_gross = 0
    for d in ranked:
        outcome = evaluate(d)
        if outcome is not None:
            fill_deal = d
            fill_bid, fill_clearing, fill_gross = outcome
            break

    record = None
    if fill_deal is not None:
        # fee layers in pinned order: exchange fee -> supply waterfall -> net;
        # DSP billing computed independently last.
        fee = exchange_fee_micros(fill_gross)
        supply_fee, net = supply_path_fee(fill_deal["package_id"], fill_gross - fee)
        dsp_fee, dsp_billed = dsp_billing(fill_gross)
        record = base_record_light()
        record.update({
            "deal_id": fill_deal["id"],
            "publisher_id": publisher_id,
            "demand_partner_id": fill_deal["demand_partner_id"],
            "auction_type": fill_deal["auction_type"],
            "winning_bid_cpm_micros": fill_bid["bid_cpm_micros"],
            "clearing_cpm_micros": fill_clearing,
            "impressions": fill_bid["impression_count"],
            "creative_domain": fill_bid["creative_domain"],
            "gross_micros": fill_gross,
            "exchange_fee_micros": fee,
            "supply_fee_micros": supply_fee,
            "publisher_net_micros": net,
            "dsp_fee_micros": dsp_fee,
            "dsp_billed_micros": dsp_billed,
            "voided": False,
            "_created_dt": now,
            "_confirmed_dt": None,
            "_voided_dt": None,
        })
        store.records[record["id"]] = record
        # counters and derived fields move (spend_conservation /
        # publisher_accrual calculations)
        partner = store.partners[fill_deal["demand_partner_id"]]
        partner["current_second_auction_count"] += 1
        partner["spend_today_micros"] += fill_gross
        partner["lifetime_spend_micros"] += fill_gross
        touch(partner)
        fill_deal["delivered_impressions"] += fill_bid["impression_count"]
        touch(fill_deal)
        recompute_publisher_accruals(pub)

    # QPS throttle transitions land after the auction completes, fill or not.
    for p in qps_throttle_marks:
        if p["status"] == "ACTIVE":
            p["status"] = "THROTTLED"
            p["_throttled_second"] = now_sec
            touch(p)

    if record is None:
        return "NO_FILL", None, throttled_deal_count
    return "FILL", record, throttled_deal_count


# ---------------------------------------------------------------------------
# payout line composition (calculation payout_line_composition, PRD §3.8)
# ---------------------------------------------------------------------------

def line_composition(batch, publisher_id):
    """Compute (gross, confirmed, unconfirmed, adjustment, payable) for one
    publisher over the batch period, per the publisher's payment terms."""
    records = [r for r in store.records.values()
               if r["publisher_id"] == publisher_id and not r["voided"]
               and batch["period_start"] <= r["_created_dt"].date() < batch["period_end"]]
    gross = sum(r["publisher_net_micros"] for r in records)
    confirmed = sum(r["publisher_net_micros"] for r in records
                    if r["_confirmed_dt"] is not None)
    unconfirmed = gross - confirmed
    reports = [rep for rep in store.reports.values()
               if rep["status"] == "RESOLVED" and rep["resolution_type"] == "MAKE_GOOD"
               and store.deals[rep["deal_id"]]["publisher_id"] == publisher_id
               and rep["period_start"] < batch["period_end"]
               and rep["period_end"] > batch["period_start"]]
    reports.sort(key=lambda rep: (rep["created_at"], rep["period_start"], rep["_seq"]))
    adjustment = sum(rep["adjustment_micros"] for rep in reports)
    pub = store.publishers[publisher_id]
    if pub["payment_terms"] == "GUARANTEED":
        payable = gross + adjustment
    else:
        payable = confirmed + adjustment
    return gross, confirmed, unconfirmed, adjustment, payable


def refresh_line(line):
    """Re-evaluate a line's composition against current records and reports.
    Returns True when any computed field changed."""
    batch = store.payout_batches[line["batch_id"]]
    gross, confirmed, unconfirmed, adjustment, payable = line_composition(
        batch, line["publisher_id"])
    changed = (line["gross_micros"] != gross or line["confirmed_micros"] != confirmed
               or line["unconfirmed_micros"] != unconfirmed
               or line["adjustment_micros"] != adjustment
               or line["payable_micros"] != payable)
    if changed:
        line["gross_micros"] = gross
        line["confirmed_micros"] = confirmed
        line["unconfirmed_micros"] = unconfirmed
        line["adjustment_micros"] = adjustment
        line["payable_micros"] = payable
    return changed


def recompute_batch_aggregates(batch):
    """line_count over existing lines; total_gross over all lines;
    total_payable over PENDING / HELD / ELIGIBLE lines."""
    lines = [l for l in store.payout_lines.values() if l["batch_id"] == batch["id"]]
    batch["line_count"] = len(lines)
    batch["total_gross_micros"] = sum(l["gross_micros"] for l in lines)
    batch["total_payable_micros"] = sum(
        l["payable_micros"] for l in lines if l["status"] in ("PENDING", "HELD", "ELIGIBLE"))
