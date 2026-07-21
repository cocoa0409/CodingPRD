# Worklog — task_1059_event_ticketing_selfserve

## Step 1: Create task directory — 2026-07-18T00:00:00.000Z

Used pre-assigned directory `tasks/task_1059_event_ticketing_selfserve` (Step 1 index scan skipped per launch instruction). Created `workspace/`.

## Step 2: Generate scaffold (Expert) — 2026-07-18T17:20:00.000Z

All three artifacts are written and validated.

**SCAFFOLD.yaml** (§1.0–§1.7) — Expert, `domain_name: event-ticketing-selfserve`, `api_prefix: /api`
- Profile: primary `quota_allocation` + secondary `pricing_engine`; layers = OCC, cascading side effects, dual-variant calc, rate/threshold triggers; topology `flat`, shape `parallel`, role model `segregation_of_duties`, consistency `immediate`.
- **15 entities**: Organizer, Venue, Buyer, Event, TicketType, SeatBlock, PromoCode, Order, OrderItem, Attendee, ScanRecord (append-only, `common_fields: false`), RefundRequest, TransferRequest, WaitlistEntry, Payout.
- **7 state machines**: Event (cyclic ONSALE↔PAUSED), Order (**parallel** payment × fulfillment), Attendee (cyclic ISSUED↔CHECKED_IN), RefundRequest (branching), TransferRequest (cyclic SENT→DECLINED→SENT), WaitlistEntry (cyclic WAITING→OFFERED→EXPIRED→WAITING), Payout (cyclic ELIGIBLE↔ON_HOLD).
- **2 OCC concurrency rules**: `order-create-stale-event` (Event.version, 412) and `payout-create-stale-organizer` (Organizer.version, 412).
- **7 calculations**: `order_fee_breakdown` (tiered, round-per-ticket-then-sum pinned), `promo_discount`, `refund_amount` (dual-variant FEE_RETAINED/FEE_INCLUDED), `organizer_reliability_score` (dual-variant LIFETIME/TRAILING), `payout_net_amount` (7-step pinned order, frozen reliability snapshot breaks the cycle), `ticket_type_availability`, `event_report`.
- **56 validation rows** (priority 1→90), **69 endpoints** (incl. `POST /_clock/set_current_utc`, default clock `2026-07-01T00:00:00Z`), **56 error codes**, **6 roles** (Organizer/Buyer entity-backed; GateStaff/FinanceOfficer/PlatformAdmin/Anonymous opaque).
- All constants declared numerically in a `global_constants:` block and re-declared per calculation (fee tiers 0.020/0.037/0.050, flat 179, min 99, cap 2500, promo floor 5000, 30% cap, hold 15 min, venue turnaround 90 min, TTLs 24h/72h, reserve tiers 0.00/0.05/0.10/0.20, default reliability 75, trailing window 2, reserve release 90 days, etc.).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** — 9 rule_ids × **2 instances = 18**, every one with a structured empty-DB `setup_api_calls` chain. All formula-derived assertions were computed in Python before being written (fee_total 1546 vs the 1545 "sum-then-round" trap; refund 10000 vs 10728; LIFETIME 58 vs TRAILING 55; payout 65→0.10→reserve 500→net 4500; negative-net −728 → ON_HOLD; promo 5000-inclusive → discount 500 / buyer_total 4864).

**SCAFFOLD_CORNER_DESIGN.yaml** — **62 instances across 9 sections** (entities 12, state_machines 13, calculations 10, validations 9, endpoints 3, errors 4, rbac 5, cross_cutting_layers 5, consistency_model 1), of which **7 are `excluded_because` stubs** pointing at named §1.8 instances; 55 carry full recipes.

**Verification**
- `yaml.safe_load` passes on all three files (fixed bare-`?`/nested-`[` hazards by quoting).
- `scaffold_lint.py` → `VERDICT: clean lint` over 736 calls; FK reverse-reachability clean for all 15 entities.
- Custom audit: 80 unique instance names, 0 unbound `${var}`, all `excluded_because` targets resolve, 0 forbidden concurrency vocabulary.

