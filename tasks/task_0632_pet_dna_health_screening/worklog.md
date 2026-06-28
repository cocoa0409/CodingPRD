# Worklog — task_0632_pet_dna_health_screening

Scenario: 632. Pet DNA & Health Screening (Embark/Wisdom Panel style): kit order & swab activation, sample receipt & genotyping pipeline, breed/ancestry & genetic-health/trait report, relative-finder & opt-in, vet-shareable report, subscription/upgrade, re-test/QNS, data download/delete

Difficulty band: Expert (passed to Step 2 scaffold generator only).

## Step 1: Create Task Directory — 2026-06-23T00:00:00.000Z

Task directory `tasks/task_0632_pet_dna_health_screening/` was pre-assigned and pre-created (with `workspace/` subdir) to avoid ID contention. Step 1 max-index scan skipped per the pipeline directive. Confirmed directory and empty `workspace/` exist.

## Step 2: Generate Scaffold (Expert band) — 2026-06-23T00:00:00.000Z

Generated all three Expert-band scaffold artifacts for task_0632_pet_dna_health_screening (Embark/Wisdom-Panel-style Pet DNA & Health Screening). All files written and `scaffold_lint.py` returns VERDICT: clean lint.

Archetype: workflow_orchestration + compliance_audit; flat topology; branching state machines; peer_roles; layers = cascading side-effects, dual-variant calculation, optimistic concurrency, derived-field reconciliation.

Entity list (12): Account, Pet, Kit, Sample, GenotypingRun, Report, HealthMarkerResult, RelativeMatch, ShareLink, Subscription, DataRequest, MarkerCatalogEntry.

Section counts (SCAFFOLD.yaml):
- State machines: 8 (Pet, Kit, Sample, Report, RelativeMatch, ShareLink, Subscription, DataRequest)
- Calculations: 5 (genotyping_qc_score, breed_ancestry_composition, subscription_upgrade_proration, relative_kinship_pct, report_health_risk_rollup)
- Validations: 16 (priority-ordered)
- Endpoints: 48
- Error codes: 18
- Roles: 5 (PlatformAdmin, Account, LabTechnician, Veterinarian, Anonymous)
- Concurrency rules: 2 (OCC on Subscription upgrade and Report finalize)

§1.8 difficulty instances: 18 (all 9 Difficulty Rules × 2, each pair satisfying its §0.5 differentiation clause).
§1.9 corner instances: 34 total (28 active test recipes + 6 excluded_because: stubs cross-referencing named §1.8 instances), spanning all nine claim-extraction-guide sections.

Key notes: formula-derived asserts pinned to code-computed literals (qc 99.10/54.00; breed [33.34, 33.33, 33.33]=100.00; proration credit 7431 + charge 12469 = 19900; kinship 24.00→23.52; grace_until 2026-05-31). Two computed back-pointer fields (Account.active_subscription_id, Pet.finalized_report_id) use non-FK descriptions. Vet token view at GET /dna/shared-reports/{token}. Default clock 2026-01-01T00:00:00Z declared.

File sizes: SCAFFOLD.yaml 1525 lines, SCAFFOLD_DIFFICULTY_DESIGN.yaml 969 lines, SCAFFOLD_CORNER_DESIGN.yaml 1066 lines.

## Step 3: Copy Shared Files — 2026-06-23T00:00:00.000Z

Copied ./INSTRUCTION.md → tasks/task_0632_pet_dna_health_screening/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-06-23T00:00:00.000Z

Generated the PRD at workspace/PRD.md (281 lines). Sources read: only SCAFFOLD.yaml (plus the skill spec, the fixed section-2.2-response-structure.md, and the reference example-prd.md). Did NOT open, grep, or reference either SCAFFOLD_DIFFICULTY_DESIGN.yaml or SCAFFOLD_CORNER_DESIGN.yaml.

