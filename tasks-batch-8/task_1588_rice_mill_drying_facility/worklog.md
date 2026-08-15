# Worklog — task_1588_rice_mill_drying_facility

## Step 1: Create Task Directory — 2026-08-13T23:43:00.000Z

Task directory `tasks/task_1588_rice_mill_drying_facility/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline invoker. Step 1 treated as DONE per instructions; no index scan performed, no other task directory touched. Difficulty target: **harder than expert level** (per user directive), to be conveyed to the scaffold generator.

## Step 2: Generate Scaffold — 2026-08-14T00:47:00.000Z

All artifacts are complete and verified. Final lint verdict (verbatim):

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  §1.5 endpoints declared:    69
  §1.1 entities declared:     12
  §1.8 instances scanned:     24
  §1.9 instances scanned:     45
  Calls scanned (§1.8+§1.9):  691

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Summary

Generated the full scaffold for task_1588_rice_mill_drying_facility from the scenario alone (no sibling tasks consulted), saved to `/home/ubuntu/github/CodingPRD/tasks/task_1588_rice_mill_drying_facility/`:

- `SCAFFOLD.yaml` — §1.0–§1.7 (no design keys embedded)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`

### Design shape (harder-than-expert calibration)
- **Complexity profile**: ledger-reconciliation (grower settlement) x quota-allocation (bin capacity); layers: optimistic concurrency, dual-variant calculation, cascading side effects, rate/threshold triggers; flat FK topology; cyclic state machines; segregation-of-duties role model; immediate consistency.
- **Entities: 12** (HarvestSeason, Grower, DeliveryContract, Bin, PaddyLot, DryingRun, MillRun, PackagingRun, ByproductSaleOrder, FumigationEvent, FoodSafetyHold [polymorphic BIN|LOT target], Settlement)
- **State machines: 11** — cycles on Season (reopen), PaddyLot (regrade self-loop), Settlement (dispute->revise loop), ByproductSaleOrder (release loop), Bin (fumigation loop)
- **Calculations: 12** — incl. dual-variant shrink (handheld vs official), tiered marginal drying charge, per-line vs aggregate checkoff rounding (1–2 cent divergences pinned), pinned waterfall order (gross->drying->checkoff->advance->net), variety-keyed milling yield with plug conservation, half-open fumigation windows vs 30-min-buffered closed packaging intervals
- **Endpoints: 69** (incl. per-season logical clock with fixed default 2026-08-01T00:00:00Z and a computed byproduct-inventory read)
- **Errors: 55** (all referenced by ≥1 design instance; none dangling)
- **Roles: 10** (9 opaque ops roles + entity-backed GrowerRep; SoD: settlement approver must differ from creator)
- **Concurrency rules: 2** — true OCC only: contract-delivery and contract-amend, both on `DeliveryContract.version` (412 ERR_STALE_CONTRACT_VERSION)

### Design files
- **§1.8: 24 instances** across all 9 rules — dual_variant 3 (PaddyLot weight / Settlement money / MillRun inventory domains), combinatorial 3 (modes a, b, c), non_linear 3, transitive_cascade 2 (depth-3 regrade->settlement->season; depth-2 fumigation->bin->drying-runs), priority_pair 3 (state-vs-capacity, safety-vs-constraint, state-vs-temporal), boundary 4 (moisture==base cliff, exactly-100% fulfillment, exact bin fit, clearance_at exact second), cross_entity 2, temporal_overlap 2 (distinct interval semantics), compensating_invariant 2 (bin mass vs paid money)
- **§1.9: 53 instances** (45 active + 8 excluded_because stubs) spanning entities / state_machines / calculations / validations / endpoints / errors / rbac / cross_cutting_layers / consistency

