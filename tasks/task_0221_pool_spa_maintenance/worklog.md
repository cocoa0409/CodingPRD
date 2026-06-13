# Worklog — task_0221_pool_spa_maintenance

## Step 1: Create task directory — 2026-06-07T05:04:25.000Z

Created `tasks/task_0221_pool_spa_maintenance/` and `tasks/task_0221_pool_spa_maintenance/workspace/`. Index 0221 derived from highest existing `task_NNNN_*` directory + 1. Scenario: "221. Pool & Spa Maintenance Service: service route/frequency, chemical reading & dosing log, equipment-repair work order, seasonal open/close, one-time vs recurring plan, weather/holiday skip, billing per visit, green-pool recovery".

## Step 2: Generate scaffold — 2026-06-07T05:18:00.000Z

All literal asserts match my computed values:
- dosing: 116.0, 100.0, 28.0, 0.0 ✓
- visit bill: 26000 (green init), 6000 (recurring base), 0 (recurring prepaid plain), 12000 (prepaid+green), 12500 (recovery) ✓
- repair: 27499 (MAJOR), 45101 (CRITICAL) ✓
- invoice/balance: 26000, 12500, 0 ✓

One concern: in the `service_visit_branching_complete_vs_skip` instance, `visit_a` is a RECURRING plan with `prepaid_visit_count: 0`, green_pool false, normal completion → billed = base = 6000. Since prepaid is 0, `visits_remaining_before` = 0, so base is billed. Correct (6000). And `billed_amount_cents == 0` at corner line 235 is `new_visit_starts_in_scheduled` — a freshly created visit, 0 before completion. Correct.

Everything is consistent and the lint is clean. The scaffold is complete.

## Summary

Generated a fully lint-clean scaffold package for **task_0221_pool_spa_maintenance**:

**Complexity profile**: Workflow-orchestration primary archetype blended with ledger-reconciliation secondary; flat (peer-FK) entity topology; branching state-machine shape; peer-roles RBAC; immediate consistency. Layers: dual-variant calculation, cascading side effects, optimistic concurrency, derived-field reconciliation.

**SCAFFOLD.yaml** (§1.0–§1.7):
- **9 entities**: Customer, Pool, ServicePlan, RouteAssignment, ServiceVisit, ChemicalReading, WorkOrder, SeasonalEvent, Invoice
- **7 state machines**: Pool (CLOSED↔OPEN↔GREEN_RECOVERY↔WINTERIZED), ServiceVisit (branching SCHEDULED→{COMPLETED, SKIPPED, RECOVERY_SCHEDULED, CANCELLED}), RouteAssignment, WorkOrder (cyclic ON_HOLD↔DIAGNOSED), SeasonalEvent, ServicePlan (bubble-up auto-complete), Invoice
- **1 concurrency rule**: OCC on Pool.version for visit-log supersede (ERR_STALE_VERSION, 412)
- **4 calculations**: dosing_recommendation (sum-then-round, pH-penalty), final_visit_bill (tiered green surcharge + recovery + prepaid coverage), repair_total (ceil-hour labor × severity mult, single tax round), invoice_total
- **17 validations** (priority-ordered), **46 endpoints** (29 POST / 17 GET), **17 error codes**, **4 RBAC roles** (AccountManager, RouteManager, FieldTechnician opaque; Customer entity_backed)

**SCAFFOLD_DIFFICULTY_DESIGN.yaml**: 9 rule_ids × 2 instances = **18 instances**, each grounded in §1.1–§1.7 with executable empty-DB setup chains and code-computed literal asserts.

**SCAFFOLD_CORNER_DESIGN.yaml**: 8 sections, **31 active corner instances + 4 excluded_because stubs** (all stub refs resolve to existing §1.8 instances).

**Validation**: `scaffold_lint.py` → `VERDICT: clean lint` (360 calls scanned, all checks a–f pass). All three files parse as valid YAML; no duplicate instance names across both design files; every formula-derived assert independently verified.

## Step 3: Copy INSTRUCTION.md — 2026-06-07T05:18:52.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0221_pool_spa_maintenance/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-07T05:24:31.000Z

Generated `workspace/PRD.md` (251 lines) for the pool-spa-maintenance domain.

**Document stats:**
- **Section count:** 5 top-level sections (Introduction, Global Specifications, Business Logic & Workflows, Endpoint Definitions, Error Code Catalogue), 19 subsections total.
- **Tables:** §4 endpoint table 46 rows / 4 columns; §5 error table 17 rows / 2 columns.

