# Worklog — task_1495_enterprise_risk_management_risk_register

## Step 1: Create Task Directory — 2026-08-13T13:20:00.000Z

Task directory `tasks/task_1495_enterprise_risk_management_risk_register/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE per invocation instructions; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-13T14:25:00.000Z

All three artifacts are written and the final lint verdict is clean:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Summary

**Files written** (under `/home/ubuntu/github/CodingPRD/tasks/task_1495_enterprise_risk_management_risk_register/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys); includes the verbatim `response_envelope` block
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top key `scaffold_corner_design`

**Counts:**
- Entities: **13** (TaxonomyCategory self-referential tree, Risk, RiskAssessment event, Control, RiskControlMapping junction, AppetiteStatement, ToleranceBreach, TreatmentPlan, TreatmentAction, KRI, KRIObservation event, RiskReport, EmergingRisk)
- State machines: **9** (Risk with reassessment + reopen cycles; KRI with parallel lifecycle×breach dimensions; TreatmentPlan with overdue/extend loop; ToleranceBreach with ACCEPTED→OPEN re-open loop; Control review cycle; plus Mapping, Action, Report, EmergingRisk)
- Endpoints: **69** (deliberately above the advisory Expert ceiling of 32 — driven by 15 FKs each requiring a reverse-reachability GET per lint check (f), 9 state machines, and a `/_clock/set_current_utc` test-driving endpoint with the mandated `2026-08-01T00:00:00Z` default)
- Error catalog: **30** codes
- §1.8 difficulty instances: **18** (2 per rule × 9 rules, all differentiation clauses honored — e.g., dual-variant on Risk scoring vs RiskReport aggregation; combinatorial modes (a) diminishing-returns discount vs (b) per-category-round-then-sum; cascades depth-3 (KRI RED → kri_alert → plan priority) and depth-2 (mapping retire → residual → breach) from different triggers; half-open vs closed interval overlap on AppetiteStatement vs RiskReport; cents vs count conserved quantities)
- §1.9 corner instances: **57** (52 active + 5 `excluded_because` stubs), spanning all nine guide sections; 643 total recipe calls lint-verified

**Notable design decisions:**
- All formula-derived asserts were pre-computed and verified in Python before pinning (e.g., residual 9 = ceil(20×(1−0.58)); report heat 2.02 vs 2.01 distinguishes pinned rounding order; PROVISIONAL 56.00 vs FINAL 37.10 divergence).
- Segregation-of-duties role model: plan/appetite approval rejected when approver's X-User-ID equals the proposer/creator (`ERR_SOD_VIOLATION`).
- OCC per §1.2.1 on two true create-with-supersede surfaces (`expected_risk_version` on assessment and plan creation), both exercised by strictly sequential §1.9 tests.
- Validation priority order pins the two tested conflict pairs: state(7) > fiscal(12) and business_constraint(9) > temporal(10).
- The taxonomy cycle rule was made genuinely triggerable by adding `PATCH /categories/{id}` (reparent) rather than leaving an unreachable error code.
- Priority ratchet asymmetry (RED sets plan priority URGENT; NORMAL clears only kri_alert) is pinned as a corner claim to kill a plausible misreading of the cascade.

## Step 3: Copy Shared Files — 2026-08-13T14:26:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1495_enterprise_risk_management_risk_register/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T15:05:00.000Z

