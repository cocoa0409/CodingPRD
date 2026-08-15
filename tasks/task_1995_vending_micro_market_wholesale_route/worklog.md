# Worklog — task_1995_vending_micro_market_wholesale_route

## Step 1: Create Task Directory — 2026-08-15T05:20:00.000Z

Task directory `tasks/task_1995_vending_micro_market_wholesale_route/` and `workspace/` already existed (created by pipeline launcher); orchestrator started at Step 2.

## Step 2: Generate Scaffold — 2026-08-15T06:04:00.000Z

Scaffold generation complete for task 1995 (Vending & Micro-Market Wholesale Route Supply). All three artifacts written and lint-clean.

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_1995_vending_micro_market_wholesale_route/SCAFFOLD.yaml` — §1.0–§1.7 (no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1995_vending_micro_market_wholesale_route/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single `scaffold_difficulty_design:` key
- `/home/ubuntu/github/CodingPRD/tasks/task_1995_vending_micro_market_wholesale_route/SCAFFOLD_CORNER_DESIGN.yaml` — single `scaffold_corner_design:` key

## Counts

| Element | Count |
|---|---|
| Entities | 10 (Operator, DeliveryRoute, Product, Location, Planogram, TelemetryEvent, ReplenishmentOrder, Promotion, CreditClaim, ServiceTicket) |
| State machines | 6 (Operator cyclic ACTIVE↔SUSPENDED; Planogram supersede chain; ReplenishmentOrder parallel fulfillment×settlement with revise cycle; CreditClaim forking; Product; ServiceTicket) |
| Concurrency rules | 2 OCC (Location.version on planogram activate; ReplenishmentOrder.version on draft PATCH), both 412/ERR_STALE_VERSION |
| Calculations | 7 |
| Validations | 12 priority tiers |
| Endpoints | 51 (incl. `/_clock/set_current_utc` with pinned default 2026-08-01T00:00:00Z) |
| Error codes | 46, each triggerable by ≥1 instance |
| Roles | 6 (peer_roles; OperatorManager is entity_backed:Operator, rest opaque) |
| Difficulty instances | 18 (2 per rule × 9 rules) |
| Corner instances | 66 (56 active + 10 `excluded_because:` stubs); 653 calls scanned |

## Lint verdict (verbatim)

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

(One fix during iteration: the telemetry sub-resource path template had to use the literal `{id}` segment for lint check (f).)

## Notable design decisions

- **Archetype**: pricing engine primary + event-sourcing secondary (append-only DEX `TelemetryEvent` drives on-hand projection, replenishment suggestion, and settlement reconciliation). Flat topology with FK links, per the diversity guidance.
- **Dual variants on genuinely different domains**: order margin (provisional from planogram vend prices vs realized from DEX cash/cashless minus a 2.75% cashless fee) and route capacity (firm=CONFIRMED vs optimistic=+SUBMITTED inclusion sets).
- **Combinatorial rules in different modes**: per-line round-half-up-then-sum pinned for order pricing (1790 vs 1791 divergence baked into the instance), and a 3-branch tiered short-date/expired credit (75%/50%/100%) with a computed literal total of 1400.
- **Cascades**: claim-approve depth-3 chain (balance → auto-apply to oldest OPEN order by created_at → auto-SETTLED) and telemetry-ingest depth-2 chain (projection rebuild → DRAFT suggested-order line refresh), each spelled out hop-by-hop in side effects.
- **Priority conflicts**: state-vs-fiscal (suspended operator beats min-order) and temporal-vs-referential (expired claim window beats over-delivered-qty). Ownership was re-ordered after path-existence (priority 5) so a missing resource 404s before ownership is evaluated.
- **Overlap rules with different interval semantics**: half-open promotion windows (adjacency allowed; scope equality treats null global as its own scope so operator-specific promos can overlap global ones) vs aggregate route-day case capacity (exact equality passes).
- **Compensating invariants**: confirm+cancel conserves firm route capacity; approve+void conserves operator credit balance (void gated on applied_cents==0 and sufficient pooled balance to prevent negative balances after partial auto-application).

## Step 3: Copy Shared Files — 2026-08-15T06:07:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1995_vending_micro_market_wholesale_route/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-15T06:25:00.000Z

All contracts pass. The PRD is complete.

## Summary

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1995_vending_micro_market_wholesale_route/workspace/PRD.md` — 336 lines. The withheld files (SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml) were never opened or referenced.

