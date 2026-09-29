# Worklog — task_2377_semiconductor_fabrication_yield_management

## Step 1: Create task directory — 2026-09-02T00:00:00.000Z

Created `tasks/task_2377_semiconductor_fabrication_yield_management/` and `tasks/task_2377_semiconductor_fabrication_yield_management/workspace/` (pre-allocated name used verbatim; no index scan performed).

## Step 2: Generate scaffold — 2026-09-02T07:31:00.000Z

Done. All three artifacts are complete, lint-clean, and the scratch chunk files have been removed.

## Output
`/home/ubuntu/github/CodingPRD/tasks/task_2377_semiconductor_fabrication_yield_management/`
- `SCAFFOLD.yaml` (143 KB) — §1.0–§1.7 only; neither `scaffold_difficulty_design` nor `scaffold_corner_design` present
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (189 KB) — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (341 KB) — single top-level key `scaffold_corner_design`

## SCAFFOLD.yaml counts
`domain_name: semiconductor-fab-yield`, `api_prefix: /fab`

| §1.1 entities | §1.2 state machines | §1.2.1 concurrency rules | §1.3 calculations | §1.4 validations | §1.5 endpoints | §1.6 errors | §1.7 roles |
|---|---|---|---|---|---|---|---|
| 14 | 14 | 3 | 10 | 50 | 63 | 61 | 6 |

Roles: ProcessEngineer, FabPlanner, QualityManager, EquipmentEngineer, YieldEngineer, Operator.

## §1.8 difficulty design — 24 instances
All nine §0.5 rules covered at ≥2: `dual_variant_calc` 3, `combinatorial_formula` 3, `non_linear_state_machine` 3, `transitive_cascade` 2, `priority_pair_validation_conflict` 3, `boundary_precision_check` 3, `cross_entity_state_dependency` 3, `resource_temporal_overlap` 2, `compensating_invariant` 2.

## §1.9 corner design — 103 instances (89 with `test_recipe`, 14 `excluded_because` stubs)
entities 12, state_machines 19 (2 stubs), calculations 14 (4), validations 26 (3), endpoints 7 (2), errors 11, rbac 9 (1), cross_cutting_complexity_layers 4 (2), consistency_model 1 — all nine taxonomy sections present.

## Audits
- **Lint:** clean (verdict block below). 1420 calls scanned across both design files.
- **Error coverage:** 61 declared / 0 uncovered.
- **Endpoint coverage:** 63 declared / 63 referenced. 53 are exercised as executable `call:` steps; the remaining 10 (all GET list/detail: process-flows, process-steps/{id}, change-requests, spc-charts, chambers, operators, wafer-start-plans, step-runs, measurements, die-sort-runs) are exercised at assertion level (e.g. `GET /fab/spc-charts returns meta.total_count == 0`). Added `process_step_reads_are_scoped_by_flow_and_by_rework_target` this pass so `GET /fab/process-steps` and `GET /fab/process-steps/{id}`, previously absent from both files, are now covered.
- **Replay audit (mechanical, 127 instances):** 0 problems — no duplicate names across the two files, every `${placeholder}` in a path/payload/assert is captured by an earlier call in the same instance, every `as:` role is a declared §1.7 role, and every `POST /_clock/set_current_utc` sequence is monotonic within its instance.
- **Error/status consistency:** every `ERR_*` mentioned in a recipe is declared in §1.6 and asserted with its declared HTTP status. Four apparent mismatches were verified as intentional: three are negative assertions in priority-ordering instances (`${err} != ERR_STALE_RECIPE_VERSION`, `!= ERR_NO_QUALIFIED_CHAMBER`, `!= ERR_STALE_PLAN_VERSION`) and one states the status inline (`returns 409 ERR_SPC_CHART_SUSPENDED`).
- **Stub audit:** all 14 `excluded_because` stubs have `name` + `claim_type` + `grounds` + `{difficulty_instance, rationale}`, no `test_recipe`, and every citation resolves. Fixed one bad citation this pass: `per_wafer_rounding_precedes_the_sort_yield_average` cited `boundary_precision_check / die_yield_rounds_each_wafer_before_averaging`, but that instance lives under `combinatorial_formula`.

