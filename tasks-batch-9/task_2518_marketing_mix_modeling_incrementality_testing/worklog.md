# Worklog — task_2518_marketing_mix_modeling_incrementality_testing

## Step 1: Create task directory — 2026-09-03T04:24:57.611Z

Created `tasks/task_2518_marketing_mix_modeling_incrementality_testing/` and `tasks/task_2518_marketing_mix_modeling_incrementality_testing/workspace/`. Index pre-assigned by the orchestration prompt (2518); no scan of ./tasks/ performed, per instruction that concurrent pipelines share this host.

## Step 2: Generate scaffold — 2026-09-03T06:13:01.799Z

All three scaffold artifacts are complete and the linter is clean on the first pass.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2518_marketing_mix_modeling_incrementality_testing/`)

| file | lines | bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 3263 | 164 KB |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2374 | 189 KB |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 6804 | 519 KB |

All three parse under `yaml.safe_load`. `SCAFFOLD.yaml` contains neither design key; the two design files each have exactly one top-level key (`scaffold_difficulty_design`, `scaffold_corner_design`).

**SCAFFOLD.yaml contents** — `domain_name: marketing-mix-incrementality`, `api_prefix: /mmm`; 13 entities, 6 state machines, 2 concurrency rules, 14 calculations, 47 validations, 57 endpoints, 61 errors, 6 roles. Complexity profile: Ledger reconciliation + Temporal windowing, flat topology, parallel state-machine shape, `segregation_of_duties` role model, `immediate` consistency, layers = dual_variant_calculation / cascading_side_effects / optimistic_concurrency / derived_field_reconciliation.

**§1.8 difficulty design** — 9 rules × 2 instances = 18 instances (`dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`).

**§1.9 corner design** — 9 sections, 89 instances (63 full recipes + 26 `excluded_because` stubs, none of which carries a `test_recipe`): entities 11, state_machines 17, calculations 14, validations 11, endpoints 6, errors 17, rbac 7, complexity_layers 5, consistency_model 1. Every stub's `difficulty_instance` citation resolves to a real §1.8 instance name, and all 107 names are unique across the union of both files.

**Verdict block (verbatim):**

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2518_marketing_mix_modeling_incrementality_testing/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2518_marketing_mix_modeling_incrementality_testing/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2518_marketing_mix_modeling_incrementality_testing/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    57
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     63
  Calls scanned (§1.8+§1.9):  1519

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Notes worth relaying: the scaffold was generated purely from the scenario text plus the generator skill (no sibling task was read, listed, or grepped). During the final section pass I caught and corrected five field-name drifts against §1.1 (`decided_by_user_id` not `accepted_by_user_id`, `allocated_cents`/`allocated_total_cents` not `optimized_*`, `variance_lines` instead of a non-existent `line_count`, `is_restatement`/`superseded_by_id` instead of `is_current` on SpendObservation) and one counter error (`spend_observation_count` stays flat on a restatement because it counts only non-superseded rows). The pre-existing `worklog.md` and empty `workspace/` in the task directory were created by the pipeline's step 1 and were left untouched.

## Step 3: Copy shared files — 2026-09-03T06:13:17.428Z

Copied `./INSTRUCTION.md` to `tasks/task_2518_marketing_mix_modeling_incrementality_testing/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T06:30:04.349Z

PRD.md for task 2518 is complete and verified.

**Output:** `workspace/PRD.md` — **493 lines, 108,095 bytes**. Built entirely with chunked `cat >>` appends; no truncation. Document ends at a completed section boundary (final row of the §5 error table).

**Section outline**
```
# Marketing Mix Incrementality API — Product Requirements Document
## 1. Introduction
## 2. Global Specifications & System-Wide Principles
  2.1 User and Role-Based Access Control
  2.2 API Response Structure (verbatim block: Standard Success / Standard Error Response Format)
  2.3 Pagination and Deterministic List Ordering
  2.4 Resource Identity, Timestamps and Versioning
  2.5 Nested Path Resolution and Body-Level Referential Integrity
  2.6 Decimal Discipline and Rounding
  2.7 Optimistic Concurrency on Contended Aggregates
  2.8 Market Data Posture
  2.9 The Logical Clock
  2.10 Cascading Invalidation, Recomputation and Conservation
  2.11 Separation of Duties
  2.12 Validation Precedence
## 3. Business Logic & Workflows
  3.1 Market Foundations, Media Channels and the Geographic Cell Pool
  3.2 Assembling a Training Window: Observations, Restatements and Completeness
  3.3 Sealing, Reopening, and the Four-Hop Staleness Cascade
  3.4 Specifying and Fitting a Model Run (Adstock / Saturation, contribution and the baseline identity / ROI and the confidence interval)
  3.5 Holdout Validation, Publication and Refresh Cadence
  3.6 The Incrementality Experiment Lifecycle (Locking the design / Enlisting cells and going in market / Reading out the lift / The decision fork and giving the population back)
  3.7 Calibrating Model Attribution Against Experiment Truth
  3.8 Budget Scenarios: Enrolment, the Two-Pass Waterfall and Approval (The optimizer / Reverting, approving, freezing and invalidating)
  3.9 Reconciling Model Attribution with Platform Reporting
## 4. Endpoint Definitions   (4-column table, 57 rows)
## 5. Error Code Catalogue   (2-column table, 61 rows)
```

