# Worklog — task_1504_driveway_sealcoating_asphalt_maintenance

## Step 1: Create Task Directory — 2026-08-13T14:40:00.000Z

Pre-assigned directory `tasks/task_1504_driveway_sealcoating_asphalt_maintenance/` with `workspace/` already exists (pipeline harness-created). Step 1 treated as DONE per invocation instructions. Target difficulty: harder than expert level.

## Step 2: Generate Scaffold — 2026-08-13T16:12:00.000Z

Scaffold generation complete. Final lint verdict (verbatim):

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

### Files written

| File | Lines |
|---|---|
| SCAFFOLD.yaml | 1798 |
| SCAFFOLD_DIFFICULTY_DESIGN.yaml | 877 |
| SCAFFOLD_CORNER_DESIGN.yaml | 1698 |

### §1.0–§1.7 surface counts (SCAFFOLD.yaml)

- **Entities: 14** — Customer, Property, SiteAssessment, Material, MaterialLot, Crew, RouteSheet, Quote, WorkOrder (3 parallel state dimensions: execution × billing × striping), DisplacementPlan, Invoice, WarrantyRecord, WarrantyClaim, WeatherSnapshot (immutable event entity, `common_fields: false`). Flat topology with FK references and full FK reverse-reachability via filtered-list GETs.
- **State machines: 11** — including a Quote revision cycle (DRAFT→SENT→REVISION_REQUESTED→DRAFT), WorkOrder parallel dimensions with a cross-dimension gate (COMPLETE requires striping VERIFIED; PAID collapses COMPLETED→CLOSED), and weather-hold/reschedule loops.
- **Concurrency rules: 2** — OCC on `Property.version` (quote create-with-supersede) and `WorkOrder.version` (reschedule).
- **Calculations: 8** — weighted-scoring PCI with per-factor caps; tiered multi-factor job pricing (provisional/final variants); invoice settlement with pinned nested-rounding order + surcharge tiered on the rounded subtotal; ceil-based gallons/application-rate math; temperature/precipitation-adjusted cure windows; ADA stall tiers (boundary at 100); route density/capacity gates; crew utilization (projected vs realized variants).
- **Validations: 11** priority layers (auth → ownership → existence → state → business_safety → referential → temporal → constraint → fiscal → OCC).
- **Endpoints: 66** under `/api`, including the `POST /api/_clock/set_current_utc` test-driving clock (default `2026-08-01T00:00:00Z`).
- **Errors: 62** (all referenced by a validation or transition; the 13 `*_NOT_FOUND` are covered by the priority-4 template).
- **Roles: 5** — OfficeAdmin/Estimator/Dispatcher/CrewLead (opaque), Customer (`entity_backed:Customer`); segregation of duties on warranty investigate vs approve.

### §1.8 instance counts

9 rules × 2 instances = **18** (all with full structured `setup_api_calls`; every formula-derived assert pre-computed to literals — e.g., quote 50300¢ vs invoice 56922¢, rounding-order 49005/51945, utilization 20.0% vs 7.8%, cure 84h cold+wet, capacity 8000==8000 then +1 rejected).

### §1.9 instance counts

**57 active corner instances + 5 `excluded_because` stubs** across all nine claim-extraction-guide sections (entities 7, state_machines 11, calculations 6+2 stubs, validations 10, endpoints 1+1 stub, errors 9+1 stub, rbac 5, cross-cutting 3+1 stub, consistency 1).

Lint scanned 1389 calls across both design files with zero violations on the final run.

## Step 3: Copy Shared Files — 2026-08-13T16:13:00.000Z

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md (bash-only step).

## Step 4: Generate PRD — 2026-08-13T16:25:00.000Z

All contracts verified. Here is the final summary.

**Output:** `workspace/PRD.md` — 370 lines.

