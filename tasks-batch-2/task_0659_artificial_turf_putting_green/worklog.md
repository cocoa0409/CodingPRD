# Worklog — task_0659_artificial_turf_putting_green

Scenario: 659. Artificial Turf & Putting-Green Install: site measure & sq-ft/design, turf product & infill selection, base prep & drainage scope, quote & deposit, crew & install scheduling, pet/playground variant, warranty & maintenance plan, callback

Difficulty: Expert

## Step 1: Create task directory — 2026-06-26T14:44:47.787Z

Task directory `tasks/task_0659_artificial_turf_putting_green/` with `workspace/` subdir was pre-assigned and already exists. No index scan performed (pre-assigned to avoid contention with parallel runs). Using `tasks/task_0659_artificial_turf_putting_green` verbatim as {task_dir}.

## Step 2: Generate scaffold — 2026-06-26T15:04:28.000Z

Generated three scaffold artifacts (subagent hit a transient API error after writing SCAFFOLD.yaml; resumed via SendMessage to complete the two design files, which it also self-corrected a YAML flow-mapping quoting bug in).

SCAFFOLD.yaml: 1654 lines. Domain: artificial turf & putting-green install.
- entities: 13 (Expert range 10–15 ✓)
- endpoints: 50 (≥ Expert 20–32 floor ✓)
- errors: 21 (Expert range 18–30 ✓)
- calculations: 8 variants (Expert ≥3 ✓)
- state_machines: 9 (Expert ≥4 ✓), state_machine_shape=parallel
- roles: 4 (peer_roles); validations: 20; concurrency_rules: 1
- complexity_layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, derived_field_reconciliation

SCAFFOLD_DIFFICULTY_DESIGN.yaml: 1604 lines, top-level key scaffold_difficulty_design, 18 depth (queue A) instances.
SCAFFOLD_CORNER_DESIGN.yaml: 1806 lines, top-level key scaffold_corner_design, 41 breadth (queue B) instances.

All three validated as well-formed YAML with correct top-level keys (SCAFFOLD.yaml has neither design key).

## Step 3: Copy shared files — 2026-06-26T15:04:30.000Z

Copied ./INSTRUCTION.md → tasks/task_0659_artificial_turf_putting_green/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-06-26T15:10:00.000Z

Generated workspace/PRD.md (305 lines, 47204 bytes) for the turf-install domain (Expert).

Sections: §1 Introduction; §2 Global Specs (9 subsections: RBAC, §2.2 envelope verbatim, pagination, common resource props, money/area rounding, parallel status dimensions + cascade consistency, nested retrieval + reference resolution, OCC on quote acceptance, validation ordering); §3 Business Logic (13 lifecycle subsections); §4 Endpoint table (51 endpoints); §5 Error catalogue (21 codes).

Documented: 14 entities; 51 endpoints; 9 state machines (Project workflow_status, Project finance_status, DesignLayout, Quote, BasePrepScope, InstallJob, WarrantyPlan, Callback, Payment); 8 calculations (quote_total, project_ledger w/ chronological + forward_projected, drainage_tier, base_prep_cost, waste_factor, deposit_amount, warranty_terms, callback_billing); 1 OCC rule (expected_project_version → ERR_STALE_PROJECT_VERSION/412); 20 validation rules in priority order.

Hard contracts all PASS: Field coverage (84/84 required present), Rule coverage (20 validations + 1 OCC + 9 state machines + 8 calculations + cascades + sibling symmetry all expressed), Path purity (§3: 0 path/method tokens). Withheld difficulty/corner design files were NOT opened. Verified no leakage markers in PRD.

## Step 5: Generate unit tests — 2026-06-26T15:26:00.000Z

Generated test_helpers/ (9 files: types.py with 10 status enums + 13 entity TypedDicts; api_client.py one-method-per-endpoint; api_errors.py 21 error IDs + HTTP map; assertions.py; factories.py; constants.py; test_users.py entity-backed header builder; fixtures.py composite catalog→MEASURED→DESIGNED→finalized scope→SENT→DEPOSIT_PAID→SCHEDULED→INSTALLED→PAID_IN_FULL; __init__.py) and test_suite/ (conftest + 6 files, 73 tests).

Per-file: test_01_pricing(16), test_02_state_machines(17), test_03_cascades(8), test_04_scheduling(6), test_05_validations(21), test_06_rbac_concurrency(5).

