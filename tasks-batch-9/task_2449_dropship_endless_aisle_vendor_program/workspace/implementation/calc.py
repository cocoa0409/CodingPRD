"""All business calculations (SCAFFOLD section 1.3 / PRD sections 2.7-2.10 and 3.x)."""

import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import db, now, touch

# ---------------------------------------------------------------- constants --

STALE_CADENCE_MULTIPLIER = 3
REVERSE_FREIGHT_FLAT_CENTS = 1295
CANCELLATION_PENALTY_CENTS = 500
DEFECT_ROUTING_MAX_DEFECT_RATE_BPS = 1500
MAX_FALLBACK_HOPS = 3
PROMISE_DEFAULT_PADDING_DAYS = 2

WEIGHT_ON_TIME = Decimal("0.50")
WEIGHT_CANCEL = Decimal("0.30")
WEIGHT_DEFECT = Decimal("0.20")

TIER_PADDING_DAYS = {
    "UNRATED": 2,
    "PLATINUM": 0,
    "GOLD": 1,
    "SILVER": 2,
    "WATCH": 3,
    "PROBATION": 5,
}

FEE_WAIVED_REASONS = ("DEFECTIVE", "NOT_AS_DESCRIBED", "LATE_DELIVERY")
VENDOR_FREIGHT_REASONS = ("DEFECTIVE", "NOT_AS_DESCRIBED")

OPEN_LINE_STATES = ("PENDING_TRANSMIT", "TRANSMITTED", "ACKNOWLEDGED", "BACKORDERED")

# ------------------------------------------------------------------ rounding --


