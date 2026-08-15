# Worklog — task_1674_dual_enrollment_concurrent_credit

## Step 1: Create Task Directory — 2026-08-14T06:41:58.000Z

Task directory `tasks/task_1674_dual_enrollment_concurrent_credit/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher (Step 1 treated as DONE per invocation contract). Verified presence; no index scan performed, no other task directory touched.

## Step 2: Generate Scaffold — 2026-08-14T08:09:52.000Z

Scaffold generation complete. All three artifacts written to `/home/ubuntu/github/CodingPRD/tasks/task_1674_dual_enrollment_concurrent_credit/` and the mandatory `scaffold_lint.py` run is clean.

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (1157 calls scanned across 18 §1.8 + 56 active §1.9 instances; 69 endpoints, 15 entities.)

**Files written**
- `SCAFFOLD.yaml` — 2355 lines (§1.0–§1.7 only; no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 848 lines (single top key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 1507 lines (single top key `scaffold_corner_design`)

**Entity set (15, flat topology, FK-linked):** HighSchool, AcademicTerm (dual-calendar: COLLEGE/HIGH_SCHOOL with add/drop/withdraw deadlines), Student (computed college_gpa/hs_gpa), Course, Prerequisite (self-referential DAG edge, cycle-rejecting), PlacementRecord (immutable, 730-day expiry), Instructor, CredentialApplication, CourseOffering (seat counters + OCC version), Enrollment (carries waitlist_seq, grade, withdrawn_at), TranscriptEntry (per-institution), FundingAgreement (state/district/family waterfall config), Invoice (status × refund_status independent axes), Payment (immutable event), ArticulationAgreement (closed-interval effective windows).

**State machines (9):** Enrollment (cyclic REGISTERED→WITHDRAWN→REGISTERED reinstatement + WAITLISTED branches + promotion), CredentialApplication (revision loop SUBMITTED→UNDER_REVIEW→NEEDS_REVISION→SUBMITTED), CourseOffering (DRAFT→OPEN→IN_SESSION→GRADING→FINALIZED + CANCELLED cascade), Invoice, TranscriptEntry, AcademicTerm, HighSchool, Student, Course. OCC concurrency rules on confirm and reinstate via `expected_offering_version` (ERR_STALE_VERSION 412).

**Calculation rules (10):** seat_availability, waitlist_promotion (waitlist_seq ordering, no id/random tie-breaks), effective_deadline (min of two calendars, inclusive), refund_percentage (100/50/0 with the cross-calendar mismatch compensation window), tuition_allocation (3-bucket waterfall gated on funding_model × delivery_mode), refund_settlement (dual-variant estimate-vs-settled with pinned per-payer rounding order), gpa_recompute (dual-variant 4.0 vs weighted 5.0 scales, W excluded vs included), prerequisite_satisfaction (DAG + grade threshold), placement_recency (latest non-expired), transfer_credit_evaluation (articulated vs native hours).

**§1.8: 18 instances** (exactly 2 per rule). Highlights: GPA divergence 3.429 vs 4.500 on identical grades; refund estimate 60000 vs settled 15000 on partial payment; rounding-order instance where pinned family remainder is 6110 vs naive 6111; drop boundary at the exact deadline second; cancel depth-3 cascade vs drop→promotion→invoice depth-3 cascade; state×referential and temporal×referential priority conflicts; seat-count and cent conservation invariants. All formula-derived asserts were pre-computed with Python (round_half_up verified literally).

**§1.9: 65 instances** (56 active + 9 `excluded_because` stubs) across all nine guide sections — entities, state_machines, calculations, validations, endpoints, errors, rbac (incl. segregation-of-duties self-approval and entity-backed ownership), cross_cutting_layers (both OCC rules, derived-field reconciliation), consistency_model. Every one of the 41 error codes is triggered by at least one instance or stub.

Additional audits passed: zero unbound `${var}` placeholders, no duplicate instance names across the union, all `grounds:` references resolve into §1.1–§1.7, no forbidden concurrency vocabulary, clock default 2026-08-01T00:00:00Z declared on the `/_clock/set_current_utc` endpoint.

## Step 3: Copy Shared Files — 2026-08-14T08:11:04.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1674_dual_enrollment_concurrent_credit/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-14T08:21:06.000Z

Note: the Step 4 subagent's first run exited prematurely before writing PRD.md (only its inventory preamble was returned). The orchestrator resumed the same agent via SendMessage; on resume it wrote the PRD and completed its audits. Final summary (verbatim):

## Summary

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_1674_dual_enrollment_concurrent_credit/workspace/PRD.md` — 312 lines.