**Section list** (domain-derived skeleton, not the example's):
- §1 Introduction (2 paragraphs, business-economics angle)
- §2.1 RBAC · §2.2 API Response Structure (verbatim block, byte-identical) · §2.3 Pagination · §2.4 Common Resource Properties (incl. TelemetryEvent `common_fields: false` exception) · §2.5 Logical Clock & Temporal Semantics · §2.6 Integer-Cent Monetary Precision · §2.7 OCC · §2.8 Validation Cascade & Error Precedence (12 tiers) · §2.9 Route Capacity Accounting (firm/optimistic) · §2.10 Operator Credit Ledger
- §3.1 Operator Onboarding · §3.2 Catalog & Delivery Geography · §3.3 Locations & Planograms · §3.4 Telemetry Ingestion & Suggested Replenishment · §3.5 Promotions, Order Drafting & Pricing at Submission · §3.6 Confirmation, Delivery & Settlement · §3.7 Expired/Short-Date Credit Claims · §3.8 Equipment Parts & Service Supply
- §4 Endpoint Definitions (51 rows, 4 columns) · §5 Error Code Catalogue (46 rows, 2 columns)

**Coverage audit (scaffold → PRD)**: `scenario` → §1 · `response_envelope` → §2.2 verbatim + §2.3 · `entities` → §2.4 + §3.1–3.8 · `state_machines` (20 transitions) → §3.1/3.2/3.3/3.5–3.6/3.7/3.8 · `concurrency_rules` → §2.7 + workflow restatements · `calculations` (7) → §2.9 capacity, §3.3 cull, §3.4 suggested-qty, §3.5 order-pricing/promo-resolution/provisional-margin, §3.6 realized-margin/cashless-fee, §3.7 short-date credit · `validations` (12 priorities) → §2.8 cascade + per-trigger restatement in §3 · `endpoints` → §4 + §3 narratives · `errors` → §5 + §2/§3 triggers · `roles` → §2.1 (incl. identity prose for all 6) + §4.

**Hard Contract reports**:
```
Field coverage check:
- entities[].fields: 56 required, 56 present, 0 missing
- endpoints[].request_body/input: 48 required, 48 present, 0 missing
- path_params: 10 required, 10 present, 0 missing
- sub-structure/common fields: 21 required, 21 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 12 checked, 12 expressed (explicit 12-tier ordering + submit-chain restatement), 0 missing
- concurrency_rules[] OCC: 2 checked, 2 expressed (capability + expected_location_version/expected_order_version + ERR_STALE_VERSION/412, no race framing), 0 missing
- state_machines[].transitions: 20 checked, 20 fully expressed, 0 missing
- calculations[]: 7 checked, 7 fully expressed in reconstructible prose (0 operator-syntax hits, 0 fuzzy words), 0 missing
- validations[] conditions: 12 checked, 12 matchable to error_id in §2.8/§3, 0 missing
- endpoints[].side_effects / applies_to: 51 checked, 51 expressed, 0 missing
- entities[].fields[] structured content: defaults/nullability/initials all placed (incl. activated_at null-until-ACTIVE), 0 missing
- sibling-branch symmetry: 6 groups checked (cancel×3, claim tiers, EXCLUSIVE/STACKABLE, firm/optimistic, provisional/realized, approve/reject), 6 symmetric, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 460
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Zero-Silence Rule notes** (rules at highest risk of going silent, all made explicit):
1. `ERR_PRODUCT_DISCONTINUED` carries dual status — 409 on repeated discontinuation (state tier), 422 when referenced at submit/activate (referential tier) — stated in §2.8, §3.2, and the §5 status cell.
2. Mark-delivered with a zero `order_total_cents` sends settlement straight to `SETTLED` (§3.6).
3. Auto-settlement by credit records no tender — `settled_tender` stays null (§3.6, §3.7).
4. A claim line whose product is absent from the order's lines counts as zero delivered and fails `ERR_CLAIM_EXCEEDS_DELIVERED_QTY` — explicitly *not* a planogram error (§3.7).
5. Cull insufficient-data carve-out: no event items in the 28-day window means *not* culled; velocity exactly 2 is not culled (§3.3).
6. EXCLUSIVE promotion tie-break is earliest `created_at`, never identifier (§3.5).
7. Logical clock startup default is exactly 2026-08-01T00:00:00Z and must never fall back to wall-clock (§2.5).
8. Scaffold tension preserved faithfully: suspension side-effect says claims are blocked for suspended operators, while the tier-8 check text scopes the operator-ACTIVE gate to submit/confirm/ticket-schedule — both statements projected as-is (§3.1 + §2.8) without inventing a reconciliation.
9. Capacity release semantics differ by cancel from-state (DRAFT: nothing; SUBMITTED: drops from optimistic set; CONFIRMED: exact firm restoration) — all three rendered (§2.9, §3.6).
10. Pinned rounding order reinforced with the worked 995-cent/10%-off counter-example (200/1790 vs rejected 199/1791) so the mode-b rule is unambiguous (§2.6, §3.5).

## Step 6: Generate Implementation — 2026-08-15T06:52:00.000Z

Implementation complete and verified.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1995_vending_micro_market_wholesale_route/workspace/implementation/`):