**Coverage confirmation (machine-checked)**
- Endpoints: all 57 `(method, path)` pairs from `endpoints[]` present in §4; set equality confirmed; every `roles` list reproduced exactly (0 mismatches; `All roles` used only where all six roles are authorized).
- Errors: 61 rows, one per `errors[]` entry, 0 extras, 0 HTTP-status mismatches against the scaffold.
- Table shapes: §4 exactly 4 columns, §5 exactly 2 columns.
- Meta-leak scan (`difficulty|scaffold|test_recipe|corner case|distractor|trap|worked example|implementer|benchmark`): 0 hits. Fuzzy-word scan: 0 hits.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced.

**Contract 1**
```
Field coverage check:
- entities[].fields: 144 required, 144 present, 0 missing
- endpoints[].input (request payloads): 87 required, 87 present, 0 missing
- endpoints[].query_params: 0 declared separately (folded into input), 0 missing
- endpoints[].path_params: 0 declared separately (folded into input), 0 missing
- unique union after de-duplication: 154 required, 154 present, 0 missing
Status: PASS
```

**Contract 2**
```
Rule coverage check:
- validations[] with priority: 47 checked, 47 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write endpoint + expected_data_window_version / expected_model_run_version + ERR_STALE_DATA_WINDOW_VERSION / ERR_STALE_MODEL_RUN_VERSION all named), 0 missing
- state_machines[].transitions: 35 checked across 6 machines (incl. ModelRun's 4 parallel dimensions), 35 fully expressed, 0 missing; all 21 state literals appear in backticks
- calculations[]: 14 checked, 14 fully expressed, 0 missing
- validations[] conditions: 47 checked, 47 matchable to an error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 30 side-effect endpoints + 47 applies_to scopes checked, all expressed, 0 missing
- entities[].fields[] structured content: 26 checked (enums, defaults, computed formulas), 26 reconstructible from prose, 0 missing
- sibling-branch symmetry: 9 groups checked (validate pass/fail, accept/reject, EFFECT_PERIOD/SPEND_PERIOD adstock, DIFF_IN_DIFF/SYNTHETIC_CONTROL readout, GEO_HOLDOUT/AUDIENCE_SPLIT design, CALIBRATED/RAW basis, optimize/revert, OVER_/UNDER_ATTRIBUTED, MATERIAL/IMMATERIAL), equal prose density, 0 asymmetric
Status: PASS
```

**Contract 3**
```
Path purity check (§3 only):
- backtick tokens scanned: 278
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
- (also: 0 unbackticked /mmm or /_clock mentions, 0 bare method words in prose)
Status: PASS
```

**Verbatim last 3 lines**
```
| `ERR_FLOORS_EXCEED_BUDGET` | 422 |
| `ERR_BUDGET_CEILING_EXCEEDED` | 422 |
| `ERR_BASELINE_BUDGET_MISMATCH` | 422 |
```

**Scaffold contradictions resolved (decisions baked into the prose, worth knowing downstream):** `stability_score` = exactly 1.0000 on a market's first publication with the stability gate skipped; `synthetic_control_weight` = pre-period treatment *rate* / control *rate* (6 dp); `ERR_PERIOD_NOT_ALIGNED` uses a half-open window range while window-vs-window overlap uses a closed range (contrast stated explicitly); an allocation channel outside the run's `included_channel_ids` maps to `ERR_CHANNEL_NOT_IN_MARKET`; CalibrationRecord accepts a source experiment in `READ_OUT` or `ACCEPTED`; same-market requirements lacking an assigned error are stated as requirements without an error id; reconciliation-against-published-run is intent, not a hard gate; `carryover_attribution_mode` must be sent explicitly despite its declared `EFFECT_PERIOD` default.

**Orchestrator verification (independent of the subagent):** `wc -l -c` = 493 / 108095; `tail -12` shows a complete final error-table row (`ERR_BASELINE_BUDGET_MISMATCH | 422`), not a mid-sentence cut; `grep -c '^| \`ERR_'` = 61 rows; five `## ` sections present at lines 3/11/152/363/427. PRD accepted, no regeneration needed.

## Step 5: Generate unit tests — 2026-09-03T07:26:39.908Z

Test generation for `task_2518_marketing_mix_modeling_incrementality_testing` is complete and fully verified.

## Files written

**`test_helpers/`** (Stage 1, 3023 lines): `types.py` 32, `api_errors.py` 175, `constants.py` 202, `test_users.py` 127, `api_client.py` 502, `factories.py` 501, `assertions.py` 528, `fixtures.py` 888, `__init__.py` 68.

**`test_suite/`** (Stage 2, 9116 lines): `conftest.py` 22, plus 18 test files —
queue A: `test_a01_carryover_and_readout_variants.py` 508, `test_a02_composed_arithmetic_orders.py` 450, `test_a03_run_and_experiment_lifecycles.py` 404, `test_a04_staleness_cascades.py` 429, `test_a05_refusal_precedence.py` 252, `test_a06_threshold_boundaries.py` 316, `test_a07_cross_entity_gates.py` 346, `test_a08_window_and_experiment_overlap.py` 471, `test_a09_conserved_quantities.py` 380;
queue B: `test_b01_core_entities.py` 726, `test_b02_lifecycle_transitions.py` 618, `test_b03_derived_quantities.py` 788, `test_b04_input_and_state_validation.py` 657, `test_b05_endpoint_behaviours.py` 506, `test_b06_refusals.py` 1178, `test_b07_authorization.py` 564, `test_b08_version_preconditions.py` 335, `test_b09_write_visibility.py` 166.

Grand total 12,139 lines.

## Tests emitted

