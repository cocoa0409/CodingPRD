# Worklog — task_2409_fountain_beverage_equipment_service_syrup

## Step 1: Create task directory — 2026-09-02T00:00:00.000Z

Created `tasks/task_2409_fountain_beverage_equipment_service_syrup/` and `tasks/task_2409_fountain_beverage_equipment_service_syrup/workspace/` (allocated name used verbatim; no index scan performed).

## Step 2: Generate Scaffold (RESUME — corner design only) — 2026-09-02T13:49:40.724Z

RESUME DECISION (orchestrator): on entry, `SCAFFOLD.yaml` (132 KB) and `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (101 KB) were already present, non-empty, and valid YAML with the correct top-level keys (`SCAFFOLD.yaml`: scenario/domain_name/api_prefix/complexity_profile/response_envelope/entities/state_machines/concurrency_rules/calculations/validations/endpoints/errors/roles; difficulty file: single key `scaffold_difficulty_design`), and both tails end mid-nothing — they are complete. Only `SCAFFOLD_CORNER_DESIGN.yaml` was missing. Since NO downstream artifact existed yet (workspace was empty — no PRD, no tests, no implementation), regenerating the two complete files would have been pure waste and would have risked losing a good §1.8 depth index, so Step 2 was run in reduced form: generate only the missing §1.9 artifact, with SCAFFOLD.yaml and SCAFFOLD_DIFFICULTY_DESIGN.yaml declared read-only to the subagent (verified untouched afterwards — mtimes still 10:55 / 11:11).

Subagent summary (verbatim):

Deliverable complete: `SCAFFOLD_CORNER_DESIGN.yaml` (single top-level key `scaffold_corner_design`, 484 KB).

## Sections and instance counts (all 9 closed-taxonomy sections, 196 instances)

| section | total | executable | `excluded_because` stubs |
|---|---|---|---|
| entities | 33 | 33 | 0 |
| state_machines | 41 | 36 | 5 |
| calculations | 52 | 44 | 8 |
| validations | 15 | 13 | 2 |
| endpoints | 7 | 7 | 0 |
| errors | 20 | 20 | 0 |
| rbac | 17 | 17 | 0 |
| cross_cutting_complexity_layers | 9 | 9 | 0 |
| consistency_model | 2 | 2 | 0 |

Every `section:`/`claim_type:` pair comes from a row of `references/claim-extraction-guide.md`; non-applicable rows (soft_delete, idempotency keys, bulk ops, scheduled actions, multi-tenancy, feature flags, DELETE endpoints) were skipped. `selector_policy` is an active complexity layer with no guide row, so the layer section covers optimistic_concurrency, cascading_side_effects, dual_variant_calculation and derived_field_reconciliation.

## Complementarity with §1.8 (18 depth instances)
- 15 §1.9 candidates that would have replayed a §1.8 trigger are `excluded_because` stubs (name + claim_type + grounds only, no recipe); every cited `difficulty_instance` was verified to exist by name in `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (script-checked: 0 dangling refs).
- Where §1.8 owns a boundary, §1.9 takes an adjacent one: §1.8 has the 13-vs-32 priority clash → §1.9 takes 13-vs-14 and 9-vs-11; §1.8 blocks serve on the same unit's OUT_OF_SPEC → §1.9 blocks on a sibling unit; §1.8 conserves van parts across the escalation loop → §1.9 covers restock and partial consumption; §1.8 reaches FROZEN via a telemetry gallon breach and releases the pool via route cancel → §1.9 enters the same 3-hop cascade via `compliance-hold PLACE` (POSTURE_FROZEN, zero overdue tasks) and via operator `SUSPEND` (which also sweeps ARRIVED stops with OUTLET_CLOSED); §1.8's variant divergence is single-run → §1.9 does the BOOK_VALUE 436800 → REPLACEMENT_RISK 501600 re-assessment that unlocks the RECALL.
- §1.8 has no OCC instance, so both `concurrency_rules` entries (agreement-create-stale-outlet, stop-create-stale-route) get stale + fresh-version pairs plus a route version 1→2→3→4 walk here.
- Name uniqueness verified across §1.8 ∪ §1.9: 0 duplicates, 0 overlaps.

## Coverage / validity
- All 53 catalog error ids are asserted by at least one executable instance (script-checked against `errors:` in SCAFFOLD.yaml).
- Forbidden concurrency vocabulary: 0 hits.
- Parses as YAML; single top-level key confirmed: `['scaffold_corner_design']`.
- SCAFFOLD.yaml and SCAFFOLD_DIFFICULTY_DESIGN.yaml untouched (mtimes 10:55 / 11:11, before this work); no other files created.

Fixes applied while validating: `breach_kind` corrected to `DATE` (enum is DATE|GALLON), 3 `compliance-hold` payloads given the required `hold_reason_code`, 2 literal `expected_route_version: "1"` replaced with captured `${rtv}`, and 4 calculations instances retagged from `conditional_validation` to the Table-3 `input_set_filtering`.

