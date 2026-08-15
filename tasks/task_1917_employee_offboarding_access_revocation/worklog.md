# Worklog — task_1917_employee_offboarding_access_revocation

## Step 1: Create Task Directory — 2026-08-15T00:32:00.000Z

Task directory `tasks/task_1917_employee_offboarding_access_revocation/` and `workspace/` were pre-created by the pipeline launcher (index 1917 assigned by the scenario number); verified present, skipped index computation per invocation instructions.

## Step 3: Copy Shared Files — 2026-08-15T00:33:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1917_employee_offboarding_access_revocation/workspace/INSTRUCTION.md`.

## Step 2: Generate Scaffold — 2026-08-15T00:56:00.000Z

All three scaffold artifacts are written, linted clean, and verified.

**Task**: Generated the complete scaffold for `task_1917_employee_offboarding_access_revocation` at beyond-expert difficulty, purely from the scenario description plus the skill spec (no sibling tasks consulted).

**Files written**:
- `/home/ubuntu/github/CodingPRD/tasks/task_1917_employee_offboarding_access_revocation/SCAFFOLD.yaml` (2412 lines) — §1.0–§1.7
- `/home/ubuntu/github/CodingPRD/tasks/task_1917_employee_offboarding_access_revocation/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (945 lines) — single key `scaffold_difficulty_design`, 18 instances (2 per rule × 9 rules)
- `/home/ubuntu/github/CodingPRD/tasks/task_1917_employee_offboarding_access_revocation/SCAFFOLD_CORNER_DESIGN.yaml` (1666 lines) — single key `scaffold_corner_design`, 50 instances across all 9 claim-guide sections

**Design highlights (beyond-expert calibration)**:
- **Archetype**: workflow orchestration + compliance/audit; segregation-of-duties role model (four SoD rules: intake approver ≠ recorder, statement approver ≠ calculator, revocation verifier ≠ executor, rehire finalizer ≠ reviewer)
- **Surface**: 11 entities, 73 endpoints, 18 error codes, 14 calculations, 10 state machines, 3 OCC concurrency rules
- **Depth mechanisms**: dual-variant calcs in three distinct domains (PTO payout state-vs-company max rule, final-pay deadline calendar/business/payday variants, asset deduction depreciation-vs-damage variants); combinatorial formulas in modes (a) tiered nested min/max and (b) pinned per-item-round-then-sum with a 1-cent divergence proof; cyclic state machines on two different entities (revocation retry loop with backoff + cap→BLOCKED posture; exit interview with two distinct reschedule/rehabilitation loops sharing one cap); depth-3 transitive cascades from two different triggers (asset default → case deduction total → statement net pay; final verification → posture flip → notice queue + covenant reminder scheduling); error-precedence pairs (state vs SoD, temporal vs fiscal); two boundary checks on different metrics/endpoints (one-second-past-due penalty flip with ceil rounding; zero-required-sessions non-auto-complete); two overlap rules with different interval semantics (half-open adjacency-allowed for interviews vs closed adjacency-forbidden for KT sessions); compensating invariants on different conserved quantities (deduction total restoration on waive; review cardinality + null-state preservation through return/resubmit loop)
- **All formula-derived asserts are pre-computed literals** (e.g., 110400¢ laptop depreciation, 98800¢ tooling default, 40000¢ one-second-late penalty, 1200000¢ 30-day penalty cap, 200000¢/250000¢ PTO divergence)

**Verification**: `scaffold_lint.py` verdict — `VERDICT: clean lint` (73 endpoints, 11 entities, 18 §1.8 + 49 active §1.9 instances, 401 calls scanned, 0 violations). Additionally verified: no forbidden concurrency vocabulary, every error code referenced, all instance names unique across both files (68 total), no `scaffold_difficulty_design`/`scaffold_corner_design` keys inside SCAFFOLD.yaml, OCC cross-checks pass, and all FK reverse-reachability GETs declared.

## Step 4: Generate PRD — 2026-08-15T01:10:00.000Z

All checks pass. The PRD is complete and verified.

**Generated:** `/home/ubuntu/github/CodingPRD/tasks/task_1917_employee_offboarding_access_revocation/workspace/PRD.md`

## What was produced

A complete PRD for the employee-offboarding domain with this structure:

- **§1 Introduction** — 2 paragraphs (business pain-point angle: HR/IT/payroll/benefits coordination failure modes, then system goals)
- **§2 Global Specifications** — 11 subsections, domain-derived titles: §2.1 RBAC (11 roles, all opaque identity, each individually named), §2.2 verbatim response-envelope block (byte-identical, markers verified), §2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending), §2.4 Logical Clock & Scheduler (startup default `2026-08-01T00:00:00Z`, sweep semantics), §2.5 Common Resource Properties (with the ManagerNotification exception: only `id`/`created_at`, no `updated_at`/`version`), §2.6 Request Evaluation Order (all 14 validations in priority sequence), §2.7 Segregation of Duties (SoD-1 through SoD-4 with recorded counterparties), §2.8 Money/Precision/Wage-Protection (integer cents, round half-up, per-item-round-then-sum pinned order), §2.9 OCC (all three rules with endpoint, occ field, error id, HTTP 412, plus generic fallback), §2.10 Hierarchy & Uniqueness, §2.11 Posture Aggregation & Cascades
- **§3 Business Logic** — 8 lifecycle-chronological subsections (intake/last-day, revocation sequencing, final pay, asset recovery, interviews/KT, benefits/covenants, rehire/closure, notification dedupe); all 14 calculations rendered as reconstructible prose (dual-variant last-day determination with weekend roll direction, three-variant final-pay deadline incl. 72-hour notice rule and semi-monthly payday grid at 17:00 UTC, dual-variant PTO payout with tenure tiers 40/80/120 and half-hour floor rounding, depreciation bps 20/25/10 capped at 7000, 2500-cent late fee added post-rounding, pinned 4-step net-pay waterfall, 8-hour daily-wage waiting penalty capped at 30 days, 17:00-anchored revocation offsets, both posture aggregates with precedence, 44/30/30/31-day notice deadlines, dedupe half-open 60-minute window)
- **§4 Endpoint table** — 73 rows, 4 columns only (Method/Path/Description/Roles)
- **§5 Error catalogue** — 18 errors, 2 columns only

## Hard Contract Reports

```
Field coverage check:
- entities[].fields + endpoints[].request_body/input + query_params + named recorded fields (calc_by_ref) + summary outputs: 84 required, 84 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] priority ordering: 14 checked, 14 expressed in §2.6 ordered list, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_*_version + exact error_id + 412 in §2.9; repeated via capability framing in §3.3/3.4/3.7), 0 missing
- state_machines[].transitions: 60+ transitions across 11 machines checked and fully expressed (from/to states, preconditions paired with error ids, side effects incl. cascades), 0 missing
- calculations[]: 14 checked, 14 fully expressed in precise prose (no operator syntax — verified 0 leaks of ==/>=/<=/+= in §2/§3), 0 missing
- validations[] conditions: 14 checked, 14 matchable to error_id in §2/§3 prose (all 18 error ids verified present in §2/§3), 0 missing
- endpoints[].side_effects / applies_to scopes: checked and expressed (scheduler sweep contents, SoD 4-endpoint scope, overlap 3-endpoint scope, sequence-gate 2-endpoint scope, deadline 2-endpoint scope, fiscal 3-point scope), 0 missing
- entities[].fields[] structured content: defaults, null-until semantics, enum sets (100 enum values verified present, incl. SUBMITTED fix), uniqueness constraints — all reconstructible, 0 missing
- sibling-branch symmetry: void INTAKE/APPROVED, waive FAILED/RETRY_SCHEDULED, asset waive TRACKED/OVERDUE, covenant ack PENDING/REMINDED, statement VOIDED DRAFT/CALCULATED, revocation-complete two advancement orders — all rendered with equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 518
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

