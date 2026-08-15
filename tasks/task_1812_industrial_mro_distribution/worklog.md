# Worklog — task_1812_industrial_mro_distribution

## Step 1: Create Task Directory — 2026-08-14T18:10:00.000Z

Directory tasks/task_1812_industrial_mro_distribution/ and workspace/ pre-created by the pipeline entry command (Step 1 completed upstream of this orchestration run).

## Step 2: Generate Scaffold — 2026-08-14T18:49:00.000Z

All three scaffold artifacts are generated and lint-clean for task 1812 (Industrial MRO Distribution), built purely from the scenario description plus the skill spec — no sibling tasks were inspected.

**Files written:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1812_industrial_mro_distribution/SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1812_industrial_mro_distribution/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single `scaffold_difficulty_design:` key, 19 instances (≥2 per rule × 9 rules)
- `/home/ubuntu/github/CodingPRD/tasks/task_1812_industrial_mro_distribution/SCAFFOLD_CORNER_DESIGN.yaml` — single `scaffold_corner_design:` key, 53 active instances + `excluded_because` stubs where §1.8 already covers a claim

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (47 endpoints, 10 entities, 514 recipe calls scanned, 0 violations.)

**Design shape:**
- Complexity profile: `pricing_engine` primary + `quota_allocation` secondary; layers = dual-variant calculation, cascading side effects, rate/threshold triggers, optimistic concurrency; flat topology; parallel state-machine shape (SalesOrder `status` × `fulfillment_status`) plus a cyclic RequisitionCart (OPEN→PENDING_APPROVAL→REJECTED→OPEN); 5 peer roles (DistributionAdmin/VendorRep/BranchManager opaque; CustomerBuyer/CustomerApprover entity-backed by CustomerAccount).
- All 8 scenario pillars are load-bearing: tiered contract price matrix with half-open effective windows and item-beats-class specificity; national-account rebates with average-rate provisional vs marginal-band final true-up; branch→central→drop-ship→backorder allocation waterfall with pinned selector; same-day/will-call promise via UTC minute-of-day cutoff (`<=` boundary) on a logical clock defaulting to 2026-08-01T00:00:00Z; drop-ship provisional-vs-actualized margins; per-item-class returns with pinned per-line-then-sum rounding; hazmat method/region safety gates ahead of fiscal checks; punch-out carts with threshold-based auto-approve fork.
- Difficulty-rule anchors: 2 cascades from different triggers (complete→spend→accrual→tier→rebate depth-4; cancel→release→backorder-fill→parent-recompute depth-3); 2 OCC rules (customer + price-rule PUTs, ERR_STALE_VERSION 412); 2 interval-overlap rules with different semantics (half-open price windows vs closed rebate periods); 2 compensating invariants (stock units; money reconciliation net_spend + credits == completed gross).
- All §1.8/§1.9 asserts use precomputed literals (e.g., rebate 300,000 provisional vs 200,000 final at 15,000,000 accrued; per-line-rounded return credit 164 vs sum-then-round 165; qty-tier unit prices 808/437), and every `${var}` traces to a declared `captures:` binding.

Note: two YAML-tooling fixes were applied during authoring (quoting of `$.data[N].field` captures and bracketed `grounds:` entries in flow sequences); final files parse cleanly and lint passes.

## Step 3: Copy Shared Files — 2026-08-14T18:51:00.000Z

Copied ./INSTRUCTION.md to tasks/task_1812_industrial_mro_distribution/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-14T18:58:00.000Z

All checks pass. The PRD is complete and verified. Final summary:

**Generated:** `/home/ubuntu/github/CodingPRD/tasks/task_1812_industrial_mro_distribution/workspace/PRD.md` from `SCAFFOLD.yaml` (the two forbidden `SCAFFOLD_DIFFICULTY_DESIGN.yaml` / `SCAFFOLD_CORNER_DESIGN.yaml` files were never opened or referenced).

**Document structure** — domain-derived, not template-copied:
- §1: 2-paragraph introduction (business context + role constituencies)
- §2: 10 subsections — RBAC with per-role identity translation; §2.2 verbatim block (byte-identical to `section-2.2-response-structure.md`); pagination; the logical clock (`2026-08-01T00:00:00Z` startup default, `to_iso8601`/`current_utc`); common resource properties; integer-cents/round-half-up discipline; OCC; left-to-right existence ordering; the `available_qty` identity; the 11-tier validation cascade stated as explicit priority prose
- §3: 9 subsections organized by business process (catalog/accounts → price matrix → stock/replenishment → punch-out carts → order capture → confirmation gates/waterfall → branch execution/drop-ship → returns → rebate accrual/true-up/settlement), with all formulas translated to precise prose (no pseudocode, no fuzzy words; freight constants 25,000/1,500/795/2,500 cents, quantity tiers 10→3%/50→5%, both rebate worked examples and the 103-cent per-line-rounding example embedded)
- §4: 47-row endpoint table, 4 columns only
- §5: 35-row error catalogue, 2 columns only; document ends there with no audit footer

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields + endpoint inputs + query/path params: 89 required, 89 present, 0 missing
  (one initial miss, `location_id`, was repaired in §3.3 and re-verified)
