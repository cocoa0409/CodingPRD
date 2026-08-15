# Worklog — task_1747_mobile_car_wash_fleet_washing_service

## Step 1: Create Task Directory — 2026-08-14T12:57:00.000Z

Task directory `tasks/task_1747_mobile_car_wash_fleet_washing_service/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline invoker; Step 1 treated as DONE per instructions. Verified both exist and are empty.

## Step 2: Generate Scaffold — 2026-08-14T13:43:00.000Z

**Task**: `/home/ubuntu/github/CodingPRD/tasks/task_1747_mobile_car_wash_fleet_washing_service/` — Mobile Car Wash & Fleet Washing Service, generated fresh from the scenario (no sibling tasks consulted).

**Counts:**
- **Entities: 15** — Customer, Site, Vehicle, Van, Technician, FleetContract, Subscription, WashOrder (self-referential `rewash_of_id`), Route, RouteStop (many-to-many junction), InspectionReport, QualityAudit (immutable, `common_fields: false`), DamageClaim, ComplianceIncident, Invoice
- **State machines: 13** — including WashOrder (cyclic weather-hold loop + independent billing dimension on the same row), Subscription (ACTIVE↔PAUSED counter-bounded cycle), DamageClaim (fork: APPROVED→PAID vs DENIED), Invoice (DRAFT→ISSUED→DISPUTED→VOID loop), Route (PUBLISHED→DRAFT revert)
- **Calculation rules: 11** — dual variants on two entity domains (wash quote booking-vs-completion; invoice PROJECTION-vs-FINAL), per-line rounding pinned for loyalty credits, evaluation-order pinning for the claim-credit cap, conservation invariants for van water / route vehicle slots / subscription calendar
- **Validation rules: 33** (unique priorities; the one shared priority-6 pair — generic state vs route-locked — carries an explicit tie-break note)
- **Endpoints: 61** (flat topology under `/fleet-wash`, filtered-list GETs cover every FK's reverse reachability, plus `/_clock/set_current_utc` with the mandatory `2026-08-01T00:00:00Z` default and `/ops/run-daily` sweep)
- **Error catalog: 33**
- **§1.8 difficulty instances: 26** — every rule ≥2: dual_variant 2, combinatorial_formula 3 (modes a, b, c each), non_linear_state_machine 3, transitive_cascade 2 (weather freeze depth-3, compliance confirm depth-3, different triggers), priority_pair 3 (state×safety, referential×fiscal, safety×temporal), boundary_precision 4 (32°F, exactly-10-vehicle tier, empty-period minimum, exactly-72h claim window), cross_entity 3 (Order×Site, Claim×InspectionReport, Order×Subscription), temporal_overlap 3 (half-open site windows, 30-min buffered technician gaps, aggregate van water capacity), compensating_invariant 3 (water budget, vehicle slots, subscription calendar)
- **§1.9 corner instances: 56** (55 active + 1 `excluded_because` stub) across all nine taxonomy sections
- **Total: 1130 structured test-recipe calls**, all placeholder-closed

**Design decisions of note:**
1. **OCC concurrency (3 rules)**: stop-add on Route.version, reschedule on WashOrder.version, amend on FleetContract.version — all true create-with-supersede races per §1.2.1's serial-observability filter; everything else demoted to state preconditions.
2. **Added `Route.shift_start_at`** (optional, default 08:00Z) after rule replay exposed that a fixed shift start made the technician-buffer rule untestable (every second same-day route would collide at 08:00). This keeps the buffer boundary (exactly 30 min admitted, 15 rejected) cleanly reachable.
3. **InspectionReport SUBMIT allowed through COMPLETED** so the DamageClaim×InspectionReport state-dependency contrast (DRAFT doesn't block APPROVE, SUBMITTED does) is reachable.
4. Every formula-derived assert is a pre-computed literal (verified by executing the formulas in Python: 31500/29925 quote divergence, 34020 reclaim quote, 609-vs-608 rounding trap, 263250/65813/197437 invoice with capped claim credits, 400000 early-termination fee, 2026-09-10/2026-09-17 pause extensions).
5. Segregation of duties on damage claims (approver ≠ payer) works over opaque QualityAuditor ids, so it's black-box testable.

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` Additional manual audits passed: forbidden-vocabulary scan clean, instance names unique across both design files, all `grounds:` refs resolve into §1.1–§1.6.

