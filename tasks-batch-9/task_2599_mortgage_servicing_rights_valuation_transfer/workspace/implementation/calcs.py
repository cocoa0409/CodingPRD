"""The eleven normative calculations plus the derived / computed field helpers."""
from decimal import Decimal

from core import (DB, D, fail, floor_int, now_date, rhu, rhu_int, rows, sort_created)

# --------------------------------------------------------------------------
# Calculation 1 constants -- msr_fair_value
# --------------------------------------------------------------------------
DQ_COST_MULTIPLIER = {
    "CURRENT": D("1.0"),
    "DQ_30_59": D("1.5"),
    "DQ_60_89": D("2.5"),
    "DQ_90_PLUS": D("4.0"),
    "FORECLOSURE": D("6.0"),
}
LOSS_MIT_SURCHARGE_CENTS = {
    "NONE": D(0),
    "TRIAL_MOD": D(2000),
    "PERMANENT_MOD": D(1000),
    "FORBEARANCE": D(1500),
}
REFERENCE_RATE_BPS = D(4000)
OAS_SCENARIOS = (
    ("DOWN_50", D("1.50"), D("-0.50"), D("0.25")),
    ("BASE", D("1.00"), D("0.00"), D("0.50")),
    ("UP_50", D("0.60"), D("0.50"), D("0.25")),
)
OAD_FACTOR = {
    "TBA_LONG": D("4.5"),
    "SWAPTION_RECEIVER": D("6.0"),
    "TREASURY_FUTURE_LONG": D("5.5"),
}
RATING_PENALTY = {"TIER_1": 0, "TIER_2": 10, "TIER_3": 25}


# --------------------------------------------------------------------------
# Portfolio-derived quantities (PRD section 3.2)
# --------------------------------------------------------------------------
def portfolio_loans(portfolio_id):
    return sort_created([l for l in rows("loans") if l["portfolio_id"] == portfolio_id])


def active_loans(portfolio_id):
    return [l for l in portfolio_loans(portfolio_id) if l["status"] == "ACTIVE"]


def portfolio_loan_count(portfolio_id):
    return len(active_loans(portfolio_id))


def portfolio_total_upb(portfolio_id):
    return sum(l["upb_cents"] for l in active_loans(portfolio_id))


def portfolio_wanr(portfolio_id):
    loans = active_loans(portfolio_id)
    total = sum(l["upb_cents"] for l in loans)
    if not loans or total == 0:
        return D("0.0000")
    weighted = sum((D(l["upb_cents"]) * l["note_rate_pct"] for l in loans), Decimal(0))
    return rhu(weighted / D(total), 4)


def portfolio_transfers(portfolio_id):
    """Servicing transfers reachable via bid packages -> purchase agreements."""
    pkg_ids = {p["id"] for p in rows("bid_packages") if p["portfolio_id"] == portfolio_id}
    agr_ids = {a["id"] for a in rows("agreements") if a["bid_package_id"] in pkg_ids}
    return [t for t in rows("transfers") if t["purchase_agreement_id"] in agr_ids]


def custodial_funds_total(portfolio_id):
    total = 0
    for loan in portfolio_loans(portfolio_id):
        total += loan["escrow_balance_cents"] + loan["suspense_balance_cents"]
    for transfer in portfolio_transfers(portfolio_id):
        total += transfer["escrow_transferred_cents"] + transfer["suspense_transferred_cents"]
    return total


# --------------------------------------------------------------------------
# Calculation 2 -- active_rate_curve_selection
# --------------------------------------------------------------------------
def active_curve():
    candidates = [c for c in rows("rate_curves") if c["status"] == "ACTIVE"]
    if not candidates:
        return None
    candidates.sort(key=lambda c: (c["as_of_date"], c["_created"], c["_seq"]), reverse=True)
    return candidates[0]


def require_active_curve():
    curve = active_curve()
    if curve is None:
        fail("ERR_NO_ACTIVE_RATE_CURVE", "no ACTIVE rate curve snapshot exists")
    return curve


def curves_ranked():
    ranked = sorted(rows("rate_curves"),
                    key=lambda c: (c["as_of_date"], c["_created"], c["_seq"]),
                    reverse=True)
    return ranked


