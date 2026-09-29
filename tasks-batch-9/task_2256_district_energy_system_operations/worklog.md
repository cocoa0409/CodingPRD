# Worklog — task_2256_district_energy_system_operations

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2256_district_energy_system_operations/` and `tasks/task_2256_district_energy_system_operations/workspace/`.

## Step 2: Generate scaffold — 2026-09-01T12:58:24.000Z

All three artifacts are complete, lint-clean, and audited.

## Output
`/home/ubuntu/github/CodingPRD/tasks/task_2256_district_energy_system_operations/`
- `SCAFFOLD.yaml` (2792 lines) — §1.0–§1.7 only; top-level keys are scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles (neither design key present).
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1807 lines) — single key `scaffold_difficulty_design`.
- `SCAFFOLD_CORNER_DESIGN.yaml` (4489 lines) — single key `scaffold_corner_design`.

## Counts
- **14 entities** (NetworkLoop, PipeSegment, FuelSupplyContract, ProductionAsset, LoadForecast, DispatchPlan, DispatchOrder, RateSchedule, ConnectionAgreement, MeteringPoint, MeterReading, Invoice, WorkOrder, ExpansionProject), graph topology.
- **11 state machines** (cyclic shape), **2 OCC concurrency rules** (loop version → dispatch-plan create; agreement version → invoice create).
- **10 calculations**, including `merit_order_dispatch` (waterfall with thermal storage), `plan_reliability_metrics` (N-1 reserve margin + fuel-diversity HHI), `segment_leak_risk_score` (weighted scoring), `invoice_billing_determinants` (12-step tiered/ratcheted billing with dual variants), pipe-sizing/NPV expansion economics, emissions intensity vs. city goal.
- **54 ordered validations**, **72 endpoints** (42 POST + 30 GET, no PUT/PATCH/DELETE), **54 errors**, **6 roles** with segregation of duties.
- `complexity_profile`: `difficulty_band: beyond_expert`, primary archetype quota_allocation_engine, secondary pricing_billing_engine, 6 complexity layers (dual_variant_calculation, cascading_side_effects, optimistic_concurrency, selector_policy, derived_field_reconciliation, rate_threshold_triggers).

## Design instances
- **§1.8: 18 instances** (9 difficulty rules × 2).
- **§1.9: 56 instances** across all nine claim-extraction-guide sections — Entities 12, State Machines 13, Calculations 11, Validations 8, Endpoints 6, Errors 10, RBAC 4, Cross-Cutting Complexity Layers 6, Consistency Model 1. Six of the Cross-Cutting/other corners are `excluded_because` stubs citing §1.8 instances by exact name.

## Audits
- `scaffold_lint.py` from repo root: **VERDICT: clean lint** over 1082 scanned calls (72 endpoints, 14 entities, 18 + 56 instances).
- Error coverage: **54/54 error ids** triggered somewhere across the two design files, 0 unreferenced.
- Endpoint coverage: **72/72** endpoints appear as `call:` entries (the last 6 collection GETs are covered by the dedicated filter/paginate instance).
- Replay audits over all 89 recipes: every recipe opens with `POST /_clock/set_current_utc`; every `expected_*_version` is a `${var}` captured earlier (no literals); no meter reading precedes its commission; no payment precedes issue. Three lifecycle-ordering flags (review-without-submit, commit-without-review) are the intentional invalid-from-state negatives and each asserts 409 `ERR_PLAN_STATE_INVALID` with the entity unchanged.
- Query-param validator over all `call:` entries: 0 problems (no undeclared filters). Prose-GET validator's 17 hits were regex false positives from `grounds: endpoints[GET ...]` brackets.
- Forbidden concurrency vocabulary sweep across all three files: 0 matches.
- All numeric literals in asserts were machine-verified with a Decimal/ROUND_HALF_UP harness (`/tmp/de_verify.py`), including tier-boundary pairs (load factor exactly 30.00 vs 30.01), arrears threshold pairs (total 25000.00 stays CURRENT vs 25000.01 flips to IN_ARREARS), leak-band boundary (score exactly 70.00 SUSPECT vs 69.96 MONITORED), and capacity ceiling (5000.0 accepted vs 5000.01 rejected).

## Step 3: Copy shared files — 2026-09-01T12:58:24.000Z

Copied `INSTRUCTION.md` → `tasks/task_2256_district_energy_system_operations/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T13:15:00.000Z

