# Worklog — task_0320_jewelry_store_custom_repair

## Step 1: Create task directory — 2026-06-13T03:49:27.000Z

Created `tasks/task_0320_jewelry_store_custom_repair/` and `tasks/task_0320_jewelry_store_custom_repair/workspace/`. Output directory fixed by user (no auto-increment). Difficulty: Expert (passed to Step 2 scaffold generator only).

## Step 2: Generate scaffold (Expert) — 2026-06-13T04:13:20.000Z

Generated all three scaffold artifacts for **task_0320_jewelry_store_custom_repair** at the **Expert tier**, lint-clean (`scaffold_lint.py` verdict: *clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5*).

**Complexity profile**: primary archetype *ledger reconciliation*, secondary *workflow orchestration*; flat topology; cyclic/fork-join state shapes; peer-role RBAC; immediate consistency. Layers: dual-variant calc, cascading side effects, optimistic concurrency, derived-field reconciliation.

**Entities (12)**: Customer, InventoryItem, Workbench, Appraisal, CustomDesignOrder, RepairTicket, LayawayPlan, TradeInOffer, SpecialOrder, Payment (append-only, `common_fields:false`), WarrantyClaim, CreditLedgerEntry (append-only). 19 foreign keys, all reverse-reachable.

**State machines (7)**: CustomDesignOrder (cyclic revision loop, 10 states), RepairTicket (fork-join parts/no-parts + QC rework loop, 8 states), LayawayPlan, TradeInOffer, SpecialOrder, WarrantyClaim (branching), Appraisal. Plus **2 concurrency rules** (OCC on `InventoryItem.version` for appraisal-finalize and layaway-activate).

**Calculations (8)**: custom_order_totals (provisional vs final dual-variant; per-line-round-then-sum), layaway_schedule (projected-payoff vs settlement-refund dual-variant), trade_in_credit (tiered purity + nested min/max clamp), repair_total (rush-tier threshold, eval-order pinned), bench_window_overlap (half-open), appraisal_slot_overlap (closed + 30-min buffer), store_credit_balance (aggregation), insurance_replacement_value.

**Validations**: 18 prioritized rules (auth → role → existence → FK → request → uniqueness → payment-polymorphism → state → cross-entity state → business constraints → temporal overlaps → fiscal → OCC).

**Endpoints**: 69 (22 GET, 11 create, 36 action/transition). Exceeds nominal Expert band (20–32) because the scenario spans 8 full lifecycle workflows plus bench scheduling, each transition given a discrete, individually-RBAC'd endpoint for clean precondition/cascade testability.

**Error catalog**: 21 codes. **Roles (4)**: SalesAssociate (opaque), Goldsmith (opaque), StoreManager (opaque), Customer (entity_backed:Customer).

**Expert tier shaping of §1.8/§1.9**: §1.8 = **9 Difficulty Rules × 2 instances = 18 instances**, every rule's differentiation clause satisfied. §1.9 = **36 active corner instances + 5 `excluded_because` stubs** across all nine claim-extraction sections. All formula-derived assertions are pre-computed literals (e.g. final_total 325603, trade-in credit 153000, settlement refund 230000, rush surcharge 10000@50000 vs 15000@50001). 237 setup/trigger calls validated; all instance names unique across both files; all grounds references resolve.

## Step 3: Copy INSTRUCTION.md — 2026-06-13T04:13:20.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-13T04:18:53.000Z

**Output:** `workspace/PRD.md` (330 lines, 51370 bytes). Design files (SCAFFOLD_DIFFICULTY_DESIGN.yaml / SCAFFOLD_CORNER_DESIGN.yaml) withheld per contract.

### Section Structure
- §1 Introduction — multi-line-of-business reconciliation framing.
- §2 Global Specifications — 11 subsections: RBAC/auth, Response Structure (verbatim), Pagination, Common Properties/Identity, Nested Retrieval/FK Resolution, Monetary Precision, OCC, Validation Ordering, Store-Credit Ledger, Bench/Appraiser Scheduling (two overlap disciplines), Cross-Entity Cascades.
- §3 Business Logic — 10 subsections by entity lifecycle.
- §4 Endpoint Definitions — 4-column table, 69 endpoint rows.
- §5 Error Code Catalogue — 2-column table, 21 error IDs.

