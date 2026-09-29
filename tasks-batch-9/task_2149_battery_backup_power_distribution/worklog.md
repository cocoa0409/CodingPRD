# Worklog — task_2149_battery_backup_power_distribution

## Step 1: Create task directory — 2026-08-24T00:00:00.000Z

Created `tasks/task_2149_battery_backup_power_distribution/` and `tasks/task_2149_battery_backup_power_distribution/workspace/` (index 2149, next after existing max 2148).

## Step 3: Copy INSTRUCTION.md — 2026-08-24T00:00:00.000Z

Copied `INSTRUCTION.md` from project root to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 2: Generate scaffold — 2026-08-24T15:29:00.000Z

All three scaffold artifacts are generated and verified.

## What was produced

`/home/ubuntu/github/CodingPRD/tasks/task_2149_battery_backup_power_distribution/`
- **`SCAFFOLD.yaml`** (146 KB) — §1.0–§1.7 plus preamble. No design keys inside.
- **`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** (133 KB) — single key `scaffold_difficulty_design`, 26 instances.
- **`SCAFFOLD_CORNER_DESIGN.yaml`** (282 KB) — single key `scaffold_corner_design`, 97 instances (84 with recipes + 13 `excluded_because` stubs).

## Design shape (beyond-Expert calibration)

- **Profile**: quota/allocation × compliance/audit; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, selector_policy; topology `graph` (self-referential `BatteryModel.replacement_model_id`, cross-aggregate FKs); `state_machine_shape: parallel`; `role_model: segregation_of_duties`.
- **Surface**: 13 entities, 58 endpoints, 52 error codes, 15 calculations, 42 ordered validations, 9 state-machine dimensions across 8 entities, 3 OCC rules, 6 roles (`Customer` is `entity_backed:Account`, rest opaque), `api_prefix: /distribution`, logical clock defaulting to `2026-08-01T00:00:00Z`.

## Difficulty rules — all nine satisfied with >=2 instances (26 total)

| rule | n | how it's differentiated |
|---|---|---|
| dual_variant_calc | 2 | CoreReturn credit (provisional 22000 vs assayed 23643) **vs** Order/Shipment hazmat (forecast 12708 vs actual 65748) |
| combinatorial_formula | 3 | mode (b) per-line rounding pinned (79212 not 79213); mode (c) waiver keyed on `subtotal_cents` 4995005 while `total_cents` is 5057790; mode (a) Peukert x temp-derate x double-ceil sizing with a unit-count tie-break |
| non_linear_state_machine | 2 | CoreReturn cycle INSPECTED->DISPUTED->INSPECTED **vs** Order parallel `fulfillment_status x credit_status` |
| transitive_cascade | 2 | 5-hop delivery cascade (shipment->order->account->CREDIT_HOLD->sibling HELD) **vs** 4-hop core-credit cascade releasing it |
| priority_pair_validation_conflict | 4 | (safety,constraint), (state,fiscal), (referential,fiscal), (temporal,constraint) |
| boundary_precision_check | 3 | warranty months `<=` at 12; zero-line order; SoC exactly 75.0 stays SELLABLE |
| cross_entity_state_dependency | 4 | Order->Account, Shipment->Warehouse, CoreReturn->Order, InventoryLot->DisposalManifest |
| resource_temporal_overlap | 3 | Carrier half-open (adjacency OK) **vs** Warehouse closed + aggregate capacity (same touching pair rejected) **vs** InventoryLot closed cooldown |
| compensating_invariant | 3 | units (`quantity_reserved`), mass (170.625 kg lead), currency (`open_receivable_cents`) |

## Verification performed

- `scaffold_lint.py` -> **`VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`** (940 calls, 58 endpoints, 13 entities).
- Custom audit: 0 unbound `${var}` across all payloads/paths/`as_user_id`/asserts; 0 duplicate instance names across both files; all `grounds` refs resolve to declared calculations/fields/priorities/errors/concurrency rules; every one of the 52 error codes is referenced by at least one design instance; every declared enum value has a producing path (added a lithium `NON_REGULATED` branch at <=20.0 Wh and a contract-CANCELLED cascade corner to close two dead ends); no forbidden concurrency vocabulary.
- Every formula-derived assert literal was computed by executing the scaffold's own formulas in Python (Decimal, `ROUND_HALF_UP`) — e.g. 23643, 65748, 79212, 5057790, 17729, 52624, 17732, 120.625, 170.625, score 87.

Constraint honored: nothing under any sibling `task_*/` was listed, read, or searched; only the skill's `SKILL.md`, `references/claim-extraction-guide.md`, `scaffold_lint.py`, and the `api_prefix`/path conventions in the skill's own `examples/` were consulted.

## Step 4: Generate PRD — 2026-08-24T15:40:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2149_battery_backup_power_distribution/workspace/PRD.md` (89,315 bytes, written incrementally in 7 appends — no truncation).

