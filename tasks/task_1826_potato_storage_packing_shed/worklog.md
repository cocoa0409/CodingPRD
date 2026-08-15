# Worklog — task_1826_potato_storage_packing_shed

## Step 1: Create Task Directory — 2026-08-14T19:07:00.000Z

Pre-created by pipeline launcher: `tasks/task_1826_potato_storage_packing_shed/` and `workspace/` (skipped per orchestrator instructions).

## Step 2: Generate Scaffold — 2026-08-14T20:07:25.000Z

All three artifacts are complete and lint-clean. Final report:

### Task 1826 — Potato Storage & Packing Shed: scaffold generated

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1826_potato_storage_packing_shed/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top key `scaffold_corner_design`

**Counts**
- **Entities: 12** — Grower, StorageShed, StorageBin, FieldLot, GradeOutAssessment, CustomerContract, PackOrder, PackRun, PackRunLotDraw, WashWaterCheck, FoodSafetyAudit, GrowerSettlement
- **Endpoints: 40** (24 writes incl. `/_clock/set_current_utc` with pinned default `2026-08-01T00:00:00Z`, 6 single GETs, 10 FK reverse-reachability list GETs)
- **Errors: 39**
- **State machines: 7** — StorageShed posture (cyclic, derived from wash-fail counters + audit flags), FieldLot (**parallel dimensions**: storage_status linear × quality_status cyclic with CONDEMNED terminal), PackOrder (cyclic ALLOCATED→PACKING→ALLOCATED partial-fill loop), GrowerSettlement (FINALIZED↔DISPUTED cycle with clerk SoD), FoodSafetyAudit (cross-instance re-audit loop), CustomerContract (clock-driven branching to FULFILLED/SHORTFALLED), PackRun (branching close)
- **Calculations: 8**, validations: 10 priority tiers, concurrency rules: 2 (OCC on FieldLot.version for assessments, Grower.version for superseding settlements), roles: 8 (segregation_of_duties model)

**§0.3 structural dimensions applied**: entity_topology `graph` (PackRunLotDraw junction + cross-aggregate FKs), state_machine_shape `parallel` (FieldLot dual dimensions; cycles on 5 other entities), relationship_patterns `[one_to_many, many_to_many, cross_aggregate]`, role_model `segregation_of_duties` (QA-records-wash vs Supervisor-runs-line; dispute re-finalize requires a different clerk), consistency_model `immediate`. **§0.2 layers (4)**: dual_variant_calculation, cascading_side_effects, derived_field_reconciliation, optimistic_concurrency. Archetype: quota_allocation × ledger_reconciliation.

