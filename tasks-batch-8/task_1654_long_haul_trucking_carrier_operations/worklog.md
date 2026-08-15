# Worklog — task_1654_long_haul_trucking_carrier_operations

## Step 1: Create Task Directory — 2026-08-14T05:04:00.000Z

Directory tasks/task_1654_long_haul_trucking_carrier_operations/ with workspace/ subdirectory was pre-created and pre-assigned by the pipeline launcher. Treated as DONE per launcher instructions; no index scan performed.

## Step 2: Generate Scaffold — 2026-08-14T06:11:57.413Z

Scaffold generation complete for task_1654_long_haul_trucking_carrier_operations. All three artifacts written and lint-clean.

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_1654_long_haul_trucking_carrier_operations/SCAFFOLD.yaml` — §1.0–§1.7 (no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1654_long_haul_trucking_carrier_operations/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1654_long_haul_trucking_carrier_operations/SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`

## Counts
- **Entities: 14** (Driver, Tractor, CustomerAccount, Lane, StateFuelRate, Load, Trip, DutyEvent, CheckCall, AccessorialCharge, FuelPurchase, SafetyEvent, Settlement, Invoice) — flat topology, all FKs reverse-reachable
- **State machines: 8** — incl. Driver parallel dims (employment × duty), AccessorialCharge resubmit cycle, Settlement rework cycle, Load INVOICED→DELIVERED revert, guarded transitions throughout
- **Calculations: 13** — dual-variant lane margin and driver pay, HOS projection/feasibility (4-clause gate), detention billing (anchor-max + free-minutes + ceil increments), fuel-plan and backhaul selectors with pinned tie-breaks, safety decay scoring, settlement with pinned per-charge rounding and pinned top-up evaluation order
- **Endpoints: 80** (incl. `POST /_clock/set_current_utc` with the mandated 2026-08-01T00:00:00Z startup default)
- **Error catalog: 60 codes** — every code exercised by at least one §1.8/§1.9 instance (verified programmatically)
- **Concurrency rules: 3** (OCC on Driver/Trip/Settlement versions, all 412 ERR_STALE_VERSION)
- **§1.8 instances: 20** across all 9 rules (dual_variant 2, combinatorial 3 covering modes a/b/c, non_linear_sm 2, cascade 2 (depth-4 check-call cascade + depth-3 suspension cascade), priority_conflict 2 (state-vs-safety, safety-vs-temporal), boundary 3 (detention minutes / safety score / guarantee cents), cross_entity 2, overlap 2 (half-open trip windows vs closed fuel-rate windows), invariant 2 (money conservation vs score restoration)). All formula-derived asserts are precomputed literals (e.g., margin 63769 vs 59419, pay 63240→65100, detention 7500, settlement share 1506 vs 1507)
- **§1.9 instances: 74 active + 5 excluded_because stubs** across all 9 guide sections (entities 9, state_machines 17, calculations 11, validations 11, endpoints 5, errors 11, rbac 5, cross-cutting 4, consistency 1)

## Lint result (verbatim)
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
  §1.5 endpoints declared:    80
  §1.1 entities declared:     14
  §1.8 instances scanned:     20
  §1.9 instances scanned:     74
  Calls scanned (§1.8+§1.9):  989
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Additional audits passed: unique instance names across both design files, all `grounds` resolve, enum-value closure (fixed REASSIGN), no forbidden concurrency vocabulary, clock discipline enforced in every event-bearing chain (occurred_at ≤ logical now). No sibling task directories were inspected.

## Step 3: Copy Shared Files — 2026-08-14T06:12:30.000Z

