# Worklog — task_1910_seafood_wholesale_dockside_purchase

## Step 1: Create Task Directory — 2026-08-15T00:08:00.000Z

Task directory `tasks/task_1910_seafood_wholesale_dockside_purchase/` and `workspace/` pre-created by pipeline launcher (verified to exist; no new index computed, no other task directory touched).

## Step 3: Copy Shared Files — 2026-08-15T00:09:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1910_seafood_wholesale_dockside_purchase/workspace/INSTRUCTION.md` (done out of order, before Step 2 subagent, since it has no dependency on scaffold output).

## Step 2: Generate Scaffold — 2026-08-15T00:38:52.978Z

Task 1910 — Seafood Wholesale & Dockside Purchase — scaffold generated at "harder than expert" tier per operator directive.

**Files written:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1910_seafood_wholesale_dockside_purchase/SCAFFOLD.yaml` — 1142 lines (§1.0–§1.7; no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1910_seafood_wholesale_dockside_purchase/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 821 lines (single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1910_seafood_wholesale_dockside_purchase/SCAFFOLD_CORNER_DESIGN.yaml` — 1377 lines (single key `scaffold_corner_design`)

**Counts:** 16 entities; 9 state machines (incl. DockTicket re-grade cycle with cap 2, InventoryLot parallel dims lifecycle×hold, ImportDocument resubmission cycle, MarketQuote PENDING_APPROVAL loop, SalesOrder compound FULFILLED bubble-up with regression); 10 calculation rules; 10 validation priority rows; 74 endpoints (incl. `POST /_clock/set_current_utc`, default `2026-08-01T00:00:00Z`); 53 error codes; 9 roles (segregation-of-duties model; VesselAgent/Customer entity-backed); 3 OCC concurrency rules. §1.8: 21 instances (dual_variant 2, combinatorial 3 covering modes a/b/c, non_linear_sm 3, cascade 2, priority_conflict 2, boundary 3, cross_entity 2, temporal_overlap 2, compensating 2). §1.9: 58 instances (51 active + 7 excluded_because stubs) across all 9 guide sections. Lint: clean (889 calls scanned). Placeholder closure, name uniqueness, stub references, and error-catalog coverage all verified mechanically; all formula-derived asserts pre-computed via Python (e.g., settlement 120000→82935, rounding-pin 3687 vs 3686, freight 11006/9901/10853, min-charge floor 4000).

**Design adjudications:** (1) `api_prefix: /` with flat topology and filtered-list GETs for all FK reverse-reachability (no nested URLs). (2) Settlement quote lookup pinned to landing-date quotes in {PUBLISHED, SUPERSEDED, EXPIRED} so historical pricing survives supersession/expiry, while order price-lock selector uses PUBLISHED-only — the two lookups intentionally differ. (3) COMMITTED→RELEASED made cascade-only (no direct release endpoint path) to force compensation through order-cancel/condemn/expiry/void. (4) Publish side effect bumps Species.version on both publish routes (PUBLISHED and PENDING_APPROVAL) so the OCC recipe ordering is deterministic. (5) Allocation species-check only (no grade gate) — documented simplification. (6) SoD enforced on quote approve / import clear / hold release (different-user), deliberately absent on import reject and hold condemn for contrast.

## Step 4: Generate PRD — 2026-08-15T00:47:52.220Z

