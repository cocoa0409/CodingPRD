# Worklog — task_0031_physical_therapy_rehab

## Step 1: Create task directory — 2026-05-28T00:00:00Z

Task directory `tasks/task_0031_physical_therapy_rehab/` was pre-created by the user; orchestrator created `workspace/` subdirectory.

## Step 2: Generate scaffold — 2026-05-28T00:00:00Z

All three files written successfully and pass the scaffold_lint.

**Files written:**
- `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0031_physical_therapy_rehab/SCAFFOLD.yaml`
- `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0031_physical_therapy_rehab/SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0031_physical_therapy_rehab/SCAFFOLD_CORNER_DESIGN.yaml`

**Top-level counts (SCAFFOLD.yaml):**
- Entities: 10 (Patient, Therapist, VeteranReferral, PlanOfCare, Evaluation, AuthorizationGrant, Visit, HomeExerciseProgram, MIPSQualityMeasure, DischargeAssessment)
- State machines: 5 (PlanOfCare, Visit, AuthorizationGrant, VeteranReferral, MIPSQualityMeasure)
- Calculations: 11 (evaluation_units, visit_planned_units, visit_billable_units, units_consumed_running, units_finalized_running, visit_billed_amount, cumulative_billed, capped_poc_limit, capped_poc_posture, mips_composite_score, discharge_outcome)
- Validations: 20 (across auth, existence, state, OCC, business_safety/fiscal/constraint/temporal/referential, generic)
- Endpoints: 42 (incl. 1 `/_clock/set_current_utc` test-driving endpoint)
- Errors: 18
- Roles: 5 (PlatformAdmin, CaseManager, Therapist [entity_backed], BillingClerk, VAReferralCoordinator)
- Concurrency rules: 2 (both OCC on PlanOfCare.version — recertify and visit-finalize)

**Design counts:**
- §1.8 Difficulty design: 9 rule_ids × 2 instances = 18 instances (meets minimum)
- §1.9 Corner design: 9 sections, 36 instances (33 active + 3 `excluded_because:` stubs pointing at §1.8 difficulty instances)

**Lint:** `VERDICT: clean lint` across 488 calls scanned in §1.8+§1.9 against the 42-endpoint §1.5 table; all 18 FKs in §1.1 have reverse-reachability in §1.5.

**Key design adjudications:**

- **Complexity profile**: quota_allocation primary + compliance_audit secondary; entity_topology=hybrid; state_machine_shape=branching; role_model=peer_roles. Selected to honor the scenario's unit-hour authorization (quota), Capped Plan of Care (compliance), MIPS reporting (audit), and the multi-role workflow (Therapist/BillingClerk/CaseManager/VA coordinator/Admin).

- **Dual-variant calc on different entity domains**: Visit (cost-accounting: planned_units vs billable_units) AND MIPSQualityMeasure (risk-scoring: score under revise vs at submit). Satisfies Rule 1's cross-domain requirement.

- **Combinatorial in different modes**: mips_composite_score (mode a — 4 inputs with non-linear min() caps) AND visit_billed_amount (mode b — rounding-order pinned: `round_half_up(rate*0.5)` PER-UNIT then sum).

- **Capped POC limits tuned for testability**: Cap values were lowered (MEDICARE=20000¢ instead of realistic $2,300=230000¢) so that the boundary instances can be reached with 1–3 visits rather than 20+. Documented in the §1.3 capped_poc_limit constants.

- **MIPS131 base lowered to 18.0** so that the REJECTED branch (composite_score < 30.0) is actually reachable; with base ≥ 30 every adjudicate would ACCEPT.

- **Cyclic state machine** on MIPSQualityMeasure (DRAFT→DRAFT self-loop via revise) chosen to satisfy Rule 3's non-linear shape requirement on a second entity.

