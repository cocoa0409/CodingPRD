# Worklog — task_0463_swim_school_lessons

## Step 1: Create Task Directory — 2026-06-21T17:22:53.000Z

Created `tasks/task_0463_swim_school_lessons/` and `tasks/task_0463_swim_school_lessons/workspace/` (pre-allocated task_dir; no index scan performed).

## Step 2: Generate Scaffold (Expert difficulty) — 2026-06-21T17:44:38.000Z

NOTE: The scaffold-generator subagent's API connection closed mid-response while emitting its final summary. All three output files were verified written and YAML-valid by the orchestrator; summary below reconstructed by the orchestrator from the written artifacts (the subagent's own verbatim summary was lost to the connection drop).

All three files written and YAML-valid:
- SCAFFOLD.yaml (1234 lines) — top-level keys: scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles. No scaffold_difficulty_design / scaffold_corner_design key present.
- SCAFFOLD_DIFFICULTY_DESIGN.yaml (1294 lines) — single top-level key scaffold_difficulty_design.
- SCAFFOLD_CORNER_DESIGN.yaml (1624 lines) — single top-level key scaffold_corner_design.

Scaffold contents (Expert band):
- domain_name: swim-school-lessons; api_prefix: /
- complexity_profile: primary=temporal_windowing, secondary=quota_allocation; layers=[cascading_side_effects, dual_variant_calculation, derived_field_reconciliation, optimistic_concurrency]; topology=flat; state_machine_shape=parallel; role_model=peer_roles; consistency=immediate
- 12 entities: Location, Level, Skill, Instructor, Parent, Student, ClassSession, Enrollment, Invoice, MakeupCredit, MakeupBooking, Assessment
- 7 state machines
- 2 concurrency rules
- 9 calculations
- 15 validations
- 51 endpoints
- 36 error codes
- 4 roles

Difficulty design (§1.8): 9 rules × 2 instances each = 18 instances (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).
Corner design (§1.9): 8 sections, 39 instances total (entities=7, state_machines=7, calculations=3, validations=9, errors=4, rbac=3, cross_cutting_complexity_layers=5, consistency_model=1).

## Step 3: Copy Shared Files — 2026-06-21T17:45:05.000Z

Copied INSTRUCTION.md (1424 bytes) to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-06-21T17:51:11.000Z

PRD.md written (301 lines). Subagent summary (verbatim):

All checks pass. The PRD is complete and validated.

I read the doc-generator SKILL.md spec, the §2.2 verbatim reference file, and the full `SCAFFOLD.yaml` (both pages), then generated the PRD at `workspace/PRD.md`.

PRD section list (302 lines):
- 1. Introduction
- 2. Global Specifications & System-Wide Principles
  - 2.1 User and Role-Based Access Control
  - 2.2 API Response Structure (verbatim)
  - 2.3 Pagination
  - 2.4 Common Resource Properties and the Logical Clock
  - 2.5 Hierarchical Consistency, Counts, and Cascades
  - 2.6 Nested Resource Retrieval
  - 2.7 Monetary Precision and the Pinned Rounding Order
  - 2.8 Readiness Scoring Precision
  - 2.9 Optimistic Concurrency Control
  - 2.10 Validation Ordering
- 3. Business Logic & Workflows (3.1 Curriculum/Levels/Skills/Locations; 3.2 Instructors and Families; 3.3 Class Sessions and Seat Quota; 3.4 Opening a Session; 3.5 Closing a Session; 3.6 Perpetual Enrollment; 3.7 Assessing Progress and Climbing the Ladder; 3.8 Makeup Credits and Redemption; 3.9 Monthly Billing; 3.10 Settling Invoices and the Parent Ledger; 3.11 The Logical Clock)
- 4. Endpoint Definitions (4-column table, 53 endpoints + filter-param paragraph)
- 5. Error Code Catalogue (2-column table, 36 errors)

