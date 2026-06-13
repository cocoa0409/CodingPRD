# Worklog — task_0303_supermarket_grocery_operations

Scenario: Supermarket / Grocery Store Operations: department & SKU/PLU, perishable shrink & date rotation (FEFO), weekly-ad price & promotion, reorder point & DSD receiving, scale/weighed items, loyalty & digital coupon, cycle count, end-of-day reconciliation

Difficulty target: Expert (passed only to Step 2 scaffold generator)

## Step 1: Create task directory — 2026-06-11T14:28:05.000Z

Created `tasks/task_0303_supermarket_grocery_operations/` and `tasks/task_0303_supermarket_grocery_operations/workspace/` at the pre-allocated path (no auto-increment). Verified `INSTRUCTION.md` and all four pipeline skills present at project root.

## Step 2: Generate scaffold (Expert difficulty) — 2026-06-11T14:54:37.000Z

All three required files are in place and the scaffold passes a clean lint. Generation complete.

### Summary

Generated a complete Expert-band scaffold for **Supermarket / Grocery Store Operations** at `tasks/task_0303_supermarket_grocery_operations/`.

**Complexity profile**: Primary archetype *Ledger reconciliation* + secondary *Pricing engine*; flat topology; parallel state-machine shape; peer_roles RBAC; immediate consistency. Layers: dual-variant calculation, cascading side effects, rate/threshold triggers, optimistic concurrency, derived-field reconciliation.

**SCAFFOLD.yaml** (§1.0–§1.7):
- **14 entities**: Department, Product (SKU/PLU, weighed flag, denormalized on-hand), InventoryLot (FEFO/expiration), Shipment, ShipmentLine (DSD receiving), PricePlan (weekly-ad), Promotion (BOGO/percent/fixed), LoyaltyMember, DigitalCoupon, ClippedCoupon, SalesTransaction (parallel tender×fulfillment axes), SaleLineItem, CycleCount, EndOfDayReconciliation.
- **10 state machines**: includes parallel (SalesTransaction tender×fulfillment), cyclic (InventoryLot ACTIVE↔QUARANTINED, LoyaltyMember ACTIVE↔SUSPENDED), branching fork-join (Shipment, CycleCount), and ClippedCoupon CLIPPED→{REDEEMED↔refund, EXPIRED}.
- **12 calculations**: FEFO depletion cogs, book-value rollup, effective ad price, promo line price (nested rounding pinned per-line-then-sum), transaction total (subtotal-keyed coupon gate), reorder flag, loyalty points accrual + tier, cycle-count variance/shrink, EOD rollup + shrink-alert.
- **13 validations** (priority-ordered, auth→existence→request→referential→state→temporal→safety→business→fiscal→OCC), **63 endpoints** (flat top-level collections, all FK reverse-reachability satisfied via sub-resource and filtered-list GETs; one `/_clock/advance` test-driving endpoint), **48 error codes**, **6 RBAC roles** (StoreManager, ReceivingClerk, PriceManager, Cashier, InventoryAuditor all `opaque`; LoyaltyMember `entity_backed`), **2 concurrency rules** (OCC on Product.version for receive and price-plan create).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml**: 9 rule_ids × 2 = **18 instances**, each with executable empty-DB setup chains and code-computed literal asserts; all differentiation clauses honored.

**SCAFFOLD_CORNER_DESIGN.yaml**: **40 active instances + 2 excluded_because stubs (42 total)** across the 9 claim-extraction-guide sections.

**Verification**: `scaffold_lint.py` → clean lint (470 calls scanned). All grounds resolve, no duplicate instance names, excluded_because references exist, enum closure holds, error catalog has no orphans/typos, all formula-derived asserts pre-computed against pinned formulas.

File sizes: SCAFFOLD.yaml 1229 lines, SCAFFOLD_DIFFICULTY_DESIGN.yaml 1312 lines, SCAFFOLD_CORNER_DESIGN.yaml 1786 lines.

## Step 3: Copy INSTRUCTION.md — 2026-06-11T14:54:58.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-11T15:01:02.000Z

