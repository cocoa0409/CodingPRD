"""Derived-field recomputation and the six program calculations.

Every derived field is recomputed in full from its source rows on every
trigger, never adjusted by a delta (PRD 2.10 / 3.9).
"""

from decimal import Decimal

from core import (
    CAP_DUE_DAYS_BY_LEVEL,
    CAP_TRIGGER_SCORE,
    CRITICAL_SCORE,
    FILL_WEIGHT,
    GOODWILL_OTIF_THRESHOLD,
    GOODWILL_PCT,
    GRACE_LOOKBACK_DAYS,
    OTIF_WEIGHT,
    REPEAT_LOOKBACK_DAYS,
    REPEAT_TIER1_SCORE,
    REPEAT_VIOLATION_THRESHOLD,
    VENDOR_EXPOSURE_ALERT_CENTS,
    clock,
    days,
    dec,
    pct2,
    round_cents,
    store,
    touch,
    touch_if_changed,
)

OPEN_VIOLATION_STATES = ("DETECTED", "EVIDENCE_COMPLETE")
OPEN_CAP_STATES = ("ISSUED", "VENDOR_SUBMITTED", "REJECTED", "ACCEPTED", "ESCALATED")


# ---------------------------------------------------------------------------
# Graph navigation
# ---------------------------------------------------------------------------


def po_of_shipment(shipment):
    return store.purchase_orders.get(shipment["po_id"])


def vendor_of_shipment(shipment):
    order = po_of_shipment(shipment)
    if order is None:
        return None
    return store.vendors.get(order["vendor_id"])


def vendor_of_violation(violation):
    shipment = store.shipments.get(violation["shipment_id"])
    if shipment is None:
        return None
    return vendor_of_shipment(shipment)


def pinned_requirement(record):
    return store.requirements.get(record["requirement_id"])


def guide_of_requirement(requirement):
    return store.guides.get(requirement["guide_id"])


def allocations_of_chargeback(chargeback_id):
    return [a for a in store.allocations.values() if a["chargeback_id"] == chargeback_id]


def allocations_of_deduction(deduction_id):
    return [a for a in store.allocations.values() if a["deduction_id"] == deduction_id]


def violations_of_shipment(shipment_id):
    return [v for v in store.violations.values() if v["shipment_id"] == shipment_id]


def shipments_of_po(po_id):
    return [s for s in store.shipments.values() if s["po_id"] == po_id]


def chargebacks_of_vendor(vendor_id):
    return [c for c in store.chargebacks.values() if c["vendor_id"] == vendor_id]


def evidence_of_violation(violation_id):
    return [
        e
        for e in store.evidence.values()
        if e["subject_type"] == "VIOLATION" and e["violation_id"] == violation_id
    ]


def evidence_of_dispute(dispute_id):
    return [
        e
        for e in store.evidence.values()
        if e["subject_type"] == "DISPUTE" and e["dispute_id"] == dispute_id
    ]


# ---------------------------------------------------------------------------
# Routing guide effectivity
# ---------------------------------------------------------------------------


def scopes_collide(scope_a, scope_b):
    """Two editions share a timeline when the scopes match or either is ALL."""
    return scope_a == scope_b or scope_a == "ALL" or scope_b == "ALL"


def guide_governs(guide, instant):
    """Half-open effectivity: [effective_from, effective_until)."""
    if guide is None or instant is None:
        return False
    if guide["status"] not in ("PUBLISHED", "SUPERSEDED"):
        return False
    if guide["effective_from"] > instant:
        return False
    until = guide["effective_until"]
    if until is not None and instant >= until:
        return False
    return True


def requirement_effective_at(requirement, instant):
    return guide_governs(guide_of_requirement(requirement), instant)


def recompute_guide_requirement_count(guide):
    count = len([r for r in store.requirements.values() if r["guide_id"] == guide["id"]])

    def mutate():
        guide["requirement_count"] = count

    return touch_if_changed(guide, ["requirement_count"], mutate)


# ---------------------------------------------------------------------------
# Shipment / purchase order roll-ups
# ---------------------------------------------------------------------------


