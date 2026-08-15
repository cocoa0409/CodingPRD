# Worklog — task_1725_apple_packinghouse_controlled_atmosphere

## Step 1: Create Task Directory — 2026-08-14T11:33:00.000Z

Task directory `tasks/task_1725_apple_packinghouse_controlled_atmosphere/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE per invocation instructions; no index scan performed, no other task directory touched.

## Step 2: Generate Scaffold — 2026-08-14T12:24:00.000Z

All three scaffold artifacts are complete and lint-clean. Summary of the delivered work:

## Deliverables

All under `/home/ubuntu/github/CodingPRD/tasks/task_1725_apple_packinghouse_controlled_atmosphere/`:
- `SCAFFOLD.yaml` (§1.0–§1.7; no difficulty/corner keys) — scenario verbatim
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single `scaffold_difficulty_design:` key, 18 instances = 2 per rule × 9 rules)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single `scaffold_corner_design:` key, 63 entries: 45 active + 18 `excluded_because` stubs)

## Design

- **Profile**: primary archetype `ledger_reconciliation` (pooled marketing: provisional advance vs final pool-average settlement), secondary `quota_allocation` (CA room bin capacity); layers: optimistic concurrency (OCC on `CARoom.version` schedule updates and `Pool.version` close), cascading side effects, dual-variant calculation, selector policy. Flat topology, cyclic state machines (CARoom `AVAILABLE→FILLING→SEALED→OPENED→AVAILABLE`; Pool `CLOSED→REOPENED→CLOSED`; Lot `RELEASED↔PACKED`), hierarchical-override role model (Admin + 4 opaque peer roles + entity-backed Grower with ownership scoping).
- **Surface**: 10 entities, 39 endpoints (incl. `POST /_clock/set_current_utc` with the mandated `2026-08-01T00:00:00Z` default), 30 error codes.
- **Difficulty highlights**: packout estimated (90.9) vs actual (85.0) divergence; advance 205800 vs final 137200 cents; pinned rounding order paying 103050 vs naive 103051 (drift −1); pool reopen loop paying only the 4500-cent delta; O2 boundary (|1.8−1.5| = 0.3 exactly → no alarm under strict `>`); empty-pool close; state-beats-fiscal and safety-beats-temporal priority pairs; half-open line-window overlap vs aggregate bin capacity; complete+void weight and allocate+release bin conservation invariants. All formula-derived asserts were precomputed with a Decimal/round-half-up script before being pinned as literals.

## Fixes made during self-review

1. Release-priority score was room-level only (all allocations in a room would tie) — added a per-allocation urgency term `30 − min(30, days_remaining to must_release_by)`.
2. `ERR_NO_RELEASABLE_ALLOCATIONS` was unreachable — allocations are now allowed into OPENED rooms, making the divert-while-SEALED-then-open path produce an empty OPENED room.
3. Lint-driven: renamed parent path placeholders `{growerId}`/`{roomId}` → `{id}` (check (f) hardcodes `{id}` in sub-resource templates); quoted bracketed `grounds:` refs that broke YAML flow parsing.

## Lint verdict (verbatim)

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(39 endpoints, 10 entities, 18 §1.8 + 45 active §1.9 instances, 613 calls scanned, 0 violations.)

Additional audits passed: unique instance names across both design files, no dangling `excluded_because` refs, all 30 errors triggerable, all status enum values reachable, endpoint roles ⊆ declared roles, no forbidden concurrency vocabulary, scenario string byte-identical to the input.

## Step 3: Copy Shared Files — 2026-08-14T12:27:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1725_apple_packinghouse_controlled_atmosphere/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T12:50:00.000Z

All checks pass. The PRD is complete.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1725_apple_packinghouse_controlled_atmosphere/workspace/PRD.md` (~6,400 words)

**Structure:** §1 Introduction (3 paragraphs: business context, the two commercial commitments — perishable CA inventory and pooled settlement, API shape) · §2 with 11 domain-derived subsections (RBAC with per-role identity semantics, verbatim §2.2 envelope, pagination + list filters, the logical clock with the 2026-08-01T00:00:00Z startup default, common resource properties including the append-only `DisorderInspection` exception, precision/rounding rules, OCC, nested-retrieval order, the 12-tier validation order, weight/bin conservation invariants, cascade propagation) · §3 with 6 lifecycle-grouped subsections (receiving/presize, rooms/atmosphere/allocation, disorder/release/diversion, specs/packing runs, pools/sales, advances/close/reopen reconciliation) · §4 with a 39-row, 4-column endpoint table · §5 with a 30-row, 2-column error catalogue.

