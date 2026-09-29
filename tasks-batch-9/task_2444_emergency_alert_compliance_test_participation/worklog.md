# Worklog — task_2444_emergency_alert_compliance_test_participation

## Step 1: Create task directory — 2026-09-02T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2444_emergency_alert_compliance_test_participation` and its `workspace/` subdirectory. Index 2444 was pre-assigned by the invoking pipeline; no scan of `./tasks/` was performed and no index was allocated locally (concurrent pipelines on this host would collide).

## Step 2: Generate scaffold design indices (PARTIAL RESUME) — 2026-09-02T19:13:00.000Z

RESUME DECISION (orchestrator): on entry, `SCAFFOLD.yaml` already existed and was complete (2545 lines, all of §1.0–§1.7: scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles), but BOTH `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were absent. No downstream artifact existed (no PRD.md, no test_suite/, no test_helpers/, no implementation/), so a full Step 2 re-run would have been safe but would have discarded 2545 lines of complete, conformant scaffold. I therefore ran Step 2 in a preserve-SCAFFOLD mode: the subagent was instructed to treat the existing SCAFFOLD.yaml as the authoritative given, NOT to modify it, and to emit only the two missing §1.8/§1.9 design indices derived from it. Verified after exit that SCAFFOLD.yaml's mtime was unchanged (19:08).

Subagent summary (verbatim):

Both design-index files are complete and the lint is clean.

## Deliverables

| File | Lines | Coverage |
|---|---|---|
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2632 | **9/9 rule_ids**, **26 non-stub instances** (3 per rule except `transitive_cascade` = 2) |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 5941 | **9/9 §1.9 sections**, **85 instances = 72 non-stub + 13 `excluded_because` stubs** |

Corner section breakdown (non-stub / stubs): entities 13/0, state_machines 14/6, calculations 13/2, validations 9/2, endpoints 6/0, errors 5/0, rbac 8/0, cross_cutting_complexity_layers 2/3, consistency_model 2/0.

Verified mechanically: single top-level keys `scaffold_difficulty_design` / `scaffold_corner_design`; every instance carries `name`/`grounds`/`distinguishing_aspect`/`test_recipe{setup,setup_api_calls,trigger,assert}` (stubs carry `excluded_because` and no `test_recipe`); **zero duplicate names across the union of both files**; every stub's `difficulty_instance` resolves to a real §1.8 instance name; **all 60 §1.5 endpoints are actually invoked** by at least one call (149 distinct call strings, 1440 call sites); **all 58 declared `errors[].id` values are referenced** (the only unreferenced `ERR_XXX` is the envelope placeholder in SCAFFOLD.yaml line 58, not a catalogue entry).

`SCAFFOLD.yaml` was not modified — mtime is still 2026-09-02 19:08:28, well before this session's writes.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /tmp/s2444.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    60
  §1.1 entities declared:     12
  §1.8 instances scanned:     26
  §1.9 instances scanned:     72
  Calls scanned (§1.8+§1.9):  1440

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Defect found in the given SCAFFOLD.yaml (needs a decision upstream)

`scaffold_lint.py <task-dir>` cannot run against the artifact as written:

```
ERROR: yaml parse failed for SCAFFOLD.yaml: while parsing a flow sequence
  in "SCAFFOLD.yaml", line 1777, column 12
