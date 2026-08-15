"""In-memory data store. All state lives in module-level dicts keyed by id.

The store starts completely empty on every boot — no seeding, preloading,
or hardcoded entity data. The test harness restarts the server before every
test, so all preconditions are built via the declared API surface.
"""

# Entity collections, keyed by resource id (UUID strings)
firms = {}
clients = {}
matters = {}
fee_arrangements = {}
phase_budgets = {}
time_entries = {}
timekeepers = {}
write_down_requests = {}
budget_amendments = {}
accrual_reports = {}
collar_true_ups = {}
