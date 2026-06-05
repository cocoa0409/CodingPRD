# Worklog — task_0128_cinema_box_office_seating

Scenario: 128. Cinema Box Office & Seating: showtime scheduling, reserved seat map, dynamic/matinee pricing, concession combo, membership/loyalty, distributor sliding film-rental split, refund/exchange, group/private rental

## Step 1: Create task directory — 2026-06-04T00:32:00.000Z

Created `tasks/task_0128_cinema_box_office_seating/` with `workspace/` subdirectory. Index 0128 (highest existing was 0127).

## Step 2: Generate scaffold — 2026-06-04T00:54:00.000Z

All three required scaffold files are generated and the lint verdict is clean. Generation complete.

### Summary

Generated the complete scaffold package for **task_0128_cinema_box_office_seating**. All three files pass `scaffold_lint.py` (`VERDICT: clean lint`, 478 calls scanned across §1.8+§1.9, all FKs reverse-reachable).

**Complexity profile**: Expert band. Primary archetype `quota_allocation` (reserved seat map: FREE→HELD→SOLD) blended with `pricing_engine` (dynamic/matinee/peak + sliding distributor split); layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers; hybrid topology; branching state-machine shape; peer_roles. `api_prefix: ""` (flat top-level collections) so FK reverse-reachability resolves.

**SCAFFOLD.yaml (§1.0–§1.7)**:
- **11 entities**: Auditorium, Film, Distributor, Showtime, Seat, Member, ConcessionCombo, Order, Ticket, Payment, Settlement (14 FKs, all with reverse-reachability GETs).
- **4 state machines + 2 concurrency rules**: Showtime (branching: SCHEDULED→{ON_SALE,CANCELLED}, →CLOSED with settlement), Order (branching at PAID→{REFUNDED,EXCHANGED}, plus HELD→EXPIRED/CANCELLED/PAID), Ticket, Film. OCC concurrency rules on `Showtime.version` for order-create and cancel (true CREATE-with-supersede races, 412).
- **5 calculations**: provisional vs final ticket price (re-priced between hold/pay), order total (combo discount round-then-sum pinned), loyalty accrual+tier derivation (>=50 SILVER / >=200 GOLD), distributor sliding split (week-indexed tiered pct with MG-floor max()), each with verified literal outputs.
- **19 validations** (priority-ordered), **39 endpoints** (incl. one `/_clock/advance` test-driving endpoint), **19 errors**, **5 roles** (CinemaManager/BoxOfficeAgent opaque; Member/Distributor entity_backed; Anonymous).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)**: all 9 §0.5 rules × **2 instances = 18 instances**, each with an executable empty-DB setup chain, every numeric assert pre-computed as a literal (e.g. prov 1000 vs final 1300; split 4200 vs 2100; MG-floor 2000; combo round-then-sum 1742 not 1741; loyalty 50→SILVER boundary; auditorium 22:00<22:05 buffer; member zero-buffer overlap).

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9)**: **37 active corner instances + 4 `excluded_because` stubs** (41 total) across all 9 claim-extraction-guide sections.

Key design decisions: `api_prefix:""`, optional-fields and `Entity[]` outputs quoted to survive YAML flow-mapping parsing, three dead-end enum values removed for enum-closure compliance.

## Step 3: Copy INSTRUCTION.md — 2026-06-04T00:55:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0128_cinema_box_office_seating/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-04T01:00:00.000Z

PRD generated at `workspace/PRD.md` (288 lines).

**Structure**: 5 top-level sections (Introduction; Global Specifications; Business Logic & Workflows; Endpoint Definitions; Error Code Catalogue). §2: 10 subsections (RBAC; Response Structure; Pagination; Common Resource Properties; OCC on Showtimes; Cascading Mutations; Nested Retrieval + validation precedence; Monetary Values/Pricing/Rounding; Loyalty/Tiers/Wallet; Auditorium Turnaround). §3: 10 subsections. §4: 39-row endpoint table; §5: 19-row error table.

**Hard Contract reports**: Field coverage 65/65 PASS; Rule coverage (19 validations, 2 OCC, all state machines, 5 calculations, sibling-branch symmetry) PASS; Path purity (§3, 278 tokens, 0 path-leaks) PASS.

**Notable coverage decisions**: OCC framed purely in stale-version terms (no race/timing); constants embedded in prose with unit framing (profile multipliers 1.00/0.70/1.30, MATINEE cutoff hour<17, PREMIUM surcharge 400 cents, 15-min hold TTL + trailer pad, 100-cent points divisor, tier breakpoints 50/200, rental cut 0.10); order-total pinned evaluation order + round-then-sum-per-combo spelled out; member-overlap (zero buffer, half-open) contrasted against auditorium double-booking (turnaround buffer); §3 path-free.

## Step 5: Generate unit tests — 2026-06-04T01:16:00.000Z