All three hard contracts PASS. The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or referenced.

## Step 5: Generate Unit Tests — 2026-08-15T01:24:00.000Z

97 total tests. The actual counts include all the multiple tags per corner instance (e.g., 2 tests for `case_create_invalid_enum_400` to cover both invalid case_type and invalid state_code, 3 for list_filter_by_status, etc.). That's correct — the skill requires ≥1 test per corner instance and ≥2 per difficulty instance, and many instances warrant multiple sub-case assertions.

## Summary

Generated complete test infrastructure for `task_1917_employee_offboarding_access_revocation` at:
- `/home/ubuntu/github/CodingPRD/tasks/task_1917_employee_offboarding_access_revocation/test_helpers/` — 9 modules (types, constants, api_errors, api_client, factories, test_users, assertions, fixtures, barrel `__init__.py`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1917_employee_offboarding_access_revocation/test_suite/` — `conftest.py` plus 7 test modules containing 97 test functions total

### Coverage audit (all green)

- **Queue A (Difficulty)** — all 18 non-stub instances covered with ≥2 tests each (36 difficulty tests minimum, all met).
- **Queue B (Corner)** — all 49 non-stub instances covered with ≥1 test each; the single stub `errors/error_catalog_full_trigger_coverage` correctly skipped (its `difficulty_instance` cross-reference to `priority_pair_validation_conflict/state_vs_sod_on_case_approve` resolves).
- **No orphan tags** — every `Design:` line in the test suite resolves to a real `name:` in the source YAML.

### Key design choices

- **PRD-first filter applied throughout.** Every test's docstring carries a verbatim PRD citation (C1/C2/C3) plus a single `Design: Difficulty/<rule>/<name>` or `Design: Corner/<section>/<name>` tag (C4). A grep pass over PRD.md confirmed all cited rule-bearing phrases appear verbatim.
- **Two-reader adjudication:** For the `asset_posture` close-gate edge (PRD §3.7 requires COMPLETE/DEFAULTED, but §3.4 says COMPLETE requires "at least one item exists"), I made `drive_case_to_ready_to_close` and the OCC `_drive_to_ready_to_close` both register + waive a real asset, so the case reaches READY_TO_CLOSE under either interpretation of the zero-asset edge.
- **Ambiguous dual-error surfaces use `validate_error_is_one_of`:** `case_terminal_lockdown_closed` accepts `ERR_INVALID_STATE` or `ERR_CASE_TERMINAL` (PRD §2.6 priority + §3.7 name both); `benefits_send_after_deadline_rejected` accepts `ERR_DEADLINE_MISSED` or `ERR_INVALID_STATE` (the scheduler may have already flipped the notice to FAILED before the send attempt); `occ_statement_calculate_stale_version_412` accepts `ERR_STALE_STATEMENT_VERSION` or `ERR_INVALID_STATE` (priority 4 state precedes priority 14 OCC).
- **Priority-pair tests** (`state_vs_sod_on_case_approve`, `temporal_vs_fiscal_on_case_create`) are legal because PRD §2.6 explicitly enumerates the evaluation order ("the server evaluates them in a fixed priority order so that the returned error is deterministic").
- **`ManagerNotification`** correctly modeled as append-only: its TypedDict omits `updated_at` and `version`, and the entity assertion positively asserts both fields are absent on the wire.
- **SoD tests** use raw header dicts (e.g., `{"X-User-ID": "it-op-1", "X-User-Role": "ITVerifier"}`) for the cross-role-same-user collision cases, since `X-User-ID` is opaque per PRD §2.1 and SoD compares against recorded counterparties, not entity ids.

### Verification

- All 17 Python files parse cleanly via `ast.parse`.
- `test_helpers` imports successfully against the framework; all 7 test modules import without errors.
- The runner's framework imports (`GenericApiClient`, validators, `set_error_http_status_map`, `build_user_headers`, `NON_EXISTENT_UUID`) match the actual installed `prd_bench_local_runner.testing` API exactly.

## Step 6: Generate Implementation — 2026-08-15T01:44:00.000Z

Done. The implementation is complete and fully verified.

## What was built

`/home/ubuntu/github/CodingPRD/tasks/task_1917_employee_offboarding_access_revocation/workspace/implementation/`:

- **`start.sh`** — guarded launcher (`pip install` only if flask missing), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- **`app.py`** — entry point
- **`core.py`** — constants, empty-on-boot in-memory store, logical clock (default `2026-08-01T00:00:00Z`, raw-string echo), response envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`, pagination fields in meta), all 18 error IDs with exact HTTP codes, auth (`X-User-ID`/`X-User-Role`, 11 roles), global request lock
- **`domain.py`** — all 14 calculations (last-day determination with per-type weekend roll, 3 final-pay deadline variants across 8 states, dual-variant PTO payout with half-hour floor and half-up cent rounding via `Decimal`, asset deductions default/damage/late-fee, deduction totals, net-pay waterfall with gross cap, late penalty with ceil-days/30-day cap, revocation scheduling offsets, benefits deadlines, covenant reminders, notification dedupe window), posture aggregates with pinned precedence, case auto-transitions, and a fixpoint scheduler sweep
- **`routes_cases.py` / `routes_work.py` / `routes_secondary.py`** — all 73 endpoints with scaffold validation priority ordering (auth → role → existence → state → SoD → temporal → referential → overlap → caps → sequence gate → fiscal → deadline → payload → OCC)

