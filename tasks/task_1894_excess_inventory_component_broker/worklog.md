# Worklog — task_1894_excess_inventory_component_broker

## Step 1: Create Task Directory — 2026-08-14T23:17:04.304Z

Created `tasks/task_1894_excess_inventory_component_broker/` and `tasks/task_1894_excess_inventory_component_broker/workspace/` (index 1894 pre-assigned by pipeline invocation; Step 1 was already done before this orchestrator started).

## Step 2: Generate Scaffold — 2026-08-14T23:45:49.000Z

All three scaffold artifacts are generated, on disk, and lint-clean.

**Files written** (under `/home/ubuntu/github/CodingPRD/tasks/task_1894_excess_inventory_component_broker/`):
- `SCAFFOLD.yaml` — 1213 lines; top-level keys: scenario, domain_name, api_prefix, complexity_profile, response_envelope (FIXED §1.0 block verbatim), entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles. No `scaffold_difficulty_design` / `scaffold_corner_design` keys.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1385 lines; single top-level key `scaffold_difficulty_design`.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 2141 lines; single top-level key `scaffold_corner_design`.

**Scaffold surface:**
- 11 entities: Seller, Customer, StorageBin, BuyOffer, Lot, ConsignmentAgreement, MarketPriceSnapshot, Listing, SalesOrder, EscrowEntry, ReturnCase (9 common_fields entities + 2 append-only).
- 6 state machines: BuyOffer (branching inspect PASS/FAIL fork), Lot (posture-derived + QUARANTINED override), Listing (cyclic ACTIVE↔PAUSED), SalesOrder (branching cancel/refund), ConsignmentAgreement (terminate + clock-sweep expiry), ReturnCase (approve/reject fork).
- 9 calculations, 10 ordered validations, 53 endpoints (incl. `POST /_clock/set_current_utc` with pinned default `2026-08-01T00:00:00Z`), 35 error codes, 5 roles (BrokerOps/Inspector/FinanceAdmin opaque; Seller/Customer entity-backed), 1 OCC concurrency rule (`listing-update-stale-version` on PATCH /listings/{id}, ERR_STALE_VERSION 412).
- Archetype: pricing engine + workflow orchestration; layers: optimistic concurrency, dual-variant calc, cascading side effects, rate/threshold triggers.

**Test targeting:**
- §1.8: 18 instances (2 per each of the 9 difficulty rules) — e.g., dual-variant Lot carrying value (straight-line 72603 vs mark-to-market 93500) and provisional-vs-final order pricing (12500 vs 11519); pinned escrow-split rounding order (BROKER_FEE -17279 / SELLER_PAYOUT -97911); depth-3 settle cascade (SalesOrder→Lot→Listing plus EscrowEntry→Seller) vs depth-3 snapshot cascade (Snapshot→Lot→Listing); state-vs-fiscal and safety-vs-constraint priority conflicts; 90-day age boundary and exact escrow funding boundary; half-open consignment-window overlap vs aggregate bin-capacity exact fit; escrow-balance and lot-quantity compensating invariants.
- §1.9: 47 instances across all 9 claim-extraction sections (entities, state_machines, calculations, validations, endpoints, errors, roles, cross_cutting_layers, consistency_model).

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (53 endpoints, 11 entities, 18 + 47 instances, 679 calls scanned; one YAML flow-style bracket issue in grounds lists was fixed by quoting scalars, then re-linted clean.)

(Orchestrator note: first scaffold subagent spawn ended its turn during design deliberation without writing files; orchestrator resumed the same agent via SendMessage, which then wrote all three files and linted clean. No sibling task_* directories were touched.)

## Step 3: Copy Shared Files — 2026-08-14T23:46:12.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1894_excess_inventory_component_broker/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-15T00:04:07.000Z

The PRD was generated and written to `/home/ubuntu/github/CodingPRD/tasks/task_1894_excess_inventory_component_broker/workspace/PRD.md` (286 lines, 46 KB), ending at §5 with no audit footer. It was produced solely from the skill spec and this task's SCAFFOLD.yaml; the two withheld design-index files and all sibling tasks were never opened.

