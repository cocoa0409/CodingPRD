# Worklog — task_0147_corporate_lms_compliance_training

Scenario: Corporate LMS & Compliance Training: course/curriculum/path, rule-based role assignment, due date/annual recurrence, completion/quiz score, certification/CEU, manager dashboard, overdue escalation, SCORM/xAPI tracking

Difficulty: Expert (10-15 entities, 20-32 endpoints, 18-30 errors, 3+ calculation variants, 4+ state machines) — passed only to Step 2 scaffold generator.

## Step 1: Create task directory — 2026-06-04T12:18:39.000Z

Task directory `tasks/task_0147_corporate_lms_compliance_training/` pre-created with `workspace/` subdir (path supplied by invocation; index not recomputed). Verified present.

## Step 2: Generate scaffold — 2026-06-04T12:45:00.000Z

The scaffold is complete and lint-clean. Here's my final report.

Generated the three scaffold artifacts for **task_0147_corporate_lms_compliance_training** from the scenario verbatim, with no reference to any sibling task.

**Files written** (all under `tasks/task_0147_corporate_lms_compliance_training/`):
- `SCAFFOLD.yaml` (§1.0–§1.7, plus `complexity_profile` and one `concurrency_rules` entry)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

**Counts (Expert band, all in target):**
- Entities: **13** (Employee, Course, CoursePrerequisite, LearningPath, PathStep, AssignmentRule, Enrollment, QuizAttempt, PathEnrollment, Certificate, TrackingSession, EscalationEvent, ClockState)
- Endpoints: **48** total = 23 business mutations + 23 GET reads + 2 test-driving (`/_clock/set`, `/_clock`). The mutation surface (23) sits at the Expert ceiling; the read count is inflated only by mandatory FK reverse-reachability + single-resource GETs.
- Errors: **21**
- Calculations: **6**, with **2** carrying dual variants (final_grade HIGHEST/LATEST on Enrollment; ceu_accrual STANDARD/SCORE_WEIGHTED on Certificate) — different entity domains
- State machines: **6** (Course, LearningPath, Enrollment [cyclic retry], PathEnrollment [compound bubble-up], Certificate [branching], TrackingSession [self-loop + cross-aggregate terminate])

**§1.8 design:** all 9 Difficulty Rules × exactly 2 instances = **18 instances**; **31 active §1.9 corner instances + 6 excluded_because stubs**. Total 332 setup/trigger calls.