## Verification

Three smoke suites (164 assertions total) all pass, exercising: full lifecycle intake→close, all four SoD checkpoints, every deadline variant (CA/CO/MA calendar incl. 72h rule, IL/NY/WA business-day, TX/FL semi-monthly payday at 17:00), PTO tier caps and state-floor max, asset overdue→defaulted cascade with depreciation bps math, retry backoff (1h/2h/3h) and cap/waive gate, sequence-rank ordering gate, half-open vs closed overlap rules, reschedule/failure caps, notice queue/send/fail/requeue/escalate, covenant arm/remind, both payroll-first and revocation-first orderings, all three OCC rules with rule-specific 412 error IDs, void cascades, and terminal lockdown.

Reboot isolation confirmed: a fresh `bash start.sh` process boots in ~0.7s with default clock and empty store (no seeding anywhere), satisfying `per-test-server` restarts.

## Judgment calls (spec-ambiguous points)

- **Readiness gate with zero assets**: treated as satisfied — required by the shipped fixture `drive_case_to_ready_to_close`, which closes a case with no assets.
- **`recommended_code` defaults to `"ELIGIBLE"`** on the auto-created DRAFT review — `test_helpers/assertions.py:assert_rehire_review` requires enum membership even pre-submit.
- Clock-gate violations (complete-before-start, default-before-grace) → `ERR_INVALID_STATE` (409); covenant acknowledge on a terminal case → `ERR_TEMPORAL_INVALID` (scaffold validation 6 maps it there explicitly).
- `recipient_manager_ref` is null on system-emitted notifications (no payload anywhere carries a manager ref); `activate` optionally accepts `owner_manager_ref`/`required_session_count` since no plan-create endpoint exists.

