# Worklog — task_1818_investment_policy_statement_portfolio

## Step 1: Create Task Directory — 2026-08-14T18:32:00.000Z

Directory `tasks/task_1818_investment_policy_statement_portfolio/` and `workspace/` were pre-created by the pipeline launcher (per skill invocation args). No index scan performed; no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-14T19:41:00.000Z

Scaffold generation complete. All three artifacts are written, lint-clean, and self-consistent.

### Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_1818_investment_policy_statement_portfolio/SCAFFOLD.yaml` (2,095 lines) — §1.0–§1.7; contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`; scenario string verbatim
- `/home/ubuntu/github/CodingPRD/tasks/task_1818_investment_policy_statement_portfolio/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1,002 lines) — single top-level key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1818_investment_policy_statement_portfolio/SCAFFOLD_CORNER_DESIGN.yaml` (2,064 lines) — single top-level key `scaffold_corner_design`

### Section counts (SCAFFOLD.yaml)

| Section | Count |
|---|---|
| entities | 15 |
| state_machines | 11 (incl. Portfolio parallel lifecycle×drift dimensions, proposal revision cycle, withdrawal re-model loop, IPS supersede self-reference) |
| calculations | 8 (drift bps threshold, per-line-floored trade generation, pinned-order cash waterfall, dual-variant withdrawal impact, TWR/Modified-Dietz performance, average-cost lot relief, month-clamping review schedule, event-sourced valuation) |
| validations | 49 rows across 13 priority tiers |
| endpoints | 79 |
| errors | 49 (every one referenced by a validation/transition and exercised by at least one test design) |
| roles | 6 (Advisor, ComplianceOfficer, entity-backed Client, CommitteeMember, CommitteeChair, PlatformAdmin — segregation-of-duties model) |
| concurrency_rules | 2 true-race OCC rules (amendment finalize on `IPS.version`, proposal generate on `Portfolio.version`) |

Complexity profile: compliance/audit + event-sourcing archetypes; flat topology; cyclic machines; 4 layers (OCC, cascading side effects, dual-variant calc, version-pinning on approval).

### Difficulty design: 24 instances (≥2 per rule, all 9 rules)

dual_variant_calc 2, combinatorial_formula 3 (modes a, b, c), non_linear_state_machine 3, transitive_cascade 2 (depth-4 reprice cascade; depth-3 amendment-finalize cascade), priority_pair_validation_conflict 3 (distinct category pairs), boundary_precision_check 4 (bps, cents, vote count, timestamp), cross_entity_state_dependency 3 (distinct pairs), resource_temporal_overlap 2 (half-open vs closed interval semantics), compensating_invariant 2 (total-value conservation; quantity/basis/cash void round-trip). Every numeric assert was pre-computed by executing the formulas in Python (e.g., per-line tax rounding 1003 vs aggregate 1002; TWR 413 bps vs Dietz 417 bps on identical flows; waterfall buy trim 73→68 units).

### Corner design: 91 entries (72 active instances + 19 `excluded_because` stubs)

All nine claim-extraction-guide sections covered: entities 12, state_machines 21, calculations 14, validations 22, endpoints 5, errors 2, rbac 8, complexity_layers 6, consistency_model 1 (counts include stubs).

### Lint verdict (verbatim)

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(79 endpoints, 15 entities, 24 §1.8 + 72 §1.9 active instances, 1,344 calls scanned, 0 violations.)

Additional QA passed: zero unbound `${var}` placeholders (lint-enforced), all OCC `expected_*_version` payloads reference captures, no forbidden concurrency vocabulary, unique instance names across both design files, all stubs cite existing difficulty instances, and every error code is both triggerable and asserted. The logical clock defaults to `2026-08-01T00:00:00Z` per the skill mandate, with a corner instance proving the default via event-futurity rejection.

## Step 3: Copy Shared Files — 2026-08-14T19:42:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1818_investment_policy_statement_portfolio/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T19:55:00.000Z