One SCAFFOLD.yaml semantic fix was carried in from earlier in the run: `ERR_PINNED_REVISION_STALE` was unreachable because `approve` required `Recipe.status == QUALIFIED` while `implement` returned the Recipe to QUALIFIED, so two change requests could never both sit APPROVED at the same revision. The Recipe state machine, the RecipeChangeRequest transitions, and the approve endpoint now allow multiple pending ECNs — the first approval performs `QUALIFIED → RESTRICTED`, later approvals are a status no-op that still bumps `Recipe.version` — which both matches real fab ECN behaviour and makes "the first implement invalidates the second request's pinned revision" reachable.

## Lint verdict (verbatim)
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    63
  §1.1 entities declared:     14
  §1.8 instances scanned:     24
  §1.9 instances scanned:     89
  Calls scanned (§1.8+§1.9):  1420

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

The hard constraint was honoured throughout: no sibling task directory under `tasks/` was listed, globbed, grepped, or read at any point.

## Step 3: Copy shared files — 2026-09-02T07:31:30.000Z

Copied `INSTRUCTION.md` to `tasks/task_2377_semiconductor_fabrication_yield_management/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T07:48:00.000Z

PRD generated and audited.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2377_semiconductor_fabrication_yield_management/workspace/PRD.md` — 465 lines, ends at §5 with no audit footer.

**Structure**
- §1 Introduction (3 paragraphs: fab business context, scope, the two cross-cutting commitments)
- §2 Global Specifications, 12 domain-derived subsections: 2.1 Fab Personnel and Role-Based Access Control · 2.2 API Response Structure (byte-verbatim from `section-2.2-response-structure.md`, machine-verified) · 2.3 Pagination · 2.4 Common Resource Properties and the Logical Clock · 2.5 Numeric Precision and Rounding Discipline · 2.6 Optimistic Concurrency on Plans, Recipes and Parent Lots · 2.7 Request Validation Order (all 50 priorities, ordered) · 2.8 Nested Resource Retrieval · 2.9 Cascading State Propagation · 2.10 Segregation of Duties · 2.11 Cleanroom Contamination Control and Gowning Protocol · 2.12 The Tool Capacity Ledger and Wafer Inventory Conservation
- §3 Business Logic, 9 lifecycle subsections: flow definition/release → recipe change control → tools/chambers/PM/qualification → wafer start planning and capacity commitment → lot creation/release/cycle time → cleanroom readiness and running the line → metrology/SPC/excursion onset → containment/disposition/rework/splits → sort/yield/speed-grade binning
- §4 Endpoint Definitions (4 columns, 63 rows) · §5 Error Code Catalogue (2 columns, 61 rows)

**Field coverage check**
- entities[].fields: 144 required, 144 present, 0 missing
- endpoints[].input (request bodies + query params): 154 required, 154 present, 0 missing
- endpoints[].output object fields (`cycle-time-projection`, `current_utc`): 7 required, 7 present, 0 missing
- Status: PASS

**Rule coverage check**
- validations[] with priority: 50 checked, 50 expressed in prose (§2.7 ordering + §3 semantics), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (operation + `expected_plan_version`/`expected_recipe_version`/`expected_lot_version` + error_id all named), 0 missing
- state_machines[].transitions: 53 checked across 13 machines (incl. Lot's and Operator's parallel dimensions), 53 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed with every constant and all pinned evaluation orders, 0 missing
- validations[] conditions: 50 checked, 50 matchable to error_id in prose, 0 missing
- endpoints[].side_effects: 126 checked, 126 expressed, 0 missing
- entities[].fields[] structured content (defaults, ranges, uniqueness, nullability, `common_fields: false` on `MetrologyMeasurement`): reconstructible from prose, 0 missing
- sibling-branch symmetry: 15 groups checked (revision-vs-reject, PASS/FAIL qual runs, IDLE|DOWN→PM, IDLE|PRODUCTIVE→DOWN, four cert transitions, both gowning transitions, three containment scopes, three dispositions, six PROVISIONAL/FINAL affected-lot definitions, two dispatch variants, projection-vs-chronological, four tiers, four signature modes, three-bucket waterfall, four ledger events), 0 asymmetric
- Status: PASS