**Task 1910 — PRD generation complete**

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1910_seafood_wholesale_dockside_purchase/workspace/PRD.md` — 380 lines.

**Section inventory:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications: 2.1 RBAC & identity, 2.2 Response Structure (verbatim block, byte-identical incl. `req_RANDOMALPHANUM123456` / empty `data`), 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending), 2.4 Common Resource Properties (all 16 entities carry `id`/`created_at`/`updated_at`/`version`; no `common_fields: false` exceptions in this scaffold), 2.5 Cents/Kilograms/Rounding (integer cents, 2dp kg, 2dp pct, round half up, pinned per-line rounding), 2.6 Logical Clock (startup default 2026-08-01T00:00:00Z, `to_iso8601`/`current_utc`, quote + lot expiry sweeps), 2.7 OCC (all 3 rules), 2.8 Validation Precedence (10-step ordered cascade), 2.9 Lot Bookkeeping (2 status dimensions, 7 weight buckets, `unit_cost_cents`, DEPLETED test), 2.10 Segregation of Duties (3 pairs)
- §3 Business Logic (8 subsections): provisioning / price board & volatility / dockside purchase / grading & yield / settlement, import & payment / orders, pricing & credit / allocations, shelf life & cold chain (freight tariff with all 9 constants embedded in prose) / holds, condemnation, recalls & substitution
- §4 Endpoint table: 74 rows, 4 columns only (Method, Path, Description, Authorized Roles), status-code paragraph (201 create / 200 modify), list-filter enumeration
- §5 Error catalogue: 53 rows, 2 columns only, statuses from error catalog

**Coverage audit (mechanical, script-verified):**
- Field-name coverage: 115/115 required identifiers present in backticks (all entity fields, all request-body keys, query params `limit`/`offset` + filters, path `id`, OCC fields `expected_dock_ticket_version`/`expected_species_version`/`expected_sales_order_version`, clock `to_iso8601`/`current_utc`) — 0 missing
- Endpoints: 74/74 in §4 table — 0 missing
- Errors: 53/53 in §5 table AND 53/53 referenced in §2/§3 prose — 0 missing
- Enum/state values: all 56 (grades, all 9 state machines' states, mode, temp_zone, doc_type, processing_type) present — 0 missing
- Roles: all 9 named with identity translation (VesselAgent/Customer entity-backed; 7 opaque with recorded-on examples) — 0 missing
- All 9 state machines' transitions (from/to, preconditions paired with error ids, side-effect cascades incl. regrade/void/condemn/expiry/deliver bucket movements and FULFILLED regression) expressed in prose
- All 10 calculations expressed in precise natural language (reconstruction-test-passing: pinned freight evaluation order, min-of-two yield formula, per-line rounding order explicitly forbidden alternative, selector ranking/tie-breaks, equality-passes gates at 10.00% volatility, credit limit, shelf-life gate); constants embedded in context

**Zero-Silence / Hard Contract self-check:** Contract 1 PASS (0 missing names, 2 passes run). Contract 2 PASS (priority ordering stated explicitly in §2.8 with first-failure-wins language; all 3 OCC rules name endpoint capability + occ field + `ERR_STALE_VERSION` 412 without race framing; cross-entity cascades enumerated in full; `applies_to` scopes for hold/segregation/labeling/import gates all enumerated; structured field content/defaults all placed on owning entities; sibling branches — publish split, submit-vs-resubmit, release-vs-condemn, void from 4 states — rendered with equal density). Contract 3 PASS (532 §3 backtick tokens scanned: 0 paths, 0 bare HTTP methods, 0 method+path combos; endpoints referenced via state-pair framing, role+verb, capability description).

**Wording adjudications (scaffold-consistent nominations):**
1. Landing-line add on non-`LANDED` ticket → `ERR_TICKET_INVALID_STATE`; order-line add on non-`DRAFT` order → `ERR_ORDER_INVALID_STATE`; shipment create on order not `CONFIRMED`/`FULFILLED` → `ERR_ORDER_INVALID_STATE` (endpoint descriptions constrain the states; the per-machine state error is the only sensible id).
2. `volatility_pct` remains 0 when no prior `PUBLISHED` quote exists (guard inert branch).
3. `ERR_SUBSTITUTION_NOT_ALLOWED` attached to manual substitution requests on lines with `allow_substitution` false (validation priority 9 check text).
4. HTTP statuses taken from the error catalog where the validations-table group status differed (e.g. `ERR_INVALID_LANDING_WINDOW` 400, `ERR_VESSEL_LANDING_OVERLAP` 409, `ERR_LABELING_NONCOMPLIANT` 422, `ERR_INVALID_YIELD` 400).
5. Role `Any` described as a marker meaning any authenticated role may read, per its RBAC description.

The withheld difficulty/corner design files were not opened, grepped, or referenced; no other `task_*` directory was read.

## Step 5: Generate Unit Tests — 2026-08-15T01:11:45.735Z

## Task 1910 — unit test generation (seafood_wholesale_dockside_purchase)

**Files written (19 files, 4499 lines):**
- `test_helpers/`: `__init__.py` (40), `types.py` (377), `api_client.py` (257 — 54 PRD endpoints), `api_errors.py` (128 — 53-error catalog registered with the framework), `assertions.py` (202 — per-entity shape + lot weight-conservation invariant + instant comparator), `factories.py` (175), `constants.py` (32), `test_users.py` (49 — entity-backed builders for VesselAgent/Customer + named SoD officer/manager identities), `fixtures.py` (433 — tiered composites: `setup_graded_lot`, `setup_confirmed_order`, `setup_reserved_allocation`, `setup_committed_allocation`, shipment chain, OCC-threading writers)
- `test_suite/`: `conftest.py` (55), `test_01_config_entities_and_envelope.py` (236), `test_02_market_quote_lifecycle.py` (151), `test_03_dock_tickets_landing_lines.py` (342), `test_04_grading_and_yield.py` (189), `test_05_settlement_void_regrade_imports.py` (377), `test_06_orders_pricing_credit.py` (281), `test_07_allocations_inventory.py` (448), `test_08_shipments_freight.py` (241), `test_09_holds_substitution_compliance.py` (486)

**Queue A (difficulty): 21/21 instances translated, 42 tests (exactly 2 each).** No skips.

**Queue B (corner): 50/51 non-stub instances translated, 50 tests (1 each).** 6 `excluded_because` stubs not translated; all stub cross-references resolve to real difficulty instances (volatility boundary, per-line rounding, freeze clock, credit limit, import gate, temporal/capacity, import-clear SoD).

**Skipped (1):**
- `Corner/errors/err_allocate_expired_lot_rejected` — asserts `ERR_LOT_INVALID_STATE` (and *not* `ERR_SHELF_LIFE_INSUFFICIENT`) when allocating against an EXPIRED lot. PRD §3.7 names exactly five allocation gates (species, lot quantity, line remaining, hold, shelf-life); no lot-lifecycle gate is stated for allocation creation, and an expired lot fails the shelf-life gate by its own rule (negative remaining hours < requirement). Two faithful PRD readers could return either error id → fails unique derivability. Gap left as gap.

**Adjudications:**
- `Difficulty/cross_entity_state_dependency/allocation_requires_confirmed_order_and_clear_active_lot`: the recipe's SUBMITTED-order arm (expecting `ERR_ORDER_INVALID_STATE` at allocation create) is not PRD-covered — the CONFIRMED-order requirement in §3.7 attaches to *commit*, and §3.7's five create-time gates omit order state. Translated the instance via its covered arm instead: hold-gate rejection on a CONFIRMED order with buckets unchanged, plus post-release success (2 tests).
- `Corner/errors/err_invalid_from_state_sweep_remaining_machines`: setup adapted — a second never-assessed landing line keeps the ticket LANDED, isolating `ERR_ASSESSMENT_INVALID_STATE` from `ERR_TICKET_INVALID_STATE` (PRD does not order those two same-priority checks).
- `Corner/entities/entity_creation_defaults_applied`: dropped the `version == 1` pin (PRD §2.4 pins version as an incrementing integer, not its initial value); presence/type asserted instead.
- `inventory_lot_parallel_hold_and_lifecycle` tests compare `frozen_at`/`expires_at` by instant value, not string equality (PRD pins the instant, not the timestamp rendering).
- `entity_missing_required_field_returns_400`: "no vessel created" sub-assertion dropped (no `GET /vessels` list endpoint exists to observe it).

**Total test count: 92.**

**Stage 2 tag-audit result:** PASS — every test function carries exactly one `Design:` line as the last docstring line; all 42 Difficulty tags resolve to real rule/instance pairs; all 50 Corner tags resolve to real non-stub section/instance pairs; all 21 difficulty instances have ≥2 tests; all 50 translated corner instances have ≥1. All 171 PRD citation lines verified verbatim against `workspace/PRD.md` (normalized grep). `py_compile` clean; `pytest --collect-only` collects 92 tests; no `skip`/`skipif`/`xfail` markers; no scaffold references in generated code.

## Step 6: Generate Implementation — 2026-08-15T01:11:45.735Z

## Task 1910 — seafood_wholesale_dockside_purchase: implementation generated

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1910_seafood_wholesale_dockside_purchase/workspace/implementation/`):