### Scaffold Coverage (verified programmatically)
- Entities (11): 75/75 field names verbatim. Payment + CreditLedgerEntry flagged `common_fields:false`.
- State machines (8): all 36 states; transitions with from/to + preconditions+error IDs + side effects (cross-entity cascades, warranty bubble-up, ledger refunds, spawned warranty repair). Cyclic revision loop (cap 3) and fork-join repair floor narrated.
- Calculations (8): dual-variant custom-order (round-per-line-then-sum), layaway schedule, trade-in tiered valuation (clamp last), repair rush tiers (inclusive 50000), bench half-open overlap, appraiser closed+30min-buffer overlap, store-credit aggregation, insurance replacement value. All constants embedded.
- Validations (16): priority ordering in §2.8; cross-entity guards + OCC.
- OCC: both rules express write endpoint + expected_inventory_item_version + ERR_STALE_VERSION (412) + ERR_VERSION_REQUIRED (422).
- Errors (21): in §2/§3 narrative AND §5 table. Roles (4): 3 opaque staff + Customer (entity_backed).

### Hard Contracts: Contract 1 (Field-Name Coverage 75/75) PASS; Contract 2 (Rule Coverage) PASS; Contract 3 (§3 Path Purity, 0 slash-paths) PASS. §2.2 byte-for-byte identical to reference.

## Step 5: Generate unit tests — 2026-06-13T04:34:04.000Z

Generated test infrastructure translating exclusively from the two design indices.

### Test files: 13 (conftest.py + 12 test_*.py)
- Queue A (depth): test_01–test_06 (calculations, non-linear state machines, cascades/invariants, validation precedence, cross-entity guards, scheduling overlap)
- Queue B (breadth): test_07–test_12 (entities CRUD, state transitions, calculations, validations, RBAC, cross-cutting/consistency)

### Test count: 72 total
- Queue A (Difficulty): 36 tests — all 18 difficulty instances covered with ≥2 tests each
- Queue B (Corner): 36 tests — all 36 non-stub corner instances covered with ≥1 test each

### Coverage audit
- 18/18 difficulty instances ≥2 tagged tests ✓; 36/36 non-stub corner instances ≥1 tagged test ✓
- 0 skipped instances — every instance passed PRD-first two-condition filter.
- 5 `excluded_because` stubs correctly NOT translated; all 5 cross-references resolve to real difficulty instances.
- Tags (72) == test functions (72): exactly one Design: line per test; no untagged/dual-tagged/freelance tests; no skip/skipif/xfail; no scaffold refs leaked.

### test_helpers/ modules: 9
`__init__.py`, `types.py`, `api_client.py` (one method per §4 endpoint), `api_errors.py` (21 errors + status map), `assertions.py` (per-entity + append-only-aware), `factories.py` (input-only payloads), `constants.py` (calc thresholds), `test_users.py` (3 opaque staff constants + make_customer_headers for entity_backed:Customer), `fixtures.py` (composite-setup driving all lifecycles from empty DB).

## Step 6: Generate implementation — 2026-06-13T04:34:04.000Z

Generated Python + Flask implementation in `workspace/implementation/`.

### Source files
- `start.sh` (foreground launcher: cd, guarded pip install, `exec python3 app.py`), `requirements.txt` (flask==3.0.3)
- `app.py` (10 blueprints, error handlers, reads $PORT default 10000, binds 0.0.0.0, threaded)
- `db.py` (in-memory dicts + id/seq/doc-number generators + new_record/touch), `errors.py` (ApiError + 21 error→status map), `response.py` (envelope + ISO-8601-UTC-3-digit), `middleware.py` (X-User-ID/X-User-Role auth, role gate, pagination)
- `services/calc.py` (Decimal + ROUND_HALF_UP), `services/common.py` (validators, FK/path resolution, OCC, ledger post/recompute, bench & appraiser overlap), `services/serialize.py` (per-entity projection; append-only exposes only id+created_at)
- `routes/` 10 modules (standing, appraisals, custom_orders, repair_tickets, layaway_plans, trade_ins, special_orders, payments, warranty_claims, credit_ledger)

