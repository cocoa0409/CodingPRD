# Worklog — task_0389_online_course_marketplace

Scenario: 389. Online Course Marketplace (Udemy/Coursera style): course catalog & curriculum, enrollment & progress tracking, quiz/assessment & certificate, instructor revenue share & payout, coupon/bundle pricing, rating/review & refund window, drip content, completion/CEU

## Step 1: Create task directory — 2026-06-17T04:26:06.000Z

Created `tasks/task_0389_online_course_marketplace/` and `tasks/task_0389_online_course_marketplace/workspace/`. Index 0389 (max existing was 0388).

## Step 2: Generate scaffold — 2026-06-17T04:48:29.000Z

Generated all three scaffold artifacts under `tasks/task_0389_online_course_marketplace/`, built purely from the scenario + skill spec (no sibling tasks inspected). `scaffold_lint.py` returns **VERDICT: clean lint** (415 calls scanned, all conform to §1.5; all 12 FKs reverse-reachable).

**Files:** SCAFFOLD.yaml (§1.0–§1.7), SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8, single top-level key), SCAFFOLD_CORNER_DESIGN.yaml (§1.9, single top-level key).

**Complexity profile:** pricing_engine + event_sourcing; flat entity topology; branching state-machine shape; peer_roles; immediate consistency. Layers: dual-variant calc, cascading side effects, rate/threshold triggers, derived-field reconciliation, optimistic concurrency.

**Counts:**
- **Entities: 12** — Instructor, Learner, Course, Lesson, Coupon, Bundle, Enrollment, LessonCompletion, Certificate, Review, Payout, RevenueLedgerEntry (Certificate + RevenueLedgerEntry are append-only, `common_fields: false`).
- **State machines: 5** — Course (DRAFT→PUBLISHED↔UNPUBLISHED→RETIRED, with cascade), Enrollment (branching fork to COMPLETED/REFUNDED/EXPIRED), Coupon (ACTIVE↔EXHAUSTED cycle + DISABLED), Payout (REQUESTED→PAID/REJECTED), Review (PUBLISHED↔HIDDEN, →RETRACTED).
- **Concurrency rules: 2** — OCC on Instructor.version (payout approve) and Bundle.version (bundle enroll), both 412/ERR_STALE_VERSION.
- **Calculations: 4** — enrollment_pricing (single vs largest-remainder bundle allocation), course_weighted_score (weighted_gate vs simple_average_transcript), lesson_completion_score (inclusive ≥ threshold), instructor_balances (PENDING/AVAILABLE/CLAWED_BACK aggregation).
- **Validations: 19** (priority-ordered, 8 categories).
- **Endpoints: 46** (includes filtered-list reverse-reach GETs and one `/_clock/set_current_utc` test-driving endpoint).
- **Error catalog: 19.**
- **RBAC roles: 4** — Anonymous (opaque), Instructor (entity_backed), Learner (entity_backed), PlatformAdmin (opaque).

**Difficulty/corner instance counts:**
- §1.8: **18 instances** = 9 rules × 2 (dual_variant_calc, combinatorial_formula [modes a+b], non_linear_state_machine, transitive_cascade [depth-3 refund chain + depth-2 retire chain], priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap [coupon half-open + bundle buffer-gap], compensating_invariant [lifetime_earned + coupon redeemed_count]).
- §1.9: **43 instances total** = 37 active test recipes + 6 `excluded_because` stubs, spanning all 9 taxonomy sections.

Two interval-overlap features with distinct semantics: Coupon validity windows (half-open `[from, until)`, adjacency allowed) and Bundle promo windows (closed + mandatory 1-day buffer), each with its own error code.

## Step 3: Copy shared files — 2026-06-17T04:48:50.000Z

