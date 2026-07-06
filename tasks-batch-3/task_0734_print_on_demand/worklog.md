# Worklog — task_0734_print_on_demand

## Step 1: Create task directory — 2026-07-04T11:05:00.000Z

Created `tasks/task_0734_print_on_demand/` and `workspace/` subdirectory. Task folder pre-assigned (no ID reassignment). Scenario: Print-on-Demand Creator Storefront (Printful/Printify style). Difficulty: Expert.

## Step 2: Generate scaffold — 2026-07-04T13:42:00.000Z

Generated Expert scaffold for task_0734_print_on_demand (Print-on-Demand Creator Storefront). SCAFFOLD.yaml declares 12 entities, 56 endpoints (including 2 test-driving `/_clock/set_current_utc` and `/_ops/decay-strikes`), 20 validations, 21 error codes, 4 roles (Anonymous, Creator, PlatformAdmin, FulfillmentPartner — peer-roles model), 5 state machines (Design, Order with parallel payment/fulfillment dimensions, FulfillmentJob with SHIPPED→FAILED→REPRINT_REQUESTED→QUEUED cycle, PayoutCycle, Storefront), 5 calculations (listing_price tiered, partner_routing waterfall, creator_profit dual-variant, creator_reprint_risk_score dual-variant, payout_cycle aggregation), and 1 OCC concurrency rule on Storefront.link-channel. SCAFFOLD_DIFFICULTY_DESIGN.yaml holds all 9 Rule 0.5 rule_ids with 2 instances each (18 total). SCAFFOLD_CORNER_DESIGN.yaml holds 19 active corner instances + 2 excluded_because stubs across state_machines / entities / validations / errors / rbac / cross_cutting_complexity_layers / endpoints sections. `scaffold_lint.py` reports "VERDICT: clean lint" (485 calls scanned, all endpoint/role/payload/captures/OCC/FK-reverse-reachability checks pass).

Files written:
- /home/ubuntu/github/CodingPRD/tasks/task_0734_print_on_demand/SCAFFOLD.yaml
- /home/ubuntu/github/CodingPRD/tasks/task_0734_print_on_demand/SCAFFOLD_DIFFICULTY_DESIGN.yaml
- /home/ubuntu/github/CodingPRD/tasks/task_0734_print_on_demand/SCAFFOLD_CORNER_DESIGN.yaml

## Step 3: Copy INSTRUCTION.md — 2026-07-04T13:45:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0734_print_on_demand/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-04T13:51:00.000Z

PRD.md written (283 lines). §2 has 10 subsections (Access Control, Response Structure, Pagination, Common Resource Properties, OCC for Storefront Link, Precision & Rounding, Cascading Side Effects, Nested Path Resolution, Validation Priority, Logical Clock & Test-Driving). §3 has 9 subsections (Creator Onboarding & KYC, Storefront Creation & Markup, External Channel Integration, Product Catalog & Variants, Design Upload/Mockup/Moderation, Listing Composition & Pricing, Order Lifecycle & Routing, Fulfillment & Reprint Cycle, Payouts & Wallet). §4 endpoint table has 4 columns; §5 error table has 2 columns.

Coverage-audit findings:
- Contract 1 (Field-Name Coverage): PASS — 71 required identifiers (entity fields + request-body inputs + query params + expected_storefront_version + to_iso8601 + outcome), all present in backticks; initially found 1 missing (`name` on FulfillmentPartner) and added it via a partner-registration sentence in §3.7.
- Contract 2 (Rule Coverage): PASS — validation priority ordering enumerated in §2.9; OCC storefront-link rule expresses write endpoint, `expected_storefront_version`, mismatch rejection, `ERR_STALE_STOREFRONT_VERSION`/412 in §2.5 and §3.3; all 3 cascade patterns covered (design-recall depth-3 in §3.5, markup-update depth-2 in §3.2, partner-backlog in §3.7/3.8); dual-variant creator_profit (provisional vs final) and creator_reprint_risk_score (incremental vs full_recompute) both expressed with divergence conditions; all 21 error IDs mentioned; all enum values including `RETIRED` covered (added briefly to §3.7).
- Contract 3 (§3 Path Purity): PASS — 483 backticked tokens in §3, zero starting with `/`, zero bare HTTP methods, zero method+path combos. Endpoints referenced via state-transition framing, role+verb, or capability description.

