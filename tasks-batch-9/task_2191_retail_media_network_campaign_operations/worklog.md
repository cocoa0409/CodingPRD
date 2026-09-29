# Worklog — task_2191_retail_media_network_campaign_operations

## Step 1: Create Task Directory — 2026-08-31T00:00:00.000Z

Created `tasks/task_2191_retail_media_network_campaign_operations/` and `tasks/task_2191_retail_media_network_campaign_operations/workspace/` (pre-allocated directory name used verbatim; no index scan performed).

## Step 3: Copy Shared Files — 2026-08-31T00:00:00.000Z

Copied `INSTRUCTION.md` to `workspace/INSTRUCTION.md`. (RESUME AUDIT: verified byte-identical to project-root `INSTRUCTION.md` via `diff`; no regeneration needed.)

## RESUME AUDIT — 2026-08-31T00:05:00.000Z

Prior run crashed after Step 1/Step 3. Artifacts present on disk at resume: `worklog.md`, `workspace/INSTRUCTION.md` (valid). Missing: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `workspace/PRD.md`, `test_helpers/`, `test_suite/`, `workspace/implementation/`, `workspace/PRD_FINALIZED.md`, `workspace/PRD_COMPLETED.md`. Pipeline resumes at Step 2.

## Step 2a: Generate SCAFFOLD.yaml — 2026-08-31T21:20:00.000Z

SCAFFOLD.yaml is complete and clean. 3,094 lines, §1.0–§1.7 only (no scaffold_difficulty_design / scaffold_corner_design key).

Counts: entities 15 (flat topology, api_prefix /rmn; AuctionBid and EngagementEvent are the two common_fields:false ledger entities; 26 FKs). state machines 13 (Campaign carries parallel delivery_status and billing_status; cycles on advertiser suspend/reinstate, plan revision + exhaust/top-up, fund freeze/unfreeze, campaign pause/resume, invoice dispute/adjust, dispute review/info-request, study invalidate->re-measure; four depth-3 cascades). concurrency rules 6 (all OCC/HTTP 412 stale expected_<parent>_version on Advertiser, Campaign x2, LineItem, TradeFundAccount, Invoice). calculations 18 (3 dual-variant pairs: attribution LAST_TOUCH/FRACTIONAL, holdout GEO/USER, off-site LOGGED/REPORTED; combinatorial modes; two interval-overlap geometries; two conserved-quantity invariants). validations 79, strictly ordered priorities 1-79 with three priority-conflict pairs. endpoints 101 (includes POST /rmn/_clock/set_current_utc with mandatory 2026-08-01T00:00:00Z startup default, and POST /rmn/_ops/run-daily-checkpoint). error codes 79 (catalog == validation-referenced set exactly). roles 8: NetworkAdmin, AccountManager, AdvertiserUser (entity_backed:Advertiser), CreditAnalyst, MeasurementAnalyst, BillingOps, CatalogOps, AuctionService; role_model segregation_of_duties.

Verification: yaml.safe_load parses; scaffold_lint.py clean; zero forbidden concurrency vocabulary; every endpoint role declared in §1.7; all triggers/applies_to resolve to declared endpoints; no ID-based ordering (created_at ASC used).

Process note: YAML flow sequences reject unquoted trailing `?`, so optional-field markers in `input:` lists are quoted strings.

## RESUME AUDIT #2 — 2026-08-31T23:05:00.000Z

Second resume. Re-verified on disk:
- `SCAFFOLD.yaml` — VALID. 3,094 lines / 238,925 bytes. `yaml.safe_load` parses clean; 13 top-level keys ending at `roles:`; counts confirmed: entities 15, state_machines 13, concurrency_rules present, calculations 18, validations 79, endpoints 101, errors 79, roles 8. Neither `scaffold_difficulty_design` nor `scaffold_corner_design` key present (correct). File terminates mid-`roles:`-list at a complete AuctionService block — not truncated.
- `workspace/INSTRUCTION.md` — VALID, byte-identical to project-root `INSTRUCTION.md` (`diff` clean).

MISSING / to regenerate: `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `workspace/PRD.md`, `test_helpers/`, `test_suite/`, `workspace/implementation/`, `workspace/PRD_FINALIZED.md`, `workspace/PRD_COMPLETED.md`.

Pipeline resumes at Step 2b (§1.8 design file), then Step 2c (§1.9), then Steps 4 → 9. Step 2a (SCAFFOLD.yaml) NOT redone.

## RESUME AUDIT #3 — 2026-08-31T23:30:00.000Z

Third resume. Re-verified on disk before doing any work:
- `SCAFFOLD.yaml` — VALID. 3,094 lines / 238,925 bytes. `yaml.safe_load` parses clean; 13 top-level keys (`scenario` … `roles`); counts confirmed: entities 15, state_machines 13, concurrency_rules 6, calculations 18, validations 79, endpoints 101, errors 79, roles 8. Neither design key present (correct). Not truncated.
- `workspace/INSTRUCTION.md` — VALID, byte-identical to project-root `INSTRUCTION.md` (`diff` clean).
MISSING at audit: `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `workspace/PRD.md`, `test_helpers/`, `test_suite/`, `workspace/implementation/`, `workspace/PRD_FINALIZED.md`, `workspace/PRD_COMPLETED.md`.

Step 2a (SCAFFOLD.yaml) NOT redone. Resumed at Step 2b/2c, and launched Step 4 in parallel with them (Step 4 reads SCAFFOLD.yaml only and is forbidden from reading either design file, so it carries no dependency on 2b/2c).

## Step 2b/2c: design-file generation — watchdog stalls (process note) — 2026-09-01T00:00:00.000Z

Two successive attempts to generate `SCAFFOLD_DIFFICULTY_DESIGN.yaml` as a single agent were killed by the harness stream watchdog ("no progress for 600s"), producing no file both times. Root cause: §1.8 for this scaffold requires ≥18 instances, each with a full structured `setup_api_calls` chain plus code-computed numeric asserts against 18 calculations — the agent reasoned for >10 minutes without emitting a tool call. The first `SCAFFOLD_CORNER_DESIGN.yaml` attempt stalled identically.

Mitigation applied: (1) instruct agents to write output EARLY and extend incrementally (one instance per Edit call) so the stream stays alive; (2) shard §1.8 across three concurrent agents, three `rule_id` blocks each, writing `SCAFFOLD_DIFFICULTY_DESIGN.part{1,2,3}.yaml`, merged by the orchestrator in canonical rule order. Shard split: part1 = dual_variant_calc / combinatorial_formula / non_linear_state_machine; part2 = transitive_cascade / priority_pair_validation_conflict / boundary_precision_check; part3 = cross_entity_state_dependency / resource_temporal_overlap / compensating_invariant. Instance `name:` prefixes are rule-specific to guarantee global uniqueness across shards.

## Step 4: Generate PRD — 2026-09-01T00:05:00.000Z

PRD complete and verified.

**Output:** `workspace/PRD.md` — **606 lines, ~20,830 words.**

Section structure: §1 Introduction; §2 Global Specifications & System-Wide Principles (2.1 RBAC; 2.2 API Response Structure — byte-identical paste, verified programmatically; 2.3 Pagination; 2.4 Resource Identity/Timestamps/Version Counters; 2.5 Logical Clock and Daily Checkpoint; 2.6 Numeric Precision and Rounding; 2.7 Stale-Parent Rejection on Child Creation; 2.8 Interval Geometry: Flights, Windows and Buffers; 2.9 The Two Conservation Ledgers; 2.10 Parallel Status Dimensions and Cascade Depth; 2.11 Segregation of Duties Across Approval Chains; 2.12 Rejection Precedence — all 79 checks numbered in scaffold priority order with error ID + HTTP status); §3 Business Logic & Workflows (3.1 Advertiser Onboarding/Credit Exposure/Agency Umbrella; 3.2 Fiscal-Period Funding; 3.3 Campaign Construction/Review/Delivery Dimension; 3.4 Inventory/Line Items/Slot Occupancy Arbitration; 3.5 Catalog Eligibility/Product Assignments/Out-of-Stock Chain; 3.6 The Sponsored Placement Auction; 3.7 Closed-Loop Attribution and Incrementality Measurement; 3.8 Invoicing/Trade Fund Deduction/Billing Dimension; 3.9 Measurement Disputes and Reporting SLA); §4 Endpoint Definitions (101-row table); §5 Error Code Catalogue (79-row table).

