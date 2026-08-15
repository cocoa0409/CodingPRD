# Worklog — task_1692_forest_nursery_reforestation_contract

## Step 1: Create Task Directory — 2026-08-14T08:28:00.000Z

Pre-assigned directory `tasks/task_1692_forest_nursery_reforestation_contract/` with `workspace/` subdirectory already created by the pipeline launcher; treated as DONE per instructions.

## Step 2: Generate Scaffold — 2026-08-14T09:36:55.332Z

All checks pass. The scaffold package is complete and verified.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1692_forest_nursery_reforestation_contract/`):

- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys nested inside)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

**Counts:**
- Entities: **14** (Landowner, SeedZone, SeedLot, CropBatch, SeedlingOrder, Allocation, StorageUnit, StoragePlacement, PlantingContract, Crew, CrewAssignment, Shipment, SurvivalSurvey with embedded replant-obligation lifecycle, CostShareEnrollment)
- State machines: **10**, including four cyclic/looping ones (lot quarantine cycle, order amend loop, contract replant loop, enrollment review/payment-hold cycles)
- Endpoints: **68** (includes `POST /reforestation/_clock/set_current_utc` with pinned default `2026-08-01T00:00:00Z`)
- Calculations: 9; validations: 29 (ordered, auth → authz → existence → OCC → state → safety → temporal → constraint → fiscal); errors: 29; roles: 5 (Landowner is `entity_backed:Landowner`, rest opaque); OCC concurrency rules: 2
- §1.8 instances (non-stub): **20** — all 9 rules at ≥2 (combinatorial_formula and boundary_precision_check have 3)
- §1.9 instances (non-stub): **46** full + 10 `excluded_because` stubs, across all 9 claim-extraction sections

**Harder-than-expert design elements:** dual-variant calcs in two domains (projected-vs-graded yield; standard-70 vs cost-share-80 survival thresholds); combinatorial formulas in all three modes ((a) replant-owed with repeat-failure escalation, (b) cost-share per-component rounding pinned, (c) price tier keyed on pre-discount subtotal); a depth-3 grade-shortfall cascade (batch → allocation → order → contract BLOCKED) and a depth-2 survey cascade (contract flip → crew release + enrollment payment hold); two priority-conflict pairs ({state, fiscal} and {safety, temporal}); boundary instances with hand-computed literals (70.00% pass, 210-day lead, 25000-unit fill, 72h handling deadline ±1s, 45-day stock age ±1d); crew half-open+cross-contract-buffer overlap vs storage aggregate-load semantics; storage-load and crew-capacity compensating invariants.

**Verification:** `scaffold_lint.py` verdict block (verbatim): "VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5" (773 calls scanned). Additionally script-verified: name uniqueness across both files (76/76 unique), placeholder binding-order closure, stub → difficulty-instance references, grounds resolution for all §1.8/§1.9 entries, endpoint-role coherence, error catalog fully referenced, and zero forbidden concurrency vocabulary. Two replay-driven design fixes were applied mid-build: allocations reserve against `projected_plantable` for SOWN/LIFTED batches (so the grade-shortfall cascade is reachable), and complete-planting's floor switches to `owed_quantity` on replant cycles (so the escalation instance's replant is legal).

## Step 3: Copy Shared Files — 2026-08-14T09:37:24.729Z

Copied `./INSTRUCTION.md` to `tasks/task_1692_forest_nursery_reforestation_contract/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T10:00:53.778Z