def recompute_shipment_counters(shipment, bump=True):
    rows = violations_of_shipment(shipment["id"])
    open_count = len([v for v in rows if v["status"] in OPEN_VIOLATION_STATES])
    capture_count = 0
    for violation in rows:
        capture_count += len(evidence_of_violation(violation["id"]))

    def mutate():
        shipment["open_violation_count"] = open_count
        # Monotonic audit counter: never falls below what it already reads.
        if capture_count > shipment["evidence_capture_count"]:
            shipment["evidence_capture_count"] = capture_count

    if bump:
        return touch_if_changed(
            shipment, ["open_violation_count", "evidence_capture_count"], mutate
        )
    mutate()
    return False


def recompute_purchase_order(order, bump=True):
    received = [s for s in shipments_of_po(order["id"]) if s["status"] == "RECEIVED"]
    total = sum((s["received_units"] or 0) for s in received)
    first_at = None
    for shipment in received:
        arrived = shipment["arrived_at"]
        if arrived is not None and (first_at is None or arrived < first_at):
            first_at = arrived

    def mutate():
        order["received_units"] = total
        order["first_receipt_at"] = first_at
        if total >= order["ordered_units"]:
            order["status"] = "RECEIVED"
        elif total >= 1:
            order["status"] = "PARTIALLY_RECEIVED"
        else:
            order["status"] = "OPEN"

    if bump:
        return touch_if_changed(
            order, ["received_units", "first_receipt_at", "status"], mutate
        )
    mutate()
    return False


def recompute_violation_evidence_count(violation, bump=True):
    count = len(evidence_of_violation(violation["id"]))
    requirement = pinned_requirement(violation)
    minimum = requirement["min_evidence_count"] if requirement else 0

    def mutate():
        violation["evidence_count"] = count
        if violation["status"] == "DETECTED" and count >= minimum:
            violation["status"] = "EVIDENCE_COMPLETE"

    if bump:
        return touch_if_changed(violation, ["evidence_count", "status"], mutate)
    mutate()
    return False


# ---------------------------------------------------------------------------
# Chargeback settlement reconciliation (PRD 3.9)
# ---------------------------------------------------------------------------


def _settlement_status(net_assessed, recovered):
    if net_assessed <= 0:
        return "WRITTEN_OFF"
    if recovered >= net_assessed:
        return "RECOVERED"
    if recovered > 0:
        return "PARTIALLY_RECOVERED"
    return "ASSESSED"


def recompute_chargeback(chargeback, bump=True, force_bump=False):
    rows = allocations_of_chargeback(chargeback["id"])
    recovered = sum(a["allocated_cents"] for a in rows if a["effective_status"] == "EFFECTIVE")
    net_assessed = chargeback["gross_assessed_cents"] - chargeback["reversal_cents"]
    outstanding = net_assessed - recovered
    if outstanding < 0:
        outstanding = 0
    posted = False
    for allocation in rows:
        if allocation["source_type"] != "DEDUCTION":
            continue
        deduction = store.deductions.get(allocation["deduction_id"])
        if deduction is not None and deduction["status"] == "POSTED":
            posted = True
            break

    def mutate():
        chargeback["recovered_cents"] = recovered
        chargeback["outstanding_cents"] = outstanding
        chargeback["deduction_posted"] = posted
        chargeback["settlement_status"] = _settlement_status(net_assessed, recovered)

    if force_bump:
        mutate()
        touch(chargeback)
        return True
    if bump:
        return touch_if_changed(
            chargeback,
            ["recovered_cents", "outstanding_cents", "deduction_posted", "settlement_status"],
            mutate,
        )
    mutate()
    return False


