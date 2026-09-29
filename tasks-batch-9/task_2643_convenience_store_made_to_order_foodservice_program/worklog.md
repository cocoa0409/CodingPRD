# Worklog — task_2643_convenience_store_made_to_order_foodservice_program

## Step 1: Create task directory — 2026-09-03T23:54:55.354Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2643_convenience_store_made_to_order_foodservice_program` and its `workspace/` subdirectory. Index 2643 was pre-assigned by the orchestrating command; no index allocation scan was performed (other pipelines run concurrently on this host).

## Step 2: Generate scaffold — 2026-09-04T01:31:34.650Z

All three scaffold artifacts are complete and the linter is clean.

**VERDICT block (verbatim, final run):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2643_convenience_store_made_to_order_foodservice_program/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2643_convenience_store_made_to_order_foodservice_program/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2643_convenience_store_made_to_order_foodservice_program/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    58
  §1.1 entities declared:     15
  §1.8 instances scanned:     20
  §1.9 instances scanned:     67
  Calls scanned (§1.8+§1.9):  926

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Deliverables** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2643_convenience_store_made_to_order_foodservice_program/`):
- `SCAFFOLD.yaml` — 2800 lines / 136 KB. §1.0–§1.7 only (no difficulty/corner keys). 15 entities, 7 state machines, 2 OCC concurrency rules, 17 calculations, 40 ordered validations, 58 endpoints, 60 error codes, 7 roles. Profile: `workflow_orchestration` + `pricing_engine`, topology `graph`, shape `parallel`, role model `segregation_of_duties`, consistency `immediate`, difficulty `beyond_expert`.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1800 lines / 105 KB. Single key `scaffold_difficulty_design`; all 9 rule_ids with 2–3 instances each (20 total).
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4773 lines / 275 KB. Single key `scaffold_corner_design`; all 9 guide sections (`entities`, `state_machines`, `calculations`, `validations`, `endpoints`, `errors`, `rbac`, `cross_cutting_complexity_layers`, `consistency_model`), 85 instances = 67 full recipes + 18 `excluded_because` stubs, every stub's `difficulty_instance` verified to exist by name in the difficulty file.

Key findings from this session's work:
- All 60 error ids in §1.6 are now reachable from at least one recipe across the two design files (verified by script; zero uncovered).
- Lint caught 10 real defects, all the same class: pagination fields (`total_count`, `has_more`) captured as `$.data.total_count` on list endpoints whose `output` is an array (`HoldingUnit[]`, `OrderLine[]`, `KitchenTicket[]`). Fixed by dropping those captures and asserting the pagination fields in prose instead — worth remembering, since the linter only resolves `$.data[N].<field>` against array outputs.
- Two self-consistency bugs found by hand-recomputation and fixed: `points_balance` was asserted as 0 after placement even though `POST /orders/{id}/place` credits `points_provisional` to the balance (now 2 / lifetime 2), and one prose line claimed a 403 for `ERR_UNAUTHENTICATED` (a 401 per §1.4 priority 1).

## Step 3: Copy shared files — 2026-09-04T01:31:49.732Z

Copied `./INSTRUCTION.md` to `tasks/task_2643_convenience_store_made_to_order_foodservice_program/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T01:46:36.935Z

PRD generation is complete and verified.

**Output:** `workspace/PRD.md`

- **Final line count: 454 lines**
- **Last section heading: `## 5. Error Code Catalogue`** (line 389); the file terminates on the final error-table row `| ERR_CLOCK_REGRESSION | 422 |` — a completed section, not mid-sentence.
- §4 endpoint table: 58 rows, exactly 4 columns (Method, Path, Description, Authorized Role(s)). §5 error table: 60 rows, exactly 2 columns.
- §2.2 (lines 25–72) diffs byte-identical against `section-2.2-response-structure.md`.

Section map: §1 Introduction; §2 with 11 subsections (2.1 RBAC, 2.2 fixed envelope, 2.3 Pagination, 2.4 Logical Clock and Daypart Authority, 2.5 Money/Points/Arithmetic Precision, 2.6 Identity/Timestamps/Version Semantics, 2.7 Request Validation Order, 2.8 OCC, 2.9 Cascade Discipline, 2.10 Ledger Invariants, 2.11 Segregation of Duties); §3 with 9 workflow subsections (chain config -> loyalty/fuel/promotions -> labor planning -> par-baked production -> waste and daypart transitions -> food safety -> order capture -> order commit -> make line and settlement axis); §4; §5.

Hard Contract reports:

```
Field coverage check:
- entities[].fields: 120 required, 120 present, 0 missing
- endpoints[].request_body: 68 required, 68 present, 0 missing
- endpoints[].query_params: 22 required, 22 present, 0 missing
- supplementary ids/params + readiness output + roles + enum values: 84 required, 84 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 40 checked, 40 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 37 checked, 37 fully expressed, 0 missing
- calculations[]: 17 checked, 17 fully expressed, 0 missing
- validations[] conditions: 40 checked, 40 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 58 checked, 58 expressed, 0 missing
- entities[].fields[] structured content: 120 checked, 120 reconstructible from prose, 0 missing
- sibling-branch symmetry: 10 groups checked, 10 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 914
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Three precision fixes were applied during the Contract 2 walk: §2.7 was rewritten to enumerate the full priority-13-through-40 tie-break sequence by error ID (its earlier prose ordering conflicted with §3.8's narrative order); §3.7 now states that an omitted `modifiers` array defaults to empty; §3.8 now explicitly defers gate-failure precedence to §2.7 rather than to its own presentation order.

One thing to flag for the orchestrator: the scaffold contradicts itself on `Order.points_final` at creation. The entity table gives `default: null` ("null before settlement", stated twice) while the `POST /orders` side_effects say `points_provisional`, `points_final` and `rework_count` are "all 0". The PRD documents **null**, since the `AUTHORIZED -> SETTLED` rule "if `loyalty_account_id` is null: `points_final` = 0" only makes sense if it was not already 0. If the hidden test suite is generated from the endpoint side_effects instead, this is the one place PRD and tests could diverge.

Both `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced.

**Orchestrator verification:** independently confirmed PRD.md is 454 lines, tail ends at the complete `## 5. Error Code Catalogue` table (60 rows, final row `ERR_CLOCK_REGRESSION`), and all 33 headings are present through §5. Not truncated — no regeneration needed. The `points_final` divergence flagged above is left unpatched by design: Step 7's PRD-First protocol will adjudicate it (PRD wins over scaffold-derived test assertions), and Steps 8/9 will pin whatever the implementation adopts.

## Step 5: Generate unit tests — 2026-09-04T03:15:41.380Z

Stage 1 and Stage 2 are complete and audited.

## Output (all at the TASK ROOT, nothing under `workspace/`)

`/home/ubuntu/github/CodingPRD/tasks/task_2643_convenience_store_made_to_order_foodservice_program/`
- `test_helpers/` — 9 modules, 2,423 lines (`types.py`, `api_errors.py`, `constants.py`, `api_client.py` with 58 endpoint methods, `test_users.py`, `factories.py`, `assertions.py`, `fixtures.py`, `__init__.py` barrel)
- `test_suite/` — `conftest.py` + 17 test modules, 5,687 lines, **119 tests**

## Coverage against the two design indices (machine-verified)
- Difficulty (queue A): 20/20 instances, every one with >=2 tests -> 52 tests in `test_01`-`test_09`.
- Corner (queue B): 85 instances, 18 `excluded_because:` stubs skipped, **67/67 non-stub instances covered** -> 67 tests in `test_10`-`test_17` (entities 12, state_machines 11, calculations 10, validations 8, endpoints 6, errors 7, rbac 7, cross_cutting_complexity_layers 5, consistency_model 1).
- Every test carries exactly one `Design:` line; every tag resolves to a real non-stub instance; no untagged, dual-tagged, dangling, or stub-derived tests. Audit script reported `problems: []`.

## Verification run
- `ast.parse` clean on all 27 files; `python3 -m pytest test_suite --collect-only -q` -> **119 tests collected**, matching the audit exactly.
- PRD-citation pass (`/tmp/check_quotes8.py`) over all 18 files in `test_suite/`: `bad: 0` on every file.
- No "scaffold"/design-document wording leaks into any docstring.

## Work completed this session
- `test_16_role_permissions.py` (368 lines, 7 tests): plan endpoints closed to everyone but `StoreManager`; the two SoD comparisons (`logged_by_user_id` on verify, `completed_by_user_id` on reopen, both `ERR_SEGREGATION_OF_DUTIES` 403); `ERR_LOCKOUT_REQUIRES_SAFETY_LEAD` distinguished from `ERR_ROLE_NOT_PERMITTED`; row-level `ERR_ORDER_NOT_OWNED` for the entity-backed `Customer`; terminal-vs-member capture parity with only the loyalty leg differing (0 vs 2 points); and the priority-1-before-3-and-4 ordering (401 despite a bogus path id and a bad enum, 401 for an undeclared role, 403 only once the headers are sound).
- `test_17_layered_workflows_and_atomic_responses.py` (476 lines, 6 tests): both optimistic-concurrency tokens (`ERR_STALE_STORE_VERSION`/`ERR_STALE_BATCH_VERSION` 412, with the 412 proven inert); consecutive-strike reset on verification; `hot_case_slots_used` across bake -> pull -> top-off -> pull -> emptying write-off; filtered pagination that partitions the filtered set; and the single `place` response carrying totals 1297/130/0/1167, 11 points, `expected_ready_at` 11:03:00Z, per-line nets 809/358, the reservation on both sides, and one SANDWICH ticket.
- Earlier in the session I fixed a real `factories.py` bug: the four named menu-item presets forwarded fields explicitly *and* via `**overrides`, so any test overriding `valid_dayparts`/`included_premium_count` raised `TypeError`. Added `_menu_item_variant` (dict merge before the call); three existing call sites now work unchanged and `None`-removal semantics are preserved.

