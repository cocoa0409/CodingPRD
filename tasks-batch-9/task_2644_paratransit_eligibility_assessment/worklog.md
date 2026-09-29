# Worklog — task_2644_paratransit_eligibility_assessment

## Step 1: Create task directory — 2026-09-03T23:56:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2644_paratransit_eligibility_assessment` and its `workspace/` subdirectory. Index 2644 was pre-assigned by the orchestrating harness; no index scan was performed (other pipelines run concurrently on this host).

## Step 2: Generate scaffold — 2026-09-04T01:32:00.000Z

All three scaffold artifacts for task 2644 are complete and the linter is clean.

Verdict block (verbatim, final run):

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2644_paratransit_eligibility_assessment/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2644_paratransit_eligibility_assessment/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2644_paratransit_eligibility_assessment/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    57
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     64
  Calls scanned (§1.8+§1.9):  1043

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2644_paratransit_eligibility_assessment/`):
- `SCAFFOLD.yaml` — 3084 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1416 lines
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4560 lines

Contents:
- §1.1–§1.7: 14 entities, 10 state machines (parallel shape; Application, FunctionalAssessment two-dimensional), 2 OCC concurrency rules, 13 calculations, 54 ordered validations, 57 endpoints, 62 errors, 8 roles (segregation_of_duties model).
- §1.8: 9 rule_ids × 2 instances = 18 active difficulty instances.
- §1.9: 76 instances across all nine sections — 64 active with full `test_recipe`s and 12 `excluded_because` stubs, every stub citing a real §1.8 instance name. Per section: entities 14, state_machines 12 (9 active), calculations 11 (8), validations 16 (14), endpoints 4, errors 8 (5), rbac 3, cross_cutting_complexity_layers 7 (6), consistency_model 1.

Verification beyond the lint: `SCAFFOLD.yaml` contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`; each design file has exactly one top-level key; all 76 corner instance names are unique and disjoint from the 18 difficulty names; every one of the 62 catalog error ids now has at least one triggering instance or a documented difficulty-design owner.

Two semantic hazards found in `SCAFFOLD.yaml` while writing recipes, handled in the design rather than by editing the scaffold: `ERR_DUE_PROCESS_INCOMPLETE` (priority 47) is dominated by priority 33 `ERR_PROCEEDING_STATE_INVALID` on every decide path, so it is documented as a defense-in-depth guard and asserted as a 409 instead; and `ERR_VISITOR_DAYS_EXHAUSTED` can only be observed if the 21 service days are recorded in descending date order, otherwise the priority-34 `ERR_VISITOR_RECORD_INACTIVE` masks it.

## Step 3: Copy shared files — 2026-09-04T01:32:30.000Z

Copied `./INSTRUCTION.md` to `tasks/task_2644_paratransit_eligibility_assessment/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T01:49:00.000Z

PRD complete and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2644_paratransit_eligibility_assessment/workspace/PRD.md` — **476 lines / 101,695 bytes**, ending at a real section boundary (last row of the §5 error table).

**Section list**
- `# Paratransit Eligibility Assessment API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 User and Role-Based Access Control; 2.2 API Response Structure; 2.3 Pagination; 2.4 Record Identity, Timestamps and Version Semantics; 2.5 Request Screening Order and Path Resolution; 2.6 Optimistic Concurrency on Packets and Rider Records; 2.7 The Logical Clock and the Day-Close Sweep; 2.8 Day Counting, Rounding and Window Arithmetic; 2.9 Segregation of Duties Across the Certification Chain; 2.10 Derived Mirrors and Conserved Quantities
- `## 3. Business Logic & Workflows` — 3.1 Registering a Rider and Opening the Intake Packet; 3.2 Submission, Return for Incomplete Items, and the Statutory Clock; 3.3 Professional Verification of Functional Limitations; 3.4 Publishing Assessment Slots, Booking the Assessment, and the Provided Ride; 3.5 Attendance, Scoring and Independent Sign-Off; 3.6 Drafting and Issuing the Determination; 3.7 Trip-by-Trip Conditions, Travel Training and Fixed-Route Competency; 3.8 Appeals and Independent Review; 3.9 Trip Conduct, No-Show Points and Suspension Due Process; 3.10 Visitor Eligibility for Out-of-Area Riders
- `## 4. Endpoint Definitions`
- `## 5. Error Code Catalogue`

**Coverage confirmation**
- **Endpoints: 57/57.** Programmatic check — every `endpoints[].path` from the scaffold appears backticked in the §4 table; table has 57 data rows and exactly 4 columns (Method, Path, Description, Authorized Role(s)).
- **Error IDs: 62/62.** Every `errors[].id` appears in the §5 table with its scaffold `http` status; 62 data rows, exactly 2 columns.

