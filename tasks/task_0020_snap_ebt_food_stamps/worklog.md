# Worklog — task_0020_snap_ebt_food_stamps

## Step 1: Create task directory — 2026-05-27T00:00:00Z

Pre-created by user: `./tasks/task_0020_snap_ebt_food_stamps/workspace/`. Skipped NNNN auto-allocation per user instruction.

## Step 2: Generate scaffold — 2026-05-27T12:27:00Z

Lint is clean. Three files written:
- `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0020_snap_ebt_food_stamps/SCAFFOLD.yaml`
- `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0020_snap_ebt_food_stamps/SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0020_snap_ebt_food_stamps/SCAFFOLD_CORNER_DESIGN.yaml`

**Scaffold generated for SNAP/EBT Food Stamps benchmark** (Expert tier; pricing_engine + compliance_audit archetypes).

**§1.1 Entities (11):** Household, HouseholdMember, Application, EBTCard, MonthlyAllotment, EligibleItemCategory, PurchaseTransaction, FraudFlag, ABAWDWaiver, SystemClock, EmergencyAllotmentProclamation

**§1.2 State machines (8):** Application, Household, EBTCard, MonthlyAllotment, FraudFlag, ABAWDWaiver, PurchaseTransaction, EmergencyAllotmentProclamation

**§1.2.1 Concurrency rules (2):** issue-allotment-stale-household (Household OCC), substantiate-fraud-stale-flag (FraudFlag OCC)

**§1.3 Calculations (3):** net_monthly_income (with BENEFIT_CALC vs LIMIT_CHECK variants), monthly_allotment (with STANDARD vs EMERGENCY variants, tiered_pricing), fraud_velocity_score (aggregation with pinned trigger-row inclusion order)

**§1.4 Validations (21):** ordered by priority spanning auth → existence → state → cross-entity state → business_safety → business_referential → business_temporal → business_fiscal → business_constraint → OCC

**§1.5 Endpoints (54):** CRUD + action endpoints across all 9 business resources, plus `/snap/_clock` test-driving endpoints; every FK has reverse-reachability GET

**§1.6 Errors (22):** ERR_UNAUTHENTICATED, ERR_FORBIDDEN, ERR_NOT_FOUND, ERR_PARENT_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_HOUSEHOLD_NOT_ACTIVE, ERR_CARD_NOT_ACTIVE, ERR_NOT_CLAIMING_INVESTIGATOR, ERR_DUPLICATE_CASE_NUMBER, ERR_DUPLICATE_ALLOTMENT_MONTH, ERR_DUPLICATE_WAIVER_QUARTER, ERR_DUPLICATE_PROCLAMATION, ERR_BENEFIT_MONTH_IN_PAST, ERR_ISSUANCE_TOO_EARLY, ERR_INCOME_LIMIT_EXCEEDED, ERR_ABAWD_REQUIREMENT_UNMET, ERR_ALL_ITEMS_INELIGIBLE, ERR_INVALID_LINE_ITEMS, ERR_OUT_OF_STATE_BLOCKED, ERR_STALE_HOUSEHOLD_VERSION, ERR_STALE_FRAUDFLAG_VERSION

**§1.7 Roles (7):** Caseworker (opaque), Applicant (entity_backed:Household), Cardholder (entity_backed:Household), BenefitIssuer (opaque), FraudInvestigator (opaque), Merchant (opaque), PolicyAdmin (opaque) — peer_roles model

**§1.8 Difficulty design:** 9 rule_ids × 2 instances each = **18 instances** (all rules satisfy their §0.5 differentiation clauses; all literal assertions pre-computed against the formulas)

**§1.9 Corner design:** 8 sections, **31 instances total** (29 active test recipes + 2 excluded_because stubs that cite §1.8 instances). Sections: entities (7), state_machines (4 incl. 1 stub), calculations (3), validations (10 incl. 1 stub), endpoints (2), errors (1), rbac (2), cross_cutting_complexity_layers (2 OCC)