Coverage audit: entities 15 (180 fields) — automated check 0 of 180 field names missing from backticked prose; `AuctionBid`/`EngagementEvent` explicitly stated to carry only `id` + `created_at`. state_machines 13 — every transition, both fork branches, all preconditions and side effects narrated; all cycles and terminal states named. concurrency_rules 6 — §2.7 as a general stale-version principle (no forbidden race vocabulary) plus the mandatory `expected_*_version` field named at each creation site; §2.12 items 20–24 map each to its 412. calculations 18 — all constants pinned (0.60/0.25/0.10, tier multipliers 1.10/1.00/0.90, 1.96, 168h washout, SLA bases 72/120/96/240, 24h floor, 48h extension, tier rates 0.20/0.35/0.50, NET_TERMS 30, GRACE 15, WRITE_OFF 60, MIN_TOP_UP 50000, MIN_ACCRUAL 1000, MIN_APPROVAL_CREDIT 100000, MAX rounds 3/2/2). validations 79 — §2.12 numbered 1–79 in strict priority order, restated in situ in §3. endpoints 101 — §4 table verified 101 rows; automated check 0 of 149 distinct inputs missing from §3 prose. errors 79 — §5 table; all 79 IDs also in §2.12. roles 8 — §2.1 plus per-capability role lists in §3 and §4 column.

Hard Contracts: Field-Name Coverage pass (0 missing). Rule Coverage pass. §3 Path Purity pass — zero HTTP methods, zero URL paths, zero symbolic operators anywhere in §3.

Zero-Silence decisions made explicit (scaffold-internal contradictions resolved; derived-field definitions and calculations outrank narrative side effects; state-machine tables outrank endpoint descriptions for legal from-states; endpoint `roles` lists authoritative for RBAC):
1. Advertiser suspension stamps `pause_reason = MANUAL` (no `ADVERTISER_SUSPENDED` member exists) and leaves `occupancy_count` and plan `reserved_cents` unchanged.
2. Onboarding submission lands in `KYC_REVIEW` (transiently through `SUBMITTED`) from both `DRAFT` and `CREDIT_HOLD`; `decision=START_REVIEW` valid only from an observed `SUBMITTED`.
3. Plan approval lands `APPROVED`, promoted to `ACTIVE` in the same request only when clock is at/after `window_start_at` and advertiser is `ACTIVE`.
4. 3rd revision round does not error — arriving at `PENDING_APPROVAL` with `revision_round == 3` makes return-for-revision terminate the plan in `REJECTED` and release the fund reservation.
5. Campaign archive legal from-states `SCHEDULED` or `COMPLETED` only; `SCHEDULED` branch requires `delivered_spend_cents == 0`, is the exact compensating release, leaves `billing_status` at `UNBILLED`.
6. Study invalidate from `MEASURING` or `PUBLISHED`; `MEASURING` branch does no campaign recomputation; invalidation files no dispute and moves no invoice; `DATA_DEFECT` stays re-measurable within `window_end_at + 30 days`.
7. Dispute escalate from `UNDER_REVIEW`/`INFO_REQUESTED`; a 3rd info request is refused (409) rather than auto-escalating; round exhaustion (`info_request_count == 2`) reached by explicit escalation setting `escalation_level` to 2 outright, any other explicit escalation increments by 1. Withdraw from `SUBMITTED`/`INFO_REQUESTED`. Resolve from `UNDER_REVIEW`/`ESCALATED` (level 1 unrejectable; level 2 rejectable).
8. `run_reconciliation` defaults to false — unfreeze goes straight to `OPEN`, leaves `last_reconciled_at` untouched; true passes through `RECONCILING` and stamps it.
9. `EngagementEvent.billable_cents` is 0 at creation, populated only at auction settlement; recording an engagement alone moves neither `spend_cents` nor `delivered_spend_cents`.
10. Supplied-but-derived inputs: `channel` on engagements and `match_type` on attributed sales must be supplied but persisted value is always derived; `attribution_model_applied` and `eligibility_status` at product creation never taken from request.
11. Boundary inclusivity pinned everywhere: catch-up at `pacing_index` strictly below 0.8000; reconciliation basis `LOGGED_BASIS` at exactly 2.00; washout passes at exactly 168h; significance true at exactly 1.9600; attribution window strictly less than window length; SLA breach asymmetric (response exactly at `sla_due_at` on time, absence exactly at `sla_due_at` a breach); tier ratios `TIER_1` at exactly 0.50, `TIER_2` at exactly 0.20.
12. Rounding order pinned: clearing price rounds up once before the floor/effective-bid clamp; CPM remainder distributed one cent at a time by `occurred_at` then `created_at`, never by `id`; per-row attribution credit rounds before campaign summation; waterfall STEP 8's two rounded quantities round before the four-way minimum; dispute uplift cap rounds before the outer minimum; pacing base truncates before the `daily_cap_cents` clamp.
13. `roas`/`iroas` are 0.0 when `delivered_spend_cents + offsite_reported_spend_cents` is 0 (4 dp).
14. `no_fill_reason`: `NO_ELIGIBLE_CANDIDATES` when `candidate_count == 0` or all rows `FILTERED_INELIGIBLE`, else `ALL_BELOW_FLOOR`; `BUDGET_EXHAUSTED` is a declared member the award rule never produces (stated explicitly).
15. Invoice write-off suspends an `ACTIVE` advertiser with `suspension_reason = CREDIT_BREACH`, fully reverses the deduction, unfreezes an `OVERDRAWN` pool. Adjust re-runs the waterfall from STEP 6 with `dispute_credit_cents` = upheld sum + supplied `adjustment_amount_cents`, leaving steps 1–5 as issued. Dispute-filed invoice may move to `DISPUTED` from `ISSUED` or `ADJUSTED`.
16. Reject branches all pinned: KYC `HOLD` does not clear `suspension_reason`; campaign `REJECT` reserves nothing; line-item eligibility `REJECT` does not increment `occupancy_count` and removes every assignment; dispute `REJECT` returns the invoice to `ISSUED`, never `ADJUSTED`.
17. Reinstatement never auto-resumes (advertiser reinstate, plan top-up, campaign resume all leave `OOS_PAUSED` items alone); catalog reinstate is two-branch on stock and succeeds either way.
18. Advertiser terminate from `ACTIVE` or `SUSPENDED`; plans not already `CLOSED`/`REJECTED` → `CLOSED`, campaigns → `ARCHIVED`, `OPEN`/`FROZEN` pools → `CLOSED`.
19. Manual fund deduction can never drive `available_cents` below 0, but invoice issuance may drive it to exactly 0 with the excess capped and the pool frozen `OVERDRAWN` — asymmetry stated.
20. `adjusted_credit_limit_cents` on the KYC decision replaces `credit_limit_cents` before the 100,000-cent approval floor is tested; the floor is waived entirely for an umbrella child.

The two withheld design files were not opened, listed, grepped or referenced, and no sibling task directory was read.

## Step 2b: Generate SCAFFOLD_DIFFICULTY_DESIGN.yaml — 2026-09-01T00:32:00.000Z

