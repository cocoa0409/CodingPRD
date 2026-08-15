# Worklog — task_1670_microgreens_specialty_produce_grower

## Step 1: Create Task Directory — 2026-08-14T06:17:00.000Z

Pre-assigned directory `tasks/task_1670_microgreens_specialty_produce_grower/` with `workspace/` subdirectory already created by the pipeline launcher; treated as DONE per invocation instructions. No index scan performed, no other task directory touched.

## Step 2: Generate Scaffold — 2026-08-14T06:39:30.000Z

All three scaffold artifacts are generated, verified, and lint-clean.

## What was produced

Task: `task_1670_microgreens_specialty_produce_grower` — a chef-direct specialty-produce grower API. All files at `/home/ubuntu/github/CodingPRD/tasks/task_1670_microgreens_specialty_produce_grower/`.

**`SCAFFOLD.yaml`** (§1.0–§1.7):
- **Complexity profile**: primary archetype `compliance_audit` (food-safety plan + harvest sanitation gate all grow ops), secondary `quota_allocation` (route minimum-order + seed/rack allocation); layers = rate_threshold_triggers, dual_variant_calculation, cascading_side_effects, optimistic_concurrency. Topology `flat`, state shape `branching`, role model `peer_roles`, `immediate` consistency.
- **15 entities**: Customer, Variety, VarietyTrial, SeedLot, GerminationTest, CropPlan, TrayBatch, FoodSafetyPlan, SanitationLog, StandingOrder, OrderItem, DeliveryRoute, DeliveryStop, SpoilageCredit, SurplusListing.
- **10 state machines** (added FoodSafetyPlan, GerminationTest, VarietyTrial machines during enum-closure audit), **2 OCC concurrency rules** (StandingOrder weekly-change, CropPlan sow), **8 calculations** (incl. dual-variant order totals + spoilage credits, germination threshold, harvest waterfall allocation, route-minimum threshold, tray-batch failure cascade), **8 validation priorities**, **67 endpoints**, **31 error codes**, **3 roles** (Grower/Chef/OpsManager; Chef is `entity_backed:Customer`).

**`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** (§1.8): all 9 difficulty rules × 2 instances = **18 instances**, each with structured `setup_api_calls`/`trigger`/`assert` and literal-computed numeric asserts (verified via Python: e.g., per-line-round 1.005 kg @100 → 101/line → subtotal 202; post-harvest credit 800×0.85×0.80×1.5 → 816; germination 0.85 inclusive boundary).

**`SCAFFOLD_CORNER_DESIGN.yaml`** (§1.9): **28 instances** across all 9 claim-extraction-guide sections (entities, state machines, calculations, validations, errors, roles, cross-cutting OCC, consistency model) plus 3 `excluded_because` stubs for §1.8-covered corners.

## Lint verdict (verbatim)

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(67 endpoints, 15 entities, 18 §1.8 instances, 25 active §1.9 instances, 468 calls scanned.)

## Key findings / fixes made during generation

- **FK reverse-reachability**: the initial draft failed lint check (f) on 7 FKs. Fixed by adding single-resource GETs for VarietyTrial/GerminationTest/SanitationLog and adding the missing FK filter params to the DeliveryStop/SpoilageCredit/SurplusListing list endpoints.
- **OCC version-capture bug (replay)**: `POST .../lines` returns `OrderItem`, so capturing `$.data.version` from it grabbed the wrong entity's version. Fixed by inserting `GET /grow/standing-orders/{id}` after each line-add to capture the true order version before `confirm`/next-line OCC calls. Same class of bug fixed for `batch_id` (was captured from the CropPlan sow response; now from `GET /grow/tray-batches?crop_plan_id=...`).
- **Cascade reachability**: the depth-3 seed-lot-block cascade required blocking a *RELEASED* lot, so I added a `RELEASED → BLOCKED` recall transition to the SeedLot state machine and rewrote the trigger to re-test the sown lot.
- **Enum closure**: added the missing FoodSafetyPlan/GerminationTest/VarietyTrial state machines so every system enum value is produced by a transition.
- Confirmed no forbidden concurrency vocabulary ("simultaneously", "first-writer-wins", etc.) anywhere in the three files.

## Step 3: Copy Shared Files — 2026-08-14T06:40:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1670_microgreens_specialty_produce_grower/workspace/INSTRUCTION.md` (bash, no subagent).

