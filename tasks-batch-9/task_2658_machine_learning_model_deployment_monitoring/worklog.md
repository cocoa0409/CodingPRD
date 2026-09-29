# Worklog — task_2658_machine_learning_model_deployment_monitoring

## Step 1: Create Task Directory — 2026-09-04T02:14:06.139Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2658_machine_learning_model_deployment_monitoring` and its `workspace/` subdirectory. Index 2658 was pre-assigned by the invoking pipeline (no scan of `./tasks/` performed, no auto-allocation — 32 pipelines run concurrently on this host and auto-allocation would collide).

## Step 2: Generate Scaffold — 2026-09-04T04:21:00.000Z

Complete. All three files are written, YAML-valid, and the scaffold linter is clean.

## Files

| Path | Lines | Bytes |
|---|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_2658_machine_learning_model_deployment_monitoring/SCAFFOLD.yaml` | 3595 | 204,901 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2658_machine_learning_model_deployment_monitoring/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2856 | 199,075 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2658_machine_learning_model_deployment_monitoring/SCAFFOLD_CORNER_DESIGN.yaml` | 5594 | 371,213 |

`SCAFFOLD.yaml` top-level keys: `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` — no `scaffold_difficulty_design` / `scaffold_corner_design` keys. The two design files each carry exactly one top-level key.

## SCAFFOLD.yaml counts (§1.0–§1.7)
- 13 entities, 58 endpoints (29 POST / 28 GET / 1 PATCH), 69 error codes
- 11 calculations, 10 state machines with 59 transitions, 58 validation rules (priorities 1–72), 2 §1.2.1 OCC rules, 5 roles
- Profile: workflow_orchestration + compliance_audit, layers `optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers`, flat topology, cyclic + parallel state shapes, `segregation_of_duties` role model, `immediate` consistency, `expert_plus`

## Design indices
- §1.8 `SCAFFOLD_DIFFICULTY_DESIGN.yaml`: 9 Difficulty Rules, **22 instances** (2–3 differentiated instances per rule)
- §1.9 `SCAFFOLD_CORNER_DESIGN.yaml`: **88 instances** — 55 with full `test_recipe`, 33 `excluded_because` stubs citing a §1.8 instance by name. Per section: entities 12, state_machines 11, calculations 12, validations 15, endpoints 5, errors 21, rbac 5, cross_cutting_complexity_layers 6, consistency_model 1

## Verification
`scaffold_lint.py` -> `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (1232 calls scanned across 22 + 55 instances)

Additional self-checks all pass: every instance `name` unique across both design files; every cited `difficulty_instance` resolves; every stub has no `test_recipe`; **all 69 error codes are triggered** somewhere in §1.8/§1.9; **all 58 endpoints are exercised**.

Three issues found and fixed while finishing:
- `ServingEndpoint.name` said "globally unique" in §1.1 while validation priority 52 declares uniqueness per `(name, region)` — the entity constraint now matches the rule (and §1.9 tests both).
- A capture used `reveiwed_by_user_id`-style field `reviewed_by_user_id`, which is not on `RevalidationTask` (the field is `reviewer_user_id`); lint caught it and it is corrected.
- Coverage gaps closed by two new §1.9 instances: `ERR_VERSION_NOT_APPROVED` was untriggered (now walked through DRAFT / PENDING_REVIEW / CHANGES_REQUESTED on `POST /deployments`), and seven GET endpoints were never called (now covered by a dual-read-channel instance plus two singleton reads added to existing chains).

Orchestrator verification: all three files present, `yaml.safe_load` succeeds on each, top-level keys confirmed correct. Task dir and `workspace/` survived the subagent (no wipe).

## Step 3: Copy Shared Files — 2026-09-04T04:22:28.864Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T04:42:00.000Z

The PRD is complete and verified.

**Output:** `workspace/PRD.md` — **577 lines / 136,917 bytes**, ending cleanly at the final row of the §5 error table.

**Section outline**
- `# ML Model Deployment & Monitoring API — Product Requirements Document`
- §1 Introduction (3 paragraphs)
- §2 Global Specifications & System-Wide Principles — 2.1 Operators, Roles and Access Control · 2.2 API Response Structure · 2.3 Pagination and List Ordering · 2.4 Resource Identity, Timestamps and the Logical Clock · 2.5 Numeric Precision and Rounding Discipline · 2.6 Stale-Version Guards on Capacity-Bearing Parents · 2.7 The Validation Ladder · 2.8 Resource Addressing and Nested Reads · 2.9 Cascade Discipline · 2.10 Segregation of Duties
- §3 Business Logic & Workflows — 3.1 Registry Entries and Their Champions · 3.2 Training-Data Snapshots · 3.3 Artifact Versions · 3.4 Serving Clusters, Deployment Creation, Traffic Ramping and Rollout Control · 3.5 Observation Windows and the Composite Health Score · 3.6 Drift Scoring, Skew Detection and Retraining Triggers · 3.7 Champion-Challenger Evaluation and Promotion · 3.8 Incident Response · 3.9 Periodic Revalidation and Operational Sweeps
- §4 Endpoint Definitions (intro paragraph + 58-row, 4-column table)
- §5 Error Code Catalogue (69-row, 2-column table)

**Coverage counts (machine-verified)**
- Entities: 13 / 13
- Endpoints: 58 / 58 — table set-equal to the scaffold on (method, path), zero missing, zero extra
- Errors: 69 / 69 — table set-equal, all HTTP codes match, and all 69 IDs are also named in §1–§3 prose
- State machines: 10 / 10 dimensions; all 59 transitions (57 unique from->to pairs) rendered
- Calculations: 11 / 11 (`traffic_ramp_step_plan`, `composite_health_score`, `drift_index`, `challenger_promotion_score`, `retraining_urgency`, `feature_skew_ratio`, `endpoint_traffic_ledger`, `evaluation_sample_ledger`, `revalidation_schedule`, `documentation_and_reproducibility_score`, `dataset_dependency_counter`)
- Validation rules: 58 / 58, front-loaded as an ordered ladder in §2.7 including all three priority-pair conflicts
- Concurrency rules: 2 / 2 · Roles: 5 / 5