Copied ./INSTRUCTION.md to tasks/task_1654_long_haul_trucking_carrier_operations/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-08-14T06:37:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1654_long_haul_trucking_carrier_operations/workspace/PRD.md` (409 lines). The withheld design files were never opened.

## PRD Section List

- **§1. Introduction** (2 paragraphs — business-context angle: asset-based carrier margin discipline)
- **§2. Global Specifications & System-Wide Principles**
  - 2.1 User and Role-Based Access Control (6 roles + identity translation: Driver entity-backed, five opaque)
  - 2.2 API Response Structure (verbatim block — verified byte-identical to `section-2.2-response-structure.md`)
  - 2.3 Pagination and List Ordering (limit 10/1/100, offset 0, `created_at` ASC, duty-events `occurred_at` ASC exception, all filter params)
  - 2.4 The Logical Clock (startup default 2026-08-01T00:00:00Z, no wall-clock fallback, `to_iso8601`/`current_utc`)
  - 2.5 Common Resource Properties (UUID `id`, `created_at`/`updated_at` 3-fractional-digit, `version` starts at 1; DutyEvent/CheckCall carry only `id`+`created_at`)
  - 2.6 Money, Mileage, and Precision (integer cents, round half up only where named, whole minutes, 6.5 MPG exact-rational)
  - 2.7 Cascading Mutations and Derived-Field Reconciliation
  - 2.8 Optimistic Concurrency Control (all three OCC rules with `expected_driver_version`/`expected_trip_version`/`expected_settlement_version` → `ERR_STALE_VERSION` 412)
  - 2.9 Request Validation Pipeline (all 12 priorities in explicit order, with sub-orders for priorities 8 and 12)
  - 2.10 Resource Identifier Resolution (left-to-right 404, all 11 NOT_FOUND IDs)
- **§3. Business Logic & Workflows** (9 subsections, process-timeline grouping): 3.1 Master Data · 3.2 Load Commercial Lifecycle · 3.3 Trip Assignment/Dispatch/Backhaul · 3.4 HOS Accounting & Feasibility · 3.5 Check Calls/Completion/ETA/Detention · 3.6 Accessorial Adjudication & Invoicing · 3.7 Fuel Purchasing & Stop Planning · 3.8 Safety Scoring & Employment Actions · 3.9 Payroll Settlement
- **§4. Endpoint Definitions** (4-column table, all 80 endpoints)
- **§5. Error Code Catalogue** (2-column table, all 60 errors)

## Coverage Audit

```
Field coverage check (Contract 1):
- entities[].fields + endpoints[].input + query params: 89 required, 89 present, 0 missing
Status: PASS