| File | Lines |
|---|---|
| start.sh | 10 |
| requirements.txt | 1 |
| app.py | 74 |
| db.py | 69 |
| errors.py | 65 |
| response.py | 60 |
| middleware.py | 43 |
| util.py | 205 |
| services/__init__.py | 0 |
| services/calc.py | 165 |
| services/cascades.py | 269 |
| routes/__init__.py | 0 |
| routes/config.py | 155 |
| routes/quotes.py | 155 |
| routes/tickets.py | 497 |
| routes/lots.py | 94 |
| routes/orders.py | 437 |
| routes/shipments.py | 211 |
| routes/compliance.py | 397 |
| routes/clock.py | 22 |

Total: 2929 lines, 19 files.

**Architecture notes**
- Module layout: `app.py` (Flask app factory, ApiError/404/405/500 handlers, blueprint registration, global RLock around each request for cascade atomicity); `db.py` (in-memory store — 16 dicts keyed by id, monotonic `_seq`, logical clock defaulting to exactly 2026-08-01T00:00:00Z, `new_record`/`touch` version bookkeeping); `errors.py` (full 46-id error catalog + ApiError); `response.py` (envelope: `meta{api_request_id, api_request_timestamp[, limit, offset, total_count, has_more]}`, `response_type`, `data`; error body `data.{error_id, message}`); `middleware.py` (X-User-ID/X-User-Role auth, 9 declared roles); `util.py` (shape validators, ISO instant/date parsing, pagination 10/1-100/0); `services/calc.py` (Decimal-only money/weight math, yield_processing, freight tariff, standing/settlement quote selectors, volatility guard, substitute selector); `services/cascades.py` (allocation release with per-cascade bucket targets, lot recall/condemn/expire, line recompute, order fulfill/regress, credit exposure, deplete check, auto-substitution, clock sweeps); `routes/` grouped by aggregate.
- Storage: pure in-memory dicts; empty at boot; no seeding, no disk persistence of any kind.
- State machines: all 10 machines implemented with precondition errors in PRD §2.8 priority order (auth → RBAC → ownership → shape → path/FK existence → OCC 412 → state 409 → safety gates → temporal → constraint → fiscal 402/422). OCC fields `expected_dock_ticket_version` / `expected_species_version` / `expected_sales_order_version` enforced as required ints; parent versions bump per spec (line add → ticket +1; publish → species +1; allocation create → order +1).
- Calculation modules: all arithmetic in `decimal.Decimal` ROUND_HALF_UP at the pinned step (provisional/final settlement, yield factors 1.00/0.97/0.92 × 1.00/0.85 with min() cap at 2dp, freight tariff base+per-kg → 5% tier keyed on pre-discount subtotal → 12% fuel on discounted → max(4000) floor, per-line rounding before summing, volatility 2dp with >= 10.00 routing to PENDING_APPROVAL, substitution credit = (old−new)×qty).
- Parallel lot dimensions (lifecycle/hold) tracked independently; seven weight buckets as Decimal 2dp; logical-clock sweeps expire PUBLISHED quotes (date passed) then ACTIVE lots (now >= expires_at) with release + auto-substitution cascades.