Generated `workspace/PRD.md` from the scaffold (supermarket-grocery-operations, Expert tier — Ledger reconciliation + Pricing engine).

**Structure:** 315 lines, 5 top-level sections, 21 subsections.
- §1 Introduction
- §2 Global Specifications (10 subsections: RBAC, fixed §2.2 envelope, pagination, identity/versioning, money/precision, denormalized reconciliation, OCC, logical clock, nested retrieval, validation order)
- §3 Business Logic (11 subsections by domain: catalog, DSD receiving, lot lifecycle, inventory rollup/reorder, pricing/promotions, loyalty/coupons, POS pricing, FEFO/COGS, accrual/tender/refund, cycle counts/EOD close, test clock)
- §4 Endpoint table (63 endpoints)
- §5 Error catalogue (48 errors)

**Hard Contract reports:**
- Contract 1 — Field-Name Coverage: 76 required, 76 present, 0 missing → PASS
- Contract 2 — Rule Coverage: 13 validations (ordered chain 1..13 in §2.10), 2 OCC rules, all 11 state machines, all 12 calculations, all side-effect cascades, sibling-branch symmetry → PASS
- Contract 3 — §3 Path Purity: 449 backtick tokens scanned, 0 path/method tokens in §3 → PASS

Every entity (15), state machine (11), calculation (12), validation (13), endpoint (63), and error (48) covered in prose. §2.2 emitted verbatim; OCC, half-open windows, integer-cents/milli-unit precision, round-half-up, per-line-then-sum, inclusive boundary semantics all stated precisely. The two withheld design files were not opened; no sibling task consulted.

## Step 5: Generate unit tests — 2026-06-11T15:21:10.000Z

Generated complete test infrastructure for `task_0303_supermarket_grocery_operations` purely from the four input files plus the unit-test-generator skill.

**test_helpers/ (Stage 1) — 9 files:**
- `__init__.py` (barrel export), `types.py` (14 entity TypedDicts + 11 status enums + role enum), `api_client.py` (one method per PRD §4 endpoint), `api_errors.py` (full 48-error catalog + HTTP-status map), `assertions.py` (per-entity assertions), `factories.py` (per-entity input-only payload factories), `constants.py` (loyalty/variance/tier thresholds), `test_users.py` (5 opaque-role headers + entity-backed `make_member_headers` builder for the only `entity_backed:LoyaltyMember` role), `fixtures.py` (composite helpers: clock, catalog, canonical single-line DSD receive workflow with OCC-version/variance-override handling, FEFO sales, pricing, members/clips, `make_gold_member` tier-4 accumulator, cycle-count and EOD helpers).

Stage 1 verified to import cleanly against the project-local framework; framework signatures confirmed before writing Stage 2.

**test_suite/ (Stage 2) — 8 test files + conftest.py, 74 tests total:**
- test_01 catalog/CRUD (10), test_02 rbac/auth (4), test_03 receiving/lots (13), test_04 pricing/promotions (7), test_05 sales pricing calc (10), test_06 sale state/loyalty (9), test_07 inventory cascades (11), test_08 validation priority (10).

**Queue split:**
- Queue A (Difficulty): 34 tests — all 17 difficulty instances covered with exactly 2 tests each.
- Queue B (Corner): 40 tests — all 40 non-stub corner instances covered with ≥1 test each.

**Skipped instances:** None under the PRD-first filter — every difficulty and non-stub corner instance had verbatim PRD coverage and unique derivability. The two corner `excluded_because:` stubs were correctly NOT translated; both cross-references resolve to real difficulty instances that own the assertion. The priority-conflict difficulty tests are legitimate because PRD §2.10 states an explicit numbered priority order plus "A check earlier in this order always masks one later," uniquely determining the masking error.

**Validation performed:** all 111 PRD docstring citations verified verbatim against PRD.md; every test carries exactly one `Design:` tag; no scaffold/table terminology leaked into code; `pytest --collect-only` collects all 74 tests with no import or syntax errors.

## Step 6: Generate implementation — 2026-06-11T15:21:10.000Z

