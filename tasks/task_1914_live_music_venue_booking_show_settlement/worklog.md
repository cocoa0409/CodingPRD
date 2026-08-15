# Worklog — task_1914_live_music_venue_booking_show_settlement

## Step 1: Create Task Directory — 2026-08-15T00:18:00.000Z

Pre-created by pipeline launcher: `tasks/task_1914_live_music_venue_booking_show_settlement/` + `workspace/`. Verified to exist; skipped per instructions.

## Step 3: Copy Shared Files — 2026-08-15T00:19:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1914_live_music_venue_booking_show_settlement/workspace/INSTRUCTION.md`.

## Step 2: Generate Scaffold — 2026-08-15T00:42:00.000Z

Clean lint. All three files written. Summary:

## Summary

**Files written:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1914_live_music_venue_booking_show_settlement/SCAFFOLD.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_1914_live_music_venue_booking_show_settlement/SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_1914_live_music_venue_booking_show_settlement/SCAFFOLD_CORNER_DESIGN.yaml`

**Counts:**
- Entities: **15** (Artist, Show, DateHold, BookingAgent, Offer, Deal, TicketTier, TicketSale, AdvanceChecklist, SupportAct, ExpenseReceipt, AncillaryRevenue, Settlement, WireTransfer, CancellationEvent)
- State machines: **8** (DateHold, Offer, Show, AdvanceChecklist, SupportAct, ExpenseReceipt, Settlement, WireTransfer)
- Calculations: **6** (artist_payout, cancellation_policy, hold_priority_rank, ticket_scaling_tier_advance, versus_threshold_straddle, expense_recoupment_ordering, deposit_wire_timing — 7 actually declared)
- Validations: **20** (priorities 1–20)
- Endpoints: **77**
- Errors: **20**
- Roles: **5** (VenueManager, BookingAgent, Promoter, ProductionManager, Accountant)
- §1.8 instances: **18** (9 rules × 2)
- §1.9 instances: **27** (across entities, state_machines, calculations, validations, endpoints, errors, roles, cross-cutting layers, consistency model)

**Notable design decisions:**
1. **Multi-party negotiation + ledger reconciliation** as blended archetypes; segregation-of-duties role model prevents Promoter from approving their own settlement.
2. **Four OCC concurrency rules** all on Show.version (date-hold confirm, offer accept, settlement submit, on-sale) — captures the hub-and-spoke contention pattern.
3. **VERSUS deal** uses marginal-rate bonus above a strictly-greater threshold — provides Rule 6 boundary check at exact equality.
4. **Expense recoupment with truncation ordering** — when the cap is exceeded, the first cap-crossing receipt is truncated and later ones recoup at 0, creating an order-sensitive computation.
5. **Ticket scaling** rolls up across tiers (cheapest-first by `tier_order` then `created_at`, never `id`); partial fills are rejected atomically.
6. **Cancellation policy** has four branch semantics (ARTIST sliding-scale penalty, VENUE full-guarantee kill, FORCE_MAJEURE deposit refund, LOW_TICKET_SALES with 30% capacity threshold).
7. **Deposit timing** is snapshotted at offer-acceptance (deposit_pct changes to Artist don't retroactively alter outstanding shows).
8. **Logical clock** endpoint `POST /_clock/set_current_utc` with mandatory default `2026-08-01T00:00:00Z` for deterministic time-gated tests.
9. **All DateHold/Offer/TicketSale/WireTransfer FKs** have both single-resource GETs and filtered-list GETs to satisfy reverse-reachability.
10. **`api_prefix: /`** chosen so the lint can derive collection segments for multiple top-level resources (Show, Artist, BookingAgent, Deal, Settlement, etc.) — cleaner than forcing everything under a single root collection.

Lint verdict: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`

## Step 4: Generate PRD — 2026-08-15T00:59:00.000Z