### Section structure
- **§1 Introduction** (2 paragraphs — problem framing + system scope)
- **§2 Global Specifications** — 10 subsections: 2.1 RBAC (headers, 7 roles incl. `Any` marker, identity prose for all six working roles, segregation of duties), 2.2 Response Structure (emitted byte-verbatim from `section-2.2-response-structure.md`), 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending, `meta` fields), 2.4 Two-Calendar Discipline (effective deadlines, term date ordering, half-open term overlap), 2.5 Seat Ledger invariant, 2.6 Common Resource Properties (with the three `common_fields: false` entities named), 2.7 Money/Percent/Rounding, 2.8 OCC (both rules), 2.9 Nested Retrieval (left-to-right), 2.10 Validation Ordering (priorities 1–16)
- **§3 Business Logic** — 10 subsections organized by lifecycle/domain: 3.1 catalog/schools/terms, 3.2 prerequisites & placement, 3.3 credentialing, 3.4 section stand-up, 3.5 enrollment lifecycle, 3.6 waitlist promotion, 3.7 tuition/refund/invoice ledger, 3.8 grading/finalization/transcript, 3.9 articulation/transfer, 3.10 logical clock
- **§4 Endpoint Definitions** — 4-column table, all 48 endpoints
- **§5 Error Code Catalogue** — 2-column table, all 36 scaffold error IDs

### Scaffold → prose coverage
Translated into prose: all 15 entities (every field named in backticks), 9 state machines (every from→to pair, preconditions with error IDs, side effects incl. cascades), all 10 calculations (seat_availability, waitlist_promotion, effective_deadline, refund_percentage, tuition_allocation waterfall, refund_settlement estimate/settled variants with pinned rounding, gpa_recompute dual scale, prerequisite_satisfaction DAG rules, placement_recency 730-day expiry, transfer_credit_evaluation dual readings), all 22 validations with priority ordering, both OCC rules (`expected_offering_version` / `ERR_STALE_VERSION` / 412 on confirm and reinstate), and all 36 error IDs surfaced in §2/§3 narrative. No pseudocode — all formulas rendered as natural language.

### Zero-Silence self-audit
- **Contract 1 (Field-Name Coverage):** 99 required, 99 present, 0 missing — PASS. (Four gaps found and repaired during audit: `date_ordering`, `uniqueness`, `funding_agreement_id`, `invoice_id`, `eligible`.)
- **Contract 2 (Rule Coverage):** state transitions (all pairs named), calculations (all 10 with full inputs/outputs), OCC (both rules with endpoint+field+error+status), validation error IDs (41/41 in prose), side effects and cascades (offering-cancel cascade, close-registration waitlist expiry, waitlist promotion double version-bump, posting GPA recompute) — PASS.
- **Contract 3 (§3 Path Purity):** 558 backtick tokens scanned in §3, 0 path tokens, 0 bare HTTP methods, 0 method+path combos — PASS.
- §2.2 emitted verbatim (all four sentinels byte-identical).

No scaffold rule could not be expressed; zero-silence confirmed.

## Step 5: Generate Unit Tests — 2026-08-14T09:32:02.000Z

Done. All Stage 1 and Stage 2 output is generated, verified, and collects cleanly under pytest.

## Summary

### Files written

