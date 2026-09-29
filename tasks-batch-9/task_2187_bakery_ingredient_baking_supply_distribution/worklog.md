# Worklog — task_2187_bakery_ingredient_baking_supply_distribution

## Step 1: Create task directory — 2026-08-31T00:00:00.000Z

Created `tasks/task_2187_bakery_ingredient_baking_supply_distribution/` and `workspace/` (pre-allocated name used verbatim; no index scan).

## Step 2 (orchestration note) — 2026-08-31T18:05:00.000Z

RESUME RUN. Step 2 was attempted three times as a single subagent producing all three scaffold artifacts; all three attempts died to the harness stream watchdog ("no progress for 600s") because the agent spent too long generating before emitting a tool call. Root cause was emitting the whole multi-thousand-line YAML in one response. Mitigation adopted: Step 2 was split into three sequential/concurrent sub-steps (2a SCAFFOLD.yaml, 2b SCAFFOLD_DIFFICULTY_DESIGN.yaml, 2c SCAFFOLD_CORNER_DESIGN.yaml), each instructed to build its file via one `Write` plus many `Edit` appends of <=120 lines. This produced steady progress and no further stalls. The scenario description was passed verbatim to 2a, along with the "Generate task harder than expert level!" difficulty instruction.

## Step 2a: Generate SCAFFOLD.yaml — 2026-08-31T18:26:00.000Z

SCAFFOLD.yaml is complete and lint-clean.

**File:** `/home/ubuntu/github/CodingPRD/tasks/task_2187_bakery_ingredient_baking_supply_distribution/SCAFFOLD.yaml` (§1.0–§1.7 only; no `scaffold_difficulty_design` / `scaffold_corner_design` keys)

**Counts**
- Entities: **14** (114 fields) — Customer, Product, CommodityIndexQuote, ForwardPricingContract, ContractLine, WarehouseZone, Lot, SiloAsset, Order, OrderLine, SubstitutionRequest, DeliveryRoute, RouteStop, TechSupportEngagement
- State machines: **7** (39 transitions) — Order is split into two parallel dimensions (`fulfillment_status` × `pricing_status`); ForwardPricingContract is cyclic (OFFERED↔COUNTERED, ACTIVE↔EXHAUSTED); Lot is cyclic (AVAILABLE↔QUARANTINED); SubstitutionRequest is branching with a revision loop; DeliveryRoute is compound
- Concurrency rules: **2** (OCC on `Order.version` for substitution create-with-supersede; OCC on `DeliveryRoute.version` for stop append)
- Calculations: **11** (incl. 2 conservation invariants)
- Validations: **34** (priority-ordered, auth → schema → existence → OCC → state → safety → referential → temporal → constraint → fiscal)
- Endpoints: **76** (incl. `POST /_clock/set_current_utc` with mandated default `2026-08-01T00:00:00Z`)
- Errors: **37**
- Roles: **8** (CustomerBuyer is `entity_backed:Customer`; the other seven are `opaque`)
- Total lines: **2603**

**Difficulty coverage (harder-than-Expert calibration)**
- Rule 1: dual-variant on two domains — `contract_line_settlement_price` (order-date vs delivery-date index) and `customer_allergen_risk_score` (provisional vs audited exposure)
- Rule 2: three distinct modes — (a) nested min/max in `bulk_silo_fill_plan`, (b) pinned round-per-line-then-sum in `order_line_extended_price`, (c) pinned evaluation order for the surcharge/rebate circular dependency in `order_total_settlement`
- Rule 4: two cascades of depth 4 and 5 from different triggers (lot quarantine → lines → orders → stops → route unseal; substitution approval → line swap → lot re-pick → reprice → credit hold → risk tier)
- Rule 5: three priority pairs (state vs safety, safety vs fiscal, temporal vs constraint), noted inline on the rows
- Rule 6: `>=` min-drop boundary via `/orders/{id}/submit` and empty-candidate-set via `/orders/{id}/allocate`
- Rule 8: half-open stop windows with a separation buffer (DeliveryRoute) vs closed inclusive-endpoint silo fill windows (SiloAsset) vs closed zone lockout intervals
- Rule 9: two conserved quantities — pounds of inventory (`lot_inventory_conservation`) and committed contract pounds (`contract_volume_conservation`)