## Assertions dropped as not uniquely PRD-derivable (gaps left as gaps, no weakening)
- Anonymous-order `points_provisional` claims in three calculations/validations recipes (kept in the rbac test, where §3.8's "An anonymous order accrues zero in this variant" plus the 0 initial value make it derivable).
- The temperature-log "SS1.5 declares no PATCH, PUT or DELETE" claim.
- The refund recipe's `production_status == READY`.
- A `GET /_clock` read-back after a rejected regression, and a "rejected request leaves `Store.version` unchanged" claim (the PRD states no atomicity/all-or-nothing rule).
- `limit=101 -> ERR_INVALID_REQUEST 400` in the pagination test: §2.7 step 3 scopes `ERR_INVALID_REQUEST` to *request bodies on write endpoints*, and §2.4 states the 1-100 range without saying what a violation does. Replaced with an offset-past-the-end assertion, which §2.4 does pin down.
- Order-sensitive row assertions in the batch-pagination recipe (`p1_first == b2`, `after_first == b3`): the PRD specifies no ordering for `GET /production-batches`, so those are asserted as set equality plus a no-overlap/no-omission check instead.

**Orchestrator verification:** confirmed `test_helpers/` (10 entries) and `test_suite/` (19 entries) exist at the task root and that `find workspace -maxdepth 2 -name 'test_*' -type d` returns nothing — no stray test directories were written under `workspace/`.

## Step 6: Generate implementation — 2026-09-04T03:15:41.380Z

Final verification complete. The implementation is finished, boots clean from a fresh process, and the smoke servers have been shut down (killed by specific PID/port only — no broad `pkill` was ever used).

## Deliverables

All under `workspace/implementation/` — 15 files, 3118 lines:

| file | lines | role |
|---|---|---|
| `start.sh` (exec bit set) | 10 | reads `$PORT`, guarded pip install, `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=2.0` |
| `app.py` | 71 | `create_app()`, 7 blueprints, error handlers, binds `0.0.0.0` |
| `core.py` | 264 | in-memory `Database`, logical clock, pinned constants, money/date arithmetic |
| `errors.py` | 102 | all 60 error ids -> HTTP status + default messages |
| `apihttp.py` | 273 | envelope, auth (401-then-403), body validators, pagination |
| `serialize.py` | 269 | 15 explicit entity serializers |
| `calc.py` | 687 | all 17 calculations, FEFO, promotion selection, sweeps, cascades |
| `routes_config.py` | 231 | stores, holding units, menu items, modifiers, daypart transitions, readiness, clock |
| `routes_loyalty.py` | 174 | promotion rules, loyalty accounts, points adjustments, fuel transactions |
| `routes_plans.py` | 93 | staffing plans + publish/lock (OCC on store version) |
| `routes_batches.py` | 179 | plan/bake/pull/discard, waste logs |
| `routes_safety.py` | 133 | temperature logs, corrective actions (SoD on verify) |
| `routes_orders.py` | 484 | order lifecycle: lines, place, authorize/settle/refund/release/void/pickup |
| `routes_kitchen.py` | 147 | ticket queue, start/complete/reopen |

## Verification results

- **Route inventory: exactly 58 endpoints**, enumerated from `app.url_map` and matching the SCAFFOLD endpoint list 1:1.
- Every `.py` file passes `ast.parse`.
- **Fresh boot on a clean port** answered `GET /orders` with 200 and the correct envelope (`meta.api_request_id` = `req_` + 20 uppercase-alnum, `api_request_timestamp` `2026-08-01T00:00:00.000Z` = the default logical clock, `limit/offset/total_count/has_more`, `response_type: "array"`).
- **Empty-store proof**: on a fresh process every listable collection returns `total_count: 0`, `data: []` — no seeded, preloaded or hardcoded entity data anywhere. Storage is Python dicts only; no SQLite, no JSON dump, no `/tmp` cache.
- **Second end-to-end scenario** (catering path) all green: catering pickup-window requirement (422 `ERR_PICKUP_WINDOW_REQUIRED`), `ERR_ORDER_MINIMUM_NOT_MET`, service fee floor (subtotal 6000 -> 800bp = 480 -> floored to 500, total 6500), staffing `planned_labor_minutes` 1173 with `peak_multiplier_bp` 11500 (400 txns @ 5000bp LUNCH: ceil(200/18)*60 + ceil(200/45)*60 = 1020, x1.15), OCC 412 `ERR_STALE_STORE_VERSION`, SoD 403 on self-reopen, cyclic ticket DONE->IN_PROGRESS->DONE with `rework_count` 1 and rework cost booked to the store, order version progression 1->11, READY->PICKED_UP inside the pickup window, `ERR_ORDER_NOT_DRAFT` on deleting a placed order's line, `limit=101` -> 400, void of a PICKED_UP order -> 409.
- Two apparent anomalies during the empty-store sweep (403 on `GET /order-lines` and `GET /kitchen-tickets` as ChainAdmin) were checked against SCAFFOLD lines 2313-2330 and 2441-2448: ChainAdmin is deliberately **not** in either endpoint's `roles` list, so the 403s are correct.

I removed the stray `__pycache__` left by the smoke runs; the implementation dir now contains only source. No test-suite or test-helper file was read or referenced — the work came from `PRD.md`, `SCAFFOLD.yaml` and `INSTRUCTION.md` only.

**Note for Step 7:** Step 5 dropped the `limit=101 -> 400` assertion as not uniquely PRD-derivable, while Step 6 implemented it as a 400. Both are self-consistent; the looser test is fine and no action is needed. Step 9 will pin the implementation's choice in PRD_COMPLETED.md.

## Step 7: Test/fix iteration — 2026-09-04

Two 8-round parallel stability sweeps (`--isolation per-test-server`, 119 tests each round).

- Iteration 1: all 8 rounds 112/119 — the same 7 failures in every round (no flakiness).
- Iteration 2: all 8 rounds **119/119**, 0 failed / 0 errors, ~230s per round.

Fixes (no test deleted; no assertion weakened; implementation untouched):
- `test_helpers/fixtures.py` — `seed_points()` expected 201 from `POST /loyalty-accounts/{id}/points-adjustments`. PRD declares no adjustment entity (§2.6 enumerates all 15) and §4 gives 200 for endpoints that modify an existing resource, which is what the endpoint returns (the updated `LoyaltyAccount`). Changed to 200; fixed 5 tests across `test_01` and `test_09`.
- `test_suite/test_02_pricing_pipeline_composition.py` — dropped the trailing `line_discount_cents == 2000` assertion from `test_the_fee_is_added_after_the_discount_and_never_earns_its_own_discount` (partial-coverage split per Step 7 §1c). PRD specifies per-line `line_discount_cents` only for `PCT_PER_LINE`; for `CENTS_OFF` it gives no line allocation rule, so a faithful reader can leave the line figure at its documented 0. The test's own cited sentence (fee after discount, 9491 not 9651) is retained in full.
- `test_suite/test_03_order_and_batch_state_machines.py` — `test_finishing_the_last_ticket_lifts_the_kitchen_axis_without_touching_the_money` claimed its second ticket *after* settling, which §3.9 forbids ("the owning order's `settlement_status` must be `AUTHORIZED`" — the PRD enumerates multi-state allowances explicitly elsewhere and names exactly one state here). Both claims now happen while AUTHORIZED; the settle still precedes both completions, so the test's point (final completion lifts the kitchen axis alone) is unchanged.

## Step 7 (orchestrator record — verbatim subagent summary) — 2026-09-04T03:38:20.000Z

The Step 7 subagent appended its own condensed entry above. Per the skill's worklog contract, the subagent's returned summary is recorded here verbatim, since its context is discarded on exit and this is the only durable trace.

Final sweep is clean. Per-round proof from all 8 `results.$i.json`:

```
results.1.json: passed=119 total=119 failed=0 errors=0 skipped=0 duration=230.4s
results.2.json: passed=119 total=119 failed=0 errors=0 skipped=0 duration=229.9s
results.3.json: passed=119 total=119 failed=0 errors=0 skipped=0 duration=230.4s
results.4.json: passed=119 total=119 failed=0 errors=0 skipped=0 duration=230.4s
results.5.json: passed=119 total=119 failed=0 errors=0 skipped=0 duration=230.5s
results.6.json: passed=119 total=119 failed=0 errors=0 skipped=0 duration=229.9s
results.7.json: passed=119 total=119 failed=0 errors=0 skipped=0 duration=230.2s
results.8.json: passed=119 total=119 failed=0 errors=0 skipped=0 duration=229.9s
```

## Summary

**Iterations run:** 2 (each = 8 concurrent rounds, 119 tests, per-test-server isolation).

Iteration 1: every round 112/119 with the *identical* 7 failures — fully deterministic, zero flakiness, no `Terminated` in the sweep log, so nothing was load-induced.

**Tests deleted:** none. No test failed the STEP 1a coverage check outright.

**Assertion removed under STEP 1c partial-coverage split (1):**
- `test_suite/test_02_pricing_pipeline_composition.py` — `test_the_fee_is_added_after_the_discount_and_never_earns_its_own_discount`: dropped the trailing `after_line["line_discount_cents"] == 2000`. **Silence category: COMPUTED-FIELD / allocation-rule silence.** PRD §3.8 specifies `line_discount_cents` writes only for `PCT_PER_LINE` ("Walking those eligible lines in ascending `created_at` order, each line's `line_discount_cents` is..."); for `CENTS_OFF` it says only "the raw discount is the smaller of the rule's `discount_cents` and the order's `subtotal_gross_cents`" and gives no line-allocation algorithm (under the alternate reading a 2-line `CENTS_OFF` order would be unimplementable), so a faithful reader can leave the line figure at the 0 §3.7 documents. The test's own cited sentence (fee taken after the discount; total 9491 not 9651) is retained in full and still passes. Scaffold rule that drove it: `Difficulty/combinatorial_formula/catering_service_fee_evaluated_after_discount_not_on_gross`.

**Fixes applied to `test_helpers/` (1 file, fixed 5 of the 7 failures):**
- `test_helpers/fixtures.py` — `seed_points()` asserted **201** from `POST /loyalty-accounts/{id}/points-adjustments`. That endpoint creates no resource: PRD §2.6 exhaustively enumerates all 15 persisted types and there is no adjustment record, while §3.2 describes the call purely as counter mutations on the `LoyaltyAccount`, and §4 pins "Endpoints that modify an existing resource ... respond with HTTP 200 and return the updated resource" — which is exactly what the endpoint returns. Changed to **200**. This single fixture bug was masquerading as 5 independent loyalty/settlement failures across `test_01` and `test_09`.

**Fixes applied to `test_suite/` setup (1 test):**
- `test_suite/test_03_order_and_batch_state_machines.py` — `test_finishing_the_last_ticket_lifts_the_kitchen_axis_without_touching_the_money` claimed its BEVERAGE ticket *after* settling, so the implementation correctly returned `ERR_ORDER_NOT_AUTHORIZED`. PRD §3.9: "The owning order's `settlement_status` must be `AUTHORIZED`" — the PRD enumerates multi-state allowances explicitly everywhere else ("must be `PLACED` or `IN_PRODUCTION`", "must be one of `PLACED`, `IN_PRODUCTION`, `ASSEMBLED` or `READY`") and names exactly one state here, so the implementation's check is PRD-required and was not weakened. Both claims now occur while AUTHORIZED; the settle still precedes both completions, preserving the test's point (the final completion lifts the kitchen axis alone with the money axis already SETTLED) and all its assertions.

**Fixes applied to `implementation/`:** none. All 7 failures traced to the test artifact; no PRD-required check was removed or relaxed, no endpoint/field/side-effect was added, and storage remains in-memory only.

**Orchestrator verification:** independently re-read all 8 `results.*.json` files — every one reports `passed=119 total=119 failed=0 errors=0 skipped=0`. `grep -c Terminated workspace/sweep.log` returns 0, confirming no round was reaped (the sweep did run under `setsid`), so the clean result is genuine and not a masked mid-request kill.

**Step 8 gate:** the skip condition does not apply — Step 7 made 1 `test_helpers/` fix and 2 `test_suite/` fixes (one an assertion removal). Although `implementation/` fixes were 0, the assertion removal and the state-gate correction both mark places where PRD prose failed to uniquely determine behavior the implementation had already chosen, which is exactly what Step 8 exists to pin. Step 8 will therefore run.

## Step 8: Finalize PRD — 2026-09-04T03:45:33.235Z

Done. Both edits are in-place revisions; the file's structure is unchanged.

## Line counts
- `PRD.md`: 454 lines; `PRD_FINALIZED.md`: 454 lines — **0.00% line delta** (2 existing lines revised in place, no lines/sections added).

## Changes
- **§3.2 (customer-care adjustments)** — *insert* — pinned that `POST /loyalty-accounts/{id}/points-adjustments` persists no adjustment record and therefore answers **HTTP 200 with the updated `LoyaltyAccount`**, not 201 — `implementation/routes_loyalty.py:127-143` (`return ok(loyalty_account_out(account))`).
- **§3.8 (Discount computation and the cap)** — *revise* — pinned that a `CENTS_OFF` discount is booked on the order only and never allocated to lines (every line's `line_discount_cents` stays 0), and narrowed the "per-line discounts sum to the order's discount" identity to `PCT_PER_LINE` rules — `implementation/calc.py:402-417` (`per_line = []` on the cents-off branch) and `calc.py:457-478` (`amounts.get(line["id"], 0)`).
- **§3.9 (Claiming a ticket)** — *no edit*. The Step 7 test_03 change was a test-setup bug; `routes_kitchen.py:88-89` enforces exactly `settlement_status == "AUTHORIZED"`, which §3.9 already states verbatim, and its ordering behind the production-status check already follows §2.7 (step 11 before step 13).

## Per-edit pre-edit search log

**Edit A — §3.2 points-adjustment response**
- (a) Subject: response status/body of the points-adjustment endpoint and whether an adjustment resource exists.
- (b) Paths enumerated/read: `routes_loyalty.py:127-143` (`adjust_points`, returns `ok(...)`); `apihttp.py:25-31` (`ok` -> 200, `created` -> `ok(data, 201)`); `serialize.py:103-114` (`loyalty_account_out` — the returned body); `core.py:71-85` (`Database.reset` — 15 collections, no adjustments table, matching §2.6's exhaustive list); cross-checked the parallel "non-creating POST" endpoints (`suspend`, `publish`, `lock`, `bake`, `pull`, `discard`, `verify`, `place`, `authorize`, `settle`, `refund`, `release`, `void`, `pickup`, `start`, `complete`, `reopen`) — all `ok(...)` -> 200, while every genuine creator uses `created(...)` -> 201.
- (c) Adjustment: scoped the sentence to this endpoint only ("The adjustment leaves no record of its own behind...") rather than stating any general rule about POST endpoints, so the existing §4 create/modify rule and every other endpoint remain untouched.

**Edit B — §3.8 cents-off line allocation + identity scope**
- (a) Subject: every write of `line_discount_cents` / `line_net_cents`, and the order-level vs per-line discount identity.
- (b) Paths enumerated/grepped (`grep -rn "line_discount_cents\|line_net_cents" implementation/*.py`): `routes_orders.py:185-186` (both 0 at line creation — matches §3.7, left verbatim); `calc.py:457-478` (`apply_promotion`, the only mutator: fills `amounts` only for `PCT_PER_LINE`, including the cap-shaving loop, then writes all lines via `amounts.get(..., 0)` and `net = gross - discount`); `calc.py:402-417` (`raw_discount_for` — cents-off branch returns an empty `per_line`); `routes_orders.py:327-329` (single callsite, invoked on every place including `rule is None`); `serialize.py:246-247` (fields exposed); `calc.py:509-523` / `484-493` (settlement basis and fee use the *order-level* `promo_discount_cents`, so a cents-off order still prices and earns correctly with zero per-line figures); `routes_orders.py:427-465` (void does not touch these fields). Also grepped `PRD_FINALIZED.md` for other statements of the identity — only §2.10's batch/loyalty invariants exist, which are unaffected.
- (c) Adjustment: two wordings were softened/re-scoped rather than made universal — the identity claim was qualified with "Under a per-line-percentage rule" (it is false for cents-off in the impl), and the cents-off clause was written as "booked on the order alone and never allocated" without asserting anything about the no-promotion path or about `line_net_cents`, which the paragraph's existing final sentence (`net = gross - discount`) already covers correctly for all branches.

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` shows exactly 2 changed lines (184 and 282), both in-place revisions of existing paragraphs with no new sections; the file is 454 lines and still ends at the complete §5 error table. Both edits trace to `<step_7_diff>` items, so the hard scope held.

**Step 9 plan (orchestrator decision):** the implementation is 15 files / 3118 lines, which is more than one subagent can exhaustively walk in a single pass without silently skipping coverage (the known failure mode is PRD_COMPLETED.md coming back byte-identical to its source, proving the scan never ran). Step 9 will therefore run as **three sequential file-partitioned passes** over the same output file, each pass owning a disjoint slice of `implementation/`: pass 1 = the global/plumbing layer (`app.py`, `core.py`, `errors.py`, `apihttp.py`, `serialize.py`), pass 2 = `calc.py` + `routes_config.py` + `routes_loyalty.py` + `routes_plans.py`, pass 3 = `routes_batches.py` + `routes_safety.py` + `routes_orders.py` + `routes_kitchen.py`. Pass 1 performs the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 edit `PRD_COMPLETED.md` in place. They must be sequential, not concurrent, because all three write the same file.

## Step 9: Complete PRD — 2026-09-04T04:12:00.000Z

Run as **three sequential file-partitioned passes** over a single `PRD_COMPLETED.md`, per the Step 8 plan above. Final: **454 lines / 110,248 chars** (source `PRD_FINALIZED.md` was 454 lines / 95,473 chars — **+14,775 chars**, 46 source paragraphs revised in place, zero new sections, zero new lines). Total **49 pins/revisions** (13 + 18 + 24 changes across 46 paragraphs; some paragraphs carry edits from more than one pass).

### Pass 1 — global/plumbing layer (`app.py`, `core.py`, `errors.py`, `apihttp.py`, `serialize.py`)
12 ambiguity-pins, 1 mismatch-revision. 454 lines / 95,473 -> 99,749 chars.
- §2.2 — revise — ambiguity — `api_request_id` pinned as `req_` + twenty `A`-`Z`/`0`-`9` chars; `api_request_timestamp` pinned to the logical clock, not wall time — apihttp.py:15-19, core.py:106-108
- §2.2 — revise — **mismatch** — the "2xx with no data -> empty object" claim now excepts 204 deletions, which return no body at all rather than an envelope — routes_orders.py:207
- §2.2 — revise — ambiguity — unrouted path / unsupported method / internal fault answered with the same error envelope carrying `ERR_INVALID_REQUEST` and the framework's own status (404/405/500); trailing slash tolerated — app.py:25,39-61
- §2.3 — revise — ambiguity — empty-string `limit`/`offset` = omitted; non-integer, `limit` <1 or >100, negative `offset` -> `ERR_INVALID_REQUEST` 400, evaluated *after* path-id resolution; `offset` past `total_count` yields an empty page, not an error — apihttp.py:220-253
- §2.3 — revise — ambiguity — `created_at` ties (the norm under a frozen clock) broken by server mint sequence — core.py:263-264
- §2.3 — revise — ambiguity — empty filter value = absent; non-boolean filters are exact unvalidated string matches (unknown value -> empty result, not 400); boolean filters accept `true/1/yes` and `false/0/no` in any case, else 400 — apihttp.py:256-273
- §2.5 — revise — ambiguity — gallon inputs quantized to 3 decimals half-up at capture; the five decimal output fields render as JSON numbers, integral values with no fractional part — core.py:231-244, serialize.py:42-43/94/121/184
- §2.6 — revise — ambiguity — a non-UUID identifier is indistinguishable from an unknown one (yields that resource's 404)
- §2.6 — revise — ambiguity — every datetime other than `created_at`/`updated_at` carries three fractional digits only off a whole second; unset datetimes are JSON `null`; `service_date` is a plain `YYYY-MM-DD` string — core.py:124-132
- §2.6 — revise — ambiguity — `updated_at` also has exactly three fractional digits — serialize.py:11-16
- §2.7 step 3 — revise — ambiguity — absent body read as `{}`; `Content-Type` not inspected; undeclared fields ignored; explicit `null` == absent; non-JSON/non-object body, empty required string, empty non-empty-array all land here; accepted ISO input grammar — apihttp.py:83-214, core.py:135-163
- §3.1 / §3.2 — revise — ambiguity — `valid_dayparts` duplicates collapsed, stored in first-supplied order (not canonical) — apihttp.py:163-179

Pass 1 verified already-pinned (not re-touched by later passes): the full 60-row error-id->HTTP-status table (programmatically diffed against `errors.py`, zero mismatches); auth 401-before-403; envelope shape and list `meta`; pagination defaults 10/0 and the 1..100 range; logical clock default `2026-08-01T00:00:00Z` with nothing reading wall time; money helpers (integer cents, round-half-up on absolute value, basis points over 10000, `ceil_div`); UUID ids, `version` starting at 1 and +1 per mutation, `created_at == updated_at` at creation; all 15 serializers' field sets (only internal `_seq` unexposed; the four append-only types correctly omit `updated_at`/`version`); every domain constant in `core.py`.

### Pass 2 — calculations, config, loyalty/fuel/promotions, plans (`calc.py`, `routes_config.py`, `routes_loyalty.py`, `routes_plans.py`)
15 ambiguity-pins, 3 mismatch-revisions. 99,749 -> 104,332 chars.
- §2.4 — revise — **mismatch** — the daypart cycle `BREAKFAST->LUNCH->DINNER->OVERNIGHT` is *not* enforced; the only two tests are "equals the clock-implied daypart" and "differs from the current one" — routes_config.py:206-208
- §3.2 — revise — **mismatch** — `lifetime_points_earned` does *not* "never decrease"; it moves by the same signed figure as `points_balance` — calc.py:518-521
- §3.2 — revise — **mismatch** — a negative settlement delta is the one path that can *demote* a member's `tier` — calc.py:521
- §2.4 — insert — the clock response is a 200 object envelope whose `data` carries `current_utc` and nothing else — routes_config.py:231
- §2.7 step 6 — insert — all six code-uniqueness checks are exact, case-sensitive, untrimmed string comparisons
- §3.1 — insert — an inverted temp band reports `ERR_INVALID_REQUEST` 400 *before* the path store resolves — routes_config.py:71-76
- §3.1 — insert — `unit_food_cost_cents > base_price_cents` -> `ERR_INVALID_REQUEST`, before the `sku` collision check — routes_config.py:131-137
- §3.1 — insert — the four defaulted menu-item integers must be >= 0; the "0 for par-baked / 0 for made-to-order" statements are descriptive, never cross-checked against `fulfillment_mode` — routes_config.py:124-129
- §3.2 — insert — `email` accepts any non-empty string — routes_loyalty.py:103
- §3.2 — insert — `occurred_at` never compared to the clock; a future-dated fuel sale is accepted and simply falls outside the look-back — routes_loyalty.py:152
- §3.2 — insert — `requires_fuel_gallons` must not be negative — routes_loyalty.py:48-50
- §3.2 — insert — suspend has no state precondition; re-suspending a `SUSPENDED` rule succeeds again with 200 and bumps `version` — routes_loyalty.py:76-82
- §3.6 — insert — the impairment sweep walks batches in the §3.5 daypart-sweep order (`bake_start_at` then `created_at`) — calc.py:241,250
- §3.6 — insert — the reserved-batch partial write-off still appends a `UNIT_IMPAIRED`/`system` waste row and bumps both versions (only `hot_case_slots_used` is spared); a reserved batch already at `remaining_qty` 0 is skipped entirely — calc.py:253-263
- §3.8 — insert — `ERR_BATCH_HOLD_EXPIRED` vs `ERR_INSUFFICIENT_BATCH_QTY` decided by whether a store/item/`HOLDING` batch with enough units exists once the hold clock is set aside — calc.py:353-367
- §3.8 — insert — a candidate whose computed discount is 0 still wins and is recorded as `applied_promotion_id` — calc.py:446-454,474-478
- §3.8 — insert — `promised_ready_at` drops the clock's sub-second part rather than rounding it — calc.py:590-592
- §3.9 — insert — the reservation-to-sale conversion increments the *line's* own `version` as well as the batch's — calc.py:623
- §3.9 — insert — "the reopened ticket's lines" = the same order `MADE_TO_ORDER` lines routed to that ticket's station, since a ticket holds no line reference — calc.py:533-543

Pass 2 verified already-pinned: `price_line`/`recompute_order_subtotal`; `derive_tier` thresholds and inclusivity; `points_from_basis` truncation; `fuel_gallons_30d` closed window with both bounds inclusive; `waste_valuation` dual basis and `append_waste_log`'s `daypart_epoch` copy; `daypart_transition_sweep`; `occupancy_end_for` (bake + hold + 15-min sanitation) and `slot_conflict_exists` strict/strict overlap; `staffing_labor_minutes` in full (400-inclusive peak -> 11500bp, per-station ceil-to-hour, 120-min BREAKFAST term, single half-up after the multiplier, 180-min floor last); `overlapping_window_count` half-open geometry; the per-line-then-sum discount and descending-`created_at` cap scale-back; `promotion_candidates`/`select_promotion` tie-break chain; `assemble_totals` catering fee; `accrue_provisional`/`settle_points` bases and the +50 fuel bonus; `station_prep_seconds`/`station_queue`/`cut_kitchen_tickets`; `ready_gate_holds`; `enter_ready`'s SOLD_OUT + slot/store-version cascade; `enter_assembled`; all seven `inspection_readiness` figures and the three-valued verdict; every config/loyalty endpoint validation; `adjust_points`; the full staffing-plan lifecycle including OCC-before-lock ordering.

### Pass 3 — batches, safety, orders, kitchen (`routes_batches.py`, `routes_safety.py`, `routes_orders.py`, `routes_kitchen.py`)
22 ambiguity-pins, 2 mismatch-revisions. 104,332 -> 110,248 chars.
- §3.4 — revise — **mismatch** — `slot_index` below 1 is a body-shape `ERR_INVALID_REQUEST` 400; only above `slot_count` is `ERR_SLOT_INDEX_OUT_OF_RANGE` 422 — routes_batches.py:32,42
- §3.8 — revise — **mismatch** — "Exactly one staffing plan must exist" -> "At least one" (impl is an `any()` predicate) — routes_orders.py:289-297
- §3.4 — insert — `bake_start_at` never compared to the clock (past allowed); `holding_unit_id` never cross-checked against `store_id` — routes_batches.py:34-46
- §3.4 — insert — `additional_qty` read only after the batch resolves and `HOLDING` is confirmed (a `PLANNED` batch reports `ERR_BATCH_STATE_INVALID`); ignored on a first bake — routes_batches.py:91-99
- §3.5 — insert — all four reason names pass the enum shape check (reserved ones reach the 422); any other string is a 400 — routes_batches.py:21,141,153
- §3.6 — insert — every accepted reading mutates the unit (`last_temp_log_at`), so `version` bumps even for an in-range reading — routes_safety.py:44,55
- §3.6 — insert — "newest-first" is §2.3's ascending order reversed, so `created_at` ties come back in reverse mint order — routes_safety.py:69
- §3.6 — insert — a further out-of-band reading on an already `LOCKED_OUT` unit moves neither posture nor counter and runs no sweep — routes_safety.py:46-57
- §3.6 — insert — the reading's `in_range` is never examined on corrective-action open; multiple actions may target one reading — routes_safety.py:74-90
- §3.7 — insert — a modifier `qty` <= 0 reports `ERR_MODIFIER_LIMIT_EXCEEDED` 422, not 400; the cap is per entry, repeated entries neither merged nor rejected — routes_orders.py:141,169-180
- §3.8 — insert — "carries enough units" is counted net of the same commit's earlier claims — routes_orders.py:257
- §3.8 — insert — single-pass FEFO allocation with a running per-batch tally; a later line uncoverable from the remainder falls to `ERR_INSUFFICIENT_BATCH_QTY` — routes_orders.py:247-274
- §3.8 — insert — the commit bumps **every** line's `version`, par-baked or not — routes_orders.py:337-338
- §3.8 — insert — `PLACED -> ASSEMBLED` at commit adds no version bump of its own — routes_orders.py:346-348, calc.py:631
- §3.9 — insert — the store kitchen-queue returns tickets of every status (`DONE`/`VOIDED` included) unless a `status` filter narrows it — routes_kitchen.py:42-49
- §3.9 — insert — `order_line_id` filter semantics — routes_kitchen.py:63-74
- §3.9 — insert — the ticket's own status is the whole gate on complete; no precondition on the owning order — routes_kitchen.py:99-108
- §3.9 — insert — release applies no channel, money-axis or window-end test; a missing `pickup_window_start` clears the gate — routes_orders.py:414-424
- §3.9 — insert — pickup reads nothing on the money axis, so an all-par-baked order can be handed off while `UNPAID` — routes_orders.py:468-484
- §3.9 — insert — authorize tests settlement status before production status, so a settled+picked-up order reports the settlement failure — routes_orders.py:362-365
- §3.9 — insert x3 — `reason` required but never persisted or exposed, on reopen, refund and void — routes_kitchen.py:124-125, routes_orders.py:393-394, routes_orders.py:430-431
- §3.9 — insert — on void, released lines bump their own `version` while unreserved lines are untouched; `points_provisional` is left standing, not zeroed; no balance floor applies (`ERR_POINTS_BALANCE_NEGATIVE` never fires on void) — routes_orders.py:444-461

Resolution of the three items handed to pass 3:
- **(a)** `list_kitchen_tickets` resolves `order_line_id` through the *line*, not any ticket field: it looks the line up and keeps tickets whose `order_id` equals that line's order **and** whose `station` equals that line's `station`; an id matching no line yields an empty page, not a 404. Pinned in §3.9 alongside the explicit statement that a `KitchenTicket` carries no line reference.
- **(b)** Pinned in all three places — reopen, refund and void each require a non-empty `reason` that is discarded once validated, recorded on no resource and exposed nowhere.
- **(c)** Both pinned: the live FEFO (`routes_orders.allocate_batches`) is a single pass with a running per-batch tally, so a batch's usable quantity for a line is `remaining_qty` minus what earlier lines of the same commit already claimed — and the hold-expired/shortfall discrimination rule was amended to count "enough units" net of those claims. `calc.fefo_select`/`fefo_candidates` are dead code and got no PRD text (nothing observable to pin).

**Orchestrator verification:** `cmp PRD_FINALIZED.md PRD_COMPLETED.md` -> differs (the scan genuinely ran; the known failure mode of a byte-identical output did not occur). 46 source lines changed, +14,775 chars, still 454 lines and 28 headings, tail still at the complete §5 table ending `ERR_CLOCK_REGRESSION | 422`. `find test_suite test_helpers implementation -name '*.py' -newer results.1.json` returns nothing — no code was touched after the green sweep, so the 8/8 x 119/119 result still describes the delivered artifact.

## Pipeline complete — 2026-09-04T04:12:00.000Z

All nine steps finished. Final state: 58 endpoints, 119 tests, 8/8 rounds at 119/119 under `--isolation per-test-server`, PRD.md -> PRD_FINALIZED.md -> PRD_COMPLETED.md.
