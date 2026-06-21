# Worklog — task_0307_stadium_venue_concessions

## Step 1: Create Task Directory — 2026-06-12T02:34:30.000Z

Task directory `tasks/task_0307_stadium_venue_concessions` was pre-assigned and already existed with a `workspace/` subdirectory. No index auto-computation performed (directory pre-assigned). Confirmed `workspace/` exists and is empty.

## Step 2: Generate Scaffold (Expert) — 2026-06-12T02:56:49.000Z

All OCC payload values use `${var}` (or `${s_v} - 1` for the deliberate stale negative test). All bound by earlier `captures: { ..._v: $.data.version }` from a GET on the stand. The lint already confirmed placeholder closure (515 calls scanned, clean).

The scaffold is complete and passes all automated checks.

## Summary

Generated a complete **Expert-tier** scaffold for **Task 0307 — Stadium & Venue Concessions**. All three files written; `scaffold_lint.py` returns **VERDICT: clean lint** (515 calls scanned across §1.8/§1.9, all FK reverse-reachability satisfied).

**Complexity profile**: primary archetype `quota_allocation` + secondary `pricing_engine`; layers = cascading side effects, dual-variant calculation, rate/threshold triggers, derived-field reconciliation, optimistic concurrency; hybrid topology; branching/parallel/compound state shape; peer-role model; immediate consistency.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **14 entities**: Venue, Product, Event, Stand, MenuItem, InventoryLot, Replenishment, Transfer, Order, OrderLine, StaffShift, WasteRecord (immutable, `common_fields:false`), RevenueShareStatement, Patron. 22 FKs, all with reverse-reachability GETs.
- **7 state machines**: Event (compound settle gate), Stand (OPEN↔SUSPENDED revert cycle), InventoryLot (depletion/expiry), Replenishment, Transfer (dispatch/complete/compensating-cancel), Order (parallel payment×fulfillment dimensions), StaffShift.
- **2 concurrency rules**: OCC on `Stand.version` for transfer-dispatch and order-ready (both 412), each with `expected_*_version` input + version-bump side effect.
- **6 calculations**: event-day surge pricing (mode-a combinatorial), order totals (mode-b round-per-line-then-sum), revenue-share settlement (GROSS/NET dual-variant), spoilage valuation (FIFO/WEIGHTED_AVG dual-variant), required staffing (ceil-threshold boundary), replenishment suggestion (≤ reorder-point boundary).
- **18 validation rules** (priority-ordered, including two temporal-overlap rules with contrasting closed-interval vs half-open semantics).
- **65 endpoints** (37 POST actions + 28 GET reads incl. one `/_clock/set_current_utc` test hook).
- **18 error codes** (all referenced).
- **4 roles**: ConcessionsManager, StockRunner, StandOperator (all `opaque`), Patron (`entity_backed:Patron`).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** all **9 rules × 2 instances = 18 instances**, every formula-derived assert pre-computed to literals (e.g., GROSS share 984 vs NET share 924 on identical inputs; FIFO 4000 vs WAVG 4800 on identical waste; round-per-line total 165 vs sum-then-round 164; depth-3 cascade expire→waste→event-cost→net-statement; depth-2 peak-window→price+staff recompute).

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** **39 active corner instances + 2 `excluded_because` stubs** across all 9 claim-extraction-guide sections (entities 10, state_machines 7, calculations 4, validations 7, endpoints 2, errors 3, rbac 2, cross-cutting 3, consistency 1). All 18 error codes triggerable; both dual-variant counterpart branches covered; OCC stale/increment, boundary complements (161 staffing, on_hand=61 no-suggestion), FK filtered-list reads.

**59 unique instance names** across both design files; all `grounds`/stub references resolve; no forbidden concurrency vocabulary. Did not view any sibling task directory.

## Step 3: Copy Shared Files — 2026-06-12T02:57:16.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0307_stadium_venue_concessions/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-12T03:02:40.000Z

Generated PRD at `workspace/PRD.md` (287 lines, 45498 bytes).