**Hard Contract reports (transcript only — no audit footer was written into PRD.md)**
- **Contract 1 — Field-Name Coverage: PASS.** Two independent passes. Pass 1 against a pre-built 167-token requirement list: 0 missing. Pass 2 re-derived from the scaffold (all `entities[].fields[].name`, all `endpoints[].input`/`query` keys stripped of `?`, all `{path}` variables = 150 identifiers): 0 missing. Two gaps were found and repaired during verification: `verification_id` (added to §2.5 stage 8 parentage rule) and the `outcome` enum literal `ACCEPTED` (added to §3.3, which previously only said "the accepted branch"). A third pass over every uppercase symbol anywhere in the scaffold left only non-enum artifacts unmatched (`YYYY`, `ALL`, `ASC`, `RESET`, `CASCADE`, `DISTANCE_FLOOR_M`, `DISTANCE_CEILING_M`, `TERM_DAYS`, `VISITOR_DAYS_ALLOWED`, `EVALUATOR_BUFFER_MINUTES`, and prose-emphasis words) — internal constant names and sketch prose, whose *values* (400/800, 1825/1095/180/0, 21, 15 minutes) are all documented.
- **Contract 2 — Rule Coverage: PASS.** All 54 validations (priorities 1–69) are in narrative; all 62 error ids are triggered somewhere in §2/§3; both OCC rules in §2.6; all 13 calculations including the pinned orderings (no-show ratio pool-once/divide-once/round-half-up-to-1dp, visitor 5-step accounting, day-close step-3-before-step-4); both multi-hop cascades verified present (3-hop expiry with `ELIGIBILITY_LAPSED`, 4-hop appeal remedy with `APPEAL_REMEDY` + `CONDITIONAL_ELIGIBILITY_AUTO`); the `days_served + days_forgiven == duration_days` conservation invariant and `suspension_days_ledger_total`; sibling-branch symmetry on the verification accepted/insufficient pair and the hearing/paper-review pair. No fuzzy quantifiers remain (an earlier "roughly six months" was replaced).
- **Contract 3 — §3 Path Purity: PASS.** Scan of lines 160–344 (`## 3.` through `## 4.`): 0 backticked tokens beginning with `/`, 0 bare HTTP methods, 0 method+path combinations, and 0 unbackticked `METHOD /path` strings.

Two notes on judgment calls made while writing §4: descriptions were rewritten as one-line minimal summaries rather than copied from the scaffold, because the scaffold's own descriptions leak side effects and enum branch behavior that SKILL.md §4 forbids in the table; and the intro paragraph states explicitly that the status code follows the addressed resource, not the cascade behind it, since several 200 endpoints (appeal decision, determination issue) create records as side effects.

**Orchestrator truncation check (per harness instruction):** independently verified — `wc -l` = 476; `tail -12` ends on a complete `| ERR_SUSPENSION_START_IN_PAST | 422 |` table row, not mid-sentence; all five `## ` section headers present at lines 3, 11, 160, 345, 409. Not truncated; no regeneration needed.

## Step 6: Generate implementation — 2026-09-04T02:26:00.000Z

The implementation is complete and verified.

## Files (23 files, 3,781 lines) — all under `/home/ubuntu/github/CodingPRD/tasks/task_2644_paratransit_eligibility_assessment/workspace/implementation/`

| file | lines | role |
|---|---|---|
| `start.sh` | 10 | guarded `pip install` (`if ! python3 -c "import flask"`) + `exec python3 app.py` |
| `requirements.txt` | 1 | `Flask==3.0.3` |
| `app.py` | 70 | blueprint registration, error handlers, `0.0.0.0:$PORT` (default 10000) |
| `store.py` | 162 | 14 in-memory dicts, logical clock, id/date helpers |
| `errors.py` | 93 | all 62 error IDs -> HTTP status |
| `envelope.py` | 79 | `meta`/`response_type`/`data`, offset pagination |
| `shapes.py` | 245 | enums + stage-9 request-shape validators |
| `lookups.py` | 149 | stage 6-8 path/body/parentage resolution |
| `auth.py` | 105 | stages 1-5 (`X-User-ID`/`X-User-Role`) |
| `owners.py` | 82 | ownership resolvers for the 15 guarded ops |
| `conduct.py` | 157 | 90-day window, points, ratio (`Decimal` ROUND_HALF_UP), ladder, ledger |
| `mirrors.py` | 130 | slot/vehicle/rider/determination derived mirrors, cascades |
| `serializers.py` | 350 | all 14 entity representations |
| `routes/reads.py` | 281 | 22 GETs |
| `routes/intake.py` | 282 | 6 |
| `routes/scheduling.py` | 401 | 8 |
| `routes/determinations.py` | 281 | 3 |
| `routes/appeals.py` | 227 | 4 |
| `routes/conduct_routes.py` | 280 | 7 |
| `routes/training.py` | 105 | 3 |
| `routes/visitors.py` | 98 | 2 |
| `routes/ops.py` | 193 | 2 (clock + day-close) |
| `routes/__init__.py` | 0 | package marker |

## Endpoint count: 57/57 (22 GET + 35 POST), confirmed from Flask's `url_map`.

## Smoke test (`PORT=18644 bash start.sh`, then killed by pid/port only)