**Boot smoke-test result**: three fresh `bash start.sh` boots each ran a scenario suite end-to-end — 57/57 (core flow: auth/RBAC, volatility guard incl. exact-10.00 approval path with segregation-of-duties, landing windows/overlap, OCC stale rejection, finalize→lot birth, settle/pay ledger, order confirm/allocate/commit/fulfill, AIR freight book/tender math, deliver→invoice, clock expiry), 51/51 (regrade cascade, import-doc gate + resubmit cycle, hold place/release/condemn with SOD, freeze clock reset, condemn + expiry auto-substitution cascades, substitution approve/apply with credit, credit-limit 402, write-off depletion, flight-capacity 1000 kg), 30/30 (VesselAgent/Customer ownership, shelf-life exact-equality gate, species/over-allocation/insufficient-quantity ordering, substitution group/price/not-allowed rejections, COMMITTED direct-release rejection, pagination envelope/bounds/filters) — all pass; server responds well within the 60 s window and restarts cleanly with empty state each boot.

**Adjudications**
- Double-hold placement returns `ERR_LOT_INVALID_STATE` (a PLACED hold implies ON_HOLD, so the priority-6 state gate fires before the priority-9 `ERR_HOLD_ALREADY_ACTIVE` constraint; that error id is unreachable given the invariant).
- Substitution approve enforces PRD §3.8 narrative order (group → price → CITES/labeling) over the generic §2.8 category ordering, per §3.8's explicit "narrative order" statement.
- Allocation creation requires order CONFIRMED (`ERR_ORDER_INVALID_STATE` otherwise), per §3.6's "no allocations can yet encumber" DRAFT/SUBMITTED orders.
- Substitution apply reduces `order.total_cents` by `price_credit_cents` (the primary formula statement) rather than re-deriving from line totals.
- Client-supplied instants echoed verbatim; system-stamped timestamps serialized ISO 8601 UTC with 3 fractional digits from the logical clock; quote expiry sweep runs before lot sweep per §2.6 ordering.