def recompute_deduction(deduction, bump=True, force_bump=False):
    rows = allocations_of_deduction(deduction["id"])
    amount = sum(a["allocated_cents"] for a in rows if a["effective_status"] != "REVERSED")
    over = 0
    for allocation in rows:
        if allocation["effective_status"] != "EFFECTIVE":
            continue
        chargeback = store.chargebacks.get(allocation["chargeback_id"])
        if chargeback is None:
            continue
        net = chargeback["gross_assessed_cents"] - chargeback["reversal_cents"]
        excess = allocation["allocated_cents"] - net
        if excess > 0:
            over += excess

    def mutate():
        deduction["amount_cents"] = amount
        deduction["allocation_count"] = len(rows)
        deduction["over_allocated_cents"] = over

    if force_bump:
        mutate()
        touch(deduction)
        return True
    if bump:
        return touch_if_changed(
            deduction, ["amount_cents", "allocation_count", "over_allocated_cents"], mutate
        )
    mutate()
    return False


# ---------------------------------------------------------------------------
# Vendor reconciliation (PRD 3.1 / 3.9)
# ---------------------------------------------------------------------------


def current_otif_score(vendor_id):
    finalized = [
        s
        for s in store.scorecards.values()
        if s["vendor_id"] == vendor_id and s["status"] == "FINALIZED"
    ]
    if not finalized:
        return Decimal("0.00")
    finalized.sort(key=lambda s: (s["period_end"], s["created_at"], s["_seq"]), reverse=True)
    return pct2(finalized[0]["composite_score"])


def vendor_open_violation_count(vendor_id):
    count = 0
    for violation in store.violations.values():
        if violation["status"] not in OPEN_VIOLATION_STATES:
            continue
        vendor = vendor_of_violation(violation)
        if vendor is not None and vendor["id"] == vendor_id:
            count += 1
    return count


def vendor_open_cap_count(vendor_id):
    return len(
        [
            c
            for c in store.caps.values()
            if c["vendor_id"] == vendor_id and c["status"] in OPEN_CAP_STATES
        ]
    )


def reconcile_vendor(vendor, bump=True, force_bump=False):
    """Full recompute of every derived vendor figure from source rows."""
    rows = chargebacks_of_vendor(vendor["id"])
    open_cents = 0
    refund_cents = 0
    for chargeback in rows:
        net = chargeback["gross_assessed_cents"] - chargeback["reversal_cents"]
        if chargeback["settlement_status"] in ("ASSESSED", "PARTIALLY_RECOVERED"):
            open_cents += net - chargeback["recovered_cents"]
        excess = chargeback["recovered_cents"] - net
        if excess > 0:
            refund_cents += excess
    charge_ids = set(c["id"] for c in rows)
    recovered_lifetime = sum(
        a["allocated_cents"]
        for a in store.allocations.values()
        if a["chargeback_id"] in charge_ids and a["effective_status"] == "EFFECTIVE"
    )

    keys = [
        "open_chargeback_cents",
        "recovered_lifetime_cents",
        "refund_due_cents",
        "exposure_alert_flag",
        "open_violation_count",
        "open_cap_count",
        "otif_score",
    ]

    def mutate():
        vendor["open_chargeback_cents"] = open_cents
        vendor["recovered_lifetime_cents"] = recovered_lifetime
        vendor["refund_due_cents"] = refund_cents
        vendor["exposure_alert_flag"] = open_cents >= VENDOR_EXPOSURE_ALERT_CENTS
        vendor["open_violation_count"] = vendor_open_violation_count(vendor["id"])
        vendor["open_cap_count"] = vendor_open_cap_count(vendor["id"])
        vendor["otif_score"] = current_otif_score(vendor["id"])

    if force_bump:
        mutate()
        touch(vendor)
        return True
    if bump:
        return touch_if_changed(vendor, keys, mutate)
    mutate()
    return False


# ---------------------------------------------------------------------------
# Calculation: chargeback_assessment (PRD 3.5)
# ---------------------------------------------------------------------------