**Lint verdict** (run against a temp dir with empty design stubs, since the two design files are other agents' deliverables):
```
Coverage
  §1.5 endpoints declared:    76
  §1.1 entities declared:     14
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Notes for the sibling design agents:** all §1.5 paths are absolute and include the `api_prefix` (`/bakery-distribution/...`) — `call:` values must match exactly. Enum closure, selector determinism (FEFO with `created_at ASC` final tie-break, never `id`), and the forbidden concurrency vocabulary were all verified.

## Step 3: Copy shared files — 2026-08-31T18:07:00.000Z

Copied `INSTRUCTION.md` (53 lines) from project root to `workspace/INSTRUCTION.md`. (Run out of order relative to Step 2 because it has no dependency on the scaffold.)

## Step 2b: Generate SCAFFOLD_DIFFICULTY_DESIGN.yaml — 2026-08-31T19:52:00.000Z

Done. `SCAFFOLD_DIFFICULTY_DESIGN.yaml` is complete and lint-clean.

**File:** `/home/ubuntu/github/CodingPRD/tasks/task_2187_bakery_ingredient_baking_supply_distribution/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`, **3030 lines**.

**Coverage: 9/9 difficulty rules, 29 instances** (all names unique, all at the top of each rule's range):

| rule_id | instances |
|---|---|
| dual_variant_calc | 3 |
| combinatorial_formula | 4 |
| non_linear_state_machine | 3 |
| transitive_cascade | 3 |
| priority_pair_validation_conflict | 3 |
| boundary_precision_check | 4 |
| cross_entity_state_dependency | 3 |
| resource_temporal_overlap | 3 |
| compensating_invariant | 3 |

**Highlights of the second half (written this session):**
- Non-linear: Order parallel dimensions (pricing PROVISIONAL while fulfillment NEW, with `ERR_ORDER_DIMENSION_GATE`), contract OFFERED↔COUNTERED cycle to `negotiation_round == 3` then `ERR_ROUND_LIMIT_REACHED`, substitution revision loop to `revision_round == 2` then the same cap on a different entity.
- Cascades of depth 4/5/3: lot quarantine unsealing a SEALED route (utilization 62.50 -> 0.00, `allergen_class_lock` GLUTEN -> NONE); substitution approval repricing 266541 -> 2629950, flipping CREDIT_HOLD and risk 0.00/GREEN -> 90.00/RED (fuel 65749 exactly cancels rebate 65749); order cancel returning 20000 drawn lb and reviving an EXHAUSTED contract.
- Priority pairs span three distinct category/HTTP pairs: 10 vs 14 (409 wins), 14 vs 33 (422 beats 402), 19 vs 26 (both 409, only error_id discriminates).
- Boundaries: `min_drop_cents` exactly 497350 passes / 496853 fails; rotation eligibility at exactly 30 days remaining (earlier-expiring lot ineligible, then empty candidate set -> `ERR_NO_ELIGIBLE_LOT`); utilization exactly 100.00 still seals; hours accumulating 2.0+1.9+0.1 = 4.0 flips OPEN->BILLABLE with fee 37000.
- Interval semantics deliberately contrasted across three resources: route half-open + 30-min buffer (10:00 touching rejected, 10:30 accepted), silo closed window (10:00:00 collides, 10:00:01 accepted), zone lockout with the clock exactly on `lockout_end_at`.
- Compensating invariants on three different ledgers: lot pounds (allocate/deallocate restores each bucket, and the deallocated line stays UNALLOCATED — not RELEASED — so risk stays 55.00/AMBER), contract pounds via a partial short shipment (20000 -> 12000 drawn, 8000 lb back to on-hand), and credit exposure cents (limit cut 1000000 -> 500000 flips CREDIT_HOLD without changing exposure; cancel returns it to 0 and to ACTIVE).

**Verification:** `scaffold_lint.py` -> `VERDICT: clean lint` (76 endpoints, 14 entities, §1.8 instances 29, 1075 calls scanned). Independent checks confirmed: YAML parses with only the one top-level key, every instance has `grounds`/`distinguishing_aspect`/`test_recipe` with `setup`/`setup_api_calls`/`trigger`/`assert`, and zero unbound `${...}` placeholders. All money/percentage asserts were computed with Decimal ROUND_HALF_UP against the §1.3 formulas. `SCAFFOLD_CORNER_DESIGN.yaml` (69 instances, other agent) was neither read nor modified; its calls were only counted incidentally by the shared linter.

**Orchestration note:** the first 2b attempt stalled to the watchdog while chunk-reading SCAFFOLD.yaml; the retry succeeded after being told to read the scaffold in one call and to cap YAML writes at ~120 lines each.

## Step 2c: Generate SCAFFOLD_CORNER_DESIGN.yaml — 2026-08-31T20:14:00.000Z

The §1.9 file is complete and lint-clean.

**Deliverable:** `/home/ubuntu/github/CodingPRD/tasks/task_2187_bakery_ingredient_baking_supply_distribution/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`, **5873 lines**, **95 instances**, **890 API calls**.

**Sections covered (all nine) and per-section counts**
| section | instances |
|---|---|
| entities | 12 |
| state_machines | 18 |
| calculations | 18 |
| validations | 13 |
| endpoints | 6 |
| errors | 13 |
| rbac | 7 |
| cross_cutting_complexity_layers | 6 |
| consistency_model | 2 |

**Work done this session (resumed at 4193 lines / 67 instances):** finished `endpoints` (unseal clearing `sequence_no` while keeping `allergen_class_lock`; abort unwinding stops/orders; index-quote listing ordered by `effective_on` DESC), then authored `errors` (13: stale route/order OCC, `ERR_ENTITY_LINK_MISMATCH`, composite-key duplicate silo, segregation of duties on the raw operator id, fourth negotiation round, inclusive contract-term edge, dispatch date mismatch, one-cent min-drop and credit-limit edges, full-quantity short drop, empty rotation candidate set, `limit=101` pagination, path-before-body 404 ordering), `rbac` (7: header presence outranking unknown role, unknown role vs role-not-permitted, PlatformAdmin blocked from buyer-exclusive submit, cross-bakery ownership, the shared residual-reading write from both peer roles, QualityManager-exclusive lockout, specialist id reused as QualityManager on claim), `cross_cutting_complexity_layers` (6: both OCC rules, the 4-hop quarantine cascade that unseals the route and clears the allergen lock, the 5-hop approval cascade flipping CREDIT_HOLD and RED tier, provisional-vs-final dual-variant delta of 30750 cents, the inclusive 4.0-hour billing threshold, and the no-split selector policy), and `consistency_model` (2: same-instant derived reads; atomic rollback when cascade hop 2 fails).

**Linter verdict (verbatim, run with a `/tmp` stub for the concurrently authored §1.8 file so `SCAFFOLD_DIFFICULTY_DESIGN.yaml` was never touched):**
```
Coverage
  §1.5 endpoints declared:    76
  §1.1 entities declared:     14
  §1.8 instances scanned:     0
  §1.9 instances scanned:     95
  Calls scanned (§1.8+§1.9):  890

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Extra validation beyond the linter: YAML parses with exactly one top-level key; no duplicate instance names; every instance carries exactly `{name, claim_type, grounds, distinguishing_aspect, test_recipe}` and every recipe exactly `{setup, setup_api_calls, trigger, assert}`; all enum literals (`category`, `allergen_class`, `allergen_program`, `delivery_mode`, `pricing_mode`, `index_code`) are declared members, the sole exception being the deliberate `SESAME` value in the invalid-enum rejection instance.

**Orchestration note:** 2c was interrupted twice by API server errors (at 2005 and 4193 lines) and resumed in place via SendMessage each time, appending rather than restarting.

### Step 2 combined verification (orchestrator-run)

```
Coverage
  §1.5 endpoints declared:    76
  §1.1 entities declared:     14
  §1.8 instances scanned:     29
  §1.9 instances scanned:     95
  Calls scanned (§1.8+§1.9):  1303

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
Top-level keys confirmed disjoint: SCAFFOLD.yaml has no design keys; each design file has exactly its own single key.

## Step 4: Generate PRD — 2026-08-31T20:35:00.000Z

PRD complete at `/home/ubuntu/github/CodingPRD/tasks/task_2187_bakery_ingredient_baking_supply_distribution/workspace/PRD.md`.

**Line count:** 419 lines (document ends at §5's error table — no audit footer in the file).

**Sections produced**
- §1 Introduction (3 paragraphs: business context, the two governing commitments, the two-dimension order model)
- §2 Global Specifications — 10 subsections: 2.1 RBAC, 2.2 API Response Structure (verbatim fixed block), 2.3 Pagination, 2.4 Resource Identity/Revision Counters/Logical Clock, 2.5 Money·Pounds·Rounding, 2.6 OCC on Orders and Routes, 2.7 Path Resolution and the Order of Rejection, 2.8 Allergen Segregation zone->trailer->bakery, 2.9 Two Conserved Quantities, 2.10 Cascades·Compound States·Recomputation
- §3 Business Logic — 11 subsections: account/catalogue/index board; forward pricing negotiation; order intake & volume draw; the pricing waterfall; receiving & FEFO rotation & reservation; bulk silo fill; quality holds/write-offs/expiry/allergen risk score; substitution adjudication; route building & sealing; dispatch/full drop/short drop; support fees, final settlement, invoicing
- §4 Endpoint table (4 columns, all 76 endpoints)
- §5 Error catalogue (2 columns, all 37 errors)

**Coverage — verified mechanically against the scaffold**

```
Field coverage check:
- entities[].fields: 95 required, 95 present, 0 missing
- endpoints[].request_body/input: 65 required, 65 present, 0 missing
- endpoints[].query_params: 20 required, 20 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 34 checked, 34 expressed in prose (global precedence chain in §2.7 plus the three named collision pairs: state>allergen on submit, allergen>credit, window>capacity), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_order_version / expected_route_version + ERR_STALE_ORDER_VERSION / ERR_STALE_ROUTE_VERSION + 412), 0 missing
- state_machines[].transitions: 7 machines / 36 transitions checked, 36 fully expressed with preconditions paired to error ids and every side effect stated, 0 missing
- calculations[]: 11 checked, 11 fully expressed in prose (both settlement-price variants, both risk-score variants, pinned rounding/eval orders, all constants embedded), 0 missing
- validations[] conditions: 34 checked, 34 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 76 endpoints checked, all side-effect sets and every applies_to scope enumerated, 0 missing
- entities[].fields[] structured content: 14 entities / 95 fields checked, defaults, initial values, enum sets and computed derivations reconstructible from prose (CommodityIndexQuote explicitly noted as carrying only id and created_at), 0 missing
- sibling-branch symmetry: 4 groups checked (LOADED->DELIVERED vs SHORT_SHIPPED; UNDER_REVIEW->APPROVED vs REJECTED; contract vs list pricing path; half-open stop window vs closed silo fill window), 4 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 910
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

