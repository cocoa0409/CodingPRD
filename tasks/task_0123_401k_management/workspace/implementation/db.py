"""In-memory data store for all entities.

Each top-level dict maps a UUID string to the entity dict.
A few secondary maps are kept for fast lookup (e.g., plan_clock by plan_id).
"""

# Plans by id
plans: dict = {}

# Participants by id
participants: dict = {}

# Contribution records by id
contribution_records: dict = {}

# Vesting snapshots by id
vesting_snapshots: dict = {}

# Loans by id
loans: dict = {}

# Loan repayments by id
loan_repayments: dict = {}

# Hardship withdrawals by id
hardship_withdrawals: dict = {}

# RMD schedules by id
rmd_schedules: dict = {}

# PlanClock by plan_id (one row per plan)
plan_clocks: dict = {}


# Audit log of (X-User-ID, X-User-Role, plan_id, action) — used for segregation-of-duties checks.
# Each entry: {"user_id": str, "role": str, "plan_id": str, "action": str,
#              "participant_id": str | None, "plan_year": int | None,
#              "loan_id": str | None, "hardship_id": str | None}
sod_audit: list = []


def reset_all():
    """Used by tests if needed."""
    plans.clear()
    participants.clear()
    contribution_records.clear()
    vesting_snapshots.clear()
    loans.clear()
    loan_repayments.clear()
    hardship_withdrawals.clear()
    rmd_schedules.clear()
    plan_clocks.clear()
    sod_audit.clear()
