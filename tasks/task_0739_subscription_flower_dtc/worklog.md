# Worklog — task_0739_subscription_flower_dtc

Scenario: 739. Subscription-Flower DTC (BloomsyBox style): subscription cadence & style/size, stem sourcing & cold-chain, recurring delivery & skip/pause, occasion/gift & message, substitution policy, vase add-on, churn/win-back, billing & renewal

Difficulty: Expert

## Step 1: Create task directory — pre-allocated

Task directory `tasks/task_0739_subscription_flower_dtc` and its `workspace/` were pre-created by the caller. Skipped ./tasks/ scan and auto-numbering per instructions. No new task directory created.

## Step 2: Generate scaffold — 2026-07-04

All checks pass. The scaffold is complete and lint-clean.

Generated: task_0739_subscription_flower_dtc (Expert difficulty)

Files (all under tasks/task_0739_subscription_flower_dtc/):
- SCAFFOLD.yaml — §1.0–§1.7 (no design keys) — 1349 lines
- SCAFFOLD_DIFFICULTY_DESIGN.yaml — single key scaffold_difficulty_design (§1.8) — 968 lines
- SCAFFOLD_CORNER_DESIGN.yaml — single key scaffold_corner_design (§1.9) — 1196 lines

Lint verdict (scaffold_lint.py, verbatim):
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.

Complexity profile: Primary archetype workflow_orchestration + secondary pricing_engine; layers: dual-variant calculation, cascading side effects, optimistic concurrency, scheduled actions. Topology hybrid; state-machine shape parallel; role model peer_roles; consistency immediate.

§1.1–§1.7 counts:
- 11 entities: Customer, Plan, Subscription, Shipment, StemLot, StemAllocation, CarrierRoute, Charge, WalletEntry, WinBackOffer, SubstitutionRule
- 5 state machines: Subscription (parallel lifecycle × billing axes, cyclic CANCELLED↔ACTIVE), Shipment (branching SOURCING→{SOURCED,SUBSTITUTED}), StemAllocation, Charge, WinBackOffer; 1 concurrency rule (OCC on Subscription.version at /change)
- 9 calculations: renewal_price (nested min/max), per_shipment_value, cancellation_refund (estimate vs actual dual-variant), stem_valuation (reserved vs committed dual-variant), shipment_stem_cost (round-per-line-then-sum), stem_availability, wallet_balance, cold_chain_deadline, loyalty_tier
- 10 validation priority rows (auth→authz→existence→body→state→OCC→referential→temporal→constraint→fiscal)
- 36 endpoints, 27 error codes, 4 roles (Customer=entity_backed; FulfillmentOps/BillingAdmin/PlatformAdmin=opaque)

§1.8 — 18 instances (2 per each of the 9 Difficulty Rules).
§1.9 — 9 sections, 49 corner instances (37 active + 12 excluded_because stubs).

Scaffold authored solely from scenario text + skill spec — no sibling task read.

## Step 3: Copy shared files — 2026-07-04

Copied ./INSTRUCTION.md -> workspace/INSTRUCTION.md (53 lines).

## Step 4: Generate PRD — 2026-07-04

Generated workspace/PRD.md (273 lines) from SCAFFOLD.yaml. Did NOT read the two withheld design files.

Section list: §1 Introduction; §2 Global Specifications (2.1 RBAC/4 roles, 2.2 API Response Structure, 2.3 Pagination, 2.4 Common Resource Properties, 2.5 Money/Quantities/Precision + conservation invariants, 2.6 Logical Clock, 2.7 Parallel Status Axes & Cascades, 2.8 OCC, 2.9 Request Validation Order 1–10, 2.10 Nested Resource Retrieval); §3 Business Logic (3.1 Catalog/Config, 3.2 Subscribing & First Cycle, 3.3 Pause/Resume/Change, 3.4 Skipping, 3.5 Fulfillment/Sourcing/Cold Chain, 3.6 Shipping & Delivery, 3.7 Renewals/Payments/Refunds, 3.8 Cancellation & Win-Back); §4 Endpoint Definitions (36/36); §5 Error Code Catalogue (27/27).