PRD generated at `workspace/PRD.md`.

**Size and structure:** 508 lines, ~13,700 words, 24 headings.

- §1 Introduction — 3 paragraphs (district heating/cooling utility; production, distribution and commercial coupling; the reproducibility and segregation-of-duties commitments)
- §2 Global Specifications (10 subsections): 2.1 User and Role-Based Access Control, 2.2 API Response Structure (pasted byte-identical from `section-2.2-response-structure.md`, verified), 2.3 Pagination, 2.4 Collection Filters, 2.5 Resource Identity/Timestamps/Version Counter, 2.6 Numeric Precision and Rounding Discipline, 2.7 Stale-Version Guards, 2.8 Loop Posture: the Network's Master Interlock, 2.9 Path Resolution and the Request Admission Ladder, 2.10 The Logical Clock
- §3 Business Logic (9 subsections): loop and buried network setup; supply contracts, assets and availability cascades; 24-hour forecast block; merit-order dispatch, resilience gates and commitment; tariffs, agreements and capacity reservation; thermal metering; billing determinants, invoice lifecycle and the arrears ledger; leak detection, permits and field work; expansion economics and climate-goal reporting
- §4 Endpoint Definitions — 4-column table, 72 rows, verified method/path/roles-identical to the scaffold
- §5 Error Code Catalogue — 2-column table, 54 rows, in scaffold order with statuses verified

**Coverage audit (all three Hard Contracts machine-verified against the scaffold):**

Field coverage check: entities[].fields 125/125; endpoints request_body/input 97/97; query_params covered; path_params 14/14; computed output keys 10/10. Status: PASS

Rule coverage check: validations 54/54 (17 priority levels); OCC rejections 2/2; state transitions 77/77 across 11 machines; calculations 10/10; error_id matchability 54/54; side_effects 103/103; entity field structured content 125/125; sibling-branch symmetry 14 groups, 0 asymmetric. Status: PASS

Path purity check (§3 only): 926 backtick tokens scanned, 0 starting with `/`, 0 bare HTTP-method tokens, 0 combined method+path tokens. Status: PASS

**Notes / gaps found and repaired during verification:**
1. Six pure-path identifiers (`contract_id`, `order_id`, `reading_id`, `invoice_id`, `work_order_id`, `project_id`) initially appeared only inside full backticked paths in §4. Added an explicit path-identifier paragraph to §2.9, which also documents a real trap: a fuel supply contract is addressed in the path as `contract_id` but referenced from a body as `fuel_contract_id`.
2. `ERR_METER_STATE_INVALID` on meter removal and `ERR_INVOICE_STATE_INVALID` on payment/void were only covered by the generic §2.9 ladder; now named at their respective transitions.
3. Invoice creation's `ConnectionAgreement.version` increment was implicit; now stated.
4. Added explicit initial-value enumerations for `LoadForecast.contributing_agreement_count`, the six `DispatchPlan` metric fields, and `Invoice.paid_amount`/`invoice_state`.
5. Removed one banned fuzzy word ("conservatively") from the expansion-revenue paragraph, replaced with a precise fallback-tier statement.
6. No symbolic operators (`==`, `>=`, `IN {`, `->`) survive anywhere in the document — all translated to natural language.

Two scaffold details worth flagging to whoever writes the reference implementation, both stated explicitly in the PRD: merit-order sizes thermal storage from nameplate `storage_capacity_kwh` while commitment checks live `state_of_charge_kwh`; and the per-meter register-read collection sorts by `read_at` ascending, the sole documented deviation from the global `created_at` ascending default. The two withheld design files were not opened, and no sibling task directory was read.

## Step 5: Generate unit tests — 2026-09-01T15:05:22.000Z

Generation is complete and fully audited.

## Files created

**`test_helpers/`** (Stage 1, 9 files, ~3.5k lines): `__init__.py` (barrel, 271 exported names, registers the error-id → HTTP status map on import), `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`. The framework package `prd_bench_local_runner.testing` is re-exported, never re-implemented.