**Lint verdict:**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
Coverage: 54 endpoints, 11 entities, 18 §1.8 instances, 29 §1.9 instances, 379 calls scanned.
```

## Step 3: Copy INSTRUCTION.md — 2026-05-27T12:28:00Z

Copied `/Users/uni/Desktop/吉/project/custom_prd_bench/INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-05-27T12:35:00Z

All 22 error IDs appear at least twice (table + prose) and no fuzzy hedge words leaked into the document. All Hard Contracts pass.

**PRD line count:** 300 lines

**Section structure:**
- §1 Introduction (2 paragraphs — system context, then scope/role-blast-radius framing)
- §2 Global Specifications (10 subsections): 2.1 RBAC, 2.2 Response Structure (verbatim from canonical), 2.3 Pagination, 2.4 Common Resource Properties, 2.5 OCC, 2.6 Nested Path Resolution, 2.7 Money/Time/Precision, 2.8 Validation Priority & Evaluation Order, 2.9 Hierarchical Consistency & Cascades, 2.10 Errors & Trigger Surfaces
- §3 Business Logic (10 subsections): 3.1 Household Intake & Members, 3.2 Application Lifecycle, 3.3 ABAWD Waivers, 3.4 Net Income / Allotment / Emergency Supplements (combined calculation home), 3.5 Allotment Issuance & Adjustment, 3.6 EBT Card Lifecycle, 3.7 Household Lifecycle (suspend/reinstate/terminate), 3.8 Eligible Categories & Purchase Auth/Settle, 3.9 Fraud Monitoring & Velocity, 3.10 Emergency Proclamations & Test Clock
- §4 Endpoint Definitions (54 endpoints in 4-column table)
- §5 Error Code Catalogue (22 errors in 2-column table)

**Hard Contract reports:**

```
Contract 1 — Field coverage check:
- entities[].fields: 47 required, 47 present, 0 missing
- endpoints[].request_body/input: covered (expected_household_version, expected_fraudflag_version, to_iso8601, line_items keys category_code/amount_cents/quantity all present in §3.5/§3.9/§3.8/§3.10)
- pagination params: limit, offset present in §2.3
Status: PASS
```

```
Contract 2 — Rule coverage check:
- validations[] with priority: 21 checked, 21 expressed (§2.8 enumerates the full ordering and notes earlier-rules-mask-later behavior), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id + http_status all named in §2.5 and reiterated at §3.5 / §3.9), 0 missing
- state_machines[].transitions: 28 checked across 8 machines, 28 fully expressed in §3, 0 missing
- calculations[]: 3 checked (net_monthly_income with BENEFIT_CALC + LIMIT_CHECK variants, monthly_allotment with STANDARD + EMERGENCY variants, fraud_velocity_score with mandatory evaluation_order pinning), 3 fully expressed in precise narrative (no pseudocode, no fuzzy words), 0 missing
- validations[] conditions: 21 checked, 21 matchable to error_id via §2/§3 narrative, 0 missing
- endpoints[].side_effects / applies_to: cascade chains (approval, suspend, reinstate, terminate, replace, settle, proclamation activate) fully described including secondary effects (version bumps, updated_at, cascade link numbering preserved), 0 missing
- entities[].fields[] structured content: defaults (heap_recipient=false, monthly_*_income=0, disabled=false, min_supplement_cents=9500), enums (state_code, relationship, status enums for every entity, trigger_rule), constraints (case_number regex, quarter regex, pan_last4 4-numeric, county_unemployment_pct range/precision, category code regex) all reconstructible from prose, 0 missing
- sibling-branch symmetry: ABAWDWaiver approve/deny/revoke equal density; Application approve/deny/expire equal density; FraudFlag substantiate/dismiss equal density; EBTCard cascade-to-CANCELLED treated uniformly across the three pre-states; 0 asymmetric
Status: PASS
```

```
Contract 3 — Path purity check (§3 only):
- backtick tokens scanned in §3
- tokens starting with `/`: 0
- bare HTTP-method tokens (POST/GET/PUT/PATCH/DELETE/OPTIONS): 0
- method+path combined tokens: 0
Status: PASS
```