Hard contracts: Contract 1 Field-Name Coverage PASS (75/75); Contract 2 Rule Coverage PASS (0 missing across validations/OCC/state machines/calculations/side-effects/sibling-branch symmetry); Contract 3 §3 Path Purity PASS (336 tokens, 0 violations).

WATCH ITEM (doc-gen flag): scaffold referenced several policy constants WITHOUT numeric values (SKIP_CUTOFF_HOURS, WINBACK_DISCOUNT_PCT, WINBACK_WINDOW_DAYS, CYCLE_DAYS, FIRST_LEAD_DAYS, CADENCE_SPACING_DAYS, CLEAN_BUFFER_MINUTES). Doc-gen assigned deterministic values (CYCLE_DAYS=30, FIRST_LEAD_DAYS=2, cadence spacing 7/14/30, SKIP_CUTOFF=48h, WINBACK_DISCOUNT=0.20, WINBACK_WINDOW=30d, CLEAN_BUFFER=30min). If §1.8/§1.9 design files pinned different numbers, expect Step-7 test/PRD reconciliation. Also: "actual" cancellation refund measured against shipment statuses immediately BEFORE the cancel cascade.

## Step 5: Generate unit tests — 2026-07-04T13:35:00.000Z

Sanity check complete. Final tally:
- **Stage 1** (`test_helpers/`): 9 modules — types, api_client, api_errors, assertions, factories, constants, test_users, fixtures, `__init__` barrel.
- **Stage 2** (`test_suite/`): conftest + 8 test files, **71 tests** — all import cleanly and pytest collects them.
- **Difficulty coverage**: 17/18 instances at ≥2 tests each. One instance (`change_state_beats_fiscal`) intentionally skipped: PRD §3.3 only pins PAST_DUE→ERR_BILLING_PAST_DUE for change; it never states that lifecycle=CANCELLED alone gates change, so the "state-40-beats-fiscal-65" precedence claim on a CANCELLED+PAST_DUE subscription fails the two-reader unique-derivability filter.
- **Corner coverage**: 37/37 non-stub instances at ≥1 test. All 12 `excluded_because:` stubs correctly omitted.
- **Verbatim PRD citations**: every quoted sentence in every docstring survives a literal grep of `PRD.md` (whitespace-normalized).
- **Scaffold citations**: every `Design: …` tag resolves to a real `name:` in the source yaml.
- **No `pytest.mark.skip`/`skipif`/`xfail` marks**.

result: Generated `test_helpers/` (9 modules) and `test_suite/` (conftest + 8 files, 71 tests) at `/home/ubuntu/github/CodingPRD/tasks/task_0739_subscription_flower_dtc/`; 17/18 difficulty instances have ≥2 tests, all 37 non-stub corner instances have ≥1 test, one difficulty instance (`change_state_beats_fiscal`) skipped as gap because PRD does not uniquely derive that outcome, all PRD citations pass verbatim-grep, all scaffold tags resolve, pytest collects 71 tests cleanly.

## Step 6: Generate implementation — 2026-07-04T13:35:00.000Z

All files in place, imports clean, all 10 blueprints registered.

result: Implemented /home/ubuntu/github/CodingPRD/tasks/task_0739_subscription_flower_dtc/workspace/implementation/ as Python + Flask with guarded pip install in start.sh, empty in-memory store on boot, and 36 endpoints across 10 blueprints (plans, carrier_routes, substitution_rules, clock, customers, subscriptions, shipments, stem_lots, charges, win_back_offers) — smoke tests confirm OCC 412 on stale version, cold-chain EXPIRED at usable_until boundary, skip cutoff inclusive at 48h, cancel cascade with wallet refund + win-back offer, payment-fail billing cascade cancelling SCHEDULED shipments, and win-back redeem restoring ACTIVE with discount.

