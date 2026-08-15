# Worklog — task_1563_plumbing_pvf_wholesale

## Step 1: Create Task Directory — 2026-08-13T21:16:00.000Z

Pre-assigned by pipeline launcher: `tasks/task_1563_plumbing_pvf_wholesale/` and its `workspace/` subdirectory already exist. Step 1 treated as DONE per orchestration instructions; no index scan performed, no other task directory touched.

## Step 2: Generate Scaffold — 2026-08-13T22:27:00.000Z

Everything is clean. The scaffold package is complete and verified.

**Lint verdict (verbatim):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
Coverage
  §1.5 endpoints declared:    78
  §1.1 entities declared:     14
  §1.8 instances scanned:     25
  §1.9 instances scanned:     65
  Calls scanned (§1.8+§1.9):  765

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5
and all §1.1 FKs have reverse-reachability in §1.5.
```

**Counts**
- Entities: 14 (Branch, Product, ContractorAccount, ManufacturerProgram, InventoryStock, StockReceipt, Payment, Quote, SelectionSheet, Order, OrderLine, Kit, DeliverySlot, ReturnRequest)
- State machines: 10 entries (Order carries two parallel dimensions — payment_status × fulfillment_status — as separate entries; Quote, SelectionSheet, ContractorAccount cyclic; Kit compound-posture; DeliverySlot threshold auto-cycle; OrderLine branching + parallel substitute axis; ReturnRequest fork)
- Calculations: 9 (counter_price_resolution, document_totals, restocking_fee, job_cost_report, credit_exposure, rebate_tier_attainment, backorder_allocation, payment_auto_allocation, delivery_cubes)
- Endpoints: 78 · Errors: 40 · Roles: 5 (BranchManager/CounterRep/InsideSales/WarehouseLead opaque; Contractor entity_backed:ContractorAccount)
- §1.8 difficulty instances: 25 (all non-stub; every rule has 2–3): dual-variant calcs on two domains (job costing vs credit exposure); combinatorial formulas in all three modes ((a) tier+promo+override-floor min, (b) per-line-then-sum restock rounding with a 1-cent discriminator, (c) pinned pre/post-discount evaluation order); 3 non-linear machine shapes; cascades depth-3 (receipt→stock→line→order→kit) and depth-3 with parallel balance hop (return-receive); 3 distinct validation priority pairs (state/fiscal, existence/state, temporal/capacity); 3 boundary equalities (cubes, rebate threshold, credit limit); 3 cross-entity gates; 3 interval semantics (half-open truck adjacency, bin 2h buffer-gap, closed-interval program touch); 3 compensating invariants (units, ledger cents, slot cubes)
- §1.9 corner instances: 65 non-stub + 7 excluded_because stubs, across all 9 taxonomy sections, including full 404-family coverage, all 40 errors triggerable, OCC 412 positive/negative pairs for all 3 concurrency rules, RBAC denials, segregation-of-duties, FIFO allocation tie-breaks, and envelope/pagination checks

**Notable design decisions**
- Flat topology under `/pvf` (no nesting); every FK has a reverse-reachability GET, verified by lint check (f).
- Found and fixed a design hole mid-build: with submit gating exposure ≤ limit, balance could never exceed the limit — so credit hold now also engages on past-due invoices (terms COD/NET_15/NET_30 + logical clock) and on manager ADJUST_LIMIT tightening; hysteresis release requires balance ≤ 80% AND no past-due invoices. ERR_LIMIT_BELOW_BALANCE was removed accordingly.
- ERR_EMPTY_RETURN (aggregate) is ordered before per-line overage so both errors are reachable; slot completion sweep fires only on clock advance, which keeps the past-window booking dual-failure deterministic.
- Logical clock endpoint with pinned startup default 2026-08-01T00:00:00Z; all time-gated setups (quote expiry, return window, program close, past-due hold) use it — no wall-clock waits.
- Placeholder closure and grounds resolvability verified by a separate script (zero unbound `${var}`, zero dangling grounds); no forbidden race vocabulary; all formula-derived asserts pre-computed to literals.

Files: `/home/ubuntu/github/CodingPRD/tasks/task_1563_plumbing_pvf_wholesale/SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`.

## Step 3: Copy Shared Files — 2026-08-13T22:29:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1563_plumbing_pvf_wholesale/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T22:53:00.000Z

(RESUME RUN note: Steps 1–3 artifacts verified complete on resume — all three scaffold YAMLs parse cleanly, no truncation; INSTRUCTION.md present. Pipeline resumed at Step 4.)

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1563_plumbing_pvf_wholesale/workspace/PRD.md` — 363 lines.