## Step 3: Copy Shared Files — 2026-08-14T13:44:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1747_mobile_car_wash_fleet_washing_service/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-14T14:00:00.000Z

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1747_mobile_car_wash_fleet_washing_service/workspace/PRD.md` — **356 lines**. Ends at §5 with no audit footer.

**Section list:**
- §1 Introduction (2 paragraphs)
- §2 Global Specifications (10 subsections): 2.1 RBAC · 2.2 API Response Structure (byte-identical to the canonical block, 1846/1846 chars) · 2.3 Pagination · 2.4 Common Resource Properties · 2.5 The Logical Clock · 2.6 Validation Cascade and Check Ordering · 2.7 Optimistic Concurrency Control · 2.8 Van Water Accountability · 2.9 Money, Units, and Rounding · 2.10 Resource Topology, Retrieval, and Cascades
- §3 Business Logic & Workflows (9 subsections): onboarding assets · commercial agreements · booking/quoting/confirming · route & stop planning · day-of-service execution · weather & daily sweep · water compliance · quality/claims/rewash · fleet billing
- §4 Endpoint Definitions (4-column table, 61 rows = 61 scaffold endpoints)
- §5 Error Code Catalogue (2-column table, 33 rows = 33 scaffold errors)

**Coverage audit (all traceable, no gaps):**
- §1.1 entities: 15/15 in prose; all 113 required field/input/query/path tokens appear in backticks (mechanically verified). QualityAudit's `common_fields: false` exception (only `id` + `created_at`) stated in §2.4.
- §1.2 state machines: 13/13, including every transition, all 75 enum/state values present verbatim, and the WashOrder billing-dimension note.
- §1.3 calculations: 11/11 in precise prose — tiered quote (both variants, pinned evaluation order, boundary phrasing), stop planning, water budget (conserved quantity), discharge gate (adequacy checked first, strictly-greater cap), invoice billing (per-line rounding pinned, zero-order period bills the minimum), claim-credit cap (derived from `billed_cents`, never `net_due_cents`), early termination (worked example 2026-08-14 → 400,000 cents), pause accounting (calendar conservation), weather policy (32/33 °F and 60/59 % boundaries), audit scoring (80 exactly passes), guarantee windows (exactly-72h allowed; held exactly 14 days not expired).
- §1.4 validations: 32/32 — §2.6 states the 12-tier ascending-priority cascade including the shared-priority-6 tie-break (route state before wash-order state on stop add/remove); per-endpoint guard chains restated in §3 (CONFIRM §3.3, stop append §3.4, PAUSE §3.2, APPROVE/MARK_PAID §3.8, REINSTATE §3.7, generate §3.9).
- §1.5 endpoints: 61/61 in §4; §1.6 errors: 33/33 in §5 and every error id mentioned in §2/§3 prose; §1.7 roles: 6/6 with identity semantics (Customer/Technician entity-backed, four opaque roles with where `X-User-ID` is recorded).
- Concurrency rules: 3/3 in §2.7 (`expected_route_version`, `expected_wash_order_version`, `expected_fleet_contract_version` → `ERR_STALE_VERSION` HTTP 412), stale-version framing only.

**Hard contract reports:**
- Contract 1 (field coverage): 113 required, 113 present, 0 missing — PASS
- Contract 2 (rule coverage): all categories above expressed — PASS
- Contract 3 (§3 path purity): 625 backtick tokens scanned, 0 paths / 0 bare HTTP methods / 0 method+path tokens — PASS

**Wording decisions of note:**
1. Pause-minimum mapping: the state machine groups the 7-day minimum under `ERR_PAUSE_DURATION_EXCEEDED`, but validation p20 and the error catalog map `pause_days` < 7 to `ERR_PAUSE_LIMIT_EXCEEDED`; the PRD follows the validation table/catalog.
2. `ERR_OPEN_COMPLIANCE_INCIDENT` scoped to the manual REINSTATE event only; system auto-reinstatement on incident resolution is phrased as conditional firing (matches `applies_to`).
3. Van-conflict asymmetry made explicit: any non-terminal route blocks MAINTENANCE_START; only PUBLISHED/LOCKED routes block LOAD_WATER.
4. Constants kept in native units (cents, gallons, minutes) with boundary-exact phrasing ("at least twenty", "exactly thirty is allowed"); no fuzzy quantifiers, no operator syntax (mechanically scanned).
5. Lifecycle event names (`CONFIRM`, `SKIP`, etc.) appear as backticked enum values of `event_type` in §3 — needed as request payload values and not HTTP methods/paths.
6. §4 uses "All" (defined in the lead paragraph) for the six-role GET endpoints to keep the table minimal.

The two difficulty/corner design files were not opened or referenced; no sibling tasks were consulted.

## Step 5: Generate Unit Tests — 2026-08-14T14:30:00.000Z

Generation complete. Final report:

## test_helpers/ inventory (9 files, 1617 lines)
- `__init__.py` — barrel export (framework generics + PRD-specific)
- `types.py` — 15 entity TypedDicts (QualityAudit correctly omits `updated_at`/`version` per common_fields: false), 22 status/enum classes, `UserRole`
- `api_client.py` — `ApiClient(GenericApiClient)` with 61 methods, one per PRD endpoint row; module-level `api_client`
- `api_errors.py` — `ApiErrorId` enum (33 errors) + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — 15 per-entity assertions + `assert_van_water_budget` conserved-quantity checker
- `factories.py` — 15 payload factories, input fields only, auto-unique plates/emails
- `constants.py` — retail rate card, discount tiers, water gallons/recovery, planning minutes, all thresholds
- `test_users.py` — `TEST_USERS` for all 6 roles + per-instance builders `make_customer_headers` / `make_technician_headers` / `make_auditor_headers`
- `fixtures.py` — composite setup: customer/site/vehicle hierarchies, order lifecycle chains (CONFIRM→stop→PUBLISH→ARRIVE→START→COMPLETE), OCC-aware `add_stop_to_route` (re-reads route version), claim review/approve/pay chains, incident confirm cascade, invoice generation

## test_suite/ inventory (11 files, 2978 lines)
- `conftest.py` — session `api` fixture + one fixture per role
- `test_01_booking_and_pricing.py` (9 tests) — quotes, tiers, surcharge, initial state, rewash pricing, immediate consistency
- `test_02_fleet_billing.py` (12) — PROJECTION vs FINAL, per-line rounding, claim-credit cap order, zero-order minimum, PREVIEW lockdown, dispute/void, duplicate FINAL, early termination fee
- `test_03_order_lifecycle_and_routes.py` (16) — weather-hold cycle, billing dimension, water/vehicle-slot conservation, stop planning, terminal lockdown
- `test_04_weather_and_compliance.py` (10) — freeze cascade, incident-confirm cascade, 32°F boundary, rain advisory, 14-day hold expiry
- `test_05_capacity_and_scheduling_guards.py` (11) — half-open site windows, 30-minute tech buffer, water/vehicle capacity equality, discharge cap, route-creation guards
- `test_06_subscriptions.py` (8) — pause cycles, counters, calendar conservation, 90-day budget, third-pause, duplicate guard
- `test_07_claims_and_audits.py` (14) — claim fork, inspection gating, 72h windows, SoD, audit 79/80 boundary
- `test_08_validation_priority_and_occ.py` (10) — three priority pairs + isolated-rule counterparts, both OCC parents, body-shape, auth
- `test_09_rbac_and_cross_entity.py` (9) — site/subscription/suspension dependencies, role denials, ownership
- `test_10_envelope_and_creation.py` (6) — creation defaults, enum/FK rejection, error envelope, pagination

## Totals and coverage
- **105 tests total**: 52 queue A + 53 queue B.
- **Queue A (§1.8): 26/26 instances translated, each with exactly 2 tests. 0 skipped.**
- **Queue B (§1.9): 55 non-stub instances → 53 translated, 2 skipped** (gaps left as gaps, no skip/xfail markers):
  - `Corner/entities/wash_order_computed_quote_input_ignored` — the recipe posts client-supplied `quote_cents`/`vehicle_count` junk and expects 201 with server-computed values; PRD never states unknown/extra fields are ignored, so a faithful PRD-only reader could reject them with `ERR_VALIDATION`. Fails unique derivability.
  - `Corner/endpoints/fk_reverse_filtered_lists` — asserts `GET /sites?customer_id=` / `?site_id=` filtering; PRD §4's locator table never names these query parameters, so the rule is not verbatim-covered.
- **Stub**: `Corner/cross_cutting_layers/cascade_end_to_end_weather_and_compliance` not translated; its `excluded_because` pointer to `weather_freeze_cascade` resolves to a real §1.8 instance.

## Tag verification (programmatic audit)
- Every one of the 105 tests carries **exactly one** `Design:` line as the **last line** of its docstring; 0 untagged, 0 dual-tagged, 0 tags pointing to non-existent instances.
- All 131 long PRD citations in docstrings survive literal whitespace-normalized grep of PRD.md (0 failures); no "scaffold" references in generated code; all modules compile and import against the real `prd_bench_local_runner` framework; `_request`/`validate_*` signatures verified against framework source.

## Step 6: Generate Implementation — 2026-08-14T14:45:00.000Z

All done. Final summary:

## Implementation complete — task_1747_mobile_car_wash_fleet_washing_service

### File inventory (`workspace/implementation/`)
- `start.sh` — reads `$PORT` (default 10000), binds 0.0.0.0, `exec python3 app.py` in foreground; dependency install guarded by `python3 -c "import flask"` so per-test reboots skip pip
- `requirements.txt` — flask>=3.0,<4.0
- `app.py` — Flask entry, blueprint registration, envelope-shaped 404/405/400 handlers
- `db.py` — in-memory `Store` (16 dicts + logical clock at exactly `2026-08-01T00:00:00Z` + insertion sequence); zero seeding
- `errors.py` — all 33 error IDs with HTTP statuses
- `util.py` — envelope (`meta.api_request_id/api_request_timestamp`, `response_type`, `data`), auth (`X-User-ID`/`X-User-Role`, 6 roles), pagination (`limit`/`offset`/`total_count`/`has_more`, default 10/1/100/0), ISO-8601 3-fractional-digit time, Decimal half-up money math, field validators, `touch()` (version++/updated_at on every mutation)
- `serialize.py` — exact per-entity field sets (QualityAudit without `updated_at`/`version`), computed fields (vehicle_count, is_rewash, pause counters, route counters)
- `services.py` — pricing, water budget, stop planning, cascades (site suspend, weather freeze, route cancel, rewash compensation), early termination fee, invoice building
- `routes/` — 15 resource modules + `__init__.py`

### Coverage
- **Endpoints: 61/61** (verified against Flask's url_map; the 62nd route is Flask's built-in `/static`)
- **Error catalog: 33/33** raised in code with correct HTTP statuses
- **State machines: all 13** — Customer, Site (with system transitions), Van, Technician, FleetContract (incl. OCC amend), Subscription (pause accounting), WashOrder lifecycle + independent billing dimension, Route, RouteStop, InspectionReport, DamageClaim (segregation of duties), ComplianceIncident, Invoice — with cascade side effects touching version/updated_at per §2.10
- **Calculations: all 11** — wash_quote_cents (QUOTED_AT_BOOKING/FINAL_AT_COMPLETION, tiered discount, 8% reclaim surcharge, rewash=0), stop_planning (lot setup tiers, per-class service minutes, 20-min drive), route_water_budget (Decimal, 1-dp gallons, conserved budget), discharge_projection (recovery ≥0.60 gate, strictly-greater cap), fleet_invoice_billing (per-line half-up rounding, PROJECTION vs FINAL line sets, stored quote_cents/final_cents per PRD §3.9), claim_credit_cap (25% of post-minimum billed), early_termination_fee (verified against the PRD's worked example: 400000), pause_accounting (365-day trailing window, 2-count/7-day/90-day rules, calendar conservation), weather_policy_evaluation (freeze ≤32 cascade, advisory ≥60), audit_scoring (80 pass, FAIL auto-rewash), guarantee_windows (72h claim/rewash, 14-day hold, daily sweep)

### Key ordering decisions (per PRD §2.6 pinned cascade)
OCC(412) before state(409); route state (ERR_ROUTE_LOCKED) before order state on stop add/remove; containment → discharge → certification; window conflict before reschedule-window expiry; inspection-required before site-suspended on START; duplicate-subscription before customer-suspended; pre-existing-condition before claim-cap; contract-active before invoice-exists.

### Verification
Three smoke suites (~120 assertions) covering auth/ownership, quote/final pricing, water reservation/release, window conflicts with touching endpoints, stale-version 412s, weather freeze cascade + holds + sweeps, inspection-gated start, pre-existing claim blocking, claim caps + SoD, contract lifecycle + termination fee, invoice generate/issue/dispute/void with billing-status flips, pause/resume/cancel accounting, containment/discharge/certification guards, tech travel buffer (incl. exactly-30-min allowed), water/vehicle capacity, customer suspension, pagination — all pass. Double-boot via `bash start.sh` confirmed fresh state and clock reset on every invocation.

Two real bugs found and fixed during smoke testing: `weather_freeze` compared a date object to the stored route_date string (routes never froze), and rewash orders were priced at completion instead of always 0.

## Step 7: Run Tests and Iterate — 2026-08-14T15:05:00.000Z

Clean 8-round sweep confirmed (105/105 in every round). Emitting the final Summary.

---

## Summary

**Iterations run: 2** (sweep 1: 8 rounds × 97/105 with an 8-test deterministic failure union; sweep 2 after fixes: 8 rounds × **105/105 — clean**).

**Tests deleted: none.** Every failing assertion traced to verbatim PRD prose; no PRD-silent or uniquely-underdetermined rules required deletion.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1747_mobile_car_wash_fleet_washing_service/test_helpers/assertions.py` — added `SiteStatus` to the `.types` import list. `assert_site` referenced it unimported (latent `NameError`; no current callers, found by proactive pyflakes scan).