**Stack:** Python + Flask 3.0.3. All storage in-memory (`db.py` dict-of-dicts keyed by UUID); no SQLite, no file dumps, no `/tmp`, no seeding. Verified empty store on boot — every `db.*[id]=rec` write is inside a request handler.

**Files (≈2,443 lines total):**
- `app.py` (69) — Flask entry, blueprint registration, `before_request` auth gate, ApiError/404/405/500 handlers, `0.0.0.0:$PORT` (default 10000), `threaded=True`
- `start.sh` — `set -euo pipefail`, guarded `pip install` (only if flask import fails), `exec python3 app.py` foreground
- `db.py` (44), `clock.py` (18) — store + logical clock; `errors.py` (73) — full error catalog; `response.py` (58) — `meta`/`response_type`/`data` envelope, `req_` ids, ISO-8601 ms timestamps; `common.py` (165) — common-field stamping, ROUND_HALF_UP via Decimal, typed body parsers, window/pagination helpers; `auth.py` (35) — `X-User-ID`/`X-User-Role` extraction + RBAC; `inventory.py` (90) — rollup/reorder/FEFO; `serializers.py` (78), `lookup.py` (82) — per-entity not-found lookups
- `routes/`: catalog (185), receiving (251), lots (108), pricing (236), loyalty (150), sales (473), audit (305), clock_admin (23)

**Endpoints:** all 64 from the PRD table. **State machines:** all 11 (Shipment, InventoryLot, PricePlan/Promotion, SalesTransaction parallel tender×fulfillment, LoyaltyMember w/ clip-expiry cascade, CycleCount, EOD, Product, ClippedCoupon). **Calculations:** all 12 (effective_unit_price, line_extended_price w/ stacking, transaction_total, FEFO depletion, product_inventory_rollup, reorder_flag, loyalty points+tier, cycle_count_variance/shrink, eod_rollup+shrink_alert) — money in integer cents, weights in milli-units, all via Decimal ROUND_HALF_UP. **Validations:** enforced in PRD §2.10 priority order; OCC on `expected_product_version` (412) checked last; entity-backed LoyaltyMember ownership enforced.

**start.sh contract:** reads `$PORT`, binds `0.0.0.0`, runs foreground via `exec`, guarded install. Verified booting fresh via `bash start.sh`.

**Verification:** Two end-to-end smoke suites pass (47 assertions). All modules byte-compile clean; no leftover processes.

## Step 7: Run tests and iterate to PASS — 2026-06-11T15:29:42.000Z

All 8 parallel rounds pass with 74/74. The stability sweep is clean across every round, confirming no flakiness.

**Iterations run:** 3 (baseline sweep + 2 fix sweeps). Final result: all 8 parallel rounds pass 74/74.

**Tests deleted:** None. Every test traced to verbatim PRD prose and was uniquely derivable.

**Fixes applied to test_helpers/:**
- `test_helpers/fixtures.py` — `_next_dept_code()`: replaced the numeric counter format `f"DEPT{n:05d}"` (which produced codes like `DEPT00001` containing digits) with a base-26 letter encoding producing `DEPT_AAAAA`. PRD §3.1 states a department `code` is "letters A through Z and underscores only," so the implementation's `^[A-Z_]+$` validation correctly rejected the digit-bearing codes. Test-fixture precondition inconsistent with PRD (TEST BUG per STEP 2); was the shared setup failure behind 65 of the 74 tests. Added a `_int_to_letters()` helper.