Rule coverage check (Contract 2):
- validations[] with priority: 12 checked, 12 expressed as an ordered pipeline with sub-orders, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (endpoint capability + occ field + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: 8 machines, all transitions expressed with preconditions + error ids + side effects (incl. cancel-tier siblings, resubmit loop, INVOICED→DELIVERED revert), 0 missing
- calculations[]: 13 checked, 13 fully expressed in precise prose (no operator syntax, no fuzzy words), 0 missing
- validations[] conditions: all matchable to error_ids in §2/§3 prose (verified: all 60 error ids appear in prose, not only §5), 0 missing
- endpoints[].side_effects / applies_to: expressed (completion cascade, suspension cascade, invoice issue/void flips, clock semantics, duty-event AUTO_HOS), 0 missing
- entities[].fields[] structured content: defaults/initials/constraints reconstructible (version=1, safety_score=100, PENDING/DRAFT/PLANNED/AVAILABLE/ACTIVE/TENDERED initials, at_home=false, voided=false, reason=REASSIGN, null-until fields), 0 missing
- sibling-branch symmetry: cancel tiers (5 states), reject (2 states), MILEAGE/PERCENTAGE variants, provisional/final variants, pickup/delivery detention legs, suspend/terminate cascades — all rendered with equal density, 0 asymmetric
Status: PASS

Path purity check (Contract 3, §3 only):
- backtick tokens scanned: 630
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks passed: all 31 state values and every enum member (`MILEAGE`/`PERCENTAGE`, duty/check-call/accessorial/safety kinds, `US-NATIONAL`, `AUTO_DETENTION`/`MANUAL`/`AUTO_HOS`, etc.) appear verbatim; all 6 role names exact; all 80 endpoint paths in §4; §2.2 byte-identical to the canonical block.

## Zero-Silence Rule Decisions

1. **`floor_pass` (margin read)** — scaffold names the boolean but not its semantics; defined in §3.2 as the load's current standing against the acceptance floor (non-negative projected margin AND projected RPM ≥ lane floor), derived directly from the accept gate.
2. **Driver-list `status` filter** — scaffold lists the param but Driver's field is `employment_status`; §2.3 states filters match "the corresponding attribute" without renaming the field.
3. **`cdl_number` / `unit_number` uniqueness** — stated as constraints in §3.1 with no invented rejection error, since the scaffold catalog has none for them.
4. **Trip-cancel `reason` payload** — scaffold says input accepts REASSIGN/CUSTOMER (default REASSIGN) and SAFETY is system-set only; PRD maps other values to `ERR_INVALID_REQUEST` via the priority-4 enum-membership rule rather than inventing a new error.
5. **`severity_points` optionality** — described as optional-when-supplied within 1..100; no default value invented.
6. **Pay-config completeness on driver update** — `ERR_PAY_CONFIG_INCOMPLETE` applies_to lists driver creation only, so §3.1 states the rule at registration and leaves the OCC-guarded update governed by field presence alone; no extra gate invented.
7. **Trip-create driver-active gate** — deliberately NOT added: the scaffold gates driver `ACTIVE` at dispatch/duty-event only, so creation checks load/tractor state plus safety/HOS/home-time/overlap exactly as specified.

## Step 6: Generate Implementation — 2026-08-14T07:15:00.000Z

Implementation complete and verified. Summary below.

## Files created (all under `/home/ubuntu/github/CodingPRD/tasks/task_1654_long_haul_trucking_carrier_operations/workspace/implementation/`)

| File | Purpose |
|---|---|
| `start.sh` | Executable launcher: guarded `pip install` (no-op when Flask present), `exec python3 app.py`, foreground |
| `requirements.txt` | `flask>=3.0,<4.0` |
| `app.py` | Flask app factory, ApiError/404/405/500 envelope handlers, blueprint registration, `0.0.0.0:$PORT` (default 10000), `threaded=True` |
| `store.py` | In-memory dicts for all 14 entity types; logical clock initialized to the PRD-mandated `2026-08-01T00:00:00Z` (only system-initial state; zero entities seeded); `touch()` for `updated_at`/`version` bumps |
| `common.py` | Envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields in `meta` for lists), auth (`X-User-ID`/`X-User-Role`, six roles), body/field validators, ISO-8601 3-fractional-digit timestamps, `limit`/`offset` pagination (default 10, 1..100) |
| `services.py` | All calculations + cascades (below) |
| `routes_fleet.py` | Clock, drivers, duty events, safety events, tractors, customers, lanes, fuel rates |
| `routes_ops.py` | Loads, trips, check calls, fuel purchases, accessorials, invoices, backhaul board |
| `routes_money.py` | Settlement lifecycle |

## Endpoint count
**80 endpoints implemented** — every row of the scaffold §1.5 table (1 clock + 16 driver/safety + 6 tractor + 6 customer + 3 lane + 3 fuel-rate + 13 load + 14 trip + 5 accessorial + 8 settlement + 4 invoice + 1 dispatch).

## Calculation / state-machine coverage
- **Calculations**: `lane_margin_screen` (provisional + final variants), `fuel_surcharge_calc` (exact rational ×2/13, round-half-up via `Fraction`), `driver_trip_pay` (both variants), `hos_clock_projection` (long-off 600 / restart 2040 / break 480 runs over half-open intervals, exact `Fraction` minutes), `hos_feasibility_check` (all 4 clauses) + 14-day home-time (exactly 14 passes), `detention_billing` (120 free minutes, 15-min×1500 increments, missing-anchor legs skipped), `fuel_purchase_costing`, `fuel_plan_selection` (price ASC → tax DESC → route order), `driver_safety_score` (8760/17520-hour decay, per-sum round-half-up, floor 0, gate ≥60), `eta_projection` (break/rest block floors, late strictly `>`), `backhaul_ranking` (rpm DESC → pickup ASC → created_at ASC, HOS filter when `driver_id` given), `cancellation_fee_tiers` (0 / 15000 / max(25000, 10%)), `settlement_gross_pay` (per-charge rounding then sum, half-open period, guarantee top-up with termination/eligibility rules).
- **State machines**: Load (11 states incl. INVOICED→DELIVERED revert), Trip (7 states, check-call rank ladder with EN_ROUTE interleave), Driver employment (suspend/terminate SAFETY cascades), Tractor, CustomerAccount, AccessorialCharge (DISPUTED→SUBMITTED resubmit loop), Settlement (DRAFT rework loop, SoD `ERR_SEGREGATION_OF_DUTY`), Invoice (issue/void/mark-paid compensating cascades).
- **Validation pipeline** follows §2.9 order: auth headers (400) → role (403) → path existence left-to-right (404) → body shape (400) → driver identity (403) → state (409) → OCC `expected_driver/trip/settlement_version` (412) → safety floor → HOS → home-time (422) → temporal overlap (422, half-open adjacency allowed; fuel-rate windows closed-interval, touching conflicts) → constraints (422, incl. state-on-route → tank → rate-unavailable sub-order) → invoice open-accessorial gate (422) → fiscal gates (402 credit-hold then margin-floor).
- **Cascades** bump `version`/`updated_at` on every touched resource; DutyEvent/CheckCall carry only `id`+`created_at`.