Full lifecycle end-to-end, all as expected:
- Intake: rider 201 -> packet 201 (DRAFT) -> submit 200 (due date `submitted_at`+21) -> re-submit 409 -> verification 201 -> duplicate request 409 `ERR_VERIFICATION_PENDING` -> receive ACCEPTED 200 (packet -> `ASSESSMENT_REQUIRED`, `attests_permanent` copied, version 4).
- Scheduling: slot 201, back-to-back slot 409 `ERR_EVALUATOR_SLOT_CONFLICT`; booking -> slot `booked_count` 1/FULL; vehicle lanes 1/0 -> overlapping wheelchair 409 `ERR_VEHICLE_WINDOW_CONFLICT`, same-window ambulatory 201, touching window 201, late window 422 `ERR_PICKUP_WINDOW_LATE`; cancel releases exactly one lane, re-cancel 409; `ATTENDED` completed both remaining rides (lanes back to 0/0); `NO_SHOW` regressed the packet to `ASSESSMENT_REQUIRED` and freed the seat.
- Scoring/sign-off: score 400 on out-of-range value; `UNCONDITIONAL`/1825 recommendation; self sign-off blocked (`ERR_SIGNOFF_NOT_INDEPENDENT` path), specialist sign-off -> packet `ASSESSMENT_COMPLETE`.
- Determination: `ERR_CONDITIONAL_REQUIRES_CONDITIONS` 422, stale version 412, draft 201, issue 200 (`expires_at` = effective+1095), rider mirrors `ELIGIBLE`/`CONDITIONAL`, trip-eligibility check true on 99F and `NO_CONDITION_MET` on 70F.
- Appeals: filed 200 (`under_appeal` true), non-independent reviewer 422, wrong reviewer 403 `ERR_NOT_ASSIGNED_REVIEWER`, hearing scheduled, day-close step 1 advanced to `HEARD` (`decision_due_date` = +30), `OVERTURNED` vacated the old determination and created the `APPEAL_REMEDY` successor with `trip_condition_count` 0 and term 1825.
- Conduct: 3 no-shows -> 6 points, 3 misses, ratio 100.0, auto `PROPOSED` proceeding (`AUTO_THRESHOLD`); decide before response 409; uphold -> 7-day ladder, end = start+6, ledger 7; day-close carried it `UPHELD_PENDING -> ACTIVE` (`service_status` SUSPENDED, 1+6) then `-> SERVED` (7+0) — `days_served + days_forgiven == duration_days` held at every step.
- Training: auto referral from the CONDITIONAL issuance -> ENROLLED -> complete(85) flipped rider competency true and mirrored onto the issued determination; re-complete 409.
- Visitors: local rider 422 `ERR_NOT_OUT_OF_AREA`; out-of-area 201 (rider -> VISITOR, 0/21); early date 422 `ERR_SERVICE_DATE_OUT_OF_RANGE`; duplicate date idempotent; 21st day -> `EXHAUSTED`, 22nd 422 `ERR_VISITOR_RECORD_INACTIVE`.
- Sweep: presumptive granted at 22 days pending (count 1), zero on the second call at the same clock; determination expiry cascade set the rider to `EXPIRED`/null/null; a third call returned all six counters zero — idempotent at a fixed clock.
- Auth: missing headers 401, wrong role 403, unknown id 404 with the entity-specific code, `limit=0` 400 `ERR_INVALID_PAGINATION`.
- Fresh boot: relaunched on the same port, `total_count` 0 and clock back to `2026-08-01T00:00:00.000Z`, day-close 200 on an empty store. Shut down cleanly; port 18644 free. No broad `pkill` was used.

Audits: no `sqlite`/`open(`/`json.dump`/`/tmp` anywhere; no seeding — the only matches were comments stating the store starts empty. Two smoke-test payload mismatches I hit were my curl's fault, not the code's (`mobility_aid`, `vehicle_number`, `attendance_status` and the five questionnaire keys all match the PRD verbatim).

## Step 5: Generate unit tests — 2026-09-04T03:18:00.000Z

Generation is complete. Both directories are at the task root (`/home/ubuntu/github/CodingPRD/tasks/task_2644_paratransit_eligibility_assessment/`), and `ls -d workspace/test_*` reports **no match** — nothing was written under `workspace/` at any point.

## Files and line counts

`test_helpers/` (Stage 1, 2,777 lines)
| file | lines |
|---|---|
| `__init__.py` | 35 |
| `api_client.py` | 374 |
| `api_errors.py` | 176 |
| `assertions.py` | 565 |
| `constants.py` | 139 |
| `factories.py` | 406 |
| `fixtures.py` | 457 |
| `test_users.py` | 108 |
| `types.py` | 517 |

`test_suite/` (Stage 2, 8,493 lines, 102 tests)
| file | lines | tests |
|---|---|---|
| `conftest.py` | 54 | — |
| `test_01_dual_variant_calc.py` | 236 | 5 |
| `test_02_combinatorial_formula.py` | 188 | 4 |
| `test_03_non_linear_state_machine.py` | 257 | 5 |
| `test_04_transitive_cascade.py` | 275 | 4 |
| `test_05_priority_pair_validation_conflict.py` | 272 | 4 |
| `test_06_boundary_precision_check.py` | 205 | 4 |
| `test_07_cross_entity_state_dependency.py` | 264 | 4 |
| `test_08_resource_temporal_overlap.py` | 244 | 4 |
| `test_09_compensating_invariant.py` | 301 | 4 |
| `test_10_entities.py` | 628 | 13 |
| `test_11_state_machines.py` | 959 | 9 |
| `test_12_calculations.py` | 795 | 8 |
| `test_13_validations.py` | 1459 | 14 |
| `test_14_endpoints.py` | 470 | 4 |
| `test_15_errors.py` | 485 | 5 |
| `test_16_rbac.py` | 374 | 3 |
| `test_17_complexity_layers.py` | 737 | 6 |
| `test_18_consistency_model.py` | 290 | 2 |

## Coverage tally

**Queue A (SCAFFOLD_DIFFICULTY_DESIGN, §1.8): 18/18 instances translated, 0 skipped, 38 tests.** One file per difficulty rule; the multi-test files split an instance's independent observable outcomes rather than duplicating a tag.

**Queue B (SCAFFOLD_CORNER_DESIGN, §1.9): 63/64 non-stub instances translated, 1 skipped, 64 tests.** By section — entities 13 translated (1 skip), state_machines 9, calculations 8, validations 14, endpoints 4, errors 5, rbac 3, cross_cutting_complexity_layers 6, consistency_model 1 instance rendered as 2 tests. The 12 `excluded_because:` stubs were deliberately left untranslated; every stub's `difficulty_instance` cross-reference was verified to resolve to a real queue-A instance that is itself translated.

