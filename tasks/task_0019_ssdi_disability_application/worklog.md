# Worklog — task_0019_ssdi_disability_application

Scenario: SSDI Disability Insurance Application — work credit requirement (QC), medical evidence, Listings/RFC, ALJ hearing scheduling, Back Pay, SSI supplemental, child auxiliary, CDR periodic review.

## Step 1: Create task directory — 2026-05-27T00:00:00Z

Skipped per user instruction. Pre-created at `./tasks/task_0019_ssdi_disability_application/` with `workspace/` subdirectory. Index 0019 assigned by user.

## Step 2: Generate scaffold — 2026-05-27T00:26:00Z

**Generated three files** at `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0019_ssdi_disability_application/`:
- `SCAFFOLD.yaml`
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `SCAFFOLD_CORNER_DESIGN.yaml`

**`scaffold_lint.py` verdict**: `clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (596 calls scanned across 18 difficulty + 27 active corner instances; 36 endpoints, 10 entities.)

### SCAFFOLD.yaml counts
- entities: **10** (Claimant, WorkCreditRecord, Application, MedicalEvidence, MedicalDeterminationDecision, HearingRequest, BenefitAward, ChildAuxiliaryBenefit, SSISupplement, CDRReview)
- state_machines: **5** (Application, HearingRequest, BenefitAward, ChildAuxiliaryBenefit, CDRReview)
- calculations: **6** (qc_count, pia_amount, back_pay_amount, ssi_supplement_amount, child_auxiliary_amount, cdr_schedule)
- validations: **18** (priorities 1–18, ordered)
- endpoints: **36**
- errors: **20**
- roles: **5** (Claimant, DDSExaminer, ALJ, BenefitsAdmin, SSAAdmin — peer-role model)
- concurrency_rules: **2** (medical_decision_stale_application, child_auxiliary_create_stale_award)

### Difficulty design instance counts (per rule_id, each ≥2)
- dual_variant_calc: 2  (back-pay INITIAL vs ALJ variants on BenefitAward; SSI eligible vs resource-ineligible on SSISupplement — different entity domains)
- combinatorial_formula: 2  (PIA tiered round-per-tier-then-sum [mode b]; QC nonlinear age-bucket + lookback gate [mode a])
- non_linear_state_machine: 2  (Application branching fork + revision loop; ChildAuxiliaryBenefit branching termination paths)
- transitive_cascade: 2  (CDR cessation depth-3 chain; hearing cancel→revert depth-2 chain)
- priority_pair_validation_conflict: 2  (state vs business_safety; business_referential vs business_safety)
- boundary_precision_check: 2  (SSI $2000 resource limit `>`; hearing 75-day lead-time `>=`)
- cross_entity_state_dependency: 2  (MedicalDecision→Application; CDRReview→Application)
- resource_temporal_overlap: 2  (60-day reconsideration closed-interval window; 75-day hearing half-open lead-time interval)
- compensating_invariant: 2  (hearing cancel round-trip on Application.status; suspend/reinstate preserves BenefitAward.PIA)
- **Total: 18**

### Corner design instance counts (per section)
- entities: 8 (required fields, defaults, type constraints, not_found, listing, duplicate uniqueness, FK reference)
- state_machines: 6 (4 active: re-submit invalid state, initial state, terminal lockdown, re-schedule invalid state; 2 `excluded_because` stubs)
- calculations: 6 (4 active: PIA low-AIME tier1-only, SSI CA state supplement, child aux first-child base amount, CDR MIE 18-month schedule; 2 stubs pointing to §1.8)
- validations: 4 (LISTING_MET missing reference, child over age, no-evidence ERR_EVIDENCE_REQUIRED, family-max exceeded)
- endpoints: 2 (filtered list, sub-resource reverse-reachability)
- errors: 4 (2 active: unauthenticated, forbidden; 2 stubs)
- rbac: 2 (ALJ cannot create claimant; DDSExaminer cannot schedule)
- cross_cutting_complexity_layers: 4 (all `excluded_because` stubs deferring to §1.8 instances)
- consistency_model: 1 (immediate consistency after submit)
- **Total: 37** (27 active test recipes + 10 `excluded_because` stubs; the lint tool counts only the 27 active)

### Complexity profile
- Primary archetype: **workflow_orchestration** (SSDI multi-step pipeline with branching)
- Secondary: **compliance_audit**
- Topology: **flat** (FK references; no nested URL paths)
- State machine shape: **branching** (Application has MEDICAL_REVIEW fork, DENIED_MEDICAL revision loop, ALJ pathway)
- Role model: **peer_roles** (Claimant/DDSExaminer/ALJ/BenefitsAdmin/SSAAdmin own different operation sets)
- Consistency: **immediate**

## Step 3: Copy INSTRUCTION.md — 2026-05-27T00:27:00Z

Copied `./INSTRUCTION.md` → `./tasks/task_0019_ssdi_disability_application/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-05-27T00:33:00Z