## Step 5: Generate unit tests — 2026-07-04T14:12:00.000Z

Generated test_helpers/ (9 files: types, api_client, api_errors, assertions, factories, constants, fixtures, test_users, __init__) and test_suite/ (8 files: conftest + test_01..08) for task_0734_print_on_demand. Tests: 55 total = 36 Difficulty (18 instances × 2) + 19 Corner (all 19 non-stub instances × 1). Queue A: every §1.8 instance covered by ≥2 tests (9 rules × 2 instances × 2). Queue B: every non-stub §1.9 instance covered by ≥1 test across sections state_machines (3), entities (3), validations (3), errors (3), rbac (3), cross_cutting_complexity_layers (2), endpoints (2). Skips: 2 corner `excluded_because` stubs (reprint_approve_when_order_not_shipped_returns_invalid_state → non_linear_state_machine/fulfillment_job_cyclic_shipped_failed_reprint_queued; platform_admin_can_verify_creator → cross_entity_state_dependency/payout_release_requires_creator_verified) — cross-refs resolve; no placeholder tests emitted. Design-tag adherence: every test docstring ends with one verbatim `Design: Difficulty/<rule_id>/<instance>` or `Design: Corner/<section>/<instance>` line matching a real yaml `name:`; no untagged, no dual-tagged, no dangling. All ≥30-char PRD citations survive literal grep of PRD.md. No pytest.mark.skip/skipif/xfail; no scaffold/§1.x references leaked into generated code.

## Step 6: Generate implementation — 2026-07-04T14:12:00.000Z

Python + Flask implementation for task_0734_print_on_demand written to workspace/implementation/ (start.sh + app.py + 5 core modules + routes/ (9 files) + services/calc.py + services/serialize.py; 56 registered routes, all 12 entities in-memory; boots via `bash start.sh` on 0.0.0.0:$PORT with a logical-clock default of 2026-03-01T00:00:00Z; end-to-end happy-path smoke passes exact expected amounts for listed price, partner charge, domestic shipping, wallet accumulation, payout release, and return-window credit).

Files produced under `/home/ubuntu/github/CodingPRD/tasks/task_0734_print_on_demand/workspace/implementation/`:
- `start.sh` (Flask-guarded pip install, `exec python3 app.py`)
- `requirements.txt` (flask==3.0.3)
- `app.py` (blueprints, error handlers, 0.0.0.0:$PORT)
- `clock.py` (logical clock, default 2026-03-01T00:00:00Z)
- `db.py` (in-memory stores per entity; `new_common_fields`, `bump`, `sorted_rows`)
- `errors.py` (ApiError + error catalog)
- `response.py` (success/error envelope, pagination helper)
- `middleware.py` (require_auth / open_endpoint decorators)
- `services/calc.py` (listing_price, partner_charge, reprint surcharge, backlog delta, floor_fee, category fee bps, strike threshold)
- `services/serialize.py` (drops internal fields like `_seq`, `_delivered_at`, `_initial_partner_charge_cents`)
- `routes/creators.py`, `storefronts.py`, `products.py`, `designs.py`, `listings.py`, `orders.py`, `fulfillment.py`, `payouts.py`, `test_ops.py`

Entities modeled (12): Creator, Storefront, Product, Variant, Design, Listing, FulfillmentPartner, Order, FulfillmentJob, ReprintRequest, PayoutCycle, ChannelSyncEvent. All in-memory dicts; no seeding at startup.

PRD ambiguities resolved:
- **Partial refund wallet math**: PRD §3.9 says "recomputed to reflect the reduced net margin" without a formula. Resolved as proportional: reduce prior creator_net by floor(prior * refund_amount / gross_amount_cents) — deducted from wallet only if the order was already DELIVERED (recognized).
- **Reprint approval — order retrograde**: state machine and side-effects list conflict: state-machine table says "SHIPPED -> ROUTED"; endpoint side-effect list and PRD §3.8 prose say "SHIPPED -> IN_PRINT". PRD wins per skill guidance — implemented `SHIPPED -> IN_PRINT`. Precondition still checks `SHIPPED`.
- **`LATE` reason_code weight**: not in PRD §3.8 weight table (DAMAGED=1, WRONG_SIZE=2, MISPRINT=0, OTHER=1). Treated as 0 for strike scoring but still accepted in reason_code enum.
- **`reprint_generation` after re-delivery**: on a delivered→reprint→re-delivered cycle, the second `mark-delivered` re-runs the final variant. Implemented as: subtract prior contribution from wallet, then add fresh final_net so the wallet never double-counts.
- **`is_sample` shipping and gross**: PRD §3.6 only removes fee/markup for the line, doesn't exempt shipping — kept shipping added to gross for sample orders.