**The one skip:** `Corner/entities/application_create_missing_functional_answers_is_invalid_request` — PRD §3.1 states a packet may be created and left in `DRAFT` with an incomplete questionnaire, so the five-key test bites at submission, not at creation. The instance's asserted 400 is not PRD-derivable; per the skip rule the gap stays a gap (no xfail, no weakened assertion, no placeholder).

## Verification passes (all green)

- Tag pass: 102/102 tests carry exactly one trailing `Design:` line, correct shape, and a name resolving verbatim into one of the two design YAMLs. No untagged, dual-tagged, or dangling tags.
- PRD-citation pass: every docstring quote >=40 chars survives literal whitespace-normalized grep against `workspace/PRD.md`. No short/decorative quotes.
- Symbol pass: all 499 `api.<method>` / `factories.<fn>` references resolve against `ApiClient` and `factories`; every imported symbol exists; no unused imports.
- `pytest test_suite --collect-only -q` -> **102 tests collected**, no collection errors.

Two notes for the implementation side. First, `GET /applicants/{id}/suspension-proceedings` declares a `status?` filter in SCAFFOLD that the PRD never mentions, so the suite deliberately asserts only on unfiltered listings and single-resource GETs there — no test depends on that filter's semantics. Second, the suite pins the §2.5 stage order in several places, notably that stage 12 (version reconciliation, 412) outranks stage 13 (business rules, 422) and that stage 11 (`ERR_PROCEEDING_STATE_INVALID`, 409) outranks a 422 response-window violation; an implementation that validates the body before the version will fail those.

**Orchestrator note:** Steps 5 and 6 were launched back-to-back as background agents rather than in one message; the impl generator was explicitly forbidden from reading `test_suite/`/`test_helpers/` in its prompt, and it reported no such reads, so isolation held.

## Step 7: Run tests and iterate — 2026-09-04T03:40:00.000Z

Clean sweep achieved. Final report:

## Summary

**Iterations run:** 2 (each an 8-round parallel sweep under `setsid nohup`).

Iteration 1: 98/102 in all 8 rounds — 4 deterministic failures, **zero flakiness** (identical failing set in every round).

**Tests deleted:** none. All four failures traced to test-artifact bugs or a real implementation ordering defect; no assertion was found to be PRD-silent or non-uniquely-derivable.

**Fixes applied to `test_suite/`** (no `test_helpers/` change was needed — the bugs were in the test functions themselves, not shared fixtures):

1. `test_suite/test_12_calculations.py` — `test_an_appeal_becomes_overdue_only_the_day_after_its_deadline` called `api.get_appeal(..., CLERK_HEADERS)` twice. PRD §4 authorizes `GET /appeals/{id}` for `Applicant`, `EligibilitySpecialist`, `IndependentReviewer`, `AccessibilityOfficeAdmin` — **not** `IntakeClerk`. The implementation's `@require` tuple in `routes/reads.py` matches PRD verbatim, so the request identity was the bug. Switched to `ADMIN_HEADERS` (added the import).
2. `test_suite/test_13_validations.py` — `test_four_appeal_guards_fire_where_the_screening_order_puts_them`: same wrong-role `get_appeal(..., CLERK_HEADERS)` -> `ADMIN_HEADERS`.
3. `test_suite/test_13_validations.py` — `test_the_sign_off_gate_answers_before_the_category_condition_coupling` asserted `ERR_ASSESSMENT_NOT_SIGNED_OFF` (422) on a draft attempt against a packet in `ASSESSMENT_SCHEDULED`. PRD §3.6 states verbatim: *"drafting against a packet in any other status is `ERR_INVALID_APPLICATION_STATE` (409)"*, and §2.5 puts that state precondition at stage 11, ahead of the stage-13 evidentiary check. Corrected the expected error to `ERR_INVALID_APPLICATION_STATE`/409 and swapped the docstring quote to the governing sentence. The test's remaining substance (the coupling checks `ERR_CONDITIONAL_REQUIRES_CONDITIONS` and `ERR_UNCONDITIONAL_FORBIDS_CONDITIONS` firing only after sign-off) is untouched, so the precedence claim survives in PRD-faithful form. Removed the now-unused import.

**Fix applied to `implementation/`:**

4. `workspace/implementation/routes/determinations.py`, `issue_determination()` — the parent-packet `ASSESSMENT_COMPLETE` check ran *before* the determination's own `DRAFT` check, so re-issuing an already-issued determination returned `ERR_INVALID_APPLICATION_STATE`. Under that ordering `ERR_DETERMINATION_ALREADY_ISSUED` is **structurally unreachable** — issuance always drives the packet to `DETERMINED`, so both of the code's two PRD-declared triggers become dead. Reordered so the determination's issuance status (stage 11 for the entity being driven, and the first condition stated in PRD §3.6's issuance paragraph) is screened first, with the parent-packet requirement following as the stage-13 *cross-entity referential requirement* §2.5 explicitly classifies it as. Verified no other test exercises the issue endpoint's error path — all other `issue_determination` call sites are success paths.

**Final sweep evidence** (8 complete result files, written 03:32):

