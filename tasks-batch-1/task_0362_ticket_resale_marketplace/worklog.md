# Worklog — task_0362_ticket_resale_marketplace

## Step 1: Create Task Directory — 2026-06-15T00:00:00.000Z

Created `tasks/task_0362_ticket_resale_marketplace/` and `tasks/task_0362_ticket_resale_marketplace/workspace/`. Directory was pre-allocated for this task; no index auto-scan performed.

## Step 2: Generate Scaffold (Expert difficulty) — 2026-06-15T00:00:00.000Z

All three artifacts complete, self-consistent, and pass `scaffold_lint.py` cleanly (627 calls scanned across §1.8+§1.9, all FKs reverse-reachable). Files: SCAFFOLD.yaml (1710 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1674 lines), SCAFFOLD_CORNER_DESIGN.yaml (1833 lines).

Complexity profile: Quota/allocation (seat-pool inventory) × Pricing engine, flat topology, parallel state shape, peer-role RBAC, immediate consistency. Layers: OCC, cascading side-effects, dual-variant calc, derived-field reconciliation, idempotency.

Scaffold contents:
- 13 entities: Venue, Section, Event, Seller, Buyer, Listing (seat-pool), Seat (polymorphic-flaggable), Order, Transfer, Payout, GuaranteeClaim, EventCredit, FraudFlag.
- 9 state-machine axes / 8 entities — including Order's two parallel dimensions (payment_status × delivery_status), a cyclic GuaranteeClaim negotiation (REPLACEMENT_OFFERED↔INVESTIGATING with round counter), and a 4-hop event-cancel cascade.
- 10 calculations — dynamic scarcity pricing (scarcity→floor→cap ordering), dual-variant buyer charge (estimate vs final), tiered seller fee by trust tier, payout clawback, dual-variant guarantee settlement, loyalty-bonus event credit, last-minute transfer-deadline interval math, lifecycle rollup, fraud severity, seat reconciliation.
- 11 validations (priority 0–10), 2 OCC concurrency rules (sale-create stale-listing 412; payout-pay stale-payout 412), 37 errors, 4 roles (Seller/Buyer entity-backed; PlatformAdmin/TrustSafety opaque), 62 endpoints (incl. 2 /_clock test-driving).

Difficulty design: 18 instances = 9 rule_ids × 2, every formula-derived assert pre-computed to literals.
Corner design: 39 instances across all 9 taxonomy sections (33 executable recipes + 6 excluded_because stubs).

## Step 3: Copy Shared Files — 2026-06-15T00:00:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-15T00:00:00.000Z

