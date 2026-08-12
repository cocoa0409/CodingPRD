# Worklog — task_0986_water_delivery_bottled_water

## Step 1: Create task directory — 2026-08-10T00:00:00.000Z

Task directory pre-assigned by the headless runner: `tasks/task_0986_water_delivery_bottled_water/` with `workspace/` subdirectory already present. Step 1 auto-index scan skipped per runner instructions. Difficulty parameter: "generate task hard than expert level!" (passed to scaffold generator at Step 2 only).

## Step 2: Generate scaffold — 2026-08-10T10:55:00.000Z

File structure is correct:
- `SCAFFOLD.yaml` does NOT contain `scaffold_difficulty_design` or `scaffold_corner_design` as top-level keys (per spec)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` has single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` has single top-level key `scaffold_corner_design`

## Summary

**Files generated** (all three required outputs):
- `/home/ubuntu/github/CodingPRD/tasks/task_0986_water_delivery_bottled_water/SCAFFOLD.yaml` (2163 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_0986_water_delivery_bottled_water/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1468 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_0986_water_delivery_bottled_water/SCAFFOLD_CORNER_DESIGN.yaml` (1164 lines)

**Artifact counts**:
- **Entities: 12** — Customer, DeliveryZone, Route, Stop, BottleCustodyLedger, CoolerRental, AddOn, Invoice, Payment, WorkOrder, PricingConfig, SkipCredit
- **State machines: 9** — one per stateful entity (Customer, Route, Stop, CoolerRental, AddOn, Invoice, Payment, WorkOrder, SkipCredit)
- **Calculations: 8** — calc_water_charge, calc_prorated_rent, calc_shortage_charge, calc_deposit_refund, calc_skip_credit, calc_route_commit, calc_auto_tier_upgrade, calc_outstanding_balance
- **Endpoints: 74** — CRUD + actions across all entities + `/_clock/set_current_utc` test-driving endpoint with default 2026-05-01T00:00:00Z
- **Errors: 18** — auth, not-found, state, fiscal, referential, temporal, capacity, OCC, etc.
- **Roles: 5** — OpsAdmin (opaque), Dispatcher (opaque), Driver (opaque), BillingAdmin (opaque), CustomerSelf (entity_backed:Customer)
- **Difficulty instances: 18** — exactly 2 per §0.5 rule × 9 rules (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant)
- **Corner instances: 28** — across sections entities (6), state_machines (4), calculations (3), validations (6), endpoints (2), errors (1), rbac (3), cross_cutting_layers (2), consistency_model (1)

**Lint verdict**: `VERDICT: clean lint` — 525 calls scanned, all §1.8/§1.9 calls conform to §1.5, all §1.1 FKs have reverse-reachability GETs.

**Key design adjudications**:
1. **Primary archetype**: `ledger_reconciliation` (bottle-custody ledger vs billing-ledger reconciliation for deposit/shortage); secondary `quota_allocation` (truck-capacity commit on Route).
2. **"Harder than expert"** was implemented by exceeding Expert-band endpoint count (74 vs 32), satisfying every §0.5 rule with structurally differentiated instances (different entity domains, error-category pairs, interval semantics, conserved quantities), and adding two OCC concurrency rules (Customer version + Route version on stop delivery).
3. **Dual-variant calculations** were placed on distinct entity domains: water charge (Stop) vs deposit refund (BottleCustodyLedger / Customer), satisfying Rule 1's differentiation clause.
4. **Combinatorial formula modes** were placed in different modes: prorated_rent = mode (a) (multi-input non-linear with conditional zero-accrual), deposit_refund = mode (c) (order-sensitive chronological replay with pinned tie-break).
5. **Cascades**: Customer.suspend -> WorkOrder cancel -> Stop cancel -> Route.committed_bottles decrement (depth 3); Route.cancel -> Stop cancel -> committed_bottles reset (depth 2).
6. **Logical clock**: default `2026-05-01T00:00:00Z` declared in the `POST /_clock/set_current_utc` endpoint description; used pervasively in test recipes to drive time-based transitions (OVERDUE, EXPIRED) deterministically.

## Step 3: Copy shared files — 2026-08-10T10:57:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_0986_water_delivery_bottled_water/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-10T11:05:00.000Z

## Generated Artifact

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_0986_water_delivery_bottled_water/workspace/PRD.md` — 301 lines, ~46 KB.

**Section structure:**
- §1 Introduction (2 paragraphs — business-context angle)
- §2 Global Specifications (10 subsections): 2.1 RBAC with per-role identity prose, 2.2 API Response Structure (byte-identical to `section-2.2-response-structure.md`, verified), 2.3 Pagination, 2.4 Logical Clock & Time-Driven Transitions, 2.5 Common Resource Properties, 2.6 Request Validation Order, 2.7 Nested Resource Retrieval, 2.8 Monetary Values & Precision, 2.9 OCC, 2.10 Bottle Custody & Deposit Liability
- §3 Business Logic (8 subsections, grouped by business process: pricing/zones → customer lifecycle → route planning → route execution → skips/credits → work orders & cooler rentals → add-ons → invoicing/payments)
- §4 Endpoint Definitions (74 endpoints, 4-column table)
- §5 Error Code Catalogue (18 errors, 2-column table)

**Hard-contract audit (mechanically verified via script):**

- **Contract 1 — Field-Name Coverage:** 90 required identifiers (all `entities[].fields[].name` + all endpoint `input`/`query_params`/`path_params`), 90 present in backticks, 0 missing. PASS (first pass missed `addon_status`, `credit_status`, `payment_status`, `rental_status`, and the `REFUNDED` state; fixed in a second pass, re-verified).
- **Contract 2 — Rule Coverage:** hand-walked. Validation priority cascade rendered as a numbered 7-stage ordered narrative in §2.6 plus the 11 endpoint-specific business checks enumerated after it; both OCC rules expressed in §2.9 with write operation, `expected_customer_version`/`expected_route_version`, `ERR_STALE_VERSION` + HTTP 412; all 8 calculations expressed in precise prose with constants embedded (24-hour inclusive cutoff, 50% late-skip ratio, 12 months / 365 days, 90-day credit expiry) including the rejected variants (per-event deposit refund, exclusive return-day, forward-looking estimate at period start) and the provisional-vs-final water-charge duality; all state transitions across 10 state machines expressed with from/to states, preconditions, and side effects; cross-entity cascades (suspend, close, deliver, route-cancel, confirm-return, payment apply/refund) each fully enumerated; asymmetric sibling branches (close from `ACTIVE` vs `SUSPENDED`; dispute resolution `RESTORE` vs `VOID`) given equal density. PASS.
- **Contract 3 — §3 Path Purity:** 440 backtick tokens scanned in §3, 0 path tokens, 0 bare-method tokens, 0 method+path combos. PASS. Endpoints in §3 are named via state-pair framing (`ARRIVED` → `DELIVERED`/`PARTIAL`), role + verb ("a `Dispatcher` may cancel a route"), or capability description (clock-setting).

**Other checks:** all 18 error IDs appear in §2/§3 prose; all 34 state values and all 66 enum values appear verbatim; all 74 endpoint paths present in §4; roles exactly as scaffolded (`OpsAdmin`, `Dispatcher`, `Driver`, `BillingAdmin`, `CustomerSelf`).

**Adjudications made:**
1. The `ERR_ALREADY_TERMINAL` (409) error exists in the error catalog but no validation entry; homed in §2.6 stage 4 as the terminal-state counterpart to `ERR_INVALID_STATE`.
2. `BottleCustodyLedger` has `common_fields: false`; §2.5 explicitly states it carries only `id` and `created_at`, with `updated_at`/`version` absent.
3. The clock endpoint's exemption from the auth-header check (validation priority 1) is expressed in §2.1 without naming its path (path lives only in §4); the `/api/v1` mount is mentioned once in §1 and §4, outside §3.
4. Per the hard constraint, neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, read, grepped, or referenced at any point.

## Step 5: Generate unit tests — 2026-08-10T11:35:00.000Z

Generation complete for task_0986_water_delivery_bottled_water. Verbatim summary:

**Files generated**
- `test_helpers/` — 9 files: `types.py` (12 entity TypedDicts; BottleCustodyLedger correctly omits `updated_at`/`version` per its append-only contract), `api_client.py` (58 endpoint methods covering every PRD §4 endpoint), `api_errors.py` (18 error IDs + HTTP map registered via `set_error_http_status_map`), `assertions.py` (12 entity assertions + customer balance invariants), `factories.py`, `constants.py` (DEFAULT_PRICING, clock default, rent/skip-credit constants), `test_users.py` (shared opaque-role constants + mandatory `make_customer_self_headers(customer_id)` builder for the entity-backed CustomerSelf role), `fixtures.py` (tiered composites: `setup_zone`/`setup_customer`, delivery chain `deliver_via_work_order`, `setup_open_invoice`, `setup_suspended_customer`, `setup_installed_rental`, `setup_skip_credit`, OCC-aware `deliver_arrived_stop`), `__init__.py` barrel.
- `test_suite/` — `conftest.py` + 11 numbered test files, **60 tests total**. `pytest --collect-only` passes (60 collected, 0 errors).

**Queue A (Difficulty): 32 tests across 16/18 instances** (exactly 2 tests per covered instance).
Skipped instances (2), with reasons:
1. `combinatorial_formula/deposit_refund_mode_c_chronological_replay` — setup depends on `PICKUP_ONLY` work-order scheduling semantics the PRD never defines (§3.6 defines stop creation only for DELIVERY/EXCHANGE_ONLY), and its claimed replay-order sensitivity has no observable effect under the PRD's opening/closing net-count formula. Fails both coverage and unique derivability.
2. `priority_pair_validation_conflict/state_vs_business_fiscal_close_with_balance` — the dual violation (CLOSED customer with outstanding balance) is unreachable through PRD-consistent API use since both closure paths gate on zero balance; the instance's expected `ERR_INVALID_STATE` also contradicts PRD §2.6's explicit terminal-state rule ("an operation attempted on a resource already sitting in a terminal state is instead rejected with `ERR_ALREADY_TERMINAL`").

**Queue B (Corner): 28 tests across 28/28 non-stub instances** (no `excluded_because:` stubs exist in this index).

**Notable PRD-first adjudications**
- Deposit-refund dual-variant tests use clean exchange-parity deliveries (net movement zero → `deposit_credit_cents == 0` vs rejected per-event 3000), avoiding the PRD-ambiguous custody effect of `MARK_SHORTAGE` entries.
- Prorated-rent tests install before the period and suspend/resume at midnight boundaries so installed-day counts (30d→8880, 15d→4440, 25d→7400 at daily rate 296) are uniquely derivable — the design's literal day counts relied on an install-day convention the PRD leaves open.
- `skip_credit_expires_at_boundary` uses `validate_error_is_one_of([ERR_CREDIT_EXPIRED, ERR_INVALID_STATE, ERR_ALREADY_TERMINAL])` on the at-expiry side (error-precedence silence pattern: PRD names the expiry error but the clock-driven auto-transition to terminal EXPIRED leaves the rejection path open); the one-second-before side asserts a hard success.
- Suspend-cascade tests assert only PRD-stated effects (PENDING work order cancelled, PLANNED stop cancelled, commitment released) and deliberately do not assert the SCHEDULED order's fate, which the PRD does not cancel.
- Terminal-state lockdown tests assert exactly `ERR_ALREADY_TERMINAL` per the explicit §2.6 sentence.

**Audit results**
- Stage 1: package imports cleanly; all helpers/pytest fixtures resolve.
- Stage 2 audit: 60/60 tests carry exactly one `Design:` tag as the final docstring line; all 60 tags resolve to real instances; queue A coverage 16/18 with ≥2 tests each (2 documented skips); queue B 28/28.
- Stage 3 (PRD-citation) audit: after fixing 8 initial mismatches (truncated/elided quotes and reformatted §4 table rows), all quoted citations match PRD.md verbatim under whitespace-normalized grep; no `pytest.mark.skip`/`skipif`/`xfail` anywhere; no "scaffold" references in generated comments or docstrings.

## Step 6: Generate implementation — 2026-08-10T11:35:00.000Z

## Files generated (all under `/home/ubuntu/github/CodingPRD/tasks/task_0986_water_delivery_bottled_water/workspace/implementation/`)

- `start.sh` — executable launcher (see below)
- `requirements.txt` — `flask>=3.0,<4`
- `app.py` — Flask entry point, blueprint registration under `/api/v1`, auth `before_request` gate, error handlers (ApiError, 404, 405, catch-all 500), `app.run(host="0.0.0.0", port=$PORT or 10000, threaded=True)`
- `db.py` — in-memory store (12 dicts keyed by id + monotonic seq + logical clock starting at `2026-05-01T00:00:00Z`); no seeding anywhere
- `errors.py` — all 18 catalog error IDs with exact HTTP statuses
- `response.py` — envelope helpers (`meta.api_request_id`/`api_request_timestamp` with 3-fractional-digit ISO, `response_type`, `data`; list meta `limit`/`offset`/`total_count`/`has_more`; pagination defaults 10/0, min 1, max 100; sort by `created_at` asc)
- `middleware.py` — `X-User-ID`/`X-User-Role` extraction (401), role decorator (403 ERR_UNAUTHORIZED), ownership check (ERR_FORBIDDEN), typed field validators, terminal-vs-invalid-state transition checker
- `services.py` — logical clock ops, time-driven auto-transitions (OPEN→OVERDUE with one-time late fee, PENDING→EXPIRED credits), all calculations, all serializers
- `routes/` — 11 blueprints: `clock_routes.py`, `pricing.py`, `zones.py`, `customers.py`, `routes_stops.py`, `work_orders.py`, `rentals.py`, `addons.py`, `invoices.py`, `payments.py`, `skip_credits.py`

## Endpoint coverage
All **74/74** endpoints from the scaffold endpoint table are implemented (clock, 3 pricing-config, 5 delivery-zone, 13 customer + sub-collections, 9 route, 9 stop, 6 work-order, 7 cooler-rental, 5 addon, 8 invoice, 5 payment, 3 skip-credit).

## State machines implemented (9)
Customer (ACTIVE/SUSPENDED/CLOSED with suspend/reinstate/close cascades), Route (DRAFT→PUBLISHED→IN_PROGRESS→COMPLETED/CANCELLED with stop cascades), Stop (PLANNED→EN_ROUTE→ARRIVED→DELIVERED/PARTIAL/SKIPPED/FAILED/CANCELLED with custody-ledger side effects), CoolerRental (PENDING_INSTALL→INSTALLED⇄SUSPENDED→RETURN_REQUESTED→RETURNED→CLOSED with linked work orders), AddOn (ACTIVE⇄PAUSED→CANCELLED), Invoice (DRAFT→OPEN→PARTIALLY_PAID/PAID/OVERDUE/DISPUTED/VOID), Payment (PENDING→APPLIED/FAILED, APPLIED→REFUNDED reopens invoice), WorkOrder (PENDING→SCHEDULED→IN_PROGRESS→COMPLETED/CANCELLED/REJECTED), SkipCredit (PENDING→APPLIED/EXPIRED/REVOKED). Terminal-state hits return ERR_ALREADY_TERMINAL; wrong non-terminal states return ERR_INVALID_STATE.

## Calculations implemented (8)
`calc_water_charge` (tier rate × actuals, config at route service_date), `calc_prorated_rent` (daily rate = round_half_up(rent×12/365) via Decimal, per-day accrual from rental status history, suspended days zero, install day and return day inclusive), `calc_shortage_charge` (shortage_count × fee at service_date config), `calc_deposit_refund` (ledger replay opening/closing at period bounds, max(0, open−close) × deposit at period_end config, plus refundable cooler deposits), `calc_skip_credit` (full vs round_half_up 50% on notified flag, expires_at = now+90d), `calc_route_commit` (sum over PLANNED/EN_ROUTE/ARRIVED, capacity ceiling enforced), `calc_auto_tier_upgrade` (inclusive thresholds at issue, applied for next period), `calc_outstanding_balance` (sum over OPEN/OVERDUE/PARTIALLY_PAID/DISPUTED, computed at read).

## How start.sh works
`set -euo pipefail`, `cd` to its own dir, guarded install (`if ! python3 -c "import flask"` then `pip install -q -r requirements.txt`) so per-test reboots skip pip, then `exec python3 app.py` in the foreground. Verified: boots on `$PORT`, binds 0.0.0.0, store is empty on every fresh boot (created a zone, killed the process, rebooted via `bash start.sh` → `total_count: 0`).

## Adjudications (PRD/scaffold ambiguities resolved)
1. **bottles_on_site = literal Σ(quantity)** including `MARK_SHORTAGE(+shortage_count)` — per scaffold's explicit signed quantities and calc_deposit_refund's "computed by replay" language (deposit-refund comparisons are internally consistent since both bounds replay the same ledger).
2. **Clock endpoint auth**: exempt from header-presence per §2.1, but if a role header *is* supplied and isn't OpsAdmin → 403.
3. **Cooler install reachability**: the linked install work order can never reach IN_PROGRESS through any endpoint (no "start install" trigger exists), so `/install` accepts the linked WO in SCHEDULED or IN_PROGRESS (driver starting the install is the documented IN_PROGRESS trigger) and completes it.
4. **Stop over-collection**: `actual_bottles_delivered > planned_bottles` → 400; over-collected empties allowed (DELIVERED when delivered==planned and collected≥planned_empties; shortage floored at 0).
5. **AddOn billing**: RECURRING charged when status==ACTIVE at draft time; ONE_TIME charged when `created_at` date falls in the period and status≠CANCELLED.
6. **Skip credit apply with no DRAFT invoice**: marked APPLIED with a pending-consumption flag absorbed into the next drafted invoice's total/balance (scaffold's "or one will be created" branch without inventing invoice periods).
7. **Route creation into an inactive zone** → ERR_INVALID_REFERENCE ("incompatible" reference); **publish with inactive zone** → ERR_INVALID_STATE (state precondition).
8. **Customer version bumps** on direct ops and on delivery cascades (the documented OCC scenario) and tier upgrades; balance-only recomputes are derived at read and don't bump version.
9. **Zero-quantity ledger entries** are not written (e.g. PICKUP_EMPTY(−0)); non-zero DELIVER_FULL/PICKUP_EMPTY/MARK_SHORTAGE entries always are.
10. **WILL_CALL manual stop planning** refused with ERR_INVALID_REQUEST(400); PICKUP_ONLY scheduling creates a stop with planned_bottles=0, planned_empties=quantity_bottles.

