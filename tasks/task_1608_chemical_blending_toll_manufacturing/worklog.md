# Worklog — task_1608_chemical_blending_toll_manufacturing

## Step 1: Create Task Directory — 2026-08-14T01:19:00.000Z

Task directory `tasks/task_1608_chemical_blending_toll_manufacturing/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher; Step 1 treated as DONE. No other task_* directory was scanned, created, or written to.

## Step 2: Generate Scaffold — 2026-08-14T01:46:30.000Z

Note: the scaffold subagent's first turn ended after planning without writing any files; it was resumed via SendMessage and completed on its second turn.

All three files exist, lint clean. Here is the final summary.

---

## Summary

Generated the Chemical Blending & Toll Manufacturing scaffold for task 1608 at `/home/ubuntu/github/CodingPRD/tasks/task_1608_chemical_blending_toll_manufacturing/`.

**Files written (lint-clean):**
- `SCAFFOLD.yaml` — 1764 lines, 81 KB
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1638 lines, 106 KB
- `SCAFFOLD_CORNER_DESIGN.yaml` — 1164 lines, 70 KB

**Scaffold surface (§1.0–§1.7):**
- 12 entities (Customer, PricingAgreement, RawMaterialLot, Recipe, Tank, CleaningRecord, BatchJob, BatchCharge, SDSDocument, PackageConfig, Shipment, HeelDisposalRecord)
- 10 state machines with 34 total transitions; non-linear shapes include the cyclic `Tank.cleaning_state` (DIRTY → … → CLEAN_VALIDATED → DIRTY via batch completion or QA FAIL), and the branching `BatchJob` with COMPLETED / CANCELLED / REJECTED_QA fork paths each carrying distinct compensation sets
- 7 calculation rules covering tiered_pricing, forward_looking, threshold, aggregation, constraint_propagation, with two explicit PROVISIONAL-vs-FINAL variants on `price_batch_job` and a running-balance reconciliation on `lot_available_kg`
- 25 ordered validation rows (auth → existence → state → safety → temporal → constraint → fiscal)
- 66 endpoints, including a `/_clock/set_current_utc` test-driving endpoint with the fixed startup default `2026-08-01T00:00:00Z`
- 27 domain-specific error codes
- 7 roles implementing segregation-of-duties (TankOperator vs QAValidator on cleaning validate; SDSAuthor isolated from lifecycle transitions)
- 2 OCC concurrency rules (BatchJob release, PricingAgreement activate), each with `expected_*_version` payload fields and 412 ERR_STALE_VERSION

**§1.8 Difficulty design — 9 rules × 2 instances = 18 instances**, all §0.5 rules covered:
- `dual_variant_calc`: TOLLING_FEE vs FORMULATED_PRICE price formula on BatchJob + chronological running-balance lot reconciliation (different entity domains)
- `combinatorial_formula`: 4-input over-yield credit branch (mode a) + `>=454 L` placard threshold (boundary-precision, distinct mode)
- `non_linear_state_machine`: BatchJob forking (HOLD_QA → COMPLETED|REJECTED_QA) + Tank cyclic cleaning loop
- `transitive_cascade`: `/complete` → Tank release → blocks next release (depth 3); `/batch-charges` → lot recompute → next charge rejected (depth 2)
- `priority_pair_validation_conflict`: state vs business_safety (release), and business_safety[19] vs business_safety[22] (complete: SDS vs placard)
- `boundary_precision_check`: half-open `effective_to` datetime boundary + `residue_ppm <= 50` numeric boundary
- `cross_entity_state_dependency`: BatchJob→Tank + BatchJob→PricingAgreement; Shipment→BatchJob
- `resource_temporal_overlap`: half-open `[start, end)` on Tank + full-coverage-supersedes window on PricingAgreement
- `compensating_invariant`: lot `quantity_kg_available` round-trip via charge→cancel; tank `occupied_by_batch_id` round-trip via release→complete

**§1.9 Corner design — 27 instances across 7 sections** (entities, state_machines, calculations, endpoints, errors, cross_cutting_layers, consistency_model), covering every capability area in the scenario: recipe/fraction-sum validation, consignment lot accounting, tank cleaning & segregation-of-duties, SDS consistency and re-issue, packaging/placarding thresholds, heel manifest enforcement, RBAC denials, OCC 412 paths, and priority-pair conflicts.

**Key difficulty-design choices made:**
- Half-open `[from, to)` interval semantics on PricingAgreement with a twist: full-coverage *supersedes* rather than rejects — partial overlap rejects with `ERR_AGREEMENT_WINDOW_OVERLAP`. Forces dual-path reasoning on the same validation.
- Tank has two orthogonal state dimensions (`operational_state` × `cleaning_state`) plus a derived `last_product_ghs` that is only cleared by validated cleaning, creating a hard precondition chain: prior batch's GHS class + incomplete cleaning blocks any subsequent release.
- Two-algorithm pricing (tolling vs formulated) pinned at BatchJob create, frozen thereafter — prevents retroactive re-pricing when the customer's agreement is later superseded.
- Over-yield credit uses `over_yield_split_pct` with the customer absorbing 100% of the upside-priced mass and then getting credited back the split share — compound rounding surface.
- The `price_batch_job` formula's TOLLING_FEE mode is intentionally identical across PROVISIONAL and FINAL, while FORMULATED_PRICE diverges — creating a "false dual variant" trap where implementers might over-engineer.
- Segregation-of-duties enforced via `X-User-ID` comparison on CleaningRecord validate (validator ≠ creator).
- Lint verdict: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (562 calls scanned, 0 violations).

## Step 3: Copy Shared Files — 2026-08-14T01:48:20.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1608_chemical_blending_toll_manufacturing/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-14T02:10:00.000Z

All checks pass. The PRD is complete. Here is the verbatim summary.

## Generation Summary — task_1608_chemical_blending_toll_manufacturing

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1608_chemical_blending_toll_manufacturing/workspace/PRD.md` — 302 lines.

