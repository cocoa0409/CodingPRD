# Worklog — task_2293_job_classification_exemption_audit

## Step 1: Create task directory — 2026-09-01T14:46:00.000Z

Created `tasks/task_2293_job_classification_exemption_audit/` and `tasks/task_2293_job_classification_exemption_audit/workspace/` (pre-allocated task name used verbatim; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T16:05:40.000Z

All three artifacts are complete and the linter passes clean on the first run.

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2293_job_classification_exemption_audit/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2293_job_classification_exemption_audit/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2293_job_classification_exemption_audit/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    43
  §1.1 entities declared:     12
  §1.8 instances scanned:     23
  §1.9 instances scanned:     45
  Calls scanned (§1.8+§1.9):  724

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2293_job_classification_exemption_audit/`):

- **SCAFFOLD.yaml** (§1.0–§1.7, no design keys): 12 entities, 8 state machines (AuditProject, JobFamily-derived Position dimension, Interview, ExemptionAnalysis, ReclassificationCase with two parallel dimensions, VoluntaryCorrection, ContractorReview), 2 §1.2.1 OCC rules, 9 calculations, 19 ordered validations, 43 endpoints, 36 errors, 7 roles (`role_model: segregation_of_duties`, `api_prefix: ""`, `consistency_model: immediate`). Scenario text is verbatim.
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml**: 9 rules / 23 instances (all nine §0.5 rules, each with ≥2 differentiated instances; 3 each for combinatorial_formula, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap).
- **SCAFFOLD_CORNER_DESIGN.yaml**: 9 sections / 64 instances — entities 14, state_machines 15, calculations 9, validations 8, endpoints 4, errors 4, rbac 4, complexity_layers 5, consistency_model 1. 45 carry full structured `test_recipe`s; 19 are `excluded_because:` stubs pointing at named §1.8 instances (all references resolve; no stub carries a `test_recipe`). All 87 instance names are unique across both design files.

Two notes worth relaying:
- I filled a gap found while authoring: `LEGAL_COUNSEL_AUTHORITY_CAP_CENTS` (25000000) and `VOLUNTARY_CORRECTION_MANDATORY_CENTS` (5000000) were referenced by validations 12/18/19 and the VoluntaryCorrection state machine but had no numeric declaration; they are now declared in `calculations.project_exposure_rollup.constants`.
- All money/score literals in both design files are hand-computed against the §1.3 formulas (e.g. FULL_RATE 22274928 vs HALF_TIME 6060912 on the same case; cost-neutral rate 2094 with delta −1156; headcount-weighted family risk 54/MEDIUM where a plain mean would give 74/HIGH; HCE shortcut EXEMPT at floor 84400/FEDERAL).
- No sibling task directory was read; generation used only the scenario text and the scaffold-generator skill spec plus its claim-extraction guide.

## Step 3: Copy shared files — 2026-09-01T16:05:59.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2293_job_classification_exemption_audit/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-01T16:20:17.000Z

PRD generated and all three Hard Contracts pass.

## Deliverable

`/home/ubuntu/github/CodingPRD/tasks/task_2293_job_classification_exemption_audit/workspace/PRD.md` — **483 lines**

## Sections written

- **§1 Introduction** — 3 paragraphs framing the FLSA classification-audit engagement and the two cross-cutting design commitments (every finding reversible; no author blesses their own finding).
- **§2 Global Specifications** — 12 subsections, domain-derived: 2.1 RBAC (7 roles, opaque-identity semantics), 2.2 API Response Structure (pasted verbatim, byte-identical), 2.3 Pagination, 2.4 Identity/Timestamps/Versioning (incl. the two entities lacking `updated_at`/`version`), 2.5 Logical Clock, 2.6 Jurisdiction Resolution & Federal Baseline, 2.7 Rejection Precedence (all 19 priorities as an explicit ordered list), 2.8 Cascade Integrity, 2.9 Stale-Read Protection (OCC), 2.10 Segregation of Duties, 2.11 Numbers/Rounding/Pinned Evaluation Order, 2.12 Posture Write Gate.
- **§3 Business Logic & Workflows** — 9 subsections grouped by audit lifecycle (engagement setup → duty documentation → interview corroboration → exemption analysis → review/determination/rescission → risk scoring → pay conversion & communication → back-wage exposure & voluntary correction → contractor review, job-change triggers & closure).
- **§4 Endpoint Definitions** — 43 rows, exactly 4 columns.
- **§5 Error Code Catalogue** — 36 rows, exactly 2 columns. Document ends at §5; no audit footer.

## Coverage audit (machine-verified against SCAFFOLD.yaml)

- **Contract 1 — Field-Name Coverage: PASS.** All 139 distinct identifiers (every `entities[].fields[].name`, the six nested `economic_reality_factors` sub-keys, and every endpoint `input`/`query_params`/`path_params` identifier) appear verbatim in backticks. 0 missing.
- **Contract 2 — Rule Coverage: PASS.** All 8 state machines' from/to values present; all 9 calculations carry formula, constant values and rounding convention; all 19 validation priorities stated in order with matchable `error_id`s; all 36 error IDs appear in §1–§3 prose (not just the table); all 25 endpoints declaring `side_effects` have those effects narrated; both `concurrency_rules[]` framed purely as stale-version rejection with write endpoint, OCC field, error ID and 412; all entity enum values present; sibling-branch symmetry preserved (5 exemption tests, 2 back-wage methods, 2 conversion methods, 3 IC tests, 3 contractor terminals, 3 interview-void source states).
- **Contract 3 — §3 Path Purity: PASS.** 0 backticked tokens in §3 start with `/`, are a bare HTTP method, or combine method+path.
- Also verified: §2.2 is a byte-exact match of `section-2.2-response-structure.md`; zero pseudocode operators (`==`, `>=`, `+=`, `min()`, `max()`, `round()`, `floor()`, boolean `AND`/`IN`); zero fuzzy quantifiers.

## Two scaffold gaps you should know about

`RECLASS_WINDOW_BUFFER_DAYS` (validation priority 15 / `ERR_RECLASS_WINDOW_CONFLICT`) and `MAX_CONCURRENT_RECLASS_PER_FAMILY` (priority 16 / `ERR_RECLASS_WAVE_CAPACITY_EXCEEDED`) are referenced by SCAFFOLD.yaml but have **no numeric declaration anywhere in it** — confirmed by grep across all 1917 lines. The `worklog.md` records the author retro-declaring `LEGAL_COUNSEL_AUTHORITY_CAP_CENTS` and `VOLUNTARY_CORRECTION_MANDATORY_CENTS` but says nothing about these two. Since PRD.md is the implementer's only artifact, an unvalued constant makes the rule unimplementable, so I stated concrete values — **7 calendar days** for the window buffer and a cap of **3** intersecting cases per job family — naming both constant identifiers in the prose for traceability. **These values are my choice, not the scaffold's**, so if the withheld design files assert different numbers the scaffold needs reconciling before tests are generated.

Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced, and no sibling task directory under `tasks/` was read.

## Step 5: Generate unit tests — 2026-09-01T17:51:11.000Z

Generation is complete.

## Files written

`test_helpers/` (Stage 1, 9 modules): `constants.py`, `test_users.py`, `api_errors.py`, `types.py`, `api_client.py`, `factories.py`, `assertions.py`, `fixtures.py`, `__init__.py`.

`test_suite/` (Stage 2): `conftest.py` plus 13 test modules —
`test_01_engagement_registry_and_defaults.py` (7), `test_02_position_inventory_and_uniqueness.py` (9), `test_03_engagement_stage_gates.py` (8), `test_04_interview_calendar_and_lifecycle.py` (7), `test_05_duties_corroboration.py` (5), `test_06_exemption_evaluation.py` (5), `test_07_analysis_review_cycle.py` (9), `test_08_determination_cascade.py` (6), `test_09_family_risk_scoring.py` (5), `test_10_back_wage_exposure.py` (7), `test_11_pay_conversion_and_communication.py` (9), `test_12_voluntary_correction_authority.py` (5), `test_13_contractor_and_access_control.py` (5).

**87 tests**, collected cleanly by pytest (`87 tests collected`, no import or fixture errors).

## Instances translated vs skipped

- **Queue A (difficulty)**: 23 instances across 9 rules; **21 translated**, each with >=2 tests. **2 skipped**, both under `resource_temporal_overlap`, both because the PRD contradicts the asserted outcome:
  - `reclassification_window_uses_closed_intervals_with_a_fourteen_day_separation` — the design demands a 14-day separation; the PRD pins separation to "strictly more than the reclassification-window buffer, which is 7 calendar days".
  - `reclassification_wave_capacity_rejects_the_third_intersecting_case_in_a_family` — the PRD permits "at most 3 cases ... may have intersecting windows inside one job family" and rejects only "A fourth intersecting unreverted case".
- **Queue B (corner)**: 64 instances, of which 19 carry `excluded_because:` stubs. All **45 non-stub instances translated** (>=1 test each); **0 stubs translated**.

Two sub-assertions were dropped (instance still translated) because the PRD does not uniquely derive them: `Position.overtime_eligible == true` in `Corner/consistency_model/determination_side_effects...` (contradicts the PRD's derivation from `current_fls_status`), and `notice_channel == CERTIFIED_MAIL` after a re-send in the communication instance (the PRD only pins the *first* send's channel). In `Corner/errors/audit_project_create_without_a_user_header_is_rejected` the "no AuditProject row was created" check is asserted through the error envelope only, since the PRD exposes no project listing endpoint.

## Coverage audit

- Design-tag audit: 87/87 tests carry exactly one trailing `Design:` line as the last docstring line; every tag resolves to an existing non-stub instance; no untagged or dual-tagged tests.
- PRD-citation audit: all **89** `PRD: "..."` citations match `workspace/PRD.md` verbatim as exact substrings (whitespace-normalized, with the suite's arrow/dash convention). One defect found and fixed during the pass: `test_04` had written a split backtick span where the PRD has a single backtick span, now `` `COMPLETED -> ATTESTED` ``.
- Scaffold-leak audit: no occurrence of "scaffold", a section reference, or queue wording anywhere in `test_suite/` or `test_helpers/`.

## Step 6: Generate implementation — 2026-09-01T17:51:11.000Z

ORCHESTRATOR NOTE: Steps 5 and 6 ran sequentially rather than concurrently (orchestrator error). To preserve the physical-isolation intent, the Step 6 subagent was given a hard constraint forbidding it from reading `test_helpers/`, `test_suite/`, or the `SCAFFOLD_*DESIGN.yaml` files; it implemented from PRD.md + SCAFFOLD.yaml + INSTRUCTION.md only.

Implementation is complete, verified end-to-end, and the smoke-test server has been shut down.

## Files written

All under `workspace/implementation/`:

- `start.sh` (guarded `pip install`, then `exec python3 app.py`), `requirements.txt`, `app.py` (`create_app()`, 13 blueprints, error handlers for `ApiError`/404/405/`HTTPException`/`Exception`, `PORT` default 10000, `threaded=True`, no reloader)
- Core: `constants.py` (all federal anchors + enums + role lists), `errors.py` (36 error ids -> message + HTTP status), `db.py` (12 in-memory dicts, logical clock, `make_row`/`touch`/`ordered`), `response.py` (envelope + pagination meta), `middleware.py` (`endpoint(roles)`, `body()`, `pagination()`), `validation.py`
- `services/`: `numbers.py` (Decimal + ROUND_HALF_UP helpers), `derive.py` (all derived-on-read fields), `exemption.py` (the 9 evaluated analysis fields), `calculations.py` (back-wage exposure, pay conversion, IC test, re-analysis requirement), `serialize.py`, `lookup.py`
- `routes/`: `clock.py`, `state_rules.py`, `audit_projects.py`, `job_families.py`, `positions.py`, `duty_statements.py`, `interviews.py`, `exemption_analyses.py`, `reclassification_cases.py`, `back_wage_estimates.py`, `voluntary_corrections.py`, `contractor_reviews.py`, `job_change_triggers.py`

## Endpoint count

43 routes registered, matching the SCAFFOLD endpoint list, including the harness clock endpoint `POST /_clock/set_current_utc`.

## Verification

Two full smoke runs against `bash start.sh` exercised: state-rule registry and federal-only fallback; project stage machine (all 4 declared edges, precondition failures, `ERR_PROJECT_NOT_READY_TO_CLOSE`, rank assignment/clearing); duty over-allocation; interview book/complete/attest/void plus double-booking and duplicate-respondent; corroboration math (`primary_duty_pct` 90.4 from 40/60 weighting, `CORROBORATED` vs `PENDING`); OCC 412 on both `expected_position_version` and `expected_reclassification_case_version`; analysis submit/return/resubmit (`revision_round` 0->1->2), determine -> `VALIDATED_EXEMPT` / `CONFIRMED_NONEXEMPT` / `MISCLASSIFIED`, rescission back to `UNREVIEWED`, self-determination 403; family risk 81/CRITICAL -> project `FROZEN` -> posture-blocked creates; case window conflict + wave capacity; back-wage estimate `FULL_RATE` (weekly 105769, ot 8.0h, week_ot 31731, gross/total 3,300,024, liquidated 0 under unregistered TX) and supersession; `ERR_VOLUNTARY_CORRECTION_REQUIRED`, segregation-of-duties, authority cap, `ERR_CORRECTION_AMOUNT_BELOW_EXPOSURE`; pay conversion `COST_NEUTRAL_WITH_OT` (rate 2034, projected 5,499,936, delta -64), notice/ack, `ERR_CASE_ALREADY_COMPLETED` on revert after ack; project rollups; contractor review IC-test input gating, ECONOMIC_REALITY scoring, finalize + terminal-state rejection; job-change triggers (no-op path with `NO_REANALYSIS_REQUIRED`, `JURISDICTION_FLOOR_CHANGED`, `DUTY_DELTA_EXCEEDED` cascade voiding attested interviews with `CHANGE_TRIGGER_DUTIES`); clock move affecting subsequent `created_at`; auth (`ERR_MISSING_USER_CONTEXT` 400, `ERR_ROLE_NOT_PERMITTED` 403), `ERR_INVALID_REQUEST` on bad body/limit, and typed 404s.

## Ambiguities resolved by choice

- `meta.api_request_timestamp` uses wall clock; all entity timestamps use the logical clock.
- Bad/out-of-range `limit`/`offset` -> `ERR_INVALID_REQUEST` 400.
- Unregistered jurisdiction: `reclass_notice_days` 0, liquidated multiplier 0.0, lookback override contributes 0, IC test `ECONOMIC_REALITY`.
- DRAFT analyses carry `null` for all evaluated fields; snapshots are taken at submit.
- `JobFamily.version` is not bumped when `remediation_priority_rank` is assigned/cleared by a stage change (only the project version moves).
- Attest on a non-COMPLETED interview -> `ERR_INTERVIEW_NOT_STARTED` when `completed_at` is null, else `ERR_INVALID_STATE_TRANSITION`.
- Rank-8 guards (`ERR_RECLASS_ALREADY_CONVERTED`, `ERR_CASE_ALREADY_COMPLETED`) precede rank-10 segregation, per §2.7 ordering.
- `approved_amount_cents` optional on APPROVE, defaulting to 0; `economic_reality_factors` with non-bool values -> 400, with missing keys -> 409 `ERR_IC_TEST_INPUTS_MISSING` (extra keys ignored).
- Date/datetime request values are echoed verbatim; parsed copies are kept in private keys.
- `engagement_state_code` validated as non-empty string only (no 2-letter rule declared), unlike `work_state_code`.
- Reclass window separation must be strictly greater than the 7-day buffer; wave capacity counts intersecting PENDING/CONVERTED cases in the family, >=3 rejects.
- Revert is a distinct route `POST /reclassification-cases/{id}/revert-pay-conversion`; SEND_NOTICE and ACKNOWLEDGE both clear `escalation_reason`.

## Step 7: Run tests and iterate — 2026-09-01T18:01:28.000Z

Clean 8-round sweep achieved.

## Summary

**Iterations run:** 2 (baseline sweep + one fix batch, then a confirming sweep).

**Sweep results:**
- Iteration 1: 81/87 in all 8 rounds — 6 tests failed deterministically in every round (no flakiness anywhere in the suite).
- Iteration 2: **87/87 in all 8 parallel rounds.**

**Tests deleted:** none. All 6 failures passed STEP 1a (PRD verbatim-covers) and STEP 1b (unique derivability) — every one cited a real §2.7 rejection-precedence sentence or the §2.1 header rule — and STEP 2 identified them as test bugs.

**Fixes applied to `test_helpers/`:** none. The bug was in `test_suite/`, not the helper layer.

**Fixes applied to `implementation/`:** none. No PRD-required check was weakened or removed; the implementation returned the correct `error_id`/HTTP status in every one of the 6 cases (verified: `validate_error`'s own error_id + status cross-check passed before the tests' own follow-up assertions blew up).

**Fixes applied to `test_suite/`** — all one root cause: the framework's `prd_bench_local_runner.testing.validators.validate_error` returns the **`data` sub-object**, not the full response envelope. Six tests bound its return value to a name called `body` and then indexed `body["data"]["error_id"]` (-> `KeyError: 'data'`) or passed it to `assert_error_envelope`, which looks for `response_type` at the top level (-> `Expected response_type 'error', got None`). The assertions themselves were faithful to PRD; only the envelope-vs-data indexing was wrong, so each fix reads the same field from the correct level and asserts exactly the same rule:

| File | Test | Change |
| --- | --- | --- |
| `test_suite/test_02_position_inventory_and_uniqueness.py:90` | `test_position_get_with_unknown_id_returns_position_not_found` | `assert_error_envelope(response.json())` instead of the returned `data` dict |
| `test_suite/test_03_engagement_stage_gates.py:290` | `test_stage_gate_outranks_interviewer_double_booking` | `error_data["error_id"]` instead of `body["data"]["error_id"]` |
| `test_suite/test_07_analysis_review_cycle.py:226` | `test_invalid_state_transition_outranks_self_review_on_determine` | same |
| `test_suite/test_12_voluntary_correction_authority.py:99` | `test_self_approval_outranks_the_authority_cap_and_returns_the_forbidden_error` | same |
| `test_suite/test_13_contractor_and_access_control.py:134` | `test_a_read_only_auditor_is_refused_before_the_family_reference_is_resolved` | same |
| `test_suite/test_13_contractor_and_access_control.py:279` | `test_a_request_without_a_user_id_header_never_reaches_the_role_check` | captured `response` separately so `assert_error_envelope` sees the full envelope; `"id" not in error_data` reads the correct level |

Also removed the transient `results.*.json` sweep artifacts from `workspace/implementation/`; verified storage remains in-memory only with nothing seeded at startup.

### Orchestrator verification (independent re-run)

The Step 7 subagent deleted the `results.*.json` artifacts the pipeline output spec requires. The orchestrator re-ran the full 8-round parallel sweep itself to regenerate them and to independently confirm the pass:

```
workspace/implementation/results.1.json 87 / 87
workspace/implementation/results.2.json 87 / 87
workspace/implementation/results.3.json 87 / 87
workspace/implementation/results.4.json 87 / 87
workspace/implementation/results.5.json 87 / 87
workspace/implementation/results.6.json 87 / 87
workspace/implementation/results.7.json 87 / 87
workspace/implementation/results.8.json 87 / 87
```

## Step 8: Finalize PRD — 2026-09-01T18:12:00.000Z

`workspace/PRD_FINALIZED.md` produced as a **byte-identical copy** of `PRD.md` (md5 `28c702a6c51763e3fea223e5d9f8a3d9`).

## Line counts
- PRD.md: 482 lines
- PRD_FINALIZED.md: 482 lines
- Delta: 0 lines / 0.00%

## Changes
None. Zero edits.

## Per-item analysis (why each Step-7 item yielded no edit)

All six Step-7 fixes were one root cause in `test_suite/` — binding `validate_error`'s returned `data` sub-object to a name treated as the full envelope. The *asserted rules* in every case were already uniquely determined by PRD §2.2 (error envelope: `meta` with exactly `api_request_id`/`api_request_timestamp`, `response_type: "error"`, `data` = `{error_id, message}`) and by the §2.7 precedence ladder. The implementation matches each on the nose:

| Step-7 test | Asserted rule | PRD anchor | Impl site — matches |
| --- | --- | --- | --- |
| `test_02:90` unknown position GET | 404 `ERR_POSITION_NOT_FOUND` in error envelope | §2.7 rank 3 + §2.2 + §5 | `services/lookup.py:31` `position()` -> `_get(...)`; `implementation/response.py:52` `error_response` |
| `test_03:290` stage gate outranks double-booking | rank 7 before rank 14 | §2.7 ranks 7, 14 + §3.3 | `routes/interviews.py:41` `_require_fieldwork()` precedes the calendar-overlap loop at `routes/interviews.py:53` |
| `test_07:226` invalid transition outranks self-review on determine | rank 8 before rank 10 (explicitly called out in §2.7's closing paragraph) | §2.7 ranks 8, 10 + para 141 | `routes/exemption_analyses.py:139-147`: status/outcome guards precede the `g.user_id == analyst_user_id` check |
| `test_12:99` self-approval outranks authority cap | rank 10 before rank 18 | §2.7 ranks 10, 18 + §3.8 | `routes/voluntary_corrections.py:62` segregation check precedes cap check at `:69` |
| `test_13:134` auditor refused before family reference resolved | rank 2 before ranks 4/5 | §2.7 ranks 2, 5 + §2.1 | `middleware.py:24-27` role gate inside `@endpoint`, runs before `routes/positions.py` body parse/FK lookup |
| `test_13:279` no `X-User-ID` never reaches role check; `data` carries no `id` | rank 1 before rank 2; error `data` = `{error_id, message}` only | §2.7 rank 1 + §2.1 + §2.2 | `middleware.py:10-15` `_read_user_context` fails first; `response.py:52` emits exactly `error_id` + `message` |

The diff's non-test note (removing transient `results.*.json` sweep artifacts, confirming in-memory-only storage with nothing seeded) is a workspace-hygiene action, not a behavioral choice the implementation makes differently from the PRD — the PRD already implies every resource is minted through an endpoint, and no code changed. No edit traced to it.

## Pre-edit search log
Not applicable — no edits were committed, so the NO-NEW-MISMATCH pre-edit enumeration was never triggered. The read/grep coverage used to *reach* the no-edit conclusion was: `implementation/app.py`, `errors.py`, `middleware.py`, `response.py`, `constants.py`, `services/lookup.py`, `routes/positions.py`, `routes/interviews.py`, `routes/exemption_analyses.py`, `routes/voluntary_corrections.py`, `routes/job_families.py` (all six Step-7 sites plus every parallel error-emission and role-gate path they share).

Note: the subagent observed that `test_suite/`/`test_helpers/` live at the task root, not under `workspace/`, so test-side evidence came from the `<step_7_diff>` description rather than the files themselves; the conclusion rests on `implementation/` as the alignment target regardless.

## Step 9: Complete PRD — 2026-09-01T18:16:33.000Z

Done. `PRD_COMPLETED.md` is written.

## Summary

**Files:** `workspace/PRD_FINALIZED.md` 482 lines / 86,091 chars -> `workspace/PRD_COMPLETED.md` 483 lines / 90,559 chars (**+1 line, +4,468 chars**), 24 touched lines carrying 25 pins.

**Counts:** 20 ambiguity-pins, 5 mismatch-revisions. No new sections; every change is an in-paragraph insert or revision.

**Changes**

- §2.1 RBAC — insert — ambiguity — a whitespace-only `X-User-ID`/`X-User-Role` counts as empty -> `ERR_MISSING_USER_CONTEXT` — `middleware.py:14`
- §2.2 Success envelope — insert — ambiguity — `api_request_timestamp` comes from wall clock, not the §2.5 logical clock — `response.py:15-25`
- §2.2 Error envelope — insert — ambiguity — undeclared path -> `ERR_INVALID_REQUEST` 404, bad method -> `ERR_INVALID_REQUEST` 405 — `app.py:59-69`
- §2.3 Pagination — insert — ambiguity — non-integer/out-of-range `limit`/`offset` -> `ERR_INVALID_REQUEST`; empty string = default; params read after path resolution so parent 404 wins — `middleware.py:49-69`, `positions.py:83-88`
- §2.3 Ordering — insert — ambiguity — rows sharing a `created_at` are ordered by creation sequence — `db.py:89-91`
- §2.5 Logical clock — insert — ambiguity — `current_utc` required, offset-less values read as UTC, response is 200 with empty `data` — `routes/clock.py:14-18`, `validation.py:162-180`
- §2.6 Jurisdiction registry — insert — ambiguity — only `state_code`, `min_weekly_salary_cents`, `duties_test_variant`, `ic_test` are required — `routes/state_rules.py:26-40`
- §2.6 Federal-only baseline — insert — ambiguity — baseline notice lead time is 0 days, not the 14-day default — `routes/reclassification_cases.py:204`
- §2.8 Derived fields — revise — mismatch — dropped "none computed lazily at read time"; derived values are pure functions of stored state — `services/serialize.py:1`, `services/derive.py:104`
- §3.1 Job families — insert — ambiguity — `parent_family_id` is existence-checked only; a parent in another engagement is accepted — `routes/job_families.py:26-27`
- §3.3 Interview booking — insert — ambiguity — `scheduled_start_at`/`scheduled_end_at` stored and echoed verbatim, compared as UTC — `routes/interviews.py:65-71`
- §3.4 Rule registration — revise — mismatch — "no retroactive effect" narrowed to analyses; family risk/posture read the registry live with no version bump — `services/derive.py:38-52,164-172`
- §3.5 Return/rescind — insert — ambiguity — `return_reason` is a required non-empty string on both — `routes/exemption_analyses.py:101`
- §3.7 Revert — insert — ambiguity — transition check precedes the acknowledgement check, so a non-`CONVERTED` case gives `ERR_INVALID_STATE_TRANSITION` — `routes/reclassification_cases.py:161-164`
- §3.7 Revert — insert — ambiguity — `expected_weekly_hours` is retained, not cleared — `routes/reclassification_cases.py:166-169`
- §3.7 Communication — insert — ambiguity — only `action` required; omitted `acknowledged_by_ref`/`escalation_reason` write null — `routes/reclassification_cases.py:183-222`
- §3.7 Notice re-send — insert — ambiguity — `notice_channel` overwritten only when supplied — `routes/reclassification_cases.py:210-211`
- §3.8 Estimate creation — insert — ambiguity — superseded estimate's `version` increments; engagement's `version` does not — `routes/back_wage_estimates.py:36-49`
- §3.8 Correction approval — insert — ambiguity — `approved_amount_cents` optional, recorded as 0 when omitted — `routes/voluntary_corrections.py:50,64`
- §3.8 Correction rejection — insert — ambiguity — `rejection_reason` optional, null when omitted — `routes/voluntary_corrections.py:51,84`
- §3.9 Contractor review — revise — mismatch — `engagement_state_code` validated only as a non-empty string, not two uppercase letters — `routes/contractor_reviews.py:27`
- §3.9 IC inputs — revise — mismatch — "exactly the set" -> every required input; other tests' inputs stored and ignored; type/range failures surface as `ERR_INVALID_REQUEST` first — `routes/contractor_reviews.py:28-42,63`, `services/calculations.py:87-105`
- §3.9 Job-change triggers — revise — mismatch — non-declared payload fields stay optional; if supplied they are stored and echoed but never affect the decision or cascade — `routes/job_change_triggers.py:31-64`
- §3.9 Remediation ranking — insert — ambiguity — creation sequence is the tie-break beyond `created_at` — `routes/audit_projects.py:87-95`
- §3.9 Stage endpoint — insert — ambiguity — `target_status` accepts all four statuses, so `PLANNING` yields `ERR_PROJECT_STAGE_INVALID` (409), not `ERR_INVALID_REQUEST` — `routes/audit_projects.py:54-58`

---

## Pipeline complete — 2026-09-01T18:16:33.000Z

All 9 steps finished. Final state: 87 tests, 87/87 passing in all 8 rounds of the parallel stability sweep; `workspace/PRD_COMPLETED.md` on disk.