### Verification performed
- `scaffold_lint.py`: clean (691 calls checked against §1.5; all FKs reverse-reachable)
- Every formula-derived assert was **executed as code** (Decimal, round_half_up) — all literals confirmed (e.g. dry 338.24 vs 340.32, checkoff 1003 vs 1002, charge 10709/4356/14157, mill split 81.60/47.60/6.80/16.00/44.00 conserving to 200.00)
- Placeholder closure audit: 0 unbound `${var}` in payloads, paths, `as_user_id`, and assert lines across both design files
- Error-catalog closure both directions; instance names unique across the union; no forbidden concurrency vocabulary

## Step 3: Copy Shared Files — 2026-08-14T00:48:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1588_rice_mill_drying_facility/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T01:10:00.000Z

All checks pass. The single "non-state arrow" flag is the `lots → SETTLED` phrase in §4's endpoint description column — intended compactness in the index table, not a §3 violation. The PRD is complete and verified.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1588_rice_mill_drying_facility/workspace/PRD.md` — 371 lines.

**Section list:**
- §1. Introduction (3 paragraphs: harvest business context, provisional-vs-final measurement tension, season tenancy under `/mill`)
- §2. Global Specifications & System-Wide Principles
  - 2.1 User and Role-Based Access Control (10 roles; `GrowerRep` entity-backed by `Grower`, nine opaque roles; SoD on settlement approval)
  - 2.2 API Response Structure (emitted verbatim from `section-2.2-response-structure.md`, confirmed byte-identical)
  - 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending, meta fields)
  - 2.4 Seasons, Tenancy, and the Logical Clock (`current_clock_iso` default `2026-08-01T00:00:00Z`, never wall-clock)
  - 2.5 Common Resource Properties (all 12 entities carry `id`/`created_at`/`updated_at`/`version`)
  - 2.6 Units of Measure, Monetary Precision, and Rounding (cwt, integer cents, 2dp round-half-up, unrounded plugs)
  - 2.7 Request Validation Order (all 11 scaffold priorities as an explicit ordered evaluation)
  - 2.8 Optimistic Concurrency Control (both OCC rules: lot create + contract amend, `expected_contract_version`, `ERR_STALE_CONTRACT_VERSION`/412)
  - 2.9 Bin Capacity Accounting and Variety Locking
  - 2.10 Milled-Product and Byproduct Inventory Accounting (5 products, produced/consumed/reserved/shipped/available)
- §3. Business Logic & Workflows (8 subsections): 3.1 Season Lifecycle; 3.2 Growers & Delivery Contracts; 3.3 Scale-Ticket Intake; 3.4 Grading/Regrade/Rejection; 3.5 Storage & Drying; 3.6 Milling, Packaging & Byproduct Sales; 3.7 Fumigation & Holds; 3.8 Settlement & Payment
- §4. Endpoint Definitions (69-row, 4-column table — matches all 69 scaffold endpoints)
- §5. Error Code Catalogue (55-row, 2-column table — all 55 scaffold error ids)

**Coverage audit results:**
- **Contract 1 (Field-Name Coverage):** PASS — `entities[].fields`: 106/106 present in backticks; `endpoints[].input` (incl. query params and `to_iso8601`/`expected_contract_version`): 70/70 present; 51/51 enum & state values present; 10/10 role names exact.
- **Contract 2 (Rule Coverage):** PASS — validation priorities: 11/11 expressed as ordered prose in §2.7; OCC rules: 2/2 fully specified (write operation + `expected_contract_version` + error id + 412, no race framing); state transitions: all 41 across 10 machines expressed with preconditions and side effects (including cascades: fumigation→drying-run auto-cancel, regrade→settlement `DISPUTED`/`LOT_REGRADED`→season revert, dispute-from-`APPROVED`→lots revert, settle→contracts `DEFAULTED`, pay→grower ledger); calculations: all 11 reconstructed in precise prose (shrink/87-divisor model, 4/7/12-cent drying tiers with boundary points, 2/3/1 grade weights with inclusive thresholds, 105% over-delivery strict guard, pinned gross→drying→checkoff→advance→net waterfall with per-line vs aggregate rounding variants, variety-keyed milling standards with unrounded plugs and conservation, 30-minute changeover and half-open fumigation windows with exact-fit/back-to-back allowances, strict spot cap); sibling branches symmetric (OPEN vs PARTIALLY_FULFILLED cancel/default, WEIGHED vs GRADED reject, manual vs auto drying cancel, provisional vs approved dispute).
- **Contract 3 (§3 Path Purity):** PASS — 466 backtick tokens scanned; 0 path tokens, 0 bare HTTP methods, 0 method+path tokens.
- Additional checks: §2.2 verbatim block matches source; all 55 error ids appear in §2/§3 narrative (not only §5); zero pseudocode operators (`>=`, `==`, `+=`, …) and zero fuzzy hedging words in prose; all 16 `→` usages are state-pair framings.

