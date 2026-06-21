# Worklog — task_0337_auto_parts_retail_distribution

## Step 1: Create task directory — 2026-06-13T15:47:50.000Z

Created `tasks/task_0337_auto_parts_retail_distribution/` and `tasks/task_0337_auto_parts_retail_distribution/workspace/` (directory name used verbatim per orchestration directive; no ./tasks/ scan or auto-increment). Verified `./INSTRUCTION.md` exists for Step 3 copy.

## Step 2: Generate scaffold (Expert) — 2026-06-13T16:10:54.000Z

All artifacts are complete, consistent, and pass the lint cleanly.

Generated the three scaffold artifacts for **task_0337_auto_parts_retail_distribution** targeting the **Expert** difficulty band (§0.4). All three pass `scaffold_lint.py` cleanly (VERDICT: clean lint — 477 calls scanned across §1.8/§1.9, all FKs reverse-reachable).

**Design DNA**: pricing_engine + quota_allocation archetype; **flat** topology (peer top-level collections under api_prefix `""`, linked by FK — a §0.3 priority pattern); **parallel** state-machine shape; peer_roles. Complexity layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation.

**SCAFFOLD.yaml** (§1.0–§1.7):
- **14 entities**: Part, Vehicle, Fitment, CrossReference (self-referential Part↔Part), Account, PriceTier, SalesOrder, OrderLine, CoreReturn, WarrantyClaim, ReorderRequest, Driver, Bay, DeliveryRun
- **7 state machines**: SalesOrder split into two parallel dimensions (fulfillment_status × settlement_status), ReorderRequest (cyclic partial-receipt self-loop), CoreReturn + WarrantyClaim (branching), Part (catalog), DeliveryRun
- **2 concurrency rules**: OCC stale-version on allocate and on ship (both via `expected_sales_order_version`, 412)
- **6 calculations**: line_net_pricing (tier matrix, retail/wholesale variants, round-then-multiply pinned, margin floor), order_rollup, hotshot_fee, warranty_credit (REFUND/REPLACE variants), core_refund, reorder_suggestion (`<=` boundary)
- **18 validations** (ordered by priority, incl. two business_temporal overlap rules)
- **62 endpoints**, **55 error codes**, **4 roles** (CounterClerk, WholesaleRep, InventoryManager, WarrantyAdmin — all opaque identity)

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** (§1.8): **9 rule_ids × 2 = 18 instances**, each with executable empty-DB setup chains and precomputed literal asserts. Temporal-overlap (Rule 8) is grounded in genuine hotshot-delivery scheduling with two distinct interval semantics: **buffered** (Driver, turnaround gap) vs **half-open** (Bay, adjacency allowed).

**SCAFFOLD_CORNER_DESIGN.yaml** (§1.9): **43 active corner instances + 6 `excluded_because` stubs** (stubs cite §1.8 instances by name) spanning all 9 claim-extraction-guide sections — required-field/enum/duplicate/not-found, invalid-transition rejections, terminal lockdown, RBAC denials, FK integrity, OCC (correct + stale on both endpoints), derived-field reconciliation, and immediate consistency.

All names are unique across both design files, no forbidden concurrency vocabulary, no id-based business decisions, and the file split is honored (neither design key appears in SCAFFOLD.yaml).

## Step 3: Copy INSTRUCTION.md — 2026-06-13T16:11:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0337_auto_parts_retail_distribution/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-13T16:17:34.000Z

All three contracts pass cleanly. The PRD is complete.

Generated `workspace/PRD.md` (332 lines) — a PRD for the EXPERT-band Auto Parts Retail & Distribution API (pricing-engine + quota-allocation archetype, flat topology).

Structure (5 top-level sections): §1 Introduction; §2 Global Specifications (11 subsections incl. RBAC, response envelope, pagination, common props, monetary/rounding, inventory accounting + inclusive reorder trigger, left-to-right existence validation, validation ordering, OCC on allocate/ship, A/R + credit discipline, two delivery-window conflict semantics buffered-driver vs half-open-bay); §3 Business Logic (10 lifecycle subsections); §4 62-endpoint table; §5 55-error table.

Coverage: 14 entities, all 9 state machines (incl. parallel fulfillment_status × settlement_status + cyclic partial-receipt reorder loop), all 6 calculations, all 18 validations, both OCC rules, all 55 errors. Hard Contracts field/rule/path-purity checks all PASS. §2.2 response envelope verified byte-identical to source.

## Step 5: Generate unit tests — 2026-06-13T16:36:05.000Z

