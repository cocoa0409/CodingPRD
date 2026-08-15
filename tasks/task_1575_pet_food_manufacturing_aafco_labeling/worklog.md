# Worklog — task_1575_pet_food_manufacturing_aafco_labeling

## Step 1: Create Task Directory — 2026-08-13T22:05:00.000Z

Task directory `tasks/task_1575_pet_food_manufacturing_aafco_labeling/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher; Step 1 treated as DONE per invocation instructions. User directive: **generate a task harder than expert level** — passed to scaffold-generator.

## Resume Assessment — 2026-08-13T22:40:00.000Z

Resumed killed run. Found: `SCAFFOLD.yaml` (87KB, valid YAML, §1.1–§1.7 complete: 15 entities, 7 state machines, 8 calculations, 16 validations, 75 endpoints, 30 errors, 9 roles) and `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (71KB, valid YAML, 9 rule groups, 0 stubs). `SCAFFOLD_CORNER_DESIGN.yaml` MISSING. `workspace/` empty (Steps 3–9 not started). Plan: Step 2 subagent regenerates ONLY SCAFFOLD_CORNER_DESIGN.yaml (§1.9) against existing SCAFFOLD.yaml; then Steps 3–9 run normally.

## Step 2: Generate Scaffold (resume — corner design only) — 2026-08-13T23:45:00.000Z

Confirmed: the same 5 (f) violations appear with an empty corner file — they are pre-existing SCAFFOLD.yaml gaps, untouched per the RESUME constraint. My corner design contributes zero lint violations.

## Summary

**Delivered**: `/home/ubuntu/github/CodingPRD/tasks/task_1575_pet_food_manufacturing_aafco_labeling/SCAFFOLD_CORNER_DESIGN.yaml` (4241 lines), single top-level key `scaffold_corner_design`, YAML-validated via `yaml.safe_load`.

**Instance counts per §1.9 section** (98 total: 71 full test-recipe instances + 27 `excluded_because:` stubs):

| Section | Instances | Full | Stubs |
|---|---|---|---|
| entities | 10 | 10 | 0 |
| state_machines | 28 | 22 | 6 |
| calculations | 10 | 4 | 6 |
| validations | 22 | 14 | 8 |
| endpoints | 4 | 4 | 0 |
| errors | 6 | 1 | 5 |
| rbac | 10 | 10 | 0 |
| cross_cutting_complexity_layers | 7 | 5 | 2 |
| consistency_model | 1 | 1 | 0 |

**Coverage highlights**: envelope shapes (object/array/error), pagination + `ERR_PAGINATION` bounds, required-field/enum/range sweeps, FK integrity and reverse-reachability GETs, initial/invalid/terminal transitions across all 7 state machines, hold-resume loop, withdraw and supersede cascades, registration happy-path + clock-driven expiry, GA spot-mean + deviation index (literals pre-computed: 25.0/3.0/MISBRANDED), fee schedule tiers (7500/5000/12000), brand complaint rollup with decay window (46.0 → 42.33 → 35.0), lot-code sequencing, both OCC rules, version-pinning on substantiation, per-role RBAC denial sweep (9 denials) plus user-scoped SoD, and immediate-consistency checks. Stubs cite only verified §1.8 instance names (no dangling refs, no name collisions across the two design files).

**Sections stubbed and why**: stubs exist only where §1.8 already exercises the exact corner (both dual-variant calcs, the pinned rounding order, threshold boundaries, both cascades, both priority-pair conflicts, the fork, the cyclic machine, the compensating invariant) — per the skill's stub rule. No section was skipped as non-applicable.

**Notable findings** (scaffold-level, left unmodified per the do-not-touch constraint):
1. `scaffold_lint.py` reports 5 pre-existing check-(f) `FK_REVERSE_UNREACHABLE` violations in SCAFFOLD.yaml (Ingredient←SupplierIngredientApproval, BrandOwner←Formula, Formula←Formula.parent_formula_id, Ingredient←FormulaIngredient, ProductionBatch←ComplaintCase.batch_id). Proven independent of §1.9: identical result with an empty corner file. All 943 §1.8+§1.9 calls pass lint checks (a)–(e) — my file adds zero violations.
2. Three error codes are unreachable via the declared §1.5 surface, so no corner instance could trigger them (noted, not stubbed): `ERR_INGREDIENT_INACTIVE` (no endpoint retires an Ingredient), `ERR_COMPLAINT_SCORE_HOLD` (auto-escalation at 60.0 caps rollable TRIAGED/INVESTIGATING scores at 57.0, so the 70.0 hold threshold can never be reached), and `ERR_TRIAL_COMPLETION_LOW` (record-verdict declares no override input field).