def assess_amounts(violation, shipment, requirement, vendor):
    fixed_fee = requirement["fixed_fee_cents"]
    unit_recovery = requirement["per_unit_recovery_cents"] * violation["affected_units"]
    handling_recovery = round_cents(
        dec(shipment["invoice_value_cents"]) * dec(requirement["handling_pct"]) / dec(100)
    )

    tier = requirement["severity_tier"]
    if tier == "TIER_1":
        cost_recovery = unit_recovery + handling_recovery
    elif tier == "TIER_2":
        cost_recovery = max(unit_recovery, handling_recovery)
    else:
        cost_recovery = 0

    variant = "STANDARD"
    if tier in ("TIER_2", "TIER_3") and not _has_recent_same_code(
        vendor["id"], requirement["requirement_code"], exclude_violation_id=violation["id"]
    ):
        variant = "GRACE_FIRST_OCCURRENCE"

    if variant == "GRACE_FIRST_OCCURRENCE":
        cost_recovery = 0
        gross = min(fixed_fee, requirement["cap_cents"])
    else:
        raw = fixed_fee + cost_recovery
        gross = min(max(raw, requirement["min_fee_cents"]), requirement["cap_cents"])

    return {
        "assessment_variant": variant,
        "fixed_fee_cents": fixed_fee,
        "cost_recovery_cents": cost_recovery,
        "gross_assessed_cents": gross,
    }


def _has_recent_same_code(vendor_id, requirement_code, exclude_violation_id=None):
    threshold = clock.now() - days(GRACE_LOOKBACK_DAYS)
    for chargeback in store.chargebacks.values():
        if chargeback["vendor_id"] != vendor_id:
            continue
        if exclude_violation_id and chargeback["violation_id"] == exclude_violation_id:
            continue
        requirement = pinned_requirement(chargeback)
        if requirement is None or requirement["requirement_code"] != requirement_code:
            continue
        assessed = chargeback["assessed_at"]
        if assessed is not None and assessed >= threshold:
            return True
    return False


# ---------------------------------------------------------------------------
# Calculation: otif_scorecard_measurement (PRD 3.7)
# ---------------------------------------------------------------------------


def measure_scorecard(scorecard, variant):
    scope = [
        order
        for order in store.purchase_orders.values()
        if order["vendor_id"] == scorecard["vendor_id"]
        and order["status"] in ("OPEN", "PARTIALLY_RECEIVED", "RECEIVED")
        and scorecard["period_start"] <= order["must_arrive_by"] <= scorecard["period_end"]
    ]
    scope.sort(key=lambda o: (o["must_arrive_by"], o["created_at"], o["_seq"]))
    measured = len(scope)
    if measured == 0:
        return None

    early = days(scorecard["tolerance_early_days"])
    late = days(scorecard["tolerance_late_days"])
    floor_pct = dec(100) - dec(scorecard["fill_tolerance_pct"])

    on_time_count = 0
    in_full_count = 0
    otif_count = 0
    per_order_fill = []
    total_received = 0
    total_ordered = 0

    for order in scope:
        first_at = order["first_receipt_at"]
        on_time = (
            first_at is not None
            and first_at >= order["must_arrive_by"] - early
            and first_at <= order["must_arrive_by"] + late
        )
        fill_pct = pct2(dec(100) * dec(order["received_units"]) / dec(order["ordered_units"]))
        in_full = fill_pct >= floor_pct
        per_order_fill.append(fill_pct)
        total_received += order["received_units"]
        total_ordered += order["ordered_units"]
        if on_time:
            on_time_count += 1
        if in_full:
            in_full_count += 1
        if on_time and in_full:
            otif_count += 1

    on_time_pct = pct2(dec(100) * dec(on_time_count) / dec(measured))
    otif_pct = pct2(dec(100) * dec(otif_count) / dec(measured))
    if variant == "ORDER_WEIGHTED":
        fill_rate_pct = pct2(sum(per_order_fill, Decimal("0")) / dec(measured))
    else:
        if total_ordered == 0:
            fill_rate_pct = Decimal("0.00")
        else:
            fill_rate_pct = pct2(dec(100) * dec(total_received) / dec(total_ordered))
    composite = pct2(OTIF_WEIGHT * otif_pct + FILL_WEIGHT * fill_rate_pct)

    return {
        "measured_po_count": measured,
        "on_time_count": on_time_count,
        "in_full_count": in_full_count,
        "otif_count": otif_count,
        "on_time_pct": on_time_pct,
        "fill_rate_pct": fill_rate_pct,
        "otif_pct": otif_pct,
        "composite_score": composite,
    }