Status: PASS
```

```
Rule coverage check:
- validations[] priority: 11 checked, 11 expressed in explicit ordered prose (§2.10 + local reinforcement), 0 missing
- concurrency_rules[] OCC: 2 checked, 2 expressed (write endpoint + expected_customer_version/expected_price_rule_version + ERR_STALE_VERSION 412 all named), 0 missing
- state_machines[].transitions: 30 checked, 30 fully expressed (from/to, preconditions w/ error ids, side effects incl. all cascade links), 0 missing
- calculations[]: 9 checked, 9 fully expressed in precise reconstructible prose, 0 missing
- validations[] conditions: 11 checked, 11 matchable to error ids in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: 47 checked, 47 expressed, 0 missing
- entities[].fields[] structured content (defaults, null-until semantics, enum members): 107 checked, 107 reconstructible, 0 missing
- sibling-branch symmetry: 6 groups checked (mark-ready 4-way, cart submit fork, cart approve/reject, return approve/reject, mark-fulfilled 2-way, cancel 2-way), 6 with equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 396
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional mechanical verifications: §2.2 byte-identical to the canonical source; all 30 state values and every enum member present as exact strings; all 35 scaffold error IDs mentioned in §1–§4 prose; endpoint-table row count matches scaffold exactly (47); zero operator-syntax or fuzzy-hedging hits in prose.

## Step 5: Generate Unit Tests — 2026-08-14T19:20:00.000Z

Generation complete. Summary of what was produced for `tasks/task_1812_industrial_mro_distribution/`:

## Stage 1 — `test_helpers/` (9 files)
- `types.py` — 16 enums + 10 entity TypedDicts (all entities carry `id`/`created_at`/`updated_at`/`version` per PRD §2.5)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per each of the 40 endpoints (all `/mro/*` plus `/_clock/set_current_utc`)
- `api_errors.py` — all 35 `ApiErrorId` values with the §5 HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity asserts plus `assert_available_qty_identity` (PRD §2.9); nullable computed fields checked leniently
- `factories.py`, `constants.py` (freight 25000/1500/795/2500, qty tiers 10→3%/50→5%, return windows 60/30, default clock), `test_users.py` (5 roles + mandatory `make_buyer_headers`/`make_approver_headers` entity-backed builders), `fixtures.py` (state-progression, order lifecycle through confirm/fulfill/complete, cart helpers with identity threading, rebate helpers), `__init__.py` barrel

## Stage 2 — `test_suite/` (11 files, 91 tests)
- `test_01_catalog_customers_and_reads.py` (12), `test_02_price_matrix_and_line_pricing.py` (9), `test_03_freight_and_credit_gate.py` (5), `test_04_carts_and_approval.py` (8), `test_05_order_confirmation_and_state_gates.py` (13), `test_06_allocation_and_stock.py` (7), `test_07_fulfillment_and_drop_ship.py` (8), `test_08_returns.py` (10), `test_09_rebates.py` (12), `test_10_security_occ_and_validation_order.py` (7), plus `conftest.py`

## Audit results (all clean)
- **Coverage**: all 19 difficulty instances have exactly ≥2 tests; all 53 non-stub corner instances have ≥1 test. The 7 `excluded_because:` stubs were not translated, and all their `difficulty_instance` cross-references resolve.
- **C4 tags**: every test ends its docstring with exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line, each resolving to a real YAML instance.
- **C1 verbatim pass**: every `PRD §x.y: "..."` citation was mechanically checked to survive literal grep of `PRD.md` (whitespace-normalized); two ellipsized citations were fixed to full verbatim rows.
- **PRD-first filter**: every emitted test traces to verbatim PRD prose naming the asserted rule (including §2.10's cascade order for the two priority-pair instances and §3.9's worked 300,000/200,000 true-up example). No `skip`/`xfail`/`skipif` markers anywhere; no scaffold references in comments.
- **Syntax/collection**: all files compile; `pytest --collect-only` collects exactly 91 tests with `test_helpers` imports resolving against the real framework.