**Section list**:
- §1 Introduction (2 paragraphs — business-context angle: consignment inventory, tank farm, regulatory gates, dual commercial models)
- §2 Global Specifications (9 subsections): 2.1 RBAC, 2.2 API Response Structure (verbatim block, byte-identical to `section-2.2-response-structure.md`), 2.3 Pagination (incl. all list-filter query params), 2.4 Resource Identity and Change Tracking, 2.5 The Logical Clock, 2.6 Hazard Classes/Storage Zones/Segregation, 2.7 Units/Precision/Rounding, 2.8 OCC, 2.9 Nested Resource Resolution and Validation Order
- §3 Business Logic (9 subsections, chronological lifecycle strategy): 3.1 Customers, 3.2 Pricing Agreements, 3.3 Recipes, 3.4 Consignment Lots, 3.5 Tanks & Cleaning, 3.6 Batch Job Lifecycle (incl. both pricing variants), 3.7 SDS, 3.8 Packaging/Placarding/Shipment, 3.9 Heel Disposition
- §4 Endpoint Definitions: 4-column table, 66 rows (all scaffold endpoints incl. clock + 12 top-level reverse-reachability GETs)
- §5 Error Code Catalogue: 2-column table, 28 rows

**Coverage audit results**:
- Contract 1 (Field-Name Coverage): PASS — 76/76 entity fields, 4/4 common fields, 56/56 request-body ids, 10/10 query params, 10/10 path params present in backticks (95 unique identifiers, 0 missing; verified by script with code-fence-stripped token extraction; two passes run).
- Contract 2 (Rule Coverage): PASS — 25/25 validations expressed with priority ordering (§2.9 enumerates the full pipeline: headers → role → path L-to-R → body FKs → state → 20 business rules in priority order → OCC last); 2/2 OCC rules expressed with endpoint + `expected_*_version` + `ERR_STALE_VERSION`/412 and no race-framing; all 30 state transitions across 10 machines expressed with preconditions and error ids; 7/7 calculations in precise prose (no pseudocode/fuzzy words — grep-verified); all 27 catalog error ids + `ERR_RECIPE_CHARGE_ORDER_INVALID` appear in §2/§3; all 34 state strings and all enum values present; all endpoint side effects and `applies_to` scopes enumerated (e.g., credit-hold on both create and release; segregation on release/heel-post/lot-intake; UN-rated on package-config-create and complete; placard on complete and dispatch); sibling branches rendered symmetrically (PASS/FAIL, TOLLING_FEE/FORMULATED_PRICE, PROVISIONAL/FINAL, INTAKE/RELEASED cancel, supersede-vs-reject).
- Contract 3 (§3 Path Purity): PASS — 431 backtick tokens scanned, 0 path tokens, 0 bare HTTP methods, 0 method+path combos.

