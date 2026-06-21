# Worklog — task_0015_401k_retirement_plan

## Step 1: Create task directory — 2026-05-27T00:00:00Z

Created `tasks/task_0015_401k_retirement_plan/workspace/` (pre-allocated path).

## Step 2: Generate scaffold — 2026-05-27T07:33:00Z

**Worklog Summary — Scaffold generation for task_0015_401k_retirement_plan**

Files written into `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0015_401k_retirement_plan/`:

| File | Size | Lines |
|------|------|-------|
| SCAFFOLD.yaml | 55,887 B | 1378 |
| SCAFFOLD_DIFFICULTY_DESIGN.yaml | 57,012 B | 1063 |
| SCAFFOLD_CORNER_DESIGN.yaml | 64,085 B | 1312 |

**Lint verdict** (`python3 skills/prd-bench-scaffold-generator/scaffold_lint.py tasks/task_0015_401k_retirement_plan/`):
```
Coverage
  §1.5 endpoints declared:    42
  §1.1 entities declared:     7
  §1.8 instances scanned:     18
  §1.9 instances scanned:     32
  Calls scanned (§1.8+§1.9):  367

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Complexity profile (chosen via §0.1–§0.4):**
- Primary archetype: compliance_audit; secondary: pricing_engine
- Layers: cascading_side_effects, rate_threshold_triggers, derived_field_reconciliation, dual_variant_calculation
- Topology: hybrid (flat top-level entities with FK cross-references)
- State-machine shape: branching (with revert cycles on Plan and Participant)
- Role model: peer_roles (PlanAdmin / Participant / Custodian)
- Consistency: immediate
- Difficulty band: **Advanced** (7 entities, 42 endpoints, 12 errors, 5 calculations w/ variants, 6 state machines)

**§1.1 Entities (7):** Plan, Participant, ContributionPeriod, Loan, HardshipWithdrawal, RMDDistribution, VestingEvent (append-only, common_fields:false).

**§1.2 State machines (6):** Plan (DRAFT→ACTIVE→FROZEN↔ACTIVE→TERMINATED), Participant (PENDING→ENROLLED↔SUSPENDED→TERMINATED), ContributionPeriod (OPEN→CLOSED→REVERSED), Loan (REQUESTED→DISBURSED→REPAID|DEFAULTED), HardshipWithdrawal (REQUESTED→APPROVED|DENIED→PAID), RMDDistribution (PENDING→PAID|MISSED). Branching cycles on Plan and Participant satisfy non-linear shape requirement.

**§1.2.1 Concurrency rules (1):** `plan-terminate-stale-version` — OCC on `Plan.version` for terminate; tested by freeze/unfreeze advancing version while a stale `expected_plan_version=v_active` is held.

**§1.3 Calculations (5):** tiered_employer_match (dual variant TIERED/SAFE_HARBOR_ENHANCED), rmd_required_distribution (dual variant UNIFORM_LIFETIME/JOINT_LIFE), vested_balance (CLIFF_3/GRADED_6, constraint_propagation), loan_amortization (pinned ceil-per-payment rounding order), max_hardship_amount (three-input nested min with age branch).

**§1.4 Validations:** 15 priorities, ordered auth (1–2), existence (3), state (4), OCC stale (5), business_safety (6–8), business_constraint (9), business_fiscal (10–11), business_temporal (12–13, overlap rules), business_referential (14), business_constraint final fields (15).

**§1.5 Endpoints:** 42 — full CRUD across all entities, action endpoints for each state transition, sub-resource and filtered-list GETs covering every FK for reverse-reachability, plus two test-driving endpoints `POST /_clock/set_current_utc` and `POST /_system/year-tick`. `api_prefix:""` (multiple top-level resources). All entity-collection segments derivable by lint.

**§1.6 Errors:** 12 (ERR_UNAUTHENTICATED, ERR_FORBIDDEN, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_STALE_VERSION, ERR_LOAN_ALREADY_OUTSTANDING, ERR_LOAN_EXCEEDS_LIMIT, ERR_DEFERRAL_LIMIT_EXCEEDED, ERR_NO_HARDSHIP_HEADROOM, ERR_RMD_NOT_REQUIRED, ERR_JOINT_LIFE_INELIGIBLE, ERR_DUPLICATE_RMD_YEAR). Every error triggerable by at least one instance.

**§1.7 RBAC:** PlanAdmin (opaque), Participant (entity_backed:Participant), Custodian (opaque, read-only).

**§1.8 Difficulty design (18 instances, 9 rules × 2):** dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant — each with 2 instances.

**§1.9 Corner design (37 entries — 32 active + 5 `excluded_because` stubs):** Walks all nine claim-extraction-guide sections — entities (creation/not-found/required-fields/defaults/system-fields/immutability), state_machines (invalid_transition, terminal_state_lockdown, cross_entity_precondition stub, cascade stub, side_effect_execution for hardship pay), calculations (deferral 300 first-tier-only, deferral 0, GRADED yos=1/yos=4, hardship penalty age≥59 boundary, RMD UNIFORM age=75), validations (deferral_limit, loan_exceeds_limit, joint_life_ineligible, existence-vs-state stub, no_hardship_headroom), endpoints (filtered list, pagination defaults, clock-set side effect, year-tick MISSED auto-transition), errors (invalid_state via double-enroll, stale_version via freeze/unfreeze), rbac (Participant→403 on POST /plans, Custodian denied on activate, missing-headers→401), cross_cutting (OCC stub, atomic cascade non-application on stale version, derived-field reconciliation post-default, pagination_with_filtering), consistency_model (immediate visibility after close).

**Design adjudications:**
- Chose `api_prefix:""` so the lint's collection-segment heuristic resolves all 7 entities (Plan→plans, Participant→participants, etc.); each entity has both single-resource `GET /<segment>/{id}` and filtered-list `GET /<segment>` so every FK satisfies reverse-reachability check (f).
- VestingEvent is the one `common_fields:false` immutable append-only entity; added `GET /vesting-events/{id}` solely so the lint's segment derivation works.
- `concurrency_rules` deliberately holds only the ONE true OCC case (plan terminate vs config-bumping operation). All other apparent "races" (e.g., double-disburse of a loan) are state preconditions and live in §1.2/§1.4, not §1.2.1.
- All ages, years_of_service, and arithmetic literals in `assert:` lines were verified by running the formula in Python before being pinned (e.g., loan monthly payment 86527 for P=1000000, n=12, r=700bps; RMD UNIFORM 37735 at factor 26.5; JOINT_LIFE 36496 at factor 27.4; tiered match 17500 vs safe-harbor 20000 at deferral 400 bps and gross 500000).
- No forbidden vocabulary anywhere ("simultaneously"/"first-writer-wins"/"in parallel"/"race winner|loser") — confirmed by grep.
- DOBs initially used 1953-01-01 for "age 73" but Python integer-div-365 placed that at age 74 at end-of-2026; corrected every DOB pegged to a specific age boundary (used 1954 for age 73, 1955 for age 72, 1952 for age 75) and re-ran lint clean.

## Step 3: Copy INSTRUCTION.md — 2026-05-27T07:35:00Z

Copied `INSTRUCTION.md` to `tasks/task_0015_401k_retirement_plan/workspace/INSTRUCTION.md` (1424 B).

## Step 4: Generate PRD — 2026-05-27T07:40:00Z

**Worklog summary (Step 4: Generate PRD)**

Generated `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0015_401k_retirement_plan/workspace/PRD.md` (237 lines) from `SCAFFOLD.yaml`.

Section coverage:
- §1 Introduction — 2-paragraph framing (audit/compliance + regulatory envelope angle)
- §2 Global Specifications — 10 subsections: 2.1 Auth & Roles, 2.2 Response Structure (verbatim), 2.3 Pagination, 2.4 Common Resource Properties (incl. VestingEvent exception), 2.5 Monetary Precision, 2.6 Hierarchical Consistency & Cascade Discipline (+ conservation invariant), 2.7 OCC on Plan Termination, 2.8 Nested Resource Retrieval, 2.9 Vesting Discipline, 2.10 Validation Ordering & Error Precedence
- §3 Business Logic — 8 subsections organized by entity lifecycle: 3.1 Plan, 3.2 Participant, 3.3 Contribution Periods + Employer Match (both TIERED and SAFE_HARBOR_ENHANCED variants), 3.4 Loans (incl. amortization), 3.5 Hardship Withdrawals (incl. max_hardship_amount), 3.6 RMD (incl. UNIFORM_LIFETIME and JOINT_LIFE variants), 3.7 VestingEvent (immutable), 3.8 Test-driving capabilities
- §4 Endpoint table — 4-column (Method, Path, Description, Authorized Role(s)); 42 endpoints
- §5 Error table — 2-column (Error ID, HTTP Status); 13 errors

Hard contracts (all PASS):
- Contract 1 (Field-Name Coverage): 48 required identifiers; all present in PRD backticks. PASS
- Contract 2 (Rule Coverage): 15 validations with priority all prose-ordered in §2.10; 1 OCC rule (plan-terminate-stale-version) with write_endpoint + `expected_plan_version` + `ERR_STALE_VERSION` + HTTP 412 all named in §2.7; all 19 state-machine transitions covered with preconditions and side-effects (incl. depth-2/3 cascades); all 5 calculations expressed as precise prose (no operator syntax, no fuzzy hedging) — tiered_employer_match dual variants disambiguated at 4%-deferral worked-case (TIERED→3.5%, SAFE_HARBOR→4%); rmd_required_distribution dual variants (uniform vs joint-life table) including age-gap eligibility rule; max_hardship_amount three-cap min with max(0, ...) clamp and age<59 penalty branch; loan_amortization with pinned ceil-at-scalar rounding order; vested_balance with both CLIFF_3 (0%/100% at 3 yrs) and GRADED_6 (0/20/40/60/80/100 at 0/1/2/3/4/5+ yrs) schedules. PASS
- Contract 3 (§3 Path Purity): 234 backtick tokens scanned in §3; 0 starting with `/`; 0 bare HTTP method tokens; 0 method+path combined. All endpoint references rewritten via state-transition framing or role+action verb. PASS

Scaffold inconsistencies flagged: none. `Participant.status` field is named `enrollment_status`; PRD distinguishes correctly between participant's `enrollment_status` and other entities' `status`. `api_prefix` is empty so endpoints use bare paths. Design files were not opened.

## Step 5: Generate unit tests — 2026-05-27T08:00:00Z

**Task: task_0015_401k_retirement_plan — Step 5 (unit-test generation)**

### Generated files
`test_helpers/` (9 files): __init__.py, types.py, api_client.py, api_errors.py, assertions.py, factories.py, constants.py, test_users.py, fixtures.py
`test_suite/` (9 files, 69 tests): conftest.py, test_01_entities_crud.py (7), test_02_state_machines.py (8), test_03_calculations.py (18), test_04_cascades.py (5), test_05_validations.py (16), test_06_endpoints_and_lists.py (5), test_07_security.py (3), test_08_concurrency_invariants.py (7)

### Test counts by queue
- Queue A (Difficulty): 36 tests / 18 of 18 instances, each ≥2 tests
- Queue B (Corner):     33 tests / 32 of 32 non-stub instances, each ≥1 test
- Total: 69 tests

### Instances skipped: 0
Every instance translated; all 5 `excluded_because:` stubs in Corner were left untranslated (they cross-reference real Difficulty instances).

### Coverage audit
- Difficulty 18/18 — PASS
- Corner 32/32 non-stub — PASS
- Excluded stubs 5/5 valid cross-refs — PASS
- 0 orphan tags, 0 untagged, 0 dual-tagged tests — PASS
- 78/78 PRD-quoted citations verified by grep against PRD.md — PASS
- 0 `pytest.mark.skip` / `skipif` / `xfail` occurrences — PASS
- All 18 generated Python files parse cleanly — PASS

## Step 6: Generate implementation — 2026-05-27T08:11:00Z

**Task 0015 (401(k) Retirement Plan) — Implementation Generator Report**

### Files created (20 source files, ~2,423 LoC)
start.sh, requirements.txt (Flask==3.0.3), app.py, db.py, errors.py, response.py, middleware.py, routes/{plans, participants, contribution_periods, loans, hardships, rmd_distributions, vesting_events, system}.py, services/{calculations, entities, clock_and_age, validators}.py

### Design notes
- In-memory only, empty at boot. No seeding. Clock advanced via `/_clock/set_current_utc`.
- Integer cents; floor via `//`; loan amortization `math.ceil` only at per-payment scalar; hardship `max(0, min(...))` clamp.
- Tiered match: floor per tier then sum (critical TIERED vs SAFE_HARBOR_ENHANCED divergence at 4% deferral).
- Cascade depth 3 (plan terminate → participants → loans; contrib close → balances → vested).
- OCC only on plan terminate (`expected_plan_version` required; ERR_STALE_VERSION → 412).
- Validation precedence (§2.10): decorator auth → existence → state → OCC → business → shape.
- VestingEvent serialized without `updated_at`/`version` (PRD §2.4 exception).
- Participant role identity-bound via `X-User-ID == participant_id`; lists auto-filter; otherwise ERR_FORBIDDEN.
- Joint Life eligibility strict `>` 10 years (per PRD §3.6).
- §402(g) cap check compares already-CLOSED periods in same `plan_year` plus current period.

