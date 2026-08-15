# Worklog — task_2013_robotics_integration_cell_commissioning

## Step 1: Create Task Directory — 2026-08-15T06:42:00.000Z

Pre-created by the invoking pipeline run (directory `tasks/task_2013_robotics_integration_cell_commissioning/` + `workspace/`); orchestrator started at Step 2 per invocation instructions.

## Step 2: Generate Scaffold — 2026-08-15T07:16:30.000Z

Scaffold generation complete. All three files were written to `/home/ubuntu/github/CodingPRD/tasks/task_2013_robotics_integration_cell_commissioning/` and the linter reports **clean lint** (verbatim verdict: "VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.").

## Summary

**Files written (all three confirmed):**
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys; split verified)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

**Entity model (14 entities):** IntegratorOrg → CustomerSite → CellProject (root chain) with children ApplicationStudy (self-referential supersedure), SafetyRiskAssessment, RobotSelection, RobotProgram (dual-axis state), AcceptanceTest (FAT/SAT), SparePartsPackage, MaintenancePlan, TrainingSession, ThroughputGuarantee, RetentionLedgerEntry (append-only, `common_fields: false`), IntegratorUser. Hybrid topology; computed fields include `adjusted_cycle_time_s`, `payload_margin_pct`, `safety_function_budget_pct`, `retention_balance_cents`, `hours_until_due`, `forecast_consumption_months`, `shortfall_pct`.

**State machines (9):** CellProject is branching + cyclic (DESIGN→BUILD→FAT→DESIGN and SAT→DESIGN rework loops, ON_HOLD↔prior-state cycle, terminate cascade); ApplicationStudy has a self-referential supersedure cycle; SafetyRiskAssessment has a REJECTED→DRAFT revise loop; RobotProgram has **parallel state dimensions** (dev_status × sim_status, with cycles on each axis and a join at release); AcceptanceTest is a PENDING→{PASS, CONDITIONAL_PASS, FAIL} fork with divergent retention side effects per branch; TrainingSession, ThroughputGuarantee (NOT_STARTED→MEASURING→{MET, MISSED, WAIVED}), MaintenancePlan, RobotSelection complete the set.

**Calculations (7):** `adjusted_cycle_time` (dual-variant: simulated derated vs measured raw), `payload_margin_check` (constraint propagation, ≥3 inputs, conjunctive), `retention_release_schedule` (waterfall 30/40/30 with pinned round-per-step order, residual guarantee bucket), `training_completion_score` (weighted scoring, per-audience weights 0.6/0.4 vs 0.5/0.5 and thresholds 80 vs 85), `spare_parts_consumption_forecast` (decay, dual-variant quoted vs delivered), `safety_function_budget` (threshold with >= boundaries at 9.0/6.0), `throughput_shortfall` (max of two shortfalls, penalty capped at balance).

**Validation rules:** 19, ordered auth → role → existence → state → OCC (412) → safety → segregation-of-duties → constraint → temporal → referential → uniqueness → fiscal → gate. **Endpoints:** 77. **Error catalog:** 19 codes. **Concurrency:** 3 OCC rules on CellProject.version (study-create, advance, ledger-post), all 412 `ERR_STALE_PROJECT_VERSION`.

**RBAC (7 roles, all `entity_backed:IntegratorUser`):** segregation-of-duties model — ProjectEngineer creates but cannot approve; SafetyLead approves but cannot create; ControlsProgrammer authors but cannot peer-review own code; SiteSupervisor runs acceptance tests and stage advances in later phases; Trainer schedules/scores (must score own session); ServiceManager owns spares/maintenance/guarantee close; FinanceAdmin owns org admin, ledger adjustments, waiver, termination, and the logical clock.

**§1.8 difficulty design:** 18 instances, exactly 2 per rule across all nine rules, each with structured `setup_api_calls`/`trigger`/`assert`, placeholder-closed, with literal computed values (e.g. retention 33,300 cents from 999,999 × 333 bps; margin exactly 20.00 passing at >=; 10.000s adjusted cycle from 8.0s @ 80%).

**§1.9 corner design:** 32 entries (28 with test recipes, 4 `excluded_because` stubs referencing §1.8 instances), across 7 sections: entities (6), state_machines (5), calculations (3), validations (7), errors (6), rbac (3), cross_cutting_layers (2). All 50 instance names across both files are unique; all stub references resolve.