## Step 3: Copy INSTRUCTION.md — 2026-07-18T17:21:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1059_event_ticketing_selfserve/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-18T17:29:00.000Z

PRD generated at `workspace/PRD.md`. 403 lines, 23 headings — §1 Introduction, §2 (2.1 RBAC, 2.2 Response Structure, 2.3 Pagination, 2.4 Common Resource Properties, 2.5 Logical Clock & Lazy Expiry, 2.6 Money/Rounding, 2.7 OCC, 2.8 Validation Precedence, 2.9 Inventory Truth), §3 (9 domain-grouped subsections), §4 endpoint table, §5 error table.

Hard contracts all PASS:
- Field coverage: entities 94/94, request bodies 41/41, query/path params 31/31, output keys 19/19.
- Rule coverage: 44/44 validations (12-rung precedence ladder in §2.8), 2/2 OCC rules, 7 machines/44 transitions, 7/7 calculations, 56 error ids, 69/69 endpoint side-effects, 15 entities, 6 sibling-branch symmetry groups.
- Path purity (§3): 758 backtick tokens scanned, 0 leaked paths/methods.

Endpoint coverage: all 69 scaffold endpoints in §4, each reachable from §3 prose. All 56 error codes in §5 and triggered in narrative.

Scaffold gaps resolved (flagged, no invention):
- `complexity_profile` claims 68 endpoints / 53 errors; actual tables hold 69 endpoints / 56 unique error ids. Followed the tables.
- Validation priority 20 scoped `ERR_REFUND_REQUEST_NOT_FOUND` to refund paths; priorities 21–24 give the other four entities their own codes → rendered each with its own not-found code in a fixed evaluation order in §2.8.
- `ERR_DUPLICATE_PROMO_CODE` is the shared uniqueness code for promo-code, seat-block `row_label` and buyer `email` collisions (validation 73) — stated explicitly at all three sites.
- `ERR_PROMO_EVENT_MISMATCH` covers promo/tier/seat-block parentage failures on order create — stated explicitly.
- Event `DRAFT → CANCELLED` has no orders to unwind; wrote DRAFT-cancel as hop 1 + waitlist expiry only.
- All 33 declared constants appear with concrete values. No constant was undeclared → no pre-patching of SCAFFOLD.yaml required.

## Step 5: Generate unit tests — 2026-07-18T17:53:00.000Z

**`test_helpers/`** (9 files, ~1,700 lines) — `types.py` (15 entity TypedDicts + 12 status/role enums; `ScanRecord` omits `updated_at`/`version` per `common_fields: false`), `api_client.py` (one method per endpoint, 68 + `/_clock/set_current_utc`), `api_errors.py` (56-entry `ApiErrorId` enum + HTTP status map), `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py` (491 lines, 5 tiers incl. `setup_completed_event_with_payout`, `setup_eligible/approved/released_payout`, `setup_offered_waitlist_entry`, `setup_transfer_offer`, `setup_reserved_onsale_event`), `__init__.py`. Identity threading enforced: `make_organizer_headers(org["id"])` / `make_buyer_headers(buyer["id"])` for the two entity-backed roles; opaque roles use shared constants.

**`test_suite/`** — `conftest.py` + 11 test files (`test_01`…`test_11`), **91 tests**.

Per-queue: Queue A Difficulty 18 instances → 36 tests (≥2 each, no shortfall); Queue B Corner 55 non-stub → 55 tests (≥1 each); 7 `excluded_because` stubs not translated (correct).

**Skipped instances: NONE.** Every non-stub instance passed the PRD-first two-condition filter. All 7 `difficulty_instance` cross-references resolve.

