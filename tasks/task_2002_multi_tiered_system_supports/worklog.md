# Worklog — task_2002_multi_tiered_system_supports

## Step 1: Create task directory — 2026-08-15T00:00:00.000Z

Pre-completed by pipeline launcher: `tasks/task_2002_multi_tiered_system_supports/` and `workspace/` already exist. Orchestrator starts at Step 2.

## Step 2: Generate scaffold — 2026-08-15T06:39:00.000Z

All three files written and lint-clean. Final report:

---

**Task 2002 MTSS/RTI scaffold complete**

**Files written:**
- `/home/ubuntu/github/CodingPRD/tasks/task_2002_multi_tiered_system_supports/SCAFFOLD.yaml` (1619 lines) — §1.0–§1.7, no forbidden keys
- `/home/ubuntu/github/CodingPRD/tasks/task_2002_multi_tiered_system_supports/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2016 lines) — single top-level `scaffold_difficulty_design:` key, 9 rule blocks × 2 instances = 18 total
- `/home/ubuntu/github/CodingPRD/tasks/task_2002_multi_tiered_system_supports/SCAFFOLD_CORNER_DESIGN.yaml` (1569 lines) — single top-level `scaffold_corner_design:` key, 32 instances (some as `excluded_because:` stubs referencing §1.8)

**Design choices:**
- **Archetype**: `quota_allocation` (interventionist weekly-minute capacity) + `compliance_audit` (fidelity, sped-referral cooling-off)
- **Layers**: rate_threshold_triggers, cascading_side_effects, derived_field_reconciliation, optimistic_concurrency
- **14 entities** (District, School, ScreeningWindow, BenchmarkCutPoint, Student, ScreeningScore, InterventionCatalogEntry, Interventionist, StudentPlan, ProgressProbe, InterventionSession, TierMovement, TeamMeeting, SpedReferral) — hierarchical topology under `/districts/...`
- **6 state machines** including cyclic StudentPlan (ACTIVE↔PAUSED) and replaceable-sibling TierMovement (PROPOSED→SUPERSEDED) for Rule 3
- **7 calculations** including dual-variant pairs (risk_band CUT_SCORE vs PERCENTILE; slope_decision SLOPE vs ENDPOINT) and three combinatorial modes (multi-input eligibility / nested-rounding fidelity / circular-looking subgroup outcome index)
- **12 validation priorities** with category pairs (state vs business_temporal; business_constraint vs business_fiscal) for Rule 5
- **2 OCC concurrency rules** on Student.version (ratify) and StudentPlan.version (exit)
- **25 error codes**, all triggerable

**Lint verdict (verbatim):**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
Coverage: 85 endpoints, 14 entities, 18 §1.8 instances, 27 §1.9 active instances (32 total), 720 calls scanned. Zero unbound `${var}` placeholders; zero forbidden vocabulary ("simultaneously"/"race"/"in parallel"); `Any` pseudo-role replaced with explicit 7-role list on all GET endpoints.

## Step 3: Copy shared files — 2026-08-15T06:40:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2002_multi_tiered_system_supports/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-15T06:59:00.000Z

The PRD is generated and all three hard contracts pass. Final report:

## Done

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2002_multi_tiered_system_supports/workspace/PRD.md` (343 lines) — generated from `SCAFFOLD.yaml` per the `prd-bench-doc-generator` skill. The two forbidden design-index files were never opened.