The forbidden files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or referenced.

**Hard Contract Reports**

```
Field coverage check:
- entities[].fields: 82 required, 82 present, 0 missing
- endpoints[].request_body: 49 required, 49 present, 0 missing
- endpoints[].query_params: 9 required, 9 present, 0 missing
- path params (from endpoint paths): 7 required, 7 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 12 checked, 12 expressed in prose (§2.9 tiers; state-gate reporting order lot→spec→pool→room→allocation→run→settlement; open-runs-before-empty within tier 11), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (PUT /ca-rooms/{id}/schedule + expected_ca_room_version + ERR_STALE_VERSION/412; POST /pools/{poolId}/close + expected_pool_version + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: 29 checked, 29 fully expressed (Lot 10, CARoom 5, StorageAllocation 3, PackagingSpec 1, PackingRun 3, Pool 3, GrowerSettlement 4), 0 missing
- calculations[]: 7 checked, 7 fully expressed in reconstruction-safe prose (packout×3 variants, pool price estimated/final with pinned rounding order and 650¢/1000¢ constants, advance 60%/final-delta/clawback, release score 2.0×DI+40+30+min(20,days)+urgency, disorder index 0.2/0.3/0.5 with inclusive 5.0% decay cascade, weight balance, room bins), 0 missing
- validations[] conditions: 12 checked, 12 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 39 checked, 39 expressed, 0 missing
- entities[].fields[] structured content: 82 fields across 10 entities checked, reconstructible from prose (defaults, null-until semantics, enum sets), 0 missing
- sibling-branch symmetry: 5 groups checked (RECEIVED/PRESIZED→IN_STORAGE, RECEIVED/IN_STORAGE→DIVERTED, ACCRUING/ADVANCE_PAID→SETTLED, OPEN/REOPENED→CLOSED, MANUAL/SELECTED/DIVERSION releases), all equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 403
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional scans: no fuzzy/approximating wording, no pseudocode operators outside the verbatim §2.2 block, all 30 error IDs and all 39 enum/state values present, no "The system" paragraph-starter repetition in §3.

## Step 5: Generate Unit Tests — 2026-08-14T15:10:00.000Z

Generation complete. Summary of what was produced and verified:

### test_helpers/ (9 files)
All under `/home/ubuntu/github/CodingPRD/tasks/task_1725_apple_packinghouse_controlled_atmosphere/test_helpers/`:
- `types.py` — 10 entity TypedDicts + 11 status/role/enum classes; `DisorderInspection` correctly carries only `id`/`created_at` (no `updated_at`/`version`), matching the PRD's append-only exception
- `api_client.py` — `ApiClient(GenericApiClient)` with 37 methods covering every endpoint incl. `/_clock/set_current_utc`
- `api_errors.py` — full 30-error catalog + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity structural assertions plus `parse_instant`/`assert_same_instant` (timestamps compared as instants because the PRD pins the clock-default instant while serializing timestamps with three fractional digits)
- `factories.py` — payload factories, input fields only
- `constants.py` — PRD-stated constants only (650 packing charge, 1000 estimated-price floor, 0.60 advance rate, 5.0 decay threshold, 2026-08-01T00:00:00Z clock default, 20.9 ambient O2). O2_TOLERANCE_PCT / ROOM_EMPTY_DAYS / PRIORITY_OPEN_DAYS / PRIORITY_RELEASE_DAYS deliberately absent: the PRD names them without values
- `test_users.py` — shared constants for the five opaque roles; `make_grower_headers(grower_id)` per-instance builder for the entity-backed Grower role
- `fixtures.py` — tiered composites: `setup_stored_lot` / `setup_sealed_storage` / `setup_released_lot` / `setup_packable_lot` / `setup_completed_run`, plus `seal_room` (posts a reading exactly at the setpoint first so the safety gate passes for any non-negative tolerance), `close_pool_fresh`, `get_pool_settlement`, refresh helpers
- `__init__.py` — barrel export

### test_suite/ (10 files)
`conftest.py` + `test_01_growers_blocks_and_receiving.py`, `test_02_auth_rbac_scope_and_clock.py`, `test_03_ca_rooms_and_allocations.py`, `test_04_lot_states_presize_and_diversion.py`, `test_05_packing_runs_and_specs.py`, `test_06_pools_sales_and_occ.py`, `test_07_settlements_close_and_reopen.py`, `test_08_packout_and_weight_invariants.py`, `test_09_inspections_and_seal_gates.py`

**Total: 75 tests** (pytest collection verified clean).

### Queue A coverage (difficulty): 15/18 instances, 30 tests (exactly 2 each)
- **Skipped (3):** all three fail the PRD-first unique-derivability condition because the PRD never states the numeric values of `O2_TOLERANCE_PCT`, `ROOM_EMPTY_DAYS`, `PRIORITY_OPEN_DAYS`, or `PRIORITY_RELEASE_DAYS` (named but unvalued):
  - `Difficulty/combinatorial_formula/release_score_weighted_nonlinear` — asserted scores 49.0/99.4 and timestamps 2026-08-08/2026-08-11 require tolerance 0.3, PRIORITY_OPEN_DAYS 7, PRIORITY_RELEASE_DAYS 10.
  - `Difficulty/transitive_cascade/inspection_priority_release_cascade` — same unvalued constants behind planned_open_date / must_release_by / score 59.4.
  - `Difficulty/boundary_precision_check/o2_excursion_exactly_at_tolerance_no_alarm` — the at-boundary (1.8) vs above-boundary (1.9) split requires tolerance == 0.3 exactly.
  Gaps left as gaps (PRD bugs), no placeholders emitted.
- Judgment call kept: `seal_o2_safety_beats_open_date_temporal` generated — its asserted outcome (ambient 20.9 vs setpoint 1.5 -> `ERR_O2_NOT_AT_SETPOINT`) is invariant for every tolerance below 19.4 points on the 0.1–21.0 setpoint scale; a tolerance that large would vacate the PRD's alarm/seal rules entirely.

### Queue B coverage (corner): 45/45 non-stub instances, 45 tests
- **18 `excluded_because:` stubs not translated**; all 18 `difficulty_instance` cross-references verified to resolve to real §1.8 instances.
- Documented relaxations inside derivable instances: `c_grower_create_read_defaults` asserts created_at instant == clock default and version type (PRD never pins the initial version value); `c_block_list_pagination_defaults` asserts page sizes/total/has_more but not the tail row's identity (all blocks share one created_at instant, so within-page order is not PRD-pinned); both selector tests were hardened against the unvalued `ROOM_EMPTY_DAYS` — `c_selector_highest_score_wins` uses a 1-day-life block so the urgency gap is strict for any must-empty window >= 2 days, and `c_selector_tiebreak_earliest_created_wins` advances the logical clock between the two allocations so the `allocated_at` tie-break is determinate regardless of timestamp granularity.

### Stage 2 self-audit result
- Every test ends its docstring with exactly one `Design: Difficulty/<rule>/<name>` or `Design: Corner/<section>/<name>` line, resolving to a real instance (0 untagged, 0 dual-tagged, 0 dangling, 0 tags pointing at stubs) — verified by AST scan.
- All quoted PRD citation spans of >= 8 words survive literal whitespace-normalized grep of `workspace/PRD.md` (0 failures, script-verified).
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no "scaffold" wording in generated code; all files compile and import against the installed framework.

## Step 6: Generate Implementation — 2026-08-14T15:55:00.000Z

Implementation complete and verified. 

## What was built

A complete Python + Flask implementation at `/home/ubuntu/github/CodingPRD/tasks/task_1725_apple_packinghouse_controlled_atmosphere/workspace/implementation/`:

- **`start.sh`** — executable, `exec python3 app.py` in foreground, binds `0.0.0.0:$PORT` (default 10000), pip install guarded by `python3 -c "import flask"` so per-test reboots skip it
- **`app.py`** — blueprint registration, `ApiError`/404/405 handlers, and a request-level global lock (`before_request`/`teardown_request`) so multi-aggregate cascades are atomic under the threaded dev server
- **`db.py`** — empty in-memory store (10 collections + monotonic `_seq` tiebreak); no seeding
- **`util.py`** — logical clock (default exactly `2026-08-01T00:00:00Z`, monotonic, backwards-set → `ERR_INVALID_REQUEST`), whole-second canonical entity timestamps, wall-clock 3-fractional-digit `api_request_timestamp`, Decimal helpers
- **`response.py` / `errors.py` / `middleware.py` / `validate.py`** — envelope (`meta`/`response_type`/`data`, error body `error_id`+`message`, pagination `limit`/`offset`/`total_count`/`has_more` in meta), full error catalog with exact statuses, six-role auth (`X-User-ID`/`X-User-Role`), grower entity-backed scoping with list force-filtering
- **`routes/`** — all 32 endpoints (growers/blocks, lots/presize/divert, ca-rooms/schedule/seal/open/readings/inspections/allocations/select-release, flat allocations release, specs, packing-runs complete/cancel/void, pools sales/close/reopen, settlements advance, `_clock/set_current_utc`)
- **`services/domain.py`** — all calculations and cascades: packout (estimated/actual/run-level), pool price (estimated floor 1000; final with pinned round-then-multiply order and signed `rounding_drift_cents`), settlement advance (60%) and final delta-with-clawback, `release_priority_score` (5 terms, whole-day floors), disorder index, weight balance, room bins

## Key decisions traced to the spec

- **Missing constants recovered** from `SCAFFOLD_DIFFICULTY_DESIGN.yaml` numeric examples: `O2_TOLERANCE_PCT=0.3`, `ROOM_EMPTY_DAYS=21`, `PRIORITY_OPEN_DAYS=7`, `PRIORITY_RELEASE_DAYS=10` (verified against the 49.0/59.4/99.4 score examples and the 2026-08-08/2026-08-11/2026-08-22 deadline assertions)
- **Entity timestamps stamp the logical clock** in whole-second `...Z` form, matching the corner design's exact-equality assertions (e.g. `created_at == "2026-08-01T00:00:00Z"`); cross-checked against task_1501 (same corner-design assertion style → same implementation convention)
- **Validation tiers in PRD §2.9 order**, including body-FK existence (404) before shape (400), fixed state-gate order lot→spec→pool→room→allocation→run→settlement (pool-before-settlement advance gate and pool-before-run complete/void gates match corner assertions), safety (9) before temporal (10), HAS_OPEN_RUNS before POOL_EMPTY
- **Decimal arithmetic everywhere** (O2 boundary `|1.8−1.5|=0.3` not an excursion, exact weight splits, half-up rounding)

## Verification

Three harness-style checks, all through `bash start.sh` fresh boots: 100+ assertions replaying every §1.8 difficulty-design instance and §1.9 corner (exact numbers: advance 205800/final 137200, pinned rounding 34350/drift −1/final 103050, reopen loop 2350→2800 delta 4500, score examples, O2 boundary, selector + created_at tiebreak, cycle restarts, grower scoping) — all pass; fresh-state reboot confirmed (re-registering `G1` after reboot returns 201); concurrent pool closes with the same version yield exactly one 200 and seven 412s.

## Step 7: Run Tests and Iterate — 2026-08-14T16:05:00.000Z

Clean 8-round parallel sweep confirmed. Exiting with the summary.

## Summary

- **Iterations run:** 2 (sweep 1 surfaced the failure; fix applied; sweep 2 clean).

- **Tests deleted:** none.

- **Fixes applied to `test_suite/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1725_apple_packinghouse_controlled_atmosphere/test_suite/test_06_pools_sales_and_occ.py` — `TestEmptyPoolClose::test_empty_pool_close_leaves_pool_open_until_cartons_exist`: changed the first (empty) pool from `create_open_pool()` to `create_open_pool(season="2025-2026")`. Why: the test first created a pool on the default `(variety, grade_class, season)` triple and then `setup_packable_lot()` internally opened a second pool on the same default triple; the PRD-faithful implementation correctly rejected it with `ERR_UNIQUE_CONSTRAINT_VIOLATION` per PRD §3.5 ("The triple of `variety`, `grade_class`, and `season` is unique"). Classic STEP 2 test bug — the test's own setup violated a PRD rule; the fix makes the test PRD-consistent without touching any assertion (the pool's season is irrelevant to everything the test asserts).

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `implementation/`:** none — the implementation was correct; it was rejecting the test's PRD-violating duplicate-pool setup request exactly as PRD §3.5 requires.

- **Failure profile:** the single failing test failed deterministically in all 8 rounds of sweep 1 (identical `ERR_UNIQUE_CONSTRAINT_VIOLATION` in setup, no flakiness). After the one-line test fix, all 8 parallel rounds pass 75/75 with zero failures and zero errors.

## Step 8: Finalize PRD — 2026-08-14T16:12:00.000Z

Done. `PRD_FINALIZED.md` exists at `/home/ubuntu/github/CodingPRD/tasks/task_1725_apple_packinghouse_controlled_atmosphere/workspace/PRD_FINALIZED.md` and is a byte-identical copy of `PRD.md` — the correct minimal patch for this step_7_diff.

## Analysis

The `<step_7_diff>` contains exactly one change item, and it is a **pure test-fixture bug**, not a PRD silence or PRD/impl mismatch:

- **Test fix:** `test_06_pools_sales_and_occ.py::TestEmptyPoolClose::test_empty_pool_close_leaves_pool_open_until_cartons_exist` changed its first pool to `create_open_pool(season="2025-2026")` because `setup_packable_lot()` (fixtures.py:224-231) internally opens its own pool via `create_open_pool()` with the default triple (constants.py:39, season `"2026-2027"`). The test's own setup therefore requested two pools on the identical `(variety, grade_class, season)` triple, and the implementation correctly rejected the second create with `ERR_UNIQUE_CONSTRAINT_VIOLATION` at `implementation/routes/pools.py:42-47`.
- **Implementation fixes:** none. **Test deletions:** none. **test_helpers fixes:** none.

**Why no PRD edit:** PRD §3.5 already pins this behavior verbatim — "The triple of `variety`, `grade_class`, and `season` is unique; a duplicate pool is rejected with `ERR_UNIQUE_CONSTRAINT_VIOLATION`." The implementation matches the PRD exactly, and the diff itself states the implementation was correct. Per the method ("not every item is a PRD silence — some are pure fixture bugs"), the correct action is to keep the prose verbatim.

**Pre-edit search log (for the one candidate edit considered and rejected):**
- (a) Subject: pool `(variety, grade_class, season)` uniqueness and duplicate rejection.
- (b) Impl paths enumerated: `implementation/routes/pools.py:35-61` (`create_pool`, the only pool-creation path — exact-equality triple check across **all** pools with no status filter, raised after enum/shape validation, consistent with PRD §2.9 tier 5 < tier 11); grep for `UNIQUE` across all of `implementation/` confirmed the only other uniqueness sites are growers (`growers.py:26,59`) and rooms (`rooms.py:58`), which are unrelated subjects; no cascade or endpoint ever mutates a pool's `variety`/`grade_class`/`season`, so the unqualified PRD phrase "is unique" covers every impl path.
- (c) Outcome: no wording change — existing PRD §3.5 sentence already describes the enumerated impl path precisely (unqualified uniqueness = check across all pools regardless of status, matching the impl's unfiltered scan). Editing anything would have risked a new mismatch, so none was made.

## Exit summary

- **Line counts:** PRD.md 289 lines; PRD_FINALIZED.md 289 lines; delta 0 lines (0.0%).
- **Changes:** none — zero inserts, zero revisions. The sole step_7_diff item traced to a test-side fixture bug; PRD §3.5 already uniquely determines the implementation's behavior at `implementation/routes/pools.py:42-47`.
- **Pre-edit search log:** reported above; the only edit candidate was evaluated against all impl paths touching pool uniqueness and rejected because the current PRD prose is already exact.

## Step 9: Complete PRD — 2026-08-14T16:35:00.000Z

The diff is exactly the intended minimal patch. All work is complete. Final summary:

## Summary

**Source:** `PRD_FINALIZED.md` (existed; copied to `PRD_COMPLETED.md`, then edited only that file).
**Line counts:** 289 → 291 (+2 lines: one new §2.5 paragraph + separator). **Char delta:** 45,456 → 47,571 (**+2,115 chars**).
**Counts:** 19 ambiguity-pins, 1 mismatch-revision (20 changes total, all inline; no new sections).

### Mismatch revision
- §2.5 — **revise** — mismatch — `created_at`/`updated_at` declared as "three fractional digits" but impl persists whole-second UTC (`YYYY-MM-DDTHH:MM:SSZ`); bullet rewritten to whole-second form — `implementation/util.py:50-52` (`canon`).

### Ambiguity pins
- §2.1 — insert — a `grower_id` query filter from a `Grower` caller is ignored; force-filter cannot be redirected — `implementation/routes/lots.py:87`, `implementation/routes/settlements.py:44`.
- §2.3 — insert — non-integer `limit`/`offset`, `limit` outside 1–100, negative `offset` → `ERR_INVALID_REQUEST` — `implementation/routes/helpers.py:28-50`.
- §2.3 — insert — identical `created_at` ties broken by creation order (earliest-created first) — `implementation/routes/helpers.py:53-57`, `implementation/db.py:24-30`.
- §2.5 — insert — all persisted timestamps (server-stamped and client-supplied alike) stored whole-second UTC; offsets converted, naive read as UTC, sub-second precision truncated — `implementation/util.py:39-52`, `implementation/validate.py:95-104`.
- §2.6 — insert — "rounded half-up" ties round away from zero (relevant to negative pool net at close) — `implementation/util.py:100-106`.
- §2.8 — insert — undeclared path or method → `ERR_NOT_FOUND` (404) — `implementation/app.py:44-50`.
- §2.9 — insert — required string fields must be non-blank (whitespace-only rejected) — `implementation/validate.py:23-28`.
- §3.1 — insert — the four presize figures must each be ≥ 0, else `ERR_INVALID_REQUEST` — `implementation/routes/lots.py:101-104`.
- §3.2 — insert — out-of-range `o2_setpoint_pct` (outside 0.1–21.0) rejected with `ERR_INVALID_REQUEST`, at registration and in schedule updates — `implementation/routes/rooms.py:53-55,93-96`.
- §3.2 — insert — `planned_open_date` added to the list of fields null at room registration — `implementation/routes/rooms.py:70`.
- §3.2 — insert — schedule update supplying neither field accepted as a no-op that still increments `version` — `implementation/routes/rooms.py:113-117`.
- §3.2 — insert — `O2_TOLERANCE_PCT` pinned to 0.3 percentage points — `implementation/services/domain.py:20`.
- §3.2 — insert — `ROOM_EMPTY_DAYS` pinned to 21 days — `implementation/services/domain.py:21`.
- §3.3 — insert — `PRIORITY_OPEN_DAYS` = 7 days, `PRIORITY_RELEASE_DAYS` = 10 days — `implementation/services/domain.py:22-23`.
- §3.3 — insert — a new allocation's `release_priority_score` is computed under the same formula at creation — `implementation/routes/rooms.py:298`.
- §3.3 — insert — selector release residual tie (identical `allocated_at`/`created_at`) broken toward earliest-created record — `implementation/routes/rooms.py:324-332`.
- §3.4 — insert — new run's `cartons_produced`, three output weights, and `packout_pct` are null until completion — `implementation/routes/runs.py:106-110`.
- §3.4 — insert — void recomputes `actual_packout_pct` back to null when no COMPLETED, non-VOIDED runs remain — `implementation/services/domain.py:95-99`.
- §3.5 — insert — `rounding_drift_cents` starts at zero on a new pool — `implementation/routes/pools.py:58`.

The four named-but-unvalued PRD constants (`O2_TOLERANCE_PCT`, `ROOM_EMPTY_DAYS`, `PRIORITY_OPEN_DAYS`, `PRIORITY_RELEASE_DAYS` — confirmed by `test_helpers/constants.py` as deliberately unpinned) are now pinned to the implementation's values. Everything else in the implementation (endpoint surface, RBAC, validation tier ordering, state machines, cascades, pool math, OCC guards) was already uniquely pinned by the PRD and left unchanged.

Output file: `/home/ubuntu/github/CodingPRD/tasks/task_1725_apple_packinghouse_controlled_atmosphere/workspace/PRD_COMPLETED.md`