**Zero-Silence Rule decisions** (scaffold gaps/conflicts resolved without invention):
1. `ERR_RECIPE_CHARGE_ORDER_INVALID` is named by the Recipe approve precondition but absent from `errors[]`; validation 17 maps both composition checks to `ERR_RECIPE_FRACTION_SUM_INVALID` (422). §3.3 expresses both mappings (create → `ERR_RECIPE_FRACTION_SUM_INVALID`; approve charge-order → `ERR_RECIPE_CHARGE_ORDER_INVALID`) and §5 carries the extra row at 422 so a PRD-only reader has its status.
2. `quantity_kg_on_hand`: entity description conflicts with the `lot_available_kg` calculation and heel-post side effects — I followed the calculation/side-effect consensus (on_hand = received − consumed − disposed; posted returns leave on_hand unchanged) and stated the return behavior explicitly.
3. `quantity_kg_committed`: merged the entity description ("parent batch non-terminal") with the calc (status `COMMITTED`) into one consistent sentence.
4. `highest_component_ghs` timing: computed at create (per endpoint side effect), frozen at approve (per state machine) — both stated.
5. Shipment-dispatch `carrier_name` check has no nominated error id; mapped to `ERR_INVALID_REQUEST` per the catalog's "required field missing" condition.
6. `OUT_OF_SERVICE` enumerated as an operational value with no invented inbound transitions.
7. Released-charge reconciliation expressed via the derived formula (removal from the committed sum returns mass to `quantity_kg_available`) rather than the state machine's looser "add back to on_hand" phrasing, avoiding double-count against the field's derivation.

## Step 5: Generate Unit Tests — 2026-08-14T02:40:00.000Z

Generation complete. Summary:

## Tests generated

**Queue A (Difficulty) — 36 tests, 18/18 instances covered at 2× each:**

| Rule | Instances | Test file |
|---|---|---|
| dual_variant_calc | price_batch_job_provisional_vs_final_formulated_mode (2), lot_available_kg_consignment_reconciliation (2) | test_07, test_06 |
| combinatorial_formula | price_batch_job_formulated_over_yield_credit_combinatorial (2), placard_threshold_at_454l_boundary (2) | test_07, test_08 |
| non_linear_state_machine | batch_job_reject_qa_and_cancel_revert_paths (2), tank_cleaning_state_machine_cyclic_revalidation (2) | test_06/test_07, test_04 |
| transitive_cascade | batch_complete_cascades_tank_release_and_sds_lock (2), charge_commit_cascades_lot_recompute_and_capacity_validation (2) | test_07, test_06 |
| priority_pair_validation_conflict | release_blocked_state_vs_credit_hold_priority (2), complete_blocked_sds_vs_placard_priority (2) | test_05, test_07 |
| boundary_precision_check | pricing_agreement_window_half_open_boundary (2), residue_ppm_at_50_threshold_boundary (2) | test_05, test_04 |
| cross_entity_state_dependency | batch_release_depends_on_tank_and_pricing_agreement_state (2), shipment_loading_depends_on_batch_completed (2) | test_05, test_08 |
| resource_temporal_overlap | tank_schedule_overlap_half_open_interval (2), pricing_agreement_window_overlap_supersede_semantics (2) | test_05, test_03 |
| compensating_invariant | charge_commit_then_cancel_restores_lot_available_invariant (2), tank_occupancy_invariant_via_complete_reverses_reservation (2) | test_06, test_07 |

**Queue B (Corner) — 27 tests, 27/27 non-stub instances covered at 1× each** (the file contains zero `excluded_because:` stubs): entities ×5 (test_01), state_machines ×7 (test_02/05/06/04), calculations ×2 (test_02/07), endpoints/RBAC ×3 (test_01), errors ×7 (test_05/03/06/07/08), cross_cutting_layers ×2 (test_03), consistency_model ×1 (test_06).

**Instances skipped: none.** Every instance passed the PRD-first two-condition filter. Two translations worth noting:
- `Corner/errors/occ_stale_version_on_release_returns_412`: the instance's own `test_recipe` is self-admittedly broken (its assert block is a note, not an assertion). Since its grounds (`concurrency_rules[batch-release-stale-batchjob]`) are verbatim PRD-covered (§2.8: `expected_batch_job_version` + `ERR_STALE_VERSION` 412), I translated it as a deterministic stale-version release (expected = current − 1 → 412, batch stays INTAKE) rather than skipping.
- `Corner/state_machines/recipe_fraction_sum_invalid_rejected_at_create`: translated as create-time rejection, matching both the instance name and PRD §3.3 ("Composition failures at creation are rejected with `ERR_RECIPE_FRACTION_SUM_INVALID` (HTTP 422)") — the yaml's approve-time trigger contradicts the PRD and was not used.

