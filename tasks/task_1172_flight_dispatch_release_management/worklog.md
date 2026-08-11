# Worklog — task_1172_flight_dispatch_release_management

## Step 1: Create task directory — 2026-08-11T09:03:00.000Z

Pre-assigned output folder `tasks/task_1172_flight_dispatch_release_management` with `workspace/` subdirectory already exists (auto-index scan skipped per pipeline instructions). Step 1 treated as done.

Difficulty parameter for Step 2 (verbatim): "generate task hard than expert level!"

## Step 2: Generate scaffold — 2026-08-11T10:24:00.000Z

Task complete. Machine-consumed summary:

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_1172_flight_dispatch_release_management/SCAFFOLD.yaml` (§1.0–§1.7; no `scaffold_difficulty_design`/`scaffold_corner_design` keys; top-level keys verified: scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles)
- `/home/ubuntu/github/CodingPRD/tasks/task_1172_flight_dispatch_release_management/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1172_flight_dispatch_release_management/SCAFFOLD_CORNER_DESIGN.yaml` (single top key `scaffold_corner_design`)

## Counts
- Entities: 15 (Station, Aircraft, Dispatcher, Captain, Desk, DeskShift, FlightLeg [self-referential via diverted_from_leg_id], FlightPlan, PayloadManifest, MelCdlItem, WeatherPackage, FlightRelease, ReleaseSignature [common_fields:false], OperationalControlRecord [common_fields:false], MonitoringEvent)
- Endpoints: 53 (flat topology under `/dispatch`; every FK has a reverse-reachability GET)
- Error codes: 41
- Calculations: 14 (incl. dual-variant trip_fuel FORECAST/WORST_CASE and dispatcher_workload flat/weighted; combinatorial modes (a) required_fuel, (b) manifest component-first rounding, (c) max_payload single-pass frozen-fuel order)
- State machines: 7 (FlightRelease cyclic signature/amendment loop; FlightLeg parallel ops_status × monitor_status; plus FlightPlan, MelCdlItem, WeatherPackage, MonitoringEvent) + 2 OCC concurrency rules (plan-create-stale-leg, weather-replace-stale-station), both 412 ERR_STALE_VERSION
- Validations: 11 priority rows (auth → role/ownership → existence → OCC → state → safety → constraint → temporal → referential → fiscal, with pinned fiscal sub-order MZFW→MTOW→MLW→CG→payload)
- §1.8 instances: 20 non-stub (2 per rule minimum; combinatorial_formula ×3, boundary_precision_check ×3), zero stubs
- §1.9 instances: 51 non-stub + 12 `excluded_because` stubs = 63 total, across sections entities/state_machines/calculations/validations/endpoints/errors/rbac/complexity_layers/consistency_model

## Verbatim lint verdict
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_1172_flight_dispatch_release_management/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_1172_flight_dispatch_release_management/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_1172_flight_dispatch_release_management/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    53
  §1.1 entities declared:     15
  §1.8 instances scanned:     20
  §1.9 instances scanned:     51
  Calls scanned (§1.8+§1.9):  741

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Notable design decisions
- Archetype: compliance/audit + multi-party negotiation; role_model segregation_of_duties enforced via license_no person-identity (ERR_DUAL_ROLE_ASSIGNMENT) and role-derived signature slots; Dispatcher/Captain entity-backed, DispatchSupervisor opaque.
- Difficulty from coupling, not padding: cycle_seq-based signature invalidation (event-sourced ReleaseSignature validity = cycle match); two depth-3 cascades with distinct triggers (delay≥60min → leg → release auto-amend → signature staleness; weather replace → plan unlock → release amend → signature staleness); pinned rounding orders and evaluation order (all assert literals computed by executing the formulas in Python — caught and fixed one arithmetic slip mid-design: recompute-cycle required_fuel is 9164, burn_eff 2756, not 9250/2782).
- Lint-driven fixes applied: sub-resource parent path placeholders renamed to literal `{id}` (signatures, control-records); ERR_NO_ACTIVE_SHIFT added to §1.6 catalog; all `expected_*_version` payloads are `${var}` captures.
- Logical clock endpoint `POST /dispatch/_clock/set_current_utc` with mandatory startup default 2026-05-01T00:00:00Z; drives MEL expiry sweep, shift-status derivation, and workload tiering.
- No sibling task directories were inspected at any point; the scaffold was generated purely from the scenario text plus the skill specification.

## Step 3: Copy shared files — 2026-08-11T10:26:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1172_flight_dispatch_release_management/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-11T10:40:00.000Z

PRD generation complete. Machine-consumed summary:

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_1172_flight_dispatch_release_management/workspace/PRD.md`
**Line count:** 334

