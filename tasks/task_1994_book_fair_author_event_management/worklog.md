# Worklog — task_1994_book_fair_author_event_management

## Step 2: Generate Scaffold — 2026-08-15T06:28:33.128Z

Scaffold generation complete for task 1994. All three artifacts written to `/home/ubuntu/github/CodingPRD/tasks/task_1994_book_fair_author_event_management/` and `scaffold_lint.py` reports **clean lint** (962 recipe calls scanned, 0 violations, all FKs reverse-reachable).

## Counts

| Artifact | Metric | Value |
|---|---|---|
| SCAFFOLD.yaml | Entities | 14 |
| | State machines | 13 (59 transitions) |
| | Calculations | 8 |
| | Validations | 38 priority-ordered rows |
| | Endpoints | 90 |
| | Error codes | 38 (all referenced by ≥1 validation/transition) |
| | Roles | 6 (Organizer/Cashier/LineStaff opaque; SchoolCoordinator/PublisherRep/AuthorRep entity_backed:Party with kind + scope checks) |
| | Concurrency rules | 3 (agreement counter, booking counter, recon recount — all OCC on parent version, 412) |
| §1.8 | Instances | **21** (dual_variant 2, combinatorial 3, non_linear_SM 3, cascade 2, priority_conflict 2, boundary 2, cross_entity 3, overlap 2, invariant 2) |
| §1.9 | Instances | **52** (50 active + 2 excluded_because stubs), spanning all 9 taxonomy sections |

## Notable design decisions

