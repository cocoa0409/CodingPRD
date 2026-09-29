# Worklog — task_2570_cancer_program_accreditation_tumor_registry_abstraction

## Step 1: Create task directory — 2026-09-03T12:47:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2570_cancer_program_accreditation_tumor_registry_abstraction` and its `workspace/` subdirectory. Index 2570 was pre-assigned by the invoking pipeline; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-03T15:04:00.000Z

All three scaffold artifacts for task 2570 are complete and pass the scaffold linter.

**Output directory:** `/home/ubuntu/github/CodingPRD/tasks/task_2570_cancer_program_accreditation_tumor_registry_abstraction/`

| File | Lines | Bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 3963 | 211,952 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1571 | 113,056 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4786 | 328,811 |

**SCAFFOLD.yaml counts** (top-level keys: `scenario`, `domain_name`, `api_prefix`, `response_envelope`, `complexity_profile`, `entities`, `state_machines`, `concurrency_rules`, `calculations`, `validations`, `endpoints`, `errors`, `roles` — no `scaffold_difficulty_design` / `scaffold_corner_design`):
- 13 entities, 10 state machines, 2 concurrency rules, 24 calculations (3 dual-variant), 79 validations, 65 endpoints, 77 errors, 7 roles
- profile: `compliance_audit` / `workflow_orchestration`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers]`, flat topology, cyclic state shape, `segregation_of_duties`, `immediate` consistency, `expert_plus`

**§1.8** (`scaffold_difficulty_design`, single top-level key): 9 rule blocks, 19 instances.

**§1.9** (`scaffold_corner_design`, single top-level key): all 9 guide sections in order, 110 instances — 78 active `test_recipe` instances plus 32 `excluded_because` delegation stubs:
entities 14, state_machines 14 (5 stubs), calculations 16 (6), validations 15 (6), endpoints 8 (3), errors 25 (6), rbac 7 (0), cross_cutting_complexity_layers 9 (6), consistency_model 2 (0).

**Lint:** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (65 endpoints, 13 entities, 19 §1.8 instances, 78 §1.9 instances, 901 calls scanned).

Two scaffold fixes were needed to reach clean lint, both surfaced by check (f): `FollowUpContact.case_id -> TumorCase` was unreachable because the linter derives an entity's collection segment only from a single-resource `GET /<segment>/{id}`, which FollowUpContact lacked (it had only the filtered list). Added `GET /cancer-registry/follow-up-contacts/{contactId}` plus the matching priority-10 existence rule and new error `ERR_CONTACT_NOT_FOUND`, wired into the §1.9 not-found sweep instance and the errors-section coverage map; the `difficulty_note` counts were updated to 65/79/77 to match. Note a linter quirk worth knowing for future tasks: the sub-resource form of check (f) matches the literal path segment `{id}`, so a sub-resource named `{caseId}` does not satisfy it — the filtered-list form is the reliable route.

## Step 3: Copy shared files — 2026-09-03T15:05:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-03T15:27:00.000Z

PRD generated and verified.

**Output:** `workspace/PRD.md` — **438 lines**, built by chunked `cat >>` appends (no single giant Write). Last section heading is exactly `## 5. Error Code Catalogue`; the file ends on the final catalogue row `| ERR_PAYMENT_EXCEEDS_BALANCE | 422 Unprocessable Entity |` with no audit footer and no contract-report block.

The two withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or grepped, and no sibling task directory was read. PRD.md contains no reference to scaffold-internal section numbering, `test_recipe`, or design-file content.

**Section list**
- §1 Introduction
- §2 Global Specifications & System-Wide Principles — 2.1 Registry Personas and RBAC; 2.2 API Response Structure (verbatim); 2.3 Pagination; 2.4 Resource Identity, Audit Stamps and Version Counters; 2.5 Path Resolution and Reverse-Reachability Reads; 2.6 The Logical Registry Clock; 2.7 Registry Posture: The Program-Wide Operating Gate; 2.8 Stale-Version Protection on Case and Batch Writes; 2.9 Segregation of Duties and Registrar Eligibility; 2.10 Numeric Precision, Rounding and Boundary Conventions; 2.11 Order of Validation; 2.12 Conserved Ledgers and Registry Invariants
- §3 Business Logic & Workflows — 3.1 Casefinding Lists, Reportability Rules and Case Identification; 3.2 Staffing the Registry and Distributing the Backlog; 3.3 Abstraction, Completeness Scoring and the QA Rework Loop; 3.4 Re-Abstraction Audits, Discrepancy Ledgers and Quality Scores; 3.5 Lifetime Follow-Up Maintenance; 3.6 State Central Registry Batches, Edit Resolution and Late-Reporting Assessments; 3.7 Multidisciplinary Cancer Conference Evidence; 3.8 Quality Measure Performance and Improvement Projects; 3.9 Deficiency Citation, Corrective-Action Response and the Accreditation Cycle
- §4 API Endpoints (65-row table, verified count)
- §5 Error Code Catalogue (77-row table, verified count)

**Coverage confirmation:** all 65 endpoints, all 79 validations (every one of the 77 distinct `error_id` values appears in §1–§3 prose, not only in the §5 table), all 77 errors, all 24 calculations (every constant value literally present in prose, including `SKIN_EXCLUDED_HISTOLOGIES` and `CNS_SITE_CODES` list members), and all 10 state machines / 64 transitions (each with an explicit FROM → TO arrow in prose).