expected ',' or ']', but got '?'
```

Cause: 15 endpoint `input:` lines use the optional-field notation `input: [state_code?, status?, limit?, offset?]`. PyYAML rejects a bare `?` inside a flow sequence, and `scaffold_lint.py::_load_yaml` calls `yaml.safe_load` with no sanitizer. Note SKILL.md's own §1.5 example uses this same notation, so the generator spec and the linter disagree — this is not specific to task 2444.

Workaround used (SCAFFOLD.yaml itself left untouched per instruction): a sanitized copy at `/tmp/s2444.yaml` with those 15 lines' optional tokens quoted (`"state_code?"`, …), then the linter's 3-explicit-path form. Fixing this properly means either quoting the optional tokens in the scaffold generator's output or adding a pre-parse sanitizer to `scaffold_lint.py`.

One design note worth flagging for the test-writing stage: 24 instances carry names matching the linter's `_NEGATIVE_NAME_RE` (`_cannot_`, `_rejected`, `_not_found`, `_forbidden`, `_unauthorized`, `_missing_auth`), which exempts *all* their calls — including setup — from role and payload checking. I hand-verified the roles and required inputs for those (notably the three-role inspection chain: draft-response StationEngineer, submit-response CertifyingOfficer, close FieldInspector; and `POST /wireless-alert-notices` requiring all five inputs) rather than relying on the clean verdict.

## Step 3: Copy shared files — 2026-09-02T19:13:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T21:05:00.000Z

Orchestrator verification before proceeding: `workspace/PRD.md` is 478 lines, ends cleanly on the final row of the §5 error table (`| ERR_PENALTY_CEILING_EXCEEDED | 422 Unprocessable Entity |`) with no mid-sentence/mid-table truncation, and all five top-level sections are present (§1 Introduction, §2 Global Specifications, §3 Business Logic & Workflows, §4 Endpoint Definitions, §5 Error Code Catalogue). Not a truncated-generator failure; accepted as-is.

Subagent summary (verbatim):

PRD generated and verified.

**Output:** `workspace/PRD.md` — 478 lines (479 counting the final unterminated line), ends at the last row of the §5 error table (a genuine document end, no audit footer).

Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced; no sibling task directory was read.

**Section list**

- `# EAS Compliance API — Product Requirements Document`
- `## 1. Introduction` (3 paragraphs)
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Operator Identity and Role-Based Access Control · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 The Logical Clock · 2.5 Record Identity and Audit Fields · 2.6 Numeric Precision and Rounding · 2.7 Version Guards on Station and Test-Event Writes · 2.8 Rejection Precedence: The Validation Ladder · 2.9 Path Resolution and Not-Found Reporting · 2.10 Station Recompute Events, Score Bands and Posture · 2.11 Two Deterministic Cascades · 2.12 Segregation of Duties and Public-File Custody
- `## 3. Business Logic & Workflows` — 3.1 State Plans, Source Requirements and Alert Forwarding Rules · 3.2 Station Registration and Alert Equipment Readiness · 3.3 Monitoring Obligations: Assignments, Receipts and Silence · 3.4 Equipment Failure, Repair Cycles and the Two Downtime Clocks · 3.5 Alert Reception: Duplicate Avoidance, Relay Selection and Accessibility · 3.6 Test Scheduling, Pre-Test Readiness and Log Retention · 3.7 Post-Test Filing, Penalty Points, Acceptance and Reversal · 3.8 Station Log Review and Compliance Scoring · 3.9 Public File Obligations and Inspection Response
- `## 4. Endpoint Definitions` (4 columns, 60 rows)
- `## 5. Error Code Catalogue` (2 columns, 58 rows)

**Completeness verification (mechanically re-checked against SCAFFOLD.yaml with a script, plus a tail read)**

- Tail check: file ends mid-nothing — last line is `| \`ERR_PENALTY_CEILING_EXCEEDED\` | 422 Unprocessable Entity |`. No mid-sentence/table/list/section truncation.
- Endpoints: **60 declared / 60 covered** — all 60 paths present in §4 with method + description + authorized roles; every write endpoint's inputs and side effects narrated in §3 (or §2 for OCC/clock).
- Entities: **12 / 12** narrated. Field-name coverage: `entities[].fields` 95 required / 95 present / 0 missing; `request_body` 44 / 44 / 0; `query_params` 27 / 27 / 0; `compliance-summary` response shape 14 / 14 / 0.
- Errors: **58 / 58** error ids appear in §5 and each is trigger-conditioned in §2 or §3 prose.
- State machines: **10 / 10** (StatePlan, Station.compliance_posture, EASDevice, MonitoringAssignment, EquipmentOutage, AlertEvent.relay_state, AlertEvent.accessibility_state, TestEvent, FilingRecord, InspectionRequest). All **60 transitions** written as explicit `FROM` -> `TO` arrow pairs with preconditions, error ids and side effects.
- Calculations: **9 / 9** (relay_rule_selection, duplicate_suppression_window, accessibility_pass_evaluation, filing_penalty_points, outage_downtime_hours dual-variant, station_compliance_score dual-variant, test_event_readiness_score, retention_until, inspection_completeness_score) — all constants embedded in business prose, all rounding positions pinned, no operator syntax (`==`/`>=`/`+=` scan clean), no fuzzy quantifiers.
- Validations: **12 / 12**, rendered as an explicitly ordered 12-rung ladder in §2.8 with every `applies_to` endpoint enumerated.
- Concurrency rules: **2 / 2** — both name write endpoint, `expected_station_version` / `expected_test_event_version`, mismatch rejection, exact error id and HTTP 412.
- Contract 1 Field-Name Coverage: **PASS**. Contract 2 Rule Coverage: **PASS**. Contract 3 §3 Path Purity: **PASS** (864 backtick tokens scanned in §3; 0 starting with `/`, 0 bare HTTP methods, 0 method+path).
- §2.2 compared byte-for-byte against `section-2.2-response-structure.md`: identical.

One scaffold discrepancy worth relaying: your brief said 5 roles, but `roles[]` declares **4** (`ComplianceAdmin`, `StationEngineer`, `CertifyingOfficer`, `FieldInspector`); the PRD follows the scaffold. Two places where the scaffold declares a precondition but nominates no error id (evaluate-readiness from a status other than `SCHEDULED`/`READINESS_PENDING`; submit-response with an empty `provided_document_kinds`) are specified with an HTTP 409 outcome — the second reusing `ERR_INSPECTION_NOT_DRAFTED`, the only candidate scoped to that endpoint — rather than inventing new error ids.

## Step 6: Generate implementation — 2026-09-02T21:35:00.000Z