The PRD is generated and all three hard contracts pass.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1692_forest_nursery_reforestation_contract/workspace/PRD.md` — 332 lines.

**Section overview:**
- **§1 Introduction** — 2 paragraphs framing the state forest nursery supply pipeline (seed zones → lots → batches → cold storage → 72-hour shipment window) and the demand side (landowner orders, planting contracts, survival surveys, cost-share), plus the `/reforestation` mount.
- **§2 Global Specifications** — 9 subsections: 2.1 RBAC with all 5 roles and identity semantics (Landowner entity-backed, four opaque operator roles); 2.2 response envelope emitted **verbatim** (diff-verified byte-identical to `section-2.2-response-structure.md`); 2.3 pagination (limit 10/1/100, offset 0, `created_at` ascending); 2.4 common properties (UUID `id`, 3-fractional-digit timestamps, `version` on every mutation incl. cascades); 2.5 the logical clock (startup default 2026-08-01T00:00:00Z, `to_iso8601`/`current_utc`); 2.6 fixed 29-step validation pipeline with left-to-right reference resolution; 2.7 the two OCC rules (`expected_seed_lot_version`, `expected_seedling_order_version` → `ERR_STALE_VERSION`/412) plus enumerated version-bump points; 2.8 precision (ceil/floor/round-half-up rules); 2.9 CASCADE A / CASCADE B overview.
- **§3 Business Logic** — 7 lifecycle-grouped subsections (landowners/zones/lots; batches sow-lift-grade; orders & allocations; storage & shipment pipeline; contracts & crews; surveys & replant cycle; cost-share & payment holds). All 9 calculations rendered as reconstruction-safe prose (seed-transfer 500-ft band-midpoint rule, tiered pricing keyed on pre-discount subtotal, pinned component-wise rounding for cost-share awards, replant escalation factor 1.25 with double cap, oldest-first withdrawal with `placed_on`/`created_at` ordering, crew daily-load and 1-day cross-contract buffer rules, etc.).
- **§4 Endpoint table** — 4 columns only, 68 rows, roles exactly as scaffolded.
- **§5 Error catalogue** — 2 columns only, all 29 error IDs.

**Hard Contract audit notes (Zero-Silence):**
- **Contract 1 (Field-Name Coverage): PASS** — 100/100 required identifiers (entity fields, request-body keys, query params, clock/OCC/retest/`planted_qty`/`reason` inputs) verified present in backticks via scripted diff.
- **Contract 2 (Rule Coverage): PASS** — all state-machine transitions (incl. cyclic quarantine/release, confirm/amend, schedule/reopen, submit/return loops), both cascades with all links, every `applies_to` scope (e.g., lead time on create/confirm/amend; quarantine gate on sow/allocate/ship), priority ordering 1–29 (with the 21.5 stock-sufficiency rule placed between 21 and 22), and sibling branches (spoilage from DISPATCHED/DELIVERED, cancel from 4 contract states) rendered with equal density. One gap found and fixed during audit: `CANCELLED` was missing as a backticked state value; added to both the order-cancel and contract-cancel narratives.
- **Contract 3 (§3 Path Purity): PASS** — 174 distinct backticked tokens in §3, zero paths, zero HTTP methods; the clock endpoint path appears only in §2.5 (allowed).
- No pseudocode operators (`>=`, `:=`, `==`, …) and no fuzzy/approximating wording anywhere in the prose; enum sweep confirmed all 46 state/enum literals present.

## Step 5: Generate Unit Tests — 2026-08-14T10:45:44.722Z

(ran concurrently with Step 6)

All checks pass. Generation complete.

## Summary

**Files written** (under `/home/ubuntu/github/CodingPRD/tasks/task_1692_forest_nursery_reforestation_contract/`):

- `test_helpers/` — 9 modules: `types.py` (14 entity TypedDicts, all with `id/created_at/updated_at/version`; 12 status/role/species enums), `api_client.py` (53 endpoint methods covering every PRD §4 route incl. the logical clock), `api_errors.py` (28 error IDs + HTTP map registered with the framework), `assertions.py`, `factories.py`, `constants.py` (all PRD thresholds), `test_users.py` (4 opaque role headers + mandatory `make_landowner_headers(id)` builder for the entity-backed Landowner role), `fixtures.py` (~40 helpers incl. `setup_graded_batch`, `setup_ready_world`, `drive_to_planted`, `setup_replant_required_world`, `setup_contract_with_fulfilled_replant`), `__init__.py` barrel.
- `test_suite/` — `conftest.py` + 13 numbered test files (`test_01`…`test_13`).

**Test counts:** 84 total — Queue A (Difficulty): **40 tests**, all 20 instances × 2. Queue B (Corner): **44 tests**, 44 of 46 non-stub instances × 1. All 10 `excluded_because` stubs correctly untranslated; every stub cross-reference verified to resolve to a real §1.8 instance.

**Instances skipped (2, both queue B):**
1. `Corner/entities/unknown_payload_field_rejected` — PRD §2.6 rule 18 covers only missing/mistyped required fields and bad enums; it never states that unknown payload fields are rejected, so two PRD-only readers diverge (ignore vs reject). Fails unique derivability.
2. `Corner/endpoints/contract_list_filtered_by_landowner` — PRD §4 says only "List contracts with filters" without naming the query parameters (unlike orders/lots/assignments/etc., whose filters are named in prose); the `landowner_id` param name is not uniquely derivable.

**Corrected literal (flagged):** `Corner/validations/survey_window_rejection_then_rounded_pct` — the index's precomputed `survival_pct == 66.67` is arithmetically wrong for its own inputs (2666/4000×100 = 66.65 exactly). Per the PRD formula ("rounded half-up to exactly two decimal places") the test asserts 66.65; all other instance expectations (window rejection, owed 134, OPEN, REPLANT_REQUIRED) verified correct and asserted verbatim.

**Stage 2 self-checks:** 84/84 tests carry exactly one `Design:` tag as the docstring's final line; 0 unknown/dangling tags; all 144 quoted citation segments survive whitespace-normalized verbatim grep of PRD.md; no skip/xfail markers; no scaffold/table references in generated code; `py_compile` clean; `pytest --collect-only` collects all 84 tests without errors. No sibling task directories were inspected.

## Step 6: Generate Implementation — 2026-08-14T10:37:57.424Z

(ran concurrently with Step 5)

Done. All 68 endpoints from the endpoint table are registered, and the implementation passes three fresh-boot smoke suites covering the full pipeline.

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1692_forest_nursery_reforestation_contract/workspace/implementation/`)