- **Queue A (Difficulty): 63 tests** across 18/18 instances, every instance >= 2 tests (min 2, max 6).
- **Queue B (Corner): 78 tests** across 63/63 non-stub instances, every instance >= 1 test. The 26 `excluded_because:` stubs were left untranslated.
- **141 test functions -> 172 collected cases** (parametrization); `pytest --collect-only` clean, no collection errors, every file byte-compiles.

## Instances SKIPPED

**None.** All 81 non-stub design instances survived the PRD-first two-condition filter and were translated at full strength. No `pytest.mark.skip`/`skipif`/`xfail` and no placeholders exist anywhere in the suite.

The filter did bite at *sub-assertion* granularity: roughly a dozen individual field assertions from the design yaml were dropped as PRD-silent while their instance was still translated. The recurring pattern is `computed-field`/`default-value` silence — the PRD names which fields a *successful* operation writes but never states that a *refused* operation persists nothing, so nulls on refused paths (`power_index`, `computed_power`, `modeled_sales_units`, `baseline_sales_units`, `holdout_mape_pct`) are not uniquely derivable. Each such test asserts the observable, PRD-committed part instead (unchanged `status`, unchanged `version`, zero child rows).

## Findings worth your attention

Four independent slices flagged the **same design-index/PRD contradiction**: several instances assert `stability_score == null` for a market's first publication, but PRD 3.5 says verbatim that `stability_score` "is recorded as exactly 1.0000, `refresh_generation` is 1, and the stability gate is skipped entirely." Being PRD-first, no test asserts that field on a first publication. This needs a decision before implementation is judged.

Three smaller design-vs-PRD conflicts, all resolved in the PRD's favour: a fresh allocation row starts at `baseline_spend_cents`, not 0 (3.8); a fresh model run is `UNVALIDATED`/`UNPUBLISHED`, not `PENDING`/`DRAFT` (3.4); adding a geo cell *does* bump the market's `version` (3.1).

## Verification performed

A structural audit script confirms: 141 tests vs 141 `Design:` tags (1:1, no dual tags, no untagged tests); every tag resolves to a real yaml `name:` (zero dangling, zero stubs translated); coverage 18/18 difficulty and 63/63 corner non-stub; no duplicate test names; no forbidden markers; the word "scaffold" and all yaml/section vocabulary absent from both directories. A separate AST pass confirms every one of the 141 docstrings ends with exactly one well-formed `Design:` line and carries a quoted PRD citation; each slice agent independently grep-verified its citations as verbatim substrings of `workspace/PRD.md`.

## Step 6: Generate implementation — 2026-09-03T07:26:39.908Z

The implementation is complete and verified.

## Files written (all under `workspace/implementation/`)

| File | Lines |
|---|---|
| `app.py` | 60 |
| `db.py` | 143 |
| `errors.py` | 149 |
| `lookup.py` | 39 |
| `middleware.py` | 49 |
| `response.py` | 117 |
| `validation.py` | 241 |
| `routes/markets.py` | 94 |
| `routes/channels.py` | 116 |
| `routes/geo_cells.py` | 72 |
| `routes/windows.py` | 132 |
| `routes/observations.py` | 163 |
| `routes/model_runs.py` | 173 |
| `routes/experiments.py` | 347 |
| `routes/calibration.py` | 103 |
| `routes/budgets.py` | 180 |
| `routes/reports.py` | 105 |
| `routes/clock.py` | 25 |
| `services/model.py` | 407 |
| `services/budget.py` | 188 |
| `services/market.py` | 121 |
| `services/reconcile.py` | 116 |
| `services/experiment.py` | 107 |
| `services/numeric.py` | 63 |
| `services/ordering.py` | 58 |
| `services/window.py` | 52 |
| `routes/__init__.py`, `services/__init__.py` | 0 |
| `start.sh` (executable), `requirements.txt` (`flask==3.0.3`) | — |

**3420 Python lines total.** `python3 -m compileall -q .` -> clean (COMPILE_OK); `__pycache__` removed afterwards so the delivered tree is source-only.

## Endpoint count: 57 — exact match

Enumerated from the blueprint decorators: budget-scenarios 6 + budget-allocations 3, calibration-records 3, media-channels 4, clock 1, experiments 10, geo-cells 3, markets 4, model-runs 7 + channel-contributions 2, spend-observations 3 + sales-observations 3, reconciliation-reports 3, data-windows 5 = **57**. The PRD 4 table matches one-for-one.

## Boot smoke test: passed

`PORT=19301 bash start.sh` backgrounded from the implementation dir — Flask reported "Running on all addresses (0.0.0.0)" within ~2s, no pip install (guarded import short-circuits). Then:
- `GET /mmm/markets` with `X-User-ID`/`X-User-Role: Auditor` -> 200, empty data with pagination meta — the store boots empty, confirming no seeding.
- No headers -> 401 `ERR_UNAUTHENTICATED`.
- `POST /mmm/markets` as DataEngineer -> 201 with `version: 1`, `data_posture: "RESTRICTED"`, `held_out_population_pct: 0.0`.
Process killed afterwards; port released.

## Runtime correctness verification (two throwaway scripts, not part of the deliverable)

Calculation fixtures — **all checks passed**: EFFECT_PERIOD adstock `[400000,800000,700000,800000]`, mean 675000, contribution 3653.3333 units / 18361653 cents, average_roi 10.2009, marginal_roi 1.575497, CI at +/-20%; SPEND_PERIOD sibling run gives adstock `[700000,1050000,525000,875000]`, 3787.0430 units, average_roi 10.5743, marginal_roi 1.236971; holdout MAPE 3.39 -> `HOLDOUT_PASSED`; stale OCC -> 412, misaligned period -> 422.

