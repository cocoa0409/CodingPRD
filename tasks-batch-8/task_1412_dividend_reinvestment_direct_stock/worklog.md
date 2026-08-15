# Worklog — task_1412_dividend_reinvestment_direct_stock

## Step 1: Create Task Directory — 2026-08-13T05:57:55.674Z

Task directory `tasks/task_1412_dividend_reinvestment_direct_stock/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher; treated as DONE per instructions (no index scan, no other task_* writes).

## Step 2: Generate Scaffold — 2026-08-13T05:57:55.674Z

All three scaffold artifacts generated and lint-clean for task_1412_dividend_reinvestment_direct_stock.

**Files written**
- `/home/ubuntu/github/CodingPRD/tasks/task_1412_dividend_reinvestment_direct_stock/SCAFFOLD.yaml` (§1.0–§1.7 only — no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1412_dividend_reinvestment_direct_stock/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single `scaffold_difficulty_design:` key)
- `/home/ubuntu/github/CodingPRD/tasks/task_1412_dividend_reinvestment_direct_stock/SCAFFOLD_CORNER_DESIGN.yaml` (single `scaffold_corner_design:` key)

**Counts**
- Entities: 11 (Plan, Participant, Enrollment, DividendEvent, PurchaseWindow, PurchaseOrder, ShareLedgerEntry [common_fields: false, immutable event log], TaxLot, FeeAssessment, PlanNotice, TransferInstruction) — flat topology with FK links, per the diversity guidance to avoid hybrid
- State machines: 7 (Plan and Enrollment are cyclic ACTIVE↔SUSPENDED; DividendEvent, PurchaseWindow, PurchaseOrder, PlanNotice, TransferInstruction)
- Calculations: 6 (reinvestment_allocation, dividend_cash_split, disposition_basis_relief, ocp_fee_assessment, window_purchase_limit, termination_settlement)
- Endpoints: 50 (incl. `POST /drip/_clock/set_current_utc` with the mandated 2026-08-01T00:00:00Z default)
- Errors: 21; Validations: 19 (priority-ordered); Roles: 2 (PlanAdmin opaque, Participant entity_backed); OCC concurrency rules: 2
- Difficulty-design instances: 18 (all 9 rules × 2, each with structured replayable setup chains and pre-computed literal asserts)
- Corner-design instances: 47 total (40 active + 7 `excluded_because:` stubs)

**Notable design decisions**
- Dual variants sit in genuinely different domains: reinvestment pricing (MARKET_CLOSE vs FIVE_DAY_AVERAGE on DividendEvent) vs cost-basis relief (FIFO vs AVERAGE_COST on TaxLot). Verified literals: 2.6316 vs 2.5063 shares; gain 6000 vs 4000 cents.
- Combinatorial formulas in two different modes: pinned nested rounding (price rounded to integer cents before share division — 2.6330 vs 2.6329 divergence) and the max(floor, amount×pct) + waiver-branch OCP fee.
- Two transitive cascades with distinct triggers: plan suspension (Plan→Enrollment→PurchaseOrder→window submitted_total_cents, depth 3, deliberately asymmetric resume — REJECTED orders are not restored) and enrollment termination (terminate→FRACTIONAL_SALE entry→TaxLot relief + SALE fee, depth 2).
- Temporal overlap with two interval semantics: half-open `[opens_at, closes_at)` window-window adjacency (touching allowed) vs closed-with-buffer dividend blackout `[record_date−2d, payable_date]` (touching rejected).
- Compensating invariants over different conserved quantities: plan share supply under TRANSFER (25.0000 == 25.0000) and cost-basis cents under disposition (remaining 26000 + realized 4000 == 30000).
- Every numeric assert was computed by executing the formulas (Decimal, round_half_up) before writing; lint verdict: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (458 calls scanned); forbidden-vocabulary grep is clean; instance names unique across both design files.

One repair worth noting: the lint's FK reverse-reachability check requires sub-resource GETs to use the literal `{id}` parent segment, so those paths were renamed (e.g. `/drip/plans/{id}/enrollments`); call sites were unaffected since they use `${var}` placeholders.

## Step 3: Copy Shared Files — 2026-08-13T05:58:10.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1412_dividend_reinvestment_direct_stock/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-13T06:13:00.000Z

All audits pass. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1412_dividend_reinvestment_direct_stock/workspace/PRD.md`.