**Fixes applied to implementation/:**
- `workspace/implementation/routes/audit.py` — `close_eod()`: the EOD rollup window mixed time bases. `window_start` was the wall-clock `created_at`, but `window_end` was `clock.now()` (the logical pricing/expiry clock, frozen at the test's advanced instant in the past). This produced an empty/inverted window that dropped every in-window sale/reconcile/pull/expire, so `shrink_total_cents` rolled up as 0 instead of 2000. Changed `window_end` to wall-clock `now_iso()`, matching the wall-clock `created_at`/`updated_at` basis used for window membership (consistent with PRD §2.4's "the moment of that mutation" and §2.3's created_at-ascending ordering; §2.8 scopes the logical clock to pricing/coupon/expiry only, not the EOD rollup). Added the `now_iso` import from `db`.

## Step 8: Finalize PRD — align documentation to implementation — 2026-06-12T02:05:55.000Z

_Resume note (orchestrator): the original interrupted run left `workspace/PRD_FINALIZED.md` as a byte-identical bare copy of `PRD.md` (md5 `06ccb944…`), i.e. only Method step 0 (`cp`) had run and no edits were applied — Step 8 was unfinished. Per the skip condition Step 8 is NOT skippable here (Step 7 had 1 `test_helpers/` fix + 1 `implementation/` fix). Re-ran Step 8 properly with the verbatim Step 7 entry inlined as `<step_7_diff>`. PRD_FINALIZED.md now md5 `c4cd8ccc…`; the single §3.10 edit was cross-checked against `routes/audit.py` (`window_end=now_iso()` :248, sales→`created_at` :262, cycle-counts→`updated_at` :282, lots→`updated_at` :290) and confirmed faithful. Verbatim subagent summary follows._

The patch is applied. The single edit is on line 188, pinning the EOD window basis.

## Summary

**Line counts:** PRD.md = 315 lines, PRD_FINALIZED.md = 315 lines (0% line-count delta; the single change rewords one sentence in place within line 188, adding no new lines).

**Changes (one bullet per change):**
- §3.10 (EOD reconciliation) — revise — Pinned the EOD close rollup window's upper bound and membership basis: "the current clock" was ambiguous (readers would default to the logical clock of §2.8), but the impl uses wall-clock "now" at close and tests each event's membership against its own wall-clock `created_at`/`updated_at`. Also pinned that cycle-count and lot membership are keyed to `updated_at` (the reconcile/pull/expire moment). — `implementation/routes/audit.py:247-248` (`window_start = created_at`, `window_end = now_iso()`), `:262` (sales `created_at`), `:282` (cycle-count `updated_at`), `:290` (lot `updated_at`).

**Step 7 items considered:**
- **Item 1 — `test_helpers/fixtures.py` `_next_dept_code()`:** No PRD edit. This was a pure TEST FIXTURE bug. PRD §3.1 (line 112) already verbatim determines the behavior ("letters A through Z and underscores only"), and the impl correctly enforces `^[A-Z_]+$` (`catalog.py:22,34`). The fixture was producing digit-bearing codes that violated the already-pinned PRD rule; fixing the fixture aligned it to existing prose. No silence, no mismatch.
- **Item 2 — `audit.py` `close_eod()` window:** PRD edit made (above). The Step 7 fix changed `window_end` from `clock.now()` (logical) to wall-clock `now_iso()`, revealing a genuine PRD/impl divergence at the under-determined phrase "the current clock."

**Per-edit pre-edit search log (EOD window edit):**
- (a) **Subject:** the EOD `close_eod` rollup window — its end-bound and the timestamp basis (wall-clock vs logical clock) for testing sales/cycle-count/lot membership.
- (b) **Impl paths enumerated and read/grepped:** `routes/audit.py` `close_eod` (`window_start`/`window_end` at :247-248; `in_window` half-open test :252-254; sales `created_at` :262; cycle-count `updated_at` :282; lot `updated_at` :290); `common.py` `stamp_new`/`touch` (:18-33, confirms `created_at`/`updated_at` use wall-clock `now_iso()`); `db.py` `now_iso` vs `clock.now` (:21-23, confirms wall-clock is distinct from logical clock); `clock.py` + `routes/clock_admin.py` (confirms the logical clock is advanced only via `/_clock/advance` and is NOT consulted in `close_eod`); also grepped `clock.now`/`now_iso`/`created_at`/`updated_at` across `audit.py` confirming `_reconciled_clock`/`_open_clock` (logical) are stored as internal `_`-fields but never used for window membership.
- (c) **Wording adjustment for consistency:** Kept the sales→`created_at` description verbatim (PRD already stated it, impl matches). For cycle-counts and lots, the impl keys membership to `updated_at` (not `created_at`), so I explicitly wrote "membership keyed to ... `updated_at`" for those two event types rather than a blanket "created_at" claim, which would have mis-described `audit.py:282` and `:290`. Tied the wall-clock basis to §2.4 and explicitly contrasted it with §2.8's logical clock to avoid the reader defaulting to the logical clock. No other §3.10 fields (opening/closing value, shrink_bps, shrink_alert) were touched, as the impl matches existing prose.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-06-12T02:14:56.000Z

_Orchestrator note: Step 9 started from `workspace/PRD_FINALIZED.md` (present, md5 `c4cd8ccc…`) and produced `workspace/PRD_COMPLETED.md` (md5 `7aa7afdf…`). The output preserves the Step 8 §3.10 EOD-window edit and layers 5 additional completeness pins. Spot-checked three claims against impl and confirmed faithful: §3.11 `current_utc` response field (`routes/clock_admin.py:23`), §3.2 variance gate floor via integer `//` (`routes/receiving.py:196`), §3.10 cycle-count DRAFT defaults `counted_qty:0`/`book_qty_snapshot:None`/`variance_qty:None`/`shrink_value_cents:0` (`routes/audit.py:60-63`). Verbatim subagent summary follows._

**Source vs output:**
- `PRD_FINALIZED.md`: 315 lines, 54,566 chars
- `PRD_COMPLETED.md`: 315 lines, 55,198 chars (char delta +632; line count unchanged — all edits are in-paragraph inserts/revisions, no new sections or paragraphs)

**Counts:** 4 ambiguity-pins, 1 mismatch-revision (5 total changes)

**Per-change bullets:**

- **§3.11 The Test-Driving Clock** — insert — ambiguity — PRD said only "the response reports the new current UTC instant"; pinned that the value is returned in a `current_utc` field as an ISO 8601 UTC string with three fractional digits — `implementation/routes/clock_admin.py:22-23`

- **§3.10 Cycle Counts** — insert — ambiguity — PRD was silent on a cycle count's field values at `DRAFT`; pinned `counted_qty` 0, `book_qty_snapshot` and `variance_qty` null, and `shrink_value_cents` 0 until submit/reconcile — `implementation/routes/audit.py:57-65`

- **§3.10 End-of-Day Reconciliation** — insert — ambiguity — PRD only pinned `opening_value_cents` at open and described the rest as computed "at close"; pinned that `sales_total_cents`, `cogs_total_cents`, `shrink_total_cents`, `closing_value_cents`, `shrink_bps` are 0 and `shrink_alert` false at open until close — `implementation/routes/audit.py:188-201`

- **§3.10 Cycle Count reconcile (short)** — revise — ambiguity — PRD said "the absolute shortfall is depleted from the product's lots in FEFO order" without naming lot eligibility or the insufficient-stock behavior; pinned that depletion draws only from FEFO-eligible (`ACTIVE`, non-expired) lots and takes the smaller of the shortfall and available eligible quantity when stock falls short — `implementation/routes/audit.py:122-127`, `implementation/inventory.py:42-90`

- **§3.2 Receiving variance gate** — revise — mismatch/ambiguity — PRD said the scaled relative variance is "scaled by 10000 and divided by the expected total" without pinning the rounding of that quotient; revised to state the quotient is floored to a whole number of basis points (matching the integer `//` the impl uses), so a fractional-bps value at the boundary does not exceed the 500-bps tolerance — `implementation/routes/receiving.py:196-197`

**Notes on items deliberately left unchanged** (PRD already pins them uniquely, or impl matches PRD and there is no observable gap): price-plan/promotion time-derived `status`, coupon having no `status` field, sale computed totals "zero until finalize", line-item computed fields filled at finalize, pay validation order (UNPAID then FINALIZED → `ERR_SALE_NOT_FINALIZED`), receive line `accepted_qty == 0` (no lot, status `SHORT`), shipment `received_total_cents`/`variance_cents` computed-on-read, FEFO eligibility and tie-breaks, loyalty multipliers/flooring, and the EOD wall-clock window (already fully pinned by the prior finalize pass).