State machines, cascades, SoD, budget — **all checks passed**: two-channel fit with exact baseline conservation, contribution ordering by `channel_code`, publish (stability exactly 1.0000, generation 1, market -> `OPEN`); RAW-basis reconciliation report with per-line-then-weighted variance, duplicate-period -> 409 and omitted-line -> 422; GEO_HOLDOUT experiment with `power_index` 2.9692 -> power 0.9000, cell assignment (held-out 12.00%), cell reuse -> 409, pre-start start -> 409, pre-elapsed read-out -> 409, conversions-over-population outranking the elapsed check -> 422, DIFF_IN_DIFF lift 10.00 +/-8.02 (CI 1.98-18.02), designer self-accept -> 403 SoD, accept cascade; calibration record (implied 18.8835, multiplier 0.5296, `OVER_ATTRIBUTED`), stale version -> 412, recalibrate -> `CALIBRATED` with baseline re-conservation and a `CALIBRATED`-basis report; budget scenario with `ERR_NO_ALLOCATIONS` before rows exist, duplicate allocation -> 409, optimize (pinned pass-one fee 2000 from 200000 churn, 3900000 allocated, 98000 unspent, conservation identity exact), author self-approval -> 403, approve -> `APPROVED`; reopen fires the full four-hop cascade (`STALE_FIT`, `UNVALIDATED`, contributions retired, scenario `INVALIDATED`, posture `FROZEN`); release-cells -> `WASHOUT` until 2026-10-19 with held-out unchanged, then washout-sweep -> `UNASSIGNED`, held-out 0.

One caveat worth noting for whoever runs the suite: the logical clock defaults to `2026-08-01T00:00:00Z` and is forward-only, so any test fixture using dates before that will find date-gated transitions already elapsed (that is what the PRD specifies).

**Orchestrator note:** Steps 5 and 6 were launched concurrently in a single message, so the implementation generator could not read `test_suite/` (it did not exist at its spawn time). Both output trees verified present on disk.

## Step 7: Run tests and iterate — 2026-09-03T07:52:49.936Z

Clean sweep achieved.

## Summary

**Iterations run: 2**

Sweep 1: 165/172 in all 8 rounds — 7 failures, fully deterministic (identical set and identical error messages in every round; no flakiness, no load-induced timeouts). Sweep 2: **172/172 in all 8 rounds**, 0 failed / 0 errors.

**Tests deleted: none.** Every failing assertion traced to a verbatim PRD sentence and survived the unique-derivability check, so all 7 failures were real defects — 4 in the implementation, 3 in the test suite.

**Fixes applied to `implementation/`**

- `workspace/implementation/services/reconcile.py`, `build_reconciliation()` — the per-line dict emitted key `model_attributed_revenue_cents` instead of `model_cents`. PRD 3.9 states verbatim: *"The resulting objects are stored on the report as `variance_lines`, each carrying `channel_id`, `model_cents`, `platform_revenue_cents`, `variance_cents` and `variance_pct`, in that ascending channel order."* The name `model_attributed_revenue_cents` belongs to the report-level total, not the line. This single rename cleared 4 failures (`KeyError: 'model_cents'`).

**Fixes applied to `test_suite/`** (STEP 2 — assertions mis-translated PRD; the implementation was faithful)

All three shared one root cause: the test asserted against a **stale creation-time snapshot** of a budget scenario, after intervening enrolment writes had legitimately moved it on.

- `test_suite/test_a09_conserved_quantities.py`, `test_optimizer_redistributes_the_three_cent_buckets_without_losing_a_cent` — `assert_budget_conservation()` was applied to `fx.scenario_with_allocations`'s creation response (totals 0/0/0, budget 4,000,000). PRD 3.8 explicitly exempts that instant: *"Because a draft has no allocation rows yet, those three cent totals are trivially zero at that moment; the conservation identity of 2.10 becomes meaningful as soon as rows exist and holds in every response thereafter."* Now re-reads the scenario after its rows exist. Same edit fixed the follow-on `optimized["version"] == draft["version"] + 1`, which PRD 3.8 anchors to the state immediately before the call (*"The scenario moves to `OPTIMIZED` and its `version` increments"*), not to a pre-enrolment snapshot.
- `test_suite/test_b06_refusals.py`, `test_baselines_short_of_the_budget_are_refused_then_completed_and_optimized` — asserted `allocated_total_cents == 0` on a DRAFT that already held an allocation row. PRD 3.8: *"A new row starts with `allocated_cents` equal to its `baseline_spend_cents` … that is, an un-optimized scenario reports the plan it was handed"* and *"`allocated_total_cents` is the sum of the rows' `allocated_cents`"*, so the correct value is the baseline sum. Replaced with a before/after snapshot comparison (strengthened: now also pins `unallocated_cents`, `shifted_total_cents` and the version as unchanged by the refused request).
- `test_suite/test_b06_refusals.py`, `test_floors_above_the_whole_budget_outrank_the_baseline_reconciliation` — same `== 0` mis-translation, plus `assert_version_unchanged(tight, after)` compared across an intervening `add_allocation`. Same before/after-snapshot fix.

No assertion was weakened, no exact `error_id` check downgraded, no skip/xfail added, and no PRD-required implementation check was removed.

**Fixes applied to `test_helpers/`: none** — the fixtures and factories were PRD-faithful throughout.

**Notes**
- The open question flagged by the test generator (first-publication `stability_score`) never surfaced; no action taken.
- The 8 result files are preserved as evidence at `workspace/sweep_results/`, moved out of `implementation/` so the delivered tree stays source-only. `__pycache__` removed.