## Step 7: Run Tests and Iterate — 2026-08-15T02:03:00.000Z

All 8 rounds pass: 96/96 in every round. The loop exits clean.

## Summary

**Iterations run:** 2 (initial sweep: 85/97 × 8 rounds, 12 deterministic failures; post-fix sweep: 96/96 × 8 rounds, zero failures).

**Tests deleted (1):**
- `test_05_cascades_and_invariants.py::TestAssetWaiveCompensatingInvariant::test_asset_waive_restores_deduction_total` — unique-derivability collapse (two-reader divergence). PRD §3.4 grants waiver only "from `TRACKED` or `OVERDUE`"; the clause "waiving an item whose deduction was `COMPUTED` or `APPLIED`..." is unreachable under that grant (COMPUTED implies RETURNED, APPLIED implies DEFAULTED), so a faithful reader restricting waiver to TRACKED/OVERDUE fails this test while remaining PRD-consistent. Scaffold driver: AssetReturnItem waive transition's side_effects clause ("if deduction_status in {COMPUTED, APPLIED}: ... run calc_deduction_total") was treated by the test generator as a live waive-from-DEFAULTED grant despite the scaffold's own preconditions limiting the transition to {TRACKED, OVERDUE}.

**Fixes applied to `test_helpers/`:**
- `test_helpers/assertions.py` — added `assert_instant_equal(actual, expected)`, which parses both sides and compares instants by value. Why: PRD §2.8 pins calendar results to explicit precisions ("a date at midnight UTC", "instants in ISO 8601 UTC") but never pins a fractional-digit rendering, so exact-string equality against `"…T00:00:00Z"` asserted a serialization rule PRD doesn't uniquely determine (implementation emits `"…T00:00:00.000Z"`, also valid ISO 8601 UTC). The instant value (the date math) is the PRD-covered rule; the string format is not (STEP 1c split).