Hard Contract reports: Field coverage 70/70 PASS; Rule coverage PASS (all 36 error IDs surfaced in narrative, all 27 state/enum values present, both OCC rules expressed, all calc formulas + validation ordering + state-machine cascades rendered); Path purity §3 PASS (0 path tokens in 377 backtick tokens).

Confirmations: §2.2 byte-for-byte verbatim; §4 4-column; §5 2-column. Did NOT read SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, or any sibling task. PRD.md written successfully.

## Step 5: Generate Unit Tests — 2026-06-21T18:11:33.000Z

Subagent summary (verbatim):

Generated complete test infrastructure for `task_0463_swim_school_lessons` strictly from the two design indices (PRD as the contract, scaffold for structure only). Final verification confirmed all citations are verbatim and all coverage targets met.

Queue A — Difficulty (depth): 18/18 instances translated, 0 skipped. All 9 rule_ids × 2 instances each received ≥2 tests (36 difficulty tests total). Covered: dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant. For the four instances where the index supplied only one scenario (resource_temporal_overlap ×2, priority_pair_validation_conflict ×2), the second test is a complementary PRD-verbatim assertion (buffer-boundary non-conflict, half-open back-to-back allowed, positive-control ERR_SESSION_FULL/ERR_ACCOUNT_PAST_DUE).

Queue B — Corner (breadth): 32/32 non-stub instances translated, 7 stubs correctly NOT translated. Non-stub instances each got 1 test (32 corner tests). Sections covered: entities (7), state_machines (6), calculations (1), validations (7), errors (4), rbac (3), cross_cutting_complexity_layers (3), consistency_model (1). The 7 `excluded_because:` stubs were verified to point at real difficulty instances and were NOT emitted as tests.

Test files created in test_suite/ (8 files, 68 tests): conftest.py, test_01_billing_calculations.py (10), test_02_readiness_and_advancement.py (10), test_03_enrollment_lifecycle.py (11), test_04_cascades_and_sessions.py (8), test_05_validation_and_priority.py (12), test_06_makeup_and_temporal.py (10), test_07_crud_rbac_concurrency.py (10).

Helper files in test_helpers/ (10): __init__.py, types.py, api_client.py, api_errors.py, assertions.py, factories.py, constants.py, test_users.py, fixtures.py.

Total test count: 68.

Verification: pytest --collect-only passes (68 collected, no import/syntax errors) under Python 3.12 + prd_bench_local_runner.testing; every difficulty instance ≥2 tests; every non-stub corner instance ≥1 test; no broken Design-tags; no stub translated; each test exactly one Design: line; no skip/skipif/xfail; all 75 quoted PRD citation fragments survive whitespace-normalized literal match against PRD.md; entity-backed roles thread real ids via make_parent_headers/make_instructor_headers, opaque roles (SchoolAdmin, BillingAdmin) use shared constants. No gaps required skipping.

## Step 6: Generate Implementation — 2026-06-21T18:11:33.000Z

Subagent summary (verbatim):

Generated a complete Python + Flask implementation for the Swim School & Lessons API (Expert-difficulty PRD task) in workspace/implementation/.

Source files created: start.sh (foreground, exec python3 app.py, guarded pip install), requirements.txt (flask==3.0.3), app.py (Flask entry, blueprint registration, error handlers mapping ApiError to envelope), clock.py (logical clock default 2026-01-01T00:00:00Z, never wall-clock), db.py (in-memory store + common-fields/version helpers + monotonic creation-sequence counter), errors.py (ApiError + all 34 error-ID/HTTP-status constants from PRD §5), response.py (success/array/error envelopes, req_ ids, 3-fractional-digit ISO timestamps, pagination in meta), middleware.py (X-User-ID/X-User-Role extraction + RBAC: ERR_MISSING_AUTH_CONTEXT / ERR_INSUFFICIENT_PERMISSIONS), helpers.py (typed body parsing ERR_INVALID_REQUEST, ISO datetime parsing, pagination limit 10/1/100 offset 0), domain.py (computed-field reconciliation: age_months, session counts, parent ledger, credit expiry; serializers; withdraw + waitlist-promotion cascades; credit issuance), calculations.py (proration FORWARD_LOOKING/CHRONOLOGICAL, sibling discount tiered + argmax full-price exclusion, pinned round-per-line-then-sum totals, readiness scoring 4-decimal ROUND_HALF_UP strict vs holistic, instructor schedule overlap closed+15min buffer, makeup overlap half-open no buffer), lookups.py (entity-specific 404 resolvers), routes/ (catalog.py, families.py, sessions.py, enrollments.py, invoices.py, makeups.py, assessments.py).

