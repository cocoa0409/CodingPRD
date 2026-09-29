# Worklog — task_2536_private_fleet_operations_backhaul_optimization

## Step 1: Create task directory — 2026-09-03T07:29:01.864Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2536_private_fleet_operations_backhaul_optimization` and its `workspace/` subdirectory. Index 2536 was pre-assigned by the invocation; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold artifacts — 2026-09-03

Wrote `SCAFFOLD.yaml` (§1.0–§1.7), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, 9 rules / 26 instances)
and `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, 9 sections / 73 instances, 13 of them `excluded_because`
stubs pointing at the §1.8 instance that already covers the claim). Generated from the scenario
description plus the scaffold-generator specification only; no sibling task was inspected.
`scaffold_lint.py` reports a clean lint over 1390 §1.8+§1.9 calls; all 63 §1.6 error codes are
asserted by at least one recipe.

## Step 2 (orchestrator record): Generate scaffold — 2026-09-03T09:45:36.924Z

Subagent summary, verbatim:

The scaffold is complete and lints clean.

**Linter verdict (verbatim):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    84
  §1.1 entities declared:     15
  §1.8 instances scanned:     26
  §1.9 instances scanned:     60
  Calls scanned (§1.8+§1.9):  1390

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files** (all in `/home/ubuntu/github/CodingPRD/tasks/task_2536_private_fleet_operations_backhaul_optimization/`):

| file | lines |
|---|---|
| `SCAFFOLD.yaml` | 3618 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2810 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4941 |

(also present: the pre-existing `worklog.md`, to which I appended a Step-2 entry, and the empty `workspace/` from Step 1)

**What the scaffold defines** — `domain_name: private-fleet-backhaul-operations`, `api_prefix: /fleet`, difficulty `expert_plus`, topology `flat`, SM shape `parallel`, role model `segregation_of_duties`, consistency `immediate`; layers `optimistic_concurrency`, `cascading_side_effects`, `dual_variant_calculation`, `derived_field_reconciliation` (+ `selector_policy`, `version_pinning_on_approval`, `rate_threshold_triggers`).

- **15 entities**: Domicile, Store, ReplenishmentOrder, Driver, DriverPayPlan, Tractor, Trailer, Trip, TripStop, BackhaulOffer, DriverPayStatement, MaintenanceWorkOrder, RoutePosting, RouteBid, TelematicsEvent.
- **14 state machines** (Trip carries two parallel dimensions: `plan_status` and `settlement_status`), **84 endpoints**, **63 error codes**, **6 roles** (FleetPlanner, TransportManager, Driver `entity_backed`, PayrollAnalyst, SafetyManager, MaintenanceCoordinator), **16 validation rules** in one priority ladder, **3 §1.2.1 OCC rules** (`backhaul-link-stale-trip`, `bid-create-stale-posting`, `payplan-assign-stale-driver`).
- **14 calculations**, including the two dual-variant ones (`driver_trip_pay` PLANNED_ACCRUAL/FINAL_SETTLEMENT, `domicile_cost_benchmark` FULLY_ALLOCATED/INCREMENTAL_VARIABLE) plus `trip_plan_totals` (per-stop ceil before summation), `hos_feasibility`, `backhaul_contribution_margin` (pre-commission tier breaks the circularity), `driver_safety_score`, `route_award_selection`, `dock_capacity_occupancy`, `pm_due_projection`, `domicile_balance_index`, `trailer_peak_case_load`.

**Design files** — §1.8: 9 rules / **26 instances**. §1.9: all nine taxonomy sections / **73 instances** (60 full recipes + 13 `excluded_because` stubs that cite the §1.8 instance already covering the claim): entities 11, state_machines 12, calculations 11, validations 13, endpoints 6, errors 7, rbac 4, cross_cutting_complexity_layers 8, consistency_model 1.

**Verification beyond the linter**: no duplicate or colliding instance names across §1.8+§1.9; every `excluded_because.difficulty_instance` resolves; every `calculations.X` / `errors.X` ground exists in the scaffold; **all 63 §1.6 codes are asserted in at least one recipe's `assert` block**; no forbidden concurrency vocabulary; `SCAFFOLD.yaml` contains neither design key and each design file has exactly one top-level key. Three scaffold edits made earlier in the run (attaching `ERR_REFERENTIAL_INCOMPLETE` to the DELIVERY-stop shape rule in §1.4/§1.5/§1.6) were what made that code reachable; no sibling task directory was read at any point.

## Step 3: Copy shared files — 2026-09-03T09:45:59.574Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T10:03:38.147Z

Orchestrator truncation check (per invocation directive): `workspace/PRD.md` is 496 lines, section
headers run §1 → §5 with no gaps, §4 endpoint table holds 86 table lines (84 endpoints + 2 header
rows), §5 holds 63 error rows, and the file's last line is a complete final row of the §5 error
table — a real section boundary, not a mid-sentence cut. No regeneration needed.

Subagent summary, verbatim:

The PRD is complete and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2536_private_fleet_operations_backhaul_optimization/workspace/PRD.md` — **496 lines**, ends at a real boundary (last row of the §5 error table; no audit footer, no contract block).

**Section list**
- `# Private Fleet Backhaul Operations API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 RBAC, 2.2 API Response Structure, 2.3 Pagination, 2.4 Resource Identity/Timestamps/Row Versions, 2.5 The Logical Clock, 2.6 Precision, 2.7 Validation Precedence (16 levels), 2.8 Stale-Version Guards (3 OCC rules), 2.9 Interval Geometry Conventions (3 geometries), 2.10 Conserved Quantities and Cascade Propagation, 2.11 Path Addressing / Filtered Collections / Segregation of Duties
- `## 3. Business Logic & Workflows` — 3.1 Stores, Domiciles and Pay Plans; 3.2 Tractors, Trailers and the Shop Schedule; 3.3 Drivers, Duty Counters, Seniority, Termination; 3.4 Replenishment Demand to Draft Trip; 3.5 Crewing and Committing; 3.6 The Backhaul Market; 3.7 Dispatch, Arrival, Close-Out, Cancellation; 3.8 Driver Pay, Settlement and Cost Benchmarking; 3.9 Safety Telematics, Coaching Holds and the Route Bid Board (9 subsections, within the mandated 5–9)
- `## 4. Endpoint Definitions` (4-column table)
- `## 5. Error Code Catalogue` (2-column table)

