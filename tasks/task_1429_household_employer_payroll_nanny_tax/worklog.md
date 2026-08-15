# Worklog — task_1429_household_employer_payroll_nanny_tax

## Step 1: Create Task Directory — 2026-08-13T06:16:18.000Z

Pre-assigned task directory `tasks/task_1429_household_employer_payroll_nanny_tax/` with `workspace/` subdirectory already existed (created by the pipeline dispatcher). No index scan or new directory creation performed; Step 1 treated as DONE per invocation instructions.

## Step 2: Generate Scaffold — 2026-08-13T07:34:00.000Z

Scaffold generation complete. All three artifacts written to `/home/ubuntu/github/CodingPRD/tasks/task_1429_household_employer_payroll_nanny_tax/`, generated purely from the scenario text and the skill spec (no sibling tasks were read).

**Files written**
- `SCAFFOLD.yaml` (1154 lines) — §1.0–§1.7: scenario verbatim, response envelope verbatim, 14 entities, 11 state machines, 2 OCC concurrency rules, 11 calculations, 32 ordered validations, 58 endpoints, 30 error codes, 4 roles.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (822 lines) — single key `scaffold_difficulty_design`, 19 instances: all 9 rules at ≥2 instances, with `combinatorial_formula` at 3 (one per mode a/b/c).
- `SCAFFOLD_CORNER_DESIGN.yaml` (1178 lines) — single key `scaffold_corner_design`, 66 instances (57 active + 9 `excluded_because` stubs) across all 9 claim-extraction-guide sections.

**Counts**: 14 entities / 11 state machines / 11 calculations / 2 OCC rules; 19 difficulty instances; 66 corner instances (57 active, 9 stubs). Instance names verified unique across the union.

**Lint verdict (verbatim)**:
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(58 endpoints, 14 entities, 19 §1.8 + 57 §1.9 active instances, 849 calls scanned; 0 violations.)

**Notable design decisions**
- Profile: `compliance_audit` × `ledger_reconciliation`; layers: optimistic concurrency, cascading side effects, dual-variant calculation, rate/threshold triggers; role model `segregation_of_duties` (filing preparer's X-User-ID ≠ submitter's, enforced via `ERR_SEGREGATION_OF_DUTIES`).
- Harder-than-expert depth lives in the mechanics, not surface volume: retroactive FICA coverage at exactly $2,800 YTD (crossing check withholds catch-up on earlier untaxed wages), FUTA $1,000 quarterly household trigger, per-line-then-sum withholding rounding (pinned so 300100-cent gross yields 37962 withheld vs the forbidden 37963), fluctuating-workweek circular rate pinned to a 4-decimal evaluation order, and a safe-harbor deposit `min(projected, 1.10 × prior_year)` with a pinned 6-step order.
- Cascades: timesheet-approve → worker YTD/leave → pay-run STALE → paycheck `basis_stale` (depth 4, gates finalize with `ERR_PAYRUN_STALE`); late deposit → tiered penalty → FICA_ER account mutation → employer posture ATTENTION (depth 3).
- Two OCC rules (registration create on `HouseholdEmployer.version`, agreement create-with-supersede on `DomesticWorker.version`); all time rules run on a logical clock defaulting to 2026-08-01T00:00:00Z per spec.
- Interval semantics deliberately differ: half-open timesheet/pay-run periods vs closed leave-request intervals; money is integer cents, time is integer minutes, leave accrual is `floor(approved_minutes/30)` capped at 2400.
- Every numeric assert in §1.8/§1.9 was precomputed by hand-executing the formulas (e.g., FWW effective rate 39.8671 → gross 132159; Q1 deposit requirement 620295, 10-day-late penalty 31015, waterfall unapplied 520558).

## Step 3: Copy Shared Files — 2026-08-13T07:35:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1429_household_employer_payroll_nanny_tax/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T07:44:00.000Z

PRD generation complete. Summary report below.

---

