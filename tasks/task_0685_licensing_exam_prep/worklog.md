# Worklog — task_0685_licensing_exam_prep

## Step 1: Create Task Directory — 2026-06-28T04:38:03.128Z

Task directory `tasks/task_0685_licensing_exam_prep/` and its `workspace/` subdir pre-existed (created by the parallel-run harness). Per execution directives, the Step 1 directory-scan was SKIPPED; the folder name is used verbatim as {task_dir}. No index computation or rename performed.

## Step 2: Generate Scaffold — 2026-06-28T05:03:20.220Z

Generated three scaffold artifacts for task_0685_licensing_exam_prep at Expert difficulty, all passing scaffold_lint.py clean (471 calls scanned, 0 violations, all FK reverse-reachability satisfied).

Entities (15): LicenseProgram, SubscriptionPlan, CEBundle, QuestionItem (immutable, common_fields:false), Cohort, CohortSession, Learner, Enrollment (aggregate root), Installment, StudyPlanDomain, PracticeSession, MockExam, PassGuaranteeClaim, CECreditAward, CohortMembership. Topology hybrid; 49 endpoints (mostly mandatory FK/CRUD reads), 22 error codes, 4 roles (Learner entity_backed; ContentAdmin/ExamProctor/PlatformOps opaque).

State machines (6, non-linear): Enrollment branches ACTIVE→{PASSED, FAILED, WITHDRAWN} with FAILED→REFUNDED; PassGuaranteeClaim branches SUBMITTED→{APPROVED, DENIED}; Cohort cycles OPEN↔FULL (compound, seats-driven); plus LicenseProgram, Installment, CohortMembership.

Key calculations (10, 3 variants): dual-variant readiness_score (conservative latest-mock vs projected all-mock-avg); financing_schedule (down-payment + remainder-to-last-installment, paid-in-full variant); guarantee_refund (pinned round-per-installment-then-sum, mode-b); domain_mastery_update (EWMA, α=0.40); pass_guarantee_eligibility (200 questions / 2 mocks / readiness≥75 inclusive); ce_credit_accrual (cumulative, conserves bundle total); two distinct interval-overlap rules (membership_window_overlap half-open vs session_buffer_overlap closed+30min); mock_overage; financing_ledger. One OCC concurrency rule on Enrollment.version (financing-restructure supersede, 412). All numeric asserts computed in Python and pinned as literals.

Design instances: 18 difficulty (9 rules × 2) + 51 corner (43 active + 8 excluded_because stubs). All 22 error codes covered; file-split contract satisfied.

## Step 3: Copy Shared Files — 2026-06-28T05:03:24.373Z

Copied ./INSTRUCTION.md → tasks/task_0685_licensing_exam_prep/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-06-28T05:08:02.439Z

Generated PRD for Licensing Exam Prep API (workspace/PRD.md, 279 lines). 5 top-level sections (Introduction, Global Specifications, Business Logic & Workflows, Endpoint Definitions, Error Code Catalogue) + 18 subsections.

Hard Contracts all PASS: (1) Field-Name Coverage — 65/65 required fields present, 0 missing. (2) Rule Coverage — all 7 validation priorities sequenced; 1 OCC concurrency rule (restructure-financing → ERR_STALE_ENROLLMENT_VERSION 412, framed as stale-data); all state-machine transitions w/ cascades; all 11 calculations in precise prose; all 22 errors mentioned; cascades expressed. (3) §3 Path Purity — 321 tokens scanned, 0 violations. §4 endpoint table 4 cols × 50 endpoints; §5 error table 2 cols × 22 errors. Withheld design files not opened; no sibling task consulted.

## Steps 5 & 6: Unit Tests + Implementation — already-complete (verified on resume) — 2026-06-28T05:30:00.000Z

Resume sanity-check only (NOT regenerated). The external SIGTERM beat the worklog writes for Steps 5/6, but both artifact sets are fully populated on disk and coherent:
- Step 5: test_helpers/ (9 files: __init__, api_client, api_errors, assertions, constants, factories, fixtures, test_users, types) + test_suite/ (conftest.py + 5 test_*.py with 79 test functions: 10+12+20+20+17). `python3 -m py_compile` clean.
- Step 6: workspace/implementation/ (app.py, start.sh, clock.py, db.py, errors.py, middleware.py, response.py, requirements.txt, routes/ [9 files], services/ [5 files]). `python3 -m py_compile` clean. start.sh = foreground `exec python3 app.py` with conditional pip install.
No file truncated mid-write; no regeneration performed. Proceeding to Step 7.

## Step 7: Run Tests and Iterate — 2026-06-28T05:40:59.533Z

All 8 rounds pass with 78/78 (one test deleted, was 79). The total is consistent across all rounds with zero failures and zero errors. The fixes are stable across all parallel rounds.

**Iterations run:** 2 sweeps (initial diagnostic sweep + post-fix verification sweep).

**Final sweep result:** All 8 rounds passed==total: Round 1–8 each 78/78 (0 failed, 0 errors). Total dropped from 79→78 due to one deletion.

