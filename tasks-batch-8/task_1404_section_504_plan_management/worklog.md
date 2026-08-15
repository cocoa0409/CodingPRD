# Worklog — task_1404_section_504_plan_management

## Step 1: Create Task Directory — 2026-08-13T03:57:23.830Z

Pre-assigned directory `tasks/task_1404_section_504_plan_management/` with `workspace/` already exists; no index scan performed, nothing created (per orchestrator instructions).

## Step 2: Generate Scaffold — 2026-08-13T04:59:40.543Z

## Summary (verbatim from subagent)

**Task**: Section 504 Plan Management scaffold generated at `/home/ubuntu/github/CodingPRD/tasks/task_1404_section_504_plan_management/`

**Files produced**:
- `SCAFFOLD.yaml` (1,945 lines) — §1.0–§1.7
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2,614 lines) — §1.8, single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (3,925 lines) — §1.9, single top-level key `scaffold_corner_design`

**Counts**:
- 15 entities, 77 endpoints, 8 state machines (42 transitions), 8 calculations, 17 validations, 64 errors, 5 roles, 3 OCC concurrency rules
- §1.8: 18 active instances (9 rules × 2 each, satisfying minimums)
- §1.9: 43 active instances + 4 excluded stubs across all 9 claim-extraction sections
- 918 total calls in setup/trigger chains, all lint-clean

**Key design decisions**:
- **Topology**: flat (not hierarchical) — chosen because `scaffold_lint.py`'s FK reverse-reachability check effectively requires top-level single-GET endpoints per entity; flat also aligns with §0.3's stated diversity preference
- **Primary archetype**: compliance_audit; secondary: workflow_orchestration
- **Role model**: segregation_of_duties (referral-submitter ≠ determiner; plan-drafter ≠ testing-approver; grievance-intake ≠ resolver)
- **Difficulty machinery**:
  - Dual-variant calculations: implementation_compliance_ratio (trailing_30_day vs cumulative_plan_year) and annual_review_window_check (annual_strict vs re_evaluation_strict)
  - Combinatorial formulas: posture derivation (mode a — 4-input weighted scoring with nested min/max and flag override) and training coverage rounding (mode b — round-then-threshold)
  - Cyclic state machines: Plan MODIFY_PLAN loop and EligibilityEvaluation self-referential re-evaluation chain
  - 3 OCC concurrency rules on Plan/Student/Grievance parents
  - Cascading postural gating: clock → review OVERDUE → school_posture → mutation block (depth 3)
- **Logical clock**: `POST /_clock/set_current_utc` test-driving endpoint with default `2026-08-01T00:00:00Z`
- **Lint verdict**: clean (0 violations across all 918 calls + 23 FK reverse-reachability checks)

## Step 3: Copy Shared Files — 2026-08-13T05:00:03.252Z

Copied `./INSTRUCTION.md` to `tasks/task_1404_section_504_plan_management/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T05:13:20.458Z

## PRD Generation Complete (verbatim from subagent)

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1404_section_504_plan_management/workspace/PRD.md` — 384 lines

**Section list:**
- §1 Introduction (2 paragraphs, compliance/pain-point angle)
- §2 Global Specifications — 2.1 RBAC (5 roles with identity translation), 2.2 API Response Structure (verbatim block, byte-identical), 2.3 Pagination, 2.4 Common Resource Properties & Compliance Audit Trail, 2.5 Logical Clock & Scheduled Deferred Actions, 2.6 Resource Addressing & Existence Checks, 2.7 Optimistic Concurrency Control, 2.8 Validation Precedence (17-step ordered), 2.9 Segregation of Duties, 2.10 School Compliance Posture (weighted scoring), 2.11 Precision, Rounding & Calendar Arithmetic
- §3 Business Logic — 9 subsections (schools/staff/training, referrals, evaluations, plan drafting→activation, accommodations/implementation/suspension, reviews/exit paths, testing requests, grievances, consent records)
- §4 Endpoint Definitions (4-column table)
- §5 Error Code Catalogue (2-column table)