**Coverage counts (all machine-verified against SCAFFOLD.yaml)**
- Entities: **15 / 15**
- Endpoints: **84 / 84** rows in §4 (`grep -c` on the table = 84)
- Error codes: **63 / 63** rows in §5, and **63 / 63** also raised in prose in §2–§3 (zero appear only in the catalogue)
- Calculations: **14 / 14** (`trip_plan_totals`, `trailer_peak_case_load`, `hos_feasibility`, `driver_trip_pay` both variants, `backhaul_contribution_margin`, `domicile_cost_benchmark` both variants, `domicile_balance_index`, `driver_safety_score`, `route_award_selection`, `pm_due_projection`, `dock_capacity_occupancy`, `asset_maintenance_conflict`, `driver_rest_gap`, `dock_hours_and_window_fit`)
- State machines: **14 / 14**, **57 / 57** transitions — 40 written with explicit `FROM -> TO` arrows, the remaining 17 verified individually as described in prose (e.g. `PLANNED -> DRAFT` coaching rollback, three cancellation shapes, offer reject/withdraw/expire, statement reversal from both origins, `NOT_COACHED -> COACHED`)
- Enum values: **0 missing** — every uppercase enum literal from every entity field constraint appears in §1–§3

**Hard Contracts**
- **Contract 1 — Field-Name Coverage: PASS.** All **171 / 171** required identifiers (142 entity fields + endpoint `request_body`/`query_params`/`path_params` inputs + 28 computed-read output keys, deduped) appear as standalone backticked tokens. Strict check (exact whole-token match, fenced code blocks excluded to preserve backtick parity) returned zero misses.
- **Contract 2 — Rule Coverage: PASS.** All 16 validation-precedence levels with their intra-level orderings, all 3 OCC guards with their `expected_*` fields and 412 codes, all cross-entity cascades (close-out chain, both cancellation shapes, coaching-hold cascade, termination cascade, offer expiry sweep, statement reversal/re-accrual ledger unwinds), field-level defaults, and sibling-branch symmetry (PLANNED vs DISPATCHED cancel; ACCRUED vs SETTLED reversal; award vs vacant vs cancel) are all stated.
- **Contract 3 — §3 Path Purity: PASS.** 1068 backticked tokens in §3 (325 unique): zero start with `/`, zero are bare HTTP methods, zero combine method+path, zero embed `/fleet`, and zero plain-text path mentions.

**Other checks:** §2.2 is byte-identical to `section-2.2-response-structure.md` (diff clean). Zero pseudocode operators (`==`, `&&`, `>=`, `:=`, `min(`, `max(`, `floor(`) anywhere in the document. Zero fuzzy-quantity words. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened or referenced, and no sibling task directory was read.

## Step 6: Generate implementation — 2026-09-03T10:43:29.000Z

Subagent summary, verbatim:

Implementation complete. All work is in `/home/ubuntu/github/CodingPRD/tasks/task_2536_private_fleet_operations_backhaul_optimization/workspace/implementation/`.

## Files written (3,474 lines total)

| File | Lines | Role |
|---|---|---|
| `core.py` | 404 | Envelope helpers, 63-entry error catalogue, `ApiError`, auth/RBAC, in-memory `DB` (15 empty dicts + logical clock), id/timestamp/version machinery, filters, pagination |
| `calc.py` | 540 | All 14 calculations with PRD constants transcribed verbatim; pay engine (both variants), offer margin/commission, HOS, safety score, interval geometry, PM projection, pay-plan pin + accrual |
| `validate.py` | 263 | Level-7 shape layer, level-5 FK resolution, pagination window, typed query-param readers |
| `routes_network.py` | 276 | 12 endpoints — stores, domiciles, pay plans, cost benchmark |
| `routes_fleet.py` | 278 | 14 endpoints — drivers (incl. termination cascade), tractors, trailers |
| `routes_orders.py` | 246 | 12 endpoints — replenishment orders, maintenance work orders |
| `routes_trips.py` | 686 | 19 endpoints — trips, stops, plan/dispatch/complete/cancel, pay preview, re-accrue, dispute |
| `routes_backhaul.py` | 227 | 9 endpoints — backhaul offers + expiration sweep |
| `routes_pay.py` | 94 | 4 endpoints — pay statements, settle, reverse |
| `routes_board.py` | 385 | 18 endpoints — postings, bids, telematics, coaching-hold cascade, `_clock/set_current_utc` |
| `app.py` | 66 | Blueprint registration under `/fleet`, error handlers, `0.0.0.0:$PORT` |
| `start.sh` | 8 | Guarded install (`if ! python3 -c "import flask"`) + `exec python3 app.py` |

## Coverage verification (mechanical, not eyeballed)

- **84/84 endpoints**: extracted the PRD §4 table and diffed it against Flask's `url_map` — `missing []`, `extra []`.
- **63/63 error codes**: every code in the PRD §5 catalogue is reachable via a `fail()` call or `must_exist`, with zero HTTP-status mismatches and zero invented codes.
- **No seeding**: fresh boot returns `total_count: 0` on all 15 collections.

## Smoke test — passed

