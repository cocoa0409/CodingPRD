# Worklog — task_0730_party_supply

## Step 1: Create task directory — 2026-07-04T11:05:00.000Z

Created `tasks/task_0730_party_supply/` and `tasks/task_0730_party_supply/workspace/`. ID pre-assigned (0730), not re-derived. Difficulty: Expert (passed to scaffold-generator at Step 2 only).

## Step 2: Generate scaffold — 2026-07-04T14:24:30.000Z

All three files written and lint-clean. Summary:

Three files written under `/home/ubuntu/github/CodingPRD/tasks/task_0730_party_supply/`:
- `SCAFFOLD.yaml` — 1915 lines (§1.0–§1.7 + §1.2.1)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1117 lines (§1.8; 18 instances = 9 rule_ids × 2)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 1351 lines (§1.9; 34 active instances + excluded stubs)

Scope covered:
- Entities (13): Sku, Bundle, BundleLine, Order, OrderLine, HeliumOrder, HeliumTank, DeliverySlot, RentalContract, CustomPrintOrder, EventPackage, EventBooking, Customer
- Endpoints (60): full CRUD + action endpoints + reverse-reachability GETs for every FK + two `/_...` test-driving endpoints (`/_clock/set_current_utc` with startup default 2026-03-01T00:00:00Z, `/_helium-tanks/{id}/refill`)
- State machines (5): Order (parallel fulfillment_status × payment_status axes), CustomPrintOrder (cyclic PROOF_SENT↔REVISION_REQUESTED), EventBooking, RentalContract, Sku (clearance)
- Errors (21) covering auth, existence, state, OCC-412, business_safety, business_referential, business_temporal, business_constraint, business_fiscal
- Concurrency: OCC on Order and Sku (two `concurrency_rules` entries, both true races per §1.2.1 filter)
- RBAC: 4 peer roles (StoreManager, StoreClerk, DeliveryDriver, Customer); Customer is entity_backed, others opaque
- Calculations (8): order_grand_total (dual-variant), helium_fill_fee (tiered + round-per-line-then-sum), helium_tank_waterfall_allocation (waterfall by created_at), delivery_fee (threshold, weekend surcharge), rental_deposit, custom_print_fee (tiered + dual-variant), event_deposit, sku_reservation_balance (derived-field reconciliation)
- All 9 §0.5 difficulty rules satisfied with 2 instances each (18 total); every §1.8 assertion pre-computed as literal
- Lint verdict: clean

## Step 3: Copy INSTRUCTION.md — 2026-07-04T14:26:00.000Z

