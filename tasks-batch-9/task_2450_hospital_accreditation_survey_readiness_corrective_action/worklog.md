# Worklog — task_2450_hospital_accreditation_survey_readiness_corrective_action

## Step 1: Create task directory — 2026-09-02T19:48:01.164Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2450_hospital_accreditation_survey_readiness_corrective_action/` and `workspace/` via `mkdir -p`. Index 2450 was pre-assigned by the invoking pipeline; no scan of `./tasks/` was performed and no index was allocated locally (32 concurrent pipelines on this host would collide).

## Step 2: Generate Scaffold — 2026-09-02T21:10:36.921Z

All three artifacts are complete and the linter is clean.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2450_hospital_accreditation_survey_readiness_corrective_action/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

**Lint verdict** (`python3 skills/prd-bench-scaffold-generator/scaffold_lint.py tasks/task_2450_...`):
```
Coverage
  §1.5 endpoints declared:    45
  §1.1 entities declared:     13
  §1.8 instances scanned:     27
  §1.9 instances scanned:     80
  Calls scanned (§1.8+§1.9):  914

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**SCAFFOLD.yaml counts** — domain `hospital-accreditation-survey-readiness`, prefix `/accreditation`; archetype `compliance_audit` + `posture_driven_gating`; topology `graph`, SM shape `parallel`, role model `segregation_of_duties`, consistency `immediate`:
13 entities · 9 state machines · 2 concurrency rules · 9 calculations · 44 validations · 45 endpoints · 56 errors · 7 roles.

**Difficulty design (§1.8)** — all 9 rules, 3 differentiated instances each (27 total): `dual_variant_calc` 3, `combinatorial_formula` 3, `non_linear_state_machine` 3, `transitive_cascade` 3, `priority_pair_validation_conflict` 3, `boundary_precision_check` 3, `cross_entity_state_dependency` 3, `resource_temporal_overlap` 3, `compensating_invariant` 3.

**Corner design (§1.9)** — 9 sections, 110 instances (80 with full `test_recipe`, 30 `excluded_because` stubs that each cite a §1.8 instance by exact name):
entities 12 (12 full) · state_machines 22 (16) · calculations 17 (6) · validations 31 (21) · endpoints 6 (5) · errors 3 (3) · rbac 10 (10) · cross_cutting_complexity_layers 8 (6) · consistency_model 1 (1).

**Extra verification done**: instance names are unique across both design files; every stub carries `name`/`claim_type`/`grounds` and no `test_recipe`; all 56 §1.6 error ids are exercised somewhere in §1.8/§1.9.

**One SCAFFOLD.yaml fix made while designing §1.9**: validation priority 17 previously demanded `window_state == CLOSED with follow_up_required == true`, which made `ERR_FOLLOW_UP_NOT_REQUIRED` (priority 32) unreachable. Priority 17 now admits any `CLOSED` window and explicitly defers the flag/deadline checks to priority 32.

The hard constraint was honored throughout: no sibling `task_*/` directory was listed, globbed, grepped, or read.

## Step 3: Copy Shared Files — 2026-09-02T21:10:36.921Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T21:25:11.229Z

PRD generation and verification are complete.

## Deliverable

`workspace/PRD.md` — **474 lines**

## Section list

§1 Introduction · §2 Global Specifications & System-Wide Principles (2.1 Actors and RBAC, 2.2 API Response Structure, 2.3 Pagination/Sorting/Collection Filters, 2.4 The Logical Clock and Its Sweeps, 2.5 Common Resource Properties and Version Semantics, 2.6 Numeric Precision/Rounding/Date Arithmetic, 2.7 Stale-View Protection on Unit and Finding Writes, 2.8 Path Traversal and Referential Resolution, 2.9 Conserved Ledgers and Cascading Recomputation, 2.10 Segregation of Duties, 2.11 Validation Precedence) · §3 Business Logic & Workflows (3.1 Chapters/Standards/Accountability Map, 3.2 Evidence Repository, 3.3 Hospital Units/Posture/Readiness Scoring, 3.4 Mock Tracer Program, 3.5 Rounding/Deficiency Ticketing/Remediation, 3.6 Survey Window Prediction and Command Center Activation, 3.7 Survey Findings/Risk Classification/Condition-Level Escalation, 3.8 ESC Submission/Clarification/Acceptance, 3.9 PPR Self-Assessment) · §4 Endpoint Definitions · §5 Error Code Catalogue

## Tail completeness — VERIFIED, not truncated

The final section is §5 and it ends with a **complete 56-row table**; the last content line is the table row `| \`ERR_CHAPTER_NOT_MAPPED\` | 422 |`, a full row terminated by a trailing newline — not mid-sentence, not mid-row, no dangling table pipe. §4 (the section immediately before) likewise ends with its complete 45th row (`/_clock/set_current_utc`). No audit footer or Hard Contract report was written into the file.

