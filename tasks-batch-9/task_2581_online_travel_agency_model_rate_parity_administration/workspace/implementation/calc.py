"""All nine calculations (PRD section 3) with pinned rounding and evaluation order."""
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

import clock
from store import created_key, db

# ---- offer_sell_price ----
MAX_MARKUP_PCT = Decimal("0.5")
# ---- parity_breach_bps ----
PARITY_TOLERANCE_BPS = 100
PARITY_MAJOR_BPS = 300
PARITY_SEVERE_BPS = 800
PARITY_MAX_NOTIFY_ROUNDS = 3
# ---- package_pricing_and_allocation ----
OPAQUE_DISCOUNT_TIERS = [
    (0, Decimal("0.00")),
    (100000, Decimal("0.06")),
    (300000, Decimal("0.09")),
    (600000, Decimal("0.12")),
]
MIN_COMPONENTS = 2
# ---- refund_passthrough_due ----
ARRIVAL_HOUR_UTC = 15
MODERATE_SECOND_BAND_HOURS = 24
# ---- dispute_settlement_total ----
MEDIATION_FEE_BASE_CENTS = 2500
MEDIATION_FEE_TIERS = [
    (0, Decimal("0.020")),
    (50000, Decimal("0.035")),
    (200000, Decimal("0.050")),
]
DISPUTE_MAX_ROUNDS = 3
# ---- supplier_composite_score ----
PARITY_PENALTY_PER_POINT = 8
PROJECTED_ESCALATION_POINTS = 1
W_PARITY_SC = Decimal("0.30")
W_CONTENT_SC = Decimal("0.25")
W_CONNECTIVITY_SC = Decimal("0.20")
W_DISPUTE_SC = Decimal("0.25")
SEVERITY_WEIGHT = {"MINOR": 1, "MAJOR": 2, "SEVERE": 4}
# ---- ranking_score ----
W_PRICE = Decimal("0.40")
W_CONTENT = Decimal("0.25")
W_PARITY = Decimal("0.20")
W_CONVERSION = Decimal("0.15")
BOOST_CAP_POINTS = 15
PARITY_HEALTH_PENALTY = 10
# ---- certification / horizon ----
CERT_VALID_DAYS = 365
PROVISIONAL_VALID_DAYS = 90
CERT_MAX_REMEDIATION_ROUNDS = 3
MAX_HORIZON_DAYS = 500
OPEN_ENDED = "9999-12-31"

PARITY_NON_TERMINAL = ("OPEN", "SUPPLIER_NOTIFIED", "SUPPLIER_RESPONDED")
PARITY_OPEN_OR_ESCALATED = ("OPEN", "SUPPLIER_NOTIFIED", "SUPPLIER_RESPONDED", "ESCALATED")
PARITY_TERMINAL = ("RESOLVED_COMPLIANT", "WAIVED")


def D(value):
    return Decimal(str(value))