**Section list:**
- 1. Introduction (2 paragraphs, business-context angle)
- 2. Global Specifications & System-Wide Principles
  - 2.1 User and Role-Based Access Control
  - 2.2 API Response Structure (verbatim block, confirmed byte-identical to the skill's canonical source)
  - 2.3 Pagination
  - 2.4 Common Resource Properties
  - 2.5 Monetary Precision and Rounding
  - 2.6 Optimistic Concurrency Control
  - 2.7 The Logical Clock and the Paving Season
  - 2.8 Weather Gating and Weather-Driven Cascades
  - 2.9 The Material Lot Ledger
  - 2.10 Route Density and Daily Capacity Discipline
  - 2.11 Validation Order
- 3. Business Logic & Workflows (3.1 Customers/Properties/Materials/Seal Cycle; 3.2 Site Measurement & PCI; 3.3 Quoting & Cost Floor; 3.4 Work Order Parallel Dimensions; 3.5 Scheduling Gates & Reservations; 3.6 Vehicle Displacement; 3.7 Execution & Cure; 3.8 Striping; 3.9 Invoicing & Settlement; 3.10 Warranty & Segregation of Duties; 3.11 Weather Postings, Utilization & Clock)
- 4. Endpoint Definitions (66-row table, 4 columns)
- 5. Error Code Catalogue (62 errors, 2 columns)

**Coverage audit (scaffold §1.1–§1.7):**

- **§1.1 Entities** — All 14 entities narrated; every field name from every entity appears verbatim in backticks (mechanical check: 0 missing of ~125 required names, including endpoint-only inputs `to_iso8601`, `month`, `amount_cents`, `expected_property_version`, `expected_work_order_version`). Computed fields carry their derivations (e.g. `on_hand_gallons` four-column ledger, `stripe_linear_ft_computed` = 18/stall + 40/ADA, `open_quote_id` singularity, `next_seal_eligible_on` = completion + `reapplication_months`). WeatherSnapshot's `common_fields: false` exception stated explicitly in §2.4.
- **§1.2 State machines** — All 10 machines rendered with exact state strings, per-transition preconditions paired with their error IDs, and every side effect stated (supersede cascades, lazy expiry flips for assessment/quote/warranty, weather-hold cascade chain sheet→work order→displacement plan, cancel compensation with lot `IN_USE→RECEIVED` reversion, re-publish non-auto-return rule, billing→CLOSED cascade, claim→REPAIR_SCHEDULED→RESOLVED chain).
- **§1.2.1 Concurrency rules** — Both OCC rules in §2.6 with write-endpoint framing, `expected_property_version`/`expected_work_order_version`, `ERR_STALE_VERSION` + HTTP 412; no race-condition language.
- **§1.3 Calculations** — All 7 expressed in precise prose with constants embedded: PCI (caps 40/35/15, weights 400/700/300, slope 10/5/0, floor 0); job_pricing (average-rate tiers 30/24/18 with inclusive boundaries at 1000/5000, grade factors 1.00/1.35/1.15, per-line rates 150/800/90, pinned per-line-round-then-sum order, mobilization 7500 below 200000, minimum 25000, cost floor with labor 5 cents/sqft); invoice_settlement (no discount, pinned order, fuel tiers 6%/4%/2% keyed on rounded subtotal at 100000/500000); gallons (waste factor 1.10, ceil); cure projection (55°F ×1.5, +12h wet, observed-over-forecast tie-break); ADA stalls (1/2/3/4 bands, exactly-100 boundary, +1 per 50 above 100, 18ft/stall + 40ft/ADA); route density (180-minute drive ceiling, equality allowed, included-status set); crew utilization (projected vs realized variants, cancelled sheets excluded, zero-capacity → 0.0, 1-decimal half-up).
- **§1.4 Validations** — All 11 priority levels rendered as an explicit ordered list in §2.11, each condition matchable to its error IDs in §2/§3 prose.
- **§1.5 Endpoints** — All 66 endpoints in the §4 table with method, path, description, roles; 201/200 status-code rule stated above the table.
- **§1.6 Errors** — All 62 catalog errors in §5 (ID + HTTP status only); every ID also mentioned with its trigger condition in §2/§3 prose (mechanical check: 0 missing).
- **§1.7 Roles** — All five roles with exact spelling in §2.1; `Customer` identity translated as entity-backed ownership semantics; the four staff roles translated as opaque identifiers with `investigated_by` as the recording example.

**Hard contracts:** Contract 1 (field-name coverage) PASS — 0 missing; Contract 2 (rule coverage) PASS — all transitions, calculations, validations, OCC rules, side effects, and sibling branches (cancel from 3 states, quarantine from 2 states, cascade sources) expressed with equal density; Contract 3 (§3 path purity) PASS — 0 violations after rewriting the two `PATCH` mentions. The forbidden sibling files were never opened.

## Step 6: Generate Implementation — 2026-08-13T16:44:00.000Z

Clean boot confirmed: empty store at startup, correct envelope with pagination meta (`limit`/`offset`/`total_count`/`has_more`), default logical clock at 2026-08-01T00:00:00.000Z, request ID prefixed `req_`, ISO 8601 with 3 fractional digits.

### Files written (22 files, 3,326 total lines)

**Foundation:** start.sh (8), requirements.txt (1), app.py (65), db.py (27), clock.py (49), errors.py (77), middleware.py (210), response.py (43), services.py (357)

**Routes:** routes/__init__.py (0), clock_admin.py (26), customers.py (64), properties.py (80), assessments.py (130), materials.py (87), material_lots.py (127), crews.py (108), route_sheets.py (133), quotes.py (390), work_orders.py (767), displacement_plans.py (99), invoices.py (126), warranty.py (259), weather.py (93)

### Endpoint count: 54 endpoints implemented (per agent summary)

Clock admin (1), customers (3), properties (3), assessments (4), materials (3), material lots (5), crews (4 including utilization), route sheets (5), quotes (7), work orders (8: list/get/schedule/reschedule/start/finish/complete/cancel), displacement plans (4), striping (4: plan/approve/mark-applied/verify), invoices (4), warranty records (2) + warranty claims (6), weather snapshots (2).

### Key behaviors implemented
- Response envelope with `meta.api_request_id` / `api_request_timestamp` (3-fractional-digit ISO UTC), `response_type`, `data`, list pagination fields in meta
- Logical clock (default 2026-08-01T00:00:00Z), settable via OfficeAdmin-only endpoint; never falls back to wall clock
- Full role-based access control with X-User-ID / X-User-Role; Customer ownership enforcement via `ERR_NOT_RESOURCE_OWNER`
- All 14 state machines with preconditions and side effects (SiteAssessment, Quote, WorkOrder execution, parallel WorkOrder billing + striping, RouteSheet, DisplacementPlan, MaterialLot, Invoice, WarrantyRecord, WarrantyClaim)
- All 7 calculations: PCI, tiered quote pricing with per-line half-up rounding and cost floor, invoice settlement with mobilization + fuel surcharge tiers, material gallons (ceil), cure window projection (forecast + observed variants), ADA stall requirement, route density gate, crew utilization (projected vs realized)
- Lazy state evaluations: quote expiry (14d), assessment expiry (30d), warranty expiry, route sheet auto-completion
- OCC on quote create (`expected_property_version`) and work-order reschedule (`expected_work_order_version`) with `ERR_STALE_VERSION` (412)
- Weather-driven cascade: failing snapshot (precip>60 or min_temp<40) flips PUBLISHED sheets + their SCHEDULED WOs to WEATHER_HOLD and NOTICE_SENT/CLEARED plans to STALE
- Compensation cascades on cancel/reschedule: lot reservations released, sheet booking recomputed, lot returns to RECEIVED when drained
- Segregation of duties on warranty claim approve/deny vs investigator
- Decimal-based money math (ROUND_HALF_UP) — no floats for cents

### Smoke-boot check: PASSED
`bash start.sh` boots cleanly from a fresh process, binds 0.0.0.0 on $PORT, and responds correctly (empty list with full pagination envelope, default clock 2026-08-01, proper auth-error path). Dependency install guarded by `python3 -c "import flask"` so per-test reboots skip pip. No entity seeding at startup — store starts empty.

## Step 5: Generate Unit Tests — 2026-08-13T17:35:00.000Z

**Files written:**

`test_helpers/` (2028 lines):
- `types.py` (387) — 14 entity TypedDicts + 14 enums; `WeatherSnapshot` correctly omits `updated_at`/`version` per its append-only nature
- `api_client.py` (281) — `ApiClient(GenericApiClient)` with 60 endpoint methods covering every PRD §4 route
- `api_errors.py` (138) — 62 `ApiErrorId` members + HTTP map registered via `set_error_http_status_map`
- `assertions.py` (273) — per-entity asserts, lot-ledger and capacity-ledger invariant checkers, `assert_instant_equal` (datetime-value comparison that tolerates fractional-second rendering, since the PRD pins milliseconds only on `created_at`/`updated_at`)
- `factories.py` (147), `constants.py` (103), `test_users.py` (32, incl. mandatory `make_customer_headers(customer_id)` for the entity-backed Customer role and `make_office_admin_headers` for segregation-of-duties), `__init__.py` (52)
- `fixtures.py` (615) — tiered composites: `setup_quote_scenario` → `setup_sent_quote` → `setup_accepted_job` → `setup_scheduled_job` → `setup_cleared_job` → `setup_in_progress_job` → `setup_curing_job` → `setup_completed_job`, plus `setup_held_job` (weather-hold cascade), `setup_warranty_scenario`/`setup_open_claim`/`setup_investigating_claim`, `add_accepted_job`/`schedule_onto_sheet`/`clear_plan_for` for multi-job scenarios

`test_suite/` (3410 lines): `conftest.py` (39) + 13 numbered test files (test_01 customers/properties/assessments → test_13 security).

**Test counts**: 89 test functions (91 collected pytest cases; two corner tests are parametrized ×2).
- **Queue A (Difficulty): 36 tests** — all 18 instances at exactly ≥2 each
- **Queue B (Corner): 53 tests** — 53 of 57 non-stub instances; all 5 `excluded_because:` stubs verified to resolve to real difficulty instances and not translated

**Skipped instances** (4, all queue B, two-condition filter failures):
1. `entities/customer_create_missing_required_returns_invalid_request` — no verbatim PRD sentence names a rejection error for omitted required fields (ERR_INVALID_REQUEST's only prose trigger is the discount range)
2. `entities/property_create_invalid_enum_returns_invalid_request` — same gap for out-of-enum `lot_kind`
3. `validations/quote_create_with_draft_assessment_rejected` — PRD names `ERR_ASSESSMENT_NOT_USABLE` only for the quote **send** path; the create-time error for a DRAFT assessment is not uniquely derivable
4. `endpoints/work_order_filtered_list_multi_fk` — PRD §4 says only "multi-filter list" without enumerating the filter parameters, so the asserted `?route_sheet_id=`/`?quote_id=`/`?execution_status=` semantics are not uniquely derivable

**Notable findings**:
- PRD internal inconsistency: §3.6 prose writes `ERR_PLAN_NOT_NOTICABLE` while the §5 catalogue and scaffold list `ERR_PLAN_NOT_NOTIFIABLE`; tests assert the catalogue id and cite the §5 row
- Corner instance `invoice_pay_before_issue_rejected`'s pre-computed literals contain an arithmetic slip (30100+7500=37600, not 37610); the test asserts the PRD-formula-derived values (subtotal 37600, surcharge 2256, total 39856)
- Utilization response key names (`projected_sqft`, `realized_utilization_pct`, etc.) are not verbatim in PRD prose — only `capacity_sqft` is; the asserted values are PRD-derived and keys are the natural rendering (accepted risk, flagged)

**Self-audit verdict**:
- Stage 1: PASS — helpers import cleanly, all framework signatures used exactly as specified, identity threading for the entity-backed Customer role throughout
- Stage 2: PASS — every one of the 89 test functions carries exactly one `Design:` tag resolving to a real instance; all 120 quoted PRD citation spans survive literal grep of PRD.md (whitespace-normalized); no skip/xfail markers; no scaffold references in comments; all 13 test modules import against `test_helpers` and `pytest --collect-only` succeeds (91 cases)

## Step 7: Run Tests and Iterate — 2026-08-13T18:15:00.000Z

All done. The final 8-round parallel sweep is fully clean: 90/90 passed in every round.

**Iterations run:** 2 (initial 8-round sweep → diagnosis + fixes → 1 single verification round 90/90 → final 8-round parallel sweep: **all 8 rounds 90/90 passed, 0 failed, 0 errors**).

**Tests deleted (1):**
- `test_04_scheduling_gates.py::TestWeatherGatePrecedence::test_missing_weather_beats_past_date` — ERROR PRECEDENCE SILENCE / unreachable scenario. It asserted `ERR_WEATHER_DATA_MISSING` when scheduling onto a past-dated sheet. Under PRD §2.7 ("lazy state evaluations … at the moment the relevant resource is loaded or acted upon") + §3.5 (a past-dated sheet with no active work orders settles to `COMPLETED`), the sheet lazily completes on load, so gate 2 reports `ERR_ROUTE_SHEET_NOT_SCHEDULABLE` before the weather gate can fire. The scenario is provably unreachable: keeping a past-dated sheet PUBLISHED requires an active work order on it, which requires a prior successful schedule, which requires a weather snapshot for that date — so "no snapshot + past date" can never co-occur under a PRD-faithful implementation. Scaffold driver: `Difficulty/priority_pair_validation_conflict/schedule_safety_vs_temporal`.

**Fixes applied to test_suite/ (test bugs; no assertion weakened):**
- `test_04_scheduling_gates.py` — `TestWeatherGatePrecedence` fixture `_setup_past_sheet_without_weather` → `_setup_sheet_without_weather` with sheet date `2026-07-20` → in-season future `2026-08-10`: publishing a past-dated sheet is correctly rejected by the PRD-required lazy closure, so the fixture's own setup violated PRD. The weather-missing assertion (`ERR_WEATHER_DATA_MISSING` + WO stays PENDING with null fields) is unchanged.
- `test_04_scheduling_gates.py` — `TestPastDateGate::test_schedule_date_in_past_rejected` fixture rebuilt: an anchored sheet (a SCHEDULED job keeps it PUBLISHED per §3.5's lazy-closure carve-out), clock advanced past the service date, second accepted job via `add_accepted_job` (import added). Assertion `ERR_DATE_IN_PAST` (PRD §2.7 verbatim) unchanged.
- `test_05_route_capacity_and_overlaps.py` — added missing `get_material_lot` import (NameError; helper already existed in `test_helpers/fixtures.py`).
- `test_02_quote_pricing.py::TestCostFloor` — assertion fixed from `list_quotes == []` to `== [setup quote id]`: the fixture legitimately pre-creates a DRAFT quote, and PRD §3.3 supersedes only on a *successful* create. The `ERR_PRICE_BELOW_COST_FLOOR` rejection assertion is untouched.

**Fixes applied to implementation/:**
- `workspace/implementation/routes/work_orders.py::_release_booking` — detach the work order (`route_sheet_id`/`material_lot_id` → None) *before* `refresh_route_sheet`; previously the recompute ran while the WO was still attached in an aggregate-included status, so cancel/reschedule never shrank the old sheet's `booked_sqft`/`total_drive_minutes` (PRD §3.5: "the old sheet's booked area and drive minutes shrink"). Fixed 3 tests (capacity ledger through cancel, reschedule OCC old-booking release, cancel-release cascade).
- `workspace/implementation/routes/work_orders.py::complete_work_order` — `next_seal_eligible_on` now preserves the completion timestamp's time-of-day when adding `reapplication_months` (was date-only midnight), per PRD §3.1 "the completion timestamp plus that job's material `reapplication_months`". Fixed the reseal-interval test.

No PRD-required implementation checks were removed or weakened, nothing was added to the implementation beyond PRD-traced behavior, and no skip/xfail was introduced.

## Step 8: Finalize PRD — 2026-08-13T18:30:00.000Z

**Output:** `workspace/PRD_FINALIZED.md`

**Line counts:** PRD.md = 370 lines, PRD_FINALIZED.md = 370 lines — 0% line-count delta (two inline sentence-level revisions, no sections added or removed).

### Changes (one bullet per edit)

- **§3.1** — revise — `next_seal_eligible_on` now explicitly pinned as "calendar months added to the completion timestamp itself, with the completion's time of day preserved, so `next_seal_eligible_on` is a full timestamp rather than a bare date" — `implementation/routes/work_orders.py:661-665` (step 7 impl fix: was date-only midnight, now preserves completion time-of-day; test asserts `2028-08-12T07:00:00Z`).
- **§3.3** — insert — appended to the open-quote supersession paragraph: "Supersession is strictly a consequence of a successful create: a create rejected for any reason (including the cost-floor rejection above) persists no quote, leaves any prior open quote in its current state, and does not modify `open_quote_id` or the property's `version`." — `implementation/routes/quotes.py:169-179` (pricing raises `ERR_PRICE_BELOW_COST_FLOOR` before the supersede/store/`open_quote_id` block; traces to the TestCostFloor assertion fix `[]` → `[setup quote id]`).

### Step-7 items that produced NO edit (with justification)

- **Deleted test** (`test_missing_weather_beats_past_date`): PRD already uniquely determines the outcome — §2.7 evaluates lazy flips "at the moment the relevant resource is loaded or acted upon", §3.5 settles a past-dated sheet with no active work orders to `COMPLETED`, and §3.5's numbered gates put the sheet check (gate 2 → `ERR_ROUTE_SHEET_NOT_SCHEDULABLE`) before the weather gate (gate 3); §2.11 puts state legality ahead of weather. The deleted scenario is unreachable under any PRD-faithful reading. Prose kept verbatim.
- **Test fixture fixes** (weather-precedence fixture date, past-date fixture anchoring, `get_material_lot` import): pure test bugs; assertions unchanged; no PRD silence.
- **`_release_booking` impl fix** (detach before recompute): an implementation bug fixed to match behavior the PRD already pins — §3.5 "the old sheet's booked area and drive minutes shrink" plus §2.10's aggregate definition. No observable choice was left open by the PRD. Prose kept verbatim.

### Per-edit pre-edit search log

**Edit B (`next_seal_eligible_on` time-of-day):**
- (a) Subject: computation, storage format, and consumption of the property seal-cycle projection set at work-order completion.
- (b) Paths enumerated: writer `implementation/routes/work_orders.py:653-666` (`complete_work_order` — the only writer); sole reader `work_orders.py:265-271` (schedule gate 5 compares only `.date()` — unaffected); passthrough serializer `implementation/routes/properties.py:26-27`; `middleware.py:197-209` `add_months` day-clamping; §3.10 warranty `expires_on` at `work_orders.py:648` uses date-only formatting — wording deliberately scoped to `next_seal_eligible_on` so no universal month-arithmetic claim is made.
- (c) Wording adjustment: chose "calendar months added to the completion timestamp itself, with the completion's time of day preserved" (scoped to the one field) instead of any broader phrasing, to avoid mis-describing the date-only warranty `expires_on` path.

**Edit A (supersession only on successful create):**
- (a) Subject: quote-creation side effects (supersession of the prior open quote, `open_quote_id` re-point, property `version` increment, quote persistence) when the create is rejected.
- (b) Paths enumerated: `implementation/routes/quotes.py:93-180` (`create_quote`) — every rejection occurs before the supersede block (172-175), the store (177), and `touch(prop)` (178-179), so the claim holds universally within the endpoint. Other supersession paths checked and excluded: `accept_quote` (quotes.py:361-366), assessment supersession (`routes/assessments.py:123`), lazy quote expiry (`services.py:233-247`). Cross-checked PRD §2.6's OCC rationale sentence — no conflict.
- (c) Wording adjustment: scoped the sentence explicitly to "a create" (not "any quote operation") because `patch_quote` (quotes.py:229-267) mutates in-memory scope fields before its own pricing raise — a broader claim about rejection atomicity would have mis-described the PATCH path. Also added the parenthetical "(including the cost-floor rejection above)" to anchor the sentence to the step-7 site.

## Step 9: Complete PRD — 2026-08-13T19:00:00.000Z

**Source vs output:** `PRD_FINALIZED.md` (370 lines, 52,686 chars) → `PRD_COMPLETED.md` (370 lines, 57,516 chars; **+4,830 chars**, 0 net line change — all edits are in-paragraph inserts/revisions, no new sections).

**Counts:** 22 ambiguity-pins, 6 mismatch-revisions (28 edited passages total).

**Changes** (PRD section — kind — class — what — impl ref):

- §2.1 — insert — ambiguity — Customer list endpoints filter to own resources instead of rejecting — implementation/routes/properties.py:63, quotes.py:187-189, work_orders.py:87-89, invoices.py:48-51, warranty.py:58-60
- §2.3 — insert — ambiguity — `has_more` = `offset+limit < total_count`; out-of-range/non-integer limit/offset → `ERR_INVALID_REQUEST` 400 — implementation/response.py:32, middleware.py:148-170
- §2.7 — insert — ambiguity — clock-set responds 200 with `data.current_utc`; bad `to_iso8601` → `ERR_INVALID_REQUEST` — implementation/routes/clock_admin.py:13-26
- §2.9 — insert — ambiguity — `DEPLETED` fires only at on-hand exactly 0 with no reservation; waste recordable in any status, uncapped by on-hand; quarantine lawful only from `RECEIVED`/`IN_USE` (else `ERR_MATERIAL_LOT_UNAVAILABLE`) — implementation/services.py:320-325, routes/material_lots.py:99-127
- §2.11 — revise — mismatch — existence of referenced identifiers now precedes customer ownership (impl returns 404 before 403 everywhere) — implementation/routes/quotes.py:300-306, warranty.py:97-104, invoices.py:99-105
- §2.11 — revise — mismatch — added exception: quote creation evaluates `expected_property_version` staleness before pricing, so it beats the cost floor — implementation/routes/quotes.py:142-169
- §3.1 — insert — ambiguity — material field ranges (coverage>0; `max_precip_probability_pct` int 0–100; cure/reapplication/warranty months and price positive ints) and lot field rules (delivered>0, unit_cost int, `received_on` YYYY-MM-DD, threshold ≥0) — implementation/routes/materials.py:46-56, material_lots.py:51-56
- §3.1 — insert — ambiguity — calendar-month addition for `next_seal_eligible_on` clamps day to shorter target month — implementation/middleware.py:197-210, routes/work_orders.py:661-665
- §3.2 — insert — ambiguity — `pothole_count` must be an integer — implementation/routes/assessments.py:55
- §3.3 — insert — ambiguity — pinned assessment must be usable at create (lazy expiry → `ERR_ASSESSMENT_EXPIRED`; non-`SUBMITTED` → `ERR_ASSESSMENT_NOT_USABLE`); missing `stripe_linear_ft` → `ERR_INVALID_REQUEST` — implementation/routes/quotes.py:121, 136-137
- §3.3 — insert — ambiguity — PATCH may alter the four scope flags, `coats`, `material_id`, `stripe_linear_ft`, `discount_pct` — implementation/routes/quotes.py:224-253
- §3.3 — insert — ambiguity — lazy quote expiry also runs on plain reads (any role), silently flipping to `EXPIRED` without error — implementation/routes/quotes.py:206
- §3.5 — revise — mismatch — crew `active` flag enforced at scheduling (gate 2), not at sheet creation (impl creates sheets for inactive crews); `daily_capacity_sqft` positive integer — implementation/routes/route_sheets.py:37-66, work_orders.py:253-256
- §3.5 — revise — mismatch — gate 2: nonexistent route sheet → `ERR_ROUTE_SHEET_NOT_FOUND` 404, not `ERR_ROUTE_SHEET_NOT_SCHEDULABLE` — implementation/routes/work_orders.py:243-245
- §3.5 — insert — ambiguity — window-hour sanity (incl. non-integer hours → same error) enforced before capacity/drive gates — implementation/routes/work_orders.py:116-127, 273-290
- §3.5 — insert — ambiguity — gate 10: nonexistent lot → `ERR_MATERIAL_LOT_NOT_FOUND`; lot/quote material mismatch → `ERR_INSUFFICIENT_MATERIAL` — implementation/routes/work_orders.py:311-331
- §3.5 — insert — ambiguity — reschedule carries material lot and `vehicles_to_move` over (not in payload); gates incl. sufficiency run against pre-release state; OCC last; then release→apply — implementation/routes/work_orders.py:301-310, 425-436
- §3.5 — insert — ambiguity — cancel nulls `route_sheet_id`/`material_lot_id` but retains `scheduled_date`, window hours, drive estimate — implementation/routes/work_orders.py:225-226, 693-701
- §3.5 — revise — mismatch — lazy closure restricted to `OPEN`/`PUBLISHED` sheets with active states enumerated; `WEATHER_HOLD` sheets never close lazily — implementation/services.py:274-288
- §3.6 — revise — mismatch — `ERR_PLAN_NOT_NOTICABLE` → `ERR_PLAN_NOT_NOTIFIABLE` (matches §5 catalogue and impl) — implementation/routes/displacement_plans.py:76, errors.py:63
- §3.7 — insert — ambiguity — start preconditions evaluated in narrated order (status → date → displacement → weather → lot), so a wrong date beats missing weather data — implementation/routes/work_orders.py:486-516
- §3.8 — insert — ambiguity — `stall_count` must be a non-negative integer else `ERR_INVALID_REQUEST` — implementation/routes/work_orders.py:723-725
- §3.9 — insert — ambiguity — `line_items` entries are `{label, amount_cents}`, in-scope lines only in seal/crack_fill/patch/striping order, plus a final `mobilization` entry always present (0 when waived) — implementation/services.py:111-140
- §3.10 — insert — ambiguity — approve/deny require `INVESTIGATING`, else `ERR_CLAIM_NOT_OPEN` — implementation/routes/warranty.py:191-193
- §3.10 — insert — ambiguity — warranty `expires_on` month addition uses the same end-of-month day clamping as §3.1 — implementation/routes/work_orders.py:648
- §3.11 — insert — ambiguity — `precip_probability_pct` integer 0–100 — implementation/routes/weather.py:44-46
- §3.11 — insert — ambiguity — utilization `month` param required as `YYYY-MM` (else `ERR_INVALID_REQUEST`); response fields `month`, `capacity_sqft`, `projected_sqft`, `realized_sqft`, `projected_utilization_pct`, `realized_utilization_pct` — implementation/routes/crews.py:75-108
- §4 — revise — ambiguity — work-orders list filters named (property, quote, route sheet, material lot, warranty claim, execution status) — implementation/routes/work_orders.py:90-94
- §4 — revise — ambiguity — warranty-records list also filterable by status — implementation/routes/warranty.py:61-69

**Notable judgments:** (1) The §2.11 vs §3.5 tension on "existence before state" was left as-is because §3.5's numbered gates already pin work-order-state-before-sheet-existence for scheduling, matching impl. (2) The general position of body-shape `ERR_INVALID_REQUEST` 400s within the §2.11 priority was deliberately left unpinned because the implementation itself is not uniform there, so pinning would have invented behavior. (3) All pricing formulas, tier boundaries, rounding order, cure projection, weather gating/tie-breaking, hold cascade, ADA table, and OCC payloads were verified to already match the PRD uniquely — no changes needed there.