## Scaffold coverage (mechanically checked against SCAFFOLD.yaml)

| Element | Scaffold | Covered | Where |
| --- | --- | --- | --- |
| Entities | 13 | 13 | §3.1–§3.9; all **107 field names** appear verbatim in backticks |
| State machines | 9 | 9 | §3.1–§3.9; all **53 transitions** with triggers, guards and side effects |
| Calculations | 9 | 9 | §3.3, §3.4, §3.5, §3.6, §3.7, §3.8, §3.9 — all in prose, no operators |
| Validations | 44 | 44 | §2.11 ladder (priorities 1–44 with `applies_to` scopes) + restated in §3 |
| Endpoints | 45 | 45 | §4 table (4 columns: Method, Path, Description, Authorized Role(s)) |
| Errors | 56 | 56 | §5 table (2 columns: Error ID, HTTP Status Code) |
| Roles | 7 | 7 | §2.1 + §2.10; all authorized-role cells in §4 |
| Concurrency rules | 2 | 2 | §2.7 (`expected_unit_version`/`ERR_STALE_UNIT_VERSION`, `expected_finding_version`/`ERR_STALE_FINDING_VERSION`, both 412) |

Per-entity prose mentions: Chapter 141, Standard 209, OwnerAssignment 18, EvidenceItem 11, HospitalUnit 5, MockTracer 13, TracerObservation 44, RoundingSession 19, DeficiencyTicket 16, SurveyWindow 10, SurveyFinding 105, EscSubmission 4, PprSelfAssessment 27. SurveyWindow's two independent dimensions are both named (`window_state` ×10, `command_center_state` ×6) with every value present (PROJECTED, ELIGIBLE, ACTIVE_SURVEY, CLOSED, STANDBY, ACTIVATED, DEMOBILIZED).

## Hard Contract reports

**Contract 1 — Field-Name Coverage: PASS.** 428 backticked tokens scanned outside code fences. 0 missing entity fields (107 required), 0 missing endpoint request-body/path/query inputs (56 required), 0 missing query params, 0 missing response-shape fields, 0 missing error ids (56), 0 missing roles (7), 0 missing state values.

**Contract 2 — Rule Coverage: PASS.** All 44 validations stated with their integer priority and `applies_to` scope in §2.11; both OCC rules with rejection error and status in §2.7; all 53 state-machine transitions with cross-entity side effects (both conserved ledgers — `chapter_mapped_standard_ledger` and `unit_penalty_ledger` — documented in §2.9 with their increment/decrement pairing); all 9 calculations including the three dual-variant pairs (attested vs projected readiness, initial vs clarification ESC deadline, self-reported vs evidence-verified PPR); all field-level defaults; sibling-branch symmetry covered explicitly for revoke/reject/abort/escalate/mark-remediated/accept branches so no branch is described only by its complement.

**Contract 3 — §3 Path Purity: PASS.** 889 backticked tokens scanned inside §3: 0 tokens beginning with `/`, 0 bare HTTP-method tokens, 0 method+path combinations; 0 raw occurrences of `/accreditation` and 0 of `POST` anywhere in §3. Endpoint paths appear only in §2.11 (scope declarations) and §4.

## Constraint compliance

Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced at any point. No worked-example numbers or `test_recipe` asserts could have leaked; every constant in the PRD (15 penalty points, 40-point cap, bands 90.00/75.00/60.00, severity days 45/30/14/1, severity points 1/3/7/15, rate thresholds 0.3400/0.8000, 45/60-day deadlines, 18/36 months, 30/60-day leads, 21/10 clarification days, 2 clarification rounds, 10.00 overstatement threshold, credits 1.0/0.5/0.0, rating points 100/50/0) traces directly to a `SCAFFOLD.yaml` line.