## Lint verdict (verbatim)
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2409_fountain_beverage_equipment_service_syrup/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2409_fountain_beverage_equipment_service_syrup/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2409_fountain_beverage_equipment_service_syrup/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    60
  §1.1 entities declared:     11
  §1.8 instances scanned:     18
  §1.9 instances scanned:     181
  Calls scanned (§1.8+§1.9):  1461

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Step 3: Copy Shared Files — 2026-09-02T13:49:40.724Z

Copied `INSTRUCTION.md` from project root to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T14:02:00.000Z

Orchestrator verification before accepting: `workspace/PRD.md` is 488 lines, starts at `# Fountain Beverage Service Network API — Product Requirements Document`, and ends at the final §5 error-table row (`| ERR_RECALL_EXPOSURE_BELOW_FLOOR | 422 |`) with a trailing newline — a natural document end, NOT the mid-section truncation this generator is known to produce. Accepted.

Subagent summary (verbatim):

PRD generated at `workspace/PRD.md`.

## Document shape
- **489 lines**, 26 headings: §1 Introduction (3 paragraphs), §2 with 12 subsections, §3 with 9 subsections, §4 endpoint table, §5 error table.
- §2 subsections: Roles/ACL, Response Structure, Pagination, Logical Clock, Common Resource Properties, Request Validation Order (full 36-rung priority ladder), Quantities/Precision/Unit Conversions, Stale-Version Guards, Interval Arithmetic (the two deliberately different overlap rules), Cascade Discipline, Conserved Ledgers, Segregation of Duties.
- §3 subsections follow the operational lifecycle: outlet onboarding & compliance hold → agreements → dispenser equipment & the two state dimensions → telemetry & gallon counters → maintenance/due/waivers → SKU catalogue, positions & forecasting → routes, allocation waterfall & stop execution → service calls, van dispatch & parts ledger → shortfall, exposure, recall & brand mix.

## Coverage cross-check (all scripted against SCAFFOLD.yaml)
- **Endpoints: 60 required, 60 present** in §4 (path-for-path match, 4 columns only).
- **Errors: 53 required, 53 present** in §5 (2 columns only); all 53 ids also appear in §2/§3 prose with their trigger conditions — 0 catalogue-only ids.
- **Entities: 11/11** documented, including the `TelemetryReading` exception (no `updated_at`, no `version`).
- **State machines: 8/8** (Outlet, PlacementAgreement, DispenserUnit `status`, DispenserUnit `calibration_status`, MaintenanceTask, ReplenishmentRoute, RouteStop, ServiceCall) — all 50 transitions with from/to, every precondition paired with its error id, and side effects on both branches.
- **Calculations: 13/13** in precise prose (forecast with both variants and tier factors, recall exposure with both variants, quarter-first fee rounding, severity weights, hardness derate + 72h grace, posture clauses, allocation waterfall ordering/case truncation, largest-remainder brand mix, both interval rules, both conserved ledgers, brix grading).
- **Validations: 36/36** with explicit relative priority and the exact `applies_to` endpoint sets; the extra `ERR_POOL_BELOW_RESERVED` guard is also stated.
- **Concurrency rules: 2/2** (`expected_outlet_version`/`ERR_STALE_OUTLET_VERSION` 412; `expected_route_version`/`ERR_STALE_ROUTE_VERSION` 412 on all three route endpoints), framed purely as stale-version comparisons.
- **Roles: 6/6** with exact spelling and each `identity` translated (5 opaque, `OutletManager` entity-backed to `Outlet.id`).

## Hard contracts
```
Field coverage check:
- entities[].fields: 99 required, 99 present, 0 missing
- endpoints[].input/request_body/query_params: 81 required, 81 present, 0 missing
- union (deduped): 117 required, 117 present, 0 missing
- enum constraint values + state names: all present verbatim in backticks, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 36 checked, 36 expressed in prose (ordered ladder), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + occ field + error_id + 412), 0 missing
- state_machines[].transitions: 50 checked, 50 fully expressed, 0 missing
- calculations[]: 13 checked, 13 fully expressed, 0 missing
- validations[] conditions: 36 checked, 36 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 60 checked, all expressed, 0 missing
- entities[].fields[] structured content (types/defaults/initials): 11 entities checked, reconstructible, 0 missing
- sibling-branch symmetry: 7 groups checked (FEE_ONLY/RECALL, SERVED/SKIPPED, PASS/FAIL, BOOK_VALUE/REPLACEMENT_RISK, TRAILING_ACTUAL/THROUGHPUT_PROJECTED, PLACE/RELEASE, DATE/GALLON), 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 872
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```
§2.2 was verified byte-identical to `section-2.2-response-structure.md`. No fuzzy/approximating words present. Seven §4 descriptions were rewritten to strip leaked scaffold-internal identifiers (`calculations.*`); no `state_machines.*`, `concurrency_rules.*` or §1.x scaffold references remain anywhere.