**Tests deleted (1):**
- `test_publish_program_bad_weights_rejected` (test_04_catalog_and_ce.py) — STEP 1b non-unique-derivability. PRD §3.1 states the creation contract for `domain_weights` as "the weights sum to exactly 1.00," which a faithful implementer enforces at create-time as `ERR_INVALID_REQUEST` (per §2.5 well-formedness priority and SCAFFOLD line 72 `constraints: "sum(weight) == 1.00"`). That makes the publish-time `ERR_BLUEPRINT_WEIGHTS_INVALID` gate unreachable — the test cannot construct its precondition (a creatable program with weights summing to 0.90). Two divergent PRD-faithful implementations exist (validate-at-create vs validate-only-at-publish), so the assertion is not uniquely determined. Drove from scaffold rule: corner `state_machines/publish_program_bad_weights_rejected`.

**Fixes applied to test_helpers/ (1 file):**
- `fixtures.py` — `setup_active_enrollment`: added a `pay_in_full=False` option that pays every DUE installment after activation. The shared helper previously left the enrollment's installment unpaid (balance outstanding), which is inconsistent with the PRD §3.5 PASS precondition ("the enrollment owe nothing"). Default stays False so withdraw/void scenarios keep observing the unpaid installment.

**Fixes applied to test_suite/ (2 files):**
- `test_03_enrollment_lifecycle_and_cascades.py` — the 3 PASS-cascade tests (`test_certify_pass_moves_to_passed`, `test_pass_certification_cascades_membership_drop_and_cohort_reopen`, `test_pass_certification_drops_all_joined_memberships`) now call `setup_active_enrollment(..., pay_in_full=True)` so the balance is 0 before certifying PASS (PRD §3.5 precondition).
- `test_02_financing_and_refunds.py` — STEP 1c partial-coverage split on the two withdraw tests. Removed the `financing_balance_cents == 0` assertions (branch-asymmetric side effect: §3.6 withdraw says only "void all DUE installments," omitting the balance-zeroing that §3.5 refund explicitly spells out; the §3.2 ledger formula `balance = total_due − paid` — pinned at 96000 by the passing restructure-ledger test — gives 96000, not 0). Kept the PRD-covered assertions (status==WITHDRAWN, `financing_paid_cents` == sum of PAID installments) and added a §3.6-covered check that no installment remains DUE after withdraw.

**Fixes applied to implementation/ (2 files):**
- `routes/enrollments.py` — `certify_exam`: reordered so the `exam_outcome != PENDING` check (`ERR_EXAM_ALREADY_CERTIFIED`) precedes the `status != ACTIVE` check (`ERR_INVALID_STATE`). PRD §3.5 verbatim mandates that a second certification attempt returns `ERR_EXAM_ALREADY_CERTIFIED`; previously a repeat certify on a FAILED enrollment hit the generic state error first.
- `routes/claims.py` — `decide_claim` MONEY_BACK/REFUNDED cascade: explicitly set `financing_balance_cents = 0` after voiding DUE installments, per PRD §3.5 verbatim "voids every remaining DUE installment (each moves to VOID, bringing financing_balance_cents to zero)."

All storage remains in-memory dicts; no seeding/persistence introduced.

## Step 8: Finalize PRD — 2026-06-28T05:45:20.276Z

Produced workspace/PRD_FINALIZED.md (minimal patch of PRD.md scoped to the <step_7_diff>).

**PRD.md vs PRD_FINALIZED.md**
- Line count: 279 → 279 (0.00% by lines — both edits expanded existing single-line markdown paragraphs in place).
- Size delta: +919 bytes (+2.15%); +134 words (+2.19%).

**Changes (one per edit)**
- §3.1 — insert — Pinned that the `domain_weights` well-formedness constraints (non-empty array; each entry an object with a non-empty `domain_code`; `weight` a number strictly > 0; weights sum to exactly 1.00) are enforced at create time as `ERR_INVALID_REQUEST` — `routes/license_programs.py:17-37, 50`.
- §3.5 — insert — Pinned that the already-certified check (`exam_outcome != PENDING` → `ERR_EXAM_ALREADY_CERTIFIED`) is evaluated before the `ACTIVE`-state check, so a repeat certify on a `FAILED`/non-`ACTIVE` enrollment surfaces `ERR_EXAM_ALREADY_CERTIFIED`, with `ERR_INVALID_STATE` reachable only when `exam_outcome` is still `PENDING` but status is not `ACTIVE` — `routes/enrollments.py:233-236`.