## Step 6: Generate Implementation — 2026-08-14T19:20:00.000Z

All four test suites pass on a single fresh boot — 129 checks total, zero failures. The implementation is complete.

## Summary

Generated a complete Python + Flask implementation for task 1812 (Industrial MRO Distribution) at `/home/ubuntu/github/CodingPRD/tasks/task_1812_industrial_mro_distribution/workspace/implementation/`:

- **`start.sh`** — executable launcher; guards `pip install` behind a flask import check (safe for per-test-server reboots), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- **`requirements.txt`** — flask
- **`app.py`** — single-file implementation (~1,900 lines)

### What was implemented

- **All 42 endpoints** from the endpoint table, including `POST /_clock/set_current_utc` with the pinned default `2026-08-01T00:00:00Z` and no wall-clock fallback
- **Response envelope** exactly per scaffold: `meta.api_request_id` (`req_…`), `meta.api_request_timestamp` (ISO8601, 3 fractional digits), `response_type`, `data`; list responses carry `limit`/`offset`/`total_count`/`has_more` in `meta`
- **Auth/RBAC**: `X-User-ID`/`X-User-Role` headers, 5 roles, entity-backed scope enforcement (`ERR_CUSTOMER_SCOPE_MISMATCH`) for CustomerBuyer/CustomerApprover across carts, orders, returns, customer records, and scoped list endpoints (auto-filter + explicit-filter rejection)
- **Pricing engine**: ACTIVE rule resolution with item-over-class specificity, half-open windows, FIXED_PRICE/DISCOUNT_PCT with `Decimal` ROUND_HALF_UP at the two pinned steps, whole-quantity tiers (≥50 → 5%, ≥10 → 3%), list-price cap
- **Order totals**: pinned freight order (WILL_CALL 0, free at subtotal ≥ 25000, SAME_DAY 1500, STANDARD 795) plus 2500 hazmat handling independent of the waiver
- **Allocation waterfall**: branch → single central (available DESC, created_at ASC tie-break) → drop-ship → backorder; `fulfillment_source` derivation; provisional drop-ship margins at confirm; vendor-confirm actualization with exact-coverage gate
- **Backorder auto-fill chain** shared by restock, cancel, and return-receive (order `created_at` ASC, line position ASC, `PARTIALLY_ALLOCATED` → `ALLOCATED` recompute)
- **Rebates**: closed-interval overlap gate, average-rate provisional accrual, marginal-band final at close with true-up delta (verified against the PRD example: accrued 15M → provisional 300,000 vs final 200,000, delta −100,000), settle
- **Returns**: per-class windows measured from `fulfilled_at` date (60d STOCKED / 30d SPECIAL_ORDER, last-day admitted), NON_RETURNABLE rejection, cumulative-qty validation over non-rejected returns, pinned per-line rounding (two 103-cent SPECIAL_ORDER lines → 82 + 82 = 164), selective RESALEABLE-STOCKED putaway, spend/rebate decrement cascade
- **Parallel state dimensions** on SalesOrder (status × fulfillment_status), promise date with inclusive cutoff boundary, `sla_breach` at mark-ready
- **OCC**: `expected_customer_version` / `expected_price_rule_version` mandatory, `ERR_STALE_VERSION` 412; window edit on an ACTIVE rule re-runs the overlap check
- **Validation cascade** in priority order with all 34 scaffold error IDs at their specified HTTP statuses
- **Empty store at boot** — no seeding anywhere; verified clean across three consecutive `bash start.sh` launches

### Verification

129 end-to-end checks across four suites (core order lifecycle, rebate lifecycle + true-up, backorder auto-fill, carts/approval/OCC/hazmat/credit/promise/returns/pricing edge cases, scope/existence-ordering/pagination) — all passing, including against a fresh boot simulating the harness's per-test-server restart behavior.

## Step 7: Run Tests and Iterate — 2026-08-14T19:35:00.000Z

Summary

- **Iterations run**: 2 (sweep 1: 6 failing tests × all 8 rounds, deterministic; sweep 2 after fix: 91/91 passed in all 8 rounds, 0 failures, 0 errors).

- **Tests deleted**: none.

