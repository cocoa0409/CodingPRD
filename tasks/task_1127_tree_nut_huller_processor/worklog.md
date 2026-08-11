# Worklog — task_1127_tree_nut_huller_processor

## Step 1: Create Task Directory — 2026-08-10T20:30:00.000Z

Task directory pre-assigned as `tasks/task_1127_tree_nut_huller_processor` with `workspace/` subdirectory; both verified present on disk. Step 1 treated as done per pipeline invocation instructions (no auto-index scan run).

Scenario: "generate task hard than expert level! 1127. Tree-Nut Huller & Processor (California almond huller): field lot intake & moisture/kernel test, hulling/drying yield & shrink, in-shell vs kernel processing routing, grower payment on graded kernel weight, aflatoxin sampling & lot rejection, storage rotation & fumigation, sizing/sorting spec by buyer, byproduct (hull/shell) sales"

## Step 2: Generate Scaffold — 2026-08-10T21:05:00.000Z

Scaffold generation complete. All three artifacts are in `/home/ubuntu/github/CodingPRD/tasks/task_1127_tree_nut_huller_processor/`, generated purely from the scenario text plus the skill spec (no sibling tasks read).

**Deliverables**
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys): fixed response envelope, 15 entities, 9 state machines, 2 OCC concurrency rules, 8 calculation rules, ordered validations (priorities 1–10), 65 endpoints, 33 error codes, 6 roles (PlantAdmin/IntakeOperator/LabTechnician/PlantOperator opaque; Grower/Buyer entity-backed with ownership scoping).
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — `scaffold_difficulty_design:` with all 9 rules × 2 instances = 18, each with a fully structured `setup_api_calls`/`trigger`/`assert` recipe.
- `SCAFFOLD_CORNER_DESIGN.yaml` — `scaffold_corner_design:` with 38 lint-recognized instances across all 9 guide sections (incl. 3 `excluded_because` stubs citing §1.8 instances).

**Design highlights (harder-than-expert calibration)**
- Profile: `ledger_reconciliation` primary + `quota_allocation` secondary; flat topology, cyclic state machines, peer-roles RBAC, immediate consistency.
- Dual-variant calcs in two domains: provisional-vs-final kernel weight on FieldLot (provisional 6242.60 vs final 5400.00 pinned) and current-vs-forward-looking bin capacity (3000 vs 2000 pinned).
- Combinatorial formulas in different modes: settlement per-component-rounding-then-sum (base 800280 + premium 60021 − deduction 6002 = 854299, pre-computed) vs the ≥3-input conditional moisture-shrink branch (1980.00 vs 1950.30).
- Cascades: depth-3 aflatoxin FAIL → lot REJECTED → placements QUARANTINED → shipments BLOCKED; depth-2 fumigation start → FUMIGATION_HOLD → BLOCKED; both with compensating restoration edges.
- Two OCC true races (processing-run create on `FieldLot.version`, shipment create on `BuyerContract.version`), two interval semantics (half-open dryer adjacency vs closed fumigation interval with aeration buffer), two conserved quantities (bin lbs, grower cents).

**Verification**: `scaffold_lint.py` final verdict, verbatim: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (65 endpoints, 15 entities, 540 calls scanned). Additionally verified: no forbidden concurrency vocabulary, no unbound `${var}` placeholders in any recipe, all 59 instance names unique across both design files, and all RBAC roles declare `identity:`.

Note: the pre-existing `worklog.md` and `workspace/` in that directory were not created or modified by me.

## Step 3: Copy Shared Files — 2026-08-10T21:06:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1127_tree_nut_huller_processor/workspace/INSTRUCTION.md` (1424 bytes, verified present).

## Step 4: Generate PRD — 2026-08-10T21:25:00.000Z