### Endpoints: 69 routes (matches PRD §4)

### State machines & calculations
Fixed validation pipeline per handler (role → path existence → body FK → body well-formed → uniqueness → payment-target → invalid-state → cross-entity guard → domain rule → version-required → stale-version), status mutate + side effects + per-record touch. Machines: Appraisal, CustomDesignOrder (cyclic revision cap 3), RepairTicket (fork-join + warranty bubble-up), LayawayPlan, TradeInOffer, SpecialOrder, WarrantyClaim + payment-driven auto-transitions. Calcs with exact constants + round_half_up per step (per-line rounding before sum; floor installments; clamp-last trade-in; pinned rush tier eval, 50000-inclusive-MID). OCC via expected_version + expected_inventory_item_version.

### Constraint confirmation
- Storage in-memory only — verified no open()/SQLite/pickle/JSON-to-disk; all db writes inside handlers. Fresh boot total_count: 0 every collection.
- start.sh reads $PORT, binds 0.0.0.0, foreground via exec.
- Smoke-tested 75 assertions across lifecycles — all passing.

## Step 7: Test/fix iteration loop — 2026-06-13T04:40:02.000Z

**Iterations run:** 2 (baseline sweep → fix → confirming sweep). Final 8-round parallel sweep: all 8 rounds passed 71/71.

**Tests deleted (1):**
- `test_occ_stale_version_on_layaway_activate_returns_412` (in `test_suite/test_12_cross_cutting.py`) — **ERROR PRECEDENCE SILENCE** collapse (STEP 1b unique-derivability failure). Test asserts `ERR_STALE_VERSION` (412) for the loser of a two-layaway race on the same item. PRD §2.8 pins validation precedence: cross-entity state guards (item-availability) run **before** version checks. Per PRD §3.5, layaway activation atomically reserves the item (→ `RESERVED`) AND bumps its version. So plan B activating against a stale version hits the item-availability guard (`ERR_ITEM_NOT_AVAILABLE`) first — `ERR_STALE_VERSION` is never reachable alone (the version-bump never happens without the simultaneous status change). A faithful PRD-only implementer following §2.8 returns `ERR_ITEM_NOT_AVAILABLE`. The named relaxation exception is scoped to `ERR_INVALID_STATE`, not `ERR_ITEM_NOT_AVAILABLE`, so deletion (not relaxation) is correct. Scaffold rule: corner instance `cross_cutting_complexity_layers/occ_stale_version_on_layaway_activate_returns_412`.
- Contrast (kept + passing): `test_occ_stale_version_on_appraisal_finalize_returns_412` — appraisal finalize bumps item version WITHOUT changing item status (§3.4), so no cross-entity guard pre-empts and `ERR_STALE_VERSION` is uniquely derivable there. Structurally different in the PRD itself.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `implementation/`:** None. `routes/layaway_plans.py::activate_plan` (lines 88–92) already checks item-availability before the OCC version check, matching PRD §2.8 pinned ordering. Implementation was PRD-correct; the deleted test contradicted the PRD's own precedence rule.

## Step 8: Finalize PRD — 2026-06-13T04:42:01.000Z

**Outcome:** `PRD_FINALIZED.md` is a byte-for-byte copy of `PRD.md` — no edits warranted (verified `diff` = 0 lines). 330 lines → 330 lines, 0.0% delta.

**Change list:**
- No edits — PRD already pins the behavior. PRD §2.8 (validation precedence: cross-entity state guards run before version checks) combined with PRD §3.5 (activation requires item IN_STOCK before the OCC item-version check) uniquely determine that the loser of a two-layaway race on the same item returns `ERR_ITEM_NOT_AVAILABLE`, never `ERR_STALE_VERSION`. The deleted test contradicted the PRD's own precedence rule; the implementation was already PRD-correct.

