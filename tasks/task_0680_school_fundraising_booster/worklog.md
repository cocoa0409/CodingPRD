# Worklog — task_0680_school_fundraising_booster

## Step 1: Create Task Directory — 2026-06-27T03:31:07.000Z

Pre-assigned directory `tasks/task_0680_school_fundraising_booster/` already existed with `workspace/` created. No index scan performed (folder pre-assigned to avoid contention). Proceeding to Step 2.

## Step 2: Generate Scaffold (Expert) — 2026-06-27T03:51:20.000Z

All three required scaffold artifacts generated and pass `scaffold_lint.py` cleanly (SCAFFOLD.yaml 840 lines, SCAFFOLD_DIFFICULTY_DESIGN.yaml 1007 lines, SCAFFOLD_CORNER_DESIGN.yaml 1356 lines).

**Complexity profile**: primary archetype *ledger reconciliation* + secondary *posture-driven gating*; layers = dual-variant calc, cascading side-effects, optimistic concurrency, rate/threshold triggers. Topology is **flat** (`api_prefix: /fundraising`, all entities top-level with FKs in body), state-machine shape **parallel**, role model **peer_roles** with segregation of duties.

**Entity model (9)**: `Campaign` (aggregate root, posture-gated), `PrizeTier`, `Seller` (cross-referenced), `Product`, `Order` (parallel payment×fulfillment dimensions), `Pledge` (cyclic), `Volunteer`, `VolunteerShift`, `Disbursement`. Cross-aggregate FKs: `Order.seller_id`/`Pledge.seller_id → Seller`, `VolunteerShift.volunteer_id → Volunteer`.

**State machines (6)**: Campaign posture DRAFT→ACTIVE→CLOSED→RECONCILED→DISBURSED (+FROZEN); Order *payment* PENDING→PAID→REFUNDED and *fulfillment* PLACED→CONFIRMED→DELIVERED/CANCELLED (parallel); Pledge PROMISED↔RECORDED→COLLECTED (cyclic revision loop); Seller ACTIVE↔BLOCKED (cascading); VolunteerShift OPEN→BOOKED→RELEASED/CANCELLED. Two OCC concurrency rules on `Campaign.version` (reconcile, disburse).

**Key calculations (8)**: `campaign_gross` (final vs forecast dual-variant), `seller_credited` (final vs forecast dual-variant), `order_totals` (SUM-THEN-ROUND tax, pinned), `profit_split_reconciliation` (pinned-evaluation waterfall: split_base = product_revenue − vendor_cogs + pledge_revenue; school takes pct, vendor takes COGS + residual), `product_reserved_qty`, `volunteer_committed_minutes`, `pledge_amount_due` (cap clamp), `prize_tier_earned` (inclusive ≥ threshold).

**Validation/error catalog**: 13 ordered validations; **13 error codes** — all referenced and triggerable.

**RBAC roles (4)**: CampaignAdmin (opaque), Seller (entity_backed:Seller, ownership-checked), Treasurer (opaque, reconcile/disburse — segregated), SchoolOfficial (opaque, read-only).

**Instance counts**: §1.8 = **18** (2 × 9 difficulty rules); §1.9 = **49** (39 active corner instances + 10 `excluded_because` stubs). All 67 instance names unique; lint verdict: clean (49 endpoints, 9 entities, 18 §1.8 + 39 §1.9 instances, 376 calls scanned).

## Step 3: Copy Shared Files — 2026-06-27T03:51:37.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0680_school_fundraising_booster/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-27T03:56:57.000Z

Generated `workspace/PRD.md` (296 lines) from SCAFFOLD.yaml. Confirmed both design files (SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml) were NOT read.

**Section structure:**
- **§1 Introduction** — booster/PTO/PTA fundraising domain, forecast-vs-settled dual view, separation of duties.
- **§2 Global Specifications** (11 subsections): RBAC (4 roles), Response Structure (verbatim), Pagination, Common Resource Properties & Mutation Semantics, Computed Roll-Ups & Recompute-on-Read, Nested/Referential Validation Ordering, OCC, Request Shape & Constraints, Posture Gating/State Legality/Check Ordering, Monetary Precision & Rounding, the Logical Clock.
- **§3 Business Logic** (9 subsections): building/opening campaign, close cascade, seller roster/share-links/blocking, catalog & two-dimensional order lifecycle, pledges & revision loop, prize tiers & seller credit, reconciliation/profit-split/disbursement, forecast-vs-final views, volunteers/shifts/overlap guard.
- **§4 Endpoint Definitions** — 4-column table, all 49 endpoints.
- **§5 Error Code Catalogue** — 2-column table, all 13 error codes.

