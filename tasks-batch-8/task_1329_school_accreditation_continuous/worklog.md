# Worklog — task_1329_school_accreditation_continuous

## Step 1: Create Task Directory — 2026-08-12T00:00:00.000Z

Task directory `tasks/task_1329_school_accreditation_continuous/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher; Step 1 treated as DONE (no index scan, no mkdir). Difficulty directive from launcher: "Generate task hard than expert level!"

## Step 2: Generate Scaffold — 2026-08-12T22:43:30.000Z

All checks pass. The scaffold is complete and lint-clean.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1329_school_accreditation_continuous/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 plus complexity profile, concurrency rules; no difficulty/corner keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design:`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design:`

**Counts:**
- Entities: 20
- State machines: 13 (incl. cyclic SelfStudyRating revision loop, branching SurveyWindow threshold fork, 8-state AccreditationTerm lifecycle, compound campus/term gating, clock-driven auto-transitions on SurveyWindow/VisitEvent/RequiredActionItem/AccreditationTerm)
- Endpoints: 95
- Errors: 14
- Roles: 6 (AccreditationOfficer, AccreditationCommission, SchoolLeader, Reviewer [entity_backed:Reviewer], SystemBursar, Anonymous) — segregation-of-duties role model
- Calculations: 8; Validations: 10 priority levels; OCC concurrency rules: 3
- §1.8 instances: 18 (9 rules × 2)
- §1.9 instances: 35 across all 9 taxonomy sections
- Lint: `VERDICT: clean lint` (616 calls scanned)

**Top difficulty levers exercised:**
- **Dual-variant calcs on different domains**: campus composite (persisted per-campus vs read-time system projection) and visit fee (provisional-at-confirm vs final-at-report-issued settlement)
- **Combinatorial formulas in different modes**: tiered annual fee with >= threshold boundary + credit/penalty signed-balance interaction (mode a); pinned single-round half-up composite index at 84.375 → 84.38 (mode b)
- **Transitive cascades, depth 3**: finalize → campus composite → campus.version → dashboard; late report accept → fee_credit −25000 → next invoice amount 645000 (precomputed literals)
- **Validation priority conflicts on different category pairs**: state(4) vs temporal(6) on survey responses; temporal(6) vs referential(7) on visit confirm
- **Temporal windowing with two interval semantics**: half-open interval-intersection for campus visit overlap (adjacency allowed) vs instant-membership for survey response windows (inclusive open, exclusive close)
- **Boundary precision**: participation threshold equality (200 >= 200 passes), zero-quorum evidence finalize, month-clamp due dates (2026-08-31 + 6mo → 2027-02-28), 60-day interim report windows
- **OCC on three parents** (AccreditationTerm, ImprovementGoal, Invoice) with strict `${var}` version capture discipline
- **Compensating invariants on different quantities**: composite index drift-free reopen/refinalize cycle; invoice outstanding-balance conservation across partial/final payments with terminal lockdown

## Step 3: Copy Shared Files — 2026-08-12T22:44:00.000Z

Copied ./INSTRUCTION.md to tasks/task_1329_school_accreditation_continuous/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-12T22:52:00.000Z

All checks pass. PRD generation is complete.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1329_school_accreditation_continuous/workspace/PRD.md` — 338 lines.

**Sections produced:**
- §1 Introduction (3 paragraphs, domain-context angle)
- §2 Global Specifications with 9 subsections: 2.1 RBAC & identity semantics, 2.2 API Response Structure (byte-identical verbatim block, verified), 2.3 Pagination, 2.4 Common Resource Properties, 2.5 Hierarchical Addressing & Validation Order, 2.6 Versioning/Cascading Mutation/OCC, 2.7 Standards/Weights/Precision, 2.8 Logical Clock & Time-Driven Transitions, 2.9 Segregation of Duties
- §3 Business Logic with 8 subsections organized by lifecycle: 3.1 Systems & Campuses, 3.2 Accreditation Terms, 3.3 Self-Study Ratings/Evidence/Composite Index, 3.4 Surveys, 3.5 Improvement Goals & Indicators, 3.6 Visiting Teams/Findings/Action Items, 3.7 Interim Reporting, 3.8 Fees/Invoices/Payments
- §4 Endpoint Definitions (95 endpoint rows + header rows, 4 columns only)
- §5 Error Code Catalogue (14 errors, 2 columns only)