## Step 4: Generate PRD — 2026-08-14T06:58:00.000Z

All checks pass. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1670_microgreens_specialty_produce_grower/workspace/PRD.md`.

## What was generated

A prose PRD for the microgreens specialty grower domain, structured as:

- **§1 Introduction** — 2 paragraphs from the business-context angle (living inventory vs. chef-facing weekly ordering), noting the `/grow` mount and the logical clock.
- **§2 Global Specifications** — 9 subsections with domain-derived titles: RBAC with per-role `identity` semantics (Chef is entity-backed by Customer via `customer_id`; Grower/OpsManager opaque), the verbatim §2.2 envelope block, pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending), resource identity (including the explicit `SanitationLog` exception: no `updated_at`, no `version`), the logical clock (startup default 2026-08-01T00:00:00Z, never falls back to wall clock), food-safety gating, precision rules (whole cents round-half-up per-line-then-sum, kg 3 decimals, germination 4 decimals), the two OCC rules, and the 8-level validation priority cascade with all 12 per-resource 404 ids enumerated.
- **§3 Business Logic** — 8 subsections organized along the grow-to-delivery pipeline (variety trials → seed quarantine/germination → crop plans and the sow gate → sanitation and harvest allocation → standing orders and the weekly change window → routes and stop minimums → spoilage credits → farmers-market surplus). All 12 state machines, 8 calculations (including the pinned post-harvest-pricing order with its 0.70 / 0.85 / 1.10 / 0.25 constants and the inclusive 0.85 germination boundary), the failure cascade, and both revenue-projection variants are expressed in narrative with no pseudocode and no fuzzy wording.
- **§4 Endpoint table** — 4 columns only, 67 rows matching the scaffold exactly.
- **§5 Error catalogue** — 2 columns only, all 32 scaffold errors.

## Hard Contract Reports

```
Field coverage check:
- entities[].fields + endpoint inputs + path/query params: 77 required, 77 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] priority ordering: expressed globally (§2.9, first-through-eighth) and per-endpoint (§3.3 sow, §3.5 line add)
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (endpoint + expected_<parent>_version + ERR_STALE_VERSION/412 named)
- state_machines[].transitions: all transitions across 12 machines fully expressed with preconditions and side effects
- calculations[]: 8 checked, 8 fully expressed (inclusive boundaries and pinned evaluation orders preserved)
- validations[] conditions: all matchable to error_ids in prose
- endpoints[].side_effects / applies_to: all expressed (cascade chains, cancel-release, delivery flip, credit posting)
- entities[].fields[] structured content: defaults and initial values reconstructible from prose
- sibling-branch symmetry: PASS/FAIL, ADOPT/RETRIAL, INCLUDED/SKIPPED, approve/reject, sell/withdraw, DRAFT- vs CONFIRMED-cancel all rendered with equal density
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 377
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks: §2.2 matches the fixed block byte-for-byte (PASS), no fuzzy/approximating words anywhere (PASS), all 35 state enum values, all category/variant/outcome enums, and all 3 role names appear verbatim.

Note on process: the first two verification runs produced false "missing" reports because the checker's regex mispaired backticks around §2.2's fenced JSON blocks and split §3 at `### 3.N.` headings; after stripping code fences and splitting on full headings, all contracts verified clean. Two genuine gaps the checker did catch — the FoodSafetyPlan lifecycle fields (`plan_code`, `water_test_current`, `sanitation_sop_version`) and DeliveryStop's `route_id` — were repaired with a dedicated §3.3 lifecycle paragraph and a §3.6 stop-recording sentence before the final PASS.

## Step 5: Generate Unit Tests — 2026-08-14T07:26:00.000Z