Generated as three concurrent shards (rules 1-3 / 4-6 / 7-9), merged by the orchestrator in canonical §0.5 rule order. Merged file: **2,702 lines**, single top-level key `scaffold_difficulty_design`, **19 non-stub instances** across all 9 `rule_id` blocks (2/2/2/2/2/2/2/2/3). `yaml.safe_load` parses clean; rule order matches §0.5 exactly; every instance carries `grounds`, `distinguishing_aspect`, and a full `test_recipe` with all four of `setup`/`setup_api_calls`/`trigger`/`assert`; instance names unique within the file and zero collisions against `SCAFFOLD_CORNER_DESIGN.yaml`. Shard part files deleted after merge validation.

Endpoint-path note resolved during this step: SCAFFOLD.yaml declares 99 of 101 endpoint paths under `/rmn`, but the two test-driving/operational endpoints are declared WITHOUT the prefix — `POST /_clock/set_current_utc` (line 2078) and `POST /_ops/run-daily-checkpoint` (line 2086). PRD.md §4 carries both through unprefixed. All design files use the unprefixed form, consistent with scaffold and PRD. (The orchestrator's shard prompts had misstated these as `/rmn/_clock/...`; the agents correctly followed the scaffold. A correction was also sent to the Step 6 implementation agent so its Flask routes register the unprefixed paths.)

### Shard 1 — dual_variant_calc, combinatorial_formula, non_linear_state_machine

- `dual_variant_calc`: `dvc_geo_vs_user_holdout_lift_divergence` (IncrementalityStudy measurement domain) / `dvc_offsite_logged_vs_reported_billing_basis` (Campaign off-site spend / Invoice billing domain) — axis: different entity domains.
- `combinatorial_formula`: `cf_headroom_min_exponent_tier_bid_ranking` (mode **a** — nested min-max + non-linear exponent + tiered multiplier) / `cf_cpm_sum_then_round_remainder_waterfall` (mode **b** — nested rounding where order matters; scaffold pins sum-then-round) — axis: different §0.5 modes.
- `non_linear_state_machine`: `nlsm_dispute_info_request_review_cycle` (MeasurementDispute — true cycle UNDER_REVIEW ↔ INFO_REQUESTED × 2) / `nlsm_campaign_parallel_delivery_billing_dimensions` (Campaign — parallel delivery_status × billing_status dimensions plus a billing-side cycle) — axis: different entities and different non-linear shapes.

Computed literals (Decimal/ROUND_HALF_UP): `incremental_sales_lift` GEO `lift_pct 0.6667`, `incremental_sales_cents 16000480` (16000000 is the wrong unrounded-lift value), USER scaled_control 27500000 → `12500000`, `lift_pct 0.4545`, `significance_score 2.8284`. `offsite_spend_reconciliation`: reported 1275 → `offsite_variance_pct 2.00` → LOGGED (boundary); 1270 → `1.60` → REPORTED; invoice `gross 2520`, `managed_service_fee_cents 126`, `net_cash_due_cents 2646`. `relevance_score_composition`/`relevance_adjusted_bid_ranking`/`second_price_clearing`: rel `0.8100`/`0.5600`, effective bids 700 (headroom-bound from a 3000 bid)/1200, `quality_adjusted_score 505.1970`/`413.9520`, ceil-once → `clearing_price_cents 575`; negations — linear-relevance reading gives 623.7000/739.2000 and flips the winner, skipping the headroom clamp gives 2165.1300. `auction_settlement_amount` CPM: `settled_spend_cents 8` = round_half_up(7.5), remainder distribution `billable_cents [2,2,1,1,1,1]`, CLICK `0`; negations 6 (round-per-event / floor-only) and 7 (truncation). `dispute_sla_clock`: `sla_response_hours 144`, `sla_due_at 2026-09-11T00:00:00.000Z`, `sla_breached false`, `version 6`; negations 48/96.

Bugs the shard found and fixed while self-verifying: (1) both campaigns were left in DRAFT but `IncrementalityStudy DESIGNED_to_RUNNING` requires `delivery_status IN {SCHEDULED, DELIVERING}` and `Campaign DRAFT_to_PENDING_REVIEW` requires ≥1 line item in PENDING_ELIGIBILITY — added the full plan-submit/approve + slot + product + line-item + hero-assignment + submit-eligibility + submit-for-review + review-decision chain per campaign and re-pointed `expected_campaign_version` at the freshly captured post-approval versions (stale v1 would have 412'd under `concurrency_rules[study-create-stale-campaign]`); (2) `Campaign DELIVERING_to_COMPLETED` lists actor `AccountManager | NetworkAdmin | system` while the endpoint's `roles` include BillingOps — switched all three `/complete` calls to AccountManager; (3) added the missing required `expected_invoice_version` to a dispute-create payload.

Deliberate scope note from the shard: Rule 2 mode **(c)** was not used — `invoice_settlement_waterfall`'s STEP-7 tier boundaries (1,000,000 / 5,000,000 cents) cannot be crossed from an empty DB without implausible prices or ~20+ engagement calls; §0.5 permits any two distinct modes.

### Shard 2 — transitive_cascade, priority_pair_validation_conflict, boundary_precision_check

- `transitive_cascade`: `tc_catalog_out_of_stock_three_hop_pause_chain` / `tc_auction_settlement_budget_exhaustion_chain` — axis: different triggering transitions (`CatalogProduct.ELIGIBLE_to_OUT_OF_STOCK` via stock-adjustments vs `AuctionEvent.AWARDED_to_SETTLED` via settle). Both depth-3, each hop caused by the previous: product OOS → assignment `PAUSED_OOS` → LineItem `OOS_PAUSED` → Campaign `PAUSED`; settlement spend → plan `ACTIVE→EXHAUSTED` → Campaign `PAUSED` → LineItem `MANUAL_PAUSED`.
- `priority_pair_validation_conflict`: `ppvc_frozen_pool_state_beats_fiscal_insufficiency` (state p39 vs business_fiscal p74 on deductions) / `ppvc_flight_window_temporal_beats_channel_mix_constraint` (business_temporal p46 vs business_constraint p64 on line-items) — axis: different error-category pairs on different endpoints. Each setup trips both members at once; assert pins the lower-priority-number winner (`ERR_TRADE_FUND_FROZEN`, `ERR_FLIGHT_WINDOW_OUTSIDE_CAMPAIGN`) plus a negative assert on the loser.
- `boundary_precision_check`: `bpc_significance_score_exactly_at_minimum_versus_one_ulp_below` / `bpc_slot_overlap_count_exactly_at_capacity_versus_adjacent_window` — axis: different metrics through distinct endpoints (`significance_score` vs `SIGNIFICANCE_MIN`, inclusive `>=`, via measure+publish; vs `slot_occupancy_overlap` RULE A `overlap_count` vs `max_concurrent_line_items`, strict `<`, half-open adjacency, via eligibility-decision).

Computed literals: `relevance_score_composition` → `relevance_score 0.86`; `relevance_adjusted_bid_ranking` headroom min(400000,400000,500000) → `quality_adjusted_score 344000.0`, tier `TIER_2`; `second_price_clearing` no runner-up → `clearing_price_cents 250000`; `auction_settlement_amount` CPC 2 CLICKs → `settled_spend_cents 500000`; `budget_plan_available` → `available_cents 0` (→ EXHAUSTED) and `500000`; `trade_fund_available` → `100000` (< requested 500000, so the fiscal check genuinely would fail); `incremental_sales_lift` GEO 10000/10000 → `lift_pct 0.6447`, `incremental_sales_cents 1959932`, `significance_score 1.96` → flag true, and 500/305 → `1.95` → flag false; `line_item_reservation` → `reserved_cents 5000`; `slot_occupancy_overlap` → C1 overlap_count 2 vs max 2 reject, C2 starting at B.flight_end_at → overlap_count 0 approve, final `occupancy_count 3`.

### Shard 3 — cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant

- `cross_entity_state_dependency`: `cesd_plan_submit_blocked_by_sibling_plan_trade_fund_reservation` (BudgetPlan→TradeFundAccount, p74 `ERR_TRADE_FUND_INSUFFICIENT` 402) / `cesd_line_item_resume_blocked_by_paused_parent_campaign` (LineItem→Campaign, p31 `ERR_CAMPAIGN_NOT_DELIVERING` 409) — axis: different entity pairs.
- `resource_temporal_overlap`: `rto_offsite_slot_buffer_inflation_rejects_adjacent_flights` (PlacementSlot, RULE C buffer-inflated windows — touching windows collide even though they pass RULE A's aggregate-capacity count, `ERR_SLOT_BUFFER_CONFLICT` p55) / `rto_study_washout_gap_rejects_disjoint_measurement_window` (IncrementalityStudy, minimum-clear-gap geometry — fully disjoint windows collide because the gap is under `WASHOUT_DAYS: 7`, `ERR_STUDY_WASHOUT_VIOLATION` p50) — axis: different interval semantics on different resource entities.
- `compensating_invariant`: `ci_budget_plan_cents_conserved_across_schedule_then_archive` (media-commitment cents) / `ci_trade_fund_cents_conserved_across_approve_then_close` (co-op accrual cents, a separate pool) / `ci_slot_occupancy_count_conserved_across_grant_then_end` (a cardinal non-monetary inventory count) — axis: three different kinds of conserved quantity. All ride invariants the scaffold declares itself (the two `# CONSERVATION INVARIANT` blocks in `calculations.budget_plan_available` / `trade_fund_available`, plus the compensating-action notes on `Campaign.SCHEDULED_to_ARCHIVED` and `LineItem.SERVING_to_ENDED`).

Computed conservation triples (before → mid → after, drift 0 in all three): budget plan avail 5000000 → 3000000 → 5000000, reserved 0 → 2000000 → 0, identity sum 5000000 at all three points; trade fund avail 3000000 → 1750000 → 3000000, reserved 0 → 1250000 → 0, accrued pinned 3000000; slot `occupancy_count` 0 → 1 → 0. Supporting: `line_item_reservation` 1400000 (100000 × 14 days) and 1000000 (100000 × 10 days); deduction cap headroom 0.6 × 3000000 = 1800000 ≥ 1250000; washout boundary `gap_hours == 168` at `window_start_at == 2026-08-19T00:00:00Z`.

Judgement call recorded by the shard: in `cesd_line_item_resume_blocked_by_paused_parent_campaign` the assert `BudgetPlan.available_cents == 3000000` follows `calculations.budget_plan_available` (reserved counts campaign allocations only), even though the line-item activate/pause endpoint prose hints at extra movement — §1.3 calculations treated as normative.

All three shards machine-checked their output against SCAFFOLD.yaml with custom validator scripts (0 errors): `grounds:` resolution against calculations / `state_machines.<Entity>.<FROM>_to_<TO>` / `validations[priority=N]` / `concurrency_rules[id]` / entity field names; endpoint method+path existence; payload keys vs declared `input:` including all required non-`?` fields; role validity and per-endpoint role permission; every `${var}` bound by an earlier `captures:`; capture jsonpaths present in the endpoint's `output:`; `expected_*_version` never a bare literal; no `round(...)` left in asserts.

## Step 2c: Generate SCAFFOLD_CORNER_DESIGN.yaml — 2026-09-01T00:46:00.000Z

Complete. All nine §1.9 sections in spec order, **79 instances** total: entities 12, state_machines 13, calculations 17, validations 8, endpoints 6, rbac 6, errors 8, cross_cutting_complexity_layers 7, consistency_model 2. Single top-level key `scaffold_corner_design` confirmed.

**Zero `excluded_because` stubs** — every instance carries a full `test_recipe` with structured `setup_api_calls`, a `trigger`, and literal asserts. (The orchestrator directed this: because §1.8 was being generated concurrently and did not exist yet, the agent could not verify that a cited `difficulty_instance` name resolves, and the spec forbids citing an unresolvable one. Some duplicate coverage with §1.8 is accepted in exchange.) All 79 names unique within the file, zero collisions with the 19 names in §1.8, and none use the reserved `dvc_`/`cf_`/`nlsm_`/`tc_`/`ppvc_`/`bpc_`/`cesd_`/`rto_`/`ci_` shard prefixes.

Notable section content: `cross_cutting_complexity_layers` carries five `optimistic_concurrency` instances, exactly one per §1.2.1 rule not already covered by §1.8 (budget-plan-create / product-assignment-create / trade-fund-deduction / dispute-create / study-create), each calling the rule's own `write_endpoint` twice so the first call's captured parent version is genuinely stale → 412 with the rule's declared `error_id`; plus one `cascading_side_effects` and one `dual_variant_calculation` (REPORTED_BASIS counterpart to the exactly-2.00 LOGGED_BASIS case: reported 101 vs logged 100 → variance 1.00 → invoice bills 101). `consistency_model` holds two `immediate` instances asserting sibling-row readability within the same request (activation response SERVING/TIER_2/reserved 1000000/relevance 0.8300 with plan ACTIVE, campaign DELIVERING, slot occupancy 1; invoice issuance gross 284 / fee 0 / deduction 57 / net 227 with an immediate pool read showing deducted 57 / available 299943).

Scaffold references reconciled by the agent:
- **Cascade design changed** after re-reading the source: §1.5 `POST /rmn/auction-events/{id}/settle` narrates "moves the same amount from `reserved_cents` to `consumed_cents`", which makes `available_cents` invariant under settlement and contradicts the §1.3 `budget_plan_available` formula (`reserved` = Σ allocated of reserving campaigns). Rather than build the exhaustion cascade on that ambiguity, the `cascading_side_effects` instance triggers exhaustion via `POST /rmn/campaigns/{id}/offsite-reconciliation`, where `offsite_reported_spend_cents` is purely additive to `consumed_cents` under both readings. Plan committed 1000100 vs 1000000 reserved → posting exactly 100 drives `available_cents` to the `<= 0` boundary of 0.
- **Slot occupancy corrected**: §1.1 line 166 and §1.2 CASCADE L3 state that `MANUAL_PAUSED` remains an occupying status (§1.5 settle's "releasing slot occupancy" is the outlier), so the cascade asserts `occupancy_count == 1`, not 0. `reserved_cents` likewise stays 1000000 because `PAUSED` is a reserving status.
- Earlier reconciliations standing: Campaign `billing_status` has no `NOT_BILLABLE`/`RECONCILING` member (corrected to `UNBILLED`/`PENDING_INVOICE`); `ERR_MAX_INFO_REQUESTS_EXCEEDED` (§1.2 escalation vs validation 65's 409) and the `POST /rmn/invoices/{id}/adjust` recompute were left unused as under-specified; `roas`/`iroas` precision is unspecified so never asserted.

**§1.5 gaps: none.** Every precondition across all 79 instances was reachable by composing endpoints already declared in §1.5 (ladder rung 1), including the ELIGIBLE→SERVING and off-site reconciliation paths. Zero new business endpoints and zero `/_<name>` test-driving endpoints added; SCAFFOLD.yaml untouched (mtime unchanged).

Verification: `yaml.safe_load` clean, per-section counts as above. A custom closure check over all 79 instances reported 0 problems — every `${var}` in every `call`/`payload`/`as_user_id`/`assert` resolves to an earlier `captures:` in the same instance, every call is a well-formed `{call, payload, as, …}` mapping, and every `expected_*_version` contains a `${...}` placeholder rather than a literal. Full scaffold lint over both design files:

```
python3 skills/prd-bench-scaffold-generator/scaffold_lint.py tasks/task_2191_retail_media_network_campaign_operations
  §1.5 endpoints declared:    101
  §1.1 entities declared:     15
  §1.8 instances scanned:     19
  §1.9 instances scanned:     79
  Calls scanned (§1.8+§1.9):  1934

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Step 6: Generate Implementation — 2026-09-01T00:52:00.000Z

Implementation complete and verified. **5,856 lines** across 17 files in `workspace/implementation/`.

Launched early (immediately after PRD.md validated) rather than concurrently with Step 5, because its three inputs — INSTRUCTION.md, SCAFFOLD.yaml, PRD.md — were all already valid and `test_suite/` did not yet exist. The required physical isolation therefore held a fortiori: the impl-gen agent could not read tests that had not been generated.

| file | lines | contents |
|---|---|---|
| `start.sh` | 18 | reads `$PORT` (default 10000), binds 0.0.0.0, guarded pip install, `exec python3 app.py` foreground |
| `requirements.txt` | 1 | `flask>=3.0` |
| `app.py` | 80 | `create_app()` → `db.reset()` (no seeding), registers 10 blueprints, error handlers for `ApiError`/404/405/400→422/500 |
| `core.py` | 523 | 79-entry `ERROR_STATUS` map, `ApiError`/`fail`, 8 roles, `CLOCK_DEFAULT = 2026-08-01T00:00:00Z`, in-memory `Store` (15 dicts, `reset()`), time helpers, `rhu/rhu_dec/ceil_int/trunc_int`, `new_row/touch/sort_rows`, envelope `ok/ok_list/err_body`, field spec `F` + `validate_body`, pagination, identity/role reads, `EXISTENCE_ORDER` |
| `guard.py` | 186 | ordered chain for checks 1–25 (identity, role, AdvertiserUser ownership, body, pagination, the 13 existence probes in scaffold order, the 6 OCC probes, advertiser-terminated) |
| `derive.py` | 1070 | all 18 calculations + 15 serialisers (budget/fund aggregates, exposure & credit limit, pacing, second-price clearing, CPM waterfall, attribution, lift/significance, SLA & evidence cap, dispute award, offsite variance/basis/billable) |
| `helpers.py` | 255 | list/filter helper, billing-status machine (`fire_billing`), pause/end/rollup cascades, advertiser suspension, plan exhaustion/revival, credit-limit enforcement, pool unfreeze, invoice↔dispute restore, shared format validators |
| `routes_advertiser.py` | 341 | 12 advertiser endpoints incl. credit-summary |
| `routes_budget.py` | 233 | 9 budget-plan endpoints |
| `routes_fund.py` | 150 | 8 trade-fund endpoints |
| `routes_campaign.py` | 478 | 12 campaign endpoints incl. performance-summary, offsite reconciliation |
| `routes_inventory.py` | 471 | placement slots + line items (15 endpoints) |
| `routes_catalog.py` | 407 | catalog products + product assignments (13 endpoints) |
| `routes_auction.py` | 414 | auction events, bids, engagement events (11 endpoints) |
| `routes_measurement.py` | 340 | attributed sales + incrementality studies (11 endpoints) |
| `routes_billing.py` | 679 | 7 invoice + 10 dispute endpoints, the 10-step invoice waterfall, the depth-three uphold unwind |
| `routes_ops.py` | 210 | `POST /_clock/set_current_utc` and `POST /_ops/run-daily-checkpoint`, **both unprefixed** per the orchestrator's mid-flight correction; 7 checkpoint sweeps |

The 13 state-machine transition tables live next to their entity (`SLOT_TRANSITIONS`/`LINE_ITEM_TRANSITIONS` in inventory, `INVOICE_TRANSITIONS`/`DISPUTE_TRANSITIONS` in billing, `BILLING_TRANSITIONS` in helpers, etc.), all driven through a single `H.require_transition` gate so the 409 error id and message shape stay uniform.

Verification performed:
- **Route surface**: programmatic diff of the 101 scaffold `method`+`path` pairs against Flask's `url_map` — 101 registered, **0 missing, 0 extra**.
- **Error ids**: all 79 declared ids are raised somewhere; no undeclared id is raised.
- **Fresh boot**: `bash start.sh` with `PORT=18742` → `GET /rmn/advertisers` returns `total_count 0`, `data []`; `created_at` on a freshly created row is `2026-08-01T00:00:00.000Z`, confirming the clock default and the empty store.
- **curl round-trip**: `POST /rmn/advertisers` → 201 full envelope (`meta.api_request_id` `req_…`, `response_type: "object"`); `GET /rmn/advertisers/{id}` → 200 identical row; deliberate `brand_code: "lower!"` → 422 `ERR_VALIDATION`.
- **Prefix check**: `POST /_clock/set_current_utc` → 200; `POST /rmn/_clock/set_current_utc` → 404.
- **Two end-to-end scripts green** (both exited 0, zero tracebacks in the server log). Pass 1: onboarding → pool accrual → plan approval → campaign/line-item/assignment → activation → auction rank/award/settle (clearing 50, CPC) → attributed sale (weight 1.0, credit 1998) → study measure → checkpoint completion → invoice issue (onsite 50, fee 3, trade fund 11, net 42, hand-checked) → dispute SLA 48h→96h → uphold credit 13, invoice ADJUSTED net 32 → exact settle → stock/delist cascades → 7 deliberate failures (404/400/422/403/401/409/404). Pass 2: PATCHes, credit-summary, pool freeze/unfreeze/reconcile, plan return-for-revision/top-up, CPM auction, NO_FILL `ALL_BELOW_FLOOR`, offsite reconciliation, restrict/reinstate, 204 DELETE, study publish/invalidate/re-measure, escalation, adjust round 1, withdraw, write-off → advertiser SUSPENDED/CREDIT_BREACH, terminate + post-termination 409, archive, filtered list reads.
- Server processes were killed by PID rather than `pkill`, to avoid disturbing concurrent agents on this host.

PRD ambiguities resolved by the implementer (recorded here as Step 8/9 input):
1. **`POST /rmn/invoices/{id}/adjust` reachability**: PRD line 406 makes `UPHOLD` itself move the invoice `DISPUTED → ADJUSTED`, while line 386 declares `adjust` only from `DISPUTED`. Both implemented literally, so operator-driven adjust is reachable only when a later dispute has pushed an `ADJUSTED` invoice back to `DISPUTED` (line 384 permits filing from `ADJUSTED`) while an earlier dispute is already `UPHELD`. Verified live; no code change needed.
2. **Invoice restore set**: line 410 calls `UPHELD` terminal, but line 384 lists `UPHELD` among states that keep an invoice `DISPUTED`. The specific rule (384) wins — `OPEN_DISPUTE_STATES` includes `UPHELD`.
3. **Off-site spend in the waterfall** uses `D.offsite_billable(camp)` summed over the plan's campaigns (basis-selected by the reconciliation), while step one's on-site spend is filtered to auctions whose `requested_at` falls in the billing month — exactly as the two sentences are worded.
4. **Off-site auctions can never settle** (line 344 restricts IMPRESSION/CLICK to on-site slots; line 346 requires an IMPRESSION to settle from `AWARDED`), so an off-site line item that won one can never be individually `end`ed (line 306). Both refusals are the literal reading; campaign `complete` is the available route.
5. **Checkpoint clock**: `as_of_date` (bare `YYYY-MM-DD` or a full instant) is applied to the logical clock for the sweep's duration and restored in a `finally`; omitting it sweeps at the current clock.
6. **Pool `RECONCILING`** is entered by the sweep only from `OPEN`; `CLOSED` follows once `reserved_cents` is 0 and 24h have passed since `last_reconciled_at`.
7. **`ENDED` line items** zero `reserved_cents` and bump the slot row's version, since occupancy is surrendered.

## Step 5 Phase A: test_helpers/ + conftest + queue A — 2026-09-01T01:35:00.000Z

Step 5 was executed in two phases because the skill's §2.1 mandates queue A before queue B ("Difficulty setups are more complex and produce composite fixtures in `test_helpers/fixtures.py` that corner translations reuse"), while 98 total design instances made a single agent a stall risk. Phase A = Stage 1 + conftest + all 19 queue-A instances (one agent). Phase B = the 79 queue-B corner instances, sharded three ways, reusing Phase A's fixtures.

### test_helpers/ (Stage 1) — 4,911 lines, 9 files

| file | lines | contents |
|---|---|---|
| `__init__.py` | 224 | barrel re-export (framework names + all local layers); `from .api_errors import *` gives every `ERR_*` unqualified; import blocks marked `# noqa: F401` |
| `types.py` | 588 | typed shapes for all 15 entities, honouring `common_fields: false` (AuctionBid, EngagementEvent carry only `id` + `created_at`) |
| `api_client.py` | 1439 | `RmnApiClient(GenericApiClient)`, one method per endpoint, `prefix = "/rmn"` via `_url()`, with `set_clock` / `run_daily_checkpoint` on the bare unprefixed paths |
| `api_errors.py` | 271 | every error id as a constant + `ERROR_HTTP_STATUS`, `ERROR_PRECEDENCE`, `error_http_status`, `error_priority`, `register_error_http_statuses` |
| `assertions.py` | 395 | 28 helpers: `round_half_up(_int)`, `parse_utc`/`iso_utc`, `hours_between`, `days_between`, `whole_day_periods`, `shift_hours/days`, `floor_to_utc_day`, the two conservation-identity asserts, `assert_plan_reservation_matches_campaigns`, `assert_slot_occupancy_matches_line_items`, `assert_occupancy_count`, `assert_no_drift`, `assert_campaign_dimensions`, `assert_line_item_paused`, `assert_refusal_beats`, `assert_error_status_is_canonical`, `assert_ranked_in_order`, `assert_decimal_places` |
| `constants.py` | 193 | ~70 PRD-quoted figures (relevance weights, tier ratios/multipliers, CPM divisor, match weights, `SIGNIFICANCE_MIN`, `WASHOUT_DAYS`, pacing catch-up pair, occupying/reserving status tuples, deduction tiers, net-terms/grace/write-off days, SLA base hours + `SLA_MANAGED_REDUCTION_HOURS`/`INFO_REQUEST_EXTENSION_HOURS`/`SLA_FLOOR_HOURS`/`MAX_INFO_REQUESTS`) |
| `test_users.py` | 122 | 8 role constants + `SECOND_*` counterparts for segregation-of-duties pairs, `make_advertiser_user_headers(advertiser_id)` for the only entity-backed role |
| `factories.py` | 462 | 29 minimal-valid payload builders with `**overrides` and a `_unique()` counter |
| `fixtures.py` | 1217 | 65 composite builders/mutators over a mutable `world` dict, all reading through `get_success_data()` |

**Endpoint / error coverage verified programmatically by exact set equality:** api_client **101/101** endpoints (`(method, normalised path)` set vs the PRD §4 table — 0 missing, 0 extra, 101 public methods); api_errors **79/79** error ids (`ERR_*` constants vs the PRD's ids — 0 missing, 0 extra).

**Composite fixtures pre-built as the union of BOTH queues' chains.** The agent surveyed all 79 queue-B chains (1,430 setup calls, 72 distinct endpoints, chains up to 39 calls deep) and tallied every terminal state; all were reachable from a builder. Ladder rungs `build_world` → `build_active_advertiser` / `build_active_managed_advertiser` / `build_child_advertiser` / `build_second_active_advertiser`, `build_trade_fund_pool` / `build_frozen_trade_fund_pool`, `build_draft_budget_plan` / `build_active_budget_plan`, `build_placement_slot` / `build_offsite_placement_slot`, `build_catalog_product`, `build_draft_campaign` / `build_pending_review_campaign` / `build_scheduled_campaign` / `build_delivering_campaign` / `build_completed_campaign`, `build_line_item` / `build_pending_eligibility_line_item` / `build_eligible_line_item` / `build_second_line_item_on_same_slot` / `build_second_campaign_on_same_plan`; auction chain `build_open_auction` → `build_ranked_auction` (stashes `world["bids"]`) → `build_awarded_auction` → `build_settled_auction`, `build_engagement_event(s)`, `build_attributed_sale`; billing/dispute `build_draft_invoice` / `build_issued_invoice` / `build_settled_invoice` / `build_filed_dispute` / `build_dispute_under_review` / `build_dispute_awaiting_info` / `request_dispute_info` / `provide_dispute_info`; measurement `build_designed_study` → `build_running_study` → `build_measured_study` → `build_published_study`; roll-ups `build_funded_advertiser`, `build_inventory`, `build_campaign_ready_world`, `build_delivering_world`, `build_billable_world`; clock/ops `set_clock`, `advance_clock_hours/days`, `run_daily_checkpoint`, plus 11 `reread_*` refreshers. Five fixtures added specifically to close the last queue-B gaps the survey exposed: `adjust_product_stock`, `suspend_advertiser`, `pause_campaign`, `pause_line_item`, `post_pool_deduction`.

### test_suite/ — conftest.py (136 lines) + 9 queue-A files, 42 tests

`test_dual_variant_calc.py` 3 · `test_combinatorial_formula.py` 6 · `test_non_linear_state_machine.py` 4 · `test_transitive_cascade.py` 7 · `test_priority_pair_validation_conflict.py` 4 · `test_boundary_precision_check.py` 4 · `test_cross_entity_state_dependency.py` 4 · `test_resource_temporal_overlap.py` 4 · `test_compensating_invariant.py` 6.

**Queue-A coverage: 17 of 19 instances, 42 tests, ≥2 per instance.** Every test carries exactly one `Design: Difficulty/<rule_id>/<instance.name>` line (42 tests / 42 tags / 17 distinct names, all verified to resolve against SCAFFOLD_DIFFICULTY_DESIGN.yaml; zero `Design: Corner/...` tags). Per instance: dvc_geo 3 · cf_headroom 3 · cf_cpm 3 · nlsm_dispute 4 · tc_catalog 4 · tc_auction 3 · ppvc_frozen_pool 2 · ppvc_flight_window 2 · bpc_significance 2 · bpc_slot_overlap 2 · cesd_plan_submit 2 · cesd_line_item_resume 2 · rto_offsite_buffer 2 · rto_washout_gap 2 · ci_budget_plan 2 · ci_trade_fund 2 · ci_slot_occupancy 2.

### Two queue-A instances SKIPPED (PRD-first filter)

1. **`dvc_offsite_logged_vs_reported_billing_basis`** — asserted outcome is *contradicted*, not merely unstated. PRD 344 restricts `IMPRESSION`/`CLICK` to on-site auctions and `OFFSITE_VIEW` to off-site ones, while PRD 346 makes settlement from `AWARDED` require ≥1 `IMPRESSION` event — so no off-site auction can ever settle. The logged off-site figure is therefore structurally 0, variance always exactly 100.00, basis always `LOGGED_BASIS`; the divergence the instance exists to test is unreachable, and the 79-item rejection contract names no error for the event-type/slot-channel pairing.
2. **`nlsm_campaign_parallel_delivery_billing_dimensions`** — not uniquely derivable. Its chain requires `POST /offsite-reconciliation` to drive `billing_status` `ACCRUING → PENDING_INVOICE`; PRD attributes that transition only to campaign completion (§3.3 line 282), and §3.8 line 380 plus §4 line 456 are both silent on reconciliation changing the billing dimension.

Gaps left as gaps — no weakening, no skip/xfail markers, no placeholders.

### Design-recipe defects found and worked around

- `nlsm_dispute…` setup settles an auction carrying only a `CLICK`, which PRD 346 forbids → setup records 1 `IMPRESSION` + 1 `CLICK` (settled figure unchanged at 1250).
- `tc_auction_settlement…` triggers settle as `BillingOps`; PRD §3.6 line 328 allows only NetworkAdmin/AuctionService while the §4 table (line 487) also lists BillingOps → settles as `AUCTION_SERVICE`, authorised under both readings.
- `tc_auction_settlement…`'s own flight `[2026-08-01, 2026-09-01)` makes the PRD headroom reading (line 336: campaign cap = daily *pacing allowance*, not `daily_cap_cents`) produce `NO_FILL`, contradicting its own asserts → flight redesigned to `[2026-08-01, 2026-08-06)`, which reproduces the design's own `winner_score 344000.0` exactly.
- `rto_study_washout_gap…` started a study against a `DRAFT` campaign → taken to `SCHEDULED`.
- `nlsm_dispute…` uses `as_user_id: au-5` for AdvertiserUser → handled by `advertiser_headers(world)`.

### Helper bugs fixed during Phase A

- `build_filed_dispute` filed as `MEASUREMENT_ANALYST`, a role PRD 394 does not authorise for filing → `ACCOUNT_MANAGER` (would have 403'd every dispute test).
- `build_settled_invoice` read `net_payable_cents`, a field with **zero** PRD occurrences → `net_cash_due_cents`.
- Missing `SLA_MANAGED_REDUCTION_HOURS` added to `constants.py` and the barrel.

Validation: `pyflakes` clean across all test files and all `test_helpers` modules; `py_compile` OK; `import test_helpers` succeeds; `pytest --collect-only` collects **42 tests in 0.1s** with no import or name errors. Tests not executed (no server in that agent's environment; Step 7 owns execution). The implementation directory was never read.

## Step 5 Phase B: Queue-B corner tests (3 concurrent shards) — 2026-09-01T00:00:00.000Z

Queue B (§1.9, 79 instances) was sharded across 3 concurrent subagents after Phase A
(queue A + test_helpers/) completed, so all composite fixtures already existed.
Per-shard filename prefixes; `Write` forbidden on shared files; shared-file bugs
fixable only by re-read-then-Edit.

### Shard B1 — entities (12) + state_machines (13) = 25 instances
25/25 instances, 25 tests, ZERO skips.
Files: test_corner_entities.py (579), test_corner_state_machines.py (711).
Shared-file bug fixed: `test_helpers/factories.py` `attributed_sale_payload` used
`"match_type": "CLICK"`, which is not a declared PRD enum value → `"CLICK_THROUGH"`.
Without this every `build_attributed_sale` would 422.
7 design-recipe defects worked around; notably a non-derivable campaign roll-up
sub-assertion was dropped from `slot_maintenance_...` because §3.4's roll-up sentence
is scoped to the line-item pause action and §2.10 states no generic rule.
Verification: pyflakes rc=0; 25 tests collected in 0.12s.

### Shard B2 — calculations (17) + validations (8) = 25 instances
24/25 instances, 24 tests, 1 skip.
Files: test_corner_calculations_auction.py (374, 4 tests),
test_corner_calculations_attribution.py (283, 4),
test_corner_calculations_billing.py (450, 6),
test_corner_calculations_ledgers.py (192, 2),
test_corner_validations.py (566, 8).
Shared-file bug fixed: `managed_advertiser_payload` omitted the mandatory
`account_manager_user_id` → added `"am_001"`. Without this every
`build_active_managed_advertiser()` would fail, including a Phase A test.
SKIP: `calculations :: offsite_variance_of_exactly_two_percent_bills_on_the_logged_basis`
— unreachable terminal state (see OFF-SITE SETTLEMENT CONTRADICTION below).
All 75 `PRD x.y: "…"` docstring citations machine-checked as verbatim substrings of
workspace/PRD.md. Verification: pyflakes clean; 24 tests collected in 0.09s.

### Shard B3 — endpoints (6) + errors (8) + rbac (6) + cross_cutting (7) + consistency (2) = 29 instances
28/29 instances, 28 tests, 1 skip.
Files: test_corner_endpoints.py (6 tests), test_corner_errors.py (8),
test_corner_rbac.py (6), test_corner_concurrency.py (6), test_corner_consistency.py (2),
plus shard-private test_helpers/fixtures_corner_rbac.py (288 lines, no shared file touched).
All five `ERR_STALE_*_VERSION` OCC instances are deterministic two-sequential-call tests
(no `run_race`), each asserting the rule's exact error id. Four rest on an explicitly
stated parent-version increment (§3.4 L312 assignment→line item, §3.4 L266 + §2.2 L85
deduction→pool, §3.9 L394 filing→invoice, §3.7 L360 design→campaign). The budget-plan
one was restructured: nothing in the PRD says plan creation mutates the advertiser row,
so the recipe's "two plans in a row" mechanism is not derivable; staleness is instead
derived from §3.1 L242's KYC increment.
SKIP: `cross_cutting_complexity_layers ::
a_one_percent_offsite_variance_bills_the_higher_reported_figure_on_the_reported_basis`
— coverage exists (§3.8 L380 verbatim) but the instance's own outcome is not derivable
(see below). The adjacent 100.00-variance boundary IS covered by the exhaustion test.
3 recipe defects worked around: `relevance_score == 0.8300` dropped where no auction has
run (§3.6 computes relevance from query + shopper segment); an illegal explicit
line-item activate immediately after campaign activation (§3.5 L300 auto-promotes)
restructured by holding the line item in PENDING_ELIGIBILITY; and
`plan_status == APPROVED` corrected to `ACTIVE` because §3.2 promotes in the same
request under the recipe's own 2026-08-01 window (§3.1 counts APPROVED/ACTIVE/EXHAUSTED
alike, so the exposure figures under test are unchanged).
Verification: pyflakes clean over all six files; 28 tests collected in 0.17s.

### OFF-SITE SETTLEMENT CONTRADICTION (independently found by all 3 shards + Phase A)
PRD §3.6 restricts `IMPRESSION`/`CLICK` events to on-site auctions and `OFFSITE_VIEW`
to off-site, while `AWARDED → SETTLED` requires >=1 `IMPRESSION`. An off-site auction
can therefore never settle; logged off-site spend is structurally 0 and
`offsite_variance_pct` can only ever be 0.00 or 100.00. This is a genuine structural
property of the PRD, not a translation error, and it accounts for the 2 queue-B skips
plus the 2 queue-A skips logged in Phase A. Not weakened, not xfailed — skipped.

### Phase B totals
77 of 79 queue-B instances covered by 77 tests (2 skips, both the off-site contradiction).
Combined suite: 119 tests collected in 0.10s.
  queue A: 42 tests over 17 of 19 §1.8 instances (multi-variant recipes → >1 test/instance)
  queue B: 77 tests over 77 of 79 §1.9 instances (1 test/instance, all tags unique)
Global audit: 119 `Design:` tags, exactly one per test, zero dual-tagged, zero tags
pointing at non-existent instances, zero `skip`/`xfail`/`skipif` markers anywhere.

## Step 7: Run tests and iterate — 2026-09-01T03:27:40.000Z

All 8 rounds pass. Final state confirmed.

## Summary

**Iterations run:** 2 full 8-round parallel sweeps (sweep 1 diagnostic: 111/119 in all 8 rounds, identical failures, zero flakiness; sweep 2 confirming: 119/119 in all 8 rounds).

**Tests deleted:** none. Every one of the 8 failures was a test-artifact mistranslation of a PRD sentence that *is* present, not PRD silence about a rule — so no test lost coverage and no deletion was warranted.

**Fixes applied to `test_helpers/`:** none. The composite fixture ladder, factories, and RBAC baselines were all PRD-consistent.

**Fixes applied to `implementation/`:** none. The implementation was correct on both failure classes; in particular the CPM remainder waterfall in `/home/ubuntu/github/CodingPRD/tasks/task_2191_retail_media_network_campaign_operations/workspace/implementation/routes_auction.py` (`_distribute_cpm`) already produced the PRD-mandated `[2,2,1,1,1,1]`, and `core.py::fmt_dt` already rendered the three-fractional-digit form PRD §2.4 requires.

**Fixes applied to `test_suite/` (8 sites, 5 files):**

*Class B — creation status (PRD §4 verbatim: "Creation endpoints answer with HTTP 201, the single removal endpoint answers with HTTP 204 and an empty data object, and every other endpoint answers with HTTP 200.").* Three setup calls in `test_suite/test_corner_errors.py` wrapped a creation in bare `validate_success(...)`, which defaults to `expected_status=200`, so they died in setup at `Expected 200, got 201` before ever reaching the rule under test. Added the explicit `201` to `create_advertiser` (~L107), `create_catalog_product` (~L143), and `create_incrementality_study` (~L272). This makes the assertion stricter, not weaker — the status is now checked against the PRD figure instead of a wrong default.

*Class A — timestamp rendering (STEP 1c partial coverage: keep the covered assertion, drop the uncovered one).* PRD pins the exactly-three-fractional-digit rendering to only three fields — line 50 for `api_request_timestamp` and line 85 for `created_at`/`updated_at`. It says nothing about how `occurred_at`, `window_start_at`, `window_end_at`, `issued_at`, `due_at`, `filed_at`, or `exhausted_at` are serialized. Five assertions compared those fields as exact strings against no-fraction literals, which asserts the *rendering* (uncovered) on top of the *instant* (covered). Converted each to an instant comparison via the suite's own `parse_utc` (docstring: "tolerating a trailing Z and fractions"), the convention the same files already used for `sla_due_at` and `first_response_at`:
- `test_combinatorial_formula.py` — `occurred_at` list vs `IMPRESSION_TIMES` (also added `parse_utc` to its `test_helpers` import block)
- `test_corner_calculations_billing.py` — `issued_at`, `due_at`, `filed_at`
- `test_resource_temporal_overlap.py` — `window_end_at`, `window_start_at`

I also normalized the one converse case, `test_corner_concurrency.py` L418 (`exhausted_at == "2026-08-01T00:00:00.000Z"`), to the same `parse_utc` form. It was passing, but it asserted the opposite rendering of the very same uncovered property — leaving both spellings in the suite would have meant no single implementation could satisfy both, which is what made this class non-uniquely-derivable in the first place. A follow-up grep confirms zero remaining raw-string timestamp equalities anywhere in `test_suite/` or `test_helpers/`.

**Final counts — sweep 2, all rounds `passed == total`:**

| round | passed/total | failed | errors | skipped |
|---|---|---|---|---|
| 1 | 119/119 | 0 | 0 | 0 |
| 2 | 119/119 | 0 | 0 | 0 |
| 3 | 119/119 | 0 | 0 | 0 |
| 4 | 119/119 | 0 | 0 | 0 |
| 5 | 119/119 | 0 | 0 | 0 |
| 6 | 119/119 | 0 | 0 | 0 |
| 7 | 119/119 | 0 | 0 | 0 |
| 8 | 119/119 | 0 | 0 | 0 |

Verified from the eight result files at `workspace/implementation/results.{1..8}.json` in one and the same sweep, checking the per-test `status` field and not just the totals: zero non-passing tests, and no test was skipped or errored into a false pass. Storage remained in-memory only throughout; no implementation file was touched.

### Orchestrator independent re-verification
Re-read all 8 `results.{1..8}.json` directly: every round reports `passed=119 total=119 skipped=0`,
and iterating the per-test `status` field yields 0 non-`passed` entries in every round.
Step 8 skip condition does NOT apply (8 `test_suite/` fixes, 2 sweeps) → Step 8 runs.

## Step 8: Finalize PRD — align documentation to implementation — 2026-09-01T03:30:00.000Z

Done. `PRD_FINALIZED.md` is a one-sentence-group patch of `PRD.md`.

## Line counts
- `PRD.md`: 605 lines; `PRD_FINALIZED.md`: 605 lines — **0.0% line delta** (one in-paragraph insertion at line 85, +3 sentences).

## Changes
- **§2.4 (Resource Identity, Timestamps and Version Counters)** — *insert* — after the `updated_at`/`version` roster, added that **every other** timestamp-valued field of a resource is rendered in the same ISO 8601 UTC / exactly-three-fractional-digit notation (client-supplied or server-stamped alike), is `null` when the row holds no instant, and that sub-millisecond input is truncated to whole milliseconds before storage/comparison/rendering — `implementation/core.py:215` (`fmt_dt`, unconditional `%03d` milliseconds), `implementation/core.py:212` (`parse_dt` ms truncation), applied at every `fmt_dt(...)` callsite in `implementation/derive.py:727-1034`.

## Pre-edit search log
**(a) Subject:** serialization rendering of all timestamp-valued fields other than `api_request_timestamp` / `created_at` / `updated_at` (the one genuine PRD-silence signal, Class A).

**(b) Impl paths enumerated:**
- `core.py::fmt_dt` (:215) — sole formatter; always emits `.%03dZ`, returns `None` for `None`. `core.py::_wall_ts` (:318) — the same shape for `api_request_timestamp` only.
- `core.py::parse_dt` (:187-212) — sole parser; truncates to ms (`microsecond // 1000 * 1000`). Grep for `fromisoformat|strptime|microsecond` returns only these two functions plus `floor_utc_day` — no second parse or format path, and truncation (never rounding) on both sides.
- `derive.py` serializers, all 15 kinds: `_common` (:727) `created_at`/`updated_at`; `ser_budget_plan` `window_start_at`, `window_end_at`, `exhausted_at`; `ser_trade_fund_account` `last_reconciled_at`; `ser_campaign` `flight_start_at`/`flight_end_at`; `ser_line_item` `flight_*`, `last_pause_at`; `ser_catalog_product` `last_stock_change_at`; `ser_product_assignment` `removed_at`; `ser_auction_event` `requested_at`; `ser_engagement_event` / `ser_attributed_sale` `occurred_at`; `ser_study` `window_*`; `ser_invoice` `issued_at`/`due_at`/`settled_at`; `ser_dispute` `filed_at`/`sla_due_at`/`first_response_at`. Grep of `"*_at":` in `derive.py` confirms **zero** serializer keys bypass `fmt_dt`.
- Writer side (to confirm nothing is stored as a raw string and echoed): `routes_auction.py:61/77` (`requested_at`), `:347/395` (`occurred_at`), `routes_budget.py:63-64`, `routes_campaign.py:124-125`, `routes_inventory.py:254-255`, `routes_measurement.py:57/83`, plus the null-initialised stamps in `routes_billing.py:234-236/468-471`, `routes_catalog.py:167/359`, `routes_fund.py:49`. All datetime inputs pass through `F(..., "datetime")` -> `validate_body` -> `parse_dt`, so every stored instant is a ms-resolution `datetime`.
- Off-resource emitters checked for over-claim risk: `routes_ops.py:27` (`current_utc`) and `:199` (`as_of`) also use `fmt_dt`; `routes_advertiser.py:312` credit-summary and `routes_campaign.py:455` performance-summary emit no timestamps.

**(c) Wording adjustment:** scoped the claim to "timestamp-valued field **of a resource**" rather than "every timestamp in every response", so it neither over-claims nor contradicts the two operational-fixture payloads (`current_utc`, `as_of`) that PRD never specifies — those happen to use the same rendering, so both readings stay consistent. Also phrased the null case explicitly ("rendered as `null` when the row holds no instant") to match `fmt_dt(None) -> None` for the many nullable stamps.

**No edit made for Class B** (the three bare `validate_success` calls): PRD §4 line 414 already states verbatim that creation endpoints answer 201, and `implementation/` pins nothing beyond that — it was a pure test-fixture default-argument bug, so manufacturing an edit would have added noise. Step 7 also made zero implementation and zero `test_helpers/` fixes, and its two other findings (the `_distribute_cpm` remainder waterfall in `routes_auction.py:259`, and `fmt_dt`) were explicitly confirmed already-correct against existing PRD prose, so neither warranted a patch.

### Orchestrator independent re-verification
`diff workspace/PRD.md workspace/PRD_FINALIZED.md` yields exactly one hunk (`85c85`) — a single
in-paragraph rewrite of §2.4 line 85, no other line touched, both files 605 lines. Confirmed minimal.