**Fixes applied to `test_suite/`:**
- `test_03_order_lifecycle_and_routes.py` — added missing `create_fleet_contract` to the `test_helpers` import list. `_fleet_order_on_aug10()` used it unimported, failing `test_weather_hold_cycle_and_stop_remove_revert` and `test_billing_dimension_advances_independently_of_lifecycle` with `NameError` before any assertion ran.
- `test_07_claims_and_audits.py` — three changes:
  1. `_order_with_in_progress_report()`: `validate_success(api_create_report(...))` → `expected_status=201`. PRD §4 verbatim: "Operations that create new resources — including generated invoices, rewash orders, and weather evaluations — return `201 Created`"; filing an InspectionReport is a creation, and the implementation correctly returned 201. Fixed `test_draft_report_does_not_block_approval` and `test_submitted_report_blocks_same_area_approval`.
  2. `test_second_rewash_request_rejected_while_first_open`: relaxed `validate_error(resp, ERR_REWASH_IN_PROGRESS)` → `validate_error_is_one_of([ERR_REWASH_IN_PROGRESS, ERR_INVALID_STATE])` (permitted coverage correction). While the first rewash is open the original sits in `REWASH_PENDING`, so the second request fails both §2.6 tier 6 (not `COMPLETED` → `ERR_INVALID_STATE`) and tier 9 (open rewash → `ERR_REWASH_IN_PROGRESS`); §2.6's cascade ("rejected with the error from the earliest check") makes `ERR_INVALID_STATE` the cascade-literal outcome while §3.8 names `ERR_REWASH_IN_PROGRESS` for the same condition — both PRD-defensible (error-precedence collapse).
  3. Added `validate_error_is_one_of` to the import list.
