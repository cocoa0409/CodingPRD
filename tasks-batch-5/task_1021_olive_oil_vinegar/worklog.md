# Worklog — task_1021_olive_oil_vinegar

## Step 1: Create task directory — 2026-07-14T18:00:27.000Z

Created ./tasks/task_1021_olive_oil_vinegar/ and ./tasks/task_1021_olive_oil_vinegar/workspace/ (pre-assigned ID, no scan).

## Step 2: Generate scaffold (Expert) — 2026-07-14T18:32:00.000Z

All three artifacts complete, parse cleanly (safe_load OK), pass scaffold lint with clean verdict.

Generated a fresh **Expert-difficulty** scaffold for task 1021 (Olive-Oil & Vinegar Tasting Shop), built purely from the scenario + skill spec (no sibling tasks consulted).

**SCAFFOLD.yaml** (§1.0–§1.7)
- Archetype: Quota/allocation + Pricing engine; topology `graph` (self-referential Product↔Product via ProductComponent); `parallel` state-machine shape; `peer_roles`.
- 11 entities: Member, Product, ProductComponent, Fusti, ReplenishmentOrder, WholesaleAccount, Order, Reservation, Subscription, TastingStation, TastingSession.
- 7 state machines — Order (parallel payment×fulfillment axes), WholesaleAccount (cyclic revision + suspend/reinstate loops), Fusti (compound/guarded auto-transitions), Reservation, Subscription (cyclic + renew self-loop), TastingSession (branching), ReplenishmentOrder.
- 6 calculations — dual-variant order pricing (provisional vs freshness-marked-down final), dual-variant fusti freshness (label vs sensory decay), gift-set bundle price (round-per-component-then-sum), order settlement (circular shipping/discount eval order pinned), FEFO fusti selector, loyalty accrual.
- 36 endpoints, 27 error codes, 19 ordered validations, 1 concurrency rule (subscription-create-stale-member OCC on Member.version), 5 roles (1 entity-backed Customer + 4 opaque), logical /api/_clock with mandated 2026-07-01T00:00:00Z default.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** (§1.8) — 18 instances, exactly 2 per each of the 9 Difficulty Rules, executable setup_api_calls chains + code-computed literal assertions (provisional 2495 vs final 2270; bundle 1810; freshness 77.78 vs 8.33; settlement discount 800 / shipping 995 / total 8195).

**SCAFFOLD_CORNER_DESIGN.yaml** (§1.9) — 43 instances across 8 taxonomy sections (37 active full recipes + 6 excluded_because stubs pointing to §1.8).

Lint: VERDICT clean; all 238 §1.8/§1.9 calls conform to §1.5, every §1.1 FK has reverse-reachability.

## Step 3: Copy INSTRUCTION.md — 2026-07-14T18:33:50.000Z

cp ./INSTRUCTION.md → tasks/task_1021_olive_oil_vinegar/workspace/INSTRUCTION.md

## Step 4: Generate PRD — 2026-07-14T18:41:15.000Z

Generated workspace/PRD.md. ~5,283 words; §2 = 10 subsections, §3 = 9 subsections; 36 endpoints documented (matches scaffold), 27 error codes (matches scaffold). Hard contracts (field coverage 70/70, rule coverage, path purity) all PASS. Did NOT read either design file.

Notable: doc-gen flagged `BUFFER_MINUTES` (station adjacency) as named-but-undeclared and left it unfabricated.

**Orchestrator patch (named-window/buffer-constant pattern):** design files pin BUFFER_MINUTES=15 with two Difficulty instances (`tasting_station_buffer_exact_gap_accepted`: gap==15 accepted; `station_buffer_window_conflict`: gap 10<15 → ERR_STATION_UNAVAILABLE). To keep those tests coverable, patched BOTH SCAFFOLD.yaml (validation priority 14 + error catalog condition) and workspace/PRD.md (§3 tasting-bar prose) to declare buffer=15 min with strict `gap < 15` collision semantics (exactly-15-minute gap accepted). SCAFFOLD re-verified safe_load OK.