**Hard contracts**
- Contract 1 (Field-Name Coverage) **PASS** — 151 identifiers (134 entity fields + 83 request/query tokens + 13 path params, deduplicated) all appear verbatim in backticks; second pass over 93 enum/state literals plus the four common fields also clean.
- Contract 2 (Rule Coverage) **PASS** — every transition, calculation, validation error, OCC rule, cross-entity cascade and endpoint side effect is stated in prose.
- Contract 3 (§3 Path Purity) **PASS** — 1,566 backtick tokens in §3, zero starting with `/`, zero bare HTTP methods, zero method+path combinations. §1–§2 also carry no path tokens.

§2.2 is byte-identical to `skills/prd-bench-doc-generator/section-2.2-response-structure.md`. No fuzzy words (`approximately`/`roughly`/`conservatively`) and no meta/difficulty/test references appear anywhere.

Two scaffold ambiguities resolved by judgement: (1) `ERR_OVERRIDE_EXCEEDS_CURRENT_TRAFFIC` rendered as "at least 0.00 and strictly less than the current `traffic_pct`" (matching validation priority 36 and the endpoint contract over the state-machine's inclusive form); (2) trigger staling rendered inclusively (`stale_after` at or before the clock, boundary explicitly called out) matching the sweep endpoint contract. Also noted: rollback drains use `DEPLOYMENT_ROLLED_BACK` while revocation/revalidation-failure drains use `DEPLOYMENT_DRAINED`, and only the latter blocks an extension. As instructed, neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, and no sibling task directory was read.

**Orchestrator truncation check (per the known doc-generator failure mode):** `tail -c 1200` shows the document terminating at `| \`ERR_NO_LABELED_PREDICTIONS\` | 422 |` — a complete final table row at a genuine section boundary, not mid-sentence. All 5 top-level sections and all 22 subsections present via `grep -n '^#'`. No regeneration needed.

## Orchestrator deviation note — Steps 5/6 launch ordering — 2026-09-04T06:30:00.000Z

**Deviation from the skill, recorded for honesty and for downstream interpretation.** The skill requires Steps 5 and 6 to be launched *concurrently in a single assistant message*, both for throughput and — more importantly — because concurrent launch gives the implementation generator *physical* isolation from `test_suite/` (the directory does not exist when it starts). I launched Step 5 alone and waited for it, so by the time the Step 6 impl generator started, `test_helpers/` and `test_suite/` already existed on disk.

**Mitigation applied** (physical isolation was unrecoverable once the ordering slipped, so it was replaced with an enforced prohibition): the Step 6 prompt led with an ABSOLUTE PROHIBITION section, flagged as the single most important instruction in the prompt, forbidding any read/open/cat/head/tail/ls/glob/grep/py_compile/import of either directory or even of the filenames inside them, and explaining that the benchmark's validity rests on writing the implementation from PRD.md alone. The Step 6 agent affirmed on exit: "no command at any point read, listed, globbed, grepped, compiled, or imported anything under `test_helpers/` or `test_suite/`."

**Residual risk:** the isolation is now attested rather than structural. Treat the Step 6 coverage claims as unverified against that specific risk. Note the mitigating evidence in the Step 6 report: its four self-written smoke suites produced 6 mismatches that it correctly diagnosed as *its own wrong expectations* about PRD semantics — behaviour consistent with an agent reasoning from the PRD rather than one that had read the assertions it needed to satisfy.

## Step 5: Generate Unit Tests — 2026-09-04T06:28:00.000Z

Generation is complete. Both design indices are fully translated.

## Output

All files at the task root — nothing was written under `workspace/` (verified: `workspace/` holds only `INSTRUCTION.md` and `PRD.md`), nothing under `workspace/implementation/` was read, and no sibling task directory was touched.

**`test_helpers/` (9 files, 2625 lines)**
`__init__.py` 64, `api_client.py` 403, `api_errors.py` 188, `assertions.py` 408, `constants.py` 272, `factories.py` 358, `fixtures.py` 575, `test_users.py` 99, `types.py` 258.

**`test_suite/` (24 test modules + `conftest.py` 20 lines, 7808 lines total)**
Queue A: `test_01` 111, `test_02` 119, `test_03` 139, `test_04` 118, `test_05` 131, `test_06` 133, `test_07` 205, `test_08` 147, `test_09` 161, `test_10` 181, `test_11` 272, `test_12` 409, `test_13` 267, `test_14` 260, `test_15` 271.
Queue B: `test_20_entity_contracts` 593, `test_21_state_machines` 457, `test_22_calculations` 341, `test_23_validations` 442, `test_24_endpoint_behaviours` 689, `test_25_error_paths` 1314, `test_26_rbac` 571, `test_27_occ` 308, `test_28_consistency` 149.

## Totals

- **116 test functions**, every one carrying exactly one `Design:` tag.
- **Queue A: 62 tests over all 22 non-stub difficulty instances** (>=2 per instance, 22/22 covered).
- **Queue B: 54 tests over 54 of the 55 non-stub corner instances**, 1:1 — entities 12, state_machines 7, calculations 4, validations 6, endpoints 5, errors 12, rbac 5, cross_cutting_complexity_layers 2, consistency_model 1.
- Programmatic audit: every tag resolves to a real, non-stub `name:` in the source yaml; no untagged, dual-tagged, malformed or stub-pointing tags; no `skip`/`skipif`/`xfail` anywhere.
- `python3 -m py_compile` passes on all 34 emitted `.py` files; both new modules also import cleanly with the task root on `sys.path` (so every helper symbol referenced exists). `pyflakes` is clean except two deliberate re-export patterns in Stage 1 files.

## Skipped instances

- **`Corner/calculations/documentation_score_ignores_array_members_outside_the_required_lists`** — the only true skip. PRD §3.3 line 206 self-contradicts on out-of-enum array members: it says "array members outside the two required lists are ignored entirely and never raise either percentage" while the same paragraph requires every member of `doc_sections`/`repro_artifacts` to be one of the declared enum keys (i.e. an out-of-enum member is an `ERR_INVALID_REQUEST`). The asserted outcome is therefore not uniquely derivable. Gap left as a gap.

## Deviations recorded (design recipe vs PRD; PRD followed in all cases)

1. **Five-ramp REALTIME walk (both new recipes).** `occ_rule_two_...` and `every_derived_field_and_cascade_...` both assert five ramps reach LIVE at 100.00 with a final delta of 35.00. PRD §3.4 line 253 spells out **six** ramps — the fifth is trimmed by the 30-point per-step ceiling to land on 95.00 with `ramp_step_index` unmoved, the sixth moves the last 5 points to LIVE. Followed the PRD; ledger deltas are 5/10/20/30/30/5.
2. **Ramp-step ledger count.** The consistency recipe asserts `total_count` 6 (5 ramps + 1 rollback); the PRD's six-ramp walk plus the single `ROLLBACK_RELEASE` row gives **7**. Asserted 7.
3. **Registry-entry version arithmetic.** The `occ_rule_two_...` recipe claims the model sits at version 1 before the promotion and 2 after. PRD §3.3 also increments the registry entry's `version` on every version `APPROVE`, so with two approved versions the pre-promotion token is 3 and the post-promotion token is 4. Asserted the PRD-derived 3 -> 4 -> 5 sequence (and 20000 = 50000 - 30000 for the challenger's `evaluation_sample_budget`).

