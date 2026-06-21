# Worklog — task_0191_electric_utility_billing

## Step 1: Create Task Directory — 2026-06-06T10:46:47.000Z

Pre-allocated directory `tasks/task_0191_electric_utility_billing` used as-is (no ./tasks index scan, per parallel-run instruction). Created `workspace/` subdirectory. Scenario: Electric Utility Billing (AMI meter read import, inclining-block tiered rates, time-of-use periods, demand charges kW, net metering credit rollover, levelized budget billing, disconnect/reconnect for nonpay, LIHEAP assistance). Target difficulty: Expert.

## Step 2: Generate Scaffold — 2026-06-06T11:11:43.000Z

All three scaffold artifacts are complete and validated. Final summary for the orchestrator's worklog:

## Task 0191 — Electric Utility Billing scaffold (Expert band)

**Files written** to `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0191_electric_utility_billing/`:
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

**Difficulty band applied:** Expert (§0.4) — primary archetype *pricing engine*, secondary *ledger reconciliation*; layers: dual-variant calculation, rate/threshold triggers, cascading side effects, optimistic concurrency. Flat entity topology, parallel state-machine shape, peer-roles RBAC, immediate consistency.

**Scaffold counts:**
- **Entities:** 10 (Tariff, Account, Meter, MeterRead, Bill, Payment, ServiceOrder, BudgetBillingPlan, AssistanceGrant, SystemClock)
- **State machines:** 6 (Tariff linear; Account *parallel* service×financial dimensions; Bill branching+VOID; ServiceOrder; BudgetBillingPlan; AssistanceGrant cyclic EXHAUSTED→APPLIED on void)
- **Calculations:** 4 (price_bill tiered+TOU+demand+net-metering+assistance; budget_true_up; arrears_age_evaluation; payment_waterfall) — each with variants
- **Concurrency rules:** 2 OCC-on-Account (bill issue, budget true-up)
- **Endpoints:** 40 (incl. 2 `/_clock` test-driving)
- **Errors:** 19 (all referenced by validations/concurrency)
- **Roles:** 4 (BillingOperator, FieldDispatcher, AssistanceCaseworker, Customer)

**Design coverage:** §1.8 = 18 difficulty instances (all 9 rules × 2, differentiation clauses honored across distinct entity domains / error-category pairs / interval semantics / conserved quantities). §1.9 = 37 active corner instances + 3 `excluded_because` stubs.

**Validation status:** `scaffold_lint.py` → **VERDICT: clean lint** (415 calls scanned, all FKs reverse-reachable). All three files parse; zero unbound placeholders; all OCC `expected_account_version` inputs reference GET-sourced `${var}` captures; no forbidden concurrency vocabulary; no `id`-based business decisions. All formula-derived assertions were computed in code (e.g., standard bill 2756, tier-straddle 25000 energy / 480000 demand / 505000 total, net-metering carryover 19904→19748, LIHEAP 2000→total 756, budget true-up 2512, arrears 45-day boundary) and pinned as literals.

**Two issues caught and fixed during generation:** (1) flow-style YAML lists with `?`/`[]` tokens needed quoting; (2) an initial wrong clearing-payment literal (1656) for the single-read bill was corrected to the computed 2636 across all instances.

## Step 3: Copy Shared Files — 2026-06-06T11:12:05.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0191_electric_utility_billing/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-06T11:17:52.000Z

The PRD is complete and verified. Here is the worklog summary for the orchestrator.

## PRD Generation Complete — task_0191_electric_utility_billing

**Output:** `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0191_electric_utility_billing/workspace/PRD.md` (273 lines)

**Sections covered:**
- **§1 Introduction** — 2 paragraphs (AMI pricing engine + collections/ledger lifecycle framing)
- **§2 Global Specifications** — 10 subsections: RBAC (with all 4 role identities translated), fixed §2.2 envelope (verified byte-for-byte against canonical source), pagination, common resource properties, nested/path validation, monetary precision/rounding, account ledger + net-metering credit bank, two-dimension status + arrears aging, hierarchical consistency/cascades, and OCC on ledger writes
- **§3 Business Logic** — 10 subsections organized by lifecycle/process: rate structure, accounts/meters/AMI reads, bill creation+pricing (8-step formula), void/reversal, payments/waterfall/reversal, collections disconnect/reconnect, budget billing/true-up, assistance grants/shield, clock advance/re-aging, and validation ordering
- **§4** — 41-endpoint table (4 columns)
- **§5** — 19-error catalogue (2 columns)