- `test_08_validation_priority_and_occ.py` — two changes:
  1. Added missing `create_confirmed_order` import, fixing `NameError` in `test_containment_error_wins_when_both_violated`, `test_containment_error_fires_without_buffer_violation`, and `test_stale_version_rejected_replay_with_current_succeeds`.
  2. `test_stale_version_rejected_replay_with_current_succeeds`: `validate_success(api.add_route_stop(...))` → `expected_status=201` (latent bug unmasked once the NameError was fixed — stop-append creates a RouteStop resource, so 201 per PRD §4).

**Fixes applied to `implementation/`: none.** The implementation was PRD-faithful in every failure — all eight failures were test-artifact bugs (missing imports, wrong expected creation status, one error-precedence over-specification).

## Step 8: Finalize PRD — 2026-08-14T15:12:00.000Z

The diff is a single in-place revision. Task complete.

**Line counts:** PRD.md 356 lines; PRD_FINALIZED.md 356 lines; 0% delta (one inline revision within an existing single-line paragraph).

**Changes (one edit total):**
- §3.8 — revise — appended a cascade-precedence sentence to the customer-rewash paragraph: the rewash request's guards run in §2.6 order (`COMPLETED` state check, then the 72-hour window, then the open-rewash check), so a second rewash request made while the first is still open is rejected with `ERR_INVALID_STATE` (the original sits in `REWASH_PENDING`), and `ERR_REWASH_IN_PROGRESS` is reached only by a request whose order is still `COMPLETED` — `/home/ubuntu/github/CodingPRD/tasks/task_1747_mobile_car_wash_fleet_washing_service/workspace/implementation/routes/orders.py:307-314`.

