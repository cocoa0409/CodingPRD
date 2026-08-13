"""Calculation rules per SCAFFOLD section 1.3 and PRD section 2.5.

All monetary values are integer cents. Basis-point applications use
round-half-up against the fixed denominator 10000.
"""
from decimal import Decimal, ROUND_HALF_UP

import common
import db

BP_DENOMINATOR = 10000


def round_half_up_cents(numerator, denominator=BP_DENOMINATOR):
    """round_half_up(numerator / denominator) to whole cents."""
    d = Decimal(numerator) / Decimal(denominator)
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def effective_rate_bp(agreement):
    """Effective first-line rate: mfl_adjusted_rate_bp if set else base_rate_bp."""
    r = agreement.get("mfl_adjusted_rate_bp")
    return r if r is not None else agreement["base_rate_bp"]


def royalty_base_derivation(agreement, lines):
    """Compute the intake aggregates for a report. Returns a dict."""
    non_sub = [l for l in lines if not l.get("is_sublicense_revenue", False)]
    sub = [l for l in lines if l.get("is_sublicense_revenue", False)]

    reported_gross = sum(l["gross_sales_cents"] for l in lines)
    reported_net = sum(l["gross_sales_cents"] - l["deductions_cents"] for l in lines)

    if agreement["royalty_base_definition"] == "NET_SALES":
        royalty_base = sum(l["gross_sales_cents"] - l["deductions_cents"] for l in non_sub)
    else:  # GROSS_SALES
        royalty_base = sum(l["gross_sales_cents"] for l in non_sub)

    sublicense_net = sum(l["gross_sales_cents"] - l["deductions_cents"] for l in sub)

    return {
        "reported_gross_sales_cents": reported_gross,
        "reported_net_sales_cents": reported_net,
        "royalty_base_cents": royalty_base,
        "sublicense_net_sales_cents": sublicense_net,
    }


def royalty_components(agreement, base_cents, sublicense_net_sales_cents):
    """Compute the two rounded components. Returns (product, passthrough, sum)."""
    product = round_half_up_cents(base_cents * effective_rate_bp(agreement))
    passthrough = round_half_up_cents(
        sublicense_net_sales_cents * agreement["sublicense_passthrough_rate_bp"])
    return product, passthrough, product + passthrough


def royalty_provisional(agreement, base_cents, sublicense_net_sales_cents):
    """PROVISIONAL variant: no minimum floor."""
    _, _, computed = royalty_components(agreement, base_cents, sublicense_net_sales_cents)
    return computed


def royalty_final(agreement, base_cents, sublicense_net_sales_cents):
    """FINAL variant: floor applied."""
    _, _, computed = royalty_components(agreement, base_cents, sublicense_net_sales_cents)
    return max(computed, agreement["minimum_period_royalty_cents"])


def underreport_threshold(agreement, benchmark_net_sales_cents):
    """round_half_up(benchmark * (10000 - tolerance_bp) / 10000)."""
    return round_half_up_cents(
        benchmark_net_sales_cents * (BP_DENOMINATOR - agreement["underreport_tolerance_bp"]))


def shortfall_calculation(agreement, report, audited_base_cents):
    """max(0, FINAL royalty recomputed at audited_base_cents - recognized)."""
    recognized = 0
    if report["status"] in ("ACCEPTED", "ACCEPTED_WITH_ADJUSTMENT"):
        recognized = report["final_royalty_cents"]
    recomputed = royalty_final(agreement, audited_base_cents,
                               report["sublicense_net_sales_cents"])
    return max(0, recomputed - recognized)


