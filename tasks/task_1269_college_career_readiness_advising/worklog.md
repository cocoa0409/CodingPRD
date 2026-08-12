# Worklog — task_1269_college_career_readiness_advising

## Step 1: Create Task Directory — 2026-08-12T14:00:00.000Z

Pre-assigned output folder `tasks/task_1269_college_career_readiness_advising` with `workspace/` subdirectory already exists. Step 1 treated as done per orchestration instructions; no auto-index scan run.

## Step 2: Generate Scaffold — 2026-08-12T15:11:00.000Z

All three scaffold artifacts are generated, lint-clean, and verified on disk.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_1269_college_career_readiness_advising/SCAFFOLD.yaml
  Difficulty design:  tasks/task_1269_college_career_readiness_advising/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_1269_college_career_readiness_advising/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    69
  §1.1 entities declared:     15
  §1.8 instances scanned:     24
  §1.9 instances scanned:     55
  Calls scanned (§1.8+§1.9):  711

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Summary

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1269_college_career_readiness_advising/`):
- `SCAFFOLD.yaml` — 1696 lines (§1.0–§1.7 + notes; no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 924 lines (single top key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 1289 lines (single top key `scaffold_corner_design`)

**Counts**: 15 entities, 12 state-machine blocks (11 entities, Application carries two decision-dimension views), 69 endpoints, 37 error codes, 10 calculations, 13 validation tiers, 5 roles, 2 OCC concurrency rules. Difficulty design: 24 instances across all 9 rules (3+3+3+2+2+3+3+2+3, exceeding the 18 minimum). Corner design: 55 active instances + 8 `excluded_because` stubs across all 9 taxonomy sections.

**Design highlights** (harder-than-expert calibration):
- Archetypes: compliance/audit (senior-audit certification with segregation-of-duties: auditor != assigned advisor) + temporal windowing (placement intervals, milestone deadlines)
- Non-linear machines on 4 entities: RecommendationRequest reroute cycle (DECLINED→REQUESTED), Certification retake loop, StudentPlan revision loop, Application parallel dimensions (submission × decision)
- Dual-variant calcs on 3 domains: plan alignment (provisional/official), milestone pct (STRICT/LENIENT), advisor caseload load (simple/weighted)
- Combinatorial formulas in all 3 modes: grade-band weighted readiness (a), equity gap per-group-rounding-then-sum pinned at 85.72 vs 85.71 (b), snapshot-ordered district target caseload (c)
- Depth-3 transitive cascades from two triggers (ops-run sweep → MISSED → app regression → plan recompute; enrollment completion → recompute → CERTIFIED-audit AUTO_DRIFT flag)
- All formula-derived asserts pre-computed as literals (verified by executing the formulas in Python)
- Deterministic selectors (advisor auto-assignment by load/created_at, site-reduction survivor ranking), logical clock with fixed default 2026-05-01T00:00:00Z, no random ids in any decision

Notes: the directory already contained a pre-existing `worklog.md` and empty `workspace/` from batch provisioning — left untouched. Every error code is referenced by at least one validation/transition; forbidden concurrency vocabulary scan is clean; RBAC identity fields are all declared (3 entity-backed, 2 opaque).

## Step 3: Copy Shared Files — 2026-08-12T15:12:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1269_college_career_readiness_advising/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-12T15:45:00.000Z

PRD generation complete. Summary:

**File**: `/home/ubuntu/github/CodingPRD/tasks/task_1269_college_career_readiness_advising/workspace/PRD.md` — verified on disk, 348 lines, ~63 KB.

**Section list**:
- §1 Introduction (2 paragraphs, pain-point/business-context angle)
- §2 Global Specifications: 2.1 Roles/RBAC (all 5 roles with `identity:` translated — `DistrictAdmin`/`WblCoordinator` opaque, `Advisor`/`Student`/`Teacher` entity-backed), 2.2 API Response Structure (verbatim fixed block), 2.3 Pagination (`limit` 10/1–100, `offset` 0, `created_at` ascending), 2.4 Common Properties & Version Discipline (incl. the pinned Student/Advisor version-bump whitelist), 2.5 Logical Clock (default 2026-05-01T00:00:00Z, `to_iso8601`/`current_utc`), 2.6 Validation Pipeline (all 13 priority stages in order, earliest-wins), 2.7 OCC (both rules, `ERR_STALE_VERSION`/412), 2.8 Nested Retrieval, 2.9 Deterministic Selection/Sweep Order, 2.10 Precision & Rounding
- §3 Business Logic: 8 subsections (caseloads, plans, enrollments, applications/milestones/decisions, letters, certifications/placements, senior audit/graduation, outcomes/ops-run sweep)
- §4 Endpoint Definitions (4-column table), §5 Error Code Catalogue (2-column table)

**Entity coverage**: 15/15 entities; 109/109 required identifiers present in backticks (all entity fields + all endpoint input/query identifiers incl. `expected_student_version`, `expected_advisor_version`, `student_ids`, `target_advisor_id`, `to_decision`, `new_teacher_id`, `interest_code`/`score`, equity-report and reassignment output fields). All 37 error IDs and all 70 state/enum values verified present.

**Endpoint coverage**: 69/69 endpoints in the §4 table; 37/37 errors in the §5 table.

**Contract results**:
- Contract 1 (field coverage): PASS — 109 required, 109 present, 0 missing (one initial miss, `student_id`, repaired in §2.8).
- Contract 2 (rule coverage): PASS — validation priority order stated as an explicit 13-stage pipeline; both OCC rules named with occ field + error id + 412 and no race framing; all 12 state machines' transitions/preconditions/side effects expressed (incl. AUTO_DRIFT auto-flag, site-capacity-reduction cascade, deactivation atomic rehoming, terminal-departure cascades); all 10 calculations in reconstructible prose (incl. pinned equity-gap rounding order with forbidden-order warning, readiness cap-after-rounding, site interval event-point algorithm); all error trigger conditions matchable in §2/§3.
- Contract 3 (§3 path purity): PASS — 618 §3 backtick tokens scanned, 0 path/method violations.

**Zero-silence notes**: no fuzzy/approximating words (one idiomatic "built around" reworded to "anchored on"); no pseudocode operators; no pseudocode, no schema tables in §3; the withheld difficulty/corner design files were never opened; PRD.md ends at §5 with no audit footer.

## Step 5: Generate Unit Tests — 2026-08-12T16:20:00.000Z

Done. Complete test infrastructure generated for task_1269 under `/home/ubuntu/github/CodingPRD/tasks/task_1269_college_career_readiness_advising/`.

## File list (line counts)

**test_helpers/ (9 files, 1,616 lines)**
- `__init__.py` (23) — barrel export: framework generics + PRD-specific code
- `types.py` (385) — 17 status/role enums + 17 entity TypedDicts (all carry id/created_at/updated_at/version per PRD §2.4)
- `api_client.py` (287) — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (all 50 routes incl. `/_clock/set_current_utc`); module-level `api_client`
- `api_errors.py` (88) — all 37 `ApiErrorId` values + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` (221) — per-entity `assert_*`, `assert_error_envelope`, `assert_three_fraction_digits`, `assert_pct` (0.001 tolerance so the pinned equity rounding order 85.72-vs-85.71 cannot leak)
- `factories.py` (136) — input-field-only payload factories with unique ref/email/code generation
- `constants.py` (54) — default clock epoch, 24-credit graduation threshold, readiness weight bands, cert-points ladder
- `test_users.py` (35) — opaque-role shared headers + `make_advisor/student/teacher_headers` builders for the three entity-backed roles
- `fixtures.py` (387) — tiered composites: `create_active_plan`, `add_completed_enrollment`, `create_application_with_milestones`, `setup_student_with_active_plan`, `setup_audit_in_review`, `setup_certified_audit`, `setup_graduated_student`, placement/cert transition walkers; all setup via `get_success_data` with "Setup failed" context