Major sections produced:
- §1 Introduction — kit→swab→genotyping→report→relative-finder→privacy lifecycle and four-actor model.
- §2 Global Specifications — 2.1 RBAC (5 roles, both headers), 2.2 fixed response envelope, 2.3 Pagination, 2.4 Common Resource Properties & Logical Clock (incl. two common_fields:false entities), 2.5 Precision/Rounding, 2.6 Hierarchical Consistency & Cascades, 2.7 Nested Retrieval & existence ordering, 2.8 Validation Ordering (priority 1–16), 2.9 OCC (both guarded writes).
- §3 Business Logic — 9 scattered subsections (Accounts/Pets/opt-in, Kits, Sample pipeline & re-tests, Reports, Share links, Relative-finder, Subscriptions/proration, Data export/delete/purge cascade, Marker catalog).
- §4 Endpoint table (4 columns) and §5 Error catalogue (2 columns).

Hard Contract reports: Contract 1 (Field-Name Coverage) PASS (46/46 fields, 34/34 inputs, 2/2 path params); Contract 2 (Rule Coverage) PASS (all 18 error IDs, 26 state values, 11 calc constants; both OCC rules; QC formula; breed remainder reallocation; kinship variants; proration floor; cascade side-effects); Contract 3 (§3 Path Purity) PASS for paths and method+path (the `kind` enum value DELETE/DOWNLOAD is backticked enum, not an HTTP method in endpoint position).

## Step 5: Generate Unit Tests — 2026-06-23T00:00:00.000Z

Generated complete test infrastructure for the Pet DNA & Health Screening API (task_0632).

Test files: 7 test files + conftest.py (8 files in test_suite/). Total test functions: 62.

Provenance breakdown:
- Queue A (Difficulty, §1.8): 34 tests — covering 17 of 18 instances at ≥2 tests each
- Queue B (Corner, §1.9): 28 tests — covering all 28 non-stub instances at ≥1 test each
- 6 corner stubs (excluded_because) correctly not translated; all cross-references resolve to real difficulty instances

Design instances SKIPPED: 1
- Difficulty/priority_pair_validation_conflict/purge_in_progress_beats_invalid_state_on_kit_activate — error-precedence / unique-derivability failure. The instance asserts ERR_PURGE_IN_PROGRESS surfaces over ERR_INVALID_STATE, but PRD §2.8 fixes the order so the state check (fifth framework check) is evaluated before the purge-in-progress freeze (a later business rule). A faithful PRD-only implementer would return ERR_INVALID_STATE. Skipped (documented inline in test_06_data_governance.py, no placeholder/xfail). The sibling instance not_resource_owner_beats_invalid_state_on_report_revoke is PRD-consistent (ownership p4 before state p5) and was kept.

Validation performed: all 62 tests collect under pytest; all 82 quoted PRD citations verified verbatim-present in PRD.md (C1); calculation values cross-checked (qc_score 99.10/54.00, kinship 24.00/23.52/49.00, proration 12469, grace_until 2026-05-31); no scaffold/§/Table references leak into generated code; compileall clean.

Files under test_helpers/: __init__.py, types.py, api_client.py, api_errors.py, assertions.py, factories.py, constants.py, test_users.py, fixtures.py
Files under test_suite/: conftest.py, test_01_genotyping_pipeline.py, test_02_sample_and_kit_lifecycle.py, test_03_reports_and_sharing.py, test_04_relative_finder.py, test_05_subscriptions.py, test_06_data_governance.py, test_07_crud_and_rbac.py

Note: One PRD/scaffold inconsistency surfaced (purge-vs-state precedence in the difficulty index contradicts PRD §2.8) — left as a gap per the PRD-first contract.

## Step 6: Generate Implementation — 2026-06-23T00:00:00.000Z

Generated a complete Python + Flask implementation at workspace/implementation/.

