# Worklog — task_1267_airport_deicing_operations_glycol

Scenario: 1267. Airport Deicing Operations & Glycol Compliance (airport deicing pad operator): deicing pad assignment & queue sequencing, fluid inventory, type & holdover time calculation, glycol collection percentage & discharge permit monitoring, aircraft acceptance & post-treatment inspection, weather event staffing & fluid supply escalation, cost recovery/billing to airlines, spill reporting, glycol recycling contract. Difficulty parameter: "hard than expert level".

## Step 1: Create task directory — 2026-08-12T12:35:00.000Z

Pre-assigned directory `tasks/task_1267_airport_deicing_operations_glycol/workspace/` already exists. Step 1 treated as done per orchestrator instruction (no auto-index scan run).

## Step 2: Generate Scaffold — 2026-08-12T13:26:00.000Z

All three scaffold artifacts are written and lint-clean. Summary:

**Files written** (all verified non-empty via ls):
- `/home/ubuntu/github/CodingPRD/tasks/task_1267_airport_deicing_operations_glycol/SCAFFOLD.yaml` (76 KB)
- `/home/ubuntu/github/CodingPRD/tasks/task_1267_airport_deicing_operations_glycol/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (65 KB)
- `/home/ubuntu/github/CodingPRD/tasks/task_1267_airport_deicing_operations_glycol/SCAFFOLD_CORNER_DESIGN.yaml` (91 KB)

**Requested counts:**
- Entities: **13** (DeiceStation, DeicePad, WeatherEvent, FluidTank, Airline, DeiceRequest, DeiceOperation, Inspection, DischargePermit, EffluentReading, SpillReport, RecyclingContract, Invoice)
- State machines: **8** (cyclic: request defer/requeue loop, weather re-intensification loop, permit suspend/reinstate loop, pad occupy/release loop; plus operation rework-lineage branching)
- Endpoints: **55** (flat topology under `/deice-ops`; ~27 are lint-mandated CRUD/reverse-reachability reads, 13 creates, 21 business actions, 1 `/_clock/set_current_utc` test-driving endpoint with the pinned 2026-05-01T00:00:00Z default)
- Error catalog: **22** codes
- Difficulty-design instances: **18** (exactly 2 per each of the 9 rules; every rule's differentiation clause honored — e.g. dual-variant spans aviation-safety holdover vs billing invoice; combinatorial modes (a) multi-input holdover table vs (b) pinned per-line-rounding invoice; overlap rules use half-open adjacency on DeicePad vs aggregate rolling-window capacity on DischargePermit)
- Corner-design instances: **45** (39 active + 6 `excluded_because:` stubs), names unique across both files
- Difficulty tier: **Expert+** ("harder than expert" as requested) — compliance/audit primary archetype blended with quota/allocation, segregation-of-duties role model, 2 OCC concurrency rules (invoice-supersede on Airline.version, permit-supersede on DeiceStation.version), depth-4 and depth-3 transitive cascades, 12 calculation rules with all numeric assert literals pre-computed via Python (e.g. marginal-vs-flat invoice 45560 vs 44840 cents; per-line-rounding total 25310 vs naive 25311)

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (553 calls scanned; the single initial FK_REVERSE_UNREACHABLE for `Invoice.supersedes_invoice_id` was fixed by adding the `supersedes_invoice_id?` filter to the invoices list GET.)

One design correction made during self-review: pad occupancy now flips at spray-start rather than at assign, so the half-open window-overlap check is actually reachable (otherwise ERR_PAD_NOT_AVAILABLE would always mask it).

## Step 3: Copy shared files — 2026-08-12T13:27:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1267_airport_deicing_operations_glycol/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-12T13:45:00.000Z

The PRD is written and verified. Summary:

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1267_airport_deicing_operations_glycol/workspace/PRD.md` — 303 lines, 50,962 bytes, non-empty.