def rhu(value):
    """round_half_up to an integer."""
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu2(value):
    """round_half_up to 2 decimal places, returned as a JSON-safe float."""
    return float(D(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def q2(value):
    return D(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def ceil_int(value):
    return int(D(value).to_integral_value(rounding=ROUND_CEILING))


def floor_int(value):
    return int(D(value).to_integral_value(rounding=ROUND_FLOOR))


def num(value):
    """Normalise a Decimal for JSON output."""
    if isinstance(value, Decimal):
        as_int = int(value)
        return as_int if value == as_int else float(value)
    return value


# ---------------------------------------------------------------- agreements ---
def agreement_window_covers(agreement, day):
    end = agreement.get("effective_to") or OPEN_ENDED
    return agreement["effective_from"] <= day <= end


def active_agreement_for_date(supplier_id, day):
    """The ACTIVE ModelAgreement whose closed window covers `day` (windows are disjoint)."""
    for row in db["model_agreements"].values():
        if row["supplier_id"] != supplier_id or row["status"] != "ACTIVE":
            continue
        if agreement_window_covers(row, day):
            return row
    return None


def latest_activated_active_agreement(supplier_id):
    best = None
    for row in db["model_agreements"].values():
        if row["supplier_id"] != supplier_id or row["status"] != "ACTIVE":
            continue
        if best is None:
            best = row
            continue
        if (row.get("activated_at") or "") > (best.get("activated_at") or ""):
            best = row
        elif (row.get("activated_at") or "") == (best.get("activated_at") or "") \
                and created_key(row) < created_key(best):
            best = row
    return best


def binding_agreement_for_travel_date(supplier_id, travel_date):
    for row in db["model_agreements"].values():
        if row["supplier_id"] != supplier_id:
            continue
        if row["status"] not in ("ACTIVE", "SUPERSEDED", "TERMINATED"):
            continue
        if agreement_window_covers(row, travel_date):
            return row
    return None


def _override_compatible(override_type, model):
    if override_type == "COMMISSION_PCT":
        return model == "AGENCY"
    if override_type == "MARKUP_PCT":
        return model == "MERCHANT"
    return True  # FLAT_FEE_CENTS works with either model


def select_override(supplier_id, rate_plan_id, travel_date, model):
    candidates = []
    for row in db["overrides"].values():
        if row["status"] != "ACTIVE" or row["supplier_id"] != supplier_id:
            continue
        if row["rate_plan_id"] is not None and row["rate_plan_id"] != rate_plan_id:
            continue
        if not (row["effective_from"] <= travel_date <= row["effective_to"]):
            continue
        if not _override_compatible(row["override_type"], model):
            continue
        candidates.append(row)
    if not candidates:
        return None
    candidates.sort(key=lambda r: (
        0 if r["rate_plan_id"] is not None else 1,   # plan-scoped ranks above supplier-wide
        -D(r["value"]),                              # higher value first
        created_key(r),                              # earliest created_at wins; id never consulted
    ))
    return candidates[0]


# ------------------------------------------------------- offer_sell_price -----
def price_offer(plan, agreement, travel_date, net_rate_cents):
    model = agreement["model"]
    winner = select_override(plan["supplier_id"], plan["id"], travel_date, model)
    if winner is None:
        applied_override_id = None
        rate = D(agreement["base_markup_pct"] if model == "MERCHANT" else agreement["base_commission_pct"])
        applied_rate_pct = agreement["base_markup_pct"] if model == "MERCHANT" else agreement["base_commission_pct"]
        eff_type = "MARKUP_PCT" if model == "MERCHANT" else "COMMISSION_PCT"
    else:
        applied_override_id = winner["id"]
        rate = D(winner["value"])
        applied_rate_pct = winner["value"]
        eff_type = winner["override_type"]

    net = D(net_rate_cents)
    if model == "MERCHANT":
        if eff_type == "FLAT_FEE_CENTS":
            gross_cents = int(net_rate_cents) + int(rate)
        else:
            gross_cents = ceil_int(net / (Decimal(1) - rate))
        margin_cents = gross_cents - int(net_rate_cents)
    else:
        gross_cents = int(net_rate_cents)
        if eff_type == "FLAT_FEE_CENTS":
            margin_cents = int(rate)
        else:
            margin_cents = rhu(net * rate)
    taxes_fees_cents = rhu(D(gross_cents) * D(plan["tax_fee_pct"]))
    return {
        "pricing_model": model,
        "applied_rate_pct": applied_rate_pct,
        "applied_override_id": applied_override_id,
        "gross_cents": gross_cents,
        "taxes_fees_cents": taxes_fees_cents,
        "display_total_cents": gross_cents + taxes_fees_cents,
        "marketplace_margin_cents": margin_cents,
        "supplier_payable_cents": gross_cents - margin_cents,
    }


# ------------------------------------------------------- parity_breach_bps ----
def severity_for_bps(breach_bps):
    if breach_bps < PARITY_TOLERANCE_BPS:
        return "NONE"
    if breach_bps < PARITY_MAJOR_BPS:
        return "MINOR"
    if breach_bps < PARITY_SEVERE_BPS:
        return "MAJOR"
    return "SEVERE"


def breach_bps_for(display_total_cents, direct_total_cents):
    return rhu((D(display_total_cents) - D(direct_total_cents)) * 10000 / D(direct_total_cents))


def compared_live_offer(rate_plan_id, travel_date):
    best = None
    for row in db["offers"].values():
        if row["rate_plan_id"] != rate_plan_id or row["travel_date"] != travel_date:
            continue
        if row["status"] != "LIVE":
            continue
        if best is None or created_key(row) > created_key(best):
            best = row  # latest created_at wins
    return best


# ------------------------------------------- package_pricing_and_allocation ----
def discount_tier_for(subtotal_cents):
    pct = OPAQUE_DISCOUNT_TIERS[0][1]
    for threshold, value in OPAQUE_DISCOUNT_TIERS:
        if subtotal_cents >= threshold:
            pct = value
    return pct


def price_package(pairs):
    """pairs: list of (component_row, offer_row). Returns (package_fields, [(component, alloc)])."""
    ordered = sorted(pairs, key=lambda pair: created_key(pair[1]))
    snapshots = [int(offer["display_total_cents"]) for _c, offer in ordered]
    subtotal = sum(snapshots)
    pct = discount_tier_for(subtotal)
    discount_cents = floor_int(D(subtotal) * pct)
    floors = []
    fracs = []
    for snapshot in snapshots:
        raw = D(snapshot) * pct
        low = floor_int(raw)
        floors.append(low)
        fracs.append(raw - D(low))
    remainder = discount_cents - sum(floors)
    order = sorted(range(len(ordered)), key=lambda i: (-fracs[i], i))
    extra = set(order[:remainder]) if remainder > 0 else set()
    allocations = []
    for index, (component, _offer) in enumerate(ordered):
        alloc = floors[index] + (1 if index in extra else 0)
        allocations.append((component, {
            "display_total_snapshot_cents": snapshots[index],
            "discount_alloc_cents": alloc,
            "allocated_cents": snapshots[index] - alloc,
        }))
    package_fields = {
        "components_subtotal_cents": subtotal,
        "discount_pct": num(pct),
        "discount_cents": discount_cents,
        "package_total_cents": subtotal - discount_cents,
    }
    return package_fields, allocations


# ------------------------------------------------- refund_passthrough_due -----
def hours_to_arrival(arrival_at, now):
    arrival = clock.parse_instant(arrival_at)
    delta = arrival - now
    seconds = D(delta.days) * 86400 + D(delta.seconds) + D(delta.microseconds) / D(1000000)
    return seconds / D(3600)


def refund_pct_for(policy, hours, cutoff_hours):
    cutoff = D(cutoff_hours)
    if policy == "FLEX":
        return Decimal("1.00") if hours >= cutoff else Decimal("0.50")
    if policy == "MODERATE":
        if hours >= cutoff:
            return Decimal("1.00")
        return Decimal("0.50") if hours >= D(MODERATE_SECOND_BAND_HOURS) else Decimal("0.00")
    if policy == "STRICT":
        return Decimal("0.50") if hours >= cutoff else Decimal("0.00")
    return Decimal("0.00")  # NON_REF


def refund_breakdown(booking, refund_pct):
    refund_cents = rhu(D(booking["charged_total_cents"]) * refund_pct)
    clawback_cents = rhu(D(booking["marketplace_margin_cents"]) * refund_pct)
    supplier_debit_cents = rhu(D(booking["supplier_payable_cents"]) * refund_pct)
    tax_refund_cents = refund_cents - clawback_cents - supplier_debit_cents
    return {
        "refund_cents": refund_cents,
        "clawback_cents": clawback_cents,
        "supplier_debit_cents": supplier_debit_cents,
        "tax_refund_cents": tax_refund_cents,
    }


# ------------------------------------------------- dispute_settlement_total ---
def settlement_for(claim_cents, charged_total_cents, refunded_cents):
    refund_due_cents = min(int(claim_cents), int(charged_total_cents) - int(refunded_cents))
    fee_pct = MEDIATION_FEE_TIERS[0][1]
    for threshold, value in MEDIATION_FEE_TIERS:
        if refund_due_cents >= threshold:
            fee_pct = value
    mediation_fee_cents = MEDIATION_FEE_BASE_CENTS + rhu(D(refund_due_cents) * fee_pct)
    return {
        "refund_due_cents": refund_due_cents,
        "mediation_fee_pct": num(fee_pct),
        "mediation_fee_cents": mediation_fee_cents,
        "settlement_total_cents": refund_due_cents + mediation_fee_cents,
    }


def preliminary_split(settlement_total_cents, filing_agreement):
    pct = D(filing_agreement["chargeback_liability_pct_marketplace"]) if filing_agreement else Decimal(0)
    marketplace = rhu(D(settlement_total_cents) * pct)
    return marketplace, int(settlement_total_cents) - marketplace


def binding_split(settlement_total_cents, binding_agreement, outcome, dispute_type):
    if outcome == "SUPPLIER_LIABLE":
        eff_pct = Decimal("0.00")
    elif outcome == "MARKETPLACE_LIABLE":
        eff_pct = Decimal("1.00")
    elif outcome == "SPLIT":
        eff_pct = D(binding_agreement["chargeback_liability_pct_marketplace"]) if binding_agreement else Decimal(0)
    else:  # REVERSE_REFUND
        eff_pct = Decimal("0.00")
    uncapped = rhu(D(settlement_total_cents) * eff_pct)
    if dispute_type == "FRAUD" and binding_agreement is not None:
        marketplace = min(uncapped, int(binding_agreement["fraud_liability_cap_cents"]))
    else:
        marketplace = uncapped
    return uncapped, marketplace, int(settlement_total_cents) - marketplace


# ------------------------------------------------ supplier_composite_score ----
def _in_period(row, period_start, period_end):
    day = row["created_at"][:10]
    return period_start <= day <= period_end


def supplier_plan_ids(supplier_id):
    return {row["id"] for row in db["rate_plans"].values() if row["supplier_id"] == supplier_id}


def composite_score(supplier, period_start, period_end, variant):
    plan_ids = supplier_plan_ids(supplier["id"])
    cases = [row for row in db["parity_cases"].values()
             if row["rate_plan_id"] in plan_ids and _in_period(row, period_start, period_end)]
    points = 0
    counted = 0
    if variant == "PROVISIONAL":
        for case in cases:
            counted += 1
            points += SEVERITY_WEIGHT.get(case["severity"], 0)
            if case["status"] in PARITY_NON_TERMINAL:
                points += PROJECTED_ESCALATION_POINTS
    else:
        for case in cases:
            if case["status"] not in ("RESOLVED_COMPLIANT", "WAIVED", "ESCALATED"):
                continue
            counted += 1
            if case["status"] == "WAIVED":
                continue
            points += SEVERITY_WEIGHT.get(case["severity"], 0)

    parity_component = max(Decimal(0), Decimal(100) - D(PARITY_PENALTY_PER_POINT) * D(points))
    content_component = D(supplier["content_score"])
    connectivity_component = D(supplier["connectivity_score"])

    disputes = [row for row in db["disputes"].values()
                if row["supplier_id"] == supplier["id"] and _in_period(row, period_start, period_end)]
    if variant == "FINAL":
        disputes = [row for row in disputes if row["status"] == "RESOLVED"]
    gross_disputed = 0
    supplier_liable = 0
    for row in disputes:
        gross_disputed += int(row["settlement_total_cents"])
        if variant == "PROVISIONAL":
            supplier_liable += int(row["preliminary_supplier_cents"] or 0)
        else:
            supplier_liable += int(row["binding_supplier_cents"] or 0)
    share = rhu(D(100) * D(supplier_liable) / D(max(1, gross_disputed)))
    dispute_component = Decimal(100) - D(min(100, share))

    composite = (W_PARITY_SC * parity_component
                 + W_CONTENT_SC * content_component
                 + W_CONNECTIVITY_SC * connectivity_component
                 + W_DISPUTE_SC * dispute_component)
    return {
        "parity_penalty_points": points,
        "parity_component": num(parity_component),
        "content_component": num(content_component),
        "connectivity_component": num(connectivity_component),
        "dispute_component": num(dispute_component),
        "composite_score": rhu2(composite),
        "cases_counted": counted,
    }


# ------------------------------------------------------------ ranking_score ---
def parity_health_for(supplier_id):
    plan_ids = supplier_plan_ids(supplier_id)
    open_cases = sum(1 for row in db["parity_cases"].values()
                     if row["rate_plan_id"] in plan_ids and row["status"] in PARITY_OPEN_OR_ESCALATED)
    return max(Decimal(0), Decimal(100) - D(PARITY_HEALTH_PENALTY) * D(open_cases))


def placement_agreements_for(supplier_id, market_id, travel_date):
    rows = []
    for row in db["placements"].values():
        if row["supplier_id"] != supplier_id or row["market_id"] != market_id:
            continue
        if row["status"] != "ACTIVE":
            continue
        if row["window_start"] <= travel_date < row["window_end"]:  # half-open
            rows.append(row)
    return rows


def rank_entries(candidates, market_id, travel_date):
    """candidates: list of (offer, rate_plan, supplier). Returns ordered list of entry field dicts."""
    min_display = min(int(offer["display_total_cents"]) for offer, _p, _s in candidates)
    rows = []
    for offer, _plan, supplier in candidates:
        price_competitiveness = q2(
            D(100) * (Decimal(1) - (D(offer["display_total_cents"]) - D(min_display)) / D(min_display)))
        parity_health = parity_health_for(supplier["id"])
        organic = q2(W_PRICE * price_competitiveness
                     + W_CONTENT * D(supplier["content_score"])
                     + W_PARITY * parity_health
                     + W_CONVERSION * D(supplier["conversion_index"]))
        agreements = placement_agreements_for(supplier["id"], market_id, travel_date)
        boost = min(BOOST_CAP_POINTS, sum(int(a["boost_points"]) for a in agreements))
        winning = None
        for agreement in agreements:
            if winning is None:
                winning = agreement
            elif int(agreement["boost_points"]) > int(winning["boost_points"]):
                winning = agreement
            elif int(agreement["boost_points"]) == int(winning["boost_points"]) \
                    and created_key(agreement) < created_key(winning):
                winning = agreement
        is_paid = boost > 0
        rows.append({
            "offer_id": offer["id"],
            "placement_agreement_id": winning["id"] if (is_paid and winning) else None,
            "price_competitiveness": num(price_competitiveness),
            "organic_score": num(organic),
            "boost_points_applied": boost,
            "final_score": num(q2(organic + D(boost))),
            "is_paid_placement": is_paid,
            "disclosure_label": winning["disclosure_label"] if is_paid else "ORGANIC",
            "_offer_key": created_key(offer),
            "_final": q2(organic + D(boost)),
            "_organic": organic,
        })
    rows.sort(key=lambda r: (-r["_final"], -r["_organic"], r["_offer_key"]))
    for index, row in enumerate(rows, start=1):
        row["rank_position"] = index
        row.pop("_offer_key")
        row.pop("_final")
        row.pop("_organic")
    return rows


# ----------------------------------------------------- placement_slot_capacity -
def placement_capacity_ok(candidate, market):
    day = clock.parse_date(candidate["window_start"])
    end = clock.parse_date(candidate["window_end"])
    capacity = int(market["paid_slot_capacity"])
    while day < end:  # window_end itself is excluded
        iso_day = day.isoformat()
        used = 0
        for row in db["placements"].values():
            if row["id"] == candidate["id"] or row["status"] != "ACTIVE":
                continue
            if row["market_id"] != candidate["market_id"]:
                continue
            if row["window_start"] <= iso_day < row["window_end"]:
                used += int(row["slots"])
        if used + int(candidate["slots"]) > capacity:
            return False
        day = clock.plus_days(day, 1)
    return True