**Output:** `workspace/PRD.md`

**Document shape:**
- 5 top-level sections (Introduction, Global Specs, Business Logic, Endpoint Definitions, Error Catalogue)
- 19 subsections total (§2 has 10 subsections, §3 has 9 subsections)
- 256 lines

**§2 layout (domain-derived):** 2.1 RBAC, 2.2 Response Structure (verbatim), 2.3 Pagination, 2.4 Common Resource Properties, 2.5 Nested Resource Retrieval and Reference Validation, 2.6 State Cascades / Hierarchical Consistency / Versioning, 2.7 OCC, 2.8 Precision and Monetary Arithmetic, 2.9 Validation Priority, 2.10 The Server Clock.

**§3 layout (lifecycle-staged):** 3.1 Claimant Intake & Work-Credit Ledger, 3.2 Filing & QC Gate, 3.3 Evidence Collection, 3.4 Medical Determination, 3.5 Reconsideration & ALJ Hearing, 3.6 Benefit Award (PIA / Back Pay / two variants), 3.7 SSI Supplement, 3.8 Child Auxiliaries & Family Maximum, 3.9 CDR.

**Hard Contracts (all PASS):** field coverage 53/53, rule coverage (18 validations + 2 OCC + 25 transitions + 6 calculations + 20 validation conditions + sibling-branch symmetry + 9 entities), path purity (0 leaked URLs/methods).

**Coverage gaps / scaffold inconsistencies noted:**

1. **`CLOSED` Application state has no inbound transition.** Resolved by enumerating all `status` values in §3.2 with annotation that `CLOSED` is "reserved for administratively closed records that are not reachable through any transition described in this document".

2. **`CDRReview` state-machine `terminal_states` mismatch.** CDRReview SM declares `terminal_states: [CONTINUED, CESSATION]` but `CDRReview.outcome` enum is `PENDING|CONTINUED|CESSATION`. The entity has no separate `status` field — translated as outcome values throughout §3.9.

3. **`ALJ_DENIED` is `terminal-ish`** per scaffold comment but not formally in `terminal_states`. Translated as a regular state reached on `DENIED` hearing outcome; no transitions leave it.

4. **`expected_application_version` priority-8 validation `applies_to` mismatch with concurrency_rules.** Validation priority 8 lists only `/medical-decision` — faithfully translated as such.

5. **`POST /ssdi/applications/{id}/evidence` roles.** Scaffold says `Claimant, DDSExaminer` — PRD reflects this.

6. **`Application.recent_qc_in_lookback` lookback semantics.** Translated as "the ten-year window that ends at the filing year inclusive" — preserves scaffold's literal formula `year(filing_date) - 10`.

7. **No `total_count` semantics in scaffold's response_envelope.** §2.3 still mentions all four pagination fields as required.

## Step 5: Generate unit tests — 2026-05-27T00:50:00Z

### Coverage stats
- **Queue A (Difficulty)** — 18 instances translated, 0 skipped. Each instance has exactly 2 tagged tests (36 tests).
- **Queue B (Corner non-stub)** — 27 instances translated, 0 skipped. Each has 1 tagged test (27 tests).
- **Queue B (Corner stub)** — 10 `excluded_because:` stubs were NOT translated (per skill contract). All `difficulty_instance` cross-references resolve to real difficulty `name:` entries.
- **Total**: 63 tagged tests across 15 test files. All compile cleanly under `python -m py_compile`.