All audits pass. The one flagged token `all_complete=true` is not an enum value — it's the AdvanceChecklist state machine's terminal-state descriptor — and its semantics are expressed in §3.5 ("`all_complete` is true exactly when all six items are true"). The forbidden difficulty-design files were never opened.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1914_live_music_venue_booking_show_settlement/workspace/PRD.md` — 320 lines.

**Section list:**
- §1 Introduction (2 paragraphs)
- §2 Global Specifications: 2.1 RBAC (headers, 5 roles, entity-backed vs opaque identity) · 2.2 API Response Structure (byte-identical to the fixed verbatim block — verified) · 2.3 Pagination · 2.4 Resource Identity and Bookkeeping Metadata (incl. explicit `updated_at`/`version` absence for TicketSale, AncillaryRevenue, CancellationEvent) · 2.5 Integer Cents and Half-Up Rounding · 2.6 OCC on the Show Spine (all 4 versioned writes) · 2.7 The House Clock (2026-08-01T00:00:00Z default, lazy transitions) · 2.8 Validation Order and Error Precedence (full 7-stage pipeline, business rules 7–20 in fixed sequence, with concrete precedence examples) · 2.9 Nested Path Existence (all 9 path params named)
- §3 Business Logic (9 subsections): 3.1 Roster · 3.2 Date-Hold Contest · 3.3 Offer Negotiation & Deal Snapshot · 3.4 Tiers/On-Sale/Roll-Up/Refunds · 3.5 Advance · 3.6 Support/Expenses/Ancillary · 3.7 Settlement Waterfall & Dispute Loop · 3.8 Wire Transfers · 3.9 Cancellation/Postponement/Force Majeure
- §4 Endpoint Definitions (77 endpoints, 4-column table) · §5 Error Catalogue (21 errors, 2-column table); document ends at §5 with no audit footer

**Zero-silence / hard-contract audit results:**

```
Field coverage check (Contract 1):
- entities[].fields: 104 required, 104 present, 0 missing
- endpoints request_body (POST inputs): 53 required, 53 present, 0 missing
- endpoints query_params (GET): 20 required, 20 present, 0 missing
- endpoints path_params: 9 required, 9 present, 0 missing
Status: PASS