# --------------------------------------------------------------------------
# Calculation 3 -- effective_valuation_selection
# --------------------------------------------------------------------------
def effective_valuation(portfolio_id):
    candidates = [r for r in rows("valuation_runs")
                  if r["portfolio_id"] == portfolio_id and r["status"] in ("COMPLETED", "STALE")]
    if not candidates:
        return None
    candidates.sort(key=lambda r: r["sequence_no"], reverse=True)
    return candidates[0]


def valuation_freshness(portfolio_id):
    run = effective_valuation(portfolio_id)
    if run is None:
        return "NONE"
    return "CURRENT" if run["status"] == "COMPLETED" else "STALE"


# --------------------------------------------------------------------------
# Calculation 1 -- msr_fair_value
# --------------------------------------------------------------------------
def _loan_value(loan, aset, discount_eff_pct, float_eff_pct, cpr, years):
    upb = D(loan["upb_cents"])
    cost = (D(aset["cost_to_service_annual_cents"]) * DQ_COST_MULTIPLIER[loan["delinquency_bucket"]]
            + LOSS_MIT_SURCHARGE_CENTS[loan["loss_mit_status"]])
    survival = Decimal(1) - cpr
    escrow = D(loan["escrow_balance_cents"])
    fee_bps = D(loan["servicing_fee_bps"])
    disc_base = Decimal(1) + discount_eff_pct / D(100)
    total = Decimal(0)
    for year in range(1, years + 1):
        begin_upb = upb * (survival ** (year - 1))
        end_upb = upb * (survival ** year)
        avg_upb = (begin_upb + end_upb) / D(2)
        gross_fee = avg_upb * fee_bps / D(10000)
        float_income = escrow * float_eff_pct / D(100)
        net_cash = gross_fee + float_income - cost
        discount_factor = Decimal(1) / (disc_base ** year)
        total += net_cash * discount_factor
    return max(0, rhu_int(total))


def _scenario_total(loans, aset, discount_eff_pct, float_eff_pct, cpr, years):
    return sum(_loan_value(l, aset, discount_eff_pct, float_eff_pct, cpr, years) for l in loans)


def msr_fair_value(portfolio_id, aset, curve, method):
    loans = active_loans(portfolio_id)
    years = aset["projection_years"]
    rate_delta_pct = (D(curve["base_rate_bps"]) - REFERENCE_RATE_BPS) / D(100)
    discount_eff_pct = aset["discount_rate_pct"] + rate_delta_pct
    float_eff_pct = aset["float_earnings_rate_pct"] + rate_delta_pct
    cpr = aset["cpr_pct"] / D(100)

    if method == "DETERMINISTIC_STATIC":
        value_cents = _scenario_total(loans, aset, discount_eff_pct, float_eff_pct, cpr, years)
        scenario_values = None
    else:
        scenario_values = {}
        weighted = Decimal(0)
        for label, cpr_mult, shift, weight in OAS_SCENARIOS:
            cpr_s = (aset["cpr_pct"] * cpr_mult) / D(100)
            total = _scenario_total(loans, aset, discount_eff_pct + shift,
                                    float_eff_pct + shift, cpr_s, years)
            scenario_values[label] = total
            weighted += weight * D(total)
        value_cents = rhu_int(weighted)

    total_upb = portfolio_total_upb(portfolio_id)
    if total_upb == 0:
        value_bps = D("0.00")
    else:
        value_bps = rhu(D(value_cents) * D(10000) / D(total_upb), 2)
    return {
        "value_cents": value_cents,
        "value_bps_of_upb": value_bps,
        "included_loan_count": len(loans),
        "effective_discount_rate_pct": rhu(discount_eff_pct, 4),
        "scenario_values": scenario_values,
    }


# --------------------------------------------------------------------------
# Calculation 6 -- tape_stratification
# --------------------------------------------------------------------------
def stratum_label(loan, scheme):
    if scheme == "BY_STATE":
        return loan["state_code"]
    if scheme == "BY_DELINQUENCY":
        return loan["delinquency_bucket"]
    rate = loan["note_rate_pct"]
    if rate < D("6.00"):
        return "LT_600"
    if rate < D("7.00"):
        return "600_699"
    return "700_PLUS"


def package_lines(package_id):
    return sort_created([t for t in rows("tape_lines") if t["bid_package_id"] == package_id])


def included_lines(package_id):
    """Tape membership -- every line still marked included, whatever the loan status."""
    return [l for l in package_lines(package_id) if l["included"]]