**Major sections:**
- §1 Introduction — stadium concessions across the event arc, four operator constituencies.
- §2 Global Specifications (8 subsections): RBAC (4 roles, opaque vs `Patron` entity-backed), fixed response envelope, pagination, common resource properties (`WasteRecord` `common_fields:false`), hierarchical consistency & derived-field reconciliation, monetary/rounding (round-half-up), OCC on Stand (both rules), validation ordering.
- §3 Business Logic (9 subsections): venues/catalog/pricing, events & stands, event lifecycle + peak-rush cascade + stand lifecycle, event-day pricing, stocking (lots/replenishment/transfers), waste & spoilage costing, staffing & replenishment advisories, mobile orders cart-to-pickup, settlement & revenue share.
- §4 Endpoint Definitions — 4-column table, all 67 endpoints incl. `/_clock` test hook.
- §5 Error Code Catalogue — all 18 error IDs.

**Hard Contracts:** Field-name coverage 0 missing; rule coverage complete (both dual-variant calcs GROSS/NET + FIFO/WEIGHTED_AVG, per-line rounding, ceiling staffing boundary, inclusive reorder trigger, both OCC rules, all 18 errors, all 36 state enums); §3 path purity clean (0 path tokens / 0 bare methods).

**Confirmation:** Did NOT read SCAFFOLD_DIFFICULTY_DESIGN.yaml or SCAFFOLD_CORNER_DESIGN.yaml.

## Step 5: Generate Unit Tests — 2026-06-12T03:20:31.000Z

Generated complete test infrastructure under the design-index-only contract. All Stage 1 helpers and Stage 2 tests compile cleanly and pass the full coverage + citation audit.

**Test files: 8** (1 conftest + 7 `test_*.py`)
- `test_01_catalog_and_entities.py` — entity CRUD, defaults, computed fields, immutability, auth/forbidden errors
- `test_02_pricing_and_order_totals.py` — event-day pricing + round-per-line order totals
- `test_03_revenue_share_and_spoilage.py` — GROSS/NET revenue share, FIFO/WEIGHTED_AVG spoilage
- `test_04_event_and_stand_lifecycle.py` — parallel order dimensions, stand revert cycle, peak-window cascade, lifecycle guards
- `test_05_inventory_movement.py` — expire-lots depth-3 cascade, transfer/refund compensating invariants, replenishment, depletion
- `test_06_validations_and_concurrency.py` — validation precedence, boundary precision, temporal overlap, cross-entity gates, stand-version OCC
- `test_07_access_and_listing.py` — role exclusivity + list-envelope pagination

**Total test functions: 75** — Queue A (Difficulty): 36 tests (all 18 difficulty instances ×2); Queue B (Corner): 39 tests (all 39 non-stub corner instances ≥1 each).

**Instances SKIPPED: 0 non-stub.** The 2 `excluded_because` corner stubs were correctly NOT translated (cross-references resolve to existing difficulty instances).

**Two PRD-first corrections (not skips):** `consistency_model/pickup_reflects_gross_sales_immediately` and `compensating_invariant/order_cancel_refund_conserves_money_to_wallet` specified a MID-tier stand base 100 asserting order total 220, internally inconsistent with PRD §3.4 (MID surge 115 → total 253). Pinned a LOW-tier/multiplier-100 stand (unit price = base = 100, total = 220, PRD-consistent) and asserted wallet/gross credit equals the order's own `total_cents`. Other monetary figures arithmetically verified against PRD formulas.

**test_helpers/ files (9):** `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`

**Audits passed:** every test carries exactly one `Design:` tag resolving to a real instance; all 105 citation fragments verbatim-present in PRD.md; no skip/xfail markers; no scaffold references; `WasteRecord` immutable (id + created_at only); Patron identity threaded via `make_patron_headers`.

## Step 6: Generate Implementation — 2026-06-12T03:20:31.000Z

Built a complete Python + Flask REST API at `workspace/implementation/`.