**Path purity check (§3 only)**
- backtick tokens scanned: 985 · tokens starting with `/`: 0 · bare HTTP-method tokens: 0 · method+path combined tokens: 0 · raw `/fab` or `_clock` substrings: 0
- Status: PASS

**Cross-checks:** §4 table validated programmatically against `endpoints[]` — 63/63 method+path rows, exact role-set match on every row. §5 table validated against `errors[]` — 61/61 IDs with 0 status mismatches and 0 extras.

**One gap found and repaired during audit:** the first draft omitted operator registration (`badge_id`, `full_name`) and both `Operator` state machines. Added as the opening of §3.6, which was retitled "Cleanroom Readiness and Running the Line" to keep §3 at 9 subsections.

**Withheld files were not accessed:** neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced, and no sibling task directory was read. All worked examples in the PRD are absent — every numeric value in the prose is a scaffold constant, threshold, or default.

## Step 5: Generate unit tests — 2026-09-02T09:20:00.000Z

Test generation is complete for `task_2377_semiconductor_fabrication_yield_management`.

## Files written

**Stage 1 — `/home/ubuntu/github/CodingPRD/tasks/task_2377_semiconductor_fabrication_yield_management/test_helpers/`** (9 files, unchanged this session): `__init__.py` (barrel), `types.py`, `constants.py`, `api_errors.py` (61 `ERR_*` + `ERROR_STATUS_MAP` + `VALIDATION_PRIORITY` 1–50), `test_users.py`, `api_client.py` (`FabApiClient`, incl. `request_without_headers`), `factories.py`, `assertions.py` (round-half-up 2/3/4-dp helpers), `fixtures.py` (`FabBuilder`, `LineSpec`/`build_line`, presets, progression helpers).

**Stage 2 — `test_suite/`**: `conftest.py` plus 19 test modules. Files added this session: `test_13_validations_operator_and_flow.py` (12), `test_14_validations_quantitative.py` (11), `test_15_endpoints.py` (5), `test_18_cross_cutting.py` (2), `test_19_consistency_model.py` (1).

## Test counts

- **137 tests total**, all collected by pytest (`137 tests collected`, no errors), all `py_compile` clean, `pyflakes test_suite/*.py` silent.
- **Queue A (Difficulty, §1.8): 48 tests / 24 instances** — every instance has ≥2 tests (`test_01`–`test_09`).
- **Queue B (Corner, §1.9): 89 tests / 89 non-stub instances** — every non-stub instance has ≥1 test. Per section: validations 23, state_machines 17, entities 12, errors 11, calculations 10, rbac 8, endpoints 5, cross_cutting 2, consistency_model 1.

## Coverage audit

Scripted audit (`/tmp/checkquotes.py`, `/tmp/verifytags.py`) reports: `tests: 137 problems: 0`, `unique tags: 113` (48 Difficulty + 89 Corner = 137 tags, 113 distinct instances), `tags ok`, `difficulty instances: 24 under 2 tests: []`, `corner instances: 89 / corner remaining: 0`. Every test docstring ends in exactly one verbatim `Design:` line, every `PRD: "..."` quote verifies as a whitespace-normalized substring of `workspace/PRD.md`, and no tag points at a stub.

## Instances skipped

None of the 113 non-stub instances were skipped. The 14 `excluded_because:` corner stubs were not translated, per the contract.

## Disclosures (design-vs-PRD deviations)

1. **`MEMORY_D5` → `MEMORY_D1`**: the corner design uses `MEMORY_D5` in three places (`process_step_reads_are_scoped_by_flow_and_by_rework_target`, `plan_for_a_different_product_family_returns_product_family_mismatch`). PRD §3.1 fixes the enum at `LOGIC_N5`/`LOGIC_N7`/`MEMORY_D1`, so `MEMORY_D5` would trip `ERR_VALIDATION` instead of the intended rule. Substituted `MEMORY_D1` (still a genuine family mismatch against the `LOGIC_N5` flow).
2. **Chart-SUSPENDED-on-violation conflict**: a difficulty instance asserts the chart suspends on the violating measurement, but PRD §3.8 suspends a chart only via `SPC_CHART` containment. The sub-assert is omitted in `test_06`; `SUSPENDED` is reached through explicit containment in `test_07`/`test_17`/`test_19`.
3. **DRAFT-plan `commitment_tier`**: a design line implies null; PRD §3.4 says a drafted plan opens at `TIER_0`. Asserted `TIER_0`.
4. **`expected_recipe_version: "${r_v} - 1"`** in one approval recipe is a stale-version probe that the PRD's §2.6 semantics make `version + 1`; used `version + 1`.
5. Two minor asserts omitted as not PRD-derivable: the "§1.5 declares no PATCH route" sub-assert in `test_10`, and the `qualified_at`/`qual_expires_at` null asserts at `EQUIPMENT`-scope containment in `test_11` (PRD only clears those at `CHAMBER` scope).