def countable_lines(package_id):
    out = []
    for line in package_lines(package_id):
        if not line["included"]:
            continue
        loan = DB["loans"].get(line["loan_id"])
        if loan is None or loan["status"] != "ACTIVE":
            continue
        out.append(line)
    return out


def tape_loan_count(package_id):
    return len(countable_lines(package_id))


def tape_upb_cents(package_id):
    return sum(l["upb_snapshot_cents"] for l in countable_lines(package_id))


def stratum_count(package_id):
    return len({l["stratum_label"] for l in countable_lines(package_id)})


def package_bid_count(package_id):
    return len([b for b in rows("bids") if b["bid_package_id"] == package_id])


# --------------------------------------------------------------------------
# Calculation 4 -- reserve_price
# --------------------------------------------------------------------------
def reserve_price(package, run, portfolio):
    total_upb = portfolio.get("frozen_total_upb_cents")
    if total_upb is None:
        total_upb = portfolio_total_upb(portfolio["id"])
    if total_upb == 0:
        return 0
    raw = (D(run["value_cents"]) * package["reserve_price_floor_pct"] / D(100)
           * D(tape_upb_cents(package["id"])) / D(total_upb))
    return rhu_int(raw)


# --------------------------------------------------------------------------
# Calculation 5 -- bid value and purchase price
# --------------------------------------------------------------------------
def bid_value_cents(package_id, price_bps):
    return rhu_int(D(tape_upb_cents(package_id)) * D(price_bps) / D(10000))


def purchase_price(package_id, price_bps):
    buckets = {}
    for line in included_lines(package_id):
        buckets.setdefault(line["stratum_label"], 0)
        buckets[line["stratum_label"]] += line["upb_snapshot_cents"]
    breakdown = {}
    total = 0
    for label in sorted(buckets.keys()):
        upb = buckets[label]
        price = rhu_int(D(upb) * D(price_bps) / D(10000))
        breakdown[label] = {"upb_cents": upb, "price_cents": price}
        total += price
    return total, breakdown


# --------------------------------------------------------------------------
# Calculation 7 -- holdback_sizing
# --------------------------------------------------------------------------
def size_holdback(agreement):
    holdback = rhu_int(D(agreement["purchase_price_cents"]) * agreement["holdback_pct"] / D(100))
    agreement["holdback_cents"] = holdback
    agreement["holdback_retained_cents"] = holdback
    agreement["holdback_released_cents"] = 0
    agreement["holdback_applied_cents"] = 0
    agreement["settlement_wire_cents"] = agreement["purchase_price_cents"] - holdback


def resize_holdback_conditional(agreement):
    floor_amount = rhu_int(D(agreement["purchase_price_cents"]) * D(15) / D(100))
    holdback = max(agreement["holdback_cents"], floor_amount)
    agreement["holdback_cents"] = holdback
    agreement["holdback_retained_cents"] = holdback
    agreement["settlement_wire_cents"] = agreement["purchase_price_cents"] - holdback


# --------------------------------------------------------------------------
# Calculation 8 -- complaint_concentration_release
# --------------------------------------------------------------------------
def transfer_cases(transfer_id):
    return [c for c in rows("error_cases") if c["servicing_transfer_id"] == transfer_id]


def complaint_ratio_pct(transfer):
    denominator = transfer["transferred_loan_count"]
    if denominator == 0:
        return D("0.00")
    case_count = len(transfer_cases(transfer["id"]))
    return rhu(D(case_count) * D(100) / D(denominator), 2)


def release_pct_for_ratio(ratio):
    if ratio <= D("25.00"):
        return D(100)
    if ratio <= D("50.00"):
        return D(50)
    return None


def complaint_release(agreement, transfer):
    ratio = complaint_ratio_pct(transfer)
    release_pct = release_pct_for_ratio(ratio)
    if release_pct is None:
        fail("ERR_COMPLAINT_TIER_BLOCKS_RELEASE",
             "complaint concentration of %s%% blocks any release" % ratio)
    gross = rhu_int(D(agreement["holdback_retained_cents"]) * release_pct / D(100))
    remediation_total = sum(c["remediation_cents"] for c in transfer_cases(transfer["id"])
                            if c["status"] == "RESOLVED")
    cap = floor_int(D(gross) * D("0.40"))
    charge = min(remediation_total, cap)
    net = gross - charge
    return {"ratio": ratio, "release_pct": release_pct, "gross": gross,
            "remediation_total": remediation_total, "cap": cap,
            "charge": charge, "net": net}


