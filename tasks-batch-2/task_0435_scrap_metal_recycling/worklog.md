# Worklog — task_0435_scrap_metal_recycling

## Step 1: Create Task Directory — 2026-06-21T00:15:00.000Z

Created `tasks/task_0435_scrap_metal_recycling/` with `workspace/` subdirectory. Task index 0435 (next after existing max 0434). Scenario: Scrap Metal Recycling Yard.

## Step 2: Generate Scaffold — 2026-06-21T00:30:00.000Z

All three files are valid and the file split is correct:
- `SCAFFOLD.yaml` has §1.0–§1.7 keys (no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` has the single top-level `scaffold_difficulty_design` key
- `SCAFFOLD_CORNER_DESIGN.yaml` has the single top-level `scaffold_corner_design` key

The lint verdict is clean. The scaffold is complete and self-consistent.

### Summary

Generated a complete three-file scaffold for **task_0435_scrap_metal_recycling** (Scrap Metal Recycling Yard), all passing `scaffold_lint.py` with `VERDICT: clean lint`.

**Complexity profile:** Ledger-reconciliation primary archetype (spot-price intake valuation vs mill-settlement reconciliation) blended with Compliance/audit; flat entity topology, branching state-machine shape, segregation-of-duties role model, immediate consistency. Layers: dual-variant calculation, cascading side effects, rate/threshold triggers, optimistic concurrency. Sits in the Advanced band.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **9 entities:** Seller, CommodityPrice, ScaleTicket, TicketLineItem (immutable, `common_fields:false`), Payout, Container, MillShipment, HedgePosition, TheftReport
- **6 state machines:** ScaleTicket (DRAFT→WEIGHED→{RELEASED|REPORTED|HOLD↔WEIGHED}→PAID — branching with revert), Payout (PENDING→{SETTLED|VOID}), Container (STAGED→DISPATCHED→CLOSED), MillShipment (SHIPPED→SETTLED), HedgePosition (OPEN→CLOSED), TheftReport (OPEN→CLEARED)
- **2 concurrency rules** (OCC, 412): dispatch-stale-container, settle-stale-hedge
- **4 calculations:** ticket_spot_valuation (per-line-round-then-sum, pinned), mill_settlement_reconciliation (forward-looking expected vs final variance), rule_1099_issuance ($600/60000c cumulative cash threshold), hedge_realization_pnl (locked-vs-effective price, min-capped realization)
- **14 ordered validations**, **17 error codes**, **41 endpoints** (incl. reverse-reachability GETs and OCC-guarded writes; no test-driving `/_` endpoints needed — all setup reachable by composition)
- **5 roles** (all `opaque`): WeighMaster, PayoutClerk, YardManager, SettlementAccountant, ComplianceOfficer

**SCAFFOLD_DIFFICULTY_DESIGN.yaml:** all 9 Difficulty Rules × 2 = **18 instances**, each with executable `setup_api_calls` chains and pre-computed literal asserts (e.g., gross_valuation 11326c, mill expected 12382c, hedge P&L +16900c/-13000c, 1099 boundary at exactly 60000c).

**SCAFFOLD_CORNER_DESIGN.yaml:** **42 instances across 10 sections** (38 active test recipes + 4 `excluded_because:` stubs that point at named §1.8 difficulty instances), covering entity CRUD, invalid-from/terminal-lockdown transitions, calculation constants/boundaries, validation triggers, endpoint side effects, error catalog, RBAC cross-role denial, OCC stale-version, and immediate-consistency claims.

All formula-derived assertions were computed in code (per-line rounding order verified to diverge: 11326 vs 11325). YAML flow-sequence pitfalls (trailing `?` optionals, `[...]`-in-flow grounds, `$.data[0]` JSONPath) were quoted to keep the files parseable.

## Step 3: Copy Shared Files — 2026-06-21T00:31:00.000Z

Copied `INSTRUCTION.md` → `tasks/task_0435_scrap_metal_recycling/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-21T00:40:00.000Z

(First attempt died mid-response with a connection error before writing any file; respawned a fresh subagent which succeeded.)

All checks pass. The §2.2 block is verbatim, no fuzzy approximating words, and no pseudocode operators leaked into prose (formulas are translated to natural language). The PRD is complete and all three Hard Contracts pass.

### Summary

Generated `workspace/PRD.md` — a prose Product Requirements Document for the **scrap-metal-recycling** domain (api_prefix `/yard`), ~5,470 words / 246 lines.

**Structure:**
- **§1 Introduction** — 2 paragraphs framing the yard's material-and-settlement loop and compliance exposure.
- **§2 Global Specifications** — 8 subsections: RBAC (2.1), verbatim Response Structure (2.2), Pagination (2.3), Common Properties & Versioning (2.4), Monetary Precision/Rounding (2.5), Existence/Path Validation (2.6), Optimistic Concurrency (2.7), Validation Ordering (2.8).
- **§3 Business Logic** — 8 scattering-zone subsections organized by entity lifecycle: sellers/theft-prevention, commodity pricing/supersede, scale-ticket weigh, theft gate (hold/clear/release/report), payout & 1099 ledger, containers, mill shipment/settlement/hedge realization, hedge positions.
- **§4 Endpoint table** — 4 columns, all 42 endpoints.
- **§5 Error catalogue** — 2 columns, all 17 error codes.

**Coverage verification (all Hard Contracts PASS):**
- **Contract 1 (Field-Name Coverage):** All ~46 required identifiers appear verbatim in backticks. 0 missing.
- **Contract 2 (Rule Coverage):** All 9 entities, 6 state machines with from/to states + preconditions + cross-entity cascades; all 4 calculations (spot valuation per-line-round-then-sum, mill settlement reconciliation + variance, 1099 cash-threshold ledger with inclusive 60000-cent / $600 boundary, hedge realization P&L with effective-price and min-cap logic); all 14 validations matched to error IDs with explicit priority ordering; both OCC rules expressed. Calculations rendered in precise prose — no pseudocode, no fuzzy words.
- **Contract 3 (§3 Path Purity):** 312 §3 backtick tokens scanned; 0 path-leading, 0 bare-method, 0 method+path tokens.

All 17 error IDs and all enum/state values appear as exact strings; §2.2 emitted byte-verbatim with all three canonical placeholders intact.

## Step 5: Generate Unit Tests — 2026-06-21T00:55:00.000Z

All test modules import cleanly with the framework present, confirming every `test_helpers` symbol the suite references (api methods, fixtures, error IDs, validators) resolves. Generation is complete.

### Summary
Generated complete test infrastructure for `task_0435_scrap_metal_recycling`.

**test_helpers/ (9 modules)**
- `types.py` — status/role enums + entity TypedDicts (TicketLineItem correctly modeled append-only: `id` + `created_at` only, no `version`/`updated_at`)
- `api_client.py` — `ApiClient(GenericApiClient)`, one method per endpoint (all 40 endpoints)
- `api_errors.py` — `ApiErrorId` enum + HTTP status map, registered with the framework
- `assertions.py` — per-entity assertions + hedge/container invariant checkers
- `factories.py` — input-field-only payload factories per entity
- `constants.py` — `TIN_1099_THRESHOLD_CENTS = 60000` and price defaults
- `test_users.py` — shared role headers (all 5 roles opaque) + `make_*_headers(user_id)` builders for segregation-of-duties tests
- `fixtures.py` — composite setup (weighed/released tickets, payouts, shipments-with-hedge, cleared-hold-then-release, partial-realization)
- `__init__.py` — barrel export

**test_suite/ (conftest + 9 test files, 74 test functions)**
- Files 01–04: Queue A (Difficulty) — 18 instances, every one covered by ≥2 tests
- Files 05–09: Queue B (Corner) — all 38 non-stub instances covered by ≥1 test

**Instances skipped: 0 translatable instances skipped.** Every difficulty instance and every corner non-stub instance passed the PRD-first two-condition filter. The 4 corner `excluded_because:` stubs were correctly NOT translated; one stub (`errors/error_stale_hedge_version_excluded`) had a broken difficulty pointer but the live corner instance `cross_cutting_complexity_layers/settle_stale_hedge_version_rejected` independently covers `ERR_STALE_HEDGE_VERSION`.

**Verification:** all 74 tests collect; expected calc values (11326, 12382, 16900, -13000, -1382, 60000 boundary) recomputed and matched; no skip/skipif/xfail; no scaffold-leakage.

## Step 6: Generate Implementation — 2026-06-21T00:55:00.000Z

Built a complete Python + Flask in-memory implementation in `workspace/implementation/`.

### Files created (19)
`start.sh`, `requirements.txt` (flask==3.0.3), `app.py` (8 blueprints + error handlers + binds 0.0.0.0:$PORT), `response.py`, `errors.py` (17 error ids), `db.py` (in-memory Store), `calc.py` (round_half_up via Decimal ROUND_HALF_UP), `middleware.py` (X-User-ID/X-User-Role auth 401 + RBAC 403), `helpers.py` (json parse, pagination, validators), `serializers.py` (TicketLineItem omits updated_at/version), `routes/` (sellers, commodity_prices, tickets incl line-items + theft gate, payouts, containers, mill_shipments, hedges, theft_reports).

### Endpoints
All 41 endpoints: sellers (5), commodity-prices (3), tickets + line-items + weigh-out/theft-hold/clear-hold/release/report (12), payouts + settle/void (5), containers + dispatch (4), mill-shipments + settle (4), hedges + close (4), theft-reports + clear (4).

### Key behaviors
Validation ordering per §2.8; per-line round-then-sum valuation; frozen gross_valuation_cents at weigh-out and expected_settlement_cents at shipment; 1099 cash ledger inclusive 60000-cent threshold + TIN gate + sticky requires_1099; segregation of duties; OCC on container dispatch + hedge-linked settle (412); hedge realization cascade + auto-close; commodity-price supersede with commodity_price_id pinning; **no seeding** — store empty every boot.

### start.sh
`cd`s to own dir, installs deps only when Flask missing (guarded against per-test-reboot contention), then `exec`s `app.py` which reads $PORT (default 10000), binds 0.0.0.0, foreground.

## Step 7: Run Tests and Iterate — 2026-06-21T01:05:00.000Z

The loop is complete. All 8 parallel stability rounds pass cleanly.

### Summary
**Iterations run:** 2 (initial sweep diagnosing the failure; confirming sweep after the fix).

**Initial state:** 74 tests, 1 consistently failing across all 8 rounds (`test_dispatch_empty_container_invalid_state`, failing identically every round — not flaky, deterministic).

**Tests deleted (1):**
- `test_dispatch_empty_container_invalid_state` in `test_suite/test_06_state_machines.py` — **ERROR-ID SILENCE / unique-derivability collapse (STEP 1b)**. The test asserted that dispatching an empty (`loaded_weight_lb == 0`) STAGED container returns `ERR_INVALID_STATE`. PRD §3.6 states the precondition verbatim ("Dispatch requires the container to be `STAGED` and its `loaded_weight_lb` to be greater than 0") but **names no error_id for the empty-container case** — unlike the OCC case (`ERR_STALE_CONTAINER_VERSION`) and the weigh-out zero-lines case (`ERR_NO_LINE_ITEMS`), both of which PRD names explicitly. Two PRD-faithful implementations diverge: (A) reads "dispatches a *non-empty* staged container" as defining the transition's domain → `ERR_INVALID_STATE` (§2.8); (B) reads the literal state machine `STAGED → DISPATCHED` as defined from STAGED and treats `loaded_weight_lb > 0` as an unnamed domain precondition routed to the lowest-priority "generic request well-formedness" → `ERR_INVALID_REQUEST` (§2.8). Both are faithful; the implementation picked (B). Scaffold rule that drove generation: `Corner/state_machines/dispatch_empty_container_invalid_state`.

**Fixes applied to test_helpers/:** none — the test bug was in `test_suite/` (an assertion the PRD does not uniquely determine), not in fixtures/factories.

**Fixes applied to implementation/:** none — no PRD-required check was weakened. The implementation's empty-container handling (returning `ERR_INVALID_REQUEST`) is one of two PRD-faithful readings, so it was left untouched; storage remains in-memory only, no seeding.

**Final state:** 73 tests, all passing in all 8 parallel rounds (73/73, 0 failed, 0 errors per round).

## Step 8: Finalize PRD — align documentation to implementation — 2026-06-21T01:15:00.000Z

The patch is complete. Here is the summary.

Summary

Line counts: PRD.md = 246 lines; PRD_FINALIZED.md = 246 lines (one line revised in place; 0% line-count delta, ~1 line / 0.4% content change).

Changes (1 bullet):
- §3.6 (Containers — Dispatch) — revise — Pinned the error_id for the empty-container dispatch case. PRD stated the precondition (loaded_weight_lb > 0) but named no rejection code; added that a STAGED container with loaded_weight_lb == 0 is rejected with ERR_INVALID_REQUEST (HTTP 422), the generic request-well-formedness code — matching routes/containers.py:81-82 (errors.invalid_request("Container is empty; cannot dispatch.")).

Per-edit pre-edit search log:
- (a) Subject identified: the empty-container dispatch precondition (loaded_weight_lb > 0) and which error_id its violation yields.
- (b) Impl paths enumerated / read: grep -rn "loaded_weight_lb|dispatch|invalid_request" over routes/ surfaced exactly four loaded_weight_lb callsites: routes/containers.py:81-82 (the empty-dispatch check → invalid_request), routes/tickets.py:261 (release capacity check → ERR_CONTAINER_CAPACITY_EXCEEDED), routes/tickets.py:268 (release increment), and routes/mill_shipments.py:67 (copy into shipped_weight_lb). Only containers.py dispatch governs the empty-dispatch error; the others are release/ship paths with their own distinct codes and were confirmed unaffected. Also read errors.py (confirmed ERR_INVALID_REQUEST = 422) and helpers.py (invalid_request helper).
- (c) Wording adjustment made: I deliberately scoped the new clause to the empty-container case in isolation and did not assert its position relative to the OCC version check. Reason: the impl checks empty (containers.py:81) before OCC (:84), but §2.8's stated business-rule priority list places optimistic-concurrency version match above generic request well-formedness. Asserting an ordering would have created a new mismatch with §2.8 on the combined empty+stale path (which Step 7 never exercised). The under-determined wording ("Dispatch is also optimistic-concurrency-guarded…") keeps the sentence consistent with both §2.8 and every enumerated impl path.

No other step_7_diff items required PRD edits: the single diff item was a test deletion documenting this exact PRD silence, and no implementation or test_helper fixes were applied in Step 7.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-06-21T01:20:00.000Z

All 7 edits are in place and the diff is clean. Each edit is a minimal in-paragraph insert; no new sections or paragraphs were added, and no lines were removed (line count unchanged at 246).

**Source vs completed:** `PRD_FINALIZED.md` (246 lines, 38,163 chars) → `PRD_COMPLETED.md` (246 lines, 39,687 chars). Char delta: **+1,524**. Line count unchanged (all edits are in-paragraph inserts; no sections/paragraphs added, nothing deleted).

**Counts:** 7 changes total — **2 ambiguity-pins** (PRD silent on a behavior the impl exhibits) + **5 mismatch/ordering-revisions** (PRD prose was silent on an error code or left an ordering ambiguous/contradictory vs §2.8, pinned to what impl does).

**Per-change log:**

- §2.3 Pagination — insert — ambiguity — pinned that non-integer `limit`/`offset` and out-of-enum `status`/`category`/`method` list filters both return `ERR_INVALID_REQUEST`, while free-text id filters are unvalidated — `helpers.py:44-58`, `routes/sellers.py:60-61`, `routes/payouts.py:75-78`.
- §3.3 Weigh-out — insert — mismatch (ordering+code) — pinned the `BANNED`-seller rejection as `ERR_SELLER_FROZEN` and that it is checked *after* weight validity (so a bad tare wins), contra §2.8's seller-frozen-before-weight priority — `routes/tickets.py:177-183`.
- §3.4 Release — insert — ambiguity — pinned that a container which exists but is not `STAGED` yields `ERR_INVALID_STATE`, evaluated after the seller-frozen gate — `routes/tickets.py:251-252`.
- §3.5 Payout creation — insert — mismatch (ordering) — pinned that segregation-of-duties is evaluated *before* the duplicate-payout check (per §2.8), contra the §3.5 prose listing duplicate first — `routes/payouts.py:36-43`.
- §3.6 Container dispatch — insert — mismatch (ordering) — pinned that the empty-container `ERR_INVALID_REQUEST` precedes the OCC version check (impl order), resolving the conflict with §2.8 which ranks OCC above request-well-formedness — `routes/containers.py:80-85`.
- §3.7 Mill shipment creation — insert — ambiguity — pinned that a container that already has a shipment is rejected with `ERR_INVALID_STATE` — `routes/mill_shipments.py:60-62`.
- §3.7 Mill shipment settle (hedge) — insert — mismatch (codes+ordering) — pinned: missing/null `expected_hedge_version` → `ERR_INVALID_REQUEST`; non-`OPEN` hedge → `ERR_INVALID_STATE`; category mismatch → `ERR_CATEGORY_MISMATCH`; and the full check order (presence → OPEN → category → over-realized → stale-version) — `routes/mill_shipments.py:134-149`.

Implementation was walked exhaustively (all 8 route modules, `calc.py`, `db.py`, `errors.py`, `helpers.py`, `middleware.py`, `response.py`, `serializers.py`). Response envelopes, common-field shapes (incl. append-only `TicketLineItem`), valuation/rounding arithmetic, the seller/ticket/payout/container/shipment/hedge/theft-report state machines, the 1099 cash-ledger and TIN gate, the OCC guards, and the supersede mechanism were all confirmed already uniquely pinned by the existing PRD and needed no change.
