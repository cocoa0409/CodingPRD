# Worklog — task_0342_wholesale_vehicle_auction

## Step 1: Create Task Directory — 2026-06-14T00:00:00.000Z

Task directory pre-allocated by orchestrator: `tasks/task_0342_wholesale_vehicle_auction` (Step 1 index scan/increment skipped per instructions). Confirmed `workspace/` subdirectory exists. Scenario: Wholesale Vehicle Auction (Manheim style). Difficulty: Expert (to be passed to scaffold-generator only).

## Step 2: Generate Scaffold (Expert) — 2026-06-14T00:00:00.000Z

All three artifacts are complete and validated. The endpoint count (64) is above the Expert band's 20–32 guideline, but that's because the flat topology generates one GET-list + one GET-detail per entity (13 entities × ~5 endpoints). The interesting action surface is lean; the GET pairs are mechanical CRUD required for FK reverse-reachability. The coupling density (cross-entity cascades, dual-variant calcs, parallel state axes) is where the Expert difficulty actually lives.

## Summary

Generated all three scaffold artifacts for **task_0342_wholesale_vehicle_auction** at **Expert** difficulty. `scaffold_lint.py` reports **VERDICT: clean lint** (592 calls across 20 §1.8 + 30 §1.9 instances, all FKs reverse-reachable).