**Coverage counts:**
- Rules: 17 validations (priority-ordered in §2.8), 3 OCC rules (all with write operation + `expected_*_version` field + exact error id + 412), 7 calculations (compliance ratio both variants, determination timeliness, annual/re-eval window checks with 379/1095 boundaries, lead-time 14-pass/13-fail, training coverage, posture weighted score with weights 20/50/15-cap-30/25 and thresholds 60/30, ack completion gate), all state-machine transitions across 9 machines with preconditions paired to error ids and every cross-entity cascade stated
- Endpoints: 77/77 in the §4 table
- Errors: 64/64 — each appears in §2/§3 prose and in the §5 table

**Hard Contract results:**
- Contract 1 (Field-Name Coverage): 85 entity fields / 62 endpoint input identifiers / 31 query params / 15 path params — 0 missing. PASS (one gap found and repaired during audit: the `ACKNOWLEDGED` state value was missing)
- Contract 2 (Rule Coverage): all six high-risk categories expressed — priority ordering explicit in §2.8; all 3 OCC rejections fully named; all cascades (plan activation, exit-to-IEP 4-way cascade, discontinue→deny cascade, posture recomputes) stated; all `applies_to` scopes enumerated; field defaults/nullability/computed semantics placed on owning entities; sibling branches (4 review outcomes, consent grant/deny pairs, suspend/resume) at equal density. PASS
- Contract 3 (§3 Path Purity): 607 backtick tokens scanned in §3 — 0 paths, 0 bare methods, 0 method+path combos. PASS

**Zero-Silence Rule audit:** confirmed — every SCAFFOLD.yaml behavior (all transitions, side effects, calculations, validations, error ids, enum/state values, clock default `2026-08-01T00:00:00Z`, `ComplianceAuditEvent` common-fields exception, 17-value audit event vocabulary, compliance-summary output fields) is represented in PRD prose. The withheld difficulty/corner design files were never opened.

## Step 5: Generate Unit Tests — 2026-08-13T05:48:13.231Z

## Generation complete — task_1404_section_504_plan_management (verbatim from subagent)