**Coverage counts:**
- Entities: 20/20 (all fields of all 20 scaffold entities covered)
- State machines: 12/12 (AccreditationTerm, SelfStudyRating, EvidenceItem, SurveyWindow, ImprovementGoal, VisitEvent, VisitFinding, RequiredActionItem, InterimReport, Invoice, Reviewer, Campus, plus InstitutionSystem side-effect transitions)
- Calculations: 8/8 (composite index, survey participation, goal attainment, action-item due date, annual fee, visit fee incl. both variants, interim report due date, late-report penalty with 25000-cent constant)
- Endpoints: 95/95 in §4 table
- Errors: 14/14 named in prose and §5
- Roles: 6/6 with identity semantics translated (Reviewer entity-backed, five opaque)

**Contract audit findings:**
- Contract 1 (Field-Name Coverage): **PASS** — 81/81 entity fields, 53/53 endpoint inputs, 17/17 query params, path param `id` present. Initial draft missed 11 system-FK/system fields (`system_id`, `term_id` already present; missing were `finding_id`, `goal_id`, `invoice_id`, `rating_id`, `visit_id`, `window_id`, `reviewer_status`, `description`, `status`); repaired by weaving them into natural ownership narrative in §3.1–§3.8, then re-audited clean.
- Contract 2 (Rule Coverage): **PASS** — 10 validations with priority ordering expressed as an explicit ordered family list in §2.5; 3 OCC rules each naming write endpoint, token field, error id, and HTTP 412; all state-transition preconditions and side effects (including multi-entity cascades like decide → system status, issue-report → action-item creation + reviewer freeing); all 8 calculation formulas in precise prose with constants (rubric max 4, 60-day advance notice, 25000-cent penalty, 180-day renewal window, 6/12/18 follow-up months); sibling branches (DECISION→TERM_ACTIVE vs DECISION→CLOSED, SUBMITTED vs LATE accept, provisional vs final visit-fee variants) rendered with equal density.
- Contract 3 (§3 Path Purity): **PASS** — 535 backtick tokens scanned in §3, zero path/method/violation tokens.

**Repairs during drafting:** corrected an initial mischaracterization of manual survey close (scaffold forces `INVALIDATED` as a state outcome, not an `ERR_THRESHOLD_NOT_MET` rejection); removed a fabricated `ERR_FEE_SCHEDULE_MISSING` reference (scaffold nominates `ERR_FISCAL_VIOLATION`); clarified the OVERDUE→VERIFIED precondition requiring a preceding submit-evidence from OVERDUE.

## Step 6: Generate Implementation — 2026-08-12T23:15:00.000Z

Fresh boot verified — store is empty, envelope has all the right fields per scaffold spec.

## Summary

**Implementation generated** at `/home/ubuntu/github/CodingPRD/tasks/task_1329_school_accreditation_continuous/workspace/implementation/`

### Files produced (25 total)