## Summary

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_1429_household_employer_payroll_nanny_tax/workspace/PRD.md`
**Line count:** 359

### Section structure
- **§1 Introduction** — 2 paragraphs from business pain-point angle (household employer compliance burden + the two architectural invariants: integer cents/minutes and the logical clock)
- **§2 Global Specifications (10 subsections)** — RBAC + identity kinds, response envelope (verbatim §2.2), pagination, common resource properties, logical clock + date interval discipline (half-open vs closed), money/minutes/rounding, OCC, validation pipeline ordering (11 tiers), employer compliance posture, status codes + left-to-right path traversal
- **§3 Business Logic (12 subsections)** — organized by entity lifecycle: rule packs → employer onboarding → registrations → worker classification/agreements/activation → timesheets + approval cascade → pay runs + gross variants + finalize/void → leave → FICA/FUTA/SUTA mechanics → liability accounts + deposits + safe-harbor → quarterly filings + segregation of duties → workers' comp → year-end packages
- **§4 Endpoint table** — 58 endpoints, 4 columns (Method, Path, Description, Authorized Roles)
- **§5 Error catalogue** — 30 errors, 2 columns (Error ID, HTTP Status)

### Hard contract audit results

**Contract 1 — Field-Name Coverage: PASS**
- 110 required identifiers (entity fields + endpoint inputs + query params + path params + pagination)
- 110 present in backticks, **0 missing** (after one repair: `regular_minutes` added inline in §3.6 hourly-gross paragraph)

**Contract 2 — Rule Coverage: PASS**
- All 25 distinct state values appear in PRD prose (uppercase, backticked)
- All 30 error IDs appear in §2/§3 narrative with trigger context
- All 11 calculation rules expressed in prose (classification scoring, hourly OT with pinned daily→weekly→top-up order and 1.5x rounding rule, FWW 4-decimal effective rate + 0.5x premium, withholding per-line-rounding-first rule, FICA $2,800 retroactive coverage with catch-up base, FUTA $1,000 quarterly trigger + $7,000 wage base, SUTA per-pack base, 6-step safe-harbor, 30-min-divisor leave accrual with 40-hour cap, tiered late-deposit penalty 0/2/5/10%, Schedule H aggregation + 90%/110% underpayment legs)
- All state-machine transitions expressed with `from`/`to` states, preconditions paired with error IDs, side effects (incl. cross-entity cascades: timesheet approval → worker YTD + pay-run STALE + paycheck `basis_stale`; finalize → 5 lazy `TaxLiabilityAccount` rows in fixed order; void → REVERSAL_PENDING + YTD decrement + accrual reversal)
- Both OCC rules expressed with `expected_employer_version` / `expected_worker_version` + `ERR_STALE_VERSION` + HTTP 412
- Validation pipeline priority ordering expressed as an 11-tier numbered list in §2.8
- Sibling branches treated with equal density (e.g., bind/lapse/expire sweeps; QUOTED/BOUND/ACTIVE/LAPSED/EXPIRED transitions; LIVE_IN vs LIVE_OUT variants; provisional vs final paycheck variants)

**Contract 3 — §3 Path Purity: PASS**
- 656 backticked tokens scanned in §3
- 0 starting with `/`, 0 bare HTTP methods, 0 method+path combinations
- Endpoints referenced via state-transition framing (`DRAFT → SUBMITTED`), role + action verb ("A `PayrollAdmin` finalizes"), or capability description ("an admin-only test-driving capability advances the logical clock")

### Key design decisions

1. **§2 subsection grouping** — chose 10 subsections, domain-named (`Logical Clock and Date Discipline`, `Money, Minutes, and Rounding`, `Employer Compliance Posture`) rather than generic. §2.2 emitted verbatim.
2. **§3 organization** — 12 subsections following the natural lifecycle of the domain (jurisdiction → employer → registrations → workers → time → pay → leave → tax mechanics → deposits → filings → comp → year-end), not the example's 7-subsection shape.
3. **Constant embedding** — translated scaffold symbolic constants into business narrative with dollar equivalents: `FICA_COVERAGE_THRESHOLD_CENTS: 280000` → "280000 cents ($2,800)"; `FUTA_WAGE_BASE_CENTS: 700000` → "$7,000"; `SS_WAGE_BASE_CENTS: 17610000` → "$176,100"; `ADDL_MEDICARE_THRESHOLD_CENTS: 20000000` → "$200,000"; `ESTIMATED_PAYMENT_THRESHOLD_CENTS: 100000` → "$1,000"; `LEAVE_ACCRUAL_DIVISOR: 30` → "one hour of leave earned per 30 hours worked"; `LEAVE_ANNUAL_CAP_MINUTES: 2400` → "40 hours".
4. **No pseudocode** — every symbolic formula (`min`, `max`, `round_half_up`, arithmetic) rewritten as natural-language prose with operator direction preserved ("at least", "above", "strictly greater than", "floored at zero", "rounded half-up to cents before being multiplied").
5. **Scattering** — `guaranteed_minutes_per_week`, `hourly_rate_cents`, `pay_method` appear across §3.4 (agreement create) and §3.6 (gross calculation); `recalc_status` and `basis_stale` introduced in §3.5 (cascade origin) and resolved in §3.6 (calculate clears them); `compliance_posture` defined in §2.9 and re-referenced through §3.2, §3.3, §3.6, §3.9, §3.10, §3.11.
6. **Files explicitly not read** — `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were not opened, grepped, or referenced, per the hard constraint.