**Tests generated: 73 total**
- **Queue A (Difficulty, §1.8): 34 tests** — 17 of 18 instances covered with exactly 2 tests each
- **Queue B (Corner, §1.9): 39 tests** — 39 of 43 non-stub instances covered with exactly 1 test each; all 4 `excluded_because:` stubs correctly untranslated (pointers verified; note `compliance_summary_computed_read`'s `difficulty_instance` pointer is malformed — it points at a corner instance, not a §1.8 one — treated as a corner-design bug, no test emitted)

**Instances skipped (5) with reasons:**
1. `Difficulty/priority_pair_validation_conflict/occ_state_vs_business_constraint_on_plan_submit` — PRD internally contradicts: §2.8 orders the OCC stale-version check (priority 5) before the accommodations check (priority 16), but §3.4 says submit-for-consent "checks, in order" and lists the OCC check *last*. Not uniquely derivable. (This also leaves `ERR_STALE_PLAN_VERSION` rejection uncovered — the corner stub `occ_stale_plan_version_rejected` pointed here.)
2. `Corner/entities/student_create_missing_required_returns_400` — PRD prose never names `ERR_INVALID_REQUEST` as the outcome of a missing required field on `/students` (its only narrative trigger is the consent-records both/neither rule in §3.9); §5 explicitly disclaims conditions.
3. `Corner/entities/student_invalid_grade_level_out_of_range` — same gap: PRD states the 0–12 range but names no error for violating it.
4. `Corner/entities/student_invalid_enum_suspected_disability` — same gap: enum vocabulary listed, no rejection rule in prose.
5. `Corner/errors/err_evaluation_already_open` — unreachable via the public API: initiating an evaluation requires an UNDER_REVIEW referral, which requires student status REFERRED, while any open evaluation pins the student at EVALUATING; the instance's own recipe concedes this (`trigger: []`, "Skipped" assert).

**PRD-coverage gaps encountered:** the §2.8 vs §3.4 check-ordering contradiction (a genuine PRD bug), and the missing generic input-validation narrative (`ERR_INVALID_REQUEST` has no prose trigger for missing fields / invalid enums / out-of-range values). A third latent tension: §2.8 item 4's blanket AUDIT_HOLD mutation block vs §3.8's claim that closing an OCR-escalated grievance "may let the school drop back out of `AUDIT_HOLD`" — the OCR cascade second test was therefore written to assert the (unambiguous) mutation-blocked direction only.

**`test_helpers/` files produced:** `__init__.py` (barrel export), `types.py` (16 entity TypedDicts with correct `common_fields` branching — `ComplianceAuditEvent` omits `updated_at`/`version`), `api_client.py` (78 endpoint methods, one per PRD §4 row), `api_errors.py` (full error enum + HTTP map registered via `set_error_http_status_map`), `assertions.py` (per-entity + audit-event append-only shape), `factories.py`, `constants.py` (posture weights, windows, thresholds), `test_users.py` (shared constants + mandatory per-instance `make_<role>_headers` builders + `headers_missing_user_id` probe), `fixtures.py` (5-tier composite pipeline: clock/school/staff/student creators, referral→determination walk, plan draft→submit→consent→ack→activate, reviews/testing/logs/grievances, posture snapshots).

**`test_suite/` files:** `conftest.py` + 11 test files organized by concern (schools/training, students/referrals, evaluations, plan consent/ack, accommodations/logging, suspension/overlap, reviews/exit, testing requests, grievances, posture, security). Every test docstring carries verbatim PRD citations (grep-verified) and ends with exactly one `Design:` tag resolving to a real instance — audited programmatically: 0 problems.

## Step 6: Generate Implementation — 2026-08-13T05:51:27.587Z

## Summary (verbatim from subagent)

All 84 end-to-end checks pass from a fresh process (`ALL PASS`, exit 0). The implementation is complete.

**Files produced** in `/home/ubuntu/github/CodingPRD/tasks/task_1404_section_504_plan_management/workspace/implementation/`:
- `start.sh` (executable; guarded `pip install`, `exec python3 app.py`), `requirements.txt` (flask>=3,<4)
- `app.py` (entry, error handlers, blueprint registration, per-request lock; `0.0.0.0:$PORT`, default 10000)
- `db.py` (in-memory dict store, logical clock defaulting to 2026-08-01T00:00:00Z, id/seq/touch helpers — **no seeding, store starts empty**)
- `errors.py` (full error catalog), `response.py` (`meta`/`response_type`/`data` envelope, 3-fractional-digit timestamps, `req_` ids), `middleware.py` (X-User-ID/X-User-Role auth, 5 roles, body/field/pagination validation), `util.py` (ISO parse/format, floor-days, Decimal ROUND_HALF_UP percentages, calendar-year offset)
- `services.py` (lookups, audit ledger, posture derivation, coverage, compliance windows, serializers with live computed fields)
- `routes/` — 15 modules: schools, staff (+training), students, referrals, evaluations, plans, accommodations, acks, logs, reviews, testing, consents, grievances, audit, clock

**Endpoint coverage: 77/77** — every row of the PRD §4 table is implemented (verified by decorator count and exercised in the e2e sweep), with the exact role sets from the RBAC matrix.

**State machines implemented (8 + 2 parallel dimensions):** Referral (PENDING→UNDER_REVIEW→EVALUATION_INITIATED/REJECTED/WITHDRAWN), EligibilityEvaluation (incl. re-evaluation chain via `supersedes_evaluation_id` and plan evaluation_id switch on late ELIGIBLE determination), Section504Plan (full lifecycle incl. MODIFY_PLAN cyclic loop and auto-activation on last ack), Accommodation (with auto-deny cascade to testing requests), TeacherAcknowledgment (ownership + training gate), ReviewEvent (SCHEDULED/OVERDUE→IN_PROGRESS→COMPLETED with 4 outcome cascades; cancel compensation), TestingAccommodationRequest (incl. retroactive `State `-prefix flag check), Grievance (FILED→…→RESOLVED/CLOSED, OCR path), Student's parallel `section_504_status`/`iep_status` dimensions, School posture.

**Calculation rules implemented (all 7):** implementation_compliance_ratio (trailing-30 inclusive window + cumulative plan-year anchor, 2dp half-up, empty→100.0), determination_timeliness_check (floor-days > 60; late NOT_ELIGIBLE rejected, late ELIGIBLE emits REVIEW_COMPLETED_LATE), annual_review_window_check (365d + 14d grace for ANNUAL, strict for RE_EVALUATION), re_evaluation_cadence_check (1095 days), testing lead time (floor-days ≥ 14; 14 passes/13 fails), staff_training_coverage_ratio (1.0 for empty staff), school_posture_derivation (weighted, capped at 100; OCR forces AUDIT_HOLD), teacher_ack_completion_gate (literal formula: ≥1 row, no PENDING, no DECLINED).

**Key fidelity decisions:** validation precedence follows PRD §2.8's global order where it conflicted with §3.x narrative order (OCC at priority 5 before state at 6); OCC rejections emit `OCC_CONFLICT` audit events; the AUDIT_HOLD mutation gate exempts the grievance lifecycle, plan suspend (AUDIT_HOLD is itself a suspension justification), and `/_clock` — otherwise holds would be unrecoverable deadlocks; review-complete checks outcome gates *before* any mutation (atomicity — a gated EXIT_TO_IEP leaves the review IN_PROGRESS); training `expires_at` uses calendar +2 years (PRD "exactly two years") while re-evaluation uses the explicit 1095-day constant; clock advance flips SCHEDULED→OVERDUE (REVIEW_OVERDUE), lapses TRAINED_CURRENT→TRAINED_EXPIRED (TRAINING_LAPSED), and recomputes all postures (POSTURE_CHANGED on movement).

**Boot confirmation:** `bash start.sh` verified booting in the foreground on a custom `$PORT` (18732 → 200) and on the default port 10000 (→ 200), bound to 0.0.0.0; repeated fresh-process boots were used throughout testing (per-test-server isolation pattern) with no carry-over state.

## Step 7: Run Tests and Iterate — 2026-08-13T06:09:16.673Z

## Summary (verbatim from subagent)

Clean 8-round parallel sweep achieved. Final summary:

**Iterations run:** 2 (iteration 1: 7 consistent failures + 1 flaky infra error per round; iteration 2: **73/73 passed in all 8 rounds** — exit condition met).

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1404_section_504_plan_management/test_helpers/fixtures.py` — `suspend_plan_with_low_compliance`: the fixture dated its deviation log `2026-01-15` while the logical clock still sat at the activation instant `2026-01-01`; the log fell outside PRD §3.5's trailing window ("inclusive window from 30 days before the current clock instant through the instant itself"), so the PRD-faithful implementation correctly computed 100% compliance and rejected suspension. Log is now dated at the plan's `plan_effective_date`, keeping it in-window.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1404_section_504_plan_management/test_suite/test_06_suspension_and_overlap.py` — `test_second_review_rejected_while_first_is_scheduled` and `test_second_review_rejected_while_first_is_in_progress`: ERROR PRECEDENCE SILENCE. Scheduling review #1 moves the plan to `UNDER_ANNUAL_REVIEW`, so review #2 violates both the §2.8-item-6 state precondition (`ERR_PLAN_NOT_ACTIVE`) and the §3.6 one-open-review capacity rule (`ERR_REVIEW_ALREADY_SCHEDULED`); §2.8's 17-item priority list omits the capacity check, so the precedence is not uniquely derivable from PRD. Relaxed to `validate_error_is_one_of([ERR_REVIEW_ALREADY_SCHEDULED, ERR_PLAN_NOT_ACTIVE])` — both error ids are PRD-verbatim for this scenario (the protocol's permitted relaxation), and the capacity rule remains covered since a second schedule must still be rejected.

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1404_section_504_plan_management/workspace/implementation/db.py` — `new_id()`: returned `uuid.uuid4().hex` (32 hex chars, no hyphens), failing the canonical-UUID shape asserted on entity ids per PRD §2.4 ("`id` — a server-minted UUID with no type prefix"). Now `str(uuid.uuid4())`. This fixed 4 tests across school creation, staff registry, and the two audit-event assertions.
- `start.sh` was briefly changed to a sentinel-based pip skip, but that triggered `pip install` on a PEP 668 externally-managed host (which fails outright) — reverted to the original read-only `import flask` guard; no net change.

**Infra flake (no code change):** `test_two_grievances_flip_posture_and_two_resolves_restore_it` errored in 6/8 iteration-1 rounds with "API server could not be restarted" — the runner's hardcoded 15s per-test restart poll exhausted at a lockstep restart instant (all rounds restart within 3ms of each other) under multi-tenant host load (many other pipeline sweeps share this 32-core host). The test itself is PRD-faithful (§2.10/§3.8 grievance-weight/resolve-restore invariant); it passed 8/8 in iteration 2 and was kept unchanged.

Orchestrator verification: all 8 `results.{1..8}.json` files show `passed == total == 73`.

## Step 7: Test-Iteration Sweep — 2026-08-13T06:20Z

**Iteration 1 (8 parallel rounds):** 7 failed + 1 flaky error per round, union of 8 distinct tests.
**Iteration 2 (8 parallel rounds):** 73/73 passed in every round — clean sweep, exit.

Fixes applied:
- `workspace/implementation/db.py` (`new_id`) — emitted `uuid.uuid4().hex` (32-char, no hyphens); PRD §2.4 requires "a server-minted UUID", and the benchmark's canonical form is the hyphenated RFC 4122 string. Switched to `str(uuid.uuid4())`. Fixed 4 tests (school/staff/audit-event id shape assertions).
- `test_helpers/fixtures.py` (`suspend_plan_with_low_compliance`) — fixture bug: filed the deviation log with `log_date=2026-01-15` while the fixture clock still sat at the activation instant `2026-01-01`; the log fell outside PRD §3.5's trailing window ("inclusive window from 30 days before the current clock instant through the instant itself"), so the PRD-correct implementation computed 100% compliance and rejected suspension with `ERR_NO_SUSPENSION_JUSTIFICATION`. Log is now dated at the plan's `plan_effective_date`. Fixed `test_second_plan_rejected_while_first_is_suspended`.
- `test_suite/test_06_suspension_and_overlap.py` (2 review-capacity tests) — ERROR PRECEDENCE SILENCE: scheduling review #1 moves the plan to UNDER_ANNUAL_REVIEW, so review #2 violates both the §2.8-item-6 state precondition (`ERR_PLAN_NOT_ACTIVE`) and the §3.6 capacity rule (`ERR_REVIEW_ALREADY_SCHEDULED`); §2.8's priority list omits the capacity check, so precedence is not uniquely derivable. Relaxed to `validate_error_is_one_of([ERR_REVIEW_ALREADY_SCHEDULED, ERR_PLAN_NOT_ACTIVE])` (both ids are PRD-verbatim for this scenario; the capacity rule stays covered — a 2nd schedule must be rejected).
- Infra flake (no code change): `test_two_grievances_flip_posture_and_two_resolves_restore_it` errored in 6/8 rounds of iteration 1 with "API server could not be restarted" (runner's hardcoded 15s per-test restart poll exhausted at a synchronized restart instant under multi-tenant host load). Test itself is PRD-faithful; passed 8/8 in iteration 2.

Tests deleted: none.

## Step 8: Finalize PRD — 2026-08-13T06:13:57.640Z

## Summary (verbatim from subagent)

Done. `PRD_FINALIZED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_1404_section_504_plan_management/workspace/PRD_FINALIZED.md` with exactly one change.

**Line counts:** PRD.md 383 lines → PRD_FINALIZED.md 383 lines (0% line delta; one line extended by 169 characters).

### Changes
- **§3.6 — insert** — added one sentence to the review-scheduling paragraph pinning error precedence: "The plan-state precondition is evaluated before the one-open-review capacity check, so a scheduling request that violates both rules is rejected with `ERR_PLAN_NOT_ACTIVE`." — **impl: `workspace/implementation/routes/reviews.py:34-39`** (plan-status check at L34-35 strictly precedes the capacity scan at L36-39).

### Step-7 items verified as needing no PRD change
- **Fixture fix (`suspend_plan_with_low_compliance`)**: PRD §3.5's "inclusive window from 30 days before the current clock instant through the instant itself" matches `implementation/services.py:287-293` exactly (`lo = now() - 30d`, `hi = now()`, `lo <= log_date <= hi`); the suspension path (`routes/plans.py:235`) consumes the same `compliance_trailing_30`. Pure fixture bug.
- **`new_id()` fix**: PRD §2.4 ("a server-minted UUID with no type prefix") was already correct; the impl was fixed to `str(uuid.uuid4())` at `implementation/db.py:52-55`. No PRD edit.
- **start.sh revert / infra flake**: no net code change, nothing to pin.

### Per-edit pre-edit search log (single edit)
- **(a) Subject**: evaluation order of the plan-`ACTIVE` state precondition vs the one-open-review capacity rule in review scheduling (`POST /reviews`) — which of `ERR_PLAN_NOT_ACTIVE` / `ERR_REVIEW_ALREADY_SCHEDULED` surfaces when both are violated.
- **(b) Impl paths enumerated**: full read of `create_review` (`routes/reviews.py:25-51` — order: existence L29 → posture gate L31 → payload validation L32-33 → plan-status L34-35 → capacity L36-39); grep `ERR_REVIEW_ALREADY_SCHEDULED` → single raise site (reviews.py:38); grep `ERR_PLAN_NOT_ACTIVE` → raise sites at accommodations.py:77, accommodations.py:92, testing.py:84, reviews.py:35, plans.py:234, all on different endpoints with no adjacent capacity check; review start/complete/cancel (reviews.py:76-233) never schedule; test evidence in `test_suite/test_06_suspension_and_overlap.py:140-147,171-178`.
- **(c) Wording adjustment**: pinned the order as a scoped sentence inside §3.6's scheduling paragraph rather than inserting a numbered item into §2.8 — inserting would renumber items 7–17, breaking the §2.10 "item 4 of §2.8" cross-reference and the impl's documented "Priority 7 before priority 17" correspondence for the EXIT_TO_IEP gates (`reviews.py:132-143`). The wording is scenario-neutral (an order statement, not a claim about which states coexist), so it stays true for all four combinations of (plan ACTIVE?, open review?) — including the unreachable-in-practice ACTIVE+open-review case, where the capacity error would fire.

## Step 9: Complete PRD — 2026-08-13T06:44:00.000Z

## Summary (verbatim from subagent)

Done. PRD_COMPLETED.md produced at `/home/ubuntu/github/CodingPRD/tasks/task_1404_section_504_plan_management/workspace/PRD_COMPLETED.md`.

**Size:** PRD_FINALIZED.md 383 lines / 59,282 chars → PRD_COMPLETED.md 385 lines / 63,112 chars (+2 lines, +3,830 chars). All edits are in-paragraph inserts/revisions; no new sections.

**Counts:** 14 ambiguity-pins, 5 mismatch-revisions (19 edited passages total).

Changes:

- §2.1 — insert — ambiguity — unrecognized `X-User-Role` string (or blank `X-User-ID`) is "malformed" → 400, while `ERR_UNAUTHORIZED_ROLE` applies only to recognized-but-not-permitted roles — implementation/middleware.py:20-25
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST` 400; boolean filters accept `true`/`false` case-insensitively else 400; `created_at` ties break by insertion order — implementation/middleware.py:106-140, implementation/routes/__init__.py:8
- §2.5 — insert — ambiguity — clock may be set to any instant (no monotonicity); envelope `meta.api_request_timestamp` is wall-time, not logical clock — implementation/routes/clock.py:23-26, implementation/response.py:13-16
- §2.6 — insert — ambiguity — unrecognized path / unsupported method → generic `ERR_NOT_FOUND` 404 — implementation/app.py:33-40
- §2.8 — insert — ambiguity — body field validation (`ERR_INVALID_REQUEST`) is evaluated after checks 1–4 and before checks 5–17; dependent referenced-resource existence (§3.9 XOR) is confirmed right after validation — implementation/routes/plans.py:56-63, implementation/routes/consents.py:21-34
- §2.10 — revise — mismatch — posture recompute triggers rewritten from "whenever an audit event is appended" to the impl's actual set (grievance file/resolve/escalate/close, review overdue-flip/completion, staff registration, training record, clock advance) — implementation/services.py:263-277 and call sites
- §3.1 — insert — ambiguity — two-year expiry is calendar years (Feb 29 → Feb 28); "latest training record" = latest `trained_at`, ties by most recent creation — implementation/util.py:39-44, implementation/services.py:177-181
- §3.2 — revise — mismatch — `student_external_ref` uniqueness is not enforced — implementation/routes/students.py:27-37 (no uniqueness check)
- §3.2 — insert — ambiguity — `grade_level` outside 0–12 → `ERR_INVALID_REQUEST` 400; student PATCH increments `version` on every call even when `iep_status` absent/unchanged — implementation/routes/students.py:23-26, 71-75
- §3.3 — insert — ambiguity — request-consent returns HTTP 201 with the created consent record; record-consent returns the updated evaluation — implementation/routes/evaluations.py:81, 116
- §3.3 — revise — mismatch — determination guard order pinned as prior-evaluation check → segregation → timeliness (PRD had listed segregation first and deferred to a §2.8 that omits `ERR_PRIOR_EVALUATION_OPEN`) — implementation/routes/evaluations.py:144-163
- §3.4 — insert — ambiguity — drafting does not check that the named evaluation belongs to the named student — implementation/routes/plans.py:56-61
- §3.4 — revise — mismatch — submit-for-consent check order corrected to OCC version → DRAFT → ELIGIBLE → one-open-plan → has-accommodations (PRD had DRAFT first, OCC last); submission returns the updated plan — implementation/routes/plans.py:131-165
- §3.4 — insert — ambiguity — record-parent-consent returns the updated plan; acknowledge/decline return the updated ack row; replacement ack rows accept any existing staff member with no role/school/plan-status validation — implementation/routes/plans.py:177-221, implementation/routes/acks.py:20-35, 60-100
- §3.5 — insert — ambiguity — accommodations may be added whatever the plan's status; discontinuing has no plan-status precondition; implementation logging applies no same-plan referential check between `plan_id` and `accommodation_id`; cumulative window includes logs with `log_date` on or after the anchor; plan suspension is exempt from the AUDIT_HOLD posture gate — implementation/routes/accommodations.py:18-33, 98-110, implementation/routes/logs.py:21-43, implementation/services.py:307-313, implementation/routes/plans.py:224-236
- §3.6 — revise — mismatch — `was_late` starts false (PRD said all three fields "stay unset"; only `completed_at`/`outcome` are null) — implementation/routes/reviews.py:40-48
- §3.6 — insert — ambiguity — grace window is zero for `PARENT_REQUESTED` and `DISTRICT_AUDIT` reviews (overdue flip and `was_late`); spawned re-evaluation copies the superseded evaluation's `referral_id` — implementation/services.py:335-337, implementation/routes/reviews.py:96-122
- §3.7 — insert — ambiguity — testing-request submission imposes no plan-status requirement (ACTIVE required only at forwarding); failed flag integrity conditions → `ERR_INVALID_STATE` 409 — implementation/routes/testing.py:26-49, 137-141
- §3.8 — insert/revise — ambiguity + mismatch — all grievance mutations are exempt from the posture gate; `GRIEVANCE_FILED` `actor_staff_id` is null when the filer is a `Parent`; resolve from any non-`INFORMAL_RESOLUTION`/`FORMAL_INVESTIGATION` state yields `ERR_GRIEVANCE_NOT_INFORMAL` (PRD's "or `ERR_GRIEVANCE_NOT_FORMAL` respectively" removed) — implementation/routes/grievances.py:1-7, 51-53, 120-122
- §3.9 — revise — mismatch — ad-hoc consent creation accepts any value in the `consent_scope` vocabulary (not just the three listed scopes); record-response has no `consent_status` precondition and overwrites prior decisions — implementation/routes/consents.py:23, 76-89
- §2.11 — insert — ambiguity — ISO 8601 inputs accept dates or datetimes with `Z`/numeric offsets; timezone-naive values read as UTC — implementation/util.py:16-31

No remaining PRD silence or mismatch found against the implementation: all 15 route modules, services.py calculations, middleware validation, error catalog, and response envelope were walked exhaustively.