**Scaffold elements deliberately restructured (not omitted):**
- Calculation tables rendered as continuous prose (§3.4 income/allotment; §3.9 velocity) rather than separate spec blocks — SUA tier table, max-allotment tier table, NET_INCOME_LIMIT_BY_SIZE table, velocity constants woven in with explicit per-size numeric values.
- `validations[].priority` rendered as a single enumerated paragraph in §2.8 rather than a table; ordering preserved.
- Cascade chains described with explicit "cascade link N of …" framing inside relevant lifecycle subsections rather than collected centrally.
- `EligibleItemCategory` and `SystemClock` explicitly called out as `common_fields: false` cases in §2.4.

**Zero-Silence Rule concerns flagged:** None. Items that required care and got explicit coverage:
- The `OUT_OF_STATE` "first-occurrence raises flag, subsequent occurrences block" two-step rule (§3.8).
- Mandatory evaluation_order pinning for velocity scoring (write SETTLED first, then re-query so trigger row IS included) — §3.9.
- `BENEFIT_CALC` vs `LIMIT_CHECK` SUA-omission asymmetry — §3.4 with directional inequality.
- CERTIFIED→ACTIVE auto-advance in same request — §3.2.
- Round-then-subtract ordering mandate for 30%-of-net step — §3.4.
- `decision_reason` shared field name between Application and ABAWDWaiver — both contexts give the field its semantics.

## Step 5: Generate unit tests — 2026-05-27T13:00:00Z

**Stage 1 (`test_helpers/`) — 9 files:**
- `__init__.py` — barrel exports (framework + PRD-specific)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint, `PREFIX="/snap"`
- `api_errors.py` — `ApiErrorId` enum + `HTTP_STATUS_CODES` map for all 22 errors, registered with framework
- `assertions.py` — per-entity assertions; `assert_lighter_fields` enforces PRD §2.4's id+created_at-only rule for `EligibleItemCategory`/`SystemClock`
- `constants.py` — domain thresholds from PRD §3.4 / §3.9
- `factories.py` — payload factories, input-fields only
- `fixtures.py` — composite setup helpers in 9 tiers (clock, single-entity, application workflow, household-to-ACTIVE, fraud-flag substantiate, purchase create/settle, allotment create/issue/adjust, proclamation, ABAWD); identity threading for entity_backed roles
- `test_users.py` — shared TEST_USERS + `make_applicant_headers()` / `make_cardholder_headers()` per-instance builders
- `types.py` — entity TypedDicts; lighter entities (`EligibleItemCategory`, `SystemClock`) omit `updated_at`/`version`

**Stage 2 (`test_suite/`) — 14 test files + conftest, 65 test functions:**

| File | Tests | Covers |
|------|------:|--------|
| test_01_household_intake.py | 6 | Corner/entities (6) |
| test_02_lighter_entities.py | 2 | Corner/entities + Corner/endpoints (PRD §2.4 lighter) |
| test_03_application_lifecycle.py | 7 | Difficulty/transitive_cascade/approval, Difficulty/dual_variant_calc/net_income, Corner/validations/abawd, Corner/state_machines/reinstate, Corner/rbac/applicant |
| test_04_household_cascades.py | 9 | Difficulty/non_linear/suspend_reinstate, Difficulty/transitive_cascade/suspend, Difficulty/compensating_invariant ×2, Corner/state_machines/terminate |
| test_05_ebt_cards.py | 4 | Difficulty/cross_entity_state_dependency/card_activate, Difficulty/resource_temporal_overlap/replace_abuse |
| test_06_monthly_allotment_calculations.py | 7 | Difficulty/dual_variant_calc/standard_emergency, Difficulty/combinatorial_formula/round_then_subtract, 3 Corner/calculations |
| test_07_monthly_allotment_lifecycle.py | 5 | Difficulty/resource_temporal_overlap/per_month_uniqueness, 2 Corner/validations, Corner/CCL/occ_household |
| test_08_purchases_and_velocity.py | 9 | Difficulty/combinatorial_formula/velocity_trigger, Difficulty/boundary_precision/velocity_count, Difficulty/cross_entity_state_dep/settle, 3 Corner/validations |
| test_09_fraud_flags.py | 4 | Difficulty/non_linear/fraud_branching, Corner/state_machines/not_claiming, Corner/CCL/occ_fraudflag |
| test_10_validation_priority.py | 4 | Difficulty/priority_pair × 2 |
| test_11_rbac_and_errors.py | 2 | Corner/errors/missing_role, Corner/rbac/merchant_can't_create |
| test_12_endpoints_meta.py | 1 | Corner/endpoints/list_pagination_meta |
| test_13_abawd_waivers.py | 3 | Difficulty/boundary_precision/abawd_county_10, Corner/validations/duplicate_waiver |
| test_14_emergency_proclamations.py | 2 | Corner/validations × 2 (duplicate_case_number, duplicate_proclamation) |

