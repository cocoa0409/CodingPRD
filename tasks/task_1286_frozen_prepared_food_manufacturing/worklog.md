# Worklog — task_1286_frozen_prepared_food_manufacturing

## Step 1: Create Task Directory — 2026-08-12T19:23:00.000Z

Task directory `tasks/task_1286_frozen_prepared_food_manufacturing/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher (per command args); Step 1 treated as DONE. Difficulty directive from user: "harder than expert level" — forwarded to scaffold generator as a beyond-Expert calibration target.

## Step 2: Generate Scaffold — 2026-08-12T20:42:00.000Z

All three scaffold artifacts are generated and lint-clean. Summary:

## Files written (all three confirmed)
- `/home/ubuntu/github/CodingPRD/tasks/task_1286_frozen_prepared_food_manufacturing/SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1286_frozen_prepared_food_manufacturing/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1286_frozen_prepared_food_manufacturing/SCAFFOLD_CORNER_DESIGN.yaml` — single top key `scaffold_corner_design`

## Counts (beyond-Expert calibration)
- **Entities: 14** — Recipe, RecipeComponent (self-referential BOM), CoPackCustomer, ProductionOrder, ProductionBatch, BlastFreezerCell, FreezingCycle, PackagingLine, LineRun, FilmSupplyLot, CCPCheck (append-only), StorageSlot, FinishedGoodsLot, Complaint
- **State machines: 8** — 4 non-linear (batch rework loop KITTED→ON_HOLD→REWORK→KITTED, lot QA_PENDING↔REJECTED, lot RELEASED↔QUARANTINED, film quarantine loop, recipe DRAFT↔APPROVED), plus compound order auto-progression
- **Calculations: 9** — incl. dual-variant shelf-life expiry (provisional planned-date vs final actual-date) and PER_CASE/PER_KG co-pack billing; mode-(a) exponent/clamp/sub-assembly-recursion scale-up; mode-(b) pinned round-per-run-then-sum film reservation; threshold contagion (lot count ≥3, recipe rate ≥0.005); best-fit cell selector with created_at/cell_code tie-break
- **Validations: 12** ordered priorities (auth → segregation → customer scope → shape → existence → OCC 412 → state → safety → temporal → constraint → fiscal), enabling two distinct priority-conflict pairs (state-vs-safety, safety-vs-temporal)
- **Endpoints: 74** (incl. `POST /plant/_clock/set_current_utc` with pinned default 2026-08-01T00:00:00Z; full FK reverse-reachability)
- **Errors: 33** — all referenced by validations/transitions and all triggerable via §1.8/§1.9 instances
- **Roles: 7** — segregation_of_duties model (QAManager release vs CCP performer; complaint resolver vs reporter), entity_backed CoPackCustomer with cross-customer scope checks
- **Concurrency rules: 2** — true OCC races only (batch-create on order version; superseding cycle-create on batch version), both 412/ERR_STALE_VERSION

## Design instances
- **§1.8: 18 instances** (9 rules × 2), every one with fully structured `setup_api_calls` (930 total calls across both files), computed literal asserts (e.g., 90.125 kg scale-up, 44 vs 45 film meters, 750000 vs 244800 cents billing, expiry 2027-08-02 vs 2027-08-03)
- **§1.9: 54 instances** (47 active + 7 `excluded_because` stubs), spanning all nine guide sections: entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_complexity_layers, consistency_model

## Verification
- `scaffold_lint.py` verdict: **clean lint** — all 930 calls conform to §1.5; all 15 FKs reverse-reachable
- Placeholder closure: zero unbound `${var}`; all OCC `expected_*_version` are `${var}`-bound; name uniqueness across the union of both design files (72 names, no dupes); no forbidden concurrency vocabulary; every enum value is producible by a declared transition or input.

## Step 3: Copy Shared Files — 2026-08-12T20:43:00.000Z

Copied ./INSTRUCTION.md → tasks/task_1286_frozen_prepared_food_manufacturing/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-12T20:58:00.000Z

PRD generation complete. `/home/ubuntu/github/CodingPRD/tasks/task_1286_frozen_prepared_food_manufacturing/workspace/PRD.md` written — 346 lines. The two forbidden design files were never opened or referenced.

## Section list

- **§1. Introduction** (2 paragraphs — business context + system scope, `/plant` mount, logical clock)
- **§2. Global Specifications & System-Wide Principles** — 2.1 User and Role-Based Access Control; 2.2 API Response Structure (verbatim block, byte-identical incl. `req_RANDOMALPHANUM123456` and `"data": { }`); 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending, meta fields); 2.4 Request Validation Pipeline (all 12 priority stages with error IDs/statuses); 2.5 Resource Identity and Common Fields (UUID `id`, ISO 8601 3-fractional-digit timestamps, `version`; CCPCheck append-only exception — no `updated_at`/`version`); 2.6 The Logical Clock (default `2026-08-01T00:00:00Z`, `to_iso8601`/`current_utc`); 2.7 Numeric Precision and Rounding (round-half-up per quantity, exact rational complaint rate); 2.8 Optimistic Concurrency Control (both OCC rules); 2.9 Nested Resource Retrieval (left-to-right 404); 2.10 Scheduling Windows and Buffer Discipline (half-open intervals, sanitation/changeover/allergen buffers); 2.11 State Propagation Across the Plant Hierarchy
- **§3. Business Logic & Workflows** (8 subsections, chronological production timeline) — 3.1 Recipe Authoring, Component Structure, and Scale-Up; 3.2 Co-Pack Customers and Production Order Intake; 3.3 Batch Execution: Kitting, Cooking, Holds, and Rework; 3.4 Blast Freezing: Cells, Cycle Booking, and Verification; 3.5 Packaging Lines, Film Supply, and Line Runs; 3.6 Critical Control Point Verification and the Fail Cascade; 3.7 Cold Storage, Lot Disposition, and Co-Pack Billing; 3.8 Complaints, Investigation, and Contagion
- **§4. Endpoint Definitions** — 4-column table (Method / Path / Description / Authorized Roles), all 74 endpoints
- **§5. Error Code Catalogue** — 2-column table, all 33 errors

## Coverage confirmation (every §1.1–§1.7 element rendered into prose)

- **Entities (14):** all 89 `entities[].fields[].name` present verbatim in backticks — PASS; types, defaults, nullability, and initial values expressed (incl. `scale_exponent` default 1.0, `base_changeover_minutes` 45, `case_rate_cents`/`kg_rate_cents` conditionality, null-until-set fields like `cooked_mass_kg`, `actual_end`, `yield_pct`, `slot_id` immutability)
- **State machines (8 machines, 45 transitions):** every from→to pair named with actor, preconditions paired to their error IDs, and side effects stated — incl. the CCP_FAIL 3-hop cascade, order auto-completion, cycle supersede-before-validation, film reservation release on cancel, rework loops
- **Calculations (9):** all rendered as precise operator-free prose passing the reconstruction test — recipe_scale_up (clamp 0.25/8.0, topological exponent product, PACKAGING forced 1.0), film_reservation (0.42/0.35 m, 6% waste, pinned per-run rounding order), freezer_cycle_duration (ceil division, 1.25 thermal factor, 4h floor, −18 °C + 2h grace verification), shelf_life_expiry (dual provisional/final variants with distinct consumers), copack_billing (PER_CASE vs PER_KG, aggregate-only rounding), complaint_contagion (inclusive thresholds 3 and 0.005, 90-day half-open trailing window, exact rational arithmetic), cell_auto_select (best-fit ranking with created_at/cell_code tie-breaks), pack_out_math (12/6 case packs), storage_occupancy (inclusive fill invariant)
- **Validations (12 priorities):** full pipeline ordering in §2.4 plus per-workflow trigger prose; segregation applies_to (release + resolve) and OCC applies_to (batch create + cycle create) enumerated exactly
- **Endpoints (74):** all in §4; inputs/query/path identifiers 70+13 all present; side effects narrated in §3
- **Errors (33):** every ID mentioned in §1–§3 prose and listed in §5
- **Roles (7):** exact spellings; identity prose for all — six opaque roles individually named, `CoPackCustomer` entity-backed with `copack_customer_id` ownership comparison

## Hard Contract reports

Field coverage check: entities[].fields 89/89, endpoints request_body/input 70/70, path_params 13/13 — PASS
Rule coverage check: validations 12/12, OCC 2/2, transitions 45/45, calculations 9/9, validation conditions 12/12, side effects all, structured fields 89/89, sibling-branch symmetry 8 groups — PASS
Path purity check (§3 only): 603 backtick tokens, 0 path tokens, 0 bare HTTP methods — PASS

All three contracts PASS. §2.2 emitted verbatim; §4 table has exactly 4 columns; §5 table has exactly 2 columns; PRD.md ends at §5 with no audit footer.

## Step 5: Generate Unit Tests — 2026-08-12T21:25:00.000Z

Generation complete and all self-checks pass. Final summary:

## Deliverables

**test_helpers/ (9 files, 1729 lines)** — `/home/ubuntu/github/CodingPRD/tasks/task_1286_frozen_prepared_food_manufacturing/test_helpers/`
- `types.py` (14 status enums + 14 entity TypedDicts; `CCPCheck` correctly omits `updated_at`/`version` per the PRD's append-only rule)
- `api_client.py` (`ApiClient(GenericApiClient)`, 54 endpoint methods covering every PRD §4 endpoint)
- `api_errors.py` (33 error IDs + HTTP map, registered via `set_error_http_status_map`)
- `assertions.py`, `factories.py`, `constants.py` (SCALE_MIN/MAX, MIN_DWELL, WASTE_PCT, case packs, contagion thresholds, 545-day rule, changeover constants)
- `test_users.py` (shared headers for the 6 opaque roles + `make_copack_customer_headers` for the entity-backed role + per-instance builders for segregation-sensitive QA roles)
- `fixtures.py` (5 tiers: creators → `setup_kitted/cooked/frozen_batch` → `setup_qa_pending/releasable/released/stored_released_lot` → `setup_contagion_scenario` building the 40-call two-batch shipped-and-complained state; all OCC version reads are dynamic)

**test_suite/ (9 files, 83 tests)** — `test_01_recipes_and_scale_up.py` (10), `test_02_orders_batches_occ.py` (10), `test_03_freezing_cycles.py` (14), `test_04_packaging_film.py` (15), `test_05_lots_and_billing.py` (11), `test_06_storage_and_withdrawal.py` (7), `test_07_quality_cascades_complaints.py` (9), `test_08_security_and_envelope.py` (7)

## Coverage
- **Queue A (Difficulty): 36 tests / 18 instances — 2 each, zero shortfalls**
- **Queue B (Corner): 47 tests / 47 non-stub instances — 1 each, zero shortfalls**; 7 `excluded_because:` stubs not translated, all cross-references verified to resolve

## Instances skipped
None wholesale. Partial adjudications (PRD-first two-condition filter applied to individual assert lines):
1. **Scale-preview instances** (`recipe_scale_up_nonlinear_exponents`, `scale_preview_clamps_factor_low`): per-line `scaled_qty` key is never named in the PRD (only `target_units`/`scale_factor`/`lines`) — asserted factor passthrough + both clamp branches + one-entry-per-component cardinality; dropped per-component quantity literals (response shape not uniquely derivable).
2. **`complaint_valid_contagion_cascade`**: dropped `releasable_cases == 0` — PRD defines `releasable_cases` only via release/quarantine/recall deltas (yielding 1000, not 0; the design assumes recompute-as-sum). Lot-level cascade (count 3, both lots QUARANTINED at rate exactly 0.005) kept.
3. **`withdraw_expired_lot_rejected`**: dropped the DESTRUCTION branch (PRD names no non-shipment purpose token); kept SHIPMENT-past-expiry → `ERR_LOT_EXPIRED` plus the exact `final_expiry_date` value.
4. **`revise_recipe_with_active_batch_rejected`**: design's recovery path (cancel a KITTED batch) is impossible per PRD; repaired via hold → cancel → revise, same asserted outcomes.
5. **`occ_stale_version_on_batch_create`**: design's "version 2 after first batch" contradicts PRD §3.2 (first batch: +1 add, +1 auto `IN_PROGRESS`); asserted stale→412/fresh→201 and the unambiguous +1 increment on an already-`IN_PROGRESS` order.
6. Borderline-kept and flagged: `hold_reason == "CCP_FAIL:METAL_DETECTOR"` (PRD pins the marker format "CCP-fail colon check-type"); `version == 1` at creation (established convention in prior benchmark suites); `purpose: "SHIPMENT"` token (PRD's uniform UPPERCASE enum convention).

## Stage 2 self-check verdict: PASS
Every one of the 83 tests carries exactly one `Design: Difficulty/<rule>/<name>` or `Design: Corner/<section>/<name>` tag as the final docstring line, all resolving to real instances; 157/157 quoted PRD spans survive whitespace-normalized literal match against PRD.md; zero `skip`/`skipif`/`xfail` markers; `pytest --collect-only` collects all 83 tests cleanly.

## Step 6: Generate Implementation — 2026-08-12T21:25:00.000Z

Implementation complete and verified. Summary:

## File list (`tasks/task_1286_frozen_prepared_food_manufacturing/workspace/implementation/`)

- `start.sh` — guarded-install launcher (`pip install` only if flask import fails), `exec python3 app.py` foreground
- `requirements.txt` — flask>=3.0,<4.0
- `app.py` — Flask entry, ApiError/404/405/generic handlers, binds `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory STORE dicts (14 collections), UUID ids, `_seq` ordering, wall-clock `created_at`, logical clock starting exactly `2026-08-01T00:00:00Z`; no seeding anywhere
- `errors.py` — all 33 catalog errors with HTTP statuses
- `response.py` — envelope (`meta.api_request_id` `req_…`, 3-fraction-digit timestamps, `response_type`, `data`), pagination `limit/offset/total_count/has_more` (defaults 10/0, clamp 1–100)
- `middleware.py` — X-User-ID + X-User-Role auth (401), 7-role RBAC (403)
- `util.py` — Decimal/round-half-up helpers, ISO datetime parsing, field validators, domain constants
- `services.py` — all derived-field computations, window/buffer checks, cascades
- `serializers.py`, `routes/` (9 modules: clock, recipes, customers, orders, freezer, packaging, ccp, storage, complaints)

