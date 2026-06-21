# Worklog — task_0013_estate_planning_trust

## Step 1: Create task directory — 2026-05-27T00:00:00Z

Created `tasks/task_0013_estate_planning_trust/workspace/` (pre-allocated path; no index scan performed).

## Step 2: Generate scaffold — 2026-05-27T00:05:00Z

Three files written to `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0013_estate_planning_trust/`:

| File | Lines |
|------|-------|
| `SCAFFOLD.yaml` | 1663 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1295 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 1207 |

**SCAFFOLD.yaml** (§1.0–§1.7 + concurrency):
- 10 entities (Decedent, Estate, Asset, BeneficiaryDesignation, Executor, PowerOfAttorney, EndOfLifeDirective, Guardianship, CreditorClaim, ProbateOrder)
- 29 distinct statuses across 6 state machines
- 5 calculations (gross_estate_value, net_taxable_estate w/ provisional vs final variants, creditor_payment_waterfall w/ pro_rata vs priority variants, intestacy_share_allocation, guardian_age_eligibility)
- 17 priority-ordered validations
- 55 endpoints
- 18 error codes
- 7 roles (EstatePlanner, Executor, Judge, Beneficiary, Registrar, Creditor, PlatformAdmin)
- 2 concurrency rules (OCC on Estate.version, guarding revoke-designation and contest-estate)

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** (§1.8):
- 9 rule_ids × 2 instances = 18 difficulty instances
- All instances ground in §1.1–§1.7 elements; each carries a structured `setup_api_calls` chain executable from empty-DB

**SCAFFOLD_CORNER_DESIGN.yaml** (§1.9):
- 9 sections (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_layers, consistency_model)
- 29 instances total (25 active with full test_recipes, 4 excluded_because stubs pointing to §1.8 instances)