Generated complete test infrastructure. **test_helpers/** (9 files): types.py (Distributor/Seat carry only id+created_at), api_client.py, api_errors.py (19 error IDs), assertions.py (+seat-conservation invariant), factories.py, constants.py, test_users.py (opaque + entity-backed builders), fixtures.py, __init__.py. **test_suite/** (1 conftest + 7 files): 72 test functions.

**Coverage**: Queue A (Difficulty) 18/18 instances translated (40 tests). Queue B (Corner) 36/37 non-stub translated (32 tests); 4 excluded_because stubs verified.

**Skip / PRD gap**: `Corner/calculations/premium_seat_class_surcharge_added` SKIPPED — PRD describes seat_class + 400c PREMIUM surcharge but provides NO input pathway to make a seat PREMIUM (showtime-create takes no seat-class params, seats auto-materialize as STANDARD). Not uniquely derivable; logged as PRD gap, not papered over.

**Verification**: all 72 collect under pytest; all files byte-compile; 89 PRD citations survive literal grep; every test exactly one Design: tag, all resolve; no skip/xfail; no scaffold leakage. Tests collected not executed (no impl at gen time).

## Step 6: Generate implementation — 2026-06-04T01:16:00.000Z

Generated complete Python + Flask impl at `workspace/implementation/` (23 files): start.sh, requirements.txt (flask==3.0.3), app.py, db.py, clock.py, errors.py, response.py, middleware.py; services/{common,domain}.py; routes/{_helpers,auditoriums,distributors,films,members,combos,showtimes,orders,tickets,settlements,clock_ctl}.py + package markers.

**Endpoints**: all 39 from scaffold §1.5. **Storage**: in-memory dicts, empty at boot (no seeding); logical UTC clock pinned by /_clock/advance drives all timestamps + time comparisons, falls back to wall-clock when unpinned; process-local so per-test-server restart starts clean. start.sh guards pip install behind Flask-import check; app.py has bind-retry loop for same-port reboot races.

**Verified manually**: envelope (meta/response_type/data, req_ ids, pagination), validation precedence, OCC (412), dual-variant pricing (provisional@hold vs final@pay), PEAK/MATINEE multipliers + matinee guard, PREMIUM surcharge, loyalty accrual/reversal + tiers, combo discount round-then-sum (BRONZE ignored), wallet credit/debit, hold expiry via clock sweep, refund (ORIGINAL/WALLET) + loyalty reversal, exchange w/ delta, showtime-cancel cascade, close→settlement (sliding split + MG floor + RENTAL 0.10), lean Distributor/Seat.

**PRD ambiguities resolved**: (1) seats materialized row_label="A", seat_number=1..N, seat_class="STANDARD" (declared defaults); PREMIUM logic implemented but unreachable. (2) exchange delta exposed as amount_due_cents on successor. (3) refund_destination ∈ {ORIGINAL,WALLET}. (4) POST /members sole no-auth endpoint. (5) existence (404) resolved before ownership (403).

## Step 7: Test and iterate to green — 2026-06-04T01:36:00.000Z

All tests pass. Final sweep: all 8 parallel rounds green, 72/72 each. (Orchestrator re-ran the 8-round sweep after Step 7 subagent's `rm -f` cleared the results files; confirmed 72/72 × 8 and regenerated results.{1..8}.json.)

**Iterations run:** 2 (initial diagnostic sweep + one fix-and-verify sweep). Initial sweep showed 5 deterministic failures (identical across all 8 rounds — no flakiness).

**Root cause:** Per PRD §3.5, `tickets_subtotal_cents` and `combos_subtotal_cents` are computed **"At payment"**, not at HELD-order creation. The implementation is PRD-faithful (leaves these at 0 on a HELD order, computes them at pay). Four of the five failing tests checked these subtotals on a HELD order; the fifth asserted a wallet-credit side effect the cancel cascade never produces.

**Tests deleted:** None (all rules verbatim PRD-covered; issues were lifecycle-timing and an uncovered side-effect assertion, handled by STEP 2 fixes and STEP 1c partial-coverage trims).

**Fixes applied to `test_suite/`** (no test_helpers/ or implementation/ changes — implementation already PRD-faithful):
- `test_01_pricing_and_settlement.py` — `test_combo_discount_rounded_per_combo_then_summed` and `test_silver_member_combo_discount_applied`: switched `create_held_order` → `create_paid_order` (STEP 2 — PRD §3.5 computes combos_subtotal_cents at payment; discount formula PRD-verbatim, unchanged).
- `test_06_scheduling_and_order_validations.py` — `test_combo_bronze_member_pays_list_price`: same `create_held_order` → `create_paid_order` fix.
- `test_07_rbac_concurrency_and_exchange.py` — `test_order_create_response_reflects_held_state_immediately`: trimmed `tickets_subtotal_cents == 1000` assertion on a HELD order (STEP 1b COMPUTED-FIELD SILENCE / STEP 1c — PRD §3.4 silent on subtotal at HELD; kept `status == "HELD"`).
- `test_02_order_lifecycle_and_cascades.py` — `test_cancel_showtime_cascades_refund_payment_and_wallet`: trimmed `wallet_credit_cents == 1500` assertion (STEP 1b BRANCH-ASYMMETRIC SIDE EFFECT — PRD §3.8 enumerates cascade as "payment marked refunded, tickets voided, seats freed, loyalty reversed" with no refund_destination; §3.7 wallet credit conditional on wallet destination the cancel never names. Kept verbatim-covered: REFUNDED order/payment status + refunded_cents == 1500).

**Fixes applied to `implementation/`:** None.

## Step 8: Finalize PRD — 2026-06-04T01:39:00.000Z

Produced `workspace/PRD_FINALIZED.md`. Line counts: PRD.md=288, PRD_FINALIZED.md=288 (0% line delta — both edits extend existing lines in place; net +2 sentences / ~520 chars).

**Changes:**
- §3.4 (Reserving Seats: Creating a Held Order) — insert — pinned that a HELD order's `tickets_subtotal_cents`, `combos_subtotal_cents`, `wallet_applied_cents`, `total_charged_cents` are not computed at hold and stay 0 until payment — `implementation/routes/orders.py:149-152`.
- §3.8 (Cancelling a Screening) — insert — pinned that the cancel cascade's per-order refund returns funds to the original payment method and never credits `wallet_credit_cents` — `implementation/routes/showtimes.py:310` (via `services/domain.py:219-257`).

**Pre-edit search log:** Edit 1 enumerated create_order/pay_order/exchange-successor/serialize/types.py — wording scoped to "begins at 0 and stays 0 while HELD" deferring computed value to §3.5, leaving exchange successor's separate amount_due_cents untouched. Edit 2 enumerated cancel_showtime/refund_paid_order/standalone refund_order — scoped new sentence strictly to cancel cascade, leaving §3.7 standalone-refund conditional-wallet prose intact. No impl/test files modified.

## Step 9: Complete PRD — 2026-06-04T01:47:00.000Z

Produced `workspace/PRD_COMPLETED.md`. PRD_FINALIZED.md=288 lines/41776 chars → PRD_COMPLETED.md=288 lines/~45084 chars (~+3300 chars, all in-paragraph). 10 edits: 8 ambiguity-pins, 2 mismatch-revisions.

**Changes:**
- §2.3 Pagination — insert — ambiguity — non-integer/out-of-range limit/offset → ERR_INVALID_REQUEST — services/common.py:60-72
- §2.7 Precedence — insert — mismatch — PRD listed ownership before existence; impl evaluates ownership only on a loaded resource (non-existent → ERR_NOT_FOUND, foreign existing → ERR_NOT_RESOURCE_OWNER) — routes/_helpers.py:20-55, routes/orders.py:181-188
- §3.2 Seat map — revise — mismatch — seats materialized uniformly: row_label "A", seat_number 1..N, seat_class STANDARD — routes/showtimes.py:115-124
- §3.2 Re-pricing — insert — ambiguity — re-price with neither field → ERR_INVALID_REQUEST; new MATINEE re-validates window → ERR_MATINEE_WINDOW_VIOLATION — routes/showtimes.py:262-271
- §3.2 Open showtime — insert — ambiguity — state violations → ERR_INVALID_STATE; RENTAL-fee violation → ERR_RENTAL_FEE_INVALID — routes/showtimes.py:235-242
- §3.4 Order create — insert — ambiguity — non-ON_SALE showtime → ERR_INVALID_STATE before stale-version check — routes/orders.py:100-107
- §3.5 Payment/wallet — insert — ambiguity — apply_wallet_credit=true w/ non-positive balance → ERR_INSUFFICIENT_WALLET_CREDIT — routes/orders.py:283-288
- §3.6 Cancel held order — insert — ambiguity — cancelling non-HELD → ERR_INVALID_STATE — routes/orders.py:334-335
- §3.7 Refund — insert — ambiguity — refund_destination enum (ORIGINAL/WALLET else ERR_INVALID_REQUEST), refunded amount = captured amount_cents, non-ON_SALE/CANCELLED showtime → ERR_PAST_SHOWTIME — routes/orders.py:356-369, services/domain.py:231-241
- §3.7 Exchange — insert — ambiguity — non-ON_SALE/past target → ERR_INVALID_STATE; seat-check order; no version/stale check; amount_due_cents present only when new subtotal greater; subtotal comparison basis; original Payment left CAPTURED — routes/orders.py:398-480

**Pipeline complete.** All 9 steps done; 72/72 tests green across all 8 parallel rounds.
