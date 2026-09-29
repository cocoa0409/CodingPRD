# Worklog — task_2550_pulmonary_function_lab_respiratory_diagnostics

## Step 1: Create task directory — 2026-09-03T09:20:05.115Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2550_pulmonary_function_lab_respiratory_diagnostics` and its `workspace/` subdirectory. Index 2550 was pre-assigned by the invoking command (no scan of ./tasks/ performed, per instruction — concurrent pipelines on this host would collide with auto-allocation).

## Step 2: Generate scaffold (subagent) — 2026-09-03T11:05:51.824Z

Scaffold generation for task 2550 is complete and lint-clean.

## Files

| Path | Lines |
|---|---|
| `SCAFFOLD.yaml` | 3167 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2355 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 5240 |

Key placement verified: `SCAFFOLD.yaml`'s top-level keys are only §1.0–§1.7 (`scenario`, `domain_name`, `api_prefix`, `complexity_profile`, `response_envelope`, `entities`, `state_machines`, `concurrency_rules`, `calculations`, `validations`, `endpoints`, `errors`, `roles`) — neither design key appears in it; each design file has exactly one top-level key.

## SCAFFOLD.yaml counts

- 13 entities (graph topology), 48 endpoints, 54 validation rules (unique priorities 1–54), 52 errors, 10 calculations, 7 state machines (parallel shape on `TestSession`: `session_status` × `custody_status`), 5 roles (segregation of duties), 2 concurrency rules
- Profile: `compliance_audit` / `workflow_orchestration`, layers `optimistic_concurrency`, `cascading_side_effects`, `dual_variant_calculation`, `selector_policy`, `difficulty_level: expert_plus`, `consistency_model: immediate`
- `api_prefix: /pft-lab`

## Design-index instance counts

- §1.8 `scaffold_difficulty_design`: **18 instances** — all nine §0.5 rules × 2 (`dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`)
- §1.9 `scaffold_corner_design`: **77 instances** across all nine guide sections — 60 with `test_recipe`, 17 `excluded_because` stubs: entities 12, state_machines 13 (4 stubs), calculations 13 (5), validations 10 (5), endpoints 5 (1), errors 14, rbac 5, cross_cutting_complexity_layers 4 (2), consistency_model 1

## Lint

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    48
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     60
  Calls scanned (§1.8+§1.9):  1315

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Notable findings during generation

- **Error reachability sweep**: all 52 declared error ids are now triggered by at least one §1.8/§1.9 instance (0 untriggered).
- **One SCAFFOLD.yaml defect found and fixed**: `ERR_SEGREGATION_OF_DUTIES` (validation priority 42) was declared only on `POST /pft-lab/interpretation-reports/{report_id}/sign`, where priority 3's identity check makes it unreachable (an InterpretingPhysician's `Staff.id` can never equal a `TestSession.technologist_staff_id`, which is a TECHNOLOGIST row). Priority 42's `check` was rewritten to cover both clauses and `applies_to` extended to `POST /pft-lab/devices/{device_id}/return-to-service`, where the `quarantine_trigger_staff_id` clause the Device state machine already declared makes it genuinely reachable.
- **Priority-masking trap encoded into a corner test**: `ERR_MAX_REJECTION_ROUNDS_EXCEEDED` (p29) is masked by `ERR_DEVICE_NOT_AVAILABLE` (p28), because the second rejection's conditional cascade soils the device. The corner instance asserts the masked 409 first, then restores the device (clock advance, fresh filter, disinfection) to reach p29 — so the downstream test suite cannot accidentally "pass" on the wrong error.
- No sibling task directory was read, listed, globbed, or grepped at any point; the scaffold derives only from the scenario text and the skill specification.

## Step 3: Copy shared files — 2026-09-03T11:06:09.177Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD (subagent) — 2026-09-03T11:26:00.000Z

PRD generation is complete.

## Output
`workspace/PRD.md` — **501 lines** (111678 bytes), last section heading **`## 5. Error Code Catalogue`**, ending on the final error-table row (`| ERR_RESCUE_DOSES_INSUFFICIENT | 409 |`) with a trailing newline and no audit footer.

Structure: §1 Introduction (3 paragraphs) → §2 with 12 domain-derived subsections (2.1 RBAC, 2.2 verbatim fixed response block, 2.3 Pagination, 2.4 Logical clock, 2.5 Common/append-only properties, 2.6 Numeric precision & chained rounding, 2.7 Version guarding, 2.8 Cascade semantics, 2.9 Path resolution + the 54-rung validation ladder, 2.10 Segregation of duties, 2.11 Rescue-dose ledger, 2.12 Selector policy) → §3 with 9 workflow subsections → §4 endpoint table → §5 error table.

## Hard Contract results

**Contract 1 — Field-Name Coverage: PASS (181/181).** Extracted every `entities[].fields[].name`, every endpoint `input` identifier and every path param from SCAFFOLD.yaml; all 181 appear verbatim in backticks. Two passes run; the 7 path params (`event_id`, `hold_id`, `lot_id`, `maneuver_id`, `report_id`, `run_id`, `staff_id`) appear in the `` `{name}` `` brace form in §2.9 and §4 (verified individually, 1–2 occurrences each).