Field coverage check: entities[].fields 165/165; request_body 102/102; query_params 38/38; path_params 13/13; union 205/205, 0 missing (two independent extraction passes). PASS
Rule coverage check: 79/79 validations; 2/2 OCC rejections; 64/64 transitions; 24/24 calculations; 77/77 distinct error_ids; 113/113 side-effect bullets; 13/13 entities structured content; 13/13 sibling-branch symmetry groups. PASS
Path purity check (§3 only): 1153 backtick tokens / 490 distinct; 0 path-like, 0 bare method, 0 method+path tokens. PASS

**Orchestrator truncation check (per invocation guard):** independently verified — `wc -l` = 438, headings end at `## 5. Error Code Catalogue`, `grep -c '^| \`ERR_'` = 77 rows, tail ends on a complete table row at a real section boundary. NOT truncated; no regeneration needed. `ERR_PAYMENT_EXCEEDS_BALANCE` is a legitimate domain error (late-reporting assessment payments, §3.6), not leakage.

## Step 6: Generate implementation — 2026-09-03T16:15:00.000Z

Implementation complete and verified.

## Modules (line counts)

**Foundation**: requirements.txt 1 | start.sh 10 | app.py 84 | errors.py 102 | response.py 57 | middleware.py 61 | validate.py 200 | spec.py 121 | db.py 207 | calcs.py 228 | services.py 423

**Routes** (`routes/`): __init__.py 0 | common.py 36 | programs.py 189 | abstractors.py 87 | casefinding.py 288 | cases.py 184 | abstractions.py 303 | audits.py 233 | conferences.py 167 | submissions.py 342 | deficiencies.py 130 | measures.py 169 | clock.py 56

**3678 lines total.** No file is truncated (every module ends on a complete statement; `python3 -m compileall` is clean and the app imports).

## Endpoints
**65 routes registered** — the 64 `/cancer-registry/...` operations of PRD §4 plus `POST /_clock/set_current_utc`. Route dump matched the PRD endpoint table one-for-one.

## Smoke test result — PASS
`bash start.sh` with `PORT=39147` booted in the foreground and bound `0.0.0.0:39147` (confirmed via `ss -ltnp`). Killed only that pid; no broad pattern kill was ever used.

Verified against a live server:
- Envelope shape: `meta{api_request_id, api_request_timestamp}` + `response_type` `object`/`array`/`error`; list `meta` adds `limit/offset/total_count/has_more`; errors carry `data{error_id, message}`.
- Full happy path: program -> abstractor -> casefinding source -> entry (`class_of_case_code=CLASS_10`, `analytic_flag=true`, suggestion derived) -> `REPORTABLE` decision minting a case with `accession_number 2026-00001`, `abstract_due_date 2027-01-01` -> assign -> abstraction (`completeness_score 100`) -> submit-qa -> qa-decision APPROVED (`approved_at` = logical clock `2026-08-01T00:00:00.000Z`) -> submission -> item -> transmit -> edit-results ACCEPTED.
- Cascades: CRITICAL citation drove `registry_posture -> FROZEN`, `open_critical_deficiency_count -> 1`, and swept the DRAFT batch to `HOLD` with `pre_hold_state=DRAFT`. Two rejected responses escalated the deficiency (`escalation_count 1` with due date +15 days, then `ESCALATED` at the cap) and propagated `ACCREDITED -> PROBATION` + `FROZEN`. Measure `UNDER_THRESHOLD -> PROJECT_REQUIRED -> PROJECT_ACTIVE -> PROJECT_CLOSED_MISSED` auto-cited the `STD 7.3` MAJOR deficiency with `source_measure_id`.
- Error bands: 401 no headers, 403 wrong role, 400 shape/bad filter/`limit=101`, 404 unknown id and unknown route, 405 wrong method, 409 conflicts (`ERR_CONFERENCE_SLOT_CONFLICT`, `ERR_SEGREGATION_OF_DUTIES_VIOLATION`, `ERR_SUBMISSION_EMPTY`, `ERR_CONFERENCE_QUORUM_NOT_MET`), 422 `ERR_SURVEY_DATE_TOO_SOON` / `ERR_CLOCK_NOT_MONOTONIC`.
- Fresh-process boot leaves the store empty (`total_count: 0` on every collection) and the clock at exactly `2026-08-01T00:00:00Z` — nothing is seeded.
- All 77 catalogued error IDs are wired to a raise site; no raise site references an uncatalogued ID.

Two notes for whoever reconciles with the test suite: rounding uses `Decimal`+`ROUND_HALF_UP` throughout with money as integer cents; `created_at`/`updated_at` are wall-clock stamps while `submitted_at`/`approved_at`/`scored_at`/`transmitted_at`/`completed_on`/`credited_on` come from the logical clock, per PRD §2.6. `evaluate` stores the strata array exactly as supplied (zero-eligible strata are dropped from the arithmetic only, per "dropped before any arithmetic happens"), with `included_strata_count` reporting the survivors.

**Orchestrator note on Step 5/6 concurrency:** the two generators were launched in back-to-back messages rather than a single message (orchestrator slip). Physical isolation was preserved in practice — `test_suite/` did not exist when the impl generator started, and the impl prompt carried an explicit standing prohibition on reading `test_helpers/`/`test_suite/` even if they appeared on disk mid-run. The impl generator's report shows no evidence of test-directory access.

## Step 5: Generate unit tests — 2026-09-03T16:56:00.000Z

Generation is complete. Both stages are written, self-consistent, and design-tagged.

## Files created

`test_helpers/` (3263 lines, 9 files): types.py 548 | api_errors.py 168 | api_client.py 359 | constants.py 99 | test_users.py 101 | factories.py 358 | assertions.py 591 | fixtures.py 894 | __init__.py 145

