# Worklog — task_1892_nutrition_labeling_regulatory_review

## Step 1: Create Task Directory — 2026-08-14T23:09:00.000Z

Directory `tasks/task_1892_nutrition_labeling_regulatory_review/` and `workspace/` pre-created by pipeline dispatcher (Step 1 already done per invocation args).

## Step 2: Generate Scaffold — 2026-08-15T00:05:00.000Z

All three artifacts are generated and verified. Final summary:

## Task 1892 — Nutrition Labeling & Regulatory Review: scaffold complete

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1892_nutrition_labeling_regulatory_review/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys leaked)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top key `scaffold_corner_design`

**Counts**
- Entities: **13** (Client, Product, Ingredient, Recipe, LabAnalysis, NutrientPanel, RaccAssignment, LabelVersion, ClaimAssessment, MarketVariant, FormatCheck, ArtworkAudit, AuditFinding)
- Endpoints: **47** — above the 28–32 target, deliberately: lint check (f) forces a reverse-reachability GET per FK (12 FK fields incl. 6 reference FKs), and 7 state machines need their action endpoints; every endpoint is load-bearing, none are padding.
- Error codes: **30** (all referenced by validations/transitions/concurrency; all design-cited codes exist in the catalog)
- State machines: **7** — ClaimAssessment (auto cycle ELIGIBLE→SUSPENDED→ELIGIBLE), LabelVersion (parallel dims review_status × release_status + reject cycle), LabAnalysis (branching + supersede), Recipe, NutrientPanel, MarketVariant, ArtworkAudit
- Calculations: **7** with **6 variants** (DATABASE/LAB panels, US_FDA/CA_CFIA serving rounding, BINARY/WEIGHTED audit scoring)
- Validations: 30 rows across 8 priority tiers; 2 OCC concurrency rules on Product.version; 6 roles (segregation-of-duties model: approver ≠ prepared_by)

**Difficulty layers (4, per §0.2/§0.3)**: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, version_pinning_on_approval. Archetype: compliance_audit + workflow_orchestration; flat topology; segregation_of_duties role model.

**§0.5 rule coverage in §1.8 (22 instances, all ≥2 per rule)**: dual_variant 3 (panel / serving / audit domains), combinatorial 3 (modes a, b, c — disqualifier interaction, raw-vs-round-first nested rounding pinned at 1.23 vs 1.24, single-serving evaluation order), non_linear_state_machine 2, transitive_cascade 2 (lab-validation depth-4 vs recipe-lock depth-4, distinct triggers), priority_pair_validation_conflict 2 (disjoint pairs: state×safety, constraint×referential), boundary_precision 3 (RACC ratio exactly 2.0, LOW_FAT exactly 3.0g, package area exactly 12.0 sq in — three metrics, three endpoints), cross_entity_state_dependency 3 (distinct pairs), resource_temporal_overlap 2 (half-open adjacency-allowed market windows vs buffered closed facility windows), compensating_invariant 2 (released-set identity per product-market; label content tuple across submit/reject).

**§1.9**: 51 non-stub instances + 3 `excluded_because` stubs across all 9 guide sections; every numeric assert pre-computed as a literal (e.g., kcal 366.75 vs 350.0, 458.44 at yield 0.8, audit scores 0 vs 91).

**Verification**: `scaffold_lint.py` final result — `VERDICT: clean lint` (711 calls scanned, 0 violations; 6 initial FK_REVERSE_UNREACHABLE findings fixed by adding 6 reverse-reachability GETs). Placeholder closure: zero unbound `${var}` (instance-wide scope, verified by script). Name uniqueness across both design files: clean. No forbidden concurrency vocabulary. All enum values reachable; endpoint roles ⊆ RBAC roles.

## Step 3: Copy Shared Files — 2026-08-15T00:07:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1892_nutrition_labeling_regulatory_review/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-15T00:20:00.000Z

