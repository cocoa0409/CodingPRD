# Worklog — task_2170_food_hub_aggregation_coop

## Step 1: Create task directory — 2026-08-29T03:57:12.685Z

Created `tasks/task_2170_food_hub_aggregation_coop/` and `tasks/task_2170_food_hub_aggregation_coop/workspace/` (index 2170 = highest existing 2169 + 1).

## Step 3: Copy shared files — 2026-08-29T03:57:40.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2170_food_hub_aggregation_coop/workspace/INSTRUCTION.md` (1424 bytes).

## Step 2: Generate scaffold — 2026-08-29T04:46:00.000Z

All three scaffold artifacts are generated and lint-clean.

## Output

`/home/ubuntu/github/CodingPRD/tasks/task_2170_food_hub_aggregation_coop/`
- `SCAFFOLD.yaml` (§1.0–§1.7, 120 KB) — no design keys inside
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, single top-level key)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, single top-level key)

## Profile
`quota_allocation` × `pricing_engine`; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, selector_policy; topology `graph`; shape `cyclic`; role model `segregation_of_duties`; `immediate`; `difficulty_level: expert_plus`.

## Contents
**12 entities** — Producer, ProducerDocument, Product, Buyer, BuyerOrder, OrderLine, Allocation, DockSlot, DockAppointment, DeliveryRoute, RejectionClaim, PatronageCycle.

**11 state machines** — Producer (cyclic: CHANGES_REQUESTED<->SUBMITTED and ACTIVE<->SUSPENDED), Product (cyclic LISTED<->DELISTED), BuyerOrder split into two parallel dimensions (`fulfillment_status` x `settlement_status`, with money closing the physical axis), ProducerDocument / OrderLine (branching-with-revert), Allocation / DockAppointment / RejectionClaim / PatronageCycle (branching), DeliveryRoute (compound, bubble-up from allocations two aggregates away).

**10 calculations** — compliance/tier evaluation, cross-producer allocation waterfall with a fully pinned selector (filter -> price ASC -> patronage ASC -> created_at ASC -> per-line empty-pool fallback), margin tier keyed on the *pre-margin* subtotal (circular-looking, order pinned), pricing rollup with round-per-allocation-then-sum plus a MIN_ORDER_MARGIN top-up, shrink apportionment that inverts on the cold-chain excursion flag, gross vs net patronage basis, capped largest-remainder patronage waterfall, voting shares, dock occupancy (aggregate-over-overlap + sanitation buffer), route stop windows (exclusive half-open, adjacency legal).

**3 OCC concurrency rules** (Product / DockSlot / DeliveryRoute versions, 412). **30 validations** in one explicit priority ladder, **43 endpoints** (incl. `POST /_clock/set_current_utc` with the mandated `2026-08-01T00:00:00Z` default), **44 errors**, **5 roles** (HubAdmin, ComplianceOfficer, Producer->entity_backed, Buyer->entity_backed, BoardDirector) with three real segregation-of-duties gates.

**§1.8: 19 instances** across all 9 rules (2 each, 3 for `compensating_invariant`). **§1.9: 73 instances** across the guide's 9 sections (63 live recipes + 10 `excluded_because` stubs).

## Verification run
```
Coverage
  §1.5 endpoints declared:    43
  §1.1 entities declared:     12
  §1.8 instances scanned:     19
  §1.9 instances scanned:     63
  Calls scanned (§1.8+§1.9):  1391

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5
and all §1.1 FKs have reverse-reachability in §1.5.
```
Additional self-audits, all clean: zero unbound `${var}` across both design files (payloads, `as_user_id`, path templates *and* asserts), zero dangling `grounds` refs, every endpoint role in the RBAC matrix, every error referenced outside the catalog, every OCC endpoint declaring its `expected_*_version` input and version bump, and no forbidden concurrency vocabulary (one occurrence of "simultaneously" was found and rewritten).

Every numeric assertion was computed by executing the scaffold's own formulas in Python rather than estimated — e.g. 124200 provisional vs 57348 final with the 1500->1800 bp tier flip; 1625 + 975 = 2600 where sum-then-round gives 2599; 49000 -> 1800 bp -> 57820; 10350 credit splitting 2070/8280 or 8280/2070 depending on the excursion flag; 8500 bp (relief-before-cap) -> 8798/1552; 300000 distributed + 700000 remainder = 1000000.