**Document structure** (domain-derived, per skill diversity rules):
- §1 Introduction — 2 paragraphs from the business-context angle (broker between excess-inventory sellers and constrained buyers)
- §2 ten subsections: RBAC with per-role `identity:` translations (BrokerOps/Inspector/FinanceAdmin opaque; Seller/Customer entity-backed), verbatim §2.2 envelope block, pagination, logical clock (startup default 2026-08-01T00:00:00Z, consignment expiry sweep), common resource properties (with explicit `updated_at`/`version` absence for MarketPriceSnapshot and EscrowEntry), integer-cents/round-half-up discipline, lot posture derivation, escrow ledger, listing-reprice OCC, and the 10-rung validation precedence ladder
- §3 eight subsections following the trade timeline (onboarding → buy-offer pipeline → lot custody/carrying value → consignment & market intelligence → listings → orders/escrow → settlement waterfall → returns), with all constants embedded in narrative (urgency premiums 0/10/25%, age discounts at 89/90–179/180 days, 0.20 volatility threshold with strict-greater semantics, 0.85 haircut, 1.10 recommended margin, 80% cost floor, 1–5000 bps fee range, pinned fee-first rounding order)
- §4 endpoint table: 53 rows, 4 columns, exact method/path match against scaffold
- §5 error catalogue: 35 rows, 2 columns

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields + common fields + endpoint inputs/query params/outputs: 71 required, 71 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] priority ladder: 10 rungs expressed in §2.10 prose, endpoint-specific orderings in §3.5/§3.6
- concurrency_rules[] OCC: 1 checked, 1 expressed (reprice write + expected_listing_version + ERR_STALE_VERSION/412 named; sequential framing only)
- state_machines[].transitions: 34 transitions across 6 machines, all from/to/precondition-error pairs and side effects expressed
- calculations[]: 9 checked, 9 fully expressed in precise prose (no pseudocode, no fuzzy words — mechanically verified)
- validations[] conditions: all matchable to their error_id in §2/§3 prose; all 35 error IDs present
- endpoints[].side_effects / applies_to: all expressed (settle waterfall, quarantine cascade, consignment pause cascade, snapshot propagation, cancel/refund cascades)
- entities[].fields[] structured content: defaults and nullability stated (payout_terms_days 30, urgency_tier STANDARD, inspection_result NONE, zero-opening balances, null-until-settle finals, suspect-flag false at conversion)
- sibling-branch symmetry: accept/reject/cancel, PASS/FAIL, both cancel states, both consignment endings, both settlement modes, both carrying-value variants — equal density
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 350
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional verifications: §2.2 block matches `section-2.2-response-structure.md` byte-for-byte (including `req_RANDOMALPHANUM123456` and the empty `"data": { }`); all 34 state enum values and all category enum values appear as exact backticked strings; snapshot list's `observed_at`/`created_at` descending sort is stated as the explicit exception to the default `created_at` ascending order.

## Step 5: Generate Unit Tests — 2026-08-15T00:26:13.000Z

Done. Everything is written to disk and verified.

## Summary

**Task:** task_1894_excess_inventory_component_broker — unit test generation from design indices + PRD.

### Files written

`test_helpers/` (Stage 1, 9 files):
- `/home/ubuntu/github/CodingPRD/tasks/task_1894_excess_inventory_component_broker/test_helpers/types.py` — 9 status enums, role enum, 10 entity TypedDicts (append-only MarketPriceSnapshot/EscrowEntry correctly omit `updated_at`/`version`)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (37 methods) + `api_client` singleton
- `api_errors.py` — `ApiErrorId` (35 errors) + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions (append-only entities assert absence of `updated_at`/`version`) + `assert_lot_quantity_invariant`
- `factories.py` — payload factories for all creatable resources
- `constants.py` — urgency premiums, age buckets, volatility threshold/window, haircut, floor ratio, fee-bps bounds, clock start
- `test_users.py` — opaque-role shared headers + mandatory `make_seller_headers`/`make_customer_headers` entity-backed builders
- `fixtures.py` — composite helpers: offer pipeline stages, `create_lot` (full intake), `create_active_listing`, `place_order`/`fund_order_fully`/`advance_order_to_delivered`, `set_clock`/`post_snapshot`, `setup_listed_broker_owned_scenario` / `setup_listed_consignment_scenario`
- `__init__.py` — barrel export

`test_suite/` (Stage 2, 12 files): `conftest.py` + `test_01_counterparty_onboarding.py`, `test_02_buy_offer_pipeline.py`, `test_03_listing_lifecycle.py`, `test_04_pricing_calculations.py`, `test_05_escrow_and_settlement.py`, `test_06_quarantine_and_safety.py`, `test_07_consignment_agreements.py`, `test_08_returns.py`, `test_09_rbac_and_errors.py`, `test_10_capacity_and_order_constraints.py`, `test_11_records_and_intelligence.py`

