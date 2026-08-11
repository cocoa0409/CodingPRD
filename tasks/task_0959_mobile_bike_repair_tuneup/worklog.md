# Worklog — task_0959_mobile_bike_repair_tuneup

## Step 1: Create Task Directory — 2026-08-09T00:00:00.000Z

Pre-assigned output folder `tasks/task_0959_mobile_bike_repair_tuneup` with `workspace/` subdirectory already existed; Step 1 auto-index scan skipped per headless-run instructions. `workspace/INSTRUCTION.md` also already present.

## Step 2: Generate Scaffold — 2026-08-09T17:53:00.000Z

All checks pass. The scaffold package is complete and lint-clean.

## Summary

Generated three scaffold artifacts for task 959 (Mobile Bike-Repair & Tune-Up) under `/home/ubuntu/github/CodingPRD/tasks/task_0959_mobile_bike_repair_tuneup/`, targeting beyond-expert difficulty (14 entities, 51 endpoints, 33 error codes — above the Expert band of 10–15 / 20–32 / 18–30 — with density from coupling, not volume).

**SCAFFOLD.yaml** (§1.0–§1.7):
- **Complexity profile**: primary archetype temporal_windowing + secondary quota_allocation; layers optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers; flat topology, parallel state shape, self-referential pattern (callback_of_id), peer_roles.
- **Entities (14)**: Zone, Customer, Bike (e-bike battery fields), Mechanic, Van, Part, TruckStockItem, StockMovement (append-only event log, common_fields: false), ServiceTier, Subscription (dual allowance views), ServiceRequest (parallel work_status × billing_status, self-FK callback), RouteDay, RouteStop, Invoice (fully itemized computed money fields).
- **State machines (8 blocks)**: ServiceRequest work axis (QUOTED→DISPATCHED→ON_SITE→IN_SERVICE⇄ON_HOLD_PARTS cycle→COMPLETED→CLOSED, plus CANCELLED/NO_SHOW branches and a DISPATCHED→QUOTED revert), ServiceRequest billing axis (ESTIMATED→INVOICED⇄DISPUTED→PAID), Invoice (ISSUED⇄DISPUTED cycle), RouteDay (LOCK⇄UNLOCK revert + cascade auto-unlock), RouteStop, Subscription (ACTIVE⇄PAST_DUE⇄SUSPENDED cycles), Mechanic, Van.
- **Concurrency (2 true OCC races)**: route-day resequence and request reschedule, both 412 ERR_STALE_VERSION on `expected_*_version`.
- **Calculations (9)**: provisional vs final invoice pricing (dual variant, billing domain); reserved vs settled subscription allowance (dual variant, subscription domain); per-line discount rounding order (pinned, 66 vs 67 cents divergence); pre-surcharge subtotal bracket keying (evaluation-order pin); warranty window (inclusive deadline); two deliberately different overlap semantics (buffered half-open mechanic stops vs closed inclusive customer windows); truck-stock reconciliation invariant.
- **Validations (25 ordered rows)**: auth → existence → format → OCC → state → safety → temporal → constraint → referential → fiscal, with pinned intra-business ordering.
- **Endpoints (51)**: flat /v1 surface including credit-adjustments, part-usages (RESERVE/RELEASE/CONSUME), resequence, reschedule, callbacks, and `POST /v1/_clock/set_current_utc` (default 2026-05-01T00:00:00Z); every FK has a reverse-reachability GET.
- **Errors (33)**, all referenced by ≥1 validation/transition; **Roles (4)**: PlatformAdmin/Dispatcher (opaque), Customer/Mechanic (entity_backed).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml**: 19 instances across all 9 rules (2 each; 3 for combinatorial_formula covering modes a/b/c), each with structured `setup_api_calls`/`trigger` chains, captured-variable closure, and precomputed literal asserts (e.g., quote 11391 vs final 16541; surcharge 500 at subtotal 19500; 412 via `${rd_v} - 1`).

