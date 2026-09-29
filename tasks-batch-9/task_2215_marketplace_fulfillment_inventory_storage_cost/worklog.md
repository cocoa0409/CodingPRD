# Worklog — task_2215_marketplace_fulfillment_inventory_storage_cost

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2215_marketplace_fulfillment_inventory_storage_cost/` and `workspace/` subdirectory (directory name pre-allocated by the invoking command).

## Step 3: Copy INSTRUCTION.md — 2026-09-01T00:00:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (53 lines, byte-identical to project root copy; verified during resume).

## Step 2: Generate scaffold — 2026-09-01T12:00:00.000Z

All three scaffold artifacts for scenario 2215 are complete and pass the generator's lint.

Verdict block, verbatim:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2215_marketplace_fulfillment_inventory_storage_cost/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2215_marketplace_fulfillment_inventory_storage_cost/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2215_marketplace_fulfillment_inventory_storage_cost/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    43
  §1.1 entities declared:     12
  §1.8 instances scanned:     22
  §1.9 instances scanned:     46
  Calls scanned (§1.8+§1.9):  924

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Files (absolute paths):
- `SCAFFOLD.yaml` (2329 lines; keys §1.0–§1.7 only, neither design key present)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2111 lines; single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (3856 lines; single key `scaffold_corner_design`)

Counts:
- Entities: 12 (SellerAccount, FulfillmentCenter, SkuListing, RestockQuota, InboundShipmentPlan, ShipmentLineItem, InventoryLot, StorageFeeAssessment, RemovalOrder, ReimbursementClaim, VelocityForecast, MultiChannelOrder)
- State machines: 6 (InboundShipmentPlan, SkuListing with parallel `listing_status` × `inventory_health`, InventoryLot with a lot-status + reconciliation cycle, RestockQuota, RemovalOrder, ReimbursementClaim with a capped info/resubmit cycle)
- Calculations: 10 (iprs_and_restock_limit, restock_allocation with PROVISIONAL/FINAL variants, storage_fee_assessment tiered LTSF, storage_utilization_ratio, velocity_forecast with TRAILING_30/SEASONAL_WEIGHTED variants, reimbursement_settlement, listing_health_recompute, mcf_fee_quote, removal_settlement, receipt_reconciliation)
- Validation priorities: 19 · Endpoints: 43 · Error codes: 44 · Roles: 4 (2 entity-backed, 2 opaque)
- Difficulty design: 9 rule_ids / 22 instances
- Corner design: 55 instances across all 9 taxonomy sections (entities 11, state_machines 8, calculations 10, validations 9, endpoints 4, errors 1, rbac 4, cross_cutting_complexity_layers 7, consistency_model 1); 9 of those are `excluded_because` stubs citing §1.8 instances by name, so 46 carry full test recipes.

Verified invariants beyond lint: all 44 error codes are referenced by at least one instance across the two design files; instance names are unique across the union of both files; every `excluded_because.difficulty_instance` resolves to an existing §1.8 instance name; no `expected_*_version` literal remains (both stale-version probes now replay a captured version that a prior write bumped). Hard constraint respected — no sibling task directory was read.

## Step 4: Generate PRD — 2026-09-01T12:20:00.000Z

PRD generated at `workspace/PRD.md`.

**Size:** 414 lines. Ends at §5 with no audit footer.

**Sections emitted (24 headings):**
- §1 Introduction (3 paragraphs, pain-point angle)
- §2 Global Specifications — 2.1 User and Role-Based Access Control, 2.2 API Response Structure (verbatim), 2.3 Pagination, 2.4 Resource Identity/Timestamps/Logical Clock, 2.5 Path Resolution and Foreign-Key Existence, 2.6 Validation Precedence (the 19-step ladder), 2.7 Conserved Unit Quantities and Compensating Actions, 2.8 Parallel State Dimensions, 2.9 Money/Volume/Rounding Discipline, 2.10 Version Guards on Sizing Writes
- §3 Business Logic — 9 subsections: onboarding + IPRS scoring; SKU listings and the two health dimensions; velocity forecasts + draft plans + allocation waterfall; confirmation gates/final allocation/release paths; receiving fork + discrepancy cascade; unfulfillable classification/removals/settlement; multi-channel fulfillment + fee comparison; reimbursement claims; storage billing epochs + sweeps
- §4 Endpoint table (43 rows, 4 columns), §5 Error table (44 rows, 2 columns)

**Coverage audit:**

```
Field coverage check:
- entities[].fields: 127 distinct required, 127 present, 0 missing
  (148 field entries across 12 entities; 127 after dedup)
