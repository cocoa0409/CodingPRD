"""Accumulation ledgers, notice threshold, filing sweep, forecast (PRD §2.5-2.7, §3).

Pinned rules (PRD §2.6):
  * The per-member specific sweep always completes before the aggregate sweep.
  * Each member's aggregate contribution is capped at
    aggregating_specific_deductible_cents when present, else the contract's
    specific_deductible_cents (mirroring rule); caps are integer cents applied
    per member before summation, with no rounding after the sum.

Accumulation window (PRD §2.5): [policy_year_start - run_in_days,
policy_year_end + run_out_days), half-open. The inclusion date is the claim's
service_date under a POLICY_YEAR contract and its paid_date under a PAID
contract. Run-out tails exist precisely to pull claims paid after year-end into
the contract, so a claim whose inclusion date sits inside the window is swept
into the contract's rows even when the contract has since EXPIRED (or been
RENEWED) — once a contract has bound coverage its ledger rows keep reflecting
their window; DRAFT contracts have no rows and insure nothing yet.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import db
from services.core import touch, find_specific_row, find_aggregate_row
from util import parse_dt

ACTIVATED_STATUSES = ("IN_FORCE", "EXPIRED", "RENEWED")


# ---------------------------------------------------------------------------
# Windows and inclusion
# ---------------------------------------------------------------------------

def window_bounds(contract):
    """Accumulation window [start - run_in, end + run_out) as datetimes."""
    start = parse_dt(contract["policy_year_start"])
    end = parse_dt(contract["policy_year_end"])
    return (start - timedelta(days=contract["run_in_days"]),
            end + timedelta(days=contract["run_out_days"]))


def core_bounds(contract):
    return parse_dt(contract["policy_year_start"]), parse_dt(contract["policy_year_end"])


def inclusion_dt(contract, claim):
    """The date that decides window membership, per the contract's basis."""
    if contract["contract_basis"] == "PAID":
        return parse_dt(claim["paid_date"]) if claim.get("paid_date") else None
    return parse_dt(claim["service_date"])


def covers(contract, claim):
    """Whether the claim's inclusion date sits inside the contract's window."""
    inc = inclusion_dt(contract, claim)
    if inc is None:
        return False
    lo, hi = window_bounds(contract)
    return lo <= inc < hi


def covers_core(contract, claim):
    """Whether the inclusion date is inside the bare policy year (no tails)."""
    inc = inclusion_dt(contract, claim)
    if inc is None:
        return False
    lo, hi = core_bounds(contract)
    return lo <= inc < hi


def check_window_ambiguity(plan_id, claim):
    """PRD §2.5 invariant, enforced at claim-payment time (validation 7).

    A claim found inside the accumulation windows of two contracts at once is
    rejected — but only where a run-in/run-out tail is what pulls the claim
    into at least one of them. Sibling contracts written on different bases
    over the same policy year legitimately cover the same claim through their
    core windows; the structural invariant protects the boundary between two
    consecutive contracts, where tails must never both cover one claim.
    """
    covering = [c for c in db["contracts"].values()
                if c["plan_id"] == plan_id and covers(c, claim)]
    if len(covering) < 2:
        return
    if all(covers_core(c, claim) for c in covering):
        return
    from errors import raise_error, ERR_CLAIM_WINDOW_AMBIGUITY
    raise_error(
        ERR_CLAIM_WINDOW_AMBIGUITY,
        "claim is covered by the run-in/run-out windows of two contracts simultaneously",
    )


# ---------------------------------------------------------------------------
# Lasers
# ---------------------------------------------------------------------------

def active_laser_for(contract_id, member_id):
    """The ACTIVE laser in force for (contract, member), if any.

    ACTIVE lasers for one member under one contract never overlap, so at most
    one governs any service instant; if several exist (adjacent windows) the
    latest-window one is the current override.
    """
    lasers = [l for l in db["lasers"].values()
              if l["contract_id"] == contract_id and l["member_id"] == member_id
              and l["status"] == "ACTIVE"]
    if not lasers:
        return None
    lasers.sort(key=lambda l: (l["effective_from"], l["_seq"]))
    return lasers[-1]


def applicable_specific_deductible(contract, member_id):
    laser = active_laser_for(contract["id"], member_id)
    if laser is not None:
        return laser["lasered_specific_deductible_cents"]
    return contract["specific_deductible_cents"]