- `start.sh` — launcher (executable)
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask entry point, blueprint registration, error handlers (ApiError + 404/405/400/500)
- `db.py` — in-memory stores (10 dicts keyed by id; empty on boot, no seeding)
- `errors.py` — `ApiError` class + all 41 error-id constants from scaffold §1.6
- `clock.py` — logical clock (default `2026-08-01T00:00:00Z`, never falls back to wall clock), ISO8601 parse/format (3 fractional digits, trailing Z)
- `response.py` — envelope helpers (`meta`/`response_type`/`data`, error body `error_id`/`message`, pagination fields `limit`/`offset`/`total_count`/`has_more`, defaults 10/1/100/0)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (6 declared roles), role gating, OperatorManager ownership
- `util.py` — id/timestamp/common-field helpers, body-shape validators (`ERR_INVALID_REQUEST` vs `ERR_INVALID_QUANTITY`)
- `routes/` — 11 blueprints: operators, delivery_routes, products, locations, planograms, promotions, telemetry, orders, credit_claims, service_tickets, clock_routes
- `services/pricing.py` — all 7 calculation rules (suggested_replenishment_qty, weekly_velocity_cull, order_pricing, promo_price_resolution, margin_per_vend provisional+realized, route_capacity_consumption firm+optimistic, short_date_credit_amount) plus the telemetry and credit-approve cascades

**Endpoint count:** 51 route handlers — every row of scaffold §1.5 (50 `/wholesale/*` operations + `POST /_clock/set_current_utc`).