## Step 7: Run tests + iterate to green — 2026-07-04T14:33:00.000Z

Sanity confirmed — 55/55 in every round of the parallel sweep.

- **Iterations run:** 2 (baseline sweep → 2 failures; fix sweep → all green).
- **Tests deleted:** none. Both failures were fair.
- **Fixes applied to `test_suite/`:**
  - `test_suite/test_04_validation_priority_and_dependencies.py` — added the missing `creator_verify_payload` import to the top-of-file `from test_helpers import (...)` block. `test_release_rejected_creator_payout_returns_creator_not_verified` referenced the symbol but it wasn't imported → `NameError`. Export already exists in `test_helpers/__init__.py`.
- **Fixes applied to `test_helpers/`:** none needed.
- **Fixes applied to `implementation/`:**
  - `workspace/implementation/routes/orders.py` — `mark_in_print` handler: broadened the precondition from `order.fulfillment_status == "ROUTED"` to `order.fulfillment_status in ("ROUTED", "IN_PRINT")` (job must still be `QUEUED`). PRD §3.8 states approved reprints put order back at `IN_PRINT` **and** cycle the job back to `QUEUED`, then instructs the workflow to "re-enter the print → ship → deliver sequence as if it were a fresh routing." A `QUEUED` job cannot advance to `SHIPPED` without a `mark-in-print` call, so the reprint cycle needs `mark-in-print` to accept the (IN_PRINT, QUEUED) reprint-re-entry state; without this the CONSUMER_FAULT reprint scenario (`test_final_creator_net_diverges_from_provisional_on_consumer_fault_reprint`) can never reach the final-variant `creator_net_cents` recompute at delivered.

result: All 55 tests pass in all 8 parallel rounds — fixed missing `creator_verify_payload` import in test_04 and broadened `mark_in_print` to accept the (IN_PRINT, QUEUED) reprint-re-entry state per PRD §3.8's "re-enters the print → ship → deliver sequence as if it were a fresh routing."

## Step 8: Finalize PRD — 2026-07-04T14:37:00.000Z

Sanity check: the edit widens the mark-in-print precondition to match impl (routes/orders.py:391 accepts `{ROUTED, IN_PRINT}` when job is `QUEUED`); this is consistent with the reprint-approval retrograde at fulfillment.py:206 which puts the order at `IN_PRINT` with `job.status="QUEUED"`. The subsequent mark-shipped/mark-delivered wording is untouched and still matches impl.

- **PRD.md**: 283 lines. **PRD_FINALIZED.md**: 283 lines. **Line-count delta**: 0 lines (+0%); single in-place sentence rewrite on line 172.

- **Changes** (one bullet per edit):
  - §3.8 (line 172, first sentence pair) — revise — mark-in-print precondition widened: now allows order `fulfillment_status` to be either `ROUTED` (fresh routing) or `IN_PRINT` (reprint re-entry) with the linked job at `QUEUED`, sets order to `IN_PRINT` and job `QUEUED`→`PRINTING`. Was: `ROUTED`→`IN_PRINT` only. Impl: `implementation/routes/orders.py:391` and `:394`; reprint-approval retrograde at `implementation/routes/fulfillment.py:194,206`.