Validation cascade follows PRD §2.6 strictly (auth → role → path existence left-to-right → state/terminal → field types → FK → dates → business checks), and both OCC contracts (`expected_customer_version` on PATCH customer, `expected_route_version` on stop deliver, ERR_STALE_VERSION 412) are enforced. Verified with 100+ smoke assertions across four scenario scripts (all passing) covering CRUD, RBAC, ownership, pagination, every state machine, all calculations with concrete numbers, disputes, refunds, overdue late fees, credit expiry, and cascades.

## Step 7: Run tests and iterate — 2026-08-10T11:45:00.000Z

All 8 rounds passed cleanly: 60/60 in every round, 0 failed. The exit condition is met.

## Summary

**Iterations run:** 2 (initial sweep → 2 deterministic failures → fix → clean 8/8 round sweep).

**Tests deleted:** None.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `test_helpers/test_suite`:** None.

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_0986_water_delivery_bottled_water/workspace/implementation/services.py` — `new_id()` (line 59-60): changed `uuid.uuid4().hex` (32 hex chars, no dashes) to `str(uuid.uuid4())` (canonical dashed 8-4-4-4-12 form). PRD §2.5 states "The `id` is a server-minted UUID with no type prefix"; the shared test library's `is_valid_uuid` enforces canonical dashed UUID format. This single fix resolved both deterministic failures:
  - `test_customer_creation_with_required_fields_returns_201` (AssertionError: id must be a valid UUID)
  - `test_bottle_custody_ledger_immutable_no_version` (AssertionError: ledger entry id must be a valid UUID)

**Final state:** 8/8 parallel rounds × 60/60 tests passing = clean stability sweep.

## Step 8: Finalize PRD — 2026-08-10T11:52:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_0986_water_delivery_bottled_water/workspace/PRD_FINALIZED.md` written with exactly one inline revision.