### `test_helpers/` files written
- `__init__.py` — barrel export
- `types.py` — entity TypedDicts, status enums (MedicalEvidence correctly has only id+created_at per PRD §2.4)
- `api_client.py` — ApiClient with one method per endpoint
- `api_errors.py` — 20-entry error catalogue + HTTP map registration
- `assertions.py` — per-entity assertions; MedicalEvidence asserts no version/updated_at
- `factories.py` — payload factories
- `constants.py` — domain thresholds from PRD §3.6–3.9
- `test_users.py` — TEST_USERS dict, `make_claimant_headers(id)` for the entity-backed Claimant role, `make_unauthenticated_headers()`, `make_headers(user_id, role)`
- `fixtures.py` — five-tier composite setup (clock, claimant+credits, application+submit+evidence, decision+appeals+award, suspend/CDR)

### `test_suite/` files written
| File | Test count | Source queue |
|---|---|---|
| `conftest.py` | 0 (fixture bridge) | — |
| `test_01_dual_variant_calculations.py` | 4 | Difficulty |
| `test_02_combinatorial_formulas.py` | 4 | Difficulty |
| `test_03_branching_state_machines.py` | 4 | Difficulty |
| `test_04_transitive_cascades.py` | 4 | Difficulty |
| `test_05_priority_pair_conflicts.py` | 4 | Difficulty |
| `test_06_boundary_precision.py` | 4 | Difficulty |
| `test_07_cross_entity_state_dependency.py` | 4 | Difficulty |
| `test_08_temporal_overlap.py` | 4 | Difficulty |
| `test_09_compensating_invariants.py` | 4 | Difficulty |
| `test_10_entities_crud.py` | 8 | Corner |
| `test_11_state_machine_corner.py` | 4 | Corner |
| `test_12_calculations_corner.py` | 4 | Corner |
| `test_13_validations_corner.py` | 4 | Corner |
| `test_14_endpoints_and_consistency.py` | 3 | Corner |
| `test_15_rbac_and_auth.py` | 4 | Corner |

