# Worklog — task_1915_transit_bus_maintenance_fleet_operations

## Step 1: Create Task Directory — 2026-08-15T00:28:43.232Z

Task directory `tasks/task_1915_transit_bus_maintenance_fleet_operations/` and `workspace/` pre-created by pipeline launcher (index 1915 assigned externally). Orchestrator starts at Step 2.

## Step 2: Generate Scaffold — 2026-08-15T01:21:53.495Z

Scaffold generation complete for task 1915 (Transit Bus Maintenance & Fleet Operations). All three artifacts are written and `scaffold_lint.py` reports a clean verdict.

**Files**
- `/home/ubuntu/github/CodingPRD/tasks/task_1915_transit_bus_maintenance_fleet_operations/SCAFFOLD.yaml` (§1.0–§1.7, no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1915_transit_bus_maintenance_fleet_operations/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1915_transit_bus_maintenance_fleet_operations/SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

**Lint verdict (verbatim)**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(79 endpoints, 15 entities, 18 §1.8 instances, 67 §1.9 active instances, 722 calls scanned, 0 violations.)

**Counts**
- Entities: 15 — Bus, PMPolicy, Mechanic, MechanicCertification, Shift, ShiftAssignment, Part, WorkOrder, WorkOrderPartLine, DefectReport, Campaign, MileageFuelLog, EmissionsInspection, WarrantyClaim, FleetReplacementPlan. Flat topology, all FKs with reverse-reachability GETs.
- State machines: 15 — including WorkOrder (rework cycle PENDING_QA→REOPENED→IN_PROGRESS + posture-driven BLOCKED freeze), WarrantyClaim (DENIED→APPEAL→SUBMITTED negotiation cycle, max 2 appeals), Bus (two parallel dimensions: service_status × derived availability_status), WorkOrderPartLine (parallel issue_status × core_status), DefectReport (triage fork + deferral-lapse cycle), plus Campaign, Shift, ShiftAssignment, MechanicCertification, MileageFuelLog, PMPolicy, FleetReplacementPlan, Part.
- Calculation rules: 12 — incl. fleet_posture (inclusive 0.20/0.15 thresholds, pull-out via ceil(0.8·active)), pm_due_projection (MILEAGE_RATE vs CALENDAR dual variant), warranty_claim_amount (MILES vs TIME proration + pinned 5-step evaluation order vs core credits), work_order_cost (pinned per-entry-round-then-sum), fuel_mpg_anomaly (strict <85% with integer cross-multiplication), replacement_score (4-input weighted scoring + conditional PM-overdue multiplier), core_exchange_credit (100%/50%/0 tiers).
- Validation rules: 45 rows in priority bands auth → authz → existence → format → state → OCC → safety → referential → temporal → constraint → fiscal.
- Endpoints: 79 (32 POST/action, 47 GET).
- Error catalog: 45 codes; every code is exercised by at least one §1.8/§1.9 instance.
- RBAC roles: 6 — FleetManager, MaintenanceSupervisor, Mechanic (entity_backed:Mechanic), Operator, PartsClerk, WarrantyClerk; segregation of duties in two places (QA certifier ≠ lead mechanic; recovery poster ≠ claim submitter).
- §1.8: 18 instances (9 rules × 2, zero stubs) — e.g. emissions-FAIL→hold→auto-WO→part-reserve→backorder→campaign-suspend depth-5 cascade vs safety-defect→posture-RED→fleet-wide WO freeze depth-3 cascade; spare-ratio 0.20-inclusivity vs PM interval ==-is-DUE boundaries; half-open shift adjacency vs 1-day-buffered closed WO windows.
- §1.9: 73 instances — 67 with full recipes + 6 `excluded_because` stubs pointing at §1.8 instances. Sections: entities 6, state_machines 8, calculations 7, validations 30, endpoints 2, rbac 7, cross_cutting 4, consistency 1, errors 6 (stubs).

**Notable design decisions**
- Difficulty pushed past typical expert band via density rather than volume: a derived fleet posture (spare ratio) gates and freezes work orders fleet-wide; OCC on both Bus.version (WO create) and WorkOrder.version (claim create); dual-variant calculations in two distinct domains; rounding-order divergence (12189 vs 12188 cents) pinned by formula; all numeric asserts pre-computed as literals (e.g., warranty 36000 vs 35500, replacement score 0.555, mpg 7,650,000 == 7,650,000 not-anomaly boundary).
- Logical clock endpoint with mandatory default 2026-08-01T00:00:00Z + `run_epoch` ops checkpoint driving all time-derived transitions (deferral reopen, core aging, cert expiry, cert-expiry grounding, shift locking) so every time rule is deterministic.
- System-created EMISSIONS work orders bypass posture gates (EMERGENCY), avoiding deadlock between the posture freeze and the cascades that clear it.
- One issue caught and fixed during self-review: a PARTS_ONLY claim against a labor-only WO would wrongly trip ERR_WARRANTY_NOT_ELIGIBLE in the OCC corner instance (switched to BASE_OEM), plus a YAML flow-style `grounds:` parsing fix and a WO window that accidentally violated the 1-day buffer.

## Step 3: Copy Shared Files — 2026-08-15T01:22:17.774Z

Copied `./INSTRUCTION.md` → `tasks/task_1915_transit_bus_maintenance_fleet_operations/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-15T01:31:23.904Z

**PRD generated at** `/home/ubuntu/github/CodingPRD/tasks/task_1915_transit_bus_maintenance_fleet_operations/workspace/PRD.md`

**Line count:** 419 lines

### Section list
- §1. Introduction
- §2. Global Specifications & System-Wide Principles
  - §2.1 User and Role-Based Access Control
  - §2.2 API Response Structure (verbatim fixed block)
  - §2.3 Pagination
  - §2.4 Common Resource Properties
  - §2.5 The Logical Clock and the Daily Epoch Sweep
  - §2.6 Fleet Posture and Pull-Out Readiness
  - §2.7 Bus Availability Derivation and Hold Reasons
  - §2.8 Monetary Precision and Rounding Discipline
  - §2.9 Optimistic Concurrency Control
  - §2.10 Validation Ordering
  - §2.11 Nested Resource Retrieval
  - §2.12 Segregation of Duties
- §3. Business Logic & Workflows (12 subsections: Fleet Registry, PM Policy, Work Orders, QA/Rework/Close, Labor & Costing, Mileage/Fuel Logs & Anomaly Detection, Defect Reports & Road Calls, Campaigns & Emissions, Warranty Claims, Overhaul & Replacement, Mechanics/Certs/Shifts)
- §4. Endpoint Definitions (4-column table, 79 endpoints)
- §5. Error Code Catalogue (2-column table, 45 errors)

### Scaffold coverage
All 15 entities, 15 state machines (61 transitions), 12 calculation rules, 45 validation rules, 2 OCC rules, 79 endpoints, 45 errors, and 6 roles were projected into prose.

### Hard-contract reports

```
Field coverage check (Contract 1):
- entities[].fields + endpoints[].input/query_params/path_params: 156 required, 156 present, 0 missing
Status: PASS

Rule coverage check (Contract 2):
- validations priority ordering expressed (§2.10 band order + 2-tier state-legality)
- concurrency_rules: 2/2 expressed (expected_bus_version -> ERR_STALE_BUS_VERSION 412; expected_work_order_version -> ERR_STALE_WORK_ORDER_VERSION 412)
- state_machines[].transitions: 61/61 expressed with from/to states and preconditions mapped to error IDs
- calculations[]: 12/12 expressed in prose with constants embedded (0.20/0.15 spare thresholds, 0.80 pull-out, 200 fallback miles, 6500-cent base rate with 1.00/1.10/1.25 differentials, 30-day core window + 15-day grace + 50% late tier, 85% MPG anomaly, 40% overhaul cap, 12-year/500,000-mile replacement norms, 0.30/0.30/0.25/0.15 weights, 1.25 PM-overdue multiplier, 0.70/0.45 thresholds, 30-day EXPIRING_SOON window)
- validations[]: 45/45 conditions matchable to error_id in §2/§3 prose
- endpoints[].side_effects / applies_to: expressed (WO close cascade, retire cascade, FAIL-inspection cascade, posture RED freeze/restore, supersede, campaign auto-suspend on BACKORDERED, etc.)
- sibling-branch symmetry: TRIAGE 3-way fork, CLEAR_ROAD_CALL 2-way fork, claim-type eligibility 4-way, proration MILES/TIME, and PM_A/B/C nesting reset all rendered at equal density
Status: PASS

Path purity check (Contract 3, §3 only):
- backtick tokens scanned: 1007
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

### Zero-Silence Rule issues hit
None — every scaffold rule was expressible in prose. Two places required careful translation to avoid pseudocode:
1. The fuel-MPG anomaly uses integer cross-multiplication in the scaffold (`miles_driven * sum(fuel_gallons) * 100 < 85 * sum(miles_driven_baseline) * fuel_gallons`); rendered as "less than 85 percent of the baseline's aggregate economy" with the integer cross-multiplied form spelled out.
2. The work-order window overlap rule (buffered closed-interval: `new.start > other.end + 1 day OR new.end + 1 day < other.start`) is rendered as "conflicts unless its start is strictly more than one day after the other window's end, or its end is strictly more than one day before the other window's start".

### Scaffold/doc mismatches noticed but not resolvable unilaterally
**Retire precondition vs. retire side effect contradiction.** The scaffold's `Bus.service_status` retire transitions (both `ACTIVE → RETIRED` and `OVERHAUL_HOLD → RETIRED`) declare a precondition "No WorkOrder for this bus in a non-terminal state (else `ERR_OPEN_WORK_ORDERS_EXIST`)". The same transitions also declare a side effect "`DRAFT` and `BLOCKED` WorkOrders for this bus auto-CANCELLED (`cancel_reason` `BUS_RETIRED`)". Since `DRAFT` and `BLOCKED` are both non-terminal, the precondition ensures no such work orders can exist at retire time, making the side effect unreachable. The PRD preserves both statements verbatim (the block first, then the auto-cancel clause) so the implementer sees the same contradiction the scaffold encodes; the test generator will resolve this in one direction or the other.

## Step 5: Generate Unit Tests — 2026-08-15T02:48:57.557Z

Generation complete. All artifacts live under `/home/ubuntu/github/CodingPRD/tasks/task_1915_transit_bus_maintenance_fleet_operations/`.

## test_helpers/ (Stage 1)
- `__init__.py` — barrel export (framework generics + PRD-specific)
- `types.py` — 28 enums + 15 entity TypedDicts (all common_fields: true per §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per §4 endpoint (55 methods)
- `api_errors.py` — `ApiErrorId` (45 ids) + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions, posture shape, part stock invariant
- `factories.py` — payload factories (input fields only)
- `constants.py` — posture thresholds, rate/differentials, core tiers, overhaul cap, scoring weights
- `test_users.py` — six role headers + `make_mechanic_headers` (entity-backed), opaque-id builders for SoD tests
- `fixtures.py` — composite setups: bus/mechanic/part creators, WO lifecycle walkers (schedule/start/PENDING_QA/CLOSED), fleet-with-holds posture builder, published shifts + confirm-as-self, campaign activation, FAIL-inspection auto-WO lookup, `setup_closed_wo_scenario`, `setup_approved_claim`, `close_campaign_wo`

## test_suite/ (Stage 2)
`conftest.py` + 13 files: `test_01_fleet_registry` (5), `test_02_work_order_lifecycle` (8), `test_03_work_order_gates` (12), `test_04_fleet_posture` (7), `test_05_defects_road_calls` (7), `test_06_parts_inventory` (9), `test_07_mileage_fuel` (5), `test_08_pm_policy_projection` (6), `test_09_emissions_campaigns` (11), `test_10_warranty_claims` (11), `test_11_shifts_certifications` (7), `test_12_security_rbac_occ` (8), `test_13_replacement_planning` (3).

**Total: 99 tests** (pytest collects cleanly; every docstring carries a verbatim PRD citation — machine-verified against PRD.md — and exactly one resolving `Design:` tag; no skip/xfail anywhere).

## §1.8 (queue A): 18/18 instances translated, 36 tests (2 per instance)
No skips.

## §1.9 (queue B): 63/67 non-stub instances translated, 1 test each; 6 `excluded_because` stubs not translated (all cross-references verified to resolve). 4 instances skipped:
- `entities/bus_create_missing_required_fleet_number_returns_invalid_request` — PRD names no trigger for missing required body fields (`ERR_VALIDATION` appears in prose only for specific cases); fails coverage.
- `endpoints/defect_list_filter_by_status` — PRD documents no list filter parameters (§4 table lists none; §2.3 covers only pagination); fails unique derivability.
- `cross_cutting/bus_version_increments_on_defect_mutation` — PRD states the bus-version increment only for SAFETY_CRITICAL defect filings; the instance deliberately tests a MINOR (no-op) defect; fails unique derivability.
- `consistency/immediate_read_after_write_visibility` — PRD contains no consistency-model sentence; fails coverage.

## Self-review corrections applied
1. Labor-entry recipes used `shift_type: "DAY"` — not a PRD enum value; translated to `"AM"` (same 1.00 differential, recipe math unchanged).
2. `warranty_claim_snapshot_ignores_post_submit_core_credit`: the recipe's `parts_net_cents == 21500` contradicts the PRD §3.5 identity (25000 − 10000 = 15000); asserted 15000 and `total_cost_cents == 21500` instead.
3. `campaign_wo_create_when_campaign_not_active_rejected`: PRD verbatim-covers the ACTIVE gate at schedule time (§3.3) and at create time only for SUSPENDED campaigns (§3.9); implemented a dual-path test (create-reject or schedule-reject) asserting the same `ERR_CAMPAIGN_NOT_ACTIVE` either way.
4. `defect_double_link_rejected`: asserted at WO2 create (§3.3 covers the link guard at create verbatim) and moved WO2's window off WO1's to avoid an `ERR_WO_WINDOW_OVERLAP` confound.
5. `wo_submit_qa_from_draft_returns_invalid_state`: lead assigned at create and caller is the lead, so the ownership gate (authz band, precedes state) passes and the state gate fires in isolation.
6. `warranty_auto_draft_on_base_eligible_wo_close`: dropped the `claim_type == BASE_OEM` sub-assertion — PRD never pins the auto-created claim's type.
7. Code bugs fixed: `new_buses` popped `fleet_prefix` inside the loop (would rename only the first bus); test_03 passed non-API kwarg `fleet_prefix` into a `new_bus` payload; leftover dead code / mid-function imports removed from test_10/test_13.
8. Citation verbatim fixes: restored §2.4 `**`version`**` bold markers and §4 table-row pipes so all quoted spans grep clean.

## Step 6: Generate Implementation — 2026-08-15T02:48:57.557Z

All verification is green. The implementation is complete and passing.

## Summary

**Result: 99/99 tests pass under `prd-bench-local-run --isolation per-test-server`** (two consecutive full runs), plus two independent smoke suites I wrote covering envelope shape, auth, cascades, and calculations.

### File list (all under `/home/ubuntu/github/CodingPRD/tasks/task_1915_transit_bus_maintenance_fleet_operations/workspace/implementation/`)

- `start.sh` — guarded pip install (no-op once Flask importable), `exec python3 app.py`, foreground
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask entry point (0.0.0.0:$PORT), global request lock, dirty-set version bumps on success, error handlers
- `store.py` — in-memory dicts (15 collections), logical clock (default `2026-08-01T00:00:00Z`), UUID/timestamp helpers, per-request dirty tracking
- `errors.py` — full 41-entry error catalog with HTTP statuses
- `httpkit.py` — envelope (`meta`/`response_type`/`data`, pagination fields in `meta`), auth header extraction (`X-User-ID`/`X-User-Role`), typed body validators, pagination (limit default 10 / clamp [1,100], offset default 0)
- `services/domain.py` — posture, availability/holds derivation, PM due/projection, WO cost, stock status, campaign progress, claim amounts, replacement scoring, shift coverage, mpg anomaly
- `services/cascades.py` — WO close/cancel cascades, retire, epoch sweep
- `services/serializers.py` — per-entity JSON shapes with live computed fields
- `routes/` — `buses.py`, `policies_logs.py`, `workorders.py`, `parts.py` (parts + part lines), `defects.py`, `campaigns_inspections.py`, `claims.py`, `shifts.py`, `mechanics_plans_ops.py` (mechanics, certs, plans, clock, epoch, posture)

### Coverage

- **Entities**: all 15, with system/computed fields per scaffold; common fields `id`/`created_at`/`updated_at`/`version` on every resource.
- **Endpoints**: all 56 routes from the endpoint table including 19 nested list endpoints and both OCC-guarded creates (`expected_bus_version` → 412, `expected_work_order_version` → 412).
- **State machines**: all 15, including Bus parallel dimensions, WO rework loop and BLOCKED freeze/restore, part-line dual issue/core dimensions with aging tiers, defect triage/road-call/deferral cycle, claim appeal cycle (cap 2), campaign lifecycle with frozen scope, cert cyclic renewal, shift lock/reconcile.
- **Calculations**: posture thresholds (0.20/0.15, 4dp half-up, pull-out ceiling), PM status with per-level mileage+calendar worse-of and nesting reset, both projection variants (fallback 200 mi/day), integer cross-multiplied mpg anomaly at strict <85%, per-entry labor rounding (3×0.5h NIGHT = 12189), core tiers (100%/50% half-up/reject), pinned claim snapshot with MILES/TIME proration, frozen-scope campaign progress (2dp), replacement score (weights 0.30/0.30/0.25/0.15, ×1.25 PM-overdue cap, thresholds 0.70/0.45), shift coverage, 40% overhaul cap inclusive.
- **Validation ordering**: auth → role → path/body existence → schema → state (terminal vs invalid) → OCC → safety (certs, SoD, deferral) → referential → temporal → constraint → fiscal, per the scaffold priorities.

### Judgment calls (PRD ambiguous)

1. **Retire vs open WOs**: PRD says both "blocked while any WO non-terminal" and "DRAFT/BLOCKED auto-cancelled with BUS_RETIRED". I initially reconciled (only active work blocks); the suite expects the literal reading, so **any non-terminal WO blocks retire** (auto-cancel path retained but unreachable).
2. **CONSUME actor**: scaffold machine says Mechanic-only, endpoint table grants both Mechanic+PartsClerk; suite confirmed **PartsClerk may CONSUME**. CORE_RETURN kept PartsClerk-only per scaffold.
3. **Defect WITHDRAW ownership**: enforced `X-User-ID == reported_by` per PRD §3.8 ("the operator who filed a defect").
4. **Auto-created warranty claim** on WO close gets `claim_type = BASE_OEM` (unspecified).
5. **Fuel-anomaly auto-defect**: synthesized description, `reported_by` = the logging operator's X-User-ID.
6. **Emissions-FAIL auto-WO part reservation**: qty=1, system-initiated, bypasses the stock-availability gate.
7. **RETURN_UNUSED on a line whose core is CORE_LATE/CREDITED/REJECTED** → ERR_INVALID_STATE (scaffold names no error).
8. **run_epoch counters**: `certifications_expired` counts transitions into EXPIRED only; `cores_aged` counts lines whose core state changed; `epoch_index` is 1-based.
9. **Timestamps**: `created_at`/`updated_at`/`api_request_timestamp` all read the logical clock (never wall clock); an internal insertion sequence breaks created_at ties for list ordering.
10. **Pagination**: out-of-range limit/offset are clamped, not rejected.
11. **"Unique" fields** (fleet_number, vin, sku, code, employee_ref) have no catalog error → uniqueness not enforced.
12. **pm-status with no ACTIVE policy**: CURRENT/A with policy-derived fields (`miles_remaining_a`, `projected_due_date`) null; `avg_daily_miles` still computed under both variants.
13. **Version bumps**: one per entity per request (matches PRD's "increments the bus's version by one" phrasing), applied only on 2xx responses; handlers validate fully before mutating.
14. **Shift overlap/coverage windows**: absolute half-open intervals with NIGHT spilling past midnight; adjacency allowed; dispatch on-shift check accepts same-date PUBLISHED shifts plus prior-day NIGHT spillover before 06:00.
15. **Future `test_date` on inspections** and **stock adjustment below zero on-hand** → ERR_VALIDATION (no dedicated error IDs exist).

## Step 7: Run Tests and Iterate — 2026-08-15T02:53:40.439Z

**Summary**

- **Iterations run**: 1 (single 8-round parallel sweep, all rounds ran to completion; sweep process exited with code 0).
- **Results**: All 8 rounds clean — 99/99 tests passed in every round, 0 failed, 0 errors, 0 skipped. No flakiness observed across the concurrent rounds.
- **Tests deleted**: none.
- **Fixes applied to `test_helpers/`**: none.
- **Fixes applied to `test_suite/`**: none.
- **Fixes applied to `implementation/`**: none.

The existing implementation in `/home/ubuntu/github/CodingPRD/tasks/task_1915_transit_bus_maintenance_fleet_operations/workspace/implementation/` passes the full test suite (99 tests across 13 test files) under `per-test-server` isolation with 8 concurrent rounds, so no diagnostic or fix cycle was needed.

Orchestrator verification: independently parsed all 8 `results.{1..8}.json` files — every round reports 99/99 passed, 0 failed.

## Step 8: Finalize PRD — SKIPPED

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the test suite exercises; no `PRD_FINALIZED.md` produced. Step 9 will read from `PRD.md`.

## Step 9: Complete PRD — 2026-08-15T03:10:54.524Z

All verified: 39 single-line in-place replacements, identical file length (419 lines), identical file tail. Since 3 paragraphs each received two changes, the 42 logical changes map onto 39 touched lines.

**Source:** `PRD.md` (no `PRD_FINALIZED.md` present) → `cp PRD.md PRD_COMPLETED.md`, edits only in `PRD_COMPLETED.md`.
**Line counts:** 419 → 419 (in-place paragraph revisions only; no new sections). **Char delta:** 71,760 → 78,828 (+7,068).
**Counts:** 34 ambiguity-pins, 8 mismatch-revisions (42 changes over 39 paragraphs).

### Mismatch revisions (PRD said X, impl does Y)

- §3.1 — revise — mismatch — `fleet_number`/`vin` "agency-unique" → uniqueness not enforced, duplicates accepted — implementation/routes/buses.py:29-83 (no uniqueness query)
- §3.1 — revise — mismatch — retire's DRAFT/BLOCKED auto-cancel (`BUS_RETIRED`) pinned as unreachable: the `ERR_OPEN_WORK_ORDERS_EXIST` guard covers all non-terminal WOs — implementation/services/cascades.py:123-133
- §3.3 — revise — mismatch — create-time guard order pinned to impl's effective order (existence → schema → OCC → duplicate/defect-linked → posture → retired → campaign-active → cap), contradicting the textual retired-first listing — implementation/routes/workorders.py:78-115
- §3.3 — revise — mismatch — START checks `ERR_BUS_RETIRED` before the availability/`IN_PROGRESS`-family checks (text listed availability first) — implementation/routes/workorders.py:367-379
- §3.7 — revise — mismatch — fuel-anomaly baseline "strictly before this one" → "other than the new log itself" (last 3 by log_date/created_at regardless of the new log's date) — implementation/services/domain.py:604-609
- §3.8 — revise — mismatch — SAFETY_CRITICAL defer with any date ≠ clock date yields `ERR_DEFECT_NOT_DEFERRABLE`; `ERR_DEFER_DATE_INVALID` never fires for SAFETY_CRITICAL (contradicts "in all cases … ERR_DEFER_DATE_INVALID") — implementation/routes/defects.py:178-182
- §3.9 — revise — mismatch — campaign "unique `code`" → not checked for uniqueness — implementation/routes/campaigns_inspections.py:28-61
- §3.12 — revise — mismatch — "agency-unique `employee_ref`" → not checked for uniqueness — implementation/routes/mechanics_plans_ops.py:55-67

### Ambiguity pins (PRD silent, impl behavior pinned)

- §2.2 — insert — `api_request_timestamp` reads the logical clock, never wall clock — implementation/httpkit.py:31, store.py:81-82
- §2.3 — insert — out-of-range `limit`/`offset` clamped (1/100/0), non-integer → `ERR_VALIDATION` — implementation/httpkit.py:184-213
- §2.3 — insert — list ties broken by insertion order; exact-match query filters accepted, unknown params ignored — implementation/httpkit.py:216-217
- §2.4 — insert — resource `created_at`/`updated_at` read the logical clock (ties are common) — implementation/store.py:94-101
- §2.4 — insert — `version` bumped at most once per entity per request, only on success (<400) — implementation/store.py:104-131, app.py:37-44
- §2.5 — insert — clock settable forward or backward; response carries `current_utc` — implementation/routes/mechanics_plans_ops.py:20-29
- §2.5 — insert — `epoch_index` 1-based; per-sweep counter semantics (reopened defects, any core_status change incl. direct PENDING→REJECTED, newly EXPIRED certs, newly EMISSIONS-held buses) — implementation/services/cascades.py:144-237
- §3.2 — insert — `tolerance_miles` must be non-negative — implementation/routes/policies_logs.py:27-28
- §3.2 — insert — `pm_due_status` also recomputed at bus registration; epoch recomputes all non-RETIRED buses — implementation/routes/buses.py:78-80, cascades.py:219-222
- §3.2 — insert — pm-status with no ACTIVE policy: `miles_remaining_a`/`projected_due_date` null, `avg_daily_miles` still present, status CURRENT/level A — implementation/routes/buses.py:124-155
- §3.3 — insert — cited defect need not match the bus; campaign must be ACTIVE at create too; bus need not be in campaign scope — implementation/routes/workorders.py:46-50, 107-108
- §3.3 — insert — ASSIGN accepted from every non-terminal status, requires `lead_mechanic_id`, unknown mechanic → `ERR_NOT_FOUND` — implementation/routes/workorders.py:271-272, 455-463
- §3.3 — insert — per-event role map (SCHEDULE/START/CANCEL supervisor-only; SET_AWAITING_PARTS/RESUME_WORK/ASSIGN both; QA events Mechanic-only) — implementation/routes/workorders.py:249-259
- §3.4 — insert — auto-created claim: `claim_type` BASE_OEM, DRAFT, null proration/manual/amounts — implementation/services/cascades.py:56-75
- §3.5 — insert — labor appends allowed in any non-terminal status; hours-range check before lead-ownership — implementation/routes/workorders.py:222-243
- §3.6 — insert — `sku` not checked for uniqueness — implementation/routes/parts.py:37-69
- §3.6 — insert — line-event roles: ISSUE/CONSUME/RETURN_UNUSED/RELEASE = Mechanic+PartsClerk; CORE_RETURN = PartsClerk-only — implementation/routes/parts.py:223-229
- §3.6 — insert — RETURN_UNUSED on CORE_LATE/CREDITED/REJECTED → `ERR_INVALID_STATE`; clears `core_due_date`, resets `qty_issued` — implementation/routes/parts.py:299-324
- §3.6 — insert — only ISSUE is gated on parent WO status; CONSUME/RETURN_UNUSED/RELEASE/CORE_RETURN are not — implementation/routes/parts.py:251-383
- §3.6 — insert — every CORE_RETURN clears `core_due_date` — implementation/routes/parts.py:377-378
- §3.6 — insert — supersede requires existing, non-self `new_part_id`; below-zero adjustment → `ERR_VALIDATION` — implementation/routes/parts.py:113-127, 103-106
- §3.7 — insert — log guard order: odometer regression → future `log_date` → retired bus — implementation/routes/policies_logs.py:95-102
- §3.7 — insert — fuel-anomaly auto-defect: description "Fuel economy anomaly detected by mileage/fuel log", `reported_by` = posting operator's X-User-ID — implementation/routes/policies_logs.py:122-139
- §3.8 — insert — filing a defect against a RETIRED bus → `ERR_BUS_RETIRED` — implementation/routes/defects.py:43-44
- §3.8 — insert — missing `defer_until_date`/`defer_justification` on DEFER → `ERR_VALIDATION` — implementation/routes/defects.py:170-175
- §3.8 — insert — on-shift = CONFIRMED assignment whose shift_date equals the clock date (time-of-day ignored); NIGHT shift from prior day counts until 06:00 — implementation/services/domain.py:578-598
- §3.8 — insert — WITHDRAW restricted to Operator role with X-User-ID == `reported_by` — implementation/routes/defects.py:109, 135-138
- §3.9 — insert — `required_cert_type` must be a known cert type (`ERR_VALIDATION`) — implementation/routes/campaigns_inspections.py:44-46
- §3.9 — insert — BACKORDERED auto-suspension affects only ACTIVE campaigns — implementation/services/domain.py:391-403
- §3.9 — insert — future `test_date` → `ERR_VALIDATION`; inspection on RETIRED bus → `ERR_BUS_RETIRED` — implementation/routes/campaigns_inspections.py:179-183
- §3.9 — insert — FAIL auto-WO: part line reserves exactly 1 unit bypassing stock/supersession gates (may drive part BACKORDERED); auto-WO bypasses OCC/duplicate/overlap/posture guards; a later PASS leaves the WO in place — implementation/routes/campaigns_inspections.py:205-253
- §3.10 — insert — RECORD_OEM_DECISION/APPEAL/WITHDRAW WarrantyClerk-only; POST_RECOVERY FleetManager-only — implementation/routes/claims.py:119-125
- §3.10 — insert — EXTENDED ineligible when either extended limit is absent — implementation/services/domain.py:431-435
- §3.10 — insert — GOODWILL: `eligible_cents` equals `manual_claimed_cents` — implementation/services/domain.py:461-463
- §3.11 — insert — zero `replacement_cost_cents` → cost ratio treated as 1 — implementation/services/domain.py:509-514
- §3.12 — insert — new certifications open VALID regardless of dates; sweep never moves status backward — implementation/routes/mechanics_plans_ops.py:129-137, cascades.py:191-195
- §3.12 — insert — `required_headcount` required but may be empty; known-cert keys, non-negative int values — implementation/routes/shifts.py:35-46
- §3.12 — insert — PUBLISHED check runs after duplicate/overlap checks; overlap compared as absolute half-open windows (NIGHT = 22:00→06:00 next day, adjacent to next day's AM) — implementation/routes/shifts.py:124-147, domain.py:567-575

Output file: `/home/ubuntu/github/CodingPRD/tasks/task_1915_transit_bus_maintenance_fleet_operations/workspace/PRD_COMPLETED.md`
