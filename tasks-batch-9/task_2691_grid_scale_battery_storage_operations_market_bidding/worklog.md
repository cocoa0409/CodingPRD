# Worklog — task_2691_grid_scale_battery_storage_operations_market_bidding

## Step 1: Create task directory — 2026-09-04T07:10:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2691_grid_scale_battery_storage_operations_market_bidding` and its `workspace/` subdirectory. Index 2691 was pre-assigned by the orchestrating caller; no scan of ./tasks/ was performed (concurrent pipelines on this host).

## Step 2: Generate Scaffold — 2026-09-04T08:52:00.000Z

All nine §1.9 sections are on disk and the scaffold lints clean.

## Verdict (verbatim from `scaffold_lint.py`)

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

with coverage: 47 endpoints declared, 9 entities declared, 19 §1.8 instances scanned, 59 §1.9 instances scanned (the 31 `excluded_because` stubs are skipped by design), 740 calls scanned.

## Counts

**SCAFFOLD.yaml (§1.0–§1.7)** — `domain_name: grid-scale-battery-storage-operations`, `api_prefix: "/"`
- 9 entities, 10 state machines (2 parallel axes on `StorageAsset`, 2 on `DispatchInstruction`), 1 concurrency rule, 7 calculations, 34 validations, **47 endpoints**, **56 error codes**, 7 roles
- `complexity_profile`: primary `quota_allocation`, secondary `pricing_engine`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers]`, topology `flat`, shape `parallel`, role model `segregation_of_duties`, consistency `immediate`
- Deliberately above the §0.4 Expert band (10–15 entities / 20–32 endpoints / 18–30 errors) on endpoints and errors, per the "harder than expert" brief

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)** — 9 rules / 19 instances (≥2 differentiated instances per rule)

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9)** — 9 sections / 90 instances (59 full recipes + 31 stubs):
entities 12, state_machines 15, calculations 13, validations 9, endpoints 5, errors 24, rbac 6, cross_cutting_complexity_layers 4, consistency_model 2

## Verified invariants
- All 56 error codes are reachable: every code is asserted in either a §1.8 instance or a non-stub §1.9 instance (checked programmatically, zero uncovered).
- Every `excluded_because.difficulty_instance` resolves to a real name in SCAFFOLD_DIFFICULTY_DESIGN.yaml (0 bad citations); no stub carries a `test_recipe`, no real instance lacks one.
- Instance names unique across the union of both design files (0 duplicates).
- `SCAFFOLD.yaml` contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`; the other two files have exactly one top-level key each.
- No sibling `task_*/` directory was listed, read, or grepped.

## SCAFFOLD.yaml fixes forced by writing §1.9
- `WarrantyClaim` submit precondition `X-User-ID != created_by_user_id` deleted — it demanded a segregation the priority-8 rule does not cover (which left the violation with no error code); SoD now applies to `adjudicate` and `safety-events/{id}/close` only, as the rule and `ERR_SEGREGATION_OF_DUTIES` state.
- `TelemetrySample.measured_mvar` constraint rewritten: it previously duplicated the priority-17 magnitude bound as a field constraint, which would have made `ERR_REACTIVE_LIMIT_EXCEEDED` unreachable behind `ERR_INVALID_REQUEST`.
- Priority-9 check now pins multi-guard order (`ERR_DISPATCH_NOT_COMPLETED` before `ERR_SCORE_NOT_PROVISIONAL` on `settle-score`), removing a genuine ambiguity for a PENDING instruction.
- `MarketBid.cleared_mw` gained a constraint routing an award above `offer_mw` to priority 3 / `ERR_INVALID_REQUEST`, so the state-machine precondition `cleared_mw <= offer_mw` is no longer codeless.

## File sizes
```
SCAFFOLD.yaml                    151087 bytes
SCAFFOLD_DIFFICULTY_DESIGN.yaml  115082 bytes
SCAFFOLD_CORNER_DESIGN.yaml      229736 bytes
```

## Step 3: Copy Shared Files — 2026-09-04T08:53:00.000Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T09:12:00.000Z

PRD generation for task_2691 is complete.

## Output
`workspace/PRD.md` — **508 lines**, written in 10 chunked `cat >> PRD.md <<'EOF'` appends (no single giant Write, so no 64k truncation).

## Section list
```
# Grid-Scale Battery Storage Operations API — Product Requirements Document
## 1. Introduction
## 2. Global Specifications & System-Wide Principles
   2.1 Operating Roles and Request Identity
   2.2 API Response Structure                      (verbatim fixed block)
   2.3 Pagination, Ordering and Filtering
   2.4 Common Resource Properties and the Version Counter
   2.5 The Stale-Asset Guard on Reservation Creation
   2.6 Request Screening Order                     (34-step ladder)
   2.7 Units, Precision and Rounding
   2.8 The Logical Clock
   2.9 Deterministic Cascades and Conserved Ledgers
## 3. Business Logic & Workflows
   3.1 Registering and Commissioning a Storage Asset
   3.2 Carving Up the State-of-Charge Pool
   3.3 Constructing an Offer and Pricing the Degradation It Costs
   3.4 Submission, Clearing, the Revision Loop and Withdrawal
   3.5 Dispatch Execution and the Telemetry Stream
   3.6 Performance Scoring, Settlement and the Compensating Reversal
   3.7 Safety Posture, Suppression, and the Suspension Cascade
   3.8 Capacity Commitments, Availability Accrual and Two Ways of Assessing Them
   3.9 Degradation Testing, Warranty Claims and Augmentation
## 4. API Endpoints        (47 rows, 4 columns)
## 5. Error Codes          (56 rows, 2 columns)
```

## Non-truncation proof
`wc -l` = 508; orchestrator independently verified the tail: document ends on a complete §5 table row (`| ERR_CLAIM_FILING_WINDOW_EXPIRED | 422 |`), a real section boundary. NOT truncated.

## Hard Contract reports
**Contract 1 — Field-Name Coverage: PASS.** All 135 scaffold identifiers appear verbatim inside backticks in PRD.md; 0 missing.

**Contract 2 — Rule Coverage: PASS.** All 56 distinct error identifiers appear in §1–§3 prose *and* the §5 catalogue, with all 56 HTTP status codes matching the scaffold exactly. §2.6's 34 numbered steps reproduce the scaffold's validation priority order 1-to-1. All 10 state machines' from/to states are named; all 7 calculations' output fields documented. The OCC rule (`StorageAsset.version` via `expected_asset_version`, `ERR_STALE_ASSET_VERSION` 412) has its own subsection §2.5 plus screening step 10.