## Helper files created (test_helpers/)
`types.py` (12 TypedDicts + 18 enums; all entities carry id/created_at/updated_at/version per PRD §2.4), `api_client.py` (64 endpoint methods incl. top-level bare-id collections), `api_errors.py` (28 error IDs + HTTP map registered via `set_error_http_status_map`), `assertions.py` (12 entity assertions + `assert_lot_balances`), `factories.py` (12 payload factories), `constants.py` (RESIDUE_LIMIT_PPM=50, PLACARD_VOLUME_THRESHOLD_L=454, package capacities, zone/severity/placard maps), `test_users.py` (6 opaque role headers + per-user-id builders for segregation-of-duties tests), `fixtures.py` (5-tier composites: `setup_batch_context`, `setup_released_batch`, `setup_batch_in_hold_qa`, `setup_batch_ready_for_completion`, `setup_completed_batch`, plus cleaning-cycle helpers), `__init__.py` barrel.

## Coverage audit
- 63 tests total, all collected by pytest cleanly; every docstring ends with exactly one `Design:` line copied verbatim from the source yaml `name:`.
- Script audit: 63/63 tags resolve to real instances (36 Difficulty = 18×2, 27 Corner = 27×1); zero unresolved, zero dual-tags, zero untagged.
- PRD citation pass: 89 quoted citations across all docstrings; every one verbatim-matches `workspace/PRD.md` after whitespace normalization (one ellipsized citation was found and rewritten verbatim).
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; all code compiles (`py_compile` clean).

## Step 6: Generate Implementation — 2026-08-14T02:33:00.000Z

Implementation complete. Here is the summary:

## Implementation Summary

### Files created (all under `/home/ubuntu/github/CodingPRD/tasks/task_1608_chemical_blending_toll_manufacturing/workspace/implementation/`)

- `start.sh` — Foreground launcher with guarded pip install (`if ! python3 -c "import flask"`) then `exec python3 app.py`
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask entrypoint; binds `0.0.0.0:$PORT` (default 10000); registers all blueprints; error handlers for `ApiError`, 404, 405, generic
- `db.py` — In-memory dicts keyed by id; logical clock state defaulting to `2026-08-01T00:00:00Z`; no seeding anywhere
- `errors.py` — `ApiError` class + all 27 error ID constants from the scaffold
- `response.py` — Envelope helpers producing `meta` / `response_type` / `data`; `api_request_id` prefixed `req_`; ISO8601 UTC timestamps with 3 fractional digits; pagination fields (`limit`, `offset`, `total_count`, `has_more`) inside `meta` only for list responses
- `middleware.py` — `X-User-ID` / `X-User-Role` extraction; role validation against the 6 declared roles; `require_role(...)` with `{"Any"}` support
- `services/common.py` — ID/timestamp helpers, ISO8601 parser, pagination, all serializers, Decimal-based numerics with `ROUND_HALF_UP`, `reconcile_lot_quantities`
- `services/calculations.py` — Severity order, zone map, incompatible pairs, `RESIDUE_LIMIT_PPM=50`, package capacities, placard threshold 454, `compute_highest_component_ghs`, `compute_theoretical_output_kg`, `compute_density_corrected_output_l`, `compute_yield_variance_pct`, `price_batch_job` (both PROVISIONAL and FINAL variants), `compute_placard`, `compute_authoring_consistency_flag`
- `routes/clock.py`, `customers.py`, `pricing_agreements.py`, `raw_material_lots.py`, `recipes.py`, `tanks.py`, `cleaning_records.py`, `batch_jobs.py`, `sds.py`, `package_shipment.py`, `heel_disposals.py`, `top_level.py`

### Endpoint coverage: 56 / 56 (every endpoint in the SCAFFOLD table is implemented)

Includes 1 clock, 6 customer, 5 pricing-agreement, 3 lot, 5 recipe, 3 tank, 5 cleaning-record, 11 batch-job, 3 batch-charge, 3 SDS, 2 package-config, 5 shipment, 3 heel-disposal routes plus the 12 top-level reverse-reachability GETs (batch-jobs, batch-charges, sds-documents, package-configs, shipments, heel-disposals — both `/{id}` and list-with-filters forms).

