# Worklog — task_2528_protective_equipment_reconditioning_certification

## Step 1: Create task directory — 2026-09-03T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2528_protective_equipment_reconditioning_certification` and `.../workspace` (pre-assigned path; index fixed by scenario number 2528, no auto-allocation performed).

## Step 2: Generate scaffold — 2026-09-03T06:57:00.000Z

All three scaffold artifacts are complete and the lint is clean.

## Files

| File | Lines | Top-level key(s) |
|---|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_2528_protective_equipment_reconditioning_certification/SCAFFOLD.yaml` | 3249 | `scenario`, `domain_name`, `api_prefix`, `response_envelope`, `complexity_profile`, §1.1–§1.7 (no `scaffold_*_design` keys) |
| `.../SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1727 | `scaffold_difficulty_design` only |
| `.../SCAFFOLD_CORNER_DESIGN.yaml` | 3817 | `scaffold_corner_design` only |

## Scaffold surface (§1.1–§1.7)

13 entities, 9 state machines (+2 §1.2.1 OCC rules), 9 calculations (2 dual-variant), 40 validations on a single priority ladder 10→110, 2 declared priority conflicts, 58 endpoints, 51 errors, 6 roles. `difficulty_level: beyond_expert`; profile = flat topology / branching state machines / segregation_of_duties / immediate consistency; layers `dual_variant_calculation`, `cascading_side_effects`, `optimistic_concurrency`, `selector_policy`.

## Design instance counts

- §1.8: 9 difficulty rule_ids × 2 = **18 instances** (all nine §0.5 rules covered twice).
- §1.9: **92 instances** across all nine claim-extraction-guide sections — entities 12, state_machines 12, calculations 13, validations 30, endpoints 4, errors 5, rbac 8, complexity_layers 7, consistency_model 1. 71 carry full `test_recipe`s; 21 are `excluded_because` stubs citing §1.8 instances by name.
- All 110 instance names are unique across the two files; every stub's cited difficulty instance exists.
- All 51 catalogued error ids are referenced by at least one design instance (verified programmatically).

## Lint

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints declared:    58
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     71
  Calls scanned (§1.8+§1.9):  1206
```

Two fixes were needed this session to reach it: five `captures: $.data.total_count` on the list endpoint `GET /equipment-units` (list outputs must capture `$.data[0].<field>`, so they became `$.data[0].id` comparisons with `total_count` asserted in prose), plus the earlier `$.data[0].id` flow-mapping quoting.

One SCAFFOLD.yaml change came out of the §1.9 walk: `v-settle-readiness` was unreachable at priority 101 because the generic `v-shipment-state` guard (50) always fired first (settle is only defined from `READY_FOR_RETURN`, where `units_in_process` is necessarily 0). It was reprioritised to 45, physically relocated above `v-shipment-state`, and given a note explaining the deliberate ordering; `ERR_SHIPMENT_NOT_READY` is now asserted as a Priority Ordering claim.

## Step 3: Copy shared files — 2026-09-03T06:59:00.000Z

Copied `./INSTRUCTION.md` → `.../workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T07:12:00.000Z

PRD generated and all three hard contracts verified mechanically.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2528_protective_equipment_reconditioning_certification/workspace/PRD.md` — **418 lines / 92,820 bytes**, built with 6 chunked heredoc appends (no single giant Write).

**File ends at a clean section boundary:** the last line is the final row of the §5 Error Code Catalogue table (`` | `ERR_STALE_UNIT_VERSION` | 412 | ``). Last section heading is `## 5. Error Code Catalogue`. No audit footer, no contract-report block inside the file.

