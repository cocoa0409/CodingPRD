# Worklog — task_0407_asc_scheduling

Scenario (verbatim):
Ambulatory Surgery Center Scheduling (ASC): case booking & surgeon block time, OR/anesthesia/recovery resource, pre-op clearance & H&P window, implant/preference card & supply, case-cost & device tracking, turnover & utilization, ASC payment grouping (CMS ASC list), cancellation/add-on

## Step 1: Create Task Directory — 2026-06-18T00:00:00.000Z

Task directory `tasks/task_0407_asc_scheduling/` was pre-allocated and pre-created (with `workspace/`). Used as-is per instructions; no auto-increment scan performed. Index 0407, short_label `asc_scheduling`.

## Step 2: Generate Scaffold (Expert difficulty) — 2026-06-18T00:00:00.000Z

Generated three Expert-tier scaffold artifacts for **Ambulatory Surgery Center (ASC) Scheduling**. Built purely from the scenario description and the skill spec — no sibling task consulted. Files written with correct top-level keys confirmed: SCAFFOLD.yaml (1518 lines, no design keys), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1196 lines, key `scaffold_difficulty_design`), SCAFFOLD_CORNER_DESIGN.yaml (3048 lines, key `scaffold_corner_design`).

**Profile:** temporal_windowing (primary) × ledger_reconciliation (secondary); flat topology under `/asc`; parallel state-machine shape; peer_roles. Layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers.

**Entities (13):** Facility, OperatingRoom, RecoveryBay, Anesthesiologist, Surgeon, Procedure, SupplyItem, SurgicalDay, SurgeonBlock, SurgicalCase, Patient, CaseImplant, ClearanceCheck. (60 endpoints, 56 errors, 19 ordered validations, 4 roles, 1 OCC concurrency rule.)

**State machines (5):**
- SurgicalCase — two parallel dimensions: `case_status` (SCHEDULED→IN_OR→IN_RECOVERY→COMPLETED, +SCHEDULED→CANCELLED) × `clearance_status` (PENDING_CLEARANCE↔ON_HOLD revert loop, →CLEARED).
- SurgeonBlock — branching-with-revert (HELD→{CONFIRMED, RELEASED}; CONFIRMED→RELEASED), release cascades to orphan cases.
- CaseImplant — RESERVED→CONSUMED with RESERVED→RELEASED revert.
- SurgicalDay — compound posture OPEN↔LOCKED→CLOSED (cyclic re-open).

**Headline calculations (9):** estimated vs actual case cost (dual-variant, per-line rounding pinned); `overrun_tiered_penalty` (marginal banding); `asc_payment_grouping` (CMS ASC list, device offset `min(...)` then multi-procedure reduction — pinned non-commutative evaluation order); projected vs actual anesthesia coverage load (dual-variant); `day_utilization` (half-open prime-time overlap threshold); supply availability/reservation conservation.

**Difficulty design:** 18 instances — all 9 §0.5 rules × 2 instances. **Corner design:** 56 active instances + 7 `excluded_because` stubs across all 9 sections; every declared error triggerable. `scaffold_lint.py` reports VERDICT: clean lint (793 calls scanned, FK reverse-reachability satisfied).

## Step 3: Copy Shared Files — 2026-06-18T00:00:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0407_asc_scheduling/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-18T00:00:00.000Z

Generated `workspace/PRD.md` (322 lines, 51KB) for the ASC Scheduling domain, purely from SCAFFOLD.yaml + doc-generator skill spec. Neither design file (DIFFICULTY/CORNER) read; no sibling task consulted.

**Section structure:** §1 Introduction; §2 Global Specifications (2.1 RBAC four opaque-identity roles, 2.2 API Response Structure, 2.3 Pagination, 2.4 Common Resource Properties / versioned mutation w/ ClearanceCheck append-only exception, 2.5 Nested Identifier Resolution & FK existence, 2.6 Validation Order 8-tier precedence, 2.7 Deterministic Facility Clock, 2.8 OCC on Block Booking, 2.9 Monetary Precision & Conservation Invariants); §3 Business Logic & Workflows (14 subsections); §4 Endpoint Definitions (4-col table, all 62 endpoints under `/asc`); §5 Error Code Catalogue (56 codes).

**Hard Contracts:** Contract 1 (71 field names in backticks), Contract 2 (OCC, both dual-variant cost calcs, marginal-band over-run penalty, non-commutative 4-step payment grouping, conservation invariants, validation precedence, all 56 error IDs) — all PASS. Contract 3 §3 path purity (478 tokens, zero path/method tokens) PASS.

## Step 5: Generate Unit Tests — 2026-06-19T00:00:00.000Z