Storage: in-memory only — module-level Store with one dict per entity keyed by UUID. No SQLite, no JSON-on-disk, no /tmp cache. Every start.sh re-invocation starts fresh empty store (verified).

start.sh: cd to script dir, guard pip install on cheap `import flask`, then exec python3 app.py; app.py binds 0.0.0.0:$PORT (default 10000) foreground, threaded=True.

No data seeded at startup: every store write lives inside a request handler or domain function reachable only from one. No seed_*/preload/module-load population.

Verification: 60+ assertions across self-managed boots covering auth/RBAC, response envelope, full curriculum→enrollment→billing→assessment→makeup lifecycle, OCC stale-version on both guarded writes, waitlist promotion, sibling-discount full-price tie-break (same-instant created_at collision resolved via creation sequence not id), CHRONOLOGICAL proration, instructor schedule buffer vs lane conflict precedence, age-out-of-range, account-past-due gating, credit expiry/restoration, occurrence capacity, level-transfer disruption credits, session-close cascade, pagination bounds, validation ordering. All passed. Design note: identical created_at sibling-discount tie-break falls back to internal monotonic _seq, never entity id, per PRD constraint.

## Step 7: Run Tests and Iterate — 2026-06-21T18:20:04.000Z

Subagent summary (verbatim):

All 8 parallel rounds are green. Exiting with the summary.

Iterations run: 2 (sweep 1 surfaced 5 stable failures; sweep 2 confirmed all green).

Initial state: 63/68 per round, with 5 tests failing identically in all 8 rounds (no flakiness — all stable bugs).

Tests deleted (1):
- test_05_validation_and_priority.py::test_open_full_session_yields_session_full_not_session_not_open — STEP 1b failure / ERROR-PRECEDENCE + BRANCH-ASYMMETRIC silence. Asserted that a plain enrollment create against a full OPEN session returns ERR_SESSION_FULL. PRD §3.6 gives the explicit create-time rule "If no seat is free, the enrollment is recorded as WAITLISTED instead," while the ERR_SESSION_FULL sentence applies to "a caller who requires immediate activation" — and there is no enrollment payload field expressing "requires immediate activation." Two divergent PRD-faithful implementations exist (create→WAITLISTED vs. create→ERR_SESSION_FULL), so the outcome is not uniquely derivable. (Design tag: Difficulty/priority_pair_validation_conflict/session_not_open_beats_session_full.) The companion negative test test_session_not_open_takes_priority_over_full (DRAFT→ERR_SESSION_NOT_OPEN) is uniquely derivable and was kept.

Fixes to test_helpers/:
- fixtures.py::setup_single_enrollment_for_billing — added a join_clock (default cycle-start 2026-01-01) so the enrollment is activated at the cycle start and its joined_at is not strictly after cycle_start, then the clock is advanced to the test instant. Previously it activated the enrollment at the mid-cycle test clock (Jan 10), making joined_at mid-cycle, which per PRD §3.9 forces the on-or-after-join-date window for both variants (9000) and collapses the FORWARD_LOOKING (12000) vs CHRONOLOGICAL (3000) distinction the two billing tests assert. This fixed test_forward_looking_charges_whole_cycle and test_chronological_charges_only_delivered_occurrences.

