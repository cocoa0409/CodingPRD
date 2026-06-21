# Worklog — task_0329_roofing_storm_restoration

Scenario: Roofing & Storm-Restoration Contractor: lead/inspection & damage assessment, scope & measurement (aerial) estimate, material order & delivery, crew scheduling, draw/progress payment, permit & inspection, change order, workmanship warranty.

Scaffold difficulty: Expert (passed to scaffold-generator only).

## Step 1: Create task directory — 2026-06-13T09:08:38.000Z

Created `tasks/task_0329_roofing_storm_restoration/` and `tasks/task_0329_roofing_storm_restoration/workspace/`.

## Step 2: Generate scaffold (Expert) — 2026-06-13T09:26:09.000Z

Generated a complete **Expert**-difficulty scaffold for the Roofing & Storm-Restoration Contractor scenario. All three files written (SCAFFOLD.yaml 1366 lines, SCAFFOLD_DIFFICULTY_DESIGN.yaml 1275 lines, SCAFFOLD_CORNER_DESIGN.yaml 1743 lines); `scaffold_lint.py` returns **`VERDICT: clean lint`** (0 violations across 595 calls).

**Complexity profile:** Ledger-reconciliation primary + workflow-orchestration secondary; **flat** topology (peer entities via FK, no nested URLs); **branching** state machines; `peer_roles`; layers = dual-variant calc, cascading side effects, optimistic concurrency, temporal windowing.

**Entities (12):** Job (ledger anchor), Estimator (immutable ref data, `common_fields:false`), Crew, Inspection, Estimate, EstimateLineItem, MaterialOrder, CrewAssignment, Permit, Draw, ChangeOrder, Warranty.

**State machines (9, all fully connected):** Job (LEAD→INSPECTED→ESTIMATED→{CONTRACTED→IN_PRODUCTION→COMPLETED | LOST}), Inspection, Estimate, MaterialOrder, CrewAssignment, Permit, Draw (REQUESTED→{DISBURSED|REJECTED}), ChangeOrder (PROPOSED→APPROVED→{APPLIED|VOIDED}), Warranty.

**Calculations (6):** `estimate_total` (aerial vs field dual-variant, pinned round-per-line-then-sum), `draw_amounts` (waterfall with retainage, progress vs final-draw variants), `material_order_sizing` (tiered freight, MIN_BUNDLES floor, ceil), `warranty_refund` (prorated vs short-rate decay), `crew_window_overlap` (half-open intervals), `permit_inspection_buffer` (closed + 24h buffer). All test asserts are literals computed in Python.

**Key validations (11, priority-ordered):** auth → forbidden → existence → FK existence → missing-field → invalid-request(422) → state(409) → cross-entity referential → temporal-overlap → fiscal → OCC(412). Two `concurrency_rules` (draw-create and change-order-apply, both OCC on `Job.version` → `ERR_STALE_JOB_VERSION` 412).

**Endpoints (55):** business actions plus GET single-resource/list/sub-resource endpoints for FK reverse-reachability, and one `/_clock/set` test-driving endpoint. **Errors (29).** **Roles (3):** FieldAdjuster (opaque), Estimator (entity_backed), ProductionManager (opaque).

**Difficulty design:** all 9 §0.5 rules × exactly 2 instances = 18, each grounded in §1.1–§1.6 with differentiation honored. **Corner design:** 38 active instances + 3 `excluded_because` stubs. All 56 instance names unique across both design files.

## Step 3: Copy INSTRUCTION.md — 2026-06-13T09:26:28.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-13T09:32:42.000Z

Generated `workspace/PRD.md` (296 lines) — a prose PRD for the **Roofing Storm Restoration API** (ledger-reconciliation + workflow-orchestration domain, flat top-level topology). DIFFICULTY/CORNER design files withheld.

**Document skeleton:** §1 Introduction (money-vs-trust framing); §2 Global Specs (11 subsections: RBAC + role identity translation, verbatim envelope, pagination, common properties + logical clock, monetary round-half-up, Job conserved ledger, state/version/cascade semantics, nested FK validation order, full 11-level validation priority order, Job-ledger OCC); §3 Business Logic (10 lifecycle-staged subsections: lead/inspection → estimates/line-items → contracting → materials → permitting → production/crews → draws → change orders → completion → warranty); §4 endpoint table (55 endpoints, 4 cols); §5 error table (29 errors, 2 cols).

**Entities (12):** Job, Estimator (reference-data, id/created_at only), Crew, Inspection, Estimate, EstimateLineItem, MaterialOrder, CrewAssignment, Permit, Draw, ChangeOrder, Warranty.

**Calculations covered:** estimate_total (round-per-line-then-sum, AERIAL contingency uplift vs FIELD); draw_amounts (gross-to-date, incremental gross_eligible_cents, progress vs final-draw retainage); material_order_sizing (max(12, ceil(...×1.15×3)), 80 lb/bundle, 3-tier freight); warranty_refund (floored elapsed months, PRORATED vs SHORT_RATE 0.90); crew_window_overlap (half-open, back-to-back allowed); permit_inspection_buffer (closed interval, 24h buffer inclusive). OCC on both expected_job_version write endpoints → ERR_STALE_JOB_VERSION (412); line-item expected_estimate_version distinguished.