Launched concurrently with Step 5 in a single assistant message, so the impl-gen subagent could not read `test_suite/` (the directory did not exist when it started).

Subagent summary (verbatim):

The implementation is complete and verified.

## Files written — `workspace/implementation/`

| File | Lines |
|---|---|
| `app.py` (factory, blueprint registration, envelope error handlers, `PORT`/`0.0.0.0`) | 96 |
| `clock.py` (logical clock, starts at `2026-08-01T00:00:00Z`, never reads wall clock) | 84 |
| `errors.py` (all 58 error ids -> HTTP codes, `ApiError`) | 92 |
| `envelope.py` (`meta`/`response_type`/`data`, pagination meta) | 49 |
| `store.py` (12 in-memory dicts, per-request version-bump guard, query helpers) | 157 |
| `auth.py` (rungs 1/2/5) | 49 |
| `validators.py` (rung 3 schema + rung 4 twelve existence getters + pagination) | 239 |
| `serializers.py` (12 entity serializers; WEA notice & log entry carry no `updated_at`/`version`) | 254 |
| `services/calculations.py` (all 9 calculations + pinned constants) | 368 |
| `services/scoring.py` (station scoring, 4-phase log review, both cascades) | 210 |
| `routes/` — `clock_routes` 20, `state_plans` 85, `stations` 135, `relay_rules` 93, `devices` 114, `assignments` 177, `outages` 189, `alerts` 159, `wea_notices` 69, `test_events` 140, `log_entries` 123, `filings` 186, `inspections` 140, `helpers` 37 | 1567 |
| `start.sh` (foreground, `$PORT`, guarded pip install, `exec python3 app.py`) | 18 |
| `requirements.txt` | 1 |

Total ~3284 lines. Storage is in-memory only; nothing is seeded at startup.

## Coverage
**60 / 60 declared endpoints registered** (verified via `url_map`). Also implemented: 12 entities, all 10 state machines, 9 calculations, the 12-rung ladder as the single ordering authority, both OCC guards (`expected_station_version` -> 412, `expected_test_event_version` -> 412), all 58 error ids, both deterministic cascades (outage 4-hop, plan-supersede 3-hop), the 11 recompute events, and parallel `relay_state` x `accessibility_state` dimensions.

## Verification
A ~330-assertion end-to-end smoke run (`/tmp/smoke_2444.py`, outside the deliverable) passes clean and confirms, among others:
- continuous vs obligation downtime (21:00->07:00 = 10.00 / 0.00 h; 87.00 h continuous breach with 40.00 obligation h), repair-cycle counter only incrementing from `VERIFICATION_FAILED`
- accessibility single-rounding (crawl 40 + -30.0 LUFS + `CAPTION_SUPPRESSED` = 3.70 -> FAILED; 75 s/-25.0/NONE = 0.00 -> PASSED)
- suppression phase A (`STATION_REPEAT`, reference id set) vs phase B (`WIRELESS_NOTICE`, reference null, FIPS-disjoint notice does not suppress); selector specificity/priority/`created_at` ranking and the plan-level MANDATORY override
- filing penalty round-per-entry-then-sum (3 late days -> 0.20 + 0.35 = 0.55 subtotal, 2.25 lateness, 0.50 unconfirmed relay, 3.30 total), amendment reversal with `SUPERSEDED_BY_AMENDMENT`, exact compensation back to 0.00, PROVISIONAL<->CERTIFIED variant flip
- ladder precedence spot-checks: `ERR_STATION_NOT_FOUND` before `ERR_DEVICE_NOT_FOUND`, `ERR_RECEIPT_COVERAGE_INCOMPLETE` before `ERR_SEGREGATION_OF_DUTIES`, `ERR_SEGREGATION_OF_DUTIES` before `ERR_PENALTY_CEILING_EXCEEDED`, `ERR_FILING_DEADLINE_PASSED`
- outage-cascade hop 4 (station -> `SUSPENDED_FILINGS` reverts `READY` events to `READINESS_PENDING` with readiness figures cleared) and plan-supersede hop 3 (`RESPONDED` -> `RESPONSE_DRAFTED`, `provided_document_kinds` retained)

**Boot check: PASS.** `PORT=18744 bash start.sh` (and a second run on 18755) came up in the foreground on `0.0.0.0`, answered `POST /state-plans` with 201 and `GET /state-plans?limit=1` with 200 in the correct envelope, then was killed; the port is closed and no stray process remains. `__pycache__` directories were removed, so only source files ship.

## Step 5: Generate unit tests — 2026-09-02T21:55:00.000Z

Launched concurrently with Step 6 in a single assistant message.

Subagent summary (verbatim):

Generation is complete for task_2444. Both stages are on disk, audited, and collect cleanly.

## Files written