Carried from earlier sessions (unchanged): the DRAINED leg of `deployment_create_and_ramp_gated_by_serving_endpoint_operational_state` omitted (§3.4 vs §4 naming contradiction); `champion_version_id is null` weakened to `!= challenger_version_id` in two cascade instances; the unreconstructible 87.63/93.25 literals left unasserted in `drift_report_critical_cascade_depth_five`; `windows_used_count` 1->0 in `every_observation_row_...`; the 90-vs-45 interval contradiction resolved to 45 in `get_model_by_id_returns_the_stored_row`; duplicate `INTENDED_USE` dropped from `computed_documentation_scores_...`; the SUBMITTED (not DRAFT) landing in `rejected_dataset_resubmission_loops_back_through_draft`; `START_REVIEW` inserted into `revalidation_failure_cascades_down_to_version_and_deployment`; the LINK_VERSION trigger re-sourced from a WARN drift breach; `evaluated_count` left unasserted where the PRD does not settle whether a not-yet-due version counts as examined; empty `serving_feature_stats` replaced by a value with no numeric `mean` in the skew-shape test; `ENGAGE_FALLBACK` inserted before `MONITOR` in `shared_operations_are_accepted_from_every_declared_holder`; and PASS/FAIL reviewer-identity enforced per §3.9 in `revalidation_review_cannot_be_taken_by_the_approver_who_decided_the_version`.

## Step 6: Generate Implementation — 2026-09-04T06:32:00.000Z

Done. The implementation for task 2658 is complete, compiles clean, and passed four smoke suites.

## Deliverable

`workspace/implementation/`

| file | lines |
|---|---|
| `start.sh` | 10 |
| `requirements.txt` | 1 (`flask>=2.0.0`) |
| `app.py` | 64 |
| `db.py` | 215 |
| `errors.py` | 101 |
| `response.py` | 54 |
| `middleware.py` | 249 |
| `calc.py` | 305 |
| `cascades.py` | 308 |
| `routes/__init__.py` | 0 |
| `routes/registry.py` | 507 |
| `routes/serving.py` | 418 |
| `routes/monitoring.py` | 468 |
| `routes/experiments.py` | 610 |
| **total** | **3310** |

## Coverage (machine-verified, not estimated)

- **Endpoints: 58/58** — `app.url_map` yields exactly 58 method+path pairs, matching the PRD §4 table one-for-one.
- **Error codes: 69/69** — `len(errors.ERROR_HTTP) == 69`, each with its PRD-mandated HTTP status.
- **State machines: 10/10** — Model, TrainingDataset, ModelVersion approval, ServingEndpoint operational, Deployment `rollout_state`, Deployment `health_state` (parallel dimension on the same row), MonitoringWindow, ChallengerEvaluation, PredictionIncident, RetrainingTrigger, RevalidationTask.
- **Calculations: 11/11** — health score (PROVISIONAL/FINAL variants), drift index (PSI, 5 bins, eps=0.0001), drift severity banding, skew ratio, promotion score, doc completeness %, ramp target/step, cumulative ramp delta, endpoint traffic ledger, evaluation sample ledger, trigger urgency + revalidation due date.
- **Validation ladder: 58 rules** in a single ordered gate chain per handler, returning the first violated rule, following PRD §2.7's band order (auth -> path 404 -> body-FK 404 -> INVALID_REQUEST + specialised body codes -> pagination -> interval/clock -> 412 stale-version -> TERMINAL/INVALID_STATE -> window/ramp gates -> override -> SoD -> safety -> referential -> uniqueness -> temporal -> capacity).

## Smoke result

Server launched with `PORT=18658 bash start.sh`; killed afterwards with `fuser -k 18658/tcp` only (no broad `pkill` at any point; 0 listeners remain on 18658).

- Suite 1 (55 checks): all green. Verified PRD worked examples health 86.08 PROVISIONAL / 77.08 FINAL, drift 0.1354 WARN, skew 1.2500 on `amount` FAIL_SKEW, revalidation due 2026-10-30, sweep idempotence, 4-hop revalidation-failure cascade, auth/pagination/envelope shape.
- Suite 2 (41 checks): 40 green; the one mismatch was a wrong test expectation — for a LIVE ramp-complete deployment `ERR_RAMP_ALREADY_COMPLETE` correctly outranks `ERR_OPEN_INCIDENT_BLOCKS_ACTION` (state band precedes safety band). Verified promotion score 0.0437 with per-line [0.0226, 0.0029, 0.0075, 0.0107], champion pointer move, manual-override -60/release +60 telescoping to 100.00, rollback to 0.00, snapshot-revocation cascade.
- Suite 3 (28 checks): 24 green; the four mismatches were again wrong expectations of mine (I assumed an empty rolling pool, but a prior CLOSED DISTRIBUTION window legitimately qualified). Verified DEGRADED half-step truncation (15.00 -> 25.00 with `ramp_step_index` held at 2), zero-label provisional score 55.00, and the full extension cycle: reserve/release budget, 1500/2000 reserved, +6-day `evaluation_ends_at`, score cleared on extend, `ERR_MAX_EXTENSIONS_REACHED` at the third extend, `ERR_INVALID_STATE` on zero labels.
- Suite 4 (13 checks): all green. Confirms the PRD's pinned ROLLING_BASELINE example — expected bins [0.1200, 0.1667, 0.2000, 0.2467, 0.2667], `drift_index` 0.0094, severity NONE, `baseline_dataset_id` null, `windows_used_count` 3 — including the top-3 cut correctly excluding a fourth, older window, plus `ERR_WINDOW_NOT_CLOSED` on an open target.

