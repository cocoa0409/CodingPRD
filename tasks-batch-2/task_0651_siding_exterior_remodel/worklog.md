# Worklog — task_0651_siding_exterior_remodel

Scenario: 651. Siding & Exterior Remodel (James Hardie contractor): measure & material/color selection, scope (siding/trim/wrap) & sq-ft estimate, permit & HOA, material order & delivery, crew & weather scheduling, change order & progress draw, lifetime/workmanship warranty, financing

Difficulty: Expert

## Step 1: Create Task Directory — 2026-06-26T14:44:38.000Z

Task directory pre-assigned and verified: tasks/task_0651_siding_exterior_remodel/ with workspace/ subdir already present. No index scan performed (pre-assigned per execution parameters).

## Step 2: Generate Scaffold — 2026-06-26T15:16:03.000Z

All three Expert-difficulty scaffold artifacts generated (SCAFFOLD.yaml 1820 lines, SCAFFOLD_DIFFICULTY_DESIGN.yaml 1751 lines, SCAFFOLD_CORNER_DESIGN.yaml 2177 lines).

Counts (all within / above Expert band):
- 15 entities (Project, HomeownerClient, StaffMember, Measurement, Estimate, EstimateLineItem, Permit, HOAApproval, MaterialOrder, ChangeOrder, WorkSchedule, Crew, ProgressDraw, Warranty, FinancingApplication)
- 69 endpoints (2 GETs per entity for FK reverse-reachability + ~42 state-transition/create POSTs across 6 state machines)
- 22 error codes
- 6 state machines — Project (parallel workflow_status × compliance_status), ChangeOrder (cyclic SUBMITTED↔NEGOTIATING), MaterialOrder (branching at confirmation), WorkSchedule (WEATHER_HOLD revert), ProgressDraw (RELEASED→CLAWED_BACK compensation), FinancingApplication (branching decide)
- 9 calculations, 3 carrying dual variants (line_extended_amount, realized_contract_total, draw_release_amount; 6 variant entries total)
- 2 concurrency_rules (OCC on Project.version for draw-release and change-order-approve)
- 5 roles (Anonymous, Estimator, ProjectManager, HomeownerClient, FinanceOfficer)

Design coverage: 18 difficulty instances (9 rules × 2), 34 corner instances (33 active + 1 excluded stub). scaffold_lint.py returns "VERDICT: clean lint" (708 calls scanned, all FKs reverse-reachable). No sibling task_*/ dirs read.

## Step 3: Copy Shared Files — 2026-06-26T15:16:03.000Z

Copied INSTRUCTION.md → workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-06-26T15:21:37.000Z

Generated workspace/PRD.md — 324 lines — lossless prose projection of the scaffold.

Sections covered: §1 Introduction (dual-axis Project aggregate); §2 Global Specs (8 subsections: RBAC w/ 5 roles, response envelope, pagination, common props/versioning, OCC on Project, monetary precision + rounding, nested retrieval, two axes + cascading consistency); §3 Business Logic (12 subsections lifecycle-organized); §4 endpoint table (67 endpoints incl /_clock/set_current_utc); §5 error table (22 codes).

Hard contract reports: Field coverage PASS (64/64 required), Rule coverage PASS (21 validations, 2 OCC, 6 state machines, 8 calculations, sibling-branch symmetry all expressed), Path purity PASS (0 path tokens in §3). Withheld design files not opened.

## Step 5: Generate Unit Tests — 2026-06-26T15:40:11.000Z

Generated complete test infrastructure from the two design indices only, with full PRD-first adjudication.

Helper files created (9 in test_helpers/): types.py (14 entity TypedDicts + 12 enums), api_errors.py (22 errors + HTTP map), constants.py (thresholds), api_client.py (one method per endpoint incl /_clock/set_current_utc), test_users.py (per-instance role-header builders for 4 entity_backed roles), factories.py (input-only payload factories), assertions.py, fixtures.py (5-tier composite setup), __init__.py.

Test files created (10 in test_suite/): conftest.py + 9 test_*.py files, 70 test functions total. All collect and compile cleanly.

Coverage: Queue A (Difficulty) all 18 instances covered with ≥2 tests each (9 rules × 2). Queue B (Corner) all 31 non-stub instances translated except 1 skipped; the 1 excluded_because stub correctly not translated.

Skipped instances (1):
- Corner/state_machines/permit_issue_blocked_without_hoa_when_required — SKIPPED. Asserts ERR_INVALID_STATE for issuing a permit when hoa_required=true and no APPROVED HOA exists, but PRD §3.4 names no error for this failure (only says issuance "requires" the HOA). Not uniquely derivable.

Quality verification: all substantial PRD quotes confirmed verbatim; every test has exactly one Design: tag resolving to a real instance; no skip/skipif/xfail markers; literal expected values copied verbatim from design YAMLs.

