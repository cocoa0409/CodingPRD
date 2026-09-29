# Worklog — task_2393_new_product_development_stage_gate

## Step 1: Create task directory — 2026-09-02T06:08:00.000Z

Created `tasks/task_2393_new_product_development_stage_gate/` and `tasks/task_2393_new_product_development_stage_gate/workspace/` (directory name pre-allocated by caller; no index scan performed).

## Step 2: Generate scaffold — 2026-09-02T08:35:00.000Z

All three scaffold artifacts are complete and the linter is clean.

Verdict block, verbatim from `python3 skills/prd-bench-scaffold-generator/scaffold_lint.py tasks/task_2393_new_product_development_stage_gate/`:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2393_new_product_development_stage_gate/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2393_new_product_development_stage_gate/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2393_new_product_development_stage_gate/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    69
  §1.1 entities declared:     17
  §1.8 instances scanned:     22
  §1.9 instances scanned:     67
  Calls scanned (§1.8+§1.9):  1232

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2393_new_product_development_stage_gate/`): `SCAFFOLD.yaml` (3360 lines), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1844), `SCAFFOLD_CORNER_DESIGN.yaml` (5185). No sibling task was inspected at any point.

SCAFFOLD.yaml (§1.0–§1.7, neither design key present)
- 17 entities, 10 state machines, 3 concurrency rules, 10 calculations, 44 validations (priorities 1–13), 69 endpoints (38 POST / 31 GET), 67 errors, 7 opaque roles (PortfolioAdmin, InnovationLead, GateChair, FunctionalReviewer, RegulatoryApprover, RnDLead, SalesAccountManager).
- Profile: workflow_orchestration + multi_party_negotiation, branching state machines, graph topology, segregation-of-duties role model, immediate consistency; complexity layers: optimistic concurrency, cascading side effects, dual-variant calculation, derived-field reconciliation.

SCAFFOLD_DIFFICULTY_DESIGN.yaml — 9 rule_ids / 22 instances
dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2.

SCAFFOLD_CORNER_DESIGN.yaml — 9 sections / 92 instances (67 full recipes, 25 stubs)
entities 12 (12 full), state_machines 15 (8/7), calculations 18 (10/8), validations 10 (7/3), endpoints 5 (5/0), errors 18 (13/5), rbac 5 (5/0), cross-cutting complexity layers 5 (5/0), consistency model 4 (2/2). All instance names unique across both design files; every stub cites an existing `rule_id / instance_name` and carries no `test_recipe`.

Final fixes applied this pass
1. FK reverse-reachability (8 violations): the linter only recognises the sub-resource form when the parent placeholder is literally `{id}`, so all nested-path parent placeholders were normalised (`{project_id}/` → `{id}/`, etc.) across all three files — 272 + 5 + 17 occurrences, all verified to be path contexts only. Item-GET paths keep their named ids (`GET /innovation-projects/{project_id}`), which is what the segment-derivation heuristic needs.
2. Added the missing required `resolution_note` to the `clear-conditions` payload in `err_conditions_window_swaps_at_the_due_instant`.
3. Reworded `xc_pagination_defaults_and_bounds_on_a_twelve_row_child_list` to match the endpoint's declared order (fielded_at descending, created_at ascending) instead of the incorrect "created_at ASC"; the setup already created rows in descending fielded_at, so the concrete page assertions stayed valid and now name `${pg_ct11_id}`/`${pg_ct12_id}`/`${pg_ct1_id}` explicitly.
4. Removed the last forbidden-vocabulary hit ("runs in parallel" in a §1.0 comment).
5. Audit: all 67 error ids are referenced by at least one design instance; no duplicate instance names; no stub carries a test recipe.

## Step 3: Copy shared files — 2026-09-02T08:36:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2393_new_product_development_stage_gate/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T08:53:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2393_new_product_development_stage_gate/workspace/PRD.md`.

**Size:** 507 lines. Generated from `SCAFFOLD.yaml` only; neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced, and no sibling task directory was read.

**Sections covered**

- **§1 Introduction** — 3 paragraphs; frames the CPG stage-gate domain, the dual independent status tracks, segregation of duties over opaque actors, and the logical clock.
- **§2 Global Specifications** — 12 subsections: 2.1 Actors/Authentication/Segregation of Duties, 2.2 API Response Structure (pasted verbatim from `section-2.2-response-structure.md`, diff-verified), 2.3 Pagination and List Ordering, 2.4 Resource Identity/Audit Fields/Logical Clock, 2.5 Order of Rejection (all 13 priority bands), 2.6 Optimistic Concurrency, 2.7 Numeric Precision and Rounding, 2.8 The Two Status Tracks, 2.9 Cascade Discipline, 2.10 Development Budget Ledger, 2.11 Cross-Aggregate Referential Integrity, 2.12 Enumerations of Record.
- **§3 Business Logic & Workflows** — 9 subsections: portfolio config + intake; gate-1 screening; concept testing; business cases/forecasts/financials; deliverable checklist; gate reviews (four-way close branch); formulation/pilot/stability/label; sell-in and reset windows; launch readiness/lock/launch/post-launch.
- **§4 Endpoint Definitions** — intro paragraph on 201-vs-200, then a 4-column table (Method, Path, Description, Authorized Role(s)) with all 69 endpoints.
- **§5 Error Code Catalogue** — 2-column table with all 67 error codes. Document ends here; no audit footer.