**Contract 2 — Rule Coverage: PASS.** All 54 validation priorities appear as numbered rungs 1–54 in §2.9 with matching `error_id`, HTTP status and `applies_to` scope (programmatic rung-by-rung diff: 0 mismatches). Both `concurrency_rules` are stated in §2.7 with write operation, required non-optional body field, 412 code and rationale. All 52 error ids present. All 38 state-machine state values backticked. All calculation constant *values* embedded in prose (only `BEV_FRAC` 0.05 is expressed as "5 percent", which is the same rule). Sibling-branch symmetry covered in both directions for PASS/WARN/FAIL, `ABSOLUTE_BASELINE`/`ROLLING_MEAN`, `PCT_BASELINE_2005`/`PCT_PREDICTED_2021`, `STOPPED_PC20`/`COMPLETED_NEGATIVE`, abort-at-0-steps vs abort-after-steps, and the device (half-open, +20 min, touching OK) vs technologist (closed, no extension, touching counts) window conventions.

**Contract 3 — §3 Path Purity: PASS.** 1108 backticked tokens across §3, 0 violations: no `/`-leading token, no bare HTTP method, no method+path combination, no plain-text `/pft-lab` mention. Endpoints in §3 are referenced only by state-transition framing, role + action verb, or capability description.

## Corrections made against the scaffold during self-review
- `rejection_reasons` value is `COUGH_ARTIFACT`, not `COUGH_FIRST_SECOND`.
- The `quality_grade` ladder was rewritten to the scaffold's actual asymmetric form (A: >=3 with both deltas <=150; B: >=3 with FEV1 delta <=200 and no FVC test; C: count **exactly 2** with FEV1 delta <=150; D: >=1; else F).
- `id_document_type` values are `PHOTO_ID`, `PASSPORT`, `EMPLOYEE_BADGE`, and both conditional custody fields are forbidden outside their own event types.
- §2.1 read-surface claim corrected against `endpoints[].roles` (`OrderingPhysician` also excluded from the staff and rescue-lot reads; rescue-lot read limited to three roles).
- Added: `hold_release_at` becomes null on order cancellation; `technologist_comment` is optional; PATCH replaces supplied fields only; §2.8 hop 2 now includes the `open_report_count` decrement, the lot settlement and the "device stays QUARANTINED rather than SOILED" exception.

Two scaffold ambiguities were resolved without inventing rules: `last_step_drop_pct` (field description says "prior step's drop_pct", formula uses `max_fev1_drop_pct`) is phrased as "the drop percent as it stood before this step — the largest fall observed on earlier steps, 0 before the first", which satisfies both readings; and the finalize-quality precondition "no ChallengeRun is ARMED or IN_PROGRESS", which carries no `error_id` in the scaffold, is described as a session-state conflict reporting the existing `ERR_SESSION_STATE_INVALID` (409).

The two withheld design files were never opened, grepped or referenced.

**Orchestrator truncation check (per invocation instruction):** `tail -25` confirms PRD.md terminates on the complete final row of the §5 error table with all 52 error ids present — a real section boundary, not mid-sentence. No regeneration needed.

## Step 6: Generate implementation (subagent) — 2026-09-03T11:56:00.000Z

## Implementation complete

All files in `workspace/implementation/`:

| File | Lines |
|---|---|
| `start.sh` (executable, guarded pip install, `exec python3 app.py`) | 10 |
| `requirements.txt` (`Flask>=2.0.0`) | 1 |
| `app.py` — blueprint registration under `/pft-lab`, error handlers, `0.0.0.0:$PORT` (default 10000) | 64 |
| `auth.py` — roles, `Actor`, ladder rungs 1-3 | 68 |
| `store.py` — 13 in-memory dicts, logical clock, id/version/seq stamping | 188 |
| `errors.py` — full error catalogue + HTTP status map | 138 |
| `responses.py` — envelope + offset pagination | 96 |
| `validation.py` — typed field validators | 162 |
| `calc.py` — every constant + all pure calculations | 353 |
| `services.py` — lookups, serialisers, cascades, selectors | 468 |
| `r_devices.py` — devices, quality log, return-to-service | 377 |
| `r_registry.py` — staff/patients/equations/lots + `_clock/set_current_utc` | 227 |
| `r_orders.py` — orders + medication holds | 296 |
| `r_sessions.py` — sessions, maneuvers, custody chain | 498 |
| `r_reports.py` — assign/sign/amend | 205 |
| `r_challenge.py` — arm/step/abort | 163 |
| **Total** | **3314** |

Route count is exactly **48**, matching the PRD endpoint table one-for-one. Storage is in-memory dicts only; nothing is seeded, imported, or persisted at boot (verified: the only `seed` match in the tree is a comment in `store.py` stating the store is empty on every boot). `__pycache__` was removed so the tree is source-only.

## Smoke test results (PID-scoped, no pattern kills)

Ran a scripted 40-call happy-path + negative-path suite on `PORT=18550`, then `kill 3866553` (confirmed stopped); a second cold boot on `18551` confirmed fresh-process startup in <3s. Every assertion passed. Notable verified values:

- Calibration: `btps_factor 1.0854`, `corrected_volume_l 3.0`, `error_pct 0.0`, `PASS`; device `NEW -> AVAILABLE`
- Biologic control: `deviation_pct 2.86`, variant `ABSOLUTE_BASELINE`, `PASS`
- Predicted/LLN: `predicted_fev1_l 3.525`, `predicted_fvc_l 5.42`, `lln_fev1_l 2.772`, equation `GLI_2012`
- Quality: grade `A`, `best_fev1_l 3.15`, `best_fvc_l 4.25`, repeatability deltas `30`/`30`, `fev1_pct_predicted 89.4`, `fvc_pct_predicted 78.4`, ratio `0.741`
- Bronchodilator: `14.3%` / `450 mL`, variant `PCT_BASELINE_2005`, positive
- Report: correct interpreter selected, `queue_load_pct 50.0`, tier `NORMAL`, `sla_minutes 1440`, `due_at 2026-08-02T00:00:00.000Z`; signing yielded `RESTRICTION`/`MILD`, `template_version PFT-2026.1`
- Cascades on sign: session -> `REPORTED`, order -> `COMPLETED`, patient `completed_order_count 1`; device -> `SOILED` after session close
- Error paths confirmed: 401 (missing header / unknown role), 403 (role not permitted, staff identity mismatch, interpreter ownership), 404, 405, 409 (duplicate device_code, filter serial reuse, order state), 412 (stale `expected_session_version`), 422 (self biologic control, ambient out of range, wrong event field set, hard context gate, coaching-required), 400 (`limit=0`), and the soft clinical gate returning **HTTP 200 with `INDICATION_REJECTED` / `MODALITY_NOT_APPROVED_FOR_INDICATION`**