## Coverage

- **Endpoints: 74/74** — Flask url_map enumerated, exact match to PRD §4 table (methods + paths)
- **Error catalog: 33/33** — every error ID is raised in code with the catalogued HTTP status
- **State machines: 8/8** — Recipe (approve/revise/retire with component + acyclic + busy gates), ProductionOrder (auto IN_PROGRESS, auto COMPLETED, cancel cascade), ProductionBatch (kit/cook/auto-FROZEN/auto-PACKED/complete/hold/resume with CCP_FAIL gate/rework loop/cancel cascade), FreezingCycle (start/complete VERIFIED-FAILED/void/supersede-before-window-check), LineRun (schedule/start/complete with lot creation/cancel with film release), FilmSupplyLot (quarantine/release), FinishedGoodsLot (release with 4 gates, reject/rework/quarantine/recall, auto-DEPLETED), Complaint (investigate/resolve with segregation + 3-hop contagion)
- **Calculations: 9/9** — recipe_scale_up (topological, clamp [0.25, 8.0], exponent chains with PACKAGING forced to 1.0), film_reservation (per-run round-half-up before aggregation, inclusive equality), freezer_cycle_duration (ceil, 1.25× when entry>0, 4h floor, -18°C + 2h grace at complete), shelf_life_expiry (provisional from planned_start vs final from actual_end), copack_billing (PER_CASE/PER_KG, aggregate-round-once, house orders null), complaint_contagion (inclusive threshold 3; exact rational 200·affected ≥ shipped; half-open (clock−90d, clock] window), cell_auto_select (capacity ASC, created_at, cell_code), pack_out_math (ceil cases 12/6, 3-dec kg, 2-dec yield), storage_occupancy (inclusive capacity, DEEP class > 545 days)
- **start.sh contract: confirmed** — reads `$PORT`, binds `0.0.0.0` (verified via external IP), `exec` foreground, HTTP-ready in ~1.5s; fresh-boot emptiness proven by boot-kill-reboot test (second boot `total_count = 0`)

