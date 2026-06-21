# Worklog — task_0293_print_copy_shop_order

## Step 1: Create task directory — 2026-06-11T02:28:11.000Z

Created `tasks/task_0293_print_copy_shop_order/` with `workspace/` subdirectory (pre-assigned directory; index not scanned). Verified `INSTRUCTION.md` and all `skills/prd-bench-*` present.

## Step 2: Generate scaffold — 2026-06-11T02:48:41.000Z

## Worklog Summary — task_0293_print_copy_shop_order

**Scenario:** Print & Copy Shop Order (product catalog, file upload & preflight, quantity/option pricing, proof approval, turnaround/rush, pickup/ship, reorder, finishing add-on)
**Difficulty band targeted:** Expert (§0.4)

**Complexity profile:** pricing_engine (primary) + workflow_orchestration (secondary); flat topology; parallel state-machine shape; peer_roles; immediate consistency. Layers: dual_variant_calculation, cascading_side_effects, rate_threshold_triggers, optimistic_concurrency, derived_field_reconciliation.

**Scaffold metrics:**
- **Entities:** 13 (Shop, Product, PricingTier, FinishingOption, Customer, Order, OrderLine, Artwork, Proof, Fulfillment, Press, PressBooking, CapacityReservation)
- **State machines:** 8 dimensions across 7 entities — Order carries two parallel dimensions (production_status × payment_status); Proof is cyclic; OrderLine is branching-with-revert; plus Artwork, Fulfillment, CapacityReservation, PressBooking
- **Concurrency rules:** 2 (OCC on Order.version for confirm and cancel)
- **Calculations:** 10 (estimate_line_price, final_line_price, order_subtotal, order_loyalty_discount, order_total, line_turnaround, daily_capacity_check, press_overlap_check, preflight_evaluation, committed_loyalty_score)
- **Validations:** 15 (priority-ordered)
- **Endpoints:** 56 (includes FK reverse-reachability GETs, `/_clock/set_current_utc` and `/_inject/customer-loyalty` test-driving endpoints)
- **Errors:** 18
- **Roles:** 3 (ShopStaff opaque, ProductionOperator opaque, Customer entity_backed:Customer)

**Design files:** §1.8 = 18 difficulty instances (9 rules × 2); §1.9 = 35 active corner instances + 5 excluded_because stubs.

**Lint:** `scaffold_lint.py` — **VERDICT: clean lint** (56 endpoints, 13 entities, 18+35 instances, 460 calls scanned; all calls conform to §1.5 and all 17 FKs have reverse-reachability). All formula-derived asserts pre-computed as literals; no forbidden concurrency vocabulary; all enum values have producing paths; every error referenced; all endpoint roles in RBAC.

Files written: `SCAFFOLD.yaml` (1415 lines), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1361 lines), `SCAFFOLD_CORNER_DESIGN.yaml` (1463 lines).

## Step 3: Copy INSTRUCTION.md — 2026-06-11T02:48:41.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0293_print_copy_shop_order/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-11T02:54:52.000Z

**Task:** task_0293_print_copy_shop_order — PRD generated at `tasks/task_0293_print_copy_shop_order/workspace/PRD.md`

**Size:** 274 lines. Sections: §1 Introduction (2 paras), §2 Global Specifications (2.1–2.10, ten cross-cutting subsections), §3 Business Logic (3.1–3.9, nine workflow subsections), §4 Endpoint table (56 rows, 4 columns), §5 Error catalogue (18 rows, 2 columns).

**Hard Contracts — all PASS:**
- **Contract 1 (Field-Name Coverage):** 75/75 required identifiers present in backticks. Added bare `status` mention in §3.2.
- **Contract 2 (Rule Coverage):** Both concurrency_rules (confirm + cancel) expressed in OCC/stale-version terms with `expected_order_version`, `ERR_STALE_ORDER_VERSION`, HTTP 412 — no race-timing framing. All 9 calculations rendered as precise prose (round-then-multiply at discounted-unit step; tax on discounted-subtotal-minus-discount with rush excluded; capacity strict-greater boundary; press half-open + buffer-adjacency-allowed; preflight DPI-before-bleed with inclusive-150 boundary; committed loyalty weighted blend 1.0/0.5 with inclusive 3.0/6.0 thresholds). 15-rung validation precedence ladder stated. All cross-entity cascades covered. All 18 error IDs surface in §2/§3 narrative.
- **Contract 3 (§3 Path Purity):** 363 §3 backtick tokens scanned — 0 slash-leading, 0 bare HTTP-method, 0 method+path tokens.