- **Complexity profile**: primary `ledger_reconciliation` + secondary `temporal_windowing`; flat topology (FK references, per skill's diversity guidance); `segregation_of_duties` role model (recon approver ≠ close-sales creator via `created_by_user_id`); logical clock with mandatory default `2026-08-01T00:00:00Z` and an agreement-only expiry sweep (bookings deliberately lazy-expire → `ERR_OFFER_EXPIRED`, agreements hard-sweep → `EXPIRED`).
- **Directive couplings implemented**: consignment terms flow into both publisher remittance (per-line `round_half_up` pinned before summation — 1647 vs 1648 divergence fixture) and school payout (tiered marginal share, CASH vs SCRIP 1.15× dual variants); pre-order allocation (tie-proof ordering: `created_at, qty, customer_name` — never id) feeds reconciliation variance and unsold-return waterfall (cap `floor(return_cap_pct × delivered)` consumed in RA `created_at` order, over-cap at reduced restocking rate); TICKETED-vs-FREE sessions gate the attendance-threshold honorarium bonus (`>=` boundary, FREE always 0).
- **Two interval geometries**: venue slots use buffered half-open `[start−setup, end+teardown)` (adjacency allowed, buffers extend occupancy); signing sessions use closed-interval aggregate floor capacity (touching windows count as overlap, sum ≤ fair capacity, equality admitted).
- **Depth-3 cascade**: fair cancel → booking CANCELLED (kill fee 25%/50% by state) → session CANCELLED → ticket VOIDED, each link caused by the previous transition; a depth-2 counter-example (RA confirm-credit → stock counters → fair totals) pins snapshot non-propagation into CALCULATED payouts.
- **Replay-verified numbers**: every numeric assert pre-computed (e.g., payout net exactly 200000 → share 40000/cash 40000/scrip 46000; remittance 1647 vs prohibited 1648; kill fee 5000; return credits 3000/1080/4080).
- One semantic fix during replay: `provisional_lines` recompute from current counters on each counts call (not frozen at close) so damage-during-RECONCILING is the sanctioned shrink-absorption path, exercised by the variance-tolerance corner instance.

## Step 3: Copy Shared Files — 2026-08-15T06:29:05.536Z

Copied ./INSTRUCTION.md → tasks/task_1994_book_fair_author_event_management/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-15T06:45:39.731Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1994_book_fair_author_event_management/workspace/PRD.md`. The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or referenced.

## Summary

**Output**: 371 lines, `workspace/PRD.md`

**Section list**:
- §1 Introduction (2 paragraphs — business context + system qualities)
- §2 Global Specifications (11 subsections): 2.1 RBAC, 2.2 API Response Structure (byte-identical verbatim block, verified), 2.3 Pagination, 2.4 Resource Identity/Timestamps/Versioning, 2.5 Logical Clock & Offer Expiry, 2.6 OCC, 2.7 Monetary Precision & Rounding Doctrine, 2.8 Two Overlap Regimes (half-open venue vs closed-interval floor geometry), 2.9 Validation Pipeline & Priority Ordering, 2.10 Party-Scoped Operations, 2.11 Derived Fair Totals & Snapshot Semantics
- §3 Business Logic & Workflows (9 subsections, organized along the fair lifecycle): 3.1 Parties/Venues/Scheduling, 3.2 Consignment Negotiation, 3.3 Inventory/Delivery/Damage, 3.4 Author Booking/Travel/Sessions, 3.5 Signing-Line Operations, 3.6 Preorders/Allocation/Sales, 3.7 Reconciliation/Remittance, 3.8 Unsold Returns, 3.9 Honoraria/Payout/Promotion
- §4 Endpoint Definitions (4-column table, 90 rows) — mechanically verified to match the scaffold's endpoint set exactly
- §5 Error Code Catalogue (2-column table, 38 rows) — verified to match scaffold error ids and HTTP statuses exactly

**Hard contract results**:
- Contract 1 (field coverage): 106 required identifiers (entity fields + endpoint inputs + query params + common fields), 106 present, 0 missing
- Contract 2 (rule coverage): all 13 state machines' transitions (from/to, preconditions + error ids, side effects), all 8 calculations (pinned rounding orders, tier constants rendered as dollar thresholds, worked examples for remittance 1,647-vs-1,648 and scrip 40,000-vs-46,000), all 3 OCC rules (write op + `expected_*_version` + `ERR_STALE_VERSION`/412), all 28 validation rules with the priority ladder in §2.9 plus pinned endpoint-local orderings in §3 (tender state-before-fiscal; admit state→safety→referential; recon approve SoD-before-variance), cross-entity cascades (fair cancel links 1a/1b/2/3, session reconcile bonus bubble-up bumping booking version, confirm-credit's deliberate non-refresh of a CALCULATED payout), sibling-branch symmetry (counter/accept mirrors, ALLOCATED/CONVERTED_BACKLIST, TENDERED/DRAFT void, kill-fee schedule, CASH/SCRIP)
- Contract 3 (§3 path purity): 634 backtick tokens scanned, 0 path/method violations
- All 46 state values, 64 enum values, 6 role names present verbatim; all 38 error ids mentioned in §1–§3 prose

**Ambiguities noticed** (inherent to the scaffold, resolved conservatively):
1. `StockLine.qty_on_hand_counted` — entity says "null until counted" but no endpoint side_effect explicitly stamps it; the PRD states the counts call stamps it (the only natural write path).
2. `POST /stock-lines` same-fair agreement constraint exists in the entity field description but no validation entry nominates an error id for it (`ERR_LINE_FAIR_MISMATCH`'s applies_to excludes it); the PRD states the rule without pinning an error.
3. `SaleTransaction` lists `TENDERED` as a terminal state yet has a `TENDERED → VOIDED` transition; the PRD describes the transitions without asserting TENDERED lockdown.
4. `complexity_profile.error_code_count` says 28 but the catalog holds 38 — the PRD documents all 38. Endpoint count (90) matches.
5. Initial value of `version` is unspecified in the scaffold; the PRD deliberately does not pin one.
6. Signing-ticket issuance has no session-state gate in the scaffold (capacity only); the PRD does not invent one.

## Step 5: Generate Unit Tests — 2026-08-15T07:43:23.763Z

Note: the Step 5 subagent's first turn ended after writing `test_helpers/` + `conftest.py` but before any `test_*.py` files; the orchestrator resumed the same agent (context intact) via SendMessage and it completed the suite. Final summary below is the completed turn's report.

## Summary

Generated complete test infrastructure for `task_1994_book_fair_author_event_management`.

### Counts
- **Queue A (Difficulty)**: 21 instances total — **21 emitted** (each with ≥2 tests), **0 skipped**.
- **Queue B (Corner)**: 52 instances total, of which 2 are `excluded_because:` stubs (correctly not translated: `immediate_visibility_after_tender`, `version_increments_on_every_mutation`). **50 non-stub instances emitted** (each with ≥1 test), **0 skipped**.
- **Total**: 105 test functions across 11 test files. All compile; all tags resolve to real instances; every docstring carries a verbatim PRD citation plus exactly one `Design:` tag.

### Test files (`test_suite/`)
- `conftest.py` — exposes `api` + per-role header fixtures
- `test_01_parties_fairs_lifecycle.py` (12 tests) — party CRUD, fair lifecycle, venue-slot overlap
- `test_02_negotiation_and_occ.py` (8 tests) — agreement/booking counters, OCC 412, rounds cap, expiry sweep, duplicate agreement
- `test_03_inventory_stock.py` (10 tests) — stock-line create/commit/deliver/damage, FK-filtered listing
- `test_04_sales_tendering.py` (11 tests) — tender state-vs-fiscal priority, markdown band, stock availability, tender-short, void compensation, copy conservation
- `test_05_preorders_allocation.py` (6 tests) — preorder window, allocation order/exact-fit/empty-stock, fulfill
- `test_06_signing_line.py` (18 tests) — session open gates, floor capacity, admit 3-check order, no-show sweep, signing bonus threshold, entitlement conservation
- `test_07_reconciliation.py` (11 tests) — close-sales spawn, provisional-vs-final variance, damage absorption, SoD, counts OCC, dispute-recount cycle, per-line rounding remittance
- `test_08_returns.py` (8 tests) — return gates, waterfall cap boundary, depth-2 cascade + snapshot staleness
- `test_09_payout_settlement.py` (10 tests) — cash-vs-scrip variants, marginal tier boundary, revision loop, travel cap + settle math, fair-cancel depth-3 cascade
- `test_10_auth_rbac.py` (9 tests) — missing headers, role denials, party existence/kind/scope
- `test_11_promotion_media.py` (4 tests) — embargo boundary, cumulative promo budget gate

### Helper files (`test_helpers/`)
- `__init__.py` (barrel export), `types.py`, `api_client.py` (one method per endpoint), `api_errors.py` (38 error IDs registered), `assertions.py` (per-entity + copy-conservation invariant), `factories.py`, `constants.py`, `test_users.py` (shared constants + per-instance entity-backed builders), `fixtures.py` (tiered composites: `make_fair_open`, `make_reconciling_fair`, `make_accepted_reconciliation`, etc.)

### PRD coverage gaps honored
None — every non-stub instance passed the PRD-first two-condition filter. The PRD's §2/§3 prose carries verbatim, uniquely-deriving rules for every assertion emitted (including the pinned 1647 remittance example, the kill-fee schedule, the tiered share with the 40000/46000 worked example, and the half-open-vs-closed interval contrast). The two corner stubs (`immediate_visibility_after_tender`, `version_increments_on_every_mutation`) were correctly skipped per spec — their assertions are owned by the cited difficulty instances.

## Step 6: Generate Implementation — 2026-08-15T07:43:23.763Z

Implementation complete and verified with end-to-end smoke tests (full fair lifecycle), edge-case tests (admit ordering, window/referential precedence, kill-fee cascade, round caps), and a fresh-boot state-wipe check.

## File list (all under `/home/ubuntu/github/CodingPRD/tasks/task_1994_book_fair_author_event_management/workspace/implementation/`)

- `start.sh` — executable launcher; guarded install (`if ! python3 -c "import flask"`), then `exec python3 app.py`
- `requirements.txt` — `flask>=3.0,<4`
- `app.py` — Flask app, blueprint registration, `ApiError`/404/405/500 envelope handlers, global request-lock middleware, `app.run(host="0.0.0.0", port=$PORT or 10000, threaded=True)`
- `db.py` — 14 in-memory dict stores (empty at boot, nothing seeded), logical clock pinned at `2026-08-01T00:00:00Z`, monotonic 3-fractional-digit ISO-8601 UTC timestamp source (guarantees unique, strictly ordered `created_at`)
- `errors.py` — all 37 catalog IDs with their HTTP statuses
- `response.py` — scaffold envelope: `meta{api_request_id, api_request_timestamp}` + `response_type` + `data`; lists add `limit/offset/total_count/has_more` into `meta`
- `middleware.py` — auth ladder (headers → role membership → party existence → kind match) and `require_scope` for priority-6 party scoping
- `util.py` — shape validation (unknown-field rejection, int/pct/enum/date/datetime validators), `limit`/`offset` parsing (default 10, 1–100, offset ≥ 0), Decimal helpers (`ROUND_HALF_UP`, floor)
- `services.py` — domain logic (below)
- `routes_core.py` (clock, parties, fairs, venue slots), `routes_negotiation.py` (agreements, bookings), `routes_inventory.py` (stock lines, preorders, sales), `routes_signing.py` (sessions, tickets), `routes_finance.py` (reconciliations, returns, payouts, media blasts)

## Scaffold concern mapping

- **State machines (13)**: all transitions implemented with precondition order per the §2.9 ladder — target-entity state (8) before cross-entity gates (8), then OCC (9), safety (10), temporal (11–15), rounds (16), duplicate (17), capacity (18), physical (19), referential (20), fiscal (21–24), closing gates (25–28). Deep fair-cancel cascade runs slots → bookings (kill fees 0/25%/50% by state, half-up) → sessions → tickets → preorders; close-sales sweeps ALLOCATED preorders and spawns the Reconciliation stamped with the acting organizer's `X-User-ID`.
- **Calculations (8)**: pinned per-line-then-sum rounding for remittance and return-credit waterfall (verified the scaffold's 1647-vs-1648 discriminator), single-final-rounding tiered school share plus `round_half_up(share * 1.15)` scrip variant, threshold signing bonus with `>=` boundary, `min(travel_actual, travel_cap)` settlement, closed-interval floor-capacity vs buffered half-open venue-overlap regimes (both boundary behaviors tested).
- **OCC (3 rules)**: `expected_agreement_version` / `expected_booking_version` / `expected_reconciliation_version` → `ERR_STALE_VERSION` 412, checked at priority 9.
- **RBAC**: exact six roles; entity-backed roles resolve `X-User-ID` to a Party and enforce kind and scope (`ERR_PARTY_NOT_FOUND`/`ERR_ROLE_PARTY_KIND_MISMATCH`/`ERR_PARTY_SCOPE_MISMATCH`); segregation-of-duties gate runs before the variance gate on reconciliation approve.
- **Error catalog**: all 37 IDs wired with catalog HTTP statuses; workflow-pinned orderings honored (tender: fair-OPEN → line fair/DELIVERED → stock → markdown → tender-short; admit: payload-session state → fire-marshal cap → ticket-session mismatch; preorder: line-fair-mismatch at 20 before window-closed at 28). Agreement offer expiry via clock-set sweep + lazy access (returns `ERR_OFFER_EXPIRED` on counter/accept while transitioning the agreement to EXPIRED); bookings never auto-expire and surface `ERR_OFFER_EXPIRED` only.
- **Clock**: `POST /_clock/set_current_utc` returns `{current_utc, expired_agreement_ids}`; `current_utc` normalized to the 3-fractional-digit Z format.

## start.sh confirmation

`start.sh` runs `bash start.sh` from `./implementation/`, performs a no-op-guarded `pip install`, and `exec`s `python3 app.py` in the **foreground**, binding **0.0.0.0** on **`$PORT`** (default 10000). Verified booting via the exact evaluator invocation on the default port, and verified a kill-and-relaunch starts with a completely empty store.

## Step 7: Run Tests and Iterate — 2026-08-15T08:00:00.000Z

Clean 8-round parallel sweep achieved: **105/105 tests passing in every round, 0 failures, 0 flakes** (deterministic pass across all rounds).

## Summary

**Iterations run:** 2 sweeps (16 total rounds). First sweep: 4 deterministic failures in all 8 rounds. Second sweep after fixes: all 8 rounds green.

**Tests deleted:** None. Every failing test traced to a PRD-verbatim rule; no PRD-silence or unique-derivability deletions were warranted.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1994_book_fair_author_event_management/test_helpers/fixtures.py` — `make_fair_scheduled`: now passes `venue_key=fair["venue_key"]` into `make_confirmed_venue_slot`. Previously the slot payload always used the factory default `"GYM"`, so any test that created a fair with a non-default `venue_key` (e.g. `"CAFETERIA"`) issued a slot-create request that violates PRD §2.9 ("a venue slot's `venue_key` equals the linked fair's `venue_key`"), which the implementation correctly rejected with `ERR_VALIDATION`. Fixed `test_stockline_filtered_list_fk_reverse` and `test_preorder_line_from_other_fair_rejected`.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1994_book_fair_author_event_management/test_suite/test_02_negotiation_and_occ.py` — `test_default_clock_pins_offer_expiry`: assertion expected `"2026-08-04T00:00:00Z"`, contradicting PRD §2.4 ("Timestamps are ISO 8601 UTC with three fractional digits"). Corrected the expected value to `"2026-08-04T00:00:00.000Z"` (the §2.4-conformant serialization of the §2.5-pinned instant plus §3.2's `offer_expiry_hours`).
- `/home/ubuntu/github/CodingPRD/tasks/task_1994_book_fair_author_event_management/test_suite/test_07_reconciliation.py` — `test_reconciliation_dispute_recount_cycle`: the test created two fairs on the same default `venue_key="GYM"` with identical default slot windows, so the second slot hold correctly tripped `ERR_VENUE_CONFLICT` per PRD §2.8's half-open buffered overlap rule. Passed `fair_overrides={"venue_key": "CAFETERIA"}` for the second fair so both fair calendars are disjoint.

**Fixes applied to `implementation/`:** None. The implementation was already PRD-faithful on all four failure points — each failure was the implementation correctly rejecting a test-side request that violated a PRD-verbatim rule (venue_key equality, three-fractional-digit timestamps, per-venue-key slot conflicts).

## Step 8: Finalize PRD — 2026-08-15T08:10:00.000Z

## Step 8 Summary — ZERO edits; PRD_FINALIZED.md is byte-identical to PRD.md

**File:** `/home/ubuntu/github/CodingPRD/tasks/task_1994_book_fair_author_event_management/workspace/PRD_FINALIZED.md`

**Line counts / delta:** PRD.md = 370 lines, PRD_FINALIZED.md = 370 lines, 0% delta (md5 `4dd233989afa4d67640dbae136f636c3` for both).

**Rationale:** Every one of the three step_7_diff items is a test-side repair where the implementation already embodied a PRD-verbatim rule. PRD.md uniquely determines each touched behavior, so no edits were warranted and none were manufactured.

**Per-item verification (subject → impl paths enumerated → PRD determination):**

1. **test_helpers/fixtures.py `make_fair_scheduled` venue_key fix** — (a) Subject: a venue slot's `venue_key` must equal the linked fair's `venue_key`, rejected as priority-7 `ERR_VALIDATION`. (b) Impl paths enumerated: `implementation/routes_core.py:328-329` (equality check, `ERR_VALIDATION`), slot creation endpoint `routes_core.py:308-351` (only path that writes `venue_key`), list filter `routes_core.py:360`. (c) No wording needed — PRD §2.9 (line 108: "It also enforces that a venue slot's `venue_key` equals the linked fair's `venue_key`," inside the priority-7 `ERR_VALIDATION` paragraph) and §3.1 (line 126: "a `venue_key` that must equal the linked fair's `venue_key`") already pin the rule, the error code, and its ladder position verbatim. Pure fixture bug.

2. **test_02 `test_default_clock_pins_offer_expiry` `.000Z` fix** — (a) Subject: serialization format of `offer_expires_at` (and all timestamps). (b) Impl paths enumerated: `implementation/db.py:52-55` (`fmt_dt`, three fractional digits) and `db.py:41-49` (`now_iso`); every call site grepped and read — `services.py:390` (`offer_expires_at` = clock + hours), `services.py:30,39` (`created_at`/`updated_at`), `routes_core.py:55` (`current_utc`), `routes_core.py:344-345` (slot `start_at`/`end_at`), `routes_signing.py:84-85,214`, `routes_finance.py:548` (`embargo_until`), `response.py:13` (`api_request_timestamp`). All serialize with exactly three fractional digits, uniformly. (c) No wording needed — PRD §2.4 (line 76: "Timestamps are ISO 8601 UTC with three fractional digits") is an unrestricted global rule that accurately describes every enumerated path; §2.5 pins the startup instant and §3.2 pins `offer_expires_at` = clock + `offer_expiry_hours`, so the expected `"2026-08-04T00:00:00.000Z"` is uniquely determined. The old test contradicted §2.4; the fix conformed the test.

3. **test_07 `test_reconciliation_dispute_recount_cycle` CAFETERIA fix** — (a) Subject: buffered half-open venue-calendar overlap, scoped by `venue_key`, excluding `RELEASED` slots, evaluated at creation. (b) Impl paths enumerated: `implementation/services.py:179-191` (`venue_conflict`: `c_start < e and s < c_end` half-open intersection, skips `RELEASED` and foreign `venue_key`s), sole call site `routes_core.py:332-339` (create-only, raising `ERR_VENUE_CONFLICT`). (c) No wording needed — PRD §2.8 (line 100) explicitly pins the half-open buffered interval, the non-`RELEASED`/same-`venue_key` scoping, the `ERR_VENUE_CONFLICT` rejection, and the touching-endpoints exclusion; §3.1 (line 126) pins that the check runs at creation. The old test constructed a genuine same-venue overlap; the fix disjointed the venue keys.

**Conclusion:** A fresh implementer reading PRD.md already arrives at behavior identical to `implementation/` on every point the step_7_diff touched; PRD_FINALIZED.md is therefore an exact copy.

## Step 9: Complete PRD — 2026-08-15T08:22:34.309Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1994_book_fair_author_event_management/workspace/PRD_COMPLETED.md` produced.

## Summary

**Source vs output**: `PRD_FINALIZED.md` (identical to `PRD.md`) — 370 lines / 59,638 chars → `PRD_COMPLETED.md` — 370 lines / 63,337 chars. Char delta **+3,699**, line delta **0** (all 25 edits are in-paragraph; no sections added).

**Counts**: 26 ambiguity-pins, 10 mismatch-revisions (some paragraph edits carry one of each; bullets below are per-change).

### Mismatch revisions (PRD said X, impl does Y)
- §2.9 — revise — mismatch — generic "quantities must be positive" now excepts delivered `qty_delivered` and counted `qty_on_hand`, both of which may be zero — routes_inventory.py:129, routes_finance.py:74
- §3.2 — revise — mismatch — agreement `offer_expiry_hours` pinned as positive **integer** (was "positive number") — routes_negotiation.py:42
- §3.4 — revise — mismatch — booking `offer_expiry_hours` pinned as positive integer — routes_negotiation.py:51
- §3.5 — revise — mismatch — open-signing gate order changed from booking→window→fair to booking→fair→window (state legality before temporal, per the §2.9 ladder) — routes_signing.py:127-136
- §3.5 — revise — mismatch — issue cap: live entitlements "may reach but never exceed `capacity_seats`"; refusal only when count already equals cap (was "must remain below…issue that would reach the cap is refused") — routes_signing.py:209-211
- §3.5 — revise — mismatch — admit cap: ADMITTED count may reach `admit_concurrent_cap`; refusal only at equality — routes_signing.py:258-260
- §3.6 — revise — mismatch — markdown band is that of "that stock line's own consignment agreement" (was "the fair's `ACCEPTED` agreement" — wrong when multiple/non-accepted agreements exist) — services.py:211-217
- §3.7 — revise — mismatch — provisional lines cover `DELIVERED` **or `RECONCILED`** lines (was `DELIVERED` only; observable on post-dispute recount) — services.py:224-238
- §3.7 — revise — mismatch — replaced "never re-locked on the cycle": every approval out of `VARIANCE_REVIEW` re-computes and overwrites remittance, so a post-dispute re-approval (all lines already `RECONCILED`) re-locks it at zero — routes_finance.py:159-169, services.py:277-289
- §3.8 — revise — mismatch — RA creation now four gates in ladder order with the agreement-fair match (`ERR_LINE_FAIR_MISMATCH`) last, not folded into gate 1 — routes_finance.py:271-284

### Ambiguity pins (PRD silent, impl behavior now pinned)
- §2.3 — insert — non-integer/out-of-range `limit`/`offset` and negative `offset` → `ERR_VALIDATION` — util.py:151-170
- §2.4 — insert — `version` starts at 1 on creation — services.py:31
- §2.4 — insert — lenient datetime parsing: naive read as UTC, non-UTC offsets normalized — util.py:38-51
- §2.5 — insert — clock accepts any instant; no forward-motion enforcement — routes_core.py:52
- §2.9 — insert — explicit JSON `null` treated as absent (required→missing error; optional→ignored) — util.py:139-142
- §2.9 — insert — global rule: absent a pinned gate, creation of venue slots/agreements/stock lines/bookings/sessions/tickets/sales/media blasts is not gated on the parent entity's lifecycle status — routes_core.py:310, routes_negotiation.py:61/213, routes_inventory.py:39/296, routes_signing.py:44/202, routes_finance.py:527
- §3.1 — insert — fair create: wrong-kind `school_party_id` → `ERR_VALIDATION` (400) — routes_core.py:113-114
- §3.1 — insert — cancel `reason` validated as string but not persisted — routes_core.py:290
- §3.2 — insert — agreement create: wrong-kind publisher → `ERR_VALIDATION` (400) — routes_negotiation.py:73-75
- §3.2 — insert — accept after lapse → `ERR_OFFER_EXPIRED` + transition to `EXPIRED`; decline after lapse → lazy expiry then `ERR_INVALID_STATE` — routes_negotiation.py:183-186, 199-201
- §3.3 — insert — stock-line create: cross-fair agreement → `ERR_LINE_FAIR_MISMATCH` — routes_inventory.py:60-61
- §3.3 — insert — `isbn` validated as string only, no ISBN-13 format check — routes_inventory.py:52
- §3.3 — insert — delivery `qty_delivered` non-negative, zero permitted — routes_inventory.py:129
- §3.3 — insert — damage write-off only against a `DELIVERED` line — routes_inventory.py:156-157
- §3.4 — insert — booking create: wrong-kind author → `ERR_VALIDATION`; no uniqueness constraint on author+fair — routes_negotiation.py:225-227
- §3.4 — insert — booking round-cap boundary: counter legal only while `negotiation_round` < 4 — routes_negotiation.py:292-293
- §3.5 — insert — admit runs the ticket's own `ISSUED`-state check (`ERR_INVALID_STATE`) before the named trio — routes_signing.py:254-255
- §3.6 — insert — sale `lines` non-empty, positive `qty`, duplicate stock lines allowed and applied independently; `tendered_amount_cents`/`change_cents` null until tender — routes_inventory.py:278-322, 341-342
- §3.6 — insert — tender: non-`DELIVERED` line reported as `ERR_LINE_FAIR_MISMATCH` — routes_inventory.py:375-378
- §3.6 — insert — void when fair not `OPEN` → `ERR_FAIR_NOT_OPEN` — routes_inventory.py:411-412
- §3.7 — insert — spawned reconciliation starts with `counted_lines`/`variance_lines` empty, `total_abs_variance` 0, `remittance_cents`/`dispute_reason` null — routes_core.py:236-246
- §3.7 — insert — counts: empty `lines` accepted; variance entries shaped `{stock_line_id, expected_on_hand, qty_on_hand, variance}`; counted lines with no provisional expectation are stored/stamped but excluded from variance — routes_finance.py:61-119, services.py:241-260
- §3.7 — insert — with multiple payouts, the settle gate consults the first-created payout — routes_core.py:277-279
- §3.7 — insert — reconciliation accept/dispute scope passes for any publisher holding an `ACCEPTED` agreement on the fair — routes_finance.py:185-191
- §3.8 — insert — RA `lines` non-empty with positive `qty`; new authorization has `credit_cents` null — routes_finance.py:225-241, 289

**Verification**: all 25 touched paragraphs confirmed via diff; no new sections, no stale cross-references (gate-count phrasing updated consistently). Everything else in the PRD (endpoint table §4, error catalog §5, state machines, rounding doctrines, cascades, formulas and their worked examples) was checked line-by-line against the implementation and already matched uniquely, so it was left untouched.