**Hard Contracts:** Contract 1 (Field-Name Coverage) PASS (63/63); Contract 2 (Rule Coverage) PASS (11 validations, 2 OCC, all state transitions, 6 calculations, 29 error IDs, sibling-branch symmetry); Contract 3 (§3 Path Purity) PASS (0 path tokens). §2.2 byte-identical to canonical block.

## Step 5: Generate unit tests — 2026-06-13T09:51:03.000Z

Generated test infrastructure from the two design indices (only test source).

**Helper modules — `test_helpers/` (9 files):** types.py (status/role/value enums + entity TypedDicts; Estimator id+created_at only), api_client.py (55 endpoint methods incl. /_clock/set), api_errors.py (28-member ApiErrorId + HTTP status map), assertions.py (per-entity + assert_job_ledger_conserved), factories.py, constants.py, test_users.py (3 roles, entity_backed Estimator builder), fixtures.py (5-tier composite setup to ESTIMATED/CONTRACTED/IN_PRODUCTION/COMPLETED/active-warranty), __init__.py.

**Test suite — `test_suite/` — 12 files, 71 tests:**
- **Queue A (Difficulty): 36 tests, all 18 instances × exactly 2 tests each.** All 9 rules covered.
- **Queue B (Corner): 35 tests, all 35 non-stub instances × ≥1 test.** The 3 `excluded_because:` stubs not translated; cross-references resolve.

Every test docstring carries exactly one verbatim PRD citation + one `Design:` tag. No skip/xfail, no scaffold-leakage, no dual-tags.

**Deviations from literal YAML values (PRD-first adjudications, not skips):**
1. `material_sizing_nonlinear_min_ceil_tier` freight: YAML asserts 21500, but PRD §3.4 freight formula uniquely yields **18500** for 5520 lbs (`12500 + ceil((5520-4000)/1000)*3000`). Asserted PRD-faithful 18500.
2. `warranty_prorated_vs_short_rate_diverge` clock: instance setup advanced 6 months but asserted refunds require 18 months elapsed. Set cancel-time clock to 2027-07-01 so PRD §3.10 formula produces the asserted divergence.

No instances skipped — all 18 difficulty + 35 non-stub corner instances passed the PRD-first two-condition filter.

## Step 6: Generate implementation — 2026-06-13T09:51:03.000Z

Built a complete Python + Flask in-memory REST API in `workspace/implementation/`.

**Files:** start.sh (guards pip install on `import flask` check, then `exec python3 app.py`; binds 0.0.0.0:$PORT default 10000, foreground), app.py (Flask entry, blueprint registration, JSON-envelope error handlers, threaded=True), errors.py, response.py (meta/response_type/data envelope, req_ IDs, 3-digit ISO8601, pagination meta), db.py (empty in-memory store, **no seeding**), middleware.py (X-User-ID/X-User-Role auth + RBAC), validators.py (priority-ordered checks + round-half-up), clock.py (logical UTC clock), timeutil.py; services/ (calculations.py, jobledger.py); routes/ (reference, jobs, inspections, estimates, material_orders, crew_assignments, permits, draws, change_orders, warranties).

**Endpoints — all 57 from the PRD table** (11 entities × create/get/list + lifecycle transitions + POST /_clock/set). Estimator immutable (id+created_at only).

**State machines (9):** Job, Inspection, Estimate (DRAFT→FINALIZED→SUPERSEDED), MaterialOrder, CrewAssignment, Permit, Draw (atomic REQUESTED→DISBURSED; REJECTED persisted only on non-version business-precondition failures), ChangeOrder, Warranty.

**Calculations:** estimate_total (round-per-line-then-sum + AERIAL uplift), draw_amounts (gross-to-date − disbursed_gross; retainage 0 when final), material_order_sizing (max(12, ceil(squares·1.15·3)), weight·80, tiered freight), warranty_refund (prorated remaining months, PRORATED vs SHORT_RATE ·0.90, double rounding).

**Key behaviors:** cascades (draw→ledger; change-order apply→contract/remaining + re-size of ORDERED material orders only; permit-final PASS→CLOSED; warranty activate→retainage release); OCC via expected_job_version→412 ERR_STALE_JOB_VERSION on draws & change-order apply; half-open crew overlap; closed-interval 24h permit-final buffer (boundary inclusive); validation precedence per PRD §2.9. Storage in-memory only, no seeding. Two end-to-end smoke suites passed; `bash start.sh` boots and serves.

**Notable interpretations:** /jobs/{id}/contract fires ERR_ALREADY_CONTRACTED before generic ESTIMATED state check; change-order apply ordering follows §2.9 (fiscal ERR_CONTRACT_BELOW_DISBURSED before OCC); optional expected_estimate_version on line-item append maps mismatch to 412 ERR_STALE_JOB_VERSION.

