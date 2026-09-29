# Worklog — task_2546_salt_mining_deicing_product_operations

## Step 1: Create task directory — 2026-09-03T09:07:00.000Z

Created pre-assigned task directory `/home/ubuntu/github/CodingPRD/tasks/task_2546_salt_mining_deicing_product_operations` and its `workspace/` subdirectory. Index 2546 was fixed by the orchestrating command (no auto-allocation scan performed, per concurrency constraint).

## Step 2: Generate scaffold — 2026-09-03T11:09:30.000Z

Scaffold for task 2546 is complete and lint-clean.

**Lint verdict (verbatim, final run):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2546_salt_mining_deicing_product_operations/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2546_salt_mining_deicing_product_operations/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2546_salt_mining_deicing_product_operations/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    67
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     64
  Calls scanned (§1.8+§1.9):  994

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files** (all in `/home/ubuntu/github/CodingPRD/tasks/task_2546_salt_mining_deicing_product_operations/`)
- `SCAFFOLD.yaml` — 2543 lines, §1.0–§1.7 only (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1587 lines, single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4713 lines, single key `scaffold_corner_design`

**§1.0–§1.7 content:** domain `salt-deicing-ops`, prefix `/salt`; 12 entities (Mine, Panel, GroundControlInspection, ProductionRun, TreatmentBatch, Depot, StockpileLot, SeasonForecast, BidContract, DeliveryOrder, Allocation, Shipment); 11 state-machine blocks (Mine carries two independent dimensions — `hoist_state` and `compliance_state`); 3 OCC rules (Mine / BidContract / StockpileLot); 13 calculations; 38 priority-ordered validations; 67 endpoints; 49 error ids; 7 roles (DepotManager is `entity_backed:Depot`). Complexity layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers; consistency model `immediate`.

**§1.8:** 9 rule_ids × 2 instances = 18, covering dual-variant preseason target and penalty basis, combinatorial reserve/invoice formulas, the PRODUCING↔SUSPENDED cycle and the bounded rework self-loop, two 4-hop cascades, two priority-conflict pairs, grade-tier and 90 %-utilization boundaries, half-open hoist windows vs closed loadout windows, and two compensating invariants (reserve/release, accrue/waive).

**§1.9:** all 9 guide sections, 94 instances = 64 full recipes + 30 `excluded_because` stubs — entities 12, state_machines 17, calculations 16, validations 9, endpoints 7, errors 19 (all `triggerability`), rbac 7, cross_cutting_complexity_layers 6, consistency_model 1. Verified: no duplicate instance names across both design files, every stub cites a real §1.8 instance, and all 49 error ids are covered by some instance.

**Adjudications made**
1. `/load` and `/receive` are always invoked as `DepotManager` with `as_user_id` set to the origin/destination depot id — this satisfies both the SM precondition (`X-User-ID == origin_depot_id`) and validations priority 4, which only scopes the ownership check to DepotManager.
2. Validations priority 3 compares the QC decider against "the X-User-ID that created the batch", but `TreatmentBatch` had no such field — the rule was unimplementable as written. I added `created_by_user_id` (source: system) to `TreatmentBatch` in §1.1; this was the one lint violation and is now resolved.
3. `POST /salt/panels/{id}/suspend` and `/abandon` were reachable only via the DEFECT-inspection cascade, so I added an `endpoints` instance exercising both manual actions (asserting manual suspend does *not* set `open_defect`, abandon VOIDs the HELD run and freezes `recoverable_tons`, and a repeat abandon returns ERR_PANEL_INVALID_STATE).
4. To keep the corner file tractable, several cheap error triggers were consolidated into multi-call instances (five lot guards on one fixture, two spec guards on one run). The 14 endpoints still not invoked via a `call:` are plain single/list GETs, asserted in prose and covered generically by the entities-section `listing`/`retrieval`/`not_found` claims.

The hard constraint was honored throughout: no sibling `task_*/` directory was listed, read, or grepped.

## Step 3: Copy shared files — 2026-09-03T11:10:00.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T11:28:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2546_salt_mining_deicing_product_operations/workspace/PRD.md`.

**Final line count: 585. Last section heading: `## 5. Error Codes`** — the file ends on the completed final table row `| ERR_PRESEASON_COVERAGE_SHORT | 409 |`, a real section boundary.

**Structure**

- §1 Introduction (business-pain framing for salt mining / deicing supply)
- §2 Global Specifications, 11 subsections: 2.1 Operator Identity and Role Authority, 2.2 API Response Structure (fixed block, verified byte-identical to `section-2.2-response-structure.md`), 2.3 Pagination and List Ordering, 2.4 Common Resource Properties, 2.5 The Logical Clock, 2.6 Rejection Precedence (38 ordered stages with error id, status and full `applies_to` enumeration), 2.7 Tonnage/Currency/Rounding Discipline, 2.8 Stale-Version Guards, 2.9 Cascade Discipline and Derived-Field Reconciliation, 2.10 Path Resolution and Reverse Reachability, 2.11 Product-Line Specification Register
- §3 Business Logic, 9 subsections: 3.1 mine's two independent derating dimensions, 3.2 panel layout / recoverable reserve, 3.3 ground-control program and 4-hop defect cascade, 3.4 production-run scheduling (half-open interval sweep) and hoisting, 3.5 treatment batches and QC adjudication, 3.6 depots / storm posture / stockpile ledger, 3.7 shipments and the closed-interval buffered loadout bay, 3.8 season forecasting and bid-contract lifecycle, 3.9 delivery orders, storm waterfall, invoicing, penalty reconciliation
- §4 API Endpoints — lead paragraph on 201/200 semantics plus a 4-column table with all **67** endpoints
- §5 Error Codes — 2-column table with all **49** error ids

**Coverage:** 12 entities, 67 endpoints, 38 validations, 13 calculations, 58 state transitions across 10 state machines, 3 OCC rules, 49 error ids.

**Contract reports**

```
Field coverage check:
- entities[].fields: 128 required, 128 present, 0 missing
- endpoints[].input (request_body + query_params + path_params): 91 required, 91 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 38 checked, 38 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_mine_version / expected_bid_contract_version / expected_stockpile_lot_version + ERR_STALE_*_VERSION + 412 all named), 0 missing
- state_machines[].transitions: 58 checked, 58 fully expressed with explicit `FROM -> TO` arrows, 0 missing
- calculations[]: 13 checked, 13 fully expressed, 0 missing
- validations[] conditions: 49 distinct error ids checked, 49 matchable to prose, 0 missing
- endpoints[].side_effects / applies_to: 41 endpoints with side effects checked, 41 expressed, 0 missing
- entities[].fields[] structured content: 128 checked, 128 reconstructible from prose (type, bound, default, initial value), 0 missing
- sibling-branch symmetry: 10 groups checked (QC PASS/FAIL/REWORK; AWARD/LOSE; CLOSED/FORFEITED; waterfall none/partial/full; cancel PLANNED/LOADED; single vs order-wide release; both pre-season target variants; both penalty variants; six depot posture edges; quarantine set/clear), 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only, lines 220-454):
- backtick tokens scanned: 1054
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Also verified: no pseudocode operators anywhere (`==`, `>=`, `+=`, `min(`, `round(`, `sum(`, `IN {`, `&&` all absent), and no fuzzy quantifiers ("approximately", "roughly", "conservatively", stray "about") remain.

Two scaffold self-contradictions were resolved and noted for the record: bid-contract decision/activate/close-season actor (`endpoints[].roles` = `ContractAdministrator` was followed over `state_machines[].actor` = `ComplianceOfficer`, since validation priority 2 keys off the endpoint's `roles` list), and release-allocations penalty handling (the endpoint `side_effects` version — `penalty_state` back to `NONE`, `shortfall_penalty_usd` back to 0 — was followed over the state machine's claim that the accrual survives). The phantom `penalty_basis` field named in validation priority 6's enum list exists on no entity and was omitted rather than invented.

**Orchestrator truncation check (per command directive):** independently ran `wc -l` (585) and `tail -25` on PRD.md. File terminates on a complete markdown table row inside `## 5. Error Codes`; all five top-level sections present (lines 3, 11, 220, 455, 531). NOT truncated — no regeneration needed.

## Step 6: Generate implementation — 2026-09-03T12:05:00.000Z

Implementation complete, verified, and the smoke server has been shut down (killed by PID 3888310, port 27026 confirmed closed).

## Files created (3,646 lines total)
Root: `/home/ubuntu/github/CodingPRD/tasks/task_2546_salt_mining_deicing_product_operations/workspace/implementation/`

| File | Lines |
|---|---|
| `start.sh` | 8 |
| `requirements.txt` | 1 |
| `app.py` | 57 |
| `db.py` | 77 |
| `errors.py` | 139 |
| `middleware.py` | 86 |
| `response.py` | 67 |
| `util.py` | 231 |
| `services/calc.py` | 260 |
| `services/derive.py` | 365 |
| `services/serialize.py` | 304 |
| `services/cascade.py` | 89 |
| `services/alloc.py` | 98 |
| `routes/mines.py` | 131 |
| `routes/panels.py` | 169 |
| `routes/inspections.py` | 84 |
| `routes/runs.py` | 205 |
| `routes/batches.py` | 206 |
| `routes/depots.py` | 111 |
| `routes/lots.py` | 63 |
| `routes/shipments.py` | 235 |
| `routes/forecasts.py` | 111 |
| `routes/contracts.py` | 176 |
| `routes/orders.py` | 249 |
| `routes/allocations.py` | 105 |
| `routes/clock.py` | 19 |

## Endpoints
**67 route rules = 66 business endpoints + `POST /_clock/set_current_utc`.** Diffed programmatically against `SCAFFOLD.yaml`: **missing from impl: none; extra in impl: none** (exact set match after path-param normalization).

## Verification
- `python3 -m py_compile` clean on all 24 modules; no `sqlite3`, no file I/O, no `/tmp`, no seeding — 12 empty dicts at boot.
- `start.sh` reads `$PORT`, binds `0.0.0.0`, `exec`s in the foreground, single-threaded.
- Smoke run 1 (full happy path): mine -> panel (recoverable_tons) -> develop/start -> run (rate 33.3333/h, hourly capacity 500.0) -> hoist -> depot -> batch (purity 96.5) -> QC by creator **403 ERR_SEGREGATION_OF_DUTIES** -> QC PASS by 2nd user mints 368.48 t lot -> run auto-closes -> forecast (binding 630000.0) -> contract submit/decide (value 21000.0)/activate/ledger -> order -> allocate (300 t, rank 1) -> deliver (freight 1237.5, credit 3900.0, **invoice_total 19671.75**) -> posture 68.48 stored -> close-season -> DEFECT cascade (panel SUSPENDED, mine HOIST_DOWN, effective 0.0).
- Smoke run 2 (edges): half-open windows let 50+50 == capacity 100 pass but the third run -> `ERR_HOIST_CAPACITY_EXCEEDED`; stale OCC -> `ERR_STALE_MINE_VERSION`; derate cascades a capacity re-fit that holds the *later-starting* run (`held_reason: CAPACITY`) and blocks its reinstate; third DEFECT -> panel `ABANDONED` with its run `VOIDED`; compliance-action by the inspector -> `ERR_SEGREGATION_OF_DUTIES`; CITE -> 1056.0, WITHDRAW -> 0.0; auth/role/404/paging all correct.

## PRD ambiguities resolved
1. **Contract lifecycle ownership** — PRD prose is loose; ContractAdministrator owns decision/activate/close-season (SCAFFOLD RBAC wins).
2. **`open_defect`** — modeled as a stored flag set by a DEFECT inspection and cleared *only* by `remediate-defect` (not by restart), since cascades are asymmetric.
3. **Reserve recompute** — every live panel's `recoverable_tons` recompute bumps that panel's version; combined with a per-request idempotent `touch()`, each entity's version rises by exactly 1 per request.
4. **`terminate_panel(bump_mine=)`** — system-driven abandonment (3rd defect) and auto-deplete on hoist do *not* double-bump the mine version; operator-driven deplete/abandon do.
5. **Auto OPEN->SURGE** fires only when covered capacity > 0 and covered occupancy >= 90%; never auto-reverts.
6. **Same-value state transitions** (e.g. re-posting an identical depot posture) -> `ERR_INVALID_REQUEST` 422; duplicate `panel_code` per mine and duplicate `season_code`+`region_code` also 422.
7. **Rejection ordering** — PRD §2.6's numbered 38-stage precedence wins wherever prose ordering conflicts. Notably: `waive-penalty` skips the stage-12 order-state check; shipment FK order is origin -> destination -> lot; shipment stage 29 compares `destination_storage_kind` against *the lot's* `storage_kind`.
8. **DEPLETED lot** — a shipment against it -> `ERR_LOT_STATE_INVALID`, while an allocation against it falls through to `ERR_INSUFFICIENT_LOT_TONS`.
9. **`ERR_DEPOT_CLOSED`** is enforced on shipment `load` as well as create/receive.
10. **`start-production` on a non-COMPLIANT mine** -> `ERR_MINE_WITHDRAWAL_ORDER_ACTIVE`; only `WITHDRAWAL_ORDER` (not `CITED`) blocks hoist/reinstate.
11. **Defect cascade hops 2-4** run only when the inspection actually moved the panel out of PRODUCING.
12. **`contract_value_usd`** stays null until AWARD; `breach_watch` is therefore false pre-award.
13. **Manual allocation** bumps the parent contract's version and also enforces the depot `state_code` match.
14. **Invoice** — each line rounded to cents first then summed; freight uses each line's own lot's depot rate; guarantee credit floored at 0 against the unrounded ceiling.
15. **ProductionRun versioning** — batch create and QC decisions do not bump the run; only the auto-close does. An explicit `close` with PENDING batches -> `ERR_RUN_INVALID_STATE`.

## Step 5: Generate unit tests — 2026-09-03T12:25:00.000Z

The suite is complete and audited. Task root: `/home/ubuntu/github/CodingPRD/tasks/task_2546_salt_mining_deicing_product_operations/`

## Infrastructure — `test_helpers/` (2,155 lines)
`__init__.py` 26, `api_client.py` 335, `api_errors.py` 179, `assertions.py` 257, `constants.py` 290, `factories.py` 382, `fixtures.py` 579, `test_users.py` 104, `types.py` 243. Plus `test_suite/conftest.py` 19 (the single `api` fixture).

## Tests — `test_suite/`, 105 tests in 18 files (7,505 lines)

Queue A (§1.8 depth index) — 36 tests, exactly 2 per each of the 18 difficulty instances:
`test_01` 300 (dual_variant_calc), `test_02` 297 (combinatorial_formula), `test_03` 306 (non_linear_state_machine), `test_04` 370 (transitive_cascade), `test_05` 284 (priority_pair_validation_conflict), `test_06` 243 (boundary_precision_check), `test_07` 332 (cross_entity_state_dependency), `test_08` 376 (resource_temporal_overlap), `test_09` 401 (compensating_invariant) — all 4 tests each.

Queue B (§1.9 breadth index) — 69 tests over all 64 non-stub corner instances:
`test_10` 548/12, `test_11` 935/15, `test_12` 736/6, `test_13` 802/7, `test_14` 497/6, `test_15` 767/10, `test_16` 574/9, `test_17` 298/3, `test_18` 139/1.

## Verification (all run on disk, not trusted from subagent reports)
- Design tags: 105 tests, every one carries exactly one trailing `Design:` line; 18/18 difficulty instances at >=2 tests, 64/64 non-stub corner instances at >=1; zero unknown tags, zero untagged, zero dual-tagged, and none of the 30 `excluded_because:` stubs was translated. No corner instance is covered from two different files.
- Citations: every quoted PRD fragment >=25 chars is byte-verbatim (whitespace-normalised) against `workspace/PRD.md` — `BAD: 0`.
- `pyflakes` clean on all 27 files; `py_compile` clean on all; `pytest --collect-only` collects 105 tests with no import or collection errors; no `skip`/`xfail`/TODO/placeholder anywhere; no scaffold-language leakage (`scaffold`, `§1.x`, design-file names all absent).
- The queue-B subagents left `test_helpers/` and `conftest.py` untouched (mtimes all <=11:42, before their files).

## Skips
No instance was skipped for PRD silence. One *assertion* inside a corner instance was dropped as PRD-silent (category: no verbatim rule): `ERR_PRODUCT_LINE_MISMATCH` for an `OPEN_PAD` destination carrying a `COVERED` `HIGHWAY_DEICING` lot — §3.7 only names `ERR_UNCOVERED_STORAGE_NOT_ALLOWED` for `FOOD_GRADE`/`WATER_CONDITIONING`.

## Adjudications
Queue A: none — all 18 recipes reproduced their stated numbers from the PRD unchanged (including 617600.00/594176.00/547328.00 grade tiers, the 35999.10 -> 36000.00 surge edge, 20565.00 capped penalty with score 78.00 and breach at 17137.50, 1000.0000/500.0000 t/h window sweeps, 5527.20 -> 4327.20 -> 5527.20 zero-drift reservation).
Queue B (reported by subagents, the two riskiest re-checked by me against the PRD): `min_take_pct: 0` is illegal per §3.8 ("at least 50 and at most 100") so recipes were raised to 50/80 — confirmed; `FINDING_CLEAR` is not in the §3.3 enum (`PASS`/`ADVISORY`/`DEFECT`) so `FINDING_PASS` was used — confirmed; `EPOCH_STAMP = "2026-08-01T00:00:00.000Z"` from §2.5 + §2.4 — confirmed. Also: `contract_value_usd is None` at `SUBMITTED`; no order status change on a partial manual reservation; `preseason_coverage_tons` 1880.00 rather than the recipe's 1974.00.

I did not execute the suite against `workspace/implementation/` — it is being generated concurrently and running it would have meant observing it.

**Note on step ordering:** Steps 5 and 6 were launched concurrently in a single orchestrator message (as the skill mandates). Step 6 finished first and is logged above; this Step 5 entry is appended after it purely because of completion order.

## Step 7: Run tests and iterate — 2026-09-03T12:55:00.000Z

All 8 rounds pass. Verification of sweep integrity: 8 distinct ports (34767, 34891, 39881, 46163, 54119, 55199, 55587, 60341), 8 `Duration:` completions, and only `Killed` (the runner's own `kill -9` between per-test server restarts) — no `Terminated`, so no sweep reaping.

## Summary

**Iterations run:** 2

**Iteration 1** — all 8 rounds reported `passed=104 failed=1 total=105`, with the *same* test failing in every round (not flaky):
- `test_11_state_machine_transitions.py::test_start_production_while_mine_under_withdrawal_order_rejected` — `AssertionError: version moved from 2 to 3 on a refused request`

**Iteration 2** — all 8 rounds report `passed=105 failed=0 total=105`:
```
round 1: passed=105 failed=0 total=105
round 2: passed=105 failed=0 total=105
round 3: passed=105 failed=0 total=105
round 4: passed=105 failed=0 total=105
round 5: passed=105 failed=0 total=105
round 6: passed=105 failed=0 total=105
round 7: passed=105 failed=0 total=105
round 8: passed=105 failed=0 total=105
```

**Tests deleted:** none. The single failure survived STEP 1a (PRD §2.6 verbatim: "the first violated check is the one whose `error_id` and HTTP status the client receives, and **no side effect of any later stage is applied**") and STEP 1b, so it was adjudicated at STEP 2.

**Fixes applied to `test_helpers/`:** none — the fixture chain was faithful.

**Fixes applied to `implementation/`:** none. I confirmed by direct probe that the implementation is correct here: the refused `start-production` left the panel at version 3 -> 3, i.e. it applies no side effect, exactly as §2.6 demands.

**Fix applied to `test_suite/`:**
- `test_suite/test_11_state_machine_transitions.py`, `test_start_production_while_mine_under_withdrawal_order_rejected` — the version baseline was captured from the `develop` response (v2) *before* an intervening `WITHDRAW` compliance action, which per PRD §3.1 ("On **every** compliance action, the recoverable reserve of every panel on the mine whose `status` is one of `PLANNED`, `DEVELOPED`, `PRODUCING` or `SUSPENDED` is recomputed from scratch") combined with §2.4 ("A recomputation of a derived field counts as a mutation: ... that panel's `updated_at` is refreshed and its `version` climbs") legitimately moves the panel to v3. The stale baseline meant the assertion was charging the refused request with a mutation the compliance action had made. Fixed by re-reading the panel immediately after the compliance action and using that as the baseline, so the `assert_version_unchanged` now isolates precisely the refused request. The assertion was **not** weakened — it remains an exact-delta version check, and I added two supporting `status == DEVELOPED` assertions (on the `develop` response and on the pre-refusal read).

One judgement call worth flagging: the PRD admits two readings of whether a *no-op* reserve recompute (here `recoverable_tons` stayed 50000.00, since `pillar_recovery_allowed` defaults to false) bumps `version` — §2.4 says recomputation unconditionally counts as a mutation, while §2.9 conditions the bump on "every entity whose stored values changed". I deliberately did not adjudicate that ambiguity in either direction: the corrected test now passes under either reading, and no other test in the suite pins it.

**Orchestrator independent verification (per memory `prd-bench-step7-verify-sweep-artifacts`):** read all 8 `workspace/implementation/results.*.json` files directly — 8 files present, non-empty (~32.5 KB each, mtime 12:42), each reporting `passed=105 failed=0 total=105`. The clean-sweep claim is confirmed against on-disk artifacts, not taken on the subagent's word.

**Step 8 gating decision:** Step 7 ran 2 iterations with 1 `test_suite/` fix, so the skip condition (0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 implementation fixes) is NOT met. Step 8 will run. Note the diff contains no `implementation/` fix, so Step 8's focus list is narrow — it should expect to find at most the §2.4-vs-§2.9 recompute-version ambiguity the subagent explicitly declined to adjudicate.

## Step 8: Finalize PRD — 2026-09-03T13:10:00.000Z

Done. `PRD_FINALIZED.md` created with two edits, both tracing to the single unadjudicated item in `<step_7_diff>`.

## Line counts
- `PRD.md`: 585 lines
- `PRD_FINALIZED.md`: 585 lines
- Line-count delta: **0 (0.0%)**; 2 lines revised in place (0.34% of lines touched). No new sections, no insertions/deletions.

## Changes
- **§2.4** — revise — "A recomputation of a derived field counts as a mutation" now says explicitly that it counts **even when the recomputed figure is identical to the one already stored**, with the `pillar_recovery_allowed`-false case named as the concrete no-op example, plus a scoping clause pointing at §3.1 for *which* panels the sweep visits — `services/derive.py:167-173` (`recompute_panel_reserves`: assigns `recoverable_tons` then calls `touch(panel)` unconditionally for every panel in `PANEL_LIVE_STATUSES`), reached from `routes/mines.py:125`.
- **§2.9** — revise — replaced the conflicting precondition "every entity **whose stored values changed**" with "every entity the request mutates — where a recomputation of a derived field is itself a mutation, per §2.4, whether or not the recomputed figure differs from the one already stored". This is the sentence Step 7 identified as contradicting §2.4 — `db.py:56-69` (`touch()` bumps unconditionally when called; no value-comparison anywhere).

## Pre-edit search log

**Edit 1 (§2.4)**
- (a) Subject: whether recomputing a stored derived field bumps `version`/`updated_at` when the recomputed value is unchanged — specifically panel `recoverable_tons` on a compliance action.
- (b) Paths enumerated and read: `db.py:56-69` (`touch`, incl. the per-request dedupe set); `services/derive.py:145` `refresh_mine_capacity`, `:164` `PANEL_LIVE_STATUSES`, `:167-173` `recompute_panel_reserves`; `services/cascade.py:21-24` `recompute_mine_capacity(bump=)`, `:27-47` `capacity_refit`, `:50-52` `hold_all_scheduled`, `:55-69` `tighten_shaft`, `:72-78` `panel_left_production`, `:81-89` `terminate_panel(bump_mine=)`; `routes/mines.py:44` (create), `:91-93` (hoist-status), `:117-131` (compliance-action); every `bump=False`/`bump_mine=False` callsite (`routes/inspections.py:59`, `routes/runs.py:157` — both only where the mine was already touched in the same request, so the dedupe makes them equivalent); `services/serialize.py:35-52` `panel_json` (confirming `recoverable_tons` is a genuinely *stored* field, unlike `mined_tons`/`ground_control_defect_count` which are computed on read); grep of all 50+ `touch(` callsites across `routes/` and `services/`.
- (c) Wording adjustments made: (i) the no-op example was phrased as "as happens whenever ... is false" rather than "only when", because `CITED -> WITHDRAWAL_ORDER` is also a no-op repricing even with the flag true — an exhaustive claim would have been false. (ii) Added the closing scoping clause "Only the panels the repricing sweep actually visits move at all; §3.1 fixes that set", because `recompute_panel_reserves` skips `DEPLETED`/`ABANDONED` panels entirely; without it, "climbs on every compliance action" would have wrongly implied terminal panels bump too.

**Edit 2 (§2.9)**
- (a) Subject: the general cascade rule stating *which* entities get `updated_at`/`version` moved in a request.
- (b) Paths enumerated and read: `db.py:56-69`; `services/alloc.py` in full — notably `new_allocation:14-26` and `release_allocation:64-69`, which `touch(lot)` while writing **nothing** to the lot row (`tons_reserved`/`tons_available` are derived at serialize time), and `accrue_shortfall`/`clear_shortfall:85-98` which write to the order but `touch` only the contract; `routes/allocations.py:25-31` `_sync_order` and `:95-105` (single release bumps allocation + lot + order but deliberately **not** the contract, matching §3.9); `routes/orders.py:205-230` (deliver: conditional `touch(depot)` per source lot) and `:233-249` (waive: order + contract only); `routes/batches.py:150-205` (QC pass/fail/rework); `routes/depots.py:71-94` (PATCH bumps even with an empty body) and `:97-111`; `routes/shipments.py:155-157, 211-212, 226-234`; `routes/lots.py:62`; `services/serialize.py:180-210` `contract_json` (ledger figures computed on read, not stored).
- (c) Wording adjustment made: dropped the first candidate, "every entity the request **writes to**", because `alloc.new_allocation` and `alloc.release_allocation` bump a lot they never write a field on, and because "writes to" would have swept in freshly *created* rows (which open at `version` 1 rather than being incremented). Also rejected "every entity the request **touches**", which would have over-claimed against the deliberate non-bumps (single allocation release not moving the contract; terminal panels; the read-only computed views of §2.10). Settled on the deliberately under-determined "every entity the request mutates", which removes the falsified `stored values changed` precondition without asserting any new membership — §3 continues to enumerate the exact per-operation version list.

Note on what was **not** edited: `touch()`'s at-most-once-per-entity-per-request dedupe is load-bearing (e.g. the third-defect path calls `touch(panel)` twice, in `routes/inspections.py:51` and `cascade.terminate_panel:84`), but §2.4/§2.9's existing "increases by exactly 1 on every mutation" already pins it, and it is outside the Step 7 diff, so it was left alone.

## Step 9: Complete PRD — 2026-09-03T13:45:00.000Z

**Orchestrator design decision (reasoning recorded per AUTONOMY directive):** prior runs of this pipeline have shown a single-subagent Step 9 scan silently no-op on a PRD this size (585 lines / 67 endpoints / 12 entities), emitting a `PRD_COMPLETED.md` byte-identical to its input — i.e. the scan never actually ran. To make that failure mode impossible, I seeded `PRD_COMPLETED.md` myself (`cp PRD_FINALIZED.md PRD_COMPLETED.md`, md5 `60e8b0ff...`) and ran the scan as **three sequential file-partitioned passes**, each editing the same file in place, each required to report md5 before/after. The partition was by implementation module, with explicit hand-off of deferred items from each pass to the next.

### Pass A — core / middleware / serializer / mines / panels / inspections / clock
Partition: `app.py`, `db.py`, `errors.py`, `middleware.py`, `response.py`, `util.py`, `start.sh`, `services/derive.py`, `services/cascade.py`, `services/serialize.py`, `routes/mines.py`, `routes/panels.py`, `routes/inspections.py`, `routes/clock.py`.

md5 `60e8b0ff14aca19b9fda0ece2a4c9216` -> `187ef74c50f63d09438b855444e32ad0`; 585 -> 585 lines; 5 sections, 67 endpoint rows, 49 error rows all intact. **17 ambiguity-pins, 6 mismatch-revisions** (23 hunks, all pure line-for-line replacement).

Ambiguity pins: §2.2 `api_request_id` shape (`req_` + 20 chars A-Z0-9) and `api_request_timestamp` reading the logical clock (`response.py:15,21`); §2.3 `limit`/`offset` clamped never rejected, `meta` echoes clamped values (`util.py:190-212`); §2.3 `created_at` ties break by server creation order (`db.py:72-77`); §2.5 clock hook returns `{}`, offset-less instants read as UTC (`clock.py:19`, `util.py:63-75`); §2.6 stage 5 empty/unparseable body = empty object, whitespace-only required strings count as missing, strings trimmed before validation (`util.py:78-98,146-159`); §2.7 input decimal-place counts are hints not validation (`util.py:111-143`); §2.10 filters are exact unvalidated string matches, boolean filters accept `true/1/yes`/`false/0/no`, filters AND together (`util.py:215-231`); §2.10 computed views echo parent id, carry no `id`/`created_at`/`updated_at`/`version` (`serialize.py:254-305`); §3.1 no-op `hoist_state` is 422 not a state conflict, `note` not persisted (`mines.py:87-88`); §3.1 capacity re-fit tie-break extends to creation order (`cascade.py:41-47`); §3.1 no-op compliance action is 422 tested last, SoD precedes `action` validation (`mines.py:100-120`); §3.2 duplicate `panel_code` is 422, compared across terminal panels too (`panels.py:43-45`); §3.2 deplete/abandon never touch the shaft dimension yet always bump the mine version (`cascade.py:81-89`); §3.3 an inspection may be filed against a panel in any status (`inspections.py:27-61`); §3.3 third-defect abandonment requires the panel standing at `SUSPENDED` (`inspections.py:58-59`); §3.3 remediation has no state precondition (`panels.py:139-147`); §5 unrouted request answers `ERR_INVALID_REQUEST` with transport status 404/405 (`app.py:39-42`).

Mismatch revisions: §2.6 stage 22 endpoint list was missing `POST /salt/panels/{id}/develop`, and `start-production` alone also fires for a merely `CITED` mine (`panels.py:93-95,107-109`); §2.6 stage 23 was missing `start-production` (`panels.py:110-111`); §3.3 hop 1 `open_defect` is a latching flag only remediation clears, not "the latest inspection is a DEFECT" (`inspections.py:45`, `panels.py:145`); §3.2 automatic depletion at hoist voids `HELD` runs too (`cascade.py:85-87`); §3.4 `HELD -> VOIDED` fires on `DEPLETED` as well as `ABANDONED` and clears `held_reason` (`cascade.py:16-18`); §3.6 a depot with `covered_capacity_tons` 0 never auto-surges (`derive.py:221-223`).

Deferred to Pass B: `reinstate`'s compliance guard, the phantom `storage_kind` filter on `GET /salt/stockpile-lots`, and the body-less action endpoints' documented optional `reason`/`note`.

### Pass B — runs / batches / depots / lots / shipments / calc
md5 `187ef74c...` -> `79d9f451c754a07b8240383f5e0a7bf1`; 585 -> 585 lines; 5 sections, 67 endpoint rows, 49 error rows intact. **11 ambiguity-pins, 8 mismatch-revisions** (22 subjects), all in-paragraph.

Highlights — mismatches: §2.6 stage 19 was missing `POST /salt/shipments/{id}/load` and conflated two different lot preconditions (shipments need `AVAILABLE`; a manual reservation needs only not-`QUARANTINED`) (`shipments.py:141-145`, `allocations.py:53`); stage 20 was missing `load` (cancel deliberately absent) (`shipments.py:146,216`); stage 33 was missing `hoist` (`runs.py:145`); stage 35 was missing `load` (`shipments.py:148`); §3.4 reinstate "the mine must be `COMPLIANT`" -> must merely not be under `WITHDRAWAL_ORDER`, so a `CITED` mine can reinstate (`runs.py:183-199`); §3.6 the sixth posture edge is a direct `CLOSED -> SURGE`, not "reachable through `OPEN`" (`depots.py:101-110`); §3.7 cancel's documented optional `reason` removed — cancel reads no body at all (`shipments.py:216-222`); §4 `GET /salt/stockpile-lots` row dropped the non-existent `storage_kind` filter (`lots.py:26`).

Highlights — pins: stage 13 `ERR_PANEL_INVALID_STATE` also guards hoist/reinstate with the panel test deferred behind stages 14/22/23/24 (`runs.py:141,193`); stage 14 pending-batch refusal on `close` (`runs.py:168`); §3.4 hoist accepts `hoisted_tons` >= 0 with four guards in written order and no capacity sweep (`runs.py:128-148`); §3.5 `rework_count` key presence (even explicit `null`) is the 422, and opening a batch mutates neither run nor depot since `open_batch_count` is read-derived (`batches.py:50,53-54,99`); §3.5 `input_tons` uncapped vs the run's `hoisted_tons` (`batches.py:48`); §3.5 qc `note` <=2000 chars trimmed, never persisted (`batches.py:134-135`); §3.6 `PATCH /salt/depots/{id}` accepts the empty subset and still bumps `version`, ignores `name`/`state_code` (`depots.py:76-93`); §3.6 `quarantine` must be a genuine JSON boolean, `quarantine_reason` 1-500 chars (`lots.py:41-46`); §3.7 `destination_storage_kind` must equal the lot's `storage_kind` — the previously-unstated condition behind stage 29 on that endpoint (`shipments.py:77-80`); §3.7 origin depot never cross-checked against the lot's `depot_id`, origin may equal destination (`shipments.py:59-61`); §3.7 bay-peer creation-order tie-break (`shipments.py:35`); §3.7 load re-tests three conditions in order with no bay re-sweep (`shipments.py:138-150`).

Deferred to Pass C: stage 29's two conditions on `POST /salt/allocations`, the contract `version` bump on that endpoint, `_sync_order`'s bidirectional `REQUESTED`<->`ALLOCATED` flip plus reservation-while-`SHORTED`, and confirmation that §3.9 agrees with the rewritten stage 19.

### Pass C — forecasts / contracts / orders / allocations / alloc / calc
md5 `79d9f451...` -> `08c8f7730b062ee86575ffa995ddb659`; 585 -> 585 lines; 5 sections, 67 endpoint rows, 49 error rows intact; tail confirmed at the completed §5 table. **12 ambiguity-pins, 10 mismatch-revisions** (22 subjects, 26 Edit calls including 4 self-refinements).

Mismatches: §2.1 "Two segregation-of-duties rules" -> **three**, adding the contract-decision rule plus the null-comparand skip (`contracts.py:120-123`, `middleware.py:81-86`); §2.6 stage 3 was missing `POST /salt/bid-contracts/{id}/decision`; stage 11 was missing `.../deliver` and needed the note that on that endpoint alone the contract-state test is deferred behind stage 12 (`orders.py:210-213`); stage 12 dropped waive-penalty's phantom "(needs `SHORTED`)" and gained `POST /salt/allocations` (`orders.py:242`, `allocations.py:50`); stage 18 `ERR_ALLOCATION_NOT_RESERVED` is raised by `/allocations/{id}/release` **alone** — the wholesale release silently skips non-`RESERVED` rows (`orders.py:158-160`); §3.6 `DEPLETED` is one test applied at **two** moments (shipment load and delivery consumption), and a drained lot with a live reservation stays `AVAILABLE` while a drained `QUARANTINED` lot stays `QUARANTINED` (`alloc.py:76-79`, `shipments.py:39-42`); §3.8 close-season branches on `fulfilled_tons` vs `committed_tons x min_take_pct / 100`, **not** `take_pct` vs `min_take_pct` (`contracts.py:173-174`); §3.9 the allocation ranking has a **fifth** key (creation order) — `created_at` is not the final arbiter under the frozen clock (`alloc.py:49-58`); §3.9 manual reservation rewritten (dropped the false `ERR_LOT_STATE_INVALID` clause, added the depot-`state_code` condition) (`allocations.py:34-74`); §3.9 wholesale release passes over `RELEASED`/`CONSUMED` rows while bumping the contract unconditionally (`orders.py:151-165`).

Pins: §2.6 stage 7 `required_by`-strictly-after-clock sits at stage 7, so a past `required_by` + bogus `bid_contract_id` reports 422 not 404 (`orders.py:48-49`); stage 29's shared identifier covers different conditions per endpoint; §3.8 `season_code`+`region_code` collision is 422 tested after all shape checks (`forecasts.py:51-54`); §3.8 forecast revision touches only 3 optional fields, ignores others, accepts the empty subset and still bumps `version` (`forecasts.py:92-111`); §3.8 contract `state_code` is two uppercase letters compared verbatim to a depot's (`contracts.py:42`); §3.8 decision SoD evaluated before `outcome` is read and before the `SUBMITTED` test, skipped when the id does not resolve (`contracts.py:118-127`); §3.9 order creation resolves `bid_contract_id` then `depot_id`, refusal chain begins with the stale-version guard (`orders.py:51-70`); §3.9 waterfall outstanding starts at the **full** `requested_tons`, netting nothing off existing rows (`orders.py:126`); §3.9 fully-allocated branch leaves the contract row untouched (`orders.py:139-148`); §3.9 single-line release walks `ALLOCATED -> REQUESTED` back and leaves `SHORTED` figures alone (`allocations.py:95-105`); §3.9 delivery bumps each source depot's `version` once per consumed row drawn from it (`orders.py:205-230`, `alloc.py:72-82`); §3.9 `waiver_reason` 1-500 chars and discarded, the accrual test is the only precondition so a `DELIVERED` order is waivable (`orders.py:233-249`).

Pass-B deferrals resolved: (1) both `ERR_PRODUCT_LINE_MISMATCH` conditions now stated in §3.9 with the product-line test first; (2) the contract `version` bump on `POST /salt/allocations` was **already** correctly pinned by existing prose — no change needed; (3) the bidirectional flip and reservation-while-`SHORTED` pinned on both endpoints and `POST /salt/allocations` added to stage 12; (4) **stage 19 (Pass B) was right and §3.9 was wrong** — `allocations.py:53` refuses only `QUARANTINED`, so §3.9 was corrected to match, agreeing with §3.6.

### Orchestrator final verification
- `wc -l`: PRD.md 585, PRD_FINALIZED.md 585, PRD_COMPLETED.md 585.
- `md5sum`: PRD_FINALIZED `60e8b0ff14aca19b9fda0ece2a4c9216` vs PRD_COMPLETED `08c8f7730b062ee86575ffa995ddb659` — **not byte-identical**, so the scan demonstrably ran (contrast the known no-op failure mode).
- `diff PRD_FINALIZED.md PRD_COMPLETED.md`: **68 lines revised**, zero lines added or removed.
- Structure: 5 top-level sections at lines 3/11/220/455/531; **67** endpoint rows; **49** error rows; tail ends on the completed final row of the §5 table, a real section boundary.
- `find implementation -name '*.py' -newermt '2026-09-03 12:42'` and the same over `test_suite/`/`test_helpers/` both return **nothing** — no implementation or test byte changed after the clean 8-round sweep, so the verified `105/105 x 8` result still holds for the shipped artifact. Steps 8 and 9 touched documentation only.

Pipeline complete: `workspace/PRD_COMPLETED.md` written.