**Notable design decisions:**
- Archetype: compliance/audit + workflow-orchestration; graph topology (many-to-many PathStep, self-referential Course-prerequisite DAG and Employee.manager_id).
- `api_prefix: ""` (flat/graph topology with many peer top-level collections) — required so the linter could derive collection segments; the original `/courses` prefix broke FK reverse-reachability detection.
- All path-id placeholders normalized to `{id}` (the linter's sub-resource reverse-reachability check matches the literal `{id}`); design-file calls carry the concrete `${var}` in the path.
- OCC on `POST /enrollments/{id}/quiz-attempts` via `expected_enrollment_version` (recurrence-reset supersede race).
- Resolved a latent unreachability: ERR_ATTEMPTS_EXHAUSTED now fires on a quiz attempt against a FAILED enrollment, with OCC (priority 9) deliberately ahead of the attempts check (priority 13) so the priority-conflict instance (stale-version beats attempts-exhausted) is consistent.
- Removed two dead enum values (Employee/AssignmentRule `DISABLED`/`DEACTIVATED`) for enum closure.

**Linter result** (`scaffold_lint.py`, verbatim verdict): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`
Additional self-audits passed: all `grounds[]` resolve, all `excluded_because` targets exist by name, no name collisions across the two design files, every error referenced, all endpoint roles in RBAC, and no forbidden concurrency vocabulary.

## Step 3: Copy INSTRUCTION.md — 2026-06-04T12:46:08.000Z

Copied `INSTRUCTION.md` → `tasks/task_0147_corporate_lms_compliance_training/workspace/INSTRUCTION.md` (1424 bytes). bash-only step, no subagent.

## Step 4: Generate PRD — 2026-06-04T12:51:29.000Z

Generated `workspace/PRD.md` — **270 lines** (45327 bytes).

### Sections covered
- **§1 Introduction** — 2 paragraphs, framed around compliance proof obligations and the deterministic logical-clock model.
- **§2 Global Specifications (10 subsections)** — Access Control (all three roles' `identity:` translated — `ComplianceAdmin` opaque, `Manager`/`Learner` entity-backed to `Employee`), Response Structure, Pagination, Identity/Timestamps/Versioning (incl. the two `common_fields: false` audit entities `QuizAttempt` and `EscalationEvent` carrying only `id`+`created_at`), Logical Clock, Nested Retrieval & existence ordering, Request-shape validation, Precision/Rounding, OCC on quiz submission, Cascading Reconciliation & conserved quantities.
- **§3 Business Logic (9 subsections + 1 sub-subsection)** — People & Catalog, Curricula, Rule-Based Assignment, Enrollment Lifecycle, Quiz/Grading/Certification, Tracking Sessions, Path Enrollments & Progress, Prerequisite Gating, Certificates/Recurrence, Escalation & Dashboard.
- **§4** — 4-column endpoint table (48 endpoints).
- **§5** — 2-column error catalogue (21 errors).

### Hard contract results: all PASS (field coverage 59/59 + 8/8; rule coverage 0 missing across validations/OCC/state-machines/calculations/side-effects/sibling-symmetry; path purity 484 tokens scanned, 0 leaks).

### Notable scattering decisions
- OCC scattered to §2.9 then reinforced at quiz-attempt (§3.5), tracking-session terminate (§3.6), recurrence reset (§3.8) — stale-version framing only, never a race.
- Quiz-attempt params split across ≥2 subsections (score/expected_enrollment_version in §3.5; state-gate set + OCC-before-attempts ordering alongside).
- Prerequisite gating in dedicated §3.7.1 (course-prereq ERR_PREREQUISITE_NOT_MET vs path-sequence ERR_PATH_STEP_LOCKED).
- Constants embedded in narrative (default due 30/60d, max_attempts 3, CEU tier mults, tier-day bands, 5-pt per-tier penalty).
- Withheld design files not opened.

## Step 5: Generate unit tests — 2026-06-04T13:05:55.000Z

Generated complete test infrastructure from the two design indices, with the PRD as the contract.

**Stage 1 — `test_helpers/` (9 files):**
- `types.py` — TypedDicts for all 14 entities + status/role/enum classes. `QuizAttempt` and `EscalationEvent` correctly carry only `id`+`created_at` (append-only, `common_fields: false`); all others carry `id`/`created_at`/`updated_at`/`version`.
- `api_client.py` — one method per §1.5 endpoint (all 48 endpoints).
- `api_errors.py` — all 21 error IDs + HTTP status map.
- `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (opaque ComplianceAdmin constant + `make_learner_headers`/`make_manager_headers` builders for entity-backed roles), `__init__.py` barrel.
- `fixtures.py` — composite helpers for clock control, published courses, started/completed/failed enrollments, running tracking sessions, published N-step paths + path-enrollments + child-step completion, assignment rules, escalation sweeps. Identity threading enforced: every ownership-gated learner call uses `make_learner_headers(employee_id)`, never the shared constant.

**Stage 2 — `test_suite/` (conftest + 9 test files, 67 test functions):**
- **Queue A (Difficulty): 36 tests** — all 18 difficulty instances ×2.
- **Queue B (Corner): 31 tests** — all 31 non-stub corner instances ×1.

**Coverage:** 18/18 difficulty (×2), 31/31 non-stub corner (×1). **Skipped: 0.** All 6 corner `excluded_because` stubs correctly NOT translated.

**Verification:** all 67 tests collect under pytest; every module byte-compiles; every test carries exactly one `Design:` tag resolving to a real non-stub instance; 75 quoted PRD fragments verbatim in PRD.md; no scaffold leakage; no skip/xfail markers.

**Notable decisions:**
- `missing_user_role_header_returns_401` bypasses `build_user_headers` and sends raw header dict via `api._request` to genuinely omit the role header.
- `attempts_exhausted` vs `stale_version`: exhausted test re-reads current version (OCC clears, attempts check fires); priority-conflict test reuses stale post-start version (OCC pre-empts) — faithful to PRD §2.9 ordering.

NOTE (orchestrator): Steps 5 and 6 were run sequentially (not concurrently) due to an orchestrator sequencing slip. To preserve the intended physical isolation, `test_helpers/` and `test_suite/` were moved to `/tmp/task_0147_tests_hold/` before launching Step 6, then restored after Step 6 exits — so the impl-gen subagent cannot read the tests.

## Step 6: Generate implementation — 2026-06-04T13:18:41.000Z

Generated complete Python + Flask implementation at `workspace/implementation/` (test dirs held out for isolation during this step, restored after).

### Files (23)
- `start.sh` (guarded pip install + `exec python3 app.py`), `requirements.txt`, `app.py` (blueprint registration + error handlers)
- Core: `db.py` (in-memory store + logical clock + ISO-3-digit timestamp), `errors.py` (§1.6 catalog), `response.py` (envelope), `middleware.py` (auth), `serializers.py`, `timeutil.py` (add_days/add_months/floored days_overdue)
- `routes/`: employees, courses, learning_paths, assignment_rules, enrollments, tracking_sessions, path_enrollments, certificates, escalations, clock
- `services/`: common, calculations, enrollment_engine, path_enrollment_svc

### Endpoints: 48 implemented — every route in PRD §4 / SCAFFOLD §1.5.

### State machines / calculations
- State machines: Course, LearningPath, Enrollment (FAILED→IN_PROGRESS retry, COMPLETED→NOT_STARTED recurrence reset, →EXPIRED, →WAIVED), PathEnrollment (compound bubble-up from children), Certificate (ACTIVE→EXPIRED/REVOKED), TrackingSession (INITIALIZED→RUNNING self-loop→TERMINATED with cross-aggregate grading promotion).
- Calculations: `final_grade` (HIGHEST_SCORE/LATEST_ATTEMPT), `ceu_accrual` (STANDARD/SCORE_WEIGHTED tiered multiplier, round-after-multiply, 2dp half-up Decimal), `path_progress_pct` (weighted, ratio→×100→round once), `escalation_tier` (0/1/2/3 thresholds), `compliance_score` ((compliant/n)*100 - Σtier*5, clamp [0,100]), conserved invariants (total_ceu_earned, compliant_required_count) reconciled on issue/revoke/expire.
- Full validation priority chain (auth→existence→field-shape→ownership→state→OCC→business gates) with exact error IDs/HTTP codes; quiz-attempt OCC checked before attempts-exhausted.

### Notable decisions / ambiguity resolutions
- escalation_tier derived at serialization time from current days_overdue (consistent across get/list/dashboard).
- Sweep "open cycle" skip / duplicate-enrollment uses statuses {NOT_STARTED, IN_PROGRESS, FAILED, EXPIRED} (COMPLETED/WAIVED resolved) → ERR_DUPLICATE + idempotent re-apply consistent.
- Field-shape validation (priority 6) before ownership (priority 7) on quiz-attempt and tracking-session commit.
- Logical clock seeded to fixed epoch 2025-01-01T00:00:00.000Z on each fresh boot; no entity seeding; store empty; all time math reads the clock.
- PathEnrollment progress recompute does not bump version (only bubble status transitions do).
- Manager/Learner read scopes via self-referential manager_id report-set traversal; ComplianceAdmin identity opaque.
- Verified end-to-end boot via start.sh (~1s ready).

## Step 7: Test & iterate loop — 2026-06-04T13:28:13.000Z

All 8 parallel rounds green: 64/64 passed, 0 failures, 0 errors, in every round. Clean sweep.

**Iterations run:** 3 sweeps (initial diagnostic + 2 fix iterations). Final: all 8 parallel rounds pass 64/64.

**Root causes:** Initial sweep showed deterministic 39/67. Dominant cause (27 of 28 failures) was a single upstream `test_helpers` bug; the rest were two more `test_helpers`/test-fairness issues.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — `set_clock(current_utc)`: added default `= DEFAULT_CLOCK`. Every test calls `set_clock()` with no argument (reset to canonical 2026-01-01 epoch), but the helper required the positional arg → `TypeError: set_clock() missing 1 required positional argument`, tanking 23 tests at setup. Default makes the helper consistent with how the whole suite calls it (the triage-hint case: one upstream fixture bug masquerading as many failures).

**Fixes applied to `test_suite/`:**
- `test_suite/test_03_state_machines_and_cascades.py` — `_setup_single_step_path_running_session`: added `set_clock("2026-01-02T...")` after opening/committing the session and before the test's terminate. PRD §3.6 requires `terminated_at` strictly after `started_at`; setup opened the session and terminated it at the same logical instant → PRD-faithful impl correctly returned `ERR_INVALID_STATE`. Advancing the clock (within the 30-day due date) makes the setup faithful to PRD. Fixed 2 tests.

**Tests deleted (3):**
- `test_compliance_score_combines_compliant_ratio_tier_penalty_and_clamp` (test_02) — **UNIQUE-DERIVABILITY collapse (computed-field silence).** PRD §3.10 defines `escalation_tier` as a pure threshold function of `days_overdue = current_utc − due_date` with no status gating; PRD §3.9 sums "current escalation_tier" over all required enrollments. Scenario has a COMPLETED enrollment whose `due_date` is 16 days past. Two faithful readers diverge: COMPLETED→tier 0 (score 40, test's reading) vs literal threshold (tier 2→score 30, impl's reading). PRD does not uniquely determine. Driven by `Difficulty/combinatorial_formula/compliance_score_nonlinear_three_input_clamp`.
- `test_start_archived_course_with_unmet_prereq_returns_course_not_published` (test_04) — **PRD-unreachable precondition.** Asserts behavior on a NOT_STARTED enrollment against an ARCHIVED course. PRD §3.2 forbids archiving a course while any enrollment is NOT_STARTED/IN_PROGRESS (`ERR_COURSE_HAS_OPEN_ENROLLMENTS`), so this combined state cannot be constructed via the API. Driven by `Difficulty/priority_pair_validation_conflict/start_course_archived_state_beats_prerequisite_constraint`.
- `test_start_blocked_by_course_state_leaves_enrollment_not_started` (test_04) — same PRD-unreachable precondition (identical archive-after-enroll setup), same scaffold instance.

The reachable variant of the course-state gate (DRAFT course → `ERR_COURSE_NOT_PUBLISHED`) remains covered by two passing sibling tests.

**No implementation changes were made** — every failure traced to a test-helper bug, a test-setup inconsistency, or an unfair/ambiguous test. The implementation's PRD-mandated checks (archive-blocks-on-open-enrollments §3.2, terminate strictly-after-started_at §3.6, literal escalation_tier §3.10) all left intact.

`workspace/implementation/results.{1..8}.json` left in place from the final clean sweep (verified by orchestrator: 64/64 in all 8 rounds).

## Step 8: Finalize PRD — 2026-06-04T13:32:22.000Z

Produced `workspace/PRD_FINALIZED.md`. (Step 8 ran: Step 7 had 3 deletions + 1 test_suite fix + 1 test_helpers fix; skip condition not met.)

**Line counts:** PRD.md = 269, PRD_FINALIZED.md = 269 (inline edits within two existing §3.9 paragraphs; no lines added/removed). Two paragraphs materially expanded.

**Changes (2):**
- §3.9 (escalation tier definition) — insert — clarified the reported `escalation_tier` for an enrollment is a pure derived value of `days_overdue` against `current_utc` and does NOT depend on the enrollment's `status` (a COMPLETED/EXPIRED/WAIVED enrollment past `due_date` still carries the nonzero tier), with an explicit aside that this per-enrollment tier is distinct from the sweep's NOT_STARTED/IN_PROGRESS-gated event emission — `services/calculations.py:92-100` + `serializers.py:74-79`.
- §3.9 (compliance_score overdue penalty) — revise — clarified the penalty sums over EVERY latest-cycle required enrollment regardless of `status` (including COMPLETED/compliant ones), using that same status-agnostic tier value — `services/calculations.py:146-158`.

**Diff items requiring NO PRD edit:** set_clock() default (pure fixture bug); clock-advance before terminate (PRD already states terminated_at strictly after started_at; ERR_INVALID_STATE not pinned by any surviving test → left PRD-silent/under-determined); the two test_04 deletions (PRD §3.2 already pins archive-blocks-on-open-enrollments → ERR_COURSE_HAS_OPEN_ENROLLMENTS at routes/courses.py:135-136; test-fairness deletions, no silence/mismatch).

NO-NEW-MISMATCH pre-edit searches logged for both edits (escalation_tier status-agnosticism enumerated across calculations.py/timeutil.py/serializers.py/escalations.py/seed sites; compliance_score penalty enumerated across calculations.py latest-cycle set + compliant-count branch). Wording scoped to avoid implying EscalationEvents emitted for terminal-status enrollments; sweep prose left untouched.

## Step 9: Complete PRD scan — 2026-06-04T13:38:18.000Z

Produced `workspace/PRD_COMPLETED.md` (full PRD-vs-implementation/ scan; started from PRD_FINALIZED.md).

**Line counts:** PRD_FINALIZED.md = 269 lines / 46,150 chars → PRD_COMPLETED.md = 269 lines / 48,594 chars (+2,444 chars; 10 lines revised in place, no lines/sections added).

**Counts:** 10 ambiguity-pins, 1 mismatch-revision.

**Changes:**
- §2.2 — insert — ambiguity — `api_request_timestamp` stamped from logical clock `current_utc`, not wall clock — `response.py:28`.
- §2.3 — insert — ambiguity — out-of-range `limit` clamps to [1,100], negative `offset` clamps to 0, non-integer → `ERR_INVALID_REQUEST` — `services/common.py:118-142`.
- §2.3 — insert — ambiguity — list ordering ties broken by ascending `id` — `services/common.py:147`.
- §2.5 — insert — ambiguity — clock initialized at boot to `2025-01-01T00:00:00.000Z` — `db.py:43`.
- §2.7 — insert — ambiguity — per-resource ownership/scope check runs after body-shape validation (malformed body → `ERR_INVALID_REQUEST` before non-owner `ERR_UNAUTHORIZED` on quiz-attempt/commit writes) — `routes/enrollments.py:208-217`, `routes/tracking_sessions.py:86-99`.
- §3.3 — insert — ambiguity — sweep walks matching employees in ascending `created_at` (tie `id`) order — `routes/assignment_rules.py:166`.
- §3.3 — insert — ambiguity — "open cycle" for skip: course = NOT_STARTED/IN_PROGRESS/FAILED/EXPIRED, path = NOT_STARTED/IN_PROGRESS/FAILED — `routes/assignment_rules.py:172,180`.
- §3.4 — insert — ambiguity — duplicate "open-cycle" enrollment states = NOT_STARTED/IN_PROGRESS/FAILED/EXPIRED — `routes/enrollments.py:21,56`.
- §3.5 — insert — ambiguity — `latest_score` tie-breaks by greatest `attempt_number` (same-cycle attempts share the logical-clock timestamp) — `services/enrollment_engine.py:41`.
- §3.6 — insert — ambiguity — tracking session opening values seeded (lesson_status null, progress_pct 0, reported_score null, terminated_at null) — `routes/tracking_sessions.py:54-57`.
- §3.6 — insert — ambiguity — terminate promotion fires only when enrollment is IN_PROGRESS with attempts remaining; otherwise session still terminates with no attempt recorded — `routes/tracking_sessions.py:150-153`.
- §3.9 — revise — mismatch — dashboard returns the refreshed `Employee` resource shape (no separate "overdue summary" structure), correcting PRD's "along with an overdue summary" — `routes/employees.py:99-102`.

**Left unchanged (PRD already governs or impl consistent):** §2.1 global ordering already covers role-check sequence; reopen aggregate recomputation honors "highest attempt score in current cycle"; path-enrollment read-recompute unversioned per §3.7; clock state serializes §2.4 common fields.

---

## PIPELINE COMPLETE — 2026-06-04T13:38:18.000Z

All 9 steps done. Final state: 8/8 parallel sweep rounds green at 64/64 (3 tests deleted from the original 67). Artifacts present: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, test_helpers/, test_suite/, workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/, results.{1..8}.json}.