### State machines implemented (9)

- **Customer**: ACTIVE → SUSPENDED → ACTIVE | TERMINATED (with `ERR_OPEN_BATCH_JOBS` guard)
- **PricingAgreement**: DRAFT → ACTIVE → SUPERSEDED | TERMINATED, including full-coverage supersession cascade and partial-overlap rejection
- **Recipe**: DRAFT → APPROVED → RETIRED (with `ERR_RECIPE_IN_USE` guard)
- **Tank** (dual-axis): operational AVAILABLE ↔ RESERVED ↔ IN_USE driven by batch cascades; cleaning DIRTY → CLEANING_IN_PROGRESS → CLEAN_PENDING_VALIDATION → CLEAN_VALIDATED (or back to DIRTY on FAIL)
- **CleaningRecord**: PENDING → PASSED | FAILED with segregation-of-duties
- **BatchJob**: INTAKE → RELEASED → CHARGING → MIXING → HOLD_QA → COMPLETED | CANCELLED | REJECTED_QA with all cascades (tank reservation, charge consumption, charge release, tank release + dirty)
- **BatchCharge**: COMMITTED → CONSUMED | RELEASED
- **SDSDocument**: DRAFT → ISSUED → SUPERSEDED with `authoring_revision` monotonic per batch
- **Shipment**: PLANNED → LOADING → DISPATCHED | CANCELLED with dispatch-time placard check
- **HeelDisposalRecord**: PENDING → POSTED with waste-manifest + segregation gates

### Calculations implemented

- `price_batch_job` — TOLLING_FEE (base + per-kg × theoretical, identical PROVISIONAL/FINAL) and FORMULATED_PRICE (PROVISIONAL uses theoretical, FINAL uses actual; over-yield credit = excess_kg × formulated_rate × over_yield_split_pct/100 subtracted); round-half-up to integer cents
- `theoretical_output_kg` — batch_size_l × density × (yield_pct/100), 3dp round-half-up
- `density_corrected_output_l` — actual_kg / density, 3dp round-half-up
- `yield_variance_pct` — 100 × (actual − theo) / theo, 3dp round-half-up
- `highest_component_ghs` — severity FLAMMABLE>OXIDIZER>TOXIN>ACID>BASE>NON_HAZ, ties broken by smallest charge_order, joined with customer lots by material_code
- `placard_determination` — capacity map {205,1000,500,20}, threshold 454 with >=, GHS→placard class map, null when not required
- `lot_available_kg` — derived committed/on_hand/available continuously reconciled from charge + heel-disposal state
- `segregation_compatible` — ZONE_ALLOWED map and symmetric INCOMPATIBLE_PAIRS set
- `authoring_consistency_flag` — three-part predicate per PRD §3.7

### Key PRD interpretation decisions

1. **Validation order** — Followed PRD §2.9 literally: header → role → existence → state → credit hold → tank cleanliness → segregation → segregation-of-duties → agreement temporal → tank schedule overlap → agreement window overlap → capacity → charge completeness → lot sufficiency → recipe approved → recipe composition → SDS consistency → SDS issued → UN-rated → package volume → placard → waste manifest → heel disposition → OCC last.
2. **OCC fields are required** on the two guarded endpoints per PRD §2.8 ("non-optional"), so a missing `expected_*_version` is treated as a stale-version failure (412) — consistent with "evaluated last" semantics.
3. **Release precondition `Tank.operational_state == AVAILABLE`** is raised as `ERR_INVALID_STATE` (it isn't in the scaffold's explicit error mapping but is a state precondition per the Tank machine).
4. **PASS validation with residue_ppm > 50** when `last_product_ghs` is non-null returns `ERR_INVALID_REQUEST` (PRD: "anything above it may not [pass]"); the scaffold has no dedicated error ID.
5. **Complete with missing PackageConfig** raises `ERR_PACKAGE_VOLUME_INSUFFICIENT` (PRD §3.6 frames it as "must exist and its total_volume_l must reach...").
6. **Heel-disposal post ordering** — segregation check fires before waste-manifest check per PRD §3.9.
7. **SDS re-authoring** — only supersedes an ISSUED document; if only a DRAFT exists, the new draft starts at revision 1 per PRD §3.7 literal text.
8. **CleaningRecord `created_by`** field added (not in scaffold entity list) to support the segregation-of-duties comparison mandated by PRD §3.5.
9. **Recipe charge_order/fraction-sum validation** — at create, both checks share `ERR_RECIPE_FRACTION_SUM_INVALID` (per scaffold `errors` entry for create); at approve, fraction sum uses `ERR_RECIPE_FRACTION_SUM_INVALID` and charge-order uses `ERR_RECIPE_CHARGE_ORDER_INVALID` per PRD §3.3.
10. **Pagination** — `limit`/`offset` (defaults 10/0, range 1..100, >=0), results sorted by `created_at` ASC; meta fields included only on list responses.