Orchestrator verification: file parses as YAML; top-level key `scaffold_corner_design`; 9 sections, 98 instances. All three scaffold artifacts now present.

## Step 3: Copy Shared Files — 2026-08-13T23:46:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1575_pet_food_manufacturing_aafco_labeling/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-14T00:05:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1575_pet_food_manufacturing_aafco_labeling/workspace/PRD.md` (330 lines).

**Section list**
- §1 Introduction (3 paragraphs, co-manufacturer compliance framing)
- §2 Global Specifications: 2.1 RBAC (9 roles, identity prose per role, `RegulatoryAffairs` entity-backed to `BrandOwner`), 2.2 API Response Structure (byte-identical to the fixed verbatim block — verified programmatically), 2.3 Pagination, 2.4 Common Resource Properties, 2.5 Logical Clock, 2.6 Precision/Units/Rounding, 2.7 OCC, 2.8 Hierarchical Consistency & Cascades, 2.9 Nested Resource Retrieval, 2.10 Validation Order & Error Precedence
- §3 Business Logic (8 subsections): 3.1 Master Data, 3.2 Supplier–Ingredient Qualification & SoD, 3.3 Formula Development & Substantiation (ME/Atwater + AAFCO floors fully in prose), 3.4 Feeding Trials, 3.5 Production & Lot Coding, 3.6 Lab Sampling & GA Compliance (pinned rounding order + deviation index + yield-override governance), 3.7 State Registration & Fees, 3.8 Complaints & Recalls
- §4 Endpoint Definitions (75-row, 4-column table), §5 Error Code Catalogue (30-row, 2-column table)

**Zero-Silence Rule coverage audit — all PASS**
- Contract 1 (field names): 87/87 entity fields, 69/69 endpoint input identifiers (incl. `tonnage_tier`, `enrolled_delta`, `confirm_adverse_event_flag`, `override`, `lot_fields`, `to_iso8601`), query params (`limit`, `offset`, `status`, `approval_state`), and path params (`id`, `formula_id`) all present in backticks — 96/96 required identifiers, 0 missing (mechanically verified against parsed SCAFFOLD.yaml)
- Contract 2 (rules): all 16 validations expressed with priority ordering (global order in §2.10 plus per-endpoint sequences in §3); both OCC rules with `expected_formula_version` + `ERR_STALE_FORMULA_VERSION`/412; all 7 state machines' transitions with preconditions, side effects, and cascades; all 8 calculations in reconstruction-safe prose (no pseudocode, no fuzzy words — 0 hits for approximately/about/roughly/etc., 0 leaked operators); all 30 error IDs surfaced in §2/§3; all endpoint `applies_to` scopes and side effects enumerated; sibling branches (PASSED/FAILED, provisional/final, overrun/underrun, formulation/lab variants) at equal density
- Contract 3 (§3 path purity): 493 backticked tokens scanned, 0 path/method/combo violations

The two forbidden index files were not opened; no sibling tasks were read.

## Step 5: Generate Unit Tests — 2026-08-14T00:35:00.000Z

Generation complete. Summary:

## Test counts per source queue

**Queue A — Difficulty (SCAFFOLD_DIFFICULTY_DESIGN.yaml):** 17 of 18 instances translated, 34 test functions (exactly 2 per translated instance), across `test_20`–`test_28`.

**Queue B — Corner (SCAFFOLD_CORNER_DESIGN.yaml):** 69 of 71 non-stub instances translated, 77 test functions (some instances get 2–3 tests), across `test_01`–`test_13`. All 27 `excluded_because:` stubs were left untranslated; every stub's `difficulty_instance` pointer was verified to resolve to a real §1.8 instance name.

**Total: 111 test functions (113 collected by pytest after parametrize expansion).**

## Instances skipped (PRD-first filter failures)

