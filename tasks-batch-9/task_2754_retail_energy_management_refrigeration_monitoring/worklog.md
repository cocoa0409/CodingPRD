# Worklog — task_2754_retail_energy_management_refrigeration_monitoring

## Step 1: Create task directory — 2026-09-04T16:40:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2754_retail_energy_management_refrigeration_monitoring` and its `workspace/` subdirectory. Index 2754 was pre-assigned by the orchestrator prompt; no scan of ./tasks/ was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-04T18:25:00.000Z

Subagent summary (verbatim):

All three scaffold artifacts are complete and the scaffold lint is clean.

**Output** (`/home/ubuntu/github/CodingPRD/tasks/task_2754_retail_energy_management_refrigeration_monitoring/`)

| File | Bytes |
|---|---|
| `SCAFFOLD.yaml` | 166,575 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 134,055 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 270,641 |

**§1.0–§1.7 surface** — domain `retail-energy-refrigeration-ops`, `api_prefix: /energy-ops`; 12 entities (Store, SetpointStandard, UtilityAccount, DemandInterval, UtilityBill, DemandResponseEvent, RefrigerationCase, TempExcursion, LightingOverride, FaultDiagnostic, MaintenanceWorkOrder, RetrofitProject); 54 endpoints (20 GET / 34 POST); 12 calculation rules; 50 ordered validations; 50 error codes; 7 roles (`role_model: segregation_of_duties`, two `entity_backed:Store` roles); 2 §1.2.1 OCC rules; `entity_topology: hybrid`, `consistency_model: immediate`, layers `optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, scheduled_actions`.

**§1.8 difficulty design** — all 9 rule ids, 23 instances: `dual_variant_calc` 2, `combinatorial_formula` 2, `non_linear_state_machine` 3, `transitive_cascade` 3, `priority_pair_validation_conflict` 3, `boundary_precision_check` 3, `cross_entity_state_dependency` 2, `resource_temporal_overlap` 3, `compensating_invariant` 2.

**§1.9 corner design** — all 9 sections, 72 instances (59 with full `test_recipe`, 13 `excluded_because` stubs): entities 12, state_machines 11, calculations 11, validations 10, endpoints 6, errors 9, rbac 6, cross_cutting_complexity_layers 6, consistency_model 1.

**Verification**
- `scaffold_lint.py`: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (767 calls scanned across 23 + 59 instances). Two violations found on first run were fixed: a system-field injection payload moved from a structured call into the assert prose, and a literal `expected_store_version: "1"` replaced with a captured `${store_v1}`.
- No duplicate `name` across both design files; every stub's `difficulty_instance` resolves to a real §1.8 name and no stub carries a `test_recipe`; all 50 error codes are exercised somewhere in §1.8/§1.9; `SCAFFOLD.yaml` carries neither design key and each design file has exactly one top-level key.
- All numeric asserts were recomputed with Decimal/ROUND_HALF_UP (e.g. tariff comparison 58208.15 -> 698497.80 vs 703198.68 / +4700.88 / not recommended; cheaper candidate -144058.92 / recommended; M&V 85479.45 expected -> rate 0.8189; fault scores 50.0 suppression-refused vs 23.1 allowed, 100.0 cap). One inherited literal was wrong and is corrected: a MINOR/2/20.0 kW REFRIGERATION fault scores **39.2**, not 22.0.

One caveat for the parent: `SCAFFOLD.yaml`'s `scenario:` key still contains the verbatim first line "Generate task harder than expert level!" (kept because the instruction said use the description verbatim). That line is known to leak into PRD.md via the scenario key and should be stripped before Step 3.

**Orchestrator action after Step 2:** the difficulty directive line ("Generate task harder than expert level!") plus its blank line were deleted from `SCAFFOLD.yaml`'s `scenario:` block with `sed -i '2,3d'`. Verified 0 remaining occurrences of that string anywhere in the task dir, so it cannot reach PRD.md. All three scaffold files verified present.

## Step 3: Copy shared files — 2026-09-04T18:24:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes). Verified workspace/ survived Step 2 (known hazard: the scaffold subagent can wipe the task dir) — it did; scaffold files and worklog.md all intact.

## Step 4: Generate PRD — 2026-09-04T18:42:00.000Z

Subagent summary (verbatim):

PRD generation complete.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2754_retail_energy_management_refrigeration_monitoring/workspace/PRD.md`
**Size:** 429 lines / 99,511 bytes (written in 8 incremental `cat >>` heredoc appends plus 4 targeted edits — no single giant Write, so no 64k truncation).
**Tail:** ends at `| \`ERR_TARIFF_SWITCH_NOT_JUSTIFIED\` | 422 |`, the final row of the §5 table — a complete section, no audit footer, nothing mid-sentence.
**Difficulty-directive grep:** `grep -c "harder than expert"` -> **0**; a broader `grep -ci "difficulty|expert level|meta-instruction"` -> **0**.
**Withheld files:** neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced. Only `SCAFFOLD.yaml`, `SKILL.md`, `section-2.2-response-structure.md` and `example-prd.md` were read.

**Section list**
- §1 Introduction
- §2 Global Specifications & System-Wide Principles — 12 subsections: 2.1 Operator Identity and RBAC · 2.2 API Response Structure (fixed verbatim block) · 2.3 Pagination and List Ordering · 2.4 Resource Identity, Version Counters and Audit Timestamps · 2.5 The Logical Clock and Scheduled Actions · 2.6 Path Resolution Order for Nested Energy Resources · 2.7 Rejection Precedence (13-step ladder) · 2.8 Decimal Discipline for Money, Energy and Temperature · 2.9 Stale-View Protection on Store and Account Writes · 2.10 The Energy Posture Ladder and Food-Safety Primacy · 2.11 Segregation of Duties and Store-Scoped Authority · 2.12 Window Arithmetic
- §3 Business Logic & Workflows — 10 subsections: 3.1 Portfolio Onboarding and the Setpoint Standard Library · 3.2 BMS Commissioning and the Degradation Cycle · 3.3 Refrigeration Monitoring, Breach Runs and Excursion Escalation · 3.4 Food-Safety Documentation, Closure and Posture Release · 3.5 Lighting Control and the Monthly Override Allowance · 3.6 Utility Metering, Bill Validation and Dispute Settlement · 3.7 Rate Schedule Optimization and Tariff Switching · 3.8 Demand Response Participation and Settlement · 3.9 Fault Diagnostics, Triage and Maintenance Execution · 3.10 Capital Retrofits, Measured Savings and Portfolio Benchmarking
- §4 Endpoint Definitions — 54 rows (Method | Path | Description | Authorized Role(s)), preceded by the 201-on-create / 200-otherwise paragraph
- §5 Error Code Catalogue — 50 rows (Error ID | HTTP Status Code)