**Section list**:
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications — 2.1 RBAC, 2.2 API Response Structure (verbatim canonical block, byte-match verified), 2.3 Pagination, 2.4 Common Resource Properties, 2.5 Precision/Rounding/Monetary, 2.6 Optimistic Concurrency Control, 2.7 Derived Fluid Inventory and Station Posture, 2.8 Validation Order, 2.9 The Logical Clock, 2.10 Nested Resource Retrieval
- §3 Business Logic & Workflows — 9 subsections (station setup; weather/staffing; request intake & reservation; queue/assignment/checkpoint; spray execution & holdover; inspection & rework; environmental compliance; glycol recycling; billing)
- §4 Endpoint Definitions (4-column table)
- §5 Error Code Catalogue (2-column table)

**Coverage**:
- Entities: 13 of 13 covered (all 93 entity field names appear verbatim in backticks; `Inspection`/`EffluentReading` flagged as `common_fields: false` — `id`/`created_at` only)
- Endpoints: 55 of 55 rows in §4 table (matches scaffold exactly)
- Errors: 22 of 22 error IDs mentioned with trigger conditions in §2/§3; §5 maps all 22 to HTTP statuses
- States: all 29 state values across 8 state machines present; all 34 transitions expressed; all 67 enum values present; all 12 calculations rendered as precise prose (holdover table, tiered marginal pricing with the 25,560c vs 24,840c FLAT_TIER contrast, collection percentage, tank selector, reserved/pool aggregations, thresholds, rolling window, checkpoint)

**Hard-contract verdicts (self-check)**:
- Contract 1 (Field-Name Coverage): PASS — 101 union identifiers required, 0 missing (one miss, `required_crew_count`, found and repaired on the second pass)
- Contract 2 (Rule Coverage): PASS — 8 validation priorities expressed in explicit order; both OCC rules name write capability + `expected_*_version` + `ERR_STALE_VERSION`/412; cascades (rework 4-link, spill-confirm, void/issue/void compensation, supersede) and all `applies_to` scopes expressed
- Contract 3 (§3 Path Purity): PASS — 498 backticked tokens scanned in §3; 0 paths, 0 bare HTTP methods, 0 method+path combos
- §2.2 emitted byte-verbatim from `section-2.2-response-structure.md` (verified programmatically); the withheld difficulty/corner design files were never read

## Step 5: Generate Unit Tests — 2026-08-12T14:10:00.000Z

All files are written and verified. Here is the summary:

### test_helpers/ (9 files)
- `__init__.py` — barrel export (framework + PRD-specific)
- `types.py` — 13 entity TypedDicts + 15 status/role enums; `Inspection`/`EffluentReading` correctly omit `updated_at`/`version` (common_fields: false)
- `api_client.py` — `ApiClient(GenericApiClient)` with 38 endpoint methods covering all PRD endpoints
- `api_errors.py` — `ApiErrorId` enum (22 errors) + HTTP status map registered with the framework
- `assertions.py` — 13 `assert_*` entity validators + common-field branching
- `factories.py` — 17 payload factories, input fields only
- `constants.py` — holdover table, rate factors, tier multipliers, pad fees, crew requirements
- `test_users.py` — shared `TEST_USERS` constants + per-instance builders for `AirlineRep` (entity-backed), `Inspector`, `EnvironmentalOfficer`
- `fixtures.py` — 6 tiers of composite fixtures from single creators through `setup_invoice_issued` and `setup_recycling_contract_with_pool`

### test_suite/ (9 files)
- `conftest.py` — pytest fixture bridge
- `test_01_requests_and_queue.py` — 12 tests (defaults, defer/requeue, assign side effects, pad guards, window overlap, expiration, abort, replenish)
- `test_02_spray_and_holdover.py` — 10 tests (holdover TABLE/RATE_ADJUSTED, multi-input, floor, acceptance gate, collection pct boundary/precision, complete validation, credit gate)
- `test_03_inspections_and_rework.py` — 6 tests (immutability, uniqueness, SoD, rework cascade, lineage completion, priority)
- `test_04_permits_effluent_weather.py` — 9 tests (permit OCC, suspend/reinstate, expiry, effluent violation/window, weather cycle, staffing)
- `test_05_spills_and_recycling.py` — 7 tests (classification, deadline, SoD close, confirm cascade, quality, pool, fulfillment)
- `test_06_invoices.py` — 8 tests (OCC stale, supersede, marginal vs flat, per-line rounding, tier straddle, issue debit, issue/void invariant, operation void guard)
- `test_07_security_and_envelope.py` — 8 tests (authentication, role denial, ownership scope, envelope shape, pagination, not found, pad validation)
- `test_08_compensating_invariants.py` — 2 tests (fluid volume exact restore, void side effects)

