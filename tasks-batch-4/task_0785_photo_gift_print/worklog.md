# Worklog — task_0785_photo_gift_print

## Step 1: Create task directory — 2026-07-07T04:14:13.000Z

Pre-assigned folder tasks/task_0785_photo_gift_print used as-is (workspace/ subdir already present). Step 1 index scan skipped per orchestrator instructions.

## Step 2: Generate scaffold (Expert) — 2026-07-07T04:14:13.000Z

Everything validates cleanly. The scaffold is complete and consistent.

## Summary

Generated a complete **Expert**-difficulty scaffold for task_0785_photo_gift_print (Photo-Gift & Print Service, Shutterfly-style) at `/home/ubuntu/github/CodingPRD/tasks/task_0785_photo_gift_print/`. All three files pass `scaffold_lint.py` with **`VERDICT: clean lint`** (383 calls scanned across §1.8/§1.9, all FK reverse-reachability satisfied).

**Complexity profile:** primary archetype `pricing_engine` + secondary `workflow_orchestration`; layers `dual_variant_calculation`, `cascading_side_effects`, `rate_threshold_triggers`, `optimistic_concurrency`; hybrid topology, parallel state-machine shape, peer roles, immediate consistency.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **12 entities** — Customer, Address, Template, Project, Photo, Proof, Promotion, PromoWindow, SurgeWindow, Order, ProductionJob, Shipment
- **6 state machines** — Template (linear); Project (**cyclic** IN_PROOF→DRAFT revision loop); Order (**parallel** payment_status × fulfillment_status axes); ProductionJob & Shipment (linear-with-cancel); Proof
- **6 calculations** — line_subtotal (tiered), promo_discount (round-per-promo-then-sum), order_total (provisional/final variants), refund_amount (wallet/cash variants), promised_ship_date (estimated/scheduled surge variants), surge_day_remaining_capacity — **3 dual-variant** calcs across Order-money, Order-date, and Customer-money domains
- **21 validations** (priority-ordered), **1 concurrency rule** (OCC proof-generate-stale-project on Project.version, 412), **38 endpoints**, **34 errors**, **3 roles** (Customer entity-backed; CatalogAdmin & ProductionOperator opaque). Logical clock endpoint with the mandated `2026-03-01T00:00:00Z` default.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml:** all **9 rules × 2 = 18 instances**, every one with a fully executable `setup_api_calls` chain and formula-derived asserts pinned to code-verified literals (e.g. subtotal 22000 vs 22800 at the qty-25 tier boundary; promo discount 46 vs 47; refund 10299 vs 9349; promised dates 2026-06-13 vs 2026-06-17; store-credit conservation 20000→9701→20000).

**SCAFFOLD_CORNER_DESIGN.yaml:** **33 instances across 8 sections** (27 executable + 6 `excluded_because` stubs pointing to valid §1.8 instances), covering CRUD/not-found/required-field/system-field claims, invalid-transition & terminal-lockdown rejections, all remaining error triggers, RBAC denials + ownership + missing-auth, the **OCC stale-version 412** test, version increments, and immediate-consistency.

Note: endpoint (38) and error (34) counts sit modestly above the soft Expert ceilings — driven by the scenario's ~9 distinct sub-domains and the reverse-reachability GETs required for 10 FK relationships — but difficulty is carried by the coupling (dual-variant pricing/turnaround/refund, depth-3 cascades, parallel Order axes, OCC, and two conserved-quantity invariants), not by padding.

## Step 3: Copy INSTRUCTION.md — 2026-07-07T04:14:13.000Z

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-07-07T04:19:00.000Z

All three Hard Contracts pass. The PRD is complete at `workspace/PRD.md` (262 lines, ~5,800 words).

**Sections covered:**
- **§1 Introduction** — 3 paragraphs framing the design→proof→order→production→ship lifecycle and the three complexity sources (layered pricing, quote-vs-placement divergence, holiday surge).
- **§2 Global Specs** — 9 subsections: RBAC with all three roles and identity translation (Customer entity-backed; CatalogAdmin/ProductionOperator opaque); §2.2 emitted verbatim; pagination; common properties & versioning (with the `Photo` no-`version`/no-`updated_at` exception called out); money/precision/rounding; logical clock & closed-vs-half-open windows; OCC; validation ordering; cascading effects.
- **§3 Business Logic** — 8 workflow subsections (catalog/accounts, project design & auto-layout, proofing loop, pricing, placement & payment, production & shipping, cancellation/refund/reorder, promotions & surge admin).
- **§4** 4-column endpoint table (38 endpoints); **§5** 2-column error table (34 errors).