- endpoints[].request_body/input + output shapes: 73 required, 73 present, 0 missing
- endpoints[].query_params: 14 required, 14 present, 0 missing
Status: PASS
```
Two repair passes were needed: `shipment_plan_id` was missing on pass 1 and was added to §3.3 line-item narrative.

```
Rule coverage check:
- validations[] with priority: 19 checked, 19 expressed as an explicit ordered ladder in §2.6, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (expected_seller_account_version/ERR_STALE_SELLER_VERSION 412 on plan creation; expected_inventory_lot_version/ERR_STALE_LOT_VERSION 412 on removal-order creation), 0 missing
- state_machines[].transitions: 30 checked, 30 fully expressed with preconditions + side effects, 0 missing
- calculations[]: 10 checked, 10 fully expressed in prose (including pinned rounding order for storage fees with the 131-vs-130-cent illustration, and the pre-discount volume-tier keying for MCF fees), 0 missing
- validations[] conditions: 19 checked, all matchable to their error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 25 endpoints with side effects checked, all expressed, 0 missing
- entities[].fields[] structured content: 12 entities checked, defaults/initial values/aggregate definitions reconstructible (added a §2.7 paragraph defining the five seller ledgers and three lot pools as aggregates rather than accumulations), 0 missing
- sibling-branch symmetry: 7 groups checked (receipt fork, claim decide, removal complete/cancel, plan cancel from DRAFT vs CONFIRMED, plan close from RECEIVED_COMPLETE vs PARTIALLY_RECEIVED, PROVISIONAL vs FINAL allocation, TRAILING_30 vs SEASONAL_WEIGHTED, MCF vs SELF_FULFILLED), all with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 845
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional verifications: §2.2 diffed byte-for-byte against `section-2.2-response-structure.md` — exact match. All 44 `errors[].id`, all 4 role names, all enum member values, and all state-machine state strings appear in backticks. No fuzzy/approximating words remain (one incidental "approximately" was rewritten). The two withheld design files were not opened, and no sibling `task_*/` directory was read.

## Step 6: Generate implementation — 2026-09-01T13:15:00.000Z

Implementation complete and boot-verified.

## Files written
All under `workspace/implementation/` — 21 files, 2,702 LOC of Python:

- `start.sh` — guarded `pip install` (only if Flask is missing) then `exec python3 app.py`; `requirements.txt` (`Flask==3.0.3`)
- `app.py` — factory, blueprint registration, `before_request` auth + per-request bookkeeping, `ApiError`/404/405/HTTPException/Exception handlers, WSGI lock serializing request bodies, `PORT` default **10000**, bind `0.0.0.0`, `threaded=True`, no reloader
- Core: `db.py` (in-memory dict store, empty at boot, dirty-set version bookkeeping), `clock.py` (logical clock pinned to `2026-08-01T00:00:00Z`), `response.py` (envelope + pagination clamps), `errors.py` (all 45 error IDs), `validate.py`, `middleware.py` (role + seller/FC scope), `serialize.py` (explicit per-entity field tuples), `calc.py` (all 10 calculations, Decimal with per-calc rounding modes, full derived-field reconciliation)
- Routes: `sellers.py` (5), `centers.py` (3), `listings.py` (7), `plans.py` (10), `lots.py` (6), `removals.py` (4), `claims.py` (5), `orders.py` (1), `ops.py` (2), plus `common.py`/`__init__.py`