- `start.sh` — guarded install (`python3 -c "import flask"` check, no re-install on per-test reboots), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — flask>=3.0
- `app.py` — thin entry point (imports `server` + all route modules, runs the Flask app)
- `server.py` — store, logical clock, envelope/error helpers, auth, field validators, derived-field computations, calculations (Decimal-based), cascades, serializers
- `routes_a.py` — clock, landowners, seed zones, seed lots, crop batches (sow/lift/grade + CASCADE A)
- `routes_b.py` — seedling orders (pricing tiers, lead time, amend OCC, cancel) + allocations
- `routes_c.py` — storage units, placements (remainder/capacity ceilings, discard)
- `routes_d.py` — planting contracts (site-prep separation of duties, herbicide window, crew overlap/capacity, complete-planting floors) + crews + assignments
- `routes_e.py` — shipments (oldest-first withdrawal, stock-age, handling window, spoilage), survival surveys (threshold variant, owed-quantity escalation, CASCADE B, payment holds), cost-share enrollments (per-component half-up rounding, review loop, pay hold)

## Key design points

- **State**: pure in-memory dicts (`STORE` in `server.py`), zero seeding; every boot starts empty (verified: fresh servers return `total_count: 0` on list endpoints).
- **Endpoint count**: 68 route rules, matching the PRD §4 table exactly.
- **Envelope**: `meta.api_request_id`/`api_request_timestamp` (3-fraction-digit ISO from the logical clock — the server never reads wall time), `response_type` object/array, `data`; pagination fields `limit`/`offset`/`total_count`/`has_more` in meta with defaults 10/0 and clamping to [1,100]; error body `data.error_id`/`data.message`.
- **Auth**: `X-User-ID` + `X-User-Role`, five roles; Landowner is entity-backed (unresolvable id → 401) with ownership scoping on reads/lists/writes (→ 403).
- **Validation precedence** follows PRD §2.6 ordering (auth → authz → existence L-to-R → OCC 412 → state 409 → quarantine → site-prep → lead time → herbicide/survey/handling/stock-age/lift windows → seed-transfer → crew overlap → spacing → window inversion → request shape → fiscal rules → cancellability → payment hold).
- **Math**: `Decimal` throughout — tier pricing keyed on pre-discount subtotal, per-component cost-share rounding before summing, ceil for `required_seedlings` (with the ≥50-acre +0.05 surcharge) and replant escalation (×1.25, capped at min(snapshot, …) then 2×snapshot), floor for `projected_plantable`, half-up 2dp survival pct with the 70.00/80.00 threshold variant.
- **Cascades**: A (grade shortfall releases newest-created ACTIVE allocations → order ALLOCATED→CONFIRMED → contract READY_TO_PLANT→BLOCKED) and B (below-threshold survey → obligation OPEN, crews released, landowner APPROVED enrollments → PAYMENT_HELD, auto-released on fulfill/waive) — each link bumps `version`/`updated_at`.

