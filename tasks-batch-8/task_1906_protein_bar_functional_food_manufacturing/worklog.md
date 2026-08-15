# Worklog — task_1906_protein_bar_functional_food_manufacturing

## Step 1: Create Task Directory — 2026-08-14T23:57:00.000Z

Directory `tasks/task_1906_protein_bar_functional_food_manufacturing/` and `workspace/` pre-created by the pipeline launcher (Step 1 completed externally; orchestrator verified existence).

## Step 2: Generate Scaffold — 2026-08-15T00:37:00.000Z

All checks pass. The scaffold for task 1906 is complete and lint-clean.

**Files written**
- `/home/ubuntu/github/CodingPRD/tasks/task_1906_protein_bar_functional_food_manufacturing/SCAFFOLD.yaml` (§1.0–§1.7 only)
- `/home/ubuntu/github/CodingPRD/tasks/task_1906_protein_bar_functional_food_manufacturing/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1906_protein_bar_functional_food_manufacturing/SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

**Counts**
- Entities: 16 (Supplier, Ingredient, IngredientLot, BrandCustomer, ManufacturingAgreement, Formula, FormulaRevision, ProductionLine, LineSlot, ProductionRun, ChangeoverEvent, ShelfLifeStudy, ShelfLifePull, LotRelease, RetainSample, ClaimReview)
- State machines: 9, plus 2 §1.2.1 OCC concurrency rules (`run-create-stale-agreement`, `schedule-slot-stale-line`)
- Calculations: 10 (protein substantiation LABEL/COMPOSITE, sweetener blend PROVISIONAL/FINAL, MARGINAL/AVERAGE tiered pricing, allergen changeover matrix, per-slab-floor cut plan, hardness projection, yield variance, quarter rollup, line day availability, claim substantiation gate)
- Validations: 38 ordered priorities; Error codes: 50; Endpoints: 77; Roles: 6 (PlantAdmin, FormulationScientist, QualityManager, ProductionPlanner, LabTechnician, entity-backed BrandCustomerRep)
- §1.8: 19 instances — 3 dual-variant (nutrition/commercial/ingredient domains), 2 combinatorial (mode a: changeover matrix; mode b: cut-plan rounding order), 2 non-linear machines (revision reject cycle; run parallel status×release axes), 2 cascades (lot-reject depth-3 de-schedule; approve→supersede→cancel depth-3), 2 priority conflicts (existence/state, safety/fiscal), 2 boundaries (inclusive MOQ, strict hardness threshold), 2 cross-entity gates (changeover-validated, retain-required), 2 overlap semantics (half-open slot + allergen buffer vs closed-interval chamber capacity), 2 compensating invariants (lot kg conservation; line 1440-minute restoration)
- §1.9: 47 instances (39 active + 8 `excluded_because` stubs) across all 9 claim-extraction sections
- `scaffold_lint.py` verdict: **clean lint** — 1047 §1.8/§1.9 calls all conform to §1.5; all FKs reverse-reachable.

**Notable design decisions**
- Dual-substantiation model: label (nominal) vs composite (reserved-lot CoA) protein — verified arithmetic pinned in asserts (24.31 vs 23.31→23.35 g), composite gate can fail after label passes (ERR_COMPOSITE_CLAIM_UNSUBSTANTIATED).
- Allergen changeover matrix is a 3-input combinatorial (carryover set, high-risk membership, wet-clean staleness in minutes) driving both validation level and slot buffer minutes (0/30/60/90).
- Segregation of duties enforced by `X-User-ID` comparison on swab/validate and record-qc/decide pairs (ERR_SOD_VIOLATION).
- Logical clock endpoint with mandatory default 2026-08-01T00:00:00Z drives shelf-life auto-COMPLETE and pull MISSED transitions deterministically.
- Priority ordering pinned terminal-lockdown (p8) above generic state (p9) so both errors are observable; retain gate (p16) deliberately precedes QC gate (p36) and the §1.9 gate-sequence instance asserts that exact order.
- Every formula-derived assert was executed and pinned as a literal (e.g., projection 152.86 == limit passes; cut plan 130 per-slab-floor vs 133 aggregate-first).

## Step 3: Copy Shared Files — 2026-08-15T00:37:30.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1906_protein_bar_functional_food_manufacturing/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-15T00:52:00.000Z

All audits pass. The PRD is complete and verified. Final summary:

## Generated PRD

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1906_protein_bar_functional_food_manufacturing/workspace/PRD.md` — 376 lines