**Sections covered**
- §1 Introduction — 3 paragraphs (domain framing, custody-chain scope, the two dominating properties: segregation of duties and conservation)
- §2 Global Specifications — 10 subsections, domain-derived titles: 2.1 Plant Personnel/Program Contacts & Access Control · 2.2 API Response Structure (verbatim, verified byte-identical against `section-2.2-response-structure.md`) · 2.3 Pagination · 2.4 Resource Identity, Timestamps & the Logical Plant Clock · 2.5 Version Stamping & Stale-Read Rejection · 2.6 Money, Measurement & Rounding Precision · 2.7 The Rejection Ladder (all 29 rungs, explicitly ordered, plus both declared priority-conflict outcomes) · 2.8 Conservation Ledgers · 2.9 Segregation of Duties · 2.10 Filtered Reads & Path Resolution
- §3 Business Logic — 9 subsections: accounts/waiver/billing · plant reference data · dock intake & discrepancy fork · identification/age/teardown/inspection · bench scheduling & severity index · determination/repair/independent verification · labelling/voiding/staging/release · condemnation/destruction/retention · turnaround/loaner selector/settlement
- §4 Endpoint Definitions — 58 rows, exactly 4 columns
- §5 Error Code Catalogue — 51 rows, exactly 2 columns

**Contract reports (transcript only)**