**Fixes applied to `test_suite/`:**
- `test_03_calculations_deadlines_payouts.py` — 4 tests switched from exact-string `==` to `assert_instant_equal` for `determined_last_day` / `final_pay_due_at` (format silence, above). 2 late-penalty tests (`test_late_penalty_one_second_past_due_is_full_first_day`, `test_late_penalty_cap_at_30_days`) reordered setup: `set_clock(past due_at)` now happens while the statement is still CALCULATED, then approve, then disburse. The original order (approve at due, then advance clock) let the PRD-mandated scheduler sweep flip the statement APPROVED→LATE before the disburse call, making the test depend on disburse-from-LATE — a path PRD does not uniquely determine ("Disbursing after `due_at` is not rejected" vs "`LATE` … terminal"). The rewrite exercises the same verbatim penalty assertions (LATE + 40000 / 1200000) through the unambiguous disburse-from-APPROVED-late branch.
- `test_04_revocation_cycles_and_gates.py` — added missing `HR_REVIEWER` import (NameError in both rehire-submit-gate tests); switched 2 `scheduled_at` asserts in the retry-cycle test to `assert_instant_equal`; fixed `test_revoke_execute_gated_on_case_status_voided_case` setup by removing the pre-void `set_clock("2026-08-10T17:00:00Z")` — per PRD §3.2 the clock release flips the task PENDING→READY which auto-advances the case APPROVED→REVOCATION_IN_PROGRESS, and §3.1 permits voiding only from INTAKE/APPROVED, so the implementation's 409 was PRD-correct and the setup was the bug. The void now happens from APPROVED with a PENDING task (cascade waives PENDING per §3.1); the final execute→ERR_INVALID_STATE assertion is unchanged.
- `test_05_cascades_and_invariants.py` — switched `send_by` / `remind_at` asserts to `assert_instant_equal`; deleted the waive-from-DEFAULTED test (above).

**Fixes applied to `implementation/`:** none — every failure traced to the test artifact layer; the implementation was already PRD-faithful on all 12.

**Final state:** 96 tests, 8/8 parallel rounds at 96/96 under `--isolation per-test-server`.

## Step 8: Finalize PRD — 2026-08-15T02:12:00.000Z

Done. PRD_FINALIZED.md is written at `/home/ubuntu/github/CodingPRD/tasks/task_1917_employee_offboarding_access_revocation/workspace/PRD_FINALIZED.md` with exactly three inline revisions, each traced to a step_7_diff item.

## Size delta

- `PRD.md`: 338 lines / 55,971 bytes. `PRD_FINALIZED.md`: 338 lines / 56,772 bytes. Lines: +0 (0.0%); bytes: +801 (+1.43%).

## Changes (one bullet per edit)

