# Step 7 — Diagnostic/Fix Loop Detail (task_1266)

## Iteration history

### Iteration 1 (baseline sweep)
8/8 rounds completed; deterministic (non-flaky) failure set, identical in every round:
89/94 passed. Union of failing tests (5):

1. `test_default_clock_pinned` (test_01_properties_and_envelope.py)
2. `test_retention_pinned_vs_rolling_expiry_diverge` (test_08_consent_lifecycle_and_retention.py)
3. `test_retention_expiry_alive_one_second_before` (test_08_consent_lifecycle_and_retention.py)
4. `test_sweep_escalation_cascade_depth3` (test_12_regulatory_sweeps.py)
5. `test_sweep_respond_after_deadline_auto_escalates` (test_12_regulatory_sweeps.py)

### Diagnosis (STEP 0-3)

All 5 failures shared one signature: test expected a system-stamped timestamp in
caller-input form `YYYY-MM-DDT00:00:00Z`, implementation rendered
`YYYY-MM-DDT00:00:00.000Z`.

- STEP 1a (coverage): PASS for all 5. PRD §2.4 pins the startup instant verbatim
  ("the logical clock reads exactly `2026-05-01T00:00:00Z`"); §2.5 pins the
  rendering of system timestamps ("`created_at` (string): an ISO 8601 UTC
  timestamp with three fractional digits, taken from the logical clock"); §2.10
  pins the expiry-horizon computation; §3.8 pins `response_due_at` =
  creation + deadline_days and the `escalated_at` stamp.
- STEP 1b (unique derivability): PASS. The only rendering convention the PRD
  states anywhere for system-stamped datetimes is three fractional digits; the
  `.000Z` form is the uniquely PRD-consistent rendering of the pinned instants
  (confirmed by the generation advisory: impl renders system stamps with 3
  fractional digits + Z and echoes caller-supplied datetimes verbatim; helpers
  were written against that convention — these 5 assertions were authoring slips).
- STEP 2: TEST IS WRONG in all 5 cases — assertions used the caller-input format
  instead of the system-rendered format. Fixed the assertions in test_suite/.
  No test_helpers fault (the suite-wide `is_iso8601_timestamp` helper checks were
  fine; only exact-string literals in these 5 tests were wrong).
- STEP 3: no implementation change — implementation is PRD-faithful
  (clock.py `format_iso` renders `%Y-%m-%dT%H:%M:%S.` + 3-digit ms + `Z`;
  changing it would violate §2.5 for `created_at`).

### Iteration 2 (post-fix sweep)
8/8 rounds: 94/94 passed each. ALL_CLEAN.

## Tests deleted
None.

## Fixes to test_helpers/
None.

## Fixes to test_suite/
- `test_01_properties_and_envelope.py` — `test_default_clock_pinned` — expected
  `created_at` changed `2026-05-01T00:00:00Z` -> `2026-05-01T00:00:00.000Z`
  (PRD §2.5 renders created_at with three fractional digits); dropped the
  now-unused `CLOCK_DEFAULT_ISO` import (constant kept in
  test_helpers/constants.py — it correctly records the §2.4 clock instant).
- `test_08_consent_lifecycle_and_retention.py` —
  `test_retention_pinned_vs_rolling_expiry_diverge` — expected
  `expires_at_pinned` -> `2026-06-09T00:00:00.000Z` and `expires_at_rolling` ->
  `2026-05-20T00:00:00.000Z`.
- `test_08_consent_lifecycle_and_retention.py` —
  `test_retention_expiry_alive_one_second_before` — expected
  `expires_at_pinned` -> `2026-05-31T00:00:00.000Z`.
- `test_12_regulatory_sweeps.py` — `test_sweep_escalation_cascade_depth3` —
  expected `escalated_at` -> `2026-05-01T00:00:00.000Z`.
- `test_12_regulatory_sweeps.py` — `test_sweep_respond_after_deadline_auto_escalates`
  — expected `response_due_at` -> `2026-05-06T00:00:00.000Z`.

## Fixes to implementation/
None.

## Final sweep evidence (passed/total per round)
round 1: 94/94
round 2: 94/94
round 3: 94/94
round 4: 94/94
round 5: 94/94
round 6: 94/94
round 7: 94/94
round 8: 94/94