### PRD-coverage gaps encountered
None caused instance skips. Every difficulty and non-stub corner instance had verbatim PRD prose covering the asserted rule (PRD §2.5, §2.6, §2.7, §2.9, §3.1–3.9). The `list_claimants_pagination_meta_present` corner instance has a `response.data.total_count`-shaped recipe but PRD §2.3 explicitly places those fields under `meta`; followed PRD (via the framework's `validate_paginated`) since the test_recipe's exact path is a shorthand. Stage-1 fixture set is structured to make every fixture use `make_claimant_headers(claimant_id)` for ownership-gated calls — never falling back to the shared `TEST_USERS["claimant_headers"]` constant — preventing the canonical entity-backed-role bug.

## Step 6: Generate implementation — 2026-05-27T00:50:00Z

**Source files written** (under `workspace/implementation/`): 1,883 LOC across 18 files.

- `start.sh` (4 LOC) — bash launcher: `set -euo pipefail`, pip-install requirements, `exec python3 app.py`
- `requirements.txt` (1 LOC) — `Flask==3.0.3`
- `app.py` (73 LOC) — Flask app factory, blueprint registration, `APIError` and HTTP-exception handlers, binds `0.0.0.0:$PORT` (default 10000), `use_reloader=False`
- `db.py` (83 LOC) — in-memory tables (9 dicts), `now_utc()`/`set_clock()` logical clock, `stamp_create`/`stamp_update`, UUID/ISO timestamp helpers
- `errors.py` (52 LOC) — `APIError` class + all 20 error_id constants and convenience builders
- `response.py` (64 LOC) — envelope helpers producing `{meta: {api_request_id, api_request_timestamp, ...pagination}, response_type, data}` exactly as PRD §2.2 mandates
- `middleware.py` (36 LOC) — `X-User-ID`/`X-User-Role` extraction; `@require_roles(...)` decorator
- `services/calculations.py` (167 LOC) — QC count + required_total_qc(age), PIA bend-point with per-tier ROUND_HALF_UP, back-pay (entitlement_start = EOD+5mo first-of-month, retroactive_floor = PFD-12mo first-of-month, effective_start = max), SSI supplement (resource gate at strict >200000, FBR=94300, $20 exclusion, state table CA/NY), child auxiliary base+family-max headroom, CDR schedule (MIE=18mo, MIP=36mo, MINE=84mo)
- `services/state.py` (282 LOC) — cross-resource transitions: `submit_application`, `apply_medical_decision`, `apply_alj_approved`, `cdr_complete_continued/cessation`, `suspend_award/reinstate_award`
- `services/utils.py` (161 LOC) — ISO8601 parser, pagination, USPS state set (50+DC), `add_months`, `first_day_of_month`, `months_between`, `years_between`, `round_half_up`
- `routes/claimants.py` (79 LOC)
- `routes/work_credits.py` (80 LOC)
- `routes/applications.py` (320 LOC) — application CRUD + `/submit` + `/medical-decision` (with OCC, EOD/AOD, LISTING_MET checks in priority order) + `/request-reconsideration` (60-day window) + `/request-hearing` + evidence + decisions
- `routes/hearings.py` (159 LOC)
- `routes/awards.py` (177 LOC)
- `routes/cdr.py` (145 LOC) — includes `/_clock/set_current_utc` + `/_clock/advance`

**State machines and OCC organization** — Every state transition is implemented as a service function in `services/state.py` that mutates the parent record once via `db.stamp_update()` (bumping `updated_at` and `version`) and then cascades to children, with each cascaded child getting its own `stamp_update`. Auto-transitions inside the same logical step (DRAFT→QC_REVIEW→MEDICAL_REVIEW, APPROVED_INITIAL→AWARDED) refresh `updated_at` only, so the caller-facing version increment is exactly one per HTTP request. OCC is implemented inline in two route handlers — `medical-decision` checks `expected_application_version`, and `child-auxiliaries` POST checks `expected_benefit_award_version`. Both fire after auth/existence/state gates per §2.9 priority order.

**PRD ambiguities resolved**:
1. **Decision after record-held**: scaffold only defines `SCHEDULED→APPROVED/DENIED` and `SCHEDULED→HELD` (no `HELD→...` decision transition). Enforce SCHEDULED-only for `/decision`.
2. **SSI cascade gate** (`ERR_SSI_NOT_REQUESTED`, priority 16): treated as server-internal invariant — cascade only fires when `claim_type == CONCURRENT_SSDI_SSI`.
3. **AIME divisor when N=0**: returns 0 cents (no division by zero).
4. **CDR diary default**: defaults the initial CDR's `diary_classification` to `"MIE"`.
5. **Reconsideration when multiple denials exist**: picks the latest (max `created_at`) `NOT_DISABLED` decision.
6. **Hearings decision after HELD** rejects with `ERR_INVALID_HEARING_STATE` — strict scaffold reading.

**start.sh confirmation**: reads `$PORT` env var via `os.environ.get("PORT", "10000")` in `app.py`; binds `host="0.0.0.0"`; foreground (`exec`); `use_reloader=False`; in-memory only — module-level dicts in `db.py`, no persistence, no seeding/preloading at startup.

## Step 7: Run tests and iterate — 2026-05-27T01:10:00Z

All 8 rounds: 63/63 passing. The fix worked on the first iteration.

**Summary:**

- Iterations run: 2 (baseline + one fix iteration).
- Tests deleted: 0.
- Fixes applied to `test_helpers/`: none. The defensive fallback in `fixtures.py` (lines 220, 352 — `payload["items"] if isinstance(payload, dict) and "items" in payload else payload`) was already correct; bugs were all in `test_suite/`.
- Fixes applied to `test_suite/` (test bug, STEP 2 — test inconsistent with PRD):
  - `test_01_dual_variant_calculations.py` (4 sites), `test_03_branching_state_machines.py` (3 sites), `test_04_transitive_cascades.py` (2 sites), `test_06_boundary_precision.py` (2 sites), `test_09_compensating_invariants.py` (2 sites), `test_12_calculations_corner.py` (1 site): replaced `get_success_data(res)["items"]` with `get_success_data(res)`. PRD §2.2 specifies the standard envelope as `data: [array]` for list responses — `data` IS the list, so indexing `["items"]` against a list raised `TypeError: list indices must be integers or slices, not str`.
  - `test_01_dual_variant_calculations.py` (test_alj_approval_variant_uses_alj_decision_date) and `test_03_branching_state_machines.py` (test_denial_then_reconsideration_then_alj_approves_creates_alj_variant_award): removed the spurious `record_hearing_held(...)` call that immediately preceded `decide_hearing(...)`. PRD §3.5 verbatim: "The judge ultimately records an outcome by transitioning the hearing from `SCHEDULED` to either `APPROVED` or `DENIED`." — i.e., the decision transition is `SCHEDULED → APPROVED/DENIED`, not `HELD → …`. The earlier sentence states `record-held` "is purely administrative; it does not by itself produce an outcome." The test's setup forced HELD before requesting a decision, which the PRD-faithful implementation correctly rejected with `ERR_INVALID_HEARING_STATE`.
- Fixes applied to `implementation/`: none. The implementation was already PRD-faithful.

Final state: 63/63 passing across all 8 parallel rounds, deterministic.

## Step 8: Finalize PRD — 2026-05-27T01:18:00Z

**File line counts**:
- PRD.md: 256 lines
- PRD_FINALIZED.md: 256 lines
- %-delta: 0% line-count delta (all edits are inline insertions within existing paragraphs); diff itself is ~24 lines (5 paragraphs revised).

**Changes** (each one is an inline insertion / mid-paragraph revision; no new sections):

- §3.3 (Medical Evidence Collection) — revise — opening sentence reframed so evidence attachment is gated only on `Application` existence, not on application `status` (PRD's "Once an application is in `MEDICAL_REVIEW`" was descriptive of timing; impl accepts evidence at any application status) — `implementation/routes/applications.py:269-296` (`add_evidence` has no status guard).
- §3.6 (PIA computation) — insert — empty-history default: when the claimant has zero qualifying years of credits, PIA is fixed at 0 cents — `implementation/services/calculations.py:72-74` (`if not years_with_credits: return 0`).
- §3.6 (PIA computation) — revise — pin the AIME rounding direction to "rounded half up to the nearest whole cent" (PRD originally said only "rounded to the nearest whole cent", silent on direction) — `implementation/services/calculations.py:82` and `services/utils.py:114-117` (`round_half_up` uses `ROUND_HALF_UP`).
- §3.6 (Back Pay / entitlement_start_date semantics) — insert — pin that the `BenefitAward.entitlement_start_date` field stores the *effective start* of the back-pay window (the max of EOD+5-months and the retroactive floor), not the EOD-plus-five-months value in isolation — `implementation/services/calculations.py:115-122` and `services/state.py:105,186` (`ent_start = calc.entitlement_start_date(...)` then stored on award).
- §3.8 (Suspend / Reinstate state-precondition errors) — insert — pin the error code used when suspend is called on a non-`ACTIVE` award or reinstate on a non-`SUSPENDED` award: `ERR_INVALID_APPLICATION_STATE` (409) is reused for both — `implementation/routes/awards.py:64-69, 80-85`.
- §3.9 (CDR completion preconditions) — revise — pin that completing a CDR requires the CDR's own `outcome` to still be `PENDING`; re-completing an already-completed CDR is rejected with `ERR_INVALID_APPLICATION_STATE` (409) — `implementation/routes/cdr.py:102-107`.
- §3.9 (Subsequent CDR diary classification) — revise — pin that the next CDR scheduled after a `CONTINUED` completion uses the *same* `diary_classification` as the just-completed review — `implementation/services/state.py:255-258`.

**Step 7 diff cross-reference**: Both Step 7 fixes (`["items"]` indexing and the spurious `record_hearing_held` before `decide_hearing`) were test-side bugs — Step 7 itself states "Fixes applied to `implementation/`: none. The implementation was already PRD-faithful." For those items: PRD §2.2 already pins `data` as the list itself, and PRD §3.5 already pins the hearing decision transition as `SCHEDULED → APPROVED/DENIED`. No PRD patch was needed for either Step 7 item.

---

## Pipeline complete — 2026-05-27T01:18:00Z

All 8 pipeline steps executed successfully. Final artifact: 63/63 tests passing across 8 parallel per-test-server isolation rounds; `PRD_FINALIZED.md` produced with 5 inline insertions / 2 revisions covering 7 minor PRD pin-downs (none of which arose from the Step 7 diff itself — Step 7 changes were all test-side bugs).