# ---------------------------------------------------------------------------
# Calculation: repeat_offender_escalation (PRD 3.8)
# ---------------------------------------------------------------------------


def repeat_offender_escalation(vendor_id, period_end, composite_score):
    window_start = period_end - days(REPEAT_LOOKBACK_DAYS)
    charged = []
    for chargeback in store.chargebacks.values():
        if chargeback["vendor_id"] != vendor_id:
            continue
        if chargeback["dispute_status"] == "REVERSED":
            continue
        assessed = chargeback["assessed_at"]
        if assessed is None or not (window_start <= assessed < period_end):
            continue
        charged.append(chargeback)

    charged_count = len(charged)
    tier1_count = 0
    for chargeback in charged:
        requirement = pinned_requirement(chargeback)
        if requirement is not None and requirement["severity_tier"] == "TIER_1":
            tier1_count += 1

    prior_failed = 0
    for cap in store.caps.values():
        if cap["vendor_id"] != vendor_id or cap["status"] != "CLOSED_UNREMEDIATED":
            continue
        closed = cap["closed_at"]
        if closed is not None and window_start <= closed < period_end:
            prior_failed += 1

    score = pct2(composite_score)
    repeat_flag = charged_count >= REPEAT_VIOLATION_THRESHOLD or (
        tier1_count >= 1 and score < REPEAT_TIER1_SCORE
    )
    cap_required = repeat_flag and score < CAP_TRIGGER_SCORE
    level = 1 + prior_failed + (1 if score < CRITICAL_SCORE else 0)
    if level > 3:
        level = 3

    return {
        "repeat_offender_flag": repeat_flag,
        "cap_required": cap_required,
        "escalation_level": level,
        "repeat_count": charged_count,
    }


def select_predecessor_cap_id(vendor_id):
    candidates = [
        c
        for c in store.caps.values()
        if c["vendor_id"] == vendor_id and c["status"] == "CLOSED_UNREMEDIATED"
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda c: (c["closed_at"], c["created_at"], c["_seq"]), reverse=True)
    return candidates[0]["id"]


def cap_due_at(issued_at, level):
    return issued_at + days(CAP_DUE_DAYS_BY_LEVEL[level])


# ---------------------------------------------------------------------------
# Calculation: dispute_reversal_determination (PRD 3.6)
# ---------------------------------------------------------------------------


def dispute_determination(dispute, chargeback, requirement, vendor):
    eligible_cap = chargeback["gross_assessed_cents"] - chargeback["reversal_cents"]

    reason = dispute["reason_code"]
    if reason in ("NOT_OUR_LABEL", "DUPLICATE_ASSESSMENT", "FEE_MISCALCULATED"):
        ceiling_pct = Decimal("100.00")
    elif reason == "CARRIER_CAUSED":
        ceiling_pct = Decimal("60.00")
    else:  # EVIDENCE_INSUFFICIENT
        minimum = requirement["min_evidence_count"] if requirement else 0
        if chargeback["evidence_at_assessment_count"] < minimum:
            ceiling_pct = Decimal("100.00")
        else:
            ceiling_pct = Decimal("50.00")

    ceiling_cents = round_cents(dec(eligible_cap) * ceiling_pct / dec(100))
    requested = min(dispute["claimed_reversal_cents"], ceiling_cents)

    pre_full = requested >= eligible_cap
    if (
        not pre_full
        and pct2(vendor["otif_score"]) >= GOODWILL_OTIF_THRESHOLD
        and dispute["round_count"] == 1
    ):
        goodwill = round_cents(dec(eligible_cap - requested) * GOODWILL_PCT / dec(100))
    else:
        goodwill = 0

    approved = min(requested + goodwill, eligible_cap)

    if approved == 0:
        status = "DENIED"
    elif approved == eligible_cap:
        status = "APPROVED_FULL"
    else:
        status = "APPROVED_PARTIAL"

    return {
        "reason_ceiling_pct": pct2(ceiling_pct),
        "goodwill_cents": goodwill,
        "approved_reversal_cents": approved,
        "status": status,
    }