## Endpoints
**43** implemented — exactly matching the PRD §4 table (verified by counting route decorators).

## Boot verification
`PORT=18215 bash start.sh` on a fresh process: server came up, `GET /fulfillment/inventory-lots` returned **HTTP 200** with `"data": []`, `total_count: 0`, correct `meta` envelope (`req_` + 20 uppercase alnum, real-wall-clock ISO-8601 with 3 ms digits) — confirming the store is genuinely empty at boot with nothing seeded. Unauthenticated request correctly returned 401 `ERR_UNAUTHENTICATED`. Full smoke suite re-run against this fresh boot passed every assertion (IPRS scoring/tiering, sibling-draft provisional waterfall, capacity vs. restock error precedence, receipt cascade with delta discrepancy accounting, suppression/reinstate, claim lifecycle and lot lock, removal settlement, LTSF aging across a year, MCF quoting/FIFO draw, billing-run rollups, and exact `version` increment semantics). Server then killed; port 18215 confirmed free.

Two notes on process hygiene: storage is in-memory only (plain dicts, no file or external persistence), and a `pkill -f "python3 app.py"` attempted mid-session was too broad — it self-terminated the agent's own shell, so it switched to killing the specific PID after confirming via `/proc/<pid>/cwd` that a neighbouring `python3 app.py` on port 18217 belongs to task_2217 and left it untouched.

## Step 5: Generate unit tests — 2026-09-01T14:35:00.000Z

Suite complete. Both remaining files are written and the whole suite passes the two mandatory audits.

## Files written

**`test_helpers/`** (8 files, ~1,895 lines) — `__init__.py`, `types.py`, `api_client.py` (48 endpoint methods), `api_errors.py` (`ApiErrorId` + `HTTP_STATUS_CODES`), `assertions.py`, `factories.py`, `constants.py` (`TEST_DEFAULTS`), `test_users.py`, plus `test_suite/conftest.py`.

**`test_suite/`** — 18 modules, **137 tests**:
- Queue A (depth), `test_01`–`test_09`: 51 tests
- Queue B (breadth), `test_10`–`test_18`: 86 tests — entities 15, state machines 12, calculations 14, validations 13, endpoints 8, errors 2, rbac 9, cross-cutting 10, consistency 3

Files added this session: `test_17_cross_cutting_layers.py` (10 tests, 5 instances), `test_18_consistency_model.py` (3 tests, 1 instance). Also fixed one dead local in `test_02`.

## Coverage vs. the design indices

- **Difficulty (§1.8): 22/22 instances translated**, every one with ≥2 tests. 0 skipped.
- **Corner (§1.9): 46/46 non-stub instances translated**, every one with ≥1 test. 0 skipped.
- The 9 `excluded_because:` stubs were not translated; all 9 cross-references resolve to real difficulty instances.
- Audits: 263 PRD citations, **0 missing** after verbatim whitespace-normalized grep against `workspace/PRD.md`; 137 tests each with **exactly one** `Design:` line, last line of the docstring, all 68 distinct tags resolving to non-stub instances; no `skip`/`xfail`/mocking; `pytest --collect-only` → 137 collected, 0 errors; pyflakes clean apart from the intentional re-export warnings in `test_helpers/__init__.py`.

## Design-yaml assertions not transcribed literally (PRD wins)

The yaml recipes contain arithmetic/setup that contradicts the PRD; in each case the PRD-derived value was asserted instead of dropping the instance:

- `consistency_model/receive_response_already_reflects_the_whole_cascade`: yaml asserts listing/lot `fulfillable_units == 50` for a receipt of `received_units: 80, unfulfillable_units: 30`. PRD §3.5 credits `received_units` to fulfillable **and** `unfulfillable_units` to unfulfillable (total 110), so 80/30/110 is asserted.
- `cross_cutting/listing_aggregates_reconcile_after_classification_and_depletion`: the yaml's second receipt at the same centre would credit the first lot (§3.5 lot candidacy), so the second lot is built at a second centre (`FC-B1`).
- `endpoints/lot_age_days_is_recomputed_on_read_while_bucket_waits_for_a_billing_run`: yaml asserts `aged_bucket == UNDER_181` while `age_days == 200`; §3.9 says the bucket follows from `age_days`, so that one assertion is omitted (0→200 on read and `D181_270` after the run are asserted).
- `endpoints/removal_completion_...`: yaml prices the fee at request time; §3.6 opens a `REQUESTED` order at 0 and settles at completion.
- `calculations/liquidation_recovery_cap_...`: yaml nets negative at request time; asserted positive net after completion at 2026-09-01.
- `state_machines/plan_lifecycle_actions_rejected_from_wrong_source_state`: yaml expects `restock_reserved_units == 250` and quotes a foreign line item; `RECEIVED_COMPLETE` releases the reservation (200) and the plan's own line is used.
- Several claim/removal instances whose receipts declared unfulfillable units directly were rebuilt via `setup_lot_with_split_pools` (receipt + classification), per §3.5/§3.6.
- Carried from earlier files: forecast list is newest-first; `SkuListing.in_flight_units` → the forecast's field; `RemovalOrder.recovery_value_cents` → `liquidation_recovery_cents`; nonexistent `SellerAccount.removal_fee_accrued_cents` dropped.

## Step 7: Run tests and iterate — 2026-09-01T15:10:00.000Z

Clean sweep achieved.

## Summary

**Iterations run:** 2 (each a full 8-round parallel `per-test-server` sweep, 137 tests/round).

- Iteration 1: 134–135 / 137 per round. Union of failures across the 8 rounds = 3 tests.
- Iteration 2 (after fixes): **8/8 rounds at 137/137.**

**Tests deleted:** none (no test failed STEP 1a coverage outright).

**Assertions removed (STEP 1c partial-coverage split):**
- `test_suite/test_09_compensating_invariants.py` → `TestPlanCancellationRestoresTheReservationLedger::test_cancellation_zeroes_every_allocation_figure_but_keeps_the_declaration`: dropped the two line-item assertions `line["final_allocated_units"] == 0` and `line["provisional_allocated_units"] == 0`. **BRANCH-ASYMMETRIC SIDE EFFECT.** PRD §3.4 renders line-level zeroing only on the sibling branches — revert says "zeroes the plan's `allocated_units` and `final_allocated_units` **and every line's `final_allocated_units`**", DRAFT-cancel says "zeroes the plan's `provisional_allocated_units` **and every line's `provisional_allocated_units`**" — while CONFIRMED-cancel is written as "it then zeroes **the plan's** `allocated_units`, `final_allocated_units` and `provisional_allocated_units`", naming no line-level effect. A faithful PRD-only reader leaves the lines untouched on that branch. Plan-level zeroing, `declared_units == 900` and the `in_flight_units == 0` assertions were kept (all verbatim-covered). (Test generated from Difficulty/compensating_invariant/plan_cancel_restores_restock_reservation_ledger_exactly.)

**Fixes applied to `test_helpers/`:** none needed.

