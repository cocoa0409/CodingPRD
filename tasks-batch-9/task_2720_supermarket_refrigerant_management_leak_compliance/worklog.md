# Worklog — task_2720_supermarket_refrigerant_management_leak_compliance

## Step 1: Create task directory — 2026-09-04T11:34:41.324Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2720_supermarket_refrigerant_management_leak_compliance` and its `workspace/` subdirectory. Index 2720 was pre-assigned by the orchestrating caller; no scan of `./tasks/` was performed (concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-04T13:14:27.635Z

All three scaffold artifacts are complete and pass the scaffold linter cleanly.

## Output
`/home/ubuntu/github/CodingPRD/tasks/task_2720_supermarket_refrigerant_management_leak_compliance/`

| file | lines | bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 2375 | 159 050 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1841 | 130 532 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3948 | 279 901 |

Scenario text stored verbatim (byte-compared after whitespace folding). `SCAFFOLD.yaml` carries neither design key; each design file has exactly one top-level key.

## SCAFFOLD.yaml counts (§1.0–§1.7)
- **14 entities** (Store, RefrigerantType, RefrigerantSystem, Technician, RecoveryEquipment, Cylinder, ServiceRecord, LeakEvent, RepairAttempt, VerificationTest, ExtensionRequest, RetrofitPlan, RegulatoryReport, Inspection)
- **10 state machines** + **2 §1.2.1 concurrency rules** (both OCC on `RefrigerantSystem.version`: `POST /service-records`, `POST /retrofit-plans`)
- **12 calculations** (2 dual-variant: `system_leak_rate_pct`, `store_period_leaked_lbs`)
- **51 ordered validations** (priority 1 auth → 49 plan cost)
- **60 endpoints**, **61 error codes**, **5 roles** (`role_model: segregation_of_duties`, `consistency_model: immediate`, layers: rate_threshold_triggers / cascading_side_effects / dual_variant_calculation / optimistic_concurrency)

## Design index instance counts
- **§1.8: 23 instances** — dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 2.
- **§1.9: 83 instances** (69 with full `test_recipe`, 14 `excluded_because` stubs) — entities 10, state_machines 11, calculations 10 (3 stubs), validations 16 (1 stub), endpoints 5, errors 17 (7 stubs), rbac 6, cross_cutting_layers 7 (3 stubs), consistency_model 1.
- All 106 instance names unique across both files; all 61 error codes are triggered or stubbed with a §1.8 citation.

## Lint
```
  §1.5 endpoints declared:    60
  §1.1 entities declared:     14
  §1.8 instances scanned:     23
  §1.9 instances scanned:     69
  Calls scanned (§1.8+§1.9):  889

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Design adjudications made
- **Fiscal bound vs generic shape check**: `ERR_INVALID_REQUEST`'s condition was tightened to exclude field-specific numeric bounds, so `estimated_cost_usd 6000000.00` is unambiguously `ERR_PLAN_COST_OUT_OF_RANGE` (priority 49) rather than a priority-3 range error. This is the only §1.0–§1.7 edit made while writing §1.9.
- **Rule isolation for every negative trigger** so exactly one validation can fire: an oversized cylinder to keep the fill limit from pre-empting `ERR_NEGATIVE_SYSTEM_CHARGE`; a 40 lb-loaded cylinder so contents cannot pre-empt `ERR_CHARGE_EXCEEDS_NAMEPLATE`; a cross-store cylinder of the *matching* chemistry so scope (p23) fires instead of chemistry (p21); a second machine for the 2027 rolling-window record so equipment currency cannot fire; `performed_at 2024-12-01` (past but pre-installation) so p30 fires without p29; a LOW-certified but *current* machine so p18 fires and not p17; a SENT_FOR_RECLAIM cylinder at 0.0 lb to prove p22 precedes p40.
- **Loser codes given their own reachability tests**: `ERR_CYLINDER_FILL_LIMIT_EXCEEDED`, `ERR_INSUFFICIENT_CYLINDER_CONTENTS` and `ERR_TECHNICIAN_CERT_EXPIRED` are suppressed losers inside §1.8 priority pairs, so §1.9 triggers each one standalone rather than stubbing them.
- **Two OCC instances, one per §1.2.1 rule**, each staling a captured `${var}` via an intervening legitimate write (a service record for rule 1, a competing plan create for rule 2 so the supersede hazard is real); plus a monotonicity instance proving version 1→2→3→4 across the three version-bumping write families and never on a read.
- **Field-name audit against §1.1** caught and fixed four invented fields in the new sections (`total_refrigerant_charge_lbs`→`total_regulated_charge_lbs`, `leak_threshold_pct`→`threshold_pct`, `LEAK_EXCEEDANCE`→`LEAK_OPEN`, and `opened_leak_event_id` replaced by `leak_rate_pct_after`/`system_charge_after_lbs` plus a `?triggering_service_record_id=` list read).
- **Pagination-under-mutation** is modelled with append-only inserts sorting last (created_at ASC, id tiebreak) so offset windows cannot duplicate or skip rows; `has_more`/`total_count` asserted on all three pages.
- `api_prefix` is left as `/` because §1.5 declares bare top-level collections and every §1.8/§1.9 call matches those paths exactly.

## Step 3: Copy shared files — 2026-09-04T13:14:51.543Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T13:33:16.533Z

PRD complete and verified.

**Output:** `workspace/PRD.md` — 482 lines, 101,215 bytes, built in 12 chunked `cat >>` appends. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced.

**Anti-truncation verification**
- `wc -l` = 482; `tail -40` ends on the final `| \`ERR_PLAN_COST_OUT_OF_RANGE\` | 422 |` table row — a real section boundary, no mid-sentence or mid-table cut, no audit footer.
- Meta-text scan for `difficulty|benchmark|scaffold|test recipe|test generator|LLM|§1.x|corner case design`: 0 hits.
- Fuzzy-word scan (`approximately|roughly|conservatively`): 0 hits (one earlier occurrence in §1 was rephrased).
- Pseudocode scan (`round_half_up(|==|!=|&&|IN {|floor(|min(|max(`): 0 hits.