- `start.sh` — foreground launcher with `exec`, guarded pip install, `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — `flask>=3.0,<4`
- `app.py` — Flask entry point with `ApiError` / 404 / 405 / 500 handlers
- `db.py` — in-memory store (20 entity collections) plus the logical clock (default `2026-08-01T00:00:00Z`, never falls back to wall clock)
- `errors.py` — `ApiError` exception carrying `error_id` / `http_status` / `message`
- `response.py` — envelope helpers producing exactly `{meta, response_type, data}` with `api_request_id` (`req_…`), `api_request_timestamp` (3-fractional-digit ISO), and list `meta.limit/offset/total_count/has_more`
- `middleware.py` — `X-User-ID` / `X-User-Role` auth, six roles, `ERR_UNAUTHENTICATED` 401 / `ERR_FORBIDDEN` 403
- `util.py` — ISO parsing, `add_years` / `add_months` (with Feb-29 → Feb-28 clamp and last-day-of-month clamp), `round_half_up_2` (Decimal, ROUND_HALF_UP), body validators, pagination (limit 1..100 default 10, offset 0)
- `services.py` — cross-cutting business logic (composite index, goal attainment, fee schedule selection, invoice issuance, interim due date, action-item due date, clock-driven transitions, late-report penalty)
- `routes/` (16 blueprints) — clock, systems, campuses, standards, terms, ratings, evidence, surveys, goals, reviewers, visits, findings, action_items, interim_reports, fees, invoices

### Endpoint count
**95 business endpoints** registered (matches PRD §4 exactly; Flask also auto-registers `/static/<path:filename>` which is ignored).

### State machines implemented (12)
AccreditationTerm (PREPARATION → SELF_STUDY → REVIEW → DECISION → TERM_ACTIVE → INTERIM_MONITORING → RENEWAL → CLOSED, plus DECISION→CLOSED on DENIED), SelfStudyRating (DRAFT/SUBMITTED/FINALIZED/REOPENED), EvidenceItem (PENDING/APPROVED/REJECTED), SurveyWindow (SCHEDULED/OPEN/CLOSED/INVALIDATED with participation threshold), ImprovementGoal (PROPOSED/ADOPTED/MONITORING/ACHIEVED/ABANDONED), VisitEvent (REQUESTED/CONFIRMED/IN_FIELD/REPORT_DRAFT/REPORT_ISSUED/CANCELLED with reviewer cascades), VisitFinding (DRAFT/ISSUED/SUPERSEDED), RequiredActionItem (OPEN/SUBMITTED/VERIFIED/OVERDUE/WAIVED with late-verify → ON_PROBATION side effect), InterimReport (DRAFT/SUBMITTED/ACCEPTED/RETURNED/LATE with LATE penalty), Invoice (ISSUED/PARTIALLY_PAID/PAID/VOID), Reviewer (AVAILABLE/ON_ASSIGNMENT/INACTIVE), Campus (IN_SCOPE/OUT_OF_SCOPE/WITHDRAWN with rating deletion cascade).

### Calculations implemented (8)
- `campus_composite_index` — Decimal weighted mean, ×100/4, ROUND_HALF_UP to 2dp; null when empty
- `survey_participation_rate` — integer-space `response_count*100 >= min_pct*eligible_count` (strict less-than fails)
- `goal_attainment` — direction-aware progress fraction, clamped [0,1], ×100, half-up 2dp; latest indicator by `measured_at`, ties broken by earliest `created_at`
- `action_item_due_date` — calendar-month addition with day-of-month clamp
- `annual_fee_invoice_amount` — tiered campus pricing + base fee + positive/negative credit ledger adjustment with `InstitutionSystem.version` bump on ledger movement
- `visit_fee_invoice_amount` — final-settlement variant (REPORT_ISSUED visits only) × `visit_day_rate_cents`
- `interim_report_due_date` — `add_years(term_start, report_year) − 60 days` with Feb-29 clamp
- `late_report_penalty` — 25000¢ debit on LATE accept; negative balance rolled into next ANNUAL_FEE

### Cross-cutting concerns
- 3 OCC rules with scaffold-named tokens: `expected_term_version` (412 ERR_STALE_TERM_VERSION), `expected_goal_version` (412 ERR_STALE_GOAL_VERSION), `expected_invoice_version` (412 ERR_STALE_INVOICE_VERSION)
- Validation priority order per PRD §2.5: auth → RBAC → existence → state → SoD → temporal → referential → uniqueness → threshold → fiscal
- Clock-driven transitions re-evaluated on every `_clock/set_current_utc`: window open/close, visit IN_FIELD/REPORT_DRAFT, action-item OVERDUE, term RENEWAL (with auto renewal-fee issuance that tolerates missing fee schedule)
- No seed data at boot; store starts empty
- `Standard`, `SurveyResponse`, `Payment`, `FeeSchedule` carry `id` + `created_at` only (no `updated_at`/`version`) per PRD §2.4

### Self-check results
- **Boot smoke test**: `bash start.sh` starts cleanly on `0.0.0.0:$PORT`, store is empty, response envelope matches scaffold
- **End-to-end test**: 25 assertions pass covering the full accreditation lifecycle (system → campus → standard → term → rating with OCC → evidence with SoD → finalize with composite=75.0 verification → reopen recompute → reviewer/visit/assignment/confirm → clock-driven IN_FIELD/REPORT_DRAFT → finding/issue/issue-report cascade → RequiredActionItem due_date=ends_on+6mo → decide ACCREDITED_WITH_STIPULATIONS → ON_PROBATION → submit/verify action item → interim report with 60-day advance-notice due date → advance to INTERIM_MONITORING → clock drives RENEWAL with auto renewal-fee invoice → close blocked before payment (ERR_FISCAL_VIOLATION) → pay invoice → close succeeds → `current_term_id` cleared)
- **412 stale-version rejection**, **422 SoD rejection**, and **composite=null after reopen** all verified

## Step 5: Generate Unit Tests — 2026-08-12T23:35:00.000Z

Generation complete. Summary:

## Deliverables

**`test_helpers/` (Stage 1)** — all under `/home/ubuntu/github/CodingPRD/tasks/task_1329_school_accreditation_continuous/test_helpers/`:
- `types.py` — 6-role enum, 16 status enums, 20 entity TypedDicts; the four lightweight records (`Standard`, `SurveyResponse`, `Payment`, `FeeSchedule`) correctly omit `updated_at`/`version` per PRD §2.4.
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per each of the ~85 PRD §4 endpoints (including `_clock/set_current_utc`); `api_client` singleton.
- `api_errors.py` — `ApiErrorId` (14 errors) + HTTP map registered via `set_error_http_status_map`.
- `assertions.py` — per-entity structural assertions; lightweight records assert `updated_at`/`version` absence (PRD §2.4 states they "are absent").
- `factories.py`, `constants.py` (LATE_REPORT_PENALTY_CENTS=25000, rubric max 4, 60-day notice, 180-day renewal window, PCT_ABS_TOL=0.001 for half-up 2dp comparisons).
- `test_users.py` — shared headers for all six roles plus `make_reviewer_headers(reviewer["id"])` (entity-backed) and per-instance makers for opaque roles (needed by the segregation-of-duties test where officer and leader share one X-User-ID).
- `fixtures.py` — composite chains: `setup_self_study_term` (full campus×standard rating coverage + advance), `walk_term_to_review`, `add_reported_visit` (confirm → clock through IN_FIELD/REPORT_DRAFT → finding → issue → issue-report), `walk_term_to_term_active`, `setup_open_action_item`, `setup_open_survey_window`, `setup_adopted_goal`, `setup_accepted_interim_report`, OCC-fresh `create_rating`/`post_payment`/`create_indicator` helpers.
- `__init__.py` barrel; `test_suite/conftest.py` session `api` + per-role header fixtures.

**`test_suite/` (Stage 2)** — 66 tests in 8 files; every docstring ends with exactly one verifiable `Design:` line (automated audit: all tags resolve, all are last-line, all quotes grep-verbatim against PRD.md).

## Coverage

- **Queue A (Difficulty): 16/18 instances × ≥2 tests = 32 tests.**
- **Queue B (Corner): 34/35 non-stub instances × 1 test = 34 tests.** (No `excluded_because` stubs exist in this index.)

## Skipped instances (PRD-contradiction, not weakened)

1. `Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_survey_response` — asserts `ERR_INVALID_STATE` for a response to a SCHEDULED window; PRD §3.4 uniquely states "The submission is accepted only while the window is `OPEN`; outside the window the request is rejected with `ERR_TEMPORAL_WINDOW_VIOLATION`."
2. `Difficulty/resource_temporal_overlap/survey_window_open_interval_membership` — asserts the at-`closes_at` response fails with `ERR_INVALID_STATE`; same PRD sentence derives `ERR_TEMPORAL_WINDOW_VIOLATION`.
3. `Corner/validations/aggregate_validation_second_active_term` — asserts `ERR_INVALID_STATE` when advancing a second term while the first is SELF_STUDY; PRD §3.2: "the same constraint guards the advance from `PREPARATION` to `SELF_STUDY`" where the constraint is the `ERR_DUPLICATE_RESOURCE` uniqueness rule — PRD uniquely derives `ERR_DUPLICATE_RESOURCE`.

## Notable adaptation

The design recipes for `temporal_vs_referential_on_visit_confirm` and `visit_confirm_requires_reviewer_available` assign an already-ON_ASSIGNMENT reviewer as CHAIR of the target visit — unreachable under PRD §3.6 ("the reviewer must exist and be `AVAILABLE`, else `ERR_REFERENTIAL_INTEGRITY`" at assignment time). The tests preserve each instance's asserted outcome exactly, but chair the target visit with a fresh AVAILABLE reviewer while `lead_reviewer_id` still names the busy one.

## Self-audit results

- Stage 1: package imports cleanly; framework signatures verified against installed `prd_bench_local_runner.testing` source; identity threading for the entity-backed Reviewer role used throughout fixtures; no "scaffold"/table references in generated code.
- Stage 2: 66/66 collect under pytest; every test has exactly one resolving `Design:` tag on the docstring's last line; every ≥4-word quoted segment in every docstring found verbatim in PRD.md (0 failures); no `skip`/`skipif`/`xfail` markers anywhere; no freelance tests beyond the two design indices.

## Step 7: Run Tests and Iterate — 2026-08-13T00:05:00.000Z

Clean 8-round parallel sweep achieved: all 8 rounds passed 66/66. Exit criterion met.

## Summary

**Iterations run:** 4 sweeps (1 initial + 3 after fixes; sweeps 2–3 were perturbed by host contention, sweep 4 was fully clean).

**Tests deleted:** None.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1329_school_accreditation_continuous/test_suite/test_02_self_study_ratings.py` — `TestEvidenceSegregation::test_officer_cannot_review_own_submission`: changed review payload from `{"decision": "APPROVE"}` to `{"decision": "APPROVED"}`. PRD §3.3 names the decision by its target state ("posting a `decision` that moves it `PENDING` → `APPROVED` or `PENDING` → `REJECTED`"), so `APPROVE` is not a PRD-faithful enum value; the implementation's `ERR_VALIDATION` (§2.5 enum rule) was correct and was masking the segregation-of-duties assertion the test exists to check (PRD §2.9/§2.1).

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1329_school_accreditation_continuous/workspace/implementation/routes/visits.py` — `confirm_visit`: moved the two overlap checks (same-campus and per-reviewer double-booking, both `ERR_TEMPORAL_WINDOW_VIOLATION`) ahead of the lead-reviewer-availability check (`ERR_REFERRIAL_INTEGRITY`). PRD §2.5 verbatim orders the families "then temporal-window rules (`ERR_TEMPORAL_WINDOW_VIOLATION`), then cross-entity referential integrity (`ERR_REFERENTIAL_INTEGRITY`)" with earlier families masking later ones; the implementation had the two families inverted. Fixed `test_campus_overlap_masks_unavailable_lead` and `test_reviewer_double_booking_masks_unavailable_lead`.

**Environmental note (no artifact change):** The recurring `test_visit_ending_at_confirmed_start_is_adjacent` / `test_clock_at_renewal_window_issues_renewal_invoice` failures were never assertion failures — they were setup-phase "API server could not be restarted" timeouts from the runner's fixed 15s per-test restart poll window, plus one mid-test connection reset. This host runs ~13 other benchmark pipelines concurrently (load spikes to 26); the failing port moved between sweeps and produced no restart logs, indicating transient spawn/poll stalls under load, not a task defect. A live GIVE-UP watcher during the final sweep captured zero events and all 528 (8 × 66) per-test restarts succeeded. Server boot measures 0.62s under moderate load; `start.sh` already guards pip install, storage is in-memory only, and no entity data is seeded.

**Final state:** 8/8 rounds × 66/66 tests passed. No skips, no weakened assertions, no PRD-silent additions.

## Step 8: Finalize PRD — 2026-08-13T00:12:00.000Z

PRD_FINALIZED.md is complete. Summary:

**Line counts / delta:** PRD.md 338 lines, PRD_FINALIZED.md 338 lines — 0% line-count delta; exactly one sentence revised inline (one line changed).

**Changes:**
- §3.3 (Self-Study Ratings, Evidence, and the Composite Index) — revise — pinned the evidence-review `decision` field to the exact enum values `APPROVED` or `REJECTED` (was: "posting a `decision` that moves it..." with values only implied by the target-state names) — `implementation/routes/evidence.py:13` (`DECISIONS = {"APPROVED", "REJECTED"}`) and `implementation/routes/evidence.py:59` (`as_enum(...)` → `ERR_VALIDATION` for any other value, e.g. `APPROVE`).

**Step 7 diff item with no PRD edit (and why):**
- `implementation/routes/visits.py` `confirm_visit` reordering — this was an implementation bug fix, not a PRD silence. PRD §2.5 already verbatim orders "then temporal-window rules (`ERR_TEMPORAL_WINDOW_VIOLATION`), then cross-entity referential integrity (`ERR_REFERENTIAL_INTEGRITY`)" with earlier families masking later ones; the implementation was inverted and Step 7 fixed it to match the PRD. Verified current `visits.py:170-218` runs both overlap checks (`ERR_TEMPORAL_WINDOW_VIOLATION`) before the lead-availability check (`ERR_REFERENTIAL_INTEGRITY`), matching existing PRD prose. Kept verbatim.

**Per-edit pre-edit search log:**

Edit 1 (§3.3 `decision` enum):
- (a) Subject: the allowed values of the `decision` request field on `POST /accreditation/evidence/{id}/review`, and how an out-of-set value is surfaced.
- (b) Impl paths enumerated and read/grepped: `implementation/routes/evidence.py` in full — line 13 (`DECISIONS` set, the only definition), line 59 (`as_enum` validation → `ERR_VALIDATION` 400 via `util.py:104-111`), line 76 (`item["review_status"] = decision` — the decision value is stored verbatim as the new `review_status`, so the enum values must equal the target state names `APPROVED`/`REJECTED`), lines 81-96 (resubmit path takes no `decision`; unaffected). Global greps across all of `implementation/`: `as_enum` callsites (`terms.py:227` outcome, `invoices.py:48` invoice_type, `standards.py:26` domain, `surveys.py:45` group, `visits.py:113` role_on_team, `goals.py:45` direction, `systems.py:35` system_type, `findings.py:37` severity) — none other touch a `decision` field; no occurrence of the verb form `APPROVE` anywhere in the implementation. The commission decision endpoint uses a separate `outcome` field whose three values PRD §3.2 already names. PRD cross-references checked: §2.5's generic rule that "an enum value outside its allowed set" yields `ERR_VALIDATION` (consistent — no need to restate the 400 here, matching the PRD's style for `severity`, `direction`, etc.), §2.9 SoD, and the §4 endpoint table row ("Approve or reject an evidence item" — descriptive, not value-pinning).
- (c) Wording adjustment: inserted "of `APPROVED` or `REJECTED`" into the existing sentence ("posting a `decision` of `APPROVED` or `REJECTED` that moves it `PENDING` → ..."), following the PRD's established inline enum style ("a `severity` of `COMMENDATION`, `RECOMMENDATION`, or `REQUIRED_ACTION`"). No claims added about validation ordering, error codes, or any other endpoint, so all enumerated paths remain accurately described.

## Step 9: Complete PRD — 2026-08-13T00:30:00.000Z

All edits are in place and verified. The file remains 338 lines (all changes are in-paragraph inserts/revisions; no new sections).

## Summary

**Source:** `PRD_FINALIZED.md` → `PRD_COMPLETED.md` at `/home/ubuntu/github/CodingPRD/tasks/task_1329_school_accreditation_continuous/workspace/PRD_COMPLETED.md`
**Line counts:** 338 → 338 (unchanged). **Char delta:** 53,529 → 57,082 (+3,553 chars).
**Counts:** 28 ambiguity-pins, 5 mismatch-revisions (33 changes total).

Note: no `test_helpers/` or `test_suite/` directories exist in this workspace, so implementation was the sole alignment target.

### Ambiguity-pins (insert/revise where PRD was silent)

- §2.3 — insert — ambiguity — out-of-range/non-integer `limit`/`offset` rejected with `ERR_VALIDATION` 400 — implementation/util.py:118-140
- §2.3 — insert — ambiguity — list endpoints accept optional exact-match query filters (`status`, `campus_id`, etc.); `total_count` reflects filtered set — implementation/routes/systems.py:54-59, ratings.py:92-100, and others
- §2.3 — insert — ambiguity — `has_more` is true exactly when `offset`+`limit` < `total_count` — implementation/response.py:29
- §2.4 — revise — ambiguity — `version` starts at 1 on creation (was "starts at its initial value") — implementation/util.py:153-159
- §2.5 — insert — ambiguity — stale-version (OCC) family placed in the priority order after SoD, before uniqueness — implementation/routes/ratings.py:49-67, goals.py:158-169, invoices.py:95-114
- §2.5 — insert — ambiguity — path-segment resources are existence-checked before body structural validation; body-referenced resources (e.g., `term_id` of a new rating) after — implementation/routes/ratings.py:21-46 vs terms.py:43-49
- §2.6 — revise — ambiguity — non-OCC endpoints ignore any supplied version field (was "do not accept a version field at all") — no version handling exists outside the three OCC endpoints
- §2.8 — insert — ambiguity — business stamps (`finalized_at`, `submitted_at`, `issued_at`) read the logical clock; audit stamps (`created_at`, `updated_at`, `api_request_timestamp`) use wall clock — implementation/routes/ratings.py:158, surveys.py:233, interim_reports.py:91, services.py:219, db.py:54-61
- §2.8 — insert — ambiguity — on auto-renewal with no fee schedule in effect, the term still enters `RENEWAL` and no invoice is issued — implementation/services.py:285-293
- §3.1 — insert — ambiguity — SINGLE_SCHOOL one-campus limit counts any existing campus row regardless of `campus_status` — implementation/routes/campuses.py:27-34
- §3.1 — insert — ambiguity — scope-in also recomputes `composite_index_pct` — implementation/routes/campuses.py:114-117
- §3.1 — insert — ambiguity — dashboard field definitions: `finalized_rating_count` = FINALIZED ratings under current term on IN_SCOPE campuses; `projected_index_pct` null when that set is empty or no current term — implementation/routes/systems.py:71-112
- §3.2 — insert — ambiguity — PREPARATION→SELF_STUDY coverage failure → `ERR_INVALID_STATE` — implementation/routes/terms.py:117-136
- §3.2 — insert — ambiguity — advance called in DECISION/INTERIM_MONITORING/RENEWAL/CLOSED → `ERR_INVALID_STATE` — implementation/routes/terms.py:214-217
- §3.2 — revise — ambiguity — stipulation-grant inadmissibility fails with `ERR_INVALID_STATE` (was "the request fails") — implementation/routes/terms.py:239-244
- §3.2 — revise — ambiguity — close requires the most recently issued RENEWAL_FEE invoice for the system to be PAID — implementation/routes/terms.py:273-284
- §3.3 — insert — ambiguity — nonexistent `term_id` → `ERR_NOT_FOUND`; creating a rating increments the owning term's `version`/`updated_at` — implementation/routes/ratings.py:37-38, 80-81
- §3.5 — revise — ambiguity — goal create also requires the named standard to exist (`ERR_REFERENTIAL_INTEGRITY`) — implementation/routes/goals.py:55-57
- §3.6 — insert — ambiguity — visit create enforces referential integrity: campus belongs to term's system, lead reviewer exists — implementation/routes/visits.py:54-66
- §3.6 — revise — ambiguity — confirm: lead reviewer not AVAILABLE → `ERR_REFERENTIAL_INTEGRITY` — implementation/routes/visits.py:212-218
- §3.6 — insert — ambiguity — cancelling a CONFIRMED visit at/after `starts_on` → `ERR_TEMPORAL_WINDOW_VIOLATION` — implementation/routes/visits.py:239-244
- §3.6 — insert — ambiguity — finding create requires standard existence; `follow_up_months` optional (recorded as given) for non-REQUIRED_ACTION severities — implementation/routes/findings.py:55-63
- §3.6 — insert — ambiguity — non-lead finding issue/supersede attempts → `ERR_FORBIDDEN` — implementation/routes/findings.py:111-114, 135-138
- §3.6 — insert — ambiguity — non-lead issue-report attempt → `ERR_FORBIDDEN` — implementation/routes/visits.py:268-271
- §3.6 — revise — ambiguity — action item's `description` is copied from the finding's `narrative`; `verified_by_user_id` starts null — implementation/routes/visits.py:287-295
- §3.6 — insert — ambiguity — overdue verify without a pending overdue submission → `ERR_INVALID_STATE` — implementation/routes/action_items.py:104-111
- §3.8 — revise — ambiguity — RENEWAL_FEE amount computed by the ANNUAL_FEE formula including credit-ledger adjustment; `billing_year` = calendar year of the renewal transition — implementation/services.py:182-207, 290
- §3.8 — insert — ambiguity — payments accepted only while invoice is ISSUED or PARTIALLY_PAID, else `ERR_INVALID_STATE` — implementation/routes/invoices.py:95-100

### Mismatch-revisions (PRD described different behavior than impl)

- §2.4 — revise — mismatch — "Three resource types are intentionally lighter" → "Four" (the sentence listed four entities; impl treats Standard, SurveyResponse, Payment, FeeSchedule as version-less) — implementation/routes/standards.py:45-47, surveys.py:235-236, invoices.py:121-122, fees.py:56-57
- §2.5 — revise — mismatch — error-family priority reordered: temporal-window and referential-integrity now precede segregation-of-duties (PRD had SoD before both; impl checks temporal before SoD in action-item verify and referential before SoD in assignment create) — implementation/routes/action_items.py:86-98, visits.py:114-129
- §3.5 — revise — mismatch — goal adopt: term-state failure is `ERR_INVALID_STATE`, not `ERR_THRESHOLD_NOT_MET` (only the two numeric conditions are threshold errors) — implementation/routes/goals.py:107-135
- §3.6 — revise — mismatch — overdue "rescue": PRD said a reviewer "may then verify it on the normal path"; impl rejects any verify of a SUBMITTED item once past `due_date` with `ERR_TEMPORAL_WINDOW_VIOLATION` — implementation/routes/action_items.py:84-91
- §3.8 — revise — mismatch — VISIT_FEE counts only visits in `REPORT_ISSUED` under the system's current term (PRD's billable set CONFIRMED/IN_FIELD/REPORT_DRAFT/REPORT_ISSUED and the read-time provisional-projection description do not exist in impl; removed) — implementation/services.py:174-181