Rule coverage check (Contract 2):
- validations[] with priority: 20 checked, 20 expressed in ordered prose (§2.8 + per-rule triggers in §3), 0 missing
- concurrency_rules[] OCC rejections: 4 checked, 4 expressed (write operation + expected_show_version + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: 34 checked across 8 machines, 34 fully expressed (from/to, preconditions, side effects), 0 missing
- calculations[]: 7 checked, 7 fully expressed in reconstruction-safe prose (waterfall, sliding scale, hold ranking/FIFO, tier roll-up, VERSUS marginal rate, recoupment truncation, deposit timing), 0 missing
- validations[] conditions: 20 checked, 20 matchable to error_id in prose; ERR_INVALID_REQUEST and ERR_ALREADY_TERMINAL also grounded, 0 missing
- endpoints[].side_effects / applies_to: 77 checked, 77 expressed (multi-endpoint scopes enumerated), 0 missing
- entities[].fields[] structured content: 104 checked, defaults/ranges/immutability/stamping rules reconstructible, 0 missing
- sibling-branch symmetry: 6 groups checked (3 deal kinds, 4 cancel reasons, 5 wire purposes, 2 confirm flavors, release/expire from-states, 4 wire transitions), 6 symmetric, 0 asymmetric
Status: PASS

Path purity check (Contract 3, §3 only):
- backtick tokens scanned: 570
- tokens starting with '/': 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks: §2.2 block is byte-identical to `section-2.2-response-structure.md`; all 64 enum/state strings appear in backticks; fuzzy-word and operator-syntax scans are clean (no pseudocode, no approximating language).

## Step 6: Generate Implementation — 2026-08-15T01:24:00.000Z

Implementation complete and smoke-tested. Summary:

## Files created (all under `/home/ubuntu/github/CodingPRD/tasks/task_1914_live_music_venue_booking_show_settlement/workspace/implementation/`)

| File | Role |
|---|---|
| `start.sh` | Foreground launcher; guarded `pip install` (no-op when flask present); `exec python3 app.py` |
| `requirements.txt` | `flask>=3.0,<4.0` |
| `app.py` | App assembly, `before_request` gauntlet (lazy time-sweep → auth), JSON error handlers, binds `0.0.0.0:$PORT` (default 10000) |
| `store.py` | In-memory dict stores (empty at boot, zero seeding), logical clock defaulting to exactly `2026-08-01T00:00:00Z`, monotonic 3-fractional-digit stamps, lazy sweep for DateHold EXPIRED + ADVANCED→SHOW_NIGHT |
| `errors.py` / `envelope.py` | Scaffold error catalog; envelope `meta/response_type/data`, `req_` ids, list pagination (`limit`/`offset`/`total_count`/`has_more` in `meta`) |
| `helpers.py` | Auth (`X-User-ID`/`X-User-Role`, 5 exact roles), RBAC, typed body validation (400s), path/FK lookups (404), pagination (limit default 10, clamp 1–100), all 15 serializers (ledger entities correctly omit `updated_at`/`version`) |
| `domain.py` | Hold rank + FIFO tie-break, roll-up ticket allocation (atomic, composite gross), settlement waterfall (VERSUS marginal threshold with strict `>`, half-up only at ROUND steps via `Decimal`), chronological recoupment cap with truncation, cancellation policy (60/30/14/7 penalty tiers, kill fees) |
| `routes_roster.py` / `routes_holds.py` / `routes_negotiation.py` / `routes_ticketing.py` / `routes_production.py` / `routes_finance.py` | All endpoint groups |

## Endpoint coverage: 77/77 PRD endpoints
(79 registered routes = 77 PRD + `GET /` health + Flask `/static`). Key semantics verified: OCC `expected_show_version` (412) on the 4 versioned writes with validation-order fidelity (412 before 422 readiness/expiry), `ERR_ALREADY_TERMINAL` vs `ERR_INVALID_STATE` split, segregation of duties (422), challenge/confirm priority + 24h window bypass, cross-show hold pool release on confirm, deposit snapshot at accept (14-day deadline), ticket roll-up with exact refund unwind via internal allocation map, support budget band/cap, wire canonical-amount matching, auto-wires on approve/buyout/performed/cancel, show→SETTLED only when settlement PAID + all payout wires COMPLETED, POSTPONED→CANCELLED restricted to VenueManager.

## Smoke-test results
Two suites, each run against a fresh `bash start.sh` boot:
- Happy path (roster → hold contest → negotiation → deal → tiers → deposit wire → on-sale → roll-up sale → refund → advance → SHOW_NIGHT via clock → settlement draft waterfall verified field-by-field → submit/dispute/return/approve → wires → SETTLED, `total_settled_shows`=1): **all checks passed**
- Branch suite (lazy hold expiry, ARTIST penalty 100% tier + wire return, FORCE_MAJEURE refund wire + flag + no kill fees, LOW_TICKET_SALES gate both directions + kill-fee rounding `rhu(0.5×10001)=5001`, postpone with successor show + refund cascade): **all checks passed**
- Fresh-boot contract verified: store empty, clock reads `2026-08-01T00:00:00.000Z`, no seeding anywhere.

One judgment call to flag: ownership failures (confirm/release by non-owner agent, challenger-id mismatch) return 403 `ERR_FORBIDDEN`; the same-agent self-challenge returns 409 `ERR_INVALID_STATE` — the scaffold assigns no specific error to either, so these follow the PRD's authz-vs-precondition split.

## Step 5: Generate Unit Tests — 2026-08-15T01:26:00.000Z

Clean. Final report:

## Summary

**Generated outputs** (both directories under `/home/ubuntu/github/CodingPRD/tasks/task_1914_live_music_venue_booking_show_settlement/`):

### Stage 1: `test_helpers/` (9 files)
- `__init__.py` — barrel export (framework generics + PRD-specific)
- `types.py` — TypedDicts for all 13 entities with correct `common_fields` branching (TicketSale / AncillaryRevenue / CancellationEvent omit `updated_at` + `version` per PRD §2.4); 18 status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with 50 endpoint methods covering every row of PRD §4
- `api_errors.py` — 21 `ApiErrorId` constants + HTTP status map, registered with `set_error_http_status_map`
- `assertions.py` — per-entity asserts + `assert_settlement_invariants` (net-door floor, artist-total floor, waterfall identity)
- `factories.py` — payload factories, input fields only
- `constants.py` — TTL ladder, booking-lead days, deposit-lead days, penalty tiers, split caps, pagination bounds
- `test_users.py` — shared constants for 5 roles + `make_booking_agent_headers(agent_id)` (mandatory per-instance builder for the entity-backed role) + opaque builders for promoter/accountant (used by the segregation-of-duties test)
- `fixtures.py` — composite helpers across all five tiers: master data, confirmed show via hold-confirm, show-with-deal via offer-accept, on-sale show (deposit + tier + clock), show-night show (advance + lazy SHOW_NIGHT flip), plus expense / ancillary / support / settlement / cancellation / wire helpers

### Stage 2: `test_suite/` (10 files, 61 tests)
- `conftest.py` — session-scoped `api` fixture + per-role header fixtures
- `test_01_artists_and_shows.py` — 7 tests
- `test_02_date_holds.py` — 7 tests
- `test_03_offer_negotiation.py` — 9 tests
- `test_04_on_sale_and_schedule.py` — 6 tests
- `test_05_ticket_sales.py` — 6 tests
- `test_06_advance_and_show_night.py` — 2 tests
- `test_07_settlement_waterfall.py` — 10 tests
- `test_08_cancellation.py` — 7 tests
- `test_09_wires_and_rbac.py` — 4 tests

### Coverage audit
- **Queue A (Difficulty)**: 34 tests across 18 instances — 17 instances covered with ≥2 tests, 1 instance SKIPPED
- **Queue B (Corner)**: 27 tests across 27 non-stub instances — all covered with ≥1 test (no stubs in this task's corner design)

### Skipped instances
- `Difficulty/cross_entity_state_dependency/show_on_sale_requires_deal_active` — **SKIPPED (PRD-first two-condition filter, unique derivability fails)**. The instance's own assert reads "on-sale returns ERR_INVALID_STATE or ERR_DEPOSIT_NOT_CLEARED" — the PRD §3.4 lists the gates ("a deal must be in place", "the deposit must have landed") but never uniquely names which error fires when `deal_id` is unset on an otherwise-CONFIRMED show. Two PRD-only readers could legitimately ship different error mappings. Gap stays a gap; no placeholder, no weakening.

### Self-check results
- **Stage 1**: all 9 helper files exist, parse, and import cleanly; append-only TypedDicts correctly omit `updated_at`/`version`
- **Stage 2 tag audit**: 61/61 tests carry exactly one `Design:` tag; 0 untagged; 0 dual-tagged; 0 tags pointing to non-existent instances
- **Stage 2 coverage**: 17/18 difficulty instances at ≥2 tests (1 intentionally skipped); 27/27 corner instances at ≥1 test
- **PRD verbatim citation check**: 79/79 quoted citations survive literal grep of `PRD.md` after whitespace normalization (0 failures)
- **No `pytest.mark.skip` / `skipif` / `xfail`** anywhere in the generated suite
- All test files compile; every name imported from `test_helpers` resolves; `conftest.py` imports cleanly

## Step 7: Run Tests and Iterate — 2026-08-15T02:05:00.000Z

All 8 rounds pass 61/61. Clean sweep achieved. Final summary:

## Summary

**Iterations run:** 2 (sweep 1: 8 rounds × 61 tests → union of 9 failing tests; fixes applied; sweep 2: all 8 rounds 61/61 passed, zero flakes).

**Tests deleted:** none.

**Tests fixed in `test_suite/` (PRD-mistranslation fixes — made MORE faithful to PRD):**
- `test_03_offer_negotiation.py::test_offer_negotiation_cycle` — asserted prior countered offers stay `COUNTERED` after a later acceptance; PRD §3.3 verbatim mandates "Every other offer on the show still sitting in `PENDING` or `COUNTERED` is swept to `SUPERSEDED`". Assertions changed to `SUPERSEDED` (implementation was already correct).
- `test_05_ticket_sales.py::test_tier_capacity_exceeded_on_create` — fixture built the show with default `total_capacity=500` while the test's own arithmetic comments assumed 100 (60+50=110 fits in 500, so no error fired). Passed `show_overrides=dict(total_capacity=100)` to match the PRD §3.4 capacity-sum rule the test intends.
- `test_07_settlement_waterfall.py::test_artist_payout_provisional_vs_final_on_show` — asserted a submission freezes the *draft-creation* snapshot (5000) even after an expense was approved while the settlement was `DRAFT`; PRD §3.6 verbatim says "Approving a receipt while a settlement draft exists recomputes the draft's `recoupable_expenses_cents` — but only a draft". Rewrote the test to assert the draft recomputes to 13000/87000 (provisional) and submission then freezes those values.
- `test_08_cancellation.py::_build_confirmed_with_deposit` — the setup helper issued a zero-amount `ARTIST_DEPOSIT` wire (artist with `deposit_pct=0.0`); PRD §3.8 requires "a strictly positive `amount_cents`", so a PRD-faithful server must reject it. Helper now skips the wire when the amount is 0.
- `test_02_date_holds.py::test_date_hold_release_from_terminal_confirmed_fails` and `test_03_offer_negotiation.py::test_offer_reject_is_terminal_and_idempotent` — relaxed exact `ERR_INVALID_STATE` to `validate_error_is_one_of([ERR_INVALID_STATE, ERR_ALREADY_TERMINAL])` (+ explicit HTTP 409 check). Unique-derivability collapse: PRD §2.8's general from-state sentence ("failures yield `ERR_INVALID_STATE`") and its terminal-state special case ("already in a terminal state and no transition is defined at all → `ERR_ALREADY_TERMINAL`") overlap on release-from-`CONFIRMED` and reject-from-`REJECTED` without naming which governs.

**Fixes applied to `test_helpers/`:**
- `test_helpers/api_client.py` — added bounded retry (6 attempts, linear backoff) on `requests.ConnectionError` / `ChunkedEncodingError` in `ApiClient._request`. Root cause of the flaky `test_versus_one_cent_above_threshold_pays_bonus` (rounds 2 and 5 of sweep 1): host-level transient SIGTERMs ("Terminated" markers in `/tmp/prd_bench_server_*.log`, no server-side tracebacks, ample RAM) kill freshly spawned per-test servers mid-request; the plugin's emergency restart recovers within ~1s, and a retried request is idempotent because any request that never completed never touched the (in-memory, per-boot) server state.

**Fixes applied to `implementation/`:**
- `workspace/implementation/routes_holds.py::confirm_hold` — the `before_request` clock sweep flips lapsed holds to `EXPIRED` before the handler, so confirming a hold past its deadline surfaced `ERR_ALREADY_TERMINAL` (409), making PRD §3.2's "Confirming at or past the applicable deadline is rejected with `ERR_HOLD_EXPIRED` (HTTP 422)" unreachable and contradicting §2.8's precedence example (staleness precedes hold-expiry timing at rules 6→9). The handler now routes `EXPIRED` holds to the rule-9 position (after the OCC check) and raises `ERR_HOLD_EXPIRED`; `CONFIRMED`/`RELEASED` holds still raise `ERR_ALREADY_TERMINAL`.

Orchestrator verification: all 8 `results.{1..8}.json` files confirm passed=61/61, failed=0.

## Step 8: Finalize PRD — 2026-08-15T02:15:00.000Z

The diff is exactly the two intended in-place revisions. Here is the exit summary.

## Summary

**File:** `/home/ubuntu/github/CodingPRD/tasks/task_1914_live_music_venue_booking_show_settlement/workspace/PRD_FINALIZED.md` (created via `cp` from PRD.md, then edited).

**Line counts / delta:** PRD.md = 320 lines; PRD_FINALIZED.md = 320 lines; **0.0% line delta** (2 lines revised in place, no insertions or deletions of lines — both edits replace text within existing lines 100 and 126).

**Changes (2 total):**

- **§2.8 (rule 5 of the validation pipeline) — revise** — Replaced the overlapping pair "failures yield `ERR_INVALID_STATE`" / "terminal state … → `ERR_ALREADY_TERMINAL`" with a determinate selection rule: terminal current state → `ERR_ALREADY_TERMINAL` (409), non-terminal wrong from-state → `ERR_INVALID_STATE` (409), plus an explicit terminal-state enumeration (hold: CONFIRMED/RELEASED/EXPIRED; offer: ACCEPTED/REJECTED/WITHDRAWN/SUPERSEDED; show: SETTLED/CANCELLED; support act: PERFORMED/BOUGHT_OUT/CANCELLED; receipt: APPROVED/REJECTED; settlement: PAID; wire: COMPLETED/FAILED/RETURNED), an override clause subordinating §3's bare "`ERR_INVALID_STATE`" from-state mentions (§3.4 on-sale, §3.5 advance toggle, §3.9 cancel) to this rule, and a carve-out clause for §3-named specific errors (`ERR_HOLD_EXPIRED`). — `implementation/routes_holds.py:89-92,119-122,164-165`; `routes_negotiation.py:138-142,158-160,178-180`; `routes_production.py:78-81,104-107,185-190,211-216,281-286,301-302`; `routes_finance.py:32-35,94-97,126-129,150-153,166-169,273-277`; `routes_ticketing.py:22-24,87-89,137-139,181-182`.
- **§3.2 (hold confirmation) — revise** — Replaced "confirming a hold that is not in the `ACTIVE` or `CHALLENGED` from-state is rejected with `ERR_INVALID_STATE`" (which contradicted the impl and the new rule 5) with: confirming at/past the deadline stays a rule-9 business failure evaluated after the §2.6 staleness check even when the lazy clock has already swept the hold to `EXPIRED` (an `EXPIRED` hold reports `ERR_HOLD_EXPIRED`, never `ERR_ALREADY_TERMINAL`); confirming a hold in `CONFIRMED`/`RELEASED` draws `ERR_ALREADY_TERMINAL` per §2.8 rule 5. — `implementation/routes_holds.py:110-144` (the Step 7 fix site) and `store.py:116-134` (the lazy sweep that flips holds to `EXPIRED` before the handler runs).

**Step-7 items requiring no edit (PRD already determines behavior; fixture/test-side bugs only):** §3.3 SUPERSEDED sweep (`routes_negotiation.py:215-219` matches verbatim PRD), §3.4 tier-capacity-sum rule (`routes_ticketing.py:47-49` matches), §3.6/§3.7 draft recompute on receipt approval (`routes_production.py:290-292`, `domain.py:210-216` match), §3.8 strictly-positive wire amount (`routes_finance.py:239-240` matches), and the `test_helpers/api_client.py` retry fix (not PRD-relevant).

**Per-edit pre-edit search log:**

1. **Edit 1 (§2.8 rule 5):** (a) Subject: the `ERR_INVALID_STATE` vs `ERR_ALREADY_TERMINAL` selection at pipeline step 5. (b) Enumerated and read every `already_terminal`/`invalid_state` raise site via grep across `routes_holds.py`, `routes_negotiation.py`, `routes_production.py`, `routes_finance.py`, `routes_ticketing.py`, `routes_roster.py`, `domain.py`, `helpers.py`, `errors.py`: all hold transitions (challenge/confirm/release), all offer transitions (`_offer_state_check` for counter/accept/reject/withdraw), show-gated operations (`_show_terminal_or`, `_show_terminal_check`, inline checks in on-sale, sale creation, advance toggle/complete, buyout, mark-performed, receipt approve, settlement submit, cancel, postpone), support-act and receipt checks, settlement PAID checks, the wire `_wire_state` helper (complete/fail/retry/mark-returned), and the ticket-refund check. (c) Wording adjustments forced by the enumeration: (i) chose an explicit terminal-state enumeration instead of a generic "no outgoing transition" definition, because the generic form mis-pins two off-site paths — `complete`/`fail`/`mark-returned` from a `FAILED` wire (impl: `ERR_ALREADY_TERMINAL` at `routes_finance.py:275-276`, but `FAILED` has the retry transition defined) and re-refund of a `REFUNDED` TicketSale (impl: `ERR_INVALID_STATE` at `routes_ticketing.py:181-182`, although `REFUNDED` is final); the enumeration includes wire `FAILED` and omits TicketSale, matching impl exactly on both; (ii) excluded show `POSTPONED` from the terminal list (impl treats it as non-terminal — `_show_terminal_or` raises `invalid_state` for it, and VenueManager-cancel from `POSTPONED` succeeds per `routes_finance.py:374-378`); (iii) excluded offer `COUNTERED` (impl: `invalid_state`, `routes_negotiation.py:139-142`); (iv) added the "governs even where a §3 passage describes a from-state failure only as `ERR_INVALID_STATE`" clause to neutralize the otherwise-new contradictions with §3.4/§3.5/§3.9 without editing those sections; (v) added the specific-error carve-out clause so rule 5 does not contradict Edit 2's `ERR_HOLD_EXPIRED` routing.
2. **Edit 2 (§3.2 confirm):** (a) Subject: error selection on the confirm endpoint for expired and terminal holds. (b) Enumerated and read `routes_holds.py:110-156` (full `confirm_hold` ordering: terminal check → ownership → competitor precondition → OCC staleness → `EXPIRED`/deadline checks → cascade), `store.py:116-134` (the `before_request` lazy sweep that flips `ACTIVE`/`CHALLENGED` holds to `EXPIRED`), `routes_holds.py:80-107` (challenge-from-`EXPIRED` → `ERR_ALREADY_TERMINAL`, the parallel endpoint touching the same hold states), and §2.8's existing precedence example (staleness rule 6 precedes expiry rule 9). (c) Wording adjustments forced by the enumeration: scoped the "never `ERR_ALREADY_TERMINAL`" claim to the confirm endpoint only (challenge-from-`EXPIRED` remains `ERR_ALREADY_TERMINAL` per impl line 90-91 and rule 5); stated the expiry check is "evaluated after the §2.6 staleness check" to match the impl's rule-9 position (stale version on an `EXPIRED` hold yields `ERR_STALE_VERSION`, keeping §2.8's existing precedence example true); dropped the old "`ERR_INVALID_STATE` for non-ACTIVE/CHALLENGED from-states" clause entirely because no observable confirm from-state yields `ERR_INVALID_STATE` in the impl (the `invalid_state` branch at line 121-122 is unreachable given the status enum), and the competitor-blocked confirm (`invalid_state`, line 127-128) is a separate precondition check the PRD never named an error for — left untouched to avoid a new pin.

## Step 9: Complete PRD — 2026-08-15T02:35:00.000Z

PRD_COMPLETED.md is written at `/home/ubuntu/github/CodingPRD/tasks/task_1914_live_music_venue_booking_show_settlement/workspace/PRD_COMPLETED.md`. All changes are inline in-paragraph inserts/revisions — no new sections, no new paragraphs, no invented behavior.

## Summary

**Size:** PRD_FINALIZED.md 320 lines / 56,494 bytes → PRD_COMPLETED.md 320 lines / 61,872 bytes (**+5,378 bytes**, 0 line-count change, 25 section headings in both).

**Counts:** 38 ambiguity-pins, 2 mismatch-revisions (40 change bullets below).

### §2 Global — insert — ambiguity (4)
- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` are clamped into bounds, not rejected; non-integer values get `ERR_INVALID_REQUEST` (400) — implementation/helpers.py:202-224
- §2.4 — insert — ambiguity — `version` starts at 1 at creation, `updated_at` initially equals `created_at` — implementation/store.py:83-91
- §2.7 — revise — ambiguity — clock is *set* (not merely advanced) verbatim with no monotonicity check; answers 200 with `data.current_utc` — implementation/routes_roster.py:170-177

### §3.1 Roster — insert — ambiguity (3)
- §3.1 — insert — ambiguity — out-of-range `deposit_pct` or negative `guarantee_floor_cents` → `ERR_INVALID_REQUEST` (400) — implementation/routes_roster.py:30-33
- §3.1 — insert — ambiguity — artist born `ACTIVE`; `status` has no transition endpoint and gates nothing — implementation/routes_roster.py:39
- §3.1 — insert — ambiguity — booking agent born `ACTIVE` — implementation/routes_roster.py:64-68

### §3.2 Holds — insert — ambiguity (7)
- §3.2 — insert — ambiguity — `total_capacity` must be an integer ≥ 1, else 400 — implementation/routes_roster.py:139
- §3.2 — insert — ambiguity — show birth also sets `deposit_required_cents`/`deposit_paid_cents` = 0, `deposit_due_by_utc` null — implementation/routes_roster.py:104-106
- §3.2 — revise — ambiguity — hold placement is not gated on show status; `booked_by_agent_id` is neither existence-checked nor compared to the caller at placement — implementation/routes_holds.py:53-61
- §3.2 — insert — ambiguity — per-show hold listing filters by `status` only — implementation/routes_holds.py:64-70
- §3.2 — insert — ambiguity — same-agent challenge → `ERR_INVALID_STATE` (409); caller ≠ `challenger_agent_id` → `ERR_FORBIDDEN` (403) — implementation/routes_holds.py:93-98
- §3.2 — insert — ambiguity — successful challenge answers HTTP 201 with the newly created challenger hold — implementation/routes_holds.py:106-107
- §3.2 — insert — ambiguity — confirm/release ownership mismatch → `ERR_FORBIDDEN` (403); competing-hold block → `ERR_INVALID_STATE` (409) — implementation/routes_holds.py:124-128, 166-167

### §3.3 Negotiation — insert — ambiguity (7)
- §3.3 — insert — ambiguity — round-one offer creation is not gated on show status — implementation/routes_negotiation.py:110-119
- §3.3 — insert — ambiguity — per-show offer listing filters by `status` only — implementation/routes_negotiation.py:122-128
- §3.3 — revise — ambiguity — `bar_split_pct`, `merch_split_pct`, and both budgets are required on every offer regardless of kind; `versus_threshold_cents` and budgets must be non-negative; kind-unrequired fields may be omitted/null (a `DOOR_SPLIT` guarantee is stored but unconstrained) — implementation/routes_negotiation.py:26-68
- §3.3 — insert — ambiguity — reject/withdraw are not gated on show status; withdraw by the wrong side → `ERR_FORBIDDEN` (403) — implementation/routes_negotiation.py:224-248
- §3.3 — insert — ambiguity — accept answers HTTP 200 with the newly minted `Deal` object — implementation/routes_negotiation.py:221
- §3.3 — insert — ambiguity — `deposit_due_by_utc` is midnight (00:00:00 UTC) 14 days before `show_date` — implementation/routes_negotiation.py:211-213
- §3.3 — insert — ambiguity — per-show deal fetch answers `ERR_NOT_FOUND` when no `ACTIVE` deal exists — implementation/routes_negotiation.py:254-261

### §3.4 Ticketing — 5 pins + 1 revision
- §3.4 — insert — ambiguity — tier creation not gated on show status; non-positive `face_price_cents`/`capacity` → `ERR_INVALID_REQUEST` (400) — implementation/routes_ticketing.py:30-44
- §3.4 — insert — ambiguity — missing deal or empty tier manifest on go-on-sale → `ERR_INVALID_STATE` (409) — implementation/routes_ticketing.py:90-94
- §3.4 — insert — ambiguity — sales accepted precisely in `ON_SALE`, `ADVANCED`, or `SHOW_NIGHT` — implementation/routes_ticketing.py:137
- §3.4 — insert — ambiguity — the `TicketSale` row's `tier_id` names the requested tier — implementation/routes_ticketing.py:144
- §3.4 — revise — **mismatch** — refund unwinds *each contributing tier* by the seats that tier supplied (PRD said "the tier's `sold_count` by the sale's `quantity`"); also pins double-refund → `ERR_INVALID_STATE` (409) and no show-status gate — implementation/domain.py:104-114, implementation/routes_ticketing.py:176-184

### §3.5 Advance — insert — ambiguity (3)
- §3.5 — insert — ambiguity — checklists listed with optional `show_id` filter — implementation/routes_production.py:56-60
- §3.5 — insert — ambiguity — toggling an item already in the requested state is a no-op (no `updated_at`/`version` change) — implementation/routes_production.py:82-85
- §3.5 — insert — ambiguity — complete-advance with `all_complete` false → `ERR_INVALID_STATE` (409) — implementation/routes_production.py:108-109

### §3.6 Support/Expenses/Ancillary — insert — ambiguity (5)
- §3.6 — insert — ambiguity — support creation not gated on show status; band pinned as `2 × buyout_fee ≥ agreed_fee`; non-positive agreed fee draws the same `ERR_SUPPORT_BUDGET_EXCEEDED` — implementation/routes_production.py:118-131
- §3.6 — insert — ambiguity — no budget cap enforced when the show has no deal (or the deal has no `support_budget_cents`) — implementation/domain.py:293-299
- §3.6 — insert — ambiguity — receipt submission not gated on show status; non-positive `amount_cents` → `ERR_INVALID_REQUEST` (400) — implementation/routes_production.py:227-235
- §3.6 — revise — ambiguity — receipt rejection not gated on show status; approving while a draft exists recomputes *every* computed field of the draft, not just `recoupable_expenses_cents` — implementation/routes_production.py:290-307, implementation/domain.py:210-216
- §3.6 — insert — ambiguity — non-positive ancillary `gross_cents` or negative `cost_cents` → `ERR_INVALID_REQUEST` (400) — implementation/routes_production.py:318-324

### §3.7 Settlement — insert — ambiguity (2)
- §3.7 — insert — ambiguity — creation requires an accepted deal and is otherwise ungated; missing deal or existing settlement → `ERR_INVALID_STATE` (409) — implementation/routes_finance.py:56-64
- §3.7 — insert — ambiguity — per-show settlement fetch answers `ERR_NOT_FOUND` when none exists — implementation/routes_finance.py:77-84

### §3.8 Wires — insert — ambiguity (7)
- §3.8 — insert — ambiguity — non-positive `amount_cents` → `ERR_WIRE_AMOUNT_MISMATCH` (422); reference-shape violations → `ERR_INVALID_REQUEST` (400); `REFUND_TO_VENUE` carries no required references — implementation/routes_finance.py:210-224, 239-240
- §3.8 — insert — ambiguity — referenced support acts/settlements must belong to the path show; artist references checked for existence only — implementation/routes_finance.py:226-236
- §3.8 — insert — ambiguity — no canonical-source amount check for `ARTIST_DEPOSIT`/`REFUND_TO_VENUE`; cross-show list adds a `show_id` filter; per-show list filters by `purpose` and `status` — implementation/routes_finance.py:241-249, 186-195, 256-263
- §3.8 — insert — ambiguity — direct wire initiation is not gated on show status — implementation/routes_finance.py:198-253
- §3.8 — revise — ambiguity — `ARTIST_BALANCE` completion moves the settlement *from `APPROVED`* to `PAID`; `REFUND_TO_VENUE` completion posts no ledger adjustment — implementation/routes_finance.py:308-320
- §3.8 — insert — ambiguity — mark-returned with wrong purpose or non-`CANCELLED` show → `ERR_INVALID_STATE` (409) — implementation/routes_finance.py:357-359

### §3.9 Cancellation/Postponement — 3 pins + 1 revision
- §3.9 — revise — **mismatch** — `REFUND_TO_VENUE` wire is initiated only when the refundable portion is positive (in practice only `FORCE_MAJEURE` with a positive paid deposit); under `ARTIST` the refundable portion is always zero so no wire is initiated — implementation/routes_finance.py:433-435
- §3.9 — insert — ambiguity — cancel answers HTTP 201 with the persisted `CancellationEvent` — implementation/routes_finance.py:445
- §3.9 — insert — ambiguity — postpone schedule violations → `ERR_INVALID_SHOW_SCHEDULE` (422); the seven-day lead time is not re-evaluated; the successor inherits `room`, `total_capacity`, and `on_sale_at_utc` with a fresh checklist; answers HTTP 201 with the successor show — implementation/routes_finance.py:456-490
- §3.9 — insert — ambiguity — non-`VenueManager` cancelling a `POSTPONED` show → `ERR_FORBIDDEN` (403) — implementation/routes_finance.py:374-378

**Notable consistency confirmations (no change needed):** the full waterfall arithmetic (incl. strict `>` VERSUS comparator and marginal-rate split), recoupment cap truncation, hold TTL ladder and challenge window, the §2.8 pipeline order (incl. OCC-before-deposit-gate on `/on-sale` and OCC-before-readiness on submit), per-act half-up kill-fee rounding then sum, low-sales threshold `ceil(0.3 × capacity)`, terminal-state catalog of §2.8 rule 5, and all endpoint/role rows in §4 match the implementation exactly.
