"""Fee composition (PRD 2.7, 3.12) and reliability scoring (PRD 3.13).

Monetary precision: round-per-line-then-sum. Each line is rounded UP to whole
cents with ceil() at the line level, then the rounded lines are summed.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

from db import db

# Fee constants (scaffold 1.3 calculations.service_fee.constants).
BASE_FEE_CENTS = 7500
PER_PAGE_CENTS = 25
RUSH_FEE_CENTS = 5000
SKIP_TRACE_FEE_CENTS = 9000
FREE_ATTEMPTS = 1
TIER1_MAX = 3
ATTEMPT_RATE1_CENTS = 2500
ATTEMPT_RATE2_CENTS = 4000
STAKEOUT_FEE_CENTS = 12000
RUSH_LABOR_MULT = Decimal("1.5")

# Reliability constants (calculations.server_reliability_score.constants).
W_SERVED = Decimal("1.0")
W_NONEST = Decimal("0.5")


def _ceil_cents(value):
    """Round a numeric value up to a whole number of cents."""
    # value is an exact integer-cent quantity in all our line computations, but
    # we apply ceil at the line level as the PRD pins the rounding order.
    return int(math.ceil(value))


def _attempt_line(n):
    """Tiered per-attempt labor for n billable attempts (PRD 3.12)."""
    tier1 = max(0, min(n, TIER1_MAX) - FREE_ATTEMPTS)
    tier2 = max(0, n - TIER1_MAX)
    return tier1 * ATTEMPT_RATE1_CENTS + tier2 * ATTEMPT_RATE2_CENTS


def total_page_count(sr_id):
    return sum(
        d["page_count"]
        for d in db.documents.values()
        if d["service_request_id"] == sr_id
    )


def billable_attempt_count(sr_id):
    """Count of non-superseded attempts under the request's non-superseded
    assignments (PRD 3.12 final variant), regardless of outcome."""
    count = 0
    for a in db.attempts.values():
        if a["service_request_id"] != sr_id:
            continue
        if a["superseded"]:
            continue
        count += 1
    return count


def final_stakeout_count(sr_id):
    """Stakeouts whose status is SCHEDULED or COMPLETED (CANCELLED excluded)."""
    count = 0
    for s in db.stakeouts.values():
        if s["service_request_id"] != sr_id:
            continue
        if s["status"] in ("SCHEDULED", "COMPLETED"):
            count += 1
    return count


def filing_line_amount(sr_id):
    """Sum of non-voided FILING invoice lines for the request."""
    total = 0
    for line in db.invoice_lines.values():
        if line["service_request_id"] != sr_id:
            continue
        if line["kind"] != "FILING":
            continue
        if line["voided"]:
            continue
        total += line["amount_cents"]
    return total


def compute_fee(sr, variant):
    """Compute the service fee for a request (PRD 3.12).

    variant == 'quoted': billable_attempt_count fixed at 0; stakeout & filing
      lines absent.
    variant == 'final': realized attempt/stakeout/filing activity.
    """
    sr_id = sr["id"]
    rush = sr["rush"]

    base_line = BASE_FEE_CENTS
    printing_line = _ceil_cents(total_page_count(sr_id) * PER_PAGE_CENTS)
    rush_line = RUSH_FEE_CENTS if rush else 0
    skip_trace_line = SKIP_TRACE_FEE_CENTS if sr["skip_trace_requested"] else 0

    if variant == "quoted":
        n = 0
        stakeout_line = 0
        filing_line = 0
    else:
        n = billable_attempt_count(sr_id)
        stakeout_line = final_stakeout_count(sr_id) * STAKEOUT_FEE_CENTS
        filing_line = filing_line_amount(sr_id)

    attempt_line = _attempt_line(n)

    subtotal = (
        base_line + printing_line + rush_line + skip_trace_line
        + attempt_line + stakeout_line + filing_line
    )

    if rush:
        labor = attempt_line + stakeout_line
        # Rush uplift applies only to labor lines, after tiering, rounded up.
        rush_uplift = _ceil_cents(Decimal(labor) * (RUSH_LABOR_MULT - Decimal(1)))
        subtotal += rush_uplift

    return subtotal


def reliability_counts(server_id):
    """Tally served / nonest / walked across the server's assignments."""
    served = 0
    nonest = 0
    walked = 0
    for a in db.assignments.values():
        if a["server_id"] != server_id:
            continue
        if a["status"] == "COMPLETED":
            sr = db.service_requests.get(a["service_request_id"])
            terminal = a.get("request_terminal")
            if terminal == "SERVED":
                served += 1
            elif terminal == "NON_EST":
                nonest += 1
        elif a["status"] in ("REASSIGNED", "CANCELLED"):
            walked += 1
    return served, nonest, walked


def _score(good, base_pool):
    if base_pool < 1:
        base_pool = 1
    raw = Decimal(100) * good / Decimal(base_pool)
    if raw > Decimal(100):
        raw = Decimal(100)
    rounded = raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if rounded < Decimal(0):
        rounded = Decimal(0)
    if rounded > Decimal(100):
        rounded = Decimal(100)
    return float(rounded)


def realized_score(server_id):
    served, nonest, walked = reliability_counts(server_id)
    good = served * W_SERVED + nonest * W_NONEST
    base_pool = served + nonest + walked
    return _score(good, base_pool)


def projected_score(server_id):
    served, nonest, walked = reliability_counts(server_id)
    server = db.servers[server_id]
    good = served * W_SERVED + nonest * W_NONEST
    base_pool = served + nonest + walked + server["active_assignment_count"]
    return _score(good, base_pool)