### PRD section list
- **§1. Introduction** (2 paragraphs, business-context angle; `/mfg` mount declared here)
- **§2. Global Specifications & System-Wide Principles**
  - 2.1 User and Role-Based Access Control
  - 2.2 API Response Structure (emitted byte-verbatim from `section-2.2-response-structure.md`; verified identical)
  - 2.3 Pagination
  - 2.4 Resource Identity, Versioning, and the Plant Logical Clock
  - 2.5 Optimistic Concurrency Control
  - 2.6 Validation Cascade and Error Ordering
  - 2.7 Allergen Governance and Segregation of Duties
  - 2.8 Inventory Mass Conservation
  - 2.9 Numerical Precision and Rounding
  - 2.10 Nested Resource Resolution and Cross-Entity Consistency
- **§3. Business Logic & Workflows** (9 subsections): 3.1 Supplier Qualification & Ingredient Registry · 3.2 Lot Intake & Disposition · 3.3 Brand Customers & Agreements · 3.4 Formulas & Revision Pipeline · 3.5 Claim Review & Label Substantiation · 3.6 Run Planning & Line Scheduling · 3.7 Allergen Changeover Control · 3.8 Run Execution, Completion & Lot Disposition · 3.9 Shelf-Life Studies & Texture Projection
- **§4. Endpoint Definitions** (77-row table, 4 columns)
- **§5. Error Code Catalogue** (50-row table, 2 columns)

### Scaffold → PRD mapping
- **§1.1 entities** (16) → §2.4 (common properties) + field/state narratives in §3.1–3.9; every field name backticked
- **§1.2 state_machines** (11) → Supplier §3.1; IngredientLot + CASCADE-REJECT §3.2; Agreement §3.3; FormulaRevision + CASCADE-SUPERSEDE §3.4; ClaimReview §3.5; ProductionRun dual-axis + LineSlot §3.6/3.8; ChangeoverEvent §3.7; LotRelease §3.8; ShelfLifeStudy/ShelfLifePull §3.9
- **§1.3 calculations** (10) → protein substantiation LABEL/COMPOSITE §3.4/3.8; sweetener PROVISIONAL/FINAL §3.6/3.8; tiered pricing §3.3; changeover matrix §3.7; cut plan §3.8; hardness projection §3.9; yield variance §3.8; quarter rollup §3.3; day availability §3.6; claim gate §3.5
- **§1.4 validations** (38, priority-ordered) → cascade stages 1–9 in §2.6; business-rule evaluation orders stated per endpoint in §3 (run-create 10→24→25→26→37→38; schedule 19→20→21→38; verify-pre-run 12→13→34; decide 15→16→35→36; submit 28→29; lot receipt 27→31; claim approve 9→11→18)
- **§1.0 response_envelope** → §2.2 (verbatim) + §2.3 (limit 10/1/100, offset 0, created_at ascending, meta fields)
- **§1.5 endpoints** (77) → §4 table; side effects narrated in §3
- **§1.6 errors** (50) → trigger prose in §2/§3, identifier table in §5
- **§1.7 roles** (6) → §2.1, with identity prose: five opaque roles plus `BrandCustomerRep` entity-backed to `BrandCustomer`, incl. the full 12-endpoint customer-scope enumeration

### Zero-Silence Rule self-audit (scaffold §1.1–§1.7 coverage)
- **Contract 1 (Field-Name Coverage): PASS** — pass 1 found 2 missing (`formula_id`, `study_id`), repaired in place; pass 2: 119 required / 119 present / 0 missing
- **Contract 2 (Rule Coverage): PASS** — all 38 validations with explicit priority ordering in prose; both OCC rules (`expected_agreement_version`, `expected_line_version` → `ERR_STALE_VERSION` 412, capability + field + error + status named, no race framing); all 11 state machines' transitions expressed with from/to, preconditions paired to error IDs, and every side effect (incl. CASCADE-REJECT depth-3 and CASCADE-SUPERSEDE depth-2 with all links and version bumps); all 10 calculations as precise prose passing the reconstruction test (pinned rounding orders, strict/inclusive boundaries, variant differences); all 50 error IDs matchable to trigger conditions in §2/§3; all endpoint side effects and `applies_to` scopes enumerated; sibling branches (MARGINAL/AVERAGE, LABEL/COMPOSITE, four claim predicates, three decide outcomes) rendered with equal density
- **Contract 3 (§3 Path Purity): PASS** — 605 backticked tokens scanned in §3; 0 path tokens, 0 bare HTTP methods, 0 method+path combos
- Additional checks: §2.2 verbatim byte-match confirmed; no pseudocode operators (`==`, `>=`, `+=`, …) in prose; no fuzzy/approximating words; all 60 enum/state values present; all 77 endpoints and all 50 errors in their tables

