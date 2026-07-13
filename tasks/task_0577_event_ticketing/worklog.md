# Worklog — task_0577_event_ticketing

## Step 1: Create task directory — 2026-07-09T00:00:00.000Z

Created `tasks/task_0577_event_ticketing/` and `tasks/task_0577_event_ticketing/workspace/` (index pre-assigned by user; no index scan performed).

## Step 2: Generate scaffold (Expert difficulty) — 2026-07-09T21:36:00.000Z

All three artifacts are written, parse cleanly, and pass `scaffold_lint.py` with `VERDICT: clean lint`. I generated the scaffold fresh from the scenario and the skill spec only — no sibling task under `tasks/` was read.

## Summary

Task: **577. Live-Event Primary Ticketing & Box Office** — designed at **Expert** difficulty.

Files written to `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0577_event_ticketing/`:
- `SCAFFOLD.yaml` (§1.0–§1.7, no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

Counts:
- **Entities:** 11 (Buyer, Event, PriceLevel, Seat, QueueToken, Hold, Order, Ticket, TicketTransfer, RefundRequest, Settlement)
- **State machines:** 8 (+2 concurrency_rules OCC on Event/Order)
- **Calculations:** 7 (2 dual-variant: dynamic seat pricing, settlement gross-vs-net)
- **Validations:** 12 (priority-ordered)
- **Endpoints:** 39
- **Errors:** 30
- **Roles:** 4 (Buyer entity_backed; BoxOffice, Promoter, GateScanner opaque)
- **§1.8 difficulty instances:** 18 (9 rules × 2)
- **§1.9 corner instances:** 47 total (31 active test recipes + 16 `excluded_because` stubs)

Design profile: quota/allocation primary archetype blended with a pricing engine, flat topology, parallel + cyclic state-machine shapes, layers = optimistic_concurrency + cascading_side_effects + dual_variant_calculation + rate_threshold_triggers. All nine Difficulty Rules are grounded in declared elements (e.g., dual-variant pricing on Seat/Ticket vs Settlement; per-seat-then-sum fee rounding vs tiered/platinum/clamp pricing; Ticket parallel dimensions vs Event ONSALE↔POSTPONED cycle; event-cancel depth-3 cascade vs pay depth-2 cascade; seat-count vs money conservation invariants).

Notes: The endpoint count (39) runs above the Expert 20–32 guideline because the flat, FK-heavy topology requires ~18 read/reverse-reachability GETs across 11 entities; the mutating/business surface itself is ~21. The lint's check (f) requires sub-resource reverse-reach GETs to use a literal `{id}` parent segment, which I applied to the 7 sub-resource list endpoints. I also made `ERR_CAPACITY_EXCEEDED` a per-hold seat limit (MAX_SEATS_PER_HOLD=2) and dropped an untriggerable `ERR_SETTLEMENT_NOT_FOUND` so every error is reachable.

## Step 3: Copy shared files — 2026-07-09T21:40:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0577_event_ticketing/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-09T21:47:00.000Z

All three contracts pass. The PRD is complete.

## Summary

Generated `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0577_event_ticketing/workspace/PRD.md` — an Expert-difficulty PRD for a live-event primary ticketing / box-office system (Ticketmaster-style), 265 lines.

**Structure**
- §1 Introduction — 2 paragraphs framing scarce inventory, dynamic pricing, and cent-exact settlement.
- §2 Global Specifications — 9 subsections: 2.1 RBAC (all four roles with `identity` translated to prose), 2.2 Response Structure (verbatim fixed block), 2.3 Pagination, 2.4 Common Properties & Versioning, 2.5 Logical Clock & Temporal Semantics, 2.6 Money/Precision/Rounding (per-seat-then-sum and round-before-clamp pinned), 2.7 OCC (both `expected_event_version` / `expected_order_version` guards), 2.8 Inventory Consistency & Cascades, 2.9 Reference Resolution & 12-step Validation Ordering.
- §3 Business Logic — 7 lifecycle subsections: event setup, presale/queue/admission, holds & dynamic pricing, ordering/payment/ticket issuance, fulfillment/gate-scan/transfers, refunds/credit/cancellation cascades, completion & settlement.
- §4 Endpoint table (4 columns, 39 endpoints) and §5 Error table (2 columns, 30 codes).

**Coverage audit result — all PASS**
- Contract 1 (Field-Name Coverage): 73/73 required identifiers present in backticks, 0 missing (all `entities[].fields`, request-body inputs, query/path params including `to_iso8601`, `expected_event_version`, `expected_order_version`, `target_status`, `new_event_datetime`, `token_id`, `refund_id`, `transfer_id`).
- Contract 2 (Rule Coverage): both OCC rejection rules, all state-machine transitions/cascades (event CANCEL/POSTPONE/COMPLETE, hold→converted, order pay/refund), all six calculations (dynamic tiered pricing with platinum floor and min/max clamp, per-seat service fee, refund amount, refund balance threshold, inventory counts, buyer credit ledger, gross/net settlement variants), validation priority ordering, and every enum value expressed in precise prose.
- Contract 3 (§3 Path Purity): 344 backtick tokens scanned in §3, 0 path/method/method+path leaks — endpoints referenced via state-transition and role+verb framing only.
- All 30 error IDs appear in §2/§3 narrative (not just the §5 table), including the 10 entity-specific not-found codes added to §2.9.

The two withheld design files were not opened.

## Step 5: Generate Unit Tests — 2026-07-09T20:25:21.000Z

Test generation is complete. All infrastructure compiles, 64 tests collect cleanly, every citation is PRD-verbatim (0 misses), and every test carries exactly one `Design:` tag resolving to a real design-index instance.

## Summary

**Files written (16 total)**

`test_helpers/` (Stage 1, 9 files): `__init__.py`, `types.py` (all entity TypedDicts + status/role enums), `api_client.py` (one method per PRD §4 endpoint), `api_errors.py` (30 error IDs + HTTP-status map registered with the framework), `assertions.py` (per-entity assertions + seat-conservation invariant), `factories.py` (input-field payload factories), `constants.py` (pricing tiers, seat cap, default clock), `test_users.py` (opaque role headers + entity-backed `make_buyer_headers`), `fixtures.py` (composite setup: `setup_onsale_event`, `setup_presale_event`, `setup_paid_order`, `setup_admitted_buyer_on_onsale_event`, plus building blocks with identity threading).

`test_suite/` (Stage 2, 7 files): `conftest.py` + `test_01_events_and_seatmap.py` (11), `test_02_buyers_and_queue.py` (7), `test_03_holds_and_pricing.py` (18), `test_04_orders_payment_tickets.py` (13), `test_05_transfers_and_refunds.py` (10), `test_06_settlement_and_cancellation.py` (5).

**Test count: 64** (34 difficulty + 30 corner).

**Coverage audit**

- **Difficulty (§1.8, queue A): 17 of 18 instances translated** (2 tests each = 34). Skipped 1:
  - `cross_entity_state_dependency/scan_gated_by_event_status` — asserts `ERR_INVALID_STATE` for scanning while the event is not ONSALE, but PRD names no error for that trigger. §2.9's `ERR_INVALID_STATE` clause is about the *target resource's* state (the ticket, which is legal here), not a different entity's (the event), so the error is not uniquely derivable (a faithful reader could return `ERR_EVENT_NOT_ON_SALE` or omit the gate). Gap left per the PRD-first filter.

- **Corner (§1.9, queue B): 30 of 31 non-stub instances translated** (1 test each). Skipped 1:
  - `validations/refund_exceeds_balance_returns_refund_exceeds_balance` — the recipe creates a *second* refund request against an already-fully-`REFUNDED` order and expects `ERR_REFUND_EXCEEDS_BALANCE` at **approve** time. PRD only permits refund creation against `PAID`/`PARTIALLY_REFUNDED` orders and runs the state check (§2.9 step 5, `ERR_INVALID_STATE`, higher priority) plus the balance check *at creation* — so the recipe's approve-time outcome is not uniquely derivable. Gap left.

- **16 `excluded_because` stubs**: correctly not translated; all 16 `difficulty_instance` cross-references verified to resolve to real §1.8 instances.

**Verification performed**: package imports against the framework; `pytest --collect-only` yields 64 tests; a programmatic checker confirms every quoted docstring fragment is a whitespace-normalized literal substring of `PRD.md` (backticks preserved) — 0 misses; every test function has exactly one `Design:` tag and none are untagged.

## Step 6: Generate Implementation — 2026-07-09T20:25:21.000Z

Implementation complete and verified end-to-end.

## Files written
- `workspace/implementation/start.sh` — bash launcher, reads `$PORT` (default 10000), binds `0.0.0.0`, foreground `exec`, guards `pip install` on a `import flask` probe.
- `workspace/implementation/requirements.txt` — `Flask>=2.2,<4`.
- `workspace/implementation/app.py` — single-file Flask app, in-memory dicts only, empty store on boot (no seeding), global request lock for consistency, logical clock defaulting to `2026-05-01T00:00:00Z`.

## Endpoints implemented
All 39 routes from the PRD/scaffold table: clock; buyers (create/get/queue-tokens/transfers); events (create/get/status/price-levels×2/seats/queue-tokens×2/holds/sweep-holds/settlement finalize+read); seats (get/list); queue-token admit; holds (get/list/release); orders (create/get/list/pay/refund-requests create+list); refund approve/reject; tickets (get/list/transfers/deliver/scan); transfers (create/accept/decline). Plus a no-auth `/healthz`.

Modeled: the fixed `meta`/`response_type`/`data` envelope with `limit`/`offset`/`total_count`/`has_more` pagination; `X-User-ID`/`X-User-Role` auth with the 4-role RBAC matrix; the two OCC guards (`expected_event_version`, `expected_order_version` → `ERR_STALE_VERSION`); parallel ticket dimensions (status × delivery × scan); Event lifecycle incl. POSTPONED/CANCELED/COMPLETED cascades; dynamic tiered+platinum+clamp pricing with `Decimal`/`ROUND_HALF_UP`; per-seat-then-sum service fee; refund balance/credit ledger; gross vs net settlement variants; the priority-ordered validation chain and full error catalog.

Verified via two smoke tests: happy path (fees 3400, settlement gross 20000 / net 10000 / fees 3400 / refunds 10000, credit 10000) and edge cases (presale exhaustion, OCC stale, scan/transfer state guards, full cancel cascade).

## PRD ambiguities and how I resolved them
1. **Buyer ownership on reads vs mutations.** PRD §2.1 ties ownership explicitly to "mutate the resource," while §2.9 phrases it generally. I enforced ownership only on Buyer *mutations* (pay, release, order-create, refund-create, transfer create/accept/decline, hold/queue buyer_id==X-User-ID); GET endpoints allow any authorized role. Specific §2.1 language wins over the §2.9 summary.
2. **Transition-precondition failures' error code.** No dedicated error exists for "price level exists / seat exists / presale_code set / datetime constraints." PRD §3.7 explicitly maps the COMPLETED-too-early precondition to `ERR_INVALID_STATE`, so I used `ERR_INVALID_STATE` for all failed transition preconditions (missing `new_event_datetime` for postpone is `ERR_VALIDATION` as a malformed body).
3. **Platinum floor when dynamic pricing disabled.** §3.1 says disabled ⇒ "exactly base," but the §3.3/scaffold algorithm applies the platinum floor after the disabled branch. I followed the explicit algorithm (platinum floor still applies); read §3.1's "regardless of how the show is selling" as referring to pct-based tiers, not the static platinum floor.
4. **Buyer version bump on CREDIT refund.** `credit_balance_cents` is computed, but the state machine lists it as a side effect and §2.8 says every affected resource bumps version/updated_at. I bump the buyer's version/updated_at on a completed CREDIT refund (not ORIGINAL).
5. **Admit / scan when event not ONSALE, and refund approval on non-VALID tickets** — no dedicated codes; used `ERR_INVALID_STATE`.
6. **Pagination out-of-range** — PRD gives min/max but no error, so I clamp (limit→[1,100], offset→≥0); non-integer values → `ERR_VALIDATION`.
7. **Token consumption** — §3.2 says "the order consumes the token," so order creation expires the buyer's ADMITTED token for that event.

One expected priority interaction to note: because seat-availability (priority 10) precedes the per-hold seat cap (priority 11), a >2-seat hold where some seats are already HELD returns `ERR_SEAT_UNAVAILABLE`, not `ERR_CAPACITY_EXCEEDED` — this follows the declared validation ordering.

## Step 7: Run Tests and Iterate — 2026-07-09T20:31:21.000Z

All 8 rounds pass 64/64. Clean sweep achieved.

## Summary

**Iterations run:** 2 (1 diagnostic baseline sweep + 1 fix sweep).

**Root cause:** Exactly one test failed, consistently across all 8 rounds (not flaky): `test_event_postpone_from_onsale_updates_datetime`. The implementation round-tripped the client-supplied `event_datetime` through its `iso()` serializer, which forcibly appends `.000` (3 fractional digits). The test sent `new_event_datetime = "2026-09-01T19:00:00Z"` and asserted the stored `event_datetime` equaled that exact string.

**Diagnostic verdict:** PRD-covered and uniquely determined — kept the test.
- Coverage: PRD §3.1 states verbatim "it sets the event's `event_datetime` to that value."
- Unique derivability: `event_datetime` is client-supplied business data, not a server-minted timestamp. PRD §2.4 scopes the "three fractional digits" convention explicitly to `created_at`/`updated_at`, and §2.5 to timestamps "the server stamps." `event_datetime` is neither, so "sets ... to that value" means echo the supplied value verbatim. The test is faithful.

**Fixes applied to `implementation/` (`workspace/implementation/app.py`):**
- Event creation (`create_event`): store the raw client string as `event_datetime_str` alongside the parsed datetime (parsed form retained for the `> clock` comparisons and the COMPLETED gate).
- Postpone side-effect block: set `event["event_datetime_str"] = body["new_event_datetime"]` when applying the new datetime.
- `ser_event`: emit `event_datetime_str` (falling back to `iso()` for safety), so the response echoes the supplied value rather than a re-normalized one.

**Tests deleted:** none.
**Fixes to `test_helpers/`:** none.

Final state: 8/8 parallel rounds green at 64/64.

## Step 8: Finalize PRD — 2026-07-09T20:34:00.000Z

Done. One edit applied.

## Summary

**Line counts:** PRD.md = 264 lines; PRD_FINALIZED.md = 264 lines (edit was inline within an existing paragraph; 0-line delta, ~0%).

**Changes (1):**
- §2.5 (Logical Clock and Temporal Semantics) — insert — appended a sentence pinning that `event_datetime` is echoed back verbatim as the exact client-supplied string, not re-serialized to the three-fractional-digit form — traces to `app.py:453` (`ser_event` emitting `event_datetime_str`), set at `app.py:719` (create) and `app.py:771` (postpone).

**Why this edit / traceability to `<step_7_diff>`:** Step 7 changed the impl so `event_datetime` round-trips the raw client string rather than passing through `iso()` (which forces `.000`). The PRD was silent on `event_datetime`'s output format: §2.4 scopes the three-fractional-digit convention to `created_at`/`updated_at`, and §2.5 to timestamps "the server stamps." `event_datetime` is client-supplied business data, neither of those. A fresh implementer could reasonably normalize it to `.000` on output and diverge. The pin closes that silence.

**Pre-edit search log:**
- (a) Subject: the response representation / serialization of `event_datetime`.
- (b) Enumerated & read impl paths: `create_event` (app.py:697-719, stores raw `event_datetime_str`); `event_status` POSTPONED side-effect (app.py:769-771, sets `event_datetime_str` to raw `new_event_datetime`); `ser_event` (app.py:453, emits `event_datetime_str` with an `iso()` fallback that never fires because both create and postpone always set the string); and the three temporal comparisons using the *parsed* datetime (app.py:709 create gate, 762 postpone gate, 765 COMPLETED gate).
- (c) Wording adjustment: scoped the claim to "the `event_datetime` returned in responses" so it says nothing about the internal parsed value used for the `> clock` / COMPLETED comparisons — avoiding a false universal that would contradict the comparison paths. Also chose "the exact string the client supplied" (not "the UTC-normalized value") because the impl echoes the literal input bytes, including any non-UTC offset, without normalization.

No other `<step_7_diff>` items existed (no test deletions, no test_helpers/ fixes). No other PRD sections required changes.

## Step 9: Complete PRD — 2026-07-09T20:42:00.000Z

Done. `PRD_COMPLETED.md` written as a minimal in-paragraph patch over `PRD_FINALIZED.md`.

## Summary

**Line/char counts:** PRD_FINALIZED.md = 264 lines / 41,369 chars → PRD_COMPLETED.md = 264 lines / 42,536 chars (+1,167 chars, 0 lines — all edits are in-paragraph, no new sections/paragraphs).

**Counts:** 7 changes total — 5 ambiguity-pins, 2 mismatch-revisions.

**Changes (one per bullet):**

- §2.3 Pagination — insert — ambiguity — list sort ties (frequent under the shared logical clock) are broken by ascending creation order — `app.py:292`
- §3.1 Event creation — insert — ambiguity — `promoter_id` is a required body field and must equal `X-User-ID` for a `Promoter` (`ERR_UNAUTHORIZED`); past `event_datetime` yields `ERR_VALIDATION` — `app.py:694,707,709`
- §3.1 Price levels / dynamic pricing — revise — mismatch — corrected the blanket "dynamic disabled ⇒ prices at base" claim: a platinum level still gets the 2.00× floor even with dynamic pricing disabled (impl applies platinum floor unconditionally) — `app.py:343-354`
- §3.1 Postpone — insert — ambiguity — missing `new_event_datetime` → `ERR_VALIDATION`; a non-future one → `ERR_INVALID_STATE` (note: differs from event-create's `ERR_VALIDATION`) — `app.py:759-763`
- §3.2 Buyer registration — revise — mismatch — email uniqueness is described as required in the source but is not enforced by impl; softened to "uniqueness not enforced" — `app.py:648-657`
- §3.5 Gate scan — insert — ambiguity — scanning a non-`VALID` ticket, or while the event is not `ONSALE`, returns `ERR_INVALID_STATE` (not `ERR_EVENT_NOT_ON_SALE`) — `app.py:1491,1499`
- §3.7 Settlement — insert — ambiguity — double-finalize → `ERR_INVALID_STATE`; `GET .../settlement` returns an **array** (single element, or empty before completion), and `PENDING` figures are recomputed live on each read until finalization freezes them — `app.py:600-609,1085-1099`

**Considered but deliberately not changed** (already pinned by PRD or defensibly generic): the many `ERR_INVALID_STATE` illegal-transition cases (deliver/release/admit/order-from-hold/approve-reject) are already generically covered by §2.9 rule (5); half-open temporal boundaries, per-seat fee rounding, dynamic-pricing tiers/clamp, cascade side-effects, credit-balance/refunded-amount derivations, and OCC all matched impl. I left the refund/transfer ownership-vs-body-FK-existence micro-ordering alone — it's an edge-only deviation from §2.9 and defensible as "the target must be resolved before ownership can be evaluated."
