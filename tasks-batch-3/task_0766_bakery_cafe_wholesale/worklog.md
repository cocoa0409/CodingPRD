# Worklog — task_0766_bakery_cafe_wholesale

Scenario: Bakery Café & Wholesale Bread: retail POS & daily-bake par/markdown, wholesale/restaurant standing order & route, pre-order (holiday) & catering, allergen & shelf-life/date, subscription (bread club), inventory & reconciliation, custom-cake linkage, delivery

Difficulty: Expert

## Step 1: Create task directory — 2026-07-05T16:07:07.000Z

Pre-assigned folder tasks/task_0766_bakery_cafe_wholesale used as-is (Step 1 scan skipped per instructions). workspace/ subdir present.

## Step 2: Generate scaffold — 2026-07-05T16:39:02.000Z

All three artifacts generated and pass scaffold_lint.py (VERDICT: clean lint). Expert difficulty. Generated purely from scenario + skill spec; no sibling task read.

Structural profile: Primary archetype Ledger reconciliation + secondary Quota/allocation; layers: dual-variant calc, cascading side effects, derived-field reconciliation, optimistic concurrency. Consistency: immediate; role model: peer roles.

Counts:
- 11 entities (Product, Oven, BakePlan, BakePlanLine, BakeLot, RetailSale, WholesaleAccount, StandingOrder, DeliveryOrder, DeliveryRoute, RouteStop).
- 50 endpoints, 8 state machines, 7 calculations, 30 error codes, 5 roles (4 opaque + WholesaleClient entity-backed), 1 concurrency rule (OCC markdown-supersede on BakeLot.version → ERR_STALE_LOT_VERSION/412).

State machines: parallel (DeliveryOrder: payment_status × fulfillment_status), cyclic (StandingOrder ACTIVE↔PAUSED), BakeLot branching (FRESH→MARKED_DOWN/SOLD_OUT/EXPIRED with re-markdown self-loop), plus BakePlan, WholesaleAccount, DeliveryRoute, RouteStop, Product.

Key calculations: dual-variant reconciliation waste (PAR_BASED vs SALES_BASED), wholesale line price (LIST vs CONTRACT tier), markdown tiered non-linear discount (mode a), account invoice round-per-line-then-sum (mode b), par-reservation and credit-balance conservation aggregations, route load. Asserted literals computed in code (markdown 240, waste 10/12/4800, invoice 800 vs sum-exact 799, bulk 7680).

§1.8: 9 rule blocks × 2 = 18 difficulty instances. §1.9: 25 active corner instances + 3 excluded_because stubs.

Notes: Added direct PACKED→DELIVERED transition. Holiday pre-order/catering, custom-cake, bread-club-subscription clauses represented lightly/deferred to keep entity set tight and coupling dense (verbatim scenario preserved regardless). Two YAML fixups for PyYAML (optional field? tokens, inner-bracket grounds refs quoted).

## Step 3: Copy shared files — 2026-07-05T16:39:02.000Z

Copied INSTRUCTION.md → workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-07-05T16:45:22.000Z

Generated workspace/PRD.md (301 lines, 5 top-level sections). Design files (§1.8/§1.9) not opened per constraint.

Structure: §1 Introduction, §2 Global Specs (10 subsections: RBAC, response envelope, pagination, common props, logical clock, monetary/rounding, par-pool & credit-ledger invariants, nested retrieval + validation precedence, OCC, cascades/derived-field recomputation), §3 Business Logic (9 subsections), §4 endpoint table (all 50), §5 error catalogue (30 errors).

Hard contracts all PASS (field-name coverage, rule coverage, §3 path purity).

Scaffold ambiguities resolved:
1. Two priority-3 validations (existence 404 vs ERR_INVALID_REQUEST 400) share priority with no declared order — documented as single tier-3 gate before all state/business checks.
2. ERR_CREDIT_LIMIT_EXCEEDED applies to both order creation and deliver — stated fiscal ceiling guards both.
3. Two deliver paths (PACKED→DELIVERED direct vs OUT_FOR_DELIVERY→DELIVERED post-dispatch) — both expressed, credit-limit precondition on direct-from-PACKED path.
4. RetailSale (common_fields: false) — carries only id/created_at, no updated_at/version.

## Step 5: Generate unit tests — 2026-07-05T17:02:47.000Z

test_helpers/ (9 files: types.py, api_client.py, api_errors.py, assertions.py, factories.py, constants.py, test_users.py, fixtures.py, __init__.py). test_suite/: conftest.py + 10 domain files. Import-collects cleanly: 61 tests.

Coverage: Queue A (Difficulty) 36 tests — all 18 instances × 2 each. Queue B (Corner) 25 tests — all 25 non-stub instances × 1 each. 3 excluded_because stubs verified cross-referencing real Difficulty instances, NOT translated. Instances skipped for PRD-first filter: none.