**Structure**: §1 Introduction (3 paras) -> §2 with 10 domain-derived subsections (2.1 Actors/RBAC, 2.2 verbatim envelope, 2.3 Pagination, 2.4 Identity & Logical Clock, 2.5 OCC, 2.6 The Rejection Ladder, 2.7 Money/Mass/Rounding, 2.8 Separation of Duties, 2.9 Derived Fields & Cascade Discipline, 2.10 Path Resolution) -> §3 with 9 workflow subsections (catalog/sites/carriers, receiving & refresh charging, order pricing, storm allocation, pack->certify->dispatch->deliver, core exchange, warranty, service contracts, disposal manifests) -> §4 endpoint table -> §5 error table.

**Hard Contracts — all PASS**

```
Field coverage check:
- entities[].fields: 133 required, 133 present, 0 missing
- endpoints[].request_body: 67 required, 67 present, 0 missing
- endpoints[].query_params: 19 required, 19 present, 0 missing
- endpoints[].path_params: 13 required, 13 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 42 checked, 42 expressed in prose (ordering rendered as the §2.6 ladder plus per-workflow relative orderings), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_order_version / expected_disposal_manifest_version + ERR_STALE_VERSION/412 all named), 0 missing
- state_machines[].transitions: 51 checked across 9 dimensions, 51 fully expressed, 0 missing
- calculations[]: 15 checked, 15 fully expressed (incl. all 3 dual-variant pairs), 0 missing
- validations[] conditions: 42 checked, 42 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 36 checked, 36 expressed, 0 missing
- entities[].fields[] structured content: 158 checked, 158 reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked (certify APPROVE/REJECT, inspect accept/reject, warranty 3-way fork, settle 2-way fork, cancel from 3 states, carrier half-open vs dock closed windows), 6 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 725
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Also verified: §2.2 is byte-identical to `section-2.2-response-structure.md`; §4 has exactly 58 rows x 4 columns; §5 has exactly 52 rows x 2 columns; all 52 error IDs also appear in §2/§3 prose; no fuzzy hedging and no pseudocode operators survive anywhere in the document.

**One scaffold gap you should know about.** `CORE_LIABILITY_ALERT_CENTS` is referenced by the delivery cascade (hop 4) and the core-credit cascade (hop 3) but is **never assigned a numeric value anywhere in SCAFFOLD.yaml** — it appears in no `calculations[].constants` block. Since the PRD is the implementer's only artifact, I had to bind it: I wrote it as **500000 cents ($5,000.00)** in both §3.5 and §3.6. If the withheld design indices pin a different figure, this is the one number to reconcile before test generation, or the CREDIT_HOLD / HELD-order cascade tests will fail a faithful implementation. (Other unbound-in-constants values were recoverable from the scaffold's own error conditions and are bound correctly: `REFRESH_COOLDOWN_HOURS` = 72, `MAX_INSPECTION_ROUNDS` = 3, `MAX_REFRESH_CYCLES` = 3.)

I did not open, grep, or reference either `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml`.

### Orchestrator reconciliation note (unbound constant)

Checked `CORE_LIABILITY_ALERT_CENTS` against both design indices before launching Step 5. Neither index names the constant. The design instances that exercise the cascade set `core_deposit_balance_cents == 600000` when they expect `CREDIT_HOLD`, and use 22000 / 10000 / 5000 / 4268 / 0 when they expect `ACTIVE`. The PRD's binding of **500000** satisfies every instance (600000 >= 500000 trips the hold; all non-tripping values are far below). No conflict — no reconciliation edit required.

## Step 6: Generate implementation — 2026-08-24T16:05:00.000Z

The implementation is complete and verified.

## What was built

`/home/ubuntu/github/CodingPRD/tasks/task_2149_battery_backup_power_distribution/workspace/implementation/` — Python + Flask, split across 13 small modules so no single Write approached the output cap:

- `start.sh` — guarded `pip install` (only when `flask` is missing), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `app.py` — blueprint registration + `ApiError`/`HTTPException`/catch-all handlers emitting the error envelope
- `common.py` — 52-code error catalogue, `Decimal` half-up rounding, logical clock (defaults to `2026-08-01T00:00:00Z`, never wall-clock), in-memory `Store` (plain dicts, zero seeding), `meta`/`response_type`/`data` envelope, `limit`/`offset`/`total_count`/`has_more` pagination, auth (`X-User-ID`/`X-User-Role`), typed body validators, path/body FK resolvers
- `calc.py` — all 15 calculations and derivations (hazmat classification, SoC decay + condition ladder, storm carve-out, line pricing -> total assembly, forecast vs. actual surcharge, lot selector with its three-way fallback, priority score, Peukert sizing + selector + fee, lead assay + assayed-final credit, manifest lead totals, hold/release cascades)
- `routes_*.py` — all **58** endpoints under `/distribution` (route count verified against the scaffold)

## Key contract decisions

- Ladder order follows PRD §2.6 verbatim (path ids before body, OCC rung 9 before every state check, SoD above state); where §3.8's prose listing conflicted with the ladder, the ladder won as §2.6 declares.
- `CORE_LIABILITY_ALERT_CENTS` = **500000** per PRD.
- `created_at`/`updated_at` and `api_request_timestamp` are stamped from the logical clock; an internal `_seq` breaks the created_at ties the logical clock makes possible, preserving "created_at ASC" list ordering.
- Client-supplied instants (`pickup_window_*`) echo verbatim; server-stamped instants render with 3 fractional digits.
- Storage is in-memory dicts only — no SQLite, no file writes, no seeding at import or startup (grep-verified).

## Verification

- Boots clean from a fresh process via `bash start.sh` and answers HTTP in under a second.
- Ran the task's own suite: `prd-bench-local-run --isolation per-test-server` -> **80/80 passed, 0 failed, 0 errors** (97.6s).
- One caveat for whoever re-runs it: `--start-command` must be an **absolute** path. A relative `bash workspace/implementation/start.sh` boots once and then fails every per-test restart (pytest's cwd differs), which surfaces as 78 spurious ERRORs, not an implementation fault.

### Orchestrator note (impl/test isolation caveat)

Steps 5 and 6 were launched concurrently in one message, which normally gives physical isolation because `test_suite/` does not exist when the impl agent starts. Step 5 ran long enough that `test_suite/` HAD materialized partway through Step 6, and the Step 6 agent ran that partial suite (80 tests; final numbering shows files 01-10 and 13, so 11-12 were still unwritten at that moment). Two consequences to carry forward:

1. The "80/80 passed" figure is against a PARTIAL suite and is not a baseline for Step 7.
2. There is a possible design-index leak path: impl may have absorbed behaviour from reading test files rather than from PRD prose alone. Step 9's full PRD-vs-implementation scan is therefore load-bearing for this task — a clean early sweep in Step 7 must NOT be read as evidence that PRD.md is complete.

## Step 5: Generate unit tests — 2026-08-24T16:20:00.000Z

Test infrastructure and suite are complete.

## What was generated

**`test_helpers/`** (1,983 lines) — Stage 1 infrastructure:
- `types.py` — 13 entity TypedDicts + all status/enum types (every entity carries `id`/`created_at`/`updated_at`/`version`, per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint under `/distribution`
- `api_errors.py` — all 52 error ids + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py`, `factories.py` (7 catalog-model presets + per-resource payload builders), `constants.py`, `test_users.py` (opaque operator roles + `make_customer_headers(account_id)` for the `entity_backed:Account` Customer role)
- `fixtures.py` — tier-0 primitives (clock, catalog, lots, order walk, shipment walk, core-exchange, manifests) plus composites: `setup_base_env`, `setup_{submitted,allocated,packed,certified,dispatched,delivered}_*`, `setup_{submitted,inspected,credited}_core_return`, `setup_account_in_credit_hold` (the five-hop delivery cascade), `setup_manifest_with_credited_return_and_scrapped_lot`