**Step_7_diff items that needed NO PRD edit (and why)**
- Deleted test `test_publish_program_bad_weights_rejected` — covered by Edit A (the create-time `ERR_INVALID_REQUEST` enforcement is what makes the publish-time `ERR_BLUEPRINT_WEIGHTS_INVALID` sum-gate unreachable). The publish gate paragraph (§3.1) was left verbatim since the impl still keeps it.
- `fixtures.py setup_active_enrollment(pay_in_full=...)` — pure fixture bug; PRD §3.5 already pins the PASS "owe nothing" balance precondition.
- test_03 PASS-cascade tests now `pay_in_full=True` — consequence of the fixture fix; already PRD-determined.
- test_02 withdraw tests dropped `financing_balance_cents == 0` assertions — pure test-laxing; PRD §3.6 already correctly omits balance-zeroing on withdraw, and the §3.2 ledger formula already uniquely fixes balance = total_due − paid (96000). No silence to pin.
- `claims.py decide_claim` MONEY_BACK setting `financing_balance_cents = 0` — PRD §3.5 already verbatim says the REFUNDED cascade voids DUE installments "bringing `financing_balance_cents` to zero." Impl fix made code match existing PRD; no edit needed.

Per-edit pre-edit NO-NEW-MISMATCH search performed for both edits (subjects: domain_weights validation lifecycle; certify-exam error ordering); enumerated all create/publish/read paths for domain_weights and both ERR_EXAM_ALREADY_CERTIFIED sites (certify_exam + withdraw_enrollment) plus ERR_INVALID_STATE reachability; wording scoped to "at create time" / "before the ACTIVE requirement" to avoid contradicting the still-present publish gate and the §3.6 withdraw ordering.

## Step 9: Complete PRD — 2026-06-28T05:52:14.166Z

Produced workspace/PRD_COMPLETED.md via full PRD-vs-implementation/ completeness scan (started from PRD_FINALIZED.md).

**Line counts:** PRD_FINALIZED.md = 279 lines / 43,573 chars; PRD_COMPLETED.md = 279 lines / 47,001 chars (char delta +3,416 reported by subagent; on-disk +3,428). No new lines, paragraphs, or sections — every change is an in-paragraph insert or revision.

**Counts:** 9 ambiguity-pins, 3 mismatch-revisions (12 changed passages total).

**Changes (one per edited passage):**
- §3.1 License program — insert — ambiguity — duplicate `license_code` rejected with `ERR_INVALID_REQUEST`; `passing_scaled_score` pinned as an integer — `routes/license_programs.py:48-54`
- §3.2 Learner — insert — ambiguity — duplicate `email` rejected with `ERR_INVALID_REQUEST` — `routes/learners.py:24-26`
- §3.2 Enrollment create — insert — ambiguity — initial `financing_paid_cents`=0, `financing_balance_cents`=price, `guarantee_eligible` false, counters/scores at 0 — `routes/enrollments.py:61-77`
- §3.2 Enrollment create (CE referential) — revise — mismatch — supplied `ce_bundle_id` is existence- and referential-checked regardless of `includes_ce`, then discarded if plan has no CE — `routes/enrollments.py:46-59`
- §3.2 Restructure — insert — ambiguity — PAID installments preserved, `financed` flag honored (non-financed rebuilt as single installment ignoring `new_financing_months`), `financing_total_due_cents` unchanged, ledger recomputed — `routes/enrollments.py:181-192` + `services/enrollment_service.py:50-76`
- §3.4 Analytics view — revise — mismatch — analytics returns the enrollment record only (scores, counters, financing); per-domain mastery NOT embedded, read via `/domains` — `routes/enrollments.py:95-102`
- §3.5 Claim filing — insert — ambiguity — filing against a non-`FAILED` enrollment rejected with `ERR_INVALID_STATE`; Learner list/fetch scoped to owned enrollments (`ERR_NOT_RESOURCE_OWNER` on others) — `routes/claims.py:28-29, 41-68`
- §3.5 Claim decide — insert — ambiguity — claim must be `SUBMITTED` (`ERR_INVALID_STATE`), checked before the enrollment-`FAILED` check — `routes/claims.py:79-84`
- §3.7 CE award — insert — ambiguity — award against an enrollment with no linked `ce_bundle_id` rejected with `ERR_REFERENCE_INCOMPATIBLE` — `routes/enrollments.py:433-436`
- §3.8 Cohort close — revise — mismatch — close permitted from `OPEN` **or** `FULL`; other statuses → `ERR_INVALID_STATE` — `routes/cohorts.py:85-86`
- §3.8 Cohort join — revise — mismatch — guard order is referential → window-conflict → capacity; the `end>start` well-formedness precedes them — `routes/cohorts.py:160-178`
- §3.8 Membership drop — insert — ambiguity — dropping a non-`JOINED` membership rejected with `ERR_INVALID_STATE`; cross-cohort list/fetch scoped to owner for Learner — `routes/cohorts.py:217-218, 228-255`
- §3.9 Deterministic time — insert — ambiguity — `to_iso8601` must be well-formed (`ERR_INVALID_REQUEST`); logical clock governs only `completed_at`/comparisons while `created_at`/`updated_at`/`api_request_timestamp` use the wall clock; set-clock returns 200 with empty data — `clock_route.py:19-26`, `db.py:11-18`, `response.py:20`

Tests used only as auxiliary cross-reference; implementation was sole alignment authority.

---

PIPELINE COMPLETE. Final state: all 8 stability rounds 78/78 (0 failed, 0 errors); PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md all on disk; results.1.json–results.8.json present.