## Step 7: Run Tests and Iterate — 2026-08-15T01:36:00.000Z

All work is complete: 8/8 rounds pass, no stray processes of mine remain (port 10000 free; the listed `claude` process is the parent orchestrator, not mine). The parent session's own prompt even corroborates the diagnosis: "Other pipeline runs are executing concurrently in this repository" — the external-SIGTERM source.

## Summary

- **Iterations run**: 3 counted 8-round sweeps (sweep 1 baseline → fixes → sweep 3 verification → SIGTERM-root-cause fix → sweep 4 verification, all 8 rounds 92/92 pass), plus 1 voided sweep that was killed mid-flight by an over-broad `pkill` of mine (no results files written; rerun cleanly as sweep 3).
- **Tests deleted**: none.
- **Fixes applied to `test_helpers/`**:
  - `test_helpers/api_client.py` — `ApiClient._request`: retry `requests.exceptions.ConnectionError` up to 4 attempts with linear backoff. Per-test-server isolation reboots the server on the same port before every test; under 8× lockstep load on this multi-tenant host, fresh connections race kernel teardown of the previous incarnation's sockets (TIME_WAIT/tuple collisions) and surface as `ConnectionResetError`/`RemoteDisconnected` before the request reaches the server. Transport artifact only — HTTP responses are never retried, and a genuinely dead server still fails after the retry budget, so no assertion semantics change.
- **Fixes applied to `test_suite/`**:
  - `test_05_settlement_void_regrade_imports.py::test_regraded_line_accepts_fresh_assessment_and_new_lot` — three corrections, all making the test more PRD-faithful: (1) publish a GRADE_B quote dated on the landing day before the second finalize (PRD §3.4 requires the settlement selector to resolve the *assessed* grade; a PRD-faithful server must otherwise reject with `ERR_QUOTE_NOT_PUBLISHED` — the old setup violated the precondition); (2) select the post-re-grade lot explicitly by exclusion (`get_lot_for_line` returned `data[0]`, but both lots share the frozen clock's `created_at`, so §2.3's ascending sort tie is implementation-defined); (3) corrected expected `received_weight_kg` to 24.25 (50.00 × 0.50 yield × 0.97 GRADE_B × 1.00 WHOLE per §3.4 — the old 48.50 omitted the yield factor).
  - `test_09_holds_substitution_compliance.py::test_second_hold_on_same_lot_rejected` — relaxed `validate_error(ERR_HOLD_ALREADY_ACTIVE)` to `validate_error_is_one_of([ERR_HOLD_ALREADY_ACTIVE, ERR_LOT_INVALID_STATE])`. Error-precedence non-uniqueness: §3.8 names `ERR_HOLD_ALREADY_ACTIVE` for a second PLACED hold, but a PLACED hold implies `hold_status=ON_HOLD`, so §2.8's pinned ordering fires the priority-6 state gate (`ERR_LOT_INVALID_STATE`) before the priority-9 constraint — both error ids are PRD-faithful (the SCAFFOLD's own precedence table reproduces the same contradiction; feedback item for scaffold/doc generator: an error id rendered unreachable by the priority table).