### Counts
- **Total tests: 75**
- **Queue A (Difficulty): 18 instances, each with ≥2 tests — PASS**
- **Queue B (Corner): 39 non-stub instances, each with ≥1 test — PASS**
- **Skipped instances: 0** (6 `excluded_because` stubs in queue B were not translated, per spec; no PRD-first skips were needed)

### Self-check verdicts
- **Stage 1 (test_helpers): PASS** — all files written, imports resolve, no scaffold references
- **Stage 2 (test_suite): PASS** — all tests tagged with exactly one `Design:` line, all tags resolve to real instances, all PRD citations verbatim, no skip/xfail markers, no scaffold leakage

## Step 6: Generate Implementation — 2026-08-12T14:25:00.000Z

Implementation complete at `/home/ubuntu/github/CodingPRD/tasks/task_1267_airport_deicing_operations_glycol/workspace/implementation/`.

**File list (24 files, 2,626 LOC):**

| Path | Size / Lines |
|---|---|
| `start.sh` | 264 B (executable, guarded pip install, `exec python3 app.py`) |
| `requirements.txt` | 16 B (`flask>=3.0,<4.0`) |
| `app.py` | 2.2 KB / 77 ln (Flask factory, blueprint registration, error handlers) |
| `db.py` | 1.7 KB / 67 ln (in-memory dict tables + logical clock, default 2026-05-01T00:00:00Z) |
| `errors.py` | 4.5 KB / 121 ln (all 22 error IDs with exact HTTP statuses) |
| `response.py` | 1.7 KB / 65 ln (envelope: `meta` / `response_type` / `data`; pagination `limit`/`offset`/`total_count`/`has_more`) |
| `middleware.py` | 981 B / 39 ln (`X-User-ID` + `X-User-Role`, 6 roles, AirlineRep ownership) |
| `util.py` | 3.0 KB / 99 ln (UUID, ISO-8601 parsing, pagination, Decimal ROUND_HALF_UP) |
| `serializers.py` | 818 B / 63 ln (strips private `_created_dt`/`_started_dt`/etc.) |
| `services/calc.py` | 186 ln (holdover_time, invoice_charges MARGINAL_TIER, collection_pct, tank_selector, queue sort) |
| `services/derived.py` | 111 ln (reserved_liters, tank status, station posture, collected pool) |
| `routes/*.py` (12 modules) | stations, pads, weather_events, fluid_tanks, airlines, deice_requests, deice_operations, inspections, discharge_permits, spill_reports, recycling_contracts, invoices, clock |