**Per-edit pre-edit search log (no-edit justification at layaway-activate / OCC-precedence site):**
- (a) Subject: error precedence between cross-entity item-availability guard and inventory-item OCC version check at layaway activation.
- (b) Impl paths enumerated: `routes/layaway_plans.py::activate_plan` (l.79–104: ERR_INVALID_STATE → ERR_ITEM_NOT_AVAILABLE → require_item_version; atomically sets item RESERVED + bumps version); `routes/appraisals.py::finalize_appraisal` (l.84–104: ERR_INVALID_STATE → ERR_ITEM_SOLD → require_item_version; bumps version WITHOUT status change, so ERR_STALE_VERSION uniquely reachable — the structural contrast); `services/common.py::require_item_version` (l.150–158) + `require_own_version` (l.136–147: ERR_VERSION_REQUIRED precedes ERR_STALE_VERSION). Grep confirmed exactly two OCC-on-item callsites, both placing the cross-entity item guard before the version check, consistent with §2.8.
- (c) Wording adjustment: None — no edit; editing would risk a false universal claim where PRD is already correct.

## Step 9: Complete PRD scan — 2026-06-13T04:49:13.000Z

Full PRD-vs-implementation completeness scan. Base: `PRD_FINALIZED.md`.

**Source vs output:** PRD_FINALIZED.md (330 lines, 51,370 chars) → `PRD_COMPLETED.md` (330 lines, 53,237 chars). Char delta +1,867; line count unchanged (all in-paragraph inserts/revisions).

**Counts:** 8 changes — 5 ambiguity-pins, 3 mismatch-revisions.

**Per-change log:**
- §2.1 (User/RBAC) — revise — mismatch — Customer `X-User-ID` is recorded but never compared to `customer_id`; authorization is by role only, no read scoped to own records — `middleware.py:9-21`.
- §2.8 (Validation ordering) — insert — mismatch — on transition/action endpoints carrying body fields (assess, receive, approve-design), state legality (`ERR_INVALID_STATE`) is checked before body well-formedness (`ERR_INVALID_REQUEST`), reversing global pipeline for those ops — `routes/repair_tickets.py:116-119`, `routes/special_orders.py:99-102`, `routes/custom_orders.py:147-161`.
- §3.1 (Workbenches) — revise — mismatch — workbench `label` not unique-enforced; duplicate label accepted — `routes/standing.py:121-132`.
- §3.2 (Appraisal void) — insert — ambiguity — void recomputes item `latest_appraised_value_cents` in place WITHOUT bumping item `updated_at`/`version` (unlike finalize) — `routes/appraisals.py:107-122`.
- §3.5 (Layaway cancel) — insert — ambiguity — cancel from PENDING (no price/paid snapshot) yields `restocking_fee_cents` 0 and `settlement_refund_cents` 0 — `routes/layaway_plans.py:135-141`.
- §3.7 (Special order create) — revise — ambiguity — special-order deposit percentage pinned to 30% — `services/calc.py:31,115-116`.
- §3.8 (Warranty spawn) — insert — ambiguity — spawned warranty RepairTicket has null `promised_at`, `bench_id`, `scheduled_start`, `scheduled_end` — `routes/warranty_claims.py:84-88` + `routes/repair_tickets.py:20-33`.
- §3.9 (Payments) — insert — mismatch — payment derived-field refresh on parent does NOT bump parent `version`; version increments only on payment-driven auto-advance (QUOTED→DEPOSIT_PAID or ACTIVE→PAID_IN_FULL) — `routes/payments.py:62-78`.

**Unchanged:** all calculation formulas, rounding, scheduling overlap, state machines, error codes, pagination ordering already match impl exactly.

---

## Pipeline complete

Final state: 71 tests across 12 files, all passing in all 8 parallel rounds (per-test-server isolation). Artifacts present: SCAFFOLD.yaml (+DIFFICULTY/CORNER design), PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, test_helpers/ (9 modules), test_suite/ (12 files), workspace/implementation/ (Flask, in-memory).