(Ran concurrently with Step 6; completion notification arrived after Step 6's.)

Generation complete for `task_1670_microgreens_specialty_produce_grower`.

## What was produced

**`test_helpers/` (9 files, Stage 1)** — `types.py` (16 status enums + 16 entity TypedDicts; `SanitationLog` correctly carries only `id`/`created_at` per PRD §2.4), `api_client.py` (all 51 endpoints under `/grow`), `api_errors.py` (32 error IDs + HTTP map registered with the framework), `assertions.py` (per-entity structural assertions + exact-decimal `expected_line_extension_cents` / `expected_germination_rate` helpers), `factories.py`, `constants.py` (0.85 germination threshold, [50,200] ppm band, 0.70/0.85/1.10/0.25 credit constants, 2026-08-01T00:00:00Z clock start), `test_users.py` (`Chef` is `entity_backed:Customer` — `make_chef_headers(customer_id)` mandatory; Grower/OpsManager opaque), and `fixtures.py` (composite chains: listed variety, approved FSP, released lot, sown/ready/harvested batch, confirmed order, delivered stop — all threading per-instance Chef identity).

**`test_suite/` (9 test files, 57 tests, Stage 2)** — every test docstring carries verbatim PRD citations plus exactly one `Design:` tag as its final line.

## Audit results (all machine-verified)

- **Coverage**: Queue A 16/16 instances with ≥2 tests each (32 tests); Queue B 25/25 non-stub instances with 1 test each. All 3 `excluded_because:` stubs verified to resolve to real difficulty instances; not translated.
- **Citations**: 88/88 PRD quotations survive whitespace-normalized verbatim grep of PRD.md.
- **Hygiene**: pyflakes clean (one real bug found and fixed: missing `create_released_seed_lot` import in test_02), no scaffold mentions, no skip/xfail markers, all 57 tests collect under `pytest --collect-only`.

## Two instances skipped under the PRD-first filter (gaps left as gaps)

1. **`Difficulty/dual_variant_calc/standing_order_projection_all_lines_vs_confirmed_only`** — the PRD never names the projection payload's field names, and the asserted `confirmed_only == 4900` requires per-line confirmation memory the PRD does not describe: PRD §3.5 defines confirmed-only as "summing lines only while the parent order is `CONFIRMED` or `LOCKED`", which after a post-confirm line add yields 5800 (order stays CONFIRMED) or 0 (order reverts to DRAFT) — never 4900. Two PRD-only readers diverge.
2. **`Difficulty/combinatorial_formula/post_harvest_credit_multi_input_nonlinear`** — the asserted 816 requires plan cap 0.85 (harvest ratio < 0.70) AND overweight adjustment 0.80 (ratio > 1.10) simultaneously; for a single-variety crop plan the PRD computes both ratios as the same quantity ("the total `harvested_kg` across the crop plan's `HARVESTED` tray batches divided by the plan's `base_harvest_kg`" vs "the plan's harvested kilograms for the variety divided by the plan's base for that variety"), making the combination unreachable, and with multiple plans "the plan" is ambiguous.

Note: the sibling dual-variant spoilage instance WAS kept — I built the fixture to reach the PRD-derivable state its distinguishing-aspect describes (single plan, 52.0 kg harvested against 40.0 kg base → ratio 1.30 → cap 1.00, excess 0.20 → adjustment 0.80 → 640 vs 800 original-paper), since with exactly one crop plan per variety both PRD readers converge on that outcome.

## Step 7: Run Tests and Iterate — 2026-08-14T07:38:00.000Z

The leftover process already exited. The loop is complete — all 8 rounds pass 57/57.

## Summary

**Iterations run: 2** (sweep 1 surfaced the failure; fix applied; sweep 2 clean across all 8 parallel rounds, 57/57 each).

**Failure diagnosed (failed in all 8 rounds of sweep 1):**
- `test_04_harvest_sanitation_and_schedule.py::TestHarvestAllocationWaterfall::test_harvest_allocation_fills_earliest_week_first` — expected the partially-filled order line's `fulfillment` to be `SHORTED`, got `ALLOCATED`.

**Diagnostic outcome:**
- STEP 1a (coverage): PRD §3.4 verbatim — "Each line is filled against its `qty_kg` in turn: a line that can be fully covered becomes `ALLOCATED`, and when supply runs out mid-line that line is partially allocated with its unfilled remainder marked `SHORTED`."
- STEP 1b (unique derivability): holds. The implementation's split-line behavior (shrink the original line to the filled amount as `ALLOCATED`, create a brand-new `SHORTED` OrderItem for the remainder) invents a resource-creation side effect the PRD never states; §3.2's cascade wording ("that shortfall marks matching `PLANNED` order lines `SHORTED`") confirms the existing line itself flips status.
- STEP 2: test and fixtures faithful to PRD (two customers, weeks 2026-08-03 / 2026-08-10, 3.0 kg lines each, 4.0 kg harvest → line 1 `ALLOCATED`, line 2 `SHORTED`).
- STEP 3: implementation bug.

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1670_microgreens_specialty_produce_grower/workspace/implementation/services.py` — `run_allocation()`: removed the undocumented mid-line split (which mutated the original line's `qty_kg`/`line_extension_cents`, marked it `ALLOCATED`, and inserted a new `SHORTED` OrderItem). Now, when supply runs out mid-line, the line itself is marked `SHORTED` with its creation-time `qty_kg` and `line_extension_cents` untouched, and remaining supply is consumed — matching PRD §3.4. The no-supply-left and full-cover branches were already correct and are unchanged.

**Verification:** final 8-round parallel sweep with `--isolation per-test-server`: 57/57 passed in every round (8/8 clean).

## Step 8: Finalize PRD — 2026-08-14T07:47:00.000Z

The diff is exactly one in-place paragraph revision at line 153, as scoped. Task complete.

## Summary

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1670_microgreens_specialty_produce_grower/workspace/PRD_FINALIZED.md`

**Line counts / delta:** `PRD.md` 302 lines, `PRD_FINALIZED.md` 302 lines — 0.0% line-count delta; one paragraph revised in place (1 line changed by `diff`).

**Changes (one bullet per change):**
- **§3.4 (Harvest Allocation waterfall)** — **revise** — appended one disambiguating sentence after the mid-line shortfall sentence: the pass never splits a line; no new `OrderItem` is created for the unfilled remainder; the partially covered line's own `fulfillment` flips to `SHORTED`; its `qty_kg` and `line_extension_cents` stay at the values stamped at line creation; the last of the supply is consumed against that line, so every line visited after it in the same pass is likewise marked `SHORTED` — `implementation/services.py:131-138` (mid-line branch of `run_allocation`).

**Rationale for the single edit:** the only <step_7_diff> item was the `run_allocation()` implementation fix (no test deletions, no test_helpers fixes). PRD §3.4's original sentence — "that line is partially allocated with its unfilled remainder marked `SHORTED`" — is precisely the wording the original implementation misread as split-line behavior (shrink original line to `ALLOCATED` + insert a new `SHORTED` OrderItem). Since the task goal is that a fresh implementer reading PRD_FINALIZED.md alone reproduces the current implementation, the ambiguity the fix resolved was pinned inline. Everything else in the diff was diagnostic narrative; no other PRD site was touched.

**Per-edit pre-edit search log:**
- **Edit 1 (§3.4 mid-line shortfall):**
  - (a) Subject: mid-line shortfall handling in the §3.4 allocation waterfall — line status outcome, no-split semantics, immutability of `qty_kg`/`line_extension_cents` during the pass, and the supply-exhaustion consequence for later lines.
  - (b) Impl paths enumerated and read/grepped: `services.py:104-142` (`run_allocation`, all three branches — full-cover `ALLOCATED`, no-supply `SHORTED`, mid-line `SHORTED` + supply zeroed); `services.py:145-182` (`cascade_block_lot`, second caller, same function, §3.2 cascade consistency); `routes/crop_plans.py:251-260` (harvest endpoint, first caller, passes `harvested_kg` as supply); `routes/standing_orders.py:135-178` (sole `OrderItem` creation site — `qty_kg`/`line_extension_cents` written only at creation) and `:220-250` (cancel path's PLANNED→SHORTED, same enum, unrelated trigger); `routes/delivery.py:134-137,221-223` (stop subtotal reads `line_extension_cents`; deliver flips ALLOCATED→DELIVERED); `routes/spoilage.py:153-177` (credit guard reads full `qty_kg` as delivered quantity); `routes/varieties.py:79` (retire guard on PLANNED/ALLOCATED); `services.py:68-75` (`recompute_subtotal`, numerically unaffected by the pass).
  - (c) Wording adjustment: every claim scoped to "the pass" ("never splits a line", "every line visited after it in the same pass") so the cancel/delivery/spoilage transitions are not implicated; used "left at the values stamped when the line was created" (verified true — creation is the only writer) instead of a broader universal immutability claim; kept the trailing surplus sentence untouched and consistent (mid-line consumption leaves no surplus). Both allocation triggers share `run_allocation`, so the per-pass wording covers the §3.2 cascade without further edits.

**No-new-mismatch check:** confirmed the appended sentence is consistent with all enumerated paths, including the cascade caller and downstream readers; no off-site behavior is narrowed, redefined, reordered, or excluded.

## Step 9: Complete PRD — 2026-08-14T08:03:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1670_microgreens_specialty_produce_grower/workspace/PRD_COMPLETED.md` produced as a minimal patch over `PRD_FINALIZED.md`, aligned to `implementation/`.

**Source vs. output**: PRD_FINALIZED.md 302 lines / 40,715 chars → PRD_COMPLETED.md 309 lines / 46,352 chars (char-delta +5,637; 73 changed diff lines). No new sections; all changes are in-paragraph inserts/revisions plus five table rows in §5.

**Counts**: 24 ambiguity-pins, 10 mismatch-revisions (34 edits total).

**Changes** (section — insert|revise — ambiguity|mismatch — what changed — impl ref):

- §2.2 — insert — ambiguity — undefined path → `ERR_NOT_FOUND` 404, unsupported method → `ERR_INVALID_REQUEST` 405, unexpected failure → `ERR_INTERNAL` 500 — app.py:49-59
- §2.3 — revise — ambiguity — out-of-range limit/offset clamped (not rejected); non-integer → `ERR_INVALID_REQUEST`; sort ties broken by creation order — middleware.py:119-133, routes/listing.py:8
- §2.5 — revise — ambiguity — lock state is pure weekday function re-evaluated per clock set; `effective_week_start` not consulted; clock may move backward; malformed `to_iso8601` → `ERR_INVALID_REQUEST`, naive value read as UTC; all system timestamps (`created_at`/`updated_at`/`api_request_timestamp`) stamped from logical clock — services.py:78-88, clock.py:15-36, response.py:8-11
- §2.7 — insert — ambiguity — kg inputs stored rounded to 3dp, but money computed from the submitted (unrounded) quantity — standing_orders.py:167-174, crop_plans.py:252/259, spoilage.py:54
- §2.8 — revise — mismatch — three guarded writes (line add, confirm, sow), not two; version field optional on all three, checked only when supplied; dropped the plan-edit example (no such endpoint) — standing_orders.py:137/161/200/210, crop_plans.py:107/126
- §2.9 — revise — ambiguity — added `ERR_FOOD_SAFETY_PLAN_NOT_FOUND`, `ERR_SANITATION_LOG_NOT_FOUND`, `ERR_SURPLUS_LISTING_NOT_FOUND` to the 404 list; out-of-range/enumeration values → `ERR_INVALID_REQUEST` — errors.py:28-30
- §3.1 — revise — ambiguity — record-panel: single submission of exactly `chef_panel_size` scores (else `ERR_INVALID_REQUEST`); requires trial `PENDING` and variety `TRIAL` (else `ERR_INVALID_STATE`); mean carried to 4dp half-up; decide: outcome must be `ADOPT`/`RETRIAL`, requires trial `PENDING` + variety `EVALUATION` — trials.py:80-129
- §3.1 — insert — ambiguity — retiring a non-`LISTED` variety → `ERR_INVALID_STATE` — varieties.py:76-77
- §3.2 — insert — ambiguity — duplicate `lot_code` per variety → `ERR_INVALID_REQUEST` 400 — seed_lots.py:40-44
- §3.2 — insert — ambiguity — result recordable only once; re-recording → `ERR_INVALID_STATE` — seed_lots.py:135-136
- §3.2 — revise — mismatch — cascade: per-plan "base minus surviving" shortfall replaced by impl's actual per-variety pass: supply = surviving `harvested_kg` − committed (`ALLOCATED`/`DELIVERED`/`CREDITED`) quantities, floored at 0, then full §3.4 pass (may `ALLOCATE` as well as `SHORT`) — services.py:145-182
- §3.3 — insert — ambiguity — gate satisfied iff ≥1 plan `APPROVED` and none `SUSPENDED`; `DRAFT` plans don't block — services.py:59-65
- §3.3 — insert — ambiguity — approving non-`DRAFT`/`SUSPENDED`, suspending non-`APPROVED` → `ERR_INVALID_STATE` — food_safety.py:66-68, 92-93
- §3.3 — insert — ambiguity — cancelling a non-`PLANNED` plan → `ERR_INVALID_STATE` — crop_plans.py:161-164
- §3.3 — revise — mismatch — sow "must carry" → "may carry" `expected_crop_plan_version`; comparison "when supplied" — crop_plans.py:107/126
- §3.3 — insert — ambiguity — sow response carries the updated crop plan — crop_plans.py:152
- §3.4 — revise — ambiguity — advance is purely state-ordered, not gated on clock/`expected_harvest_date` (dropped "at its expected_harvest_date") — crop_plans.py:195-218
- §3.4 — insert — ambiguity — most recently filed sanitation log governs the harvest gate — crop_plans.py:244
- §3.4 — insert — ambiguity — same-order allocation tie-break = line creation order — services.py:91-101
- §3.5 — revise — mismatch — removed "a deactivated customer cannot place changes" (impl never checks `is_active`; no deactivation endpoint exists) — customers.py:20-27
- §3.5 — revise — ambiguity — `effective_week_start` stored as supplied (no format/Monday check); `weekly_subtotal_cents` starts at zero — standing_orders.py:65/84
- §3.5 — revise — mismatch — `ERR_ORDER_NOT_EDITABLE` scoped to `CANCELLED` orders (LOCKED yields `ERR_WEEKLY_CHANGE_LOCKED`, not NOT_EDITABLE despite being neither DRAFT nor CONFIRMED); OCC phrasing optional for line add and confirm — standing_orders.py:146-164, 200-213
- §3.5 — revise — mismatch — lock rule restated as weekday strictly-greater-than-cutoff (removed "relative to its effective_week_start"); removed claim that dispatch uses the order's frozen subtotal — services.py:78-88, delivery.py:132-145
- §3.5 — insert — ambiguity — projection response = order fields plus `all_lines_total` and `confirmed_only_total`; confirmed-only is zero outside `CONFIRMED`/`LOCKED` — standing_orders.py:117-125
- §3.5 — revise — mismatch — cancel flips only `SCHEDULED`/`INCLUDED` stops to `SKIPPED` (DELIVERED untouched); cancelling `LOCKED`/`CANCELLED` → `ERR_INVALID_STATE` — standing_orders.py:243-253
- §3.6 — revise — ambiguity — stops addable only to `PLANNED` routes (else `ERR_INVALID_STATE`); `stop_subtotal_cents` starts at zero — delivery.py:89-99
- §3.6 — revise — mismatch — dispatch stop subtotal sums only lines in `PLANNED`/`ALLOCATED`/`DELIVERED` (SHORTED/CREDITED excluded), not "the order's final, locked subtotal" — delivery.py:132-138
- §3.6 — revise — ambiguity — dispatch/complete state preconditions → `ERR_INVALID_STATE`; deliver flips only `PLANNED`+`ALLOCATED` lines; deliver on non-`INCLUDED` stop and skip on non-`SCHEDULED` stop → `ERR_INVALID_STATE`; unresolved `INCLUDED` stop blocks complete with `ERR_INVALID_STATE` — delivery.py:118-120, 155-175, 212-215, 232-235
- §3.7 — insert — ambiguity — spoilage report requires stop `outcome` `DELIVERED`, else `ERR_INVALID_STATE` — spoilage.py:99-102
- §3.7 — revise — mismatch — "can only be lower than" → "never exceeds" original-paper figure (factors can both be 1.00) — spoilage.py:48-53
- §3.7 — revise — ambiguity — POST_HARVEST plan selection: most recently created plan for the variety with ≥1 `HARVESTED` batch; none → no reduction — spoilage.py:39-41, 60-74
- §3.7 — revise — ambiguity — delivered quantity = line's full `qty_kg` while `DELIVERED`/`CREDITED`, else zero; credit posts to the stop's customer; adjudicating non-`PENDING` → `ERR_INVALID_STATE` — spoilage.py:149-178, 188-189
- §3.8 — revise — ambiguity — `tray_batch_id` need only exist (no harvest-state/quantity/surplus check); sell/withdraw non-`LISTED` → `ERR_INVALID_STATE` — surplus.py:43-44, 89-90, 100-103
- §4 — revise — mismatch — weekly-change line addition returns 201 (creates `OrderItem`), not 200 as the intro claimed — standing_orders.py:181
- §5 — insert — ambiguity — five new catalogue rows: the three pattern-derived 404s, `ERR_NOT_FOUND` 404, `ERR_INTERNAL` 500 — errors.py:28-30, app.py:51/59

## Step 6: Generate Implementation — 2026-08-14T07:23:00.000Z

(Completed concurrently with Step 5; recorded when its completion notification arrived.)

Implementation complete and verified. All files live under `/home/ubuntu/github/CodingPRD/tasks/task_1670_microgreens_specialty_produce_grower/workspace/implementation/`.

## What was built

Python + Flask, in-memory store, empty at every boot (no seeding anywhere):

- `start.sh` — guarded dependency install (`python3 -c "import flask"` check), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000), foreground
- `app.py` — blueprint registration, `ApiError`/404/405/500 envelope handlers
- `db.py` — store + logical clock starting exactly at `2026-08-01T00:00:00Z`, advanced only via `POST /grow/_clock/set_current_utc` (never wall-clock)
- `errors.py`, `response.py`, `middleware.py` — exact scaffold envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; error body `error_id`/`message`), `X-User-ID`/`X-User-Role` auth with the three exact role spellings, typed body validators, `limit`/`offset` pagination (default 10, clamped to 1..100) with `total_count`/`has_more` in `meta`
- `services.py` — common fields (`id`/`created_at`/`updated_at`/`version`, 3-fractional-digit ISO timestamps from the logical clock; SanitationLog gets only `id`/`created_at`), Decimal money math (round-half-up per line then sum), food-safety gate, weekly lock sync, harvest waterfall, lot-block cascade
- `routes/` — all 62 endpoints from the endpoint table

