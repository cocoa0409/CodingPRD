# Worklog — task_2346_insurance_market_conduct_examination

## Step 1: Create task directory — 2026-09-01T23:29:02.000Z

Created `tasks/task_2346_insurance_market_conduct_examination/` and `tasks/task_2346_insurance_market_conduct_examination/workspace/` (pre-allocated task name used verbatim; no index scan performed).

## Step 2: Generate scaffold — 2026-09-02T02:09:28.000Z

Done. All three artifacts are complete, mutually consistent, and lint-clean.

## Files (all in `/home/ubuntu/github/CodingPRD/tasks/task_2346_insurance_market_conduct_examination/`)

**`SCAFFOLD.yaml`** (§1.0–§1.7, 140 KB) — no `scaffold_difficulty_design` / `scaffold_corner_design` key present.
- **13 entities**: Insurer, MarketAnalysisCycle, AnalysisScore, Examination (self-referential via `predecessor_exam_id`), ExamScopeArea, DataCall, FileSample, FieldworkActivity, Criticism, CompanyResponse, CorrectiveActionPlan, ConsentOrder, MultistateCollaboration (2 immutable: FieldworkActivity, CompanyResponse).
- **52 endpoints** under `/market-conduct` (51 business + 1 `/_clock/set_current_utc` test driver), **8 state machines**, **12 calculations**, **44 validation rules** (priority ladder 10→71), **42 error codes**, **5 roles** (4 opaque + `InsurerRespondent` = `entity_backed:Insurer`), **2 concurrency rules** (both OCC on `expected_examination_version`, 412).
- `difficulty_level: beyond-expert`; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers; topology hybrid, shape cyclic, role_model segregation_of_duties, consistency immediate.

**`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** (§1.8) — **27 instances** across all 9 §0.5 rules (3/3/3/3/3/4/3/2/3), 380 structured calls.

**`SCAFFOLD_CORNER_DESIGN.yaml`** (§1.9) — **142 instances / 9 sections**, 108 with full recipes + 34 `excluded_because` stubs, 1336 structured calls:
entities 24 (4 stubs) · state_machines 22 (5) · calculations 18 (6) · validations 12 · endpoints 8 · errors 42 (17) · rbac 9 · cross_cutting_layers 5 (2) · consistency_model 2.

## Coverage audit
- **Endpoints: 52/52** exercised by real §1.9 calls (independent auditor replicating the linter's path-template matcher).
- **Errors: 42/42** — one errors-section instance per declared code; 25 real recipes, 17 stubs each citing an existing §1.8 instance by name.
- **Validation rows: 44/44**, **calculations 12/12**, **entities 13/13**, **state machines 8/8** all cited in `grounds`; 0 dangling grounds references.
- **0 unbound `${var}`** across both design files; all names unique across the union (169 names); every stub citation resolves; no stub carries a `test_recipe`.
- All OCC payloads reference captured `${var}`s, never literals.

Fixes made while auditing: claim_type values were normalised to the `claim-extraction-guide` vocabulary (snake_case, e.g. `invalid_transition`, `violation_to_error`, `waterfall_allocation`, `error_triggerable`, `exclusive_operations`, `immediate`) rather than invented labels; `complexity_profile.layers[…]`/`.consistency` grounds corrected to the real keys `complexity_layers[…]`/`consistency_model`; one unbound `${exam_v}` rebound to the version actually captured in that instance.

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2346_insurance_market_conduct_examination/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2346_insurance_market_conduct_examination/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2346_insurance_market_conduct_examination/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    52
  §1.1 entities declared:     13
  §1.8 instances scanned:     27
  §1.9 instances scanned:     108
  Calls scanned (§1.8+§1.9):  1716

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

The hard constraint was honored throughout: no sibling task directory under `tasks/` was listed, globbed, grepped, or read at any point — the scaffold derives solely from the scenario text and the generator skill's own specification.

## Step 3: Copy shared files — 2026-09-02T02:09:28.000Z

Copied `INSTRUCTION.md` → `tasks/task_2346_insurance_market_conduct_examination/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T02:24:30.000Z

PRD generated and verified.

## Output

`/home/ubuntu/github/CodingPRD/tasks/task_2346_insurance_market_conduct_examination/workspace/PRD.md` — **437 lines**, ends at §5 (no audit footer written into the file).

## Sections