Note for the caller: this is the implementation side only. The concurrently running Step 5 test-suite agent was untouched; I read nothing under `test_suite/`, `test_helpers/`, or either `SCAFFOLD_*_DESIGN.yaml`.

## Step 5: Generate unit tests (subagent) — 2026-09-03T12:35:00.000Z

Generation is complete and all audits are green.

## Final fixes this pass
The two citations flagged as non-verbatim were truncated mid-sentence with an appended period. Both were extended to the PRD's real sentence end (not shortened), so C3 (full-sentence quotes) still holds:
- `test_suite/test_02_combinatorial_formulas.py` — the §3.2 failing-calibration quote now runs through "…and drives the device to `QUARANTINED`, stamping `quarantined_at` … with the acting technologist."
- `test_suite/test_16_role_permissions.py` — the §2.1 technologist-identity quote now runs through the ownership-check clause ("…compare that foreign-key field to `X-User-ID`.").

## Audit results
- Verbatim citations: 145 docstring quotes checked, **0 not found verbatim** in `workspace/PRD.md`.
- Design tags: **96 tagged tests, 0 problems** — exactly one `Design:` line per test, always the last docstring line, every tag resolving to a real design instance name.
- Queue A: 36 tests over **18/18 difficulty instances** (2 each, none short).
- Queue B: 60 tests over **60/60 non-stub corner instances** (1 each).
- `compileall` clean; `pytest --collect-only` collects **96 tests** with no import or collection errors.
- No `__pycache__`/`.pytest_cache` left behind in either output directory.

## Output inventory (line counts)

`test_helpers/` — 2372 lines total
| file | lines |
|---|---|
| `__init__.py` | 46 |
| `api_client.py` | 481 |
| `api_errors.py` | 136 |
| `assertions.py` | 295 |
| `constants.py` | 163 |
| `factories.py` | 466 |
| `fixtures.py` | 447 |
| `test_users.py` | 62 |
| `types.py` | 276 |

`test_suite/` — 5761 lines total
| file | lines | tests |
|---|---|---|
| `conftest.py` | 41 | — |
| `test_01_dual_variant_calculations.py` | 250 | 4 |
| `test_02_combinatorial_formulas.py` | 192 | 4 |
| `test_03_workflow_state_machines.py` | 195 | 4 |
| `test_04_transitive_cascades.py` | 200 | 4 |
| `test_05_validation_priority_masking.py` | 239 | 4 |
| `test_06_boundary_precision.py` | 200 | 4 |
| `test_07_cross_entity_state_dependencies.py` | 204 | 4 |
| `test_08_resource_window_overlap.py` | 189 | 4 |
| `test_09_compensating_invariants.py` | 236 | 4 |
| `test_10_entity_records.py` | 457 | 10 |
| `test_11_state_transitions.py` | 453 | 10 |
| `test_12_calculations.py` | 445 | 9 |
| `test_13_validation_gates.py` | 455 | 10 |
| `test_14_endpoint_behaviour.py` | 291 | 4 |
| `test_15_error_catalogue.py` | 1015 | 14 |
| `test_16_role_permissions.py` | 371 | 5 |
| `test_17_concurrency_guards.py` | 201 | 2 |
| `test_18_immediate_consistency.py` | 127 | 1 |

## Known design/PRD divergences (asserted the PRD, documented inline)
Four design instances asserted outcomes the PRD contradicts or does not uniquely derive; each test asserts the PRD value with the governing quote and an explanatory comment: coaching-round grade D (needed a non-coachable second-round defect to keep `acceptable_maneuver_count` at 1), challenge step anchors (`last_step_dose_units` 175.000 / `last_step_drop_pct` 1.67 are the pre-step values per §3.7), the substituted challenge agent (HISTAMINE is not an admitted agent — used MANNITOL), and the maneuver-append roll-up (§2.5/§3.6 make that response a `Maneuver` row, so the roll-up is asserted on the immediately following session read plus a double-read `assert_unchanged`). No instance was weakened, skipped-marked, or stubbed.

No server was started, so no process was killed, and nothing under `workspace/implementation/` was read or written.

## Step 7: Run tests and iterate (long-lived subagent) — 2026-09-03T13:27:36.619Z

All clean. Everything intact, all 8 result files present.

## Summary

**Iterations run:** 2 (sweep 1 -> 11 failures deterministic across all 8 rounds; sweep 2 -> fully green).

**Final sweep result:** all 8 `results.$i.json` files exist under `workspace/implementation/`, and each shows `passed == total == 96` with `failed=0, errors=0, skipped=0` (rounds 1-8, ~176 s each). No flaky test appeared in either sweep — every failure in sweep 1 failed in 8/8 rounds, so nothing was load-induced.