Copied `INSTRUCTION.md` to `tasks/task_0730_party_supply/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-04T14:32:20.000Z

All three hard contracts pass. Let me confirm the final state.

Contracts:

Field coverage check:
- entities[].fields: all present in backticks in prose
- endpoints[].request_body / input: all present (`expected_order_version`, `expected_sku_version`, `pct`, `delta`, `mode`, `lines`, `delivery_slot_id`, `to_iso8601`)
- endpoints[].query_params: `limit`, `offset`, and reference to `theme_tag` / `category` / `sku_id` / `bundle_id` / `order_id` / `van_id` / `status` / `event_package_id` filters all in table + narrative
- Status: PASS

Rule coverage check:
- validations[].priority 1-19 explicitly enumerated in §3.9
- concurrency_rules: both entries (Order reserve → `expected_order_version` → `ERR_STALE_ORDER_VERSION` HTTP 412; Sku clearance → `expected_sku_version` → `ERR_STALE_SKU_VERSION` HTTP 412) named with write endpoint, occ field, error id and http status; framed in stale-version terms, not overlap/parallel terms
- state_machines: Order fulfillment axis (8 transitions), Order payment axis (2 transitions), CustomPrintOrder (7 transitions), EventBooking (4 transitions), RentalContract (4 transitions), Sku (2 transitions) — all with from/to states, preconditions, and side-effect cascades (Sku.reserved_qty/on_hand_qty, HeliumTank.remaining_cubic_ft, DeliverySlot.status, RentalContract cascade on pickup, store_credit_cents on refund/return/event-cancel, deposit forfeiture cases)
- calculations: `order_grand_total` (with provisional and finalized variants), `helium_fill_fee` (round-then-sum), `helium_tank_waterfall_allocation` (created_at ASC, tank_code tiebreak), `delivery_fee` (base+setup+weekend), `rental_deposit` (undiscounted unit price × 2.0 × qty), `custom_print_fee` (tiered marginal, sum-then-round, revision surcharge), `event_deposit`, `sku_reservation_balance`, `overlap_returns_within_14_days` — all expressed in precise business narrative with constants embedded
- validations[] conditions matched to error IDs in prose
- endpoints[].side_effects: reserve cascade, pickup cascade with rental cascade, cancel cascade, no-show sweep, event forfeit sweep all in narrative
- sibling-branch symmetry: on-time return vs late return vs damaged (all three branches given equal density with deposit outcome specified); DEPOSIT vs FULL payment modes both fully specified
- Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 448
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
- Status: PASS

result: Generated `/home/ubuntu/github/CodingPRD/tasks/task_0730_party_supply/workspace/PRD.md` (314 lines) — §1 (2-para introduction), §2 with 13 subsections, §3 with 9 subsections, §4 endpoint table (58 endpoints), §5 error catalogue (21 errors). All three hard contracts PASS.

## Step 5: Generate unit tests — 2026-07-04T14:53:00.000Z

All files generated. Sanity check summary:

- **test_helpers/**: 9 files (types, api_client, api_errors, assertions, factories, constants, test_users, fixtures, __init__)
- **test_suite/**: 18 files (conftest + 17 test files)
- **AST-parse**: all files parse OK
- **No scaffold references**: no "scaffold" or "§1.x" / "Table N" leaked
- **C1 verbatim**: all citations survive substring grep of PRD.md (modulo whitespace + backticks)
- **Design tag coverage**: every test carries exactly one `Design: Difficulty/…` or `Design: Corner/…` line
- **Difficulty**: 18/18 instances ×2 tests = 36 tests
- **Corner**: 33/34 non-stub instances covered ×1 test = 33 tests; 1 PRD-filter skip documented (`stale_order_version_on_reserve` fails unique-derivability given PRD §3.9 priority ordering)
- **Corner stubs**: 5 stubs correctly not translated (each cross-references a difficulty instance that carries the assertion)

result: Generated test_helpers/ (9 files) and test_suite/ (conftest + 17 test files), producing 69 tests total — 36 Difficulty (18 instances × 2) + 33 Corner (33 of 34 non-stub instances × 1); PRD-filter skipped Corner/errors/stale_order_version_on_reserve; all 5 stub instances correctly not translated.

## Step 6: Generate implementation — 2026-07-04T14:43:00.000Z

Sanity check summary: the app boots via `bash start.sh`, listens on `$PORT` (default 10000) bound to `0.0.0.0`, starts with an empty store and a default clock of `2026-03-01T00:00:00Z`, registers 61 routes at `/api/*`. I exercised: envelope shape (`meta`/`response_type`/`data`), auth 401/403/404, OCC 412 on stale order version, `SKU.reserved_qty` cascade on reserve/cancel/sweep, helium bulk-tier fee (7544 for 25 latex + 10 foil), custom print marginal tiers with revision surcharge (7500 for 10 ft × 2 revisions), rental deposit using undiscounted price on clearance SKU (6000 for 3 × $10 units), delivery slot half-open overlap (409 for overlap on same van; adjacent endpoints allowed), no-show sweep on clock advance flipping READY_FOR_PICKUP → CANCELLED + issuing store credit, DELIVERY channel flow through pickup→deliver, and Customer-role ownership check on custom print revision.

result: Generated the party-supply Flask API at /home/ubuntu/github/CodingPRD/tasks/task_0730_party_supply/workspace/implementation/ — 22 source files (app.py, db.py, errors.py, response.py, middleware.py, pagination.py, routes/{skus,bundles,customers,orders,helium,delivery,rentals,custom_print,events,clock}.py, services/{calc,order,sweep}.py), 61 routes under /api, guarded start.sh + requirements.txt (Flask 3.0.3), empty in-memory store on each boot, logical clock defaulting to 2026-03-01T00:00:00Z with sweep on `/api/_clock/set_current_utc`, calculations verified against PRD examples; OCC + priority-ordered validation implemented per §3.9.

## Step 7: Run tests + iterate to PASS — 2026-07-04T15:03:00.000Z

All 8 rounds pass with 69/69. Sanity check: I verified the two failure categories were traced to verbatim PRD requirements (§3.4 provisional total, §2.3 created_at ASC pagination), applied targeted implementation fixes, and reran the full 8-round parallel sweep — every round is green.

Summary:
- Iterations run: 2 (baseline sweep to identify failures, one fix iteration).
- Tests deleted: 0.
- Fixes applied to `test_helpers/`: none.
- Fixes applied to `implementation/`:
  - `workspace/implementation/services/order.py` — added `recompute_provisional_totals` implementing PRD §3.4's provisional variant (live `Sku.unit_price_cents`, no clearance, excludes helium/delivery/rental deposits) and short-circuited `recompute_order_totals` to it when the order is DRAFT. Previously DRAFT orders returned `grand_total_cents=0`.
  - `workspace/implementation/routes/orders.py` — `create_order` now calls `osvc.recompute_provisional_totals(order)` so the create response carries the provisional total.
  - `workspace/implementation/db.py` — added a monotonic `_seq` insertion counter, stamped by `stamp_common`, so entities created at the same logical-clock instant have a deterministic tiebreak that preserves creation order.
  - `workspace/implementation/pagination.py` — `paginate` now tiebreaks on `_seq` instead of random `id`, honoring PRD §2.3 "sorts its resources by created_at in ascending order" for same-instant siblings (e.g. 12 SKUs created back-to-back with the clock frozen).

result: 8/8 rounds green (69/69); fixed DRAFT-order provisional grand-total per PRD §3.4 and pagination created_at tiebreak per PRD §2.3.

## Step 8: Finalize PRD — 2026-07-04T15:25:00.000Z

**Sanity check:** Ran `diff -u` — only two hunks changed, exactly at §2.3 and §3.4, both are insertions into existing paragraphs. Line count identical (314 → 314) since the changes are inline additions to already-long paragraphs. Word count 7064 → 7206 (+142 words, +2.0%).

result: PRD_FINALIZED.md written — 2 minimal insertions pin (a) list-endpoint tiebreak = insertion order and (b) DRAFT orders carry the provisional variant on their monetary fields at create time.

**Metrics**
- Line counts: PRD.md 314 → PRD_FINALIZED.md 314 (delta 0 lines, 0% by lines; +142 words, +2.0% by words). Both edits are inline insertions into two long paragraphs.

**Change bullets**
- §2.3 Pagination — insert — clarifies that when two resources share the same `created_at`, list endpoints tiebreak by insertion order — `implementation/pagination.py:31` (sort key `(created_at, _seq)`) and `implementation/db.py:80-83` (monotonic `_seq` stamped by `stamp_common`).
- §3.4 Order Assembly and Reservation — insert — pins that the provisional variant is written onto the DRAFT order's monetary fields at order creation time (so the create-order response returns provisional `subtotal_cents`, `deposit_cents`, `grand_total_cents`, and `helium_fee_cents`/`delivery_fee_cents` = 0) — `implementation/routes/orders.py:122-123` and `implementation/services/order.py:97-98,138-180`.

**Pre-edit search logs**

Edit 1 — §2.3 pagination tiebreak
- (a) Subject: how list endpoints break ties when two resources share `created_at`.
- (b) Impl paths enumerated and read/grepped: pagination.py, db.py, all paginate call sites, services/order.py helium waterfall sort.
- (c) Wording adjustment: scoped the new clause to "list response … tiebreak" so it does not silently override the helium waterfall's `tank_code` tiebreak in §2.10.

Edit 2 — §3.4 DRAFT order carries provisional totals
- (a) Subject: what the DRAFT order's persisted monetary fields contain before reserve, and specifically what the create-order response returns.
- (b) Impl paths enumerated and read/grepped: routes/orders.py create_order, services/order.py recompute_*_totals, custom_print/rentals/events attach routes, sweep.py credit path, do_reserve.
- (c) Wording adjustment: bounded the pin to "at order creation time" (not "any time DRAFT") because impl does not refresh provisional on later attach operations; phrased custom-print inclusion as "if one is already pinned".

## Step 9: Complete PRD — 2026-07-04T15:45:00.000Z

All 25 edits complete. Same line count (all inline paragraph mods), +9,289 chars.

result: PRD_COMPLETED.md written — 25 inline pins over PRD_FINALIZED (16 ambiguity, 9 mismatch); 314→314 lines, 57,704→66,993 chars (+9,289).

Summary:
- Source: `PRD_FINALIZED.md` — 314 lines / 57,704 chars.
- Target: `PRD_COMPLETED.md` — 314 lines / 66,993 chars (Δ +9,289 chars). No new sections; every change is an in-paragraph insert/revise.
- Ambiguity-pins: 16. Mismatch-revisions: 9.

Changes:
- §2.1 (Customer ownership) — revise — mismatch — impl only enforces `customer_id == X-User-ID` on the two custom-print Customer endpoints; read endpoints do not gate.
- §2.2 (`api_request_id` shape) — insert — ambiguity — `req_` + 20 mixed-case alphanumerics.
- §2.2 (`api_request_timestamp` source) — insert — ambiguity — sampled from `db.clock`, not wall-clock.
- §2.2 (error content-type) — insert — ambiguity — errors use the same JSON envelope.
- §2.3 (pagination validation, filter equality, total_count semantics) — insert — ambiguity — non-integer/out-of-range → `ERR_INVALID_REQUEST`; strict string equality; `has_more` = `offset + len(data) < total_count`.
- §2.4 (logical-clock timestamps + tiebreak) — insert — ambiguity — created_at/updated_at all sampled from `db.clock`; ties resolved by insertion order.
- §2.10 (tank auto-EMPTY on drain, refill idempotency) — insert — ambiguity — allocation flips ACTIVE→EMPTY at 0; restore may flip back to ACTIVE.
- §2.11 (OCC input validation + priority ordering) — insert — ambiguity — missing/non-integer `expected_*_version` → `ERR_INVALID_REQUEST`; `ERR_INVALID_STATE` fires before OCC.
- §2.12 (UNPAID no-show no-credit case) — insert — ambiguity — sweep only credits when payment was DEPOSIT_HELD/PAID.
- §2.13 (clock endpoint payload + no monotonic guard; sweep affects Customer/Sku/HeliumTank/DeliverySlot versions) — insert — ambiguity.
- §2.9 (seasonal check requires both boundaries) — insert — ambiguity.
- §3.1 (SKU create rejects, restock delta ≥ 0, clearance non-idempotent) — insert — ambiguity.
- §3.1 (Bundle create details) — insert — ambiguity — duplicate `bundle_code` → `ERR_INVALID_REQUEST`, missing sku_id → `ERR_FK_NOT_FOUND`, DISCONTINUED enum has no transition endpoint.
- §3.2 (helium tank create + refill semantics) — insert — ambiguity — duplicate `tank_code` rejected; refill idempotent.
- §3.3 (delivery slot ISO validation, coercion, cancelled-slot exclusion from overlap) — insert — ambiguity.
- §3.4 (add-on single-attach caps + parent-DRAFT invariant + Helium initial fields) — insert — ambiguity.
- §3.4 (create-order shape: non-empty lines, exactly-one sku/bundle, pickup fields stored verbatim, delivery_slot_id existence-only, slot untouched until reserve) — insert — ambiguity.
- §3.5 (pickup pre-state channel-split) — revise — mismatch — impl allows PICKING → PICKED_UP for DELIVERY/IN_STORE.
- §3.5 (return always REFUNDED, never PARTIALLY_REFUNDED) — revise — mismatch.
- §3.5 (payment mode validation, DEPOSIT UNPAID pre-req, DEPOSIT_NOT_APPLICABLE order) — revise — mismatch.
- §3.5 (cancel: no release from DRAFT, deposit-only refund flip, EMPTY→ACTIVE on helium restore) — revise — mismatch.
- §3.6 (rental deposit rounding order, DRAFT parent, multi-attach, non-terminal overlap set, `returned_at` init, damage doesn't restock) — revise — mismatch.
- §3.7 (approve cascade: pin fee then recompute totals + bump order) — insert — ambiguity.
- §3.7 (custom-print init: `print_fee_cents: 0`) — insert — ambiguity.
- §3.8 (event confirm uses `>=` on lead-day comparison, cancel only flips DEPOSIT_HELD payment) — revise — mismatch.
- §4 (helium GET) — revise — mismatch — returns list envelope with limit/offset, not a single object.