### PRD ambiguities resolved (recorded inline as code comments)
1. Loan term upper bound 1..180 inclusive (broader bound to cover primary-residence class).
2. GRADED_6 at YoS=5 → 100% (PRD §2.9 + scaffold table agree).
3. Uniform/Joint Life tables: tabulated Uniform 73–120; Joint Life fallback `uniform + (gap-10)*0.5` guarantees Joint > Uniform.
4. RMD pay pro-rata: `ee_share = floor(distributed * ee / total)`, employer absorbs rounding remainder.
5. Penalty age threshold: `AGE_PENALTY_THRESHOLD = 59` (PRD §3.5 invokes §2.5 floor-to-whole-years rule).

### Boot verification
`bash start.sh` boots cleanly. HTTP-200 within ~2s on `0.0.0.0:$PORT`. Smoke battery covered: success envelope, full plan-activate-enroll-contribute-close path with TIERED 15200 match on $3800 gross; SAFE_HARBOR path; loan disburse amortization 3510 on 80000@5%/24mo; one-loan-at-a-time; loan-exceeds-limit; hardship approve+pay with employee-first and 10% age<59 penalty; RMD age-gate, duplicate-year, joint-life ineligible; OCC stale-version; cascade depth 3 on plan terminate.

## Step 7: Run tests and iterate — 2026-05-27T08:30:00Z