File list: start.sh (guarded foreground launcher), requirements.txt, app.py (entry + error handlers + blueprint registration), clock.py (logical clock default 2026-01-01T00:00:00Z), db.py (in-memory store), errors.py (error catalog), response.py (envelope helpers), middleware.py (auth/RBAC), helpers.py (pagination/validation), serializers.py (entity views + computed back-pointers); routes/: clock_routes.py, accounts.py, pets.py, kits.py, samples.py, reports.py, share_links.py, relative_matches.py, subscriptions.py, data_requests.py, marker_catalog.py; services/: common.py, calculations.py, cascades.py, report_service.py, sample_service.py.

Framework/deps: Flask 3.0.3 only. Decimal arithmetic from stdlib for all rounding/money.
Endpoints implemented: 48 — matching the PRD §4 endpoint table.

Constraints confirmed: start.sh reads $PORT (default 10000), binds 0.0.0.0, runs foreground via exec, guards pip install on a Flask import check. Storage in-memory only (Python dicts keyed by id) — no SQLite, no disk, no /tmp cache. Fresh boot produces empty store (total_count: 0), zero startup seeding, logical clock reads 2026-01-01T00:00:00.000Z before any clock-set call.

## Step 7: Run Tests and Iterate — 2026-06-23T00:00:00.000Z

Both consecutive 8-round parallel sweeps fully clean — 62/62 in all 16 round-runs (final results.1..8.json all passed=62 total=62).

Iterations run: 3 sweeps total (1 baseline diagnostic + 2 confirming). Fixes converged in the first iteration; the third sweep confirmed stability.

Tests deleted: None. No test was found PRD-silent or non-uniquely-derivable to the point of requiring deletion.

Fixes applied to test_suite/:
- test_05_subscriptions.py — test_upgrade_with_stale_version_after_cancel_rejected: relaxed exact-error assertion validate_error(resp, ERR_STALE_VERSION) to validate_error_is_one_of(resp, [ERR_STALE_VERSION, ERR_INVALID_STATE]) (added validate_error_is_one_of import). Explicitly-permitted ERROR-PRECEDENCE relaxation: PRD §2.9 names this exact scenario (cancel moving ACTIVE→GRACE, then stale-version upgrade) as ERR_STALE_VERSION, but PRD §2.8 fixes a priority order where the state precondition (ERR_INVALID_STATE, priority 5) is evaluated strictly before the OCC version check (ERR_STALE_VERSION, last). After the cancel, the subscription is in GRACE (upgrade undefined) AND the supplied version is stale, so the two PRD sentences are in genuine tension — a faithful PRD-only implementer could reasonably land on either. PRD supports the "ERR_STALE_VERSION is possible" reading, so per protocol the assertion is relaxed to the two-member set.

Fixes applied to test_helpers/: None.

Fixes applied to implementation/:
- app.py — module top: set logging.getLogger("werkzeug").setLevel(logging.ERROR) to suppress the per-request access-log flood the harness readiness-probe generates (hundreds of 404s per boot). Under the 8-round concurrent harness (~8× peak CPU/IO), this log flood was pushing some server boots past the per-test-server restart window, producing non-deterministic "could not be restarted" setup failures. No API-behavior change.
- app.py — __main__: suppressed the Flask dev-server startup banner (flask.cli.show_server_banner) and set use_reloader=False to trim boot I/O. No API-behavior change; purely boot-latency hardening.

Key finding: The only genuine logic discrepancy was the §2.8-vs-§2.9 error-precedence conflict (1 deterministic failure). All other intermittent failures in the first post-fix sweep were environmental server-restart timeouts under 8× concurrent load, not test/implementation bugs — resolved by boot-latency hardening. Storage remains in-memory only; no seeding; store starts empty on every boot.

## Step 8: Finalize PRD — 2026-06-23T00:00:00.000Z

Produced workspace/PRD_FINALIZED.md (281 lines; 0% line delta, both edits revised existing single-line paragraphs in place; +1207 chars, +2.86%).