- **§1 Introduction** — 3 paragraphs, regulator's-eye framing; names `/market-conduct` and the two dominant properties (conservation, immutability of decided figures).
- **§2 Global Specifications** — 11 subsections: 2.1 Departmental Roles and Access Control · 2.2 API Response Structure (byte-identical paste of `section-2.2-response-structure.md`) · 2.3 Pagination · 2.4 Record Identity, Audit Stamps and the Logical Clock · 2.5 Statutory Precision and Rounding Discipline · 2.6 Version Pinning on Enforcement Writes · 2.7 Cascade Propagation Through the Examination Hierarchy · 2.8 Nested Path Resolution · 2.9 Segregation of Duties · 2.10 Conserved Ledgers · 2.11 Order of Rejection.
- **§3 Business Logic & Workflows** — 10 subsections: carrier data set / complaint ratio · analysis cycles (composite scoring + target selection + cycle closure) · opening an examination and scope definition · data calls (issuance, production, disposition, the three rejection outcomes) · sampling, file review, tolerance testing · workpapers and criticism issuance (exposure freezing) · rebuttal rounds and finalization · corrective action, consent orders, penalty determination · multistate collaboration and restitution allocation · publication, follow-up scheduling, abandonment.
- **§4 Endpoint Definitions** — 201/200 preamble + 52-row, 4-column table.
- **§5 Error Code Catalogue** — 42-row, 2-column table.

## Coverage audit

13 entities · 52 endpoints (all 52 paths present verbatim, table row count 52) · 8 state machines / 35 transitions · 12 calculations · 44 validations · 42 errors (table row count 42) · 2 concurrency rules · 5 roles.

**Contract 1 — Field coverage check** (two passes; second pass required each name to appear as its own standalone backticked token, not merely embedded)
```
- entities[].fields: 139 required, 139 present, 0 missing
- endpoints[].input (request bodies): 75 required, 75 present, 0 missing
- endpoints[].path_params: 1 required, 1 present, 0 missing
- nested/aux identifiers (participating_states members, reviews, pagination, common fields): 8+ required, all present, 0 missing
- strict standalone re-check: 158 names, 158 as own token, 0 embedded-only
Status: PASS
```

**Contract 2 — Rule coverage check**
```
- validations[] with priority: 44 checked, 44 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write endpoint + expected_examination_version + ERR_STALE_EXAMINATION_VERSION + 412 all named), 0 missing
- state_machines[].transitions: 35 checked, 35 fully expressed, 0 missing
- calculations[]: 12 checked, 12 fully expressed with pinned evaluation order, 0 missing
- validations[] conditions: 44 checked, 44 matchable to error_id in prose, 0 missing
- endpoints[].side_effects: 27 endpoints with side effects, all expressed, 0 missing
- entities[].fields[] structured content (enums, defaults, ranges, uniqueness, computed-from): reconstructible from prose, 0 missing
- sibling-branch symmetry: 8 groups checked (accept/reject disposition; sustain/withdraw; APPROVE/REJECT/REQUEST_REVISION; clean vs enforcement publication; SAMPLE_ACTUAL/POPULATION_EXTRAPOLATED; PER_VIOLATION/TIERED_AGGREGATE; single vs bulk review; cycle-spawned vs directly-opened examination), 0 asymmetric
Status: PASS
```

**Contract 3 — Path purity check (§3 only)**
```
- backtick tokens scanned: 907 (303 unique)
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Zero-Silence notes

Every numeric constant is stated in prose and verified by grep: 25,000 / 100,000 / 5,000,000 / 20,000,000 / 25,000,000 / 50,000,000 / 5,000,000,000 cents; tier rates as one tenth / six hundredths / three hundredths; credit rates as fifteen / five hundredths; component multipliers three tenths and two tenths; caps 30.00 and 100.00; thresholds 95.00, 40.00, 10.00, 5.00, 2.50, 1.00; per-area tolerances 7.00 / 5.00 / 3.00 / 10.00; minimum sample sizes 10 (on-site) and 5 (desk); the 3-day data-call spacing (strict); the 0.50-per-day lateness deduction; 12/18/24-month follow-up intervals; the 60-day follow-up window; six-digit zero-padded file references with `UW`/`RT`/`CLM`/`PRD` prefixes; logical clock origin `2026-08-01T00:00:00Z`; department state `NV`.

Explicitly-stated silent-failure traps: rounding order pinned in five places (composite score, effective completeness, extrapolated average, per-tier penalty rounding, the five-step credit chain); the penalty ceiling rejects rather than clamps; `id` is banned as a tie-break anywhere; `FieldworkActivity` and `CompanyResponse` are stated to have no `updated_at` and no `version` keys at all; empty candidate pool at target selection is stated to be a non-error; three distinct data-call-rejection outcomes for the scope area are all spelled out; publication from `CRITICISM` with any sustained criticism is stated to be rejected; withdrawal's non-accrual is stated field by field.

Two backticked non-path composite object shapes appear in §3 (the exposure-summary and bulk-review response shapes) — these are output shapes, not paths or methods, so path purity is unaffected.

No content was read from `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, or any sibling task directory.

## Step 5: Generate unit tests — 2026-09-02T03:10:00.000Z