**Iterations run:** 2 (1 initial 8-round sweep showing 3 failing tests deterministically across all 8 rounds; 1 post-fix 8-round sweep showing all 69/69 passing in every round).

**Tests deleted:** None. All three failing tests had verbatim PRD coverage with unique derivability; they were salvageable by fixture/expectation fixes or by an implementation bug fix.

**Fixes applied to `test_suite/`:**

- `test_suite/test_03_calculations.py::test_rmd_joint_life_at_age_73_spouse_60_balance_1m_yields_36496` — Fixture bug: the test chose `spouse_date_of_birth="1966-01-01T00:00:00Z"` expecting spouse_age=60 at year-end 2026, but PRD §3.6's age formula `floor((Dec 31 - DOB).days/365)` yields age 61 for that DOB (22279/365 = 61.04). The Joint Life lookup miss made the implementation extrapolate factor 27.5 instead of the (73,60)=27.4 the test expected. Changed to `1966-06-30T00:00:00Z` so the PRD age formula yields exactly 60.
- `test_suite/test_06_endpoints_and_lists.py::test_set_clock_endpoint_advances_age_for_rmd_age_check` — Fixture bug: the test chose participant `date_of_birth="1954-01-01T00:00:00Z"` expecting year-end-2027 age=73 and factor 26.5, but PRD §3.6's formula yields 27027/365=74.05 → age 74 → factor 25.5. Changed to `1954-06-30T00:00:00Z` so floor(26847/365)=73, matching the expected factor 26.5 and required amount 37_735.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `implementation/`:**