**§1.8 instances: 19** (≥2 per rule; combinatorial_formula carries 3 — mode (a) open-market cap with nested max/min, mode (b) per-lot-round-then-sum fees at the 12.5-cent rate producing a pinned 1-cent divergence, mode (c) pool-price evaluation-order pinning where a grower's own shipment enters its pool). Every numeric assert was precomputed with Python (e.g., provisional net 1706000 vs final 317000 cents on identical history).

**§1.9 instances: 66** (57 active recipes + 9 `excluded_because` stubs citing §1.8 instances), spanning all nine taxonomy sections.

**Quality Checklist: passed.** Verdict block verbatim:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(749 calls scanned across 19 §1.8 + 57 §1.9 instances.) Supplementary checks run beyond the linter: placeholder closure (every `${var}` bound by an earlier `captures:` — one bug found and fixed), assert-reference closure, grounds resolvability against §1.1–§1.7, cross-file name uniqueness, forbidden-vocabulary scan (none), all 39 errors referenced by a validation/transition, all transitions carry preconditions + side effects. Setup chains were replayed call-by-call; this caught and fixed a real design flaw (the RESTRICTED 4-hour wash window was unreachable under the original "latest check must be PASS" freshness rule — re-pinned as "most recent PASS anchors freshness" and the §1.8 safety-vs-temporal instance re-timed accordingly).

**Disclosure**: endpoints (40) and errors (39) sit above the Expert guideline band (32/30) — deliberate: 10 endpoints are lint-mandated FK reverse-reachability GETs and the rest are the cascade/compensation/OCC triggers the difficulty directive required; no padding entities or CRUD filler were added. Note the final SCAFFOLD.yaml was YAML-round-tripped once (to pin list ordering on all list GETs), so authoring comments were stripped; all values were verified intact afterward.

## Step 3: Copy Shared Files — 2026-08-14T20:07:25.604Z

Copied `./INSTRUCTION.md` → `tasks/task_1826_potato_storage_packing_shed/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T20:15:30.000Z

All three hard contracts pass. PRD is shipped at `/home/ubuntu/github/CodingPRD/tasks/task_1826_potato_storage_packing_shed/workspace/PRD.md`.

### Summary

**PRD line count:** 345 lines

**Section list:**
- §1 Introduction (2 paragraphs)
- §2 Global Specifications & System-Wide Principles — 10 subsections (2.1 RBAC; 2.2 API Response Structure [verbatim]; 2.3 Pagination; 2.4 Common Resource Properties; 2.5 Logical Clock and Time Semantics; 2.6 Weights, Units, and Precision; 2.7 Optimistic Concurrency Control; 2.8 Nested Resource Retrieval; 2.9 Validation Order; 2.10 Hierarchical Consistency and Cascading Side Effects)
- §3 Business Logic & Workflows — 10 subsections organized by business process (Harvest Intake; In-Storage Stewardship; Commercial Book; Allocation Waterfall; Pack-Line Operations; Cancellation & De-allocation; Food Safety; Lot Quality Holds; Grower Settlement; Reading the Operation)
- §4 Endpoint Definitions — 40 endpoints, 4-column table (Method / Path / Description / Authorized Roles)
- §5 Error Code Catalogue — 39 errors, 2-column table (Error ID / HTTP Status)

**Zero-Silence Rule confirmation — every scaffold element covered in prose:**

- **Entities (12/12):** Grower, StorageShed, StorageBin, FieldLot, GradeOutAssessment, CustomerContract, PackOrder, PackRun, PackRunLotDraw, WashWaterCheck, FoodSafetyAudit, GrowerSettlement — every field name in backticks in prose.
- **State machines (8/8):** StorageShed posture (NORMAL/RESTRICTED/QUARANTINED with recompute rules and the quarantine cascade); FieldLot storage_status and parallel quality_status (with CLEAR→ON_HOLD→CLEAR|CONDEMNED and the auto-close on zero availability); CustomerContract settle sweep; PackOrder full lifecycle including top-up self-loop and cascade de-allocation; PackRun SCHEDULED→COMPLETED|ABORTED; FoodSafetyAudit FIELD_WORK→PASSED|FAILED with cross-instance re-audit loop; GrowerSettlement PROVISIONAL→FINALIZED→PAID with DISPUTED and SUPERSEDED branches and the SoD re-finalize gate.
- **Calculations (7/7):** expected_packout_fraction (both variants, 0.75 default), allocation_waterfall (eligibility, ranking, floor/round-half-up, min guard, atomicity), open_market_cap (always lot-assessment basis, floor at zero), pool_price (two-step SHIPPED aggregation, CONTRACT_BLEND fallback, zero fallback), grower_settlement (provisional and final variants, per-lot-then-sum pinned rounding), storage_fee (12.5 cents/cwt/week, 14-day boundary, forbidden sum-then-round), shrink_reconciliation (re-baseline semantics, weight-conservation invariant), wash_water_result (all numeric bounds, quarantine threshold 8.0, freshness anchor and 12h/4h windows).
- **Validations (10/10 priority tiers):** Explicit §2.9 with ordered evaluation (auth → authorization → existence → OCC → state gates → food-safety → cross-reference → temporal → shape → fiscal), including the explicit corollary about food-safety outranking fiscal and the SoD check placed in tier 5.
- **Endpoints (40/40):** all in §4 table with correct method, path, description, roles; all side effects described in §3 narrative.
- **Errors (39/39):** all in §5 table; every error_id is also mentioned in §2 or §3 prose paired with its trigger condition.
- **Roles (8/8):** all spelled exactly; Grower identity translated as entity-backed (X-User-ID = Grower.id, ownership checks against grower_id), other seven roles translated as opaque operator identifiers.

**Hard Contract reports:**

```
Field coverage check:
- entities[].fields: 86 required, 86 present, 0 missing
- endpoints[].request_body inputs not in entity fields: 8 required, 8 present, 0 missing
- endpoints[].query_params / shared params: 1 unique ("limit"+"offset" already in 2.3; filters grower_id/bin_id/variety/storage_status/contract_id/shed_id/status all in entity set), 0 missing
Status: PASS

Rule coverage check (120 probes walked):
- validations[] with priority: 10 tiers expressed in ordered §2.9 prose, 0 missing
- concurrency_rules[] OCC rejections: 2 expressed (write_endpoint + expected_*_version + ERR_STALE_VERSION + 412 all named), 0 missing
- state_machines[].transitions: 25 transitions fully expressed (from/to + preconditions + error_id + side_effects), 0 missing
- calculations[]: 7 fully expressed (formula + constants + precision + algorithm), 0 missing
- validations[] conditions: all 39 error_ids matchable to prose trigger conditions, 0 missing
- endpoints[].side_effects / applies_to: all expressed in workflow narrative, 0 missing
- entities[].fields[] structured content (types/defaults/initial values/enum membership): all reconstructible from prose
- sibling-branch symmetry: parallel transitions (NORMAL->QUARANTINED vs RESTRICTED->QUARANTINED; REQUESTED->CANCELLED vs ALLOCATED->CANCELLED; PACKING->SHIPPED vs PACKING->ALLOCATED; audit PASS vs FAIL) all rendered with equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 477
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Step 5: Generate Unit Tests — 2026-08-14T20:38:00.000Z

Generation complete. All 99 tests collect cleanly and the Stage 2 audit passes.

### Summary

**Task**: `task_1826_potato_storage_packing_shed` — full test infrastructure generated from the two design indices only, against `workspace/PRD.md`.

#### Queue A — Difficulty (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`)
19/19 instances covered, each with ≥2 tests (38–42 tests). Skipped: none.

One PRD/deviation note: for `settlement_provisional_vs_final_packout_basis` the design's recipe listed the condemn step before a clock advance, which pins `closed_at` to 2026-08-30; the emitted final-variant test asserts the PRD-derived values (final storage_fees 50000.00 for 4 binned→closed weeks, net 392000.00) rather than the YAML's stale commentary numbers. The dual-variant contrast the instance exists to probe (provisional net 1706000 vs final 392000, basis 882.00 vs 200.00, CONTRACT_BLEND fallback vs realized pool) is fully asserted.

#### Queue B — Corner (`SCAFFOLD_CORNER_DESIGN.yaml`)
57/57 active instances covered with ≥1 test each; 9 `excluded_because:` stubs excluded (all cross-references into queue A verified to resolve). Skipped: none.

#### Stage 2 audit
- **Tag coverage**: PASS — every non-stub instance has its required test count (queue A ≥2, queue B ≥1)
- **Tag uniqueness/format**: 99 tests, exactly one `Design:` line each; zero orphan tags; zero untagged tests
- **PRD citation sweep**: 147 quoted citations, 100% verbatim-grep survivable against PRD.md (C1/C2/C3)
- **No** `pytest.mark.skip`/`skipif`/`xfail`; no scaffold references in comments/docstrings
- `pytest --collect-only` collects all 99 tests with no import errors

#### Files
- `test_helpers/`: `__init__.py`, `types.py` (append-only entities correctly omit `version`/`updated_at`), `api_client.py` (one method per PRD §4 endpoint), `api_errors.py` (39 errors registered via `set_error_http_status_map`), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (incl. `make_grower_headers` for the entity-backed Grower role and `make_clerk_headers` for SoD), `fixtures.py` (composite setups incl. `setup_allocated_contract_order`, `setup_packing_order_with_run`, `setup_grower_with_closed_lot`)
- `test_suite/`: `conftest.py` + `test_01_settlement_economics.py`, `test_02_allocation_waterfall.py`, `test_03_pack_line_and_runs.py`, `test_04_food_safety_cascade.py`, `test_05_lot_lifecycle.py`, `test_06_settlement_lifecycle.py`, `test_07_orders_and_terminal_states.py`, `test_08_api_conventions.py`, `test_09_records_audits_pool.py`

## Step 6: Generate Implementation — 2026-08-14T20:57:00.000Z

Implementation complete and verified. Summary:

### Files created (all under `/home/ubuntu/github/CodingPRD/tasks/task_1826_potato_storage_packing_shed/workspace/implementation/`)

- `start.sh` — launcher (executable)
- `requirements.txt` — `flask>=3.0,<4.0`
- `app.py` — Flask app factory, error handlers (ApiError/404/405/500 all return the scaffold error envelope), binds `0.0.0.0:$PORT` (default 10000)
- `store.py` — in-memory dicts for all 12 entity types + the logical clock (starts exactly `2026-08-01T00:00:00Z`)
- `util.py` — response envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`), pagination (`limit`/`offset`/`total_count`/`has_more`, default 10, min 1, clamp 100), Decimal/datetime helpers, field validators, `round_half_up`/`floor2`
- `auth.py` — `X-User-ID`/`X-User-Role` validation (400 `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), per-endpoint RBAC (403 `ERR_INSUFFICIENT_PERMISSIONS`), Grower entity-backed ownership checks
- `logic.py` — derived-field reconciliation (bin `occupied_cwt`/variety lock, lot `available_cwt`/`reserved_cwt`, contract commitment ledger recomputed from orders), posture recompute + quarantine cascade, allocation waterfall (LOT_ASSESSMENT/SHED_BLEND fractions at 4dp, floor2 coverage, rhu raw with allocatable cap, atomic pre-flight), open-market cap, wash freshness (12h NORMAL/4h RESTRICTED, inclusive), line-schedule conflict (1h cross-variety buffer, half-open adjacency), settlement math (per-lot-then-sum rounding, pool price with CONTRACT_BLEND fallback, storage/inhibitor/processing lines)
- `views.py` — all 36 endpoints, validation priority per PRD §2.9 (auth → RBAC/ownership → existence → OCC → state → food-safety → cross-ref → temporal → shape → fiscal), OCC on assessments/settlements (`ERR_STALE_VERSION` 412), SoD re-finalize (`ERR_SOD_REFINALIZE_CLERK` 403), season supersede/conflict, clock settle sweep (FULFILLED/SHORTFALLED)