**start.sh contract:** `cd "$(dirname "$0")"`; guarded dependency install (`if ! python3 -c "import flask"` so per-test reboots don't re-run pip); `exec python3 app.py` (foreground, signals propagate). `app.py` binds `0.0.0.0` on `int(os.environ.get("PORT", "10000"))`. Verified live: honors `PORT=19877`, defaults to 10000, binds `0.0.0.0`, responds 200 within seconds, and boots to an empty store on every fresh process.

**Notable design decisions:**
- **Parallel state dimensions on orders** — `fulfillment_status` and `settlement_status` tracked independently on one row; capacity is a derived aggregate (never stored), so confirm/cancel effects fall out of filtered sums per §2.9, with cancel-from-CONFIRMED providing the exact compensating release.
- **Cascade chains implemented as side-effecting helpers** — telemetry ingest rebuilds `Location.on_hand_projection` (bumps `Location.version`) then refreshes the latest DRAFT `TELEMETRY_SUGGESTED` order (bumps its version); claim approve fires the 3-link cascade (balance += → auto-apply min(balance, amount_due) to oldest OPEN order by `created_at` ASC → auto-SETTLED at zero due, with `settled_tender` staying null) and the claim self-SETTLES when `applied_cents == requested_credit_cents`.
- **Tier ordering per PRD §2.8** — submit gates fire in declared order: shape (tier 2) → body-ref existence (6) → from-state (7) → related-entity gates (8) → temporal (9) → empty-order constraint (10) → referenced-entity state (11) → fiscal floor (12). Verified: a submit on a non-draft order with a stale date returns `ERR_ORDER_NOT_DRAFT`, not the temporal error.
- **Money math** — `Decimal` + `ROUND_HALF_UP` at exactly the specified step: per-line-per-case for order pricing (verified the scaffold's 995@10%×2-lines example: discount 200, total 1790), per-line for claim credits, once for the 275bps cashless fee.
- **Promotion overlap** — half-open `[starts_at, ends_at)`, equal operator scope only (null==null), adjacency allowed, terminated excluded from both pricing and overlap checks; EXCLUSIVE winner picks max effective cents with `created_at` ASC tie-break.
- **TelemetryEvent is the deliberate common-fields exception** — `id` + `created_at` only (no `updated_at`/`version`), stored with a parsed `recorded_at_dt` for window/tie-break comparisons and stripped from responses.
- One pre-existing bug fixed during verification: promo window eligibility compares parsed `_dt` fields, not the raw string fields.

Smoke coverage exercised: full order lifecycle (draft → submit → revise → submit → confirm → deliver → settle), pricing with EXCLUSIVE promo, provisional and realized margins, capacity gate + compensating release, telemetry projection + suggestion refresh cascade, credit claim approve/void/auto-apply/auto-settle, claim aggregate-quantity gate, promotion overlap scoping, cull boundary (exactly 2 not culled), OCC 412s on both guarded endpoints, RBAC 403s, and auth 400s — all passing.

## Step 5: Generate Unit Tests — 2026-08-15T06:58:00.000Z

All checks pass. Task complete.

## Summary

### test_helpers/ (9 files, `/home/ubuntu/github/CodingPRD/tasks/task_1995_vending_micro_market_wholesale_route/test_helpers/`)
- `types.py` — 9 entity TypedDicts + 13 status/role enums; `TelemetryEvent` correctly omits `updated_at`/`version` (append-only per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with 46 endpoint methods covering every §4 endpoint incl. `/_clock/set_current_utc`
- `api_errors.py` — 46 error IDs + HTTP map registered via `set_error_http_status_map`; `ERR_PRODUCT_DISCONTINUED` registered as 422 (PRD §5 lists 409 only for repeated discontinuation, which one test passes explicitly)
- `assertions.py` — per-entity `assert_*` (telemetry asserts version/updated_at **absence**) + line/slot/projection/claim-line finders
- `factories.py`, `constants.py` (cull threshold 2, 28-day window, 275 bps fee, 30/14/7 claim tiers, clock landmarks), `test_users.py` (6 roles; `make_operator_manager_headers(operator_id)` mandatory builder for the entity-backed role)
- `fixtures.py` — composite builders: `setup_selling_location` (operator+route+products+location+ACTIVE planogram with OCC version re-read), `walk_order_to_delivered`, `settle_order_with_event`, `create_claim`, `set_logical_clock`, read-back helpers
- `__init__.py` — barrel export

### test_suite/ (10 files, 92 tests collected cleanly by pytest)
- `test_01_accounts_catalog_and_access.py` (12), `test_02_planograms_tickets_and_listings.py` (10), `test_03_telemetry_suggestion_and_cull.py` (8), `test_04_order_drafting_and_state_guards.py` (12), `test_05_pricing_and_promotions.py` (11), `test_06_capacity_routes_and_submission_gates.py` (14), `test_07_delivery_and_settlement.py` (8), `test_08_credit_claim_adjudication.py` (11), `test_09_credit_ledger_and_cascades.py` (6)

### Per-queue counts
- **Queue A (Difficulty): 36 tests** — all 18 instances × exactly 2 tests
- **Queue B (Corner): 56 tests** — all 56 non-stub instances × 1 test

### Skipped instances
None. Every non-stub instance passed the PRD-first two-condition filter — including the two priority-pair instances (PRD §2.8 states "the first failing tier determines the response" and gives the claim-window-vs-quantity example verbatim). All 10 `excluded_because` stubs were verified (cross-references resolve) and not translated.

### Judgment calls (unique-derivability softening, no weakened instances)
- `operator_creation_applies_defaults`: `version == 1` reduced to int-type presence (PRD §2.4 never pins the initial value)
- `planogram_activation_supersedes_incumbent`: `activated_at` asserted via `2026-08-01T00:00:00` second-precision prefix (millisecond formatting not pinned for that field)
- Second tests for both priority-pair instances are causal controls (winner removed → loser error fires), same Design tag

### Stage 2 self-check
Automated audit (ast + yaml + grep): 0 untagged / dual-tagged / unresolved / stub-pointing tags; 18/18 difficulty instances at ≥2; 56/56 corner non-stub at ≥1; 0 stubs translated; all 92 docstrings carry a ≥8-word verbatim PRD substring and end with the Design line; no `skip`/`skipif`/`xfail`; no "scaffold" references; `pytest --collect-only` reports 92 tests.

## Step 6: Test-fix iteration loop — 2026-08-15T07:10:00.000Z

8-round parallel stability sweep (`prd-bench-local-run --isolation per-test-server`, 92 tests/round).

**Iteration 1:** all 8 rounds crashed at first boot — `ServerStartError: exited prematurely with code 143` (SIGTERM within ~1s of spawn). Root cause: co-tenant benchmark pipelines on this shared host run `pkill -f "python3 app.py"` as sweep cleanup, which matched and killed this task's server (entry file was `app.py`). Fix: renamed `workspace/implementation/app.py` → `vending_wholesale_server.py` and updated `start.sh` to exec it (same defense other tasks on this host already carry); also switched the flask presence check to `importlib.util.find_spec` to shave boot time.

**Iteration 2:** all 8 rounds green — 92/92 passed, 0 failed, 0 skipped, ~69.5s/round. No test deletions, no test_helpers changes, no implementation logic changes were needed.

## Step 7: Run Tests and Iterate — 2026-08-15T07:10:00.000Z

## Summary

**Result: CLEAN 8-round parallel sweep — all 8 rounds at 92/92 passed, 0 failed, 0 skipped (~69.5s/round).**

### Iterations run
2 (iteration 1 surfaced an infrastructure-kill bug; iteration 2 was fully green)

### Tests deleted
None.

### Fixes applied to `test_helpers/`
None.

### Fixes applied to `implementation/`
- `/home/ubuntu/github/CodingPRD/tasks/task_1995_vending_micro_market_wholesale_route/workspace/implementation/app.py` → renamed to `vending_wholesale_server.py`. The first sweep's rounds all died at boot with `ServerStartError: exited prematurely with code 143` (SIGTERM <1s after spawn). Root cause: co-tenant benchmark pipelines on this shared EC2 host run `pkill -f "python3 app.py"` as sweep cleanup, which pattern-matched and killed this task's server (confirmed by comments in other tasks' start.sh files describing the identical hazard). The task-distinctive entry filename no longer matches any `app.py` pkill pattern.
- `/home/ubuntu/github/CodingPRD/tasks/task_1995_vending_micro_market_wholesale_route/workspace/implementation/start.sh` — `exec python3 app.py` → `exec python3 vending_wholesale_server.py`; also switched the dependency presence check from `python3 -c "import flask"` to `importlib.util.find_spec('flask')` to avoid a full flask import on every per-test reboot.

No implementation logic changes were required — once the server survived boot, every PRD-derived test passed in every round, including the concurrency/timing-sensitive ones the 8-round sweep is designed to surface.

## Step 8: Finalize PRD — 2026-08-15T07:15:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1995_vending_micro_market_wholesale_route/workspace/PRD_FINALIZED.md` is written and **byte-identical to PRD.md** — every `<step_7_diff>` item was infrastructure-only and revealed no PRD silence or PRD/impl mismatch.

**Line counts / delta**
- PRD.md: 336 lines; PRD_FINALIZED.md: 336 lines; delta 0 lines (0.0%). `diff -q` confirms byte-identical.

**Changes**
- None. No inserts, no revisions.

**Per-item verification log (mandatory (a)/(b)/(c) for each step_7_diff item)**

1. **Item: `app.py` renamed to `vending_wholesale_server.py`**
   - (a) Subject: server entry-point filename / process identity.
   - (b) Paths enumerated and inspected: `workspace/implementation/vending_wholesale_server.py` (read in full — pure Flask bootstrap: blueprint registration for all 11 route modules, four error handlers, `app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))`; filename is not observable via any HTTP behavior). PRD.md grepped for `app\.py|start\.sh|entry|filename|file name` (only hit was prose "projection entry" at line 169, unrelated) and for `python|flask|start\.sh|\.py\b|executable|script|launcher|boot|spawn|process name` (only hit was the API table header at line 231) and for `server header|user-agent|process title|command line|argv|self-identif` (no matches). INSTRUCTION.md read — its `app.py` mention is only inside a non-binding Python/Flask *example*, and INSTRUCTION.md is not an edit target.
   - (c) No wording adjustment needed — PRD never pins an entry filename, so the rename neither contradicts nor disambiguates any PRD sentence. No edit committed.

2. **Item: `start.sh` — `exec python3 vending_wholesale_server.py` + `importlib.util.find_spec('flask')` dependency check**
   - (a) Subject: launcher script contents (dependency presence check, exec target).
   - (b) Paths enumerated and inspected: `workspace/implementation/start.sh` (read in full — conditional pip install + exec of the renamed entry; both changes affect only boot-time provisioning, not request handling). PRD.md grepped as above — `start.sh` has zero mentions; the PRD specifies HTTP-observable behavior only.
   - (c) No wording adjustment needed — the PRD is silent on launcher internals, and the implementation change is invisible to the API contract. No edit committed.

**Additional corroboration:** `implementation/results.8.json` shows 92 passed / 0 failed / 0 skipped, matching the step_7_diff claim that no logic changes were required once the server survived boot. No tests were deleted and no `test_helpers/` fixes occurred, so there were no auxiliary evidence sites to reconcile.

A fresh implementer reading PRD_FINALIZED.md alone already produces a behaviorally equivalent codebase; the Step 7 fixes addressed a shared-host `pkill` hazard, which is environmental, not behavioral.

## Step 9: Complete PRD — 2026-08-15T07:45:00.000Z

PRD_COMPLETED.md is complete. All 21 changed line-blocks are pure in-line revisions (`c` hunks only) — no lines or sections added or removed.

## Summary

**Source vs output:** `PRD_FINALIZED.md` 336 lines / 49,928 bytes → `PRD_COMPLETED.md` 336 lines / 57,815 bytes. Char delta **+7,811** (49,686 → 57,497 chars). Line count unchanged — every change is an in-paragraph insert/revision.

**Counts:** 23 ambiguity-pins, 9 mismatch-revisions (32 edits total; some share a line).

**Changes (one bullet each):**

- §2.1 — insert — ambiguity — creation-time ownership compares the referenced parent's operator (location's for planograms/orders/tickets, order's for claims) and runs after body-referenced ids resolve; ownership applies to writes only, reads unrestricted — middleware.py:34-37; all GET routes call `get_auth` only
- §2.3 — insert — ambiguity — out-of-range/non-integer `limit`/`offset` → `ERR_INVALID_REQUEST`; filters are exact-match, unmatched values yield empty pages — response.py:45-67
- §2.4 — insert — ambiguity — `version` starts at 1, `updated_at` initially equals `created_at` — util.py:14-18
- §2.4 — revise — mismatch — cascade mutations observable via subsequent reads; the causing operation's response returns only its own primary resource (was "every mutation is visible in the response") — telemetry.py:70-73, credit_claims.py:163-173, pricing.py:153/197/257
- §2.5 — insert — ambiguity — clock accepts any parseable instant (earlier or later); missing/unparseable `to_iso8601` → `ERR_INVALID_REQUEST`; logical clock supplies all server timestamps incl. `api_request_timestamp`; timestamp inputs echoed verbatim, compared as parsed instants; all state in-memory, restart resets stores and clock — clock_routes.py:12-23, clock.py:13-14, response.py:14-18, promotions.py:79-80, db.py:1
- §2.6 — insert — ambiguity — half-up rounding is Decimal `ROUND_HALF_UP`: ties round away from zero, negative halves go more negative — pricing.py:17-23
- §2.7 — revise — mismatch — OCC guards are strict equality (was "advanced beyond"); missing/non-integer `expected_*` → `ERR_INVALID_REQUEST`; from-state check fires before the version guard — planograms.py:133-140, orders.py:186-193
- §2.8 preamble — revise — mismatch — role authorization (tier 3) evaluated before field-level shape (tier 2) on every endpoint; only unparseable/non-object JSON precedes the role check (optional-body endpoints ignore malformed bodies); path existence + ownership precede validations that inspect stored state; creation ownership after parent resolution — e.g. operators.py:21-24, orders.py:218-226, util.py:28-37
- §2.8 tier 2 — revise — mismatch — `ERR_INVALID_QUANTITY` covers non-integer as well as non-positive `quantity_cases`/`quantity_units`/parts `quantity` — orders.py:46-50, credit_claims.py:39-41, service_tickets.py:43-45
- §2.8 tier 6 — insert — ambiguity — telemetry-event `items[].product_id` included in body-referenced existence — telemetry.py:52-53
- §3.1 — insert — ambiguity — explicit-null `default_tender` treated as omitted (→ `CASH`) — operators.py:25-27
- §3.1 — revise — mismatch — suspension does not gate credit-claim filing (§2.8 tier 8 and impl omit it; PRD §3.1 listed it) — credit_claims.py:25-60 (no operator-status check)
- §3.2 — insert — ambiguity — `daily_case_capacity`/`min_order_cents` non-negative (zero admitted) else `ERR_INVALID_REQUEST`; `delivery_weekdays` may be empty/repeat; availability `date` param required, strict `YYYY-MM-DD`, echoed in response — delivery_routes.py:26-35, 70-85
- §3.2 — insert — ambiguity — `case_pack_qty` must be positive int (→ `ERR_INVALID_REQUEST`); `base_price_cents`/`cost_cents`/`shelf_life_days` non-negative (zero admitted); `eligible_location_types` may be empty; null `perishability_class` ≡ omitted — products.py:31-51
- §3.3 — insert — ambiguity — `slots` may be empty; slot-row constraints (non-empty `slot_code`; non-negative `par_level_units`/`vend_price_cents`; duplicate `product_id` → `ERR_INVALID_REQUEST`); rows validated sequentially in payload order, full per-row chain — planograms.py:28-63
- §3.3 — revise — mismatch — activation order: `ERR_PLANOGRAM_NOT_DRAFT` from-state first, then OCC guard, then slot revalidation (PRD prose listed OCC first) — planograms.py:133-142
- §3.4 — insert — ambiguity — telemetry numeric fields non-negative (zero admitted) else `ERR_INVALID_REQUEST`; `recorded_at` only shape-checked, no clock-relative gate; `items` may be empty; per-row sequential validation — telemetry.py:25-53
- §3.4 — revise — mismatch — projection rebuilt across the location's whole event history (one entry per product ever reported), not merely the ingested event's products; location `version` bumps on every ingestion; refresh empties the suggested draft when no `ACTIVE` planogram exists — pricing.py:127-153, 156-160, 181-197
- §3.4 — insert — ambiguity — suggested lines emitted in planogram slot order — pricing.py:163-177
- §3.4 — revise — mismatch — generate-from-telemetry does validate date shape (malformed → `ERR_INVALID_REQUEST`); only future-date/weekday gates defer to submission (PRD said flatly "not validated until submission") — orders.py:110, 53-59
- §3.5 — insert — ambiguity — order creation validates shape (well-formed date, positive quantities) despite leniency; empty `lines` admitted; order lines carry no uniqueness constraint — orders.py:62-79
- §3.5 — insert — ambiguity — PATCH: absent/null members leave fields unchanged; a no-field edit still recomputes `total_cases` and bumps `version` — orders.py:194-213
- §3.5 — insert — ambiguity — promotion window must parse and `starts_at` strictly before `ends_at`, else `ERR_INVALID_REQUEST` — promotions.py:45-53
- §3.5 — insert — ambiguity — repeated termination → `ERR_INVALID_STATE_TRANSITION` (409) — promotions.py:122-125
- §3.5 — insert — ambiguity — submission's referenced-entity checks run per line in payload order (ACTIVE → eligibility → planogram membership per line, first failing line wins) — orders.py:258-268
- §3.5 — insert — ambiguity — a submit rejected with `ERR_MIN_ORDER_NOT_MET` leaves computed `unit_price_cents`/`line_total_cents`/`order_total_cents`/`promo_discount_cents` stored on the still-DRAFT order without a version increment — orders.py:270-272
- §3.5 — insert — ambiguity — revision drops per-line pinned `unit_price_cents`/`line_total_cents` — orders.py:291-293
- §3.6 — insert — ambiguity — apply-credit: from-state gate before `amount_cents` inspection; non-positive-integer amount → `ERR_INVALID_REQUEST` — orders.py:362-371
- §3.6 — revise — mismatch — settle's from-state gate fires before telemetry-event existence (strict §2.8 tier order would put tier 6 first) — orders.py:399-408
- §3.7 — insert — ambiguity — malformed `expiration_date` → `ERR_INVALID_REQUEST`; empty-`lines` claim admitted with `requested_credit_cents` 0 — credit_claims.py:42-48, 31
- §3.7 — insert — ambiguity — claim lines evaluated in payload order within each gate; first failing line determines the rejection — credit_claims.py:64-79, 82-96
- §3.8 — insert — ambiguity — parts-row constraints: non-empty `part_sku`/`part_name`, non-negative `unit_price_cents` (→ `ERR_INVALID_REQUEST`), positive `quantity` (→ `ERR_INVALID_QUANTITY`) — service_tickets.py:34-48

Output file: `/home/ubuntu/github/CodingPRD/tasks/task_1995_vending_micro_market_wholesale_route/workspace/PRD_COMPLETED.md`