### Test count: 90 (pytest-collected cleanly with PYTHONPATH=task dir)

- **Queue A (Difficulty): 34 tests** — 17 instances × 2 each
- **Queue B (Corner): 56 tests** — all 47 non-stub instances covered (several with 2 tests)

### Instances skipped: 1

- `Difficulty/cross_entity_state_dependency/return_approve_requires_order_delivered` — fails unique-derivability/reachability: its recipe creates the ReturnCase while the order is SHIPPED, but PRD §3.8 states "A `Customer` opens a case against one of their own orders — and only while that order is `DELIVERED`, failing with `ERR_ORDER_NOT_DELIVERED` otherwise", so the setup chain itself cannot be built via PRD-faithful API calls; the asserted approve-time outcome is unreachable. No placeholder emitted.

### Verification performed
- All 90 docstrings end with exactly one `Design:` tag; all tags resolve to real instances (no bogus/dual/untagged tags)
- Every PRD citation passes a whitespace-normalized verbatim grep of PRD.md (8-word anchor check)
- No `pytest.mark.skip`/`skipif`/`xfail`; no "scaffold" references in generated code
- `python -m py_compile` passes on all files; `pytest --collect-only` reports 90 tests

## Step 6: Generate Implementation — 2026-08-15T00:26:13.000Z