**`test_suite/`** (4,395 lines) — 13 files, **136 tests**, all collected cleanly by pytest.

## Coverage against the design-index-only contract

- **Queue A (difficulty)**: all 26 instances x >=2 tests = 52 tests, tagged `Design: Difficulty/<rule_id>/<name>`
- **Queue B (corner)**: all 84 non-stub instances x >=1 test = 84 tests, tagged `Design: Corner/<section>/<name>`. The 13 `excluded_because:` stubs were not translated; every stub's `difficulty_instance` cross-reference was verified to resolve.
- No instance was skipped — every one passed the PRD-first two-condition filter, so there are no gaps to report. No `skip`/`skipif`/`xfail` anywhere.

## Verification performed

An audit script (AST + YAML based) confirms, and currently reports zero problems:
- exactly one `Design:` line per test, resolving to a real instance (136 tags = 136 tests)
- every PRD citation survives a whitespace-normalized literal match against `PRD.md`, each >=8 words (several citations were rewrapped after the checker caught hyphen/line-break corruption)
- no scaffold leakage: zero occurrences of "scaffold", "§1.x", "Table N", or `priority=N` in emitted code
- all 13 test modules import cleanly and pyflakes reports no undefined names

## Notable adjudication calls

- `CORE_LIABILITY_ALERT_CENTS` = **500000** taken from PRD (hop four / hop three of the two cascades), as instructed.
- Two assertions from difficulty instances were dropped rather than weakened where PRD does not uniquely derive them: `certified_by_user_id == null` after a *failed* endorsement check (kept only where the failure is the SoD rung, which PRD places above every state check), and `refresh_charge_count`/`scrap_manifest_id` defaults on a brand-new lot (PRD states only that `quantity_reserved` opens at 0). Instance coverage is preserved by the remaining assertions in each test.
- All literal expected values (65748, 12708, 79212, 118080, 231.600, 87, 52624, 118800, 170.625, ...) were copied verbatim from the design indices, not recomputed.