Copied `INSTRUCTION.md` → `tasks/task_0389_online_course_marketplace/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-17T04:56:41.000Z

Generated `workspace/PRD.md` for the Online Course Marketplace domain.

**Document metrics:**
- **5 top-level sections** (Introduction; Global Specifications; Business Logic & Workflows; Endpoint Definitions; Error Code Catalogue)
- **22 subsections** — 11 in §2 (access control, response structure, pagination, common properties, reverse-reach retrieval, monetary precision, revenue-ledger principle, logical clock, cascades/consistency, optimistic concurrency, validation ordering) and 11 in §3 (accounts, catalog, publishing, single-course pricing, coupons, bundles, learning/scoring, completion/certificates, refund/expiry, reviews/moderation, payouts)
- **275 lines**
- **46 endpoints** (4-column table) and **19 error codes** (2-column table), all matching the scaffold

**Hard Contract results (all PASS):**
- Contract 1 — Field-Name Coverage: 78 required identifiers, 0 missing
- Contract 2 — Rule Coverage: both OCC rules, all calculations, all state transitions with side-effect cascades, validation priority ordering, all 19 error triggers in prose
- Contract 3 — §3 Path Purity: 316 backtick tokens scanned, 0 paths/methods leaked

**Confirmation:** SCAFFOLD_DIFFICULTY_DESIGN.yaml and SCAFFOLD_CORNER_DESIGN.yaml were NOT read.

> Note: Steps 5 & 6 were first launched concurrently around 13:00 but both subagents hit transient API errors (529 Overloaded / connection-closed) before returning summaries; their partial on-disk outputs did not survive the session gap. Re-launched concurrently below.

## Step 5: Generate unit tests — 2026-06-17T12:35:19.000Z

Generated complete test infrastructure from the two design indices only (no freelance discovery from SCAFFOLD.yaml).

### test_helpers/ (9 files — Stage 1)
- `__init__.py` — barrel export (framework generics + PRD-specific)
- `types.py` — entity TypedDicts (mutable carry id/created_at/updated_at/version; `Certificate` and `RevenueLedgerEntry` carry only id/created_at per PRD §2.4) + status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint
- `api_errors.py` — `ApiErrorId` enum + HTTP status map, registered with the framework
- `assertions.py` — per-entity assertions with the mutable/immutable common-field split
- `factories.py` — per-endpoint payload factories (input fields only; unique-email sequencing)
- `constants.py` — course/instructor defaults, promo buffer, `MISSING_UUID`
- `test_users.py` — opaque (Anonymous/PlatformAdmin) shared constants + entity-backed (Instructor/Learner) `make_*_headers(id)` builders with identity threading
- `fixtures.py` — composite setup helpers (published courses, graded courses, bundles, enrollment lifecycle, refund/expiry/completion, payouts, reviews)

### test_suite/ (6 test files + conftest.py — Stage 2)
- **73 test functions total**, every one carrying exactly one verbatim `Design:` tag.
- **Queue A (Difficulty): 36 tests** — all **18** difficulty instances covered, each with exactly **2** tests.
- **Queue B (Corner): 37 tests** — all **37** non-stub corner instances covered (≥1 each).

### Skips / stubs
- **0 instances skipped** under the PRD-first filter — every difficulty and non-stub corner instance had verbatim PRD coverage that uniquely derives the asserted outcome.
- **6 `excluded_because` stubs** correctly not translated; all 6 cross-references verified to resolve to real difficulty instances.

### Notable PRD-faithfulness corrections made during generation
- `missing_auth_headers_returns_unauthenticated`: corner setup used the `Anonymous` role (→403 not 401), so the test uses an unrecognized role — still uniquely deriving `ERR_UNAUTHENTICATED` from the same verbatim §2.1 sentence.
- `occ_payout_approve_stale_version_rejected`: corner setup requested a payout while balance was 0 (PRD §3.11 forbids that). Rebuilt with two sales so the first expiry funds the request and the second expiry bumps the instructor version, staying PRD-faithful while still reaching the stale-version 412.

### Audits passed
All files compile; every test has exactly one Design tag (no untagged/dual-tagged); no `skip`/`skipif`/`xfail`; no scaffold leakage; all 74 quoted PRD citations verified as verbatim substrings of `workspace/PRD.md`; all `test_suite` imports resolve against the barrel exports.

## Step 6: Generate implementation — 2026-06-17T12:49:46.000Z

Generated a complete Python + Flask implementation in `workspace/implementation/`, built purely from PRD.md + SCAFFOLD.yaml + INSTRUCTION.md (no test files consulted; explicit no-peek instruction given because test_suite/ already existed from Step 5).

**Files written (27 total):**
- `start.sh` (foreground launcher, guarded pip install), `requirements.txt` (Flask 3.0.3)
- `app.py` (entry point, blueprint registration, error envelope handlers)
- Core modules: `db.py` (in-memory store), `clock.py` (logical clock), `errors.py` (error catalog), `response.py` (envelope helpers), `middleware.py` (auth/RBAC)
- `routes/` (11 files): accounts, courses, lessons, coupons, bundles, enrollments, lesson_completions, certificates, reviews, payouts, clock_routes
- `services/` (6 files): common, serialize, ledger, pricing, course_derived, enrollment_logic

**Endpoints implemented: 47** — full §1.5 / §4 surface.

**Storage approach:** pure in-memory dicts keyed by UUID, empty on every boot — no seeding. Balances aggregate fresh over an append-style `RevenueLedgerEntry` collection per PRD §2.7.

**Key PRD-fidelity decisions:**
- Revenue ledger + `instructor_balances` aggregation per formula (lifetime_earned → -500 after sale+refund because SALE flips to CLAWED_BACK/excluded while REFUND -share is included).
- Balance recompute bumps instructor `version` only when a value actually changes (keeps instructor-version OCC coherent across reads).
- Largest-remainder bundle allocation with created_at tie-break; round-half-up cents via `Decimal`; 4dp scores, 2dp ratings.
- Validation priority order per §2.11 (auth → forbidden → not-found → state → business → OCC → field-level). EXHAUSTED coupon yields priority-6 `ERR_COUPON_NOT_REDEEMABLE` before priority-8 exhausted check.
- Half-open coupon-window overlap (touching allowed) and closed-with-1-day-buffer bundle promo overlap.
- Lazy `ACTIVE→EXPIRED` on read/write past `refund_deadline` (flips SALE PENDING→AVAILABLE); auto `ACTIVE→COMPLETED` with certificate issuance + CEU award.

**start.sh:** reads `$PORT` (default 10000), binds `0.0.0.0`, guards pip install on flask import check, `exec`s `python3 app.py` in foreground. Verified via kill-and-reboot cycle.

**Orchestrator verification:** all 27 impl `.py` files + all test files (`test_helpers/` + `test_suite/`) pass `py_compile`.

## Step 7: Run tests and iterate — 2026-06-17T13:07:08.000Z

**Iterations run:** 2 fix iterations (3 sweeps total: 1 baseline + 2 verification). Final sweep: all 8 parallel rounds passed 72/72. Orchestrator re-confirmed independently with a 9th sweep: 72/72 passed, 0 failed.

**Baseline:** 14/72 passing, stable across all 8 rounds (not flaky — systematic). One shared setup error (`ERR_COURSE_NOT_PUBLISHABLE - Total quiz_weight across graded lessons must be >= 1`) blocked 54 tests, plus 5 other distinct failures.

**Tests deleted (1):**
- `test_publish_graded_lesson_missing_questions_not_publishable` (test_05) — **STEP 1b unique-derivability collapse (unreachable precondition)**. Asserts publishing a course with a graded lesson at `question_count=0` yields `ERR_COURSE_NOT_PUBLISHABLE`, but PRD §3.2 states verbatim that `question_count` "must be at least 1 when `is_graded` is true" — a generic field-level validation (`ERR_INVALID_REQUEST`, 400) at lesson creation. A faithful implementer rejects the lesson at creation, so the publish-time state is unreachable; the asserted outcome is not uniquely derivable. Scaffold rule: `Corner/state_machines/publish_graded_lesson_missing_questions_not_publishable`.

**Fixes applied to test_suite/ (test bugs, STEP 2 — assertions/setups inconsistent with PRD):**
- `test_02_scoring_and_completion.py` — `_setup_graded_three_lesson_enrollment`: lowered `completion_threshold_pct` 1.00→0.60 so a 2-of-3-pass enrollment (progress 0.67) actually completes and issues a certificate; weighted 0.86 still diverges from the simple average.
- `test_04_refund_revenue_ledger.py` — two assertions: corrected `lifetime_earned_cents` expectation 0 → **-2000** to match PRD §2.7's verbatim formula (after refund the SALE is CLAWED_BACK/excluded and the REFUND -2000 is included). Old "nets to 0" assertions contradicted the formula they quoted.
- `test_05_state_and_payouts.py` — (a)+(b) two 0-balance payout setups violated PRD §3.11 (`payout_balance_cents >= 1` to request); rebuilt to fund via window-expiry flip first ((b) drains to 0 by approving a first payout, then approves a second to faithfully reach approve-time `ERR_INSUFFICIENT_BALANCE`). (c) `test_bundle_enroll_with_stale_version_after_retire_cascade_rejected`: **STEP 1b ERROR PRECEDENCE relaxation** — retire cascade → RETIRED bundle; PRD §2.11 orders state eligibility before OCC, so relaxed to `validate_error_is_one_of([ERR_STALE_VERSION, ERR_INVALID_STATE])` (both PRD-grounded).
- `test_06_catalog_crud_rbac.py` — `test_instructor_cannot_approve_payout`: same 0-balance setup issue; funded via expiry so the REQUESTED payout exists, leaving the RBAC `ERR_FORBIDDEN` assertion intact.

**Fixes applied to implementation/ (STEP 3 — true implementation bug):**
- `routes/courses.py`, `publish_course`: the publish gate enforced `sum(quiz_weight) >= 1` even for courses with **zero graded lessons** (empty sum = 0 < 1), making every non-graded course unpublishable. PRD §3.8 explicitly supports them ("A course with no graded lessons auto-satisfies the score condition"), so the constraint is now vacuous when no graded lesson exists. This unblocked the 54-test setup cluster.

All in-memory storage untouched (no seeding); start.sh and the boot path unmodified. Final test count: 72 functions.

## Step 8: Finalize PRD — 2026-06-17T13:12:11.000Z

Produced `workspace/PRD_FINALIZED.md` (minimal inline patch of PRD.md scoped to `<step_7_diff>` items).

**Line counts:** PRD.md = 275, PRD_FINALIZED.md = 275, **0% line-count delta** (both edits are inline expansions within existing paragraphs).

**Changes (2):**
- **§3.3 (Publishing) — revise** — scoped the `sum(quiz_weight) >= 1` publish-gate requirement to apply only when the course has ≥1 graded lesson; a no-graded-lesson course satisfies it vacuously and is publishable on ≥1 lesson alone — `implementation/routes/courses.py:154-163` (the `if graded_lessons:` guard). Traces to Step 7 Item 3 (impl fix); the original literal "sum across graded lessons must be at least 1" was a mismatch (empty sum = 0 < 1 made every non-graded course unpublishable).
- **§2.10 (OCC) — revise** — clarified bundle-enroll evaluates state eligibility before the OCC version check (per §2.11): a retire-cascade-RETIRED bundle yields `ERR_INVALID_STATE` (409), while `ERR_STALE_VERSION` (412) remains the outcome for a still-`ACTIVE` bundle whose version no longer matches — `implementation/routes/enrollments.py:195` (state check) precedes `:199` (OCC). Traces to Step 7 Item 2c (ERROR PRECEDENCE relaxation).

**Items intentionally not edited** (fixture bugs / already PRD-determined): Item 1 test deletion (§3.2 already pins creation-time `question_count>=1`); test_02 threshold value change; test_04 `lifetime_earned_cents` (§2.7 formula already matches `ledger.py`); test_05 a/b + test_06 payout-balance setups (§3.11 already requires `payout_balance_cents >= 1`).

Per-edit pre-edit NO-NEW-MISMATCH search was performed for both edits (enumerated re-publish path, lesson-creation validation, weighted-score denominator, retire cascade, enroll's own version bump, payout OCC) — wording scoped to avoid claims about off-site paths.

## Step 9: Complete PRD — 2026-06-17T13:19:05.000Z

Produced `workspace/PRD_COMPLETED.md` (full PRD-vs-implementation scan starting from PRD_FINALIZED.md).

**Source vs output:** PRD_FINALIZED.md = 275 lines / 46,510 chars → PRD_COMPLETED.md = 275 lines / 47,510 chars (**+1,000 chars**, 0 line delta; all in-paragraph inserts).

**Counts:** ambiguity-pins = 5 (one paragraph combined two adjacent silences); mismatch-revisions = 0.

**Per-change:**
- §3.4 Pricing/Enrollment (Single-Course) — insert — ambiguity — single-course enroll allowed only from `PUBLISHED`; DRAFT/UNPUBLISHED/RETIRED → `ERR_INVALID_STATE` (409) — `routes/enrollments.py:91-92`
- §3.4 Pricing/Enrollment (Single-Course) — insert — ambiguity — `coupon_code` resolving to no coupon of the course's instructor → `ERR_COUPON_COURSE_MISMATCH` (422); resolution case-insensitive over the instructor's coupons — `routes/enrollments.py:144-156`
- §3.6 Bundles — insert — ambiguity — successful bundle enroll returns `201` with `response_type` array, data = created member enrollments in member-course order — `routes/enrollments.py:213-229`
- §3.8 Completion/Certificates — insert — ambiguity — enrollment→certificate reverse-reach read returns `response_type` array (one element after completion, empty otherwise) — `routes/enrollments.py:383-386`
- §3.9 Refund Window — insert — ambiguity — `REFUND` ledger entry written with status `AVAILABLE` (counts toward `lifetime_earned_cents`) — `routes/enrollments.py:332-333`, `services/ledger.py:41-43`

**Left unchanged (deliberate):** list-endpoint auto-scoping (consistent with §2.1, untested, no clean pin site); coupon-resolution vs duplicate-enrollment guard ordering (both readings under §2.11 business band); defensive "PUBLISHED course must still have ≥1 published lesson to enroll" check (unreachable given publish gate).

---

## Pipeline complete

All 9 steps done. Final state: 72 tests, 8/8 parallel rounds green + independent 9th sweep 72/72. Outputs: SCAFFOLD.yaml + 2 design indices, PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, test_helpers/ (9), test_suite/ (conftest + 6), workspace/implementation/ (27 files).