**SCAFFOLD_CORNER_DESIGN.yaml**: 44 instances (42 active + 2 excluded_because stubs) across all 9 claim-guide sections — entity defaults/system/computed fields, invalid transitions, terminal lockdown, guarded transitions, warranty/fee/boundary calculations, 12 validation-violation cases, action/computed-read endpoints, uniqueness errors, 3 RBAC denials, 2 OCC stale-version tests, filter pagination, and immediate-consistency read-back.

**Lint verdict (verbatim)**:
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(§1.5 endpoints: 51; §1.1 entities: 14; §1.8 instances: 19; §1.9 instances: 42; calls scanned: 586.) Also verified: no forbidden concurrency vocabulary, no design keys inside SCAFFOLD.yaml, no duplicate instance names across both design files, and no unreferenced error codes. Two authoring fixes were needed en route: quoting `errors[...]`/`validations[...]` grounds entries for YAML flow syntax, and renaming sub-resource GET parent placeholders to `{id}` to satisfy lint check (f).

## Step 3: Copy Shared Files — 2026-08-09T17:54:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_0959_mobile_bike_repair_tuneup/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-09T18:02:00.000Z

All hard contracts pass. Final verification of structure.

```
Field coverage check:
- entities[].fields: 86 required, 86 present, 0 missing
- endpoints[].input/request_body: 12 additional unique names (event_type, amount_cents, reason, quantity, note, action, labor_minutes, stop_ids, expected_route_day_version, expected_service_request_version, use_credit, dispute_reason, to_iso8601), all present, 0 missing
- path_params: 13 required (zone_id…invoice_id), 13 present, 0 missing
- common/envelope: id, created_at, updated_at, version, limit, offset, total_count, has_more all present
Status: PASS

Rule coverage check:
- validations[] priority ordering: global pipeline stated in §2.10; booking order (battery → window → overlap → ownership → period → usable → allowance) in §3.4; dispatch 4-error order in §2.10/§3.6; warranty-before-callback-exists in §3.8 — expressed
- concurrency_rules[]: 2 checked, 2 expressed (write op + occ field + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: 30 checked (ServiceRequest work 10, billing 4, Invoice 6, RouteDay 6, RouteStop 4, Subscription 8, Mechanic 2, Van 3) — all from/to states, preconditions, and side effects expressed, 0 missing
- calculations[]: 9 checked (provisional_quote, final_invoice pinned 8-step order, parts_line_discounts with the 333-cent example, route_surcharge brackets 10000/500/20000/1200 with inclusive lower bounds, subscription_allowance dual views, warranty_window inclusive deadline, mechanic_stop_overlap buffered half-open, customer_window_overlap closed-interval, truck_stock_reconciliation with guards and compensating invariant), 0 missing
- validations[] conditions: 25 checked, all matchable to their error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: expressed in workflow narratives (cascades, fee-invoice auto-creation, allowance settle/release, version bumps), 0 missing
- entities[].fields[] structured content: defaults (active=true, battery_certified=true, battery_health_pct=100, travel_buffer_minutes=15, ebike_only=false, nullables), enum sets, and system/computed sources reconstructible from prose
- sibling-branch symmetry: CANCEL from QUOTED/DISPATCHED/ON_SITE treated distinctly; SUSPEND vs CANCEL cascade symmetry; LOCKED/OPEN→IN_PROGRESS both stated; VOID from DRAFT vs DISPUTED distinguished
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 458
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Summary

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_0959_mobile_bike_repair_tuneup/workspace/PRD.md` — 291 lines.