### Files written
- `start.sh` — foreground launcher (executable); guards `pip install` on a cheap `import flask` check, then `exec python3 app.py`.
- `requirements.txt` — `flask==3.0.3`.
- `app.py` — entry point, all ~60 routes, error handlers, `app.run(host="0.0.0.0", port=int(os.environ.get("PORT","10000")), threaded=True)`.
- `db.py` — in-memory store (one dict per entity, keyed by id) + logical clock for expiry + ISO-8601-millis formatter.
- `errors.py` — `ApiError` class and full §5 error catalogue with HTTP statuses.
- `response.py` — success/array/error envelope helpers.
- `middleware.py` — `X-User-ID`/`X-User-Role` auth + per-endpoint RBAC decorator.
- `util.py` — round-half-up (Decimal), field validators, pagination, create/touch bookkeeping.
- `services.py` — all calculations + inventory FIFO debit/cascades.
- `serializers.py` — per-entity public projections (WasteRecord omits `updated_at`/`version`).

### Stack & storage
Python 3.9 + Flask 3.0.3. Storage is purely in-process Python dicts keyed by UUID id, guarded by an `RLock`. Money is integer cents via `decimal.Decimal` with `ROUND_HALF_UP`. Datetimes parsed to aware UTC, serialized to ISO-8601 millis.

### Contract confirmations
- `start.sh` reads `$PORT` (default 10000), binds `0.0.0.0`, runs foreground via `exec`, guards dependency install.
- No data seeded/preloaded/hardcoded at startup — store empty on every boot (verified by reboot test: total_count 3 → 0 after restart).

### Self-verification (impl-gen subagent's own run)
Booted server, ran 75 functional assertions across three suites (all passing): auth/RBAC masking order, event-day pricing (780→840 peak), per-line fee rounding (199), peak-window cascade, OCC stale-version 412, payment/stock gates, FIFO consumption, transfer dispatch/complete/cancel with weighted-avg costing + IN_TRANSIT re-credit, expiry cascade (waste→event ledger→lot EXPIRED), GROSS vs NET settlement (NET floored at 0), refund-to-wallet, replenishment `<=` boundary, event-window closed-interval overlap, shift half-open overlap, pagination envelope.

## Step 7: Run Tests and Iterate — 2026-06-12T03:30:40.000Z

All tests pass across the full 8-round parallel sweep (75/75 in every round; verified independently: rounds 1–8 all passed=75 total=75).

**Iterations run:** 1 fix iteration. Initial sweep showed 5 failures stable across all 8 rounds; after fixes, two consecutive 8-round parallel sweeps (16 rounds total) were fully green at 75/75 each.

**Initial failures (union across 8 rounds):**
- `test_settlement_gross_basis_ignores_waste` — setup 409 ERR_INVALID_STATE
- `test_settlement_net_basis_subtracts_waste_from_base` — setup 409 ERR_INVALID_STATE
- `test_expire_lots_bumps_event_waste_cost` — 409 ERR_INVALID_STATE on settle
- `test_expire_cascade_shrinks_net_venue_share_at_settlement` — 409 ERR_INVALID_STATE on settle
- `test_patron_cannot_cancel_another_patrons_order` — ConnectionReset (transport flake, downstream effect of per-test-server left mid-flow by the same root cause / load)

**Root cause:** All failures traced to settlement fixtures driving an event straight from `DOORS_OPEN` to settle. PRD §3.5 (line 138) states verbatim: *"Settlement is permitted only while the event is `IN_PROGRESS`."* The implementation correctly rejects settle from `DOORS_OPEN` with `ERR_INVALID_STATE` (app.py:276). The fixtures never advanced the event to `IN_PROGRESS` (never opened the peak window). This is a STEP 2 test-fixture bug, not an implementation bug — the PRD-required state check was correct and preserved.