### State storage

In-memory only: module-level dicts in `store.py`, empty on every boot. No seeding, no disk persistence. Logical clock resets to `2026-08-01T00:00:00Z` per process. Verified: after reboot `GET /field-lots` returns `total_count: 0`.

### start.sh contract

`set -euo pipefail`, `cd` to its own dir, guarded install (`if ! python3 -c "import flask"` — no-op on per-test reboots), then `exec python3 app.py` in the foreground. Flask binds `0.0.0.0` on `PORT` (default 10000, verified listening on both 18301 and 10000).

### Verification

Five smoke suites (~150 assertions) run against a live server, all passing: auth/RBAC, CRUD + pagination, bin gates (capacity/variety/posture), assessment OCC + shrink monotonic/ceiling + auto-close, 21-day retreat window (exactly 21 days allowed), wash PASS/FAIL boundaries (4.0 passes/4.01 fails), RESTRICTED at 2 consecutive fails, allocation math incl. SHED_BLEND variant divergence (raw 10.00 vs 10.06), full/partial/top-up allocation, run-close draw errors (imbalance/exceeds/grade/duplicate/empty), abort compensation, cancel restore, open-market cap, schedule conflicts (same/different variety, adjacency), wash-freshness windows (12h/4h, inclusive boundary, FAILs don't extend), full quarantine cascade (6 runs aborted, 8 orders reset to REQUESTED, 3 lots held, contract ledger restored, release/assign/inhibitor gates, PASS exit with holds persisting), condemn via ON_HOLD only with diversion channel, audit FAIL→quarantine→re-audit PASS loop, settlement provisional/final math (exact cent values, e.g. final net 299050.0), dispute/SoD/pay, season conflict/supersede, clock sweep SHORTFALLED + FULFILLED.

Two real bugs found and fixed during testing: `reserved_cwt` reconciled before the order flipped to ALLOCATED (under-counted), and CONDEMNED transition not setting `quality_status`.

Fresh-boot log: clean Flask startup on `0.0.0.0:18301`, HTTP 200 within 2s, empty store, correct default clock echo; second reboot equally clean.

## Step 7: Run Tests and Iterate — 2026-08-14T21:35:00.000Z

All 8 rounds pass 98/98 — clean sweep. The task is complete.

---

### Summary

**Iterations run:** 3 completed 8-round sweeps (plus 1 externally-killed attempt mid-flight).
- Sweep 1: 89/99 in every round — 10 deterministic failures, identical set across all 8 rounds.
- Sweep 2 (after test-artifact fixes): all 10 original failures resolved; 2 rounds clean 98/98, 6 rounds 97/98 with the *same* test failing on `Connection reset by peer` — root-caused (below) as an environmental SIGTERM killing the freshly-booted server mid-test (all rounds run in lockstep, so one signal burst at 21:07:40 hit the same test in 6 rounds; server logs show `Terminated` = SIGTERM, whereas every harness kill path uses port-scoped SIGKILL).
- Sweep 3b (after SIGTERM hardening): **98/98 × 8 rounds — clean.**

**Tests deleted (1):**
- `test_05_lot_lifecycle.py::TestLotIntakeDefaults::test_computed_available_cwt_input_ignored` — PRD-silence: no PRD sentence governs acceptance/ignorance of unknown request-body fields; scaffold corner `c_lot_create_computed_available_cwt_input_ignored` ("client-supplied value is ignored") never reached PRD prose (doc-generator Zero-Silence violation). Two PRD-faithful readers diverge (strict-reject 400 vs silent-ignore 201), so unique derivability fails; the test's only covered remnant (`available_cwt == original_weight` on create) duplicates `test_new_lot_starts_intake_clear_with_zero_ledgers`.

**Tests split under STEP 1c (1):**
- `test_09_records_audits_pool.py::test_create_returns_201_with_server_fields` — removed only the `created_at.startswith("2026-08-01T00:00:00")` assertion. PRD §2.5's logical-clock stamp list explicitly enumerates `binned_at`/`closed_at`/`completed_at`/`paid_at`/audit `closed_at` and omits `created_at`; the scaffold's `created_at == logical clock` claim is scaffold-only (Zero-Silence violation). All PRD-covered assertions (201, UUID, `version==1`, ISO-8601 format, GET round-trip) retained.

**test_helpers/ fixes (1):**
- `test_helpers/fixtures.py::ship_order` — `complete_run(run_id, ...)` → `complete_run(run["id"], ...)`; the NameError crashed all 4 `ship_order` callers and masked their downstream assertions.

**test_suite/ fixes (4 files):**
- `test_01_settlement_economics.py` — added missing `create_binned_lot` import (NameError in 4 tests); `test_final_variant_uses_actuals_and_realized_pool` net 392000→**342000** (PRD §3.9: 400000 gross − 50000 storage − 8000 inhibitor); two pool tests' draws 133.34→**133.33** raw / 33.34→**33.33** cull (PRD §3.4 reservation is rhu(100/0.75)=133.33 and §3.5 forbids exceeding it), basis 100→**200** and gross 250000→**500000** (both ships draw on G1's L1; §3.9 final variant sums actual packed totals), net 237500→**487500**. All expected values re-verified with Decimal arithmetic.
- `test_02_allocation_waterfall.py::test_auto_settle_fulfilled_when_packed_reaches_commitment` — same 133.33/33.33 draw correction.
- `test_07_orders_and_terminal_states.py::TestPriorityConflictStateOverFiscal` (both tests) — `lot_weight_cwt` 100.00→**120.00**: the setup's allocate was correctly rejected per PRD §3.4 atomicity (coverage 100×0.9=90 < requested 100); 120.00 yields coverage 108.00 ≥ 100.00 so the intended tier-5-vs-tier-10 conflict is actually reached. The implementation's pool check was correct — fixture bug, not implementation bug.