### Smoke test
Ran end-to-end against a live server: clock set, customer, lot, recipe approval, tank registration, cleaning open/submit/validate (PASS), pricing agreement activation, batch create (verified `quoted_price_cents = 10000 + 50 × 1350.0 = 77500`), release (tank cascaded AVAILABLE→RESERVED), charge commit, and start-charging (charges COMMITTED→CONSUMED, lot quantities reconciled, batch version bumped). All steps returned the expected envelope and status codes.

## Step 7: Run Tests and Iterate — 2026-08-14T02:55:00.000Z

All 8 rounds pass cleanly (63/63 each). 

## Summary

- **Iterations run:** 2 (initial sweep identified the failure; post-fix sweep clean).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `test_suite/`:** none.

- **Fixes applied to `implementation/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1608_chemical_blending_toll_manufacturing/workspace/implementation/routes/batch_jobs.py` — `release_batch_job`: removed an extra precondition check `if tank["operational_state"] != "AVAILABLE": raise ERR_INVALID_STATE` that fired before the PRD-listed schedule-overlap check. PRD §3.6's explicit release-check ordering does not include a tank-operational-state gate; the only tank-side guards PRD names are cleanliness (`ERR_TANK_NOT_CLEAN_VALIDATED`), segregation (`ERR_INCOMPATIBLE_SEGREGATION`), schedule overlap (`ERR_TANK_SCHEDULE_OVERLAP`), and capacity (`ERR_BATCH_SIZE_EXCEEDS_CAPACITY`). The unsupported extra check was intercepting the overlap scenario in `test_overlapping_window_release_rejected` and returning `ERR_INVALID_STATE` instead of the PRD-mandated `ERR_TANK_SCHEDULE_OVERLAP`. Per PRD §2.9, "source-state validity" applies to the entity undergoing the requested transition (the batch), not to cascade side-effect targets (the tank).

## Step 8: Finalize PRD — 2026-08-14T03:10:00.000Z

The patch is exactly one revised line. Done.

## Summary

**Line counts / %-delta:** `PRD.md` 302 lines, `PRD_FINALIZED.md` 302 lines — 0% line-count delta (one in-place revision of a single paragraph; the modified line grew by ~60 words).

**Changes (one edit total, tracing to the single step_7_diff item):**
- §3.6 (batch release paragraph) — revise — after the release-check enumeration, inserted "This list is exhaustive: the source-state check is the batch's alone, release performs no check on the tank's `operational_state`, and the cleanliness, segregation, schedule-overlap, and capacity rules are the only tank-side guards," and re-scoped the cascade clause to "cascades the tank from `AVAILABLE` to `RESERVED` — a state the release writes onto the tank, not a precondition the tank must satisfy" — impl: `/home/ubuntu/github/CodingPRD/tasks/task_1608_chemical_blending_toll_manufacturing/workspace/implementation/routes/batch_jobs.py:172-259` (post-fix release has no operational-state gate; line 251 writes `RESERVED` unconditionally).

**Pre-edit search log (mandatory enumeration for the single edit):**
- (a) Subject: batch-release preconditions — specifically whether the tank's `operational_state` is inspected at release and which entity the `ERR_INVALID_STATE` source-state check covers.
- (b) Impl paths enumerated via `grep -rn "operational_state"` and `grep -rn "ERR_TANK_SCHEDULE_OVERLAP|ERR_TANK_NOT_CLEAN_VALIDATED|OUT_OF_SERVICE"` over `implementation/`, each read:
  1. `routes/batch_jobs.py:172-259` — `release_batch_job` (Step 7 site): checks batch-INTAKE, credit hold, tank 404, `CLEAN_VALIDATED`, segregation, agreement 404/ACTIVE/window, schedule overlap, capacity, OCC; no `operational_state` inspection; cascade sets `RESERVED` unconditionally.
  2. `routes/cleaning_records.py:39-46` — cleaning-record creation **does** gate on `tank["operational_state"] != "AVAILABLE"` → `ERR_INVALID_STATE`; PRD §3.5 already specifies this.
  3. `routes/tanks.py:57` — registration initializes `AVAILABLE`.
  4. `services/common.py:189` — serializer, read-only.
  5. `routes/batch_jobs.py:301, 455, 477, 518` — start-charging/complete/reject/cancel cascades write `operational_state` without any prior-state rejection guard.
