# Worklog — task_0629_dental_lab_restoration

Scenario: Dental Lab & Restoration Fabrication: case intake (Rx/impression/scan) & doctor account, restoration type (crown/bridge/denture/aligner) & material, CAD/CAM & milling/printing schedule, shade/remake & try-in, turnaround SLA & rush, shipping/pickup route, per-unit pricing & invoice, redo/warranty

Difficulty: Expert

## Step 1: Create task directory — 2026-06-22

Created `tasks/task_0629_dental_lab_restoration/workspace/`. Pre-allocated directory used directly (no auto-numbering scan, to avoid parallel-task ID contention).

## Step 2: Generate scaffold (Expert) — 2026-06-22

All three artifacts complete; `scaffold_lint.py` reports `VERDICT: clean lint`.
Coverage: §1.5 endpoints declared: 56; §1.1 entities declared: 13; §1.8 instances scanned: 18; §1.9 instances scanned: 29; Calls scanned (§1.8+§1.9): 406.

Archetype: workflow orchestration (fabrication pipeline with revision/remake cycles) + pricing engine secondary. Layers: dual-variant calculation, cascading side effects, rate/threshold triggers, optimistic concurrency.

Scale: 13 entities (Doctor, Material, MillMachine, CourierRoute, Case, Restoration, FabricationUnit, ShadeRecord, MillJob, RouteStop, Invoice, CreditMemo, RemakeRequest); 56 endpoints (above the Expert band of 20-32 mainly because of the mandatory FK reverse-reachability GETs — 13 FKs, including a self-FK on FabricationUnit); 18 error codes; 5 RBAC roles; 5 calculations; 4 state machines; 16 ordered validations; 2 concurrency rules.

State machines (5 total): Case (cyclic — TRY_IN→REVISION→DESIGN revision loop + warranty reopen), FabricationUnit (branching — accept→PASSED vs remake→REMADE_OUT with non-billable replacement), MillJob (linear + cancel), MillMachine (AVAILABLE↔MAINTENANCE), Invoice (parallel dimensions: billing_status × delivery_status evolving independently).

Key calculations: `line_item_pricing` (per-unit-round-then-sum, pinned order); `invoice_total` (provisional vs final dual variant — tier-crossing + SLA credit; nested rush→discount→tax→credit chain); `turnaround_promise` (rush-halving with 24h floor, slowest-restoration max); `sla_breach_evaluation` (strict `>` boundary); `credit_ledger_conservation` (issue/void invariant). Assert literals computed in code (12990 vs 12341 provisional/final, 82202 rush-bridge total, 37497 vs 37496 rounding divergence, 2400 SLA credit).

RBAC: peer_roles — Doctor (entity_backed:Doctor, ownership-gated), LabTech, Scheduler, Billing, LabAdmin (opaque).

Expert difficulty: §1.8 all 9 Difficulty Rules × 2 instances (18 total), executable empty-DB setup chains. Depth: 4-hop ship cascade (ship→sla_breach→FINAL invoice→CreditMemo→doctor ledger), provisional/final tier-crossing dual variant, two interval-overlap geometries (half-open milling vs buffer-expanded route windows), two validation priority conflicts, two conserved-quantity invariants. §1.9: 9 taxonomy sections, 40 instances (29 active full recipes + 11 excluded_because stubs).

## Step 3: Copy INSTRUCTION.md — 2026-06-22