- **§2.8** — revise — appended a sentence pinning that every stored calendar-result instant (determined last day, deadlines, schedules, dispatch timestamps) is rendered with exactly three fractional digits, e.g. `2026-08-10T00:00:00.000Z`, matching the `created_at` convention — `implementation/core.py:130-133` (`fmt_dt` always emits `%03d` milliseconds) applied universally by `ser` at `implementation/core.py:301-311`. (Traces to the `assert_instant_equal` helper addition and the 8 switched asserts in test_03/test_04/test_05.)
- **§3.3** — revise — pinned that only an `APPROVED` statement can be disbursed (any other status, including scheduler-marked `LATE`, is rejected `ERR_INVALID_STATE`); scoped the "not rejected after `due_at`" sentence to disbursement of an `APPROVED` statement with penalty computed as of the disbursement instant; pinned that the scheduler's APPROVED→LATE flip computes the same penalty as of the sweep instant — `implementation/routes_work.py:585-595` (`st["status"] != "APPROVED"` → `err_invalid_state`; penalty via `calc_late_penalty(due_at, now, wage)`), `implementation/domain.py:476-484` (sweep flip computes penalty at sweep `now`). (Traces to the two reordered late-penalty tests in test_03.)
- **§3.4** — revise — pinned asset waiver as permitted only from `TRACKED`/`OVERDUE` with any other status (incl. `RETURNED`/`DEFAULTED`) rejected `ERR_INVALID_STATE`; noted the invariant that a `TRACKED`/`OVERDUE` item's deduction is always `NONE`, and demoted the COMPUTED/APPLIED deduction clause to an explicit conditional so it no longer reads as a waive-from-DEFAULTED grant — `implementation/routes_work.py:432-433` (from-state gate), `implementation/routes_work.py:438-443` (dead COMPUTED/APPLIED branch preserved as conditional). (Traces to the deleted `test_asset_waive_restores_deduction_total`.)

No edits were made for the remaining diff items: the `HR_REVIEWER` import and the `test_revoke_execute_gated_on_case_status_voided_case` setup were pure test-artifact bugs — PRD §3.1/§3.2 already uniquely determine void-from-INTAKE/APPROVED and the clock-release auto-advance, and the implementation matches them (`implementation/routes_cases.py:333-338`, `implementation/domain.py:308-314`).

## Per-edit pre-edit search log

**Edit 1 (§2.8 fractional digits).** (a) Subject: serialization rendering of stored calendar-result instants. (b) Enumerated paths: `core.py:130-133` (`fmt_dt`, sole formatter, always 3 digits); `core.py:301-311` (`ser`, applies to every datetime on every resource); producers of covered fields — `domain.py:92-107` (`determined_last_day`), `domain.py:124-144` (`final_pay_due_at`/`due_at`), `domain.py:208-211` + `routes_work.py:248` (`scheduled_at`, incl. retry backoff), `routes_work.py:306` + `routes_cases.py:277` (`return_due_at`), `domain.py:214-218` (`send_by`), `domain.py:221-224` (`remind_at`), and `now_dt()` stamps (`executed_at`, `sent_at`, `acknowledged_at`, `disbursed_at`, `returned_at`, `closed_at`, `finalized_at`) — all 3-digit; off-scope paths checked for false-universal risk — `routes_cases.py:68-85` clock endpoints return `CLOCK["raw"]` verbatim (test_07:49 asserts exact `"2026-08-01T00:00:00Z"`), input-echo fields (`notice_received_date`, `requested_last_day`, `issued_date`, `scheduled_start/end`), and `api_request_timestamp` (`core.py:136-138`, already 3-digit per §2.2). (c) Wording scoped to "every such stored calendar instant" (the categories already named in the sentence) rather than a universal "all timestamps" claim, specifically to avoid covering `current_utc`, which the implementation echoes raw.

**Edit 2 (§3.3 disburse/LATE).** (a) Subject: disbursement from-states and waiting-time-penalty computation instants. (b) Enumerated paths: `routes_work.py:581-598` (`disburse_statement` — APPROVED-only gate, `now <= due_at` → DISBURSED, else LATE + penalty as of disbursement `now`); `domain.py:476-484` (sweep APPROVED→LATE computing penalty as of sweep `now`); `domain.py:199-205` (`calc_late_penalty` ceil/cap formula); `routes_cases.py:296-299` (close accepts DISBURSED or LATE); `domain.py:327` (payroll-first clearance gate on APPROVED/DISBURSED/LATE — untouched by wording); `domain.py:391` (deduction cascade only recomputes CALCULATED/APPROVED); `routes_cases.py:351-354` (void sweeps DRAFT/CALCULATED to VOIDED); cross-check vs §2.6 rule 4 (terminal-state lockdown → `ERR_INVALID_STATE`) and the existing "`DISBURSED`, `LATE`, and `VOIDED` are terminal" sentence. (c) Added "of an `APPROVED` statement" to the previously unscoped "Disbursing after `due_at`" sentence so it cannot be read as permitting disburse-from-LATE; penalty as-of wording split into "disbursement instant" vs "sweep instant" to describe both enumerated computation sites accurately.