**Lint verdict** (`python3 skills/prd-bench-scaffold-generator/scaffold_lint.py tasks/task_0013_estate_planning_trust`):
```
Coverage
  §1.5 endpoints declared:    55
  §1.1 entities declared:     10
  §1.8 instances scanned:     18
  §1.9 instances scanned:     25
  Calls scanned (§1.8+§1.9):  449
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Design highlights:**
- **Archetype**: multi_party_negotiation + compliance_audit (probate supervision needs court/executor/beneficiary alignment; HIPAA/POA/SoD enforce compliance constraints).
- **Layers**: cascading_side_effects (death registration cascades 3 levels), dual_variant_calculation (net_taxable_estate frozen-snapshot vs live-gross; waterfall pro-rata vs priority), version_pinning_on_approval (OCC on Estate.version), derived_field_reconciliation (gross_estate_value_cents, inventory_snapshot_gross_cents), optimistic_concurrency.
- **State-machine shape**: branching with a true PROBATE_OPEN ↔ CONTESTED cycle and ProbateOrder branching by order_type.
- **Role model**: segregation_of_duties (Executor cannot attest a DNR; if Executor is also beneficiary, court must waive).
- **Difficulty rule satisfaction**: dual_variant_calc on Estate vs CreditorClaim (different entity domains); combinatorial_formula via waterfall (mode a: 3-input non-linear) and intestacy remainder (mode b: nested rounding order); non_linear_state_machine on Estate (cycle) and ProbateOrder (branching); transitive_cascade depth 3 (register-death→Estate→POA) and depth 2 (CLOSE_ESTATE→Estate→Executor); priority_pair_validation_conflict (state vs business_safety; business_temporal vs business_fiscal); boundary_precision_check (120-day strict at endpoint A; empty-set at endpoint B); cross_entity_state_dependency (Estate↔BeneficiaryDesignation; ProbateOrder↔Executor); resource_temporal_overlap (POA half-open intervals; Guardianship point-uniqueness — different interval semantics); compensating_invariant (share_basis_points conservation; gross_estate_value_cents conservation).

## Step 3: Copy INSTRUCTION.md — 2026-05-27T00:08:00Z

Copied `INSTRUCTION.md` into `workspace/`.

## Step 4: Generate PRD — 2026-05-27T00:16:00Z

**Output**: `workspace/PRD.md` — 309 lines.

### Section structure
- §1 Introduction (3 paragraphs — system goals, domain coverage, cross-cutting concerns)
- §2 Global Specifications (9 subsections):
  - 2.1 RBAC (7 roles, each identity translated)
  - 2.2 Response Structure (verbatim from source)
  - 2.3 Pagination
  - 2.4 Common Resource Properties
  - 2.5 Nested Resource Retrieval & Path Validation
  - 2.6 Optimistic Concurrency Control (both OCC rules)
  - 2.7 Monetary and Share Precision
  - 2.8 Cascading Mutations and Audit Integrity (incl. inventory_snapshot freeze)
  - 2.9 Validation Ordering (full 17-priority list)
- §3 Business Logic (10 subsections, organized by lifecycle stages from drafting through closure with cross-cutting waterfall/calculation in middle)
- §4 Endpoint table (4 columns)
- §5 Error catalogue (2 columns)

### Hard Contracts
- Field coverage: 43/43 entity fields, 42/42 endpoint inputs — PASS
- Rule coverage: 17/17 validations, 2/2 OCC rules, 25/25 transitions, 5/5 calculations (incl. all variants) — PASS
- Sibling-branch symmetry (directive WITNESSED vs NOTARIZED; waterfall pro_rata vs priority_full_pay; net_taxable provisional vs final; intestacy CA/NY/FL/IL + TX divergent) — PASS
- §3 path purity: 0 paths, 0 HTTP methods, 0 backtick FK declarations — PASS

### Intentional scattering decisions
- `expected_estate_version` appears in §2.6 (contract) and §3.1/§3.7 (workflow context); `reason` in contest/supersession narrative; `resolution_note` only in resolve-contest sentence; `decision`/`CONFIRM` only in guardianship review sentence (§3.3); `to_iso8601` only in §3.10.
- Validation priority concentrated in §2.9, with each trigger condition repeated in its §3 workflow home.
- Net-taxable variant selection is a stand-alone subsection (§3.9) because the two-variant pattern is the most subtle correctness pitfall in the domain.
- §3 contains zero schema tables, zero FK declarations, and zero endpoint paths/methods in backticks — relationships introduced through action verbs and parent context.

## Step 5: Generate unit tests — 2026-05-27T00:35:00Z

### Helper file inventory (test_helpers/)
9 files: `__init__.py`, `types.py` (10 entities, 13 enums), `api_client.py` (52 methods), `api_errors.py` (18 error IDs + HTTP map), `assertions.py` (10 entity assertions + common-field), `factories.py` (11 payload factories), `constants.py` (basis points, creditor window, age, intestacy state shares), `test_users.py` (opaque-role shared constants + entity-backed per-instance builders), `fixtures.py` (3 tiers; ~620 lines).

### Test files (test_suite/)
16 test files + conftest.py, **60 total tests**. Files numbered `test_01_…` through `test_16_…`, organized by concern (dual-variant calcs, combinatorial formulas, state-machine topology, cascades, validation priority, boundary precision, cross-entity dependencies, temporal uniqueness, compensating invariants, entity CRUD, state machines, calculations, validations, endpoints, errors/RBAC, cross-cutting/consistency).

### Coverage
- **Queue A — Difficulty: 18/18 instances translated, each with ≥2 tests (36 difficulty-tagged tests).**
- **Queue B — Corner: 24/25 active non-stub instances translated (24 corner-tagged tests).**
- 4 `excluded_because` stubs correctly NOT translated:
  - `state_machines/contest_estate_stale_version_excluded`
  - `calculations/intestacy_excluded_by_difficulty`
  - `errors/missing_auth_header_returns_unauthenticated_excluded`
  - `errors/insufficient_estate_funds_excluded`
- **1 active instance skipped under PRD-first filter**:
  - `entities/fk_estate_decedent_id_invalid_returns_not_found` — PRD §2.5/§2.9 scopes existence/`ERR_NOT_FOUND` rule explicitly to "URL path" parameters; body-FK validation (`decedent_id` in POST /estates body) not committed by PRD to either `ERR_NOT_FOUND` or `ERR_INVALID_REQUEST`. Two PRD-only implementers could ship either outcome — fails unique derivability.

All tests carry the mandatory `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` docstring tag copied verbatim plus a PRD citation matching C1/C2/C3.

## Step 6: Generate implementation — 2026-05-27T00:35:00Z

**Location:** `workspace/implementation/`
**File count:** 24 files (22 .py + 1 .sh + 1 .txt)
**Total LoC:** 2,796

**Top-level modules:** `start.sh` (exec python3 app.py after pip install), `requirements.txt` (Flask==3.0.3), `app.py` (factory + error handlers + blueprint registration; binds 0.0.0.0:$PORT), `db.py` (in-memory dicts for 10 entities + pinned-clock state), `errors.py`, `response.py` (envelope `{meta, response_type, data}` with `req_…` IDs and 3-digit ISO timestamps), `middleware.py` (`require_roles` decorator: auth first, role second), `common.py` (UUID minting, created_at/updated_at/version stamping, ISO parse/format, pagination params), `views.py` (one serializer per entity), `services/calculations.py`, `services/cascades.py`, `routes/*.py` (one blueprint per resource family).

**Mounted endpoints:** 55 routes — matches PRD endpoint table. Distribution: estates 9, directives 7, creditor-claims 6, assets/designations/executors/poas/probate-orders 5 each, guardianships 4, decedents 3, clock 1.

**Hard-constraint conformance:** in-memory dicts only; zero seeding; foreground via `exec python3 app.py`; reads `PORT` env (default 10000); binds `0.0.0.0`. Boot verified via start.sh on port 18913 — HTTP ready in ~4s.

**Tricky design decisions:**
1. **Calculation ordering on cascades.** Mutate children → recompute gross → recompute net → touch(estate) once (single version bump per logical operation, per PRD §2.8).
2. **OCC field reading order.** `expected_estate_version` checked after existence/role/state but before mutation; stale returns 412 before revoke.
3. **Two-variant net taxable.** `'final'` iff `status ∈ {ADMINISTRATION, CLOSED} AND inventory_snapshot_gross_cents IS NOT NULL`. Snapshot set once in `cascade_approve_inventory`; subsequent re-appraisals don't leak.
4. **Waterfall variant switch.** Any DRAFT `CLOSE_ESTATE` order at pay-time → pro-rata-within-class with residual cents allocated one-at-a-time in `created_at` ASC order so class total = remaining pool exactly.
5. **Death cascade gating.** Only estates in `ALIVE` cascade to `DECEASED`; non-durable POAs walked once per cascade independent of estate status.
6. **Beneficiary identity model.** `Beneficiary.X-User-ID` = `BeneficiaryDesignation.id`; contest verifies designation belongs to contested estate before OCC.
7. **Executor identity model.** `Executor.X-User-ID` = `Executor.id`; accept/decline check named candidate; file-for-probate/liquidate check `Estate.executor_user_id`.
8. **Guardian eligibility boundary.** Strict-inequality `(ward_dob + 18y).date() > date_of_death.date()`. Feb-29 wards → Feb-28 in non-leap years.
9. **POA interval overlap.** Half-open `[effective_at, effective_until)` with `None` = +inf; standard interval-overlap with null-as-infinity short-circuit.
10. **Validation priority resolution.** Canonical PRD §2.9 order: auth → existence → role → state → business. revoke-designation on already-REVOKED returns `ERR_INVALID_STATE` (409) even with stale OCC.

## Step 7: Iterate tests until pass — 2026-05-27T01:00:00Z

**Final sweep**: all 8 parallel rounds 59/59 passed (verified by re-reading results.*.json).

**Iterations run**: 3 sweeps.

**Tests deleted (1)**:
- `test_15_errors_and_rbac.py::TestWardOverAgeAtStrictBoundary::test_ward_18th_birthday_equal_to_date_of_death_ineligible` — STEP 1b non-unique-derivability. PRD §3.3 simultaneously says (a) "ward implied to be under eighteen ... is promoted from PROPOSED to COURT_REVIEW" (strict reading: exact-18 stays PROPOSED) and (b) "ward whose eighteenth birthday lands on the exact date of death is ineligible; in that case the review yields ERR_WARD_OVER_AGE" (requires the row be reviewable, i.e. promoted). A PRD-faithful impl adopting reading (a) returns ERR_INVALID_STATE under §2.9 priority order (state check at priority 4 fires before ward-age at priority 11). Error-precedence-silence + cascade-boundary-silence collapse.

**Fixes applied to `test_helpers/fixtures.py`**:
- `bootstrap_estate_with_contingent_designation_chain` — moved contingent-designation creation to AFTER `finalize_plan` so referenced primary is ACTIVE at create time. Original fixture violated PRD §3.1's `ERR_CONTINGENT_PARENT_INVALID` precondition.
- `bootstrap_administration_with_assets_and_claim` — now advances to ADMINISTRATION (via APPROVE_INVENTORY entry) before filing/allowing the claim, matching PRD §3.6 (allowance only during ADMINISTRATION).
- Added `bootstrap_probate_open_with_assets` — a PROBATE_OPEN fixture WITHOUT any allowed claim (PRD forbids allowance during PROBATE_OPEN), for the provisional-variant test.

**Fixes applied to `test_helpers/__init__.py`**:
- Exported the new `bootstrap_probate_open_with_assets` helper.

**Fixes applied to `test_suite/test_01_dual_variant_calculations.py`**:
- `test_provisional_variant_uses_live_gross` — switched to `bootstrap_probate_open_with_assets` (no allowed claim); PATCHes asset appraisal and verifies live gross flows into provisional net (PRD §3.9). Asserts `net == 5_000_000` initially, then `net == 8_000_000` after PATCH.
- `test_final_variant_freezes_inventory_snapshot` — fixture now produces ADMINISTRATION state with allowed claim directly. Dropped assertion `data["gross_estate_value_cents"] == 8_000_000` on summary response: PRD §3.9 lists summary's `gross_estate_value_cents` but does not specify whether it echoes live Estate gross or active variant's `gross_used` — non-unique-derivable. Remaining `net_taxable_estate_cents == 4_900_000` is itself a strict witness of frozen-snapshot (non-frozen impl would yield 7_900_000).

**Fixes applied to `implementation/`**: None — implementation was PRD-faithful in all observed failures; every fix was in the test artifact.

## Step 8: Finalize PRD — 2026-05-27T01:08:00Z

**Line counts**: PRD.md = 309; PRD_FINALIZED.md = 309; %-delta = 0% (both edits revised existing single-line paragraphs in place).

**Changes**:
- **§3.3 (Death and the Inheritance Cascade) — revise** — Pinned exact-18 boundary: only eligible (strictly-under-18) wards are promoted from `PROPOSED` to `COURT_REVIEW` by the registration cascade; exact-18 and older wards stay in `PROPOSED`. Noted that an attempt to review a still-`PROPOSED` row yields `ERR_INVALID_STATE` (priority-4 state check); `ERR_WARD_OVER_AGE` is reserved for review-time ineligibility on `COURT_REVIEW`. — `implementation/services/cascades.py:60-70`, `implementation/services/calculations.py:244-248` (`guardian_eligible` uses strict `>`; cascade promotes only when eligible).
- **§3.9 (The Two-Variant Net Taxable Estate) — revise** — Pinned that the net-taxable summary's response `gross_estate_value_cents` field echoes the active variant's chosen gross (live Estate gross for provisional; frozen `inventory_snapshot_gross_cents` for final), not always the live Estate field. Also pinned that invoking the summary marks the estate as having run the net-taxable calculation (the precondition for `CLOSE_ESTATE` entry). — `implementation/services/calculations.py:35-66`, `implementation/routes/estates.py:245-253`.

**Items intentionally not patched** (pure fixture bugs, not PRD silence): `bootstrap_estate_with_contingent_designation_chain`, `bootstrap_administration_with_assets_and_claim`, and `bootstrap_probate_open_with_assets` — PRD §3.1, §3.6, and §3.9 already determine the underlying behavior unambiguously; the original fixtures simply built the wrong preconditions.
