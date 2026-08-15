# Worklog — task_1973_behavioral_intervention_team_care_referral

## Step 1: Create Task Directory — 2026-08-15T04:05:00.000Z

Directory tasks/task_1973_behavioral_intervention_team_care_referral/ and workspace/ pre-created by the invoking pipeline (orchestrator instructed to skip index computation).

## Step 2: Generate Scaffold — 2026-08-15T05:00:00.000Z

All three scaffold artifacts are generated, linted clean, and verified non-empty.

## Files

- `/home/ubuntu/github/CodingPRD/tasks/task_1973_behavioral_intervention_team_care_referral/SCAFFOLD.yaml` (§1.0–§1.7, no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1973_behavioral_intervention_team_care_referral/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1973_behavioral_intervention_team_care_referral/SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

## Counts

| Element | Count |
|---|---|
| Entities | 12 (Student, StaffMember, ConcernReport, CareCase, RiskScoring, InterventionPlan, MandatedAssessment, LeaveDecision, ReentryEvaluation, FollowUpCheckin, DisclosureGrant, TrendReport) |
| State machines | 8 (CareCase cyclic with escalation re-triage + re-entry denial loops; InterventionPlan revision cycle; 6 smaller) |
| Calculations | 6 (2 dual-variant: triage_risk_score, trend_report_metrics) |
| Validations | 11 priority rows (auth → existence → OCC → state → privacy/segregation safety → constraint → temporal → referential) |
| Endpoints | 47 (flat topology under `/bit`, incl. `POST /bit/_clock/set_current_utc` with default 2026-08-01T00:00:00Z) |
| Errors | 35 |
| Roles | 7 (6 entity_backed:StaffMember + SystemAdmin opaque) |
| Concurrency rules | 2 OCC rules on CareCase.version (plan create, re-entry petition) |
| Queue A (§1.8) | 18 instances — 9 rules × 2, all with structured setup_api_calls/trigger/assert |
| Queue B (§1.9) | 41 active instances + 5 excluded_because stubs across all 9 guide sections |

Lint verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (747 calls scanned). No forbidden concurrency vocabulary anywhere.

## Notable design decisions

- **Archetype**: compliance/audit primary + workflow orchestration secondary; segregation-of-duties role model (plan approver ≠ drafter, outcome recorder ≠ orderer, leave decider ≠ requester, re-entry decider ≠ original leave decider) enforced by identity comparison with ERR_SEGREGATION_OF_DUTIES.
- **Rule differentiation highlights**: dual-variant calcs sit on different domains (per-case risk score INITIAL vs REASSESSMENT 60.0 vs 48.0 for identical inputs; TrendReport ENTRY_COHORT 50.0% vs ACTIVE_IN_WINDOW 66.7% on identical data); combinatorial formulas hit modes (a) weighted+threshold+IMMINENT-ratchet and (b) pinned category-share rounding order (residual 0.1 to last enum bucket); cascades are depth-4 (NOT_CLEARED → case → LeaveDecision → check-in cancellations) and depth-2 (IMMINENT crossing → auto-approved SAFETY_MINIMUM grants); temporal overlaps use half-open adjacency-allowed (disclosure grants) vs closed capacity-1 slot (assessments); compensating invariants conserve exactly-one-ACTIVE-plan and exactly-one-SCHEDULED-checkin per case.
- **All formula-derived asserts are pre-computed literals** (e.g., 60.0 HIGH at the >= 60 boundary vs 59.8 MODERATE; ratchet floors 32.1 to HIGH; closure at exactly 3 STABLE check-ins; grant expiry at exactly `now == expires_at`; check-in MISSED only strictly past due+1d).
- **Privacy gating** (validation priority 6) gives GET /bit/care-cases/{id} three observable outcomes — full / redacted five-field view / 403 — driven by role, assignment, and DisclosureGrant scope/expiry.

(Note: first Step 2 subagent spawn returned an off-topic hallucination without writing files; was discarded. A fresh subagent produced the above.)

## Step 3: Copy Shared Files — 2026-08-15T05:01:00.000Z

Copied ./INSTRUCTION.md to tasks/task_1973_behavioral_intervention_team_care_referral/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-15T05:15:00.000Z

PRD generated and verified. Summary below.

## Output

`/home/ubuntu/github/CodingPRD/tasks/task_1973_behavioral_intervention_team_care_referral/workspace/PRD.md` — 50,347 bytes, 291 lines, 6,911 words, 25 headings. Ends at §5 with no audit footer.

## Section structure

- **§1 Introduction** (2 paragraphs: campus CARE-team context + the segregation/privacy/logical-clock design tensions)
- **§2 Global Specifications** (10 subsections): 2.1 RBAC with per-role identity translation (6 entity-backed roles + opaque SystemAdmin) · 2.2 Response Structure (byte-verbatim from `section-2.2-response-structure.md`, verified by exact-string match) · 2.3 Pagination (limit 10/1/100, offset 0, created_at ascending, meta fields) · 2.4 Resource Identity/Timestamps/Versioning (all 12 entities, cascade-mutation semantics) · 2.5 Logical Clock & Expiry Sweeps (startup default `2026-08-01T00:00:00Z`, `to_iso8601`/`current_utc`, three sweeps) · 2.6 Numeric Precision (1-decimal round-half-up, whole-day cadence, null-before-first-scoring) · 2.7 Privacy Partitioning (role-based full view, redacted 5-field view, grant-mediated access) · 2.8 Segregation of Duties & Ownership (4 segregated pairs + 3 ownership rules) · 2.9 OCC (`expected_case_version`, 412, no race framing) · 2.10 Order of Validation (explicit 11-rank ladder with masking semantics)
- **§3 Business Logic** (8 subsections, lifecycle-timeline grouping): 3.1 Rosters & Concern Intake · 3.2 Risk Scoring & Triage Rubric · 3.3 Intervention Planning · 3.4 Follow-Up Cadence & Stability · 3.5 Mandated Assessment & Leave-Decision Cascade · 3.6 Leave, Re-Entry, Return · 3.7 Disclosure Grants · 3.8 Closure & Trend Reporting
- **§4 Endpoint table** — 47 rows (matches scaffold exactly), 4 columns only
- **§5 Error catalogue** — 35 rows, 2 columns only

## Coverage audit (all three Hard Contracts PASS)

- **Contract 1 Field-Name Coverage**: 77/77 required names present in backticks (all entity fields + endpoint inputs + query params + path params + common fields + clock output field), 0 missing — PASS
- **Contract 2 Rule Coverage**: 11/11 validation priorities expressed as an ordered ladder; 2/2 OCC rules (write endpoint + `expected_case_version` + `ERR_STALE_CASE_VERSION`/412); 36/36 state transitions with preconditions, error IDs, and side effects; 6/6 calculations in reconstruction-safe prose (weights 35/35/15/15, ×4 scale, 0.6/0.4 blend, 80/60/30 thresholds, IMMINENT ratchet, cadence 2/7/14/30 + 1-day grace + fixed 7-day re-entry, closure aggregate, both trend variants, pinned residual-to-last category rounding); 62 enum values, 35 error IDs in §2/§3 prose, all endpoint side effects, all field defaults/nullability; sibling branches (STABLE/ESCALATED, CLEARED/NOT_CLEARED, GRANT/DENY, APPROVED_WITH_CONDITIONS/DENIED, ENTRY_COHORT/ACTIVE_IN_WINDOW, INITIAL/REASSESSMENT) at equal density. 66/66 targeted rule anchors present — PASS
- **Contract 3 §3 Path Purity**: 523 backticked tokens scanned in §3, 0 slash-prefixed, 0 bare HTTP methods, 0 method+path combos — PASS
- **Style**: no pseudocode operators (`==`, `>=`, `+=`, `->`, boolean/set keywords) in prose; no fuzzy words (approximately/roughly/conservatively); no scaffold numbers beyond prose-translated constants

## Zero-Silence Rule adjudications

1. **start-review error ID**: the state-machine note mentions "ERR_INVALID_STATE" but no such ID exists in the error catalog, whose `ERR_REPORT_NOT_UNDER_REVIEW` condition explicitly covers "start-review requires SUBMITTED". Used `ERR_REPORT_NOT_UNDER_REVIEW` (catalog authoritative).
2. **Manual `LEAVE_OF_ABSENCE` PATCH**: scaffold says only ENROLLED↔WITHDRAWN may be set manually without naming an error; PRD states a direct PATCH to `LEAVE_OF_ABSENCE` is rejected with `ERR_VALIDATION` (the catalog's invalid-value bucket).
3. **Auto-grant `effective_from`**: the IMMINENT cascade specifies only `expires_at` = now+72h; PRD states the window opens at the moment of creation (minimal reading consistent with the half-open window contract).
4. **`ordered_at` slot interval**: the slot-occupation check references `ordered_at`, which is not a declared field; PRD phrases it as "the closed interval from the moment that earlier assessment was ordered through its `due_at`" without inventing a field name.
5. **`external_ref` uniqueness**: stated as a uniqueness rule with no error ID attached (scaffold declares no error for duplicates).

The forbidden files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, and no other `task_*` directory was read.

## Step 5: Generate Unit Tests — 2026-08-15T05:35:00.000Z

Generation complete and verified. Summary:

## Test infrastructure: `test_helpers/` (9 files)

- **`types.py`** — 12 entity TypedDicts (all carry `id/created_at/updated_at/version` per PRD §2.4; no append-only entities in this scaffold) + 15 status/enum classes (offices, categories, case/report/plan/assessment/decision/evaluation/checkin/grant statuses, roles).
- **`api_client.py`** — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (41 methods, including `set_clock` for the logical-clock test-driver).
- **`api_errors.py`** — `ApiErrorId` enum (36 errors) + HTTP status map registered via `set_error_http_status_map()`.
- **`assertions.py`** — per-entity `assert_*` shape checkers + `assert_case_read_redacted` (exactly the five PRD §2.7 fields).
- **`factories.py`** — one payload factory per creatable entity, input fields only.
- **`constants.py`** — rubric weights, tier thresholds (30/60/80), cadence days (2/7/14/30), grace day, 7-day re-entry horizon, 72h auto-grant TTL, closure minimum 3, 14-day assessment window, startup clock `2026-08-01T00:00:00Z`, pinned category order.
- **`test_users.py`** — shared `TEST_USERS` constants + per-instance `make_<role>_headers(user_id)` builders for all six entity-backed roles (opaque SystemAdmin constant is canonical).
- **`fixtures.py`** — composite chains: `setup_staff_group` (identity-threaded cast), intake (`submit_report`, `accept_report_and_get_case`, `setup_case_in_intake`), triage (`score_case`, `setup_case_triaged`), plan lifecycle (`draft_plan` with live OCC version fetch, `setup_case_plan_active`), check-ins (`get_scheduled_checkin`, `complete_stable`, `accumulate_stable_checkins`), closure (`setup_case_closable`, `setup_case_closed`), assessment/leave/re-entry tiers (`setup_case_in_mandated_assessment`, `setup_case_in_leave_decision`, `setup_case_on_leave`, `setup_reentry_pending`), grants (`request_grant`, `setup_approved_grant`), `set_clock`.

## Test suite: `test_suite/` (conftest + 8 files, 79 tests, 79 Design tags)

| File | Tests | Queues covered |
|---|---|---|
| test_01_risk_scoring_calculation.py | 8 | dual_variant (scoring), combinatorial (ratchet), boundary@60, corner moderate-band, corner computed-fields |
| test_02_concern_report_intake.py | 11 | cross-entity enrollment gate (×2), corner entities/intake/review/related-report/accept-link/reporter-ownership/immediate-consistency |
| test_03_intervention_plan_lifecycle.py | 8 | revision loop (×2), single-active-plan invariant (×2), plan-approve case-state gate (×2), open-plan gate, closed-case lockdown |
| test_04_checkin_cadence_and_stability.py | 11 | escalation re-triage cycle (×2), single-scheduled-checkin invariant (×2), closure boundary 2-vs-3 (×2), cadence constants, complete-twice idempotency, MISSED grace boundary (×2), assign-manager ownership |
| test_05_assessment_leave_reentry.py | 12 | NOT_CLEARED 4-link cascade (×2), assessment slot closed-interval (×2), expiry sweep, due-window ±1s (×2), evaluator==orderer, re-entry denial loop, conditions-required, reentry-already-pending, chair-cannot-decide |
| test_06_disclosure_privacy.py | 10 | IMMINENT auto-grant cascade (×2), half-open overlap pair (×2), window-shape-vs-overlap priority (×2), privacy 403, redacted five-field view, revoke-requires-APPROVED, grant expiry blocks read |
| test_07_trend_reporting.py | 7 | ENTRY_COHORT vs ACTIVE_IN_WINDOW variants (×2), category residual rounding order (×2), empty window, window_end boundary, window-invalid |
| test_08_security_occ_and_envelope.py | 12 | missing auth header, role gates (Reporter-scoring, CM-order), segregation identity-based, opaque SystemAdmin, 404, pagination envelope, OCC stale-version on plan + re-entry, state-vs-rubric priority pair (×2), scoring-mode-invalid |

**Queue totals:** A (Difficulty): 36 tests across 18/18 instances (≥2 each). B (Corner): 43 tests across 25/25 non-stub instances (≥1 each). The 5 `excluded_because:` stubs were not translated; all 5 cross-references resolve to real queue-A instances.

**Instances skipped for PRD-silence / unique-derivability failure: none.** Every instance's asserted rule is verbatim-covered in PRD prose (the PRD is unusually precise — it pins the rounding order, half-open vs closed interval semantics, the `>=` expiry boundary, the ratchet, and the validation ladder).

**Verification performed:** all files compile; `test_helpers` barrel imports cleanly; automated audit confirmed (a) ≥2/≥1 tag coverage for every instance, (b) zero dangling tags, (c) exactly one `Design:` line per test; a citation sweep extracted all 109 quoted docstring passages and verified each survives literal whitespace-normalized grep of `workspace/PRD.md`; all 26 asserted error IDs appear in PRD prose (not just the §5 table); zero `skip`/`skipif`/`xfail` markers anywhere.

## Step 6: Generate Implementation — 2026-08-15T05:35:00.000Z

Implementation complete and boot-verified. Summary:

## File structure
`tasks/task_1973_behavioral_intervention_team_care_referral/workspace/implementation/`
- `start.sh` — exec-launches `python3 app.py`, `PORT` env (default 10000), `0.0.0.0`, guarded `pip install` (no-op once Flask present) so per-test reboots don't contend
- `app.py` — Flask app factory, blueprint registration, envelope-wrapped error handlers (ApiError/404/405/500)
- `db.py` — in-memory `Store` singleton (12 dicts + logical clock + insertion seq); starts empty, zero seeding; ISO-8601 3-fractional-digit UTC serialization; `version` starts at 1, `touch()` bumps version + updated_at
- `errors.py` — ApiError + all 35 catalog error IDs
- `response.py` — exact envelope: `meta{api_request_id (req_*), api_request_timestamp}`, `response_type` object/array/error, list meta adds `limit/offset/total_count/has_more`
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (rank 1: 400 on missing/invalid role or unresolved entity-backed staff id; rank 2: 403 role-not-listed); SystemAdmin is opaque
- `routes/` — 13 blueprints (students, staff, reports, cases, scorings, plans, assessments, leave_decisions, reentries, checkins, grants, trends, clock) + shared util (pagination with limit default 10/min 1/max 100, offset default 0; created_at-ascending sort with insertion-seq tiebreak)
- `services/domain.py` — risk scoring, cadence, cascades, sweeps, privacy gating
- `services/trends.py` — trend metrics + pinned category distribution

## Endpoint coverage: 47/47
All routes from the endpoint table, including `POST /bit/_clock/set_current_utc` (logical clock pinned at `2026-08-01T00:00:00Z` at boot, never wall-clock).

## Key design decisions
- **Validation ladder (§2.10)** implemented literally per endpoint: auth → role → existence (path ids left-to-right, then body FKs incl. `case_manager_id` before accept's state check) → OCC (rank 4, before state) → state (409 family) → privacy (rank 6) → segregation/ownership (rank 7) → enrollment gate (rank 8) → field/constraint checks (rank 9, in the PRD's listed sub-order) → temporal windows (rank 10) → cross-reference (rank 11). PRD prose wins over scaffold precondition ordering (e.g., assessment create: evaluator-same 400 → due-window 422 → slot 409).
- **Risk scoring**: Decimal arithmetic, `base = 4*(.35s+.35o+.15a+.15sub)`, INITIAL = round-half-up(base,1); REASSESSMENT blends 0.6·base + 0.4·previous; thresholds ≥80/60/30; IMMINENT ratchet floors a drop at HIGH (score unchanged, tier floored).
- **IMMINENT auto-grants**: created APPROVED to COUNSELING_CENTER + CAMPUS_SAFETY, SAFETY_MINIMUM, 72h window, null requested/approved_by, `auto_approved: true` — only on crossing into IMMINENT, never on continuation.
- **Cascades**: accept links-or-creates case (existing case untouched, no version bump); plan approve supersedes prior ACTIVE + resets cadence (cancel SCHEDULED, schedule now+cadence[tier]); STABLE +1/successor, ESCALATED resets/supersedes/no successor/re-TRIAGED; NOT_CLEARED and assessment-expiry share one 4-link LEAVE_DECISION cascade (cancel check-ins); GRANT_LEAVE suspends plan + student LEAVE_OF_ABSENCE; re-entry approval reactivates SUSPENDED plan with `reentry_conditions`, resets stability, fixed now+7d check-in, student ENROLLED.
- **Sweeps** run only on clock advance, in PRD order: assessments → check-ins (fixpoint loop, successor anchored to missed `due_at` + cadence) → grants (`now >= expires_at`).
- **Privacy gating**: full view for BITChair/PrivacyOfficer/DeanOfStudents, assigned CaseManager, or CounselingEvaluator on a SCHEDULED/COMPLETED assessment; otherwise an APPROVED in-window (`effective_from <= now < expires_at`) grant for the caller's office — FULL_RECORD → full, else redacted 5-field view (`id, student_id, status, current_risk_tier, current_risk_score`); no path → `ERR_PRIVACY_SCOPE_INSUFFICIENT` 403.
- **Segregation of duties**: approver≠drafter, recorder==evaluator and ≠orderer, leave decider≠requester, re-entry decider≠original leave decider; ownership: plan submit by drafter only, check-in complete by assigned manager only, Reporter reads own reports only.
- **Trend reports**: ENTRY_COHORT vs ACTIVE_IN_WINDOW closed-interval input sets; category distribution with pinned rounding — first four categories rounded independently, WELLBEING_GENERAL takes the residual so shares sum to 100.0.

## Boot verification
Two fresh `PORT=<port> bash start.sh` boots, both killed afterward. Smoke suites passed end-to-end: (1) intake→triage→OCC-guarded plan (412 on stale version)→segregated approval→3×STABLE check-ins→closure gate (409, tier not LOW)→MISSED sweep with anchored successor→privacy 403→trend report; (2) IMMINENT auto-grants (exactly 2, none on continuation), ratchet (score 40.0 → tier HIGH), assessment order guards (400 evaluator-same, 422 due-window), NOT_CLEARED cascade, dean segregation on leave and re-entry, `ERR_CONDITIONS_REQUIRED`, plan reactivation with conditions, 72h grant expiry sweep. Store verified empty at boot — no seeding anywhere.

## Step 7: Run Tests and Iterate — 2026-08-15T06:10:00.000Z

## Summary

**Result: clean 8-round parallel sweep — 79/79 passed in every round (632/632 total), union of failures empty.**

### Iterations run
2 (iteration 1: 70/79 with 9 failures in the one round that survived an external kill; iteration 2: all 8 rounds green).

### Tests deleted
None. Every failing assertion traced to a verbatim PRD sentence; no PRD-silent or unique-derivability-collapsed tests were found.

### Fixes applied to `test_helpers/`
- `test_helpers/assertions.py` — added `assert_timestamp_instant(actual, expected)`, which parses both sides and compares instants. PRD §2.4 pins the three-fractional-digit serialization only for `created_at`/`updated_at` (§2.2 for `api_request_timestamp`); the string form of domain timestamps (`due_at`, `completed_at`, `closed_at`) is unpinned while their instant values are fully pinned (§3.3/§3.4/§3.8 cadence and stamping rules). Exact-string equality was failing on the implementation's PRD-faithful `.000Z` serialization (DEFAULT-VALUE/computed-field silence pattern on the serialization form); instant comparison keeps the covered rule at full strength.
- `test_helpers/__init__.py` — exported the new helper.

### Fixes applied to `test_suite/` (test bugs, not implementation bugs)
- `test_04_checkin_cadence_and_stability.py` — 8 exact-string timestamp assertions (lines 45, 123, 150, 152, 197, 224, 232, 279) converted to `assert_timestamp_instant`.
- `test_03_intervention_plan_lifecycle.py::test_second_draft_while_draft_open_rejected` — setup was `TRIAGED` → draft → case in `PLAN_DRAFTING`, where PRD §3.3's rank-5 state gate ("any other state besides `TRIAGED` or `PLAN_ACTIVE` yields `ERR_CASE_NOT_PLAN_ACTIVE`") correctly pre-empts the rank-9 open-plan exclusion. Fixed setup to reach the only state where `ERR_OPEN_PLAN_EXISTS` can fire: `PLAN_ACTIVE` with an open revision draft ("a case already `PLAN_ACTIVE` stays there").
- `test_05_assessment_leave_reentry.py::test_second_assessment_while_slot_occupied_rejected` — was asserting `ERR_ASSESSMENT_ALREADY_PENDING`, but ordering moves the case to `MANDATED_ASSESSMENT` (PRD §3.5) and every exit path completes/expires the assessment, so the rank-5 state gate always fires first; corrected expectation to `ERR_CASE_NOT_PLAN_ACTIVE`.
- `test_05_assessment_leave_reentry.py::test_second_petition_while_pending_rejected` — same ladder logic: filing moves the case `ON_LEAVE` → `REENTRY_REVIEW` (PRD §3.6), so the second filing trips the rank-5 state gate before the rank-9 pending-petition exclusion; corrected expectation to `ERR_CASE_NOT_ON_LEAVE`.

### Fixes applied to `implementation/`
- `start.sh` + entry point renamed `app.py` → `bit1973_server.py` (infrastructure only, zero behavior change). This host runs many benchmark pipelines concurrently; a neighboring pipeline's cleanup pattern-killed `app.py` processes, SIGTERMing 7 of 8 round-1 servers at boot (exit 143, external to the runner, which only SIGKILLs by port). The task-unique entry name made all 8 iteration-2 rounds survive on first attempt. The evaluator contract (`bash start.sh`, PORT env, 0.0.0.0, foreground) is unchanged.

No implementation logic was touched — the implementation was already PRD-faithful on all 9 substantive failures.

## Step 8: Finalize PRD — 2026-08-15T06:20:00.000Z

## Exit Summary

**Line counts / %-delta:** PRD.md = 291 lines; PRD_FINALIZED.md = 293 lines; delta = +2 lines (+0.69%). Two inline edits, no new sections, no deletions.

**Changes:**
- **§2.4** — insert — Added a paragraph pinning the serialization form of all non-common timestamp fields: every timestamp-valued field on any resource (`observed_at`, `due_at`, `completed_at`, `closed_at`, `decided_at`, `effective_from`, `expires_at`, `window_start`, `window_end`) is serialized as ISO 8601 UTC with exactly three fractional digits and a `Z` suffix (e.g. `2026-08-01T00:00:00.000Z`), client-supplied timestamps are normalized to that form, and the clock endpoint's `current_utc` uses it too — `implementation/db.py:50-52` (`iso_z`), `implementation/db.py:73-82` (`serialize` applies it to every `datetime`), `implementation/routes/clock.py:22`.
- **§2.10** — revise — Extended the closing "practical consequence" paragraph with one sentence making explicit that the state-advancing creation operations (plan drafting §3.3, assessment ordering §3.5, re-entry filing §3.6) move the case out of the gating state, so a second identical request fails at the rank-5 state gate (`ERR_CASE_NOT_PLAN_ACTIVE` / `ERR_CASE_NOT_ON_LEAVE`) before the rank-9 open-plan/pending-petition exclusions or the rank-10 slot-occupation rule are reached — `implementation/routes/plans.py:38-49` vs `66-74`, `implementation/routes/assessments.py:35-39` vs `67-77`, `implementation/routes/reentries.py:50-52` vs `62-69`.

**No edit for the `start.sh`/`app.py`→`bit1973_server.py` rename** — pure infrastructure, zero PRD relevance, as the diff guidance stated.

**Per-edit pre-edit search log:**

*Edit 1 (timestamp serialization form):*
- (a) Subject: wire form of timestamp fields other than `created_at`/`updated_at` (§2.4) and `api_request_timestamp` (§2.2).
- (b) Enumerated paths: `db.py:50-52` (`iso_z` canonical `%Y-%m-%dT%H:%M:%S.` + 3-digit ms + `Z`), `db.py:73-82` (`serialize` — the single serialization choke point for every record), `response.py:12`, `routes/clock.py:22`, `routes/reports.py:46-67` (`observed_at`), `routes/assessments.py:46-91,155` (`due_at`, `completed_at`), `routes/checkins.py:65,73`, `services/domain.py:83-96,111-128,182-185` (check-in `due_at`, auto-grant `effective_from`/`expires_at`), `routes/cases.py:93` (`closed_at`), `routes/leave_decisions.py:63` and `routes/reentries.py:152` (`decided_at`), `routes/trends.py:21-41` (`window_start`/`window_end` stored as datetimes and echoed). No alternative serializer exists anywhere.
- (c) Adjustment: instead of a per-field list that could silently omit a field, worded as a universal rule over "every timestamp-valued field carried on any resource" with the field list as illustrative examples, and explicitly extended to `current_utc` — matching the single shared `iso_z` helper on all enumerated paths.

*Edit 2 (rank-5 pre-empts rank-9/10 on state-advancing creates):*
- (a) Subject: ladder interaction between rank-5 state gates and the rank-9 open-plan/pending-petition plus rank-10 slot-occupation exclusions.
- (b) Enumerated paths: `routes/plans.py:29-49` (rank 4 → rank 5) vs `plans.py:66-74` (rank 9 `ERR_OPEN_PLAN_EXISTS`); `routes/plans.py:91-93` (`TRIAGED`→`PLAN_DRAFTING`, `PLAN_ACTIVE` stays — so `ERR_OPEN_PLAN_EXISTS` remains reachable from `PLAN_ACTIVE`, which the corrected test `test_second_draft_while_draft_open_rejected` exercises); `routes/assessments.py:35-39` (rank 5) vs `assessments.py:59-77` (rank 10 slot rule); `routes/reentries.py:41-52` (rank 4 → rank 5) vs `reentries.py:62-69` (rank 9 `ERR_REENTRY_ALREADY_PENDING`); cascade exits in `services/domain.py:134-155,161-193` confirming every exit from `MANDATED_ASSESSMENT` completes/expires the assessment.
- (c) Adjustment: worded as a *consequence* sentence appended to the existing "practical consequence" paragraph (no rank redefinition, no new errors, no reordering); explicitly notes the duplicate-resource errors remain observable while the case still sits in the gating state — required for consistency with the `PLAN_ACTIVE` revision-draft path at `plans.py:44-49,66-74`, where `ERR_OPEN_PLAN_EXISTS` does fire.

## Step 9: Complete PRD — 2026-08-15T06:40:00.000Z

## PRD_COMPLETED.md produced

**Source vs. output:** `PRD_FINALIZED.md` 293 lines / 51,799 chars → `PRD_COMPLETED.md` 293 lines / 54,545 chars (char-delta **+2,746**). 18 hunks, all single-line in-paragraph inserts/revisions; no new sections, no new paragraphs.

**Counts:** 15 ambiguity-pins, 4 mismatch-revisions (one §3.1 edit carries one of each).

**Changes:**

- §2.2 — insert — ambiguity — `api_request_timestamp` pinned as a logical-clock reading — response.py:9-13
- §2.3 — revise — ambiguity — pinned pagination rejections (`ERR_VALIDATION` 400 for non-integer / out-of-range limit/offset), `created_at` ties broken by creation order, `total_count` counts the filtered set pre-pagination — routes/util.py:33-45, db.py:85-86
- §2.4 — revise — ambiguity — `version` starts at **1** on creation — db.py:40
- §2.4 — insert — ambiguity — every server-minted timestamp (incl. workflow stamps and envelope meta) reads the §2.5 logical clock, never wall clock — db.py:33-52
- §2.5 — revise — ambiguity — clock endpoint accepts any parseable target, even behind the current reading, then runs sweeps — routes/clock.py:14-22
- §2.5 — insert — ambiguity — MISSED sweep iterates to a fixpoint: one large clock advance can retire a whole chain of past-anchored successors — services/domain.py:172-188
- §2.7 — insert — ambiguity — case **list** endpoint applies no per-record redaction or grant lookup; three-outcome gating governs only the single-case read — routes/cases.py:32-44
- §2.9 — revise — ambiguity — OCC fires on any inequality (not just "advanced past"); absent or non-integer `expected_case_version` is `ERR_VALIDATION` 400 at rank 9 — routes/plans.py:30-36,54-55; routes/reentries.py:42-48,57-58
- §2.10 rank 9 — insert — ambiguity — global pin: every narrative-named payload field is required (unless marked optional/defaulted/conditional) and free-text fields must be non-empty strings — all route files
- §3.1 — revise — **mismatch** — "campus-unique `external_ref`" softened to administrative convention; server applies no duplicate check — routes/students.py:13-28
- §3.1 — insert — ambiguity — PATCH restating the current value still increments `version`; PATCH omitting `enrollment_status` is a no-op — routes/students.py:43-55
- §3.1 — revise — ambiguity — report accept links to the **earliest-created** non-CLOSED case when several exist — routes/reports.py:137-145
- §3.2 — revise — **mismatch** — scoring state gate is mode-agnostic (`INTAKE` or `TRIAGED` for either mode); INITIAL-on-TRIAGED and REASSESSMENT-on-INTAKE fail as `ERR_SCORING_MODE_INVALID` (400), not `ERR_CASE_NOT_TRIAGEABLE` (409) — routes/scorings.py:31-68
- §3.2 — insert — ambiguity — auto-grant `purpose` pinned to the fixed string `Auto-approved safety disclosure on IMMINENT risk tier crossing` — services/domain.py:123
- §3.4 — revise — ambiguity — check-in completion accepted at any time while `SCHEDULED` (early, at, or after `due_at`); no lateness rejection, overdue handling belongs solely to the MISSED sweep — routes/checkins.py:41-67
- §3.6 — revise — ambiguity — petition's `leave_decision_id` is the most recently created `GRANTED` decision; `conditions` created null — routes/reentries.py:18-27,71-86
- §3.6 — revise — ambiguity — re-entry denial leaves `conditions` null — routes/reentries.py:175-179
- §3.7 — revise — **mismatch** — deny requires a non-empty `rationale` (`ERR_VALIDATION` otherwise) but does **not** persist it; the grant record has no rationale field — routes/grants.py:120-131
- §3.8 — revise — **mismatch** — `avg_days_to_close` is the exact elapsed span in fractional days (seconds ÷ 86,400), not a whole-day span — services/trends.py:33-37

**Notable confirmations requiring no change:** endpoint/role table matches all 13 blueprints exactly; the §2.10 rank ladder matches every route's check ordering (existence → OCC → state → fields → temporal → cross-ref); REASSESSMENT blend uses the previous scoring's recorded (rounded) score; privacy-view matrix (incl. CounselingEvaluator limited to `SCHEDULED`/`COMPLETED`) matches; grant overlap is half-open intersection among `REQUESTED`/`APPROVED`; trend-report membership, closure rate, and residual rounding order all match services/trends.py.
