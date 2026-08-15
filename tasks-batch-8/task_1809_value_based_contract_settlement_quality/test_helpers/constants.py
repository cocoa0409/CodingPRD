"""Domain thresholds and logical-clock conventions (PRD §2.4, §2.6, §3).

The PRD names three windows — the reconciliation runout, the dispute window,
and the dispute-resolution window — without fixing their day counts. Tests
therefore place the logical clock at dates whose outcomes are invariant for
any plausible positive window length: finalize well past period_end, dispute
actions within a day of their anchor, and "window passed" a full year later.
"""

# --- Logical clock dates (PRD §2.4: all date decisions read this clock) ---
CLOCK_START = "2026-01-01T00:00:00Z"
CLOCK_MAR = "2026-03-01T00:00:00Z"
CLOCK_APR = "2026-04-01T00:00:00Z"
CLOCK_INTERIM = "2026-07-01T00:00:00Z"
CLOCK_RECONCILE = "2027-01-05T00:00:00Z"   # at/after period_end 2027-01-01
CLOCK_LATE_PAID = "2027-01-06T00:00:00Z"
CLOCK_FINALIZE = "2027-06-01T00:00:00Z"    # months past period_end: runout satisfied
CLOCK_DISPUTE = "2027-06-02T00:00:00Z"     # one day after finalize: filing window open
CLOCK_RESOLVE = "2027-06-03T00:00:00Z"     # one day after filing: resolution window open
CLOCK_WINDOW_PAST = "2028-06-01T00:00:00Z"     # a year past finalize: dispute window closed
CLOCK_RESOLUTION_PAST = "2028-06-03T00:00:00Z"  # a year past filing: resolution window elapsed

# Startup default stated in PRD §2.4.
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# --- Canonical contract terms (cents / basis points, PRD §2.6) ---
BENCHMARK_PMPM_CENTS = 100000
SHARED_SAVINGS_RATE_BP = 5000
SHARED_LOSS_RATE_BP = 4000
MIN_SAVINGS_RATE_BP = 200       # MSR, >= comparison (PRD §3.3)
MIN_LOSS_RATE_BP = 200          # MLR, <= comparison on the negated rate
SAVINGS_CAP_BP = 1000
LOSS_CAP_BP = 800
STOP_LOSS_CENTS = 2000000
WITHHOLD_RATE_BP = 500
QUALITY_GATE_FLOOR_POINTS = 30
QUALITY_GATE_EXCELLENCE_POINTS = 80

# --- Rollup constants (PRD §3.6) ---
DEFAULT_SCORE_MILLI = 1000

# --- Interim completion factors in milli (PRD §3.9) ---
COMPLETION_MILLI = {1: 150, 2: 320, 3: 480, 4: 620, 5: 740, 6: 850,
                    7: 910, 8: 950, 9: 970, 10: 985, 11: 995}

# --- Renewal thresholds (PRD §3.13) ---
RENEW_MIN_SAVINGS_BP = 100
QUALITY_DROP_TOLERANCE = 5

# --- Canonical expected rollup values (derived from the PRD formulas) ---
# Two-member canonical population: M1 12 member-months + M2 6 member-months,
# no FINAL risk scores -> default 1000 milli each (PRD §3.6).
CANON2_TOTAL_MEMBER_MONTHS = 18
CANON2_BENCHMARK_CENTS = 1800000
# Single-member population: M1 12 member-months at default score.
SINGLE_TOTAL_MEMBER_MONTHS = 12
SINGLE_BENCHMARK_CENTS = 1200000

# Canonical quality gate outcome for the dual-measure catalog with
# HBA1C 350/1000 (3 points, weight 9000) and MAMMO 50/1000 (0 points, weight
# 1000), both LOCKED: composite round_half_up(27000*100/(9*10000)) = 30, which
# equals the floor -> sliding branch base multiplier 5000 (PRD §3.10).
CANON2_COMPOSITE_POINTS = 30
CANON2_MULTIPLIER_BP = 5000
# Single-measure catalog HBA1C 350/1000 weight 10000 LOCKED: composite
# round_half_up(3*10000*100/(9*10000)) = 33 -> multiplier 5000 + 300 = 5300.
SINGLE_COMPOSITE_POINTS = 33
SINGLE_MULTIPLIER_BP = 5300

# Single-member journey, one PAID claim of 400,000 cents:
#   pool = round_half_up(400000*500/10000) = 20000 (per claim, PRD §3.7)
#   gross = 800000; rate = trunc(800000*10000/1200000) = 6666 >= MSR
#   shared = min(round(800000*0.5), round(1200000*0.1)) = 120000 (cap binds)
#   adjusted = round(120000*0.53) = 63600; released = round(20000*0.53) = 10600
SINGLE_CLAIM_AMOUNT = 400000
SINGLE_NET_PAYABLE_CENTS = 74200
# Same journey with an additional 100,000-cent PAID claim:
#   pool = 25000; gross = 700000; rate = 5833; shared = 120000 (cap);
#   adjusted = 63600; released = round(25000*0.53) = 13250
TWO_CLAIM_NET_PAYABLE_CENTS = 76850
# After voiding the 100,000-cent claim the figures return to the single-claim
# values (PRD §3.7 recompute).
POST_VOID_NET_PAYABLE_CENTS = 74200

# Two-member canonical journey, claims 400,000 (M1) + 700,000 (M2):
#   actual = 1100000; pool = 20000 + 35000 = 55000; gross = 700000
#   rate = trunc(700000*10000/1800000) = 3888; shared = min(350000, 180000) = 180000
#   adjusted = 90000; released = 27500; forfeited = 27500; net = 117500
CANON2_NET_PAYABLE_CENTS = 117500

# Interim report over the single-member journey with claims 400,000 + 100,000
# paid by 2026-04-01, months_elapsed 6 (PRD §3.9):
#   ytd = 500000; annualization estimate = round(500000*12/6) = 1000000
#   gross = 200000; rate = 1666 >= MSR; shared = min(100000, 120000) = 100000
#   interim composite 33 -> multiplier 5300 (VALIDATED and LOCKED both count)
#   est_net = round(100000*0.53) + round(25000*0.53) = 53000 + 13250 = 66250
#   reserve = round(66250*6/12) = 33125
INTERIM_RESERVE_ACCRUAL_CENTS = 33125