# ---------------------------------------------------------------------------
# Specific sweep (per member)
# ---------------------------------------------------------------------------

def _sorted_scope_claims(contract, member_id=None):
    """PAID claims inside the contract's window, in the contract's chronological
    order: (service_date, created_at) under POLICY_YEAR, (paid_date, created_at)
    under PAID; creation sequence breaks residual ties."""
    claims = []
    for c in db["claims"].values():
        if c["status"] != "PAID":
            continue
        if c["plan_id"] != contract["plan_id"]:
            continue
        if member_id is not None and c["member_id"] != member_id:
            continue
        if not covers(contract, c):
            continue
        claims.append(c)
    claims.sort(key=lambda c: (inclusion_dt(contract, c), c["created_at"], c["_seq"]))
    return claims


def notice_threshold_hit(contract, accumulated_cents, deductible_cents) -> bool:
    """accumulated >= notice_threshold_pct * deductible, evaluated exactly
    (rational/decimal arithmetic — no floating-point blur at the boundary)."""
    threshold = Decimal(str(contract["notice_threshold_pct"]))
    return Decimal(accumulated_cents) >= threshold * Decimal(deductible_cents)


def recompute_specific_row(contract, member_id):
    row = find_specific_row(contract["id"], member_id)
    if row is None:
        return
    claims = _sorted_scope_claims(contract, member_id)
    accumulated = sum(c["paid_amount_cents"] for c in claims)
    deductible = applicable_specific_deductible(contract, member_id)
    excess = max(0, accumulated - deductible)
    notice = notice_threshold_hit(contract, accumulated, deductible)

    old_notice = row["notice_triggered"]
    if (row["accumulated_cents"] != accumulated or row["excess_cents"] != excess
            or row["applicable_deductible_cents"] != deductible
            or row["notice_triggered"] != notice):
        row["accumulated_cents"] = accumulated
        row["excess_cents"] = excess
        row["applicable_deductible_cents"] = deductible
        row["notice_triggered"] = notice
        touch(row)

    # Notice obligation flips ride along with the recompute (PRD §3.4).
    member = db["members"].get(member_id)
    if member is not None:
        if not old_notice and notice and member["notice_status"] == "NONE":
            member["notice_status"] = "NOTICE_PENDING"
            touch(member)
        elif old_notice and not notice and member["notice_status"] == "NOTICE_PENDING":
            member["notice_status"] = "NONE"
            touch(member)


# ---------------------------------------------------------------------------
# Aggregate sweep (whole plan)
# ---------------------------------------------------------------------------

def _posted_reimbursements_for_contract(contract_id):
    total = 0
    for r in db["reimbursements"].values():
        if r["status"] != "POSTED":
            continue
        filing = db["filings"].get(r["filing_id"])
        if filing is not None and filing["contract_id"] == contract_id:
            total += r["received_amount_cents"]
    return total


def recompute_aggregate_row(contract):
    row = find_aggregate_row(contract["id"])
    if row is None:
        return
    claims = _sorted_scope_claims(contract, member_id=None)
    cap = contract["aggregating_specific_deductible_cents"]
    if cap is None:
        cap = contract["specific_deductible_cents"]
    per_member = {}
    for c in claims:
        per_member[c["member_id"]] = per_member.get(c["member_id"], 0) + c["paid_amount_cents"]
    accumulated = sum(min(total, cap) for total in per_member.values())
    # Posting a reimbursement nets the reimbursed excess out of the plan's
    # unrecovered exposure (PRD §3.7).
    posted = _posted_reimbursements_for_contract(contract["id"])
    excess = max(0, accumulated - contract["aggregate_deductible_cents"] - posted)
    if (row["accumulated_cents"] != accumulated or row["excess_cents"] != excess
            or row["applicable_deductible_cents"] != contract["aggregate_deductible_cents"]):
        row["accumulated_cents"] = accumulated
        row["excess_cents"] = excess
        row["applicable_deductible_cents"] = contract["aggregate_deductible_cents"]
        row["notice_triggered"] = False
        touch(row)


def sweep_for_claim(claim):
    """Recompute every bound contract row whose window covers the claim.

    Order pinned (PRD §2.6): specific sweep first, aggregate second.
    """
    contracts = [c for c in db["contracts"].values()
                 if c["plan_id"] == claim["plan_id"]
                 and c["status"] in ACTIVATED_STATUSES
                 and covers(c, claim)]
    for contract in contracts:
        recompute_specific_row(contract, claim["member_id"])
    for contract in contracts:
        recompute_aggregate_row(contract)