Queue coverage: Queue A (Difficulty) all 18 instances, ≥2 tests each = 37 tests. Queue B (Corner) all 36 non-stub instances ≥1 test = 36 tests. 4 corner stubs correctly not translated.

KEY ROUTING NOTE: PRD uses nested project-child routing (/projects/{id}/design-layouts/{id}/accept) while design indices used flat paths (scaffold was converted to flat topology during Step 2 lint recovery). PRD is the contract under test, so api_client.py follows PRD nested paths; only /_payments/* and /_clock/* drivers stay flat.

PRD-first filter: no full skips. Two assertions dropped as not uniquely-derivable: cash_conserved_deposit_then_refund (outstanding==0 → replaced with conserved-cash facet) and the priority_pair re-accept tests use validate_error_is_one_of([ERR_INVALID_STATE, ERR_DESIGN_ALREADY_ACCEPTED]) while still asserting variant/scope 422 does NOT win. All 73 docstrings carry exactly one Design: tag; verbatim PRD citations grep-verified; no skip/xfail; 73 collected.

## Step 6: Generate implementation — 2026-06-26T15:26:00.000Z

Built Python + Flask 3.0.3 (Python 3.14) implementation at workspace/implementation/, in-memory only (process-local dicts in db.py, empty every boot, no seeding). start.sh reads $PORT (default 10000), binds 0.0.0.0, guards pip install on import flask check, execs app.py foreground.

18 files: Foundation (app.py, db.py, clock.py, errors.py, response.py, middleware.py, ownership.py, common.py, lookups.py, requirements.txt, start.sh); routes/ (clock, customers, catalog, crews, projects, site_measures, design_layouts, base_prep_scopes, quotes, payments, install_jobs, warranty_plans, callbacks); services/ (calculations, project_service, payment_service).

48 endpoints (all PRD §4). PRD §4 nested paths authoritative over SCAFFOLD flat topology (PRD-wins). Parallel Project state dims (workflow_status × finance_status) advance independently; payment settlement drives cross-dim nudges. Calculations use Decimal round-half-up, round-per-line-before-summing. Ledger replays SETTLED payments by (created_at, _seq) monotonic tie-break; forward-projected folds in PENDING. OCC via expected_project_version → ERR_STALE_PROJECT_VERSION (412). 3 no-version/no-updated_at entities (TurfProduct, InfillProduct, Payment). Bug fixed during verify: quote TTL anchored to logical clock instant (_logical_created_at) not wall-clock created_at. Deliberate non-validation: project create does not reject unknown customer_id (FK not in PRD §2.7 ERR_REFERENCE_NOT_FOUND catalog).

NOTE: Step 2 scaffold agent later converted SCAFFOLD to FLAT topology (api_prefix /, 55 endpoints) for FK reverse-reachability lint. PRD remained nested; both Step 5 and Step 6 independently followed PRD nested paths, so tests↔impl are mutually consistent. Verified: 73 tests collect cleanly with PYTHONPATH=task_root.

## Step 7: Run tests and iterate — 2026-06-26T15:51:00.000Z

FINAL RESULT: 8/8 parallel rounds, 73/73 tests passing, 0 failures, 0 errors in every round (verified on disk: results.1..8.json all passed=73 total=73 failed=0 errors=0).

Iterations run: 2 fix iterations (3 full 8-round sweeps total).

Tests deleted: None. Every failing test traced to a verbatim PRD rule and survived the unique-derivability check.

Fixes applied to test_helpers/: None.

Fixes applied to implementation/:
1. routes/quotes.py send_quote() — REAL LOGIC BUG. The project version increment was incorrectly gated inside the `if workflow_status == DESIGNED` branch, so a second quote sent while project already QUOTED bumped no version. test_stale_then_fresh_quote_accept failed all 8 initial rounds: it sends a sibling quote to bump version then expects stale-version accept of the first quote → ERR_STALE_PROJECT_VERSION; the missing bump made the stale accept succeed. PRD §3.6 line 170 makes the version increment an unconditional coordinate effect of every send (contrast §3.1 line 128 "the very first measure" when it means first-only). Fixed by moving touch(project) outside the if.
2. app.py entry point — app.run(..., threaded=True) so a single per-test-server boot services the runner health-check + test request concurrently without dropping the connection under the 8x-concurrent sweep. Eliminated rotating ConnectionError/Connection reset flakiness (test_accept_void_sibling_quote_rejected, test_start_install_before_scheduled_start_rejected, test_drainage_tier_flat_poor_soil_resolves_to_panel intermittently). Storage remains in-memory-only; no seeding, no persistence.

Infra note (not a code defect): one intermediate sweep saw 7/8 rounds die at startup with ServerStartError code 143 (SIGTERM) due to external host contention (load avg ~30, ~120 concurrent processes from other pipelines starving the simultaneous boot burst). Re-run at lower load produced clean 8/8. No application change warranted.

## Step 8: Finalize PRD — 2026-06-26T15:56:00.000Z

Produced workspace/PRD_FINALIZED.md (305 lines, same as PRD.md — one sentence revised in place, no net line delta).

1 edit:
- §3.6 (Quote Lifecycle: Send) — revise — Pinned that on quote send the project version increment is an unconditional coordinate effect of EVERY send, while the workflow advance DESIGNED→QUOTED only fires when project is still DESIGNED (a send while already QUOTED leaves workflow unchanged but still bumps version) — routes/quotes.py:155-168.

Item 2 (app.py threaded=True): NO PRD edit — pure server-infra/concurrency fix, no behavioral surface.

Pre-edit global consistency search confirmed the "every send bumps version" wording was scoped strictly to send (not all mutations), so it does not contradict the site-measures path where the version bump is gated to the first measure only (§3.1), nor accept_design / revise / payment-settlement paths.

## Step 9: Complete PRD — 2026-06-26T16:00:00.000Z

Produced workspace/PRD_COMPLETED.md (311 lines, +6 from PRD_FINALIZED.md's 305; +5027 chars). TERMINATION SIGNAL — pipeline complete.

13 edits: 9 ambiguity-pins, 4 mismatch-revisions (6 new lines are endpoint-table rows filling silence; prose edits in-paragraph).
- §2.1 RBAC — revise/mismatch — empty/unrecognized headers → ERR_UNAUTHENTICATED, not ERR_FORBIDDEN_ROLE (latter only for recognized-but-unpermitted role) — middleware.py:26-36
- §2.3 Pagination — insert/ambiguity — list endpoints accept exact-match status/kind/FK filters; catalog active/include_pending parse booleans else ERR_INVALID_REQUEST — catalog.py, projects.py
- §3.1 Project create — insert/ambiguity — customer_id not reference-checked — projects.py:57-62
- §3.1 Site measure — revise/mismatch — recording allowed in any workflow status; only first (while DRAFT) advances to MEASURED + bumps version — site_measures.py:39-63
- §3.2 Catalog — insert/ambiguity — OpsAdmin-only, positive-number/flag defaults, case-sensitive sku uniqueness → ERR_DUPLICATE_RESOURCE — catalog.py
- §3.6 Quote expiry — insert/ambiguity — TTL anchored to logical-clock instant at creation, lazy expiry on read — project_service.py, quotes.py
- §3.7 Payments — revise/ambiguity — settle/fail resolve payment_id as path-style (ERR_NOT_FOUND); non-PENDING target → ERR_INVALID_STATE — payments.py:79-113
- §3.7 Ledger — insert/ambiguity — include_pending boolean parse; ledger read returns full Project with 4 ledger fields overlaid — projects.py:91-117
- §3.7 Deposit settle — revise/mismatch — version bumps only at DEPOSIT_DUE→DEPOSIT_SETTLED crossing — payment_service.py:50-82
- §3.12 Close — insert/ambiguity — non-INSTALLED close → ERR_INVALID_STATE; ERR_PROJECT_NOT_CLOSEABLE only for INSTALLED failing paid/callback test — projects.py:126-133
- §3.12 Cancel — insert/ambiguity — cancel of INSTALLED/CLOSED/CANCELLED → ERR_INVALID_STATE — projects.py:145-146
- §3.12 Refund/balance settle — revise/mismatch — version bump tied to actual →REFUNDED / →PAID_IN_FULL transitions — payment_service.py:67-82
- §4 Endpoint table — insert ×6/ambiguity — added implemented single-resource GET rows (site-measure, base-prep-scope, install-job, warranty-plan, callback, /payments/{id})

Deliberate non-changes: calculation formulas, §2.9 validation-priority chain, design-accept/install-schedule check orderings, parallel-status cascades all already pin uniquely. add_months day-clamp and relative ordering of 3 design-accept business errors left unpinned (low-stakes, PRD does not contradict).

=== PIPELINE COMPLETE: all 9 steps done, 73/73 tests pass across 8/8 stability rounds, PRD_COMPLETED.md on disk. ===
