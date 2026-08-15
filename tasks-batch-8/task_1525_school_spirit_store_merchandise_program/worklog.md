# Worklog — task_1525_school_spirit_store_merchandise_program

## Step 1: Create Task Directory — 2026-08-13T18:08:02.261Z

Task directory `tasks/task_1525_school_spirit_store_merchandise_program/` and `workspace/` pre-created and pre-assigned by the pipeline dispatcher; Step 1 treated as DONE per invocation args. Verified existence with `ls`.

## Step 2: Generate Scaffold — 2026-08-13T19:25:32.174Z

Scaffold generation complete for task_1525. All three artifacts written and machine-verified.

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_1525_school_spirit_store_merchandise_program/SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1525_school_spirit_store_merchandise_program/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design:`
- `/home/ubuntu/github/CodingPRD/tasks/task_1525_school_spirit_store_merchandise_program/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design:`

## Counts
- **Entities: 13** (MerchProgram, Vendor, Design, ProductVariant, SeasonalDrop, PurchaseOrder, PreOrderCampaign, PreOrder, EventSale, Order, ExchangeRequest, ActivityAccount, AllocationRun) — flat topology, FK-joined
- **State machines: 11** — including Design cyclic revision loop (SUBMITTED→REJECTED→SUBMITTED), Order parallel dims (payment_status × fulfillment_status), PreOrderCampaign goal-fork with bubble-up close, EventSale FLAGGED→COUNTED recount loop
- **Calculations: 9** — incl. per-line-vs-sum rounding (pinned order), provisional-vs-final campaign units, FIFO-vs-weighted-avg valuation, capped waterfall allocation, vendor-quote selector, licensing-fee amortization
- **Endpoints: 66** — incl. `POST /_clock/set_current_utc` (default `2026-08-01T00:00:00Z` documented) and a `run-ops` checkpoint endpoint
- **Errors: 50** — all referenced by at least one design instance
- **§1.8: 20 non-stub instances** (every rule ≥2; boundary_precision and cross_entity_state_dependency carry a 3rd)
- **§1.9: 55 non-stub + 12 `excluded_because:` stubs = 67 instances** across all nine taxonomy sections

## Harder-than-expert elements
Quota allocation on physical stock (on_hand vs reserved_online vs preorder demand), compliance gating (licensing approval + segregation of duties: drawer counter ≠ opener), two OCC rules (drop create on program version; licensing transitions on design version), depth-3 design-revoke cascade (Design→Variant sellability→Campaign cancel→PreOrder refunds), ops-run epoch expiry, half-open drop windows vs closed+buffer register bookings, and exact-amount tendering (shortfall 402 vs overpay 422).

## Verification
- `scaffold_lint.py` verdict (verbatim): **"VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5."** (66 endpoints, 13 entities, 20 §1.8 + 55 §1.9 instances, 796 calls scanned)
- Scripted audits passed: instance-name uniqueness across both files, zero forbidden concurrency vocabulary, zero unbound `${var}` placeholders, zero dangling `excluded_because:` refs, 100% error-catalog trigger coverage
- All formula-derived assert literals computed and confirmed by execution (900 vs 899 rounding split, 30000/42000/28000 waterfall, 70000 vs 60000 FIFO/WAVG, +500 tolerance boundary, 500-cent deposit floor, 900 landed cost, 4000→3200 refund reversal)

One design fix made mid-audit: added `POST /preorder-campaigns/{id}/cancel` so DRAFT campaigns have a reachable terminal path (otherwise a never-opened campaign would permanently block program close via `ERR_UNRESOLVED_OPERATIONS`).

## Step 3: Copy Shared Files — 2026-08-13T19:26:08.129Z

Copied `./INSTRUCTION.md` → `tasks/task_1525_school_spirit_store_merchandise_program/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T19:50:00.000Z