`test_helpers/` (1,849 lines):
- `__init__.py` (37) — barrel export of framework generics + PRD-specific helpers
- `types.py` (321) — status enums, role enum, 15 entity TypedDicts (append-only `Prerequisite`/`PlacementRecord`/`Payment` correctly omit `updated_at`/`version` per PRD 2.6)
- `api_client.py` (287) — `ApiClient(GenericApiClient)` with one method per endpoint (53 methods, all `/dual-credit` paths + `_clock/set_current_utc`)
- `api_errors.py` (96) — all 41 `ApiErrorId`s + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` (228) — per-entity assertions, `assert_seat_conservation`, `assert_invoice_conservation`, `assert_same_instant`
- `factories.py` (143) — 14 payload factories, input fields only
- `constants.py` (52) — placement validity 730d, refund pcts, GPA scales, standard calendar/funding presets
- `test_users.py` (55) — `TEST_USERS` + per-instance builders; `make_instructor_headers(instructor_id)` for the entity-backed role; `NO_AUTH_HEADERS`
- `fixtures.py` (630) — composite fixtures: `setup_base`, `register_student`/`register_and_confirm`, OCC-aware `confirm_enrollment`/`reinstate_enrollment`, `move_offering_to_grading`, `complete_enrollment_with_grade`, `setup_graded_scenario`, `setup_dual_course_posted_scenario`, `setup_mixed_enrollment_scenario`, `setup_delivery_mode_pair`, `setup_mismatch_withdraw_scenario`

`test_suite/` (3,162 lines): `conftest.py` (45) + 16 test files (`test_01`…`test_16`), 92 tests total; `pytest --collect-only` passes (92 collected, 0 errors).

### Per-queue test counts
- **Queue A (§1.8 difficulty):** 36 tests — all 18 instances × 2 tests each
- **Queue B (§1.9 corner):** 56 tests — all 56 non-stub instances × 1 test each

### Skipped instances
**0 skipped.** Every non-stub instance passed the PRD-first two-condition filter (this PRD's prose pins all referenced rules, including the §2.10 priority order and the refund/GPA formulas). The 9 `excluded_because:` stubs (6 errors + 1 validations + 2 cross_cutting_layers) were not translated, as required; all 9 `difficulty_instance` cross-references resolve to real §1.8 instances.

Three assertion-level adjudications were made inside emitted tests (instances still tested; underivable sub-assertions trimmed):
1. `create_high_school_applies_default_status` — omitted the recipe's `version == 1` assertion (PRD 2.6 states version "increments by 1 on every mutation" but never pins the initial value).
2. `duplicate_and_invalid_prerequisite_edges_rejected` — the duplicate edge is re-posted with the *same* `min_grade` (C) instead of the recipe's B, so it is an "exact duplicate edge" under every reading of PRD 3.2.
3. `enrollment_withdraw_reinstate_cycle` — did not assert the new invoice's `refund_pct == null` (PRD never states a fresh invoice's `refund_pct` value); asserted `status == ISSUED` / `refund_status == NONE` instead, which PRD 3.7 states verbatim.

### Stage 2 tag-audit result
**PASS.** All 92 test docstrings end with exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line, copied verbatim from the YAMLs and resolving to a real non-stub instance. No untagged tests, no dual-tagged tests, no stub-pointing tags, no `skip`/`skipif`/`xfail` markers, no "scaffold" references in generated code. Separately, all 184 PRD quotations in docstrings were machine-verified to survive literal (whitespace-normalized) grep of `workspace/PRD.md`.

## Step 6: Generate Implementation — 2026-08-14T09:32:02.000Z

Done. All verification suites pass (167 checks across 4 smoke suites; the single flagged item was my own test's wrong expectation — approving an already-APPROVED application correctly returns 409 `ERR_CREDENTIAL_APPLICATION_INVALID_STATE`).

## Summary

**Files written** — all under `/home/ubuntu/github/CodingPRD/tasks/task_1674_dual_enrollment_concurrent_credit/workspace/implementation/`:

| File | Lines | Purpose |
|---|---|---|
| `start.sh` | 10 | Guarded pip install + `exec python3 app.py` |
| `requirements.txt` | 1 | flask>=3.0 |
| `app.py` | 85 | Flask app, blueprint registration (`url_prefix="/dual-credit"`), ApiError/404/405/generic handlers |
| `db.py` | 33 | In-memory dict store (15 collections), insertion seq — empty on every boot |
| `util.py` | 106 | IDs, request IDs, wall-clock timestamps (3-frac-digit ISO), `LogicalClock` (default `2026-08-01T00:00:00Z`, echoes raw set string), `parse_dt`/`fmt_dt`, `rhu_cents` (Decimal ROUND_HALF_UP) |
| `errors.py` | 65 | `ApiError` + all 40 error IDs with exact HTTP statuses |
| `response.py` | 46 | Envelope: `meta{api_request_id, api_request_timestamp}`, `response_type`, `data`; list meta adds `limit`/`offset`/`total_count`/`has_more` |
| `middleware.py` | 55 | `X-User-ID`/`X-User-Role` extraction; 6 declared roles; `Any` = any declared role |
| `validate.py` | 142 | Shape validators (str/int/number/enum/datetime), pagination (`limit` 1–100, `offset` ≥ 0 → `ERR_INVALID_PAGINATION_PARAMETERS`), path/body-FK existence |
| `services/core.py` | 42 | `new_record` (id/created_at/updated_at/version; Prerequisite, PlacementRecord, Payment are lightweight), `touch`, serialization, created_at-ASC sort |
| `services/calculations.py` | 445 | All 10 calculation rules |
| `services/transitions.py` | 125 | Multi-entity cascades + finalize posting |
| `routes/` (16 modules) | ~1430 | All 46 endpoints |

**10 calculation rules** — grouped in `services/calculations.py`, numbered to match the scaffold: `seat_availability` (computed REGISTERED count, never a stored counter), `waitlist_promotion` (min `waitlist_seq`, only when offering OPEN), `effective_deadline` (min across both calendars, inclusive bounds), `refund_percentage` (100 drop; 50 iff `now <= college_term.drop_deadline`), `tuition_allocation` (state/district/family waterfall, `create_invoice`), `refund_settlement` (`apply_refund_estimate` billed-variant + `settle_refund` paid-variant with pinned family remainder), `gpa_recompute` (college 4.0 with W excluded; HS 5.0 with W=0 in the denominator; 3-dp half-up), `prerequisite_satisfaction` (DAG self/dup/cycle via DFS + POSTED COLLEGE entry check), `placement_recency` (expiry-invisible records, latest by taken_at/created_at), `transfer_credit_evaluation` (closed active window, articulated vs native readings, 1-dp).

**9 state machines** — single-resource transitions inline in their route modules (HighSchool, AcademicTerm, Student, Course, CredentialApplication, TranscriptEntry, Invoice payment/refund transitions, Enrollment confirm/drop/withdraw/reinstate/cancel-waitlist); multi-entity side-effect bundles in `services/transitions.py`: `close_registration_cascade` (WAITLISTED→EXPIRED via either term), `cancel_offering_cascade` (conditional PENDING/WAITLISTED→CANCELLED, REGISTERED→DROPPED + invoice voided at pct 100), `finalize_offering_posting` (COLLEGE+HS entries for COMPLETED; WITHDRAWN gets COLLEGE W always, HS W only when `withdrawn_at > hs_term.drop_deadline`), `release_seat_and_promote`.

**Two OCC rules** — `POST /enrollments/{id}/confirm` and `/reinstate` both require integer `expected_offering_version` in the body (missing/invalid → `ERR_VALIDATION` at priority 4), checked at priority 6 after the enrollment's own state check and before the offering-state check; mismatch → `ERR_STALE_VERSION` 412. Offering `version` bumps exactly on seat moves (confirm-register, drop, withdraw, reinstate, promotion — so a drop that promotes bumps it twice; waitlist outcome does not bump).

**start.sh** — confirmed: binds `0.0.0.0:$PORT` (verified via `ss`: `0.0.0.0:17941 LISTEN`), runs in the foreground via `exec`, and the pip install is guarded (`python3 -c "import flask"`) so per-test reboots are no-ops. Verified `bash start.sh` boots cleanly and that state created before a kill is gone after reboot — pure in-memory dicts, no SQLite/JSON/tmp persistence, zero seeding at startup.

## Step 7: Test-Fix Iteration — 2026-08-14T09:40:00.000Z

First 8-round parallel sweep: 87/92 in every round, same 5 deterministic failures (no flakiness). All five adjudicated as STEP 2 test-artifact bugs; the implementation was PRD-correct in every case. Zero tests deleted; zero implementation changes.

**Fixes applied**
- `test_suite/test_10_difficulty_cycles.py` — two call sites used `self._setup_withdrawn_cycle()` for a module-level function (AttributeError). Changed to plain `_setup_withdrawn_cycle()`.
- `test_suite/test_03_calculations_gpa_and_placement.py` (`test_gpa_w_included_hs_excluded_college`) — setup called `register_student(ctx)` (which already creates a PENDING_VERIFICATION enrollment on `ctx["offering"]`) and then `create_enrollment` again for the same (student, offering), tripping PRD 3.5's verbatim `ERR_DUPLICATE_ENROLLMENT` rule. Reused the fixture-created enrollment for `enr_a`.
- `test_helpers/fixtures.py` (`setup_dual_course_posted_scenario`) — stored pre-post transcript-entry snapshots in ctx despite the docstring promising all four entries POSTED; now stores the POST responses (status POSTED).
- `test_suite/test_02_state_machine_guards.py` (`test_credential_approve_from_submitted_rejected`) — asserted `ERR_CREDENTIAL_APPLICATION_INVALID_STATE`, but with `reviewed_by` null the caller fails the priority-3 ownership rule, which PRD 2.10 orders strictly before the priority-6 state check ("when several rules are violated the same one always surfaces first"); PRD 2.1/3.3 name `ERR_NOT_RESOURCE_OWNER` for exactly this violation. Corrected the expected error to `ERR_NOT_RESOURCE_OWNER` and added a state-unchanged assertion.

Second 8-round parallel sweep: **92/92 in all 8 rounds** — clean.

### Step 7 exit summary (verbatim from the fix subagent) — recorded 2026-08-14T09:49:11.000Z

All 8 rounds of the final sweep pass 92/92. The task is complete.

## Summary

**Iterations run:** 2 (first sweep: 87/92 in all 8 rounds, same 5 deterministic failures, zero flakiness; second sweep after fixes: **92/92 in all 8 rounds**).

**Tests deleted:** 0 — every failure traced to a test-artifact bug; no PRD-silence or unique-derivability deletions were needed.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1674_dual_enrollment_concurrent_credit/test_suite/test_10_difficulty_cycles.py` — `test_withdraw_then_reinstate_closes_the_cycle` and `test_reinstate_issues_a_new_invoice_and_preserves_the_old_audit` called `self._setup_withdrawn_cycle()` on a module-level function (AttributeError). Changed both call sites to the plain function call.
- `/home/ubuntu/github/CodingPRD/tasks/task_1674_dual_enrollment_concurrent_credit/test_suite/test_03_calculations_gpa_and_placement.py` — `test_gpa_w_included_hs_excluded_college` setup violated PRD 3.5's verbatim duplicate-enrollment rule: `register_student(ctx)` already creates a PENDING_VERIFICATION enrollment on `ctx["offering"]`, and the test then posted a second `create_enrollment` for the same (student, offering) → correct `ERR_DUPLICATE_ENROLLMENT` 409. Fixed the setup to reuse the fixture-created enrollment for `enr_a`.
- `/home/ubuntu/github/CodingPRD/tasks/task_1674_dual_enrollment_concurrent_credit/test_suite/test_02_state_machine_guards.py` — `test_credential_approve_from_submitted_rejected` asserted `ERR_CREDENTIAL_APPLICATION_INVALID_STATE`, but with `reviewed_by` null the reviewer caller fails the priority-3 ownership rule, which PRD §2.10 orders strictly before the priority-6 state precondition ("when several rules are violated the same one always surfaces first"), and PRD §2.1/§3.3 name `ERR_NOT_RESOURCE_OWNER` for exactly this violation. Corrected the expected error to `ERR_NOT_RESOURCE_OWNER` (exact-error assertion preserved, not downgraded), added a state-unchanged assertion, and added the missing `get_credential_application` import.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1674_dual_enrollment_concurrent_credit/test_helpers/fixtures.py` — `setup_dual_course_posted_scenario` stored pre-post transcript-entry snapshots in `ctx` despite its docstring promising "all four transcript entries are POSTED"; the fixture now stores the POST responses so `math_entry_college` etc. carry `status == "POSTED"`.

**Fixes applied to `implementation/`:** none — the implementation was PRD-faithful in all five failures (ownership-before-state priority per §2.10, duplicate-enrollment guard per §3.5, and entry status transitions per §3.8 all behaved correctly).

## Step 8: Finalize PRD — 2026-08-14T10:01:23.000Z

Step 7 had 0 deletions but 3 `test_suite/` fixes + 1 `test_helpers/` fix, so the skip condition did not apply; the finalizer ran. Verbatim summary:

Done. `PRD_FINALIZED.md` is written with exactly one targeted edit.

## Summary

**Line counts / delta:** PRD.md 312 lines (48,110 chars) → PRD_FINALIZED.md 312 lines (48,503 chars); +393 chars, **+0.817%**. Single-paragraph diff; no new sections.

**Changes (one edit total):**
- **§3.3 (Instructor Credentialing)** — *insert* — added one sentence after the review-owner/segregation sentence: the ownership and segregation checks on approve/deny/request-revision apply regardless of the application's current `status` and, per §2.10's ordering, surface ahead of the state-machine precondition; since a `SUBMITTED` application's `reviewed_by` is null and equals no caller, a decision call against a `SUBMITTED` application fails with `ERR_NOT_RESOURCE_OWNER` — `workspace/implementation/routes/credential_applications.py:95-106` (`_decision`: ownership L95-96 → SoD L97-101 → state L102-106, unconditional on status).

**Step 7 items needing no edit (verified, not assumed):**
- `test_10` AttributeError fix — pure test-code bug (module-level helper called via `self`); no PRD implication.
- `test_03` duplicate-enrollment fixture fix — PRD §3.5 already verbatim-pins `ERR_DUPLICATE_ENROLLMENT` for same (student, offering) in `PENDING_VERIFICATION`/`REGISTERED`/`WAITLISTED`; fixture violated the rule.
- `fixtures.py` POST-snapshot fix — PRD §2.2's blanket rule ("operations that create or modify a resource will return the created or updated resource object") plus §4's 200-for-state-transitions already pin that `post_entry` returns 200 with the updated entry (`status` `POSTED`); §3.8 does not "otherwise note". Confirmed against `implementation/routes/transcript_entries.py:37-49` and `response.py:14` (`success_object` default 200). PRD not silent; fixture bug only.

**Per-edit pre-edit search log (the single edit):**
- (a) **Subject:** precedence/applicability of review-ownership (`caller == reviewed_by`) and segregation (`caller != instructor_id`) vs. the `UNDER_REVIEW` state precondition on the three credential decision endpoints; the error surfaced for a decision call on a `SUBMITTED` application.
- (b) **Impl paths enumerated:** grep over all of `implementation/` confirmed decision logic lives only in `routes/credential_applications.py`. Read in full: `_decision` L88-113 (shared by `approve`/`deny`/`request_revision` L116-128) — ownership/SoD checked unconditionally before state; `begin_review` L73-85 — notably performs **no** SoD check, so `reviewed_by == instructor_id` is reachable, meaning on later states a recorded owner who is the instructor gets `ERR_CREDENTIAL_SELF_APPROVAL`, not the state error; `resubmit` L131-146 and `create` L25-53 — instructor-ownership paths the edit deliberately does not touch. Test surface cross-checked: test_02's fixed test, test_06 self-approval and owner-mismatch tests, test_10's revision/resubmit/re-claim cycle — all consistent with the inserted sentence.
- (c) **Wording adjustment:** dropped a draft clause claiming a caller equal to the recorded owner reaches the state error — false where owner == `instructor_id` (SoD interposes at the same priority). Final wording pins only (i) the checks' state-independence and §2.10 precedence, and (ii) the concrete `SUBMITTED` outcome; both are true on every enumerated path.

## Step 9: Complete PRD — 2026-08-14T10:24:27.000Z

All 17 hunks landed as intended — every change is an in-paragraph insert/revision; no new sections, no reformatting. Final verification of the deliverable:

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1674_dual_enrollment_concurrent_credit/workspace/PRD_COMPLETED.md`
- Source: `workspace/PRD_FINALIZED.md` (312 lines / 48,503 chars) → PRD_COMPLETED.md (312 lines / 51,681 chars); char-delta **+3,178**, line count unchanged (all edits are inline paragraph revisions).