**Not truncated:** the file ends at the final row of the §5 error table (`| \`ERR_RECALL_EXPOSURE_BELOW_FLOOR\` | 422 |`) with a trailing newline — a natural document end, no audit footer.

I did not open `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml`, and did not read or list any sibling task directory.

One judgment call worth flagging: the scaffold specifies that serving a stop "recomputes each affected position's `alert_level` from its stored forecast horizon" without pinning which stored inputs feed that recomputation. I rendered it as re-running the days-of-cover test against the new `on_hand_units` using the daily rate the position's most recent forecast run measured, leaving `forecast_units`, `requested_units`, `forecast_variant` and `promo_suppressed` untouched, and noted the band can only move toward `NONE`. That is the most determinate faithful reading, but it is the one place where the scaffold itself is under-specified.

## Step 5: Generate Unit Tests — 2026-09-02T15:25:00.000Z

Launched concurrently with Step 6 in a single assistant message, so the impl-gen subagent could not see `test_suite/` (it did not exist at its spawn time).

Subagent summary (verbatim):

Stage 2 complete. Both design indices are fully translated.

## Output

**`test_suite/` — 22 files, 217 test functions** (final two files written this session):
- `test_22_role_and_identity_gates.py` — 17 tests (all `rbac` instances)
- `test_23_concurrency_cascades_and_consistency.py` — 11 tests (9 `cross_cutting_complexity_layers` + 2 `consistency_model`)

Earlier files: `test_01`–`test_08` (queue A), `test_10`–`test_21` (queue B entities, state machines, cascades, forecasts, shortfall/exposure, severity/posture, allocation, brand mix, calibration/parts/windows, validation priority, endpoints, errors).

**`test_helpers/`** (Stage 1): `__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`, plus `test_suite/conftest.py` exposing the `api` fixture and per-role header fixtures.

## Instance translation

| Queue | Instances | Translated | Skipped | Stubs (no recipe → no test) |
|---|---|---|---|---|
| A — §1.8 Difficulty | 18 | 18 (36 tests; each depth instance split into a refused/permitted or setup/consequence pair) | 0 | 0 |
| B — §1.9 Corner | 196 names, 181 non-stub | 181 (1 test each) | 0 | 15 |

Queue B per section (tests = non-stub instances): entities 33, state_machines 36 of 41 (5 stubs), calculations 44 of 52 (8 stubs), validations 13 of 15 (2 stubs), endpoints 7, errors 20, rbac 17, cross_cutting_complexity_layers 9, consistency_model 2. Nothing was skipped for PRD-filter reasons — every non-stub instance had verbatim PRD coverage that uniquely derived its asserted outcome. Cross-checked: 196 `- name:` entries, 181 `test_recipe:` blocks, 15 stubs carrying `excluded_because`.

## Verification