## Step 5: Generate Unit Tests — 2026-08-13T08:42:00.000Z

Generation complete. Summary:

## Files written

**`test_helpers/`** (under `/home/ubuntu/github/CodingPRD/tasks/task_1429_household_employer_payroll_nanny_tax/test_helpers/`):
- `types.py` — 20 status/role enums + 15 entity TypedDicts; `StateRulePack`/`TaxDeposit` correctly carry only `id` + `created_at` (no `version`/`updated_at`)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (62 methods incl. clock, registrations, filings, policies, year-end)
- `api_errors.py` — all 30 `ApiErrorId`s + HTTP map registered via `set_error_http_status_map`
- `assertions.py` — per-entity structural assertions, `line_amount()`, leave-balance and account-balance invariant checkers
- `factories.py` — payload factories per entity + `make_work_entries` + employee/contractor questionnaire presets
- `constants.py` — FICA 280000, SS base 17610000, FUTA trigger/base, leave divisor 30/cap 2400, periods-per-year, default clock 2026-08-01
- `test_users.py` — shared constants for opaque roles + mandatory per-instance builders for entity-backed roles (`make_household_client_headers(employer_id)`, `make_worker_headers(worker_id)`)
- `fixtures.py` — composite helpers: OCC-threaded registration/agreement creation (fresh parent version reads), `setup_registered_employer`, `setup_classified_worker`, `setup_active_worker`, `create_approved_timesheet`, `setup_calculated/finalized_pay_run`, `setup_worker_with_accrued_leave`, `setup_accepted_filing`, tax-account-by-type lookup
- `__init__.py` — barrel export

**`test_suite/`**: `conftest.py` + 9 test files, **94 tests total** (38 queue A + 56 queue B), organized by concern from simple onboarding to finalization/void, leave, deposits, filings/year-end, RBAC.

## Coverage verdicts

- **Queue A (Difficulty): 19/19 instances, each with exactly 2 tests** — all pre-computed values hand-verified against PRD formulas (e.g. FWW gross 132159, per-line rounding 262138 vs forbidden 262137, late-deposit penalty 31015, waterfall unapplied 520558, retroactive FICA catch-up SS base 300000).
- **Queue B (Corner): 56/57 non-stub instances covered** (≥1 test each). All 9 `excluded_because` stubs verified to resolve to real difficulty instances and not translated. Zero bogus/untagged/dual-tagged tests; every docstring ends with exactly one verbatim `Design:` line.
- **PRD citation audit: 140/140 quoted sentences survive verbatim grep of PRD.md** (whitespace-normalized, parsed-docstring level). No `skip`/`skipif`/`xfail` anywhere.