1. **`Difficulty/combinatorial_formula/aafco_profile_check_energy_normalization_branch`** — the instance's pinned literals contradict what the PRD uniquely derives. The PRD's modified-Atwater formula (§3.3) yields ME 4194.5 for protein 27 / fat 18 / fiber 1 / moisture 8, not the instance's 4347.4; and because `calcium_min_pct`/`phosphorus_min_pct` default to 0 (PRD §3.3) while calcium/phosphorus are gated against AAFCO floors, both profiles in the instance would compute DEFICIENT — the instance asserts the second is COMPLIANT. Skipped, not weakened.

2. **`Corner/entities/numeric_and_parameter_bounds_fail`** — asserts `ERR_INVALID_REQUEST` (400) for out-of-range numeric values (inclusion_pct 0.0, animal_count 7, duration_days 20), but PRD §2.10 assigns `ERR_INVALID_REQUEST` verbatim only to "a missing required field, a wrong-typed value, or an enum value outside its declared set"; range violations have no PRD-named error_id, so the asserted outcome is not uniquely derivable.

3. **`Corner/calculations/lot_code_sequencer_chronological`** — asserts exact lot_code strings (`20260825-LINE-L1-001`), but PRD §3.5 specifies only "an eight-digit calendar stamp, followed by the line_id, followed by a sequence number" without pinning separators; the exact-string assertion is not uniquely derivable.

Partial adjudication: `Corner/entities/brand_owner_listing_paginates_and_filters` — the pagination assertions (limit/offset/total_count/has_more, §2.3) were emitted; the `status=SUSPENDED` filter sub-assertion was dropped because the PRD says only "several list endpoints" accept `status` without naming brand-owners.