## Step 5: Generate unit tests — 2026-07-14T18:58:13.000Z

test_helpers/ (9 modules): constants, types, api_errors (28 error IDs + HTTP map), api_client (one method per endpoint), test_users (opaque roles + make_customer_headers), factories, assertions, fixtures, __init__. Imports clean.
test_suite/: 11 test files + conftest, **73 tests total**, all collect (verified: 73 collected with PYTHONPATH=task_dir).
- Queue A (Difficulty): 36 tests — all 18 non-stub instances × 2 tests (9 rules × 2).
- Queue B (Corner): 37 tests — all 37 non-stub instances ≥1 test. 6 excluded_because stubs correctly not translated.
- 0 Design-tag errors; 0 coverage shortfalls; 43 distinctive docstring quotes survive literal grep of PRD.md.
- Instances skipped: none.
- One PRD-first adjudication (not a skip): `wholesale_order_requires_account_approved` scaffold triggers at POST /orders, but PRD §3.3 permits create with non-approved account (discount→0) and localizes ERR_WHOLESALE_NOT_APPROVED to pay (§3.4); both tests assert at pay endpoint, citing §3.4 verbatim.

## Step 6: Generate implementation — 2026-07-14T18:58:13.000Z

workspace/implementation/: app.py (single-module Flask), requirements.txt (flask==3.0.3), start.sh (foreground, reads $PORT default 10000, binds 0.0.0.0, exec python3 app.py).
- 36 route handlers (17 @app.get + 19 @app.post) — matches scaffold's 36 endpoints exactly. app.py ast.parse OK.
- In-memory dict stores only, empty on boot, no seeding; threaded=True.
- Fixed response envelope (meta/response_type/data), pagination in meta (limit 10/min1/max100, offset 0), sort created_at asc + insertion tiebreak.
- Auth X-User-ID/X-User-Role, 5 roles; ERR_UNAUTHENTICATED/UNAUTHORIZED/FORBIDDEN_NOT_OWNER.
- Clock default 2026-07-01T00:00:00Z; money integer cents Decimal ROUND_HALF_UP per-line; freshness 2dp; bundle round-per-component-then-sum; settlement subtotal→discount→shipping.
- Dual freshness (label vs sensory), FEFO fusti selection, reserve→commit→release/restock ledger, LOW/EMPTY auto-transition + auto ReplenishmentOrder, freshness markdown at fulfill, parallel Order axes, OCC version fields incl. expected_member_version subscription-create supersede.
- Impl self-smoke passed across full lifecycle (order create→pay→fulfill→return, wholesale tiers, gift-set bundle, freshness markdown, FEFO, replenishment, tasting buffer exactly-15 accepted/14 rejected, subscription OCC+supersede, allergen conflict, dup SKU, auth/role errors).
- Judgment call: order cancel + subscription/session transition invoked by wrong actor → ERR_UNAUTHORIZED (403), matching PRD explicit actor assignments.

## Step 7: Run tests and iterate — 2026-07-14T19:05:25.000Z

Ran as 2 waves of 4 via sweep.sh (host-saturation mitigation). All 8 rounds pass 73/73 with zero union failures (verified on disk: results.1..8.json all 73/73).

**Iterations run:** 2 (initial diagnostic sweep + one fix round → clean sweep).

**Tests deleted:** None. All 4 failures were unfaithful-artifact or implementation bugs, not PRD-silence.

**Fixes applied to test_helpers/ + test_suite/:**
- test_helpers/assertions.py — added assert_same_instant(actual, expected): compares two ISO 8601 timestamps by parsed UTC instant (tolerates trailing Z + any fractional precision). PRD §2.4 pins 3-fractional-digit rendering only for created_at/updated_at/api_request_timestamp; silent on derived date fields (best_by_date, tasting start_at), so exact-string equality against a zero-fractional literal asserted an unpinned format detail.
- test_suite/test_02_fusti_freshness.py (test_fusti_best_by_computed_from_harvest_plus_shelf_life) — replaced == "2027-06-25T00:00:00Z" with assert_same_instant; keeps PRD-pinned computed value (harvest + 540d), drops format demand. Impl returned 2027-06-25T00:00:00.000Z.
- test_suite/test_08_tasting_bar.py (test_session_exactly_15_minutes_after_prior_is_accepted) — same normalization for start_at; coverage (exactly-15-min gap → BOOKED) unchanged.