All audits pass. Test generation for task_0407_asc_scheduling is complete.

**Test infrastructure generated for `task_0407_asc_scheduling`.**

**test_helpers/ (9 files):**
- `types.py` — role enum + 12 status enums + entity TypedDicts (ClearanceCheck correctly carries only `id`+`created_at`, no `updated_at`/`version`, per `common_fields: false`)
- `api_client.py` — `ApiClient(GenericApiClient)`, 64 methods, one per `/asc` endpoint
- `api_errors.py` — full 58-error catalog + framework HTTP-status registration
- `assertions.py` — per-entity assertions + conservation-invariant checkers
- `factories.py` — input-only payload factories per entity
- `constants.py` — cost rates, tiered-penalty bands, payment-grouping & coverage constants
- `test_users.py` — 4 opaque role-header constants (no entity_backed roles → no per-instance builders)
- `fixtures.py` — composite setup tiers (facility world, booked case, in-recovery, completed-case lifecycles)
- `__init__.py` — barrel export

**test_suite/ (conftest.py + 10 test files), 91 tests total:**

**Queue A (Difficulty):** all 18 instances × ≥2 tests = 36 tests. Every one of the 9 rule_ids fully covered (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).

**Queue B (Corner):** 55 of 56 non-stub instances covered (1 test each). The 7 `excluded_because` stubs were not translated; all 7 `difficulty_instance` cross-references verified to resolve.

**Skipped (1 instance):** `Corner/errors/error_case_not_scheduled_on_reschedule` — fails the two-condition filter. PRD §3.5 says reschedule "may move a `SCHEDULED` case" but never names the rejection `error_id` for the reschedule path; `ERR_CASE_NOT_SCHEDULED` is named in prose only for the **start** path (§3.11). Reason category: **error-id-not-named-for-this-endpoint / applies_to-scope** (a PRD-only reader could faithfully emit a different state-conflict error). Gap left as a gap, no placeholder.

**Verification:** all files `py_compile` clean; 91 tests collect under pytest; all 119 docstring citation segments confirmed verbatim in PRD.md (modulo whitespace + markdown bold); no scaffold leakage in comments/docstrings; no `skip`/`xfail`/`skipif`; every difficulty instance has ≥2 `Design:` tags and every covered corner instance exactly 1, with no tags pointing to unknown/stub instances.

Note: the runner framework `prd_bench_local_runner` is not pip-installed in this environment; validation was run against the framework source tree (it is injected on `PYTHONPATH` by the runner at execution time). Tests assume a live server at `API_BASE_URL`, as designed.

## Step 6: Generate Implementation — 2026-06-19T00:00:00.000Z

Implementation complete and verified.

Generated a complete Python + Flask implementation for the ASC Scheduling API at `tasks/task_0407_asc_scheduling/workspace/implementation/`.

### Source files produced
- `start.sh` — foreground launcher: reads `$PORT` (default 10000), guards `pip install` behind `python3 -c "import flask"`, and `exec python3 app.py`.
- `app.py` — Flask entry point, blueprint registration, `ApiError`/404/405/500 handlers, binds `0.0.0.0:$PORT`.
- `requirements.txt` — `flask==3.0.3`.
- `db.py` — in-memory store (dicts keyed by id), `stamp_common`/`touch` for `id`/`created_at`/`updated_at`/`version`, plus an internal monotonic `_seq` for deterministic tie-breaking. Starts empty; **no seeding** anywhere.
- `errors.py` — full 60-entry error catalog (PRD §5).
- `response.py` — success/list/error envelopes (`meta`/`response_type`/`data`), `req_` ids, 3-fractional-digit ISO timestamps.
- `middleware.py` — `X-User-ID`/`X-User-Role` auth + role gating.
- `services/helpers.py`, `services/calculations.py`, `services/case_ops.py`, `services/timeutil.py` — validation/serialization, the calculation engine, shared compensating ops, and deterministic time math.
- `routes/resources.py`, `routes/days.py`, `routes/blocks.py`, `routes/cases.py` — all endpoints.

### Coverage
All 13 entities and all 60 endpoints from the PRD §4 table are implemented (facilities, ORs, recovery bays, anesthesiologists, surgeons, procedures, supply items, patients, surgical days, surgeon blocks, surgical cases, case implants, clearance checks), including all state machines (block HELD→CONFIRMED→RELEASED with cascade; case SCHEDULED→IN_OR→IN_RECOVERY→COMPLETED + cancel; parallel clearance PENDING↔ON_HOLD→CLEARED; implant RESERVED→CONSUMED/RELEASED; day OPEN↔LOCKED→CLOSED) and the coverage-load report.