- `workspace/implementation/routes/plans.py::terminate_plan` — Plan-terminate cascade was not applying PRD §3.4's deemed-distribution semantics for cascaded loan defaults. PRD §3.4 explicitly: "Alternatively, a default — transitioning DISBURSED → DEFAULTED, initiated either by a plan administrator or as a cascaded consequence of the participant being terminated — treats the unpaid principal as a deemed distribution against the participant's vested employer match: the participant's employer_balance_cents is reduced by the loan's prior outstanding_principal_cents... vested_employer_balance_cents is recomputed...". Added the employer_balance reduction per cascaded default and a `recompute_vested_balance(p)` call after the outstanding-principal recomputation.
- `workspace/implementation/routes/participants.py::terminate_participant` — Same root cause as above, applied symmetrically to the direct participant-terminate path. Now reduces employer_balance by each defaulted loan's prior outstanding and recomputes vested employer balance.

**Final result:** 69/69 tests pass across all 8 parallel rounds.

## Step 8: Finalize PRD — 2026-05-27T08:40:00Z

**Line counts:** PRD.md = 237 lines, PRD_FINALIZED.md = 237 lines (line-count delta 0%, all edits are inline within existing single-line paragraphs). Word delta +517 words (+8.9%); char delta +3981 chars (+8.7%).