`test_suite/` (9029 lines, conftest + 15 test files):
conftest.py 62 (—) | test_01_dual_variant_calculations.py 426 (4) | test_02_combinatorial_formulas.py 446 (6) | test_03_state_machine_topology.py 334 (4) | test_04_transitive_cascades.py 397 (5) | test_05_validation_precedence.py 361 (4) | test_06_boundaries_and_overlap.py 511 (8) | test_07_cross_entity_and_ledgers.py 648 (8) | test_08_entities.py 604 (13) | test_09_state_machines.py 589 (9) | test_10_calculations.py 681 (9+1) | test_11_validations.py 527 (9) | test_12_endpoints.py 536 (5) | test_13_errors.py 1725 (19) | test_14_rbac.py 590 (7) | test_15_cross_cutting_and_consistency.py 592 (6)

**Total: 117 tests.** No file truncation (all files compile; `python3 -m pyflakes` clean; no `__pycache__` left behind).

## Per-queue instance coverage

- **Queue A (§1.8 difficulty): 19/19 instances -> 39 tests** (>=2 tests per instance), files 01–07.
- **Queue B (§1.9 corner): 77/78 non-stub instances -> 78 tests** (>=1 per instance), files 08–15: entities 13/14, state_machines 9/9, calculations 10/10, validations 9/9, endpoints 5/5, errors 19/19, rbac 7/7, cross_cutting_complexity_layers 3/3, consistency_model 2/2.
- Every test carries exactly one terminal `Design:` line; a tag-verification pass confirmed all 117 tags resolve to real instance `name:` values in the two design yamls, with no dual-tagged or orphan tags.
- Citation gate: `tests=117 problems=0` (every quoted span greppable verbatim in `workspace/PRD.md`); symbol gate: `symbol problems = 0`. No comment mentions the scaffold.

## Instances SKIPPED (gaps left as gaps)

1. `Corner/entities/submission_system_state_fields_generated_and_client_state_input_ignored` — the PRD says server-owned fields are server-generated and "Clients never supply either value", but never states that client-supplied values for them are *silently ignored* rather than rejected, so the design's asserted 201 is not uniquely derivable.

## Partial translations (non-derivable assertions omitted, instance still covered)

- `Corner/rbac/a_peer_registrar_cannot_abstract_or_submit_another_registrars_case` — the submit-qa leg asserting `ERR_NOT_ASSIGNED_ABSTRACTOR` was dropped: PRD §3.3 makes only `ERR_ABSTRACTION_NOT_DRAFT` derivable there. Create-leg 403, the owner's 201 and the workload counts are all kept.

## PRD-first corrections applied against the design indices

- `entities` instance 1: `next_survey_due_year` asserted as 2021 (PRD §3.1), not the design's value.
- `errors/measure_with_no_eligible_strata_and_project_on_a_draft_measure_are_rejected`: asserts `ERR_PROJECT_NOT_REQUIRED` (PRD §3.8), not `ERR_MEASURE_STATE_INVALID`.
- `consistency_model` instance 1: `registry_posture` asserted as `"OPEN"` — the design's `NORMAL` is not a PRD posture value; `completed_case_count` dropped (no such program field in the PRD); `abstract_due_date` asserted as `2027-01-01` with `days_to_due == 153`, because PRD §3.1 anchors the due date on `first_contact_date + timeliness_standard_days`, not the design's `diagnosis_date + 180`.
- `consistency_model` instance 2: the design's `pv_after == pv_before` across the follow-up-contact write was replaced by stability across two *consecutive* computed reads (before and after the write), since PRD §2.4 + §3.5 require the contact's recompute of the program's follow-up rates to increment the program `version`.

## Step 7: Run tests and iterate — 2026-09-03T17:12:00.000Z

All 8 parallel rounds pass 117/117 — same collected count as the baseline sweep (no tests dropped).

## Summary

**Iterations run:** 2 sweeps (8 parallel rounds each). Baseline: 111/117 in all 8 rounds, with an identical 6-test failure set every round (fully deterministic — no flakiness, no reaping tell in the logs). Final: 117/117 in all 8 rounds.

**Fixes applied to `test_suite/`** (no `test_helpers/` changes were needed; no implementation changes were needed):

1. `test_suite/test_10_calculations.py` — local `_entry()` factory helper. It passed `diagnosis_date`/`first_contact_date` as hardcoded keywords *and* splatted `**overrides`, so any caller overriding a date crashed with `TypeError: got multiple values for keyword argument 'diagnosis_date'`. Rewrote it to merge a base dict with `overrides` before calling `f.casefinding_entry_payload`. (Broke `test_the_follow_up_variant_only_swaps_the_reported_lost_rate` at setup.)

2. `test_suite/test_13_errors.py` — `test_response_and_review_bracket_the_same_window_from_both_sides` asserted `response_due_date == "2026-08-31"` for a **MINOR** deficiency cited `2026-08-01`. PRD §3.9 gives MINOR a 60-day window ("a `CRITICAL` ... within 30 days, a `MAJOR` within 45 days, and a `MINOR` within 60 days, and `response_due_date` is `cited_on` plus that many days"), i.e. `2026-09-30`, which is exactly what the implementation returned. The test had applied the CRITICAL window; corrected to `2026-09-30`.

3. `test_suite/test_13_errors.py` — `test_neither_workflow_may_be_entered_before_its_trigger_exists` asserted `cases_presented_count is None` on a never-held session. PRD §3.7: "A new session opens in `SCHEDULED` with an empty `attendances` array, `cases_presented_count` and `prospective_case_count` **at zero**". Corrected to `== 0`.