**Hard Contracts — all PASS:**
- **Contract 1 (Field-Name Coverage):** 54/54 entity fields, 25/25 endpoint inputs, 9/9 query params present
- **Contract 2 (Rule Coverage):** both OCC rules (write endpoint + `expected_account_version` + `ERR_STALE_ACCOUNT_VERSION`/412), all 26 state transitions, 4 calculations (price_bill, budget_true_up, arrears_age_evaluation, payment_waterfall), all 19 validations matchable to error IDs, all 19 error IDs present; 41 behavioral spot-checks verified
- **Contract 3 (§3 Path Purity):** 0 path/method/method+path leaks across 409 §3 backtick tokens

**Notable design decisions:**
- All numeric thresholds embedded in prose as words (ARREARS_DAYS=45 → "forty-five days"; TOU hour windows spelled out with explicit inclusive/exclusive bounds) to satisfy the no-pseudocode / reconstruction-test rule
- The 8-step `price_bill` formula translated step-for-step into precise narrative, with the round-once-after-TOU-sum rule, the fixed+demand credit floor, and the assistance-after-credit ordering all called out explicitly
- Validation priority made explicit for the disconnect-notice chain (shield → arrears → state) per Contract 2 category 1
- OCC framed purely in stale-version terms (no "simultaneous"/"race" language)
- Confirmed: did NOT open `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml`

## Step 5: Generate Unit Tests — 2026-06-06T11:37:07.000Z

Everything is complete and validated. I cleaned up the temporary stub. Let me provide the final summary.

## Summary

Generated complete test infrastructure for **task_0191_electric_utility_billing** under the design-index-only contract.

### Files produced
- **`test_helpers/`** (9 files): `types.py` (entity TypedDicts + status/role enums; MeterRead & SystemClock correctly lean — id+created_at only), `api_client.py` (46 endpoint methods), `api_errors.py` (19 errors + HTTP-status map registration), `assertions.py` (per-entity validators + charge-decomposition/credit-floor invariants), `factories.py`, `constants.py`, `test_users.py` (3 opaque roles + entity-backed Customer with `make_customer_headers` identity builder), `fixtures.py` (composite setup chains: active-tariff/account/meter, issue-with-OCC, in-arrears, disconnect-pending, disconnected, budget-billed, assisted, plus 2756/2636 read-set builders), `__init__.py` barrel.
- **`test_suite/`** (conftest + 6 test files).

### Test counts
- **73 tests total**, all collect cleanly under pytest.
- **Queue A (Difficulty): 36 tests** — every one of the 18 instances has ≥2 tests.
- **Queue B (Corner): 37 tests** — every one of the 37 non-stub instances has exactly ≥1 test.

### Instances skipped / not translated
- **3 corner stubs left untranslated** (correct per contract — they carry `excluded_because` and the cited difficulty instance owns the assertion): `validations/complete_order_account_type_mismatch_rejected`, `cross_cutting_complexity_layers/budget_trueup_stale_account_version_rejected`, `cross_cutting_complexity_layers/cascade_disconnect_ordering_end_to_end`. All three cross-references resolve to real difficulty instances.
- No instances dropped for PRD-coverage failure; the PRD prose covers and uniquely derives every translated rule.

### Notable coverage decisions
- **Design-index arithmetic bug corrected via PRD-first adjudication.** The combinatorial instance `tiered_plus_tou_plus_demand_nonlinear_energy` asserts `total_due_cents == 505000`, but PRD §3.3 step 5 mandates gross = fixed(1000)+energy(25000)+demand(480000) = **506000** (the index omitted the fixed charge). I asserted the PRD-derived 506000, backed by the independent `assert_bill_charge_decomposition` invariant. The energy/demand/billed_peak sub-assertions (all PRD-correct) are kept.
- **`invalid_payment_zero_amount_rejected`**: design index grounds it on the generic range rule (`ERR_VALIDATION_RANGE`), but PRD §3.5 and the §5 catalogue both specifically and verbatim name `ERR_INVALID_PAYMENT` for a non-positive payment amount, so the test asserts the PRD-uniquely-derived `ERR_INVALID_PAYMENT` (409).
- Second-coverage tests for queue A use genuinely distinct PRD-derivable assertions (e.g., a fractional round-once-vs-per-period divergence case 23≠24; APPLIED-grant shield in addition to PLEDGED; positive control of the Bill→Tariff dependency) rather than duplicates.
- All 97 quoted PRD spans across docstrings verified to survive a literal grep of PRD.md; every docstring ends with exactly one verbatim `Design:` tag; zero orphan/dual tags; zero scaffold-terminology leaks; Customer identity correctly threaded for all ownership-gated payments.