**Heading list (29 headings, in file order)**
`# Supermarket Refrigerant Leak Compliance API — Product Requirements Document`; `## 1. Introduction`; `## 2. Global Specifications & System-Wide Principles`; `### 2.1. User and Role-Based Access Control`; `### 2.2. API Response Structure` (+ `#### Standard Success Response Format`, `#### Standard Error Response Format`, pasted verbatim); `### 2.3. Pagination`; `### 2.4. The Logical Compliance Clock`; `### 2.5. Common Resource Properties and Immutable Evidence Records`; `### 2.6. Measurement Precision and Rounding Discipline`; `### 2.7. Conservation of Refrigerant Mass`; `### 2.8. Optimistic Concurrency on Refrigeration Systems`; `### 2.9. The Pinned Recomputation Cascade`; `### 2.10. Validation Precedence`; `### 2.11. Resource Addressing and Filtered Collections`; `## 3. Business Logic & Workflows`; `### 3.1. Building the Regulated Asset Inventory`; `### 3.2. Certified Labour, Recovery Machines and Cylinder Custody`; `### 3.3. The Service Ledger: Filing Work Against a System`; `### 3.4. Leak Rate Measurement and Automatic Event Detection`; `### 3.5. Repair, Two-Stage Verification and the Retrofit Mandate`; `### 3.6. Deadlines, the Extension Day Budget, and the Compliance Sweep`; `### 3.7. Transition Planning: Retrofit, Retire, and the End of a System's Life`; `### 3.8. Record Retention and the Compensation of a Service Record`; `### 3.9. Regulatory Filings, Inspections and Penalty Exposure`; `## 4. Endpoint Definitions`; `## 5. Error Code Catalogue`.

**Contract 1: Field-Name Coverage — PASS**
- `entities[].fields[].name`: 151/151 present verbatim in backticks, 0 missing.
- `endpoints[].input` identifiers (request bodies, query params, path-adjacent keys): 99/99 present, 0 missing.
- Structured `endpoints[].output` keys (leak-rate projection 8, compliance-run 7, clock 2): 17/17 present.
- All enum values across every entity field: 0 missing. All state-machine state names: 0 missing. All 5 role names: 0 missing. All numeric constants of all 12 calculations, including nested maps (`PENALTY_PER_DAY`, `PENALTY_MULTIPLIER`, surcharge brackets, weights, thresholds): 0 missing.

**Contract 2: Rule Coverage — PASS**
1. Validations: 51 rows / 49 distinct priorities all narrated, with the strictly-ascending first-violation-wins order stated in §2.10; no error ID is absent from §1–§4 prose (checked all 61 against the body excluding the §5 table).
2. Concurrency: both OCC rules on `RefrigerantSystem.version` via `expected_system_version` → `ERR_STALE_SYSTEM_VERSION` (412), on both service-record filing and retrofit-plan filing, in §2.8.
3. State machines: 56/56 transitions accounted for across 10 machines — 24 rendered as explicit `FROM → TO` arrows, 32 narrated in prose (verified by co-occurrence); the only 3 flagged by the arrow scan are Cylinder `RECOVERED → SENT_FOR_RECLAIM` / `SENT_FOR_RECLAIM → RECLAIMED` (both fully described in §3.2 under the `disposition` field name) and LeakEvent `NEW → OPEN`, which is the creation pseudo-state (`initial_state: OPEN`) described as event creation.
4. Calculations: all 12 named and specified, including the pinned 7-step posture order, both leak-rate variants, both leaked-mass variants, per-citation rounding, the surcharge ladder keyed on the base alone, calendar-year retention, and the three-component compatibility score.
5. Validation conditions: inclusive/exclusive bounds, strict-vs-non-strict deadline comparisons, and the closed buffered equipment interval all stated explicitly.
6. Endpoint side effects and `applies_to`: cascades, ledger reversals, sweep pass order with `created_at` tie-breaker, and sweep report keys all narrated.
7. Entity field structured content: computed-field derivations, input scopes that deliberately differ between counters, and null-at-creation sets all documented.
8. Sibling-branch symmetry: `ROLLING_AVERAGE`/`ANNUALIZING`, `CHARGE_BASED`/`BALANCE_BASED` (with the 20.0-vs-0.0 contrast), the FAIL fork below-2 vs at-2-or-more, and accept/reject plus approve/reject decision pairs all given with disjoint effects.

**Contract 3: §3 Path Purity — PASS**
1,077 backticked tokens (365 unique) in §3: 0 tokens starting with `/`, 0 bare HTTP methods, 0 method+path combinations; also 0 unbacktick'd raw path mentions. All 60 operations are referred to in §3 by state-transition framing, role + action verb, or capability description.

**Table fidelity (scripted diff against the scaffold)**
- §4: exactly 4 columns; 60/60 endpoints, same order as `endpoints[]`, no extras or omissions, and every row's authorized-role set matches `endpoints[].roles` exactly.
- §5: exactly 2 columns; 61/61 error IDs with zero status-code mismatches, zero extras.

**Orchestrator verification (independent):** re-checked `wc -l` = 482, heading list (29 headings, §1–§5 all present), `tail -6` ends on the final error-catalogue row, and a grep for `harder than expert|difficulty|benchmark|scaffold` returned 0 hits. PRD is not truncated; no difficulty meta-text leaked.

## Step 6: Generate implementation — 2026-09-04T14:11:57.000Z

(Recorded before Step 5 because Step 6 finished first; the two ran concurrently, launched in a single orchestrator message so the implementation generator could not see `test_suite/`, which did not yet exist at its spawn time.)

Implementation complete and smoke-verified.

## Files written (all under `workspace/implementation/`)

Total 3,685 lines across 33 files. No file truncated (every module ends in a complete definition; `import app` succeeds).

| File | Lines | | File | Lines |
|---|---|---|---|---|
| `start.sh` | 10 | | `services/ledger.py` | 184 |
| `requirements.txt` | 1 | | `services/posture.py` | 156 |
| `app.py` | 73 | | `services/guards.py` | 184 |
| `util.py` | 104 | | `services/deadlines.py` | 70 |
| `errors.py` | 103 | | `services/plans.py` | 79 |
| `response.py` | 128 | | `services/reports.py` | 103 |
| `db.py` | 137 | | `services/events.py` | 49 |
| `middleware.py` | 83 | | `routes/stores.py` | 110 |
| `validate.py` | 179 | | `routes/systems.py` | 190 |
| `constants.py` | 168 | | `routes/technicians.py` | 72 |
| `routes/recovery_equipment.py` | 82 | | `routes/cylinders.py` | 125 |
| `routes/service_records.py` | 228 | | `routes/leak_events.py` | 51 |
| `routes/repair_attempts.py` | 115 | | `routes/verification_tests.py` | 155 |
| `routes/extension_requests.py` | 156 | | `routes/retrofit_plans.py` | 187 |
| `routes/regulatory_reports.py` | 120 | | `routes/inspections.py` | 129 |
| `routes/ops.py` | 154 | | `routes/__init__.py`, `services/__init__.py` | 0 |