**Queue A (Difficulty) — 18 instances enumerated, 18 emitted, 0 skipped.** Each instance carries exactly 2 distinct tests asserting different facets.

**Queue B (Corner) — 31 instances enumerated, 29 non-stub emitted, 2 stubs deliberately not translated:**
- `state_machines/approve_already_approved_application_returns_invalid_state` — STUB, excluded_because cites Difficulty/priority_pair_validation_conflict/state_beats_business_fiscal_on_double_approve
- `validations/priority_dual_failure_state_vs_business_fiscal_on_approve` — STUB, excluded_because cites the same Difficulty instance

**Stage 1 audit:** all 18 difficulty + 29 non-stub corner instances mapped; stubs resolve cleanly. No invented tests; no PRD-uncovered claims.
**Stage 2 audit:** all 65 functions tagged exactly once; no skip/skipif/xfail; no scaffold/§ references.
**PRD-citation pass:** all docstring citations survive literal grep of PRD.md.

**Numbers:** 9 helpers files / 14 test_suite files (+ conftest) / 65 test functions (36 Difficulty + 29 Corner).

## Step 6: Generate Flask implementation — 2026-05-27T13:10:00Z

**Files created (20 total):**
1. `start.sh` — bash launcher (`exec python3 app.py`)
2. `requirements.txt` — Flask 3.0.3 only
3. `app.py` — entry point, blueprint registration, error handlers, listens on `0.0.0.0:$PORT`
4. `db.py` — in-memory store + `SystemClock` register + ISO 8601 helpers
5. `errors.py` — `APIError` class + `ERROR_CATALOG` (all 22 error_ids)
6. `response.py` — `success` / `list_success` / `error` helpers producing the `meta`/`response_type`/`data` envelope
7. `middleware.py` — `require_roles(*roles)` decorator extracting `X-User-Role` + `X-User-ID`
8. `util.py` — pagination, body parsing, FK parent-404 helpers
9. `services/calculations.py` — `net_monthly_income` (BENEFIT_CALC + LIMIT_CHECK), `compute_monthly_allotment` (STANDARD + EMERGENCY), `fraud_velocity_should_flag`, plus constant tables
10. `services/household_ops.py` — `bump_household` + `recompute_household_totals`
11–20. `routes/{households,members,applications,ebt_cards,monthly_allotments,categories,purchase_transactions,fraud_flags,abawd_waivers,emergency_allotments,system_clock}.py`

**Endpoints implemented:** 54 (matches PRD §4 exactly).
**State machines wired:** 8.
**Calculations implemented:** 3 (net_monthly_income, monthly_allotment, fraud_velocity_score).

**Validation order:** Auth decorators first; inside views top-down per PRD §2.8: path-id existence → body FK existence → state precondition → cross-entity host-state → claiming-investigator → uniqueness/temporal → safety (ABAWD/income) → constraints → OCC last.

**OCC handling:** `expected_household_version` on issue, `expected_fraudflag_version` on substantiate. Cascaded mutations bump own version+updated_at per §2.9.