The suite cannot be executed end-to-end here — there is no candidate implementation in `workspace/`; verification was limited to collection, compilation, lint, quote verification and tag/coverage auditing.

## Step 6: Generate implementation — 2026-09-02T09:20:00.000Z

Implementation complete and validated.

## Files written
All under `/home/ubuntu/github/CodingPRD/tasks/task_2377_semiconductor_fabrication_yield_management/workspace/implementation/`:

- Core: `app.py` (app factory, unauthenticated `/_clock/set_current_utc`, ApiError/HTTPException/catch-all handlers, `strict_slashes = False`, `threaded=True`), `start.sh` (executable, installs Flask only if missing, `exec python3 app.py`, honours `$PORT`), `requirements.txt`
- Infrastructure: `db.py` (14 plain dicts, no seeding), `clock.py` (logical clock pinned to `2026-08-01T00:00:00Z`), `response.py` (meta/envelope/pagination), `errors.py` (all 62 PRD error ids + 404/405/500 mappings), `auth.py` (`X-User-ID`/`X-User-Role`), `validate.py`, `util.py` (Decimal ROUND_HALF_UP helpers), `calc.py` (every derived-value formula)
- Domain: `services/cascades.py` (hold precedence, containment, particle escalation, requalification, tool-down, capacity ledger), `routes/{common,flows,equipment,planning,production,excursions,sort}.py`

## Endpoint count
63 business endpoints registered — exact parity with the 63 declared in `SCAFFOLD.yaml` (`grep -c "^  - method:"` = 63; Flask reports 63 non-static rules).

## Verification
Two throwaway end-to-end smoke suites (`/tmp/fab_smoke.py`, `/tmp/fab_smoke2.py`, not part of the deliverable) both report `FAILURES: 0` against freshly launched servers. Combined coverage: full flow/recipe/ECN lifecycle with requalification cascade, plan commit tiers and capacity budget, lot release/split/rejoin/rework, dispatch chamber selection and ranking, ledger arithmetic, metrology classification, Western-Electric run rule, SPC/PARTICLE/DIE_SORT excursions with PROVISIONAL→FINAL severity re-scoring, all three containment scopes, all three dispositions, PM purge window, qualification lapse sweep, die sort/binning/completion, operator revocation, and the envelope/auth/pagination/405 negatives. Three initial mismatches were all incorrect expectations in my own smoke script (capacity already consumed by a completed run; 40.9 vs 40.89 rounding; FINAL DIE_SORT set is same-flow lots only) — no implementation changes were needed.

## Ambiguities resolved (highlights of 28)
Release-rejected flow bumps `revision` on next step append; product-family mismatch placed at validation priority 34; non-author resubmit → `ERR_UNAUTHORIZED`; operator PATCH does field-level authz before state checks (Operator may not set `cert_status`, QualityManager may not set `gown_state`); FAIL/over-limit qualification runs still bump `version` without a state transition; dispatch triage discriminates `ERR_PM_PURGE_ACTIVE` / `ERR_CHAMBER_QUAL_EXPIRED` / `ERR_NO_QUALIFIED_CHAMBER` only when a single reason explains every candidate's rejection; `wafer_results` shape errors → 400 `ERR_VALIDATION` while arithmetic inconsistency (including the empty array) → 422 `ERR_WAFER_RESULT_INCONSISTENT`; `chamber_id` required for CHAMBER and EQUIPMENT containment; PARTICLE excursions end at `version` 2 with `contained_by_user_id` null; null `released_at` cycle-time projection → `ERR_LOT_INVALID_STATE`; `api_request_timestamp` uses real wall clock while all domain timestamps use the logical clock; clock endpoint intentionally unauthenticated; measurement 404 reuses `ERR_STEP_RUN_NOT_FOUND`.