Verification: `ast.parse` clean on all 20 files; `pytest --collect-only` collects 91 with no import errors; pyflakes clean. Tag audit: exactly one `Design:` line per test, 73 distinct tags = 18 Difficulty + 55 Corner, zero unknown/dual/untagged. Verbatim citation audit scripted against PRD.md — all pass. No skip/skipif/xfail; no scaffold references leak.

Judgment call flagged: `Corner/state_machines/corner_pause_from_draft_is_an_invalid_transition` asserts `ERR_INVALID_EVENT_TRANSITION`; PRD binds that code to wrong-source lifecycle transitions in three places but never for `pause` specifically. Kept because §3.4 scopes `ERR_EVENT_NOT_ONSALE` to selling operations and §4 describes pause as a lifecycle transition. Weakest derivability link in the suite; likely Step-9 pin candidate.

## Step 6: Generate implementation — 2026-07-18T17:53:00.000Z

`workspace/implementation/` — 18 Python modules + launcher: `start.sh` (guarded `pip install`, `exec python3 app.py`), `requirements.txt`, `app.py`, `db.py` (in-memory store, logical clock default `2026-07-01T00:00:00Z`, ms-precision ISO), `errors.py`, `response.py`, `middleware.py`; `services/` (constants, money, derive, lookup, serializers, pricing, refunds, reliability, payouts, workflow); `routes/` (clock, parties, events, ticket_types, seat_blocks, promo_codes, orders, attendees, scans, refund_requests, transfer_requests, waitlist, payouts).

**Route count: 69 registered vs 69 PRD §4 rows** — verified via `app.url_map`. `ast.parse` clean; server booted via `start.sh` and answered 200. Smoke suites exercised checkout/fee ladder/promo, reserved-seat collisions, pay→scan→CHECKED_IN_FULL, refunds (FEE_RETAINED 4500/364/4500), transfer decline→resend→accept, waitlist sweep/claim, cancel cascade, payout chain with SoD, auth/RBAC/pagination.

PRD ambiguities resolved:
1. Waitlist claim vs its own hold — an `OFFERED` entry's `requested_quantity` counts toward `held_count`; excluded its own offer from availability, else the flow is unreachable.
2. Scan-time attendee state precedence — scaffold rule 48's `applies_to` excludes `/api/scans`, so scans use `ERR_TICKET_VOIDED`/`ERR_ALREADY_CHECKED_IN`; on `POST /api/transfer-requests` PRD prose wins (voided → `ERR_TICKET_VOIDED` first).
3. Undeclared error codes — scan gate, waitlist requeue, transfer send event gates → `ERR_EVENT_NOT_ONSALE`; attendee void on COMPLETED event → `ERR_INVALID_EVENT_TRANSITION`.
4. Event-create guard order — PRD §3.2 "First… Second…" wins over scaffold priority: start-validity before venue double-booking.
5. Event roll-ups — `gross_cents`/`refunds_cents`/`issued_count`/`checked_in_count` stored and recomputed only at PRD-named points; tier `sold_count`/`held_count`, `seats_taken`, promo `uses_count` derived at read time.
6. `release-reserve` — no from-state declared; only maturity check enforced.
7. Tier creation status gate — §3.3 declares no error, so no gate enforced.

## Step 7: Test and fix loop — 2026-07-18T17:57:00.000Z

**Iterations run:** 1 (the initial 8-round sweep passed clean; no fix loop was needed).

**Sweep result:** All 8 rounds — 91/91 passed, 0 failed, 0 errors, 0 skipped. Run as 2 waves of 4 concurrent rounds via `sweep.sh`; no boot-timeout ERRORs, no flakiness (zero union failures across rounds).

**Tests deleted:** None. No test failed in any round, so the STEP 1 coverage / unique-derivability protocol was never triggered.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `implementation/`:** None.