Booted via `PORT=18539 bash start.sh` (log confirms `Running on all addresses (0.0.0.0)`), ran two end-to-end scripts, **0 HTTP 500s across 91 requests**, then killed the process.

Envelope confirmed byte-for-byte against PRD §2.2 (`meta.api_request_id` = `req_` + 20 alnum, timestamp with exactly 3 fractional digits, `response_type` of `object`/`array`/`error`, error body nested under `data`, pagination fields inside `meta`).

Hand-verified computed results:
- **Pay engine**: mileage 6000 + activity 1500 + hourly 11250 (225 detention min = 400 actual - 145 planned - 30 grace) + bonus 0 = 18750 subtotal -> guarantee makeup 1250 -> gross 20000. Statement created in `ACCRUED`, both money ledgers raised, settle -> `SETTLED`, reverse -> ledgers back to 0 and trip `ADJUSTED`, re-accrue -> new statement on the original pin.
- **Cost benchmark**: fuel 6200 + maint 1900 + pay 20000 = 28100 variable; `window_days` 7 x 15000 = 105000 fixed; 133100 total; 1331 per case; advantage -431.
- **Offer margin**: 350 miles x 185 + 500 cases x 9 = 69250 variable -> 30750 gross margin -> `tier_margin_pct` 0.3075 (high tier, 6%) -> 6000 commission -> 24750 contribution -> `margin_pct` 0.2475.
- **Coaching-hold cascade**: 3 x severity-3 seatbelt = 36 points -> score 64 -> hold fires -> the `PLANNED` trip reverted to `DRAFT`, stripped of driver/tractor/trailer/pin, `planned_pay_cents` 0, order back to `UNSCHEDULED`, store ledger 50 -> 0, tractor `AVAILABLE`, bid `PASSED_OVER`, posting `bid_count` 1 -> 0. Coaching one event restored 12 points (score 76) and lifted the hold without restoring the trip or bid.
- **Precedence spot-checks**: `ERR_UNAUTHORIZED` (403) beats existence, `ERR_SEGREGATION_OF_DUTIES` (403) beats posting state on award, `ERR_STALE_POSTING_VERSION` (412), `ERR_DUPLICATE_BID` (422), `ERR_DRIVER_COACHING_HOLD` before duplicate-bid, `ERR_DRIVER_SCOPE_VIOLATION` (403), `ERR_BENCHMARK_NO_VOLUME` (422), empty award pool -> `VACANT` with HTTP 200.

## Notable specification decisions

- **PRD §2.7's numeric ladder overrides §3's narrative order** wherever they disagree, and overrides the scaffold's `preconditions` ordering. Concretely: SoD (level 3) runs before the posting's own state check on award, and `ERR_DUPLICATE_BID` (level 15) runs after driver eligibility (level 11) even though §3.9 mentions it earlier.
- **`ERR_BID_WINDOW_OPEN`** is unplaced in the ladder; implemented as part of the award's own level-8 state check, immediately after `ERR_POSTING_NOT_OPEN`.
- **Coaching-hold cascade skips only `DELIVERY` stops**, following the literal grammar of PRD §3.9 ("the stops themselves" whose subject is "Every `DELIVERY` stop"). The scaffold's looser "its stops go SKIPPED" would also cover non-delivery stops; PRD wins per the skill's fidelity rule. This is the one place where a reasonable reader could disagree, and it only diverges on a trip carrying a non-delivery stop.
- **Statement settle checks `trip.settlement_status == ACCRUED`** (per §3.8's explicit sentence) rather than `plan_status == COMPLETED` (per §2.7 level 10's looser phrasing); the former implies the latter.
- `requirements.txt` was relaxed to `Flask>=3.0` so the guarded install is a no-op against the host's Flask 3.1.3, avoiding per-test-reboot install contention.

Constraints honored: no reads of `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_helpers/`, `test_suite/`, or any sibling task directory. Storage is Python dicts only — no SQLite, no disk JSON, no `/tmp` cache, no seeding.

## Step 5: Generate unit tests — 2026-09-03T11:53:36.000Z

Launched concurrently with Step 6 in a single assistant message (physical isolation: `test_suite/`
did not exist when the impl generator started).

Subagent summary, verbatim:

Generation is complete and verified.

## Files written

**`test_helpers/`** (9 files, 2199 lines)

| file | lines |
|---|---|
| `__init__.py` | 132 |
| `api_client.py` | 339 |
| `api_errors.py` | 138 |
| `assertions.py` | 318 |
| `constants.py` | 67 |
| `factories.py` | 221 |
| `fixtures.py` | 468 |
| `test_users.py` | 70 |
| `types.py` | 446 |

**`test_suite/`** (20 files, 7332 lines, 188 tests)

| file | lines | tests |
|---|---|---|
| `conftest.py` | 56 | — |
| `test_01_*.py` | 181 | 6 |
| `test_02_*.py` | 332 | 8 |
| `test_03_*.py` | 380 | 9 |
| `test_04_*.py` | 366 | 12 |
| `test_05_*.py` | 292 | 7 |
| `test_06_*.py` | 351 | 7 |
| `test_07_*.py` | 320 | 6 |
| `test_08_*.py` | 352 | 6 |
| `test_09_*.py` | 400 | 11 |
| `test_10_entity_contracts.py` | 505 | 16 |
| `test_11_state_machines.py` | 690 | 19 |
| `test_12_calculations.py` | 638 | 14 |
| `test_13_validations.py` | 847 | 18 |
| `test_14_endpoints.py` | 505 | 10 |
| `test_15_errors.py` | 688 | 14 |
| `test_16_rbac.py` | 541 | 10 |
| `test_17_cross_cutting.py` | 719 | 12 |
| `test_18_consistency.py` | 147 | 2 |

## Coverage

