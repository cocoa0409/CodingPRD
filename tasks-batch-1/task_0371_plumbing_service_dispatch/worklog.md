# Worklog — task_0371_plumbing_service_dispatch

Scenario: Plumbing Service & Dispatch: service call (leak/drain/water-heater/repipe) & dispatch, flat-rate book & estimate, technician/route & ETA, parts/truck-stock inventory, permit & inspection, emergency/after-hours, membership/maintenance plan, warranty/callback

Difficulty: Expert (passed to Step 2 scaffold-generator only)

## Step 1: Create Task Directory — 2026-06-15T00:00:00.000Z

Created `tasks/task_0371_plumbing_service_dispatch/` and `tasks/task_0371_plumbing_service_dispatch/workspace/` (pre-assigned directory name; no scan/increment performed).

## Step 2: Generate Scaffold — 2026-06-15T00:00:00.000Z

All three scaffold artifacts are generated, validated, and lint-clean. Here is the summary.

## Task 0371 — Plumbing Service & Dispatch (Expert) — Scaffold Complete

**Files written** (all under `tasks/task_0371_plumbing_service_dispatch/`):
- `SCAFFOLD.yaml` (§1.0–§1.7, no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

**`scaffold_lint.py` verdict:** `clean lint` — 644 §1.8/§1.9 calls all conform to §1.5; all 16 FKs have reverse-reachability.

### Scaffold counts (§1.1–§1.7)
- **Entities: 15** — MembershipPlan, Customer, Technician, Inspector, FlatRateItem, Part, TruckStock, ServiceJob (hub), DispatchAssignment, Estimate, EstimateLine, Permit, InspectionVisit, Invoice, Callback
- **State machines: 5** — ServiceJob (cyclic, 9 states, reopen loop), DispatchAssignment, Estimate (cyclic revision loop), Permit (cyclic reapply-on-fail), Callback
- **Calculations: 4** — estimate_provisional_total, invoice_final_total, technician_callback_rate (all dual-variant), callback_warranty_check
- **Validations: 14** (priority-ordered, 8 categories)
- **Endpoints: 60** (flat topology, includes 1 `/_clock/set` test-driving endpoint)
- **Errors: 15**
- **Roles: 4** — OfficeManager (opaque), Dispatcher (opaque), Technician (entity_backed), Customer (entity_backed); peer_roles model
- **Concurrency rules: 2** — both OCC `expected_job_version` on ServiceJob (estimate-create and dispatch-create supersede races)

### Design-file instance counts
- **§1.8 (depth):** 9 rules × 2 = **18 instances**
- **§1.9 (breadth):** 9 sections, **39 instances** = 34 active + 5 `excluded_because` stubs

### Profile
Workflow-orchestration (secondary: temporal-windowing); layers: cascading side-effects, dual-variant calculation, optimistic concurrency, rate/threshold triggers; flat topology; cyclic state machines; immediate consistency. Endpoint count (60) sits above nominal Expert band — driven by 5 state machines' action triggers plus 16-FK reverse-reachability GETs, not padding.

No sibling `task_*/` directory was read.

## Step 3: Copy Shared Files — 2026-06-15T00:00:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-15T00:00:00.000Z

The PRD is complete. **Output:** `workspace/PRD.md` (~287 lines, 47KB).

### Section list
- §1. Introduction (3 paragraphs)
- §2. Global Specifications (2.1 RBAC all four roles; 2.2 API Response Structure; 2.3 Pagination; 2.4 Common Resource Properties & Versioning — three `common_fields:false` entities MembershipPlan/FlatRateItem/Part; 2.5 Nested Retrieval & Existence Ordering; 2.6 Validation Ordering priority 1–14; 2.7 OCC on Job-Scoped Creation, `expected_job_version`, ERR_STALE_JOB_VERSION/412; 2.8 Monetary Precision & Rounding; 2.9 Cascades)
- §3. Business Logic & Workflows (10 subsections: configuration; dispatch; estimate building/pricing; authorization/credit/permit cascade; work/permits/inspections; invoicing & provisional-vs-final divergence; cancellation; warranty callbacks & reopen cycle; technician callback rates; clock test-driving)
- §4. Endpoint Definitions (60 endpoints)
- §5. Error Code Catalogue (15 error IDs)

### Hard Contract reports: Contract 1 (Field-Name Coverage 68/68) PASS; Contract 2 (Rule Coverage — OCC×2, validations 1–14, 5 state machines, 4 calculations incl. constants 1.5/15000/8900/50000/12000/ROLLING_WINDOW=5/WARRANTY_DAYS=90/cutoff 18:00 UTC/30-min travel buffer) PASS; Contract 3 (§3 Path Purity, 380 tokens, 0 violations) PASS.

Confirmation: the two withheld design files were NOT read, opened, grepped, or referenced.

## Step 5: Generate Unit Tests — 2026-06-15T17:12:20.000Z

Subagent (agentId a34af9c46a4941368) completed all file writes but its returned summary was lost to a connection-level socket error after 29 tool uses. Artifacts verified on disk by orchestrator:
- `test_helpers/`: __init__.py, api_client.py, api_errors.py, assertions.py, constants.py, factories.py, fixtures.py, test_users.py, types.py — all present, all `py_compile`-clean.
- `test_suite/`: conftest.py + test_01_crud_and_validation.py (11 tests), test_02_state_machines_and_rbac.py (19 tests), test_03_pricing_calculations.py (8 tests) = **38 tests total**, all `py_compile`-clean.
- Every one of the 38 tests carries a `Design:` tag (11/19/8 match the per-file test counts exactly — no untagged tests).

(Subagent's own coverage-audit / design-adjudication narrative was not captured due to the socket error; the Step 7 iteration loop will surface any residual gaps as failures.)

## Step 6: Generate Implementation — 2026-06-15T17:12:20.000Z

Subagent (agentId a2929c0db3b41aa85) completed all file writes but its returned summary was lost to a connection-level socket error after 32 tool uses. Artifacts verified on disk by orchestrator:
- `workspace/implementation/`: start.sh (foreground launcher, lazy pip-install, `exec python3 app.py`), requirements.txt (Flask==3.0.3), app.py (60KB), plus modules clock.py, db.py, errors.py, helpers.py, middleware.py, pricing.py, response.py, serializers.py — all present, all `py_compile`-clean.
- start.sh guards pip install behind an import check to avoid boot contention under the 8-round concurrent sweep.

(Subagent's own design narrative was not captured due to the socket error; Step 7 iteration loop validates behavior.)

## Step 7: Run Tests and Iterate — 2026-06-15T17:12:20.000Z

All 8 parallel rounds pass with 38/38. Clean sweep. Exiting with the summary.

## Summary

**Iterations run:** 2 (1 diagnostic baseline showing 36/38, 1 verification showing 38/38 across all 8 parallel rounds).

**Tests deleted:** None. Both failures were test-bugs fixable in-place without losing coverage.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py`, `setup_permit_job_issued` fixture — changed the customer's `service_address` from `f"1 {jurisdiction} St"` to just `jurisdiction`. The fixture assumed the implementation extracts an embedded jurisdiction code from the address; PRD §3.4 says only "a `jurisdiction` derived from the customer" and is silent on the derivation method, so the PRD-faithful implementation legitimately uses the whole `service_address` as the code. Setting the address equal to the bare jurisdiction code makes the inspector/permit jurisdictions match under any reasonable derivation. (Fixed the setup error `ERR_LICENSE_REQUIRED - Inspector jurisdiction mismatch` in `test_permit_reapply_cycle_failed_to_issued_increments_count`; the sibling `test_schedule_inspection_jurisdiction_mismatch_returns_license_required` still passes since its wrong inspector `CITY99` ≠ permit `CITY04`.)

**Fixes applied to `test_suite/`:**
- `test_suite/test_02_state_machines_and_rbac.py`, `test_immediate_consistency_committed_credit_visible_in_same_flow` — replaced the hard-coded `assert cust_after["committed_credit_cents"] == 20000` with `assert cust_after["committed_credit_cents"] == scenario["estimate"]["estimate_total_cents"]`. The test author's literal `20000` omitted the PRD §3.3 base trip fee of 8900 cents (labor-after-discount 20000 < 50000 waive threshold, no plan), so the correct estimate total is 28900. The PRD rule cited (§3.4: "increased by that same estimate total") is exactly that `committed_credit_cents == estimate_total_cents`, so asserting against the estimate's actual total is the more PRD-faithful expression of the rule than any hard-coded number.

**Fixes applied to `implementation/`:** None. The implementation's pricing (28900) and jurisdiction-derivation were both PRD-faithful; both failures traced to test artifacts.

Final state: 38/38 passing in every one of the 8 concurrent rounds, no flakiness.

## Step 8: Finalize PRD — 2026-06-15T17:19:00.000Z

Done. The patch is minimal and complete.

## Summary

**Line counts:** PRD.md = 287 lines, PRD_FINALIZED.md = 287 lines. One line revised (line 160). Delta: 0% line-count change; one sentence extended in place.

**Changes (one bullet per change):**
- §3.4 — revise — pinned the permit auto-creation jurisdiction-derivation method: "a jurisdiction derived from the customer" → "...derived from the customer — specifically, the customer's `service_address` value used verbatim as the permit's jurisdiction code." — `implementation/app.py:1155` (`jurisdiction = customer.get("service_address")`).

**Step 7 items considered:**
- Item 1 (jurisdiction derivation, fixtures.py fix) — **genuine PRD silence, patched.** PRD §3.4 said only "a jurisdiction derived from the customer"; impl uses the whole `service_address` verbatim. Pinned.
- Item 2 (20000 → estimate_total, test_02 fix) — **no patch.** PRD §3.3 already fully determines the trip fee (8900 when not waived; 50000 waive threshold) and §3.4 determines committed_credit == estimate_total. With labor-after-discount 20000 < 50000 and no plan, estimate_total = 28900. PRD is not silent; this was a pure test-author arithmetic error. Confirmed against `pricing.py:14-15,91-92,96` (TRIP_FEE_BASE_CENTS=8900, TRIP_WAIVE_THRESHOLD_CENTS=50000) and §3.4's committed-credit rule.

**Per-edit pre-edit search log:**

Edit 1 — §3.4 jurisdiction derivation:
- (a) Subject identified: how a `Permit`'s `jurisdiction` field is set/derived, and everything that reads/compares a permit or inspector jurisdiction.
- (b) Impl paths enumerated and read/grepped (`grep -n "jurisdiction"` across app.py + full reads):
  - `app.py:1155` — permit auto-create cascade in `approve_estimate`: `jurisdiction = customer.get("service_address")` (the only place a permit jurisdiction is *derived*). Verified this is the sole permit-creation site (no manual `POST /permits` endpoint exists; permits are only born via this cascade and via §3.7 cancel-void / §3.5 reissue, none of which set jurisdiction).
  - `app.py:427,432` — `create_inspector`: inspector `jurisdiction` is a directly-supplied request field, not derived. My wording does not touch inspector jurisdiction, so consistent.
  - `app.py:1234-1235` — `schedule_inspection`: compares `inspector["jurisdiction"] != permit["jurisdiction"]` (plain equality of the two stored values). My wording describes only how the permit value is *set*, not how the comparison works, so the existing equality check remains accurately described by unchanged PRD §3.5 prose.
- (c) Wording adjustment: scoped the addition strictly to the permit's jurisdiction at auto-create time ("the permit's jurisdiction code"), deliberately not making any claim about inspector-jurisdiction origin or the equality-comparison mechanics, both of which are already correctly covered by other PRD prose. No further softening needed; "used verbatim" exactly matches the impl's direct assignment with no transformation.

## Step 9: Complete PRD — 2026-06-15T17:24:00.000Z

All 14 edits are in place and well-formed. The PRD_COMPLETED.md is complete.

## Summary

**File deltas:** PRD_FINALIZED.md → PRD_COMPLETED.md: 287 → 287 lines (unchanged; all edits in-paragraph/in-table-cell), 47,956 → 50,360 chars (+2,404).

**Counts:** 13 ambiguity-pins, 0 mismatch-revisions (the implementation never contradicted PRD prose outright — every divergence was PRD silence the impl resolved one way).

**Changes (one per edit):**
- §2.3 Pagination — insert — ambiguity — pinned that `created_at`-ascending sort ties (e.g. under a frozen test clock) break by creation order, earlier first — `helpers.py:132-134`
- §2.6 Validation Ordering — insert — ambiguity — pinned that the dispatch `ERR_VALIDATION` (window_end > window_start) is evaluated in the well-formedness tier, ahead of the OCC check — `app.py:763-776`
- §3.1 (technician) — insert — ambiguity — pinned that set-availability carries the new value in a required `status` field — `app.py:280`
- §3.1 (customer) — insert — ambiguity — pinned `credit_limit_cents` minimum of 0 — `app.py:189-190, 230-231`
- §3.1 (truck stock) — insert — ambiguity — pinned create-or-restock upsert keyed on technician_id/part_id (overwrites quantity+reorder_point, bumps version, returns 201) — `app.py:367-390`
- §3.2 (confirm) — insert — ambiguity — pinned that confirming onto an `OFF_DUTY` technician yields `ERR_INVALID_STATE` (the one confirm gate the PRD left unnamed) — `app.py:862-863`
- §3.5 (complete) — insert — ambiguity — pinned `consumed_parts` shape (required list of {string part_id, int units≥1}; malformed → `ERR_INVALID_REQUEST`), that a non-PASSED permit → `ERR_INVALID_STATE`, and that same-part entries are summed before the stock check — `app.py:586-637`
- §3.7 (cancel) — insert — ambiguity — pinned that the credit release is floored at 0 — `app.py:716-717`
- §3.8 (accept) — insert — ambiguity — pinned stock restore goes to the *completing* technician and credit release is conditional on amount>0 and floored at 0 — `app.py:1429-1451`
- §3.8 (reopen) — insert — ambiguity — pinned which technician may start/complete a reopened job (recorded completing tech, falling back to most-recent CLOSED assignment's tech; others → `ERR_UNAUTHORIZED`) — `app.py:513-536`
- §4 table (truck-stock list) — revise — ambiguity — named filters `part_id`/`technician_id` — `app.py:398-404`
- §4 table (service-jobs list) — revise — ambiguity — named filters `customer_id`/`authorized_estimate_id`/`status` — `app.py:489-498`
- §4 table (dispatch-assignments list) — revise — ambiguity — named filters `job_id`/`technician_id`/`status` — `app.py:804-813`
- §4 table (estimate-lines list) — revise — ambiguity — named filters `estimate_id`/`flat_rate_item_id`/`part_id` — `app.py:1068-1077`
- §4 table (inspections list) — revise — ambiguity — named filters `inspector_id`/`scheduled_date`/`result` — `app.py:1273-1282`

**Notes on what was deliberately left unchanged** (PRD already pins them uniquely, matching impl): the `ERR_VALIDATION` window check itself, after-hours freeze logic (18:00 UTC / weekend), all pricing/rounding formulas, permit jurisdiction = `service_address` verbatim, callback warranty floor-division ≤90 days, rolling-window callback rate, config-resource field omission (no `updated_at`/`version`), and the standard error/success envelopes — all verified consistent against `pricing.py`, `serializers.py`, `db.py`, and `app.py`.

---

## Pipeline Complete

Resumed from Step 5. Steps 5–9 all completed. Final state: **38/38 tests passing across all 8 concurrent stability-sweep rounds, no flakiness.** Artifacts: `test_helpers/` (9 files), `test_suite/` (conftest + 3 test files, 38 tests), `workspace/implementation/` (Flask app + 9 modules + start.sh, in-memory only), `workspace/PRD_FINALIZED.md` (Step 8), `workspace/PRD_COMPLETED.md` (Step 9).

---

# RESUME + REPAIR (round 2) — difficulty-queue coverage gap

**Defect found:** the round-1 Step 5 (truncated by a socket error) covered only 4 of 18 difficulty (queue A) instances — the 14 core depth/cascade/state-machine/concurrency/conservation tests were missing. The round-1 "38/38 pass" and the Step 8/9 PRD finalization were produced against that truncated suite and must be redone. Scaffold / PRD / implementation are preserved (Steps 1–4, 6 untouched). Below: Step 5 redo (full regen), then Steps 7–9 redone against the completed suite.

## Step 5 (redo): Regenerate Unit Tests — full coverage — 2026-06-15T17:41:44.000Z

Subagent (agentId ab242444a936be7d7) performed a complete from-scratch regeneration of `test_helpers/` + `test_suite/`, forbidden from reading `workspace/implementation/`. Orchestrator on-disk audit: **51 test functions = 51 `Design:` tags (1:1, no duplicates), all `py_compile`-clean.** Coverage: **difficulty (queue A) 17/18, corner (queue B) 34/34.** The 14 previously-missing difficulty instances are now all present; the only uncovered difficulty instance is the one justified skip below. Deleted 3 truncated round-1 files (`test_01_crud_and_validation.py`, `test_02_state_machines_and_rbac.py`, `test_03_pricing_calculations.py`); `test_suite/` now holds `conftest.py` + 6 regenerated `test_*.py`.

Subagent's verbatim summary:

---
Regeneration is complete and fully audited. Here is the final report.

### 1. Final file list

**test_helpers/** (kept the prior high-quality `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `__init__.py`; extended `fixtures.py` with the deep composites the missing difficulty instances needed):
`__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`

New fixtures added: `setup_permit_job_in_progress_scheduled`, `setup_completed_permit_job`, `setup_reopened_job`, `run_one_completed_job`, `schedule_inspection_on_issued_permit`.

**test_suite/**:
`conftest.py`, `test_01_pricing_calculations.py`, `test_02_estimate_and_job_lifecycle.py`, `test_03_cascades_and_invariants.py`, `test_04_dispatch_and_permits.py`, `test_05_callbacks_and_warranty.py`, `test_06_crud_rbac_concurrency.py`

### 2. Test count
**51 tests total** = 1 test per non-stub instance.
- **Difficulty (queue A): 17/18 covered** (1 justified skip — see §4).
- **Corner (queue B): 34/34 covered.** The 5 `excluded_because` stubs were correctly NOT emitted; all 5 cross-references resolve to real §1.8 instances.

### 3. Design tags emitted (audited 1:1 against the indices)

**Queue A — Difficulty (17):** `dual_variant_calc/{provisional_estimate_vs_final_invoice_total_diverge, technician_lifetime_vs_rolling_callback_rate_diverge}`, `combinatorial_formula/{estimate_per_line_rounding_order_pinned_mode_b, trip_fee_waiver_keyed_on_post_discount_labor_mode_c}`, `non_linear_state_machine/{service_job_reopen_cycle_completed_to_reopened_to_completed, estimate_revision_cycle_presented_to_revised_to_presented}`, `transitive_cascade/{complete_cascades_estimate_then_truckstock_then_technician_depth3, approve_cascades_credit_commit_then_permit_autocreate_depth2}`, `priority_pair_validation_conflict/{approve_state_beats_credit_fiscal, confirm_skill_safety_beats_double_booked_temporal}`, `boundary_precision_check/present_empty_estimate_zero_lines_rejected`, `cross_entity_state_dependency/{start_work_blocked_until_estimate_approved_job_estimate, complete_blocked_until_permit_passed_job_permit}`, `resource_temporal_overlap/{technician_assignment_buffered_pairwise_overlap, inspector_daily_aggregate_capacity_full}`, `compensating_invariant/{truckstock_units_conserved_consume_then_callback_restore, customer_credit_conserved_commit_then_cancel_release}`

**Queue B — Corner (34):** entities (8): `create_service_job_returns_201_with_defaults, create_service_job_missing_category_returns_invalid_request, create_service_job_bad_category_enum_returns_invalid_request, get_service_job_nonexistent_returns_not_found, create_customer_omitting_credit_limit_applies_default, create_service_job_with_nonexistent_customer_fk_returns_not_found, system_fields_generated_on_create_input_ignored, list_service_jobs_pagination_envelope`; state_machines (5): `confirm_already_confirmed_assignment_returns_invalid_state, cancel_already_cancelled_job_terminal_lockdown, initial_state_of_new_estimate_is_draft, permit_reapply_cycle_failed_to_issued_increments_count, cancel_job_cascades_assignment_cancel_conditional`; calculations (4): `emergency_surcharge_applied_for_emergency_priority, membership_discount_capped_at_max, callback_warranty_boundary_at_exactly_90_days, callback_rate_zero_when_no_completions`; validations (4): `complete_with_insufficient_stock_returns_error, schedule_inspection_jurisdiction_mismatch_returns_license_required, confirm_unavailable_technician_returns_invalid_state, confirm_unlicensed_technician_for_permit_job_returns_license_required`; endpoints (3): `window_end_before_start_returns_validation, estimate_line_part_without_part_id_returns_invalid_request, truck_stock_reverse_reachability_by_technician`; errors (2): `callback_against_non_completed_job_returns_warranty_expired, accept_expired_warranty_callback_returns_warranty_expired`; rbac (4): `dispatcher_cannot_approve_estimate_unauthorized, customer_cannot_approve_other_customers_estimate_unauthorized, missing_auth_headers_returns_unauthenticated, technician_cannot_create_part_unauthorized`; cross_cutting (3): `occ_stale_job_version_on_estimate_create, occ_correct_job_version_succeeds_and_increments, derived_field_needs_restock_recomputed_on_restock`; consistency_model (1): `immediate_consistency_committed_credit_visible_in_same_flow`

### 4. Skipped instances

- **`Difficulty/boundary_precision_check/after_hours_cutoff_at_exactly_17_00_triggers_multiplier`** — failed **condition (2) unique derivability**. The instance asserts a `window_start` at exactly 17:00 UTC sets `after_hours=true` (labor 15000), claiming "cutoff is >=17". But PRD §3.2 states verbatim: *"The after-hours cutoff hour is 18:00 UTC, meaning any confirmed window starting at hour 18 or later in the UTC day counts as after hours."* A faithful PRD-only implementer uniquely derives `after_hours=false` and labor=10000 at 17:00 — the exact opposite of the asserted outcome — so the test would fail against any correct implementation. The instance contradicts the PRD; skipped per the PRD-first rule (not weakened, no placeholder). Note: the *other* boundary instance (`present_empty_estimate_zero_lines_rejected`) is covered, so Rule 6 still has one tagged test.

**One literal-value adjudication (covered, not skipped):** `transitive_cascade/approve_cascades_credit_commit_then_permit_autocreate_depth2` — the YAML asserts `committed_credit_cents == 60000`, but the PRD-derived total for its own setup (base 40000, normal-hours, no plan, no parts) is 48900 (40000 + 8900 trip). The literal 60000 is internally inconsistent with the PRD. Rather than hard-code the erroneous literal (which would fail a correct implementation), the test asserts the instance's actual invariant — `committed_credit_cents == estimate_total_cents` read live + `> 0`, status AUTHORIZED, exactly one APPLIED permit — faithfully capturing the depth-2 credit-commit-then-permit-autocreate cascade.

### 5. Orphan/residual files deleted
Deleted the 3 truncated prior-run files in `test_suite/`: `test_01_crud_and_validation.py`, `test_02_state_machines_and_rbac.py`, `test_03_pricing_calculations.py`. Final `test_suite/` contains only `conftest.py` + the 6 regenerated `test_*.py` files; no residue remains.

### 6. Implementation isolation
Confirmed: did **not** read, open, glob, or grep anything under `workspace/implementation/`. Every assertion derives from `workspace/PRD.md` plus the difficulty/corner design indices; all literal values were copied from the YAML (with the single PRD-first adjudication noted above).
---

## Step 7 (redo): Run Tests and Iterate — 2026-06-15T17:54:50.000Z

Long-lived diagnostic subagent (agentId a3fd35fdf14082643). Orchestrator on-disk verification: all 8 `results.{1..8}.json` show **51/51 passed, 0 failed, 0 errors** — clean sweep, no flakiness. The 14 newly-added difficulty tests surfaced 3 deterministic failures, all adjudicated as test-artifact bugs (no implementation defects, no deletions).

Subagent's verbatim summary:

---
Clean 8-round sweep achieved. Here is the summary.

**Iterations run:** 2 (baseline sweep + one fix batch, then confirming sweep).

**Failures (union across 8 rounds):** 3 tests, all failing deterministically in all 8 rounds (no flakiness). All three traced to **test-artifact bugs** (STEP 2), not implementation defects — the previously-validated implementation correctly enforced PRD rules that the freshly-generated difficulty-test fixtures violated.

**Tests deleted:** none. (All three failures had full PRD coverage + unique derivability; the artifacts were wrong, not the implementation.)

**Fixes applied to `test_helpers/`** (`test_helpers/fixtures.py`):
- `setup_completed_job` — now provisions a truck-stock row per distinct consumed part (quantity = units consumed, reorder_point 0) before calling `complete_job`. The fixture previously consumed parts at completion without ever creating truck stock, so the PRD §3.7 check ("for every consumed part, the technician's truck-stock quantity must be ≥ units claimed") correctly rejected with `ERR_INSUFFICIENT_STOCK`. Fixed `test_provisional_estimate_and_final_invoice_totals_diverge`.
- `setup_permit_job_issued` — its hardcoded flat-rate `code="PMT-FR"` collided when the fixture was invoked twice in one test (PRD §3.1: flat-rate `code` is unique across the book), producing `ERR_INVALID_REQUEST - code already exists`. Now suffixes the code with a monotonic counter (`PMT-FR-1`, `PMT-FR-2`, …); added an `itertools.count` module-level sequence. No test asserts the literal code. Fixed `test_inspector_daily_aggregate_capacity_full`.

**Fixes applied to `test_suite/`** (`test_05_callbacks_and_warranty.py`):
- `test_lifetime_and_rolling_callback_rates_diverge` — the two `validate_success(api.create_callback(...))` calls used the default `expected_status=200`, but PRD §4 states creating a callback returns `201 Created`. Added `expected_status=201` to both. Made the assertion *more* faithful to PRD, not less.

**Fixes applied to `implementation/`:** none. The implementation was confirmed PRD-faithful for all three failures.

**Final per-round pass counts:** all 8 rounds 51/51 passed (0 failed, 0 errors, 0 skipped).
---

## Step 8 (redo): Finalize PRD — 2026-06-15T17:57:50.000Z

Subagent (agentId a7a9903c82ad1cd14). This round's Step 7 produced 0 implementation fixes and 0 deletions; only 3 test-artifact fixes, each tracing to a PRD rule already pinned uniquely. Result: **PRD_FINALIZED.md is byte-identical to PRD.md (287 lines, 0 edits)** — verified on disk by orchestrator (`diff` reports IDENTICAL). The round-1 §3.4 jurisdiction-derivation pin is intentionally not re-applied here (it was driven by round-1's Step 7 fixture fix, not this round's); the comprehensive impl scan in Step 9 re-pins all impl-resolved ambiguities regardless of step_7_diff.

Subagent's verbatim summary:

---
Done. `PRD_FINALIZED.md` was created as a copy of `PRD.md` and, after adjudicating all three Step 7 items, requires zero edits — every Step 7 fix traced to a rule the PRD already pins uniquely.

**Line counts:** PRD.md = 287 lines; PRD_FINALIZED.md = 287 lines. Delta: 0 lines (0.0%). Files are byte-identical.

**Changes:** Zero. The Step 7 round produced no implementation fixes and no test deletions — only three test-artifact bug fixes (two fixture preconditions, one test's expected HTTP status). Each traces to a PRD rule that is already pinned uniquely, so no PRD edit is warranted.

### Per-item adjudication (why no edit)
(a) Truck-stock ≥ units-claimed check on completion — Already pinned. PRD §3.5 states verbatim the per-part truck-stock sufficiency rule and ERR_INSUFFICIENT_STOCK; impl enforces it (app.py:633-637). Fixture never provisioned stock → fixture precondition error, not PRD silence.
(b) Flat-rate code uniqueness — Already pinned. PRD §3.1: "Each FlatRateItem carries a code that is unique across the book"; impl enforces (app.py:133-135). Fixture reused a hardcoded code → fixture bug.
(c) Callback-create returns 201 — Already pinned. PRD §4 lead lists "a callback" among create ops returning 201 Created; impl returns 201 (app.py:1377). Test used default expected_status=200 → test bug; fix made test more faithful.

No PRD-silence or PRD-mismatch was found for any Step 7 item; PRD_FINALIZED.md is intentionally identical to PRD.md.
---

## Step 9 (redo): Complete PRD — 2026-06-15T18:02:53.000Z

Subagent (agentId af162666b3e89f4a1). Full impl-vs-PRD scan starting from PRD_FINALIZED.md (which equals PRD.md this round). Orchestrator on-disk verification: PRD_COMPLETED.md = 287 lines, 51,516 chars (+3,665 over FINALIZED), 14 revised lines (28 diff lines = 14 in-place revisions); jurisdiction `service_address` pin present. **14 ambiguity-pins, 0 mismatch-revisions.** This set = the 13 round-1 Step 9 pins + the §3.4 jurisdiction-derivation pin (round-1 carried that one in Step 8; since round-2 Step 8 made no edits, Step 9's full scan correctly re-captured it). Since the implementation is frozen/unchanged, the scan converges to the same complete PRD as round 1.

Subagent's verbatim summary:

---
All 14 edits are in place and coherent. The PRD_COMPLETED.md is a minimal in-paragraph/in-row patch over PRD_FINALIZED.md with zero new sections or lines.

**File metrics:** PRD_FINALIZED.md 287 lines/47,851 chars; PRD_COMPLETED.md 287 lines/51,516 chars (+3,665 chars; same line count — all in-paragraph inserts or in-row revisions). 14 changed lines.

**Counts:** 14 changes total — all ambiguity-pins; 0 outright mismatch-revisions. (`final_labor_cents` pin is closest to a mismatch — PRD prose could be read post-discount, classified as ambiguity-pin since PRD never explicitly stated either reading.)

**One bullet per change:**
- §2.3 Pagination — insert — ambiguity — equal-created_at tie broken by creation order (_seq) — helpers.py:134
- §3.1 Truck stock — insert — ambiguity — create/restock is upsert keyed on (technician_id, part_id); existing row overwrites quantity+reorder_point (not additive), bumps version, returns 201 — app.py:365-390
- §3.2 Dispatch create — insert — ambiguity — window-bounds ERR_VALIDATION evaluated before OCC ERR_STALE_JOB_VERSION — app.py:770-776
- §3.2 Confirm — revise — ambiguity — OFF_DUTY availability gate fires ERR_INVALID_STATE — app.py:862-863
- §3.2 Confirm — insert — ambiguity — skill ceiling = max skill_required over FLAT_RATE lines of every estimate of the job (any status), 0 if none; permit-requirement derived same way — app.py:819-845
- §3.4 Permit auto-create — insert — ambiguity — jurisdiction = customer's service_address copied verbatim — app.py:1155
- §3.5 Complete — insert — ambiguity — consumed_parts is array (may be empty) of {part_id:str, units:int>=1}; same-part entries summed before stock check/decrement/invoice — app.py:588-624
- §3.5 Complete — revise — ambiguity — missing truck-stock row for a consumed part counts as zero held → ERR_INSUFFICIENT_STOCK — app.py:635
- §3.6 Invoice — revise — ambiguity — final_labor_cents is pre-discount labor subtotal; discount applies only inside final_total_cents — pricing.py:148
- §3.7 Cancel — insert — ambiguity — credit release floors committed_credit_cents at 0 — app.py:716-717
- §3.8 Callback accept — revise — ambiguity — stock restored to recorded completing technician, skipped if no row; credit release conditional on authorized_amount_cents>0 and floored at 0 — app.py:1429-1451
- §3.8 Reopen — insert — ambiguity — reopened-job field flow owned by recorded completing technician; others get ERR_UNAUTHORIZED — app.py:513-536
- §4 table (service-jobs) — revise — ambiguity — filters customer_id/authorized_estimate_id/status — app.py:489-498
- §4 table (dispatch-assignments) — revise — ambiguity — filters job_id/technician_id/status — app.py:804-813
- §4 table (estimate-lines) — revise — ambiguity — filters estimate_id/flat_rate_item_id/part_id — app.py:1068-1077
- §4 table (inspections) — revise — ambiguity — filters inspector_id/scheduled_date/result — app.py:1273-1282

**Behaviors verified ALREADY uniquely pinned by PRD (left unchanged):** concrete defaults (credit_limit 100000, status AVAILABLE, reorder_point 2, max_daily_inspections 4, licensed_for_permits/requires_permit false, priority STANDARD, window_start null, counters 0); validation tier order + OCC tier 6 + existence path-then-body; OCC only on Estimate/DispatchAssignment create + ERR_STALE_JOB_VERSION 412; after_hours freeze RECEIVED→DISPATCHED, 18:00 UTC, Sat/Sun, 1.5×; 30-min travel buffer + half-open overlap + CONFIRMED/EN_ROUTE/ON_SITE; round-half-up per-line, 15000 cap, 8900 trip, 50000 waive, 12000 emergency, 4dp rates; credit commit on approval + ERR_CREDIT_LIMIT_EXCEEDED + permit void on cancel + estimate DECLINED cascade + conditional assignment cancel; lifetime_completed_count first-completion guard + completing-tech credit + ACCEPTED→RESOLVED on re-completion; 90-day inclusive warranty floor-div + lifetime_callback_count; rolling-5 ordered completed_at/created_at desc, denom min(5,completed), 0.0 when 0; config resources omit updated_at/version; cascade per-resource version bumps; inspector capacity PENDING-per-date + jurisdiction ERR_LICENSE_REQUIRED + reapply_count.

The PRD now pins every silence the implementation resolves; no remaining impl-vs-PRD gaps were found.
---

---

## RESUME + REPAIR (round 2) — Complete

Difficulty-queue coverage gap closed. Final state:
- **test_suite/**: 51 tests = 51 `Design:` tags (1:1). **Difficulty (queue A) 17/18** (sole skip: `after_hours_cutoff_at_exactly_17_00_triggers_multiplier` — PRD §3.2 pins the cutoff at 18:00 UTC verbatim, so the scaffold's 17:00 assertion fails PRD-first unique-derivability; PRD wins). **Corner (queue B) 34/34.** All 14 previously-missing difficulty instances now covered.
- **Step 7 sweep**: all 8 concurrent rounds **51/51 passed, 0 failed/0 errors**, no flakiness. 3 test-artifact bugs fixed (2 in test_helpers/fixtures.py, 1 in test_05_callbacks_and_warranty.py); 0 implementation fixes; 0 deletions — the frozen implementation was PRD-faithful for every new difficulty test.
- **Step 8**: PRD_FINALIZED.md byte-identical to PRD.md (0 edits — all Step 7 fixes traced to already-pinned PRD rules).
- **Step 9**: PRD_COMPLETED.md = 14 ambiguity-pins over PRD_FINALIZED.md (full impl scan, 0 mismatch-revisions).
- Scaffold / PRD.md / implementation/ preserved unchanged from round 1, as instructed.