# ---------------------------------------------------------------------------
# Filing sweep (PRD §3.5)
# ---------------------------------------------------------------------------

def recompute_filing(filing):
    """Chronological sweep over the filing's attached claims in PAID status,
    ordered by (service_date, created_at). Each line's eligible excess is the
    portion of the claim's paid dollars sitting above the applicable deductible
    given its chronological position:

        eligible_i = max(0, cum_i - ded) - max(0, cum_{i-1} - ded)
    """
    contract = db["contracts"].get(filing["contract_id"])
    if filing["filing_scope"] == "SPECIFIC":
        deductible = applicable_specific_deductible(contract, filing["member_id"])
    else:
        deductible = contract["aggregate_deductible_cents"]

    lines = [l for l in db["line_items"].values() if l["filing_id"] == filing["id"]]
    paid_lines = []
    for line in lines:
        claim = db["claims"].get(line["claim_id"])
        if claim is not None and claim["status"] == "PAID":
            paid_lines.append((line, claim))
        else:
            if line["eligible_excess_cents"] != 0:
                line["eligible_excess_cents"] = 0
    paid_lines.sort(key=lambda pair: (parse_dt(pair[1]["service_date"]),
                                      pair[1]["created_at"], pair[1]["_seq"]))
    running = 0
    total = 0
    for line, claim in paid_lines:
        before = running
        running += claim["paid_amount_cents"]
        # Portion of this claim's paid dollars sitting above the deductible
        # given its chronological position: the excess after the claim minus
        # the excess already attributable before it.
        eligible = max(0, running - deductible) - max(0, before - deductible)
        line["eligible_excess_cents"] = eligible
        total += eligible
    if filing["requested_amount_cents"] != total:
        filing["requested_amount_cents"] = total
        touch(filing)


# ---------------------------------------------------------------------------
# High-cost claimant forecast (PRD §3.9)
# ---------------------------------------------------------------------------

CREDIBILITY_FULL_MEMBER_COUNT = 500
MANUAL_PER_MEMBER_EXCESS_CENTS = 1200000
MANUAL_HIT_RATE = Decimal("0.04")


def compute_forecast(plan, forecast_basis, next_year_deductible, now):
    """Projection set: the plan's ACTIVE members with at least one PAID claim
    whose paid_date falls in the trailing 365 days before the logical instant."""
    window_start = now - timedelta(days=365)
    trailing = {}
    for member in db["members"].values():
        if member["plan_id"] != plan["id"] or member["status"] != "ACTIVE":
            continue
        total = 0
        count = 0
        for c in db["claims"].values():
            if c["member_id"] != member["id"] or c["status"] != "PAID" or not c.get("paid_date"):
                continue
            paid_dt = parse_dt(c["paid_date"])
            if window_start <= paid_dt < now:
                total += c["paid_amount_cents"]
                count += 1
        if count > 0:
            trailing[member["id"]] = total

    member_count = len(trailing)
    pure_excess = sum(max(0, t - next_year_deductible) for t in trailing.values())
    pure_count = sum(1 for t in trailing.values() if t >= next_year_deductible)

    if forecast_basis == "PURE_EXPERIENCE":
        return pure_excess, pure_count

    # CREDIBILITY_WEIGHTED: blend plan experience with the manual rate.
    # PRD §3.9 / §2.7: the credibility factor z is carried to two decimal
    # places before blending (e.g. 1/500 = 0.002 -> 0.00).
    z = min(Decimal(1), Decimal(member_count) / Decimal(CREDIBILITY_FULL_MEMBER_COUNT))
    z = z.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    manual_excess = member_count * MANUAL_PER_MEMBER_EXCESS_CENTS
    excess = (z * Decimal(pure_excess) + (Decimal(1) - z) * Decimal(manual_excess)
              ).to_integral_value(rounding=ROUND_HALF_UP)
    count = (z * Decimal(pure_count)
             + (Decimal(1) - z) * Decimal(member_count) * MANUAL_HIT_RATE
             ).to_integral_value(rounding=ROUND_HALF_UP)
    return int(excess), int(count)