## Step 6: Generate Implementation — 2026-06-06T11:37:07.000Z

Fresh boot confirms completely empty state (all `total_count=0`, clock `current_utc=None`) — no seeding. The implementation is complete and verified.

## Summary

Built a complete Python + Flask implementation of the Electric Utility Billing API in `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0191_electric_utility_billing/workspace/implementation/`.

**Files (23 total):**
- `start.sh` — foreground launcher (guarded pip install, `exec python3 app.py`)
- `requirements.txt` (Flask 3.0.3), `app.py` (blueprint registration + error handlers)
- Foundation: `db.py`, `errors.py`, `response.py`, `middleware.py`
- `routes/`: tariffs, accounts, meters, meter_reads, bills, payments, service_orders, budget_plans, assistance_grants, clock
- `services/`: `common.py` (parsing/pagination/validation), `pricing.py` (price_bill engine), `ledger.py` (arrears/waterfall/grant lifecycle), `serializers.py`

**Endpoints implemented: 40** — full CRUD/action surface across all 10 resource groups including the `/_clock` control surface, matching the PRD §4 endpoint table exactly.

**Notable architecture decisions:**
- **In-memory only** — per-entity dicts in `DB`, no disk/SQLite. The `SystemClock` is a singleton record with `current_utc=None` until set. Verified fresh boot wipes all state (no seeding).
- **Pricing engine** (`price_bill`) uses `Decimal` with `ROUND_HALF_UP`; energy charge rounded **once** after the TOU-weighted sum, demand and export-credit rounded independently. Net-metering credit caps at `gross - (fixed + demand)` floor with carryover rolling forward into the credit bank.
- **Parallel state dimensions** tracked independently on the account (`service_status` × `financial_status`); arrears aging is a floor-of-day-difference threshold with the 45-day boundary inclusive, recomputed both on payment (post-allocation set) and on clock advance (version bumped only when status changes).
- **OCC** via `expected_account_version` on bill-issue and budget true-up → `ERR_STALE_ACCOUNT_VERSION` (412); validation ordering follows PRD priority (tariff-active → state → OCC for issue; state → OCC for true-up).
- **Cascades**: payment waterfall (oldest-due-first, due_date then created_at tie-break) clears arrears and auto-cancels a scheduled disconnect reverting service to ACTIVE; bill void refunds NM credit + assistance grant (un-EXHAUSTING) + decrements budget counters; disconnect-notice gates evaluate shield → arrears → state in PRD-mandated order.
- **start.sh / $PORT**: reads `PORT` env (default 10000), `app.run(host="0.0.0.0", port=..., threaded=True)`, foreground via `exec`. Confirmed binds `0.0.0.0` and responds well within the 60s window.

**Verification:** Ran 70+ assertions across 5 smoke-test scripts covering pricing math (tiered + TOU + demand + NM), OCC rejection, arrears boundaries (0/1/43/44/45 days), full disconnect→complete→reconnect cycle, budget billing + true-up reconciliation, assistance shield + consumption + refund, payment reversal, and the full error catalog (auth/RBAC/FK/overlap/range/state). All real behavior passes.

## Step 7: Test-Fix Iteration Loop — 2026-06-06T11:46:33.000Z

All 8 parallel rounds pass cleanly: 72/72 each (was 73 total before the one deletion). The union of failing tests is empty. Exiting with the summary.

## Summary

**Iterations run:** 2 (baseline sweep → fixes → confirming sweep). Both sweeps were full 8-round parallel runs.

**Baseline:** 68/73 in all 8 rounds — 5 deterministic failures (no flakiness; identical across rounds):
- `test_empty_period_bill_floors_to_fixed_charge`
- `test_empty_period_with_budget_plan_still_floors_to_fixed_actual`
- `test_applied_grant_also_blocks_disconnect_then_lifts_on_cancel` (setup-crash)
- `test_fk_not_found_surfaces_over_missing_required_field`
- `test_void_then_reissue_conserves_credit_pool`

**Final:** 72/72 in all 8 rounds, clean.