## Summary

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_1495_enterprise_risk_management_risk_register/workspace/PRD.md` — 340 lines.

**Section list:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications (11 subsections): 2.1 RBAC · 2.2 API Response Structure (byte-identical verbatim block, verified against `section-2.2-response-structure.md`) · 2.3 Pagination · 2.4 Logical Clock & Time-Driven State Changes · 2.5 Common Resource Properties & Append-Only Event Records · 2.6 Scoring Scales, Bands & Numeric Precision · 2.7 Optimistic Concurrency Control · 2.8 Validation Precedence (12-class ladder) · 2.9 Nested Paths & Referential Integrity · 2.10 Segregation of Duties · 2.11 Cascading Recalculation
- §3 Business Logic (8 subsections): 3.1 Taxonomy & Appetite Framework · 3.2 Risk Registration, Scoring & Assessment Loop · 3.3 Control Library & Risk-Control Mapping (incl. full residual-discount formula in prose) · 3.4 Tolerance Breaches · 3.5 Treatment Plans, Actions & Budget Reservations · 3.6 KRIs & Alert Cascades · 3.7 Emerging Risks & Scenario Analysis · 3.8 Board Reporting & Aggregation
- §4 Endpoint Definitions — 69 rows, 4 columns; every method/path/role-set diffed clean against the scaffold
- §5 Error Code Catalogue — 30 rows, 2 columns; IDs and HTTP statuses match the scaffold exactly

**Coverage audit (all three hard contracts PASS):**
- Contract 1 field coverage: 80 required identifiers (70 entity fields incl. common fields, 46 endpoint input/query identifiers after dedupe) — 80 present in backticks, 0 missing; all 30 state values, all enum values (`INHERENT`/`RESIDUAL`, bands, `ABOVE`/`BELOW`, `PROVISIONAL`/`FINAL`, `STANDARD`/`URGENT`), all 5 role names, and all 30 error IDs appear in §2/§3 prose.
- Contract 2 rule coverage: 12/12 validation-priority classes expressed as an explicit precedence ladder with masking semantics; 2/2 OCC rules (`expected_risk_version` + `ERR_STALE_VERSION`/412 for both assessment-create and plan-create, framed purely in stale-version terms); all 30+ state transitions named as `FROM` → `TO` pairs with preconditions paired to error IDs and every side effect stated (incl. cascades: attest/retire fan-out, RED ratchet, reservation reserve/release, draft auto-supersede, clock sweeps + lazy read evaluation); all 9 calculations rendered as pseudocode-free prose passing the reconstruction test (diminishing-returns discount with 0.90 cap/ceil/floor-1, per-category-round-then-sum aggregation, strict KRI thresholds, promotion threshold 10, rollup 0.00-when-empty); sibling branches (4 RESIDUAL self-transitions, 4 close origins, 3 cancel origins, ABOVE/BELOW, PROVISIONAL/FINAL) rendered at equal density.
- Contract 3 §3 path purity: 487 backticked tokens scanned — 0 paths, 0 bare HTTP methods, 0 method+path combos (endpoints referenced via state-pair framing, role+verb, or capability description).

**Zero-silence decisions (scaffold-implied, pinned in prose):**
1. RESIDUAL from REASSESSMENT — the state machine lists self-transitions only for ASSESSED/TREATMENT/MONITORING, but `ERR_ASSESSMENT_KIND_NOT_ALLOWED` rejects RESIDUAL only from DRAFT/IDENTIFIED/CLOSED; §3.2 pins RESIDUAL as a status-preserving self-transition permitted from all four non-terminal assessed states.
2. Range-error mapping for non-catalogued fields — `coverage_weight`, `weight_factor`, `max_mapped_risks`, `min_observation_interval_days`, `budget_cents`, `treatment_budget_cents` are absent from the `ERR_SCORE_OUT_OF_RANGE` catalog entry; §2.6 pins their violations to `ERR_INVALID_REQUEST` (400).
3. `period_end` before `period_start` → `ERR_INVALID_REQUEST` (§3.8); shared-boundary-counts-as-overlap applied uniformly to draft auto-supersede (scaffold states it only for FINALIZED); create-overlapping-FINALIZED explicitly not rejected at create time.
4. Plan-create ownership anchored to the parent risk's `owner_user_id` (the plan's own `owner_user_id` remains a free payload field for the treatment owner).
5. Multi-KRI `kri_alert` reconciliation — the NORMAL-clear cascade is pinned as subject to the any-ACTIVE-RED-KRI invariant from the field definition.
6. AMBER_BREACH pinned as touching nothing beyond the KRI's own breach dimension; `mapped_active_count` pinned at 0 on control creation; the clock described as an advance-to capability without inventing a backward-set rejection.

The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or referenced.

## Step 5: Generate Unit Tests — 2026-08-13T15:32:00.000Z

All 114 tests collect cleanly, every design instance is covered, all citations are PRD-verbatim, and every docstring ends with a valid Design tag.

## Summary

**Generated output** (both directories under `/home/ubuntu/github/CodingPRD/tasks/task_1495_enterprise_risk_management_risk_register/`):

**`test_helpers/` (10 files, Stage 1)**
- `types.py` — 13 entity TypedDicts (Risk/RiskAssessment/Control/Mapping/Appetite/Breach/Plan/Action/KRI/KRIObservation/Report/EmergingRisk/TaxonomyCategory) + 13 status enums + UserRole; respects common_fields (RiskAssessment/KRIObservation omit `version`/`updated_at`).
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (68 endpoints in PRD §4, including `POST /_clock/set_current_utc`); singleton `api_client` instance.
- `api_errors.py` — `ApiErrorId` enum + `HTTP_STATUS_CODES` map for all 30 errors from PRD §5; registered via `set_error_http_status_map`.
- `assertions.py` — per-entity `assert_*` validators + `assert_risk_budget_invariant` (PRD §3.5 conservation rule).
- `factories.py` — payload factories for every entity; only `source: input` fields.
- `constants.py` — band edges, DISCOUNT_CAP=0.90, PROMOTE_THRESHOLD=10, MAX_PLAN_EXTENSIONS=3, default logical clock 2026-08-01T00:00:00Z.
- `test_users.py` — `TEST_USERS` constants for the 5 opaque roles + `make_<role>_headers(user_id)` builders (identity is `opaque` per PRD §2.1, so user_id is the matching string recorded on the entity).
- `fixtures.py` — composite helpers in 5 tiers (create_category/risk/control/appetite/plan; create_identified/assessed/residual_assessed_risk; create_active_control/mapping; create_approved_appetite/plan; create_in_progress_plan; advance_clock; setup_risk_in_treatment_with_plan; setup_risk_in_monitoring). Identity threading: every fixture that creates a Risk records `owner_user_id` and uses matching `make_risk_owner_headers(owner_user_id)` for downstream owner-only calls; plan approver always differs from proposer (SoD, PRD §2.10).
- `__init__.py` — barrel export of framework generics + all PRD-specific symbols.

**`test_suite/` (14 test files + conftest.py, Stage 2)**
- `conftest.py` — session-scoped `api` fixture + per-role header fixtures.
- 114 test functions across 14 files, organized by concern (entities, state machines, calculations, validations, RBAC, breach workflows, temporal overlaps, compensating invariants, priority conflicts, cascades, endpoints, non-linear state machines, boundary precision, misc errors).

**Coverage audit (vs. the two design indices — the only test source)**
- **Queue A (Difficulty)**: 18/18 instances × ≥2 tests each = 36 tests tagged `Design: Difficulty/<rule_id>/<instance>`.
- **Queue B (Corner)**: 52/52 non-stub instances × ≥1 test each = 78 tests tagged `Design: Corner/<section>/<instance>`. The 5 `excluded_because:` stubs in `errors/` (window_overlap, report_period_overlap, budget_exceeded, control_not_active, open_breach_blocking) were correctly NOT translated — their `difficulty_instance` cross-references all resolve to real queue-A instances which own the assertion.
- 0 unexpected/orphan tags; 0 untagged tests; 0 dual-tagged tests.

**PRD-first filter application**
- **All 70 non-stub instances passed both filter conditions** (verbatim PRD coverage + unique derivability). No skips required. Every test docstring carries a verbatim-quoted PRD sentence (C1/C2/C3) — verified programmatically: a distinctive ≥8-word substring of each quote greps cleanly against PRD.md.
- Instances that the silence-pattern table would normally flag (e.g., `plan_approve_state_beats_business_fiscal`, `appetite_constraint_range_beats_temporal_overlap`) were emitted because PRD §2.8 explicitly enumerates the precedence ladder and PRD §3.5 explicitly says "three guards evaluated in precedence order: the risk-state guard first... then segregation of duties... and finally the budget guard, always last" — so priority is PRD-covered, not scaffold-only.
- OCC stale-version tests use the sequential form (fresh version captured → mutation advances version → second write with stale version rejected), which PRD §2.7 pins uniquely.
- All numeric literal expectations (residual 9, heat totals 56.00/37.10/2.02, scenario_score 12/18/6, progress 66.67, etc.) are uniquely derived from PRD §3 formulas and the recipes' pinned inputs.

**Notable design decisions**
1. **Fixture strategy**: 5-tier composite helpers in `fixtures.py`. The heaviest fixture (`setup_risk_in_monitoring`) walks the only PRD-legal path to MONITORING (create → submit → INHERENT → RESIDUAL → plan PROPOSED → APPROVED → enter-treatment → plan CANCELLED → monitor). All fixtures use `get_success_data()` so setup failures surface as setup errors, not assertion noise.
2. **Role-header model**: All 5 roles have `identity: opaque` (PRD §2.1: "X-User-ID is an opaque operator identifier that is not the `id` of any persisted entity"). Ownership/SoD checks compare X-User-ID against recorded `owner_user_id` / `proposer_user_id` / `created_by` strings, so `TEST_USERS` constants carry stable user IDs (`user_owner_1`, `user_rm_1`, `user_rm_2`, etc.) and factories thread the same ID through entity payloads. For SoD tests I added a `USER_DUAL` constant: the same person acting first as RiskOwner (creator) then as RiskManager (approver), which violates SoD because X-User-ID matches `proposer_user_id` regardless of role.
3. **OCC capture strategy**: Fixtures re-read the risk immediately before each OCC-guarded write (`get_risk_version()` helper) and pass that fresh `version` as `expected_risk_version`. Tests that exercise staleness capture a version, perform a version-bumping mutation, then replay the stale value — deterministic without `run_race` (per the SKILL's note that OCC's commit-time check makes either form deterministic).
4. **Breach generation**: Breaches are created organically (appetite tolerance 5 with risk inherent 20 → RESIDUAL assessment → residual 20 ≥ 5 → OPEN breach). The `create_breach_via_residual` helper centralizes this; `get_risk_breaches` lists them. ACCEPTED-breach review-by-reopen uses `advance_clock` to the exact `review_by` instant.
5. **Rounding-order test (Difficulty/combinatorial_formula/report_heat_per_category_rounding_order_mode_b)**: Two categories with `weight_factor 1.005` each containing one risk with residual 1. Per-category round-half-up produces 1.01 each; total 2.02 (sum-then-round would yield 2.01). Asserts both the per-category `heat_score` and the `heat_score_total`, falsifiable against the wrong rounding order.

## Step 6: Generate Implementation — 2026-08-13T15:50:00.000Z

Done. Summary below.

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1495_enterprise_risk_management_risk_register/workspace/implementation/`)