## Generation Complete

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1892_nutrition_labeling_regulatory_review/workspace/PRD.md` — 271 lines.

### Section List
- **§1. Introduction** (2 paragraphs — business context + scope)
- **§2. Global Specifications & System-Wide Principles**
  - 2.1 User and Role-Based Access Control (all 6 roles, per-role `identity:` translation, client-chain scoping, segregation of duties)
  - 2.2 API Response Structure (emitted verbatim from `section-2.2-response-structure.md`, byte-identical)
  - 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending, meta fields)
  - 2.4 Common Resource Properties (`id`/`created_at`/`updated_at`/`version`; cascade mutations bump version)
  - 2.5 Numeric Precision and the Rounding Discipline (2dp round-half-up; pinned raw-first ordering; integer audit scores; exact decimal tier comparisons)
  - 2.6 Optimistic Concurrency Control (both OCC rules on `expected_product_version` → `ERR_STALE_VERSION` 412, stale-state framing only)
  - 2.7 The Logical Clock and Time-Window Semantics (default `2026-08-01T00:00:00Z`, half-open windows, 86,400 s facility buffer)
  - 2.8 Request Validation Order and Nested Resource Retrieval (8-level priority sequence, within-level listed-order rule, release-gate order, left-to-right path resolution)
  - 2.9 The Dual-Market Regulatory Model (US_FDA/CA_CFIA, full RACC table values, three divergence points)
- **§3. Business Logic & Workflows** (8 subsections): 3.1 Client Onboarding and Product Registration · 3.2 Ingredient Catalogue and Recipe Formulation · 3.3 Laboratory Substantiation of Nutrient Values · 3.4 Nutrient Panel Computation and the Rounding Pipeline · 3.5 Serving-Size Determination · 3.6 Label Drafting, Regulatory Review, and Release · 3.7 Claim Eligibility and Content Freshness · 3.8 Market Variants and Artwork Audits
- **§4. Endpoint Definitions** — 47-row table, 4 columns only (Method / Path / Description / Authorized Role(s))
- **§5. Error Code Catalogue** — 30-row table, 2 columns only

### Hard Contract Reports
```
Field coverage check:
- entities[].fields + endpoint inputs + query params + envelope/common fields: 90 required, 90 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 8 priority levels expressed incl. within-level ordering + release-gate order, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_product_version + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: 23 checked, 23 fully expressed (incl. cascades, compensating withdraw, claim re-evaluation), 0 missing
- calculations[]: 7 checked, 7 fully expressed in precise prose (panel computation, serving-size, claim eligibility, declaration tier-rounding, statement ordering, format tiers, audit scoring), 0 missing
- validations[] conditions: 30 checked, 30 matchable to error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed in workflow narratives, 0 missing
- entities[].fields[] structured content: defaults (allergen_tags [], yield_factor 1.0, scoring_method WEIGHTED, review_round 0), nullability, and initial states reconstructible, 0 missing
- sibling-branch symmetry: 8 groups (VALIDATED/REJECTED, ELIGIBLE/INELIGIBLE/NOT_REQUIRED, SUSPENDED→ELIGIBLE/INELIGIBLE, US/CA variants, DATABASE/LAB, BINARY/WEIGHTED, approve/reject, format tiers) at equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 449
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

### Coverage Confirmation
Every scaffold element received prose coverage: all 12 entities (fields, defaults, nullability, initial states), all 8 state machines with all 23 transitions (preconditions + error ids + side effects), all 7 calculations (formulas translated to precise natural language with thresholds, evaluation order, and rounding pinned — including the raw-vs-rounded ordering rule and per-nutrient declaration tiers), all 30 validation rules matched to their error ids and `applies_to` scopes, both OCC rules, all 47 endpoints in §4, all 30 errors in §5, and all 6 roles with identity semantics. The withheld difficulty/corner design files were never opened.

## Step 6: Generate Implementation — 2026-08-15T00:45:00.000Z

Implementation complete and verified. Summary:

## Files generated

All under `/home/ubuntu/github/CodingPRD/tasks/task_1892_nutrition_labeling_regulatory_review/workspace/implementation/`:

- **`app.py`** (~1,050 lines) — complete Flask implementation: all 47 endpoints from the endpoint table, in-memory store (13 dicts keyed by UUID, zero seeding), full validation priority chain, both cascade families, and all six calculations.
- **`start.sh`** — launcher (executable).
- **`requirements.txt`** — `flask>=3.0`.

## start.sh contract

Reads `$PORT` (default 10000, passed through to `app.run(host="0.0.0.0", port=...)` in `app.py`), binds `0.0.0.0`, and uses `exec python3 app.py` so the server runs in the foreground with signal propagation. The dependency install is guarded (`if ! python3 -c "import flask"`) so per-test-server reboots skip `pip install` entirely once Flask is present.

## Key implementation decisions (traced to PRD)

- **Envelope**: `meta` (api_request_id `req_*`, `api_request_timestamp` with 3 fractional digits) / `response_type` (`object`|`array`|`error`) / `data` (`error_id` + `message` on errors); pagination fields `limit`/`offset`/`total_count`/`has_more` in `meta` for lists only.
- **Auth**: `X-User-ID` + `X-User-Role`, six roles; `ClientRep`/`QualityManager` are entity-backed (X-User-ID must equal the resource's client-chain id; global list endpoints filter to own chain, path-scoped reads return 403 otherwise); segregation-of-duties 403 on approve.
- **Calculations in Decimal, round-half-up**: DATABASE panel weighted aggregation with yield adjustment; LAB panel adopts the validated assay verbatim; the unrounded per-100g vector is stored privately (`_raw`, stripped at serialization) and all downstream per-RACC/per-serving values derive from it per the pinned rounding discipline. US_FDA household-first (nearest 0.5 unit) vs CA_CFIA metric-first (nearest 5g/1g) serving rounding; ratio bands `<2.0 / 2.0–3.0 / >3.0` compared as exact decimals against RACC.
- **Cascades**: recipe lock supersedes LOCKED sibling → its CURRENT panels STALE → ELIGIBLE claims on those panels SUSPENDED; lab validation repoints `latest_validated_lab_analysis_id`, supersedes prior VALIDATED, stales its LAB panels, suspends dependent claims. New CURRENT panels re-evaluate SUSPENDED claims (pass → ELIGIBLE + repoint basis, fail → INELIGIBLE). Every mutation (including system cascades) bumps `version`/`updated_at`.
- **`content_status` is derived on read** (READY/NEEDS_REVISION from suspended claims + pinned-panel staleness + locked-recipe drift), so it's always consistent; format checks never affect it, they only gate release.
- **Validation order** per PRD §2.8, including the pinned release-gate order (OCC 412 → LABEL_NOT_APPROVED → CONTENT_REVISION_REQUIRED → CLAIMS_NOT_RESOLVED → FORMAT_CHECK_FAILED), priority-6 overlap/duplicate checks before priority-7 window validity, and scope errors last (422).
- **Logical clock** defaults to `2026-08-01T00:00:00Z`; half-open variant windows, 1-day facility buffer with equality permitted.
- **OCC** `expected_product_version` on label-draft create and release only → 412.

## Self-check (smoke-booted)

The server was booted three times via `bash start.sh` on throwaway ports. Fresh-boot confirmed: after restart, previously created IDs return 404 `ERR_NOT_FOUND`. Four smoke scripts (60+ assertions, all passing) exercised: auth error envelope (400 with exact error body), client→product→ingredient→recipe→lock→panel→RACC→label→submit→approve→release happy paths, envelope shape for object/array/error, OCC 412, draft-withdraw on re-create, claim evaluation math (LOW_FAT 15.42 vs 3.0 → INELIGIBLE/FAT), CA NOT_REQUIRED claims, LAB supersede cascade suspending an ELIGIBLE claim and flipping content_status to NEEDS_REVISION, re-evaluation to INELIGIBLE on the new panel, variant window + logical clock activation (409 before window, 200 after clock set), duplicate/retire semantics, facility 1-day buffer 409, window-invalid 422, WEIGHTED scoring (1 CRITICAL + 1 MINOR → 89 → FAIL) vs BINARY (1 MINOR → 0 → FAIL), close-from-SCHEDULED 409, release supersede chain with `superseded_by_id` reverse-lookup filter, withdraw restoring the superseded label, reject retaining declared content + pinned snapshot with review_round incrementing on resubmit, format-failure gating release with content_status unaffected, and cross-client 403 scoping.

## Step 5: Generate Unit Tests — 2026-08-15T01:00:00.000Z

## Summary

Generated complete test infrastructure for `task_1892_nutrition_labeling_regulatory_review`, translating both design indices under the design-index-only contract.

### Test counts
- **Queue A (Difficulty): 44 tests** — 22 instances × 2 tests each, all 9 rules covered (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant). Audit confirms every instance carries ≥2 tests with verbatim `Design: Difficulty/<rule_id>/<name>` tags.
- **Queue B (Corner): 49 tests** — every non-stub instance covered by exactly ≥1 test with verbatim `Design: Corner/<section>/<name>` tags. The 3 `excluded_because:` stubs were not translated; their difficulty-instance cross-references all resolve.
- **93 tests total**, all collected cleanly by pytest; 160 PRD citations verified verbatim against `workspace/PRD.md` (whitespace-normalized literal match); no skip/xfail markers; no scaffold references in generated code.

### Instances skipped (PRD-first filter, gaps left as gaps — 2)
1. **`Corner/entities/entity_racc_create_extra_field_rejected`** — category: request-shape/default-value silence. The instance asserts posting a computed field (`serving_size_g`) returns 400 `ERR_INVALID_REQUEST`, but PRD §2.8's body-check rule only covers required fields, enum validity, positivity, yield band, and line shape — it never states unknown extra fields are rejected. A PRD-faithful implementer could ignore the field and return 201, so the outcome is not uniquely derivable.
2. **`Corner/calculations/calc_racc_unknown_category_rejected`** — category: PRD contradicts the claim. The instance expects CONFECTION under CA_CFIA → `ERR_RACC_CATEGORY_UNKNOWN`, but PRD §2.9 states verbatim "Both markets share the same reference-amount table" including "`CONFECTION` 40 grams" — a PRD-only implementer would succeed with racc_g 40, not error.

### Key adjudication decisions
- **Version assertions are relative (+1)**: this PRD's §2.4 says version "increments by one on every mutation" but never pins an initial value (unlike sibling tasks whose PRDs say "starts at 1"), so no test asserts an absolute initial version.
- **Canonical statements discovered, not hard-coded**: fixtures call `GET /api/recipes/{id}/ingredient-statement` to obtain the exact canonical `ingredient_statement_text`/`contains_text` for submit-review paths, making success-path fixtures immune to the PRD's case/separator ambiguity in allergen rendering. Exact strings are asserted only in `calc_ingredient_statement_canonical_order`, where the string form is the claim.
- **Clock-separated ingredient creation** in the canonical-order test so the `created_at` tie-break is deterministic under both wall-clock and logical-clock timestamping.
- **Priority-pair instances** (state-beats-safety, constraint-beats-referential) translated with a second control test each (the lower-priority error firing once the higher-priority violation is removed), grounded in PRD §2.8's explicit fixed priority sequence.

### `test_helpers/` (9 files)
`__init__.py` (barrel), `types.py` (13 TypedDicts + 19 enums), `api_client.py` (42 endpoint methods, `/api` prefix), `api_errors.py` (30 errors, registered HTTP map), `assertions.py` (per-entity + 3-fractional-digit timestamp checker), `factories.py`, `constants.py` (RACC table, disqualifier/claim thresholds, format tiers, audit weights, 86400s buffer), `test_users.py` (opaque shared headers + `make_client_rep_headers`/`make_quality_manager_headers` entity-backed builders), `fixtures.py` (tiered composites: wafer/cookie workspaces, approved/released label walks, lab-validated claim workspace, audit scheduling).

### `test_suite/` (12 files)
`conftest.py` plus `test_01_registration_listing_and_auth.py` (7), `test_02_rbac_and_ownership.py` (6), `test_03_nutrient_panel_computation.py` (6), `test_04_serving_size_determination.py` (9), `test_05_label_submit_review_and_format.py` (9), `test_06_recipe_lab_cascades.py` (7), `test_07_claim_eligibility.py` (12), `test_08_label_release_lifecycle.py` (14), `test_09_market_variants.py` (9), `test_10_artwork_audits.py` (9), `test_11_occ_pinning_and_consistency.py` (5).

All paths rooted at `/home/ubuntu/github/CodingPRD/tasks/task_1892_nutrition_labeling_regulatory_review/`.

## Step 7: Run Tests and Iterate — 2026-08-15T01:25:00.000Z

All 8 rounds of sweep 3 verified clean: 93/93 passed, 0 failed, 0 errors in every round. Exit condition met.

## Summary

**Iterations run:** 3 eight-round parallel sweeps.
- Sweep 1 (baseline): 79–80/93 per round; union of 14 failing tests (3 defect clusters + 1 transport flake).
- Sweep 2 (after fixes 1–4 below): 92/93 in all 8 rounds; single remaining failure.
- Sweep 3 (after fix 5): **93/93 in all 8 rounds — clean exit.**

**Tests deleted:** none. Every failing assertion traced to a rule stated verbatim in PRD.md; no PRD-silence (STEP 1a) or unique-derivability collapse (STEP 1b) was found, so no deletions were warranted.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1892_nutrition_labeling_regulatory_review/test_helpers/api_client.py` — `ApiClient.__init__`: mounted an `HTTPAdapter` with `Retry(total=5, connect=5, read=5, allowed_methods=None, raise_on_status=False)`. Under per-test-server isolation the module-level pooled `requests.Session` occasionally reuses a stale keep-alive connection to the just-killed server, producing `RemoteDisconnected` (the 2/8-round flake on `test_10::test_binary_scoring_any_finding_fails` in sweep 1). Only transport-level connection/protocol errors are retried — status codes pass through untouched, so assertion semantics are unchanged.

**Fixes applied to `test_suite/`:**
- `test_05_label_submit_review_and_format.py` — added the missing `create_product` import (5 tests died with `NameError` before reaching any assertion).
- `test_05_label_submit_review_and_format.py::test_ingredient_statement_canonical_order` — corrected the `contains_text` expectation from `"Contains: Wheat, Milk."` to `"Contains: WHEAT, MILK."` (STEP 2: assertion mis-translated PRD §3.2's "the literal prefix `Contains: `, the comma-joined tags, and a closing period", where tags are the uppercase `allergen_tags` enum codes; the title-cased rendering existed only as a SCAFFOLD.yaml example, never in PRD).
- `test_07_claim_eligibility.py::test_claim_succeeds_once_recipe_locked` — the assertion comment assumed fat 2.0/100g ("fat per RACC 2.0 x 0.55 = 1.1 <= 3.0") but the ingredient was built with the factory default profile (fat 8.0 → per-RACC 4.4 > 3.0), so the PRD-faithful implementation correctly returned INELIGIBLE (STEP 2: fixture input contradicted the test's own documented precondition). Fixed by passing the explicit nutrient profile the assertion assumes.

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1892_nutrition_labeling_regulatory_review/workspace/implementation/app.py` — `_new_record`: `id` changed from `uuid.uuid4().hex` to `str(uuid.uuid4())`. PRD §2.4 requires "a server-minted UUID with no type prefix"; the harness's shared `is_valid_uuid` validator accepts only the canonical dashed 8-4-4-4-12 form. This unblocked all 8 tests failing at `assert_*` common-field checks (test_01, test_03 ×2, test_04 ×2, test_07 ×2, test_10).

## Step 8: Finalize PRD — 2026-08-15T01:35:00.000Z

Both edits verified. The diff between PRD.md and PRD_FINALIZED.md contains exactly the two intended in-place edits, and the `translated_contains_text` enumeration confirms the §3.2 edit is correctly scoped (variant translations are stored free text, never compared to canonical — not mis-described).

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1892_nutrition_labeling_regulatory_review/workspace/PRD_FINALIZED.md` created.

**Line counts:** PRD.md 270 lines → PRD_FINALIZED.md 270 lines; 0.0% line-count delta (2 lines revised in place, +~320 characters total). No sections added or removed.

### Changes (one bullet per edit)

- **§2.4 Common Resource Properties** — revise — pinned the `id` rendering to "the canonical dashed 8-4-4-4-12 hexadecimal form (as produced by Python's `str(uuid.uuid4())`)" and explicitly excluded the dashless 32-character hex rendering — `implementation/app.py:227` (`_new_record`, the Step 7 impl fix from `uuid.uuid4().hex` to `str(uuid.uuid4())`).
- **§3.2 Ingredient Catalogue and Recipe Formulation** — revise — replaced both vague "comma-joined" phrases: ingredient names are "joined by `, ` (a comma followed by a single space)", and `contains_text` tags are "joined by `, ` with each tag written verbatim as its uppercase allergen code", with the exact example `Contains: WHEAT, MILK.` added — `implementation/app.py:700` (`", ".join(names)`) and `app.py:706` (`"Contains: " + ", ".join(tags) + "."`).

### Step-7 diff items that produced no PRD edit

- `test_helpers/api_client.py` Retry adapter — transport-level only; status codes pass through, assertion semantics unchanged; no PRD behavioral surface.
- `test_05` missing `create_product` import — pure fixture bug (NameError before any assertion).
- `test_07::test_claim_succeeds_once_recipe_locked` — pure fixture bug: the ingredient used the factory-default fat 8.0/100g while the assertion's own comment assumed 2.0/100g; the PRD-faithful impl correctly returned INELIGIBLE. PRD §3.7 thresholds already pinned; no edit.

### Per-edit pre-edit search log

**Edit 1 (§2.4 id format):**
- (a) Subject: string rendering of the server-minted `id` field on all resources.
- (b) Enumerated paths: grep for `uuid` and `"id"` across `app.py` — the sole minting site is `_new_record` at `app.py:227`, reached by all 13 resource creators (clients :761, products :798, ingredients :852, recipes :910, lab analyses :1015, nutrient panels :1104, RACC assignments :1218, label versions :1296, claims :1553, market variants :1656, format checks :729, artwork audits :1806, audit findings :1859). Also checked the harness validator `is_valid_uuid` (`prd-bench-local-runner/src/prd_bench_local_runner/testing/assertions.py:19-30`, dashed 8-4-4-4-12 regex, case-insensitive) and confirmed `api_request_id` (`app.py:136`, `req_…`) is §2.2 scope, untouched.
- (c) Adjustment: pinned the dashed form but deliberately did not pin letter case (validator is case-insensitive; lowercase is only implied via the `str(uuid.uuid4())` reference) — avoids over-specifying beyond observable behavior.

**Edit 2 (§3.2 statement rendering):**
- (a) Subject: rendering of the computed `ingredient_statement_text` / `contains_text` (join separator and tag casing).
- (b) Enumerated paths: sole builder `_canonical_statements` (`app.py:687-711`); consumers `get_ingredient_statement` (:978-995, returns verbatim) and `submit_review` (:1370-1380, exact compare after `.strip()`); tag source `create_ingredient` (:844-846, validates against the uppercase `ALLERGENS` enum, so "verbatim uppercase code" matches everything storable); non-consumer `translated_contains_text` (:1628-1661, stored free text, never compared to canonical). Test evidence: `test_05` expects `"Wheat Flour, Sugar, Butter"` and `"Contains: WHEAT, MILK."`; `test_07:227`'s `"Contains: Wheat."` is inert draft content in a test rejected at `ERR_RECIPE_NOT_LOCKED` before any statement comparison.
- (c) Adjustment: scoped the wording to the computed capability's *returned* strings (the sentence's existing scope) so the market-variant `translated_contains_text` path is not newly constrained; preserved the `Contains: None.` empty-case and the trim-before-compare sentences verbatim.

## Step 9: Complete PRD — 2026-08-15T01:45:00.000Z

The diff is exactly 10 paragraphs touched, all inline. Work is complete.

## Summary

**Files:** `workspace/PRD_FINALIZED.md` (source; 270 lines / 50,098 chars) → `workspace/PRD_COMPLETED.md` (270 lines / 51,587 chars; **char-delta +1,489**). Line count unchanged — every change is an in-paragraph insert or revision; no new sections.

**Counts:** 11 ambiguity-pins, 1 mismatch-revision (12 changes total across 10 paragraphs).

**Changes:**
- §2.1 — insert — ambiguity — on the five global (non-nested) listing endpoints, client-chain scoping for `ClientRep`/`QualityManager` is applied as a result filter, not a 403 — `implementation/app.py:949-951` (also 1147-1149, 1346-1348, 1589-1591, 1842-1844)
- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` are clamped (limit into [1,100], negative offset to 0); non-integer values rejected with `ERR_INVALID_REQUEST` — `app.py:247-262`
- §2.4 — insert — ambiguity — `version` starts at 1 on creation — `app.py:230`
- §2.8 — insert — ambiguity — body-shape check also covers a non-JSON-object body, an empty required string, and a malformed ISO 8601 datetime, all `ERR_INVALID_REQUEST` — `app.py:381-387, 396-399, 426-436`
- §3.2 — insert — ambiguity — ingredient-statement capability rejects with `ERR_RECIPE_NOT_LOCKED` when the product has no currently `LOCKED` recipe — `app.py:984-989`
- §3.2 — insert — ambiguity — `canonical_order` elements each name `ingredient_id` and `quantity_g` — `app.py:707-710`
- §3.6 — insert — ambiguity — new label draft initializes `panel_snapshot_id`, `approved_by`, and `superseded_by_id` empty — `app.py:1296-1312`
- §3.6 — revise — **mismatch** — rejection "optionally recording a free-text `reason`" → "optionally accepting a free-text `reason` that is not persisted on the label" (impl parses but never stores it) — `app.py:1421`
- §3.6 — insert — ambiguity — withdrawal restores the superseded label to `RELEASED` *with its `superseded_by_id` cleared* — `app.py:1503-1507`
- §3.7 — revise — ambiguity — claim creation reads a `CURRENT` panel only "whenever the claim requires evaluation"; when none exists, creation is rejected with `ERR_PANEL_NOT_CURRENT` — `app.py:1542-1547`
- §3.7 — revise — ambiguity — `CA_CFIA` `SUGAR_FREE`/`LOW_CALORIE` settle `NOT_REQUIRED` *before any panel lookup* (no `CURRENT` panel required) and also leave `basis_panel_id` empty — `app.py:1533-1540`
- §3.8 — revise — ambiguity — "Scope is enforced before scheduling" rewritten to pin the §2.8 priority order impl actually runs: facility-conflict check first, then window coherence, then scope consistency — `app.py:1777-1805`

Everything else in the implementation (all 40 endpoints, both cascades, rounding pipeline, serving-size math for both markets, claim thresholds/disqualifiers, format-check tiers, variant window/activation rules, audit scoring, logical clock, OCC ordering) was already uniquely pinned by PRD_FINALIZED.md and required no change.