**Orchestrator verification (independent of the subagent):** all 8 `results.*.json` in `workspace/sweep_results/` parsed — every one reports `passed=172 total=172 failed=0 errors=0`, all written at 07:45 (a real concurrent sweep, not a stale or fabricated artifact). Copies also placed in `workspace/implementation/` to match the skill's documented output layout. Independent greps confirm: zero `pytest.mark.skip/skipif/xfail` anywhere in `test_suite/` or `test_helpers/`; 141 test functions (-> 172 parametrized cases, consistent with the reported total); zero sqlite/pickle/json.dump/`/tmp` persistence in `implementation/`, i.e. in-memory storage only.

## Step 8: Finalize PRD — 2026-09-03T07:57:22.829Z

Done. Both edits applied to `PRD_FINALIZED.md`.

## Line counts
- `PRD.md`: 493 lines / 108,095 bytes
- `PRD_FINALIZED.md`: 493 lines / 109,107 bytes
- Delta: 0 lines (+2 sentences inserted into existing paragraphs), **+1,012 bytes = +0.94%**

## Changes (2)
- **3.8 "Channels are enrolled one at a time…"** — insert — enrolling a budget allocation is also a write to the parent scenario: `allocated_total_cents` = sum of rows' `allocated_cents`, `unallocated_cents` = `total_budget_cents` - `reallocation_fee_cents` - that sum (so the 2.10 identity holds from the first row, not only post-optimize); `shifted_total_cents` and the two projection totals untouched; the scenario's `updated_at`/`version` move only when one of the two figures actually changes (a `baseline_spend_cents` of 0 leaves the version alone) — `implementation/services/budget.py:179-188` (`refresh_allocation_totals`), callsite `implementation/routes/budgets.py:162`.
- **3.8 optimizer gate paragraph** — insert — a refused optimize persists nothing (cent buckets, `status`, `updated_at`, `version` unchanged; an un-optimized scenario still reports its baseline plan rather than zeros) — `implementation/services/budget.py:72-95` (all five gates precede any write) and `budget.py:36-38` (`_greedy` floors refusal in either pass, still pre-write).

## Items with **no** PRD change
- **`reconcile.py` `model_cents` rename** — PRD 3.9 already pins the per-line key verbatim (`"each carrying channel_id, model_cents, platform_revenue_cents, variance_cents and variance_pct"`) and the report-level total separately as `model_attributed_revenue_cents`. Step 7's fix moved the impl *to* the PRD; nothing was under-determined, so prose kept verbatim.
- The three `test_suite/` fixes were stale-snapshot assertion bugs; their PRD anchors (creation-time zeros, `allocated_cents = baseline_spend_cents`, `allocated_total_cents` as the row sum, version increment on optimize) exist verbatim and were left untouched. What they *did* reveal — that enrolment legitimately moves the scenario's buckets and version, and that a refusal moves nothing — is what the two edits pin.