- `start.sh` — executable launcher; guards `pip install` behind a `python3 -c "import flask"` check (no-op on per-test reboots), then `exec python3 app.py` in the foreground
- `requirements.txt` — `flask>=2.2`
- `app.py` — Flask entry point; binds `0.0.0.0:$PORT` (default 10000); registers blueprints and error handlers (ApiError → envelope; 404/405 → enveloped `ERR_NOT_FOUND`)
- `db.py` — in-memory store (13 dicts keyed by id), monotonic insertion sequence, logical clock initialized to exactly `2026-08-01T00:00:00Z`; no seeding anywhere
- `errors.py`, `response.py`, `middleware.py`, `util.py` — ApiError; `meta`/`response_type`/`data` envelope with `limit`/`offset`/`total_count`/`has_more` pagination in meta (default 10/0, min 1, max 100); `X-User-ID`/`X-User-Role` auth with the five exact role names; ISO8601 3-fractional-digit formatting, strict typed body validators, Decimal coercion
- `services.py` — scoring/breach/cascade/aggregation engine + all serializers
- `routes/` — 10 blueprints: `categories`, `risks`, `controls` (incl. flat `/control-mappings/{id}/approve|retire`), `appetite`, `plans`, `actions_breaches`, `kris`, `reports`, `emerging`, `clock`