**`test_suite/`** (Stage 2, 16 test modules + `conftest.py`), **223 tests total**:

| tests | file | queue |
|---|---|---|
| 10 | test_01_forecast_projection_variants.py | A |
| 6 | test_02_invoice_variant_reconciliation.py | A |
| 8 | test_03_merit_order_waterfall.py | A |
| 8 | test_04_plan_commitment_cycles.py | A |
| 8 | test_05_agreement_dimensions_and_reservations.py | A |
| 8 | test_06_transitive_cascades.py | A |
| 9 | test_07_admission_ladder_precedence.py | A |
| 8 | test_08_cross_entity_state_dependencies.py | A |
| 9 | test_09_overlapping_window_contention.py | A |
| 19 | test_10_entity_envelopes_and_defaults.py | B |
| 22 | test_11_lifecycle_edges_and_terminal_states.py | B |
| 18 | test_12_determinant_and_scoring_arithmetic.py | B |
| 17 | test_13_admission_rung_conditions.py | B |
| 20 | test_14_endpoint_surfaces_and_collections.py | B |
| 28 | test_15_refusal_identifiers_and_gates.py | B |
| 25 | test_16_role_columns_versions_and_visibility.py | B |

## Coverage against the design indices

- 89 named instances across the two indices; 15 carry `excluded_because:` and produced **no** tests, as required.
- **All 74 non-stub instances translated (74/74)** — 18 depth instances (queue A) and 56 breadth instances (queue B). No instance was skipped for lack of PRD coverage.
- Every test docstring ends with exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line, copied verbatim; audited mechanically (223/223 pass, zero untagged, zero dual-tagged, zero tags pointing at a stub or a non-existent instance).

## PRD-first narrowings recorded (assertion dropped or weakened rather than fabricated)

1. `pipe_segment_requires_an_existing_parent_loop` — asserted the generic FK-not-found identifier; the PRD does not scope `ERR_LOOP_NOT_FOUND` to a body reference.
2. `system_fields_are_server_generated_and_clock_driven` — only the server-minted / clock-driven half is asserted; the PRD states no client-override rejection.
3. `meter_reading_and_dispatch_order_are_immutable_ledger_rows` and the Endpoints E1 instance — route-absence probes (no PUT/PATCH/DELETE) omitted; the PRD never states those routes are absent.
4. `a_loop_version_read_before_an_activation_is_stale_for_plan_creation` — the index's "loop version unchanged after plan creation" assertion was dropped as directly contradicted by the PRD ("the loop's own `version` is incremented by 1" on plan creation). The 412, the zero-plan residue, the refreshed version/reservation and the plan's own version steps are all asserted.
5. `every_cascade_of_a_write_is_already_visible_in_that_write_s_response` — the repeated-read assertion is grounded on the loop version/counter sentence rather than on a fabricated consistency-model quote.

## Verification run

- `python3 -m py_compile test_suite/*.py test_helpers/*.py` — clean.
- `pytest test_suite --collect-only` — 223 collected, no import or collection errors.
- Import audit across all 17 modules: no unused imports, all `from test_helpers import (...)` blocks alphabetized and consolidated into one statement per file, every imported name present in the barrel `__all__` and resolvable.
- Citation audit: 223/223 PRD quotes are verbatim contiguous spans of a whitespace-normalized `workspace/PRD.md`; no generated text contains the word "scaffold" or a section sign. Two pre-existing quotes were repaired during this pass (`test_02` adjustment sentence, `test_12` project-opening sentence) and three files had stray secondary import lines folded back into their sorted block (`test_05`, `test_06`, `test_07`); one unused import removed from `test_10`.

## Step 6: Generate implementation — 2026-09-01T15:05:22.000Z

Implementation is complete and verified. Servers I started have been stopped.

## Files created (all under `workspace/implementation/`)