- **OCC scoped to PlanOfCare.version only** (per §1.2.1's "only sanctioned mechanism"); both concurrency rules guard write endpoints that bump PlanOfCare.version (recertify directly, finalize via the cumulative_billed cascade).

- **Test-driving endpoint** `/_clock/set_current_utc` added (§1.5 priority ladder rung 3) because no plausible business endpoint can advance the server clock; required to reach time-gated state-machine auto-transitions (RECERT_DUE, EXPIRED).

- **Capped POC boundary precision**: The exact 18000¢ (= 0.90 * 20000¢) was not reachable with the rate schedule's integer per-unit prices; the instance was anchored at cumulative=18200¢ (>=18000¢ holds; ratio 0.91 → AT_CAP_WARNING), documented inline in the test_recipe `setup` prose.

## Step 3: Copy INSTRUCTION.md — 2026-05-28T00:00:00Z

Copied root `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-05-28T00:00:00Z

**PRD generation complete for task_0031_physical_therapy_rehab.**

**Output file:** `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0031_physical_therapy_rehab/workspace/PRD.md`

**Stats:** 292 lines, 6,531 words.

**Sections produced (domain-derived skeleton):**
- §1. Introduction (2 paragraphs framing the unit-hour authorization + Capped PoC + MIPS reporting domain)
- §2. Global Specifications (11 subsections):
  - 2.1 User and Role-Based Access Control (five roles enumerated; `Therapist` entity-backed identity + four opaque roles all explicitly translated per skill §2.1 contract)
  - 2.2 API Response Structure (verbatim from `section-2.2-response-structure.md`)
  - 2.3 Pagination
  - 2.4 Common Resource Properties
  - 2.5 Nested Resource Retrieval and Path Validation
  - 2.6 Optimistic Concurrency on Plans of Care (both OCC rules with `expected_plan_of_care_version` + `ERR_STALE_PLAN_VERSION` 412)
  - 2.7 Capped Plan of Care — the Fiscal Backbone (all five insurance-type cap values pinned-once at activation; three posture buckets with boundary inclusivity)
  - 2.8 Precision and Rounding (MPPR per-unit-then-sum + MIPS half-up to 2dp)
  - 2.9 Hierarchical Consistency and Cascading State (preview of the three cascade chains)
  - 2.10 Time, Test-Driving the Clock, and Auto-Transitions
  - 2.11 Validation Priority Ordering (full priority chain spelled out)
- §3. Business Logic & Workflows (10 subsections, lifecycle-chronological grouping):
  - 3.1 Patient Intake and Therapist Onboarding
  - 3.2 Veteran Referrals and Plan-of-Care Creation (depth-2 activate cascade)
  - 3.3 Evaluations and the Eight-Minute Rule
  - 3.4 Authorization Grants — the Unit-Hour Pool (closed-closed window overlap, running-sum aggregation)
  - 3.5 Visit Lifecycle — Scheduling, Completion, and Finalization (planned/chronological dual variants, MPPR billing with worked example, half-open visit overlap)
  - 3.6 Recertification, Discharge, and Plan Termination (depth-3 discharge cascade + clock-driven expiry cascade)
  - 3.7 Home Exercise Programs and MIPS Quality Reporting (full composite-score formula in precise prose)
  - 3.8 Discharge Assessment and Outcome Classification (three-bucket outcome with inclusive thresholds)
  - 3.9 Veteran Referral Termination
  - 3.10 Therapist Licensing Demo Policy (the priority-420 demo rule)
- §4. Endpoint Definitions (4-column table; all 41 endpoints)
- §5. Error Code Catalogue (2-column table; all 18 error IDs)

**Hard Contracts:** Field coverage PASS (62/62), Rule coverage PASS (all priority chain + 2 OCC + 18 transitions + 11 calcs + 18 validations + side effects + 4 sibling-branch symmetry groups), Path purity PASS (0 path tokens in §3).

**Scattering notes:**
- `expected_plan_of_care_version` OCC contract placed in §2.6 (cross-cutting) and re-referenced from §3.5 visit-finalize + §3.6 recertify operations.
- MPPR per-unit-then-sum rounding ordering placed in §2.8 AND restated in §3.5 with worked 4-unit `CPT_97140_MANUAL` → 8750 cents example.
- Eight-minute-rule buckets enumerated twice (§3.3 evaluation, §3.5 visit) to make dual-variant divergence example land cleanly.
- `INACTIVE` patient status reserved in enum but unreachable by any transition; disclosed honestly in §3.6.
- All 18 error IDs appear in §2/§3 prose at firing point, not only in §5 table.

## Step 5: Generate unit tests — 2026-05-28T00:00:00Z

**Test infrastructure (Stage 1) — 9 files in `test_helpers/`:**
- `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`

**Test suite (Stage 2) — 16 files in `test_suite/`:**
- `conftest.py`
- `test_01_difficulty_dual_variant_calc.py` (5)
- `test_02_difficulty_combinatorial_formula.py` (4)
- `test_03_difficulty_non_linear_state_machine.py` (4)
- `test_04_difficulty_transitive_cascade.py` (4)
- `test_05_difficulty_priority_pair_validation_conflict.py` (4)
- `test_06_difficulty_boundary_precision_check.py` (4)
- `test_07_difficulty_cross_entity_state_dependency.py` (4)
- `test_08_difficulty_resource_temporal_overlap.py` (4)
- `test_09_difficulty_compensating_invariant.py` (4)
- `test_10_corner_entities.py` (7)
- `test_11_corner_state_machines.py` (7)
- `test_12_corner_calculations.py` (4)
- `test_13_corner_validations.py` (5)
- `test_14_corner_endpoints_errors_rbac.py` (5)
- `test_15_corner_cross_cutting_consistency.py` (5)

**Total tests emitted: 70**

**Queue breakdown:**
- Queue A (Difficulty): 37 tests across 18 instances (all 9 rules × 2 instances each, each instance ≥2 tests; some get 3)
- Queue B (Corner): 33 tests across 32 non-stub instances (each ≥1 test)

**Instances skipped: 0.** Every difficulty and non-stub corner instance had verbatim PRD coverage and unique derivability. The 3 corner stubs flagged `excluded_because:` were correctly NOT translated.

**Every test docstring ends with the mandatory `Design: …` tag** (70/70). PRD citations are verbatim quotes that grep cleanly against PRD.md. No `pytest.mark.skip`, `skipif`, or `xfail` anywhere.

## Step 6: Generate Flask implementation — 2026-05-28T00:00:00Z

**File tree (`workspace/implementation/`):**

```
implementation/
├── start.sh                # foreground exec launcher, $PORT (default 10000), 0.0.0.0
├── requirements.txt        # flask==3.0.3
├── app.py                  # Flask factory + error handlers + blueprint registry
├── db.py                   # in-memory stores, logical clock, UUID/timestamp helpers, RLock
├── errors.py               # APIError class + 18 error_id constants from §1.6 / §5
├── response.py             # PRD §2.2 envelope helpers
├── middleware.py           # X-User-ID / X-User-Role extraction; entity-backed Therapist check
├── routes/                 # 10 blueprint modules covering 42 endpoints
└── services/               # validation / calculations / cascades
```

**LOC:** ~2,812 across 18 Python files. 42 endpoints registered; boots <2s with empty stores.

**Notable design choices:**

- **Concurrency strategy.** Single process-wide `threading.RLock` (`db.mutation_lock`) wraps every mutating handler; reads are lock-free. OCC pin on `expected_plan_of_care_version` handles cross-request ordering for POC cascades.
- **Time handling.** Two-clock model — logical clock (default `2025-01-01T00:00:00.000Z`, mutated by `/_clock/set_current_utc`) drives ALL business-rule comparisons AND every `created_at`/`updated_at`. Wall clock is used only for `meta.api_request_timestamp`. The clock endpoint re-evaluates all four §2.10 time-gated auto-transitions in priority order with `(created_at, id)` sort.
- **Rounding.** `decimal.Decimal` + `ROUND_HALF_UP`. MPPR is per-unit-rounded-then-summed exactly as PRD §2.8/§3.5 mandate. Capped posture uses integer cross-multiplication (`cumulative * 100 >= limit * 90`) to avoid float boundary surprises at the 90% line.
- **Role/identity.** PRD §2.1 verbatim — five roles. `require_auth(allowed_roles)` enforces priority 100/110/115 in one call (header presence → role allowed → Therapist-entity-existence). Full §2.11 priority order honored.
- **No seeding.** All stores empty at module load; logical clock is the only pre-initialized state.

## Step 7: Run tests + iterate to PASS — 2026-05-28T00:00:00Z

All 8 rounds pass with 70/70.

- **Iterations run:** 3 (initial diagnostic sweep, then two fix-and-rerun cycles).

- **Tests deleted:** None.

- **Fixes applied to `test_helpers/`:**
  - `test_helpers/fixtures.py` — `complete_visit()`: before issuing the COMPLETE request, the fixture now GETs the visit, reads `scheduled_start_utc`, and advances the server clock to that instant via `set_clock`. PRD §3.5 requires "today (UTC) is on or after the date portion of `scheduled_start_utc`" for the SCHEDULED → COMPLETED transition; the previous fixture set the clock to 2026-06-01 then completed a visit scheduled at 2026-06-02, so the PRD-faithful implementation correctly rejected with ERR_INVALID_STATE. This single change unblocked 17 failures across tests 01, 04, 05, 06, 09, 11, 12, 14, 15.

- **Fixes applied to `test_suite/`:**
  - `test_suite/test_05_difficulty_priority_pair_validation_conflict.py` — `test_activate_va_poc_missing_referral_returns_va_referral_required` rewritten to `test_activate_va_poc_with_cancelled_referral_returns_va_referral_required`. The original test attempted to activate a VA_TRICARE POC that was created WITHOUT a `veteran_referral_id`, but PRD §3.2 verbatim requires VA_TRICARE POC creation to include `veteran_referral_id`, so the implementation correctly rejected at POC create. Switched to a reachable sub-condition of ERR_VA_REFERRAL_REQUIRED: build the POC with a referral, then CANCEL the referral before activation so the activation precondition "the referenced VeteranReferral must be in ISSUED status" trips.
  - `test_suite/test_13_corner_validations.py` — `test_capped_poc_exceeded_blocks_visit_finalize` setup loop reduced from 3 finalizes to 2. MEDICARE cap (PRD §2.7) is 20,000¢; each 90-minute CPT_97110_THER_EX visit bills 11,200¢ (6 units → 3200 + 5×1600), so 2 finalizes already push cumulative_billed_cents to 22,400¢ and capped_status to EXCEEDED. The previous test issued a 3rd finalize in setup which was correctly rejected by the EXCEEDED gate (which is the very rule under test), so setup blew up before the actual assertion.

- **Fixes applied to `implementation/`:** None. The implementation correctly enforced every PRD rule; all failures traced to test_helpers fixtures or test setup constructing PRD-inconsistent preconditions.

- **Final result:** 8 parallel rounds × 70 tests each = **all 70 passing in all 8 rounds**, no flakiness.

## Step 8: PRD_FINALIZED minimal patch — 2026-05-28T00:00:00Z

**Output file:** `workspace/PRD_FINALIZED.md`

**Line counts:** PRD.md = 292 lines, PRD_FINALIZED.md = 292 lines, **delta = 0 lines (0.0%)**.

**Changes:** None. PRD_FINALIZED.md is a verbatim copy of PRD.md. All three Step 7 diff items are pure test-side fixes; Step 7 records 0 implementation/ fixes.

### Per-item analysis (pre-edit search log)

**Item 1 — `test_helpers/fixtures.py` `complete_visit()` clock advance**
- (a) Subject: PRD §3.5 SCHEDULED → COMPLETED time precondition.
- (b) Impl paths: `routes/visits.py::complete_visit` 246-256; `services/validation.py::clock_today_utc` 117-121; cross-checked `cancel_visit` 341-352 and `no_show_visit` 372-379.
- (c) No edit. PRD §3.5 already states the rule verbatim and impl matches; the fixture was pre-staging the wrong clock.

**Item 2 — `test_suite/test_05` activate-VA test rewrite**
- (a) Subject: PRD §3.2 VA_TRICARE create-side `veteran_referral_id` requirement + activate-side ERR_VA_REFERRAL_REQUIRED preconditions.
- (b) Impl paths: `routes/plans_of_care.py::create_plan_of_care` 72-111; `activate_plan_of_care` 185-210; `routes/visits.py` 99-120.
- (c) No edit. PRD §3.2 verbatim mandates `veteran_referral_id` at create and the three activate-time preconditions; the original test path was unreachable because PRD blocks it at create.

**Item 3 — `test_suite/test_13` capped-POC setup loop reduced 3 → 2**
- (a) Subject: PRD §2.7 MEDICARE cap × PRD §3.5 MPPR on 6-unit CPT_97110 visit.
- (b) Impl paths: `services/calculations.py::CPT_RATE_CENTS` 49-54, `eight_minute_units` 21-43, `visit_billed_cents` 62-77, `CAPPED_LIMITS_CENTS` 84-90, `capped_posture` 97-110; `routes/visits.py::finalize_visit` 311-316.
- (c) No edit. PRD pins the MEDICARE cap, the MPPR formula, the CPT rate, and the 8-minute-rule formula verbatim; two finalized visits → 22,400¢ > 20,000¢ → EXCEEDED, exactly what the impl exhibits. The Step 7 fix corrected setup arithmetic, not the contract.

## Step 9: PRD_COMPLETED full scan — 2026-05-28T00:00:00Z

**File stats**
- `PRD_FINALIZED.md`: 292 lines, 47,446 chars
- `PRD_COMPLETED.md`: 292 lines, 52,474 chars
- Char delta: +5,028 chars (all in-paragraph; no new sections)

**Counts**
- Ambiguity-pins: 16
- Mismatch-revisions: 1 (§2.11 example would have contradicted impl's actual priority chain)

**Per-change bullets**

- §2.2 — insert — ambiguity — pinned `api_request_id` format as `req_` + 20 lowercase hex chars — db.py:21-23
- §2.3 — insert — ambiguity — pinned pagination-input rejection (`ERR_INVALID_REQUEST` 400) for non-integer/out-of-range limit/offset; `(created_at, id)` tiebreaker; exact `has_more` formula — response.py:30-46, 61-79
- §2.4 — insert — ambiguity — pinned `id` as plain UUID 8-4-4-4-12 hex; `created_at`/`updated_at` sourced from logical clock (not wall) — db.py:29-48, 127-139
- §2.7 — insert — ambiguity — pinned `capped_dollar_limit_cents` is `null` while plan is DRAFT — routes/plans_of_care.py:126
- §2.10 — insert — ambiguity — pinned clock seed `2025-01-01T00:00:00.000Z`, endpoint response shape, ordered re-evaluation sequence with exact predicates, `(created_at, id)` visit order, and `ERR_INVALID_REQUEST` on malformed `to_iso8601` — db.py:106, routes/clock.py:17-33, services/cascades.py:216-285
- §2.11 — revise — mismatch — replaced the "missing-field vs license" example with the actual flow: body-shape validation runs after auth/role but before FK lookup; named cross-field invariants surface `ERR_INVALID_REQUEST` — services/validation.py:21-67
- §3.1 — insert — ambiguity — pinned therapist `full_name` length 1-120, NPI regex, `license_state` regex, `ERR_INVALID_REQUEST` on NPI duplicate — routes/therapists.py:27-41
- §3.2 — insert — ambiguity — pinned `referring_va_facility_code` regex, `referral_authorization_number` non-empty + `ERR_INVALID_REQUEST` on duplicate; no patient-veteran-flag check at referral-issue — routes/veteran_referrals.py:38-59
- §3.2 — insert — ambiguity — pinned `diagnosis_icd10` regex; certified-window range/length violations → `ERR_INVALID_REQUEST` 400; missing VA `veteran_referral_id` → `ERR_INVALID_REQUEST`; supplying on non-VA → `ERR_INVALID_REQUEST`; `initial_evaluation_id` starts `null` — routes/plans_of_care.py:73-129
- §3.4 — insert — ambiguity — pinned `effective_to ≥ effective_from`, `effective_to ≤ POC.certified_end_date`, mismatched/improper `veteran_referral_id` all → `ERR_INVALID_REQUEST` — routes/authorization_grants.py:44-79
- §3.5 — insert — ambiguity — pinned that any Therapist may complete (caller need not equal visit's `therapist_id`); three complete-preconditions surface `ERR_INVALID_STATE`; grant-not-ACTIVE → `ERR_INVALID_STATE`; in-flight overrun → `ERR_AUTHORIZATION_EXHAUSTED` — routes/visits.py:212-269
- §3.5 — insert — ambiguity — pinned that cancel/no-show carry no ownership check; timing/state failures → `ERR_INVALID_STATE` 409 — routes/visits.py:331-386
- §3.7 — insert — ambiguity — pinned HEP `prescribed_on` violation → `ERR_INVALID_REQUEST` 400; HEP accepts any Therapist (no plan-PT match); §3.10 licensing does not apply on HEP create — routes/home_exercise_programs.py:22-76
- §3.7 — insert — ambiguity — pinned MIPS period-end violation → `ERR_INVALID_REQUEST` 400; `composite_score` is `null` until first revise/submit — routes/mips_measures.py:83-104
- §3.7 — insert — ambiguity — pinned MIPS revise accepts optional `numerator_met`/`measure_code` (keeps existing when omitted); does not re-run eligibility; submit/revise on non-DRAFT → `ERR_INVALID_STATE` 409; adjudicate treats `null` `composite_score` as 0.0 and does not recompute — routes/mips_measures.py:127-202
