# Worklog — task_2355_employer_health_coverage_reporting

## Step 1: Create task directory — 2026-09-02T03:54:35.210Z

Created `tasks/task_2355_employer_health_coverage_reporting/` and `tasks/task_2355_employer_health_coverage_reporting/workspace/` (pre-allocated name used verbatim; no index scan performed).

## Step 2: Generate scaffold — 2026-09-02T05:51:46.604Z

Done. All three artifacts are in place and the linter is clean on the first run.

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.

Coverage
  §1.5 endpoints declared:    69
  §1.1 entities declared:     16
  §1.8 instances scanned:     24
  §1.9 instances scanned:     71
  Calls scanned (§1.8+§1.9):  883
```

Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2355_employer_health_coverage_reporting/`):

**SCAFFOLD.yaml** (3321 lines, §1.0–§1.7 only — no design keys). `api_prefix: /ale-reporting`; archetype compliance_audit + ledger_reconciliation, `role_model: segregation_of_duties`, `consistency_model: immediate`, complexity layers dual_variant_calculation / rate_threshold_triggers / cascading_side_effects / optimistic_concurrency.
- 16 entities (7 immutable ledgers), 8 state machines (Form1095C has two independent dimensions; Transmittal is cyclic with a correction loop), 2 OCC rules, 7 calculations, 45 ordered validations, 69 endpoints, 53 errors, 5 roles.
- Domain spine: FTE aggregation with rounding-order traps, look-back vs monthly measurement, W-2/rate-of-pay/FPL harbor ladder, line 14/15/16 precedence, 1094-C build/transmit/AIR correction cycles (limit 3), electronic-filing threshold, Letter 226-J response with largest-remainder cent allocation, late-furnishing penalty tiers.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** (1924 lines, single key `scaffold_difficulty_design`) — 9 rule ids / 24 instances: dual_variant_calc 3, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 2.

**SCAFFOLD_CORNER_DESIGN.yaml** (4161 lines, single key `scaffold_corner_design`) — 9 sections / 88 instances (71 active + 17 `excluded_because` stubs deferring to named §1.8 instances): Entities 11, State Machines 10, Calculations 10, Validations 7, Endpoints 6, Errors 34 (one per remaining catalog entry; the 19 already driven by named instances elsewhere are listed in a header comment instead of duplicated), RBAC 4, Cross-Cutting Complexity Layers 5, Consistency Model 1.

All 112 instance names are unique across the two design files. The hard constraint was honored: nothing outside the task-2355 directory and the scaffold-generator skill's own spec/linter was read at any point.

## Step 3: Copy shared files — 2026-09-02T05:51:46.604Z

Copied `INSTRUCTION.md` to `tasks/task_2355_employer_health_coverage_reporting/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T06:08:46.612Z

PRD generated and audited.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2355_employer_health_coverage_reporting/workspace/PRD.md` — 452 lines, ~12,470 words. Ends at §5 with no audit footer; §2.2 is byte-verbatim against `section-2.2-response-structure.md` (verified by string comparison).

**Sections**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications & System-Wide Principles — 2.1 Actors, Headers and RBAC / 2.2 API Response Structure (verbatim) / 2.3 Pagination / 2.4 Resource Identity, Timestamps and the Logical Clock / 2.5 Flat Collections, Reverse Reachability and Path Identifier Validation / 2.6 The Validation Ladder / 2.7 Segregation of Duties / 2.8 Optimistic Concurrency Control / 2.9 Counting, Rounding and Monetary Precision / 2.10 Season Closure and the Open-Correction Chain / 2.11 Atomic Batch Writes
- §3 Business Logic & Workflows — 3.1 Opening the Season and Registering the Aggregated Group / 3.2 Determining ALE Status / 3.3 Workforce Records: Hires, Hours and Measurement Cycles / 3.4 Employment Changes and the Termination Cascade / 3.5 Identifying Full-Time Months / 3.6 Offers of Coverage, Affordability and the Twelve Monthly Codes / 3.7 Delivering Statements to Employees / 3.8 Assembling, Transmitting and Correcting the Submission / 3.9 Answering a Proposed Penalty Assessment
- §4 Endpoint Definitions — 4 columns, 69 rows
- §5 Error Code Catalogue — 2 columns, 53 rows

**Field coverage check:**
- entities[].fields: 193 required, 193 present, 0 missing
- endpoints[].request_body: 99 required, 99 present, 0 missing
- endpoints[].query_params: 26 required, 26 present, 0 missing
- endpoints[].path_params: 10 required, 10 present, 0 missing
- Status: PASS

