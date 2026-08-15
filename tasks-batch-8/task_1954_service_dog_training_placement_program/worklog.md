# Worklog — task_1954_service_dog_training_placement_program

## Step 1: Create Task Directory — 2026-08-15T02:55:00.000Z

Task directory `tasks/task_1954_service_dog_training_placement_program/` and `workspace/` pre-created by the pipeline launcher (Step 1 done externally). Difficulty directive: harder than expert level.

## Step 2: Generate Scaffold — 2026-08-15T03:55:00.000Z

Scaffold generation complete. All three artifacts are written and pass `scaffold_lint.py` with a clean verdict (1793 setup/trigger calls mechanically validated against §1.5, all FK reverse-reachability satisfied).

### Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_1954_service_dog_training_placement_program/SCAFFOLD.yaml` (1715 lines — §1.0–§1.7, no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1954_service_dog_training_placement_program/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1190 lines — single top-level key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1954_service_dog_training_placement_program/SCAFFOLD_CORNER_DESIGN.yaml` (1951 lines — single top-level key `scaffold_corner_design`)

### Counts

| Metric | Count |
|---|---|
| Entities | 18 (Applicant, TaskAssessment, WaitlistEntry, Contribution, PuppyRaiser, Trainer, Dog, HealthScreening, RaiserPlacement, TrainingMilestone, MatchRecord, TeamTrainingClass, Enrollment, PublicAccessTest, Partnership, FollowUp, Recertification, SupportRequest) |
| State machines | 16 (120 transitions; cycles on Applicant/Dog/Partnership/SupportRequest, guarded and compound transitions, terminal lockdowns) |
| Calculations | 10 (incl. dual-variant fundraising provisional/final, dual-variant rolling-vs-cumulative training advancement, origin-conditional health clearance, pinned rounding-order PAT scoring, two selector policies, clock-sweep scheduler, refund clawback) |
| Validation rules / error codes | 34 / 34 (strict priority ordering; three-tier OCC at priority 7; segregation-of-duties on both PAT evaluator and fundraising receive) |
| Endpoints | 116 (incl. `POST /api/_clock/set_current_utc` with pinned 2026-08-01T00:00:00Z default) |
| Roles | 8 (ProgramAdmin, IntakeCoordinator, TrainingDirector, Veterinarian opaque; Trainer, Evaluator entity_backed:Trainer; Applicant, PuppyRaiser entity-backed) |
| §1.8 instances | 26 non-stub (dual_variant 2; all other seven rules 3 each — every rule ≥2) |
| §1.9 instances | 51 non-stub + 8 excluded_because stubs = 59 total, spanning all nine claim-extraction sections |

### Key design decisions

- **Concurrency**: three true-race OCC rules (`enroll-stale-class`, `match-propose-stale-dog`, `recert-schedule-stale-partnership`), each with required `expected_*_version` input and version-increment side effect on the parent.
- **Cascades with divergent branches**: PAT-2nd-fail dissolves the match (depth 4), class-cancel retains it (depth 3), refund clawback reverts eligibility (depth 3) — three distinct triggers satisfying Rule 4.
- **Pinned arithmetic verified by hand**: all formula-derived asserts are precomputed literals (e.g., provisional 750000 vs final 765000; rolling 69.3 vs cumulative 80.8; PAT per-section 81.5 vs forbidden sum-then-round 80.6; boundary fail 79.6; follow-up dates 2027-01-14/04-14/07-13; recert 2028-10-19 leap-year rollover).
- **Dead-rule pruning**: removed `ERR_HEALTH_CLEARANCE_MISSING` and `ERR_DUPLICATE_ACTIVE_ENTRY` after reachability analysis showed their guards were shadowed by state preconditions — every remaining error code is triggerable and referenced.

## Step 3: Copy Shared Files — 2026-08-15T03:56:30.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1954_service_dog_training_placement_program/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-15T04:05:00.000Z

Structure looks correct. One more detail — the scaffold's `endpoint start` description says "min size 2" while the state machine says `enrolled_count >= 1`. My §4 description says "(minimum size; clock at least starts_on)" — neutral, and §3.7 states "at least 1". Both are consistent with the authoritative state-machine precondition. The PRD is complete.

### Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1954_service_dog_training_placement_program/workspace/PRD.md` — 390 lines.

**Section list:**
- §1. Introduction (3 paragraphs, pipeline-friction angle)
- §2. Global Specifications & System-Wide Principles — 2.1 RBAC (all 8 roles with identity translations), 2.2 API Response Structure (verbatim fixed block), 2.3 Pagination, 2.4 Common Resource Properties (with the `TrainingMilestone` common-fields exception called out), 2.5 The Logical Clock, 2.6 Request Validation Order (10-step priority pipeline), 2.7 Optimistic Concurrency Control (all 3 OCC rules), 2.8 Scheduled Sweep Rules, 2.9 Money, Precision, and Rounding
- §3. Business Logic & Workflows — 3.1 Intake & Assessment, 3.2 Waitlist (requirement variants, rank, eligibility), 3.3 Fundraising Ledger, 3.4 Raisers/Trainers/Dog Intake, 3.5 Health Screening (two clearance tracks), 3.6 Raiser Placement & Advanced Training (milestones, gates, career-change cascade), 3.7 Matching/Classes/PAT (selector policies, PAT scoring order, graduation cascade), 3.8 Partnerships/Follow-Ups/Recertification, 3.9 Owner Support
- §4. Endpoint Definitions — 116-row table, 4 columns
- §5. Error Code Catalogue — 34-row table, 2 columns

**Hard-contract verification (all mechanical checks scripted against the scaffold):**
- **Contract 1 (Field-Name Coverage): PASS** — 109 required identifiers (entity fields + endpoint input/query/path params), 109 present in backticks, 0 missing (after two repair passes that added `class_id` and `partnership_id` into §3.7/§3.8 narrative).
- **Contract 2 (Rule Coverage): PASS** — all 16 state machines expressed with preconditions paired to error IDs and side-effect cascades (withdraw, career-change, class-cancel, PAT-fail, refund-clawback, dissolve); all 10 calculations rendered as precise prose (fundraising dual variant with pinned divergence, rank score with all 8 constants, health clearance component points with origin tracks, milestone rolling/cumulative gates, per-section-then-average PAT rounding, graduation threshold, both selector policies with tie-breaks, sweep schedule, refund clawback ordering); all 33 validations mapped to error IDs in §2.6/§3 prose; all 3 OCC rules name write-endpoint + expected-version field + exact error ID/status; sibling-branch symmetry preserved (deny/withdraw/career-change/retire/dissolve multi-from-state transitions, PAT pass/fail branches, recert PASS/FAIL branches).
- **Contract 3 (§3 Path Purity): PASS** — 839 backticked tokens scanned in §3, 0 path tokens, 0 bare HTTP methods, 0 method+path combos. Endpoints appear only in §4.
- Auxiliary checks: all 34 error IDs present in §2/§3 narrative and in the §5 table; all 8 role names exact; all state enum values present as exact UPPERCASE strings; all 104 enum members present; all 116 endpoint paths in the §4 table with scaffold-exact role lists; §2.2 emitted byte-verbatim from the fixed block.

**Notable scaffold inconsistency handled:** class-start minimum — the state machine and priority-21 validation say `enrolled_count >= 1`, while the `ERR_CLASS_TOO_SMALL` catalog prose says `< 2`. The PRD follows the state-machine/validation precondition ("at least 1") and keeps the §4 description neutral.

## Step 5: Generate Unit Tests — 2026-08-15T04:30:00.000Z

All done. Final summary:

### Generation complete

**Test counts**
- Queue A (Difficulty): **46 tests** across 23/26 instances (≥2 each)
- Queue B (Corner): **57 tests** across 51/51 non-stub instances (≥1 each; the 8 `excluded_because:` stubs are not translated — their cross-references to difficulty instances all resolve)
- Total: **103 test functions**, 0 skips/xfail markers, all 124 PRD citations grep-verified verbatim, all modules import cleanly.