## Constraint compliance

- Storage is in-process dicts only. A `grep` for `open(`, `sqlite3`, `shelve`, `pickle`, `json.dump(`, `/tmp` across every `.py` returns nothing. Cold boot re-verified: 13 tables, **0 rows**, clock at the documented default `2026-08-01T00:00:00Z` — so per-test `start.sh` relaunch wipes all state and nothing is ever seeded.
- `start.sh` reads `$PORT`, binds `0.0.0.0`, runs in the foreground, no reloader, no threading.
- `__pycache__` removed; the deliverable directory contains only the 14 source files.
- The prohibition was honoured in full: no command at any point read, listed, globbed, grepped, compiled, or imported anything under `test_helpers/` or `test_suite/`, nor `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `worklog.md`, or any sibling task directory. The three throwaway smoke scripts live in `/tmp`, not in the deliverable.

One judgement call worth flagging: where PRD §3.5–§3.8 prose sequences gates differently from the §2.7 ladder (monitoring-window `DEPLOYMENT_NOT_SERVING`, `MANUAL_OVERRIDE_ACTIVE` vs `OVERRIDE_EXCEEDS_CURRENT_TRAFFIC`, evaluation-schedule `MODEL_ARCHIVED`), I followed §2.7, per the instruction that PRD.md's stated priority ordering is the contract. On conclude I implemented `CHALLENGER_UNHEALTHY` and `SKEW_CHECK_FAILED` as criteria keys rather than 422 pre-gates, since §3.7 enumerates their boundary semantics as criteria and pre-gating them would make the three-way fork unreachable.

Orchestrator verification: `test_helpers/` (9 files) and `test_suite/` (25 files, 116 test functions) confirmed at the task root; `find` shows no stray copies under `workspace/`; implementation directory holds 14 source files plus `routes/`.

## Step 7: Run Tests and Iterate — 2026-09-04T07:18:59.915Z

Clean 8-round sweep achieved: **116/116 passing in all 8 parallel rounds**.

## Summary

**Iterations run:** 3 (each a full 8-round parallel sweep). Progression: 109/116 -> 114/116 -> 116/116, with identical failures in all 8 rounds every time — no flakiness or load-induced noise at any point.

**Tests deleted:** none. Every failing test traced to a verbatim PRD sentence and passed the unique-derivability check; all 7 failures were defects in the test artifact itself, not PRD-silence.

**Fixes applied to `test_helpers/`:** none. The bugs were in `test_suite/`; the helper layer was already correct (notably `api_errors.ERROR_HTTP` already mapped all five affected codes to 409, and `fixtures.record_and_close_window` already implemented the correct record->advance-clock->close sequence).

**Fixes applied to `test_suite/`:**

1. `test_suite/test_25_error_paths.py` — five `validate_error(..., <ERR>, 422)` calls asserted HTTP 422 for error codes that PRD §5's error catalogue pins at **409**. Corrected to 409: `ERR_SAMPLE_BUDGET_EXCEEDED` and `ERR_ACTIVE_EVALUATION_EXISTS` (in `test_scheduling_an_evaluation_walks_metrics_arms_budget_then_uniqueness`), `ERR_RETRAIN_REQUIRED` (in `test_a_high_urgency_trigger_cannot_be_dismissed`), `ERR_DUPLICATE_MODEL_NAME` and `ERR_DUPLICATE_SERVING_ENDPOINT_NAME` (in `test_registry_uniqueness_is_on_the_pair_and_hashes_must_match`). The error_id assertions were left exactly as-is — only the mistranslated status literal changed.

2. `test_suite/test_03_drift_baseline_variants.py` — the local `_closed_distribution_history` helper recorded all four DISTRIBUTION windows on one deployment before closing any, which PRD §3.5 correctly rejects ("no other window sharing this `deployment_id` and this `window_kind` may still be in `status` `OPEN` … exactly one open window per deployment per monitoring family"). Rewrote it to use the existing `record_and_close_window` helper so each window is closed before the next is recorded. Verified the rolling-baseline top-3 ranking and the pinned expected bins `[0.1200, 0.1667, 0.2000, 0.2467, 0.2667]` are unaffected by the reordering. Fixed 3 tests.

3. `test_suite/test_01_health_score_variants.py:109` — `validate_success(...)["data"]` double-unwrapped the envelope (`validate_success` already returns `body["data"]`), causing `KeyError: 'data'`. Dropped the redundant subscript.

**Fixes applied to `implementation/`:** **none.** The implementation was correct on all 7 failures and was not modified — verified by `ls` (only the 14 original source files plus `routes/`) and by a persistence audit confirming no `sqlite3`/`pickle`/`open(`/`json.dump(` anywhere, so state is in-memory only and `start.sh` re-invocation wipes it.

One systematic step worth noting: after iteration 2 revealed the same 422-vs-409 class recurring, I stopped fixing one-at-a-time and machine-audited every `(ERR_*, <status>)` literal pair across all 25 test files against the PRD §5 catalogue parsed straight from `PRD.md`. That found exactly the two remaining mismatches and confirmed zero others, which is why iteration 3 was the last.

### Orchestrator independent verification of Step 7 (not taken on trust)

Per a known failure mode where a Step 7 agent reports a clean sweep while leaving no artifacts behind, the sweep was verified directly on disk rather than from the subagent's report:
- `ls -la results.*.json` -> all 8 files present, ~34.5 KB each, all timestamped 07:17.
- `json.load` on each of the 8 -> `passed=116 total=116 failed=0` for rounds 1 through 8. Confirmed genuinely clean.
- `grep` for `pytest.mark.skip` / `pytest.mark.xfail` / `skipif` across `test_suite/` and `test_helpers/` -> **none**, so the green sweep was not bought with dodged assertions.
- Test count still **116** functions with **116** `Design:` tags -> 1:1, and no test was silently dropped to reach green (consistent with the reported 0 deletions).
- Persistence audit re-run independently -> no `sqlite3`/`pickle`/`json.dump(`/`shelve` in `implementation/`; storage is in-memory only.

**Step 8 gating decision:** the skip condition requires 0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes. Deletions, `test_helpers/` fixes and `implementation/` fixes were all 0, but there were 3 `test_suite/` fixes, so the condition is not met and Step 8 runs. Expectation recorded in advance: because `implementation/` was never modified, these three fixes were pure test-artifact defects (a mistranslated HTTP status where PRD §5 is explicit, a fixture ordering that PRD §3.5 explicitly forbids, and an envelope double-unwrap) and none of them evidences PRD silence or PRD/impl mismatch. Step 8 should therefore legitimately produce a near-empty or empty diff; that outcome is correct, not a failure, and the real completeness work falls to Step 9's full scan.

## Step 8: Finalize PRD — 2026-09-04T07:20:30.000Z

## Result: `PRD_FINALIZED.md` created, zero edits warranted

`workspace/PRD_FINALIZED.md` exists as a byte-identical copy of `PRD.md`.

- Line counts: PRD.md 577 / PRD_FINALIZED.md 577 — **0 lines changed, 0.0% delta** (136,917 bytes both; `diff` empty).
- Changes: **none.** All three Step 7 items were verified against `implementation/` and every one is a defect in the test artifact against a PRD that already uniquely pins the behavior — consistent with Step 7 having applied zero implementation fixes.

### Verification per Step 7 item (mandatory pre-edit search, run even though no edit followed)

**Item 1 — five `validate_error(..., 422)` corrected to 409**
- (a) Subject: HTTP status mapping of the error catalogue, specifically `ERR_SAMPLE_BUDGET_EXCEEDED`, `ERR_ACTIVE_EVALUATION_EXISTS`, `ERR_RETRAIN_REQUIRED`, `ERR_DUPLICATE_MODEL_NAME`, `ERR_DUPLICATE_SERVING_ENDPOINT_NAME`.
- (b) Enumerated: `implementation/errors.py:3-101` (`ERROR_HTTP`, `ApiError.http_status = ERROR_HTTP.get(id, 400)`); raise sites `routes/experiments.py:77,82,84,86,89,256`, `routes/monitoring.py:433`, `routes/registry.py:67`, `routes/serving.py:46`; PRD §5 table (lines 507-577) and §2.7 ladder (lines 116-140). Ran a full programmatic diff of PRD §5's 69 rows against `ERROR_HTTP`: **69 vs 69, zero missing on either side, zero status mismatches.** PRD §5 pins all five at 409 verbatim (`PRD.md:541,543,545,547,559`).
- (c) No wording adjustment needed — PRD already determines this; editing would have been a no-op or a corruption.
- Bonus check on the same site: impl's evaluation-create gate order is MODEL_MISMATCH -> ACTIVE_EVALUATION_EXISTS -> CHALLENGER_NOT_SHADOW -> MODEL_ARCHIVED -> SAMPLE_BUDGET_EXCEEDED, which matches §2.7's uniqueness-band ordering and capacity-last rule exactly.

**Item 2 — `_closed_distribution_history` rewritten to close each window before recording the next**
- (a) Subject: the one-open-window-per-(deployment, window_kind) rule and the rolling-baseline candidate pool.
- (b) Enumerated: `routes/monitoring.py:66-78` (siblings loop: duplicate-open checked before overlap, both before `ERR_DEPLOYMENT_NOT_SERVING` at :77-78), `:128-157` (close path, `window_end > db.now()` -> `ERR_WINDOW_NOT_ENDED`, i.e. "at or before" as PRD states), `_expected_bins` at `:163-187` (pool = same `deployment_id`, `DISTRIBUTION`, `CLOSED`, excluding own window; sorted `window_end`, `created_at` desc; top 3), `ROLLING_WINDOW_LIMIT = 3`; PRD §3.5 (line 279) and §3.6 (line 307) and §2.3/§2.7.
- (c) No adjustment: PRD §3.5 states the rule verbatim ("no other window sharing this `deployment_id` and this `window_kind` may still be in `status` `OPEN` … exactly one open window per deployment per monitoring family"), §2.7 pins `ERR_DUPLICATE_OPEN_WINDOW` (uniqueness band) ahead of `ERR_MONITORING_WINDOW_OVERLAP` (temporal band) ahead of `ERR_DEPLOYMENT_NOT_SERVING` (temporal band, last) — which is precisely the impl's check order — and §3.6 pins the pool predicate, the `window_end` desc / `created_at` desc ranking, the first-three cut, and the expected bins `0.1200, 0.1667, 0.2000, 0.2467, 0.2667`.

**Item 3 — `test_01_health_score_variants.py:109` redundant `["data"]` dropped**
- (a) Subject: the success envelope shape on a single-resource read (`GET /monitoring-windows/{id}`), plus the health-read it sits next to.
- (b) Enumerated: `implementation/response.py` (`ok`/`created`/`listing`), `routes/monitoring.py:105-109` (window read), `routes/serving.py:347-380` (`deployment_health`, on-demand FINAL over an OPEN window, `score_variant` default `PROVISIONAL`); PRD §2.2 (lines 29-55).
- (c) No adjustment: §2.2 pins the `meta`/`response_type`/`data` envelope, so the double-unwrap was purely a test bug; impl also matches §3.5's "computes the score on demand and does not persist it".

### Considered and deliberately not edited
`PRD.md:279` introduces the record-window gates as "Three gates guard the record." listing `rollout_state` first, whereas the impl evaluates it last (`routes/monitoring.py:77`). This is not a divergence: §2.7 is explicitly the single authoritative ordering ("Every request walks a single ordered ladder … The bands, in evaluation order") and places the general not-serving check in the temporal band after uniqueness/overlap, exactly as implemented. §3.5 makes no ordering claim, so adding one would risk a new mismatch without fixing an ambiguity. Likewise left alone: the impl's `_seq` third-level tiebreak in the rolling-baseline sort (only reachable when both `window_end` and `created_at` tie — a case the corrected helper no longer produces, hence not revealed by any Step 7 fix), and the extra nulls (`baseline_delta_pct`, `prediction_count`, `labeled_prediction_count`) the health read returns when a deployment has no PERFORMANCE window (outside every Step 7 site).

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` is empty, both 136,917 bytes / 577 lines. For Step 8 a byte-identical output is the legitimate expected result given Step 7's zero implementation fixes (unlike Step 9, where byte-identity would signal the scan never ran). The three items Step 8 explicitly deferred as out-of-scope — the §3.5 gate-ordering wording, the `_seq` third-level tiebreak, and the extra null fields on the health read with no PERFORMANCE window — are being forwarded to Step 9 as starting hints, since they are exactly the residual PRD silences Step 9's full scan exists to close.

## Step 9 execution plan (orchestrator decision) — 2026-09-04T07:21:00.000Z

Step 9 is being run as **three sequential file-partitioned passes** over the 3,299-line implementation rather than one pass. Rationale: a known failure mode is a single Step 9 agent exhausting its budget on the walk and emitting a byte-identical `PRD_COMPLETED.md` — i.e. the scan silently never ran. Partitioning bounds each agent's reading load and makes the "did it actually scan" question checkable per pass. The passes must be sequential, not parallel, because all three edit the same file.
- Pass 1: `db.py`, `errors.py`, `response.py`, `middleware.py`, `app.py`, `routes/registry.py` (1,646 lines) — creates `PRD_COMPLETED.md` from `PRD_FINALIZED.md`.
- Pass 2: `routes/serving.py`, `routes/monitoring.py` (886 lines) — continues editing.
- Pass 3: `routes/experiments.py`, `calc.py`, `cascades.py` (1,223 lines) — continues editing, plus the three deferred Step 8 hints.

## Step 9: Complete PRD — 2026-09-04T08:05:00.000Z

Run as three sequential file-partitioned passes over `implementation/` (3,299 lines). All three edited `workspace/PRD_COMPLETED.md` in place; passes 2 and 3 were explicitly forbidden from any `cp` so as not to destroy prior passes' work, and each was handed the previous pass's deferred findings.

**Cumulative result: PRD.md 577 lines / 136,917 chars -> PRD_COMPLETED.md 579 lines / 161,239 chars (+2 lines, +24,322 chars, +17.8%). 69 edits total: 50 ambiguity-pins, 19 mismatch-revisions.**

### Pass 1 — app.py, db.py, errors.py, response.py, middleware.py, routes/registry.py (1,646 lines)
26 edits (19 ambiguity-pins, 7 mismatch-revisions); 577 -> 579 lines, 136,917 -> 146,128 chars.
- §2.1 revise/ambiguity — headers rejected when whitespace-only; role compared case-sensitively against the untrimmed value — middleware.py:30-37
- §2.2 revise/ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars — response.py:9,13
- §2.2 revise/ambiguity — `api_request_timestamp` is real wall-clock UTC, the one instant that does not read the logical clock, always 3 fractional digits — response.py:16-19
- §2.3 insert/ambiguity — present-but-non-integer `limit`/`offset` is `ERR_INVALID_PAGINATION`, not `ERR_INVALID_REQUEST`; whitespace trimmed — middleware.py:53-75
- §2.3 insert/ambiguity — implicit final tiebreak on internal creation sequence wherever `created_at` is the last sort key — db.py:192-197
- §2.3 insert/ambiguity — exact `has_more` formula; echoed `limit`/`offset` are effective values; filters exact case-sensitive; boolean filter accepts true/1/yes / false/0/no any case and yields an empty page on anything else; undeclared query params ignored — middleware.py:82-102, response.py:43
- §2.4 revise/**mismatch** — instants render with 3 fractional digits *only* when the ms component is non-zero (`2026-08-01T00:00:00Z`), sub-ms truncated not rounded — db.py:98-105
- §2.4 insert/ambiguity — accepted ISO-8601 input grammar (T or space, optional seconds, <=9 fractional digits, optional `Z`/offset normalised to UTC, omitted offset = UTC); unparseable -> `ERR_INVALID_REQUEST` — db.py:66-95, middleware.py:187-195
- §2.5 insert/ambiguity — quantities are JSON numbers without trailing zeros (`80.00` -> `80.0`); decimals are a rounding not a rendering rule — db.py:151-157
- §2.7 revise/**mismatch** — specialised-code preference does not outrank the endpoint's other required-field sweep; bin-proportion code needs a present array — middleware.py:228-249, registry.py:122-125
- §2.7 insert/ambiguity — new paragraph: JSON `null` == omitted; absent/invalid/non-object body treated as `{}`; numeric fields must be JSON numbers; non-string body FK skips the 404 band -> `ERR_INVALID_REQUEST` — middleware.py:43-47,112,159,174, registry.py:38-48
- §2.8 insert/ambiguity — trailing slash insignificant; unrouted path -> `ERR_NOT_FOUND` 404, undeclared method -> `ERR_METHOD_NOT_ALLOWED` 405, both outside §5/the ladder and answered before headers are read — app.py:23,38-49
- §3.1 insert/ambiguity — duplicate `name`/`owner_team` check spans entries of any `registry_status` — registry.py:65-67
- §3.1 insert/ambiguity — archive takes no body; re-archiving an `ARCHIVED` entry is accepted and bumps `version` again — registry.py:106-112
- §3.2 revise/**mismatch** — submit does not re-check `baseline_bin_proportions` (immutable after registration); takes no body — registry.py:176-192
- §3.2 revise/ambiguity — snapshot-decision `note` must be a string but is not persisted — registry.py:202
- §3.2 insert/ambiguity — `revocation_reason` >=1 char, no max; revoke leaves `decided_by_user_id` untouched — registry.py:229-238
- §3.3 revise/**mismatch** — digest may arrive as `artifact_digest` **or** `artifact_uri` (digest wins if both), stored/returned as `artifact_digest`, neither -> `ERR_INVALID_REQUEST`; `feature_spec_hash` is 1-80 chars — registry.py:259-273
- §3.3 insert/ambiguity — `parent_version_id` may be in any `approval_state` — registry.py:288-289
- §3.3 revise/**mismatch** — an array member outside the declared key set is `ERR_INVALID_REQUEST`, not "ignored entirely" — middleware.py:198-214, registry.py:280-282
- §3.3 insert/ambiguity — documentation PATCH requires both arrays (omitted or `null` -> `ERR_INVALID_REQUEST`; `[]` clears) — registry.py:353
- §3.3 revise/ambiguity — version-decision `note` not persisted — registry.py:407
- §3.3 insert/ambiguity — `BLOCKED -> APPROVED` re-evaluates neither the doc/repro gate nor `pii_review_passed`, and does not bump the registry entry's `version` — registry.py:464-475
- §3.3 insert/ambiguity — deprecation closes revalidation tasks in `created_at` ascending order, keeps `blocked_reason`, leaves the snapshot's `version` unmoved — registry.py:495-506
- §4 `GET /models` revise/**mismatch** — add the `champion_version_id` filter — registry.py:98
- §4 `POST /model-versions` revise/**mismatch** — snapshot need not be approved at registration; digest field named `artifact_digest` or `artifact_uri` — registry.py:252-272

errors.py was diffed programmatically against §5: exactly 69 ids, zero missing/extra, zero status mismatches. Claims verified against a live server on an unusual port.

### Pass 2 — routes/serving.py, routes/monitoring.py (886 lines)
19 edits (13 ambiguity-pins, 6 mismatch-revisions); 146,128 -> 154,184 chars, no line-count change (all in-paragraph).
- §2.3 revise/**mismatch** — only revalidation tasks declare a non-`created_at` list ordering; window / skew-check / trigger lists are `created_at` asc; `window_end` desc and `checked_at` desc recast as internal "most recent row wins" lookups; the `total_urgency` desc claim dropped — monitoring.py:124,336,365, cascades.py:116,139, experiments.py:480
- §2.7 revise/**mismatch** — specialised-shape-code preference only guarantees precedence behind the *presence* sweep; per-endpoint beyond that — monitoring.py:47-58,290-291
- §2.10/§3.4 ledger revise/**mismatch** — "every rollout action" narrowed to `ROLLBACK`/`RETIRE`; `HOLD`/`RESUME` recompute nothing and never touch the cluster row or its `version` — serving.py:295-306
- §3.6 `LINK_VERSION` revise/**mismatch** — introduces the **lineage anchor**: the drift report's version, else the skew check's version, else none — monitoring.py:371-381,455-459
- §4 `POST /serving-endpoints` revise/**mismatch** — accepted fields corrected from `pattern_support`/`min_headroom_pct` to `serving_feature_spec_hash` plus optional `max_traffic_pct`/`deploy_cooldown_minutes` — serving.py:35-42
- §4 operational-state row revise/**mismatch** — enum `OPEN`/`DRAINING`/`FROZEN` -> `OPEN`/`FROZEN`/`DRAINED` — serving.py:20
- §3.4 insert/ambiguity — no posture state machine, no terminal posture; re-setting the held value is accepted and bumps `version`; missing/unknown -> `ERR_INVALID_REQUEST` — serving.py:82-92
- §3.4 insert/ambiguity — creation never compares the serve interval to the clock; `ERR_SERVE_WINDOW_EXPIRED` is ramp-time only — serving.py:119-120,223
- §3.4 insert/ambiguity — ramp precondition list is topical, not an evaluation order; ramp allowed from `PENDING`/`RAMPING`/`LIVE`, `HELD`/`DRAINING` -> `ERR_INVALID_STATE`, already-`LIVE` -> `ERR_RAMP_ALREADY_COMPLETE` — serving.py:233-239
- §3.4 insert/ambiguity — `action` required; `note` validated as an unbounded string then discarded — serving.py:277-279
- §3.4 insert/ambiguity — `ROLLBACK` ledger row's `from`/`to`, `step_index` (pre-reset), `health_state_at_step`, `clock_at_step` — serving.py:313-316
- §3.4 insert/ambiguity — `RETIRE`'s `DRAIN_RELEASE` row columns; leaves `ramp_step_index`, `rolled_back_at` and the champion pointer alone, touches no evaluation — serving.py:332-343
- §3.5 insert/ambiguity — exact field-validation sequence (bins -> counts/consistency -> the rest); `positive_rate`/`observed_bin_proportions` stored verbatim, never re-rounded — monitoring.py:43-58,89,91
- §3.5 insert/ambiguity — the three window gates are topical; §2.7 fixes precedence — monitoring.py:63-78
- §3.5 insert/ambiguity — provisional mirror applies to every `window_kind` and never moves `health_state` — monitoring.py:102-103
- §3.5 insert/ambiguity — health read: empty `score_variant` == omitted, other values `ERR_INVALID_REQUEST` after path resolution; pool includes `OPEN` windows; persists nothing; full five-null shape when no window exists — serving.py:346-380
- §3.6 insert/ambiguity — a closed window may be scored any number of times, independently — monitoring.py:192-230
- §3.6 insert/ambiguity (handoff 2) — absent/`null`/non-object map, non-object entry and bad `mean` all give `ERR_INVALID_FEATURE_STATS`; empty serving map legal; extra entry keys ignored; maps persisted verbatim — monitoring.py:261-291
- §3.6 insert/ambiguity — `retrained_version_id` resolved under every action (dangling -> 404 even on `ACKNOWLEDGE`); `dismissed_reason` bounded 1-500 under every action — monitoring.py:391-399

Handoff item 1 resolved in favour of the implementation, but without discarding the domain orderings: §2.3 reassigns them to their real home (`window_end` desc -> `latest_performance_window`/rolling-baseline pool; `checked_at` desc -> `latest_skew_check`), and drops `total_urgency` desc because nothing uses it. Revalidation tasks were verified to genuinely sort `due_at` asc -> `created_at` asc -> internal sequence, so that declaration survives.

### Pass 3 — routes/experiments.py, calc.py, cascades.py (1,223 lines)
24 edits (18 ambiguity-pins, 6 mismatch-revisions); 154,184 -> 161,239 chars, 0 lines.
- §3.4 insert/ambiguity — `cumulative_ramp_delta_pct` recomputed after *every* ledger append, whatever the row's `reason` — cascades.py:86
- §3.4 insert/ambiguity — `DRAIN_RELEASE` row's `step_index` (never reset by this hop), `health_state_at_step`, `clock_at_step` — cascades.py:176 via 74-87
- §3.6 revise/**mismatch** — the 0.0001 floor applies only to the two proportions inside the log ratio, never to the leading difference; worked 0.0000-vs-0.2000 example added — calc.py:143-148
- §3.6 revise/**mismatch** — hop 5 fires for *every* `CRITICAL` breach whether or not hop 4 found a `RAMPING` deployment, and applies no serving-state gate; the deployment is written at most once by hops 3+4 — cascades.py:244-280
- §3.6 insert/ambiguity — staleness term is 0 whenever the whole-day count is not strictly positive, so it never contributes negatively — calc.py:210-214
- §3.7 insert/ambiguity — creation defaults on scheduling (`challenger_version_id` copied from the challenger deployment, `created_by_user_id` from `X-User-ID`, `extension_count` 0, `criteria_failures` empty, `metric_lines`/`promotion_score`/`labeled_prediction_count` null) — experiments.py:91-110
- §3.7 insert/ambiguity — `ERR_INVALID_METRIC_SET` owns the degenerate shapes and the endpoint's exact field-validation sequence, hence precedence over `ERR_INVALID_REQUEST` on `expected_model_version` and over `ERR_INVALID_INTERVAL`; both maps persisted verbatim — experiments.py:25-42, 55-67
- §3.7 revise/**mismatch** — real precedence of the four business gates: `ERR_ACTIVE_EVALUATION_EXISTS` -> `ERR_CHALLENGER_NOT_SHADOW` -> `ERR_MODEL_ARCHIVED` -> `ERR_SAMPLE_BUDGET_EXCEEDED` — experiments.py:78-89
- §3.7 insert/ambiguity — which transitions bump the challenger version row: scheduling, extending, a non-promoted conclusion and the drain do; starting and promotion do not — experiments.py:108-110, 163, 223, 233
- §3.7 insert/ambiguity — negative-zero normalisation applies to each `metric_lines` entry as well as to `promotion_score` — calc.py:259-263
- §3.7 insert/ambiguity — per-branch `version` bookkeeping on conclusion — experiments.py:218-233
- §3.7 insert/ambiguity — the extension block is keyed on the exact string `DEPLOYMENT_DRAINED`, so a `DEPLOYMENT_ROLLED_BACK` inconclusive can extend; neither arm's liveness is re-examined — experiments.py:238-256
- §3.7 insert/ambiguity — extension leaves `labeled_prediction_count` in place, pushes `evaluation_ends_at` 7 days from its previous value (not from the clock), adds 500 samples, re-reserves — experiments.py:256-269
- §3.7 revise/**mismatch** — the system-driven drain is reached from exactly three places (snapshot revocation, rollback, revalidation failure); `RETIRE` leaves `COLLECTING` evaluations alone — cascades.py:147-182
- §3.7 insert/ambiguity — the drain key is the list's only member, added at most once, list held in ascending ASCII order — cascades.py:154-157
- §3.8 insert/ambiguity — the drift cascade's auto-raised incident always stamps `DRIFT`/`SEV2`/`drift_report_id` — cascades.py:266-280
- §3.8 insert/ambiguity — `note` and `override_traffic_pct` shape-checked under all five actions; only `MANUAL_OVERRIDE` requires and records the percentage; `note` recorded on no row and echoed in no response — experiments.py:346-350
- §3.8 revise/**mismatch** — gate order is `ERR_MANUAL_OVERRIDE_ACTIVE` -> `ERR_OVERRIDE_EXCEEDS_CURRENT_TRAFFIC` -> `ERR_DEPLOYMENT_NOT_SERVING`, reconciled with the §2.7 bands — experiments.py:380-385
- §3.8 insert/ambiguity — `MANUAL_OVERRIDE` ledger row's `step_index` (unread and unmoved), `health_state_at_step`, `clock_at_step` — experiments.py:396 via cascades.py:74-87
- §3.8 insert/ambiguity — the `OVERRIDE_RELEASE` row carries the same three fields; both rows retained as an audit trail while the cumulative telescopes back — experiments.py:442
- §3.8 revise/**mismatch** — resolution increments the deployment's `version` exactly once even when both the override release and the health step-down wrote to it; the cluster's `version` only when the release actually moved traffic — experiments.py:428-457
- §3.9 insert/ambiguity — the staleness pass runs *after* the revalidation-task pass and stales in `created_at` ascending order — experiments.py:559-602
- §3.9 insert/ambiguity — a `findings` string sent with `START_REVIEW` is shape-checked then discarded; only `PASS`/`FAIL` record it — experiments.py:494, 512-517, 521
- §3.9 insert/ambiguity — the FAIL cascade never writes to the snapshot row at all, and hop 3 drains in `created_at` ascending order — cascades.py:185-192, 298-300, 172

Handoff items 2 and 3 were resolved *without* over-claiming: `criteria_failures` was pinned as "added at most once, held in ascending ASCII order" rather than asserting an observable re-sort (a `COLLECTING` evaluation always carries an empty list, so `cascades.py:157`'s `sorted()` is unobservable at that call site); and the `whole_days_between` floor was pinned only via its observable consequence (the term is 0 whenever the count is not strictly positive), since `approved_at` is always <= the monotonic clock and the floor-vs-truncate distinction is unreachable.

Pass 3 deliberately left as-is (already determinate, or the distinction is unobservable): the ramp-planner and health-score prose, the skew tie-break to the lexicographically smallest feature name, the hop3/hop4 interleaving inside `drain_deployments_for_version`, a breached report staying at `version` 1, and concluding an evaluation whose registry entry has since been archived.

### Orchestrator final verification

- `PRD_COMPLETED.md` is **579 lines / 161,239 chars** and is **NOT** byte-identical to `PRD_FINALIZED.md` (128 changed line-sides) — so unlike the known failure mode, the scan demonstrably ran.
- Document intact: ends at `| \`ERR_NO_LABELED_PREDICTIONS\` | 422 |`, the genuine final row of the §5 table; 27 `#` headings, same as the source; no malformed §4/§5 table rows.
- Leak check: `grep -ic "scaffold|harder than expert|difficulty|pytest|test_suite"` -> **0 hits**. Neither the difficulty instruction nor any test/meta language reached the PRD.
- `find` over `implementation/`, `test_suite/` and `test_helpers/` for anything modified after the 07:17 green sweep -> **empty**. No Step 8 or Step 9 agent touched the code or the tests, so the verified 8/8 rounds at 116/116 remain valid for the final artifact; `results.{1..8}.json` on disk describe exactly the shipped implementation.

**Pipeline complete.** Step 9 has written `workspace/PRD_COMPLETED.md`.