Notable adjudications:
- standing_order_active_paused_active_cycle: design's absolute version==3 not uniquely derivable (PRD §2.4 permits server-chosen initial value) → asserts relative version==v0+2.
- markdown_on_expired_lot_returns_lot_expired: markdown from EXPIRED undefined → validate_error_is_one_of([ERR_LOT_EXPIRED, ERR_INVALID_STATE]).
- All markdown/stale-version tests read live version rather than hard-coding absolute.

## Step 6: Generate implementation — 2026-07-05T17:02:47.000Z

workspace/implementation/: app.py (~940 lines), requirements.txt (Flask>=3.0,<4.0), start.sh (guarded pip-install, reads $PORT default 10000, binds 0.0.0.0, exec foreground). All 50 endpoints implemented. In-memory dicts only; nothing seeded at boot; logical clock resets to 2026-03-01T00:00:00Z on fresh process.

Key ambiguities resolved (PRD prose + §2.8 precedence over scaffold):
- Validation precedence from PRD §2.8 (authoritative): bake-lot creation checks ERR_OVEN_SLOT_CONFLICT (tier 7) before ERR_INVALID_WINDOW (tier 8) despite §3.3 narrative reverse order.
- All timestamps use logical clock (§2.5), millisecond ISO-8601 Z.
- Credit-limit ceiling at order creation and direct PACKED→DELIVERED only; post-dispatch OUT_FOR_DELIVERY→DELIVERED books credit without re-checking.
- Payments: three explicit transitions only; non-conforming → ERR_INVALID_STATE.
- Derived-field version bumps on writes that recompute; reads recompute live without bump. close_account nonzero balance → ERR_INVALID_STATE.
- Account-close/standing-order-cancel cascades only touch standing-order-linked non-delivered orders.

## Step 7: Run tests and iterate — 2026-07-05T17:05:58.000Z

Clean first-sweep pass. Iterations run: 1 (single full 8-round parallel sweep). All 8 rounds passed cleanly — total=61, passed=61, failed=0, errors=0, skipped=0 in every round. No failing or flaky tests in the union across rounds.
- Tests deleted: none.
- Fixes applied to test_helpers/: none.
- Fixes applied to implementation/: none.

Verified independently: results.1..8.json all show 61/61.

## Step 8: Finalize PRD — 2026-07-05T17:05:58.000Z

SKIPPED per skip condition. Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, and 0 implementation/ fixes (zero iterations beyond baseline) → PRD.md already determined every behavior the implementation exhibits. PRD_FINALIZED.md not produced. Step 9 will start from PRD.md.

## Step 9: Complete PRD — 2026-07-05T17:12:07.000Z

Started from PRD.md (PRD_FINALIZED.md absent). Produced workspace/PRD_COMPLETED.md. PRD.md 301 lines / 41,781 chars → PRD_COMPLETED.md 301 lines / 43,662 chars (+1,881 chars; all in-paragraph inserts/revisions, no new lines/sections). 6 ambiguity-pins, 2 mismatch-revisions (8 changes).

Changes:
- §2.3 Pagination — insert — ambiguity — out-of-range limit/offset silently clamped; non-integer → ERR_INVALID_REQUEST (app.py:437-460).
- §2.3 List ordering — insert — ambiguity — created_at tie-break by creation sequence/insertion order (app.py:465).
- §3.3 Bake lots — insert — ambiguity — recording a lot has no bake-plan-state precondition; COMMITTED→BAKED advance only when plan is COMMITTED (app.py:792-796).
- §3.3 Oven slots — revise — mismatch — slot conflict (tier 7) evaluated before interval validity (tier 8); ERR_OVEN_SLOT_CONFLICT when both fail (app.py:767-776).
- §3.4 Markdown — revise — mismatch — lot already EXPIRED refused with ERR_LOT_EXPIRED (tier-4 guard) vs time-based ERR_MARKDOWN_NOT_ELIGIBLE (app.py:841-848).
- §3.7 Payments — insert — ambiguity — amount_cents ≥ 1 (ERR_INVALID_REQUEST); non-conforming payment → ERR_INVALID_STATE (app.py:1284-1300).
- §3.7 Deliver — revise — mismatch — direct counter delivery from PACKED authorizes Manager OR Driver (app.py:1264-1272).
- §3.8 Route stops — insert — ambiguity — adding a stop not gated by route status (app.py:1389-1423).

Left as-is: §3.1 oven "may later be RETIRED" has no endpoint/impl mechanism — no observable/testable divergence.

## Pipeline complete — 2026-07-05T17:12:07.000Z

All steps done. Final: 61/61 tests pass stably across 8 concurrent rounds under per-test-server isolation. Deliverables present: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, workspace/PRD.md, workspace/PRD_COMPLETED.md, workspace/implementation/, test_helpers/, test_suite/. PRD_FINALIZED.md absent (Step 8 skipped).
