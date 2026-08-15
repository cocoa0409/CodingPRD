# Worklog — task_1959_dental_supply_distribution_equipment

## Step 1: Create Task Directory — 2026-08-15T03:01:00.000Z

Pre-created by the pipeline launcher: `tasks/task_1959_dental_supply_distribution_equipment/` and `workspace/` existed before this orchestrator started.

## Step 2: Generate Scaffold — 2026-08-15T03:48:00.000Z

Done. All three scaffold artifacts are generated and lint-clean.

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_1959_dental_supply_distribution_equipment/SCAFFOLD.yaml` — §1.0–§1.7 (904 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_1959_dental_supply_distribution_equipment/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design:` key, 19 instances (623 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_1959_dental_supply_distribution_equipment/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design:` key, 50 active instances + 5 `excluded_because:` stubs (978 lines)

The pre-existing `workspace/` subdirectory was not touched. No sibling task was read at any point.

## Design summary

- **Complexity profile**: primary archetype `workflow_orchestration` (equipment sale pipeline QUOTE→CONFIRMED→INSTALL_SCHEDULED→INSTALLED→TRAINED→ACCEPTED; service ticket branch/cycle), secondary `temporal_windowing` (dispatch/install scheduling). Layers: dual_variant_calculation, cascading_side_effects, selector_policy, optimistic_concurrency. Flat topology (all linkage via FK fields, filtered-list reverse GETs), cyclic state-machine shape, peer_roles, immediate consistency.
- **Surface**: 12 entities, 58 endpoints, 30 ordered validations, 30 domain error codes, 11 calculations, 9 state machines, 6 roles (PracticeManager and FieldTechnician are `entity_backed`; the rest `opaque`), 1 OCC rule (`usage-profile-upsert-stale-practice` on `Practice.version`, HTTP 412), logical clock endpoint with the mandated `2026-08-01T00:00:00Z` startup default.
- **Difficulty rules (all 9 satisfied, differentiated per §0.5)**: dual variants on ServiceTicket repair cost (WARRANTY 0 vs SERVICE_PLAN 5000 for identical inputs) and TradeIn valuation (784717 vs 25000); combinatorial formulas in all three modes ((c) volume tier keyed on pre-discount subtotal → 450000; (a) bundle min(cap) with ELITE tier bonus → 17000/15000/20000; (b) rebate per-line round-then-sum → 126 not 125); cyclic EquipmentSale rework loop + forking/cyclic ServiceTicket; depth-3 cascades from deliver (order→usage profile→AUTO order) and claim submit (claim→fund debit→promotion EXHAUSTED); priority conflicts state-vs-fiscal and safety-vs-constraint; boundary checks on reorder-point equality (via `/_replenishment/run`) and credit equality (via submit); cross-entity guards EquipmentSale→Practice and RebateClaim→Order; half-open technician overlap vs closed-interval practice install-bay overlap; credit-conservation and van-stock-conservation invariants.
- **Numeric literals**: every formula-derived assert was precomputed with Python (e.g., `0.98^12 × 1,000,000 = 784717`; `29 − 8×1.0357 = 20.7144`; plan share `min(22000, 100000) = 22000`) — no unresolved expressions in any assert.

## Lint verdict (verbatim)

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(58 endpoints, 12 entities, 19 §1.8 + 50 §1.9 instances, 553 calls scanned.) Two issues were found and fixed during iteration: a missing `warranty_agreement_id?` reverse-reachability filter, and YAML flow-context quoting for `{id}` path templates / `field?` optional markers / `Entity[]` outputs. A supplementary audit confirmed: no forbidden concurrency vocabulary, correct file key separation, all 74 instance names unique across both design files, all `grounds:` references resolve, all stub citations exist, and every error code is referenced by at least one validation.

## Step 3: Copy Shared Files — 2026-08-15T03:49:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1959_dental_supply_distribution_equipment/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-15T04:06:00.000Z

PRD generated and all verification passes are green. Final report:

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1959_dental_supply_distribution_equipment/workspace/PRD.md` (generated from `SCAFFOLD.yaml`; the two forbidden design-index files were not opened or referenced).

**Document design** (domain-derived, not copied from the example skeleton):
- §1: 2-paragraph introduction (dual consumables/capital-equipment business, logical clock, compensation discipline).
- §2: 11 subsections — RBAC with per-role `identity` prose, verbatim §2.2 envelope, pagination, common resource properties, the logical clock + lazy expiry (default `2026-08-01T00:00:00Z`), cents/half-up vs 4-decimal usage precision, OCC (`expected_practice_version` on the usage-profile upsert only), the 6-rung validation ladder, half-open vs closed-interval scheduling geometry, controlled-product compliance, and cascade/compensation principles.
- §3: 7 workflow subsections (onboarding → usage profiles/replenishment → ordering → promotions/rebates → equipment pipeline → trade-ins → service tickets), with validation priority orders stated per endpoint family, all 11 calculations in reconstruction-safe prose, and all state transitions with preconditions/side effects/error IDs.
- §4: 58 endpoint rows (Method/Path/Description/Roles only); §5: 30 error rows (ID/HTTP status only).

**Hard Contract Reports**

```
Field coverage check:
- entities[].fields: 77 required, 77 present, 0 missing
- endpoints[].request_body: 22 required, 22 present, 0 missing
- endpoints[].query_params (incl. shared identifiers): 2 required (limit, offset), 2 present, 0 missing
- (101 total identifiers incl. line/van-stock sub-fields and response-only names; 0 missing)
Status: PASS

Rule coverage check:
- validations[] with priority: 30 checked, 30 expressed (global 6-rung ladder in §2.8 + per-endpoint orderings in §3), 0 missing
- concurrency_rules[] OCC rejections: 1 checked, 1 expressed (PUT /api/usage-profiles + expected_practice_version + ERR_STALE_VERSION/412 named), 0 missing
- state_machines[].transitions: 30 checked, 30 fully expressed, 0 missing
- calculations[]: 11 checked, 11 fully expressed, 0 missing
- validations[] conditions: 30 checked, 30 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 58 checked, 58 expressed, 0 missing
- entities[].fields[] structured content: 77 checked, 77 reconstructible, 0 missing
- sibling-branch symmetry: 8 groups checked (cancel DRAFT/SUBMITTED, coverage fork, repair_cost 3 variants, valuation 2 variants, deny/settle, reopen/close, lazy-expiry pair, half-open/closed geometry), 8 symmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 519
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks: §2.2 block byte-identical to the canonical source; no pseudocode operators or fuzzy-quantity words in prose; all 30 error IDs appear in §2/§3 narratives; §4 role assignments match the scaffold exactly for all 58 endpoints.

## Step 5: Generate Unit Tests — 2026-08-15T04:47:00.000Z

Generation complete for `task_1959_dental_supply_distribution_equipment`. All artifacts are in place and verified.

## What was generated

**`test_helpers/` (Stage 1, 9 files):**
- `types.py` — 12 entity TypedDicts + 15 status/role enums (all entities carry §2.4 common fields)
- `api_client.py` — `ApiClient(GenericApiClient)` with 41 endpoint methods covering every PRD §4 route, including `POST /api/_replenishment/run` and `POST /api/_clock/set_current_utc`
- `api_errors.py` — all 30 error IDs with the §5 HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity shape assertions + `van_stock_quantity` helper
- `factories.py`, `constants.py` — input-only payload factories; domain thresholds (28-day window, 500000/200000 tiers, 0.02 ELITE bonus, 200 cents/min labor, 7500 estimate, 0.98 depreciation, scrap table, 90/30-day windows)
- `test_users.py` — 6 role headers; mandatory `make_practice_manager_headers(practice_id)` / `make_field_technician_headers(technician_id)` builders for the two entity-backed roles
- `fixtures.py` — composite setup: `setup_accepted_sale`, `drive_sale_to_accepted`, `setup_ticket_assessed/dispatched/resolved`, `setup_rebate_claim`, `create_accepted_trade_in`, `upsert_profile` (OCC version auto-refetch), `load_van_stock`, `create_service_plan`, `set_clock`

**`test_suite/` (Stage 2): `conftest.py` + 9 test files, 88 tests** — `pytest --collect-only` passes.

## Design-index contract compliance (audited programmatically)

- **Queue A (difficulty): all 18 instances × ≥2 tests = 36 tests** — every `Design: Difficulty/<rule_id>/<instance.name>` tag resolves to a real instance
- **Queue B (corner): all 50 non-stub instances × 1 test = 50 tests** — the 5 `excluded_because:` stubs were not translated; their `difficulty_instance` cross-references all resolve
- Every test carries exactly one Design tag (0 malformed); zero `skip`/`skipif`/`xfail` markers; zero "scaffold" mentions in generated code
- **PRD citation check: all quoted citations survive literal grep of PRD.md** (two initial failures — an elided gate-order quote and a stray period — were fixed by quoting the full sentences)
- All index-precomputed expected values independently re-verified (784717 vs 25000 trade-in divergence, 126 vs 125 rebate rounding order, 17000/15000/20000 bundle bonus+cap, 20.0 vs 20.7144 reorder boundary, 22000 plan_share, 184734 re-appraisal, etc.)

No instances were skipped: every non-stub instance in both indices has verbatim PRD coverage and a uniquely derivable outcome. Notable two-reader adjustments: the practice-defaults test omits `version == 1` (PRD never pins the initial counter value) and the upsert-supersede test asserts via the listing ("exactly one profile per pair") rather than same-id identity, since PRD does not pin row identity across supersede.

## Step 6: Generate Implementation — 2026-08-15T04:49:00.000Z

Status so far:
- Implementation complete at `/home/ubuntu/github/CodingPRD/tasks/task_1959_dental_supply_distribution_equipment/workspace/implementation/` (Python + Flask, in-memory store, no seeding, `start.sh` with guarded dependency install and `exec`).
- First full run: 86/88 passed. The two failures were (a) credit semantics — tests require the reservation to survive delivery, fixed by switching to a stored ledger field; (b) a transient 500 caused by my own mid-run edits (mixed module versions during a per-test reboot), not a code defect.
- Focused rerun of the two affected test files with the final code: 24/24 passed.

(Orchestrator note: the subagent's trailing full-suite rerun was stopped when the subagent exited; Step 7 owns the authoritative 8-round sweep.)

## Step 7: Run Tests and Iterate — 2026-08-15T04:55:00.000Z

All 8 parallel rounds pass cleanly — 88/88 tests in every round, zero failures, zero flakiness. The exit condition is met on the first sweep.

## Summary

- **Iterations run**: 1 (single 8-round parallel stability sweep; all 8 rounds green at 88/88 tests each).
- **Tests deleted**: none.
- **Fixes applied to `test_helpers/`**: none.
- **Fixes applied to `test_suite/`**: none.
- **Fixes applied to `implementation/`**: none.

The task at `/home/ubuntu/github/CodingPRD/tasks/task_1959_dental_supply_distribution_equipment` was already in a fully passing, stable state — no diagnostic or repair work was needed.

(Orchestrator verification: `results.1.json` through `results.8.json` each report 88/88 passed.)

## Step 8: Finalize PRD — 2026-08-15T04:55:30.000Z

SKIPPED per the skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the implementation exhibits; no `PRD_FINALIZED.md` is produced.

## Step 9: Complete PRD — 2026-08-15T05:12:00.000Z

All edits verified against the implementation. The diff touches exactly 25 paragraphs; every pinned behavior was confirmed against the code. Task complete.

## Summary

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1959_dental_supply_distribution_equipment/workspace/PRD_COMPLETED.md`
- Source `PRD.md`: 303 lines, 53,854 chars → `PRD_COMPLETED.md`: 303 lines, 57,828 chars (+3,974 chars, +0 lines; all changes are inline paragraph inserts/revisions, no new sections).

**Counts:** 25 ambiguity-pins, 6 mismatch-revisions (31 behavioral pins across 25 edited paragraphs).

**Changes:**

- §2.3 — revise — ambiguity — `limit`/`offset` out-of-range values are clamped (to [1,100] / ≥0), non-integer values rejected with `ERR_INVALID_REQUEST` (400) — implementation/util.py:234-253
- §2.3 — insert — ambiguity — list sort gains a tertiary creation (insertion) order tiebreak — util.py:110-112
- §2.4 — insert — ambiguity — `version` starts at 1 on creation — util.py:85-95
- §2.5 — revise — mismatch — clock endpoint *sets* (not "advances") the clock; target need not be in the future — routes/ops.py:20-26, db.py:55-57
- §2.5 — insert — ambiguity — `current_utc` echo format: three fractional digits, none on whole seconds — util.py:42-48
- §2.5 — insert — ambiguity — envelope `api_request_timestamp` is wall-clock, the sole exception to the logical clock — envelope.py:14-16
- §2.5 — insert — mismatch (vs §2.4 "every mutation") — lazy EXPIRED flips change only `status`; no `updated_at` refresh, no `version` increment — calc.py:25-32
- §2.8 — revise — mismatch — "quantities strictly positive" scoped: monetary/count fields non-negative; only order-line/parts quantities, `sale_price_cents`, `training_minutes`, present `max_qty_per_order` strictly positive — util.py:159-169, routes/* field validators
- §2.8 — revise — mismatch — end>start window check applies only to install-scheduling and dispatch windows; promotion and coverage-agreement windows stored as supplied — routes/equipment.py:146-149, routes/service.py:187-192 vs routes/commercial.py:81-82, routes/service.py:475-476
- §3.1 — insert — ambiguity — duplicate `sku` rejected with `ERR_INVALID_REQUEST` (400) — routes/products.py:30-32
- §3.1 — insert — ambiguity — van stock may hold any catalog product kind; both quantities non-negative integers — routes/equipment.py:298-321
- §3.2 — insert — ambiguity — superseding a profile updates only the three config fields; `id`, `created_at`, `on_hand_estimate`, `average_daily_usage`, `last_evaluated_at` carry over — routes/usage_profiles.py:97-102
- §3.2 — insert — ambiguity — `reorder_point`/`target_stock_level` stored with caller-supplied precision — routes/usage_profiles.py:51-52
- §3.2 — insert — ambiguity — auto-draft orders priced like any new order (price snapshot, volume discount, no promotion) and bypass §3.3 creation gates incl. practice standing — calc.py:197-216, calc.py:116-141
- §3.2 — insert — ambiguity — sweep processes profiles in standard listing order; `evaluated_profile_count` is the total profile count; `created_order_ids` in processing order — calc.py:253-285
- §3.3 — insert — ambiguity — a product may repeat across lines, each priced independently — routes/orders.py:39-54, calc.py:62-76
- §3.3 — revise — mismatch — available credit is a stored ledger (not the "limit minus SUBMITTED totals" formula): debited at submit, restored only on SUBMITTED cancel; delivery does not release — calc.py:36-44, routes/orders.py:268,299, calc.py:219-250
- §3.3 — insert — ambiguity — submitting an empty-lined draft rejected with `ERR_INVALID_REQUEST` (400) — routes/orders.py:235-236
- §3.4 — insert — ambiguity — kind-specific promotion attributes optional except `fund_total_cents`; id-list members not catalog-validated; missing `discount_pct` prices as zero; missing `rebate_per_unit_cents` yields zero claims; BUNDLE_DISCOUNT carries null `fund_remaining_cents` — routes/commercial.py:66-112, calc.py:100,456
- §3.4 — insert — ambiguity — `revision_note` required but not persisted on the claim — routes/commercial.py:267
- §3.5 — insert — ambiguity — non-EQUIPMENT `product_id` on quote rejected with `ERR_INVALID_REQUEST` (400) — routes/equipment.py:59-62
- §3.5 — insert — ambiguity — warranty `end_date` month arithmetic clamps day to target month length — util.py:51-56, routes/equipment.py:232
- §3.6 — insert — ambiguity — apply-to-sale target need not belong to the trade-in's practice — routes/commercial.py:414-455
- §3.7 — insert — ambiguity — service-plan registration: non-`SERVICE_PLAN` type rejected with `ERR_INVALID_REQUEST`; no practice-match or sale-state cross-checks — routes/service.py:458-497
- §3.7 — insert — ambiguity — ticket creation against non-ACCEPTED sale rejected with `ERR_INVALID_STATE` (409) — routes/service.py:75-80
- §3.7 — insert — ambiguity — multiple qualifying warranties: earliest-created wins, ties to creation order — calc.py:407-410
- §3.7 — insert — ambiguity — dispatch selector ties: `created_at` then onboarding order — calc.py:382
- §3.7 — insert — ambiguity — resolve: non-DISPATCHED ticket rejects with `ERR_INVALID_STATE` regardless of caller; assignment 403 only when DISPATCHED — routes/service.py:252-260, 280-283
- §3.7 — insert — ambiguity — a part with no van entry at all is rejected with `ERR_PARTS_NOT_ON_VAN` — routes/service.py:288-301
- §3.7 — insert — ambiguity — reopen boundary: exactly 30 days after `resolved_at` still reopens; only strictly later rejected — routes/service.py:349
- §4 — revise — mismatch — 201 only for primary-effect creations; action endpoints that spawn resources (dispatch, acceptance, replenishment) and the usage-profile upsert return 200 — routes/service.py:222, routes/equipment.py:254, routes/ops.py:17, routes/usage_profiles.py:106

No new sections, no invented behavior; PRD.md is untouched.