**Route count:** 55 app routes registered (excluding Flask's default `/static/<path:filename>`) vs 55 scaffold endpoints — exact (method, path) match, zero missing, zero extra.

**Boot verification:**
- Server boots via `bash start.sh` on `$PORT`, binds `0.0.0.0`, foreground via `exec`, HTTP ready in <2 s.
- 401 `ERR_UNAUTHENTICATED` without headers; 404 `ERR_NOT_FOUND` for missing station; 201 station creation returns correct envelope with logical-clock timestamps.
- Restart isolation verified: killing the process and re-launching yields an empty store (recreating station code `S1` after restart returns 201, not a conflict).
- End-to-end lifecycle smoke-tested: station → tank → pad → airline → request (auto-reserved) → assign → acceptance PASS → start (TYPE_IV/100/NONE at −5 °C → holdover 120 TABLE) → complete (collection 60 % ≥ 50 % → OK) → post-treatment PASS by a different inspector (SoD enforced) → op CLEARED, request COMPLETED → invoice created (pad 60 000c + 450 L × 140c = 63 000c fluid, no storm surcharge, total 123 000c) → issued → airline balance 123 000, monthly_billed_liters 450, month_key `2026-05`.

**Self-check verdicts:**
- No seeding anywhere — store starts empty; nothing in `app.py` or module init populates entities.
- All Decimal/ROUND_HALF_UP for money and percentages; no float math for cents.
- OCC guarded exactly on the two endpoints declared in scaffold §1.2.1 (`POST /invoices` with `expected_airline_version`, `POST /discharge-permits` with `expected_station_version`) → `ERR_STALE_VERSION` 412.
- Validation priority order honored: auth → RBAC/ownership → existence → state → safety gates (permit/acceptance/SoD) → business constraints → temporal → fiscal.
- Rework lineage: rework child ops inherit request; rework start requires lineage request `IN_PROGRESS` (PRD §3.6 explicitly says rework proceeds through the same lifecycle — scaffold's strict `request.status == ASSIGNED` precondition would make rework impossible, so PRD wins per skill guidance).
- Storm surcharge uses the completion-time snapshot (`_storm_surcharge_applies` frozen at `complete`), per PRD §3.9 "evaluates the completion-time snapshot, never current conditions."
- Logical clock never falls back to wall time; spill deadline, permit expiry, rolling window, and monthly reset all consult it.

## Step 7: Run tests and iterate — 2026-08-12T15:05:00.000Z

**Result: clean 8-round parallel sweep — all 8 rounds 75/75 passed** (iteration 4). 0 tests deleted; every failure traced to a test-artifact bug or a boot-latency issue, never to a PRD-silent assertion.

**Iterations run:** 4 sweeps (75 → 61 → 74 → 75 passed per round).

**Tests deleted:** none. Every failing assertion was traced to a verbatim PRD rule (§2.4, §2.8, §3.4, §3.5, §3.9), so deletion was never triggered.

**Fixes applied to `test_suite/`:**

- Missing imports (63 of 67 round-1 failures): added `TEST_USERS` to the `from test_helpers import (...)` block in all 8 test files; added `create_deice_request_payload` (test_02), `create_station` + `setup_recycling_contract_with_pool` (test_05), `create_pad` + `create_reserved_request` (test_06), `create_fluid_tank` (test_05). Pure test-generation omission — names were exported from the barrel but never imported.
- `test_02_spray_and_holdover.py` — 3 tests (`test_collection_pct_below_minimum_flagged`, `test_collection_pct_at_exactly_minimum_passes`, `test_collection_pct_precision_two_thirds`) called `validate_success()` on the dict returned by the `complete_operation()` fixture (which already unwraps via `get_success_data`). Assert directly on the returned dict.
- `test_02` `test_holdover_table_variant_without_active_event` — asserted `holdover_minutes == 60` for TYPE_IV/100 with no active event; PRD §3.5's table gives 120 with no precipitation (60 is the SNOW column). Corrected the expected value to 120.
- `test_01` `test_queued_request_expires_after_two_ops_epochs` and `test_02` `test_complete_from_planned_returns_invalid_state` — asserted tank values of 5000 against the fixture's default 20000 L tank; made the fixture explicit via `tank_overrides` so the asserted constants match the constructed state.
- `test_06` `test_invoice_issue_debits_airline_balance` and `test_invoice_issue_then_void_restores_balance` — expected total 62000 assumes a MEDIUM pad fee (35000); the fixture default pad is LARGE (60000). Passed `pad_overrides={"max_size_class": "MEDIUM"}` so setup matches the PRD-derived expectation.
- `test_03` `test_acceptance_on_spraying_operation_invalid_state` — relaxed to `validate_error_is_one_of([ERR_INVALID_STATE, ERR_INSPECTION_EXISTS])`: PRD §2.8 places wrong-from-state and duplicate-unique-child violations at the *same* (fourth) priority level with no intra-level ordering, so the exact choice is not uniquely derivable (error-precedence relaxation is the permitted exception).
- `test_04` `test_weather_reintensification_cycle` / `test_weather_forecasted_end_cancels` — asserted `ended_at` string equality against `2026-05-01T00:00:00Z`; PRD §2.4 mandates three fractional digits (`.000Z`) for serialized timestamps while §2.9/§3.2 only pin the clock *value*. Changed to instant-equality comparison via a local `_parse_ts` helper.

**Fixes applied to `test_helpers/`:** none — fixtures/factories/assertions were consistent with PRD throughout; all bugs were in the test files themselves.

**Fixes applied to `implementation/`:**

- `start.sh` — replaced the per-boot `python3 -c "import flask"` dependency check with a one-time `.deps_ok` marker (shell-builtin test) and precompiled bytecode. Under the 8-round concurrent sweep, the extra interpreter spawn per per-test reboot occasionally pushed startup past the runner's hardcoded 15s restart-poll window, causing spurious "server could not be restarted" setup failures (4 tests in iteration 3, 0 after the fix). No application logic was touched — the implementation was PRD-faithful in every functional failure.

## Step 8: Finalize PRD — 2026-08-12T15:25:00.000Z

PRD_FINALIZED.md is written and verified. Here is the exit summary.

**Line counts:** PRD.md = 303 lines, PRD_FINALIZED.md = 303 lines (0% line-count delta; both edits are inline sentence insertions into existing paragraphs, ~+230 chars total). File verified on disk at `/home/ubuntu/github/CodingPRD/tasks/task_1267_airport_deicing_operations_glycol/workspace/PRD_FINALIZED.md`.

**Changes (2 total):**

- §2.4 — insert — pinned that every server-stamped resource timestamp (e.g. `WeatherEvent.ended_at`) uses the same ISO 8601 UTC three-fractional-digit format as `created_at`/`updated_at`, and that the clock endpoint's `current_utc` response uses it too — `implementation/util.py:15-19` (`iso_now`), `implementation/routes/weather_events.py:106,113`, `implementation/routes/clock.py:20`.
- §2.8 — insert — pinned the one intra-level ordering the implementation fixes within the fourth (state-admissibility) priority level: when an inspection recording violates both one-per-kind uniqueness and the kind's required operation state, `ERR_INSPECTION_EXISTS` surfaces first — `implementation/routes/inspections.py:33-44`.

**Step 7 diff items that required no PRD edit:** missing test imports, double-unwrapped `validate_success`, tank/pad fixture defaults (test_01/02/06) — pure test-artifact bugs; holdover 60→120 correction — PRD §3.5 already pins 120 and `implementation/services/calc.py:24` (`"NONE": 120`) matches; `start.sh` `.deps_ok` fix — boot latency, no application logic.

**Per-edit pre-edit search log:**

- **Edit 1 (§2.4):** (a) Subject: serialization format of server-generated timestamps beyond `created_at`/`updated_at`. (b) Enumerated paths: `util.py:15-19` (sole formatter, `microsecond//1000` truncation); `weather_events.py:106,113` (`ended_at` stamp), `:94` (clears to null on activate — unaffected); `clock.py:20` (`current_utc`); `response.py:17` (`api_request_timestamp`, already pinned by §2.2); all `created_at`/`updated_at` sites via grep of `iso_now` (~40 sites, all consistent); client-supplied fields echoed verbatim — `weather_events.py:42`, `discharge_permits.py:66-67,172`, `deice_requests.py:93,211-212`, `spill_reports.py:42`, `inspections.py:122-123`. (c) Wording scoped to "timestamps the server stamps onto a resource" (plus `current_utc` explicitly) so the verbatim-echo behavior of client-supplied timestamps is neither claimed nor contradicted.
- **Edit 2 (§2.8):** (a) Subject: intra-level ordering between duplicate-unique-child (`ERR_INSPECTION_EXISTS`) and wrong-from-state (`ERR_INVALID_STATE`) at the fourth priority level. (b) Enumerated paths: grep confirmed `inspection_exists` is raised only at `inspections.py:36` — the uniqueness check precedes both the ACCEPTANCE state check (`:37-39`) and the POST_TREATMENT state check (`:40-44`), with SoD after; other level-four checks (stale OCC in `invoices.py`/`discharge_permits.py`, terminal-state lockdowns) exist but involve no duplicate-unique-child error. (c) Wording explicitly states "no general intra-level ordering, with one pinned exception" scoped to inspection recording, so nothing is claimed about OCC-vs-state or other same-level combinations the implementation does not pin.

## Step 9: Complete PRD — 2026-08-12T15:55:00.000Z

PRD_COMPLETED.md is written to disk at `/home/ubuntu/github/CodingPRD/tasks/task_1267_airport_deicing_operations_glycol/workspace/PRD_COMPLETED.md` (verified: 305 lines, 58,074 bytes).

**Source vs. output**: `PRD_FINALIZED.md` (303 lines / 51,499 chars) → `PRD_COMPLETED.md` (305 lines / 58,074 chars); char-delta **+6,575** across 23 diff hunks.

**Counts**: 17 ambiguity-pins (insert), 6 mismatch-revisions (revise).

### Change ledger

- §2.2 — insert — ambiguity — unknown path or unsupported method → `ERR_NOT_FOUND` 404; unexpected failure → HTTP 500 `ERR_INTERNAL` in the same envelope — implementation/app.py:50-67
- §2.3 — insert — ambiguity — `limit`/`offset` range and integer validation → `ERR_INVALID_REQUEST`; `total_count` counts the filtered set; `has_more` formula; `created_at` ties keep insertion order — implementation/util.py:77-99, implementation/response.py:33
- §2.4 — revise — ambiguity — `version` starts at 1 at creation (was silent on initial value) — implementation/routes/stations.py:50 (all creators)
- §2.4 — insert — ambiguity — client-supplied datetimes are stored and echoed verbatim; offset-less datetimes interpreted as UTC — implementation/util.py:22-35, implementation/routes/weather_events.py:42
- §2.4 — insert — mismatch — blanket "version increments on every mutation" rule carved out: ops-checkpoint request sweep bumps no request version; tank `on_hand_liters` system adjustments (spray/spill/void) never bump tank version, and spray deduction does not even refresh `updated_at`; derived-field recomputation is not a mutation — implementation/routes/stations.py:92-96, implementation/routes/deice_operations.py:147-159, implementation/routes/spill_reports.py:104-109
- §2.8 — revise — mismatch — for path-identified resources owned by an airline (get airline/request/invoice, abort), existence is resolved first so 404 precedes the 403 ownership failure; body-supplied `airline_id` ownership still precedes existence — implementation/routes/airlines.py:52-56, implementation/routes/deice_requests.py:120-122,263-265, implementation/routes/invoices.py:80-84
- §2.8 — insert — ambiguity — pinned two cross-level orders: assign checks the request's QUEUED state before parsing the payload (ahead of pad-existence 404); spray start checks op-PLANNED → acceptance gate → request state — implementation/routes/deice_requests.py:158-165, implementation/routes/deice_operations.py:68-94
- §2.8 — revise — mismatch — "non-positive quantities" replaced with the actual sign rules (zero permitted for `credit_limit_cents`, `price_per_liter_cents`, `assigned_crew_count`, `on_hand_liters`, `collected_liters`; strictly positive required for the listed others) — implementation/routes/airlines.py:26-27, implementation/routes/weather_events.py:130-131, implementation/routes/fluid_tanks.py:46-47, implementation/routes/recycling_contracts.py:33-34
- §2.8 — insert — ambiguity — null counts as missing; empty strings fail non-empty fields; unknown payload fields ignored; duplicate unique codes (station/pad/airline) → `ERR_INVALID_REQUEST` — implementation/util.py:38-41, implementation/routes/stations.py:22-29, implementation/routes/airlines.py:28-30, implementation/routes/pads.py:29-31
- §2.9 — revise — mismatch — rolling discharge windows removed from the logical-clock list (they are anchored on readings' `measured_at`, never the clock); all server-stamped resource timestamps added to the clock list; only `api_request_timestamp` is wall-clock; clock setter accepts backward moves — implementation/routes/discharge_permits.py:157-166, implementation/util.py:15-19, implementation/response.py:14-17, implementation/routes/clock.py:12-21
- §2.10 — insert — ambiguity — inspections sub-list may be filtered by `kind` — implementation/routes/inspections.py:156-159
- §3.1 — insert — ambiguity — take-out-of-service on a non-AVAILABLE pad → `ERR_INVALID_STATE`; OUT_OF_SERVICE qualified as terminal for direct transitions (spray-start exception pinned in §3.5); pad list filters `station_id`/`status` — implementation/routes/pads.py:81-82,62-68
- §3.1 — insert — ambiguity — tank creation validation: `capacity_liters` > 0, 0 ≤ `on_hand_liters` ≤ `capacity_liters`, else `ERR_INVALID_REQUEST`; tank list filters — implementation/routes/fluid_tanks.py:42-49,87-98
- §3.1 — revise — mismatch — replenish retry walk is limited to UNRESERVED requests still in QUEUED/DEFERRED (aborted/expired ones keep UNRESERVED but are not revisited), uses the standard §3.3 selector (may pick a different tank), and stops at the first uncoverable request — implementation/routes/fluid_tanks.py:125-142
- §3.2 — insert — ambiguity — weather event list filters `station_id`/`status` — implementation/routes/weather_events.py:72-78
- §3.2 — insert — ambiguity — escalate accepted only from FORECASTED/ACTIVE (`ERR_INVALID_STATE` from ENDED/CANCELLED); crew count must be ≥ 0 — implementation/routes/weather_events.py:125-131
- §3.4 — insert — ambiguity — assignment response carries the updated request (not the created operation); operation execution fields (`oat_celsius`, `actual_liters`, `collected_liters`, `collection_pct`, `collection_flag`, `holdover_*`) are born null — implementation/routes/deice_requests.py:232,213-220
- §3.4 — insert — ambiguity — abort releases the reservation by clearing `assigned_tank_id` to null and `fluid_reservation_status` to UNRESERVED — implementation/routes/deice_requests.py:29-37
- §3.4 — insert — mismatch — checkpoint expiry releases the reservation in the derived sense only (expired request keeps `assigned_tank_id`/`fluid_reservation_status` values); the sweep refreshes request `updated_at` but never request `version`; permit expiry boundary is strictly-earlier (effective_to == now survives) — implementation/routes/stations.py:92-103
- §3.5 — revise — mismatch — spray start on a rework child requires the lineage request to be IN_PROGRESS (not ASSIGNED) and leaves the request untouched; pad is set OCCUPIED whenever not already, including the OUT_OF_SERVICE-after-assignment corner; check order pinned — implementation/routes/deice_operations.py:84-117
- §3.6 — insert — ambiguity — post-treatment PASS releases the request reservation by the same field-clearing (null `assigned_tank_id`, UNRESERVED) — implementation/routes/inspections.py:84-93
- §3.6 — insert — ambiguity — the pad is untouched by a FAIL and stays OCCUPIED through the rework lineage — implementation/routes/inspections.py:142
- §3.6 — insert — ambiguity — operation list filters: `request_id`, `station_id`, `pad_id`, `tank_id`, `parent_operation_id`, `status` — implementation/routes/deice_operations.py:39-57
- §3.7 — insert — ambiguity — spill's tank must belong to the named station (else `ERR_INVALID_REQUEST`); report born with `confirmed_by`/`closed_by` null — implementation/routes/spill_reports.py:29-30,45-46
- §3.8 — insert — ambiguity — contract born with `last_shipment_revenue_cents` null; `price_per_liter_cents` ≥ 0 and `contracted_min_liters` > 0 validation; contract list filters — implementation/routes/recycling_contracts.py:33-37,48,72-77
- §3.9 — insert — ambiguity — `supersedes_invoice_id` null when no draft was superseded; `month_key` null until the first billing touch — implementation/routes/invoices.py:59, implementation/routes/airlines.py:39
- §3.9 — revise — mismatch — voided invoice's terminal status is `VOID` (PRD never named it); `monthly_billed_liters` moves by whole-liter truncation of `actual_liters` while the fluid charge uses the exact figure — implementation/routes/invoices.py:160,132,157

Notable mismatches found and aligned: the rework-child start semantics (request IN_PROGRESS vs ASSIGNED), rolling windows not consulting the logical clock, the version-bump exemptions, invoice terminal status `VOID`, and the 404-before-403 ordering for AirlineRep path resources.