**Files written** (all under `tasks/task_0342_wholesale_vehicle_auction/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 + concurrency_rules
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`

**Structural profile** (flat topology, `peer_roles`, parallel state-machine shape):
- **13 entities**: AuctionSale, Lane, Seller, Buyer, Consignment, ConditionReport, RunListEntry (Lot), Bid (append-only event), ArbitrationClaim, Settlement, GatePass, Carrier, TransportOrder
- **9 state machines, 64 endpoints, 59 error codes, 9 calculations, 12 validations, 4 roles** (AuctionAdmin/Arbitrator opaque; Seller/Buyer entity_backed)
- One OCC concurrency rule (`bid-create-stale-lot`) on `RunListEntry.version`

**Non-linear state machines** (Difficulty Rule 3): Settlement carries **parallel `payment_status × title_status` axes** on one row; Consignment has a **cycle** (RUN_LISTED↔IF_PENDING via lot relist); RunListEntry **forks** SOLD/IF/PASSED with divergent side-effects; ArbitrationClaim **branches** APPROVED_FULL/APPROVED_PARTIAL/DENIED.

**Key calculations**: `clearing_price` (second-price proxy auction, nested min/max over top/second ceilings + increment, earliest-`created_at` tie-break — never `id`); `bid_increment` (tiered ladder with strict `>=` band boundaries at 500000/1000000); `sale_outcome` (inclusive reserve threshold); `buyer_fee` and `seller_net_proceeds` (both **dual-variant** provisional@hammer vs final@settlement-after-arbitration, on different entity domains); `buyer_total_due` (pinned per-term-round-then-sum order, mode-b combinatorial); `arbitration_credit`; plus two conserved-quantity aggregations (`buyer_credit_balance`, `lane_slot_occupancy`).

**Expert calibration notes**: All 9 §0.5 rules satisfied with 2 instances each (18) plus 2 OCC instances = 20 §1.8 instances. Cascade depth-4 (payment→CLEARED→GatePass→Consignment SETTLED) and depth-3 (arbitration→Settlement VOID→Consignment ARB_UNWOUND); two temporal-overlap rules with distinct interval semantics on different resources (Lane half-open no-buffer vs Carrier closed-interval + turnaround buffer); two compensating invariants over different conserved quantities (buyer credit in cents vs lane slot count). All formula-derived asserts are pre-computed literals.

## Step 3: Copy Shared Files — 2026-06-14T00:00:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-14T00:00:00.000Z

Generated `workspace/PRD.md` (363 lines) from the EXPERT-tier wholesale-vehicle-auction scaffold.

### Structure
- **§1 Introduction** — 3 paragraphs framing the four-party (seller/buyer/operator/arbitrator) remarketing domain, the money-title-inventory-gate reconciliation promise, two hard precision concerns.
- **§2 Global Specs** — 11 subsections: RBAC (2.1), fixed Response Structure (2.2), Pagination (2.3), Common Properties/Versioning (2.4, including Bid's `common_fields:false` reduced set), Nested/Referential Resolution (2.5), Validation Precedence (2.6), Monetary Precision & Rounding (2.7), Provisional-vs-Final principle (2.8), OCC on the live block (2.9), Buyer Credit conservation ledger (2.10), Cascade Consistency (2.11).
- **§3 Business Logic** — 12 subsections by lifecycle: sale+lane lifecycle, dealers, consignment+condition report, run-list/slot scheduling, the block (bids+clearing price+bid increment), close/hammer/outcome, buyer fee+total due, seller net proceeds, settlement (dual-axis payment×title + clearing cascade + write-off), arbitration, gate pass+transport, filtered-list discovery.
- **§4** — 64-row endpoint table. **§5** — 59-row error table.

### Coverage (verified mechanically)
- 64/64 endpoints and 59/59 errors match scaffold exactly. Contract 1 (Field-Name) PASS, Contract 2 (Rule) PASS (12 priority validations, single OCC rule, all transitions, both Settlement axes + 4-deep clearing cascade, arbitration's three branches, all 8 calculations), Contract 3 (§3 Path Purity) PASS (0 slash-paths in §3).

### Notable scattering decisions
- Bid inputs split: core params in §3.5; `expected_lot_version` anchored in §2.9 (OCC).
- `total_due_cents` formula split between §3.7 (computation) and §2.10 (conserved credit ledger).
- Calculation constants embedded with dollar-context unit conversions.
- Flat peer-collection topology expressed via filtered-list discovery (§3.12) + FK-in-body framing, no nested paths.
- Bid `PLACED` state mentioned once as immutable append-only event.

## Step 5: Generate Unit Tests — 2026-06-14T00:00:00.000Z

Generated complete test infrastructure for **task_0342_wholesale_vehicle_auction** from the two design indices only (no freelance walking of SCAFFOLD.yaml). All 70 tests collect cleanly, byte-compile, carry verbatim PRD citations (91/91 citations confirmed against a literal grep of PRD.md), and end with exactly one `Design:` tag resolving to a real instance.

### Coverage
**Queue A — Difficulty (20 instances, all covered with exactly 2 tests each):** All 10 rule_ids × 2 instances satisfied: `dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`, `optimistic_concurrency`. The companion test for each instance pins a different observable consequence of the same PRD rule.

**Queue B — Corner (30 non-stub instances, all covered with 1 test each):** sections `entities` (7), `endpoints` (2), `state_machines` (6), `validations` (5), `rbac` (4), `errors` (4), `cross_cutting_complexity_layers` (1 active: `arbitration_partial_recredit_delta`), `consistency_model` (1).

**Skipped instances:** None. Every non-stub instance passed the PRD-first two-condition filter. **Stubs (correctly NOT translated):** 3 `excluded_because` stubs in `cross_cutting_complexity_layers`.

### Key findings
- Verified all pre-computed monetary literals against PRD formulas (buyer_fee 47850/41250, total_due 772850/666250/213208, seller proceeds 705500/607500, credit re-credit deltas, clearing 525000/509999) — all consistent.
- One tag bug caught and fixed during audit: `write_off_suspends_buyer_and_recredits` lives in corner section `state_machines`, not `endpoints` — tag corrected.
- Identity threading honored: `Buyer`/`Seller` are `entity_backed`, so all bids/arbitration/transport calls use `make_buyer_headers(buyer["id"])` with real entity id.

### Files
`test_helpers/`: `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`
`test_suite/`: `conftest.py`, `test_01_clearing_and_fees.py`, `test_02_lifecycle_and_cascades.py`, `test_03_concurrency_temporal_precedence.py`, `test_04_difficulty_companions.py`, `test_05_entities_and_listing.py`, `test_06_preconditions_and_validations.py`, `test_07_rbac.py`

## Step 6: Generate Implementation — 2026-06-14T00:00:00.000Z

Built a complete Python + Flask in-memory REST API. All state in module-level dicts in `db.py`, wiped on every restart; no seeding or disk persistence.

### Files created (in `workspace/implementation/`)
- `start.sh` — foreground launcher, guarded `pip install`, `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `app.py`, `db.py`, `errors.py`, `response.py`, `middleware.py`, `routes/` (sales+lanes, dealers, consignments+condition-reports, lots+bids, arbitration, settlements, transport), `services/` (`calc.py`, `cascade.py`, `common.py`, `lookup.py`)

### Endpoints: All 64 from PRD §4.

### State machines & calculations encoded
- **Sale** DRAFT→OPEN→RUNNING→CLOSED→SETTLED (cascades lanes); **Lot** SCHEDULED→BIDDING_OPEN→BIDDING_CLOSED→(HAMMERED|PASSED|IF_PENDING), HAMMERED→FINALIZED/ARB_REVERSED, IF_PENDING→SCHEDULED relist; **Settlement** parallel payment×title axes + 4-deep clearing cascade; **Arbitration** OPEN→RESOLVED with DENIED/APPROVED_PARTIAL/APPROVED_FULL branches.
- **Calculations** verified at band boundaries: bid_increment (3 bands strict `>=`), clearing_price (proxy, earliest-created_at tie-break), buyer_fee (STANDARD/PREMIUM + 10% online surcharge, per-term round-then-sum), seller_net_proceeds (commission cap 150000, assurance 5000, floor 0), arbitration_credit (30% cap inclusive), buyer credit ledger, OCC on `expected_lot_version` (412). Validation precedence per §2.6.

### PRD ambiguities resolved
- No `ERR_CONSIGNMENT_NOT_CATALOGED` exists → lot creation cascades consignment to RUN_LISTED only when CATALOGED (no error otherwise).
- TransportOrder ownership derived/stored from referenced settlement's buyer (entity has no `buyer_id` input).
- Carrier window buffer = required gap `>= turnaround_buffer_minutes` between closed pickup intervals.
- `record-payment` recompute is no-op for committed_cents but keeps invariant safe.

## Step 7: Run Tests and Iterate — 2026-06-14T00:00:00.000Z

All 8 parallel rounds pass 70/70 with no failing union. The earlier missing-file was confirmed transient (round 3 passed both in isolation and in this clean sweep). Exiting with the summary.

**Iterations run:** 2 sweeps with fixes, plus 1 transient-confirmation re-run, plus 1 final clean sweep. Final state: all 8 parallel rounds pass 70/70.

**Initial state:** 68/70 in all 8 rounds — 2 deterministic failures, both in `test_suite/test_04_difficulty_companions.py`.

**Root cause (shared):** Both failing tests assumed a single PROXY bidder's ceiling becomes the hammer price. Per PRD §3.5, a single bidder clears at "the lesser of C1 and the greater of the house floor and the lot's `starting_bid_cents`" — i.e. `max(house_floor, starting_bid)`, capped by the ceiling. With `starting_bid_cents=400000` the hammer is 400000, not the bidder's 800000 ceiling. The implementation's clearing-price logic was correct; the tests were not.

**Tests deleted:** None (no PRD-silence deletion needed).

**Fixes applied to `test_suite/` (no `test_helpers/` changes needed):**

1. `test_04_difficulty_companions.py::test_clearing_mirrors_final_proceeds_onto_consignment` — STEP 2 test bug. The fixture's single PROXY bid (ceiling 800000) did not produce the 800000 hammer the asserted literal (779000) assumed; per §3.5 a single bidder clears at `max(house_floor, starting_bid)`. Changed `starting_bid_cents=400000`→`800000` so the single-bidder clearing price genuinely equals 800000, making the cited §3.9 mirror assertion (proceeds 779000) PRD-correct.

2. `test_04_difficulty_companions.py::test_full_approval_voids_gatepass_and_zeros_consignment_proceeds` → renamed `test_full_approval_voids_gatepass` — STEP 1c partial-coverage split. The `expected_proceeds_cents == 0` assertion collapses under STEP 1b in this cleared-first scenario: PRD §3.10 zeroes proceeds only as "the consignment cascades **from `SOLD`** to `ARB_UNWOUND`", but the test clears the settlement first, leaving the consignment `SETTLED` — a state the PRD's unwind cascade does not cover, so a faithful reader can implement it either way (collapse pattern: BRANCH-ASYMMETRIC / state-gated side effect with PRD silence on the non-`SOLD` source state). Removed only that assertion; kept the gate-pass-VOID assertion, which is verbatim-covered, uniquely derivable, and is this companion's distinct target. The SOLD→ARB_UNWOUND proceeds-zeroing remains covered by the `test_02` counterpart (`test_full_approval_arbitration_reverses_settlement_unwinds_consignment_and_lot`) which exercises it from the correct `SOLD` state.

**Fixes applied to `implementation/`:** None — the implementation was PRD-faithful (correct single-bidder clearing price, and a full-approval unwind correctly gated on the consignment being `SOLD`).

**Flakiness note:** One round's results file went missing in the first post-fix sweep due to runner-side port/boot contention at 8x peak load. Re-running that round in isolation gave 70/70, and a subsequent clean 8-round parallel sweep produced 70/70 across all 8 rounds — confirming no test/implementation flakiness.

## Step 8: Finalize PRD — 2026-06-14T00:00:00.000Z

The patch is in place — exactly one paragraph revised (§3.10), one logical edit, minimal change.

**Line counts:** PRD.md = 363 lines; PRD_FINALIZED.md = 363 lines (one paragraph revised in place; +0 lines, %-delta ≈ 0%). One sentence appended within §3.10's existing unwind paragraph.

**Changes (one bullet per change):**
- **§3.10 — revise** — appended a clause to the full-approval-unwind paragraph pinning that the settlement-void, buyer re-credit, and gate-pass-void steps are unconditional, while the lot→`ARB_REVERSED` and consignment→`ARB_UNWOUND`(+proceeds-zeroing) cascades are gated on their source states (`HAMMERED`/`SOLD`); and explicitly stating the cleared-first case (lot `FINALIZED`, consignment `SETTLED`) leaves the lot/consignment unchanged with `expected_proceeds_cents` not zeroed — `implementation/services/cascade.py:123-152` (`unwind_settlement`).

**Per-edit pre-edit search log:**
Edit 1 (§3.10 unwind cleared-first behavior):
- (a) Subject: full-approval unwind's per-entity side effects — which steps unconditional vs state-gated; consignment proceeds/lot status/consignment status when settlement already cleared (consignment SETTLED, lot FINALIZED) vs SOLD/HAMMERED.
- (b) Impl paths enumerated/read: `cascade.py::unwind_settlement` (:123-152, settlement+credit unconditional, lot gate at :137, consignment+proceeds gate at :143-146, gate-pass at :149-152); `cascade.py::maybe_clear_settlement` (:69-107, produces cleared-first states); `routes/settlements.py::record_payment/record_title` (:39-67); `routes/arbitration.py::rule_claim` (:71-130); `routes/lots.py::hammer_lot` (:173-231); `calc.py::clearing_price` (:78-81, confirmed Item 1 is pure fixture bug — single-bidder branch matches §3.5).
- (c) Wording adjustment: kept original sentence verbatim, only appended. Gate-pass step worded as "gated only on a gate pass existing in `ISSUED` status" (not unconditional) so normal path with no gate pass yet isn't mis-described. Lot/consignment gates worded as "only if currently `HAMMERED`/`SOLD`" so all off-Step-7 source states are correctly left untouched. No claim about title_status, keeping wording under-determined where impl is silent.

## Step 9: Complete PRD — 2026-06-14T00:00:00.000Z

Full PRD-vs-implementation completeness scan. All four edits applied cleanly (in-paragraph inserts/revisions, no new sections).

**Source vs completed**
- `PRD_FINALIZED.md`: 363 lines, 55,752 chars
- `PRD_COMPLETED.md`: 363 lines, 56,600 chars (char delta +848; line delta 0 — all edits in-paragraph)

**Counts:** Ambiguity-pins: 3; Mismatch-revisions: 1.

**Changes**
- §2.1 (RBAC) — insert — ambiguity — pinned that an absent/empty/whitespace-only header is treated as missing, and an `X-User-Role` not exactly one of the four recognized roles is treated as malformed; both yield `ERR_MISSING_AUTH_CONTEXT` — `middleware.py:17-24`
- §3.1 (Lanes) — revise — ambiguity — pinned that `lane_number` uniqueness is checked only against non-`ARCHIVED` lanes, so a number held only by an archived lane may be reused — `routes/sales.py:152`
- §3.4 (Building the Run List) — insert — ambiguity — pinned that a slot falling outside the lane's operating window is rejected with `ERR_LANE_SLOT_OVERLAP` (same error as the overlap case) — `routes/lots.py:46-48`
- §3.11 (Transport) — revise — mismatch — pinned that transport-order buyer ownership derives from the referenced settlement's `buyer_id`, so `settlement_id`/`carrier_id` existence is resolved before the ownership check; reverses the generic §2.6 ownership-before-existence ordering for this endpoint — `routes/transport.py:123-128`

**Deliberately unchanged:** hammer-time `ERR_CROSS_SALE_REFERENCE` guard structurally always satisfied; lot creation has no consignment-status precondition (consistent with PRD's exhaustive constraint list); ownership-before-existence holds for path-resource-owned operations. PRD otherwise thorough on calculations, state machines, error codes, cascades — all matched impl exactly.

---

## Pipeline Complete

All 9 steps finished. Final test state: **70/70 passing across all 8 parallel rounds**. Artifacts present: SCAFFOLD.yaml + 2 design indices, PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, test_helpers/ + test_suite/ (70 tests), workspace/implementation/ (Flask, in-memory, 64 endpoints), 8 passing results.{1..8}.json.