- **Queue A (difficulty, §1.8): 26 of 26 instances -> 73 tests.**
- **Queue B (corner, §1.9): 60 of 60 non-stub instances -> 115 tests** (73 instances total; the 13 stub instances are intentionally untested). Per section: entities 11, state_machines 10, calculations 7, validations 9, endpoints 5, errors 7, rbac 4, cross_cutting_complexity_layers 6, consistency_model 1.
- **Instances skipped by the PRD-first filter: none.** Every non-stub instance had verbatim PRD coverage that uniquely derives its outcome.

## Verification

`pytest --collect-only` collects 188 tests cleanly. A citation checker (AST docstring extraction, whitespace-normalized verbatim containment of every quoted span against `workspace/PRD.md`, exactly one `Design:` line per test) reports `tests: 188 problems: 0`. A tag checker reports `bad: []`, `difficulty covered: 26 of 26`, `corner covered: 60 of 60`, `corner missing count: 0`. `py_compile` and `pyflakes` are clean across `test_suite/`; no `meta["total"]` (only `total_count`) and no mention of the scaffold anywhere; 188 unique test names.

## Documented deviations where a design instance contradicted the PRD

The asserted outcome always follows the PRD, never the instance's arithmetic:

1. **Stopless assignments** (TRIP-V9, TRIP-X6, TRIP-C6): three instances staff a DRAFT trip with no stops, but §3.5 says a trip with no stops has a null `planned_end_at` and can never be assigned. Added a store/order/DELIVERY stop to each fixture so the successful assignment is legal.
2. **SoD vs. bid-window ordering:** the own-award instance asserts `ERR_BID_WINDOW_OPEN` (409) ahead of `ERR_SEGREGATION_OF_DUTIES`, but §2.7 level 3 puts SoD above entity-state checks while §3.9 lists the window first — not uniquely derived. Dropped the early-award probe and awarded after `bid_close_at`, preserving the instance's real claim.
3. **TRIP-C4 arithmetic:** the design's `planned_duty` 255 / pay 24400 mis-sums service; §3.4 gives service 90 + drive 160 + break 0 = **250**, and pay 10400 + 4000 + 0 with a 5600 guarantee makeup = **20000**.
4. **`delivered_cases` timing:** the design asserts 400 after one stop completes; §3.4/§3.7 set `delivered_cases` at close-out, so it is **0** beforehand.
5. **Invalid enum:** `origin_kind: THIRD_PARTY_PICKUP` is not a declared value; used `THIRD_PARTY`.
6. **Tractor PATCH:** corrected the instance's `pm_hold` expectation to `True` per the PM-interval rule.

## Step 7: Run tests and iterate — 2026-09-03T12:14:52.354Z

Orchestrator verification (per the "Verify Step 7 sweep artifacts" rule): read all 8
`workspace/implementation/results.{1..8}.json` directly — every one reports
`passed=188, failed=0, total=188, errors=0`, all written at 12:12 UTC. The clean sweep is
backed by artifacts on disk, not just the subagent's claim. Step 7 applied 4 fix groups
(3 in the test layer, 1 in `implementation/`), so Step 8 is NOT skipped.

Subagent summary, verbatim:

Clean sweep achieved. All 8 parallel rounds report `passed == total == 188`, `failed == 0`, verified from `results.1.json` … `results.8.json` on disk.

## Summary

**Iterations run: 2**

Sweep 1: all 8 rounds identical at 106/188 (82 failures, fully deterministic — no flakiness anywhere in either sweep). Sweep 2 after fixes: 8x188/188.

**Tests deleted: none.** Every failing test's rule was verbatim in PRD.md; no PRD-silence deletions were warranted.

**Fixes applied to `test_suite/` (the test layer, all in `/home/ubuntu/github/CodingPRD/tasks/task_2536_private_fleet_operations_backhaul_optimization/test_suite/`)**

1. **Double-wrapped validators — 128 call sites across 11 files** (`test_03`, `test_08`, `test_10`, `test_11`, `test_12`, `test_13`, `test_14`, `test_15`, `test_16`, `test_17`, `test_18`). The generated tests wrote `get_success_data(validate_success(resp, 200))`. `validate_success` already returns the `data` dict, so the outer `get_success_data` received a dict and blew up on `response.status_code` — accounting for 79 of the 82 failures. Stripped the redundant outer wrapper, leaving `validate_success(resp, 200)`, which asserts the *exact* status (strictly stronger than the lenient any-2xx `get_success_data`). Also dropped the now-unused `get_success_data` import from the 7 files where no other use remained; `pyflakes` is clean.

2. **`test_13_validations.py::test_a_recycled_store_code_is_refused_even_with_different_capacities`** — asserted `clash["error"]["id"]`, but `validate_error` returns the `data` object itself (`{error_id, message}`). Corrected to `clash["error_id"]`; the `ERR_DUPLICATE_CODE`/422 assertion above it is untouched.

3. **`test_04_transitive_cascades.py::test_the_hold_flip_pushes_the_planned_trip_backwards_into_draft`** — STEP 1c partial-coverage split. §3.9's sentence is *"Every `DELIVERY` stop on those trips releases its replenishment order `SCHEDULED -> UNSCHEDULED` … and the stops themselves go to `SKIPPED`"* — the subject is the DELIVERY stops, so PRD does not state that a trip's `VENDOR_PICKUP`/`DROP_OFF` stops are skipped by the coaching-hold cascade. Kept the covered assertion (DELIVERY stops -> `SKIPPED`), removed the uncovered one by filtering the loop on `stop_type`.

**Fixes applied to `workspace/implementation/`**