**Section list:**
- §1. Introduction (2 paragraphs)
- §2. Global Specifications & System-Wide Principles: 2.1 User and Role-Based Access Control; 2.2 API Response Structure (verbatim block, byte-identical to `section-2.2-response-structure.md` — verified); 2.3 Pagination; 2.4 The Logical Clock; 2.5 Common Resource Properties; 2.6 Optimistic Concurrency Control; 2.7 Precision, Rounding, and Units; 2.8 Nested Resource Retrieval; 2.9 Evaluation Order of Validation Rules; 2.10 Joint Responsibility and the Two Signature Slots; 2.11 The Operational Control Audit Trail
- §3. Business Logic & Workflows: 3.1 Reference Data and Desk Staffing; 3.2 Leg Creation and Dispatcher Assignment; 3.3 Flight Planning: Wind, Fuel, and Alternate Selection; 3.4 The Payload Manifest: Weight, Balance, and Center of Gravity; 3.5 The Dispatch Release and the Joint Signature Cycle; 3.6 MEL/CDL Deferrals and the Repair Clock; 3.7 Weather Currency and Revalidation Cascades; 3.8 En-Route Operations: Delay, Departure, Monitoring, Diversion, and Closure
- §4. Endpoint Definitions (53 endpoints + header row, all rows 4 columns: Method | Path | Description | Authorized Role(s))
- §5. Error Code Catalogue (41 errors + header row, all rows 2 columns: Error ID | HTTP Status Code)

**SCAFFOLD §1.1–§1.7 coverage confirmation:**
- Entities (15): all covered; all 107 entity field names present in backticks; structured content (defaults `OPEN`/6/0/1/0/`false`, nullables, `common_fields: false` on ReleaseSignature/OperationalControlRecord stated as id+created_at only) expressed.
- State machines (7 machines, all transitions): every from→to pair named in prose, every precondition paired with its error_id, every side effect stated (including 3-hop cascades for delay_auto_amend, weather_revalidation, mel_expiry_sweep, and sibling-symmetric treatment of RELEASED→CLOSED vs other-non-terminal→CANCELLED on arrival, and RELEASED→UNDER_AMENDMENT vs PENDING_SIGNATURES→DRAFT on cascades).
- Calculations (14): all expressed as precise prose — no pseudocode operators (`==`, `>=`, `+=`, `IN {…}` absent — verified by regex scan), no fuzzy words (approximately/about/roughly/around scan clean); all 22 constants embedded in context (10,000-kg steps, 1%/step, 50-kt headwind, 100 kg / 5% / 0.5 h fuel floors, 87.5/12.5 kg pax/bag, arms 18.0/17.6/18.4/19.5/18.1, CG envelopes 20.0–31.0 / 22.0–30.0, 200 NM alternate cap, 500 kg divert margin, 200 ft / 500 m minima bump, 60-minute delay threshold, 30-minute rest buffer); boundary pins stated (ceil 50000→5/50001→6, margin 500→NONE / 0→CONSIDER_DIVERT, payload equality accepted, CG bounds inclusive, delay 60 triggers / 59 does not, component-first rounding 101-vs-100 example, workload dual-variant 2-vs-4 example).
- Validations: all 11 priority levels (0–10) stated as an explicit ordered pipeline in §2.9 with first-match-wins semantics; every `check` matchable to its `error_id` in §2/§3 prose; `applies_to` scopes enumerated in the relevant workflow narratives.
- Endpoints (53): all in §4 table; side effects all described in §3 narratives; input/query/path identifiers all backticked (76 request-body/input names, 14 path params — the latter verbatim inside backticked §4 path tokens, matching example-prd.md precedent).
- Errors (41): all mentioned in §2/§3 prose before §5 table.
- Roles (3): exact spellings; `identity:` fields translated in §2.1 (Dispatcher and Captain entity-backed with ownership-comparison prose; DispatchSupervisor opaque with `actor_id` recording note).