## Boot smoke test result

`bash start.sh` + curl: server listens within ~2s. Three scripted suites (52 + 34 + 9 assertions) passed clean on fresh boots, covering: 401/403/404/412 precedence, OCC on batch create and order amend, quarantine gate, lift/lead/survey/herbicide/handling/stock-age windows, tiered pricing (6,400,000 → 5,440,000 at the 15% tier), WHITE_OAK projection floor(1000·0.2·0.8·0.88)=140, fractional-acre required_seedlings (0.3·300→90), mark-ready gating, crew overlap, shipment withdrawal + order FULFILLED, spoilage decrementing shipped_quantity, ERR_NOT_CANCELLABLE, both cascades end-to-end, payment hold/pay blocking, and the schedule/reopen/waive obligation loop.

## Step 7: Run Tests and Iterate — 2026-08-14T11:07:45.389Z

All 8 rounds pass 84/84. The benchmark loop is complete.

## Summary

**Iterations run:** 3 sweeps (iteration 2's parallel sweep was killed mid-run at ~79% by host-level contention from a sibling pipeline, so I completed a full single-round sanity run to extract its deterministic failures, then reran the full 8-round sweep as iteration 3).

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1692_forest_nursery_reforestation_contract/test_helpers/fixtures.py` — `setup_ready_world`: parameter `mark_ready=True` shadowed the module-level `mark_ready()` helper, making line 384 `mark_ready(contract["id"])` raise `TypeError: 'bool' object is not callable` in 25 tests. Renamed the parameter to `do_mark_ready`.
- Same file — `if enrollment:` treated callers' `enrollment={}` (empty dict meaning "create a default APPROVED enrollment") as falsy, so no enrollment was created; changed to `if enrollment is not None:`. This fixed `test_survey_threshold_cost_share_landowner` (threshold must rise to 80.00 per PRD §3.6) and `test_below_threshold_survey_holds_enrollment_payment` (`ctx["enrollment"]` was `None`).

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1692_forest_nursery_reforestation_contract/test_suite/test_08_contracts.py` — updated the single caller of the renamed kwarg to `do_mark_ready=False`.
- `/home/ubuntu/github/CodingPRD/tasks/task_1692_forest_nursery_reforestation_contract/test_suite/test_10_surveys.py` — `test_survival_exactly_at_threshold_passes`: the test surveyed `alive_count=7000` against a contract planted with 4000, violating PRD §3.6's "`alive_count` must be non-negative and no greater than that snapshot" precondition (implementation correctly rejected with 400). Fixed to `alive_count=2800` (2800/4000 = exactly 70.00), preserving the equality-at-threshold boundary assertion.

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1692_forest_nursery_reforestation_contract/workspace/implementation/routes_a.py` — `sow_crop_batch`: added the missing lot-state gate. PRD §3.2 "requires the lot to be `AVAILABLE`"; a DEPLETED lot previously fell through to the `sown_grams > remaining_grams` shape check (ERR_INVALID_REQUEST). Now: QUARANTINED → `ERR_LOT_QUARANTINED`; any other non-AVAILABLE (DEPLETED) → `ERR_INVALID_STATE` per §2.6 rule 5.
- `/home/ubuntu/github/CodingPRD/tasks/task_1692_forest_nursery_reforestation_contract/workspace/implementation/routes_b.py` — `create_allocation`: added the missing order-state gate (rule 5, before the rule-21 fiscal ceiling): allocation requires the order in `CONFIRMED` or `ALLOCATED`, else `ERR_INVALID_STATE`. Allocating to a CANCELLED order previously hit `ERR_ALLOCATION_EXCEEDS_AVAILABLE`.
- `/home/ubuntu/github/CodingPRD/tasks/task_1692_forest_nursery_reforestation_contract/workspace/implementation/routes_d.py` — `start_planting`: reordered the gates so the transition preconditions without a dedicated §2.6 slot (crew coverage, planting window → rule 5 `ERR_INVALID_STATE`) fire before the herbicide efficacy window (rule 9 `ERR_SITE_PREP_WINDOW_INVALID`), matching §2.6's fixed pipeline precedence.

**Final state:** 84/84 tests passing in all 8 parallel rounds.

## Step 8: Finalize PRD — 2026-08-14T11:14:18.151Z

Done. `PRD_FINALIZED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_1692_forest_nursery_reforestation_contract/workspace/PRD_FINALIZED.md` with exactly three in-place revisions, all traceable to the `<step_7_diff>` implementation fixes. The four test-side fixes were verified as pure fixture/test bugs against already-pinned PRD behavior (§3.6's 80.00 cost-share threshold and the `alive_count ≤ planted_count_snapshot` precondition are both verbatim in the PRD and match `routes_e.py:201-213`), so they required no edits.

## Line counts
- `PRD.md`: 332 lines; `PRD_FINALIZED.md`: 332 lines; **0.0% line delta** (three lines revised in place, no sections added or removed).

## Changes
- **§3.2** — revise — extended the sow sentence's parenthetical: a non-`AVAILABLE`, non-quarantined lot (in practice `DEPLETED`) fails the sow with `ERR_INVALID_STATE` — `implementation/routes_a.py:228-231` (`sow_crop_batch`).
- **§3.3** — insert — new sentence in the allocation paragraph: the order must be `CONFIRMED` or `ALLOCATED`, otherwise `ERR_INVALID_STATE` — `implementation/routes_b.py:147-148` (`create_allocation`).
- **§3.5** — revise — restructured the start-planting passage: crew coverage and planting-window membership are transition preconditions with no dedicated §2.6 rule, each rejecting with `ERR_INVALID_STATE` and evaluated before the herbicide efficacy window (`ERR_SITE_PREP_WINDOW_INVALID`) — `implementation/routes_d.py:142-153` (`start_planting`).

## Per-edit pre-edit search log

**Edit 1 (§3.2 sow gate)**
- (a) Subject: lot-state requirement at sow time; error identity per non-`AVAILABLE` case.
- (b) Enumerated paths: `routes_a.py` `sow_crop_batch` (the site, lines 219-247), `quarantine_seed_lot`/`release_seed_lot` (lot gates already pinned in §3.1); `routes_b.py` `create_allocation:149-151` and `routes_e.py` `create_shipment:34-36` (both gate on `QUARANTINED` only — a `DEPLETED` lot does **not** block them); `server.py:365 lot_remaining`; PRD §2.6 rules 5-6, §3.1 quarantine paragraph.
- (c) Adjustment: scoped the claim to the sow operation and named `DEPLETED` as "in practice" the only other case, so the sentence cannot be read as gating allocations/shipments on `DEPLETED` lots (implementation does not).

**Edit 2 (§3.3 allocation order-state gate)**
- (a) Subject: order-state precondition at allocation creation and its error identity.
- (b) Enumerated paths: `routes_b.py` `create_allocation` (the site — gate fires after body-FK existence, before quarantine/species/shape/batch/ceiling checks, matching §2.6 rule-5 precedence); `server.py:455 release_allocation` (demotes `ALLOCATED`→`CONFIRMED`, never creates); `routes_b.py` `cancel_order` (state gate already pinned); `routes_e.py` `create_shipment` (reads allocations, never creates); grep confirmed no other allocation-creation path.
- (c) Adjustment: used "any other state" (covers `PENDING_REVIEW`, `FULFILLED`, `CANCELLED` — all rejected by the impl) and placed the sentence before the batch-state sentence so paragraph order mirrors the §2.6 pipeline, without adding any new ordering claim beyond what rule 5 already implies.

**Edit 3 (§3.5 start-planting gates)**
- (a) Subject: error identities for crew-coverage and planting-window failures, and their evaluation order vs. the herbicide efficacy window.
- (b) Enumerated paths: `routes_d.py` `start_planting` (the site, lines 134-156); grep for `herbicide_applied_on` (written only by `record_site_prep`, read only by `start_planting`); grep for `planting_window_start/end` (written in `create_contract`, read only in `start_planting`); crew-coverage read only in `start_planting` (`confirm_assignment:329` has a separate, already-pinned contract-state gate); PRD §2.6 rule 5 before rule 9, plus §2.6's note that trigger conditions are defined in §3.
- (c) Adjustment: pinned only the observable precedence ({crew coverage, planting window} before herbicide window); deliberately did **not** pin the relative order between the two `ERR_INVALID_STATE` preconditions (identical error_id/status, unobservable); kept all thresholds, the half-open coverage interval, inclusive window bounds, and the herbicide rule text verbatim.

## Step 9: Complete PRD — 2026-08-14T11:31:54.174Z

The diff is exactly 18 in-place line revisions (no lines added or removed; no new sections), covering 21 logical changes. All edits verified against the implementation.

## Summary

**Source vs output**: `PRD_FINALIZED.md` 332 lines / 54,335 chars → `PRD_COMPLETED.md` 332 lines / 57,057 chars. Char delta: **+2,699**. Output: `/home/ubuntu/github/CodingPRD/tasks/task_1692_forest_nursery_reforestation_contract/workspace/PRD_COMPLETED.md`.

**Counts**: 18 ambiguity-pins, 3 mismatch-revisions (21 changes across 18 edited lines).

**Changes** (section — insert|revise — class — what — impl ref):

- §2.3 — revise — ambiguity — out-of-range `limit`/`offset` are clamped to the nearest bound (not rejected); non-integer values get `ERR_INVALID_REQUEST` — server.py:144-149
- §2.3 — revise — **mismatch** — list ordering pinned to creation sequence (`_seq`), not `created_at` ascending (diverges only if the clock was moved backward between creations) — server.py:150
- §2.4 — revise — ambiguity — `version` starts at 1 at creation — server.py:351
- §2.5 — revise — ambiguity — clock accepts any well-formed instant, forward or backward; no monotonicity check — routes_a.py:26-28
- §2.6 intro — insert — ambiguity — rule-18 rejections (missing/malformed/out-of-bounds field) surface at field-read time, even ahead of lower-numbered rules (pins impl's field-order evaluation, e.g. contract `acres`/`contingency_pct` shape before window inversion; order `quantity` shape before lead time) — routes_d.py:26-46, routes_b.py:36-39, routes_a.py:179-183
- §2.6 rule 18 — revise — ambiguity — catch-all: any §3 field constraint without its own error id (positivity, ranges, code uniqueness, uncatalogued date-ordering) → `ERR_INVALID_REQUEST` (400) — covers sow>remaining (routes_a.py:236), plantable>lifted (routes_a.py:277), negative elevation (routes_a.py:69), zone/unit/crew-code duplicates (routes_a.py:71, routes_c.py:25, routes_d.py:228), germination ranges (routes_a.py:100,150), future herbicide date (routes_d.py:97), alive>snapshot (routes_e.py:204), past replant_date (routes_e.py:284), delivered_at<dispatched_at (routes_e.py:145)
- §2.7 — revise — ambiguity — version fields sent to non-OCC endpoints, like all undeclared payload fields, are ignored rather than rejected — server.py:219-225
- §3.2 — revise — ambiguity — `actual_sow_date` stored as supplied, unconstrained vs `planned_sow_date`/clock — routes_a.py:233-237
- §3.2 — insert — ambiguity — crop-batch list filters are `seed_lot_id`, `status` — routes_a.py:212
- §3.3 — revise — ambiguity — amend payload fields are individually optional; a no-op amendment is still accepted (resets to `PENDING_REVIEW`, bumps version) — routes_b.py:103-114
- §3.3 — revise — ambiguity — manual allocation release blocked by in-flight shipment → `ERR_INVALID_STATE` (409) — routes_b.py:207-212
- §3.4 — revise — ambiguity — ungraded batch has zero unplaced remainder, so placement against it always fails `ERR_PLACEMENT_EXCEEDS_PLANTABLE` — routes_c.py:50-53
- §3.4 — revise — ambiguity — no lower bound enforced on `planted_confirmed_at` vs `delivered_at` — routes_e.py:162-165
- §3.5 — insert — ambiguity — contract creation performs no order-ownership or order-state cross-check — routes_d.py:23-25
- §3.5 — revise — ambiguity — verify-site-prep inspects only `site_prep_status` (never contract lifecycle status); non-`RECORDED` → `ERR_SITE_PREP_NOT_VERIFIED` (422) — routes_d.py:109-111
- §3.5 — revise — ambiguity — `planted_qty` is a positive whole number; replant-cycle floor falls back to `acres`×`trees_per_acre` when no obligation remains `OPEN`/`SCHEDULED` — routes_d.py:166, 177-184
- §3.5 — insert — ambiguity — contract list filters are `landowner_id`, `site_zone_id`, `seedling_order_id`, `status` — routes_d.py:81
- §3.5 — revise — **mismatch** — crew `active` flag is informational only; assignment creation never consults it (PRD previously implied it gates assignments; impl has no check) — routes_d.py:257-302
- §3.5 — insert — ambiguity — assignment scheduling does not inspect the contract's status — routes_d.py:262
- §3.7 — revise — **mismatch** — `documented_acres` violations split: non-positive → `ERR_INVALID_REQUEST` (400), excess over `enrolled_acres` → `ERR_ENROLLMENT_ACRES_EXCEEDED` (422) (PRD's compound "otherwise ERR_ENROLLMENT_ACRES_EXCEEDED" covered both) — routes_e.py:411-417
- §3.7 — revise — ambiguity — enrollment self-mismatch → `ERR_UNAUTHORIZED` (mirroring orders), and `cost_share_eligible` is not consulted at enrollment time — routes_e.py:352-358, 348-378

**Not changed** (verified already uniquely pinned): all endpoint/role mappings match §4 exactly; all calculation formulas (projected_plantable, tiered pricing, required_seedlings, award components, owed_quantity escalation/cap), both cascades, OCC semantics, quarantine gates, all window bounds/inclusivity, withdrawal ordering, depletion rule, and error-id/catalogue mappings conform to the PRD as written.