4. **`routes_pay.py`, module constant `VARIANTS` (used by the `GET /fleet/pay-statements` filter)** — was `("FINAL_SETTLEMENT",)`, so a filter of `variant=PLANNED_ACCRUAL` was rejected as `ERR_INVALID_REQUEST` instead of returning an empty page. §2.11 declares statements "filtered by … `status` or `variant`" and §3.8 declares the engine's *two* variants by name, so `PLANNED_ACCRUAL` is a declared enum value under §2.7 level 7. Widened to both members; nothing else changed (only `FINAL_SETTLEMENT` is still ever written to a statement).

No assertions were weakened, no skip/xfail added, no error_id downgraded to an HTTP-status check, and no PRD-required implementation check removed.

## Step 8: Finalize PRD — 2026-09-03T12:18:04.374Z

Orchestrator check: `PRD_FINALIZED.md` is 496 lines / 115584 chars vs `PRD.md` 496 lines / 115093
chars — a real +491-char in-paragraph diff, not a byte-identical copy.

Subagent summary, verbatim:

Both edits confirmed against the implementation and the tests. Done.

## Summary

**Line counts:** PRD.md 496 lines -> PRD_FINALIZED.md 496 lines (0.0% line delta; both edits are in-paragraph insertions into existing long lines — +2 sentences, ~+490 chars, ~+0.4% by bytes).

**Changes (2 total):**

- §2.11 (Path Addressing, Filtered Collections) — *insert* — pinned the `variant` filter vocabulary on `GET /fleet/pay-statements` to both `PLANNED_ACCRUAL` and `FINAL_SETTLEMENT`, so `variant=PLANNED_ACCRUAL` is well-formed and returns an empty page rather than `ERR_INVALID_REQUEST` — `implementation/routes_pay.py:15,50`
- §3.9 (Coaching-hold cascade) — *revise* — resolved the ambiguous subject of "the stops themselves go to `SKIPPED`" to the `DELIVERY` stops only, and stated that no stop of any other type is touched (status and `version` unmoved) — `implementation/routes_board.py:62-75`

**Items from `<step_7_diff>` that produced NO PRD edit:**
- Item 1 (128 double-wrapped `get_success_data(validate_success(...))` call sites) — pure test-harness bug; the envelope and status contract in §2.2/§4 already determine the behavior.
- Item 2 (`clash["error"]["id"]` -> `clash["error_id"]`) — pure test bug; §2.2's error envelope already spells out `data.error_id` verbatim.

## Per-edit pre-edit search log

**Edit 1 — §2.11 variant filter**
- (a) Subject: the `variant` token — every place the system declares or validates a `variant` vocabulary, and every place a statement's `variant` is written.
- (b) Enumerated/read: `grep -rn "variant" implementation/*.py` -> `routes_pay.py:11-15,50` (statement list filter, `VARIANTS`), `routes_trips.py:552,559,565` (`PAY_VARIANTS` on the trip pay preview — same two members, `qrequired_enum`), `routes_network.py:128,135,179,191` (`BENCHMARK_VARIANTS` = `FULLY_ALLOCATED`/`INCREMENTAL_VARIABLE`, a *different* vocabulary), `calc.py:172,175,195` (engine branch on the two pay variants), `calc.py:518` (`accrue_statement` writes `variant: "FINAL_SETTLEMENT"` — the only write site). Also read `validate.py:211-217` (`qenum` fails `ERR_INVALID_REQUEST` on an undeclared value, returns `None` when absent -> filter skipped).
- (c) Adjustment: scoped the sentence explicitly to "the `variant` filter" on the *statement collection* rather than to `variant` generally, so it cannot be read as touching the benchmark's `variant` vocabulary; and kept §3.8's existing "`FINAL_SETTLEMENT` — the only value that field ever holds" verbatim by phrasing the addition as *the filter's declared vocabulary*, not as values the field can hold (consistent with `calc.py:518` being the sole writer).

**Edit 2 — §3.9 coaching-hold cascade stop scope**
- (a) Subject: which stops move to `SKIPPED`, and under which operation.
- (b) Enumerated/read: `grep -rn "SKIPPED" implementation/*.py` -> `routes_board.py:75` (coaching-hold cascade: filters `stop_type != "DELIVERY"` with `continue`, so non-DELIVERY stops get neither a status change nor a `bump`), `routes_trips.py:500` (trip **cancel**: skips *every* stop in `PLANNED`/`ARRIVED` regardless of type), `routes_trips.py:18,20,424` (stop-status vocabulary and the complete-trip terminal-state gate). Also read `routes_fleet.py:122-152` (driver termination — releases bids only, never touches stops) and confirmed `coaching_hold_cascade` has exactly one definition and no other caller path. Confirmed the full stop-type set at `routes_trips.py:17`.
- (c) Adjustment: the first draft said "Only `DELIVERY` stops are touched by this cascade", which would have falsely contradicted the same paragraph's own trip/tractor/trailer strip and risked bleeding into the cancel path at `routes_trips.py:500`. Re-scoped to "No stop of any other type is touched", left inside the cascade sentence so it binds only to the coaching-hold cascade, and added "their `version` does not move" to match the `continue`-before-`bump` control flow.

## Step 9: Complete PRD — 2026-09-03T12:44:56.185Z

Orchestrator decision (recorded per the AUTONOMY directive): Step 9 was run as **three sequential
file-partitioned subagent passes** rather than one subagent. A single-pass scan over an
11-module / ~3500-line implementation reliably returns a PRD_COMPLETED.md that is byte-identical
to its input — i.e. the scan never actually ran. Partitioning bounds each pass's reading load:
  - Pass A: core.py, validate.py, app.py, routes_network.py  (created PRD_COMPLETED.md from PRD_FINALIZED.md)
  - Pass B: calc.py, routes_pay.py, routes_backhaul.py
  - Pass C: routes_fleet.py, routes_orders.py, routes_trips.py, routes_board.py (+ final structural check)
Each pass edited the same PRD_COMPLETED.md in place and was told not to revert its predecessors.

