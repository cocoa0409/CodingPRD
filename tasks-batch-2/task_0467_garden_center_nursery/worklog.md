# Worklog — task_0467_garden_center_nursery

## Step 1: Create Task Directory — 2026-06-22T03:25:13.000Z

Task directory `tasks/task_0467_garden_center_nursery/` and its `workspace/` subdirectory were pre-allocated and confirmed to exist (empty). No index scan performed (per orchestration instruction, the path is fixed to avoid ID contention with 4 other parallel tasks).

## Step 2: Generate Scaffold — 2026-06-22T03:50:15.000Z

All three files are written, parse cleanly, and pass `scaffold_lint.py`. The scaffold was generated purely from the scenario description and the skill specification — no sibling task directories were read.

### Summary

Generated an **Expert-tier** scaffold for **Garden Center & Plant Nursery Retail** (`task_0467_garden_center_nursery`). Archetype: quota/allocation + ledger reconciliation; topology hybrid; **parallel** state-machine shape; peer-roles; immediate consistency.

**Entities (13):** Nursery, Account (RETAIL/LANDSCAPER_B2B, credit + loyalty), Product (LIVE_PLANT/BULK_MATERIAL/DRY_GOOD, hardiness range, warranty config), InventoryLot (live-goods, qty/reserved/shrink/sold ledger), CareLogEntry (append-only care/shrink log), SeasonalPromotion, Vehicle, Order, OrderLine, SpecialOrder, Delivery, WarrantyClaim, LoyaltyEvent (append-only, polymorphic source).

**State machines (6):** InventoryLot (cyclic QUARANTINE↔AVAILABLE→DEPLETED), Order **fulfillment_status** × Order **payment_status** (two parallel dimensions on one row), SpecialOrder (branching REQUESTED→APPROVED→RECEIVED / CANCELLED), Delivery, WarrantyClaim. Plus 2 OCC concurrency rules (order confirm/allocate stale-version, 412).

**Key calculations (7):** `line_pricing` (round-per-line-then-sum, pinned), `order_totals` (redemption capped at post-discount subtotal), `loyalty_accrual` (STANDARD vs GOLD ×2 dual-variant), `shrink_valuation` (PROVISIONAL vs FINAL dual-variant), `special_order_deposit` (ceil 30%), `warranty_payout` (single final floor over a fractional per-unit net), `lot_allocation_selector` (created_at ASC, FEFO tie-break, no id).

**Validations / errors:** 17 ordered validation rules (auth → existence → referential → constraint → state → cross-entity state → safety → temporal → fiscal → OCC); **44 error codes**, all triggerable.

**Endpoints:** 57 (lean mutating surface; flat reverse-reachability GETs inflate the read count to satisfy FK reverse-reachability with `api_prefix: ""`).

**Design files:** §1.8 has all 9 difficulty rules × 2 instances = **18 instances** (incl. nested-rounding 553-vs-554, payout 1699-vs-1698, GOLD/STANDARD loyalty divergence, depth-3 fulfill→deplete→final-shrink cascade, buffered-vs-plain temporal overlap on Vehicle/Promotion, lot-unit and loyalty-point conservation invariants). §1.9 has **39 corner instances** (37 active + 2 stubs) across all 9 guide sections.

**Verification:** `scaffold_lint.py` → `VERDICT: clean lint`. All `grounds`, transition refs, and stub `difficulty_instance` refs resolve; 57 unique instance names; no forbidden concurrency vocabulary; no unresolved formula asserts; enum closure fixed (CREDIT_HOLD now produced/consumed, CLOSED removed). All three files written to the task directory.

## Step 3: Copy Shared Files — 2026-06-22T03:50:15.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-22T03:57:22.000Z

**PRD generated:** `workspace/PRD.md` (320 lines, 51694 bytes)

**Section list:** 1. Introduction; 2. Global Specifications (2.1 RBAC / 2.2 API Response Structure / 2.3 Pagination / 2.4 Logical Clock default 2026-01-01T00:00:00Z / 2.5 Common Resource Properties w/ care-log+loyalty-event carve-out / 2.6 Hierarchical Consistency / 2.7 OCC / 2.8 Nested Retrieval + Referential Integrity / 2.9 Monetary Precision+Rounding / 2.10 Validation Ordering); 3. Business Logic (10 subsections); 4. Endpoint Definitions (58 endpoints); 5. Error Code Catalogue (44 errors).