**Tests deleted (1):**
- `test_void_then_reissue_conserves_credit_pool` (`test_suite/test_03_cascades_and_ledger.py`) — DELETED for unique-derivability collapse, **branch-asymmetric / incomplete-inverse side effect** (STEP 1b). PRD §3.3 step 6 banks `(carried_balance + export_credit) − applied` at issuance (Reading A, which the first-issue assertion requires), but PRD §3.4 void refunds **only** `net_metering_credit_applied_cents` and is silent on un-banking the export credit issuance deposited. So a PRD-faithful implementation leaves the banked export credit in place on void, and re-issuing the same export-bearing period legitimately compounds the bank to 39904. The test's expected sequence (19904 → 20000 → 19904) is not producible by any single faithful Reading-A implementation. The sibling test `test_void_conserves_net_metering_credit_pool` already covers the void-conservation invariant faithfully (issue→void) and still passes. Scaffold rule that drove generation: `Difficulty/compensating_invariant/void_conserves_net_metering_credit_pool`.

**Fixes applied to `implementation/`:**
- `services/pricing.py`, `price_bill()` — seeded the `total_import` / `total_export` (and per-period `period_import`) `sum()` calls with `Decimal(0)`. A bare `sum()` over an empty `reads` window returns int `0`, which lacks `Decimal.to_integral_value()`, crashing the `_num()` serializer with `ERR_INVALID_REQUEST` on every zero-read (empty-period) bill. Fixed the 2 empty-period tests plus the setup crash in the grant-shield test.
- `routes/accounts.py`, `create_account()` — moved the request-body foreign-key existence check (`tariff_id` → `ERR_FK_NOT_FOUND`) ahead of the structural `require_fields`/`require_str` validation, matching PRD §3.10's verbatim precedence ("request-body foreign keys yielding `ERR_FK_NOT_FOUND`. Structural validation of the request body follows: a missing required field ... yields `ERR_INVALID_REQUEST`"). Previously a missing `holder_name` masked a non-existent `tariff_id` with `ERR_INVALID_REQUEST`.

**Fixes applied to `test_helpers/`:** none.

No implementation checks were weakened, no assertions downgraded, no skip/xfail added. Storage remains in-memory only.

## Step 8: Finalize PRD — 2026-06-06T11:50:54.000Z

`PRD_FINALIZED.md` created as a byte-identical copy of `PRD.md`. After rigorous analysis, **no edits were warranted** — every Step 7 diff item traces to behavior the existing PRD already uniquely determines, or to a pure fixture/serializer bug.

## Summary

**Line counts:** PRD.md = 273 lines; PRD_FINALIZED.md = 273 lines. **Delta: 0 lines (0%).**

**Changes:** None. Each of the three Step 7 items was evaluated and found to already be determined by existing PRD prose, so patching would have either been redundant or introduced a new mismatch.

### Per-item analysis (with mandatory pre-edit search log)

**Item 1 — Deleted test `test_void_then_reissue_conserves_credit_pool` (net-metering credit banking).**
- (a) Subject: how `net_metering_credit_balance_cents` is banked at issuance and refunded at void.
- (b) Paths enumerated/read: `services/pricing.py:181-189,223-224`; `routes/bills.py:118-119` (issue commits balance); `routes/bills.py:157-158` (void does `balance += net_metering_credit_applied_cents` only); `routes/accounts.py:56`; `serializers.py:46`. Cross-checked surviving tests `test_net_metering_carryover_rolls_to_next_bill` and `test_void_conserves_net_metering_credit_pool` — both require Reading A.
- Finding: PRD §3.3 step 6 (line 148) + §3.4 (line 158) already control this uniquely. Deleted test asserted a void-then-reissue sequence not producible by the faithful combination — a fixture inconsistency, not a PRD silence.
- (c) No wording change (no edit).

**Item 2 — `price_bill()` empty-period `Decimal(0)` sum seed.**
- (a) Subject: pricing output for a zero-read (empty) billing period.
- (b) Paths: `services/pricing.py:132-165,230-235`; observable result via `test_empty_period_bill_floors_to_fixed_charge`.
- Finding: PRD §3.3 already determines every output (sum over zero reads = 0; floor to fixed). The seed only repaired a `_num()` serializer crash; no PRD-observable value changed. Pure bug fix.
- (c) No wording change (no edit).

**Item 3 — `create_account()` FK-before-structural ordering.**
- (a) Subject: precedence of `ERR_FK_NOT_FOUND` (body FK) vs `ERR_INVALID_REQUEST` (structural) on resource creation.
- (b) Paths: `routes/accounts.py:34-45` (FK-first, the fix); parallel create routes `meters.py:29-38`, `bills.py:39-47`, `payments.py:37-47`, `budget_plans.py:27-33`, `assistance_grants.py:29-38` — all structural-first; `services/common.py:42-46`.
- Finding: PRD §3.10 (line 202) already prescribes FK-before-structural globally; Step 7 fix made `create_account` conform. NOTE: impl is **inconsistent** — only `create_account` is FK-first; the other 5 create routes remain structural-first, contradicting §3.10. Restating §3.10 would deepen the existing universal-claim mismatch → forbidden new mismatch. Left verbatim. (Flagged for Step 9 full-scan adjudication.)
- (c) Deliberately no edit.