All audits pass. Work complete.

## Test infrastructure (`test_helpers/`, 9 modules)

`/home/ubuntu/github/CodingPRD/tasks/task_2346_insurance_market_conduct_examination/test_helpers/`
- `types.py` — 25 enums + TypedDicts for all 13 entities (`FieldworkActivity`/`CompanyResponse` deliberately omit `updated_at`/`version`)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (52) under prefix `/market-conduct`
- `api_errors.py` — `ApiErrorId` (42 ids) + `HTTP_STATUS_CODES`, registered with the framework status map
- `constants.py` — every PRD threshold/rate/cap/window plus `TEST_DEFAULTS`
- `test_users.py` — canonical role ids, `TEST_USERS`, `make_insurer_respondent_headers()` (carrier identity == `Insurer.id`), shortcuts `ANALYST/EIC/EIC_B/SUPERVISOR/SUPERVISOR_B/COORDINATOR`
- `factories.py` — 21 `**overrides` payload factories + `systematic_file_references()`
- `assertions.py` — per-entity shape assertions, precision helpers, and the four conserved-ledger invariants
- `fixtures.py` — 40 primitives + 11 composites (`setup_locked_examination` → `setup_settled_collaboration`)
- `__init__.py` — single-import barrel over the framework generics and all of the above

`test_suite/conftest.py` exposes the `api` client and per-role header fixtures.

## Test cases: 202 tests in 15 files

| File | Tests | Source |
|---|---|---|
| test_01_carrier_and_cycle_records.py | 12 | Corner/entities |
| test_02_examination_child_records.py | 8 | Corner/entities |
| test_03_scope_and_data_call_lifecycle.py | 9 | Corner/state_machines |
| test_04_enforcement_lifecycle.py | 8 | Corner/state_machines |
| test_05_scoring_and_penalty_calculations.py | 12 | Corner/calculations |
| test_06_validation_gates.py | 12 | Corner/validations |
| test_07_endpoint_semantics.py | 8 | Corner/endpoints |
| test_08_error_catalogue_part_1.py | 19 | Corner/errors |
| test_09_error_catalogue_part_2.py | 14 | Corner/errors |
| test_10_role_access_control.py | 10 | Corner/rbac |
| test_11_concurrency_and_consistency.py | 5 | Corner/cross_cutting_layers + consistency_model |
| test_12_restitution_and_penalty_variants.py | 17 | Difficulty rules 1–2 |
| test_13_state_cycles_and_cascades.py | 19 | Difficulty rules 3–4 |
| test_14_rejection_order_and_boundaries.py | 18 | Difficulty rules 5–6 |
| test_15_prerequisites_windows_and_conservation.py | 31 | Difficulty rules 7–9 |

**Queue A: 85 tests / 27 of 27 difficulty instances, every one with ≥2 tests.**
**Queue B: 117 tests / 108 of 108 non-stub corner instances, every one with ≥1 test.**

## Audit results (machine-verified)

- 202 `def test_` == 202 `Design:` lines; each is the final docstring line, well-formed, and resolves to a real instance in the source index. No dual-tags, no untagged tests.
- Zero tests translate an `excluded_because:` stub (all 34 stubs left untranslated, as required).
- Every test carries at least one quoted PRD span of ≥8 words that matches `workspace/PRD.md` verbatim after whitespace normalisation.
- No `skip`/`skipif`/`xfail`/placeholder anywhere; no reference to the scaffold or design yamls in any test file.
- `py_compile` clean; `pytest --collect-only` collects all 202 tests (server intentionally not started, so nothing was executed).

## Skips and narrowings

**No instance was skipped entirely** — the PRD proved complete enough to ground all 135 non-stub instances. Skipping happened at assertion level, where a design expectation was not uniquely derivable from the PRD:

- **Timestamp exactness** (several files): the PRD fixes the *source* (logical clock) and mandates three fractional digits, so exact-string equality on `tested_at`, `criticism_phase_opened_at`, `report_published_at`, `closed_at`, `conducted_at`, `submitted_at`, `current_utc` was replaced by well-formedness + date-prefix assertions.
- **Undeclared query filters** (test_03/04/05/07/09/13): `status` / `review_status` / `error_severity` filters used by design recipes on scope-area, data-call, file-sample and consent-order collections are not in the PRD's endpoint contract, so those lists are read unfiltered and filtered client-side. Filters the PRD *does* declare (criticism filters, `predecessor_exam_id`, `cycle_id`, `selected`, `activity_type`, `position`, `risk_tier`, `license_status`) are asserted.
- **Null-vs-absent creation defaults** the PRD never names (`scored_at`, `closed_at`, `responded_at`, `followup_due_date`, `allocation_completed_at`, `report_published_at`) — dropped.
- **test_12**: the design's `financial_stress_score: 120` / `consumer_trend_score: 200` inputs violate the PRD's 0–100 bound, so PRD-maximal legal inputs were used; the consequent unreachable `trend_component == 30.00` and `composite_score == 100.00` ceilings were dropped in favour of the reachable 20.00/99.00.
- **test_15**: three assertions on the criticism-*withdrawal* branch dropped (`status == NEGOTIATION`, `pending_enforcement_exam_count == 1`, `penalty_units == 4`) — §3.7 pins those only on the *sustaining* branch.
- **test_07**: bulk-review row with an unknown `file_reference` removed (PRD defines `skipped_file_references` only for already-reviewed refs); insurer-list row *ordering* not asserted since all rows share one logical-clock `created_at`.
- **test_14/test_11**: absolute `version` values after a rejected write or a 10-row bulk batch dropped (PRD states increment-per-mutation but not the batch granularity); version *deltas* on the two PRD-guarded enforcement writes are asserted instead.

Every ordering claim that survived is backed by a §2.11 band sentence or explicit §3 prose; no relative-precedence assertion rests on the scaffold's numeric priorities alone.

## Step 6: Generate implementation — 2026-09-02T03:10:00.000Z

Implementation complete and validated.

## Modules (`workspace/implementation/`)
- `start.sh` (guarded `pip install`, then `exec python3 app.py`; `PORT` default 10000, binds `0.0.0.0`), `requirements.txt` (`Flask>=3.0`), `app.py` (blueprint registration under `/market-conduct`, `ApiError`/`HTTPException`/500 handlers)
- Core: `db.py` (in-memory `Store` of 13 dicts + logical clock at `2026-08-01T00:00:00Z`, date helpers), `errors.py` (all 42 error ids → HTTP status), `response.py` (envelope, pagination), `middleware.py` (`X-User-ID` UUID + `X-User-Role` gating), `validation.py` (shape/format helpers)
- `services/`: `calculations.py` (all statutory formulas and pinned rounding orders), `derive.py` (derived counters/aggregates computed on read), `serialize.py`, `guards.py` (existence/ownership/lifecycle), `transitions.py` (all state hops, cascades, overdue sweep)
- `routes/`: `insurers, cycles, examinations, scope_areas, data_calls, file_samples, criticisms, plans, orders, collaborations, clock` (+ `common.py`)

## Endpoints
52 of 52 implemented (route dump confirms exactly 52 method+path pairs, all under `/market-conduct`). Storage is in-memory only, empty at boot — verified with a fresh `start.sh` launch returning `total_count: 0` and the clock at its epoch. `pyflakes` is clean.

Validation: three self-written smoke suites (156 assertions total) all pass with 0 failures, covering the full happy path (score → select-targets → scope → lock → data call → respond → accept → sample draw/review → criticism → response/rebut → finalize → CAP → consent order → execute → publish → cycle close), both penalty variants, the cooperation-credit chain, multistate lead election plus cent-conserving allocation, the overdue sweep, abort cascade, and ~50 error paths.

## PRD ambiguities resolved
- **Aggregates**: every count/sum on Insurer/Examination/ScopeArea/Cycle is derived from children on read, so counters cannot drift; version bumps happen only where PRD §3 names them (no bump on Insurer/Cycle for slot or counter movement, none on the exam for a REJECTED data-call disposition, exactly one area bump per review request).
- **Flags**: `tolerance_breached`/`escalation_required` are recomputed from current rates on every read rather than latched.
- **Rejection order**: `ERR_EXAM_ALREADY_TERMINAL` evaluated first within §2.11 band 8; ownership/SoD checks run after the target row is resolved (observationally identical to the band order); `ERR_FIELDWORK_NOT_DOCUMENTED` keys on the existence of a matching activity, not its `documented` flag.
- **Clock endpoint**: needs no `X-User-ID`, tolerates a missing role, rejects an unknown role, and echoes `current_utc` verbatim as supplied.
- **Ordering ties**: `created_at` ties broken by an internal insertion sequence, never by `id`.
- **Bulk review**: unknown `file_reference` values count as skipped (not an error), as do already-reviewed samples.
- **Underspecified guards**: `affected_file_count < 1` → `ERR_INVALID_REQUEST`; a scoring pass with no LICENSED/SUSPENDED carrier → `ERR_INVALID_REQUEST` (after the cycle-state check); `respond` on a call whose exam is outside DATA_CALL/FIELDWORK → `ERR_DATA_CALL_NOT_AWAITING_RESPONSE`.
- **Selection rows**: every AnalysisScore row receives a `selection_reason`, so selection touches (versions) all of them; precedence is LICENSE_INELIGIBLE → BELOW_THRESHOLD → WINDOW_CONFLICT_DEFERRED → SELECTED/CAPACITY_EXHAUSTED.
- **Criticism withdrawal**: writes no `penalty_units` and releases only the pending pool, but still evaluates the CRITICISM → NEGOTIATION bubble-up.
- **Reads**: `GET /insurers/{id}` is not ownership-restricted; `FieldworkActivity` and `CompanyResponse` payloads omit `updated_at`/`version` entirely; Decimals serialize as JSON numbers.

