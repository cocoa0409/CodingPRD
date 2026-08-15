"""Domain thresholds and standard-fixture expected values (PRD §3).

The standard fixture used across the suite:
- agreement: tier T1 day_rate_cents 100000, OT threshold 480 min, multiplier 1.5;
  meal_penalty_cents 2500; rest_penalty_cents 1000; turnaround_min_hours 10;
  PHW 0.06 / 0.085 / 0.012; residual base SYNDICATION 0.045.
- production jurisdictions: CA 0.10, NM 0.05.
- timecard TC-A: call 08:00, meal 14:30-15:00, wrap 19:00 on 2026-08-10,
  scheduled_hours 10 -> worked 630, OT 150, day_gross 146875, one MEAL unit.
"""

# PRD §3.6 / §3.7 penalty thresholds
MEAL_WINDOW_MINUTES = 360        # meal delay strictly greater than this is a violation
MIN_REST_MINUTES = 30            # break shorter than this is a REST violation

# PRD §3.14 garnishment cap
MAX_GARNISH_PCT = 0.25

# PRD §3.9 window discount
WINDOW_STEP_DISCOUNT = 0.10
WINDOW_DISCOUNT_FLOOR = 0.50

# PRD §3.6 day-rate conversion
HOURS_PER_DAY_RATE = 8

# Standard agreement constants
T1_DAY_RATE_CENTS = 100000
T1_OT_THRESHOLD_MINUTES = 480
T1_OT_MULTIPLIER = 1.5
T2_DAY_RATE_CENTS = 20000
MEAL_PENALTY_CENTS = 2500
REST_PENALTY_CENTS = 1000
TURNAROUND_MIN_HOURS = 10
PHW_PENSION_PCT = 0.06
PHW_HEALTH_PCT = 0.085
PHW_WELFARE_PCT = 0.012
SYNDICATION_BASE_PCT = 0.045
CA_TAX_PCT = 0.10

# Standard engagement window
ENGAGEMENT_START_DATE = "2026-08-03"
ENGAGEMENT_END_DATE = "2026-09-11"

# TC-A derived expectations (verified against the PRD §3.6/§3.7 formulas)
TCA_WORKED_MINUTES = 630
TCA_OVERTIME_MINUTES = 150
TCA_DAY_GROSS_CENTS = 146875
TCA_FINAL_PENALTY_CENTS = 2500
TCA_LINE_GROSS_CENTS = 149375        # 146875 day gross + 2500 CONFIRMED MEAL penalty
TCA_LINE_TAX_CENTS = 14938           # round_half_up(149375 x 0.10)
TCA_LINE_DISPOSABLE_CENTS = 134437   # 149375 - 14938
TCA_LINE_CAP_CENTS = 33609           # round_half_up(134437 x 0.25)
TCA_LINE_PHW_CENTS = 23453           # 8963 + 12697 + 1793 (per-component rounding)
TCA_PHW_PENSION_CENTS = 8963
TCA_PHW_HEALTH_CENTS = 12697
TCA_PHW_WELFARE_CENTS = 1793

# Standard residual expectations (SYNDICATION, receipts 20000000)
RESIDUAL_RECEIPTS_CENTS = 20000000
RESIDUAL_PROVISIONAL_CENTS = 4500    # round_half_up(100000 x 0.045)
RESIDUAL_FINAL_FIRST_WINDOW_CENTS = 900000   # 20000000 x 0.045 x 1.0
RESIDUAL_FINAL_SECOND_WINDOW_CENTS = 810000  # 20000000 x 0.045 x 0.90