| round | passed/total | failed | errors | skipped |
|---|---|---|---|---|
| 1 | 102/102 | 0 | 0 | 0 |
| 2 | 102/102 | 0 | 0 | 0 |
| 3 | 102/102 | 0 | 0 | 0 |
| 4 | 102/102 | 0 | 0 | 0 |
| 5 | 102/102 | 0 | 0 | 0 |
| 6 | 102/102 | 0 | 0 | 0 |
| 7 | 102/102 | 0 | 0 | 0 |
| 8 | 102/102 | 0 | 0 | 0 |

Test count is still 102 (`grep -c "^def test_"` across `test_suite/`), so nothing was dropped, and `grep` for `pytest.mark.skip`/`xfail` across `test_suite/` and `test_helpers/` returns 0 matches — the clean sweep is not the result of suppressed tests.

**Orchestrator independent verification (per memory of a prior pipeline that claimed a clean sweep with no artifacts):** re-ran `ls -la` on the eight `results.*.json` (all present, ~30KB each, mtime 03:32) and parsed each with `json.load` — every round reports `passed=102 total=102 failed=0 errors=0 skipped=0`. `grep -c "^def test_"` summed to 102 and the skip/xfail grep returned 0. Evidence confirmed first-hand, not taken on the subagent's word.

## Step 8: Finalize PRD — 2026-09-04T03:45:00.000Z

Done. Two surgical edits; PRD_FINALIZED.md is 476 lines (same as PRD.md, 0.0% line delta — both edits extend existing paragraphs in place), and the file still ends at the §5 Error Code Catalogue table's last row.

## Changes

- **§3.6 (issuance paragraph, line 255)** — revise — pinned the guard order and the two previously code-less packet requirements at issuance: the determination's own `DRAFT`/no-other-`ISSUED` screen (`ERR_DETERMINATION_ALREADY_ISSUED` 409) runs *before* the parent-packet checks, and the packet checks now name their codes — `ERR_INVALID_APPLICATION_STATE` (409) for a packet not in `ASSESSMENT_COMPLETE`, `ERR_ASSESSMENT_NOT_SIGNED_OFF` (422) for the missing single attended/signed-off assessment; the coupling re-check is stated as following them — `implementation/routes/determinations.py:140-155`.
- **§2.5 (stage-11 ordering sentence, line 108)** — insert — added two sentences scoping the within-stage-11 ranking to records the addressed operation actually drives, and classifying a status requirement on a *different* record (parent packet at issuance) as a stage-13 cross-entity requirement screened afterwards. Without this, the unmodified §2.5 sentence ("the application's own workflow status is checked first … then a determination's issuance status") reads as mandating exactly the ordering Step 7 removed from `implementation/routes/determinations.py:140-146`.

