# Worklog — task_0331_furniture_mattress_retail_delivery

Scenario: Furniture & Mattress Retail with Delivery: catalog & configuration (fabric/size), financing/lease-to-own, delivery scheduling & route, assembly/haul-away add-on, white-glove vs threshold, damage/return window, warranty/protection plan, special-order lead time.

Scaffold difficulty: Expert (passed only to prd-bench-scaffold-generator).

## Step 1: Create task directory — 2026-06-13T00:00:00.000Z

Created `tasks/task_0331_furniture_mattress_retail_delivery/` and `workspace/` subdirectory. Verified prd-bench skills present and `prd-bench-local-run` on PATH.

## Step 2: Generate scaffold (Expert) — 2026-06-13T00:00:00.000Z

All three files are structurally valid, the file split is honored, the lint is clean, and all counts land in the Expert band. The scaffold is complete.

Generated a complete **Expert**-difficulty scaffold for **Furniture & Mattress Retail with Delivery** — three files, all passing `scaffold_lint.py` (`VERDICT: clean lint`, 497 calls scanned).

**Complexity profile:** `workflow_orchestration` + `pricing_engine`; flat entity topology; parallel/cyclic/branching state shapes; peer-role RBAC; layers = dual-variant calc, temporal windowing, cascading side-effects, optimistic concurrency, derived-field reconciliation.

**SCAFFOLD.yaml contents:**
- **10 entities:** Customer, Product, Order (parallel `payment_status × fulfillment_status`), OrderLine, FinancingPlan, Payment (`common_fields:false`), DeliveryRoute, DeliveryStop, ProtectionPlan, ReturnRequest
- **5 state machines:** Order (parallel axes), FinancingPlan (cyclic CURRENT↔PAST_DUE + payoff/default), ReturnRequest (branching-with-revert), DeliveryRoute (linear+capacity), DeliveryStop (linear+bubble-up)
- **13 calculation rules** incl. dual-variant `financing_monthly_payment` (installment interest vs lease markup) and `financing_payoff_balance` (sum-of-digits rebate vs no-rebate), `order_grand_total` (pinned sum-then-round tax), `return_refund`, `protection_premium`, tier-based `return_window_deadline`
- **21 validations** (priority-ordered, with deliberate priority conflicts), **49 endpoints** (incl. all FK reverse-reachability GETs + 1 `/_clock` test-driving endpoint), **31 errors**
- **4 roles** (SalesAssociate/StoreManager/DeliveryDispatcher opaque; Customer `entity_backed:Customer`)
- **2 concurrency rules** (OCC: `stop-book-stale-route`, `financing-apply-stale-order`)

**§1.8 SCAFFOLD_DIFFICULTY_DESIGN.yaml:** 9 rules × 2 = **18 instances**, all with executable `setup_api_calls` chains and code-computed literal asserts (e.g., payoff 90026 vs 113881 Δ23855; grand-total 156746; DTI inclusive-boundary 0.43 at income 25400).

**§1.9 SCAFFOLD_CORNER_DESIGN.yaml:** **36 active instances + 3 `excluded_because` stubs** across all 9 claim-extraction sections; every stub's `difficulty_instance` reference resolves; zero duplicate names across both design files.

Files: SCAFFOLD.yaml (1340 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1105 lines), SCAFFOLD_CORNER_DESIGN.yaml (1514 lines).

## Step 3: Copy INSTRUCTION.md — 2026-06-13T00:00:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-13T00:00:00.000Z

Generated PRD at `workspace/PRD.md` (~6,700 words, 288 lines). Read only SCAFFOLD.yaml — neither design file opened.

Sections: §1 Introduction (independent payment × fulfillment axes; integer-cents server-computed money); §2 Global Specs (RBAC 4 roles, 3 opaque + Customer entity-backed; §2.2 envelope; pagination; common/derived fields incl. Payment id/created_at only; monetary precision; two order status dimensions; capacity/scheduling ledger; cascades; nested-retrieval + validation priority chain; OCC); §3 Business Logic (12 scattered workflow subsections); §4 Endpoint table (all 49); §5 Error catalogue (all 31).

Hard Contracts all PASS: field coverage 73/73; rule coverage (validations priority chains, 2 OCC, state machines parallel/cyclic/branching, 11 calcs single-vs-ceil rounding, cascades, sibling-branch symmetry) 0 missing; path purity §3 (425 backtick tokens, 0 path/method tokens) PASS. File ends at §5, no audit footer.

## Step 5: Generate unit tests — 2026-06-13T00:00:00.000Z

