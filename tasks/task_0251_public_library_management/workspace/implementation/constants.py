"""System-wide constants drawn from PRD §3 / SCAFFOLD §1.2-1.3.

Branch policy knobs (loan_period_days, grace_days, fine rates, thresholds, the
reservation buffer) are PER-BRANCH inputs and live on the Branch record, not
here. The values below are the global, non-overridable constants.
"""

# Loan renewal cap (PRD §3.3 "maximum of two renewals"; SCAFFOLD MAX_RENEWALS=2).
MAX_RENEWALS = 2

# Hold pickup window length in days. PRD §3.6 / SCAFFOLD §1.1 name the constant
# PICKUP_WINDOW_DAYS as the offset added to ready_at to form pickup_deadline; no
# concrete numeric value is pinned in the contract, so we use the conventional
# 3-day hold-shelf window. Time-based tests drive the logical clock explicitly
# past pickup_deadline rather than depending on the precise width.
PICKUP_WINDOW_DAYS = 3