- **Per-edit pre-edit search log**:
  - **Edit 1** (mark-in-print precondition):
    - (a) Subject: source-state precondition for `POST /pod/orders/{id}/mark-in-print` and the resulting order/job transitions.
    - (b) Enumerated impl paths read/grepped: `implementation/routes/orders.py:383-401` (`mark_in_print` handler — asserts order status in `{ROUTED,IN_PRINT}` AND job status `QUEUED`; sets order to `IN_PRINT`, bumps; sets job to `PRINTING`, bumps); `implementation/routes/orders.py:404-430` (`mark_shipped` — still requires `IN_PRINT` + job `PRINTING`); `implementation/routes/orders.py:433-448` (`mark_delivered` — still requires `SHIPPED` + job `SHIPPED`); `implementation/routes/orders.py:230-289` (capture→route path — freshly-routed order enters with `fulfillment_status=ROUTED` + `job.status=QUEUED`); `implementation/routes/fulfillment.py:176-218` (`approve_reprint` — cycles `job.status="QUEUED"` and sets `order.fulfillment_status="IN_PRINT"`, producing the reprint-re-entry state); `implementation/routes/fulfillment.py:104-105` (`mark_failed` — job `SHIPPED`→`FAILED`, doesn't affect mark-in-print reachability since job must be QUEUED).
    - (c) Wording adjustment: stated the two allowed source states explicitly rather than merely "from `ROUTED`", added the linked-job `QUEUED` gate that impl checks, and used "sets the order's `fulfillment_status` to `IN_PRINT`" (covers both `ROUTED→IN_PRINT` and the `IN_PRINT` self-transition case) instead of "transitions from ROUTED to IN_PRINT" so the sentence is consistent with the reprint-re-entry path. Downstream mark-shipped/mark-delivered sentences left verbatim — they already match impl exactly.

result: PRD_FINALIZED.md written; one revise in §3.8 line 172 widens the mark-in-print precondition to `(order.fulfillment_status in {ROUTED, IN_PRINT}) AND (job.status == QUEUED)` to match implementation/routes/orders.py:391 and enable the §3.8 reprint re-entry path; test-04 import fix was a fixture-only bug (no PRD edit); line counts 283→283 (0% delta).

## Step 9: Complete PRD — 2026-07-04T14:54:00.000Z

All sections preserved, no new sections.

Source: `PRD_FINALIZED.md` — 283 lines, 50417 chars.
Output: `PRD_COMPLETED.md` — 283 lines, 58455 chars. Delta: +8038 chars, 0 line delta.

Counts: 26 total in-paragraph revisions/inserts — **10 mismatch-revisions**, **16 ambiguity-pins**.

Per-change bullets:

- §2.1 (Roles) — revise — mismatch — impl authenticates & role-checks but does not compare `X-User-ID` to resource `creator_id`/`partner_id`; PRD's ownership-check language contradicts impl (`middleware.py:38-55`; ownership never called in `routes/*`).
- §2.4 (Common Resource Properties) — insert — ambiguity — pin ChannelSyncEvent field list + all stores empty on process start (`db.py:29-41`).
- §2.9 (Validation Priority) — insert — ambiguity — pin transitive body-FK resolution and that structural `ERR_INVALID_REQUEST` checks precede FK resolution in practice (`routes/orders.py:82-115`).
- §2.10 (Logical Clock) — insert — ambiguity — pin `ERR_INVALID_REQUEST` on missing/malformed `to_iso8601` and PlatformAdmin-only roles on both test-driving endpoints (`routes/test_ops.py:16-71`).
- §3.1 (Creator Onboarding) — insert — ambiguity — pin `ERR_INVALID_REQUEST` for duplicate email and outcome-value validation on `/verify` (`routes/creators.py:29-32, 62-64`).
- §3.1 (Creator Onboarding) — revise — mismatch — impl does not enforce ISO-3166 well-formedness on `payout_country_code`; PRD implied a two-letter format constraint (`routes/creators.py:25-27`).
- §3.2 (Storefront Creation) — insert — ambiguity — pin `ERR_INVALID_REQUEST` for slug uniqueness violation and invalid `integration_channel` (`routes/storefronts.py:36-53`).
- §3.3 (External Channel Integration) — insert — ambiguity — pin `ERR_INVALID_STATE` when link is attempted on NATIVE storefront or under UNVERIFIED/REJECTED creator (`routes/storefronts.py:126-136`).
- §3.3 (External Channel Integration) — insert — ambiguity — pin channel-sync-events sort/pagination and ingest-channel-order body/behavior including `creator_net_cents=0` and channel-value validation (`routes/storefronts.py:191-255`).
- §3.4 (Product Catalog) — insert — ambiguity — pin `ERR_INVALID_REQUEST` for duplicate SKU, invalid category, invalid base_cost_cents (`routes/products.py:29-49`).
- §3.4 (Product Catalog) — insert — ambiguity — pin variant creation requires only color+size, no uniqueness enforced, invalid delta yields `ERR_INVALID_REQUEST` (`routes/products.py:74-93`).
- §3.5 (Design Mockup) — insert — ambiguity — pin the exact `mockup_url` URL format `https://mockups.example.com/{id}.png` (`routes/designs.py:79`).
- §3.6 (Listing Pricing) — revise — mismatch — impl recomputes `gross_amount_cents` on capture-with-routing (adds shipping); PRD listed only three occasions and omitted this fourth (`routes/orders.py:257-262`).
- §3.7 (Buyer checkout) — insert — ambiguity — pin that `listing_id` must resolve to a listing whose `storefront_id` matches the request's `storefront_id`, else `ERR_FK_NOT_FOUND` (`routes/orders.py:121-123`).
- §3.7 (Sample orders) — insert — ambiguity — pin sample-limit governs per-order item_count only, no aggregate cap; provisional and final `creator_net_cents` both 0 (`routes/orders.py:49-54, 118-119`).
- §3.7 (Authorization/Capture) — revise — mismatch — impl computes `gross_amount_cents` at authorize with `shipping_cents=0` (since routing hasn't run), then again at capture with shipping; PRD implied a single formula (`routes/orders.py:189-190, 258-262`).
- §3.7 (Refunds — partial) — revise — mismatch — impl only debits wallet when order was DELIVERED at refund time and applies `floor(prior * amt / gross)` reduction; PRD implied unconditional recompute (`routes/orders.py:336-346`).
- §3.7 (Refunds — full) — revise — mismatch — impl debits wallet only when DELIVERED, sets `creator_net_cents=0`, only touches fulfillment when PENDING/ROUTED; PRD implied wallet always affected (`routes/orders.py:316-335`).
- §3.7 (Void) — insert — ambiguity — pin that void leaves fulfillment_status as-is and disallows non-PENDING/non-CANCELLED fulfillment states (`routes/orders.py:352-362`).
- §3.7 (Routing selector) — revise — mismatch — impl uses insertion `_seq` as a secondary tie-breaker below `created_at`; PRD claimed created_at is the terminal tie-breaker (`routes/orders.py:218-225`).
- §3.8 (Mark in print) — insert — ambiguity — pin the reprint-re-entry acceptance state (IN_PRINT with job QUEUED) and idempotent write (`routes/orders.py:383-401`).
- §3.8 (Reprint request open) — insert — ambiguity — pin `ERR_INVALID_REQUEST` on out-of-set fault_category/reason_code (`routes/fulfillment.py:128-131`).
- §3.8 (Reprint approval) — revise — mismatch — impl increments `reprint_strike_count` by exactly 1 on approval, ignoring reason_code weight; PRD called it "windowed weighted score" without disambiguating the incremental step (`routes/fulfillment.py:210-216`).
- §3.8 (Delivered — re-delivery) — insert — ambiguity — pin the wallet reconciliation on re-delivery (debit prior, credit new) that occurs when a reprint cycle re-runs mark-delivered (`routes/orders.py:451-462`).
- §3.8 (Strike score) — revise — mismatch — impl weights LATE=0; PRD didn't include LATE in the weight table (`services/calc.py:17-24`).
- §3.8 (Strike decay window) — insert — ambiguity — pin the half-open `[now-90d, now)` window (upper bound exclusive) (`routes/test_ops.py:36-64`).
- §3.9 (Payout Release) — revise — mismatch — impl uses an internal `_delivered_at` per-order stamp, not `updated_at`, to filter delivered orders into the cycle window (`routes/orders.py:455; routes/payouts.py:101-111`).
- §3.9 (Payout Cycle creation) — insert — ambiguity — pin ISO-parse-failure yields `ERR_INVALID_REQUEST`, DRAFT-only overlap check, half-open overlap predicate, and initial 0s for gross/fee/net (`routes/payouts.py:38-73`).
- §3.9 (Payout Return window) — revise — mismatch — impl compares against release's `updated_at`+72h and rejects at-or-after that instant (PRD said "strictly less than ... at release"); language clarified to match (`routes/payouts.py:161-164`).
- §4 (Endpoint /pod/creators/register) — revise — mismatch — impl accepts any recognized role header (or none) via `open_endpoint`, not just Anonymous (`middleware.py:58-73; routes/creators.py:22-23`).

result: PRD_COMPLETED.md written at /home/ubuntu/github/CodingPRD/tasks/task_0734_print_on_demand/workspace/PRD_COMPLETED.md (283 lines, 58455 chars, +8038 vs source) with 16 ambiguity-pins and 10 mismatch-revisions applied inline.