## Step 6: Generate Implementation — 2026-06-26T15:40:11.000Z

Built complete Python + Flask implementation in workspace/implementation/.

Files created (12): start.sh (foreground launcher: cd to script dir, guarded pip install on import flask check, exec python3 app.py), app.py (entry + routes + error handlers + clock endpoint, binds 0.0.0.0:$PORT default 10000, threaded, no reloader), calculations.py (8 calcs w/ Decimal/ROUND_HALF_UP + ROUND_CEILING), services.py (cross-entity logic, depth-3 cascade), db.py (in-memory Store), errors.py (22 error IDs), response.py (envelope), middleware.py (auth/RBAC), helpers.py (parsing/pagination/touch), serialize.py, clock.py, requirements.txt.

Endpoints: 62 routes covering all entities + /_clock/set_current_utc test hook.

Key design decisions: in-memory only (empty on every boot, verified total_count 0 + clock 2026-04-01T00:00:00.000Z); envelope matches scaffold/PRD; validation priority order (PRD 3.12: auth → forbidden-role → SoD → existence → invalid-request → invalid-state → business); OCC on expected_project_version for draw release + change-order approve (412 ERR_STALE_PROJECT_VERSION), project cancel version mismatch via ERR_CANCEL_NOT_ALLOWED; two overlap semantics (crew=half-open no buffer; site=closed ±24h); money in integer cents; retainage cumulative-cap headroom; contract-total recompute bumps version. Cancel cascade chained strictly through material-order cancellation per literal contract. Smoke-tested 100+ assertions across 6 runs, all passing.

## Step 7: Run Tests and Iterate — 2026-06-26T15:57:43.000Z

All 8 parallel rounds pass cleanly (69/69 each). The loop is complete.

**Iterations run:** 2 (initial diagnostic sweep + one fix sweep).

**Tests deleted (1):**
- `test_cancel_without_reason_returns_invalid_request` (test_03_project_lifecycle.py) — ERROR PRECEDENCE / contradictory coverage. The test asserted `ERR_INVALID_REQUEST` for an omitted `cancelled_reason`, citing the generic §3.12 missing-field rule. But §3.8 specifically and verbatim states "a cancellation attempt on an ineligible status, or one omitting the `cancelled_reason`, is rejected with `ERR_CANCEL_NOT_ALLOWED`." Two divergent PRD-faithful implementations are articulable (generic §3.12 → INVALID_REQUEST vs. specific §3.8 → CANCEL_NOT_ALLOWED), and the more specific §3.8 directly contradicts the test's expectation, so the outcome is not uniquely derivable.

