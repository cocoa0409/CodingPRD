# Worklog — task_0317_consignment_thrift_resale

Scenario: Consignment & Thrift Clothing Resale: consignor agreement & intake/grading, pricing & markdown schedule, split percentage & payout, unsold return/donation, tag & inventory aging, store credit, daily settlement, item authentication

## Step 1: Create task directory — 2026-06-13T00:00:00.000Z

Created `tasks/task_0317_consignment_thrift_resale/` and `workspace/` subdirectory (pre-assigned index, auto-scan skipped per orchestration args). Verified `./INSTRUCTION.md` and all six prd-bench skills present.

## Step 2: Generate scaffold (Expert band) — 2026-06-13T00:05:00.000Z

All three files written and the lint is clean (exit 0). The scaffold is complete.

Generated all three scaffold artifacts for **task_0317_consignment_thrift_resale** at the **Expert** difficulty band. `scaffold_lint.py` returns `VERDICT: clean lint` (exit 0).

**Files written**:
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`, §1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`, §1.9)

**Complexity profile**: primary archetype *pricing engine* blended with *compliance/audit*; flat entity topology; parallel state-machine shape; segregation-of-duties role model; immediate consistency. Layers: dual-variant calculation, rate/threshold triggers, cascading side effects, derived-field reconciliation, optimistic concurrency, scheduled/deferred actions.

**Entities (12)**: Consignor, MarkdownSchedule, ConsignorAgreement, IntakeBatch, Item, AuthenticationReview, Sale, SaleLine, PayoutLedgerEntry, StoreCreditTransaction, DailySettlement, DonationRecord.

**State machines (5 entries)**: Item carries **two parallel dimensions** (grading: PENDING_GRADE→ACCEPTED/REJECTED; listing: NOT_LISTED↔ON_FLOOR↔PULLED→SOLD/RETURNED/DONATED); AuthenticationReview is **cyclic** (IN_REVIEW↔DISPUTED with dispute_round increments); DailySettlement and Sale are **branching** (OPEN→{FINALIZED,VOIDED}; COMPLETED→VOIDED). Plus 2 concurrency rules (OCC on DailySettlement.version and Item.version).

**Key calculations (6)**: markdown_price (step-function tiered by age, floored), split_base (GROSS vs NET dual-variant), consignor_proceeds (round-half-up split + cash/store-credit divergence), store_credit_payout (non-linear tiered bonus), donation_valuation, settlement_rollup (round-per-line-then-sum order pinned).

**Validation/error counts**: 20 ordered validations; **24 error codes** (within the 18–30 Expert band); every error is triggerable.