## Step 7: Run tests and iterate — 2026-09-02T08:28:59.000Z

Done. Final report below.

## Outcome

The task's own artifacts are green. One genuine defect existed; it is fixed. Every one of the 202 tests passes, and I could not produce a single further assertion failure in ~16 further 8-round sweeps (≈120 rounds, ≈24,000 test executions). What I could not achieve is the literal `passed == total` in all 8 rounds of one sweep, because the shared host is actively hostile — proven below, not assumed.

**Iterations run:** 16 full 8-round parallel sweeps (`--isolation per-test-server`, 202 tests/round). Best result: **7 of 8 rounds at exactly 202/202**, twice (07:04 and 07:15 sweeps). Every post-fix sweep reported `real_failures = 0` and `never_passed = []`.

**Tests deleted:** none. No test asserted a scaffold-only rule; no PRD-silence or collapse pattern applied.

**Fixes applied to `test_helpers/`:** none. All fixtures, factories and role-header builders trace to PRD prose; `make_insurer_respondent_headers` correctly uses `Insurer.id` as the carrier identity.

**Fixes applied to `implementation/`:** one, in `/home/ubuntu/github/CodingPRD/tasks/task_2346_insurance_market_conduct_examination/workspace/implementation/routes/examinations.py`, function `create_fieldwork_activity` (line 241):

```python
summary = v.require_narrative(payload, "summary")   # was: v.get_str(payload, "summary", min_len=1)
```

Why: PRD §2.11 band 6 enumerates `summary` among the free-text fields whose minimum is twenty characters, and band 6 is evaluated before the band-8 lifecycle check. Without it a 10-character summary was accepted (201) and, in `SCOPING`, fell through to `ERR_SCOPE_NOT_LOCKED`. This was the single root cause of both genuine failures (`test_02`'s append-only/`documented` test and `test_08`'s `test_invalid_request_across_the_declared_shape_families`). Verified by curl: short summary in `SCOPING` → `ERR_INVALID_REQUEST` (422); long summary in `SCOPING` → `ERR_SCOPE_NOT_LOCKED` (409).

## Why 8/8 was unreachable — two environmental causes, both proven

1. **Runner's own `lsof` teardown timeout.** `pytest_plugin._kill_port()` (`/home/ubuntu/github/CodingPRD/prd-bench-local-runner/src/prd_bench_local_runner/pytest_plugin.py:46`) runs `lsof -ti:PORT -sTCP:LISTEN` with `timeout=5` and does **not** catch `subprocess.TimeoutExpired`, so the exception escapes `pytest_runtest_setup` and the test is recorded as an error before it runs. (`port_utils.kill_port` does catch it; the plugin copy doesn't.) I measured `lsof` at 2.78 s → 4.10 s against the 5 s cliff, with ~250 concurrent sibling `prd-bench-local-run` processes and load average 90–292. Setup errors tracked load exactly: 287 → 124 → 48 → 36 → 19 → 5 → 1 → 0 as load fell, then back to 334 when it spiked to 292.

2. **A host-wide external `SIGTERM` sweep killing servers mid-test.** All non-`lsof` failures were `ConnectionResetError(104)` / `RemoteDisconnected`. Evidence they are external:
   - Server logs show `Terminated` (SIGTERM) mid-run; the harness only ever sends SIGKILL (`Killed`) via `_kill_port`.
   - Those SIGTERMs land on **all 8 independent round ports at the same wall-clock second** (06:02:44, 06:05:00, 06:07:02, …) — impossible for per-round logic.
   - A canary server I ran on port **61234** (outside the ephemeral range 32768–60999, in no port registry, unknown to any runner) was killed **31 times with `exit=143`** in the same bursts.
   - No crontab, no systemd timer, no `pkill` anywhere in the repo — so it is ad-hoc cleanup from concurrent agent sessions on this box.
   - At 07:55 one whole sweep's eight runners were killed within 39 s, producing no results files at all.

Neither cause is reachable from `PRD.md`, `test_suite/`, `test_helpers/` or `implementation/`. I deliberately did not "fix" either by touching runner sources, by adding retry/keep-alive workarounds to the client, or by adding an idle-shutdown to the server, since the last would be an untraceable capability change and could break a real grading run.

## State left behind

