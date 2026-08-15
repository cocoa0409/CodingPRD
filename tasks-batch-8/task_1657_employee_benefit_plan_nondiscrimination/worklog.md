# Worklog — task_1657_employee_benefit_plan_nondiscrimination

## Step 1: Create Task Directory — 2026-08-14T05:18:00.000Z

Task directory `tasks/task_1657_employee_benefit_plan_nondiscrimination/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE per invocation contract.

## Step 2: Generate Scaffold — 2026-08-14T06:00:00.000Z

All three scaffold artifacts are complete and lint-clean. Summary:

### Files written

| File | Lines | Contents |
|---|---|---|
| `SCAFFOLD.yaml` | 1,556 | §1.0–§1.7 (envelope, entities, state machines, concurrency rules, calculations, validations, endpoints, errors, RBAC) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2,948 | §1.8, single top-level key `scaffold_difficulty_design` |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4,682 | §1.9, single top-level key `scaffold_corner_design` |

### Counts
- **Entities:** 13 (Employer, Plan, PlanVersion, PlanYear, CensusEmployee, CompensationRecord, Contribution, RegulatoryLimit, SafeHarborElection, SafeHarborNotice, TestRun, TestResultLine, Correction)
- **Endpoints:** 57 (incl. `/_clock/set_current_utc` with fixed startup default `2026-08-01T00:00:00Z`, plus `execute-synchronously` test-driving helper)
- **Errors:** 20; **Roles:** 4 (PlatformAdmin, PlanAdministrator, ComplianceAnalyst, Auditor — all `opaque` identity, segregation-of-duties role model)
- **Calculations:** 13; **State machines:** 7; **Validations:** 21 (ordered priority 1–21); **Concurrency rules:** 3 OCC rules
- **Difficulty instances:** 18 (2 per each of the 9 rules, all with structured replayable recipes)
- **Corner instances:** 52 total — 51 active with recipes + 1 `excluded_because` stub (`error_election_locked_suspend_after_filed`); sections covered: entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_layers, consistency_model
- **Lint:** `VERDICT: clean lint` (960 calls scanned, 0 violations; all FKs reverse-reachable)

### Notable design decisions
- **Archetype:** compliance/audit primary + ledger-reconciliation secondary; Expert-band ceiling with 6 complexity layers (OCC, cascading side effects, dual-variant calc, rate/threshold triggers, scheduled actions, derived-field reconciliation).
- **Difficulty anchors:** ADP/ACP three-prong `max(1.25x, min(+2pp, 2x))` ceiling (combinatorial mode a); dependent-care per-person $5k cap applied *before* averaging (mode b, rounding order pinned); PROVISIONAL-vs-FINAL run variants that diverge after corrective distributions; first-year vs lookback top-heavy variants that flip verdicts on identical ledgers; strictly-greater boundaries at 5.0% ownership (HCE), 60.0000% (top-heavy), and inclusive 70.0000% (coverage) — all with literal-computed asserts (e.g., excise 225000, gap income 171308 for a 2028-02-01 execution).
- **State machines:** PlanYear cyclic (lock→unlock→relock with TestRun supersession cascade), Correction with parallel dimensions (approval pipeline × excise status), SafeHarborNotice clock-driven LAPSED auto-transition, PlanVersion half-open interval truncation/supersession on amendment adoption.
- **Segregation of duties:** Correction proposer's `X-User-ID` is recorded and barred from approving (user-level, distinct from role-level RBAC denial — both are tested).
- **Mid-course correction:** Subagent initially used `${var} + N` arithmetic for OCC versions; a self-written replay audit caught 28 off-by-one mismatches, so all OCC payloads were mechanically rewritten to capture the current version via a fresh GET immediately before the guarded call (the rule-3c-sanctioned pattern). Zero unbound placeholders, zero dangling grounds, no forbidden concurrency vocabulary.
- **Orchestrator note:** first spawn exited after planning without writing files; resumed via SendMessage and completed (added `POST /ndt/employers/{id}/archive` during self-review to close the Employer.status=ARCHIVED enum-closure gap).

## Step 3: Copy Shared Files — 2026-08-14T06:00:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1657_employee_benefit_plan_nondiscrimination/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T06:25:00.000Z

PRD generation complete. Output: `workspace/PRD.md` — 284 lines.

### Section list

- **§1 Introduction** (2 paragraphs — business-context angle: TPA compliance cycle, then system scope with `/ndt` mount)
- **§2 Global Specifications** — 2.1 Roles & headers, 2.2 API Response Structure (byte-verbatim from the skill's source file, verified by exact substring match), 2.3 Pagination, 2.4 Resource Identity/Timestamps/Versioning, 2.5 The Logical Clock, 2.6 Money/Ratios/Rounding Discipline, 2.7 Optimistic Concurrency Control, 2.8 Validation Precedence, 2.9 Nested Resource Resolution
- **§3 Business Logic** (9 subsections, timeline-grouped): 3.1 Employers & Controlled Groups, 3.2 Plan Setup/Versioning/Mid-Year Amendments, 3.3 Statutory Limits, 3.4 Plan Year & Census Building, 3.5 Census Lock & Determination Sweep, 3.6 Testing Engine (all six batteries as precise prose formulas), 3.7 Corrections/Waterfalls/Excise, 3.8 Safe Harbor Elections & Notices, 3.9 Filing/Termination/Archival
- **§4 Endpoint Definitions** — 57-row table (Method/Path/Description/Roles only), matching all 57 scaffold endpoints
- **§5 Error Code Catalogue** — 20-row table (Error ID/HTTP Status only), no audit footer after §5

### Hard Contract results (all PASS)

- **Contract 1 (fields)**: 77 entity fields, 62 request-body ids, 23 query params — 96/96 present in backticks, 0 missing. Two misses found and repaired during generation (`census_employee_id`, `election_id`, both FK fields expressed through action narrative per the no-declared-FK style rule).
- **Contract 2 (rules)**: 21/21 validations with priority ordering expressed as an explicit observable sequence in §2.8 (earliest-failure-masks-later semantics stated); 3/3 OCC rules with occ_field + ERR_STALE_VERSION/412 named; all 25 state-machine transitions across 7 machines with preconditions and side effects; 13/13 calculations as reconstruction-safe prose (inclusive/exclusive boundaries preserved: "strictly greater than 5 percent", "at least 70.0000", "no greater than the ceiling", 999.9999 sentinel, ACT/365 gap income, 6-decimal proration); 108/108 enum/state values present; all 20 error IDs mentioned in §2/§3 prose; cross-entity cascades (unlock supersession, execute supersession + QNEC creation + recharacterized sibling, suspend design-strip, terminate plan cascade, adoption truncation, forfeit supersession, notice-lapse on clock set) all stated.
- **Contract 3 (§3 path purity)**: 616 backticked tokens scanned in §3, 0 path/method violations — endpoints referenced via state-pair framing, role+verb, or capability description.

### Notable wording decisions

- **Rounding-before-averaging** (ADP/ACP/dependent-care) stated explicitly per §1.3 precision; the ADP ceiling rendered as "the greater of one-and-a-quarter times the NHCE average, and the lesser of (NHCE average plus two percentage points) and (twice the NHCE average)" — matching the scaffold's operative second formula line.
- **Correction proposal state gate**: scaffold validation 6 says "corrections only in CORRECTING" while the state machine allows the first proposal from RESULTS_REVIEW; rendered as "permitted while RESULTS_REVIEW (first proposal moves the year to CORRECTING) or already CORRECTING", consistent with both entries.
- **FAILED-run member flagging**: scaffold's parenthetical "(no status change; review uses detail payload)" rendered explicitly — contributions stay `POSTED`, HCE cohort identified via `detail.member_ids`.
- **"later TestRun" supersession on execute** rendered as "every later-created test run … in PASSED or FAILED", staying literal without inventing a reference point.
- Two regex hits on "about/around" reviewed and kept: both are non-numeric usages ("exact about who did what", "organizes work around a hierarchy"), not threshold approximations.

## Step 5: Generate Unit Tests — 2026-08-14T06:45:00.000Z

All green. Final summary:

### Summary

Generated complete test infrastructure for `task_1657_employee_benefit_plan_nondiscrimination` from the two design indices only, under PRD-first adjudication.

#### File inventory (3972 lines total)

`test_helpers/` (1346 lines):
- `__init__.py` (35) — barrel export: framework generics + PRD-specific
- `types.py` (414) — 13 entity TypedDicts + 25 status/role enums; all entities carry the 4 common fields per PRD §2.4 ("No entity in this system is exempt from the common property set.")
- `api_client.py` (189) — 45 endpoint methods covering every PRD §4 endpoint
- `api_errors.py` (53) — 20 `ApiErrorId` values + HTTP map registered via `set_error_http_status_map`
- `assertions.py` (146) — per-entity asserters + `assert_pct` (4dp half-up) + `get_result_line`
- `factories.py` (139) — payload factories, input fields only
- `constants.py` (59) — thresholds (70.0 coverage, 60.0 top-heavy strictly-greater, 1.25/2.0/2.0 ADP prongs, 0.55 DC ratio, 0.10 excise, 0.07/365 gap income, 30-day notice gap)
- `test_users.py` (40) — 4 opaque role headers + per-user builders (used for segregation-of-duties tests)
- `fixtures.py` (271) — composite builders: hierarchy, locked-census 401k, failing-ADP RESULTS_REVIEW, CORRECTING with proposed/approved correction, clock setter. Fixtures publish a raised 402(g) limit (6900000) for census scenarios whose HCE deferral ledger exceeds the standard 2350000 example limit — the design recipes' own limit (2350000) conflicts with PRD §3.4's aggregate 402(g) guard at setup time; the two 402(g) boundary tests keep the standard limit via a separate fixture path.

`test_suite/` (2626 lines, 84 tests): `conftest.py` (29), `test_01_employer_rbac_and_auth.py` (167), `test_02_plan_structure_and_versioning.py` (388), `test_03_census_lock_and_occ.py` (507), `test_04_testing_engine.py` (585), `test_05_corrections_and_excise.py` (481), `test_06_safe_harbor_and_priority.py` (469).

#### Tests per queue
- **Queue A (Difficulty):** 16 of 18 instances translated, each with exactly 2 tests (32 tests)
- **Queue B (Corner):** 50 of 51 non-stub instances translated (52 tests; 2 OCC instances got a second test each). The `error_election_locked_suspend_after_filed` stub was not translated per the `excluded_because` rule.

#### Skipped instances (PRD-first filter failures)
1. `Difficulty/boundary_precision_check/coverage_ratio_exactly_70_passes` — the asserted 70.0000 ratio depends on which employees are `BENEFITING` vs `ELIGIBLE_NOT_BENEFITING`; PRD §3.5 names the four `covered_status` values but never states the classification rule, so two PRD-only readers can legitimately diverge on the exact value.
2. `Difficulty/cross_entity_state_dependency/testrun_state_gates_planyear_file` — PRD §3.9's file precondition ("every FINAL test run created after the last EXECUTED correction must carry overall_result PASS") is vacuous-truth ambiguous when no FINAL run exists after the execute; one faithful reading permits the file, the design's rejects it.
3. `Corner/entities/census_employee_computed_fields_ignore_client_input` — PRD never states that client-supplied computed/unknown payload fields are rejected (an implementer may silently ignore them); the asserted `ERR_INVALID_REQUEST` is not uniquely derived.

#### Translation-time adjustments (design bugs worked around, assertions not weakened)
- `correction_execute_supersedes_later_runs_depth2`: the design recipe creates the second run in CORRECTING, which PRD §3.6 forbids; the test creates it via the lawful RESULTS_REVIEW re-open. The "all terminal runs superseded" assertion was narrowed to the later-created run ("later-created" referent is unambiguous only for it); tr8a-style pre-correction runs are not asserted.
- `corrective_distribution_conserves_deferral_ledger`: row-level RECHARACTERIZED split representation is ambiguous in PRD §3.7; the test asserts the uniquely-derivable invariants (oldest-first DISTRIBUTED, DISTRIBUTED total == correction amount, ledger total conserved).
- `dependent_care_per_person_cap_then_average_rounding` / `adp_input_set_excludes_terminated_before_year`: `detail.*` field names are not PRD-named; asserted on the PRD-pinned `value_pct` (27.7783 pins cap-before-average) and `hce_status` instead.
- `forfeit_rejects_elective_deferral`: PRD names no error_id for forfeiting a non-employer-source type; used `validate_error_is_one_of([ERR_INVALID_REQUEST, ERR_INVALID_STATE])` per the error-precedence pattern; the MATCH forfeit success path is asserted exactly.

#### Stage 2 self-audit
- Tag integrity: 84/84 tests end with exactly one `Design: Difficulty/...` or `Design: Corner/...` line resolving to a real instance; no unknown tags, no stub translated, no dual tags.
- Coverage: every translated difficulty instance has ≥2 tests; every translated non-stub corner instance has ≥1. Shortfalls limited to the 3 skipped instances above.
- PRD citation pass: every docstring's quoted PRD sentences verified verbatim against PRD.md (multi-probe substring check — 0 misses after fixing one ellipsis-spliced quote).
- Helper-only-import rule: test files import only from `test_helpers` (+ pytest/re); no skip/xfail markers anywhere; no "scaffold"/table references in generated code; nothing read or written under `workspace/implementation/`; no sibling tasks read.
- All files compile; `pytest --collect-only` collects 84 tests cleanly.

## Step 6: Generate Implementation — 2026-08-14T06:50:00.000Z

Implementation complete and verified. Here is the summary.

### Implementation complete: task_1657 Employee Benefit Plan Nondiscrimination

#### File inventory (all under `workspace/implementation/`)

| File | Lines | Purpose |
|---|---|---|
| `start.sh` | 10 | Foreground launcher, `exec python3 app.py`, guarded dep install |
| `requirements.txt` | 1 | `flask>=3.0` |
| `app.py` | 57 | Flask app factory, blueprint registration, error handlers (ApiError, 404/405/400, catch-all) |
| `db.py` | 57 | In-memory `Store` (13 dicts, empty at boot) + `LogicalClock` (fixed default `2026-08-01T00:00:00Z`, never wall-clock) |
| `errors.py` | 55 | `ApiError` + all 20 error-ID constants from the scaffold catalog |
| `response.py` | 48 | Envelope: `meta{api_request_id, api_request_timestamp}` (+`limit/offset/total_count/has_more` on lists), `response_type`, `data` |
| `middleware.py` | 43 | `X-User-ID`/`X-User-Role` auth (401 `ERR_UNAUTHENTICATED`, 403 `ERR_UNAUTHORIZED`); 4 roles |
| `routes/structure.py` | 602 | Clock, Employer, Plan, PlanVersion (create/adopt), PlanYear lifecycle (open/lock/unlock/terminate/file), RegulatoryLimit |
| `routes/census.py` | 337 | CensusEmployee create/list/fetch/PATCH, CompensationRecord, Contribution (+forfeit) |
| `routes/testing.py` | 397 | TestRun (queue/finalize/void/execute-synchronously, result-lines), Correction (propose/approve/execute/void) |
| `routes/safe_harbor.py` | 218 | SafeHarborElection (propose/suspend/revoke), SafeHarborNotice (create/list/distribute/acknowledge) |
| `services/common.py` | 400 | Field validators, pagination (limit 1-100 default 10), lookups, cascade helpers |
| `services/determination.py` | 147 | Lock sweep: ownership attribution (bidirectional 1-hop family, cap 100), HCE (lookback-year), key employee, coverage cohorts |
| `services/engine.py` | 406 | All 6 test batteries + FULL_SUITE, result lines, PASS/FAIL derivation, engine_input_hash |
| `services/correction.py` | 197 | Distribution waterfall with RECHARACTERIZED split, QNEC equal-dollar allocation, recharacterization, QMAC reallocation, excise (10%) + gap income (7% ACT/365) |
| `services/safe_harbor.py` | 91 | Election effectiveness, design sync/strip, notice lapse, 30-day window check |
| `services/amendment.py` | 179 | Interval truncation/supersession on adoption, mid-year impact projection with match formula parser |

#### Boot check
`bash start.sh` boots on `0.0.0.0:$PORT` in ~2s with an empty store; verified via fresh-process launches followed by `GET /ndt/employers` (empty list, `total_count: 0`) and a create. Three smoke suites (163 checks total) each passed on a fresh boot: envelope shape, RBAC, CRUD, uniqueness, lock sweep + family attribution, ADP/ACP with inclusive boundary checks, coverage 70.0-inclusive PASS, top-heavy + min contribution, cafeteria/dependent-care, corrections pipeline (SoD 403, OCC 412, excise on-time vs late with 381-day leap-year gap = 73,068 cents), safe harbor lifecycle (distribute→EFFECTIVE at lock, suspend strips design, notice lapse on clock set, window-closed 422), amendment truncation/supersession + impact projection (proration 0.504110), unlock cascade, filing gates, pagination bounds.

#### PRD interpretation decisions (for Step 8/9)
1. **Coverage cohort classification inputs**: PRD enumerates statuses but no eligibility algorithm. Implemented: `INELIGIBLE` if hired after `year_end`; `EXCLUDABLE` if terminated on/before `year_end` or hired after `year_start`; `BENEFITING` if any posted plan-type contribution accrual exists or the adopted version has a non-NONE safe harbor design; else `ELIGIBLE_NOT_BENEFITING`.
2. **Entity attribution rollup** (corporation ≥50% owner attribution to employees) is described as applying "on top" with a 100 cap, but no concrete transfer formula exists in the PRD; only the direct+family sum capped at 100 is computed (family is the only concrete transfer rule given).
3. **`CAFETERIA_UTILIZATION_PCT`** is in the metric vocabulary but has no formula in the calculations table; emitted as `NOT_APPLICABLE` with utilization share in detail (100 × benefiting NHCE / non-excludable NHCE).
4. **Top-heavy with `prior_year_py_id` set**: PRD says prior-year balances only, but contributions are per-plan-year children with no cross-year reference; balance semantics identical in both modes in this data model (documented divergence is a no-op over the stored set).
5. **Correction execute staleness cascade** uses correction `created_at` as the "later TestRun" boundary (the correction entity's only pre-execute timestamp).
6. **Void authorization**: PROPOSED→VOIDED requires `ComplianceAnalyst`; APPROVED→VOIDED requires `PlanAdministrator` (per state-machine actors), enforced as 409 `ERR_INVALID_STATE` when the authenticated role doesn't match the transition's actor.
7. **Safe-harbor election proposal** accepted in DRAFT…RESULTS_REVIEW (not CORRECTING/FILED/TERMINATED) under the priority-6 state gate; notice window check uses the initial-election rule (`end <= year_start - 1 day`) unless the plan year is `CENSUS_COLLECTING` (mid-year rule, `end <= year_end - 30 days`).
8. **Suspend OCC-before-`ERR_ELECTION_LOCKED`**: validation priority 9 (OCC) precedes priority 20, so a stale `expected_election_version` returns 412 even when `suspension_reason` is also missing.
9. Lock-census rejects an empty census with `ERR_CENSUS_INCOMPLETE` (vacuous truth would otherwise pin a version with no determinations); `expected_*_version` fields are optional per the skill's OCC convention (checked only when provided).
10. 405s are mapped to the 404 `ERR_NOT_FOUND` envelope (wrong-path and wrong-method are indistinguishable per §2.9's spirit).

## Step 7: Test/Iterate Loop — 2026-08-14T07:15:00.000Z

**Result: clean 8-round parallel sweep — 84/84 passed in every round (rounds 1–8).**

### Iterations run
2 (sweep 1: 8 failures/round; sweep 2 after fixes: all green).

### Tests deleted
None.

### Fixes applied to `test_suite/`
- `test_suite/test_04_testing_engine.py` — `test_pagination_filter_interaction_test_runs`: the fixture call `hce_spec=(30000000, 0, 6)` built a 6% owner who IS an HCE under PRD §3.5's verbatim ownership prong ("attributed_ownership_pct strictly greater than 5 percent"), so the coverage run FAILED (0% HCE benefiting → ratio 0 < 70) instead of producing the PASSED runs the test paginates over. The test's own comment documented the intended scenario ("no eligible HCE → NOT_APPLICABLE → PASSED"). Changed ownership 6 → 5 (5.0 is not strictly > 5, no prior-year comp → NHCE), realizing the documented PRD scenario.

### Fixes applied to `test_helpers/`
None.

### Fixes applied to `implementation/`
- `services/common.py` — `new_entity`: initial `version` 0 → 1. Fixes `test_employer_create_returns_system_fields` (asserts `version >= 1`, traced to PRD §2.4 "increments by one on every state-changing operation" with creation as the first change; matches sibling-task convention, e.g. task_1656).
- `routes/structure.py` — `unlock_census`: state gate widened from CENSUS_LOCKED-only to {CENSUS_LOCKED, TESTING, RESULTS_REVIEW, CORRECTING}. PRD §3.5's `ERR_PENDING_WORK` guard (QUEUED/RUNNING runs, PROPOSED/APPROVED corrections) and the supersede-PASSED/FAILED cascade are unreachable under the narrow reading (queueing a run moves the year to TESTING; corrections exist only in CORRECTING), so the only PRD-consistent reading admits post-lock non-terminal states. Fixes `test_lock_unlock_cycle_supersedes_terminal_runs`, `test_relock_increments_census_lock_version_without_resurrecting_runs`, `test_unlock_blocked_by_pending_work`.
- `routes/testing.py` — `execute_correction`: supersede marker changed from the correction's own `created_at` to the remedied (failed) test run's `created_at`, per PRD §3.7 "execution marks every later-created test run … SUPERSEDED, because the correction changed the balances those runs measured" — runs created after the failure but before the correction measured the same broken balances. Fixes `test_correction_execute_supersedes_later_runs`.
- `db.py` + `routes/structure.py` + `routes/safe_harbor.py` + `services/correction.py` — `LogicalClock` now keeps the verbatim ISO reading alongside the parsed instant (`now_iso()`); `set_clock` response, notice `distributed_at`, and correction `executed_at` copy it exactly. PRD §2.5 states the clock "reads exactly `2026-08-01T00:00:00Z`" and §2.5/§3.8 state workflow stamps read the logical clock — the previous `fmt_dt` normalization produced `...T00:00:00.000Z`. Fixes `test_clock_default_is_fixed_startup_time`.

### Flakiness note
`test_notice_window_boundary_exactly_30_days_passes` failed 6/8 rounds in sweep 1 with transport-level errors (ConnectionResetError / RemoteDisconnected / IncompleteRead) at random mid-test requests, with no server-side traceback. Forensics showed ~20 concurrent port-registry holders and at least one foreign task's full 8-round sweep (a loans API) overlapping that window on this shared host; the failure signature is external SIGKILL-style interference, not an artifact defect. Sweep 2 (all fixes applied) passed 84/84 × 8 with zero recurrence.

## Step 8: Finalize PRD — 2026-08-14T07:25:00.000Z

Produced `workspace/PRD_FINALIZED.md` as a minimal patch of `PRD.md`.

**Line counts / delta:** PRD.md 284 lines / 57,200 bytes; PRD_FINALIZED.md 284 lines / 58,029 bytes — 0% line delta, +1.45% byte delta. Five lines changed, zero added/removed, no new sections.

### Changes (one bullet per change)

- **§2.4** — revise — `version` now "starts at 1 when the resource is created — creation is the first state-changing operation — and … increments by one on every subsequent state-changing operation" — `implementation/services/common.py:36` (`new_entity` sets `"version": 1`).
- **§3.5** — revise — unlock gate widened from `CENSUS_LOCKED` → `CENSUS_COLLECTING` to "lawful from any post-lock, non-terminal state — `CENSUS_LOCKED`, `TESTING`, `RESULTS_REVIEW`, or `CORRECTING` — and returns the year to `CENSUS_COLLECTING`; attempted from any other state it is rejected with `ERR_INVALID_STATE`" — `implementation/routes/structure.py:476-506`.
- **§4 endpoint table** — revise — unlock-census row updated to "(CENSUS_LOCKED/TESTING/RESULTS_REVIEW/CORRECTING → CENSUS_COLLECTING)" to stay consistent with the §3.5 revision — `implementation/routes/structure.py:476`.
- **§3.7** — revise — correction-execution cascade now pins the "later-created" marker to the remedied run: "every test run for the plan year created later than the failed run the correction remedies … and sitting in `PASSED` or `FAILED` as `SUPERSEDED`; the remedied run itself keeps its status" — `implementation/routes/testing.py:367-374` (marker = `remedied["created_at"]`; strict `>` filter in `implementation/services/common.py:397`).
- **§2.5** — insert — the clock "retains the exact string it was set to … and the `now_iso8601` echo is that verbatim reading, never normalized"; workflow stamps (`distributed_at`, `executed_at`) "copy the clock's reading exactly, so before any explicit adjustment they stamp exactly `2026-08-01T00:00:00Z`" — `implementation/db.py:50-65`, `implementation/routes/structure.py:136`, `implementation/routes/safe_harbor.py:197`, `implementation/services/correction.py:29`.

**Step-7 item needing no edit:** the `test_04_testing_engine.py` fixture fix (ownership 6 → 5) was a pure fixture bug — PRD §3.5 already pins "strictly greater than 5 percent"; no PRD change.

### Per-edit pre-edit search log

1. **Version init (§2.4).** (a) Subject: initial value of the common `version` property. (b) Enumerated all 17 `new_entity(...)` callsites (structure.py:159/240/292/340/581; census.py:137/237/300; testing.py:113/267; safe_harbor.py:83/153; engine.py:45; correction.py:87/112/132/156) — every entity funnels through `new_entity` (`version: 1`); all mutations via `bump` (+1); no entity created with version 0 anywhere. Checked the sibling counter `census_lock_version` (§3.4 "starting at 0", structure.py:343) — distinct field, untouched by my wording. (c) Added "creation is the first state-changing operation" so the new sentence reconciles with the retained "increments by one" clause rather than contradicting it.

2. **Unlock gate (§3.5 + §4 row).** (a) Subject: lawful source states and target state of unlock-census. (b) `unlock_census` is the only unlock path (grep: structure.py:479-506 only); verified the pending-work guard (structure.py:492-499) and inline supersede cascade (:500-503) remain accurately described by the retained sentences; verified §2.8's "pending-work blocking on census unlock" precedence entry stays correct (state gate precedes the pending-work check, matching impl order); verified bad-state rejection is `ERR_INVALID_STATE` 409 (:489). Also updated the §4 table row, which a fresh implementer would otherwise read as a CENSUS_LOCKED-only gate. (c) Widened wording covers all four source states in one clause rather than redefining the transition as `CENSUS_LOCKED → CENSUS_COLLECTING`, avoiding a new mismatch with the TESTING/RESULTS_REVIEW/CORRECTING sources Step 7 admitted.

3. **Correction supersede marker (§3.7).** (a) Subject: reference point for "later-created" in the execution cascade. (b) Enumerated all five supersede cascades: execute_correction with marker (testing.py:374), forfeiture (census.py:336, no marker), suspension (safe_harbor.py:127, no marker), unlock (structure.py:500-503, no marker), amendment adoption (amendment.py:100, no marker) — confirmed the edit re-scopes only the §3.7 execution sentence, leaving the "every PASSED or FAILED" wordings of §3.2/§3.4/§3.5/§3.8 intact; verified the remedied run must keep `FAILED` status because `propose_correction` requires a `FAILED` FINAL run to exist (testing.py:246-254) and the filing gate (structure.py:537-545) is orthogonal. (c) Added the explicit "the remedied run itself keeps its status" clause because the strict-`>` filter (common.py:397) excludes the remedied run — behavior the original "every later-created" phrasing left ambiguous.

4. **Clock verbatim reading (§2.5).** (a) Subject: string form of logical-clock readings (`now_iso8601`, `distributed_at`, `executed_at`). (b) Enumerated all clock consumers: verbatim-string writers structure.py:136, safe_harbor.py:197, correction.py:29; parsed-instant consumers safe_harbor.py:64/85 (lapse/window comparisons), correction.py:28-30 (gap/excise date math); storage db.py:50-65 (`_now_str` verbatim, whitespace-trimmed). Confirmed no conflict with §2.2 `api_request_timestamp` (response.py:15-17, wall clock with 3 fractional digits) or §2.4 `created_at`/`updated_at` (common.py:20-22, wall clock with millis) — the edit names only the logical-clock fields. Confirmed §3.7/§3.8 "stamps … from the logical clock" phrasings remain consistent. (c) Scoped the verbatim claim to the clock's own echo and stamps, and said "never normalized to another timestamp format" rather than naming a specific rival format, so the sentence can't be misread as constraining `created_at`/`updated_at`.

## Step 9: Complete PRD — 2026-08-14T07:55:00.000Z

All checks pass. The work is complete — here is the summary.

### Summary

**File produced:** `workspace/PRD_COMPLETED.md`

**Source vs. output:** PRD_FINALIZED.md 284 lines / 58,029 chars → PRD_COMPLETED.md 286 lines / 68,785 chars (**+2 lines, +10,756 chars**). The +2 lines are one short standalone paragraph in §2.2; no new sections were added.

**Counts:** 26 edit operations → **24 ambiguity-pins**, **14 mismatch-revisions** (several edits mix both; classified by dominant character).

#### Changes (section — insert/revise — ambiguity/mismatch — what — impl ref)

- **§2.2** — insert — ambiguity — unrouted path/unsupported method → `ERR_NOT_FOUND` 404; non-JSON body → `ERR_INVALID_REQUEST` 400 — `app.py:33-48`, `services/common.py:45-51`
- **§2.3** — revise — ambiguity — non-integer/out-of-range `limit`/`offset` → 400; sort tie-break by `id` — `services/common.py:196-221`
- **§2.5** — revise — ambiguity — malformed `to_iso8601` → `ERR_INVALID_REQUEST` 400 — `routes/structure.py:130-134`
- **§2.7** — revise — mismatch — all three expected-version fields are **optional** (PRD said "requires"); non-integer → 400, mismatch → 412 only when supplied — `structure.py:432-440`, `testing.py:335-343`, `safe_harbor.py:108-115`
- **§2.8** — revise — mismatch — payload shape is validated as the body is read (before FK/uniqueness on creation endpoints; around the version match on the three OCC endpoints); ssn-uniqueness precedes family-FK, elsewhere FK precedes uniqueness — all route handlers (`structure.py:144-158`, `census.py:124-136`, etc.)
- **§2.8** — insert — ambiguity — any lifecycle/per-entity state-gate failure → `ERR_INVALID_STATE` 409; added the failed-FINAL-run gate to the business-rule order — all route handlers
- **§3.1** — revise — mismatch — `entity_type` drives no derivation (PRD claimed it drives entity attribution; impl has none) — `services/determination.py:24-47`
- **§3.1** — revise — ambiguity — archive refusal (already-ARCHIVED or active-plan-with-non-terminal-year) → `ERR_INVALID_STATE` 409; per-employer plan list takes `status` filter — `structure.py:167-182, 209-219`
- **§3.2** — insert — ambiguity — inverted interval rejected at creation as well as adoption (`ERR_INVALID_DATE_RANGE`); adopting non-DRAFT → `ERR_INVALID_STATE` — `structure.py:289-291, 364-366`
- **§3.2** — revise — ambiguity — amendment truncates/supersedes **each** overlapping ADOPTED version — `services/amendment.py:64-78`
- **§3.2** — revise — mismatch — proration day count is half-open (`effective_end` exclusive), not "inclusive of both endpoints"; projection is a `detail` object (amendments only) with `amendment_impact` per overlapping plan year carrying `plan_year_id`/`days_amended`/`days_total`/`proration`; match projection = deferral-rate tiers over current-year comp, two-stage cent rounding, `projected_safe_harbor_match_cents` + `per_employee` pairs; supersede scope = plan years overlapping the amendment — `services/amendment.py:88-154`
- **§3.3** — revise — ambiguity — negative limits → `ERR_INVALID_REQUEST` 400; non-integer `year_label` filter → 400 — `structure.py:570-576, 601-605`
- **§3.4** — revise — ambiguity — blocked/mistimed census open → `ERR_INVALID_STATE` 409 — `structure.py:408-419`
- **§3.4** — revise — ambiguity — malformed ssn → 400; out-of-range `ownership_pct_direct` → 400; creation defaults for derived fields (`INELIGIBLE`/`NHCE`/`NON_KEY`/direct ownership); patchable field list (ssn immutable) — `census.py:124-153, 162-200`
- **§3.4** — revise — mismatch — compensation record's owner is the path employee (no body FK exists, so the cross-chain FK clause was dropped); `source` is always `IMPORTED` via the API — `census.py:224-243`
- **§3.4** — revise — ambiguity — 402(g) guard evaluated only when an ACTIVE limits row exists; forfeit violations → `ERR_INVALID_STATE` 409 — `census.py:288-299, 317-337`
- **§3.5** — revise — ambiguity — fourth lock precondition: census must be non-empty; sweep bumps each employee's `version`; lock re-evaluates election effectiveness — `structure.py:452-454, 466-471`, `determination.py:146-147`
- **§3.5** — revise — mismatch — removed entity-attribution clause (impl performs none); self-referential family link contributes nothing — `determination.py:24-47`
- **§3.5** — revise — ambiguity — terminated-before-year-start exclusion requires a `date_of_termination` on record (HCE and key sweeps) — `determination.py:56-58, 77-79`
- **§3.5** — revise — ambiguity — full coverage-cohort rules pinned: hired after `year_end` → `INELIGIBLE`; terminated on/before `year_end` → `EXCLUDABLE`; hired after `year_start` → `EXCLUDABLE`; else `BENEFITING` via plan-type contribution sets (POSTED/PENDING_DISTRIBUTION/DISTRIBUTED) or active safe harbor design; else `ELIGIBLE_NOT_BENEFITING` — `determination.py:93-137`
- **§3.6** — revise — ambiguity — execution is driven only via execute-synchronously; out-of-order (earlier queued sibling, ties by `id`) or non-QUEUED call → `ERR_INVALID_STATE` 409; version bumps on every queueing; finalize transitions the year only from TESTING but bumps plan-year and run versions regardless — `testing.py:147-194`
- **§3.6** — insert — ambiguity — per-battery `detail` key enumeration and `distribution_review_contribution_ids` flag key — `services/engine.py:77-84, 151-162, 195-204, 254-289, 328-334, 389-406`
- **§3.6** — revise — ambiguity — battery gating: coverage/ADP/ACP/top-heavy run for any plan type; cafeteria/dependent-care gated by plan type; coverage NHCE% = 0 when no eligible NHCE; NOT_APPLICABLE coverage line carries 0.0000; empty ADP/ACP cohort averages 0.0000; all three ADP/ACP lines share outcome and ceiling threshold — `engine.py:70-94, 121-162, 360-374`
- **§3.6** — revise — mismatch — removed the top-heavy "allocation waterfall" (impl computes only the shortfall total); key rate = all contribution types in POSTED/PENDING_DISTRIBUTION/DISTRIBUTED over current-year comp, zero-comp keys skipped — `engine.py:207-236`
- **§3.6** — revise — ambiguity — cafeteria: eligible-NHCE definition, zero-denominator → 0.0000, concentration denominator excludes `EXCLUDED_FROM_TESTING`, zero-total → 0.0000, and the `CAFETERIA_UTILIZATION_PCT` line (null threshold, always NOT_APPLICABLE); dependent-care cohort excludes `EXCLUDED_FROM_TESTING` and `EXCLUDABLE`, threshold 55.0000; PROVISIONAL also counts RECHARACTERIZED amounts — `engine.py:243-334`
- **§3.7** — revise — ambiguity — `test_run_id` is only an FK to a run of the same plan year (mode/result unchecked); target FK 422; missing non-QNEC target → 400; failed-FINAL gate requires status `FAILED` (not SUPERSEDED) → `ERR_INVALID_STATE`; Feb 29 → Feb 28 deadline — `testing.py:217-265`, `correction.py:15-22`
- **§3.7** — revise — mismatch — any `ComplianceAnalyst` (not only the proposer) voids a PROPOSED correction; wrong-role/state void → `ERR_INVALID_STATE` 409 — `testing.py:379-402`
- **§3.7** — revise — mismatch+ambiguity — waterfall tie-break adds `id`; partial split shrinks the original row to the distributed portion with a RECHARACTERIZED sibling (same type/date); dropped the nonexistent "deferral totals reconciled" side effect; QNEC creates one POSTED row **per NHCE** (PRD said singular) dated `year_end`, remainder to earliest-created, none when cohort empty; RECHARACTERIZATION/QMAC walk mechanics pinned; `QMAC_REALLOCATION` and `PLAN_AMENDMENT_RETRO` behaviors pinned (were silent); gap days floored at zero; excise/gap income computed only for `CORRECTIVE_DISTRIBUTION` — `services/correction.py:25-164`
- **§3.8** — revise — ambiguity — election proposal allowed only in DRAFT/CENSUS_COLLECTING/CENSUS_LOCKED/TESTING/RESULTS_REVIEW; effectiveness requires the year to **be** CENSUS_LOCKED and is evaluated at distribute/acknowledge/lock; "governing plan version" = the pinned `adopted_version_id`; notices creatable under an election in any status; the 30-day rule applies iff the year is CENSUS_COLLECTING at distribution, initial rule otherwise — `routes/safe_harbor.py:25-27, 66-90, 143-161`, `services/safe_harbor.py:11-47, 74-91`
- **§3.9** — revise — mismatch+ambiguity — filing gate considers only FINAL runs still PASSED/FAILED, created strictly after the last-created EXECUTED correction (by `created_at`), and all such runs when none executed; excise-at-filing scoped to `CORRECTIVE_DISTRIBUTION` (PRD said every EXECUTED correction); termination also bumps the parent plan's `version` — `structure.py:509-553`, `correction.py:167-185`

Tests were used only as auxiliary cross-reference; every pin above cites the implementation as authority.