## Step 7: Run tests and iterate — 2026-08-24T16:35:00.000Z

All 8 parallel rounds pass 136/136. Exiting.

## Summary

**Iterations run:** 2 (each = 8 concurrent full rounds, no early exit).

- **Iteration 1** — 8/8 rounds identical: 135/136, one deterministic failure.
- **Iteration 2** — 8/8 rounds: **136/136 passed, 0 failed, 0 errors.** No flakiness surfaced in any round.

**Tests deleted:** none. The single failure survived STEP 1a (PRD verbatim-covers) and STEP 1b (uniquely derivable), so deletion was not warranted.

**Fixes applied to `test_helpers/`:** none — the defective fixture lived in the test module itself.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_2149_battery_backup_power_distribution/test_suite/test_02_order_pricing.py` — helper `_order_of(...)` hardcoded `code="TX-DAL"` and preset SKU `IB-AGM-95`. `test_volume_break_steps_up_at_exactly_twenty_five_units` is the only test that builds two environments (qty 24 and qty 25), so its second `_order_of` call re-registered an existing warehouse code and was correctly refused by the implementation with `ERR_DUPLICATE_SKU` (HTTP 409) at setup — the assertion under test never ran. PRD §3.1 states verbatim: *"Its `sku` must be unique across every model row regardless of that row's `status`, and a collision is refused with `ERR_DUPLICATE_SKU` (HTTP 409); the same code guards the uniqueness of a warehouse `code` and of a carrier `code` within their own collections."* This is a **STEP 2 test bug** (fixture constructs a precondition the PRD forbids), not an implementation bug. Fix: `_order_of` now takes `site_code` and `sku` parameters, and the two-environment test names them distinctly (`TX-DAL`/`IB-AGM-95-A`, `TX-HOU`/`IB-AGM-95-B`). No assertion was weakened — all four expected values (`discount_pct` 0.01->0.03 at the 25-unit break, line totals 617760/630500, order totals 694930/710638) are unchanged, and I independently re-derived each from PRD §3.3 before touching the file.

**Fixes applied to `implementation/`:** none. No implementation defect was found; the code traced correctly to PRD prose everywhere I audited it (hazmat classification ladder, per-line-then-sum rounding, forecast-vs-actual base-fee multiplier, half-open carrier window vs closed dock window, ladder rung ordering including version-before-state and dispatch-window-before-rejected-carrier, five-hop delivery and four-hop credit-release cascades, in-memory-only storage with no seeded data).

**Note on the Step 5/6 concurrency concern:** the 56 tests that materialized after the implementation agent's partial 80-test run all pass without implementation changes, so no evidence of test-file absorption surfaced.

## Step 8: Finalize PRD — 2026-08-24T16:45:00.000Z

**Outcome: `PRD_FINALIZED.md` is byte-identical to `PRD.md`. Zero edits were warranted.**

I am saying this plainly rather than manufacturing edits: the sole `<step_7_diff>` item is a test-fixture bug, and the behavior it collided with is already pinned verbatim in the PRD, with the implementation matching that prose exactly.

**Counts:** PRD.md 398 lines / PRD_FINALIZED.md 398 lines / **0.0% delta** (md5 `1cfcb222...` on both).

**Changes:** none.

**Verification performed (the pre-edit search, run even though it terminated in no edit):**

(a) *Subject identified* — uniqueness of `sku` / warehouse `code` / carrier `code` and the error+status returned on collision; secondarily the pricing values the repaired test re-asserts (volume break at exactly 25, per-line rounding, order total assembly), since Step 7 claims those were re-derived unchanged.

(b) *Impl paths enumerated and read* — all three uniqueness callsites, not just the warehouse one the test tripped:
- `implementation/routes_ref.py:73-76` — model `sku`, loop over **all** of `DB.battery_models.values()` with no status filter -> `ERR_DUPLICATE_SKU`
- `implementation/routes_ref.py:151-153` — warehouse `code` -> `ERR_DUPLICATE_SKU` (the Step 7 site)
- `implementation/routes_ref.py:183-185` — carrier `code` -> `ERR_DUPLICATE_SKU`
- `implementation/common.py:76` — `"ERR_DUPLICATE_SKU": 409`
- `implementation/calc.py:237-262` — `volume_discount` thresholds 100/25/10, 15% cap, `rhu(...,4)` on `discount_pct`, per-line `cents(...)` then summed into subtotal
- `implementation/calc.py:228-234` — `hazmat_surcharge` endorsed-site 0.85 multiplier

Each maps to already-verbatim PRD prose: §3.1 line 148 (uniqueness sentence covering all three collections and naming `ERR_DUPLICATE_SKU`/409), §3.3 line 176 (tier + volume components, cap, four-decimal rounding, per-line rounding before summing, with the explicit "sum-then-round is not the rule" disclaimer), §3.3 line 178 (five-step total assembly), §2 line 114 item 16 (uniqueness sits late in the constraint ladder — consistent with the impl validating all fields before the duplicate check), and the §7 error table line 395.

(c) *Wording adjustment* — none needed; no enumerated path was mis-described by existing prose, and no impl-pinned choice was left open by it.

**Notable finding for the record:** the impl's model-`sku` check iterates every row unconditionally, so a `DISCONTINUED` model still blocks its `sku` — exactly what §3.1's "regardless of that row's `status`" already requires. Step 7's conclusion holds: this was a STEP 2 fixture bug (the two-environment test re-registered `TX-DAL`/`IB-AGM-95`), correctly refused by the implementation, and it exposed no PRD silence and no PRD/impl divergence to close.

## Step 9: Complete PRD — 2026-08-24T17:00:00.000Z

`PRD_COMPLETED.md` is written and verified intact.

## Summary

**Source vs output:** `PRD_FINALIZED.md` 398 lines / 89,315 chars -> `PRD_COMPLETED.md` 399 lines / 95,700 chars (+6,385 chars, +1 line). Section headers byte-identical (27), endpoint table still 58 rows, error table still 52 rows, file tail intact. Diff is 28 lines out -> 29 lines in (all in-paragraph edits; one new bullet in §2.2). No new sections.

**Counts:** 32 edits total — **29 ambiguity-pins**, **3 mismatch-revisions**.

### Changes

- §2.1 Actors/RBAC — insert — ambiguity — Customer scoping on `GET /accounts/{id}` compares the account's own `id`; on list endpoints scoping is a silent filter, and only an `account_id` query naming another account is `ERR_ACCOUNT_SCOPE_VIOLATION` — `routes_ref.py:49`, `routes_order.py:18-24`
- §2.2 Error format — insert — ambiguity — unknown path -> 404 / unsupported method -> 405, both with `ERR_INVALID_REQUEST` — `app.py:35-37`
- §2.3 Pagination — insert — ambiguity — `created_at` ties broken by platform creation sequence — `common.py:sort_rows`
- §2.4 Clock — insert — ambiguity — `current_utc` rendered with 3 fractional digits; clock may be wound backwards — `routes_ref.py:206-213`
- §2.6 rung 5 — revise — ambiguity — required strings non-empty; explicit `null` counts as absent; body optional on no-field endpoints; non-object body -> `ERR_INVALID_REQUEST` — `common.py:get_body/_present/f_str`
- §3.1 Discontinue — insert — ambiguity — admissible from any status, rewrites the pointer, successor need not be `ACTIVE` or distinct — `routes_ref.py:126-136`
- §3.1 Carrier — insert — ambiguity — `accepts_hazmat_classes` required but may be empty — `routes_ref.py:180`
- §3.2 Receiving — insert — ambiguity — lot opens with `refresh_charge_count` 0 and three null fields — `routes_inv.py:34-39`
- §3.2 State of charge — insert — ambiguity — elapsed months floored at zero (baseline >= clock => 100.0) — `calc.py:114`
- §3.2 `quantity_available` — revise — ambiguity — carve-out is *always* netted into the reported field; the storm-order figure is never a stored field — `calc.py:152`
- §3.2 Refresh charge — insert — ambiguity — `measured_open_circuit_voltage` accepted at any numeric value, stored verbatim, used in no derivation — `routes_inv.py:77,92`
- §3.2 Scrap — insert — ambiguity — manifest `version` also increments; no warehouse match required between lot and manifest — `routes_inv.py:97-122`
- §3.3 Order creation — insert — ambiguity — full opening-field set; storm event's `status` not examined at creation — `routes_order.py:40-61`
- §3.3 Order lines — insert — ambiguity — `core_expected_count > quantity` is `ERR_INVALID_REQUEST` at rung 5, ahead of model FK resolution — `routes_order.py:97-99`
- §3.3 Order lines — insert — ambiguity — line opening fields; order `version` increments on line add — `routes_order.py:106-120`
- §3.3 Submit — insert — ambiguity — `ERR_MODEL_DISCONTINUED` gate sits between the line-count gate and the credit gate — `routes_order.py:162-182`
- §3.4 Allocate — insert — ambiguity — a `HELD` credit posture refuses with `ERR_INVALID_STATE` — `routes_order.py:214-215`
- §3.4 Lot selection — insert — ambiguity — intra-request tentative reservation: earlier lines' picks deduct from later lines' effective availability — `calc.py:311-312`, `routes_order.py:237-242`
- §3.4 Fallback inspection — revise — ambiguity — the coverable-lot probe also nets earlier lines' tentative take — `calc.py:320-321`
- §3.5 Pack — insert — ambiguity — `end <= start` is `ERR_INVALID_REQUEST` at rung 5 before FK resolution; window instants stored/echoed verbatim; shipment opening-field set — `routes_ship.py:28-31,84-100`
- §3.5 Certify — insert — ambiguity — `rejection_reason` ignored on `APPROVE` — `routes_ship.py:140-156`
- §3.5 Certify (waived) — insert — ambiguity — a waived order's row is not rewritten, so its `version` does not advance — `routes_ship.py:152`
- §3.5 Certify (reject) — insert — ambiguity — carrier appended unconditionally (duplicates possible); order `version` does advance — `routes_ship.py:162-166`
- §3.5 **Dispatch** — **revise** — **mismatch** — prose listed the carrier blacklist before the window; impl and the ladder evaluate the pickup window first, then `ERR_CARRIER_PREVIOUSLY_REJECTED` — `routes_ship.py:178-183`
- §3.6 Core return — insert — ambiguity — full opening-field set — `routes_core.py:64-79`
- §3.6 Re-inspection — insert — ambiguity — `dispute_reason` is not cleared by the next inspection — `routes_core.py:119-132`
- §3.7 Settle — insert — ambiguity — `replacement_warehouse_id` is resolved whenever supplied, so `ERR_WAREHOUSE_NOT_FOUND` fires under `ACCOUNT_CREDIT` too — `routes_warranty.py:101-102`
- §3.7 Settle — insert — ambiguity — a non-`ACTIVE` model with no successor pointer falls back to the claimed model itself — `routes_warranty.py:113-114`
- §3.8 Size — insert — ambiguity — non-`DRAFT` refused with `ERR_INVALID_STATE` — `routes_contract.py:84-85`
- §3.8 **Attach** — **revise** — **mismatch** — prose ordered account-match before order-status; impl and the ladder check contract `SIZED`, then order status, then `ERR_ACCOUNT_MISMATCH` — `routes_contract.py:104-109`
- §3.9 Attach core return — **revise** — **mismatch** — an existing `disposal_manifest_id` on the return is overwritten rather than refused; both rows' `version` increment — `routes_manifest.py:75-84`

### Notes
- Step 8's byte-identical finalize meant every silence was still open; the two ordering mismatches (§3.5 dispatch, §3.8 attach) were prose that read backwards against both the implementation and the PRD's own §2.6 ladder — a green test suite would not have caught either, since Step 7 had no assertion pinning gate precedence there.
- I found no implementation behaviour that contradicts a *uniquely pinned* PRD statement, so no formula, constant, role list, error status, or state-machine edge required revision: all 6 roles, 52 error codes, 58 endpoint role lists, 15 calculations and the 9 state dimensions match the prose as written.
- One class of behaviour has no verbatim PRD basis at all and is now pinned: the intra-request tentative reservation in `calc.select_lot` (§3.4) and the treatment of an explicit JSON `null` as absent (§2.6) — both are exactly the "absorbed from elsewhere, never derived from prose" class the brief flagged.

### Orchestrator final verification

- `results.{1..8}.json` all present and independently re-read: **136/136 passed, 0 failed** in every one of the 8 rounds.
- Artifact line counts: PRD.md 398, PRD_FINALIZED.md 398 (byte-identical, md5 `1cfcb2229652e35fc602c3a37d0d1434`), PRD_COMPLETED.md 399.
- Pipeline complete through Step 9.
