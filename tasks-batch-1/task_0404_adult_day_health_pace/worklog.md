# Worklog — task_0404_adult_day_health_pace

Scenario: Adult Day Health & PACE Program: participant enrollment & eligibility (nursing-home level of care), daily attendance & transportation, interdisciplinary care plan, capitated PACE payment & enrollment lock-in, meal/activity schedule, nursing & medication services, Medicaid/Medicare dual billing, voluntary/involuntary disenrollment

Scaffold difficulty: Expert (applies to Step 2 only).

## Step 1: Create task directory — 2026-06-18T12:26:07.000Z

Task directory `tasks/task_0404_adult_day_health_pace/` was pre-allocated and pre-created with an empty `workspace/`. Auto-increment skipped per instruction. Verified `workspace/` exists; root `INSTRUCTION.md` and all six `prd-bench-*` skills present.

## Step 2: Generate scaffold (Expert difficulty) — 2026-06-18T12:54:00.000Z

Generated an **Expert-tier** scaffold for **task_0404_adult_day_health_pace** (Adult Day Health & PACE Program). All three files written to the task directory and verified clean by `scaffold_lint.py` (clean lint; 678 §1.8+§1.9 calls scanned, all conform; all 17 FKs reverse-reachable).

**SCAFFOLD.yaml (§1.0–§1.7):**
- **Entities: 12** — Program, Participant, Enrollment, LevelOfCareAssessment, CarePlan, CarePlanGoal, AttendanceDay, TransportLeg, MedicationOrder, MedicationAdministration (append-only event), CapitationPayment, DisenrollmentRequest. Flat-with-references topology under `api_prefix: /pace`.
- **State machines: 7** — Participant (5-state lifecycle with disenroll cascade), LevelOfCareAssessment (PENDING→CERTIFIED/DENIED/EXPIRED/SUPERSEDED), CarePlan (**cyclic** IN_REVIEW↔REVISION review loop), AttendanceDay, MedicationOrder, CapitationPayment (DRAFT→FINALIZED→RECONCILED + VOID compensation), DisenrollmentRequest (**branching** SUBMITTED→{APPROVED,DENIED}).
- **Concurrency rules: 2** — both OCC on `Participant.version` (capitation finalize, disenrollment finalize).
- **Calculations: 6** — capitation_amount (dual-variant FULL_MONTH vs DAILY × dual/non-dual, round-per-component), lock_in_penalty (threshold/boundary), ancillary_meal_charge, idt_completeness (set subset), census_occupancy (`>=` boundary), participant_ledger (derived reconciliation).
- **Validations: 26** (priority-ordered, 8 categories incl. concurrency).
- **Endpoints: 61** (flat CRUD + action endpoints + filtered-list GETs + one `/_clock/set_current_utc` test-driving endpoint).
- **Errors: 26**; **RBAC roles: 5** (ProgramAdmin, IntakeCoordinator, MedicalDirector, NurseStaff, BillingSpecialist) under a segregation-of-duties model (all `opaque` identity).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** 9 rules × 2 = **18 instances**, all formula-derived asserts pre-computed as literals.

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** **40 active instances + 11 excluded_because stubs** spanning entities, state_machines, calculations, validations, rbac, cross-cutting layers, and consistency_model.

**Notable design decisions:** (1) flat topology so the lint's collection-segment derivation resolves all FKs; (2) split capacity into `daily_census_capacity` (live census) + `max_roster` (enrollment cap) so the census `>=` boundary is reachable; (3) mid-month-allowed disenrollment effective dates so DAILY proration produces genuine partial `covered_days`. All 69 instance names unique; every grounds reference resolves; no forbidden concurrency vocabulary.

## Step 3: Copy shared files — 2026-06-18T12:56:27.000Z

