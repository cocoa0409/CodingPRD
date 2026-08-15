# Worklog — task_2025_meat_protein_wholesale_trading

Scenario: 2025. Meat & Protein Wholesale Trading (protein trading desk): carcass/primal purchase & cutout value, yield conversion & specification (trim/fat) compliance, cold storage position & aging, forward contract vs spot & hedging exposure, USDA grading & inspection documentation, load-out & LTL/temperature control, rejection at receiving & claim, weekly price sheet & customer allocation

Requested difficulty: harder than expert level.

## Step 1: Create Task Directory — 2026-08-15T07:50:00.000Z

Directory tasks/task_2025_meat_protein_wholesale_trading/ and workspace/ already created (pre-provisioned by the pipeline launcher); orchestrator began at Step 2 as instructed.

## Step 2: Generate Scaffold — 2026-08-15T08:53:30.000Z

All checks green. The scaffold is complete and lint-clean.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2025_meat_protein_wholesale_trading/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top key `scaffold_corner_design`

**Counts:**
- Entities: **16** (Supplier, Customer, Warehouse, Product, PriceSheet, PriceSheetLine, YieldSpec, PurchaseOrder, InventoryLot, FabricationBatch, ForwardContract, Allocation, Shipment, TemperatureReading, Claim, InspectionCertificate)
- State machines: **11** — including a bounded cyclic negotiation loop (Claim: OFFER_MADE ⇄ COUNTERED, 3-round cap), parallel state dimensions (Shipment `status` × sticky `temp_compliance`), cyclic quarantine/release and supplier suspend/reinstate loops, clock-sweep auto-transitions (lot EXPIRED, contract DEFAULTED), and compound cross-entity cascades
- Calculations: **10** — dual-variant cutout (booking sheet vs grading sheet), aging×grade unit value (4 age bands × 6 grade multipliers, single final rounding), tiered allocation waterfall, credit exposure, warehouse occupancy, FIFO lot selector, strict-`>` temperature breach, hedging exposure, and provisional-vs-final claim settlement
- Validations: **16** ordered priority rows spanning auth → existence → state → safety → constraint → temporal → referential → fiscal → OCC
- Endpoints: **72** (deliberately above the Expert band — every action maps to a state transition or FK reverse-reachability requirement)
- Errors: **59** catalogued; verified every one is referenced by §1.2/§1.4 and exercised by at least one §1.8/§1.9 instance
- Roles: **7** (segregation-of-duties model: Trader writes contracts/sheets but RiskOfficer cancels/runs allocation; WarehouseOperator receives but QualityGrader inspects; CustomerRep is `entity_backed:Customer` with ownership enforcement; ClaimsAdjuster offers but never files)
- §1.8 instances: **18** (exactly 2 per rule × 9 rules, all with literal-computed asserts — e.g., cutout 398000 vs 399000, aging 470→447 at age 7→8, per-line rounding 511 vs forbidden 510)
- §1.9 instances: **68** (64 active recipes + 4 `excluded_because` stubs), covering all 9 claim-guide sections

**Notable design decisions:**
- Flat topology with self-referential genealogy (PriceSheet supersedes itself; InventoryLot parent_lot_id fabrication lineage) — a departure from the usual hierarchical scaffolds, per §0.3 diversity guidance
- Two true OCC races per §1.2.1's serial-observability filter: claim offers (supersede without state change) and contract amendments (stay OPEN), both with `expected_*_version` captured from prior responses
- Depth-3 transitive cascade on sheet publish (supersede → shipment-free CONFIRMED allocations cancel → exposure recompute → CREDIT_HOLD auto-release) vs depth-2 claim-accept cascade
- Credit enforcement is a post-grant threshold trigger (grant, recompute, auto-hold) rather than a pre-grant gate, with strict `>` so `exposure == limit` stays ACTIVE — giving a clean cents boundary paired against the Fahrenheit boundary
- Fixed logical clock (default `2026-08-01T00:00:00Z`, documented in the endpoint) drives aging bands, shelf-life expiry sweeps, and forward-contract default sweeps
- Lint verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (870 calls scanned)

## Step 3: Copy Shared Files — 2026-08-15T07:51:00.000Z

Copied ./INSTRUCTION.md to tasks/task_2025_meat_protein_wholesale_trading/workspace/INSTRUCTION.md (done while Step 2 was in flight; recorded here in step order).

## Step 4: Generate PRD — 2026-08-15T09:16:00.000Z