## Boot smoke results
- 3× fresh-boot determinism: empty store (`GET /drivers` → `{"data":[],"total_count":0}`) and clock default `2026-08-01T00:00:00.000Z` each time; no persistence anywhere.
- Two end-to-end suites (337 assertions total) passed on fresh `start.sh` boots: suite 1 (160 checks) — full tender→screen→accept→assign→dispatch→check-calls→detention→invoice→settlement flow with exact expected figures (FSC 15385, margin 87685, detention 9000/3000, final margin 99835, settlement 66600+3000+50400=120000, SoD 403, void/re-issue/mark-paid cycle); suite 2 (177 checks) — HOS clock projections with exact minute values at 7 timestamps, 34h restart, ETA numbers, fuel-plan ranking/tiebreaks/infeasible, tank-capacity/state-on-route/driver-mismatch 422/403s, period-boundary exclusion at `period_end`, TONU fee, cancel-tier table, OCC 412s, pagination meta and 400 range checks, backhaul ordering + HOS driver filter, 404 error IDs.
- One implementation bug found and fixed during testing (missing `opt_dt` import causing PATCH /trips 500; stale `request_args` helper causing GET /drivers 500); all other failures observed were smoke-script clock-sequencing mistakes, which confirmed the pipeline ordering (e.g., future-`occurred_at` 400 correctly precedes 409/403 state/identity errors).

## Step 5: Generate Unit Tests — 2026-08-14T07:25:00.000Z

**Task**: task_1654_long_haul_trucking_carrier_operations — generated `test_helpers/` (9 modules) and `test_suite/` (conftest + 14 test files, 113 tests).

### Test files
| File | Tests | Content |
|---|---|---|
| `test_01_fleet_master_data.py` | 9 | Driver/tractor registration defaults, pay-config completeness, 404, OOS guard cycle |
| `test_02_response_envelopes_and_not_found.py` | 3 | Success/error envelope shape, 10-family 404 sweep |
| `test_03_listing_and_filters.py` | 4 | Pagination envelope + created_at ASC (clock-stepped for tie-safety), status filter, reverse-FK lists, empty backhaul board |
| `test_04_load_commercial_pipeline.py` | 13 | Tender defaults, screen guards, FSC floor, margin floor (402), credit-hold gate (incl. Queue A pair), cancel tiers, immediate visibility |
| `test_05_trip_assignment_gates.py` | 10 | Load-state gate, safety floor 60/59 boundary, state-beats-safety priority, HOS multi-clause gate, home-time 14-day boundary, tractor single-assignment |
| `test_06_temporal_windows.py` | 9 | Half-open trip-window adjacency, safety-beats-overlap priority, closed fuel-rate window touch, settlement period overlap, duty-event monotonicity, default clock |
| `test_07_trip_execution_and_completion.py` | 11 | Redispatch/cancel guards, check-call rank, appointment anchoring, ETA arithmetic, DELIVERED 4-hop cascade, PERCENTAGE pay variants, detention 120-min boundary |
| `test_08_driver_employment_and_safety.py` | 13 | Parallel employment×duty axes, suspension cascade, void-restores-score, terminate lockdown, decay weights, AUTO_HOS violation, version increment rules |
| `test_09_accessorial_adjudication.py` | 5 | Dispute-resubmit cycle, LUMPER passthrough stability, terminal REJECTED, per-action state guards, duplicate-leg rule |
| `test_10_fuel_and_backhaul.py` | 7 | Off-route purchase, tank-capacity boundary + costing, PLANNED-trip fuel guard, fuel-plan tax tie-break, empty-route infeasibility, backhaul rpm ranking + pickup tie-break |
| `test_11_invoicing_and_margin.py` | 7 | Issue/mark-paid lifecycle, open-accessorial gate, invoice state guards, void compensation, reissue total conservation, provisional-vs-final margin |
| `test_12_payroll_settlements.py` | 12 | Rework cycle, DRAFT-only guards, SoD, full lifecycle to PAID, half-open period scope, per-charge share rounding (1506 vs 1507), top-up evaluation order, exact-minimum boundary |
| `test_13_optimistic_concurrency.py` | 4 | Driver/trip/settlement OCC stale-version rejections, existence-before-body-format |
| `test_14_rbac_and_driver_identity.py` | 6 | Missing headers, Driver foreign-trip mismatch, three role-exclusive denials, shared reads |