| Layer | Files |
|---|---|
| Entry | `app.py` (59), `start.sh` (9, +x), `requirements.txt` (1) |
| Core | `db.py` (105), `errors.py` (73), `response.py` (49), `validators.py` (166), `middleware.py` (104), `enums.py` (30) |
| Domain logic | `calc.py` (460), `services.py` (298) |
| Routes (14 modules) | `routes/__init__.py`, `clock.py`, `loops.py`, `segments.py`, `fuel.py`, `assets.py`, `forecasts.py`, `plans.py`, `rates.py`, `agreements.py`, `metering.py`, `invoices.py`, `workorders.py`, `expansion.py` |

**Total: 24 files, 3,257 lines** (3,247 Python). **72 registered HTTP routes**, exactly matching the 72 `- method:` endpoint declarations in `SCAFFOLD.yaml`, path for path.

## Notable design decisions
- **Zero-seed boot**: `db.Store` builds 14 empty dicts plus a logical clock pinned to `2026-08-01T00:00:00Z`; verified all 14 collections return `[]` with `total_count: 0` on a fresh process. Cold boot to first 200 is ~1s, suitable for `--isolation per-test-server`.
- **Stable ordering without a wall clock**: because the logical clock is frozen, `created_at` ties are broken by a hidden monotonic `_seq`; hidden keys (`_seq`, `_service_date`, `_read_at`, …) are stripped by `response.serialize`. Client-supplied timestamps are echoed verbatim in the visible field while the parsed value lives under a `_`-prefixed key.
- **Single admission ladder**: `middleware.endpoint` wraps every handler in one `RLock`, authenticates (401 → 403), then handlers apply the scaffold's 17-priority order (schema 400 → path 404 → body FK 404 → ownership 403 → stale version 412 → duplicate code → referential mismatch → state gate → segregation → safety → temporal → monotonicity → empty set → sufficiency 422 → fiscal). Query-param enum filters and pagination are validated *before* path lookups, per steps 3 vs 4.
- **All arithmetic in `decimal.Decimal` with ROUND_HALF_UP**, quantized per-field (2/3/4/6 dp); storage SOC commit/decommit uses unquantized exact add/subtract so decommit restores the ledger bit-for-bit (verified 400.0 → 0.0 → 400.0).
- **Compute-before-write for fallible calculations**: expansion sizing that yields no feasible diameter (`ERR_NO_FEASIBLE_PIPE_SIZE` 422) and invoice determinants with insufficient reads (`ERR_INSUFFICIENT_METER_DATA` 422) persist nothing.
- **Version-bump accounting is explicit** for cascades: e.g. work-order completion performs exactly one loop bump for the isolation/posture unwind and only when `requires_isolation`; a DRAFT→VOID invoice does no ledger work and no agreement bump.

## Verification
Three scripted end-to-end smoke runs against fresh boots (`/tmp/de_smoke.py`, `de_smoke2.py`, `de_smoke3.py`) exercised ~120 calls, all passing, including hand-checked numerics: forecast projection (`9828.00 kW`, `146.241 MWh`), merit-order dispatch with storage energy cap (HHI `0.5255`, N-1 reserve margin `23.12%`), invoice determinants under both variants (`ESTIMATED` admits estimated reads and zeroes the ratchet; `ACTUAL_TRUE_UP` restricts to ACTUAL and applies it), minimum-bill flooring, arrears entry/exit at the 25,000 threshold, isolation-clearance denial while a plan is COMMITTED, work-window conflicts, segment re-banding on completion, and expansion NPV/convert. Also confirmed 401 on missing headers, 403 role and ownership denials, 400 pagination/enum violations, 404 unknown path, 405 method-not-allowed, and 412 on both stale-version guards.

One operational note: an early `pkill -f "python3 app.py"` may have briefly killed unrelated Flask servers on this box (including any the parallel test-generation agent had running); subsequent work used a dedicated port and targeted PID kills only.

## Step 7: Run tests and iterate — 2026-09-01T15:33:35.000Z

All 8 parallel rounds pass 223/223.

## Summary

**Iterations run:** 3 sweeps (8 parallel rounds each). Sweep 1: 162/223 in all 8 rounds. Sweep 2: 221/223 (one round 220 — a flaky transport failure). Sweep 3: **223/223 in all 8 rounds**.

