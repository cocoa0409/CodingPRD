"""Every calculation of PRD sections 3.3 - 3.9, with the pinned rounding orders."""
from decimal import Decimal

from core import ceil_div, dq
from db import ordered, store

D = Decimal

# --- cost allocation constants (PRD 3.6) ---------------------------------
INLAND_ORIGIN_PER_UNIT = D("42.00")
INLAND_DEST_PER_UNIT = D("55.00")
EXPORT_CLEARANCE_FLAT = D("180.00")
THC_ORIGIN_FLAT = D("320.00")
THC_DEST_FLAT = D("295.00")
MIN_OCEAN_FREIGHT = D("450.00")
MIN_MARINE_PREMIUM = D("75.00")
MARINE_INSURANCE_RATE_PCT = D("0.35")
INSURANCE_COVER_FACTOR = D("1.10")
IMPORT_DUTY_PCT = D("6.50")
ZONE_MULTIPLIER = {"ZONE_1": D("1.00"), "ZONE_2": D("1.15"), "ZONE_3": D("1.35")}
CONTAINER_MIN_KG = {"LCL": D("0"), "DRY_20": D("8000"), "DRY_40": D("15000"),
                    "REEFER_40": D("12000")}
SELLER_BUCKETS = {
    "EXW": set(),
    "FCA": {1, 2},
    "FOB": {1, 2, 3},
    "CFR": {1, 2, 3, 4},
    "CIF": {1, 2, 3, 4, 5},
    "DAP": {1, 2, 3, 4, 5, 6, 7},
    "DDP": {1, 2, 3, 4, 5, 6, 7, 8},
}
MAX_LINES = 50

# --- risk scoring constants (PRD 3.4 / 3.7) ------------------------------
SEVERITY_WEIGHT = {"CRITICAL": D("40"), "MAJOR": D("15"), "MINOR": D("5")}
AMOUNT_CLAUSES = {"AMOUNT", "EXPIRY", "LATEST_SHIPMENT"}
RISK_ACCEPT_CEILING = D("45.00")
RISK_REJECT_FLOOR = D("60.00")
RISK_CEILING = D("100.00")
MAX_CURE_ROUNDS = 3

# --- drawing constants (PRD 3.7) -----------------------------------------
PARTIAL_UNDERDRAW_PCT = D("5.00")
MIN_NEGOTIATION_FEE = D("150.00")
NEGOTIATION_FEE_PCT = D("0.125")
USANCE_DISCOUNT_RATE_PCT = D("4.75")
USANCE_DAY_BASIS = D("360")
MIN_USANCE_DAYS = 30

# --- insurance constants (PRD 3.8) ---------------------------------------
TIER_1_CEILING = D("250000.00")
TIER_2_CEILING = D("1000000.00")
TIER_RATE_PCT = {"TIER_1": D("0.85"), "TIER_2": D("1.15"), "TIER_3": D("1.60")}
RATING_MULTIPLIER = {"AAA": D("0.80"), "AA": D("0.85"), "A": D("0.90"),
                     "BBB": D("1.00"), "BB": D("1.20"), "B": D("1.45"),
                     "CCC": D("1.80")}
POLICY_FEE_MIN = D("250.00")
POLICY_FEE_PCT = D("0.10")
FEE_WAIVER_DEDUCTIBLE = D("5000.00")

# --- misc ---------------------------------------------------------------
DOC_BUFFER_HOURS = 24
LICENSE_UTILISATION_WARN_PCT = D("90.00")
MAX_NEGOTIATION_ROUNDS = 3

LIVE_BOOKING_STATES = ("BOOKED", "CONFIRMED", "SHIPPED")
SHIPPED_FULFILLMENT = ("SHIPPED", "SHORT_SHIPPED", "CLOSED")


# =========================================================================
# lines and order values
# =========================================================================
def order_lines(order_id):
    rows = [r for r in store.shipment_lines.values() if r["export_order_id"] == order_id]
    return sorted(rows, key=lambda r: r["line_no"])