- `python -m py_compile test_suite/*.py` — clean.
- Tag audit (AST over all 22 files): 217 tests, 217 `Design:` lines, exactly one per test and always the final docstring line; every tag resolves to a real `name:` in `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or the correct section of `SCAFFOLD_CORNER_DESIGN.yaml`; 0 dangling, 0 untagged, 0 dual-tagged. Queue-B tags are 1:1 with instances; the 18 duplicated tags are all queue-A instances intentionally covered by a two-test pair.
- Quote gate `check_quotes.py test_suite/*.py` — "checked 304 quotes; 0 problems" (every quoted span appears verbatim in whitespace-normalised `workspace/PRD.md`).
- No occurrence of "scaffold" or §1.x references anywhere in `test_suite/` or `test_helpers/`; no unused imports and no unresolved barrel symbols in the two new files.
- `workspace/` was never written to and `workspace/implementation/` was never read.

## Step 6: Generate Implementation — 2026-09-02T15:25:00.000Z

Launched concurrently with Step 5 in a single assistant message; subagent was additionally forbidden from reading `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_suite/` and `test_helpers/`.

Subagent summary (verbatim):

The implementation is complete, verified, and the smoke server is shut down.

## Files created (all under `workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| `core.py` | 648 | store, envelope, auth, rung-1..3 helpers, `Ladder`, logical clock, decimal helpers, 11 lookups |
| `routes_routes.py` | 445 | replenishment routes, stops, allocation waterfall, arrive/serve/skip (12 endpoints) |
| `calc.py` | 439 | the 13 calculations |
| `routes_service.py` | 420 | van part stocks + service calls (12) |
| `routes_supply.py` | 340 | supply items, telemetry readings, supply positions (11) |
| `routes_agreements.py` | 280 | placement agreements incl. shortfall/recall (7) |
| `serialize.py` | 251 | ordered per-entity response projections |
| `routes_maintenance.py` | 244 | maintenance tasks (6) |
| `routes_outlets.py` | 236 | clock + outlets + brand-mix report (7) |
| `routes_units.py` | 176 | dispenser units (5) |
| `cascade.py` | 175 | posture/skip/release/return cascades |
| `app.py` | 73 | blueprint wiring, error handlers, `0.0.0.0:$PORT` foreground run |
| `start.sh` | 16 | launcher (`exec python3 app.py`) |
| `requirements.txt` | 1 | `flask>=2.2` |

Total 3744 lines. Storage is `core.Store` (11 plain dicts + logical clock + `_seq`), constructed empty at import; nothing is seeded, nothing touches disk, so each `bash start.sh` starts blank.

## Endpoint coverage: 60 / 60

I extracted the PRD §4 table into a sorted list and diffed it against Flask's `url_map` (normalising path-placeholder names, ignoring Flask's built-in `/static`): **exact match, no extras, no gaps** — 59 domain endpoints plus `POST /fountain-network/_clock/set_current_utc`.

## Validation priority ladder (PRD §2.6, 36 rungs)

Two complementary mechanisms:

1. **Rungs 1–2 in the `endpoint(roles)` decorator** (`core.py`) — auth then role check run before any handler body, under a global `LOCK`, and reset the per-request `g.touched` set.
2. **Ordered code with explicit `# rung N` markers** in every handler (131 rung comments across the route modules). Statements are physically written in ascending rung order, so reading a handler top-to-bottom *is* reading the ladder.
3. **`core.Ladder`** (`core.py:353`) for the two handlers where the rungs are numerous and interleaved with reference resolution — stop creation (`routes_routes.py:88`, rungs 3→4→5→8→9→19→21→23→30) and service-call dispatch (`routes_service.py`, 3→4→9→10→21→24→25→26). `add(rung, fn)` records `(rung, registration_order, fn)`; `run()` sorts on `(rung, registration_order)` and invokes in order, so the declared priority is data, not an accident of statement order.

## Conserved ledgers

**National pool** — invariant `supply_item.reserved_pool_units == Σ position.allocated_units`. Only three code paths move it, and each moves both sides in the same statement pair: allocation (`routes_routes.py` `allocate_stop`), serve (`serve_stop` — `allocated → on_hand`, `reserved_pool_units -= delivered`), and release (`cascade.release_stop_allocations`, the four PRD §2.10 movements, used by stop-skip, route-cancel, posture-freeze and outlet-suspend cascades). Rung 32 gates every grant on `national_allocation_units - reserved_pool_units >= case_pack_units`, and `PATCH /supply-items` refuses a pool below the reserved figure (`ERR_POOL_BELOW_RESERVED`).

**Van parts** — invariant `on_van_units + reserved_units + consumed_units == initial_units + restocked_units`. Reservation (dispatch), reversal (escalate/cancel/return-cascade) and consumption (resolve) are the only mutators; each is a paired transfer between two of the five counters, never a bare increment, so the identity holds by construction. Both invariants are asserted directly in the smoke suites.

## Smoke test results

Server launched with `PORT=18409 bash start.sh`, exercised via two urllib suites (71 assertions; 36 assertions) on fresh servers: **`FAILURES: none` for both.** Coverage included envelope shape (`meta.api_request_id` = `req_` + 20 uppercase alnum, `response_type`, `data`), missing/bad auth headers (401/403), the clock endpoint, outlet create/read/list/pagination, compliance hold → FROZEN → posture cascade, both stale-version guards (412), the allocation waterfall with `floor` to case packs, serve's deliberate non-reduction of `route.committed_units`, both ledger identities, van-window ±30-minute boundary (30 min conflicts, 31 min does not), escalation ceiling, shortfall assessment + segregation of duties + recall staging, confirm-return → task waive → agreement TERMINATED → outlet SUSPENDED cascade, and the brand-mix largest-remainder report summing to exactly 100.0. A separate probe confirmed `expected_*_version: -1` reaches the 412 guard while a non-integer still yields 400.

Server then stopped (`pkill -f "[a]pp\.py"`, confirmed down).

## Interpretive judgement calls

- **Logical clock as sole domain time source** — `created_at`/`updated_at`/`completed_at` come from the logical clock, not wall time; an internal `_seq` tiebreak sits behind the declared `created_at ASC` sort. Only `meta.api_request_timestamp` uses wall time.
- **Clock echo format** — the clock endpoint echoes the caller's instant preserving supplied precision (`iso_flex`) while server-written timestamps use fixed-millisecond `iso_ms`. All caller-supplied datetimes are stored and echoed verbatim, with a parsed copy kept privately for arithmetic.
- **`version` semantics** — "increments on every write" read as once per resource per request, enforced by the `g.touched` set, so a cascade revisiting a row does not inflate its version.
- **Suspension vs posture** — on `SUSPEND` neither overdue nor hold counter changes, so posture is not recomputed; pending and arrived stops are skipped with `OUTLET_CLOSED`, never a spurious `POSTURE_FROZEN`. Conversely the freeze cascade fires whenever a recomputation lands on FROZEN, not only on the placing of a hold.
- **Serve vs route accounting** — `serve` does not touch the route row; `route.delivered_units` is computed only at completion as the sum over SERVED stops.
- **No outlet-ACTIVE precondition on agreement or unit creation** — §4's rung list names outlet existence and the version guard but no status gate; the gate appears at `activate`.
- **`CLOSE` with zero dispensers** — "every dispenser unit must be RETURNED" treated as vacuously true.
- **`lifetime_dispensed_gallons`** — `round_half_up(total_ounces / 128, 2)` from an exact internal Decimal ounce total, so repeated ingestion never drifts.
- **Telemetry re-evaluation scope** — ingestion re-evaluates SCHEDULED FILTER_CHANGE tasks on the gallon limb alone; the calendar limb still requires an explicit `evaluate-due`.
- **`evaluate-due` idempotence** — only SCHEDULED→DUE, SCHEDULED→OVERDUE and DUE→OVERDUE are declared, so an unbreached or already-recorded status+`breach_kind` returns the task unmutated with no version bump.
- **Allocation response** — lists only positions receiving a strictly positive grant.
- **Empty `supply_position_ids`** — passes the rung-3 shape check and fails at rung 31 with `ERR_NO_ELIGIBLE_POSITIONS`.
- **Query-string enum filters** — an out-of-vocabulary value is 400 `ERR_INVALID_REQUEST`, not an empty result set.
- **`PATCH /supply-items`** — promotional interval validated post-merge, version always bumps, `ERR_POOL_BELOW_RESERVED` checked outside the ladder as a post-merge consistency rule.
- **Rounding orders** — shortfall fee rounds per quarter to whole cents before summing (the quarterly commitment itself stays exact); recall exposure rounds per unit before summing.
- **Interval arithmetic kept deliberately distinct** — stop windows half-open with zero buffer (strict `<`), van windows closed with ±30-minute buffer (non-strict `<=`).
- **`part_units` conditionality** — required whenever `part_sku` is supplied; a reservation row is written only when the count is `> 0`.
- **`reading_at_from` / `reading_at_to`** treated as inclusive bounds.
- **`window_days`** — forecast accepts any `>= 1` (no upper bound stated); telemetry listing bounded 1..90 as written.
- **One genuine PRD-literal deadlock, left as written:** hold `RELEASE` requires the outlet to be ACTIVE while `REINSTATE` requires no open hold, so a SUSPENDED outlet carrying an open hold cannot be recovered by either verb. Both preconditions implemented literally (409 `ERR_INVALID_STATE_TRANSITION`) rather than relaxing one.

## Step 7: Run Tests and Iterate — 2026-09-02T15:45:00.000Z

Clean sweep achieved: **217/217 passing in all 8 parallel rounds**.

**Iterations run:** 2

**Iteration 1** — 8/8 rounds at 213/217. Identical 4 failures in every round (fully deterministic, not flakiness), all with the same setup error:
`Setup step failed with HTTP 422: ERR_TIMESTAMP_IN_FUTURE - reading_at must be at or before the logical clock.`

- `test_01_forecast_and_fee_arithmetic.py::TestExposureVariantDivergence::test_book_value_exposure_depreciates_below_the_recall_floor`
- `...::TestExposureVariantDivergence::test_replacement_risk_exposure_escalates_over_the_recall_floor`
- `...::TestQuarterlyFeeRoundingOrder::test_fee_rounds_each_quarter_before_summing_the_cents`
- `...::TestQuarterlyFeeRoundingOrder::test_assessment_defaults_the_exposure_variant_and_echoes_its_period`

**Tests deleted:** none. All four assertions are verbatim-covered by PRD §3.9 (per-quarter round-then-sum fee, `BOOK_VALUE` 1%-per-month depreciation, `REPLACEMENT_RISK` 0.5%-per-month escalation, and the list of fields a successful assessment writes) and uniquely derivable.

**Fixes applied to `test_helpers/`:** none — the offending setup helper lived in the test file itself, not in `test_helpers/`.

**Fixes applied to test setup (`test_suite/`):**
- `test_suite/test_01_forecast_and_fee_arithmetic.py` — `_assessment_scenario()`: the shared setup pinned the logical clock to `2026-08-01T00:00:00Z` and then ingested its three quarterly telemetry readings, the last of which is at `2026-08-15T00:00:00Z`. PRD §2.6 rung 20 / §3.4 require `reading_at` to be at or before the logical clock, so the PRD-faithful implementation correctly refused the third reading with `ERR_TIMESTAMP_IN_FUTURE`. Changed the opening pin to the assessment instant `2026-10-01T00:00:00Z` (which the helper already pinned afterwards anyway), so every reading is at or before the clock. This is a STEP 2 test-setup bug — the fix makes the setup more PRD-faithful without touching any assertion.

**Fixes applied to `implementation/`:** none. The implementation's arithmetic was verified independently against PRD §3.9 before rerunning: `calc.py::assessed_quarters` (quarter enters when its own start lies in the half-open period -> Q1/Q2/Q3 for `2026-01-01`->`2026-10-01`), `calc.py::agreement_shortfall_fee` (rounds each quarter to whole cents before summing -> 49951 + 24951 + 9951 = 84853, shortfall gallons 1697.03), and `calc.py::equipment_recall_exposure` / `months_in_service` (9 whole 30-day months -> 436800 book value, 501600 replacement risk, delta 64800). All matched the tests' expected values exactly, confirming the sole defect was the setup ordering.

**Orchestrator verification:** all 8 `results.{1..8}.json` independently re-read on disk — every round `passed=217 total=217 failed=0`; `sweep.log` ends in `SWEEP_DONE` (round duration 366.0s). No reaping signature.

## Step 8: Finalize PRD — 2026-09-02T15:47:00.000Z

`workspace/PRD_FINALIZED.md` created as a byte-identical copy of PRD.md. **Zero edits** — the single Step 7 diff item revealed neither PRD silence nor PRD/impl mismatch.

### Line counts
- PRD.md: 488 lines
- PRD_FINALIZED.md: 488 lines
- Delta: 0 lines, 0.00% — identical md5 (`8821c5c0ed9b82fb29f72161826b3668`)

### Changes
None.

### Verification performed (why no edit was warranted)

The one diff item was a Step 2 test-setup ordering bug in `test_suite/test_01_forecast_and_fee_arithmetic.py::_assessment_scenario()`, with zero implementation fixes and zero test deletions. The Step 8 subagent was explicitly told not to take that at face value and to check the two things that could still hide a PRD gap.

**(a) Subject: the `reading_at` future-timestamp boundary and its error code.**

Impl paths enumerated (grepped `TIMESTAMP_IN_FUTURE` and every `now()` comparison across all 8 route modules + core/calc/cascade — exactly two callsites exist network-wide):
- `implementation/routes_supply.py:155-159` — `create_reading()`: `require(reading_at <= now(), "ERR_TIMESTAMP_IN_FUTURE", ...)`, non-strict, placed after rung 3 field validation and rung 5 `get_unit`/`get_item` existence.
- `implementation/routes_service.py:67-71` — `create_call()`: `require(reported_at <= now(), "ERR_TIMESTAMP_IN_FUTURE", ...)`, non-strict, placed after rung 5 existence, rung 6 `require_outlet_ownership`, rung 10 serviceability.
- `implementation/core.py:151-153` — `now()` returns `db.clock` only (never wall clock); `db.clock` initialised to `CLOCK_EPOCH`.
- `implementation/core.py:69` — `ERR_TIMESTAMP_IN_FUTURE` mapped to HTTP 422.

PRD already pins all four dimensions in prose a PRD-only reader finds:
- PRD.md:134 (§2.6 rung 20) names the non-strict boundary ("must be at or before the logical clock"), the code, the 422, **and** the exact two endpoints — matching the fact that only those two callsites exist.
- PRD.md:254 (§3.5) repeats it for `reading_at`; PRD.md:321 (§3.7) repeats it for `reported_at`.
- PRD.md:91 pins the logical clock as the reference and `2026-08-01T00:00:00Z` as the pre-set value, with no wall-clock fallback.
- PRD.md:465 lists the 422 status.
- The rung ladder (PRD.md:112-138) pins rung 20's position relative to rungs 3/5/6/10, matching both callsites' guard ordering.

No wording adjustment needed — nothing was under-determined. The `422` the failing setup received was the PRD-correct response to a reading at `2026-08-15` against a clock pinned to `2026-08-01`.

**(b) Subject: the assessment arithmetic the four failing tests asserted on.**

Because the setup fix unblocked assertions that had never actually executed, the subagent re-checked that those assertions are PRD-derivable rather than impl-only choices. Paths read: `calc.py:245-254` (`assessed_quarters`), `calc.py:236-242` (`_quarter_end`), `calc.py:257-288` (`agreement_shortfall_fee`), `calc.py:208-210` (`months_in_service`), `calc.py:213-230` (`equipment_recall_exposure`), plus the assessment write path in `routes_agreements.py`. Each is verbatim covered by PRD §3.9 (PRD.md:337-353): quarter-start-inside-half-open-period entry, exact unrounded quarterly commitment, per-quarter round-half-up-then-sum with the ordering explicitly declared "pinned", `assessed_shortfall_gallons` as a report-only 2-dp figure, the `IN_SERVICE`/`SERVICE_HOLD`/`RECALL_STAGED` exposure statuses, 30-day truncated months, BOOK_VALUE 1%/month with clamp-to-zero, REPLACEMENT_RISK 0.5%/month, per-unit rounding before summation, the `BOOK_VALUE` default variant, and the field list a successful assessment writes.

No edit was made, so no NO-NEW-MISMATCH re-scoping was required — but both searches were run in full before concluding.

## Step 9: Complete PRD — 2026-09-02T15:56:00.000Z

Source: `workspace/PRD_FINALIZED.md` — 488 lines, 101631 bytes
Completed: `workspace/PRD_COMPLETED.md` — 488 lines, 107854 bytes (char delta +6180; every change is in-paragraph, no new lines, paragraphs or sections)

Counts: 40 pinned behaviors across 36 changed lines — 37 ambiguity-pins, 3 mismatch-revisions.

- §2.1 Foundation — insert — ambiguity — pinned that the whole network starts empty and unseeded on every boot, with the logical clock at the `2026-08-01T00:00:00Z` epoch and no persistence across restarts — implementation/app.py:1-7, core.py:CLOCK_EPOCH
- §2.2 Response envelope — insert — ambiguity — pinned `request_id` shape as `req_` plus exactly twenty characters drawn from uppercase letters and digits — implementation/core.py:_meta
- §2.2 Response envelope — insert — ambiguity — pinned that the envelope `timestamp` is the one value read from real wall-clock time rather than the logical clock of §2.4 — implementation/core.py:_meta
- §2.2 Error envelope — insert — ambiguity — pinned that an error body carries exactly `error_id` and `message` and never a `data` or `meta` member — implementation/core.py:error_body
- §2.3 Pagination — insert — ambiguity — pinned that a non-integer `limit`/`offset` and a negative `offset` are malformed identically to an out-of-range `limit`, i.e. `ERR_INVALID_REQUEST` at 400 — implementation/core.py:pagination
- §2.3 Filtering — insert — ambiguity — pinned that an out-of-enumeration filter value is `ERR_INVALID_REQUEST`/400, an empty-string filter is treated as absent, and a filter naming an unknown identifier selects nothing rather than erroring — implementation/core.py:q_str
- §2.3 Ordering — insert — ambiguity — pinned that `created_at` ties break by creation order, earliest-created first — implementation/core.py:sort_rows
- §2.4 Clock — insert — ambiguity — pinned that submitted timestamps are echoed back exactly as supplied while comparisons use the parsed instant — implementation/core.py:iso_flex, f_dt
- §2.4 Server-written timestamps — insert — ambiguity — pinned millisecond-precision `Z`-suffixed formatting for every server-written timestamp — implementation/core.py:iso_ms
- §2.6 Ladder rung 1-2 — insert — ambiguity — pinned that a missing/blank `X-User-Id` or `X-User-Role`, and a role outside the declared enumeration, are all the same authentication failure — implementation/core.py:endpoint
- §2.6 Ladder rung 3 — insert — ambiguity — pinned JSON type strictness: integer fields reject fractional and boolean values, timestamp fields reject unparseable strings, string fields reject the empty string — implementation/core.py:f_int, f_dt, f_str
- §2.6 Ladder tie-break — insert — ambiguity — pinned that two checks registered at the same rung run in registration order — implementation/core.py:Ladder.run
- §3.1 Outlet creation — insert — ambiguity — pinned the full set of server-initialised outlet fields at registration (`ACTIVE`, `NORMAL` posture, no hold, zero counters) — implementation/routes_outlets.py:create_outlet
- §3.1 Suspension cascade — insert — ambiguity — pinned that suspension skips both `PENDING` and `ARRIVED` stops and does not itself recompute posture — implementation/cascade.py:suspend_outlet
- §3.1 Compliance hold — insert — ambiguity — pinned that a submitted `reason_code` on the status-change and hold endpoints is accepted but not stored or echoed — implementation/routes_outlets.py:change_status
- §3.2 Agreement defaults — insert — ambiguity — pinned `free_on_loan` default `true` and `shortfall_fee_cents_per_gallon` default `50` (integer cents, zero allowed) — implementation/routes_agreements.py:50-51
- §3.2 Supersession — insert — ambiguity — pinned that only sibling `DRAFT` agreements of the same outlet are superseded to `EXPIRED`, in creation order, and the outlet's version is bumped — implementation/routes_agreements.py:89-99
- §3.2 Term closure — insert — ambiguity — pinned that closure compares the logical clock to `term_end_date` inclusively (`now >= term_end`) — implementation/routes_agreements.py:274
- §3.3 Unit placement — insert — ambiguity — pinned resolution order (outlet before agreement) and the initial `calibration_status`/counter state of a newly placed unit — implementation/routes_units.py:create_unit
- §3.3 Calibration movement — insert — ambiguity — pinned that calibration status moves only on maintenance-task completion and never on telemetry ingestion — implementation/routes_maintenance.py:complete_task, calc.py:brix
- §3.4 Telemetry ingestion — insert — ambiguity — pinned that a reading is immutable once written: it carries `created_at` only, with no `updated_at` and no `version` — implementation/serialize.py:READING_FIELDS
- §3.5 Due evaluation — insert — ambiguity — pinned that evaluation is idempotent — when neither status nor breach flag changes the row is left entirely untouched, version included — implementation/routes_maintenance.py:evaluate_due
- §3.5 Due evaluation order — insert — ambiguity — pinned that the gallon threshold is tested before the calendar deadline and that the 72-hour grace applies only to the calendar branch — implementation/calc.py:maintenance_due_evaluation
- §3.6 Supply item pool — insert — ambiguity — pinned that a `PATCH` re-checks the merged window as an interval first and only then guards the national pool against outstanding reservations — implementation/routes_supply.py:patch_item
- §3.6 Position registration — insert — ambiguity — pinned the initial position state (zero allocated, null planned stop, `NONE` band, no forecast) — implementation/routes_supply.py:create_position
- §3.6 Forecast step 3 — insert — ambiguity — pinned that the net requirement divides by case pack with floor semantics and that the forecast persists the derived daily-ounce rate for later reuse — implementation/calc.py:outlet_supply_forecast
- §3.6 Promotional suppression — insert — ambiguity — pinned the half-open promotional window test (`start <= clock < end`) and that both bounds must be present for suppression to apply — implementation/calc.py:outlet_supply_forecast
- §3.6 Alert band — insert — ambiguity — pinned that a zero on-hand position is `CRITICAL` regardless of the daily rate, including a zero rate — implementation/calc.py:alert_band
- §3.6 Acknowledge alert — insert — ambiguity — pinned that acknowledgement has no state gate: any band, `NONE` included, can be acknowledged — implementation/routes_supply.py:acknowledge_alert
- §3.6 Reading `window_days` — revise — mismatch — removed the claim that `window_days` shapes interpretation of a reading; no calculation consumes it — implementation/calc.py:trailing_daily_ounces
- §3.7 Stop creation — insert — ambiguity — pinned the stop ladder order (shape, route, outlet, route version, route status, region, interval, overlap, sequence uniqueness) and that a new stop bumps the route's version — implementation/routes_routes.py:144-163
- §3.7 `service_date` — revise — mismatch — softened "midnight instant" to a convention, since any parseable instant is accepted and stored as submitted — implementation/routes_routes.py:52
- §3.7 Server-initiated skips — revise — mismatch — corrected `PENDING`-only to: `PENDING` alone for `POSTURE_FROZEN`, both `PENDING` and `ARRIVED` for `OUTLET_CLOSED` and `ACCESS_DENIED` — implementation/cascade.py:suspend_outlet, routes_routes.py:251-258
- §3.7 Allocation — insert — ambiguity — pinned that allocation has no route- or stop-status gate, and pinned the response shape (`route_stop_id`, `allocated_position_count`, `total_allocated_units`, `granted_units_by_position`) — implementation/routes_routes.py:289-353
- §3.7 Allocation grant — insert — ambiguity — pinned that pool and capacity are re-read per position inside the loop and that a zero grant leaves the position wholly untouched — implementation/routes_routes.py:318-344
- §3.7 Serve — insert — ambiguity — pinned that serving processes positions in creation order, releases the reservation floored at zero, re-derives the alert band, and deliberately leaves `committed_units` unreduced — implementation/routes_routes.py:407-426
- §3.7 Route completion — insert — ambiguity — pinned that completion takes no body and no expected-version field, and that `delivered_units` sums `SERVED` stops only — implementation/routes_routes.py:204-221
- §3.8 Dispatch parts — insert — ambiguity — pinned that `part_sku` without `part_units` is `ERR_INVALID_REQUEST`, that a reservation is taken only when units exceed zero, and that the first matching van stock row is used — implementation/routes_service.py:141, 180-194, 219-226
- §3.8 Resolution — insert — ambiguity — pinned `consumed_part_units` default of 0 and the exact three-way ledger move (reserved released, consumed added, unconsumed returned to the van) — implementation/routes_service.py:259, 281-291
- §3.9 Recall decision — insert — ambiguity — pinned the check order (state, segregation of duties, free-on-loan, exposure floor) with the last two evaluated only for a `RECALL` outcome, and that staging reaches `IN_SERVICE` and `SERVICE_HOLD` units in creation order — implementation/routes_agreements.py:214-254
- §3.9 Brand-mix report — insert — ambiguity — pinned that lines are emitted only for items with positive total ounces, ordered by item creation, with `top_brand_name` resolved by the first line on ties — implementation/calc.py:brand_mix_report

Deliberately not pinned (would require inventing behavior or documenting unreachable code): duplicate ids inside `supply_position_ids`; negative `months_in_service` for a future `installed_at`; the unreachable `escalation_count <= 2` guard inside dispatch state legality; a zero stored daily rate at serve time; waiving a task on a `RETURNED` unit; JSON key ordering.

**Orchestrator verification:** PRD_COMPLETED.md is 488 lines / 107854 bytes, heading count identical to the source, and ends on the complete error-catalogue table (not truncated). `find` over `implementation/`, `test_suite/` and `test_helpers/` confirms no `.py` file was modified after the 15:44 clean sweep, so the 217/217 × 8-round result still describes the artifacts on disk.

## Pipeline complete — 2026-09-02T15:57:00.000Z

All nine steps satisfied. Final state: 217 tests, 8/8 rounds passing under `--isolation per-test-server`; PRD.md -> PRD_FINALIZED.md (byte-identical) -> PRD_COMPLETED.md (40 behaviors pinned).