**Fixes applied to implementation/:**
- workspace/implementation/app.py (create_order) — removed create-time ERR_WHOLESALE_NOT_APPROVED rejection. PRD §3.3 states wholesale discount rate is zero unless APPROVED, so order creation with non-APPROVED account is permitted; APPROVED requirement enforced only at payment per §3.4 (check already present there). This was blocking setup of test_pay_wholesale_order_with_{submitted,draft}_account_rejected, which correctly assert rejection at pay.

Final: 73/73 across all 8 rounds. Step 8 NOT skipped (impl + test fixes occurred).

## Step 8: Finalize PRD — 2026-07-14T19:07:48.000Z

Produced workspace/PRD_FINALIZED.md. PRD.md = 255 lines, PRD_FINALIZED.md = 255 lines; one line revised in place (§2.4), 0% line-count delta.

- §2.4 — revise — pinned that every timestamp-/date-valued field the API emits renders as ISO 8601 UTC instant with exactly 3 fractional digits (enumerating derived date fields best_by_date, start_at/end_at) — impl app.py:105-109 (fmt_dt), applied at :265/:336.
- create_order ERR_WHOLESALE_NOT_APPROVED removal → No PRD edit; PRD §3.3/§3.4 already correct, impl fix aligned impl to prose. Nothing to pin.

Pre-edit search: confirmed fmt_dt is sole datetime formatter, applied uniformly with 3-digit fractional across all datetime emissions; wording restricted to "timestamp-/date-valued field the API emits" to avoid bleeding onto non-datetime fields.

## Step 9: Complete PRD — 2026-07-14T19:12:52.000Z

Produced workspace/PRD_COMPLETED.md. PRD_FINALIZED.md = 255 lines / 37,661 chars → PRD_COMPLETED.md = 255 lines / 39,080 chars (+1,419 chars, 7 prose lines revised). Ambiguity-pins = 6, mismatch-revisions = 2 (8 changes).

- §3.1 Members — revise — mismatch — PRD claimed email "unique and non-empty"; impl enforces only non-empty, no uniqueness → reworded to "system does not enforce email uniqueness" (app.py:460-474).
- §3.5 Fulfillment — insert — ambiguity — final settlement updates only final_subtotal_cents/final_total_cents; discount_cents/shipping_fee_cents retain provisional values (app.py:1089-1093).
- §3.6 Cancellations — revise — ambiguity — UNPAID/PENDING cancel by owning Customer, leaves payment_status UNPAID (only fulfillment_status→CANCELLED) (app.py:1154-1170).
- §3.6 Cancellations — insert — ambiguity — per-state actor rule: Customer for PENDING/RESERVED, ShopStaff for FULFILLED return; role mismatch → ERR_UNAUTHORIZED, ownership check first (app.py:1150-1166).
- §3.7 Wholesale — insert — ambiguity — enumerated decision values APPROVE/REQUEST_CHANGES/REJECT (app.py:803,817-832).
- §3.7 Wholesale — insert — ambiguity — suspend/reinstate via same decision endpoint with decision SUSPEND/REINSTATE + expected_wholesale_account_version (app.py:803-840).
- §3.8 Subscriptions — insert — ambiguity — renewal-order line-type from product_type (REFILL/BUNDLE/UNIT), no wholesale account/no wallet credit, retail pricing (app.py:1285-1333).
- §3.9 Tasting Bar — insert — ambiguity — premature NO_SHOW (before start) → ERR_INVALID_STATE (app.py:1463-1464).

Note: test_helpers/ and test_suite/ live at task root (not under workspace/); subagent aligned to implementation/ as directed — correct.

---
PIPELINE COMPLETE — task_1021_olive_oil_vinegar: 73/73 tests passing across 8 stability rounds. All 9 steps done.