**Tests deleted:** none. Three assertions were removed under STEP 1c partial-coverage handling (test kept, uncovered assertion dropped):
- `test_09_compensating_invariants.py::TestOpenReportTotalConservation::test_a_superseding_assignment_moves_the_load_and_keeps_the_total_at_one` — dropped the `queue_load_pct`/`load_tier`/`sla_minutes`/`due_at` value assertions on the *superseding* report. **Ordering silence:** PRD §3.9 makes the five deadline steps normative ("First the report is inserted … Second, the laboratory-wide open workload is counted … including the row just inserted") but never says whether the prior report on that study has already moved to `REASSIGNED` when step two counts. Open count is 1 or 2 on equally faithful readings (50.00 %/NORMAL/1440 vs 100.00 %/SURGE/2880), so the figure is not uniquely derivable. All state/conservation assertions (REASSIGNED, `superseded_by_report_id`, per-interpreter counts 0/1, total 1, `assigned_at`) were kept.
- `…::test_an_amendment_reopens_the_seat_but_never_the_deadline` — dropped `study["turnaround_minutes"] == <re-signed value>`. **Branch-asymmetric side effect:** PRD §3.9 binds the copy to the transition ("the study moves from `ACCEPTED` to `REPORTED` and copies `turnaround_minutes` onto its own field"); an already-`REPORTED` study makes no such move, so refreshing the copy on a re-signature is not derivable. Replaced with `session_status == "REPORTED"`.

**Fixes applied to `test_helpers/`:**
- `fixtures.py` — `record_challenge_step()`: `_created(...)` (201) -> `_ok(...)` (200). PRD §4: "recording a challenge step answers 200 with the updated `ChallengeRun` rather than 201". This single fixture bug caused 4 of the 11 failures across `test_04`, `test_09` and `test_15`.

