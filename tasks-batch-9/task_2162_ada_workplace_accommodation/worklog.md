# Worklog — task_2162_ada_workplace_accommodation

## Step 1: Create task directory — 2026-08-28T09:24:34.000Z

Created `tasks/task_2162_ada_workplace_accommodation/` and `tasks/task_2162_ada_workplace_accommodation/workspace/` (next index derived from highest existing `task_2161_*`).

## Step 3: Copy shared files — 2026-08-28T09:25:01.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2162_ada_workplace_accommodation/workspace/INSTRUCTION.md`. (Run early — no dependency on Step 2.)

## Step 2: Generate scaffold — 2026-08-28T10:30:24.000Z

All three artifacts are written and pass the skill's lint cleanly.

**Files** (in `/home/ubuntu/github/CodingPRD/tasks/task_2162_ada_workplace_accommodation/`):
- `SCAFFOLD.yaml` (3,135 lines) — §1.0–§1.7, no design keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2,315 lines) — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (3,735 lines) — single key `scaffold_corner_design`

**Profile**: multi-party negotiation × compliance/audit; graph topology; cyclic state shape with a parallel dimension; segregation-of-duties roles; immediate consistency. Layers: optimistic concurrency, cascading side effects, dual-variant calculation, scheduled/deferred actions. `api_prefix: "/"` (flat top-level collections — required for lint check (f) segment derivation).