Setup-chain repair (not a skip): several difficulty-instance recipes post nutrient profiles omitting `calcium_min_pct`/`phosphorus_min_pct`, which default to 0 and would render the profile DEFICIENT, breaking their own substantiation chains (the corner index's shared-chain header itself specifies Ca 1.0 / P 0.8). Those setups add the two fields; the asserted rules are unchanged.

## test_helpers file list

All under `test_helpers/`: `__init__.py` (barrel: framework generics + PRD-specific), `types.py` (15 entity TypedDicts, all carrying §2.4 common fields; 24 status/role enums), `api_client.py` (`ApiClient(GenericApiClient)`, one method per each of the 32 PRD endpoints), `api_errors.py` (all 30 error IDs + HTTP map registered via `set_error_http_status_map`), `assertions.py` (per-entity structural assertions), `factories.py` (payload factories with unique-value generators), `constants.py` (AAFCO floors, Atwater constants, weights, thresholds, fee schedule), `test_users.py` (9 role headers + `make_regulatory_affairs_headers` for the entity-backed RegulatoryAffairs role + SoD builders), `fixtures.py` (tiered composites: draft/nutrient-review/substantiated/locked formula chains, OCC-aware batch creation, batch/trial/registration state walkers, complaint and recall helpers).

## Verification performed

- Every emitted test's docstring ends with exactly one `Design:` line resolving to a real, non-stub instance (automated audit: 0 errors; all 17 covered difficulty instances have ≥2 tests; all 69 covered corner instances have ≥1).
- All 184 quoted PRD citation passages survive whitespace-normalized verbatim matching against `PRD.md` (4 initial failures fixed).
- `python -m py_compile` clean on all 25 files; `pytest --collect-only` collects 113 tests with no import errors.

No sibling task directories were read; generation used only this task's four inputs plus the skill spec and the installed framework's public API.

## Step 6: Generate Implementation — 2026-08-14T00:22:00.000Z

All checks pass. Here is the summary.

## Summary

Complete Python + Flask implementation generated at `workspace/implementation/`.

### File list and line counts (2,861 total lines)

| File | Lines |
|---|---|
| `start.sh` | 8 |
| `requirements.txt` | 1 |
| `app.py` | 62 |
| `db.py` | 80 |
| `errors.py` | 164 |
| `response.py` | 54 |
| `middleware.py` | 144 |
| `services/calculations.py` | 335 |
| `routes/clock.py` | 47 |
| `routes/brand_owners.py` | 80 |
| `routes/suppliers.py` | 104 |
| `routes/ingredients.py` | 73 |
| `routes/supplier_ingredient_approvals.py` | 155 |
| `routes/formulas.py` | 283 |
| `routes/nutrient_profiles.py` | 85 |
| `routes/feeding_trials.py` | 185 |
| `routes/production_batches.py` | 277 |
| `routes/lots.py` | 35 |
| `routes/lab_ga.py` | 110 |
| `routes/state_registrations.py` | 179 |
| `routes/complaint_cases.py` | 173 |
| `routes/recall_actions.py` | 227 |

### Endpoint coverage: 75 / 75
The scaffold declares 75 endpoint entries (`- method:` rows in §1.5); the Flask app registers exactly 75 API endpoint methods (76 URL rules minus Flask's built-in `/static` route). Full coverage across all 15 resources plus the logical clock.

### Key implementation points
- **Storage**: purely in-memory dicts in `db.py`, instantiated fresh per process; verified that a fresh boot returns `total_count: 0` after a previous boot created data. No seeding anywhere.
- **Logical clock**: defaults to `2026-08-01T00:00:00Z`, advanced only via `POST /petfood/_clock/set_current_utc`, triggers the APPROVED→EXPIRED registration sweep (annual expiry = one calendar year after `decided_at`).
- **Calculations** (all `Decimal` + `ROUND_HALF_UP`): modified-Atwater ME with the halved 0.44 fiber coefficient for LAB_ANALYSIS; AAFCO check with growth-floor grouping for GROWTH/GESTATION_LACTATION/ALL_LIFE_STAGES and >4000 kcal/kg normalization; GA composite with the pinned round-3-then-sum-then-divide-then-round-2 order (verified the load-bearing example: 38.236/22.379/22.345 → 27.24); deviation index; yield variance with strict >5.00 threshold; tiered registration fees; complaint risk scoring with provisional/final variants and the 90-day/30-day brand rollup windows; lot-code sequencer.
- **Validation precedence**: auth → RBAC → existence → state (with `ERR_ALREADY_TERMINAL` for truly terminal states) → ordered business guards per PRD §2.10 (SoD before supplier-approval; ingredient-active before inclusion-sum; sourcing before adequacy gate; recall→ingredient→sourcing→line-conflict on release).
- **OCC**: `expected_formula_version` enforced (HTTP 412) on batch creation and registration approval.
- **Cascades**: formula supersede/withdraw, pairing revoke → formula DRAFT rollback, batch reject → lot quarantine, recall initiate/terminate with compensation, all with per-resource `version`/`updated_at` bumps.

### Boot confirmation
`bash start.sh` boots cleanly (guarded `pip install`, `exec python3 app.py`, binds `0.0.0.0:$PORT`). Smoke-tested end-to-end: auth rejection (401), brand owner creation (201), clock set, full supplier→pairing→formula→substantiate→lock→batch→release→start→complete→lot→sample→GA-report→registration→approve workflow, complaint auto-escalation at score ≥60 (85 → ESCALATED_RECALL), recall cascade (batch→RECALLED, lots→RECALLED, `open_recall_flag`/`open_recall_count` rollups), effectiveness flow with range validation, and close rollups. All returned expected statuses and error IDs.

## Step 7: Run Tests and Iterate — 2026-08-14T00:55:00.000Z

Clean 8-round parallel sweep achieved: **113/113 passed in every round, 0 failures in the union**.

## Summary

**Iterations run:** 3 sweeps (24 round-executions total).

**Tests deleted:** None. Every failing assertion traced to verbatim PRD prose; no test required deletion.

**Fixes applied to `test_helpers/`:**
- `factories.py` — `state_registration_payload`: default `tonnage_tier` changed from `"T1"` to `3.0`. PRD §3.7 defines the field as "declaring the brand's prior-year tonnage in that state" with boundaries in tons ("below 5 tons pays the base fee; 5 tons up to but not including 50 tons pays one and a half times the base; 50 tons or more pays double"); the T1/T2/T3 label names appear nowhere in PRD.md, so a PRD-only implementer cannot accept them (ENUM-MEMBERSHIP-ONLY collapse in the payload, fixed per partial-coverage rule 1c — the fee assertions themselves are PRD-verbatim and were preserved).
- `fixtures.py` — `setup_registration`: `tonnage_tier` parameter default `"T1"` → `3.0`, same reason.

**Fixes applied to `test_suite/`:**
- `test_06_registration_lifecycle.py`, `test_10_calculation_results.py`, `test_12_endpoints_and_rbac.py`, `test_13_occ_versioning_cascades.py`, `test_27_difficulty_temporal.py` — replaced string tier labels with numeric tonnage at the same PRD boundaries (`"T1"`→`3.0` keeps base-fee assertions 7500/5000/6000; `"T2"`→`20.0` keeps NY 1.5×=12000; `"T3"`→`60.0` keeps TX 2.0×=12000). Assertions unchanged; only the payloads made PRD-faithful.
- `test_13_occ_versioning_cascades.py::test_substantiation_pins_locked_profile_version` — the test compared the pin against the stale profile-creation snapshot (version 1). PRD §3.3 states ME "is recomputed as part of the transition" at submission and §2.4 increments version on "recomputation of derived fields", so the profile's current version at substantiation is 2. Fixed the test to re-read the profile via the list endpoint and pin against its current version.
- `test_11_validation_gates.py` — added missing `get_registration` import (NameError masked earlier by the tonnage setup failure).
- `test_26_difficulty_cross_entity.py` — added missing `setup_locked_formula` import.

**Fixes applied to `implementation/`:**
- `routes/clock.py` — `set_current_utc` now re-evaluates every brand owner's `complaint_score` after advancing the logical clock (new `_recompute_windowed_scores`, persisting + touching the brand only when the score changes). PRD §2.5 requires that "every windowed calculation in the complaint risk model — the trailing 90-day rollup window and the 30-day post-closure decay — evaluates its window against the logical clock's current reading"; previously the stored score went stale across clock advances (returned 42.33 instead of 35.0 after a 31-day advance expired the decay share).

## Step 8: Finalize PRD — 2026-08-14T01:05:00.000Z

Done. `PRD_FINALIZED.md` is written with exactly three inline edits, all traced to `<step_7_diff>` items.

## Line counts
- `PRD.md`: 330 lines; `PRD_FINALIZED.md`: 330 lines — 0% delta (3 lines revised in place, no insertions/deletions of lines).

## Changes
- **§2.5** — revise — Appended a sentence pinning that advancing the logical clock re-evaluates every brand owner's `complaint_score` against the new reading, persisting it (refreshing `updated_at`, incrementing `version`) only when the value changes — `implementation/routes/clock.py:22-37` (`_recompute_windowed_scores`), `implementation/services/calculations.py:293-301` (`touch`).
- **§3.7** — revise — `tonnage_tier` now pinned as "a number declaring the brand's prior-year tonnage in that state, expressed in tons" (was: an unqualified "tonnage tier" whose representation — numeric tons vs. tier label — PRD left open) — `implementation/routes/state_registrations.py:36` and `:169` (`require_number`), `implementation/services/calculations.py:182-193` (numeric compare vs 5/50 tons), `implementation/middleware.py:84-88`.
- **§4 endpoint table** — revise — Clock row description extended to "triggers the registration expiry sweep and re-evaluates complaint risk scores" — `implementation/routes/clock.py:23-24`.

## Items deliberately not patched
- `test_13` substantiation-pin fix: pure test bug. PRD already determines version=2 — §3.3 ("metabolizable energy is recomputed as part of the transition") + §2.4 (version increments on "recomputation of derived fields"); impl (`routes/formulas.py:183-190`) always touches the profile on submission.
- `test_11` / `test_26` missing imports: pure test bugs, no behavioral content.
- The five payload swaps (`"T1"`→`3.0` etc.) share the same root silence as the factories fix — covered by the single §3.7 edit.

## Per-edit pre-edit search log

**Edit 1 (§2.5 clock recompute)**
- (a) Subject: `complaint_score` persistence/recompute triggers and brand-record mutation semantics.
- (b) Paths enumerated: `routes/clock.py:14-37` (advance → expiry sweep → score recompute, touch only on change); `routes/complaint_cases.py:70-74` + callsites `:120` (triage), `:145` (resolve), `:172` (close-no-action) — score persisted **without** `touch`; `routes/state_registrations.py:131-134` (approval gate reads the *stored* score, threshold 70.0); `routes/brand_owners.py:36,43-50` (init 0; GET returns stored value); `services/calculations.py:220-252` (window/decay math keyed on `store.now()`); test evidence `test_10_calculation_results.py:167-173` (31-day advance → 42.33 becomes 35.0).
- (c) Wording scoped strictly to clock advancement ("Advancing the clock … also re-evaluates") so it does not imply complaint-activity recomputes touch brand `version`/`updated_at` (they do not — no `touch` at `complaint_cases.py:74`); the "unchanged score leaves the brand untouched" clause mirrors the inequality guard at `clock.py:35`; no ordering claim between the expiry sweep and the score recompute; no claim of recompute-on-read anywhere (approval gate reads the stored value — consistent).

**Edit 2 (§3.7 tonnage_tier numeric)**
- (a) Subject: `tonnage_tier` request-field type/semantics on registration create and resubmit.
- (b) Paths enumerated: `routes/state_registrations.py:36,42,53` (create), `:169,175-176` (resubmit — same field, same type); `services/calculations.py:182-193` (fee tiers compare the numeric value directly against 5/50, multipliers 1/1.5/2.0); `middleware.py:84-88` (`require_number` rejects booleans and non-numbers); test payloads at `test_helpers/factories.py:134`, `fixtures.py:346`, `test_06/10/12/13/27` using 3.0/20.0/60.0.
- (c) Chose "a number … expressed in tons": deliberately no non-negativity claim (impl accepts negatives, yielding base fee), no integer-only claim (impl and tests use floats), no response-shape claim (impl stores `_tonnage_tier` privately, never serialized — left under-determined rather than asserted). The fee paragraph's "scaled by the declared tonnage tier" was left verbatim; it reads consistently once the field is numeric.

**Edit 3 (§4 clock table row)**
- (a) Subject: clock endpoint's triggered behavior as summarized in the endpoint table.
- (b) Paths enumerated: `routes/clock.py:14-25` (both sweeps run on every set); grep confirmed no other endpoint invokes `compute_brand_complaint_score` or the expiry sweep; consistency with the just-edited §2.5 narrative.
- (c) No adjustment needed — the added clause asserts only what `clock.py:23-24` does and what §2.5 now states normatively.

## Step 9: Complete PRD — 2026-08-14T01:35:00.000Z

All edits applied and verified. Final summary:

## Summary

**Produced:** `workspace/PRD_COMPLETED.md`

**Size:** `PRD_FINALIZED.md` 330 lines / 61,076 chars → `PRD_COMPLETED.md` 330 lines / 66,025 chars (delta +4,949 chars; all changes are in-paragraph inserts/revisions — no new sections, line count unchanged, 24 paragraphs patched).

**Counts:** 15 ambiguity-pins, 9 mismatch-revisions.

### Changes (one per patch)

**Mismatch revisions (9):**
- §2.4 — revise — mismatch — `version`/`updated_at` no longer claimed to advance on *every* derived-field recomputation; carve-out for upward rollups (`approved_ingredient_count`, `total_batch_count`, `open_recall_flag`, `open_recall_count`, `complaint_score`) which update in place without touching the parent's `version`/`updated_at` (exceptions: batch creation, clock-driven score refresh) — `services/calculations.py:293-301` (touch) vs. non-touching rollups at `routes/suppliers.py:98-104`, `routes/production_batches.py:219-221`, `routes/complaint_cases.py:70-74`, `routes/recall_actions.py:97-101,118-136`.
- §2.5 — revise — mismatch — "annual, state-specific expiry date" → uniform rule: expiry = exactly one calendar year after approval `decided_at`, sweep on every clock advance expires when now ≥ expiry, Feb 29 → Feb 28 — `routes/clock.py:40-60`.
- §3.1 — revise — mismatch — `open_recall_count` now counts recalls whose status is anything other than `CLOSED` **or `TERMINATED`** — `routes/recall_actions.py:131-136`.
- §3.1 — revise — mismatch — `country_code` no longer asserted to be ISO-3166 alpha-2; stored as supplied, format not validated — `routes/suppliers.py:23`.
- §3.3 — revise — mismatch — profile listing "array of zero or one entries" → latest-per-basis array of zero/one/two entries; replaced profile discarded outright; "the" profile for gates/calculations = most recently posted across bases — `routes/nutrient_profiles.py:59-85`, `routes/formulas.py:149-155`.
- §3.5 — revise — mismatch — best-by check compares against the batch's full `scheduled_start` instant (not calendar date); also pinned exact lot-code format `YYYYMMDD-{line_id}-{seq:03d}` and count-based sequencing under a frozen clock (replacing the false "ties impossible" rationale) — `routes/production_batches.py:263-265`, `services/calculations.py:258-274`.
- §3.6 — revise — mismatch — lab-sample listing ordered by sampling position (FIRST/MIDDLE/LAST/COMPOSITE, ties by `created_at` then `id`), an explicit exception to §2.3's default — `routes/lab_ga.py:62-63`.
- §3.8 — revise — mismatch — empty `scope_batch_ids` scopes every batch not already `REJECTED`/`RECALLED` (COMPLETED remains recallable), not "non-terminal" per §3.5 — `routes/recall_actions.py:54-61`.
- §3.8 — revise — mismatch — recall terminal states are `CLOSED` and `TERMINATED` (COMPLETED still accepts close); "unclosed" → open = status other than CLOSED/TERMINATED — `routes/recall_actions.py:17`.

**Ambiguity pins (15):**
- §2.1 — insert — ambiguity — RegulatoryAffairs ownership comparison is definitional only; no endpoint enforces an ownership rejection — absent from all of `routes/`.
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` → `ERR_PAGINATION`; `created_at` ties broken by `id` ascending; `total_count` is post-filter; `has_more` ⟺ `offset+limit < total_count` — `middleware.py:116-137`, `response.py:23`.
- §2.8 — insert — ambiguity — rollups write only the derived field on the parent (see §2.4 carve-out) — `routes/recall_actions.py:97-101`.
- §3.2 — insert — ambiguity — `coa_document_ref` optional when `requires_coa` is false — `routes/supplier_ingredient_approvals.py:30-35`.
- §3.3 — insert — ambiguity — submitting a formula with no ingredient lines → `ERR_INVALID_STATE` (409) — `routes/formulas.py:167-168`.
- §3.3 — insert — ambiguity — submission-time ME recomputation refreshes the profile's `updated_at` and advances its `version` — `routes/formulas.py:184-190`.
- §3.3 — insert — ambiguity — substantiation uses the current (most recently posted) profile; with several PASSED protocols the most recently created supplies the pinned version — `routes/formulas.py:229-242`.
- §3.4 — insert — ambiguity — protocol creation gated only on basis (not formula state); adult-maintenance minimum violations → `ERR_INVALID_REQUEST` (400) — `routes/feeding_trials.py:24-36`.
- §3.4 — insert — ambiguity — open-enrollment failures: basis → `ERR_PROFILE_BASIS_MISMATCH`, formula state → `ERR_INVALID_STATE`; `enrolled_delta` is any integer, no sign check — `routes/feeding_trials.py:96-115`.
- §3.4 — insert — ambiguity — explicit-pass request expressed via optional `requested_verdict` field; all other payloads route purely on ratio — `routes/feeding_trials.py:163-171`.
- §3.5 — insert — ambiguity — batch create against non-LOCKED formula → `ERR_INVALID_STATE`; new batch has `yield_variance_pct` null until completion — `routes/production_batches.py:43-44,55`.
- §3.5 — insert — ambiguity — release re-checks formula still LOCKED (`ERR_INVALID_STATE`) before the four gates — `routes/production_batches.py:112-113`.
- §3.5 — insert — ambiguity — `lot_fields` carries `packaged_units`/`best_by_date`; completion is applied before `lot_fields` validation, so a lot error leaves the batch COMPLETED; lot cutting not gated on batch status — `routes/production_batches.py:214-228`, `routes/lots.py:15-21`.
- §3.6 — insert — ambiguity — samples/GA reports not gated on batch status; verdict stays `PENDING` when the formula has no profile; label guarantees read from the most recently posted profile; no-profile report → deviation 0.00 / COMPLIANT — `routes/lab_ga.py:29-53,82-86`, `services/calculations.py:104-107`.
- §3.7 — insert — ambiguity — resubmission leaves `submitted_at` and `decided_at` unchanged — `routes/state_registrations.py:160-179`.
- §3.8 — insert — ambiguity — triage `confirm_adverse_event_flag` optional, overwrites (may clear) the flag; complaint-score windows keyed on each case's last status-change timestamp, lower bound inclusive; recall scope ids must resolve (404) and belong to the formula (400) — `routes/complaint_cases.py:108-110`, `services/calculations.py:239-249`, `routes/recall_actions.py:42-53`.

**Notable verification:** all 60+ endpoint role assignments in the §4 table match impl exactly; all calculation constants/formulas (Atwater ME, AAFCO floors + energy normalization, GA pinned rounding order, deviation index, yield variance, fee schedule, complaint weights, escalation 60.0 / hold 70.0 thresholds) match `services/calculations.py`; guard orderings in §2.10 match impl evaluation order.