**Orchestrator's independent truncation check (per the known doc-generator failure mode):** `tail -20 PRD.md` ends at `| \`ERR_CHAPTER_NOT_MAPPED\` | 422 |` — a complete table row at a real section boundary. `grep -c '^| \`ERR_'` = 56, matching the scaffold's 56 errors. All 5 top-level sections and 20 subsections present. **Not truncated; no regeneration needed.**

## Step 5: Generate Unit Tests — 2026-09-02T22:22:33.477Z

Test infrastructure and suite are complete for task 2450.

## Files

**`test_helpers/`** (2402 lines)

| file | lines |
|---|---|
| `types.py` | 481 |
| `assertions.py` | 311 |
| `api_client.py` | 264 |
| `api_errors.py` | 128 |
| `fixtures.py` | 822 |
| `factories.py` | 171 |
| `constants.py` | 100 |
| `test_users.py` | 77 |
| `__init__.py` | 48 |

**`test_suite/`** (6850 lines + 61-line `conftest.py`, 137 test functions → 147 collected cases)

| file | lines | tests |
|---|---|---|
| `test_01_readiness_scoring_variants.py` | 324 | 6 |
| `test_02_deficiency_due_dates_and_unit_posture.py` | 537 | 9 |
| `test_03_finding_classification_and_esc_deadlines.py` | 540 | 8 |
| `test_04_survey_window_dimensions_and_ppr_variants.py` | 311 | 7 |
| `test_05_cascading_recomputation.py` | 533 | 11 |
| `test_06_validation_precedence_and_preconditions.py` | 605 | 12 |
| `test_07_tracer_and_rounding_occupancy.py` | 221 | 4 |
| `test_08_chapter_standard_and_unit_records.py` | 568 | 13 |
| `test_09_tracer_scheduling_and_lifecycle.py` | 552 | 11 |
| `test_10_tracer_scoring_and_readiness_reads.py` | 308 | 6 |
| `test_11_evidence_repository_and_independence.py` | 274 | 5 |
| `test_12_rounding_sessions_and_deficiency_tickets.py` | 339 | 6 |
| `test_13_role_authorization_and_unit_scope.py` | 297 | 7 |
| `test_14_survey_window_lifecycle_and_prediction.py` | 411 | 9 |
| `test_15_findings_and_response_cycle.py` | 369 | 9 |
| `test_16_ppr_self_assessments.py` | 296 | 5 |
| `test_17_identifiers_pagination_and_versioning.py` | 360 | 9 |

## Test count by queue

- **Queue A (Difficulty, §1.8):** 57 tests over all **27/27** instances (9 rules × 3), every instance carrying ≥2 tests.
- **Queue B (Corner, §1.9):** 80 tests over all **80/80** live instances (entities 12, state_machines 16, calculations 6, validations 21, endpoints 5, errors 3, rbac 10, cross_cutting 6, consistency_model 1).
- 107 distinct `Design:` tags = 27 + 80. **Zero coverage gaps.**

## Instances translated vs skipped

**Skipped: none.** Every non-stub instance in both indices was translatable — each had verbatim PRD coverage and a uniquely-derivable outcome. The 30 `excluded_because:` corner stubs were not translated (verified: no stub name appears anywhere in `test_suite/`).

What *was* dropped is a handful of individual sub-assertions inside otherwise-translated instances, where the design yaml asserted something the PRD does not pin. Grouped by silence pattern:

- **computed-field / rendering silence (4):** `participating_weight_pct` in the stopped (no-participating-chapter) path; `MockTracer.window_start/window_end` fractional rendering (§2.6's instant list omits them); `chapter_breakdown` row-internal key names; `created_at` exact instant values (PRD never says `created_at` is stamped from the logical clock) — asserted as format instead.
- **branch-asymmetry silence (2):** a NON_COMPLIANT observation on an `UNMAPPED` standard (§3.4 declares only the `MAPPED→` and `EVIDENCE_COMPLETE→DEFICIENT` branches); the `UNMAPPED`-source chapter counter effects.
- **cross-entity-cascade silence (2):** whether the 201 body of the write that *causes* a cascade already reflects the cascaded state (worked around by re-reading); whether the newly filed self-assessment whose own flagging triggers the `ON_TRACK → AT_RISK` flip is itself returned for reassessment.
- **design/PRD conflicts where the PRD won (3):** yaml asserted `risk_level IMMEDIATE_THREAT` where §3.7's index arithmetic gives `HIGH`; yaml asserted `RETURNED_FOR_REASSESSMENT` on a single-escalation chapter where §3.9 requires two; yaml asserted a unit `version` *unchanged* by tracer START where §2.5/§3.4 say it is bumped.
- **design setup contradicting the ladder (1):** `follow_up_open_without_follow_up_required_rejected` staged a DEMOBILIZED command centre, but ladder rung 18 (`ERR_COMMAND_CENTER_NOT_ACTIVATED`) precedes rung 32. I re-activated the command centre before the trigger (`DEMOBILIZED → ACTIVATED` is a declared entry point) so the instance's actual claim — rung 32 surfacing over rung 17 — is exercised faithfully.

## Design-tag confirmation

An AST-based audit over all 17 files confirms: every one of the 137 test functions has a docstring whose **last non-empty line** is exactly one `Design:` line; **zero** tests have zero or two tags; every tag resolves to a real instance in the correct index and section; no tag points at an `excluded_because:` stub. All PRD quotations (≈400) were machine-checked as verbatim whitespace-normalised substrings of `workspace/PRD.md` — 0 misses. No `pytest.mark.skip/skipif/xfail` anywhere; no occurrence of the word "scaffold" in `test_suite/` or `test_helpers/`.

## Execution

Full sweep against the reference implementation (`prd-bench-local-run --isolation per-test-server`, server restarted and DB emptied before each test): **147/147 passed, 0 failed, 0 errors, 0 skipped** (results at `/tmp/t2450_full_results2.json`). The first sweep surfaced 4 real defects in the tests (the two PRD-conflict items above), which I fixed and re-verified.

**Orchestrator note:** this Step 5 "147/147" figure was obtained against a reference implementation the test-generator subagent built for itself, *not* against Step 6's `workspace/implementation/` — the two steps ran concurrently by design (physical isolation), so Step 5 could not have seen Step 6's output. It is therefore not evidence that the real pairing passes. Step 7's 8-round sweep is the authoritative check.

## Step 6: Generate Implementation — 2026-09-02T22:22:33.477Z

The implementation is complete and verified.

## Files (all under `workspace/implementation/`)

| File | Lines |
|---|---|
| `app.py` | 85 |
| `store.py` | 101 |
| `errors.py` | 128 |
| `envelope.py` | 68 |
| `auth.py` | 46 |
| `helpers.py` | 250 |
| `calc.py` | 212 |
| `cascade.py` | 359 |
| `serialize.py` | 275 |
| `routes/__init__.py` | 1 |
| `routes/chapters.py` | 120 |
| `routes/standards.py` | 96 |
| `routes/evidence.py` | 150 |
| `routes/units.py` | 70 |
| `routes/tracers.py` | 269 |
| `routes/rounding.py` | 293 |
| `routes/windows.py` | 271 |
| `routes/findings.py` | 191 |
| `routes/ppr.py` | 179 |
| `routes/clock.py` | 52 |
| `start.sh` | 14 |
| `requirements.txt` | 1 |

Total 3231 lines.

## Endpoints

**45 endpoints implemented — an exact set-match against SCAFFOLD §1.5** (verified programmatically by diffing Flask's `url_map` against the scaffold's endpoint table: zero missing, zero extra). Note the scaffold declares 45, not 48. That covers chapters/standards/owner-assignments, the evidence repository, units + the dual-variant readiness read, mock tracers + observations, rounding/deficiency tickets, survey windows + findings, the ESC response cycle, PPR self-assessments, and `POST /_clock/set_current_utc`.

## Constraint confirmations

- **In-memory only**: all state lives in plain dicts on the `Store` singleton in `store.py`. Grep confirms no `sqlite`, `pickle`, `shelve`, `redis`, file `open(`, or `/tmp` usage anywhere; the only `json.dumps` is the HTTP response body writer. `PYTHONDONTWRITEBYTECODE=1` is exported by `start.sh` and stray `__pycache__` dirs were removed.
- **No seeding**: `Store.reset()` creates empty collections only. A fresh boot answers every list endpoint with `total_count: 0`, and the logical clock starts at the fixed `2026-08-01T00:00:00.000Z`. No entity is created at import or startup.
- **`start.sh`**: reads `$PORT` (default 10000), guards the pip install with `python3 -c "import flask"`, and `exec python3 app.py` runs Flask in the foreground bound to `0.0.0.0`.
- **Boot check**: `bash start.sh` was run repeatedly on fresh processes (ports 10731–10745). Latest clean run booted in <4 s and answered `POST /accreditation/chapters` with `201` and a correct envelope.

## Behaviour smoke-tested end to end

Full lifecycle exercised on a fresh server: chapter/standard/owner mapping (`UNMAPPED→MAPPED→EVIDENCE_COMPLETE`), evidence SUBMIT/VALIDATE with `ERR_SEGREGATION_OF_DUTIES`, tracer OCC (`ERR_STALE_UNIT_VERSION`), 60-min turnaround conflict, `ERR_TRACER_WINDOW_NOT_STARTED`, tracer COMPLETE scoring (`tracer_score 66.67`, chapter rate `0.6667`, base `66.67`, band `AT_RISK`), ticket creation with band-snapshot acceleration (HIGH 14d → 7d, `accelerated: true`), penalty ledger 7 → readiness 59.67 → `NOT_READY`, UnitManager scope + role gating, `ERR_SESSION_NOT_CLOSED` then VERIFY releasing points, survey window prediction/eligibility via the clock sweep, command-center gating, `LOCKED_FOR_SURVEY` cascade, a WIDESPREAD condition-level finding, close-survey due-date derivation (`2026-10-25`), `ERR_CONDITION_LEVEL_ESCALATION_REQUIRED` → escalate → submit → clarification (capped due `2026-10-01`) → accept → `FOLLOW_UP_PENDING` → follow-up survey close → `ACCEPTED`, and the PPR cycle (dual scores, `ERR_DUPLICATE_RESOURCE`, duplicate-rating 400, `ERR_STANDARD_CHAPTER_MISMATCH`, escalation count 2 → chapter `AT_RISK` → `RETURNED_FOR_REASSESSMENT`, revise with no double-charge, attest and `ERR_PPR_ALREADY_ATTESTED`). Envelope shape, pagination meta, 401/403/404/405 JSON handlers all confirmed.

Per instruction, `test_suite/` and `test_helpers/` were never read.

## Step 7: Run Tests and Iterate — 2026-09-02T22:35:57.605Z

Clean sweep on the first iteration — no fixes were required.

## Summary

**Iterations run:** 1

**Sweep verification (authoritative):**
- 8 concurrent rounds launched under `setsid nohup`, `--isolation per-test-server`, joined with `wait`; process group confirmed gone before reading results.
- All 8 `results.{1..8}.json` parse as JSON and each reports `passed: 147, failed: 0, errors: 0, skipped: 0, total: 147`.
- `workspace/sweep.log` independently contains 8 `Results: 147/147 passed, 0 failed, 0 errors, 0 skipped` lines (round duration ~289 s under host contention). No `Terminated` / `RemoteDisconnected` reaping signature.
- Union of failing tests across all 8 rounds: **empty**. No flakiness surfaced — the timing-sensitive areas (tracer occupancy with 60-min trailing buffer, `expected_unit_version` / `expected_finding_version` stale-view guards at rung 8, rounding-capacity intersection, logical-clock sweeps) were stable across every round.

**Tests deleted:** none. No test failed either sub-check of STEP 1, so no PRD-silence or unique-derivability collapse had to be adjudicated.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

**Key findings / notes:**
- The prior worklog's Step 5 "147/147" figure was measured against the test-generator's own throwaway reference implementation, so it was *not* evidence about the real pairing. This sweep is the first authoritative check of `workspace/implementation/` against `test_suite/`, and the real pairing passes at full strength.
- Storage constraint spot-checked and holds: all state is in-memory dicts on the `Store` singleton (`workspace/implementation/store.py`), with no seeding at boot — which is why 147 per-test-server restarts × 8 rounds produced identical results.
- Final passing `results.1.json` … `results.8.json` are left in place at `workspace/implementation/`.

**Orchestrator's independent re-verification of the Step 7 sweep artifacts** (a known failure mode is a Step 7 subagent claiming a clean sweep while leaving no `results.*.json` behind, so the orchestrator does not take the claim on trust):
- `ls -la workspace/implementation/results.*.json` → all 8 files present, each ~49 KB, mtime 22:29.
- Each file independently parsed with `json.load` → every round reports `passed=147 failed=0 errors=0 skipped=0 total=147`.
- `grep -c "Results:" sweep.log` → 8 (one completion line per round, all `147/147`).
- `grep -c "Terminated" sweep.log` → 0, confirming no SIGTERM reaping contaminated the run.
**Verdict: the clean 8-round sweep is genuine.**

## Step 8: Finalize PRD — SKIPPED — 2026-09-02T22:35:57.605Z

**Skip condition met per the skill's Step 8 spec.** Step 7 exited on its *first* 8-round sweep with 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline. There is therefore no `<step_7_diff>` to hand off: Step 7 produced no evidence of any site where `PRD.md` failed to determine a behavior the implementation exhibits, and Step 8's edit scope is defined as exactly those sites. Spawning the subagent with an empty diff could only produce out-of-scope edits, which the skill forbids.

No `workspace/PRD_FINALIZED.md` is produced. Step 9 will therefore take `workspace/PRD.md` as its source, per its stated input rule.

Reasoning recorded here rather than escalated, per the pipeline's non-interactive autonomy contract.

## Step 9: Complete PRD — 2026-09-02T22:51:30.112Z

Verified and complete. `PRD_COMPLETED.md` ends at the final error-catalogue row `| ERR_CHAPTER_NOT_MAPPED | 422 |` — no truncation, no mid-table cut.

## Metrics

- Source: `workspace/PRD.md` — 474 lines, 97,232 chars
- Output: `workspace/PRD_COMPLETED.md` — 474 lines, 110,587 chars
- Char delta: **+13,355**; line delta: **0** (every change is an in-paragraph insert or revision; no new paragraphs, no new sections, no reordering)
- **44 changed lines: 37 ambiguity-pins, 7 mismatch-revisions**

## Changes

**Mismatches (PRD prose contradicted implementation)**

- §2.3 — revise — mismatch — `mode` was cross-referenced to §2.7 (stale-view protection); it is defined in §3.3, and the readiness read takes no pagination at all — `routes/units.py:60`
- §2.11 rung 13 — revise — mismatch — rung enumerated "finding … actions as declared in §3" and listed `revoke`; impl guards findings at rung 20 (`ERR_FINDING_NOT_AWAITING_RESPONSE`) and revoke at rung 22, so rung 13 never fires for either. Replaced the hand-wave with the literal ticket/window transition table and noted `OPEN_SURVEY`'s exemption — `routes/windows.py:103-115`, `routes/rounding.py:244-250`, `routes/findings.py:46,89,158`, `routes/standards.py:87`
- §3.1 — revise — mismatch — `weight_pct` "carried to two decimal places" read as a validation constraint; impl stores `q2(weight_pct)`, rounding finer input half up rather than rejecting — `routes/chapters.py:52`, `calc.py:99`
- §3.3 — revise — mismatch — posture re-evaluation was said to fire "on a failed verification"; `FAIL_VERIFICATION` touches only the ticket. Also pinned that `LOCKED_FOR_SURVEY` survives ledger re-evaluation while readiness is still recomputed — `routes/rounding.py:274-277`, `cascade.py:306`
- §3.6 — revise — mismatch — "The first activation advances the window's `version`"; every activation touches the window. Added that re-activating from `ACTIVATED` is `ERR_INVALID_STATE_TRANSITION` and that both demobilize failure modes share that code ahead of temporal guards — `routes/windows.py:105-110,138`
- §3.6 — revise — mismatch — `CLOSE_SURVEY` "with no precondition"; impl requires `window_state == ACTIVE_SURVEY` else `ERR_INVALID_STATE_TRANSITION`. Pinned the no-follow-up branch (`follow_up_required` false, `follow_up_due_at` null, demobilize only if `ACTIVATED`) — `routes/windows.py:111,176-179`
- §5 — revise — mismatch — "Every failure response carries one of the identifiers below"; three framework errors sit outside the table (`ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500), and an absent/invalid body is coerced to `{}` rather than rejected — `app.py:58-75`, `helpers.py:17-18`

**Ambiguity-pins**

- §2.1 — insert — ambiguity — whitespace-only `X-User-ID` is `ERR_UNAUTHENTICATED`; role compare is exact/case-sensitive — `auth.py:24-27`
- §2.2 — insert — ambiguity — `api_request_timestamp` comes from the logical clock, so it repeats across same-instant requests — `envelope.py:38`
- §2.3 — insert — ambiguity — non-base-ten `limit`/`offset` is `ERR_INVALID_REQUEST`; empty-string parameter means omitted — `helpers.py:168-185`
- §2.3 — revise — ambiguity — `has_more` pinned as `offset + len(data) < total_count`; `_seq` tie-break made explicit for same-`created_at` rows — `envelope.py:57`, `store.py:98`
- §2.3 — insert — ambiguity — filters are exact case-sensitive matches; empty/absent filter ignored; non-matching value yields an empty page, not an error — `routes/ppr.py:121-123`
- §2.4 — revise — ambiguity — the clock is assigned unconditionally (backwards moves allowed, sweeps run identically); response `data` carries exactly three fields — `routes/clock.py:20,46-52`
- §2.4 — insert — ambiguity — neither sweep touches any `HospitalUnit` (no readiness/band/posture recompute) — `routes/clock.py:22-44`
- §2.5 — insert — ambiguity — `version` moves at most once per request per entity; a resource created in-request stays at `version` 1; `updated_at == created_at` for such resources — `store.py:69-82,94`
- §2.6 — insert — ambiguity — Decimals serialise as JSON numbers, so trailing zeros are lost (`0.00` → `0.0`); counts/points/`version` are integers — `envelope.py:23-25`
- §2.6 — revise — ambiguity — tracer occupancy compares minute-truncated instants while storing full precision; rounding sessions truncate to the second; interval sanity uses the untruncated values — `calc.py:122-128`, `routes/tracers.py:69-76`
- §2.8 — insert — ambiguity — where a body carries two FKs, `unit_id` resolves first (mock-tracers, findings) — `routes/tracers.py:38`, `routes/windows.py:195`
- §2.9 — insert — ambiguity — readiness recomputation counts as a mutation only when score or band actually changes — `cascade.py:281`
- §2.11 rung 3 — insert — ambiguity — undeclared body keys ignored; five declared fields validated then discarded (`reason`, ticket `note`, window `note`, `rationale`, `attestation_note`) — `routes/standards.py:81`, `routes/rounding.py:219`, `routes/windows.py:93`, `routes/findings.py:41`, `routes/ppr.py:166`
- §2.11 rung 10 — insert — ambiguity — rung 3 only type-checks the sample counts, so zero/negative fall through to rung 10 — `helpers.py:63`
- §2.11 rung 32 — insert — ambiguity — a null `follow_up_due_at` counts as expired — `routes/windows.py:135`
- §3.1 — insert — ambiguity — the `UNMAPPED → MAPPED` posture change is conditional on the standard actually being `UNMAPPED`; a `DEFICIENT` standard keeps `DEFICIENT` — `cascade.py:87`
- §3.1 — revise — ambiguity — revocation `reason` is validated but never persisted — `routes/standards.py:81`
- §3.2 — insert — ambiguity — `SUBMIT` leaves `reviewed_by_user_id`/`review_note` untouched, so an old rejection note survives resubmission — `routes/evidence.py:124-131`
- §3.2 — insert — ambiguity — the evidence-complete transition fires only from `MAPPED`; otherwise only `validated_evidence_count` rises — `cascade.py:117`
- §3.2 — insert — ambiguity — both `REJECT` entry points write `reviewed_by_user_id` and `review_note`; an omitted note overwrites with null — `routes/evidence.py:141-144`
- §3.3 — insert — ambiguity — chapters examined in creation order, which is also `chapter_breakdown` order; unassessed unit returns base 0.00 / penalty 0 / weight 0.00 / empty breakdown — `cascade.py:204,217-228`
- §3.3 — insert — ambiguity — a zero observation denominator yields rate `0.0000` rather than an error — `cascade.py:235`
- §3.3 — insert — ambiguity — per-chapter contribution rounded half up to 2dp (round-then-sum) while the division uses the unrounded weight sum — `cascade.py:250`
- §3.3 — revise — ambiguity — the readiness read is a derivation, not a resource (no `id`/`created_at`/`updated_at`/`version`); 8 top-level fields; `mode` echoed as `ATTESTED` when omitted; breakdown elements carry exactly 6 fields with `rate` and `compliance_rate` as synonyms; bad `mode` rejected before the unit lookup; empty `mode` treated as omitted — `cascade.py:250-277`, `routes/units.py:60-69`
- §3.4 — insert — ambiguity — `abort_reason` optional on both `ABORT` entry points, storing null when omitted — `routes/tracers.py:140,199`
- §3.4 — insert — ambiguity — the completion cascade moves only `MAPPED`/`EVIDENCE_COMPLETE` standards; others get only a restamp plus `version` bump; each standard visited once, in first-`NON_COMPLIANT`-observation order — `routes/tracers.py:187-194`, `cascade.py:147`
- §3.5 — insert — ambiguity — session `close` takes no body; the still-`OPEN` check runs before the escalated-ticket check — `routes/rounding.py:115-127`
- §3.5 — insert — ambiguity — `FAIL_VERIFICATION` runs no ledger re-evaluation; only the ticket is mutated — `routes/rounding.py:274-277`
- §3.5 — revise — ambiguity — the ledger moves by the delta between new and old points (so a `LIFE_SAFETY` escalation of an already-`IMMEDIATE_THREAT` ticket moves nothing) and the re-evaluation runs either way — `routes/rounding.py:285-291`
- §3.6 — insert — ambiguity — reopening for a follow-up resets nothing: `survey_closed_at`, `condition_level_finding_count`, `follow_up_required`, `follow_up_due_at` all persist — `routes/windows.py:144`
- §3.7 — insert — ambiguity — escalation writes `follow_up_due_at` only when `survey_closed_at` exists, touches the window regardless, and returns the finding — `routes/findings.py:60-69`
- §3.8 — insert — ambiguity — the submission call returns the submission record, not the finding — `routes/findings.py:128`
- §3.8 — insert — ambiguity — "newest round" means highest `submission_round`; omitted `decision_note` writes null; the ruling returns the finding, not the submission — `routes/findings.py:141-145,173,191`
- §3.9 — revise — ambiguity — `self_ratings` is required, but an empty array is well formed — `routes/ppr.py:19-21`
- §3.9 — insert — ambiguity — a zero denominator gives `self_score`/`verified_score`/`gap` all 0.00 and no flag — `cascade.py:346`
- §3.9 — insert — ambiguity — `ppr_escalation_count` never decrements; the filing assessment excludes itself from the reassessment cascade it triggers — `routes/ppr.py:110`, `cascade.py:59`
- §3.9 — insert — ambiguity — revision rewrites `flagged_overstatement` from the new gap (may fall back to false) without refunding the point, and also self-excludes from the cascade — `routes/ppr.py:146-157`
- §3.9 — revise — ambiguity — `attestation_note` validated but persisted nowhere — `routes/ppr.py:166`

**Orchestrator's independent verification of Step 9:**
- `wc -l -c` → `PRD.md` 474 lines / 97,232 chars; `PRD_COMPLETED.md` 474 lines / 110,587 chars (+13,355 chars, 0 line delta) — matches the subagent's report exactly.
- `tail -5 PRD_COMPLETED.md` ends at `| \`ERR_CHAPTER_NOT_MAPPED\` | 422 |`, a complete final table row at a real section boundary. **Not truncated.**
- `diff <(grep "^#" PRD.md) <(grep "^#" PRD_COMPLETED.md)` → empty: identical section structure, confirming the "no new sections, no reordering" constraint held.
- `diff PRD.md PRD_COMPLETED.md | grep -c "^>"` → 44 changed lines, matching the reported 37 ambiguity-pins + 7 mismatch-revisions.
- Invariants preserved: 56 `ERR_` catalogue rows and 45 endpoint rows, same as `PRD.md`.
- `find implementation -newer implementation/results.1.json` (excluding `__pycache__`) → **no `.py` or `start.sh` modified after the sweep**, so Step 9 confined itself to the PRD and the verified 8-round 147/147 result still describes the code on disk.

**Pipeline complete.** `workspace/PRD_COMPLETED.md` written; Step 9 was the final step.