**Entities (14)**: Employee, JobProfile, EssentialFunction, AccommodationRequest, MedicalDocumentationRequest, FunctionAnalysis, AccommodationOption, UndueHardshipAssessment, TrialPeriod, EffectivenessReview, DenialRecord, Appeal, AbsenceRecord (polymorphic leave/workers'-comp), MedicalDisclosure (append-only).

**State machines (8 machines, 72 transitions)**: `AccommodationRequest.stage` (28 transitions, cyclic — four distinct re-entries into OPTION_EXPLORATION), `AccommodationRequest.confidentiality_posture` (parallel dimension, 4), `MedicalDocumentationRequest.status` (6), `AccommodationOption.status` (10, branching fork with divergent counters + revision cycle), `TrialPeriod.status` (7, extension cycle), `Appeal.status` (8, supplement cycle + seal-stay), `DenialRecord.status` (4), `AbsenceRecord.status` (6).

**Counts**: 13 calculations, 38 validations (strict priority ladder 10→81), 53 endpoints, 54 error codes, 7 roles, 3 OCC concurrency rules (all three write endpoints take `expected_*_version` and bump the parent version).

**Design indices**: §1.8 = **21 instances** across all 9 rules (2/2/2/2/3/3/3/2/2). §1.9 = **61 instances** (54 with full recipes + 7 `excluded_because` stubs) across entities 11, state_machines 9, calculations 6, validations 5, endpoints 3, errors 14, rbac 7, cross-cutting layers 5, consistency_model 1.

**Verification performed**:
- `scaffold_lint.py` verdict, verbatim: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (53 endpoints, 14 entities, 21 §1.8 + 54 §1.9 instances, 1040 calls scanned)
- Custom checks: zero unbound `${var}` across 1040 calls and all assert lines; 82 unique instance names; every `grounds` ref resolves (calculations, 72 declared transitions, validation priorities, entity fields, errors, roles, endpoints, concurrency rule ids); all 54 error codes appear in a design file; all 7 stub `difficulty_instance` refs resolve; no forbidden concurrency vocabulary; computed-enum closure audited (removed dead `JobProfile.RETIRED`, added an EF-retirement cascade producing `FunctionAnalysis.SUPERSEDED`).
- Every formula-derived assert literal was computed in Python against the declared formulas/constants, e.g. hardship 78.38 (SITE_LOCAL) vs 17.74 (EMPLOYER_WIDE) on identical inputs; exactly 70.00 → UNDUE vs 69.99 → BORDERLINE from an 11-cent input delta; per-component rounding 150636 vs the forbidden 150637; pre-credit tier 62.70 vs the wrong re-tier 59.40; trial 7.10 (LATEST_WEIGHTED) vs 6.33 (CUMULATIVE_MEAN); renormalised 2-review 5.25.

## Step 4: Generate PRD — 2026-08-28T10:42:43.000Z

PRD generated and verified.

**Output:** `workspace/PRD.md` — **517 lines**, written incrementally in six append passes (no one-shot Write).

**Section list**
- 1. Introduction (3 paragraphs)
- 2. Global Specifications & System-Wide Principles — 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 Resource Identity, Timestamps and Version Semantics · 2.5 The Logical Clock and Deferred Operations · 2.6 Rejection Ordering: How the Server Chooses an Error · 2.7 Optimistic Concurrency on Contested Records · 2.8 Nested Path Resolution and Reverse Lookups · 2.9 Money, Weights, Ratios and Rounding · 2.10 Confidentiality as a Parallel Dimension · 2.11 The Committed-Cost Ledger and Its Zero-Drift Rule
- 3. Business Logic & Workflows — 3.1 Job Architecture: Profiles, Duties and Publication · 3.2 Workforce Records: Employees, Leave and Workers' Compensation · 3.3 Intake and the Bounded Medical Documentation Budget · 3.4 Essential-Function Analysis with the Manager · 3.5 Option Exploration, Costing and Coverage · 3.6 Undue Hardship and the Clearing Fork · 3.7 The Decision, the Trial Period and Effectiveness Review · 3.8 Denial, Appeal and Remand · 3.9 Renewal Cadence, Disclosure Logging and the Integrity Score
- 4. Endpoint Definitions (4-column table)
- 5. Error Code Catalogue (2-column table)

**Requested verification counts (scripted against SCAFFOLD.yaml)**
- Error codes: **54 / 54** present, and all 54 are also mentioned in §1–§4 narrative (not only in the §5 table)
- Endpoints: **53 / 53** present as exact `| METHOD | \`path\` |` rows in §4
- Calculations: **13 / 13** expressed in prose (`option_net_cost`, `essential_function_coverage`, `undue_hardship_assessment`, `trial_effectiveness`, `documentation_budget`, `interactive_process_integrity`, `disclosure_authorization`, `renewal_cadence`, `committed_cost_ledger`, `trial_window_conflict`, `doc_window_conflict`, `intermittent_capacity`, `daily_sweep_order`)
- All 40 numeric/named constants present as values embedded in business context; all state enumeration values, all `type: enum` member values, and all 7 role names present verbatim in backticks

**Hard Contract reports**

```
Field coverage check:
- entities[].fields: 126 required, 126 present, 0 missing
- endpoints[].request_body: 75 required, 75 present, 0 missing
- endpoints[].query_params: 19 required, 19 present, 0 missing
- endpoints[].path_params: 1 required, 1 present, 0 missing
(strict exact-backtick match, no token splitting: 0 missing of 137 deduped names)
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 38 checked, 38 expressed in prose (§2.6 states the full 38-step ordering), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_request_version / expected_option_version + ERR_STALE_VERSION + 412 all named), 0 missing
- state_machines[].transitions: 73 checked across 8 machines, 73 fully expressed, 0 missing
- calculations[]: 13 checked, 13 fully expressed, 0 missing
- validations[] conditions: 38 checked, 38 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 53 checked, 53 expressed, 0 missing
- entities[].fields[] structured content: 14 entities / 126 fields checked, 126 reconstructible from prose, 0 missing
- sibling-branch symmetry: 7 groups checked (GRANT_WITH_TRIAL vs GRANT_PERMANENT, hardship fork Branch A vs B, SITE_LOCAL vs EMPLOYER_WIDE, CUMULATIVE_MEAN vs LATEST_WEIGHTED, 4 trial resolve outcomes, 4 appeal decide outcomes, 4 renewal-review outcomes), 7 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 987
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Notes on tricky content deliberately pinned in prose:** the per-component-then-sum rounding order for `option_net_cost_cents`; the mitigation tier read from the *pre-credit* `raw_hardship_score` (including the non-monotonic 0.00/0.10/0.05/0.00 band shape); the renormalised recency weights for `LATEST_WEIGHTED` when fewer than three reviews exist; the closed-interval-plus-7-day-washout trial rule (earliest legal start = prior end + 8 days) versus the half-open zero-buffer documentation window; the two depth-5 transitive cascades (ineffective trial, appeal remand); the confidentiality seal cascade staying `UNDER_REVIEW` appeals; the zero-drift ledger release rule; and the sweep's 8-phase order with "phases never re-run within one sweep".

`SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced.

**Orchestrator verification:** `wc -l` = 517; file ends mid-§5 error table at `ERR_OPEN_CASE_LIMIT` (last catalogue row) — all five sections present, no truncation.

## Step 6: Generate implementation — 2026-08-28T11:08:09.000Z

*(Launched concurrently with Step 5; completed first, so it is recorded first. `test_suite/` did not exist when this agent started, giving physical read-isolation from the tests.)*

All servers I launched are stopped (no listeners remain on my ports; the remaining `python3 app.py` PIDs belong to other concurrent work and were left untouched).

**Files written** — `workspace/implementation/` (3,024 lines total)

| File | Lines | Contents |
|---|---|---|
| `start.sh` | 8 | Guarded `pip install` + `exec python3 app.py`, `0.0.0.0:$PORT` (default 10000) |
| `requirements.txt` | 1 | Flask |
| `app.py` | 86 | Blueprint wiring, global request lock, error handlers |
| `store.py` | 131 | In-memory dicts (14 collections), logical clock (default `2026-08-01T00:00:00Z`), ISO parsing |
| `errors.py` | 80 | All 54 error IDs → HTTP status |
| `envelope.py` | 136 | `meta`/`response_type`/`data` envelope, `limit`/`offset`/`total_count`/`has_more`, dirty-row version tracker |
| `validation.py` | 136 | Body well-formedness (ladder step 5) |
| `authz.py` | 150 | Ladder steps 1–4, 6/7 lookups, 8 (case owner), 9 (manager scope), 12 (seal) |
| `calc.py` | 287 | All 13 calculations, Decimal + ROUND_HALF_UP, all pinned constants |
| `domain.py` | 292 | Roll-ups, committed-cost ledger, seal cascade, withdrawal cascade, 8-phase daily sweep |
| `r_workforce.py` | 328 | Employees, job profiles, essential functions, absence records |
| `r_cases.py` | 480 | Intake, stage machine, decide, renewal review, confidentiality, disclosure log |
| `r_docs.py` | 234 | Documentation rounds + function analyses |
| `r_options.py` | 202 | Options + undue-hardship assessments |
| `r_trials.py` | 229 | Trials, effectiveness check-ins, resolve |
| `r_appeals.py` | 219 | Denials, appeals, segregation of duties |
| `r_ops.py` | 25 | Logical clock, daily sweep |

**Endpoints implemented: 53** (matches the PRD §4 table exactly).

**Boot check: PASS.** `PORT=18799 bash start.sh` came up in <4s; `GET /employees` as `ComplianceAuditor` returned `200` with a well-formed envelope and `data: []` / `total_count: 0` (confirming zero seeded state), and an unauthenticated request returned `401 ERR_UNAUTHENTICATED` in the error envelope. Storage is purely in-process dicts — no file, no SQLite, no cache.

**Verification beyond boot** — five end-to-end scenario scripts (~350 assertions) all pass, covering: full happy path (intake → docs → analysis → options → hardship → grant → trial → renewal), the rejection ladder (401/403/400/404/409/412/422 precedence including body-before-path), OCC on all three guarded writes, the 5-hop INEFFECTIVE and REMAND cascades, the seal cascade staying an UNDER_REVIEW appeal, `ERR_APPEAL_MUST_REMAND`, ledger zero-drift, the doc-window exclusive endpoint, the trial washout boundary (+7 collides, +8 legal), intermittent-capacity aggregation, and the sweep's phase ordering. Spot-checked numerics matched hand computation exactly (net cost `74000+17760`, `SITE_LOCAL` saturation → raw 80.00 → tier 0.05 → 76.00 UNDUE vs `EMPLOYER_WIDE` 8.83 NOT_UNDUE on the same shape; `LATEST_WEIGHTED` 7.60 vs `CUMULATIVE_MEAN` 4.00).

**Two interpretive calls worth flagging** (PRD is ambiguous; both are defensible and documented in code):
1. `created_at`/`updated_at` read the **logical clock**, not wall time — §2.5's "nothing reads the host wall clock" plus §2.4's example literal `2026-08-01T00:00:00.000Z` (the clock's startup default). `meta.api_request_timestamp` uses real time.
2. Manager department scope on the two *profile*-scoped operations (author/revise a duty) compares against `JobProfile.department_code`, since no case exists on those paths.

**Orchestrator verification:** `ls workspace/implementation/` shows only the 17 declared files (+ `__pycache__`) — no leftover scenario scripts, no seeded data file, no SQLite/JSON persistence artifact.

## Step 5: Generate unit tests — 2026-08-28T11:20:06.000Z

*(Launched concurrently with Step 6; completed second.)*

Test infrastructure complete for `/home/ubuntu/github/CodingPRD/tasks/task_2162_ada_workplace_accommodation/`.

## Files written

**test_helpers/** (2,355 lines)
| file | lines |
|---|---|
| `types.py` | 491 |
| `fixtures.py` | 686 |
| `assertions.py` | 359 |
| `api_client.py` | 287 (53 endpoint methods) |
| `factories.py` | 177 |
| `api_errors.py` | 122 (54 errors + status map) |
| `constants.py` | 98 |
| `test_users.py` | 84 |
| `__init__.py` | 51 |

**test_suite/** (4,563 lines, 96 tests, 12 modules + conftest)
`conftest.py` 54 · `test_01_job_architecture.py` 417 · `test_02_intake_and_case_opening.py` 250 · `test_03_medical_documentation.py` 474 · `test_04_function_analysis.py` 150 · `test_05_option_costing.py` 185 · `test_06_undue_hardship.py` 532 · `test_07_exploration_and_decision.py` 462 · `test_08_trial_period.py` 593 · `test_09_denial_and_appeal.py` 480 · `test_10_confidentiality_and_renewal.py` 500 · `test_11_access_control.py` 251 · `test_12_concurrency_and_sweep.py` 215

All files were written incrementally (create + append), never one-shot.

## Coverage

- **Queue A (Difficulty):** 21/21 instances × exactly 2 tests = **42 tests**. Zero shortfalls.
- **Queue B (Corner):** 54/54 non-stub instances × 1 test = **54 tests**. Zero shortfalls.
- **7 `excluded_because` stubs** not translated; all 7 `difficulty_instance` cross-references verified to resolve to real §1.8 instances.
- **Instances skipped: none.** Every non-stub instance passed the PRD-first two-condition filter.
- No `skip`/`skipif`/`xfail` anywhere; no freelance tests (every tag resolves to a real instance, no unknown tags, no dual tags).

## Two assertion-level deviations (PRD beats the design index)

1. `Corner/calculations/corner_coverage_ratio_excludes_marginal_functions_from_both_terms` — the recipe's second assertion (naming a marginal duty in `coverage_function_ids` returns `ERR_FUNCTION_NOT_IN_PINNED_PROFILE` on option creation) **fails unique derivability**: PRD §3.5 says the opposite — *"an id listed in `coverage_function_ids` that falls outside the filtered denominator set contributes nothing at all"* — and the §2.6 rung-18 wording covers only "belong to the pinned profile and are live", which a marginal ACTIVE duty satisfies. The rejection assertion is omitted; the instance's headline claim (coverage excludes marginal weight from both terms) is fully asserted.
2. Same instance asserts `essential_function_count == 1`; PRD §3.1 states it counts *"duties on the profile whose `status` is `ACTIVE`, regardless of whether they are essential or marginal"*, so the test asserts **2**. (SCAFFOLD.yaml agrees with the PRD — this is a corner-design bug.)

## Verification performed

- **C1 literal-grep pass:** all **242** docstring quotations survive a literal grep of PRD.md modulo whitespace (em dashes, arrows and bold markers preserved verbatim).
- **C4 tag pass:** every test docstring ends with exactly one well-formed `Design:` line.
- `pyflakes` clean (no undefined names, no unused imports in generated code).
- `pytest --collect-only` → **96 tests collected**, no import or collection errors.
- **Ladder discipline:** every negative fixture was checked against the 38-rung §2.6 order so the intended rung fires — e.g. scope (14) before budget (19) before window (26) on doc rounds; state (10) before appeal-window (25) on re-filing; coverage (16) before hardship-block (31) on grants; OCC (11) before window (26) on stale doc rounds; reviews (35) before outcome-mismatch (36) on trial resolution.
- All literal expected values were independently recomputed from the PRD formulas (net cost 150636 vs the forbidden 150637; hardship 78.38 / 17.74 / 70.00 / 69.99 / 66.00→62.70 / 34.57 / 21.74; effectiveness 7.10 / 6.33 / 5.25; cadences 365 / 90; deadlines 2026-09-02 / 2026-09-16; renewal 2028-08-02).

## Step 7: Run tests and iterate — 2026-08-28T11:26:56.000Z

Clean 8-round sweep achieved.

**Iterations run:** 2

**Iteration 1 result:** 95/96 in all 8 rounds — one deterministic failure, no flakiness anywhere in the suite.

- `test_02_intake_and_case_opening.py::test_every_case_mutation_moves_the_version_by_exactly_one`
- Failure detail (identical in all 8 rounds): `AssertionError: assert '2026-08-03T09:00:00.000Z' > '2026-08-03T09:00:00.000Z'` — tripped on `assert patched["updated_at"] > patched["created_at"]`.

**Iteration 2 result:** 96/96 in all 8 parallel rounds.

**Tests deleted:** none (no whole test failed STEP 1).

**Assertions removed under STEP 1c (partial coverage split):**
- `test_suite/test_02_intake_and_case_opening.py:193` — removed `assert patched["updated_at"] > patched["created_at"]`. **Category: DEFAULT/COMPUTED-FIELD SILENCE on the timestamp source.** STEP 1a: grepping PRD.md for `updated_at` returns exactly three sentences (all in §2.4), none of which relates `updated_at` to `created_at` ordering — the strongest is *"Most resources additionally carry `updated_at` — same format, refreshed on every mutation of that row"*. STEP 1b two-reader experiment: §2.5 states *"Nothing in this service reads the host machine's wall clock"*, and §2.4's own example literal is `2026-08-01T00:00:00.000Z`, the clock's startup default — so Reader A stamps `created_at`/`updated_at` from the logical clock and, with the clock frozen at one instant across the mutation, "refreshing" writes the identical value (`updated_at == created_at`); Reader B reads §2.5's enumerated list (`issued_at`/`responded_at`/`filed_at`/`review_date`) as exhaustive and stamps row-lifecycle timestamps from wall time (`updated_at > created_at`). Both are PRD-faithful, so the ordering assertion is not uniquely derivable. Scaffold rule that drove it: `Corner/cross_cutting_complexity_layers/corner_version_increments_on_every_case_mutation`.
- The test's covered assertions were all retained: `version == 1` on create, `== 2` after the coordinator's PATCH, `== 3` after the OCC-guarded doc-round issue, plus `requested_accommodation_text` and `stage == "DOC_PENDING"`. The test still fails if the implementation gets version accounting wrong.

**Fixes applied to `test_helpers/`:** none — no fixture, factory, or role-header helper constructed a precondition inconsistent with the PRD.

**Fixes applied to `implementation/`:** none. The implementation's logical-clock stamping in `workspace/implementation/store.py::Store.new_row` (`row["created_at"] = self.now_iso()`, `row["updated_at"] = row["created_at"]`) is the PRD-faithful reading of §2.5's categorical no-wall-clock rule, so weakening it to satisfy the test would have violated the cardinal rule against removing a PRD-required behavior.

**Note on flakiness:** the 8-round sweep surfaced zero timing-sensitive behavior — the same single test failed in all 8 rounds of iteration 1 with byte-identical error text, and all 96 tests passed in all 8 rounds of iteration 2. The concurrency/OCC tests (`test_12_concurrency_and_sweep.py`) and the sweep phase-ordering tests were stable across all 16 round-executions.

Left the tree clean: `results.*.json` and `__pycache__` removed; `workspace/implementation/` holds only its 17 declared files, storage remains in-memory dicts with no seeded data.

**Orchestrator note:** Step 7 removed the `results.{1..8}.json` artifacts the pipeline output spec declares. A final confirming 8-round sweep is run alongside Step 8 to regenerate them and re-verify green on the final tree.

## Step 8: Finalize PRD — 2026-08-28T11:29:23.000Z

`PRD_FINALIZED.md` is written.

## Line counts
- `PRD.md`: 517 lines — `PRD_FINALIZED.md`: 517 lines — **0% line delta** (3 lines revised in place, 0 added/removed; +473 characters, ~0.47% by size).

## Changes
- **§2.4 (line 94) — revise** — `created_at` is now explicitly stamped *from the logical clock of §2.5* rather than an unspecified source — `implementation/store.py:114`
- **§2.4 (line 96) — revise** — `updated_at` is refreshed *from that same logical clock* on every mutation — `implementation/store.py:116`, `implementation/envelope.py:47-52`
- **§2.4 (line 98) — insert** — one sentence appended to the cascade paragraph pinning the consequence: with the clock frozen, `updated_at == created_at` after a mutation even though `version` moves; they differ only if the clock was moved in between — `implementation/store.py:114-116`, `implementation/envelope.py:47-55`

All three edits address the single Step 7 item (the removed `assert patched["updated_at"] > patched["created_at"]`, categorized as DEFAULT/COMPUTED-FIELD SILENCE on the timestamp source). They are one logical edit split across the two sentences that describe the two stamps plus the sentence that states the observable consequence.

## Pre-edit search log

**Edit 1+2+3 (single subject, searched once as a unit)**

(a) **Subject identified:** the source of the `created_at` / `updated_at` row-lifecycle stamps, and the resulting ordering relationship between them.

(b) **Impl paths enumerated (read/grepped):**
- `grep -rn "updated_at\|created_at\|now_iso\|now()\|today()"` across all of `implementation/` — the complete write-site set is exactly three lines: `store.py:114` (`created_at = self.now_iso()`), `store.py:116` (`updated_at = row["created_at"]`), `envelope.py:52` (`updated_at = stamp`, where `stamp = store.now_iso()` at `envelope.py:47`). No other file writes either field.
- `store.py:88-118` — `Store.now/now_iso/today/set_clock`, `LOGICAL_CLOCK_DEFAULT = 2026-08-01T00:00:00Z`, and `new_row` (client-supplied fields are applied *before* the stamps, so a client `created_at` can never win).
- `envelope.py:31-55` — `touch`/`flush_dirty`: the single mutation-stamp path; skips `JOURNAL_KINDS` and rows without `version`, so `EffectivenessReview`/`MedicalDisclosure` keep `created_at` only (matches the untouched exception sentence).
- All 32 `touch(...)` callsites across `r_appeals.py`, `r_docs.py`, `r_workforce.py`, `r_cases.py`, `r_trials.py`, `r_options.py`, plus the cascade/sweep path `domain.py:19,244-282` — every one funnels into `flush_dirty`, including sweep-driven cascades Step 7 never exercised.
- Off-site clock consumers checked for contradiction: `r_docs.py:29,61,98,103`, `r_cases.py:332,342,384`, `r_appeals.py:61,67`, `r_trials.py:130`, `calc.py:233,280`, `domain.py:216-217,284`, `r_ops.py:18` — all read the same clock; §2.5 already covers them, so nothing needed re-wording.
- `r_ops.py:14-18` — `set_current_utc` has no monotonicity guard, so the clock may move backward.
- `store.py:130-131` (`by_created`, stable sort) and `calc.py:166` (`(review_date, created_at)` sort) — ties are broken by insertion order.

(c) **Wording adjustments made to keep all enumerated paths consistent:**
- Wrote "refreshed **from that same logical clock**" instead of naming a specific stamping site, so it covers `envelope.py:52` *and* every cascade/sweep caller uniformly, and the pre-existing journal-entry exception sentence stays true untouched.
- Deliberately phrased the consequence conditionally ("**while the clock still reads the creation instant**") rather than as a flat `updated_at == created_at` universal, which would be false after any `set_current_utc`.
- Used "`updated_at` **differs from** `created_at` only when the clock has been moved in between" rather than "is later than", because `set_clock` accepts backward moves and can produce `updated_at < created_at`.
- Left tie-breaking for `created_at`-ascending list ordering (`store.py:131`, `calc.py:166`) **un-pinned** — a frozen clock makes ties common, but that is outside the Step 7 item and the existing §2.2/§2.5 prose is not contradicted by the new sentence. Under-determined by design; Step 9 can pin it if warranted.
- Left §2.5's enumerated stamp list (`issued_at`/`responded_at`/`filed_at`/`review_date`) verbatim — the §2.4 edit assigns the source specifically and does not require re-opening that list.

## Orchestrator verification: confirming 8-round sweep — 2026-08-28T11:29:56.000Z

Independent re-run of the full 8-round parallel sweep by the orchestrator (not the Step 7 fix agent), against the final tree, to regenerate the `results.{1..8}.json` deliverables Step 7 had cleaned up:

```
round 1: passed=96 total=96
round 2: passed=96 total=96
round 3: passed=96 total=96
round 4: passed=96 total=96
round 5: passed=96 total=96
round 6: passed=96 total=96
round 7: passed=96 total=96
round 8: passed=96 total=96
```

All 8 rounds green under `--isolation per-test-server`. Confirms Step 7's exit condition on the final artifact state.

## Step 9: Complete PRD — 2026-08-28T11:39:39.000Z

All 33 patches are in place and verification passes.

**Files** — `PRD_FINALIZED.md` 517 lines / 100,352 chars → `PRD_COMPLETED.md` 517 lines / 108,453 chars (**+8,101 chars, 0 lines**; every patch is an in-paragraph insert or revision, no new sections, no new paragraphs).

**Counts** — 33 changes total: **28 ambiguity-pins**, **5 mismatch-revisions**.

### Changes

- **§2.1** — insert — ambiguity — an empty (present-but-blank) `X-User-ID` is treated as absent → `ERR_UNAUTHENTICATED` — `authz.py:30`
- **§2.3** — insert — ambiguity — pagination bounds are validated before the parent path id of a nested listing resolves — `envelope.py:100-114`, all list views
- **§2.3** — insert — ambiguity — **`created_at` ties broken by insertion order** (frozen clock makes ties the common case) — `store.py:129-131`
- **§2.3** — insert — ambiguity — filter values are never validated; unparseable boolean filters and unknown query params are ignored, not rejected — `envelope.py:127-136`
- **§2.4** — insert — ambiguity — the primary target row always advances `version`/`updated_at` even on a no-op write, while cascade-reached rows move only on real change — `envelope.py:31-54`, `domain.py:11-20`
- **§2.5** — revise — mismatch — "nothing reads the host wall clock" carved out for the envelope's `api_request_timestamp`, which *is* wall-clock — `envelope.py:18-20`
- **§2.5** — insert — ambiguity — **`set_current_utc` has no monotonicity guard**; a backward instant is accepted — `r_ops.py:13-18`
- **§2.6 rung 5** — insert — ambiguity — cross-field/conditional body constraints (length bounds, date ordering, `due_date` > issuance, decision-conditional requiredness) live at rung 5, ahead of all id resolution — `r_docs.py:29-33`, `r_trials.py:33-36`, `r_workforce.py:35-36,241-244`, `r_cases.py:259-267`
- **§2.6 rung 9** — revise — mismatch — **manager scope on the two profile-scoped duty ops compares against `JobProfile.department_code`** (no case exists there) — `r_workforce.py:153,198`
- **§3.1** — insert — ambiguity — duty revision has no `DRAFT` precondition; it stays available on a `PUBLISHED` profile — `r_workforce.py:192-219`
- **§3.3** — revise — mismatch — case amendment has *no* stage precondition (works on `CLOSED`/`WITHDRAWN`/`DENIED_FINAL`), only the seal blocks it — `r_cases.py:113-129`
- **§3.3** — insert — ambiguity — issuing a round is declared only from `INTAKE`/`DOC_PENDING`; otherwise `ERR_INVALID_STAGE_TRANSITION`, evaluated ahead of OCC/seal/scope/permission/budget — `r_docs.py:34-36`
- **§3.3** — insert — ambiguity — a response after the window closes → `ERR_DOC_REQUEST_NOT_OPEN` — `r_docs.py:98`
- **§3.3** — insert — ambiguity — unmet stage-specific preconditions (obvious-disability skip, no sufficient round, DOC_PENDING deny conditions, HARDSHIP_REVIEW→OPTION_EXPLORATION re-entry) all draw `ERR_INVALID_STAGE_TRANSITION` — `r_cases.py:169-201,295-308`
- **§3.3** — insert — ambiguity — Employee naming a non-`WITHDRAWN` target, and a coordinator naming `WITHDRAWN`, → `ERR_INVALID_STAGE_TRANSITION` — `r_cases.py:160-167`
- **§3.4** — insert — ambiguity — recording an analysis has no stage precondition — `r_docs.py:161-189`
- **§3.4** — insert — ambiguity — off-role fields on an amendment are silently ignored; no analysis-status precondition; version advances regardless — `r_docs.py:225-233`
- **§3.5** — revise — mismatch — at propose/revise time every `coverage_function_ids` member must be `ACTIVE` + `is_essential` + on the pinned profile (`ERR_FUNCTION_NOT_IN_PINNED_PROFILE`); the "contributes nothing" tolerance only covers later retirement, which is why §3.6's re-check omits `is_essential` — `r_options.py:28-36,51,155-156`
- **§3.5** — insert — ambiguity — option revision permitted only from `PROPOSED` or `HARDSHIP_BLOCKED` — `r_options.py:111-114`
- **§3.7** — insert — ambiguity — a foreign-case or wrong-status `selected_option_id` → `ERR_INVALID_STAGE_TRANSITION`, never the two 422 codes — `r_cases.py:281-283`
- **§3.7** — insert — ambiguity — a bad `alternative_option_id` → `ERR_INVALID_STAGE_TRANSITION` — `r_cases.py:303-306`
- **§3.7** — insert — ambiguity — `rejected_option_ids` ordered `created_at` ascending — `r_cases.py:333-334`
- **§3.7** — insert — ambiguity — `/decide` answers 200 with the `AccommodationRequest`, never the new denial record — `r_cases.py:292,311`
- **§3.7** — insert — ambiguity — trial-schedule stage/option guard failures → `ERR_INVALID_STAGE_TRANSITION`, before the three deconfliction rules — `r_trials.py:39-42`
- **§3.7** — insert — ambiguity — trial/absence overlap test: `start < absence.end_date` (exclusive) **and** `end >= absence.start_date` (inclusive) — `r_trials.py:62`
- **§3.7** — insert — ambiguity — a check-in on a trial outside `ACTIVE`/`UNDER_REVIEW` → `ERR_TRIAL_NOT_RESOLVABLE` — `r_trials.py:121-123`
- **§3.8** — insert — ambiguity — each appeal action is bound to one role; the other permitted role draws `ERR_APPEAL_NOT_ACTIONABLE` — `r_appeals.py:110-118`
- **§3.8** — insert — ambiguity — wrong status, non-stamped officer, and an unusable `REVERSE` alternative all → `ERR_APPEAL_NOT_ACTIONABLE`; `DISMISS` is not officer-bound — `r_appeals.py:151-160`
- **§3.9** — insert — ambiguity — renewal review requires `RENEWAL_DUE` (`ERR_INVALID_STAGE_TRANSITION`, ahead of OCC); seal blocks all four outcomes; all four return 200 with the predecessor case — `r_cases.py:365-369,402`
- **§3.9** — revise — mismatch — `CONTINUE`'s "additionally requires not sealed" reworded, since the seal applies to all four — `r_cases.py:369`
- **§3.9** — insert — ambiguity — successor copies `request_channel`/`requested_accommodation_text`/`disability_obvious`/`absence_record_id`, re-pins the employee's current profile when `PUBLISHED` else falls back to the predecessor's, and never raises `ERR_PROFILE_NOT_PUBLISHED` — `r_cases.py:405-436`
- **§3.9** — revise — mismatch — integrity is recomputed on disclosure append **only for an unauthorized row** (it rides the seal cascade) — `r_cases.py:466-467`, `domain.py:158-161`
- **§3.9** — insert — ambiguity — unsealing a case that is not `SEALED` → `ERR_INVALID_STAGE_TRANSITION` — `r_cases.py:138-139`

### End-of-run verification
- Error codes in §5: **54 rows / 54 distinct** ✅
- Endpoint rows in §4: **53** ✅
- Top-level sections: **5** (`## 1.`–`## 5.`) ✅
- Line count unchanged at 517 (no structural edits) ✅