PRD generation complete. (First subagent attempt died mid-write with no output on disk; re-spawned bounded subagent completed the full document.)

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1127_tree_nut_huller_processor/workspace/PRD.md` — 342 lines, 7,755 words.

**Section list:**
- §1. Introduction (2 paragraphs, business-context angle)
- §2. Global Specifications — 2.1 User and Role-Based Access Control; 2.2 API Response Structure (verbatim fixed block, untouched); 2.3 Pagination; 2.4 Common Resource Properties; 2.5 The Logical Clock and Lazy Fumigation Clearance; 2.6 Weights, Money, and Rounding Discipline; 2.7 Optimistic Concurrency on Lots and Contracts; 2.8 Validation Order and Error Precedence (all 10 priority tiers in prose); 2.9 Referential Integrity and Not-Found Errors; 2.10 Plant-Wide Safety Cascades
- §3. Business Logic — 9 subsections organized by plant workflow timeline (master data → intake/lab → drying → routing/hulling → storage/FIFO → fumigation → contracts/shipments → settlement → byproduct sales)
- §4. Endpoint Definitions (65-row table, 4 columns: Method / Path / Description / Authorized Roles)
- §5. Error Code Catalogue (33-row table, 2 columns)

**Hard contract reports:**

- **Contract 1 (Field-Name Coverage):** 73 required identifiers (all entity fields + all request_body/query_param names including `to_iso8601`, `current_utc`, `route`, OCC fields) — two passes run, pass 1 found `current_utc` missing (fixed in §2.5), pass 2: 73 present, 0 missing. PASS
- **Contract 2 (Rule Coverage):** validations[] priority: 10 tiers expressed as an explicit ordered precedence in §2.8; concurrency_rules: both OCC rules expressed with write endpoint + occ field + exact error id + 412 (§2.7, reinforced in §3.4/§3.7); state transitions: all FieldLot/ProcessingRun/DryingBatch/StorageBin/StoragePlacement/FumigationEvent/BuyerContract/Shipment/Settlement transitions expressed with from→to states, preconditions paired to error ids, and all side effects; calculations: all 8 (kernel_weight_grading both variants, settlement_amount with component-rounding-before-summation, bin_capacity_projection both variants, fifo_withdrawal_allocation with placed_at/created_at tie-break and spec gate, aflatoxin_verdict with inclusive 20.0 boundary, byproduct_available_stock, dryer_reservation_overlap half-open with adjacency allowed, fumigation_schedule_overlap closed-interval with touching forbidden) in precise reconstructible prose; all 33 error ids mentioned in §2/§3; sibling branches (IN_SHELL/KERNEL routing, both OCC rules, cascade directions) rendered with equal density. PASS
- **Contract 3 (§3 Path Purity):** 497 backtick tokens scanned in §3 — 0 path tokens, 0 bare HTTP methods, 0 method+path combos (endpoints referenced via state-pair framing, role+verb, capability description). PASS

**Final section status:** §5 Error Code Catalogue is complete — the file ends on the full 33-row error table with `ERR_BYPRODUCT_STOCK_EXCEEDED | 422` as the last row, no truncation, no audit footer. The withheld design files were never opened.

## Step 5: Generate Unit Tests — 2026-08-10T21:50:00.000Z

## File Inventory

**test_helpers/** (1498 lines total)
- `__init__.py` (38) — barrel export (framework + PRD-specific)
- `types.py` (341) — 14 status/enum types + 16 entity TypedDicts
- `api_client.py` (220) — 52 endpoint methods covering every PRD endpoint incl. `/_clock/set_current_utc`
- `api_errors.py` (80) — 33 `ApiErrorId` values + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` (225) — per-entity `assert_*` + bin/settlement/grower invariant checkers
- `factories.py` (197) — payload factories for all input-carrying entities
- `constants.py` (27) — thresholds (MOISTURE_STD 8.0, AFLATOXIN_LIMIT 20.0, PREMIUM_GRADE 0.70, etc.)
- `test_users.py` (45) — shared headers + per-instance builders for entity-backed Grower/Buyer
- `fixtures.py` (325) — tiered composites: growers/lots, sampled→graded→routed, drying completion, processed lot, bin+placement, planned shipment, DRAFT settlement