## Summary

**Line counts / delta:** PRD.md = 300 lines, PRD_FINALIZED.md = 300 lines — 0% line-count delta (single in-place sentence revision on line 78; no sections added or removed).

**Changes (one total):**
- §2.5 Common Resource Properties — **revise** — the sentence "The `id` is a server-minted UUID with no type prefix." now reads "The `id` is a server-minted UUID rendered in its canonical dashed 8-4-4-4-12 lowercase hexadecimal string form, with no type prefix." — pins the string representation that the Step 7 fix converged on — `workspace/implementation/services.py:59-60` (`new_id()` returning `str(uuid.uuid4())`).

**Why an edit was warranted despite the fix direction being impl→PRD:** the pre-fix implementation (`uuid.uuid4().hex`, 32 dashless hex chars) is direct evidence that the original §2.5 wording did not uniquely determine the representation — a real implementer chose the dashless reading and both deterministic Step 7 failures resulted. Pinning the canonical dashed form guarantees a fresh implementer reproduces the current implementation. This was the only Step 7 diff item, and no other PRD prose was touched.

**Per-edit pre-edit search log (the single edit):**
- (a) Subject: string representation of the system-managed resource `id` field.
- (b) Impl paths enumerated and read/grepped: `services.py:59-60` `new_id()` (sole ID minter; `str(uuid.uuid4())` → dashed, lowercase); `services.py:63-71` `base_record()` feeding every standard-resource create (store sites verified by grep: `routes/customers.py:58`, `zones.py:28`, `routes_stops.py:52,89,368`, `pricing.py:54`, `payments.py:46`, `invoices.py:126`, `rentals.py:44,73`, `addons.py:47`, `work_orders.py:49`); `services.py:129-141` `add_ledger_entry()` (custody-ledger `id` via the same `new_id()`, consistent with §2.5's second paragraph); all reference fields (`customer_id`, `route_id`, `zone_id`, `stop_id`, `invoice_id`, `customer_ref`, `delivery_zone_id`, `linked_stop_id`) copy minted strings verbatim, so the pin propagates transitively; `response.py:19` `api_request_id` (`"req_" + uuid.uuid4().hex[:20]`) is a non-resource envelope field separately specified at PRD line 40 — outside the edited sentence's scope, unaffected; no route validates path-parameter UUID format (dict string-equality lookups only), so no contradiction anywhere.
- (c) Wording adjustment: inserted "rendered in its canonical dashed 8-4-4-4-12 lowercase hexadecimal string form" inside the existing sentence; "lowercase" exactly matches Python `str(uuid.UUID)` output on every enumerated minting path, so no enumerated path is mis-described.

## Step 9: Complete PRD — 2026-08-10T12:05:00.000Z

Done. `PRD_COMPLETED.md` produced at `/home/ubuntu/github/CodingPRD/tasks/task_0986_water_delivery_bottled_water/workspace/PRD_COMPLETED.md`.

**Source / stats**
- Source: `PRD_FINALIZED.md` (existed; copied, then edited in place as `PRD_COMPLETED.md`)
- Lines: 300 → 300 (all edits in-paragraph, no new sections)
- Chars: 46,266 → 50,519 (Δ +4,253)

**Counts**
- Ambiguity-pins: 18
- Mismatch-revisions: 6

**Changes**

- §2.1 — insert — ambiguity — clock endpoint: role header optional, but if `X-User-Role` is supplied it must be `OpsAdmin` (else 403) — implementation/routes/clock_routes.py:17-19
- §2.3 — insert — ambiguity — non-integer `limit`/`offset`, `limit` outside 1–100, or negative `offset` → `ERR_INVALID_REQUEST`; `created_at` ties broken by creation order — implementation/response.py:46-76
- §2.4 — insert/revise — ambiguity — clock accepts any well-formed target instant (backward moves permitted); "advances" → "changes"/"setting" — implementation/routes/clock_routes.py:26-33
- §3.1 — insert — ambiguity — volume thresholds must also be strictly positive, else `ERR_INVALID_PRICING_CONFIG` — implementation/routes/pricing.py:30-39
- §3.1 — insert — ambiguity — duplicate zone `code` rejected with `ERR_INVALID_REQUEST` — implementation/routes/zones.py:22-24
- §3.1 — insert — ambiguity — creating a route in an inactive zone rejected with `ERR_INVALID_REFERENCE` — implementation/routes/routes_stops.py:78-79
- §3.2 — insert — ambiguity — customer PATCH only from `ACTIVE`/`SUSPENDED`; `CLOSED` → `ERR_ALREADY_TERMINAL` — implementation/routes/customers.py:87-88
- §3.2 — insert — ambiguity — suspend cascade cancels `PLANNED` stops on routes with `service_date` today or later — implementation/routes/customers.py:136-146
- §3.2 — insert — ambiguity — close from `ACTIVE` with a standing cooler rental → `ERR_INVALID_STATE` — implementation/routes/customers.py:185-190
- §3.3 — insert — ambiguity — stops plannable while route is `DRAFT` or `PUBLISHED`; manual planning for `WILL_CALL` refused with `ERR_INVALID_REQUEST`; stop arrival bumps route `version` — implementation/routes/routes_stops.py:206-217, 53
- §3.3 — revise — mismatch — route completion writes no invoice line entries; billing happens at invoice-draft time per §3.8 — implementation/routes/routes_stops.py:160-174, implementation/routes/invoices.py:26-96
- §3.3 — insert — ambiguity — route cancel moves only non-terminal stops to `CANCELLED` — implementation/routes/routes_stops.py:183-191
- §3.4 — revise — mismatch — clean exchange = delivered exactly `planned_bottles` AND empties collected ≥ `planned_empties_pickup` (over-collection still clean) — implementation/routes/routes_stops.py:304-305
- §3.4 — insert — ambiguity — actuals must be non-negative; `actual_bottles_delivered` > `planned_bottles` → `ERR_INVALID_REQUEST` — implementation/routes/routes_stops.py:293-303
- §3.4 — insert — ambiguity — custody entries written only for non-zero quantities — implementation/routes/routes_stops.py:314-322
- §3.5 — insert — ambiguity — `notified_before_cutoff` optional, defaults false; credit rate uses config in effect on route's `service_date`; skip returns the updated stop — implementation/routes/routes_stops.py:350-373
- §3.5 — revise — mismatch — apply with no `DRAFT` invoice: no invoice is created; credit goes `APPLIED` and is absorbed at next draft; with a `DRAFT`, the earliest-created absorbs it — implementation/routes/skip_credits.py:40-58, implementation/routes/invoices.py:79-85
- §3.6 — insert — ambiguity — `CustomerSelf` work-order creation is ownership-checked (`ERR_FORBIDDEN`) — implementation/routes/work_orders.py:37
- §3.6 — insert/revise — ambiguity — scheduling: earliest-created matching route chosen; no match → `ERR_INVALID_REFERENCE`; `PICKUP_ONLY` schedules with `planned_bottles` 0 and empties = quantity; `COOLER_RETURN` scheduling requires rental `RETURN_REQUESTED`; cooler state failures → `ERR_INVALID_STATE` — implementation/routes/work_orders.py:87-124
- §3.6 — insert — ambiguity — rental-spawned `COOLER_INSTALL` work order gets `requested_date` = current logical date, `quantity_bottles` 0 — implementation/routes/rentals.py:33-45
- §3.6 — revise — mismatch — install allowed while linked work order is `SCHEDULED` or `IN_PROGRESS` (not only `IN_PROGRESS`) — implementation/routes/rentals.py:96-101
- §3.6 — insert — ambiguity — confirm-return completes linked `COOLER_RETURN` order only if it stands `SCHEDULED`/`IN_PROGRESS` — implementation/routes/rentals.py:166-170
- §3.6 — revise — mismatch — closing a `RETURNED` rental has no "accrued rent fully billed" gate; any `RETURNED` rental may close — implementation/routes/rentals.py:174-187
- §3.7 — insert — ambiguity — `RECURRING` add-on charged only while `ACTIVE`; `ONE_TIME` charged only if not `CANCELLED` and created in period; charge = quantity × unit_price — implementation/routes/invoices.py:51-61
- §3.8 — revise — mismatch — `total_due_cents` also subtracts already-`APPLIED` skip credits not yet absorbed; no rounding step fires (all whole-cent inputs); water rate uses customer's tier at draft time; `deposit_credit_cents` also absorbs returned cooler deposits; `balance_due_cents` starts equal to total — implementation/routes/invoices.py:44-96
- §3.8 — insert — ambiguity — issue with non-positive total → `ERR_INVALID_STATE`; tier thresholds drawn from config in effect at `billing_period_end`; bottle count from stops with service dates in the half-open window — implementation/routes/invoices.py:157-189
- §3.8 — insert — ambiguity — partial application against a `DISPUTED` invoice reduces balance but leaves it `DISPUTED` — implementation/routes/payments.py:78-81
- §3.8 — insert — ambiguity — rent accrual: `RETURN_REQUESTED` days accrue; install day counts as a full accrual day — implementation/services.py:156-176

**Items deliberately left unchanged**: endpoint/role table (fully aligned with impl), error catalogue (aligned), ledger immutability (aligned), shortage/deposit/refund formulas (aligned), the §3.4 "projected-charges cache" sentence (non-observable color; impl exposes no projection, and the sentence pins only that nothing is persisted — no contradiction).