**Harder-than-expert elements:** dual-variant calcs in two entity domains, mode-(a) + mode-(b) combinatorial formulas, parallel-axis + cyclic state machines on different entities, a depth-3 SAT-fail cascade (project → assessment supersede + program rework + selection unlock) and a depth-2 site-patch → forecast cascade, two validation-priority conflicts with different category pairs, half-open trainer-interval semantics vs aggregate meter-rollover semantics, and two compensating invariants (retention-money conservation; release/rework counter monotonicity).

## Step 3: Copy Shared Files — 2026-08-15T07:19:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2013_robotics_integration_cell_commissioning/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-15T07:44:00.000Z

The PRD is complete and all checks pass. Final summary:

## Task Complete

**Output written:** `/home/ubuntu/github/CodingPRD/tasks/task_2013_robotics_integration_cell_commissioning/workspace/PRD.md` — 370 lines. The forbidden index files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.

### PRD section list
- **1. Introduction** — 2 paragraphs (integrator business context, cycle-time/retention tension, system scope)
- **2. Global Specifications** — 12 subsections: 2.1 RBAC (headers, 7 roles, per-role entity-backed identity prose), 2.2 API Response Structure (**byte-verbatim** from `section-2.2-response-structure.md`, verified by diff), 2.3 Pagination, 2.4 Common Resource Properties (incl. RetentionLedgerEntry's `id`/`created_at`-only exception), 2.5 Nested Resource Validation, 2.6 Request Evaluation Order (full 19-priority ladder in prose), 2.7 OCC (3 rules, `expected_project_version`, `ERR_STALE_PROJECT_VERSION`/412), 2.8 Retention Ledger, 2.9 Rounding Conventions, 2.10 Logical Clock (default `2026-08-01T00:00:00Z`), 2.11 PL Ordering, 2.12 Cascades
- **3. Business Logic** — 9 subsections by lifecycle stage (org/site/project intake; studies; safety; selection; programs; acceptance/advance gates; parts+maintenance; training; guarantee/termination/closure)
- **4. Endpoint Definitions** — 77-row table, exactly 4 columns (Method, Path, Description, Authorized Role(s))
- **5. Error Code Catalogue** — 19-row table, exactly 2 columns

### Zero-Silence / contract coverage results (scripted, all PASS)

**Contract 1 — Field-Name Coverage:**
- entities[].fields: 89 required, 89 present, 0 missing
- endpoints request_body/input: 71 required, 71 present, 0 missing
- query params: 15 required, 15 present, 0 missing; `limit`/`offset` present
- Enum/state values: 70 required, 0 missing; all 19 error IDs present in §2/§3 prose (not just §5); all 7 role names present

**Contract 2 — Rule Coverage (manual walk over scaffold):**
- Validations with priority: 19 checked, 19 expressed — full ladder in §2.6 plus per-endpoint relative orders (payload-before-brand §3.4; safety-before-segregation §3.3; advance ordering state→OCC→retention→gates §3.6)
- OCC rules: 3/3 expressed with write endpoint + `expected_project_version` + error id + 412
- State-machine transitions: 45 checked, all expressed with preconditions, error pairing, and side effects (incl. both GUARANTEE→CLOSED branches, FAT/SAT rework cascades, termination cascade enumeration, dual-axis RobotProgram cycle)
- Calculations: 7/7 fully in precise prose (adjusted cycle time 3dp + feasibility bands; payload margin ≥20.0; 30/40/residual retention waterfall with pinned step order and CONDITIONAL_PASS halving; 60/40 vs 50/50 training weights with 80/85 thresholds; shift-factor forecast with quoted/delivered variants; PL budget point model with inclusive 9/6 thresholds; shortfall max/min penalty formula)
- Endpoint side effects / applies_to scopes: all expressed (site PATCH re-forecast, study-create version bump, record-computes-but-does-not-post, clock set drives only NO_SHOW, etc.)
- Field structured content (defaults, ranges, initial values): reconstructible from prose; sibling branches (PASS/CONDITIONAL_PASS/FAIL, MET/MISSED/WAIVED) rendered at equal density

**Contract 3 — §3 Path Purity:** 511 backticked tokens scanned; 0 path tokens, 0 bare HTTP methods, 0 method+path combos

**Additional checks:** §2.2 verbatim byte-identical; no fuzzy words ("approximately"/"roughly"/etc.); no pseudocode operators in prose; PRD ends at §5 with no audit footer.

## Step 5: Generate Unit Tests — 2026-08-15T08:20:00.000Z

# Summary

**Generated test infrastructure for `task_2013_robotics_integration_cell_commissioning`**

## test_helpers/ (10 files)
- `/home/ubuntu/github/CodingPRD/tasks/task_2013_robotics_integration_cell_commissioning/test_helpers/__init__.py` — barrel export (framework + PRD-specific)
- `types.py` — 14 entity TypedDicts (RetentionLedgerEntry correctly omits `updated_at`/`version` per PRD §2.4); 14 status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (~50 endpoints covered)
- `api_errors.py` — 19 `ApiErrorId` values + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — `assert_<entity>()` per entity, with PRD-exact field checks
- `factories.py` — payload factories for every entity, input fields only
- `constants.py` — domain thresholds (PL cutoffs, retention %s, pass scores, default clock)
- `test_users.py` — 7 role header builders + shared `TEST_USERS` constants; all roles entity-backed so each has a `make_<role>_headers(user_id)` builder
- `fixtures.py` — tiered composites: `setup_full_project`, `setup_project_in_{study,design,build,fat,ship,sat,training,guarantee}`, plus step-level helpers (`create_and_submit_study`, `approve_assessment`, `create_validated_locked_selection`, `create_released_program`, `run_training_session`, `get_throughput_guarantee_for_project`, etc.)

## test_suite/ (12 files, 63 tests)
- `conftest.py` — session-scoped `api` fixture + one role-header fixture per role
- `test_01_organizations_projects_intake.py` — 6 tests (entities: creation defaults, required fields, 404, pagination envelope, computed field, ledger immutability)
- `test_02_project_state_machine.py` — 5 tests (initial/terminal, hold/resume, terminate cascade, FAT rework cycle, SAT cascade depth-3)
- `test_03_application_studies.py` — 6 tests (dual-variant cycle time, feasibility tiers, SoD, supersede target, OCC on create, state-vs-referential priority)
- `test_04_safety_risk_assessments.py` — 4 tests (PL threshold boundary, muting gate, state-vs-safety priority, reject-revise loop)
- `test_05_robot_selections.py` — 3 tests (margin exactly 20 passes, inertia-over-limit rejects, brand scope)
- `test_06_robot_programs.py` — 3 tests (release requires SIM_PASSED, parallel dev/sim axes, release-revision monotonicity)
- `test_07_acceptance_tests_and_retention.py` — 6 tests (defects 0 vs 1 boundary, retention waterfall pinned rounding, conservation + overrelease, guarantee close window violation, throughput shortfall max)
- `test_08_spare_parts_and_maintenance.py` — 5 tests (quoted-vs-delivered forecast divergence, site shift cascade, package lifecycle, maintenance rolling window + boundary)
- `test_09_training_and_guarantee.py` — 4 tests (trainer half-open adjacency, outside-window rejection, TRAINING→GUARANTEE gate, logical clock default + NO_SHOW)
- `test_10_rbac_and_cross_cutting.py` — 4 tests (SafetyLead denied study create, Trainer denied guarantee close + 401, OCC on advance, DESIGN gate requires APPROVED assessment)
- `test_11_difficulty_second_angles.py` — 16 tests providing the mandatory second test for each queue-A instance

## Per-queue disposition

**Queue A (Difficulty):** 18 instances — **18 translated, 0 skipped**. Every instance has ≥2 tests (the "duplicate" tags in the audit are exactly the 18 instances × 2 tests).

**Queue B (Corner):** 27 non-stub instances — **27 translated, 0 skipped**. 4 `excluded_because:` stubs in the `errors` section correctly not translated (their difficulty-instance pointers resolve: `state_vs_business_safety_on_assessment_approve`, `project_design_advance_requires_approved_assessment`, `payload_margin_multi_input_threshold`, `trainer_double_booking_half_open_adjacency`).

**Skipped categories:** none — every non-stub instance had verbatim PRD coverage that uniquely derived the asserted outcome (PRD §2.6 explicitly pins the validation ladder; §3.2/§3.3/§3.4/§3.5/§3.6/§3.7/§3.8/§3.9 verbatim-state the rules, formulas, and side effects exercised).

## Total test count
**63 tests** (36 queue-A + 27 queue-B), all tagged with exactly one `Design:` line.

## Syntax-check results
- `python3 -m py_compile test_helpers/*.py test_suite/*.py` → ALL_OK
- All 11 test modules import cleanly with `prd_bench_local_runner` on `sys.path` → 11/11 OK
- Docstring audit: 63 tests, 0 untagged, 0 dual-tagged, 45 unique tags, 18 expected duplicate tags (the 18 difficulty instances × 2 tests each)

(Orchestrator note: the Step 5 subagent's first run stopped after planning without writing files; it was resumed via message and completed the generation above.)

## Step 6: Generate Implementation — 2026-08-15T08:45:00.000Z

The implementation is complete and verified. Default-port boot works (401 = auth enforced, server responding on 10000); the exit code is from the cleanup `pkill`.

## Summary

**Task**: `task_2013_robotics_integration_cell_commissioning` — full Python + Flask implementation written to `/home/ubuntu/github/CodingPRD/tasks/task_2013_robotics_integration_cell_commissioning/workspace/implementation/`.

### File list (25 files)
- `start.sh` (executable, guarded `pip install`, `exec python3 app.py`), `requirements.txt` (flask>=3.0)
- `app.py` (entry point, blueprint registration, error handlers, `0.0.0.0:$PORT` default 10000, reloader off)
- `db.py` (empty-per-boot in-memory store + logical clock defaulting to `2026-08-01T00:00:00Z`), `errors.py` (all 19 error IDs), `response.py` (envelope: `meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; list meta `limit`/`offset`/`total_count`/`has_more`), `middleware.py` (`X-User-ID`/`X-User-Role` auth, 7 roles), `validation.py`, `timeutil.py` (ISO-8601 UTC, 3 fractional digits)
- `services/calculations.py` (all 7 calculations, Decimal round-half-up), `services/domain.py` (ledger, cascades, guarantee init, OCC helpers)
- `routes/`: `orgs.py`, `sites.py`, `projects.py`, `studies.py`, `assessments.py`, `selections.py`, `programs.py`, `tests.py`, `packages.py`, `plans.py`, `sessions.py`, `guarantees.py`, `ledger.py`, `clock.py`

### Endpoint coverage
All **77 endpoints** from the scaffold/PRD §4 table implemented, including the three reverse-reachability user listings, `superseded-by`, the 0-or-1 project guarantee fetch, and the FinanceAdmin-only logical clock.

### State machines
All 8 implemented: CellProject (12-state branching lifecycle incl. ON_HOLD/resume with prior-status restore, terminate with atomic compensating PENALTY, FAT/SAT rework cascades bumping `rework_count`), ApplicationStudy (supersede self-cycle with revision+1), SafetyRiskAssessment (REJECTED→DRAFT revise loop; SAT-fail SUPERSEDED + DRAFT shell cascade), RobotSelection (LOCKED↔VALIDATED), RobotProgram (**parallel dev/sim axes** — rework leaves sim untouched), AcceptanceTest (PASS/CONDITIONAL_PASS derivation, record- or fail-triggered rework cascade), TrainingSession (inclusive start window, trainer-scores-own, NO_SHOW sweep on clock set), ThroughputGuarantee (MEASURING→MET/MISSED/WAIVED with project GUARANTEE→CLOSED on zeroed balance), MaintenancePlan (DRAFT/ACTIVE/SUSPENDED/CLOSED).

### Calculations (all Decimal, round-half-up at pinned precision)
adjusted cycle time (3dp) + feasibility bands; payload margin (2dp, ≥20.0% gate); retention waterfall 30/40/residual with CONDITIONAL_PASS halving; training weighted scores (0.6/0.4, 0.5/0.5, 1dp); spare-parts forecast (unit count cancels algebraically to `months*2/shifts`, 1dp; re-derived on deliver and on site shift-count PATCH); safety budget (capped fencing points, muting penalty, inclusive PL thresholds); throughput shortfall (2dp) with min-capped penalty; `hours_until_due` smallest-k remainder.

### Validation ordering
Full §2.6 ladder: 401 → 403 (endpoint + stage-pinned actor) → 404 left-to-right → 409 state → 412 OCC (on study-create/advance/ledger-post) → safety 422 → SoD 422 → payload 422 → brand 422 → windows/conflicts → supersede 422 → duplicate 409 → conservation/balance 422 → 400 field checks → 422 gate preconditions.

### start.sh contract
Confirmed: reads `PORT` (default 10000 verified), binds `0.0.0.0`, foreground via `exec`, guarded dependency install (no-op when flask present). Three consecutive fresh-process boots each served HTTP in ~0.6s with an empty store — safe for `prd-bench-local-run --isolation per-test-server`.

### Verification
Three smoke suites (~130 assertions) run against live boots covering the full happy path (org→site→project→study/assessment→selection→program→FAT→SHIP→SAT→guarantee→training→CLOSED with exact ledger trail), all error IDs, rework/terminate cascades, boundary values (102% conditional-pass edge, 20.0% margin, inclusive session windows, exact training thresholds), OCC staleness, retention mismatch/overrelease, and MISSED/WAIVED settlement math — all passing.

## Step 7: Run Tests and Iterate — 2026-08-15T09:02:00.000Z

All 8 rounds pass 63/63 with an empty failure union — clean sweep. Here is the final summary.

## Summary

**Iterations run:** 2 (iteration 1: 4 stable failures in all 8 rounds; iteration 2: 63/63 × 8 rounds, zero flakiness).

**Tests deleted:** none. All four failures passed STEP 1 (PRD verbatim coverage + unique derivability); every one was a STEP-2 test-side bug where the test's own setup/request was inconsistent with the PRD, causing the PRD-faithful implementation to correctly reject it.

**Fixes applied to `test_helpers/`:** none — the fixtures, factories, and role-header builders were all PRD-consistent; the bugs were in how individual tests used them.

**Fixes applied to `test_suite/`** (3 files, 4 tests):

1. `/home/ubuntu/github/CodingPRD/tasks/task_2013_robotics_integration_cell_commissioning/test_suite/test_08_spare_parts_and_maintenance.py` — `test_maintenance_window_meter_vs_interval_aggregate_capacity`: removed the gratuitous `org_overrides={"brand_specialization": "ABB"}` from the `setup_project_in_sat` call. The setup chain validates a robot selection whose factory-default brand is `FANUC`, so the PRD §3.4 brand-scope rule correctly rejected setup with `ERR_BRAND_OUT_OF_SCOPE`. Org brand is irrelevant to this maintenance-window test.

2. `/home/ubuntu/github/CodingPRD/tasks/task_2013_robotics_integration_cell_commissioning/test_suite/test_09_training_and_guarantee.py` — `test_training_start_outside_window_rejected`: replaced the hand-rolled DRAFT-project setup with `setup_project_in_training(...)`. PRD §3.8 gates session start on the project standing in `TRAINING`, and the §2.6 ladder evaluates `ERR_INVALID_STATE` (priority 4) before `ERR_OUTSIDE_SESSION_WINDOW` (priority 10) — so only a TRAINING-state project can reach the window check the test asserts.

3. `/home/ubuntu/github/CodingPRD/tasks/task_2013_robotics_integration_cell_commissioning/test_suite/test_11_difficulty_second_angles.py` — `test_project_rework_cycle_design_fat_design_second_pass`: replaced the `move_project_to_build(...)` call with a direct `advance_project(...)`. The test had already re-released the existing program in place, so the helper's creation of a *new* program with the default name `MAIN` collided with the existing one (`ERR_DUPLICATE_CODE` per PRD §3.5's program-name uniqueness). Also added `advance_project` to the module import list and dropped the now-unneeded `move_project_to_build` local import.

4. Same file — `test_retention_ledger_conservation_across_milestones_full_cycle`: added the missing `setup_project_in_guarantee` import (NameError at setup; the helper existed and was exported via `fixtures.py`'s star export, just never imported by the test module).

**Fixes applied to `implementation/`:** none — the implementation was PRD-faithful in every failing case (brand scope, state-before-window priority, program-name uniqueness were all correctly enforced).

Final state: 63 tests, 0 deletions, 8/8 clean rounds.

## Step 8: Finalize PRD — 2026-08-15T09:10:00.000Z

Done. `PRD_FINALIZED.md` exists at `/home/ubuntu/github/CodingPRD/tasks/task_2013_robotics_integration_cell_commissioning/workspace/PRD_FINALIZED.md` and is **byte-identical to PRD.md** — the explicitly-valid zero-edit outcome.

## Summary

**Line counts / delta:** PRD.md = 370 lines, PRD_FINALIZED.md = 370 lines, 0% delta (diff confirms byte-identity).

**Changes:** none. All four Step 7 items were confirmed to be pure test-side bugs with no PRD silence or PRD/impl mismatch behind them. Each candidate edit was investigated and rejected because the PRD already uniquely determines the behavior the implementation exhibits:

**Per-item investigation log** (subject / impl paths enumerated / wording adjustment):

1. **Brand-scope rejection (`ERR_BRAND_OUT_OF_SCOPE`)** — (a) subject: brand-scope check on selection validation and its ordering vs. payload check. (b) Enumerated: `implementation/routes/selections.py:80-101` (validate endpoint: state check → payload/inertia check at line 85-93 → brand check at 95-97, `DUAL` covers both brands); PRD §3.4 ("Validation runs two checks in a pinned order. First the payload and inertia check… Only then does the brand-scope check run… a `DUAL` specialization covers both brands") and §2.6 ladder items 8–9. The Step 7 trigger (FANUC factory default vs. ABB org override) is a test-fixture construct; impl validates whatever brand is supplied. (c) No edit — PRD already pins rule, order, and DUAL semantics exactly as implemented.

2. **Session start: state-before-window** — (a) subject: evaluation order on `POST /training-sessions/{id}/start`. (b) Enumerated: `implementation/routes/sessions.py:107-124` (session-state check → project `TRAINING` check raising `ERR_INVALID_STATE` at 114-115 → window check raising `ERR_OUTSIDE_SESSION_WINDOW` at 119-121, both ends inclusive); PRD §3.8 ("Starting a session is legal only while the project stands in `TRAINING` and only inside the scheduled window… both ends inclusive") and §2.6 ladder (priority 4 `ERR_INVALID_STATE` before priority 10 `ERR_OUTSIDE_SESSION_WINDOW`). The two `ERR_INVALID_STATE` checks (session state, project state) share one error code, so their relative order is client-invisible. (c) No edit — PRD's ladder plus §3.8 uniquely derive the implementation's behavior.

3. **Program-name uniqueness (`ERR_DUPLICATE_CODE`)** — (a) subject: `program_name` uniqueness scope on program creation. (b) Enumerated: `implementation/routes/programs.py:29-52` (duplicate name within the project → `ERR_DUPLICATE_CODE` 409 at lines 38-40); PRD §3.5 ("a `program_name` unique within the project — collisions are rejected with `ERR_DUPLICATE_CODE` (HTTP 409)") and §2.6 ladder item 14. The Step 7 collision came from the test helper creating a second program with default name `MAIN` — a fixture bug, not a PRD gap. (c) No edit — uniqueness scope and error are verbatim-pinned.

4. **Missing test-module import (`setup_project_in_guarantee`)** — (a) subject: none PRD-facing; pure NameError in `test_11`. (b) No impl path exists (test-only symbol). (c) No edit — no PRD relevance.

**Conclusion:** the implementation was PRD-faithful at every Step 7 site, and every behavior involved was already uniquely derivable from PRD prose. A fresh implementer reading PRD.md (= PRD_FINALIZED.md) alone is not underdetermined at any of the four sites, so the correct minimal patch is the empty patch.

## Step 9: Complete PRD — 2026-08-15T09:06:00.000Z

Produced `/home/ubuntu/github/CodingPRD/tasks/task_2013_robotics_integration_cell_commissioning/workspace/PRD_COMPLETED.md` as a minimal patch over the latest PRD.

**Source vs output**: Source `PRD_FINALIZED.md` (identical to `PRD.md`) — 370 lines / 56,712 chars; `PRD_COMPLETED.md` — 370 lines / 59,701 chars (+2,989 chars, +0 lines; all edits in-paragraph).

**Counts**: 24 ambiguity-pins, 2 mismatch-revisions (26 edits total across 25 lines).

**Changes**:
- §2.1 — insert — ambiguity — authentication never resolves `X-User-ID` against the roster and does not require declared role to match stored `user_role`; ownership checks are raw string comparison — `implementation/middleware.py:30-50`
- §2.3 — insert — ambiguity — `has_more` semantics: true iff `offset` + returned items < `total_count` — `implementation/response.py:26`
- §2.8 — revise — mismatch — `milestone_ref` enumeration was closed but incomplete; extended to cover the opening WITHHOLD carrying the project's own id, guarantee-driven postings carrying the guarantee id, and the termination PENALTY carrying `MANUAL` — `implementation/routes/sites.py:135`, `implementation/routes/guarantees.py:82,91,115-116`, `implementation/routes/projects.py:194`
- §3.2 — insert — ambiguity — study creation without `supersedes_study_id` requires project status STUDY, else `ERR_INVALID_STATE` — `implementation/routes/studies.py:40-44`
- §3.2 — insert — ambiguity — `sim_cycle_time_s`/`sim_confidence_pct` optional (stored null) at creation; no range enforced on `sim_cycle_time_s` — `implementation/routes/studies.py:59-66`
- §3.2 — insert — ambiguity — submit with either sim field unset → `ERR_INVALID_REQUEST` (400) — `implementation/routes/studies.py:129-130`
- §3.3 — insert — ambiguity — assessment creation legal in any project status; client-supplied `pl_achieved` accepted but recomputed at submission — `implementation/routes/assessments.py:30-54`
- §3.3 — insert — ambiguity — submit computability breach (no fencing, no curtain zones) → `ERR_INVALID_STATE` (409) — `implementation/routes/assessments.py:90-93`
- §3.3 — revise — ambiguity — SAT-rework supersedes every APPROVED assessment, one shell each; shell copies risk score, `pl_target`, `pl_achieved`, fencing, zones, muting, and creator, with budget and approver null — `implementation/services/domain.py:143-162`
- §3.4 — revise — ambiguity — `payload_margin_pct` unset until a successful validation; proposal legal in any project status — `implementation/routes/selections.py:33-56,98`
- §3.5 — insert — ambiguity — program creation legal in any project status — `implementation/routes/programs.py:30-33`
- §3.5 — insert — ambiguity — REWORK→CODED code-complete is legal regardless of project status (DESIGN/BUILD restriction binds only OUTLINE→CODED) — `implementation/routes/programs.py:83-90`
- §3.6 — insert — ambiguity — advance evaluation order: state legality, then per-stage actor pinning (`ERR_FORBIDDEN_ROLE`), then version freshness — `implementation/routes/projects.py:66-75`
- §3.6 — revise — ambiguity — BUILD→FAT gate uses the most recently created APPROVED assessment — `implementation/routes/projects.py:118-124`
- §3.6 — insert — ambiguity — acceptance test records creatable in any project status — `implementation/routes/tests.py:67-72`
- §3.6 — insert — ambiguity — FAIL verdict records `retention_released_cents` of zero — `implementation/routes/tests.py:56-57`
- §3.6 — revise — ambiguity — SAT failure cascade moves every APPROVED assessment to SUPERSEDED with one shell per assessment — `implementation/services/domain.py:143-162`
- §3.7 — revise — mismatch — deleted "Every recorded maintenance service resets the burn clock..." (no service-recording capability exists in the API) — no impl counterpart
- §3.7 — revise — ambiguity — quoting legal in any project status — `implementation/routes/packages.py:28-33`
- §3.7 — revise — ambiguity — ORDERED legal only from QUOTED; DELIVERED legal only from ORDERED — `implementation/routes/packages.py:74-75,85-86`
- §3.7 — revise — ambiguity — plan creation legal in any project status; `hours_until_due` unset until first computed — `implementation/routes/plans.py:28-46`
- §3.7 — revise — ambiguity — re-activation from SUSPENDED re-runs neither stage nor window checks, only recomputes `hours_until_due`; meter readings accepted in every status except CLOSED (`ERR_INVALID_STATE`) — `implementation/routes/plans.py:84-88,103-108`
- §3.8 — insert — ambiguity — session scheduling legal in any project status — `implementation/routes/sessions.py:33-37`
- §3.8 — insert — ambiguity — completion by anyone other than the assigned trainer → `ERR_FORBIDDEN_ROLE` (403) — `implementation/routes/sessions.py:133-135`
- §3.9 — insert — ambiguity — outcome inconsistent with supplied observations (MET whose conditions fail, or MISSED while both MET conditions hold) → `ERR_INVALID_REQUEST` (400) — `implementation/routes/guarantees.py:69-76`
- §3.9 — insert — ambiguity — MISSED penalty that doesn't zero the balance leaves the project in GUARANTEE; a later hand-posted entry zeroing the balance with a settled guarantee closes the project — `implementation/routes/guarantees.py:93-94`, `implementation/routes/ledger.py:62`, `implementation/services/domain.py:94-102`
- §3.9 — revise — ambiguity — termination clears any `hold_reason` — `implementation/routes/projects.py:197`

Everything else in the impl (RBAC role sets per endpoint, full evaluation ladder, all state machines, all calculation formulas and rounding, cascades, envelope/pagination shapes, clock semantics) matched PRD prose uniquely and was left untouched.