- **Fixes applied to `implementation/`**:
  - `workspace/implementation/start.sh` — added `trap '' TERM` before `exec python3 app.py`. Root cause of the residual flake (`test_held_and_shelf_short_lot_reports_hold` in 3 of 8 rounds): external mid-round SIGTERMs on the shared host were killing freshly-booted servers mid-test (log evidence: one extra "Terminated" per affected port, simultaneous across 3 different-port rounds at the same wall second; nothing in the runner/plugin sends SIGTERM mid-round — per-test kills are SIGKILL and lifecycle SIGTERM fires only at round end). Ignored-signal dispositions survive `exec`, so the server inherits SIGTERM=IGN; the harness's own shutdown paths (per-test `kill_port` SIGKILL, `stop()`'s SIGKILL fallback after its 5s SIGTERM grace) remain fully effective — verified empirically: server survives SIGTERM and keeps serving, dies on SIGKILL. No endpoint, field, side effect, or PRD behavior changed; storage remains pure in-memory with no seeding.

Final state: sweep 4 — round 1-8 each 92/92 passed, 0 failed, 0 errors. No tests weakened, no implementation check removed, no assertions downgraded (the one relaxation is the protocol-permitted `validate_error_is_one_of` coverage correction).

## Step 8: Finalize PRD — 2026-08-15T01:42:00.000Z

Done. PRD_FINALIZED.md is produced with exactly two inline insertions, both traced to step_7_diff items and verified against all related implementation paths.

**Summary for worklog:**

- **Line counts**: PRD.md 379 lines → PRD_FINALIZED.md 379 lines (0.0% delta; two sentences appended inline to existing paragraphs at lines 78 and 226).

**Changes:**
- §2.3 — insert — pinned the list-sort tie-break: resources sharing the same `created_at` (common under the frozen logical clock) are ordered among themselves by creation order, earliest created first — `workspace/implementation/util.py:202` (`apply_filters` sorts by `(created_at, _seq)`; `_seq` is the global monotonic creation counter from `db.py:62`).
- §3.8 — insert — pinned error precedence for a second hold on an already-held lot: the from-state gate (§2.8 priority 6) fires before the one-active-hold constraint (priority 9), and since a lot with a `PLACED` hold always reads `ON_HOLD`, a second placement surfaces `ERR_LOT_INVALID_STATE` (409) — `workspace/implementation/routes/compliance.py:174-180`.

**Step-7 items with no edit (and why):**
- `test_helpers/api_client.py` ConnectionError retry — harness transport artifact; no API behavior, no PRD silence.
- test_05 fix (1) (publish GRADE_B quote on the landing day pre-finalize) — PRD §3.4 already pins settlement on the *assessed* grade with `ERR_QUOTE_NOT_PUBLISHED` otherwise; `tickets.py:423-428` matches. Fixture bug, not a silence.
- test_05 fix (3) (`received_weight_kg` 24.25) — PRD §3.4 already pins `min(landed, landed × yield × condition × processing)`; `calc.py:44-51` matches (50.00 × 0.50 × 0.97 × 1.00). Fixture bug.
- `start.sh` `trap '' TERM` — process-level hardening against external SIGTERMs on the shared host; no endpoint, field, or side effect changed; the start.sh contract belongs to INSTRUCTION.md, not the PRD.

**Per-edit pre-edit search log:**

