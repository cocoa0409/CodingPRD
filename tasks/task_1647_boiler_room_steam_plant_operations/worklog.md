# Worklog — task_1647_boiler_room_steam_plant_operations

## Step 1: Create Task Directory — 2026-08-14T04:34:00.000Z

Task directory `tasks/task_1647_boiler_room_steam_plant_operations/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher; Step 1 treated as DONE per instructions (no index scan, no writes outside this directory).

## Step 2: Generate Scaffold — 2026-08-14T04:58:00.000Z

Note: the first subagent attempt exited after drafting design thinking without writing files; resumed the same agent via SendMessage, which then wrote all three files, fixed YAML flow-sequence quoting, added flat alias GETs to satisfy FK reverse-reachability lint, and finished with a clean lint verdict. Verbatim summary:

All three files are valid. Final lint verdict is clean. Here's the summary:

## Summary

**Files written:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1647_boiler_room_steam_plant_operations/SCAFFOLD.yaml` — §1.0–§1.7 (no scaffold_difficulty_design / scaffold_corner_design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1647_boiler_room_steam_plant_operations/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1647_boiler_room_steam_plant_operations/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

**Counts:**
- Entities: **10** (Plant, Boiler, Operator, BoilerLogEntry, ChemistryLog, Inspection, SteamTrap, LoadDispatch, Incident, FuelDelivery)
- State machines: **7** (Boiler with 3 parallel dims, BoilerLogEntry, ChemistryLog, Inspection, Operator, LoadDispatch, Incident)
- Calculations: **9** (combustion_efficiency, steam_trap_loss_cost, blowdown_volume_recommendation, lead_lag_dispatch_selection, certificate_expiry_check, license_expiry_check, fuel_inventory_balance, feedwater_mass_balance, dispatch_window_overlap_check, inspection_scheduling_conflict_check — actually 10)
- Endpoints: **68** (after adding flat alias GETs for FK reverse-reachability)
- Error codes: **27**
- §1.8 instances: **18** (9 rules × 2)
- §1.9 instances: **36** (active; 4 are `excluded_because:` stubs that don't run)

**Lint verdict:** clean — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.

**Notable design decisions (harder-than-expert calibration):**
- **Dual-variant calcs across distinct domains:** combustion_efficiency (input/output vs ASME PTC 4.1 heat-loss, gated by `state_code='MA'`) on Boiler; steam_trap_loss_cost (Napier linear vs Grashof sqrt, gated by `state_code='NY'`) on SteamTrap.
- **Combinatorial formulas in distinct modes:** lead_lag_dispatch_selection (mode a: 3-input non-linear with min() saturation + additive LEAD_BONUS); blowdown_volume_recommendation (mode b: 7-step chain with rounding-order trap — step 6 must consume the ROUNDED value from step 5).
- **Non-linear state machines on different entities:** Boiler carries THREE parallel dimensions (ops_status × cert_status × water_status) with cross-dimension forced transitions; Operator.license_status has cyclic shape (ACTIVE→EXPIRING→ACTIVE via renew-license).
- **Transitive cascades from different triggers:** Incident→TRIPPED→LoadDispatch CANCELLED→auto-create lag-dispatch (depth 3); Relief pop FAILED→cert SUSPENDED→ops TRIPPED (depth 2).
- **Priority collisions across distinct error-category pairs:** state vs business_safety (warm on TRIPPED+LAPSED boiler returns ERR_INVALID_STATE); business_safety vs business_referential (wrong-state operator with bad FK returns ERR_LICENSE_WRONG_STATE).
- **Boundary precision on different metrics/endpoints:** cert expiry at exactly +30days flips to EXPIRING (inclusive `<=`); fuel_inventory reaching exactly 0 succeeds (zero-edge) but -1 fails.
- **Cross-entity state deps on different pairs:** Boiler→Operator (license gate); Boiler→Inspection (POST_INCIDENT PASSED gate for reset).
- **Temporal overlap with different interval semantics:** LoadDispatch uses half-open `[start, end)` (adjacent allowed); Inspection uses closed+buffered intervals (touching endpoints conflict).
- **Compensating invariants on different quantities:** fuel conservation (received - consumed == inventory); feedwater mass balance (feedwater == blowdown + steam/8.345 within drift tolerance).
- **Two OCC concurrency rules** (log-verify on Boiler.version; outcome-record on Inspection.version) — both pass the §1.2.1 serial-observability filter.
- **Segregation of duties RBAC** — Operator records, different Operator verifies, only PlantManager voids VERIFIED entries.
- **Logical clock** via `POST /_clock/set_current_utc` with default `2026-08-01T00:00:00Z` for deterministic time-gated tests.

## Step 3: Copy Shared Files — 2026-08-14T04:58:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1647_boiler_room_steam_plant_operations/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T05:25:00.000Z

Verbatim subagent summary:

All checks pass. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1647_boiler_room_steam_plant_operations/workspace/PRD.md` (330 lines).

## Summary

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1647_boiler_room_steam_plant_operations/workspace/PRD.md` — 330 lines, 68 endpoint rows in §4, 26 error rows in §5.

### Section list
- §1 Introduction (2 paragraphs — regulatory context + audit/posture-driven design commitments)
- §2 Global Specifications: 2.1 Roles & identity semantics, 2.2 Response Structure (verbatim, byte-compared PASS), 2.3 Pagination, 2.4 Logical Plant Clock & Operations Checkpoint, 2.5 Common Resource Properties, 2.6 Numeric Precision & Rounding, 2.7 Validation Pipeline & Priority (all 22 rules, ordered), 2.8 OCC, 2.9 Nested Retrieval & Flat Aliases, 2.10 Fuel Ledger & Water Mass Balance, 2.11 Scheduling Interval Semantics
- §3 Business Logic (9 subsections): 3.1 plant/boiler/operator/fuel establishment, 3.2 licensing & duty segregation, 3.3 water chemistry & blowdown, 3.4 boiler ops & lead/lag selector, 3.5 log entries & efficiency ledger, 3.6 inspections & certificates, 3.7 steam traps & loss projection, 3.8 load dispatch, 3.9 incidents & posture
- §4 Endpoint Definitions (68 rows, 4 columns), §5 Error Catalogue (26 rows, 2 columns)

### Coverage audit (scaffold table → PRD sections)
- `entities` (10) → field defaults/structured content in §2.5 + §3.1–3.9 narrative; all 76 field names backticked
- `state_machines` (7 machines, ~40 transitions) → ops §3.4, cert §3.6, water §3.3, log-entry §3.5, chemistry §3.3, inspection §3.6, operator §3.2, dispatch §3.8, incident §3.9 — every from/to, precondition + error_id, and side effect expressed
- `calculations` (10) → combustion efficiency dual-variant (§3.5), trap Napier/Grashof (§3.7), blowdown 7-step pinned chain with rounding trap (§3.3), lead/lag scoring (§3.4), cert/license expiry boundaries (§3.6/§3.2), fuel & water invariants (§2.10), half-open vs closed+buffered intervals (§2.11)
- `validations` (22) → §2.7 numbered pipeline in exact priority order + trigger-side restatements in §3
- `concurrency_rules` (2) → §2.8 (endpoint, occ field, ERR_STALE_VERSION/412, no simultaneity framing) + restated in §3.5/§3.6
- `endpoints` (68) → §4 table; side effects in §2/§3
- `errors` (26) → §5 + all mentioned in §2/§3 prose
- `roles` (3) → §2.1 with per-role identity translation (Operator entity-backed; PlantManager/Inspector opaque)

### Hard contract reports
- **Contract 1 (fields)**: 76/76 entity fields, 12/12 endpoint input-output names, 10/10 path params, 27/27 error ids, 63/63 enum values, 5/5 role/header names — **PASS** (path params verified inside `{...}` path tokens per example-PRD convention)
- **Contract 2 (rules)**: all 22 validations with priority expressed; 2/2 OCC rules with endpoint+field+error+status; ~40 transitions fully expressed; 10/10 calculations with constants and boundary inclusivity; all side effects and applies_to scopes enumerated; sibling branches rendered symmetrically (four trip from-states, EXPIRING vs LAPSED recovery asymmetry, both pop-test bounds, both calc variants) — **PASS**
- **Contract 3 (§3 path purity)**: 538 backtick tokens scanned, 0 violations — **PASS**; §2.2 verbatim byte-compare — **PASS**; fuzzy-word and operator-syntax sweeps clean

### Zero-Silence decisions
1. **Undefined constants**: `SULFITE_MIN_PPM`, `PHOSPHATE_MIN_PPM`, `PHOSPHATE_MAX_PPM`, `CHEMISTRY_CRITICAL_COUNT`, `CRITICAL_CYCLES_FACTOR`, `CHEMISTRY_RECOVERY_COUNT`, and `CONDITIONAL_FOLLOWUP_DAYS` are referenced by scaffold rules but never valued there — rendered symbolically in backticks rather than inventing numbers.
2. **`FuelDelivery.price_per_gal`**: the trap-loss calculation references a delivery price that is not an entity field; rendered faithfully as "price from the most recent delivery, default 3.50/gal when none" per the scaffold's own input_set text.
3. **Pop-test double statement**: scaffold both rejects PASSED-with-out-of-envelope lift (validation 15) and describes forcing FAILED (transition side effect) — both rendered, with validation framed as firing on PASSED recordings and the forcing as the outcome-level cascade.
4. **Validation 5's split error ids**: single rule maps to `ERR_WATER_CRITICAL` (warm, water CRITICAL) and `ERR_WATER_OUT_OF_SPEC` (bring-online, not IN_SPEC) per the error catalog and state machine.
5. **Unpaired schema/state errors**: boiler setpoint vs plant header, missing `certificate_number`, positivity constraints, and verify-on-TRIPPED mapped explicitly to `ERR_INVALID_REQUEST` / `ERR_INVALID_STATE` consistent with the catalog's generic conditions.
6. **Clock semantics**: rendered as a single logical plant clock (default 2026-08-01T00:00:00Z) per the endpoint description, with all expiry math anchored to it.

## Step 5: Generate Unit Tests — 2026-08-14T05:50:00.000Z

Verbatim subagent summary:

All 75 test items collect cleanly (74 test functions; one is parametrized ×2). The work is complete. Final summary:

## Summary

**Generated** for `task_1647_boiler_room_steam_plant_operations`:

### Test counts
- **Queue A (Difficulty): 38 tests** — all 18 instances covered with ≥2 tests each (two instances got 3).
- **Queue B (Corner): 36 tests** — all 36 non-stub instances covered with ≥1 test; the 4 `excluded_because:` stubs were verified to resolve to real difficulty instances and were not translated.
- **Total: 74 test functions / 75 collected items**, across 10 files (`test_01` plant/boiler setup & listing → `test_10` access control & OCC).

### Helper inventory (`test_helpers/`)
- `types.py` — 17 status/role enums + 10 TypedDicts (append-only BoilerLogEntry/ChemistryLog/FuelDelivery correctly omit `updated_at`/`version` per PRD §2.5)
- `api_client.py` — `ApiClient(GenericApiClient)`, one method per PRD §4 endpoint (46 methods), module-level `api_client`
- `api_errors.py` — `ApiErrorId` (27 errors) + HTTP map registered via `set_error_http_status_map`
- `assertions.py` — per-entity shape assertions + `assert_fuel_ledger_invariant` / `assert_water_mass_balance`
- `factories.py` — 10 payload factories (input fields only)
- `constants.py` — PRD-named thresholds (enthalpy/HHV/loss constants, Napier/Grashof, 8.345 lb/gal, 25.0 gal drift, 30d/60d expiry windows, inspection 4h+2h occupancy)
- `test_users.py` — `TEST_USERS` + mandatory `make_operator_headers(operator_id)` for the entity-backed Operator role; `ANON_HEADERS`/`ROLE_ONLY_HEADERS` for 401 tests
- `fixtures.py` — tiered composites: plant/operator/boiler creators, `create_online_boiler`, `trip_boiler_via_incident`, OCC-fresh `verify_entry` / `create_and_verify_log_entry`, inspection schedule/record/PASSED-annual helpers, dispatch and leaking-trap helpers
- `__init__.py` barrel; `test_suite/conftest.py` exposes `api` + role-header fixtures

### Per-instance disposition
All 18 difficulty instances **emitted**; all 36 non-stub corner instances **emitted**; 4 corner stubs **skipped as designed** (pointers all resolve). No `skip`/`xfail` anywhere; every docstring carries a verbatim-grep-verified PRD citation plus exactly one `Design:` tag (audit script: 0 failures).

### PRD-derivability adjudications made
1. **Pop-test out-of-envelope PASSED recordings are PRD-contradictory** — §2.7 item 15 says "rejected with `ERR_RELIEF_SETPOINT_EXCEEDED`/`ERR_RELIEF_NO_LIFT`", while §3.6 says the envelope check "forces" a `FAILED` outcome with cascades. I translated `boiler_parallel_dimensions_cert_vs_ops` and `relief_failure_cert_suspension_depth2` via the unambiguous **explicit-`FAILED`** path (§3.6: "Any explicitly recorded `FAILED` pop test carries the same two cascades") and added in-envelope-PASSED / POST_INCIDENT-recovery companions. No test asserts either behavior for an out-of-envelope PASSED recording; the excluded stubs (`relief_setpoint_exceeded_returns_422`, `err_relief_no_lift_when_pressure_below_setpoint`) stay untranslated.
2. **`blowdown_volume_rounding_order_trap_mode_b`** — the rounding-chain output (`bd_volume_gal_per_day`) is exposed on no PRD-declared response surface, so per the instance's own fallback I assert the deterministic, PRD-derivable `cycles_of_concentration` recomputation (11.5 after latest log; 5.0 after voiding it), citing §3.3 verbatim.
3. **Fuel-underflow on verify** — PRD names `ERR_FUEL_INVENTORY_UNDERFLOW` only for voids, but §2.10's hard invariant ("may never go negative") plus the catalogue make it the only consistent error for an underflowing verify; emitted as designed (with the zero-boundary success companion). Also note: three difficulty recipes verify entries with no fuel delivered; I added a fuel delivery to those setups so the asserted efficiency/selector claims hold under either enforcement reading (asserted values are unaffected — the formulas don't involve inventory).
4. **License-gate isolation fix** — in `boiler_warm_requires_operator_license_active`, flipping the license to EXPIRED requires `run_ops`, which also lapses a never-inspected boiler's cert (priority 6 fires before the license gate at 8). I record a PASSED annual inspection first so the license gate is the only failing check.
5. **Unspecified chemistry config constants** (`SULFITE_MIN_PPM`, `PHOSPHATE_*`, `CRITICAL_CYCLES_FACTOR`) appear only symbolically in the PRD. I used the design indices' in-spec readings (sulfite 30 / phosphate 40, cycles ≤ 5.0) verbatim and deliberately avoided asserting `water_status == OUT_OF_SPEC` in cases where a small invented `CRITICAL_CYCLES_FACTOR` could force CRITICAL instead (the bring-online test asserts only the gate error, which fires for any non-IN_SPEC state from WARMING only if the boiler isn't forced to STANDBY — residual risk documented here; cycles=15 assumes factor ≥ 1.5, the conventional choice).
6. **Dropped two non-derivable micro-assertions**: `Boiler.version == 1` at creation (PRD never states the initial version value) and "client-supplied `ops_status` ignored" (PRD silent on unknown-field handling); the `boiler_system_fields_input_ignored` instance instead asserts the full PRD-verbatim initial-state triple, cycles 1.0, and zero totals.