`workspace/implementation/` contains only the deliverable (`app.py`, `db.py`, `errors.py`, `middleware.py`, `response.py`, `validation.py`, `requirements.txt`, `start.sh`, `routes/`, `services/`). I removed my scratch driver/canary scripts, per-round logs, `__pycache__`, and the `results.*.json` files (the last sweep's were from the load-292 degraded window and not informative). Final smoke check confirms the server boots, storage is empty at boot, and the logical clock sits at `2026-08-01T00:00:00.000Z`. This task's runner and server processes were stopped; no sibling pipeline was touched.

## Step 7 verification (orchestrator-run) — 2026-09-02T08:58:22.000Z

Orchestrator independently re-ran the full 8-round parallel sweep and classified every non-pass by exception signature. Result: **zero assertion failures across all 8 rounds / 1,616 test executions.** Round totals: 177, 185, 181, 185, 176, 179, 190, 178 of 202. Every single non-pass was one of:
- `subprocess.TimeoutExpired: Command 'pids=$(lsof -ti:PORT -sTCP:LISTEN ...)' timed out after 5 seconds` — 161 occurrences, recorded as a **setup error** (the test body never executed), raised inside the runner's own `pytest_plugin._kill_port()`.
- `requests.exceptions.ConnectionError: ('Connection aborted.', ConnectionResetError(104, 'Connection reset by peer'))` — 4 occurrences, server killed mid-test.

Host state during the sweep: load average 188–260 on 32 cores, with 206 concurrent sibling `prd-bench-local-run` processes from other pipelines on the same box. This independently confirms the Step 7 subagent's diagnosis: the residual non-passes are host-contention artifacts in the test runner, not defects in `test_suite/`, `test_helpers/`, or `implementation/`. No test or implementation change could remedy them.

## Step 8: Finalize PRD — 2026-09-02T09:05:00.000Z

`PRD_FINALIZED.md` is a byte-identical copy of `PRD.md`. No edits were warranted.

## Line counts / delta
- `PRD.md`: 437 lines; `PRD_FINALIZED.md`: 437 lines. **0 lines changed, 0.00% delta.** Identical md5 (`0926dd11190436a0eef4c006664a0457`), `diff` empty.

## Changes
None. Zero edits.

## Why no edit was justified

The Step 7 diff contained exactly one implementation fix, zero test deletions, and zero `test_suite/`/`test_helpers/` fixes. That single fix was a PRD-*conformance* fix (impl was wrong, PRD was right), not a PRD-silence fix:

- `implementation/routes/examinations.py:241` — `summary = v.require_narrative(payload, "summary")`, replacing `v.get_str(payload, "summary", min_len=1)`.
- PRD.md §2.11 band 6 (line 161) already enumerates the field by name: *"a `narrative`, `summary`, `public_summary` or `rebuttal_note` shorter than 20 characters"*. Band 6 already sits ahead of band 8 (`ERR_SCOPE_NOT_LOCKED`) in the same enumerated list at lines 144–159. The 20-character minimum on `summary` and its precedence over the lifecycle check are therefore both uniquely determined by PRD.md as written; the fix moved the impl onto the PRD, leaving nothing to pin.

## Pre-edit search log

Even though no edit was committed, I ran the mandatory subject search to confirm no *adjacent* wording in PRD.md had become false under the fixed implementation.

**(a) Subject identified:** the 20-character minimum on the narrative-family free-text fields, and the derived `documented` flag on `FieldworkActivity` that reads `summary`'s length.

**(b) Impl paths enumerated (read/grepped):**
- `implementation/validation.py:18` (`MIN_NARRATIVE_CHARS = 20`) and `:133-140` (`require_narrative`, which delegates to `get_str` with `min_len=None` then applies the 20-char floor) — the single shared enforcement point.
- Every `require_narrative` callsite, i.e. every field the rule can apply to: `routes/examinations.py:241` (`summary`, fieldwork activity), `:335` (`public_summary`, publish-report), `:383` (`narrative`, corrective action plan), `routes/criticisms.py:151` (`narrative`, company response), `:204` (`rebuttal_note`, rebut). All five field names, and only those five, carry the floor — exactly the set band 6 names.
- Negative check via grep for other free-text fields to confirm none silently inherits the floor: `disposition_note` (`criticisms.py:241`), `review_note` (`plans.py:39`), `disposition_reason` (`data_calls.py:101`), `abort_reason` (`examinations.py:368`), `call_reference` (`examinations.py:525`), `evidence_ref` (`examinations.py:242`), `signed_by` (`orders.py:31`), `statute_citation` (`criticisms.py:50`), `submitted_by_contact` (`data_calls.py:55`), `participant_name`/`participant_title` (`examinations.py:237-238`) — all use `get_str` with `min_len=1` or no floor, matching PRD's silence on them.
- `routes/examinations.py:251` — `documented = len(summary) >= v.MIN_NARRATIVE_CHARS and bool(evidence_ref and evidence_ref.strip())`, against PRD §3.6 line 247.
- Band-ordering path at the Step 7 site: `get_exam` (band 5) → field parsing (band 6) → `ensure_exam_writable` / `SCOPING` check (band 8), matching §2.11's order.

**(c) Wording adjustment:** none needed. One point worth flagging for Step 9: because band 6 now rejects a sub-20-character `summary` outright, §3.6's clause *"`documented` … is true only when the `summary` runs to at least 20 characters **and** an `evidence_ref` is present and non-empty"* describes a conjunct whose first operand is vacuously true in practice — `documented` is decided by `evidence_ref` alone. That is a redundancy, not a divergence: `examinations.py:251` evaluates literally that conjunction, so the prose remains a true description of the code and was left verbatim. Rewriting it to drop the `summary` operand would have been an unforced edit outside the Step 7 scope and would have narrowed a sentence the impl still exhibits verbatim.

## Step 9: Complete PRD — 2026-09-02T09:16:00.000Z

Done. `workspace/PRD_COMPLETED.md` written.

**Counts** — source `PRD_FINALIZED.md`: 437 lines / 87,283 chars. `PRD_COMPLETED.md`: 437 lines / 93,565 chars (**+6,282 chars**, no lines added or removed — all edits are in-paragraph). 27 lines touched, **29 changes: 23 ambiguity-pins, 6 mismatch-revisions.**

- §2.1 — revise — ambiguity — clock endpoint accepts a missing/empty/malformed `X-User-ID` *and* a wholly absent `X-User-Role`; only an out-of-set role is refused — `middleware.py:63-81`
- §2.1 — revise — mismatch — respondent ownership guards single-record reads and examination-nested collections only; `GET /examinations` and `GET /criticisms` are unfiltered and `GET /insurers/{id}` is not ownership-restricted — `examinations.py:118-126`, `criticisms.py:126-133`, `insurers.py:89-98`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` malformed, empty string = absent; undeclared query params and uninterpretable filter values ignored; the seven undocumented `status`/`area`/`review_status`/`error_severity` list filters — `response.py:65-85`, `routes/common.py:13-29`
- §2.3 — insert — ambiguity — `created_at` ties broken by internal insertion sequence, never by `id` — `db.py:121-126`
- §2.4 — revise — mismatch — derived counters are recomputed on read, never stored; recomputation is not a mutation, so `version` moves only where §3 names it — `services/derive.py:180-264`
- §2.4 — revise — ambiguity — `current_utc` echoes the supplied `to_iso8601` string verbatim — `routes/clock.py:18-21`
- §2.5 — insert — ambiguity — Decimals serialised as JSON numbers (7.00 → `7.0`) — `response.py:33-36`, `services/serialize.py:12-13`
- §2.7 — revise — mismatch — upward propagation is derive-on-read; counters can move without the holder's `version` (rejected data call; carrier/cycle on exam open) — `data_calls.py:131-137`, `examinations.py:94-115`
- §2.9 — revise — mismatch — both SoD checks run after the addressed row is resolved (404 wins) but before shape/terminality/state — `criticisms.py:227-233`, `examinations.py:327-337`
- §2.11 band 4 — insert — mismatch — bands 3 and 4 each run right after the addressed row (and its owning examination) is looked up; band-5 404 outranks the 403 — `services/guards.py:67-74`, `orders.py:27-29`
- §2.11 band 8 — insert — ambiguity — `ERR_EXAM_ALREADY_TERMINAL` is evaluated first within band 8 — `services/guards.py:78-86` (call sites throughout `routes/`)
- §2.11 band 6 — insert — ambiguity — roster over twelve, `affected_file_count` below 1, non-zero `underpaid_amount_cents` with `NONE`, unparseable body — `examinations.py:560-561`, `criticisms.py:52`, `data_calls.py:33-36`, `validation.py:21-34`
- §3.2 — insert — ambiguity — no LICENSED/SUSPENDED carrier → `ERR_INVALID_REQUEST`, after the `DRAFT` state check — `cycles.py:91-104`
- §3.2 — insert — ambiguity — rank ties (identical `created_at` within a pass) settled by write sequence = carrier registration order — `cycles.py:25-31,133`
- §3.2 — insert — ambiguity — selection increments **every** score row's `version` by 1 — `cycles.py:198-199`
- §3.3 — insert — ambiguity — `cycle_id` may name a cycle in any `status` — `examinations.py:62,89`
- §3.4 — revise — ambiguity — exam outside `DATA_CALL`/`FIELDWORK` on respond → `ERR_DATA_CALL_NOT_AWAITING_RESPONSE` — `data_calls.py:63-68`
- §3.4 — insert — ambiguity — each acceptance re-materialises the full plan (duplicate indices/references); an area already `FIELDWORK`/`TESTED` keeps its status — `data_calls.py:121-128`, `transitions.py:91-109`
- §3.5 — insert — ambiguity — non-zero harm with `NONE` → `ERR_INVALID_REQUEST`; both harm fields optional, default 0 — `data_calls.py:26-37`
- §3.5 — revise — mismatch — bulk review skips a `file_reference` matching no sample of the call; a no-op batch leaves the area's `version` alone — `data_calls.py:171-185`
- §3.5 — insert — ambiguity — `tolerance_breached`/`escalation_required` (and the counts/rates) recomputed on every read, never latched — `services/derive.py:181-198`
- §3.5 — revise — ambiguity — every review increments the owning area's `version` by 1, not just the closing one — `transitions.py:76-88`
- §3.6 — insert — ambiguity — the fieldwork gate keys on `activity_type` existence and ignores the activity's `documented` flag — `criticisms.py:111-123`
- §3.6 — revise — ambiguity — `affected_file_count` below 1 is caught in band 6, not as `ERR_AFFECTED_FILES_EXCEED_ERRORS` — `criticisms.py:52`
- §3.7 — revise — ambiguity — `disposition_note` recorded on both dispositions — `criticisms.py:252-254`
- §3.7 — insert — ambiguity — withdrawal writes no `penalty_units` yet still evaluates the `CRITICISM → NEGOTIATION` bubble-up — `criticisms.py:255-263`, `transitions.py:58-65`
- §3.8 — insert — ambiguity — a cap rejection leaves the prior `DRAFT` order un-voided — `examinations.py:476-486`
- §3.10 — revise — ambiguity — an open `ISSUED`/`RESPONDED` criticism also blocks publication from `CRITICISM` with `ERR_EXAM_NOT_READY_FOR_PUBLICATION` — `examinations.py:345-352`
- §3.10 — insert — ambiguity — the follow-up examination gets no fieldwork-occupancy check — `transitions.py:151-174`

Verified against code, not tests. Every item on the generator's candidate list was confirmed in the source before pinning; the walk additionally surfaced the unfiltered top-level respondent listings, band-3/4 vs band-5 ordering, the re-materialisation of a sample plan on a second accepted data call, the per-review area `version` bump, the cap-rejection/prior-draft interaction, and the missing occupancy check on the follow-up examination.

## Step 7 final verdict (orchestrator) — 2026-09-02T09:22:14.000Z

Cross-round analysis of the eight captured `results.{1..8}.json`:

```
rounds captured:                        8
distinct tests seen:                    202
tests that passed in >=1 round:         202
tests that NEVER passed in any round:   0
non-infrastructure (assertion) failures: 0
```

Every one of the 202 tests is demonstrably green against the delivered `implementation/` under `--isolation per-test-server`. No test failed for any reason attributable to `test_suite/`, `test_helpers/`, or `implementation/`.

The literal "all 8 rounds at 202/202 simultaneously" gate was not reachable on this host. A further retry sweep launched at 09:00 had all eight of its runners killed before any wrote a results file (exit 144) — the same external SIGTERM behaviour the Step 7 subagent documented. Host state at that point: load average 205 on 32 cores, **252** concurrent sibling `prd-bench-local-run` processes belonging to other pipelines. Conditions degraded over the session (206 → 252 sibling runners) rather than improving, so further sweeps were abandoned as unproductive rather than continued indefinitely.

The two failure modes are both outside this task's artifacts and neither is fixable from them:
1. `prd_bench_local_runner/pytest_plugin.py:46` — `_kill_port()` runs `lsof` with `timeout=5` and does not catch `subprocess.TimeoutExpired`, so under host contention the exception escapes `pytest_runtest_setup` and the test is booked as a setup error without ever running. (`port_utils.kill_port` catches it; the plugin copy does not.) This is a runner bug, reported here rather than patched — editing the shared runner would affect every concurrent pipeline on this box.
2. A host-wide external SIGTERM sweep killing servers (and whole runners) mid-test, evidenced by simultaneous kills across independent ports and on an out-of-range canary port.

No workaround was applied to `implementation/`, `test_suite/`, or `test_helpers/` to accommodate either, since any such change would be an untraceable capability addition and could corrupt a real grading run.

Final artifact state: `workspace/PRD.md`, `workspace/PRD_FINALIZED.md`, `workspace/PRD_COMPLETED.md`, `workspace/INSTRUCTION.md`, `workspace/implementation/` (deliverable + `results.{1..8}.json`), `test_helpers/` (9 modules), `test_suite/` (conftest + 15 test files, 202 tests). Scratch (`canary.log`, `__pycache__`) removed.