No sibling task directory was read, listed, or grepped at any point.

## Step 4: Generate PRD — 2026-08-29T05:05:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2170_food_hub_aggregation_coop/workspace/PRD.md` — **392 lines, ~81 KB**, built incrementally (7 append operations plus targeted patches), ending at §5 with no audit footer.

## Structure
§1 Introduction (3 paragraphs) · §2 with 11 subsections (roles/identity, verbatim response envelope, pagination+filters, identity/versioning/nested-path resolution, logical clock, cents & rounding, OCC, the 30-rung screening ladder, segregation of duties, cascade discipline, interval geometry) · §3 with 9 domain subsections (onboarding -> documents/tiers/suspension -> catalog & offers -> buyers/orders/lines -> aggregation -> cross-dock -> routing/delivery -> settlement & rejection claims -> patronage governance) · §4 43-row 4-column endpoint table · §5 44-row 2-column error table.

## Coverage verification (scripted against SCAFFOLD.yaml)
```
Field coverage check:
- entities[].fields:        107 required, 107 present, 0 missing
- endpoints[].request_body:  60 required,  60 present, 0 missing
- endpoints[].query_params:  14 required,  14 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority:      30 checked, all 30 expressed as an explicit ordered ladder (§2.8), 0 missing
- concurrency_rules[] OCC:           3 checked, 3 expressed with write_endpoint + expected_<parent>_version + error_id + 412, 0 missing
- state_machines[].transitions:     58 checked (57 distinct from->to pairs), 57/57 rendered verbatim as `FROM -> TO`, 0 missing
- calculations[]:                   10 checked, 10 fully expressed in prose (all constant values present verbatim), 0 missing
- validations[] conditions:         30 checked, all matchable to their error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects:         43 endpoints, all side-effect sets narrated (incl. both 5-hop and 4-hop cascades), 0 missing
- errors[]:                         44 checked, 44 mentioned outside the §5 table, 0 missing
- sibling-branch symmetry:  suspension vs no-show cascade, provisional vs final valuation, RECEIVED/NO_SHOW/CANCELLED,
                            APPROVE/DENY/WITHDRAW, RATIFY/REJECT, PAID/WRITTEN_OFF from both predecessors — equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 586 · tokens starting with `/`: 0 · bare HTTP-method tokens: 0 · method+path tokens: 0
Status: PASS

Also verified: §2.2 is byte-identical to section-2.2-response-structure.md; §4 = 43 rows/4 columns; §5 = 44 rows/2 columns; no fuzzy/approximating words.
```

## One thing the orchestrator must reconcile
Three constants are **named but never bound to a value anywhere in SCAFFOLD.yaml**: `MAX_REVIEW_CYCLES`, `WRITE_OFF_GRACE_DAYS`, `TEMP_TOLERANCE_C`. A PRD-only implementer cannot guess them, so I bound them explicitly in prose as **3 review cycles**, **30 grace days**, and **2.0 °C tolerance**. Since the §1.8/§1.9 design indices were withheld (never opened, grepped, or listed for content — only `ls` on the directory), any worked example there that assumes different values will diverge from the PRD; these three values should be checked against the design indices before test generation, and either the PRD or the indices adjusted. All other constants (1800 bp ceiling, tier boundaries 50000/200000/500000, tier rates 1800/1500/1250/1000, 2500-cent margin floor, fault rates 2000/8000/5000/9000/10000/0, 1500 bp audited relief, 9000 bp cap, 3000 bp patronage cap, 25000-cent share unit, 10-share cap, 45-minute sanitation default, `2026-08-01T00:00:00Z` clock default) came from the scaffold and are stated verbatim.

### Orchestrator reconciliation of the three unbound constants (performed before Step 5)

Grepped both design indices for each constant and for every executable assert that depends on it:

- `MAX_REVIEW_CYCLES` — PRD binds **3**. `SCAFFOLD_CORNER_DESIGN.yaml:1424` states "MAX_REVIEW_CYCLES is 3, so with review_cycles already at 3 a fourth REQUEST_CHANGES must return HTTP 409 ERR_REVIEW_CYCLE_LIMIT". **Exact match — no action.**
- `TEMP_TOLERANCE_C` — PRD binds **2.0 °C** with a strict `>` comparison (equality is within tolerance), matching `SCAFFOLD.yaml:490`. Every recipe uses `temp_setpoint_c: 2.0` (threshold 4.0) with `recorded_temp_c` of either 1.5 (17 occurrences, assert `temp_excursion == false`) or 5.5 (4 occurrences, assert `temp_excursion == true`). Both asserts hold under 2.0. **Consistent — no action.**
- `WRITE_OFF_GRACE_DAYS` — PRD binds **30**. The only write-off recipe (`SCAFFOLD_CORNER_DESIGN.yaml:2372-2588`) sets `invoice_due_date` 2026-10-01 and advances the clock to 2026-12-01 asserting `WRITTEN_OFF`; that assert holds under 30 (threshold 2026-10-31) and under 60 alike. The index's narrative line "the write-off threshold is 60 days later" appears only in a non-asserting `given`. No recipe asserts a still-`INVOICED` settlement after a clock advance (both `settlement_status == INVOICED` asserts have no `set_current_utc` in their trigger), so no executable test distinguishes 30 from 60. **No test-breaking conflict — PRD's 30 stands; no action.**

Verdict: all three PRD bindings are consistent with every executable assert in both design indices. No PRD edit and no index edit required before Step 5.

## Step 6: Generate implementation — 2026-08-29T05:30:00.000Z

The implementation is complete and verified.

## Files written (3,275 lines total)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | Launcher: reads `$PORT` (default 10000), binds `0.0.0.0`, `exec python3 app.py` in foreground, dependency install guarded on `import flask` |
| `requirements.txt` | 1 | `Flask>=3.0` |
| `app.py` | 80 | Blueprint registration, envelope error handlers, per-request lock + touch-set scope |
| `store.py` | 151 | In-memory dicts, logical clock, `base_record`/`touch`, integer money helpers |
| `constants.py` | 89 | Enums, rates, tiers, and the three PRD-bound constants |
| `errors.py` | 104 | All 44 error IDs -> HTTP statuses + messages |
| `envelope.py` | 85 | `meta`/`response_type`/`data` envelope, pagination (limit 10/1/100, offset 0) |
| `validators.py` | 185 | Ladder rungs 1-3 (`@endpoint`) + field/ISO-8601 validators |
| `fetch.py` | 40 | Ladder rungs 4-5: path-segment and body-FK existence with the correct not-found vocabulary |
| `domain.py` | 226 | Compliance evaluation, availability, dock occupancy, route/line rollups |
| `pricing.py` | 271 | Tier selection, `compute_money`, two-variant `run_rollup`, allocation waterfall |
| `cascade.py` | 253 | 5-hop suspension cascade, 4-hop no-show, staging, route auto-advance, 4-part clock sweep |
| `governance.py` | 151 | Shrink apportionment, patronage basis, capped largest-remainder waterfall |
| `serializers.py` | 233 | 12 entity serialisers with live-derived fields |
| `routes_*.py` (6 files) | 1,283 | All 43 endpoints |

## Validation ladder

The PRD §2.8 order is a single explicit 30-rung ladder. Rungs 1-3 live in the `@endpoint(roles=[...])` decorator (header presence -> role recognition -> endpoint admission). Rungs 4-30 are inlined **in ascending rung order** in each handler, each marked with a `# rung N` comment, and only the rungs that apply to that operation appear. Verified precedences: dock capacity (20) before sanitation (21); OCC (9) above every state/business rule; body-FK existence (5) before request shape (6); ownership (7) before decision authority (8); SoD (12) before producer standing (13).

## OCC

Three writes require a parent version, checked at rung 9 before any state or business rule: `expected_product_version` -> `ERR_STALE_PRODUCT_VERSION`, `expected_dock_slot_version` -> `ERR_STALE_DOCK_SLOT_VERSION`, `expected_route_version` -> `ERR_STALE_ROUTE_VERSION` (all 412). A missing version field is `ERR_INVALID_REQUEST` at rung 6. No other write reads a version. `touch()` bumps a record's `version` by exactly 1 **per request** using a `flask.g`-scoped set, so a cascade reaching a record over several hops still yields +1 as §2.10 requires.

