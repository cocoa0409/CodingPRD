# Worklog — task_2236_emissions_monitoring_allowance_compliance

## Step 1: Create task directory — 2026-09-01T09:29:22.387Z

Created `tasks/task_2236_emissions_monitoring_allowance_compliance/` and `tasks/task_2236_emissions_monitoring_allowance_compliance/workspace/` (directory name pre-allocated by the caller; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T11:34:24.281Z

Done. All three artifacts are complete and lint-clean.

Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2236_emissions_monitoring_allowance_compliance/`):
- `SCAFFOLD.yaml` — §1.0–§1.7, top-level keys only (`scenario`, `domain_name`, `api_prefix`, `complexity_profile`, `response_envelope`, `entities`, `state_machines`, `concurrency_rules`, `calculations`, `validations`, `endpoints`, `errors`, `roles`); no design keys present.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design` (§1.8), 30 instances across 9 rule blocks.
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design` (§1.9), 73 instances across all 9 sections.

Scaffold counts (verified by parsing the file):
- entities 14, state machines 10, concurrency rules 3, calculations 11, validations 47, endpoints 65, error catalog 59, RBAC roles 6.
- `domain_name: emissions-monitoring-allowance-compliance`, `api_prefix: /emissions`; profile: topology `hybrid`, state shape `parallel`, role model `segregation_of_duties`, consistency `immediate`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, derived_field_reconciliation, bulk_operations]`.

§1.8 / §1.9 instance counts:
- §1.8: 30 instances — dual_variant 3, combinatorial 3, non_linear 3, cascade 3, priority 4, boundary 4, cross_entity 4, overlap 3, invariant 3.
- §1.9: 73 instances — entities 12, state_machines 14, calculations 13, validations 11, endpoints 6, errors 4, rbac 4, complexity_layers 8, consistency_model 1. Of these, 41 carry a full `test_recipe` and 32 are `excluded_because` stubs, each citing a §1.8 instance that exists by name (verified: 0 bad references, 0 duplicate names across the two files).
- Error coverage: all 59 catalog codes are exercised somewhere in §1.8/§1.9.

Lint verdict (verbatim, `scaffold_lint.py`):

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    65
  §1.1 entities declared:     14
  §1.8 instances scanned:     30
  §1.9 instances scanned:     41
  Calls scanned (§1.8+§1.9):  883

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Notes on the two issues fixed at the end: three enum literals in the design files were wrong against the scaffold (`ARP`→`ARP_SO2`, `CSAPR_SO2`→`CSAPR_SO2_G1`, `BITUMINOUS_COAL`→`COAL`) plus a Facility defaults assertion (`max_concurrent_control_outages == 2`, `status == OPERATING`); and one bulk-append OCC call used a literal `expected_quarterly_report_version: "2"`, now a captured `${q2_v2}` from the preceding successful bulk response. The hard constraint was respected throughout — no sibling task directory was listed, read, or grepped.

## Step 3: Copy shared files — 2026-09-01T11:34:30.000Z

Copied `INSTRUCTION.md` from project root to `tasks/task_2236_emissions_monitoring_allowance_compliance/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T11:51:48.419Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_2236_emissions_monitoring_allowance_compliance/workspace/PRD.md` is written (486 lines).

**Section list**

- §1 Introduction — two-clocks framing (operational vs. regulatory), the cascade design commitment, segregation of duties, conserved allowance ledger, `/emissions` prefix.
- §2 Global Specifications (11 subsections): 2.1 User and Role-Based Access Control · 2.2 API Response Structure (byte-verbatim from `section-2.2-response-structure.md`) · 2.3 Pagination and Collection Filtering · 2.4 The Logical Compliance Clock · 2.5 Resource Identity and Audit Fields · 2.6 Measurement Precision and Rounding · 2.7 Stale-Version Guards · 2.8 Rule Precedence · 2.9 Cascade Integrity and Hierarchical Consistency · 2.10 The Conserved Allowance Quantity · 2.11 Path Resolution for Nested Resources.
- §3 Business Logic (9 subsections): 3.1 Facilities, Units, Dispatch and Outage Planning · 3.2 Monitoring Systems: Two Independent Status Dimensions · 3.3 Relative Accuracy Test Audits, Bias and the Retest Loop · 3.4 Fuel Sampling and Laboratory Analysis · 3.5 Recording Operating Hours: Two Determination Methods · 3.6 Missing Data Substitution and Monitor Data Availability · 3.7 The Quarterly Emissions Report · 3.8 Permit Limits, Rolling Averages and Excess Emission Reporting · 3.9 Allowance Holdings, Trading and the True-Up.
- §4 Endpoint Definitions — 65-row, 4-column table. §5 Error Code Catalogue — 59-row, 2-column table. Document ends at §5, no footer.

**Coverage**

- **Entities (14):** all 151 field names rendered in prose with types, defaults, enum members and constraints. `DailyCalibration`/`OperatingHour` are called out as the two append-only records with no `updated_at`/`version`, carrying `monitoring_system_version_after` / `quarterly_report_version_after` instead.
- **State machines (10, 49 transitions):** `MonitoringSystem`'s parallel `qa_status` × `cal_status` axes; `RataTest`'s `FAILED`→`SCHEDULED` retest cycle with `FAILED`→`VOIDED` supersession; `FuelSample`'s `ANALYZED`↔`INVALIDATED` loop with no terminal state; `QuarterlyReport`'s two loops back to `DRAFT`; `ExcessEmissionEvent`'s `UNDER_REVIEW`→`REPORTED` revert; `AllowanceAccount`'s `TRUE_UP_LOCKED`→`OPEN` compensation edge; plus `Unit`, `AllowanceTransaction`, `ControlOutageWindow`, `ComplianceCertification`. Terminal states and undeclared-transition rejection stated for each.
- **Calculations (11):** every formula translated to natural language with all 22 constants inline (F-factor 1800.0, 0.000000166, 0.1194, 205.3, 2000.0, 2.0 sulfur ratio, 20-hour lookback, 400 ppm, tier floors 95.0/90.0/80.0, floor 80.0, t-values 1.860/1.833/1.812/1.796, RA threshold 10.0, low-emitter 0.300/5.000, span 3/720/8760, min samples 3/24/24, penalty ratio 2.0, bulk 200, 26-hour calibration validity). Load-bearing orderings preserved: round-per-hour-then-sum, `total_so2_tons` from already-rounded lbs, substitution's three pinned ordering rules, ceiling-not-round for `obligation_tons` / `penalty_allowance_debit_tons`, and reversal crediting stored `debited_*` rather than re-deriving.
- **Validations (47):** the full priority ladder is rendered in §2.8 as an explicit banded ordered list with every `applies_to` scope and every pinned-order rationale (shape before 404, OCC first in the state band, duties before OCC, lock before insufficiency, out-of-control before not-certified, overlap before in-past, reason-required last), and the numeric ranges enumerated.
- **Endpoints (65):** all methods, paths, roles match the scaffold exactly (`Any` where all six roles apply); status-code convention stated. Every side effect narrated in §3.
- **Errors (59):** all IDs and HTTP statuses match; every error is also reasoned about in §2/§3 prose, not only listed in the table.
- **Roles (6):** each `identity:` translated explicitly — `FacilityOperator` as the sole entity-backed role scoped by `operator_org` (with its ten scoped writes enumerated), the other five as opaque identifiers recorded into `submitted_by_user_id` / `certifier_user_id` but never compared to an `id`.

**Hard Contracts:** Contract 1 field-name coverage **PASS** (166/166 names present in backticks; two passes). Contract 2 rule coverage **PASS** (validation priorities, three OCC rules, all cascade side effects, all `applies_to` scopes, sibling-branch symmetry for revoke-vs-reject, settle-vs-reverse, excuse/enforce/return). Contract 3 §3 path purity **PASS** (zero backtick tokens in §3 starting with `/`, bare HTTP methods, or method+path).

Four scaffold-internal inconsistencies were resolved toward the computational source of truth and are worth flagging: `max_concurrent_control_outages` (entity says at least 1 with default 2, range rule says 0–10 — both transcribed); `measured_hour_count` (rendered per the formula, i.e. no operating-time filter, with the divergence made explicit); `window_sample_count` (rendered as count of qualifying hours per the formula, not distinct dates per the entity description); `bias_adjustment_factor` (rendered per the calculation, `1 + mean_difference / cems_mean`, not the entity description's absolute-value form). I also had to state the program-to-pollutant mapping explicitly (`ARP_SO2`/`CSAPR_SO2_G1` → `SO2`, `CSAPR_NOX_ANNUAL`/`CSAPR_NOX_OZONE` → `NOX_RATE`) since the scaffold only says "whose program pollutant matches" and a PRD-only reader cannot infer it. The two withheld design files were never opened, grepped, or referenced, and no sibling task directory was read.

## Step 5: Generate unit tests — 2026-09-01T13:26:39.644Z

Both stages are complete and verified.

## Files created

`test_helpers/` (9 modules): `__init__.py`, `types.py`, `api_client.py` (every PRD endpoint), `api_errors.py` (all 59 `ERR_*` ids), `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`.

`test_suite/`: `conftest.py` + 22 test modules, **116 tests**.

| file | tests | file | tests |
|---|---|---|---|
| test_01_operating_hour_determination | 8 | test_12_validation_priority_pairs | 6 |
| test_02_monitoring_system_qa_and_calibration | 5 | test_13_entity_creation_shape_and_defaults | 4 |
| test_03_out_of_control_cascade | 5 | test_14_entity_input_rejection_and_not_found_codes | 4 |
| test_04_missing_data_substitution_and_availability | 6 | test_15_entity_listing_ledgers_and_associations | 5 |
| test_05_rata_statistics_and_retest_loop | 6 | test_16_state_machine_starts_loops_and_lockdown | 6 |
| test_06_rata_cross_entity_and_window_resource | 6 | test_17_calculation_input_sets_and_boundaries | 5 |
| test_07_report_lifecycle_and_certified_ledger | 6 | test_18_validation_bounds_uniqueness_and_guards | 6 |
| test_08_allowance_true_up_waterfall_and_cascade | 6 | test_19_endpoint_shapes_bulk_and_substitution | 6 |
| test_09_allowance_tonnage_conservation | 4 | test_20_authentication_scope_and_retest_references | 4 |
| test_10_control_outage_windows | 6 | test_21_role_partition_and_shared_reads | 4 |
| test_11_rolling_window_sample_boundary | 4 | test_22_stale_version_guards_and_immediate_consistency | 4 |

Queue A (test_01–12): 68 tests. Queue B (test_13–22): 48 tests.

## Instances translated vs skipped

- **Difficulty (§1.8): 30/30 translated**, every one with >=2 tests (checker: `difficulty missing:` empty, `<2 tests: []`).
- **Corner (§1.9): 73 instances = 41 live + 32 `excluded_because:` stubs. All 41 live translated; 0 stubs translated** (by design — their only requirement is a resolving `difficulty_instance:` pointer, and all 32 resolve).
- **Zero instances skipped for PRD-coverage reasons.** No `skip`/`xfail`/placeholder markers anywhere.
- 71 distinct `Design:` tags across 116 tests; every test carries exactly one tag; no untagged, dual-tagged, or dangling tags.

## Verification

`python3 -m compileall` clean; `pytest --collect-only` -> 116 collected, 0 errors; citation checker -> `checked files: 22 missing: 0` (every `PRD: "..."` block is a verbatim, whitespace-normalized substring of `workspace/PRD.md`); no emitted file mentions the word "scaffold".

## Design-vs-PRD gaps found (PRD followed in every case)

1. `entity_facility_creation_returns_every_declared_field` asserts `Facility.status == ACTIVE`; PRD line 185 declares `OPERATING`.
2. `entity_child_create_under_an_unknown_parent_returns_the_parent_code` demands `ERR_UNIT_NOT_FOUND` "not `ERR_INVALID_REQUEST`" for a malformed body under an unknown parent; PRD line 147 orders shape before existence -> `ERR_INVALID_REQUEST`.
3. Same instance names a field `calibration_error_pct`; the PRD's fields are `zero_error_pct_of_span` / `span_error_pct_of_span`.
4. Several corner recipes assert `created_at == "2026-08-01T00:00:00Z"`; PRD §2.5 pins timestamps to three fractional digits, so exact-string equality with the clock value is unsatisfiable — asserted `created_at == updated_at` plus a format check instead.
5. Difficulty invariant #1 claims HTTP 409 for `ERR_INSUFFICIENT_ALLOWANCES`; PRD §5 maps it to 422.
6. Difficulty invariant #2 uses `submission_format: "XML"`, not in the PRD enum (`XML_ECMPS` / `JSON_ECMPS`).
7. `ep_substitution_runs_only_over_unavailable_hours` names constants `TIER2_MIN_AVAILABILITY_PCT` / `TIER3_MIN_AVAILABILITY_PCT`; the PRD's names are the tier-2/tier-3 availability thresholds exported as `TIER_2_AVAILABILITY_PCT` / `TIER_3_AVAILABILITY_PCT`.
8. `val_applicable_standard_basis_is_reserved_for_low_emitters` supplies the RA-10.7 (failing) run set while asserting `PASSED` with `relative_accuracy_pct == 10.0`.
9. `ep_substitution_runs_only_over_unavailable_hours` asserts `monitor_data_availability_pct_at_substitution == 80.0` and method `T3_LOOKBACK_MAXIMUM`; PRD line 282's per-hour availability excludes the hour itself and all later hours -> 100.0 and `T1_90TH_PERCENTILE` (the substituted value 220.0 ppm / 292.2 lb is the same either way).
10. `err_retest_must_cite_a_failed_unclaimed_audit_of_the_same_system` swaps its two run sets — the audit labelled FAILED (RA 10.7) is given the RA-10.0 runs and vice versa.

Minor, nothing asserted on it: the rbac/errors recipes cite the `FacilityOperator` scope rule as "priority=5" and the role rule as "priority=3"; the PRD numbers them 4 and 3.

## Step 6: Generate implementation — 2026-09-01T13:26:39.644Z

The implementation is complete and verified end-to-end.

## Files (all under `.../task_2236_emissions_monitoring_allowance_compliance/workspace/implementation/`)

| file | lines | role |
|---|---|---|
| `start.sh` | 10 | launcher (chmod +x) |
| `requirements.txt` | 1 | `flask>=2.0` |
| `app.py` | 88 | app factory, 12 blueprints, error handlers, `$PORT` entry point |
| `constants.py` | 184 | every enum, threshold, factor, role name, error catalogue input |
| `db.py` | 90 | `Store` = 14 in-memory dicts, logical clock, `public()`/`touch()`/`sort_rows()` |
| `errors.py` | 95 | `ERROR_STATUS` map for 60 error ids, `ApiError`, `fail()` |
| `util.py` | 128 | `Decimal` + ROUND_HALF_UP helpers (`rhu`, `rhu_dec`, `ceil_int`, `D`), ISO-8601 parse/format |
| `response.py` | 48 | `meta`/`response_type`/`data` envelope, `api_request_id`, array/plain-array/error responses |
| `middleware.py` | 58 | header auth (steps 1–3), FacilityOperator scope (step 10) |
| `validation.py` | 242 | shape/enum/range/pagination/filter primitives (steps 6, 7, 95) |
| `lookup.py` | 127 | `find`/`get` (path 404s), `require_child_of` (belongs-to-parent 404s), relationship queries |
| `services/calc.py` | 347 | the 11 calculations |
| `services/hours.py` | 198 | hour build + append finalisation, substitution tiers |
| `services/reports.py` | 87 | report recomputation/aggregation |
| `services/permits.py` | 95 | limit evaluation, excess-event raise/withdraw |
| `services/cascade.py` | 61 | out-of-control cascade |
| `services/allowances.py` | 383 | settlement, true-up cascade, compensation cascade, posture/dispatch |
| `routes/*.py` | 2 188 total | 12 blueprints (see below) |
| **total** | **4 729** | |

## Module layout / endpoint organisation (65 = 65)

`app.url_map` was diffed programmatically against the PRD §4 table: **65 impl / 65 PRD, no missing, no extras.** Per blueprint: `quarterly_reports` 12 (387 ln), `monitoring_systems` 8 (318), `allowances` 8 (310), `rata_tests` 6 (266), `facilities` 5 (185), `operating_hours` 5 (330), `excess_events` 5 (118), `fuel_samples` 4 (145), `permit_limits` 4 (115), `control_outages` 4 (180), `units` 3 (89), `clock` 1 (44). Routes stay thin: they run the ladder in order and delegate arithmetic/cascades to `services/`.

**Calculations** all live in `services/calc.py` (heat input by 3 methods, SO2/NOX/CO2 mass, calibration error percentages, RATA statistics + relative accuracy + bias, rolling permit windows, missing-data substitution tiers with nearest-rank percentiles, availability, exceedance/penalty figures), pure `Decimal` with ROUND_HALF_UP; `round()` and float math are never used for stored values.

**Validation ladder** is enforced by construction, not by convention: each handler calls, in fixed order, `authenticate()` (1–3) -> `enforce_facility_scope()` (10) -> segregation (40, only certification sign, which deliberately precedes shape) -> `body_dict()/*_field()` (90) -> `pagination()` (95) -> `get()` path 404s (100) -> body-FK `get()` (110) -> `require_child_of()` (120) -> OCC (200) -> state (210+) -> safety (300+) -> fiscal (400+). Uncatalogued uniqueness/format violations report `ERR_INVALID_REQUEST`.

**OCC** on exactly the 5 declared endpoints (daily calibration, single hour append, bulk hour append, certification sign, transaction proposal); the guard field is parsed before the FK/state checks it must precede and compared at ladder step 200.

**Cascades** — out-of-control (`services/cascade.py`), true-up (`run_true_up`) and compensation (`reverse_settled_transaction`) each implement their four links in one function so links cannot be skipped. Allowance tonnage is conserved: settlement stores exact `debited_prior/current/next_tons` and reversal credits back precisely those amounts; only `holdings_next_vintage_tons` may go negative.

## `start.sh`

`exec python3 app.py` in the foreground (no `&`, no daemon); `app.py` binds `host="0.0.0.0"`, `port=int(os.environ.get("PORT", "10000"))`, `use_reloader=False`. Verified by cold boot on the default port: it listened on `0.0.0.0:10000` and answered `GET /emissions/facilities?limit=5` with an empty array and a correct envelope. pip install is conditional on flask being absent, so per-test reboots don't contend.

## Verification

Two end-to-end smoke passes against a live server (scripts kept outside the task dir, in `/tmp`), the second finishing **0 failures**, covering: facility/unit/system creation, calibration ladder + staleness sweep via `_clock` (CAL_CURRENT->CAL_EXPIRED, parallel to an unchanged `qa_status`), the FAILED-RATA loop (`FAILED`->`SCHEDULED` on the same row, attempt 2, runs cleared) plus `ERR_RA_BASIS_NOT_PERMITTED` and the permitted low-emitter `APPLICABLE_STANDARD` denominator, hour append/bulk/duplicate/method-mismatch/OCC negatives, substitution tiers, report validate->submit->certify->reject->reopen->recertify->accept with certification revocation debiting the unit ledger, permit evaluation -> excess event -> RETURN loop -> ENFORCE, the shortfall true-up cascade (obligation 279 = ceil(0.786) + 278 event debit, surrendered 5, shortfall 274, penalty 548 driving `holdings_next` to -546, `TRUE_UP_LOCKED`, posture `DEFICIT`, dispatch restricted with ONLINE->RESERVE_SHUTDOWN), the compensation cascade restoring holdings exactly and returning the account to `OPEN`/`COMPLIANT`, transfer settle+reverse conservation across two accounts, control-outage overlap/activate/close/cancel, and the auth/scope/pagination negatives. Earlier SCAFFOLD worked-example figures still reproduce exactly (1388.889 mmBtu, 502.8 lb SO2, 208.3 lb NOx, 149.25 t CO2, availability 80.0).

Storage is in-memory only (`grep` for `open(`/sqlite/json.dump/pickle/`/tmp` returns nothing), the store is empty immediately after import (asserted programmatically), nothing is seeded, and all `__pycache__` dirs plus both smoke servers were cleaned up. I did not read or write anything under `test_suite/`, `test_helpers/`, the two design YAMLs, or any sibling task.

## Step 7: Run tests and iterate — 2026-09-01T13:58:13.895Z

All tests pass. Two consecutive full 8-round parallel sweeps came back clean: **8/8 rounds × 116/116 tests** (1856 green test executions), the second of them while another agent's 8-round sweep was running concurrently on the same host.

## Summary

**Iterations run:** 3 full 8-round sweeps (sweep 1 diagnostic at 99/116 per round; sweeps 2–3 after fixes; sweep 2 had a single non-assertion transport flake, sweeps 3–4 fully green), plus one fast targeted subset run between sweeps.

**Tests deleted:** none (no whole test was deleted). Five individual assertions were removed for PRD silence:

| File | Assertion removed | PRD-silence category |
|---|---|---|
| `test_suite/test_05_rata_statistics_and_retest_loop.py` | `passing["standard_deviation"] == 0.008038` and `failing["standard_deviation"] == 0.007401` (2 tests) | COMPUTED-FIELD SILENCE — PRD §2.6 names the sample standard deviation only as "the intermediate sample standard deviation carried to six decimal places", never as a response-visible attribute. Scaffold rule driving generation: RATA statistic precision. |
| `test_suite/test_08_allowance_true_up_waterfall_and_cascade.py` | `before["compliance_posture"] == "WATCH"` immediately after opening an allowance account | BRANCH-ASYMMETRIC SIDE EFFECT / trigger silence — PRD §3.9 enumerates posture-recompute triggers (settlement, reversal, true-up, report submission/certification/disposition, event enforcement); account opening is not among them. Scaffold rule: shortfall cascade posture flip. |
| `test_suite/test_09_allowance_tonnage_conservation.py` | `proposed["allowance_account_version_after"] == 2` | DEFAULT-VALUE SILENCE — PRD's "always at least 2" applies to daily calibrations and operating hours, not accounts; PRD says an accepted proposal has "no holdings moved yet". Scaffold rule: allowance tonnage conservation. |

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — `create_facility()`: `true_up_deadline_utc` was passed both explicitly and via `**overrides`, so any test overriding it raised `TypeError: facility_payload() got multiple values`. Now `overrides.setdefault("true_up_deadline_utc", TRUE_UP_DEADLINE)`, so an explicit override wins (2 tests unblocked).

**Fixes applied to `test_suite/` (all made tests *more* PRD-faithful; no assertion weakened):**
- `test_06_rata_cross_entity_and_window_resource.py` — two fixtures drove `OFFLINE → RESERVE_SHUTDOWN` directly, which PRD §3.1 forbids ("exactly four moves are permitted"). Now routed through `ONLINE`; the version assertion in `test_the_identical_payload_succeeds_once_the_unit_is_online` updated 3 → 4 to match the third dispatch patch.
- `test_07_report_lifecycle_and_certified_ledger.py` — `signed_utc` expected `...T00:00:00Z`; PRD §2.5 mandates three fractional digits on server-minted timestamps → `2026-04-02T00:00:00.000Z`.
- `test_10_control_outage_windows.py` — same precision bug in 3 places; added a distinct `CLOCK_STAMP = "2026-08-01T00:00:00.000Z"` for server-stamped comparisons, leaving `CLOCK` as the clock *input*.
- `test_17_calculation_input_sets_and_boundaries.py` — `validate_paginated` returns `(data, meta)`; the test compared the meta dict to an int. Now `transactions, tx_meta = ...` / `tx_meta["total_count"] == 1`. (Audited every other `validate_paginated` call site — no further misuses.)

**Fixes applied to `implementation/`:**
- `workspace/implementation/services/cascade.py` — `demote_system_out_of_control(...)` gained a `fail_calibration=True` parameter; the `cal_status = "CAL_FAILED"` write is now conditional. PRD §3.2 puts that write in link one of the *calibration-driven* cascade only, states a QAAnalyst declaration "runs the identical link two, three and four chain", and explicitly declares `OUT_OF_CONTROL` + `CAL_CURRENT` legitimate.
- `workspace/implementation/routes/monitoring_systems.py` — `transition_qa_status()`, `DECLARE_OUT_OF_CONTROL` branch now calls `demote_system_out_of_control(..., fail_calibration=False)` then `run_links_two_to_four(...)`, so a declaration moves only the QA axis. This single fix cleared 5 failures whose setups died on `ERR_CALIBRATION_NOT_CURRENT`. No PRD-required check was removed or weakened; storage remains in-memory dicts only.

**Note on the one flake in sweep 2** (`test_recording_runs_is_refused_while_the_unit_is_not_dispatching`, `ConnectionResetError(104)` on the fixture's 4th request): traced through `/tmp/prd_bench_server_55721.log` — the server had booted cleanly, served the readiness probe plus 3 requests, then printed `Killed` mid-test with no Python traceback and no bind error across all 116 boots. That is an external SIGKILL of the server process (host contention — a second agent session's 8-round sweep was running concurrently, and `~/.cache/prd-bench-local-runner/ports.tsv` showed 9 holders), not a defect in PRD.md, `test_suite/`, `test_helpers/`, or `implementation/`. It did not recur across the following 16 clean rounds, so no code change was made for it.

Orchestrator verification: all 8 `results.{1..8}.json` read back `passed 116 / total 116`.

## Step 8: Finalize PRD — 2026-09-01T14:05:10.142Z

Done. `PRD_FINALIZED.md` written with 5 inline edits, no new sections.

## Line counts / delta
- `PRD.md`: 485 lines, 13,630 words, 100,583 chars
- `PRD_FINALIZED.md`: 485 lines (unchanged — all edits inline), 13,892 words (+1.92%), 102,244 chars (+1.65%)

## Changes (one bullet each)
- **§3.2 (DECLARE_OUT_OF_CONTROL)** — revise — "running the full four-link cascade" -> "running the link two, three and four chain", plus an explicit statement that a declaration moves the QA axis only, leaving `cal_status` and `consecutive_failed_calibrations` alone, so `OUT_OF_CONTROL` + `CAL_CURRENT` is the normal declared state — `implementation/services/cascade.py:55-70`, `implementation/routes/monitoring_systems.py:196-197`
- **§2.6 (relative accuracy precision bullet)** — insert — the sample standard deviation is an internal intermediate feeding `confidence_coefficient`, not persisted and not a field of the audit resource — `implementation/services/calc.py:249-258`, `implementation/routes/rata_tests.py:172-181`
- **§2.5 (audit fields)** — insert — `allowance_account_version_after` semantics: stamped at transaction creation, re-stamped after the movement only when the transaction actually moves holdings (settlement, the true-up that created it, reversal of a settled row); the "always at least 2" floor does not apply to it — `implementation/services/allowances.py:60,211,303,324-325,379`
- **§3.9 (proposal paragraph)** — insert — an accepted proposal's `allowance_account_version_after` is the account's current, unchanged `version` (equal to the `expected_allowance_account_version` it had to match) — `implementation/services/allowances.py:60`, `implementation/routes/allowances.py:178-222`
- **§3.9 (facility compliance posture)** — insert — posture is a stored field, not derived at read time, and opening an allowance account is not a recompute moment, so the facility keeps its prior posture — `implementation/routes/allowances.py:81-99`, `implementation/routes/facilities.py:86,113-117`, `implementation/services/allowances.py:97-127`

## Per-edit pre-edit search log
1. **§3.2 declaration** — (a) subject: every write a QA declaration makes to the monitoring-system row, especially `cal_status`. (b) enumerated: `grep 'cal_status"] *='` -> `routes/clock.py:38` (26-hour expiry -> `CAL_EXPIRED`), `services/cascade.py:67` (now conditional on `fail_calibration`), `routes/monitoring_systems.py:251/254` (calibration verdict), plus both `demote_system_out_of_control` callsites (`monitoring_systems.py:196` declaration `fail_calibration=False`; `:265` calibration path default `True`), the `CERTIFY` cal guards (`:172-177`), and `services/hours.py:59-68` `classify_hour` which reads both axes. (c) adjustment: dropped an initial "therefore immediately restorable by CERTIFY" clause — `CERTIFY` also has the no-`FAILED`-RATA guard (`monitoring_systems.py:170`), so the claim would have been a false universal; re-worded to "which is precisely the state the stricter `CERTIFY` guard above demands". Also deliberately left the PRD's silence about an absent `effective_utc` intact (impl falls back to the logical clock) rather than widening scope.
2. **§2.6 standard deviation** — (a) subject: whether the sample standard deviation is a response-visible field. (b) enumerated: `grep 'sample_stdev|stdev|standard_dev'` -> only `util.py:60`, `services/calc.py:43,249,256`; `routes/rata_tests.py:172-181` consumes the stats dict and stores only `reference_mean`/`cems_mean`/`mean_difference`/`confidence_coefficient`; `db.public()` (`db.py:56-60`) strips only `_`-prefixed keys, so nothing leaks it; `reschedule_rata` (`:253-262`) has no sd to clear. (c) no adjustment needed.
3. **§2.5 `allowance_account_version_after`** — (a) subject: when the field is written and what value it carries. (b) enumerated: `grep version_after` -> `services/allowances.py:60` (creation), `:211` (settle, after `refresh_account_figures`+`touch(account)`+`posture_and_dispatch`), `:303` (true-up zero-shortfall branch), `:324-325` (true-up shortfall branch, after the link-two account bump), `:379` (reversal of a settled row); `routes/allowances.py:269-307` shows `RECORD` and reversal-of-`RECORDED` do **not** re-stamp it; also checked `services/hours.py:121,147` and `routes/monitoring_systems.py:280` so the untouched "always at least 2" claim for the two ledger types stays true. (c) adjustment: first draft said the value is the account version "once the operation ... has finished with the account row", which would wrongly imply `RECORD` refreshes it; re-worded to "re-stamped ... whenever the transaction actually moves holdings — at settlement, at the true-up that created it, and at the reversal of a settled row", and explicitly excluded a bare `RECORD`.
4. **§3.9 proposal** — (a) subject: same field at the proposal site. (b) enumerated: `routes/allowances.py:161-222` (version guard at `:178`, then `allowances.new_transaction` at `:213`), `services/allowances.py:44-65`; confirmed nothing in the proposal path calls `touch(account)`. (c) no adjustment; wording ties the reported value to the guard value, which is exactly the impl invariant.
5. **§3.9 posture** — (a) subject: what recomputes `compliance_posture` and whether it is stored or derived on read. (b) enumerated: sole writer `services/allowances.py:97-127`; callers via `posture_and_dispatch` -> `allowances.py:210` (settle), `:304` and `:328` (both true-up branches), `:382` (reversal), `routes/excess_events.py:116` (ENFORCE), `routes/quarterly_reports.py:205` (submit), `:262` (sign), `:328` (certification revoke), `:367` (disposition); initial value `routes/facilities.py:86`; reads `routes/facilities.py:113-117` and list-filter `:94-110` both use the stored value; `routes/allowances.py:81-99` (`open_account`) has no recompute; `reopen_report` (`quarterly_reports.py:371-387`) has none either. (c) adjustment: avoided any "recomputed **only** at these moments" phrasing, because impl also recomputes on certification revocation (a trigger the PRD's list does not name, and behaviorally a no-op since `SUBMITTED` and `CERTIFIED` both feed the projection). The committed wording asserts only the two facts the impl guarantees everywhere: the posture is stored rather than read-derived, and opening an account does not recompute it.

## Step 9: Complete PRD — 2026-09-01T14:26:19.289Z

§4's endpoint table cross-check is complete: all 65 rows map 1:1 onto the 65 `@bp.route` decorators across the 12 registered blueprints, with identical methods, paths and role tuples (`grep authenticate` confirms every non-`ANY_ROLE` gate), and the line-355 claim about 201-on-create / 200-otherwise holds for every handler. No edit was needed there. §5's error catalogue likewise matches `errors.py`'s `ERROR_STATUS` exactly.

## Exit summary

- **Source**: `workspace/PRD_FINALIZED.md` — 485 lines, 102244 chars
- **Result**: `workspace/PRD_COMPLETED.md` — 485 lines, 114968 chars
- **Char delta**: **+12724** (line count unchanged — every pin is an in-paragraph insert or revision; no new paragraphs, no new sections)
- **Ambiguity-pins: 36** · **Mismatch-revisions: 10** (46 discrete changes over 39 lines)

### Changes

- §2.1 — revise — mismatch — scope compares the facility reached through the *path* only; "or body" removed — `middleware.py:45-53`
- §2.1 — insert — ambiguity — scope check skipped entirely when the path id does not resolve, falling through to the 404 — `middleware.py:50-51`
- §2.3 — insert — ambiguity — ordering ties broken by insertion sequence; descending is that same order reversed — `db.py:83-90`
- §2.3 — insert — ambiguity — `has_more` is `offset + len(returned) < total_count` — `response.py:31`
- §2.3 — insert — ambiguity — unparseable/non-member filter value -> `ERR_INVALID_REQUEST` 400; undeclared query param ignored — `validation.py:177`
- §2.4 — revise — ambiguity — clock `data` holds exactly two fields, `current_utc` echoed verbatim, expired ids in `created_at` ascending — `routes/clock.py:25-43`
- §2.5 — insert — ambiguity — all eleven client-supplied timestamps stored/echoed verbatim, never renormalised; derived fields inherit that spelling — `validation.py:112`
- §2.8 — insert — ambiguity — the five uniqueness/cross-field `ERR_INVALID_REQUEST` rules are evaluated at their own sections' points, not at the ladder's generic slot — `routes/facilities.py:166`, `monitoring_systems.py:239`
- §2.8 — insert — ambiguity — a present-but-blank mandatory reason counts as absent -> `ERR_REASON_REQUIRED` — `routes/control_outages.py:174`
- §2.8 — revise — ambiguity — full enumeration of the range-checked numeric fields and their bounds — `validation.py:217`
- §2.10 — insert — ambiguity — caveat that the reversed-`TRANSFER_OUT` counterparty unwind is the one further unguarded movement — `services/allowances.py:345-350`
- §3.1 — revise — ambiguity — `max_concurrent_control_outages` accepted 0 through 10 inclusive, 0 being legal — `routes/facilities.py:67`
- §3.1 — insert — **mismatch** — that bound is checked **before** the `orispl_code` uniqueness rule, not at its §2.8 position — `routes/facilities.py:67-71`
- §3.1 — insert — ambiguity — facility PATCH is a plain field patch: no state precondition, `RETIRED` reversible, empty patch still bumps `version` — `routes/facilities.py:120-145`
- §3.1 — insert — **mismatch** — PATCH checks the ceiling bound before resolving the facility id (`ERR_VALUE_OUT_OF_RANGE` beats `ERR_FACILITY_NOT_FOUND`) — `routes/facilities.py:128-130`
- §3.1 — insert — ambiguity — duplicate `unit_identifier` -> `ERR_INVALID_REQUEST`, checked after the two numeric bounds — `routes/facilities.py:161-166`
- §3.1 — revise — ambiguity — unit capacity/heat-input bounds report `ERR_VALUE_OUT_OF_RANGE` — `routes/facilities.py:161-162`
- §3.1 — insert — ambiguity — dispatch never touches `control_status`; only outage transitions move it; `DEGRADED` is never assigned — `routes/units.py:87`, `control_outages.py:154,168`
- §3.1 — revise — ambiguity — outage `control_device` mismatch -> `ERR_INVALID_REQUEST` **before** the interval and overlap rules — `routes/control_outages.py:50-54`
- §3.2 — insert — ambiguity — `DECLARE_OUT_OF_CONTROL` anchors at the logical clock when `effective_utc` is omitted — `routes/monitoring_systems.py:194-195`
- §3.2 — revise — ambiguity — duplicate `calibration_utc` -> `ERR_INVALID_REQUEST`, after the version guard and the retired check — `routes/monitoring_systems.py:237-239`
- §3.2 — insert — ambiguity — link four is unconditional; links two/three are input-driven, so with no flipped hour the unit's `data_availability_pct` and every report `version` stand unchanged — `services/cascade.py:35-50`
- §3.3 — insert — ambiguity — scheduling imposes no condition on the audited system's `qa_status`; a `RETIRED` system is schedulable — `routes/rata_tests.py:56-113`
- §3.3 — revise — ambiguity — retired system at the runs step is `ERR_INVALID_STATE_TRANSITION`, immediately after the `SCHEDULED` precondition and ahead of dispatch/run-count — `routes/rata_tests.py:159-160`
- §3.5 — insert — ambiguity — version guard skipped when no report resolves (`ERR_HOUR_OUTSIDE_REPORT_PERIOD` wins); evaluated ahead of duplicate/sample/on-the-hour/method/range when one does — `routes/operating_hours.py:179`
- §3.5 — revise — ambiguity — `op_time_fraction`'s two decimals are convention, not a constraint; 0.125 accepted verbatim — `routes/operating_hours.py:100-108`
- §3.5 — revise — ambiguity — SO2 bias system selection (live before retired, then newest created; 1.0 when no SO2 system); `nox_mass_lbs` null when the rate is absent — `services/hours.py:_pick`, `services/calc.py:86-88`
- §3.5 — revise — ambiguity — Appendix-D NOx likewise null when the rate was not supplied — `services/calc.py:99-101`
- §3.5 — insert — ambiguity — governing system for data quality chosen by the same rule and treated as absent (never forcing `UNAVAILABLE`) when the unit owns none — `services/hours.py:_pick`
- §3.5 — insert — ambiguity — bulk: empty array rejected first / >200 rejected last; guard = earliest resolving report; intra-array duplicates caught; bare 201 array with no pagination `meta` — `routes/operating_hours.py:110-111,211,225,244,255`
- §3.6 — revise — **mismatch** — unit `data_availability_pct` refreshed only by the three hour-level operations, never by report validation; latest `(year, quarter)` touched wins — `services/reports.py` `recompute_unit_availability_for_periods`, `routes/quarterly_reports.py:147-187`
- §3.6 — revise — **mismatch** — lookback tier requires `so2_conc_ppm` actually present, so Appendix-D hours never contribute — `services/calc.py:160-161`
- §3.6 — revise — **mismatch** — substituted concentration rounded half up to zero decimals (12.5 -> 13) and the stored whole number drives the mass; Appendix-D flow counts as 0 -> `so2_mass_lbs` 0.0 — `services/hours.py:179`, `services/calc.py:108`
- §3.6 — insert — ambiguity — substitution bumps each report `version` but does **not** revert `VALIDATED`; bare 200 array, no pagination `meta` — `services/hours.py:196`, `routes/operating_hours.py:330`
- §3.7 — revise — **mismatch** — rejection's implicit revocation stamps `revoked_utc` and bumps `version` but leaves `revocation_reason` null (the reason lands on the report as `rejection_reason`) — `routes/quarterly_reports.py:355-362`
- §3.8 — insert — ambiguity — evaluate returns the permit limit, never the event; every evaluation is a write and bumps `version` even on an identical verdict — `routes/permit_limits.py:107-140`, `services/permits.py:36`
- §3.8 — revise — **mismatch** — a zero `LB_PER_MMBTU` heat-input sum falls back to `INSUFFICIENT_DATA` with null `current_rolling_value` — `services/calc.py:324-325`, `services/permits.py:28-29`
- §3.8 — insert — ambiguity — `INSUFFICIENT_DATA` also withdraws `DETECTED` events, exactly as `IN_COMPLIANCE` does — `services/permits.py:40`
- §3.8 — revise — ambiguity — `narrative`/`corrective_action` must be >=1 char (`ERR_INVALID_REQUEST`, not `ERR_REASON_REQUIRED`); whitespace-only accepted — `validation.py:48`, `routes/excess_events.py:53-70`
- §3.9 — insert — ambiguity — a `program` the facility does not hold -> `ERR_INVALID_REQUEST`, checked as soon as the facility resolves — `routes/allowances.py:67`
- §3.9 — revise — **mismatch** — duplicate-account rule evaluated **before** the `compliance_year`/holdings bounds — `routes/allowances.py:69-79`
- §3.9 — revise — ambiguity — `RECORD` applies no account lock check; the lock bites at settlement — `routes/allowances.py:269-274`
- §3.9 — revise — ambiguity — surrender row created unconditionally (0.0 possible); true-up returns the account, and `allowance_account_version_after` is the post-cascade version — `routes/allowances.py:154`, `services/allowances.py`
- §3.9 — insert — ambiguity — reversing a `TRANSFER_OUT` debits the counterparty by full `quantity_tons`, unguarded, bumping its `version` — `services/allowances.py:345-350`
- §3.9 — revise — ambiguity — reversed `TRUE_UP_PENALTY` rows get `version` +1 and the same `reason` copied to `reversal_reason` — `services/allowances.py:363`
- §3.9 — revise — **mismatch** — posture recompute moments pinned: settlement, reversal of a **settled** row only, true-up, submission, certification, revocation, disposition (both `ACCEPT` and `REJECT`), event enforcement — `services/allowances.py` `posture_and_dispatch`, `routes/quarterly_reports.py` `_refresh_posture`

Deliberately left unpinned (unreachable in impl, so pinning would invent behavior): `bias_adjustment` with `cems_mean == 0`, clock expiry with `_last_calibration is None`, a second `SIGNED` certification on one report, and `find_open_report` ambiguity (moot — the duplicate-period check spans all statuses). Ordering divergences that are already correctly pinned by the §2.8 ladder (CERTIFY's RATA-before-calibration, retest-before-window, duplicate-report-period-before-range, duplicate-monitoring-system-before-range) were left untouched.