Changes:
- §2.9 (paragraph "The first is the subscription upgrade…") — revise — Replaced the claim that an already-cancelled (ACTIVE→GRACE) or already-upgraded (ACTIVE→SUPERSEDED) subscription yields ERR_STALE_VERSION with impl's actual behavior: per the §2.8 priority order the state precondition (ERR_INVALID_STATE) is evaluated before the OCC version check, so a stale-version upgrade against any subscription that has left ACTIVE surfaces ERR_INVALID_STATE; ERR_STALE_VERSION applies only when the subscription still passes the earlier framework checks. Also pinned that a missing expected_subscription_version surfaces ERR_INVALID_REQUEST even on a non-ACTIVE subscription (required-field check precedes state precondition) — implementation/routes/subscriptions.py:109,112,118,123.
- §2.9 (paragraph "The second is report finalization…") — revise — Same precedence alignment: kept the valid ERR_STALE_VERSION example (attaching a marker bumps version while report stays PRELIMINARY); corrected the "revoking the report bumps its version" example (actually yields ERR_INVALID_STATE — revoke moves report to terminal REVOKED, tripping the state precondition before the version check); pinned that for finalize the state precondition is checked before the required-field check — implementation/routes/reports.py:114,119,123,127.

Items requiring no PRD edit: the two app.py changes (werkzeug log level, banner suppression + use_reloader=False) are non-behavioral boot/logging hardening — no observable API change. No tests deleted; no test_helpers changes.

## Step 9: Complete PRD — 2026-06-23T00:00:00.000Z

Produced workspace/PRD_COMPLETED.md from PRD_FINALIZED.md (281 → 281 lines; no new lines/sections; chars 43,325 → 45,161, +1,836). Section counts unchanged (5 H2, 18 H3).

Counts: 6 ambiguity-pins, 3 mismatch-revisions (8 edited passages; the §3.4 marker passage carries one of each).

Per-change bullets:
- §2.3 Pagination — insert — ambiguity — out-of-range limit/offset clamped (<1→1, >100→100, negative offset→0); non-integer → ERR_INVALID_REQUEST — helpers.py:34-54
- §2.8 Validation Ordering — revise — mismatch — swapped priority so purge-in-progress freeze precedes the relative-finder opt-in check — routes/relative_matches.py:43-49
- §3.1 Accounts — insert — ambiguity — missing/blank/non-string/duplicate email → ERR_INVALID_REQUEST — routes/accounts.py:22-28
- §3.2 Kit Activation — insert — ambiguity — pinned check order (state → purge → referential); wrong-account or non-REGISTERED pet → ERR_INVALID_REQUEST — routes/kits.py:83-93
- §3.4 Breed Composition — insert — ambiguity — breed_segments whose match_cm sum to zero yields empty composition (degenerate division skipped) — services/calculations.py:83-85
- §3.4 Health Markers — revise — mismatch — marker_code recorded verbatim, NOT cross-checked against catalog; attach not gated by report state; recompute uses rule matching report's current state — routes/reports.py:60-88
- §3.7 Subscriptions — insert — ambiguity — annual_fee_cents must be integer ≥ 0; non-integer/boolean/negative → ERR_INVALID_REQUEST — routes/subscriptions.py:43-44
- §3.7 Upgrade — revise — mismatch — request tier optional, defaults to PREMIUM when omitted — routes/subscriptions.py:117-120
- §3.9 Marker Catalog — insert — ambiguity — duplicate marker_code → ERR_INVALID_REQUEST — routes/marker_catalog.py:25-27

Key findings: (1) §2.8 global priority list had purge/opt-in reversed relative to relative-match create; (2) marker marker_code not validated against MarkerCatalogEntry despite "drawn from the catalog" wording; (3) marker-attach recompute follows report's current state rather than always preliminary rule; (4) subscription upgrade defaults missing tier to PREMIUM. Already-pinned behaviors (qc_score formula, proration, kinship variants, §2.9 OCC orderings, cascade side-effects, response envelopes) needed no change.

## Pipeline Complete — 2026-06-23T00:00:00.000Z

All 9 steps complete. Final state: 62 tests, 8/8 final sweep rounds at 62/62. Artifacts present: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, worklog.md, test_helpers/ (10), test_suite/ (9), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}.