def ordered_goods_value(order_id):
    total = D("0.00")
    for line in order_lines(order_id):
        total += dq(line["quantity"] * line["unit_price_usd"], 2)
    return dq(total, 2)


def shipped_goods_value(order_id):
    total = D("0.00")
    for line in order_lines(order_id):
        total += dq(line["shipped_quantity"] * line["unit_price_usd"], 2)
    return dq(total, 2)


def billable_quantity(order, line):
    if order["fulfillment_status"] in SHIPPED_FULFILLMENT:
        return line["shipped_quantity"]
    return line["quantity"]


def live_booking(order_id):
    rows = [b for b in ordered(store.bookings)
            if b["export_order_id"] == order_id and b["status"] in LIVE_BOOKING_STATES]
    return rows[-1] if rows else None


# =========================================================================
# incoterm cost allocation (PRD 3.6)
# =========================================================================
def _weight_basis(order, variant):
    booking = live_booking(order["id"])
    if booking is None:
        return D("0.000"), None
    total = D("0.000")
    if variant == "provisional":
        for line in order_lines(order["id"]):
            if line["quantity"] > 0:
                total += line["gross_weight_kg"]
    else:
        for line in order_lines(order["id"]):
            if line["shipped_quantity"] > 0 and line["quantity"] > 0:
                total += dq(line["gross_weight_kg"] * line["shipped_quantity"]
                            / line["quantity"], 3)
    return dq(total, 3), booking


def cost_allocation(order, variant):
    """Returns (buckets dict keyed 1..8, seller_total, buyer_total)."""
    weight_basis, booking = _weight_basis(order, variant)
    if variant == "provisional":
        value_basis = order["ordered_goods_value_usd"]
    else:
        value_basis = order["shipped_goods_value_usd"]

    container_min = D("0")
    tariff = D("0.00")
    if booking is not None:
        container_min = CONTAINER_MIN_KG[booking["container_type"]]
        sailing = store.sailings.get(booking["vessel_sailing_id"])
        if sailing is not None:
            tariff = sailing["tariff_rate_per_1000kg_usd"]
    chargeable = weight_basis if weight_basis > container_min else container_min
    units = D(ceil_div(chargeable, 1000))
    zone = ZONE_MULTIPLIER[order["destination_zone"]]

    buckets = {}
    buckets[1] = dq(INLAND_ORIGIN_PER_UNIT * units, 2)
    buckets[2] = dq(EXPORT_CLEARANCE_FLAT, 2)
    buckets[3] = dq(THC_ORIGIN_FLAT, 2)
    main = dq(tariff * zone * units, 2)
    buckets[4] = main if main > MIN_OCEAN_FREIGHT else MIN_OCEAN_FREIGHT
    premium = dq(value_basis * MARINE_INSURANCE_RATE_PCT / D(100)
                 * INSURANCE_COVER_FACTOR, 2)
    buckets[5] = premium if premium > MIN_MARINE_PREMIUM else MIN_MARINE_PREMIUM
    buckets[6] = dq(THC_DEST_FLAT, 2)
    buckets[7] = dq(INLAND_DEST_PER_UNIT * units, 2)
    buckets[8] = dq(value_basis * IMPORT_DUTY_PCT / D(100), 2)

    seller_keys = SELLER_BUCKETS[order["incoterm"]]
    seller = D("0.00")
    buyer = D("0.00")
    for key in range(1, 9):
        if key in seller_keys:
            seller += buckets[key]
        else:
            buyer += buckets[key]
    return buckets, dq(seller, 2), dq(buyer, 2)


def seller_owns(order, bucket_key):
    return bucket_key in SELLER_BUCKETS[order["incoterm"]]