**Coverage audit**

- **Contract 1 (field-name coverage) — PASS.** Pass A: all 166 `entities[].fields[].name` identifiers appear verbatim in backticks (0 missing). Pass B: all 98 distinct endpoint `input`/`query_params`/`path_params` identifiers appear in backticks (0 missing).
- **Contract 2 (rule coverage) — PASS.** All 72 state-machine transitions across the 10 machines are expressed with preconditions bound to their `error_id` and their side effects (16 are written as grouped from-sets, e.g. "to `KILLED` from either `SCREENED` or `PILOT_QUALIFIED`", rather than as arrow pairs). All 10 calculations are reproduced with every pinned constant and rounding step; no scaffold worked-example numbers were copied. All 44 validations are represented, all 67 error codes are now explained in prose (not just tabulated), and all 7 multi-endpoint `applies_to` sets are stated in full. The 3 OCC rules are framed purely as stale-version reads. Sibling symmetry preserved, including the deliberate asymmetry that the kill cascade withdraws `ACCEPTED` presentations and unwinds ACV while the discontinue cascade does not.
- **Contract 3 (§3 path purity) — PASS.** Zero backticked tokens in §3 start with `/`, are a bare HTTP method, or combine method+path; endpoints are named via state-transition framing, role+verb, or capability description.