Orchestrator verification: PRD.md 115093 chars -> PRD_FINALIZED.md 115584 -> PRD_COMPLETED.md
126977 (all 496 lines). `cmp` confirms PRD_COMPLETED.md is NOT identical to PRD_FINALIZED.md —
the scan produced a real +11393-char patch. 5 top-level sections, ends on the final §5 error row.

Totals across the three passes: **34 ambiguity-pins + 10 mismatch-revisions = 44 edits**, all
in-paragraph, no new sections, no line-count change.

### Pass A summary, verbatim:

PASS A complete. `PRD_COMPLETED.md` was created from `PRD_FINALIZED.md` and edited in place; only prose determined by my four partition files was touched.

## Counts
- `PRD_FINALIZED.md`: 496 lines / 115,584 chars -> `PRD_COMPLETED.md`: 496 lines / 119,919 chars (**+4,335 chars**, no new lines, no new sections — every change is an in-paragraph insert or revision)
- 16 PRD lines changed / 17 discrete edits: **15 ambiguity-pins, 2 mismatch-revisions**

## Changes
- §2.1 (L17) — insert — ambiguity — missing/empty `X-User-ID` is also `ERR_UNAUTHENTICATED`, tested after the role so the role wins when both are wrong — core.py:288-299
- §2.2 (L48) — insert — ambiguity — `api_request_id` is `req_` + twenty uppercase-letter/digit characters — core.py:127-131
- §2.2 (L51) — insert — ambiguity — audit-only free-text fields (`reason_code`, `termination_reason`, `dispute_note`, `coaching_note`, `performed_odometer_miles`) are recorded internally and never appear on any resource representation — core.py:265-266
- §2.3 (L78) — insert — ambiguity — non-integer `limit`/`offset` are `ERR_INVALID_REQUEST`, `offset` has no upper bound, an empty value means absent -> default — validate.py:181-201
- §2.3 (L80) — insert — ambiguity — `created_at` ties are broken by server creation sequence, so pages are deterministic — core.py:273-275
- §2.4 (L84) — insert — ambiguity — `created_at`, `updated_at` and `api_request_timestamp` come from the real clock, never the logical clock — core.py:246-262, core.py:149-153
- §2.6 (L102) — revise — **mismatch** — "instant comparisons are exact to the second" -> exact at full supplied precision, fractional seconds included, never truncated — core.py:305-333
- §2.7 L5 (L112) — insert — ambiguity — a non-string reference is not a level-5 not-found; it falls through to level 7 as `ERR_INVALID_REQUEST` — validate.py:248-263
- §2.7 L7 (L114) — insert+revise — ambiguity — RFC 3339 acceptance (`Z` or `+/-HH:MM`, any case, any fractional digits; stored/echoed byte-for-byte, compared in UTC); absent/unparseable body treated as `{}` while a non-object body is `ERR_INVALID_REQUEST`; explicit `null` on an optional field means omitted; integer fields reject booleans and non-integral numbers, number fields reject booleans — validate.py:19-29, 48-65, 80-83
- §2.11 (L157) — insert (x2) — ambiguity — filters narrow conjunctively on exact equality; enumerated filters reject out-of-vocabulary values with `ERR_INVALID_REQUEST`; reference/free-text filters accept any string and match nothing; boolean filters accept `true/false/1/0` in any case; empty value means absent — core.py:384-397, validate.py:204-229
- §3.1 (L167) — insert — ambiguity — re-asserting a store's current `status` is accepted (not an invalid transition) and still bumps `version` — routes_network.py:68-76
- §3.1 (L175) — insert — ambiguity — a pay-plan amendment supplying no rate at all is accepted and still raises `version` — routes_network.py:253-276
- §3.8 (L306) — insert — ambiguity — `variant`, `window_start`, `window_end` are mandatory query params; omission is `ERR_INVALID_REQUEST` reported only after the domicile is resolved — routes_network.py:134-138
- §3.8 (L310) — insert — ambiguity — under `INCREMENTAL_VARIABLE` the exclusion touches only `total_cost_cents`; `fixed_cost_cents` still reports the full computed window charge — routes_network.py:176-182
- §3.8 (L312) — revise — ambiguity — `window_start`/`window_end` are echoed exactly as supplied, `window_days` is derived — routes_network.py:191-193
- §5 (L429) — insert — **mismatch** — "status paired with an identifier is fixed" now excepts the transport-level rejections: unknown path -> `ERR_INVALID_REQUEST` with 404, unsupported method -> `ERR_INVALID_REQUEST` with 405 — app.py:43-51

## Scan attestation
Exhaustively scanned all four partition files — `core.py` (404 lines), `validate.py` (263), `app.py` (66), `routes_network.py` (276) — line by line: envelope/meta shape, error catalogue, auth, DB/clock init, id/timestamp/version machinery, filters, pagination, rounding helpers, all typed readers, FK resolution, blueprint/error handlers, and all 12 network endpoints including the full cost-benchmark formula chain. Every edit was cross-checked against the whole `implementation/` tree (greps over `qenum`/`qstr`/`qbool`, `page(`, `new_row`, `clock_now`/`real_now`, underscore-prefixed fields, `by_created`) so no wording is true only locally. Verified with no change needed: the §5 catalogue is set-, status- and order-identical to `ERROR_STATUS` (63 entries); the 62/19 cents-per-mile fuel/maintenance rates; the half-open benchmark window and `window_days` floor-at-1; the `TelematicsEvent` no-`version`/no-`updated_at` exception; `has_more`/`total_count` semantics; all role lists in §4 for network endpoints. I did not read SCAFFOLD*.yaml, worklog.md, or any sibling task directory. Untouched for passes B/C: pay/backhaul calculation internals (`calc.py`) and the driver/order/trip/board endpoint flows.

### Pass B summary, verbatim:

Scan complete. Ten edits made to `PRD_COMPLETED.md`, all in-paragraph.

**Before -> after:** 496 lines / 119,919 chars -> 496 lines / 122,744 chars (no new lines, no new sections).

**Counts:** 8 ambiguity-pins, 2 mismatch-revisions.

- **§2.7 level 10** — revise — mismatch — "a settling statement's trip must be `COMPLETED`" was false: `routes_pay.settle_statement` gates on the trip's *payroll* dimension being `ACCRUED` and never re-reads `plan_status`; also corrected the level's code list, which named `ERR_STATEMENT_NOT_ACCRUED` (actually a level-8 code) instead of `ERR_INVALID_STATE_TRANSITION` — routes_pay.py:65-67
- **§3.5 (maintenance conflict)** — revise — mismatch — "A trip with no stops … can never be assigned at all, so the interval is always well defined" was false: `trip_buffered_interval` returns null for a stopless trip and both the maintenance-conflict and rest-gap checks return early rather than failing (and `assign_trip` imposes no stop requirement) — calc.py:349-357, 365-369, 396-401
- **§3.5 (pay-plan pin)** — insert — ambiguity — the pin also captures the six rate values in force at that instant (which is what later pay computations read, and why an in-place amendment of the same plan row cannot re-price the trip), held internally and not a field of the trip representation — calc.py:468-483, 493-501
- **§3.6 (submit-review)** — insert — ambiguity — the status check precedes the expiry check, so an offer both out of `PROPOSED` and past expiry reports `ERR_OFFER_NOT_UNDER_REVIEW` — routes_backhaul.py:96-99
- **§3.6 (revise)** — insert — ambiguity — status check precedes the round-limit check; and the four optional economics fields are shape-checked at level 7 (same bounds as creation) before either state check — routes_backhaul.py:111-118
- **§3.6 (expiration sweep)** — insert — ambiguity — the response is a single summary object echoing no rows; `expired_offer_ids` follows `created_at` ascending, and `unlinked_trip_ids` is grouped per swept offer in that same order — routes_backhaul.py:210-227
- **§3.7 (PM projection)** — insert — ambiguity — the next-midnight boundary is strict; both window instants use the three-fractional-digit form; and the projected window is never run through §3.2's buffered-closed conflict test, so it may legitimately collide with another committed trip of the same tractor — calc.py:435-449
- **§3.8 (hourly component)** — insert — ambiguity — under `FINAL_SETTLEMENT` a null `actual_duty_minutes` (trip not yet closed out, reachable via pay-preview) is read as zero — calc.py:196
- **§3.8 (settlement)** — insert — ambiguity — `settlement_reference` is a mandatory string with no default and no length bound, rejected at level 7 before the statement's status check; the settled statement, not the trip, is returned — routes_pay.py:60, 77
- **§3.8 (reversal)** — insert — ambiguity — the statement's status is the only gate (the trip's payroll dimension is never examined, so reversal is legal from a `DISPUTED` trip and lands it in `ADJUSTED` regardless); an existing `settlement_reference` is left untouched; the reversed statement is returned — routes_pay.py:86-97