**Tests deleted:** none. Every failure traced to a test-harness defect (wrong helper-call shape, wrong envelope unwrapping, stale HTTP connection reuse), not to PRD silence or non-derivability, so STEP 1 never reached a deletion verdict.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — the five tariff factories `hospital_rate_schedule`, `commercial_rate_schedule`, `residential_rate_schedule`, `industrial_rate_schedule`, `university_rate_schedule` each passed a literal `code=` *and* `**overrides`, so any caller supplying its own `code` raised `TypeError: got multiple values for keyword argument 'code'` before a single request was sent. Rewritten to merge defaults with overrides into one dict. This was the single root cause of 57 of the 61 sweep-1 failures (matching the ≥5-shared-setup-error triage hint).
- `test_helpers/api_client.py` — added an `ApiClient.__init__` that sets `Connection: close` on the session. The harness reboots the server on the same port before every test, so a keep-alive socket pooled by an earlier test was occasionally already dead when the next test's first request reused it, surfacing as `RemoteDisconnected` mid-setup (round 8 of sweep 2). Transport-only change; no request content or assertion touched.

**Fixes applied to `test_suite/`:**
- `test_10_entity_envelopes_and_defaults.py:78`, `test_14_endpoint_surfaces_and_collections.py:626`, `test_15_refusal_identifiers_and_gates.py:390` and `:826`, `test_11_lifecycle_edges_and_terminal_states.py:292` — removed a stray `["data"]` applied to `validate_success(...)`, which already returns the envelope's `data` payload. Double-indexing raised `KeyError: 'data'` before the real assertions ran.
- `test_10_entity_envelopes_and_defaults.py:301` — `validate_error(...)` returns the error `data` object, not the whole body, so `body["response_type"] == "error"` raised `KeyError`. Replaced with `body["error_id"] == ApiErrorId.PLAN_NOT_FOUND`; the `response_type == "error"` envelope check is already performed inside `validate_error`, so no coverage was lost.

**Fixes applied to `implementation/`:** none. Every failure was a test-artifact defect; no PRD-required check was removed or weakened, and no endpoint, field, or side effect was added.

**Flakiness note:** the sweep-2 signal was a genuine timing-sensitive bug (stale pooled socket) that a single round would have hidden — exactly the class the 8-round design is meant to catch. Sweep 3 showed zero variance across rounds.

## Step 8: Finalize PRD — 2026-09-01T15:35:59.000Z

`workspace/PRD_FINALIZED.md` created as a byte-identical copy of `workspace/PRD.md`. **No edits were needed** — every item in `<step_7_diff>` is a pure test-artifact defect with no PRD-silence and no PRD/impl mismatch.

## Line counts
- `PRD.md`: 507 lines
- `PRD_FINALIZED.md`: 507 lines
- Delta: 0 lines, 0.00% (`diff` reports no difference)

## Changes
None. (No `{PRD section} — {insert|revise}` bullets to report.)

## Per-item verification log

**1. `test_helpers/fixtures.py` — five tariff factories passed literal `code=` plus `**overrides` (TypeError)**
- (a) Subject: `RateSchedule` creation payload — `code`, `customer_class`, the three charge fields, `tiers`, `ratchet_lookback_months`.
- (b) Enumerated/read: `implementation/routes/rates.py:19-43` (the only `POST /rate-schedules` handler), `implementation/validators.py:130-151` (`get_tiers` — non-empty + strictly-increasing ceilings, stored in supplied order), `services.require_unique_code("rate_schedules","code",...)`, `errors.py` `ERR_DUPLICATE_CODE`/`ERR_INVALID_REQUEST` mappings. Impl matches PRD §3.5 exactly (charges `ge=0`, `ratchet_lookback_months` default 11, ladder validation, code uniqueness). The failure occurred in Python before any HTTP request was issued, so it could not have observed impl behavior at all.
- (c) No wording adjustment — nothing to edit.

**2. `test_helpers/api_client.py` — added `Connection: close` on the session**
- (a) Subject: HTTP transport / connection reuse.
- (b) Enumerated: `implementation/app.py` (Flask app + server startup), `implementation/start.sh`, `implementation/middleware.py` (request hooks) — nothing anywhere in the impl sets, reads or depends on keep-alive semantics; behavior is the framework default. PRD §2.2/§2.9 make no transport claims.
- (c) No wording adjustment — a PRD statement here would invent behavior the impl does not deliberately exhibit.