**Hard Contract reports:** Contract 1 (Field-Name Coverage) PASS — 77/77 entity fields, 12/12 endpoint body/param ids. Contract 2 (Rule Coverage) PASS — all 6 state machines, 7 calculations, OCC both rules, validation ordering rendered. Contract 3 (§3 Path Purity) PASS — 0 path/method tokens in §3 prose.

**Confirmation:** Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was read, opened, grepped, or referenced. Only `SCAFFOLD.yaml`, skill spec, and reference templates were read. PRD ends at §5 table with no audit footer.

## Step 5: Generate Unit Tests — 2026-06-22T04:11:57.000Z

**Test infrastructure generated.**

**Files written:** `test_helpers/` (9 files): `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`. `test_suite/` (11 files): `conftest.py` + 10 domain-language test files (`test_01_provisioning` … `test_10_validation_precedence_and_rbac`).

**Test counts:** 73 test functions, every one tagged with exactly one `Design:` line (73 tags — no untagged, no dual-tagged).

**Instances translated:** Queue A (Difficulty) 18/18 instances, 2 tests each (36 tests). Queue B (Corner) 37/37 non-stub instances, ≥1 test each (37 tests).

**Instances skipped:** None skipped for PRD-filter failure. The 2 `excluded_because` corner stubs (`error_promotion_window_conflict`, `error_vehicle_window_conflict`) correctly NOT translated — their assertions are owned by difficulty instances `resource_temporal_overlap/promotion_plain_window_overlap` and `resource_temporal_overlap/vehicle_buffered_window_overlap`.

**Quality gates:** All 82 PRD citations verified verbatim. No scaffold leakage; no skip/skipif/xfail. Two PRD-derivability adjustments: dropped `version == 1` absolute-start asserts (PRD §2.5 says "starts at its initial value" without pinning 1 — only relative +1 increment is derivable); reframed the second `order_fulfill_requires_delivery_delivered` test to the PRD-verbatim "reaching DELIVERED unblocks the parent order's fulfillment." All 20 files compile under Python 3.9 (runner framework supplied at exec time, only syntax exercised).

## Step 6: Generate Implementation — 2026-06-22T04:11:57.000Z

**Stack:** Python + Flask, in-memory only (dicts keyed by id). Store starts empty on every boot — no seeding, no persistence.

**File list (`workspace/implementation/`):** `start.sh` (guarded foreground launcher, binds `$PORT` default 10000 on `0.0.0.0`, `exec python3 app.py`), `requirements.txt` (flask==3.0.3), `app.py`, foundation: `db.py`, `errors.py`, `clock.py` (default 2026-01-01T00:00:00Z), `response.py`, `middleware.py`, `validation.py`, `lookups.py`; `routes/` (11 modules); `services/` (calc, inventory, loyalty).

**Endpoint count:** 57 routes.

**State machines:** InventoryLot (QUARANTINE↔AVAILABLE→DEPLETED, auto-deplete); Order fulfillment (DRAFT→CONFIRMED→ALLOCATED→FULFILLED +CANCELLED w/ compensating reversals) × parallel payment (UNPAID→ON_ACCOUNT/PAID w/ credit-hold bubble-up/lift); SpecialOrder (REQUESTED→APPROVED→RECEIVED branch CANCELLED, mints QUARANTINE lot on receive); Delivery (SCHEDULED→DISPATCHED→DELIVERED +CANCELLED); WarrantyClaim (FILED→APPROVED/DENIED).

**Calculations (integer cents, pinned rounding):** line_pricing (per-line floor, single best ACTIVE in-scope promo, half-open window); order_totals (redemption capped at post-discount subtotal × 5¢/pt, net floored at 0); loyalty_accrual (floor dollars before ×rate, GOLD ×2); special_order_deposit (ceil 30%); warranty_payout (exact rational, single final floor) + loyalty clawback; shrink_valuation (provisional vs final); lot_allocation_selector (FEFO: created_at asc, tie-break smaller received_qty, id tie-break forbidden).

**Cross-cutting:** OCC `expected_order_version` on all 6 order transitions (412 ERR_STALE_VERSION); validation precedence auth→RBAC→path-existence→body-FK→shape→uniqueness→state→business→fiscal→OCC; cascading version/updated_at bumps; vehicle buffered-adjacency conflict; promotion plain half-open overlap; hardiness advisory gate w/ acknowledge override; ledger entities (CareLogEntry, LoyaltyEvent) exempt from version/updated_at.