## Step 7: Run tests and iterate to green — 2026-06-13T09:55:37.000Z

**Iterations run:** 1 (a single 8-round parallel stability sweep). All 8 concurrent rounds returned `passed=71, total=71, failed=0, errors=0, skipped=0`. No flakiness surfaced — the union of failing tests across all 8 rounds is empty.

**Tests deleted:** None. Every test passed, so no STEP 1 (PRD-silence / non-unique-derivability) deletion was warranted.

**Fixes applied to test_helpers/:** None required.

**Fixes applied to implementation/:** None required.

**Notes on the diagnostic process:**
- Fully read PRD, INSTRUCTION, all 11 implementation source files (app, db, errors, middleware, response, validators, clock, timeutil, services/calculations, services/jobledger, all 10 route modules), all 9 test_helpers modules, and all 12 test_suite files before running, to understand the contract end-to-end.
- Implementation is in-memory only (plain dicts in db.py, no disk/SQLite/JSON persistence), so per-test-server reboots via start.sh wipe all state. The logical clock (clock.py) resets to wall-time on each fresh boot, and start.sh installs Flask only when missing to avoid boot-time contention under 8x concurrent load.
- Environment note: Python 3.9.6; timeutil.parse_iso8601 correctly strips trailing `Z` before datetime.fromisoformat, so ISO timestamps with `Z` parse fine — exercised by clock/warranty and crew/inspection-window tests, all passed.

Verified independently by orchestrator: all 8 results.{1..8}.json show passed=71 total=71 failed=0 errors=0.

## Step 8: Finalize PRD — SKIPPED — 2026-06-13T09:55:37.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, and 0 implementation/ fixes (zero iterations beyond baseline). PRD.md already determined every behavior the implementation exhibits. No PRD_FINALIZED.md produced.

## Step 9: Complete PRD — eliminate residual ambiguity/mismatch — 2026-06-13T10:01:26.000Z

Produced `workspace/PRD_COMPLETED.md` from `PRD.md` (PRD_FINALIZED.md absent → base = PRD.md) with six minimal inline edits, full impl scan.

**Line counts / char delta:** PRD.md = 296 lines, 43,049 chars → PRD_COMPLETED.md = 296 lines, 44,685 chars (+1,636 chars). No new lines/paragraphs/sections (all in-paragraph).

**Counts:** ambiguity-pins = 5, mismatch-revisions = 1.

**Per-change:**
- §3.2 — insert — ambiguity — pinned that final_total_cents (not just line_subtotal_cents) is recomputed on every line-item append; DRAFT estimate carries live running final_total_cents; both totals init to 0; finalization freezes last-append values — routes/estimates.py:71-79,127.
- §3.4 — insert — ambiguity — pinned delivered_short is null at order creation, only overwritten when boolean supplied on deliver — routes/material_orders.py:37,79-84.
- §3.7 — insert — ambiguity — pinned a REJECTED draw's gross_eligible_cents/retainage_cents/net_disbursed_cents/is_final are null; OCC/version failure persists no draw at all — routes/draws.py:24-38,77-80.
- §3.7 — revise — mismatch — corrected parenthetical: any cumulative_pct outside (0,1] yields ERR_PCT_OUT_OF_RANGE (422); only non-numeric yields ERR_INVALID_REQUEST — routes/draws.py:55-62.
- §3.10 — insert — ambiguity — pinned start_at + term_months uses calendar-month arithmetic with same day/time-of-day and last-valid-day clamping — services/calculations.py:106-120.
- §3.10 — insert — ambiguity — pinned calendar-month elapsed-months formula `(cur.year-start.year)*12 + (cur.month-start.month)`, decremented when current day/time-of-day hasn't reached start_at's, floored at 0 — services/calculations.py:83-90.

Checked-and-unchanged (PRD already pins or impl matches prose): RBAC/ownership (§2.1), envelope/pagination (§2.2-2.3), validation priority incl. fiscal-before-OCC on change-order apply (§2.9), estimate round-per-line-then-sum + AERIAL/FIELD (§3.2), contract binding + supersede cascade (§3.3), material sizing/freight tiers incl. "part thereof" ceil (§3.4), permit-final buffer (whole-hours wording observably equivalent to fractional `<24`) + crew half-open overlap (§3.5-3.6), draw math + ledger cascade (§3.7), change-order apply cascade + re-sizing (§3.8), completion guards (§3.9), warranty activation/retainage-release + refund roundings (§3.10).

## Pipeline complete — 2026-06-13T10:01:26.000Z

All 9 steps done. Final state: 71/71 tests pass across all 8 stability rounds. Artifacts: SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml + SCAFFOLD_CORNER_DESIGN.yaml, workspace/PRD.md, workspace/PRD_COMPLETED.md (Step 8 skipped → no PRD_FINALIZED.md), test_helpers/ (9 files) + test_suite/ (12 files, 71 tests), workspace/implementation/ (Python+Flask, in-memory).