### Coverage
- **§1.8 Queue A**: 20/20 instances translated, each with exactly 2 tests (40 tests). No skips — notably, the two `priority_pair_validation_conflict` instances were retained because PRD §2.9 explicitly pins the pipeline order ("a failure at any stage short-circuits the stages after it"), satisfying both coverage and unique derivability.
- **§1.9 Queue B**: 73/74 non-stub instances translated (1 test each). All 5 `excluded_because:` stubs verified to resolve to real difficulty instances and not translated.
  - **Skipped (1)**: `Corner/calculations/hos_restart_34h_boundary` — driver A's `cycle_70h == 4200` headline assertion hinges on whether an *in-progress* ≥34h off run resets the cycle at qualification or at run end; PRD §3.4 ("resets the cycle accumulator at the moment the run ends" vs "a run of exactly 34 hours qualifies") admits both readings (2220 vs 4200), failing unique derivability. Gap logged, no placeholder emitted.

### Self-audit results
- **Tag integrity**: all 113 tests carry exactly one `Design:` tag as the final docstring line; every tag resolves to a real instance in the source YAML (verified programmatically).
- **Citation audit**: every test cites PRD prose; 164 citation segments verified to contain a verbatim ≥8-word run in `workspace/PRD.md` (one tool artifact — nested quotes in the `"All roles" means ...` citation — confirmed verbatim by direct grep).
- **Helper inventory**: `types.py` (18 enums + 15 TypedDicts, append-only DutyEvent/CheckCall omit updated_at/version), `api_client.py` (84 methods covering every §4 endpoint), `api_errors.py` (60 error IDs + HTTP map registered with the framework), `assertions.py` (14 entity assertions incl. append-only field-absence and settlement/invoice component arithmetic), `factories.py` (13 payload factories), `constants.py` (all §3 thresholds), `test_users.py` (shared constants + per-instance builders; Driver is entity-backed and threaded via `make_driver_headers(driver["id"])`), `fixtures.py` (5 tiers: clock/CRUD helpers, refdata preamble, planned→dispatched→delivered trip chains, adjudication/invoice/settlement composites, two-lumper and exact-minimum scenario builders).
- **No** `pytest.mark.skip`/`skipif`/`xfail`, no scaffold references in comments, all modules compile and import cleanly.

One design-index bug worked around: `driver_trip_window_half_open_adjacency`'s recipe sets `last_home_at` 2026-07-20 with delivery 08-05, which under PRD §3.4 fails home-time (16 days > 14) before the overlap check could ever fire; the translation uses 2026-07-28 so the asserted half-open adjacency outcome is reachable, keeping the instance's assertion intact.

## Step 7: Run Tests and Iterate — 2026-08-14T07:45:00.000Z

**Summary**

- **Iterations run:** 2 (initial 8-round sweep → fixes → confirming 8-round sweep). Final sweep: all 8 rounds 113/113 passed, zero failures, zero errors, zero flakiness.

- **Tests deleted:** none. Every failing assertion traced to a verbatim PRD sentence with unique derivability; all 5 failures were test-layer bugs.