**Fixes applied to test_helpers / test_suite (4):**
- `test_03_project_lifecycle.py` `test_filing_permit_advances_compliance_without_touching_workflow` — was asserting `MEASURED` on the stale DRAFT snapshot returned by `create_measured_project()`; now asserts on a refetched project (matching the sibling test's pattern).
- `test_03_project_lifecycle.py` `test_window_cancel_rejects_progress_draw_on_it` and `test_window_cancel_sets_status_cancelled` — fixture precondition was inconsistent with PRD §3.6 (only PROPOSED/CONFIRMED/WEATHER_HOLD windows are cancellable; the fixture used `setup_completed_window`, and COMPLETED is terminal). Switched to `setup_scheduled_window` (CONFIRMED window) with a REQUESTED draw on it, which validly exercises the cancel cascade.
- `test_04_scheduling.py` helper `_confirmed_window_on_shared_crew` — returned the stale PROPOSED snapshot from `propose_window`; now returns the confirmed-window response (fixes `test_cancelling_window_sets_cancelled_and_unblocks_same_crew`).
- `test_07_material_orders.py` `test_ordered_sqft_ceil_and_project_advances_to_ordered` — used `validate_success` (expects 200) on the material-order POST, which correctly returns 201 per PRD §4; switched to `get_success_data` (matches the same call elsewhere in the file).

**Fixes applied to implementation (2):**
- `app.py` `baseline_estimate()` — moved the baseline-uniqueness check (`ERR_BASELINE_EXISTS`) ahead of the project-MEASURED state check, so "a second baseline attempt" yields `ERR_BASELINE_EXISTS` as PRD §3.3 explicitly mandates (after the first baseline the project is already ESTIMATED, which previously tripped `ERR_INVALID_STATE` first). Empty-estimate and first-baseline paths verified unaffected.
- `app.py` server runner — replaced the werkzeug dev server with `waitress` (added to requirements.txt; start.sh install-guard updated to check both flask and waitress). This eliminated the connection-reset flake (Connection reset by peer) that was failing the first test of the suite in 6/8 rounds under the per-test-server reboot load.

Final state: 8/8 parallel rounds at 69/69 passing.

## Step 8: Finalize PRD — 2026-06-26T16:00:23.000Z

Produced workspace/PRD_FINALIZED.md (minimal patch of PRD.md). Line counts: PRD.md 324, PRD_FINALIZED.md 324 (net line delta 0; one §3.12 paragraph rewritten in place, +~1100 chars / ~+0.3%).

Changes (1):
- §3.12 — insert — Pinned that in baseline promotion the baseline-uniqueness check (ERR_BASELINE_EXISTS) is evaluated before the project-workflow-state (MEASURED) check, while the estimate's own DRAFT status check still comes first; project-MEASURED and then ERR_EMPTY_ESTIMATE follow — implementation/app.py:426-441.

Why only one edit: Of the six Step 7 diff items, five are pure test/fixture/infrastructure issues whose behavior PRD already pins verbatim (cancel-without-reason → §3.8 already states ERR_CANCEL_NOT_ALLOWED; permit-filing stale snapshot → §3.4+§2.8; window-cancel fixture → §3.6; shared-crew helper stale snapshot → no PRD relevance; material-order 201 → §4; waitress runner → non-behavioral). Only baseline-uniqueness ordering is a genuine PRD ambiguity (§3.12 generic ordering vs §3.3 second-baseline promise), pinned per impl.

Pre-edit search log: subject = precedence of ERR_BASELINE_EXISTS vs ERR_INVALID_STATE in baseline_estimate(); enumerated all BASELINE_EXISTS/ERR_INVALID_STATE/MEASURED sites (grep), confirmed single raise site app.py:435, full handler order estimate-DRAFT→uniqueness→MEASURED→empty; wording scoped exception to project-workflow-state check only, preserving estimate-DRAFT-first.

## Step 9: Complete PRD — 2026-06-26T16:07:26.000Z

Produced workspace/PRD_COMPLETED.md via full PRD-vs-implementation scan. Source PRD_FINALIZED.md 324 lines / 49,880 chars → PRD_COMPLETED.md 324 lines / 52,952 chars (line delta 0, all in-paragraph inserts/revisions; char delta +3,072).

Counts: ambiguity-pins 7, mismatch-revisions 3.

Per-change log:
- §2.1 (StaffMember identity) — revise — mismatch — only staff X-User-ID comparison is the draw-release segregation check (with approval-time stamping); no general FK==X-User-ID ownership check. — app.py:1172
- §2.1 (HomeownerClient identity) — revise — mismatch — HomeownerClient access is role-membership only, no owner-scoping. — app.py:195-200, 1281-1293
- §2.4 (Versioning) — insert — ambiguity — version initial value = 1. — helpers.py:177
- §3.1 (Registration) — revise — mismatch — email lowercased but NOT uniqueness-enforced (no conflict code in catalog). — app.py:104, 132
- §3.1 (Project origination) — insert — ambiguity — non-existent project_manager_id → ERR_NOT_FOUND; wrong role_code → ERR_INVALID_REQUEST. — app.py:164-167
- §3.1 (Project read/list) — insert — ambiguity — fetch role-gated only (not owner-restricted); list applies no implicit owner-scoping. — app.py:188-200
- §3.2 (Measurement) — insert — ambiguity — non-existent estimator_id → ERR_NOT_FOUND; wrong role_code → ERR_INVALID_REQUEST. — app.py:272-275
- §3.4 (HOA review) — insert — ambiguity — both approve and deny require SUBMITTED (else ERR_INVALID_STATE); approval has no compliance-axis side effect. — app.py:601, 615-623
- §3.10 (Progress draw request) — insert — ambiguity — at request only work_schedule_id existence + milestone_pct range validated; window-COMPLETED & project-IN_PROGRESS deferred to approval. — app.py:1089-1101 vs 1144-1151
- §3.11 (Financing decide) — insert — ambiguity — DTI gate before principal gate; computed monthly_payment_cents/dti_ratio + status=DECLINED persisted even on failing 422. — app.py:1314-1325
- §3.12 (Validation order, segregation) — insert — ambiguity — on draw release path draw resolves first (ERR_NOT_FOUND) before segregation; other existence deferred until after segregation. — app.py:1169-1174
- §3.12 (Validation order, body) — insert — ambiguity — path ids → body field shape/type/enum (ERR_INVALID_REQUEST) → body-FK existence (ERR_NOT_FOUND) → numeric-range (ERR_INVALID_REQUEST / ERR_VALIDATION_RANGE). — app.py:265-278, 327-336, 1250-1263, 935-943

## Pipeline Complete — 2026-06-26T16:07:26.000Z

All 9 steps executed end to end. Final state: 69 tests passing in all 8 parallel stability rounds. PRD_COMPLETED.md present on disk (termination signal). Task directory contains SCAFFOLD.yaml + 2 design indices, worklog.md, test_helpers/ (9 files), test_suite/ (10 files, 69 tests), workspace/ (INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/ with 8 passing results files).