**Integrity check (cardinal rules):** verified rather than assumed. `implementation/db.py` uses pure in-memory Python dicts across 15 collections, with `reset()` clearing every collection on boot. Grep for `sqlite`, `open(`, `pickle`, `shelve`, `/tmp/`, and JSON file paths returned zero hits — no file-backed persistence anywhere. The only `seed`/`preload`/`hardcode` matches are docstring comments explicitly stating the store starts empty; no seeding code exists.

Caveat flagged by the subagent: a clean first sweep confirms implementation and tests agree, but is not evidence that PRD.md fully specifies the asserted behavior — the Step 9 audit becomes the only signal and tends to be larger, not smaller.

Orchestrator verification: all 8 `results.N.json` re-read independently — 91/91, 0 failed, 0 errors in every round.

## Step 8: Finalize PRD — SKIPPED — 2026-07-18T17:58:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, 0 `implementation/` fixes. No `PRD_FINALIZED.md` produced; Step 9 starts from `PRD.md`.

## Step 9: Complete PRD — 2026-07-18T18:06:00.000Z

`workspace/PRD_COMPLETED.md` written. Source `PRD.md` 402 lines / 72,688 chars → `PRD_COMPLETED.md` 402 lines / 81,275 chars (**+8,587 chars**, 38 lines modified, 0 lines added/removed — every change is an in-paragraph insert or revision).

**Counts: 32 ambiguity-pins, 8 mismatch-revisions.**