**Section structure**:
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications (11 subsections): 2.1 RBAC (headers, 5 roles, identity prose — Contractor entity-backed to `ContractorAccount`, four opaque roles), 2.2 API Response Structure (**verbatim** fixed block, byte-identical incl. `req_RANDOMALPHANUM123456` / `2025-05-24T10:30:00.123Z` / `"data": { }`), 2.3 Pagination & Collection Filtering (`limit` 10/1/100, `offset` 0, `created_at` ascending, all query-filter names), 2.4 Common Resource Properties, 2.5 Logical Clock & Scheduled Automation (startup default `2026-08-01T00:00:00Z`, expiry/completion/credit sweep), 2.6 Monetary Precision (integer cents, round-half-up, ceiling price floor, pinned per-line restock rounding), 2.7 Validation Pipeline & Nested Retrieval (ordered 8-stage pipeline, left-to-right path ids, explicit precedence: floor > override-role, hold > credit-limit, ownership > state), 2.8 OCC (3 rules), 2.9 Credit Policy (dual exposure variants, hysteresis), 2.10 Reservation & Backorder Waterfall, 2.11 Truck Cubes / Windows / Bin Buffers
- §3 Business Logic (10 subsections): catalog/receiving, manufacturer programs, accounts/payments/credit cycle, quotes/revisions/conversion, selection sheets, counter pricing & document totals, fulfillment/backorders/substitutions, kitting/staging/completion, delivery booking, returns
- §4 Endpoint table: 78 rows, 4 columns (Method, Path, Description, Authorized Role(s))
- §5 Error catalogue: 40 rows, 2 columns (Error ID, HTTP Status Code); document ends at §5 with no audit footer

**Coverage audit (Hard Contracts)**:

```
Field coverage check:
- entities[].fields + endpoint inputs/query/path params: 121 required, 121 present, 0 missing
  (includes array-member names finish/qty/unit_cost_cents/order_line_id/threshold_cents/rebate_pct,
   OCC fields, clock input/output to_iso8601/current_utc, computed-read outputs
   statement_balance_cents/provisional_cost_cents/final_cost_cents/order_count/line_count)
- error ids: 40 required, 40 present in backticks, 0 missing
- state/enum values: 59 required, 59 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] priority orderings: pipeline stated globally (§2.7) + 5 endpoint-specific chains
  (line-add floor>manager, submit hold>limit, booking state>hold>OCC>window>capacity,
   return window>non-returnable>empty>qty, ownership>state) — 0 missing
- concurrency_rules[] OCC rejections: 3/3 expressed (write capability + expected_quote_version /
  expected_order_version / expected_order_line_version + ERR_STALE_* + HTTP 412, no race framing)
- state_machines[].transitions: all 10 machines fully expressed (7 account incl. ADJUST_LIMIT
  ACTIVE-only + release-lands-ACTIVE; 2 program; 6 quote; 5 sheet; 2 payment; 9 fulfillment;
  9 order-line; 4 kit; 6 slot; 4 return) — 0 missing
- calculations[]: 9/9 in precise prose (tier pricing 0/5/10/15, floor ceil(cost×105%), promo min
  rule with price_source naming, pinned 6-step document totals with 500,000/2,000,000-cent volume
  tiers and 50,000/2,500-cent freight, restock 10%/25% at 30/90 whole days with per-line rounding,
  job-cost provisional vs final, statement vs forward exposure with 80% round-half-up release and
  COD/15/30 terms, rebate attainment with equality boundary, FIFO waterfalls with created_at
  ordering never-id, cube capacity with equality allowed)
- validations[] conditions: 28/28 matched to error ids in prose
- endpoints[].side_effects / applies_to: all cascades narrated (receipt→stock→program→waterfall→
  bubble-up; receive→restock→waterfall→balance→hold-release; completion→auto-invoice→balance→hold;
  cancel release chain; booking/cancel-booking slot recompute)
- field structured content: defaults/initials reconstructible (flags false, nullable FKs null,
  counters 0, single-state POSTED/APPLIED, nulls until award/approve/close)
- sibling-branch symmetry: quote 3 exits, credit-review 3 actions, cancel 3 from-states,
  substitute approve/reject, return approve/reject divergence, slot OPEN/FULL siblings — all equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 584
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, and no sibling task directories were inspected — generation drew solely from this task's `SCAFFOLD.yaml` plus the doc-generator skill and its fixed §2.2 source.

## Step 5: Generate Unit Tests — 2026-08-13T23:51:00.000Z

Generation complete. Summary:

## File inventory

**`test_helpers/`** (9 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_1563_plumbing_pvf_wholesale/test_helpers/`)
- `types.py` — 14 entity TypedDicts (all `common_fields: true`) + 16 status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (~70 methods) + singleton
- `api_errors.py` — all 40 `ApiErrorId` values with HTTP map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` + `assert_stock_invariants` (available == on_hand − reserved), `assert_credit_exposure`, `assert_job_costing`
- `factories.py` — payload factories for every creatable resource (input fields only)
- `constants.py` — tier pcts, volume/freight ladder, restock tiers, hold hysteresis, terms days, buffer hours, clock default
- `test_users.py` — `TEST_USERS` shared headers for the 4 opaque roles + `make_contractor_headers(account_id)` for the entity-backed Contractor (plus per-role id-parameterized builders)
- `fixtures.py` — tiered composite helpers: `setup_branch_product_account`, `create_draft/submitted/picked_up/delivered_order`, `create_awarded_quote`, `create_presented/approved_sheet`, `create_submitted/approved/credited_return`, `create_kitted_order`, `stage_kit`, `make_slot`, `book_order`, `receive_stock`, `set_clock`, `get_stock_row`, `get_order_line`
- `__init__.py` — barrel export

**`test_suite/`** — `conftest.py` + 14 test files numbered by concern (catalog, pricing, credit, quotes/sheets, computed reads, fulfillment, substitution, validation priority, kitting, delivery slots, programs, returns, security/RBAC, reads/envelopes).

## Test counts
- **112 test functions total**: 50 queue A (Difficulty) + 62 queue B (Corner)
- Queue A: **25/25 instances at exactly 2 tests each**
- Queue B: **62/65 non-stub instances at ≥1 test each**; all 7 `excluded_because:` stubs untranslated and their cross-references verified resolvable

## Instances skipped (3)
1. `Corner/entities/product_create_returns_201_with_defaults_and_system_fields` — asserts `version == 1` at creation; PRD §2.4 pins only "+1 on every mutation", never the origin — not uniquely derivable.
2. `Corner/cross_cutting_layers/version_increments_on_each_mutation` — entire claim is absolute versions (v1==1, v2==2, v3==3); same origin ambiguity.
3. `Corner/state_machines/slot_completed_by_clock_then_booking_rejected` — asserts booking a COMPLETED slot yields `ERR_INVALID_STATE`, but PRD §3.9's exhaustive five-guard booking list contains no slot-status guard; the clock-vs-`window_end` guard yields `ERR_DELIVERY_WINDOW_PAST`. Not PRD-derived.

## Deliberate relaxations (documented in-place)
- `quote_expires_via_clock_sweep` — post-sweep award uses `validate_error_is_one_of([ERR_QUOTE_EXPIRED, ERR_INVALID_STATE])` per the error-precedence silence pattern (PRD §2.7 pipeline orders state gating before quote freshness for an already-EXPIRED quote).
- `submit_response_reflects_reservation_immediately` and the double-submit untouched test accept `fulfillment_status ∈ {OPEN, PICKING}` — PRD §3.7's bubble-up fires "whether by the initial reservation", so a fully-stocked submit may already read PICKING in the same envelope (§2.4); the pinned assertions (totals, cubes, version, reservation) remain strict.

## Stage 2 self-audit result
- **Tag audit**: every one of the 112 tests has exactly one docstring-final `Design: Difficulty/...` or `Design: Corner/...` line; all tags resolve to real `name:` entries; no stub-targeted or malformed tags.
- **Citation audit**: 154 quoted docstring spans checked — all survive literal (whitespace-normalized) grep of `PRD.md`; every test carries a `PRD §` citation and all asserted `error_id`s are named in PRD prose.
- **No `pytest.mark.skip` / `skipif` / `xfail` anywhere**; no "scaffold" mentions in generated code.
- **Sanity**: `compileall` clean, pyflakes clean (modulo intentional barrel re-exports), all 112 tests collect under `pytest --collect-only` with `PYTHONPATH=<task dir>`.

## Step 6: Generate Implementation — 2026-08-13T23:51:00.000Z

The implementation is complete and verified. Final summary:

## Implementation Summary

### File inventory — `/home/ubuntu/github/CodingPRD/tasks/task_1563_plumbing_pvf_wholesale/workspace/implementation/`

| File | Purpose |
|---|---|
| `app.py` | Complete single-file Flask application (~2,400 lines): all 63 endpoints from the endpoint table, response envelope (`meta`/`response_type`/`data` with `api_request_id`, 3-fractional-digit `api_request_timestamp`), error envelope, auth middleware (`X-User-ID`/`X-User-Role` + Contractor ownership scope), RBAC per role matrix, all state machines (Account credit hysteresis, Program, Quote revision chain, SelectionSheet loop, Order parallel payment/fulfillment dimensions, OrderLine + substitute dimension, Kit compound posture, DeliverySlot OPEN/FULL auto-cycle, ReturnRequest fork), all calculations (tiered counter pricing with promo/override, pinned document-totals order, per-line restocking fees, job costing dual variants, dual credit exposure views, rebate tier attainment, backorder waterfall, payment FIFO auto-allocation, delivery cubes), all 28 validation rules in priority order with exact error IDs/HTTP statuses, 3 OCC rules (`expected_quote_version`/`expected_order_version`/`expected_order_line_version` → 412s), and the logical clock (`/pvf/_clock/set_current_utc`, default `2026-08-01T00:00:00Z`) driving quote expiry, slot completion, and the credit sweep |
| `requirements.txt` | `flask>=3.0` |
| `start.sh` | Executable foreground launcher: `set -euo pipefail`, `cd "$(dirname "$0")"`, guarded dependency install (`if ! python3 -c "import flask"` — no-op on per-test reboots), then `exec python3 app.py` |

### State storage
In-memory only: a module-level `store` dict of 12 entity collections (plain dicts keyed by UUID) plus a logical-clock datetime. No disk I/O, no database, **no seeding** — verified that a fresh process boots with an empty store (restart test returned `total_count: 0`).

### start.sh contract
Confirmed: runs in **foreground** via `exec`, reads `$PORT` (default 10000 via `os.environ.get("PORT", "10000")`), binds **0.0.0.0**, and the guarded pip install makes re-invocation instant. Booted via `bash start.sh` and answered HTTP within ~1 second.

### Verification
Three smoke suites (~100 assertions) all pass against live boots: auth/RBAC/ownership, catalog uniqueness, program overlap + accrual + tier attainment + close/settle, tier/promo/override pricing (floor-outranks-role precedence), reservation + backorder waterfall + OPEN→PICKING bubble-up, will-call pickup and dispatch/confirm-delivery invoicing, payment FIFO → PAID, quote submit/award/revise(OCC)/convert with QUOTE_LOCKED lines, sheet present/approve/revise/convert at SHOWROOM_LIST prices, slot overlap (half-open, touching allowed) + capacity-equality FULL flip + booking OCC + window-past rejection, kit assembly/stage bin 2-hour buffer/double-kitting/foreign-line rules, returns window/returnable/empty/qty pipeline ordering + segregation of duties + per-line fee rounding + restock cascade, credit-hold hysteresis (engage on statement balance/past-due, release at ≤80%), ADJUST_LIMIT tightening, and clock sweeps. Money arithmetic uses `Decimal` ROUND_HALF_UP; the price floor uses ceiling rounding.

## Step 7: Run Tests and Iterate — 2026-08-14T00:51:00.000Z

**Iterations run:** 2 (Sweep 1: 7 failures in all 8 rounds; Sweep 2: all 8 rounds pass 112/112).

**Tests deleted:** None.

**Fixes applied to `test_suite/`:**
- `test_03_credit_accounts.py` — added `201` as the expected status to 6 `validate_success(api.create_payment(...))` calls (lines 197, 218, 219, 248, 279, 295, 324). PRD §4 states: "Operations that create a new resource — including conversion actions that mint an order, and revision creation, which mints the superseding quote — return `201 Created`." A Payment is a newly-created resource (has its own `id`, `created_at`, `version`, `applied_at`), so the implementation correctly returns 201. The tests asserted the default 200, which was a test-vs-PRD inconsistency (STEP 2 fix).
- `test_06_fulfillment.py` — added `201` to the single `validate_success(api.create_payment(...))` call at line 318, same root cause.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `implementation/`:** None — the implementation was already PRD-faithful.

**Root cause (single shared bug):** Every failure was `AssertionError: Expected 200, got 201` from POST `/pvf/contractor-accounts/{id}/payments`. The 7 tests span 4 test classes (`TestHoldHysteresis` ×2, `TestPastDueHoldAndRelease`, `TestPayments` ×3, `TestParallelDimensions`) and all 8 rounds identically — not flaky, just a systematic misuse of `validate_success`'s default `expected_status=200` for a resource-creation endpoint.

**Verification:** Sweep 2 = 8 rounds × 112 tests = 896/896 passes. Zero failures, zero errors, zero flakes across all 8 parallel runs.

## Step 8: Finalize PRD — 2026-08-14T01:05:00.000Z

**Line counts / delta:** PRD.md = 362 lines, PRD_FINALIZED.md = 362 lines; 1 line modified in place, 0 added/removed (0% line-count delta; one sentence revised on line 236).

**Changes (one total — both step_7_diff items share a single root cause):**
- §4 (Endpoint Definitions, line 236) — revise — extended the non-exhaustive example list in the `201 Created` rule from "conversion actions that mint an order, and revision creation, which mints the superseding quote" to also name "posting a payment, which mints a new payment resource on the account" — `implementation/app.py:996` (`create_payment` → `return ok(dict(payment), 201)`).

No other edits were warranted: step_7_diff lists zero implementation fixes, zero test-helper fixes, and zero deletions; both test-suite fixes (`test_03_credit_accounts.py` ×7 call sites, `test_06_fulfillment.py` ×1) trace to this same PRD ambiguity — "posting a payment" reads as an action on the account, so a fresh reader defaulted to `validate_success`'s 200 even though Payment is a resource under §2.4.

**Per-edit pre-edit search log:**
- Edit 1 (§4, line 236):
  - (a) Subject: which successful POST operations return `201` vs `200`; pinning payment posting as resource creation.
  - (b) Impl paths enumerated: all 75 routes in `implementation/app.py` scanned with a paren-aware status extractor. Result: exactly 17 endpoints return 201 — `create_branch` (app.py:652), `create_product` (713), `create_account` (780), `create_payment` (996), `create_inventory` (1024), `create_stock_receipt` (1097), `create_quote` (1203), `revise_quote` (1309), `convert_quote` (1364), `create_sheet` (1426), `convert_sheet` (1540), `create_order` (1605), `add_order_line` (1678), `create_kit` (2021), `create_slot` (2141), `create_program` (2228), `create_return` (2322) — and every one mints a new resource. All remaining POSTs (every state transition, credit-review, delivery booking/cancel, clock set, substitute propose/decide, kit stage/unstage, program close/settle, return submit/decision/receive) return 200 and mint nothing. The PRD's general two-sentence rule already describes all 75 paths correctly; only the payment's classification was non-obvious to a fresh reader.
  - (c) Wording adjustment: the example list stays explicitly non-exhaustive ("including ..."), so adding payment posting as a third example cannot narrow or misdescribe any other enumerated path; no softening or re-scoping was needed. The general rule sentence and the `200 OK` sentence are otherwise verbatim.

## Step 9: Complete PRD — 2026-08-14T01:35:00.000Z

**Source vs output:** `workspace/PRD_FINALIZED.md` (362 lines / 64,504 chars) → `workspace/PRD_COMPLETED.md` (363 lines / 67,305 chars). Char delta: **+2,801** (one pure insertion; all other changes are in-paragraph revisions).

**Counts:** 23 ambiguity-pins, 3 mismatch-revisions (26 changes total, in 24 diff hunks).

**Changes** (PRD section — insert|revise — ambiguity|mismatch — what changed — impl evidence):

- §2.2 — insert — ambiguity — unrouted path / unsupported method answered with `ERR_INVALID_REQUEST` envelope at HTTP 404/405 — app.py:204-227
- §2.3 — revise — ambiguity — non-integer `limit`/`offset`, `limit` outside 1–100, negative `offset` rejected with `ERR_INVALID_REQUEST` — app.py:165-184
- §2.3 — revise — ambiguity — list sort ties on `created_at` broken by `id` ascending — app.py:187-188
- §2.4 — revise — ambiguity — `version` starts at 1 at creation — app.py:321-331
- §2.5 — revise — ambiguity — missing/unparsable `to_iso_iso8601` → `ERR_INVALID_REQUEST`; any valid instant accepted unconditionally — app.py:624-631
- §2.7 — revise — **mismatch** — pipeline reordered to auth → role → path-id resolution → ownership scope → body shape → body refs → state → business (impl fetches path ids before body validation in every handler; ownership after fetch, before body/state) — app.py:801-805, 1618-1622, 1842-1845, 1916-1924
- §3.1 — revise — ambiguity — `cubes_per_unit` is an integer ≥ 0 — app.py:685
- §3.1 — revise — ambiguity — product order-lines read returns stored rows without the computed `qty_backordered` overlay — app.py:743-751 (vs `line_view` at 1556-1564)
- §3.3 — revise — ambiguity — explicit payment allocations: each `amount_cents` ≥ 1; order must resolve (`ERR_ORDER_NOT_FOUND`) and belong to the account (`ERR_INVALID_REQUEST`) — app.py:937-950
- §3.3 — revise — ambiguity — job-costing echoes `job_name`; `order_count` = in-scope orders; `line_count` = non-CANCELLED lines in OPEN/ALLOCATED/BACKORDERED/FILLED — app.py:879-885
- §3.4 — revise — **mismatch** — quote creation accepts optional `supersedes_quote_id` (must resolve, `ERR_QUOTE_NOT_FOUND`; recorded as given, `revision_no` still 1) instead of always null — app.py:1181-1193
- §3.4 — revise — **mismatch** — revision payload must always carry fresh `valid_until` (only `lines` is optional/carried over); state gate and OCC check run before supplied lines resolve — app.py:1273-1284
- §3.4 — revise — ambiguity — converted PROJECT order carries `will_call` false — app.py:1328
- §3.5 — revise — ambiguity — FIXTURE/special-order violation at sheet creation rejected with `ERR_INVALID_REQUEST` — app.py:1392-1394
- §3.5 — revise — ambiguity — converted SHOWROOM order carries null `job_name`, `will_call` false — app.py:1503-1504
- §3.6 — revise — ambiguity — PROJECT orders never accept added lines (`ERR_INVALID_STATE`) — app.py:1640-1641
- §3.6 — revise — ambiguity — `price_override_cents` must be an integer ≥ 1 — app.py:362, 1625
- §3.6 — revise — ambiguity — totals ladder evaluated at order creation and re-run on every line/allocation mutation (add, submit, backorder fills, substitute approval, staging picks, booking, cancel) — app.py:564, 1604, 1721, 1757, 1786, 1861, 1966
- §3.7 — revise — ambiguity — submitting a line-less order rejected with `ERR_INVALID_STATE` — app.py:1703-1704
- §3.7 — revise — ambiguity — substitute proposal accepted from `NONE`, `REJECTED`, or a prior `APPROVED` substitute_status — app.py:1900-1908
- §3.7 — revise — ambiguity — substitute APPROVE first releases the original product's partial reservation — app.py:1938-1945
- §3.8 — revise — ambiguity — kit creation not gated on order fulfillment status or source — app.py:1984-1987
- §3.9 — revise — ambiguity — CANCELLED/COMPLETED slots excluded from the overlap check — app.py:2122-2123
- §3.9 — revise — ambiguity — slot cancellable only while OPEN or FULL with `booked_cubes` zero — app.py:2154-2157
- §3.10 — revise — ambiguity — order's fulfillment timestamp is its `invoiced_at`; a never-invoiced order skips the window check (empty-return check then rejects) — app.py:610-612, 2357-2360
- §3.10 — revise — ambiguity — return receive auto-creates the inventory record (on_hand 0) when none exists, mirroring receiving — app.py:2447-2453

Notable finding behind the main mismatch: the original PRD's validation pipeline (body shape → path ids) was inverted relative to every implemented handler (all fetch path ids immediately after role checks), so steps 3–5 were renumbered with ownership explicitly pinned between path resolution and state evaluation. Everything else in the PRD — pricing ladder, credit hysteresis, waterfall, capacity/staging rules, return fee schedule, error catalogue, RBAC table — matched the implementation as written.