## Endpoint count

**69 endpoints** implemented — the complete scaffold table: 9 category, 16 risk, 7 control, 2 mapping, 5 appetite, 9 plan, 1 action, 4 breach, 6 KRI, 3 report, 6 emerging-risk, 1 clock.

## Key architectural decisions

- **Logical clock & lazy sweeps**: clock lives in `db._logical_clock`; `POST /_clock/set_current_utc` sets it and eagerly sweeps (IN_PROGRESS plans with `clock > due_date` → OVERDUE; ACCEPTED breaches with `clock >= review_by` → OPEN). The same checks run lazily on single-GET of a plan/breach. Wall clock is used only for `created_at`/`updated_at`/`meta` timestamps.
- **Validation priority ordering**: each view body sequences checks explicitly per the §2.8 ladder: auth (401) → RBAC (403) → body shape (400) → path/body FK existence left-to-right (404) → ownership (403) → OCC `expected_risk_version` (412) → state guards incl. `ERR_ASSESSMENT_KIND_NOT_ALLOWED`/`ERR_KRI_NOT_ACTIVE` (409) → SoD (422) → domain ranges (422) → temporal (409/422/400) → referenced-state guards (409) → capacity/budget last (422). PRD-mandated asymmetries honored: monitor checks breach-then-plan, close checks plan-then-breach; mapping approve checks control-state before capacity.
- **Calculations**: all-Decimal residual scoring (contributions sorted desc, tie by mapping creation seq; `acc += c*(1-acc)`; 0.90 cap; `ceil` with floor 1); `round_half_up` for progress_pct (2dp), scenario_score (0dp), and per-category heat (2dp, rounded before summation); strict KRI threshold comparisons; closed-interval overlap for reports vs half-open `[from, to)` overlap for appetite windows.
- **Cascades**: mapping approve/retire and control attest/retire recompute residual + run breach evaluation per affected risk (only when inherent present), bumping each touched risk/control/mapping version; KRI RED sets `kri_alert=true` + bumps version on category risks in ASSESSED/TREATMENT/MONITORING/REASSESSMENT and ratchets their non-terminal plans to URGENT (one-way); NORMAL clears alerts only when no other ACTIVE red KRI remains in the category; report creation auto-CANCELS overlapping older DRAFTs; promotion materializes a DRAFT Risk with `source_emerging_risk_id`.
- **Derived fields computed at read**: `available_treatment_cents`, `mapped_active_count`, `current_tolerance_score` (via the effective APPROVED window at the current logical clock) — always consistent, no drift.
- **Append-only events**: RiskAssessment/KRIObservation carry only `id` + `created_at` (no `updated_at`/`version`).