**Contract 3 — §3 Path Purity: PASS.** 0 backticked tokens in §3 begin with `/`, 0 are a bare HTTP method.

**§4/§5 shape checks:** §4 is 4 columns / 47 rows, all (method, path) pairs and authorized-role sets match the scaffold. §5 is 2 columns / 56 rows.

**Constraints honored:** neither design yaml was opened, grepped, or referenced. No difficulty/test-design language leaked into the PRD.

**Two scaffold inconsistencies resolved in prose:** (1) bid state machine has `UNCLEARED → DRAFT` while the catalogue names `ERR_BID_NOT_SUBMITTED` for a bad revise — §3.4 states revise departs from `UNCLEARED`, any other status yields `ERR_BID_NOT_SUBMITTED`; (2) list ordering — every list endpoint description in this scaffold says newest first, so §2.3 documents descending `created_at` for all top-level collections, with an instruction's telemetry ascending by `sampled_at`.

## Step 6: Generate Implementation — 2026-09-04T09:46:00.000Z

The implementation is complete, boots cleanly, and all 47 endpoints are registered.

## Files written
`workspace/implementation/`

| file | lines | bytes |
|---|---|---|
| `start.sh` (exec, guarded pip install, chmod +x) | 10 | 399 |
| `requirements.txt` | 1 | 13 |
| `app.py` | 63 | 2217 |
| `db.py` (in-memory store, logical clock) | 152 | 4349 |
| `errors.py` (all 56 error IDs) | 86 | 4098 |
| `numeric.py` (Decimal/ROUND_HALF_UP) | 65 | 1546 |
| `response.py` (envelope + pagination) | 58 | 1586 |
| `middleware.py` (auth/RBAC/ownership) | 51 | 1836 |
| `validators.py` (shape screening) | 217 | 7772 |
| `services/calc.py` (7 calculations) | 296 | 10252 |
| `services/core.py` (derivations, cascades, waterfall) | 595 | 21461 |
| `routes/assets.py` (5 endpoints) | 139 | 5260 |
| `routes/reservations.py` (4) | 117 | 3941 |
| `routes/bids.py` (7) | 346 | 13631 |
| `routes/dispatches.py` (8) | 332 | 13569 |
| `routes/telemetry.py` (2) | 119 | 5073 |
| `routes/safety.py` (5) | 138 | 5307 |
| `routes/obligations.py` (5) | 150 | 5474 |
| `routes/captests.py` (5) | 183 | 6895 |
| `routes/claims.py` (6) | 197 | 7261 |

Total 3315 lines. `__pycache__` dirs from the smoke run were removed.

## Endpoint coverage
`app.url_map` reports exactly **47 rules / 47 method-paths**, matching the scaffold endpoint table (5 asset + clock, 4 reservation, 7 bid, 8 dispatch, 2 telemetry, 5 safety, 5 obligation, 5 capacity-test, 6 warranty-claim).

## Smoke test (random port 24442, killed by recorded PID only)
Boot took under 2s. Verified end-to-end:
- Envelope: `meta.api_request_id` = `req_` + 20 alnum, `api_request_timestamp` with 3 fractional digits, `response_type` object/array/error, `data`; list responses carry `limit`/`offset`/`total_count`/`has_more` inside `meta`; `limit=500` -> `ERR_INVALID_REQUEST` 400.
- Auth: missing `X-User-ID` -> `ERR_UNAUTHENTICATED` 401; wrong role -> `ERR_FORBIDDEN_ROLE` 403; unknown asset -> `ERR_ASSET_NOT_FOUND` 404; unknown route -> `ERR_INVALID_REQUEST` 404 in the standard envelope.
- Full trading flow: register asset (`rated=100.0`, `available=100.0`, `free_dispatchable=40.0`) -> commission (version 2) -> SoC reservation with `expected_asset_version` -> draft bid -> submit -> clearing-result -> dispatch -> accept -> execute -> telemetry sample (`apparent_mva=10.198`, `error_ratio=0.0`, `within_deadband=true`) -> complete (`delivered_mwh=2.5`, `soc_delta=-2.5`, composite 100.0, PROVISIONAL) -> settle-score (SETTLED). Asset ledgers conserved: `soc 47.5`, `throughput 2.5`, `efc 0.0125`, `reserved_total 0.0`, `free 37.5`.
- Obligation enrol -> unavailability -> FINAL assess (`measured_available_hours 8750.0`, `availability_pct 99.89`).
- Capacity test schedule -> start -> complete (`measured_soh 70.0`, `expected_soh 98.48`, `deficit 28.48`, `warranty_claim_triggered true`).
- Warranty claim draft (`claimed_shortfall_pct` copied 28.48) -> submit -> adjudicate as PlatformAdmin (`remedy_energy_add_mwh 31.328`, asset unchanged) -> install-remedy rejected as `ERR_CLAIM_NOT_APPROVED` before `remedy_install_date`, accepted after the clock was advanced; asset then `rated 131.328`, `available 91.930`, `free 37.5` — the documented propagation order.
- Fresh-boot cleanliness: a second server on a new port reports `total_count: 0` for all 8 collections — no seeding anywhere.

Both servers were stopped by their specific PID (3892862 and 3926036); no broad `pkill` was used. Did not touch `test_helpers/`, `test_suite/`, the difficulty/corner design files, or any sibling task.

## Step 5: Generate Unit Tests — 2026-09-04T10:34:00.000Z

Generation complete for task 2691. No server was started and no pytest run; static generation only.

## Output location (task root, nothing under `workspace/`)

### `test_helpers/` — 9 files, 2091 lines
| file | bytes | lines |
|---|---|---|
| `__init__.py` | 1823 | 66 |
| `types.py` | 9212 | 393 |
| `api_client.py` | 8895 | 215 |
| `api_errors.py` | 6131 | 125 |
| `constants.py` | 1662 | 56 |
| `test_users.py` | 2736 | 64 |
| `factories.py` | 5750 | 206 |
| `assertions.py` | 10342 | 230 |
| `fixtures.py` | 24228 | 785 |