**Hard Contracts — all PASS:** field coverage (~80 names in backticks), rule coverage (all transitions, 6 calcs with constants, OCC, validation priority orderings, cascades), §3 path purity (0 violations across 366 §3 tokens).

**Notable design decisions:**
- Where validation-priority table and state-machine precondition lists disagreed on ordering, followed the **priority table**: auto-layout checks DPI gate before photo-count bounds; pay checks surge capacity before store-credit sufficiency; proof-gen checks project state before OCC.
- Treated `ERR_PROMO_MIN_NOT_MET` as a hard rejection on both quote and placement.
- All calculation formulas rendered as precise prose (finish surcharges, volume tiers, round-per-promo-then-sum, restocking fee, calendar-day turnaround, surge capacity).

## Step 5: Generate unit tests — 2026-07-07T04:39:00.000Z

Test infrastructure is complete and fully verified.

**Stage 1 — `test_helpers/`** (9 modules): types.py (14 enums + entity TypedDicts; Photo omits updated_at/version), api_client.py (all 38 endpoints), api_errors.py (all 34 error IDs + HTTP-status map), assertions.py, factories.py, constants.py, test_users.py, fixtures.py, __init__.py. fixtures.py threads entity-backed Customer identity through ownership-gated calls and provides composite builders (setup_approved_project, setup_paid_order, setup_order_with_label, setup_order_delivered, surge/clock helpers).

**Stage 2 — `test_suite/`** (7 files, 63 test functions)

Coverage (design-index-only):
- **Queue A (Difficulty): 36 tests.** All 17 translatable instances ≥2 tests each (refund and promo-window got 3).
- **Queue B (Corner): 27 tests.** All 27 non-stub instances, 1 test each. The 6 `excluded_because:` stubs not translated.

Instance skipped (1):
- **`Difficulty/priority_pair_validation_conflict/order_place_state_beats_fiscal`** — asserts ERR_PROJECT_NOT_APPROVED pre-empts ERR_PROMO_MIN_NOT_MET on POST /orders. PRD §2.8 lumps all §3 rules together without ordering them against each other → not uniquely derivable → skipped per Core rule. Its sibling (`shipment_existence_beats_production_state`) IS PRD-derivable (§2.8 places existence before §3) and covered by 2 tests. Corner stub `corner_promo_min_not_met_rejected` points at the skipped instance; left untranslated → ERR_PROMO_MIN_NOT_MET remains an uncovered PRD-precedence gap (not a test bug).

Verification: all 63 tests collect cleanly; test_helpers imports; all 70 quoted PRD citations verbatim; every test carries exactly one resolving Design: tag.

## Step 6: Generate implementation — 2026-07-07T04:39:00.000Z

Generated a complete Python + Flask implementation for the Photo-Gift & Print Service API. Impl-gen's own end-of-run check reported **63/63 passing** under `prd-bench-local-run --isolation per-test-server` (verification only; Step 7 sweep authoritative).

Files (in `workspace/implementation/`): app.py (single cohesive module), requirements.txt (flask>=3.0.0), start.sh (reads $PORT, binds 0.0.0.0, exec foreground, pip-install guarded on cheap `import flask`).

Coverage: 38 endpoints; all 33 error IDs wired to exact HTTP statuses; envelope (meta/response_type/data) + pagination (limit/offset/total_count/has_more) match scaffold verbatim.