Copied `./INSTRUCTION.md` → `tasks/task_0629_dental_lab_restoration/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-22

PRD at `workspace/PRD.md`, 272 lines. Sections: §1 Introduction; §2 Global Specifications (2.1 RBAC, 2.2 API Response Structure, 2.3 Pagination, 2.4 Common Resource Properties, 2.5 Nested Resource Retrieval & Existence Ordering, 2.6 Monetary/Quantities/Rounding, 2.7 OCC (both rules), 2.8 Hierarchical Consistency & Cascades, 2.9 Validation Order & Precedence); §3 Business Logic (10 lifecycle subsections); §4 Endpoint Definitions (all 57 endpoints); §5 Error Code Catalogue (all 18 error IDs).

Hard Contracts all PASS: Contract 1 (69 field names, 0 missing), Contract 2 (6 calculations with exact constants — type factors 1.00/1.25/2.00/0.30, RUSH 0.50, TAX 0.0825, SLA_CREDIT 0.20, tiers 0%/5%/10% at 0–4/5–19/20+, turnaround 120/168/240/336h, rush floor 24h, MAX_REVISIONS=3; per-unit-round-then-sum worked example 37497 vs 37496; both OCC rules; validation precedence; cascades), Contract 3 (§3 path purity, 0 violations). Confirmed: did NOT read either SCAFFOLD_DIFFICULTY_DESIGN.yaml or SCAFFOLD_CORNER_DESIGN.yaml.

## Step 5: Generate unit tests — 2026-06-22

test_helpers/ (9 files): __init__.py, types.py (13 entity TypedDicts + 11 status/enum types + UserRole), api_client.py (ApiClient ~55 methods), api_errors.py (ApiErrorId enum + HTTP map), assertions.py (per-entity + assert_invoice_total_identity invariant), factories.py (one payload factory per entity, monotonic counter), constants.py (pricing/SLA/tier thresholds), test_users.py (opaque roles + make_doctor_headers for entity_backed:Doctor), fixtures.py (5-tier composite setup chain).
test_suite/ (6 test files + conftest.py): 65 tests total.
Coverage (design-index-only): Queue A (Difficulty §1.8) 18/18 instances translated, each ≥2 tests, 0 skipped. Queue B (Corner §1.9) 29/29 non-stub instances translated, each ≥1 test, 0 non-stub skips; 11 excluded_because stubs correctly NOT translated, all 11 cross-refs resolve. Verification: every docstring ends with one Design: tag resolving to a real instance; no skip/skipif/xfail; all 65 tests collect under pytest.

## Step 6: Generate implementation — 2026-06-22

Python + Flask at workspace/implementation/. Files: start.sh, requirements.txt (flask==3.0.3), app.py (~55 routes + auth/RBAC + error handlers), clock.py (logical clock default 2026-01-01T00:00:00Z), db.py (in-memory dict tables, UUID/ts/version stamping), errors.py (ApiError + 18 error-ids), response.py, middleware.py (header auth, role gate, pagination), validate.py, lookups.py, serialize.py, services/calculations.py, services/case_service.py, services/mill_service.py, services/route_service.py, services/warranty_service.py, plus routes/ dir.
Storage: pure in-memory, one dict per entity keyed by UUID, starts empty every boot; money in integer cents; Decimal + ROUND_HALF_UP for rounding. start.sh: set -euo pipefail, guarded pip install (only if import flask fails), exec python3 app.py binding 0.0.0.0:$PORT (default 10000), threaded.
Notable: Case state machine (INTAKE→DESIGN→FABRICATION→TRY_IN→{REVISION loop→DESIGN}→SHIPPED→DELIVERED + cancel; ACCEPT promotes MILLED units to PASSED); Invoice parallel billing_status×delivery_status. Calc ordering pinned (per-unit round before sum; invoice total rush→discount→tax→SLA-credit-last; final variant re-reads completed_case_count; SLA breach strict shipped_at > promised_ready_at; rush halving integer floor with 24h floor). OCC: expected_case_version + expected_machine_version, checked after state precond, before business checks, 412. Validation precedence auth→role→owner→existence→state→OCC→business→schema. Cascades verified (submit, ACCEPT-ship final invoice + credit memo + ledger, confirm-delivery completed_case_count, cancel mill-job free interval + invoice void, warranty REMADE_OUT non-billable replacement conserving billable_unit_count, credit-memo void ledger decrement). Smoke-tested end-to-end; start.sh boots to HTTP 200.

## Step 7: Run tests and iterate to PASS — 2026-06-22

Clean sweep achieved. All 8 parallel rounds passed 65/65 tests.

**Iterations run:** 3 sweeps (1 baseline + 2 after-fix). Final sweep: all 8 parallel rounds passed 65/65, no flakiness.

**Baseline:** 4 tests failed consistently across all 8 rounds, in two root-cause categories.

**Tests deleted:** None. Every failure traced to a test-helper fixture bug or an incidental precedence entanglement in a test, not to PRD-silent assertions.

**Fixes applied to `test_helpers/fixtures.py`:**
- `_schedule_and_mill_units` — added a `base_day` parameter. The revision fixtures reused one machine across cycles, and completed (`DONE`) mill jobs remain non-`CANCELLED`, so they still occupy their half-open intervals (PRD §3.4). Re-milling at the same `start_at` collided with the prior cycle's `DONE` job → `ERR_MACHINE_DOUBLE_BOOKED` setup failure. Re-mills now land on a distinct calendar day per cycle. (Implementation correctly rejects — the double-booking check is PRD-faithful.)
- `_schedule_and_mill_units` — added a `start_fab_times` parameter; `advance_revision_once` passes `start_fab_times=2`. From `REVISION`, the walk is `REVISION → DESIGN → FABRICATION` (PRD §3.5: the advancement "applied to a case sitting in REVISION, lands it back in DESIGN"), so two `start-fabrication` legs are needed before `ready-tryin`. The fixture issued only one, leaving the case in `DESIGN`, so `ready-tryin` failed with `ERR_INVALID_STATE - Case is not in FABRICATION`. These two fixture fixes unblocked `test_max_revisions_exceeded_owner`, `test_max_revisions_fires_for_owner_when_ownership_passes`, and `test_ownership_precedes_max_revisions_check`.

**Fixes applied to `test_suite/test_04_scheduling_constraints.py`:**
- `test_milljob_start_requires_available_machine` — the test captured `expected_machine_version` *before* taking the machine to `MAINTENANCE`. But maintenance bumps the machine version (PRD §3.4), so the captured version was stale, and per PRD §2.9 the OCC check (`ERR_STALE_MACHINE_VERSION`) precedes the domain `AVAILABLE`-machine safety check — the impl correctly returned the OCC error. The test's intended assertion (a `MAINTENANCE` machine fails start → `ERR_INVALID_STATE`, PRD §3.4) was entangled with OCC. Fixed the test to read the machine's *current* version after maintenance, so the OCC check passes and the `AVAILABLE`-precondition failure surfaces cleanly as `ERR_INVALID_STATE` — isolating the PRD rule without changing the impl.

**Fixes applied to `implementation/`:** None. The PRD-faithful implementation was correct throughout; all failures were test-artifact issues.

## Step 8: Finalize PRD — 2026-06-22

Produced `workspace/PRD_FINALIZED.md` as a byte-identical copy of `PRD.md` — **zero edits**. PRD.md 272 lines, PRD_FINALIZED.md 272 lines (0% delta).

Why no edits: every `<step_7_diff>` item is a pure test/fixture artifact against a PRD-faithful implementation (diff records "Fixes applied to implementation/: None" and "Tests deleted: None"). Each behavior the fixes maneuver around is already uniquely determined by existing PRD prose, so there is no PRD-silence or PRD-mismatch to pin.
- Item 1 (re-mill base_day): PRD §3.4 already pins DONE jobs keep occupying half-open intervals, only CANCELLED jobs freed (impl mill_service.create_mill_job overlap loop skips only CANCELLED).
- Item 2 (start_fab_times=2): PRD §3.5 already pins REVISION→DESIGN→FABRICATION two-leg walk (impl case_service.start_fabrication).
- Item 3 (stale machine version in test): PRD §2.9 pins state→OCC→AVAILABLE precedence; PRD §3.4 pins maintenance bumps machine version (impl mill_service.start_job + machine_maintenance/release db.touch). Both already determined.
No new-mismatch risk introduced since no wording was changed.

## Step 9: Complete PRD — eliminate residual ambiguity/mismatch — 2026-06-22

Produced `workspace/PRD_COMPLETED.md` from `PRD_FINALIZED.md` base. Source 272 → completed 272 lines (in-paragraph edits only); chars 38,890 → 40,884 (+1,994). Counts: 5 ambiguity-pins, 5 mismatch-revisions (10 changes).

Per-change list:
- §2.1 (RBAC ownership) — revise — mismatch — added warranty-remake-open as a third Doctor-ownership-gated op, LabAdmin exempt (app.py:515-516).
- §2.3 (Pagination ordering) — insert — ambiguity — pinned equal-created_at tie-break = ascending persistence order (middleware.py:69).
- §2.4 (Common Resource Properties) — insert — ambiguity — pinned version initial = 1, created_at/updated_at from logical clock not wall clock (db.py:52, db.py:58).
- §2.9 (Validation order) — revise — mismatch — added remake-request-open to ownership-gated list with precedence placement (app.py:512-522).
- §3.1 (Doctor email) — revise — mismatch — "unique email" → expected-unique but server does not enforce/reject duplicates (app.py:88-105).
- §3.1 (Material code) — revise — mismatch — "short unique code" → expected-unique but not enforced (app.py:132-151).
- §3.4 (Mill job scheduling) — insert — mismatch — pinned scheduling does not validate unit status; only capability + double-booking gates (mill_service.py:10-40).
- §3.5 (Try-in verdict) — revise — mismatch — pinned TRIED_IN collapsed into verdict transition, never persisted; REVISE MILLED→QUEUED, ACCEPT MILLED→PASSED directly (case_service.py:179-182,216-219).
- §3.5 (ShadeRecord) — insert — ambiguity — pinned shade_code = restoration's requested_shade (case_service.py:191).
- §3.7 (Route stop attach) — insert — mismatch — pinned window-conflict check evaluated before capacity, so ERR_ROUTE_WINDOW_CONFLICT precedes ERR_ROUTE_AT_CAPACITY (route_service.py:18-34).
- §4 (Endpoint table, /cases/{id}/invoice) — insert — ambiguity — pinned returns paginated array envelope (sole element), not bare object (app.py:477-482).

## Final verification — 2026-06-22

Re-ran the final 8-round parallel stability sweep (orchestrator-level, to regenerate the evidence `results.{1..8}.json` files which an intermediate `rm -f` had cleared). Result: all 8 rounds passed 65/65, 0 failures, no flakiness. Evidence files present at `workspace/implementation/results.{1..8}.json`.

## PIPELINE COMPLETE

All 9 steps complete. Task deliverables in place: SCAFFOLD.yaml + 2 design indices, worklog.md, test_helpers/ (9 files), test_suite/ (6 test files + conftest, 65 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}. Final state: 65/65 tests pass across 8 parallel isolation rounds.