The forbidden files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced; no sibling task directories were inspected.

## Step 5: Generate Unit Tests — 2026-08-15T01:20:00.000Z

Generation complete. Final summary:

## Deliverables

**`test_helpers/` — 9 files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1906_protein_bar_functional_food_manufacturing/test_helpers/`):
`types.py` (16 entity TypedDicts, all `common_fields: true`; 25 enums), `api_client.py` (81 methods covering every PRD endpoint incl. `_clock`), `api_errors.py` (50 error IDs + HTTP map, registered via `set_error_http_status_map`), `assertions.py` (per-entity asserts + lot-mass and line-day invariant checkers, `assert_2dp`), `factories.py`, `constants.py` (PRD thresholds: SWAB_LIMIT_PPM 20, staleness 1440, buffers 0/30/60/90, TRIM 0.04, 12 bars/case, 91-day quarter, 5.00% yield, 30-day retain), `test_users.py` (shared opaque-role headers + `make_brand_customer_rep_headers(customer.id)` for the entity-backed role + per-role builders for SoD user-id threading), `fixtures.py` (primitive builders plus 12 composite scenario fixtures: label/composite, provisional/final sweetener, wet-clean staleness chain, peanut-line, gluten-free line, swab-gated run, supersede, yield pair, quarter-window pair, study pair, etc.), `__init__.py` barrel.

**`test_suite/` — 12 files** (`conftest.py` + 11 numbered test files), **77 tests**, all collected cleanly by pytest.

## Coverage

- **Queue A (Difficulty): 38 tests** — 19/19 instances with ≥2 tests each.
- **Queue B (Corner): 39 tests** — 39/39 non-stub instances with ≥1 test each.
- **Stubs (8):** not translated; all `excluded_because` cross-references verified to resolve to real difficulty instance names (`c_run_cancel_side_effects`, `c_moq_boundary_stub`, `c_state_safety_priority_stub`, `c_quote_computed_read_stub`, `c_day_availability_stub`, `c_cascade_layer_stub`, `c_dual_variant_layer_stub`, `c_rollup_reconciliation_stub`).

## Instances skipped

None. Every difficulty and non-stub corner instance passed the PRD-first two-condition filter. Two sub-assertions *inside* otherwise-covered instances were not uniquely derivable and were adjusted without weakening the covered claim: (1) `c_supplier_creation_defaults` asserts the PRD-stated defaults (PROVISIONAL, []) but not `version == 1` / exact `created_at` (PRD §2.4 never pins the initial version value nor logical-clock-driven `created_at`); (2) version checks in `c_lot_release_transition` and the revision reject-cycle use relative +1-per-mutation deltas instead of absolute values (§2.4 only states the increment).

## Self-audit verdicts

- **Stage 1: PASS** — compiles/imports cleanly; framework signatures verified against installed `prd_bench_local_runner.testing`; setup helpers use `get_success_data`; entity-backed role identity threaded via builders.
- **Stage 2: PASS** — 77/77 tests carry exactly one resolving `Design:` line (19 Difficulty tags ×2, 39 Corner tags ×1, zero unknown/untagged/dual-tagged); all 130 PRD citation quotes verbatim-grep against `PRD.md`; every asserted `error_id` and every priority/ordering claim (existence>state, safety>fiscal, state>safety, run-create gate order, lot-release guard order) is backed by explicit PRD prose (§2.6, §3.6, §3.8); no `skip`/`skipif`/`xfail`; no scaffold references in generated code; two-reader pass applied (no absolute version/timestamp equality where PRD leaves it open).

## Step 6: Generate Implementation — 2026-08-15T01:48:00.000Z

The implementation is complete and verified. Final summary:

## Implementation Complete — task_1906_protein_bar_functional_food_manufacturing

**Location:** `/home/ubuntu/github/CodingPRD/tasks/task_1906_protein_bar_functional_food_manufacturing/workspace/implementation/`

### File inventory (3,194 total lines)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | Foreground launcher; guarded pip install (`import flask` check), `exec python3 app.py`, `$PORT` (default 10000), binds 0.0.0.0 |
| `requirements.txt` | 1 | flask>=3.0 |
| `app.py` | 42 | Flask entry, blueprint registration, ApiError/404/405/500 envelope handlers |
| `db.py` | 98 | In-memory stores (dicts keyed by id, start empty every boot — zero seeding), logical clock pinned at `2026-08-01T00:00:00Z`, UUID/timestamp/version bookkeeping |
| `errors.py` | 99 | ApiError + all 50 scaffold error IDs with correct HTTP statuses |
| `util.py` | 154 | ISO8601 parse/format, Decimal helpers (round-half-up 2dp, ceil-0.01, floor-int), shape/enum validators |
| `response.py` | 79 | `meta`/`response_type`/`data` envelope, `req_` ids, 3-fractional-digit timestamps, limit/offset/total_count/has_more pagination (default 10, min 1, cap 100) |
| `middleware.py` | 57 | X-User-Role/X-User-ID auth (401/403), BrandCustomerRep ownership scoping |
| `serialize.py` | 109 | Per-entity serializers; computed fields (approved_revision_id, quarter rollup, lot ledger) derived at read |
| `services/calc.py` | 258 | All 10 calculations |
| `services/inventory.py` | 233 | FIFO reservation ledger, CASCADE-REJECT (3-link), CASCADE-SUPERSEDE (2-link), consumption/auto-DEPLETE, MISSED-pull materialization, clock-set evaluation |
| `routes/catalog.py` | 309 | suppliers, ingredients, ingredient-lots (12 endpoints) |
| `routes/commercial.py` | 233 | customers, agreements + lifecycle + quote (11 endpoints) |
| `routes/formulas.py` | 452 | formulas, revisions + pipeline + cascades, claim reviews (15 endpoints) |
| `routes/lines.py` | 238 | lines, slots, changeovers, day-availability (11 endpoints) |
| `routes/runs.py` | 643 | production runs + lifecycle, retain samples, lot releases (16 endpoints) |
| `routes/studies.py` | 179 | shelf-life studies, pulls, projection, logical clock (7 endpoints) |

### Coverage

- **Endpoints: 77/77** — verified programmatically via Flask's URL map against the scaffold table.
- **State machines: 9/9** — Supplier qualification, IngredientLot (incl. auto-DEPLETED at exact-zero), ManufacturingAgreement, FormulaRevision (incl. reject-back cycle + auto-SUPERSEDE), ProductionRun (compound dual-axis `status` × `release_status`), ChangeoverEvent (incl. FAILED→CLEANING_LOGGED re-clean loop and bookkeeping-free auto-CANCELLED that skips version bump), ShelfLifeStudy (auto-FAILED strict `>`, auto-COMPLETED at clock>expiry), LotRelease field-pair (qc_disposition × decision, HOLD_REWORK→SCRAPPED), ClaimReview (SUBMITTED→IN_REVIEW→APPROVED/REVISION_REQUESTED cycle).
- **Calculations: 10/10** — protein_claim_substantiation (LABEL + COMPOSITE variants, pinned per-line-round-then-divide rounding order), sweetener_blend_adjustment (PROVISIONAL ceil-0.01 + FINAL CoA-weighted with atomic top-up), agreement_case_pricing (MARGINAL walk + AVERAGE reached-tier, integer cents, half-up per-case), changeover_level_matrix (carryover set, PEANUT/TREE_NUT high-risk, 1440-min wet-clean staleness), cut_plan_case_count (per-slab floor before multiply, 4% trim, 12 bars/case), hardness_projection (fractional-day linear rate), yield_variance_check (inclusive ±5.00 gate), agreement_quarter_rollup (91-day half-open window), line_day_availability (1440-minute occupancy), claim_substantiation_gate (all four claim tags).
- **Error codes: 50/50** with scaffold HTTP statuses; validation cascade ordering implemented (auth → role → rep-scope → path 404s left-to-right → body-FK 404s → shape 400 → enum 400 → terminal lock 409 → state legality 409 → per-endpoint business order, including PRD-pinned orders such as SoD→retain→yield→QC on lot-release decide and segregation→revision→agreement→customer→MOQ→OCC on run create).
- **OCC**: `expected_agreement_version` (run create) and `expected_line_version` (schedule) → `ERR_STALE_VERSION` 412, checked last in each endpoint's business chain.

### Boot confirmation

Verified across five fresh-process boots (each starting with empty stores, proving no carry-over state for per-test-server isolation). Final check ran `bash start.sh` on a scratch port and got a 200 from `POST /mfg/_clock/set_current_utc` returning `{"current_utc": "2026-08-01T00:00:00Z"}`, then killed the server. Three end-to-end smoke suites (60+ assertions) passed covering the full operating loop: supplier qualification → lot intake/release → agreement activation + both pricing modes → revision pipeline with label/composite substantiation gates → claim-review adjudication with disclaimer and SoD guards → run create/schedule/verify/start/complete with FIFO reservation, sweetener top-up, slot overlap/buffer rules → both cascades (lot-reject de-scheduling with `INGREDIENT_SHORTAGE`, revision-approve supersede with `FORMULA_SUPERSEDED`) → retain/QC/decide with all four release gates → shelf-life pulls with MISSED materialization, strict failure boundary, and clock-driven auto-completion → rep scoping (403s on foreign/missing `customer_id`, implicit agreement-scoped run listing).

## Step 7: Run Tests and Iterate — 2026-08-15T02:05:00.000Z

## Summary

**Result: clean 8-round parallel sweep — 76/76 passed in every round (0 failures, 0 flakes).**

### Iterations run
2 (baseline sweep → fixes → verification sweep).

### Baseline
Round 1–8 all failed the same 5 tests deterministically (72/77 each): four UUID-format assertions and one pull-window rejection.

### Tests deleted (1)
- **`test_pull_recorded_past_grace_window_rejected`** (`test_suite/test_11_shelf_life.py`, class `TestPullWindow` removed) — **unique-derivability collapse (STEP 1b)**. The test records a baseline pull, sets the clock to 2026-08-11 (past pull 1's due 2026-08-08 + 2-day grace), then asserts a new recording at 2026-08-11 is rejected with `ERR_PULL_WINDOW_MISSED`. PRD §3.9 states each pull "receives a 0-based `pull_index` assigned in creation order within its study" with `due_utc` computed from that index, and PRD line 93 + §3.9 mandate that pulls whose grace elapsed "are marked missed" when the clock is set. Under that plain reading, the clock-set materializes pull 1 as a MISSED record consuming index 1, so the new recording takes index 2 (due 2026-08-15) and falls inside both stated window bounds — the PRD's own rules determine *acceptance*, and the implementation (generated from the scaffold) behaved exactly that way. The rejection semantics traces only to the scaffold's second clause "a pull whose grace has elapsed is MISSED and cannot be recorded" (SCAFFOLD.yaml `validations[priority=23]`; corner instance `c_pull_window_missed`), which never reached PRD prose. A faithful PRD-only implementer lands on the failing behavior while remaining consistent with every cited PRD sentence. Feedback for doc-generator: Zero-Silence violation — the MISSED-slot blocking rule was never rendered into PRD; for unit-test-generator: unique-derivability miss on the slot-targeting semantics.

### Fixes applied to `test_helpers/`
None.

### Fixes applied to `test_suite/`
None beyond the deletion above (no assertions weakened, no skips/xfails added).

### Fixes applied to `implementation/` (1)
- **`workspace/implementation/db.py` — `new_id()`**: changed `uuid.uuid4().hex` (32-char undashed hex) to `str(uuid.uuid4())` (canonical dashed RFC 4122 form). PRD §2.1 (line 86) requires `id` to be "a server-minted UUID with no type prefix"; the benchmark-wide `is_valid_uuid` contract enforces the canonical dashed representation. This single fix resolved all four remaining failures: `test_success_and_error_envelopes`, `test_read_after_write_returns_created_resource`, `test_creation_applies_defaults`, `test_revision_no_sequence_and_allergen_profile`. Verified no other code depends on the undashed format.

### Final state
- Total tests: 76 (was 77; one deleted per PRD-First contract).
- All 8 parallel rounds: `passed == total == 76`, `failed == 0`.
- Implementation storage remains in-memory only; `start.sh` unchanged; no PRD.md modifications.

## Step 8: Finalize PRD — 2026-08-15T01:35:00.000Z

The diff is exactly two revised lines, both traced to Step 7 items. Final verification of the two edit sites against the implementation is complete (all enumerated paths consistent). Summary below.

## Result

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1906_protein_bar_functional_food_manufacturing/workspace/PRD_FINALIZED.md`