**Document skeleton (domain-derived, not template-copied):**
- §1: 2-paragraph introduction (business context → system scope/approval chain)
- §2: 10 subsections — 2.1 RBAC (all 8 roles with identity semantics: `InterventionistRole` entity-backed, six others + `Any` opaque), 2.2 response envelope (verified **byte-identical** to `section-2.2-response-structure.md`), 2.3 pagination, 2.4 hierarchical addressing + flat aliases + left-to-right 404 order, 2.5 the validation pipeline (all 12 priorities in explicit order with masking consequences), 2.6 common resource properties (incl. explicit absence of `updated_at`/`version` on the 4 append-only/immutable entities), 2.7 logical clock (default `2026-08-01T00:00:00Z`, no wall-clock fallback), 2.8 capacity ledger (inclusive boundary), 2.9 OCC, 2.10 per-calculation rounding discipline
- §3: 9 subsections organized chronologically along the program pipeline (setup → staffing → screening → movement proposals → plan activation → fidelity/probes → meetings/ratification → plan endings → referral + outcome reporting). Both calculation variants (cut-score/percentile, slope/endpoint) rendered as reconstructible prose; all constants embedded (12 weeks, 80%, 60 days, 8/4 probes, trailing 4, 30-student/5-point penalty, 10th/25th percentiles, 7/14-day cadence)
- §4: 4-column table, all **85/85 endpoints** present (verified by diff against scaffold)
- §5: 2-column table, all **25 error IDs**, each also mentioned in §1–§3 prose

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 59 required, 59 present, 0 missing
- endpoints[].request_body: 47 required, 47 present, 0 missing
- endpoints[].query_params: 11 required, 11 present, 0 missing
- endpoints[].path_params: 15 required, 15 present, 0 missing
Status: PASS
```
```
Rule coverage check:
- validations[] with priority: 12 checked, 12 expressed in ordered prose (§2.5), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (ratify + expected_student_version + ERR_STALE_VERSION/412; exit + expected_plan_version + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: 25 checked (5 ScreeningWindow/Plan/Meeting/Referral machines + TierMovement), 25 fully expressed, 0 missing
- calculations[]: 7 checked, 7 fully expressed (both variants of risk_band and slope_decision, tier-movement eligibility matrix with all 3 branches at equal density, per-week-then-average fidelity, pinned-order subgroup index, inclusive capacity, 1-indexed aimline), 0 missing
- validations[] conditions: 12 checked, 12 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed (version increments, ledger release/re-commit, auto-propose on scoring, EXIT_MOVED/EXIT_SPED_REFERRAL cascades, IEP append, counter dynamics), 0 missing
- entities[].fields[] structured content: all defaults/initials reconstructible (12, 80, [], TIER_1, 0, true, 100, 0, nulls), 0 missing
- sibling-branch symmetry: tier-eligibility TIER_1/2/3 branches, EXIT_RESPONSIVE/EXIT_NO_PROGRESS, ELIGIBLE/NOT_ELIGIBLE, dual WITHDRAWN sources — all equal density, 0 asymmetric
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 402
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional scans: no fuzzy/approximating words, no operator pseudocode outside backticks (the single "NOT" hit is the scaffold's own normative "MUST NOT" clock language in §2.7), PRD ends at §5 with no audit footer. One post-draft repair was applied: the `grade_level` 0–12 range was added to the cut-point definition in §3.3.

## Step 5: Generate unit tests — 2026-08-15T07:51:00.000Z

Generation complete. Summary of what was produced and the key adjudication decisions:

## Output

**`/home/ubuntu/github/CodingPRD/tasks/task_2002_multi_tiered_system_supports/test_helpers/`** — 9 files: `types.py` (14 TypedDicts with correct `common_fields` branching — cut points/scores/probes/sessions omit `updated_at`/`version`), `api_client.py` (one method per PRD §4 endpoint, including flat aliases and the test clock), `api_errors.py` (all 25 error IDs + HTTP map registered via `set_error_http_status_map`), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (`make_interventionist_role_headers(entity_id)` for the entity-backed role), `fixtures.py` (screening→ratify chains, `setup_active_plan`, clock-stepped probe drivers, `probe_until_sped_referral`, the ~200-call `build_outcome_report_cohort`), `__init__.py` barrel.

**`/home/ubuntu/github/CodingPRD/tasks/task_2002_multi_tiered_system_supports/test_suite/`** — `conftest.py` + 15 test files, **62 tagged test functions (71 collected with parametrization)**.

## Coverage audit (verified by script)

- Queue A: 17/18 difficulty instances covered with ≥2 tests each.
- Queue B: all 25 non-stub corner instances covered ≥1; all 5 `excluded_because:` stubs verified to resolve and not translated.
- Every test's docstring ends with exactly one `Design:` line resolving to a real instance; every quoted PRD sentence passes a whitespace-normalized literal grep of PRD.md; no skip/xfail markers; pyflakes clean; pytest collects.

## Deliberate skip (gap left as a gap)

**`Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_score_creation`** — skipped under the PRD-first filter. The instance asserts ERR_INVALID_STATE for a score POSTed to a CLOSED window past its date range, but the PRD contradicts this: §3.3 states "Recording is only allowed while the window's `status` is `OPEN` … otherwise the submission is rejected with `ERR_WINDOW_NOT_OPEN` (HTTP 409)", and §2.5's own observable-consequence example says "a score submitted to a window that is not open reports `ERR_WINDOW_NOT_OPEN` even if no matching cut point exists." A PRD-faithful implementer returns ERR_WINDOW_NOT_OPEN, so the instance fails unique derivability. (The sibling instance `business_constraint_vs_business_fiscal_on_plan_create` IS translated, because PRD §3.5 explicitly states "The capacity check of §2.8 runs after matching, per the pipeline order.")

## Robustness decisions worth noting

- **Single-probe slope ambiguity**: the PRD's least-squares slope rule is undefined for a one-probe trailing window, so any counter/threshold assertion depending on probe #1's decision is non-derivable. Referral-cascade tests use `probe_until_sped_referral` (probe until the referral appears, never probing an exited plan) so both readings converge to the same asserted final state; the TIER_2→TIER_3 progress-monitoring test records 5 flat probes so the "four most recent NON_RESPONSIVE" all have ≥2-point windows; the counter test asserts the RESPONSIVE-probe reset to exactly 0.
- **OCC exit test** was restructured so the stale `expected_plan_version` is the only failing precondition (ACTIVE plan, full EXIT_RESPONSIVE evidence, version advanced via pause/resume) — making ERR_STALE_VERSION uniquely derivable rather than racing ERR_INVALID_STATE.
- All version-bearing writes in fixtures re-read the entity version immediately before the call (PRD §2.9 threading), and interventionist-gated calls (probes/sessions) always use `make_interventionist_role_headers(interventionist["id"])`.

## Step 6: Generate implementation — 2026-08-15T07:51:00.000Z

Implementation complete. Final report:

## What was built

A complete Python + Flask implementation of the MTSS/RTI benchmark task at `/home/ubuntu/github/CodingPRD/tasks/task_2002_multi_tiered_system_supports/workspace/implementation/`:

- **`start.sh`** (executable) — guarded dependency install (`if ! python3 -c "import flask"`) then `exec python3 app.py`; binds `0.0.0.0:$PORT` (default 10000), foreground
- **`app.py`** — blueprint registration, error handlers, a request-scoped `RLock` (before/teardown) serializing multi-step cascades
- **`db.py`** — in-memory store, starts empty every boot (verified: boot 1 created 1 district, boot 2 showed `total_count: 0`); logical clock defaults to `2026-08-01T00:00:00Z` with no wall-clock fallback
- **`errors.py` / `response.py` / `clock.py` / `middleware.py`** — exact scaffold error catalog, the `meta`/`response_type`/`data` envelope with `limit`/`offset`/`total_count`/`has_more` pagination, ISO-8601 3-fractional-digit timestamps, `X-User-ID`/`X-User-Role` auth (7 roles; `Any` treated as the documentation marker the PRD says it is), body validation (`ERR_INVALID_REQUEST`), OCC helpers
- **`services.py`** — hierarchical left-to-right path resolution, window auto-transition refresh (SCHEDULED→OPEN at `opens_on`, OPEN→CLOSED after `closes_on`, inclusive dates), cut-score risk bands, aimline (pinned baseline/goal at plan start, round-half-up, 8/4 probe totals), slope decision (exact `Fraction` least-squares, trailing ≤4 probes, `b >= a` → RESPONSIVE), per-week-then-average fidelity with floor at both steps, subgroup outcome index (penalty → floor → max(0)), capacity ledger, ratify/referral cascades
- **`routes/`** — 10 modules covering all 84 registered routes: nested CRUD/actions, all 13 flat read aliases, all 18 flat list helpers, outcome report, and `POST /_clock/set_current_utc`

## Verification

- Booted cleanly via `bash start.sh`; 84 routes registered
- Two smoke suites (153 assertions total) all pass, covering: auth/RBAC failures, envelope/pagination shape, window lifecycle including clock-driven auto-open/close, score guards ordering (`ERR_WINDOW_NOT_OPEN` 409 before `ERR_CUT_POINT_NOT_DEFINED` 422), cut-point validation, plan creation (OCC 412, catalog mismatch 422, inclusive capacity boundary), pause/resume/exit/cancel state gates, probe cadence/aimline values (e.g. 56.25→56), slope decisions, unresponsiveness counter, auto-referral cascade at the district minimum (plan → EXIT_SPED_REFERRAL, minutes released), ratification cascade (ACTIVE mismatched plans → EXIT_MOVED, student version bump, stale re-exit → 412), supersession, minute-blocking while proposals pending, referral lifecycle (consent +60 days, IEP append on ELIGIBLE), per-week-then-average fidelity (58 not the naive 60), and outcome-report small-cohort penalty (moved-up ELL cohort → 95)

## Judgment calls worth flagging

- **OCC placement**: `expected_*_version` checked after existence but before state/business checks, per PRD §2.9's cascade examples (stale exit on an EXIT_MOVED plan must yield 412, not 409)
- **Meeting minute precondition**: implemented as "no PROPOSED movements for any student of the school" per the PRD §3.7 sentence (the scaffold's literal parenthetical is vacuous since `decided_at_meeting_id` is null while PROPOSED)
- **InterventionistRole ownership**: plan-scoped writes (probes, sessions, pause, resume) require `X-User-ID == plan.interventionist_id`, mismatch → 403 `ERR_INSUFFICIENT_PERMISSIONS` (the only 403 in the catalog)
- **Missing 404 IDs** for flat aliases of append-only entities (probe/session/score/cut-point) fall back to `ERR_INVALID_REQUEST` 404, since the catalog defines no `ERR_{PROBE,SESSION,SCORE,CUTPOINT}_NOT_FOUND`

## Step 7: Test/fix iteration loop — 2026-08-15T08:05:00.000Z

**Iteration 1 sweep**: 68/71 passed in each of 8 parallel rounds; 3 tests failed deterministically in all rounds (no flakiness).

Diagnoses and fixes (all test-side; implementation was PRD-faithful in every case):

1. `test_04::test_score_recording_rejected_outside_window_range` — TEST SETUP BUG (STEP 2). Case 3 created the `manual` window while the clock (left at 2026-09-01 by Case 2) was already past its `closes_on`, then moved the clock backward to 2026-08-10. The PRD §3.3 lifecycle is forward-only (SCHEDULED→OPEN→CLOSED→SCORED); the window was already CLOSED and could not be manually closed ("Only an OPEN window can be manually closed" 409). Fix: set the clock into the window range BEFORE creating the window. The asserted rule (recording against a non-OPEN window → ERR_WINDOW_NOT_OPEN 409) is PRD-verbatim and unchanged.

2. `test_12::test_ratify_rejected_once_meeting_minuted` — PARTIAL COVERAGE (STEP 1c). The assertion "minute succeeds while a PROPOSED movement exists for a student of the school" fails unique derivability: "no `PROPOSED` rows remain before it" (PRD §3.7) admits both the school-scoped reading (implemented; gives the ERR_INVALID_STATE clause teeth) and the vacuous submission-scoped reading. The covered assertion (ratify at a non-CONVENED meeting → ERR_INVALID_STATE, verbatim in §3.7's three preconditions) was kept by restructuring: ratify the movement, minute the now-quorate meeting, then re-attempt ratify → ERR_INVALID_STATE (meeting-state and movement-state preconditions both fail with the same error id).

3. `test_14::test_ratify_with_stale_student_version_rejected` — TEST BUG (STEP 2). `validate_success(resp)` defaulted to 200 for `propose_tier_movement`, but PRD §4 verbatim requires 201 for resource-creating operations ("Operations that create a new resource return a `201 Created` status code"); suite convention (test_11) already passes 201. Fix: `validate_success(..., 201)`.

No tests deleted. No implementation changes.

**Iteration 2 sweep**: all 8 parallel rounds passed 71/71. Clean — loop exits.

---

Subagent final summary (verbatim):

Clean 8-round sweep: all 8 rounds passed 71/71.

## Summary

- **Iterations run**: 2 (iteration 1: 68/71 × 8 rounds, 3 deterministic failures; iteration 2: 71/71 × 8 rounds, zero failures, no flakiness).

- **Tests deleted**: none.

- **Fixes applied to `test_suite/`** (all three failures were test-side; no `test_helpers/` changes were needed):
  - `/home/ubuntu/github/CodingPRD/tasks/task_2002_multi_tiered_system_supports/test_suite/test_04_screening_windows_and_scores.py` — `test_score_recording_rejected_outside_window_range`: Case 3 setup created the window while the logical clock (left at 2026-09-01 by Case 2) was already past `closes_on`, then wound the clock backward — inconsistent with PRD §3.3's forward-only lifecycle (SCHEDULED→OPEN→CLOSED→SCORED), so the manual close correctly got ERR_INVALID_STATE. Fix: moved `set_clock("2026-08-10T00:00:00Z")` before window creation. The asserted rule (non-OPEN window → ERR_WINDOW_NOT_OPEN 409) is PRD-verbatim and untouched.
  - `/home/ubuntu/github/CodingPRD/tasks/task_2002_multi_tiered_system_supports/test_suite/test_12_team_meetings.py` — `test_ratify_rejected_once_meeting_minuted`: partial-coverage repair per STEP 1c. The "minute succeeds while a PROPOSED movement exists" assertion fails unique derivability — "no `PROPOSED` rows remain before it" (PRD §3.7) admits both the school-scoped reading (implemented) and the vacuous submission-scoped reading. Restructured to keep only the covered assertion: ratify the movement, minute the meeting (now legitimate under both readings), then re-attempt ratify → ERR_INVALID_STATE 409 (verbatim-covered by §3.7's three preconditions).
  - `/home/ubuntu/github/CodingPRD/tasks/task_2002_multi_tiered_system_supports/test_suite/test_14_optimistic_concurrency.py` — `test_ratify_with_stale_student_version_rejected`: `validate_success(resp)` defaulted to expecting 200 for `propose_tier_movement`; PRD §4 verbatim requires 201 for resource creation ("Operations that create a new resource return a `201 Created` status code"), matching suite convention in test_11. Fix: `validate_success(..., 201)`.

- **Fixes applied to `implementation/`**: none — the implementation was PRD-faithful in all three cases (forward-only window lifecycle, school-scoped minute gate, 201-on-create).

## Step 8: Finalize PRD — 2026-08-15T08:20:00.000Z

The diff is exactly the four intended single-paragraph revisions. Task complete.

## Summary

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_2002_multi_tiered_system_supports/workspace/PRD_FINALIZED.md`

**Line counts / delta:** PRD.md 343 lines → PRD_FINALIZED.md 343 lines (0.0% line delta; 4 paragraphs revised inline, no sections added or removed).

### Changes (one bullet per edit)

- **§2.1** — revise — pinned that an `InterventionistRole` caller performing a plan-scoped write (record probe, record session, pause, resume) must have `X-User-ID == plan.interventionist_id`, mismatch → `ERR_INSUFFICIENT_PERMISSIONS` 403 — `implementation/routes/plans.py:34-39` (`_check_plan_ownership`), call sites plans.py:156, 178, 270, 336.
- **§2.4** — revise — pinned that the flat read aliases for the four append-only/immutable leaf resources (cut point, screening score, probe, session) reject an unresolvable identifier with `ERR_INVALID_REQUEST` at HTTP 404 (rather than its usual 400), while every other flat alias keeps its dedicated `ERR_*_NOT_FOUND` — `implementation/routes/windows.py:234,322`, `implementation/routes/plans.py:429,438`.
- **§2.9** — revise — pinned that the optimistic-concurrency version check runs after path and body-reference existence resolution and before state preconditions and business rules (a dual failure reports `ERR_STALE_VERSION`) — `implementation/routes/plans.py:88,157,179,203,240`, `implementation/routes/movements.py:100`, `implementation/routes/meetings.py:100`.
- **§3.7** — revise — pinned the minute gate's scope: a meeting may be `MINUTED` only when no `PROPOSED` movement remains for any student of the meeting's school (replacing the under-determined "submitted to a meeting" phrasing) — `implementation/routes/meetings.py:145-150`.

### Step-7 items judged to need no edit

- **test_04 (window lifecycle clock fix):** pure test-fixture bug; PRD §3.3/§2.7 already pin the forward-only SCHEDULED→OPEN→CLOSED→SCORED lifecycle and §2.5 pins state-precondition `ERR_INVALID_STATE`. Implementation (`refresh_window_status`, services.py:341-353; close gate windows.py:85-86) is PRD-faithful.
- **test_14 (201 on `propose_tier_movement`):** PRD §4 verbatim already requires 201 for resource creation; movements.py:104 conforms. Pure test bug.

### Per-edit pre-edit search log (NO-NEW-MISMATCH RULE)

1. **§2.1 ownership** — (a) subject: which operations enforce interventionist ownership and the mismatch error. (b) enumerated: grep for `_check_plan_ownership` found exactly 4 call sites (pause 156, resume 178, probe 270, session 336) — also exactly the four endpoints authorizing `InterventionistRole` in the §4 table; all reads use `require_role(*ALL_ROLES)` with no ownership check; exit/cancel are TeamLead-only so no InterventionistRole path exists. (c) wording lists the four writes explicitly instead of a blanket "any plan operation," so reads (no ownership check) are not mis-described.
2. **§2.4 flat-alias 404** — (a) subject: error identity for flat aliases lacking a dedicated NOT_FOUND code. (b) enumerated all 13 flat read aliases and 18 flat list helpers across districts/students/windows/catalog/interventionists/plans/movements/meetings/referrals routes: dedicated codes everywhere except the four leaf aliases (cut point/score/probe/session → `ERR_INVALID_REQUEST` 404); no flat list helper is keyed by a leaf id. Also noted app.py:18-30 catch-all handlers use `ERR_INVALID_REQUEST` for unmatched routes — outside the PRD's endpoint surface, deliberately left unpinned. (c) added "carrying HTTP status 404 for this case rather than its usual 400" to stay consistent with the §5 catalog row (`ERR_INVALID_REQUEST` → 400) instead of silently contradicting it.
3. **§2.9 OCC placement** — (a) subject: version-check ordering within the §2.5 pipeline. (b) enumerated all 7 OCC call sites (grep `_check_plan_occ`/`_check_student_occ`): create_plan (after path + body-FK existence, before matching/capacity), pause/resume (after resolve + ownership, before state), exit/cancel (after resolve, before state), propose (after resolve_student, before eligibility), ratify (after meeting + movement body-ref existence, before the three state preconditions). (c) chose "after path and body-reference existence resolution and before state preconditions and business rules" rather than "between §2.5 stages three and four," because create_plan runs the check after stage-4 body references; the sentence is deliberately silent on ownership-vs-version ordering (pause/resume run ownership first), so no enumerated path is mis-described. Consistent with §2.9's existing EXIT_MOVED 412 example.
4. **§3.7 minute gate** — (a) subject: which unresolved movements block minuting. (b) enumerated: minute gate meetings.py:145-150 (school-scoped scan over all movements); PROPOSED-exit paths (propose_movement supersession services.py:475-478, ratify services.py:506 + cascade supersession 520-523, reject meetings.py:132); the per-student ratify freshness precondition (meetings.py:106-114) already pinned verbatim in §3.7's preceding paragraph and untouched. (c) replaced "submitted to a meeting" (movements are never bound to a meeting pre-ratification — `decided_at_meeting_id` stays null) with "proposed for students of the meeting's school," matching the impl scan exactly and removing the phantom submission concept.

## Step 9: Complete PRD — 2026-08-15T08:50:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_2002_multi_tiered_system_supports/workspace/PRD_COMPLETED.md` written as a minimal patch over `PRD_FINALIZED.md`.

## Summary

**Source vs output:** `PRD_FINALIZED.md` 343 lines / 54,621 chars → `PRD_COMPLETED.md` 343 lines / 59,943 chars (char-delta **+5,322**; line count unchanged — all edits are in-paragraph inserts/revisions, no new sections).

**Counts:** 21 edits total — **19 ambiguity-pins, 2 mismatch-revisions** (one pure mismatch: unresponsiveness-counter reset scope; one default-ordering contradiction: probe/session list ordering vs §2.3 default).

**Changes (section — insert|revise — ambiguity|mismatch — what — impl ref):**

- §2.1 — insert — ambiguity — unrecognized `X-User-Role` value (incl. `Any`) counts as malformed → `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` — middleware.py:45
- §2.1 — insert — ambiguity — interventionist ownership check positioned after path resolution, before version/state/business checks (403 masks stale version/wrong state) — routes/plans.py:34-39, call order at 155-158
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST` 400 — middleware.py:224-246
- §2.3 — insert — ambiguity — same-timestamp ordering tie-broken by creation (insertion) order — middleware.py:252-254
- §2.3 — insert — ambiguity — `total_count` = post-filter/pre-pagination count; `has_more` ⟺ `offset+limit < total_count` — response.py:27-34
- §2.4 — insert — ambiguity — flat collection helpers with unresolvable parent `{id}` → parent's dedicated `ERR_*_NOT_FOUND` 404 — e.g. routes/students.py:85-91
- §2.5 — revise — ambiguity — body-reference stage generalized to score `student_id` (→`ERR_STUDENT_NOT_FOUND`, before window-open rule) and ratify/reject `movement_id` (→`ERR_MOVEMENT_NOT_FOUND`, incl. cross-school) — routes/windows.py:169-171, routes/meetings.py:78-87
- §2.5 — revise — ambiguity — explicit `null` counts as missing; unknown body fields rejected; non-object JSON body rejected; integral floats (5.0) accepted as integers — middleware.py:63-116
- §2.6 — insert — ambiguity — `version` starts at 1 at creation — middleware.py:197-206
- §2.7 — insert — ambiguity — missing/non-string/unparseable `to_iso8601` → `ERR_INVALID_REQUEST` 400 — routes/reports.py:31-43
- §3.1 — insert — ambiguity — student `grade_level` outside 0–12 → `ERR_INVALID_REQUEST` 400 — routes/students.py:27-28
- §3.1 — insert — ambiguity — catalog `is_active` filter accepts `true`/`false` case-insensitively; other values → 400 — routes/catalog.py:68-75
- §3.3 — insert — ambiguity — automatic window transitions apply at creation (born `OPEN`/`CLOSED`); manual close only from `OPEN`, else `ERR_INVALID_STATE` — routes/windows.py:50, 85-86; services.py:341-353
- §3.3 — insert — ambiguity — multiple matching cut points: most recently defined governs — services.py:367-378
- §3.3 — revise — ambiguity — scoring auto-proposal scoped to latest band *within the window being scored*; auto-proposals carry server rationale, supersede, bump student version; "most recently SCORED window" = most recent by scoring action — routes/windows.py:100-123, services.py:390-398
- §3.4 — insert — ambiguity — TIER_1 `to_tier` ≠ indicated band → `ERR_INVALID_TIER_MOVE` 422 — routes/movements.py:38-41
- §3.4 — insert — ambiguity — TIER_2→TIER_1 bar met if *any* plan of the student satisfies it; TIER_3→TIER_2 needs latest RESPONSIVE on *some* plan — routes/movements.py:51-54, 80-84
- §3.6 — revise — ambiguity — aimline goal uses the *same* window's kind; baseline/goal/total pinned at activation; fallback defaults (0/goal/baseline) when evidence absent — services.py:555-583
- §3.6 — revise — mismatch — session list ordered `scheduled_on` ASC (created_at tie-break) instead of §2.3 default; minutes mismatch → `ERR_INVALID_REQUEST` 400, checked after ACTIVE state — services.py:450-453, routes/plans.py:337-341
- §3.6 — insert — mismatch — probe list ordered `administered_on` ASC (created_at tie-break) instead of §2.3 default — services.py:443-447
- §3.6 — insert — ambiguity — trailing window of <2 probes: both slopes zero → first probe always RESPONSIVE — services.py:600-628
- §3.6 — revise — mismatch — counter resets only on move to TIER_1 (not any tier move); auto-referral fires when a TIER_3 NON_RESPONSIVE probe leaves counter *at or above* the minimum — services.py:511-512, routes/plans.py:290-307
- §3.7 — insert — ambiguity — rejection takes no version field and skips the freshest-proposal precondition — routes/meetings.py:119-134
- §3.8 — insert — ambiguity — pause after tier moved → `ERR_INVALID_STATE` 409; cancel of ACTIVE-with-probes or terminal plan → `ERR_INVALID_STATE` 409 — routes/plans.py:160-163, 243-253
- §3.9 — insert — ambiguity — `triggered_plan_id` = earliest-created ACTIVE plan; null with no cascade when none — routes/referrals.py:38-41, services.py:534-548
- §3.9 — insert — ambiguity — outcome report: missing `window_id` → 400; window not in district → `ERR_WINDOW_NOT_FOUND` 404; window status unrestricted — routes/reports.py:15-28

All other impl behaviors (envelope shape, RBAC matrix, path-resolution order, OCC endpoints, capacity ledger, fidelity/aimline/slope math, cascades, error catalogue) were already uniquely pinned by PRD_FINALIZED.md and left untouched. Implementation passes 71/71 tests per `results.8.json`.