No PRD edit was made for Step 7 items 1-3: those were test-artifact bugs against behavior PRD already determines (verified `GET /appeals/{id}` in `implementation/routes/reads.py:203-204` carries exactly PRD §4's four roles, and `draft_determination` at `implementation/routes/determinations.py:80-85` screens status 409 -> version 412 -> sign-off 422, matching §3.6 plus §2.5 stages 11/12/13 verbatim).

## Per-edit pre-edit search log

**Edit 1 — §3.6 issuance**
- (a) Subject: relative order and error codes of the guards on `POST /determinations/{id}/issue`, i.e. every place a determination's own status and its parent application's status are both consulted.
- (b) Paths enumerated: grepped all of `implementation/` for `ERR_INVALID_APPLICATION_STATE`, `ERR_DETERMINATION_ALREADY_ISSUED`, `ERR_ASSESSMENT_NOT_SIGNED_OFF`, `ERR_INVALID_ASSESSMENT_STATE`, `ERR_VERIFICATION_STATE_INVALID`, then read each hit: `routes/determinations.py` `draft_determination` (80-91) and `issue_determination` (140-155) plus the shared `_signed_off_assessment` helper (21-29); `routes/intake.py:143,180,206` (submit / return-incomplete / request-verification) and `receive_verification` (242-275); `routes/scheduling.py:118` (`book_assessment`), `:289,296` (attendance), `:353,355` (scores), `:385` (sign-off); and `grep raise ApiError` across `routes/appeals.py`, `routes/training.py`, `routes/visitors.py`. `issue_determination` is the only endpoint that checks a determination's status alongside its parent packet's; the shared sign-off predicate is the same "exactly one ATTENDED + SIGNED_OFF" helper used by drafting.
- (c) Adjustments: scoped the new order claim to "Its substantive guards … stated here" rather than a global precedence rule, so the draft endpoint's PRD-stated app-status-first order is untouched; described the evidentiary check as "the same single attended, signed-off assessment the drafting step required" instead of restating the predicate, so it cannot diverge from `_signed_off_assessment`'s exactly-one semantics; said the coupling is re-checked "after those" rather than reordering it.

**Edit 2 — §2.5 stage-11 sentence**
- (a) Subject: what the within-stage-11 entity ordering governs, and where a cross-record status requirement sits.
- (b) Paths enumerated: same sweep as above, re-checked for any endpoint that screens a *non-driven* record's status ahead of the driven record's — `routes/intake.py` `receive_verification` (verification is the only status checked; app status untouched), `routes/scheduling.py:118` (`book_assessment`: driven application first, then `ERR_SLOT_FULL` capacity), `routes/appeals.py:47` (determination appealability, no competing appeal status), `routes/training.py:69-77` (referral status first, then the determination-category guard), `routes/visitors.py:69-84` (record `ACTIVE` first, then range/allowance). None contradicts "driven record's own status first".
- (c) Adjustments: left the original enumeration byte-identical and appended rather than rewrote; used "the addressed operation actually drives" plus a single illustrative "for instance" rather than an exhaustive list, so no other endpoint's ordering is implicitly re-specified.

**Orchestrator verification:** `wc -l` on both files = 476/476; `diff PRD.md PRD_FINALIZED.md` shows exactly two changed lines (108 and 255), both in-paragraph extensions, no section added or removed; tail still lands on the final error-table row.

## Step 9: Complete PRD — 2026-09-04T04:16:00.000Z

Run as **three sequential file-partitioned passes** over `implementation/` rather than one pass, because a single-pass Step 9 has previously produced a PRD_COMPLETED.md byte-identical to its source (i.e. the scan silently never ran). Partition: pass A = cross-cutting core (`app.py`, `auth.py`, `envelope.py`, `errors.py`, `shapes.py`, `lookups.py`, `owners.py`, `store.py`, `serializers.py`); pass B = `routes/intake.py`, `routes/scheduling.py`, `routes/determinations.py`; pass C = `routes/appeals.py`, `routes/conduct_routes.py` + `conduct.py`, `routes/training.py`, `routes/visitors.py`, `routes/ops.py` + `mirrors.py`, `routes/reads.py`. Pass A owned the `cp`; B and C edited in place and each verified the prior passes' edits survived.

**Totals: 66 edits — 55 ambiguity-pins, 11 mismatch-revisions.** PRD_FINALIZED.md 476 lines / 102,854 chars -> PRD_COMPLETED.md 477 lines / 121,106 chars (+1 line, **+18,252 chars**). Only one line was added (a new bullet in §2.2); everything else is in-paragraph.

### Pass A — cross-cutting core (17 edits: 16 ambiguity, 1 mismatch)
- §2.1 — insert — ambiguity — stage 1 is a header-*presence* test with exact case-sensitive role matching, so an empty/whitespace `X-User-ID` passes authentication and is caught only at stage 4 — `auth.py:36-39`, `shapes.py:8-17`
- §2.1 — insert — ambiguity — ownership on the two path-less listings (applications, determinations) is evaluated against the `applicant_id` query filter; omitting the filter passes and scopes implicitly to the acting rider — `owners.py:78-82`
- §2.1 — revise — ambiguity — defined "cannot supply a comparable actor identity" as an `X-User-ID` present but empty/whitespace-only — `auth.py:69-72`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars from A-Z/0-9 — `store.py:57-58`
- §2.2 — insert — ambiguity — pre-dispatch failures use `ERR_INVALID_REQUEST`: unknown path 404, bad method 400, unexpected fault 500 (the only non-400 uses of that code) — `app.py:50-60`
- §2.3 — insert — ambiguity — pagination values parsed as base-10 ints with whitespace trimmed; present-but-empty/decimal/boolean forms rejected; absent takes default; offset past `total_count` yields empty page with `has_more` false — `envelope.py:36-73`
- §2.3 — insert — ambiguity — `created_at` ties break by server creation sequence, making every ordering total and stable — `store.py:160-162`
- §2.4 — revise — ambiguity — `id` published as canonical lowercase hyphenated 36-char UUID — `store.py:50-52`
- §2.4 — revise — ambiguity — `updated_at` stamped equal to `created_at` at creation — `store.py:145-150`
- §2.5 stage 3 — insert — ambiguity — stage skipped for staff roles; an unresolvable path/body reference makes ownership undeterminable and falls through to the stage 6/7 404; the query-filter form still 403s on a nonexistent rider — `auth.py:59-63,95`, `owners.py:25-82`
- §2.5 stage 5 — insert — ambiguity — a nonexistent appeal falls through to `ERR_APPEAL_NOT_FOUND`; a null `reviewer_user_id` refuses every actor with `ERR_NOT_ASSIGNED_REVIEWER` (precedes the 409 state check) — `auth.py:76-84`
- §2.5 stage 9 — insert — ambiguity — body must be a JSON object (absent/empty read as `{}`); explicit `null` on an optional field == omitted; strict boolean/integer typing with decimals allowed only for `threshold_value` and trip-check numerics — `shapes.py:65-162`
- §2.5 stage 9 — insert — ambiguity — instants accept `Z`/explicit offset (normalized to UTC), offset-less as UTC, date-only as midnight UTC; date fields must be exactly 10-char `YYYY-MM-DD`; required strings non-empty after trim — `store.py:85-111`, `shapes.py:78-82`
- §3.1 — insert — ambiguity — wrong-typed questionnaire keys fail the five-key completeness test like missing ones; `functional_answers` must be an object — `shapes.py:215-245`
- §3.2 — revise — ambiguity — `days_pending_statutory` floors at zero if the clock is set back before `completeness_established_at` — `serializers.py:86-88`
- §3.6 — insert — ambiguity — `threshold_value` may be integer or decimal, echoed as supplied — `shapes.py:154-162`
- §3.6 — revise — **mismatch** — `expires_at` is a calendar date published as `YYYY-MM-DD`, not a timestamp; all comparisons against it are date comparisons — `serializers.py:224`
- §4 — insert — ambiguity — a trailing slash on any path is equivalent — `app.py:28`

Pass A also verified clean with no edit needed: the §5 error table matches `errors.py` `ERROR_HTTP` exactly (62/62 ids, zero status mismatches); every serializer's field set matches the PRD-declared fields for all 14 entities except the `expires_at` type issue; the 15 ownership-guarded operations in §2.1 map 1:1 onto the 15 `ownership=` call sites, the 5 segregated-step operations onto the 5 `identity_required=True` sites, the 2 assigned-reviewer operations onto the 2 `assigned_reviewer=True` sites; envelope/pagination `meta` shape and `has_more` semantics match §2.2/§2.3.

### Pass B — intake / scheduling / determinations routes (23 edits: 19 ambiguity, 4 mismatch)
- §3.2 — revise — mismatch — `days_pending_statutory` does **not** freeze at its last value on return-incomplete; it reads 0 for as long as `completeness_established_at` is null — `serializers.py:85-86` + `routes/intake.py:185-187`
- §3.2 — insert — ambiguity — return-incomplete from any status other than `SUBMITTED` is `ERR_INVALID_APPLICATION_STATE` (409); `missing_items` entries are not element-type-checked — `routes/intake.py:177,179-180`
- §3.1 — insert — ambiguity — `claimed_conditions` must be an array but its entries are not type-checked — `routes/intake.py:92`
- §3.3 — insert — ambiguity — verification request against a packet neither `SUBMITTED` nor `PENDING_VERIFICATION` is `ERR_INVALID_APPLICATION_STATE` (409), screened before `ERR_VERIFICATION_PENDING` — `routes/intake.py:205-210`
- §3.3 — insert — ambiguity — both verification endpoints answer with the verification record in `data` (201 / 200), never the parent packet — `routes/intake.py:235,282`
- §3.3 — revise — mismatch — the re-request's only gate is "no verification still in `REQUESTED`"; presence of an `INSUFFICIENT` is not separately tested — `routes/intake.py:208-210`
- §3.4 — insert — ambiguity — booking against a packet not in `ASSESSMENT_REQUIRED` is `ERR_INVALID_APPLICATION_STATE` (409) — `routes/scheduling.py:117-118`
- §3.4 — insert — ambiguity — `rescheduled_from_assessment_id` validates neither the prior assessment's attendance nor its parentage; `slot_id` is resolved first, so both-missing answers `ERR_SLOT_NOT_FOUND` — `routes/scheduling.py:107-111,153`
- §3.4 — insert — ambiguity — `vehicle_number` is not required to be unique — `routes/scheduling.py:76`
- §3.4 — insert — ambiguity — the named assessment's attendance status is never consulted when reserving a ride — `routes/scheduling.py:180-181,217`
- §3.4 — insert — ambiguity — `cancelled_reason` is a required non-empty string, screened before cancellability — `routes/scheduling.py:247-250`
- §3.4 — insert — ambiguity — `ERR_EVALUATOR_SLOT_CONFLICT` is screened after `ERR_SLOT_IN_PAST` — `routes/scheduling.py:42-49`
- §3.5 — revise — mismatch — `Evaluator` and `AccessibilityOfficeAdmin` are each allowed all three attendance branches, not Admin-only-for-cancellation — `routes/scheduling.py:282`
- §3.5 — insert — ambiguity — a too-early `ATTENDED`/`NO_SHOW` is `ERR_INVALID_ASSESSMENT_STATE` (409), screened after the `SCHEDULED` check — `routes/scheduling.py:288-296`
- §3.5 — insert — ambiguity — bookings closed by an agency cancellation keep `cancelled_reason` null — `routes/scheduling.py:307`
- §3.5 — insert — ambiguity — scoring an already `SIGNED_OFF` assessment is `ERR_INVALID_ASSESSMENT_STATE` (409), attendance screened first — `routes/scheduling.py:352-355`
- §3.5 — insert — ambiguity — a re-score overwrites `evaluator_notes`, clearing it to null when omitted — `routes/scheduling.py:350,365`
- §3.6 — insert — ambiguity — `effective_date` is unconstrained relative to the logical clock — `routes/determinations.py:76`
- §3.6 — insert — ambiguity — comparator/type coupling is one-directional: a boolean condition type with `GTE|GT|LTE|LT` + threshold is accepted at drafting and the comparator is ignored at evaluation — `routes/determinations.py:46-53,260-265`
- §3.6 — insert — ambiguity — a draft leaves `term_days` null too — `routes/determinations.py:101`
- §3.6 — insert — ambiguity — the auto-created referral gets `referral_response_deadline_date` = issuing date + 14 days and is created without deduplication — `routes/determinations.py:187-204`
- §3.7 — revise — mismatch — the trip-eligibility check carries no ownership resolver, so an `Applicant` may check any determination — `routes/determinations.py:226-227` (vs §2.1's fifteen)
- §3.7 — insert — ambiguity — the `INELIGIBLE`/`UNCONDITIONAL`/`TERM_EXPIRED` short-circuits all report `applied_condition_ids` `[]` and `evaluated_condition_count` 0 — `routes/determinations.py:244-248`
- §3.7 — insert — ambiguity — an omitted trip fact leaves its condition unsatisfied (still examined and counted), never an error — `routes/determinations.py:213-214,261-265`

### Pass C — appeals / conduct / training / visitors / day-close / reads (26 edits: 20 ambiguity, 6 mismatch)
- §2.1 — revise — mismatch — the dangling `FunctionalAssessment` ownership linkage guards nothing; the four by-own-id fetches (assessment, appeal, proceeding, visitor record) carry no owner comparison — `routes/reads.py:100,203,236,278`
- §2.3 — insert — ambiguity — full per-listing query-filter sets, exact-string equality, unknown params ignored, `excused` truthiness parsing (`true`/`1`/`yes`) — `routes/reads.py:26-38,75-77,112-115,139-141,172-176,218-219,259-261`
- §2.7 — insert — ambiguity — every sweep step walks records in `created_at` asc, ties by creation sequence — `routes/ops.py:34,55,67,82,105,127,157`
- §2.7 step 2 — revise — mismatch — the lapse also increments `version`, not just status + `updated_at` — `routes/ops.py:63-64`
- §2.7 step 2 — insert — ambiguity — three sequential passes, so one proceeding can advance twice per sweep and each advance counts in `proceedings_advanced_count` — `routes/ops.py:49-97`
- §2.7 step 5 — insert — ambiguity — `continued_service_extended` is the idempotence guard; an already-extended appeal is skipped and not re-counted — `routes/ops.py:163-166`
- §2.7 para counters — revise — mismatch — day-close never inspects the request body, so a non-object body is ignored rather than 400 — `routes/ops.py:176-183`
- §2.10 — insert — ambiguity — slot/vehicle counters are recomputed by recount and touched only when the recount differs — `mirrors.py:48-51,71-77`
- §3.7 — insert — ambiguity — referral `determination_id` accepts any stored determination (not scoped to rider or the issued grant) and resolves before the enum check — `routes/training.py:34-37`
- §3.7 — insert — ambiguity — opening a referral touches nothing else (no rider/determination version bump) — `routes/training.py:42-58`
- §3.8 — insert — ambiguity — filing writes no rider field but touches the rider record — `routes/appeals.py:78-80`
- §3.8 — insert — ambiguity — "the assessment behind it" = the packet's single ATTENDED+SIGNED_OFF assessment; comparison skipped when absent — `routes/appeals.py:22-27,102-104`
- §3.8 — insert — mismatch — the strictly-later `hearing_at` test is stage 9 and precedes the `REVIEWER_ASSIGNED` check and both branch refusals — `routes/appeals.py:121-126`
- §3.8 — insert — ambiguity — `granted_category` `INELIGIBLE` is a stage-9 400, not the 422 coupling code — `routes/appeals.py:154-156`
- §3.8 — insert — ambiguity — the rider record is touched on every UPHELD decision regardless of category — `routes/appeals.py:183-186`
- §3.8 hop 2 — insert — ambiguity — successor's `issued_at`/`under_appeal`/`rationale` (= `decision_note`)/`fixed_route_competency_confirmed`; no visitor supersede, no other determination disturbed — `routes/appeals.py:195-217`
- §3.8 hop 4 — insert — ambiguity — remedy referral deadline = `decided_at` + 14 days, remaining fields null, category guard not re-applied — `routes/appeals.py:225` + `routes/determinations.py:188-203`
- §3.9 — insert — ambiguity — excusal has no state or event-type guard; any type, re-excusable as a self-loop — `routes/conduct_routes.py:102-116`
- §3.9 — insert — ambiguity — auto-proposal raised after the event is stored and not echoed (response is the trip event, 201) — `routes/conduct_routes.py:85-95`
- §3.9 — insert — ambiguity — manual proposal is not threshold-gated, not blocked by a live proceeding (only `PROPOSED` consolidated), `review_window_end_date` unvalidated — `routes/conduct_routes.py:129-149`
- §3.9 — revise — mismatch — the `suspension_start_date` coupling is stage-9 and runs ahead of all four listed guards, not last — `routes/conduct_routes.py:209-219`
- §3.9 — insert — ambiguity — the ACTIVE inclusive day count is floored at zero if the clock is set back before the start date — `conduct.py:138-141`
- §3.10 — insert — ambiguity — all three visitor-grant body fields required (`home_agency_certification_provided` a JSON boolean -> 400, not the gate) — `routes/visitors.py:27-29`
- §3.10 — insert — ambiguity — `home_agency_name` lands on the visitor record only; in the INELIGIBLE case the rider record is not touched — `routes/visitors.py:52-57`
- §3.10 — insert — ambiguity — `service_dates` published in recording order (not sorted); counters describe the recorded date's window — `routes/visitors.py:87-92` + `serializers.py:344`
- §3.10 — revise — mismatch — only the §3.6 issuance operation supersedes ACTIVE visitor records; the §3.8 appeal-remedy successor does not — `routes/appeals.py:190-226` vs `routes/determinations.py:183`

Pass C's two most consequential findings: the appeal-remedy successor is issued **without** the visitor-supersede cascade (PRD previously said "issuing any determination"), and the §3.9 decide guard order in the PRD contradicted the impl's stage-9-first coupling check.

**Orchestrator final verification:** `wc -l -c` -> PRD.md 476/101,695; PRD_FINALIZED.md 476/102,854; PRD_COMPLETED.md 477/121,106. `cmp PRD_FINALIZED.md PRD_COMPLETED.md` reports the files DIFFER, so the scan demonstrably ran (this is the specific failure mode the three-pass split was designed to prevent). Five `## ` sections still present, tail lands on the final error-table row, so nothing was truncated. `find implementation -name '*.py' -newermt '2026-09-04 03:33'` returns nothing — the implementation is byte-identical to what produced the 8/8 clean sweep, so no re-run was required.

## Pipeline complete — 2026-09-04T04:16:00.000Z

All nine steps finished. Final artifacts: SCAFFOLD.yaml + two design indices; workspace/PRD.md -> PRD_FINALIZED.md -> PRD_COMPLETED.md; 102 tests in test_suite/ over test_helpers/; workspace/implementation/ (23 files, 3,781 lines, 57 endpoints) passing 102/102 in all 8 rounds of the final stability sweep.