**Fixes applied to `test_suite/` (test bugs, all made more PRD-faithful):**
- `test_05_validation_priority_masking.py` (2 sites) and `test_08_resource_window_overlap.py` (1 site) — `body["error"]["error_id"]` -> `body["error_id"]`. `validate_error` returns PRD §2.2's `data` object directly, so the extra `["error"]` hop raised `KeyError: 'error'`.
- `test_02_combinatorial_formulas.py::test_a_failing_calibration_quarantines_without_refreshing_currency` — raw string equality on `last_calibration_at` -> `assert_instant(...)`. The literal lacked the three fractional digits PRD §2.5 mandates for every server-minted timestamp.
- `test_16_role_permissions.py::_a_quarantined_device_and_its_accuser` — the fixture created no filter replacement or high-level disinfection, so return-to-service correctly stopped at PRD §2.9 **rung 36** (`ERR_INFECTION_CONTROL_INCOMPLETE`, explicitly "on both study scheduling and return-to-service") and never reached the **rung 42** segregation check the test targets. Added the hygiene pair, performed by the accusing technologist (PRD §3.3's "two clearing measurements" are the calibration and biologic control, not the hygiene events).
- `test_09_compensating_invariants.py::test_an_amendment_reopens_the_seat_but_never_the_deadline` — re-signature clock moved from `2026-08-04T10:30Z` to `2026-08-10T10:00Z`, i.e. PRD §3.9's own wording "A report amended and re-signed a week late is therefore breached". This keeps `sla_breached is True` at full strength under either deadline reading, and the literal `due_at` expectation became the PRD's actual rule — `assert_instant(resigned["due_at"], second["due_at"])`, that `due_at` keeps its original value.

**Fixes applied to `implementation/`:** none. Every sweep-1 failure traced to the test artifact or to an assertion the PRD does not uniquely determine; no PRD-required check was removed, weakened, or added, and storage remains in-memory only.

**Orchestrator independent verification (per memory note on Step 7 sweep artifacts):** re-read all 8 `results.$i.json` myself with a fresh parser — files dated 13:17, ~32 KB each, every round reporting `passed=96 total=96 failed=0 errors=0 skipped=0`. Confirmed, not taken on the subagent's word.

**Step 8 decision:** Step 7 applied 0 `implementation/` fixes but did make 1 `test_helpers/` fix, 5 `test_suite/` fixes and 3 partial-coverage assertion removals across 2 iterations — so this is NOT the zero-iteration skip case. Step 8 runs, with the assertion removals (the two PRD-silence findings on §3.9 deadline-step ordering and the amendment `turnaround_minutes` copy) as its focus list.

## Step 8: Finalize PRD (subagent) — 2026-09-03T13:33:00.000Z

Done. Four edits, all traced to `<step_7_diff>` items.

## Line counts
- `PRD.md`: 501 lines / 111,678 B
- `PRD_FINALIZED.md`: 503 lines / 113,841 B
- Delta: +2 lines (+0.40 %), +2,163 B (+1.94 %)

## Changes
- **§2.5** — insert — new paragraph after the four system-property bullets: every instant-valued field (not just `created_at`/`updated_at`) is rendered ISO 8601 UTC with three fractional digits and trailing `Z`, including client-supplied instants, which are converted to UTC and re-rendered; calendar-date fields keep `YYYY-MM-DD`. Traces to the `test_02` `last_calibration_at` string-equality fix. — `implementation/store.py:47-57` (`iso`), `r_devices.py:194`
- **§3.3** — insert — sentence appended to the between-patient hygiene paragraph: the same pair test is what §2.9 rung 36 evaluates on study scheduling and return-to-service, and with a null `last_session_end_at` the `COMPLETE` filter replacement + `COMPLETE` high-level disinfection must still exist (any time qualifies). Traces to the `test_16::_a_quarantined_device_and_its_accuser` fixture fix (never-used device still stopped at rung 36). — `implementation/services.py:168-181`, `r_devices.py:348`, `r_sessions.py:115`
- **§3.9 (deadline paragraph)** — insert — sentence after "Reports that are `SIGNED` or `REASSIGNED` are excluded": on a superseding assignment the earlier report is still `ASSIGNED` when the open count is taken, because the demotion runs only after all five deadline steps. Traces to the dropped `queue_load_pct`/`load_tier`/`sla_minutes`/`due_at` assertions in `test_09::…superseding_assignment…`. — `implementation/r_reports.py:56-81`
- **§3.9 (amendment paragraph)** — insert — clause after the re-signature rule: re-signing still decrements `open_report_count`, but the rest of the signing cascade does not re-run — the study's `turnaround_minutes` keeps the first-signature value, study `version`/`updated_at` unchanged, order stays `COMPLETED`, `completed_order_count` not raised again. Traces to the dropped `study["turnaround_minutes"]` assertion in `test_09::…amendment_reopens_the_seat…`. — `implementation/r_reports.py:175-186`

No edit for: the `record_challenge_step` 201->200 fixture bug (§4 already explicit), the `body["error"]["error_id"]` test bug (§2.2 already explicit), the `test_09` re-signature clock/`due_at` change (§3.9 already pins `assigned_at`/`due_at` immutability), and the "hygiene events are not clearing measurements" reading (§3.3's fourth condition already scopes segregation to the calibration and biologic control).

## Per-edit pre-edit search log

**Edit 1 (§2.5 timestamp rendering)**
- (a) Subject: rendering format of every stored/returned instant-valued field.
- (b) Enumerated: `grep '_at"] =\|_at": '` across all of `implementation/` -> `r_reports.py:38,68,159`; `r_devices.py:177,194`; `r_orders.py:219,220,283`; `r_sessions.py:151,152,284,450`; `services.py:200,215,304`; plus `store.py:47` (`iso`, 3-digit formatter, string pass-through), `store.py:118` (`iso_date`), `validation.py:155` (`v_datetime` -> parsed datetime, so `r_sessions.py:151-152` normalizes client input), `r_registry.py:227` (`current_utc`), date-only fields (`last_biologic_control_date`, `expires_on`, `birth_date`, `baseline_established_on`).
- (c) Adjustment: added the "converted to UTC and re-rendered" clause after confirming client-supplied `scheduled_start_at`/`scheduled_end_at` are normalized rather than echoed; added the closing sentence exempting calendar-date fields so the rule cannot be read onto `iso_date` fields.

**Edit 2 (§3.3 infection-control gate)**
- (a) Subject: the `infection_control_satisfied` pair test and every gate that consumes it.
- (b) Enumerated: `services.py:168-181` (boundary defaults to `last_session_end_at`; null boundary => pair must merely exist), `services.py:184-192` (`maybe_return_soiled_device`), `r_devices.py:348` (return-to-service, evaluated after rung 28 and before the clearance-evidence and segregation checks), `r_sessions.py:115-117` (scheduling, between rung 35 and rung 37), `r_devices.py:287-306` (which events set `outcome COMPLETE` and trigger self-clearing), `services.py:213-220` (`close_device_after_session` sets `last_session_end_at`), and the unused `boundary_iso` parameter (no other callers).
- (c) Adjustment: phrased as "always reads whatever `last_session_end_at` the device is carrying" instead of naming only return-to-service, so the sentence also covers the scheduling gate and the SOILED self-clearing path; kept the preceding "hygiene performed before the last patient never counts" sentence verbatim.

**Edit 3 (§3.9 open-count timing)**
- (a) Subject: when a superseded report leaves the open set, and what the lab-wide open count sees.
- (b) Enumerated: `r_reports.py:33-84` (select -> insert -> increment winner -> count/tier/SLA/due -> demote prior -> decrement loser), `services.py:466-468` (`open_report_total`, its only caller being `r_reports.py:60`), `services.py:455-463` (`roster_capacity`, staff-based, unaffected), `services.py:245-250` (the other `REASSIGNED` producer: the abort/quarantine cascade), `services.py:258-264` (`adjust_open_reports`, all five callsites), `services.py:430-452` (`select_interpreter`; `pending_release_staff_ids` is never passed by any caller).
- (c) Adjustment: scoped the sentence to "this assignment supersedes an earlier report on the same study" so it makes no claim about the abort-cascade `REASSIGNED` path, and referred to "the demotion described below" rather than restating the demotion, to avoid a second, possibly divergent description.

**Edit 4 (§3.9 re-signature cascade)**
- (a) Subject: the signing cascade onto study / order / patient and the study's `turnaround_minutes` copy.
- (b) Enumerated: `r_reports.py:154-187` (whole sign path; `adjust_open_reports(-1)` at :173 is unconditional, the study/order/patient block at :175-186 is guarded by `session_status == "ACCEPTED"` with a nested `order["status"] == "IN_TESTING"` guard, and `touch(session)` lives inside that guard), `grep turnaround_minutes` -> only writers are `r_reports.py:160,177` and the `None` initialisers `r_reports.py:44`, `r_sessions.py:178`; `grep IN_TESTING` -> `r_sessions.py:183`, `services.py:232`, `r_reports.py:179`; `grep completed_order_count` -> `r_registry.py:113` init, `r_reports.py:184` increment; `r_reports.py:190-205` (amend re-increments `open_report_count`).
- (c) Adjustment: my first draft opened with "re-signing changes nothing outside the report itself", which the unconditional `adjust_open_reports(-1)` at `r_reports.py:173` contradicts; rewrote to state the decrement explicitly and then list only the parts that do not re-run, and phrased the whole clause as a property of the re-signature path so it makes no universal claim about the `ACCEPTED -> REPORTED` case (where the order sub-cascade is additionally `IN_TESTING`-guarded).

**Orchestrator verification:** `PRD_FINALIZED.md` is not byte-identical to `PRD.md` (503 vs 501 lines, 113841 vs 111678 B) and still terminates on the complete final row of the §5 error table. The patch is real.

**Step 9 plan:** the implementation is 3303 lines across 14 modules, and a single-pass full scan has previously no-opped on artifacts this size (producing a `PRD_COMPLETED.md` byte-identical to its source). Step 9 is therefore run as **three sequential file-partitioned passes**, each editing the same `PRD_COMPLETED.md` in place: (1) foundation + registry + devices, (2) orders + sessions, (3) reports + challenge + calc/services residue. The orchestrator performs the `cp PRD_FINALIZED.md PRD_COMPLETED.md` itself before pass 1 and verifies a non-empty diff after each pass.

## Step 9: Complete PRD — three sequential file-partitioned passes (subagents) — 2026-09-03T14:04:00.000Z

Run as three sequential passes over one shared `PRD_COMPLETED.md` (orchestrator did the `cp PRD_FINALIZED.md PRD_COMPLETED.md` itself; each pass edited in place with Edit only). Totals: **38 ambiguity-pins, 7 mismatch-revisions**; 501 -> 503 -> 507 lines, 111,678 -> 113,841 -> 126,481 bytes.

### Pass 1 — app / auth / store / errors / responses / validation / r_registry / r_devices (16 pins, 4 mismatches)

- §2.1 RBAC — insert — ambiguity — header values are trimmed and an empty/whitespace-only header counts as absent (401) — `auth.py:45-52`
- §2.2 Error format — revise — mismatch — envelope is not 4xx-only; the same shape carries the HTTP 500 fault response — `app.py:51-54`
- §2.2 meta bullet — insert — ambiguity — reduced error `meta` holds on 4xx and 5xx alike, unhandled fault => `ERR_INTERNAL` — `app.py:51-54`, `responses.py:55-61`
- §2.3 Pagination — insert — ambiguity — omitted/empty => default; non-integer, `limit` outside 1-100, negative `offset` => `ERR_INVALID_REQUEST` (not clamped); over-range offset => empty array — `responses.py:64-86`
- §2.3 Pagination — insert — ambiguity — equal `created_at` broken by insertion order, `id` never consulted — `store.py:182-184`, `responses.py:92-93`
- §2.3 Pagination — insert — ambiguity — `total_count` = filtered count pre-window; exact `has_more` formula — `responses.py:41-52,94-96`
- §2.4 Clock — insert — ambiguity — clock is *set*, backwards targets accepted, no monotonicity — `r_registry.py:213-218`
- §2.4 Clock — insert — ambiguity — nothing ever moves a lot out of `EXPIRED`, incl. a backwards clock move — `r_registry.py:220-226`
- §2.9 rung 3 — insert — ambiguity — staff resolution keys off the *acting* role, so LabManager/ComplianceAuditor are never resolved against `Staff` — `auth.py:59-67`
- §2.9 rung 15 — insert — ambiguity — added the missing >0 / >=0 numeric bounds (`measured_fev1_l`, `measured_fvc_l`, `baseline_fev1_l`, `baseline_fvc_l`, `applicable_age_*`) plus three uniform conventions: no blank strings anywhere, optional `null` = absent (takes default), undeclared body members ignored — `validation.py:27-47,95-101`, `r_registry.py:53-56`, `r_devices.py:101-106`
- §2.9 rung 16 — insert — ambiguity — only the eight conditional fields participate (`note` always allowed) and `null` counts as absent on both halves of the test — `r_devices.py:121-134`
- §3.1 Staff — insert — ambiguity — baseline trio stays optional for non-controls and is stored if supplied — `r_registry.py:51-58`
- §3.1 Reference equations — revise — mismatch — `status` is a client-settable optional input (`ACTIVE`|`SUPERSEDED`, default `ACTIVE`); only an `ACTIVE` publication supersedes, and it bumps the earlier set's version — `r_registry.py:146-172`
- §3.2 Device registration — insert — ambiguity — `consecutive_biologic_failures` 0 and all other dossier fields null at creation — `r_devices.py:51-65`
- §3.2 Quality log — insert — ambiguity — every record returns the full field set with inapplicable members present-and-null; `ambient_temp_c` echoed as an integer — `r_devices.py:155-180`
- §3.3 Return to service — insert — ambiguity — `clearance_note` is required, non-empty, and not persisted — `r_devices.py:343-344`
- §3.3 Return to service — revise — mismatch — only the first three conditions yield `ERR_QUARANTINE_CLEARANCE_INCOMPLETE` (422); it sits between rung 36 and rung 42 — `r_devices.py:345-371`
- §3.3 Infection control — insert — ambiguity — filter replacement always bumps device `version`; disinfection bumps it only when it clears `SOILED` — `r_devices.py:301-306`
- §4 intro — insert — ambiguity — trailing slash tolerated; unknown path => `ERR_NOT_FOUND` 404; bad method => `ERR_METHOD_NOT_ALLOWED` 405; neither needs auth headers — `app.py:15,36-49`
- §4 intro — insert — ambiguity — list filters are exact string equality, never enum-validated; unrecognised/empty value matches nothing — `r_devices.py:77-93,317-336` (verified identical in `r_orders`, `r_sessions`, `r_challenge`, `r_reports`)
- §5 catalogue — insert — mismatch — added `ERR_QUARANTINE_CLEARANCE_INCOMPLETE` 422, `ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500 — `errors.py:68-71`

Verified-already-pinned (pass 1): `/pft-lab` prefix and blueprint mounting; 401-before-403-before-404 ladder; the five role names and per-endpoint role lists (staff/lot/quality-event reads correctly exclude `OrderingPhysician`); UUID ids with no prefix; `version` 1 / +1 per mutation and event records carrying only `id`+`created_at`; three-fractional-digit ISO rendering and offset->UTC conversion; BTPS chain (4dp factor -> 3dp corrected -> 2dp error, strict >3.00 fail); NEW->AVAILABLE only on a pass; `last_calibration_at` vs `last_calibration_error_pct` asymmetry; biologic 5.00/10.00 inclusive bands, 180-day baseline rule, 3-record PASS/WARN rolling window with fallback, PASS/WARN/FAIL device effects and quarantine cascade; leak-check `COMPLETE` with no device effect; dwell >=20 min; `ERR_FILTER_SERIAL_REUSED`; `ERR_SELF_BIOLOGIC_CONTROL`; infection-control pair vs `last_session_end_at` (incl. null boundary); return-to-service evidence strictly after `quarantined_at`, `WARN` not qualifying, failure-streak zero, trigger-technologist exclusion, and the cleared quarantine fields; registry uniqueness codes; lot receipt defaults; clock epoch `2026-08-01T00:00:00Z`; `age_years` derivation; 201-vs-200 status map.

### Pass 2 — r_orders / r_sessions (12 pins, 2 mismatches; all in-paragraph, line count unchanged)

- §2.9 (body identifier resolution) — insert — ambiguity — a body FK that is present but not a string misses the lookup and reports that identifier's own 404 rather than `ERR_INVALID_REQUEST`; only absent/null falls to rung 15 — `services.py:13-19` (via `r_orders.py:40`, `r_sessions.py:84-90`)
- §3.4 (drafting) — revise — mismatch — `current_medication_classes` is the single array that may be supplied as `[]`, treated as omitted, against rung 15's universal non-empty-array claim — `r_orders.py:50` / `validation.py:125`
- §3.4 (revision) — insert — ambiguity — a revision supplying none of the four fields is valid, still applies the `DRAFT`/`rejection_reason` reset and still bumps `version`; `test_context` and `current_medication_classes` are not revisable — `r_orders.py:102-126`
- §3.4 (ownership) — revise — mismatch — PRD said "anyone else … is refused"; impl exempts `LabManager` on cancel entirely, ownership applies only to an acting `OrderingPhysician`, refusal is `ERR_ROLE_NOT_PERMITTED` 403 evaluated after `{order_id}` resolves and before body validation — `r_orders.py:21-29,169-171`
- §3.4 (hold issuance) — insert — ambiguity — a `medication_class` outside `current_medication_classes` is `ERR_INVALID_REQUEST` 400 at rung 15, pre-empting the version guard and state gate — `r_orders.py:203-205`
- §3.4 (hold issuance) — insert — ambiguity — every successful issuance re-stamps the order (`version` +1) even from `MED_HOLD_ISSUED` — `r_orders.py:232-234`
- §3.4 (attestation) — insert — ambiguity — the order is re-stamped only when the attestation actually moved its `status` or `hold_release_at`; otherwise its `version`/`updated_at` are untouched — `r_orders.py:288-295`
- §3.4 (cancellation) — insert — ambiguity — `cancellation_reason` is a required, non-empty string — `r_orders.py:173`
- §3.5 (scheduling defaults) — insert — ambiguity — `acceptable_maneuver_count` starts at 0 — `r_sessions.py:165`
- §3.6 (maneuver inputs) — insert — ambiguity — `pef_l_s` and `back_extrapolated_volume_ml` are required and carry no range constraint of their own — `r_sessions.py:235-236`
- §3.6 (maneuver inputs) — insert — ambiguity — `phase` is never cross-checked against the order or an armed run (`POST_BD` without a bronchodilator request, challenge phases with no run, both accepted) — `r_sessions.py:228`
- §3.6 (append gates) — insert — ambiguity — the technologist-ownership refusal is `ERR_ROLE_NOT_PERMITTED` 403, tested right after `{session_id}` resolves and ahead of body shape and every state gate — `r_sessions.py:223-226`
- §3.6 (finalization) — insert — ambiguity — finalization is open to any `Technologist` with no credential/competency/device gate, and `technologist_comment` is overwritten on every finalization (returning to null when omitted on a later round) — `r_sessions.py:340-353`
- §3.8 (custody applicability) — insert — ambiguity — custody events are accepted for any `session_status` other than `REPORTED`/`ABORTED` (so `ACCEPTED` and `REJECTED` still accept them), and the rung-25 session-state check pre-empts `ERR_CUSTODY_NOT_APPLICABLE` — `r_sessions.py:427-432`
- §3.8 (custody roles) — insert — ambiguity — the split is symmetric (a `ComplianceAuditor` submitting the three sequencing types is also 403) and is decided from the submitted `event_type` before `{session_id}` resolution and body validation; a non-declared `event_type` bypasses the split and falls to rung 15 — `r_sessions.py:383-402`

Verified-already-pinned (pass 2): order state machine and rung 23 mapping; soft-rejection 200 + `rejection_reason` precedence; empty vs non-empty medication list branch to `READY`/`SUBMITTED`; hold hour table, `release_at`, supersession of `PENDING`/`VIOLATED` same-class holds, `hold_release_at` = max over `PENDING`+`ATTESTED`; `WITHHELD`->`ATTESTED`/`TAKEN`->`VIOLATED` and the `READY`-without-compliance trap; cancellation cascade (holds, live studies oldest-first, no `abort_count` bump); all list filters and read-role sets (including `FLOOR_READ_ROLES` excluding `OrderingPhysician`); the full scheduling gate order 23->28->32->33->34->35->36->37->39->40->50->51->53; both interval conventions and the 20-minute allowance applied to both windows; equation selector keys and predicted/LLN chained rounding; `bev_limit_ml`, acceptability trichotomy, `rejection_reasons` fixed order; two-pool best/repeatability logic and tie-breaks; grade ladder asymmetries; derived percentages; `IN_PROGRESS` transition and coaching-round bound; accept/reject device soiling rules; bronchodilator variants; custody sequence, `WITNESS_SIGNED` non-advancing, conditional field rules, `version` bump on every custody event.

### Pass 3 — r_reports / r_challenge + final calc.py & services.py sweep (10 pins, 1 mismatch; all in-paragraph)

- §2.9 rung 15 — insert — ambiguity — added `post_step_fev1_l` to the "greater than 0" numeric-range list — `r_challenge.py:108`
- §3.7 ¶1 — insert — ambiguity — arming, stepping and aborting are open to any `Technologist`, not only the study's `technologist_staff_id`, and none of the three writes a study field, so the study's `version` moves only via the dosed-abort cascade — `r_challenge.py:22,104,146`
- §3.7 ¶2 — revise — **mismatch** — the gate order was stated as session-state -> challenge-not-requested -> contraindicated; impl checks the airflow contraindication *before* the ordered-agent match. Reordered the prose and added the rung 31/43 cross-reference (§2.9's ladder already had it right, so the section prose contradicted it) — `r_challenge.py:32-43`
- §3.7 ¶2 — insert — ambiguity — a null `fev1_pct_predicted` also reports `ERR_CHALLENGE_CONTRAINDICATED` — `r_challenge.py:36`
- §3.7 final ¶ — insert — ambiguity — runs terminated by a session-abort cascade leave their own `abort_reason` null (only `stop_reason` is written) — `services.py:240-242`
- §3.9 pool ¶ — insert — ambiguity — the filter and the ranking read `open_report_count` as it stands on arrival, ahead of the supersession release, so a single-interpreter roster at capacity gets `ERR_NO_ELIGIBLE_INTERPRETER` on a second assignment (the `pending_release_staff_ids` parameter is never passed) — `services.py:430-452`, `r_reports.py:33`
- §3.9 assignment ¶ — insert — ambiguity — a report demoted to `REASSIGNED` by cascade leaves `superseded_by_report_id` null, unlike a supersession by fresh assignment — `services.py:245-250` vs `r_reports.py:78-79`
- §3.9 assignment ¶ — insert — ambiguity — assignment re-stamps the study (`version` +1, `updated_at` refreshed) even though no study field moves — `r_reports.py:83`
- §3.9 signing ¶ — insert — ambiguity — the named-physician test runs once `{report_id}` resolves and before the body is examined, on amend as on sign — `r_reports.py:126-127, 194-195`
- §3.9 signing ¶ — insert — ambiguity — `clinical_comment` is required and non-empty on every signature including a re-signature — `r_reports.py:128`
- §3.9 timing ¶ — insert — ambiguity — the order advance is conditional on the order still being `IN_TESTING`; a cancelled order is left alone and `completed_order_count` is not raised — `r_reports.py:179-186`
- §3.9 amendment ¶ — insert — ambiguity — `amendment_reason` is required/non-empty and overwrites the prior reason; amendment clears nothing else (`signed_at`, `turnaround_minutes`, `sla_breached`, `pattern`, `severity`, `template_version`, `clinical_comment` all survive until re-signature) — `r_reports.py:196, 200-203`

Verified-already-pinned (pass 3): **calc.py in full** — syringe/tolerance/BTPS chain and the "round `corrected_volume_l` first" ordering, the whole PH2O table, BCS bands with inclusive upper edges, 180-day baseline validity, `Z_LLN` 1.645 with the "round rsd first" ordering, BEV limit `max(100, round(5 % of FVC))` and the `<=` boundary, EOFE 15.0-or-plateau, the A/B/C/D/F ladder including `C == 2` and "null never satisfies", both BD variants, the pattern 2x2 with boundaries on the normal side, all five severity bands, `PFT-2026.1`, the three SLA bases, the inclusive 50.00/80.00 tier edges and 1.00/1.50/2.00 multipliers, PC20 `>= 20.00` on the *rounded* fall, the strict 400-unit ceiling and the exact-400 negative branch, the interpolation formula, half-up everywhere and `trunc_int` for turnaround. **Step-8 §3.9 insertions re-verified accurate** against `r_reports.py:35-82` (five-step deadline ordering, demotion strictly after) and `r_reports.py:154-186` (re-signature cascade). **services.py** — lookups' non-string-key behaviour, all serializers, device gates, `quarantine_device`/`cascade_device_quarantine`/`close_device_after_session`, `abort_session`'s fan-out, `settle_run_ledger`'s step-count rule and `DEPLETED` transition, `recompute_hold_release`'s maximum, `_best_two`'s tie-break, `recompute_session_quality`'s two pools, `apply_bronchodilator_response`, `select_reference_equation`'s three ranking keys, `roster_capacity`, `open_report_total`.

### Orchestrator final verification

- `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md` (507 vs 503 lines, 126,481 vs 113,841 B) — the scan genuinely ran in all three passes.
- Tail intact: file ends on the complete final row of the §5 error table (`| ERR_INTERNAL | 500 |`), a real section boundary.
- Every file under `implementation/` still carries its pre-sweep mtime (11:36-11:48, vs the green sweep at 13:17), confirming Steps 8 and 9 touched documentation only — the 8-round 96/96 green result remains valid for the delivered implementation.

**Pipeline complete.**