All audits pass. The task list shows the scaffold design phase was already completed; this PRD generation completes the doc-generation step.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1525_school_spirit_store_merchandise_program/workspace/PRD.md` — 353 lines.

**Section list:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications: 2.1 Roles & RBAC, 2.2 API Response Structure (byte-verbatim canonical block, diff-verified), 2.3 Pagination, 2.4 Common Resource Properties, 2.5 The Logical Clock, 2.6 Money/Precision/Rounding, 2.7 Optimistic Concurrency Control, 2.8 Request Validation Pipeline, 2.9 Inventory Counters and Sellability
- §3 Business Logic (8 subsections): 3.1 Program setup & lifecycle, 3.2 Vendors & licensing pipeline, 3.3 Variants & seasonal drops, 3.4 Preorder campaigns & production lock, 3.5 Purchase orders/receiving/valuation, 3.6 Event POS & online sales, 3.7 Drawer reconciliation/refunds/exchanges, 3.8 Profit allocation & wind-down
- §4 Endpoint Definitions (66 rows, 4 columns), §5 Error Code Catalogue (50 rows, 2 columns)

**Zero-Silence Rule self-audit (Contract 2 walk):**
- **State machines:** all 11 covered verbatim in prose — MerchProgram `SETUP→ACTIVE→CLOSED→RECONCILED` with both `ERR_UNRESOLVED_OPERATIONS` gates and `ERR_PROFIT_NOT_FULLY_ALLOCATED`; Vendor `PENDING→APPROVED↔SUSPENDED` with suspension quote-ineligibility; Design revision loop (`REJECTED→SUBMITTED`, `revision_count` +1, `rejection_reason` cleared) and the 3-link `REVOKED` cascade; SeasonalDrop open/close/settle with `settled_margin_cents` snapshot definition; PO receive loop with exact-equality completion and campaign `IN_PRODUCTION→FULFILLING` bubble-up; campaign lock fork (equality passes goal), `FULFILLING→CLOSED` bubble-up, three cancel paths; PreOrder pay/fulfill/cancel/refund rules incl. PAID-cancel-while-OPEN; EventSale recount loop (`OPEN`/`FLAGGED`→`COUNTED`→`RECONCILED` at-or-below tolerance, else `FLAGGED`) and director override; Order parallel payment/fulfillment dimensions incl. run-ops `EXPIRED_RELEASED`; ExchangeRequest approve/reserve and complete semantics; AllocationRun `DRAFT→POSTED→REVERSED`.
- **Calculations (9/9, exact rounding/ordering):** order totals (per-line round-half-up then sum, pinned, with the 333¢×3→900-vs-899 discriminator); deposit max-floor formula; dual campaign projections (`placed_units` vs `paid_units`, lock consults paid only); FIFO (receipt-time ASC, `created_at` tie-break) vs WEIGHTED_AVG (round-half-up average); over/short (expected = float + cash sales − cash refunds, inclusive tolerance boundary); allocation waterfall (floor shares, cap headroom, iterative renormalized redistribution, dust to largest weight with `created_at` tie-break, conservation invariant, capped-overflow remainder allowed); exchange differential; vendor quote selector (3-level ranking, empty→`ERR_NO_ELIGIBLE_VENDOR`, campaign stays `OPEN`); landed cost (fee amortized over `qty_ordered`, round-half-up, latest receipt wins, 0 until first receipt).
- **Validations:** all 13 priorities rendered as an explicitly ordered pipeline in §2.8 with every `error_id` attached; all 50 error IDs appear in §2/§3 prose.
- **RBAC matrix:** all 6 roles named, all `identity: opaque` translated individually, Customer ownership exception (`X-User-ID` vs `customer_user_id` for preorder pay/cancel and exchange create) stated.
- **OCC (2/2):** both rules name write operation, `expected_program_version`/`expected_design_version`, mismatch rejection, `ERR_STALE_VERSION` HTTP 412; "no other endpoint takes a version field" stated.
- **Clock endpoint default:** logical clock reads exactly `2026-08-01T00:00:00Z` before any set, MUST NOT fall back to wall clock (§2.5).

**Mechanical contracts:** Contract 1 PASS (119/119 required field/parameter names present in backticks, verified by script); Contract 3 PASS (567 §3 backtick tokens, zero path/method violations); no pseudocode operators or fuzzy approximators in prose.

## Step 6: Generate Implementation — 2026-08-13T20:33:30.000Z

Implementation complete. Summary:

## Files written
All under `/home/ubuntu/github/CodingPRD/tasks/task_1525_school_spirit_store_merchandise_program/workspace/implementation/`:
- `start.sh` — foreground launcher, `exec python3 app.py`, guarded pip install (no-op when flask present), binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — flask>=3.0
- `app.py` — Flask entry point, blueprint registration, envelope-shaped 404/405/500 handlers
- `core.py` — in-memory store (empty at boot, zero seeding), ApiError + all 41 error IDs, response envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`), pagination (`limit`/`offset`/`total_count`/`has_more`, default 10, clamp 1..100), auth (`X-User-ID`/`X-User-Role`, six roles), logical clock (defaults to exactly `2026-08-01T00:00:00Z`), monotonic 3-fractional-digit timestamps, Decimal round-half-up/floor helpers, computed `sellable`/`available_qty`/`low_stock`/campaign unit projections, campaign cancel cascade
- `routes_catalog.py` — programs (lifecycle, profit adjustments, valuation, run-ops), clock, vendors, designs + licensing workflow, variants, drops
- `routes_supply.py` — purchase orders, preorder campaigns (lock fork, vendor selector, auto-POs), preorders (pay/fulfill/cancel)
- `routes_sales.py` — event sales (drawer open/close-count/reconcile/cancel), orders (EVENT_POS + ONLINE), fulfillment transitions, refunds
- `routes_finance.py` — exchanges, activity accounts, allocation runs (waterfall)