## Step 5: Generate Unit Tests — 2026-08-14T01:47:00.000Z

Generation complete. All files live under `/home/ubuntu/github/CodingPRD/tasks/task_1588_rice_mill_drying_facility/`.

## Summary

**93 tests generated, all collecting cleanly** (`PYTHONPATH=. pytest --collect-only`), zero skip/xfail markers, zero untagged/phantom tags.

### Queue A — Difficulty (24 instances × 2 tests = 48 tests, no shortfalls)
- `dual_variant_calc` (6 tests): shrink_handheld_vs_official_moisture, settlement_checkoff_per_line_vs_aggregate, mill_yield_estimated_vs_actual
- `combinatorial_formula` (6): drying_charge_tiered_marginal_rates, settlement_three_line_rounding_order, settlement_advance_waterfall_order_pinned
- `non_linear_state_machine` (6): lot_regrade_self_loop_cycle, settlement_dispute_revise_cycle, byproduct_reserve_release_cycle
- `transitive_cascade` (4): regrade_disputes_settlement_reverts_season, fumigation_cancels_planned_drying_runs
- `priority_pair_validation_conflict` (6): season_state_beats_spot_cap_constraint, hold_safety_beats_variety_constraint, bin_state_beats_fumigation_window_overlap
- `boundary_precision_check` (8): moisture_exactly_base_zero_shrink, contract_exactly_fulfilled_at_100_percent, bin_exact_capacity_fit, fumigation_clearance_at_exact_second
- `cross_entity_state_dependency` (4): settlement_approve_gated_by_season_review, lot_grading_gated_by_active_hold
- `resource_temporal_overlap` (4): fumigation_half_open_adjacency_allowed, packaging_line_changeover_buffer
- `compensating_invariant` (4): drying_reserve_cancel_preserves_bin_capacity, dispute_cycle_preserves_paid_money

### Queue B — Corner (45 non-stub instances × 1 test = 45 tests, no shortfalls)
entities 7, state_machines 8, calculations 7, validations 12, endpoints 3, errors 1, rbac 3, cross_cutting_layers 3, consistency 1.