### `test_suite/` — 18 files, 7100 lines, 248 tests
| file | bytes | lines | tests |
|---|---|---|---|
| `conftest.py` | 671 | 22 | - |
| `test_01_dual_variant_scoring_and_assessment.py` | 9141 | 192 | 7 |
| `test_02_offer_pricing_and_degradation_model.py` | 10448 | 226 | 7 |
| `test_03_parallel_axes_and_negotiation_cycle.py` | 9905 | 214 | 7 |
| `test_04_cascades.py` | 15074 | 320 | 8 |
| `test_05_screening_precedence.py` | 7170 | 170 | 6 |
| `test_06_boundaries.py` | 11153 | 258 | 8 |
| `test_07_cross_entity_state_dependencies.py` | 15849 | 375 | 11 |
| `test_08_temporal_windows.py` | 11773 | 256 | 10 |
| `test_09_conservation.py` | 10538 | 219 | 9 |
| `test_10_entity_records_and_listings.py` | 15868 | 373 | 13 |
| `test_11_lifecycle_transitions.py` | 22352 | 497 | 20 |
| `test_12_derived_calculations_and_ledger_visibility.py` | 22446 | 530 | 18 |
| `test_13_business_rule_validations.py` | 33070 | 758 | 27 |
| `test_14_endpoint_surface.py` | 14144 | 334 | 12 |
| `test_15_state_conflict_errors.py` | 28796 | 661 | 25 |
| `test_16_limit_and_reference_errors.py` | 42237 | 1022 | 38 |
| `test_17_role_authorization.py` | 25186 | 624 | 22 |

## Coverage against the two design indices
- **§1.8 (queue A, difficulty): 19/19 instances translated**, every one with >=2 tests (78 tests across `test_01`-`test_09`, plus the rule-bearing modules `test_11`-`test_13` where difficulty rules extend).
- **§1.9 (queue B, corner): 59/59 non-stub instances translated** — `entities` 12/12, `state_machines` 7/7, `calculations` 4/4, `consistency_model` 2/2, `validations` 6/6, `cross_cutting_complexity_layers` 2/2, `endpoints` 5/5, `errors` 15/15, `rbac` 6/6. The 31 instances carrying `excluded_because:` were not translated (stubs, by contract).
- **Skipped instances: none.** No non-stub instance failed the PRD-first two-condition filter, so there are no gaps and no skip/xfail markers anywhere in the suite.

## Verification performed
- Every file `ast.parse`s cleanly.
- Every one of the 248 tests carries **exactly one** trailing `Design:` line; every tag resolves to a real non-stub instance whose section/rule_id matches the tag's queue.
- Every `PRD: "..."` citation passes a literal substring check against `workspace/PRD.md` (C1 verbatim), is rule-bearing prose rather than an endpoint-table row, and is a full sentence.
- Zero unused imports (fixed three found in a final sweep). Zero occurrences of the word "scaffold".

## Design-index deviations worth recording
Each is a sub-probe adjustment where the recipe contradicted the PRD; in every case the PRD value was asserted and the instance's claim is still exercised:
- `half_open_reservation_windows...` — recipe's priority ranks contradict PRD §3.2; tests assert the PRD ranks.
- `market_bid_revision_cycle_reaches_revision_limit` — recipe revises from UNCLEARED, not SUBMITTED.
- `bid_window_ramp_buffer...` — recipe's 13:16 challenger violates the whole-quarter-hour rule; a legal 13:45-14:45 window was used.
- `claim_filed_on_day_thirty...` — each probe builds a fresh world so only the filing-window rule can fire.
- `other_roles_exclusive_operations_are_forbidden` — recipe's invalid `denial_reason "OUT_OF_WARRANTY"` replaced with the valid `"NO_SHORTFALL"` (403 assertion unaffected: priority 2 outranks priority 3).
- `every_path_id_returns_its_own_entity_specific_not_found` — two extra `ERR_DISPATCH_NOT_FOUND` tests (direct read + nested telemetry read) derived from the same PRD sentence.

**Orchestrator verification:** `workspace/` contains only INSTRUCTION.md, PRD.md, implementation/ — no stray test_helpers/ or test_suite/ landed there. 248 tests counted on disk; grep for `pytest.mark.skip`/`xfail` returns zero hits.

## Step 7: Iterate Tests + Fixes — 2026-09-04T11:05:00.000Z

Two iterations. Final state: **all 8 parallel rounds green, 254 / 254 passed, 0 failed, 0 errors, 0 skipped** (per-round `results.$i.json`, ~461 s each under 8-way contention). No test was deleted and `implementation/` was not touched.

### Iteration 1 — baseline sweep
8 concurrent rounds under `setsid nohup`, `--isolation per-test-server`, results in `workspace/implementation/results.{1..8}.json`. Every round reported the identical outcome: **230 / 254 passed, 24 failed, 0 errors**. The union of failures was exactly 24 and each one failed in all 8 rounds, so there was **zero flakiness** — every defect was deterministic. Diagnosis was taken only from the per-round JSON; `sweep.log` (8 rounds sharing one fd) was ignored as spliced.

The 24 split into three groups.

**Group A — 21 tests, `AttributeError: 'dict' object has no attribute 'status_code'` (test bug).**
Root cause: 22 call sites wrote `get_success_data(validate_success(response, expected_status=N))`. `prd_bench_local_runner.testing.validators.validate_success` already returns the parsed `data` payload, so the outer lenient `get_success_data` received a `dict` where it expected a `requests.Response`. Fixed by an AST-driven unwrap of the outer call at all 22 sites, keeping the inner `validate_success(..., expected_status=N)` — which is the *stricter* of the two helpers (exact status + full envelope shape), so no assertion was weakened. Two now-unused `get_success_data` imports were dropped.

**Group B — 2 tests, timestamp serialization (`test_04_cascades.py`).**
`assert after["suspended_at"] == "2026-08-10T14:20:00Z"` and the same shape for `accrual_started_at`; the platform returns `2026-08-10T14:20:00.000Z`. §2.4 pins "an ISO 8601 UTC timestamp with three fractional digits" for `created_at` and `updated_at` only; §3.7 says of these two fields merely that `suspended_at` "records the current logical instant" and that the obligation "has its `accrual_started_at` set to that instant", and §2.7 says only "time always ISO 8601 UTC". Two PRD-faithful implementations therefore exist — echo the caller's spelling, or normalise to the platform's canonical three-digit form — so the *spelling* is not uniquely derivable while the *instant* is. Handled as STEP 1c partial coverage: kept the covered assertion by comparing instants through a new local `_instant()` parser, dropped only the uncovered serialization claim. These were the only two literal-string timestamp assertions in the whole suite.