Implementation complete and verified. Summary:

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_1894_excess_inventory_component_broker/workspace/implementation/`:

| File | Contents |
|---|---|
| `start.sh` | Executable launcher; guards `pip install` behind a `python3 -c "import flask"` check (no-op on per-test reboots), then `exec python3 app.py` in the foreground |
| `requirements.txt` | `flask>=2.2` |
| `app.py` | Flask entry point; binds `0.0.0.0:$PORT` (default 10000); global request lock, auth `before_request`, `ApiError`/404/405/500 handlers emitting the scaffold error envelope |
| `core.py` | In-memory `Store` (dicts keyed by id, **no seeding**, starts empty every boot), logical clock (startup default exactly `2026-08-01T00:00:00Z`), full error-ID catalog, envelope helpers (`meta`/`response_type`/`data`, pagination `limit`/`offset`/`total_count`/`has_more`), auth (`X-User-ID`/`X-User-Role`, 5 roles), payload validators, pagination parsing |
| `calc.py` | All §1.3 calculations with exact `Fraction` arithmetic + round-half-up: urgency-premium provisional pricing, age-discount/volatility final settlement pricing (strict `> 0.20` threshold, `(t−30d, t]` window), pinned escrow split (fee rounded first, payout = remainder), dual carrying-value variants (straight-line 365-day decay / mark-to-market 0.85 haircut), recommended price (1.10×), posture derivation, bin occupancy, credit exposure |
| `serialize.py` | Exact per-entity representations; snapshots/escrow entries correctly omit `updated_at`/`version` |
| `routes_a.py` | Clock set + consignment expiry sweep, sellers, customers, storage bins (13 endpoints incl. list) |
| `routes_b.py` | Buy-offer pipeline (submit/accept/reject/cancel/receive/inspect/convert/initiate-return/mark-returned), lots (list/get/flag/quarantine/release), market price snapshots |
| `routes_c.py` | Consignment agreements (create/list/get/terminate with pause cascade), listings (CRUD + OCC-guarded PATCH + activate/pause/withdraw) |
| `routes_d.py` | Sales orders (create/list/get/deposit/fulfill/ship/deliver/settle/cancel), escrow ledger, return cases (open/get/list/start-review/approve/reject/issue-refund) |

## Endpoint count
54 endpoints — the full §1.5 endpoint table.

## Verification result
Server booted cleanly from fresh processes via `bash start.sh` (4 separate boots, each with empty state — confirming per-test-server isolation works). Three smoke suites totaling **87 checks, all passing**:
- Full broker-owned lifecycle: offer → accept → receive → inspect (provenance gate) → convert (bin capacity) → list → OCC reprice (412 on stale) → order (urgency pricing 231¢/unit) → partial+exact escrow deposits → fulfill/ship/deliver → settle at +100 days (5% age discount: 219¢/unit, refund 240¢, BROKER_REVENUE entry).
- Consignment flow: window validation (422 invalid / 409 overlap / touching admitted), seller mismatch, fee-bps range, activation gating (`ERR_NO_CURRENT_CONSIGNMENT_AGREEMENT`), fee snapshot frozen at creation, pinned split (fee 607 = round-half-up(606.5), payout 5458), seller balances, volatility dampener (spread 0.30 → 3% dampener; exactly-0.20 case noted non-triggering).
- Returns: OPENED→UNDER_REVIEW→APPROVED (refund = funded escrow, order→REFUND_PENDING)→REFUND_ISSUED (units reserved→returned, order REFUNDED).
- Quarantine: flag gates orders/activation (422), quarantine withdraws ACTIVE listings, blocks fulfill/settle (409 `ERR_LOT_QUARANTINED`), release restores IN_STOCK.
- Cascades: DEPLETED→listing SOLD_OUT, bin occupancy excludes DEPLETED, clock sweep expires agreements and pauses listings, credit-limit exact-equality admitted / 402 one cent over, RBAC and ownership scoping (401/403/404 precedence), pagination envelope.

## Step 7: Test/Implementation Diagnostic Loop — 2026-08-15

Iteration 1: 8-round parallel sweep (`--isolation per-test-server`), 83/90 passed in every round; identical 7-test failure set across all 8 rounds (no flakiness).

Diagnosis (PRD-First protocol):
- **Cluster A — floor-at-creation (4 tests)**: PRD §3.5 verbatim requires the cost floor to be checked at listing creation; the implementation does, so test setups creating below-floor listings (expecting 201) contradict the PRD sentence their own docstrings quote. A persisted below-floor listing is unreachable under PRD (cost basis immutable; create + reprice both floor-checked).
  - DELETED `test_03 TestCostFloor::test_activate_below_cost_floor_rejected` — asserted outcome (activation-time floor rejection) unreachable under PRD; unique-derivability collapse. Scaffold rule: Corner/validations/asking_below_cost_floor_rejected_on_activate.
  - DELETED `test_06 TestSafetyPrecedence::test_counterfeit_beats_cost_floor_on_activate` — precedence pair (counterfeit × floor at activation) requires co-existing violations PRD makes unreachable. Scaffold rule: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_listing_activate.
  - FIXED `test_03 TestCostFloor::test_activate_at_exact_cost_floor_admitted` — setup now creates at 8000 (≥ floor 6400), then reprices to exactly 6400; exact-floor admission assertions preserved.
  - FIXED `test_06 TestSafetyPrecedence::test_rejected_activation_leaves_listing_draft` — setup asking 6000 → 8000 (≥ floor); counterfeit-blocks-activation + stays-DRAFT assertions preserved.
- **Cluster B — timestamp string format (3 tests)**: PRD pins instants (§2.4 startup clock; §3.4 window echo) but never the string representation of `effective_from`/`observed_at`; §2.2/§2.5 "three fractional digits" convention supports the server's `.000Z`. Exact-string equality fails unique derivability.
  - FIXED `test_07::test_adjacent_window_touching_boundary_admitted`, `test_11::test_snapshots_returned_newest_first`, `test_11::test_snapshot_observed_at_reads_startup_clock` — exact-string equality relaxed to instant comparison via new `test_helpers/assertions.py::assert_instant_equals`; ordering and instant assertions preserved.

No implementation changes — the implementation was PRD-faithful on all 7 failures.

Suite now 88 tests (90 − 2 deletions).

Iteration 2: 8-round parallel sweep — all 8 rounds 88/88 passed. EXIT CONDITION MET.

## Step 8: Finalize PRD — 2026-08-15T00:42:36.000Z

Done. The patch is a single in-place revision; everything else in the step_7_diff traced to behavior PRD already pins.

## Summary

**File:** `/home/ubuntu/github/CodingPRD/tasks/task_1894_excess_inventory_component_broker/workspace/PRD_FINALIZED.md`

**Line counts / delta:** PRD.md 286 lines → PRD_FINALIZED.md 286 lines (0% line delta; one paragraph revised in place, +1 sentence).

### Changes (one edit total)

- **§2.4 — revise — inserted one sentence pinning the canonical serialization form of every emitted timestamp: ISO 8601 UTC with exactly three fractional digits, whole-second instants render `.000`, startup clock appears as `2026-08-01T00:00:00.000Z`, and echoed client-supplied instants (`effective_from`/`effective_to`) are re-serialized in the same form — `implementation/core.py:92-94` (`iso()`); emitter callsites `core.py:139`, `serialize.py:17-18, 99, 115-116, 130-131, 179`, `routes_a.py:60`.**

### No-edit items (PRD already determines behavior — kept verbatim)

- **§3.5 cost floor (the two deleted tests):** PRD already states all three check sites unambiguously — "The floor is checked when the listing is created, again whenever it is repriced, and once more at every activation" plus the activation paragraph's "Finally, the asking price must satisfy the cost floor" and §2.10's ladder (floor = 9th, after counterfeit/consignment). Implementation matches exactly: `_check_floor` in `create_listing` (`routes_c.py:183`), `reprice_listing` (`routes_c.py:238`), `activate_listing` (`routes_c.py:270`, last in the battery); formula `(cost_basis*4)//5` (`calc.py:228-230`) = "eighty percent, rounded down". The deletions were unreachable-premise fixture bugs (below-floor listings cannot persist under creation-time floor check), not PRD silence. No edit.