## Verification

Server boots cleanly from a fresh process in ~0.4 s; 160 concurrent requests over 8 threads produced zero errors and no lock deadlock. All 43 routes are registered and match PRD §4 exactly. Behavioural checks that passed against hand-computed expectations: per-allocation rounding (5050, where sum-then-round gives 5049), 2500¢ margin floor topping up the largest allocation, per-allocation pallet ceiling, tier re-selection at invoice from the smaller delivered subtotal, suspension and no-show cascades (delist -> reverse -> re-grade -> re-price -> route detach with recomputed `stop_count`/`pallets_loaded`), credit-limit and no-supply atomicity (nothing persisted), review-cycle ceiling of 3, write-off strictly after due + 30 days with no patronage credited, `temp_excursion` strict `>` at setpoint + 2.0 °C, TEMP_ABUSE fault inversion (2000/8000) with audited relief applied before the 9000 cap, capped largest-remainder patronage (distributed + remainder == pool), half-open interval geometry with adjacency legal, and the full 404 vocabulary.

**No entity data is seeded at startup.** All `db.*` writes live inside request handlers; `Store.reset()` creates only empty dicts. A cold-booted server returns `total_count: 0` for every listable collection and a logical clock of exactly `2026-08-01T00:00:00.000Z`. Storage is process-local Python dicts only — no SQLite, no JSON dump, no `/tmp` cache — so `--isolation per-test-server` wipes every byte on restart.

## Step 5: Generate unit tests — 2026-08-29T05:31:00.000Z

Test infrastructure and suite generated for `task_2170_food_hub_aggregation_coop`.

## Instance translation

**§1.8 (Difficulty, queue A): 19 translated / 0 skipped.** Every one of the 19 instances passed the PRD-first two-condition filter, and each carries **>=2** tests (two rules got 3: `dock_slot_aggregate_capacity_with_sanitation_buffer_geometry` and `route_stop_exclusive_window_allows_adjacency_rejects_zero_length`, split so each of adjacency / capacity / buffer / zero-length is asserted in an isolated scenario).

**§1.9 (Corner, queue B): 63 live recipes translated / 0 skipped.** All 63 non-stub instances have >=1 test. The 10 `excluded_because:` stubs were **not** translated; all 10 `difficulty_instance` cross-references were verified to resolve to a real `name:` + `rule_id` pair in the difficulty index.

No instance was dropped, weakened, or marked skip/xfail — no `pytest.mark.skip` / `skipif` / `xfail` appears anywhere in the output.

## test_helpers/ (9 files, 1999 lines)

| File | Lines | Contents |
|---|---|---|
| `types.py` | 417 | 20 status/role enums + 12 entity TypedDicts (all carry `updated_at`/`version` — PRD §2.4 states no entity omits them) |
| `api_client.py` | 187 | `ApiClient(GenericApiClient)`, one method per declared operation incl. `set_clock` |
| `api_errors.py` | 102 | 44-member `ApiErrorId` + HTTP map, registered via `set_error_http_status_map` |
| `assertions.py` | 306 | per-entity assertions + invariant checkers (`assert_product_availability`, `assert_order_total_identity`, `assert_allocation_money_split`, `assert_shrink_split_conserved`, `assert_pool_conserved`, `assert_receivable_identity`) |
| `factories.py` | 170 | 13 payload factories, input fields only |
| `constants.py` | 85 | PRD-bound thresholds incl. `MAX_REVIEW_CYCLES=3`, `WRITE_OFF_GRACE_DAYS=30`, `TEMP_TOLERANCE_C=2.0`, `CLOCK_STARTUP_DEFAULT="2026-08-01T00:00:00Z"` |
| `test_users.py` | 57 | shared `TEST_USERS` for opaque roles + per-instance `make_producer_headers` / `make_buyer_headers` builders |
| `fixtures.py` | 639 | 5 tiers, headlined by `setup_scenario(stage=...)` walking `draft -> aggregated -> scheduled -> booked -> staged -> in_transit -> delivered -> invoiced -> paid`, plus `onboard_active_producer`, `onboard_audited_producer`, `setup_paid_order_with_shrink` |
| `__init__.py` | 36 | barrel export |