Generated `workspace/PRD.md` (319 lines) from the Expert-difficulty scaffold (13 entities, 8 state machines incl. Order's parallel payment/delivery axes, 9 calculations, 11 priority-ordered validations, 2 OCC rules, 63 endpoints, 37 error codes, 4 roles).

Sections: §1 Introduction (secondary-market guarantor role, inventory/commercial/transaction/protection layers, simulated clock); §2 Global Specs (RBAC, §2.2 envelope verbatim, pagination, common props/versioning, seat-pool reconciliation, monetary precision, nested-reference order, validation priority ladder, OCC, simulated clock); §3 Business Logic (catalog setup, sellers/buyers/trust-tier, listing+pricing, reserve/charge, escrow/commission/payout, delivery/transfers/last-minute, buyer guarantee, fraud detection, event cancellation/credits); §4 endpoint table; §5 error table.

Hard contracts PASS: Field coverage 82/82; Rule coverage (validation ladder, 2 OCC, 9 state machines, 9 calcs, 37 errors, side-effect cascades, sibling symmetry) 0 missing; Path-purity §3 (529 tokens, 0 path leaks).

Notable: §2.8 full priority-0..10 ladder narrative; OCC framed purely as stale-version (expected_listing_version on POST /orders + guarantee accept-offer; expected_payout_version on payout pay); dual-variant calcs (buyer estimate vs final, guarantee protection vs event-issue refund); parallel Order axes with pinned-order lifecycle_state rollup; half-open transfer deadline ("strictly before deadline_at"); floor-truncation for price/fee/credit.

## Step 5: Generate Unit Tests — 2026-06-15T11:42:00.000Z

Generation complete. All audits pass.

## Summary

Generated complete test infrastructure for **task_0362_ticket_resale_marketplace** (Expert difficulty, StubHub-style ticket resale marketplace).

### Files generated

**`test_helpers/`** (Stage 1 — PRD-specific infrastructure):
- `types.py` — 4-role enum, 17 status enums, 13 entity TypedDicts (all `common_fields: true`)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (all PRD §4 endpoints incl. clock controls)
- `api_errors.py` — `ApiErrorId` enum (37 errors) + HTTP-status map registered with the framework
- `assertions.py` — per-entity assertions + seat-pool reconciliation invariant checkers
- `factories.py` — input-field-only payload factories with unique-barcode helper
- `constants.py` — calculation thresholds (fee rates, demand slope, loyalty/bonus, deadline windows, gouge ratio) + canonical-fixture derived figures
- `test_users.py` — opaque PlatformAdmin/TrustSafety shared constants + entity-backed `make_seller_headers`/`make_buyer_headers` per-instance builders (identity threading)
- `fixtures.py` — 5-tier composite helpers (catalog → listings/seats → reserve/charge → charged-order/delivery-failed-with-claim/credit-earning composites)
- `__init__.py` — barrel export

**`test_suite/`** (Stage 2 — 69 tests across 10 files): `conftest.py` + `test_01`–`test_09`.

### Coverage audit (all pass)
- **69 tests = 69 `Design:` tags** (exactly one per test; no untagged/dual-tagged).
- **Queue A (Difficulty):** all **18 instances** (9 rules × 2) covered with **exactly 2 tests each** = 36 tests.
- **Queue B (Corner):** all **33 non-stub instances** covered with **1 test each** = 33 tests.
- **6 `excluded_because:` stubs NOT translated**; every `difficulty_instance` cross-reference verified to resolve to a real difficulty instance.
- **96 verbatim PRD citations** all survive a literal ≥9-word-window grep of `PRD.md` (fixed an initial round of ellipsis-fused/abbreviated quotes to contiguous full sentences).
- No `pytest.mark.skip`/`skipif`/`xfail`; no scaffold/pipeline-vocabulary leakage in emitted code (module docstrings rewritten to PRD-only language; mandated `Design:` tags retained).

### Skipped instances
**None.** The PRD is exhaustively prose-complete: every non-stub difficulty and corner instance has verbatim PRD coverage and unique derivability, so all 51 testable instances were translated. No two-reader ambiguity or silence-pattern gap forced a skip.

### Notes for downstream
- The two OCC anchors (`expected_listing_version` on order-create / accept-offer; `expected_payout_version` on payout-pay) are threaded through fixtures by re-reading `version` before each version-sensitive call.
- The `reservation_expired_temporal_beats_split_rule` and `frozen_state_beats_wallet_fiscal` precedence instances were translated as the asserted single outcome the PRD uniquely determines (the charge endpoint does not re-check split_rule, and `ERR_LISTING_FROZEN` precedes fiscal in PRD §2.8 regardless of which guard catches it) — no precedence assertion beyond what PRD prose pins.

## Step 6: Generate Implementation — 2026-06-15T11:59:00.000Z

(Note: the first Step 6 subagent died on a transient socket-close API error mid-stream after writing a partial tree with no app.py; that partial output was wiped and Step 6 was regenerated fresh from scratch by a new subagent. The summary below is from the successful run.)

The implementation is complete and verified. Here is my summary.

## Summary

Generated a complete Python + Flask implementation for **task_0362_ticket_resale_marketplace** (EXPERT difficulty) at `workspace/implementation/`.

### Files (34 total)
- **Launcher/config**: `start.sh` (guarded `pip install` + `exec python3 app.py`, binds `0.0.0.0:$PORT` default 10000), `requirements.txt` (Flask 3.0.3)
- **Foundation**: `app.py` (blueprint registration + error handlers), `db.py` (in-memory store, starts empty, UUID/version/timestamp helpers), `errors.py` (full error catalog as ApiError), `response.py` (exact `meta`/`response_type`/`data` envelope), `middleware.py` (X-User-ID/X-User-Role auth + ownership), `validate.py` (body-shape validation), `clock.py` (simulated logical clock, ISO-8601 with 3 fractional digits)
- **Routes** (12): venues+sections, events, parties (sellers/buyers), listings, seats, orders, transfers, payouts, claims, credits, fraud, clock_routes — all ~60 endpoints from the PRD table
- **Services** (11): calc, recompute (derived-field reconciliation), lookup, paginate, serialize, seat_ops, order_ops, transfer_ops, claim_ops, event_ops, fraud_ops, sweeps

### Entities (13)
Venue, Section, Event, Seller, Buyer, Listing, Seat, Order, Transfer, Payout, GuaranteeClaim, EventCredit, FraudFlag — with all `system`/`computed` derived fields (seat-pool counts, escrow/wallet ledgers, active_listing_count, capacity, etc.).

### State machines (8)
Event (6-state incl. cancel/complete cascades), Listing (DRAFT→ACTIVE↔SOLD_OUT, FROZEN), Order payment axis × delivery axis (parallel dimensions) with derived `lifecycle_state` rollup, Transfer, Payout, GuaranteeClaim (cyclic negotiation back-edge), EventCredit, FraudFlag.

### Calculations (9)
effective_listing_price (FIXED + DYNAMIC scarcity, scarcity→floor→cap order), buyer_charge (estimate vs final dual-variant, 12% fee), seller_fee (trust-tier tiers 15/12/10/20%), payout_clawback, guarantee_settlement (protection re-issues credit vs event-issue), event_credit_amount (110% loyalty bonus at lifetime≥3), transfer_deadline (1440-min standard vs 30-min last-minute compression), order_lifecycle_rollup, fraud_severity (gouge band at face×2.5). All money in integer cents with floor truncation.

### Notable design decisions
- **Validation priority** follows PRD §2.8 exactly: body-shape(400)→auth(401/403)→not-found(404)→referential(422)→state(409)→safety→temporal→inventory/idempotency(priority 8)→fiscal(402)→OCC(412 last). Verified idempotency-replay short-circuits as a success but idempotency-*conflict* fires at priority 8.
- **OCC**: `expected_listing_version` on POST /orders and accept-offer; `expected_payout_version` on payout pay — both evaluated last.
- **Cascades**: event-cancel 4-hop (DELISTED→CREDITED→CLAWED_BACK→VOID), event-complete 2-hop (DELISTED + ESCROWED→RELEASABLE), guarantee refund/replacement, each child gets its own version bump + timestamp.
- **Clock sweeps**: reservation expiry, transfer EXPIRED, ON_SALE→LAST_MINUTE auto-crossing fired on `/_clock/set` and `/_clock/advance`. Credit-expiry sweep is wired but inert because the PRD names no concrete validity window (documented in `sweeps.py`).
- **No seeding** — store empty on every boot, confirmed via fresh-server inspection (0 entities).

### Verification
7 end-to-end test batches passed covering: full purchase lifecycle + payout escrow/release, dynamic pricing, split rules, fraud freeze/unfreeze, event-cancel cascade, guarantee refund + replacement, time sweeps, last-minute compressed deadline, loyalty bonus, auth/RBAC/envelope/pagination, referential mismatch, idempotency replay/conflict, delivery-before-payment guards, WHOLE split. All 33 Python files compile; `start.sh` boots and serves within ~4s. (Note: one earlier "duplicate barcode on fresh server" was a leftover-process artifact in my test loop, not a code bug — confirmed once the orphaned process was killed.)

## Step 7: Run Tests and Iterate — 2026-06-15T12:14:00.000Z

All 8 parallel rounds pass cleanly. Done.

## Summary

**Iterations run:** 2 (1 diagnostic sweep that surfaced 6 stable failures, 1 confirming sweep — all 8 rounds green, 67/67).

The 6 failures were identical across all 8 rounds (no flakiness; the initial "63/69" was a stable 6-test failure set).

**Tests deleted (2):**
- `test_cancel_a_cancelled_event_returns_already_terminal` (test_02_state_lifecycle.py) — **ENUM-MEMBERSHIP-ONLY / unique-derivability collapse**. Asserted re-cancelling a `CANCELLED` event yields `ERR_ALREADY_TERMINAL`, but the PRD names that error only in the §2.8 error list and the §5 catalogue — no prose names its write pathway. Worse, §3.1 verbatim directs the opposite: "Any attempt to drive the event status from a state the transition does not permit is rejected with `ERR_INVALID_STATE`." A faithful reader produces `ERR_INVALID_STATE`. Driven by scaffold rule: state_machines/cancel_a_cancelled_event terminal-guard.
- `test_reservation_expired_temporal_beats_split_rule_constraint` (test_08_validation_precedence.py) — **ERROR PRECEDENCE SILENCE**. Advanced the clock past `reservation_expires_at` then charged, expecting `ERR_RESERVATION_EXPIRED`. But PRD §2.10 mandates the clock-advance sweep auto-refunds the expired reservation (the companion passing test `test_reservation_expiry_on_clock_advance_releases_seats` confirms this), so the order is `REFUNDED` before charge and the faithful outcome is `ERR_INVALID_STATE`. `ERR_RESERVATION_EXPIRED` is unreachable in any §2.10-faithful implementation, so the relaxation criterion ("A is possible") fails → delete. Driven by scaffold rule: priority_pair_validation_conflict/reservation_expired_temporal.

**Fixes applied to `test_suite/` (2):**
- `test_09_boundaries_and_overlap.py` — `test_distinct_barcode_tokens_both_addable`: changed `validate_success(api.create_seat(...))` to pass `expected_status=201`. Seat creation is a new stand-alone resource → 201 per PRD §4; the default 200 made it fail on a correct 201 response.
- `test_03_calculations.py` — `test_dynamic_price_clamped_to_cap_when_demand_exceeds`: the fixture built a DYNAMIC listing with `ask_price_cents=40000 > cap 30000`, which PRD §3.3 requires be rejected at creation (the setup itself 402'd). Rewrote it to a PRD-valid listing (ask 30000 == cap, floor 10000, 4 seats) and sell 2 to drive scarcity (×1.25 → raw 37500), so the cap clamp genuinely binds → effective 30000. The cited cap-clamp assertion is unchanged and still PRD-faithful.

**Fixes applied to `implementation/` (2):**
- `services/sweeps.py` — `_sweep_transfers`: changed the deadline test from `now >= deadline` to `now > deadline`. "deadline_at has passed" (PRD §2.10/§3.6) means strictly past; at exactly `deadline_at` the transfer must stay `SENT` (acceptance at that instant is separately rejected by the half-open `< deadline_at` accept rule, yielding `ERR_TRANSFER_DEADLINE_PASSED` instead of `ERR_INVALID_STATE` from a premature sweep-expiry).
- `services/order_ops.py` — `charge`: removed the `applied_credit > wallet → ERR_INSUFFICIENT_WALLET_CREDIT` precondition. PRD §3.4 says the applied credit is *recomputed* (clamped to current wallet) at charge time and "the final total can exceed the estimate" — a sentence that is only observable if a shrunken wallet raises the final rather than rejecting the charge. The `buyer_charge` calc already clamps `applied = min(elected, gross, wallet)`, so the recompute now correctly drops the credit and charges the full gross. The reservation-time wallet check (the only PRD-named `ERR_INSUFFICIENT_WALLET_CREDIT` pathway, in `routes/orders.py`) is untouched.

Final state: 8/8 parallel rounds pass, 67/67 tests each, stable across the sweep.

(Orchestrator note: Step 7's loop deletes `results.*.json` at the start of each iteration, so the final passing set was not left on disk. The orchestrator re-ran the 8-round sweep once as independent verification — see the post-Step-7 confirmation below.)

## Step 7 Verification (orchestrator) — 2026-06-15T12:15:00.000Z

Orchestrator re-ran the full 8-round parallel sweep (`prd-bench-local-run --isolation per-test-server`) to confirm Step 7's exit claim and regenerate the `results.{1..8}.json` artifacts. Result: **all 8 rounds passed=67 failed=0 total=67**. Stable, no flakiness. Artifacts persisted at `workspace/implementation/results.{1..8}.json`.

## Step 8: Finalize PRD — 2026-06-15T12:19:00.000Z

Both edits were inline within existing paragraphs (no new lines added). Line count unchanged; word count +70 (+0.96%).

## Summary

**Line counts:** PRD.md 319 lines → PRD_FINALIZED.md 319 lines (0% line delta; both edits were inline within existing paragraphs). Word count 7306 → 7376 (+70 words, +0.96%).

**Changes (1 bullet per change):**
- §3.6 — insert — Pinned the transfer-expiry sweep boundary: "`deadline_at` has passed" now explicitly means the clock is **strictly after** `deadline_at`, so a transfer at exactly `deadline_at` is NOT swept (while accept/recall at that same instant ARE rejected by the separate half-open `< deadline_at` rule) — `services/sweeps.py:45` (`now > deadline`).
- §3.4 — revise — Removed the contradictory charge precondition "and that any `applied_credit_cents` is still within the buyer's `wallet_credit_cents`" and added a sentence clarifying that a shrunken wallet never rejects the charge; the applied credit is recomputed/clamped instead — `services/order_ops.py:59-87` (charge has no wallet-credit rejection; `calc.buyer_charge` clamps `applied = min(elected, gross, wallet)` at `services/calc.py:69`).

**Per-edit pre-edit search log:**

Edit 1 (§3.6 transfer-sweep boundary):
- (a) Subject: the `deadline_at` comparison boundary in the transfer-expiry sweep.
- (b) Enumerated/read impl paths: `services/sweeps.py:_sweep_transfers` (line 45, `now > deadline` → EXPIRED); `services/transfer_ops.accept` (line 66, `now >= deadline_at` → reject, separate half-open rule); `services/transfer_ops.recall` (line 93, `now >= deadline_at` → reject); `services/sweeps.py:_sweep_reservations` (line 31, `now >= expires` — DIFFERENT boundary for reservations); grep `deadline` across the impl confirmed no other callsite.
- (c) Adjustment: scoped the wording strictly to the SWEEP only ("strictly after `deadline_at` ... is not swept"), parenthetically noting accept/recall are still rejected at that instant so I don't contradict §3.6's existing half-open accept/recall prose, and deliberately did NOT generalize "has passed" — leaving the reservation sweep's `>=` boundary (which shares the "has passed" phrasing in §2.10) untouched.

Edit 2 (§3.4 charge wallet precondition):
- (a) Subject: the wallet-credit constraint at charge time and the `ERR_INSUFFICIENT_WALLET_CREDIT` pathway.
- (b) Enumerated/read impl paths: `services/order_ops.charge` (lines 59-111 — checks PENDING/FROZEN/ACTIVE-SOLD_OUT/reservation-expiry only; no wallet rejection; recomputes via `calc.buyer_charge`); `services/calc.buyer_charge` (line 57-73, `applied = min(elected_credit, gross, wallet_at_eval)`); `routes/orders.py:create_order` (lines 89-91, the reservation-time `applied_credit > wallet → ERR_INSUFFICIENT_WALLET_CREDIT` check — the ONLY place that error is raised, confirmed intact). Verified `ERR_INSUFFICIENT_WALLET_CREDIT` appears nowhere in the charge path.
- (c) Adjustment: removed only the charge-time precondition clause and left the reservation-time `ERR_INSUFFICIENT_WALLET_CREDIT` sentence (§3.4 reservation paragraph) and §2.8/§5 error catalogue references untouched, so the error's sole surviving pathway (reservation) remains correctly described.

**Items requiring NO PRD edit (verified PRD already determines impl behavior; these were test/fixture bugs, not PRD silence/mismatch):**
- `test_cancel_a_cancelled_event_returns_already_terminal` deletion — §3.1 already pins event mis-transitions to `ERR_INVALID_STATE`; impl `event_ops.cancel` raises `ERR_INVALID_STATE`; `ERR_ALREADY_TERMINAL` is defined but never raised anywhere in the impl.
- `test_reservation_expired_temporal_beats_split_rule_constraint` deletion — §2.10 auto-refund sweep + §3.4 charge ordering already determine `ERR_INVALID_STATE`; the test premise was unreachable.
- Seat-creation 201 fix — §4 already mandates 201 for new stand-alone resources.
- Dynamic price-cap-clamp fixture fix — §3.3 already mandates rejection of `ask_price_cents > cap` at creation (`routes/listings.py:53-54`); the original fixture was simply invalid.

## Step 9: Complete PRD — 2026-06-15T12:29:00.000Z

Paragraph ordering is correct. All edits are coherent. The implementation walk is complete and every notable behavior is now pinned.

## Summary

**Source vs completed:** `PRD_FINALIZED.md` (319 lines, 51,449 chars) → `PRD_COMPLETED.md` (323 lines, 56,015 chars). Delta: +4 lines, +4,566 chars.

**Change counts:** 11 changes total — 8 ambiguity-pins, 3 mismatch-revisions.

**Per-change log:**

- §2.1 (RBAC) — insert — ambiguity — pinned selective read-ownership: Seller/Buyer self-record + single Payout/EventCredit reads are ownership-checked, but single-resource GETs for venues/sections/events/listings/seats/orders/transfers/claims/flags are not; ownership is enforced on state-changing ops, and payout `pay`/confirm-delivery-window carry no ownership check — `routes/parties.py:40,81`, `routes/payouts.py:21`, `routes/credits.py:20`, `routes/orders.py:142` (no ownership), `routes/transfers.py:69`.
- §2.1 (RBAC) — insert — ambiguity — pinned that `GET /payouts` (Seller) and `GET /event-credits` (Buyer) auto-filter to the caller's own resources; all other list endpoints do not — `routes/payouts.py:37-38`, `routes/credits.py:39-40`.
- §2.3 (Pagination) — revise — ambiguity — pinned that out-of-range `limit` is clamped to [1,100], negative `offset` clamped to 0, and non-integer values rejected with `ERR_INVALID_REQUEST` — `services/paginate.py:28-39`.
- §2.10 (Clock) — revise — ambiguity — pinned clock response shape: current instant returned as `data.current_utc` (ISO 8601, 3 fractional digits) — `routes/clock_routes.py:25,36`.
- §2.10 (Sweeps) — revise — mismatch — removed the auto credit-expiry sweep (impl has none / no validity duration) and pinned that the last-minute sweep fires only for `ON_SALE` events — `services/sweeps.py:9-12,55-66`.
- §3.1 (enter-last-minute) — revise — ambiguity — pinned `ERR_INVALID_STATE` for both wrong-state and clock-not-reached cases — `services/event_ops.py:19-25`.
- §3.1 (complete) — revise — ambiguity — pinned `ERR_INVALID_STATE` for wrong-state or doors-not-reached — `services/event_ops.py:31-35`.
- §3.4 (reservation) — revise — ambiguity — pinned `reservation_expires_at` = current clock + 30 minutes — `services/order_ops.py:8-12`.
- §3.4 (idempotency) — revise — ambiguity — pinned the compared params, the identical-key replay returning the prior order with 201 (no new order/hold/version), and its ordering after FK resolution but before business checks — `routes/orders.py:56-68,82-86`.
- §3.4 (charge credit redemption) — insert — ambiguity — pinned whole-credit (non-fractional) FIFO redemption: final credit consumed in full even on overshoot — `services/order_ops.py:42-56`.
- §3.5 (confirm-delivery-window) — revise — ambiguity — pinned error codes/order: no escrowed payout → `ERR_PAYOUT_NOT_RELEASABLE`, not delivered → `ERR_INVALID_STATE`; acts on all escrowed payouts, returns the order — `routes/orders.py:195-209`.
- §3.7 (refund re-issue) — revise — ambiguity — pinned re-issued credit's `event_id` (from order's listing) and `bonus_applied` false, and that re-issue is skipped when `applied_credit_cents` is 0 — `services/claim_ops.py:169-182`.
- §3.8 (severity) — revise — ambiguity — pinned subject-listing resolution for SEAT/ORDER PRICE_GOUGE subjects and the unresolved-listing fallback (price absent, face 0 → LOW) — `services/fraud_ops.py:8-19,29-36`.
- §3.8 (confirm) — revise — mismatch — pinned that DUPLICATE_BARCODE void requires `subject_type == SEAT`, and freeze applies only when listing status is DRAFT/ACTIVE (other statuses, incl. SOLD_OUT/DELISTED, left unchanged) — `services/fraud_ops.py:83-104`.
- §3.9 (credit lifecycle) — revise — mismatch — replaced the credit-expiry-sweep sentence: `EXPIRED` exists in the model but no sweep auto-expires credits — `services/sweeps.py:9-12`.

(Note: the §2.1 entry covers two distinct inserts and §3.8 covers two; total distinct edits = 11, spanning the 8 ambiguity-pins and 3 mismatch-revisions noted above.) Tests were used only as auxiliary cross-reference (e.g., confirming not-delivered → `ERR_INVALID_STATE`); implementation was the sole authority.