**Stage 1 — `test_helpers/` (2,270 lines)**
| file | lines |
|---|---|
| `constants.py` | 148 |
| `types.py` | 314 |
| `api_client.py` | 289 (one method per PRD §4 endpoint + `api_client` singleton) |
| `api_errors.py` | 146 (60 error ids + status map registered at import) |
| `test_users.py` | 56 (four roles + the dual-duty operator) |
| `factories.py` | 184 |
| `assertions.py` | 285 |
| `fixtures.py` | 696 (tiers 1–5 composite setups) |
| `__init__.py` | 152 (barrel) |

**Stage 2 — `test_suite/` (10,232 lines, 18 test files + 47-line `conftest.py`)**
Queue A: `test_01_station_scoring_variants` 275 · `test_02_accessibility_and_penalty_formulas` 307 · `test_03_parallel_state_machines` 507 · `test_04_cascade_propagation` 345 · `test_05_validation_priority_conflicts` 307 · `test_06_threshold_boundaries` 354 · `test_07_cross_entity_gates` 330 · `test_08_suppression_windows` 361 · `test_09_compensating_invariants` 341.
Queue B: `test_10_entity_shapes` 725 · `test_11_state_machine_corners` 1306 · `test_12_calculation_corners` 1345 · `test_13_validation_corners` 767 · `test_14_endpoint_contract_corners` 623 · `test_15_error_catalogue_corners` 567 · `test_16_role_authorisation_corners` 1143 · `test_17_complexity_layer_corners` 312 · `test_18_consistency_model_corners` 270.

## Test count and coverage

- **221 test functions, 260 collected items** (parametrize expansion). `pytest test_suite --collect-only` -> 260 collected, 0 errors, 0 warnings; pyflakes clean.
- **Queue A (§1.8): 26 / 26 non-stub instances translated, 0 skipped**, every instance carrying >=2 tests.
- **Queue B (§1.9): 72 / 72 non-stub instances translated, 0 skipped.**
- **13 stubs emitted no tests**; I independently verified all 13 `difficulty_instance:` pointers resolve to real `name:` entries in the difficulty yaml — no broken pointers. (A 14th `excluded_because:` hit in the corner yaml is the header comment describing the convention, not an instance.)

## Audit results (my own scripted pass, not the subagents' self-reports)

- Every test carries **exactly one** trailing `Design:` line; all 221 tags resolve to a real instance name under the matching `rule_id` / `section`. No untagged, dual-tagged or dangling-tag tests.
- **559 PRD citations, all now literal single-line substrings of `PRD.md`.** 354 had been line-wrapped inside docstrings (content faithful, but a strict literal grep would have missed them); I reflowed each onto one line and re-verified 559/559 literal, with every test holding at least one literal citation.
- No `pytest.mark.skip`/`xfail`, no placeholders; no occurrence of "scaffold" or scaffold section refs anywhere in `test_suite/` or `test_helpers/`.
- `SCAFFOLD.yaml` unmodified; nothing read or written under `workspace/implementation/`; no sibling task directory touched.

## Skipped instances

None — all 98 non-stub instances passed the PRD-first two-condition filter. The gaps that surfaced were **sub-assertion level**, dropped inside otherwise-translated instances, the notable ones being: breach-flag state after `fail-verification` (PRD clears `restored_at` and both hour figures but is silent on the flags); `retention_until_max` before `close-logging`; pre-verification accessibility defaults; `ERR_DEVICE_DECOMMISSIONED` on assignment create (PRD pins only `ERR_DEVICE_NOT_READY` there); `Station.version` not incrementing on a public-file upload (contradicts §2.5); and the design's expectation that a `READY` event's late re-evaluation returns `ERR_READINESS_WINDOW_NOT_OPEN` (§2.8 puts the state check first, so it is unreachable). Two design-recipe defects were corrected against the PRD: a suppressed alert keeps `matched_relay_rule_id` null / `relay_class_applied` `NONE`, and phase-A station repeat requires the *same* `originator_sequence`. Server-stamped instants are asserted by parsed instant or prefix rather than exact string, since the PRD pins the three-fractional-digit spelling only for `created_at`.

One interface note for future files: `test_helpers` exports three `test_`-prefixed names (`test_event_version`, `test_event_payload`, `test_log_entry_payload`) that pytest collects as tests if imported unaliased; every test file imports them aliased or via the module.

## Step 7: Run tests and iterate — 2026-09-02T22:30:00.000Z

Orchestrator independent verification (per the known failure mode where a Step 7 subagent claims a clean sweep without leaving artifacts): 8 `results.{1..8}.json` present under `workspace/implementation/`, each parsed directly — all report `passed=260 total=260 failed=0 errors=0 skipped=0`. `grep -rn "mark.skip\|mark.xfail" test_suite/ test_helpers/` returns 0 hits. Sweep confirmed genuine.

Subagent summary (verbatim):

Clean 8-round sweep achieved. Here is the summary block.

---

## Summary

**Iterations run:** 3 (baseline sweep -> fix batch -> confirmation sweep; plus a targeted 30x isolation re-run to adjudicate one load-induced flake).

**Final sweep numbers (all 8 parallel rounds):**