**Line counts:** PRD.md 376 lines → PRD_FINALIZED.md 376 lines (0.0% line-count delta; both edits are in-place revisions of existing lines 86 and 233).

## Changes (2 edits, both revisions, no new sections)

- **§2.4 (Resource Identity) — revise** — The `id` bullet now pins the canonical dashed RFC 4122 representation (8-4-4-4-12 hyphenated hexadecimal groups, e.g. `550e8400-e29b-41d4-a716-446655440000`) instead of the bare "server-minted UUID with no type prefix," which admitted the undashed `uuid4().hex` form the implementation originally shipped. — `implementation/db.py:76-77` (`new_id()` → `str(uuid.uuid4())`); benchmark contract `is_valid_uuid` at `prd-bench-local-runner/src/prd_bench_local_runner/testing/assertions.py:28`.
- **§3.9 (Shelf-Life Studies) — revise (two sentences in the pull paragraph)** — Pins the implementation's MISSED-pull semantics that the deleted `test_pull_recorded_past_grace_window_rejected` exposed as PRD-silent: (a) `pull_index` is one creation-order sequence shared by `RECORDED` and `MISSED` pulls alike; (b) becoming `MISSED` materializes an actual pull record that consumes its index (with `recorded_utc`/`hardness_n` null), evaluated at clock-set and at the start of every record attempt *before* the new index is assigned, only while the study is `ACTIVE`; (c) an elapsed grace window therefore never blocks a later recording — the new pull takes the next unconsumed index and the window/`ERR_PULL_WINDOW_MISSED` check is evaluated against that pull's own `due_utc`. — `implementation/services/inventory.py:191-217` (`next_pull_index`, `pull_due_utc`, `materialize_missed_pulls`), `implementation/routes/studies.py:114-147` (`record_pull`), `implementation/services/inventory.py:220-233` (`evaluate_clock_transitions`).