### Notable design decisions
- **OCC**: `expected_block_version` checked against `SurgeonBlock.version` after existence but before any state/business rule (priority 7), → `ERR_STALE_BLOCK_VERSION` (412). Every block mutation (`touch`) bumps version.
- **Validation precedence** follows PRD §2.6 exactly: auth → existence(path) → existence(body FK, same-facility) → well-formed → uniqueness → OCC → state → temporal → safety → fiscal → posture. Booking guards are ordered priorities 9–19 (temporal conflicts before fiscal capacity, capacity before posture).
- **Calculations** use `Decimal` with `ROUND_HALF_UP`, per-line rounding then summing (never sum-then-round). Verified: estimate (planned/RESERVED), actual cost with marginal-band overrun penalty (800/1500/3000), device-intensive offset (lesser of pct vs actual consumed device cost), multi-procedure 50% reduction by same-patient/same-day rank, OFFICE_BASED floor — all in the pinned STEP1→4 order. Utilization and coverage-load round half-up to 1 decimal using half-open prime-time overlap.
- **Conservation invariants** maintained eagerly: `committed_minutes` and `reserved_qty` adjusted on book/cancel/release/consume; day `booked_minutes`/`utilization_pct` recomputed on every relevant mutation and frozen when CLOSED.
- **Determinism**: `current_utc` facility clock (no wall-clock for windows); H&P freshness measured to service-date midnight UTC; cascades and ranking ordered by `(start_min, created_at)`.
- Internal fields (`_seq`, `_last_clearance_reset_seq`) are stripped from all serialized output. `ClearanceCheck` is append-only (`id` + `created_at` only, no `version`/`updated_at`).

### Confirmation
`start.sh` reads `$PORT`, binds `0.0.0.0` in the foreground via `exec`; the server log confirms "Running on all addresses (0.0.0.0)". Boots cleanly from a fresh empty process. All modules compile; ~50 smoke assertions across auth, RBAC, CRUD, uniqueness, pagination/sort, OCC, the full intra-op workflow, cost/payment calculations, block-release cascade, supply conservation, add-on bypass, and clearance/DEFER logic pass.

## Step 7: Run Tests and Iterate — 2026-06-19T00:00:00.000Z

Clean 8-round parallel sweep achieved.

**Iterations run:** 2 (baseline sweep at 87/91, then one fix batch → clean 90/90 across all 8 parallel rounds).

The baseline had 4 stable failures (failing in all 8 rounds — not flaky), reducing to 2 distinct root causes.

### Tests deleted (PRD-silence category)

- **`test_block_capacity_one_over_rejected`** (`test_07_booking_constraints.py`) — **ERROR PRECEDENCE / unreachability (STEP 1b)**. The test asserted `ERR_BLOCK_CAPACITY_EXCEEDED` when a third case overflows a block's allocated minutes. But PRD §3.4 fixes the booking-guard order so the window check (`ERR_CASE_OUTSIDE_BLOCK_WINDOW`) and the OR turnover-conflict check both precede the capacity check. Since `allocated_minutes == end_min − start_min` (§3.4) and a block is bound to one OR, non-overlapping in-window cases tile the window to at most `allocated_minutes`; any non-add-on booking that would push `committed_minutes` past `allocated_minutes` must first fall outside the window or collide in the OR. The capacity-exceeded outcome is therefore not uniquely derivable as a first-failing guard — a faithful PRD-only implementation never returns `ERR_BLOCK_CAPACITY_EXCEEDED` in this scenario (the implementation correctly returned `ERR_CASE_OUTSIDE_BLOCK_WINDOW`). The reachable half of the boundary rule (exact-fill allowed) remains covered by `test_block_capacity_exact_fill_allowed`. Scaffold rule that drove generation: `Difficulty/boundary_precision_check/block_capacity_exact_fill_allowed_one_over_rejected`. A documenting comment replaced the function in-place.

### Fixes applied to `test_suite/` (STEP 2 test bugs — assertions made MORE faithful to PRD)

All three were the same arithmetic slip: the test author computed `60*1200 + 18000` as `78000`, but `60*1200 = 72000`, so the PRD §3.9 formula yields `90000`. The implementation's `90000` was correct; the expected values were corrected upward.

- **`test_01_case_cost_calculations.py` → `test_estimated_cost_at_booking_mac_60min`** — corrected expected estimate `78000` → `90000`.
- **`test_01_case_cost_calculations.py` → `test_actual_cost_diverges_from_estimate_with_overrun`** — corrected expected estimate `78000` → `90000` and actual cost `152790` → `128100` (`78*1200 + 18000 anesthesia + 16500 over-run penalty`, per PRD §3.12).
- **`test_09_concurrency_and_crud.py` → `test_estimate_present_in_booking_response`** — corrected expected estimate `78000` → `90000`.

