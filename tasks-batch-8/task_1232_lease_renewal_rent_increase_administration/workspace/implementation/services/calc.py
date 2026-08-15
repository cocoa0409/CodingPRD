"""Calculation rules — pricing pipeline, staggered term, MTM rent, retention, forecast."""

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store
from timeutil import (
    parse_date, add_months, add_days, month_key, clock_date,
)


TERM_DISCOUNT_PER_MONTH_BPS = 10
MAX_TERM_DISCOUNT_BPS = 180
MTM_PREMIUM_BPS = 1500

AGENT_MAX_CONCESSION_BPS = 300
MANAGER_MAX_CONCESSION_BPS = 800
ABSOLUTE_MAX_CONCESSION_BPS = 2000

OPEN_OFFER_STATUSES = {"DRAFT", "ISSUED", "COUNTERED", "ACCEPTED"}


def round_half_up_int(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_effective_cap_bps(policy: dict) -> int:
    return min(
        int(policy["base_cap_bps"]) + int(policy["cpi_adjustment_bps"]),
        int(policy["hard_ceiling_bps"]),
    )


def compute_pricing(monthly_rent_cents: int, market_rent_cents: int,
                    offered_term_months: int, rate_strategy: str,
                    cap_bps: int):
    """Six-step pipeline. Returns (proposed_rent_cents, proposed_increase_bps)."""
    base = Decimal(int(monthly_rent_cents))
    market = Decimal(int(market_rent_cents))

    # Step 1: gap_bps
    if base <= 0:
        gap_bps = 0
    else:
        gap = (market - base) / base * Decimal(10000)
        gap_bps = round_half_up_int(gap)
        if gap_bps < 0:
            gap_bps = 0

    # Step 2: strategy share
    factor = {"AGGRESSIVE": Decimal("1.0"),
              "BALANCED": Decimal("0.6"),
              "CONSERVATIVE": Decimal("0.3")}[rate_strategy]
    strategy_pct_bps = round_half_up_int(Decimal(gap_bps) * factor)

    # Step 3: term discount
    term_discount_bps = (int(offered_term_months) - 12) * TERM_DISCOUNT_PER_MONTH_BPS
    if term_discount_bps > MAX_TERM_DISCOUNT_BPS:
        term_discount_bps = MAX_TERM_DISCOUNT_BPS
    if term_discount_bps < 0:
        term_discount_bps = 0

    # Step 4: uncapped
    uncapped_bps = strategy_pct_bps - term_discount_bps
    if uncapped_bps < 0:
        uncapped_bps = 0

    # Step 5: cap
    capped_bps = min(uncapped_bps, int(cap_bps))

    # Step 6: rent
    rent_decimal = base * (Decimal(1) + Decimal(capped_bps) / Decimal(10000))
    rent_cents = round_half_up_int(rent_decimal)

    # proposed_increase_bps over base
    if base <= 0:
        increase_bps = 0
    else:
        increase = (Decimal(rent_cents) - base) / base * Decimal(10000)
        increase_bps = round_half_up_int(increase)
        if increase_bps < 0:
            increase_bps = 0

    return rent_cents, increase_bps


def compute_notice_days_required(proposed_increase_bps: int, policy: dict) -> int:
    if int(proposed_increase_bps) > int(policy["high_increase_threshold_bps"]):
        return int(policy["notice_days_high"])
    return int(policy["notice_days_low"])


def compute_latest_issue_date(lease: dict, notice_days_required: int):
    """None when lease is MTM."""
    if lease["status"] == "MTM":
        return None
    end = parse_date(lease["term_end_date"])
    return (end - timedelta(days=notice_days_required)).strftime("%Y-%m-%d")


def offer_projected_end(offer: dict, lease: dict):
    """projected_end for an offer: base = lease.term_end_date or clock date if lease MTM."""
    if lease["status"] == "MTM":
        base = clock_date()
    else:
        base = parse_date(lease["term_end_date"])
    return add_months(base, int(offer["offered_term_months"]))


def staggered_term_selection(lease: dict, property_: dict) -> int:
    """Pick t in [min_term_months, max_term_months] minimizing load; tie -> larger t."""
    prop_id = property_["id"]
    subject_lease_id = lease["id"]

    if lease["status"] == "MTM":
        base = clock_date()
    else:
        base = parse_date(lease["term_end_date"])

    # Pre-compute lease counts per month bucket (excluding subject lease)
    lease_counts = {}
    for l in store.leases.values():
        if l["property_id"] != prop_id:
            continue
        if l["id"] == subject_lease_id:
            continue
        if l["status"] not in ("ACTIVE", "RENEWAL_PENDING", "NON_RENEWAL_NOTICED"):
            continue
        if not l.get("term_end_date"):
            continue
        k = month_key(parse_date(l["term_end_date"]))
        lease_counts[k] = lease_counts.get(k, 0) + 1

    # Pre-compute offer counts per month bucket (excluding subject lease's offers)
    offer_counts = {}
    for o in store.renewal_offers.values():
        if o["status"] not in OPEN_OFFER_STATUSES:
            continue
        o_lease = store.leases.get(o["lease_id"])
        if o_lease is None:
            continue
        if o_lease["property_id"] != prop_id:
            continue
        if o_lease["id"] == subject_lease_id:
            continue
        pend = offer_projected_end(o, o_lease)
        k = month_key(pend)
        offer_counts[k] = offer_counts.get(k, 0) + 1

    min_t = int(property_["min_term_months"])
    max_t = int(property_["max_term_months"])
    best_t = None
    best_load = None
    for t in range(min_t, max_t + 1):
        pend = add_months(base, t)
        k = month_key(pend)
        load = lease_counts.get(k, 0) + offer_counts.get(k, 0)
        if best_load is None or load < best_load or (load == best_load and t > best_t):
            best_load = load
            best_t = t
    return best_t


def mtm_rent_cents(lease: dict, policy: dict) -> int:
    """Two pinned rounding steps."""
    # Find most recently created offer with issued_on_date set
    issued = [o for o in store.renewal_offers.values()
              if o["lease_id"] == lease["id"] and o.get("issued_on_date")]
    if issued:
        issued.sort(key=lambda o: o["created_at"], reverse=True)
        base_cents = int(issued[0]["proposed_rent_cents"])
    else:
        cap = int(policy["effective_cap_bps"])
        base_decimal = Decimal(int(lease["monthly_rent_cents"])) * (
            Decimal(1) + Decimal(cap) / Decimal(10000))
        base_cents = round_half_up_int(base_decimal)

    premium_decimal = Decimal(base_cents) * (
        Decimal(1) + Decimal(MTM_PREMIUM_BPS) / Decimal(10000))
    return round_half_up_int(premium_decimal)


def concession_bps_for(proposed_rent_cents: int, requested_rent_cents: int) -> int:
    if int(proposed_rent_cents) <= 0:
        return 0
    diff = Decimal(int(proposed_rent_cents)) - Decimal(int(requested_rent_cents))
    ratio = diff / Decimal(int(proposed_rent_cents)) * Decimal(10000)
    return round_half_up_int(ratio)


def compute_retention_metrics(property_id: str, cohort_start: date, cohort_end: date,
                              variant: str) -> dict:
    """Cohort + retained/lost/mtm/pending counts per §3.8."""
    cohort_lease_ids = set()
    # Leases with term_end_date in window
    for l in store.leases.values():
        if l["property_id"] != property_id:
            continue
        if not l.get("term_end_date"):
            continue
        te = parse_date(l["term_end_date"])
        if cohort_start <= te <= cohort_end:
            cohort_lease_ids.add(l["id"])
    # Leases with a COUNTERSIGNED-or-RESCINDED doc (reached countersign) whose prior_term_end_date in window
    for d in store.renewal_documents.values():
        if d["lease_id"] is None:
            continue
        if d["status"] not in ("COUNTERSIGNED", "RESCINDED"):
            continue
        prior_end = d.get("prior_term_end_date")
        if not prior_end:
            continue
        lease = store.leases.get(d["lease_id"])
        if lease is None or lease["property_id"] != property_id:
            continue
        pe = parse_date(prior_end)
        if cohort_start <= pe <= cohort_end:
            cohort_lease_ids.add(lease["id"])

    cohort_size = len(cohort_lease_ids)

    def doc_currently_countersigned_in_window(lease_id):
        for d in store.renewal_documents.values():
            if d["lease_id"] != lease_id:
                continue
            if d["status"] != "COUNTERSIGNED":
                continue
            prior_end = d.get("prior_term_end_date")
            if not prior_end:
                continue
            pe = parse_date(prior_end)
            if cohort_start <= pe <= cohort_end:
                return True
        return False

    def has_accepted_offer(lease_id):
        for o in store.renewal_offers.values():
            if o["lease_id"] == lease_id and o["status"] == "ACCEPTED":
                return True
        return False

    def has_open_offer(lease_id):
        for o in store.renewal_offers.values():
            if o["lease_id"] == lease_id and o["status"] in OPEN_OFFER_STATUSES:
                return True
        return False

    def has_executed_renewal(lease_id):
        # a document that reached COUNTERSIGNED (status COUNTERSIGNED) and not rescinded
        for d in store.renewal_documents.values():
            if d["lease_id"] == lease_id and d["status"] == "COUNTERSIGNED":
                return True
        return False

    trailing_retained = 0
    pipeline_retained = 0
    mtm_count = 0
    lost_count = 0
    pending_count = 0

    for lid in cohort_lease_ids:
        lease = store.leases[lid]
        is_trailing = doc_currently_countersigned_in_window(lid)
        if is_trailing:
            trailing_retained += 1
        is_mtm = lease["status"] == "MTM"
        if is_mtm:
            mtm_count += 1
        # lost: ENDED without executed renewal
        if lease["status"] == "ENDED" and not has_executed_renewal(lid):
            lost_count += 1
        # pending: open offer not accepted
        has_open_not_accepted = False
        for o in store.renewal_offers.values():
            if o["lease_id"] == lid and o["status"] in ("DRAFT", "ISSUED", "COUNTERED"):
                has_open_not_accepted = True
                break
        if has_open_not_accepted:
            pending_count += 1
        # pipeline retained
        if is_trailing or has_accepted_offer(lid) or is_mtm:
            pipeline_retained += 1

    retained = trailing_retained if variant == "TRAILING" else pipeline_retained

    if cohort_size == 0:
        rate = None
    else:
        rate = round_half_up_int(Decimal(retained) / Decimal(cohort_size) * Decimal(10000))

    return {
        "cohort_size": cohort_size,
        "retained_count": retained,
        "mtm_count": mtm_count,
        "lost_count": lost_count,
        "pending_count": pending_count,
        "retention_rate_bps": rate,
        "variant": variant,
    }


def compute_expiration_forecast(property_id: str, months_ahead: int) -> dict:
    """Per-month committed and projected counts from current clock month."""
    from datetime import date as _date
    today = clock_date()
    start_month = _date(today.year, today.month, 1)

    months = []
    for i in range(months_ahead):
        m_start = add_months(start_month, i)
        key = month_key(m_start)
        committed = 0
        projected = 0
        for l in store.leases.values():
            if l["property_id"] != property_id:
                continue
            if l["status"] not in ("ACTIVE", "RENEWAL_PENDING", "NON_RENEWAL_NOTICED"):
                continue
            if not l.get("term_end_date"):
                continue
            if month_key(parse_date(l["term_end_date"])) == key:
                committed += 1
        for o in store.renewal_offers.values():
            if o["status"] not in OPEN_OFFER_STATUSES:
                continue
            o_lease = store.leases.get(o["lease_id"])
            if o_lease is None or o_lease["property_id"] != property_id:
                continue
            pend = offer_projected_end(o, o_lease)
            if month_key(pend) == key:
                projected += 1
        months.append({
            "month": m_start.strftime("%Y-%m"),
            "committed": committed,
            "projected": projected,
        })
    return {
        "window_start": start_month.strftime("%Y-%m-%d"),
        "months": months,
    }