**Storage:** pure in-memory singleton `_Store`; no seeding; per-test-server restart guarantees clean state.

**start.sh PORT:** reads `os.environ.get("PORT", "10000")`, binds `0.0.0.0`. start.sh uses `exec python3 app.py`.

**Judgement calls / PRD ambiguities (flag for Step 7):**
1. Out-of-state detection from `merchant_id` — encoded as `XX_` prefix convention; PRD does not specify.
2. `certification_end_date = current_utc + 365 days` (calendar-month arithmetic unspecified).
3. Cardholder activate ordering: `ERR_INVALID_STATE` before `ERR_HOUSEHOLD_NOT_ACTIVE`.
4. Household.suspend without SUBSTANTIATED flag → `ERR_INVALID_STATE`.
5. MonthlyAllotment.adjust without qualifying proclamation → `ERR_INVALID_STATE`.
6. Waiver `monthly_work_hours` upper bound unconstrained.
7. Duplicate EligibleItemCategory code → `ERR_INVALID_REQUEST`.
8. `_clock` endpoints: PolicyAdmin writes; several roles read.

## Step 7: Run tests and iterate to PASS — 2026-05-27T13:35:00Z

All 8 rounds pass 65/65. Clean sweep — exited.

- **Iterations run**: 2.
- **Tests deleted**: 0.
- **Fixes applied to `test_helpers/`**: none.
- **Fixes applied to `test_suite/`** (test bugs — fixtures violated PRD §3.1's case_number format `^[A-Z]{2}-[0-9]{6}$`; renamed to PRD-faithful 6-digit IDs):
  - `test_01_household_intake.py`: `CA-DEF001` → `CA-100100`, `CA-DEF002` → `CA-100101`, `CA-C00001` → `CA-100102`.
  - `test_03_application_lifecycle.py`: `CA-A00001` → `CA-300001`, `CA-R00001` → `CA-300002`, `CA-RBAC02` → `CA-300003`.
  - `test_04_household_cascades.py`: `CA-T00001` → `CA-400001`.
  - `test_06_monthly_allotment_calculations.py`: `CA-N00001` → `CA-100003`, `CA-M00001` → `CA-100004`, `CA-E00001` → `CA-100005`. Also added `set_clock("2026-07-01T00:00:01Z")` between issue and proclamation activation in `test_standard_then_emergency_adjust_yields_expected_supplement` so the proclamation activation timestamp is strictly after `issued_at` (PRD §3.5 "reached ACTIVE ... after the allotment's issued_at timestamp").
  - `test_07_monthly_allotment_lifecycle.py`: `CA-P00001` → `CA-700001`, `CA-I00001` → `CA-700002`, `CA-OCC001` → `CA-700003`.
  - `test_08_purchases_and_velocity.py`: `CA-X00001` → `CA-800001`, `CA-Y00001` → `CA-800002`, `CA-L00001` → `CA-800003`.
  - `test_09_fraud_flags.py`: `CA-F00001` → `CA-900001`, `CA-OCC002` → `CA-900002`.
  - `test_11_rbac_and_errors.py`: `CA-RBAC01` → `CA-110001`.
  - `test_12_endpoints_meta.py`: `CA-LP0001/0002/0003` → `CA-120001/120002/120003`.
  - `test_13_abawd_waivers.py`: `CA-W00001` → `CA-130001`.
  - `test_14_emergency_proclamations.py`: `CA-D00001` → `CA-140001` (both occurrences).
- **Fixes applied to `implementation/`**: none.

Final state: 8/8 rounds, 65/65 tests passing.

## Step 8: Finalize PRD — 2026-05-27T13:36:00Z

**PRD.md vs PRD_FINALIZED.md**: 300 lines each (0% line-delta — all edits inline within existing paragraphs). Character delta: 47,087 → 51,761 (+4,674 chars, +9.9%).

**Changes** (PRD section — kind — what changed — impl file:line):

- §3.1 (member status) — insert — pinned that PATCH allows both `ACTIVE→REMOVED` and `REMOVED→ACTIVE`, each re-running roster recomputation — routes/members.py:146-153
- §3.2 (Application create) — insert — pinned Applicant ownership gate at create+submit; clarified household-state check is at submit only — routes/applications.py:50-72,107-134
- §3.2 (approval cascade) — revise — pinned `certification_end_date = current_utc + 365 days` (not calendar 12-month addition) — routes/applications.py:239
- §3.2 (application expiry) — revise — pinned that expiry is evaluated on every `set_current_utc` call and that both rows have updated_at/version bumped — routes/system_clock.py:16-40
- §3.3 (ABAWD age) — revise — pinned the integer-year anniversary-based age calculation; clarified the "no member under 18" set is restricted to `ACTIVE` members — routes/applications.py:145-168
- §3.3 (waiver approve) — insert — pinned that failing the county-pct OR work-hours predicate surfaces as `ERR_INVALID_STATE` (no dedicated error id) — routes/abawd_waivers.py:129-134
- §3.5 (issue) — revise — pinned that missing ACTIVE EBT card surfaces as `ERR_INVALID_STATE`; pinned that missing/non-int/bool `expected_household_version` is `ERR_INVALID_REQUEST` while int-mismatch is `ERR_STALE_HOUSEHOLD_VERSION` — routes/monthly_allotments.py:131-154
- §3.5 (adjust) — insert — pinned that the "reached ACTIVE at" instant is the proclamation's `updated_at` (fallback `created_at`), strict-greater than `issued_at`; missing match surfaces as `ERR_INVALID_STATE` — routes/monthly_allotments.py:184-201
- §3.6 (replace abuse window) — insert — pinned that the counted set is "REPLACED-status cards whose `updated_at` falls in `[current_utc-90d, current_utc]` inclusive on both ends", including the just-mutated predecessor — routes/ebt_cards.py:166-180
- §3.7 (suspend) — insert — pinned that missing-SUBSTANTIATED-flag surfaces as `ERR_INVALID_STATE` (no dedicated error id) — routes/households.py:157-166
- §3.8 (category code) — revise — pinned the regex `^[A-Z][A-Z0-9_]{1,31}$` (must start with uppercase letter); duplicate `code` surfaces as `ERR_INVALID_REQUEST` (no dedicated duplicate-category error) — routes/categories.py:18,40-43
- §3.8 (line-items validation) — revise — pinned that structural validation, unknown-category, and empty-array arms all surface as `ERR_INVALID_LINE_ITEMS` in a single pre-eligibility pass — routes/purchase_transactions.py:50-79
- §3.8 (out-of-state derivation) — insert — pinned the rule: merchant location is inferred when the first two chars are uppercase letters AND the third is `_`; otherwise the merchant is treated as in-state — routes/purchase_transactions.py:101-105
- §3.9 (fraud-flag substantiate) — revise — pinned that missing/non-int/bool `expected_fraudflag_version` is `ERR_INVALID_REQUEST`; only int-mismatch is `ERR_STALE_FRAUDFLAG_VERSION` — routes/fraud_flags.py:122-128
- §3.9 (dismiss terminal-state) — insert — pinned that dismissing a `SUBSTANTIATED` or `DISMISSED` flag is `ERR_INVALID_STATE` — routes/fraud_flags.py:145-146
- §3.9 (velocity window) — revise — pinned that the 24-hour window is `[current_utc-24h, current_utc]` with both endpoints inclusive — services/calculations.py:151-165
- §3.10 (proclamation activate) — revise — pinned that activating a proclamation with `benefit_month < current_month` surfaces as `ERR_INVALID_STATE` — routes/emergency_allotments.py:106-109
- §3.10 (SystemClock) — revise — pinned: lighter-entity fields only; `id` minted lazily on first set/read and stable thereafter; `to_iso8601` accepts a trailing `Z`; re-emitted as `YYYY-MM-DDTHH:MM:SS.sssZ`; pre-set value reflects real wall clock; deferred-transition evaluation fires on every set call — db.py:60-93, routes/system_clock.py:16-65