**Group C — 1 test, `assessment_mode` after the deration cascade (`test_04_cascades.py`).**
`test_shrunken_available_energy_derates_the_capacity_obligation` asserted `assessment_mode == "PRELIMINARY"` and `availability_pct == 100.00`. §3.9 link three enumerates exactly three effects — the move to `SHORTFALL`, recording `derated_committed_mw`, and having `penalty_exposure_usd` "recomputed under the `PRELIMINARY` variant" — and never names `assessment_mode` or `availability_pct`; those two fields are written by the assess operation of §3.8 ("`assessment_mode` records which variant was applied"). "Recompute `penalty_exposure_usd` under the PRELIMINARY variant" reads equally as *use the preliminary period for that one figure* or as *run a full preliminary assessment*, so the two fields are not uniquely determined. Dropped those two assertions per STEP 1c; kept `status`, `derated_committed_mw`, `shortfall_hours` and `penalty_exposure_usd`, all of which hold under either reading.

### Iteration 2 — verification
A targeted single round over the 8 touched files (`test_04`, `test_11`–`test_17`, symlinked into a scratch `_diag/` inside the task root so the runner's `sys.path` injection of `Path(test_dir).parent` still resolves `test_helpers`) returned **176 / 176 passed**. The full 8-round parallel sweep then returned **254 / 254 in all 8 rounds**. `_diag/` and every `/tmp` scratch file were removed; `__pycache__` trees were cleaned.

### Files changed
`test_suite/` only — `test_04_cascades.py`, `test_11_lifecycle_transitions.py`, `test_12_derived_calculations_and_ledger_visibility.py`, `test_13_business_rule_validations.py`, `test_14_endpoint_surface.py`, `test_15_state_conflict_errors.py`, `test_16_limit_and_reference_errors.py`, `test_17_role_authorization.py`.
`test_helpers/` unchanged (audited: `factories.py` emits money and energy as JSON numbers, `test_users.py` binds `SiteController` identity to the asset id, no fixture violated a PRD precondition). `workspace/implementation/` unchanged — no PRD-required check was relaxed, no endpoint, field or side effect was added, and storage remains in-memory dicts with no seeding. Zero `skip`/`xfail` markers in the tree. Test count is unchanged at 254 collected.

All servers were owned by the runner; the only process I stopped was one stale polling shell of my own, by recorded PID. No broad `pkill` was ever issued.

## Step 7 (addendum): subagent's returned summary, verbatim — 2026-09-04T11:20:00.000Z

Step 7 is complete: **all 8 parallel rounds green — 254 / 254 passed, 0 failed, 0 errors, 0 skipped.**

**Iterations run: 2**

- **Iteration 1** (baseline 8-round `setsid nohup` sweep): every round reported the identical `230 / 254 passed, 24 failed, 0 errors`. Union of failures = 24, each failing in all 8 rounds -> zero flakiness, all deterministic. Diagnosis taken only from `results.{1..8}.json`; `sweep.log` ignored as spliced.
- **Iteration 2** (after the fix batch): a targeted round over the 8 touched files returned 176/176, then the full 8-round parallel sweep returned **254 / 254 in all 8 rounds** (~461 s per round under 8-way contention). Per-round evidence is on disk at `workspace/implementation/results.{1..8}.json`.

**Tests deleted: none.** No test's asserted *rule* turned out to be uncovered in full; two tests carried partially-uncovered assertions, handled under STEP 1c:

- `test_04_cascades.py::TestTelemetryRunawayCascade::test_the_lockout_suspends_the_plant_from_the_market` and `::test_suspension_fails_live_instructions_and_opens_the_availability_accrual` — **DEFAULT/FORMAT SILENCE (partial)**. §2.4 pins "three fractional digits" for `created_at`/`updated_at` only; §3.7 says only that `suspended_at` "records the current logical instant" and the obligation "has its `accrual_started_at` set to that instant". Echoing the caller's spelling and normalising to the canonical `.000Z` form are both PRD-faithful, so the exact-string comparison was replaced by an instant comparison (new local `_instant()` parser); the covered "records the current logical instant" assertion is kept. Design instance: `Difficulty/transitive_cascade/telemetry_runaway_cascades_six_levels_...`.
- `test_04_cascades.py::TestCapacityTestCompletionCascade::test_shrunken_available_energy_derates_the_capacity_obligation` — **COMPUTED-FIELD SILENCE (partial)**. §3.9 link three enumerates exactly three effects and never names `assessment_mode` or `availability_pct`; those are written by the §3.8 assess operation ("`assessment_mode` records which variant was applied"). "Recomputed under the `PRELIMINARY` variant" reads equally as *that one figure* or *a full preliminary assessment*, so both assertions were dropped; `status`, `derated_committed_mw`, `shortfall_hours`, `penalty_exposure_usd` are kept (they hold under either reading). Design instance: `Difficulty/transitive_cascade/capacity_test_completion_cascades_four_levels_...`.

**Fixes applied to `test_helpers/`: none.** Audited end-to-end and found faithful — `factories.py` emits money/energy as JSON numbers (not the known string bug), `test_users.py` binds the `SiteController` identity to the asset id per §2.1, no fixture violates a PRD precondition.

**Fixes applied to `test_suite/`** (the real defect behind 21 of the 24 failures):

- `test_11_lifecycle_transitions.py`, `test_12_derived_calculations_and_ledger_visibility.py`, `test_13_business_rule_validations.py` (x4), `test_14_endpoint_surface.py` (x2), `test_15_state_conflict_errors.py`, `test_16_limit_and_reference_errors.py` (x10), `test_17_role_authorization.py` (x3) — 22 sites wrote `get_success_data(validate_success(response, expected_status=N))`, producing `AttributeError: 'dict' object has no attribute 'status_code'` because `validate_success` already returns the parsed `data` payload while `get_success_data` expects a `requests.Response`. Unwrapped the outer lenient call via an AST-driven rewrite, keeping the **stricter** inner `validate_success(..., expected_status=N)` (exact status + full envelope shape) — no assertion weakened, no skip/xfail added. Two orphaned `get_success_data` imports removed.

**Fixes applied to `implementation/`: none.** No PRD-required check was relaxed, no endpoint/field/side effect was added, storage is still in-memory dicts with no seeding.

Cleanup done: scratch `_diag/` and all `/tmp` scratch removed, `__pycache__` trees cleaned.

**Orchestrator verification:** independently read all 8 `results.$i.json` — every round `254 / 254`.

## Step 8: Finalize PRD — 2026-09-04T11:30:00.000Z

`PRD_FINALIZED.md` is written. Three edits, all traceable to the two STEP-1c partial-coverage items in the Step 7 diff; the 22 `get_success_data` sites got no PRD edit (pure harness API misuse, no PRD dimension), and `test_helpers/`/`implementation/` had no fixes, so nothing else was touched.

## Size
- PRD.md: 508 lines / 104,042 bytes
- PRD_FINALIZED.md: 508 lines / 104,825 bytes
- Line delta: 0 (+0.0%); byte delta: +783 (+0.75%). Three lines revised in place, no lines/sections added.

## Changes
- **§3.7 link two — revise** — `suspended_at` is pinned to the server's canonical ISO 8601 UTC form with three fractional digits (clock at `2026-08-10T14:20:00Z` -> `2026-08-10T14:20:00.000Z`), not the caller's spelling — `services/core.py:444` via `db.py:66-71`.
- **§3.7 link six — revise** — `accrual_started_at` is written in the same three-fractional-digit form as `suspended_at` — `services/core.py:486` via `db.py:66-71`.
- **§3.9 link three — revise** — the deration cascade recomputes and writes **only** `penalty_exposure_usd` (preliminary arithmetic over the stored `unavailable_hours` and the period from the start of `program_year` to the logical now), leaving `assessment_mode`, `availability_pct`, `measured_available_hours` and `shortfall_hours` at whatever values they already carried — `services/core.py:522-542` (`rederate_obligations` / `preliminary_penalty`), `services/calc.py:210-255`.

## Per-edit pre-edit search log

**Edit 1 — `suspended_at` timestamp format**
- (a) Subject: how the platform renders a logical-clock instant it stamps onto a row, specifically `suspended_at`.
- (b) Enumerated/read: `grep -rn "fmt_dt\|clock_now()"` across `implementation/` — the only two `fmt_dt(now)` row writes are `services/core.py:444` (`suspended_at`) and `:486` (`accrual_started_at`); `db.py:66-71` (`fmt_dt` = `%03dZ`, exactly three digits); `db.py:126,137` (`created_at`/`updated_at` use the same helper, wall clock); `routes/assets.py:83` (registration -> null), `:128` (commission -> null), `:135-139` (clock endpoint parses `current_utc`, stores no string, returns `{}`); `services/core.py:496-508` (`safety_resume_recompute` -> `suspended_at = None`, and the already-`SUSPENDED` `ALARM -> LOCKOUT` branch at `:446-449` deliberately does **not** re-stamp); `validators.py:129-141` (`v.timestamp` returns `(raw, parsed)`); `grep -n "_raw"` confirming every caller-supplied timestamp (`commercial_operation_date`, `window_start/end`, `delivery_start/end`, `setpoint_start/end`, `sampled_at`, `scheduled_date`, `remedy_install_date`, `emergency_response_ack_at`) is stored **verbatim**.
- (c) Adjustment: scoped the claim to this server-stamped field only ("written by the server") and dropped any general statement about timestamp handling, so the verbatim-echo paths for the ten caller-supplied timestamp fields are not mis-described. Left sub-millisecond rendering unstated (impl truncates `microsecond // 1000`) rather than making a precision claim the Step 7 site does not exercise.

**Edit 2 — `accrual_started_at` timestamp format**
- (a) Subject: the format of the accrual open-stamp, and everything that reads it back.
- (b) Enumerated/read: `services/core.py:480-487` (link six write), `:510-518` (`safety_resume_recompute` parses it with `db.parse_dt` and nulls it), `routes/obligations.py:61` (created null), `:100-111` (`unavailability` touches only `unavailable_hours`), `:114-150` (`assess` never writes it), `db.parse_dt` (`db.py:74-89`, accepts both `Z` and offset spellings, so the round-trip through the canonical form is lossless).
- (c) Adjustment: expressed as "the same three-fractional-digit form as `suspended_at`" rather than restating the example, keeping one authority for the format and avoiding a second, independently-driftable spelling rule.

**Edit 3 — which obligation fields the deration cascade writes**
- (a) Subject: the field-write set of the capacity-test-completion deration cascade, and every other writer of the same obligation fields.
- (b) Enumerated/read: `services/core.py:522-533` (`rederate_obligations` — writes `status`, `derated_committed_mw`, `penalty_exposure_usd`, then `db.touch`; candidates `ACTIVE`/`SHORTFALL` only, ordered `by_program_year`); `:536-551` (`preliminary_penalty` / `preliminary_period_hours` — logical now, year start of `program_year`, negative clamped to 0, returns only the penalty and discards the computed status/`availability_pct`); `services/calc.py:198-255` (`derated_committed`, `assess_obligation` — the tier multiplier comes from the freshly computed `availability_pct`, not the stored one); `routes/captests.py:174-182` (link three's position in the chain, `recompute_free` last); `routes/obligations.py:51-71` (creation defaults: `availability_pct` null, `assessment_mode` null, `measured_available_hours`/`shortfall_hours` 0.0), `:100-111` (unavailability — `unavailable_hours` only), `:114-150` (assess — the only writer of all six figures plus `status`, with the `PENALIZED`/`FULFILLED` status latches); `services/core.py:480-487` and `:510-518` (the safety cascade's obligation writes: `accrual_started_at` and `unavailable_hours` only).
- (c) Adjustment: wrote "at whatever values they already carried" instead of "the values the last assessment left them with" (§3.8's phrasing for the unavailability operation), because an obligation reached by this cascade may never have been assessed — in the impl it then still holds its creation defaults (`availability_pct`/`assessment_mode` null). Also said the cascade "evaluates the preliminary arithmetic of §3.8" rather than "runs a preliminary assessment", so the wording cannot be read as invoking the assess operation's status ladder or its `PENALIZED`/`FULFILLED` latches, which this path bypasses (it forces `SHORTFALL`).

**Orchestrator verification:** PRD_FINALIZED.md is 508 lines, +783 bytes over PRD.md, 6 changed diff lines (3 revised in place), tail intact at the §5 table's last row — not truncated, not byte-identical.

## Step 9: Complete PRD — 2026-09-04T12:05:00.000Z

**Orchestrator note on method.** Step 9 was run as **three sequential, module-partitioned passes** over one shared `workspace/PRD_COMPLETED.md`, rather than as a single subagent. Rationale (written here per the AUTONOMY directive, since no one could be consulted): the implementation is 3315 lines across 21 modules, and a single scan agent cannot hold it plus the 508-line PRD in context without degrading into a shallow skim — the known failure mode being a `PRD_COMPLETED.md` byte-identical to its input, which is proof the scan never ran. Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from copying and edited in place. Each pass was told which modules the other passes owned, was allowed to *read* outside its partition to keep shared-helper wording consistent, and handed forward an explicit list of deferrals.

### Partition
- **Pass 1 — cross-cutting infrastructure:** `app.py`, `db.py`, `errors.py`, `numeric.py`, `response.py`, `middleware.py`, `validators.py`, `start.sh`. Subject: response envelope + meta, `response_type`, pagination semantics/defaults/bounds, ordering, error envelope + status map, auth/role screening, ownership middleware, the shared shape-validation ladder, numeric precision/rounding, timestamp parse/render helpers, the logical clock, unknown route/method handling.
- **Pass 2 — calculation core + asset/trading routes:** `services/calc.py`, `services/core.py`, `routes/assets.py`, `routes/reservations.py`, `routes/bids.py`. Subject: all 7 calculations and their operand sets/rounding/clamping, the SoC/reserved/free ledger and its invariants, asset lifecycle + version counter + OCC guard, reservations, bid construction/degradation pricing/submission/clearing/revision/withdrawal, and the cascades originating there.
- **Pass 3 — remaining six route modules:** `routes/dispatches.py`, `telemetry.py`, `safety.py`, `obligations.py`, `captests.py`, `claims.py`. Subject: dispatch issuance→acceptance→execution→completion/failure with ledger + scoring side effects and ordering, telemetry ingestion + derived fields + runaway trigger, safety reporting/suppression/closure + SoD gate, obligation enrolment/unavailability/PRELIMINARY-FINAL assess, capacity test schedule/start/complete + cascade, warranty claim draft/submit/adjudicate/deny/install + filing window, plus the §4/§5 rows for those modules.

### Aggregate result
| file | lines | chars |
|---|---|---|
| PRD.md | 508 | 104,042 |
| PRD_FINALIZED.md | 508 | 104,825 |
| **PRD_COMPLETED.md** | **509** | **122,661** |

Char-delta vs `PRD_FINALIZED.md`: **+17,836 (+17.0%)**; 123 changed diff lines; +1 line only (essentially all edits are in-paragraph inserts/revisions, no new sections — §-count still 5). Document ends at the last row of the §5 error table (`| ERR_CLAIM_FILING_WINDOW_EXPIRED | 422 |`) — not truncated, and NOT byte-identical to its input.

**Total: 65 edits — 51 ambiguity-pins, 20 mismatch-revisions** (pass 1: 12 pins / 0 mismatches; pass 2: 15 pins / 11 mismatches; pass 3: 24 pins / 9 mismatches).

### Pass 1 changes (12 ambiguity-pins, 0 mismatch-revisions)
- §2.1 — insert — ambiguity — whitespace-only header counts as empty for `ERR_UNAUTHENTICATED`; routing rejections precede authentication — `middleware.py:21-26`, `app.py:36-43`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 random `A-Z0-9`, minted per response — `response.py:14-18`
- §2.2 — insert — ambiguity — `api_request_timestamp` comes from the host wall clock, not the logical clock — `response.py:21-28`
- §2.2 — insert — ambiguity — unknown path -> `ERR_INVALID_REQUEST` 404, unsupported method -> `ERR_INVALID_REQUEST` 405, both router-decided before auth/body screening, trailing slash ignored; unexpected failure -> `ERR_INTERNAL` 500 — `app.py:22,36-53`
- §2.3 — insert — ambiguity — `?limit=` empty counts as omitted; whitespace/leading `+` tolerated; `10.0` rejected; `offset` unbounded above; undeclared query params ignored; shape check precedes path-`{id}` existence — `validators.py:174-192`
- §2.3 — insert — ambiguity — `has_more` is exactly `offset + len(rows) < total_count`; offset past end yields empty `data`, false `has_more`, full `total_count` — `response.py:49`
- §2.3 — insert — ambiguity — millisecond `created_at` ties settled by server insertion sequence — `db.py:27-31,147-152`
- §2.4 — insert — ambiguity — `id` is a random v4 UUID, canonical lower-case hyphenated; `created_at`/`updated_at` are wall-clock, not logical-clock — `db.py:108-109,123-139`
- §2.6 step 3 — insert — ambiguity — JSON `null` counts as absent; undeclared fields ignored; missing/non-object body is `ERR_INVALID_REQUEST`; numeric fields must be JSON numbers and integer fields JSON integers (not whole floats); blankness judged trimmed but stored untrimmed, length ceiling measured untrimmed — `validators.py:19-92`
- §2.7 — insert — ambiguity — accepted ISO 8601 spellings (`Z`/`z`, numeric offset, naive-as-UTC); client instants echoed verbatim, server-written instants canonical `...sssZ` — `db.py:66-89`
- §2.7 — insert — ambiguity — rounding uses exact decimal arithmetic over the textual form but emits JSON numbers, so trailing zeros are lost (12.50 -> `12.5`) — `numeric.py:20-41`
- §2.8 — insert — ambiguity — the clock is one process-wide instant, settable backwards, normalises `current_utc` to UTC, holds until next set, governs business rules only — `db.py:33-36,54-60`

### Pass 2 changes (15 ambiguity-pins, 11 mismatch-revisions)
Mismatch-revisions:
- §3.1 — revise — mismatch — `soh_pct` is not "the `measured_soh_pct` of the test with the greatest `scheduled_date`"; `core.soh_from_tests` is dead code and `soh_pct` is simply overwritten by each completion — `core.py:126` / `captests.py:172`
- §3.2 — revise — mismatch — "a failed capacity request leaves the pool exactly as it found it" was false: the step-one expiry sweep is not unwound, and pool figures move without an asset `version` bump — `core.py:379-426`
- §3.3 — revise — mismatch — offer-price operand list wrongly named `available_energy_mwh`, `offer_mw` and the delivery interval (none reach the price) and omitted `cycle_limit_per_year` and `warranty_throughput_limit_mwh` — `calc.py:59-87`
- §3.3 — revise — mismatch — power bounds are checked at drafting and **revision**, not "again when a draft is re-priced"; `reprice_draft_bids` and submission never re-test — `bids.py:284` / `core.py:307`
- §3.4 — revise — mismatch — window exclusivity is not "the last submission gate"; it is evaluated ahead of the cycle/throughput budgets — `bids.py:179-211`
- §3.4 — revise — mismatch — `cleared_mw > offer_mw` is not a §2.6 step-3 check; it runs after path resolution and before the status check — `bids.py:235-239`
- §3.4 — revise — mismatch (ordering) — offered-power bound precedes the revision-allowance check — `bids.py:284-288`
- §3.6 — revise — mismatch — `error_ratio`'s numerator is the already-3-decimal `deviation_mw`, not the raw absolute difference — `calc.py:115-126`
- §3.8 — revise — mismatch — `FINAL` + no shortfall + non-null `derated_committed_mw` yields **FULFILLED**, not SHORTFALL — `calc.py:236-245`
- §4 — revise — mismatch — commission row claimed it "seeds state-of-health and derived energy fields"; it recomputes nothing — `assets.py:114-130`
- §4 — revise — mismatch — `/market-bids` omitted the `market_type` filter; `/soc-reservations` said "product" for `purpose` — `bids.py:127-135`, `reservations.py:73-79`

Ambiguity-pins:
- §2.3 — insert — enum-validated vs opaque-identifier vs integer filters; `limit`/`offset` screened before filters, filters in listed order — `assets.py:100-102` *(pass-1 deferral)*
- §2.5 — insert — `expected_asset_version` must be a non-negative JSON integer; `3.0`/`-1` is `ERR_INVALID_REQUEST`, not 412 — `validators.py:62`, `reservations.py:30`
- §2.8 — insert — clock-set returns HTTP 200 with `data` an empty object — `assets.py:139` *(pass-1 deferral)*
- §3.1 — insert — registration evaluates rated -> available -> efc -> free in that order; `equivalent_full_cycles_ytd` reflects `initial_cumulative_throughput_mwh` immediately — `core.py:205-210`
- §3.1 — insert — `equivalent_full_cycles_ytd` is 0.0 (no division) when `available_energy_mwh` is 0 — `core.py:151-157`
- §3.2 — insert — `window_end > window_start` is a step-3 shape check ahead of existence; the reservation persists `expected_asset_version` as its own field — `reservations.py:31,53`
- §3.3 — insert — `delivery_end > delivery_start` and the quarter-hour checks are step-3 shape checks in that order; whole quarter-hour = minute multiple of 15, zero seconds, zero fractional seconds — `bids.py:31-34,77-81`
- §3.3 — insert — `cycle_debit_efc` reads the rounded `expected_energy_mwh` and is 0.0 when `available_energy_mwh` is 0 — `calc.py:100-104`
- §3.3 — insert — direction-combined base and weighted floor each rounded to 4 decimals; the charge-side clamp at 0 precedes the weighting — `calc.py:76-82`
- §3.3 — insert — the four operations that re-price DRAFT offers (capacity-test completion, dispatch completion, dispatch compensation, augmentation installation), the three fields rewritten, the `delivery_start` order, the per-draft `version` bump — `core.py:307-319`
- §3.4 — insert — withdrawal when the reservation is no longer `HELD`: nothing released, no pool recompute, asset `version` unmoved — `bids.py:328-345`
- §3.7 — insert — an `OFFLINE` asset is never suspended by the cascade; links three to six do not run, `suspension_reason`/`suspended_at` stay null, but the event still bumps the asset `version` — `core.py:441-452`
- §3.8 — insert — the PRELIMINARY period is clamped at 0.0 hours when the clock precedes 1 January of `program_year` — `core.py:545-551`
- §3.8 — insert — `measured_available_hours` is not floored at 0; a 0.0-hour period yields `availability_pct` exactly 0.00 without dividing — `calc.py:214-218`
- §3.9 — insert — an obligation link three visits but does not find derated is left wholly untouched, so a stale `derated_committed_mw` survives a recovery — `core.py:522-533`

### Pass 3 changes (24 ambiguity-pins, 9 mismatch-revisions)
- §3.2 — revise — mismatch — reservation consumption by a completed delivery imposes no precondition beyond `HELD`: asset scope is not re-tested and delivered energy is never compared against `reserved_mwh`, so `consumed_mwh` may exceed it — `dispatches.py:226-246`
- §3.5 — revise — ambiguity — `setpoint_end > setpoint_start` is an intra-body shape check (step 3), so it precedes existence resolution and reports `ERR_INVALID_REQUEST` — `dispatches.py:33-36`
- §3.5 — revise — ambiguity — acceptance examines the execution axis before the parent offer's status: `ERR_DISPATCH_NOT_PENDING` outranks `ERR_BID_NOT_CLEARED` — `dispatches.py:142-145`
- §3.5 — revise — ambiguity — an `ALARM` posture is refused at execution with the same identifier as a lockout, `ERR_ASSET_SAFETY_LOCKOUT` (409) — `dispatches.py:172`
- §3.5 — revise — ambiguity — the execution energy check uses this instruction's own energy alone, no sibling instructions summed as at creation — `dispatches.py:177-179`
- §3.5 — revise — ambiguity — `ERR_DISPATCH_NOT_ACCEPTED` precedes the reservation `HELD` check — `dispatches.py:167-170`
- §3.5 — revise — ambiguity — `sample_index >= 1` is a shape constraint (`ERR_INVALID_REQUEST`) while its strict monotonicity is the step-24 ordering rule (`ERR_TELEMETRY_OUT_OF_ORDER` 409) — `telemetry.py:23,65-67`
- §3.5 — revise — ambiguity — index monotonicity failure shares `ERR_TELEMETRY_OUT_OF_ORDER`; the three ordering comparisons run in a fixed sequence (vs `setpoint_start`, vs newest sample, vs max index), only the first applying to a first sample — `telemetry.py:57-68`
- §3.5 — revise — ambiguity — auto-created thermal events copy `detected_max_cell_temp_c` from the sample's `max_cell_temp_c`; remaining fields take the manual-report initial values — `telemetry.py:95-105`
- §3.6 — revise — ambiguity — `failure_reason` body is optional entirely; the field is a 1..120-char non-blank string — `dispatches.py:254`
- §3.6 — revise — mismatch — a supplied `failure_reason` is honoured only on the no-delivery branch (default `OPERATOR_FAILURE`); the compensation branch overwrites it with `DELIVERY_VOIDED` regardless — `dispatches.py:271,301`
- §3.6 — revise — ambiguity — the `EXECUTING -> FAILED` branch moves no ledger (`soc_mwh`, `cumulative_throughput_mwh`, `equivalent_full_cycles_ytd` untouched, no `DRAFT` offer re-priced) but still recomputes the pool and bumps the asset `version` — `dispatches.py:265-280`
- §3.7 — revise — mismatch — corrected the lockout-gate enumeration to the actual 13 guarded operations (adds `SUBMITTED`-offer withdrawal, dispatch completion, capacity-test start and completion, augmentation installation) and stated the negative set that stays open on a locked-out plant — `gate_lockout` call sites across `reservations.py:40`, `bids.py:91,166,280,312`, `dispatches.py:47,147,214`, `captests.py:55,125,149`, `claims.py:185`
- §3.7 — revise — ambiguity — `suppression_agent_kg` is required and must be `>= 0` — `safety.py:70`
- §3.7 — insert — ambiguity — discharging suppression does not write the asset row at all: neither `updated_at` nor `version` moves — `safety.py:66-81`
- §3.7 — revise — ambiguity — closure stores only the coordination fields the body supplied; an omitted one keeps its existing null / empty-array / false value — `safety.py:126-131`
- §3.7 — revise — ambiguity — the asset's `version` increases on every successful closure, whichever of the five landings the recompute reaches and even when both axes are unchanged — `safety.py:134-137`
- §3.8 — revise — ambiguity — the duplicate-enrolment comparison on `program_name` is exact, case-sensitive and untrimmed — `obligations.py:44-49`
- §3.8 — revise — ambiguity — `unavailable_hours_delta` is required and must be `>= 0` — `obligations.py:104`
- §3.8 — revise — ambiguity — `reason` is a 1..500-char non-blank string that is shape-screened but persisted nowhere — `obligations.py:105`
- §3.8 — insert — ambiguity — every assessment rewrites `derated_committed_mw` from the asset's current `available_energy_mwh` under both variants, including writing it back to null — `obligations.py:129-147`
- §3.9 — revise — mismatch — the filing window is an inclusive upper bound at `scheduled_date + 30 days` (30 elapsed days passes, 31 fails), not "within 30 days of" — `claims.py:23-25,52`
- §3.9 — insert — ambiguity — the window has no lower edge: a claim drafted before the cited test's `scheduled_date` is in window — `claims.py:52`
- §3.9 — revise — ambiguity — `remedy_outage_days` is a JSON integer `>= 1` — `claims.py:131`
- §3.9 — revise — ambiguity — `remedy_energy_add_mwh` is sized at adjudication time from pre-remedy rated energy (nameplate plus currently-`REMEDIED` claims), not from the rated energy at test completion — `claims.py:157-160`
- §3.9 — revise — ambiguity — an install attempt before `remedy_install_date` reuses `ERR_CLAIM_NOT_APPROVED` (409), tested after the status guard and before the lockout gate — `claims.py:178-185`
- §4 — revise — mismatch — dispatch-instruction list filters are asset, offer, execution status and scoring status — `dispatches.py:110-130`
- §4 — revise — mismatch — telemetry append targets an executing **or completed** instruction's stream — `telemetry.py:34`
- §4 — revise — mismatch — safety-event list filters are asset, originating dispatch instruction, status and severity (no "category" filter exists) — `safety.py:47-50`
- §4 — revise — mismatch — capacity-test list filters are asset, baseline test and status — `captests.py:94-96`
- §4 — revise — mismatch — warranty-claim list filters are asset, cited capacity test and status (no `claim_type` filter exists) — `claims.py:85-87`

### Deferrals resolved and items consciously left
- `obligations.py:85` (`program_year` via `query_int` with no bounds) — left unpinned: the effective floor is an unreachable sentinel, so documenting it would state non-observable behavior; §2.3's shared `query_int` contract already covers what is observable.
- `obligations.py:135-141` — resolved: pass 2 pinned the `PENALIZED`/`FULFILLED` absorbing states; pass 3 added the unconditional `derated_committed_mw` write-back including null.
- `dispatches.py:190-201, 226-246, 286-311` — resolved: pass 2 pinned the completion ledger order and the settled/provisional sample split; pass 3 added the previously silent `EXECUTING`-fail branch.
- **SiteController ownership gate / §2.6 step 7** — verified, no edit needed: `check_asset_ownership` has exactly six call sites (dispatch execute/complete/fail, telemetry append, capacity-test start/complete), matching §2.6 step 7 and §2.1 exactly.
- **§5 error table** — verified against every identifier the route modules raise, including HTTP status; no change required.
- Four candidates skipped as already uniquely determined by global sections: non-negativity on `max_cell_temp_c`/`detected_max_cell_temp_c` (§2.6 step 3), the instruction's `version` advancing on telemetry append (§2.4), `recompute_rated` in capacity-test cascade link two (value cannot change), and the position of draft re-pricing inside the completion and install cascades (no observable ordering dependency). One clause was drafted then removed as unreachable — an instruction accepted before a suspension can never be executed after the posture falls back, because suspension cascade link five already FAILS every live instruction.

### Orchestrator final verification
- `PRD_COMPLETED.md` is **509 lines / 122,661 chars**, differs from `PRD_FINALIZED.md` (123 changed diff lines) — the scan demonstrably ran.
- Tail is the last row of the §5 error table; all 5 top-level sections present; no truncation.
- All 8 `workspace/implementation/results.$i.json` re-read: **254 / 254 passed, 0 failed** in every round.
- Task tree clean: exactly one `worklog.md` (at the task root, no drift into `workspace/`); no `__pycache__`, no `*.bak`, no `_diag/`; `test_helpers/` and `test_suite/` at the task root, not under `workspace/`.

**PIPELINE COMPLETE.**