### Instances not translated (7 corner `excluded_because:` stubs — by rule, cross-references all resolve)
shrink_precision_and_variants_covered → shrink_handheld_vs_official_moisture; drying_tier_and_settlement_rounding_covered → drying_charge_tiered_marginal_rates; error_state_vs_capacity_priority_covered → season_state_beats_spot_cap_constraint; error_hold_vs_variety_priority_covered → hold_safety_beats_variety_constraint; error_bin_state_vs_window_priority_covered → bin_state_beats_fumigation_window_overlap; error_boundaries_covered → contract_exactly_fulfilled_at_100_percent; layer_cascading_side_effects_covered → fumigation_cancels_planned_drying_runs; layer_dual_variant_covered → settlement_checkoff_per_line_vs_aggregate. **No non-stub instance was skipped** — every rule survived the PRD-first two-condition filter (PRD §2.7's explicit fixed validation order covers all three priority-pair instances).

### Adjudications applied
- `season_settle_guards_and_contract_default`: the recipe's dual-violation assertion (unpaid settlement AND open order → `ERR_UNPAID_SETTLEMENTS_EXIST`) is a PRD-silent intra-endpoint precedence claim; restructured to exercise each settle guard in isolation (validation-priority silence pattern), keeping the DEFAULTED cascade assertion.
- `run_and_order_invalid_transitions`: dropped the recipe's BINNED-lot-in-drying-run sub-claim (`err_pre`) — PRD §3.5 names `ERR_LOT_ALREADY_IN_DRYING_RUN` only for the non-terminal-run guard and pins no error id for the must-be-GRADED requirement (two-reader failure). The remaining five state-error assertions are all PRD-named.
- Inventory-row assertions tolerate `produced_cwt` vs `produced` key spelling (PRD §2.10 pins component names, not wire keys) via `get_inventory_component`; the numeric ledger values are asserted exactly.

### Helper files
`test_helpers/`: `types.py` (12 TypedDicts + 15 enums), `api_client.py` (52 endpoint methods), `api_errors.py` (55 error ids + HTTP map registered with the framework), `assertions.py` (per-entity + capacity-invariant + inventory-row checkers), `factories.py`, `constants.py` (drying tiers, milling standards, checkoff rate, clock), `test_users.py` (10 role header sets + `make_grower_rep_headers`/`make_clerk_headers` per-instance builders), `fixtures.py` (5-tier composites: `create_open_season`, `create_contract_lot` with auto-OCC version refresh, `setup_binned_contract_lots`, `setup_completed_mill_run`, `settlement_reaching` through draft/issued/approved/paid), `__init__.py` barrel. `test_suite/`: `conftest.py` + 7 domain-named test files.

## Resume Assessment — 2026-08-14T01:48:00.000Z

Previous run ended with an execution error after Step 6's file generation but before its worklog entry. Orchestrator audit on resume:
- Steps 1–5: complete per prior worklog entries; artifacts verified present (SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, workspace/INSTRUCTION.md, workspace/PRD.md, test_helpers/ 9 files, test_suite/ 7 test files collecting 93 tests cleanly).
- Step 6: implementation/ contains all expected files (app.py, db.py, errors.py, middleware.py, response.py, util.py, validate.py, routes/ 13 modules, services/core.py, start.sh, requirements.txt; 2498 lines total). All .py files compile (`py_compile` clean). Boot smoke test: `bash start.sh` on a test port came up, served a well-formed error envelope (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` with `data`/`meta`/`response_type` structure) for a probe request, and shut down cleanly. Verdict: Step 6 output is complete and valid — kept as-is, not regenerated. Resuming pipeline at Step 7.

## Step 7: Run Tests and Iterate — 2026-08-14T02:05:00.000Z

Clean 8-round sweep achieved. Final summary:

## Summary

**Iterations run:** 2 sweeps (8 parallel rounds each, 93 tests/round)
- Iteration 1: 89/93 in every round — 4 deterministic failures, zero flakiness
- Iteration 2: **93/93 in all 8 rounds — fully green, union of failures empty**

**Tests deleted:** none. Every failing test traced to a verbatim PRD rule with unique derivability (PRD §3.7 fumigation window semantics; PRD §3.8 checkoff rounding variants), so all four were kept and repaired.

**Fixes applied to `test_helpers/`:** none — fixtures/factories/headers were all PRD-consistent.

**Fixes applied to `test_suite/`:**

1. `/home/ubuntu/github/CodingPRD/tasks/task_1588_rice_mill_drying_facility/test_suite/test_04_bins_drying_fumigation.py` — the module-level helper `_cleared_fumigation_on_b06()` called `api.begin_aeration` / `api.clear_fumigation`, but `api` is a pytest fixture in scope only inside test functions → `NameError` in `test_fumigation_window_overlap_inside_window_rejected` and `test_fumigation_back_to_back_at_clearance_allowed`. Fix: added `api_client` to the `test_helpers` import and switched the helper's two calls to `api_client.*` (the fixture returns that same singleton, so semantics are unchanged).

2. `/home/ubuntu/github/CodingPRD/tasks/task_1588_rice_mill_drying_facility/test_suite/test_06_settlements.py` — test-authoring arithmetic slip contradicting both PRD §3.8 and the test's own comment. For lot lines 100100/100300/100500, the per-line checkoffs are 501+502+503 = **1506**, not 1507. Corrected: `provisional_checkoff_cents` 1507→1506, `provisional_net_cents` 299393→299394 in `test_three_line_provisional_checkoff_sums_per_line_roundings`; and the final-minus-provisional difference 2→1 in `test_three_line_final_checkoff_rounds_aggregate_once` (its other constants — aggregate checkoff 1505, final net 299395 — were already correct).

**Fixes applied to `implementation/`:** none. The implementation was PRD-faithful on all four exercised rules (half-open fumigation window with back-to-back-at-clearance allowed; per-line half-up checkoff rounding in the provisional variant vs single aggregate rounding in the final variant). Verified independently with Decimal recomputation before touching the tests.

## Step 8: Finalize PRD — 2026-08-14T02:12:00.000Z

## Step 8 complete — zero edits; PRD_FINALIZED.md is byte-identical to PRD.md

**Line counts / delta:** PRD.md 370 lines, PRD_FINALIZED.md 370 lines, 0% delta (`cmp` confirms byte-identical).

**Changes:** none. Both `<step_7_diff>` items were test-side authoring bugs (a pytest fixture scoping `NameError`; an arithmetic slip in expected constants) with zero implementation changes. Neither reveals a PRD silence or mismatch — verified below.

### Verification log (zero-edit outcome)

**Candidate site 1 — §3.7 fumigation window (half-open, back-to-back-at-clearance allowed)**
- (a) Subject: fumigation overlap-window semantics and aeration/clearance clock gates.
- (b) Impl paths enumerated (grep for `fumigation|clearance|exposure_ends|ERR_FUMIGATION|ERR_EXPOSURE|ERR_AERATION` across all `.py`, excluding `__pycache__`):
  - `implementation/routes/fumigation.py` — the only behavioral site: create (window conflict check at line 51: `if started < o_clear and o_start < clearance:`), begin-aeration (line 98: `clock < exposure_ends_at` → error, so exact-at-end passes), clear (line 118: `clock < clearance_at` → error, so at-or-past passes). Auto-cancel of `PLANNED` drying runs via `core.cancel_drying_run` (core.py:304).
  - Non-behavioral references only: `errors.py` (error catalog), `app.py` (blueprint registration), `db.py` (collection name), `routes/helpers.py` (404 mapping). No other path computes or compares fumigation windows.
- (c) Wording adjustment: none needed. PRD.md line 214 already pins the exact predicate verbatim ("an overlap exists when the new start falls before the other's clearance and the other's start falls before the new clearance, which means back-to-back treatments whose start exactly equals the predecessor's clearance are allowed"), line 212 pins the half-open window ("ends at, but does not include, `clearance_at`"), and line 216 pins both clock gates ("a clock reading exactly at the exposure end is sufficient"; "at or past `clearance_at`"). The Step 7 failures here were a pure Python scoping bug (`api` fixture referenced from a module-level helper); the behavior under test was never in question.

**Candidate site 2 — §3.8 checkoff rounding (per-line provisional vs single-aggregate final)**
- (a) Subject: checkoff/gross rounding variants and the pinned gross→drying→checkoff→advance→net evaluation order.
- (b) Impl paths enumerated (grep for `checkoff|CHECKOFF|provisional_|final_|compute_provisional|compute_final`):
  - `implementation/services/core.py` — `compute_provisional` (lines 257–270): per-line `sum(q0(line_value × 0.005))`; `compute_final` (lines 273–289): exact aggregate gross `Σ(dry_weight × price)` rounded once via `q0`, checkoff `q0(exact_gross × 0.005)`. `CHECKOFF_RATE = Decimal("0.005")` (line 19).
  - `implementation/util.py` lines 52–53: `q0` = `ROUND_HALF_UP` to whole cents — matches PRD's "rounded half-up" in both variants.
  - Callers: `routes/settlements.py` (create:72, approve:117, revise:180) and `routes/lots.py:266` (regrade cascade recomputing provisional on a DRAFT settlement — covered by existing PRD §3.8 prose on regrade/revise, and by §3.4's cascade; not part of the Step 7 items and consistent).
- (c) Wording adjustment: none needed. PRD.md line 224 pins the provisional variant verbatim ("that line's value multiplied by the half-of-one-percent checkoff rate (0.005) and rounded half-up to whole cents per line"), and line 228 pins the final variant ("exact line values — dry weight times price, unrounded — rounded half-up to whole cents exactly once at the end … applies the 0.005 rate to the exact aggregate gross and rounds half-up a single time"). Independent Decimal recomputation confirms the corrected test constants are uniquely derivable from this prose: per-line checkoffs 501+502+503 = 1506; aggregate checkoff 1505; final-minus-provisional difference 1. The Step 7 failure was a test-author arithmetic slip, not a PRD ambiguity.

Output file: `workspace/PRD_FINALIZED.md` (byte-identical copy of PRD.md).

## Step 9: Complete PRD — 2026-08-14T02:35:00.000Z

Step 9 complete. `workspace/PRD_COMPLETED.md` is written as a minimal patch over PRD_FINALIZED.md.

**Source vs output**: PRD_FINALIZED.md (source, byte-identical to PRD.md) — 370 lines / 58,423 chars → PRD_COMPLETED.md — 373 lines / 62,543 chars (**+3 lines, +4,120 chars**, 24 diff hunks, all inline inserts/revisions; no new sections).

**Counts**: 15 ambiguity-pins, 8 mismatch-revisions (23 changes total).

Changes:

- §2.1 — insert — ambiguity — GrowerRep scoping: growers collection compares against the grower's own `id`; list endpoints filter rather than reject; resources with no grower reference (seasons, bins, all runs, orders, fumigation events, holds) are GrowerRep-readable unscoped — middleware.py:43-61, routes/helpers.py:40-46,99-106
- §2.3 — insert — ambiguity — non-integer `limit`/`offset`, limit outside 1-100, or negative offset → `ERR_INVALID_REQUEST` (400) — routes/helpers.py:16-37
- §2.3 — insert — ambiguity — `has_more` = (offset + page size) < total_count; `total_count` counts the filtered set; filters are exact-equality, null fields never match, unknown filter params ignored — response.py:40, routes/helpers.py:87-96
- §2.4 — revise — ambiguity — clock set accepts the supplied instant verbatim (forward or backward, no monotonicity check), normalized to whole-second UTC — routes/seasons.py:142-150, util.py:63-74
- §2.5 — revise — mismatch — cascades are not "visible in the same response" (endpoints return only the primary resource); revised to atomic-with-write, visible on subsequent read — routes/*.py return shapes, services/core.py:43-52
- §2.6 — insert — ambiguity — cwt quantities serialize as plain JSON numbers (trailing zeros dropped), monetary values as JSON integers — response.py:9-16
- §2.6 — revise — mismatch — scheduling and fumigation timestamps are both compared at whole-second precision (impl truncates only microseconds; PRD claimed minute precision for scheduling) — util.py:63-74, routes/packaging_runs.py:43-46
- §2.7 step 4 — insert — ambiguity — numeric domain rules: strictly positive (`contracted_cwt`, `capacity_cwt`, `gross_weight_lbs`, `input_cwt`, `quantity_cwt`, `package_size_kg`) vs non-negative (`spot_daily_cap`, `advance_issued_cents`, `tare_weight_lbs`, `fuel_cost_cents`, `actual_output_cwt`, `units_planned`, `units_produced`, `exposure_hours`, `aeration_hours`, `act_*_cwt`); prices and grade deltas are signed integers; percentages unconstrained — validate.py:39-76 and all create/verify routes
- §2.7 — insert — mismatch — resource-dependent check placement: contract grower/variety match fires right after contract resolution, fumigation future-start right after season resolution, and at lot storage `ERR_LOT_ALREADY_IN_DRYING_RUN` is checked right after lot-state, ahead of bin status and holds — routes/lots.py:62-68,305-310, routes/fumigation.py:31-36
- §2.9 — revise — mismatch — variety lock is also set when the first drying-run reservation is placed (from the run's first lot), and is enforced only at direct store; drying-run planning performs no variety check — routes/drying_runs.py:71-72,110-113, routes/lots.py:318-326
- §2.10 — insert — ambiguity — inventory response shape: object keyed by product name with `produced_cwt`/`consumed_cwt`/`reserved_cwt`/`shipped_cwt`/`available_cwt` at 2dp — services/core.py:232-241, routes/seasons.py:153-157
- §3.1 — insert — ambiguity — season collection is filterable by `status` — routes/seasons.py:46
- §3.2 — insert — ambiguity — `grade_adjustments` required at creation, keys limited to the six symbols, signed integer cent values, omitted grades price at zero delta — validate.py:121-139, routes/lots.py:177-180
- §3.2 — revise — ambiguity — amendment accepts any subset of the three fields; omitted fields unchanged — routes/contracts.py:64-86
- §3.3 — revise — mismatch — `drying_run_id` is retained after run completion for traceability and cleared back to null only on cancellation (PRD had implied it exists only "while a non-terminal run holds it") — routes/drying_runs.py:116-121, services/core.py:303-316
- §3.4 — insert — ambiguity — regrade recomputes contract fulfillment with version advancing only when tally/status actually changes; the 105% over-delivery guard is not re-evaluated on regrade — routes/lots.py:258-261, services/core.py:143-163
- §3.4 — insert — ambiguity — a GRADED lot referenced by a planned drying run may still be rejected; the run's reservation and expected output are unchanged — routes/lots.py:276-293
- §3.5 — revise — mismatch — "Five guards" corrected to "Six guards" (the store-door list enumerates six) — PRD prose vs routes/lots.py:305-323
- §3.5 — revise — ambiguity — drying-run completion moves only lots still standing GRADED to BINNED (a mid-run-rejected lot is skipped); the reservation is still released in full — routes/drying_runs.py:108-121
- §3.6 — insert — ambiguity — a mill run scheduled against an unlocked bin records null variety; at completion a still-null variety resolves from the bin's then-current lock, falling back to `LONG_GRAIN`, and is stamped on the run — routes/mill_runs.py:101-105
- §3.8 — insert — ambiguity — drafting is not gated on season state; `lot_ids` recorded in lots' creation order; provisional amounts computed at draft creation — routes/settlements.py:20-73
- §5 — revise — mismatch — added `ERR_NOT_FOUND` (404) row and a note that it is emitted for unmatched routes, including undeclared methods on declared paths — app.py:28-34

Everything else in the implementation (69 endpoints, all state machines, all 12 calculations, OCC, hold/temporal/capacity guard ordering, settlement two-pass rounding) was already uniquely pinned by the PRD and left untouched.

## Pipeline Complete — 2026-08-14T02:35:00.000Z

All Steps 1–9 done. Final state: 93/93 tests passing across an 8-round parallel stability sweep (per-test-server isolation); PRD.md → PRD_FINALIZED.md (byte-identical, zero Step-7-driven edits) → PRD_COMPLETED.md (23 minimal patches). task_1588_rice_mill_drying_facility is benchmark-ready.