- **Fixes applied to `test_helpers/`**:
  - `/home/ubuntu/github/CodingPRD/tasks/task_1812_industrial_mro_distribution/test_helpers/factories.py` — `create_price_rule_payload`: the factory unconditionally injected its defaults `item_class="STOCKED"` and `discount_pct=10` into every payload. When a test requested an item-scoped `FIXED_PRICE` rule (`item_id=...`, `contract_unit_price_cents=...`), the merged payload carried both scope keys and both value fields, which PRD §3.2 forbids verbatim ("exactly one of `item_id` ... or `item_class` ... must be set — supplying both or neither is a shape violation rejected with `ERR_VALIDATION`" and "each must omit the other's value field"). The implementation was PRD-correct to reject it; the factory was constructing a PRD-invalid precondition. Fix: after merging overrides, pop the default `item_class` when the caller passed `item_id` without explicitly passing `item_class`, and pop the default `discount_pct` when the effective `rule_type` is `FIXED_PRICE` and the caller didn't set `discount_pct`. The deliberate both-set shape test (`test_price_rule_scope_exactly_one_rejected`) is preserved because it passes `item_class` explicitly. All call-site payload shapes verified locally.

- **Fixes applied to `implementation/`**: none — the implementation's rejection was exactly the PRD-required behavior; the 6 failures were one upstream factory bug masquerading as 6 independent failures (the triage-hint pattern: identical "Setup step failed ... Exactly one of item_id / item_class must be set" across all 6).

## Step 8: Finalize PRD — 2026-08-14T19:42:00.000Z

## Summary

**Output produced**: `/home/ubuntu/github/CodingPRD/tasks/task_1812_industrial_mro_distribution/workspace/PRD_FINALIZED.md` — an exact copy of `PRD.md` with **zero edits**.

**Line counts**: PRD.md = 279 lines, PRD_FINALIZED.md = 279 lines, delta = 0%.

### Changes applied

None. The single `<step_7_diff>` item is a **pure test-fixture bug**, not a PRD silence or PRD/impl mismatch:

- The only Step 7 fix was to `test_helpers/factories.py` (`create_price_rule_payload`), which had been unconditionally injecting `item_class="STOCKED"` and `discount_pct=10` defaults, constructing payloads that violated shape rules the PRD already pins verbatim. No implementation fixes were applied, and no tests were deleted. The step_7_diff itself states: "the implementation's rejection was exactly the PRD-required behavior."

### Verification log (why no edit was warranted)

Per the method, I located the matching implementation behavior before deciding:

- (a) **Subject**: price-rule scope shape (exactly-one-of `item_id`/`item_class`) and rule-type value-field pairing (`contract_unit_price_cents` vs `discount_pct`).
- (b) **Impl paths enumerated and read**:
  - `implementation/app.py:938-940` — create path rejects both-set/neither-set scope with `ERR_VALIDATION`, matching PRD §3.2's "supplying both or neither is a shape violation rejected with `ERR_VALIDATION`" verbatim.
  - `implementation/app.py:862-883` (`validate_rule_value_fields`, `require_all=True` on create) — `FIXED_PRICE` requires `contract_unit_price_cents` and rejects present `discount_pct`; `DISCOUNT_PCT` requires `discount_pct` strictly in (0, 100) and rejects present `contract_unit_price_cents`. Matches PRD §3.2's "each must omit the other's value field" verbatim.
  - `implementation/app.py:1000-1075` (`update_price_rule`) — merges value fields, normalizes the off-type field to null (lines 1045, 1054); consistent with §3.2's pairing rule and §2.7's OCC description.
  - `implementation/app.py:886-916` (`check_rule_overlap`) — scope-key semantics (tier+item vs. tier+class, half-open windows) match §3.2's activation gate prose; not touched by the Step 7 item but enumerated per the no-new-mismatch search discipline.
- (c) **Wording adjustment**: none — the PRD text at §3.2 (lines 123-125 of PRD.md) already uniquely determines every behavior the implementation exhibits at all enumerated sites, so no insert or revise was committed.

Since the PRD already pins the behavior that the failing factory violated, any PRD edit here would have been a change-for-change's-sake and risked creating a new mismatch. `PRD_FINALIZED.md` is therefore byte-identical to `PRD.md`, and a fresh implementer reading it already receives the full, uniquely-determined specification the current implementation was built against.

## Step 9: Complete PRD — 2026-08-14T19:58:00.000Z

All edits applied cleanly. The diff confirms 19 changed lines (in-paragraph replacements only; no lines added or removed), bundling 23 logical changes since two long cascade/paragraph lines each received two edits.

## Summary

**Source vs output:** `PRD_FINALIZED.md` (identical to `PRD.md`) 279 lines / 46,907 chars → `PRD_COMPLETED.md` 279 lines / 49,594 chars (**+2,687 chars**, +0 lines). Output at `/home/ubuntu/github/CodingPRD/tasks/task_1812_industrial_mro_distribution/workspace/PRD_COMPLETED.md`.

