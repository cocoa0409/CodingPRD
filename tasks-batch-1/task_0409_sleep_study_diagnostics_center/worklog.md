# Worklog — task_0409_sleep_study_diagnostics_center

## Step 1: Create task directory — 2026-06-19T02:14:00.000Z

Created `tasks/task_0409_sleep_study_diagnostics_center/` with `workspace/` subdirectory. Index 0409 (highest existing was 0408).

## Step 2: Generate scaffold — 2026-06-19T02:31:00.000Z

All three required files are written and the scaffold lints clean. There were pre-existing `worklog.md` and `workspace/` in the directory (not mine to touch).

Generated the three scaffold artifacts for **task_0409_sleep_study_diagnostics_center**, all passing `scaffold_lint.py` (`VERDICT: clean lint`, 441 calls scanned).

**Files**: `SCAFFOLD.yaml` (§1.0–§1.7), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8), `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9).

**Complexity profile**: workflow_orchestration + temporal_windowing, flat entity topology, branching state-machine shape, peer_roles, immediate consistency. Layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation.

**Contents**:
- **8 entities**: Patient, Referral, SleepBed, StudyOrder, ScoringReport, DMEOrder, ComplianceRecord, FollowUp (self-referential resupply FK on DMEOrder).
- **5 state machines**: Referral (branching prior-auth + bubble-up), StudyOrder (revert cycle SCORED↔IN_PROGRESS), ScoringReport (FINALIZED/RETURNED fork), DMEOrder, FollowUp.
- **3 concurrency rules** (OCC, 412): stale Referral on study create, stale StudyOrder on scoring submit, stale predecessor DMEOrder on resupply create.
- **5 calculations**: `ahi_index`, `severity_band` (AASM >= bands), `cpap_adherence` (3-input compound-AND with window short-circuit), `resupply_cycle_number`, `epworth_delta`.
- **14 validation rules** (ordered, priority 1–14).
- **39 endpoints** (flat collections; `api_prefix: ""`; reverse-reachability via filtered-lists + 3 sub-resource GETs).
- **34 error codes**.
- **5 roles**: SchedulingCoordinator, SleepTechnologist, Physician, DMECoordinator (opaque) + Patient (entity_backed:Patient).

**Difficulty design**: all 9 §0.5 rules × exactly 2 instances = **18 instances**, all formula-derived asserts pre-computed as literals.

**Corner design**: **41 active instances** across 8 sections + **5 `excluded_because` stubs** citing existing §1.8 instance names. No duplicate names across both design files.

Did not read or reference any sibling task directory, per the hard constraint.

## Step 3: Copy INSTRUCTION.md — 2026-06-19T02:32:00.000Z

Copied root `INSTRUCTION.md` to `tasks/task_0409_sleep_study_diagnostics_center/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-19T02:37:00.000Z

Generated `workspace/PRD.md` from the scaffold. All three Hard Contracts pass.

**Structure**: 5 top-level sections; 9 §2 subsections (RBAC, Response Structure, Pagination, Common Resource Properties, Hierarchical Consistency, Nested/Filtered Retrieval, Validation Ordering, Clinical Precision & Rounding, OCC); 11 §3 subsections (clinical lifecycle); §4 endpoint table (39 endpoints); §5 error table (33 error codes); ~282 lines.