- **Fixes applied to `test_helpers/`:**
  - `test_helpers/fixtures.py` — `setup_accepted_load`: merged `load_overrides` with the positional `rate_cents` default via `setdefault` instead of passing both, eliminating `TypeError: tender_load() got multiple values for keyword argument 'rate_cents'` that broke the two `test_12` settlement rounding/top-up tests at fixture-construction time.

- **Fixes applied to `test_suite/`:**
  - `test_06_temporal_windows.py::test_duty_event_strictly_increasing_enforced` — logical clock moved from `2026-08-01T06:00:00Z` to `07:00:00Z`; the third setup event (06:01) was after logical now, so PRD §3.4's future-timestamp `ERR_INVALID_REQUEST` fired inside a `get_success_data` setup step before the strictly-increasing rule under test could be exercised.
  - `test_07_trip_execution_and_completion.py::_boundary_chain` — `delivered_at`/`clock_to` corrected from `20:01` to `21:01`; the scaffold design and the test's own assertion require 181 elapsed minutes → 61 billable → ceil(61/15)·1500 = 7500, but 18:00→20:01 is only 121 elapsed (1 billable). Data now matches the asserted PRD §3.5 arithmetic; the sibling `exactly_120` test is unaffected (still exactly one charge, no pickup charge).
  - `test_10_fuel_and_backhaul.py::test_fuel_purchase_tank_capacity_boundary` — second purchase's `purchased_at` changed from `12:01` to `12:00` (the logical now); the future timestamp made pipeline stage-4 `ERR_INVALID_REQUEST` pre-empt the stage-10 `ERR_TANK_CAPACITY_EXCEEDED` under test (PRD §2.9 ordering).

- **Fixes applied to `implementation/`:** none. The implementation was PRD-faithful on every probed rule (pipeline ordering, HOS projection, detention billing, fuel costing, settlement rounding); all failures were fixture/test setup violating PRD preconditions (future timestamps, contradictory boundary data, duplicate kwargs).

## Step 8: Finalize PRD — 2026-08-14T07:52:00.000Z

Step 8 complete. `PRD_FINALIZED.md` is produced at `/home/ubuntu/github/CodingPRD/tasks/task_1654_long_haul_trucking_carrier_operations/workspace/PRD_FINALIZED.md` and is byte-identical to `PRD.md` — the investigation found zero PRD silences or PRD/impl mismatches within the Step 7 scope, so the minimal patch is the empty patch.

## Line counts and delta

- `PRD.md`: 409 lines; `PRD_FINALIZED.md`: 409 lines; delta 0 lines, 0.0%.

## Changes

None. Every `<step_7_diff>` item traced to a verbatim PRD sentence that uniquely determines the behavior, and the implementation is PRD-faithful at each site.

## Per-item investigation log (subject / impl paths enumerated / wording adjustment)

1. **`test_helpers/fixtures.py` — `setup_accepted_load` setdefault merge**
   - (a) Subject: fixture-level kwarg collision (`rate_cents` passed both positionally and via `load_overrides`), breaking the two `test_12` settlement tests at fixture-construction time.
   - (b) Paths enumerated: `test_helpers/fixtures.py:177-190` (the fix itself); the unblocked tests `test_suite/test_12_payroll_settlements.py:150-260` (`test_accessorial_share_rounds_per_charge_then_sums`, `test_per_charge_share_feeds_guarantee_top_up`); impl settlement computation `implementation/services.py:416-433` (per-charge `rhu(Fraction(amount*2500,10000))` then sum; subtotal excludes guarantee; `top_up = max(0, 120000 - subtotal)` gated on non-TERMINATED + >=1 COMPLETED trip in scope).
   - (c) No wording change: the fix is pure Python fixture mechanics with zero API-behavior content, and the unblocked tests quote PRD §3.9 verbatim — impl matches it exactly.