Key files:
- /home/ubuntu/github/CodingPRD/tasks/task_0739_subscription_flower_dtc/workspace/implementation/start.sh
- /home/ubuntu/github/CodingPRD/tasks/task_0739_subscription_flower_dtc/workspace/implementation/app.py
- /home/ubuntu/github/CodingPRD/tasks/task_0739_subscription_flower_dtc/workspace/implementation/services/calculations.py
- /home/ubuntu/github/CodingPRD/tasks/task_0739_subscription_flower_dtc/workspace/implementation/services/subscription.py
- /home/ubuntu/github/CodingPRD/tasks/task_0739_subscription_flower_dtc/workspace/implementation/routes/subscriptions.py
- /home/ubuntu/github/CodingPRD/tasks/task_0739_subscription_flower_dtc/workspace/implementation/routes/shipments.py

## Step 7: Test iteration loop — 2026-07-04T13:50:00.000Z

All 8 rounds pass: 70/70 each. Total went from 71 → 70 as expected (deleted 1 ambiguous test), and the 1 remaining failure was fixed. Clean sweep.

Sanity checks I ran:
- Re-verified all 8 result files show `passed=70 failed=0 errors=0 total=70`.
- Confirmed test count 70 = original 71 minus the 1 deleted test.
- Confirmed the ambiguous test I deleted was the only STEP-1b failure; the other failure was a genuine implementation bug fixed under STEP 3.

result: 8-round parallel sweep clean at 70/70; win-back redeem now surfaces ERR_OFFER_EXPIRED after clock advance, and the ambiguous 30-minute clean-buffer boundary test was deleted.