## Pre-edit search log
**Edit 1** — (a) Subject: scenario-level cent aggregates (`allocated_total_cents`, `unallocated_cents`, `shifted_total_cents`, projection totals) and scenario `version`/`updated_at` on allocation enrolment. (b) Enumerated: `grep -rn "refresh_allocation_totals|allocated_total_cents|unallocated_cents|shifted_total_cents" implementation/` -> every writer read in full: `routes/budgets.py:57-80` (create defaults all 0), `routes/budgets.py:123-163` (the only enrolment path; no allocation update/delete endpoint exists), `services/budget.py:135-141` (optimizer), `:147-156` (revert, which overrides to `total_budget`/0), `:179-188` (conditional `touch`), `services/market.py:77-108` (`reset_scenario_to_baseline` + freeze/thaw, which use the residual formula), plus `db.touch`/2.4 semantics and PRD lines 188/292 (freeze/thaw prose) to confirm no contradiction. (c) Adjustments: scoped the sentence to "enrolling a row" so it cannot be read as overriding revert's `allocated_total_cents = total_budget_cents` / `unallocated_cents = 0`; replaced an earlier draft's "`shifted_total_cents` stays 0 until the optimizer runs" with "`shifted_total_cents` and the two projection totals are left untouched by the enrolment" (describes the code's actual non-write instead of asserting a state universal); added the explicit no-change/no-version-bump clause to match the conditional `touch` at `budget.py:186`.

**Edit 2** — (a) Subject: side effects of a *refused* optimize on the scenario and its rows. (b) Enumerated: `services/budget.py:72-144` line by line (all five gates and both `_greedy` calls precede the first mutation at line 126, including the pass-two `ERR_FLOORS_EXCEED_BUDGET` at `:36-38` which fires after the fee is priced but before any write), `services/market.py:117-121` (`require_posture_open` is a pure read — no `sync_market`/`touch`), `routes/budgets.py:100-104` (route does auth + `must` lookup only), `middleware.py:36-49` and `errors.py` (no write on the error path), `routes/budgets.py:94-97` (`GET` scenario does not refresh totals, so the post-refusal read is a faithful snapshot). (c) Adjustment: scoped to "a refusal at any of those rungs" rather than a service-wide "no rejected request ever persists anything", and named `updated_at`/`version` explicitly since 2.4 ties them to mutation.

**Orchestrator verification:** `PRD_FINALIZED.md` is 493 lines / 109,107 bytes, is NOT byte-identical to `PRD.md` (diff shows exactly the two in-paragraph 3.8 insertions and no other hunks), and ends at the same real section boundary (final error-table row `ERR_BASELINE_BUDGET_MISMATCH | 422`) — not truncated.

## Step 9: Complete PRD — 2026-09-03T08:23:37.157Z

**Orchestrator decision (recorded per the autonomy directive):** Step 9 was run as **three sequential file-partitioned passes** over `implementation/`, each editing `workspace/PRD_COMPLETED.md` in place, rather than as one single-pass subagent. Rationale: a single Step 9 subagent facing a 493-line PRD plus a 3400-line implementation has repeatedly, in this pipeline, returned a `PRD_COMPLETED.md` byte-identical to its source — i.e. the exhaustive scan never actually ran. Partitioning forces every implementation module to be walked by some pass. Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 edited the existing file. Partition: pass 1 = core infra (`app/db/errors/lookup/middleware/response/validation`) + `services/{numeric,ordering,window,market}.py` + `routes/{markets,channels,geo_cells,windows,observations}.py`; pass 2 = `routes/{model_runs,calibration,reports}.py` + `services/{model,reconcile}.py`; pass 3 = `routes/{experiments,budgets,clock}.py` + `services/{experiment,budget}.py`.

### Pass 1 of 3 — core infra + markets / channels / geo cells / windows / observations

Counts: `PRD_FINALIZED.md` 493 lines / 109,107 chars -> `PRD_COMPLETED.md` 493 lines / 112,958 chars. Ambiguity-pins: 13 · Mismatch-revisions: 2. All 15 changes were in-place single-line replacements inside 2.1-2.7 and 3.1-3.3; no lines added or removed, so 3.4 onward stayed byte-identical for passes 2 and 3.

- 2.1 — insert — ambiguity — whitespace-only identity header counts as empty (-> `ERR_UNAUTHENTICATED`); both headers trimmed before role matching — `middleware.py:40-49`
- 2.3 — insert — ambiguity — `limit`/`offset` must be base-ten integers or `ERR_INVALID_REQUEST`; omitted/empty falls back to default; all other query params are unvalidated equality filters (unrecognised enum value -> empty page, empty-string value ignored) — `response.py:84-106`, `routes/markets.py:60-65`
- 2.3 — revise — **mismatch** — PRD gave sales observations a `channel_code` tie-break, but a sales row names no channel; impl ties on `period_start_date` only — `services/ordering.py:32-35`
- 2.4 — insert — ambiguity — `created_at`/`updated_at` come from real server time, not the 2.9 logical clock — `db.py:49-51`
- 2.5 — insert — ambiguity — explicit JSON `null` == omitted field; absent/`null` body == empty object; non-object body -> `ERR_INVALID_REQUEST`; date fields accept bare `YYYY-MM-DD` or UTC-midnight instant (non-zero time or non-zero offset rejected) and echo the client's wire shape verbatim; unknown path/method -> `ERR_INVALID_REQUEST` at HTTP 404/405 — `validation.py:22-45,167-210`, `app.py:37-44`
- 2.6 — insert — ambiguity — scaled decimals serialise as JSON numbers, not quoted strings — `response.py:33-52`
- 2.7 — insert — ambiguity — a missing/non-integer/negative `expected_data_window_version` is `ERR_INVALID_REQUEST`, not a 412 mismatch — `routes/observations.py:38`
- 3.1 — revise — **mismatch** — `adstock_decay_rate` must carry *at most* two decimal places (PRD said "exactly"); impl accepts `0` and `0.5` — `routes/channels.py:27`
- 3.1 — insert — ambiguity — channel PATCH re-checks `max_spend_cents >= min_spend_cents` against merged values; a no-op or empty body still bumps `version` — `routes/channels.py:108-115`
- 3.2 — insert — ambiguity — window `end > start` and exact-division checks run before `market_id` resolution (`ERR_INVALID_REQUEST` beats `ERR_MARKET_NOT_FOUND`) — `routes/windows.py:33-41`
- 3.2 — insert — ambiguity — window overlap test ignores the incumbent's `status` — `routes/windows.py:43-50`
- 3.2 — insert — ambiguity — `price_index`/`distribution_index` are unbounded and unrounded, null when omitted — `routes/observations.py:36-37`
- 3.2 — insert — ambiguity — `include_superseded` accepted truthy/falsy tokens; `superseded_by_id` filter only returns rows when `include_superseded` is also true — `routes/observations.py:86-98`, `validation.py:232-241`
- 3.2 — insert — ambiguity — `macro_index` unbounded; both sales optionals null when omitted — `routes/observations.py:117-119`
- 3.3 — insert — ambiguity — reopen `reason` is required as a string but may be empty — `routes/windows.py:123`

Verified-consistent, no edit needed: posture ladder ordering and `ERR_MARKET_POSTURE_BLOCKED` gates (`services/market.py:16-30`); the seal precondition order state->elapsed->completeness and the sales create order state->uniqueness->alignment, both matching the 2.12 ladder; `reset_scenario_to_baseline`'s `unallocated_cents = total_budget - sum(baseline)` reduces to the 3.6/3.8 "zero" wording because freeze/thaw only ever touch scenarios that passed `ERR_BASELINE_BUDGET_MISMATCH`; the whole 5 status table matches `errors.py:12-81` exactly; every persisted field in the six entities owned by this pass is already named in the PRD with no extras.

### Pass 2 of 3 — model runs / holdout + publication / calibration / reconciliation

Counts: 493 lines / 112,958 chars -> 493 lines / 117,412 chars. 21 changes: **18 ambiguity-pins, 3 mismatch-revisions**. All surgical in-paragraph edits; file still exactly 493 lines.

- 3.4 — insert — ambiguity — window-not-in-run's-market is `ERR_INVALID_REQUEST`, and that test plus the `holdout_periods` and channel-membership tests run only after all three FKs resolve, in that order — `routes/model_runs.py:52-65`
- 3.4 — insert — ambiguity — `control_variables` omitted is recorded as an empty array — `routes/model_runs.py:38-41`
- 3.4 — revise — **mismatch** — deleted "(`EFFECT_PERIOD` is its declared default value)"; the field has no default and omitting it is `ERR_INVALID_REQUEST` — `routes/model_runs.py:49`
- 3.4 — insert — ambiguity — a new run already reports `refresh_generation` 1 with `unit_price_cents`/`modeled_sales_units`/`baseline_sales_units`/`observation_period_count`/`holdout_mape_pct`/`stability_score` null — `routes/model_runs.py:81-87`
- 3.4 — revise — **mismatch** — `SPEND_PERIOD` total is "at least as large" as `EFFECT_PERIOD`, strictly larger only when decay and lag are both non-zero — `services/model.py:39-51`
- 3.4 — insert — ambiguity — a baseline-negative fit also leaves the run's aggregates and any pre-existing `STALE_FIT` row set intact (deletion happens only after the identity closes) — `services/model.py:155-161`
- 3.4 — insert — ambiguity — `is_current` list filter reads `true`/`1`/`yes` (trimmed, case-insensitive) as true and coerces every other non-empty value to false instead of rejecting — `routes/model_runs.py:160-163`
- 3.5 — insert — ambiguity — validation may be re-invoked after it has branched, recomputing in place; `publication_status`/`calibration_status` are not consulted — `services/model.py:205-207`
- 3.5 — insert — ambiguity — the per-period baseline uses `baseline_sales_units` as the run currently reports it, so a recalibration moves the backtest — `services/model.py:215`
- 3.5 — insert — ambiguity — holdout per-period contributions are re-derived from the `is_current` rows' stored series and fit-time curve parameters, so a later channel revision cannot move them — `services/model.py:217-227`
- 3.5 — insert — ambiguity — zero base total: score is 1.0000 when drift is zero, else 0.0000 (no division) — `services/model.py:268-269`
- 3.5 — insert — ambiguity — `override_stability` is optional and strictly boolean; a non-boolean is `ERR_INVALID_REQUEST` at body-shape time, `false`/omitted leaves the gate armed — `routes/model_runs.py:137`
- 2.7 — insert — ambiguity — `expected_model_run_version` is an integer of zero or more (same shape rung as the window field) — `routes/calibration.py:25`
- 3.7 — insert — ambiguity — both channel tests answer `ERR_CHANNEL_NOT_IN_MARKET`; a run with no `is_current` row for the channel is `ERR_MODEL_RUN_INVALID_STATE`; a wrong experiment status is `ERR_EXPERIMENT_INVALID_STATE` and outranks all three — `routes/calibration.py:36-55`
- 3.7 — insert — ambiguity — `ERR_CALIBRATION_MULTIPLIER_OUT_OF_RANGE` also answers zero residual and a 0.0000 implied lift — `services/reconcile.py:22-32`
- 3.7 — insert — ambiguity — `superseded` filter uses the `true`/`1`/`yes` vocabulary; other values are `ERR_INVALID_REQUEST` — `routes/calibration.py:94-96`
- 3.7 — insert — ambiguity — a decomposition row whose calibrated figures come out unchanged is not bumped (`updated_at`/`version` frozen) — `services/model.py:355-361`
- 3.9 — revise — **mismatch** — the run's `publication_status` is never inspected, so a fitted but `UNPUBLISHED` run is a valid report target — `routes/reports.py:53-62`
- 3.9 — insert — ambiguity — `platform_lines` needs >=1 entry; non-object entries, non-integer or missing `platform_revenue_cents` (any sign accepted) are `ERR_INVALID_REQUEST` — `routes/reports.py:19-40`
- 3.9 — revise — ambiguity — gate precedence: calibration state -> posture -> platform-line match -> per-period uniqueness — `routes/reports.py:57-67`
- 3.9 — insert — ambiguity — `variance_pct` is 0.00 when a line's `model_cents` is zero, `weighted_variance_pct` is 0.00 when `model_attributed_revenue_cents` is zero, and the submitted entries are echoed as `platform_lines` (order preserved, reduced to the two keys) — `services/reconcile.py:88-106`, `routes/reports.py:74`

Left deliberately undocumented: two impl guards in this partition (`ERR_DATA_WINDOW_INCOMPLETE` raised inside `perform_fit`/`perform_validate` for absent sales) are unreachable given a sealed window is 100% complete, so the PRD stays silent on them rather than documenting dead paths.

### Pass 3 of 3 — experiments / budgets / clock

Counts: 493 lines / 117,412 chars -> 493 lines / 121,735 chars. **Ambiguity-pins: 17 · Mismatch-revisions: 6** (23 edits). All in-paragraph, line-preserving.

- 2.9 — revise — ambiguity — `current_utc` pinned as a required ISO-8601 zero-offset instant (bare date = midnight; missing field or non-zero offset -> `ERR_INVALID_REQUEST`), and the success response's `data` carries that one field echoing the supplied string — `routes/clock.py:18-25`, `validation.py:194-199`
- 2.10 — revise — mismatch — fiscal conservation identity holds "from the first allocation row onwards"; a fresh scenario reports all three components at 0 against a positive budget — `routes/budgets.py:66-71`
- 3.6 — revise — ambiguity — `end_date > start_date` is a body-shape check preceding `market_id`/`channel_id` resolution; `washout_days` is required — `routes/experiments.py:37,44-48`
- 3.6 — revise — ambiguity — draft create-time nulls/zeros (`power_index`, `computed_power`, `synthetic_control_weight`, 4 counts, 4 lift fields null; both realised populations 0) — `routes/experiments.py:67-79`
- 3.6 — revise — mismatch — assign-cells: cell resolution runs *before* the `DESIGN_LOCKED` state check (PRD had them the other way round); both arrays required, may be empty, repeats not rejected — `routes/experiments.py:148-158`
- 3.6 — revise — ambiguity — assign-cells share ceiling sums the *distinct* named cells — `routes/experiments.py:174-177`
- 3.6 — revise — ambiguity — arm populations sum each array as supplied (repeat counts twice; a cell in both arrays counts in both arms and ends in `CONTROL`) — `routes/experiments.py:179-189`
- 3.6 — revise — ambiguity — `ERR_CONVERSIONS_EXCEED_POPULATION` outranks `ERR_EXPERIMENT_NOT_ELAPSED` — `routes/experiments.py:234-243`
- 3.6 — revise — ambiguity — synthetic control rescales by the *published six-decimal* weight, not the unrounded quotient — `services/experiment.py:87-89`
- 3.6 — revise — mismatch — accept-cascade hop 3 freeze detail: rows reset to baseline/0/`NONE`/0.0000, fee + `shifted_total_cents` + both projection totals zeroed, `allocated_total_cents`/`unallocated_cents` recomputed from the restored baselines (PRD said `unallocated_cents` was zeroed) — `services/market.py:77-100`
- 3.6 — revise — ambiguity — `rejection_reason`: whitespace-only counts as empty (contrast with reopen `reason`) — `routes/experiments.py:290-292`
- 3.6 — revise — ambiguity — computed `washout_until_date` is rendered in the wire shape the experiment's `end_date` was supplied in — `routes/experiments.py:325`
- 3.6 — revise — ambiguity — the redesign limit is tested before any cell is moved, so a refused loop writes nothing — `routes/experiments.py:313-315`
- 3.6 — revise — mismatch — the redesign loop leaves `synthetic_control_weight`, `rejection_reason` and `decided_by_user_id` standing (PRD claimed everything computed is cleared) — `routes/experiments.py:330-344`
- 3.8 — revise — ambiguity — run-not-in-market on scenario create is `ERR_INVALID_REQUEST`; `reallocation_fee_pct` defaults to 0.00 — `routes/budgets.py:31-40`
- 3.8 — revise — mismatch — the same-market and horizon-exactness tests outrank the run-state and ceiling gates (`ERR_INVALID_REQUEST` wins over `ERR_MODEL_RUN_NOT_PUBLISHED`) — `routes/budgets.py:39-55`
- 3.8 — revise — ambiguity — scenario create-time `projected_contribution_units` 0.0000 and `projected_incremental_revenue_cents` 0 — `routes/budgets.py:70-71`
- 3.8 — revise — mismatch — `ERR_CHANNEL_RETIRED` named and pinned as outranking both membership tests and the duplicate test (PRD listed membership first, error unnamed) — `routes/budgets.py:132-149`
- 3.8 — revise — ambiguity — enrolment is not gated on scenario status — `routes/budgets.py:124-163`
- 3.8 — revise — mismatch — the "zero-baseline row does not bump the scenario" example only holds after the first enrolment; the first always moves `unallocated_cents` off 0 — `services/budget.py:179-188`
- 3.8 — revise — ambiguity — marginal gains compared exactly (not at four decimals); a `PAUSED` channel is still seeded at its floor and `PAUSED` is the only status the walk skips (a post-enrolment retirement is walked normally) — `services/budget.py:39-58`
- 3.8 — revise — ambiguity — pass two can itself raise `ERR_FLOORS_EXCEED_BUDGET` off the fee-reduced budget, with nothing written — `services/budget.py:107,36-38`
- 3.8 — revise — ambiguity — optimize and revert rewrite every allocation row unconditionally (version bumps even when figures are unchanged); freeze/thaw do the same — `services/budget.py:130,147-156`, `services/market.py:80-108`
- 3.8 — revise — mismatch — approval's duty comparison outranks the state check — `services/budget.py:159-165`

### Step 9 totals and orchestrator verification

Across the three passes: **48 ambiguity-pins + 10 mismatch-revisions = 58 edits**, 54 changed lines, `PRD_FINALIZED.md` 109,107 chars -> `PRD_COMPLETED.md` 121,735 chars (+12,628 chars, +11.6%), line count unchanged at 493 throughout (every edit was in-paragraph).

Orchestrator-side checks (independent of the subagents): `wc -l -c` = 493 / 121,735; `cmp` against `PRD_FINALIZED.md` shows the file is NOT byte-identical (54 `>` lines in the diff), so the scan genuinely ran and did not silently no-op; the document still has all five `## ` sections and all 61 error rows, and ends at the real final boundary (`| ERR_BASELINE_BUDGET_MISMATCH | 422 |`) rather than mid-sentence; and `find implementation -name '*.py' -newer sweep_results/results.1.json` returns nothing, confirming no implementation file was modified after the green 8-round sweep — the 8×172/172 result therefore still describes the delivered code.

**PIPELINE COMPLETE.** All nine steps executed. Final state: 172/172 tests passing in all 8 concurrent rounds; `workspace/PRD_COMPLETED.md` written.