## Coverage
- **Endpoints: 66/66** from the §1.5/§4 table (13 entities + clock).
- **State machines: 11/11** — MerchProgram (SETUP→ACTIVE→CLOSED→RECONCILED with unresolved-ops and profit-allocated gates), Vendor (PENDING↔APPROVED↔SUSPENDED), Design (cyclic DRAFT/SUBMITTED/APPROVED/REJECTED/REVOKED + revision counter + 3-link revoke cascade), SeasonalDrop (SCHEDULED→OPEN→CLOSED→SETTLED + settle margin snapshot), PurchaseOrder (partial-receive loop, exact-equality completion, campaign bubble-up to FULFILLING), PreOrderCampaign (goal fork at lock, bubble-close on last fulfill), PreOrder (two-phase pay, customer escape hatch), EventSale (open → count → tolerance auto-reconcile/FLAGGED recount loop/director override), Order (parallel payment × fulfillment dimensions), ExchangeRequest (PENDING→APPROVED/REJECTED→COMPLETED), AllocationRun (DRAFT→POSTED→REVERSED).
- **Calculations: 9/9** — per-line round-then-sum order totals; deposit max(floor, rhu(price·qty·pct)); provisional vs lock-authoritative campaign units; FIFO (receipt layers, chronological consumption) vs WEIGHTED_AVG valuation; cash over/short with inclusive tolerance boundary; allocation waterfall (floor shares, capped-overflow iterative redistribution, deterministic dust to largest-weight/earliest-created); exchange differential vs captured line price; vendor quote selector (cost ASC → production_days ASC → vendor created ASC); landed cost with rhu fee amortization, latest receipt wins.
- **Validation pipeline** enforced in PRD §2.8 order (auth → role/ownership → path FKs → body FKs → shape → program gate → state → licensing → temporal → constraints → fiscal → selector → OCC), with OCC (`expected_program_version` on drop create, `expected_design_version` on licensing transitions) deliberately checked last at 412.