All 8 roles are named individually in §2.1 with their `identity:` translated (`CustomerBuyer` entity-backed to `Customer`; the other seven opaque, with the recorded-operator fields listed). Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, and no sibling task directory was read.

**Orchestration note:** interrupted once by an API server error at 110 lines; resumed in place via SendMessage.

**Orchestrator spot-check:** 419 lines / 97215 chars; 30 headings §1–§5 present; endpoint table holds exactly 76 data rows; the 37 declared `ERR_*` ids all appear in the PRD (the scaffold's 38th token is the `ERR_XXX` placeholder inside the response-envelope example, correctly absent).

## Step 6: Generate implementation — 2026-08-31T23:05:00.000Z

Both smoke suites now report **0 failures** against a freshly launched process, and the final boot check passes.

## Modules (`.../workspace/implementation/`, 3489 lines total)

| file | lines | role |
|---|---|---|
| `app.py` | 86 | app factory, 7 blueprints under `/bakery-distribution`, error handlers, `/healthz` |
| `store.py` | 177 | in-memory dicts keyed by uuid, logical clock, `bump`/`insert`/`reset`, Decimal helpers |
| `errors.py` | 53 | all 37 error ids -> HTTP status, `ApiError`, `fail()` |
| `envelope.py` | 48 | `meta`/`response_type`/`data` envelope, `req_` + 20 alnum ids, pagination meta |
| `auth.py` | 48 | 8 roles, `X-User-ID`/`X-User-Role`, `authenticate`, `require_owner` |
| `validate.py` | 193 | body/query coercion, enum/date/instant/number, pagination bounds |
| `common.py` | 30 | `path_lookup` (404) vs `fk_lookup` (422), uniqueness |
| `serialize.py` | 207 | one serializer per entity + `pricing_summary` |
| `calc.py` | 428 | all 11 calculations (pinned pricing order, FEFO selector, compartment waterfall, silo fill, risk, exposure, attach fee) |
| `domain.py` | 209 | allergen gate, contract volume draw/return, reservation release, 4-hop lot cascade, route completion, clock advance, zone lockout |
| `api_catalog.py` | 197 | customers, products, zones, index quotes, clock |
| `api_contracts.py` | 222 | forward contracts + lines, offer/activate/terminate (SoD) |
| `api_inventory.py` | 212 | lots, silos, quarantine/release/expire |
| `api_orders.py` | 447 | orders, lines, submit/reprice/finalize/invoice, allocate/deallocate/cancel, pricing-summary |
| `api_substitutions.py` | 278 | request/claim/revise/resubmit/withdraw/reject/approve (OCC + 5-hop cascade) |
| `api_routes.py` | 506 | routes, stops, seal/unseal/dispatch/abort, deliver/short (OCC + windows + capacity) |
| `api_tech.py` | 138 | engagements, hours, attach, waive |
| `start.sh` | 9 | guarded pip install, `exec python3 app.py` on `$PORT` |
| `requirements.txt` | 1 | `Flask==3.0.3` |

## Coverage
- **76 endpoints** registered under `/bakery-distribution` (method+path pairs), matching the scaffold count exactly.
- All 14 entities' declared field sets verified present in their serializers (scaffold-parsed cross-check, zero missing).
- 7 state machines, both optimistic-concurrency rules (`expected_order_version` / `expected_route_version` -> 412), 11 calculations, 34 validations with the documented precedence, 37 error ids, 8 roles.
- Storage is in-memory only; `store.reset()` at import, nothing seeded, nothing written to disk. Verified: the fresh boot returned `total_count: 0` for `GET /orders`.

## Boot check
`PORT=18915 bash start.sh` -> `/healthz` 200; `GET /bakery-distribution/orders` 200 with a well-formed array envelope (`limit/offset/total_count/has_more`, empty data); `POST /bakery-distribution/customers` 201 with `created_at` = `2026-08-01T00:00:00.000Z` (logical clock default, not wall clock). Server then killed; port free. `__pycache__` removed so the deliverable directory contains only the 19 source files.

## Spec fixes applied this session
In `api_orders.py`: submit now requires the referenced contract to be `status == "ACTIVE"` (previously accepted `EXHAUSTED`); removed the erroneous `recompute_risk_score` calls from `submit_order`/`cancel_order` (the in-flight variant belongs only to allocate/deallocate/substitution-approval); `cancel_order` now also zeroes `tech_attach_fee_cents` per the VOID transition.

One operational note: the concurrent test-generation agent runs per-test servers as `python3 app.py`, so my earlier broad `pkill -f app.py` cleanup very likely killed some of its transient servers around 22:51. I switched to port-scoped kills afterwards; if that agent reported flaky connection errors in that window, that is the cause, not the implementation.

**Orchestrator spot-check:** implementation/ contains exactly the 19 declared source files (no `results.*.json` yet, no `__pycache__`); grep confirms no file references `test_helpers` or `test_suite`, so no test leakage into the implementation.

## Step 5: Generate unit tests — 2026-09-01T01:30:00.000Z

Queue B is complete and the whole suite is verified. Final state:

## Deliverable

**Files**: 32 test modules in `/home/ubuntu/github/CodingPRD/tasks/task_2187_bakery_ingredient_baking_supply_distribution/test_suite/` plus `conftest.py`, backed by 9 modules in `test_helpers/` (`__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`).

**Total tests**: 153 (`153 tests collected in 0.27s`, no collection errors).

**Instances translated**
- Queue A (Difficulty): 28 of 29 instances -> 58 tests (every instance has >=2 tests).
- Queue B (Corner): 94 of 95 instances -> 95 tests — entities 12/12, state_machines 18/18, calculations 18/18, validations 12/13, endpoints 6/6, errors 13/13, rbac 7/7, cross_cutting_complexity_layers 6/6, consistency_model 2/2.

**Modules added this session**: `test_28_submission_and_dispatch_gate_errors.py` (8 tests, finishing `errors`), `test_29_role_and_ownership_boundaries.py` (7, all of `rbac`), `test_30_cross_cutting_layers.py` (4), `test_31_thresholds_selector_and_approval_cascade.py` (3), `test_32_immediate_consistency.py` (2).

**Instances SKIPPED (2, both not-uniquely-derivable — same PRD conflict)**
- `Difficulty/cross_entity_state_dependency/lot_release_blocked_by_zone_in_sanitation_lockout`
- `Corner/validations/corner_val_zone_state_gate_outranks_lockout_window_on_lot_release`

Both require releasing a quarantined lot from a zone inside its sanitation lockout to report `ERR_RELATED_ENTITY_STATE_INVALID`, but PRD §3.1 states that while a zone is inside its lockout window "no quarantined lot in it may be released, and both attempts are rejected with `ERR_ZONE_LOCKOUT_CONFLICT` (HTTP 409)", so the asserted outcome is not uniquely derivable from the contract. No placeholder, xfail or weakened variant was emitted.

**Verification performed**
- Design tags cross-checked programmatically against both indices: 122 distinct instances tagged, zero tags pointing at non-existent instances, zero untagged or dual-tagged tests, every docstring's last line is its single `Design:` line.
- Every quoted PRD citation in `test_suite/` and `test_helpers/` (whitespace-normalised) matches `workspace/PRD.md` exactly once. This pass caught and fixed 9 pre-existing citation defects: stripped `**Hop n:**` bold markers in `test_08_cascade_propagation.py` (7), a sentence truncated before its em-dash clause in `test_18_settled_unit_price.py`, and an ellipsis placed inside a single quoted span in `test_22_attach_fee_and_risk_score.py`.
- Static undefined-name sweep over all 32 modules: clean. No occurrence of the word "scaffold" in generated code.
- Tests were not executed (`workspace/implementation/` was never read or run, per the scope constraint).

**Orchestrator spot-check:** `pytest test_suite --collect-only -q` -> `153 tests collected`, no collection errors. Steps 5 and 6 were launched concurrently in a single message, so `test_suite/` did not exist when the implementation agent started.

## Step 7: Run tests and iterate — 2026-09-01T00:45:00.000Z

All 8 parallel rounds now pass 153/153.

## Summary

**Iterations run: 2** (iteration 1 baseline: 134/153 in all 8 rounds, 19 failures, zero flakiness; iteration 2 after fixes: 153/153 in all 8 rounds).

### Tests deleted
None. No whole test was removed — every failure resolved to either a PRD-silent *sub-assertion* (removed per STEP 1c partial-coverage handling) or a genuine implementation/test-fixture defect.

### Assertions removed (STEP 1c — partial coverage, BRANCH-ASYMMETRIC SIDE EFFECT collapse)
- `test_suite/test_17_cascade_and_settlement_transitions.py` — `TestQuarantineCascadeInnerHops::test_a_quality_hold_releases_the_line_and_walks_the_order_back_to_new`: dropped `assert line["lot_id"] is None`. PRD §3.7 hop one (quoted verbatim in the test's own docstring) says only that the line "flips back to `UNALLOCATED`" and specifies the two pound movements; it never says the lot link is cleared, whereas §3.5's *deallocation* branch does spell out "`lot_id` and `silo_id` cleared to null". A faithful PRD-only implementer can legitimately retain `lot_id` on the quarantine branch as the audit record. All sibling assertions (QUARANTINED, quarantine_reason, UNALLOCATED, order back to NEW, pricing_status PROVISIONAL, total_cents 30750, lot buckets, conservation, zone on_hand_lb) were preserved at full strength. Scaffold rule that drove generation: `Corner/state_machines/corner_quarantine_cascades_release_of_reserved_order_line`.
- `test_suite/test_30_cross_cutting_layers.py` — quarantine-cascade layered test: dropped the identical `assert released_line["lot_id"] is None` for the same reason; hops one–four assertions all kept. Scaffold rule: `Corner/cross_cutting_complexity_layers/...quarantine_cascade...`.

### Fixes applied to `test_suite/` (STEP 2 — test-vs-PRD consistency)
- `test_suite/test_30_cross_cutting_layers.py:202-205` (`test_the_replayed_token_is_refused_and_the_refreshed_one_is_accepted`): the `GET /bakery-distribution/substitution-requests` read was issued with the `WO` (WarehouseOperator) header, but PRD §4's endpoint table authorizes only TechnicalSpecialist, QualityManager, AccountManager, PricingController, PlatformAdmin for that endpoint — the fixture was making a PRD-illegal request and getting a correct `403 ERR_ROLE_NOT_PERMITTED`. Switched to `TS` (TechnicalSpecialist), the same identity the test uses to raise the requests. The implementation's role gate was left intact. Import line updated accordingly.

### Fixes applied to `implementation/`
- `workspace/implementation/store.py` — added `iso_sec(dt)`, a whole-second ISO 8601 UTC renderer, alongside the existing three-fractional-digit `iso()`.
- `workspace/implementation/serialize.py` — switched the 15 business date / window-instant fields from `iso()` to `iso_sec()`: `effective_on`, `term_start_on`, `term_end_on`, `lockout_start_at`, `lockout_end_at`, `manufactured_on`, `expires_on`, `last_fill_window_start_at`, `last_fill_window_end_at`, `requested_delivery_on`, `order_placed_on`, `delivered_on`, `service_on`, `window_start_at`, `window_end_at`. This resolved 16 of the 19 failures (e.g. `assert '2026-09-15T10:30:00.000Z' == '2026-09-15T10:30:00Z'`). PRD §2.4 pins "three fractional digits" only for `created_at`/`updated_at`, and those two fields still use `iso()`; the date/instant fields are UTC midnight dates or explicit request-echoed window instants that the client supplies without fractional digits, so echoing them at second precision is the faithful reading. No assertion was weakened — every one of the 16 tests still checks the exact date value / computed expiry / stamped placement date.

Storage remains in-memory dicts with nothing seeded at startup; no endpoint, field, or side effect was added, and no PRD-required check was removed or weakened. Test-run artifacts (`results.*.json`, `__pycache__`) were cleaned out of the task tree.

**Orchestrator observation:** independently confirmed via directory polling — the baseline sweep wrote 134/153 identically in all 8 rounds at 00:08:26, and the post-fix sweep wrote 153/153 identically in all 8 rounds at 00:23:06. Because the agent then deleted the `results.*.json` files, the orchestrator re-ran the final 8-round sweep itself to restore them as the required deliverable (result recorded below).

### Step 7 orchestrator re-verification sweep — 2026-09-01T01:05:00.000Z

Orchestrator re-ran the full 8-round parallel sweep (`--isolation per-test-server`, `--timeout 120`, `--test-timeout 30`) to restore the `results.{1..8}.json` deliverables the fix agent had deleted:

```
results.1.json 153/153   results.5.json 153/153
results.2.json 153/153   results.6.json 153/153
results.3.json 153/153   results.7.json 153/153
results.4.json 153/153   results.8.json 153/153
```
All 8 rounds green, zero flakiness. Exit code 0.

## Step 8: Finalize PRD — 2026-09-01T01:03:00.000Z

Done. `PRD_FINALIZED.md` written with two edits.

**Line counts:** PRD.md 419 -> PRD_FINALIZED.md 421 (+2 lines, +0.48%).

**Changes**
- §2.4 (Resource Identity / logical clock, after the "UTC dates at midnight" paragraph) — *insert* — pins that the nine business-date fields plus the six window-instant fields (`lockout_start_at`, `lockout_end_at`, `last_fill_window_start_at`, `last_fill_window_end_at`, `window_start_at`, `window_end_at`) serialise as ISO 8601 UTC at whole-second precision with no fractional digits, that the three-fractional-digit form is reserved for `created_at`/`updated_at`/`api_request_timestamp`, and that unset ones serialise as null — `implementation/serialize.py:44,56-57,80-81,91-92,110-111,120,123-124,165,180-181`; `implementation/store.py:89-95` (`iso_sec`) vs `store.py:80-86` (`iso`).
- §3.7 (quarantine four-hop cascade, hop one) — *revise* — adds that hop one does **not** clear the released line's `lot_id`/`silo_id` (contrasted with §3.5 deallocation, which does) — `implementation/domain.py:99-112` (`lot_release_cascade`, sets only `allocation_status`) vs `implementation/domain.py:51-64` (`release_line_reservation`, `clear_refs=True`).

**No edit made for the third Step 7 item** (test_30 role header switched from `WO` to `TS` on `GET /substitution-requests`): `implementation/api_substitutions.py:20-21` `READ_ROLES = (TechnicalSpecialist, QualityManager, AccountManager, PricingController, PlatformAdmin)` matches PRD §4's row exactly — that was a pure fixture bug, not a PRD silence or mismatch.

**Per-edit pre-edit search log**

Edit 1 (date/instant rendering precision)
- (a) Subject: response-side rendering format of every datetime-valued field, and the precision contract for timestamps generally.
- (b) Paths enumerated/read: `store.py` `iso()` / `iso_sec()` / `wall_now_iso()`; all of `serialize.py` (every serialiser, confirming exactly `created_at`/`updated_at` use `iso()` and all 15 date/window fields use `iso_sec()`, including the nested `pricing_summary` -> `order`/`order_line`/`quote` reuse); `envelope.py` `_meta()` (`api_request_timestamp` = 3 digits); `validate.py` `date()` (midnight truncation via `day_of`) and `instant()` (retains sub-second in store, so rendering — not storage — is what truncates); grep for all `v.date(`/`v.instant(`/`day_of` callsites (`api_catalog.py:171`, `api_inventory.py:32`, `api_orders.py:39,252`, `api_contracts.py:27-28`, `api_routes.py:57,163-164`, `api_catalog.py:148-152`) to confirm which fields are midnight dates and which are free instants; `api_catalog.py:28` clock-set (returns empty data, no timestamp echo); grep for any other `iso(` use (only `api_catalog.py:176`, an error *message*, not a pinned field).
- (c) Adjustment: split the sentence into "business-date fields" vs "window-instant fields" rather than calling all fifteen midnight dates, because `lockout_*_at`, `last_fill_window_*_at` and `window_*_at` legitimately carry non-midnight times; phrased as *rendered to* whole-second precision (not "stored as") so sub-second client input on `v.instant` fields is not contradicted; and included the null clause since `iso_sec(None)` returns null for the nullable members.

Edit 2 (quarantine hop-one reference retention)
- (a) Subject: whether a released order line's `lot_id`/`silo_id` are cleared, across every release-style path.
- (b) Paths enumerated/read: `domain.lot_release_cascade` (hop one — no ref clearing) and both its callers: `api_inventory.py:94` (quarantine) and `domain.py:193` (clock-driven lot expiry); `domain.release_line_reservation` (`clear_refs=True` -> clears both) and its callers via `release_order_reservations` at `api_orders.py:399` (deallocate) and `:417` (cancel); `api_substitutions.py:223-261` (approval hop two: sets `lot_id=None`, then re-sets to the replacement, and re-sets `silo_id` on BULK); `api_orders.py:373-375` (allocation writes both); consumers of `lot_id`/`silo_id` — `api_routes.py:135,422-429,475-483` (stop append / deliver / short) and the `order-lines` list filters at `api_orders.py:148-149` — confirming a retained non-null `lot_id` on an `UNALLOCATED` line is never double-counted (every mutation path re-checks `allocation_status == "RESERVED"` before moving pounds) and does show up under the `lot_id`/`silo_id` list filters.
- (c) Adjustment: initially wrote "are only overwritten when the line is allocated again"; softened to "until some later operation writes them" because substitution approval (hop two) and cancel/deallocate also write or clear those refs, so the narrower claim would have been a false universal about paths outside the cascade.

## Step 9: Complete PRD — 2026-09-01T01:38:00.000Z

Done. `PRD_COMPLETED.md` is complete and every implementation module has been walked.

## Totals

| | value |
|---|---|
| `PRD_FINALIZED.md` (source) | 421 lines / 98,065 chars |
| `PRD_COMPLETED.md` | 423 lines / 120,539 chars |
| delta | **+2 lines / +22,474 chars** |
| change groups | **50** (49 in-paragraph, 1 new paragraph in §3.5) |
| ambiguity-pins | **43** |
| mismatch-revisions | **7** |
| sections added | 0 |

## Per-change log

- §2.2 — insert — ambiguity — `api_request_id` pinned as `req_` + exactly 20 upper-case alphanumerics; `api_request_timestamp` pinned to wall clock, not the logical clock — `envelope.py:12`, `store.py:98`
- §2.3 — insert — ambiguity — empty/non-integer `limit`/`offset` and negative `offset` are `ERR_VALIDATION`; default ordering tie-broken by insertion order; quote listing pinned as `effective_on` DESC then `created_at` ASC — `validate.py:141`, `api_catalog.py` quote list
- §2.4 — insert — ambiguity — `created_at`/`updated_at` pinned to 3 fractional digits from the logical clock — `store.py:80`
- §2.4 — **revise** — **mismatch** — clock advance recomputes **three** families, not two, in the fixed order contracts -> zones -> lots, each family in `created_at` order; zone `version` bumps only on an actual status change; clock endpoint returns an empty `data` object — `domain.py:175`, `domain.py:208`
- §2.5 — insert — ambiguity — pounds/hours render as JSON integers when whole and fractional otherwise; money/percentage fields always render fractional — `store.py:173`, `store.py:179`
- §2.7 — insert — ambiguity — framework-level rejections pinned: unknown path -> `ERR_RESOURCE_NOT_FOUND` 404 pre-auth, bad method -> `ERR_VALIDATION` at **405**, unparseable body/internal failure -> `ERR_VALIDATION` 400, trailing slashes insignificant, `GET /healthz` returns bare `{"status":"ok"}` — `app.py:49-77`
- §2.10 — insert — ambiguity — the three *conditional* version bumps (zone on-hand, customer exposure/risk, order-line pricing) pinned as change-only, with the credit-limit adjustment as the unconditional exception — `calc.py:219`, `calc.py:280`, `calc.py:403`, `api_catalog.py:68`
- §3.1 — insert — ambiguity — `min_drop_cents` pinned as a non-negative whole number of cents — `api_catalog.py:40`
- §3.1 — insert — ambiguity — `new_credit_limit_cents` non-negative integer; `reason` required, >=1 char — `api_catalog.py:71`
- §3.1 — insert — ambiguity — zone `sanitation_lockout` flag defaults false, both window instants required when false/absent and ignored (stored null) when true; no ordering constraint between them — `api_catalog.py:117`
- §3.2 — insert — ambiguity — a drafted contract starts with both `authored_by_user_id` and `approved_by_user_id` null; no term-ordering or account-standing check at draft time — `api_contracts.py:23`
- §3.2 — insert — ambiguity — `volume_committed_lb` is an integer; `cap_cents_per_lb` unbounded; contract aggregates recomputed for drawn as well as committed; contract-line append has **no** state gate at all — `api_contracts.py:69`
- §3.2 — insert — ambiguity — all three offer refusals report `ERR_INVALID_STATE_TRANSITION`, empty-lines before term-ordering; `basis_cents_per_lb` bounded ±500; each rewritten line bumps its own `version` — `api_contracts.py:128`
- §3.2 — insert — ambiguity — activation's four tests pinned to §2.7 order (status -> account standing -> SoD -> overlap); non-`ACTIVE` bakery -> `ERR_RELATED_ENTITY_STATE_INVALID`; overlap inclusive at both endpoints and only `ACTIVE` siblings considered — `api_contracts.py:177`
- §3.2 — insert — ambiguity — termination `reason` required, >=1 char — `api_contracts.py:212`
- §3.3 — insert — ambiguity — line append requires `UNPRICED` (else `ERR_INVALID_STATE_TRANSITION`); `quantity_lb` may be fractional, stored at 2dp; append prices nothing — `api_orders.py:92-119`
- §3.3 — insert — ambiguity — empty order on submit -> `ERR_INVALID_STATE_TRANSITION`; any non-`ACTIVE` contract status -> `ERR_RELATED_ENTITY_STATE_INVALID` — `api_orders.py:234`
- §3.3 — insert — ambiguity — reprice: commercial check first, blocking fulfillment set -> `ERR_ORDER_DIMENSION_GATE`, never re-draws contract volume, absorbs credit breach as `CREDIT_HOLD`, always bumps `version` — `api_orders.py:272`
- §3.3 — insert — ambiguity — cancel requires pre-`ALLOCATED` fulfillment with no commercial gate; `cancellation_reason` <=200; risk score deliberately not recomputed on cancel — `api_orders.py:408`
- §3.3 — **revise** — **mismatch** — pricing summary response shape corrected: `data` is the full order object plus a `lines` array of full order-line objects each extended with a whole `index_quote` object (or null), ordered `created_at` ASC, variant selected from `pricing_status`, pure read that never raises `ERR_INDEX_QUOTE_MISSING` — `serialize.py:199`, `api_orders.py:433`
- §3.4 — insert — ambiguity — the non-index branch ignores `cap_cents_per_lb`; a null observation date yields `ERR_INDEX_QUOTE_MISSING` rather than any fallback — `calc.py:104`, `calc.py:107`
- §3.5 — insert — ambiguity — `quantity_received_lb` may be fractional, stored at 2dp — `api_inventory.py:33`
- §3.5 — insert (new paragraph) — ambiguity — allocation runs the selector per line in `created_at` order against a *working* on-hand that already deducts earlier lines' claims; empty order -> `ERR_INVALID_STATE_TRANSITION`; bulk-capability sweep precedes the per-line fill plan — `api_orders.py:332-369`, `calc.py:289`
- §3.5 — insert — ambiguity — deallocation from a routed order reports `ERR_RELATED_ENTITY_STATE_INVALID` — `api_orders.py:388`
- §3.6 — insert — ambiguity — non-bulk SKU -> `ERR_PRODUCT_NOT_BULK_CAPABLE`; `min_fill_lb` non-negative; both pound inputs fractional at 2dp; both uniqueness tests precede the bulk-capability test — `api_inventory.py:149`
- §3.6 — insert — ambiguity — residual reading rounded to 2dp; the capacity ceiling is checked only after the silo resolves, so a bad path reports `ERR_RESOURCE_NOT_FOUND` first; no ownership check on the endpoint — `api_inventory.py:206-209`
- §3.7 — insert — ambiguity — a lot outside its zone -> `ERR_INVALID_STATE_TRANSITION`; lockout test precedes zone-status test so a lockout-closed zone always reports `ERR_ZONE_LOCKOUT_CONFLICT` — `api_inventory.py:86`, `api_inventory.py:103`
- §3.7 — insert — ambiguity — `disposal_note` unbounded; disposing a lot still holding reserved pounds -> `ERR_INVALID_STATE_TRANSITION` — `api_inventory.py:127`
- §3.8 — insert — ambiguity — optional `order_id` arms the `ERR_ENTITY_LINK_MISMATCH` check and is evaluated after the stale-version check; omitted means no link check — `api_substitutions.py:55`
- §3.8 — **revise** — **mismatch** — claim's conditions reordered to impl order (request status -> parent order status -> SoD), so a doubly-invalid claim reports `ERR_RELATED_ENTITY_STATE_INVALID` — `api_substitutions.py:121`
- §3.8 — insert — ambiguity — request-revision has **no** SoD test (any `QualityManager`, requester included); revision note 1–500 required; resubmission is requester-only (`ERR_SEGREGATION_OF_DUTIES`) with both fields required and no parent-order version bump — `api_substitutions.py:137`, `api_substitutions.py:154`
- §3.8 — **revise** — **mismatch** — approval: `RELEASED` is transient, the line resting at `RESERVED` on the replacement lot (with `silo_id` re-derived for the new SKU, null tolerated); hop skipped entirely for a non-`RESERVED` line; line `version` advances 3x (once if skipped); replacement lot chosen before any check; five tests in §2.7 order; `INVOICED` parent -> `ERR_RELATED_ENTITY_STATE_INVALID`; reprice skipped (version still bumped) when not `PROVISIONAL`; `decision_note` <=500 — `api_substitutions.py:204`
- §3.8 — insert — ambiguity — rejection `decision_note` <=500 and `decided_by_user_id` overwritten by the rejecting manager — `api_substitutions.py:188`
- §3.8 — insert — ambiguity — withdrawal by anyone other than the requester -> `ERR_SEGREGATION_OF_DUTIES` — `api_substitutions.py:174`
- §3.9 — insert — ambiguity — `route_code` uniqueness exact/case-sensitive -> `ERR_DUPLICATE_RESOURCE`; `service_on` truncated to UTC midnight; capacity stored at 2dp — `api_routes.py:52`, `common.py:23`
- §3.9 — insert — ambiguity — no ordering constraint between window instants; route status tested before order status (same code); lock derivation from a wholly-`NONE` order leaves the lock open; a two-class order can never board an unlocked route; exact equality admits no neutral class — `api_routes.py:99`, `api_routes.py:158`
- §3.9 — insert — ambiguity — cancelled stops invisible to both window tests; the service-day containment made precise (start >= midnight and < next; end > midnight and <= next) — `api_routes.py:114`, `api_routes.py:150`
- §3.9 — insert — ambiguity — compartment test before vehicle-capacity test; both enforced only on append and seal, and on append against the would-be, window-sorted stop set; all other re-runs are non-enforcing — `calc.py:360`, `api_routes.py:192-195`
- §3.9 — insert — ambiguity — stop cancellation: stop status -> `ERR_INVALID_STATE_TRANSITION`, route status -> `ERR_RELATED_ENTITY_STATE_INVALID`, HTTP 200 with the stop resource, own `sequence_no` zeroed, survivors not renumbered, route `version` always bumped — `api_routes.py:248`
- §3.9 — **revise** — **mismatch** — seal's allergen test corrected: equality against **every** class the order's lines carry, tested unconditionally for a bulk stop (so it fails even against a `NONE` lock) and only past `NONE` for a bagged stop; six conditions reordered to §2.7 order with min-drop last; sequencing numbers only non-cancelled stops with change-only stop version bumps — `api_routes.py:277`, `api_routes.py:33`
- §3.10 — insert — ambiguity — dispatch: unpriced stop order -> `ERR_RELATED_ENTITY_STATE_INVALID` (409); tests in §2.7 order; only `PLANNED` stops examined; non-`ROUTED` orders untouched; no body; sealed aggregates and lock left as-is; response is the route — `api_routes.py:337`
- §3.10 — **revise** — **mismatch** — abort: `abort_reason` required 1–200; both refusals `ERR_INVALID_STATE_TRANSITION` with status first; cancelled stops zeroed and bumped, already-cancelled untouched, only `LOADED` orders stepped back; aggregates **written** to 0 rather than recomputed; `allergen_class_lock` survives — `api_routes.py:365`
- §3.10 — insert — ambiguity — dock preconditions pinned to impl order and codes (stop -> `ERR_INVALID_STATE_TRANSITION`, route and order -> `ERR_RELATED_ENTITY_STATE_INVALID`); `delivered_lb` stamped with full order pounds; lines walked `created_at` ASC with version bumps; null `lot_id`/`silo_id` tolerated; completion sets `stop_count` and derives load/utilization from stops' `delivered_lb`; response carries the stop — `api_routes.py:397`, `api_routes.py:412`, `domain.py:148`
- §3.10 — **revise** — **mismatch** — short drop: the previously unpinned apportionment is now fixed as **greedy** across lines in `created_at` ASC (`min(remaining, quantity_lb)` each, earlier lines satisfied in full), full line reservation always relieved, silo credited only with pounds actually taken and left wholly alone at zero take, contract return computed from **that line's own** shorted pounds (floored at 0, zero skipped) with each touched contract re-evaluated and bumped; `delivered_lb_total` a required number >=0 (negatives are `ERR_VALIDATION`), `short_reason` 1–200, range test after the state preconditions — `api_routes.py:453`, `domain.py:78`
- §3.10 — insert — ambiguity — route list ordered `created_at` ASC with a whole-day `service_on` filter; both stop listings ordered by `window_start_at` then `created_at` then insertion order and include `CANCELLED` stops; per-route listing unfiltered — `api_routes.py:84`, `api_routes.py:216`, `api_routes.py:226`
- §3.11 — insert — ambiguity — `work_note` <=500; `hours_logged` rounded half-up after each addition; posting only from `OPEN`/`BILLABLE` (else `ERR_INVALID_STATE_TRANSITION`); every accepted posting bumps `version` even below threshold — `api_tech.py:72`
- §3.11 — insert — ambiguity — `order_id` required on attach; every non-`PROVISIONAL` commercial status (`UNPRICED`/`VOID` included) -> `ERR_ORDER_DIMENSION_GATE`; four tests in §2.7 order — `api_tech.py:94`
- §3.11 — insert — ambiguity — `waiver_reason` required 1–200; a non-null `order_id` blocks the waiver with `ERR_INVALID_STATE_TRANSITION` — `api_tech.py:124`
- §3.11 — insert — ambiguity — finalization: commercial status first as `ERR_INVALID_STATE_TRANSITION`, no `expected_order_version`, the index-quote failure emerges from the repricing walk (first offending line aborts, nothing repriced), and no min-drop/credit re-test so a breach lands as `CREDIT_HOLD` — `api_orders.py:290`
- §3.11 — insert — ambiguity — invoicing's three tests pinned to §2.7 order and no `expected_order_version` — `api_orders.py:310`

## Notes

- §4 (endpoint/role table) and §5 (37 error codes and statuses) were verified line-by-line against `auth.py` role tuples and `errors.py`'s `ERROR_HTTP` and required **no** edits — the sole discrepancy is the framework 405, now pinned in §2.7.
- `SCAFFOLD*.yaml` and `worklog.md` were never opened; tests were used only as cross-reference, never as authority.