## Instances skipped (1, with reason)

- **`Corner/endpoints/worker_list_status_filter`** — fails the PRD-coverage condition: the PRD names an optional `status` filter only for registrations (§3.3) and agreements (§3.4); the workers-list endpoint row in §4 carries no filter mention. A PRD-only implementer could legitimately not implement the filter, so the asserted filtering outcome is not uniquely derived. Gap left as a gap (PRD bug, not test bug).

## Notable two-reader adjudications

- `employer_create_defaults_and_computed_fields`: the instance's `version == 1` pin is not PRD-derivable (PRD only requires +1 per mutation) — the test asserts type/presence instead of the absolute initial value.
- Multi-worker paycheck reads use `GET /workers/{id}/paychecks` rather than list indices where `created_at` ties could make ordering ambiguous; tax accounts are looked up by `tax_type` rather than list position.
- `leave_overlap_beats_balance` second test isolates the fiscal rule (non-overlapping, over-balance → `ERR_INSUFFICIENT_LEAVE_BALANCE`) per the validation-priority silence pattern — the priority-assertion test itself is legitimate because PRD §2.8 pins the pipeline order verbatim.

## Step 6: Generate Implementation — 2026-08-13T08:42:30.000Z

The implementation is complete and verified. Final summary:

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_1429_household_employer_payroll_nanny_tax/workspace/implementation/`:

- `start.sh` — guarded-install launcher (`pip install` only when flask/waitress missing), `exec python3 app.py`, foreground, `0.0.0.0:$PORT` (default 10000)
- `requirements.txt`, `app.py` (Flask entry, error handlers, waitress with Flask-dev fallback)
- `db.py` — 14 empty in-memory stores, logical clock (default exactly `2026-08-01T00:00:00Z`), monotonic `_seq` insertion counter for deterministic ordering under a frozen clock
- `errors.py` — all 30 catalog error IDs with their exact HTTP statuses
- `response.py` — envelope `{meta:{api_request_id, api_request_timestamp}, response_type, data}`; list meta adds `limit/offset/total_count/has_more`
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (401), role gating (403), entity-backed ownership for HouseholdClient (employer id) and Worker (worker id)
- `util.py` — body/date/pagination validation, Decimal half-up rounding
- `services/payroll.py` — gross variants + withholding; `services/tax.py` — accounts/safe-harbor/deposits/filings/year-end; `services/posture.py` — compliance posture; `services/serializers.py` — public shapes with fresh derivation of computed fields
- `routes/` — 14 blueprints: clock, employers, state_rule_packs, registrations, workers, agreements, timesheets, pay_runs, paychecks, leave_requests, tax (accounts+deposits), filings, policies, year_end

## Endpoints

All **52** endpoints from the scaffold table are implemented (1 clock, 4 employer, 2 rule-pack, 4 registration, 6 worker, 4 agreement, 6 timesheet, 7 pay-run, 3 paycheck, 5 leave, 3 tax-ledger, 6 filing, 4 policy, 3 year-end).

## State machines / calculations implemented

- **10 state machines**: employer (ONBOARDING↔ACTIVE/SUSPENDED with auto-activation on first ACTIVE registration), registration, worker (classify/activate/terminate with agreement cascade), agreement (auto-supersede with `effective_to = new_from − 1 day`), timesheet (DRAFT→SUBMITTED→APPROVED→LOCKED + reject loop + STALE cascade to pay runs and `basis_stale` on paychecks), pay run (OPEN→CALCULATED, STALE-recalc, FINALIZED), paycheck (parallel deposit/stub dimensions, void compensating reversal), leave (approve/deny/cancel with balance release), filing (PREPARED→SUBMITTED→ACCEPTED/REJECTED→re-prepare loop, segregation-of-duties), policy (QUOTED→BOUND→ACTIVE→EXPIRED/LAPSED with clock sweeps), year-end.
- **9 calculations**: classification score (≥3 → CONTRACTOR), hourly gross with pinned daily→weekly OT extraction and guarantee top-up (1.5x rate rounded half-up per-minute before multiplying), FWW premium (4-decimal effective rate), per-line-rounded withholding (SS/Medicare/Addl-Medicare/SIT/FIT; zero lines omitted), FICA $2,800 retroactive catch-up on the crossing check, FUTA $1,000 quarterly trigger (projected over the calculating run's own gross) with $7,000 wage base, SUTA per-state wage base, safe-harbor 6-step deposit requirement with 110% prior-year cap leg, tiered late-deposit penalty (2%/5%/10% on the *required* amount) landing on FICA_ER, waterfall deposit allocation in fixed account order, floor-based leave accrual (÷30, cap 2400), year-end Schedule H + W-2 lines + underpayment test.
- **OCC**: `expected_employer_version` / `expected_worker_version` → `ERR_STALE_VERSION` 412; parent version bumps on child creation.

## Notable decisions

- **Computed fields derived fresh on read** (worker YTD/FICA/leave fields, employer `compliance_posture`, account `projected_annual_cents`/`balance_cents`) so every cascade is immediately consistent without stored-denormalized drift.
- **`_seq` insertion counter** breaks `created_at` ties — essential because the frozen logical clock makes all timestamps identical within a test (e.g. the five tax accounts must list in fixed creation order FICA_EE, FICA_ER, FUTA_ER, SIT_EE, SUTA_ER).
- **Two-pass pay-run calculate**: gross for all members first so the FUTA quarterly trigger sees the whole run's wages, then tax lines in worker `created_at` order.
- Paycheck internal tax bases (`_ss_base_cents`, `_fica_base_cents`, …) retained on the record (never serialized) to power YTD derivations, W-2 wage bases, and void reversal with FICA-coverage-loss accrual reversal.
- No seeding at startup; store starts empty on every boot — verified.

## Verification

Booted repeatedly via `bash start.sh` from fresh processes; ran three smoke suites replaying every hand-computed scenario in SCAFFOLD_DIFFICULTY_DESIGN.yaml and the SCAFFOLD_CORNER_DESIGN.yaml behaviors (gross variants 142500/132159/148500, per-line rounding 262138, FICA boundary/catch-up 18600/4350, safe-harbor 620295/27500, waterfall splits, void invariant 120000/3120, STALE cascade, SoD 403s, OCC 412s, overlap adjacency, pagination envelope, policy sweeps, year-end figures 48715): **215/215 checks pass** across three independent fresh boots.

## Step 7: Run Tests and Iterate — 2026-08-13T08:55:10.000Z

## Summary

- **Iterations run:** 2 (first sweep: 46/94 failing identically in all 8 rounds — deterministic, no flakiness; second sweep: 94/94 passing in all 8 rounds).

- **Tests deleted:** None.

- **Fixes applied to `test_helpers/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1429_household_employer_payroll_nanny_tax/test_helpers/fixtures.py` — added `_ensure_rule_pack(state_code)` and called it at the top of `setup_registered_employer`. The composite fixture created the employer without first seeding the state's rule pack, violating the PRD §3.2 precondition ("The primary state must already have a rule pack — otherwise the create is rejected with `ERR_STATE_RULES_MISSING`"), so the PRD-faithful implementation correctly rejected every setup. This single fixture bug accounted for 45 of 46 failures. The ensure-step tolerates `ERR_DUPLICATE_RULE_PACK` so tests that pre-seed custom packs (e.g. `sit_rate=0.0`, `workers_comp_required=True`, custom OT thresholds in test_04/05/07) keep their own configuration.

- **Fixes applied to `test_suite/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1429_household_employer_payroll_nanny_tax/test_suite/test_03_timesheets.py` — added missing `setup_classified_worker` to the `test_helpers` import list; `TestTimesheetAgreementGate.test_timesheet_without_covering_agreement_returns_422` used it and died with `NameError` (1 failure).

- **Fixes applied to `implementation/`:** None — the implementation was already PRD-faithful; every failure traced to the two test-artifact bugs above.

Final state: 8/8 rounds at 94/94 passed under `--isolation per-test-server`. (Orchestrator-verified: all 8 `results.{i}.json` files show passed == total == 94.)

## Step 8: Finalize PRD — 2026-08-13T09:00:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1429_household_employer_payroll_nanny_tax/workspace/PRD_FINALIZED.md` is written and verified byte-identical to `PRD.md` — the correct outcome here, because neither `<step_7_diff>` item reveals a PRD silence or a PRD/impl mismatch.