- (c) Wording adjustment: the sentence is explicitly scoped to release ("release performs no check...", "the only tank-side guards" within the release-check list) so it cannot be read as contradicting path 2 (the §3.5 cleaning rule legitimately gates on `operational_state`); the cascade clause was reworded from a plain "from `AVAILABLE` to `RESERVED`" to "a state the release writes onto the tank, not a precondition" to defuse the exact misreading that produced the removed check, while remaining accurate for paths 1 and 5 (the write is unconditional in the impl). §2.9 was deliberately left untouched: a global redefinition of "source-state validity" risked mis-describing cleaning-record creation, where the tank itself is the entity undergoing the requested transition.

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1608_chemical_blending_toll_manufacturing/workspace/PRD_FINALIZED.md`

## Step 9: Complete PRD — 2026-08-14T03:35:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1608_chemical_blending_toll_manufacturing/workspace/PRD_COMPLETED.md` is written (copied from PRD_FINALIZED.md, then edited in place only).

**Size:** PRD_FINALIZED.md 302 lines / 48,991 chars → PRD_COMPLETED.md 302 lines / 53,648 chars (+4,657 chars, 0 line delta — all edits are inline paragraph inserts/revisions; no new sections).

**Counts:** 25 edits total — 18 ambiguity-pins, 7 mismatch-revisions.

**Changes (one bullet each):**