**Design decisions:** Two-dimensional parallel order state model (production_status × payment_status) as §2.7 organizing principle. §3 split by lifecycle stage. Estimate-vs-locked pricing distinction got §2.8. Two `/_clock` and `/_inject` test hooks described as capabilities in §3.9 without leaking paths. No design YAMLs read.

## Step 5: Generate unit tests — 2026-06-11T03:10:38.000Z

**Test files:** 8 test files (`test_01`–`test_08`) + `conftest.py` in `test_suite/`; 9 modules in `test_helpers/`.

**Total tests:** 70 test functions, each carrying exactly one `Design:` tag.

**Queue A (Difficulty):** all 18 instances covered, every one with exactly 2 tests (36 tests). Covers all 9 rules. 0 skipped.

**Queue B (Corner):** 33 non-stub instances → 32 translated (1 test each), 1 skipped. The 5 `excluded_because` stubs correctly NOT translated.

**Skipped instances (why-category):**
- `Corner/state_machines/confirm_order_with_no_lines_returns_invalid_state` — missing-error-mapping gap. Instance asserts `ERR_VALIDATION` for zero-line confirm, but PRD never states which error fires for zero lines; not uniquely derivable.

**Derivability judgements:**
- Softened `version == 1`-on-creation asserts to "version is an integer" / "id is a server UUID" (PRD §2.4 says version "begins at its initial value" without pinning 1).
- Kept `confirm increments version by exactly 1` (PRD §3.6 explicit).
- Kept loyalty preview divergence test (committed 0.0 vs projected 1.0): UNPAID order → spend 0 in both, projected = count-only = 1.0.

**Helper design:** Customer is `entity_backed`; `make_customer_headers(customer_id)` for ownership-gated calls; opaque ShopStaff/ProductionOperator use shared-constant headers. Composite fixtures absorb empty-DB→confirmable chains. All PRD quotes confirmed via literal grep. No scaffold leakage; no skip/xfail; all files byte-compile clean.

## Step 6: Generate implementation — 2026-06-11T03:10:38.000Z

**Status:** Complete and smoke-tested. Boots via `start.sh` on `$PORT`/`0.0.0.0`, in-memory store only (no seeding, no persistence).

**Files (in `workspace/implementation/`):** `start.sh` (foreground, guards pip install on `import flask`), `requirements.txt` (flask==3.0.3), `app.py`, `db.py` (in-memory dicts, UUID/ISO-8601 minting, version start-at-1, pinnable clock, monotonic _seq), `errors.py` (all 18 error ids), `response.py` (envelopes + pagination meta), `middleware.py` (X-User-ID/Role auth 401 + role gate 403), `routes/` (9 modules), `services/` (common, pricing, serialize, ownership).

**Endpoints implemented:** 56 (full PRD §4 table incl. `/_clock` and `/_inject` hooks).

**Architecture:** State machines enforced inline per PRD §3.9 precedence ladder: auth(401)→role(403)→existence(404 left-to-right)→ownership(403)→state(409)→OCC(412)→business checks. Two-dimensional Order model (production_status × payment_status) as independent fields; READY bubbles up when all lines PRODUCED. Calculations (Decimal, ROUND_HALF_UP, integer cents) in `services/pricing.py`: round-half-up at discounted-unit step then integer-multiply; greatest-min_quantity tier; rush surcharge separate at lock; order totals ordered (subtotal→loyalty discount→rush fee→taxable base subtotal-discount→tax→+rush+ship); turnaround whole-day with rush-cutoff slip; committed loyalty (1.0·count + 0.5·paid/10000, round-half-up 1dp, inclusive GOLD≥6/SILVER≥3); loyalty-preview forward projection over CONFIRMED/IN_PRODUCTION/READY. Confirm atomic (all preconditions before commit; capacity strict-greater boundary). Cascades: cancel releases HELD reservations + CONFIRMED bookings (each child version-bumped); product edits recompute estimate only on OPEN lines. OCC on expected_order_version for confirm/cancel (412); reorder bumps source version.