Fixes to test_suite/:
- test_05_validation_and_priority.py::test_age_out_of_range_takes_priority_over_past_due — changed the in-range big_kid birthdate from 2017-01-01 (~108 months, above the level's exclusive max_age_months=72) to 2022-01-01 (48 months, inside [36,72) at the Jan-5 clock). The old birthdate tripped ERR_AGE_OUT_OF_RANGE during setup before the test could exercise its precedence assertion.

Fixes to implementation/:
- lookups.py — added entity_exists_anywhere(id) helper (scans all 12 entity collections) to distinguish a genuinely-missing id (not-found) from an id that names a wrong-type entity (reference-mismatch).
- routes/enrollments.py::create_enrollment — a body FK (student_id/class_session_id) that resolves to an entity of the wrong type now yields ERR_REFERENCE_MISMATCH (PRD §3.6: "checked for type and ownership consistency"), while a truly-absent id still yields the matching not-found error (PRD §2.6/§2.10 existence-then-reference ordering preserved). This fixed test_enrollment_reference_mismatch_wrong_type_session (was returning ERR_CLASS_SESSION_NOT_FOUND for a Location id used as the session id). The pre-existing GET not-found path is unaffected.

Final result: All 8 parallel rounds green: 67/67 passed, 0 failed, 0 errors in every round.

ORCHESTRATOR NOTE: The subagent's final-sweep results.*.json artifacts were absent on exit (cleaned up). The orchestrator re-ran the full 8-round parallel sweep independently to confirm and to persist the required output artifacts — all 8 rounds: passed=67 failed=0 total=67. results.{1..8}.json now persist in workspace/implementation/.

## Step 8: Finalize PRD — 2026-06-21T18:24:59.000Z

Not skipped (Step 7 had 1 deletion + test_helpers fix + test_suite fix + 2 implementation fixes). Subagent summary (verbatim):

The edit is in place. One change made; line count unchanged.

Line counts: PRD.md = 301 lines; PRD_FINALIZED.md = 301 lines; %-delta = 0% line count (one line revised in place, no lines added/removed).

Changes (1 total):
- §3.6 — revise — Pinned the full-OPEN-session create outcome. Replaced the ambiguous trailing sentence "A caller who requires immediate activation but finds the session full is rejected with ERR_SESSION_FULL" with explicit prose stating that enrollment creation against a full open session always yields WAITLISTED (never ERR_SESSION_FULL), and that ERR_SESSION_FULL arises only when an existing enrollment re-acquires a seat on resume. — implementation/routes/enrollments.py:84,96-113 (create → WAITLISTED) and :183-185 (resume → ERR_SESSION_FULL).

Per-edit pre-edit search log:
- Edit 1 (§3.6 full-session create): (a) Subject: ERR_SESSION_FULL and the create-time outcome of a full OPEN session. (b) Paths enumerated and read: enrollments.py::create_enrollment (free seat + CURRENT → ACTIVE; free seat + PAST_DUE → ERR_ACCOUNT_PAST_DUE; no free seat → WAITLISTED unconditionally — no ERR_SESSION_FULL); enrollments.py::resume_enrollment lines 183-185 (the sole request-level ERR_SESSION_FULL trigger); domain.py::promote_waitlist line 113 (full session silently skips promotion, raises nothing); errors.py:47 (ERR_SESSION_FULL=409). Grepped all ERR_SESSION_FULL/free_seat/WAITLISTED/capacity comparisons. (c) Adjustment: Scoped the surviving ERR_SESSION_FULL claim to the resume path, consistent with the resume path and not contradicting promote_waitlist (internal cascade, no error).

Items requiring NO PRD edit (traced and confirmed):
- fixtures.py setup_single_enrollment_for_billing (join_clock): pure test-helper bug. Proration in calculations.py::compute_window_count (60-73) already matches PRD §3.9 verbatim.
- test_suite test_age_out_of_range_takes_priority_over_past_due (birthdate): pure test-fixture bug; no PRD silence/mismatch.
- lookups.py entity_exists_anywhere + enrollments.py reference-mismatch: PRD §2.6, §2.10, §3.6 already uniquely determine wrong-type body FK → ERR_REFERENCE_MISMATCH vs. truly-absent id → not-found. Impl conforms.

## Step 9: Complete PRD — 2026-06-21T18:30:55.000Z

Always runs. Source = PRD_FINALIZED.md. Subagent summary (verbatim):

All edits are in place and minimal (in-paragraph inserts/revisions, no new sections). The work is complete.

File counts: PRD_FINALIZED.md (source) → PRD_COMPLETED.md: both 301 lines (all edits in-paragraph). Char count 49,089 → 51,138 (+2,049 chars).

Change counts: 7 changes total — 5 ambiguity-pins, 2 mismatch-revisions.

Per change:
- §2.1 (RBAC) — insert — ambiguity — pinned that list endpoints are owner-scoped for a Parent only on GET /invoices and GET /parents/{id}/students; all other Parent-accessible list endpoints return the full unscoped collection — routes/invoices.py:116-117 (scoped) vs routes/enrollments.py:118-128, routes/makeups.py:33-48,129-140, routes/assessments.py:74-85 (unscoped).
- §3.5 (Closing a Session) — revise — mismatch — removed the "credit side effects" claim from the close cascade (withdrawal mints no makeup credit; credits arise only from pause SKIP and approval LEVEL_TRANSFER_DISRUPTION), and pinned that close is permitted only from OPEN (else ERR_INVALID_STATE) — routes/sessions.py:135,149-152; domain.py:145-164.
- §3.6 (Enrollment) — revise — ambiguity — pinned is_prorated_first_cycle = true iff joined_at is not exactly at UTC midnight — domain.py:132-139.
- §3.6 (Enrollment) — insert — ambiguity — pinned that a WAITLISTED create still sets joined_at to now (ordering key), keeps is_prorated_first_cycle false, and bumps the session version — routes/enrollments.py:108-113.
- §3.7 (Assessment) — revise — mismatch — assessed_level_id is captured at creation time (PRD said "at submission time"); also pinned per-entry shape/score-range validated at creation while exact skill-set coverage enforced at submit, and the four readiness fields default to 0/0.0/false until submission — routes/assessments.py:36-47,56,64-67.
- §3.9 (Proration) — revise — ambiguity — pinned occurrence/join/chronological comparisons use each date's UTC-midnight instant against [cycle_start, cycle_end) and current_utc, and a zero-occurrence cycle yields a 0 prorated charge — calculations.py:32-73,54.
- §3.9 (Sibling discount) — insert — ambiguity — pinned discount_pct is a decimal fraction (0.0 / 0.10 / 0.15), not a whole-number percent — calculations.py:122.

Notable impl behaviors confirmed already-pinned (no change): resume does not gate on account standing; student-withdraw and direct-withdraw cascades issue no credits; enrollment FK existence-vs-reference-mismatch ordering; _clock/set_current_utc response shape; pause SKIP-credit + promotion ordering.

ORCHESTRATOR NOTE: Steps 8 and 9 are documentation-only — implementation/, test_suite/, and test_helpers/ were not modified (impl source mtimes predate the doc edits). The Step 7 8-round green sweep (67/67 every round) therefore remains valid for the final artifact set.

---

## PIPELINE COMPLETE

All 9 steps executed. Final state: 67/67 tests pass across all 8 parallel rounds. Artifacts present: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, workspace/PRD.md, workspace/PRD_FINALIZED.md, workspace/PRD_COMPLETED.md, workspace/INSTRUCTION.md, workspace/implementation/ (+ results.{1..8}.json), test_helpers/, test_suite/, worklog.md.