**Verification:** 60 assertions across two smoke suites pass. `start.sh` boots cleanly, binds 0.0.0.0:$PORT foreground, empty store. (Note: test client connects to 127.0.0.1 on this macOS sandbox; server binds 0.0.0.0 correctly.)

## Step 7: Run Tests and Iterate — 2026-06-22T04:20:23.000Z

Clean exit achieved. All 8 parallel rounds pass 73/73.

**Iterations run:** 2 (initial diagnostic sweep + 1 fix sweep). Final 8-round parallel sweep clean: every round 73/73.

**Root cause (single, deterministic):** 39/73 tests failed identically across all 8 initial rounds, all tracing to one error — `ERR_STALE_VERSION` (`expected_order_version does not match`). 35 surfaced as "Setup step failed with HTTP 412", 4 as direct assertion failures.

The benchmark contract was correctly enforced by the implementation. PRD §2.5 ("`version` … increments by one on every mutation of the resource"), §2.6, and §2.7 (which explicitly cites "another writer has, **for example, added a line** … the request is rejected with `ERR_STALE_VERSION`") all establish that **adding an order line is a mutation that bumps the order's `version`**. The implementation's `add_line` correctly calls `touch(order)` (routes/orders.py:146), advancing the version from 1 → 2.

The **test layer was wrong**: setup helpers and several test bodies captured `order["version"]` at `create_order` time (=1) and passed that stale value to `confirm` after a line had been added, so the PRD-faithful server correctly rejected the confirm with `ERR_STALE_VERSION`. This was a TEST BUG (STEP 2 of the protocol), not an implementation defect — confirmed by the fact that `test_order_version_increments_on_confirm` and `test_confirm_with_stale_version_rejected` already passed by re-reading the live version via `get_order`, the canonical correct pattern.

**Tests deleted:** none. (No PRD-silence or non-derivability; the asserted rules are verbatim in PRD and uniquely determined.)

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — added `current_order_version(order_id)` helper (reads the live order version via `GET /orders/{id}`, per PRD §2.7 OCC). Rewrote the `confirm(...)` helper to re-read the live version before confirming instead of trusting the stale create-time version passed by callers. This single change fixed all 17 `X.confirm(...)` call sites in test bodies plus the 4 internal composite setups (`setup_confirmed_order`, `setup_fulfilled_order`, `setup_account_with_points`, `setup_b2b_credit_hold`), which then chain correctly off the returned live versions.

**Fixes applied to `test_suite/`:**
- `test_suite/test_03_order_pricing.py` — 5 inline `api.confirm_order(..., F.confirm_payload(order["version"]), ...)` calls (in `test_line_pricing_rounds_per_line_then_sums`, `test_two_line_promo_gross_and_net_totals`, `test_redemption_capped_at_post_discount_subtotal`, `test_promotion_inactive_outside_window_no_discount`, `test_confirm_response_carries_fresh_totals`) changed to read `X.current_order_version(order["id"])` before confirming. (`test_confirm_empty_order_rejected` left unchanged — it adds no line, so version stays 1, and `ERR_ORDER_EMPTY` precedes the version gate.)
- test_06 lines 84/126 (`test_credit_hold_account_blocks_confirm`, `test_confirm_redeeming_more_than_balance_rejected`) left unchanged: their asserted errors (`ERR_ACCOUNT_NOT_ACTIVE`, `ERR_INSUFFICIENT_POINTS`) precede the stale-version gate in PRD §2.8 precedence, so they pass regardless of the stale version, and both already passed.

**Fixes applied to `implementation/`:** none. The implementation was PRD-faithful throughout; no check was weakened, no endpoint/field/side-effect added, storage remained in-memory only.

## Step 8: Finalize PRD — 2026-06-22T04:22:11.000Z

**PRD.md vs PRD_FINALIZED.md:** 320 lines vs 320 lines, **0% delta** — `PRD_FINALIZED.md` is a verbatim copy of `PRD.md` (confirmed by `diff`: identical). **Zero edits made.**