## Key design decision

All `source: computed` fields (film meters, slot occupancy, cell status, `releasable_cases`, `billed_amount_cents`, yield, units totals, expiry dates, `valid_complaint_count`, `days_before_expiry`) are **derived on read** from base records, so every cascade ledger effect (CCP-fail film release, quarantine releasable-case drop, billing recompute) is exact by construction and cannot drift. Verification: 5 custom end-to-end suites pass against fresh boots — lifecycle, CCP fail cascade + rework loop, supersede/sanitation/auto-select, changeover buffers (45/120/same-customer), both billing variants, contagion boundaries, segregation, customer scope, OCC (412 before state per the §2.4 pipeline), and envelope shape.

One real bug was found and fixed during verification (`new_customer` NameError in `line_window_conflict`), plus the `billed_amount_cents`-null-until-first-release rule from PRD §3.2.

## Step 7: Test-Iterate Loop — 2026-08-12T22:15:00.000Z

Iteration 1 sweep (8 parallel rounds): 75/83 in every round — 8 deterministic failures, zero flaky variance.

Diagnosis (PRD-first protocol): all 8 failures were test-artifact bugs; the implementation was PRD-faithful in every rejection. No test deletions (every asserted rule traced to verbatim PRD prose with unique derivability). No implementation changes.