**Changes (one per edit):**

- §2.6 — revise — clarified that derived-field reconciliation on the same row triggered by the same cascade event shares ONE version bump (no double-bump), matching impl's single `stamp_update` per affected entity in cascade chains — `implementation/routes/plans.py:185-216`, `implementation/routes/participants.py:198-228`
- §3.3 — revise — pinned the §402(g) cap test to compare (YTD already-CLOSED `employee_contribution_cents` for the same participant whose `period_end_date.year == plan.plan_year`) + this period's raw deferral against `annual_deferral_limit_cents`, strictly exceeds rejects; no auto-shrink — `implementation/routes/contribution_periods.py:122-179`
- §3.3 — revise — pinned that tier-2 match floors twice: first floor on the `(capped_comp * tier2_pct_bps) // 10000` intermediate, then integer-divide-by-2 (second implicit floor) — `implementation/services/calculations.py:38-45`
- §3.4 — revise — pinned `term_months` accepts [1, 180] uniformly (Loan has no category discriminator), removing the general-vs-primary-residence split — `implementation/routes/loans.py:42-58`
- §3.4 — revise — pinned loan borrowing limit half-of-vested as `floor((employee_balance + vested_employer_balance) / 2)` (floor on the divide-by-2, not on the sum) — `implementation/routes/loans.py:160-163`
- §3.4 — revise — pinned that loan `amount_cents` on repay must be strictly positive (shape failure → `ERR_INVALID_REQUEST`), AND >= outstanding (business → `ERR_INVALID_STATE`) — `implementation/routes/loans.py:196`, `implementation/routes/loans.py:203-208`
- §3.5 — revise — pinned hardship cap_a order: `floor((employee_balance + vested_employer_balance) / 2)` THEN subtract `outstanding_loan_principal_cents`, so cap_a may be negative and outer max-with-zero clamps it — `implementation/services/calculations.py:113-127`
- §3.6 — revise — pinned full Uniform Lifetime Table (every integer age 73-120 with explicit factors) and clamping for ages > 120 to factor 2.0; pinned exact Joint Life Table key/value pairs and the deterministic fallback formula `uniform_factor(p_age) + 0.5 * (gap - 10)` for missing pairs — `implementation/services/calculations.py:145-234`, `implementation/routes/rmd_distributions.py:52-71, 118`
- §3.6 — revise — pinned RMD-pay pro-rata split: `ee_share = floor(distributed * ee / total)`, `er_share = distributed - ee_share`, total==0 → both 0; rounding residual lands on employer side — `implementation/routes/rmd_distributions.py:241-253`
- §3.7 — revise — pinned that "crosses a vesting boundary" means `vested_pct_bps(prior_yos)` differs from `vested_pct_bps(new_yos)` under the plan's schedule; pinned VestingEvent `as_of_date` on year-tick is the current system-clock ISO 8601 ms string, NOT a derived anniversary date — `implementation/routes/system.py:48-72`

No new sections added; no PRD-pinned behavior altered.