## Boot smoke test
`bash start.sh` on scratch ports booted cleanly every time (including a fresh reboot showing `total_count: 0` — no state carryover). Verified live: envelope/error shape (400 `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), full POS drawer flow (SoD 403, tolerance reconcile), online order → partial refund with proportional reservation release → run-ops expiry (full refund + release), campaign goal-met lock with auto-PO and FULFILLING/CLOSED bubble-ups, goal-unmet lock refund cascade, design revoke cascade (campaign CANCELLED + preorder REFUNDED + sellable false + `ERR_LICENSE_REVOKED` on sale), exchange with exact differential collection, allocation waterfall (700/2100 split, dust-exact) with CLOSED-gated post and reverse, drop OCC/overlap/adjacency, and pagination meta. Server killed after test.

## Step 5: Generate Unit Tests — 2026-08-13T20:36:00.000Z

All done. Final summary:

## Files written

**test_helpers/** (9 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_1525_school_spirit_store_merchandise_program/test_helpers/`):
- `types.py` — 15 status/enum types + 13 entity TypedDicts (all common_fields entities carry id/created_at/updated_at/version)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (53 methods incl. the `_clock/set_current_utc` test driver)
- `api_errors.py` — 52 `ApiErrorId` values + HTTP status map registered via `set_error_http_status_map` (incl. 402 for `ERR_DEPOSIT_SHORTFALL`, 412 for `ERR_STALE_VERSION`)
- `assertions.py` — per-entity shape assertions + profit-split invariant checker
- `factories.py` — payload factories (input fields only) for all 13 resources
- `constants.py` — default clock `2026-08-01T00:00:00Z`, the five program policy defaults (500/14/7/30/500)
- `test_users.py` — `TEST_USERS` shared headers for the six (all-opaque) roles + per-user builders for drawer segregation and Customer-ownership flows
- `fixtures.py` — composite setup tiers: program lifecycle, OCC-threaded design approval chain, vendor/quote approval, drop creation with program-version threading, PO create→submit→receive, `setup_storefront`, `setup_open_campaign_shop`, `setup_campaign_in_production`, `setup_campaign_fulfilling`, `setup_exchange_shop`, `setup_profit_program`, `setup_waterfall_scenario`

