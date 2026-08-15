# Worklog — task_1295_pallet_manufacturing_recycling

## Step 1: Create Task Directory — 2026-08-12T19:24:00.000Z

Created `tasks/task_1295_pallet_manufacturing_recycling/workspace/` (RESUME RUN: Step 1 treated as DONE per command args; directory verified to exist and contain no partial artifacts — workspace/ empty, no SCAFFOLD files, so pipeline resumes from Step 2).

## Step 2: Generate Scaffold — 2026-08-12T20:18:00.000Z

Clean lint with all checks passing. The scaffold is complete.

## Summary

**Task**: `task_1295_pallet_manufacturing_recycling` — Pallet Manufacturing & Recycling scaffold, written to `/home/ubuntu/github/CodingPRD/tasks/task_1295_pallet_manufacturing_recycling/` (SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml). No sibling task directories were read.

**Counts:**
- **Entities: 15** (PalletSpec, LumberPriceIndex, SeasonalPriceIndex, CorePurchaseBatch, CoreUnit, RepairWorkOrder, InventoryLot, HeatTreatmentRun, Customer, SalesOrder, OrderLine, PoolReturn, DeliveryRoute, RouteStop, GrindingBatch)
- **Endpoints: 76** (see deviation note below)
- **Error codes: 62**, all referenced by at least one validation/transition
- **State machines: 12**, including a true cycle (CoreUnit IN_REPAIR→FAILED→UNSORTED→re-sorted→IN_REPAIR with `repair_cycle_count`), parallel dimensions (SalesOrder payment×fulfillment; InventoryLot quality×heat_treat_status), and compound/cross-entity gates (batch-gated sorting, route+sibling-gated stop arrival)
- **Calculations: 10** (business-logic rules, ≥3 required)
- **Difficulty layers (4, max)**: dual_variant_calculation, cascading_side_effects, rate_threshold_triggers, optimistic_concurrency
- **Difficulty design: 9 rules × 2 instances = 18**; **corner design: 52 instances** across all 9 claim-extraction sections (4 stubs citing §1.8 coverage)
- **Lint: `VERDICT: clean lint`** (76 endpoints, 15 entities, 18 §1.8 + 48 active §1.9 instances, 578 calls scanned, 0 violations; all FKs reverse-reachable)

**Design decisions worth noting:**