**Conclusion:** The entire Step 7 diff was a test-layer fixture bug (stale order version captured at create time, reused after a line was added), fixed purely in `test_helpers/fixtures.py` and `test_suite/test_03_order_pricing.py`, with zero implementation fixes and zero test deletions. The implementation is PRD-faithful at the diff site, and the PRD already uniquely determines the behavior: §2.5 ("`version` … increments by one on every mutation"), §2.6 (side-effect mutations increment version), §3.3 ("Adding a line also refreshes the order's running gross total"), §2.7 (explicitly cites "another writer has, for example, added a line … the request is rejected with `ERR_STALE_VERSION`"). No diff item revealed a PRD silence or PRD/impl mismatch, so no edits were manufactured.

**Pre-edit search (sole diff subject — stale-version on add-line):** impl paths enumerated: `db.py:42-66` (base_versioned initial version 1; touch increments by one), `routes/orders.py:106-147` (add_line calls touch → version 1→2), `routes/orders.py:66-72` (_check_occ compares expected_order_version, raises ERR_STALE_VERSION), all order-mutating transitions (confirm/allocate/fulfill/cancel/charge_account/pay) call touch + _check_occ consistently. No off-site path diverges.

## Step 9: Complete PRD — 2026-06-22T04:28:31.000Z

**File deltas:** `PRD_FINALIZED.md` 320 lines / 51,694 chars → `PRD_COMPLETED.md` 320 lines / 53,287 chars (+1,593 chars; line count unchanged — every change is an in-paragraph insert/revision, no new paragraphs or sections).

**Counts:** Ambiguity-pins (PRD silent → pinned to impl): 8. Mismatch-revisions (PRD described different behavior → revised to impl): 1. Total changes: 9.

**Per-change log:**
- `§2.3 Pagination` — insert — ambiguity — list ordering ties on `created_at` broken by creation order, oldest-created first — `routes/*` sort on `_seq`, `db.py:48`
- `§2.5 Common Resource Properties` — insert — ambiguity — `version` initial value pinned to 1 on creation — `db.py:49`
- `§2.7 OCC` — insert — ambiguity — absent/non-integer `expected_order_version` rejected with `ERR_INVALID_REQUEST` (422) at the stale-version gate, after earlier state/business checks — `routes/orders.py:66-72`
- `§3.4 (allocate)` — insert — ambiguity — non-`CONFIRMED` order rejected with `ERR_ORDER_NOT_CONFIRMED`, checked before feasibility/version — `routes/orders.py:276-277`
- `§3.4 (lot selector)` — insert — ambiguity — final allocation tie (equal `created_at` and `received_qty`) resolved by creation order, earlier-created lot first — `routes/orders.py:327`
- `§3.4 (fulfill)` — insert — ambiguity — non-`ALLOCATED` order rejected with `ERR_ORDER_NOT_ALLOCATED` (checked first); only non-cancelled deliveries gate fulfillment, `CANCELLED` deliveries never block — `routes/orders.py:336-345`
- `§3.4 (cancel)` — insert — ambiguity — cancelling already-`FULFILLED`/already-`CANCELLED` order rejected with `ERR_ORDER_ALREADY_FULFILLED` — `routes/orders.py:379-383`
- `§3.5 Loyalty` — revise — mismatch — `points_balance` is the running sum of all signed `points_delta` (accruals less redemptions less reversal claw-backs), computed identically to `lifetime_points`, not "accruals minus redemptions" only — `services/loyalty.py:33-39`
- `§3.6 (pay)` — insert — ambiguity — paying an order already in `PAID` status rejected with `ERR_ORDER_NOT_CONFIRMED` — `routes/orders.py:476-478`
- `§3.9 (activate)` — insert — ambiguity — activation sets `ACTIVE` and bumps `version` with no current-status precondition; unresolved promotion id on activate returns `ERR_NURSERY_NOT_FOUND` (404) (no promotion-specific not-found code) — `routes/promotions.py:98-108`

**Left unchanged (impl already matches PRD / pinning would over-specify):** line-pricing promo tie-break (PRD already pins "earliest created_at"); confirm's lack of explicit DRAFT guard (no catalogued error; OCC version-bump prevents replay); warranty-window boundary inclusivity (already implied); negative field rejections (covered by §2.10 general field-shape clause).

---

## Pipeline Complete

All 9 steps finished. Final 8-round parallel stability sweep: **73/73 passing in every round**. Task artifacts present: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, test_helpers/, test_suite/, workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/, results.{1..8}.json}.