**3. Stray `["data"]` applied to `validate_success(...)` at `test_10:78`, `test_14:626`, `test_15:390`, `test_15:826`, `test_11:292`**
- (a) Subject: the success-response envelope (`meta` / `response_type` / `data`).
- (b) Enumerated/read: `implementation/response.py:33-40` (`success()` — the single envelope constructor for all 2xx), `response.py:41-48` (`error()`), `response.py:16-24` (`build_meta`, `req_` prefix, `now_ts` three-fraction-digit stamp), `implementation/middleware.py` `paginate` (the only injector of `limit`/`offset`/`total_count`/`has_more` into `meta`), plus the framework helper `prd_bench_local_runner/testing/validators.py:27-50` which already returns `body["data"]`. Impl envelope is exactly PRD §2.2. The `KeyError: 'data'` was double-unwrapping in the test, not an envelope divergence.
- (c) No wording adjustment.

**4. `test_10:301` — `validate_error(...)` return shape; assertion rewritten to `body["error_id"] == ApiErrorId.PLAN_NOT_FOUND`**
- (a) Subject: the error envelope and the 404 for an unresolved `plan_id` path identifier.
- (b) Enumerated/read: `implementation/routes/plans.py:81-83` (`GET /dispatch-plans/{plan_id}` → `svc.path_get("plans", ...)`), `implementation/services.py:11-38` (`NOT_FOUND` map — `plans` → `ERR_PLAN_NOT_FOUND`, used by *every* plan action, not just the read: optimize/submit/review/commit/decommit/reconcile all route through the same `path_get`), `implementation/errors.py:24` (`ERR_PLAN_NOT_FOUND` → 404), `implementation/response.py:41-48` (error envelope carries `response_type: "error"` and `data.{error_id,message}`). All consistent with PRD §2.9 rung 4 and §5. The `response_type == "error"` check is still performed inside the framework's `validate_error`, so nothing PRD-pinned went unasserted.
- (c) No wording adjustment.

**5. Test deletions / implementation fixes**
- None reported in `<step_7_diff>`; nothing to trace. Final sweep was 223/223 across 8 rounds with the impl untouched, which is itself evidence the PRD's pinned behaviors and the impl already agree at every site Step 7 exercised.

## Step 9: Complete PRD — 2026-09-01T15:44:35.000Z

Patch complete.

**Files:** source `PRD_FINALIZED.md` (identical to `PRD.md`) 507 lines / 99,359 chars → `PRD_COMPLETED.md` 507 lines / 105,064 chars (**+5,705 chars**, line count unchanged — every change is an in-paragraph insert or revision; no new sections, paragraphs, or bullets).

**Counts:** 30 changes — **24 ambiguity-pins**, **6 mismatch-revisions**.