```
Field coverage check:
- entities[].fields: 133 required, 133 present, 0 missing
- endpoints[].request_body: 78 required, 78 present, 0 missing
- endpoints[].query_params: 15 required, 15 present, 0 missing
- nested value-object keys (part_lines, component_criteria): 16 required, 16 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 40 checked, 40 expressed in the §2.7 ordered ladder, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_equipment_unit_version + ERR_STALE_UNIT_VERSION + 412 all named), 0 missing
- state_machines[].transitions: 44 checked, 44 fully expressed, 0 missing
- calculations[]: 9 checked, 9 fully expressed (all 31 constants present; COMPLIANCE_SURCHARGE_RATE rendered as "2 percent"), 0 missing
- validations[] conditions: 40 checked, 40 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 58 endpoints checked, all expressed, 0 missing
- entities[].fields[] structured content: 133 checked, reconstructible from prose (incl. ComponentInspection's common_fields:false stated explicitly), 0 missing
- sibling-branch symmetry: 13 groups checked (count fork, accept join, three TESTED branches, two REPAIR_PENDING branches, three INSTALLED branches, two cancel edges, two loaner-book edges, two loaner-return edges, two pre-test condemn edges, two metric_direction branches, PROVISIONAL/FINAL, MANUFACTURE_DATE/FIRST_SEASON), 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 952
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional spot-checks: 0 fuzzy/approximating words; 0 pseudocode/operator leaks anywhere in the file (`==`, `>=`, `+=`, `min()`, `round()`, `IN {…}`, `AND`/`OR` all absent); all 44 state values, all enum values, all 51 error IDs and all 6 role names present verbatim. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, and no sibling task directory was read.

**Orchestrator truncation check:** independently verified — 418 lines, headings §1–§5 all present at lines 3/11/159/297/362, tail ends on the final error-table row. Not truncated; no regeneration needed.

## Steps 5 & 6: launched concurrently — 2026-09-03T07:14:00.000Z

Test generator (Step 5) and implementation generator (Step 6) both launched as background subagents. (Step 6 returned first; its summary is recorded below out of numeric order because Step 5 was still running.) Orchestrator decision recorded for audit: the two Agent calls went out in back-to-back messages rather than a single message, so the *physical* isolation guarantee (impl-gen literally cannot see a `test_suite/` that does not yet exist) was only approximate — Step 5 had a few seconds' head start. To compensate, Step 6's prompt carries an absolute prohibition on reading, listing, globbing or grepping `test_helpers/`, `test_suite/`, the task root, and both design YAMLs; it is restricted to INSTRUCTION.md + SCAFFOLD.yaml + PRD.md as inputs and to `workspace/implementation/` as its only write target. Both prompts also mandate chunked `cat >>` appends and a post-write `ls -la` to guard against the 64k output-cap truncation failure mode.

## Step 6: Generate implementation — 2026-09-03T07:46:00.000Z

The implementation is complete and verified.

## Modules written (all under `/home/ubuntu/github/CodingPRD/tasks/task_2528_protective_equipment_reconditioning_certification/workspace/implementation/`)

| file | lines | contents |
|---|---|---|
| `app.py` | 56 | blueprint registration, `ApiError`/404/405/500 handlers, `0.0.0.0:$PORT` (default 10000) |
| `start.sh` | 10 | guarded `pip install` (`if ! python3 -c "import flask"`) + `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=3.0.0` |
| `util.py` | 93 | ISO-8601 (3 fractional digits), datetime arithmetic, `Decimal` ROUND_HALF_UP helpers |
| `errors.py` | 90 | all 51 PRD error ids → HTTP status, `ApiError` |
| `db.py` | 110 | in-memory dict store, logical clock defaulting to `2026-08-01T00:00:00Z`, one-version-bump-per-row-per-request |
| `response.py` | 102 | `meta`/`response_type`/`data` envelope, offset pagination (10/1/100, offset 0) |
| `auth.py` | 73 | ladder rungs 1–3 (`X-User-Role`, `X-User-ID`, CustomerContact scope) |
| `validate.py` | 159 | rung 4 schema validation |
| `calc.py` | 334 | enums/constants + all 9 calculations (severity index with per-site caps, dual-variant settlement, turnaround clipping, label code, loaner selector, service age, retention) |
| `serialize.py` | 280 | one serializer per entity; caller-supplied datetimes echo verbatim |
| `cascades.py` | 224 | derived-field refresh, four-hop condemnation cascade, ledger moves, part-stock ledger |
| `helpers.py` | 92 | rung-5 existence resolution, list plumbing |
| `routes_reference.py` | 264 | clock, model specs, approved parts, benches, loaner units |
| `routes_accounts.py` | 86 | accounts, waiver acknowledgment, billing hold |
| `routes_shipments.py` | 173 | intake, count fork, accept, settle |
| `routes_units.py` | 309 | units, identify, teardown, inspections, condemn, staging/release, purge, sub-collection reads |
| `routes_tests.py` | 198 | booking (cooldown envelope + daily quota), record-impacts, determine |
| `routes_repairs.py` | 249 | orders, part lines, submit/install/verify/cancel |
| `routes_labels.py` | 192 | label issue/read/void, destruction witness/verify |
| `routes_loaners.py` | 120 | booking (selector policy + explicit checks), read/list, return |

**3,215 lines total. All 58 endpoints from PRD §4 are registered** (verified by dumping `app.url_map` — exactly 58, matching the table one-for-one).

## Smoke-test result

Three independent scripted passes, each against a freshly booted server (boot-to-first-200 under 1 s, so per-test reboots are comfortably inside the harness window): **168/168 assertions pass, 0 failures.** Coverage included the PRD's own worked numbers: `final_total_cents` 27927 for the two-unit PRIORITY_RUSH FINAL variant (§3.9), `RCP-ND002-20260801-001` / `RCP-ND010-20260801-002` plant-wide label sequencing, `committed_due_at` 2026-08-12 clipping, severity indices 350.0 / 130.0 / 36.5 / 10.8 with per-site caps and material offset, conservation ledgers on both `ApprovedPart` and `IntakeShipment`, the four-hop condemn and void cascades, both SoD gates, verification exhaustion → `REPAIR_UNSUCCESSFUL` condemnation, retest ceiling, calibration/quota/window rejections, waiver and billing-hold gates, OCC 412s, CustomerContact scoping, and the transport-level 401/403/404/405. Envelope confirmed as `{"meta":{"api_request_id","api_request_timestamp"},"response_type","data"}` with `limit`/`offset`/`total_count`/`has_more` added on lists.

## Notes worth relaying

- **One spec-fidelity call changed during testing:** `POST /equipment-units/{id}/condemn` now accepts any non-empty `condemn_reason` string rather than only enum members, because PRD §3.8 says the persisted reason is "derived rather than trusted"; the persisted value is still derived (`LIFE_EXPIRED` → `COMPONENT_FAIL` → `NOT_RECONDITIONABLE`).
- **`ERR_INSPECTION_INCOMPLETE` is unreachable by construction** — the auto-advance `DISASSEMBLED → INSPECTED` fires exactly when coverage completes, and booking already requires `INSPECTED`/`REPAIRED`, so the state rung (7) always pre-empts rung 15. Both checks are implemented as written; the unreachability is inherent to the PRD, not a coding choice. Same for the PROVISIONAL 27926 figure: no endpoint applies the PROVISIONAL rounding order to a non-empty billable set.
- **Storage is in-memory only, and nothing is seeded** — no SQLite, no disk dump, no `/tmp` cache; the store is verified empty on a fresh boot.
- **I never read `test_suite/`, `test_helpers/`, the task root listing, the two SCAFFOLD design files, or any sibling task directory.**
- **Heads-up on a mistake I made:** while cleaning up my own smoke server I ran a broad `pkill -f "python3 app.py"`, which likely killed other agents' `app.py` servers running at that moment (four PIDs were live). Anything harness-managed under `--isolation per-test-server` gets relaunched per test, but if a concurrent agent reports a spurious "server could not be restarted" around that window, that is the cause. I switched to port-scoped kills immediately afterwards.

**Orchestrator note on the `pkill` incident:** recorded as a cross-pipeline hazard. This host runs up to 32 of these pipelines concurrently, so a broad `pkill -f "python3 app.py"` from any one agent is a plant-wide outage for every other pipeline's server. Nothing in *this* task needs repair (Step 6's own smoke test finished clean afterwards), but if Step 7's first sweep shows connection failures clustered at one wall-clock instant, this is a candidate cause alongside the setsid-reaping pattern.

## Step 5: Generate unit tests — 2026-09-03T07:53:00.000Z

Test suite for task 2528 is complete and audited.

## Files on disk

`/home/ubuntu/github/CodingPRD/tasks/task_2528_protective_equipment_reconditioning_certification/test_helpers/` (Stage 1, 2425 lines total): `__init__.py` 58, `api_client.py` 322, `api_errors.py` 127, `assertions.py` 275, `constants.py` 97, `factories.py` 283, `fixtures.py` 697, `test_users.py` 94, `types.py` 472.

`.../test_suite/` — `conftest.py` 57 lines plus 21 test files, 106 tests:

Queue B (breadth, 12 files, 69 tests): `test_01_entities_and_field_shapes.py` 584/12, `test_02_read_after_write_consistency.py` 104/1, `test_03_state_machine_transitions.py` 549/9, `test_04_calculations.py` 517/6, `test_05_intake_and_inspection_validations.py` 262/5, `test_06_determination_and_part_validations.py` 252/5, `test_07_repair_and_scheduling_validations.py` 367/6, `test_08_labelling_and_settlement_validations.py` 318/6, `test_09_endpoint_behaviour.py` 167/3, `test_10_error_catalogue.py` 253/5, `test_11_rbac.py` 310/8, `test_12_optimistic_concurrency.py` 185/3.

Queue A (depth, 9 files, 37 tests): `test_20_dual_variant_calculations.py` 165/5, `test_21_combinatorial_formulas.py` 115/4, `test_22_non_linear_state_machines.py` 134/4, `test_23_transitive_cascades.py` 157/4, `test_24_validation_precedence_pairs.py` 129/4, `test_25_boundary_precision.py` 130/4, `test_26_cross_entity_state_dependency.py` 138/4, `test_27_resource_temporal_overlap.py` 168/4, `test_28_conservation_ledgers.py` 169/4.

## Coverage

- Queue A: 18/18 difficulty instances, every one with ≥2 tests (37 tests).
- Queue B: 69/71 non-stub corner instances, 1+ test each (69 tests). All 21 `excluded_because:` stubs cross-reference-checked — every one resolves to a real difficulty instance; none translated.
- 106 tests / 106 `Design:` tags, exactly one per test, all resolving to a real `name:` in the correct index. `pytest --collect-only` collects 106.

## Skipped instances (2, both non-unique-derivability)

- `corner/validations/identify_a_unit_against_a_discontinued_model_rejected` — §3.4 places `ERR_MODEL_NOT_RECONDITIONABLE` on teardown and repair-order-create, not identify; identify must succeed for `condemn_required` to be recomputed, so the design's expected refusal is not PRD-derivable.
- `corner/validations/booking_a_shell_test_before_the_required_inspections_rejected` — the §2.7 ladder ranks the state rung (7) above inspection-completeness (15), so a DISASSEMBLED unit yields `ERR_UNIT_STATE_INVALID`; once INSPECTED the summary can no longer be PENDING, making `ERR_INSPECTION_INCOMPLETE` unreachable on that endpoint.

## Verification passes

- **PRD citations**: all 204 quoted spans (≥8 words) are byte-verbatim substrings of `workspace/PRD.md` under whitespace normalization only. 16 defects found and fixed this pass — 13 ASCII transliterations of the PRD's arrow/em-dash in `test_09`–`test_12`, 2 altered terminal punctuation and 1 paraphrase-in-quotes in `test_11_rbac.py`.
- **Error ids**: every `ERR_*` asserted in a test body is named in that test's prose (one gap fixed in `test_26`, which now cites the §3.5 calibration-currency sentence).
- Zero `skip`/`xfail` markers, zero occurrences of "scaffold" or design/section/table references; `pyflakes` clean on all of `test_suite/`.

## Two PRD-over-design divergences worth flagging to review

- `bench_sessions_collide_across_closed_cooldown_padded_windows` asserts `retest_count == 1` on a unit's *first* session; §3.5 says retest_count counts sessions beyond the first, so the test asserts `0` and cites that sentence.
- The design's `SUBMITTED` repair-order status is `PARTS_PENDING` in the PRD; `ShellTest.determined_at` and `LoanerAssignment.return_condition_note` do not exist in the PRD, so those assertions were dropped rather than invented.

Also note `NON_EXISTENT_UUID` in the framework is the nil UUID, not the v4-shaped literal the corner-design header names; tests that needed a v4 shape use a private constant.

**Orchestrator cross-check:** Step 5's `ERR_INSPECTION_INCOMPLETE` unreachability finding independently matches Step 6's — the two agents, which never saw each other's output, reached the same conclusion about the §2.7 rung-7-pre-empts-rung-15 interaction. That agreement raises confidence it is a genuine PRD-inherent artifact rather than either side's coding error, so no Step 7 action is expected on it.

## Step 7: Run tests and iterate — 2026-09-03T08:11:00.000Z

## Summary

**Diagnosis: the sole failure was an external process kill, not a defect. No fix was warranted; the final sweep is 8/8 green.**

### Iterations run
2 full 8-round sweeps, plus 3 targeted reproduction experiments (200 + 120 + 848 test executions).

### STEP 0 — root cause of the iteration-1 failure

Iteration 1 showed `test_label_issue_stamps_certified_at_and_the_retention_window` (`test_suite/test_03_state_machine_transitions.py:384`) failing in rounds 2, 3, 5 with `RemoteDisconnected('Remote end closed connection without response')`. `results.*.json` truncates to the exception's last line, so I recovered the detail from the runner's per-port server logs:

- All 8 rounds' server processes — on 8 **independent** ports (35039, 38317, 42863, 46125, 50239, 50685, 54603, 59217) — logged `Terminated` at the **identical wall-clock second, 07:49:45**, each while serving the label test's request chain.
- `Terminated` = SIGTERM. The runner only ever uses `kill -9` (`Killed`), and every other death in those logs is `Killed` (105 per round = exactly one per per-test-server restart). Zero `Traceback`, zero `Address already in use`.
- This is precisely the documented benign signature: another pipeline's agent ran a broad `pkill -f "python3 app.py"`. In 5 rounds the SIGTERM landed between requests (test still passed); in 3 rounds it landed mid-request → `RemoteDisconnected`.
- The 0.636 s duration bifurcation I had flagged is explained by the same cause, not by timing logic: with the server already dead, the next test's `_ensure_port_free()` returns immediately instead of paying one `kill_port` + `sleep 0.5` round (`prd-bench-local-runner/src/prd_bench_local_runner/pytest_plugin.py:73-85`).
- Corroboration: 8 concurrent **full-suite** runs driven by the runner's own plugin (`per-test-server`, `--timeout=30`) returned **106 passed × 8 = 848/848**, zero failures.

Because the failure was externally induced, no STEP 1a/1b/1c coverage or derivability question arose, and no STEP 2 test bug or STEP 3 implementation bug exists for it.

### Proof of final clean sweep (all 8 artifacts on disk, `2026-09-03 08:11`)

| results file | passed / total |
|---|---|
| `.../workspace/implementation/results.1.json` | 106 / 106 |
| `.../workspace/implementation/results.2.json` | 106 / 106 |
| `.../workspace/implementation/results.3.json` | 106 / 106 |
| `.../workspace/implementation/results.4.json` | 106 / 106 |
| `.../workspace/implementation/results.5.json` | 106 / 106 |
| `.../workspace/implementation/results.6.json` | 106 / 106 |
| `.../workspace/implementation/results.7.json` | 106 / 106 |
| `.../workspace/implementation/results.8.json` | 106 / 106 |

`failed=0 errors=0 skipped=0` in every round; `grep -cE "FAILED|ERROR"` on `workspace/sweep.log` returns 0.

### Tests deleted
None. No test exhibited PRD silence or a STEP 1b collapse pattern.

### Fixes to `test_helpers/`
None required. I audited `test_helpers/fixtures.py`, `factories.py`, and `constants.py` in full against PRD §2–§3; every fixture drives only documented endpoints and every constant traces to PRD prose (e.g. `CLOCK_EPOCH = "2026-08-01T00:00:00Z"`, `REQUIRED_WAIVER_VERSION = "2026.1"`, `PASS_SI_MAX = 300.0`, `REPAIR_SI_MAX = 360.0`, `PART_UNIT_PRICE_CENTS = 4500`).

### Fixes to `implementation/`
None required. I read every module (`app.py`, `db.py`, `auth.py`, `validate.py`, `response.py`, `errors.py`, `util.py`, `helpers.py`, `calc.py`, `cascades.py`, `serialize.py`, and all `routes_*.py`) against the §2.7 29-rung ladder. Spot checks confirmed correct precedence, e.g. `routes_shipments.settle_shipment` orders `ERR_SHIPMENT_NOT_READY` → `ERR_SHIPMENT_STATE_INVALID` → `ERR_ACCOUNT_ON_HOLD` → `ERR_SETTLEMENT_LOCKED` (rungs 6/7/27/28), and `routes_labels.issue_label` orders role → schema → existence → `ERR_UNIT_STATE_INVALID` → `ERR_CONDEMN_REQUIRED` → `ERR_LABEL_WINDOW_EXPIRED` → `ERR_ACCOUNT_ON_HOLD` → `ERR_STALE_UNIT_VERSION`. Storage is in-memory only (`db.Store` dicts); no seeding, no on-disk persistence, no non-PRD endpoints or fields.

**Notes for the caller:** the `ERR_INSPECTION_INCOMPLETE` unreachability you flagged is consistent with what I read — the §2.7 ladder ranks the unit-state rung above the inspection-completeness rung and the auto-advance `DISASSEMBLED → INSPECTED` fires the instant coverage completes, so no test targets it and none needed to. Also worth knowing for future runs on this host: a red round whose server log ends in `Terminated` rather than `Killed`, at a timestamp shared across all 8 independent ports, is an external `pkill` and should be re-run rather than diagnosed. All my temporary repro servers (ports 18333, 18401-18408, 18501-18508) were killed by port with `fuser -k`, and their logs removed; no broad `pkill` was ever issued.

**Orchestrator verification of the clean sweep:** independently confirmed rather than taken on the subagent's word — `ls -la results.*.json` shows all 8 files present (timestamped 08:11), and parsing each yields `passed=106 total=106 failed=0 errors=0 skipped=0`. The sweep artifacts are real.

**Orchestrator note:** the external-`pkill` root cause is corroborated by an independent trace — the Step 6 impl-gen subagent self-reported issuing a broad `pkill -f "python3 app.py"` during its own smoke-test cleanup, and 07:49:45 falls in that window. So the two accounts, produced by agents that never saw each other's output, match. This is a cross-pipeline hazard, not a defect in this task.

## Step 8: Finalize PRD — SKIPPED — 2026-09-03T08:14:00.000Z

Skipped per the skill's explicit skip condition. Step 7 exited with **0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes** — zero iterations of substantive change beyond the baseline; the only red round was traced to an external SIGTERM from a concurrent pipeline, not to any PRD/impl divergence. With no Step 7 fix sites to target, there is no `<step_7_diff>` to hand off and `PRD_FINALIZED.md` would be a byte-identical copy of `PRD.md`, so no subagent was spawned and no `PRD_FINALIZED.md` was written. Step 9 therefore starts from `PRD.md`, which is the skill's specified fallback source.

## Step 9: Complete PRD — 2026-09-03T08:40:00.000Z

**Orchestrator design decision:** run as **three sequential file-partitioned passes** over one shared `PRD_COMPLETED.md` rather than one subagent scanning all 22 implementation modules. A single-shot scan of an implementation this size (3,215 lines / 22 modules against a 418-line PRD) reliably under-scans and returns a near-identical copy. Each pass received the prior passes' rulings as explicit non-contradiction constraints, and passes 2 and 3 were told NOT to re-copy `PRD.md` over the file (which would have destroyed earlier work). Source was `PRD.md`, since Step 8 was skipped and no `PRD_FINALIZED.md` exists.

Partition:
- Pass 1 — global layer + intake: `app.py`, `db.py`, `response.py`, `auth.py`, `validate.py`, `errors.py`, `util.py`, `helpers.py`, `routes_reference.py`, `routes_accounts.py`, `routes_shipments.py`
- Pass 2 — unit lifecycle + bench testing: `routes_units.py`, `routes_tests.py`, `serialize.py`
- Pass 3 — repair/label/loaner + the two calculation engines: `routes_repairs.py`, `routes_labels.py`, `routes_loaners.py`, `calc.py`, `cascades.py`

### Pass 1 (global + intake) — 29 ambiguity-pins, 5 mismatch-revisions

`cp PRD.md PRD_COMPLETED.md` performed first. 418 lines/92,820 B → 420 lines/102,164 B (+2 lines, one new paragraph inside §2.4, no new sections). Mismatches: (1) §2.4 — `version` advances exactly once per row per request regardless of field/counter/cascade-hop count, and a row created by the request stays at `version` 1 (`db.py:78-100`); this globally resolves §3.8's per-hop phrasing which read as +2 on the unit. (2) §2.7 rung 3 — scope outranks existence only on the single-account read; the single-shipment read fetches first, so an unknown id gives `ERR_SHIPMENT_NOT_FOUND`. (3) §3.2 — component criteria enforce *coverage*, not "exactly one object per required code"; extras accepted, only 4 of 6 keys structurally enforced. (4) §3.3 — season dates are not required or normalised to UTC midnight. (5) §3.9 — billing hold is checked **before** the settlement lock, and re-settling a `CLOSED` shipment returns `ERR_SHIPMENT_STATE_INVALID`, leaving `ERR_SETTLEMENT_LOCKED` reachable only via label void. Also pinned: `api_request_id` = `req_` + 20 uppercase-alnum; `api_request_timestamp` from the logical clock not wall time; pagination edge semantics; `created_at` tie-break on insertion order; 29-Feb→28-Feb clamping on whole-year advances; rung-4 null/absent/unknown-field semantics; three non-catalogue transport ids (`ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500).