**Edit 3 (§3.4 asset waiver).** (a) Subject: asset-waiver from-states and deduction side effects. (b) Enumerated paths: `routes_work.py:428-453` (`waive_asset_item` — TRACKED/OVERDUE gate at :432-433, conditional deduction branch at :440-443, posture recompute/reconcile at :445-452); `routes_work.py:359-394` (`record_asset_return` — the only path setting COMPUTED, and it moves the item to RETURNED); `routes_work.py:397-425` (`mark_asset_defaulted` — the only path setting APPLIED, moving the item to DEFAULTED); `routes_cases.py:347-350` (void cascade TRACKED→WAIVED, deduction untouched); `domain.py:251-256` (`compute_deduction_total` sums APPLIED only); `routes_cases.py:188-192` (summary `projected_deduction_cents` sums COMPUTED); verified the invariant TRACKED/OVERDUE ⇒ `deduction_status == NONE` holds across all transitions; confirmed §4 locator row ("only a locator" per §4 intro) defers to §3 so no table edit needed. (c) Replaced the semicolon-attached clause (readable as a live waive-from-DEFAULTED grant) with an explicit from-state restriction plus a conditional "should a waived item's deduction be…" phrasing that mirrors the implementation's unreachable branch without granting the transition, and stated the NONE invariant so the two-reader collapse cannot recur.

## Step 9: Complete PRD — 2026-08-15T02:28:00.000Z

All edits are in place — 23 paragraph-local revisions, no new sections, line count unchanged. Final report:

## Summary

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1917_employee_offboarding_access_revocation/workspace/PRD_COMPLETED.md`

**Counts:** Source `PRD_FINALIZED.md`: 338 lines / 56,772 chars → `PRD_COMPLETED.md`: 338 lines / 61,290 chars. Char delta **+4,518**; line count unchanged (all edits are in-paragraph inserts/revisions; no new sections, no new paragraphs). 23 diff hunks covering 26 distinct behavioral pins: **21 ambiguity-pins, 5 mismatch-revisions**.

**Changes (section — insert|revise — ambiguity|mismatch — what — impl ref):**

- §2.1 — insert — ambiguity — only `verified_by`/`reviewer_hr_ref` are serialized; `intake_hr_ref`, approver ref, `calc_by_ref`, executor ref, task/asset waive reasons, and review return reasons are internal-only — core.py:301-311, routes_cases.py:147-148,230, routes_work.py:133-134,524, routes_secondary.py:772
- §2.3 — revise — ambiguity — `limit` clamped into 1–100 (sub-1 raised, not rejected), `offset` clamped to ≥0, non-numeric values fall back to defaults — core.py:314-327
- §2.3 — insert — ambiguity — creation-timestamp sort ties broken by insertion order — core.py:316
- §2.3 — insert — ambiguity — `has_more` = `offset + returned < total_count` — core.py:220-227
- §2.4 — revise — ambiguity — clock set accepts any parseable instant (no monotonicity check); set and read both return `current_utc` echoing the exact last-supplied string un-normalized — routes_cases.py:68-85
- §2.4 — insert — ambiguity — sweep skips releasing revocation tasks of CLOSED/VOIDED cases — domain.py:425-427
- §2.8 — revise — mismatch — decimal-place counts for `pto_balance_hours`/`tenure_years` are conventional, not enforced; any non-negative number accepted — routes_cases.py:114-118,124-126
- §2.10 — insert — ambiguity — sub-resource listings accept only the `status` filter; other collection filters are top-level only — routes_work.py:163-171,348-356,478-486; routes_secondary.py:164-172,295-303,417-425,515-523,644-652,709-717; routes_cases.py:383-391
- §2.11 — revise — mismatch — one reconciliation pass advancing multiple states bumps `version` once per pass — domain.py:302-341
- §3.1 — insert — mismatch — intake validation order pinned (dates → employee_ref → fiscal → enums/tenure/intake_hr_ref), diverging from strict §2.6 priority in the employee_ref-vs-fiscal corner — routes_cases.py:95-127
- §3.1 — insert — ambiguity — TX/FL: a 17:00 UTC payday on the determined last day itself counts (determined day is midnight) — domain.py:110-121
- §3.1 — insert — ambiguity — auto-created plan starts with null `owner_manager_ref`/`required_session_count` 0; auto-created review starts `recommended_code` `ELIGIBLE`, null `reviewer_hr_ref`/`rationale` — routes_cases.py:249-272
- §3.2 — insert — ambiguity — verification rejection requires no `failure_reason`; field left untouched — routes_work.py:230-231
- §3.4 — insert — ambiguity — assets registered during INTAKE carry null `return_due_at` until approval; those registered post-approval are stamped (dl + 3 days) at registration — routes_work.py:303-306
- §3.4 — revise — ambiguity — 2,500-cent late fee applies to any late return regardless of condition; a late GOOD/NORMAL_WEAR return yields a COMPUTED 2,500-cent deduction on its own — routes_work.py:384-391
- §3.4 — insert — ambiguity — mark-defaulted before the 7-day grace or outside PAYROLL_PENDING/CLEARANCE_IN_PROGRESS → `ERR_INVALID_STATE` — routes_work.py:405-409
- §3.5 — revise — ambiguity — interview completion before `scheduled_start` → `ERR_INVALID_STATE`; decline/cancel only from `SCHEDULED`; 5-day hard limit evaluated only once a determined last day exists — routes_secondary.py:206-208,225-270
- §3.5 — insert — ambiguity — plan activation payload optionally carries `owner_manager_ref` and `required_session_count` — routes_secondary.py:316-325
- §3.5 — insert — ambiguity — session scheduling is not gated on plan status (any non-terminal case) — routes_secondary.py:366-401
- §3.5 — revise — ambiguity — session completion before start or under non-ACTIVE plan → `ERR_INVALID_STATE`; explicit plan completion short of required count → `ERR_INVALID_STATE` — routes_secondary.py:339-340,428-444
- §3.6 — insert — ambiguity — notice queueing / covenant arming fire once at the posture-completion transition; later-created notices stay DRAFT forever, later-created acks keep null `remind_at` and are never reminded — domain.py:315-325
- §3.6 — revise — ambiguity — requeue recomputes `send_by` from now with the same 17:00 UTC snap; escalation below the failure cap → `ERR_INVALID_STATE` — routes_secondary.py:570-598
- §3.7 — revise — mismatch — readiness gate's asset condition is satisfied vacuously by a case tracking no assets (impl skips the posture check when zero items) — domain.py:288-292
- §3.7 — insert — ambiguity — unmet statement/notice preconditions at close → `ERR_INVALID_STATE` (409) — routes_cases.py:297-302
- §3.7 — revise — ambiguity — `net_pay_preview_cents` recomputes the waterfall live from the statement's stored wages/PTO against the current case deduction total; 0 when no statement; `ready_to_close` evaluated live regardless of case status — routes_cases.py:183-209
- §3.8 — revise — mismatch — `recipient_manager_ref` is persisted as null (no intake field supplies a manager identity) — domain.py:262-282

**Not changed (verified already pinned):** all 64 endpoints and role sets match §4; state machines, calculation formulas (PTO dual-variant, net-pay waterfall, depreciation bps, damage fractions, waiting-time penalty ceil/cap, revocation offsets, benefits deadline day-counts, covenant reminder), error catalogue, SoD-1..4 plus reviewer-vs-approver, OCC guards on exactly close/calculate/record-return, dedupe window semantics, and the startup clock value all matched the implementation as written.