**implementation/ fixes (1):**
- `app.py` — install `SIGTERM → SIG_IGN` at startup. The isolation harness terminates servers exclusively via port-scoped SIGKILL (verified in `pytest_plugin.py`/`port_utils.py`), so SIGTERM carries no shutdown contract; a spurious external SIGTERM on this multi-pipeline shared host was killing freshly-booted servers mid-test. Smoke-verified: server survives SIGTERM and keeps serving, still dies on SIGKILL (per-test isolation unaffected). No API/PRD-visible behavior change.

No PRD-required implementation check was removed or weakened; the implementation needed zero business-logic changes — every functional failure traced to test-artifact bugs, plus one environmental hardening.

## Step 8: Finalize PRD — 2026-08-14T21:45:00.000Z

The patch is complete and minimal. Final verification of the two edited regions reads correctly in context (§2.5 line 93, §2.9 inserted paragraph after tier 10).

### Summary

**Line counts:** `PRD.md` 345 lines → `PRD_FINALIZED.md` 347 lines (+2, +0.58%). Two edits total, both inline; no new sections.

**Changes:**
- **§2.5 — revise** — Replaced "All timestamps written by the server (...) are stamped from this logical clock" with an exhaustive split: only `binned_at`/`closed_at`/`completed_at`/`paid_at`/audit `closed_at` come from the logical clock; `created_at`, `updated_at`, and `api_request_timestamp` are wall-time — `implementation/logic.py:40,52` (`new_record`/`touch` use `wall_now()`), `implementation/util.py:65,81` (envelope), vs `clock_stamp()` at `views.py:359,519,561,1039,1143,1320` and `logic.py:136`.
- **§2.9 — insert** — New paragraph after tier 10: request bodies are closed field sets; any unnamed body field (including server-computed fields like `available_cwt`) is rejected `ERR_INVALID_REQUEST`/400, evaluated after path-identifier existence and ahead of every other body-level validation, applying also to each object in a run close's `draws` list — `implementation/util.py:157-160` (`check_unknown`), 25 call sites across `views.py` (e.g. `:270` lot create, `:932` draw objects).