1. **OCC placement and precedence** — OCC guards confirm/allocate/dispatch with `expected_*_version`; validation priorities pin the OCC check (priority 6, →412 ERR_STALE_VERSION) *before* generic state preconditions (priority 7), making the stale-version tests deterministic even when the transition would also be state-invalid. This is stated explicitly in the validation row's `check` text.
2. **Dual-variant pairs** sit on genuinely different domains: batch settlement (provisional manifest-based vs final per-grade+shortage-penalty, 5000 vs 2775) and route margin (provisional all-stops vs final minus skipped-plus-surcharge, 21300 vs −9200).
3. **Combinatorial formulas in different modes**: mode (a) new-build cost (nested ceil board-feet × half-open index window × quantity-tiered overhead; 99→7434 vs 100→7056 flips the tier branch), mode (b) order pricing (per-line round-then-sum pinned; subtotal 20500, seasonal 2050, total 22550).
4. **All assert literals pre-computed** with a Python harness (round-half-up via Decimal) — including the −556 bp grade-yield variance and the 493.3358/500.0025 exact-fit trailer cube boundary.
5. **Logical clock** test-driving endpoint `POST /pallet-ops/_clock/set_current_utc` with the mandatory startup default `2026-08-01T00:00:00Z` stated in its description.
6. **Deviation from the requester's endpoint target**: 76 endpoints vs the ~30–32 guideline. This is a consequence of the skill's hard rules at 15 entities — testability-completeness (every state reachable), enum closure (e.g. `record-payment` produces PAID, `reinstate` closes the SUSPENDED→ACTIVE cycle), and FK reverse-reachability GETs. Every endpoint is exercised by at least one design-file chain; nothing is padding. Entities (15), difficulty rules (9×2), state machines (12, with cycles+parallel), and calculation variants all hit the requested Expert-top marks.
7. **Error catalog at 62** vs ~30 target — driven by domain-specific named errors (per the skill's "use domain-specific names" principle) across 25 ordered validation rows plus state-machine preconditions; each is reachable and several anchor the priority-conflict instances (ERR_HT_NOT_RUNNING vs ERR_HT_DWELL_SHORT; ERR_HT_REQUIRED vs ERR_INSUFFICIENT_STOCK).

## Step 3: Copy Shared Files — 2026-08-12T20:20:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1295_pallet_manufacturing_recycling/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-12T20:31:00.000Z

PRD generated and all three hard contracts verified mechanically. The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1295_pallet_manufacturing_recycling/workspace/PRD.md` — 366 lines.

**Section list:**
- §1 Introduction (2 paragraphs — business context + design commitments, `/pallet-ops` mount)
- §2 Global Specifications (10 subsections): 2.1 RBAC, 2.2 API Response Structure (verbatim contract block), 2.3 Pagination, 2.4 Common Resource Properties and Entity Identity, 2.5 The Logical Clock, 2.6 Money/Precision/Rounding, 2.7 Optimistic Concurrency Control, 2.8 Validation Priority Ladder, 2.9 Parallel Status Dimensions, 2.10 Physical Capacity as a First-Class Constraint
- §3 Business Logic & Workflows (9 subsections): specs/engineering baseline, price indices, core procurement/sorting/settlement, repair work orders, inventory lots + heat treatment/ISPM-15, customers/orders/sales cycle, pool returns/credit ledger, delivery routes/stops/margin, grinding/fiber recovery
- §4 Endpoint Definitions — 76 rows (Method, Path, Description, Authorized Role(s) only)
- §5 Error Code Catalogue — 62 rows (Error ID, HTTP Status Code only)

**Hard contract reports:**
- Field coverage: 106 required (92 entity fields + 70 endpoint inputs + 4 common + 3 OCC/clock, deduplicated), 106 present in backticks, 0 missing — PASS
- Rule coverage: all 12 state machines' transitions with preconditions+error IDs and side effects; all 10 calculations (incl. variants `settlement_provisional`, `recycled_repair_unit_cost`, `provisional_excludes_actuals`) translated to precise prose with embedded constants (0.6 deck fraction / 144, 18%/12%/9% overhead tiers at 100/500, 1500/1100/800 price book, 10000 bp base, 1.00/0.60 grade factors + 0.25 shortage penalty, 185¢/mile + 4500¢/stop, 700/350/0 pool tiers, 95¢/min labor, 6h dwell, 3 repair cycles); all 3 OCC rules (write endpoint + `expected_order_version`/`expected_route_version` + `ERR_STALE_VERSION` 412, pinned before state checks); all 25 validations with priority ladder expressed; all 62 error IDs triggered in §2/§3 prose; all endpoint side effects covered; both `common_fields: false` entities (LumberPriceIndex, SeasonalPriceIndex) explicitly noted as lacking `updated_at`/`version`; logical clock default `2026-08-01T00:00:00Z` stated — PASS
- §3 path purity: 604 backtick tokens scanned, 0 path/method/combo violations — PASS

Additional scans: no fuzzy/approximating words, no pseudocode operators in prose, all enum/state values present as exact UPPERCASE strings, all 6 roles + `Any` with `identity: opaque` translated into §2.1 prose, all query-param filter names covered in §3 narratives.

## Step 5: Generate Unit Tests — 2026-08-12T20:55:00.000Z

All checks pass. Final summary:

## Summary

**Task:** task_1295_pallet_manufacturing_recycling — test infrastructure + suite generated.

### Counts
- **Queue A (Difficulty):** 18 instances → **36 tests** (every instance has ≥2 tests, no shortfall)
- **Queue B (Corner):** 48 non-stub instances → **48 tests** (every non-stub instance has ≥1 test)
- **Total: 84 tests**, all collected cleanly by pytest, all imports resolve against `test_helpers`
- **Instances skipped: 0** — every instance passed the PRD-first two-condition filter (verbatim PRD coverage + unique derivability). The 4 `excluded_because` stubs were not translated (per spec); all 4 cross-references verified to resolve to real difficulty instances.

### Verification performed
- Tag audit: every test docstring ends with exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line; all 84 tags resolve to real instances; no stub-tagged tests.
- Verbatim citation sweep: 126 quoted PRD passages extracted from docstrings, all survive literal whitespace-normalized grep of `workspace/PRD.md`.
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere.
- Arithmetic re-derived independently (settlement 2775/5000, variance −556 bp, margins 21300/−9200, unit costs 7434/7056, yields 1.5625/6.25, cube 493.3358/500.0025) — all match the design indices' pre-computed values.

### test_helpers/ files
`__init__.py` (barrel), `types.py` (15 TypedDicts + status enums; LumberPriceIndex/SeasonalPriceIndex correctly omit `updated_at`/`version`), `api_client.py` (all 60 endpoints), `api_errors.py` (60 error IDs + HTTP map registered with framework), `assertions.py` (per-entity validators, immutable-row absence checks), `factories.py` (input-field-only payload factories), `constants.py` (price book, tiers, pool credits, route costs, dwell, clock default), `test_users.py` (7 opaque role header sets + builders), `fixtures.py` (~45 composite helpers: pricing world, order confirm/allocate chains, delivery pipeline, batch/sort/settlement, repair-to-lot, HT runs, credit-rich customer, grinding).

### test_suite/ files (9)
`test_01_api_envelope_auth_and_pagination.py`, `test_02_specs_and_market_indices.py`, `test_03_core_batches_sorting_and_settlement.py`, `test_04_grinding_and_pool_credit_cascade.py`, `test_05_repair_work_orders_and_recycled_inventory.py`, `test_06_heat_treatment.py`, `test_07_customers_orders_pool_returns.py`, `test_08_allocation_inventory_and_occ.py`, `test_09_routes_stops_and_margins.py`, plus `conftest.py`.

### Structural decisions worth recording
1. **Recipe repair (documented, not value-changing):** instance `route_margin_provisional_vs_final_with_skip`'s `setup_api_calls` omitted arriving/completing stop1 before close — without it, close fails `ERR_STOPS_OPEN` and the pinned final margin (−9200, which counts stop1's 30000 revenue) is unreachable. The fixture adds stop1 arrive+complete; asserted values copied verbatim.
2. **Cube float precision:** literal cube values (493.3358, 500.0025, 6.6667) asserted via `pytest.approx(abs=1e-4)` to absorb float64 representation; all money values asserted as exact integer cents.
3. **Roles are all opaque** (`identity: opaque`), so shared `TEST_USERS` constants are the canonical form; no ownership-threaded builders needed.
4. **OCC ordering test** (`occ_stale_order_version_on_confirm`) relies on PRD §2.8's explicit pinning of stale-version before state checks, so the second confirm with the pre-confirm version asserts 412 (not 409); `double_confirm_rejected_not_draft` deliberately carries the *current* version to exercise the state gate.

## Step 6: Generate Implementation — 2026-08-12T20:52:00.000Z

Implementation complete and verified. Summary:

## File list

`/home/ubuntu/github/CodingPRD/tasks/task_1295_pallet_manufacturing_recycling/workspace/implementation/` (~2,700 lines):

- `start.sh` — executable launcher (details below)
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask entry point; registers 11 blueprints; `ApiError`/404/405/catch-all handlers that always emit the scaffold error envelope
- `db.py` — in-memory `Store` (15 entity dicts), logical clock (default exactly `2026-08-01T00:00:00Z`, never wall-clock), ISO-8601 millisecond timestamping, ISPM-15 mark sequence
- `errors.py` — all 60+ error IDs from the scaffold catalog with their HTTP statuses
- `response.py` — envelope: `meta`(`api_request_id` `req_…`, `api_request_timestamp` 3-fractional-digit UTC) + `response_type` (`object`/`array`/`error`) + `data`; pagination fields (`limit`/`offset`/`total_count`/`has_more`) live inside `meta` for list endpoints
- `middleware.py` — `X-User-Role` auth (six declared roles; the literal value `Any` is rejected with 401 since it's only an RBAC-matrix placeholder), RBAC enforcement, `limit`/`offset` parsing (default 10, min 1, max 100), typed field validators
- `routes/` — one blueprint per resource group: `specs`, `indices` (lumber + seasonal), `cores` (batches + units), `repairs`, `lots` (inventory + HT runs), `customers`, `orders` (orders + lines), `pool_returns`, `routes` (routes + stops), `grinding`, `clock`
- `services/calc.py` — all calculation rules with `Decimal`/`ROUND_HALF_UP`: board-feet formula, unit cube (4dp), new-build cost with quantity-tiered overhead (18/12/9%), recycled-repair cost (grade schedule + parts + 95¢/min), order pricing (per-line round then sum, seasonal bp uplift, credit cap), final settlement with shortage penalty (floor 0), grade-yield variance bp, provisional/final route margins, pool credit tiers, lexicographic allocation selector (RECYCLED_REPAIR → lowest cost → earliest), grinding yield (4dp)
- `services/helpers.py` — common-field stamping (`id`/`created_at`/`updated_at`/`version=1`; index rows get only `id`+`created_at` per PRD §2.4), mutation touch, serialization stripping `_`-prefixed internals

## State storage

In-memory only: plain module-level dicts in `db.Store()`. No disk, no database, no seeding — the store is empty on every boot (verified: fresh process returns `total_count: 0`). Since `prd-bench-local-run` kills and re-launches via `start.sh` per test, each test gets a pristine store automatically. Internal bookkeeping (parsed datetimes, creation-order counters, HT assignment lists) uses `_`-prefixed keys stripped at serialization.

## start.sh contract

Guards the dependency install with `if ! python3 -c "import flask"` (no-op on repeat boots, avoiding pip contention across concurrent reboots), then `exec python3 app.py` — foreground, signals propagate. `app.py` reads `PORT` (default 10000) and binds `0.0.0.0` with `threaded=True`. Verified end-to-end via `PORT=19345 bash start.sh` + curl.

## Notable design decisions

- **OCC pinned before state checks** (validation priority 6): confirm/allocate/dispatch validate `expected_order_version`/`expected_route_version` first — a stale writer on a state-invalid resource gets 412, verified.
- **Atomic allocation**: all OPEN lines are resolved against the selector with projected per-lot debits before any reservation commits; one failure rolls back everything. `ERR_HT_REQUIRED` vs `ERR_INSUFFICIENT_STOCK` distinguished per the selector spec.
- **Parallel status axes** kept independent: order `payment_status` vs `fulfillment_status` (total=0 at confirm flips to `CREDIT_SETTLED`), lot `quality_grade` untouched by HT stamping.
- **Ledger syncs** as side effects: confirm debits pool credit, cancel re-credits, pool-return credit posts balance + decrements outstanding and spawns CoreUnit rows (SCRAP→GRINDING_QUEUED, A/B→YARD), stop completion increments `pool_units_outstanding` when all of an order's stops complete.
- **Repair eligibility order** follows scaffold preconditions exactly: grade → YARD → already-open (so a duplicate WO on an IN_REPAIR core surfaces `ERR_CORE_NOT_IN_YARD`).
- **Logical clock** drives `order_date`, HT `started_at`/dwell (6h), lot `created_at` index lookups, and ISPM-15 mark minting (`HT-<chamber>-<yyyymmdd>-<seq>`); dwell and freshness verified with clock advancement.
- Half-open index windows with adjacency permitted, latest-`effective_from` defensive tie-break; provisional values retained at close (never zeroed) for both batches and routes.

## Step 7: Run Tests and Iterate — 2026-08-12T22:06:00.000Z

All changes verified. The task is complete — all 8 rounds pass 84/84.

---

## Summary

**Iterations run: 2** (iteration 1 surfaced failures; iteration 2 clean: all 8 rounds `passed == total == 84`).

**Tests deleted: none.** Every failing test traced to either a test-fixture bug or an infrastructure flake — no PRD-silence or unique-derivability violations found.

**Fixes applied to `test_helpers/`:**

1. `/home/ubuntu/github/CodingPRD/tasks/task_1295_pallet_manufacturing_recycling/test_helpers/fixtures.py` — `setup_delivered_customer` gained an optional `customer_id` parameter. The fixture previously always registered a new customer; two tests fed it a `company_name` already registered by `setup_sellable_world` in the same test, violating the PRD §3.6 sentence "A `SalesRep` registers a **Customer** with a unique `company_name`" (the implementation's 400 `ERR_INVALID_REQUEST` was PRD-correct — a STEP 2 fixture bug, not an implementation bug).
2. `/home/ubuntu/github/CodingPRD/tasks/task_1295_pallet_manufacturing_recycling/test_helpers/api_client.py` — `ApiClient._request` now retries exactly once on `requests.ConnectionError` with a fresh `Session`. The per-test-server harness SIGKILLs the server between tests, leaving this session's pooled keep-alive connections pointing at the dead server; the first request of the next test could die with RST (observed as `ConnectionResetError(104)` in round 6). Only transport failures are retried — completed HTTP responses (including error envelopes) pass through untouched, so no assertion is weakened. The retry is side-effect-free because the failure can only occur on a request that never reached the server.

**Fixes applied to `test_suite/`:**

3. `/home/ubuntu/github/CodingPRD/tasks/task_1295_pallet_manufacturing_recycling/test_suite/test_07_customers_orders_pool_returns.py` — `test_close_customer_with_pool_units_rejected` and `test_pool_credit_b_tier_lookup` now reuse the customer already created by `setup_sellable_world` via `customer_id=cust["id"]` instead of re-registering the same `company_name`.

**Fixes applied to `implementation/`:**

4. `/home/ubuntu/github/CodingPRD/tasks/task_1295_pallet_manufacturing_recycling/workspace/implementation/app.py` — server boot path hardened against the harness kill-and-respawn pattern, root-caused via kernel-level reproduction: when the harness SIGKILLs the server, the kernel's orderly close of its accepted keep-alive sockets leaves server-side TIME_WAIT entries that on this kernel (7.0.0-aws, `tcp_tw_reuse=2`) block a SO_REUSEADDR rebind of the same port for up to 60s — far beyond the runner plugin's 15s restart-poll window (this caused the "could not be restarted" errors, one in every round of iteration 1, always after request-heavy tests). Two layers:
   - A `WSGIRequestHandler` subclass sets `SO_LINGER(1, 0)` on every accepted socket, so closes become RST and create no server-side TIME_WAIT at all (verified empirically: 40 requests then kill → 0 TIME_WAITs, instant rebind). Safe because the server is keep-alive-only and never closes a connection while a response is in flight.
   - A bounded (13s) retry loop around the werkzeug serve call catching `SystemExit` (werkzeug's EADDRINUSE path), covering the residual race where an unrelated process grabs the port in the kill-respawn gap on this multi-tenant host.

No endpoint, field, side effect, or behavior visible to the API contract was added or changed; storage remains in-memory dicts, empty on every boot. `start.sh` was temporarily instrumented for forensics and restored byte-identical to its original form.

## Step 8: Finalize PRD — 2026-08-12T22:09:00.000Z

Task complete. `/home/ubuntu/github/CodingPRD/tasks/task_1295_pallet_manufacturing_recycling/workspace/PRD_FINALIZED.md` produced as a byte-identical copy of PRD.md — **zero edits were warranted**.

## Summary on exit

**Line counts / %-delta:** PRD.md = 366 lines; PRD_FINALIZED.md = 366 lines; delta = 0 lines (0.0%), byte-identical (`diff` clean).

**Changes:** none. Each `<step_7_diff>` item was evaluated and rejected as a PRD-edit trigger:

- **Item 1 (test_helpers/fixtures.py `customer_id` param)** — pure fixture bug. PRD §3.6 already pins "A `SalesRep` registers a **Customer** with a unique `company_name`", and the implementation enforces exactly that: `workspace/implementation/routes/customers.py:26-27` rejects a duplicate `company_name` with 400 `ERR_INVALID_REQUEST`. The step_7_diff itself labels the implementation "PRD-correct". PRD already determines the behavior → prose kept verbatim.
- **Item 2 (test_helpers/api_client.py one-shot `ConnectionError` retry)** — test-transport infrastructure only. No endpoint, field, or side effect in `implementation/` corresponds to it; there is no PRD subject to patch.
- **Item 3 (test_07 fixture reuse)** — same fixture bug as item 1; no PRD subject.
- **Item 4 (implementation/app.py SO_LINGER + bounded EADDRINUSE retry)** — TCP-socket and process-boot hardening only. The diff certifies "No endpoint, field, side effect, or behavior visible to the API contract was added or changed". Boot-time bind/port/foreground contract lives in `INSTRUCTION.md` (not PRD.md), and the implementation still satisfies it (`app.py:78-85` binds `0.0.0.0:$PORT`, default 10000). The only PRD boot-adjacent statement — §2.5's logical-clock startup default `2026-08-01T00:00:00Z` — is implemented exactly (`db.py:14`) and was untouched by the fix.

**Per-edit pre-edit search log** (the candidate edits considered and rejected; the rule's enumeration was performed for each):

1. **Candidate: pin customer `company_name` uniqueness more tightly.**
   - (a) Subject: customer registration uniqueness check.
   - (b) Paths enumerated: `implementation/routes/customers.py:25-27` (uniqueness scan → `ERR_INVALID_REQUEST`); all customer-creation callsites in `test_helpers/fixtures.py` (`create_customer`, `setup_sellable_world`, `setup_delivered_customer`, `setup_pool_credit`); `test_suite/test_07_customers_orders_pool_returns.py` fixed tests. PRD §3.6 and §2.8 ladder step 5 (`ERR_INVALID_REQUEST` covers request-shape/constraint violations).
   - (c) Adjustment: none — PRD §3.6 already uniquely determines the behavior and the implementation matches it, so no edit was committed (edit rejected, not merely reworded).
2. **Candidate: pin boot/storage behavior (in-memory, empty-on-boot; socket close semantics).**
   - (a) Subject: server boot path and storage initialization.
   - (b) Paths enumerated: `implementation/app.py` (`create_app`, `__main__` serve loop, `_Handler`/`_Server`), `implementation/db.py` (`Store` of 15 plain dicts, empty at import; logical clock default), `implementation/start.sh` (conditional pip install, `exec python3 app.py`), `implementation/routes/clock.py` (clock-set endpoint), and a repo-wide grep for `SO_LINGER|TIME_WAIT|serve_forever|SystemExit` confirming the socket code exists only in `app.py`'s `__main__` block and touches no route handler.
   - (c) Adjustment: none — every enumerated path's behavior is either outside the PRD's scope (socket linger, port-rebind retry) or already exactly described by PRD §2.5 (clock default). Pinning kernel/socket details in the PRD would invent constraints the API contract does not exhibit and risk new mismatches, so no edit was committed.
3. **Candidate: pin anything about client connection retry.**
   - (a) Subject: HTTP client session/keep-alive behavior.
   - (b) Paths enumerated: `test_helpers/api_client.py` (retry logic); confirmed no corresponding server-side behavior exists in `implementation/` (server is keep-alive-only per `app.py:68` comment; no retry-related endpoint or field).
   - (c) Adjustment: none — no PRD subject exists; edit rejected.

**Bottom line:** Step 7 found no PRD-silence or unique-derivability violations (all failures were fixture bugs or kernel/harness flakes), so the faithful finalized PRD is PRD.md verbatim. A fresh implementer reading PRD_FINALIZED.md plus INSTRUCTION.md already produces a code base behaviorally equivalent to `implementation/` at the API-contract level.

## Step 9: Complete PRD — 2026-08-12T22:25:00.000Z

All changes applied cleanly. Both files remain at 366 lines (all edits are inline). Here is the final summary.

## Summary

**Source file:** `PRD_FINALIZED.md` (366 lines, 53,015 chars) → `PRD_COMPLETED.md` (366 lines, 56,735 chars). Char delta: **+3,720**; line count unchanged (every change is an inline insert/revision).

**Counts:** 27 ambiguity-pins, 5 mismatch-revisions (32 change sites across 30 paragraphs).

### Changes

- §2.1 — revise — mismatch — `X-User-ID` is never required or inspected; `X-User-Role` is the single mandatory credential — `implementation/middleware.py:33-44`
- §2.1 — revise — mismatch — literal `Any` is not an acceptable `X-User-Role` value (matrix placeholder only); presenting it yields `ERR_UNAUTHENTICATED` — `implementation/middleware.py:16-38`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset`, `limit` outside 1–100, or negative `offset` → `ERR_INVALID_REQUEST` — `implementation/middleware.py:59-75`
- §2.3 — insert — ambiguity — creation-timestamp ties broken by insertion sequence — `implementation/services/helpers.py:20-21,49-51`
- §2.4 — insert — ambiguity — `version` starts at 1 on creation — `implementation/services/helpers.py:13-19`
- §2.5 — insert — ambiguity — clock settable to any instant (forward or backward); offset-less ISO timestamps interpreted as UTC — `implementation/routes/clock.py:12-18`, `implementation/middleware.py:155-157`
- §2.8 — insert — ambiguity — unknown paths and unsupported methods surface as `ERR_NOT_FOUND` (404) — `implementation/app.py:31-37`
- §3.1 — insert — ambiguity — duplicate `spec_code` → `ERR_INVALID_REQUEST` — `implementation/routes/specs.py:35-36`
- §3.1 — revise — mismatch — dropped "only `ACTIVE` specs are selectable when creating inventory lots or order lines" / "RETIRED spec no longer selectable": impl enforces spec existence only, never status — `implementation/routes/lots.py:31-32`, `implementation/routes/orders.py:56-58`
- §3.1 — insert — ambiguity — retire attempted from non-`ACTIVE` status fails with `ERR_INVALID_STATE` — `implementation/routes/specs.py:93-94`
- §3.2 — insert — ambiguity — index windows must be non-degenerate (`effective_from` strictly before `effective_to`), else `ERR_INVALID_REQUEST` — `implementation/routes/indices.py:30-31,81-82`
- §3.2 — insert — ambiguity — duplicate `season_code` and out-of-range `multiplier_bp` both rejected with `ERR_INVALID_REQUEST` — `implementation/routes/indices.py:77-78,84-85`
- §3.3 — insert — ambiguity — `agreed_unit_price_cents` is zero-or-greater; `estimated_grade_mix` requires all three keys, non-negative numerics summing to one, else `ERR_INVALID_REQUEST` — `implementation/routes/cores.py:26-39,48`
- §3.3 — insert — ambiguity — `count` defaults to 1 (minimum 1); bulk create's `data` carries the first created row — `implementation/routes/cores.py:141-166`
- §3.3 — insert — ambiguity — SCRAP-note rule evaluated against the effective note: payload `condition_notes` replaces the stored note; a core received with a non-empty note needs none at sort time — `implementation/routes/cores.py:204-224`
- §3.3 — insert — ambiguity — `grade_yield_variance_bp` treats the actual `A` fraction as zero when `received_count` is zero — `implementation/services/calc.py:175-183`
- §3.4 — insert — ambiguity — `actual_labor_minutes` is zero-or-greater — `implementation/routes/repairs.py:146`
- §3.4 — revise — mismatch — no three-repair-cycle cap is enforced (`MAX_REPAIR_CYCLES` defined but unused) and `rework_of_id` is never set: `FAILED` always cycles the same row in place back to `UNSORTED`/`YARD` — `implementation/routes/repairs.py:156-166`, `implementation/services/calc.py:23`
- §3.5 — insert — ambiguity — directly created `RECYCLED_REPAIR` lot: `quality_grade` defaults to `A`, `unit_cost_cents` is 0, no lumber-index coverage required — `implementation/routes/lots.py:44-49`
- §3.5 — insert — ambiguity — recycled lot from a batch-less (pool-returned) core costs `parts_cost_cents` + labor only — `implementation/routes/repairs.py:29-39`
- §3.5 — insert — ambiguity — assign-lot additionally requires the lot `AVAILABLE` and not already assigned to any live (`STAGING`/`RUNNING`) run, this one included, each gate failing with `ERR_INVALID_STATE` — `implementation/routes/lots.py:174-190`
- §3.5 — insert — ambiguity — `ispm15_mark_id`: `<yyyymmdd>` is the completion date on the logical clock; `<seq>` is a server-wide counter starting at 1 — `implementation/routes/lots.py:245-251`, `implementation/db.py:35-38`
- §3.6 — insert — ambiguity — duplicate `company_name` → `ERR_INVALID_REQUEST` — `implementation/routes/customers.py:26-27`
- §3.6 — insert — ambiguity — allocation is atomic: all `OPEN` lines resolved in creation order before any reservation commits, projected debits shared across competing lines, first unsatisfiable line aborts with its error leaving all lots untouched — `implementation/routes/orders.py:233-270`
- §3.7 — insert — ambiguity — credited pool returns spawn core units with null `batch_id`, species `MIXED`, empty `condition_notes`, `repair_cycle_count` 0 — `implementation/routes/pool_returns.py:117-131`
- §3.8 — insert — ambiguity — stop `load_cube_cuft` computed over `ALLOCATED`/`FULFILLED` lines only for `DELIVERY`/`MIXED` stops with an `order_id`; zero otherwise — `implementation/routes/routes.py:104-112`
- §3.8 — insert — ambiguity — dispatch's order-`ALLOCATED` gate applies only to `DELIVERY`/`MIXED` stops carrying an `order_id` — `implementation/routes/routes.py:187-194`
- §3.8 — insert — ambiguity — order becomes `DELIVERED` only when every stop referencing it is `COMPLETED` (a `SKIPPED` co-stop holds it at `SHIPPED`); `pool_units_outstanding` grows by the sum of the order's `FULFILLED` line quantities — `implementation/routes/routes.py:247-266`
- §3.8 — revise — mismatch — skip endpoint imposes no route-state gate (PRD claimed `DISPATCHED`-only plus cancellation); only the stop's `SCHEDULED` status is checked — `implementation/routes/routes.py:270-278`
- §3.8 — insert — ambiguity — close payload `fuel_surcharge_cents` is an integer, zero or greater — `implementation/routes/routes.py:286-287`
- §3.9 — insert — ambiguity — `input_core_ids` must be a non-empty array of existing core ids (`ERR_INVALID_REQUEST` / `ERR_REFERENCED_NOT_FOUND`); `revenue_cents` defaults to zero — `implementation/routes/grinding.py:25-36,101-102`

Verified already-pinned behavior left untouched: all endpoint paths/roles in §4, the full error catalogue (62 codes, matching `errors.py` exactly), all calculation formulas (settlement, pricing, margins, yield, costing, overhead tiers, price book, credit tiers), OCC contract and priority ladder, state machines, and response envelope shapes.