2. **`test_06::test_duty_event_strictly_increasing_enforced` — clock 06:00 → 07:00**
   - (a) Subject: duty-event future-timestamp rejection pre-empting the strictly-increasing rule.
   - (b) Paths enumerated: `implementation/routes_fleet.py:233-256` (future-`occurred_at` → `ERR_INVALID_REQUEST` at lines 240-242, strictly-increasing → `ERR_DUTY_EVENT_OUT_OF_ORDER` at 253-256, in that order); the parallel check-call and fuel-purchase timestamp gates at `implementation/routes_ops.py:519-522` and `611-614`; PRD §3.4 (line 191: "An `occurred_at` after the logical now fails request validation with `ERR_INVALID_REQUEST`") and §2.9 stage 4 (line 131) vs stage 9 (line 136).
   - (c) No wording change: PRD §3.4 + §2.9 already pin both the rule and its pipeline precedence verbatim; the failure was a setup event timestamped after the logical now.

3. **`test_07::_boundary_chain` — `delivered_at`/`clock_to` 20:01 → 21:01**
   - (a) Subject: detention billing arithmetic (anchor, 120 free minutes, 15-minute increments at 1500 cents).
   - (b) Paths enumerated: `implementation/services.py:24-26` (`FREE_MINUTES=120`, `DETENTION_INCREMENT_MIN=15`, `DETENTION_INCREMENT_CENTS=1500`), `services.py:268-274` (shared increment pricing for manual + auto detention), `services.py:282-300` (`auto_create_detention`: anchor = later of arrival/appointment, `billable = max(0, elapsed - 120)`, skip when zero); callers via trip completion `services.py:468-493`; PRD §3.5 (line 217).
   - (c) No wording change: PRD §3.5 pins the arithmetic verbatim ("Exactly 120 elapsed minutes produces nothing... divided into 15-minute increments, rounded up, at 1500 cents per increment"); the old test data (18:00→20:01 = 121 elapsed) simply contradicted the test's own 7500-cent assertion.

4. **`test_10::test_fuel_purchase_tank_capacity_boundary` — second `purchased_at` 12:01 → 12:00**
   - (a) Subject: pipeline ordering — future-`purchased_at` body validation (stage 4) before tank-capacity constraint (stage 10).
   - (b) Paths enumerated: `implementation/routes_ops.py:601-650` (`create_fuel_purchase`: `purchased_at > now()` → `ERR_INVALID_REQUEST` at 611-614, then driver-identity, `ERR_TRIP_NOT_FUELABLE`, `ERR_STATE_NOT_ON_ROUTE`, `ERR_TANK_CAPACITY_EXCEEDED` at ~629-632, `ERR_FUEL_RATE_UNAVAILABLE`, in §2.9 order); costing formulas at 642-646 match PRD §3.7; PRD §3.7 (line 235: future `purchased_at` is `ERR_INVALID_REQUEST`) and §2.9 stages 4/10 (lines 131, 137).
   - (c) No wording change: PRD §3.7 + §2.9 already pin the rule and its precedence verbatim; the future timestamp in the old test data made stage 4 legitimately pre-empt the stage-10 error under test.

**NO-NEW-MISMATCH confirmation:** with zero edits committed, no new wording exists that could mis-describe any code path. The pre-edit searches above (duty-event, check-call, and fuel-purchase timestamp gates; detention pricing shared by auto and manual paths; settlement gross-pay computation) additionally confirm the existing PRD prose is consistent with every implementation path touching those subjects, so keeping the prose verbatim introduces no divergence for Step 9 to undo.

## Step 9: Complete PRD — 2026-08-14T08:05:00.000Z

Done. PRD_COMPLETED.md produced at `/home/ubuntu/github/CodingPRD/tasks/task_1654_long_haul_trucking_carrier_operations/workspace/PRD_COMPLETED.md`.

**Source vs output**: `PRD_FINALIZED.md` (409 lines / 68,082 chars) → `PRD_COMPLETED.md` (409 lines / 71,214 chars), char-delta +3,132. All edits are inline inserts/revisions within existing paragraphs; no new sections.

**Counts**: 14 ambiguity-pins, 1 mismatch-revision (all edits were prose-level; the mismatch class covers where PRD wording, read literally, contradicted impl).

Changes:

- §2.3 — insert — ambiguity — pin `limit`/`offset` validation: non-integer, out-of-range limit (1–100), or negative offset → `ERR_INVALID_REQUEST` 400 — `implementation/common.py:183-207`
- §2.3 — insert — ambiguity — pin creation-sequence tie-break when `created_at` ties (logical clock makes ties common), and add trip-scoped duty-event list to the `occurred_at`-ascending exceptions — `implementation/common.py:210-211`, `implementation/routes_ops.py:585-586`
- §2.3 — insert — ambiguity — pin that `GET /loads/{id}/invoice` is the one non-paginated list response (meta carries no limit/offset/total_count/has_more) — `implementation/common.py:79-82`, `implementation/routes_ops.py:326-332`
- §2.9 stage 4 — revise — mismatch — "non-negative odometers" applies to tractor registration only; check-call odometers are governed by stage-9 monotonicity, not a 400 minimum — `implementation/routes_ops.py:524` (no `min_v`) vs `implementation/routes_fleet.py:383` (`min_v=0`)
- §2.9 stage 4 — insert — ambiguity — pin `effective_to` ≥ `effective_from` as a 400 datetime ordering, and scope the logical-now ceiling to event timestamps only (duty events, check calls, safety events, fuel purchases), not `hired_at`/`last_home_at`/appointments/windows/period bounds — `implementation/routes_fleet.py:574-576`, `implementation/routes_fleet.py:91-92` (no ceiling check)
- §2.10 — insert — ambiguity — body-carried references (load's `customer_id`/`lane_id`, trip's `load_id`/`driver_id`/`tractor_id`, settlement's `driver_id`, optional `trip_id` on duty events/accessorials) resolve to the same per-type 404s, after body-shape validation — `implementation/routes_ops.py:133-134,349-351`, `implementation/routes_fleet.py:245-246`, `implementation/routes_ops.py:302-303`, `implementation/routes_money.py:32`
- §3.1 — insert — ambiguity — duplicate `cdl_number` → `ERR_INVALID_REQUEST` 400 — `implementation/routes_fleet.py:93-95`
- §3.1 — insert — ambiguity — duplicate `unit_number` → 400; `current_fuel_gallons` above capacity → 400 — `implementation/routes_fleet.py:387-392`
- §3.2 — insert — ambiguity — margin read on a never-screened load (null projections) reports `floor_pass` false — `implementation/routes_ops.py:262-263`
- §3.3 — insert — ambiguity — backhaul board: absent `tractor_id` query param → `ERR_INVALID_REQUEST` 400; standard `limit`/`offset` pagination applies — `implementation/routes_ops.py:809-814`
- §3.3 — insert — ambiguity — trip-cancel `reason` supplied as null also defaults to `REASSIGN` — `implementation/routes_ops.py:466-468`
- §3.4 — insert — ambiguity — 11h/70h clocks have no floor and may report negative minutes; fractional remaining minutes are rounded down in responses — `implementation/services.py:206,221`, `implementation/services.py:55-58`
- §3.4 — insert — ambiguity — with no completed long-off run, 11h/14h accumulation anchors at the driver's first recorded event; same anchor rule for the break flag, and a driver currently inside a ≥30-min off run has zero break accumulation — `implementation/services.py:202-208,224-231`
- §3.4 — revise — ambiguity — illegal-driving trigger is "at or below zero" clocks (drive/cycle can go negative), and the projection is evaluated over the stream *before* the new event is appended — `implementation/routes_ops.py:257-262`
- §3.5 — insert — ambiguity — fractional billable detention minutes are truncated to whole minutes before pricing; `amount_cents` computed from that whole-minute `quantity` — `implementation/services.py:300-306`
- §3.6 — insert — ambiguity — at invoice creation `total_cents` stands at `linehaul_cents` + `fuel_surcharge_cents` until issue recomputes it — `implementation/routes_ops.py:747`
- §3.7 — insert — ambiguity — stage-10 fuel-purchase checks run in fixed order: route membership → tank capacity → rate availability — `implementation/routes_ops.py:624-635`
- §3.7 — insert — ambiguity — fuel-plan candidate objects carry `state_code`, `effective_price_cents`, `tax_cents_per_gallon`, `cumulative_miles_to_enter`, `route_order` — `implementation/services.py:356-363`
- §3.8 — insert — ambiguity — manual safety event `severity_points` defaults to 1 when omitted — `implementation/routes_fleet.py:316-318`