4. `test_suite/test_11_validations.py` — `test_resetting_the_clock_to_its_own_instant_is_an_error_and_not_a_no_op` asserted `validate_success(..., 200) is None`. `validate_success` returns the envelope's `data`, and PRD §2.2 states "For 2xx responses with no data, it contains an empty object" — so `data` can never be `null`; the assertion was unsatisfiable under the PRD envelope contract. Reduced to the load-bearing check: the forward clock move returns 200 with a well-formed envelope. (The three `ERR_CLOCK_NOT_MONOTONIC`/422 assertions bracketing it are untouched.)

**Assertions deleted for PRD silence** (STEP 1b unique-derivability failures; both are single ancillary assertions inside otherwise-covered tests, handled per STEP 1c partial-coverage splitting — no whole test was deleted):

5. `test_suite/test_06_boundaries_and_overlap.py` — `test_back_to_back_conference_session_is_refused_by_the_changeover_buffer` asserted the read-back echoed `start_at == "2026-08-05T13:00:00Z"` byte-for-byte, while the implementation re-serialises to the canonical `...T13:00:00.000Z`. **Category: format/serialization silence.** PRD §2.4 pins the three-fractional-digit rendering only for the audit stamps the server mints (`created_at`/`updated_at`); §2.11 requires only that a submitted timestamp *be* an ISO 8601 UTC instant. Two faithful readers diverge — one echoes the client string verbatim, one normalises client instants into the same canonical form used for its own stamps. The test's actual subject (the 409 `ERR_CONFERENCE_SLOT_CONFLICT` and the untouched `session_state == "SCHEDULED"`) is retained.

6. `test_suite/test_14_rbac.py` — `test_holding_a_role_grants_nothing_on_another_roles_operation` created a registrar after the forbidden `set_clock` and asserted `created_at == "2026-08-01T00:00:00.000Z"`, i.e. that `created_at` is stamped from the **logical** clock. **Category: computed-field/source silence.** PRD §2.6 scopes the logical clock to "timeliness, follow-up ageing, response windows, and audit windows"; §2.4 says only that `created_at` is "an ISO 8601 UTC instant with exactly three fractional digits" and never names the logical clock as its source. Two faithful readers diverge (logical-clock stamp vs. wall-clock stamp); the implementation chose wall clock. The no-side-effect intent of the assertion is already covered by the retained `ERR_FORBIDDEN`/403 assertion on the `set_clock` call itself, plus the retained program/measure/deficiency re-read assertions.

Nothing in `workspace/implementation/` was modified — all six failures traced to the test layer, and the implementation's behaviour on each was the PRD-faithful one.

**Orchestrator independent verification (per memory: Step 7 sweep artifacts must be re-checked):** parsed all 8 `results.*.json` myself — every file reports `passed 117 / total 117 / failed 0 / errors 0 / skipped 0`. Sweep ran under `setsid nohup` per the invocation's reaping guard; `sweep.log` shows a clean `Results: 117/117 passed` with 217.3s duration and no `Terminated` tell. Artifacts confirmed present on disk, not merely claimed.

**Step 8 skip-condition evaluation:** NOT skipped. Step 7 made 4 `test_suite/` fixes and 2 PRD-silence assertion deletions (0 `test_helpers/`, 0 `implementation/`). The skip condition requires all four counts at zero, so Step 8 runs with the above as `<step_7_diff>`.

## Step 8: Finalize PRD — 2026-09-03T17:20:00.000Z

`PRD_FINALIZED.md` is written. Three prose revisions, no new sections.

## Size

| | PRD.md | PRD_FINALIZED.md | delta |
|---|---|---|---|
| lines | 438 | 438 | 0 (+0.0%) |
| words | 14714 | 14837 | +123 (+0.84%) |
| bytes | 109356 | 110171 | +815 (+0.75%) |

3 of 438 lines revised (0.68% of lines touched). No insertions, no deletions.

## Changes

- **§2.4 — revise — audit-stamp source pinned to real wall-clock time** (covers step_7_diff item 6): added that `created_at`/`updated_at` are taken from the server's real wall-clock time, not the logical clock of §2.6, so a clock move does not change what a later creation or mutation stamps. `implementation/db.py:184` (`new_entity` -> `wall_now_iso()`), `implementation/db.py:178` (`commit()` -> `updated_at = wall_now_iso()`), `implementation/response.py:16`.
- **§2.4 — revise — client-supplied instants are re-rendered canonically** (covers item 5): added that a persisted client instant (`start_at`/`end_at`) is stored and echoed in the canonical three-fractional-digit form, with the explicit `2026-08-05T13:00:00Z` -> `2026-08-05T13:00:00.000Z` example, and that client-supplied plain calendar dates are echoed unchanged. `implementation/routes/conferences.py:54-55`, `implementation/db.py:66-70` (`fmt_instant`), `implementation/db.py:73-76` (`fmt_date`).
- **§2.6 — revise — clock-move response body** (covers item 4): a successful clock move returns HTTP 200 with an empty `data` object rather than any representation of the clock. `implementation/routes/clock.py:56` (`return ok_data({})`).

**Items that needed no PRD change** (PRD already uniquely determines; impl matched; the failure was in the test layer):
- Item 1 — `_entry()` duplicate-kwarg `TypeError`: pure fixture bug, no behavioral claim.
- Item 2 — MINOR response window: PRD §3.9 already states 60 days; `spec.py:114 RESPONSE_WINDOW_DAYS = {"CRITICAL": 30, "MAJOR": 45, "MINOR": 60}` matches verbatim.
- Item 3 — `cases_presented_count` on a never-held session: PRD §3.7 already says "at zero"; `routes/conferences.py:58-59` initialises both counts to `0`.