**Section structure**:
- §1 Introduction (2 paragraphs, pain-point + scope angle)
- §2 Global Specifications: 2.1 Roles/auth headers with per-role `identity` translation, 2.2 verbatim response-structure block, 2.3 Pagination (limit 10/1–100, offset 0, `created_at` ascending), 2.4 Resource identity & common fields (incl. StockMovement's id+created_at-only exception), 2.5 Money/rounding (integer cents, round half up), 2.6 Logical clock (startup default 2026-05-01T00:00:00Z), 2.7 OCC (both rules with exact occ field names and ERR_STALE_VERSION/412), 2.8 Nested path resolution (left-to-right 404, all 13 path-param names), 2.9 Cross-entity cascades (version bumps, both auto-transitions), 2.10 Validation precedence pipeline
- §3 Business Logic, 9 subsections: territory/accounts/bikes → catalog & truck-stock ledger → mechanics & vans (3-hop suspend cascade) → booking (ordered validation chain, provisional quote, reschedule) → subscriptions & dual allowance views → route days/stops/resequence → on-site events & part usages → warranty callbacks → invoicing & settlement (pinned 8-step calculation)
- §4 Endpoint table: 51 rows, 4 columns only (Method/Path/Description/Roles)
- §5 Error catalogue: 33 rows, 2 columns only

**Coverage notes**: All three hard contracts PASS (field-name coverage 103/103 after mechanical diff; rule coverage walked across all state transitions, calculations, validations, OCC rules, and cascade side effects; §3 path purity clean at 458 tokens). All 33 error IDs appear in §2/§3 narrative with trigger conditions; all enum/state values verified present verbatim. The withheld difficulty/corner design files were not read.

## Step 5: Generate Unit Tests — 2026-08-09T18:25:00.000Z

All checks pass. Generation complete.

## Summary

**Task:** `task_0959_mobile_bike_repair_tuneup` — full test infrastructure + suite generated from the two design indices only.

### Test counts (80 total, all collected by pytest)

- **Queue A (Difficulty): 38 tests** — all 19 instances × exactly 2 tests each, tagged `Design: Difficulty/<rule_id>/<instance.name>`.
- **Queue B (Corner): 42 tests** — all 42 non-stub instances × 1 test each, tagged `Design: Corner/<section>/<instance.name>`.
- **Stubs not translated (2):** `Corner/state_machines/hold_parts_resume_cycle_corner` (cross-ref resolves to difficulty instance `service_request_parallel_dims_and_parts_hold_cycle`) and `Corner/errors/stale_version_error_triggerable` (cross-ref `occ_stale_resequence_returns_412` does NOT resolve to any difficulty instance — it names a corner instance; per spec this broken pointer is a corner-design bug, so the stub is skipped with no placeholder).

### Instances skipped
None. Every non-stub instance passed the PRD-first two-condition filter. Two assertions were **relaxed** rather than skipped:
- `version == 1 at creation` (in `zone_create_applies_active_default` and `customer_create_system_fields_initialized`) — PRD §2.4 pins "increments by one on every mutation" but never names the initial value, so a PRD-only reader could start at 0; the version literal was dropped, the rest of each test kept.
- `completed_at` exact string — asserted as `startswith("2026-05-01T00:00:00")` since PRD §2.4 requires three fractional digits, making the exact serialized form non-unique.

### Known upstream data bug (not propagated)
`Difficulty/dual_variant_calc/invoice_provisional_vs_final_totals` asserts `discount_cents == 1429`, which is arithmetically inconsistent with the same instance's own pinned values (1055 + 240 + 74 = 1369; subtotal 14816 and total 16541 only reconcile with 1369). The test asserts the PRD-uniquely-derived **1369**; 1429 would fail every correct implementation.

### Files written
`test_helpers/`: `types.py` (14 entity TypedDicts — StockMovement correctly omits `updated_at`/`version` per its append-only nature), `api_client.py` (all 43 endpoints), `api_errors.py` (33 error IDs registered with the framework), `assertions.py` (per-entity + allowance/invoice invariant checkers), `factories.py`, `constants.py`, `test_users.py` (shared constants for opaque roles + `make_customer_headers`/`make_mechanic_headers` builders used for every ownership/assignment-gated call), `fixtures.py` (primitive creators, event helpers, and composites: `setup_quoted_request`, `setup_dispatched_request`, `setup_in_service_request`, `setup_completed_job` with parts consumption, `setup_issued_invoice`, `setup_two_stop_route_day`), `__init__.py` barrel.

`test_suite/`: `conftest.py` + 8 files — `test_01_catalog_and_accounts.py` (9), `test_02_booking_and_windows.py` (15), `test_03_routing_and_dispatch.py` (13), `test_04_on_site_and_stock.py` (9), `test_05_job_outcomes.py` (7), `test_06_invoicing_and_payment.py` (18), `test_07_subscriptions_and_cascades.py` (6), `test_08_rbac.py` (3).

### Verification performed
- All files compile; `pytest --collect-only` yields exactly 80 tests.
- Automated audit: every test has exactly one Design tag resolving to a real instance; all 19 difficulty instances have ≥2 tests; all 42 corner instances have ≥1.
- Automated C1 check: every quoted PRD citation greps verbatim in `PRD.md` (after whitespace normalization).
- No `skip`/`skipif`/`xfail` markers; no "scaffold" mentions in generated code comments/docstrings.

### Key design decisions
- **Identity threading:** all mechanic-scoped events (ARRIVE/START_SERVICE/HOLD/RESUME/COMPLETE/MARK_NO_SHOW) and customer-owned actions (PAY/DISPUTE/own CANCEL) use per-instance headers built from the actual entity `id`; opaque roles use shared constants.
- **Priority-pair instances** are legitimately testable because PRD §2.10 ("Business rules run last") and §3.4 ("Booking enforces its checks in this order") state the order in prose; the second test for `pay_disputed_...` uses the correct-amount-on-DISPUTED variant to prove the state gate (not the amount) drives the error.
- **OCC tests use relative versions** (`rd_v - 1` / `rd_v + 1`) so they hold regardless of the initial version value.
- Fixture helpers use `get_success_data` internally so setup failures surface as clear "Setup step failed" errors.

## Step 6: Generate Implementation — 2026-08-09T18:45:00.000Z

Done. The implementation is complete and verified against two full end-to-end smoke suites (~90 assertions, all passing) plus a fresh-boot check confirming an empty store and clean restart.

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_0959_mobile_bike_repair_tuneup/workspace/implementation/app.py` — single-file Flask app (~1900 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_0959_mobile_bike_repair_tuneup/workspace/implementation/start.sh` — executable launcher; guarded `pip install` (no-op once Flask is importable), `exec python3 app.py` in foreground
- `/home/ubuntu/github/CodingPRD/tasks/task_0959_mobile_bike_repair_tuneup/workspace/implementation/requirements.txt` — `flask>=3.0`

Boot contract: reads `$PORT` (default 10000), binds `0.0.0.0`, foreground via `exec`, store is module-level dicts that start empty on every process boot — no seeding anywhere.

## Endpoint coverage

All 51 endpoints from the scaffold endpoint table: zones, customers (+bikes reverse list, credit-adjustments), bikes, mechanics (list + events), vans (list + events + stock + stock-movements), parts (+stock reverse list), stock-movements (get/list), service-tiers, subscriptions (list + events with decoupling cascade), service-requests (create/get/list, events, reschedule, callbacks, part-usages, invoice generation + invoice list), route-days (create/get/list, events, stops, resequence), route-stops (get/list, events), invoices (get, events), and `POST /v1/_clock/set_current_utc` (clock starts at exactly 2026-05-01T00:00:00Z, never wall-clock).

## Key design decisions

- **State machines**: `ServiceRequest` tracks `work_status` and `billing_status` as independent parallel dimensions on one row; the COMPLETED→CLOSED bubble-up fires inside the PAY request. RouteDay has LOCK/UNLOCK revert, START (requires ≥1 active stop), CLOSE (all stops terminal), plus the LOCKED→OPEN auto-unlock whenever a side effect empties a LOCKED day. Subscription SUSPEND/CANCEL from ACTIVE/PAST_DUE runs the decoupling cascade; CANCEL from SUSPENDED cascades nothing; REINSTATE restores no coverage. Mechanic SUSPEND runs the 3-hop cascade (PLANNED stops → UNASSIGNED, requests DISPATCHED→QUOTED, day version bumps + auto-unlock).
- **OCC**: only resequence (`expected_route_day_version`) and reschedule (`expected_service_request_version`) carry version fields; mismatch → ERR_STALE_VERSION 412, checked after body validation, before state guards, per priority order.
- **Calculation order** (pinned, PRD-faithful): provisional quote = callout + (base − per-line half-up discount), surcharge bracket keyed on pre-surcharge subtotal (<10000 → 0, <20000 → 500, else 1200; inclusive lower edges), 8% tax half-up via `Decimal`/`ROUND_HALF_UP` (no floats for money). Final invoice evaluates labor gross (incl. overage; 0 for CALLBACK/NO_SHOW), parts lines from grouped CONSUME movements, per-line discounts rounded half-up before summing (verified: two 333-cent lines at 10% → 66, not 67), then callout/subtotal/surcharge/tax/total. Cancellation and no-show auto-invoices are DRAFT with callout + tax only, surcharge 0, `is_no_show_fee` set only for no-show.
- **Overlap semantics kept deliberately asymmetric**: customer double-booking uses closed intervals (touching endpoints conflict); mechanic stop overlap uses buffered half-open intervals with only the new stop's `travel_buffer_minutes` (default 15) applied, exact touch at the expanded boundary allowed — both verified by smoke tests.
- **Validation pipeline**: auth (401) → role (403) → path existence L→R (404) → body shape/enum/unknown-field (400) → OCC (412) → generic state (409) → named state guards → business rules in PRD narrative order (booking: battery safety → window shape → customer overlap → bike/subscription ownership → period → status → allowance; dispatch: QUOTED → day OPEN → van → mechanic suspended → e-bike cert → capacity → window/overlap). Mechanic-scoped events require `X-User-ID == scheduled_mechanic_id` (403 otherwise); PAY/DISPUTE restricted to the owning customer.
- **Stock ledger**: TruckStockItem is a mutable derived view keyed by `(van_id, part_id)`; StockMovement is append-only (id + created_at, no version/updated_at) carrying both `quantity` and signed `quantity_delta` (0 for RESERVE/RELEASE/CONSUME). Sufficiency guards per spec; COMPLETE auto-releases per-request outstanding reservations via a RELEASE movement; subscription allowance settle (reserved−1, consumed+1) happens only for still-covered requests; both `allowance_remaining` and `settled_allowance_remaining` are exposed on every subscription read.

One judgment call to flag: callback eligibility when the original is not COMPLETED returns ERR_WARRANTY_EXPIRED 409 (per scaffold priority-15 grouping, which covers "original COMPLETED" under that error id) rather than ERR_INVALID_STATE.

## Step 7: Run Tests and Iterate — 2026-08-09T19:15:00.000Z

All 8 rounds: 80/80 passed, empty failure union. Clean sweep achieved.

Note: the `.deps_installed` sentinel lives inside `implementation/` — it's a build artifact, not entity data (storage remains purely in-memory dicts; the store starts empty on every boot, verified by tests across 640 fresh boots).

## Summary

**Iterations run:** 3 sweeps (24 rounds total). Iteration 1: 4 deterministic failures + infra flakes. Iteration 2: deterministic failures gone, 7 infra restart flakes. Iteration 3: all 8 rounds clean (80/80 each).

**Tests deleted:** None. Every failing assertion traced to a verbatim PRD rule; no PRD-silent or non-uniquely-derivable tests found among the failures.

**Fixes applied to `test_suite/`** (arithmetic corrections making assertions match the PRD-pinned formula — no weakening):
- `test_06_invoicing_and_payment.py::test_provisional_quote_at_creation`: expected quote 11391 → **11891**. The old value summed subtotal (10510) + tax (881) but dropped the 500 surcharge; PRD §3.4: "the quote total is subtotal plus surcharge plus tax". Implementation was already correct.
- `test_07_subscriptions_and_cascades.py::test_suspend_clears_coverage_and_releases_allowance`: pre-suspend quote 11391 → **11891** (same arithmetic slip).
- `test_07_subscriptions_and_cascades.py::test_suspend_recomputes_quote_without_discount`: pre 11391 → **11891**, post-decoupling 12352 → **12852** (11400 + 500 + 952; same dropped-surcharge slip).

**Fixes applied to `implementation/`** (`workspace/implementation/app.py`):
- `request_events()`: mechanic-scoped identity check (`X-User-ID == scheduled_mechanic_id`) now applies only when `X-User-Role` is `Mechanic`, per PRD §2.1: Dispatcher/PlatformAdmin identifiers are opaque and "the server does not compare those identifiers to any entity's `id`". Previously a Dispatcher firing START_SERVICE from QUOTED got ERR_FORBIDDEN instead of the PRD-required ERR_INVALID_STATE. Customer role remains 403 for non-CANCEL events (PRD §2.1 enumerates the customer's write verbs).
- `stop_events()`: same §2.1 correction for ARRIVE/DONE — identity comparison only for Mechanic role (previously 403'd any Dispatcher).
- Entry point: bind-retry loop (50 × 0.2s) around `app.run()` so a lingering socket in the harness's SIGKILL-then-respawn window cannot abort boot.
- `start.sh`: replaced the per-boot `python3 -c "import flask"` dependency check (a full interpreter + Flask import, ~40% of boot CPU × 640 boots) with a zero-cost `.deps_installed` sentinel file, reducing boot-time CPU pressure under the 8-way concurrent sweep plus co-tenant load on this shared 8-CPU box.

**Infrastructure finding:** the intermittent "API server could not be restarted" errors were environmental — other benchmark sweeps (task_0950, task_0955) run concurrently on the same host, producing synchronized CPU stalls (load avg ~35 observed) that pushed some server boots past the runner's fixed 15s poll window. The start.sh/boot hardening above eliminated them in iteration 3.

## Step 8: Finalize PRD — 2026-08-09T19:20:00.000Z

Step 8 complete. PRD_FINALIZED.md exists at `/home/ubuntu/github/CodingPRD/tasks/task_0959_mobile_bike_repair_tuneup/workspace/PRD_FINALIZED.md` and is a byte-identical copy of PRD.md — **zero edits** was the correct outcome.

## Line counts / delta
- PRD.md: 291 lines; PRD_FINALIZED.md: 291 lines; delta 0.0%.

## Changes
None. Every `<step_7_diff>` item traced to either (a) behavior the PRD already uniquely determines, (b) a test-suite arithmetic bug where the PRD was already correct, or (c) infrastructure invisible to the PRD.

## Per-edit pre-edit search log (all considered edits — all rejected)

**Candidate 1 — mechanic-scoped identity check on `request_events()` (Step 7 impl fix)**
- (a) Subject: scoping of the `scheduled_mechanic_id` identity comparison to `X-User-Role: Mechanic` on service-request events.
- (b) Impl paths enumerated and read: `request_events()` (app.py:1243-1332, incl. role branches at 1251-1266); `authenticate`/`authorize` (app.py:181-189); all writers/clearers of `scheduled_mechanic_id` — dispatch (app.py:1586-1606), mechanic-suspend cascade (app.py:783), cancel-from-DISPATCHED clear (app.py:1283), stop SKIP clear (app.py:1713); §4 role table row for the events endpoint.
- (c) No wording adjustment. PRD §2.1 (lines 15-17) already uniquely determines the behavior: the `scheduled_mechanic_id` comparison is stated only under the `Mechanic` role paragraph, and Dispatcher/PlatformAdmin identifiers are declared opaque with "the server does not compare those identifiers to any entity's `id`". §2.10's pipeline (auth/authorization before state checks) then uniquely yields `ERR_INVALID_STATE` for a Dispatcher firing START_SERVICE from QUOTED, and 403 for a Customer firing any non-CANCEL event (§2.1 enumerates the customer's write verbs exhaustively; CANCEL is the only one on this endpoint). Implementation now matches; PRD needed no change.

**Candidate 2 — same identity scoping on `stop_events()` (Step 7 impl fix)**
- (a) Subject: identity comparison for ARRIVE/DONE on route-stop events.
- (b) Impl paths enumerated and read: `stop_events()` (app.py:1675-1718) — comparison at 1686 is guarded by `role == "Mechanic"` and applies only to ARRIVE/DONE, not SKIP; cross-checked §3.6's SKIP prose ("available to a Mechanic or Dispatcher", no identity restriction) and §3.7's mechanic-scoped event list (arrive, start, hold, resume, complete, mark-no-show — SKIP absent).
- (c) No wording adjustment. §2.1 sentence "on-site events and stop events that are restricted to the assigned mechanic compare the request's `scheduled_mechanic_id` against `X-User-ID`" plus the opaque-Dispatcher clause determines this; SKIP's exclusion matches §3.6/§3.7. No edit.

**Candidate 3 — provisional-quote arithmetic (Step 7 test_suite fixes, 11391→11891 and 12352→12852)**
- (a) Subject: quote formula — whether the 500 surcharge enters the quote total and the tax base.
- (b) Impl paths enumerated and read: `compute_quote()` (app.py:433-447), `route_surcharge()` (app.py:425-430), and all three callsites — booking (app.py:1197), subscription-decoupling recompute (app.py:1079), callback creation (app.py:1411). Verified impl returns `subtotal + surcharge + tax` with tax on `subtotal + surcharge`.
- (c) No wording adjustment. PRD §3.4 already pins this verbatim: "The route surcharge is then selected by bracket on this pre-surcharge subtotal exactly as §3.9 defines, the 8% tax is applied to subtotal plus surcharge with half-up rounding, and the quote total is subtotal plus surcharge plus tax." The old test values dropped the surcharge — a test arithmetic bug, not PRD silence. No edit.

**Candidate 4 — boot bind-retry loop and `start.sh` `.deps_installed` sentinel (Step 7 impl/infra hardening)**
- (a) Subject: server boot resilience under the harness's SIGKILL-then-respawn cycle.
- (b) Impl paths enumerated and read: entry point (app.py:1900-1915, 50×0.2s retry around `app.run`) and `start.sh` (sentinel-gated pip install).
- (c) No wording adjustment. Neither the bind-retry nor dependency-install strategy is API-visible behavior; the PRD governs request/response semantics only. No edit.

## Step 9: Complete PRD — 2026-08-09T19:35:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_0959_mobile_bike_repair_tuneup/workspace/PRD_COMPLETED.md` is written (copied from PRD_FINALIZED.md, then 29 in-place edits; no new sections).

## Summary

**Files / sizes**
- Source: `PRD_FINALIZED.md` — 291 lines, 44,549 chars
- Output: `PRD_COMPLETED.md` — 293 lines, 48,246 chars (char-delta +3,697)

**Counts**
- Ambiguity-pins: 23
- Mismatch-revisions: 6

**Changes** (impl refs: `workspace/implementation/app.py`)

- §2.2 — insert — ambiguity — undefined path → `ERR_NOT_FOUND` 404; wrong method → 405 with `ERR_NOT_FOUND` body; unexpected failure → 500 `ERR_INTERNAL` — app.py:146-173
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_VALIDATION` 400; created_at ties broken by creation order — app.py:283-318
- §2.4 — revise — ambiguity — `version` starts at 1 on creation — app.py:324-327
- §2.6 — insert — ambiguity — all server-emitted timestamps (`api_request_timestamp`, `created_at`, `updated_at`, `completed_at`) read from the logical clock — app.py:89-96, 326, 1309
- §2.10 — insert — ambiguity — strings non-empty; integers must be JSON ints (booleans rejected); missing/unparseable body treated as empty object; body-supplied resource ids must exist else `ERR_NOT_FOUND` 404 — app.py:195-277, 340-344
- §3.1 — revise — mismatch — credit adjustment: overdraft refusal is `ERR_VALIDATION` 400 (unnamed before); success responds 201 Created (§4's general rule implied 200) — app.py:655-667
- §3.1 — insert — ambiguity — email uniqueness is exact string comparison — app.py:628-630
- §3.2 — revise — mismatch — release/consume guard is per-request (units the acting request still holds reserved on that van, capped by row `reserved`), not row-level `reserved`; quantity must be a positive integer — app.py:929, 1440-1453
- §3.3 — insert — ambiguity — ASSIGN_MECHANIC first requires the van itself `ACTIVE` (`ERR_INVALID_STATE`), then the target mechanic `ACTIVE` — app.py:851-858
- §3.3 — insert — ambiguity — mechanic named at van creation must exist but need not be `ACTIVE` — app.py:806, 809-810
- §3.4 — insert — ambiguity — booking pre-checks pinned before battery safety: reference existence (404), Customer self-booking (`ERR_FORBIDDEN` 403), inactive zone (`ERR_VALIDATION` 400) — app.py:1136-1146
- §3.4 — insert — ambiguity — new requests also carry `cancel_reason` null — app.py:1194
- §3.4 — insert — ambiguity — reschedule double-booking re-check excludes the request itself — app.py:1351-1352
- §3.5 — insert — ambiguity — `period_start`/`period_end` accepted with no ordering check — app.py:1022-1023
- §3.6 — revise — mismatch — route-day creation checks van-ACTIVE (`ERR_VAN_UNAVAILABLE`) before duplicate van+date (`ERR_ROUTE_DAY_EXISTS`); invalid calendar date → `ERR_VALIDATION` 400 — app.py:1469-1480
- §3.6 — insert — ambiguity — START with no active stops / CLOSE over a non-terminal stop → `ERR_INVALID_STATE` 409 — app.py:1531-1540
- §3.6 — insert — ambiguity — `planned_end` < `planned_start` → `ERR_MECHANIC_WINDOW_OVERLAP` — app.py:1578
- §3.6 — insert — ambiguity — resequence `stop_ids` duplicates or set-mismatch → `ERR_VALIDATION` 400; responds with the updated route day — app.py:1628-1650
- §3.7 — revise — mismatch — mechanic-scoped events bind identity only when actor role is `Mechanic`; `Dispatcher` fires them uncompared; Customer firing non-CANCEL or Mechanic firing CANCEL → `ERR_FORBIDDEN` 403 — app.py:1251-1266, 1683-1687
- §3.7 — insert — ambiguity — part-usages: van derived from the active (PLANNED/ARRIVED) stop (none → `ERR_INVALID_STATE`), positive integer quantity, response is the updated (van, part) stock row — app.py:1422, 1434-1439, 1456
- §3.7 — revise — mismatch — cancel from ON_SITE leaves `scheduled_mechanic_id` in place (only DISPATCHED-cancel clears it) — app.py:1282-1283
- §3.7 — revise — mismatch — no-show fireable by assigned mechanic or a dispatcher (was "mechanic only"); leaves `scheduled_mechanic_id` in place — app.py:1245, 1261-1266, 1324-1331
- §3.8 — insert — ambiguity — callbacks skip the battery-safety gate and customer double-booking rule — app.py:1360-1388
- §3.8 — revise — ambiguity — original not COMPLETED → `ERR_WARRANTY_EXPIRED` 409, ahead of the deadline comparison — app.py:1372-1373
- §3.8 — insert — ambiguity — callback provisional quote is 0 cents — app.py:436-437
- §3.9 — insert — ambiguity — invoice generation takes no body fields; any supplied field rejected as unknown — app.py:1729
- §3.9 — insert — ambiguity — `line_items`: parts lines in first-consumption order, then a labor line last (part_id null, sku "LABOR", quantity 1, unit/line totals = gross labor) — app.py:1750-1777
- §3.9 — insert — ambiguity — no-show/cancellation-fee invoices have empty `line_items`; every invoice carries `is_no_show_fee` (true only on no-show fee invoices) — app.py:1807-1808
- §3.9 — revise — mismatch — `dispute_reason` is optional on DISPUTE (impl never requires it) — app.py:1837-1848

All other implementation behavior (validation pipeline ordering, OCC, state machines, quote/invoice math, surcharge brackets, warranty inclusivity, cascades, allowance accounting, envelopes, endpoint/role table) was already uniquely pinned in PRD_FINALIZED.md and left untouched.
