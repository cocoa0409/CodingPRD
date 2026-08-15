# Worklog — task_1360_degree_audit_graduation_certification

## Step 1: Create Task Directory — 2026-08-13T00:30:00.000Z

Task directory `tasks/task_1360_degree_audit_graduation_certification/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher; Step 1 treated as DONE per instructions (no index scan, no other task_* directory touched).

## Step 2: Generate Scaffold — 2026-08-13T01:08:00.000Z

All three scaffold artifacts are generated, lint-clean, and structurally audited. No sibling task directories were touched — the design was derived solely from the scenario text and the skill specification.

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_1360_degree_audit_graduation_certification/SCAFFOLD.yaml` — §1.0–§1.7 (no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1360_degree_audit_graduation_certification/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1360_degree_audit_graduation_certification/SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`

## Summary of the design

**Complexity profile**: compliance/audit primary, graph-constraint secondary; layers = optimistic concurrency, cascading side effects, dual-variant calculation, derived-field reconciliation; flat topology with FK links; approval-chain role model with segregation-of-duties; immediate consistency; Expert band.

**Entities (11)**: Program (half-open catalog-year ranges), RequirementGroup, HonorsPolicy (closed inclusive effective-year ranges, INSTITUTIONAL/CUMULATIVE GPA basis), Course, Student (computed credits + dual GPAs, financial hold), Enrollment (grade/credit/grade-point computation, W exclusion), StudentProgram (catalog-year pinned declaration), DegreeAudit (STANDARD/WHAT_IF/CONDITIONAL/FINAL kinds, CURRENT/SUPERSEDED), SubstitutionWaiver (SUBSTITUTION/WAIVER kinds, requester identity for SoD), GraduationApplication (filing deadline, honors designation), Diploma (self-referential `reissue_of_diploma_id` chain).

**State machines (7)**: notably a cyclic SubstitutionWaiver (SUBMITTED→DENIED→SUBMITTED resubmit loop, APPROVED→REVOKED compensation) and a branching GraduationApplication (UNDER_REVIEW forks to CLEARED / CONDITIONALLY_CLEARED / DENIED, with system auto-resolution CONDITIONALLY_CLEARED→CLEARED|DENIED when the last IN_PROGRESS enrollment resolves).

**Calculations (5)**: per-enrollment grade/credit award; GPA with pinned sum-then-round-once 3-decimal rounding (institutional vs cumulative variants); waterfall group-satisfaction allocation (largest-deficit, created_at ordering, group_code tie-break, substitution/waiver offsets with max(0,·) floor); audit progress with completed-only vs include-in-progress variants; Latin honors thresholds (>= inclusive, residency gate, policy basis selection).

**Endpoints (43)**, **errors (35)**, **roles (4: Student entity-backed, Advisor/RegistrarStaff/SystemAdmin opaque)**, plus one OCC concurrency rule (`audit-create-stale-student-program`, 412 ERR_STALE_VERSION) and a `/_clock/set_current_utc` test-driving endpoint with the mandated 2026-08-01T00:00:00Z default.

**Difficulty design**: 18 instances (9 rules × 2), all with structured setup/trigger chains and pre-computed literal asserts (e.g., GPA 45.00/12 = 3.750 hitting MAGNA exactly; 14/5 = 2.800 vs rejected per-term-average 3.667; depth-3 post-grade cascade Enrollment→Student→DegreeAudit→GraduationApplication; depth-2 waiver→audit→program-flag cascade).

**Corner design**: 42 entries (33 active + 9 `excluded_because` stubs) across all nine taxonomy sections — every error code in the catalog has a trigger, RBAC denials, pagination/envelope shape, FK 404s, and OCC stale-version rejection are all covered.

**Lint verdict** (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (417 calls scanned; 43 endpoints; 11 entities; 18 §1.8 + 33 active §1.9 instances; name uniqueness verified across both design files.)

## Step 3: Copy Shared Files — 2026-08-13T01:09:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1360_degree_audit_graduation_certification/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T01:35:00.000Z

All verification passes are clean. The PRD is complete and ships.

## Summary

**Generated:** `/home/ubuntu/github/CodingPRD/tasks/task_1360_degree_audit_graduation_certification/workspace/PRD.md` (313 lines) from `SCAFFOLD.yaml`, per the `prd-bench-doc-generator` skill. The two withheld design files were not opened.

**Structure**
- **§1 Introduction** — 2 paragraphs, registrar-office pain-point angle (catalog-year drift, lost exceptions, late certification discoveries).
- **§2 Global Specifications** — 11 subsections: RBAC with per-role `identity:` translations (§2.1), byte-identical verbatim response-envelope block (§2.2, diff-verified against `section-2.2-response-structure.md`), pagination (§2.3), common resource properties (§2.4), the logical clock incl. the `2026-08-01T00:00:00Z` default and `to_iso8601`/`current_utc` (§2.5), left-to-right nested retrieval naming all nine `ERR_*_NOT_FOUND` ids (§2.6), the explicit 11-step gatekeeping order with every error id mapped (§2.7), half-open catalog ranges vs. closed policy intervals (§2.8), pinned GPA rounding / exact grade points / inclusive thresholds (§2.9), OCC scoped solely to audit creation (§2.10), and the recompute cascade with `updated_at`/`version` semantics (§2.11).
- **§3 Business Logic** — 7 subsections organized by lifecycle (catalog building → academic record → declaration → audits → exception chain → application review → conferral/diplomas). All four calculation rules rendered in precise prose (waterfall allocation with `created_at`/course-code/`term` tie-breaks, pinned single-final-rounding GPA, conditional in-progress projection, honors residency gate and inclusive thresholds). All state transitions named as UPPERCASE pairs; every side-effect cascade (supersession, `latest_audit_satisfied` refresh with version bump, `CONDITIONALLY_CLEARED` auto-resolution to `CLEARED`/`DENIED`+`CONTINGENCY_FAILED`, confer cascade, revoke compensation) expressed.
- **§4 Endpoint table** — 43 rows, 4 columns only (Method/Path/Description/Roles).
- **§5 Error catalogue** — all 35 error ids, 2 columns only; document ends there with no audit footer.

**Hard Contract Reports**
- **Contract 1 (Field-Name Coverage):** entities[].fields 72 required, 72 present, 0 missing; request_body ids 47/47; query params 15/15. **PASS**
- **Contract 2 (Rule Coverage):** validation priority order (11 steps) expressed explicitly in §2.7 and per-endpoint in §3.5/§3.6; 1 OCC rule fully expressed (write capability + `expected_student_program_version` + `ERR_STALE_VERSION`/412, no race framing); all 24 state transitions with preconditions/side-effects; all 5 calculations reconstructible from prose (no pseudocode, no fuzzy words — mechanically scanned); all 35 error ids matchable to trigger conditions in §2/§3; all endpoint side-effects and applies_to scopes covered; sibling branches (3 decide outcomes, 2 decision steps, 3 grade-change branches, 4 audit kinds) rendered with equal density. **PASS**
- **Contract 3 (§3 Path Purity):** 433 backtick tokens scanned in §3; 0 path tokens, 0 bare HTTP methods, 0 method+path combos. **PASS**

## Step 6: Generate Implementation — 2026-08-13T02:05:00.000Z

Implementation generated at `/home/ubuntu/github/CodingPRD/tasks/task_1360_degree_audit_graduation_certification/workspace/implementation/` and verified working end-to-end with two smoke suites.

### Files created (16 source files + start.sh + requirements.txt)

- `start.sh` — foreground bash launcher; guarded dependency install (only runs `pip install` if flask missing); `exec python3 app.py`; reads `$PORT` (default 10000); binds `0.0.0.0`.
- `requirements.txt` — `flask>=3.0`.
- `app.py` — Flask app factory, blueprint registration, `ApiError`/404/405/generic exception handlers all returning the standard error envelope, a global `before_request`/`teardown_request` lock around the in-memory store for cascade atomicity.
- `db.py` — in-memory dicts for all 11 entities, logical clock initialized to `2026-08-01T00:00:00Z`, `RLock`. **No seeding.**
- `errors.py` — `ApiError` carrying `(error_id, message, http_status)`; `HTTP_STATUS` table exactly mirrors scaffold §1.6 / PRD §5.
- `response.py` — success envelope `{meta:{api_request_id,api_request_timestamp[,limit,offset,total_count,has_more]}, response_type, data}` and error envelope `{meta, response_type:"error", data:{error_id,message}}`; timestamps ISO-8601 UTC with three fractional digits; `req_*` ids.
- `middleware.py` — header extraction (`X-User-ID`, `X-User-Role`), role grant enforcement, student ownership, pagination parser enforcing limit ∈ [1,100], offset ≥ 0.
- `util.py` — UUID/timestamp helpers, JSON body parsing, field validators (string/number/int/bool/enum/ISO date/ISO datetime/str-list), `paginate()` (sort by `created_at` asc, tie-break `id`), `make_resource()` and `touch()` for `id`/`created_at`/`updated_at`/`version`.
- `services/academic.py` — grade constants, `apply_grade_to_enrollment`, GPA calculation using `Decimal` with `ROUND_HALF_UP` rounded once to 3 decimals, `recompute_student_derived`.
- `services/audit.py` — `compute_audit` implementing the waterfall allocation: process eligible enrollments in `(created_at, course_code, term, id)` order, allocate to group with largest remaining deficit (tie-break `group_code` ASC), at most one group per enrollment, CONDITIONAL variant projects IN_PROGRESS at full credits with min_grade bypassed, computes `groups_result`/`outstanding_credits`/`overall_satisfied`.
- `services/cascade.py` — the recompute chain: student derived → CURRENT STANDARD/CONDITIONAL/FINAL audits on ACTIVE declarations (WHAT_IF and SUPERSEDED never touched) → `latest_audit_satisfied` flip with `version` bump → CONDITIONALLY_CLEARED auto-resolution to CLEARED or DENIED+`CONTINGENCY_FAILED` once the student's IN_PROGRESS count reaches zero.
- `services/honors.py` — closed-interval covering policy lookup, residency gate, basis GPA selection, threshold comparison with inclusive `>=`.
- `routes/clock.py` — `POST /_clock/set_current_utc` (SystemAdmin only).
- `routes/programs.py` — programs CRUD + retire, requirement groups (with `group_code` per-program uniqueness), honors policies (closed-interval overlap detection, shared boundary IS overlap), program reverse-lookup lists.
- `routes/courses_students.py` — course/student create with `course_code`/`student_number` uniqueness, student get.
- `routes/enrollments.py` — enrollment create with `(student, course, term)` duplicate rule (WITHDRAWN sibling does not block), list with filters + student role scoping, post-grade (IN_PROGRESS only), grade-changes (COMPLETED/WITHDRAWN only).
- `routes/student_programs.py` — declare, list/get/withdraw, audit creation with `expected_student_program_version` OCC → `ERR_STALE_VERSION` (412), FINAL/CONDITIONAL restricted to RegistrarStaff, WHAT_IF requires `target_program_id` + ACTIVE target + coverage of the declaration's catalog year, supersedes prior same-kind CURRENT audit (same kind+target for WHAT_IF), bumps StudentProgram `version` by 1, FINAL refreshes `latest_audit_satisfied`.
- `routes/waivers.py` — file waiver (SUBSTITUTION requires enrollment_id, WAIVER requires credit_waiver_amount; SUBSTITUTION enrollment must exist), advisor-decision (segregation-of-duties: requested_by_role=ADVISOR && same X-User-ID → `ERR_SELF_APPROVAL_FORBIDDEN`), registrar-decision (re-checks substitution enrollment COMPLETED, fires cascade on APPROVE), resubmit (preserves original `requested_by_*`), revoke (cascade with exception removed).
- `routes/applications.py` — create (Student owner only), list/get, submit (DRAFT + no live sibling + filing deadline `clock <= conferral_date − 30d` + no financial hold), begin-review (requires CURRENT FINAL audit + no financial hold), decide (CLEARED requires satisfied FINAL audit, CONDITIONALLY_CLEARED requires ≥1 IN_PROGRESS enrollment, DENIED), confer (requires covering honors policy, computes honors, sets `conferred_at` from logical clock, transitions StudentProgram→COMPLETED and Student→GRADUATED, creates PENDING Diploma), reissue (latest diploma by `created_at` must be REVOKED, honors recomputed from current GPAs, defaults fall back to app/legal name and expected conferral date).
- `routes/diplomas.py` — list/get/issue/revoke.

### Architecture notes

- **Storage**: module-level dicts in `db.py`. Each fresh `python3 app.py` boots with empty dicts, satisfying per-test-server isolation.
- **Concurrency**: single global `RLock` acquired per request — audit recomputation is multi-step and must be atomic.
- **Validation order**: header presence (400) → role grant (403) → path existence (404) → body FK existence (404) → from-state (409) → OCC (412) → segregation of duties (403) → uniqueness/overlap (409) → filing window (422) → referenced-entity state (422/409) → financial hold (402). Structurally malformed payloads → `ERR_INVALID_REQUEST` (400).
- **Audit waterfall**: ties in allocation deficit are broken by `group_code` ASC; ties in enrollment order are broken by `course_code` then `term` then `id` (for stability when two enrollments share `created_at` in the same logical millisecond).
- **Recompute**: only hops that actually change a field call `touch()` (bump `version` + `updated_at`), per PRD §2.4 "Each hop that actually changes a resource refreshes that resource's `updated_at` and increments its `version`."

### PRD interpretation decisions

1. **Pagination validation runs after role grant but before any list filtering**, since the PRD places it under structural gatekeeping.
2. **Unknown role values** (not one of the four named) return `ERR_FORBIDDEN` rather than `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, because the header itself was present — the value simply doesn't match any grant.
3. **`reason` on grade-changes and `revoke`** is required in the body per the endpoint table but is not persisted on the entity (the entity carries no `reason` field for grade changes; for revoke it goes to `revocation_reason`). Same for `decision_reason` on DENY — persisted only when supplied.
4. **Resubmit**: `requested_by_role`/`requested_by_user_id` are explicitly preserved from the original creation (PRD: "the segregation-of-duties anchor survives the rewrite").
5. **Audit creation** always increments StudentProgram `version` by exactly 1 per the endpoint side-effects; the FINAL-audit `latest_audit_satisfied` flip may independently bump `version` via the cascade only if the flag actually changes — but since audit creation itself uses `touch(sp)` unconditionally after the flag is updated, version goes up by exactly 1 on audit creation regardless of whether the flag changed. (The flag change is not a separate cascade here because creation is itself the trigger.)
6. **`Student` role on `/enrollments`, `/student-programs`, `/diplomas` list endpoints**: results are scoped to the caller's own records (rather than returning a 403) — PRD §2.1 says "every Student interaction — reads included — is scoped to that student's own records under the ownership rule."
7. **Filing deadline comparison**: the logical clock is compared as an instant against `expected_conferral_date - 30 days` (with the date interpreted as midnight UTC); "on or before" the deadline is accepted, after is rejected.

## Step 5: Generate Unit Tests — 2026-08-13T02:30:00.000Z

Complete. Test infrastructure and suite generated for `task_1360_degree_audit_graduation_certification`.

## Summary

**Outputs**
- `test_helpers/` (9 files): `types.py` (enums + TypedDicts), `api_client.py` (42 endpoint methods, `Connection: close` for per-test-server isolation), `api_errors.py` (35 error IDs + HTTP map registered via `set_error_http_status_map`), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (entity-backed `make_student_headers`, opaque advisor/registrar/sysadmin makers), `fixtures.py` (tiered helpers: `make_program`/`make_course`/`make_student`/`enroll`/`declare`, OCC-aware `run_audit`, waiver chain helpers, `open_application`…`confer`, and the mega-fixture `setup_graduation_pipeline`), `__init__.py` barrel.
- `test_suite/`: `conftest.py` + 7 test files, **70 tests total**, all collected by pytest.

**Coverage**
- **Queue A (Difficulty): 36 tests — all 18 instances with ≥2 tests each** (9 rules × 2 instances).
- **Queue B (Corner): 34 tests — all 33 non-stub instances with ≥1 test each** (`what_if_major_change_evaluation` got 2: target evaluation + catalog-range mismatch).
- **9 stubs not translated** (6 in `errors`, 3 in `cross_cutting_layers`); all their `difficulty_instance` cross-references verified to resolve to real §1.8 instances.
- **0 instances fully skipped.** No `skip`/`skipif`/`xfail` markers anywhere.

**Per-file breakdown**: `test_01_program_catalog.py` 8, `test_02_academic_record.py` 10, `test_03_degree_audits.py` 13, `test_04_waivers.py` 9, `test_05_graduation_applications.py` 14, `test_06_conferral_honors_diplomas.py` 10, `test_07_security_and_envelope.py` 6.

**Audit notes (partial-scope translations, both PRD-derivability driven):**
1. `Corner/validations/active_application_uniqueness` — the recipe's blocking half asserts the *create* of a second application is rejected while a DRAFT sibling exists, but the PRD anchors `ERR_ACTIVE_APPLICATION_EXISTS` only to submission ("...blocks the filing with `ERR_ACTIVE_APPLICATION_EXISTS`"). A faithful PRD-only implementer could permit the create. The test therefore covers only the uniquely-derivable half: a terminal DENIED application does not block a fresh application (created *and* submitted successfully).
2. `Corner/validations/filing_deadline_inclusive_boundary` — the recipe's "+1 second past midnight fails" probe is not uniquely derivable from "the logical clock must read on or before the date thirty days before the `expected_conferral_date`" (timestamp-midnight vs whole-calendar-day readings diverge). The test keeps the exact-deadline pass (2026-08-16T00:00:00Z succeeds under both readings) and probes the fail side at 2026-08-17T00:00:00Z, which is unambiguously past under either reading.

**Verification performed**: all files compile; every docstring carries verbatim PRD quotes (normalized-substring grep against PRD.md passes for all 70 tests); every docstring ends with exactly one `Design:` tag resolving to a real instance; no test references scaffold terminology; `test_helpers` imports cleanly.

## Step 7: Test-Fix Diagnostic Loop — 2026-08-13T02:10:00.000Z

### Sweep 1 (baseline): 59-60/70 per round; union of 11 failing tests in 3 buckets

1. **8 tests × 8 rounds — setup 409 `ERR_UNIQUE_CONSTRAINT_VIOLATION` on course_code.**
   Root cause in `test_helpers/fixtures.py::setup_graduation_pipeline`: it created one
   course per enrollment spec, but several tests legitimately enroll the same course in
   multiple terms (PRD §3.2 allows re-enrollment per term; course codes are globally
   unique). Fix: per-call course cache keyed on `course_code` inside
   `setup_graduation_pipeline` (test_helpers fix — fixture constructed preconditions
   that violate PRD's course-code uniqueness).
2. **2 tests × 8 rounds — `Expected GPA 2.8, got 3.5`.**
   `test_single_final_rounding_institutional` / `test_single_final_rounding_cumulative_coincides`
   (test_02): the design instance's arithmetic slip — fixture data is 1cr A + 2cr B +
   1cr A = 14 grade points over 4 attempted credits, so PRD §2.9's pinned formula gives
   14/4 = 3.500, not the docstring's "14/5 = 2.800". Implementation was PRD-correct.
   Fix: expected values 2.800 → 3.500 in both tests + docstring correction; the
   per-term round-then-average contrast (3.667) is preserved and still rejected.
3. **1 test × 6/8 rounds — "API server could not be restarted" (infra flake).**
   All failures at the same wall-clock second across rounds: SIGKILL→rebind race and
   host-wide load spikes from concurrent benchmark pipelines. Fix:
   `workspace/implementation/app.py` now retries the bind on transient `EADDRINUSE`
   (up to 40 × 0.25s) so a slow-to-release predecessor socket cannot kill the boot.

### Sweep 2: 64/70 per round; union of 7 failing tests

- The 8-test setup-409 bucket dropped to 2 tests: `TestHonorsGpaBasisDivergence`
  (`test_identical_records_yield_divergent_basis_gpas`,
  `test_conferral_designations_diverge_by_basis`) calls `setup_graduation_pipeline`
  TWICE per test with identical course codes — the second call hit the global
  course-code uniqueness. Fix (test_suite/test_06): `DIVERGENT_ENROLLMENTS` replaced by
  `_divergent_enrollments(prefix)` generating per-scenario course codes
  (`CI100/CI101/CIR500` vs `CC100/CC101/CCR500`); GPAs unchanged (3.900/2.950).
- Restart flake spread to 5 tests (bursts at 4 wall-clock seconds) — external load
  (60+ concurrent prd-bench-local-run processes from other task pipelines on the
  32-core host). No test/implementation rule implicated.

### Sweep 3 (final): 70/70 in all 8 rounds — CLEAN

Union of failures: 0. All three fixes held under ~60 concurrent external
prd-bench-local-run processes on the host. No tests were deleted; every fix traced
to a verbatim PRD sentence or to test-side data inconsistent with PRD.

## Step 8: Finalize PRD — 2026-08-13T02:45:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1360_degree_audit_graduation_certification/workspace/PRD_FINALIZED.md` produced with exactly one inline revision.

**Line counts / delta:** PRD.md 313 lines (47,748 bytes) vs PRD_FINALIZED.md 313 lines (48,015 bytes) — 0.00% line delta, +267 bytes (+0.56%); single-paragraph edit, no new sections.

**Changes:**
- §3.2 — revise — pinned `course_code` uniqueness as global across the entire course catalog, stated the `ERR_UNIQUE_CONSTRAINT_VIOLATION` rejection applies regardless of which terms/enrollments the existing course is used in, and clarified that re-taking a course in a later term means a new enrollment under the existing course, not re-creating it — `implementation/routes/courses_students.py:29-33` (global uniqueness scan) and `implementation/routes/enrollments.py:61-71` (duplicate-enrollment scoped per student+course+term).

**Per-edit pre-edit search log:**
- Edit 1 (§3.2 course-code uniqueness scope):
  - (a) Subject: scope of the `course_code` uniqueness constraint and its interaction with the per-(student, course, term) duplicate-enrollment rule.
  - (b) Impl paths enumerated/read: `routes/courses_students.py:19-39` (only course-creation path — global scan of `db.courses`); `routes/enrollments.py:38-93` (only enrollment-creation path — duplicate check on `student_id`+`course_id`+`term` with IN_PROGRESS/COMPLETED sibling); `services/audit.py:68-100` (reads `course_code` only for eligibility membership and the created_at/course_code/term tie-break — no uniqueness semantics); `routes/programs.py:133-151` (`eligible_course_codes` stored as plain strings, no existence validation); greps confirming single write paths for `db.courses[`/`db.enrollments[` and all four `ERR_UNIQUE_CONSTRAINT_VIOLATION`/`ERR_DUPLICATE_ENROLLMENT` raise sites (`courses_students.py:32,63`, `programs.py:141` group_code, `enrollments.py:69`); `test_helpers/fixtures.py:222-235` fixture comment corroborating global uniqueness with legal per-term re-takes.
  - (c) Wording adjustment: used "unique across the entire course catalog — a single global scope" plus the enrollment-agnostic rejection clause and the re-take sentence, instead of enumerating "not per term/program/student" (courses carry no such associations; enumerating them could imply they exist). Confirmed the wording makes no claim about `eligible_course_codes` validation (impl has none) and leaves the already-explicit duplicate-enrollment sentence untouched.

**Step-7 items judged non-edits:**
- test_02 rounding (item 2): PRD §2.9 already uniquely pins the formula (single final round-half-up to 3 decimals; 14/4 = 3.500); `services/academic.py:44-61` matches verbatim — the test expectation was the defect.
- test_06 per-scenario codes (item 3): honors basis selection (`services/honors.py:17-32`) matches PRD §3.7; the collision was the same global-course-code theme covered by the §3.2 edit.
- app.py EADDRINUSE bind retry (item 4): behavior-neutral boot hardening with zero API-observable surface; startup is INSTRUCTION.md's contract, outside the PRD's domain, and the step-7 note itself flags it as API-neutral.

## Step 9: Complete PRD — 2026-08-13T03:05:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1360_degree_audit_graduation_certification/workspace/PRD_COMPLETED.md` produced from `PRD_FINALIZED.md` (which existed; it was itself only a 1-hunk delta over `PRD.md`).

**Source vs output:** PRD_FINALIZED.md 313 lines / 47,840 chars → PRD_COMPLETED.md 315 lines / 51,114 chars (+2 lines, +3,274 chars).

**Counts:** 19 ambiguity-pins, 2 mismatch-revisions (21 change bullets total; no new sections, all inline inserts/revisions).

- §2.1 — insert — ambiguity — present-but-unrecognized `X-User-Role` value is rejected with `ERR_FORBIDDEN` (403), not the 400 header error — implementation/middleware.py:30-35
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` also yields `ERR_INVALID_PAGINATION_PARAMETERS` — implementation/middleware.py:58-65
- §2.3 — insert — ambiguity — list sort ties on `created_at` broken by `id` ascending — implementation/util.py:139
- §2.4 — insert — ambiguity — `version` starts at 1 and `created_at` == `updated_at` at creation — implementation/util.py:150-155
- §2.7 — revise — mismatch — the Student-ownership and `FINAL`/`CONDITIONAL` kind checks land *after* path-existence 404s (ownership needs the loaded resource; kind restriction needs the parsed body), contrary to the strict step-2-before-step-3 reading — implementation/routes/student_programs.py:142-150, implementation/routes/courses_students.py:91-95
- §2.7 — insert — ambiguity — malformed-payload definition extended: wrong JSON field types, empty required strings, non-JSON/non-object bodies, undefined routes/methods, and unexpected server failures all surface `ERR_INVALID_REQUEST` (400) — implementation/util.py:31-96, implementation/app.py:43-62
- §3.1 — insert — ambiguity — authoring requirement groups / honors policies under a `RETIRED` version remains permitted — implementation/routes/programs.py:123-155, 179-227
- §3.1 — insert — ambiguity — `min_total_credits`, `min_gpa`, `required_credits`, and honors thresholds validated for numeric type only (no positivity/ordering); year fields and `residency_min_credits` must be integers — implementation/routes/programs.py:51-54, 131, 186-196
- §3.2 — insert — ambiguity — course `credits` validated as a number with no positivity constraint — implementation/routes/courses_students.py:27
- §3.2 — revise — mismatch — a `W` supplied at enrollment creation starts the enrollment `WITHDRAWN`, not `COMPLETED` — implementation/services/academic.py:31-34, implementation/routes/enrollments.py:88-89
- §3.2 — insert — ambiguity — graded creation applies the grade as a second mutation, so the enrollment first appears with `version` 2 — implementation/routes/enrollments.py:88-91
- §3.2 — insert — ambiguity — grade-change `reason` is required but not persisted on the enrollment — implementation/routes/enrollments.py:178
- §3.3 — insert — ambiguity — no uniqueness constraint on declarations; multiple declarations per student (even same program version) allowed — implementation/routes/student_programs.py:34-69
- §3.3 — insert — ambiguity — withdrawal is never blocked by attached audits, exceptions, or applications — implementation/routes/student_programs.py:118-130
- §3.4 — revise/insert — ambiguity — for `STANDARD`/`CONDITIONAL`/`FINAL` runs a client-supplied `target_program_id` is disregarded and recorded as the declared program; kind restriction enforced after `audit_kind` is parsed — implementation/routes/student_programs.py:147-161
- §3.4 — insert — ambiguity — a `FINAL` creation that flips `latest_audit_satisfied` still advances the declaration `version` by exactly one — implementation/routes/student_programs.py:235-238
- §3.4 — insert — ambiguity — `groups_result` is emitted in group creation order (`created_at` asc, `id` tie-break) — implementation/services/audit.py:45, 124-138
- §3.5 — insert — ambiguity — exception references are existence-only: the group need not belong to the declaration's program, the substituted enrollment need not belong to the student; opposite-kind fields stored as null — implementation/routes/waivers.py:48-67, 87-88
- §3.5 — insert — ambiguity — resubmission clears `decision_reason`; decision/resubmit/revoke remain available after the declaration leaves `ACTIVE` — implementation/routes/waivers.py:150-300 (no sp-status checks), 273
- §3.6 — insert — ambiguity — filing deadline is an instant comparison: conferral date taken as midnight UTC minus 30 days; filing at exactly that instant passes — implementation/routes/applications.py:174-182
- §3.6 — insert — ambiguity — conditional auto-resolution runs only for `ACTIVE` declarations (cascade scope), so a conditionally cleared application on a since-withdrawn declaration never auto-resolves — implementation/services/cascade.py:31-38, 76-109
- §3.7 — insert — ambiguity — confer returns the updated application object (200), not the new diploma — implementation/routes/applications.py:326
- §3.7 — revise — ambiguity — diploma revocation's `revocation_reason` is a required field — implementation/routes/diplomas.py:105
- §3.7 — insert — ambiguity — "latest diploma" for reissue is most recent by `created_at` with `id` tie-break — implementation/routes/applications.py:356

Notable deliberately-unpinned items (verified no observable behavior): the waiver approve/revoke path skipping the conditional-application cascade hop is behaviorally inert given the CONDITIONALLY_CLEARED⇒IN_PROGRESS invariant; `ERR_HONORS_POLICY_MISSING` at reissue and `ERR_AUDIT_NOT_SATISFIED`-on-missing-final at decide are unreachable since policies/audits are never deleted; GPA "0.000" is a numeric value (impl serializes `0.0`).