**Hard Contract results (all PASS):**
- **Contract 1 (Field-Name Coverage):** 54 required identifiers — all present in backticks, 0 missing (`note` caught missing on first pass and added to §2.8).
- **Contract 2 (Rule Coverage):** All 17 error IDs surface in §2/§3 prose; all calculation constants embedded; all 23 state values + 22 enum values present; OCC rule on visit-logs expressed with `expected_pool_version` + `ERR_STALE_VERSION`/412; validation priority ordering and cross-entity cascades all expressed.
- **Contract 3 (§3 Path Purity):** 321 backtick tokens scanned in §3; 0 starting with `/`, 0 bare HTTP methods, 0 method+path combos.

**Confirmation:** Read only `SCAFFOLD.yaml`; did NOT open `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml`.

## Step 5: Generate unit tests — 2026-06-07T05:43:22.000Z

Generated complete test infrastructure for `task_0221_pool_spa_maintenance`, translating exclusively from the two design indices (design-index-only contract honored).

### test_helpers/ (Stage 1) — 9 files
- `types.py` — entity TypedDicts + 14 status/role enums; `ChemicalReading` correctly modeled as append-only (only `id` + `created_at`, no `updated_at`/`version`).
- `api_client.py` — `ApiClient(GenericApiClient)` with 46 endpoint methods (one per PRD endpoint).
- `api_errors.py` — 17 `ApiErrorId` values + HTTP status map.
- `assertions.py` — per-entity assertions; append-only assertion enforces absence of `updated_at`/`version` on readings.
- `factories.py` — input-only payload factories with process-unique email generation.
- `constants.py` — dosing/billing/repair thresholds from PRD calculations.
- `test_users.py` — opaque role constants + `make_customer_headers()` builder for the one entity_backed role (Customer).
- `fixtures.py` — composite setup helpers across all tiers.
- `__init__.py` — barrel export.

### test_suite/ (Stage 2) — 9 test files, 67 test functions

### Coverage (all targets met)
- **Difficulty queue:** all 18 instances covered by ≥2 tests each.
- **Corner queue:** all 31 non-stub instances covered by ≥1 test each.
- **Instances skipped:** 4 — the corner `excluded_because` stubs (`reading_recommended_dose_input_ignored`, `close_pool_blocked_by_open_visits`, `nothing_to_bill_on_zero_charge_invoice`, `route_at_capacity_returns_error`); each correctly left untranslated since its cited difficulty instance owns the assertion. No instances skipped for PRD-coverage failure.

### Verification
- All 18 files compile; `test_helpers` imports cleanly; pytest collects all 67 tests with zero errors.
- Every Design tag resolves to a real instance; no dual/untagged tests.
- All literal expected values independently recomputed and confirmed.

One notable finding: the difficulty instance `state_before_fiscal_on_invoice_issue` describes a "zero-charge already-ISSUED invoice" in prose, but a zero-charge invoice can never reach ISSUED (blocked by `ERR_NOTHING_TO_BILL`). Translated the genuinely-reachable state-gate behavior (re-issue from ISSUED → `ERR_INVALID_STATE`) instead.

## Step 6: Generate implementation — 2026-06-07T05:43:22.000Z

Built a complete Python + Flask implementation at `workspace/implementation/`.

### Source files created (21 total)
- **Foundation**: `app.py` (entry point, error handlers, waitress server with bind-retry), `db.py` (in-memory store), `errors.py` (17-error catalogue), `response.py` (envelope: `meta`/`response_type`/`data`), `middleware.py` (`X-User-ID`/`X-User-Role` auth + RBAC), `start.sh`, `requirements.txt`
- **Services**: `common.py`, `calculations.py` (4 calc rules, Decimal-based), `derived.py`, `lookup.py`
- **Routes** (8 blueprints): `customers.py`, `pools.py`, `service_plans.py`, `route_assignments.py`, `visits.py`, `work_orders.py`, `seasonal_events.py`, `invoices.py`

### Endpoints implemented: 47 (full §4 table)

### State machines (7) + calculations (4)
- **State machines**: Pool, ServiceVisit (branching), RouteAssignment, WorkOrder (ON_HOLD→DIAGNOSED revert loop), SeasonalEvent, ServicePlan (auto-bubble-up to COMPLETED), Invoice — with cross-entity preconditions and cascades.
- **Calculations**: `dosing_recommendation`, `final_visit_bill`, `repair_total`, `invoice_total` (verified at round-half-up boundaries).

### Confirmations
- **Storage in-memory only** — all state in `db.Store` dicts, no SQLite/file/external persistence; store starts empty on every boot.
- **`start.sh` reads `$PORT`** (default 10000), **binds `0.0.0.0`**, runs **foreground via `exec`**, guards pip install behind import check.

NOTE: Step 5 and Step 6 report differing worked-example values for some dosing/billing literals (Step 5: dosing 116.0/100.0/28.0; billing 26000/12000/6000/12500 — Step 6: dosing e.g. 130.0; billing 23000/9500). These are independent generations; Step 7's iteration loop will reconcile any genuine divergence against PRD.