**Counts:** 18 ambiguity-pins, 5 mismatch-revisions (23 changes total).

**Changes:**

- §2.2 — insert — ambiguity — `api_request_timestamp` pinned as stamped from the logical clock — app.py:94,105 (clock_iso at :31-33)
- §2.3 — revise — ambiguity — non-integer/out-of-range `limit` and non-integer/negative `offset` rejected with `ERR_VALIDATION`; `created_at` ties broken by creation order; `has_more` true exactly when items remain beyond the page — app.py:166-195
- §2.4 — revise — ambiguity — offset-less `to_iso8601` read as UTC, offset-bearing converted to UTC, malformed/non-string → `ERR_VALIDATION` — app.py:611-622
- §2.5 — insert — ambiguity — `created_at`/`updated_at` stamped from the logical clock — app.py:204,216-218
- §2.9 — revise — mismatch — StockBalance lazy creation also occurs on first return putaway, not only first restock — app.py:2185
- §2.10 (step 3) — revise — mismatch — for carts/orders/returns/rebate-agreements the owner's identity is discovered by loading the target, so target existence precedes the scope check — app.py:1396-1399, 1682-1685, 2120-2125, 1176-1179, 1766-1769, 2025-2031
- §2.10 (step 4) — revise — mismatch — body-carried item references (cart/order lines, restock `item_id`, price-rule `item_id`) are existence-checked after shape checks, not before — app.py:1371-1376, 1557-1563, 1301-1307, 949-953
- §2.10 (step 5) — insert — ambiguity — a request body an endpoint reads must be a JSON object — app.py:225-233
- §2.10 (step 10) — revise — mismatch — two local inversions pinned: national-account gate fires before period-overlap at agreement create; vendor line-coverage fires before per-entry cost-figure validation — app.py:1139-1153, 1914-1936
- §3.1 — revise — ambiguity — `sku` non-empty; `description` may be empty — app.py:788-791
- §3.1 — revise — ambiguity — `account_number`, `display_name`, `primary_ship_to_state` non-empty — app.py:648-654
- §3.2 — revise — ambiguity — rule PUT may switch `rule_type` (new type's value field required, other cleared); tier and scope immutable — app.py:1013-1054, 1069-1073
- §3.3 — revise — ambiguity — `location_code`, `region_state` non-empty — app.py:1250-1254
- §3.3 — insert — ambiguity — restock responds with the updated StockBalance as it stands after the auto-fill chain — app.py:1317
- §3.3 — insert — ambiguity — backorder auto-fill re-derives each filled line's `fulfillment_source` — app.py:531
- §3.4 — revise — ambiguity — `punch_out_external_ref` stored verbatim; carts born with `estimated_total_cents` zero and `rejection_reason` unset; revision does not reprice — app.py:1378-1386, 1425-1430
- §3.4 — insert — ambiguity — only `OPEN` carts may be submitted; other statuses → `ERR_INVALID_STATE_TRANSITION` — app.py:1442-1443
- §3.5 — insert — ambiguity — order-create existence resolution order pinned: `customer_id`, `fulfillment_branch_id`, then `source_cart_id` — app.py:1524-1542
- §3.6 — revise — ambiguity — central-depot ranking: residual same-millisecond `created_at` ties broken by creation order — app.py:414-428
- §3.7 — insert — ambiguity — vendor-confirm `actual_costs` coverage judged as a set; duplicate entries neither add nor remove coverage and the last occurrence's figures prevail — app.py:1914-1945
- §3.7 — revise — mismatch — completion gates ordered: commercial `status` must be `CONFIRMED` (`ERR_INVALID_STATE_TRANSITION` otherwise, e.g. for a `SUBMITTED` order) before the `FULFILLED` check raises `ERR_ORDER_NOT_FULFILLED`; old prose said "anything earlier" → `ERR_ORDER_NOT_FULFILLED` — app.py:1959-1965
- §3.9 — insert — ambiguity — when return credits drive `accrued_spend_cents` negative, `current_tier_index` falls back to 0 — app.py:550-556
- §4 (endpoint table) — revise — ambiguity — PUT `/mro/price-rules/{id}` description widened from "value or window" to "rule_type, value, or window" — app.py:1013-1017, 1069

All other implementation behaviors (41 endpoints, roles per endpoint, freight/credit/pricing/rebate formulas, rounding steps, allocation waterfall, state machines, error catalogue, envelope shape) were verified against the PRD and already uniquely pinned, so no further changes were needed.