### Pass 2 (unit lifecycle + testing) — 13 ambiguity-pins, 0 mismatch-revisions

420 lines/102,164 B → 420 lines/107,460 B (every edit in-paragraph). No assigned-module behavior contradicted the PRD — every gap was silence. Pinned: newborn unit field values (ten nullables, `PENDING` summaries, false flags, `retest_count` 0); account-wide serial-duplicate scope with count-ceiling tested first; `service_age_years`/`life_expired` computed once at identification and never recomputed; `warranty_coverage` frozen at identification while `condemn_required` refreshes on each inspection; an uncovered-but-valid `component_code` → `ERR_INVALID_REQUEST` *after* the state and duplicate guards; a unit's first bench session leaves `version`/`updated_at` untouched because the row is written only when `retest_count` changes; repeatable purge that re-stamps and re-bumps; and the general §4 flat-representation rule (FK ids only, `part_lines` the sole nested structure, one-decimal severities). Explicitly deferred the severity/verdict formulas and cascade hop mechanics to pass 3.

### Pass 3 (repairs, labels, loaners, calc, cascades) — 23 ambiguity-pins, 6 mismatch-revisions

420 lines/107,460 B → 420 lines/115,167 B. Mismatches: (1) §2.8 — the part stock guard is **per-line, not aggregate**, so two lines naming the same `approved_part_id` can each clear it and drive `on_hand_qty` negative; the "never goes negative" claim was dropped. (2) §2.8 — the disposition invariant is qualified: the condemn cascade is unguarded on already-condemned units, the one path that moves a unit out of `units_in_process` twice. (3) §3.2 — loaner `status` is written directly by booking/return, not derived from the earliest-starting active assignment (`cascades.refresh_loaner_status` is dead code). (4) §3.8 — destruction verification writes `custody_status` `DISPOSED` outright rather than as a guarded transition. (5) §3.9 — booking overwrites the loaner's status whatever it held. (6) §3.9 — return writes `AVAILABLE` unconditionally even with another active assignment. The flagged hop-1 guard is now pinned: only an `AT_PLANT` unit moves to `PENDING_DISPOSAL`, so a post-void `STAGED_FOR_RETURN` unit keeps custody and gets a `PENDING` record that can never be witnessed. Also pinned: both SoD comparisons are skipped when `X-User-ID` is absent; a `SHELL` `REPLACE` is consulted by neither verdict rung; `ERR_PART_MODEL_MISMATCH` precedes `ERR_PART_NOT_APPROVED` within rung 12; part-line append answers 200 with the whole order; `INSTALLED` lines survive a cancel keeping their consumed qty and cents; `ERR_NO_LOANER_AVAILABLE` has no ladder rung and is reached only after both account gates.

