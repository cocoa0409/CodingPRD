# Worklog — task_0132_moving_relocation

Scenario: Moving & Relocation Booking — inventory survey/cubic-feet estimate, binding vs non-binding estimate, packing/crating add-on, valuation coverage (released vs full-value), long-haul vs local hourly, crew/truck dispatch, storage-in-transit, damage claim. Difficulty: Expert.

## Step 1: Create task directory — 2026-06-03T17:37:49.000Z

Created `tasks/task_0132_moving_relocation/` and `tasks/task_0132_moving_relocation/workspace/` (pre-allocated index 0132; no scan performed per orchestration instructions).

## Step 2: Generate scaffold (Expert) — 2026-06-03T18:02:51.000Z

All three files generated, parse cleanly, and pass `scaffold_lint.py` with a clean verdict.

Generated the three scaffold artifacts for **task_0132_moving_relocation** at **Expert** difficulty. All files are in `tasks/task_0132_moving_relocation/`:
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, single top-level key)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, single top-level key)

**Complexity profile:** primary archetype *pricing_engine* + secondary *temporal_windowing*; flat entity topology; parallel state-machine shape; segregation-of-duties role model; layers: optimistic_concurrency, dual_variant_calculation, cascading_side_effects, rate_threshold_triggers.

**Scale (Expert band):**
- **12 entities** — Customer, MoveJob (hub, parallel job_status × payment_status), InventorySurvey, SurveyItem, Estimate, PackingOrder, Truck, Crew, Dispatch, StorageLot, DamageClaim, ClaimItem.
- **45 endpoint definitions** (above the 20–32 ceiling — driven by the 12 mandatory FK reverse-reachability list GETs, per-entity single GETs needed for lint segment derivation, and 12 action endpoints for 5 state machines; accepted per the skill's "guidelines not hard rules" and the FK-reachability overage note).
- **27 error codes** (all referenced by a validation row or design test), **26 validation rules** (priority-ordered), **5 roles** (Customer entity_backed; Estimator/Dispatcher/ClaimsAdjuster/PlatformAdmin opaque), **2 concurrency rules** (OCC on MoveJob.version for estimate-create and SIT-waive).

**5 state machines:** MoveJob (parallel dimensions), Estimate (cyclic DRAFT↔REVISED→REVISED), Dispatch (branching to COMPLETED/CANCELLED), DamageClaim (branch-with-revert APPROVED→UNDER_REVIEW), StorageLot (linear with accrual).

**7 calculations** including 3 dual-variant ones across different entity domains: estimate_total (long-haul cwt tariff vs local hourly), final_charge_reconciliation (binding-locked vs non-binding actual-weight re-rate), claim_settlement (released $0.60/lb vs full-value repair/replacement-minus-deductible); plus cubic_feet_rollup, packing_total, valuation_premium, sit_accrual. All formula-derived test asserts are pre-computed literals (verified in code, e.g. long-haul estimate 666864¢, non-binding final 783067¢, SIT 51400¢).

**Difficulty design:** all 9 rules × 2 instances = 18 instances. Notable Expert mechanics: round-per-component-then-sum rounding order, dual-variant divergence on two entity domains, depth-3 cancel cascade (job→dispatch→freed truck/crew window proven by re-dispatch), priority conflicts (SoD vs invalid-state on claim approve; capacity vs truck-overlap on dispatch), boundary precision (declared-value ≥ floor; crew 90-min turnaround buffer), two resource overlap semantics (truck half-open touch-allowed vs crew buffered), two compensating invariants on different conserved quantities (gross_charges_cents money conservation on SIT waive; refunded_cents payout-credit conservation on claim reopen).

**Corner design:** 35 active + 4 excluded_because stubs covering CRUD, not-found, enum/required-field, duplicate uniqueness, invalid/terminal transitions, all error triggers, RBAC denials, OCC, and immediate-consistency.

One design correction applied during generation: the segregation-of-duties rule was originally placed on estimate-accept, but since only Customers accept (and the estimator is opaque), that SoD was unenforceable — it was moved entirely to damage-claim adjudication (same-role file-vs-adjudicate), and the dependent §1.8 priority-conflict instance and §1.9 stubs were updated accordingly.

`scaffold_lint.py` verdict: **clean lint** — all 507 §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability.

## Step 3: Copy shared files — 2026-06-03T18:03:23.000Z

Copied `INSTRUCTION.md` → `tasks/task_0132_moving_relocation/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-03T18:09:50.000Z

Generated `workspace/PRD.md` for the **Moving & Relocation Booking API** (Expert: 12 entities, 31 endpoints, 27 errors, 5 state machines, parallel job/payment state, dual-variant pricing, OCC). ~302 lines, ~45 KB.

**Structure:** §1 Introduction (business context, five roles, parallel job/payment ledger theme); §2 Global Specifications (2.1 RBAC, 2.2 Response Structure byte-identical to source, 2.3 Pagination, 2.4 Common Properties & Version Semantics with SurveyItem/ClaimItem as common_fields:false exceptions, 2.5 Nested Retrieval, 2.6 OCC both rules, 2.7 Job Ledger conservation, 2.8 Precision round-per-component-then-sum, 2.9 Parallel Dimensions & cascades); §3 Business Logic (12 lifecycle/process subsections incl. inventory rollup, packing, estimate pricing engine, acceptance/payments, scheduling, departure/delivery/reconciliation, storage & waivers, cancellation cascades, damage claims/settlement, validation ordering); §4 Endpoint table; §5 Error table.

**Hard contracts — all PASS:** field coverage 78/78 present, 0 missing; rule coverage (validation ordering, 2 OCC rules, 5 state machines, 7 calculations, 26 validation conditions, side-effects/cascades) 0 missing; path-purity §3 (411 tokens scanned, 0 paths/methods). §2.2 byte-identical to canonical source.

**Confirmation:** read only `SCAFFOLD.yaml` (+ skill spec, fixed §2.2 source, reference example-prd.md). Did NOT open/grep/reference either design YAML.

## Step 5: Generate unit tests — 2026-06-03T18:25:42.000Z

Generated complete test infrastructure for `task_0132_moving_relocation` (Expert PRD: 12 entities, 31 endpoints, 27 errors, 5 state machines).

**Stage 1 — `test_helpers/` (9 files):** types.py (entity TypedDicts + 11 enums; SurveyItem/ClaimItem omit updated_at/version as append-only line items); api_client.py (one method per endpoint, all 31); api_errors.py (27 error IDs + HTTP-status map); assertions.py, factories.py, constants.py, test_users.py (Customer = entity_backed → per-instance make_customer_headers; opaque-role builders for ClaimsAdjuster SoD control); fixtures.py (5-tier composite helpers QUOTING→BOOKED→IN_TRANSIT→DELIVERED, plus released storage lots and approved claims, with identity threading); __init__.py barrel export.

**Stage 2 — `test_suite/` (conftest + 8 domain files):** 71 test functions total, organized by concern (pricing, claims, estimate lifecycle, dispatch/delivery reconciliation, dispatch scheduling, storage/waivers, cancellation cascade, CRUD/access).

**Coverage (clean audit):** Queue A (Difficulty) **18/18 instances** translated, 2 tests each (36 tests), zero skips. Queue B (Corner) **35/35 non-stub instances** translated, ≥1 test each (35 tests), zero skips. The 4 `excluded_because:` stubs correctly NOT translated.

**Validation passed:** every test carries exactly one `Design:` tag (0 untagged/dual-tagged/dangling); every PRD citation verbatim (survives literal grep of PRD.md); no scaffold/§1.x leakage; no skip/skipif/xfail markers; all helper imports resolve.

## Step 6: Generate implementation — 2026-06-03T18:25:42.000Z

Generated complete Python + Flask implementation at `workspace/implementation/`.

**Files:** start.sh (guarded-install foreground launcher); requirements.txt (flask>=2.0); app.py (app factory, blueprint registration, error handlers, binds 0.0.0.0:$PORT default 10000, threaded=True); db.py (in-memory store + id/timestamp/version helpers); errors.py (ApiError + 27-entry error_id→HTTP-status table verbatim from PRD §5); response.py (envelope builders PRD §2.2); middleware.py (X-User-ID/X-User-Role auth + RBAC); serialize.py (strips internal _-prefixed keys); services/calculations.py (7 calcs); services/common.py (pagination, datetime parsing, validators, balance recompute); routes/ (8 blueprints across 12 entities/45 endpoints).

**Storage:** pure in-memory module-level dicts keyed by id + monotonic _seq counter for created_at-ascending sort. No seeding, no disk, no external persistence. All entities built only through declared endpoints. `bash start.sh` verified to boot and serve HTTP 200 on 0.0.0.0.

**Calculation literals verified to match design:** cubic-feet rollup 370cf/2590lb, packing 38300, valuation_premium 14432, long-haul estimate 666864 (linehaul 543900, accessorial 24000), local estimate 70200 (labor 57000), SIT 51400 (7 billable days), non-binding final 783067, claim settlements 2400 (RELEASED) / 40000 (FULL_VALUE), binding+addendum re-rate 783067, binding-locked balance 566864.

**Interpretation calls:** (1) MoveJob.version bumps only on estimate generation + SIT waive (per §2.4); all other ledger mutations touch updated_at only — load-bearing for the two OCC checks. (2) "The linked packing order" singular → selects most-recently-created PackingOrder by move_job_id. (3) Reopen on CLOSED job → ERR_INVALID_STATE (transition undefined), not ERR_NOT_DELIVERED. (4) Delivery gross recompute: extras = gross − accepted_estimate_total, gross = final + extras. (5) Unknown route/405 → ERR_NOT_FOUND (404) to keep envelope standard.

## Step 7: Run tests and iterate — 2026-06-03T18:28:00.000Z

**Iterations run:** 1 (a single 8-round parallel sweep). All 8 rounds passed cleanly on the first sweep — 71/71 tests passed, 0 failed, 0 errors, 0 skipped in every round. Independently re-verified by the orchestrator: results.{1..8}.json all show passed=71 failed=0 total=71 errors=0.

**Command used:** `prd-bench-local-run --start-command "cd .../workspace/implementation && bash start.sh" --test-dir .../test_suite --isolation per-test-server --timeout 120 --test-timeout 30 --results-file .../results.${i}.json` (i=1..8 concurrent, joined with `wait`).

**Tests deleted:** None. **Fixes applied to test_helpers/:** None. **Fixes applied to implementation/:** None.

PRD coverage was not in question — every test passed against the existing PRD-faithful implementation on the first stable sweep. No flakiness surfaced across 8 concurrent rounds. (One transient triage false-alarm in the subagent's first script — filtering on `outcome` instead of the runner's `status`/`passed`/`total` counters — was self-corrected; authoritative counters confirm fully green.)

## Step 8: Finalize PRD — SKIPPED — 2026-06-03T18:28:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes (zero iterations beyond baseline). `PRD.md` already determined every behavior the implementation exhibits at the Step 7 fix sites, so `PRD_FINALIZED.md` is not produced. Step 9 will run from `PRD.md` directly.

## Step 9: Complete PRD — eliminate residual ambiguity — 2026-06-03T18:35:00.000Z

Produced `workspace/PRD_COMPLETED.md` via full PRD-vs-implementation scan (started from `PRD.md` since Step 8 was skipped).

**Line counts:** PRD.md 301 → PRD_COMPLETED.md 301 (all edits in-paragraph). **Char delta:** 45,365 → 47,723 (+2,358).

**Counts:** 6 ambiguity-pins, 4 mismatch-revisions (10 total edits).

**Per-change log:**
- §2.4 — insert — ambiguity — `version` initial value pinned to 1 — db.py:60
- §2.6 — insert — ambiguity — non-integer `expected_move_job_version` rejected with ERR_INVALID_FIELD before version compare — estimates.py:83-84, storage_lots.py:118-119
- §3.3 — revise — ambiguity — `packing_lines` required (possibly empty) array, `crate_count` optional; per-line missing-key→ERR_VALIDATION, non-list/out-of-range numeric→ERR_INVALID_FIELD; amend leaves omitted/null fields unchanged — packing_orders.py:19-32,40,90-95
- §3.4 — insert — ambiguity — multi packing-order job reads most-recently-created for packing_cents — estimates.py:25-32 (orders[-1])
- §3.5 — insert — ambiguity — pinned ERR_INVALID_STATE for second deposit (payment_status≠UNPAID), balance while job not DELIVERED, and balance while payment_status≠DEPOSIT_PAID — move_jobs.py:121-122,131-134
- §3.6 — insert — ambiguity — truck-capacity check uses most-recently-created survey; no-survey job treated as 0 CF (check passes) — dispatches.py:26-32,64-68
- §3.7 — revise — mismatch — re-rate (BINDING addendum + NON_BINDING) holds surveyed total_cubic_feet/distance_miles/non-weight components at accepted-estimate values, changes only weight; actual_cubic_feet used solely for tolerance test, so LOCAL labor unchanged — calculations.py:199-220
- §3.8 — insert — ambiguity — release of non-IN_STORAGE lot or job not DELIVERED/IN_TRANSIT both rejected ERR_INVALID_STATE — storage_lots.py:75-79
- §3.10 — insert — ambiguity — reopen while linked job CLOSED rejected ERR_INVALID_STATE — damage_claims.py:187-188
- §4 — revise — mismatch — POST /move-jobs/{id}/payments returns 201 Created for both DEPOSIT and BALANCE (PRD's blanket "modify → 200" was wrong for payments) — move_jobs.py:127,142

**Key findings:** All RBAC role assignments, error-code→HTTP mappings, ledger conservation identity, pricing/valuation/SIT/settlement formulas, and round-per-component-then-sum discipline already matched PRD prose exactly. The only true mismatches were the payment status code (201 vs stated 200) and the §3.7 reconciliation cubic-feet basis; the rest was silence the implementation resolved with a specific choice.

---

## Pipeline complete — 2026-06-03T18:35:00.000Z

All 9 steps done. Final state: scaffold (3 YAMLs) + PRD.md + PRD_COMPLETED.md + test_helpers/ (9 files) + test_suite/ (conftest + 8 files, 71 tests) + implementation/ (Flask, in-memory). Test status: **71/71 passing across all 8 parallel stability rounds**. Step 8 skipped (zero Step 7 fixes); PRD_FINALIZED.md intentionally absent.