### Per-edit pre-edit search log

**Edit 1 (§2.4 timestamp serialization sentence)**
- (a) Subject: the wire representation of every timestamp the server emits (stamped fields, envelope meta timestamp, echoed client-supplied instants, clock response).
- (b) Paths enumerated and read/grepped: `core.py:92-94` (`iso()` — sole serializer, `%Y-%m-%dT%H:%M:%S.` + `%03d` ms + `Z`); `core.py:135-140` (`_meta` → `api_request_timestamp`); `serialize.py` in full (`_base` created_at/updated_at line 17-18; lot `received_at` line 99; agreement `effective_from`/`effective_to` lines 115-116; snapshot `observed_at`/`created_at` lines 130-131; escrow entry `created_at` line 179); `routes_a.py:60` (`current_utc`); grep over `routes_b.py`/`routes_d.py`/`app.py` for `iso(|strftime|isoformat|req_dt|parse_dt` — no other emission or echo paths (routes_b stamps `received_at`/`observed_at`/`created_at` via `now_dt()` at lines 209/313/318, all later serialized through `iso()`); `core.py:97-110` (`parse_dt` normalizes echoed instants to UTC before re-serialization). Cross-checked against relaxed assertions in `test_suite/test_07_consignment_agreements.py:86` and `test_suite/test_11_records_and_intelligence.py:79,81,106` and the new `test_helpers/assertions.py::assert_instant_equals`.
- (c) Wording adjustments: scoped the claim to "every timestamp the server emits" (verified universal — all 8 emission sites route through the one `iso()` function, so the universal is safe); explicitly named the only two client-echoed instant fields (`effective_from`/`effective_to`) rather than implying all request fields echo; pinned representation only (exactly three fractional digits, `.000` for whole seconds) and deliberately left accepted *input* formats under-determined, since Step 7 never exercised input parsing. Confirmed consistency with §2.2 ("three fractional digits" for `api_request_timestamp`) and §2.5 (same for `created_at`/`updated_at`) — the new sentence generalizes both without contradicting either.

**No-edit verification (floor) — search performed to justify non-edit:** subject = asking-price floor enforcement; enumerated `routes_c.py:58-64` (`_check_floor`), callsites at lines 183 (create), 238 (reprice, after staleness at 227 and state at 233), 270 (activate, after posture/counterfeit/consignment at 258-269), and `calc.py:228-230` (floor formula). §3.5 prose covers all three sites and their precedence ordering via §2.10's ladder (structural constraints 9th, matching floor-before-positivity at `routes_c.py:183-184`); no wording gap found.

## Step 9: Complete PRD — 2026-08-15T00:51:36.000Z

PRD_COMPLETED.md is produced and verified. Summary:

**File delta**
- Source: `/home/ubuntu/github/CodingPRD/tasks/task_1894_excess_inventory_component_broker/workspace/PRD_FINALIZED.md` — 286 lines, 46,919 chars
- Output: `/home/ubuntu/github/CodingPRD/tasks/task_1894_excess_inventory_component_broker/workspace/PRD_COMPLETED.md` — 289 lines, 49,410 chars (+3 lines, +2,491 chars)

**Counts**: 16 ambiguity-pins, 2 mismatch-revisions (18 changes total). No new sections; all edits are inline inserts/revisions plus one appended error-catalogue row.