## Key semantics implemented

- **Validation priority**: auth → role → path existence (left-to-right) → body shape (`ERR_INVALID_REQUEST`) → FK existence → state → food-safety → seed → temporal → fiscal (422 `ERR_CREDIT_EXCEEDS_DELIVERY`, 412 `ERR_STALE_VERSION`)
- **Sow gate order**: plan `PLANNED` → APPROVED food-safety plan exists and none SUSPENDED → lot RELEASED → sufficient seed → OCC last; creates TrayBatch (`SOWN`, `sown_at` from clock, `expected_harvest_date` = sow date + `days_to_harvest`), decrements lot (0 → `DEPLETED`), plan version bump
- **Germination**: rate 4-decimals round-half-up, inclusive 0.85 PASS boundary; FAIL on QUARANTINE/RELEASED → BLOCKED + cascade (live batches → FAILED, allocation re-pass shorts PLANNED lines)
- **Harvest allocation waterfall**: PLANNED lines ordered by `effective_week_start` then order `created_at` (never id); full cover → ALLOCATED; mid-line supply exhaustion splits the line (filled part ALLOCATED + new SHORTED remainder line, extensions recomputed per line); zero supply → SHORTED
- **Weekly lock**: clock weekday &gt; `change_cutoff_day` flips CONFIRMED → LOCKED (line add → `ERR_WEEKLY_CHANGE_LOCKED`), rollover back → CONFIRMED; CANCELLED order line edits → `ERR_ORDER_NOT_EDITABLE`; OCC fields enforced when present on line-add/sow/confirm
- **Dispatch**: stop subtotal = sum of pending-delivery line extensions (SHORTED excluded, so cascades reduce subtotals); inclusive `&gt;=` minimum → INCLUDED; deliver flips lines to DELIVERED; complete requires every INCLUDED stop DELIVERED or with a resolved credit
- **Spoilage credits**: dual-variant pricing — ORIGINAL_PAPER at line price; POST_HARVEST_PRICING with pinned order (plan cap 1.00/0.85 at 0.70 ratio, overweight excess over 1.10 capped at 0.25, single final rounding); approval posts to `credit_balance_cents`, full-quantity credit flips line to CREDITED
- **Chef ownership**: `X-User-ID` must equal the Customer `id` on order create/line/confirm/cancel and spoilage report (403 otherwise); Grower/OpsManager IDs opaque

## Verification

Three in-process suites (the shared host kills long-lived background servers, so functional verification ran through Flask's test client after confirming real TCP boot): 52 main-flow checks, 45 edge checks (recall cascade, partial split, sanitation ppm band, empty route, min-boundary skip, OCC stale, credit-exceeds 422, retire-in-use, cross-chef 403), and 9 dual-variant credit-pricing checks (cap 0.85 shortfall → 1700; overweight 1.2 → 1800; extreme overweight → 1500) — all pass. The real `bash start.sh` contract was verified over TCP: fresh boot on `PORT`, empty store (`total_count: 0`), correct envelope shapes for success, list, and error responses.
