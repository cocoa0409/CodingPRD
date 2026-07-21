# Worklog — task_1024_hydroponics_indoor_garden

## Step 1: Create task directory — 2026-07-15

Created `tasks/task_1024_hydroponics_indoor_garden/` and `workspace/` subdirectory (pre-assigned folder, index not scanned).

## Step 2: Generate scaffold (Expert) — 2026-07-15

Task 1024 — Hydroponics & Indoor-Garden Store scaffold generated. All three files written and pass scaffold_lint.py with VERDICT: clean lint (198 §1.8/§1.9 calls checked, all FKs reverse-reachable). All three parse under yaml.safe_load; every formula-derived assert literal recomputed in Python and matches.

Difficulty: Expert. Flat multi-resource topology (api_prefix: ""), primary archetype quota/allocation + secondary pricing-engine, with OCC, cascading side-effects, dual-variant, and derived-field-reconciliation layers.

Scaffold surface (SCAFFOLD.yaml):
- 12 entities: Product, InventoryLot, Customer, CommercialAccount, Order (embedded lines array), Subscription, Consultant, ConsultBooking, Room, WorkshopSession, WorkshopRegistration, RMA.
- 9 state machines including two non-linear: Order carries parallel payment_status × fulfillment_status axes; RMA is cyclic (UNDER_REVIEW↔INFO_REQUESTED). Plus CommercialAccount, Subscription, ConsultBooking, WorkshopSession, WorkshopRegistration, InventoryLot.
- 6 calculations: order_net_total (tiered discount + hazmat surcharge, provisional/final variants), loyalty_points_accrual (per-line-floor-then-sum), consult_fee (estimate ceil-to-hour vs actual prorated), rma_refund (warranty/restock-fee), inventory_reservation (FIFO waterfall by created_at→lot_code), commercial_credit_used (aggregation).
- 16 validations (priority-ordered, 8 categories), 56 endpoints (incl. /_clock/set_current_utc default 2026-07-01T00:00:00Z), 16 error codes, 4 roles (StoreAdmin opaque; Customer, CommercialBuyer, Consultant entity-backed — peer-roles model).
- 1 concurrency rule: OCC on CommercialAccount.version guarding POST /commercial-accounts/{id}/orders (CREATE-with-supersede; expected_commercial_account_version required, version bumped).

Design files: SCAFFOLD_DIFFICULTY_DESIGN.yaml = 18 instances (2 per each of 9 Difficulty Rules). SCAFFOLD_CORNER_DESIGN.yaml = 17 active corner instances + 6 excluded_because stubs.

## Step 3: Copy shared files — 2026-07-15

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-15

Generated workspace/PRD.md (~299 lines) from SCAFFOLD.yaml. Did not open either withheld design file.
Sections: §1 Intro; §2 Global Specs (2.1 Roles/RBAC, 2.2 Response Structure, 2.3 Pagination, 2.4 Common Props, 2.5 Monetary/Units/Rounding, 2.6 Logical Clock, 2.7 Inventory/Lots, 2.8 OCC, 2.9 Validation-order); §3 Business Logic (9 subsections); §4 Endpoint table (56 endpoints, matches scaffold); §5 Error table (16 codes, matches).
Hard Contracts all PASS: Field-Name Coverage 0 missing; Rule Coverage complete; §3 Path Purity 0 violations.

## Step 5: Generate unit tests — 2026-07-15

test_helpers/ (9 files): types.py, api_client.py, api_errors.py (16 error IDs), assertions.py, factories.py, constants.py, test_users.py (opaque StoreAdmin + make_*_headers for 3 entity_backed roles), fixtures.py, __init__.py.
test_suite/ (conftest + 8 files, 51 test functions): test_01_catalog_inventory … test_08_subscriptions_rbac.
Coverage: Queue A (§1.8) 18 instances → 17 translated (×2 = 34), 1 skipped. Queue B (§1.9) 17 non-stub → all 17 translated (×1). 6 excluded_because stubs not translated.
Skip note: Difficulty/priority_pair_validation_conflict/safety_hazmat_beats_referential_not_in_order — SKIPPED (validation-priority silence: PRD §2.9/§3.9 do not order ERR_HAZMAT_NOT_RETURNABLE vs ERR_PRODUCT_NOT_IN_ORDER). Sibling state_account_hold_beats_fiscal_credit kept (§3.4 explicit ordered chain). Corner stub error_hazmat_not_returnable_covered points at skipped instance → ERR_HAZMAT_NOT_RETURNABLE left uncovered (genuine gap). Also trimmed exactly-at-buffer-accepted branch within consultant-buffer instance (not uniquely derivable); core ERR_CONSULTANT_UNAVAILABLE still covered by 2 tests.

## Step 6: Generate implementation — 2026-07-15