**Net result:** All three items already pinned by existing PRD prose (items 1 & 3) or non-observable bug fixes (item 2). PRD_FINALIZED.md == PRD.md byte-for-byte.

## Step 9: Complete PRD — 2026-06-06T11:57:41.000Z

All edits in place: 9 logical paragraphs revised, no sections added or removed (28 headings preserved), char delta +2256.

## Summary

**Source vs completed**
- Source: `PRD_FINALIZED.md` — 273 lines, 47,056 chars
- Completed: `PRD_COMPLETED.md` — 273 lines, 49,312 chars
- Char delta: **+2,256**; no lines added/removed (in-paragraph inserts/revisions only); 28 headings preserved (no new sections).

**Counts**
- Ambiguity-pins (PRD silent → pinned): **6**
- Mismatch-revisions (PRD described differently → revised): **3**

**Per-change log** `{section} — {insert|revise} — {kind} — {what} — {impl ref}`

- **§3.10** — revise — mismatch — Replaced the false universal "FK-existence before structural validation" claim with per-route reality: only `POST /accounts` checks the body FK first (and only when `tariff_id` is present; an absent `tariff_id` falls through to the structural check); the other five create routes run structural validation first, so a structurally-invalid request with a nonexistent FK yields `ERR_INVALID_REQUEST` before `ERR_FK_NOT_FOUND` — `accounts.py:34-39` vs `meters.py:29,37`, `bills.py:39,45`, `payments.py:37,45`, `budget_plans.py:27,31`, `assistance_grants.py:29,37` (flagged adjudication).
- **§2.1** — insert — ambiguity — Pinned that a Customer acting on another account's resource fails the ownership check with `ERR_FORBIDDEN_ROLE` — `middleware.py:52-56`, `meter_reads.py:101`.
- **§2.9** — revise — mismatch — Added budget-plan enrollment, payment posting, and payment reversal to the version-incrementing enumeration, and noted payment post/reverse bump version unconditionally — `budget_plans.py:54`, `payments.py:83`, `payments.py:119`.
- **§3.5 (payment post)** — revise — mismatch — Changed "Each such financial- or service-status change increments version" to: posting a payment increments `Account.version` once, unconditionally — `payments.py:83`.
- **§3.5 (reversal)** — insert — ambiguity — Pinned that reversal restores `balance_cents` by the full reversed amount and increments `Account.version` once, unconditionally — `payments.py:104,119`.
- **§3.3 step 7** — insert — ambiguity — Pinned which grant "the grant" is when multiple are consumable: the oldest-created `PLEDGED`/`APPLIED` grant with `remaining_cents > 0`, single grant per bill — `pricing.py:93-106`.
- **§3.1** — insert — ambiguity — Pinned that a duplicate tariff `code` is rejected with `ERR_INVALID_REQUEST` — `tariffs.py:117-119`.
- **§3.2 (meters)** — insert — ambiguity — Pinned that a duplicate meter `serial` is rejected with `ERR_INVALID_REQUEST` — `meters.py:40-42`.
- **§3.2 (meter reads)** — insert — ambiguity — Pinned that optional `export_kwh` defaults to zero when omitted or null — `meter_reads.py:38-39`.
- **§2.8** — insert — ambiguity — Pinned that the clock opens unset (null `current_utc`) until first set, and while unset every account computes `CURRENT` — `db.py:32`, `ledger.py:64-67`.
- **§2.3** — insert — ambiguity — Pinned that out-of-range/non-integer `limit`/`offset` are rejected with `ERR_INVALID_REQUEST` (not clamped), list-sort tie-break is creation order, and `has_more` is `offset + limit < total_count` — `common.py:129-141,150,157`.

**Deliberately left unchanged**: void-time grant-refund heuristic (`bills.py:183-196`) and Customer-ownership-vs-FK ordering only diverge in multi-grant edge cases the PRD's single-grant framing doesn't address; pinning would invent behavior. Tests used only as auxiliary cross-reference.

---

## Pipeline Complete — task_0191_electric_utility_billing

Final state: **72/72 tests pass across all 8 parallel stability rounds** under `prd-bench-local-run --isolation per-test-server`. Expert difficulty. All nine pipeline steps executed; full artifact set present.