## Boot smoke test result

Booted via `bash start.sh` on a fresh port: store verified empty (`/categories` and `/risks` return `[]` with pagination meta), POST `/categories` → 201 with full envelope, GET `/categories/{id}` → 200 round-trip, auditor write → 403 `ERR_FORBIDDEN`, missing headers → 401 `ERR_UNAUTHENTICATED`. A 56-assertion end-to-end suite passed from a fresh boot, covering OCC 412s, owner/SoD rejections, inherent/residual scoring, breach create/dedupe/ack/accept/clock-reopen, mapping residual discount (20 → 10 at 50% effectiveness), KRI red/normal cascade, plan budget reservation/release, overdue sweep + extend, progress rollup (50.0 → 100.0), report provisional (40.0) vs final (20.0) aggregation with draft supersede on shared boundary, and emerging-risk promote threshold/force paths. The single suite "FAIL" line was a bug in my ad-hoc test script itself (it expected `ERR_OBSERVATION_TOO_SOON` for an observation 1 second ahead of the logical clock; 422 `ERR_OBSERVATION_IN_FUTURE` is the correct ladder-ordered response — verified by hand).

## Step 7: Test-Fix Diagnostic Loop — 2026-08-13T16:10:00.000Z

Ran the 8-round parallel stability sweep (`--isolation per-test-server`) three times.

**Iteration 1**: 18/114 failing, identical across all 8 rounds. All diagnosed as test-side defects; implementation was PRD-faithful in every case:
- 11 KRI tests posted observations timestamped after the default logical clock (2026-08-01T00:00:00Z) without advancing it first; the implementation correctly rejected them with ERR_OBSERVATION_IN_FUTURE (PRD §3.6). Fixed by calling `advance_clock("2026-08-02T00:00:00Z")` in the affected `_build` helpers (test_03, test_10 ×2 classes, test_12, test_13) — same pattern the passing TestKriObservationGap already used.
- TestMappingRetireCascade + TestAppetiteBreachInclusiveGreaterEqual approved the appetite statement before the mappings, so the first mapping approval recomputed residual 12 ≥ tolerance and opened a breach mid-setup (PRD §3.3 cascade), defeating each scenario's premise. Fixed by approving the appetite after mapping approvals, before the residual assessment (no APPROVED statement ⇒ "no breach is possible", PRD §3.4).
- 3 NameErrors: missing `create_identified_risk` (test_10) and `create_residual_assessment` (test_11) imports.
- test_extend_returns_to_in_progress_and_increments asserted exact-string equality on `due_date`; PRD pins the 3-fractional-digit serialization only for created_at/updated_at, so the assertion was relaxed to an instant comparison (STEP 1c partial coverage — kept the covered "sets due_date to new_due_date" semantics).