## Step 6: Generate Implementation — 2026-08-14T06:12:00.000Z

Verbatim subagent summary:

Everything compiles, no seeding anywhere, and the route count (68) matches the endpoint table exactly (50 nested + 18 flat aliases). The implementation is complete and verified.

## Summary

**File inventory** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1647_boiler_room_steam_plant_operations/workspace/implementation/`):

- `start.sh` — guarded pip install (skips when flask importable), `exec python3 app.py`, foreground
- `requirements.txt` — `flask>=2.2,<4.0`
- `app.py` — Flask factory, envelope-wrapped error handlers, blueprint registration, `0.0.0.0:$PORT`
- `store.py` — in-memory dicts for all 10 entity types + insertion/causal-event counters (empty at boot, no seeding)
- `clock.py` — logical plant clock, default `2026-08-01T00:00:00Z`
- `errors.py` — all 27 PRD error IDs with exact HTTP statuses
- `util.py` — response envelope (`meta.api_request_id/api_request_timestamp`, `response_type`, `data`), 3-fractional-digit timestamps, `limit/offset/total_count/has_more` pagination (default 10, clamp [1,100]), round-half-up 2dp/4dp helpers, body validators
- `auth.py` — `X-User-ID`/`X-User-Role` auth (401) + role authorization (403)
- `resolve.py` — left-to-right scope-checked path resolution (404) + flat-alias lookups
- `services.py` — all domain logic (below)
- `routes/` — 11 modules (plants, boilers, operators, log_entries, chemistry, inspections, steam_traps, dispatches, incidents, fuel, aliases)

**Endpoint count:** 68 route handlers = 50 nested endpoints + 18 flat alias GETs — matches the scaffold endpoint table 1:1.

**Calculations implemented:**
- `combustion_efficiency` — dual variant: input-output `(steam·1010)/(fuel·140000)·100` default vs MA heat-loss `100 − (6.5 + 4.0 + (blowdown/max(feedwater,1e-6))·100 + 1.5)`; verified 90.18 (TX) vs 80.31 (MA) on identical inputs
- `steam_trap_loss_cost` — Napier `51.45·d²·p` vs NY Grashof `24.24·d²·√p`; verified 463.05 vs 18.18; annual = leak·8760; cost chained from rounded intermediates; price from latest delivery or 3.50 default
- `blowdown_volume_recommendation` — full 7-step chain with the step-5 round-then-multiply ordering pin and [5.0, 5000.0] clamp; degenerate guards (cycles ≤ target → 0%, pct ≥ 100 → clamped)
- `lead_lag_dispatch_selection` — eligibility (ONLINE + VALID + non-CRITICAL), score = capacity · efficiency-factor · (1 − min(cycles/10,1)·0.15) + 5000 incumbency bonus, 4dp scoring, tie-break capacity DESC then created_at ASC, null fallback
- `certificate_expiry_check` / `license_expiry_check` — strict `<` for lapse/expiry, inclusive `<=` 30d/60d windows (boundary-verified: expiry == now → EXPIRING, 1s past → LAPSED)
- `fuel_inventory_balance` — compensating ledger, 2dp, underflow enforced on both verify and void
- `feedwater_mass_balance` — drift > 25.0 gal auto-raises MEDIUM CHEMISTRY_EXCURSION incident
- `dispatch_window_overlap_check` — half-open `[start,end)`, adjacency allowed
- `inspection_scheduling_conflict_check` — closed buffered `[t−2h, t+6h]`, touching conflicts

Also: three parallel Boiler dimensions (ops/cert/water) with independent tracks; depth-3 trip cascade (trip → cancel future SCHEDULED windows → auto-create replacement from remaining ONLINE boilers within 15 min); run_ops checkpoint (license recompute, cert recompute with FAILED-annual poisoning, dispatch activate/complete, posture, exactly +1 ops_run_index/plant version); SoD on verify; OCC (`expected_boiler_version`/`expected_inspection_version`, required, 412, checked last per pipeline).

**Key PRD-interpretation decisions:**
1. **Pop-test envelope violation → forced FAILED (200), not 422.** PRD §3.6 says both "rejected with ERR_RELIEF_NO_LIFT" and "the envelope check forces it — ends as a FAILED outcome". I chose forced-FAILED because both difficulty-design instances assert it and both 422 corner tests were explicitly excluded in favor of them. Equality at setpoint and at the upper tolerance bound passes (Decimal comparison).
2. **License gate (priority 8) evaluated before cert/emergency gates (6/7) on warm/bring-online.** The design test `boiler_warm_requires_operator_license_active` has the boiler LAPSED by run_ops (no PASSED inspection) yet expects ERR_OPERATOR_LICENSE_INVALID — irreconcilable with strict §2.7 numeric order. State(4) and water(5) still precede everything, so both designed priority-pair tests hold.
3. **Unspecified chemistry constants chosen** so the PRD's own worked readings hold (sulfite 30/ phosphate 40 in-spec; cycles 15.0 out-of-spec but not critical): SULFITE_MIN=20, phosphate band [20,60], CRITICAL_COUNT=3, CRITICAL_CYCLES_FACTOR=1.5 (strict >), RECOVERY_COUNT=2, CONDITIONAL_FOLLOWUP_DAYS=30.
4. **Posture rule:** any OPEN/ACK HIGH/CRITICAL incident OR any TRIPPED boiler → DEGRADED if any boiler ONLINE else EMERGENCY; else NORMAL. This uniformly reproduces the incident-trip, pop-fail-trip, mitigate, reset, and run_ops posture behaviors in the design docs.
5. **Blowdown "latest 24h" window is anchored to the chemistry log's `recorded_at`**, not the plant clock — the design fixture's math (steam_rate 350) only works that way since the clock is never set in that scenario.
6. **Blowdown recommendation is computed but not serialized** (scaffold's ChemistryLog has no such field; the design docs assert only `cycles_of_concentration`).
7. **`price_per_gal` accepted optionally on fuel-deliveries** but kept internal (the entity table omits it while the loss calc references it); loss calc falls back to 3.50.
8. **run_ops cert rule skips SUSPENDED boilers** (SUSPENDED restores only via POST_INCIDENT PASSED, causal-event ordering), and per the literal any-kind rule a boiler whose latest PASSED inspection is a pop test (null expiry) lapses at the next checkpoint.
9. **Incident close from OPEN allowed only for LOW** (MEDIUM blocked too — "only when its severity is LOW").
10. **Timestamps serialized with 3 fractional digits** (`.000Z`) per PRD §2.5; the harness's instant comparisons normalize fractions.

**Verification:** 137 smoke assertions pass across three rounds (all design-doc expected values, cascades, RBAC, OCC, boundaries, interval semantics, ledger compensation); `bash start.sh` from `./implementation/` boots to HTTP in ~0.7s on a fresh port and process.

## Step 7: Run Tests and Iterate — 2026-08-14T06:25:00.000Z

Verbatim subagent summary:

All 8 rounds passed 75/75. The loop is complete.

## Summary

- **Iterations run**: 2 (first sweep found 1 deterministic failure in all 8 rounds; fix applied; second sweep passed all 8 rounds at 75/75).

- **Tests deleted**: none.

- **Fixes applied to `test_helpers/`**: none.

- **Fixes applied to `test_suite/`**:
  - `/home/ubuntu/github/CodingPRD/tasks/task_1647_boiler_room_steam_plant_operations/test_suite/test_10_access_control_and_concurrency.py` — `TestValidationPriorityLicenseVsReferential::test_license_wrong_state_precedes_referential_check`. The setup step called `validate_success(api.create_operator(...))` without `expected_status=201`. `validate_success` defaults to expecting HTTP 200, but `POST /plants/{plantId}/operators` returns 201 per PRD §4 ("Operations that create a new, stand-alone resource or add a new resource to a collection return a 201 Created status code"). Added `expected_status=201` to the setup call. This is a test-side bug fix that makes the test more faithful to PRD; the actual asserted rule (ERR_LICENSE_WRONG_STATE precedes ERR_REFERENCED_NOT_FOUND per PRD §2.7 stage 9 before stage 11) is unchanged.

- **Fixes applied to `implementation/`**: none. The implementation was already PRD-faithful; the only failure was a test-setup status-code expectation bug. The known friction point noted in the prompt (license gate before cert/emergency gate on warm/bring-online) does not actually surface as a failure in the current suite — the only test that touches it (`test_warm_rejected_when_operator_license_expired`) passes in all 8 rounds because the test setup pre-clears the cert gate with a PASSED annual inspection before checkpointing the license to EXPIRED, which isolates the license gate as the only failing check; that setup is PRD-consistent, so no adjudication was required.

## Step 8: Finalize PRD — 2026-08-14T06:35:00.000Z

Verbatim subagent summary:

Task complete. PRD_FINALIZED.md is a byte-identical copy of PRD.md — zero PRD edits were warranted.

**File status**
- `/home/ubuntu/github/CodingPRD/tasks/task_1647_boiler_room_steam_plant_operations/workspace/PRD.md`: 330 lines
- `/home/ubuntu/github/CodingPRD/tasks/task_1647_boiler_room_steam_plant_operations/workspace/PRD_FINALIZED.md`: 330 lines
- %-delta: 0.0% (`diff -q` confirms identical)

**Changes**
- None.

**Rationale (per the single Step 7 diff item)**
- `test_suite/test_10_access_control_and_concurrency.py` — `TestValidationPriorityLicenseVsReferential::test_license_wrong_state_precedes_referential_check` — the fix added `expected_status=201` to a setup call for `POST /plants/{plantId}/operators`. This is a pure test-side bug: the test helper `validate_success` defaults to expecting 200, while the PRD already uniquely determines the status code. PRD §4 (PRD.md line 225) states verbatim: "Operations that create a new, stand-alone resource or add a new resource to a collection return a `201 Created` status code." The implementation agrees — `implementation/routes/operators.py:49` returns `success_object(operator_json(rec), 201)` from `create_operator`. No PRD silence, no PRD/impl mismatch — so no PRD edit.
- The asserted rule itself (ERR_LICENSE_WRONG_STATE at stage 9 precedes ERR_REFERENCED_NOT_FOUND at stage 11) is already pinned by PRD §2.7's fixed global validation order and was unchanged by Step 7.

**Per-edit pre-edit search log**
- No edits were committed, so there are no edit entries to log. For completeness, the verification performed for the candidate subject (HTTP status for `POST /plants/{plantId}/operators`):
  - (a) Subject: status code returned when adding an operator to a plant's operator collection.
  - (b) Impl paths enumerated and read: `implementation/routes/operators.py` lines 27–49 (`create_operator` → `return success_object(operator_json(rec), 201)`), plus grep across `implementation/routes/*.py` for the operators endpoint family (aliases.py GET routes, incidents.py/chemistry.py/log_entries.py operator references — none touch creation status), and PRD.md line 225 (§4 status-code rule).
  - (c) Wording adjustment: none — the existing PRD §4 sentence already covers the case exactly as implemented; a fresh implementer reading §4 plus the §2/§3 endpoint narratives would produce a 201 for this route.

## Step 9: Complete PRD — 2026-08-14T06:55:00.000Z

Verbatim subagent summary:

All edits complete and verified. Final state: 22 diff hunks (30 discrete edits), ERR_RELIEF_* remains only in the §5 catalog (identifiers exist in impl `errors.py` but are never raised; §2.7 item 15 and §3.6 now unambiguously describe forced-FAILED).

## Report

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1647_boiler_room_steam_plant_operations/workspace/PRD_COMPLETED.md`

**Size:** PRD_FINALIZED.md 330 lines / 57,221 chars → PRD_COMPLETED.md 333 lines / 61,838 chars (**+3 lines, +4,617 chars**).

**Counts:** 25 ambiguity-pins, 7 mismatch-revisions (30 edits collapsed into 22 diff hunks; several edits share single-line paragraphs).

**Changes (one bullet each):**

- §2.2 — insert — ambiguity — pin undefined-path 404 and unsupported-method 405 both carrying `ERR_NOT_FOUND` in the standard envelope — implementation/app.py:37-43
- §2.3 — insert — ambiguity — `limit`/`offset` out-of-range values are clamped (not rejected), non-integer → `ERR_INVALID_REQUEST`, `has_more` = offset+returned < total_count, `created_at` ties break by insertion order — implementation/util.py:108-133
- §2.5 — insert — ambiguity — `version` begins at 1 on creation — implementation/util.py:246-255
- §2.7 intro — insert — ambiguity — field-level validation (missing/wrongly-typed/out-of-enum) → `ERR_INVALID_REQUEST` (400) — implementation/util.py:139-241
- §2.7 item 8 — revise — ambiguity — ACTIVE-license gate also covers recording log entries, chemistry logs, and surveys, but NOT creating steam traps, dispatches, or incidents — implementation/routes/log_entries.py:62, chemistry.py:54, steam_traps.py:97 (gated) vs steam_traps.py:36, dispatches.py:39, incidents.py:44 (ungated)
- §2.7 item 15 — revise — **mismatch** — out-of-envelope `PASSED` pop test is NOT 422-rejected (`ERR_RELIEF_SETPOINT_EXCEEDED`/`ERR_RELIEF_NO_LIFT` never raised); outcome is forced to `FAILED` with §3.6 cascades — implementation/services.py:813-822
- §2.7 item 18 — revise — ambiguity — fuel-underflow check also blocks verification, not only voiding — implementation/services.py:380-385, routes/log_entries.py:133
- §2.7 post-list — insert — **mismatch** — on warm/bring-online the caller-side gates (8, 9) run after water (5) and ahead of cert (6)/emergency (7); on log-entry void the role check (17) runs before the license gate (8) — implementation/routes/boilers.py:140-154, 169-189; routes/log_entries.py:149-158
- §2.10 — insert — ambiguity — auto-raised drift incident names the boiler in `triggered_boiler_id` — implementation/services.py:433-445
- §3.1 — revise — **mismatch** — `header_pressure_actual_psi` reads the most recent `VERIFIED` entry (was "non-voided"), tie on `recorded_at` → most recently created — implementation/services.py:253-271
- §3.3 — insert — ambiguity — cycles quotient pinned to 2dp round-half-up; all thresholds (10.0 max, critical product, bring-online gate) consume the rounded value — implementation/services.py:522-530, routes/boilers.py:182-189
- §3.3 — insert — ambiguity — deterioration check runs on the same reading, so one severe reading carries `IN_SPEC` directly to `CRITICAL` (ONLINE boiler ends STANDBY via the BANKING shed) — implementation/services.py:541-558
- §3.3 — insert — ambiguity — voiding with no remaining logs also resets `cycles_of_concentration` to 1.0; voiding never moves `ops_status` nor raises incidents — implementation/services.py:614-656, routes/chemistry.py:99-112
- §3.3 — revise — ambiguity — blowdown step-3 window anchored at the chemistry log's own `recorded_at` (inclusive both ends), not the plant clock — implementation/services.py:594-600
- §3.3 — insert — ambiguity — blowdown recommendation is internal-only, never serialized — implementation/services.py:580-581, 114-118
- §3.5 — insert — ambiguity — verification that would push `fuel_inventory_gal` negative refused with `ERR_FUEL_INVENTORY_UNDERFLOW` — implementation/routes/log_entries.py:132-133
- §3.5 — revise ×2 — **mismatch** — header-pressure adoption/recompute reads among `VERIFIED` entries (both occurrences of "non-voided entries") — implementation/services.py:253-271
- §3.5 — insert — ambiguity — `efficiency_pct` unset (null) when no verified entries remain, or input-output with zero cumulative fuel — implementation/services.py:347-350, 362-365
- §3.6 — insert — ambiguity — `PASSED` pop test requires a measured lift: body value, falling back to the scheduled value, else `ERR_INVALID_REQUEST`; a supplied lift overwrites the stored one — implementation/routes/inspections.py:136-140, services.py:824-825
- §3.6 — revise — **mismatch** — envelope sentence no longer "rejected with ERR_RELIEF_NO_LIFT / ERR_RELIEF_SETPOINT_EXCEEDED" (forced-FAILED sentence following it now governs) — implementation/services.py:813-821
- §3.6 — revise — ambiguity — "latest PASSED inspection" = most recently recorded (outcome-event order) — implementation/services.py:704-726
- §3.6 — insert — ambiguity — checkpoint certificate recomputation skips `SUSPENDED` boilers outright — implementation/services.py:757-758
- §3.6 — insert — ambiguity — CONDITIONAL follow-up reuses `inspector_name`/`inspector_license_no`, born `PENDING` — implementation/services.py:857-873
- §3.6 — insert — ambiguity — posting accepts any `PASSED` inspection (not annual-only); non-PASSED → `ERR_INVALID_STATE` — implementation/routes/inspections.py:160-165
- §3.7 — insert — ambiguity — annual cost computed from the rounded, as-reported annual loss — implementation/services.py:685-687
- §3.7 — revise — **mismatch** + ambiguity — deliveries may carry optional `price_per_gal` (accepted, never serialized); price taken from latest `delivered_at` among priced deliveries (was "most recently recorded delivery"); 3.50 default when none priced — implementation/services.py:674-680, routes/fuel.py:38-48
- §3.8 — revise — ambiguity — `assigned_boiler_ids` elements must reference boilers of the same plant — implementation/routes/dispatches.py:49-53
- §3.9 — revise — ambiguity — `triggered_boiler_id` must reference a boiler of the same plant — implementation/routes/incidents.py:59-63
- §3.9 — insert — ambiguity — formal posture rule: OPEN/ACKNOWLEDGED HIGH/CRITICAL incident or any TRIPPED boiler → EMERGENCY if none ONLINE else DEGRADED; otherwise NORMAL — implementation/services.py:278-292
- §3.9 — insert — ambiguity — depth-3 replacement window inherits cancelled window's start/end/target, `assigned_boiler_ids` = full ranked eligible list, none created when no boiler eligible — implementation/services.py:504-516
- §3.9 — revise — **mismatch** — dropped "against an ONLINE boiler" qualifier; FAILED pop test suspends cert regardless of ops state — implementation/services.py:853-855, 486-516

**Deliberately left unpinned (already unique or legitimate implementation freedom):** symbolic chemistry constants (`SULFITE_MIN_PPM`, phosphate band, `CHEMISTRY_CRITICAL_COUNT`, `CRITICAL_CYCLES_FACTOR`, `CHEMISTRY_RECOVERY_COUNT`, `CONDITIONAL_FOLLOWUP_DAYS` — PRD prose implies no value-dependent behavior; services.py:6-11 confirms config freedom); 3-fractional-digit timestamps (already pinned in §2.2/§2.5; util.py:17-23); MEDIUM-from-OPEN close block (already pinned by "only when LOW" in §3.9/item 21; incidents.py:155); pop-test-PASSED-with-null-expiry lapsing (already pinned by §3.6's "any kind … null → LAPSED"; services.py:719-721).