| Round | Passed / Total | Failed | Errors | Skipped |
|---|---|---|---|---|
| 1 | 260 / 260 | 0 | 0 | 0 |
| 2 | 260 / 260 | 0 | 0 | 0 |
| 3 | 260 / 260 | 0 | 0 | 0 |
| 4 | 260 / 260 | 0 | 0 | 0 |
| 5 | 260 / 260 | 0 | 0 | 0 |
| 6 | 260 / 260 | 0 | 0 | 0 |
| 7 | 260 / 260 | 0 | 0 | 0 |
| 8 | 260 / 260 | 0 | 0 | 0 |

**Tests deleted:** none. 221 test functions / 260 collected items remain intact.

**Fixes applied to `test_suite/`:**

1. `test_suite/test_11_state_machine_corners.py` — `TestReceiptLogEntryReactivation::test_receipt_log_line_returns_a_silent_assignment_to_active`: dropped two post-append station-summary assertions (`assert_summary_inputs(summary, silent_assignment_count=0)` and `assert_score_and_posture(summary, 100.00, "COMPLIANT")`). **STEP 1c partial coverage / STEP 1b unique-derivability failure.** Design tag: `Corner/state_machines/receipt_log_entry_reactivates_a_matching_silent_assignment`.
   - The assertions require a *station recompute event* to fire on a `RECEIPT` test-log-line append. PRD §2.10 states verbatim: *"There are eleven recompute events, and each of them re-runs the station scoring described in §3.8 in full"* — and the enumerated eleven do **not** include appending a test log line (they include "recording a receipt against a monitoring assignment", i.e. the explicit `record-receipt` endpoint, only). Against that, §3.6 says *"A `RECEIPT` line additionally refreshes the matching assignment's `last_receipt_at` and returns that assignment to `ACTIVE` if it was `SILENT`, exactly as an explicit receipt would."* Two divergent PRD-faithful readings exist: (i) "exactly as an explicit receipt would" imports the full explicit-receipt semantics including the recompute; (ii) the closed eleven-event enumeration is authoritative and the "exactly as" clause is scoped to the two named row effects — reinforced by §3.3, which spells out the log-line path as stamping `last_receipt_at` and returning the row to `ACTIVE` while pointedly omitting the "Either way a station recompute event fires" sentence it attaches to the explicit path. Since `silent_assignment_count` is a stored station field (§2.5: *"A freshly registered station has ... `silent_assignment_count` 0"*) refreshed only in scoring phase 3, reading (ii) legitimately leaves it at 1 and the score at 90.00. Not uniquely derivable -> the two uncovered assertions removed; every PRD-covered assertion in the test (row `SILENT`->`ACTIVE`, `silence_flagged_at` cleared, `last_receipt_at` stamped, `logged_entry_count` -> 1, event stays `READY`, and the pre-append 90.00/`COMPLIANT` summary that follows a genuine log-review recompute) was kept.

2. `test_suite/test_16_role_authorisation_corners.py` — `_run_full_role_chain()` helper (consumed by `test_each_role_completes_its_own_exclusive_operations_in_one_pass` and `test_the_end_to_end_pass_lands_certified_and_compliant`): added a re-read of the test event at the end of the chain before populating `rows`. **STEP 2 test bug — stale snapshot.** Design tag: `Corner/rbac/each_role_completes_its_own_exclusive_operations_in_one_end_to_end_pass`.
   - The chain's local `event` variable was last assigned from the `close-logging` response (status `LOGGED`) and never refreshed, so `rows["test_event"]` was a pre-filing snapshot while the test correctly asserted `status == "FILED"`. The assertion is PRD-faithful — §3.7: *"A successful filing is stored in `SUBMITTED` with `reversal_reason` null, increments the event's `version` by one, and advances the event to `FILED`."* The fix makes the test more faithful (it now observes the event's true final state) rather than weakening the assertion.

**Fixes applied to `test_helpers/`:** none required.

**Fixes applied to `implementation/`:** none. No implementation defect was found; both failures traced to the test artifact, and the implementation's reading of the eleven-recompute-event enumeration was upheld.

**Load-induced flake adjudicated, not "fixed":** in the second sweep, `test_11_state_machine_corners::TestLoggedTestEventSealsLogging::test_close_logging_twice_is_rejected` failed in rounds 3 and 4 only, with `RemoteDisconnected` and `ConnectionResetError(104)` respectively — the documented contention signature. `close_logging` in `workspace/implementation/routes/test_events.py` contains no timing logic (a plain status guard, `retention_until_max` refresh, and `touch`). I ran the test 30x with a freshly booted server per iteration: 30/30 passed. Confirmed host contention; no change made, and the endpoint was clean across all 8 rounds of the confirmation sweep.

**Hygiene verified after the clean sweep:** zero `mark.skip` / `mark.xfail` anywhere in `test_suite/` or `test_helpers/`; zero disk-persistence primitives (`sqlite`, `open(`, `json.dump`, `/tmp`, `pickle`, `shelve`) in `implementation/`, so storage stays in-memory only and `start.sh` re-invocation wipes all state; no entity data seeded at startup; no endpoint, response field, side effect, header, or capability added; all `__pycache__` removed; no stray servers left listening; `pytest --collect-only` -> 260 collected, 0 errors.

