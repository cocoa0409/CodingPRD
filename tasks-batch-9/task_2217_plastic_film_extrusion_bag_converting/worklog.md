# Worklog — task_2217_plastic_film_extrusion_bag_converting

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2217_plastic_film_extrusion_bag_converting/` and `workspace/` subdirectory (name pre-allocated by the caller; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T04:05:00.000Z

All three artifacts are complete and lint-clean. Final verdict block, verbatim:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2217_plastic_film_extrusion_bag_converting/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2217_plastic_film_extrusion_bag_converting/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2217_plastic_film_extrusion_bag_converting/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    68
  §1.1 entities declared:     13
  §1.8 instances scanned:     29
  §1.9 instances scanned:     67
  Calls scanned (§1.8+§1.9):  2095

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Files written

- `SCAFFOLD.yaml` (§1.0–§1.7; neither companion key present)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

## Scaffold contents

**13 entities:** Product, ResinGrade, BlendRecipe, ExtrusionLine, ExtrusionRun, FilmRoll, RegrindPool, RegrindTransaction (append-only ledger, `common_fields: false`), PrintPress, PlateSet, PrintJob, BagLot, ComplianceDossier.

**10 state-machine tables across 8 machines** — BlendRecipe.status, ExtrusionRun.status, FilmRoll.status, PlateSet.status, BagLot.status, ComplianceDossier.status, ExtrusionLine.posture, plus PrintJob carrying three independent dimensions (status, registration_state, color_state).

**13 calculations:** `blend_composition_totals`, `blend_cost_and_density`, `blend_property_indices`, `regrind_cap_evaluation`, `gauge_capability`, `run_mass_balance` (nominal/as_built variants), `pool_mass_balance`, `seal_strength_qualification` (provisional/final variants), `bag_count_and_accuracy`, `case_packout_allocation`, `line_posture`, `line_occupancy_conflict`, `press_cylinder_capacity`.

**16 validation priorities**, **68 endpoints**, **65-error catalog**, **6 RBAC roles** (PlantAdmin, BlendEngineer, QualityManager, ExtrusionOperator, PrintOperator, ConvertingOperator) + 2 segregation-of-duties rules, **2 OCC concurrency rules** (regrind reincorporation vs. stale pool version; packout vs. stale bag-lot version — both `expected_<parent>_version` → 412-class stale-version errors, the only sanctioned write-write mechanism).

**§1.8 difficulty design: 29 instances** over all nine Difficulty Rules (dual_variant_calc 2, combinatorial_formula 5, non_linear_state_machine 4, transitive_cascade 2, priority_pair_validation_conflict 4, boundary_precision_check 5, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 2).

**§1.9 corner design: 113 instances = 67 full `test_recipe`s + 46 `excluded_because` stubs**, by section: entities 14 (0 stubs), state_machines 15 (6), calculations 13 (8), validations 15 (5), endpoints 6 (1), errors 35 (22), rbac 7 (0), cross_cutting_complexity_layers 6 (3), consistency_model 2 (1).

## Verification performed

- Hard constraint honored: no sibling task directory was listed, globbed, grepped, or read at any point. Design came solely from the scenario text plus the generator skill spec.
- All formula-derived assertions were pre-computed as literals with an independent Decimal/`ROUND_HALF_UP` reference script (gauge Cpk with population sd, seal provisional-vs-final ratio floors, 6-dp bag unit weight → floored theoretical count → count accuracy, regrind cap banding, per-line-rounded blend cost/density, case/pallet waterfall, mass balance and PCR embedding).
- Four independent audits, all clean: (1) every `NNN ERR_X` assertion matches the catalog's declared HTTP status; (2) every `${var}` used in a call or assert is bound by an earlier `captures:` in the same instance; (3) all 65 catalog errors are exercised by §1.8 or §1.9 (no dead errors — one dead error, ERR_PLATE_WEAR_LIMIT_REACHED, was removed during generation); (4) all 40 `state_machines.*` grounds resolve to declared from→to transitions, and every other `grounds[*]` path resolves to a declared §1.1–§1.7 element.
- Forbidden §1.2.1 concurrency vocabulary is absent from names and prose; the only remaining such token is the spec-mandated `claim_type: parallel`.
- Instance names are unique across the union of §1.8 and §1.9; every stub's cited `difficulty_instance` exists by name in SCAFFOLD_DIFFICULTY_DESIGN.yaml.

## Step 3: Copy shared files — 2026-09-01T04:05:30.000Z

Copied `INSTRUCTION.md` from project root to `workspace/INSTRUCTION.md` (53 lines).

## Step 4: Generate PRD — 2026-09-01T04:18:00.000Z

The PRD is complete and passes all three hard contracts.

## Deliverable

`workspace/PRD.md` — **441 lines**, generated from `SCAFFOLD.yaml` (3019 lines, `domain_name: film-extrusion-bag-converting`, difficulty `beyond_expert`). Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced, and no sibling task directory was read.

## Structure

- **§1 Introduction** — plant chain-of-custody framing plus the two design commitments (segregation of duties, non-reversal of compliance cascades).
- **§2 Global Specifications** — 11 subsections: RBAC; API Response Structure (byte-identical verbatim block, confirmed programmatically); Pagination and Collection Filters; Common Resource Properties / Logical Clock / Immutable Ledger Rows; Numeric Precision and Rounding Discipline; Optimistic Concurrency on Pools and Lots; Order in Which a Request Is Screened (all 16 priorities); Derived Aggregates, Cascades and the Line Posture Gate; Food-Contact and Recycled-Content Doctrine; Segregation of Duties; Business-Code Uniqueness.
- **§3 Business Logic & Workflows** — 10 subsections following the physical stream: resin library → blend design and regrind cap → recipe review/supersession → line scheduling → run execution → regrind ledger → roll release → printing (three independent dimensions) → converting/seal/packout → dossiers and revocation cascade.
- **§4 Endpoint Definitions** — 4-column table (Method | Path | Description | Authorized Role(s)), **68 rows**.
- **§5 Error Code Catalogue** — 2-column table, **65 rows**. Document ends here with no audit footer.

## Coverage audit (mechanical, verified against the scaffold)

| Required set | Count | Present | Missing |
|---|---|---|---|
| `entities[].fields[].name` | 181 | 181 | 0 |
| Nested array object keys | 16 | 16 | 0 |
| Write-endpoint `input` identifiers | 107 | 107 | 0 |
| GET query params | 33 | 33 | 0 |
| Common fields (`id`/`created_at`/`updated_at`/`version`) | 4 | 4 | 0 |
| OCC fields (`expected_regrind_pool_version`, `expected_bag_lot_version`) | 2 | 2 | 0 |
| Enum + state-machine values | 72 | 72 | 0 |
| `errors[].id` | 65 | 65 | 0 |
| Roles | 6 | 6 | 0 |
| Endpoint paths in §4 table | 68 | 68 | 0 |
| Validation priorities 1–16 with error codes | 16 | 16 | 0 |
| State-machine transition states (8 machines) | all | all | 0 |
| Calculation/global constants (numeric values) | 37 | 37 | 0 |

**Contract 1 — Field-Name Coverage: PASS.** **Contract 2 — Rule Coverage: PASS** (all 13 calculations, 8 state machines including the three independent PrintJob dimensions and the BagLot 3-way fork, both `concurrency_rules`, both SoD rules, all 16 validation priorities). **Contract 3 — §3 Path Purity: PASS** (938 inline-code tokens in §3, 0 starting with `/`, 0 bare HTTP methods, 0 method+path pairs).

## Notes worth relaying

- Two fixes were applied during the audit: `gauge_readings` and `seal_specimens` were described only in prose ("reading log", "specimen log") and are now also named verbatim in backticks in §3.5 and §3.9.
- One judgment call: the scaffold marks `test_kind` optional on seal-specimen appends without declaring a default. The PRD states it defaults to `BOTTOM_SEAL`, since the seal-qualification calculation reads only `BOTTOM_SEAL` rows and any other default would make the panel unreachable.
- `CAP_DELTA_HIGH` (−5.0) is rendered as prose ("`HIGH` subtracts 5.0 percentage points") rather than as a signed literal, per the no-pseudocode rule; the other two band deltas are rendered the same way.
- Earlier audit runs reported hundreds of false "missing" identifiers. Root cause was the triple-backtick fence in the verbatim §2.2 block desynchronizing inline-code pairing for the rest of the file; stripping fenced blocks before extraction resolved it. The clean numbers above are from the corrected harness.

## Step 6: Generate implementation — 2026-09-01T05:00:00.000Z

Implementation is complete and verified.

## Files created

All under `workspace/implementation/`:

**Core (root)** — `app.py` (Flask factory, blueprint registration, `ApiError`/`HTTPException`/`Exception` handlers), `store.py` (13 in-memory dicts, logical clock, `new_common`/`touch`/`serialize`), `response.py` (meta envelope), `auth.py` (`endpoint(roles)`: 401 then 403), `validation.py` (body/field parsers, pagination, path fetch, FK resolution in PRD §2.7 rule-6 order, uniqueness), `errors.py` (68 error-id → HTTP map), `num.py` (Decimal ROUND_HALF_UP helpers), `config.py` (constants + enums), `requirements.txt`, `start.sh`.

**`services/`** — `refs.py` (chain walkers: `lot_chain`, `eligible_pool`, `is_reversed`), `calc.py` (all derived aggregates: blend indices, gauge capability, pool balances, seal panels, bag/case/pallet allocation), `cascade.py` (`book_transaction`, `propagate_recycled_content`, `rederive_line_posture`, `block_plate_setup_jobs`, `revoke_dossier_cascade`).

**`routes/`** — `registry.py` (clock, products, resin grades, presses, pools, transactions), `blend.py` (recipes, components, submit/approve/reject/reopen), `extrusion.py` (19 routes: lines, runs, gauge samples, regrind draws, film rolls), `printing.py` (11 routes: plate sets, print jobs), `converting.py` (13 routes: bag lots, seal tests, packout, release/ship, compliance dossiers).

## Endpoint count

**68** Flask rules (`len(app.url_map.iter_rules())` excluding `static`), matching the PRD §4 endpoint table.

## Boot verification

`PORT=19217 bash start.sh` from a clean process: ready in **1 s**, and all 13 collection reads returned `200` with `total_count=0`, `n=0`, `response_type: "array"`, a well-formed `req_`+20-char `api_request_id` and a 3-fractional-digit UTC timestamp — confirming **zero seeded data**. No data files are written at runtime (only `__pycache__`, which was removed). Server killed; ports 18217/19217 confirmed closed.

## Verification beyond boot

Four end-to-end smoke suites (in `/tmp`, not deliverables) exercised all 68 endpoints across full happy paths and ~60 negative cases, all passing. Three apparent failures in the last two runs were traced to wrong test expectations, not implementation defects, and each was confirmed against PRD text:

- `product_id` naming a non-product id returns `404 ERR_PRODUCT_NOT_FOUND` (band 6) before `ERR_PRODUCT_MISMATCH` (band 12).
- `finalize-tests` on a `CONVERTING` lot returns `ERR_BAG_LOT_STATE_INVALID` (band 9) before `ERR_INSUFFICIENT_SEAL_PANEL` (band 15).
- An invalid enum member is `400 ERR_INVALID_REQUEST` per band 3, not 422.

Numerics spot-checked against the PRD: `bag_unit_weight_kg` at 6 dp (0.042530), `bag_count_theoretical` floor (380/0.04253 = 8934), `count_accuracy_pct = produced/theoretical×100` at 2 dp, gauge Cpk capped at 4.000, superseding seal panel restricted to `BOTTOM_SEAL` while the SoD check spans all specimens regardless of `test_kind`, cumulative pallet ceiling (8930 bags → 179 cases → 45 pallets), partial-case suppression, and `claim_variance_pct` at 3 dp with the ±0.500 CONFORMING window.

Cascade behavior confirmed correct, including two subtleties: a `SHIPPED` lot is **not** quarantined by dossier revocation (PRD §3.10 lists only QUALIFIED/CONDITIONAL/PACKED/RELEASED), and `clear-capability-flags` returns the line `FROZEN → OPEN` without restoring already-condemned runs/rolls.

## Step 5: Generate unit tests — 2026-09-01T06:35:00.000Z

Stage 2 is complete. Final state of the deliverable:

## Files

`test_helpers/` (9 files, Stage 1): `__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`

`test_suite/` (Stage 2): `conftest.py` + 19 test modules
- Queue A (§1.8 depth index): `test_01_blend_recipe_derivations.py`, `test_02_blend_recipe_lifecycle.py`, `test_03_gauge_capability.py`, `test_04_run_scheduling_and_holds.py`, `test_05_regrind_ledger.py`, `test_06_printing_floor.py`, `test_07_seal_qualification.py`, `test_08_packout_waterfall.py`, `test_09_screening_order.py`, `test_10_conditional_release_gate.py`, `test_11_cascades.py`
- Queue B (§1.9 breadth index): `test_12_reference_entities.py`, `test_13_state_machines.py`, `test_14_calculations.py`, `test_15_validations.py`, `test_16_endpoints.py`, `test_17_errors.py`, `test_18_rbac.py`, `test_19_cross_cutting.py`

Last two files added in this pass: `test_18_rbac.py` (12 tests — the two role exclusives on approve/release/issue, the PlantAdmin non-override, the shared ConvertingOperator/QualityManager seal panel, and both §2.11 duty separations including the submit-then-approve identity trick built with `make_blend_engineer_headers("u-qm-1")`); `test_19_cross_cutting.py` (14 tests — pool `version` OCC on repeated draws, per-append recipe reconciliation, the second-hold posture threshold plus resume, and the run-completion response immediacy).

## Counts and coverage

- 217 test functions total (the not-found sweep in `test_17` additionally parametrizes to 12 cases).
- Queue A: 29 difficulty instances, every one with >=2 tests, 0 under-covered.
- Queue B: 67 live corner instances — 66 translated, 1 skipped. All 46 `excluded_because:` stubs untranslated, none tagged.
- Tag audit: 0 untagged, 0 dual-tagged, 0 tags pointing at non-existent instances, 0 stub instances tagged.
- Citation audit: every test has at least one physical docstring line carrying >=8 verbatim PRD tokens; 0 non-verbatim quotes (whitespace-normalized substring check against `workspace/PRD.md`); 0 ellipsis-abbreviated quotes.
- `pyflakes` clean over `test_suite/`; all names imported from `test_helpers`, all `api.*` and `ApiErrorId.*` references resolve.

## Skipped instance (1)

`Corner/validations/a_one_layer_recipe_for_a_three_layer_product_is_rejected` — the designed recipe trips two rung-12 gates simultaneously (`ERR_LAYER_COUNT_MISMATCH` and `ERR_BARRIER_STRUCTURE_REQUIRED`, since a one-layer blend also lacks the barrier layer that the three-layer product demands). The PRD lists the seven submit gates without pinning an intra-rung evaluation order, so the asserted `ERR_LAYER_COUNT_MISMATCH` is not uniquely derivable. Left as a gap, per the skip rule — no weakened test, no xfail, no placeholder.

## Design-yaml deviations worth flagging to the PRD/design owners

Field-name drift in the design indices was mapped onto the PRD's actual names: `net_output_kg` -> `net_good_kg`, `regrind_applied_pct` -> `regrind_actual_pct`, `blended_cost_per_kg` -> `blend_cost_per_kg`, `RUN_SCRAP` -> `EXTRUSION_SCRAP`. Two assertions were dropped as non-derivable rather than invented: `virgin_feed_kg` (the PRD names only "an intermediate virgin feed mass", never exposing a field) and a non-null `release_blocked_reason` after a refused release (the PRD stamps that field only on quarantine). One instance's precondition was corrected — the count-accuracy release test needed a `PACKED` lot to reach its designed 422, since releasing a `QUALIFIED` lot uniquely derives 409 `ERR_BAG_LOT_STATE_INVALID`.

## Step 7: Run tests and iterate — 2026-09-01T07:35:00.000Z

All 8 parallel rounds pass: **231/231 in every round**, no flakiness.

## Summary

**Iterations run:** 2 (initial sweep → 3 fixes → confirming sweep).

**Iteration 1 union of failures (3 tests, all failing deterministically in 8/8 rounds):**
1. `test_05_regrind_ledger.py::TestRegrindReversalRestoresPoolMass::test_reversal_returns_the_pool_to_its_pre_draw_balances`
2. `test_12_reference_entities.py::TestBagLotComputedCountBlock::test_a_new_lot_opens_with_every_bag_unpacked_and_untested`
3. `test_14_calculations.py::TestProvisionalSealVariantOnAppend::test_the_final_variant_stays_null_until_a_manager_finalizes`

**Tests deleted:** none (no test asserted a wholly PRD-silent rule).

**Fixes applied to `test_suite/` (STEP 2 — test mis-translated PRD; STEP 1c — partial coverage):**

- `test_suite/test_05_regrind_ledger.py` — `test_reversal_returns_the_pool_to_its_pre_draw_balances`: asserted `validate_success(..., 200)` on `POST /regrind-transactions/{id}/reverse`. PRD §4 verbatim: *"Operations that bring a new resource into existence — a product, a resin grade, … a pool, **a reversal**, a press, … — return `201 Created`."* The test's expected status contradicted PRD; corrected to `201`. (Implementation was right; the sibling test in the same class, which uses `get_success_data` without a status pin, already passed.)

- `test_suite/test_12_reference_entities.py` and `test_suite/test_14_calculations.py` — removed the single assertion `lot["seal_final_verdict"] is None` from each test (STEP 1b **DEFAULT-VALUE SILENCE** on an enum sentinel, resolved via STEP 1c partial-coverage split; all other assertions in both tests kept intact). PRD names `seal_final_verdict` in exactly three places, none of which states its value before finalization: it gives the fork values (*"`seal_final_verdict` is `PASS` when … otherwise `CONDITIONAL` … otherwise `FAIL`"*), says the fields *"are written"* at finalization, and reads it at release. Meanwhile the PRD's own convention for verdict/conformance enums is an explicit `PENDING` sentinel — *"`seal_provisional_mean_n` is null and `seal_provisional_verdict` reads `PENDING`"* and *"begins in `DRAFT` with `as_built_recycled_content_pct` and `claim_variance_pct` null and `claim_conformance` reading `PENDING`"* — so a faithful PRD-only reader can equally produce `null` or `"PENDING"` for the unwritten final verdict. Two divergent readings exist ⇒ not uniquely derivable. The adjacent numeric assertions (`seal_final_min_n`/`seal_final_mean_n` null) were retained, since PRD does establish numeric-null-before-computation verbatim elsewhere (e.g. *"Both `regrind_actual_pct` and `actual_recycled_content_pct` are null before completion."*).

**Fixes applied to `test_helpers/`:** none needed — no fixture, factory, or role-header helper constructed a precondition inconsistent with PRD.

**Fixes applied to `implementation/`:** none. No PRD-required check was removed or weakened; in all three cases the implementation was the PRD-faithful side (201 for a reversal per §4; `"PENDING"` a legitimate reading of the unwritten final verdict per the PRD's enum-sentinel convention).

## Step 8: Finalize PRD — 2026-09-01T07:40:00.000Z

Done. `workspace/PRD_FINALIZED.md` written with a single-sentence patch.

## Line counts
- `PRD.md`: 440 lines; `PRD_FINALIZED.md`: 440 lines — 0% line delta (one line revised in place, +1 sentence / ~48 words).

## Changes
- **§3.9 Converting: Seal Qualification, Case Packout and Release** — *insert* — appended to the final-seal-variant paragraph (line 279): before finalization writes them, `seal_final_min_n` and `seal_final_mean_n` are null and `seal_final_verdict` reads the sentinel `PENDING`, set at lot creation, and nothing other than finalization changes any of the three — `implementation/routes/converting.py:98-100` (creation) and `:202-204` (finalization).

## Per-edit pre-edit search log

**Edit 1 — subject: the lot's three "final seal" fields (`seal_final_verdict`, `seal_final_min_n`, `seal_final_mean_n`) and their pre-finalization values.**

(b) Impl paths enumerated (grepped `seal_` across all of `implementation/`, then read each hit):
- `routes/converting.py:78-112` — `POST /bag-lots` creation block: `seal_final_min_n`/`seal_final_mean_n` → `None`, `seal_final_verdict` → `"PENDING"` (also `seal_provisional_verdict` → `"PENDING"`).
- `routes/converting.py:127-172` — `POST /bag-lots/{id}/seal-tests`: appends the specimen, may flip `CONVERTING → TESTING`, calls only `calc.recompute_seal_provisional`; never touches any `seal_final_*` field.
- `services/calc.py:350-361` — `recompute_seal_provisional`: writes only the two *provisional* fields.
- `routes/converting.py:175-228` — `POST /bag-lots/{id}/finalize-tests`: the sole writer of all three final fields (`:202-204`), after the `ERR_INSUFFICIENT_SEAL_PANEL` and `ERR_NO_ELIGIBLE_REGRIND_POOL` guards, i.e. a refused finalization leaves them unwritten.
- `services/calc.py:374-392` — `final_seal_verdict`: pure computation, returns `(verdict, min_n, mean_n)`; writes nothing.
- `routes/converting.py:265-287` (`_issued_dossier_for_release`, used by lot release) — the only *reader* of `seal_final_verdict`, comparing `== "CONDITIONAL"`; a `"PENDING"` value simply does not match, so the release-gate prose stays true.
- `services/cascade.py:160-200` — dossier-revocation cascade (lot quarantine + packout unwind, plate nonconformance, line freeze): resets `packed_*`/`pallet_count`/`bag_count_unpacked` and `quarantine_reason` only; confirmed it does **not** reset any seal field, so the "nothing other than finalization ever changes them" clause holds.
- `routes/converting.py:231-262` (packout) and `routes/registry.py` list/read endpoints — no seal writes; bag-lot list filters are `print_job_id`/`product_id`/`status` only, so the sentinel is never a filter value.

(c) Wording adjustments: the sentence was first placed immediately after the paragraph's opening sentence, which left the following "It is computed over the **superseding panel**" with an ambiguous antecedent (the sentinel rather than the final variant); moved it to the end of the paragraph so no surrounding prose changed. Scoped the claim to "nothing other than finalization ever changes any of the three" only after confirming the revocation cascade and packout leave the seal block untouched; kept the provisional fields out of the sentence since PRD already pins `seal_provisional_verdict`'s `PENDING`.

**No PRD edit for Step 7 item 1** (`POST /regrind-transactions/{id}/reverse` status): impl returns `created(row)` → 201 (`implementation/routes/registry.py:334`), which PRD §4 already states verbatim ("a reversal … return `201 Created`"). That was a test bug, not a PRD silence, so the prose is left verbatim.

## Step 9: Complete PRD — 2026-09-01T07:58:00.000Z

Verified the file compiles as clean Markdown and all sections/tables are intact. Final state:

**Files**
- Source: `workspace/PRD_FINALIZED.md` — 440 lines, 86,237 chars
- Output: `workspace/PRD_COMPLETED.md` — 440 lines, 96,734 chars
- Char delta: **+10,497**; line delta: **0** (44 lines revised in place, no lines or sections added)

**Counts:** 44 changes total — **35 ambiguity-pins**, **9 mismatch-revisions**

**Changes**

- §2.3 Pagination — insert — ambiguity — pinned `has_more` as `offset + len(items) < total_count`, empty-string `limit`/`offset` treated as absent, and `(created_at, insertion-seq)` as the collection sort — `response.py:42`, `validation.py:142-157`, `store.py:93-94`
- §2.3 Pagination — insert — ambiguity — boolean filters matched case-insensitively against `true`/`false`, all others by exact string compare — `validation.py:165-168`
- §2.4 Common Properties — insert — ambiguity — `created_at`/`updated_at` come from real server time; only `recorded_at`, `issued_at`, `revoked_at` read the logical clock — `store.py:53-84`
- §2.4 Logical clock — insert — ambiguity — `current_utc` mandatory, may move the clock backwards, answered `200` with empty `data` object — `routes/registry.py:37-43`
- §2.6 OCC — revise — mismatch — *every* ledger row (not just draws and reversals) bumps pool `version`; the computed balance read refreshes aggregates without bumping it — `services/cascade.py:120-152`, `routes/registry.py:269-274`
- §2.7 Screening order — revise — mismatch — FK-resolution order includes `extrusion_run_id` between `line_id` and `pool_id`, and the listed sequence is exact — `validation.py:205-215`
- §2.8 Posture — revise — mismatch — `incapable_run_count` and `revoked_dossier_count` are monotonic *stored* counters (only cleared by clear-capability-flags), never recounted; only `active_hold_count` is recounted per derivation — `services/calc.py:446-459`
- §3.1 Products — insert — ambiguity — `product_code` <= 40 chars; `layflat_width_mm` and `bag_length_mm` must be positive — `routes/registry.py:51,57-58`
- §3.1 Resin library — insert — ambiguity — `melt_index`, `dart_impact_index`, `haze_index`, `cof_index`, `seal_initiation_temp_c` mandatory and otherwise unconstrained (any sign) — `routes/registry.py:138,143-146`
- §3.2 Recipe creation — insert — ambiguity — enumerated all 20 literal creation defaults, and that `regrind_cap_pct` is *not* seeded from the product and `clarity_index` is *not* seeded at 100 — `routes/blend.py:26-46,76`
- §3.2 Components — insert — ambiguity — `resin_grade_id` required for VIRGIN/ADDITIVE, silently nulled for REGRIND (never resolved, never 404s); DRAFT check precedes the layer check; append returns `201` with the whole recipe — `routes/blend.py:108-119,137`
- §3.3 Submit — insert — ambiguity — the six gates fire in §2.7 band order (food-contact resin first), not in narration order — `routes/blend.py:152,159`
- §3.3 Approve — insert — ambiguity — three checks in order predecessor-APPROVED → SoD → product match; approval leaves `food_contact_eligible` at its last recomputed value — `routes/blend.py:208,214,220`
- §3.3 Reopen — insert — ambiguity — a surviving pin refuses reopen with `ERR_RECIPE_STATE_INVALID` — `routes/blend.py:269`
- §3.4 Lines — insert — ambiguity — `max_gauge_micron`/`max_layflat_mm` are mandatory plain numbers with no positivity or min/max ordering constraint — `routes/extrusion.py:44-48`
- §3.4 Run creation — insert — ambiguity — enumerated all run creation defaults and null fields; `scheduled_start`/`scheduled_end` echoed verbatim — `routes/extrusion.py:177-206`
- §3.4 Reschedule — insert — ambiguity — both bounds mandatory, end-after-start is a shape violation, and the run excludes itself from its own occupancy comparison — `routes/extrusion.py:225-247`, `105`
- §3.5 Gauge readings — insert — ambiguity — `micron` must be positive and is otherwise unconstrained, `layflat_mm` defaults 0.0 and may be either sign; append returns `201` with the whole run — `routes/extrusion.py:284-311`
- §3.5 Closure inputs — revise — mismatch — an eligible pool is required **only** when `scrap_kg > 0`; both mass fields are non-negative rather than positive — `routes/extrusion.py:443`
- §3.5 Closure effects — revise — mismatch — the `EXTRUSION_SCRAP` row is booked only when `scrap_kg > 0`; content propagates to rolls *and* their bag lots — `routes/extrusion.py:459`, `services/cascade.py:99-116`
- §3.5 Wound rolls — revise — mismatch — a new roll's `actual_recycled_content_pct` is seeded from the run's current figure (non-null if the run already closed), and no run-status gate applies to recording a roll — `routes/extrusion.py:481-519` esp. `514`
- §3.6 Pools — insert — ambiguity — `polymer_family` restricted to the four recyclable families (`EVOH`/`TIE` rejected as invalid enum members); all opening aggregates zero — `config.py` `POOL_POLYMER_FAMILIES`, `routes/registry.py:234,244-251`
- §3.6 Balance read — insert — ambiguity — the computed read writes reconciled figures back but leaves `updated_at`/`version` untouched — `routes/registry.py:269-274`
- §3.6 Draws — insert — ambiguity — budget compared as `round(consumed + kg, 3)` against an unrounded budget, exact landing accepted; returns `201` with the ledger row — `routes/extrusion.py:397,414`
- §3.6 Roll scrap — insert — ambiguity — an explicit `pool_id` is used as given with no family/food-contact re-check; `pcr_kg` from the roll's own as-built content (0.000 while null); returns `200` with the roll; missing-pool checked only when `pool_id` omitted — `routes/extrusion.py:596,607`
- §3.6 Reversals — insert — ambiguity — reversal `pcr_kg` always 0.000; returns `201` with the reversal row; only `regrind_consumed_kg`/`regrind_actual_pct` are re-derived; refusal order already-reversed → not-reversible — `routes/registry.py:293-334`, `services/calc.py` `recompute_run_regrind`
- §3.7 Roll release — revise — mismatch — gate order is run-COMPLETED → line posture → gauge capability → layflat (PRD had posture last); deviation of exactly 5.0 passes — `routes/extrusion.py:546-556`
- §3.7 Plate sets — insert — ambiguity — `wear_limit_impressions` at least one (default 500000) — `routes/printing.py:43`
- §3.7 Plate wear — insert — ambiguity — both WORN triggers apply only while the plate is still `MOUNTED`; a non-mounted plate accrues counters without transitioning — `routes/printing.py:289-292`, `services/cascade.py:181-184`
- §3.8 Print jobs — insert — ambiguity — enumerated creation defaults, windows echoed verbatim, and no clock gate at creation (a wholly past window is accepted) — `routes/printing.py:138-159`
- §3.8 Registration — insert — ambiguity — `registration_drift_micron` mandatory with no sign/magnitude constraint — `routes/printing.py:195`
- §3.8 Color proof — insert — ambiguity — `delta_e_measured` mandatory, otherwise unconstrained — `routes/printing.py:216`
- §3.8 Setup exhaustion — insert — ambiguity — the measurement that tips the count past four is still stored and still moves its own dimension's state before the block lands — `routes/printing.py:182-188,203-207`
- §3.8 Job completion — revise — mismatch — the plate moves to `WORN` only if still `MOUNTED` when the impressions threshold is crossed — `routes/printing.py:289-292`
- §3.9 Lot creation — insert — ambiguity — `bag_count_scrapped` defaults 0, never negative, and is *not* checked against `bag_count_produced` — `routes/converting.py:55`
- §3.9 Count accuracy — insert — ambiguity — theoretical count is zero when the job has no `printed_kg` or unit weight rounds to zero, and `count_accuracy_conforming` reads false whenever the pct is null — `services/calc.py:409-417`
- §3.9 Seal tests — insert — ambiguity — `specimen_index` >= 1, `measured_n_per_15mm` >= 0; `attempt` counted across all `test_kind`s; append returns `201` with the whole lot; lot-state check precedes the converting-feature gates — `routes/converting.py:131-136,154-172`
- §3.9 Finalization — insert — ambiguity — the `LOT_SCRAP` row's `pcr_kg` formula (0.000 when as-built is null), and the pool check runs before any lot field is written — `routes/converting.py:193-227` esp. `219`
- §3.9 Packout — insert — ambiguity — `requested_bags` a strictly positive integer; check order version → status → quantity; every packout re-derives the count-accuracy block; the move to `PACKED` is unconditional even when zero bags are packed; returns `200` with the lot — `routes/converting.py:235-262`
- §3.9 Release — revise — mismatch — gate order is dossier-ISSUED → CONDITIONAL-conforming → food-contact → count accuracy (PRD listed count accuracy first), and one dossier must satisfy every applicable clause via set narrowing — `routes/converting.py:265-306`
- §3.9 Ship — insert — ambiguity — a `RELEASED` lot with zero packed cases is refused with `ERR_BAG_LOT_STATE_INVALID` — `routes/converting.py:320-323`
- §3.10 Dossier draft — insert — ambiguity — `food_contact_declared` mandatory (not defaulted); all issue/revoke stamps null at creation; returns `201` — `routes/converting.py:336,348-366`
- §3.10 Issue — insert — ambiguity — the first two preconditions both report `ERR_BAG_LOT_STATE_INVALID`, in the stated order — `routes/converting.py:386-399`
- §3.10 Revocation cascade — revise — mismatch — level four fires only if the plate is still `MOUNTED`; the traceable roll is quarantined when still `WOUND` independently of whether the line freezes — `services/cascade.py:181-194`
- §3.10 Clear flags — insert — ambiguity — no body, always writes the line (advancing `updated_at`/`version`) even when both counters were already zero, returns `200` with the line — `routes/extrusion.py:88-101`