Fixes applied:
- `test_suite/test_04_packaging_film.py` — `TestQuarantinedFilmPriority._quarantined_setup` referenced the `api` pytest fixture without receiving it (NameError); threaded `api` through the helper and both call sites.
- `test_suite/test_05_lots_and_billing.py` — same scoping bug in `TestReleaseRejectedLotPriority._rejected_lot`; threaded `api` through.
- `test_suite/test_06_storage_and_withdrawal.py` — added missing `setup_releasable_lot` import (NameError).
- `test_helpers/fixtures.py` — `setup_contagion_scenario` created batch 2 only after batch 1 completed, but PRD §3.2 auto-completes the order at that moment (every batch resolved, ≥1 COMPLETED), so the second `create_batch` correctly hit `ERR_ORDER_NOT_OPEN`. Both batches are now created up front before either is produced.
- `test_helpers/factories.py` — `create_copack_customer_payload` unconditionally injected `case_rate_cents: 1500`; for `billing_method="PER_KG"` that violates PRD §3.2 ("null otherwise ... `ERR_INVALID_REQUEST`"). The factory now drops `case_rate_cents` and defaults `kg_rate_cents` when the method is PER_KG.

Iteration 2 sweep: 82/83 + 1 error in all 8 rounds — `test_rework_loop_closes_back_through_kit_and_cook` errored in setup with the runner's "API server could not be restarted" readiness-poll timeout (15 s window). Solo rerun passed 83/83, and a diagnostic 8-round sweep with server stderr capture passed 8×83/83 — runner-level readiness flake under peak 8-way load, not a test or implementation defect (no server crash logged; boot attempts all clean).

