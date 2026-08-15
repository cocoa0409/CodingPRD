# Worklog — task_1867_janitorial_sanitation_supply_distribution

## Step 1: Create Task Directory — 2026-08-14T21:47:00.000Z

Directory `tasks/task_1867_janitorial_sanitation_supply_distribution/` and `workspace/` pre-created by pipeline runner (per command args; index scan skipped by instruction).

## Step 2: Generate Scaffold — 2026-08-14T22:19:00.000Z

All three scaffold artifacts are generated and verified. Summary:

**Files written** (under `/home/ubuntu/github/CodingPRD/tasks/task_1867_janitorial_sanitation_supply_distribution/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (response envelope verbatim, entities, state machines, concurrency rules, calculations, validations, endpoints, errors, roles); neither design key present
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design` (§1.9)

**Counts:**
- Entities: 13 (Facility, Product, UsageRecord, ForecastProfile, Technician, Dispenser, TrainingRecord, StandingOrder, Order, OrderLine, ContractBid, SubstitutionProposal, TrialProgram)
- State machines: 11 (non-linear cycles on ContractBid revision loop, StandingOrder pause/resume, Facility suspend/reinstate, Product shortage/resolve; auto-transitions and bubble-ups on Order/OrderLine)
- Calculations: 7 (usage_forecast PROVISIONAL/FINAL, fuel_surcharge QUOTED/ACTUAL, order_line_pricing per-line-rounding, order_total_rollup pinned evaluation order, credit_exposure, effective_unit_price, trial_conversion_credit)
- Validations: 20 priority-ordered rows
- Endpoints: 64 (incl. `POST /jansan/ops/run-daily` checkpoint and `POST /jansan/_clock/set_current_utc` with pinned default 2026-08-01T00:00:00Z)
- Errors: 19 (all referenced by ≥1 validation)
- Roles: 4 (DistributorAdmin opaque, SalesRep opaque, FacilityManager entity_backed:Facility, FieldTechnician entity_backed:Technician)
- Concurrency rules: 1 OCC rule (ForecastProfile PATCH, `expected_forecast_profile_version` → ERR_STALE_VERSION 412)

**§1.8:** 18 instances total, 18 non-stub (9 rules × 2, all differentiation clauses honored — different entity domains, different modes (b)/(c), different cascade triggers (depth 3 + depth 2), different error-category pairs, different metrics/endpoints, different entity pairs, half-open vs closed interval semantics, units vs dollars conserved quantities).

**§1.9:** 42 instances total, 39 non-stub (3 `excluded_because` stubs citing real §1.8 instances), spanning all nine guide sections: entities 8, state_machines 11, calculations 4, validations 8, endpoints 2, errors 3, rbac 4, cross_cutting_layers 1, consistency_model 1. Instance names unique across the union of both design files (60 total).

**Verification:** `scaffold_lint.py` verdict, verbatim:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(306 calls scanned across both design files; all payloads ⊆ endpoint inputs, all captures resolve to declared output fields, OCC version inputs are `${var}` placeholders, zero unbound placeholders.) Also verified: all numeric asserts were pre-computed as literals from the pinned formulas (e.g., subtotal 5000 → fee 0/surcharge 200/total 5200; forecast FINAL avg 1.0 vs PROVISIONAL 3.0 on identical records), no forbidden race vocabulary, and enum closure (removed an initially-declared but unreachable `WITHDRAWN` bid state).

## Step 3: Copy Shared Files — 2026-08-14T22:19:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1867_janitorial_sanitation_supply_distribution/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T22:34:00.000Z

All audits pass. The PRD is complete and verified.

**Output:** `workspace/PRD.md` — 315 lines.

**Section list:**
- §1 Introduction (2 paragraphs, business-context angle, notes the `/jansan` mount)
- §2 Global Specifications (11 subsections): 2.1 RBAC, 2.2 API Response Structure (verbatim block, byte-identical PASS), 2.3 Pagination, 2.4 Resource Identity and Common Fields, 2.5 Referenced Resources and Existence Validation, 2.6 Money/Precision/Rounding, 2.7 The Logical Clock, 2.8 Optimistic Concurrency Control, 2.9 The Facility Exposure Ledger, 2.10 Stock Reservation Semantics, 2.11 The Validation Priority Stack (all 20 validations as a numbered, explicitly ordered list)
- §3 Business Logic (9 subsections): 3.1 Facility Onboarding/Suspension/Archival, 3.2 Product Catalog and Warehouse Stock, 3.3 Usage Capture and Consumption Forecasting, 3.4 Closed-Loop Chemical Program (dispensers + dilution training), 3.5 Standing Orders and Auto-Replenishment, 3.6 Order Placement/Pricing/Settlement, 3.7 Shortage Response and the Substitution Cascade, 3.8 Commercial Programs (contract bids + sample trials), 3.9 The Daily Ops Checkpoint
- §4 Endpoint Definitions: 64 rows, 4 columns (Method/Path/Description/Authorized Roles), row-by-row diffed against scaffold — 0 mismatches
- §5 Error Code Catalogue: 19 rows, 2 columns (Error ID/HTTP Status)

**Hard-contract audit results:**
- **Contract 1 (Field-Name Coverage): PASS** — entity fields 80/80, request-body ids 54/54, query params 13/13, path params 12/12, error ids 19/19, state enum values 31/31 (audit initially flagged `SUSPENDED`/`TERMINATED`, which only appeared inside combined tokens like `` `ACTIVE → SUSPENDED` ``; fixed by splitting state pairs into separate backticked tokens; path params appear inside §4's backticked path strings)
- **Contract 2 (Rule Coverage): PASS** — validations with priority 20/20 expressed in the ordered §2.11 stack; OCC rule 1/1 (PATCH endpoint, `expected_forecast_profile_version`, `ERR_STALE_VERSION`/412 all named, pure stale-version framing); state transitions 40/40 expressed including all 8 OrderLine transitions and the 3-way cancel sibling groups; calculations 7/7 with full formula prose (dual PROVISIONAL/FINAL and QUOTED/ACTUAL variants, pinned rollup order, divisor-always-90, equality-triggers semantics); all applies_to scopes enumerated (e.g. facility gate names all six guarded operations); cross-entity cascades (shortage 3-link, bid reprice, trial conversion, suspend/reinstate) all stated with their secondary effects
- **Contract 3 (§3 Path Purity): PASS** — 517 backticked tokens in §3, zero paths, zero bare HTTP methods, zero method+path combos

**Conscious compressions:** (1) list-endpoint filters are stated as one narrative sentence per entity in §3 rather than restating `limit`/`offset` each time (§2.3 covers pagination globally); (2) the standing-order frequency-to-days mapping (7/14/30) is stated once in §3.5 and §3.9 cross-references it; (3) delivery minimum written as "5,000 cents ($50.00)" to preserve the cents contract while reading naturally; (4) read-endpoint role lists live in the §4 table rather than being repeated in prose for every fetch/list. No rules were dropped — compressions affect repetition, not specification content.

## Step 6: Generate Implementation — 2026-08-14T22:55:00.000Z

All remaining servers belong to other tasks' sessions. Mine are cleaned up. The implementation is complete.

**Files written** (all under `workspace/implementation/`):

- `start.sh` — executable launcher; guards `pip install` behind `python3 -c "import flask"`, then `exec python3 app.py` (foreground, `$PORT` default 10000, binds `0.0.0.0`). Verified fresh boot in ~2.5s via `bash start.sh`.
- `requirements.txt` — Flask>=3.0,<4.0
- `app.py` — Flask entry point, blueprint registration, ApiError/404/405/400/500 handlers producing the scaffold's error envelope
- `db.py` — 13 in-memory dict tables, all empty at boot (no seeding)
- `clock.py` — logical clock pinned at `2026-08-01T00:00:00Z` startup default, monotonic, ISO-8601 3-fractional-digit formatting/parsing
- `errors.py` — `ApiError` + all 19 scaffold error IDs
- `response.py` — envelope helpers: `meta{api_request_id, api_request_timestamp}` + `response_type` + `data`; pagination fields `limit/offset/total_count/has_more` inside `meta`
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (401), role membership (403), FacilityManager entity-backed ownership (403)
- `services.py` — all calculation engines (usage_forecast PROVISIONAL/FINAL with 90-day window and ÷90 divisor, per-line round-half-up then sum, pinned fee→surcharge→total rollup, fuel surcharge tiers 4%/6%/9% × distance bands 1.0/1.25/1.5, credit exposure, effective-unit-price with closed-window bid selection, trial credit cap), shortage cascade, forecast recompute, standing-order preview, bid→standing-order cascade, order placement pipeline
- `routes_facilities.py`, `routes_products.py`, `routes_usage.py`, `routes_forecast.py`, `routes_dispensers.py` (technicians + dispensers + training), `routes_standing_orders.py`, `routes_orders.py` (orders + order lines), `routes_substitutions.py`, `routes_bids.py`, `routes_trials.py`, `routes_ops.py` (run-daily sweep + clock set)

**Endpoint count: 64/64** implemented — matches both the scaffold endpoint table and PRD §4 (all resources, state-transition actions, list endpoints with pagination, `/jansan/ops/run-daily`, `/jansan/_clock/set_current_utc`).

**Key interpretation decisions:**

1. **Facility ledger resync** — `committed_cents`/`outstanding_cents` recomputed by full aggregation over the facility's orders on every money event (place, delivery reprice, invoice, cancel, shortage cascade, substitution accept/decline/expire). This is equivalent to the PRD's delta-adjustment language but immune to drift; `Facility.version`/`updated_at` bump only when a counter actually changes.
2. **Validation priority stack** — implemented in PRD §2.11 order: auth(1) → endpoint role(2) → entity-backed ownership(3) → existence(4) → request shape(5) → OCC(6) → state(7) → facility gate(8) → product availability(9) → stock(10) → dilution(11) → zone(12) → tech window(13) → bid overlap(14) → clock(15) → dup SO(16) → dup trial(17) → discontinue(18) → archive(19) → credit(20). Notably, ownership (3) precedes existence (4), so a FacilityManager referencing a facility that isn't theirs gets 403 even if the id doesn't exist.
3. **Body-FK 404 for opaque roles** — DistributorAdmin/SalesRep requests with nonexistent body-referenced ids return 404 (verified).
4. **Substitution accept price_delta** — finalized as `(new frozen unit price − original frozen unit price) × qty` at accept time.
5. **Standing-order generation in run-daily** — generated orders attempt full placement; on any ApiError the order stays DRAFT (per PRD "stays DRAFT for manual attention"), and `next_run_date` advances by frequency regardless. Facility-inactive generators skip placement (order stays DRAFT) since the placement facility gate applies.
6. **Trial conversion** — builds the conversion order, freezes its line price to compute the merchandise subtotal for the credit cap (`min(sample_value_cents, subtotal)`), sets `trial_credit_cents`, then runs the normal placement pipeline which recomputes the full rollup with the credit floored at 0.
7. **Half-open vs closed intervals** — technician windows half-open `[start, end)` (touching OK), bid protection windows closed (touching = overlap), both verified.
8. **Fresh-boot cleanliness** — store is empty per boot; all state lives in module-level dicts inside one process; per-test-server restarts get a pristine store. Smoke-verified across three separate process boots.

**Verification:** three smoke suites run against live boots covering facility/product/order lifecycle, money math (including delivery-minimum shortfall fee, QUOTED→ACTUAL surcharge repricing, credit equality boundary), training gating, shortage cascade (with and without substitutes), proposal accept/decline/expiry sweep with exact-expiry boundary (strict `>`), bid lifecycle including closed-window touching-overlap rejection and revision loop, trial conversion with credit capping, dispenser zone/technician-window/half-open rules, forecast PROVISIONAL-vs-FINAL divergence, OCC 412, clock regression, standing-order suspend/reinstate asymmetry, archive/discontinue guards, RBAC 401/403/404, and envelope shapes. All passing (the 6 initial "failures" across the runs were traced to bugs in my throwaway smoke scripts — wrong expected arithmetic and a stale port — not the implementation; each was re-verified with corrected expectations or raw curl).

## Step 5: Generate Unit Tests — 2026-08-14T23:05:00.000Z

That extra test is intentional — the `credit_boundary_at_limit_passes_then_exceeds` instance is a boundary pair (at-limit passes / one-cent-over fails), and queue B requires ≥1, so 2 is compliant. Everything checks out.

**Task:** task_1867_janitorial_sanitation_supply_distribution — complete test infrastructure + suite generated from the two design indices only.

### Files written

**test_helpers/ (9 files, ~1,400 lines):**
- `types.py` — 13 entity TypedDicts (all carry id/created_at/updated_at/version per PRD §2.4), 19 status/enum classes, role enum
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (all 46 endpoints under `/jansan`, including `_clock/set_current_utc` and `ops/run-daily`)
- `api_errors.py` — 19 `ApiErrorId` values with HTTP map registered via `set_error_http_status_map`
- `assertions.py` — `assert_{entity}` per entity + stock/ledger invariant checkers
- `constants.py` — domain thresholds (FORECAST_WINDOW_DAYS=90, LEAD_TIME_DAYS=7, DELIVERY_MINIMUM_CENTS=5000, fuel tiers 3.00/4.00, distance bands 25/75, PASS_SCORE_PCT=80, default clock 2026-08-01T00:00:00Z)
- `factories.py`, `test_users.py` (with mandatory `make_facility_manager_headers` / `make_field_technician_headers` entity-backed builders), `fixtures.py` (composite setups: placed orders, active standing orders, awarded bids, pending substitution proposals, certified training, forecast profiles with usage)
- `__init__.py` — barrel export

**test_suite/ (9 files):** `conftest.py` + 8 test files organized by concern (facilities/catalog/auth, forecasting+OCC, orders/pricing, lifecycle/credit/stock, dispensers/training, standing orders, shortage/substitution, bids/trials/clock).

### Test count: **76** (collected cleanly by pytest)

### Coverage
- **Queue A (Difficulty):** 18/18 instances translated, exactly 2 tests each (36 tests). None skipped — every instance's rule is verbatim-covered by PRD §2/§3 and uniquely derivable.
- **Queue B (Corner):** 39/39 non-stub instances translated (40 tests; the credit-boundary instance gets a boundary pair). The 3 `excluded_because:` stubs (`dispenser_install_sets_closed_loop`, `bid_revision_cycle`, `error_facility_inactive_on_place`) were not translated; all cross-references resolve to real queue A instances.

### PRD-first adjudications applied
- Dropped `version == 1`-at-create sub-assertions (two corner instances) — PRD says version "increments by one on every modification" but never pins the birth value; not two-reader derivable.
- Dropped "no product persisted" clause (invalid-enum test) — no product list endpoint exists to verify it.
- Timestamp equality assertions (`installed_at`, `expires_at`, `next_run_date`) use prefix matching on the derived instant, since PRD pins the time but not the millisecond serialization suffix.
- Priority-pair tests are legitimate because PRD §2.11 explicitly states "the first failing check determines the response" with numbered priorities.

### Stage 2 self-checks (all passing)
- All 76 docstrings carry exactly one `Design:` tag as the final line; every tag resolves to a real instance with correct rule_id/section.
- All 81 quoted PRD citations survive whitespace-normalized literal grep of PRD.md (C1/C2/C3).
- No `skip`/`skipif`/`xfail` markers; no "scaffold" references in generated code; AST scan found zero unresolved names; `py_compile` + import + `pytest --collect-only` all clean.

## Step 7: Run Tests and Iterate — 2026-08-14T23:20:00.000Z

Clean exit condition met — all 8 parallel rounds pass 76/76.

**Iterations run:** 2 (baseline sweep → diagnose → fix → verification sweep)

**Baseline:** 70/76 in all 8 rounds (6 deterministic failures, zero flakiness — same 6 tests failed in every round).

**Tests deleted:** none. Every failing test asserted a rule verbatim-covered by PRD and uniquely derivable; all failures were STEP 2 test-artifact bugs.

**Fixes applied to `test_helpers/` (1 file):**
- `test_helpers/fixtures.py` — `setup_placed_order()`: added the `unit_of_measure="CASE"` parameter and forwarded it to `setup_facility_with_product()`. Four tests (`test_allocation_moves_units_on_place`, `test_cancel_releases_reservation_without_drift`, `test_cascade_cancels_line_and_order_when_no_substitute`, `test_cascade_releases_stock_and_committed_credit`) passed `unit_of_measure="EACH"` — a PRD-declared product field (§3.2) — and died with `TypeError` in fixture setup before reaching any assertion. The composite fixture simply hadn't forwarded a parameter its sibling fixtures already supported.

**Fixes applied to `test_suite/` (2 files, 3 spots):**
- `test_suite/test_04_order_lifecycle_credit_stock.py` — `test_place_succeeds_after_reinstatement`: expected `total_cents` corrected 6200 → 5200. PRD §3.6 pins `total_cents = subtotal + fee + surcharge`; here 1000 + 4000 + 200 = 5200, matching even the test's own docstring ("subtotal 1000 + fee 4000 + surcharge 200"). The implementation's 5200 was PRD-correct.
- Same file — `test_invoice_moves_committed_to_outstanding`: expected `total_cents` and `outstanding_cents` corrected 6200 → 5200 (identical arithmetic typo; delivery at the same fuel index 2.50 keeps the QUOTED surcharge of 200).
- `test_suite/test_07_shortage_and_substitution.py` — `test_substitution_proposal_expiry_sweep`: message-string-only correction 6200 → 5200 (assertion `committed_cents == 0` was already correct; message aligned for future diagnostic clarity).

**Fixes applied to `implementation/`:** none. In every failure the implementation computed the PRD-correct value; the bugs were all in the test artifact layer.

**Final state:** 8/8 rounds × 76/76 tests passed under `--isolation per-test-server`, verified programmatically across all `results.1..8.json`.

## Step 8: Finalize PRD — 2026-08-14T23:30:00.000Z

Zero-diff confirmed. Files are identical at 315 lines each.

**PRD.md vs PRD_FINALIZED.md line counts and %-delta:** 315 lines / 315 lines — 0.00% delta. Zero edits.

**Changes applied:** none. Each step_7_diff item traces to a test-artifact bug; the PRD already uniquely pins the implementation's behavior in every case.

**Per-item verification log (in lieu of per-edit search log, since there are no edits):**

1. **`test_helpers/fixtures.py` — `setup_placed_order()` `unit_of_measure` forwarding**
   - Subject: PRD §3.2 product field `unit_of_measure`.
   - Impl paths enumerated: `workspace/implementation/routes_products.py:29,48` (field is required-on-create, stored as free-form string).
   - Test helper path: `test_helpers/fixtures.py:74,113,205` — composite fixture was missing a `unit_of_measure` parameter that its sibling `setup_facility_with_product` already accepted.
   - PRD §3.2 (line 150) already declares `unit_of_measure` as "a free-form `unit_of_measure` such as CASE, GAL, or EACH". Impl matches PRD. Pure fixture bug — no PRD silence, no PRD edit.

2. **`test_place_succeeds_after_reinstatement` expected `total_cents` 6200 → 5200**
   - Subject: order rollup `total_cents` computation for `subtotal=1000, fuel_index=2.50, default distance multiplier=1.0`.
   - Impl paths enumerated: `workspace/implementation/services.py:20` (`DELIVERY_MINIMUM_CENTS = 5000`), `:149-170` (`fuel_pct` returns 4% below 3.00; distance multiplier 1.0 <25 mi), `:173-190` (`recompute_order_money`: fee = max(0, 5000−1000) = 4000; surcharge = 5000 × 0.04 × 1.0 = 200; total = 1000+4000+200−0 = 5200), `:417-431` (placement rollup), `:77` (committed_cents summation), plus all callsites of `recompute_order_money` (delivery reprice at `:421` QUOTED, delivery ACTUAL path, shortage cascade recompute in §3.7 chain, substitution accept/decline recompute, trial-conversion pipeline, standing-order preview path is separate at `:357`).
   - PRD §3.6 (line 188) explicitly pins the rollup formula in prose: "total_cents, the subtotal plus fee plus surcharge minus trial_credit_cents, floored at zero", with fee = "shortfall between the subtotal and the 5,000-cent ($50.00) delivery minimum" and surcharge = "4 percent when the index is below 3.00" × "1.0 under 25 miles". Uniquely determines 5200. Test had arithmetic typo; impl was correct. No PRD edit.

3. **`test_invoice_moves_committed_to_outstanding` expected `total_cents` and `outstanding_cents` 6200 → 5200**
   - Subject: identical rollup as item 2 (delivery at same fuel_index 2.50 keeps QUOTED=ACTUAL=200 surcharge); plus ledger semantics at INVOICED transition.
   - Impl paths enumerated: same as item 2, plus `services.py:77-79` (ledger recomputation over PLACED/PARTIALLY_BLOCKED/DELIVERED vs INVOICED) and the invoice endpoint's commit→outstanding move.
   - PRD §3.6 (line 190) pins "committed_cents falls by the order's total_cents and outstanding_cents rises by the same amount". PRD already determines both the 5200 total and the ledger movement. Test had identical arithmetic typo. No PRD edit.

4. **`test_substitution_proposal_expiry_sweep` assertion message 6200 → 5200**
   - Subject: proposal-expiry cascade releasing the order's 5200 commitment from `committed_cents`.
   - Impl paths enumerated: proposal-expiry sweep path (decline-equivalent), the auto-cancel chain in §3.7 (`services.py` shortage/substitution cascade), and the ledger recompute at `:77`.
   - PRD §3.7 (line 202) pins "the daily sweep expires a PENDING proposal once the clock is strictly past its expires_at, moving it to EXPIRED with exactly the same line, order, and ledger effects as a decline". The underlying 5200 is pinned by §3.6 as in item 2. Message-only fix; assertion itself was already correct. No PRD edit.

**Conclusion:** The correct output is the unchanged copy. PRD_FINALIZED.md exists at `workspace/PRD_FINALIZED.md` and is byte-identical to PRD.md.

## Step 9: Complete PRD — 2026-08-14T23:45:00.000Z

Done. `workspace/PRD_COMPLETED.md` is written.

**Files:** `PRD_FINALIZED.md` 315 lines / 53,171 chars → `PRD_COMPLETED.md` 315 lines / 56,446 chars (**+0 lines, +3,275 chars**). All changes are in-paragraph inserts/revisions; no sections added or removed.

**Counts:** 19 ambiguity-pins, 3 mismatch-revisions (17 paragraphs touched; the §2.4 paragraph carries one pin + one revision, §3.8 trials paragraph carries two pins).

**Changes:**

- §2.1 — insert — ambiguity — FacilityManager on list endpoints is not rejected; results are scoped to own `facility_id` before query filters — routes_usage.py:77-78, routes_forecast.py:87-88, routes_dispensers.py:152-153,260-261, routes_standing_orders.py:112-113, routes_orders.py:123-124,253-255, routes_substitutions.py:66-67, routes_trials.py:91-92
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit` (must be 1–100) or `offset` (≥0) → `ERR_VALIDATION` (400) — routes_usage.py:91-99 (and identical `_pagination` in all list route files)
- §2.4 — insert — ambiguity — resources are born with `version` 1 — services.py:40-48
- §2.4 — revise — mismatch — stock-counter moves (`qty_on_hand`/`qty_allocated`) never refresh the product's `updated_at`/`version` (product version changes only on shortage declare/resolve/discontinue), and a facility whose recomputed ledger/`closed_loop_enrolled` is unchanged is not refreshed — services.py:425-430, routes_orders.py:169-175,208-216, services.py:80-83,91-93
- §2.5 — insert — ambiguity — array payload entries (order/bid `lines`, standing-order `items`) validated per-entry in array order: entry shape first, then referenced-product existence; first failing entry decides — routes_orders.py:32-48, routes_standing_orders.py:33-46, routes_bids.py:36-47
- §2.5 — insert — ambiguity — undefined path or unsupported method → `ERR_NOT_FOUND` (404); malformed JSON body treated as empty object — app.py:42-54
- §2.7 — insert — ambiguity — every server-generated timestamp (created_at/updated_at, all lifecycle stamps, envelope `api_request_timestamp`) reads the logical clock — clock.py, response.py:18, services.py:42,53
- §3.2 — insert — ambiguity — duplicate `sku` → `ERR_VALIDATION`; negative opening `qty_on_hand` → `ERR_VALIDATION` — routes_products.py:30,38-40
- §3.3 — insert — ambiguity — usage records born with `posted_at` null — routes_usage.py:53
- §3.3 — insert — ambiguity — duplicate forecast profile per facility+product → `ERR_VALIDATION` — routes_forecast.py:37-39
- §3.3 — insert — ambiguity — forecast profile's initial computed fields: `avg_daily_usage` 0.0, `reorder_point` = `safety_stock`, `recommended_qty` 0, `replenishment_recommended` = (`current_on_hand` ≤ `safety_stock`), `variant_used`/`last_computed_at` null — routes_forecast.py:48-53
- §3.4 — revise — mismatch — "(a technician may later be `INACTIVE`)" → no API operation transitions a technician out of `ACTIVE` — routes_dispensers.py:42-50
- §3.4 — insert — ambiguity — non-CHEMICAL dispenser product → `ERR_VALIDATION` — routes_dispensers.py:81-82
- §3.4 — revise — mismatch — training records may be scheduled against any existing product regardless of category (was "against a chemical product") — routes_dispensers.py:219-239
- §3.5 — insert — ambiguity — `price_protected` requires the AWARDED bid's closed protection window to cover the current clock time — services.py:344-356
- §3.5 — insert — ambiguity — auto-generated orders use `delivery_date` = standing order's `next_run_date` and zero line discounts — routes_ops.py:86-92
- §3.6 — insert — ambiguity — `discount_pct` bounds are inclusive (0 and 1 allowed), outside → `ERR_VALIDATION` — routes_orders.py:43-44
- §3.6 — insert — ambiguity — order born with all money fields zero, `fuel_surcharge_variant` `QUOTED`, `fuel_index_at_delivery`/`placed_at` null; lines born with `unit_price_cents`/`line_total_cents` 0 until placement — routes_orders.py:51-83
- §3.8 — insert — ambiguity — duplicate `bid_reference` → `ERR_VALIDATION` — routes_bids.py:53-55
- §3.8 — insert — ambiguity — `trial_end` must be on or after `trial_start` (equality allowed), else `ERR_VALIDATION`; trials born with `conversion_order_id` null and `conversion_credit_cents` 0 — routes_trials.py:43-44,60-61
- §3.8 — insert — ambiguity — conversion after `trial_end` → `ERR_INVALID_STATE` (409); on placement-pipeline failure the rejection propagates, the conversion order remains `DRAFT`, and the trial stays `ACTIVE` — routes_trials.py:121-122,129-148

**Deliberately not pinned (justified):** `has_more` formula (impl's `offset+len(page) < total_count` is observably equivalent to any standard reading), `ERR_INTERNAL` 500 fallback (outside the PRD's 4xx-only error-catalogue scope), `api_request_id` random-segment length (opaque identifier, contract is only the `req_` prefix), and unreachable defensive re-checks in bid submit / standing-order activate (create-time validation already guarantees them).