**Rule coverage check:**
- validations[] with priority: 45 checked, 45 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + `expected_controlled_group_version`/`expected_group_member_version` + error_id all named), 0 missing
- state_machines[].transitions: 58 checked, 58 fully expressed, 0 missing
- calculations[]: 7 checked, 7 fully expressed (pinned orders, constants, rounding), 0 missing
- validations[] conditions: 45 checked, 45 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 38 endpoints with side effects checked, 38 expressed, 0 missing
- entities[].fields[] structured content: 193 checked, 193 reconstructible from prose (every enum value present in backticks; 0 missing), 0 missing
- sibling-branch symmetry: 13 groups checked, 13 with equal prose density, 0 asymmetric
- Status: PASS

**Path purity check (§3 only):**
- backtick tokens scanned: 933
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
- Status: PASS

Additional cross-checks: §4 rows match the scaffold's 69 endpoints exactly in method, path, order and authorized-role set (programmatic diff, zero discrepancies); §5's 53 error IDs and HTTP statuses match the scaffold one-for-one. The two `SCAFFOLD_*_DESIGN.yaml` files were never opened, grepped, or referenced, and no sibling task directory was read.

## Step 5: Generate unit tests — 2026-09-02T06:56:23.792Z

All final whole-suite sweeps are done. Suite is complete and audited.

## Files created

`/home/ubuntu/github/CodingPRD/tasks/task_2355_employer_health_coverage_reporting/`

**Stage 1 — `test_helpers/` (9 files):** `types.py` (~31 enums, 16 TypedDicts split into 9 mutable / 7 append-only families), `api_client.py` (`ApiClient` with one method per PRD endpoint, all 69 verified against §4), `api_errors.py` (53 error ids + `HTTP_STATUS_CODES`, registered with the framework via `set_error_http_status_map`), `constants.py`, `test_users.py` (7 seeded operators + `EmployeeSelfService` header builder), `factories.py` (payload builders with `_UNSET`/`_merge` so recipes can pin or delete fields), `assertions.py` (shape assertions per family; append-only rows assert `updated_at`/`version` are absent), `fixtures.py` (tiered composites, live version reads, the determined-ALE prelude, statement/transmittal/penalty pipelines), `__init__.py` (barrel).

**Stage 2 — `test_suite/` (18 files):** `conftest.py` plus `test_01`…`test_17`.

## Test counts

| Queue | Files | Tests | Instances |
|---|---|---|---|
| A (Difficulty, §1.8) | 7 (`test_01`–`test_07`) | 65 | 24 / 24 translated, 0 skipped |
| B (Corner, §1.9) | 10 (`test_08`–`test_17`) | 148 | 71 / 71 live translated, 0 skipped |
| **Total** | **17** | **213** | **95** |

213 test functions; 219 pytest items (3 parametrized tests). All 17 `excluded_because:` stubs correctly produced no tests, and all 17 `difficulty_instance` back-pointers resolve to real difficulty instance names.

## Machine-verified audits (whole suite, run by me)

- **Coverage:** every difficulty instance has ≥2 tests, every live corner instance ≥1. No instance under-covered.
- **Tags (C4):** every test has exactly one `Design:` line, it is the last docstring line, and its `<rule_id>`/`<section>` segment matches the instance's actual parent in the source yaml. Zero untagged, dual-tagged, mistagged, or stub-tagged tests.
- **Citations (C1/C3):** all 485 quoted citations match `workspace/PRD.md` verbatim under whitespace normalization. This pass found and I fixed 5 quotes in `test_15_window_duplicate_and_amount_errors.py` where markdown bold markers had been dropped (`PenaltyEvidence` → `**PenaltyEvidence**`, `FilingSeason` ×2, `EmploymentEvent`, `the full` → `the **full**`).
- **Hygiene:** zero `pytest.mark.skip`/`skipif`/`xfail`, zero `TODO`/`FIXME`, zero scaffold/design-index/§1.x leakage in any emitted file.
- **Compile/collect:** `py_compile` clean on all 27 files; `pytest test_suite --collect-only` collects the whole suite as one unit.

## Skips