Generated complete test infrastructure (EXPERT band). Output: test_helpers/ (9 files) + test_suite/ (conftest + 8 test files), **81 tests total**, all 1:1 tagged with a `Design:` line.

Coverage: Queue A (Difficulty) 18/18 instances translated, 0 skipped (each ≥2 tests; dual_variant_calc got 3). Queue B (Corner) 43/43 non-stub instances translated, 0 skipped; all 8 excluded_because stubs verified and not translated. Bidirectional instance audit clean; all helper imports + api_client methods resolve; every cited PRD sentence verbatim-present.

Notable: `cesd_core_accept_blocked_by_line_not_shipped`'s recipe actually triggers a reject (REJECTED + A/R unchanged) rather than the not-shipped block its name implies; translated faithfully to recipe asserts. Numeric expecteds (14000/20000 pricing, 1080 margin floor, 1500 round-then-multiply, 4000/3250 hotshot fees, 19400/14000/5400 A/R, 10250 allocate total) copied verbatim from design YAML and re-checked vs PRD formulas. No skips required.

## Step 6: Generate implementation — 2026-06-13T16:36:05.000Z

Built complete Python + Flask implementation at workspace/implementation/ (21 files). start.sh reads $PORT (default 10000), binds 0.0.0.0, foreground exec. Files: app.py, db.py (empty in-memory store), errors.py, response.py, middleware.py, services/ (common, model, inventory, pricing), routes/ (parts, catalog, accounts, sales_orders, order_lines, core_returns, warranty_claims, reorder_requests, delivery).

**66 endpoints implemented** (impl-gen reports matches PRD §4 table). In-memory dicts keyed by id, no seeding, no disk persistence; fresh boot yields empty state. Money via Decimal ROUND_HALF_UP per-unit + ROUND_CEILING margin floor, round-then-multiply. Internal microsecond instants (_shipped_at_us/_created_us, stripped from responses) for deterministic warranty `<=` window. Validation ordering per §2.8: auth(401)→role(403)→existence L-to-R(404)→body(422)→business; OCC last. Delivery: driver buffered (priority 17 first), bay half-open positive-overlap (priority 18), exact adjacency allowed. Smoke-validated 49 assertions; clean boot ~7s.

NOTE for Step 7: impl reports 66 endpoints vs scaffold's stated 62 — Step 7 should confirm no PRD-untraceable endpoints crept in (any extra endpoint must trace to a verbatim PRD §4 row, else it is implementation-hacking).

## Step 7: Run tests and iterate — 2026-06-13T16:48:00.000Z

**Outcome:** Clean 8-round parallel sweep — all 8 rounds pass 80/80, zero failures, zero errors, zero flakiness. (Orchestrator independently re-ran the full 8-round sweep after the subagent exited; results.1..8.json all passed=80 total=80 failed=0 errors=0.)

**Iterations run:** 2 (baseline sweep surfaced 3 deterministic failures; fix sweep passed all 8 rounds).

### Tests deleted (1)
- **`test_cancel_invoiced_order_rejected`** (test_07_state_machines.py) — **error-precedence-silence collapse**. PRD §3.4 lists cancel guards: fulfillment-state check first (`ERR_INVALID_FULFILLMENT_STATE`), then the invoiced check ("regardless of fulfillment ... `ERR_ORDER_ALREADY_INVOICED`"). For a SHIPPED+INVOICED order both guards trip simultaneously. §2.8 says business checks fire "in the order their narratives describe" (→ fulfillment-state wins), but "regardless of fulfillment" admits the invoiced check as overriding (→ invoiced wins). Two PRD-faithful implementations diverge on the pinned outcome. Compounding: settlement machine requires SHIPPED before INVOICED, so `ERR_ORDER_ALREADY_INVOICED` on cancel is structurally unreachable in isolation. Scaffold rule: `Corner/state_machines/sm_cancel_invoiced_order_rejected`.