Notable design choices:
- In-memory only (Store class of plain dicts), empty at boot, no seeding.
- Logical clock as aware UTC datetime (default 2026-03-01T00:00:00Z); created_at/updated_at use clock instant, api_request_timestamp uses wall-clock; monotonic _seq breaks created_at ties.
- Decimal + ROUND_HALF_UP for all money; promo discount round-per-promo-then-sum vs original subtotal, sorted PERCENT→FLAT→FREE_SHIP.
- Dual-variant calcs: quote (estimated, no surge/window/limit gates) vs placement/pay (scheduled surge extension + promo-window + per-customer-limit gates).
- Validation priority: auth → authz → existence L-to-R → ownership → body → state/business.
- Cascades: proof-approve (proof→project→photos depth 3), order-cancel (order→job→shipment VOID + refund/wallet credit); version bumped on every touched entity except Photo. Surge capacity computed dynamically from active jobs so cancel frees capacity.
- Global request lock + threaded=True.

## Step 7: Test/fix iteration loop — 2026-07-07T04:41:00.000Z

All 8 rounds passed cleanly: 63/63 in every round, zero failures, errors, or skips. The initial sweep is already green with no flakiness, so no diagnostic/fix iterations were needed.

Summary:
- Iterations run: 1 (the initial 8-round parallel stability sweep).
- Result: all 8 rounds passed 63/63 (failed=0, errors=0, skipped=0) with no flakiness across rounds.
- Tests deleted: none.
- Fixes applied to `test_helpers/`: none.
- Fixes applied to `implementation/`: none.

(Orchestrator verified all 8 results.{1..8}.json independently: every round passed=63 total=63 failed=0 errors=0.)

## Step 8: Finalize PRD — 2026-07-07T04:41:00.000Z

SKIPPED. Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, and 0 implementation/ fixes — the skip condition is met. PRD.md already determined every behavior the implementation exhibits at the sites Step 7 could exercise. No PRD_FINALIZED.md produced; Step 9 starts from PRD.md.

## Step 9: Complete PRD — 2026-07-07T05:03:00.000Z

Full PRD-vs-implementation scan complete. Started from PRD.md (Step 8 skipped, no PRD_FINALIZED.md).

- **Source vs completed**: PRD.md 262 lines / 39,248 chars → PRD_COMPLETED.md 262 lines / 40,647 chars (+1,399 chars). No lines added/removed — all in-paragraph inserts/revisions.
- **Ambiguity-pins**: 8 · **Mismatch-revisions**: 2 · Total 10 changes.

Changes:
- §3.1 Templates — revise — mismatch — named error for retiring a non-ACTIVE template as ERR_INVALID_PROJECT_STATE — app.py:585-586.
- §2.3 Pagination — insert — ambiguity — pinned out-of-range clamping (limit→[1,100], offset floored at 0), non-integer/missing → default — app.py:433-440.
- §2.3 Pagination — insert — ambiguity — pinned Customer sees only owned records on GET /projects,/orders,/shipments (silent scoping, not ownership error) — app.py:634-635,880-881,1095-1097.
- §2.2 Response Structure — insert — ambiguity — pinned api_request_timestamp uses real wall-clock, independent of logical clock — app.py:145-147,208-221.
- §3.4 Pricing — insert — ambiguity — pinned promised_ship_date returned as bare YYYY-MM-DD — app.py:414-417.
- §3.5 Placing/Paying — insert — ambiguity — pinned unknown promo code silently skipped, never an error — app.py:357-358.
- §3.7 Reordering — insert — ambiguity — pinned payment_method copied from source, no promo_codes carry over — app.py:1008,1015.
- §3.6 Production/Shipping — revise — mismatch — pinned shipment address_id supplied in body, existence-checked only (need not equal order's ship_address_id) — app.py:1055-1056.
- §3.5 Paying — revise — ambiguity — pinned violating either UNPAID or NEW precondition yields ERR_ORDER_NOT_PAYABLE — app.py:891-892.
- §3.8 Surge windows — insert — ambiguity — pinned turnaround_extra_days ≥ 0, capacity_per_day ≥ 1 — app.py:1229-1230.

Deliberately-skipped marginal item: quote endpoint checks only existence (not ownership) of optional ship_address_id while placement checks ownership — left unpinned as low-value and non-contradictory.

---

## PIPELINE COMPLETE

All 9 steps done. Final state: 63/63 tests passing across all 8 stability rounds. Deliverables present: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, test_helpers/, test_suite/, workspace/{INSTRUCTION.md, PRD.md, PRD_COMPLETED.md, implementation/}. PRD_FINALIZED.md intentionally absent (Step 8 skipped — clean first sweep).