**Precedence judgment:** Followed §3.9 deterministic ladder (OCC before business checks; press-overlap before booking-interval) over §3.5/§3.6 conversational ordering. Empty-order confirm maps to `ERR_LINE_NOT_LOCKABLE` (only fitting catalog error for "no lockable lines").

## Step 7: Run tests and iterate — 2026-06-11T03:16:37.000Z

All 8 parallel rounds pass cleanly (70/70 each, 0 failures, 0 errors). Verified results.{1..8}.json all 70/70.

**Iterations run:** 2 (one diagnostic sweep + one confirmation sweep after the fix).

**Initial state:** Round 1–8 each at 69/70. Exactly one deterministic failure across all 8 rounds (not flaky — same test every round): `test_loyalty_committed_zero_while_preview_projects_one` in `test_suite/test_07_payment_loyalty_and_production.py`. Failure: `assert 1.3 == 1.0` on `preview["projected_loyalty_score"]`.

**Root cause (STEP 1b — UNIQUE-DERIVABILITY collapse):** Test asserted exact loyalty-preview projected score of `1.0`. PRD §3.7 says preview "projects the score forward as if the customer's confirmed-but-not-yet-fulfilled orders had already completed." The committed-score formula blends `completed_order_count` (×1.0) and `lifetime_paid_cents/10000` (×0.5). PRD does not pin whether "as if completed" folds in payment. Reading A (test): completion=hand-off only increments count → 1.0. Reading B (impl): hand-off requires PAID, so projection folds order's total ($60) into projected lifetime_paid_cents → 1.0 + 0.3 = 1.3. Both PRD-faithful → COMPUTED-FIELD-SILENCE collapse. Exact value 1.0 not uniquely derivable. Implementation (Reading B) correct, unchanged.

**Fix applied (STEP 1c — PARTIAL COVERAGE split, not full deletion):** `test_suite/test_07_payment_loyalty_and_production.py`, `test_loyalty_committed_zero_while_preview_projects_one`. Replaced non-derivable exact-value assertion `projected_loyalty_score == 1.0` with uniquely-derivable directional fact `projected_loyalty_score > committed_loyalty_score`. Kept PRD-determined assertions: committed `loyalty_score == 0.0`, `loyalty_tier == "NONE"`, `committed_loyalty_score == 0.0`.