## Endpoints: 60 implemented / 60 declared

Route dump matches the PRD table exactly: stores 3, refrigerant-types 3, systems 5, technicians 4, recovery-equipment 4, cylinders 5, service-records 4, leak-events 3, repair-attempts 3, verification-tests 3, extension-requests 5, retrofit-plans 6, regulatory-reports 5, inspections 5, compliance-runs 1, `/_clock/set_current_utc` 1.

## Smoke check (ports 18742/18743/18744, each killed by exact PID; ports confirmed released)

Boot time from `bash start.sh` to first 200: **0.61 s** (pip install is skipped when Flask is importable). Ran a 40-call end-to-end script; every status code and computed value matched expectation:

- Envelope: `{meta:{api_request_id "req_"+20 alnum, api_request_timestamp}, response_type, data}`; `response_type` object/array/error; list meta carries `limit/offset/total_count/has_more`; all instants exactly 3 fractional digits.
- Cascade: ADD_REFRIGERANT 20 lb on a 50/100 lb system -> charge 70.0, leak rate 20.0 %, auto leak event (`LEAK_RATE_CALCULATION`, repair deadline +30 d), system `LEAK_OPEN`, store `AT_RISK`; equipment released at +60 min buffer; retention `2029-07-01`.
- Repair -> initial PASS (`FOLLOWUP_PENDING`, verification deadline +10 d) -> follow-up PASS -> `VERIFIED_CLOSED`, system back to `COMPLIANT`.
- Reference arithmetic reproduced: retrofit compatibility **84.1 / COMPATIBLE**, GWP reduction 64.6; two MINOR 1-day citations at multiplier 1.00 -> **551.10**; 6-day-late report -> base 990.00 + 5 % surcharge 49.50 = **1039.50**.
- Error paths verified: 401 unauth, 403 role / store-scope / technician-identity mismatch, 409 duplicate + equipment decontamination conflict + report period overlap, 412 stale system version, 422 segregation of duties, 400 pagination/validation/malformed JSON, 404 unknown id and unknown route, 405 wrong method.

Storage is pure in-memory dicts (`db.COLLECTIONS`); a repo scan confirms no sqlite, no file writes, no `/tmp` cache, and no seeded data — the logical clock is the only preset value (`2026-08-01T00:00:00Z` on every boot). `__pycache__` removed; only `.py`, `start.sh`, `requirements.txt` remain.

## PRD ambiguities resolved