def mfl_sweep(new_agreement):
    """Run the most-favored-licensee sweep on activation of new_agreement.

    For each OTHER agreement M: same patent_reference, status ACTIVE,
    mfl_clause true, effective_rate > new base_rate_bp -- processed in
    created_at ASC order: set M.mfl_adjusted_rate_bp = new base rate;
    RETROACTIVE mode also computes the lookback credit.
    """
    affected = [
        m for m in db.agreements.values()
        if m["id"] != new_agreement["id"]
        and m["patent_reference"] == new_agreement["patent_reference"]
        and m["status"] == "ACTIVE"
        and m["mfl_clause"]
        and effective_rate_bp(m) > new_agreement["base_rate_bp"]
    ]
    affected.sort(key=lambda m: (m["created_at"], m["id"]))

    now = common.logical_now()
    for m in affected:
        new_rate = new_agreement["base_rate_bp"]
        if m["mfl_mode"] == "RETROACTIVE":
            window_start = common.add_months(now, -3 * m["mfl_lookback_quarters"])
            credit = 0
            reports = [
                r for r in db.reports.values()
                if r["agreement_id"] == m["id"]
                and r["status"] in ("ACCEPTED", "ACCEPTED_WITH_ADJUSTMENT")
                and r.get("accepted_at") is not None
                and common.parse_dt(r["accepted_at"]) >= window_start
            ]
            for r in reports:
                r_base = r["adjusted_base_cents"] if r["adjusted_base_cents"] is not None \
                    else r["royalty_base_cents"]
                r_product = round_half_up_cents(r_base * new_rate)
                r_passthrough = round_half_up_cents(
                    r["sublicense_net_sales_cents"] * m["sublicense_passthrough_rate_bp"])
                recomputed = max(r_product + r_passthrough,
                                 m["minimum_period_royalty_cents"])
                credit += max(0, r["final_royalty_cents"] - recomputed)
            m["last_mfl_credit_cents"] = credit
            licensee = db.licensees[m["licensee_id"]]
            licensee["credit_balance_cents"] += credit
            common.touch(licensee)
        else:
            m["last_mfl_credit_cents"] = 0
        m["mfl_adjusted_rate_bp"] = new_rate
        common.touch(m)


def milestone_trigger_check(agreement):
    """After an acceptance: achieve PENDING CUMULATIVE_SALES milestones whose
    threshold <= updated cumulative. Processed in created_at ASC order."""
    ms = [
        m for m in db.milestones.values()
        if m["agreement_id"] == agreement["id"] and m["status"] == "PENDING"
    ]
    ms.sort(key=lambda m: (m["created_at"], m["id"]))
    for m in ms:
        if m["trigger_type"] == "CUMULATIVE_SALES" and \
                agreement["cumulative_accepted_base_cents"] >= m["threshold_cents"]:
            achieve_milestone(m)


def achieve_milestone(m):
    """Set achieved_at, accrue fee to licensee, bump milestone version."""
    agreement = db.agreements[m["agreement_id"]]
    licensee = db.licensees[agreement["licensee_id"]]
    m["status"] = "ACHIEVED"
    m["achieved_at"] = common.logical_now_str()
    common.touch(m)
    licensee["outstanding_balance_cents"] += m["fee_cents"]
    common.touch(licensee)


def revert_milestone(m):
    """ACHIEVED -> PENDING compensation: clear achieved_at, un-accrue fee."""
    agreement = db.agreements[m["agreement_id"]]
    licensee = db.licensees[agreement["licensee_id"]]
    m["status"] = "PENDING"
    m["achieved_at"] = None
    common.touch(m)
    licensee["outstanding_balance_cents"] -= m["fee_cents"]
    common.touch(licensee)


def milestone_revert_check(agreement):
    """After a void-acceptance: revert ACHIEVED CUMULATIVE_SALES milestones
    whose threshold > updated cumulative."""
    ms = [
        m for m in db.milestones.values()
        if m["agreement_id"] == agreement["id"]
        and m["status"] == "ACHIEVED"
        and m["trigger_type"] == "CUMULATIVE_SALES"
        and agreement["cumulative_accepted_base_cents"] < m["threshold_cents"]
    ]
    ms.sort(key=lambda m: (m["created_at"], m["id"]))
    for m in ms:
        revert_milestone(m)


def inventor_share_distribution(agreement, pool_cents):
    """Waterfall allocation with pinned rounding. Returns list of line dicts
    preserving agreement.inventor_shares order."""
    shares = agreement["inventor_shares"]
    lines = []
    for s in shares:
        amount = round_half_up_cents(pool_cents * s["share_bp"])
        lines.append({
            "inventor_name": s["inventor_name"],
            "share_bp": s["share_bp"],
            "amount_cents": amount,
        })
    remainder = pool_cents - sum(l["amount_cents"] for l in lines)
    if remainder != 0:
        order = sorted(range(len(lines)),
                       key=lambda i: (-lines[i]["share_bp"], lines[i]["inventor_name"]))
        if remainder > 0:
            for i in order[:remainder]:
                lines[i]["amount_cents"] += 1
        else:
            for i in reversed(order):
                if remainder == 0:
                    break
                lines[i]["amount_cents"] -= 1
                remainder += 1
    return lines