# =========================================================================
# invoice totalling chain (PRD 3.5)
# =========================================================================
def invoice_chain(order, persist=False):
    """Returns (declared_total_usd, declared_total_invoice_currency, shares)."""
    variant = "final" if order["fulfillment_status"] in SHIPPED_FULFILLMENT \
        else "provisional"
    buckets, _seller, _buyer = cost_allocation(order, variant)
    pool = buckets[4] if seller_owns(order, 4) else D("0.00")
    addend = buckets[5] if seller_owns(order, 5) else D("0.00")

    rows = []
    subtotal = D("0.00")
    for line in order_lines(order["id"]):
        qty = billable_quantity(order, line)
        extended = dq(qty * line["unit_price_usd"], 2)
        discount = dq(extended * line["line_discount_pct"] / D(100), 2)
        net = dq(extended - discount, 2)
        if qty <= 0:
            rows.append((line, D("0.00"), D("0.00"), False))
            continue
        rows.append((line, extended, net, True))
        subtotal += net
    subtotal = dq(subtotal, 2)

    shares = {}
    included = [r for r in rows if r[3]]
    assigned = D("0.00")
    for line, _extended, net, _ok in included:
        share = D("0.00") if subtotal == 0 else dq(pool * net / subtotal, 2)
        shares[line["id"]] = share
        assigned += share
    if included:
        residual = dq(pool - assigned, 2)
        if residual != 0:
            sink = sorted(included, key=lambda r: (-r[2], r[0]["line_no"]))[0][0]
            shares[sink["id"]] = dq(shares[sink["id"]] + residual, 2)
    for line, _extended, net, ok in rows:
        if not ok:
            shares[line["id"]] = D("0.00")

    declared = dq(subtotal + pool + addend, 2)
    invoice_currency = dq(declared * order["fx_rate_usd_to_invoice"], 2)

    if persist:
        for line, extended, net, _ok in rows:
            line["line_extended_usd"] = extended
            line["line_net_usd"] = net
            line["apportioned_freight_usd"] = shares[line["id"]]
    return declared, invoice_currency, shares


# =========================================================================
# risk scoring (PRD 3.4 / 3.7)
# =========================================================================
def _contribution(finding, carryover):
    if finding["cure_status"] == "WAIVED":
        return D("0.00")
    weight = SEVERITY_WEIGHT[finding["severity"]]
    clause = D("1.5") if finding["clause_ref"] in AMOUNT_CLAUSES else D("1.0")
    return dq(weight * clause * carryover, 2)


def _sum_capped(pairs):
    total = D("0.00")
    for finding, carryover in sorted(pairs, key=lambda p: (p[0]["created_at"],
                                                           p[0]["_seq"])):
        total += _contribution(finding, carryover)
    total = dq(total, 2)
    return total if total < RISK_CEILING else RISK_CEILING


def terms_risk_score(review):
    pairs = []
    for finding in store.findings.values():
        if finding["source"] != "TERMS":
            continue
        if finding["lc_terms_review_id"] != review["id"]:
            continue
        if finding["cure_status"] not in ("OPEN", "CURED"):
            continue
        pairs.append((finding, D("1.0")))
    return _sum_capped(pairs)


def examination_risk_score(presentation, lc):
    round_no = presentation["presentation_round"]
    pairs = []
    for finding in store.findings.values():
        selected = False
        if finding["source"] == "DOCUMENT" and \
                finding["document_presentation_id"] == presentation["id"]:
            selected = True
        elif finding["source"] == "TERMS" and \
                finding["letter_of_credit_id"] == lc["id"] and \
                finding["cure_status"] == "OPEN":
            selected = True
        if not selected:
            continue
        if round_no >= 2 and finding["severity"] == "MINOR":
            continue
        raised = finding.get("raised_in_round") or 0
        carry = D("1.0") if raised == round_no else D("0.5")
        pairs.append((finding, carry))
    return _sum_capped(pairs)


def finding_count(review_id):
    return sum(1 for f in store.findings.values()
               if f["lc_terms_review_id"] == review_id)