**Changes** (one bullet each):
- §2.2 — insert — ambiguity — pinned undefined-path 404 and unsupported-method 405 (both `ERR_INVALID_REQUEST`) and unexpected-failure `ERR_INTERNAL` (500), in the standard envelope — app.py:40-50
- §2.3 — revise — ambiguity — pinned clamping (not rejection) of out-of-range `limit`/`offset`, 400 for non-integer values, meta echoing effective values, `created_at` ties broken by creation order (earliest first), and the exact `has_more` formula (`offset` + page size < `total_count`) — core.py:262-272, core.py:147-153, routes_a.py:94-97
- §2.4 — revise — ambiguity — clock set accepts any parseable instant (no forward-only constraint); pinned input-instant parsing: offsetless values read as UTC, offsets normalized to UTC, unparseable → `ERR_INVALID_REQUEST` — routes_a.py:41-48, core.py:97-110, core.py:252-258
- §2.4 — insert — ambiguity — consignment sweep recomputes a lot's posture once per expired agreement when several expire on the same lot — routes_a.py:50-59
- §2.8 — insert — ambiguity — escrow ledger entries stamped at the same instant read in the order they were written — routes_d.py:289-292, calc.py:180-191
- §2.10 — revise — mismatch — ownership vs existence: request-decidable ownership (identity vs path/body identifier) stays at rung 3, but ownership requiring the loaded resource is evaluated after that resource's existence check, so an unknown id surfaces its 404 first (impl loads-then-checks on get/cancel offer, get/deposit/cancel order, escrow-entries, return-case reads) — routes_b.py:94-96, routes_d.py:159-160, routes_d.py:305-306
- §2.10 — revise — ambiguity — within the existence rung: path identifiers left-to-right, then body foreign keys in the order the endpoint narrative names them (seller→lot on agreements, customer→listing on orders, offer→bin on convert) — routes_c.py:86-90, routes_d.py:84-89, routes_b.py:185-188
- §2.10 — revise — ambiguity — payload-shape validation (`ERR_INVALID_REQUEST`) positioned immediately after role authorization and before all later rungs — every handler's require_roles-then-body order, e.g. routes_d.py:77-81, routes_c.py:222-225
- §3.2 — insert — ambiguity — a payload-supplied `provenance_doc_url` on PASS is recorded onto the offer — routes_b.py:169-170
- §3.3 — revise — ambiguity — market-basis latest-snapshot selection: further ties after `created_at` go to the later-recorded snapshot — calc.py:37-41
- §3.3 — revise — ambiguity — flag-counterfeit permitted at any time, whatever the lot's current status (no state guard) — routes_b.py:262-268
- §3.3 — revise — ambiguity — `quarantine_note` is accepted but not persisted; no lot representation carries it — routes_b.py:273, serialize.py:85-106
- §3.4 — revise — ambiguity — snapshot list full ties (observed_at, created_at) broken in favor of the later-recorded snapshot — routes_b.py:332
- §3.5 — revise — ambiguity — same later-recorded tie-break for the recommended-price snapshot selection — calc.py:44-48
- §3.6 — revise — mismatch — cancellation books a `CUSTOMER_REFUND` for the negative of `escrow_funded_cents` whenever the funded balance is positive, in either pre-fulfillment state (PRD had said a `PENDING_ESCROW` cancel "simply releases the reservation"; impl refunds partially funded cancels too) — routes_d.py:267-273
- §3.7 — insert — ambiguity — fulfill evaluates the order's own state guard before the lot-quarantine guard — routes_d.py:193-197
- §3.7 — revise — ambiguity — settle checks DELIVERED state and quarantine in that order — routes_d.py:226-230
- §5 — insert — ambiguity — added `ERR_INTERNAL` (500) row to the error catalogue — app.py:48-50

Everything else verified as already uniquely pinned by the PRD: all 53 endpoint role assignments match the §4 table; all 35 catalogue error statuses match; all 9 calculations (floor, recommended, provisional, final-settlement, escrow split, straight-line, market basis, volatility, exposure) match exactly including half-up rounding points; all 6 state machines' transitions, guards, and cascades (settle waterfall entry order, quarantine withdraw cascade, consignment pause cascade, SOLD_OUT-on-DEPLETED propagation, posture derivation order) match; OCC staleness-outranks-state already pinned; the activate battery order already pinned; the rung-10 credit-vs-positivity order in order creation was left unpinned deliberately because it is unobservable (the exposure ≤ credit invariant makes the two errors mutually exclusive).

(Orchestrator close-out: final stability verification — all 8 `results.{1..8}.json` rounds independently re-confirmed `total=88 passed=88 failed=0 errors=0`. Pipeline complete; `workspace/PRD_COMPLETED.md` exists.)