workspace/implementation/: start.sh (foreground, reads $PORT default 10000, binds 0.0.0.0), requirements.txt (flask==3.0.3), app.py (56 routes via add_url_rule dispatch, RBAC decorator, per-endpoint validation ordering), store.py (in-memory dicts, logical-clock helpers), errors.py (16-entry catalog), envelope.py, calc.py (Decimal pricing/loyalty/consult/RMA), domain.py (inventory waterfall, derived-field reconciliation, credit/seat/loyalty recompute).
Verified: all source files ast.parse OK; route count = 56 via url_map (matches scaffold); boots via start.sh; end-to-end smoke pass. In-memory only, no seeding.
Flagged low-confidence interpretations: RMA against non-SHIPPED order → ERR_INVALID_STATE (409); GET /orders?status= filters on fulfillment_status; entity-backed roles scoped to own resources on reads too.

## Step 7: Test-and-iterate fix loop — 2026-07-15

All 8 rounds pass cleanly (51/51). Sweep run as 2 waves of 4 via workspace/sweep.sh (no inline pkill).

Iterations run: 2 sweeps (baseline + verification).
Baseline: 50/51, one deterministic failure in all 8 rounds: test_order_bringing_credit_to_exact_limit_accepted (assert 970000 == 1000000).
Diagnosis: implementation PRD-faithful. PRD §3.4 states a COMMERCIAL order gets a 5% volume bonus when subtotal_cents >= 500000. Test placed order A (600000 → net 570000) and B (400000 → net 400000) = credit_used 970000, but test's inline math assumed no discount and expected 1,000,000. Test precondition inconsistent with PRD pricing — STEP 2 test bug.
Tests deleted: None.
Fixes to test_suite/ (test_04_commercial_accounts.py):
- test_order_bringing_credit_to_exact_limit_accepted: changed draws from qty 15+10 vs 1,000,000 limit to qty 10+10 (subtotals 400000 each, below 500000 volume-bonus threshold, net == subtotal) vs 800,000 limit; assertion now credit_used_cents == 800_000.
- test_order_above_limit_rejected (shared flawed setup): mirrored sub-threshold quantities and 800,000 limit; third qty-1 order strictly exceeds limit, still asserts ERR_CREDIT_LIMIT_EXCEEDED.
Fixes to test_helpers/: None.
Fixes to implementation/: None — pricing/credit logic already PRD-faithful.
Final state: 8/8 rounds green, 51/51 each.

## Step 8: Finalize PRD — 2026-07-15

PRD.md vs PRD_FINALIZED.md: 299 vs 299 lines, 0% delta, byte-identical. 0 edits.
Both Step 7 diff items were pure test-fixture arithmetic bugs (test author's inline math omitted PRD §3.4 5% commercial volume bonus), not PRD silence or PRD/impl mismatch. Verified: calc.py price_order is sole pricing path (VOLUME_THRESHOLD 500000, BONUS 0.05, MAX_DISCOUNT 0.12); credit check app.py uses strictly-greater rejection (exact-equality passes, 402). PRD lines 161/167 already uniquely determine both. PRD_FINALIZED.md is a verbatim copy — correct outcome.

## Step 9: Complete PRD — 2026-07-15

PRD_FINALIZED.md (299 lines / 40891 chars) → PRD_COMPLETED.md (299 lines / 42036 chars), +1145 chars, no line-count change (all in-paragraph edits, no new sections).
Counts: 4 ambiguity-pins, 1 mismatch-revision.
- §2.3 Pagination — insert — ambiguity — out-of-range limit / negative offset / non-integer rejected with ERR_VALIDATION (app.py:126-139).
- §2.3 Pagination — insert — ambiguity — equal-timestamp list-sort tiebreaker (server insertion order); per-endpoint filter query params enumerated, unknown params ignored (store.py:112-115; list_* 429-963).
- §3.4 Order Placement — revise — ambiguity — each line's unit_price_cents is server-captured snapshot of product's current price (client line price ignored); quantity must be positive integer (app.py:151-177).
- §3.5 Shipping — revise — mismatch — ship-time credit_used_cents recompute refreshes updated_at but does NOT bump account version (exception to §2.4 blanket recompute-bumps-version; contrast confirm/cancel) (app.py:499-502 vs touch(acct) 387/521).
- §3.8 Registrations — insert — ambiguity — a Customer listing a session's registrations sees only their own (app.py:864-870).
All monetary/temporal constants matched impl exactly; no formula revisions.

## Pipeline complete — 2026-07-15

All 9 steps done. Final: 8/8 sweep rounds green, 51/51 tests each. Artifacts: SCAFFOLD.yaml + 2 design files, PRD.md → PRD_FINALIZED.md (verbatim copy) → PRD_COMPLETED.md, workspace/implementation/ (56 routes, in-memory Flask), test_helpers/ + test_suite/ (51 tests).