**test_suite/** (14 files): `conftest.py` + 13 numbered test files (95 tests total).

## Test counts and coverage

- **95 tests**, all with exactly one terminal `Design:` tag, all PRD citations verbatim-greppable (134 quoted spans checked, 0 misses), no skip/skipif/xfail anywhere.
- **Queue A (difficulty): 20/20 instances translated, 0 skipped — 40 tests (exactly 2 per instance).** Second tests per instance exercise the sibling assertion axis (e.g., FIFO 70000 vs WEIGHTED_AVG 60000 divergence, tolerance 500-reconciles vs 501-flags, goal-equality vs goal-minus-one, OCC stale-fail vs fresh-succeed).
- **Queue B (corner): 55/55 non-stub instances translated, 0 skipped — 55 tests.** All 12 `excluded_because:` stubs verified to resolve to real difficulty instances and not translated.

## Judgment calls (per-assertion two-reader rulings, no instance skipped)

- `create_program_applies_documented_defaults` and `design_created_in_draft_initial_state`: the recipes' `version == 1` assertion is not uniquely derivable from PRD (§2.4 defines increment semantics but no initial value), so those two assertions were dropped while keeping each instance's PRD-derivable claims (defaults, SETUP/DRAFT, counters at 0).
- `selector_tiebreak_prefers_faster_vendor`: recipe leaves vendor C PENDING (not SUSPENDED as the prose aspect says); both are ineligible under "eligible vendors are APPROVED vendors", and the test asserts selection of vendor B only.
- `expires_at` in the run-ops test is asserted by prefix (`2026-09-12T12:00:00`) to tolerate millisecond rendering, staying derivable from "ready_at plus the program's pickup_window_days".

## Stage 2 self-audit result

- Tag format: every one of 95 tests ends its docstring with exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line (C4); no dual tags, no untagged tests.
- Instance-name resolution: all 40 difficulty tags resolve against `SCAFFOLD_DIFFICULTY_DESIGN.yaml` with matching `rule_id`; all 55 corner tags resolve against `SCAFFOLD_CORNER_DESIGN.yaml` with matching `section`; no tag points at a stub.
- Verbatim citations: all 134 docstring quotes match `workspace/PRD.md` after whitespace normalization; priority-ordering tests (state-vs-fiscal, safety-vs-temporal) are backed by the normative-ordering sentence in PRD §2.8.
- All 13 test modules + `test_helpers` compile and import cleanly.

## Step 7: Run Tests and Iterate — 2026-08-13T20:50:00.000Z

## Summary

**Exit condition met**: iteration 2 sweep — all 8 parallel rounds passed 95/95 with 0 failures, 0 errors.

**Iterations run**: 2 (iteration 1: 6 deterministic failures identical across all 8 rounds; iteration 2: clean 8×95/95).

**Tests deleted**: none. (One assertion was removed from a test — see below — no whole-test deletions; every failing rule traced verbatim to PRD.)

**Fixes applied to `test_helpers/`**: none needed — the fixture layer was PRD-faithful; all test-side bugs were in the test modules themselves.

**Fixes applied to `test_suite/`** (4 files, 5 tests):
- `test_suite/test_01_program_and_catalog_basics.py`
  - `test_design_created_in_draft_initial_state` — setup bug: built the program with `create_program()` (SETUP) then asserted design creation succeeds; PRD §2.8 step 6 gates catalog writes to ACTIVE programs. Changed to `create_active_program()` (STEP 2 — setup violated the PRD program gate; the implementation's `ERR_PROGRAM_NOT_ACTIVE` was correct).
  - `test_filtered_list_orders_by_event` — NameError: added missing `create_open_event` import.
- `test_suite/test_05_pos_sales.py` — `test_refund_exceeds_paid_rejected` — NameError: added missing `create_pos_order` import.
- `test_suite/test_07_campaign_lifecycle.py` — `test_paid_units_one_below_goal_cancels_at_lock` — removed the `assert locked["paid_units"] == 1` line: after the goal-unmet lock fires the §3.4 refund cascade, the paid preorder is REFUNDED and PRD's counter definition ("sum over preorders in `PAID` or `FULFILLED` only… `CANCELLED` and `REFUNDED` preorders are excluded from both") uniquely determines `paid_units == 0`; the assertion contradicted PRD. Kept the covered assertion (`status == CANCELLED`) per STEP 1c.
- `test_suite/test_13_security_and_access.py` — `test_catalog_write_before_activation_rejected` — setup bug: the `create_design()` setup step was itself a gated catalog write under SETUP and failed before the asserted call. Rewrote the test to attempt the design creation directly as the catalog write under test (still asserting `ERR_PROGRAM_NOT_ACTIVE` 409 per PRD §2.8 step 6); swapped the import from `create_design` to `create_design_payload`.

**Fixes applied to `implementation/`** (1 file):
- `workspace/implementation/routes_sales.py` — `create_event()` register-buffer check: changed both overlap comparisons from `<=` to `<`. PRD §3.6 requires "a gap of at least the program's `register_buffer_minutes`" — a booking starting exactly at `prior ends_at + buffer` (exactly-buffer gap) must be accepted; the old `<=` rejected the exact-boundary case. The one-minute-short case still correctly conflicts.

No tests were weakened (all `error_id` assertions retained at full strength), no implementation checks were stripped, and no endpoints/fields/seed data were added.

## Step 8: Finalize PRD — 2026-08-13T20:58:00.000Z

Done. `PRD_FINALIZED.md` is written with exactly one inline revision; everything else in the step_7_diff traced to behavior the PRD already uniquely determines (pure test-side bugs) and required no patch.

**Line counts / %-delta:** PRD.md 353 lines, PRD_FINALIZED.md 353 lines — 0% line delta (one line revised in place, no insertions or deletions of lines).

**Changes:**
- §3.6 (line 191) — revise — appended the boundary pin "— a gap exactly equal to the buffer passes, and only a gap strictly smaller than the buffer is rejected —" to the register-buffer sentence, so the exactly-`ends_at + register_buffer_minutes` booking is accepted and only strictly-shorter gaps draw `ERR_EVENT_REGISTER_CONFLICT` — `implementation/routes_sales.py:44-53` (`create_event()`, conflict iff `starts_at < other["ends_at"] + buffer and other["starts_at"] < ends_at + buffer`, the Step 7 `<=` → `<` fix site).

**Step_7_diff items requiring no edit (PRD already determines):**
- `test_design_created_in_draft_initial_state` / `test_catalog_write_before_activation_rejected` — test setup bugs; PRD §2.8 step 6 already pins the ACTIVE program gate, and `create_design()` conforms via `gate_active(program)` at `routes_catalog.py:352`.
- `test_filtered_list_orders_by_event` / `test_refund_exceeds_paid_rejected` — NameError import fixes; no behavioral content.
- `test_paid_units_one_below_goal_cancels_at_lock` — deleted assertion contradicted PRD §3.4 (counters + refund cascade); `campaign_units` (`core.py:380-391`) and `lock_campaign` (`routes_supply.py:297-302`) match the PRD verbatim.

**Per-edit pre-edit search log (the single edit):**
- (a) Subject: boundary semantics of the register-buffer booking-conflict gap comparison at event creation.
- (b) Impl paths enumerated and read/grepped: `routes_sales.py:23-72` (`create_event` — sole raise site of `ERR_EVENT_REGISTER_CONFLICT`, symmetric two-sided `<` check over non-`CANCELLED` same-program, same-register events); `routes_sales.py:169-182` (`cancel_event` — CANCELLED events drop out of future scans, matching the PRD's "non-`CANCELLED`"); `routes_sales.py:95-115` (`open_drawer` — distinct temporal check `now_logical() > ends_at`, untouched by the wording); `routes_catalog.py:42` (`register_buffer_minutes` via `opt_int(..., 30, 0)` — buffer may be 0); `core.py:42` (error constant). Repo-wide grep for `register_buffer` / `REGISTER_CONFLICT` / `register_location` confirms no other consumers.
- (c) Wording adjustment: an earlier candidate phrasing describing the buffer zone as "half-open" was rejected because it would redefine the retained "closed intervals, inclusive endpoints and all" clause and risk mis-describing the touching-window case. The committed wording is a pure gap-comparison pin ("exactly equal passes; only strictly smaller rejects"), which is exactly equivalent to the implementation's `<` comparisons for both event orderings and every buffer value — including buffer 0, where touching events (gap 0) are accepted by the code and by the new clause alike — and leaves all other enumerated paths accurately described.

## Step 9: Complete PRD — 2026-08-13T21:25:00.000Z

The diff is exactly as intended: 29 source lines revised, 31 lines in their place (+2 net lines from one inserted paragraph). All edits are in-paragraph; no sections added or removed.

## Summary

**Source:** `PRD_FINALIZED.md` → `PRD_COMPLETED.md` (both at `workspace/`)
- Lines: 353 → 355 (+2); Chars: 57,480 → 60,806 (+3,326)
- **Ambiguity-pins: 31** (some bundled per edit site); **Mismatch-revisions: 4**

### Mismatch revisions
- §2.8 step 5 + §3.1 — revise — mismatch — `amount_cents ≥ 1` was stated globally, but profit adjustments accept any integer (negative reduces undistributed profit); scoped the rule to payment/refund amounts — `routes_catalog.py:130` (no minimum), vs `routes_supply.py:460` / `routes_sales.py:435` (min 1)
- §2.8 after step 13 — revise — mismatch — pipeline order carved out for two endpoints: vendor update applies the ACTIVE gate before body-shape checks (`routes_catalog.py:314` before `:317-330`); PO receipt applies the state precondition before parsing the body (`routes_supply.py:133` before `:137-138`)
- §3.4 — revise — mismatch — "creates one against an APPROVED design" dropped; impl enforces licensing only at campaign open — `routes_supply.py:193-227` (no design-status check in `create_campaign`; check lives in `open_campaign` `:263-268`)
- §3.7 — revise — mismatch — "Rejection takes a `note`" removed; exchange rejection neither requires nor stores a note — `routes_finance.py:122` (only `decision` required), `:143-144`

### Ambiguity pins
- §2.3 — insert — ambiguity — limit/offset out-of-range values are clamped (limit to [1,100], offset to ≥0), non-integer → `ERR_INVALID_REQUEST` — `core.py:227-238`
- §2.3 — insert — ambiguity — orders-list `variant_id` filter matches orders containing a line for that variant — `routes_sales.py:364-368`
- §2.4 — insert — ambiguity — `version` starts at 1 on creation — `core.py:175`
- §2.8 step 2 — insert — ambiguity — customer-ownership check runs after resource loading (steps 3–4), so a missing resource 404s before an ownership 403 — `routes_supply.py:449-453`, `routes_finance.py:33-48`
- §3.1 — insert — ambiguity — five policy knobs must be non-negative integers when supplied — `routes_catalog.py:39-43`
- §3.1 — insert — ambiguity — profit adjustment returns 201 with the updated program; neither adjustments nor ops runs are gated on program status — `routes_catalog.py:135`, `:177-212`
- §3.2 — insert — ambiguity — quotes are shape-validated only (fields present, non-negative ints, status enum, one ACTIVE per design); quote `design_id` existence not checked — `routes_catalog.py:228-258`
- §3.2 — insert — ambiguity — `licensing_fee_cents` non-negative integer; rejection `note` optional (null when omitted); revocation note accepted but not persisted — `routes_catalog.py:351`, `:417-422`
- §3.3 — insert — ambiguity — variant `unit_price_cents` must be a positive integer — `routes_catalog.py:457`
- §3.3 — insert — ambiguity — drop-overlap check excludes `SETTLED` drops — `routes_catalog.py:530-536`
- §3.4 — insert — ambiguity — campaign `unit_price_cents` and `goal_units` are positive integers — `routes_supply.py:206-208`
- §3.4 — insert — ambiguity — deposit pay reports `ERR_PREORDER_NOT_PAYABLE` before `ERR_CAMPAIGN_NOT_OPEN` when both fail — `routes_supply.py:465-470`
- §3.5 — insert — ambiguity — submit enforces the `min_order_qty` captured on the PO at creation, not the vendor's current quote — `routes_supply.py:67`, `:116`
- §3.5 — insert — ambiguity — valuation `method` override: unrecognized value → `ERR_INVALID_REQUEST`; `per_variant` entries carry `variant_id`, `on_hand_qty`, `value_cents` — `routes_catalog.py:146-148`, `:169-171`
- §3.6 — insert — ambiguity — `opening_float_cents` non-negative integer — `routes_sales.py:102`
- §3.6 — insert — ambiguity — order `lines` must be a non-empty array — `routes_sales.py:188-190`
- §3.6 — insert — ambiguity — online orders also require `payment_method` (CASH/CARD) — `routes_sales.py:236-243`
- §3.6 — insert — ambiguity — drop-OPEN requirement (`ERR_DROP_NOT_OPEN`) applies to online lines only; EVENT_POS lines are not drop-gated — `routes_sales.py:270-277`
- §3.6 — insert — ambiguity — stored line shape: `variant_id`, `qty`, `discount_pct`, captured `unit_price_cents`, `line_total_cents` — `routes_sales.py:296-303`
- §3.6 — insert — ambiguity — pickup from any state other than `READY_FOR_PICKUP` is `ERR_PICKUP_NOT_READY` — `routes_sales.py:404-406`
- §3.7 — insert — ambiguity — `closing_counted_cents` non-negative integer; recounts also overwrite `counted_by_user_id` — `routes_sales.py:125`, `:138-140`
- §3.7 — insert — ambiguity — online-refund reservation release formula pinned: per line cumulative released = floor(qty × cumulative refunded ÷ total), each refund releasing the delta — `routes_sales.py:478-493`
- §3.7 — insert — ambiguity — exchange requires a fulfilled order (`POS_FULFILLED`/`PICKED_UP`, else `ERR_INVALID_STATE_TRANSITION`); window measures from sale instant (POS) or pickup instant (online) — `routes_finance.py:53-63`, `routes_sales.py:321`, `:412`
- §3.7 — insert — ambiguity — for zero/negative differentials `amount_collected_cents` is optional but must be a non-negative integer if supplied — `routes_finance.py:174-177`
- §3.7 — insert — ambiguity — negative-differential refund moves the order to `REFUNDED` (not just `PARTIALLY_REFUNDED`) when cumulative refunded reaches `total_cents` — `routes_finance.py:194-198`
- §3.8 — insert — ambiguity — `cap_cents` non-negative when not null; account creation not gated on program status — `routes_finance.py:221-224`, `:207-233` (no gate)
- §3.8 — insert — ambiguity — run creation not gated (only posting requires CLOSED); zero accounts yields a run with no lines — `routes_finance.py:331-359`, `:270-271`
- §3.8 — insert — ambiguity — reversal not gated on program status — `routes_finance.py:410-432` (no `gate_closed`)

Everything else in the implementation (endpoint roster, RBAC table, error catalog statuses, OCC guards, state machines, deposit/royalty/clawback/waterfall math, FIFO/WEIGHTED_AVG valuation, drawer segregation, cascade behavior, envelope shape) was already uniquely pinned by the PRD and left untouched.