Summary:
- **Iterations run:** 2 (baseline sweep + verification sweep).
- **Tests deleted:**
  - `test_lot_hold_with_exact_clean_buffer_accepted` in `/home/ubuntu/github/CodingPRD/tasks/task_0739_subscription_flower_dtc/test_suite/test_03_shipment_fulfillment.py` — STEP 1b, ambiguous-boundary category. PRD §3.5 says "within a 30-minute clean buffer"; a faithful reader can interpret "within N" as either ≤ N (inclusive, gap == 30 conflicts) or < N (exclusive, gap == 30 accepted). Both readings are PRD-consistent, so the outcome is not uniquely derivable. (The test's own docstring conceded this: "a faithful reader could implement 'within N' as strictly less-than N".)
- **Fixes to `test_helpers/`:** none.
- **Fixes to `implementation/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_0739_subscription_flower_dtc/workspace/implementation/routes/win_back_offers.py` — `redeem_offer`: removed the pre-state-check lazy `OFFERED → EXPIRED` transition. PRD §2.9 orders State (5, `ERR_OFFER_NOT_REDEEMABLE`) before Temporal (8, `ERR_OFFER_EXPIRED`); flipping the offer to `EXPIRED` inside redeem preempted the temporal check and surfaced the wrong error_id. The lazy transition remains a read-endpoint concept per PRD §3.8.

## Step 8: Finalize PRD — 2026-07-04T13:55:00.000Z

Sanity check: file line counts are equal (273 vs 273). Only two lines changed, both in-place. Character delta modest.

result: Wrote /home/ubuntu/github/CodingPRD/tasks/task_0739_subscription_flower_dtc/workspace/PRD_FINALIZED.md — 273 lines vs PRD.md 273 lines (0% line-delta; 2 lines edited in place).

**Change log:**
- §3.5 — revise — clarified that the 30-minute clean-buffer boundary is inclusive-of-conflict (gap == 30 min conflicts; only gap > 30 min clears) — `implementation/routes/shipments.py:168` (`if gap1 > buffer or gap2 > buffer: continue`).
- §3.8 — revise — narrowed the lazy `OFFERED → EXPIRED` transition to read endpoints (list-offers) and stated that redeem does not preempt its state check with the lazy flip, so §2.9's ordering surfaces `ERR_OFFER_EXPIRED` for an expired-but-unobserved offer — `implementation/routes/win_back_offers.py:36-56` (no lazy flip inside redeem) + `implementation/services/views.py:213-219` (lazy flip only in `winback_view`).

**Per-edit pre-edit search log:**

Edit 1 (§3.5 lot-hold clean buffer):
- (a) Subject: lot-hold-conflict detection / clean-buffer boundary semantics.
- (b) Impl paths enumerated: `services/calculations.py:43` (`CLEAN_BUFFER_MINUTES = 30`); `routes/shipments.py:151-170` (only site comparing gaps to buffer, uses strict-`>` non-conflict); `services/views.py:164-165` (allocation view surfaces `hold_start`/`hold_end`, no buffer comparison). No other impl path references `CLEAN_BUFFER` or performs interval comparison against a buffer.
- (c) Wording adjustment: none — the sentence is scoped only to the reservation-refusal rule; the strict-`>` clause states the exact impl comparison and does not touch any other buffer-independent hold-window logic.

Edit 2 (§3.8 lazy transition scope):
- (a) Subject: `OFFERED → EXPIRED` lazy transition and its interaction with the redeem state gate.
- (b) Impl paths enumerated: `services/views.py:213-229` (`winback_view` — flips status when observed on read); `routes/customers.py:75-88` (`GET /customers/{id}/win-back-offers` — the sole list endpoint invoking `winback_view` on stored offers); `routes/win_back_offers.py:21-70` (`POST /win-back-offers/{id}/redeem` — no pre-state-check flip; state gate reads stored status; temporal gate reads `expires_at` at §2.9 step 8; final `winback_view` on response only wraps the already-`REDEEMED` offer, so lazy flip is a no-op there); `routes/subscriptions.py:339-341` (mint site, unrelated to lazy transitions).
- (c) Wording adjustment: replaced initial mention of "offer fetches and list-offers responses" with "the list-offers response" after confirming no single-offer GET endpoint exists. This keeps the wording consistent with all enumerated paths.

## Step 9: Complete PRD — 2026-07-04T14:05:00.000Z

Headings preserved. Sanity checks complete.

**Summary:**

Source: `PRD_FINALIZED.md` — 273 lines / 39,862 chars.
Target: `PRD_COMPLETED.md` — 273 lines / 44,902 chars (char-delta +5,040; no new sections, no new paragraphs).

Counts: ambiguity-pins = 15, mismatch-revisions = 0.

Changes:
- §2.3 Pagination — insert — ambiguity — pinned the two non-default sort orders (`/subscriptions/{id}/shipments` by `(cycle_index, scheduled_delivery_date, created_at)`; `/subscriptions/{id}/charges` by `(cycle_index, created_at)`) and pinned exact `has_more` semantics — implementation/routes/subscriptions.py:161, implementation/routes/subscriptions.py:177, implementation/response.py:33.
- §3.1 Catalog — insert — ambiguity — pinned that a `service_date` on carrier route is an ISO 8601 UTC instant with three fractional digits — implementation/routes/carrier_routes.py:22.
- §3.1 Catalog — insert — ambiguity — pinned `max_substitution_pct` range [0,1] rejected with `ERR_INVALID_REQUEST` — implementation/routes/substitution_rules.py:23.
- §3.1 Customers — insert — ambiguity — pinned that a duplicate email is rejected with `ERR_INVALID_REQUEST` and `full_name` non-empty — implementation/routes/customers.py:37, implementation/services/validators.py:32.
- §3.2 Subscribing — insert — ambiguity — pinned that a Customer must pass their own `X-User-ID` as `customer_id` else `ERR_NOT_OWNER` — implementation/routes/subscriptions.py:69.
- §3.2 Subscribing — insert — ambiguity — pinned that `renewal_price_cents` is recomputed on every read from live plan/config, not served from the stored snapshot — implementation/services/views.py:65.
- §3.3 Pause/Resume — insert — ambiguity — pinned that `paused_until` is left unchanged if `resume_date` omitted, and that pause/resume from wrong states surface as `ERR_INVALID_STATE` — implementation/routes/subscriptions.py:192, implementation/routes/subscriptions.py:209.
- §3.3 Change — insert — ambiguity — pinned that a missing `plan_id` in body raises `ERR_PLAN_NOT_FOUND` (404), and that change is legal only from `ACTIVE`/`PAUSED` else `ERR_INVALID_STATE` — implementation/routes/subscriptions.py:241, implementation/routes/subscriptions.py:245.
- §3.5 Fulfillment (sourcing) — insert — ambiguity — pinned that sourcing a shipment whose status is not `SCHEDULED` is `ERR_INVALID_STATE` — implementation/routes/shipments.py:104.
- §3.5 Fulfillment (allocations) — insert — ambiguity — pinned that `hold_end` must be at or after `hold_start` and that a body naming a non-existent lot returns `ERR_STEM_LOT_NOT_FOUND` (404) — implementation/routes/shipments.py:132, implementation/routes/shipments.py:137.
- §3.5 Fulfillment (confirm-sourced) — insert — ambiguity — pinned that missing/empty `from_variety`/`to_variety` in substitution branch is `ERR_INVALID_REQUEST` — implementation/routes/shipments.py:233.
- §3.6 Shipping — insert — ambiguity — pinned that a non-existent `route_id` returns `ERR_ROUTE_NOT_FOUND` (404) and `delivery_window_end` must be > `delivery_window_start` — implementation/routes/shipments.py:284, implementation/routes/shipments.py:289.
- §3.6 Delivery — insert — ambiguity — pinned that delivering a non-`SHIPPED` shipment (and analogous state-mismatch errors on confirm-sourced/ship/allocations) return `ERR_INVALID_STATE` — implementation/routes/shipments.py:141, implementation/routes/shipments.py:219, implementation/routes/shipments.py:294, implementation/routes/shipments.py:325.
- §3.7 Renewals — insert — ambiguity — pinned that renewal is legal only from `ACTIVE`/`PAUSED` (else `ERR_INVALID_STATE`), that scheduling uses the former `next_renewal_date` as start instant, and that renewal returns `201 Created` — implementation/routes/subscriptions.py:371, implementation/routes/subscriptions.py:381, implementation/routes/subscriptions.py:398.
- §3.7 Payments — insert — ambiguity — pinned `outcome` enum, that non-`PENDING` charge yields `ERR_INVALID_STATE`, and that `version` increments on the charge always and on the subscription on state-mutating branches — implementation/routes/charges.py:32, implementation/routes/charges.py:34, implementation/routes/charges.py:44, implementation/routes/charges.py:52.
- §3.7 Refunds — insert — ambiguity — pinned that `amount_cents >= 1` (integer) and that non-`CAPTURED` charge yields `ERR_INVALID_STATE` — implementation/routes/charges.py:63, implementation/routes/charges.py:65.
- §3.8 Cancellation — insert — ambiguity — pinned that non-`ACTIVE`/`PAUSED` cancel yields `ERR_INVALID_STATE`; pinned `refund_destination` recognition, wallet-vs-charge split (full wallet credit, capped charge bump), `related_charge_id` semantics, omit/zero-refund behavior, and cancel_reason update rule — implementation/routes/subscriptions.py:292, implementation/routes/subscriptions.py:310-329, implementation/routes/subscriptions.py:344.
- §3.8 Win-back redeem — insert — ambiguity — pinned path/body existence-check order (`ERR_OFFER_NOT_FOUND` then `ERR_SUBSCRIPTION_NOT_FOUND`) and that non-`CANCELLED` subscription yields `ERR_INVALID_STATE` — implementation/routes/win_back_offers.py:26, implementation/routes/win_back_offers.py:34, implementation/routes/win_back_offers.py:46.
- §3.8 Win-back list — insert — ambiguity — pinned that lazy `EXPIRED` transition is applied before the `status` filter — implementation/routes/customers.py:86.

result: PRD_COMPLETED.md written at /home/ubuntu/github/CodingPRD/tasks/task_0739_subscription_flower_dtc/workspace/PRD_COMPLETED.md with 18 in-paragraph ambiguity-pins (0 mismatch-revisions); 273 lines, +5,040 chars vs PRD_FINALIZED.md.