**Endpoints**: 51 (core business + state-transition surface plus the FK reverse-reachability GETs mandated by lint check (f); the band's 20–32 is a guideline, surplus is entirely read-only discovery endpoints required for testability).

**Roles (5)**: StoreAdmin, IntakeGrader, Authenticator, CashierClerk, SettlementManager (all `opaque`; SoD enforced — an Authenticator may not authenticate an item they graded).

**Test design**: §1.8 has all **9 Difficulty Rules × 2 instances = 18**, each grounded with formula-derived asserts pre-computed as literals. §1.9 has **34 active corner instances + 3 excluded_because stubs** across 8 sections. Cross-checks passed: zero unresolvable grounds, zero forbidden concurrency vocabulary, all OCC payloads use `${var}`, no duplicate names across the §1.8∪§1.9 union, all time arithmetic verified exact (90/30/60/10/200-day boundaries).

Design fix: removed a dead `ERR_DATE_ALREADY_FINALIZED` error and two unreachable enum values (`ADJUSTMENT`, `EXPIRE`); reworked the store-credit void to flip the originating ISSUE transaction to VOID status.

## Step 3: Copy INSTRUCTION.md — 2026-06-13T00:06:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0317_consignment_thrift_resale/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-13T00:10:00.000Z

**Output:** `workspace/PRD.md` (281 lines). All three Hard Contracts pass (Field coverage PASS, Rule coverage PASS, Path purity PASS). Withheld design YAMLs not opened.

**Domain:** Consignment & Thrift Clothing Resale API — pricing-engine + compliance-audit system covering consignor onboarding, intake/grading, authentication, markdown pricing, sale splits, dual payout channels (cash ledger vs store credit with bonus), sale void compensation, unsold disposition, daily settlement.

**Structure:** §1 Introduction; §2 Global Specs (10 subsections: RBAC, response structure, pagination, common props/versioning, nested retrieval & validation-precedence, monetary precision/rounding, derived balance reconciliation, OCC, hierarchical consistency/cascades, the aging clock); §3 Business Logic (9 lifecycle subsections); §4 Endpoint table (51); §5 Error catalogue (24).

**Documented coverage:** 13 entities / 57 fields; 51 endpoints / 36 input identifiers; 6 calculations (markdown_price, split_base, consignor_proceeds, store_credit_payout, donation_valuation, settlement_rollup) with constants embedded (86400; 150; 2000/10000 bonus thresholds at 10%/20%; 25% donation valuation; 30% default floor); 5 state machines; 24 errors; 2 OCC rules (412 ERR_STALE_ITEM_VERSION / ERR_STALE_SETTLEMENT_VERSION); 5 roles (StoreAdmin, IntakeGrader, Authenticator, CashierClerk, SettlementManager).

## Step 5: Generate unit tests — 2026-06-13T03:20:00.000Z

**test_helpers/** (9 files): types.py, api_client.py (1 method/endpoint), api_errors.py (24 error→HTTP map, registered), assertions.py (per-entity + append-only-vs-mutable common-field checks), factories.py (input-only payloads), constants.py (bonus/fee/floor/valuation literals), test_users.py (5 opaque-role shared headers + per-role builders for SoD operator-id pinning), fixtures.py (clock + on-floor/sold/auth-review/settlement composite setups), __init__.py barrel.

**test_suite/** (8 files): conftest.py + test_01..test_07. **68 tests** emitted: 34 from queue A (difficulty), 34 from queue B (corner).

**Coverage audit:** all 34 non-stub corner instances ≥1 test; 17/18 difficulty instances ≥2 tests; 3 corner stubs correctly not translated (all cross-refs resolve); every Design tag resolves to a real non-stub instance; all 75 quoted PRD citations survive a verbatim grep of PRD.md; no skip/xfail; no scaffold-label leakage.

**One difficulty instance SKIPPED:** `priority_pair_validation_conflict/business_temporal_vs_business_constraint_window_vs_price` — fails unique-derivability. PRD §2.5 groups "on-floor and pricing constraints" in a single tier with no stated internal order between ERR_ITEM_NOT_ON_FLOOR and ERR_PRICE_BELOW_FLOOR; the priority numbers (9 vs 13) are scaffold-only (validation-priority / error-precedence silence pattern). A PRD-only implementer could surface either error, so no test can hard-code the loser. The dependent corner stub `error_price_below_floor_already_covered_stub` consequently leaves ERR_PRICE_BELOW_FLOOR's trigger genuinely untested — an upstream PRD gap, not papered over.

**Initial version not pinned:** PRD §2.4 says version "begins at its initial value" without naming 1, so the literal `version==1` / `version==2` sub-assertions from two corner instances were omitted (default-value silence pattern); the increment is asserted relatively via assert_version_incremented, and the other PRD-covered defaults (status, zeroed balances, grading_status) are kept.

## Step 6: Generate implementation — 2026-06-13T03:25:00.000Z

Built a complete Python + Flask implementation at `workspace/implementation/`.

**Files written:** `start.sh` (reads `$PORT` default 10000, binds `0.0.0.0`, foreground via `exec`, guarded pip install), `requirements.txt` (flask>=2.0), `app.py` (entry, blueprint registration, error handlers, threaded=True), `db.py` (in-memory `Store` dicts + drivable logical `Clock`, single module-level instance, no seeding), `errors.py` (`ApiError` + 24-entry error→HTTP catalogue), `response.py` (exact envelope, req_ ids, 3-digit ISO timestamps, pagination meta), `middleware.py` (X-User-ID/X-User-Role auth + RBAC decorator), `routes/` (9 blueprints: consignors, schedules, agreements, batches, items, reviews, sales, settlements, misc), `services/` (common.py validation/pagination/timestamps, calc.py Decimal money math, serialize.py output + derived-balance reconciliation).

**Structure:** Layered routes → services → db. Money uses `decimal.Decimal` with explicit half-up rounding and floor; store_share computed by subtraction (absorbs remainder); settlement rollup round-per-line-then-sum.

**Endpoints:** 49 PRD endpoints all implemented (51 handler functions). Covers all state machines (item grading/listing parallel dims, cyclic auth review, branching settlement/sale), markdown step-function pricing with aging clock, GROSS/NET split bases, CASH vs STORE_CREDIT payout with tiered bonus, void compensation netting to zero, donation valuation, both OCC fields, SoD, validation precedence (auth → role → path-existence → body-FK → state → OCC → business rules).

**start.sh confirmation:** Reads `$PORT` (default 10000), binds `0.0.0.0`, runs `exec python3 app.py` foreground. Verified fresh boot = empty store; kill+relaunch wipes all state; install guard skips pip on warm boots (~2.5s restart). All 5 smoke-test suites pass.

## Step 7: Run tests and iterate — 2026-06-13T03:35:00.000Z

All 8 parallel rounds pass cleanly with 68/68 tests each. The loop is complete.

**Iterations run:** 2 (1 baseline sweep, 1 verification sweep after the fix).

**Diagnosis:** The baseline 8-round sweep showed exactly 2 stable failures (identical across all 8 rounds), both in `test_06_settlement.py`, both with `NameError: name 'api' is not defined`:
- `test_settlement_payable_round_per_line_then_sum`
- `test_settlement_total_gross_sums_line_prices`

Root cause: both tests call a module-level helper `_setup_two_net_lines_sold(business_date, clock_iso, email)` whose body referenced the bare name `api`. In this suite `api` is a pytest fixture injected only into test functions (conftest.py just returns `api_client`); it is not in scope inside a plain module-level helper. The other test functions in the file work because they receive `api` as a parameter.

This was a **TEST BUG** (STEP 2 — test-suite mistranslation), not an implementation bug. The two assertions themselves are faithful to PRD §3.9 and the expected values are correct (NET base 8001−150=7851; round_half_up(7851×0.5)=3926; ×2 = 7852 payable; gross 8001+8001=16002), and the PRD-faithful implementation already computes them correctly.

**Fixes applied to test_suite/** (`test_helpers/` untouched, `implementation/` untouched):
- `test_suite/test_06_settlement.py`, helper `_setup_two_net_lines_sold`: replaced the five `api.` calls (`create_intake_batch`, `create_item`, `grade_item`, `list_item`, `create_sale`) with `api_client.` — the module symbol already imported at the top of the file and the exact object the `api` fixture wraps. Behavior-identical, more faithful (matches how `fixtures.py` helpers call `api_client` directly).

**Tests deleted:** none — no PRD-silence or non-unique-derivability issues; the only defect was a Python scoping typo.

**Fixes to test_helpers/ or implementation/:** none.

Verification: the post-fix 8-round parallel sweep is fully green — every round 68/68 passed, 0 failed. AST scan of all test files confirmed no other module-level helper references a bare `api`. Orchestrator re-confirmed all 8 results files: 68/68 / failed=0.

## Step 8: Finalize PRD — 2026-06-13T03:40:00.000Z

(Step 8 spawned because the literal skip condition requires 0 test_suite/ fixes; Step 7 had 1.)

**Outcome: PRD_FINALIZED.md is a byte-identical copy of PRD.md — zero edits.**

- PRD.md: 281 lines / PRD_FINALIZED.md: 281 lines / Delta: 0 lines, 0% (identical MD5 `8acedfc991ad9f3a73a61ef0fafcff28`).
- **No changes.** The sole Step 7 diff item is a pure `test_suite/` Python scoping bug (`api` → `api_client`) — not a PRD silence and not a PRD/impl mismatch.

**Pre-edit search confirming no pin needed (settlement rollup subject):** verified the two settlement-rollup assertions' expected values (NET 8001−150=7851; round_half_up(7851×0.5)=3926; ×2 = 7852 payable; gross 16002) are uniquely derivable from existing PRD prose (§3.5 line proceeds PRD.md:162, §3.1 NET fee basis PRD.md:126, §3.9 rollup PRD.md:184-192 — PRD.md:190 already pins round-per-line-then-sum ordering) and match `routes/settlements.py:99-162` + `services/calc.py:63-71`. No behavioral choice left open, no impl divergence. Wording adjustment: none.

## Step 9: Complete PRD — 2026-06-13T03:45:00.000Z

PRD_COMPLETED.md written with 10 minimal in-paragraph pins.

**Source vs completed:** `PRD_FINALIZED.md` (281 lines, 46,376 chars) → `PRD_COMPLETED.md` (281 lines, 49,551 chars). Char delta **+3,175**. Line count unchanged (all edits mid-paragraph inserts; no new sections/paragraphs).

**Counts:** 10 changes — **10 ambiguity-pins, 0 mismatch-revisions** (every gap was PRD silence where impl behavior was unique but unstated; none contradicted existing prose).

**Per-change:**
- §2.1 — insert — ambiguity — `X-User-Role` present but unrecognized value yields `ERR_UNAUTHENTICATED` (not `ERR_FORBIDDEN_ROLE`); forbidden-role only applies to recognized roles — `middleware.py:27-28`
- §2.3 — insert — ambiguity — `has_more` true exactly when `offset + window_size < total_count`; list filters are exact string-equality with no enum validation (unknown filter value → empty set, not an error) — `response.py:45`, `routes/items.py:72-75`, `routes/sales.py:171-174`
- §3.1 (schedule) — insert — ambiguity — out-of-range/non-numeric `base_floor_pct` and missing `tiers` key → `ERR_INVALID_REQUEST`; only tier structural violations → `ERR_INVALID_SCHEDULE` — `routes/schedules.py:46-56`, `13-35`
- §3.1 (schedule) — insert — ambiguity — archiving idempotent, no state precondition; re-archiving succeeds 200 and still bumps version — `routes/schedules.py:78-86`
- §3.1 (agreement) — insert — ambiguity — termination idempotent, no state precondition; re-terminating succeeds 200 and still bumps version — `routes/agreements.py:105-113`
- §3.2 (batch) — insert — ambiguity — closing is state-gated and not idempotent; closing a `CLOSED` batch → `ERR_INVALID_STATE` — `routes/batches.py:51-52`
- §3.3 — insert — ambiguity — `verdict_note` initializes null on open, always present in serialized reviews, and a verdict without a note leaves prior value unchanged — `routes/reviews.py:37`, `73-74`
- §3.4 — insert — ambiguity — clock driven before `floor_date` clamps negative elapsed time to zero (age never negative) — `services/calc.py:35-37`
- §3.5 (sale) — insert — ambiguity — `payment_method` purely informational; a `STORE_CREDIT` payment debits nothing and posts no transaction — `routes/sales.py:22`, `82`
- §3.5 (sale) — insert — ambiguity — sale lines validated phase-by-phase (resolve all → on-floor all → duplicates → price band), each phase scanning all lines before the next — `routes/sales.py:40-67`
- §3.6 (redeem) — insert — ambiguity — `amount_cents` must be integer ≥ 1; absent/non-integer/<1 → `ERR_INVALID_REQUEST` — `routes/consignors.py:135`

**Verified already-pinned (no change):** `sale_line_ref` holds item id; GET donation-record returns a list; redeem 201 / clock-set 200; all monetary constants (150/2000/10000/0.10/0.20/0.25/0.30) and field shapes match.

---

## Pipeline complete — 2026-06-13T03:46:00.000Z

All 9 steps done. Final state: 68/68 tests pass across all 8 parallel stability rounds (failed=0 each). Artifacts present: SCAFFOLD.yaml + 2 design YAMLs, test_helpers/ (9 files), test_suite/ (8 files, 68 tests), workspace/implementation/ (Flask, in-memory), PRD.md → PRD_FINALIZED.md (identical) → PRD_COMPLETED.md (+10 ambiguity pins).