## Step 7: Run tests and iterate — 2026-06-07T05:46:28.000Z

- **Iterations run:** 1 (a single 8-round parallel sweep).
- **Result:** All 8 rounds passed 67/67 tests (`passed == total`, `failed == 0`, `errors == 0` in every round). No flakiness surfaced across the concurrent rounds. Verified independently by the orchestrator: results.{1..8}.json all show passed=67 total=67 failed=0.
- **Tests deleted:** None — no test failed unique-derivability or PRD-coverage checks because no test failed at all.
- **Fixes applied to test_helpers/:** None required.
- **Fixes applied to implementation/:** None required.

The implementation already satisfies the full test suite stably under per-test-server isolation. In-memory only (state in `db.py`'s `Store`, wiped on each boot, no seeding); `start.sh` boots via waitress with a bind-retry loop handling concurrent-reboot port contention.

(The Step 7 subagent noted an earlier "FAIL" listing was a false alarm from reading the wrong JSON key — `outcome` vs `status` — corrected to confirm all passed.)

## Step 8: Finalize PRD — SKIPPED — 2026-06-07T05:46:28.000Z

Skipped per skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, and 0 implementation/ fixes (zero iterations beyond baseline). PRD.md already determined every behavior the implementation exhibits at the sites Step 7 would have touched. `PRD_FINALIZED.md` not produced; Step 9 starts from `PRD.md`.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-06-07T05:51:00.000Z

Produced `workspace/PRD_COMPLETED.md` via full PRD-vs-implementation scan, starting from `PRD.md` (Step 8 skipped, no PRD_FINALIZED.md).

**Source vs. completed file:**
- `PRD.md`: 251 lines, 37,928 chars
- `PRD_COMPLETED.md`: 251 lines, 40,497 chars (**+2,569 chars**, 0 net lines — every change in-paragraph, no new sections)

**Counts:** 10 changes total — 9 ambiguity-pins, 1 mismatch-revision.

**Per-change log:**
- **§2.1** — revise — mismatch — Narrowed Customer ownership to work-order `hold`/`resolve` actions only; no ownership check on any Customer GET/list — `routes/work_orders.py:36-42,128-176`
- **§2.3** — insert — ambiguity — Out-of-range `limit`, negative `offset`, or non-integer pagination → `ERR_INVALID_REQUEST` — `services/common.py:49-72`
- **§2.8** — insert — ambiguity — Successful visit-log write returns `201 Created` with mutated pool as `data` — `routes/pools.py:78-92`
- **§3.1** — insert — ambiguity — Duplicate-`email` create → `ERR_INVALID_REQUEST` — `routes/customers.py:31-33`
- **§3.1** — insert — ambiguity — Suspend not state-gated (re-suspend succeeds, bumps `version`/`updated_at`) — `routes/customers.py:56-65`
- **§3.2** — insert — ambiguity — Route-window minute bounds (`window_start_minute` 0–1439, `window_end_minute` 1–1440; out-of-range → `ERR_INVALID_REQUEST`) — `routes/route_assignments.py:30-31`
- **§3.4** — insert — ambiguity — Visit-create checks only existence of pool/plan/route + slot minute bounds — `routes/visits.py:81-103`
- **§3.5** — insert — ambiguity — Chemical reading recordable against visit in any status (no visit-state gate) — `routes/visits.py:300-329`
- **§3.6** — insert — ambiguity — Green-pool initial branch fires for any SCHEDULED+`green_pool`=true completion; sets `service_status` to `GREEN_RECOVERY` even if already in recovery — `routes/visits.py:159-218`
- **§3.7** — insert — ambiguity — WEATHER-makeup placement (first free minute in window, one-minute slot); no-free-slot → no makeup, `makeup_visit_id` stays null, skip still succeeds — `routes/visits.py:48-70,250-270`
- **§3.10** — insert — ambiguity — Invoice-create validates only existence of `pool_id`/`visit_id`/`work_order_id`, not referential linkage; balance accrues to named pool regardless — `routes/invoices.py:36-66,120`

**Notes:** Tests used only as auxiliary cross-reference. Additive list-filter params not named in §4 (`makeup_visit_id`, `raised_by_visit_id`) left unpinned as purely additive (§4 phrases filters non-exhaustively).

---

## Pipeline complete — task_0221_pool_spa_maintenance

All 9 steps executed. Final state: 67/67 tests pass across all 8 stability rounds under per-test-server isolation. Artifacts: SCAFFOLD.yaml (+ difficulty/corner design), workspace/PRD.md → PRD_COMPLETED.md, test_helpers/ + test_suite/ (67 tests), workspace/implementation/ (Python+Flask, in-memory). Step 8 skipped (Step 7 was clean on first sweep).