## Per-edit pre-edit search log

**Edit 1 — audit-stamp source**
- (a) Subject: what time source stamps `created_at` and `updated_at` on every entity kind.
- (b) Enumerated: `db.py:183-193 new_entity` (both stamps, all 13 `KINDS`, versioned and unversioned); `db.py:167-179 commit` (the single `updated_at` write path for every mutation in the app); `db.py:129-164 mark/force_touch/_tracked_view`; `response.py:16-18 wall_now_iso` and `response.py:24 api_request_timestamp`; `db.py:41-56` logical-clock accessors; grep of `wall_now_iso|clock_now()|fmt_instant` across all of `implementation/` to confirm no path stamps `created_at`/`updated_at` from `clock_now()` and no path stamps `submitted_at`/`approved_at`/`scored_at`/`transmitted_at` from wall time (`abstractions.py:186,229`, `audits.py:131`, `submissions.py:210,315` are all `fmt_instant(clock_now())`). Also checked `FollowUpContact` (`new_entity(..., versioned=False)` — still wall-clock `created_at`, consistent with §2.4's stated exception).
- (c) Adjustment: scoped the claim to "these audit stamps" rather than "server timestamps" so it makes no claim about `api_request_timestamp` and cannot be read as contradicting the logical-clock sourcing of `submitted_at`/`approved_at`/`scored_at`/`transmitted_at`/`completed_on`/`credited_on`/`last_reconciled_through`. Deliberately said nothing about list ordering, since `page()`/`all_of` sort by an internal insertion sequence (`db.py:207`) which is a tie-break refinement of §2.3's `created_at` ascending, not a redefinition of it.

**Edit 2 — client-supplied instant normalisation**
- (a) Subject: the stored/echoed rendering of any timestamp or date a client submits.
- (b) Enumerated: grepped every `f_instant` and `f_date` callsite. Client instants exist in exactly two places — `routes/conferences.py:35-36` (`start_at`/`end_at`, persisted via `fmt_instant`) and `routes/clock.py:20` (`current_utc`, consumed by `set_clock` and never persisted or echoed). Read `db.py:91-106 parse_instant` and `db.py:66-70 fmt_instant`. Read the round-trip consumers of the stored strings — `conferences.py:45-46` (slot-conflict comparison), `conferences.py:131` (`ERR_SESSION_NOT_YET_STARTED`), `services.py:185` (conference-compliance window) — all re-parse the canonical string, so normalisation is idempotent everywhere. Separately enumerated all 17 client-supplied date fields (`casefinding.py:69,73,74`, `cases.py:125`, `deficiencies.py:24`, `submissions.py:67-69`, `abstractors.py:25,78`, `programs.py:112,132`, `abstractions.py:38,44,51`, `audits.py:25-26`) and confirmed `f_date`->`fmt_date` echoes them byte-identically.
- (c) Adjustment: named the two fields explicitly instead of asserting a universal "every submitted timestamp is normalised", and appended the clause "client-supplied plain calendar dates are echoed unchanged" so the sentence cannot be over-read into the date paths.

**Edit 3 — clock-move response body**
- (a) Subject: the `data` payload of a successful `POST /_clock/set_current_utc`.
- (b) Enumerated: `routes/clock.py:56` (`ok_data({})`); `routes/common.py:18-25` (`ok` vs `ok_data`); `response.py:28-34 object_response` (`data if data is not None else {}` — `data` is never `null` on any 2xx, which is what made the original assertion unsatisfiable); grepped `ok_data` across the app — the only other importer is `routes/programs.py:16`, and its `compliance-summary` handler at `programs.py:105` returns a full non-empty program payload via `object_response`, so the empty-object claim must not be generalised past the clock endpoint.
- (c) Adjustment: confined the sentence to "a successful move" inside §2.6 rather than adding a general statement about empty-data endpoints, which would have mis-described `compliance-summary`; phrased the exclusion as "rather than any representation of the clock" instead of "the clock is never returned in a response body", since clock-derived fields do appear in resource bodies throughout.

## Step 9: Complete PRD — 2026-09-03T18:20:00.000Z

**Orchestrator design decision (recorded per AUTONOMY instruction):** Step 9 was run as **three sequential file-partitioned passes** over a single shared `PRD_COMPLETED.md`, rather than one monolithic scan. Rationale: a single subagent cannot hold a 3678-line implementation plus a 438-line dense PRD and still scan exhaustively; the known failure mode is a subagent that reports a completed scan while leaving `PRD_COMPLETED.md` byte-identical to its source. The orchestrator seeded `PRD_COMPLETED.md` itself (`cp PRD_FINALIZED.md PRD_COMPLETED.md`, md5 verified identical at seed) and each pass edited it in place with a disjoint, explicitly-assigned slice of `implementation/`. Passes ran strictly sequentially because they share one output file.

Partition:
- **Pass 1** — foundation layer: app.py, errors.py, response.py, middleware.py, validate.py, spec.py, db.py, calcs.py, services.py
- **Pass 2** — routes/: common.py, programs.py, abstractors.py, casefinding.py, cases.py, abstractions.py, clock.py
- **Pass 3** — routes/: audits.py, conferences.py, submissions.py, deficiencies.py, measures.py

### Pass 1 (foundation) — 14 ambiguity-pins, 3 mismatch-revisions (17 changes); 110,171 -> 113,696 chars

- §2.1 — insert — ambiguity — empty/whitespace-only `X-User-ID` counts as absent for the 401 — middleware.py:37
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars from A–Z/0–9 — response.py:9,12
- §2.3 — insert — ambiguity — `limit`/`offset` as empty string fall back to default rather than erroring — validate.py:150-151
- §2.3 — insert — ambiguity — `created_at` ordering ties broken by ascending creation sequence — db.py:207
- §2.3 — revise — ambiguity — `has_more` pinned to `offset + len(data) < total_count` — response.py:42
- §2.4 — revise — **mismatch** — PRD claimed every derived-field recomputation increments `version`; impl bumps `version`/`updated_at` at most once per request and only when a field other than `updated_at`/`version` actually changed, with force-touched operations as the stated exception; a resource created by the same request stays at `version` 1 — db.py:129-181,156, routes/abstractions.py:297 (verified empirically)
- §2.4 — insert — ambiguity — `updated_at` equals `created_at` at creation; mutating response rendered after the bump — db.py:183-193, routes/common.py:21-23
- §2.5 — insert — ambiguity — list filter as empty string treated as absent, not unrecognised — validate.py:177-183
- §2.11 — insert — ambiguity — routing precedes the validation ladder: unknown path -> 404 `ERR_NOT_FOUND`, wrong method -> 405 `ERR_METHOD_NOT_ALLOWED`, neither in the §5 catalogue — app.py:51-58
- §2.11 — insert — ambiguity — JSON `null` counts as absent for required check and defaulting — validate.py:25-30
- §2.11 — insert — ambiguity — string fields need a non-whitespace char; the three AJCC categories and `diagnostic_confirmation_code` are the only ones accepting `""`; check does not reach array members — validate.py:33-41,129-138
- §2.11 — revise — ambiguity — dates exactly `YYYY-MM-DD`; instants accept `Z`, an offset normalised to UTC, or no zone (read as UTC) — db.py:79-106
- §3.1 — revise — **mismatch** — timeliness recompute trigger list was under-inclusive; impl also refreshes on every `case_state`/assignment change (10+ callsites) — services.py:55-61
- §3.4 — insert — ambiguity — `audit_fail_streak` on void recomputed as trailing run of consecutive non-PASS verdicts over remaining closed audits in ascending `scored_at` — services.py:346-355
- §3.5 — insert — ambiguity — the 1826-day CoC cohort boundary is inclusive — services.py:120
- §3.9 — insert — ambiguity — responding `X-User-ID` retained as server-side state, not a deficiency field — services.py:419
- §4 table — revise — **mismatch** — casefinding-source row's "HIM discharge list" replaced with the actual `source_type` enum — spec.py:7-8

No-change coverage confirmed: all 77 `error_id -> HTTP status` pairs diffed programmatically against §5 (exact match); every `spec.py` constant matches PRD prose (full list enumerated); all of `calcs.py` (24 formulas, precision conventions, reportability rules, completeness algebra, weighted-error verdict, assessment order, measure rates, performance bands); all of `services.py` cascades; envelope/pagination/role shapes; db.py identity and clock defaults. Deliberately left under-determined: `strict_slashes=False`, defensive `ERR_INTERNAL`/`ERR_HTTP_*` handlers, `f_int` boolean rejection, duplicate array members.

### Pass 2 (routes A) — 10 ambiguity-pins, 13 mismatch-revisions (23 changes); 113,696 -> 119,811 chars

- §3.1 — insert — ambiguity — `reference_year` a required unbounded integer; both conference/coordinator compliance flags open false — programs.py:27-60
- §3.1 — insert — ambiguity — the two entry-date rules are `ERR_INVALID_REQUEST` shape failures evaluated before `{sourceId}` resolves; `accession_date` unconstrained — casefinding.py:81-86
- §3.1 — revise — **mismatch** — reportability precedence fixed: entry state -> withdrawn program -> reference-year window -> missing `override_reason_code` — casefinding.py:216-226
- §3.1 — revise — ambiguity — `accession_number` sequence counts cases of that diagnosis year **including voided** (a void permanently consumes its number), in contrast to `sequence_number` which counts only non-voided — casefinding.py:167-173
- §3.2 — insert — ambiguity — `certification_expires_on` may already be past at creation; lapse enforced only at assignment/abstraction — abstractors.py:25-44
- §3.2 — revise — **mismatch** — `unassign_reason` shape-validated but not persisted — cases.py:99
- §3.2 — revise — **mismatch** — staffing `effective_on`/`reason` not persisted; no state precondition, so any status may be set from any other incl. `TERMINATED -> ACTIVE` — abstractors.py:74-87
- §4 table — revise — **mismatch** — employment-status row: "voids" in-flight abstractions -> "moves their in-flight abstractions to REJECTED" — services.py:370-373
- §3.3 — revise — **mismatch** — abstraction-creation gate order pinned (case state -> FROZEN -> ACTIVE/cert/program -> ownership last); `submitted_at`/`approved_at`/`qa_reviewer_user_id` null at creation — abstractions.py:80-120
- §3.3 — revise — **mismatch** — `stage_source` is the one mandatory clinical field at creation (`ERR_INVALID_REQUEST`, not a completeness deduction) — abstractions.py:27-29,72
- §3.3 — revise — ambiguity — submit-qa `DRAFT` state check precedes the ownership check — abstractions.py:176-179
- §3.3 — insert — ambiguity — QA reviewer ACTIVE/program-match gates apply only when `X-User-ID` resolves to a registrar; order active -> SoD -> program match — abstractions.py:211-219
- §3.3 — insert — ambiguity — APPROVED cascade also re-derives case follow-up standing and program follow-up rates — abstractions.py:235,242
- §3.3 — revise — ambiguity — reopen-draft: every clinical field optional incl. `stage_source`; omitted retains, explicit `null` clears (empty array for `treatment_modalities`) and can restore `missing_required_fields` — abstractions.py:288-292
- §3.3 — revise — **mismatch** — reopen-draft sets case `IN_ABSTRACTION` from either allowed state and bumps `version` unconditionally via `db.force_touch` — abstractions.py:297-298
- §3.5 — revise — ambiguity — case follow-up standing also derived at identification and at completing QA approval (worded non-exclusively) — casefinding.py:200, abstractions.py:235
- §3.5 — revise — **mismatch** — compliance summary returns the program's **full** representation; recomputation persisted (version moves only on real change) and carries the submission hold/restore cascade; advances no state machine; `follow_up_variant` validated before `{programId}` resolves; `state_central_all_years` affects the response body only — programs.py:92-105
- §4 table — revise — **mismatch** — compliance-summary row corrected likewise — programs.py:92-105
- §3.2 — revise — **mismatch** — `REWORK_PENDING` neither assignable nor releasable (release demands `ASSIGNED`) — cases.py:67,102-104
- §3.9 — revise — **mismatch** — survey scheduling accepted from `ACCREDITED` **or** `PROBATION`; state checked before the date rule; `survey_year` from year of `survey_date`; posture thaw noted — programs.py:108-133
- §3.9 — revise — **mismatch** — survey completion: `completed_on` mandatory by shape but neither persisted nor bounded, `survey_date` untouched; `survey_year` from the clock; posture recomputed on both branches; surveyor of record held internally — programs.py:136-160
- §3.9 — revise — ambiguity — accreditation decision order state -> SoD -> compliance gates; no surveyor of record when probation arrived by escalation; CoC follow-up rate recomputed at decision; `next_survey_due_year` untouched when `survey_year` null; `PROBATION -> PROBATION` allowed — programs.py:163-189
- §2.6 — revise — **mismatch** — clock checkpoint runs the deficiency sweep after the case/source passes but **before** the program/registrar passes (PRD said "Finally") — clock.py:26-55

Verified empirically on a private port (torn down by pid): program-creation defaults; compliance-summary leaving `version` at 1 twice; filter-before-404 orderings; accession numbering across a void (`2026-00001` voided -> next `2026-00002`, `sequence_number` stayed 1); reopen-draft null-clear vs omit-retain with score 100 -> 76 and the unconditional case-version bump.

No-change coverage: common.py plumbing; all list/read endpoints' filters, ordering and pagination; every role gate vs the §4 table; source-creation defaults and completeness formula; entry duplicate key, class-of-case and reportability suggestion engines; entry reopen's three refusals, cap and compensating void cascade; assign/unassign gate order and ledger effects; follow-up contacts (COMPLETED-only gate, both date bounds, monotonic `last_contact_date`, unversioned event shape); supersede rules, `rework_round` cap, completeness scoring, the 85 quality gate, all three QA verdict cascades; clock monotonicity error, per-entity refresh set, `last_reconciled_through` exclusivity, sweep tie-break, empty-`data` 200.

### Pass 3 (routes B) — 22 ambiguity-pins, 8 mismatch-revisions (30 changes); 119,811 -> 126,583 chars

- §2.7 — revise — **mismatch** — submission-item add carries no posture check at all, so a frozen program's swept batch fails `ERR_SUBMISSION_NOT_DRAFT`, never `ERR_REGISTRY_FROZEN` — submissions.py:134-146
- §3.2 — revise — **mismatch** — "whenever an audit is voided" -> "whenever an audit **that had already been scored** is voided" — audits.py:199-206
- §3.5 — insert — **mismatch** — added the §3.4 audit rework cascade and its void unwind to the follow-up-standing trigger list — audits.py:159-160,221-222
- §3.4 — revise+insert — **mismatch** — corrected FK order (abstraction before auditor); auditor gates reordered ACTIVE -> SoD -> program mismatch with window capacity interposed, program membership last and compared against the **case's** program; `audited_field_count` 0 and `scored_at` null at creation — audits.py:30-74
- §3.4 — insert — ambiguity — `ERR_NOT_ASSIGNED_ABSTRACTOR` (403) for a scorer who is not the assigned auditor, after both audit-state checks — audits.py:114-119
- §3.4 — revise — ambiguity — CRITICAL_FAIL cascade also re-derives case timeliness/follow-up fields and program follow-up rates — audits.py:153-168
- §3.4 — insert — ambiguity — suspension runs **after** the rework cascade, releasing the freshly reworked case, carrying its abstraction `REWORK_REQUIRED -> REJECTED`, zeroing `assigned_open_case_count` — audits.py:170-173
- §3.4 — insert — ambiguity — `void_reason` shape-validated, never persisted — audits.py:182
- §3.4 — revise — ambiguity — unwind re-derives case timeliness/follow-up against restored `completed_on` and recomputes program rates/backlog/posture — audits.py:216-231
- §3.4 — revise — **mismatch** — quality **and productivity** scores recomputed only on voiding an already-scored audit — audits.py:199-206
- §3.6 — insert — ambiguity — no ordering constraint ties `deadline_date` to the reporting period — submissions.py:69
- §3.6 — insert — **mismatch** — item add has no posture gate — submissions.py:139
- §3.6 — revise — ambiguity — item created with `resolution_note` null and returned as the operation's own 201, not the batch's — submissions.py:148-158
- §3.6 — insert — ambiguity — `transmit_note` shape-validated, not persisted — submissions.py:190
- §3.6 — revise — **mismatch** — on edit-results the array shape checks run ahead of the batch-state check (contra §2.11 band order); `edit_codes` may be omitted and reads empty; a repeated `case_id` is not an error and the last entry wins — submissions.py:223-250
- §3.6 — insert — ambiguity — edit-results answers with the batch representation — submissions.py:270
- §3.6 — revise — ambiguity — resolve has no batch-state gate; batch `version` moves with `failed_item_count`; answers with the **item's** representation — submissions.py:279-290
- §3.6 — insert — ambiguity — `retransmit_note` not persisted; retransmit leaves `resolution_note`/`edit_codes` standing so `edit_error_codes` still reports the previous round — submissions.py:297,316-325
- §3.6 — insert — ambiguity — a batch with no assessment returns `ERR_PAYMENT_EXCEEDS_BALANCE` for any payment; payments have no state precondition — submissions.py:335-341
- §3.7 — insert — ambiguity — `required_disciplines` required but may be empty, making the discipline leg of quorum vacuous — conferences.py:37-38
- §3.7 — revise — ambiguity — `is_required_coordinator` defaults false when omitted — conferences.py:95-96
- §3.7 — insert — ambiguity — recording attendance answers 200 with the updated **session** — conferences.py:113
- §3.7 — insert — ambiguity — `credit_note` shape-validated, not persisted — conferences.py:148
- §3.8 — revise — ambiguity — `project_title`/`target_rate_pct`/`final_rate_pct` null at creation; no uniqueness on `measure_code` or (code, year); `measurement_year` only integer-validated — measures.py:32-46
- §3.8 — insert — ambiguity — empty `strata` array is not a shape failure and reaches `ERR_MEASURE_STRATA_EMPTY` while absent/null is `ERR_INVALID_REQUEST`; measure-state check precedes the strata test; nothing requires `compliant_case_count <= eligible_case_count` — measures.py:85-110
- §3.8 — revise — ambiguity — project fields conditionally required per `action`, the other action's field range-validated then discarded; `target_rate_pct` `ERR_INVALID_REQUEST` evaluated only after the state check — measures.py:129-145
- §3.8 — insert — ambiguity — closing a project never restates `performance_rate_pct`/`pooled_rate_pct`; auto-cite carries `evidence_reference` null and the 45-day MAJOR `response_due_date` — measures.py:155-166
- §3.9 — insert — ambiguity — a future `cited_on` is `ERR_INVALID_REQUEST` raised before `program_id` resolves — deficiencies.py:29-32
- §3.9 — revise — **mismatch** — a second response always overwrites `response_narrative` but overwrites `evidence_reference` only when supplied; prior `reviewer_notes` left standing — deficiencies.py:86-90
- §3.9 — revise — ambiguity — `reviewer_notes` stored under either outcome and only when supplied — deficiencies.py:110-112

No-change coverage: audit window-capacity interval arithmetic and its 409, the `overlapping >= 2` semantics, verdict thresholds and PASS-at-2 boundary, list filters, absence of posture gates on audit create/score, per-resource 404s; submissions' `expected_submission_version` ordering per §2.8, transmit's five-gate order, the assessment's five-step evaluation and relief tiers, retransmit's five gates and round cap, period-overlap inclusivity, HOLD-at-creation-when-frozen, case `submission_state` transitions; conferences' half-open interval + 30-minute buffer, three quorum conditions, 30-minute qualifying threshold, `ERR_SESSION_NOT_YET_STARTED` inclusivity, the 12-month window/volume/coordinator rules; measures' three-band verdict with inclusive comparisons, mean-of-rounded vs pooled contrast, zero-eligible exclusion, evaluable-state set, `ERR_PROJECT_NOT_REQUIRED` vs `ERR_MEASURE_STATE_INVALID` split; deficiencies' 30/45/60 mapping, CRITICAL-only posture effect, respondable-state pair, closed-window 409, review SoD, escalation cap/15-day extension/four-link probation cascade. Deliberately not pinned to avoid a false claim: that `file_response` or a REJECTED review recomputes program aggregates (all three open states carry the same `open_critical_deficiency_count`, so the recompute is a no-op and does not bump `version`).

### Step 9 totals

- Source `PRD_FINALIZED.md` 438 lines / 110,171 chars -> `PRD_COMPLETED.md` 438 lines / 126,583 chars (**+16,412 chars, +14.9%**; 0 new lines — every change an in-paragraph insert or revision, no new sections).
- **46 ambiguity-pins, 24 mismatch-revisions — 70 discrete changes** across the three passes.

**Orchestrator independent verification of the final deliverable:** `PRD_COMPLETED.md` md5 `50c2191936a272fc9648b8d2b98f7f53` differs from `PRD_FINALIZED.md` `398f6b524e29bbae8e2c0656302fa85d` (the byte-identical no-op failure mode did NOT occur); `diff` against PRD_FINALIZED shows 108 changed lines; all five `##` sections present and in order (§1 line 3, §2 line 13, §3 line 152, §4 line 286, §5 line 358); §4 table has exactly 65 method rows; §5 catalogue has exactly 77 `ERR_` rows; the file ends on a complete final table row at a real section boundary. No implementation or test file was modified by Step 9, so the Step 7 green sweep (8/8 rounds, 117/117 each) remains valid.

**Pipeline complete.** All nine steps finished; `workspace/PRD_COMPLETED.md` written.