**Counts:** 19 ambiguity-pins (PRD silent → pinned to impl), 3 mismatch-revisions (PRD described a different behavior → revised to impl).

**Ambiguity-pins (inserts):**
- §2.1 — insert — ambiguity — empty/whitespace-only `X-User-ID`/`X-User-Role` header values are treated as missing and rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` — `implementation/middleware.py:36-43`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` rejected with `ERR_INVALID_PAGINATION_PARAMETERS`; empty value treated as absent — `implementation/validate.py:104-126`
- §2.3 — insert — ambiguity — per-endpoint equality-filter query params enumerated (terms, students, instructors, prerequisites, placement records, credential applications, offerings, enrollments, transcript entries, funding agreements, invoices, payments, articulation agreements; none for high schools/courses), applied before pagination so `total_count`/`has_more` reflect the filtered set; unrecognized params ignored — `implementation/routes/helpers.py:11-23` plus each route's `list_response(...)` filters
- §2.3 — insert — ambiguity — `created_at`-ascending ties broken by creation order — `implementation/services/core.py:38-42`
- §2.6 — insert — ambiguity — `updated_at` initialized equal to `created_at`; `version` starts at 1 at creation — `implementation/services/core.py:14-17`
- §2.10 — insert — ambiguity — course-must-be-`ACTIVE` precondition for offering create/open pinned to priority 6 — `implementation/routes/offerings.py:59-61,119-121`
- §3.1 — insert — ambiguity — creating an offering on a non-`ACTIVE` course rejected with `ERR_INVALID_STATE` (409) — `implementation/routes/offerings.py:59-61`
- §3.3 — insert — ambiguity — `decision_reason` starts null at application creation — `implementation/routes/credential_applications.py:50`
- §3.3 — insert — ambiguity — resubmit retains a previously recorded `decision_reason` — `implementation/routes/credential_applications.py:131-146`
- §3.4 — insert — ambiguity — start-session and begin-grading from any wrong origin state fail with `ERR_OFFERING_INVALID_STATE` — `implementation/routes/offerings.py:146-147,157-158`
- §3.5 — insert — ambiguity — enrollment creation requires an `OPEN` offering (else `ERR_OFFERING_INVALID_STATE`), and new enrollments start with `grade`, `waitlist_seq`, `withdrawn_at` null — `implementation/routes/enrollments.py:80-106`
- §3.5 — insert — ambiguity — placement recency full ties broken in favor of the later-created record — `implementation/services/calculations.py:390`
- §3.5 — insert — ambiguity — cancel-waitlist retains `waitlist_seq` (never reused) — `implementation/routes/enrollments.py:288-299`, `implementation/services/calculations.py:238-245`
- §3.7 — insert — ambiguity — invoice refund fields (`refund_pct`, `refund_estimate_cents`, `est_*`, `refund_paid_cents`) are null at creation until a refund event — `implementation/services/calculations.py:157-162`
- §3.8 — insert — ambiguity — submit-grade on non-`REGISTERED` enrollment → `ERR_ENROLLMENT_INVALID_STATE`; while offering not `GRADING` → `ERR_OFFERING_INVALID_STATE`; repeat submission overwrites the grade — `implementation/routes/enrollments.py:313-322`
- §3.8 — insert — ambiguity — finalize creates transcript entries in enrollment creation order, `COLLEGE` entry before `HIGH_SCHOOL` per enrollment — `implementation/services/transitions.py:88-111`
- §3.8 — insert — ambiguity — voiding from any non-`POSTED` state → `ERR_TRANSCRIPT_ENTRY_INVALID_STATE` — `implementation/routes/transcript_entries.py:56-57`
- §3.9 — insert — ambiguity — `target_institution` query param required; omitted/empty → `ERR_VALIDATION` (400) — `implementation/routes/enrollments.py:329-331`
- §3.9 — insert — ambiguity — transfer-evaluation response echoes the requested `target_institution` — `implementation/services/calculations.py:439-445`