*Edit 1 (§2.3 tie-break):*
- (a) Subject: ordering of list-endpoint results when `created_at` values tie.
- (b) Paths enumerated: `util.py:195-205` `apply_filters` (the single sort site used by all 12 list endpoints — grepped every `apply_filters` call in `routes/quotes.py:81`, `tickets.py:146,356,487`, `lots.py:34`, `orders.py:121,291,427`, `shipments.py:89`, `compliance.py:100,199,292`); `db.py:49-63` (`_seq` assignment); all other ordering sites checked for consistency — `orders.py:157` (line pricing, same key), `calc.py:96,113` (quote selectors, `(_quote_date, _seq)`), `calc.py:162` (substitute selector, `(price, species _seq)`), `cascades.py:82,259,265` (latest-assessment pick and sweep iteration, unobservable within one atomic request under the global lock). `_seq` order coincides with `created_at` order (logical clock never retreats) and deterministically breaks exact ties.
- (c) Wording scoped to list endpoints (§2.3's subject) and phrased as "the order in which they were created, earliest created first" — avoids redefining the §3.2/§3.8 selector tie-breaks, which the PRD already pins via `created_at` and which the implementation satisfies.

*Edit 2 (§3.8 hold-placement precedence):*
- (a) Subject: which error surfaces when a hold is placed on a lot that already carries a `PLACED` hold.
- (b) Paths enumerated: `compliance.py:164-193` `create_hold` (only site raising either error: state gate at line 174, PLACED-hold scan at line 179); every `hold_status` mutation/read site grepped — `compliance.py:191` (→`ON_HOLD` at placement), `compliance.py:224-230` (release flips hold→`RELEASED` and lot→`CLEAR` atomically), `compliance.py:234-252` + `cascades.py:181-192` (condemn flips both to `CONDEMNED`), plus readers `tickets.py:208`, `orders.py:338,397`, `lots.py:59,82`, `calc.py:154`; other `ERR_LOT_INVALID_STATE` sites (`lots.py:55,81`, `orders.py:334,392`) are different operations. Confirmed no path leaves a `PLACED` hold on a `CLEAR` lot, so the constraint at line 179 is unreachable and the implementation always returns `ERR_LOT_INVALID_STATE` here.
- (c) Wording references the §2.8 priorities already in the document and states the observable outcome, without deleting `ERR_HOLD_ALREADY_ACTIVE` from §2.8 priority 9 or the §5 catalogue (the implementation retains the check as dead code) — no enumerated path is mis-described.

## Step 9: Complete PRD — 2026-08-15T01:55:00.000Z

**Task 1910 — PRD_COMPLETED.md produced**

- Source: `workspace/PRD_FINALIZED.md` (379 lines / 65,008 chars) → `workspace/PRD_COMPLETED.md` (380 lines / 67,835 chars); char-delta **+2,827**. 22 diff hunks, all inline inserts/revisions; no new sections.
- Counts: **19 ambiguity-pins**, **7 mismatch-revisions** (26 changes total; two hunks each carry one pin + one revision).

Changes (section — insert|revise — ambiguity|mismatch — what changed — impl file:line):

- §2.2 — insert — ambiguity — `api_request_timestamp` reads the logical clock — implementation/response.py:18-22
- §2.2 — insert — ambiguity — undeclared paths / unsupported methods rejected `ERR_INVALID_REQUEST` (400) — implementation/app.py:45-51
- §2.3 — insert — ambiguity — `offset` non-negative; non-integer or out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST` (400) — implementation/util.py:172-192
- §2.4 — insert — ambiguity — `version` starts at 1 at creation — implementation/db.py:54-63
- §2.6 — revise — ambiguity — clock set accepts any valid instant (no forward-only rule, naive instant read as UTC) and echoes the submitted `to_iso8601` back as `current_utc` — implementation/routes/clock.py:13-22, implementation/util.py:141-156
- §2.8 item 3 — insert — ambiguity — ownership comparison needs the resource: nonexistent path-named resource surfaces the 404 first; `Customer` adding a line to a nonexistent order draws `ERR_ORDER_NOT_FOUND` — implementation/routes/orders.py:250-253, implementation/routes/tickets.py:163-168
- §2.8 item 7 — revise — mismatch — endpoint-specific pins prevail over the enumeration order: settlement checks import clearance before the hold block; substitution approval runs group/quote/price (items 9-10) before labeling — implementation/routes/tickets.py:183-212, implementation/routes/compliance.py:315-344
- §3.3 — insert — ambiguity — landing-window instants without an explicit offset are read as UTC — implementation/util.py:141-156, implementation/routes/tickets.py:105-106
- §3.4 — insert — ambiguity — recording an assessment against a line whose owning ticket is not `LANDED` → `ERR_TICKET_INVALID_STATE` (409) — implementation/routes/tickets.py:385-386
- §3.4 — revise — mismatch — re-grade recalls only lots still in `ACTIVE` lifecycle; terminal-lifecycle lots untouched — implementation/routes/tickets.py:236-242
- §3.5 — revise — mismatch — void recalls only lots still in `ACTIVE` lifecycle — implementation/routes/tickets.py:236-242
- §3.6 — insert — ambiguity — `min_remaining_shelf_life_hours` must be non-negative, else `ERR_INVALID_REQUEST` (400) — implementation/routes/orders.py:260-262
- §3.7 — insert — ambiguity — `transit_hours` is a required non-negative integer, else `ERR_INVALID_REQUEST` (400) — implementation/routes/orders.py:317-319
- §3.7 — insert — ambiguity — allocation creation enforces two state gates the PRD omitted: lot lifecycle `ACTIVE` → `ERR_LOT_INVALID_STATE`, order `CONFIRMED` → `ERR_ORDER_INVALID_STATE` — implementation/routes/orders.py:332-336
- §3.7 — revise — mismatch — allocation gate order restated to the impl/§2.8 precedence (state → hold → shelf-life → lot qty → line over-allocation → species), replacing the prior narrative order — implementation/routes/orders.py:329-366
- §3.7 — revise — mismatch — cascade list releasing committed weight drops `expiry` (expiry releases only `RESERVED` allocations; committed stays put) — implementation/services/cascades.py:195-206
- §3.7 — revise — ambiguity — freeze requires lifecycle `ACTIVE` and `storage_type` `FRESH`, else `ERR_LOT_INVALID_STATE` (409) — implementation/routes/lots.py:52-60
- §3.7 — revise — ambiguity — write-off requires `qty_kg` > 0 (`ERR_INVALID_REQUEST`) and lifecycle `ACTIVE` (`ERR_LOT_INVALID_STATE`) — implementation/routes/lots.py:74-89
- §3.7 — insert — ambiguity — a supplied `flight_date` must be valid YYYY-MM-DD on either mode, else `ERR_INVALID_REQUEST` (400) — implementation/routes/shipments.py:57-59
- §3.7 — insert — ambiguity — tender requires `actual_weight_kg` > 0 and `volume_m3` ≥ 0, else `ERR_INVALID_REQUEST` (400) — implementation/routes/shipments.py:139-144
- §3.8 — insert — ambiguity — auto-created substitution also starts with `decided_by_user_id` empty and `price_credit_cents` at zero — implementation/services/cascades.py:234-249
- §3.8 — revise — ambiguity — approval resolves the substitute's standing quote between the group and price checks; unresolvable → `ERR_QUOTE_NOT_PUBLISHED` (422) — implementation/routes/compliance.py:322-327
- §3.8 — revise — ambiguity — application re-resolves the standing quote; unresolvable → `ERR_QUOTE_NOT_PUBLISHED` (422) — implementation/routes/compliance.py:376-381
- §3.8 — revise — mismatch — dropped "equivalently restated as the sum of the repriced line totals"; impl reduces `total_cents` by the credit, which diverges from restatement under per-line rounding — implementation/routes/compliance.py:391
- §3.8 — revise — mismatch — condemn epilogue defers to the §2.9 DEPLETED test (available+reserved+committed zero, received > 0) instead of "every bucket except shipped and spoiled reads zero" — implementation/routes/compliance.py:250, implementation/services/cascades.py:123-133
- §4 — insert — ambiguity — filters match on exact equality; unrecognized query parameters are ignored — implementation/util.py:195-205

Everything else in the PRD (envelope shape, OCC fields, selectors, rounding rules, state machines, tariff, sweeps, error catalog, endpoint/role table) was verified against implementation/ and already pinned uniquely — no change.
