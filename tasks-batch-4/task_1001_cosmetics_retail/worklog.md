# Worklog — task_1000_cosmetics_retail

## Step 1: Create Task Directory — 2026-07-12T00:00:00.000Z

Created `tasks/task_1000_cosmetics_retail/` and `tasks/task_1000_cosmetics_retail/workspace/` (pre-assigned path; no index scan performed).

## Step 2: Generate Scaffold (Expert) — 2026-07-12T00:50:00.000Z

All three artifacts are generated and the lint is clean.

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints declared:    47
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     64
  Calls scanned (§1.8+§1.9):  634
```

## Files

- `SCAFFOLD.yaml`
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `SCAFFOLD_CORNER_DESIGN.yaml`

## What was generated (Expert band)

**Profile**: quota/allocation primary + pricing-engine secondary; layers = optimistic concurrency, cascading side effects, dual-variant calculation, selector policy; hybrid topology; parallel state-machine shape; peer roles; immediate consistency.

**12 entities**: Store, Product, Variant, InventoryLot, Customer, Promotion, Order, OrderLine, PointsLedgerEntry (append-only, `common_fields: false`), Artist, ServiceBooking, ReturnRequest.

**6 state machines**: Order **fulfilment** × Order **payment** (parallel dimensions on one row), ServiceBooking (**cyclic** CONFIRMED↔RESCHEDULE_PENDING, capped at 2 loops), ReturnRequest (**branching** APPROVE/DENY with disjoint side-effect sets), Variant launch gate (clock-driven SCHEDULED→ROUGE→VIB→PUBLIC→CLOSED), Customer tier (**cyclic** INSIDER↔VIB↔ROUGE).

**6 calculations**: `order_pricing` (PROVISIONAL vs FINAL variants; per-line bundle rounding pinned — 3×350 @15% = 891 not 892; pinned evaluation order tier-discount → GWP threshold → points), `tier_evaluation` (ROLLING upgrade-only vs CHECKPOINT downgrade-allowed), `points_accrual` (floor→multiplier→category bonus→cap), `refund_settlement` (single HALF_UP per request + restocking fee + clawback), `shade_match_ranking` (selector: eligibility filter, score expression, tie-break to `created_at`, empty-pool fallback), `launch_allocation_draw` (waterfall launch-pool-first + tier window + per-customer cap).

**47 endpoints** (incl. `/_clock/set_current_utc` with the mandated `2026-05-01T00:00:00Z` default), **40 errors**, **28 ordered validations**, **4 roles**, **2 OCC rules** (`tester-conversion-stale-lot` on InventoryLot, `line-add-stale-order` on Order), **2 conserved-quantity invariants** (inventory units, points ledger), **2 overlap semantics** (Artist half-open + 15-min sanitation buffer vs Store aggregate 60-min BOPIS slot bucket).

**Difficulty design**: 9 rules × 2 instances = **18**, all with executable structured `setup_api_calls`/`trigger` chains and pre-computed literal asserts (verified by running the formulas: 891, 158, 93, 799/10, 400, 7500-boundary GWP, etc.).

**Corner design**: **65 instances** across all 9 claim-guide sections (1 `excluded_because` stub), covering CRUD/defaults/computed-field/immutability, invalid + terminal transitions, calculation filters and boundaries, every business error, RBAC denials + ownership, both OCC surfaces, conditional GWP-skip cascade, and immediate-consistency reads.

Note: endpoint count (47) and error count (40) run above the nominal Expert bands (20–32 / 18–30) — the scenario declares eight distinct sub-domains, and the surface is driven by FK reverse-reachability requirements. Entity, calculation and state-machine counts sit inside the band.

## Step 3: Copy Shared Files — 2026-07-12T00:51:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-12T01:00:00.000Z

PRD generated at `workspace/PRD.md` — 390 lines, ~9,600 words.

Sections: §1 Introduction (3 paras); §2 Global Specifications (11 subsections: RBAC/4 roles, Response Structure verbatim, Pagination, Logical Clock, Common Resource Properties incl. PointsLedgerEntry lacking updated_at/version, Money/Points/Rounding, Conserved Quantities, OCC on Shared Counters, Validation Precedence 1–8, Hygiene Classification, Nested Resource Retrieval); §3 Business Logic (9 subsections, all 6 calculations + all state machines rendered as prose, no pseudocode); §4 47-endpoint table; §5 41-error table.

Coverage audit: Field coverage PASS (93/93 entity fields, 59/59 request_body, 16/16 query_params, 1/1 path_params, 0 missing). Rule coverage PASS (28/28 validations, 2/2 OCC rules, 28/28 transitions, 6/6 calculations, 47/47 endpoint side_effects, 93/93 field structured content, 5 sibling-branch symmetry groups balanced, 41/41 error IDs in prose). Path purity PASS (643 backtick tokens in §3, 0 paths/methods leaked). §2.2 byte-identical to canonical source. Neither design index nor any sibling task was read.

Note from generator: scaffold's `refund_settlement` uses an intermediate `tier_share_cents` that is not a persisted ReturnRequest field; rendered in prose as "the tier share to withhold" rather than inventing a column.

## Step 5: Generate Unit Tests — 2026-07-12T01:30:00.000Z

Files: `test_helpers/` (1,824 lines) — __init__.py, types.py (20 enums + 11 entity TypedDicts; PointsLedgerEntry omits updated_at/version per append-only common_fields:false), api_client.py (45 endpoint methods), api_errors.py (40 error IDs + status map), assertions.py (per-entity + assert_lot_units_conserved / assert_points_ledger_conserved invariant checkers), factories.py, constants.py, test_users.py (per-instance make_customer_headers / make_artist_headers for the two entity_backed roles), fixtures.py (532 lines, 7 tiers). `test_suite/` (3,518 lines) — conftest.py + 9 domain test files, **100 tests**.

Coverage: Queue A (Difficulty §1.8) 18 instances × 2 tests = 36. Queue B (Corner §1.9) 64 non-stub instances × 1 test = 64. Audited: 100/100 carry exactly one Design: tag; zero unknown/stub tags; 0 citation failures (every docstring quote survives whitespace-normalised literal grep of PRD.md); no skip/skipif/xfail; pyflakes-clean; `pytest --collect-only` = exactly 100.

Skipped/deviations: `Corner/cross_cutting_layers/error_stale_order_version_covered_by_difficulty_design` is an `excluded_because:` stub, correctly not translated (its cross-reference resolves to a real §1.8 instance). No instance failed the PRD-first filter. One recipe-ordering deviation (`Corner/calculations/launch_cap_allows_exactly_the_cap_and_rejects_one_more`): recipe pre-created both trigger orders as DRAFTs before reserving either, but PRD §3.6 gate two counts held units across orders "whose fulfillment_status is anything other than CANCELLED" — which literally includes DRAFT — so the recipe's expected outcome is not PRD-derivable. Kept the rule and literals (cap 2, allowed at 2, rejected at 3) but sequenced create→reserve one order at a time.

Hazard fixed: pytest's default collection prefix is `test*` (not `test_*`), so factory `tester_conversion_payload` was collected as a bogus test (102 instead of 100). Renamed to `make_tester_conversion_payload`.

## Step 6: Generate Implementation — 2026-07-12T01:50:00.000Z

`workspace/implementation/` (21 files): start.sh (foreground, guarded dep-install, `exec python3 app.py`, binds 0.0.0.0:$PORT default 10000), app.py (blueprints, error handlers, global request lock), db.py (in-memory dicts + logical clock), errors.py (40-entry catalog), response.py (envelope), middleware.py (auth/validation/pagination/lookups/ownership), util.py (ISO-8601 ms, Decimal HALF_UP), routes/ (catalog, inventory, loyalty, promotions, orders, bookings, returns), services/ (pricing, loyalty, orders, booking), requirements.txt (flask).

47 routes, exactly matching the PRD §4 table.

start.sh boots: three consecutive fresh launches at 0.19s / 0.20s / 0.19s to first HTTP response; SIGTERM propagates through exec. Fresh boot = every table empty, clock at 2026-05-01T00:00:00.000Z. No seeding, no SQLite, no JSON dump, no /tmp cache.

Notable findings:
- Boot-time trap fixed: Python's HTTPServer.server_bind() calls socket.getfqdn() for a cosmetic server_name; reverse-DNS times out on this host making every boot 5.3s. Under per-test-server isolation that cost is paid hundreds of times and risks flaky restart failures. app.py neutralizes the lookup → 0.19s boots.
- Two ~60-assertion smoke suites pass, covering per-line bundle rounding, tier-discount→GWP→points ordering, PROVISIONAL vs FINAL under allow_partial clipping, launch waterfall, per-customer cap with cancel-restored headroom, refund settlement + clawback, rolling-vs-checkpoint tier asymmetry, hygiene strikes, artist buffered half-open intervals, BOPIS slot head-count, both OCC guards, both conservation invariants.
- One PRD ambiguity resolved in favor of PRD prose over SCAFFOLD priority numbers: at reserve, ERR_INSUFFICIENT_STOCK is checked before the points gates (PRD §3.6 gate order), even though scaffold validations[].priority lists points first.

Orchestrator note: Steps 5 and 6 were launched sequentially rather than concurrently (orchestrator error). Physical test-blindness for Step 6 was replaced by an explicit hard constraint in its prompt forbidding any read/list/grep of test_helpers/, test_suite/, and both design indices. The Step 6 subagent's file reads were limited to INSTRUCTION.md, SCAFFOLD.yaml, PRD.md.

## Step 7: Run Tests and Iterate — 2026-07-12T02:10:00.000Z

All 100 tests pass in all 8 parallel rounds, confirmed across two consecutive sweeps (16/16 clean rounds).

**Iterations run: 3 sweeps** (1 diagnostic + instrumented reproduction, then 2 verification sweeps).

**Tests deleted: none.** No test failed a PRD coverage or unique-derivability check. The single failure found was transport-level, never reaching the application, so STEP 1 was never triggered.

### The one failure, and why it was not an implementation bug

Sweep 1 showed `test_stale_order_version_on_a_second_line_add` failing in 2 of 8 rounds with:

```
requests.exceptions.ConnectionError: ('Connection aborted.', BadStatusLine('POST /orders HTTP/1.1\r\n'))
```

The client read back its own request line as the HTTP status line — the signature of a TCP self-connect (simultaneous open on loopback). Root cause, established from evidence:

- The runner allocates the server's port via `bind(("127.0.0.1", 0))` (`port_utils.py:206`) — so the server lives on an OS ephemeral port (observed: 52444–52451, sequential). The pytest client's outbound sockets draw source ports from that same sequential pool.
- `--isolation per-test-server` SIGKILLs and reboots the server before every test (`pytest_plugin.py:_restart_server`), leaving a ~1s window with no listener.
- A request issued into that window whose source port collides with the destination port connects to itself and echoes the request back. `requests` defaults to `max_retries=0`, and POST is non-idempotent so urllib3 will not auto-retry it — which is why the failure always landed on a POST.

Instrumented `start.sh` to capture server output across a full sweep: 808 server boots, zero tracebacks, zero EADDRINUSE, zero abnormal exits. The request never reached the app. Implementation logic was clean throughout (100/100 in 6 of 8 rounds even before any fix).

### Fixes applied to `test_helpers/`

- **`test_helpers/api_client.py` — `ApiClient.__init__` / new `_harden_transport()`**: mount an `HTTPAdapter` with a bounded urllib3 `Retry` (`connect=5, read=5, backoff_factor=0.2`) so a request fired into the restart window redials on a fresh connection (fresh source port), clearing the self-connect.
  - `status_forcelist=()` / `status=0` — no HTTP status is ever retried, so every error_id, 4xx and 412 assertion still sees the first response the server sent. Verified: a `GET /stores/<unknown>` landed exactly once server-side and returned ERR_STORE_NOT_FOUND.
  - A genuinely down or broken server fails every attempt, so this cannot hide an implementation defect — it only absorbs transport noise.

### Fixes applied to `implementation/`

- **`workspace/implementation/start.sh`**: no behavioural change; restored `exec python3 app.py` after diagnostics and documented why `exec` is load-bearing (the runner reaps the server by SIGKILLing the PID holding the listening socket; a surviving wrapper shell would leak one process per reboot).

**No implementation logic was changed — none was needed.** No test_suite/ fixes. Incidental cleanup: killed 8 stray leaked app.py servers from earlier runs; removed temporary instrumentation.

## Step 8: Finalize PRD — 2026-07-12T02:20:00.000Z

**Result: ZERO PRD edits. `workspace/PRD_FINALIZED.md` is a byte-identical copy of `workspace/PRD.md`** (md5 b02b94ece990823f970426e6cd6f3b9d for both). 389 → 389 lines, 0.0% delta.

Justification per <step_7_diff> item:

- **Item 1 — test_helpers/api_client.py retry adapter → NOT a PRD silence.** Subject: whether the API contract has client-visible content about connection retries/idempotency/status-driven retry. Paths enumerated: test_helpers/api_client.py:3-49 (HTTPAdapter + urllib3 Retry mounted on session); grepped PRD.md and all of implementation/ for `retry|connection|port|restart|process` — zero hits in PRD; implementation has no retry, keep-alive, connection-lifecycle, or request-dedup logic anywhere. The fix lives entirely below the HTTP layer (redials a TCP self-connect that never delivered a request); status_forcelist=()/status=0 mean no server response is ever retried. No client-observable endpoint/error/transition is affected. Pinning anything would manufacture a requirement the impl does not exhibit.
- **Item 2 — implementation/start.sh (`exec python3 app.py`) → NOT a PRD silence.** Subject: server launch/process-lifecycle contract. Step 7 records "no behavioural change". This contract is already fully determined — but by INSTRUCTION.md (line 11 foreground, line 18 PORT default 10000, line 21 use exec, line 41 shows `exec python3 app.py` verbatim), not the PRD. PRD.md is scoped to business rules and deliberately says nothing about process management; adding a launch section would be a new section, out of scope, redundant.

Cross-check: Step 7 reported zero test deletions, zero test_suite/ fixes, and zero implementation logic changes — no test was found non-derivable from PRD, and no business rule moved away from what PRD.md specifies. Both surviving diff items are confined to the transport and process layers, so there is no PRD-silence or PRD/impl mismatch to pin.

## Step 9: Complete PRD — 2026-07-12T02:30:00.000Z

`workspace/PRD_COMPLETED.md` written. Lines 389 → 390 (+1; the single new line is a row appended to the §5 error table — every other edit is an in-paragraph insert/revision, no new sections/paragraphs). Chars 64,567 → 71,603 (+7,036).

**22 changes: 19 ambiguity-pins, 3 mismatch-revisions.**

- §2.1 RBAC — insert — ambiguity — Customer list endpoints silently scoped to own records; foreign `customer_id` (or foreign `order_id` on /order-lines) filter → ERR_FORBIDDEN_OWNERSHIP — routes/orders.py:136-139,199-207, routes/loyalty.py:97-100, routes/bookings.py:164-167, routes/returns.py:107-111
- §2.3 Pagination — insert — ambiguity — non-integer / out-of-range limit/offset → ERR_INVALID_REQUEST — middleware.py:115-131
- §2.4 Logical Clock — revise — **mismatch** — "Nothing reads the host wall clock" is false: api_request_timestamp, created_at, updated_at come from host time; only domain deadlines/stamps use the logical clock. Also: clock may be set backwards, gates never roll back, advanced_variant_ids in creation order — util.py:18-21, db.py:47,57, routes/catalog.py:40-85
- §2.9 step 5 — revise — **mismatch** — body-reference-existence endpoint list omitted the shade finder's store_id, the promotion's bundle_variant_ids, and the booking's linked_order_id — routes/catalog.py:264-266, routes/promotions.py:62-65, routes/bookings.py:110
- §3.1 Stores — insert — ambiguity — region_code validated only as non-empty string (length never enforced); status accepted at creation — routes/catalog.py:96-100
- §3.1 Variants — insert — ambiguity — discontinued variant on an order's initial lines is accepted (refusal lands at reserve); PATCH /variants writes launch_status verbatim with no transition check — routes/orders.py:85,113, routes/catalog.py:238-239
- §3.1 Variants — insert — ambiguity — the three launch instants are optional (null → gate never fires); per_customer_cap recorded on every variant, limited or not — routes/catalog.py:180-186, 52-53
- §3.2 Lots — insert — ambiguity — launch_reserved_units > units_received → ERR_INVALID_REQUEST, raised before store/variant resolution — routes/inventory.py:33-37
- §3.2 Testers — insert — ambiguity — `units` is a required integer ≥ 1 — routes/inventory.py:86
- §3.3 Shade Finder — insert — ambiguity — undertone/depth_index/finish_pref required, depth bounded 1–12; store_id naming no store → ERR_STORE_NOT_FOUND — routes/catalog.py:260-266
- §3.3 Shade Finder — insert — ambiguity — `data` is the bare Variant resource; the score is not returned — routes/catalog.py:294
- §3.4 Customers — insert — ambiguity — email uniqueness not policed; initial_tier written verbatim (never re-derived); lifetime_spend_cents always starts at 0; hygiene_strikes 0 / return_privilege ACTIVE — routes/loyalty.py:33-56
- §3.4 Ledger — insert — ambiguity — a missing ledger entry answers with the generic ERR_NOT_FOUND (404) — middleware.py:196-200
- §5 Error Catalogue — insert — ambiguity — added the ERR_NOT_FOUND | 404 row — errors.py:44
- §3.5 Promotions — insert — ambiguity — gift_variant_id optional on every promo kind (a GWP/SAMPLE without one materialises nothing); bundle_variant_ids defaults to [] on BUNDLE / null otherwise, and an empty member list never qualifies — routes/promotions.py:50-59, services/pricing.py:47-48, services/orders.py:205,221
- §3.5 Order creation — insert — ambiguity — `lines` required but may be empty; a pickup_slot_start on a SHIP_FROM_STORE order is stored unvalidated — routes/orders.py:52-73
- §3.5 Line addition — insert — ambiguity — returns the re-quoted Order (200), not the new OrderLine — routes/orders.py:176-179
- §3.6 Allocation — insert — ambiguity — a variant with no lot at the store = zero drawable units; clipped lines survive at quantity 0 rather than being deleted — services/orders.py:88-92,147-169
- §3.6 Gift materialisation — insert — ambiguity — "drawable stock" = the gift lot's general pool net of this reservation's own draws, and must cover the full gift_quantity; the gift line draws into reserved_units; sample promotions materialised in created_at order — services/orders.py:205-227, services/pricing.py:71-77
- §3.7 Fulfilment — insert — ambiguity — wrong-channel actions → ERR_INVALID_ORDER_STATE; MARK_READY on an UNPAID order → ERR_INVALID_ORDER_STATE, not ERR_PAYMENT_NOT_CAPTURED — routes/orders.py:263-267
- §3.7 Accrual — insert — ambiguity — the EARN entry is appended unconditionally, even for 0 points — services/orders.py:263
- §3.7 Cancellation — insert — ambiguity — `reason` accepted and discarded (not persisted); an UNPAID cancelled order stays UNPAID — routes/orders.py:294, services/orders.py:305-309
- §3.8 Bookings — insert — ambiguity — an INACTIVE artist → ERR_INVALID_REQUEST; artist/store pairing not checked; the calendar conflict is tested before ERR_BOOKING_ORDER_MISMATCH — routes/bookings.py:112-127
- §3.8 Rescheduling — insert — ambiguity — the state gate precedes the max-reschedule gate; a proposal is not conflict-checked (only acceptance is) — routes/bookings.py:191-198
- §3.9 Return creation — insert — ambiguity — the owning order must be PICKED_UP/SHIPPED, else ERR_INVALID_RETURN_STATE, checked ahead of the four policy gates — routes/returns.py:52-53
- §3.9 Return decision — revise — **mismatch** — "re-run at decision time" narrowed to approval time; a denial never re-checks quantity — routes/returns.py:138-152
- §3.9 Settlement — insert — ambiguity — the tier share is 0 when the order's subtotal_cents is 0 (no division) — services/pricing.py:194-199

## Final Verification Sweep (orchestrator) — 2026-07-12T03:05:00.000Z

Step 7's subagent had removed its `results.*.json` artifacts on exit, so the orchestrator re-ran the 8-round parallel sweep to regenerate them and independently confirm green. Result: results.{1..8}.json all **100/100 PASS** — ALL 8 ROUNDS GREEN.