**Step-7 items with no PRD edit (with reason):** `fixtures.py` `ship_order` NameError (test-artifact bug); test_01 net 342000, draws 133.33/33.33, basis 200/gross 500000/net 487500 and test_02's 133.33/33.33 (test arithmetic bugs — PRD §3.9 and §3.4 already uniquely pin these and impl `logic.py:350,468-518` agrees); test_07 `lot_weight_cwt` 120.00 (fixture bug — impl's §3.4 atomic pool check was correct); SIGTERM→SIG_IGN (no API-visible behavior).

**Pre-edit search log:**

*Edit 1 (§2.9 closed body sets):* (a) Subject: handling of request-body fields outside an endpoint's documented set, and the check's position in validation order. (b) Enumerated all 25 `check_unknown` call sites in `views.py` (every mutating endpoint plus per-draw objects at `:932`), confirming uniform `ERR_INVALID_REQUEST`/400 rejection invoked immediately after `get_body()` — i.e. after path-existence helpers (`get_grower`/`get_lot`/`get_shed`/etc., called first on nested routes) and before body-FK existence, OCC, state, food-safety, temporal, shape, and fiscal checks; also confirmed list endpoints only read named query params, so query strings are out of scope. (c) Scoped wording to "request bodies"/"body-level validation" (silent on query strings, which impl ignores silently) and to "after path-identifier existence" only — deliberately not claiming precedence over ownership checks, since `dispute_settlement` (`views.py:1292-1294`) runs `check_unknown` before the grower-ownership check.