Iteration 3 sweep (exact contract command): **8 rounds × 83/83 passed.** Clean exit.

## Step 7: Run Tests and Iterate — 2026-08-12T22:00:00.000Z

Clean 8-round parallel sweep achieved: **8 rounds × 83/83 passed** with the exact contract command.

## Summary

- **Iterations run:** 3 sweeps (8 parallel rounds each), plus 1 solo diagnostic round and 1 diagnostic sweep with server-stderr capture.

- **Tests deleted:** None. All 8 failing tests traced to verbatim PRD prose with unique derivability (PRD §2.4 stage ordering, §2.1 segregation, §3.5 film quarantine, §3.7 lot-release state gate and PER_KG billing, §3.8 contagion thresholds).

- **Fixes applied to `test_helpers/`:**
  - `factories.py` — `create_copack_customer_payload`: unconditionally injected `case_rate_cents: 1500`, which PRD §3.2 forbids for `PER_KG` ("null otherwise ... `ERR_INVALID_REQUEST`"); the implementation was correctly rejecting it. Factory now drops `case_rate_cents` and defaults `kg_rate_cents` when `billing_method == "PER_KG"`. (Fixed `test_billing_per_kg_variant`.)
  - `fixtures.py` — `setup_contagion_scenario`: created batch 2 after batch 1 completed, but PRD §3.2 auto-completes the order at that moment, so the second batch create correctly hit `ERR_ORDER_NOT_OPEN`. Both batches are now created up front, before either is produced. (Fixed `test_third_complaint_quarantines_origin_lot`, `test_recipe_rate_contagion_quarantines_sibling_lot`.)