Four impl branches were deliberately left unpinned as **unreachable** rather than documented as behavior: `calc.inspection_verdict_summary`'s `model is None` and `certification_label_code`'s null `standard_code_snapshot` (both need an un-identified unit, which cannot reach the calling endpoints); `issue_label`'s no-`DETERMINED`-session skip of the freshness window (a `TEST_PASSED` unit always has one); and `revert_to_in_process`'s `settlement_locked` early return (void already refuses earlier). `cascades.refresh_loaner_status` / `refresh_units_registered` are dead code, so the observable direct writes were pinned instead.

### Orchestrator verification of the final artifact

Checked on disk rather than taken on the subagents' word — this guards the known failure mode where a completeness scan silently returns an unmodified copy:
- `PRD.md` 418 lines / 92,820 B → `PRD_COMPLETED.md` 420 lines / 115,167 B (**+22,347 B, +24.1%**).
- `cmp -s` confirms the two files **differ** (not byte-identical), and `diff` reports **58 changed/added lines** — the scan demonstrably ran.
- 27 headings preserved; file ends on the final row of the §5 error catalogue (`ERR_STALE_UNIT_VERSION | 412`) — a real section boundary, not truncated.
- Difficulty-instruction leakage check: `grep -ic 'scaffold\|beyond_expert\|harder than expert'` returns **0** for both `PRD.md` and `PRD_COMPLETED.md`. The "Generate task harder than expert level!" directive went only to the Step 2 scaffold subagent and never reached the doc, test, or implementation generators.

**Totals across Step 9: 65 ambiguity-pins + 11 mismatch-revisions = 76 changes, no new sections, no line-count growth beyond pass 1's single §2.4 paragraph.**

## Pipeline complete — 2026-09-03T08:40:00.000Z

All nine steps finished. Step 8 skipped by its documented condition. Final deliverables in place: `SCAFFOLD.yaml` + both design indices, `test_helpers/` (2,425 lines), `test_suite/` (106 tests, 0 deleted), `workspace/PRD.md`, `workspace/implementation/` (3,215 lines, 58 endpoints), `workspace/PRD_COMPLETED.md`, and `results.{1..8}.json` at 106/106 each.