**Mismatch-revisions:**
- §2.5 — revise — mismatch — "A confirm ... each moves `seats_taken` by exactly one" overgeneralized; revised to "a confirm that registers the enrollment", with an explicit carve-out that a waitlist-outcome confirm moves no seat and leaves the offering `version` untouched — `implementation/routes/enrollments.py:185-193`
- §3.3 — revise — mismatch — PRD's parallel prose omitted `decision_reason` for deny; impl records it for all three decisions, so deny now "likewise recording an optional `decision_reason` when supplied" — `implementation/routes/credential_applications.py:107-110,122-123`
- §3.4 — revise — mismatch — offering-open checks reordered to impl's actual order: course `ACTIVE` (`ERR_INVALID_STATE`) first, then both terms `OPEN` (`ERR_TERM_NOT_OPEN`), then instructor credentialing — `implementation/routes/offerings.py:117-136`

Everything else in the implementation (endpoint table, roles, error catalogue, state machines, waterfall/refund/GPA formulas, OCC scope, cascades, clock semantics, envelope shapes, 201/200 status assignment) was already uniquely pinned by PRD_FINALIZED.md and required no change.

Post-Step-9 orchestrator verification: `workspace/PRD_COMPLETED.md` present; all 8 final-sweep results files show 92/92 passed, 0 failed.