## Summary

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1412_dividend_reinvestment_direct_stock/workspace/PRD.md` — 6,253 words. The forbidden `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were not opened or referenced.

### Section list
- **1. Introduction** (2 paragraphs: business context + system scope)
- **2. Global Specifications** — 2.1 RBAC (header contract, both role identity translations), 2.2 API Response Structure (verbatim block), 2.3 Pagination, 2.4 The Logical Clock, 2.5 Money/Shares/Rounding Discipline (three pinned rounding orders), 2.6 Common Resource Properties (incl. ShareLedgerEntry's absent `updated_at`/`version`), 2.7 OCC (both rules with exact error ids), 2.8 Plan Status Gating & Nested Resolution, 2.9 Share Ledger & Tax-Lot Books, 2.10 Fee Assessment & Waiver, 2.11 Validation Order (nine tiers, masking semantics)
- **3. Business Logic** — 9 subsections: plan drafting/publishing/modification; participants/enrollment/elections; initial deposits & position reporting; dividend processing (declare→price→execute→settle); OCP windows/orders/settlement; fees & admin waiver; notices/suspension/resumption; transfers & gifts; termination settlement/basis relief/tax reporting
- **4. Endpoint Definitions** — 50-row table (4 columns only)
- **5. Error Code Catalogue** — 21-row table (2 columns only)

### Coverage audit
- **Contract 1 (fields)**: 88/88 required identifiers present in backticks, 0 missing (two repair passes: added `plan_id`, then clean)
- **Contract 2 (rules)**: all 7 state machines' transitions with preconditions+side effects; all 6 calculations as precise prose (variants, constants, pinned rounding orders, boundaries like frac==0.0000 and equality-on-ceiling); all 17 validation rules matched to their error ids with applies_to scopes enumerated (9 plan-gated endpoints, 4 enrollment-gated ops, 2 window-gated ops); both OCC rules with endpoint+field+error+412; validation priority tiers stated explicitly; sibling branches (3 elections, 2 pricing bases, 2 basis methods, TRANSFER/GIFT, 3 notice types) at equal density
- **Contract 3 (§3 path purity)**: 134 unique backtick tokens scanned — 0 paths, 0 bare HTTP methods, 0 method+path tokens
- All 46 enum/state values present (one repair: `EXECUTED`); all 21 error ids appear in §2/§3 prose; no fuzzy/approximating words; §2.2 emitted byte-verbatim

### Ambiguities resolved
1. **Auto-waiver scope** — `fee_waiver_eligible` description says OCP-only while `FeeAssessment.waived` reads generally; resolved to automatic waiver for OCP only, administrative waiver (with `reason`) as the sole path for ENROLLMENT/SALE/TRANSFER fees, consistent with the termination formula's "waivable by admin only".
2. **Provenance tag bindings** — scaffold lists `source_type` vocabularies without explicit per-event binding; bound tags via state-machine side effects (ACTIVATION/WINDOW/TERMINATION/TRANSFER for fees; DEPOSIT/DIVIDEND/WINDOW/TERMINATION/TRANSFER for ledger entries).
3. **OCC placement** — Contract 3 bars paths from §3, so the two OCC rules are fully named (method+path, field, error id, 412) in §2.7; §3 cross-references by capability.
4. **Intra-tier ordering** — equal-priority validations (the four priority-5 state gates, three priority-6 temporal checks) are presented as unordered within their tier; only the nine-tier ordering is asserted.
5. **Tax report fidelity** — scaffold describes the report only as "dividends declared, disposition proceeds/basis/gain"; expressed at exactly that depth plus the gain formula from `disposition_basis_relief`, without inventing aggregation mechanics.

## Step 5: Generate Unit Tests — 2026-08-13T06:47:00.000Z

All 76 tests collect cleanly. The work is complete.

## Summary

**Task**: `task_1412_dividend_reinvestment_direct_stock` — full test infrastructure generated from the two design indices under the PRD-first rule.

### Tests emitted: 76 total

**Queue A (Difficulty) — 36 tests, 2 per instance, all 18 instances covered:**
- `dual_variant_calc`: reinvestment pricing basis (MARKET_CLOSE 1900 vs FIVE_DAY_AVERAGE 1995, shares 2.6316 vs 2.5063) and basis relief (FIFO gain 6000 vs AVERAGE_COST gain 4000)
- `combinatorial_formula`: nested rounding pinned (price 1899 → 2.6330, not 2.6329) and OCP fee max/floor/waiver (4.5600 / 3.4000 / 4.8000 settled shares)
- `non_linear_state_machine`: plan and enrollment suspend/resume cycles (two loops each)
- `transitive_cascade`: plan-suspend depth-3 cascade (enrollment → order → window total 12000→0) and termination depth-2 cascade (FRACTIONAL_SALE −0.5 @2000 net 750, lots→0, SALE fee 250)
- `priority_pair_validation_conflict`: state-gate-masks-fiscal and schedule-sanity-masks-overlap, each paired with an isolated-control test proving the masked error fires alone
- `boundary_precision_check`: cumulative ceiling exact-hit accepted / strict overshoot rejected (+ cancel-releases-reservation), and zero-fractional termination skipping sale entry and fee
- `cross_entity_state_dependency`: enrollment activate under SUSPENDED plan (+ DRAFT-plan enroll control), order submit to SCHEDULED window (+ OPEN-window control)
- `resource_temporal_overlap`: half-open window adjacency allowed / overlap rejected; closed blackout boundary touch rejected / clear window accepted (+ strictly-inside case)
- `compensating_invariant`: transfer share-supply conservation (12.5/12.5, supply 25) with TRANSFER_IN carryover lot @1000; cost-basis conservation (30000 → 26000 remaining + 4000 realized)

**Queue B (Corner) — 40 tests, 1 per non-stub instance, all 40 covered.** The 7 `excluded_because` stubs were not translated; all cross-references verified to resolve to real difficulty instances.

**Instances skipped**: none — every non-stub instance passed the PRD two-condition filter.

### Helper files created (`test_helpers/`)
`__init__.py` (barrel), `types.py` (15 enums + 11 TypedDicts; `ShareLedgerEntry` correctly omits `updated_at`/`version`), `api_client.py` (45 endpoint methods incl. logical clock), `api_errors.py` (21 errors registered with the framework), `assertions.py` (per-entity asserts + `assert_shares_equal` Decimal-based 4dp comparator), `factories.py`, `constants.py`, `test_users.py` (`make_participant_headers` builder for the entity-backed Participant role, `NO_AUTH_HEADERS`), `fixtures.py` (5-tier composites: plan/enrollment/window/dividend/transfer chains), plus `test_suite/conftest.py` and 6 test files.

### Notable design decisions
- **Version-literal divergence adjudicated PRD-first**: the difficulty instance `plan_suspend_resume_cycle` pre-computed `version == 5`, but PRD arithmetic (create → +1 per mutation, per §2.6/§3.1) yields 6, and the PRD never pins the initial version. Tests therefore assert the PRD-derivable rule — version increments by exactly 1 per transition relative to the observed publish version — instead of the absolute literal. Same treatment for OCC tests (assert `observed + 1` rather than literal 3). Corner instances asserting `version == 1` at create kept only the PRD-derivable default/status assertions.
- **Share quantities** are compared via `Decimal(str(x))` equality so tests pass whether the implementation serializes 4dp quantities as JSON numbers or strings, while still catching rounding drift.
- **No freelance tests**: every test carries exactly one terminal `Design:` line; an automated pass verified all 76 docstring citations are whitespace-normalized verbatim substrings of PRD.md, all tags resolve, and coverage minimums hold (verified via `/tmp/verify_1412.py`, 0 errors).
- All files byte-compile, `test_helpers` imports against the real framework, and `pytest --collect-only` collects 76 tests.

## Step 6: Generate Implementation — 2026-08-13T06:47:30.000Z

Implementation complete and verified. Summary:

## File list
All under `/home/ubuntu/github/CodingPRD/tasks/task_1412_dividend_reinvestment_direct_stock/workspace/implementation/`:

- `start.sh` — foreground launcher; guarded `pip install` (no-op when Flask is present), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — `flask`
- `app.py` — Flask entry point, error handlers (ApiError → envelope; 404/405 → `ERR_NOT_FOUND`)
- `db.py` — in-memory store (11 entity dicts + internal disposition/dividend-income lists), logical clock (default exactly `2026-08-01T00:00:00Z`), UUID/sequence/timestamp helpers
- `errors.py`, `response.py`, `middleware.py`, `util.py` — error type, envelope helpers (`meta`/`response_type`/`data`, pagination fields `limit`/`offset`/`total_count`/`has_more`), `X-User-ID`/`X-User-Role` auth + ownership checks, parsing/Decimal rounding/pagination
- `services.py` — serializers, derived-field recompute, FIFO/AVERAGE_COST basis-relief engine, termination settlement, plan suspend/resume/terminate cascades, dividend execution, OCP window settlement, transfer execution, tax report
- `routes/` — 10 modules: plans, participants, enrollments, dividends, windows, orders, notices, transfers, fees, clock

## Endpoint count
50 route handlers — the full scaffold §1.5 endpoint table (49 resource endpoints + `POST /drip/_clock/set_current_utc`).

## State storage
In-memory only, via module-level dicts in `db.py`. **No seeding** — every store starts empty at boot (verified: fresh boot returns `total_count: 0`). All Decimal/share state is recomputed per process; nothing persists across restarts, satisfying per-test-server isolation.

## Notable implementation decisions
- **Logical clock for entity timestamps**: `created_at`/`updated_at`/`acquired_at`/`published_at`/`executed_at`/`terminated_at` all use the logical clock (required for record-date eligibility to be testable); only the envelope's `api_request_timestamp` uses wall clock (matches PRD §2.2 example).
- **Version bumps only where the scaffold states them**: derived-field reconciliations (`share_balance`, `total_cost_basis_cents`, `submitted_total_cents`) never bump `version`; TaxLot relief does bump (stored-field mutation). Ledger entries carry only `id`/`created_at`.
- **Pinned rounding orders** implemented literally with `Decimal` ROUND_HALF_UP: reinvestment price rounded to cents before share division; PARTIAL split rounds the reinvested portion first (cash takes residue); fractional sale rounds gross before fee subtraction.
- **FIFO relief** uses total-basis minus already-relieved for fully consumed lots (anti-drift); **AVERAGE_COST** computes the weighted average once, relieves pro-rata with the oldest lot absorbing 4dp residue. Termination relieves fractional part first (recorded as the disposition), then whole — mathematically identical to a single full relief under both methods.
- **Underspecified error mappings** (no catalog entry exists): dividend-execute before `payable_date`, window close before `closes_at`, notice take-effect before `effective_at`, and SUSPENSION/TERMINATION notice guards → `ERR_INVALID_STATE` (409); source enrollment not ACTIVE at transfer execute → `ERR_ENROLLMENT_NOT_ACTIVE`; duplicate participant email → `ERR_VALIDATION` (400).
- **Validation ordering** follows the scaffold priority table: auth → RBAC/ownership → path existence (left-to-right) → body shape (400) → OCC (412) → state gates (409) → temporal (422) → business constraints → fiscal → referential recipient checks.
- **Plan-level terminate** accepts an optional `sale_price_cents` body (default 0) since the endpoint declares no input but cascades the full enrollment termination; plan termination also terminates PENDING enrollments ("every non-terminal") while the direct endpoint still requires ACTIVE/SUSPENDED.

Verified with two ad-hoc suites (≈115 checks) covering the full lifecycle: plan/participant/enrollment CRUD + RBAC + ownership, OCC (412s), election rules, deposit, dividend declare/price/execute/settle under both pricing bases, record-date eligibility, window schedule/blackout/overlap/adjacency, OCP min + cumulative limit boundary (equality allowed), fee floor + `AUTO_ELIGIBLE` waiver, admin waiver, suspension cascade (orders → REJECTED, asymmetric resume), transfers/gifts with carryover basis, termination frac==0 boundary, plan-termination cascade with fractional-sale net proceeds, per-year tax report (FIFO and AVERAGE_COST figures), notice lead-time/take-effect flows, pagination, and clean fresh-boot state.

## Step 7: Run Tests and Iterate — 2026-08-13T06:52:00.000Z

## Summary

- **Iterations run**: 1 (single 8-round parallel sweep; no fixes needed).
- **Sweep result**: all 8 rounds passed 76/76 tests (`results.1.json` through `results.8.json` at `/home/ubuntu/github/CodingPRD/tasks/task_1412_dividend_reinvestment_direct_stock/workspace/implementation/`).
- **Tests deleted**: none.
- **Fixes applied to `test_helpers/`**: none.
- **Fixes applied to `implementation/`**: none.

The pre-existing implementation and test suite for task_1412_dividend_reinvestment_direct_stock were already mutually consistent and stable under the 8-round concurrent per-test-server sweep — no timing-sensitive failures, no port collisions, no flaky rounds. The loop exits clean on iteration 1.

(Orchestrator verification: all 8 `results.*.json` files confirmed `passed == total == 76`.)

## Step 8: Finalize PRD — 2026-08-13T06:52:30.000Z

SKIPPED per the skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the implementation exhibits, so no `PRD_FINALIZED.md` was produced.

## Step 9: Complete PRD — 2026-08-13T07:10:00.000Z

PRD_COMPLETED.md is written and verified. Final summary:

**Source vs output**: `workspace/PRD.md` (no PRD_FINALIZED.md existed) 277 lines / 44,405 chars → `workspace/PRD_COMPLETED.md` 279 lines / 49,762 chars; char-delta **+5,302** (23 in-place hunks; one hunk is a 2-line paragraph insert in §2.11, everything else is inline insert/revise; no new sections).

**Counts**: 26 ambiguity-pins, 3 mismatch-revisions.

**Ambiguity-pins (insert)**:
- §2.3 — insert — ambiguity — list tie-break by insertion order under a stationary clock; non-integer/out-of-range `limit`/`offset` and non-enum filter values → `ERR_VALIDATION` 400; `total_count` is the pre-pagination filtered count; `has_more` ⟺ `offset+limit < total_count` — services.py:69-92, util.py:124-146, response.py:24-31
- §2.4 — insert — ambiguity — all persisted timestamps (`created_at`, `updated_at`, `acquired_at`, `published_at`, `executed_at`, `terminated_at`) read from the logical clock; `api_request_timestamp` is the sole wall-clock reading; clock set has no monotonicity check — db.py:41-57, response.py:12-16, routes/clock.py:12-18
- §2.6 — insert — ambiguity — `version` starts at 1 on creation; recomputing `share_balance`/`total_cost_basis_cents`/`submitted_total_cents` is not a mutation (no `updated_at` refresh, no version bump) — services.py:48-66, 413-441
- §2.9 — insert — ambiguity — ledger `source_id` for `DEPOSIT`/`TERMINATION` provenance is the owning enrollment's id — routes/enrollments.py:197, services.py:585-596
- §2.9 — insert — ambiguity — exact `total_cost_basis_cents` rule: lots with shares remaining in creation order; all but last contribute round(remaining×cps); last contributes recorded `total_basis_cents` minus already-relieved basis — services.py:413-432
- §2.10 — insert — ambiguity — fee `source_id` per provenance (ACTIVATION/TERMINATION → enrollment id; WINDOW → order id; TRANSFER → instruction id) — routes/enrollments.py:127-130, services.py:589,722-728,773-776
- §2.11 — insert — ambiguity — OCC check (412) sits between body-shape validation and state gates — routes/plans.py:147-161, routes/enrollments.py:141-157
- §3.1 — insert — ambiguity — plan field ranges: `discount_pct` ∈ [0,1), `ocp_fee_pct` ≥ 0, `_cents` fields non-negative integers, all `ERR_VALIDATION` 400 — routes/plans.py:53-80
- §3.1 — insert — ambiguity — auto-created MODIFICATION notice: `effective_at` = logical clock + 10 days, fixed placeholder message — services.py:790-803
- §3.1 — insert — ambiguity — plan termination accepts optional `sale_price_cents`, non-negative, default 0 — routes/plans.py:209-213
- §3.2 — insert — ambiguity — duplicate email → `ERR_VALIDATION` 400 — routes/participants.py:29-33
- §3.2 — insert — ambiguity — new enrollment starts PENDING with `share_balance` 0.0000 and `total_cost_basis_cents` 0 — routes/enrollments.py:82-95
- §3.3 — insert — ambiguity — INITIAL lot `total_basis_cents` = round4-quantity × cost, half-up to cents — routes/enrollments.py:198-200
- §3.4 — insert — ambiguity — execute before `payable_date` → `ERR_INVALID_STATE` 409 — routes/dividends.py:103-106
- §3.4 — insert — ambiguity — zero-sized portion writes nothing (no CASH_PAYOUT under FULL_REINVEST; no REINVEST entry/lot under CASH_ONLY) — services.py:681-698
- §3.5 — insert — ambiguity — close before `closes_at` → `ERR_INVALID_STATE` 409 — routes/windows.py:153-156
- §3.5 — insert — ambiguity — OCP lot `total_basis_cents` = fee-net amount (`amount_cents − charged_cents`) — services.py:740-743
- §3.6 — insert — ambiguity — waiver is not state-guarded; re-waiving overwrites `waived_reason` — routes/fees.py:12-22
- §3.7 — insert — ambiguity — take-effect before `effective_at` → `ERR_INVALID_STATE` 409 — routes/notices.py:95-98
- §3.7 — insert — ambiguity — TERMINATION-notice cascade settles fractional shares at sale price 0 — routes/notices.py:110
- §3.8 — insert — ambiguity — counterpart payload violations (incl. empty/non-string GIFT name/address) → `ERR_RECIPIENT_NOT_ENROLLED` 422, not `ERR_VALIDATION` — routes/transfers.py:56-91
- §3.8 — insert — ambiguity — TRANSFER_IN entry `price_cents` = FMV; lot `cost_per_share_cents` = round(relieved basis ÷ quantity), `total_basis_cents` = total relieved basis — services.py:764-771
- §3.9 — insert — ambiguity — enrollment termination requires a strictly positive integer `sale_price_cents` — routes/enrollments.py:171-173
- §3.9 — insert — ambiguity — tax report `year` is a required integer query param, else `ERR_VALIDATION` 400 — routes/enrollments.py:261-267
- §3.9 — insert — ambiguity — `dividends_cents` = full executed dividend cash (reinvested + payout) keyed by `payable_date` year; unexecuted declarations contribute nothing — services.py:534-541,700
- §3.9 — insert — ambiguity — dispositions attributed to the logical-clock execution year; at termination only the fractional sale is reportable (whole-share withdrawal yields no entry) — services.py:522-531,590-591

**Mismatch-revisions (revise)**:
- §2.11 — revise — mismatch — the strict "authz before not-found before body shape" tier claim now carries explicit exceptions: stored-resource ownership requires loading the resource first (404 precedes 403 on enrollment-scoped access; only participant-record endpoints, keyed by the path id, 403 first), and enrollment creation validates payload shape before the self-enrollment 403 and participant-existence 404 — routes/enrollments.py:56-67,109-114 vs routes/participants.py:45-50
- §3.4 — revise — mismatch — record-date eligibility boundary "23:59:59 UTC" → end of day 23:59:59.999 UTC (impl admits entries up to 23:59:59.999999) — services.py:651-656
- §3.5 — revise — mismatch — dividend blackout end "23:59:59 UTC" → 23:59:59.999 UTC — routes/windows.py:37-42

Everything else in the PRD (rounding orders, election rules, blackout/overlap geometry, OCC contracts, fee formulas, FIFO/AVERAGE_COST relief, suspension/resume cascades, state-gate catalog, endpoint table, error catalog) was verified against the implementation and already pinned uniquely — left untouched.