**Hard Contract verification (machine-checked against SCAFFOLD.yaml)**
- **Contract 1 — Field-Name Coverage: PASS.** All 167 `entities[].fields[].name` appear verbatim in backticks (0 missing) and all 104 distinct endpoint request/query/path identifiers appear verbatim (0 missing). The first automated pass flagged 3 genuine gaps — `utility_account_id` on `UtilityBill`, `DemandInterval` and `DemandResponseEvent` — which were fixed by naming the parent link in §3.6 and §3.8.
- **Contract 2 — Rule Coverage: PASS.** 12 state machines / 64 transitions all documented (either as explicit `A -> B` arrows or as prose covering multi-origin transitions and the derived posture ladder); one real gap found and fixed — DR `SCHEDULED -> NOTIFIED` was implied but never stated, now explicit. All 12 calculations documented with every `output_fields` entry in backticks and every named constant's value stated in prose (including both dual-variant pairs: coincident/anytime peak and simple-payback/risk-adjusted scoring, and `INTERVAL_HOURS` rendered as "a quarter of an hour"). Both `concurrency_rules` documented in §2.9 with their OCC fields and 412 errors. All 50 validation `error_id`s and all 7 roles appear verbatim.
- **Contract 3 — §3 Path Purity: PASS.** 927 backtick tokens inside §3; zero start with `/`, zero are bare or path-prefixed HTTP methods, zero bare method words appear in §3 prose, zero slash-paths in §3 prose, and the string `energy-ops` appears 0 times in §3. Every endpoint is reached by state-transition framing, role + action verb, or capability description.

**Scaffold inconsistencies resolved during writing:** (1) `SetpointStandard.revision` — entity rule ("predecessor revision + 1") preferred over the endpoint side-effect's flat "revision 1"; (2) `tariff_locked_until_iso` references an undefined `TARIFF_LOCK_DAYS` and no endpoint applies a scheduled switch, so the field's semantics were written without inventing a number.

**Orchestrator truncation audit (per the known doc-generator failure mode):** independently verified — `wc` reports 429 lines / 99,511 bytes; headings are exactly §1–§5; the §4 endpoint table has 54 rows and the §5 error table has 50 rows, matching the scaffold's declared counts; the file's last line is a complete table row terminating §5. Not truncated. `grep -ci "harder than expert"` -> 0 confirmed independently.

## Step 5: Generate unit tests — 2026-09-04T20:15:00.000Z

Subagent summary (verbatim):

Generation is complete. Both queues are fully translated and all three audit passes are clean.

## Output

`/home/ubuntu/github/CodingPRD/tasks/task_2754_retail_energy_management_refrigeration_monitoring/test_helpers/` (1,973 lines)
`__init__.py` 49 · `api_client.py` 338 · `api_errors.py` 113 · `assertions.py` 266 · `constants.py` 92 · `factories.py` 240 · `fixtures.py` 567 · `test_users.py` 84 · `types.py` 224

`/home/ubuntu/github/CodingPRD/tasks/task_2754_retail_energy_management_refrigeration_monitoring/test_suite/` (8,872 lines, 234 tests)

| file | tests | lines |
|---|---|---|
| conftest.py | 0 | 46 |
| test_01_bill_recompute_variants.py | 6 | 243 |
| test_02_retrofit_scoring_variants.py | 6 | 210 |
| test_03_demand_response_settlement.py | 5 | 186 |
| test_04_nonlinear_state_cycles.py | 9 | 337 |
| test_05_cascades.py | 10 | 399 |
| test_06_precedence_conflicts.py | 10 | 379 |
| test_07_boundary_precision.py | 9 | 367 |
| test_08_cross_entity_state.py | 6 | 271 |
| test_09_temporal_overlap.py | 9 | 332 |
| test_10_resource_representations.py | 23 | 756 |
| test_11_lifecycle_transitions.py | 22 | 738 |
| test_12_calculation_details.py | 22 | 797 |
| test_13_validation_gates.py | 20 | 681 |
| test_14_endpoint_contracts.py | 18 | 685 |
| test_15_error_conditions.py | 27 | 1025 |
| test_16_role_authority.py | 17 | 766 |
| test_17_concurrency_and_clock.py | 15 | 654 |

## Instance coverage

- **Queue A (§1.8 depth index): 23 / 23 instances -> 70 tests.** 9 rule_ids, no stubs; every instance carries at least 2 tests.
- **Queue B (§1.9 breadth index): 59 / 59 non-stub instances -> 164 tests.** entities 11, state_machines 9, calculations 7, validations 8, endpoints 6, errors 9, rbac 5, cross_cutting_complexity_layers 3, consistency_model 1. The 13 `excluded_because:` stubs were not translated, as specified.
- **SKIPPED instances: none.** Every non-stub instance passed the PRD-first two-condition filter (verbatim coverage + unique derivability), so there are no gaps to report.

## Audits

- **Completeness/tag audit:** 234 tests, every one with exactly one `Design:` line as the last line of its docstring; 0 untagged, 0 dual-tagged, 0 tags pointing at a non-existent or stubbed instance; 0 under-covered instances.
- **PRD-citation audit:** every test docstring quotes a PRD sentence that matches `workspace/PRD.md` byte-for-byte after whitespace normalisation. This pass found and I fixed two pre-existing paraphrases from earlier sessions — `test_06_precedence_conflicts.py` (rank 7 read "target" instead of "target resource") and `test_12_calculation_details.py` (a condensed DR-baseline sentence, now the verbatim two-pass PRD text).
- **Scaffold-citation audit:** no occurrence of "scaffold" or the design-index names anywhere in either output directory.
- `python3 -m compileall` clean; `pytest --collect-only` collects all 234 tests with no import or collection errors.

## Notes for the next step