## Per-edit pre-edit search log

**Edit 1 (UUID format)**
- (a) Subject: string representation of the server-minted `id` on every resource.
- (b) Paths enumerated: `db.py:76-77` `new_id()` (sole mint site); `db.py:80-88` `base_record()` (sole caller); all 18 `base_record()` call sites across `routes/catalog.py`, `routes/commercial.py`, `routes/formulas.py`, `routes/lines.py`, `routes/runs.py`, `routes/studies.py`, `services/inventory.py` (covers all 16 entity types, including MISSED pulls); grep for direct `["id"] =` assignments returned none; `serialize.py:_emit` passes `id` through unchanged; `response.py:11` `api_request_id` is a separate `req_`-prefixed token governed by §2.2, untouched.
- (c) Adjustment: pinned "canonical dashed RFC 4122 representation" with an 8-4-4-4-12 pattern and a lowercase example, but did not mandate hex case — impl emits lowercase, the benchmark regex is case-insensitive, and mandating case would over-pin beyond what any consumer requires.

**Edit 2 (pull recording / MISSED materialization)**
- (a) Subject: shelf-life pull recording, `pull_index` assignment, MISSED materialization, and the recording-window rejection.
- (b) Paths enumerated and read: `routes/studies.py:114-147` (`record_pull`: terminal lock → materialize → next index → window check `recorded_dt > CLOCK.current or recorded_dt > due + 2d` against the *new* index's own due → create `RECORDED` → projection → auto-FAIL); `services/inventory.py:191-192` (`next_pull_index` counts pulls of any status); `services/inventory.py:195-196` (`pull_due_utc`); `services/inventory.py:199-217` (`materialize_missed_pulls`: ACTIVE-only, consumes consecutive indices, null `recorded_utc`/`hardness_n`); `services/inventory.py:220-233` (`evaluate_clock_transitions`: materialize per ACTIVE study, then auto-COMPLETE past-expiry with passing/absent projection); `routes/studies.py:150-155` (`list_pulls` returns RECORDED + MISSED in creation order); `routes/studies.py:158-169` + `services/calc.py:174-190` (projection filters `status == "RECORDED"`; MISSED excluded from projection and `pulls_used`); `serialize.py:96-97` + `_emit` (None datetime → JSON null). Cross-checked PRD-wide statements touching the same subject: §2.4 line 93 clock-set summary (consistent — "marked missed, as detailed in §3.9"), §2.6 stage 8 terminal lock (consistent), endpoint table line 307 and error catalogue line 361 (unaffected, window rejection sentence kept verbatim).
- (c) Adjustments: added the "of an `ACTIVE` study" qualifier to the MISSED sentence (impl early-returns for non-ACTIVE studies in both materialize paths, so unqualified wording would falsely claim FAILED/COMPLETED/TERMINATED studies keep accruing MISSED pulls at later clock-sets); scoped the "never blocks" claim to the recording path only and explicitly re-anchored the retained window rejection to the new pull's own `due_utc`; deliberately made no projection-related claim in the new sentences since §3.9's projection paragraph already pins "recorded pulls" — avoiding a redundant claim that could drift.

## Step 9: Complete PRD — 2026-08-15T01:50:00.000Z

Produced `/home/ubuntu/github/CodingPRD/tasks/task_1906_protein_bar_functional_food_manufacturing/workspace/PRD_COMPLETED.md` (copied from PRD_FINALIZED.md, then edited in place; all other files untouched).

**Size**: PRD_FINALIZED.md 376 lines / 68,687 chars → PRD_COMPLETED.md 378 lines / 74,243 chars (delta +2 lines, +5,556 chars; 31 paragraphs revised inline + 1 short new paragraph in §2.2).

**Counts**: 28 ambiguity-pins, 13 mismatch-revisions.

**Mismatch revisions** (PRD described different behavior than impl):
- §2.1 — revise — mismatch — "must carry X-User-ID" → X-User-ID may be omitted; empty identifier still participates in SoD comparisons — middleware.py:24
- §3.1 — revise — mismatch — supplier creation honors an explicit `qualification_status` (not always PROVISIONAL) — catalog.py:73-76
- §3.1 — revise — mismatch — ingredient creation honors an explicit `status` (ACTIVE/DISCONTINUED; only path to DISCONTINUED) — catalog.py:144-149
- §3.2 — revise — mismatch — dropped "expressed to two decimal places" on `received_qty_kg` (only > 0 enforced) — catalog.py:216
- §3.3 — revise — mismatch — customer creation honors explicit `status` (only path to SUSPENDED) — commercial.py:62
- §3.3 — revise — mismatch — `tier_breaks`: strictly ascending ceilings (equal rejected), positive `upto_cases`, non-negative rates, at least one tier — commercial.py:87-108
- §3.4 — revise — mismatch — formula creation honors explicit `status` (only path to ARCHIVED) — formulas.py:105-108
- §3.6 — revise — mismatch — run-creation gate order: inserted the formula-ARCHIVED check (`ERR_FORMULA_ARCHIVED`) between revision-APPROVED and agreement-ACTIVE — runs.py:105-114
- §3.6 — revise — mismatch — `batch_code` is the run's own 1-based ordinal zero-padded to four digits (`BATCH-0001` first), not a count of prior runs — runs.py:139, db.py:30
- §3.6 — revise — mismatch — previous-run selection restricted to runs whose CONFIRMED/COMPLETED slot ends at or before the new start — runs.py:203-219
- §3.6 — revise — mismatch — removed "Free minutes are never negative"; `free_minutes` is computed unclamped — calc.py:233
- §2.6 + §3.7 — revise — mismatch — record-swab evaluates state/level checks before request-shape validation, deviating from the global cascade order — lines.py:180-190
- §3.9 — revise — mismatch — pull window "bounded on both sides" → bounded on the late side only; any past `recorded_utc` accepted — studies.py:127

**Ambiguity pins** (PRD silent; pinned to impl):
- §2.1 — insert — claim-review read-by-id and resubmission are not customer-scoped; scoped list is exhaustive — formulas.py:385-389, 441-452
- §2.2 — insert — fallback errors `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405), `ERR_INTERNAL` (500) in the same envelope — app.py:25-38
- §2.3 — insert — non-integer/negative pagination params → `ERR_INVALID_REQUEST`; limit > 100 silently capped; enum filter params → `ERR_INVALID_ENUM_VALUE`; identifier filters not existence-checked — response.py:42-74
- §2.3 — insert — list sort ties on identical `created_at` break by creation order — catalog.py:37-38 (all routes)
- §2.4 — revise — `version` starts at 1 — db.py:80-88
- §2.4 — insert — clock may be set to any instant, including backward; reverses nothing — studies.py:172-179
- §2.4 — insert — client datetimes parsed as ISO 8601, naive read as UTC, rendered with `Z` and fractional digits only when sub-second — util.py:51-63, db.py:68-73
- §2.6 — insert — terminal-state lock guards mutating actions only; reads unaffected — e.g. runs.py:181-186, 577-580
- §2.8 — insert — auto-DEPLETED rides the consuming mutation's single version increment — inventory.py:79-86, 176-186
- §3.1 — insert — supplier PATCH revises `allergens_handled` outright; repeated status skips transition check; every successful PATCH bumps version — catalog.py:98-120
- §3.1 — insert — either nominal assay accepted/stored for any category; mandate only makes the paired field required — catalog.py:136-165
- §3.2 — insert — either CoA assay accepted/stored on any receipt — catalog.py:218-231
- §3.2 — insert — CASCADE-REJECT changeover cancellation exempts events already VALIDATED — inventory.py:110-113, 144-146
- §3.3 — insert — quote takes `cases` as a query parameter, positive integer else `ERR_INVALID_REQUEST` — commercial.py:222-230
- §3.4 — insert — protein line whose ingredient lacks `nominal_protein_pct` (or lot lacks `coa_protein_pct`) contributes zero — calc.py:52, 69
- §3.4 — insert — failed nutrition verification writes nothing; revision stays SUBMITTED with label null — formulas.py:270-276
- §3.4 — insert — CASCADE-SUPERSEDE changeover cancellation exempts VALIDATED events — inventory.py:170-172
- §3.5 — insert — reviewed `claim_tag` need not be in `claim_tags`; revision may be in any status; multiple reviews per tag allowed — formulas.py:345-382
- §3.5 — insert — resubmission retains the stamped `reviewer_id` — formulas.py:441-452
- §3.5 — insert — verification-triggered `substantiation_ok` refresh does not bump the review's version — formulas.py:71-78
- §3.6 — insert — per-line reserved quantity: provisional ceil requirement for SWEETENER lines, exact `qty_kg_per_batch` otherwise; readiness compares against the same requirement — inventory.py:56-76, runs.py:128-133
- §3.6 — insert — re-scheduling a cascade-de-scheduled run does not clear its `cancel_reason` — runs.py:309-311
- §3.6 — insert — day-availability takes `date` as a YYYY-MM-DD query parameter; occupied minutes discard sub-minute remainder after summing — lines.py:122-136, calc.py:217-234
- §3.7 — insert — recorded `swab_allergen_ppm` must be ≥ 0 (`ERR_INVALID_REQUEST`) — lines.py:189-190
- §3.7 — insert — validating a SWAB_VALIDATE event directly from CLEANING_LOGGED → `ERR_INVALID_STATE` — lines.py:202-205
- §3.8 — insert — successful pre-run verification also increments the revision's and each topped-up lot's version — runs.py:385-395
- §3.8 — insert — decide SoD guard is vacuous while `qc_recorded_by` is null (no QC recorded) — runs.py:617
- §3.9 — insert — zero-elapsed-days projection (first/last pulls share `recorded_utc`) equals the last recorded pull's hardness — calc.py:187-188

Notable confirmed-consistency areas (no change needed): all 60+ endpoint paths and role lists in §4 match the blueprints exactly; LABEL/COMPOSITE protein rounding pipeline, cut-plan floor ordering, tier pricing math, changeover level matrix, OCC gates, cascade links, and the missed-pull materialization semantics were already uniquely pinned by the PRD.

---

## Pipeline complete — 2026-08-15T01:50:00.000Z

All 9 steps finished. Final state: 76/76 tests passing across 8 parallel stability rounds under `--isolation per-test-server`; PRD chain PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md produced; worklog contains verbatim summaries for every step.
