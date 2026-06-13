"""Management-fee accrual (PRD §3.8, accrue_management_fee).

gross_fee per ACTIVE commitment on the fund:
  eff_rate_bps = max(0, fund.mgmt_fee_rate_bps - sideletter_discount_bps(lp, fund))
  contribution = round_half_up(committed_cents * eff_rate_bps / 10000 * days / 365)
gross_fee_cents = sum of per-commitment ROUNDED contributions (round PER
COMMITMENT then sum).

fee_offset variant (when fund.fee_offset_pct_bps > 0 and the fund has at least
one MANAGEMENT_FEE call whose period falls in the accrual period):
  offset_applied = min(gross_fee, round_half_up(
      sum(MANAGEMENT_FEE call called_amount_cents in period) * fee_offset_pct_bps / 10000))
  net_fee = max(0, gross_fee - offset_applied)
Otherwise offset_applied = 0 and net_fee = gross_fee.
"""
from decimal import Decimal

import db
from services import dates, sideletters
from services.derive import round_half_up

DAYS_PER_YEAR = 365


def compute_fee(fund, period_start_str, period_end_str):
    start_dt = dates.parse_dt(period_start_str)
    end_dt = dates.parse_dt(period_end_str)
    days = dates.whole_days(start_dt, end_dt)

    gross = 0
    for c in db.commitments.values():
        if c["fund_id"] != fund["id"] or c["status"] != "ACTIVE":
            continue
        discount = sideletters.sideletter_discount_bps(c["lp_id"], fund["id"])
        eff_rate = max(0, fund["mgmt_fee_rate_bps"] - discount)
        contribution = round_half_up(
            Decimal(c["committed_cents"])
            * Decimal(eff_rate)
            / Decimal(10000)
            * Decimal(days)
            / Decimal(DAYS_PER_YEAR)
        )
        gross += contribution

    # Offset variant.
    offset_applied = 0
    if fund["fee_offset_pct_bps"] > 0:
        mgmt_fee_calls_sum = 0
        has_qualifying = False
        for call in db.capital_calls.values():
            if call["fund_id"] != fund["id"] or call["purpose"] != "MANAGEMENT_FEE":
                continue
            # The call's period falls in the accrual period. The call's
            # temporal anchor is its due_date; treat it as in-period when it
            # lies within the half-open [period_start, period_end).
            due = dates.parse_dt(call["due_date"])
            if due is not None and start_dt <= due < end_dt:
                has_qualifying = True
                mgmt_fee_calls_sum += call["called_amount_cents"]
        if has_qualifying:
            candidate = round_half_up(
                Decimal(mgmt_fee_calls_sum)
                * Decimal(fund["fee_offset_pct_bps"])
                / Decimal(10000)
            )
            offset_applied = min(gross, candidate)

    net = max(0, gross - offset_applied)
    return gross, offset_applied, net