**Skipped difficulty instances (3)**
1. `priority_pair_validation_conflict/state_vs_fiscal_priority_on_contribution` — PRD does not uniquely derive the winner: §2.6 puts both `ERR_APPLICANT_NOT_ACTIVE` and `ERR_CONTRIBUTION_BELOW_MINIMUM` in step 10 "Domain rules," and §3.3 states the 100-cent minimum *before* the applicant-active rule, so a PRD-only reader could plausibly fire the fiscal error first. Not uniquely derivable.
2. `priority_pair_validation_conflict/safety_vs_referential_priority_on_pat` — contradicts PRD: §3.7 PAT scheduling states checks "in evaluation order" with `ERR_EVALUATOR_NOT_CERTIFIED` *before* `ERR_EVALUATOR_CONFLICT`; the instance asserts CONFLICT wins.
3. `cross_entity_state_dependency/pat_schedule_requires_class_in_session` — no PRD coverage: nothing in §3.7 or the §4 endpoint table gates PAT scheduling on the class being IN_SESSION; a PRD-only implementer could allow scheduling on any ENROLLED enrollment.

**Per-instance counts:** every covered difficulty instance has exactly 2 tests; every covered corner instance has 1 test except `applicant_creation_initial_state_and_system_fields` (2) and `class_capacity_full_boundary` (2).