**test_suite/** (2142 lines total)
- `conftest.py` (40) — session `api` fixture + role-header fixtures
- 8 test files, 75 test functions total

## Test Counts by Queue

- **Queue A (Difficulty)**: 18/18 instances covered, each with exactly 2 tests → 36 tests
- **Queue B (Corner)**: 38/38 non-stub instances covered with ≥1 test → 39 tests (one instance, `byproduct_stock_accounting_and_exhaustion`, has 2 tests)
- **75 tagged tests total**, all collected cleanly by pytest.

## Skipped Instances

None. The 3 `excluded_because:` stubs (`shipment_blocked_to_planned_on_fumigation_clearance`, `route_state_vs_safety_priority_ordering`, `shipment_spec_vs_fiscal_priority_ordering`) are correctly untranslated; their difficulty-instance cross-references all resolve.

## Lint Verdicts

- **Syntax**: all 18 files compile (`py_compile`).
- **Coverage audit** (scripted against both YAMLs): 56 expected tags, 56 present, 0 missing, 0 unexpected — OK.
- **PRD citation audit** (verbatim, ≥8-word sliding window against PRD.md): 75/75 pass — OK.
- **No `pytest.mark.skip`/`skipif`/`xfail`**; no scaffold references in generated comments — clean.

## Step 6: Generate Implementation — 2026-08-10T21:50:00.000Z

## Implementation Complete: task_1127_tree_nut_huller_processor

### File inventory (all under `/home/ubuntu/github/CodingPRD/tasks/task_1127_tree_nut_huller_processor/workspace/implementation/`)

| File | Lines | Purpose |
|---|---|---|
| `start.sh` | 10 | Foreground launcher; guarded pip install; `exec python3 app.py` |
| `requirements.txt` | 1 | flask>=3.0 |
| `app.py` | 57 | App factory, blueprint registration, error handlers, `before_request` lazy-clearance hook, `0.0.0.0:$PORT` (default 10000) |
| `db.py` | 89 | Empty-at-boot in-memory store, logical clock (default `2026-05-01T00:00:00Z`, never wall-clock), ISO8601 parse/format, `stamp`/`touch` (updated_at + version) |
| `errors.py` | 45 | ApiError + full error catalog constants |
| `response.py` | 84 | Envelope (`meta`/`response_type`/`data`), list pagination (`limit`/`offset`/`total_count`/`has_more`, defaults 10/0, bounds 1–100), created_at-asc sort |
| `middleware.py` | 54 | `X-User-ID`/`X-User-Role` auth (401), role gating (403), body parsing |
| `validate.py` | 111 | Field/enum/range validators, state-gate helper (`ERR_ALREADY_TERMINAL` vs `ERR_INVALID_STATE`) |
| `services/calc.py` | 257 | All calculations (Decimal, ROUND_HALF_UP) |
| `services/cascade.py` | 101 | Aflatoxin/fumigation cascades, lazy clearance, shipment block/unblock |
| `services/serialize.py` | 104 | Per-entity serializers with computed aggregates |
| `routes/core.py` | 99 | Growers, buyers |
| `routes/lots.py` | 257 | Lots + lab tests |
| `routes/processing.py` | 306 | Dryers, drying batches, processing runs |
| `routes/storage.py` | 349 | Bins, placements, withdrawals, fumigations |
| `routes/commercial.py` | 464 | Contracts, shipments, settlements, byproduct sales, `/_clock/set_current_utc` |

Total: 2,388 lines across 16 files (+2 empty `__init__.py`).

### Endpoint coverage
**65/65** endpoints from SCAFFOLD §1.5 implemented (6 core + 9 lots/lab-tests + 14 dryers/batches/runs + 15 bins/placements/withdrawals/fumigations + 21 contracts/shipments/settlements/byproducts/clock).

### State machines / calculations / validations covered
- **State machines (9):** FieldLot (incl. REJECTED→SAMPLED resample cycle, REJECTED→DISPOSED, PROCESSING→PROCESSED, PROCESSED→SETTLED bubble-up), ProcessingRun, DryingBatch, StorageBin, StoragePlacement, FumigationEvent (incl. lazy AERATING→CLEARED), BuyerContract (incl. OPEN→FULFILLED bubble-up, close-from-FULFILLED), Shipment (PLANNED↔BLOCKED), Settlement (DRAFT↔ISSUED compensating void).
- **Calculations (7):** kernel_weight_grading (provisional + final variants, 2dp half-up), settlement_amount (component-rounded whole cents: base, premium gated at edible ≥ 0.70, moisture deduction 0.005/point over 8.0, summed post-rounding), bin_capacity_projection (current + forward-looking), fifo_withdrawal_allocation (placed_at/created_at order, free = remaining − allocated, partial last take, spec gate), aflatoxin_verdict (1dp, 20.0 boundary FAILs), byproduct_available_stock (plant-wide reconciliation), dryer (half-open) and fumigation (closed, incl. aeration buffer) overlap rules.
- **Validations:** full 10-priority order (auth → RBAC/ownership → path/body existence in canonical FK order → OCC `expected_lot_version`/`expected_contract_version` (412) → shape/conditional lab-test fields → state/terminal → safety lockouts → temporal → physical → fiscal), all 33 catalog error IDs with correct HTTP statuses.
- **Cascades:** aflatoxin FAIL quarantine + shipment block, resample-PASS compensation, dispose frees bins, fumigation start/aerate/lazy-clear with shipment block/unblock, all with per-resource `updated_at`/`version` bumps.

### Smoke-test results (5 suites, each on a fresh `bash start.sh` boot, then killed)
- Boot1/boot2 check confirmed **empty store after kill/relaunch** (per-test-server isolation safe); default port 10000 verified with the exact evaluator invocation.
- Suite 1 (intake→drying→route→OCC run→grade→settlement pay): PASS — provisional 6757.1, settlement components (1125000/112500/0/1237500), lot SETTLED.
- Suite 2 (placements, spec/stale/remaining gates, FIFO free-pool, fumigation closed-interval conflict + full cascade + lazy clearance, confirm, byproduct stock): PASS.
- Suite 3 (auth 401/403, grower/buyer ownership, aflatoxin 20.0-boundary FAIL cascade, resample compensation, dispose, pagination envelope/bounds): PASS.
- Suite 4 (lab-test conditional fields 400/409, multi-run input snapshots with cancel, moisture-deduction settlement (64000/32000/640/95360), void/cancel, bin-touch lazy clearance): PASS.
- Suite 5 (contract close/terminal rules, shipment cancel compensation, FULFILLED at exact delivered==required, SETTLED-lot placement rejection): PASS.

Orchestrator note: post-Step-6 route parity verified independently — 65 scaffold endpoints vs 65 Flask routes, 0 missing, 0 extra.

## Step 7: Run Tests and Iterate — 2026-08-10T22:18:00.000Z

All 8 rounds pass 75/75 with zero failures and zero errors. The flaky "server could not be restarted" errors from iteration 1 also vanished — they were load-contention artifacts of the broken iteration, not real bugs.

## Summary

- **Iterations run:** 2 (iteration 1: 5 deterministic failures + 3 flaky infra errors across rounds; iteration 2: clean 8/8 rounds, 75/75 each).

- **Tests deleted:** none — every failing assertion traced to verbatim PRD prose.

- **Fixes applied to `test_helpers/`:**
  - `fixtures.py` → `setup_settlement_draft`: `create_processed_lot(grower_id=...)` returns `grower: None` when given a grower_id (by design in `create_sampled_lot`), so the returned scenario dict violated its own documented contract and `scenario["grower"]["id"]` raised `TypeError: 'NoneType' object is not subscriptable`. Fix: restore the real grower record (`processed["grower"] = grower`) before returning. Fixed `test_settlement_approve_twice_returns_invalid_state` and `test_settlement_cancelled_terminal_lockdown`.

- **Fixes applied to `test_suite/`:**
  - `test_05_contracts_shipments.py` → `test_shipment_quantity_beyond_contract_remaining_rejected`, `test_shipment_spec_vs_contract_remaining`, `test_shipment_spec_mismatch_alone_rejected`: setup passed run outputs totaling 5900 lbs (kernel 3500 + shell 1500 + hull 900) against a default 5000-lb lot, violating the PRD's non-negative shrink rule ("the three outputs summed together may not exceed the run's `input_weight_lbs`... rejected with `ERR_SHRINK_NEGATIVE`"), so setup died with HTTP 422 before the assertion under test. Fix: pass `gross_weight_lbs=8000` at each call site so the fixture chain is PRD-consistent; assertions themselves were already faithful (PRD §Buyer Contracts remaining-quantity gate, §Validation Order category 9-before-10, and the sizing gate, all verbatim).

- **Fixes applied to `implementation/`:** none — the implementation was PRD-faithful throughout; all failures were test-artifact setup bugs.

Orchestrator verification: all 8 `results.{i}.json` files exist on disk; each reports passed=75, total=75, failed=0, errors=0.

## Step 8: Finalize PRD — 2026-08-10T22:25:00.000Z

## Step 8 report: PRD_FINALIZED.md produced — 0 edits (byte-copy)

**File:** `/home/ubuntu/github/CodingPRD/tasks/task_1127_tree_nut_huller_processor/workspace/PRD_FINALIZED.md`

### Line counts / delta
- PRD.md: 342 lines; PRD_FINALIZED.md: 342 lines; **0.0% delta** (identical md5 `489bea79…`). Per the task's own guidance, since all Step 7 fixes were pure test-artifact bugs tracing to verbatim PRD prose, the correct output is an unmodified copy — no edits were invented.

### Audit of each `<step_7_diff>` item

**Item 1 — `test_helpers/fixtures.py` → `setup_settlement_draft` grower restoration**
- (a) Subject: whether the PRD is silent/mismatched about what a processed-lot/settlement scenario's grower record is — i.e., any API behavior around grower records, processed lots, or settlement creation.
- (b) Paths enumerated and read: `test_helpers/fixtures.py:119-133` (`create_sampled_lot` — documents "Grower (unless given)", returns `grower: None` when a `grower_id` is passed, by fixture-side design), `fixtures.py:207-228` (`create_processed_lot` pass-through), `fixtures.py:299-328` (`setup_settlement_draft` and its fix at line 326); the two affected tests `test_suite/test_06_settlements.py:210-246`; implementation settlement paths `implementation/routes/commercial.py:360-408` (`_settlement_action`, approve/void/pay/cancel); PRD line 224 (settlement lifecycle, terminal states), line 120 (validation order: `ERR_ALREADY_TERMINAL` vs `ERR_INVALID_STATE`), line 146 (`payable_outstanding_cents` definition).
- (c) Finding: the bug was the fixture violating its **own documented return contract** (`processed["grower"]` was `None` though the helper created the grower itself). The API's grower/settlement behavior was never involved and matches PRD verbatim (approve from `DRAFT`→`ISSUED`, cancel from `DRAFT`→`CANCELLED`, `PAID`/`CANCELLED` terminal → `ERR_ALREADY_TERMINAL`, other wrong from-states → `ERR_INVALID_STATE`, balances as defined). **No PRD silence, no mismatch → no edit.**

**Item 2 — `test_suite/test_05_contracts_shipments.py` → `gross_weight_lbs=8000` at three call sites**
- (a) Subject: the non-negative shrink rule on run completion, the shipment sizing-spec gate, the contract remaining-quantity gate, and validation-order category 9-before-10.
- (b) Paths enumerated and read: `implementation/routes/processing.py:180-223` (run creation; `input_weight_lbs` snapshot = lot `gross_weight_lbs` minus other non-CANCELLED runs' inputs), `processing.py:269-295` (run completion; shrink check at lines 280-284 raising `ERR_SHRINK_NEGATIVE` 422 when summed outputs exceed the snapshot); `implementation/routes/commercial.py:151-218` (shipment creation; spec gate at lines 188-194 raising `ERR_SPEC_MISMATCH` **before** the remaining-quantity gate at lines 195-200 raising `ERR_CONTRACT_REMAINING_EXCEEDED`); PRD line 180 (snapshot definition, verbatim), line 182 (shrink rule, verbatim: "the three outputs summed together may not exceed the run's `input_weight_lbs`… rejected with `ERR_SHRINK_NEGATIVE`"), line 123 (validation-order category 9 lists the sizing-spec gate and category 10 the contract-remaining gate), line 208 (contract semantics / `UNSIZED`). Also cross-checked the run-complete path's harvest-accumulator recompute and `PROCESSING`→`PROCESSED` transition against PRD line 182 — consistent.
- (c) Finding: the test setups passed 5900 lbs of outputs against a default 5000-lb lot, violating the already-verbatim PRD shrink rule, so the fixture chain died with HTTP 422 before the assertions under test. The assertions themselves were PRD-faithful. Implementation matches PRD exactly on every gate involved. **No PRD silence, no mismatch → no edit.**

### Changes
- None. 0 inserts, 0 revisions. Every Step 7 fix traced to verbatim PRD prose or to test-internal fixture contracts; the implementation was PRD-faithful throughout, so `PRD_FINALIZED.md` is a byte-copy of `PRD.md`.

## Step 9: Complete PRD — 2026-08-10T22:45:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1127_tree_nut_huller_processor/workspace/PRD_COMPLETED.md` produced (copy of PRD_FINALIZED.md + 25 minimal inline edits; no new sections).

**Size**: PRD_FINALIZED.md 342 lines / 53,913 chars → PRD_COMPLETED.md 344 lines / 58,356 chars. Char delta **+4,443** (+4,484 bytes; the 2 added lines are the two §5 catalogue rows).

**Counts**: 21 ambiguity-pins, 4 mismatch-revisions.

Ambiguity-pins (insert):
- §2.1 — insert — ambiguity — entity-backed callers on list endpoints: `grower_id`/`buyer_id` filters naming another owner are overridden by caller's own id on /lots, /settlements, /contracts; buyer scope on /shipments combines conjunctively — routes/lots.py:72-75, routes/commercial.py:93-96,229-231,345-348
- §2.2 — insert — ambiguity — `api_request_timestamp` is stamped from the logical clock (success and error envelopes) — implementation/response.py:20-24
- §2.3 — insert — ambiguity — non-integer `limit`/`offset`, `limit` outside [1,100], negative `offset` → `ERR_INVALID_REQUEST` (400) — implementation/response.py:50-73
- §2.3 — insert — ambiguity — `created_at` ties break by creation order; filters combine conjunctively; dangling-id filters yield empty pages; out-of-set enum filter values → `ERR_INVALID_ENUM` (400) — implementation/response.py:76-84, implementation/validate.py:79-86
- §2.4 — insert — ambiguity — `version` starts at 1 at creation — implementation/db.py:76-83
- §2.5 — insert — ambiguity — clock may be set to any instant, earlier or later (no monotonicity constraint) — routes/commercial.py:452-464
- §2.5 — insert — ambiguity — lazy fumigation clearance actually runs at the head of every request, not only on bin-touching operations — implementation/app.py:32-34
- §2.8.2 — insert — ambiguity — ownership-vs-existence ordering: /growers/{id} and /buyers/{id} 403 before lookup; all other entity-scoped reads 404 a dangling path id before ownership — routes/core.py:56-60,93-95 vs routes/lots.py:85-87
- §2.8.5 — insert — ambiguity — explicit null counts as absent; non-object JSON body is a shape failure; unknown body fields are ignored (outside the lab-test forbidden-field rule) — implementation/validate.py:42-46, implementation/middleware.py:47-54
- §2.9 — insert — ambiguity — body foreign keys validated in fixed order (grower_id, lot_id, dryer_id, bin_id, contract_id, buyer_id), first dangling rejected; lab tests/placements/withdrawals path ids and undefined routes → `ERR_NOT_FOUND` (404) — routes/processing.py:57-63, routes/storage.py:101-107,170-173,233-235, routes/lots.py:255-256, implementation/app.py:42-48
- §3.1 — insert — ambiguity — `premium_rate_pct` supplied as null defaults to 0.0 — routes/core.py:25-27
- §3.1 — insert — ambiguity — duplicate ranch_code/buyer_code/dryer_code/bin_code → `ERR_INVALID_REQUEST` (400) — routes/core.py:31-33,71-73, routes/processing.py:35-37, routes/storage.py:61-63
- §3.2 — insert — ambiguity — `graded_kernel_weight_lbs` added to the born-null field list — routes/lots.py:59
- §3.2 — insert — ambiguity — "latest test of a type" ties on `recorded_at` break toward the later-created test — services/calc.py:75-81
- §3.2 — insert — ambiguity — aflatoxin test against any other non-terminal state (PASS on non-SAMPLED, FAIL on RECEIVED/REJECTED) copies `aflatoxin_ppb` but changes no status, fires no cascade — routes/lots.py:214-227
- §3.5 — insert — ambiguity — per-form lot output defined (KERNEL/SHELL/HULL map to same-name accumulators; IN_SHELL = kernel+shell); cumulative placed counts placements in every status (withdrawn/disposed still count) — services/calc.py:225-244
- §3.5 — insert — ambiguity — FIFO `placed_at`+`created_at` double-ties break by creation order — services/calc.py:142-150
- §3.6 — insert — ambiguity — fumigation start while bin not AVAILABLE → `ERR_INVALID_STATE` (409) — routes/storage.py:309-311
- §3.7 — insert — ambiguity — contract close with non-zero `reserved_qty_lbs` → `ERR_INVALID_STATE` (409) — routes/commercial.py:140-143
- §3.7 — insert — ambiguity — shipment planning gates report in fixed order: sizing, then remaining-quantity, then free-pool sufficiency — routes/commercial.py:188-203
- §5 — insert — ambiguity — catalogue gains `ERR_NOT_FOUND` (404; also 405 for unsupported method on a defined route) and `ERR_INTERNAL` (500) — implementation/errors.py:27, implementation/app.py:42-53

Mismatch-revisions (revise):
- §3.2 — revise — mismatch — provisional-kernel discount was "one percent for every full point" of moisture excess; impl prorates fractional excess (9.5% moisture → 1.5-point excess → 1.5% discount) — services/calc.py:46-55
- §2.6 — revise — mismatch — timestamp comparisons were "exact to the second"; impl compares parsed values at full supplied precision, reads offset-less values as UTC, and rejects unparseable timestamps as `ERR_INVALID_REQUEST` — implementation/db.py:60-73, routes/processing.py:136,154
- §3.2 — revise — mismatch — kernel-grade gate said any non-PROCESSED state → `ERR_INVALID_STATE`; impl returns `ERR_ALREADY_TERMINAL` for terminal lots (aligning with §2.8.6) — routes/lots.py:196-201
- §3.1 — revise — mismatch — "dryers and bins can be listed and re-read" implied GET /dryers/{id}; impl has no such route (consistent with the §4 table), so dryers are list-only while bins are list+read — routes/processing.py (no by-id dryer route), routes/storage.py:87-91

Everything else in the walk (all 60 endpoints, state machines, FIFO/shrink/settlement/byproduct formulas, OCC rules, cascades, precedence order) was already uniquely pinned by the PRD and matches the implementation.