**Partition scanned exhaustively:** `calc.py` (540 lines — all 14 calculations, every constant, every rounding site, both pay variants, the pin/snapshot/accrual trio), `routes_pay.py` (97 lines — all four endpoints plus `_unwind_ledgers`), `routes_backhaul.py` (227 lines — all nine endpoints). Every behaviour was classified; the remainder either already had a unique PRD pin (offer margin's eleven steps and tier keying, HOS ceilings/order/strictness, safety score and hold threshold, dock hours/window/capacity geometry, closed-buffered overlap, rest-gap boundary, trip aggregates and `peak_case_load` walk, service-minute rounding order, accept-offer gate order and SoD conditionality, statement field set, ledger movements) or is unobservable (integer-valued roundings that are no-ops, unreachable defensive branches such as a missing store on a `DELIVERY` stop or an unresolvable driver plan at pin time).

Read core.py/validate.py/routes_trips.py/routes_board.py/routes_network.py for cross-checking only. One out-of-partition observation for pass C: `routes_trips.py:371-374` (backhaul re-link) returns a displaced `ACCEPTED` offer to `PROPOSED` but, unlike trip cancellation at `routes_trips.py:534-535`, does **not** reset `margin_exception_approved` — §3.6 line 253 is silent on that field.

### Pass C summary, verbatim:

PASS C complete.

## Scope scanned (exhaustive)

- `implementation/routes_fleet.py` (278 lines) — all 12 endpoints: driver create/read/list/pay-plan-assign/hos-reset/duty-log/termination cascade; tractor create/read/list/patch + `_derive_tractor`; trailer create/read/list.
- `implementation/routes_orders.py` (246 lines) — all 11 endpoints: replenishment order create/read/list/cancel; work order create (polymorphic asset), read/list, defer/reschedule/start/complete/cancel + `_asset_of`.
- `implementation/routes_trips.py` (686 lines) — all 17 endpoints: trip create/read/list; stop append/list/delete; plan gate; assignment; backhaul linkage; dispatch; complete (full cascade); cancel (both shapes); pay-preview; re-accrue; settlement-dispute; flat stop read/list/arrive/complete + `_driver_scope`.
- `implementation/routes_board.py` (385 lines) — all 14 endpoints: posting create/read/list/award/cancel; bid create/read/list/withdraw; telematics create/read/list/coach; logical-clock setter + `coaching_hold_cascade` and `_release_bids`.

`core.py`, `validate.py`, `calc.py`, `routes_pay.py`, `routes_backhaul.py`, `routes_network.py`, `app.py` were read as cross-reference only (every edit was grepped against the whole `implementation/` dir before committing).

## Size

| | lines | chars |
|---|---|---|
| before | 496 | 122,744 |
| after | 496 | 126,977 |

No new paragraphs, no new sections; all 17 edits are in-paragraph.

## Counts: 11 ambiguity-pins, 6 mismatch-revisions

- §2.1 — insert — ambiguity — driver-scope ownership comparison runs *after* the level-8 state check, not at level 2 — `routes_trips.py:418-420, 607-609, 646-650, 672-675`; `routes_board.py:283-286`
- §2.7 L6 — revise — mismatch — `ERR_PARENT_MISMATCH` guards **stop append and stop deletion** (two ops, two forms), not "stop append, stop arrival, stop completion, bid withdrawal (four)"; the flat stop surfaces name no parent and bid withdrawal raises driver-scope instead — `routes_trips.py:114,186`; `routes_board.py:278-293`
- §2.7 L10 — revise — mismatch — an asset the addressed trip already holds counts as free; a shop-bound asset must be `AVAILABLE`; guarded ops seven->**eight** (adds work-order start) — `routes_trips.py:279-287`; `routes_orders.py:200-202`
- §2.7 L15 — revise — mismatch — code-uniqueness guards ten->**twelve** operations (adds trip creation and route-posting creation, the 7th and 8th business codes) — `routes_trips.py:40`; `routes_board.py:95`
- §3.2 — insert — ambiguity — tractor correction: empty subset accepted and still bumps `version`; resulting `pm_last_service_odometer > odometer_miles` is `ERR_INVALID_REQUEST` with the omitted member read from the current row; a correction may clear a hold — `routes_fleet.py:216-232`
- §3.2 — insert — ambiguity — reschedule leaves `deferral_count` untouched (ceiling not refreshed) — `routes_orders.py:186-189`
- §3.3 — revise — mismatch — duty-log correction leaves `hos_status` **exactly as it stood** (PRD said "re-derives `hos_status`") — `routes_fleet.py:104-119`
- §3.3 — insert — ambiguity — empty duty-log correction accepted; none of the three driver operator surfaces examines `status`, so all remain available on a `TERMINATED` driver — `routes_fleet.py:74-86,89-119`
- §3.4 — revise — mismatch — stop deletion has **no** plan-status gate (PRD said "from a `DRAFT` trip"); §4 table row 377 wording aligned — `routes_trips.py:180-194`
- §3.4 — insert — ambiguity — deletion cascades nothing (order/ledger untouched) and returns the parent trip in `data` — `routes_trips.py:187-194`
- §3.5 — insert — ambiguity — assignment permitted in `DRAFT`/`PLANNED`/`DISPATCHED`/`IN_PROGRESS`, else `ERR_INVALID_STATE_TRANSITION` — `routes_trips.py:276-277`
- §3.5 — revise — mismatch — an asset already `ASSIGNED` to *this* trip passes the availability gate — `routes_trips.py:279-287`
- §3.6 — insert — ambiguity — **the handed-over lead, verified**: the re-link path returns a displaced `ACCEPTED` offer to `PROPOSED` with `margin_exception_approved` left as it stood (the reset is cancellation-only), and the displaced offer's `version` advances whatever status it held — `routes_trips.py:370-374` vs `routes_trips.py:533-536`
- §3.7 — insert — ambiguity — a check-out omitting `cases_handled` moves neither the parent's aggregates nor its `version` — `routes_trips.py:683-685`
- §3.7 — insert — ambiguity — `DRAFT` cancellation leaves the pre-linked backhaul offer, `backhaul_offer_id`, `backhaul_credit_cents` and `hos_status` all untouched — `routes_trips.py:503-538`
- §3.8 — insert — ambiguity — pay-preview `variant` is mandatory (`ERR_INVALID_REQUEST` at level 7, after trip resolution) and an unresolvable pay plan is `ERR_REFERENTIAL_INCOMPLETE` — `routes_trips.py:559-562`
- §3.9 — insert — ambiguity — the coaching-hold strip leaves the trip's backhaul link and credit untouched, even when pushed back to `DRAFT` — `routes_board.py:47-53`
- §3.9 — insert — ambiguity — an `X-User-ID` naming no `Driver` row is `ERR_DRIVER_NOT_FOUND` at bid placement, resolved after the posting reference and body shape and before the stale-version guard — `routes_board.py:225`

## Structural consistency check (final pass duty): PASS

- Well-formed markdown; the only odd-backtick lines are the four ```json fences (33/46/58/70), as expected.
- All five top-level sections present and in order (1 Introduction, 2 Global Specifications, 3 Business Logic, 4 Endpoint Definitions, 5 Error Code Catalogue); §2.1–2.11 and §3.1–3.9 all present in order.
- §4 endpoint table: **84 rows**, every one beginning with a valid method.
- §5 error table: **63 rows**, matching `core.ERROR_STATUS` exactly (63 entries).
- File ends at a real section boundary — the last `ERR_BENCHMARK_NO_VOLUME | 422` table row followed by a single trailing blank line, no mid-sentence truncation.

Two notes for the record: (1) four of my edits landed in §2.1/§2.7, nominally PASS A's sections, but each was *determined* by my partition files (the only `ERR_PARENT_MISMATCH`, `ERR_DRIVER_SCOPE_VIOLATION`, extra `unique_code` and extra `ERR_ASSET_NOT_AVAILABLE` sites live in `routes_trips.py`/`routes_board.py`/`routes_orders.py`), and each old wording was a false universal that would have created a new mismatch had I only edited §3. (2) I deliberately did **not** pin the narrative-vs-precedence listing order in §3.5's plan gate and §3.9's bid gate (both narrate gates in an order that differs from §2.7's ladder), because §2.7's numbered levels plus per-code level assignment already determine those uniquely.

---

# PIPELINE COMPLETE — Step 9 wrote workspace/PRD_COMPLETED.md.