- The two design YAMLs' prefixed ids (`str_...`, `ua_...`) were replaced with `NON_EXISTENT_UUID` throughout, per PRD 84 ("a server-minted UUID carrying no type prefix").
- Two places where a design recipe was not literally realisable were adapted without weakening the claim: the tariff-switch precedence test uses a mismatched version token of `99` on the second account (a fresh account is genuinely at version 1, so the recipe's "same stale token" could not be stale there), and it additionally asserts that the *correct* token on that account yields `ERR_TARIFF_SWITCH_NOT_JUSTIFIED` 422 — which is what actually proves rank 8 precedes rank 13.
- Boolean query filters are passed as the string `"true"` (matching the existing `outliers_only` usage) rather than Python `True`.
- `test_helpers/` and `test_suite/` are both at the task root; nothing was written inside `workspace/`, and `worklog.md`, `workspace/implementation/`, `PRD_FINALIZED.md` and `PRD_COMPLETED.md` were never read or touched. No `pkill` was ever run and no server was started.

**Orchestrator verification after Step 5:** `find workspace -type d -name 'test_*'` returns nothing — neither test directory drifted into `workspace/` (a known Step 5 hazard). `python3 -m pytest test_suite --collect-only -q` from the task root collects **234 tests** with no errors.

## Step 6: Generate implementation — 2026-09-04T20:15:30.000Z

Steps 5 and 6 were launched as concurrent background subagents so the implementation generator had no visibility into `test_suite/`. Step 6 returned first (at ~19:20Z); its summary is recorded here after Step 5's for readability of step order.

Subagent summary (verbatim):

Implementation complete. All 54 endpoints are live, smoke-tested end to end, and the server was launched/killed on an isolated port (18754, PID-targeted kill only).

## Output location
`/home/ubuntu/github/CodingPRD/tasks/task_2754_retail_energy_management_refrigeration_monitoring/workspace/implementation/`

## Modules (3,449 lines total, Python 3 + Flask)
| File | Lines | Role |
|---|---|---|
`app.py` | 78 | 11 blueprints under `/energy-ops`, ApiError/404/405/500 envelope handlers, `0.0.0.0:$PORT` |
`start.sh` / `requirements.txt` | 8 / 1 | guarded `pip install`, `exec python3 app.py` |
`errors.py` | 67 | 50-entry error catalogue with HTTP statuses |
`util.py` | 165 | Decimal ROUND_HALF_UP helpers, ISO parse/format (3 fractional digits), custom JSON emitter so Decimals print as exact literals |
`db.py` | 68 | in-memory dicts (12 buckets), logical clock, row factories |
`envelope.py` | 50 | §2.2 success/list/error envelopes |
`validate.py` | 211 | §2.7 step-3 schema layer (`parse_float=Decimal` so declared decimal places are enforced on the literal sent) |
`security.py` | 56 | 7 roles, 401/403 gate, store-scope check |
`derive.py` | 179 | reachability paths + every derived counter/ledger |
`calc.py` | 464 | all 13 calculation rules + constants |
`cascade.py` | 107 | idempotent version `touch`, posture ladder, 3 cascade links |
`serial.py` | 284 | 12 serializers with §2.8 precision |
`common.py` | 122 | 30+ enum vocabularies, 11 existence resolvers, pagination |
`routes_stores/standards/accounts/bills/dr/cases/excursions/overrides/faults/retrofits/misc.py` | 113–225 each | the 54 endpoints |

## Coverage
- **Endpoints: 54 / 54** — verified by dumping the URL map; the set matches the §4 table exactly (path, method and role list).
- **Calculations: all 13** — dual-variant `period_peak_demand` (COINCIDENT/ANYTIME + 80% ratchet floor), 10-step bill recompute + variance, DR baseline (recency->severity two-pass), DR settlement (per-interval rounding), posture ladder, exposure ladder, 7-step fault score, override projection, dual-variant retrofit priority (SIMPLE_PAYBACK / RISK_ADJUSTED with capped fault-density bonus), M&V climate-adjusted realization, EUI benchmark with subject-excluded peer median, tariff-switch projection.
- **State machines: all** — `bms_status` cycle, `standard.status` supersession chain, `validation_state`, parallel `event_state` x `settlement_state`, `monitoring_state`, `excursion.state` (incl. cyclic ACKNOWLEDGED->OPEN), `override.state` (+ clock sweep), `fault.state`, `work_order.state`, `retrofit.state` (branching APPROVED->VERIFIED|SHORTFALL_REVIEW).
- Rejection precedence follows §2.7 globally (schema before existence, SoD before state, state before stale-version, stale before food-safety, food-safety before referential).
- Storage is in-memory dicts only; no seeding, no file/DB persistence (audited: the only `json` use is response serialization).

## Smoke-test results (port 18754, all green)
Store register -> standard draft/publish -> commission (v-check) -> activate; case register; readings 41.0 -> 43.5 (excursion OPEN, case ALARM, store CONSTRAINED) -> +2h (exposure 120 -> ESCALATED -> store **LOCKED**); cross-store gateway reading -> 403 `ERR_STORE_SCOPE_VIOLATION`; override on locked store -> 409 `ERR_FOOD_SAFETY_HOLD`; document + close -> posture released; 37.5 kW x 8 h = **300.00 kWh** projection, second request -> 422 `ERR_OVERRIDE_BUDGET_EXCEEDED`, 13 h window -> 400; bill recompute reproduced 100750.00 / 19002.25 / 4490.71 / 1563.64 / **125806.60**, variance -18.53 -> VARIANCE_FLAGGED; dispute; adjustment by recomputer -> 403 SoD, by another -> ADJUSTED; DR conflict inside the 240-min recovery gap -> 409; notify baseline **1292.00** (1310.5/1290.5/1275.0 mean); early activate -> 422; clock sweep completed 1 event, expired 1 override, recomputed 1 store, and reported all-zero counters on the identical second call; settle 194.50 kWh / 97.3% / 81.69 USD with the account ledger matching, then reverse-settlement; fault MAJOR/6th/20.0 kW REFRIGERATION -> **89.3**, triage -> URGENT work order + store DEGRADED/CONSTRAINED, schedule, complete -> fault RESOLVED; retrofit propose **58.0** -> approve by proposer 403 -> approve **50.6** -> 30-day M&V 422 -> 90-day verify -> revoke-verification; benchmark report; envelope/meta shape, `req_`-prefixed ids, 3-digit timestamps, pagination meta, 401 without headers, 403 wrong role, 404 unknown store.

Two judgement calls worth flagging: retrofit escalation fires only on a posture *raise* to CONSTRAINED/LOCKED (matches the scaffold state-machine side effects, which attach it to `posture_raise_constrained`/`_locked` but not `_curtailed`), and the benchmark report's `stores` array contains only peer-group members (non-null EUI), per the scaffold's "for every store of the requested peer group".

## Step 7: Run tests and iterate — 2026-09-04T20:52:00.000Z

Subagent summary (verbatim):

Green across all 8 parallel rounds. Summary below.

## Iterations run
**2.** Iteration 1: 230/234 in every round — 4 deterministic failures, zero flakiness (identical failing set in all 8 rounds, so no load-induced noise to re-run). Iteration 2: 234/234 in all 8 rounds.

## Tests deleted
**None.** No failing test turned out to rest on a PRD-silent rule; all four traced to real defects in either the test artifact or the implementation.

## Assertions removed under STEP 1c (partial coverage)
- `test_suite/test_15_error_conditions.py` — `test_the_two_legal_edges_reset_the_breach_counter`: dropped the bolt-on assertion that `target_state: "ALARM"` yields `ERR_INVALID_REQUEST`. Failed **unique derivability**: PRD names only `BYPASSED` and `ARMED` as `target_state` values but never declares that enum's domain, so one reader gets `ERR_INVALID_REQUEST` at precedence level 3 (undeclared enum member) while another reasonably lets `target_state` range over `monitoring_state` and refuses at level 7 with `ERR_CASE_STATE_INVALID` — which is what the implementation does. The test's titular assertions (both legal edges reset `consecutive_breach_count` to zero) are verbatim-covered and kept.

## Fixes applied to `test_suite/`
- `test_10_resource_representations.py` — `test_the_owning_store_is_taken_from_the_creation_path`: the test injected a body `store_id` through `fx.create_case(api, store_id, **overrides)`, colliding with that helper's positional parameter (`TypeError: got multiple values for argument 'store_id'`). Now calls `api.create_refrigeration_case` directly with the factory payload plus the injected key, matching the pattern the sibling `test_client_supplied_system_keys_are_ignored_at_creation` already uses. Pure test bug — the test could never reach the server.
- `test_17_concurrency_and_clock.py` — renamed `test_the_current_token_re_standardises_and_then_goes_stale_itself` -> `..._and_the_replay_hits_the_state_gate`: it asserted `ERR_STALE_STORE_VERSION` on a replay against a store left mid-commissioning, contradicting a verbatim §2.7 sentence — "State admissibility outranks stale-view protection, so a commissioning attempt against a store already mid-commissioning is reported as `ERR_BMS_STATE_INVALID` even when the supplied version is also stale." Now asserts `ERR_BMS_STATE_INVALID`/409 with that sentence quoted in the docstring. Still an exact error_id assertion, just the one PRD mandates; the genuine stale-token path stays covered by the sibling test that exercises it from `ACTIVE`.
- `test_12_calculation_details.py` — `test_a_received_bill_leaves_its_store_out_of_the_peer_group`: `len(report["stores"]) == 3` -> `== 4`. The test was self-contradictory (4 marine stores, yet it demanded a row for the null-intensity 4th while capping the list at 3), so it could not pass under any implementation.

## Fixes applied to `implementation/`
- `routes_misc.py` — `benchmark_report()`: the row loop iterated the peer group, which is filtered to non-null intensities, so a store with no qualifying bill got no row at all. Split into `scope` (all stores of the requested `climate_zone`+`store_format`, used for the reported rows and `outlier_count`) and `group` (non-null intensities only, used for `peer_group_count` and `peer_group_median_eui`). PRD §3.10 states verbatim "A store with a null intensity has a null percentile and a false flag", which presupposes a reported row, while "a store with a null intensity is in nobody's peer group, not even its own group's count" keeps it out of the count. `calc.benchmark_for_store` already returned the correct all-null figure set for such a store, so no calc change was needed.

## Final sweep evidence
`results.1..8.json` on disk in `workspace/implementation/` (timestamped 20:40), each **234 / 234**, `failed: 0`, `errors: 0`.

One note for the record: no implementation check was weakened anywhere. The only implementation change *added* rows to a report; the two error-code discrepancies both resolved in the implementation's favour, since §2.7's precedence ladder and its worked examples backed the server over the test in each case.

**Orchestrator verification after Step 7:** independently re-read all eight `workspace/implementation/results.*.json` — every round reports `passed 234 / total 234, failed 0, errors 0`. The sweep artifacts are on disk, so this is not an unsubstantiated clean-sweep claim. Step 7 applied 1 `implementation/` fix, so Step 8 is NOT skipped.

## Step 8: Finalize PRD — 2026-09-04T20:56:00.000Z

Subagent summary (verbatim):

Done. Summary below.

## Line counts
- `PRD.md`: 429 lines / 99,511 bytes
- `PRD_FINALIZED.md`: 429 lines / 101,264 bytes (3 lines revised, 0 added/removed; **+1.76% by bytes, 0.0% by lines**)

## Changes (one bullet each)
- **§3.10 (Benchmarking, line 311) — revise — the report's row scope, row ordering, the null-intensity row's remaining two figures, and what `outliers_only` does *not* change** — traced to the Step 7 `implementation/routes_misc.py` fix (`scope` vs `group` split) and the `test_12` `len(stores) == 4` correction. Added: rows cover every store of the requested `climate_zone`+`store_format` whether its intensity is null or not, ordered by `created_at` ascending; a null-intensity row carries null `peer_median_eui` and null `outlier_threshold_eui` too; `outliers_only` narrows only the row list, leaving `peer_group_count`, `peer_group_median_eui` and `outlier_count` unchanged, with `outlier_count` counting flagged stores across the whole scope rather than the returned rows — `implementation/routes_misc.py:25-61`, `implementation/calc.py:354-364`.
- **§3.3 (monitoring-state, line 203) — revise — declares the `target_state` enum domain and where an `ALARM` target is refused** — traced to the STEP 1c assertion removal in `test_15_error_conditions.py`. Added: `target_state` is declared over `ARMED`/`ALARM`/`BYPASSED`, so anything outside those is `ERR_INVALID_REQUEST` at the schema level, while `ALARM` passes the schema and, on a case that resolves, is always refused `ERR_CASE_STATE_INVALID` — `implementation/routes_cases.py:194,203-204`, `implementation/common.py:24`.
- **§2.4 (Resource identity, line 84) — insert — client-supplied server-owned keys and nested parent-reference keys are ignored, not rejected** — traced to the `test_10_resource_representations.py` fix (`test_the_owning_store_is_taken_from_the_creation_path`). Added: a body carrying `id`/`created_at`/`updated_at`/`version` or any other server-owned or derived field is not rejected for it; `store_id`, `utility_account_id`, `case_id`, `fault_id` always come from the resolved path; genuine body references (`standard_id`, `supersedes_standard_id`) are explicitly exempted — `implementation/db.py:44-53`, `implementation/routes_cases.py:47`, `implementation/routes_stores.py:59-73`.

## Per-edit pre-edit search log
**Edit 1 — §3.10**
- (a) Subject: which stores become benchmark-report rows, their order, the aggregate counters, and the field set of a null-intensity row.
- (b) Enumerated/read: `routes_misc.benchmark_report` (scope/group/rows/`outlier_count`/`peer_group_count`/`peer_group_median_eui`, `outliers_only` `continue` placement), `calc.benchmark_for_store` (all three branches: null-intensity, no-other-peers, normal), `calc.peer_group_members`, `calc.store_eui` + `calc.qualifying_bills`, `calc._median`, `derive._by_created` (tie-break `(created_at, _seq)`), and the two parallel consumers of the same figures off the Step 7 site: `serial.store` (`_eui_map`, lines 25-42) and `routes_stores.list_stores`' `benchmark_outlier_flag` filter (lines 86-98).
- (c) Adjustment: first draft said the three aggregates "are computed over the whole scope either way", which would have implied null-intensity stores count toward `peer_group_count`/`peer_group_median_eui` and contradicted the verbatim "in nobody's peer group, not even its own group's count" plus `calc.peer_group_members`' non-null filter. Reworded to "are unchanged by it". Also deliberately said nothing about pagination, since this endpoint returns `envelope.ok` (an object, no `limit`/`offset`), and nothing about the no-other-peers branch's null median/threshold, which is off the Step 7 site.

**Edit 2 — §3.3**
- (a) Subject: the `target_state` field's declared domain and the precedence level at which an `ALARM` target fails.
- (b) Enumerated/grepped: `grep -rn MONITORING_STATES` -> `common.py:24` (vocabulary), `routes_cases.py:194` (the only `target_state` consumer), `routes_stores.py:127` (the `monitoring_state` list filter, which shares the vocabulary); `validate.get_enum` (raises `ERR_INVALID_REQUEST`, §2.7 level 3) and the ordering `get_enum` -> `common.get_case` (404, level 4) -> the four state branches in `set_monitoring_state:197-204`; also confirmed all four branches emit the same `ERR_CASE_STATE_INVALID`, so branch order is behaviorally invisible.
- (c) Adjustment: dropped an unconditional "is always refused with `ERR_CASE_STATE_INVALID`" in favour of "on a case that resolves, ... whatever the case's current state", so the sentence cannot be read as outranking the level-4 `ERR_CASE_NOT_FOUND` check on an unknown case id.

**Edit 3 — §2.4**
- (a) Subject: what the server does with body keys it does not read — server-owned/derived fields and nested parent references.
- (b) Enumerated/grepped: `validate.body()` (parses to a dict, no key whitelist or strictness), `grep -rn "unknown|unexpected|set(body|keys()"` across `implementation/*.py` (only `app.py`'s 500 handler — no strict-key rejection anywhere), `db.new_row`/`new_event_row` (server mints `id`/`created_at`/`updated_at`/`version`/`_seq`), `grep -n '"store_id": |"utility_account_id": |"case_id": |"fault_id": '` across all `routes_*.py` (every parent reference sourced from the path variable or parent row: `routes_accounts:46`, `routes_bills:36`, `routes_cases:47,142,171`, `routes_dr:50`, `routes_faults:39,98,114`, `routes_overrides:57`, `routes_retrofits:31`), plus `grep -rn 'body, "[a-z_]*_id"'` to find the *legitimate* body id inputs (`routes_stores.py:192` `standard_id`, `routes_standards.py:30` `supersedes_standard_id`), and `routes_stores.create_store` for the injected-`bms_status`/`active_standard_id` case.
- (c) Adjustment: the first draft's "a parent reference such as `store_id` ... is ignored" would have mis-described `standard_id` and `supersedes_standard_id`, which *are* read from the body; narrowed the claim to the four specific parent-linking fields and added the explicit parenthetical exemption for genuine body references.

**No edit (deliberate)** — the `test_17_concurrency_and_clock.py` rename: `routes_stores.commission_bms:196-201` orders state -> stale -> food-safety -> referential exactly as §2.7's verbatim worked example already mandates, so the PRD text was kept byte-identical.

**Orchestrator verification after Step 8:** `PRD_FINALIZED.md` exists (101,264 bytes), is NOT byte-identical to `PRD.md` (6 diff lines = 3 revised lines), and still terminates at the complete §5 error table — not truncated.

## Step 9: Complete PRD — 2026-09-04T21:32:00.000Z

Step 9 was executed as **three sequential passes partitioned by implementation module**, because a single-pass scan over a 23-module / 3,449-line implementation reliably degenerates into a byte-identical no-op. Pass 1 did the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 edited the same file in place with the Edit tool only. Net effect: 429 lines / 101,264 chars -> 437 lines / 123,450 chars, **+22,186 chars (+21.9%)**, 45 ambiguity-pins and 9 mismatch-revisions.

### Pass 1 — cross-cutting core (app, envelope, util, errors, validate, security, db, common, derive, cascade, serial)

Subagent summary (verbatim):

Pass 1 complete. PRD_COMPLETED.md is intact (ends at the full 50-row §5 table).

**Setup:** `cp workspace/PRD_FINALIZED.md workspace/PRD_COMPLETED.md` done as the first action.

**Line/char counts:** PRD_FINALIZED.md 429 lines / 101,264 chars -> PRD_COMPLETED.md 437 lines / 111,801 chars (+8 lines, +10,537 chars). 50 error rows, 54 endpoint rows, 30 headings all preserved.

**Counts:** 14 ambiguity-pins, 4 mismatch-revisions.

**Changes**
- §2.1 — insert — ambiguity — missing/empty/unrecognised `X-User-Role` -> `ERR_UNAUTHORIZED` (not 401/400); auth guard precedes path-identifier resolution; endpoint-table matching precedes even that — security.py:41-43
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars from A-Z/0-9 (24 total) — util.py:112-113
- §2.2 — insert — ambiguity — `api_request_timestamp` is read from the logical clock, not wall time, so it repeats between clock moves — envelope.py:17
- §2.2 — revise — mismatch — error envelope covers the 5xx response too, not "4xx status codes" alone — app.py:63-68
- §2.3 — insert — ambiguity — `limit`/`offset` accept only canonical decimal spelling (leading `+`, `010`, `10.0`, exponent, empty all rejected); non-member filter values and non-`true`/`false` boolean filters are `ERR_INVALID_REQUEST`; identifier filters are opaque strings, never resolved — validate.py:157-211
- §2.3 — insert — ambiguity — **`created_at` ties break by insertion order**; load-bearing because the logical clock rarely moves, so most rows share a `created_at` — db.py:66-68, derive.py:11-12
- §2.3 — insert — ambiguity — `offset` at/beyond `total_count` yields an empty `data` array, not an error — common.py:110-111
- §2.3 — revise — mismatch — "single-resource **reads**" -> all single-resource responses (creations and action responses included) omit the four pagination meta keys — envelope.py:25-31
- §2.4 — insert — ambiguity — exact emission grammar `YYYY-MM-DDTHH:MM:SS.mmmZ` with sub-millisecond precision **discarded, not rounded**; new row's `updated_at` equals its `created_at` — util.py:71-78
- §2.4 — insert — ambiguity — `version` advances **at most once per request** however many effects touch the row (verified: every bump in the codebase goes through `cascade.touch`) — cascade.py:21-30
- §2.5 — insert — ambiguity — data store starts completely empty; nothing seeded — db.py:17-31
- §2.7 item 3 — insert — ambiguity — body form (empty->`{}`; non-object/unparseable->400; endpoints declaring no body never inspect it); JSON `null` == omitted; no type coercion; integer fields accept zero-fraction decimals (`60.0`); **decimal-place limit measured on the literal as transmitted, so `12.340` fails a 2-place field**; exact ISO grammar (1-9 fractional digits, only first six retained) — validate.py:23-148
- §2.8 — revise — mismatch — `baseline_kw` is the one 2-dp exception to "demand values in kW carry one decimal place" — serial.py:150
- §2.8 — insert — ambiguity — JSON renders a field at its declared fractional width with trailing zeros (`12.30`, `0.1100`); whole-number fields as bare integers; null != zero — util.py:121-165
- §2.10 — revise — **mismatch** — cascade trigger is *any posture raise*, not "any transition out of `NORMAL`" (so `CONSTRAINED`->`CURTAILED` revokes too); an unchanged recomputation is fully inert; a *fall* writes the value but fires nothing; a reported escalated-retrofit count covers only newly-flipped projects — cascade.py:84-107
- §3.1 — insert — ambiguity — `lighting_*_time_local` grammar `HH:MM` or `HH:MM:SS`, stored and echoed verbatim (not normalised) — common.py:44
- §4 preamble — insert — ambiguity — trailing slash insignificant — app.py:44
- §5 preamble — insert — ambiguity — `ERR_NOT_FOUND` (404, unmatched path), `ERR_METHOD_NOT_ALLOWED` (405), `ERR_INTERNAL` (500) sit outside the 50-row catalogue but use the same envelope; table left at exactly 50 rows — app.py:53-68

**Deliberately left alone**
- The 50-entry error catalogue: script-verified id-for-id, status-for-status, and even in identical order versus `errors.py`. No change.
- The 7 role names, §2.6's 404 family order, §2.11's four store-scoped operations and both duty-separation pairs, and §2.10's ladder rules: each verified against `security.py`/`common.py`/`calc.POSTURE_RANK` and already pinned uniquely.
- Every derived counter and ledger in `derive.py` (`alarm_case_count`, `urgent_work_order_count`, `override_kwh_used_month`, `verified_savings_kwh_ytd`, `portfolio_realization_rate`, `dr_optout_count`, `dr_incentive_accrued_usd`, `refrigeration_fault_density`): all already pinned exactly in §3.3/§3.5/§3.8/§3.9/§3.10.
- All 14 serializers: script-verified that all ~190 emitted field names already appear in the PRD; per-field precision widths cross-checked against §2.8 (only `baseline_kw` diverged).

**Flag for later passes:** `routes_misc.py:69` sets `db.clock = current_utc` unconditionally, so the clock can be moved *backwards*, while §2.5 says a `PlatformAdmin` "may move it forward". That's a route-owned rule, so I left it for pass 2/3.

### Pass 2 — calc.py + routes_stores / routes_standards / routes_accounts / routes_bills

Subagent summary (verbatim):

All 17 edit fragments landed and the document is structurally intact.

**In-place editing confirmed.** Every change was made with the `Edit` tool. No `cp`, no `Write`, no overwrite of `PRD_COMPLETED.md`; all of pass 1's wording is preserved.

**Line/char counts:** incoming 437 lines / 111,801 chars -> outgoing **437 lines / 118,852 chars** (+7,051 chars, +0 lines — every edit was in-paragraph). Integrity verified: **50 §5 error rows**, **54 §4 endpoint rows**, five `##` sections intact, file still ends at the complete §5 table (`ERR_TARIFF_SWITCH_NOT_JUSTIFIED | 422`).

**Counts: 14 ambiguity-pins, 2 mismatch-revisions** (16 subjects across 17 edit operations).

- **§3.1 store registration** — insert — ambiguity — duplicate `code` has no dedicated catalogue entry; it is refused with `ERR_INVALID_REQUEST` (400), compared exactly and case-sensitively — `routes_stores.py:56-58`
- **§3.1 standard drafting** — insert — ambiguity — `supersedes_standard_id` is resolved but its **scope is never compared** to the drafting standard's, so cross-scope supersession is legal and inherits `revision`+1; `revision` is not unique — `routes_standards.py:33-46`
- **§3.2 commissioning** — insert — **mismatch** — commissioning does **not** recompute `energy_posture`: a store `CONSTRAINED` solely by a `DEGRADED` BMS stays `CONSTRAINED` through `COMMISSIONING` and only falls at activation. Flagged as the single exception to §2.10's universal "recomputed at the end of every request that changes one of its inputs" — `routes_stores.py:207-210` vs `:222-224` (verified live: DEGRADED/CONSTRAINED -> COMMISSIONING/**CONSTRAINED** -> ACTIVE/NORMAL)
- **§3.6 account attachment** — insert — ambiguity — no uniqueness of any kind, so a store may hold many accounts; account-scoped vs store-scoped derivations delimited (store-level ones reach through *all* accounts); attachment is not BMS-gated — `routes_accounts.py:26-64`, `derive.py:58-83`
- **§3.6 account attachment** — insert — ambiguity — the five candidate fields are validated only individually; a candidate identical to the live tariff is accepted — `routes_accounts.py:38-43`
- **§3.6 account listing** — insert — ambiguity — `tariff_state` is declared over three members including `SWITCHED`, which no operation ever writes, so `?tariff_state=SWITCHED` is a valid query matching nothing rather than a 400 — `common.py:17`, `routes_stores.py:114`
- **§3.6 interval ingest** — insert — ambiguity — response is 201 with `data` = the whole array of created intervals in supplied order, `response_type` `object`, no pagination `meta`; the interval object's exact seven fields — `routes_accounts.py:156`, `envelope.py:26-32`
- **§3.6 bill recording** — insert — ambiguity — the period is never compared to the clock and carries no uniqueness/overlap rule; one account may hold many identical/overlapping-period bills, each competing to be reference/qualifying bill — `routes_bills.py:22-58`
- **§3.6 variance** — insert — ambiguity — when `recomputed_amount_usd` is exactly 0.00 no division is attempted, `variance_pct` is 0.00 and the bill lands `VALIDATED` — `routes_bills.py:80-88` (verified live)
- **§3.6 adjustment gate** — revise — ambiguity — "must be `STABLE`" softened to "must not be `PENDING_SWITCH`", matching the actual test and consistent with `SWITCHED` being unreachable — `routes_bills.py:120`
- **§3.7 reference bill** — insert — ambiguity — tie-break at equal `created_at` goes to the **later** creation order; descending single-row selections invert §2.3's earliest-first secondary key at every level; no trailing-window restriction applies — `calc.py:403-405`
- **§3.7 candidate substitution** — insert — ambiguity — only the four named fields are substituted; the candidate ratchet floor still uses the account's single `ratchet_peak_kw` and the reference bill's own half-open period — `calc.py:436-439`
- **§3.7 projection outputs** — insert — ambiguity — the two partial outcomes pinned: all-seven-null only with no reference bill (`switch_recommended` **null**); with a null candidate field -> `switch_recommended` **false**, candidate basis and demand null; with complete candidates but an empty eligible set -> basis **reported**, demand null; the read never raises `ERR_DEMAND_DATA_MISSING` — `calc.py:410-449` (all three verified live)
- **§3.7 tariff switch** — revise — ambiguity — `ERR_TARIFF_SWITCH_NOT_JUSTIFIED` also covers the empty-candidate-interval-set case — `routes_accounts.py:175-177`
- **§3.8 baseline recency pass** — insert — ambiguity — the descending recency pass breaks equal-`created_at` ties by the **later** creation order — `calc.py:148-152`
- **§3.9 fault-score example** — revise — **mismatch** — PRD said "the same severity **and load** on `HVAC` at its third occurrence scores 62.1"; 62.1 requires **30.0 kW**, not 20.0 kW (20.0 kW yields 59.4). Rewritten to name 30.0 kW and give 59.4 as the 20.0 kW contrast — `calc.py:243-260` (confirmed by direct invocation; the 89.3 example was already correct)
- **§3.10 sole-peer benchmark** — insert — ambiguity — with no other peers, `peer_median_eui` and `outlier_threshold_eui` are both **null** alongside the already-pinned false flag and 100.0 percentile — `calc.py:372-379` (verified live)

**Deliberately left alone**
- **`retrofit_simple_payback` / `retrofit_risk_adjusted` / `measured_savings` division-by-zero** (`calc.py:274`, `:287`, `:307`) — reachable at the extreme of the validated input ranges, confirmed to raise `decimal.DivisionByZero`, surfacing as an undeclared HTTP 500 `ERR_INTERNAL`. Left unpinned because writing a 500 into the PRD would enshrine a defect rather than resolve an ambiguity.
- Unreachable defensive branches (`tariff_projection`'s null-`recomputed_amount_usd` guard, `dr_settlement`'s null-`baseline_kw` and zero-target guards, `activate_bms`'s missing-standard guard) — no observable behavior to pin.
- The surcharge boundary at exactly 20000.00 — impl's `>=` and the PRD's "below ... otherwise" agree at 0.00; no divergence.
- The ascending `_seq` fourth sort key in `period_peak_demand` and `dr_settlement` — already covered by pass 1's §2.3 earliest-first wording.
- `exposure_ladder`, `breaches`, `breach_deviation`, `fault_score`'s seven steps, `compute_posture` — verified against §3.3/§3.9/§2.10 and already uniquely pinned.

**Cross-partition notes**
- **No contradiction found** between pass 1's new wording and my partition, with one qualification: §2.10's line "recomputed synchronously, at the end of every request that changes one of its inputs" is a genuine over-claim given BMS commissioning. Rather than editing §2.10 (pass 1's territory), I pinned the exception at the specific §3.2 site and cross-referenced §2.10 explicitly. I verified by grep + reading that commissioning is the **only** such site.
- Three of my edits sit in sections whose *routes* belong to pass 3 but whose *calculation rules* are explicitly mine: §3.8 baseline recency tie-break, §3.9 fault-score worked example, §3.10 sole-peer null median/threshold.

### Pass 3 — routes_dr / routes_cases / routes_excursions / routes_overrides / routes_faults / routes_retrofits / routes_misc

Subagent summary (verbatim):

Verification passes. Here is my report.

**No `cp`, no full-file `Write`.** All 18 changes were surgical `Edit` calls against the existing `workspace/PRD_COMPLETED.md`.

**Size:** incoming 437 lines / 118,852 chars -> outgoing 437 lines / 123,450 chars (**+4,598 chars**, line count unchanged — all edits were in-paragraph).

**Counts:** 17 ambiguity-pins, 3 mismatch-revisions.

- **§2.5** — revise — mismatch — "A `PlatformAdmin` **may move it forward**" -> "moves it", since the clock is written unconditionally — `routes_misc.py:69`
- **§2.5** — insert — ambiguity — the supplied instant is written unconditionally; an instant equal to or earlier than the present clock is accepted and the sweep runs against that earlier value (it can still complete/expire a row an earlier sweep missed), and nothing already advanced is moved back — `routes_misc.py:69-102`
- **§2.5** — insert — ambiguity — `stores_posture_recomputed` counts distinct stores recomputed, whether or not a posture actually changed — `routes_misc.py:104,112`
- **§2.7 step 3** — revise — mismatch — "**Two** domain limits are enforced at this level" -> **three**, adding a case whose `alarm_high_f` is not strictly above `alarm_low_f` (checked before store existence) — `routes_cases.py:39-40`
- **§3.3** — insert — ambiguity — duplicate `case_code` in a store is `ERR_INVALID_REQUEST`, checked *after* store resolution and the BMS gate — `routes_cases.py:43-45`
- **§3.3** — insert — ambiguity — `reading_iso` is validated only as an instant: not against the clock, not against the previous `last_reading_iso`; negative derived exposure floors at 0 — `routes_cases.py:105-111`, `util.py:85-90`
- **§3.3** — insert — ambiguity — the store's `version` advances on the excursion-opening reading (via `alarm_case_count`) even when the posture does not change — `routes_cases.py:160-161`
- **§3.3** — insert — mismatch — a computed `OPEN` rung never lowers an excursion already at `ESCALATED`/`DISPOSITION_REQUIRED` (PRD's "first match wins" implied demotion), while `mandatory_disposition` is always rewritten; and the ladder runs on the opening reading, so a >=2 h opening run is born `ESCALATED` and locks the store — `routes_cases.py:83-97,162`
- **§3.4** — insert — ambiguity — a rearm advances both case and store `version`; a closure leaving the case in `ALARM` advances neither, and only a real posture change moves the store — `routes_excursions.py:76-83`
- **§3.5** — insert — ambiguity — a wholly-past window is admitted and persisted `SCHEDULED` (charged, expired by the next clock set); creation and revocation each advance the store's `version` — `routes_overrides.py:55-69,84`
- **§3.8** — insert — ambiguity — the 240-minute recovery separation is symmetric (measured from whichever event ends first); a wholly elapsed curtailment window enrolls normally — `routes_dr.py:25-28`
- **§3.8** — insert — ambiguity — settlement advances the account's `version`; enroll/notify/activate leave it alone — `routes_dr.py:124`
- **§3.8** — insert — ambiguity — reversal advances the account's `version` too — `routes_dr.py:140`
- **§3.9** — insert — ambiguity — a `ROUTINE` triage leaves the store wholly untouched (`version` static); an `URGENT` one advances it — `routes_faults.py:106-111`
- **§3.9** — insert — ambiguity — `equipment_ref` conflict is matched **system-wide**, not per store — `routes_faults.py:141-149`
- **§3.9** — insert — ambiguity — completing an `URGENT` order advances the store's `version`; a `ROUTINE` one does not — `routes_faults.py:184-186`
- **§3.10** — insert — ambiguity — both M&V branches advance the store's `version`; proposal and approval do not — `routes_retrofits.py:113-114`
- **§3.10** — insert — ambiguity — revoke-verification advances the store's `version` — `routes_retrofits.py:129`
- **§3.10** — insert — ambiguity — `outliers_only` must be spelled exactly `true`/`false`, else `ERR_INVALID_REQUEST` — `routes_misc.py:23`, `validate.py:203-211`
- **§3.10** — insert — ambiguity — per-store rows sit under the response key **`stores`**; `peer_group_median_eui` is null when no group member has an intensity — `routes_misc.py:54-60`, `calc.py:337`

**The two handed-off items**
1. **Clock direction — confirmed no guard.** `routes_misc.py:69` assigns `db.clock = current_utc` with no comparison against the old value; `v.get_dt` only checks ISO form. So the clock is freely settable backwards. Pinned in §2.5 (two edits above), including that a backwards set still runs the same sweep and reverts nothing.
2. **Division-by-zero -> HTTP 500 — reachable through my routes; no PRD action taken.** Verified by direct call: `retrofit_simple_payback` raises `decimal.DivisionByZero` whenever `rhu(projected_annual_savings_kwh x blended_rate, 2) == 0.00` — e.g. `projected_annual_savings_kwh = 0.01` at the default 0.1100 rate, which the `gt=0`/2-dp validator admits — so `POST /stores/{id}/retrofit-projects` can 500. `measured_savings` likewise raises when `rhu(projected x mv_period_days / 365, 2) == 0.00` (e.g. projected 0.01, `mv_period_days` 60), so `submit-measurement` can 500. `retrofit_risk_adjusted` is effectively unreachable. `app.py:62-67` maps any unexpected exception to `ERR_INTERNAL`/500, which §5 already declares as an out-of-catalogue identifier — so nothing was enshrined.

**Deliberately left alone**
- §3.8 baseline recency tie-break, §3.9 fault-score worked example, §3.10 sole-peer null median/threshold — pass 2 already pinned them.
- §3.5 "when a store leaves `NORMAL`" (the `SCHEDULE_EXTEND` cascade) — loose in isolation, but §2.10 already pins the trigger as any **raise**.
- Re-documenting a disposition overwriting all four fields — §3.4's "records ... and stamps" already reads last-write-wins.
- A global "derived-field change touches the parent" rule in §2.4 — deliberately *not* added: it is false as a universal. Pinned per-narrative instead.
- `urgent_work_order_count` in the suppression triage response (current store count, not 0) — the field name determines it.

**Integrity check:** `437 123450 PRD_COMPLETED.md`; 5 `##` sections (1-5 in order); 50 §5 error rows; 54 §4 endpoint rows; tail is the complete §5 table.

### Orchestrator verification after Step 9

- `workspace/PRD_COMPLETED.md` exists at 437 lines / 123,450 bytes and is **not** byte-identical to `PRD_FINALIZED.md` — the partitioned scan genuinely ran (the known single-pass no-op failure mode did not occur).
- Structure intact: five `##` sections in order, 54 §4 endpoint rows, 50 §5 error rows, file terminates on the last error row.
- No source file under `workspace/implementation/`, `test_suite/`, or `test_helpers/` has an mtime later than 20:33; the green 8-round sweep completed at 20:40. The Step 9 passes edited only `PRD_COMPLETED.md`, so the 8 x 234/234 evidence in `workspace/implementation/results.{1..8}.json` still describes the shipped code.
- One residual defect is recorded by both pass 2 and pass 3 and deliberately NOT written into the PRD: `calc.retrofit_simple_payback` and `calc.measured_savings` can raise `decimal.DivisionByZero` -> HTTP 500 `ERR_INTERNAL` at the extreme low end of the validated input ranges (e.g. `projected_annual_savings_kwh = 0.01`). No test exercises it. Pinning a 500 into the PRD would enshrine a defect rather than resolve an ambiguity, so it is flagged here instead.

**Pipeline complete.** All nine steps executed; `workspace/PRD_COMPLETED.md` written.