**Tests deleted:** None. Every failure was a faithful test blocked by a faulty precondition; no PRD-silence or non-unique-derivability issues found.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py`, `setup_settled_event_with_sales_and_waste` — inserted `open_peak_window(event)` after the order pickup and waste record, before `close_stand`/`settle_event`. Advances the event to `IN_PROGRESS` so settle is legal. Placed after pickup so `gross_sales_cents` (4922) was already snapshotted (PRD §3.8 line 184), leaving gross/waste unchanged.

**Fixes applied to `test_suite/`:**
- `test_suite/test_05_inventory_movement.py`, `_depth3_cascade_settled` helper — same fix: inserted `open_peak_window(event)` immediately after pickup, before the clock advance / `expire_lots` / `close_stand` / `settle_event`. Keeps gross 4922 and waste 2000 intact while making the event `IN_PROGRESS` for settle.

**Fixes applied to `implementation/`:** None. The implementation was already PRD-faithful.

## Step 8: Finalize PRD — 2026-06-12T03:32:23.000Z

`PRD_FINALIZED.md` created as a faithful, byte-identical copy of `PRD.md` (287 lines each, 0% delta; `diff` confirms IDENTICAL).

**Changes:** No edits — all four Step 7 diff items are pure fixture/test-precondition bugs. The PRD already uniquely determines the behavior they exercised.

All four failing items traced to a single subject: the settlement state gate. Fixtures drove events from `DOORS_OPEN` straight to settle, never advancing through `IN_PROGRESS`. PRD §3.5 (line 138) already states verbatim "Settlement is permitted only while the event is `IN_PROGRESS`," and the implementation enforces exactly that at `implementation/app.py:276`. The Step 7 diff confirms 0 implementation fixes and 0 deletions — the fix was inserting `open_peak_window(event)` into fixtures. No PRD silence and no PRD/impl mismatch to pin.

**Per-edit pre-edit search log:** No edits made. Subject evaluated: the settlement state gate. Impl paths enumerated: `settle_event` (app.py:271-308, state check line 276 IN_PROGRESS-only; settleability gate lines 280-285; peak_window→false + status→SETTLED lines 287-289); cross-referenced parallel lifecycle checks — `open_doors` (app.py:223), `peak_window_open` (app.py:241-246), `peak_window_close` (app.py:262), `deliver_replenishment` (app.py:708), `complete_transfer` (app.py:853); confirmed `services.compute_revenue_share` (services.py:220-227) consistent with §3.9. Wording adjustment: none — every path already consistent with existing PRD prose.

## Step 9: Complete PRD — 2026-06-12T03:37:40.000Z

Produced `PRD_COMPLETED.md` from `PRD_FINALIZED.md` via full PRD-vs-implementation scan.

**Source vs completed:** 287 lines / 45,498 chars → 287 lines / 47,344 chars (delta **+1,846 chars**, 0 line delta — 6 in-paragraph revisions/inserts on existing lines; no new sections).

**Counts:** ambiguity-pins = **5**, mismatch-revisions = **1**.

**Per-change bullets:**
- **§2.8 (Validation Ordering)** — insert — ambiguity — body structural parse (required-field presence, type/format/range) runs ahead of `ERR_NOT_FOUND` for a body-referenced resource; "finally" `ERR_INVALID_REQUEST` governs only path-existence + post-resolution business rules — app.py:108-120/124.
- **§3.5 (expiry sweep)** — revise — mismatch — PRD claimed expiring a not-yet-eligible lot is rejected with `ERR_LOT_NOT_EXPIRED`; impl's stand-level sweep silently skips ineligible lots, returns 200 with the stand, never raises that error — app.py:417-456.
- **§3.5 (replenishment delivery)** — insert — ambiguity — delivered lot's `expires_at` always null; delivery responds 200 with the updated replenishment (not the new lot) — app.py:714-727.
- **§3.5 (transfer complete/cancel)** — insert — ambiguity — lots created on transfer completion / in-transit cancel-compensation get `par_level`/`reorder_point` = 0 and `expires_at` = null; complete/cancel respond 200 with the updated transfer — app.py:855-867, 883-895.
- **§3.9 (revenue-share-statement retrieval)** — insert — ambiguity — GET statement endpoint responds 200 with an array-style envelope (`response_type:"array"` + pagination) holding the event's statements, not a bare object — app.py:311-319.
- **§4 (endpoint intro / settle)** — insert — ambiguity — `POST .../settle` returns 201 Created with the newly created revenue-share statement in `data` (creating semantics win over the concurrent event transition) — app.py:271-308.

**Deliberately unchanged:** EXPIRY waste cost computed across candidate lots while on-hand decrement draws from the named lot (PRD §3.6 already pins); venue percentage "up to two decimals" not enforced (permissive non-enforcement, no distinct testable behavior); replenishment-suggestion entries already match pinned fields.

---

## Pipeline complete

All 9 steps finished. Final state: 75/75 tests passing across 8 parallel rounds; PRD.md → PRD_FINALIZED.md (byte-identical) → PRD_COMPLETED.md (+1846 chars, 6 in-paragraph pins).