**Iteration 2**: 1/114 failing in all 8 rounds. TestKriBelowDirection::test_equal_to_red_is_not_breach_under_below asserted NORMAL for value == red under a BELOW indicator, contradicting PRD §3.6 ("AMBER_BREACH when it is strictly less than the amber threshold and at least the red threshold" — 20 < 40 and 20 ≥ 20 ⇒ AMBER_BREACH; equality is only excluded from the RED band). Fixed the assertion to AMBER_BREACH, matching the ABOVE twin test.

**Iteration 3**: all 8 rounds clean, 114/114 each. No test deletions were required — every failure traced to a test-artifact defect, none to PRD silence or unique-derivability collapse. No implementation changes were needed.

## Step 7: Run Tests and Iterate — 2026-08-13T16:10:00.000Z

All 8 rounds pass 114/114. Final summary:

## Summary

**Iterations run:** 3 (each a full 8-round parallel sweep, `--isolation per-test-server`, 114 tests/round)

**Result:** Iteration 3 — all 8 rounds clean, 114/114 passed in every round.

**Tests deleted:** None. Every failure traced to a test-artifact defect; no PRD-silence or unique-derivability collapses found.

**Fixes applied to `test_helpers/`:** None — fixtures, factories, and role-header builders were all PRD-consistent.

**Fixes applied to `test_suite/`** (all test bugs; the implementation was PRD-faithful in every case):

1. **11 KRI observation tests — missing clock advance** (`test_03_calculations.py` `TestKriBelowDirection._below_kri`, `test_13_boundary_precision.py` `TestKriRedThresholdStrictInequality._build`, `test_12_non_linear_state_machine.py` `TestKriParallelLifecycleAndBreachDimensions._build_active_kri`, `test_10_cascades.py` `TestKriRedCascade._build` and `TestKriAlertRatchetAsymmetry._build`): tests posted observations timestamped `2026-08-01T01:00:00Z+`, which lie after the default logical clock (`2026-08-01T00:00:00Z`), so the implementation correctly rejected them with `ERR_OBSERVATION_IN_FUTURE` (PRD §3.6). Added `advance_clock("2026-08-02T00:00:00Z")` to each setup — the same pattern the passing `TestKriObservationGap` already used.

2. **Mid-build breach ordering** (`test_10_cascades.py` `TestMappingRetireCascade._build`, `test_13_boundary_precision.py` `TestAppetiteBreachInclusiveGreaterEqual.test_residual_equal_to_tolerance_creates_breach`): both approved the appetite statement *before* the control mappings, so the first mapping approval recomputed residual 12 ≥ tolerance and opened a breach mid-setup (PRD §3.3 cascade: approval recomputes residual and runs breach evaluation). Verified empirically against the live server. Reordered so appetite approval happens after mapping approvals and before the residual assessment (PRD §3.4: with no APPROVED statement "no breach is possible").

3. **NameError ×3** (`test_10_cascades.py`, `test_11_endpoints.py`): missing imports — added `create_identified_risk` (test_10) and `create_residual_assessment` (test_11) to the test_helpers import lists.

4. **`due_date` serialization assertion** (`test_02_state_machines.py` `test_extend_returns_to_in_progress_and_increments`): exact-string equality `"2026-09-30T00:00:00Z"` is not uniquely derivable — PRD pins the 3-fractional-digit format only for `created_at`/`updated_at`, so a conformant implementation returning `...00.000Z` failed. Relaxed to an instant comparison via a `_parse_instant` helper (STEP 1c partial-coverage correction; the covered assertions — status `IN_PROGRESS`, `extension_count` 1, due_date set to the requested instant — are preserved).

5. **PRD-contradicting KRI assertion** (`test_03_calculations.py` `test_equal_to_red_is_not_breach_under_below`): asserted `NORMAL` for value == red under a BELOW indicator. PRD §3.6 uniquely determines `AMBER_BREACH` ("strictly less than the amber threshold and at least the red threshold" — 20 < 40 and 20 ≥ 20); equality with red is excluded only from the RED band. Corrected to `AMBER_BREACH`, matching the ABOVE twin test.

**Fixes applied to `implementation/`:** None — the implementation was PRD-correct in every failure investigated (breach-on-approve cascade, `ERR_OBSERVATION_IN_FUTURE` guard, AMBER-at-red-equality evaluation, 3-fractional-digit datetime rendering).

## Step 8: Finalize PRD — 2026-08-13T16:18:00.000Z

Done. The diff is a single inserted paragraph.

