"""Domain thresholds and weights — numeric constants from the PRD.

Sources:
  - PRD §2.7 / §3.6: thank-you completion weights.
"""
# Thank-you completion weights (PRD §3.6).
W_SENT = 1.00
W_DRAFTED = 0.40
W_PENDING = 0.00

# Empty-set short-circuit value (PRD §3.6: "When n_total is zero — completion_pct is exactly 100.00").
EMPTY_COMPLETION_PCT = 100.00