One PRD behaviour worth flagging to whoever writes the tests: a rework rewind deliberately leaves the lot's `OPEN` step run open (spec lists no abort), so the chamber stays `BUSY` until that run is separately aborted — implemented literally as written.

## Step 7: Run tests and iterate — 2026-09-02T11:05:00.000Z

Sweep complete — clean on the first iteration.

**Iterations run:** 1 (single 8-round parallel sweep, `setsid nohup`-wrapped, per-test-server isolation, runner-claimed ports).

**Result:** all 8 rounds `137/137 passed, 0 failed, 0 errors, 0 skipped`. Zero non-passing tests in the union across rounds, so no flakiness signal surfaced and the diagnostic protocol (STEP 0–3) never triggered.

Per-round evidence in `workspace/implementation/results.{1..8}.json`; runner log at `workspace/sweep.log`. Each round took ~1500 s wall clock (the host is heavily CPU-contended; the 8 concurrent rounds took ~25 min total), and no round showed a `Terminated` server log or a synchronized death, i.e. no reaping.

**Tests deleted:** none — no test failed STEP 1a (PRD coverage) or STEP 1b (unique derivability), because no test failed at all.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

Notes:
- The test artifact is 137 tests across 19 files in `test_suite/`, backed by `test_helpers/` (fixtures 1051 lines, factories 480, types 487). Verified there are no `pytest.mark.skip` / `xfail` markers anywhere in `test_suite/` — the only `skip` match is a corner-design name inside a docstring (`test_12_calculations.py:117`), not a marker. So the 137/137 is a genuine full-suite pass, not a partially-skipped one.
- The `results.*.json` files sit inside `workspace/implementation/` because the prescribed sweep command writes them there. They are run artifacts only — the implementation never reads them, and storage remains in-memory (no SQLite, no on-disk dump), so per-test-server restarts still wipe all state.

Orchestrator verification: re-read all 8 results files directly; each reports passed=137, total=137, failed=0, errors=0, skipped=0.

## Step 8: Finalize PRD — SKIPPED — 2026-09-02T11:06:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline. Per the skill's Step 8 skip condition, `PRD.md` already determined every behavior the tests exercised, so no `PRD_FINALIZED.md` is produced and Step 9 starts from `PRD.md`. Decision made autonomously (non-interactive run); no subagent spawned.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-09-02T11:20:00.000Z

Source: `workspace/PRD.md` (Step 8 skipped, so no `PRD_FINALIZED.md`). Output: `workspace/PRD_COMPLETED.md`.

**Counts:** PRD.md 465 lines / 79,562 chars → PRD_COMPLETED.md 466 lines / 92,175 chars (+12,613 chars, +1 line — a single new bullet in §2.2). 56 total changes: 49 ambiguity-pins, 7 mismatch-revisions. 0 new sections (29 headings before and after).

**Mismatch-revisions (PRD said something impl does not do)**

- §2.11 / §3.3 — revise — mismatch — over-limit `particle_count` does not error on a qualification run; a `PASS` is accepted `200 OK` and treated exactly as `FAIL` — `routes/equipment.py:183`
- §2.7 (item 21) / §3.9 — revise — mismatch — binning checks run `status` before lot `flow_state`, inverting items 16/21 — `routes/sort.py:135-139`
- §2.12 — revise — mismatch — track-out applies credit+debit as one expression rounded once, not two rounded movements — `routes/production.py:221`
- §3.8 — revise — mismatch — `EQUIPMENT` scope aborts every open run regardless of prior tool state, and disqualifies only the supplied chamber, not "any chamber leaving QUALIFIED" — `services/cascades.py:161-180`
- §3.8 — revise — mismatch — `SCRAP` recomputes the FINAL affected set at disposition time (not the held lots) and also clears `hold_excursion_id` — `routes/excursions.py:107-118`
- §3.8 — revise — mismatch — `root_cause_note` is validated but never persisted — `routes/excursions.py:78`
- §3.9 — revise — mismatch — `premium_target_die`/`standard_target_die` each >= 0, not "sum >= 0" — `routes/sort.py:131`