NOTE: the Step 5 subagent's final API call dropped on a socket error ("The socket connection was closed unexpectedly") AFTER writing all artifacts, so no verbatim summary was returned. Orchestrator verified completeness directly instead:
- test_helpers/ complete: __init__.py, api_client.py, api_errors.py, assertions.py, constants.py, factories.py, fixtures.py, test_users.py, types.py (9 files).
- test_suite/: conftest.py + 7 test files (test_01_catalog_and_intake, test_02_order_lifecycle, test_03_pricing_and_totals, test_04_financing, test_05_delivery, test_06_returns_and_protection, test_07_security_and_listing).
- 80 test functions, all 80 carry a 1:1 `Design:` tag (no untagged / no dual-tagged). Queue A (Difficulty) = 34, Queue B (Corner) = 46.
- All test_helpers + test_suite files compile under py_compile; no file truncated mid-statement.

## Step 6: Generate implementation — 2026-06-13T00:00:00.000Z

Built a complete Python + Flask in-memory REST API at `workspace/implementation/`.

Source files (24): Infrastructure — app.py, db.py (in-memory dicts), errors.py, response.py, middleware.py (auth+RBAC), helpers.py, clock.py. Services — services/calculations.py (11 calc rules), services/domain.py (cross-entity recompute), services/serializers.py. Routes (9 blueprints): customers, products, orders, order_lines, financing, delivery_routes, delivery_stops, protection_plans, return_requests, clock_admin. Plus start.sh, requirements.txt.

51 endpoints implemented (all entities, transitions, FK reverse-reachability lists, test clock) matching PRD §4.

State machines/calcs/OCC: Parallel Order machine (independent payment_status & fulfillment_status axes, system bubble-up from DeliveryStop complete/cancel); cyclic FinancingPlan (PENDING_APPROVAL→CURRENT↔PAST_DUE→PAID_OFF/DEFAULTED, gated approval credit→DTI→open-plan priority, pinned principal snapshot, payment routing self-loop/catch-up/payoff); branching-with-revert ReturnRequest; linear Route/Stop with cascades. Calculations use Decimal + ROUND_HALF_UP, single-rounding on combined bases (tax sum-then-round, sum-of-digits rebate), integer ceiling for monthly payments. OCC: expected_route_version/expected_order_version vs live parent version → ERR_STALE_VERSION (412), applied last per validation priority. Guard ordering follows PRD prose authority.

start.sh: reads $PORT (default 10000), binds 0.0.0.0, runs `python3 app.py` foreground via exec, pip install guarded behind flask-import check. In-memory only (module-level dicts; no SQLite/JSON/disk), nothing seeded at boot.

## Step 7: Test-iterate-fix loop — 2026-06-13T00:00:00.000Z

All 8 parallel rounds pass 80/80 with zero failures in the union. Clean sweep. Exiting the loop.

**Iterations run:** 2 (initial baseline + 2 fix rounds), final 8-round sweep clean at 80/80 across all rounds.

**Tests deleted:** None. Every failure traced to a PRD-faithful rule (coverage + unique derivability both held); all were test-helper consistency bugs or one implementation precedence bug.

**Root causes (two distinct, both stable across all 8 rounds — not flaky):**

1. **14 tests (12 in `test_05_delivery.py`, 2 in `test_02_order_lifecycle.py`) failed with `ERR_LEAD_TIME_NOT_MET` during setup.** Triage hint applied: ≥5 tests sharing one setup error → test_helpers first suspect. PRD §3.4 defines `earliest_schedulable_date` = order's `created_at` date + max special-order `lead_days`; §3.8 rejects booking when route `service_date` < that date. The route factory hard-codes `service_date: 2026-03-01`, but these tests never pinned the test clock, so orders were created at real wall-clock time (2026-06-13), producing an esd far past the route date. The implementation rejected correctly; the fixtures constructed a self-inconsistent precondition. STEP 2 test-layer bug.

2. **1 test (`test_cancel_order_with_active_stop_rejected`) got `ERR_INVALID_STATE` instead of `ERR_STOP_ACTIVE`.** STEP 1b unique-derivability held: booking a stop forces the order `CONFIRMED → SCHEDULED` (§3.8), so an order carrying a BOOKED/DISPATCHED stop is always SCHEDULED, never DRAFT/CONFIRMED. The implementation's state-gate-first ordering made the PRD-named `ERR_STOP_ACTIVE` outcome structurally unreachable — contradicting §3.11's explicit declaration that an active stop blocks cancellation with that error. PRD uniquely determines the stop-active check must precede the state gate. STEP 3 implementation fix.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — `setup_delivered_order()`: added a clock pin to the route anchor date (new `deliver_iso` param defaulting to `2026-03-01T09:00:00Z`) before order creation, so the created_at-date-based esd stays on/before the route service_date. Fixed both `test_02` failures.
- `test_helpers/fixtures.py` — `setup_approved_return()`: now threads its `deliver_iso` through to `setup_delivered_order()` instead of double-setting the clock.

**Fixes applied to `test_suite/`:**
- `test_suite/test_05_delivery.py` — local `_confirmed_order()` helper: pinned the clock to `2026-03-01T09:00:00Z` before order creation (idempotent with the explicit pins the passing tests already do). Fixed all 12 `test_05` failures.