## Summary on exit

**Line counts / %-delta:** PRD.md = 359 lines; PRD_FINALIZED.md = 359 lines; delta = 0%. `diff` confirms the files are identical.

**Changes:** None.

**Per-item analysis (the mandatory pre-edit search, performed for each candidate edit; both concluded "no edit"):**

1. **Step-7 item: `_ensure_rule_pack` added to `test_helpers/fixtures.py`, called at top of `setup_registered_employer`**
   - (a) Subject identified: the rule-pack precondition on creates (`ERR_STATE_RULES_MISSING`) and duplicate-pack rejection (`ERR_DUPLICATE_RULE_PACK`, which the fixture's ensure-step tolerates for idempotent seeding).
   - (b) Impl paths enumerated and read/grepped: `implementation/routes/employers.py:52-54` (employer create gate, firing before the pay-frequency floor check at lines 55-59, matching PRD §2.8 pipeline order 4→9→10); `implementation/routes/workers.py:72-73` (worker create gate); `implementation/routes/policies.py:52-53` (policy quote gate); `implementation/routes/state_rule_packs.py:51-53` (duplicate-pack 409); `implementation/errors.py:60,68` (status mapping 422/409); plus `services/posture.py::pack_for_state` usage. Also read `test_helpers/fixtures.py:111-138` to confirm the fix is fixture-side only.
   - (c) Wording adjustment: none — no edit made. Every enumerated path is already pinned verbatim by PRD §3.2 ("The primary state must already have a rule pack — otherwise the create is rejected with `ERR_STATE_RULES_MISSING` (HTTP 422)"), §3.4 (worker work-state gate), §3.11 (policy state gate), §3.1 ("a duplicate create is rejected with `ERR_DUPLICATE_RULE_PACK` (HTTP 409)"), and the §5 error catalogue. The step-7 fix repaired a fixture that violated an already-pinned precondition; the implementation was the correct party. Any PRD "clarification" here would have been redundant prose, and a stronger claim (e.g. pinning test-side idempotent seeding) would describe behavior the API does not exhibit — violating the NO-NEW-MISMATCH rule.

2. **Step-7 item: `test_suite/test_03_timesheets.py` — added missing `setup_classified_worker` import**
   - (a) Subject identified: Python `NameError` in test code (helper used at line 137, absent from the import block at lines 4-18).
   - (b) Impl paths enumerated: none exist — the item touches no API behavior. The underlying test asserts `ERR_NO_ACTIVE_AGREEMENT` on timesheet create without a covering agreement, already pinned by PRD §3.5 and implemented in `routes/timesheets.py`.
   - (c) Wording adjustment: none — pure test-artifact bug with zero PRD relevance.

**Conclusion:** The step_7_diff itself records "Fixes applied to `implementation/`: None — the implementation was already PRD-faithful," and both test-artifact fixes trace to behavior the PRD already uniquely determines (item 1) or to no behavior at all (item 2). Under the HARD SCOPE, the only faithful patch is the empty patch: PRD_FINALIZED.md = PRD.md, verbatim.

## Step 9: Complete PRD — 2026-08-13T10:07:51.000Z

All edits verified against the diff. The work is complete.

## Summary

**Source:** `PRD_FINALIZED.md` (identical to `PRD.md`) → **`/home/ubuntu/github/CodingPRD/tasks/task_1429_household_employer_payroll_nanny_tax/workspace/PRD_COMPLETED.md`**
- Lines: 359 → 363 (+4); chars: 59,645 → 64,678 (**+5,033**)
- Changes: **33 ambiguity-pins**, **5 mismatch-revisions** (38 total, all inline; no new sections)

### Changes

- **§2.1** — insert — ambiguity — empty/whitespace header values count as missing → `ERR_UNAUTHENTICATED` — `implementation/middleware.py:23`
- **§2.2** — insert — ambiguity — unknown path → `ERR_NOT_FOUND` 404; unsupported method → same error body with HTTP 405; unexpected failure → `ERR_INTERNAL` 500 — `implementation/app.py:51-61`
- **§2.3** — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST`; `created_at` ties broken by creation (insertion) order, never id — `implementation/util.py:25-49,206-207`
- **§2.4** — insert — ambiguity — `version` starts at 1 with `updated_at` == `created_at` at creation — `implementation/db.py:102-109`
- **§2.5** — insert — ambiguity — clock set is non-monotonic and returns 200 `{"current_utc": ...}`; all server timestamps (incl. `meta.api_request_timestamp`) render from the logical clock; serialized YTD/leave fields use the clock's calendar year — `implementation/routes/clock.py:17-33`, `response.py:22`, `services/serializers.py:77`
- **§2.8** — revise — **mismatch** — segregation-of-duties check runs after the `PREPARED` state precondition on filing submit, not in the authorization step — `implementation/routes/filings.py:100-103`
- **§2.8** — insert — ambiguity — explicit per-endpoint precondition orders (e.g. §3.4 activation) govern over the general pipeline — `implementation/routes/workers.py:166-192`
- **§2.9** — revise — ambiguity — RESTRICTED-posture policy must be for the worker's work state — `implementation/services/posture.py:33-45`
- **§3.2** — revise — ambiguity — `fein` must be exactly 9 digits; `prior_year_schedule_h_cents` is a non-negative integer — `implementation/routes/employers.py:48-50`, `util.py:158-162`
- **§3.3** — insert — ambiguity — registration create requires employer `ONBOARDING`/`ACTIVE` (else `ERR_INVALID_STATE`) — `implementation/routes/registrations.py:59-60`
- **§3.3** — revise — ambiguity — `agency_account_number` is a required non-empty string on activate — `implementation/routes/registrations.py:102`
- **§3.4** — insert — ambiguity — worker creation not gated on employer status; workers list has optional `status` filter — `implementation/routes/workers.py:59-73,109`
- **§3.4** — insert — ambiguity — answer values not enum-validated (non-literal = no point); extra question keys retained verbatim, ignored by score — `implementation/routes/workers.py:124-147`
- **§3.4** — insert — ambiguity — agreement creation not gated on worker status — `implementation/routes/agreements.py:48-100`
- **§3.4** — revise — **mismatch** — termination leaves timesheets in place: `DRAFT` ones still submittable, `SUBMITTED` ones no longer approvable (approval requires `ACTIVE` worker) — `implementation/routes/timesheets.py:115-143`
- **§3.5** — insert — ambiguity — `entries` may be empty and `worked_minutes` may be 0 (creatable, not submittable) — `implementation/routes/timesheets.py:68-85`
- **§3.5** — insert — ambiguity — timesheets list has optional `status` filter — `implementation/routes/timesheets.py:211`
- **§3.6** — insert — ambiguity — pay-runs list has optional `status` filter — `implementation/routes/pay_runs.py:163`
- **§3.6** — revise — ambiguity — calculate membership = current `ACTIVE` status with `hire_date` on or before `period_start`; `created_at` ties broken by creation order — `implementation/routes/pay_runs.py:77-95`
- **§3.6** — insert — ambiguity — STALE recalculation skips members lacking a covering `ACTIVE` agreement, leaving them unchanged with `basis_stale` retained — `implementation/routes/pay_runs.py:215-221`
- **§3.6** — insert — ambiguity — when both `APPROVED` and `LOCKED` timesheets cover the period, the `APPROVED` one governs basis — `implementation/services/payroll.py:132-148`
- **§3.6** — insert — ambiguity — FWW: zero total worked → effective rate 0.0000 and premium 0; FWW `regular_minutes`/`double_minutes`/`guarantee_top_up_minutes` derivations; `fww_effective_rate_cents_per_minute` null on `HOURLY` — `implementation/services/payroll.py:155-168,237-253`
- **§3.6** — revise — **mismatch** — SS base is min(this check's FICA base incl. catch-up, remaining SS room after YTD and same-run earlier bases), not min(gross, room) — `implementation/services/payroll.py:319-323`
- **§3.6** — revise — **mismatch** — only `gross_cents`-based lines are computed/persisted; no provisional withholding-line variant exists — `implementation/services/payroll.py:291-348`, `services/serializers.py:172-196`
- **§3.6** — revise — ambiguity — finalize workers-comp gate requires a policy for the member worker's work state — `implementation/routes/pay_runs.py:258-268`
- **§3.7** — revise — ambiguity — `ytd_approved_minutes` year attribution by `period_start` — `implementation/services/serializers.py:79-85`
- **§3.7** — insert — ambiguity — leave-requests list has optional `status` filter — `implementation/routes/leave_requests.py:143`
- **§3.8** — insert — ambiguity — calculate-time FUTA quarterly trigger projects the run's own member gross into `pay_date`'s quarter — `implementation/routes/pay_runs.py:180-188`, `services/payroll.py:72-94`
- **§3.9** — insert — ambiguity — line→account mapping pinned (`FICA_EE`←`SS_EE`+`MEDICARE_EE`+`ADDL_MEDICARE_EE`, `FICA_ER`←`SS_ER`+`MEDICARE_ER`; `FIT_EE` accrues to no account) — `implementation/services/tax.py:25-43`
- **§3.9** — revise — ambiguity — `projected_annual_cents` is 0 whenever `accrued_cents` is 0; per-period average rounded half-up to 4dp before multiplication, final projection rounded to cents — `implementation/services/tax.py:90-99`
- **§3.9** — revise — **mismatch** — safe-harbor per-period average kept at full precision (not 4dp); only the quarterly installment is rounded — `implementation/services/tax.py:114-127`
- **§3.9** — insert — ambiguity — deposit record carries the computed `penalty_cents` — `implementation/routes/tax.py:70-93`, `services/serializers.py:243`
- **§3.9** — insert — ambiguity — deposit `amount_cents` must be a non-negative integer — `implementation/routes/tax.py:55`
- **§3.9** — insert — ambiguity — tax-accounts and deposits lists have optional `tax_year` filter — `implementation/routes/tax.py:41,104`
- **§3.10** — insert — ambiguity — filings list has optional `tax_year` and `status` filters — `implementation/routes/filings.py:139`
- **§3.11** — insert — ambiguity — binding a policy whose `coverage_start` is already reached activates it immediately in the bind request; policies list has optional `status` filter — `implementation/routes/policies.py:76-81,103`
- **§3.12** — insert — ambiguity — new package born with `schedule_h_total_cents` null, `w2_lines` empty, `underpayment_penalty_applies` false — `implementation/routes/year_end.py:54-61`
- **§3.12** — revise — ambiguity — `w2_lines` ordered by worker `created_at` ascending — `implementation/services/tax.py:319-325`

Notable confirmed matches requiring no change: the full endpoint table (all 52 routes, methods, and role lists match), the pinned hourly/FWW gross formulas, safe-harbor six-step math, penalty tiers, posture rules, OCC endpoints, and all error-code/HTTP mappings.