## Summary

**Line counts:** PRD.md = 340 lines, PRD_FINALIZED.md = 342 lines (+2 lines, +0.59%).

### Changes (one edit total)

- **§2.5 (Common Resource Properties and Append-Only Event Records) — insert** — added a closing paragraph pinning that the three-fractional-digit rendering is uniform across the API: every datetime-valued response field (`effective_from`, `effective_to`, `review_by`, `due_date`, `last_observation_at`, `observed_at`, `period_start`, `period_end`, clock endpoint's `current_utc`, envelope's `api_request_timestamp`) is ISO 8601 UTC with exactly three fractional digits and a `Z` suffix, and unset datetime fields render as null — `implementation/util.py:24-27` (`fmt_dt`, sole formatter), `implementation/services.py:348-349,366,379,416,429,438-439`, `implementation/routes/clock.py:21`, `implementation/response.py:11`. Traces to step_7_diff item 4 (`due_date` exact-string assertion not uniquely derivable; impl returned `...00.000Z`).

### Items requiring no PRD edit (PRD already determines behavior; pure test bugs)

- **Item 1 (11 KRI observation tests, `ERR_OBSERVATION_IN_FUTURE`)** — PRD §3.6 (line 209) already pins the futurity guard verbatim and §2.4 pins the clock's initial instant `2026-08-01T00:00:00Z`; impl `routes/kris.py:103-115` matches PRD exactly.
- **Item 2 (mid-build breach on mapping approval)** — PRD §3.3 (line 177) already pins "recomputes the risk's residual score and runs appetite-breach evaluation" on mapping approval, and §3.4 (line 183) pins "when no such statement exists, no breach is possible"; impl `routes/controls.py:159` → `services.py:111-117` (`cascade_recompute_risk`) → `services.py:86-108` (`evaluate_breach`) matches.
- **Item 3 (NameError ×3)** — missing test imports; no behavioral content.
- **Item 5 (KRI value == red under BELOW)** — PRD §3.6 (line 211) uniquely determines `AMBER_BREACH` ("strictly less than the amber threshold and at least the red threshold"); impl `services.py:142-154` matches PRD; the test contradicted the PRD.

### Pre-edit search log (for the single edit)

- **(a) Subject:** response rendering format of datetime-valued fields.
- **(b) Impl paths enumerated and read/grepped:** `implementation/util.py:24-27` (`fmt_dt` — confirmed the sole datetime formatter via repo-wide grep for `isoformat|strftime|%Y-%m-%d`); all 13 serializers in `implementation/services.py` read in full (lines 255-469) covering category, risk, assessment, control, mapping, appetite statement, breach, plan, action, KRI, observation, report, emerging risk; `implementation/routes/clock.py:21` (`current_utc`); `implementation/response.py:11` (`api_request_timestamp`); `implementation/routes/plans.py:140-152` (extend stores the parsed `new_due_date`, which serializes through `fmt_dt`); grep of all route files confirmed no serializer bypasses `services.py`.
- **(c) Wording adjustments:** (i) widened from naming only `due_date` (the Step 7 site) to a uniform rule covering every datetime-valued response field, since all flow through the same `fmt_dt` path and naming one would falsely imply the others differ; (ii) added "a datetime field that has no value renders as null" to stay consistent with the two nullable paths — `review_by` (`services.py:366`) and `last_observation_at` (`services.py:416`); (iii) included the `Z` suffix, matching `fmt_dt`'s `%03dZ` and the existing §2.2 envelope example `2025-05-24T10:30:00.123Z`.

Output file: `/home/ubuntu/github/CodingPRD/tasks/task_1495_enterprise_risk_management_risk_register/workspace/PRD_FINALIZED.md`

## Step 9: Complete PRD — 2026-08-13T16:45:00.000Z

All 20 changes applied cleanly. The work is complete.

## Summary

**Source**: `PRD_FINALIZED.md` (342 lines, 53,431 chars) → `PRD_COMPLETED.md` (344 lines, 55,569 chars); char-delta +2,138. Only `PRD_COMPLETED.md` was edited (copied from `PRD_FINALIZED.md` first).

**Counts**: 19 ambiguity-pins, 1 mismatch-revision.

**Changes**:

- §2.1 — revise — mismatch — §2.1 claimed the server stamps the caller's `X-User-ID` as `owner_user_id` on Risk/TreatmentPlan; impl takes `owner_user_id` from the request body and server-stamps only `proposer_user_id` (plan) and `created_by` (appetite) — `implementation/routes/risks.py:41`, `implementation/routes/plans.py:293,313`, `implementation/routes/appetite.py:60`
- §2.2 — insert — ambiguity — pinned routing/plumbing fallbacks: unmatched route → `ERR_NOT_FOUND` 404, wrong method → `ERR_NOT_FOUND` body at 405, unhandled failure → `ERR_INTERNAL` 500 — `implementation/app.py:25-37`
- §2.3 — insert — ambiguity — out-of-range/non-integer `limit`/`offset` rejected with `ERR_INVALID_REQUEST` — `implementation/util.py:140-148`
- §2.3 — insert — ambiguity — defined `has_more` as `offset + limit < total_count` — `implementation/util.py:151-156`
- §2.4 — revise — ambiguity — clock endpoint applies any target unconditionally (backwards accepted) and runs both sweeps on every call — `implementation/routes/clock.py:13-21`, `implementation/db.py:49-50`
- §2.5 — revise — ambiguity — `version` starts at 1 on creation — `implementation/services.py:24-27`
- §2.8 item 3 — insert — ambiguity — naive datetimes interpreted as UTC; unrecognized extra body fields ignored — `implementation/util.py:42-44,51-57`
- §3.1 — insert — ambiguity — reparenting with null `parent_category_id` permitted, detaches to root — `implementation/routes/categories.py:71-89`
- §3.1 — insert — ambiguity — appetite window-direction check evaluated only after category-existence and score-range checks pass — `implementation/routes/appetite.py:47-55`
- §3.2 — insert — ambiguity — assessment record also exposes `likelihood`/`impact`/`notes` (submitted values for INHERENT; null likelihood/impact for RESIDUAL) — `implementation/routes/risks.py:228-238`, `implementation/services.py:294-306`
- §3.2 — insert — ambiguity — reopen `reason` accepted but not persisted — `implementation/routes/risks.py:116-119`
- §3.4 — revise — ambiguity — whitespace-only breach-accept rationale rejected with `ERR_INVALID_REQUEST` — `implementation/routes/actions_breaches.py:102-104`
- §3.5 — insert — ambiguity — plan-reject `reason` accepted but not persisted — `implementation/routes/plans.py:68-81`
- §3.5 — insert — ambiguity — plan-cancel `reason` accepted but not persisted — `implementation/routes/plans.py:118-133`
- §3.5 — insert — ambiguity — plan `version`/`updated_at` change only when recomputed `progress_pct` differs (first action leaves version untouched) — `implementation/services.py:124-135`
- §3.6 — insert — ambiguity — NORMAL-result alert clear leaves already-clear risks unmodified — `implementation/services.py:169-179`
- §3.7 — insert — ambiguity — `stress_factor` outside [0.5, 3.0] rejected with `ERR_SCORE_OUT_OF_RANGE` (PRD previously gave no error code) — `implementation/routes/emerging.py:43-45`
- §3.7 — revise — ambiguity — promotion force-rationale must be non-empty after trimming whitespace — `implementation/routes/emerging.py:102`
- §3.7 — insert — ambiguity — promoted Risk carries over only `category_id`/`title`; `description` null and `treatment_budget_cents` 0 — `implementation/routes/emerging.py:108-125`
- §3.7 — insert — ambiguity — dismiss `reason` accepted but not persisted — `implementation/routes/emerging.py:130-140`

Output file: `/home/ubuntu/github/CodingPRD/tasks/task_1495_enterprise_risk_management_risk_register/workspace/PRD_COMPLETED.md`

## Post-Step-9: Final verification sweep — 2026-08-13T16:48:00.000Z

The Step 7 subagent's final sweep results files were not retained on disk after its exit, so the orchestrator re-ran the full 8-round parallel stability sweep (same command, `--isolation per-test-server`, 114 tests/round) after Step 9 completed, to confirm the final artifact set (implementation untouched since Step 7's green sweep; PRD_FINALIZED.md and PRD_COMPLETED.md are docs-only) and to leave `results.{1..8}.json` in place per the output contract.

Result: all 8 rounds passed 114/114 (0 failed, 0 errors, 0 skipped in each round; ~142s per round). `workspace/implementation/results.1.json` through `results.8.json` regenerated and retained.