1. `POST /_clock/set_current_utc` is header-exempt, but if a role header is presented it must be PlatformAdmin.
2. `limit` outside 1..100 or negative `offset` -> 400 `ERR_INVALID_REQUEST` rather than clamping.
3. All datetimes canonicalised to 3 fractional digits, including echoed request values.
4. Retiring an already-RETIRED system -> `ERR_SYSTEM_RETIRED` (priority 10 wins over the generic transition error).
5. Terminal leak event on attempt/test create -> `ERR_LEAK_EVENT_TERMINAL`; non-terminal-but-illegal -> `ERR_INVALID_STATE_TRANSITION` (disjoint domains).
6. Reclaim certification checks quantity (45) before purity (46), per §2.10's numbering rather than §3.2's prose order.
7. Manual `POST /leak-events` rejects `LEAK_RATE_CALCULATION`; gates ordered retired -> applicability -> open-event -> clock.
8. `initial_charge_lbs > full_charge_lbs`, over-fill on cylinder create, `due_on <= clock`, and a test `performed_at` before its attempt's `repair_completed_at` all surface as `ERR_INVALID_REQUEST` (no dedicated code declared).
9. Extension decision requires `granted_days` on APPROVE / `denial_reason_code` on DENY; approval order requested -> cap -> terminal, with the 15-day window after state legality.
10. Retrofit submission gates ordered by numeric priority (retired 10 -> prohibited 27 -> incompatible 38); incompatibility is raised from a scored copy so a rejected submission mutates nothing.
11. `compliance_state`, store aggregates, `vented_loss_lbs`, and live-inspection exposure are always *derived*, never patched — satisfies every transition sentence in §3.4/3.5/3.7/3.8.
12. Technician conflicts are half-open intervals (a repair attempt's instant is tested for containment); equipment conflicts are closed intervals and unconditional.
13. `current_attempt` falls back to the newest VERIFIED attempt while the event is `FOLLOWUP_PENDING`, otherwise two-stage verification would be unreachable.
14. `ERR_UNRECLAIMED_REFRIGERANT_REUSE` fires on any `refrigerant_added_lbs > 0` from a SENT_FOR_RECLAIM cylinder, not only for ADD_REFRIGERANT.
15. Version bumps: `db.commit` (bump only on real change) for stores/cylinders/technicians/events/inspections; unconditional `db.touch` for systems on the endpoints §2.9 names.
16. `stores_recomputed_count` counts stores touched by any of the five sweep passes.
17. Plan completion requires status IN_PROGRESS; the "no overdue leak event" precondition surfaces as `ERR_INVALID_STATE_TRANSITION`.
18. `total_leaked_lbs`/`included_system_count` are computed at report creation as well as at submission.
19. Numeric fields reject JSON strings (strict typing, §2.10 priority 3).
20. Four convenience fields not in the PRD schema are stored but harmless: `System.retirement_reason_code`, `RetrofitPlan.submission_note`, `RegulatoryReport.submission_note`, `Cylinder.initial_contents_lbs`.

Only post-summary code change: `errors.py` gained a `_humanize()` fallback so undeclared-message errors return e.g. `"Store not found."` instead of echoing the raw id; `error_id` values are unchanged. Smoke suite re-run green after that edit.

## Step 5: Generate unit tests — 2026-09-04T14:52:34.909Z

Test suite generation for task 2720 is complete.

## Files written (task root, nothing inside `workspace/`)

**`test_helpers/`** (Stage 1 infrastructure, 2983 lines)
`__init__.py` 17 · `constants.py` 128 · `types.py` 494 · `api_errors.py` 187 · `test_users.py` 89 · `api_client.py` 338 · `factories.py` 515 · `assertions.py` 462 · `fixtures.py` 753

**`test_suite/`** (Stage 2, 6562 lines, 116 tests)
`conftest.py` 87
Queue A (§1.8, 47 tests): `test_01_dual_variant_calculations.py` 209/4 · `test_02_combinatorial_formulas.py` 249/6 · `test_03_non_linear_state_machines.py` 234/6 · `test_04_transitive_cascades.py` 268/4 · `test_05_priority_pair_conflicts.py` 263/6 · `test_06_boundary_precision.py` 292/7 · `test_07_cross_entity_state_dependency.py` 282/6 · `test_08_resource_temporal_overlap.py` 192/4 · `test_09_compensating_invariants.py` 200/4
Queue B (§1.9, 69 tests): `test_10_corner_entities.py` 454/10 · `test_11_corner_state_machines.py` 626/11 · `test_12_corner_calculations.py` 452/7 · `test_13_corner_validations.py` 775/15 · `test_14_corner_endpoints.py` 293/5 · `test_15_corner_errors.py` 739/10 · `test_16_corner_rbac.py` 468/6 · `test_17_corner_cross_cutting.py` 341/4 · `test_18_corner_consistency.py` 138/1

## Coverage (machine-verified by an AST audit against both yaml indices)

- **Queue A**: 23/23 non-stub instances translated, every one with >=2 tests (47 tests). No skips.
- **Queue B**: 69/69 non-stub instances translated, >=1 test each — entities 10/10, state_machines 11/11, calculations 7/7, validations 15/15, endpoints 5/5, errors 10/10, rbac 6/6, cross_cutting_layers 4/4, consistency_model 1/1. The 14 `excluded_because:` stubs (3 calculations, 1 validations, 7 errors, 3 cross_cutting) were left untranslated, as required.
- Every test carries exactly one `Design:` tag as the final docstring line; all 92 tags resolve to a real instance name **and** the correct section. No untagged, dual-tagged or dangling tags. **No PRD-filter skips** — every non-stub instance passed the two-condition filter.
- `py_compile` clean on all 28 files; `pytest --collect-only -q` collects exactly 116 tests; zero unused imports; no scaffold/design-index references anywhere in the emitted code. `worklog.md` and `workspace/` untouched.

## Three design/PRD adjudications Step 7 should know about

1. **`total_regulated_charge_lbs`** — the corner index repeatedly asserts this as the sum of *current* charge (80.0). PRD §3.1 (line 179) defines it as the sum of `full_charge_lbs` over ACTIVE+REGULATED systems, so I encoded the PRD value (100.0, and 160.0->100.0 in the aggregates test) in three places: `test_12_corner_calculations.py`, `test_15_corner_errors.py` (`a_system_still_holding_refrigerant_cannot_be_retired`), `test_18_corner_consistency.py`.
2. **Initial PASS does not close an event** — the rbac instance `technician_cannot_verify_the_repair_they_performed` asserts closure on the second (initial) PASS; PRD §3.5 (lines 261–263) uniquely derives FOLLOWUP_PENDING with the deadline re-based. `test_16` asserts the PRD-correct intermediate state and then adds the follow-up PASS to reach the instance's asserted end state (VERIFIED_CLOSED, `closed_at` 2026-08-10, system COMPLIANT, store open 0).
3. **Unsound negative control repaired** — the errors instance `refrigerant_awaiting_reclaim_cannot_be_charged_back_into_a_system` claims the *identical* ADD succeeds post-certification, but that timestamp would legitimately trip the §3.3 labour/decontamination intervals. The retry runs at `2026-08-01T04:00:00Z` with an in-code comment; the isolation claim is preserved. Related robustness choice: the not-found sweep uses the framework's `NON_EXISTENT_UUID` instead of the index's version-0 UUID, which would have tripped shape validation first.

**Orchestrator verification:** `find workspace -maxdepth 2 -name 'test_*' -type d` returned nothing (no stray test dirs under `workspace/`); both `test_helpers/` and `test_suite/` are at the task root; only one `worklog.md` exists (task root); `__pycache__` dirs removed before Step 7.

## Step 7: Run tests and iterate — 2026-09-04T15:07:53.517Z

Clean 8-round sweep achieved.

## Summary

**Iterations run:** 2 (iteration 1 exposed 14 deterministic failures — identical in all 8 rounds, no flakiness; iteration 2 was green).

**Tests deleted:** none. Every failing test's asserted rule was verbatim-covered and uniquely derivable from PRD.md (§2.4 future-timestamp rule, §2.8 concurrency token, §2.10 precedence ladder). All 14 failures were test-artifact bugs, not PRD-silence.

**Fixes applied to `test_helpers/`:** none — the common fixtures were PRD-faithful; the bugs were all local to individual test functions in `test_suite/`.

**Fixes applied to `implementation/`:** none. The implementation was correct on every one of the 14 failures; in particular its §2.4 `require_not_after_clock` gate (`workspace/implementation/services/guards.py:163`) was rejecting fixtures that genuinely sent a future `performed_at`, and weakening it would have violated the cardinal rule.

**Fixes applied to `test_suite/` (all made the tests *more* faithful to PRD):**

*Cluster 1 — wrong error-envelope key (5 tests, `KeyError: 'error'`).* `validate_error()` returns the envelope's `data` dict, so `body["error"]["error_id"]` never resolves. Changed to `body["error_id"]` in `test_05_priority_pair_conflicts.py` (3x), `test_08_resource_temporal_overlap.py:169`, `test_13_corner_validations.py:141`. The exact-`error_id` assertions were preserved verbatim.

*Cluster 2 — `performed_at` / test instants later than the logical clock (8 tests, `ERR_TIMESTAMP_AFTER_CLOCK`).* PRD §2.4: "no physical-world timestamp supplied in a request body may lie in the future relative to it. `performed_at`, `repair_completed_at`, `detected_at`, `reclaim_issued_on`, `verified_on` and `period_end` are all subject to this rule". Each test set a clock and then filed work after it. Fixed by moving the work instant back, or advancing the clock where a downstream assertion pinned the work instant:
- `test_04_transitive_cascades.py` — `_mandated_system_ready_to_convert`: conversion record `performed_at` `2026-08-08T10:00Z` -> `2026-08-07T20:00Z` (clock had to stay at `08-08T00:00Z` because the test asserts `completed_at`/`leak_rate_baseline_at` equal it). Chosen to clear both the technician half-open interval and the machine's closed decontamination-buffered interval.
- `test_06_boundary_precision.py` — added `X.set_clock(api, "2026-08-01T03:00:00Z")`; the test pins `detected_at`/`initial_repair_deadline` at `03:00`, so the clock, not the record, had to move.
- `test_11_corner_state_machines.py`, `test_12_corner_calculations.py` — verification tests `08-08T10:00/11:00Z` -> `08-07T10:00/11:00Z`; the `leak_rate_baseline_at` assertion in test_11 was re-pinned to the new follow-up instant (`closed_at` correctly stays at the unchanged clock).
- `test_15_corner_errors.py` — two tests' opening `set_clock` moved to `04:00Z` / `06:00Z`, the instants their own later records need in order to clear the 60-minute decontamination buffer.
- `test_17_corner_cross_cutting.py` — added `X.set_clock(api, "2026-08-01T04:00:00Z")` before the second (stale-token) write; per §2.4 "setting the clock mutates no entity by itself", so the token remains stale and `ERR_STALE_SYSTEM_VERSION` is still the asserted outcome.

*Cluster 3 — factory misuse (1 test, `TypeError`).* `test_10_corner_entities.py`: `service_record_payload()` takes `expected_system_version` positionally, and the test passed both `1` positionally and `expected_system_version=F.OMIT` by keyword. Now passes `F.OMIT` positionally, which is what actually drops the required field the test is probing.

**Final sweep evidence (`results.$i.json`):** round 1: 116/116 · 2: 116/116 · 3: 116/116 · 4: 116/116 · 5: 116/116 · 6: 116/116 · 7: 116/116 · 8: 116/116. Zero failures, zero errors, zero skips in every round.

I did not touch `worklog.md`.

**Orchestrator verification (independent):** all eight `workspace/implementation/results.[1-8].json` exist (timestamped 15:06, ~35.9 KB each) and each parses with `passed=116 total=116 failed=0 errors=0`. Sweep artifacts confirmed present, so the clean-sweep claim is substantiated rather than asserted.

**Step 8 gating decision (orchestrator):** the skip condition requires 0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes. Step 7 made 14 `test_suite/` fixes, so Step 8 is NOT skipped and runs with the above entry inlined as `<step_7_diff>`. Note that the three clusters look like pure test-artifact bugs, so a byte-identical `PRD_FINALIZED.md` would be a legitimate outcome here; the residual-ambiguity work belongs to Step 9.

## Step 8: Finalize PRD — 2026-09-04T15:11:00.000Z

## Result

`workspace/PRD_FINALIZED.md` was created as a byte-identical copy of `workspace/PRD.md` — **no edit is warranted**.

- Line counts: PRD.md 482 / PRD_FINALIZED.md 482, delta 0.0%. Identical md5 (`9938fd72...`).
- Changes: **none.**

## Why (per Step 7 cluster, traced into `implementation/`)

Every one of the 14 iteration-1 failures was a test-artifact bug. Step 7 applied **zero** implementation fixes, **zero** `test_helpers/` fixes and **zero** test deletions, so there is no Step 7 site that can evidence PRD-silence or PRD-mismatch. I verified each cluster's asserted rule against the implementation rather than trusting the summary:

**Cluster 1 — error-envelope key (`body["error"]` -> `body["error_id"]`).** Subject: error response shape. Paths read: `implementation/response.py:63-72` (`"response_type": "error"`, `"data": {"error_id": ..., "message": ...}`), `implementation/errors.py:1-20,72`. This is exactly the envelope PRD §2.2 already prints, including the error-only `meta`. The bug was in the tests' access path into `validate_error()`'s return value. No PRD gap.

**Cluster 2 — `ERR_TIMESTAMP_AFTER_CLOCK` (8 tests).** Subject: which body instants are clock-gated, and the gate's comparison. Enumerated *every* callsite of the guard, not just the Step 7 sites: `services/guards.py:163` (`instant > db.now()`, i.e. equality is accepted) called from `routes/service_records.py:76` (`performed_at`), `routes/repair_attempts.py:51` (`repair_completed_at`), `routes/verification_tests.py:73` (`performed_at`), `routes/leak_events.py:30` (`detected_at`), `routes/cylinders.py:108` (`reclaim_issued_on`), `routes/recovery_equipment.py:77` (`verified_on`), `routes/regulatory_reports.py:33` (`period_end`). That is *precisely* the six-field list PRD §2.4 enumerates — no extra field is gated (notably not `period_start` or `due_on`) and none is missing. The collateral rules the fixes had to satisfy are also already verbatim in PRD: the half-open technician interval and the closed, 60-minute-buffered machine interval (`services/guards.py:112-134`, `routes/service_records.py:80-85` vs PRD §3.3); `completed_at`/`leak_rate_baseline_at` stamped at the logical clock on plan completion and `leak_rate_baseline_at` set to the follow-up test's `performed_at` with `closed_at` at the clock (PRD §3.5, §3.7); "setting the clock mutates no entity by itself" (PRD §2.4), which is what keeps the test_17 token stale. I specifically considered whether the impl's *unconditional* decontamination buffer diverges from PRD's differing-chemistry rationale sentence — it does not: PRD's normative sentence ("two records on the same machine collide if their buffered intervals share even a single instant") is already unconditional and matches `guards.require_no_equipment_conflict`, and no Step 7 fix turned on that distinction (the affected records were same-chemistry and were moved clear of the buffer entirely).

**Cluster 3 — factory misuse in `test_10_corner_entities.py`.** Subject: `expected_system_version` as a required field. Paths read: `routes/service_records.py:35` and `routes/retrofit_plans.py:28` (`validate.req_int`, so omission is `ERR_INVALID_REQUEST` at priority 3), plus the stale-version checks at `routes/service_records.py:53` and `routes/retrofit_plans.py:36` — both sitting after identity/reference resolution and before `require_active_system`, matching PRD §2.10 priorities 8 then 10. The bug was purely the helper's positional signature. No PRD gap.

**Precedence-pair tests (test_05/08/13).** Their surviving negative assertions (`!= ERR_TECHNICIAN_CERT_EXPIRED`, `!= ERR_CYLINDER_FILL_LIMIT_EXCEEDED`, `!= ERR_INSUFFICIENT_CYLINDER_CONTENTS`, `!= ERR_TECHNICIAN_SCHEDULE_CONFLICT`, `!= ERR_TIMESTAMP_AFTER_CLOCK`) are all decided by the ladder already spelled out in PRD §2.10, and the impl's guard order (`guards.py` docstrings 9->10->11->14...->29->32->33->39-42->47, `retrofit_plans.py:36-46` for 8/10/27/28/49) matches it.

Per-edit pre-edit search log: not applicable — zero edits committed. The enumerations above are the searches that led to the no-edit conclusion.

**Orchestrator note:** a byte-identical `PRD_FINALIZED.md` is the correct outcome when Step 7 made no `implementation/` fixes and no deletions — the 14 fixes were all local test-function bugs (envelope access path, clock-ordering in fixtures, a positional-argument misuse). Confirmed independently with `md5sum` (both `9938fd72...`) and `wc -l` (482/482). Residual-ambiguity work is therefore entirely Step 9's, which always runs.

## Step 9: Complete PRD — 2026-09-04T15:42:11.348Z

Run as **three sequential module-partitioned passes** over one shared `workspace/PRD_COMPLETED.md`. Pass 1 owned the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were forbidden to re-copy and edited in place with targeted string replacements only (a whole-file rewrite of a ~100 KB document would hit the model output cap and destroy earlier passes' work). Partition boundaries: pass 1 = app/middleware/response/errors/validate/util/constants/db + routes stores/systems/technicians/recovery_equipment/cylinders; pass 2 = routes service_records/leak_events/repair_attempts/verification_tests + services ledger/events/posture/guards; pass 3 = routes extension_requests/retrofit_plans/regulatory_reports/inspections/ops + services deadlines/plans/reports. Each pass handed forward the silences it found outside its own partition.

**Size progression:** 482 lines / 101,215 bytes (source) -> 109,571 (after pass 1) -> 121,669 (after pass 2) -> **130,497 bytes** (final). Line count 482 throughout — every edit was in-paragraph, no new sections, no added or removed lines. Total **65 edits: 49 ambiguity-pins, 16 mismatch-revisions.**

### Pass 1 (13 modules; 17 ambiguity-pins, 4 mismatch-revisions)
- `§2.1` — revise — mismatch — `X-User-ID`/`X-User-Role` "empty" clarified to include whitespace-only values — `middleware.py:38-41`
- `§2.1` — insert — ambiguity — store scoping applies only to the single-resource reads of §2.10 step 7; list endpoints and the leak-rate projection are never scope-filtered or scope-rejected — `middleware.py:80-83`, `stores.py:56-70`, `systems.py:92-115`
- `§2.2` — insert — ambiguity — `message` is advisory only; absent a specific message the server humanizes the `error_id` (`ERR_SYSTEM_RETIRED` -> `System retired.`) — `errors.py:8,12-18`
- `§2.3` — insert — ambiguity — non-integer/out-of-range `limit` and non-integer/negative `offset` are rejected `ERR_INVALID_REQUEST` (400), never clamped; an over-large `offset` returns an empty page with true `total_count` and `has_more` false — `response.py:75-95,58`
- `§2.4` — insert — ambiguity — clock exemption covers header *presence* only: a presented non-empty `X-User-Role` must be `PlatformAdmin`, otherwise `ERR_FORBIDDEN_ROLE` (403), not `ERR_UNAUTHENTICATED` — `middleware.py:29-37`
- `§2.5` — insert — ambiguity — every emitted instant, including echoed request values, is parsed (Z / explicit offset / naive-as-UTC), normalised to UTC and re-rendered with exactly three fractional digits, sub-millisecond precision truncated — `util.py:38-65`, `response.py:25-26`
- `§2.5` — insert — ambiguity — "mutation" means an actual stored-field change (`version`/`updated_at` stay put on a no-op action), with `RefrigerantSystem` the one resource that bumps unconditionally on every §2.9 cascade — `db.py:114-137`, `posture.py`
- `§2.6` — insert — mismatch — rounding disciplines govern computed values only; supplied masses (`full_charge_lbs`, `initial_charge_lbs`, `nominal_capacity_lbs`, `initial_contents_lbs`, the three service-record movements) are stored/echoed verbatim, not re-quantised — `validate.py:120-141`, `systems.py:50-56`, `cylinders.py:27-34`
- `§2.10` (priority 3) — insert — ambiguity — body parsed as JSON regardless of `Content-Type`; empty/whitespace body = empty object; non-object JSON rejected; undeclared fields ignored; explicit `null` = absent; required strings need a non-whitespace character; numerics must be JSON numbers (strings and booleans rejected) — `validate.py:13-30,33-59,89-92,120-123`
- `§2.11` — revise — mismatch — path-existence is checked *after* request-shape (step 3 before step 4), so a bad body plus an unresolvable path id reports `ERR_INVALID_REQUEST`; trailing slashes accepted — every route file, `app.py:39`
- `§2.11` — insert — ambiguity — filters match by exact equality and enum filters are not validated (unknown value -> empty page, `total_count` 0); the three boolean filters accept `true/false/1/0` case-insensitively, anything else `ERR_INVALID_REQUEST` — `response.py:103-128`
- `§3.1` — revise — mismatch — `state_code` is validated only as a non-empty string; the two-letter form is conventional, not enforced — `stores.py:46`
- `§3.1` — revise — mismatch — system registration retains `initial_charge_lbs` and a null `retirement_reason_code`, and runs the store through §2.9 steps 5-7 in full, leaving the new system at `version` 1 — `systems.py:64-87`, `posture.py`
- `§3.2` — insert — ambiguity — `reason_code` is required on both legs of the technician status loop and is discarded on reinstatement — `technicians.py:61,67-70`
- `§3.2` — insert — ambiguity — the 365-day equipment window is inclusive at its far edge and unbounded on the near side; a `last_verification_on` after the compared instant counts as current — `recovery_equipment.py:15-21`, `guards.py:33-40`
- `§3.2` — insert — ambiguity — cylinder over-fill at registration is `ERR_INVALID_REQUEST` (400), not `ERR_CYLINDER_FILL_LIMIT_EXCEEDED`, and is checked before `store_id`/`refrigerant_type_id` resolution; `initial_contents_lbs` is retained — `cylinders.py:30-37`
- `§3.2` — insert — ambiguity — reclaim-shipment preconditions are state-legality checks -> `ERR_INVALID_STATE_TRANSITION` (409) — `cylinders.py:83-84`
- `§3.2` — insert — ambiguity — reclaim-certification also gates `reclaim_issued_on` against the clock, and quantity-vs-purity are evaluated in §2.10 priority order (quantity wins) — `cylinders.py:107-112`
- `§3.4` — insert — ambiguity — projection rejects an unknown `method` / unparseable `as_of` with `ERR_INVALID_REQUEST` but accepts an `as_of` after the clock — `systems.py:116-127`
- `§3.7` — insert — ambiguity — retiring an already-`RETIRED` system yields `ERR_SYSTEM_RETIRED` (priority 10); `retirement_reason_code` is stored; the named `RETIRE` plan is checked for status and type only, not for belonging to the retiring system — `systems.py:158,170-181`, `guards.py:166-169`
- `§5` — insert — ambiguity — `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405) and `ERR_INTERNAL` (500) documented as out-of-catalogue routing/fault errors in the standard envelope — `app.py:48-63`, `errors.py:90-92`

### Pass 2 (8 modules; 15 ambiguity-pins, 6 mismatch-revisions)
- `§2.9` — insert — ambiguity — steps 1 and 2 are opt-in: only service-record create/void, retrofit-plan completion, and (step 2 alone) the closing follow-up test perform them; every other cascade begins at step 4 and leaves `current_charge_lbs`/`leak_rate_pct` stale — `posture.py:141-151`
- `§2.9 step 6` — insert — ambiguity — `capped` is re-derived on every exposure pass (can revert true->false); inspections visited in `created_at`,`_seq` order — `posture.py:51-67`
- `§2.9` — insert — ambiguity — each precedence rung's predicate, and that step 4 re-derives state from scratch rather than applying an incremental transition — `posture.py:12-33`
- `§2.10 item 11` — insert — mismatch — `ERR_LEAK_EVENT_TERMINAL` is evaluated *ahead* of priority 9, so a terminal event never yields `ERR_INVALID_STATE_TRANSITION` — `repair_attempts.py:37-38`, `verification_tests.py:52-53`
- `§3.1` — insert — ambiguity — open/overdue counts range over all systems regardless of status; `vented_loss_lbs` is a from-scratch re-sum over the store's non-voided ledger — `posture.py:90-114`
- `§3.3` — insert — ambiguity — omitted `cylinder_id` with moving mass is `ERR_INVALID_REQUEST` decided *before* reference resolution — `service_records.py:43-50`
- `§3.3` — insert — ambiguity — `leak_event_id` is existence-checked only: not required to match the system, not required to be non-terminal — `service_records.py:50`
- `§3.3` — insert — ambiguity — "governing retrofit plan" defined (newest `APPROVED` `RETROFIT`, else newest `IN_PROGRESS`, else the system's own chemistry); chemistry gate confined to three service types and skipped without a cylinder — `guards.py:62-91`
- `§3.3` — insert — ambiguity — `ERR_UNRECLAIMED_REFRIGERANT_REUSE` fires on any positive `refrigerant_added_lbs`, whatever the `service_type` — `guards.py:94-97`, `service_records.py:69-70`
- `§3.3` — insert — ambiguity — the two cylinder gates each test their own movement in isolation from the other, though the write applies both — `guards.py:139-147`
- `§3.3` — revise — mismatch — `vented_loss_lbs` re-summed, not incremented; plus the `system_charge_after_lbs`/`leak_rate_pct_after` snapshot and the plan-bubble count over either `plan_type` with no error at 0 or >=2 — `posture.py:111-114`, `service_records.py:121-136`
- `§3.4` — revise — mismatch — the rate recompute and trigger re-evaluation are unconditional on every accepted record, not only ones that add refrigerant — `service_records.py:133-137`
- `§3.4` — insert — ambiguity — manual `POST /leak-events` rejects `LEAK_RATE_CALCULATION` as an enum violation; the three preconditions run in written order with the applicability `ERR_INVALID_REQUEST` raised at that position, clock check last — `leak_events.py:21-30`
- `§3.5` — insert — ambiguity — the machine's store is compared against the *leak event's* system (priority 23 precedes 24); the attempt occupies the single instant `repair_completed_at` under the half-open rule and is subject to no equipment-decontamination check — `repair_attempts.py:43-54`, `guards.py:119-123`
- `§3.5` — insert — ambiguity — filing an attempt runs only cascade steps 5-7; no system field and no system `version` moves — `repair_attempts.py:96`
- `§3.5` — revise — mismatch — `current_attempt` falls back to the newest `VERIFIED` attempt while the event is `FOLLOWUP_PENDING` — `deadlines.py:26-41`
- `§3.5` — insert — ambiguity — `performed_at` before the attempt's `repair_completed_at` is `ERR_INVALID_REQUEST` raised after the priority-29 clock check — `verification_tests.py:73-75`
- `§3.5` — insert — ambiguity — an initial `PASS` is inert on the system (no baseline rebase, no rate/charge recompute, no re-settle, no `version` bump) — `verification_tests.py:130-135`
- `§3.5` — revise — mismatch — follow-up `PASS`: the tested attempt is marked `VERIFIED` when none is awaiting; baseline is *re-derived* under §3.4's three-way rule rather than forced to the test's `performed_at`; `current_charge_lbs` untouched; linked records' `version` advances — `verification_tests.py:108-132`, `ledger.py:118-141`
- `§3.5` — insert — mismatch — `retrofit_due_on` is edge-triggered on *entry* into `RETROFIT_MANDATED`, never restamped for a second mandated event, never cleared by settlement — `posture.py:31-32`
- `§3.8` — insert — mismatch — `void_reason_code` is a required non-empty string; the two `ERR_VOID_NOT_PERMITTED` gates run in written order with equality counting as "reached"; a `PASS` test depends on the record via **either** `triggering_service_record_id` **or** the record's own `leak_event_id` — `service_records.py:163-191`
- `§3.8` — insert — ambiguity — `vented_loss_lbs` re-summed rather than decremented, and the cylinder's `disposition` is *not* reverted — `service_records.py:209-216`, `posture.py:111-114`

Pass 2 also corrected a stale pass-1 hand-off: `Inspection.capped` was **already** pinned in the original PRD §3.9 and matches `posture.py:57` exactly, so only the cascade-side re-derivation needed pinning. It also declined two non-edits: §2.4's "may not lie in the future" already uniquely excludes equality for `require_not_after_clock`, and `db.touch` on void is behaviourally indistinguishable from `db.commit` because `voided` always flips False->True.

### Pass 3 (8 modules; 17 ambiguity-pins, 6 mismatch-revisions)
- `§2.9 ¶1` — revise — mismatch — "every other cascade begins at step 4" was over-broad; now scoped to cascades that touch a system, plus a third group beginning at **step 5** that touches no system field: extension decision/revocation, the sweep's post-pass store recomputation, and the three inspection actions — `extension_requests.py:126,155`, `ops.py:130-131`, `inspections.py:68,107,128`
- `§2.10 priority 10` — revise — mismatch — added retrofit-plan submission to the `ERR_SYSTEM_RETIRED` endpoint list — `retrofit_plans.py:110`
- `§3.6` — revise — mismatch — the `repair_deadline` = `initial_repair_deadline` + `extension_days_granted_total` identity holds only after a grant; a revocation restores the literal `deadline_before` snapshot taken at *filing*, which diverges when a second grant was approved in between — `extension_requests.py:146-148`, `deadlines.py:58-65`
- `§3.7` — revise — mismatch — submission gates were listed in reverse of executed order and `gwp_reduction_pct` was omitted; now pins retired -> prohibited -> incompatible (10/27/38), all three derived figures rewritten, and that a refused submission persists nothing (scoring on a copy) — `retrofit_plans.py:108-127`
- `§3.7` — revise — mismatch — completion re-derives **both** `current_charge_lbs` and `leak_rate_pct` (steps 1+2), and `compliance_state` can settle at `LEAK_OPEN` when a surviving non-mandated event remains — `retrofit_plans.py:184-186`, `posture.py:12-33`
- `§3.9` — revise — mismatch — "all four money fields at 0.00" -> `days_late` 0 plus three money fields; null-field list completed — `regulatory_reports.py:52-56`
- `§3.6` — insert — ambiguity — strictness of both filing windows, and that filing has **no state gate** beyond the terminal check (`REPAIR_OVERDUE`, `RETROFIT_MANDATED` are valid targets; never `ERR_INVALID_STATE_TRANSITION`) — `extension_requests.py:39-45`, `deadlines.py:68-70`
- `§3.6` — insert — ambiguity — filing recomputes nothing and bumps no other resource's `version`/`updated_at` — `extension_requests.py:46-64`
- `§3.6` — insert x2 — ambiguity — the 15-day window sits immediately after the `PENDING` check and ahead of all constraints; the approval's recomputation is store-only (steps 5-7) — `extension_requests.py:95-98,126`
- `§3.6` — insert — ambiguity — `denial_reason_code` required but **not retained**; denial skips the terminal-event check and recomputes no store — `extension_requests.py:93,102-106`
- `§3.6` — insert — ambiguity — `deadline_after` retained; revocation recomputation store-only — `extension_requests.py:152-155`
- `§3.6` — insert — ambiguity — the ordering key per sweep pass, `created_at` first tie-breaker, insertion order final — `ops.py:46,63,84,102,121`
- `§3.6` — insert — ambiguity — store consequences deferred: each touched store recomputed **once** after all five passes in first-touch order; `stores_recomputed_count` = distinct touched stores; ids listed in pass order in a single-object envelope — `ops.py:30-32,130-141`
- `§3.7` — insert — ambiguity — non-future `due_on` -> `ERR_INVALID_REQUEST` at priority 3 ahead of reference resolution; cost band tested on the **supplied** value while `estimated_cost_usd` is stored re-quantised to two decimals (explicit contrast with §2.6) — `retrofit_plans.py:29-30,45-47,55`
- `§3.7` — insert x2 — ambiguity — `submission_note` null at filing; superseding covers either `plan_type` and bumps each superseded plan's `version` — `retrofit_plans.py:63,71-76`
- `§3.7` — insert — ambiguity — `submission_note` stored, emitted, and sticky across resubmissions — `retrofit_plans.py:125-126`
- `§3.7` — insert — ambiguity — `service_record_id` checked for existence only; both completion preconditions report `ERR_INVALID_STATE_TRANSITION` — `retrofit_plans.py:159-164`
- `§3.9` — insert — ambiguity — report totals written at **creation** as well as submission — `regulatory_reports.py:58`
- `§3.9` — insert — ambiguity — report `submission_note` stored/emitted/sticky — `regulatory_reports.py:95-96`
- `§3.9` — insert — ambiguity — filings never feed the §2.9 cascade; assessments never enter `penalty_exposure_total_usd` — `regulatory_reports.py:101-120`
- `§3.9` — insert — ambiguity — citations stored with exactly three fields in payload order (extra keys dropped); `chronic_multiplier_applied`, `penalty_exposure_usd` and `capped` all written at open — `inspections.py:18-32,54-66`
- `§3.9` — insert — ambiguity — all three inspection actions run steps 5-7 for the whole store, re-pricing every live sibling inspection — `inspections.py:68,107,128`, `posture.py:70-131`

Pass 3 deliberately left four things unedited: `plans.score_plan`'s unresolvable-chemistry early return is **unreachable** (documenting it would invent behavior); the clock endpoint's `{current_utc, previous_utc}` shape was already pinned by pass 1 in §2.4; the surcharge ladder, both leaked-mass variants, window bounds, overlap rule and per-citation rounding order were already exact; and retrofit-plan creation's trailing store recomputation is unobservable under §2.5's no-op rule.

**Residual silence/mismatch: none found in any partition.** Pass 3 states its own partition is fully pinned bar the unreachable branch.

**Orchestrator verification (independent):** `PRD_COMPLETED.md` is 482 lines / 130,497 bytes with md5 `4de3b24c...`, distinct from `PRD_FINALIZED.md`'s `9938fd72...` — so the scan demonstrably ran rather than producing a byte-identical copy. Heading count 28, unchanged; the file still ends on the final `ERR_PLAN_COST_OUT_OF_RANGE` error-catalogue row, so no truncation. `find implementation -name '*.py' -newermt '2026-09-04 15:07'` returned nothing: no implementation file changed after the clean sweep, so the 8/8 x 116/116 evidence in `results.[1-8].json` still describes the shipped code. Pipeline complete.