def round_half_up(value, places=0):
    exp = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(exp, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(round_half_up(value, 0))


def rhu2(value):
    return float(round_half_up(value, 2))


def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(value)


# ------------------------------------------------------------ row selectors --


def vendor_of(item):
    return db.vendors.get(item["vendor_id"]) if item else None


def item_of(line):
    return db.items.get(line["item_id"]) if line else None


def vendor_of_line(line):
    item = item_of(line)
    return vendor_of(item) if item else None


def order_lines(order_id):
    rows = [l for l in db.lines.values() if l["order_id"] == order_id]
    return sorted(rows, key=lambda l: l["line_number"])


def line_returns(line_id):
    rows = [r for r in db.returns.values() if r["line_id"] == line_id]
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def order_returns(order_id):
    ids = set(l["id"] for l in order_lines(order_id))
    rows = [r for r in db.returns.values() if r["line_id"] in ids]
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def vendor_rules(vendor_id):
    rows = [r for r in db.rules.values() if r["vendor_id"] == vendor_id]
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def vendor_items(vendor_id):
    rows = [i for i in db.items.values() if i["vendor_id"] == vendor_id]
    return sorted(rows, key=lambda i: (i["created_at"], i["_seq"]))


def item_snapshots(item_id):
    rows = [s for s in db.snapshots.values() if s["item_id"] == item_id]
    return sorted(rows, key=lambda s: (s["created_at"], s["_seq"]))


def latest_published_scorecard(vendor_id):
    rows = [
        s for s in db.scorecards.values()
        if s["vendor_id"] == vendor_id and s["status"] == "PUBLISHED"
    ]
    if not rows:
        return None
    return max(rows, key=lambda s: (s["period_end"], s["created_at"], s["_seq"]))


def matching_rules(vendor_id, zone_code, ship_method):
    return [
        r for r in db.rules.values()
        if r["vendor_id"] == vendor_id
        and r["status"] == "ACTIVE"
        and r["zone_code"] == zone_code
        and r["ship_method"] == ship_method
    ]


def best_coverage_rule(vendor_id, zone_code, ship_method):
    """Smallest transit_days, tie-break smallest created_at."""
    rows = matching_rules(vendor_id, zone_code, ship_method)
    if not rows:
        return None
    return min(rows, key=lambda r: (r["transit_days"], r["created_at"], r["_seq"]))


def has_active_coverage(vendor_id, ship_method=None):
    for r in db.rules.values():
        if r["vendor_id"] != vendor_id or r["status"] != "ACTIVE":
            continue
        if ship_method is not None and r["ship_method"] != ship_method:
            continue
        return True
    return False


def blackout_covering(vendor_id, day):
    for b in db.blackouts.values():
        if (
            b["vendor_id"] == vendor_id
            and b["status"] == "ACTIVE"
            and b["start_date"] <= day <= b["end_date"]
        ):
            return b
    return None


def clock_date():
    return now().date()


# --------------------------------------------- available_to_promise_units --


def availability(item):
    """Re-derive the offer's availability view against the logical clock."""
    vendor = vendor_of(item)
    clock = now()

    candidates = [
        s for s in db.snapshots.values()
        if s["item_id"] == item["id"]
        and s["status"] == "ACTIVE"
        and s["effective_from"] <= clock
        and (s["effective_to"] is None or clock < s["effective_to"])
    ]
    snapshot = None
    if candidates:
        snapshot = max(
            candidates,
            key=lambda s: (s["effective_from"], s["created_at"], s["_seq"]),
        )

    cadence = vendor["inventory_refresh_cadence_minutes"] if vendor else 1440
    stale_limit = cadence * STALE_CADENCE_MULTIPLIER
    refreshed = item["last_inventory_refresh_at"]
    if refreshed is None:
        stale = True
    else:
        age_minutes = int((clock - refreshed).total_seconds() // 60)
        stale = age_minutes > stale_limit

    if snapshot is None or stale:
        effective_on_hand = 0
    else:
        effective_on_hand = snapshot["on_hand_units"]

    buffer_units = vendor["safety_buffer_units"] if vendor else 0
    grace_units = vendor["oversell_grace_units"] if vendor else 0
    atp = effective_on_hand - buffer_units + grace_units - item["reserved_units"]
    if atp < 0:
        atp = 0

    return {
        "effective_on_hand_units": effective_on_hand,
        "inventory_is_stale": stale,
        "available_units": atp if item["status"] == "ACTIVE" else 0,
        "atp_raw": atp,
    }


# ------------------------------------------------ unit cost / order totals --


def derive_unit_cost(item):
    vendor = vendor_of(item)
    if vendor is None:
        return 0
    if vendor["cost_model"] == "COMMISSION":
        rate = vendor["commission_rate_bps"] or 0
        return rhu_int(Decimal(item["unit_retail_cents"]) * (10000 - rate) / 10000)
    wholesale = item.get("unit_wholesale_cost_cents")
    if wholesale is None:
        return 0
    rate = vendor["wholesale_discount_bps"] or 0
    return rhu_int(Decimal(wholesale) * (10000 - rate) / 10000)


def order_totals(order):
    counted = [
        l for l in order_lines(order["id"])
        if l["status"] != "CANCELLED_BY_VENDOR"
    ]
    total_retail = sum(l["quantity"] * l["unit_retail_cents"] for l in counted)
    total_cost = sum(
        l["quantity"] * l["unit_cost_cents"] + l["surcharge_cents"] for l in counted
    )
    return total_retail, total_cost, total_retail - total_cost


def order_refunded_cents(order):
    total = 0
    for ra in order_returns(order["id"]):
        if ra["status"] in ("AUTHORIZED", "RECEIVED") and ra["refund_cents"]:
            total += ra["refund_cents"]
    return total


def order_retailer_absorbed_cents(order):
    total = 0
    for ra in order_returns(order["id"]):
        if ra["status"] in ("AUTHORIZED", "RECEIVED") and ra["routing_destination"] == "RETAILER_DC":
            total += REVERSE_FREIGHT_FLAT_CENTS
    return total


def line_returned_units(line):
    total = 0
    for ra in line_returns(line["id"]):
        if ra["status"] in ("AUTHORIZED", "RECEIVED"):
            total += ra["quantity_returned"]
    return total


# ------------------------------------------------------ order derived state --


def fulfillment_status(order):
    lines = order_lines(order["id"])
    if not lines:
        return "OPEN"
    cancelled = [l for l in lines if l["status"] == "CANCELLED_BY_VENDOR"]
    if len(cancelled) == len(lines):
        return "CANCELLED"
    open_lines = [l for l in lines if l["status"] in OPEN_LINE_STATES]
    shipped = [l for l in lines if l["status"] == "SHIPPED"]
    if not open_lines and shipped:
        return "SHIPPED"
    if shipped and open_lines:
        return "PARTIALLY_SHIPPED"
    return "OPEN"


def financial_status(order):
    lines = order_lines(order["id"])
    if lines and all(l["status"] == "CANCELLED_BY_VENDOR" for l in lines):
        return "REFUNDED"
    shipped = [l for l in lines if l["status"] == "SHIPPED"]
    if not shipped:
        return "PENDING"
    total_retail = order_totals(order)[0]
    refunded = order_refunded_cents(order)
    if refunded <= 0:
        return "CAPTURED"
    if refunded < total_retail:
        return "PARTIALLY_REFUNDED"
    return "REFUNDED"


def net_retail_cents(order):
    lines = order_lines(order["id"])
    if lines and all(l["status"] == "CANCELLED_BY_VENDOR" for l in lines):
        return 0
    return order_totals(order)[0] - order_refunded_cents(order)


def promise_variant_in_effect(order):
    for l in order_lines(order["id"]):
        if l["transmitted_at"] is not None:
            return "RECOMPUTED"
    return "QUOTED"


# ------------------------------------------------------ delivery promise --


def promise_date(item, order, variant, anchor):
    """Return the promise date, or None when no ACTIVE coverage row matches."""
    vendor = vendor_of(item)
    rule = best_coverage_rule(
        item["vendor_id"], order["customer_zone_code"], item["ship_method"]
    )
    if rule is None or vendor is None:
        return None

    base_date = anchor.date()
    rollover = 1 if anchor.hour >= rule["cutoff_hour_utc"] else 0

    if variant == "QUOTED":
        lead_days = item["lead_time_days"]
        padding_days = vendor["promise_padding_days"]
    else:
        scorecard = latest_published_scorecard(vendor["id"])
        if scorecard is not None and scorecard["avg_ship_hours"] is not None:
            lead_days = max(1, int(math.ceil(dec(scorecard["avg_ship_hours"]) / 24)))
        else:
            lead_days = item["lead_time_days"]
        padding_days = 0

    promise = base_date + timedelta(
        days=rollover + lead_days + rule["transit_days"] + padding_days
    )
    while blackout_covering(item["vendor_id"], promise) is not None:
        promise = promise + timedelta(days=1)
    return promise


def line_promise_date(line):
    if line.get("_recomputed_promise_date") is not None:
        return line["_recomputed_promise_date"]
    return line.get("_quoted_promise_date")


def refresh_order_promises(order):
    lines = [
        l for l in order_lines(order["id"])
        if l["status"] != "CANCELLED_BY_VENDOR"
    ]
    quoted = [l["_quoted_promise_date"] for l in lines if l.get("_quoted_promise_date")]
    if quoted:
        order["quoted_promise_date"] = max(quoted)
    recomputed = [
        l["_recomputed_promise_date"] for l in lines if l.get("_recomputed_promise_date")
    ]
    if recomputed:
        order["recomputed_promise_date"] = max(recomputed)


def promise_divergence_days(order):
    if order["recomputed_promise_date"] is None or order["quoted_promise_date"] is None:
        return 0
    return (order["quoted_promise_date"] - order["recomputed_promise_date"]).days


# --------------------------------------------------------- SLA deadlines --


def pin_deadlines(line, item, vendor):
    transmitted = line["transmitted_at"]
    line["ack_deadline_at"] = transmitted + timedelta(hours=vendor["ack_sla_hours"])
    line["ship_deadline_at"] = transmitted + timedelta(
        hours=item["lead_time_days"] * 24 + vendor["ship_sla_grace_hours"]
    )


def ack_sla_breached(line):
    deadline = line["ack_deadline_at"]
    if deadline is None:
        return False
    if line["acknowledged_at"] is not None and line["acknowledged_at"] > deadline:
        return True
    if line["status"] == "TRANSMITTED" and now() > deadline:
        return True
    return False


def ship_sla_breached(line):
    deadline = line["ship_deadline_at"]
    if deadline is None or line["shipped_at"] is None:
        return False
    return line["shipped_at"] > deadline


def ship_hours(line):
    delta = now() - line["transmitted_at"]
    return rhu2(dec(delta.total_seconds()) / Decimal(3600))


# ---------------------------------------------------------- transmission --


def transmit_line(line, item, vendor, order, rule):
    line["status"] = "TRANSMITTED"
    line["transmitted_at"] = now()
    line["transmit_attempt_count"] = line["transmit_attempt_count"] + 1
    line["unit_cost_cents"] = item["unit_cost_cents"]
    line["surcharge_cents"] = rule["surcharge_cents"]
    pin_deadlines(line, item, vendor)
    line["_recomputed_promise_date"] = promise_date(
        item, order, "RECOMPUTED", line["transmitted_at"]
    )
    touch(line)


# --------------------------------------------------- cancellation cascade --


def cancel_line_cascade(line):
    """The four-hop vendor cancellation cascade (PRD section 3.6)."""
    item = item_of(line)
    vendor = vendor_of(item)
    order = db.orders[line["order_id"]]

    # hop 1
    line["status"] = "CANCELLED_BY_VENDOR"
    touch(line)
    item["reserved_units"] = item["reserved_units"] - line["quantity"]
    item["lifetime_released_units"] = item["lifetime_released_units"] + line["quantity"]
    touch(item)

    # hop 2 (totals and fulfillment_status are derived on read)
    refresh_order_promises(order)
    touch(order)

    # hop 3 is the derived financial axis; hop 4 posts the penalty
    if fulfillment_status(order) == "CANCELLED" and vendor is not None:
        penalty = CANCELLATION_PENALTY_CENTS * len([
            l for l in order_lines(order["id"])
            if l["status"] == "CANCELLED_BY_VENDOR"
            and item_of(l) is not None
            and item_of(l)["vendor_id"] == vendor["id"]
        ])
        if penalty:
            post_chargeback(vendor, penalty)


# ------------------------------------------------------ settlement ledger --


def post_chargeback(vendor, amount):
    vendor["chargeback_balance_cents"] = vendor["chargeback_balance_cents"] + amount
    vendor["settlement_balance_cents"] = vendor["settlement_balance_cents"] - amount
    touch(vendor, bump=False)


def reverse_chargeback(vendor, amount):
    vendor["chargeback_balance_cents"] = vendor["chargeback_balance_cents"] - amount
    vendor["settlement_balance_cents"] = vendor["settlement_balance_cents"] + amount
    touch(vendor, bump=False)


def credit_settlement(vendor, amount):
    vendor["settlement_balance_cents"] = vendor["settlement_balance_cents"] + amount
    touch(vendor, bump=False)


# ------------------------------------------- suspension / reinstatement --


def suspension_cascade(vendor):
    """Four causally ordered hops shared by manual and probation suspension."""
    # hop 1
    for rule in vendor_rules(vendor["id"]):
        if rule["status"] == "ACTIVE":
            rule["status"] = "INACTIVE"
            rule["inactivated_by_suspension"] = True
            touch(rule)

    # hop 2
    suppressed = []
    for item in vendor_items(vendor["id"]):
        if item["status"] == "ACTIVE":
            item["status"] = "SUPPRESSED"
            item["suppression_reason"] = "VENDOR_SUSPENDED"
            touch(item)
            suppressed.append(item["id"])

    # hop 3
    affected_orders = []
    for line in sorted(db.lines.values(), key=lambda l: (l["created_at"], l["_seq"])):
        if line["item_id"] in suppressed and line["status"] == "PENDING_TRANSMIT":
            before = fulfillment_status(db.orders[line["order_id"]])
            line["status"] = "BACKORDERED"
            touch(line)
            affected_orders.append((line["order_id"], before))

    # hop 4
    seen = set()
    for order_id, before in affected_orders:
        if order_id in seen:
            continue
        seen.add(order_id)
        order = db.orders[order_id]
        if fulfillment_status(order) != before:
            touch(order)


def reinstate_cascade(vendor):
    for rule in vendor_rules(vendor["id"]):
        if rule["inactivated_by_suspension"]:
            rule["status"] = "ACTIVE"
            rule["inactivated_by_suspension"] = False
            touch(rule)
    for item in vendor_items(vendor["id"]):
        if item["status"] == "SUPPRESSED" and item["suppression_reason"] == "VENDOR_SUSPENDED":
            item["status"] = "ACTIVE"
            item["suppression_reason"] = None
            touch(item)


# ------------------------------------------------------- return routing --


def return_routing(ra, line):
    """SCAFFOLD calculations.return_routing_selection."""
    current = item_of(line)
    pool = [current]
    if current["fallback_item_id"]:
        fallback = db.items.get(current["fallback_item_id"])
        if fallback is not None:
            pool.append(fallback)
    pool = [c for c in pool if c["sku"] == current["sku"]]

    today = clock_date()
    eligible = []
    for candidate in pool:
        vendor = vendor_of(candidate)
        if vendor is None or vendor["onboarding_status"] != "ACTIVE":
            continue
        if blackout_covering(vendor["id"], today) is not None:
            continue
        scorecard = latest_published_scorecard(vendor["id"])
        if scorecard is not None and scorecard["defect_rate_bps"] is not None:
            if scorecard["defect_rate_bps"] > DEFECT_ROUTING_MAX_DEFECT_RATE_BPS:
                continue
        eligible.append(candidate)

    if not eligible:
        ra["routing_destination"] = "RETAILER_DC"
        ra["routed_vendor_id"] = None
        ra["restock_disposition"] = "RETAILER_RESTOCK"
        return None

    def rank(candidate):
        scorecard = latest_published_scorecard(candidate["vendor_id"])
        if scorecard is None or scorecard["defect_rate_bps"] is None:
            defect = 10000
        else:
            defect = scorecard["defect_rate_bps"]
        return (defect, candidate["unit_cost_cents"], candidate["created_at"], candidate["_seq"])

    winner = min(eligible, key=rank)
    ra["routing_destination"] = "VENDOR"
    ra["routed_vendor_id"] = winner["vendor_id"]
    ra["restock_disposition"] = winner["restock_policy"]
    return winner


def return_financials(ra, line):
    """SCAFFOLD calculations.return_financials - normative seven steps."""
    item = item_of(line)

    base = ra["quantity_returned"] * line["unit_retail_cents"]
    ra["refund_base_cents"] = base

    if base < 5000:
        fee_rate_bps = 0
    elif base < 20000:
        fee_rate_bps = 500
    else:
        fee_rate_bps = 1000

    if ra["reason_code"] in FEE_WAIVED_REASONS:
        ra["restocking_fee_cents"] = 0
    else:
        ra["restocking_fee_cents"] = rhu_int(Decimal(base) * fee_rate_bps / 10000)

    if ra["reason_code"] in VENDOR_FREIGHT_REASONS:
        ra["reverse_freight_owner"] = "VENDOR"
    else:
        ra["reverse_freight_owner"] = item["reverse_freight_owner"]

    if ra["reverse_freight_owner"] == "RETAILER" and ra["reason_code"] == "BUYER_REMORSE":
        ra["customer_freight_charge_cents"] = REVERSE_FREIGHT_FLAT_CENTS
    else:
        ra["customer_freight_charge_cents"] = 0

    ra["refund_cents"] = (
        ra["refund_base_cents"]
        - ra["restocking_fee_cents"]
        - ra["customer_freight_charge_cents"]
    )

    if ra["routing_destination"] == "RETAILER_DC":
        ra["vendor_chargeback_cents"] = 0
    else:
        chargeback = ra["quantity_returned"] * line["unit_cost_cents"]
        if ra["reverse_freight_owner"] == "VENDOR":
            chargeback += REVERSE_FREIGHT_FLAT_CENTS
        ra["vendor_chargeback_cents"] = chargeback


# -------------------------------------------------- retransmit selection --


def retransmit_target(line, order):
    """SCAFFOLD calculations.retransmit_target_selection; None when nothing is eligible."""
    current = item_of(line)
    visited = set([current["id"]])
    chain = []
    cursor = current
    for _ in range(MAX_FALLBACK_HOPS):
        nxt_id = cursor["fallback_item_id"]
        if not nxt_id or nxt_id in visited:
            break
        nxt = db.items.get(nxt_id)
        if nxt is None:
            break
        visited.add(nxt_id)
        chain.append(nxt)
        cursor = nxt

    today = clock_date()
    eligible = []
    for candidate in chain:
        if candidate["id"] == current["id"]:
            continue
        if candidate["sku"] != current["sku"]:
            continue
        if candidate["status"] != "ACTIVE":
            continue
        vendor = vendor_of(candidate)
        if vendor is None or vendor["onboarding_status"] != "ACTIVE":
            continue
        rule = best_coverage_rule(
            candidate["vendor_id"], order["customer_zone_code"], candidate["ship_method"]
        )
        if rule is None:
            continue
        if blackout_covering(candidate["vendor_id"], today) is not None:
            continue
        view = availability(candidate)
        if view["inventory_is_stale"]:
            continue
        if view["available_units"] < line["quantity"]:
            continue
        eligible.append((candidate, rule))

    if not eligible:
        return None, None

    def rank(entry):
        candidate, rule = entry
        return (
            rule["transit_days"],
            candidate["unit_cost_cents"],
            candidate["created_at"],
            candidate["_seq"],
        )

    return min(eligible, key=rank)


# ---------------------------------------------------- scorecard metrics --


def compute_scorecard(scorecard):
    """SCAFFOLD calculations.vendor_scorecard_metrics."""
    vendor_id = scorecard["vendor_id"]
    period_start = scorecard["period_start"]
    period_end = scorecard["period_end"]

    population = []
    for line in db.lines.values():
        item = item_of(line)
        if item is None or item["vendor_id"] != vendor_id:
            continue
        if line["transmitted_at"] is None:
            continue
        day = line["transmitted_at"].date()
        if period_start <= day <= period_end:
            population.append(line)

    shipped = [l for l in population if l["status"] == "SHIPPED"]
    cancelled = [l for l in population if l["status"] == "CANCELLED_BY_VENDOR"]

    shipment_by_line = {}
    for confirmation in db.shipments.values():
        shipment_by_line.setdefault(confirmation["line_id"], confirmation)

    on_time_shipped = [
        l for l in shipped
        if shipment_by_line.get(l["id"]) is not None
        and shipment_by_line[l["id"]]["on_time"]
    ]

    shipped_ids = set(l["id"] for l in shipped)
    defect_returns = [
        r for r in db.returns.values()
        if r["status"] in ("AUTHORIZED", "RECEIVED")
        and r["reason_code"] in ("DEFECTIVE", "NOT_AS_DESCRIBED")
        and r["line_id"] in shipped_ids
    ]

    scorecard["transmitted_line_count"] = len(population)
    scorecard["shipped_line_count"] = len(shipped)
    scorecard["cancelled_line_count"] = len(cancelled)
    scorecard["defect_return_count"] = len(defect_returns)
    scorecard["transmitted_unit_count"] = sum(l["quantity"] for l in population)
    scorecard["shipped_unit_count"] = sum(l["quantity"] for l in shipped)
    scorecard["cancelled_unit_count"] = sum(l["quantity"] for l in cancelled)
    scorecard["defect_unit_count"] = sum(r["quantity_returned"] for r in defect_returns)

    seeds = (
        scorecard["seeded_prior_avg_ship_hours"],
        scorecard["seeded_prior_on_time_ship_rate_bps"],
        scorecard["seeded_prior_cancellation_rate_bps"],
        scorecard["seeded_prior_defect_rate_bps"],
    )

    if scorecard["transmitted_line_count"] == 0:
        if all(seed is None for seed in seeds):
            scorecard["on_time_ship_rate_bps"] = None
            scorecard["cancellation_rate_bps"] = None
            scorecard["defect_rate_bps"] = None
            scorecard["avg_ship_hours"] = None
            scorecard["composite_score"] = None
            scorecard["tier"] = "UNRATED"
            scorecard["promise_padding_days"] = PROMISE_DEFAULT_PADDING_DAYS
            return
        on_time = scorecard["seeded_prior_on_time_ship_rate_bps"]
        scorecard["on_time_ship_rate_bps"] = 0 if on_time is None else on_time
        cancel = scorecard["seeded_prior_cancellation_rate_bps"]
        scorecard["cancellation_rate_bps"] = 10000 if cancel is None else cancel
        defect = scorecard["seeded_prior_defect_rate_bps"]
        scorecard["defect_rate_bps"] = 10000 if defect is None else defect
        avg = scorecard["seeded_prior_avg_ship_hours"]
        scorecard["avg_ship_hours"] = None if avg is None else rhu2(dec(avg))
    else:
        if scorecard["metric_variant"] == "EVENT_EQUAL":
            if scorecard["shipped_line_count"] == 0:
                scorecard["on_time_ship_rate_bps"] = 0
                scorecard["defect_rate_bps"] = 0
            else:
                scorecard["on_time_ship_rate_bps"] = rhu_int(
                    Decimal(10000 * len(on_time_shipped)) / scorecard["shipped_line_count"]
                )
                scorecard["defect_rate_bps"] = rhu_int(
                    Decimal(10000 * scorecard["defect_return_count"])
                    / scorecard["shipped_line_count"]
                )
            scorecard["cancellation_rate_bps"] = rhu_int(
                Decimal(10000 * scorecard["cancelled_line_count"])
                / scorecard["transmitted_line_count"]
            )
        else:
            if scorecard["shipped_unit_count"] == 0:
                scorecard["on_time_ship_rate_bps"] = 0
                scorecard["defect_rate_bps"] = 0
            else:
                on_time_units = sum(l["quantity"] for l in on_time_shipped)
                scorecard["on_time_ship_rate_bps"] = rhu_int(
                    Decimal(10000 * on_time_units) / scorecard["shipped_unit_count"]
                )
                scorecard["defect_rate_bps"] = rhu_int(
                    Decimal(10000 * scorecard["defect_unit_count"])
                    / scorecard["shipped_unit_count"]
                )
            if scorecard["transmitted_unit_count"] == 0:
                scorecard["cancellation_rate_bps"] = 0
            else:
                scorecard["cancellation_rate_bps"] = rhu_int(
                    Decimal(10000 * scorecard["cancelled_unit_count"])
                    / scorecard["transmitted_unit_count"]
                )

        if scorecard["shipped_line_count"] == 0:
            scorecard["avg_ship_hours"] = None
        else:
            total = Decimal(0)
            for line in shipped:
                confirmation = shipment_by_line.get(line["id"])
                if confirmation is not None:
                    total += dec(confirmation["ship_hours"])
            scorecard["avg_ship_hours"] = rhu2(total / scorecard["shipped_line_count"])

    composite_bps = rhu_int(
        WEIGHT_ON_TIME * Decimal(scorecard["on_time_ship_rate_bps"])
        + WEIGHT_CANCEL * Decimal(10000 - scorecard["cancellation_rate_bps"])
        + WEIGHT_DEFECT * Decimal(10000 - scorecard["defect_rate_bps"])
    )
    score = round_half_up(Decimal(composite_bps) / 100, 2)
    scorecard["composite_score"] = float(score)

    if score >= 95:
        tier = "PLATINUM"
    elif score >= 90:
        tier = "GOLD"
    elif score >= 80:
        tier = "SILVER"
    elif score >= 70:
        tier = "WATCH"
    else:
        tier = "PROBATION"
    scorecard["tier"] = tier
    scorecard["promise_padding_days"] = TIER_PADDING_DAYS[tier]