- §2.1 — revise — ambiguity — unrecognized `X-User-Role` value is rejected as malformed context with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400), not `ERR_UNAUTHORIZED` — implementation/middleware.py:33-38
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST`; `has_more` = `offset` + returned < `total_count`; `created_at` ties broken by ascending `id` — implementation/services/common.py:37-61, response.py:37
- §2.5 — revise — ambiguity — clock accepts any parseable ISO 8601 instant, no monotonicity requirement — implementation/routes/clock.py:12-23
- §2.7 — insert — ambiguity — batch sizes, tank capacities, package counts, `over_yield_split_pct`, `charge_order`, `residue_ppm` are integers; `yield_variance_pct` carried to 3dp round-half-up — implementation/services/common.py:81-95 (to_int), services/calculations.py:113-121
- §2.8 — revise — ambiguity — missing or non-integer `expected_*_version` → `ERR_STALE_VERSION` (412), same as a mismatch — implementation/routes/pricing_agreements.py:159-168, routes/batch_jobs.py:237-247
- §2.9 — insert — ambiguity — `ERR_INVALID_REQUEST` shape/range/enum failures sit outside the fixed validation ordering (raised at point of field inspection); undefined paths or unsupported methods → `ERR_NOT_FOUND` (404) — implementation/app.py:44-57
- §3.2 — revise — **mismatch** — all three rate fields (`tolling_base_fee_cents`, `tolling_per_kg_cents`, `formulated_price_per_kg_cents`) are required at creation under either pricing mode, not per-mode — implementation/routes/pricing_agreements.py:58-67
- §3.2 — insert — ambiguity — `effective_from`/`effective_to` must be present and parseable at creation, but their ordering is checked only at activation — implementation/routes/pricing_agreements.py:74-82 vs 130-133
- §3.3 — revise — **mismatch** — `revision` monotonicity is a convention only; the server validates just integer ≥ 1 — implementation/routes/recipes.py:91-93
- §3.3 — revise — ambiguity — `components` must be non-empty; all composition failures at creation (including bad `charge_order`) → `ERR_RECIPE_FRACTION_SUM_INVALID`; `ERR_RECIPE_CHARGE_ORDER_INVALID` only at approval re-verification — implementation/routes/recipes.py:30-31, 61-74, 110-111
- §3.3 — insert — ambiguity — components with no matching customer lot are skipped in hazard profiling; no resolvable component → `highest_component_ghs` = `NON_HAZ`; value computed once at creation, never recomputed — implementation/routes/recipes.py:113-121, services/calculations.py:76-97
- §3.4 — revise — ambiguity — lot-ownership constraint is enforced at start-charging, not at charge commit — implementation/routes/batch_jobs.py:546-588 vs 291-292
- §3.5 — revise — ambiguity — cleaning record captures creator as `created_by` (returned in responses); submit requires record `PENDING` + tank `CLEANING_IN_PROGRESS` (else `ERR_INVALID_STATE`) and leaves the record itself unchanged — implementation/routes/cleaning_records.py:75, 106-119; services/common.py:206
- §3.5 — revise — ambiguity — both PASS and FAIL require record `PENDING` + tank `CLEAN_PENDING_VALIDATION`; PASS above the 50-ppm limit on a product-bearing tank → `ERR_INVALID_REQUEST` (400) — implementation/routes/cleaning_records.py:128-156
- §3.6 — revise — ambiguity — charge commit performs no batch-state check and does not validate `charge_order`/`material_code`/ownership against the recipe at commit; those gates run at start-charging — implementation/routes/batch_jobs.py:546-588
- §3.6 — revise — ambiguity — charge-book completeness means exactly one `COMMITTED` charge per component; other-status charges ignored; unknown/duplicate `charge_order` also fails with `ERR_INCOMPLETE_CHARGES` — implementation/routes/batch_jobs.py:270-295
- §3.6 — revise — ambiguity — completion gates: earliest-created `ISSUED` SDS governs and supplies the classification; missing package config → `ERR_PACKAGE_VOLUME_INSUFFICIENT`; placard gate requires the batch's shipment to exist and contain `placard_class`; heel gate covers every lot referenced by the batch's charge rows — implementation/routes/batch_jobs.py:373-437
- §3.7 — revise — **mismatch** — replaced "each batch carries exactly one living SDS" with accumulation semantics — implementation/routes/sds.py:58-103
- §3.7 — revise — **mismatch** — re-authoring supersedes only an `ISSUED` document; existing DRAFTs untouched; multiple DRAFT and even multiple ISSUED documents may coexist; new revision = superseded issued revision + 1, else 1; history list returns all documents — implementation/routes/sds.py:58-79, 122-135
- §3.8 — revise — **mismatch** — package-config 1:1 cardinality is conventional, not enforced; completion/dispatch consult the earliest-created configuration — implementation/routes/package_shipment.py:55-59, 71-112
- §3.8 — revise — ambiguity — placarding consults the non-`SUPERSEDED` SDS with the highest `authoring_revision`, falling back to the batch's `highest_component_ghs_snapshot` when no SDS exists — implementation/routes/package_shipment.py:38-52
- §3.8 — revise — **mismatch** — shipment 1:1 also conventional; transitions address the earliest-created shipment and return `ERR_NOT_FOUND` when none exists; dispatch requires an existing package config (else `ERR_INVALID_STATE`); batch-scoped config/shipment fetches return the paginated array envelope — implementation/routes/package_shipment.py:62-66, 115-124, 164-219
- §3.9 — revise — ambiguity — heel masses default to 0 when omitted; lot must exist (404) and be referenced by any of the batch's charge rows regardless of charge status (else `ERR_INVALID_REQUEST` 400); `disposal_method`/`waste_manifest_number` mandatory only at posting, though a supplied `disposal_method` is enum-validated at recording — implementation/routes/heel_disposals.py:49-104
- §3.9 — revise — ambiguity — posting requires record `PENDING` (else `ERR_INVALID_STATE`); the lot's `version` increments on every posting, pure returns included — implementation/routes/heel_disposals.py:119-157
- §4 table — revise — **mismatch** — dropped "1:1" from the package-config/shipment create rows; the two batch-scoped fetch rows now state they return the paginated array envelope — implementation/routes/package_shipment.py:115-124, 164-173

No changes were needed for the §3.6 release check-order, pricing formulas, lot reconciliation formulas, segregation rules, or §5 error catalogue — PRD_FINALIZED already pinned those exactly as implemented.

---

## Pipeline complete

Steps 1–9 all finished. Final state: 63/63 tests passing across all 8 parallel stability rounds under `--isolation per-test-server`; `workspace/PRD_COMPLETED.md` (302 lines, 53,648 chars) is the alignment-complete PRD.