**Cross-checks against the scaffold:** endpoint table matches all 69 method+path pairs exactly (no extras, none missing); role authorization matches on all 69 rows (0 mismatches); all 67 error IDs match their HTTP statuses; all 20 declared list orderings (including the stage-gate list's `created_at` descending exception) match. No fuzzy hedging words and no pseudocode or operator syntax present.

One scaffold inconsistency resolved by the skill's fixed contract: `validations[]` priority 1–2 name the header `X-Role`, but the PRD uses the mandated `X-User-ID` / `X-User-Role` pair throughout.

## Step 5: Generate unit tests — 2026-09-02T10:10:00.000Z

Test generation is complete and audited.

## Files created

**Infrastructure — `test_helpers/`** (9 files): `__init__.py` (barrel), `api_client.py` (69 endpoint methods over `GenericApiClient`), `api_errors.py` (error→status map registered at import), `assertions.py` (17 per-entity shape assertions plus the ledger and attainment invariants), `constants.py`, `factories.py`, `fixtures.py` (three tiers: primitives → project skeletons → ledger/lock targeting), `test_users.py` (seven role header builders), `types.py`. Plus `test_suite/conftest.py` (session `api` fixture + seven role-header fixtures).

**Tests — `test_suite/`**: 21 files, **178 tests**.
- Queue A (depth, `test_01`–`test_08`): **53 tests** — `test_01_idea_screening_score.py`, `test_02_business_case_financials.py`, `test_03_pilot_scale_up_and_line_booking.py`, `test_04_dev_budget_and_version_precedence.py`, `test_05_label_clearance_and_checklist_cycle.py`, `test_06_gate_review_outcomes.py`, `test_07_sell_in_and_reset_windows.py`, `test_08_launch_lock_and_post_launch.py`.
- Queue B (breadth, `test_09`–`test_21`): **125 tests** across entities/endpoints (25), state machines + consistency model (17), calculations + cross-cutting layers (27), validations + RBAC (19), error ladders (37).

## Coverage

- **Queue A: 22/22 difficulty instances, every one at ≥2 tests** (53 tests; no tag resolves outside the index).
- **Queue B: 67/67 non-stub corner instances, every one at ≥1 test** (125 tests). The 25 `excluded_because:` stubs produced no tests; all 25 `difficulty_instance` cross-references were checked and resolve to real difficulty instances.
- **Instances skipped: none.** No test is weakened, marked skip/xfail, or left as a placeholder.

## Audit results

- Every test docstring ends with exactly one `Design:` line; no untagged, dual-tagged or dangling tags (checked by AST over all 178 tests).
- All **267** quoted PRD spans are verbatim substrings of `workspace/PRD.md` (whitespace-normalised literal match, 0 misses).
- All files compile; every `test_helpers` import resolves; no duplicate test names; no module-level runtime calls; no `skip`/`skipif`/`xfail`, no `requests`, no server lifecycle handling, no occurrence of "scaffold"; >=5 tests per file.

## Sub-claims dropped (instance still covered), all PRD-driven

- Design recipes that hand-create checklist items a passing gate close auto-creates were re-routed through the auto-created items (otherwise `ERR_DUPLICATE_DELIVERABLE_TYPE`); studies are opened only against `PILOT_PASSED` formulations per §3.7.
- `err_sell_in_ladder_...`: the claim that withdrawing an `ACCEPTED` presentation answers `ERR_PRESENTATION_INVALID_STATE` contradicts §3.8, which permits it and bars withdrawal only from `SHIPPED` — that assertion was omitted.
- `rbac_segregation_of_duties_...`: the design's "422" for `ERR_QUORUM_NOT_MET` contradicts §3.6/§5 (409); the test asserts 409.
- Checklist "declared array order", strict `updated_at > created_at`, exact `earliest_lockable_date` strings, and the HTTP status of a timepoint append are not uniquely derivable from the PRD, so those assertions were replaced by the derivable form (type lookup + `total_count`, prefix match, body identity).
- No `validate_error_is_one_of` fallbacks were needed: every asserted refusal is pinned by §2.5's thirteen bands or an explicit intra-section ordering sentence.
- One design lead-time literal was corrected: a second presentation booked at `2026-09-21T10:00` against a `2026-10-12` window start violates the 21-whole-day rule, so `test_07` books at `2026-09-15T10:00`.

## Step 6: Generate implementation — 2026-09-02T10:56:00.000Z

Note (orchestrator): Steps 5 and 6 ran sequentially rather than concurrently. Physical isolation was replaced by an explicit hard prohibition in the Step 6 prompt against reading `test_helpers/`, `test_suite/`, either design yaml, or any sibling task; the impl-gen subagent confirmed it built only from INSTRUCTION.md + SCAFFOLD.yaml + PRD.md and wrote its own smoke walk rather than using the test suite.

Implementation complete and verified.

## Files created
All under `workspace/implementation/` (24 files, ~3,660 lines of Python):

**Launcher / deps**
- `start.sh` — `cd`s to its own directory, installs deps only when Flask is *absent* (cheap `importlib.util.find_spec` probe, not a full import), then `exec python3 app.py` on `PORT` (default 10000), bound `0.0.0.0`
- `requirements.txt` — `Flask>=2.2`

**Infrastructure**
- `app.py` — blueprint registration, `ApiError`/`HTTPException`/catch-all handlers (404 → `ERR_NOT_FOUND`, 405 → `ERR_METHOD_NOT_ALLOWED`, unhandled → `ERR_INTERNAL` 500), a WSGI lock middleware that serialises requests so the conserved derived fields stay exact, `threaded=True`, no reloader
- `db.py` — the 17 in-memory store dicts plus insertion-order helpers (`_seq`), `children()`; **nothing is seeded and nothing touches disk**
- `clock.py` — logical clock starting `2026-08-01T00:00:00Z`, moved only by `POST /_clock/set_current_utc`; audit stamps come from the wall clock with a monotonic 1 ms guard
- `response.py` — the `meta`/`response_type`/`data` envelope, `req_`+20-char request ids, list pagination meta, Decimal→float serialisation
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (bands 1–2 before path resolution), role gates, pagination parsing, filtering, multi-key ordering
- `validation.py` — every §2.12 enum, the deliverable/evidence/readiness type tables and owner map, typed field extractors
- `calc.py` — all ten calculations in `Decimal` with ROUND_HALF_UP and the PRD's constants

**Domain services**
- `services/core.py` — row minting/`touch`/`apply` (a derived-field change is itself a write: `updated_at` + `version += 1`), authoritative-case / current-formulation / authoritative-concept-test resolution, the five conserved recomputations (budget ledger, slot count, ACV, best pilot yield, launch readiness), checklist auto-creation, evidence auto-approval, completeness + gate readiness index, and the four cascades (kill, wind-down, recycle step-back, depth-4 supersede)

**Routes (10 blueprints)** — `routes/common.py` (14 band-3 resolvers) plus `config_roots.py` (13 endpoints), `projects.py` (7), `business_cases.py` (5), `deliverables.py` (7), `gate_reviews.py` (9), `formulations.py` (3), `pilots.py` (10), `labels.py` (5), `sellin.py` (6), `launch.py` (4)

## Endpoint count
**69** — confirmed by walking `app.url_map`, matching the PRD/SCAFFOLD tables exactly.

## Boot confirmation
Booted on port 18393 via `start.sh` several times (including kill-and-relaunch cycles, mirroring `--isolation per-test-server`). A self-written 250-line smoke walk (`/tmp/smoke_2393.py`, urllib + JSON, **no test-suite code**) passed clean twice, once on each of two fresh processes, with identical numbers — confirming per-boot determinism and empty stores after restart:

- config roots, duplicate-gate 409, retailer/window/pilot-line creation
- rejection ordering: unauthenticated 401 and wrong-role 403 both beat a bogus path's 404
- project → screen (`screening_score` 85.00, gate-2 checklist auto-created) → concept test → business case (`npv_usd` 14178942.39, `gross_margin_pct` 63.95) + forecast line (auto-approving both gate-2 deliverables)
- gate review open/vote/close: owner-cannot-vote, duplicate-function, quorum, chair-voted-and-closed all fire in band order; PASSED advances to `PILOT_QUALIFIED`, locks the case, and creates the gate-3 checklist
- formulation → pilot run (line conflict 409, budget cap 422, ledger 12000.00, yield 95.00 → `PILOT_PASSED`) → shelf-life study (formulation OCC 412, timepoint ordering 409, PASS → `SHELF_LIFE_CLEARED`) → label approval → readiness deliverables with self-approval 403 → `launch_readiness_pct` 100.00
- gate 3 PASSED → `LAUNCH_READY`; sell-in booking → present (not-due 409) → ACCEPTED (SKU overrun 422) → `AUTHORIZED`, ACV 30.00
- launch lock (outside-window and 45-day lead-time violations, then lock) → launch → post-launch periods (sequence 409, CONTINUE then DISCONTINUE with the wind-down cascade)
- envelope/pagination meta and `limit=0` → `ERR_INVALID_REQUEST`

Note on timing: on this loaded host a bare `import flask` costs ~10 s (0.45 s CPU) — pure host contention. The `find_spec` probe in `start.sh` avoids paying that twice, bringing a cold boot to ~7.6 s; the app's own import adds under a second. `__pycache__` was cleared, and the only non-`.py` files in the directory are `start.sh` and `requirements.txt` — no database, cache, or JSON artifact is ever written.

## Step 7: Run tests and iterate — 2026-09-02T13:30:00.000Z

Done — clean 8-round parallel sweep, **178/178 in all 8 rounds**.

### Iterations run
2. Iteration 1: 176/178 in all 8 rounds — the *same* 2 failures in every round (no flakiness; the extra `FAILED` lines visible in the interleaved sweep log were the runner's own retries, and all resolved on retry under load). Iteration 2 after fixes: 178/178 × 8.

### Tests deleted
None. Both failures survived STEP 1a (verbatim PRD coverage) and STEP 1b (unique derivability), and both fixtures were PRD-faithful, so both were real implementation bugs (STEP 3).

### Fixes applied to `test_helpers/`
None — no fixture, factory, or role-header helper was inconsistent with the PRD.

### Fixes applied to `implementation/`

1. **`clock.py`** — added `audit_stamp()`; **`services/core.py`** (`new_row`, `touch`) now stamp `created_at`/`updated_at` from the **logical clock** instead of host wall time.
   *Why:* PRD §2.4 states categorically "**Time is not read from the host.**", in the section titled "Resource Identity, **Audit Fields** and the Logical Clock". Corroborating: §2.6's "Where any ordering fallback is needed among rows sharing a timestamp…" is dead letter under a monotonic-ms wall clock (no two rows can ever share a stamp) and only meaningful if `created_at` is logical. `api_request_timestamp` (§2.2, which never says "current instant") was deliberately left on the wall clock.
   Failing test: `test_the_logical_clock_is_the_only_source_of_now` — got `2026-09-02T13:00:52.805Z` where the clock stood at `2026-08-03T00:00:00Z`.

2. **`routes/config_roots.py`** (`list_stage_gates`) — stage-gate ordering key changed from `created_at` DESC to `(created_at, _seq)` DESC.
   *Why:* consequence of fix 1. Logical-clock stamps make `created_at` ties the norm, and a stable descending sort would have returned tied rows in *ascending* insertion order, contradicting §2.3's "ordered by `created_at` **descending** — newest configuration first". `id` is still never an ordering key. (Verified the other tie-broken lists are unaffected: `db.children`/`M.order` already base on the insertion ordinal, which is exactly the `created_at` ASC sense the other exceptions in §2.3 require; checklist items' `deliverable_type` ASC tie-break now actually engages, as §2.3 specifies.)

3. **`routes/business_cases.py`** (`create_forecast_line`) — the line's `line_units` / `line_revenue_usd` are now computed *into the insert* rather than written by the subsequent `recompute_case` pass, so the newly minted row is not touched by its own creating request.
   *Why:* PRD §2.4 — "`version` is an integer that **starts at 1 on insert**"; and §2.4's exhaustive derived-field-maintenance list (project fields, `booked_slot_count`, `best_pilot_yield_pct`) does not include forecast-line fields. `recompute_case` is now a no-op against that line.
   Failing test: `test_every_row_creating_call_answers_201_with_its_audit_fields` — "the forecast line row starts at version 1", `assert 2 == 1`.

### Orchestrator note
The Step 7 subagent ran its sweeps without `--results-file`, so the required `results.{1..8}.json` artifacts were absent on exit. Its green claim was independently verified against `workspace/sweep.log`, which contains exactly 8 × `Results: 178/178 passed, 0 failed, 0 errors, 0 skipped` and 8 × `178 passed in ...` pytest summaries. The orchestrator then re-ran the identical 8-round sweep under `setsid` **with** `--results-file` to materialise the artifacts and re-confirm the result; see `workspace/sweep_final.log`.

### Orchestrator verification sweeps (Step 7 confirmation)

Sweep A (`workspace/sweep_final.log`, 13:31–13:43): rounds 1,3,5,6,7 = 178/178; rounds 2,4,8 = 177/178. All three failures were connection-level — `RemoteDisconnected` / `ConnectionResetError(104)` — on three *different* tests in `test_08_launch_lock_and_post_launch.py`
(`test_the_two_attainment_bases_coincide_in_the_first_period`, `test_the_trailing_basis_reaches_the_harsher_verdict_on_the_same_numbers`, `test_superseding_a_revision_invalidates_the_label_that_cleared_it`), each of which passed in the other seven rounds. Diagnosed as load-induced, not an implementation defect, on this evidence: the sweep log contains bare `Killed` lines against pytest *collection* processes (`collecting ... Killed`) — the OOM/kill-9 signature, not the `Terminated` reaping signature — the host carried 188 concurrent runner processes at a 15-min load average of 67.6, and none of the three endpoints has timing logic. Per the skill's contention guidance, no code was changed; the sweep was re-run instead.

Sweep B (`workspace/sweep_final2.log`, 13:44–13:52, host load average down to ~40): **all 8 rounds 178/178, 0 failed, 0 errors, 0 skipped.** `results.{1..8}.json` in `workspace/implementation/` are from this sweep. Step 7 is complete with zero further fixes beyond the three the fix subagent applied.

## Step 8: Finalize PRD — 2026-09-02T13:59:00.000Z

Done. `PRD_FINALIZED.md` written with 5 in-place revisions, all traceable to the three `<step_7_diff>` implementation fixes.

### Line counts
- `PRD.md`: 507 lines; `PRD_FINALIZED.md`: 507 lines (0.00% line delta — every change is an in-place sentence revision, no new sections/lines).

### Changes
- **§2.4 (logical clock paragraph)** — insert — audit stamps `created_at`/`updated_at` are minted from the logical instant (shared stamps when the clock stands still; clock moves never recompute a stored stamp), and `api_request_timestamp` is the one timestamp taken from the host clock — `implementation/clock.py:126` (`audit_stamp`), `implementation/services/core.py:39,51`, `implementation/response.py:22`.
- **§2.3 (default ordering sentence)** — revise — ties on `created_at` are the norm under logical-clock stamps, so a list with no other declared key is returned in creation (insertion) order regardless of what the clock did between writes — `implementation/middleware.py:108-118` (`order` with empty keys → `_seq` ASC), `implementation/db.py:72-79`.
- **§2.3 (stage-gate bullet)** — insert — configurations sharing a `created_at` are returned newest-created first, so the descending list reads in exact reverse creation order — `implementation/routes/config_roots.py:79`.
- **§2.6 (ordering-fallback sentence)** — revise — generic tie-break is creation order, earlier-created first, with the descending stage-gate list of §2.3 as the sole reversed exception; `id` still never a tie-break — `implementation/routes/config_roots.py:79`, `implementation/middleware.py:115`, `implementation/services/core.py:133-160`.
- **§3.4 (Volume and gross revenue)** — insert — `line_units`/`line_revenue_usd` belong to the forecast line's own insert, so the created line is returned at `version` 1 and the case recomputation rewrites no line — `implementation/routes/business_cases.py:132-137`, `implementation/services/core.py:376-380` (`recompute_case` → `apply` no-op).

### Per-edit pre-edit search log
1. **§2.4 audit stamps.** (a) Subject: source of every stored timestamp and of the envelope stamp. (b) Enumerated: `services/core.py new_row/touch/apply` (the only writers of `created_at`/`updated_at`/`version` — grepped repo-wide, no other assignment site), `clock.py stamp/audit_stamp/current_dt/current_raw`, `response.py _meta`, plus logical-clock readers (`routes/gate_reviews.py:232,242,274,286,312,339`, `routes/pilots.py:128`, `routes/sellin.py:117`, `routes/launch.py:61,93`, `routes/projects.py:93`). (c) Adjustment: scoped the claim to `created_at`/`updated_at` and explicitly carved out `api_request_timestamp` as host-sourced; deliberately did **not** claim anything about `current_utc` echoing or the monotonic 1 ms guard in `stamp()` (neither is a step-7 site, and a universal "no host time anywhere" claim would have mis-described `response.py:22`).
2. **§2.3 default ordering.** (a) Subject: what the unqualified list order actually sorts on. (b) Enumerated every `M.order` callsite (`config_roots.py:79,119,164,209`, `projects.py:77,182`, `business_cases.py:88,149`, `deliverables.py:104`, `gate_reviews.py:71,167`, `formulations.py:64`, `pilots.py:102,247`, `labels.py:52`, `sellin.py:97`, `launch.py:177`) plus `middleware.order`/`db.rows`. (c) Adjustment: restricted the "creation order" claim to lists *with no other declared key* — `deliverables.py:104` genuinely sorts on the `created_at` string as its primary key, so a blanket "all lists are in insertion order" would have been a new mismatch; the checklist-items bullet is left verbatim.
3. **§2.3 stage-gate bullet.** (a) Subject: ordering of stage-gate configurations. (b) Enumerated: `config_roots.py:70-81` (the only stage-gate list), and the other stage-gate selectors that could have been implicated — `services/core.py:224` `gate_for` (unique `(category, gate_number)` pair, insertion scan) and `services/core.py:232` `commercialization_gate` (lowest `gate_number`, not creation-ordered). (c) Adjustment: confined the sentence to the *list endpoint's* tie direction so it says nothing about how `gate_for`/`commercialization_gate` pick a gate.
4. **§2.6 fallback.** (a) Subject: the system-wide tie-break rule among equal timestamps. (b) Enumerated: `middleware.order` (stable sort seeded on `_seq`), `config_roots.py:79` (the one reversed tie), `services/core.py:133` `authoritative_case` (creation-order last), `services/core.py:151` `authoritative_concept_test` (creation-order first among `fielded_at` ties), `services/core.py:139` `current_formulation` (revision, no timestamp tie), `deliverables.py:104`. (c) Adjustment: phrased as "creation order, earlier-created row first" (rather than "`created_at` ascending", which is vacuous under ties) and named the stage-gate list as the single reversed case, so both `authoritative_case`'s "last taken" and the concept-test "earliest created" remain correct readings.
5. **§3.4 forecast line.** (a) Subject: when a forecast line's derived figures are written and what its `version` is. (b) Enumerated: `routes/business_cases.py:99-142` (create), `services/core.py:376-395` `recompute_case` (writes line figures through `apply`, which touches only on real change), `calc.forecast_line_figures`, `routes/business_cases.py:145-151` (read), and §2.4's derived-field list (project fields, `booked_slot_count`, `best_pilot_yield_pct` — no line fields); grepped `forecast_lines` for any other writer — none. (c) Adjustment: added the reason a line's figures never move later (its inputs are immutable) instead of asserting "forecast lines are immutable rows", and left out any general "a no-op recomputation is not a write" claim, which would have contradicted the unconditional parent touches at `routes/business_cases.py:78` and `routes/pilots.py:90,237`.

## Step 9: Complete PRD — 2026-09-02T14:20:00.000Z

Done. `PRD_COMPLETED.md` is in place at `workspace/PRD_COMPLETED.md`.

### Size
| | Source (`PRD_FINALIZED.md`) | `PRD_COMPLETED.md` |
|---|---|---|
| Lines | 507 | 507 |
| Chars | 89,071 | 104,516 |

Char delta **+15,445**; 52 lines touched, 0 lines added or removed, 0 new sections, 0 new paragraphs (every change is an in-paragraph insert or in-place revision).

### Counts
- **ambiguity-pins: 49**
- **mismatch-revisions: 8**

### Changes
- §2.1 — insert — ambiguity — `X-Role` accepted as a synonym for `X-User-Role`, consulted only when the latter is absent or empty; an empty header string counts as absent — `middleware.py:27`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset`, negative `offset`, out-of-range `limit` all answer `ERR_INVALID_REQUEST` at band 4, so a bad `limit` on an unresolvable path still reports 404 first — `middleware.py:52`
- §2.3 — insert — ambiguity — filter comparison semantics (stored int compared numerically, stored null matches `""`/`null`/`None`, else string equality), unknown query params ignored, and the four collections that accept no filters at all — `middleware.py:80,92`; `business_cases.py:149`; `gate_reviews.py:167`; `projects.py:181`; `launch.py:177`
- §2.4 — insert — ambiguity — a write landing on values already stored is not a write: `updated_at`/`version` stay untouched, with the two unconditional-touch exceptions named — `core.py:56`
- §2.4 — revise — ambiguity — clock setter's `data` is `{"current_utc": …}` echoing the supplied value verbatim, carrying no `id`, stamps or `version` — `config_roots.py:24`
- §2.4 — insert — ambiguity — only `created_at`/`updated_at` are clock-minted with three fractional digits; every client instant is echoed byte-for-byte in the form sent (bare dates and offsets accepted); `closed_at` is the raw string the clock setter last supplied — `clock.py:39,111,126`
- §2.6 — insert — ambiguity — opening a business case unconditionally increments the project's `version` although no project field changes — `business_cases.py:78`
- §2.6 — insert — ambiguity — a new formulation revision does *not* touch the project for its own sake; the project moves only if the cascade rewrites a project field — `formulations.py:39`; `core.py:456`
- §2.7 — insert — ambiguity — client numbers are round-half-up normalised on ingest at the field's declared scale, after range checks, and the normalised value is what is stored and computed with — `validation.py:139`
- §2.8 — insert — ambiguity — the admitted-set list is exhaustive; every operation not named imposes no track precondition (terminal states included), the sole extra bar being checklist submission's `ERR_DELIVERABLE_INVALID_STATE` — `deliverables.py:131`
- §3.1 — insert — ambiguity — stage-gate field bounds, `veto_functions` not de-duplicated, no cross-consistency between `stage_from`/`stage_to`/`gate_number`, and two gates of one category may both declare `stage_to` `LAUNCH_READY` — `config_roots.py:36`
- §3.1 — insert — ambiguity — retailer / reset-window / pilot-line field bounds, exact-string duplicate matching, and `window_end <= window_start` as a shape violation — `config_roots.py:97,141,182`
- §3.1 — insert — ambiguity — project `idea_description` is an unbounded non-empty string with no uniqueness rule — `projects.py:24`
- §3.2 — insert — ambiguity — the screening `rationale` is validated as a string and then discarded, not stored — `projects.py:107`
- §3.4 — insert — ambiguity — all eight business-case fields are required whatever the `variant_mode`, with their ranges — `business_cases.py:38`
- §3.4 — **revise — mismatch** — opening a case supersedes *every* prior non-terminal case, not just the previous one, and `case_type` counts every prior case including already-`SUPERSEDED` ones — `business_cases.py:56,74`
- §3.4 — insert — ambiguity — forecast-line field ranges (`store_count` whole >=0, velocity/lift >=`0.00`, price >=`0.0000` at 4dp) — `business_cases.py:105`
- §3.4 — insert — ambiguity — `avg_list_price_usd` is `0.0000` by definition when the summed `store_count` is zero, not a division error — `calc.py:139`
- §3.4 — insert — ambiguity — the auto-approval sweep runs on *every* accepted forecast line, and touches only `PENDING` items — `business_cases.py:137`; `core.py:279`
- §3.5 — insert — ambiguity — a manually created checklist item needs only an existing gate (no category, next-gate or `required_deliverable_types` binding) and stores the supplied `owner_function` as given — `deliverables.py:45`
- §3.5 — revise — ambiguity — "live" in the duplicate check means any status other than `CANCELLED`, enumerated explicitly — `deliverables.py:16,72`
- §3.5 — insert/revise — ambiguity — prerequisites resolve against the whole checklist store (a cross-project edge resolves happily), re-pointing has no state precondition, and re-asserting the same edge is a no-op — `deliverables.py:200`
- §3.5 — insert — ambiguity — submission field shapes and the ordering of the item-status bar before the project-terminal bar — `deliverables.py:120,131`
- §3.5 — insert — ambiguity — `decision` is exactly `APPROVE` or `REJECT`; `comment` <=1000 chars is validated then discarded — `deliverables.py:159`
- §3.5 — insert — ambiguity — waiver `reason` is a required 1–500 char string, validated not stored — `deliverables.py:187`
- §3.6 — insert — ambiguity — a scheduled review's gate need only exist (no category/next-gate binding), and any number of `SCHEDULED` reviews may coexist — `gate_reviews.py:20`
- §3.6 — insert — ambiguity — opening checks the review's own `SCHEDULED` status before the parent project's state — `gate_reviews.py:88`
- §3.6 — insert — ambiguity — ballot `rationale` <=1000 chars *is* stored (null when omitted), and the seat named bears no relation to the caller's role or the veto list — `gate_reviews.py:120`
- §3.6 — insert — ambiguity — `conditions` <=2000 chars, both condition fields optional at the shape band and tested for substance only once the branch is known — `gate_reviews.py:200`
- §3.6 — insert — ambiguity — the `CONDITIONAL_PASS` shape checks run in a stated order, after chair and quorum, ahead of the three 422 bars — `gate_reviews.py:228`
- §3.6 — insert — ambiguity — the other three branches ignore `conditions`/`conditions_due_at` entirely (neither validated nor stored); `closed_at` uses the raw clock form; `status` and `decision` always agree — `gate_reviews.py:214`
- §3.6 — **revise — mismatch** — the `PILOT_QUALIFIED -> LAUNCH_READY` passing close also runs the checklist auto-creation attempt (normally finding nothing) before recomputing readiness — `gate_reviews.py:_advance`; `core.py:272`
- §3.6 — insert — ambiguity — the authoritative case is promoted to `LOCKED` only from `COMPUTED`; a `DRAFT` case stays `DRAFT` and a caseless project simply locks nothing — `gate_reviews.py:_advance`
- §3.6 — **revise — mismatch** — recycle re-creation follows the same existence-and-`stage_from` rule and skips pairs that still exist, so it normally mints nothing; it also runs on the `SCREENED` self-loop — `core.py:272,438`
- §3.6 — insert — ambiguity — the kill cascade excludes the closing review by identity, which keeps the `KILLED` status the close gave it — `core.py:412`
- §3.6 — insert — ambiguity — `resolution_note` 1–2000 chars not stored; clearing re-tests only checklist completeness and leaves the frozen figures, `dev_status` and `next_gate_number` alone; expiry takes an empty body and can never fire on a null `conditions_due_at` — `gate_reviews.py:304,323,328`
- §3.7 — insert — ambiguity — formulation field shapes, and `revision` counting every revision the project has ever had (superseded included) with no reuse — `formulations.py:39`
- §3.7 — insert — ambiguity — `end_at <= start_at` is a shape violation raised before `pilot_line_id` is resolved; cost floor; only a `SUPERSEDED` formulation bars a booking — `pilots.py:33,47`
- §3.7 — insert — ambiguity — `effective_buffer_minutes` is stored on and returned with the run, and each side of the overlap comparison uses its own stored buffer — `pilots.py:22,81`
- §3.7 — insert — ambiguity — completion and cancellation impose no formulation-status condition (only starting does), cancellation's `reason` is discarded, `PILOT_PASSED` is reached only from `DRAFT`/`PILOT_FAILED`, ledger and best-yield refresh on every success, and a below-floor yield never demotes an already-passed formulation — `pilots.py:90,125`
- §3.7 — **revise — mismatch** — opening a stability study does *not* require `PILOT_PASSED`; the only bar is that the formulation not be `SUPERSEDED`, and `start_at` is never compared against the clock — `pilots.py:200,209`
- §3.7 — insert — ambiguity — timepoint `day_index` is a whole number >=0 (day 0 legal) and `quality_score` lies in `0.00`–`100.00` — `pilots.py:263`
- §3.7 — insert — ambiguity — `SHELF_LIFE_CLEARED` is reached only from `PILOT_PASSED`; the study still closes `PASSED` either way — `pilots.py:286`
- §3.7 — insert — ambiguity — a label draft's `label_version` is 1–40 chars, any revision status may be described, and multiple drafts may name one revision — `labels.py:19,24`
- §3.7 — insert — ambiguity — decide's `comment` <=1000 chars is not stored, and a supplied `unsupported_claims` is stored verbatim on the `APPROVE`/`REJECT` branches too, while omitting it leaves the existing list — `labels.py:90,107`
- §3.7 — **revise — mismatch** — the supersede cascade clears only `evidence_url` on the `REGULATORY_CLEARANCE` item, and levels three and four run only when level two actually invalidated a label — `core.py:468`
- §3.8 — **revise — mismatch** — full bookable-state matrix, and `commercial_status` is rewritten to `SELL_IN_SCHEDULED` only out of `NOT_STARTED`/`SELL_IN_REJECTED`; later bookings leave the track where it stood — `sellin.py:35,83`
- §3.8 — insert — ambiguity — the present transition writes the project only when the track stands at exactly `SELL_IN_SCHEDULED` — `sellin.py:122`
- §3.8 — insert — ambiguity — `accepted_sku_count` is a whole number >=0 and its absence on the `ACCEPTED` branch answers `ERR_INVALID_REQUEST` (400) *after* the presentation's state check — `sellin.py:134,144`
- §3.8 — insert — ambiguity — withdrawal `reason` is required, <=500 chars, stored nowhere; the `SHIPPED` bar applies only when the withdrawn row is itself `ACCEPTED` — `sellin.py:180,186`
- §3.9 — **revise — mismatch** — the commercialisation gate is the *lowest*-`gate_number` gate of the project's category whose `stage_to` is `LAUNCH_READY`; a category with none yields an empty required set — `core.py:232`
- §3.9 — **revise — mismatch** — dropped "or waived": waiving a readiness item performs no recomputation and leaves `launch_readiness_pct`, `updated_at` and `version` untouched; recomputation covers reviewer approval, auto-approval, the `LAUNCH_READY` close and the label cascade's lock slip — `deliverables.py:196`; `core.py:291,329`
- §3.9 — **revise — mismatch** — `blocking_deliverable_types` follows the commercialisation gate's own `required_deliverable_types` array order, not weight order nor mint order; `launch_date` is null while unlocked — `core.py:313`; `projects.py:94`
- §3.9 — insert — ambiguity — a slipped readiness figure at launch answers `ERR_LAUNCH_READINESS_INCOMPLETE` (422) after the date check — `launch.py:93`
- §3.9 — insert — ambiguity — post-launch field ranges, with `actual_gross_margin_usd` alone unbounded below — `launch.py:113`
- §3.9 — insert — ambiguity — a `plan_units_per_period` of `0.00` yields both attainments at `0.00` rather than a division error, hence `DISCONTINUE` — `calc.py:290`
- §4 — insert — ambiguity — an unrouted path answers `ERR_NOT_FOUND` (404) and a wrong method `ERR_METHOD_NOT_ALLOWED` (405), both before authentication; a trailing slash is the same route; the clock setter returns a computed object — `app.py:54,64`

Judgement calls: framework-level errors (404/405) were expressed as §4 prose rather than new rows in the §5 catalogue, to honour "never add new sections". Two paragraphs drafted as standalone additions (§2.8 exhaustiveness, §3.6 branch-field handling) were folded into adjacent paragraphs so the file stays line-for-line aligned with the source.

### Pipeline complete
All nine steps are done. Final state: 21 test files / 178 tests, all passing in 8/8 parallel rounds under `--isolation per-test-server`; `results.{1..8}.json` present in `workspace/implementation/`; `PRD.md` -> `PRD_FINALIZED.md` -> `PRD_COMPLETED.md` all present.