**Fixes applied to `test_suite/` (fixture-shaped bug living in the test's own setup helper):**
- `test_suite/test_16_role_access_control.py`, `TestExclusiveWriteFamilies._in_transit_plan_of_sixty`: it captured `seller_version_before` *before* running `create_in_transit_plan`, then `test_the_four_refusals_write_nothing_at_all` asserted the seller's `version` still equalled that stale value (observed 3 vs. expected 1). PRD §2.10 states "A successful plan creation itself increments the seller's `version` by 1" and §2.4/§2.10 make confirmation's `restock_reserved_units` write another mutation, so 3 is the PRD-correct post-setup value. Moved the capture to after setup — this also makes the refused plan-creation quote a *current* version, so `ERR_FORBIDDEN_ROLE` is the only possible rejection reason, strengthening the precedence claim the test makes.

**Fixes applied to `implementation/`:** none — no PRD-required check was weakened or removed.

**Flake diagnosed as non-task infrastructure noise (no code change):** `test_12_calculation_variants.py::TestReimbursementPerUnitCap::test_the_lower_seller_cap_replaces_the_listing_unit_cost` failed in 5/8 rounds of iteration 1 with `RemoteDisconnected` on the `POST /fulfillment/inventory-lots/{id}/unfulfillable-classification` request. Evidence it was an ambient host event, not an implementation defect: all 5 failing rounds restarted that test within a 30 ms window (06:57:05.19–06:57:05.22 — the 8 rounds run in lockstep); the server log `/tmp/prd_bench_server_50369.log` shows the request never reached the app and contains **no traceback**; the implementation has no `exit`/`signal`/thread machinery that could self-terminate; the host had 110 GB free memory (no OOM); and the test passed on a fresh single server and in all 8 rounds of iteration 2.

## Step 8: Finalize PRD — 2026-09-01T15:25:00.000Z

`workspace/PRD_FINALIZED.md` created. **413 lines → 413 lines (0.0% delta)**; exactly one line revised (§3.4, line 236).

### Changes

- **§3.4 (Inbound Shipment Plan Lifecycle — Cancelling)** — *revise* — added an explicit statement that the CONFIRMED-cancel branch zeroes only the *plan-level* `allocated_units` / `final_allocated_units` / `provisional_allocated_units` and writes nothing at line level, so the cancelled plan's line items retain their own `provisional_allocated_units` and `final_allocated_units` — `implementation/routes/plans.py:304-321` (specifically the `else` branch at 312-318, which has no `plan_lines()` loop, contrasted with 310-311 and 270-271).

### Per-edit pre-edit search log

**Edit 1 — §3.4 CONFIRMED-cancel line-level allocation figures**

(a) **Subject identified:** which writes (plan-level vs. line-level) the four allocation fields `allocated_units`, `final_allocated_units`, `provisional_allocated_units` receive on plan release/terminal paths.

(b) **Impl paths enumerated** (via `grep -rn "provisional_allocated_units\|final_allocated_units\|allocated_units" --include=*.py`, then read in full):
- `routes/plans.py:92-94` — plan creation initialises all three plan-level fields to 0.
- `routes/plans.py:176-177` — line-item creation initialises both line-level fields to 0.
- `calc.py:280-289` (`run_provisional`) — writes line-level `provisional_allocated_units` + plan-level total; reached from `create_plan` (105), `create_line_item` (185), `revert_plan` (274), `refresh_sibling_drafts` (298-302).
- `routes/plans.py:238-241` (confirm) — writes line-level `final_allocated_units` and plan-level `final_allocated_units`/`allocated_units`.
- `routes/plans.py:262-274` (revert) — zeroes plan-level and **line-level** `final_allocated_units`, then re-runs the provisional waterfall.
- `routes/plans.py:308-311` (DRAFT-cancel) — zeroes plan-level and **line-level** `provisional_allocated_units`.
- `routes/plans.py:312-318` (CONFIRMED-cancel) — **plan-level only; no line loop.** This is the Step 7 site.
- `routes/plans.py:320` → `calc.refresh_sibling_drafts` — skips the plan being acted on (`other["id"] == plan["id"]`), so the cancelled plan's own lines are not re-derived afterwards.
- `routes/plans.py:385` (receipt → `RECEIVED_COMPLETE`) and `routes/ops.py:79-80` (billing-run plan closure → `CLOSED`) — two further paths that zero plan-level `allocated_units` and likewise never touch line-level allocation figures.
- `calc.py:133-134`, `calc.py:255-262`, `routes/sellers.py:93` — read-only aggregations over plan-level `allocated_units`/`provisional_allocated_units`; unaffected.
- `calc.recompute_all` (173-188) — reconciles lots/listings/sellers/quotas/FCs only; never line items. Confirms `restock_reserved_units` / `committed_receiving_units` restoration in §3.4 happens by full re-derivation, matching the existing PRD prose (left verbatim).
- `serialize.py:48-52` — both line-level fields are client-visible on `GET .../line-items`, so the behaviour is observable and worth pinning.

(c) **Wording adjustment:** scoped the new clause strictly to the cancelled plan (`every line item of the cancelled plan`) rather than "every line", so it makes no claim about sibling draft plans whose lines *are* rewritten by `refresh_sibling_drafts` at line 320. Also named only the two allocation fields rather than "the line's figures", so it does not accidentally speak for `received_units` / `shortfall_units` (written on the receipt path). Phrased as a contrast with the revert and draft-cancel branches, so it neither restates nor narrows those branches' existing verbatim prose, and says nothing about the `RECEIVED_COMPLETE`/`CLOSED` paths.

### Items deliberately NOT patched

- **`test_16` fixture fix (stale `seller_version_before`)** — pure fixture bug. PRD §2.4 (`version` starts at 1, +1 per subsequent mutation including derived-field-only ones), §2.7 (recomputation is a mutation) and §2.10 (plan creation itself increments the seller's `version`) already determine the post-setup value of 3: creation bumps via the explicit `mark_dirty(seller)` at `routes/plans.py:108`, confirmation bumps via `recompute_seller`'s `restock_reserved_units` write (`calc.py:133`), and shipping does not (both `CONFIRMED` and `IN_TRANSIT` are in `RESERVING_STATUSES`, so the ledger is unchanged). No PRD silence.
- **`test_12` `RemoteDisconnected` flake** — diagnosed as host noise, no implementation behaviour involved, no PRD implication.

## Step 9: Complete PRD — 2026-09-01T15:40:00.000Z

`workspace/PRD_COMPLETED.md` is written.

**Source vs completed:** `PRD_FINALIZED.md` 413 lines / 81,884 chars → `PRD_COMPLETED.md` 413 lines / 85,779 chars (**+3,895 chars**, 27 lines revised in place, no new sections, no new paragraphs).

**Counts:** 25 ambiguity-pins, 2 mismatch-revisions.

Implementation was walked exhaustively (all 43 routes verified against the §4 table for path, method, role set and status; every calc formula, state transition, ladder position, error code and response-field list cross-checked). Endpoint/role/status parity was already exact; all remaining gaps were silences plus two prose statements that contradicted the code.

### Changes

- §2.1 — revise — ambiguity — auth rejects blank/whitespace-only headers, not just absent ones — `implementation/middleware.py:17`
- §2.2 — revise — ambiguity — `api_request_timestamp` comes from real wall clock, not the logical clock — `implementation/response.py:20`
- §2.3 — insert — ambiguity — out-of-range/non-numeric `limit`/`offset` are clamped (1..100, ≥0) or fall back to defaults, never rejected; `meta` reports clamped values — `implementation/response.py:56`
- §2.4 — insert — ambiguity — `created_at`/`updated_at` are stamped from the logical clock — `implementation/db.py:91`
- §2.4 — insert — ambiguity — `version` advances once per request (not per field write), and rows created by the request stay at version 1 with `updated_at == created_at` — `implementation/db.py:74`
- §2.4 — revise — ambiguity — clock-set answers 200 with a `data` object whose only field is `current_utc`, and accepts backwards moves — `implementation/routes/ops.py:94`
- §2.7 — revise — **mismatch** — lot `missing_units` is reduced by a later receipt making good the shortfall as well as by an approved claim (PRD said "only by an approved reimbursement claim") — `implementation/routes/plans.py:437`
- §3.1 — revise — ambiguity — duplicate `fc_code` → `ERR_INVALID_REQUEST`; `region_code` required non-empty — `implementation/routes/centers.py:29`
- §3.1 — insert — ambiguity — FC posture update: both fields optional, only supplied ones written, empty payload still 200 — `implementation/routes/centers.py:61`
- §3.1 — revise — ambiguity — quota `period_end` not after `period_start` → `ERR_INVALID_REQUEST` — `implementation/routes/sellers.py:79`
- §3.1 — insert — ambiguity — `seller_status` gates nothing; SUSPENDED sellers keep all capabilities — `implementation/calc.py:242`
- §3.2 — insert — ambiguity — `suppression_reason` is re-pinned on every recompute while the suppression condition holds — `implementation/calc.py:112`
- §3.3 — revise — ambiguity — forecast inputs are integers except `seasonal_index` — `implementation/routes/listings.py:106`
- §3.4 — revise — ambiguity — revert decrements `utilized_units` on whichever period is ACTIVE then, floored at 0, skipped when none — `implementation/routes/plans.py:263`
- §3.4 — revise — ambiguity — confirmed-cancel quota decrement reads the same way — `implementation/routes/plans.py:313`
- §3.5 — insert — ambiguity — new absorbing lot's full opening state (`ACTIVE`, `RECONCILED`, `UNDER_181`, `ltsf_exposed` false, fees 0, three anchors null) — `implementation/routes/plans.py:397`
- §3.5 — insert — ambiguity — over-receipt takes the completion branch and is never rejected — `implementation/routes/plans.py:379`
- §3.5 — revise — **mismatch** — lot returns to `RECONCILED` only from `DISCREPANCY_OPEN`; a `DISCREPANCY_CLAIMED` lot keeps that value when a receipt clears the shortfall — `implementation/routes/plans.py:442`
- §3.5 — insert — ambiguity — line `shortfall_units` floored at 0 — `implementation/routes/plans.py:389`
- §3.6 — revise — ambiguity — classification requires `units` ≥ 1 and non-empty `disposition_reason` — `implementation/routes/lots.py:39`
- §3.6 — revise — ambiguity — removal window end not after start → `ERR_INVALID_REQUEST` — `implementation/routes/removals.py:36`
- §3.7 — revise — ambiguity — `consumed_lot_allocations` elements are exactly `{inventory_lot_id, units}` — `implementation/routes/orders.py:60`
- §3.8 — insert — ambiguity — null anchor ⇒ `filing_deadline_at` null and window check skipped at filing and resubmission — `implementation/routes/claims.py:50`
- §3.8 — revise — ambiguity — `information_request_note` is required and non-empty — `implementation/routes/claims.py:95`
- §3.8 — insert — ambiguity — approval with 0 eligible units → `ERR_REIMBURSEMENT_EXCEEDS_ELIGIBLE_UNITS` (422), nothing persisted — `implementation/routes/claims.py:161`
- §3.8 — revise — ambiguity — denial leaves `eligible_units` at 0 — `implementation/routes/claims.py:151`
- §3.9 — insert — ambiguity — billing-run summary carries only its six fields, no `id`/timestamps/`version` — `implementation/routes/ops.py:83`
- §3.9 — insert — ambiguity — `age_days` floored at 0; persisted `aged_bucket` only rewritten by an assessment, so a read can show `age_days` past the stored bucket — `implementation/calc.py:44`, `implementation/calc.py:530`

## Pipeline complete — 2026-09-01T15:40:00.000Z

All steps 1–9 finished. Final state: 137 tests, 8/8 parallel `per-test-server` rounds at 137/137. Artifacts on disk: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_helpers/` (8 files), `test_suite/` (19 files), `workspace/{INSTRUCTION.md,PRD.md,PRD_FINALIZED.md,PRD_COMPLETED.md}`, `workspace/implementation/` (21 files + `results.{1..8}.json`).