## Step 8 skip-condition adjudication — 2026-09-02T22:32:00.000Z

Step 7 exited with 0 deletions, 0 `test_helpers/` fixes and 0 `implementation/` fixes, but **2 `test_suite/` fixes**, so the skip condition (which requires all four counts to be zero) does NOT apply and Step 8 runs. Substantively, fix #1 is exactly the signal Step 8 exists to act on: it documents a genuine PRD ambiguity (§2.10's closed eleven-recompute-event enumeration versus §3.6's "exactly as an explicit receipt would" clause) that the implementation resolved one way. Fix #2 is a pure stale-snapshot test bug and is expected to yield no PRD edit.

## Step 8: Finalize PRD — 2026-09-02T22:35:00.000Z

Subagent summary (verbatim):

`PRD_FINALIZED.md` written. Three inline edits, all tracing to Step 7 item 1.

## Size

| | PRD.md | PRD_FINALIZED.md | Delta |
|---|---|---|---|
| lines | 478 | 478 | 0 (+0.0%) |
| words | 12,149 | 12,400 | +251 (+2.07%) |
| bytes | 87,276 | 89,009 | +1,733 (+1.99%) |

3 of 478 lines touched (0.63%); no sections added or removed.

## Changes

- **§2.10 (recompute-event lead-in)** — revise — marked the eleven-event enumeration explicitly **closed** ("no write outside it rescores a station, however similar its row effects may look to one that does") — `implementation/services/scoring.py:112` (`recompute_station`), reached from exactly 11 sites.
- **§2.10 (list bullet 5)** — revise — "recording a receipt against a monitoring assignment" narrowed to "…through the explicit `POST /monitoring-assignments/{id}/record-receipt` capability", so the bullet cannot be read as covering the `RECEIPT` log-line path — `implementation/routes/assignments.py:127`.
- **§3.3 (receipts paragraph, final sentence)** — revise — "same receipt effect" -> "same *assignment-row* effect"; added that the log-line path also clears `silence_flagged_at`, fires **no** station recompute, and does not rewrite the station row at all (`accessible_source_count`, `silent_assignment_count`, `penalty_points_total`, `compliance_score`, `compliance_variant_applied`, `compliance_posture`, `updated_at`, `version` all unchanged), with the concrete `silent_assignment_count` = 1 / 10.00-point-deduction consequence spelled out — `implementation/routes/log_entries.py:92-101` (no `recompute_station`, no `touch(station)`).
- **§3.6 (logging paragraph)** — revise — dropped the load-bearing-but-wrong "exactly as an explicit receipt would" universal; replaced with the explicit assignment-row writes plus two disclaimers: (1) not a §2.10 recompute event, (2) no assignment-status gate — a matching assignment in any status other than `SILENT` keeps its status and the line is still accepted — `implementation/routes/log_entries.py:96-101`, `implementation/routes/assignments.py:117-118`.

**Item 2 (test_16 stale snapshot): no PRD edit.** Verified `create_filing` at `implementation/routes/filings.py:119-120` sets `event["status"] = "FILED"` and `touch(event)` (version +1), which is verbatim what §3.7 already states. Pure fixture bug; nothing to pin.

## Pre-edit search log

**Edit 1 + 2 (§2.10 closed enumeration / receipt bullet)**
- (a) Subject: the complete set of writes that fire a station recompute event.
- (b) Enumerated: `grep -rn "recompute_station\|outage_cascade\|plan_supersede_cascade"` over all of `implementation/`. Exactly 11 trigger sites, matching the PRD list one-for-one: `routes/stations.py:119` (log review, `log_review=True`), `routes/assignments.py:84` (create), `:127` (record-receipt), `:146` (decommission), `:176` (reinstate), `routes/outages.py:69` -> `services/scoring.py:178` (outage create, hop 3), `routes/outages.py:180` (close), `routes/filings.py:123` (create), `:158` (accept), `:178` (reverse), `routes/state_plans.py:84` -> `services/scoring.py:202` (plan-supersede hop 2). Also read `routes/log_entries.py` (no recompute), `routes/stations.py:123-135` (`public-file-documents` mutates the station row but does **not** rescore), `routes/clock_routes.py` reference in §2.4 (no recompute), `routes/test_events.py` (`evaluate-readiness`, `close-logging` — no recompute), `routes/alerts.py` (via grep — no recompute).
- (c) Adjustment: wrote "no write outside it rescores a station" rather than "no write outside it mutates a station", because `public-file-documents` does mutate the station row (`public_file_document_count`, `version`) without rescoring. Bullet 5 was scoped by naming the endpoint rather than by adding a negative carve-out, to avoid asserting anything about paths the bullet never covered.