All three hard contracts pass. The PRD is complete. Here is the final summary.

### Deliverable

- **Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_1818_investment_policy_statement_portfolio/workspace/PRD.md`
- **Length:** 384 lines
- **Withheld files respected:** `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, greped, or referenced.

### Section list

1. **Introduction** (2 paragraphs — fiduciary-process angle + technical commitments)
2. **Global Specifications & System-Wide Principles** — 2.1 Users/Roles/Ownership · 2.2 API Response Structure (emitted byte-verbatim from `section-2.2-response-structure.md`, verified by exact substring match) · 2.3 Pagination · 2.4 Common Resource Properties (incl. `CashFlowEvent` carrying only `id`/`created_at`) · 2.5 The Logical Clock (startup default `2026-08-01T00:00:00Z`, `PlatformAdmin`-only setter) · 2.6 Monetary Precision, Percentages, and Rounding · 2.7 Validation Order and Error Precedence (all 13 priority categories, ordered) · 2.8 Optimistic Concurrency Control (exactly two OCC rules) · 2.9 The Cash Ledger (event-sourced projections, polymorphic source) · 2.10 Two Independent Portfolio Dimensions · 2.11 Cascades and Cross-Entity Consistency · 2.12 Segregation of Duties
3. **Business Logic & Workflows** — 3.1 Client Onboarding & Termination · 3.2 IPS Lifecycle · 3.3 Securities/Pricing/Restricted List · 3.4 Portfolios/Positions/Cash Movements · 3.5 Drift Monitoring & Rebalance Proposals · 3.6 Withdrawal Modeling & Settlement · 3.7 Benchmarks & Performance Measurement · 3.8 Amendments/Votes/Minutes
4. **Endpoint Definitions** — 79 rows (matches scaffold's 79 endpoints), 4 columns only
5. **Error Code Catalogue** — 49 rows, 2 columns only

### Coverage audit (scaffold → PRD)

| Scaffold rule group | PRD passage |
|---|---|
| `response_envelope` (envelope, pagination defaults 10/1/100/0, meta fields, created_at-ascending sort) | §2.2 (verbatim), §2.3 |
| 15 entities, 93 fields — all names in backticks | scattered §2.1/§2.4/§2.9 + §3.1–3.8; null-until semantics for `activated_at`, `executed_at`/`executed_price_cents`, `voided_at`, `modeled_at`, `finalized_*`, `ratified_*`; defaults (`review_cadence_months` 12, `description`/`reason` "", all initial states) |
| 11 state machines, every transition (from/to, preconditions + error ids, side effects) | Client §3.1; IPS (11 transitions incl. 4 termination cascades) §3.2; Security §3.3; Portfolio lifecycle + 4 drift transitions §3.4/§3.5; Proposal (11 transitions incl. create-with-supersede, TTL expiry, revision loop) §3.5; Trade (6 transitions) §3.5; Withdrawal (8 transitions incl. staleness revert) §3.6; Report §3.7; Amendment (7 transitions) §3.8; Minute §3.8 |
| 2 `concurrency_rules` | §2.8 — `expected_portfolio_version`→`ERR_STALE_PORTFOLIO_VERSION` (412), `expected_ips_version`→`ERR_STALE_IPS_VERSION` (412); "no other endpoint accepts a version field" |
| 8 calculations, full formulas in precise prose | drift_assessment §3.5; trade generation + cash waterfall (pinned order, per-line floor, 2,000 bps reserve) §3.5; withdrawal model (both variants, ceil sizing, feasibility fallback) §3.6; performance_return (TWR chain + Modified Dietz, round-once) §3.7; tax_lot_relief (single-rounding relief, full-exit rule, void reversal) §3.5; ips_review_schedule (month-add clamp, strict overdue) §3.2; portfolio_valuation (arrival-order ledger) §2.9 |
| 50 validations with priorities | §2.7 ordered 13-category precedence + explicit shared-endpoint orderings (submit §3.2; generation §3.5; execute §3.5; finalize §2.7/§3.8); every condition paired with its `error_id` near its workflow |
| 79 endpoints (request bodies, query filters, side effects) | §4 table + prose; all 58 endpoint identifiers (`targets`, `direction`, `to_iso8601`, `expired_proposal_count`, `expired_proposal_ids`, `current_utc`, all query params incl. `from`/`to`, …) covered |
| 49 errors | all named in §2/§3 prose and indexed in §5 |
| 6 roles + identities | §2.1 — `Client` entity-backed ownership sentence; 5 opaque roles individually named |

**Machine-checked results:**
- Contract 1 (fields): 93/93 present, 0 missing; endpoint identifiers 58/58, 0 missing
- Contract 2 (rules): every transition/calculation/validation/OCC rule expressed per the audit above; 64/64 enum & state values present as exact strings
- Contract 3 (§3 path purity): 733 backticked tokens scanned in §3 — 0 paths, 0 bare HTTP methods, 0 method+path combos
- No pseudocode operators (`==`, `>=`, `min(`, `AND`/`OR`, …) and no fuzzy quantifiers anywhere in prose
- §2.2 block byte-identical to the canonical source; §4 = 4 columns; §5 = 2 columns; PRD ends at §5 with no audit footer

## Step 5: Generate Unit Tests — 2026-08-14T20:15:00.000Z

Generation complete. Summary for Step 7's diagnostic loop:

### Files written

**test_helpers/** (9 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_1818_investment_policy_statement_portfolio/test_helpers/`):
- `types.py` — 25 status/role enums + 16 entity TypedDicts; `CashFlowEvent` correctly omits `updated_at`/`version` (append-only, PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per §4 endpoint (45 methods, all under `/advisory`)
- `api_errors.py` — 49 `ApiErrorId` values + HTTP map registered via `set_error_http_status_map`
- `assertions.py`, `factories.py`, `constants.py` (CLOCK_DEFAULT 2026-08-01, CAPITAL_GAINS_RATE_BPS 2000, QUORUM 3, TTL 7d, RISK_DELTA_MAX 10, CLASS_ORDER)
- `test_users.py` — `TEST_USERS` + `make_client_headers(client_id)` (entity-backed) + per-id builders for Advisor/CommitteeMember/CommitteeChair (SoD distinctness)
- `fixtures.py` — tiers: `create_active_client`, `create_active_ips` (full DRAFT→ACTIVE pipeline signing with `make_client_headers`), `setup_active_portfolio`, canonical `setup_three_lot_portfolio` (cash 100000; EQA 100@1000 b90000; EQB 100@1000 b40000; EIB 200@500 b110000), `setup_breached_60_40`, `generate_proposal` (fresh OCC read), `setup_quorum_amendment`, `create_ratified_minute`, `finalize_amendment`, withdrawal model/settle helpers

**test_suite/** — `conftest.py` + 9 test files: `test_01_envelope_auth_rbac`, `test_02_client_lifecycle`, `test_03_ips_lifecycle`, `test_04_securities_positions_restrictions`, `test_05_portfolios_cash_ledger`, `test_06_proposals_trades`, `test_07_withdrawals`, `test_08_benchmarks_reports`, `test_09_amendments_minutes`.

### Coverage (audited programmatically)
- **126 tests, 96 distinct design tags.** All 24 difficulty instances have ≥2 tests (48 tests); all 72 non-stub corner instances have ≥1 test. No stub translated (all 14 stub cross-references resolve). Every test ends with exactly one verbatim `Design: Difficulty/<rule>/<name>` or `Design: Corner/<section>/<name>` line; zero unknown tags; zero skip/xfail; zero "scaffold" mentions. Every PRD citation passes a whitespace-normalized literal grep of PRD.md. All files compile; pytest collects cleanly.

### Instances skipped
None. Every non-stub instance passed the PRD-first two-condition filter.

### Judgment calls / weakened sub-assertions (relevant for the diagnostic loop)
1. **`execute_then_void_restores_quantity_basis_cash`** — the instance's `lifetime_realized_gains_cents == 0` sub-assertion was dropped: the PRD void paragraph enumerates restoration of only `quantity`, `cost_basis_cents`, `cash_balance_cents` ("the net effect returns quantity, cost_basis_cents, and cash_balance_cents to their pre-execution values"), so gains-reversal is not uniquely derivable. Tests assert the triple, the TRADE_VOID event (−120000, source_type TRADE), trade VOIDED + `voided_at`, proposal still EXECUTED.
2. **`rebalance_per_line_tax_rounding_mode_b`** — the "sell order EQ1, EQ2, EQ3" list-order sub-assertion was dropped (list ordering among trades minted in one request is not pinned by the PRD); asserted instead per-security quantities {EQ1:1, EQ2:1, EQ3:2} and the pinned totals (reserve 1003, sells 5012, buys 0, cash_delta 4009), which uniquely encode the per-line rounding order.
3. **`cashflow_event_immutability_common_fields_false`** — the "no POST/PUT/DELETE route exists" sub-assertion is un-testable via the declared surface; kept the field-shape assertions (id + created_at only, signed amount, provenance).
4. **`rbac_client_scoped_lists`** — kept the 403-on-foreign-`client_id`-filter assertion on the strength of §2.1's ownership rule naming "its portfolios"; if Step 7 sees a silent-scoping implementation fail here, this is the place to re-adjudicate.
5. **Tie-break reliance**: `buy_selector_price_rank_then_created_at_tiebreak` and the per-line-tax sell split rely on creation order being observable via `created_at` ties resolving to insertion order; both logical-clock and wall-clock readings converge on the asserted outcome under any stable ordering.

No baseline/smoke/RBAC/listing/pagination tests were invented outside the two indices; pagination and RBAC tests present are exactly the corner instances that enumerate them.

## Step 6: Generate Implementation — 2026-08-14T20:15:00.000Z

Done. Implementation complete and verified.

### Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1818_investment_policy_statement_portfolio/workspace/implementation/`):

- `start.sh` — guarded install (`if ! python3 -c "import flask"`), `exec python3 app.py`, executable
- `requirements.txt` — flask only
- `app.py` — app factory, blueprint registration, ApiError/404/405 handlers, `0.0.0.0:$PORT` (default 10000)
- `store.py` — in-memory dicts per entity + insertion sequence counter; **empty at every boot, zero seeding**
- `logical_clock.py` — logical clock defaulting to exactly `2026-08-01T00:00:00Z`; all timestamps (including `meta.api_request_timestamp`) read it; 3-fractional-digit `Z` formatting
- `errors.py`, `envelope.py`, `auth.py`, `validate.py`, `serialize.py` — error type, `meta`/`response_type`/`data` envelope with `limit/offset/total_count/has_more` pagination, `X-User-ID`/`X-User-Role` auth (6 roles), request-shape validators, computed-field serializers
- `logic.py` / `logic2.py` — valuations, event-sourced ledger, drift assessment (exact `Fraction` bps, strict `>` band), trade generation (gain-per-unit ranking, per-line floor), cash waterfall (sells → reserve → buy trim in CLASS_ORDER, sells never recomputed), execution/void (exact compensation), withdrawal model (CASH_FIRST/PRO_RATA ceil / TAX_AWARE variants, projected drift), TWR/MWD returns, `month_add` clamp, all cascades (supersede/terminate/finalize pin-expiry, reprice, staleness reverts, create-with-supersede)
- 15 `routes_*.py` modules

**Endpoint coverage: 79/79** (verified by counting route decorators against the PRD §4 table).

**Verification**: three smoke suites (~130 assertions) pass on fresh boots — main lifecycle, deep calculations (sell ranking, tax reserve 17820-trim case, PRO_RATA vs TAX_AWARE plans, TWR=1000bps vs MWD=1021bps on identical flows, void exact-compensation, band-edge equality, untargeted-holding breach, supersede/terminate/pin cascades, SoD gates, quorum, checkpoint TTL), and edge validations (all 40+ error IDs exercised). Restart robustness confirmed: 5/5 `bash start.sh` cycles boot with empty state and default clock; default-port (10000) boot responds.

**Interpretation decisions** where the PRD admitted multiple readings:

1. **IPS submit battery order** — PRD §3.2's explicit sequence (state → allocation-sum → risk → client-ACTIVE) was followed over the scaffold `validations[].priority` categories (which rank the 409 before the 422s), per the skill's PRD-wins rule. Same for amendment finalize (state → OCC → minute gates, per §2.7's explicit carve-out), minute ratify (DRAFT → SoD → refs, per §3.8), and trade release (BLOCKED → restricted → LISTED → proposal APPROVED, per §3.5 prose).
2. **`direction` enum for cash-movements** — the PRD names event kinds but never the request enum spellings; chose `DEPOSIT`/`WITHDRAWAL` (the prose's own words).
3. **`target_pct`/`band_pct` "exactly two decimal places"** — enforced as "at most 2dp" (reject `33.333` with 400), accepting `60` and `60.5`; stored as `Decimal`, serialized as JSON numbers.
4. **Reprice cascade touches only positions with `quantity > 0`** ("does not touch any held position changes only the security itself" — a zero-quantity row's value cannot change).
5. **Version starts at 1**; one mutation event = one increment even when a cascade changes several fields of the same resource.
6. **Void does not reverse `lifetime_realized_gains_cents`** — the PRD's exact-compensation clause names only `(quantity, cost_basis_cents, cash_balance_cents)`.
7. **Out-of-range `limit`/`offset`** (limit <1 or >100, offset <0) → 400 rather than clamping ("ranges enforced").
8. **Client role on list endpoints with an explicit foreign `client_id`/`portfolio_id` filter** → silently intersected to empty (force-scope), not 403; single-resource reads → 403. For `GET /clients/{id}` specifically, the ownership check fires before existence per priority 3 (path id vs `X-User-ID`).
9. **`PUT allocation-targets` response** — `response_type: "array"` without pagination meta (it returns a collection but declares no `limit`/`offset` inputs).
10. **`from`/`to` event filters** — accept full datetimes or `YYYY-MM-DD` dates (date-only `from` = day start, `to` = day end, inclusive), matching the PRD's "[from, to]" window notation.
11. **405 responses** are mapped to 404 `ERR_NOT_FOUND` (no catalog entry exists for wrong-method).

## Step 7: Run Tests and Iterate — 2026-08-14T20:45:00.000Z

Clean exit achieved. Final summary:

### Summary

**Iterations run: 2** (sweep 1: 111/126 in all 8 rounds, 15 unique failures, 0 flaky-only; sweep 2 after fixes: **126/126 in all 8 rounds**).

#### Tests deleted
None. No whole-test deletions were warranted; three *assertions* were removed under STEP 1c (partial coverage), and one test's foreign-filter assertion was removed under STEP 1b:

- `test_rbac_client_scoped_lists` (test_01) — removed the `ERR_NOT_RESOURCE_OWNER`-on-foreign-`client_id`-filter assertion. PRD §2.1's 403 ownership language covers resource access ("a `Client` reading its own record"), while every list-endpoint sentence states scoping semantics ("a `Client` sees only its own household's rows" §3.2/§3.4/§3.7). Two faithful readers diverge (403 vs silent-intersection-to-empty, Step 6 decision #8) → not uniquely derivable. Kept and mirrored the covered scoping assertions (c1 sees exactly its own portfolio; c2 sees none of c1's).
- `test_reprice_reverts_modeled_withdrawal` (test_04) and `test_reprice_reverts_modeled_withdrawal_to_submitted` (test_07) — removed `reverted["modeled_plan"] == []`. PRD §3.6 says revert is "clearing `modeled_plan`…" without pinning the cleared rendering (null vs []); `modeled_at is None` stays (verbatim: "null until the request reaches `MODELED`"). DEFAULT-VALUE SILENCE pattern.

#### Fixes to `test_helpers/`
- `assertions.py` — added `_parse_instant` + `assert_iso_instant_equal(actual, expected)`: compares parsed UTC instants, not strings. PRD pins the *instant* for clock-derived fields (§2.5 "read this clock", §3.2 month-addition) but pins three-fractional-digit *serialization* only for `api_request_timestamp`/`created_at`/`updated_at` (§2.2/§2.4), so exact-string assertions on `activated_at`/`next_review_due`/`generated_at`/`expires_at`/`current_utc` were not uniquely derivable (implementation emits `.000Z`, both renderings PRD-faithful).
- `__init__.py` — exported `assert_iso_instant_equal`.

#### Fixes to `test_suite/`
- test_01: `current_utc` assertion → instant comparison; `test_rbac_client_scoped_lists` reworked (above).
- test_03: 8 timestamp assertion sites across 4 tests → instant comparison.
- test_06: `generated_at`/`expires_at` in `test_proposal_ttl_expiry_at_checkpoint_boundary` → instant comparison.
- test_09: `next_review_due` in `test_finalize_cascade_applies_cadence_and_recomputes_due` → instant comparison.
- test_04 / test_07: removed non-derivable `modeled_plan == []` assertions (above).
- test_08: `test_benchmark_unique_name_and_default_description` — **test bug**: factory `create_benchmark_payload` injects `"description": "blend"` by default, so the omit path was never exercised (server correctly echoed "blend"). Test now pops the key before create; PRD §3.7 "defaults to empty" is covered verbatim. Return-variant fixture `_setup_perf_fixture` and `test_performance_flow_window_excludes_period_start_date` — **test bug**: recorded cash flows dated 08-11/08-21 against the default logical clock (08-01) without advancing it; implementation correctly rejected per §3.4 `ERR_EVENT_IN_FUTURE`. Fixtures now call `set_clock` first.

#### Fixes to `implementation/`
None required — the implementation was PRD-faithful in every failing case. (`test_execute_frozen_leaves_no_side_effects`'s connection-reset in sweep 1 did not reproduce in a logged solo run and passed all 8 rounds of sweep 2; consistent with host-level resource contention from orphan server processes, not a code defect.)

## Step 8: Finalize PRD — 2026-08-14T20:55:00.000Z

Done. `PRD_FINALIZED.md` written at `/home/ubuntu/github/CodingPRD/tasks/task_1818_investment_policy_statement_portfolio/workspace/PRD_FINALIZED.md`.

### Summary

**Line counts / delta:** PRD.md 384 lines (73,109 bytes) → PRD_FINALIZED.md 384 lines (74,214 bytes). Line delta 0.0% (all edits are intra-paragraph); byte delta +1,105 (+1.5%), +148 words. Four edit sites covering three subjects; every edit traces to a `<step_7_diff>` item. The two test_08 items were pure fixture bugs (impl PRD-faithful: `opt_str(b,"description","")` at routes_benchmarks.py:20 matches §3.7 "defaults to empty" verbatim; `ERR_EVENT_IN_FUTURE` per §3.4) — no PRD edit.

**Changes:**
- **§2.1 — insert** — Added sentence pinning that on the six Client-accessible collection list endpoints (portfolios, IPS records, positions, withdrawal requests, performance reports, cash-flow events) ownership is a visibility scope, not a rejection: query filters narrow within the scope, so a filter naming another household's id yields an empty page, never `ERR_NOT_RESOURCE_OWNER` — implementation/routes_portfolios.py:54-58, routes_ips.py:66-70, routes_positions.py:45-49+57-60, routes_withdrawals.py:64-68, routes_reports.py:61-65, routes_events.py:30-35.
- **§2.5 — insert** — Appended sentence pinning that every ISO 8601 UTC datetime the server emits (envelope `api_request_timestamp`, `created_at`/`updated_at`, all clock-derived fields, `next_review_due`, `occurred_at`, `effective_from`/`effective_to`, `current_utc`) serializes with exactly three fractional digits and `Z` suffix (`.000Z`) — implementation/logical_clock.py:17-24, envelope.py:9, serialize.py (all `fmt`/`fmt_or_none` sites), logic.py:38-39, routes_ops.py:40.
- **§3.6 — revise** — Generalized "null until the request reaches `MODELED`" from `modeled_at` alone to all six modeled fields — implementation/routes_withdrawals.py:51-53 (creation nulls all six).
- **§3.6 — insert** — Appended sentence pinning that clearing the model (staleness revert, rejection, or cancellation) resets each of `modeled_plan`, the three modeled totals, `post_withdrawal_drift_status`, `modeled_at` to null — implementation/logic.py:220-226 (`clear_model`), callers logic.py:212-217, routes_withdrawals.py:138-139/157-158.

**Pre-edit search logs:**

*Edit 1 (§2.1 list scope).* (a) Subject: Client-role ownership on collection lists vs specific-resource operations. (b) Enumerated: all six top-level Client-accessible list handlers (scope-then-filter, no 403 path — verified line-by-line); nested `list_targets` (routes_ips.py:131-141) which DOES 403 via `_client_owns` on the path-addressed parent; `list_clients` (no Client role); all single-resource getters and Client mutations (403). (c) Wording adjusted during drafting: explicitly enumerated the six collections rather than saying "list endpoints" universally, so the nested allocation-targets list (403 on foreign parent IPS) is not mis-described; existing §3.1/§3.2/§3.4/§3.7 scoping sentences left verbatim and remain consistent.

*Edit 2 (§2.5 serialization).* (a) Subject: wire format of server-emitted datetimes. (b) Enumerated via grep for `isoformat|strftime|clock.fmt|fmt_or_none` across all impl files: every datetime emission flows through `clock.fmt`/`fmt_or_none` (three fractional digits, `Z`); date-only fields `period_start`/`period_end`/`meeting_date` use date `.isoformat()`; validate.py:132 is input parsing, not emission. (c) Wording scoped to "datetime" so the `YYYY-MM-DD` date fields are excluded; the example `.000Z` rendering reconciles with §2.5 ¶1's instant notation `2026-08-01T00:00:00Z` (instant vs serialization).

*Edits 3a/3b (§3.6 modeled fields).* (a) Subject: null rendering of the six modeled fields pre-`MODELED` and after clearing. (b) Enumerated every path touching them: creation (routes_withdrawals.py:47-54, all None), modeling (logic2.py:258-263; CASH_FIRST yields `modeled_plan: []` — PRD's "the plan is empty" already pins that), `clear_model` (logic.py:220-226, all None) and all its callers — reprice (routes_securities.py:85), cash movement (routes_portfolios.py:180), position intake (routes_positions.py:41), execute/void/settle (logic2.py:173/195/332), reject/cancel (routes_withdrawals.py:139/158); settlement retains the model into `SETTLED` (no clear in `settle_withdrawal`). (c) Wording: 3a's "null until the request reaches `MODELED`" constrains only the pre-`MODELED` window, so `APPROVED`/`SETTLED` retention is not contradicted; 3b names all three clearing triggers so reject/cancel (same `clear_model`) inherit the null semantics; cross-references in §3.3/§3.4/§3.5 ("cleared"/"revert") inherit the definition without edit.

## Step 9: Complete PRD — 2026-08-14T21:10:00.000Z

The patch is complete. All 12 changed lines are exactly the planned in-place edits; no lines added or removed.

### Summary

**Files**: `/home/ubuntu/github/CodingPRD/tasks/task_1818_investment_policy_statement_portfolio/workspace/PRD_FINALIZED.md` (384 lines, 74,214 chars) → `PRD_COMPLETED.md` (384 lines, 75,396 chars; **+1,182 chars**, 12 lines revised in place, 0 lines added/removed).

**Counts**: 12 ambiguity-pins, 2 mismatch-revisions (across 12 edited lines — one line carries two pins, one carries a pin plus a revision).

**Method**: walked all 23 implementation modules (every route, state machine, formula, validation, cascade, serializer) against PRD prose. Most impl behavior was already uniquely pinned (envelope shape, validation-order batteries incl. the §2.7 finalize exception, drift/trade/waterfall math, withdrawal variants, Dietz/TWR returns, RBAC tables, cascades). Changes made:

- §2.3 — insert — ambiguity — list sort ties on identical `created_at` (common under the logical clock) keep creation/insertion order — store.py:23-26 (`_seq`), all list routes sort by `(created_dt, _seq)`
- §2.4 — insert — ambiguity — `version` starts at 1 on creation (PRD previously only specified increments) — logic.py:44-47
- §2.6 — revise — ambiguity — half-up bps rounding pins ties away from zero, so negative exact halves (possible in `portfolio_return_bps`) round further negative — logic.py:50-55, logic2.py:356,369
- §2.7 item 4 — revise — ambiguity — datetime inputs must carry an explicit UTC offset (`Z`/`±hh:mm`) and are normalized to UTC — validate.py:124-137
- §3.2 — revise — ambiguity — `next_review_due`, like `activated_at`, is null until the IPS first reaches `ACTIVE` — routes_ips.py:54, serialize.py:41
- §3.3 — revise — ambiguity — ticker must be non-empty, letters/digits/dots only — routes_securities.py:16,25-27
- §3.3 — revise — ambiguity — reprice cascade touches only positions with more than zero units ("holding") — routes_securities.py:79-85
- §3.4 — revise — ambiguity — cash-movement `direction` enum pinned to `DEPOSIT` | `WITHDRAWAL` (PRD never named the values) — routes_portfolios.py:162
- §3.4 — revise — ambiguity — event-list `from`/`to` window: both bounds inclusive; bare `YYYY-MM-DD` dates bind the whole UTC day — routes_events.py:15-22,39-46
- §3.5 — revise — ambiguity — a `BUY` fill into a security the portfolio does not hold opens the lot at zero units/zero basis first (compositionally yields version 2 for such positions) — logic2.py:142-146
- §3.5 — revise — ambiguity — checkpoint reports `expired_proposal_ids` in proposal creation order — routes_ops.py:21-26
- §3.5 — revise — mismatch — the "same `EXPIRED` fate" sentence split: pin-loss (supersession/archival) expires non-terminal proposals including `APPROVED`, while a newer generation expires only `PROPOSED`/`NEEDS_REVISION` — logic.py:251-256 vs routes_proposals.py:58-61 (`OPEN_PROPOSAL_STATES`)
- §2.11 — revise — mismatch — "generation supersedes earlier non-terminal proposals" corrected to `PROPOSED`/`NEEDS_REVISION` only; an `APPROVED` proposal survives generation and leaves `APPROVED` only via execution, TTL expiry, or the pin cascade — routes_proposals.py:58-61, logic.py:20
- §3.7 — insert — ambiguity — `portfolio_return_bps` and `excess_return_bps` remain null until finalization — routes_reports.py:48-49

The two mismatch revisions resolve a genuine internal PRD contradiction (§3.5 Generation paragraph + impl expire only `PROPOSED`/`NEEDS_REVISION` on generation; §2.11 and §3.5's final paragraph said "non-terminal", which includes `APPROVED`) in favor of the implementation.