- **Fixes applied to `test_suite/`:**
  - `test_04_packaging_film.py` — `_quarantined_setup` referenced the `api` fixture without receiving it (NameError); threaded `api` through helper + both call sites. (Fixed 2 tests.)
  - `test_05_lots_and_billing.py` — same scoping bug in `_rejected_lot`; threaded `api` through. (Fixed 2 tests.)
  - `test_06_storage_and_withdrawal.py` — added missing `setup_releasable_lot` import. (Fixed 1 test.)

- **Fixes applied to `implementation/`:** None — the implementation was PRD-faithful in every rejection.

- **Flakiness note:** iteration 2 showed one identical infra-level error in all 8 rounds (`test_rework_loop_closes_back_through_kit_and_cook`: runner's 15s server-restart readiness poll expired under peak 8-way load). It did not reproduce in the solo round, the diagnostic sweep with captured server logs (no crash — boots were clean), or the final confirmation sweep. Runner-level readiness-window event, not a test or implementation defect; no action taken.

## Step 8: Finalize PRD — 2026-08-12T22:08:00.000Z

**PRD_FINALIZED.md is byte-identical to PRD.md — zero edits were warranted.**

- **Line counts**: PRD.md = 345 lines, PRD_FINALIZED.md = 345 lines, **0.0% delta**.
- File written: `/home/ubuntu/github/CodingPRD/tasks/task_1286_frozen_prepared_food_manufacturing/workspace/PRD_FINALIZED.md`

### Analysis of each `<step_7_diff>` item

Every Step 7 fix was test-side; the implementation was PRD-faithful in every rejection, and every behavior the 8 originally-failing tests exercised is already uniquely pinned by verbatim PRD prose. Per the method ("not every item is a PRD silence — some are pure fixture bugs"), no PRD patch traced from any item:

- **§3.2 rate-field conditionality** (factories.py `create_copack_customer_payload` fix; fixed `test_billing_per_kg_variant`) — pure fixture bug. PRD §3.2 already states verbatim: "`case_rate_cents` ... required exactly when the method is `PER_CASE` and null otherwise ... supplying the wrong combination is a request-shape failure rejected with `ERR_INVALID_REQUEST`." Impl: `implementation/routes/customers.py:34-53` rejects a non-null `case_rate_cents` under `PER_KG` exactly as written. No PRD silence.
- **§3.2 order auto-completion** (fixtures.py `setup_contagion_scenario` fix; fixed `test_third_complaint_quarantines_origin_lot`, `test_recipe_rate_contagion_quarantines_sibling_lot`) — pure fixture bug. PRD §3.2 already pins auto-completion ("When every batch of an `IN_PROGRESS` order has resolved into `COMPLETED` or `CANCELLED` and at least one of them is `COMPLETED`, the order automatically transitions") and `ERR_ORDER_NOT_OPEN` on batch-add to a non-open order. Impl: `implementation/services.py:393-405` (`order_completion_check`, invoked from batch complete/cancel at `routes/orders.py:236,310`) and `routes/orders.py:134`. No PRD silence.
- **test_04 `_quarantined_setup` NameError** (2 tests) — pure Python scoping bug (`api` fixture not threaded); no behavioral content. Underlying behavior (film quarantine beats window conflict) is pinned by PRD §2.4 stages 9-before-10 and §3.5; impl: `implementation/routes/packaging.py:92-107`.
- **test_05 `_rejected_lot` NameError** (2 tests) — same pure scoping bug. Underlying behavior (release from `REJECTED` → `ERR_LOT_STATE`, state stage 8 before safety stage 9) is pinned by PRD §2.4 and §3.7; impl: `implementation/routes/storage.py:215-237`.
- **test_06 missing `setup_releasable_lot` import** (1 test) — pure import bug. Underlying behavior (segregation of duties at release) is pinned by PRD §2.1 and §2.4 stage 3; impl: `implementation/routes/storage.py:217-222`.
- **implementation/ fixes: none** — no PRD/impl mismatch exists to pin.

### Per-edit pre-edit search log

No edits were committed. For each candidate edit considered (one per substantive Step 7 item), the mandatory enumeration was performed:

1. **(a) Subject**: customer rate-field conditionality under `billing_method`. **(b) Paths enumerated**: `routes/customers.py:24-69` (only creation endpoint and only writer of `case_rate_cents`/`kg_rate_cents`), `services.py:201-219` (`order_billed_amount_cents`, the only reader of the rate fields), `serializers.py` (`customer_out`), plus grep for `case_rate_cents`/`kg_rate_cents` across all of `implementation/`. **(c) Outcome**: PRD §3.2 prose already matches every enumerated path exactly — candidate edit rejected as unnecessary (would be a no-op rewording, which itself risks new mismatch).
2. **(a) Subject**: order auto-completion and batch-create gating. **(b) Paths enumerated**: `services.py:37,393-405` (`BATCH_TERMINAL`, `order_completion_check`), both callsites `routes/orders.py:222-237` (batch complete) and `routes/orders.py:293-311` (batch cancel — also triggers the check, consistent with §3.2's "has resolved" phrasing and §2.11's "batches appear and resolve"), batch-create gate at `routes/orders.py:130-134`. **(c) Outcome**: PRD §3.2 already covers all enumerated paths verbatim; no edit.

A fresh implementer reading PRD.md (= PRD_FINALIZED.md) alone already receives every behavioral choice the implementation exhibits along the Step 7 sites, and the no-new-mismatch rule cautioned against gratuitous rewording of prose that is already exact.

## Step 9: Complete PRD — 2026-08-12T22:22:00.000Z

Done. PRD_COMPLETED.md produced at `/home/ubuntu/github/CodingPRD/tasks/task_1286_frozen_prepared_food_manufacturing/workspace/PRD_COMPLETED.md`.

**Source vs output:** `PRD_FINALIZED.md` (345 lines, 60037 chars) → `PRD_COMPLETED.md` (345 lines, 63761 chars; **+3724 chars**). All edits are inline paragraph inserts/revisions; no sections added, line count unchanged.

**Counts:** 23 ambiguity-pins, 1 mismatch-revision.

**Changes (one bullet each):**

- §2.1 — insert — ambiguity — CoPackCustomer list endpoints enforce scope by restriction (own records only); explicit foreign-chain filters (`copack_customer_id`, `lot_id`, `batch_id`) and reading another customer's record yield `ERR_CROSS_CUSTOMER_ACCESS` — customers.py:76, orders.py:71-77, storage.py:84-93, complaints.py:75-88
- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` are clamped (1/100/0), non-integer values rejected `ERR_INVALID_REQUEST` — response.py:42-65
- §2.3 — insert — ambiguity — list sort ties break by creation (insertion) order — response.py:68-75
- §2.6 — insert — ambiguity — clock accepts any valid ISO 8601 instant, forward or backward — clock.py:16-20
- §2.10 — insert — ambiguity — same-customer runs (incl. two house-brand runs) need no changeover gap; house-brand incoming run uses 45 min and never triggers the allergen rule — services.py:331-365
- §3.1 — revise — ambiguity — `shelf_life_days` pinned positive integer; recipe list filterable by `status` — recipes.py:44, 61-64
- §3.1 — insert — ambiguity — `parent_component_id`: nonexistent → `ERR_NOT_FOUND`; different-recipe component → `ERR_INVALID_REQUEST` — recipes.py:119-127, 176-184
- §3.1 — insert — ambiguity — scale-preview `target_units` is a required positive-integer query parameter — recipes.py:319-327
- §3.1 — insert — ambiguity — scale-preview `lines` entry field shape (component_id … effective_exponent, scaled_quantity) — recipes.py:337-349
- §3.1 — insert — ambiguity — topological traversal: creation order among peers, cyclic leftovers (DRAFT only) appended in creation order — recipes.py:273-294
- §3.1 — revise — **mismatch** — PRD said only the component's own exponent is forced to 1.0 for PACKAGING with ancestors' exponents contributing; impl forces 1.0 for every PACKAGING component along the ancestor chain, ancestors included — recipes.py:297-312
- §3.2 — revise — ambiguity — order `units_planned` positive integer; order list filterable by `recipe_id`, `copack_customer_id`, `status` — orders.py:36, 68-83
- §3.2 — revise — ambiguity — batch `units_planned` positive integer — orders.py:124
- §3.4 — revise — ambiguity — cell `capacity_kg`/`min_load_kg`/`pull_down_kg_per_hour` positive integers, `sanitation_minutes` non-negative integer; duplicate `cell_code` or `min_load_kg` > `capacity_kg` → `ERR_INVALID_REQUEST` — freezer.py:34-46
- §3.4 — revise — ambiguity — `load_kg` positive integer, `entry_temp_c` any number — freezer.py:80-81
- §3.4 — insert — ambiguity — verification cascade COOKED→FROZEN applies only if the batch is still COOKED at completion (e.g. not ON_HOLD) — freezer.py:202-206
- §3.5 — revise — ambiguity — duplicate `line_code` → `ERR_INVALID_REQUEST`; `rate_units_per_minute`, `rolls_received`, `meters_per_roll` positive integers — packaging.py:37-43, 246-247
- §3.5 — insert — ambiguity — film-lot quarantine/release from the wrong status → `ERR_INVALID_REQUEST` (400) — packaging.py:283-284, 294-295
- §3.5 — revise — ambiguity — run `units_planned` positive integer — packaging.py:79
- §3.5 — revise — ambiguity — `units_packed`/`film_meters_consumed` positive integers at completion — packaging.py:186-188
- §3.5 — insert — ambiguity — batch auto-advance FROZEN→PACKED only if still FROZEN at run completion; lot still created otherwise — packaging.py:221-223
- §3.6 — revise — ambiguity — failure marker pinned to the exact string `CCP_FAIL:<check_type>` (e.g. `CCP_FAIL:METAL_DETECTOR`) — services.py:427, orders.py:263
- §3.7 — revise — ambiguity — duplicate `slot_code` → `ERR_INVALID_REQUEST`; `capacity_cases` positive integer — storage.py:40-43
- §3.7 — revise — ambiguity — put-away `cases` positive integer; put-away to a slot other than the pinned one → `ERR_INVALID_REQUEST` — storage.py:121, 131-134
- §3.7 — revise — ambiguity — withdrawal `cases` positive integer; `purpose` is a required free-form string where exactly `SHIPMENT` triggers the expiry gate and shipment accounting, any other value (e.g. `DESTRUCTION`) is non-shipment — storage.py:162-185
- §3.8 — insert — ambiguity — complaint filing resolves the lot (and CoPackCustomer scope) before validating remaining body fields, so a missing lot yields `ERR_NOT_FOUND` even with malformed fields; `units_affected` positive integer — complaints.py:31-42
- §3.8 — insert — ambiguity — resolution `notes` validated as string but not persisted on the complaint — complaints.py:137-139, serializers.py:227-239
- §3.8 — revise — ambiguity — contagion affected-volume window membership judged by the complaint's `reported_at` (no resolution timestamp exists) — services.py:466-471

Notable verified non-changes: §2.4 pipeline order matches impl exactly (incl. segregation-before-state on lot release/complaint resolve, window-before-capacity on cycle booking); cycle supersede is atomic (old cycle voided only after validations pass) which the PRD's "becomes VOIDED the moment the new reservation is created" already admits; dwell/film/pack-out/billing/contagion formulas and rounding all match impl constants. Left unpinned as out of PRD scope: HTTP-level fallback handlers (unknown path → `ERR_NOT_FOUND` envelope, 405 → `ERR_INVALID_REQUEST`) in app.py:20-30.

**PIPELINE COMPLETE — all 9 steps done. Final state: 83/83 tests passing across 8/8 parallel stability rounds.**