**Fixes applied to `implementation/`:**
- `workspace/implementation/routes/orders.py` — `cancel_order()`: reordered guards so the `active_stops_for_order` check (→ `ERR_STOP_ACTIVE`) runs before the DRAFT/CONFIRMED state gate (→ `ERR_INVALID_STATE`), making the PRD-declared `ERR_STOP_ACTIVE` outcome reachable. Verified `test_cancel_delivered_order_rejected` still yields `ERR_INVALID_STATE`. No PRD-required check removed/weakened; no new endpoint/field/seed; storage remains in-memory.

Verified: results.{1..8}.json all passed=80 total=80.

## Step 8: Finalize PRD — 2026-06-13T00:00:00.000Z

PRD_FINALIZED.md created as exact copy of PRD.md; 288 vs 288 lines, 0% delta (byte-for-byte identical). No edits warranted — neither Step 7 root cause maps to a PRD silence or PRD/impl mismatch.

- Root cause 1 (14 ERR_LEAD_TIME_NOT_MET failures): pure STEP 2 test-layer fixture bug (unpinned clock). Impl rejected correctly per PRD §3.4 (esd = created_at date + max special-order lead_days) and §3.8 (reject when route.service_date < esd → ERR_LEAD_TIME_NOT_MET). Verified services/domain.py:77-93 + routes/delivery_stops.py:72-78 match PRD verbatim. No edit.
- Root cause 2 (ERR_STOP_ACTIVE precedence): STEP 3 impl fix that brought code into line with what PRD §3.11 already says (active stop blocks cancel with ERR_STOP_ACTIVE; booking forces CONFIRMED→SCHEDULED per §3.8, so the check must precede the state gate). PRD prose was already correct; impl was wrong and got fixed. Keep prose verbatim. No edit.

NO-NEW-MISMATCH pre-edit search log: both subjects searched globally (lead-time/esd gate across services/domain.py + routes/orders.py + routes/delivery_stops.py; order-cancel guard ordering across cancel_order, active_stops_for_order, all stop transitions, close_order) — PRD wording consistent with every enumerated path; no edits committed.

Verified: PRD_FINALIZED.md identical to PRD.md (diff -q clean).

## Step 9: Complete PRD scan — 2026-06-13T00:00:00.000Z

Walked implementation/ exhaustively (all 10 route modules + calculation/domain/serializer services, helpers, clock, errors, middleware, response envelope). PRD was already tight: all monetary constants, gate thresholds, rounding, state machines, cascades, validation-priority ordering, and response shapes uniquely pinned and matching. Only 4 spots needed alignment across 3 lines.

Source PRD_FINALIZED.md 288 lines / 46,461 chars → PRD_COMPLETED.md 288 lines / 46,904 chars (char delta +443, +0 lines). Ambiguity-pins: 1. Mismatch-revisions: 3.

Changes:
- §3.1 Catalog — revise — mismatch — PRD claimed sku "unique across the catalog" but routes/products.py does no duplicate check; reworded to state server does not enforce uniqueness — implementation/routes/products.py:38-74.
- §3.1 Customers — revise — mismatch — PRD claimed email "unique across customers" but routes/customers.py does no duplicate check; reworded to state server does not enforce uniqueness — implementation/routes/customers.py:14-37.
- §3.8 Booking a stop — insert — ambiguity — PRD never stated white-glove buffer magnitude; impl uses fixed 30 minutes, pinned "a service buffer of 30 minutes" — implementation/services/calculations.py:34 (WHITE_GLOVE_BUFFER_MINUTES = 30).
- §3.8 Booking a stop — revise — mismatch — PRD asserted invariant "at most one BOOKED/DISPATCHED stop per order" but book_stop enforces no per-order stop-uniqueness guard; reworded to note booking accepts a second active stop and leaves an already-SCHEDULED order in SCHEDULED — implementation/routes/delivery_stops.py:31-109.

Left unchanged (already consistent): POST /financing-plans/{id}/payments → 201 with Payment (covered by §4 generic rule + §2.4); unit_load over non-cancelled lines == ACTIVE lines at booking; per-order financing (ERR_FINANCING_EXISTS) and per-line protection (ERR_PROTECTION_NOT_ALLOWED) uniqueness genuinely enforced; all monetary constants/thresholds (assembly 4900, haul 3500, tier 7900/19900, tax 825 bps, installment 1200 bps, lease 1.30×, credit floors 640/600, DTI 43%, max 2 plans, protection 650/300 bps, windows 100/30 days, restock 1500 bps) already explicit and matching.

## Pipeline complete — 2026-06-13T00:00:00.000Z

All 9 steps done. Final state: 80 tests, 8/8 parallel rounds passing 80/80. Artifacts: SCAFFOLD.yaml (+ DIFFICULTY/CORNER design), workspace/PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, test_helpers/ + test_suite/ (80 tests), workspace/implementation/ (Python+Flask, in-memory).
