"""Distribution waterfall + commitment split + recycling (PRD §3.5, §3.6).

distribution_waterfall: four-tier American-style waterfall on the fund's
cumulative economics, evaluated strictly in order 1->2->3->4, each tier
consuming from a running remainder starting at gross_amount_cents.

  paid_in      = fund.total_called_cents          (before this event)
  prior_dist   = fund.total_distributed_cents      (before this event)
  pref_accrued = round_half_up(paid_in * pref_rate_bps / 10000 * pref_years)
  Tier 1 (ROC): roc_due = max(0, paid_in - prior_dist); t1 = min(remaining, roc_due)
  Tier 2 (Pref): pref_due = max(0, pref_accrued - max(0, prior_dist - paid_in))
                 t2 = min(remaining, pref_due)
  Tier 3 (Catch-up): target = round_half_up(t2 * carry / (10000 - carry))
                     t3 = min(remaining, round_half_up(target * gp_catchup / 10000))
  Tier 4 (Carry split): t4_gp = round_half_up(remaining * carry / 10000)
                        t4_lp = remaining - t4_gp
  lp_share = t1 + t2 + t4_lp ; gp_carry = t3 + t4_gp

Clawback: if cumulative LP receipts (prior LP + this lp_share) < pref_accrued,
  shortfall = pref_accrued - cumulative_lp_receipts
  gp_carry = max(0, gp_carry - shortfall); clawed-back added to lp_share;
  every allocation clawback_flag = true.
"""
from decimal import Decimal

import db
from services import allocation, dates, derive
from services.derive import round_half_up


def _pref_years(fund):
    # Simple, non-compounding; preferred years derived from vintage_year to the
    # event date (declaration time).
    now_year = dates.now_utc().year
    years = now_year - fund["vintage_year"]
    return max(0, years)


def _cumulative_lp_receipts_prior(fund_id):
    """Sum of lp_share_cents over the fund's events with status IN
    {DECLARED, PAID} (before this event)."""
    total = 0
    for e in db.distribution_events.values():
        if e["fund_id"] == fund_id and e["status"] in ("DECLARED", "PAID"):
            total += e["lp_share_cents"]
    return total


def run_waterfall(fund, gross_amount_cents):
    """Returns (lp_share_cents, gp_carry_cents, clawback_flag)."""
    paid_in = derive.fund_total_called(fund["id"])
    prior_dist = derive.fund_total_distributed(fund["id"])
    carry = fund["carry_rate_bps"]
    gp_catchup = fund["gp_catchup_rate_bps"]
    pref_years = _pref_years(fund)

    pref_accrued = round_half_up(
        Decimal(paid_in) * Decimal(fund["pref_rate_bps"]) / Decimal(10000) * Decimal(pref_years)
    )

    remaining = gross_amount_cents

    # Tier 1 — Return of Capital.
    roc_due = max(0, paid_in - prior_dist)
    tier1 = min(remaining, roc_due)
    remaining -= tier1

    # Tier 2 — Preferred Return.
    pref_due = max(0, pref_accrued - max(0, prior_dist - paid_in))
    tier2 = min(remaining, pref_due)
    remaining -= tier2

    # Tier 3 — GP Catch-up.
    if (10000 - carry) != 0:
        catchup_target = round_half_up(
            Decimal(tier2) * Decimal(carry) / Decimal(10000 - carry)
        )
    else:
        catchup_target = 0
    tier3 = min(
        remaining,
        round_half_up(Decimal(catchup_target) * Decimal(gp_catchup) / Decimal(10000)),
    )
    remaining -= tier3

    # Tier 4 — Carry split.
    tier4_gp = round_half_up(Decimal(remaining) * Decimal(carry) / Decimal(10000))
    tier4_lp = remaining - tier4_gp

    lp_share = tier1 + tier2 + tier4_lp
    gp_carry = tier3 + tier4_gp

    # Clawback: cumulative LP receipts (prior + this event) vs pref_accrued.
    prior_lp = _cumulative_lp_receipts_prior(fund["id"])
    cumulative_lp = prior_lp + lp_share
    clawback_flag = False
    if cumulative_lp < pref_accrued:
        shortfall = pref_accrued - cumulative_lp
        new_gp = max(0, gp_carry - shortfall)
        clawed_back = gp_carry - new_gp
        gp_carry = new_gp
        lp_share += clawed_back
        clawback_flag = True

    return lp_share, gp_carry, clawback_flag


def split_to_commitments(fund_id, lp_share_cents):
    """Split lp_share_cents across eligible commitments pro-rata by drawn_cents.

    Eligible: status IN {ACTIVE, DEFAULTED} and drawn_cents > 0.
    Returns (eligible_commitments, amount_by_commitment_id) or raises
    ERR_NO_PARTICIPATING_COMMITMENTS when empty.
    """
    import errors

    eligible = []
    weights = {}
    for c in db.commitments.values():
        if c["fund_id"] != fund_id:
            continue
        if c["status"] not in ("ACTIVE", "DEFAULTED"):
            continue
        drawn = derive.commitment_drawn(c)
        if drawn <= 0:
            continue
        eligible.append(c)
        weights[c["id"]] = drawn

    if not eligible:
        errors.fail(
            errors.ERR_NO_PARTICIPATING_COMMITMENTS,
            "No eligible commitment for the distribution split.",
        )

    amounts = allocation.largest_remainder_split(lp_share_cents, eligible, weights)
    return eligible, amounts


def recycle(fund, event):
    """Recall a recyclable PAID event into unfunded capacity (PRD §3.6).

    Returns recallable amount; mutates each affected commitment's
    recycled_restored_cents (reducing drawn_cents).
    """
    import errors

    cap_total = round_half_up(
        Decimal(fund["recycling_cap_pct_bps"])
        * Decimal(derive.fund_total_committed(fund["id"]))
        / Decimal(10000)
    )
    headroom = max(0, cap_total - derive.fund_recycled_to_date(fund["id"]))
    recallable = min(event["lp_share_cents"], headroom)
    if recallable <= 0:
        errors.fail(
            errors.ERR_RECYCLING_CAP_EXCEEDED,
            "Recall would exceed the recycling cap.",
        )

    lp_share = event["lp_share_cents"]
    allocs = [
        a
        for a in db.distribution_allocations.values()
        if a["distribution_event_id"] == event["id"]
    ]
    for a in allocs:
        if lp_share <= 0:
            share = 0
        else:
            share = round_half_up(
                Decimal(recallable) * Decimal(a["amount_cents"]) / Decimal(lp_share)
            )
        commitment = db.commitments.get(a["commitment_id"])
        if commitment is None:
            continue
        current_drawn = derive.commitment_drawn(commitment)
        share = min(share, current_drawn)  # never push drawn below 0
        if share > 0:
            commitment["recycled_restored_cents"] = (
                commitment.get("recycled_restored_cents", 0) + share
            )
            db.touch(commitment)

    return recallable