**test_suite/ (9 files, 2,756 lines)** — conftest.py + 8 numbered test files; **103 tests total**

## Test counts per queue
- **Queue A (Difficulty): 48 tests** — all 24 instances × exactly 2 tests each (rule coverage: dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant)
- **Queue B (Corner): 55 tests** — all 55 non-stub instances × 1 test each (entities 6, state_machines 6, calculations 3, validations 28, endpoints 3, errors 1, rbac 3, cross_cutting 3, consistency_model 2)

## Skip list
No instances were skipped. All 24 difficulty instances and all 55 non-stub corner instances passed the PRD-first two-condition filter (PRD.md is unusually complete — every asserted error_id/threshold/formula is named in §2–§3 prose). The 8 `excluded_because:` corner stubs (errors section) were not translated; all 8 `difficulty_instance` cross-references verified to resolve.

## Judgment calls (two-reader derivability)
- `student_creation_defaults_and_system_fields`: dropped the `created_at == updated_at` equality sub-assert (PRD doesn't pin equality); kept the verbatim-covered 3-fractional-digit format, version=1, UUID, defaults.
- `active_plan_cardinality_conserved_on_supersede`: the ACTIVE-count invariant is asserted via client-side filtering of the full plans list rather than the `?status=ACTIVE` query param (PRD only says "most" reverse lookups accept a status filter — plans not named).
- `application_create_autoseeds_milestones`: asserts the kind *set* {ESSAY, TRANSCRIPT, FEE_PAYMENT} plus non-decreasing `created_at` ordering, since PRD pins the list ordering rule but not the seed creation order.

## Verification results
- `python3 -m py_compile`: all 18 files pass
- `pytest --collect-only`: 103 tests collected, 0 errors
- **Stage-2 tag audit: PASS** — every test has exactly one `Design:` line as the last docstring line; all 79 distinct tags resolve to real instances; zero untagged/dual-tagged/unknown tags; no stub leakage
- **Verbatim citation sweep: PASS** — all 150 quoted docstring spans match PRD.md literally (whitespace-normalized)
- No `pytest.mark.skip`/`skipif`/`xfail`; no scaffold/section-table references in generated code; sibling tasks and `workspace/implementation/` never touched

## Step 6: Generate Implementation — 2026-08-12T16:20:00.000Z

Implementation complete and verified. Summary:

## Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_1269_college_career_readiness_advising/workspace/implementation/`)

| File | Lines |
|---|---|
| start.sh (executable, guarded pip install, `exec`, `$PORT`, 0.0.0.0) | 10 |
| requirements.txt (flask) | 1 |
| app.py (entry, before_request auth, envelope error handlers) | 50 |
| store.py (in-memory dicts, logical clock default 2026-05-01T00:00:00Z, 3-fractional-digit ISO timestamps, version/touch discipline) | 87 |
| util.py (error catalog, envelope, schema validation, pagination, Decimal half-up helpers) | 319 |
| computed.py (all derived-field calculations + serializers) | 526 |
| cascades.py (AUTO_DRIFT, student terminal cascade, placement termination, site capacity reduction) | 80 |
| routes/admin.py (clock, advisors, teachers, pathways) | 353 |
| routes/students.py (enroll, list, graduate, withdraw) | 138 |
| routes/plans.py (plans + enrollments) | 270 |
| routes/apps.py (applications, decisions, milestones) | 339 |
| routes/recs.py (recommendation requests) | 186 |
| routes/wbl.py (certifications, sites, placements) | 323 |
| routes/audit.py (senior audits, outcomes, ops runs) | 302 |
| routes/__init__.py | 13 |

Total 2,997 lines. No seeding anywhere — store starts empty; all entities are built via the declared API surface.

## Endpoints: 69/69 (verified by counting route decorators; matches the PRD §4 table including `POST /_clock/set_current_utc` and both ops-run routes)

## State machines implemented (11)
Student (ENROLLED→GRADUATED/TRANSFERRED_OUT/WITHDRAWN with full closing cascades), Advisor (ACTIVE↔INACTIVE with atomic selector rehoming), StudentPlan (DRAFT/REVISING→ACTIVE with supersede, ACTIVE→REVISING), CourseEnrollment (PLANNED/ENROLLED/COMPLETED/FAILED/DROPPED with retake/replan loops and plan-ACTIVE gates), Application submission dimension (DRAFT→READY with milestone gate + deadline, READY→SUBMITTED with rec-letter gate, CONFIRMED, WITHDRAWN with milestone waiver, system READY→DRAFT regression), Application decision dimension (PENDING/DEFERRED/WAITLISTED/ACCEPTED/DENIED, decided_at only when leaving PENDING), ApplicationMilestone (PENDING↔READY auto-advance, COMPLETED with dependent bubble-up, WAIVED recovery from MISSED, system MISSED), RecommendationRequest (accept/decline/reroute with reroute_count, submit, advisor-only verify, student withdraw), Certification (schedule/pass/fail/retake loop with retake_count, cancel), Placement (confirm with pairwise half-open overlap + aggregate interval capacity, term-start gate, complete with hours, decline, terminate with reason), SeniorAudit (IN_REVIEW/FLAGGED/CERTIFIED with SoD + 5 pinned graduation gates and CERTIFIED→FLAGGED AUTO_DRIFT freeze-break), OutcomeRecord (UNVERIFIED/DISPUTED→VERIFIED).

## Calculations implemented (10, all per §1.3/§2.10 with Decimal ROUND_HALF_UP)
plan_alignment (PROVISIONAL/OFFICIAL, empty-required=100), plan_readiness_score (grade-12 vs ≤11 weight bands, round-then-cap-100), milestone_completion_pct (STRICT stored, LENIENT only on single-plan GET), audit_credits (exact, 24-credit snapshot, equality passes), caseload_load (SIMPLE/WEIGHTED with no-active-plan +0.5), caseload_equity_gap_index (pinned per-group 4dp then sum×100→2dp), district_target_caseload (ACTIVE-pool snapshot, INACTIVE→0), wbl_hours_progress (cap after rounding), certification_points (0/50/100), site_overlap_max (half-open interval event-point sweep). OCC on Student.version (plan create) and Advisor.version (reassignments) → 412.

## Verification
- `python3 -m py_compile` passes on all 13 .py files.
- Smoke boot (`PORT=18931 bash start.sh` in background): clean boot; 404 for unknown route, 401 `ERR_UNAUTHENTICATED` without headers, 404 `ERR_NOT_FOUND` for missing advisor; end-to-end flow exercised (advisor→student selector→pathway→plan with OCC 412 on stale retry→activate→enrollment with `counts_toward_pathway: true`→application with 3 auto-seeded READY milestones→ops-run `run_index 1`, `plans_recomputed 1`; 400 on unknown field, 403 on wrong role). Readiness math spot-checked (grade-12: 0×0.30+100×0.40+100×0.20+100×0.10 = 70.0). Server killed after the smoke test.

**Orchestrator route-parity check**: SCAFFOLD §1.5 declares 69 (method, path) pairs; implementation registers exactly the same 69 — no missing, no extra.

## Step 7: 8-round stability sweep — 2026-08-12T17:05:00.000Z

**Result: PASS — two consecutive clean sweeps (8/8 rounds, 103/103 tests each), final sweep under load 6.87.**

Iterations: 7 sweeps total. Sweep 1: 92/103 × 8 (13 distinct failures). Sweeps 2-3: isolated environmental flakes. Sweep 4 (boot-instrumented diagnostic): clean. Sweep 5: 2 infra flakes (first-test restart timeout). Sweeps 6-7: clean with final artifacts.

Fixes applied:
- `implementation/util.py::validate_schema` — added missing `max` range enforcement (`min` and `gt` were checked, `max` was silently ignored), so `grade_level: 13` now yields ERR_VALIDATION per PRD §2.6 "numeric ranges hold — grade_level between 9 and 12 inclusive". Verified live, then by sweep.
- `implementation/app.py` — `app.run(..., threaded=True)` for health-poll responsiveness under parallel load.
- `implementation/start.sh` — boot path minimized (one-shot `.deps_installed` sentinel instead of a `python3 -c "import flask"` subprocess on every per-test reboot; `PYTHONDONTWRITEBYTECODE=1`) to shrink the window for the harness's 15s restart poll under co-tenant load.
- `test_suite/test_03_applications_milestones.py` — `_setup_pending_interview` referenced the pytest `api` fixture out of scope (NameError); threaded `api` through as a parameter (2 call sites).
- `test_suite/test_08_readiness_opsruns.py` — same out-of-scope `api` NameError in `_setup_milestone_pool`, `_setup_readiness`, `_setup_regression`; threaded `api` through (5 call sites).
- `test_suite/test_05_certifications_placements.py` — added missing `create_pathway` import (NameError in test_certification_points_levels).

Tests deleted: none. Every failing assertion traced to PRD-verbatim rules; all non-assertion failures were harness restart timeouts ("could not be restarted", 15s poll) caused by machine-wide scheduling saturation from co-tenant benchmark pipelines on this shared 8-core box, plus one mid-test ConnectionResetError under the same conditions. Boot-time diagnostics (832 boots logged) showed worst-case boot phase of 0.44s, confirming boot cost was never the cause.

## Step 8: Finalize PRD — 2026-08-12T17:10:00.000Z

`/home/ubuntu/github/CodingPRD/tasks/task_1269_college_career_readiness_advising/workspace/PRD_FINALIZED.md` produced — byte-identical to PRD.md (zero edits; verified with `diff` → IDENTICAL).

**Line counts / %-delta:** PRD.md 348 lines, PRD_FINALIZED.md 348 lines, 0% delta.

**Changes:** none.

**Per-item analysis of `<step_7_diff>` (each traced to implementation; none revealed PRD-silence or PRD-mismatch):**

- `implementation/util.py::validate_schema` `max` enforcement — an **implementation fix toward the PRD**, not a PRD gap. PRD §2.6 stage 2 already pins "numeric ranges hold — `grade_level` between 9 and 12 inclusive … Failure yields `ERR_VALIDATION` (HTTP 400)" and §3.1 pins "an integer `grade_level` between 9 and 12". The only `"max"` schema spec in the impl is `grade_level` (`implementation/routes/students.py:39`, enforced at `implementation/util.py:254-255`). PRD already uniquely determines `grade_level: 13 → ERR_VALIDATION`; prose kept verbatim per method rule 2.
- `implementation/app.py` `threaded=True` (`app.py:53-54`) — infra-only change (server concurrency for harness health polls); no API-visible behavioral choice, outside PRD scope. No edit.
- `implementation/start.sh` boot minimization (`.deps_installed` sentinel, `PYTHONDONTWRITEBYTECODE=1`) — infra-only boot script; no API-visible behavior. No edit.
- `test_suite/test_03_applications_milestones.py`, `test_08_readiness_opsruns.py`, `test_05_certifications_placements.py` — pure fixture bugs (out-of-scope `api` NameError fixed by threading the fixture through helper signatures; one missing `create_pathway` import). Verified at `test_03:69`, `test_08:79/128/224`, `test_05:11`. No assertions changed, no behavioral implication. No edits.
- No tests deleted.

**Per-edit pre-edit search log** (zero edits committed; the single candidate edit — `grade_level` max enforcement — was analyzed and rejected):

- (a) Subject: `grade_level` 9–12 range validation (stage-2 schema check).
- (b) Impl paths enumerated and read/grepped: `implementation/routes/students.py:39` (schema `min: 9, max: 12`), `students.py:69` (record persistence), `implementation/util.py:250-257` (`min`/`max`/`gt` enforcement order), `implementation/computed.py:64-66` (weighted caseload grade weights), `computed.py:185` (readiness grade band), `computed.py:309` (serializer), `implementation/routes/audit.py:43-45` (senior-audit `grade_level == 12` gate).
- (c) No wording change made: PRD §2.6/§3.1 already describe the enforced behavior exactly (inclusive 9–12 bounds, `ERR_VALIDATION`/400 at stage 2), and all enumerated paths are consistent with that existing prose — committing any edit would only risk introducing a new mismatch.

Bottom line: Step 7's only behavioral fix aligned the implementation to PRD-verbatim rules; all other fixes were harness-infra or test-fixture plumbing. PRD.md already uniquely determines every behavior the implementation exhibits, so PRD_FINALIZED.md is a verbatim copy.

## Step 9: Complete PRD — 2026-08-12T17:20:00.000Z

PRD_COMPLETED.md produced at `/home/ubuntu/github/CodingPRD/tasks/task_1269_college_career_readiness_advising/workspace/PRD_COMPLETED.md`. All changes are in-paragraph inserts/revisions; no new sections, no invented behavior.

**Size delta:** PRD_FINALIZED.md 348 lines / 63,157 chars → PRD_COMPLETED.md 348 lines / 65,490 chars (+2,333 chars, 15 lines touched).

**Counts:** 14 ambiguity-pins, 1 mismatch-revision (15 edits total).

**Change log:**
- §2.3 — insert — ambiguity — pins `ERR_VALIDATION` for non-integer `limit`/`offset` and negative `offset`, and defines `has_more` as `offset + returned < total_count` — implementation/util.py:291-308, 90
- §2.5 — insert — ambiguity — clock-set returns `current_utc` in a 200 OK response — implementation/routes/admin.py:35
- §2.6 stage 2 — insert — ambiguity — extends schema-failure enumeration with future-at-creation `deadline_at`, `required_work_hours` ≥ 0, non-negative `hours_logged`, and `new_teacher_id` required on reroute — implementation/routes/apps.py:82-84, admin.py:292/332, wbl.py:286-287, recs.py:141-142
- §2.6 stage 8 — insert — ambiguity — target states no client transition can reach (application `DRAFT`, milestone `PENDING`/`READY`/`MISSED`, cert `REGISTERED`, placement `OFFERED`, audit `DRAFT`, outcome `UNVERIFIED`) yield `ERR_INVALID_STATE` — implementation/routes/apps.py:137-138/338-339, wbl.py:84/273, audit.py:89/205
- §3.1 — insert — ambiguity — a `Teacher` may read only their own record and routed-request queue; cross-teacher reads are `ERR_FORBIDDEN` — implementation/routes/admin.py:240-241, 269-270
- §3.1 — insert — ambiguity — deactivation rehomes advisees in `created_at` ascending order with each assignment incrementing the chosen advisor's simulated count — implementation/routes/admin.py:129-139
- §3.1 — insert — ambiguity — deactivating a non-`ACTIVE` advisor or reactivating a non-`INACTIVE` one is `ERR_INVALID_STATE` — implementation/routes/admin.py:120-127
- §3.1 — insert — ambiguity — bulk reassignment requires each listed student to be an `ENROLLED` advisee of the source (else `ERR_INVALID_STATE`); target advisor checked for existence only, no status/capacity gate — implementation/routes/admin.py:159-174
- §3.2 — revise — ambiguity — pathway configuration update may move `status` between `ACTIVE` and `RETIRED` in either direction — implementation/routes/admin.py:341-342
- §3.3 — insert — ambiguity — returning a `DROPPED`/`FAILED` enrollment to `PLANNED` clears its recorded grade to null — implementation/routes/plans.py:263-264
- §3.4 — insert — ambiguity — past/present `deadline_at` at application creation is a schema failure under `ERR_VALIDATION` (400), before role authorization — implementation/routes/apps.py:81-84
- §3.5 — revise — ambiguity — any authenticated advisor may reroute a `DECLINED` request (assigned-advisor check binds verification only); missing `new_teacher_id` is `ERR_VALIDATION` — implementation/routes/recs.py:141-144, 153-158
- §3.7 — insert — ambiguity — with no `ACTIVE` plan, `pathway_requirements_met`/`certification_requirement_met`/`work_hours_met` are trivially true — implementation/computed.py:252-255
- §3.7 — insert — ambiguity — audit certification is reachable only from `IN_REVIEW`; other from-states are `ERR_INVALID_STATE` before the gates — implementation/routes/audit.py:88, 111
- §3.7 — revise — mismatch — graduation is gated first on the student still being `ENROLLED` (`ERR_INVALID_STATE`), then on a `CERTIFIED` audit; PRD had claimed the certified audit was the "single hard precondition" — implementation/routes/students.py:110-115
- §3.7 — insert — ambiguity — withdrawal requires the student still be `ENROLLED`, else `ERR_INVALID_STATE` — implementation/routes/students.py:132-133

Everything else in the implementation (endpoint/role matrix, all state machines, rounding orders, selector rankings, cascade effects, version discipline, pipeline stage ordering) was verified against the PRD and found already uniquely pinned — no further changes needed.