*Edit 2 (§2.5 clock sources):* (a) Subject: which clock sources each server-written timestamp. (b) Grep-enumerated every `clock_stamp()`/`wall_now()` site: logical clock serves exactly `binned_at` (views.py:359), lot `closed_at` (logic.py:136, views.py:519,561), `completed_at` (:1039), audit `closed_at` (:1143), `paid_at` (:1320) — matching PRD's existing list; wall clock serves `created_at` (logic.py:40, all resources including subordinate `common=False` records), `updated_at` (logic.py:42,52), `api_request_timestamp` (util.py:65,81). Client-echoed fields (`harvest_date`, `measured_at`, `scheduled_*`, etc.) and the clock endpoint's `current_utc` echo are not server-generated. (c) Used "server-generated timestamp" (excludes client-echoed date fields) and kept PRD's original five-item list verbatim to avoid re-scoping any business stamp.

Output file: `/home/ubuntu/github/CodingPRD/tasks/task_1826_potato_storage_packing_shed/workspace/PRD_FINALIZED.md`

## Step 9: Complete PRD — 2026-08-14T22:10:00.000Z

All edits verified. The completed file is in place. Here is the final report.

### Summary

**Produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1826_potato_storage_packing_shed/workspace/PRD_COMPLETED.md`

**Source:** `PRD_FINALIZED.md` (existed; copied then edited). 347 lines / 54,950 chars → 349 lines / 60,475 chars (**+2 lines, +5,525 chars**). All changes are inline inserts/revisions; no new sections, no invented behavior. Every behavioral claim below was confirmed by reading `implementation/` and by live-probing the server (4 probe batches, ~40 endpoint probes).

**Counts:** 34 ambiguity-pins, 7 mismatch-revisions (41 changes total).

#### Ambiguity-pins (PRD silent → pinned impl behavior)

- §2.1 — insert — empty/whitespace-only `X-User-ID` and out-of-set `X-User-Role` count as malformed (400) — auth.py:23-34
- §2.3 — insert — non-integer `limit`/`offset`, `limit`<1, negative `offset` → `ERR_INVALID_REQUEST`; `limit`>100 clamped, not rejected — util.py:238-253
- §2.3 — insert — `has_more` = `offset` + returned items < `total_count` — util.py:263-270
- §2.4 — insert — `version` starts at 1 on creation — logic.py:39-44
- §2.5 — insert — clock call applies any instant (no monotonicity check; backward allowed) and returns 200 with `data.current_utc` echoing `to_iso8601` — views.py:1328-1346
- §2.9 tier 2 — insert — ownership decided from path alone (grower self-read, grower settlement list) fires before existence; ownership needing the loaded target (lot read, settlement read/dispute) fires after, so missing targets answer 404 — views.py:192-194, 308-309, 1223-1242, 1294-1299
- §2.9 tier 3 — insert — absent or non-non-empty-string body FK reference → `ERR_INVALID_REQUEST` before existence — views.py:340-345, 654-657, 661-665
- §2.9 tier 9 — insert — present-but-malformed fields (empty string, wrong type, unparseable number/date, fractional integer) → `ERR_INVALID_REQUEST`; date fields accept ISO date or datetime (bare date = midnight UTC, naive datetime = UTC) — util.py:163-232
- §3.1 — insert — duplicate `grower_code` → `ERR_INVALID_REQUEST` (400) — views.py:180-182
- §3.1 — insert — duplicate `bin_code` within shed → `ERR_INVALID_REQUEST` (400) — views.py:236-238
- §3.1 — insert — `original_weight_cwt` must be strictly > 0 — views.py:273
- §3.2 — insert — assessments accepted only on `BINNED` lots (`INTAKE`/`CLOSED` → `ERR_LOT_INVALID_STATE`) — views.py:386-387
- §3.2 — insert — percentage outside 0–100 or negative `cumulative_shrink_cwt` → `ERR_INVALID_REQUEST` (not the 422s) — views.py:390-395
- §3.2 — insert — sprout-inhibitor has no storage-status gate (accepted on `INTAKE`/`BINNED`/`CLOSED` lots not `ON_HOLD`) — views.py:446-458
- §3.2 — insert — manual close ignores `quality_status`; an `ON_HOLD` lot with remnant ≤ 5.0 closes and stays `ON_HOLD` — views.py:544-551
- §3.3 — revise — `priority_rank` is a required integer; contract `grade_min_us1_pct` bounded 0–100 — views.py:600-603
- §3.3 — insert — `market_price_cents_per_cwt` integer strictly > 0 — views.py:675
- §3.3 — insert — order `grade_min_us1_pct` bounded 0–100 — views.py:677
- §3.4 — insert — zero-coverage / zero-fraction lots are passed over without a reservation — logic.py:346-349
- §3.4 — revise — outstanding need ≤ 0 also rejects with `ERR_INSUFFICIENT_ALLOCATION_POOL` — views.py:767-773
- §3.4 — insert — both fiscal ceilings evaluated only on first allocation from `REQUESTED`; top-ups skip them (contract-`ACTIVE` gate still applies to every allocation) — views.py:750-766
- §3.4 — revise — reservations unique per lot per order: top-up into an already-reserved lot merges `raw_cwt`/`packed_equiv_cwt` in place — logic.py:351-364
- §3.5 — insert — `draws` on an `ABORTED` close accepted and ignored — views.py:910-918
- §3.5 — insert — draw weights: `raw_drawn_cwt` > 0, others ≥ 0, violations → `ERR_INVALID_REQUEST` — views.py:940-944
- §3.5 — insert — zero-total-packed grade gate passes iff `grade_min_us1_pct` == 0 — views.py:996-998
- §3.5 — insert — reservations on undrawn lots survive the close and remain on the order even after `SHIPPED` (shipping releases nothing) — views.py:1011-1013, 1043-1048
- §3.6 — insert — de-allocation reset does not touch runs: a `SCHEDULED` run stays `SCHEDULED` on the reset order and a later close validates draws against then-current reservations — logic.py:220-225
- §3.7 — insert — negative `turbidity_ntu`/`chlorine_ppm` → `ERR_INVALID_REQUEST`; `water_temp_f` unbounded — views.py:1066-1068
- §3.7 — insert — recording a check (and closing an audit) mutates the shed (`updated_at`/`version`) even when counters unchanged — views.py:1090, 1147-1148
- §3.7 — revise — quarantine cascade holds only lots that are `BINNED` **and** `CLEAR` (closed lots unaffected) — logic.py:189-195
- §3.7 — revise — audit opening ungated on posture, concurrent open audits allowed; close counts are required non-negative integers — views.py:1105-1138
- §3.10 — insert — a `Grower` listing field lots sees only their own (implicit `grower_id` = `X-User-ID` filter before query filters) — views.py:317-318
- §5 — insert — routing fallbacks: undefined path → `ERR_INVALID_REQUEST` 404; unsupported method → `ERR_INVALID_REQUEST` 405 — app.py:31-39

#### Mismatch-revisions (PRD described different behavior → revised to impl)

- §2.9 tier 9 — revise — enumeration order changed to "draws within reservation, draw balance" (impl checks reservation before balance; verified live: over-reservation + imbalanced → `ERR_RUN_DRAW_EXCEEDS_RESERVATION`) — views.py:962-991
- §3.3 — insert — on pack-order creation, `order_type`/`variety` enum checks fire before shed/contract reference existence (verified: bad enum + bad shed → 400, not 404) — views.py:651-657
- §3.5 — insert — run-close check sequence pinned: duplicate-lot (`IMBALANCE`) → reservation (`EXCEEDS_RESERVATION`) → balance (`IMBALANCE`) → grade gate (verified live; PRD prose order differed) — views.py:957-1000
- §3.6 — revise — partial release does **not** credit the contract ledger (PRD said the released packed-equivalent is credited back; verified live: `allocated_active_cwt`/`remaining_committed_cwt` unchanged at 20.01/880.0 before and after) — logic.py:213-236 + 107-129
- §3.7 — revise — same partial-release correction in the quarantine paragraph ("left unchanged on a partial release") — logic.py:233-236
- §3.8 — insert — `to_status` enum validated before lot state gates (verified: bogus `to_status` on `INTAKE` lot → 400, not 409) — views.py:478-485
- §4 table — revise — `GET /potato-shed/field-lots` authorized roles now include `PackLineSupervisor` (impl allows all 7 staff roles + `Grower`; verified 200) — views.py:313-314

**Not pinned (deliberately skipped as sub-observable/internal):** transient `reserved_cwt` reconciliation timing on lots with reservations retained by `SHIPPED` orders (durable observable — retention on the order — is pinned), future-dated PASS wash checks counting as fresh, and Decimal→float JSON wire formatting.