def open_finding_count(presentation_id):
    return sum(1 for f in store.findings.values()
               if f["document_presentation_id"] == presentation_id
               and f["cure_status"] == "OPEN")


# =========================================================================
# drawing bounds and pricing (PRD 3.4 / 3.7)
# =========================================================================
def drawing_bounds(amount, tolerance_pct):
    upper = dq(amount * (D(1) + tolerance_pct / D(100)), 2)
    lower = dq(amount * (D(1) - tolerance_pct / D(100)), 2)
    return upper, lower


def effective_underdraw_floor(lc):
    if lc["partial_shipment_allowed"]:
        pct = lc["tolerance_pct"]
        if PARTIAL_UNDERDRAW_PCT > pct:
            pct = PARTIAL_UNDERDRAW_PCT
        return dq(lc["amount_usd"] * (D(1) - pct / D(100)), 2)
    return lc["min_drawable_usd"]


def price_drawing(presented, lc):
    gross = presented if presented < lc["max_drawable_usd"] else lc["max_drawable_usd"]
    fee = dq(gross * NEGOTIATION_FEE_PCT / D(100), 2)
    if fee < MIN_NEGOTIATION_FEE:
        fee = MIN_NEGOTIATION_FEE
    if lc["availability"] == "SIGHT":
        discount = D("0.00")
    else:
        discount = dq(gross * USANCE_DISCOUNT_RATE_PCT / D(100)
                      * D(lc["usance_days"]) / USANCE_DAY_BASIS, 2)
    net = dq(gross - fee - discount, 2)
    return net if net > 0 else D("0.00")


# =========================================================================
# insurance premium (PRD 3.8)
# =========================================================================
def price_premium(buyer, credit_limit, insured_pct, deductible, prior_exposure):
    basis = dq(prior_exposure + credit_limit, 2)
    if basis <= TIER_1_CEILING:
        tier = "TIER_1"
    elif basis <= TIER_2_CEILING:
        tier = "TIER_2"
    else:
        tier = "TIER_3"
    rate = TIER_RATE_PCT[tier]
    multiplier = RATING_MULTIPLIER[buyer["credit_rating"]]
    base = dq(credit_limit * insured_pct / D(100) * rate / D(100) * multiplier, 2)
    if tier == "TIER_1" and deductible >= FEE_WAIVER_DEDUCTIBLE:
        fee = D("0.00")
    else:
        fee = dq(credit_limit * POLICY_FEE_PCT / D(100), 2)
        if fee < POLICY_FEE_MIN:
            fee = POLICY_FEE_MIN
    return tier, dq(base + fee, 2)


# =========================================================================
# settlement waterfall (PRD 3.9)
# =========================================================================
def settlement_waterfall(settlement, order, policy):
    outstanding = order["outstanding_receivable_usd"]
    bucket1 = settlement if settlement < outstanding else outstanding
    bucket1 = dq(bucket1, 2)
    remainder = dq(settlement - bucket1, 2)
    if policy is not None:
        exposure = order["insured_exposure_usd"]
        covered = remainder if remainder < exposure else exposure
        cap = dq(policy["credit_limit_usd"] - policy["indemnified_total_usd"], 2)
        net_of_deductible = dq(covered - policy["deductible_usd"], 2)
        if net_of_deductible < 0:
            net_of_deductible = D("0.00")
        share = dq(net_of_deductible * policy["insured_pct"] / D(100), 2)
        bucket2 = remainder
        if cap < bucket2:
            bucket2 = cap
        if share < bucket2:
            bucket2 = share
        if bucket2 < 0:
            bucket2 = D("0.00")
        bucket2 = dq(bucket2, 2)
    else:
        bucket2 = D("0.00")
    bucket3 = dq(remainder - bucket2, 2)
    if bucket3 < 0:
        bucket3 = D("0.00")
    return bucket1, bucket2, bucket3