All checks pass. The PRD is complete and verified. Final report:

---

## Task Complete: PRD Generated for task_2025_meat_protein_wholesale_trading

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2025_meat_protein_wholesale_trading/workspace/PRD.md` — **395 lines** (72.3 KB)

The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.

### Section list

- **§1. Introduction** — 3 paragraphs (business context, computational economics, role/convention overview)
- **§2. Global Specifications** — 11 subsections: 2.1 RBAC (7 roles, identity bindings, ownership chain), 2.2 API Response Structure (byte-identical to canonical block), 2.3 Pagination and List Filtering (all filter params enumerated), 2.4 The Logical Trading Clock (init `2026-08-01T00:00:00Z`, both sweeps, output fields), 2.5 Resource Identity/Timestamps/Versions (incl. the 4 entities lacking `updated_at`/`version`), 2.6 Weights/Money/Rounding, 2.7 Trading Weeks + Published-Sheet Selector, 2.8 Request Validation Pipeline (all 16 priorities as an ordered, masking cascade), 2.9 OCC (both rules, exact fields/IDs/412), 2.10 Credit Exposure + Auto Credit Hold, 2.11 Occupancy/Capacity/Cascade Bookkeeping
- **§3. Business Logic** — 9 subsections: 3.1 Reference Data, 3.2 Price Sheet Cycle, 3.3 PO Booking/Receiving, 3.4 Inspection/Grading/Lot Value, 3.5 Fabrication, 3.6 Forward Contracts + Allocation Waterfall, 3.7 Load-Out/Cold Chain/Dock Decisions, 3.8 Claims/Settlement, 3.9 Net Exposure
- **§4. Endpoint Definitions** — 72-row, 4-column table
- **§5. Error Code Catalogue** — 59-row, 2-column table (no audit footer; document ends here)

### Coverage audit (all three Hard Contracts PASS, verified mechanically)

- **Contract 1 (Field-Name Coverage):** PASS. A Python verifier parsed SCAFFOLD.yaml and extracted all backticked tokens from the PRD (fenced code blocks stripped first). `entities[].fields`: 131 required identifiers total (16 entity field sets + every `input`/`query_params`/`path_params` name + 12 endpoint output fields like `current_utc`, `confirmed_count`, `exposure_lbs`), **131 present, 0 missing** — verified in one pass after the full document was assembled, with the delimiter-parity bug in the first checker diagnosed and corrected before accepting the result.
- **Contract 2 (Rule Coverage):** PASS by manual walk of every scaffold table against the prose: all 16 validation priorities expressed as an explicitly ordered pipeline (§2.8) with per-error catalog statuses; both OCC rules named with `write_endpoint` capability + `expected_claim_version`/`expected_contract_version` + exact error IDs + 412, framed purely in stale-version terms; all 11 state machines rendered (41 transitions, incl. the 3-transition parallel `temp_compliance` axis, the GRADED→RECEIVED revocation exception, and both void paths sharing `ERR_BATCH_NOT_DRAFT`); all 10 calculations fully rendered with constants embedded (per-line-then-sum cutout with both sheet selectors and the grading fallback; grade multipliers 1.08/1.00/0.94/0.90/0.85/0.97; boundary-inclusive age bands 7/14/21/22 days at 1.00/0.95/0.88/0.75; waterfall tier order and earmark pool semantics; exposure floor and strict credit comparison; FIFO ranking and all-or-nothing insufficiency; sticky BREACHED with strict boundary; 4-component exposure net; per-type provisional percentages 60/50/100/40; 80% liability cap + conditional 15000-cent freight allowance); all multi-link cascades (publish, revoke, reject, void, accept) rendered in causal order; sibling branches (offer from 3 states, deny from 2, withdraw from 3, compliant/non-compliant inspection) given equal density.
- **Contract 3 (§3 Path Purity):** PASS. 665 backticked tokens scanned inside §3 — **0** starting with `/`, **0** bare HTTP methods, **0** method+path combinations; plain-text scan for `POST`/`GET`/`PUT`/`/api` in §3 also clean. Endpoints are referenced via state-pair framing, role + verb, and capability descriptions only.
- **Supporting checks:** §2.2 block is byte-identical to `section-2.2-response-structure.md`; all 59 error IDs present in prose; all 74 enum/state values present verbatim; all 72 scaffold paths appear in the §4 table; zero pseudocode operators (`==`, `>=`, `min(`, `+=`, etc.) and zero fuzzy words ("approximately", "roughly", "conservatively", …) in the prose.

One scaffold ambiguity was handled conservatively: the error ID for closing an already-terminal price sheet and for shipment-creation against a non-`CONFIRMED` allocation are not nominated in the scaffold, so the PRD states the preconditions and their 409 class without inventing new error IDs.

## Step 5: Generate Unit Tests — 2026-08-15T09:55:00.000Z

All checks pass. The generation is complete.

**Generated output** in `/home/ubuntu/github/CodingPRD/tasks/task_2025_meat_protein_wholesale_trading/`:

- **`test_helpers/`** (9 files): `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`, `__init__.py`
- **`test_suite/`** (12 files): `conftest.py` + 11 test files, **99 tests total**, all collecting cleanly under pytest

**Tests per file:** test_01 reference data/envelope: 6 · test_02 price sheet cycle: 8 · test_03 purchase orders/receiving: 13 · test_04 cutout/lot valuation: 7 · test_05 lot lifecycle: 6 · test_06 fabrication: 6 · test_07 allocations/waterfall: 9 · test_08 credit/contracts/exposure: 10 · test_09 shipments/cold chain: 12 · test_10 claims/settlement: 11 · test_11 security/validation pipeline: 11

**§1.8 (queue A): 18/18 instances translated, 2 tests each (36 tests).**

**§1.9 (queue B): 63/64 non-stub instances translated (1 test each).** The 4 `excluded_because` stubs were not translated; cross-references verified (`grading_certificate_computes_actual_cutout`, `temp_boundary_error_free_compliance`, `line_allocated_lbs_reconciliation` point to translated difficulty instances; `stale_version_errors` points to the two translated cross_cutting OCC instances).

**Skipped (1):** `Corner/entities/warehouse_create_computed_field_input_ignored` — fails the two-condition filter twice: PRD never says whether a client-supplied computed field is ignored vs rejected (not uniquely derivable), and its `version == 1` assertion is unpinned (PRD §2.5 pins "increments by one on every mutation" but no initial value). No weakened placeholder emitted.

**Notable adjudications:**
1. `hedging_exposure_report_math`: the YAML's precomputed literals (1200 lbs / 840000c) contradict its own setup under the PRD §3.9 formula (1000 + 500 − 300 − 200 = **1000 lbs / 700000c**); the test asserts the PRD-derived values.
2. `void_voided_batch_returns_batch_not_draft`: recipe setup was broken (drafting on an IN_INSPECTION lot violates PRD §3.5's AVAILABLE requirement); repaired minimally (inspect carcass lot first, one YieldSpec-covered output) with the asserted rule unchanged.
3. OCC tests assert relative version progression (v+1, v+2) rather than the recipes' hardcoded 2/3, since the initial version is unpinned.
4. `clock_default_is_fixed_startup_time` asserts a `"2026-08-01T00:00:00"` prefix on `published_at`, since §2.2 permits three-fractional-digit timestamps (both `…00Z` and `…00.000Z` are faithful).

**test_helpers architecture:** `ApiClient(GenericApiClient)` with one method per endpoint, all paths carrying the `/api` prefix; full 53-error id→HTTP map registered via `set_error_http_status_map`; append-only entities (Product, YieldSpec, TemperatureReading, InspectionCertificate) TypedDict/assertions omit `updated_at`/`version` per PRD §2.5; six opaque roles as shared `TEST_USERS` constants while entity-backed CustomerRep is threaded exclusively via `make_customer_rep_headers(customer["id"])` (no shared constant, preventing the ownership-check bug); factories randomize business codes; `fixtures.py` provides 6 tiers (reference singles → sheet cycle → procurement → `setup_available_lot` → `setup_confirmed_allocation` → `setup_staging/delivered_shipment`/`setup_filed_claim` with breach flag), all using `get_success_data` so setup failures surface as clear "Setup step failed" errors.

**Audits passed:** every test has exactly one resolving `Design:` tag; every docstring citation survives whitespace-normalized literal grep of PRD.md; no `skip`/`skipif`/`xfail` marks anywhere; no hardcoded initial-version assertions.

## Step 6: Generate Implementation — 2026-08-15T09:55:00.000Z

Implementation complete and verified. Here is the summary.

**File list — `tasks/task_2025_meat_protein_wholesale_trading/workspace/implementation/`**

| File | Contents |
|---|---|
| `start.sh` | Executable launcher: guarded `pip install` (no-op once Flask is present), `exec python3 app.py`, foreground, `0.0.0.0:$PORT` (default 10000) |
| `requirements.txt` | `flask>=3.0,<4.0` |
| `app.py` | Flask app, blueprint registration, envelope-wrapped handlers for ApiError/404/405/500 |
| `store.py` | In-memory tables, logical clock (boots at exactly `2026-08-01T00:00:00Z`), monotonic wall-clock timestamps, UUID/request-id generation |
| `helpers.py` | `ApiError`, success/error envelopes, Decimal discipline (2dp weights, integer cents, ROUND_HALF_UP), shape-validation primitives, pagination, auth/ownership, sheet selectors, and the calculation library |
| `routes_reference.py` | Suppliers (+status suspend/reinstate cascade), customers, warehouses, products, yield specs |
| `routes_sheets.py` | Price sheets, lines, publish (3-link supersede cascade), close/discard, the allocation waterfall |
| `routes_procurement.py` | Purchase orders (booking cutout, receive, cancel), lot inspect/quarantine/release, fabrication draft/post/void |
| `routes_trading.py` | Forward contracts (amend with OCC, cancel cascade), allocation create/cancel |
| `routes_logistics.py` | Shipments (explicit + FIFO draw), temperature readings (sticky BREACHED axis), depart/deliver/reject (+returns-lot cascade) |
| `routes_claims.py` | Claims full negotiation lifecycle + settlement, inspection certificates issue/revoke (+3-link grade-revert cascade) |
| `routes_misc.py` | `POST /api/_clock/set_current_utc` (expiry + default sweeps, value repricing), `GET /api/exposure` |

All 72 endpoints, 11 state machines, 10 calculations, 16 validation priorities (checked in pipeline order, auth → ownership → shape → path → FK → state → cross-entity → safety → uniqueness → capacity → temporal → kind → credit → OCC → supply), 59 error IDs with exact HTTP statuses, and 7 roles with CustomerRep entity-backed ownership are implemented.

**State storage**

Purely in-memory: module-level Python dicts in `store.TABLES` keyed by UUID, one per entity type, plus a module-level logical clock. No SQLite, no files, no `/tmp` cache, no seeding — every `start.sh` boot yields empty tables and the initial clock. Verified: after kill + `bash start.sh`, all lists return `total_count: 0` and the clock reads `2026-08-01T00:00:00Z`. A global monotonic sequence number keeps `created_at ASC` ordering deterministic.

**Most intricate calculations**

1. **`cutout_value`** — two distinct sheet selectors (booking: max week_start → max published_at → min created_at among PUBLISHED; grading: sheet whose half-open week contains the certificate `issue_date` among PUBLISHED/CLOSED/SUPERSEDED, fallback to the booking estimate), per-line `round_half_up` then sum (never sum-then-round), zero contribution for missing lines, PRIMAL single-line variant.
2. **`allocation_waterfall`** — per-line remaining supply, tier-then-creation ordering, earmarked grants drawing from `committed − delivered − earmarked` at contract price without consuming sheet supply, partial grants, and mid-run `CREDIT_HOLD` transitions via immediate exposure recompute (strict `>` against the limit).
3. **`claim_final_settlement` vs `claim_provisional_credit`** — different caps (per-type 0.4–1.0 vs flat 0.80), min-keyed on claimed amount vs current offer, plus the conditional 15000-cent freight allowance (TEMPERATURE_ABUSE + BREACHED).
4. **`aging_adjusted_unit_value`** — single final rounding over `base × grade_mult × age_band_mult` with boundary-inclusive bands (≤7, 8–14, 15–21, ≥22), triggered by grading, revocation, inspection, release, and clock advances.
5. **`hedging_exposure`** — four-component netting with per-component status/week filters and the §2.7 basis-price selector.

**PRD ambiguities resolved**

- **Supersede vs week-conflict**: publishing a same-week sheet naming `supersedes_sheet_id` would always fail the conflict check if the target counted. I exclude the supersede target from the conflict scan — otherwise the §3.2 supersede cascade could never fire.
- **Fabrication-post capacity**: implemented the literal formula `occupied_lbs + total_output_weight ≤ capacity_lbs` (occupied still includes the about-to-be-consumed input lot), matching the formula stated identically in PRD §2.11 and scaffold validation 11.
- **Waterfall grant when the earmarked contract is no longer OPEN** (e.g., DEFAULTED by a clock sweep, which does not cancel REQUESTED earmarks): pool treated as 0 → grant 0 → SHORTFALL.
- **Returns-lot "source warehouse"** when FIFO draws span warehouses: warehouse and `production_date` both taken from the oldest (first-drawn) lot.
- **Explicit `lot_ids` that cannot cover `shipped_lbs`**: rejected atomically with `ERR_INSUFFICIENT_SUPPLY` (PRD only specifies the sufficiency check for FIFO).
- **Ownership vs. existence ordering**: priority-3 ownership is evaluated only when the target/body reference resolves; otherwise the request falls through to shape (400) → path (404) → FK (422). Shape validation always precedes path-existence checks.
- **Offer-cap placement**: state check → `offer_round < 3` → OCC version (the scaffold's precondition order; the PRD pipeline has no explicit category for the cap).
- **`version` starts at 1**; customer/warehouse records bump version on recompute only when a value actually changes; `created_at`/`updated_at` use a monotonic wall clock (logical clock drives `published_at`, ages, week checks, sweeps); weights are quantized to 2dp half-up at ingestion; `loss_lbs` may be 0 and `credit_limit_cents` may be 0; shipment create against a non-CONFIRMED allocation returns the generic `ERR_INVALID_STATE` (409).

**Verification**

Two ad-hoc suites (162 checks total) run against fresh `bash start.sh` boots: **114/114** and **48/48** pass, covering per-line cutout rounding incl. a half-up boundary proof (1666.5 → 1667), grading fallback, age-band repricing across clock advances, credit-hold trigger/release, tier-ordered partial grants, shortfall, supersede/close/contract-cancel/supplier-suspend cascades, fabrication post/void unwind with mass-balance and yield-band routing, FIFO insufficiency atomicity, sticky temperature breach, claim negotiation cap + OCC 412s, exposure netting, and validation-priority orderings (shape-before-404, ownership-before-shape, etc.).

## Step 7: Run Tests and Iterate — 2026-08-15T10:35:00.000Z

## Summary — Clean 8/8-round sweep achieved (99/99 tests passing in every round)

**Iterations run:** 3 sweeps (8 parallel rounds each).

**Tests deleted:** None.

**Fixes applied to `test_suite/` (2):**
1. `/home/ubuntu/github/CodingPRD/tasks/task_2025_meat_protein_wholesale_trading/test_suite/test_03_purchase_orders_and_receiving.py` — `test_po_receive_blocked_when_supplier_suspended`: changed expected error from `ERR_SUPPLIER_SUSPENDED` to `ERR_PO_NOT_BOOKED`. PRD §3.1's suspension cascade cancels the supplier's BOOKED POs, and §2.8's pipeline ("Earlier stages mask later ones") evaluates the target-state check (stage 7) before the cross-entity supplier check (stage 8), so `ERR_PO_NOT_BOOKED` is the uniquely-derivable outcome. The test's second assertion (PO lands in `CANCELLED`) was PRD-faithful and kept; docstring updated to cite §3.1 + §2.8.
2. `/home/ubuntu/github/CodingPRD/tasks/task_2025_meat_protein_wholesale_trading/test_suite/test_09_shipments_and_cold_chain.py` — `test_fifo_lot_selection_oldest_first`: fixed arithmetic slip in the final assertion (`300 - 100 = 200` remaining, not `100`). PRD §3.7's FIFO draw uniquely derives 200; the implementation was correct.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `implementation/` (1 — infrastructure robustness, no API behavior change):**
3. `/home/ubuntu/github/CodingPRD/tasks/task_2025_meat_protein_wholesale_trading/workspace/implementation/`: renamed the server entrypoint `app.py` → `protein_desk_server.py` and updated `start.sh`'s `exec` line accordingly (with a comment explaining why).

**Key diagnostic finding — the flakiness root cause:** Sweep 2 produced `ConnectionError: Connection reset by peer` in `test_insufficient_supply_returns_409` in 7/8 rounds (round 3 clean). Server-side logs (`/tmp/prd_bench_server_<port>.log`) showed the server receiving **SIGTERM** ("Terminated", not the runner's SIGKILL "Killed") mid-test, at instants synchronized across all 8 of my rounds AND across other tasks' sweeps on this shared host (10:03:49, 10:04:22/26, 10:05:04). Co-tenant pipelines run host-wide `pkill -f "python3 app.py"` waves between their sweep restarts; ~10 other tasks already renamed their entrypoints to dodge it (documented in their start.sh files, e.g. task_1363, task_1293). Any test mid-flight when a wave landed failed spuriously — this was environmental interference, not an implementation or test bug. After the rename, server logs confirmed zero SIGTERM events across the full sweep, and all 8 rounds passed 99/99.

## Step 8: Finalize PRD — 2026-08-15T10:24:00.000Z

## Summary

**PRD.md vs PRD_FINALIZED.md:** 395 lines vs 395 lines, 0.0% delta — byte-identical (same md5: `49965cfd6ee8f5e27b44613b38458c39`).

**Changes:** Zero edits. All three `<step_7_diff>` items verified as already uniquely pinned by the PRD (or out of PRD scope).

### Per-item verification log (zero edits, so verification log instead of search log)

**Item 1 — test_03 `test_po_receive_blocked_when_supplier_suspended` (`ERR_PO_NOT_BOOKED`, not `ERR_SUPPLIER_SUSPENDED`)**
- (a) Subject: error reported when receiving a purchase order whose supplier was suspended while the PO was BOOKED.
- (b) Impl paths enumerated and read: `workspace/implementation/routes_reference.py:79-105` (`set_supplier_status` — suspension cascade cancels every BOOKED PO of the supplier with `cancel_reason="SUPPLIER_SUSPENDED"`, matching PRD §3.1 line 160 verbatim); `workspace/implementation/routes_procurement.py:118-165` (`receive_po` — checks path existence (5) → body FK (6) → PO-status-BOOKED target state (7, line 131-132, raises `ERR_PO_NOT_BOOKED`) → supplier-ACTIVE cross-entity check (8, line 134-136), never reached after the cascade). Also enumerated the only other stage-7-vs-8 site touching the same rule, `create_po` (routes_procurement.py:51-90): creation has no stage-7 target, so stage 8 fires directly — consistent with the same pipeline. The corrected test's second assertion (PO lands `CANCELLED`) matches the cascade.
- (c) PRD passage that already covers it: §2.8 line 115 ("Earlier stages mask later ones") + stage 7 (line 123, lists `ERR_PO_NOT_BOOKED`) ordered before stage 8 (line 124, `ERR_SUPPLIER_SUSPENDED`); §3.3 line 184 lists receive preconditions in the same order ("The purchase order must be `BOOKED`, else `ERR_PO_NOT_BOOKED`. Its supplier must be `ACTIVE`, else `ERR_SUPPLIER_SUSPENDED`."); §3.1 line 160 pins the cascade that makes the PO non-BOOKED. Behavior uniquely derived in three independent places — no edit.

**Item 2 — test_09 `test_fifo_lot_selection_oldest_first` (final assertion 300−100=200)**
- (a) Subject: FIFO lot draw arithmetic on shipment creation.
- (b) Impl paths enumerated and read: `workspace/implementation/routes_logistics.py:116-154` (explicit-lot branch and FIFO branch; FIFO pool = AVAILABLE lots of the allocation's product, sorted by `(production_date, _seq)`, drawing `min(need, current_weight_lbs)` per lot until covered, zero-drawn lots → `DEPLETED`); cross-checked the returns-lot path at routes_logistics.py:326-336 (uses the same drawn-lot ordering for `production_date` copy) and the DEPLETED-terminal claim against PRD §3.4 line 190. The corrected test (300 lb older lot drained to 0, 100 lb taken from the 300 lb newer lot leaving 200) is a direct arithmetic consequence.
- (c) PRD passage that already covers it: §3.7 line 230 ("ranked by `production_date` ascending with earlier `created_at` breaking ties; the selector walks that ranked list drawing from each lot the lesser of the remaining need and the lot's `current_weight_lbs` until the shipped weight is covered, and any lot drawn to zero moves to `DEPLETED`"). Uniquely derives 200 — the fix was a pure test-side arithmetic slip, no PRD silence. No edit.

**Item 3 — implementation entrypoint rename `app.py` → `protein_desk_server.py`**
- (a) Subject: server process filename.
- (b) Impl paths enumerated and read: `workspace/implementation/start.sh` (execs `python3 protein_desk_server.py` with a comment explaining the co-tenant `pkill -f "python3 app.py"` interference); `workspace/implementation/protein_desk_server.py`. Zero API behavior change.
- (c) PRD coverage: grepped PRD.md for `app\.py|app\.run|Flask|filename|start\.sh` — zero hits. The PRD deliberately specifies API behavior only; process/entrypoint naming is the build contract's concern (INSTRUCTION.md), not the PRD's. No edit.

**Conclusion:** `PRD_FINALIZED.md` at `/home/ubuntu/github/CodingPRD/tasks/task_2025_meat_protein_wholesale_trading/workspace/PRD_FINALIZED.md` is the unchanged copy of PRD.md — every Step 7 change traced either to a test-side correction toward behavior the PRD already uniquely determines, or to an infrastructure rename with no API-surface effect.

## Step 9: Complete PRD — 2026-08-15T10:43:00.000Z

Done. PRD_COMPLETED.md is written with 25 diff hunks (26 distinct pins/revisions; two share one paragraph line). Summary below.

## Exit summary

**File**: `/home/ubuntu/github/CodingPRD/tasks/task_2025_meat_protein_wholesale_trading/workspace/PRD_COMPLETED.md`
**Source**: `PRD_FINALIZED.md` (byte-identical to `PRD.md`) — 395 lines / 72,603 chars → **PRD_COMPLETED.md** — 397 lines / 78,021 chars (**+2 lines, +5,418 chars**). All changes are in-paragraph inserts/revisions; no new sections; PRD_FINALIZED.md and PRD.md untouched.

**Counts**: 24 ambiguity-pins, 2 mismatch-revisions.

**Changes** (section — insert|revise — ambiguity|mismatch — what changed — impl ref):

- §2.3 — insert — ambiguity — out-of-range/unparseable `limit`/`offset` are coerced (clamped to [1,100] / floored at 0 / defaults), never rejected — implementation/helpers.py:220-235
- §2.4 — insert — ambiguity — timestamp sources pinned: `created_at`/`updated_at`/`api_request_timestamp` are wall-clock; logical clock governs only domain readings; `TemperatureReading.recorded_at` is client-supplied — implementation/store.py:62-69, implementation/helpers.py:255-272
- §2.4 — insert — ambiguity — clock-set is unconditional (no forward-only check), offset-less instants read as UTC, and sweeps visit candidates in creation order with id arrays in that order — implementation/routes_misc.py:25-55, implementation/helpers.py:201-213
- §2.5 — revise — ambiguity — `version` starts at **1** on creation — implementation/helpers.py:265-272 (`stamp_new`)
- §2.5 — insert — ambiguity — create/mutation payloads are read field-by-field; unknown, system-managed, or computed keys supplied by the client are ignored (server-minted values prevail) — all create handlers, e.g. implementation/routes_reference.py:37-57
- §2.6 — insert — ambiguity — integer-only fields enumerated (all cents amounts, `capacity_lbs`, `shelf_life_days`, `weekly_supply_lbs`, `committed_lbs`); weighed fields accept positive decimals quantized half-up to 2dp; `loss_lbs` and `credit_limit_cents` may be zero; temps/fat/yield accept any number — implementation/routes_trading.py:64-65, implementation/routes_sheets.py:111-112, implementation/routes_procurement.py:58-59,293-295, implementation/routes_reference.py:133,193,246
- §2.8 stage 3 — insert — ambiguity — when the acted resource does not exist, ownership is unevaluable and the stage-5 404 is reported — implementation/routes_trading.py:245-251, implementation/routes_logistics.py:273-277
- §2.8 stage 10 — revise — ambiguity — week-conflict check at publish exempts the `supersedes_sheet_id` target — implementation/routes_sheets.py:235-243
- §2.8 stage 16 — insert — ambiguity — an explicit `lot_ids` list that cannot cover the weight also fails with `ERR_INSUFFICIENT_SUPPLY` — implementation/routes_logistics.py:128-130
- §2.10 — insert — ambiguity — the exposure aggregate is rounded half-up to whole cents after the zero floor — implementation/helpers.py:490-500
- §3.1 — revise — ambiguity — supplier suspension `reason` is optional; `suspension_reason` is null when omitted — implementation/routes_reference.py:83-90
- §3.1 — revise — ambiguity — `max_fat_pct` is required for PRIMAL/SUBPRIMAL (else `ERR_INVALID_REQUEST`) and ignored/stored-null for CARCASS — implementation/routes_reference.py:245-252
- §3.1 — revise — **mismatch** — `expected_yield_pct` "between 0 and 100" softened to nominal; all three yield percentages are stored as supplied with no range validation (impl enforces none) — implementation/routes_reference.py:310-312
- §3.2 — insert — ambiguity — duplicate (sheet, product) lines are permitted; calculations needing "the" line use the earliest-created match — implementation/helpers.py:367-373
- §3.2 — revise — ambiguity — publishing a sheet whose supersede target shares its `week_start_date` succeeds (target exempt from the conflict check) — implementation/routes_sheets.py:238-239
- §3.3 — insert — ambiguity — when no sheet is PUBLISHED at booking, every line lookup misses and the estimate is zero cents — implementation/helpers.py:350-364, 387-408
- §3.4 — revise — ambiguity — grading-time sheet selector tie-break: latest `published_at`, then earliest `created_at` — implementation/helpers.py:414-427
- §3.4 — revise — ambiguity — `grade_result` on a non-`USDA_GRADE` certificate is accepted/stored when a declared grade, else `ERR_INVALID_REQUEST` — implementation/routes_claims.py:255-261
- §3.5 — insert — ambiguity — `total_output_weight_lbs` and `yield_efficiency_pct` are quantized half-up to two decimals — implementation/routes_procurement.py:336-338, 428-429
- §3.6 — revise — ambiguity — earmarked contract no longer OPEN at run time: pool is zero, allocation falls to SHORTFALL, sheet supply untouched — implementation/routes_sheets.py:325-336
- §3.6 — revise — **mismatch** — "supply exhausted or the credit gate's aftermath" replaced: a zero grant means the available pool (sheet or contract) is exhausted; the credit gate never fires inside a run — implementation/routes_sheets.py:340-363
- §3.6 — revise — ambiguity — auto-settle to SETTLED pinned to deliveries against an **OPEN** contract — implementation/routes_logistics.py:290-292
- §3.7 — revise — ambiguity — shipment create against a non-CONFIRMED allocation fires `ERR_INVALID_STATE` (409) — implementation/routes_logistics.py:87-90
- §3.7 — revise — ambiguity — remaining unshipped balance subtracts weight of all earlier shipments regardless of status; a rejected shipment's weight is not returned — implementation/routes_logistics.py:102-108
- §3.7 — insert — ambiguity — explicit-lot draw rule: in listed order, each lot contributes min(remaining need, current weight); EXPIRED beats NOT_AVAILABLE per lot; insufficient named lots → `ERR_INSUFFICIENT_SUPPLY` (409) with nothing decremented; empty `lot_ids` ≡ omitted (FIFO runs) — implementation/routes_logistics.py:75-130
- §3.7 — insert — ambiguity — shipment response carries `lot_ids`: the lots actually drawn, in draw order, omitting zero-contribution entries — implementation/routes_logistics.py:31, 118-147
- §3.7 — insert — ambiguity — temperature readings are payload-stamped and appendable in any shipment status, including after delivery/rejection — implementation/routes_logistics.py:202-231
- §3.7 — revise — ambiguity — earmarked delivery accrues `delivered_lbs` even on a non-OPEN contract, but auto-SETTLED fires only while OPEN — implementation/routes_logistics.py:285-293
- §3.7 — revise — ambiguity — returns lot lands in the warehouse of the oldest drawn lot (production_date asc, creation order tie-break) and copies that lot's production_date — implementation/routes_logistics.py:330-348
- §3.8 — insert — ambiguity — offer/counter check order pinned: state (`ERR_CLAIM_STATE_INVALID`) → offer cap (`ERR_CLAIM_OFFER_LIMIT_EXCEEDED`) → OCC version (`ERR_STALE_CLAIM_VERSION`) — implementation/routes_claims.py:135-145, 163-168
- §3.9 — insert — ambiguity — exposure params validated: missing `product_id`/`week_start` → `ERR_INVALID_REQUEST` (400); unknown product → `ERR_PRODUCT_NOT_FOUND` (404); `week_start` need only be an ISO date (no Monday rule), matched by exact date equality — implementation/routes_misc.py:76-85

All nine generation-time scrutiny items were verified in code and are covered above (version=1; unknown fields ignored; `ERR_INVALID_STATE` for non-CONFIRMED shipment create; same-week supersede publishes successfully; non-OPEN earmark → SHORTFALL; returns-lot warehouse = oldest drawn lot's warehouse; explicit-lot insufficiency → `ERR_INSUFFICIENT_SUPPLY`; cap before OCC; wall vs logical timestamp split).

Pipeline complete: Steps 1–9 all done; PRD_COMPLETED.md exists. Final state: 99/99 tests pass in all 8 parallel stability rounds under per-test-server isolation.