**Edit 3 (§3.3 log-line receipt path)**
- (a) Subject: the full write set of a `RECEIPT` test-log-line append, and what it does *not* touch on the station.
- (b) Enumerated: `routes/log_entries.py:33-103` in full; `grep -rn "last_receipt_at\|silence_flagged_at"` over `implementation/` — all five writers: `routes/assignments.py:64-65` (create defaults), `:120-123` (explicit receipt), `routes/log_entries.py:97-100` (this path), `routes/outages.py:175` (close -> `SUSPENDED`->`SILENT` stamps `silence_flagged_at`), `services/scoring.py:121-124` (phase-1 silence sweep). Read `store.py:70-79` (`touch` bumps `version` once per row per request, no-op on unversioned rows) and `store.py:94-95` (`assignments_of_station` — no status filter). Read `routes/stations.py:90-112` (`compliance-summary`) to confirm `silent_assignment_count`, `accessible_source_count`, `compliance_score` are served from **stored** station fields while `outage_breach_count` / `unfiled_test_count` are computed live.
- (c) Adjustment: restricted the "not rewritten / `updated_at` and `version` not refreshed" claim to the **station** row only — `touch(event)` and `touch(assignment)` do fire on this path, so a blanket "no row is rewritten" would have been a new mismatch. Also wrote "keep the values the last recompute event left them at" rather than naming specific values, and named only the six phase-3/phase-4 station fields (leaving `outage_breach_count` / `unfiled_test_count` out, since those are not stored).

**Edit 4 (§3.6 "exactly as an explicit receipt would")**
- (a) Subject: how far the log-line receipt's equivalence to the explicit `record-receipt` endpoint extends.
- (b) Enumerated: `routes/assignments.py:109-128` (explicit receipt: ownership check -> `ERR_ASSIGNMENT_NOT_ACTIVE` on `DECOMMISSIONED` -> stamp -> `SILENT`->`ACTIVE` -> `recompute_station`) side by side with `routes/log_entries.py:59-101` (rung-9 `ERR_LOG_ENTRY_SOURCE_UNKNOWN` requires >=1 matching assignment of **any** status, then stamps every matching row and flips only the `SILENT` ones, no recompute). Re-checked `store.assignments_of_station` for a hidden status filter — there is none. Re-read §2.8 rung 9 and §3.6's `ERR_LOG_ENTRY_SOURCE_UNKNOWN` sentence: both already say "at least one monitoring assignment of that station" with no status qualifier, so the added disclaimer is consistent with them.
- (c) Adjustment: two. (i) Added the explicit "no assignment-status gate" disclaimer, because deleting "exactly as an explicit receipt would" without it would have left a fresh implementer free to import `ERR_ASSIGNMENT_NOT_ACTIVE` into the log-line path, which the impl does not do. (ii) Deliberately left PRD's singular "the matching assignment" verbatim rather than widening it to "every matching assignment": the impl loops over all rows whose `source_call_sign` matches, but multi-match was never exercised by Step 7, so the looser existing wording is kept rather than pinning a behavior no diff item revealed.

## Step 9: Complete PRD — 2026-09-02T22:51:00.000Z

Orchestrator verification: `workspace/PRD_COMPLETED.md` is 479 lines, retains all five top-level sections (§1–§5) and ends cleanly on the final row of the §5 error catalogue — not truncated. Confirmed Step 9 touched nothing else: the newest mtime under `workspace/implementation/`, `test_suite/` and `test_helpers/` is 22:05, well before Step 9 started (~22:36), so the passing implementation and the 8-round-clean test suite are byte-identical to what Step 7 signed off.

Subagent summary (verbatim):

Done. `PRD_COMPLETED.md` written; nothing else touched.

## Counts

- **Source vs output:** `PRD_FINALIZED.md` 478 lines / 89,009 chars -> `PRD_COMPLETED.md` 479 lines / 96,316 chars (**+1 line, +7,307 chars**). 28 in-place paragraph revisions + 1 inserted bullet; no sections added, no lines deleted.
- **Ambiguity-pins: 24. Mismatch-revisions: 5.**

## Changes