**Fixes to `test_helpers/`:** none.
**Fixes to `implementation/`:** none (impl's preview projection Reading B traces to PRD §3.7, unchanged).
**Tests deleted:** none (partial-coverage split per STEP 1c).

**Final result:** 8/8 parallel rounds clean — 70/70 passed, 0 failed, 0 errors in every round.

## Step 8: Finalize PRD — 2026-06-11T03:18:51.000Z

**PRD.md vs PRD_FINALIZED.md:** 274 → 274 lines (0.0% delta; one paragraph revised in place). Trailing "informational only" sentence preserved verbatim.

**Change:**
- **§3.7 (loyalty preview) — revise** — pinned forward-projection mechanics: starts from committed `completed_order_count`/`lifetime_paid_cents`; folds in orders with `production_status` in {`CONFIRMED`, `IN_PRODUCTION`, `READY`} (+1 to count each; adds `total_cents` to projected `lifetime_paid_cents` only when not yet `PAID`); derives `projected_loyalty_score`/`projected_loyalty_tier` via the same committed-score formula and tier thresholds — `implementation/routes/customers.py:66-82`.

Single Step 7 item. Original PRD only said preview "projects the score forward as if confirmed-but-not-yet-fulfilled orders had already completed" — did not pin (a) which production_status values qualify, (b) that projection folds order total_cents into projected lifetime_paid_cents (Reading B → 1.3 not 1.0), (c) no-double-count guard for already-PAID orders. Now pinned to match impl.

**Pre-edit search log:** Subject = loyalty preview forward projection. Enumerated impl paths: `routes/customers.py:60-85` (preview, Step 7 site), `services/pricing.py:128-139` (`compute_loyalty_score`/`tier_for_score` shared helper), `routes/fulfillments.py:102-108` (committed settlement uses identical formula), `routes/orders.py:370` (pay += total_cents) and `:392` (refund -= total_cents) justify PAID-guard, `routes/orders.py:239` (discount keys on committed tier, untouched). Wording deferred to "very same formula and inclusive tier thresholds defined above" to avoid drift from pricing.py; status filter scoped with explicit exclusion list.

## Step 9: Complete PRD — 2026-06-11T03:24:39.000Z

**Source vs completed:** PRD_FINALIZED.md 274 lines / 44,592 chars → PRD_COMPLETED.md 274 lines / 46,592 chars (+2,000 chars; all in-paragraph, no line-count change).

**Counts:** 10 changes — 8 ambiguity-pins, 2 mismatch-revisions. No new sections.

**Per-change log:**
- §2.3 Pagination — insert — ambiguity — out-of-range `limit`/`offset` silently clamped (limit→[1,100], offset→≥0), non-integer rejected `ERR_VALIDATION` — `services/common.py:99-122`
- §3.2 Customers — revise — mismatch — customer `email` "unique within shop" NOT enforced; duplicate emails accepted — `routes/customers.py:22-41`
- §3.2 Orders — insert — ambiguity — Customer opening order with `customer_id` ≠ `X-User-ID` rejected `ERR_NOT_ORDER_OWNER` (403) — `routes/orders.py:39-41`
- §3.2 Line Assembly — insert — ambiguity — line creation does not check parent order's `production_status`; admitted in any state — `routes/order_lines.py:41-88`
- §3.3 Artwork — revise — ambiguity — `page_count`/`dpi` integers; `bleed_mm` may be fractional — `routes/artworks.py:33-35,128-134`
- §3.6 Confirm — insert — ambiguity — order with zero lines rejected `ERR_LINE_NOT_LOCKABLE` (409) — `routes/orders.py:174-175`
- §3.6 Totals — revise — ambiguity — shipping fee comes from earliest-created fulfillment when more than one — `routes/orders.py:243,406-409`
- §3.8 Reorder — insert — ambiguity — accepts `expected_order_version` but performs no OCC check; never returns `ERR_STALE_ORDER_VERSION` — `routes/orders.py:103-107`
- §3.8 Reorder — insert — ambiguity — cloning recomputes estimate at clone time, does NOT re-apply product-active guard; inactive-product lines still clone — `routes/orders.py:116-139`
- §3.9 Clock-pin — revise — ambiguity — pin governs only confirm-time turnaround/rush-cutoff arithmetic and returned `current_utc`; `created_at`/`updated_at`/`api_request_timestamp` keep real wall clock — `db.py:44-69,85-99`, `response.py:32`

**Already-pinned (no change):** §3.9 validation precedence (state-before-business, overlap-before-interval, finishing-before-active), loyalty dollars conversion, estimate-vs-locked pricing, round-then-multiply, press half-open buffer, capacity strict-greater, preflight DPI-before-bleed boundaries, response serializers, generic `ERR_INVALID_STATE` rung.

---

## Pipeline complete — 2026-06-11T03:24:39.000Z

All 9 steps finished. Final state: 70/70 tests pass across all 8 parallel stability rounds. Deliverables in `tasks/task_0293_print_copy_shop_order/`: SCAFFOLD.yaml + 2 design YAMLs, worklog.md, test_helpers/ (9 modules), test_suite/ (8 files, 70 tests), workspace/ (INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/ + results.{1..8}.json).