**Step 7 items examined, no edit needed:**
- `test_helpers/assertions.py` `SiteStatus` import — pure fixture bug (latent `NameError`), no behavioral content.
- test_03 missing `create_fleet_contract` import, test_08 missing `create_confirmed_order` import — pure fixture bugs.
- test_07 report-filing 201 and test_08 stop-append 201 — already PRD-determined: §4's rule "Operations that create new resources — including generated invoices, rewash orders, and weather evaluations — return `201 Created`" is non-exhaustive, and §2.4 lists InspectionReport and RouteStop as primary resources; implementation returns 201 at `implementation/routes/reports.py:57` and `implementation/routes/routes_stops.py:248`. Step 7 itself cited §4 as the governing prose; the test-helper 200 default was the bug.

**Pre-edit search log (single edit):**
- (a) Subject: guard chain of `POST /fleet-wash/wash-orders/{id}/rewash` and the error returned when a prior rewash is still open.
- (b) Paths enumerated: `implementation/routes/orders.py:300-318` (the only `ERR_REWASH_IN_PROGRESS` raise site; order is auth → existence → ownership → COMPLETED state → 72h window → open rewash); `implementation/routes/audits.py:22-60` (FAIL-audit auto-rewash requires COMPLETED at :37, so it also yields `ERR_INVALID_STATE` during an open rewash — consistent with the invariant the edit describes); `implementation/services.py:30` (`OPEN_REWASH_STATES`, matching §3.8's existing list), `:190-218` (`create_rewash_order`), `:221-225` (`has_open_rewash`), `:161-187` (`cancel_order` compensation reverts original to COMPLETED, so a request succeeds after cancellation), `:259` (`complete_order` closes the original to CLOSED, which also fails the COMPLETED check); PRD-side cross-check against §2.6 tiers 6/8/9 and its earliest-check-wins rule, which the edit applies rather than alters.
- (c) Wording adjustments: scoped the pinned outcome to "while the first rewash is still open" (silent on post-cancellation/post-completion originals, where behavior differs); listed the three-check order exactly as implemented; phrased the last clause as "the open-rewash guard is reached only by a request whose order is still `COMPLETED`" (lexically true at orders.py:307-312) instead of claiming `ERR_REWASH_IN_PROGRESS` is unreachable.

## Step 9: Complete PRD — 2026-08-14T15:30:00.000Z

The diff is exactly as intended: 23 in-paragraph line revisions plus one inserted paragraph (2 lines) in §2.6. No sections added, no restructuring.

**Files:** `workspace/PRD_FINALIZED.md` (356 lines, 57,923 chars) → `workspace/PRD_COMPLETED.md` (358 lines, 60,960 chars). Char delta: **+3,037**.

**Counts:** 24 ambiguity-pins, 0 mismatch-revisions. Every behavior walked in `implementation/` (all 16 route modules, services.py, util.py, serialize.py, db.py, errors.py) was already uniquely pinned by the PRD except the 24 below; no passage was found where the PRD described a behavior contradicting the implementation.

- §2.1 — insert — ambiguity — only `X-User-Role` is validated at auth time; a missing/mismatched `X-User-ID` fails ownership/crew checks with `ERR_FORBIDDEN` — implementation/util.py:62-69.
- §2.2 — insert — ambiguity — `api_request_timestamp` is stamped from the logical clock — util.py:24-28.
- §2.3 — revise — ambiguity — non-integer/out-of-range `limit`/`offset` rejected with `ERR_VALIDATION` (not clamped); `created_at` ties broken by creation order; `has_more` true iff `offset` + returned items < `total_count` — util.py:272-304.
- §2.4 — insert — ambiguity — all server-set timestamps (`created_at`, `updated_at`) come from the logical clock — util.py:311-324.
- §2.5 — insert — ambiguity — clock set to exactly the supplied instant, no monotonicity enforced — routes/clock_ops.py:18-25.
- §2.6 — insert — ambiguity — on shared event endpoints, resource-level ownership is checked at load while event-dependent actor rules (START/COMPLETE lead, ARRIVE lead, report SUBMIT filer, invoice DISPUTE parties) run only after the event payload passes tier-4 validation — routes/orders.py:224-241, routes/reports.py:96-101, routes/subscriptions.py:104-112.
- §2.10 — insert — ambiguity — a `stop_id` existing only under a different route is `ERR_NOT_FOUND` for the nested path — routes/routes_stops.py:266-268.
- §3.1 — insert — ambiguity — duplicate customer `email` → `ERR_VALIDATION` — routes/customers.py:26-28.
- §3.1 — insert — ambiguity — duplicate vehicle `plate` → `ERR_VALIDATION` — routes/vehicles.py:33-35.
- §3.2 — insert — ambiguity — non-`FLEET` customer on contract creation → `ERR_VALIDATION` — routes/contracts.py:53-55.
- §3.2 — insert — ambiguity — negative `loyalty_credit_pct` → `ERR_VALIDATION`, at creation and on amendment — routes/contracts.py:50-52, 123-127.
- §3.2 — insert — ambiguity — date amendment validated against the merged pair: effective `end_date` must fall strictly after effective `start_date` — routes/contracts.py:128-136.
- §3.2 — insert — ambiguity — trailing 365-day pause window is inclusive of a `started_at` exactly 365 days back — serialize.py:97-109.
- §3.2 — revise — ambiguity — cancelling a paused subscription closes the open pause record (`ended_at`/`days` as on resume) but does not shift `next_service_date` — routes/subscriptions.py:130-144.
- §3.3 — insert — ambiguity — booking failures for vehicles not belonging to the customer and for a subscription covering none of the listed vehicles are `ERR_VALIDATION` — routes/orders.py:83-89.
- §3.4 — insert — ambiguity — technician travel buffer considers stops in `PLANNED`/`ARRIVED`/`DONE` on other non-`CANCELLED` same-date routes; overlapping planned windows conflict — routes/routes_stops.py:154-176.
- §3.5 — insert — ambiguity — report entry `notes` may be omitted, defaulting to an empty string — routes/reports.py:45.
- §3.6 — insert — ambiguity — weather-evaluation `cancelled_route_ids` in route-creation order; `held_order_ids` per cancelled route in order-creation order then unrouted held orders — services.py:308-330.
- §3.6 — insert — ambiguity — sweep's `closed_order_ids`/`expired_order_ids` each in order-creation order — routes/clock_ops.py:28-47.
- §3.7 — revise — ambiguity — incident `notes` is required; a supplied `wash_order_id` must reference an existing order (`ERR_NOT_FOUND`) — routes/incidents.py:25-32.
- §3.7 — insert — ambiguity — confirming an incident at an already-`SUSPENDED` site still confirms the incident but keeps the site's current `suspension_reason` and does not re-fire the cascade — routes/incidents.py:90-98.
- §3.8 — insert — ambiguity — claim `area` is one of the five §3.5 inspection areas — routes/claims.py:22,36.
- §3.8 — insert — ambiguity — the rewash order carries `subscription_id` null and `requires_inspection` false (not copied from the original) — services.py:197-215.
- §3.8 — insert — ambiguity — explicit `approved_amount_cents` of zero is acceptable; a negative value fails with `ERR_VALIDATION` — routes/claims.py:112-114.