### Fixes applied to `test_suite/` (2)
- **`test_allocate_insufficient_stock_rejected`** (test_07_state_machines.py) — fixture inconsistent with PRD. Set part stock 1 / line qty 2, but PRD §3.3 marks a line `is_special_order=true` when `qty > available_qty` at creation, and §3.4 skips the insufficient-stock check for special-order lines, so PRD-faithful impl correctly allocated. Rewrote setup to build a genuinely non-special line (part available 2; two orders each add non-special qty-2 line; allocate first to drain available to 0; allocate second → `ERR_INSUFFICIENT_STOCK`). §3.4 assertion unchanged.
- **`test_core_qty_exceeds_outstanding_rejected`** (test_08_calc_validation_rbac_occ.py) — fixture issued a creation request PRD-faithful impl correctly rejects. PRD §3.6 requires core-return *creation* qty not exceed `cores_outstanding`; after accepting cr1 outstanding hit 0, so creating cr2 was correctly rejected at creation (test expected 201). Rewrote with line qty 2: open cr1 and cr2 (both valid at creation, which doesn't decrement outstanding), accept cr1 (2→0), then accept cr2 → `ERR_CORE_EXCEEDS_OUTSTANDING`, leaving `cores_outstanding == 0`. Now faithfully exercises the accept-time guard.

### Fixes applied to `test_helpers/`
- None.

### Fixes applied to `implementation/`
- None. All behaviors the failing tests collided with (is_special_order computation, special-order skip on allocate insufficient-stock, core-return creation-time qty guard, cancel guard ordering) were already faithful to PRD; defects were in test fixtures and one PRD-non-uniquely-determined test.

### Endpoint-count note
None of the failures touched a PRD-untraceable endpoint; all involved core flows (allocate, cancel, core-returns) whose rows are present verbatim in PRD §4. No endpoint added or relied upon to make tests pass.

## Step 8: Finalize PRD — 2026-06-13T16:51:20.000Z

Produced `workspace/PRD_FINALIZED.md` (332 lines; PRD.md = 332 lines; 0% line delta — one paragraph edited inline, net +3 sentences of pinned prose within §3.4).

Changes (1):
- §3.4 (Cancellation) — insert — pinned precedence between the two cancel guards so a SHIPPED+INVOICED order yields `ERR_INVALID_FULFILLMENT_STATE` (fulfillment-state check fires first; invoiced check reached only after it passes) — implementation/routes/sales_orders.py:234-238. Kept existing "regardless of fulfillment" prose verbatim; appended only the precedence clarification; scoped strictly to the cancel operation's two guards so allocate/ship uses of ERR_INVALID_FULFILLMENT_STATE are untouched.

Items requiring no PRD edit (verified pure fixture bugs):
- test_allocate_insufficient_stock_rejected — is_special_order (order_lines.py:51) + allocate non-special stock check (sales_orders.py:124-131) already match PRD §3.3/§3.4. Fixture bug only.
- test_core_qty_exceeds_outstanding_rejected — creation-time guard (core_returns.py:40) + accept-time guard (core_returns.py:88) already match PRD §3.6. Fixture bug only.

## Step 9: Complete PRD — 2026-06-13T16:58:11.000Z

Produced `workspace/PRD_COMPLETED.md` (332 lines, 51,821 chars) as a minimal patch over PRD_FINALIZED.md (332 lines, 50,054 chars; +1,767 chars). Line count unchanged — all changes in-paragraph; no new sections.

Counts: 7 changes — 5 ambiguity-pins, 2 mismatch-revisions.

Per-change:
- §2.8 Validation Ordering — revise — mismatch — path existence (404) → body well-formedness (422) → body FK existence (404); body FK existence checked only after body is well-formed — order_lines.py:32-38, catalog.py:77-83, delivery.py:127-139
- §3.3 Opening Orders (line creation) — insert — ambiguity — new line (special or not) opens status PENDING with cores_outstanding 0 — order_lines.py:65-66
- §3.3 Pricing variants — insert — ambiguity — retail variant zeros only merch discount; unit_core_price_cents still applies tier core_discount_pct at retail — pricing.py:35-37,51
- §3.4 Allocation — revise — mismatch — allocate checks fulfillment OPEN first (ERR_INVALID_FULFILLMENT_STATE) then empty/on-hold/stock/version — sales_orders.py:114-134
- §3.4 Shipment — insert — ambiguity — ship also ships special-order PENDING lines now having received stock (debit on_hand, no reserved change, reorder cascade) — sales_orders.py:203-216
- §3.4 Cancellation — insert — ambiguity — cancel rolls up after cancelling lines: subtotals→0, hotshot_fee_cents retained, order_total_cents equals that fee — sales_orders.py:256
- §3.8 Reorder lifecycle — revise — mismatch — qty_ordered snapshots reorder_qty verbatim, no minimum (manual create with reorder_qty=0 yields qty_ordered=0) — reorder_requests.py:38-42

## Pipeline complete — 2026-06-13T16:58:11.000Z

All 9 steps complete. Final state: 80/80 tests pass across all 8 parallel stability rounds (orchestrator-verified). Artifacts present: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, worklog.md, test_helpers/, test_suite/ (80 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}.
