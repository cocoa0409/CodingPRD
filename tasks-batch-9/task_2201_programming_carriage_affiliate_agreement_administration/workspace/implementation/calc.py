"""All calculation rules (scaffold Table 1.3 / PRD sections 3.3 - 3.9).

Every rounding order in this module is pinned exactly as the PRD states it:
rates at four decimal places of a cent, amounts at whole cents, rounding half
up, and applied per-report / per-finding BEFORE any summation.
"""
from decimal import Decimal

import constants as K
from store import (
    D,
    clamp,
    dfloor,
    floor_days,
    month_first_day,
    now,
    period_first_day,
    period_last_day,
    rhu,
    rhu_int,
    whole_months_between,
    db,
)

ZERO = Decimal("0")


# ---------------------------------------------------------------------------
# C1 - agreement effective rate (escalator + MFN cap + floor)
# ---------------------------------------------------------------------------
def active_mfn_clause(agreement_id):
    """At most one clause per agreement may be ACTIVE (validation 64)."""
    for clause in db.mfn_clauses.values():
        if clause["agreement_id"] == agreement_id and clause["status"] == "ACTIVE":
            return clause
    return None


def contract_year_index(agreement, as_of_month_first_day):
    elapsed_days = floor_days(as_of_month_first_day, agreement["term_start_date"])
    return max(0, elapsed_days // K.CONTRACT_YEAR_DAYS)


def agreement_effective_rate(agreement, as_of_month_first_day):
    """Returns (escalated_rate, effective_rate, mfn_capped, year_index)."""
    index = contract_year_index(agreement, as_of_month_first_day)
    base = D(agreement["base_license_fee_cents_per_sub"])
    escalator = D(agreement["escalator_pct"])
    escalated = rhu(base * ((Decimal(1) + escalator) ** index), K.RATE_PRECISION)

    clause = active_mfn_clause(agreement["id"])
    if clause is not None and clause["benchmark_status"] == "BENCHMARKED":
        benchmark = D(clause["benchmark_rate_cents"])
        floor_rate = D(clause["rate_floor_cents"])
        capped = max(min(escalated, benchmark), floor_rate)
        effective = rhu(capped, K.RATE_PRECISION)
        mfn_capped = effective < escalated
    else:
        effective = escalated
        mfn_capped = False
    return escalated, effective, mfn_capped, index


def rate_for_month(agreement, as_of_month_first_day):
    return agreement_effective_rate(agreement, as_of_month_first_day)[1]


def stamp_agreement_rates(agreement):
    """Agreement-level stamping prices the month containing the logical now."""
    current = now()
    as_of = month_first_day(current.year, current.month)
    escalated, effective, mfn_capped, index = agreement_effective_rate(agreement, as_of)
    agreement["escalated_rate_cents_per_sub"] = escalated
    agreement["effective_rate_cents_per_sub"] = effective
    agreement["mfn_capped"] = mfn_capped
    agreement["applied_escalator_years"] = index
    return agreement


# ---------------------------------------------------------------------------
# C2 - subscriber report license fee (PROVISIONAL / FINAL variants)
# ---------------------------------------------------------------------------
def floor_subscribers(agreement, distributor):
    return dfloor(
        D(agreement["penetration_floor_pct"]) * D(distributor["total_subscribers"])
    )


def report_fee_inputs(agreement, distributor, reported_subscribers, reported_tier,
                      period_month):
    total = D(distributor["total_subscribers"])
    penetration_pct = rhu(D(reported_subscribers) / total, 4) if total > 0 else ZERO
    rate_applied = rate_for_month(agreement, period_first_day(period_month))
    tier_mult = K.TIER_MULTIPLIER[reported_tier]
    tier_breach = K.TIER_RANK[reported_tier] < K.TIER_RANK[agreement["committed_tier"]]
    floor_subs = floor_subscribers(agreement, distributor)
    billable_provisional = reported_subscribers
    billable_final = max(reported_subscribers, floor_subs)
    return {
        "penetration_pct": penetration_pct,
        "rate_applied_cents_per_sub": rate_applied,
        "tier_placement_breach": tier_breach,
        "floor_subscribers": floor_subs,
        "billable_provisional": billable_provisional,
        "billable_final": billable_final,
        "provisional_fee_cents": fee_cents(billable_provisional, rate_applied, tier_mult),
        "final_fee_cents": fee_cents(billable_final, rate_applied, tier_mult),
    }


def fee_cents(billable, rate_applied, tier_mult):
    """Rounded to whole cents per report, before any invoice summation."""
    return rhu_int(D(billable) * D(rate_applied) * D(tier_mult))


def stamp_report_provisional(report, agreement, distributor):
    data = report_fee_inputs(
        agreement,
        distributor,
        report["reported_subscribers"],
        report["reported_tier"],
        report["period_month"],
    )
    report["penetration_pct"] = data["penetration_pct"]
    report["rate_applied_cents_per_sub"] = data["rate_applied_cents_per_sub"]
    report["tier_placement_breach"] = data["tier_placement_breach"]
    report["provisional_fee_cents"] = data["provisional_fee_cents"]
    report["billable_subscribers"] = None
    return report


def stamp_report_final(report, agreement, distributor):
    data = report_fee_inputs(
        agreement,
        distributor,
        report["reported_subscribers"],
        report["reported_tier"],
        report["period_month"],
    )
    report["penetration_pct"] = data["penetration_pct"]
    report["rate_applied_cents_per_sub"] = data["rate_applied_cents_per_sub"]
    report["tier_placement_breach"] = data["tier_placement_breach"]
    report["billable_subscribers"] = data["billable_final"]
    report["license_fee_due_cents"] = data["final_fee_cents"]
    return report


# ---------------------------------------------------------------------------
# C3 - MFN benchmark rate
# ---------------------------------------------------------------------------
def _volume_band(total_subscribers):
    if total_subscribers < 2000000:
        return "SMALL"
    if total_subscribers < 10000000:
        return "MID"
    return "LARGE"


def peer_adjusted_rate(peer_agreement, peer_distributor):
    factor = K.VOLUME_BAND_FACTOR[_volume_band(peer_distributor["total_subscribers"])]
    if peer_distributor["distributor_type"] == "VMVPD":
        platform = Decimal(1) - K.VMVPD_PLATFORM_DISCOUNT
    else:
        platform = Decimal(1)
    raw = D(peer_agreement["effective_rate_cents_per_sub"]) * factor * platform
    return rhu(raw, K.RATE_PRECISION)


def mfn_benchmark(clause):
    """Evaluate the peer comparison set and stamp the clause's benchmark."""
    agreement = db.agreements[clause["agreement_id"]]
    this_distributor_id = agreement["distributor_id"]
    scope_types = K.SCOPE_TYPES[clause["mfn_scope"]]
    current = now()

    candidates = []
    for peer in db.agreements.values():
        if peer["id"] == agreement["id"]:
            continue
        if peer["lifecycle_status"] not in ("EXECUTED", "SUSPENDED"):
            continue
        if peer["committed_tier"] != agreement["committed_tier"]:
            continue
        if not (peer["term_start_date"] <= current < peer["term_end_date"]):
            continue
        peer_distributor = db.distributors.get(peer["distributor_id"])
        if peer_distributor is None:
            continue
        if peer_distributor["id"] == this_distributor_id:
            continue
        if peer_distributor["total_subscribers"] < clause["min_peer_subscribers"]:
            continue
        if peer_distributor["distributor_type"] not in scope_types:
            continue
        candidates.append((peer, peer_distributor))

    if not candidates:
        clause["benchmark_rate_cents"] = None
        clause["benchmark_peer_agreement_id"] = None
        clause["benchmark_status"] = "NO_COMPARABLE"
        clause["last_reset_at"] = current
        return clause

    scored = [
        (peer_adjusted_rate(peer, dist), peer["created_at"], peer["_seq"], peer)
        for peer, dist in candidates
    ]
    scored.sort(key=lambda row: (row[0], row[1], row[2]))
    best_rate, _created, _seq, best_peer = scored[0]
    clause["benchmark_rate_cents"] = best_rate
    clause["benchmark_peer_agreement_id"] = best_peer["id"]
    clause["benchmark_status"] = "BENCHMARKED"
    clause["last_reset_at"] = current
    return clause


# ---------------------------------------------------------------------------
# C4 - audit recovery amount
# ---------------------------------------------------------------------------
def engagement_findings(engagement_id):
    return [
        f for f in db.audit_findings.values() if f["engagement_id"] == engagement_id
    ]


def findings_in_pricing_order(engagement_id):
    findings = engagement_findings(engagement_id)
    return sorted(findings, key=lambda f: (f["period_month"], f["created_at"], f["_seq"]))


def audit_recovery(engagement, agreement):
    """Price the whole sample; returns per-finding stamps plus the totals."""
    current = now()
    base_total = 0
    interest_total = 0
    var_total = 0
    rep_total = 0
    stamps = []

    for finding in findings_in_pricing_order(engagement["id"]):
        variance = max(0, finding["audited_subscribers"] - finding["reported_subscribers"])
        if engagement["rate_basis"] == "PERIOD_RATE":
            rate = rate_for_month(agreement, period_first_day(finding["period_month"]))
        else:
            rate = D(agreement["effective_rate_cents_per_sub"])
        report = db.subscriber_reports.get(finding["subscriber_report_id"])
        tier = report["reported_tier"] if report else "BASIC"
        tier_mult = K.TIER_MULTIPLIER[tier]
        recovery = rhu_int(D(variance) * D(rate) * tier_mult)
        months = whole_months_between(period_last_day(finding["period_month"]), current)
        interest = rhu_int(D(recovery) * K.MONTHLY_INTEREST_PCT * D(months))

        base_total += recovery
        interest_total += interest
        var_total += variance
        rep_total += finding["reported_subscribers"]
        stamps.append(
            {
                "finding": finding,
                "variance_subscribers": variance,
                "rate_applied_cents_per_sub": D(rate),
                "finding_recovery_cents": recovery,
            }
        )

    if rep_total > 0:
        underreporting_pct = rhu(D(var_total) / D(rep_total), 4)
    else:
        underreporting_pct = ZERO

    if underreporting_pct < K.PENALTY_TIER_1_THRESHOLD:
        penalty = Decimal("1.00")
    elif underreporting_pct < K.PENALTY_TIER_2_THRESHOLD:
        penalty = Decimal("1.10")
    else:
        penalty = Decimal("1.25")

    if underreporting_pct >= K.AUDIT_COST_SHIFT_THRESHOLD:
        cost_shift = K.AUDIT_COST_CENTS
    else:
        cost_shift = 0

    recovery_amount = rhu_int(D(base_total + interest_total) * penalty) + cost_shift

    return {
        "stamps": stamps,
        "total_variance_subscribers": var_total,
        "total_reported_subscribers": rep_total,
        "underreporting_pct": underreporting_pct,
        "penalty_multiplier": penalty,
        "base_recovery_cents": base_total,
        "interest_cents": interest_total,
        "audit_cost_shift_cents": cost_shift,
        "recovery_amount_cents": recovery_amount,
    }


# ---------------------------------------------------------------------------
# C5 - invoice net due (pinned six-step waterfall)
# ---------------------------------------------------------------------------
def billable_reports(agreement_id, period_month):
    rows = [
        r
        for r in db.subscriber_reports.values()
        if r["agreement_id"] == agreement_id
        and r["period_month"] == period_month
        and r["status"] in ("ACCEPTED", "AUDIT_ADJUSTED")
        and r.get("invoice_id") is None
    ]
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def coop_cap_pct_for(gross):
    if gross < K.COOP_BAND_1_MAX:
        return K.COOP_CAP_BAND_1
    if gross < K.COOP_BAND_2_MAX:
        return K.COOP_CAP_BAND_2
    return K.COOP_CAP_BAND_3


def _offset_lines(agreement_id, types):
    rows = [
        c
        for c in db.marketing_commitments.values()
        if c["agreement_id"] == agreement_id
        and c["commitment_type"] in types
        and c["status"] in ("PARTIALLY_EARNED", "EARNED")
        and c["earned_unbilled_cents"] > 0
    ]
    order = {t: i for i, t in enumerate(types)}
    return sorted(
        rows,
        key=lambda c: (order[c["commitment_type"]], c["created_at"], c["_seq"]),
    )


def _draw(lines, budget):
    """Consume `budget` cents from `lines` in their pinned order."""
    plan = []
    remaining = budget
    for line in lines:
        if remaining <= 0:
            break
        take = min(line["earned_unbilled_cents"], remaining)
        if take > 0:
            plan.append({"commitment_id": line["id"], "amount_cents": take})
            remaining -= take
    return plan, budget - remaining


def invoice_net_due(invoice):
    """Evaluate the six pinned steps; returns the stamps plus the offset plan."""
    agreement_id = invoice["agreement_id"]

    # STEP 1 - gross
    if invoice["invoice_kind"] == "LICENSE_FEE":
        reports = billable_reports(agreement_id, invoice["period_month"])
        gross = sum(r["license_fee_due_cents"] for r in reports)
        source_report_ids = [r["id"] for r in reports]
    else:
        engagement = db.audit_engagements.get(invoice.get("audit_engagement_id"))
        gross = engagement["recovery_amount_cents"] if engagement else 0
        source_report_ids = []

    # STEP 2 - co-op ceiling band, selected from the STEP 1 gross
    cap_pct = coop_cap_pct_for(gross)
    ceiling = rhu_int(D(gross) * cap_pct)

    # STEP 3 - co-op / marketing-support offset (LICENSE_FEE only)
    if invoice["invoice_kind"] == "LICENSE_FEE":
        coop_lines = _offset_lines(agreement_id, ["COOP_ADVERTISING", "MARKETING_SUPPORT"])
        coop_plan, coop_offset = _draw(coop_lines, ceiling)
    else:
        coop_plan, coop_offset = [], 0

    # STEP 4 - launch-fee offset against what STEP 3 left of the gross
    if invoice["invoice_kind"] == "LICENSE_FEE":
        launch_lines = _offset_lines(agreement_id, ["LAUNCH_FEE"])
        launch_budget = max(0, gross - coop_offset)
        launch_plan, launch_offset = _draw(launch_lines, launch_budget)
    else:
        launch_plan, launch_offset = [], 0

    # STEP 5 - audit adjustments are never double counted
    recovery_adjustment = 0

    # STEP 6 - floor at zero, carry the remainder forward
    raw_net = gross - coop_offset - launch_offset + recovery_adjustment
    net_due = max(0, raw_net)
    carryforward = max(0, -raw_net)

    return {
        "gross_license_fee_cents": gross,
        "coop_cap_pct": cap_pct,
        "coop_offset_cents": coop_offset,
        "launch_fee_offset_cents": launch_offset,
        "recovery_adjustment_cents": recovery_adjustment,
        "net_due_cents": net_due,
        "carryforward_cents": carryforward,
        "offset_plan": coop_plan + launch_plan,
        "source_report_ids": source_report_ids,
    }


def stamp_invoice_amounts(invoice):
    data = invoice_net_due(invoice)
    for key in (
        "gross_license_fee_cents",
        "coop_cap_pct",
        "coop_offset_cents",
        "launch_fee_offset_cents",
        "recovery_adjustment_cents",
        "net_due_cents",
        "carryforward_cents",
    ):
        invoice[key] = data[key]
    invoice["_offset_plan"] = data["offset_plan"]
    invoice["_source_report_ids"] = data["source_report_ids"]
    return data


# ---------------------------------------------------------------------------
# C7 - rights window occupancy (half-open intervals)
# ---------------------------------------------------------------------------
def window_neighbours(window):
    key = (window["content_title_id"], window["platform"], window["territory_code"])
    out = []
    for other in db.rights_windows.values():
        if other["id"] == window["id"]:
            continue
        if (
            other["content_title_id"],
            other["platform"],
            other["territory_code"],
        ) != key:
            continue
        if other["status"] not in ("CLEARED", "ACTIVE"):
            continue
        if other["window_start"] < window["window_end"] and (
            window["window_start"] < other["window_end"]
        ):
            out.append(other)
    return out


def holdback_days(window, title):
    return floor_days(window["window_start"], title["linear_premiere_at"])


# ---------------------------------------------------------------------------
# C8 - blackout separation (closed intervals + 24h buffer + monthly cap)
# ---------------------------------------------------------------------------
def blackout_hours(rule_start, rule_end):
    seconds = (rule_end - rule_start).total_seconds()
    return rhu(D(seconds) / D(3600), 2)


def blackout_key_rules(distributor_id, territory_code, exclude_id=None):
    out = []
    for rule in db.blackout_rules.values():
        if rule["id"] == exclude_id:
            continue
        if rule["status"] not in ("SCHEDULED", "ENFORCED"):
            continue
        agreement = db.agreements.get(rule["agreement_id"])
        if not agreement or agreement["distributor_id"] != distributor_id:
            continue
        if rule["territory_code"] != territory_code:
            continue
        out.append(rule)
    return out


# ---------------------------------------------------------------------------
# C9 - renewal leverage + distribution loss
# ---------------------------------------------------------------------------
def latest_substantiated_report(agreement_id):
    rows = [
        r
        for r in db.subscriber_reports.values()
        if r["agreement_id"] == agreement_id
        and r["status"] in ("ACCEPTED", "AUDIT_ADJUSTED")
    ]
    if not rows:
        return None
    rows.sort(key=lambda r: (r["period_month"], r["created_at"], r["_seq"]))
    return rows[-1]


def renewal_leverage(agreement, distributor, variant):
    latest = latest_substantiated_report(agreement["id"])

    subscriber_share = rhu(
        D(distributor["total_subscribers"]) / D(K.TOTAL_ADDRESSABLE_SUBS), 6
    )

    if latest is None:
        penetration_ratio = ZERO
    else:
        ratio = D(latest["penetration_pct"]) / D(agreement["penetration_floor_pct"])
        penetration_ratio = rhu(min(ratio, Decimal("2.0")), 4)

    payment_score = rhu(
        Decimal(1)
        - clamp(
            D(distributor["receivable_balance_cents"])
            / D(max(1, distributor["credit_limit_cents"])),
            0,
            1,
        ),
        4,
    )
    compliance_score = rhu(
        Decimal(1)
        - clamp(
            D(agreement["penetration_breach_count"]) / K.BREACH_SCORE_DENOMINATOR, 0, 1
        ),
        4,
    )

    leverage_score = rhu(
        Decimal(100)
        * (
            K.W_SHARE * min(subscriber_share / K.SHARE_SATURATION, Decimal(1))
            + K.W_PENETRATION
            * min(penetration_ratio / K.PENETRATION_SATURATION, Decimal(1))
            + K.W_PAYMENT * payment_score
            + K.W_COMPLIANCE * compliance_score
        ),
        2,
    )

    recapture = (
        K.RECAPTURE_RATE_BASE if variant == "BASE_CASE" else K.RECAPTURE_RATE_DOWNSIDE
    )
    if latest is None:
        loss = 0
        at_risk = 0
    else:
        loss = rhu_int(
            D(distributor["total_subscribers"])
            * D(latest["penetration_pct"])
            * (Decimal(1) - recapture)
        )
        at_risk = rhu_int(
            D(loss) * D(agreement["effective_rate_cents_per_sub"]) * Decimal(12)
        )

    return {
        "latest_accepted_report_id": latest["id"] if latest else None,
        "subscriber_share": subscriber_share,
        "penetration_ratio": penetration_ratio,
        "payment_score": payment_score,
        "compliance_score": compliance_score,
        "leverage_score": leverage_score,
        "recapture_rate": recapture,
        "distribution_loss_subscribers": loss,
        "annualized_revenue_at_risk_cents": at_risk,
    }