Copied root `INSTRUCTION.md` → `tasks/task_0404_adult_day_health_pace/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-18T13:04:37.000Z

PRD written to `workspace/PRD.md` (315 lines). Design files (SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml) confirmed never opened.

**Section list:** §1 Introduction; §2 Global Specifications (2.1 RBAC all 5 roles + both auth errors opaque; 2.2 API response block; 2.3 pagination; 2.4 common resource props incl. MedicationAdministration `common_fields:false` exception; 2.5 existence/nested-ref/validation precedence 401→403→404→400→409 state→business; 2.6 cascades/derived fields/ledger reconciliation; 2.7 monetary round-half-up round-per-component; 2.8 OCC on Participant billing both rules; 2.9 logical clock/date gating); §3 Business Logic & Workflows (8 lifecycle subsections); §4 Endpoint Definitions (62 endpoints, 4-col table); §5 Error Code Catalogue (26 errors).

**Hard-contract self-reports:** Field coverage PASS (66/66 entity fields, 46/46 request bodies, 15/15 query params); Rule coverage PASS (8 state machines incl. cyclic CarePlan + branching DisenrollmentRequest; 6 calculations; 26 validations; 2 OCC rules; cascades); Path-purity PASS (493 backtick tokens scanned in §3, 0 slash-prefixed / bare-method / method+path tokens).

**Notable coverage decisions:** census vs roster split kept distinct (`daily_census_capacity`/`ERR_CENSUS_FULL` vs `max_roster`/`ERR_CAPACITY_EXCEEDED`) with boundary inclusivity; `ERR_CARE_PLAN_NOT_ACTIVE` reuse spelled out; capitation half-open coverage interval [effective, disenroll) + fixed 5-step round-per-component order; lock-in penalty boundary (`>=` end date → 0); parameter scattering (`expected_participant_version` in §2.8 vs gating in §3.7/§3.8).

## Step 5: Generate unit tests — 2026-06-18T17:31:30.000Z

Generated complete test infrastructure for **task_0404_adult_day_health_pace** (Adult Day Health & PACE Program, Expert tier) from the two design indices only — no freelance walk of SCAFFOLD.yaml.

### Coverage audit

**Queue A (Difficulty) — 18/18 instances translated, 0 skipped.** Every instance got ≥2 PRD-grounded tests (38 difficulty tests total; `capitation_full_month_vs_daily_diverge` and `care_plan_review_revision_cycle` each got 3). All 9 rules covered: dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant. All literal expected values (capitation 630000/420000/680000/226666/147000, lock-in 0/149333, ancillary 2750, etc.) are PRD-3.7/3.8-derivable and copied verbatim from the YAML.

**Queue B (Corner) — 40/40 non-stub instances translated, 0 skipped.** One test each across entities (9), state_machines (12), calculations (5), validations (7), rbac (3), cross_cutting_complexity_layers (3), consistency_model (1). The 11 `excluded_because:` stubs were correctly NOT translated; all 11 `difficulty_instance` cross-references verified to resolve to real Difficulty instances.

**No instances skipped** — every design instance passed the PRD-first two-condition filter (the PRD's Section 3 prose verbatim-covers and uniquely-derives each asserted rule, error_id, threshold, transition, and side effect). The OCC instances qualified because PRD 2.8 states both the `expected_participant_version` requirement and the `ERR_STALE_VERSION` rejection.

### Files (all under task dir)

- `test_helpers/`: `__init__.py`, `types.py`, `api_client.py` (one method per endpoint), `api_errors.py` (26 error IDs + status map), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (5 opaque roles + unknown-role), `fixtures.py` (composite enroll-chain / disenroll / capitation / attendance helpers)
- `test_suite/`: `conftest.py` + 7 test files (`test_01`–`test_07`)

### Verification

- **78 test functions total**, each with exactly one `Design:` tag (no untagged/dual-tagged); 38 Difficulty + 40 Corner.
- All quoted PRD citations confirmed verbatim against PRD.md (modulo whitespace, em-dash, backticks, markdown bold, and documented `...` elisions).
- All test_helpers and test_suite files compile clean (`py_compile`). The `MedicationAdministration` TypedDict and assertion correctly omit `updated_at`/`version` (common_fields:false). No scaffold/table references leak into emitted code comments.

Note: full runtime execution requires the `prd_bench_local_runner` framework (provided by the runner, not pip-installed here), so tests were validated by compilation + structural/citation audit rather than live pytest.

## Step 6: Generate implementation — 2026-06-18T17:31:30.000Z

Built a complete Python + Flask REST API for the **Adult Day Health & PACE Program** (task_0404), an EXPERT-tier benchmark. All smoke tests across four suites pass, covering the full happy path plus the complex calculations, cascades, OCC, and validation-precedence edge cases.

### Architecture
- **In-memory only**: one module-level dict per entity in `db.py`, empty on every import. No seeding, no disk persistence (verified via grep — no `open`/`sqlite`/`json.dump`/`/tmp`/`seed_`).
- **Flask blueprints**, one route module per resource group; thin routes delegate to shared service helpers.
- **Decimal-based money** with `ROUND_HALF_UP`, round-per-component then sum (never `float`).
- **Settable logical clock** (`/_clock/set_current_utc`) drives all time-gated logic (LOC expiry, age, lock-in window).

### File list (20 files)
- `start.sh` (foreground, `exec python3 app.py`, guarded `pip install` on missing flask), `requirements.txt`, `app.py` (blueprint registration + error handlers)
- `db.py`, `response.py`, `errors.py`, `middleware.py`
- `routes/`: programs, participants, enrollments, loc_assessments, care_plans, attendance, transport, medications, capitation, disenrollment
- `services/`: common (parsing/validation/pagination/system-fields), calculations (capitation, lock-in penalty, ancillary meal charge), participant_helpers (LOC-cert gating, ledger recompute, enrolled_count)

### Endpoint count: 61 routes (matches the PRD §4 table — 11 entities with full CRUD + all state-transition actions + clock).

### Notable design decisions (all traced to PRD prose)
- **Response envelope** `meta`/`response_type`/`data` exactly per PRD §2.2; pagination fields (`limit`/`offset`/`total_count`/`has_more`) live inside `meta`; lists sorted by `created_at` ascending.
- **Auth headers** `X-User-ID`/`X-User-Role`; five disjoint roles enforced via a `require_roles` decorator that authenticates → authorizes **before** any path-id existence check, honoring PRD §2.5 precedence (401 → 403 → 404 → 400 → 409 → business rules). Verified: missing-auth on a nonexistent resource returns 401, not 404.
- **OCC** on `expected_participant_version` vs `Participant.version` for both capitation-finalize and disenroll-finalize (ERR_STALE_VERSION, 412).
- **Capitation calc**: FULL_MONTH factor=1 vs DAILY factor=covered_days/days_in_month; half-open `[effective, disenroll)` covered-days window; dual vs Medicare-only supplement split; each component rounded independently then summed. Verified DAILY example (145161/150000) and non-dual supplement (617000).
- **Lock-in penalty**: `medicare_rate * remaining_days / lock_in_days`, half-up; boundary `>=` (finalize ON end-date → 0). Verified 150000 mid-window and 0 on-boundary.
- **Disenrollment cascade** runs atomically: enrollment→CLOSED, active plan→SUPERSEDED (or VOID if DECEASED) with its meds→DISCONTINUED, scheduled/checked-in days→CANCELLED with their planned legs→CANCELLED, FKs cleared, enrolled_count decremented.
- **MedicationAdministration** is append-only — carries only `id`+`created_at`, no `updated_at`/`version` (verified in response).
- **Derived participant fields** (ledger_billed/reconciled, lifetime_attendance_days) and `Program.enrolled_count` kept consistent; voiding a FINALIZED payment returns the ledger exactly to pre-finalize (verified → 0).
- **`strict_slashes=False`** so trailing-slash variants resolve; `threaded=True` for concurrent test requests.

Each request boots from a fresh empty process; confirmed `start.sh` reaches HTTP readiness within ~3s, binds `0.0.0.0:$PORT`, and runs in the foreground.

## Step 7: Run tests and iterate — 2026-06-18T17:48:00.000Z

All tests pass across two consecutive 8-round parallel sweeps (16/16 rounds, 78/78 each). Independently re-confirmed by orchestrator with a third clean 8-round sweep (8/8 rounds, 78/78 each); results.{1..8}.json regenerated.

**Iterations run:** 3 sweeps (1 diagnostic + 2 confirmation). Final two sweeps were both fully clean (16 rounds total, 78/78 each).

**Tests deleted:** None. Both initial failures and the one flaky failure traced to genuine implementation bugs, not test/PRD-fidelity problems.

**Fixes applied to test_helpers/:** None.

**Fixes applied to implementation/:**

1. `routes/care_plans.py` — `void_care_plan`: Reordered the two guards so the active-plan check precedes the state check. The PRD (§3.3) gives a dedicated error for the active-plan case ("an attempt to void the participant's active care plan is rejected with `ERR_CANNOT_VOID_ACTIVE`"). Previously an ACTIVE plan hit the generic `ERR_INVALID_STATE` first (status not in DRAFT/IN_REVIEW/REVISION) before the active-plan check could fire. Fixed `test_void_active_care_plan_rejected`.

2. `routes/disenrollment.py` — `approve`, `withdraw`, and `finalize`: Maintain `enrolled_count` as the derived count of ENROLLED participants per PRD §2.6 ("the Program's `enrolled_count` equals the number of that program's participants whose `status` is `ENROLLED` ... the corresponding derived field is updated so that it never drifts from the true total"). Approve and withdraw previously changed participant status without recomputing the count; finalize used a manual `-1`. Now all three call the existing `recompute_enrolled_count` helper so the count never drifts during the DISENROLLMENT_PENDING window. Fixed `test_approve_does_not_decrement_enrolled_count` (and keeps `test_approve_then_withdraw_conserves_enrolled_count` passing).

3. `app.py` / `start.sh` / `requirements.txt` — Switched the WSGI server from Flask's dev server (`app.run`) to **waitress** (with a dev-server fallback on ImportError). Under per-test-server isolation the runner's `requests.Session` reuses keep-alive connections; the Werkzeug dev server intermittently reset those reused connections under the 8× concurrent boot load, surfacing as `BadStatusLine`/`ConnectionError` (`test_recoup_exceeds_billed_rejected` failed 2/8 in the diagnostic sweep, on a setup `sign` request). Waitress handles connection lifecycle robustly; the flakiness was eliminated across two subsequent full sweeps. The `start.sh` import guard now also checks for `waitress` so the implementation stays self-contained.

**Key finding:** The `enrolled_count` fix required resolving an apparent tension between PRD §2.6 (count *equals* ENROLLED participants — a never-drift invariant) and §3.8's per-workflow "decreases by 1" at finalize. §2.6's authoritative derived-field invariant governs: the count must drop when the participant leaves ENROLLED at approve, so recomputing (not manual increment/decrement) is the uniquely PRD-faithful implementation.

## Step 8: Finalize PRD — 2026-06-18T17:52:00.000Z

PRD_FINALIZED.md produced as a minimal in-line patch of PRD.md targeting the Step 7 implementation-fix sites.

**Line counts:** PRD.md = 315 lines, PRD_FINALIZED.md = 315 lines. Delta = 0 lines (all edits were in-line revisions of existing lines, no structural change). 4 lines revised (~1.3% of lines touched).

**Changes (one bullet each):**
- §3.3 — revise — Pinned that for a care plan that is the participant's active plan, the active-plan check (`ERR_CANNOT_VOID_ACTIVE`) is evaluated **before** the state check (`ERR_INVALID_STATE`), so an ACTIVE plan rejects with `ERR_CANNOT_VOID_ACTIVE` even though its status is not DRAFT/IN_REVIEW/REVISION — `routes/care_plans.py:209-214`.
- §3.8 (approve) — revise — Pinned that the program's derived `enrolled_count` drops by 1 **at approval** (when the participant leaves ENROLLED for DISENROLLMENT_PENDING), not at finalize — `routes/disenrollment.py:80-87`.
- §3.8 (withdraw) — revise — Pinned that `enrolled_count` rises by 1 again **at withdrawal** (participant returns to ENROLLED), restoring the pre-approval value — `routes/disenrollment.py:118-127`.
- §3.8 (finalize bullet) — revise — Fixed the mismatch "the program's `enrolled_count` decreases by 1" to state that finalize reconciles the derived count per §2.6 and leaves it **unchanged**, since the participant already left ENROLLED at approval — `routes/disenrollment.py:202-211`.

**Item 3 (waitress/start.sh/requirements):** No PRD edit — confirmed transport/infra only, no API-behavioral effect.

**Per-edit pre-edit search log:**
1. Edit 1 (void ordering): (a) Subject: care-plan void error ordering. (b) Grepped all `ERR_CANNOT_VOID_ACTIVE`/`active_care_plan_id` references in care_plans.py — only callsite is void_care_plan (206-217), active-plan check (211) precedes state check (213); checked activate_care_plan to confirm active plan is always ACTIVE. (c) Worded the pin around "currently the participant's active plan" (keying on the FK not the status), avoiding any claim that precedence depends on status value.
2. Edits 2-4 (enrolled_count): (a) Subject: when derived `enrolled_count` changes across enroll/approve/withdraw/finalize. (b) Grepped every `enrolled_count`/`recompute_enrolled_count` ref: programs.py:43 (init 0), participant_helpers.py:58-65 (recompute=count ENROLLED), participants.py:118 & :138 (post-enroll +1), disenrollment.py:86 (approve -1), :125 (withdraw +1), :210 (finalize 0). Cross-checked §2.6, §3.1, §3.4 line 162 ("increases by 1" at enroll — still accurate). (c) Scoped finalize wording to "reconciled per §2.6 ... leaves it unchanged" so it stays consistent with the recompute being a no-op at finalize; left §3.4's "increases by 1" untouched.

## Step 9: Complete PRD — 2026-06-18T17:57:00.000Z

PRD_COMPLETED.md produced via full PRD-vs-implementation/ completeness scan, starting from PRD_FINALIZED.md.

**File counts:** PRD_FINALIZED.md (source): 315 lines / 50,595 chars → PRD_COMPLETED.md: 315 lines / 52,807 chars. Char delta: **+2,212**. Line count unchanged (all edits in-paragraph inserts/revisions; no new sections or paragraphs).

**Counts:** 8 changes total — **5 ambiguity-pins**, **3 mismatch-revisions**.

**Changes (one per edit):**
- §2.3 Pagination — insert — ambiguity — pinned that the limit min/max constraint and negative offset are applied by *clamping* (not rejection), the clamped `limit` is echoed in `meta.limit`, and a non-integer `limit`/`offset` is `ERR_INVALID_REQUEST` — `services/common.py:172-193`
- §3.1 Establishing the Program — insert — mismatch — pinned that `state_code` is validated only as a required non-empty string with no two-letter length/format enforcement (PRD said "two-letter" but impl accepts any string) — `routes/programs.py:21`, `services/common.py:39-47`
- §3.2 LOC Certification — revise — mismatch — PRD tied the participant `version` increment to the APPLICANT→ELIGIBLE bubble-up only; impl increments on *every* certify (always repoints `active_loc_assessment_id` and touches the participant), including recertification of an already-ELIGIBLE/ENROLLED participant — `routes/loc_assessments.py:92-97`
- §3.3 Care Plan review loop — insert — ambiguity — pinned that the single `/submit` endpoint serves both transitions, accepting a plan in `DRAFT` or `REVISION` → `IN_REVIEW` and rejecting any other status with `ERR_INVALID_STATE` — `routes/care_plans.py:150-161`
- §3.4 Enrollment — insert — ambiguity — pinned the fixed evaluation order of the same-class enroll preconditions: ELIGIBLE state → program OPEN → LOC certified → active care plan → age → first-of-month → roster cap — `routes/participants.py:92-120`
- §3.7 Capitation Finalize — insert — ambiguity — pinned that the four listed checks run in stated order (DRAFT → program-OPEN → coverage → LOC) and the OCC `expected_participant_version`/`ERR_STALE_VERSION` check is evaluated *last* — `routes/capitation.py:98-128`
- §3.7 Ancillary attendance-summary — insert — ambiguity — pinned that `service_month` is a query parameter, only its year+month are used to match days, and omitting it yields `ERR_INVALID_REQUEST` — `routes/participants.py:147-149`
- §3.8 Disenrollment Finalize — insert — ambiguity — pinned that checks run APPROVED-state first then participant-DISENROLLMENT_PENDING, with the OCC `ERR_STALE_VERSION` check evaluated *last* — `routes/disenrollment.py:153-161`

**Left unchanged (already pinned or obvious default):** request-revision transitions + signature clearing (§3.3); deny/withdraw state-before-kind (§2.5); medication-admin day-state → `ERR_CARE_PLAN_NOT_ACTIVE` (§3.6); ISO-8601 date echo (output-shape); at-creation `reconciled_cents`/`recoup_cents`=0 (default).

---

## Pipeline complete — 2026-06-18T17:57:00.000Z

All 9 steps finished. Final state: 78/78 tests passing across an independently re-run 8-round parallel per-test-server sweep (8/8 rounds clean). Task artifacts complete: SCAFFOLD.yaml + 2 design files, PRD.md / PRD_FINALIZED.md / PRD_COMPLETED.md, test_helpers/ (9 files), test_suite/ (conftest + 7 files, 78 tests), workspace/implementation/ (Flask app + start.sh + results.{1..8}.json).