- §2.1 RBAC — revise — mismatch — CustomerAccount ownership is enforced *only* on the single-agreement read, single-invoice read and payment; metering-point, per-meter register-read and tariff reads are unchecked — `routes/metering.py:67`, `routes/rates.py:55`
- §2.3 Pagination — revise — ambiguity — blank/non-integer `limit`/`offset` are also `ERR_INVALID_REQUEST` — `middleware.py:70-84`
- §2.4 Filters — insert — ambiguity — enum filters reject unknown values 400; id filters accept any string and match nothing — `validators.py:154-166`
- §2.5 Timestamps — insert — ambiguity — client-supplied instants are echoed verbatim; only `created_at`/`updated_at` are server-normalised — `db.py:63-75`, `response.py:27-31`
- §2.7 Version guards — revise — ambiguity — the version field must be an integer ≥ 0 — `routes/plans.py:30`, `routes/invoices.py:40`
- §2.8 Posture — insert — ambiguity — isolating excavation on an already-`ISOLATED` loop restamps `ISOLATED` and still bumps count and `version` — `routes/workorders.py:162-165`
- §3.1 Segments — revise — ambiguity — `diameter_mm`/`install_year` must be integers, `buried_depth_m` unconstrained — `routes/segments.py:43-46`
- §3.2 Assets — insert — ambiguity — `derated_capacity_kw`/`min_stable_output_kw`/`storage_capacity_kwh` may not be negative — `routes/assets.py:35-44`
- §3.2 Availability — revise — ambiguity — the `DERATED` gate judges the post-overwrite ceiling; nothing persists when a gate refuses — `routes/assets.py:110-127`
- §3.2 Availability — revise — ambiguity — contract self-edges (e.g. `ACTIVE→ACTIVE`) also yield `ERR_AVAILABILITY_STATE_INVALID` — `routes/fuel.py:79-83`
- §3.2 Suspension cascade — revise — mismatch — only `APPROVED` plans whose orders reference an asset just derated are reverted, not every plan on the loop — `services.py:120-134`
- §3.2 Expiry cascade — revise — ambiguity — already-`OUTAGE` assets untouched (no `version` bump); expiry touches no plan or posture — `services.py:147-154`
- §3.3 Forecast create — revise — ambiguity — actual degree-hour inputs may not be negative — `routes/forecasts.py:44-47`
- §3.3 Publish — revise — mismatch — the `DRAFT` state gate runs *before* the `ACTUAL_WEIGHTED_FINAL` 400, which is judged on post-overwrite values — `routes/forecasts.py:101-114`
- §3.4 Plan create — revise — mismatch — the forecast's `forecast_state` is not checked at creation — `routes/plans.py:40-43`
- §3.4 Effective capacity — insert — ambiguity — the storage rule outranks `DERATED` for a thermal store — `calc.py:143-150`
- §3.4 Dispatch order — revise — ambiguity — `allocated_kw` is the block rounded to 2 dp — `calc.py:183`
- §3.4 Order energy — insert — ambiguity — energy/discharge/cost/emissions derive from the *unrounded* block — `calc.py:176-179`
- §3.4 Approval loss — revise — mismatch — the trigger is an `AVAILABLE→DERATED` cascade only, not "DERATED or OUTAGE" — `services.py:112-128`
- §3.4 Reconcile — revise — ambiguity — refusal code is `ERR_FORECAST_STATE_INVALID`, after the `COMMITTED` gate — `routes/plans.py:248-254`
- §3.5 Tariff — revise — ambiguity — `ratchet_lookback_months` is a non-negative integer, stored but consulted by no calculation — `routes/rates.py:27`
- §3.7 Load factor — revise — ambiguity — period hours truncate downwards; a sub-hour period gives 0.0 — `services.py:267`, `calc.py:268`
- §3.7 Adjustment — revise — ambiguity — adjustment never moves `billing_state` in either direction — `routes/invoices.py:145-153`
- §3.7 Payment — revise — ambiguity — `amount` is required and non-negative (negative = 400, not mismatch) — `routes/invoices.py:160`
- §3.8 Age component — insert — ambiguity — the ratio is capped above at 1 but not floored at 0 — `calc.py:310-314`
- §3.8 Assessment — revise — ambiguity — an `UNDER_REPAIR` segment still stores the new score and bumps `version` — `routes/segments.py:120-124`
- §3.8 Excavation — insert — ambiguity — an already-`UNDER_REPAIR` segment is left entirely untouched — `routes/workorders.py:154`
- §3.8 Sign-off — revise — ambiguity — `open_isolation_count` floors at 0 and the loop is touched even when not `ISOLATED` — `routes/workorders.py:219-225`
- §3.9 Sizing — revise — ambiguity — `ERR_NO_FEASIBLE_PIPE_SIZE` persists nothing, discarding in-call revisions — `routes/expansion.py:114-123`
- §3.9 Conversion — revise — mismatch — the new agreement stays `PENDING_CAPACITY` (no activation, no sweep), `service_mode` is unchecked, and the response carries the project — `routes/expansion.py:166-180`

Note: `implementation/results.*.json` (8 runs, 223/223 passing) were only inspected for pass/fail counts; tests were not used as an authority.

---

## Pipeline complete

All 9 steps finished. `workspace/PRD_COMPLETED.md` exists on disk. Final test state: 223/223 passing in all 8 parallel rounds under `--isolation per-test-server`.