## test_suite/ (10 files, 103 tests)

| File | Tests |
|---|---|
| `conftest.py` | — (fixture bridge) |
| `test_01_producer_onboarding.py` | 18 |
| `test_02_catalog_and_offers.py` | 6 |
| `test_03_aggregation_and_pricing.py` | 16 |
| `test_04_cross_dock.py` | 9 |
| `test_05_routing_and_delivery.py` | 11 |
| `test_06_settlement_and_shrink.py` | 14 |
| `test_07_governance_and_equity.py` | 7 |
| `test_08_access_control.py` | 15 |
| `test_09_cascades_and_invariants.py` | 7 |

## Verification performed

- **Design tags**: all 103 tests carry **exactly one** `Design:` line; 0 untagged, 0 dual-tagged, 0 pointing at a non-existent instance (every tag's `<section>`/`<rule_id>` was checked against the source yaml, not just the name).
- **PRD citations**: every quoted span >=20 chars in every docstring was whitespace-normalised and grepped against `workspace/PRD.md` — **0 non-verbatim citations**.
- `pytest --collect-only` -> **103 tests collected**, clean import of all modules.
- `pyflakes` clean on `test_suite/` and all of `test_helpers/` except the intentional `# noqa: F401` barrel re-exports.
- No wall-clock use anywhere; all 47 temporal manipulations go through `POST /_clock/set_current_utc`.
- No cross-test state dependence: `TEST_USERS` is referenced only in `conftest.py`; every test builds its own entities via declared endpoints, and ownership-gated calls always thread the real entity id through `make_producer_headers` / `make_buyer_headers`.

One note for the implementation stage: the suite is written but has never been executed, since `workspace/implementation/` does not yet exist.

(Orchestrator note: that last line is also the isolation receipt — Step 5 and Step 6 were launched concurrently in a single message, so the test generator could not see `implementation/` and the implementation generator could not see `test_suite/`.)

## Step 7: Run tests and iterate — 2026-08-29T06:35:00.000Z

Clean exit. All 8 parallel rounds pass, 103/103 each.

## Summary

**Iterations run:** 2 full 8-round parallel sweeps (initial + confirming), plus 2 single-round mutation probes in between.

**Iteration 1 (initial sweep):** all 8 rounds `103/103`. No failing tests, so the diagnostic protocol (STEP 0-3) had no union set to operate on.

Because a green first sweep is a known ambiguous signal in this pipeline — vacuous tests, leak-tuned tests, and a genuinely complete implementation all print the same `passed == total` — I mutation-tested the sweep before exiting rather than accepting it at face value.

**Mutation probe 1 — the three PRD-bound constants + logical clock default.** Set `MAX_REVIEW_CYCLES 3->4`, `WRITE_OFF_GRACE_DAYS 30->45`, `TEMP_TOLERANCE_C 2.0->3.5`, `STARTUP_CLOCK 2026-08-01->2026-09-15`. Result `95/103` — 8 tests caught it, spanning the review-cycle ceiling, the clock default, claim credit-split/credit-memo, claim re-adjudication refusal, and three ratification/shrink/pool-conservation tests. The constants are genuinely load-bearing and correctly bound.

**Mutation probe 2 — RBAC rung 3 and all three OCC rules.** Disabled the ladder's role-admission check and the `expected_product_version` / `expected_dock_slot_version` / `expected_route_version` comparisons. Result `98/103` — the three `ERR_STALE_*_VERSION` tests plus two segregation-of-duties tests (producer barred from the aggregation waterfall, board director barred from opening a cross-dock door) all fired.

All six touched files were restored and verified byte-identical by md5 against pre-mutation copies before the confirming sweep.

**Iteration 2 (confirming sweep):** all 8 rounds `103/103`, run against the verified-pristine implementation. No flakiness across the 8 concurrent rounds.

- **Tests deleted:** none. No test failed STEP 1a (PRD coverage) or STEP 1b (unique derivability), because no test failed at all.
- **Fixes applied to `test_helpers/`:** none required.
- **Fixes applied to `implementation/`:** none required.

Storage was audited and confirms the contract: in-memory Python dicts only (`store.py`), no SQLite, no JSON dump, no `/tmp` cache, and nothing seeded, preloaded, or hardcoded at import or startup.

The eight `results.{1..8}.json` deliverables are on disk in `/home/ubuntu/github/CodingPRD/tasks/task_2170_food_hub_aggregation_coop/workspace/implementation/`, generated by the final confirming sweep. Mutation-probe results were written to scratchpad files, never to the declared deliverable paths, so the deliverables reflect only pristine-code runs.

One caveat worth flagging: this task arrived already green, so I did not exercise the fix loop itself — my confidence rests on the two mutation probes, which cover the bound constants, the clock, RBAC, and OCC, but not every one of the 30 ordered validations or 11 state machines. A test that is vacuous in some untested corner would not have been caught by these two probes.

### Orchestrator verification

Independently re-read all eight `results.{i}.json`: every round reports `passed: 103, total: 103, failed: 0`. Deliverables present and intact (the Step 7 "tidy-away" failure mode did not occur).

## Step 8: Finalize PRD — SKIPPED — 2026-08-29T06:36:00.000Z

Skip condition met exactly as specified: Step 7 exited on the first 8-round sweep with 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline. `PRD.md` already determined every behavior the implementation exhibits at every site Step 7 could observe, so there is no `<step_7_diff>` to patch against and no `PRD_FINALIZED.md` is produced. Step 9 therefore starts from `PRD.md`.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-08-29T05:53:00.000Z

Done. `workspace/PRD_COMPLETED.md` is written.

## Result

- **PRD.md**: 392 lines / 81,336 chars -> **PRD_COMPLETED.md**: 392 lines / 88,162 chars (**+6,826 chars**, 36 lines revised, 0 lines added/removed, no new sections/headings/table rows).
- **42 inline edits** across 36 paragraphs: **40 ambiguity-pins**, **2 mismatch-revisions**.

## Changes

- §2.2 — insert — ambiguity — `api_request_timestamp` is read from the logical clock, not wall-clock — envelope.py:13
- §2.3 — insert — ambiguity — a `limit`/`offset` present but unparseable as an integer is also `ERR_INVALID_REQUEST` — envelope.py:49-58
- §2.3 — insert — ambiguity — ties on identical `created_at` (the norm, since the clock is frozen) break by creation order — store.py:125-127
- §2.3 — revise — ambiguity — filters compare raw query strings and are never validated against their enum — routes_catalog.py:73-76
- §2.4 — insert — ambiguity — a non-string body FK reports its not-found code, not `ERR_INVALID_REQUEST`; two body FKs resolve in narrative order (slot before producer) — fetch.py:25-26, routes_dock.py:77-78
- §2.5 — insert — ambiguity — any parseable instant accepted incl. backwards; the sweep never un-expires a doc or un-suspends a producer — cascade.py:217-253
- §2.10 — revise — ambiguity — `version` increments exactly once per request however many cascade hops reach a record — store.py:103-122
- §3.1 — revise — ambiguity — equity `amount_cents` >= 0; `memo` validated then discarded — routes_producers.py:281-282
- §3.1 — insert — ambiguity — review `note` is not persisted or echoed — routes_producers.py:167
- §3.2 — insert — ambiguity — `expires_on` <= `issued_on` is `ERR_INVALID_REQUEST`, not `ERR_INVALID_WINDOW`; documents may be attached in any `onboarding_status` — routes_producers.py:90-92
- §3.2 — revise — ambiguity — adjudication carries `decision` in {`VERIFY`,`REJECT`}; `rejection_reason` optional, null when omitted — routes_producers.py:232-259
- §3.2 — revise — **mismatch** — suspension hop 3 unwinds allocations on *any* item of the producer, not only the newly delisted ones — cascade.py:92-93
- §3.3 — insert — ambiguity — `quantity_offered` is an integer >= 0 — routes_catalog.py:86
- §3.3 — insert — **mismatch** — the below-committed check runs *after* the window check, so a doubly-bad offer returns `ERR_INVALID_WINDOW` — routes_catalog.py:107-113
- §3.4 — revise — ambiguity — line `commodity_code` is length-checked only, not shape-checked like a product's — routes_orders.py:246
- §3.5 — insert — ambiguity — availability during a run is net of units earlier lines already drew — pricing.py:167-169, 221
- §3.5 — insert — ambiguity — `order_pallets` covers the valuation set and always uses reserved `quantity`, including at invoicing — pricing.py:120-125
- §3.5 — insert — ambiguity — rollups zero REVERSED/SHORT_CLOSED money fields but leave `margin_bp` as-is — pricing.py:105-113
- §3.5 — insert — ambiguity — every demand line's `version` advances at aggregation, incl. one left `PENDING` — pricing.py:259-268
- §3.6 — revise — ambiguity — `received_pallets` optional (default 0), `recorded_temp_c` optional (null) — routes_dock.py:172-173
- §3.6 — insert — ambiguity — a null staged temp leaves `temp_excursion` false — cascade.py:136
- §3.6 — insert — ambiguity — `PLANNED -> LOADED` is swept only during a `RECEIVED` close-out — routes_dock.py:193, cascade.py:140
- §3.6 — insert — ambiguity — `NO_SHOW`/`CANCELLED` ignore any supplied `received_pallets`/`recorded_temp_c` — routes_dock.py:194-200
- §3.6 — insert — ambiguity — the slot's `version` advances only when `pallets_booked` changes, so `RECEIVED` does not move it — routes_dock.py:202-205
- §3.6 — revise — ambiguity — `temp_setpoint_c` is required, any number, no default — routes_dock.py:34
- §3.7 — revise — ambiguity — `sequence_no` any integer, no uniqueness/ordering constraint; `service_minutes` integer — routes_delivery.py:265-267
- §3.7 — revise — ambiguity — negative `service_minutes` also yields `ERR_INVALID_WINDOW` — routes_delivery.py:284-285
- §3.7 — insert — ambiguity — a `PLANNED` route with no reserved allocation (e.g. no stops) dispatches to `ERR_INVALID_ROUTE_STATE` — routes_delivery.py:326-332
- §3.7 — insert — ambiguity — unnamed allocations stay `STAGED` and outside the final valuation; a receipted allocation's own status is not re-screened — routes_orders.py:373-388
- §3.7 — insert — ambiguity — a line with nothing delivered keeps its status — routes_orders.py:394-395
- §3.7 — revise — ambiguity — route completion also accepts orders already `CLOSED` — cascade.py:170
- §3.7 — insert — ambiguity — absent/non-array/empty `line_receipts` is `ERR_INVALID_REQUEST` — routes_orders.py:343-344
- §3.8 — revise — ambiguity — payment `amount_cents` >= 1 — routes_orders.py:443
- §3.8 — insert — ambiguity — a filed claim carries its own `producer_fault_bp`/`buyer_credit_cents`/`producer_charge_cents`/`hub_absorbed_cents` at 0 — routes_claims.py:63-75
- §3.8 — insert — ambiguity — adjudication `note` is discarded — routes_claims.py:86
- §3.8 — insert — ambiguity — the tier used for shrink relief is read live at adjudication, not frozen — governance.py:37
- §3.8 — insert — ambiguity — approval never re-runs the pricing rollup; invoiced/allocation money stands — routes_claims.py:126-153
- §3.8 — revise — ambiguity — write-off boundary is strict (exactly due + 30 days is not yet late) — cascade.py:252
- §3.9 — revise — ambiguity — fiscal-year uniqueness spans cycles in every status incl. `CANCELLED` — routes_governance.py:185-187
- §3.9 — insert — ambiguity — the member net basis used at distribution is the one frozen at ratification — governance.py:98-108
- §3.9 — insert — ambiguity — a member with a 0-cent final share is not written to and its `version` does not move — governance.py:143-147
- §3.9 — insert — ambiguity — the cycle exposes only the snapshot totals, never a per-member breakdown — serializers.py:220-233

Nothing in the endpoint table (all 43 paths/roles match the implementation) or the error catalogue (all 44 codes/statuses match `errors.py`) required change.

### Orchestrator note

The green Step 7 sweep did **not** mean the PRD was unambiguous — it meant no test happened to assert the ambiguous behaviors. Step 9's full scan recovered 42 of them, including two genuine PRD/impl mismatches (suspension hop-3 unwind scope, and the window-check-before-below-committed error precedence) that no test exercised. This is the pipeline's completeness backstop working as designed.