**test_helpers/** (`/home/ubuntu/github/CodingPRD/tasks/task_1954_service_dog_training_placement_program/test_helpers/`): `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`. Key design points: `TrainingMilestone` TypedDict omits `updated_at`/`version` (PRD §2.4 append-only); `make_trainer/evaluator/applicant/puppy_raiser_headers(entity_id)` builders for the four entity-backed roles; composite fixtures walk the full pipeline to `setup_graduated_partnership`; timestamp assertions use instant/date-prefix comparison (not exact strings) because PRD §2.4 mandates three fractional digits while the clock default is written without them.

**test_suite/** (`.../test_suite/`): `conftest.py` plus `test_01_fundraising_requirements.py`, `test_02_training_and_state_cycles.py`, `test_03_pat_and_class_cascades.py`, `test_04_difficulty_boundaries_and_invariants.py`, `test_05_corner_entities_and_envelope.py`, `test_06_corner_state_machines.py`, `test_07_corner_calculations.py`, `test_08_corner_auth_and_ledger_guards.py`, `test_09_corner_capacity_and_graduation_gates.py`, `test_10_corner_occ_and_cascades.py`.

(Note: Step 5 required one resume — the first subagent run completed its PRD-first adjudication analysis but stopped before writing files; a resume message instructed it to write files incrementally, which it then did, including a third skip adjudication (pat_schedule_requires_class_in_session) discovered mid-write.)

## Step 6: Generate Implementation — 2026-08-15T04:45:00.000Z

All checks pass. The implementation is complete and verified.

### Files created (all under `/home/ubuntu/github/CodingPRD/tasks/task_1954_service_dog_training_placement_program/workspace/implementation/`)

| File | Role |
|---|---|
| `start.sh` | Executable launcher: guards `pip install` behind an `import flask` check, then `exec python3 app.py` (foreground, `$PORT` default 10000, binds `0.0.0.0`) |
| `requirements.txt` | `flask>=2.2,<4.0` |
| `app.py` | Flask app factory, blueprint registration, envelope-compliant error handlers (400/404/405/generic) |
| `core.py` | In-memory `STORE` dicts (empty at boot, no seeding), logical clock frozen at `2026-08-01T00:00:00Z`, response envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`), `ApiError`, auth (`X-User-ID`/`X-User-Role`, 8 roles), field validators, pagination |
| `services.py` | All 10 calculations (dual-variant fundraising requirement, rank score, health clearance with origin gates, rolling/cumulative milestone figures with renormalization, pinned per-section-then-average PAT scoring, selectors, sweep, refund clawback) plus cascade helpers (dissolve, withdraw, career-change, class-cancel, graduation) and 18 serializers |
| `routes_intake.py` | Clock + applicants + assessments + waitlist + contributions (27 endpoints) |
| `routes_program.py` | Raisers + trainers + dogs + screenings + placements + milestones (31 endpoints) |
| `routes_match.py` | Matches + classes + enrollments + PATs (23 endpoints) |
| `routes_aftercare.py` | Partnerships + follow-ups + recertifications + support requests (18 endpoints) |

### Endpoint coverage: 116 / 116
Verified programmatically: parsed the PRD §4 endpoint table (116 routes) and diffed against the Flask url_map — zero missing, zero extra API routes (only Flask's built-in `/static/<filename>` exists). Decimal/ROUND_HALF_UP arithmetic throughout; OCC fields `expected_class_version` / `expected_dog_version` / `expected_partnership_version` required and enforced at 412.

### Verification performed
Four self-written HTTP suites (≈180 assertions) run against fresh boots, all passing: full happy-path pipeline (intake → waitlist → funding → screening → placement → milestones → match → class → PAT → graduation → partnership → recert → support), PAT-fail/withdraw/class-cancel/career-change cascades, clock sweeps (FOLLOWUP missed at due+7d boundary, RECERT_DUE and pass-reset), selector tie-breaks (raiser nulls-last; match rank/listed_at/applicant-created_at), health-threshold boundaries (DONATED 84 pass / 82 fail; BRED CARRIER double-fail), the scaffold's pinned milestone example (cumulative 80.8 vs rolling 69.3 → no advancement), rounding precision (94.4/91.7/83.3 → 89.8), SoD conflicts, reopen-window ±14d boundary, OCC 412s, pagination defaults/clamps. `bash start.sh` verified on 4 fresh processes including default port 10000.

### PRD ambiguities resolved (concrete choices)
1. **Class start minimum size**: scaffold's error catalog said `< 2` but PRD says "minimum class size is one enrolled pair" → enforced `enrolled_count >= 1` (PRD wins).
2. **Enrollment creation window**: PRD silent → required class `ENROLLING` (else `ERR_INVALID_STATE`); also rejected a second ENROLLED enrollment per match.
3. **Assessment finalize `outcome` values** unpinned → accept `ACCEPT`/`ACCEPTED`/`FINALIZED_ACCEPTED` and `REJECT`/`REJECTED`/`FINALIZED_REJECTED`.
4. **Email uniqueness** has no catalog error → `ERR_VALIDATION` 400.
5. **Terminal lockdown scope**: applied to direct action endpoints on the resource; nested creates use their specific state errors (so contribution-create on DENIED/WITHDRAWN/PLACED → `ERR_APPLICANT_NOT_ACTIVE`, not `ERR_ALREADY_TERMINAL`). Assessment finalize and screening submit are not in the scaffold's terminal set → `ERR_INVALID_STATE` on replay.
6. **PAT evaluator buffer**: conflict iff |Δscheduled_at| < 90 min (occupied-window-vs-buffered-window semantics); exactly 90 min (= "windows exactly 30 minutes apart") allowed; INVALIDATED excluded.
7. **Timestamps**: all domain fields use the logical clock (3-fractional-digit `...Z`); only `meta.api_request_timestamp` uses wall clock.
8. **`version` starts at 1**, +1 per mutation including system cascades; rank recompute bumps only when the value changes.
9. **RECERT_DUE sweep guard**: flip only when no COMPLETED_PASS covers the current window (pass covers iff `completed_on + 365d > recert_due_at`), so a partnership can become RECERT_DUE again after an earlier pass — the literal "any pass since activation" reading would make re-expiry impossible.
10. **Entry creation honors the ledger invariant**: `raised_cents` = sum of already-RECEIVED contributions (pre-approval funding is legal), with immediate eligibility evaluation.
11. **Sub-resource GET lists** (non-paginated per the endpoint table's `input: []`) return plain array envelopes; only the 7 endpoints declaring `limit?`/`offset?` paginate.
12. **Direct match dissolve mid-class** leaves the ENROLLED enrollment untouched (the machine lists no enrollment link for direct dissolve).
13. **Career-change from MATCHED/TEAM_TRAINING**: match dissolve fires entry/applicant reverts but skips the dog revert (dog goes to CAREER_CHANGED).
14. **Unmarked endpoint-table inputs treated as required** (OCC fields, `resolution_note`, `reason`, `denial_reason`, etc.); milestone `career_change_recommended` surfaced on milestone responses per the calculation rule; `certified_tasks` updates don't bump `Dog.version` (only transitions do).

## Step 7: Run Tests and Iterate — 2026-08-15T05:05:00.000Z

**All 8 rounds pass 103/103.** The exit condition is met.

### Summary

**Iterations run:** 3 sweeps (8 parallel rounds each)
- Sweep 1: 98/103 per round — 5 tests failing deterministically across all 8 rounds
- Sweep 2: 102/103 per round — sole remaining failure was a `NameError` I had already fixed mid-sweep (edit landed after launch)
- Sweep 3: **103/103 in all 8 rounds — clean**

**Tests deleted:** none. Every failing test traced to a PRD-verbatim rule; all failures were repairable bugs.

**Fixes applied to `test_suite/` (the test layer):**
1. `/home/ubuntu/github/CodingPRD/tasks/task_1954_service_dog_training_placement_program/test_suite/test_07_corner_calculations.py` — `TestMatchSelectorTaskCoverage._dog_certified_retrieve_only(self)` referenced `api` without it in scope (`NameError`); threaded `api` through the helper signature and both call sites. The PRD §3.7 coverage-gap assertions (`ERR_NO_ELIGIBLE_MATCH`, `ERR_TASK_COVERAGE_INSUFFICIENT`) had never executed.
2. `/home/ubuntu/github/CodingPRD/tasks/task_1954_service_dog_training_placement_program/test_suite/test_08_corner_auth_and_ledger_guards.py` — added missing top-level imports `create_approved_raiser`, `create_certified_trainer`, and `create_cleared_dog` (the last one was a latent second `NameError` in `test_second_placement_on_placed_dog_rejected` that would have surfaced one line after the first fix). Assertions untouched.

**Fixes applied to `implementation/`:**
1. `/home/ubuntu/github/CodingPRD/tasks/task_1954_service_dog_training_placement_program/workspace/implementation/core.py` — added `"screenings": {"CLEARED", "FAILED"}` to `TERMINAL_STATES`, per PRD §3.5 verbatim: *"Both screening outcomes are terminal; a screening in `DRAFT` is the only submittable state."*
2. `/home/ubuntu/github/CodingPRD/tasks/task_1954_service_dog_training_placement_program/workspace/implementation/routes_program.py` — `submit_screening` now calls `check_terminal("screenings", s)` before the DRAFT from-state check, so a double submit on a `CLEARED` screening yields `ERR_ALREADY_TERMINAL` (§2.6 step 8 terminal lockdown precedes step 9 from-state membership) instead of `ERR_INVALID_STATE`. This corrects a scaffold-over-PRD decision recorded in the worklog; the PRD's explicit "both outcomes are terminal" sentence plus the pinned pipeline order uniquely determine the error.

No endpoints, fields, or side effects were added beyond PRD; no assertions were weakened; no skips/xfails introduced.

## Step 8: Finalize PRD — 2026-08-15T05:12:00.000Z

### Summary

**Result: PRD_FINALIZED.md is byte-identical to PRD.md — no edits were made.**

#### Line counts
- `PRD.md`: 389 lines
- `PRD_FINALIZED.md`: 389 lines
- Delta: 0 lines, 0.0%

#### Why no edits were warranted

The `<step_7_diff>` lists four fixes. The two test-suite fixes (`test_07` `NameError` threading `api` through a helper; `test_08` missing top-level imports) are explicitly pure test-code bugs with no PRD signal — no PRD edit traces to them.

The two implementation fixes were both analyzed against the PRD and found to be **already uniquely determined by existing PRD prose**, exactly as the Step 7 agent believed:

1. **`implementation/core.py:57`** — `TERMINAL_STATES["screenings"] = {"CLEARED", "FAILED"}`. PRD §3.5 (line 167) states verbatim: *"Both screening outcomes are terminal; a screening in `DRAFT` is the only submittable state."* The two outcomes are named in the immediately preceding sentences (`CLEARED` on pass, `FAILED` on fail). Terminality of screenings is PRD-verbatim; no edit.

2. **`implementation/routes_program.py:552`** — `submit_screening` calls `check_terminal("screenings", s)` before the `DRAFT` from-state check, so re-submitting a `CLEARED` screening yields `ERR_ALREADY_TERMINAL` (not `ERR_INVALID_STATE`). PRD §2.6 opens with *"Every request passes through a fixed pipeline of checks, evaluated in this order"* and pins step 8 (terminal lockdown, `ERR_ALREADY_TERMINAL`, 409) strictly before step 9 (from-state membership, `ERR_INVALID_STATE`, 409). Composed with §3.5's terminality declaration and §5's `ERR_ALREADY_TERMINAL | 409` catalogue entry, the error for a double submit is uniquely determined. The §4 endpoint-table row (`POST /api/screenings/{id}/submit | DRAFT → CLEARED or FAILED per clearance score; dog mirrors`) describes only the happy path and does not conflict. The test suite's `TestScreeningDoubleSubmitRejected` cites exactly these two PRD sections as authority. No edit.

#### Pre-edit search log

No edits were committed, so no (a)/(b)/(c) entries exist per the letter of the requirement. However, the mandatory enumeration was performed for the candidate edit subject (screening status/terminality and terminal-lockdown ordering) before concluding "no edit":

- **Subject:** screening entity status lifecycle, terminal states, and error choice on out-of-terminal transition.
- **Impl paths enumerated and read/grepped:** `core.py:50-66` (`TERMINAL_STATES`), `core.py:447-452` (`check_terminal`), all 47 `check_terminal` call sites across `routes_intake.py`, `routes_program.py`, `routes_match.py`, `routes_aftercare.py` (uniform step-8-before-step-9 pattern), `routes_program.py:420-431` (`begin_screening`), `routes_program.py:455-460` (`dog_screenings`), `routes_program.py:509-536` (`create_screening`), `routes_program.py:539-543` (`get_screening`), `routes_program.py:546-568` (`submit_screening`), `services.py:183-198` (`ser_screening`), plus PRD §2.6, §3.5, §4 (screening rows), §5, and `test_suite/test_06_corner_state_machines.py::TestScreeningDoubleSubmitRejected`.
- **Wording adjustment:** none — every enumerated path is consistent with the existing PRD prose, so any added wording would have been redundant churn; the looser-is-safer principle favors leaving the verbatim text untouched.

#### Files
- `/home/ubuntu/github/CodingPRD/tasks/task_1954_service_dog_training_placement_program/workspace/PRD_FINALIZED.md` (created; identical to `PRD.md`)

## Step 9: Complete PRD — 2026-08-15T05:25:00.000Z

All edits are in place. The diff shows exactly 25 single-paragraph hunks, line count unchanged (389 lines both), char delta +3425. The file is written at `/home/ubuntu/github/CodingPRD/tasks/task_1954_service_dog_training_placement_program/workspace/PRD_COMPLETED.md`.

### Summary

**Source vs output:** `PRD_FINALIZED.md` (identical to `PRD.md`) — 389 lines / 64,654 chars → `PRD_COMPLETED.md` — 389 lines / 68,079 chars (+3,425 chars; 25 in-place paragraph edits, no new sections).

**Counts:** 21 ambiguity-pins, 4 mismatch-revisions.

**Changes (one per bullet):**

- §2.2 — revise — mismatch — pagination-fields bullet scoped to "paginated top-level list endpoints" (nested collection endpoints omit them) — implementation/core.py:413-420, 221-233
- §2.3 — revise — mismatch — nested sub-resource collections return the full collection unpaginated (meta carries only request id/timestamp); also pins created_at tie-break by creation order — implementation/core.py:402-420
- §2.4 — insert — ambiguity — `version` starts at 1 at creation — implementation/core.py:183
- §2.5 — revise — ambiguity — clock-advance rank recompute applies to non-`CLOSED` entries only — implementation/services.py:860-866
- §2.8 — revise — ambiguity — RECERT_DUE sweep uses full-timestamp strictly-later-than comparison vs `recert_due_at`; rank recompute non-`CLOSED` — implementation/services.py:839, 860-866
- §3.1 — insert — ambiguity — duplicate `email` rejected with `ERR_VALIDATION` — implementation/routes_intake.py:109-111
- §3.1 — insert — ambiguity — resubmit from any non-`NEEDS_INFO` state (terminal `DENIED`/`WITHDRAWN` included) → `ERR_INVALID_STATE` — implementation/routes_intake.py:193-194
- §3.1 — insert — ambiguity — finalize `outcome` vocabulary pinned (`ACCEPT`/`ACCEPTED`/`FINALIZED_ACCEPTED`, `REJECT`/`REJECTED`/`FINALIZED_REJECTED`; else `ERR_VALIDATION`); non-`DRAFT` finalize → `ERR_INVALID_STATE` — implementation/routes_intake.py:380-389
- §3.1 — insert — ambiguity — approve responds 200 carrying the updated applicant (not the created entry) — implementation/routes_intake.py:243
- §3.2 — revise — mismatch — entry created with `raised_cents` seeded from the ledger invariant (sum of `RECEIVED` contributions, possibly nonzero pre-approval) and eligibility evaluated immediately (can be created `ELIGIBLE` with applicant mirrored to `MATCH_ELIGIBLE`); replaced "raised_cents 0" — implementation/routes_intake.py:217-242
- §3.3 — insert — ambiguity — applicant-active check (`ERR_APPLICANT_NOT_ACTIVE`) enforced before minimum-amount check (`ERR_CONTRIBUTION_BELOW_MINIMUM`) — implementation/routes_intake.py:488-499
- §3.4 — revise — mismatch — SUSPENDED-trainer exclusion enforced at milestone recording (acting Trainer) and open-enrollment lead check (`ERR_INVALID_STATE`); evaluator duty fails with `ERR_EVALUATOR_NOT_CERTIFIED`; class creation may still name a suspended lead — implementation/routes_program.py:726-729, implementation/routes_match.py:280-282, 577-586
- §3.4 — insert — ambiguity — sire/dam reference resolution applies only on the BRED track; on DONATED any supplied sire_id/dam_id is itself `ERR_DONOR_LINEAGE_INVALID` without resolution — implementation/routes_program.py:317-351
- §3.5 — insert — ambiguity — screening creation rejects any non-`IN_HEALTH_SCREENING` dog status, terminal included, with `ERR_INVALID_STATE` — implementation/routes_program.py:519-520
- §3.6 — insert — ambiguity — explicit-pick region check (`ERR_VALIDATION`) evaluated before status/capacity check (`ERR_RAISER_CAPACITY`) — implementation/routes_program.py:590-601
- §3.6 — insert — ambiguity — placement `started_on`/`ended_on` are ISO calendar dates (YYYY-MM-DD) from the logical clock — implementation/routes_program.py:631, implementation/services.py:209-210
- §3.6 — insert — ambiguity — `certified_tasks` serializes as an alphabetically sorted array — implementation/services.py:178
- §3.7 — insert — ambiguity — a match that already has an `ENROLLED` enrollment is rejected with `ERR_INVALID_STATE` — implementation/routes_match.py:382-383
- §3.7 — insert — ambiguity — `GRADUATED`/`FAILED`/`WITHDRAWN` declared terminal for enrollments (`ERR_ALREADY_TERMINAL` on further transitions) — implementation/core.py:60, implementation/routes_match.py:427
- §3.7 — insert — ambiguity — graduation responds 201 carrying the created `Partnership` — implementation/routes_match.py:524
- §3.7 — insert — ambiguity — scheduled PAT carries `section_percents`/`official_score`/`passed_gates` null until scoring — implementation/routes_match.py:630-633
- §3.7 — insert — ambiguity — `exercise_scores` payload shape pinned: exactly 12 object entries `{exercise_code, raw_score int 0-3}`, each code exactly once, else `ERR_VALIDATION` — implementation/routes_match.py:650-667
- §3.8 — insert — ambiguity — reinstate lands `RECERT_DUE` when current logical time is strictly later than `recert_due_at` (full-timestamp comparison) — implementation/routes_aftercare.py:93
- §3.8 — insert — ambiguity — partnership dissolve requires a payload `reason` — implementation/routes_aftercare.py:127-128
- §3.8 — insert — ambiguity — recert window computed on the calendar date of `recert_due_at` ±30 days inclusive — implementation/routes_aftercare.py:274-276
- §3.9 — insert — ambiguity — triage `priority` uses the same `LOW`/`MEDIUM`/`HIGH`/`URGENT` vocabulary as `severity` — implementation/routes_aftercare.py:419

The most substantive fix is the §3.2 mismatch: the PRD claimed waitlist entries are created with `raised_cents` 0 and status `PENDING`, but the implementation seeds `raised_cents` from the pre-approval ledger (contributions may be recorded/received while the applicant is still in intake) and evaluates eligibility immediately at creation.