**Hard Contract reports**: Field coverage PASS (47/47 entity fields, 3/3 request bodies, 8/8 path params, 8/8 query params). Rule coverage PASS (14/14 validations, 3/3 OCC, all 5 state machines' transitions, 5/5 calculations, 33 error IDs matchable). Path purity PASS (§3: 0 path tokens, 0 bare HTTP methods).

**Confirmation**: Did NOT read SCAFFOLD_DIFFICULTY_DESIGN.yaml or SCAFFOLD_CORNER_DESIGN.yaml.

## Step 5: Generate unit tests — 2026-06-19T02:58:00.000Z

**test_helpers/ (9 files)**: types.py, api_client.py (39 endpoints), api_errors.py (32 errors), assertions.py, factories.py, constants.py, test_users.py (4 opaque roles + entity-backed Patient builder), fixtures.py (full clinical lifecycle helpers), __init__.py.

**test_suite/ (conftest + 5 test files, 77 tests)**: test_01 scoring/adherence (16), test_02 referral/study workflows (19), test_03 scheduling/validation guards (21), test_04 invariants/concurrency/consistency (8), test_05 entities/listing/access (13).

**Coverage**: Queue A (Difficulty) all 18 instances ≥2 tests (36 tagged); Queue B (Corner) all 41 non-stub instances ≥1 test (41 tagged). Every test carries exactly one verbatim `Design:` tag. No skip/xfail. 5 stubs verified (excluded_because cross-refs resolve). Instances skipped: none.

**Verification**: all files AST-parse; test_helpers imports; all 77 tests collect; every citation ≥8-word substring survives literal grep of PRD.md.

## Step 6: Generate implementation — 2026-06-19T02:58:00.000Z

Generated Python + Flask implementation in `workspace/implementation/` (8 files): start.sh (foreground, $PORT on 0.0.0.0, guarded pip install, exec python3 app.py), requirements.txt (flask==3.0.3), app.py (39 routes, auth/RBAC, error handlers), db.py (8 in-memory entity dicts, empty on boot, no seeding), errors.py (33-entry catalog), response.py (envelope helpers), helpers.py (auth, pagination, round_half_up, ISO parsing), domain.py (serializers, calculations, bed-collision).

**39 endpoints** match the endpoint table. **5 state machines** (Referral, StudyOrder w/ SCORED↔IN_PROGRESS revert + bubble-up, ScoringReport, DMEOrder w/ resupply chain, FollowUp). **5 calculations** (ahi_index divide-then-round, severity_band inclusive edges, cpap_adherence window-gate+compound-AND, resupply_cycle_number, epworth_delta cross-FK-chain). 3 OCC checks (412), bed double-booking w/ turnover buffer, half-open compliance-window overlap, validation ordering per §2.7, version bumps on all mutations.

**Confirmation**: start.sh binds 0.0.0.0:$PORT foreground via exec; in-memory-only, no seeding, fresh boot every invocation.

## Step 7: Run tests and iterate — 2026-06-19T03:52:00.000Z

**Iterations run:** 2 (initial sweep surfaced 9 deterministic failures shared identically across all 8 rounds; second sweep after fixes was clean 77/77 × 8).

**Tests deleted:** None. All failures traced to a test-helper unpacking bug and a genuine implementation gap; no test asserted a scaffold-only or non-PRD-derivable rule.

**Fixes applied to `test_suite/`:**
- `test_01_scoring_and_adherence_calculations.py` — 6 adherence tests (`test_adherence_window_gate_short_circuits_to_false`, `test_adherence_short_window_ignores_usage_clauses`, `test_adherence_fails_on_average_usage_clause`, `test_adherence_all_three_usage_clauses_must_hold`, `test_adherence_pct_boundary_exactly_seventy_percent_is_adherent`, `test_adherence_min_nights_boundary_twenty_one`): changed `_, dme, _ = create_fulfilled_dme()` to `_, _, dme = create_fulfilled_dme()`. Fixture returns `(study, report, dme_order)`; tests were grabbing the scoring report as `dme` and posting a compliance record against the report's id, which the PRD-faithful server correctly rejected with `ERR_DME_NOT_FOUND` (404). STEP-2 test bug (wrong tuple position), fixed in test, not implementation.

**Fixes applied to `implementation/`:**
- `app.py`, `referral_cancel()` — added `SCHEDULED` to the referral cancellable-from set. PRD §3.2 literally enumerates `{SUBMITTED, PENDING_AUTH, AUTHORIZED}`, but the PRD also (a) describes a cancel cascade that cancels `ORDERED`/`SCHEDULED` studies and releases their bed nights, and (b) catalogs `ERR_REFERRAL_HAS_ACTIVE_STUDY`, which fires only when a study is `IN_PROGRESS/SCORED/INTERPRETED` — a condition that can only exist once the referral has bubbled to `SCHEDULED`. Under the literal enumeration that error path and both cascade paragraphs would be permanently unreachable. Including `SCHEDULED` is the only coherent reading. Resolved `test_referral_cancel_cascades_to_scheduled_study`, `test_referral_cancel_releases_bed_night_for_rebooking`, `test_cancel_referral_blocked_by_in_progress_study`.

**Final state:** 77/77 passing across all 8 concurrent rounds.

**Orchestrator verification note:** An initial orchestrator re-run of the 8-round sweep reported 0/77 ("could not be restarted") — root-caused to a malformed `--start-command "bash start.sh"` (missing the `cd <impl_dir> &&` prefix the runner's `_parse_command` requires to set CWD; without it the runner ran start.sh from the pytest CWD where it does not exist). Re-running with the correct `cd <impl_dir> && bash start.sh` form (as Step 7's subagent used) gives all 8 rounds 77/77 passed, 0 failed, 0 errors (~47s each). Implementation confirmed correct.

Step 7 had implementation fixes → Step 8 will NOT be skipped.

## Step 8: Finalize PRD — 2026-06-19T03:54:00.000Z

Produced `workspace/PRD_FINALIZED.md`. **0% line-count delta** (282 → 282; one line revised in place).

**Change**: §3.2 (Prior-Authorization Branch) — revise — added `SCHEDULED` to the referral cancellable-from enumeration (`SUBMITTED, PENDING_AUTH, AUTHORIZED` → `+ SCHEDULED`), named the rejected-from states (`DENIED, COMPLETED, CANCELLED` → `ERR_INVALID_STATE`), and added a parenthetical explaining why `SCHEDULED` is cancellable while the active-study guard still blocks further-advanced studies — impl `app.py:240-243`.

**Pre-edit search log**: Subject = referral cancellable-from set + illegal-cancel error. Enumerated `referral_cancel()` (app.py:229-259), cascade/active-study guard, and all referral state-producing paths (create→SUBMITTED, request_auth→PENDING_AUTH, approve→AUTHORIZED, deny→DENIED, schedule bubble-up→SCHEDULED, interpret bubble-up→COMPLETED, cancel→CANCELLED), `_active_bed_holders` (domain.py:235-245). Confirmed DENIED/COMPLETED/CANCELLED are the exact reachable excluded states, all terminal → `ERR_INVALID_STATE` accurate. Wording kept minimal (append + parenthetical).

**Not edited**: test_suite/ tuple-position fix was a pure fixture bug (server correctly returned ERR_DME_NOT_FOUND) — no PRD silence/mismatch, no edit.

## Step 9: Complete PRD — 2026-06-19T03:58:00.000Z

Produced `workspace/PRD_COMPLETED.md` (full PRD-vs-implementation scan). Source PRD_FINALIZED.md (282 lines, 41,432 chars) → PRD_COMPLETED.md (282 lines, 43,271 chars), char delta +1,839, no lines added/removed (all in-paragraph revisions).

**Counts**: ambiguity-pins 5 · mismatch-revisions 1.

**Changes**:
- §2.1 RBAC — revise — mismatch — PRD claimed Patient ownership checks compare resource patient FK to X-User-ID; impl does role-set membership only, no ownership compare. Revised to role-level access + ownership-as-convention. (app.py:63-66, helpers.py:27-40)
- §3.5 Scheduling/bed-booking — insert — ambiguity — pinned symmetric trailing-buffer block overlap `[start, end+buffer)` and which study states hold a booking (SCHEDULED/IN_PROGRESS/SCORED/INTERPRETED). (domain.py:248-261, 235-245)
- §3.6 Scoring — insert — ambiguity — `/score` returns HTTP 200 with the updated study order object. (app.py:521)
- §3.7 Interpretation (return) — insert — ambiguity — return action returns HTTP 200 with the scoring report (RETURNED). (app.py:625)
- §3.7 Interpretation (interpret) — insert — ambiguity — interpret returns HTTP 200 with the scoring report (FINALIZED), not study/referral. (app.py:606)
- §3.10 Compliance Reporting — insert — ambiguity — pinned ERR_INVALID_REQUEST for ill-formed window (end≤start) / negative count at body-validation, and ERR_INVALID_STATE for non-FULFILLED device as priority-5 state check (after body validity, before window-overlap). (app.py:802-825)

Other behaviors (calculations, validation priority §2.7, OCC §2.9, cascades §2.5, remaining errors) already uniquely pinned and confirmed consistent.

---

## PIPELINE COMPLETE — 2026-06-19T03:58:00.000Z

All 9 steps done. Final state: **77/77 tests passing across all 8 concurrent rounds** (~47s/round). Task tree complete: SCAFFOLD.yaml + 2 design files, 77 tests (10 test_helpers files + 7 test_suite files), Python/Flask implementation (8 source files), PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md.