No whole instance was skipped. Individual assertions were dropped where the PRD is silent, by silence-pattern category: `computed-field` (fields absent from the PRD entirely — `furnish_count`, `transfer_month`, `resolved_at`, `single_member_id`; timestamps the PRD stamps without naming the clock as source — replaced with `is_iso8601_timestamp` checks; batch-response array ordering), `default-value` (null-vs-absent-vs-zero initial values: `annual_average_fte`, `monthly_group_fte`, `ft_source_by_month` at hire, a correction's initial `transmittal_id`, `required_channel is null`), `branch-asymmetry` (WARNING-only statement destination, error rows from the `REJECTED` branch, cumulative-vs-reset `error_count`), `validation-priority` (bare ordering claims with no PRD precedence sentence), `cross-entity-cascade` (unstated secondary effects: member `version` on detach, counters at agency acceptance), `applies_to-scope` (status for PATCH/PUT/DELETE on `/hours-records`, which the PRD merely omits).

## Design-index bugs surfaced (PRD followed in every case)

- Recipes specifying HTTP 422 for `ERR_INVALID_REQUEST` (PRD §2.6 rung 3 and §5 say 400) and 422 for `ERR_MEASUREMENT_METHOD_CONFLICT` (PRD says 409).
- `attach_forms_on_built_transmittal_rejected` expects `aggregate_return_count == 1`; the §3.8 formula yields 2.
- `resolve_already_resolved_error_rejected` names `resolution_status == ACCEPTED`; §3.8 says `ACCEPTED_AS_FILED`.
- Two Errors-slice recipes are unreachable as written: a reporting-year headcount of 30 floors section (a) at zero, so the `allocation/reset` precondition (`allocated_total_cents` above zero) can never hold; also a headcount-vs-determination ordering problem, since `reporting_year_ft_months` freezes at determination time.

## Step 6: Generate implementation — 2026-09-02T06:56:23.792Z

Implementation complete and validated.

## Files created
All under `/home/ubuntu/github/CodingPRD/tasks/task_2355_employer_health_coverage_reporting/workspace/implementation/`:

| File | Role |
|---|---|
| `start.sh` (executable) | guarded `pip install` (only when Flask is missing, to avoid boot contention under `--isolation per-test-server`) then `exec python3 app.py` |
| `requirements.txt` | `Flask==3.0.3` |
| `app.py` | app factory, blueprint registration under `/ale-reporting`, global request lock, `ApiError`/404/405/500 handlers, `/health` |
| `db.py` | in-memory dict store, `_seq` ordering, logical clock (starts exactly `2026-08-01T00:00:00Z`), `insert`/`touch` |
| `errors.py`, `envelope.py` | 53-code catalogue + status map; `meta`/`response_type`/`data` envelope, `req_` + 20 uppercase alnum ids, 3-digit ISO timestamps, offset pagination |
| `auth.py`, `shapes.py`, `lookups.py`, `guards.py` | header auth + 5 roles, request-shape coercion (rung 3), FK resolution (rung 4), season/group/scope gates |
| `calc.py` (620 lines) | the 7 calculations: FTE aggregation with pinned rounding, seasonal exception, dual-variant full-time determination, 12-line derivation (steps A–G), safe-harbor fall-through, penalty tiers, largest-remainder allocation |
| `sync.py` | derived counters, cascade chains LINK 1–5, correction drafting, allocation zeroing |
| `routes/{seasons,workforce,forms,filing,penalty}.py` | 17 / 17 / 12 / 13 / 10 endpoints |

## Endpoint count
**69** (verified by introspecting `app.url_map`), matching the scaffold total: seasons 17, workforce 17, forms 12, filing 13, penalty 10. 16 entities, 8 state machines, 45-rung validation ladder, 53 error codes.

## Notable design decisions
- **Zero seeding, fresh boot verified**: after `bash start.sh` all 16 collections report `total_count 0` and the clock reads the specified startup instant; boot to first 200 in ~1–3 s on this loaded host.
- **Clock split**: `created_at`/`updated_at`/`api_request_timestamp` come from wall clock; every business stamp (`locked_at`, `furnished_at`, `built_at`, `transmitted_at`, `recomputed_at`, …) comes from the logical clock.
- **Version bumping** via a per-request dirty set on `flask.g`, so a record's `version` advances at most once per request and only on a real value change.
- **Derived counters** are refreshed centrally before serialisation on every mutating request, keyed on "live" forms (neither status dimension `VOIDED`), so `open_transmittal_id` clears itself on acceptance.
- **Regenerate returns the statement acted upon** (the original), per §1.5's convention that action endpoints return 200 reporting the parent; the drafted `CORRECTED` form is reachable through the `corrected_from_form_id` filter.
- **Employment-event cascades target the latest non-voided statement**, so a termination after a correction is drafted rewrites the correction's lines (month 9 → `2B` + `TERMINATION`, months 10–12 → `1H`/`2A`/`NOT_EMPLOYED`), which is also the only reading consistent with §3.5 step B stating that cascade-written `special_situation` values overwrite line derivation.
- **Undeclared error choices pinned**: reopen from non-determined → `ERR_GROUP_NOT_DETERMINED_ALE`; reopen after transmission → `ERR_TRANSMITTAL_STATE_INVALID`; `allocation/reset` with nothing allocated → `ERR_NOTICE_NOT_RECOMPUTED`; `start-correction-cycle` with no open errors → `ERR_TRANSMITTAL_STATE_INVALID`; `CORRECT_FORM` on an error naming no form → `ERR_INVALID_REQUEST`; bad `limit`/`offset` → `ERR_INVALID_REQUEST` (400).

## Verification
Two hand-written end-to-end scripts (`/tmp/ale_smoke.py`, `/tmp/ale_smoke2.py`, ~160 calls total, outside the deliverable) both finish with **FAILURES: 0**, covering: determination with stale-version 412, seasonal exception (`105 / SEASONAL_EXCEPTION / NON_ALE`) and single-member basis, look-back vs monthly measurement, hours/offer overlap conflicts, line derivation and roll-ups, consent identity 403 and withdrawal cascade to `season.open_correction_count`, SoD 403 on furnish/transmit/submit-response, attach/detach/build/transmit with `ERR_ELECTRONIC_FILING_REQUIRED`, agency response → `FILED_WITH_ERRORS` + `REDELIVERY_REQUIRED`, error resolution drafting a discoverable correction, penalty recompute (`741000` split `370500/370500`, exclusion `15/15`), reset/submit/`SUSTAINED` reallocation, season lock plus the `ERR_DETERMINATION_LOCKED` vs `ERR_SEASON_LOCKED` distinction, rehire/transfer/leave transitions, and the auth/pagination/404 surfaces.

One note: several background test-generation agents from a different pipeline (`prd-bench-entrance`) are active in this session and write into `test_suite/`. I did not use their output — that directory, plus both `SCAFFOLD_*_DESIGN.yaml` files and all sibling task directories, remained unread per your constraints.

## Step 7: Run tests and iterate — 2026-09-02T11:05:00.000Z

The task is complete — the first 8-round parallel stability sweep came back fully clean, so no diagnostic iteration was required.

## Summary

**Iterations run:** 1 (a single 8-round parallel sweep, all rounds launched concurrently under `setsid nohup` and joined with `wait`).

**Sweep result — all 8 rounds `passed == total`:**

| Round | passed / total | failed | errors | skipped | duration |
|---|---|---|---|---|---|
| 1 | 219 / 219 | 0 | 0 | 0 | 1654 s |
| 2 | 219 / 219 | 0 | 0 | 0 | 1588 s |
| 3 | 219 / 219 | 0 | 0 | 0 | 1662 s |
| 4 | 219 / 219 | 0 | 0 | 0 | 1654 s |
| 5 | 219 / 219 | 0 | 0 | 0 | 1667 s |
| 6 | 219 / 219 | 0 | 0 | 0 | 1581 s |
| 7 | 219 / 219 | 0 | 0 | 0 | 1646 s |
| 8 | 219 / 219 | 0 | 0 | 0 | 1606 s |

Union of failing tests across all 8 rounds: **empty**. No flakiness surfaced (no test passed in some rounds and failed in others), so the diagnostic protocol (STEP 0–3) was never entered.

**Tests deleted:** none — no test failed, so no PRD-silence / unique-derivability review was triggered.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

**Supporting checks performed while the sweep ran** (read-only audit of the artifact, to confirm the green sweep isn't hollow):
- `grep` for `pytest.mark.skip` / `skipif` / `xfail` across `test_suite/` and `test_helpers/` → **0 hits**, so all 219 items genuinely executed (results files also report `skipped: 0`).
- `grep` for `sqlite` / `json.dump` / `/tmp` file writes / `pickle` in `workspace/implementation/` → **0 hits**; storage is `db.py`'s in-memory `Store` of plain dicts, freshly constructed on every `app.py` boot, which is what makes the `--isolation per-test-server` restart a true state wipe.
- Read the full implementation (`app.py`, `db.py`, `auth.py`, `shapes.py`, `lookups.py`, `guards.py`, `envelope.py`, `errors.py`, `calc.py`, `sync.py`, and all five route modules) plus `test_helpers/{fixtures,factories,constants,assertions,test_users}.py` against PRD §2.1–§2.11 and §3.1–§3.9. Nothing is seeded at startup; every entity the tests need is built through declared endpoints by the fixtures.

**Operational note for the caller:** this host is heavily CPU-contended (245 concurrent `prd-bench-local-run` processes were live at sweep start). The sweep's first ~20 minutes crawled to 7% and then accelerated sharply as neighbours drained; total wall time was ~28 minutes for all 8 rounds. That contention is load, not an artifact defect — worth remembering if a future sweep on this box times out rather than fails.

Artifacts left in place: `workspace/implementation/results.{1..8}.json` and `workspace/sweep.log`.

**Orchestrator verification:** independently re-read all 8 `results.{i}.json` — every round reports passed=219, total=219, failed=0, errors=0, skipped=0.

## Step 8: Finalize PRD — SKIPPED — 2026-09-02T11:06:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline. Per the skill's Step 8 skip condition, `PRD.md` already determined every behavior the implementation exhibits at the sites tests exercised, so no `PRD_FINALIZED.md` is produced. Step 9 therefore starts from `PRD.md`.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-09-02T11:32:00.000Z

Complete. `workspace/PRD_COMPLETED.md` is written and aligned to `workspace/implementation/`. Step 8 was skipped, so the scan started from `workspace/PRD.md`.

## Counts

- **Source:** `workspace/PRD.md` — 452 lines, 92,858 chars
- **Result:** `workspace/PRD_COMPLETED.md` — 452 lines, 112,808 chars (char delta **+19,950**)

Lines unchanged at 452; 57 lines touched, all in-paragraph inserts/revisions. No new sections, paragraphs, bullets or table rows.

- **ambiguity-pins: 47**
- **mismatch-revisions: 11**

## Changes

- §2.1 — insert — ambiguity — consent ownership is checked after the `consent_id` resolves (so `ERR_CONSENT_NOT_FOUND` precedes `ERR_FORBIDDEN_ROLE`) and governs only grant/withdraw — routes/forms.py:72-78
- §2.2 — insert — ambiguity — `api_request_timestamp` reads real time, not the logical clock — envelope.py:24, db.py:78-80
- §2.2 — insert — ambiguity — only the two batch creates return an array `data`, 201, no pagination meta — envelope.py:70-78
- §2.2 — insert — ambiguity — pagination meta appears on list endpoints only — envelope.py:36-52
- §2.2 — insert — ambiguity — unrouted path → `ERR_RECORD_NOT_FOUND`, bad method → `ERR_INVALID_REQUEST`, unhandled → `ERR_INTERNAL` 500 (only code outside §5) — app.py:42-66
- §2.3 — insert — ambiguity — limit/offset range and type faults; unparseable filter yields an empty page, empty-string filter ignored — envelope.py:81-138
- §2.4 — insert — ambiguity — `created_at`/`updated_at` use real time; no-op counter writes don't bump; one `version` bump per request; created rows stay at 1 — db.py:111-135, sync.py:28-32
- §2.4 — revise — ambiguity — clock accepts `Z`/offset/naive, answers 200 with `current_utc`; enumerates the ten business timestamps taken from the logical clock — routes/seasons.py:406-417, shapes.py:192-204
- §2.5 — revise — mismatch — body-FK list gains `transmittal_id`, loses `penalty_notice_id`; filter values never 404 — routes/filing.py:381, envelope.py:104-138
- §2.6 rung 7 — insert — ambiguity — re-locking a `LOCKED` season answers `ERR_SEASON_LOCKED` — routes/seasons.py:104
- §2.6 rung 9 — insert — ambiguity — reopen reuses `ERR_GROUP_NOT_DETERMINED_ALE` for its own state set — routes/seasons.py:231-232
- §2.6 rung 10 — revise — ambiguity — event date-ordering faults share `ERR_EMPLOYMENT_EVENT_NOT_APPLICABLE` — routes/workforce.py:374-387
- §2.6 rung 16 — insert — ambiguity — the statement examined is the most recently created; none passes the rung — routes/workforce.py:251-254
- §2.6 rung 17 — revise — ambiguity — both start-correction refusals share `ERR_TRANSMITTAL_STATE_INVALID` — routes/filing.py:317-320
- §2.6 rung 20 — insert — ambiguity — allocation reset reuses `ERR_NOTICE_NOT_RECOMPUTED` for a zero allocation — routes/penalty.py:261-264
- §2.6 rung 31 — revise — ambiguity — the rung is "employee holds ≥1 statement that reached the agency" — routes/penalty.py:217-226
- §2.8 — insert — ambiguity — version echoes validated as non-negative integers first — routes/seasons.py:176, routes/filing.py:49
- §2.9 — insert — ambiguity — both allocations degenerate to all-zero rather than dividing by zero — calc.py:471-506
- §2.10 — insert — ambiguity — both correction counters are re-derived; exact populations; only `DETERMINED_ALE`↔`CORRECTION_OPEN` transition — sync.py:79-99
- §2.11 — revise — ambiguity — batch rows created in ascending month order; duplicate month inside one array also rejected — routes/seasons.py:349-362
- §3.1 — revise — mismatch — `affordability_pct` constrained only to 0<x<1 at any precision; the four other figures only non-negative — routes/seasons.py:51-59
- §3.1 — insert — ambiguity — group init fields (`monthly_group_fte` empty, averages null); group registration is not season-gated — routes/seasons.py:130-150
- §3.1 — insert — ambiguity — member amendment fields both optional; `version` bumps even when nothing moves — routes/seasons.py:313-327
- §3.1 — revise — ambiguity — `member_fte` rounds the quotient alone; uniqueness per member/`count_year`/month; recording is ungated — routes/seasons.py:333-382
- §3.2 — insert — ambiguity — `single_member_id` read only under the single-member basis; the named member need not be `ACTIVE` — routes/seasons.py:176-207
- §3.2 — insert — ambiguity — determination writes `monthly_group_fte`/`annual_average_fte_raw`/`single_member_id`; self-loop allowed from every state but `LOCKED` — routes/seasons.py:203-218
- §3.2 — insert — ambiguity — reopen clears `monthly_group_fte` to `[]`, keeps three fields, discards `reason`; other states → `ERR_GROUP_NOT_DETERMINED_ALE`; both member statuses scanned — routes/seasons.py:221-250
- §3.3 — insert — ambiguity — wage-field conditionality; PATCH leaves omitted fields, explicit null clears the override; hire/amend ungated — routes/workforce.py:164-169, 218-239
- §3.3 — insert — ambiguity — hour figures and `measurement_year` only non-negative; duplicate month → `ERR_DUPLICATE_HOURS_MONTH` — routes/workforce.py:270-291
- §3.3 — insert — ambiguity — `employee_id` forbidden on `STANDARD`/mandatory on `INITIAL`; latest qualifying cycle governs; the four date-ordering rules — routes/workforce.py:60-90, calc.py:142-171
- §3.3 — revise — ambiguity — per-employee overlap scope spans every cycle naming that employee, any `cycle_type` — routes/workforce.py:101-114
- §3.4 — insert — ambiguity — applicability and date ordering share one code; events are ungated — routes/workforce.py:361-390
- §3.4 — insert — ambiguity — leave cascade spans all `measurement_year`s; every cascade acts on the latest live statement, nothing when there is none — sync.py:292-313, lookups.py:139-144
- §3.4 — revise — ambiguity — transfer stamps by month number alone; nothing else on the line or the chain moves — sync.py:305-313
- §3.4 — revise — mismatch — termination roll-up also rewrites `all_12_months_code`, and the termination month's `assessable` goes false — sync.py:283-288
- §3.4 — insert — ambiguity — rehire does not unwind the termination rewrite or close the correction — routes/workforce.py:412-418
- §3.5 — insert — ambiguity — recompute inspects the latest statement, needs a season, returns the employee, refreshes only three per-month fields plus roll-ups — routes/workforce.py:240-260, sync.py:322-329
- §3.5 — insert — ambiguity — look-back denominator rows placed by their own `measurement_year`; method re-resolved first — calc.py:225-235
- §3.5 — revise — mismatch — a hire date in a later calendar year yields hire month 13, leaving no month employed — calc.py:174-181
- §3.6 — insert — ambiguity — end strictly after start; `covered_months` frozen at creation, falling back to the start date's year; ungated — routes/workforce.py:470-500
- §3.6 — revise — ambiguity — governing-offer tie broken by creation order — calc.py:268-272
- §3.6 — insert — ambiguity — step-A settled months keep null `safe_harbor_applied`/`affordability_threshold_cents` — calc.py:344-354, 405-412
- §3.6 — revise — mismatch — the LNAP cycle is the employee's own latest `INITIAL` cycle regardless of method, never the member's `STANDARD` — calc.py:321, 357-362
- §3.6 — insert — mismatch — regeneration answers with the **original**; correction inherits plan month/preference but takes the acting user; reason on both; in-place path replaces `generated_by_user_id` — routes/forms.py:186-199, sync.py:221-247
- §3.7 — insert — ambiguity — `granted_at`/`withdrawn_at` are never cleared; `grant_count` counts the first grant — routes/forms.py:81-106
- §3.7 — revise — mismatch — `intentional_disregard` overrides even an on-time delivery; member total is a full re-derived sum over every form incl. voided — calc.py:598-612, sync.py:60-64
- §3.8 — insert — ambiguity — `open_transmittal_id` = latest transmittal not `ACCEPTED`/`SUPERSEDED`, else null — sync.py:16-24, 65-69
- §3.8 — insert — ambiguity — exact populations of `attached_form_count`/`unattached_form_count` and their sum to `generated_form_count` — sync.py:9-15, 43-59
- §3.8 — insert — ambiguity — detach keeps `built_by_user_id`; wrong-transmittal detach → `ERR_FORM_NOT_ATTACHED`; attach voids the predecessor whatever the `transmission_type` — routes/filing.py:118-152
- §3.8 — revise — mismatch — `form_count` is re-derived after every write, not frozen — sync.py:102-111
- §3.8 — insert — ambiguity — error entries' `form_1095c_id` optional; the three consistency faults are `ERR_INVALID_REQUEST`; `receipt_id` optional; only `PENDING_FILING` statements move — routes/filing.py:246-308
- §3.8 — revise — mismatch — `CORRECT_FORM` imposes no transmittal-status requirement; unnamed row → `ERR_INVALID_REQUEST`; statement moves only from `FILED_WITH_ERRORS`; note becomes the correction's `correction_reason` — routes/filing.py:386-419
- §3.9 — insert — ambiguity — asserted arrays mandatory but may be empty; entries validated and employee ids resolved; proposed amount only non-negative — routes/penalty.py:31-84
- §3.9 — revise — mismatch — asserted line codes required for `OFFER_PROOF` only; `employee_id` optional (not forbidden) on `MEC_OFFER_PROOF` — routes/penalty.py:143-158
- §3.9 — insert — ambiguity — recompute needs a governing season (`ERR_FILING_SEASON_NOT_FOUND`) — routes/penalty.py:227-229
- §3.9 — revise — ambiguity — `unallocated_amount_cents` is always `recalculated − allocated` — routes/penalty.py:246-249
- §3.9 — revise — mismatch — notice `status` mirrors `determination`; `ABATED_FULL` also zeroes `allocated_total_cents`; `ABATED_PARTIAL` leaves both totals; `SUSTAINED` degenerate case — routes/penalty.py:329-346
- §4 — insert — ambiguity — batch creates answer 201 with an array, clock answers 200 with `current_utc`, trailing slashes accepted, unlisted `GET /health` returns a bare `{"status":"ok"}` — app.py:19, 68-70, envelope.py:70-78

Cross-checks run: all 53 error codes in `errors.ERROR_STATUS` match the §5 table's identifiers and HTTP statuses exactly; the §4 endpoint table matches the 46 registered routes one-for-one (only `/health` was undocumented, now pinned).

**Orchestrator verification:** `PRD_COMPLETED.md` present — 452 lines / 112,808 chars, all 5 top-level sections intact, ends cleanly at the §5 error catalogue.

---

## Pipeline complete — 2026-09-02T11:33:00.000Z

Resume run finished. Steps 1–6 were already satisfied on disk and were not re-run (per the resume protocol: all three scaffolds non-empty, `workspace/INSTRUCTION.md` present, `workspace/PRD.md` complete through §5, `test_suite/` with 17 `test_*.py` files plus `test_helpers/`, and `workspace/implementation/` with `start.sh`). Step 7 ran and passed 219/219 on all 8 rounds of its first sweep. Step 8 was skipped under its documented skip condition. Step 9 wrote `workspace/PRD_COMPLETED.md`.