### Fixes applied to `implementation/`

None. The implementation was PRD-faithful for all four failures; the calculation engine (`services/calculations.py`) and the booking-guard precedence (`routes/blocks.py`) both correctly implement PRD §3.9, §3.12, and §3.4.

### Final state
All 8 concurrent rounds: **90/90 passing, stable, no flakiness.**

## Step 8: Finalize PRD — 2026-06-19T00:00:00.000Z

Done. PRD_FINALIZED.md was created and, after analysis, requires no edits — it is a verbatim copy of PRD.md.

**Line counts:** PRD.md = 322 lines; PRD_FINALIZED.md = 322 lines. **Delta: 0 lines (0%).**

**Changes:** None. All four `<step_7_diff>` items trace to behaviors the PRD already determines uniquely, with a PRD-faithful implementation in each case.

**Per-item analysis:**

- **§3.9 estimate formula (3 test fixes: estimate 78000→90000)** — no edit. PRD §3.9 line 162 prose ("`scheduled_minutes` multiplied by ... 1,200 cents per scheduled minute" + "18,000 cents for `MAC`") uniquely yields `60×1200+18000 = 90000`. The test's `78000` was an author slip. PRD already correct.
- **§3.12 actual cost (actual 152790→128100)** — no edit. PRD §3.12 line 182 prose uniquely yields `78×1200+18000+16500 = 128100`. Implementation matches. No PRD silence.
- **§3.4 booking-guard precedence (deleted `test_block_capacity_one_over_rejected`)** — no edit. PRD §3.4 line 130 already enumerates the guard sequence with window and time-conflict checks before the capacity check; §3.4 line 124 pins `allocated_minutes = end_min − start_min`. Unreachability of capacity-exceeded in the tiling scenario is a derived consequence of an ordering the PRD already fixes — not a silence.

No `<step_7_diff>` item revealed a PRD silence or a PRD/impl mismatch, so PRD_FINALIZED.md is byte-identical to PRD.md (confirmed via `diff`).

## Step 9: Complete PRD — 2026-06-19T00:00:00.000Z

PRD_COMPLETED.md produced via full PRD-vs-implementation scan.

**File comparison**
- Source (`PRD_FINALIZED.md`, byte-identical to `PRD.md`): 322 lines, 51,296 chars.
- `PRD_COMPLETED.md`: 322 lines, 51,846 chars. Char delta: **+550**. Line delta: **0** (both edits are in-paragraph inline revisions; no new lines, paragraphs, or sections).

**Change counts**
- Ambiguity-pins: **2** (coverage-load `basis` literal values + required `service_date`; coverage-load response field names/shape).
- Mismatch-revisions: **1** (completion `ERR_IMPLANT_NOT_SETTLED` scope).

**Changes**
- `§3.11 (Completion)` — revise — mismatch — PRD said *"every `CaseImplant` ... must have `consumed_qty` recorded"*, but impl only enforces this for still-`RESERVED` implants and skips `RELEASED`/`CONSUMED` ones. Pinned to "every still-`RESERVED` `CaseImplant` ... (implants already in `RELEASED` or `CONSUMED` status are not subject to this check)" — `routes/cases.py:312-316`.
- `§3.14 (Coverage-load report — parameters)` — insert — ambiguity — Pinned `basis ∈ {PROJECTED (default), ACTUAL}` with any other value → `ERR_INVALID_REQUEST`, and `service_date` as a required query param rejected with `ERR_INVALID_REQUEST` when absent — `routes/resources.py:256-261`.
- `§3.14 (Coverage-load report — response shape)` — insert — ambiguity — Pinned the JSON key names `anesthesiologist_id` and `minutes` (integer), the `basis` echo of the resolved value, and that the report carries no common lifecycle fields — `routes/resources.py:262-269`.

**Areas examined and left unchanged** (PRD already pins uniquely, impl agrees): 8-tier validation precedence (§2.6), booking-guard ordering (§3.4), conservation invariants (§2.9), per-line half-up rounding, over-run marginal banding (§3.12), 4-step ASC payment grouping (§3.13), utilization half-open overlap (§3.14), H&P freshness (§3.8), DEFER supersession scoping (§3.8), all state-machine transitions, full error catalog, entity field shapes.

---

**Pipeline complete.** task_0407_asc_scheduling: 90/90 tests passing across 8 concurrent stability rounds. All Step 1–9 artifacts present.