# --------------------------------------------------------------------------
# Calculation 9 -- counterparty_transfer_risk_score
# --------------------------------------------------------------------------
def _clamp(value, low, high):
    return max(low, min(high, value))


def risk_score(counterparty, variant="PRE_AWARD"):
    rating_penalty = RATING_PENALTY[counterparty["servicer_rating"]]
    net_worth = counterparty["net_worth_cents"]
    if net_worth >= 1000000000:
        capital_penalty = 0
    elif net_worth >= 500000000:
        capital_penalty = 15
    else:
        capital_penalty = 30
    approval_penalty = max(0, (2 - len(counterparty["agency_approvals"])) * 8)
    base = _clamp(100 - (rating_penalty + capital_penalty + approval_penalty), 0, 100)

    complaint_penalty = 0
    sla_penalty = 0
    if variant == "POST_TRANSFER":
        completed = []
        for transfer in rows("transfers"):
            if transfer["status"] != "COMPLETED":
                continue
            agreement = DB["agreements"].get(transfer["purchase_agreement_id"])
            if agreement is not None and agreement["buyer_id"] == counterparty["id"]:
                completed.append(transfer)
        worst = D("0.00")
        ack_breaches = 0
        res_breaches = 0
        for transfer in completed:
            ratio = complaint_ratio_pct(transfer)
            if ratio > worst:
                worst = ratio
            for case in transfer_cases(transfer["id"]):
                if case["ack_breached"]:
                    ack_breaches += 1
                if case["resolution_breached"]:
                    res_breaches += 1
        complaint_penalty = min(30, rhu_int(worst * D(3)))
        sla_penalty = min(20, ack_breaches * 5 + res_breaches * 10)
        score = _clamp(base - (complaint_penalty + sla_penalty), 0, 100)
    else:
        score = base

    if score >= 80:
        tier = "LOW"
    elif score >= 60:
        tier = "MEDIUM"
    elif score >= 40:
        tier = "ELEVATED"
    else:
        tier = "HIGH"
    return {"variant": variant, "score": score, "tier": tier,
            "rating_penalty": rating_penalty, "capital_penalty": capital_penalty,
            "approval_penalty": approval_penalty, "complaint_penalty": complaint_penalty,
            "sla_penalty": sla_penalty}


# --------------------------------------------------------------------------
# Calculation 10 -- notice_statutory_window
# --------------------------------------------------------------------------
def notice_window(notice_type, effective_date, sent_date):
    if notice_type in ("TRANSFEROR_15DAY", "COMBINED"):
        lead_days = (effective_date - sent_date).days
        compliant = lead_days >= 15
    else:
        lead_days = (sent_date - effective_date).days
        compliant = 0 <= lead_days <= 15
    return lead_days, ("COMPLIANT" if compliant else "LATE")


# --------------------------------------------------------------------------
# Calculation 11 -- hedge_mark_to_market
# --------------------------------------------------------------------------
def hedge_mtm(position, current_base_rate_bps):
    raw = (D(position["notional_cents"]) * position["hedge_ratio_pct"] / D(100)
           * OAD_FACTOR[position["instrument"]]
           * (D(position["entry_base_rate_bps"]) - D(current_base_rate_bps)) / D(10000))
    return rhu_int(raw)


def open_hedge_mtm(portfolio_id):
    return sum(p["mark_to_market_cents"] for p in rows("hedge_positions")
               if p["portfolio_id"] == portfolio_id and p["status"] == "OPEN")


# --------------------------------------------------------------------------
# Transfer readiness (derived third dimension, PRD section 3.7)
# --------------------------------------------------------------------------
def derive_readiness(transfer):
    ready = (transfer["notice_status"] == "NOTICES_ATTESTED"
             and transfer["data_status"] == "RECONCILED"
             and transfer["pipeline_status"] == "PIPELINE_TRANSFERRED")
    transfer["readiness"] = "READY" if ready else "NOT_READY"


def transfer_notices(transfer_id):
    return sort_created([n for n in rows("notices")
                         if n["servicing_transfer_id"] == transfer_id])


def notice_counts(transfer_id):
    notices = transfer_notices(transfer_id)
    late = len([n for n in notices if n["compliance_status"] == "LATE"])
    return len(notices), late