- §2.1 — revise — mismatch — ownership was scoped to "mutating" endpoints; impl also enforces it on 9 scoped single-resource reads, on none of the organizer/venue/buyer reads, and on no list endpoint — `services/lookup.py:82`, `routes/orders.py:192`
- §2.3 — revise — ambiguity — unparseable (non-integer) `limit`/`offset` also → `ERR_INVALID_REQUEST` — `response.py:67`
- §2.4 — insert — mismatch — Event roll-up recomputes do **not** advance the event's `version`/`updated_at` — `services/derive.py:183`, `routes/orders.py:245`
- §2.9 — insert — ambiguity — multiple lines naming the same tier are summed and tested once per distinct tier — `routes/orders.py:145`
- §3.1 — revise — ambiguity — buyer-email uniqueness is exact and case-sensitive — `routes/parties.py:91`
- §3.2 — insert — ambiguity — acting Organizer must equal `organizer_id` on event create, checked after both lookups — `routes/events.py:42`
- §3.3 — revise — mismatch — tier create is **not** gated on event status — `routes/ticket_types.py:26`
- §3.3 — revise — ambiguity — tier read exposes the derived available count under both `available` and `available_count` — `services/serializers.py:23`
- §3.3 — insert — ambiguity — tier PATCH: both fields optional, no status gate, empty edit still bumps both versions — `routes/ticket_types.py:74`
- §3.3 — insert — mismatch — seat-block duplicate-`row_label` check runs *before* the range check; `seating_mode` not checked — `routes/seat_blocks.py:26`
- §3.3 — insert — ambiguity — promo `valid_from`/`valid_until` never compared at creation — `routes/promo_codes.py:24`
- §3.4 — revise — mismatch — promo resolution is global-by-code preferring the order's event — `routes/orders.py:64`
- §3.4 — revise — mismatch — the four promo gates fire in §2.8 precedence (window → parentage → floor → exhausted) — `routes/orders.py:81`
- §3.4 — revise — mismatch — checkout precedence list places the promo window right after the event-state gate — `routes/orders.py:81`
- §3.4 — insert — ambiguity — cross-line seat duplication → `ERR_SEAT_UNAVAILABLE`; within-line → `ERR_SEAT_RANGE_INVALID` — `routes/orders.py:107`, `:121`
- §3.5 — revise — mismatch — pay checks event `ONSALE` *first*, before held/pending and hold-expiry gates — `routes/orders.py:227`
- §3.5 — revise — ambiguity — pay leaves event `version` untouched, bumps order `version` once — `routes/orders.py:238`
- §3.5 — insert — ambiguity — scan: non-gate event status → `ERR_EVENT_NOT_ONSALE`, before window and mismatch checks — `routes/scans.py:28`
- §3.5 — insert — ambiguity — fulfilment re-derivation scope, VOIDED handling, version bump only on change — `services/workflow.py:105`
- §3.5 — insert — ambiguity — GateStaff may undo any check-in; Organizer only on owned events — `routes/attendees.py:86`
- §3.5 — revise — ambiguity — void: COMPLETED event → `ERR_INVALID_EVENT_TRANSITION` before already-voided guard; clears `checked_in_at`; no fulfilment re-derive — `routes/attendees.py:68`
- §3.6 — insert — ambiguity — transfer creation does not consult event status — `routes/transfer_requests.py:30`
- §3.6 — insert — ambiguity — send: non-gate event status → `ERR_EVENT_NOT_ONSALE`; caller must be holder or `from_buyer_id` — `routes/transfer_requests.py:93`
- §3.6 — insert — ambiguity — accept leaves `offer_expires_at` set; email mismatch → `ERR_UNAUTHORIZED` before source-status gate — `routes/transfer_requests.py:127`
- §3.7 — insert — ambiguity — waitlist join does not consult event status — `routes/waitlist.py:28`
- §3.7 — insert — ambiguity — claim check order (event → entry → expiry → ceiling → capacity) + self-exclusion of the entry's own offered hold — `routes/waitlist.py:88`
- §3.7 — revise — ambiguity — requeue checks entry status first; wrong event status → `ERR_EVENT_NOT_ONSALE` — `routes/waitlist.py:139`
- §3.8 — revise — ambiguity — `item_refunds` non-empty, `reason` required (may be empty), cross-order line → `ERR_ORDER_ITEM_NOT_FOUND` — `routes/refund_requests.py:22`, `:56`
- §3.8 — revise — ambiguity — null `paid_at` → `ERR_REFUND_WINDOW_CLOSED` — `routes/refund_requests.py:75`
- §3.8 — revise — ambiguity — approval computes from stored `policy` + event's current `fee_mode` — `routes/refund_requests.py:142`
- §3.8 — revise — ambiguity — `REFUNDED` requires exact equality; overshoot leaves `PARTIALLY_REFUNDED` — `services/workflow.py:139`
- §3.8 — revise — ambiguity — settlement voids the first `quantity` still-live admissions per line in `created_at` order — `services/workflow.py:147`
- §3.8 — insert — ambiguity — settlement does not refresh event `gross_cents`/`refunds_cents` — `services/workflow.py:127`
- §3.8 — revise — ambiguity — cancellation's auto refund requests carry `settled_at` null, `reason` = "Event cancelled" — `services/workflow.py:221`
- §3.9 — insert — ambiguity — bad `variant` → `ERR_INVALID_REQUEST`; score clamped 0–100; `events_counted` 0 on default; no ownership check — `routes/parties.py:47`, `services/reliability.py:49`
- §3.9 — insert — mismatch — payout create: event need not belong to organizer, duplicates allowed, OCC guard runs after the event-status check — `routes/payouts.py:34`
- §3.9 — insert — ambiguity — payout exposes `reserve_rate` as a fractional number — `services/payouts.py:70`
- §3.9 — insert — ambiguity — mark-eligible precondition order, write-back only on success; hold recomputes nothing — `routes/payouts.py:103`
- §3.9 — revise — ambiguity — approval tests stored `net_amount_cents` with no recompute — `routes/payouts.py:150`
- §3.9 — insert — ambiguity — reserve release permitted from any status, doesn't move status, repeatable — `routes/payouts.py:177`
- §3.9 — insert — ambiguity — event report is ownership-scoped for Organizer — `routes/events.py:209`
- §4 — revise — mismatch — ticket-type create row said "on a DRAFT or ONSALE event"; impl accepts any status — `routes/ticket_types.py:26`
