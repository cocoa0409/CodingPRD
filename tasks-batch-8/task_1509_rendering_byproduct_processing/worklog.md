# Worklog — task_1509_rendering_byproduct_processing

## Step 1: Create Task Directory — 2026-08-13T15:15:00.000Z

Task directory `tasks/task_1509_rendering_byproduct_processing/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher. Step 1 treated as DONE per instructions; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-13T17:13:00.000Z

Done. All three scaffold artifacts generated and lint-clean for the Rendering & Byproduct Processing scenario (Darling Ingredients rendering plant).

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1509_rendering_byproduct_processing/`):
- `SCAFFOLD.yaml` (2,652 lines) — §1.0–§1.7 only (verified: no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (722 lines) — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (1,495 lines) — single top-level key `scaffold_corner_design`

**Counts:**
- Entities: **16** (Plant w/ posture gate, CompliancePermit, Supplier, SupplierAgreement, Vehicle, WashTicket, CollectionRoute, RouteStop, InboundBatch, CookRun, ProductLot, CustomerContract, SalesOrder, PriceIndexEntry, OdorEvent, PeriodSettlement)
- State machines: **14** (cyclic: cook-run recook loop, agreement/contract suspend-reinstate, vehicle sanitation, lot downgrade-regrade, order confirm-deallocate, settlement close-reopen; posture-driven plant gating)
- Calculations: **15** (incl. dual-variant cook yield and pickup fee, mode-(a) index/basis/grade pricing, mode-(b) pinned per-unit rounding, mode-(c) self-inclusive tier projection, odor decay with 600/700 hysteresis, tiered energy straddle, two conservation invariants)
- Validations: **18** priority-ordered rows
- Endpoints: **104** (flat topology under `/rendering`, incl. `POST /_clock/set_current_utc` with pinned default 2026-08-01T00:00:00Z)
- Errors: **70** domain-specific codes
- Roles: **11** (10 operational + Any; segregation-of-duties model with 5 SoD walls: creator≠approver, reporter≠confirmer, screener≠adjudicator, grader≠releaser, closer≠finalizer)
- §1.8 instances: **19** (2 per rule × 9 rules, +1 extra combinatorial_formula instance covering all three modes (a)/(b)/(c)); all formula-derived asserts are pre-computed literals (e.g., fee 58700/50825, variance −1.25%, energy 968000¢ tier straddle, net 4812500 at the inclusive 100k tier boundary)
- §1.9 instances: **73** (70 active + 3 `excluded_because` stubs), covering all nine guide sections
- Concurrency: 3 true-race OCC rules (order-create vs contract, stop-create vs route, agreement amend), all wired per §1.2.1

**Verification:** `scaffold_lint.py` verdict — `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (881 calls scanned, 0 violations). Additionally audited: placeholder closure (zero unbound `${var}`), instance-name uniqueness across both design files (92 unique), banned-concurrency vocabulary absent, every error code referenced, system-enum value closure, role/endpoint consistency, and OCC wiring (parent `common_fields`, required `expected_*_version` input, version-bump side effect). No sibling task directories were inspected.

## Step 3: Copy Shared Files — 2026-08-13T17:15:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1509_rendering_byproduct_processing/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-13T17:48:00.000Z

PRD generation complete. I did not open, grep, or reference `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml` at any point.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1509_rendering_byproduct_processing/workspace/PRD.md` — 473 lines

**Section overview:**
- **§1 Introduction** — 2 paragraphs (business context of rendering operations + the four operational doctrines: posture gate, segregation of duties, mass/money conservation, OCC)
- **§2 Global Specifications** — 11 subsections: 2.1 Roles & headers (all 11 roles with opaque-identity prose), 2.2 Response envelope (verbatim block, confirmed byte-identical to `section-2.2-response-structure.md`), 2.3 Pagination & list filtering (limit default 10/min 1/max 100, offset 0, `created_at` ascending, all per-collection filters), 2.4 Common resource properties (incl. the `common_fields: false` exceptions for WashTicket and PriceIndexEntry), 2.5 Logical clock (startup default `2026-08-01T00:00:00Z`, whole-hour scheduling), 2.6 Units/precision/rounding, 2.7 Plant posture gate, 2.8 OCC (all 3 rules), 2.9 Validation precedence (all 18 priorities, ordered, with priority-13's internal ordering), 2.10 Segregation of duties (all 6 pairs), 2.11 Conservation invariants
- **§3 Business Logic** — 9 subsections organized by business-process timeline: plant onboarding/settlement calendar, permits & odor compliance, suppliers & agreements (incl. amend), fleet & collection logistics, receiving/screening, cook runs (segregation, yields, tiered energy), lots & grading, contracts/index pricing/orders, period close & calendar advancement
- **§4 Endpoint Definitions** — status-code paragraph (201/200 rule incl. collect's 201) + 104-row table with exactly 4 columns
- **§5 Error Code Catalogue** — 70-row table with exactly 2 columns

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 143 required, 143 present, 0 missing
- endpoints[].request_body/input: 104 required, 104 present, 0 missing (incl. to_iso8601, current_utc, decision, expected_grade, override_note, and the three expected_*_version OCC fields)
- endpoints[].query_params: covered (limit/offset plus all 20+ filter names in §2.3), 0 missing
- nested member names batch_id/threshold_lbs/discount_pct/lot_id/quantity_lbs: all present
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 18 checked, 18 expressed in §2.9 with explicit first-match ordering, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (order create + expected_contract_version + ERR_STALE_VERSION/412; stop create + expected_route_version; agreement amend + expected_agreement_version — no race framing), 0 missing
- state_machines[].transitions: 14 machines, all transitions expressed with from/to states, preconditions paired to error IDs, and every side effect (incl. posture cascades, strike cascades, void reversals), 0 missing
- calculations[]: 15 checked, 15 fully expressed in precise prose (coefficients, 150 cents/mile, 12500-cent freight, 500-hour energy tier at 4200/3800, grade tables, hysteresis 600/700, per-line rounding, pinned composition order), 0 missing
- validations[] conditions: all matchable to error IDs in §2.9/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed (incl. stop-create validation scopes, dispatch-time agreement-window recheck, price-time ship-date recheck), 0 missing
- entities[].fields[] structured content: defaults, null-until semantics, and enum domains reconstructible from prose, 0 missing
- sibling-branch symmetry: fats/meals grading, FIXED/INDEX_LINKED, PROVISIONAL/FINAL fees, revoke-from-ACTIVE/SUSPENDED, 4-state terminate branches, downgrade GRADED/RELEASED, void COLLECTED/DELIVERED — all rendered with equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 925
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks: all 70 error IDs, all 11 role names, all 49 state values, and all enum values appear verbatim in backticks; no fuzzy/approximating words anywhere; §2.2 verified byte-identical to the canonical source block.

## Step 5: Generate Unit Tests — 2026-08-13T18:26:00.000Z

All done. The remaining `app.py` processes are root-owned and belong to other concurrent benchmark runs on this shared host — not mine; the runner cleaned up its own servers.

## Summary

Generated complete test infrastructure for `task_1509_rendering_byproduct_processing` and validated it end-to-end against the existing implementation.

### Files written

**`test_helpers/`** (9 files, ~2,300 lines):
- `types.py` — 11 role/status enums + 16 entity TypedDicts; append-only `WashTicket`/`PriceIndexEntry` correctly omit `updated_at`/`version`
- `api_client.py` — `ApiClient(GenericApiClient)` with 71 endpoint methods covering every PRD §4 endpoint including `/_clock/set_current_utc`
- `api_errors.py` — 70 `ApiErrorId` members + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — 16 entity assertions + `assert_batch_mass_conserved` / `assert_settlement_margin_consistency` invariants
- `factories.py`, `constants.py` (species coefficients, energy tiers, odor thresholds, freight/transport rates), `test_users.py` (all 11 roles with multiple operator ids for SoD pairs), `fixtures.py` (composite chains: active agreement/contract, dispatched/collected stops, completed cook runs, released lots, settlements, clock control)
- `__init__.py` barrel export

**`test_suite/`** (14 files: `conftest.py` + 13 test files, 108 tests, ~4,000 lines): `test_01` plants/permits/settlements (10), `test_02` odor/posture (5), `test_03` suppliers/agreements (8), `test_04` fleet/routes (12), `test_05` stops/fees (17), `test_06` batches/cook runs (16), `test_07` lots/order confirmation (7), `test_08` contracts/pricing (12), `test_09` orders/fulfilment (5), `test_10` security/error catalogue (3), `test_11` segregation of duties (6), `test_12` optimistic concurrency (3), `test_13` cascades (4).

### Coverage vs. design indices
- **Queue A (§1.8 difficulty): 19/19 instances emitted, 2 tests each = 38 tests; 0 skipped.** Every instance passed the PRD-first two-condition filter (all asserted rules — dual-variant fees/yields, pinned rounding order, tier self-inclusion, hysteresis boundary, priority-pair winners, cascades, OCC — have verbatim PRD coverage pinning a unique outcome).
- **Queue B (§1.9 corner): 70/70 non-stub instances emitted, 1 test each = 70 tests; 0 skipped.** The 3 `excluded_because:` stubs were not translated; all three `difficulty_instance` pointers verified to resolve (`dispatch_cancelled_route_dirty_vehicle`, `odor_confirm_permit_plant_route_cascade`, `cook_yield_theoretical_vs_actual`).

### Tag integrity
Every one of the 108 test docstrings ends with exactly one `Design: Difficulty/<rule_id>/<instance>` or `Design: Corner/<section>/<instance>` line copied verbatim from the source YAML — verified programmatically (108/108 tags, all resolve, none dual-tagged, none pointing at stubs). Additionally every docstring's quoted PRD citation was grep-verified verbatim against `workspace/PRD.md` (108/108). No `skip`/`skipif`/`xfail` anywhere; no scaffold references in comments.

### Execution validation
Ran the suite with `prd-bench-local-run --isolation per-test-server` against `workspace/implementation`: **108/108 passed** (final run). One test-side defect found and fixed during bring-up (dispatch-priority setup scheduled a stop window on the wrong service date, tripping `ERR_WINDOW_OUTSIDE_ROUTE`); no PRD or implementation changes were needed. A generation note was appended to the task-local `worklog.md`.

## Step 6: Generate Implementation — 2026-08-13T18:26:00.000Z

All 104 declared endpoints are registered (the 105th route is Flask's built-in `/static`). Implementation complete and verified.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1509_rendering_byproduct_processing/workspace/implementation/`):

- `start.sh` — executable launcher; guards `pip install` behind `python3 -c "import flask"`, then `exec python3 app.py` (foreground, `$PORT` default 10000, binds `0.0.0.0`)
- `requirements.txt` — `flask>=2.2`
- `app.py` — Flask entry, blueprint registration, envelope-shaped error handlers (ApiError/404/405/500)
- `db.py` — in-memory stores (16 dicts keyed by id), logical clock (default `2026-08-01T00:00:00Z`), insertion sequence. **No seeding anywhere — store starts empty on every boot**
- `common.py` — `meta`/`response_type`/`data` envelope, `limit`/`offset`/`total_count`/`has_more` pagination (defaults 10/0, min 1, max 100), X-User-ID/X-User-Role auth, schema validators, round-half-up helpers, `stamp_new`/`touch` (created_at/updated_at/version on the logical clock)
- `logic.py` — posture gate, all cascade functions, constants, calculation engines
- `routes_plants.py`, `routes_permits.py` (permits + odor events), `routes_supply.py` (suppliers + agreements + amend OCC), `routes_fleet.py` (vehicles + wash tickets + quarantine), `routes_logistics.py` (routes + stops), `routes_production.py` (batches + cook runs + lots), `routes_sales.py` (contracts + orders + index entries)

**Endpoints:** all 104 from the PRD §4 table implemented and registered.

**State machines:** all 14 implemented with precondition errors and side effects — Plant (posture gate + DECOMMISSIONED terminal), CompliancePermit (incl. auto-suspend at violation threshold, expiry at advance-period), Supplier (3-strike cascade), SupplierAgreement (incl. SoD approval + window overlap + amend OCC), Vehicle (sanitation loop + DEEP-wash quarantine rule), CollectionRoute (dispatch/complete/cancel + auto IN_PROGRESS), RouteStop (8 states incl. VOIDED reversal), InboundBatch (policy-routed screening + SoD adjudication + auto DEPLETED), CookRun (full STAGED→COOKING→SETTLING→PRESSING→COMPLETED + FAILED↔STAGED recook loop), ProductLot (grade/release/downgrade/regrade/reject + auto DEPLETED on shipment drawdown), CustomerContract, SalesOrder (DRAFT→PRICED→CONFIRMED→SHIPPED→INVOICED + deallocate/cancel allocation release), OdorEvent, PeriodSettlement (OPEN/CLOSED/REOPENED/FINALIZED with SoD finalize).

**Calculations:** all 15 from scaffold Table 1.3 — cook_yield (per-line round-half-up, theoretical + variance), pickup_service_fee (PROVISIONAL without discount / FINAL with current-period volume discount), index_linked_unit_price (latest entry ≤ ship date, single rounding), order_amount_composition (pinned evaluation order, freight 12500), tier_selection_projected_volume (order contributes to own tier), odor_score_update (600/700 hysteresis, +50 recovery), vehicle_route_overlap (half-open, adjacency allowed), cooker_capacity_check (aggregate, not per-line), route_capacity_check (equality allowed), energy_cost_tiered (marginal 500h straddle at 4200/3800), grade_determination (inclusive boundaries, OFF_SPEC → REJECTED), contract_spec_check, segregation_compatibility, batch_mass_conservation, settlement_accrual_conservation.

**Boot verification:** `bash start.sh` launched on port 19909, answered requests, restarted multiple times; each fresh boot shows an empty store. Two smoke suites (~100 assertions) passed end-to-end, covering the full pipeline (plant → supplier → agreement → vehicle → route → stop → collect → batch → screen → cook → lots → grade/release → contract → order → price/confirm/ship/invoice → settlement close/advance), plus posture gates, SoD rejections, OCC 412s, cascades, energy tier straddle, index-linked pricing, and yield-override. Two real bugs found and fixed during verification: cook-start re-verification crediting the run's own reservation, and shipment decrementing both `quantity_lbs` and `allocated_lbs` so `available_lbs` is conserved and DEPLETED can trigger.

## Step 7: Run Tests and Iterate — 2026-08-13T18:35:00.000Z

## Summary

**Result: clean 8-round parallel sweep on the first iteration — exit.**

- **Iterations run:** 1 (single 8-round parallel sweep; all rounds ran to completion)
- **Round results:** rounds 1–8 each `passed=108 total=108 failed=0 errors=0` (~138 s per round, 8 concurrent)
- **Tests deleted:** none — no failures surfaced, so no PRD-coverage/unique-derivability deletions were triggered
- **Fixes applied to `test_helpers/`:** none
- **Fixes applied to `implementation/`:** none

The implementation and test suite generated in prior steps (per `worklog.md`: 108 tests covering all 19 §1.8 difficulty instances and 70 §1.9 corner instances, all traced to verbatim PRD citations) held up under the full 8× concurrent per-test-server sweep with zero flakiness — no timing-sensitive failures, no port collisions, no fixture ordering artifacts. Task #8 (iterate test/fix loop until 8-round clean sweep) is complete.

## Step 8: Finalize PRD — 2026-08-13T18:35:30.000Z

SKIPPED per skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the implementation exhibits; no `PRD_FINALIZED.md` produced.

## Step 9: Complete PRD — 2026-08-13T18:56:00.000Z

All changes verified. The task is complete — here is the final report.

## Step 9 Complete: PRD_COMPLETED.md produced

**File**: `/home/ubuntu/github/CodingPRD/tasks/task_1509_rendering_byproduct_processing/workspace/PRD_COMPLETED.md`

### Size stats
- Source `PRD.md`: 472 lines, 80,361 chars → `PRD_COMPLETED.md`: 472 lines, 82,940 chars (**+2,551 chars**, 22 paragraphs edited in place; no new sections, no line-count change).

### Counts
- **Ambiguity-pins (inserts): 20**
- **Mismatch-revisions: 7**

### Mismatch-revisions (PRD described behavior impl does not exhibit)
- **§2.7** — revise — mismatch — added `product lots` to the list of resources whose mutations a SUSPENDED plant rejects (all five lot endpoints call `posture_gate(plant, "op")`) — `implementation/routes_production.py:456,472,487,504,520`.
- **§3.4** — revise — mismatch — supplier/agreement suspension cascades cancel only `SCHEDULED`/`ARRIVED` stops; they do not cancel routes and do not void `COLLECTED` stops (only plant suspension/decommission do, via `cancel_route_system`) — `implementation/logic.py:194-223` vs `152-170`.
- **§3.8** — revise — mismatch — `volume_commitment_lbs`, `tier_discounts`, and `margin_floor_pct` are required on contract creation (PRD said "may also carry"; impl validates with `required=True`) — `implementation/routes_sales.py:40,41,51`.
- **§3.8** — revise — mismatch — `tier_discounts` entries may be supplied in any order; the server sorts ascending by `threshold_lbs` at pricing time (PRD described the submitted list as already sorted) — `implementation/routes_sales.py:295`.
- **§3.8** — revise — mismatch — "re-pricing an order" replaced with "pricing a later order": pricing is `DRAFT`-only (`ERR_ORDER_INVALID_STATE` otherwise), so an order can never be re-priced — `implementation/routes_sales.py:270-271`.
- **§3.8** — revise — mismatch — shipping decrements each lot's `quantity_lbs` **and** `allocated_lbs` (leaving `available_lbs` unchanged); PRD said only `allocated_lbs` decreases, which contradicts its own DEPLETED condition — `implementation/routes_sales.py:399-409`.
- **§3.9** — revise — mismatch — dropped the vacuous proviso "provided its ACTIVE permit, if any, is not SUSPENDED/REVOKED/EXPIRED" from odor recovery; impl checks only posture==RESTRICTED and score≥700 (a RESTRICTED plant can never hold a non-ACTIVE permit) — `implementation/routes_plants.py:126-127`.

### Ambiguity-pins (PRD silent; pinned to impl behavior)
- **§2.3** — insert — non-integer/out-of-range `limit`, non-integer/negative `offset` → `ERR_INVALID_REQUEST` (400); `created_at` ties break by creation order — `implementation/common.py:260-291,256`.
- **§2.3** — insert — non-integer `period_index` filter → `ERR_INVALID_REQUEST` — `implementation/routes_plants.py:148-153`.
- **§2.4** — insert — `version` starts at 1 at creation; `updated_at` initially equals `created_at` — `implementation/common.py:225-231`.
- **§2.5** — insert — clock accepts any parseable ISO 8601 timestamp, rejects unparseable with `ERR_INVALID_REQUEST`, responds `200 OK` with `current_utc` — `implementation/routes_plants.py:16-26`.
- **§2.7** — insert — decommission cascade releases lot allocations of `CONFIRMED` orders before cancelling them — `implementation/logic.py:186-191`.
- **§2.8** — insert — pinned stale-version check position in §2.9 precedence: after posture gate and the endpoint's own state check (route-PLANNED / agreement-ACTIVE / contract-ACTIVE), before remaining business rules — `implementation/routes_logistics.py:193-196`, `routes_sales.py:209-212`, `routes_supply.py:274-277`.
- **§2.9 rule 2** — insert — `scheduled_window_end` strictly later than `scheduled_window_start` is a schema violation — `implementation/routes_logistics.py:177-178`.
- **§2.9 rule 4** — insert — body `plant_id` disagreeing with the owning resource's plant (agreements, wash tickets, stops, orders) → `ERR_INVALID_REQUEST` immediately after existence checks — `implementation/routes_supply.py:116-117`, `routes_fleet.py:68-69`, `routes_logistics.py:190-191`, `routes_sales.py:206-207`.
- **§3.3** — insert — amended `effective_to` earlier than `effective_from` → `ERR_INVALID_REQUEST` — `implementation/routes_supply.py:290-293`.
- **§3.4** — insert — dispatch's agreement-window check applies to non-`CANCELLED` stops only — `implementation/routes_logistics.py:100,105-109`.
- **§3.4** — insert — collect payload minimums: `actual_weight_lbs` ≥ 1, `actual_distance_miles` ≥ 0 — `implementation/routes_logistics.py:296-297`.
- **§3.4** — insert — `final_fee_cents` settles against the agreement's fee schedule **as it stands at collection time** (post-amendment values apply) — `implementation/routes_logistics.py:307-308`, `logic.py:242-259`.
- **§3.4** — insert — collection-created batch's `received_at` is stamped with the server's current logical time — `implementation/routes_logistics.py:323`.
- **§3.6** — insert — one batch on several `planned_inputs` lines: weights accumulate for the `ERR_WEIGHT_EXCEEDS_REMAINING` check — `implementation/routes_production.py:191-197`.
- **§3.6** — insert — completion outputs are integers ≥ 0; zero theoretical total records `yield_variance_pct` as 0.0 — `implementation/routes_production.py:324-325,336-339`.
- **§3.6** — insert — energy cost accrues to the current period settlement regardless of its status (`OPEN`/`REOPENED`/`CLOSED`) — `implementation/routes_production.py:386-389`.
- **§3.7** — insert — grading requires `lab_moisture_pct` always, `lab_ffa_pct` for fats, `lab_protein_pct` for meals; the inapplicable field is stored null — `implementation/routes_production.py:438-446`.
- **§3.7** — insert — regrading records the regrader as `graded_by` — `implementation/routes_production.py:507-509`.
- **§3.8** — insert — all three spec fields (`spec_max_moisture_pct`, `spec_max_ffa_pct`, `spec_min_protein_pct`) are required on every contract regardless of product type — `implementation/routes_sales.py:31-33`.
- **§3.8** — insert — `margin_pct` is 0.0 when `unit_price_cents` is zero — `implementation/routes_sales.py:301-305`.

Everything else in the PRD (state machines, fee/yield/energy/margin formulas, cascades, SoD rules, endpoint table, error catalogue, validation priorities 1–18) was verified line-by-line against the implementation and already pinned uniquely — no change needed.