- §2.2 — revise — ambiguity — `api_request_timestamp` is read from the logical clock, not wall clock — `envelope.py:20`
- §2.2 — insert — ambiguity — undefined path -> 404 / undefined method -> 405, both with `ERR_INVALID_REQUEST` (the one id whose status §5 doesn't fix) — `app.py:64-73`
- §2.3 — revise — ambiguity — non-integer / out-of-range `limit`, negative `offset` -> `ERR_INVALID_REQUEST` 400; empty-string param = omitted — `validators.py:158-177`
- §2.3 — revise — ambiguity — `created_at` ties broken by monotonic insertion sequence; no endpoint overrides the ordering — `store.py:82-87`
- §2.3 — revise — ambiguity — `has_more` formula; filters are exact case-sensitive string equality; `obligation_breached` accepts `true/1/false/0`; empty/unrecognised/unknown params ignored — `envelope.py:38`, `routes/helpers.py:8-30`
- §2.4 — revise — ambiguity — clock-set response `data` is an empty object — `routes/clock_routes.py:20`
- §2.5 — revise — ambiguity — `version` bumps at most once per request regardless of how many steps mutate a row; rows created by the request return `version` 1 / `updated_at` == `created_at` even when later steps fill fields in — `store.py:65-79`
- §2.8 — revise — ambiguity — JSON `null` counts as absent everywhere (required -> 400, optional -> default, `source_call_sign: null` on `TRANSMISSION` accepted); required strings must be non-empty — `validators.py:50-64`
- §2.11 — revise — **mismatch** — `plan_revalidation_required` is never cleared; no endpoint re-points a station's plan — `routes/stations.py` (no such route), `services/scoring.py:200-201`
- §3.1 — revise — **mismatch** — `mandatory_relay_event_codes` members are uppercase **alphanumeric** (not letters only) and need not be distinct — `validators.py:31`, `routes/state_plans.py:36-39`
- §3.1 — revise — ambiguity — activate with empty `required_source_types` -> `ERR_INVALID_REQUEST` 400, checked after the `DRAFT` check — `routes/state_plans.py:78-79`
- §3.1 — revise — ambiguity — relay-rule `fips_codes` is required, members exactly five digits, may be empty, need not be distinct — `routes/relay_rules.py:34`
- §3.2 — revise — ambiguity — station registration never examines the plan's `status` — `routes/stations.py:42`
- §3.2 — revise — ambiguity — `REGISTERED` -> `READY` is the only status move; a `READY` unit with a false flag stays `READY` with `readiness_check_passed` false; a `FAILED` unit is checked without error — `routes/devices.py:89-94`
- §3.2 — revise — ambiguity — `document_kind`/`reference_label` are free non-empty strings (not the §3.9 enum) and are not persisted — `routes/stations.py:127-134`
- §3.3 — revise — ambiguity — `counts_toward_required_sources` is derived per read, not stored — `serializers.py:101-110`
- §3.3 — revise — ambiguity — `record-receipt` on a `SUSPENDED` row is accepted, keeps `SUSPENDED`, only `last_receipt_at` moves — `routes/assignments.py:117-127`
- §3.3 — revise — **mismatch** — reinstate precondition order is DECOMMISSIONED -> `ERR_DEVICE_NOT_READY` -> `ERR_SOURCE_TYPE_ALREADY_COVERED` (PRD had the last two reversed) — `routes/assignments.py:158-170`
- §3.4 — revise — ambiguity — outage filed against an already-`FAILED` unit is accepted; hops 1–2 no-op, hop 3 still fires — `services/scoring.py:164-178`
- §3.4 — revise — ambiguity — `verification_note` accepted but never stored; fail-verification does **not** clear `continuous_clock_breached` / `obligation_breached` — `routes/outages.py:135,141-145`
- §3.5 — revise — ambiguity — new alert carries all four accessibility measurement fields null — `routes/alerts.py:71-74`
- §3.5 — revise — ambiguity — suppressed alert also keeps `forward_delay_seconds_applied` 0 — `routes/alerts.py:68,77-79`
- §3.5 — revise — ambiguity — selector and the mandatory-code override use the station's plan whatever the plan's own `status` — `services/calculations.py:102,123`
- §3.6 — revise — ambiguity — wrong-state `evaluate-readiness` reports `ERR_TEST_NOT_READY` — `routes/test_events.py:104-105`
- §3.6 — revise — **mismatch** — rung 9 runs `ERR_LOG_ENTRY_SOURCE_UNKNOWN` before `ERR_DEVICE_STATION_MISMATCH`, then the rung-10 window; matching assignments count in any status — `routes/log_entries.py:59-74`
- §3.6 — revise — **mismatch** — a `RECEIPT` line refreshes **every** matching assignment, not one — `routes/log_entries.py:96-101`
- §3.7 — revise — ambiguity — receipt coverage attributes lines to source types via assignments' `source_call_sign` (any status), empty plan passes; ceiling sum is rounded and, on an amendment, still includes the not-yet-reversed prior filing — `routes/filings.py:58-72,85-88`
- §3.8 — revise — ambiguity — compliance-summary computes `missing_source_count`/`outage_breach_count`/`unfiled_test_count`/`required_source_count` live at read time while the rest are last-recompute values; no audit fields — `routes/stations.py:96-111`
- §3.9 — revise — ambiguity — `provided_document_kinds` is required but may be empty and need not be distinct — `routes/inspections.py:79-81`

## Pipeline complete — 2026-09-02T22:52:00.000Z

All nine steps satisfied for task_2444. Resume entry point was Step 2 (partial: design indices only, SCAFFOLD.yaml preserved); Steps 3, 4, 5+6 (concurrent), 7, 8 and 9 all ran in this session. Final state: 3 scaffold artifacts, 478-line PRD.md, 18-file / 221-function / 260-item test suite, 60-endpoint Flask implementation, an 8-round sweep at 260/260 in every round, plus PRD_FINALIZED.md and PRD_COMPLETED.md.