**Hard Contracts**: Field coverage PASS (65/65 fields), Rule coverage PASS (13 validations as 10-step ladder; 2 OCC rules; all state machines; 8 calculations; both cascades), Path purity PASS (376 tokens, 0 path leaks). §2.2 byte-identical to canonical source.

## Step 5: Generate Unit Tests — 2026-06-27T09:45:00.000Z

Generated complete test infrastructure for `task_0680_school_fundraising_booster` (Expert difficulty, School Fundraising & Booster Programs).

### Stage 1 — `test_helpers/` (9 files)
- `types.py` — entity TypedDicts (all primary resources carry `id/created_at/updated_at/version`) + status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (campaigns, prize-tiers, sellers, products, orders, pledges, volunteers, shifts, disbursements, clock)
- `api_errors.py` — `ApiErrorId` enum + HTTP status map (registered with framework)
- `assertions.py` — per-entity structural assertions
- `factories.py` — input-only payload factories
- `constants.py` — `TAX_RATE`, `MISSING_UUID` (v4-shaped, since the framework's all-zero `NON_EXISTENT_UUID` is not v4-shaped), test defaults
- `test_users.py` — opaque-role shared headers + `make_seller_headers()` builder for the one `entity_backed:Seller` role
- `fixtures.py` — composite setup helpers (campaign create/activate, active CATALOG/PLEDGE/EVENT, orders, pledges, reconcile/disburse lifecycle, volunteers/shifts)
- `__init__.py` — barrel export

### Stage 2 — `test_suite/` (conftest + 11 files, 75 tests)
- **Queue A (Difficulty):** all 18 instances across 9 rules, each with exactly 2 tests (36 tests) — files `test_01`–`test_05` covering dual-variant gross/credit, order-tax sum-then-round, profit-split waterfall, parallel order dimensions, pledge revision loop, close/block cascades, refund compensation, posture-vs-seller-block & reference-vs-stock precedence, cross-entity gating, prize-tier & stock boundaries, shift overlap (half-open + buffer).
- **Queue B (Corner):** all 39 non-stub instances, each with exactly 1 test (39 tests) — files `test_06`–`test_11` covering entities/CRUD/defaults, state transitions, calculation side-effects, validations, endpoints+RBAC, OCC/cascade/consistency.

### Verification performed
- All 75 tests collect cleanly; all `test_helpers` + `test_suite` byte-compile.
- Coverage audit: 18/18 difficulty instances (≥2 tests each), 39/39 non-stub corner instances (≥1 test each), all Design tags resolve to real `name:` entries. The 10 `excluded_because:` stubs were correctly **not** translated.
- Citation audit: every test's docstring carries exactly one `Design:` line; every quoted citation passes a literal whole-span grep of PRD.md (modulo whitespace, with backticks/em-dashes/arrows preserved) and contains a distinctive ≥8-word literal substring; no unbalanced backticks; no `skip`/`xfail`/`skipif` markers.

### Instances skipped
**None.** Every difficulty and non-stub corner instance survived the PRD-first two-condition filter — the PRD prose verbatim-covers and uniquely-derives each asserted rule (notably the §2.6/§2.9 explicit precedence ladder backs both priority-pair tests).

### Note for downstream
One difficulty instance (`campaign_forecast_vs_final_gross_diverge`) carries a literal expected value (`forecast_gross_cents == 13825`) in `SCAFFOLD_DIFFICULTY_DESIGN.yaml` that is arithmetically inconsistent with the PRD's own forecast formula for the given setup (the correct PRD-derived value is 15990: 10825 PAID + 2165 PENDING + 3000 RECORDED). The test asserts the PRD-correct computed value (15990) rather than the inconsistent scaffold literal, since asserting 13825 would fail a faithful PRD implementation. The seller-domain twin instance's literals (final 15825, forecast 24667) are internally consistent and were copied verbatim.

## Step 6: Generate Implementation — 2026-06-27T09:45:30.000Z

Generated a complete Python + Flask implementation in `workspace/implementation/`.

### Files (26 source files + launcher)
- `start.sh` — foreground launcher, guarded `pip install` (only if flask missing), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `app.py` — blueprint registration + error-envelope handlers; in-memory store starts **empty** on every boot (no seeding)
- Foundation: `db.py`, `errors.py`, `response.py`, `middleware.py`, `helpers.py`, `lookups.py`, `clock.py`, `serializers.py`
- `services/`: `calc.py` (all calculations/roll-ups), `mutations.py` (version-bump + close/block cascades), `validation.py` (precedence-ladder helpers)
- `routes/`: campaigns, prize_tiers, sellers, products, orders, pledges, volunteers, shifts, disbursements, clock_route

### Endpoints — all 50 from the PRD table implemented
Campaign lifecycle (create/get/list/report + activate/freeze/unfreeze/close/reconcile/disburse), PrizeTier, Seller (+credit-forecast, block/unblock), Product, Order (pay/confirm/deliver/cancel/refund), Pledge (record/revise/collect/cancel), Volunteer, VolunteerShift (book/release/cancel), Disbursement read-back, and `POST /_clock/set_current_utc`.

### Key design decisions
- **Response envelope** read verbatim from scaffold §1.0 / PRD §2.2: `meta`/`response_type`/`data`, error body `error_id`/`message`; pagination `limit`/`offset`/`total_count`/`has_more` (default 10, min 1, max 100).
- **Auth** headers `X-User-ID` + `X-User-Role` (roles `CampaignAdmin`/`Seller`/`Treasurer`/`SchoolOfficial`); Seller ownership = `X-User-ID == body.seller_id`.
- **Posture gate resolution**: PrizeTier, Seller, Product are created in DRAFT (campaign building blocks, no gate), while Order, Pledge, Volunteer, VolunteerShift creation require ACTIVE.
- **Validation precedence** enforced exactly (auth → rbac → path-exist → ref-exist → shape → OCC before state-legality → posture → seller-block → domain guards). OCC on reconcile/disburse uses `expected_campaign_version` (412).
- **Money** uses `Decimal` + `ROUND_HALF_UP`, rounded once: order tax = `round(gross × 0.0825)` (sum-then-round); reconciliation waterfall = `school = round(split_base × pct)`, `vendor = cogs + (split_base − school)` with split_base floored at 0.
- **Computed-on-read** roll-ups (campaign gross/forecast, seller credited/tier, product reserved_qty, volunteer committed_minutes); `school_profit_cents`/`vendor_payable_cents` frozen at reconcile.
- **Cascades** (close, seller-block) and refund compensation each give every touched child its own `version` bump + `updated_at`. `reconciled_at` from logical clock (default `2026-04-01T00:00:00Z`).
- Shift overlap uses half-open intervals with the buffer extending only the requested shift's start.

### Verification
Smoke-tested live via curl and in-process via Flask test client across the full lifecycle (order→pay→reconcile→disburse, tax/split, pledge cap/forecast, prize-tier boundary, refund compensation, close cascade, seller-block guard, OCC 412-before-409, insufficient-stock boundary, RBAC/auth/existence/shape errors, double-disburse/disburse-before-reconcile). `start.sh` boots fresh and serves HTTP 200 within ~1.5s.

## Step 7: Run Tests and Iterate — 2026-06-27T10:00:00.000Z

All 8 parallel rounds pass cleanly (75/75 each).

**Iterations run:** 2 (1 diagnostic baseline sweep + 1 verification sweep after fixes).

**Tests deleted:** None. Every failing test asserted a verbatim, uniquely-derivable PRD rule; all five failures were test-artifact bugs (setup ordering / wrong field read), not PRD-silent assertions.

**Fixes applied to test_suite/ (test setup is the test artifact under STEP 2):**

1. `test_04_gating_and_precedence.py` — `TestPostureGateBeatsSellerBlocked._setup_frozen_with_blocked_seller_order`: reordered to **block the seller before placing the order**. PRD §3.3's block cascade cancels a seller's PENDING+PLACED orders, so an order placed before the block was CANCELLED and pay tripped state-legality (`ERR_INVALID_STATE`, priority 7) before reaching the posture gate. Order create carries no seller-block guard (PRD §2.9 scopes that guard to pay/record/collect), so blocking first leaves the order PENDING+PLACED with a BLOCKED seller — letting both the posture gate (FROZEN) and seller-block guard apply, so the posture gate correctly wins with `ERR_CAMPAIGN_NOT_ACTIVE`.
2. `test_04_gating_and_precedence.py` — `test_pay_rejected_when_seller_blocked` and `test_pay_rejected_leaves_order_pending`: same block-then-place reorder so paying genuinely reaches the seller-block guard (`ERR_SELLER_BLOCKED`).
3. `test_09_validations.py` — `test_pledge_record_when_seller_blocked_returns_seller_blocked`: block-then-create reorder; the PRD block cascade cancels still-PROMISED pledges, so creating the pledge after the block keeps it PROMISED and recording it reaches the seller-block guard.
4. `test_01_money_calculations.py` — `test_credit_forecast_adds_pending_and_recorded`: changed the asserted field from `credited_cents` to `forecast_credited_cents`. PRD §3.8 names the forward-looking projection `forecast_credited_cents` (distinct from the final `credited_cents`); the value (24667) is unchanged and PRD-pinned.

**Fixes applied to test_helpers/:** None.

**Fixes applied to implementation/:** None. The implementation was faithful to the PRD throughout (block cascade, validation precedence ladder, and the `forecast_credited_cents` field on the credit-forecast read were all already correct).

**Final sweep:** All 8 parallel rounds passed `passed == total == 75`. Stale `results.*.json` artifacts removed from the implementation directory.

## Step 8: Finalize PRD — 2026-06-27T10:08:00.000Z

Produced `workspace/PRD_FINALIZED.md` (not skipped — Step 7 had 4 `test_suite/` fixes).

**Line counts / delta:** PRD.md = 296 lines (45,159 bytes); PRD_FINALIZED.md = 296 lines (46,002 bytes). Line delta 0 (both inline insertions within existing paragraphs); byte delta +843 (+1.87%).

**Changes (one per edit):**
- §3.4 (Catalog / paying an order) — insert — pinned that paying an order whose `fulfillment_status` is `CANCELLED` is rejected with `ERR_INVALID_STATE` at the state-legality step (priority 7), ahead of the posture gate and seller-block guard — `implementation/routes/orders.py:136-137`.
- §3.8 (Forecast vs Final, per-seller) — insert — pinned that the dedicated credit-forecast read returns the full canonical seller object (final `credited_cents` and `earned_prize_tier_id` over the final figure) plus the added `forecast_credited_cents`, and that `forecast_credited_cents` appears only on this read — `implementation/serializers.py:66-84`, `implementation/routes/sellers.py:67-71`.

**Items NOT edited (pure fixture bugs; PRD already uniquely determines):** diff items 2 and 3, and the posture-gate-beats-seller-block aspect of item 1 — all already pinned verbatim in §2.9 (line 124 scopes the seller-block guard to pay/record/collect; line 126 fixes the full precedence ladder), §3.3 (block cascade cancels PROMISED pledges), and §3.5 (recording requires ACTIVE seller). No silence, so no edits.

## Step 9: Complete PRD — 2026-06-27T10:14:00.000Z

Produced `workspace/PRD_COMPLETED.md` via full PRD-vs-implementation scan (always runs).

**Files:** Source `PRD_FINALIZED.md` (296 lines, 46,002 chars) → `PRD_COMPLETED.md` (296 lines, 47,706 chars). Char delta: **+1704**. All changes in-paragraph/in-cell; no lines added, no new sections.

**Counts:** 7 changes total — **4 ambiguity-pins**, **3 mismatch-revisions**.

**Per-change:**
- **§3.1 — revise — mismatch — DRAFT child-creation block.** Impl only posture-gates orders/pledges/volunteers/shifts (require ACTIVE); sellers, prize tiers, products carry no posture gate and are creatable in DRAFT. Also pinned the ACTIVE-creation gate fires in FROZEN/CLOSED too. — `validation.py:65`, `routes/orders.py:63`, `routes/pledges.py:46`, `routes/volunteers.py:28`, `routes/shifts.py:52`.
- **§3.1 — revise — mismatch — "Once ACTIVE, sellers, ... and products may all be created."** Revised to list only posture-gated children (orders, pledges, volunteers, shifts); sellers/prize-tiers/products already creatable in DRAFT.
- **§2.8 — revise — mismatch — `profit_split_pct` "expressed to two decimal places."** Impl enforces only `(0, 1]` range; revised to say two decimals is conventional, not enforced. — `routes/campaigns.py:48-50`.
- **§2.3 — insert — ambiguity — pagination out-of-range handling.** `limit` clamped to [1,100], negative `offset` clamped to 0, clamped limit echoed in `meta.limit`, non-integer raises `ERR_INVALID_REQUEST`. — `helpers.py:98-108`.
- **§3.6 — insert — ambiguity — `receipt_number` sequence.** Orders and pledges share one server-wide monotonic sequence starting at 1. — `db.py:26,33-35`; `routes/orders.py:145`, `routes/pledges.py:154`.
- **§3.5 — insert — ambiguity — `units_recorded` body validation on record.** Required integer ≥ 0, else `ERR_INVALID_REQUEST`. — `routes/pledges.py:99-101`.
- **§4 — insert — ambiguity — report endpoint shape.** `GET .../report` returns the campaign resource itself (identical shape to `GET .../campaigns/{id}`). — `routes/campaigns.py:106-110`.

**Pipeline complete.** All 9 steps executed; `PRD_COMPLETED.md` written and verified on disk.