**Ambiguity-pins (PRD silent)**

- §2.2 — insert — `ERR_NOT_FOUND`/`ERR_METHOD_NOT_ALLOWED`/`ERR_VALIDATION` for unrouted path, bad method, non-object body; empty body = `{}` — `app.py:48-56`, `validate.py:16`
- §2.3 — insert — non-integer `limit`/`offset` -> `ERR_VALIDATION`; empty-string param = absent; filters are exact-equality, empty ignored, bad enum -> `ERR_VALIDATION`, unknown params ignored — `validate.py:137-174`
- §2.3 — insert — `created_at` ties keep creation order (stable sort) — `db.py:57`
- §2.4 — insert — `/_clock/set_current_utc` is exempt from the §2.1 header checks; `data` is exactly `{"current_utc": ...}` — `app.py:35-42`
- §2.5 — insert — `capacity_budget_hours`, `usl`, `lsl`, `ucl`, `lcl` also 2 dp; `particle_limit`, `pm_interval_hours`, `purge_buffer_hours`, `queue_factor` unrounded — `routes/planning.py:52`, `routes/flows.py:389`
- §2.6 — insert — version fields are integers >= 0; bad shape -> `ERR_VALIDATION` at priority 3 — `routes/planning.py:178`
- §2.7 (item 5) — insert — `plan_id`/`chamber_id` added to the FK list; per-endpoint resolution order pinned (lot: `flow_id`->`plan_id`; run: `step_id`->`lot_id`->`operator_id`; measurement: `spc_chart_id`->`step_run_id`; chamber: `equipment_id`->`qualified_recipe_id`) — `routes/planning.py:124`, `routes/production.py:96,262`
- §2.8 — insert — a missing measurement `id` reports `ERR_STEP_RUN_NOT_FOUND` — `routes/production.py:329`
- §2.10 — insert — non-author resubmit -> `ERR_UNAUTHORIZED`, checked before `status` — `routes/flows.py:296`
- §3.1 — insert — `revision` bumps on the first append after a rejected release (latch consumed/cleared) — `routes/flows.py:111-113,130`
- §3.1 — insert — `rework_target_step_id` need only resolve; no same-flow/earlier-sequence check — `routes/flows.py:90`
- §3.1 — insert — `supersedes_flow_id` of a different family -> `ERR_PRODUCT_FAMILY_MISMATCH` — `routes/flows.py:135`
- §3.2 — insert — `qual_expiry_days` must be an integer — `routes/flows.py:192`
- §3.2 — insert — authoring not gated on recipe `status`; risk scored from the already-rounded `proposed_target` — `routes/flows.py:233-236`
- §3.2 — insert — `reviewer_comment` validated, not persisted — `routes/flows.py:275`
- §3.2 — insert — implement does not examine recipe `status` first — `routes/flows.py:366`
- §3.3 — insert — chamber set-up checks neither `tool_type` agreement nor recipe `QUALIFIED` — `routes/equipment.py:125-126`
- §3.3 — insert — lapse sweep scope = every tool_type+recipe-matching chamber, before any other filter — `routes/production.py:31-46`
- §3.3 — insert — qualification run is not a resource; response `data` is the `Chamber` — `routes/equipment.py:189`
- §3.3 — insert — `pm_reason` validated, not persisted — `routes/equipment.py:72`
- §3.4 — insert — `week_start_date` parsed/normalised; unparseable -> `ERR_VALIDATION` — `routes/planning.py:35`
- §3.5 — insert — projection gates on non-null `released_at` only (`ERR_LOT_INVALID_STATE`); `data` is the six values alone — `routes/planning.py:322-326`
- §3.6 — insert — operator patch field-level auth (`ERR_UNAUTHORIZED` both ways, before shape); neither field -> `ERR_VALIDATION`; no-op gown still bumps `version` — `routes/equipment.py:251-259`
- §3.6 — insert — `REVOKED`->other -> `ERR_VALIDATION`; `REVOKED`->`REVOKED` no-op — `routes/equipment.py:274`
- §3.6 — insert — `ERR_RECIPE_RESTRICTED` runs at priority 25, ahead of the operator/step checks the paragraph lists first — `routes/production.py:110`
- §3.6 — insert — empty-candidate error precedence is per-chamber sole reason: purge-only -> `ERR_PM_PURGE_ACTIVE`, lapse-only -> `ERR_CHAMBER_QUAL_EXPIRED`, else `ERR_NO_QUALIFIED_CHAMBER` (incl. multi-reason and empty base set) — `routes/production.py:69-76`
- §3.6 — insert — zero/negative qual window -> remaining fraction 0, full 40-point penalty — `calc.py:174-178`
- §3.6 — insert — score/`chamber_code` ties fall back to creation order — `routes/production.py:82`
- §3.6 — insert — tool `version` bumps on track-in either way; a lot already `IN_PROCESS` is untouched — `routes/production.py:156-162`
- §3.6 — insert — `PRODUCTIVE->IDLE` is a second write, so track-out/abort that idles the tool bumps its `version` by 2 — `services/cascades.py:62-66`
- §3.6 — insert — abort does not write the lot row at all — `services/cascades.py:69-87`
- §3.6 — insert — `abort_reason` validated, not persisted — `routes/production.py:241`
- §3.7 — insert — chart limits rounded to 2 dp then ordered (`ERR_VALIDATION` before `step_id` resolution); no `metrology_required` gate at chart creation — `routes/flows.py:389-394`
- §3.7 — insert — every accepted measurement writes count+`last_side` and bumps chart `version` by exactly 1 — `routes/production.py:291-299`
- §3.7 — insert — `particle_reading` is any number, 2 dp; response `data` is the `Chamber`; `version` always bumps — `routes/equipment.py:196-204`
- §3.7 — insert — multiple open runs -> `lot_id` from the earliest-created; PARTICLE excursion is `FINAL` from creation and opens at `version` 2 — `services/cascades.py:201-216`
- §3.8 — insert — `chamber_id` required for `CHAMBER` and `EQUIPMENT` (`ERR_VALIDATION`); ignored-but-resolved for `SPC_CHART`; need not relate to the source — `routes/excursions.py:49-55`
- §3.8 — insert — `SPC_CHART` scope on a `DIE_SORT` excursion fires no cascade yet still succeeds — `services/cascades.py:184-187`
- §3.8 — insert — `CHAMBER` scope aborts + holds even when the chamber was not `QUALIFIED` — `services/cascades.py:147-158`
- §3.8 — insert — rework: hold/disposition/null-`hold_excursion_id` failures are all `ERR_LOT_INVALID_STATE`; no step at `current_step_seq` -> `ERR_REWORK_TARGET_NOT_SET`, which precedes the budget check — `routes/planning.py:286-309`
- §3.8 — insert — split does not examine the parent's `hold_state` — `routes/planning.py:222`
- §3.8 — insert — split child: `priority_class` default `STANDARD`, `rework_count` 0, `released_at`/`completed_at`/`actual_cycle_time_days` all null (hence no projection) — `routes/planning.py:232-249`
- §3.8 — insert — rejoin requires a still-resolvable parent, has no `flow_state` gate, clears `hold_excursion_id`, leaves `completed_at` null — `routes/planning.py:262-276`
- §3.9 — insert — per-element shape = `ERR_VALIDATION` (priority 3) vs arithmetic/empty = `ERR_WAFER_RESULT_INCONSISTENT` (priority 43, after lot state/hold); `wafer_slot` not unique; `wafer_results` recorded verbatim — `routes/sort.py:32-79`
- §3.9 — insert — `actual_cycle_time_days` left null when the lot has no `released_at` — `routes/sort.py:153`
- §4 — insert — qualification-run and particle-reading POSTs return `200 OK` with the `Chamber` — `routes/equipment.py:189,204`

Subagent verification note: every `fail(...)` site across all 14 source files now maps to explicit PRD prose; all replacements were assertion-checked as unique matches; §-structure unchanged.

Orchestrator verification: `workspace/PRD_COMPLETED.md` exists, 466 lines / 92,558 chars, 29 headings (same as PRD.md), ends with the complete error-code table — not truncated.

---

# Pipeline complete

Steps 1-7 and 9 ran; Step 8 skipped per its documented skip condition. Final state: 137/137 tests passing in all 8 rounds of the stability sweep, `workspace/PRD_COMPLETED.md` written.