**Doc-generator self-check verdicts:**
- Contract 1 (Field-Name Coverage): entities 107/107, request_body/input 76/76, path_params 14/14 — 0 missing. **PASS**
- Contract 2 (Rule Coverage): validations priority 11/11 ordered in prose; concurrency_rules 2/2 (write_endpoint + `expected_leg_version`/`expected_station_version` + `ERR_STALE_VERSION`/412, no race-framing); state-machine transitions 31/31; calculations 14/14; validation conditions 11/11 matchable to error_ids; endpoint side_effects/applies_to 53/53; field structured content reconstructible; sibling-branch groups symmetric (8/8). **PASS**
- Contract 3 (§3 Path Purity): 541 backtick tokens scanned in §3; 0 starting with `/`, 0 bare HTTP methods, 0 method+path combos. **PASS**
- §2.2 verbatim: byte-identical **PASS**; §4 table 4 columns / §5 table 2 columns **PASS**; fuzzy-word and operator-leakage scans clean.

Forbidden files `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were not opened, and no other `task_*/` directory was accessed.

## Step 5: Generate unit tests — 2026-08-11T11:05:00.000Z

All checks pass. Final summary:

## Files written

**test_helpers/** (9 files, under `/home/ubuntu/github/CodingPRD/tasks/task_1172_flight_dispatch_release_management/test_helpers/`):
`__init__.py` (barrel: framework re-exports + PRD-specific), `types.py` (15 status/role enums, 15 entity TypedDicts — `ReleaseSignature`/`OperationalControlRecord` correctly omit `updated_at`/`version` per PRD §2.5), `api_client.py` (40 endpoint methods over `GenericApiClient`, all under `/dispatch`), `api_errors.py` (41 `ApiErrorId` values + HTTP map registered via `set_error_http_status_map`), `assertions.py` (per-entity assertions incl. append-only shape check, `assert_instant_equals`, `assert_desk_quota_invariants`), `factories.py` (16 payload factories, input fields only), `constants.py` (calculation thresholds + standard-chain pinned fuel figures), `test_users.py` (`TEST_USERS` + mandatory per-instance builders `make_dispatcher_headers`/`make_captain_headers` for the two entity-backed roles), `fixtures.py` (composite chains: `setup_reference_data`, `setup_computed_plan`, `setup_locked_plan`, `setup_manifest_chain`, `setup_release_draft/_pending/_released`, `setup_leg_departed`, `setup_two_variant_plans`, `setup_release_draft_with_expired_mel`; identity threading via `make_*_headers(entity_id)` throughout).

**test_suite/** (9 files, under `.../test_suite/`): `conftest.py`, `test_01_reference_data_and_envelope.py` (10), `test_02_desk_staffing.py` (8), `test_03_leg_creation.py` (10), `test_04_flight_planning.py` (10), `test_05_weather_and_plan_lock.py` (7), `test_06_manifest.py` (10), `test_07_release_cycle.py` (19), `test_08_operations.py` (14).

## Counts

- **Total tests: 88**, collected cleanly by `python3 -m pytest --collect-only` (0 errors).
- **Queue A (§1.8 Difficulty): 20/20 instances translated, 41 tests** — every instance has ≥2 tests (fuel_margin_exact_threshold_boundaries has 3). No skips.
- **Queue B (§1.9 Corner): 47/51 non-stub instances translated, 47 tests.** 12 `excluded_because:` stubs correctly not translated; all 12 `difficulty_instance` cross-references verified to resolve.
- **No orphan/dual/untagged tests**; every test docstring ends with exactly one verbatim `Design:` line resolving to a real instance.

## Queue B skips (PRD-first filter failures)

1. `Corner/validations/fuel_exceeds_capacity_rejected` — recipe triggers plan *create*; PRD names `ERR_FUEL_EXCEEDS_CAPACITY` only at plan lock and release submit (§3.3/§3.5). Coverage fails (applies_to-scope).
2. `Corner/validations/manifest_mlw_exceeded` — recipe inputs violate both MLW (63995 > 62000) and payload (19500 > 17505); asserting MLW requires an intra-fiscal reporting sub-order the PRD never pins (§2.9 item 11 groups them). Unique derivability fails (validation-priority).
3. `Corner/validations/manifest_mzfw_first_among_fiscal` — recipe inputs simultaneously violate MZFW, MTOW, MLW, and payload; "MZFW reported first" has no PRD ordering statement. Same category.
4. `Corner/endpoints/pagination_limit_bounds_rejected` — PRD §2.3 states limit bounds (1–100) but never names the out-of-range behavior; reject-with-400 vs clamp is not uniquely derivable.

## Deviations from recipe literals (PRD wins over index arithmetic)

- `leg_parallel_ops_and_monitor_dimensions`: asserted `fuel_margin_kg == -95` (PRD formula: rhu(4000−2730)−1365), not the recipe's `-96`.
- `immediate_visibility_after_create`: dropped the recipe's `version == 1` assertion (PRD pins increments, never the initial value — default-value silence); all pinned fields still asserted.
- `leg_depart_gated_on_release_and_shift`: avoided the recipe's backward clock move (20:00 → 10:30), which PRD neither permits nor forbids; the success leg uses a forward-only next-day shift instead.

## Verdicts

- pytest collection: **clean, 88/88**.
- Verbatim PRD citation sweep: **111/111 quoted spans grep-verified against PRD.md** (3 initial misses — `**bold**` lead words — fixed and re-verified).
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no scaffold/table references in generated code (comments cite only PRD sections).

## Step 6: Generate implementation — 2026-08-11T11:05:00.000Z

IMPLEMENTATION COMPLETE — task_1172_flight_dispatch_release_management

FILES WRITTEN (all under /home/ubuntu/github/CodingPRD/tasks/task_1172_flight_dispatch_release_management/workspace/implementation/):
- start.sh (339 B, executable, mode 0775)
- requirements.txt (11 B; flask>=2.0)
- app.py (1082 B; blueprint registration, ApiError/404/405/500 handlers, PORT env, 0.0.0.0)
- db.py (1151 B; in-memory dict store, logical clock default 2026-05-01T00:00:00Z, empty at boot — no seeding)
- errors.py (4341 B; ApiError + full 38-entry error catalog with scaffold HTTP statuses)
- util.py (7149 B; envelope, auth, structural body validation, datetime parse/format, pagination)
- serializers.py (5401 B; per-entity serializers, clock-derived DeskShift.status, dispatcher workload, desk occupancy)
- services.py (15836 B; all §1.3 calculations in Decimal/ROUND_HALF_UP, selectors, cascades, audit writer)
- routes_core.py (8998 B; stations, aircraft, dispatchers, captains, desks, desk-shifts)
- routes_legs.py (10916 B; leg CRUD + delay/cancel/depart/arrive/divert)
- routes_plans.py (8461 B; plans create/get/list/lock/recompute, manifests POST/GET/list/PUT)
- routes_ops.py (7570 B; mel-items, weather-packages, replace, _clock/set_current_utc)
- routes_rel.py (13822 B; releases + submit/sign/recall/amend/signatures, monitoring-events, control-records)

ROUTE COUNT: 53/53 — flask url_map dump matches SCAFFOLD.yaml §1.5 exactly (verified programmatically; orchestrator independently re-verified post-hoc: 53/53 present, sole extra route is Flask's built-in /static/<filename>).

start.sh CONTRACT: reads $PORT (default 10000), binds 0.0.0.0, foreground via `exec python3 app.py`, dependency install guarded by `python3 -c "import flask"` (no-op on per-test reboots), executable bit set.

SYNTAX/IMPORT CHECK: PASS — py_compile clean on all 11 modules; app imports and boots.

LIVE BOOT SMOKE TEST: PASS — booted via `bash start.sh` on scratch ports 18711–18743 repeatedly; each boot empty (total_count==0 verified after prior boots wrote data → per-test-server isolation safe); HTTP ready <2s; killed cleanly.

BEHAVIORAL VERIFICATION: three scenario suites (~90 assertions, ALL_PASS, zero server tracebacks): happy path leg→plan→lock→manifest→release→dual-sign→depart→monitor→divert; exact fuel math (burn 2625, trip 5250, contingency 263, alternate 583, reserve 1313, required 7408); component-first manifest rollup (pax 13125/bags 1875/cargo 1000 → 16000); OCC 412s; all error ids exercised (DUPLICATE_RESOURCE, NOT_ASSIGNED_*, STALE_VERSION, WEATHER_NOT_CURRENT/BELOW_MINIMA incl. MEL bump, WORST_CASE_REQUIRED, PLAN_IN_USE, MANIFEST/RELEASE_EXISTS, DUPLICATE_SIGNATURE, RELEASE_NOT_PENDING, LEG_NOT_IN_FLIGHT, MEL_ITEM_EXPIRED, REST_VIOLATION, SHIFT_OVERLAP, WINDOW_INVALID, DELAY_INVALID_TIME, REPAIR_WINDOW_EXCEEDED, MZFW_EXCEEDED, DISPATCHER_OVERLOADED, DESK_OVERLOADED, NO_DISPATCHER_AVAILABLE, NO_SUITABLE_ALTERNATE); cascades (mel_expiry_sweep RELEASED→UNDER_AMENDMENT cycle/amendment +1, weather_revalidation LOCKED→COMPUTED + PENDING→DRAFT, delay auto-amend at exactly ≥60 min, 59 no-op); acknowledge de-escalation gating; margin boundary 500→NONE.

NOTABLE DECISIONS (PRD-fidelity choices where prose pinned behavior):
- Cancel cascade cancels DRAFT/PENDING/UNDER_AMENDMENT but NOT RELEASED releases (PRD §3.5 "in the diversion case RELEASED as well"), overriding scaffold §1.2's looser "any non-terminal" wording.
- Validation order follows PRD §2.9 globally: structural(400) → auth → role → path existence → ownership → body FKs → OCC → state → safety (REST before SHIFT_OVERLAP; MEL_EXPIRED before NO_ACTIVE_SHIFT at depart) → uniqueness → temporal → referential → fiscal.
- created_at/updated_at use the logical clock with 3 fractional digits (PRD §2.5); caller-supplied datetimes echoed normalized (seconds when whole); ReleaseSignature/OperationalControlRecord carry only id+created_at (no version/updated_at).
- Ownership (ERR_NOT_ASSIGNED_*) enforced only where PRD/scaffold name it: leg create explicit dispatcher, delay/cancel/depart/arrive, divert (role-dependent), plan lock/recompute, release submit/recall/amend, sign, monitoring-event create + acknowledge; plan/manifest/release create accept any Dispatcher.
- Auto-amend/weather/MEL cascade audit records use actor 'system'; delay-triggered auto-amend also 'system' (AUTO_* naming).
- limit/offset validated: non-integer, limit<1, limit>100, offset<0 → 400 ERR_INVALID_REQUEST; lists sorted created_at ASC with insertion-sequence tiebreak (never id).

## Step 7: Run tests and iterate — 2026-08-11T12:56:00.000Z

All 8 rounds pass 88/88. Clean sweep — exiting. (Orchestrator disk verification: results.1–8.json each show passed=88, failed=0, errors=0, total=88.)

## Summary

**Iterations run:** 4 sweeps (8 parallel rounds each)
- Iteration 1: 19/88 per round (systematic fixture failure)
- Iteration 2: 79–81/88 (fixture cascade fixed; new failures surfaced)
- Iteration 3: 87/88 (one deterministic NameError left)
- Iteration 4: **88/88 in all 8 rounds — clean**

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1172_flight_dispatch_release_management/test_helpers/fixtures.py` — `setup_reference_data`: changed `arr_station` creation from `alternate_distance_nm=0` to `20`. PRD §2.9 rejects "a non-positive quantity" with `ERR_INVALID_REQUEST`, so the fixture was issuing a malformed request; the implementation was correct to reject it. This single fixture bug caused 66+ cascading setup failures per round.
- `/home/ubuntu/github/CodingPRD/tasks/task_1172_flight_dispatch_release_management/test_helpers/fixtures.py` — `setup_reference_data`: merged `dispatcher_overrides`/`captain_overrides` into a dict before calling the payload factories, fixing `TypeError: got multiple values for keyword argument 'name'` when tests overrode the default dispatcher/captain names.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1172_flight_dispatch_release_management/test_suite/test_02_desk_staffing.py` — added missing imports `create_station_payload` (in `test_window_invalid_rejected`) and `add_second_leg` (module-level, for `test_selector_desk_auto_assign_lowest_load`); both were NameErrors in otherwise PRD-faithful tests.
- `/home/ubuntu/github/CodingPRD/tasks/task_1172_flight_dispatch_release_management/test_suite/test_07_release_cycle.py` — added missing `setup_reference_data` import in `test_dispatcher_cannot_create_station_forbidden` (NameError).
- `/home/ubuntu/github/CodingPRD/tasks/task_1172_flight_dispatch_release_management/test_suite/test_06_manifest.py` — `test_payload_one_kg_over_max_rejected`: relaxed exact `ERR_PAYLOAD_EXCEEDS_LIMIT` to `validate_error_is_one_of([ERR_PAYLOAD_EXCEEDS_LIMIT, ERR_MZFW_EXCEEDED])`. ERROR PRECEDENCE SILENCE: `max_payload_kg` is pinned by the `mzfw_kg - oew_kg` ceiling on the standard aircraft, so crossing 19000→19001 simultaneously violates the zero-fuel-weight check; PRD §2.9 item 11 places both fiscal checks at the same "always last" priority level with no intra-level ordering, so a faithful PRD-only implementation may report either.

**Fixes applied to `implementation/`:** none — the implementation was PRD-faithful throughout; every failure traced to the test artifact layer (fixture PRD violation + missing imports + one precedence-silent assertion).

The transient "API server could not be restarted" setup errors seen in early iterations (8 concurrent rounds × per-test restarts under load) did not recur once the real failures were fixed.

## Step 8: Finalize PRD — 2026-08-11T13:05:00.000Z

PRD_FINALIZED.md is written at `/home/ubuntu/github/CodingPRD/tasks/task_1172_flight_dispatch_release_management/workspace/PRD_FINALIZED.md`.

## Summary

**Line counts / delta:** PRD.md 334 lines; PRD_FINALIZED.md 334 lines (single in-place line revision; +1 sentence, 0.0% line-count delta, one line's content changed out of 334).

**Changes (one bullet per change):**
- §2.9 item 11 — revise — appended a sentence pinning the intra-level evaluation order of the five manifest weight-and-balance checks (zero-fuel weight → takeoff weight → landing weight → center of gravity → payload-limit), explicitly scoped to manifest creation, manifest update, and release submission — `implementation/services.py:247-261` (`validate_manifest_fiscal` if-chain), callsites `implementation/routes_plans.py:166`, `implementation/routes_plans.py:215`, `implementation/routes_rel.py:122`.

**Items from `<step_7_diff>` deliberately not patched (with rationale):**
- Fixture `alternate_distance_nm=0` → 20: pure fixture bug. PRD §2.9 item 1 already determines the behavior ("a non-positive quantity" → `ERR_INVALID_REQUEST`); implementation's `pos_int` schema (`implementation/routes_core.py:22`, `implementation/util.py:122-125`) is PRD-faithful. Step 7's own classification agrees.
- Fixture `dispatcher_overrides`/`captain_overrides` dict-merge fix: test-helper artifact only; no behavioral subject exists in the PRD.
- Missing imports in `test_02_desk_staffing.py`, `test_07_release_cycle.py`: test-artifact NameErrors; nothing about implementation behavior or PRD silence.
- ERROR PRECEDENCE SILENCE: patched (the one edit above). The implementation's order is a concrete deterministic choice (fixed sequential if-chain in a single shared helper), not incidental, so per the task note it is pinned rather than left under-determined.

**Per-edit pre-edit search log (NO-NEW-MISMATCH RULE):**
1. Edit: §2.9 item 11 intra-fiscal ordering sentence.
   - (a) Subject: relative evaluation order among the five manifest weight/CG/payload checks (`ERR_MZFW_EXCEEDED`, `ERR_MTOW_EXCEEDED`, `ERR_MLW_EXCEEDED`, `ERR_CG_OUT_OF_ENVELOPE`, `ERR_PAYLOAD_EXCEEDS_LIMIT`).
   - (b) Enumerated impl paths: `implementation/services.py:247-261` (`validate_manifest_fiscal` — confirmed by grep across all `implementation/*.py` to be the only site raising these five errors; `errors.py:43-47` holds catalog entries only); all three callsites read: `implementation/routes_plans.py:154-178` (manifest create), `implementation/routes_plans.py:203-223` (manifest update), `implementation/routes_rel.py:97-133` (release submit, including surrounding MEL/qualification/plan-lock/manifest-missing/weather/fuel-capacity ordering); `implementation/services.py:27-30` (CG bound constants, consistent with §3.4); `ERR_FUEL_EXCEEDS_CAPACITY` sites (`routes_plans.py:126`, `routes_rel.py:127`) checked to confirm the edit makes no claim about them.
   - (c) Wording adjustment: initial draft considered claiming a fixed order for all of level 11; narrowed to "fixed order relative to one another" among only the five §3.4 manifest checks, with the three evaluation sites named, and no claim about `ERR_FUEL_EXCEEDS_CAPACITY` or the alternate-pool/workload/desk checks — so every enumerated path is described accurately and nothing off the Step 7 site is constrained.

## Step 9: Complete PRD — 2026-08-11T13:30:00.000Z

The diff confirms exactly the intended edits — all in-paragraph inserts/revisions, no new sections. Work is complete.

## Summary

**File stats**
- Source: `workspace/PRD_FINALIZED.md` — 334 lines, 56,220 chars
- Output: `workspace/PRD_COMPLETED.md` — 337 lines, 60,264 chars (+3 lines, +4,011 chars)

**Counts: 22 ambiguity-pins, 6 mismatch-revisions (28 changes total)**

**Ambiguity pins (insert unless noted):**
- §2.2 — insert — ambiguity — error envelope extended to framework failures: unknown path → ERR_NOT_FOUND (404), unsupported method → ERR_INVALID_REQUEST (400), unexpected failure → ERR_INTERNAL (500); lead-in widened to "4xx and 5xx"; ERR_INTERNAL row added to §5 — implementation/app.py:31-44, errors.py:55
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit` (1–100) or negative `offset` rejected with ERR_INVALID_REQUEST, not clamped; `created_at` sort ties break by insertion order — implementation/util.py:186-219
- §2.4 — insert — ambiguity — clock set accepts any ISO 8601 instant, including one earlier than the current clock — implementation/routes_ops.py:177-189
- §2.5 — insert — ambiguity — `version` starts at 1 on creation — implementation/db.py:31-36
- §2.5 — insert — ambiguity — non-system datetime fields echo caller/clock instants in UTC `Z`, three fractional digits only when sub-second precision exists — implementation/util.py:58-65, serializers.py:5-23
- §2.6 — revise — ambiguity — `expected_leg_version` rejected on any inequality with current version, not only when the version "has advanced beyond" — implementation/routes_plans.py:54-55
- §2.9 — insert — ambiguity — weather checks (ERR_WEATHER_NOT_CURRENT / ERR_WEATHER_BELOW_MINIMA) placed in the final economics level: after weight/CG checks, before fuel-capacity, on lock/submit/cascade — implementation/routes_rel.py:120-127, routes_plans.py:124-126
- §3.1 — revise — ambiguity — the ≤2h urgency tier includes legs whose `sched_dep_utc` has already passed — implementation/serializers.py:52-59
- §3.3 — insert — ambiguity — plan creation performs no dispatcher-ownership check and is not gated on leg `ops_status` — implementation/routes_plans.py:49-56
- §3.3 — insert — ambiguity — `forecast_wind_kts` is an integer (negative = headwind); non-positive ground speed → ERR_INVALID_REQUEST — implementation/routes_plans.py:22, services.py:149-150
- §3.4 — revise — ambiguity — `cargo_kg` accepts any non-negative number, not merely "one decimal" — implementation/routes_plans.py:31
- §3.4 — insert — ambiguity — manifest creation performs no dispatcher-ownership check, not gated on leg `ops_status` — implementation/routes_plans.py:154-163
- §3.4 — insert — ambiguity — manifest update: omitted fields keep current values; no ownership check — implementation/routes_plans.py:203-223
- §3.4 — insert — ambiguity — CG envelope comparison uses the exact, unrounded center of gravity — implementation/services.py:242,257-259
- §3.5 — insert — ambiguity — release creation performs no dispatcher-ownership check, not gated on leg `ops_status` — implementation/routes_rel.py:48-60
- §3.5 — insert — ambiguity — a non-completing signature leaves the release's `version`/`updated_at` untouched — implementation/routes_rel.py:170-175
- §3.6 — insert — ambiguity — clearing a non-OPEN item → ERR_INVALID_STATE — implementation/routes_ops.py:98-99
- §3.6 — insert — ambiguity — expiry sweep processes each item's affected legs in `created_at` ascending order — implementation/services.py:363
- §3.7 — insert — ambiguity — replacing a SUPERSEDED package → ERR_INVALID_STATE — implementation/routes_ops.py:151-152
- §3.8 — insert — ambiguity — delay admissible on SCHEDULED or DEPARTED legs; terminal states → ERR_INVALID_STATE — implementation/routes_legs.py:137-138
- §3.8 — insert — ambiguity — continuation leg also copies `flight_no` from the diverted leg — implementation/routes_legs.py:260
- §3.8 — insert — ambiguity — DIVERT_RECOMMENDED record carries `from_status` MONITORING / `to_status` ALERTED — implementation/routes_rel.py:281-282

**Mismatch revisions:**
- §2.9 level 1 — revise — mismatch — "a non-positive quantity" replaced with field-floor rule (impl admits 0 on non-negative fields like `pax_count`/`cargo_kg`; rejects ≤0 only on strictly-positive fields) — implementation/util.py:122-141
- §2.9 level 3 — revise — mismatch — role authorization runs before any load; ownership runs immediately after the target loads (a missing target surfaces ERR_NOT_FOUND before ownership), and before remaining body FKs — implementation/routes_legs.py:135-136, routes_rel.py:100-101 (uniform pattern)
- §2.9 level 7 + §3.2 — revise — mismatch — leg-creation check order pinned as impl runs it: captain qualification → dispatcher resolution (overload/auto-select) → dual-role against the resolved dispatcher (so overload can mask dual-role on this endpoint) — implementation/routes_legs.py:70-85
- §3.8 — revise — mismatch — leg cancellation cancels only non-RELEASED non-terminal releases; a RELEASED release survives cancellation (aligns §3.8 with §3.5 and impl) — implementation/routes_legs.py:171, services.py:338-346
- §3.8 — revise — mismatch — monitoring remaining-estimate uses the plan's stored (rounded) `burn_eff_kg_per_hour`, not "the exact effective burn" — implementation/routes_rel.py:242
- §4 — revise — mismatch — recompute row drops "weather": impl recompute re-derives from current MEL/manifest/alternate-pool state only — implementation/routes_plans.py:132-142, services.py:401-412

Notable deliberate non-changes: PRD prose already uniquely pinned all fuel/weight/CG formulas, alternate/desk/dispatcher selectors, sweep/cascade semantics, signature-cycle rules, and the endpoint table (verified route-by-route against all five route modules); unreachable defensive branches (e.g., monitoring-event-no-release ERR_INVALID_STATE, recompute alternate-pool-empty fallback) were not pinned since impl can never exhibit them.
