# Worklog — task_1507_securities_lending_collateral_management

## Step 1: Create Task Directory — 2026-08-13T15:01:00.000Z

Pre-created and pre-assigned by the pipeline launcher (tasks/task_1507_securities_lending_collateral_management/ + workspace/). Step 1 treated as DONE per instructions; no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-13T16:24:00.000Z

Scaffold generation complete. All three files written to `/home/ubuntu/github/CodingPRD/tasks/task_1507_securities_lending_collateral_management/`, lint clean.

## Files written

- `SCAFFOLD.yaml` (1,254 lines) — §1.0–§1.7; no `scaffold_difficulty_design`/`scaffold_corner_design` keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (694 lines) — single top-level key `scaffold_difficulty_design` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (1,092 lines) — single top-level key `scaffold_corner_design` (§1.9)

## SCAFFOLD.yaml contents (§1.0–§1.7)

- **Complexity profile**: quota/allocation primary + compliance/audit secondary; layers = optimistic_concurrency, cascading_side_effects, rate_threshold_triggers, ops_run_checkpoint; flat topology, cyclic state shape, segregation-of-duties role model, immediate consistency
- **14 entities**: Security, BeneficialOwner, Borrower, LendablePosition, BorrowRequest, Loan (parallel dims: status × margin_status), CollateralPledge, MarginCall, Recall, ReinvestmentTranche, RevenueLedgerEntry (append-only, `common_fields: false`), LimitOverride, RegulatoryReport, PeriodClose
- **12 state machines / 53 transitions**: negotiation cycle PROPOSED⇄COUNTERED on Loan, recall fail/buy-in chain, margin-call OPEN→ESCALATED→CURED/DEFAULTED, report DRAFT⇄FINALIZED→FILED rework cycle, borrower-default and security-halt cascades
- **2 concurrency rules** (both OCC on `Loan.version`, 412 `ERR_STALE_VERSION`): `loan-amend-stale-version`, `pledge-substitute-stale-version`
- **12 calculations**: dual-variant fee accrual (per-day vs per-month rounding), dual-variant reinvestment income (stated yield vs NAV realization), owner-first/agent-residual revenue split, per-pledge-then-sum collateral rounding, ≥9000bps utilization gate, half-open forward-capacity, exclusive-deadline fail fees, indemnity shortfall, buy-in charge
- **10 prioritized validation rows, 73 endpoints, 35 error codes, 6 roles** (DeskTrader/OpsSettler/RiskOfficer/DeskAdmin opaque; BorrowerRep/OwnerRep entity-backed with scoping; SoD on override approve and report file)

## §1.8 difficulty design — 19 instances (9 rules, all ≥2)

dual_variant_calc 2 (Loan fees vs ReinvestmentTranche income), combinatorial_formula 3 (modes a, b, c all covered), non_linear_state_machine 2 (Loan negotiation cycle vs RegulatoryReport reopen cycle), transitive_cascade 2 (borrower default depth-4, security halt depth-3), priority_pair_validation_conflict 2 (state-vs-fiscal, safety-vs-constraint), boundary_precision_check 2 (utilization 9000/8999bps, deficit 0-vs-1-cent), cross_entity_state_dependency 2 (Loan→Borrower, ReinvestmentTranche→Loan), resource_temporal_overlap 2 (override mutual exclusion vs per-day aggregate capacity), compensating_invariant 2 (share buckets, collateral cash).

## §1.9 corner design — 57 instances (53 active + 4 `excluded_because` stubs)

Across all nine claim-guide sections: entities 7, state_machines 13, calculations 4, validations 4, endpoints 4, errors 10, rbac 6, complexity_layers 8, consistency_model 1.

## Verification

- `scaffold_lint.py`: **VERDICT: clean lint** — 73 endpoints, 14 entities, 19+53 instances, 628 calls scanned; all calls conform to §1.5, all FKs reverse-reachable
- All formula-derived asserts pre-computed and verified in Python (e.g., fee true-up +2¢, split 26738/16042 on pool 42780, per-pledge rounding 40006 vs 40005, fail fees 8000/30000, buy-in 720000, indemnity 80000)
- Self-audit: zero unbound `${var}` placeholders, 76 unique instance names, all 35 errors referenced from §1.2/§1.4/§1.5, no forbidden race vocabulary, OCC payloads reference captured versions only
- Replay pass caught and fixed three design bugs pre-lint: revenue-split double-count of FEE_TRUE_UP, halt-cascade making the halt error unreachable at match (rerouted to loan-create/collateral-pledge paths), and release-check ordering (deficit before uninvested-cash, pinned in the pledge transition)

## Step 3: Copy Shared Files — 2026-08-13T16:24:30.000Z

Copied ./INSTRUCTION.md → tasks/task_1507_securities_lending_collateral_management/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-13T16:52:00.000Z

All verification passes. Final summary:

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1507_securities_lending_collateral_management/workspace/PRD.md` — 341 lines. The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened.

### Section overview
- **§1 Introduction** — 2 paragraphs, business-context angle (owner/borrower/desk economics, SoD, logical clock).
- **§2 Global Specifications** (12 subsections) — 2.1 RBAC with per-role `identity:` translations (`BorrowerRep`/`OwnerRep` entity-backed, four desk roles opaque); 2.2 verbatim response-envelope block (byte-compared against `section-2.2-response-structure.md`); 2.3 pagination + all 13 list-filter sets; 2.4 logical clock (default `2026-08-01T00:00:00Z`); 2.5 integer cents / basis points / round-half-up; 2.6 common fields (with `RevenueLedgerEntry`/`PeriodClose` exception) + OCC contract; 2.7 ten-level validation priority order; 2.8 left-to-right path resolution; 2.9 utilization gate (floor division, ≥9000 bps inclusive); 2.10 forward-capacity day-interval accounting; 2.11 margin (10200/10500 bps) and per-pledge haircut valuation; 2.12 daily MTM run + month-end close.
- **§3 Business Logic** (9 subsections) — securities/halt cascade; counterparties and inventory; demand/matching/selector; negotiation loop/booking/amendments/returns; collateral posting/release/substitution/margin calls; reinvestment; recalls/fail fees/buy-ins; overrides/suspension/default cascade; ledger/accruals/close/revenue waterfall/regulatory reporting.
- **§4 Endpoint table** — 73 rows, 4 columns, roles verified per-row against the scaffold (0 mismatches).
- **§5 Error catalogue** — 35 errors, 2 columns, statuses matching the scaffold exactly.

### Coverage audit (scaffold rule → PRD prose)
- **Contract 1 (field names):** 95/95 required identifiers in backticks (73 entity fields, 4 endpoint-only inputs incl. `expected_loan_version`, 9 MTM/clock response fields, 9 path-only params) — **PASS** (two passes run; second pass confirmed).
- **Contract 2 (rules):** all 10 validation priorities expressed as an explicit ordered list (§2.7); both OCC rules with `expected_loan_version` + `ERR_STALE_VERSION`/412 and no race-framing (§2.6, §3.4, §3.5); all 48 state transitions across 12 machines with preconditions, error IDs, and side effects (incl. every cascade link: halt 3-link, settlement, default 4-link, request-cancel cascade); all 12 calculations as precise prose (pinned rounding orders, 9000-bps inclusive gate, 360-day basis, half-open windows, fail-fee deadline-exclusive/delivery-inclusive window, waterfall pinned order with `FEE_TRUE_UP` and fail-economics exclusions); all defaults and structured field content placed; sibling branches (accept/confirm, ISSUED/EXTENDED, CASH/SECURITY, provisional/final) rendered with equal density — **PASS**.
- **Contract 3 (§3 path purity):** 564 backticked tokens scanned in §3; 0 paths, 0 bare HTTP methods, 0 method+path combos — **PASS**.
- All 35 error IDs appear in §2/§3 narrative; all 65 enum/state values appear as exact strings; no pseudocode operators outside code fences; document ends at §5 with no audit footer.

## Step 6: Generate Implementation — 2026-08-13T17:25:00.000Z

73 endpoints in the scaffold, 73 route handlers implemented. The count matches exactly.

Here is the summary:

---

## Implementation Summary

### Files Written (13 source files + 2 config)

| File | Purpose |
|------|---------|
| `implementation/start.sh` | Foreground launcher, guarded pip install, `exec python3 app.py` |
| `implementation/requirements.txt` | `flask>=3.0.0` |
| `implementation/app.py` | Entry point, blueprint registration, error handlers, `app.run(host="0.0.0.0", port=$PORT)` |
| `implementation/db.py` | In-memory stores (14 dicts, all empty at boot), logical clock (defaults `2026-08-01T00:00:00Z`) |
| `implementation/errors.py` | `ApiError` class + all 35 error ID constants with HTTP statuses |
| `implementation/response.py` | Envelope helpers: `meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`, pagination fields in `meta` |
| `implementation/middleware.py` | `X-User-Role`/`X-User-ID` extraction, role gating, entity-backed scoping (OwnerRep/BorrowerRep) |
| `implementation/routes/helpers.py` | JSON body parsing, field validation, pagination (limit/offset/total_count/has_more), 404 helper |
| `implementation/routes/securities.py` | 6 endpoints: CRUD, halt, resume, price mark |
| `implementation/routes/owners_borrowers.py` | 12 endpoints: owner + borrower CRUD, suspend/resume/offboard/default |
| `implementation/routes/limit_overrides.py` | 5 endpoints: create, read, list, approve (SoD), reject |
| `implementation/routes/positions_requests.py` | 10 endpoints: position CRUD + suspend/resume, borrow request CRUD + cancel + match (selector) |
| `implementation/routes/loans.py` | 9 endpoints: create, read, list, counter, accept, confirm, cancel, amendments (OCC), returns |
| `implementation/routes/pledges.py` | 5 endpoints: create, read, list, substitute (OCC), release |
| `implementation/routes/margin_calls.py` | 3 endpoints: read, list, declare-default |
| `implementation/routes/recalls.py` | 6 endpoints: create, read, list, extend, cancel, buy-in |
| `implementation/routes/reinvestments.py` | 5 endpoints: create, read, list, mark, unwind |
| `implementation/routes/ledger.py` | 2 endpoints: read, list |
| `implementation/routes/ops_reports.py` | 10 endpoints: clock set, MTM, month-end close, period close read, report CRUD + finalize/reopen/file |
| `implementation/services/calculations.py` | All 12 calculation rules |
| `implementation/services/state_machines.py` | All 12 state machine transition/cascade functions |
| `implementation/services/ops.py` | Daily MTM batch + month-end close |

### Endpoint Count: 73 (matches scaffold exactly)

### 12 Calculations Realized

1. **required_collateral_value** — `compute_required_collateral_cents()`: margin_bps conditional on collateral_type (10200 CASH / 10500 SECURITIES), `round_half_up` at final multiplication only, using `Decimal`.

2. **posted_collateral_value** — `compute_posted_collateral_cents()` + `compute_pledge_marked_value()`: per-pledge rounding FIRST (each pledge rounded to integer cents), then summed. Haircut from pledged security's asset_class (200/600/1000 bps).

3. **margin_deficit_and_call_issuance** — In `evaluate_cure()` and `run_mark_to_market()`: deficit = required - posted; strict `> 0` for issuance; OPEN calls refreshed, ESCALATED calls keep original amount; cure when deficit <= 0 (exact equality = fully collateralized).

4. **loan_fee_accrual** — Provisional: `compute_daily_fee()` rounds half-up per day; one entry per (loan, date) enforced by `already` check. Final: `run_month_end_close()` reconstructs exact unrounded total from `_accrual_inputs`, rounds once, posts FEE_ACCRUAL_FINAL + FEE_TRUE_UP.

5. **rebate_accrual** — `compute_daily_rebate()`: active_cash * rate / 10000 / 360, round_half_up per day, posted as negative REBATE_ACCRUAL. One per (loan, date).

6. **reinvestment_income** — Provisional: `compute_daily_reinvest_income()` per (tranche, date). Final: `_unwind_tranche()` computes `realized = nav - principal` (may be negative), posts REINVEST_INCOME_FINAL.

7. **borrower_utilization_bps** — `compute_utilization_cents()` sums market_value over BOOKED/RECALLED loans; `compute_utilization_bps()` = floor(util * 10000 / effective_limit). Booking gate: prospective_bps >= 9000 blocks (inclusive).

8. **forward_capacity_check** — `check_forward_capacity()`: day-by-day walk of half-open [start, end) window; occupied = on_loan + sum of covering reservations; rejects if occupied + new > total on any day; open-term uses 3650-day horizon.

9. **fail_fee_accrual** — `compute_fail_fee_for_tranche()`: fee_days = max(0, delivery_date - deadline); fee = fee_days * round_half_up(shares * fail_price * 100 / 10000). Per-tranche rounding before day-count multiplication.

10. **buy_in_charge** — `compute_buy_in_charge()`: undelivered * buy_in_price_cents, posted as negative BUY_IN_CHARGE.

11. **revenue_split_waterfall** — `compute_revenue_split()`: gross = FEE_ACCRUAL_FINAL + REINVEST_INCOME_FINAL (FEE_TRUE_UP excluded); rebates negated from stored-negative; net_pool = gross - rebates; owner_share = round_half_up(net * bps / 10000); agent_share = net - owner_share (exact residual).

12. **indemnity_shortfall** — `compute_indemnity_shortfall()`: owed = market_value at default + FEE_ACCRUAL_FINAL entries; seized = sum of just-seized pledge values; shortfall = max(0, owed - seized); posts INDEMNITY_CREDIT only if owner opted in.

### 12 State Machines Realized

1. **Loan** — PROPOSED/COUNTERED cycle (counter), BOOKED (accept/confirm with full precondition battery), CANCELLED (reservation release + request re-open), RECALLED (system on recall create), SETTLED (settlement cascade: pledges RELEASED, tranches UNWOUND, calls CURED), DEFAULTED (default cascade: pledges SEIZED + COLLATERAL_SEIZURE entries, tranches UNWOUND, INDEMNITY_CREDIT, position release, recall cancel).

2. **BorrowRequest** — SUBMITTED -> MATCHED (match creates Loan PROPOSED), MATCHED -> LOANED (on booking), MATCHED -> SUBMITTED (on proposal cancel), SUBMITTED/MATCHED -> CANCELLED (borrower action), SUBMITTED/MATCHED -> EXPIRED (MTM run).

3. **Recall** — ISSUED -> EXTENDED (once only, strictly later deadline), ISSUED/EXTENDED -> COMPLETED (delivered == quantity, finalize fail fees), ISSUED/EXTENDED -> FAILED (MTM past deadline, snapshot fail_price), ISSUED/EXTENDED -> CANCELLED (zero deliveries only, loan back to BOOKED), FAILED -> BOUGHT_IN (DeskTrader, fail fee + buy-in charge, loan SETTLED).

4. **MarginCall** — OPEN -> CURED (deficit closed), OPEN -> ESCALATED (past due_date with deficit), ESCALATED -> CURED (deficit closed), ESCALATED -> DEFAULTED (RiskOfficer declare-default, fires loan default cascade).

5. **CollateralPledge** — ACTIVE -> RELEASED (DeskTrader, margin check then uninvested-cash check), ACTIVE -> SUBSTITUTED (BorrowerRep with OCC, replacement >= old value), ACTIVE -> SEIZED (system on loan default).

6. **LimitOverride** — REQUESTED -> APPROVED (RiskOfficer, SoD check, window overlap check), REQUESTED -> REJECTED, APPROVED -> EXPIRED (MTM when current >= expires_at).

7. **ReinvestmentTranche** — INVESTED -> UNWOUND (manual by DeskTrader or cascade on settle/default/buy-in).

8. **RegulatoryReport** — DRAFT -> FINALIZED (requires PeriodClose, aggregates frozen), FINALIZED -> DRAFT (reopen, aggregates cleared), FINALIZED -> FILED (DeskAdmin, SoD filer != finalizer).

9. **BeneficialOwner** — ACTIVE -> SUSPENDED, SUSPENDED -> ACTIVE, ACTIVE/SUSPENDED -> OFFBOARDED (guarded by zero open loans/reservations, suspends OPEN positions).

10. **Borrower** — ACTIVE -> SUSPENDED (cancels SUBMITTED requests), SUSPENDED -> ACTIVE, ACTIVE/SUSPENDED -> DEFAULTED (four-link cascade).

11. **Security** — LENDABLE -> HALTED (three-link cascade: cancel requests, cancel proposals, release reservations), HALTED -> LENDABLE.

12. **LendablePosition** — OPEN -> SUSPENDED (owner only), SUSPENDED -> OPEN (owner only).

### 2 OCC Rules Realized

1. **loan-amend-stale-version** — `POST /api/loans/{id}/amendments` requires `expected_loan_version`; mismatch returns `ERR_STALE_VERSION` (412). Also gated by `margin_status == CALL_OPEN` (ERR_MARGIN_CALL_OUTSTANDING).

2. **pledge-substitute-stale-version** — `POST /api/loans/{loan_id}/pledges/{pledge_id}/substitute` requires `expected_loan_version`; mismatch returns `ERR_STALE_VERSION` (412). Both OCC endpoints increment `loan.version` on success.

### Key Properties

- **No seeding**: All 14 stores are empty dicts at module init. Every entity is constructed via API calls.
- **In-memory only**: No SQLite, no file I/O, no /tmp cache.
- **start.sh**: Reads `$PORT` (default 10000), binds `0.0.0.0`, guarded `pip install` (no-op when flask already present), `exec python3 app.py` for foreground execution.
- **Logical clock**: Defaults to `2026-08-01T00:00:00Z`, settable via `POST /api/_clock/set_current_utc`, never falls back to wall clock.
- **All monetary math uses `Decimal`** with `ROUND_HALF_UP`, never `float`.

## Step 5: Generate Unit Tests — 2026-08-13T17:35:00.000Z

Done. Full test infrastructure and suite generated for task_1507_securities_lending_collateral_management.

## Summary

**test_helpers/ (9 files, all written new):**
- `types.py` — 14 entity TypedDicts + all status/role enums; `RevenueLedgerEntry` and `PeriodClose` correctly modeled as append-only (no `updated_at`/`version`).
- `api_client.py` — `ApiClient(GenericApiClient)` with 77 methods, one per endpoint row in the PRD endpoint table (all under `/api`).
- `api_errors.py` — full 35-entry `ApiErrorId` catalog + HTTP status map registered with the framework via `set_error_http_status_map`.
- `assertions.py` — per-entity `assert_*` checkers + position bucket-conservation invariant.
- `factories.py` — payload factories for all creatable entities (input fields only).
- `constants.py` — margin bps (10200/10500), haircuts (200/600/1000), 9000bps utilization cap, 100bps fail fee, 360-day basis, clock start.
- `test_users.py` — `TEST_USERS` constants for the 4 opaque roles; mandatory `make_borrower_rep_headers`/`make_owner_rep_headers` builders for the two entity-backed roles; per-role opaque builders for SoD tests; `ANONYMOUS_HEADERS` for 401.
- `fixtures.py` — composite helpers: `setup_desk`, `setup_booked_loan`, `setup_cash_loan_with_pledge`, `create_and_book_loan`, `create_borrow_request`, pledge/tranche/recall/return shortcuts, `set_clock`, `run_mtm`, `run_mtm_for_dates`, `run_mtm_on`, `run_month_end_close`, `setup_finalized_report`, entity getters, `list_ledger_entries`. Identity threading enforced (entity-backed roles always built from the created entity's id).
- `__init__.py` — barrel export of framework generics + PRD-specific code.

**test_suite/ (13 files: conftest.py + 12 test modules, 101 tests):**
- Queue A (Difficulty): **39 tests covering all 19/19 instances at ≥2 tests each** (100% coverage).
- Queue B (Corner): **62 tests covering all 53/53 non-stub instances at ≥1 test each** (100% coverage).
- 4 `excluded_because:` stubs not translated; all 4 `difficulty_instance` cross-references verified to resolve.

**Instances skipped:** none — every instance passed the PRD-first two-condition filter. One design-index wrinkle handled: the corner instance `recall_fail_and_buy_in_full_chain` lists `${ff} == 38000` for the FAIL_FEE ledger amount, but PRD §3.7 states "both entries are charged to the borrower as negative amounts," so the test asserts `-38000` (PRD is the contract; the recall entity's own `fail_fee_cents` field asserts 38000).

**Stage 2 self-audit results (all clean):**
- C4 tags: 101/101 tests carry exactly one `Design:` tag; zero untagged or dual-tagged.
- All 101 tags resolve to real instances in the source yamls; zero dangling refs; zero stub tags emitted.
- Zero `pytest.mark.skip`/`skipif`/`xfail`.
- C1 verbatim check: all 158 quoted PRD citation spans survive whitespace-tolerant literal grep of `workspace/PRD.md` (fixed 19 initial failures caused by elisions and markdown bold anchors).
- Zero "scaffold" mentions in generated code comments/docstrings.
- All files compile; `test_helpers` imports cleanly against the installed `prd_bench_local_runner` framework.

## Step 7: Run Tests and Iterate — 2026-08-13T18:05:00.000Z

All 8 rounds pass: 100/100 in each. Clean sweep.

---

## Summary

**Iterations run:** 2 (initial sweep + 1 fix-rerun cycle).

**Tests deleted (with PRD-silence category):**
- `TestComputedFieldRejected::test_position_create_rejects_computed_bucket_input` (test_01_entities_and_validation.py) — **PRD-silent on extra-field rejection**. PRD §3.2 enumerates the fields a position-create payload carries but never states that the server rejects payloads containing additional fields. PRD §2.7 #4 covers required-fields-present and enum-range rules only. The scaffold rule that drove generation was a strict-input-validation convention not actually stated in PRD.

**Fixes applied to `test_helpers/`:**
- None. (No factory / fixture / assertion helper changes were needed.)

**Fixes applied to `test_suite/`:**
- `test_05_recalls_and_buyins.py::test_second_recall_on_same_loan_rejected` — relaxed the error assertion to `validate_error_is_one_of([ERR_RECALL_ALREADY_OPEN, ERR_INVALID_STATE])`. PRD §2.7 places State (priority 6) before Structural rules including `ERR_RECALL_ALREADY_OPEN` (priority 8), so a faithful implementation may report either; PRD names both errors but does not pin which side of the state-vs-structural race wins.
- `test_05_recalls_and_buyins.py::test_recall_extend_only_once` — same relaxation to `validate_error_is_one_of([ERR_RECALL_ALREADY_EXTENDED, ERR_INVALID_STATE])` for the same precedence reason.
- `test_06_reinvestment_and_accruals.py::test_provisional_stream_diverges_from_final_without_trueup` — added `limit=100` to the `list_ledger_entries(OPS, loan_id=loan_id)` call. The test expected 11 entries (10 PROVISIONAL + 1 FINAL) but PRD §2.3's default page size is 10, so the FINAL entry was being paginated out — a fixture bug, not an implementation bug.
- `test_12_occ_and_matching.py::test_selector_ranks_by_min_fee_then_created` — changed `setup_desk(...)` to pass `min_fee_bps=50` so the default-desk position (fee=25, qty=10000) is no longer eligible for the request (max_rate=40). Previously the desk position tied with `p2` on all three ranking keys (`min_fee_bps`, `created_at`, `quantity_total`) because the logical clock freezes `created_at`, triggering `ERR_AMBIGUOUS_MATCH` instead of the intended rank-by-fee outcome.

**Fixes applied to `implementation/`:**
- All `routes/*.py` and `services/ops.py` — changed resource `"version"` initialization from `0` to `1`. PRD §2.6 says version "increments by one with every mutation"; the test suite consistently reads creation as the first mutation (`# create v1, accept v2, return v3` in test_07_cascades.py), so initial=1 is the convention the OCC tests and the negotiation-cycle tests assume.
- `routes/pledges.py::create_pledge` — moved request-shape validation (`require_fields(body, ["pledge_type"])` and `_validate_pledge_fields(body)`) BEFORE `get_or_404(db.loans, ...)`. PRD §2.7 priority is shape(4) → existence(5), so a malformed body must produce `ERR_VALIDATION` even when the path `loan_id` doesn't exist.
- `services/state_machines.py::return_shares` — added `_delivery_tranches` tracking (date + shares) on the open recall so fail fees can be computed retroactively for late deliveries once `fail_price_cents` is snapshotted at failure time. Per PRD §3.7, fail fees accrue per delivery tranche based on the calendar days from `deadline_date` to the delivery date; the previous implementation skipped accrual for tranches delivered while the recall was still `ISSUED`/`EXTENDED`.
- `services/state_machines.py` — added `_accrue_pending_fail_fees(recall)` helper that walks `_delivery_tranches` and accrues fees for any tranche not yet charged.
- `services/state_machines.py::_settle_loan` — removed the `_touch(loan)` call so settlement no longer double-bumps the loan version. The PRD's atomic-mutation rule (§2.6) plus "each return ... increments the loan's `version`" (§3.4) means a return-that-settles is one mutation, one version bump. The responsibility for the version bump now sits at the mutation entry point.
- `services/ops.py` — call `_accrue_pending_fail_fees(recall)` from the daily-run recall-failure branch (after the `fail_price_cents` snapshot) so tranches delivered late-but-before-failure get charged.
- `routes/recalls.py::buy_in_recall` — added `_touch(loan)` before `_settle_loan(loan)` so the buy-in mutation (which is the versioned entry point now that `_settle_loan` no longer touches) bumps the loan version exactly once.

## Step 8: Finalize PRD — 2026-08-13T18:20:00.000Z

# Step 8 complete — PRD_FINALIZED.md produced

**File:** `/home/ubuntu/github/CodingPRD/tasks/task_1507_securities_lending_collateral_management/workspace/PRD_FINALIZED.md`

**Line counts:** PRD.md = 340 lines, PRD_FINALIZED.md = 340 lines (0.0% line delta — all edits are inline within existing paragraphs; character delta is ~+2.3 KB across 8 paragraphs).

## Changes (one bullet per edit)

- **§2.6** — revise — `version` now pinned to start at 1 at creation ("creation itself counts as the resource's first mutation") — `routes/*.py` all creation sites (e.g. `routes/recalls.py:58`, `routes/positions_requests.py:46`, `routes/loans.py:67`, `services/ops.py:130` for margin calls) init `"version": 1` after the Step 7 0→1 fix.
- **§2.8** — revise — added the single exception to "path identifiers resolve before examining the request body": pledge posting validates payload shape (presence/enum of `pledge_type` + §3.5 type-consistency) before resolving path `loan_id`, yielding `ERR_VALIDATION`/`ERR_PLEDGE_TYPE_MISMATCH` even for a non-existent loan — `routes/pledges.py:47-53`.
- **§3.2** — insert — position create: server initializes the three computed quantities (`quantity_reserved`/`quantity_on_loan`=0, `quantity_available`=`quantity_total`); extra payload fields, including client-supplied computed buckets, are ignored rather than rejected — `routes/positions_requests.py:26-57` (deleted test `test_position_create_rejects_computed_bucket_input`).
- **§3.7** — revise — recall issuance pinned to `BOOKED`-only (`ERR_INVALID_STATE` otherwise); second-recall-while-open resolves to `ERR_INVALID_STATE` because the open recall holds the loan in `RECALLED` and §2.7 state (6) precedes structural (8) — `routes/recalls.py:31-32` fires before `:45-47`.
- **§3.7** — revise — second extension attempt resolves to `ERR_INVALID_STATE` (extension defined only from `ISSUED`; recall is already `EXTENDED`) instead of `ERR_RECALL_ALREADY_EXTENDED` — `routes/recalls.py:119-122`.
- **§3.7** — insert — fail-fee accrual timing: every delivery tranche is charged from the single snapshotted `fail_price_cents`; post-snapshot tranches accrue at delivery, pre-snapshot (late-but-before-failure) tranches accrue retroactively at the failing daily run or at completion; a recall completing without ever failing accrues nothing — `services/state_machines.py:128-146,192-211`, `services/ops.py:182-186`.
- **§3.4** — insert — a return that settles is one mutation: loan `version` increments exactly once, no extra bump for the settlement cascade — `services/state_machines.py:120,148-149,154-163`.
- **§3.7** — revise — buy-in's settlement of the loan is a single mutation incrementing loan `version` by one — `routes/recalls.py:214-216`.

**No PRD change** for the two pure fixture bugs in the diff: `limit=100` on `list_ledger_entries` (PRD §2.3 already pins default page size 10) and `min_fee_bps=50` in the selector test (PRD §3.3 already pins ranking keys and the tie rule).

## Per-edit pre-edit search log (NO-NEW-MISMATCH)

1. **§2.6 version-init.** (a) Subject: `version` field initial value/increment semantics. (b) Enumerated: grep `"version":` across `routes/`, `services/`, `app.py`, `db.py` — 14 creation sites all init 1 (securities, pledges ×2, owners, borrowers, recalls, reinvestments, reports, positions, requests, loans ×1+match, overrides, margin calls in ops.py); `_touch` (`state_machines.py:9-11`) is the sole incrementer (+1); `_post_ledger` and the `PeriodClose` dict carry no version, matching the PRD's two exceptions. (c) Added "subsequent" to "every subsequent mutation" so creation-as-first-mutation doesn't double-count.

2. **§2.8 pledge-shape exception.** (a) Subject: path-id-resolution vs body-validation ordering. (b) Enumerated ordering in every route via grep of `get_json_body`/`get_or_404`/`require_fields`: `create_pledge` is the *only* endpoint validating body shape before path resolution; all other path-bearing routes (recalls ×4, loans ×6, substitute, release, reinvestments ×3, reports ×3, overrides ×3, owner/borrower/securities transitions, match, cancel) resolve path ids first; body-first creates have no path ids. (c) Scoped the carve-out to pledge posting only and called it "the single exception" rather than universalizing §2.7 shape-before-existence (which `create_recall`, `amend_loan`, etc. do not follow) — avoids a new mismatch.

3. **§3.2 position-create extras.** (a) Subject: handling of undeclared fields in the position-create payload. (b) Enumerated: `create_position` builds the record solely from the four named fields (`positions_requests.py:42-56`); `require_fields` (`helpers.py:19-23`) checks presence only — no unknown-field rejection exists anywhere; no other endpoint creates positions. (c) Wording scoped to the position-create endpoint only; no universal claim about other endpoints' payloads.

4. **§3.7 second-recall race.** (a) Subject: state-vs-structural error for a second recall. (b) Enumerated: `create_recall` ordering (state `:31-32` → shape `:35-38` → quantity `:41-42` → already-open `:45-47` → window `:51-52`); every transition that opens/closes a recall (`_complete_recall`, `cancel_recall`, buy-in, default cascade `:290-293`, ops fail branch) confirms an open recall always co-occurs with a non-`BOOKED` loan, making the state check fire first; `ERR_RECALL_ALREADY_OPEN` is thereby unreachable in impl. (c) Kept both error codes in the text (catalogue intact) but pinned the reported one to `ERR_INVALID_STATE`; deliberately said nothing about shape-vs-state ordering here, since `create_recall` checks state *before* body shape — a pre-existing quirk outside Step 7 scope.

5. **§3.7 second-extension race.** (a) Subject: state-vs-structural error for re-extension. (b) Enumerated: `extend_recall` (`recalls.py:119-122`) checks `status != "ISSUED"` before `extended_once`; since extension lands the recall in `EXTENDED`, `ERR_RECALL_ALREADY_EXTENDED` is unreachable; cancel/buy-in/default paths unaffected. (c) Mirrored edit 4's pattern ("defined only from ISSUED ... ERR_INVALID_STATE under the same §2.7 priority").

6. **§3.7 fail-fee accrual timing.** (a) Subject: when each delivery tranche's fail fee is charged and at which price. (b) Enumerated: `return_shares` tranche recording + immediate accrual when price known (`state_machines.py:123-146`); `_accrue_pending_fail_fees` early-return when price is null and per-tranche catch-up (`:192-211`); ops fail branch snapshot→accrue ordering (`ops.py:179-187`); `_complete_recall` posting `FAIL_FEE` only when fee>0 (`:214-227`); buy-in remainder accrual (`recalls.py:177-206`); verified fee formula matches PRD exactly (`calculations.py:240-243`: round per-tranche product, then multiply by days). (c) Explicitly covered the never-failed-completion case (no price ⇒ no fee ⇒ no entry) so the completion sentence doesn't contradict the new retroactive-accrual sentence.

7. **§3.4 settling-return version.** (a) Subject: loan version bumps on the return-that-settles path. (b) Enumerated all `_settle_loan` callers (`state_machines.py:149` after `_touch` at `:120`; `recalls.py:216` after `_touch` at `:215`) and all other `_touch(loan)` sites (book, cancel, counter `:158`, amend `:228`, recall create/cancel, reinvest create, substitute, default) — exactly one touch per mutation entry point; `_settle_loan` itself now only updates `updated_at`. (c) None needed beyond scoping the sentence to "the settling return".

8. **§3.7 buy-in version.** (a) Subject: loan version bump on buy-in settlement. (b) Same enumeration as edit 7 plus `buy_in_recall` body (`recalls.py:163-218`): `_touch(loan)` at `:215` precedes `_settle_loan` at `:216`, single bump. (c) Rephrased the cascade enumeration from a colon-list to an emdash-list so the appended "single mutation ... increments version by one" clause attaches to the whole cascade sentence unambiguously.

## Step 9: Complete PRD — 2026-08-13T18:55:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1507_securities_lending_collateral_management/workspace/PRD_COMPLETED.md` is written — a minimal inline patch over PRD_FINALIZED.md, verified against every file in `implementation/` (app, middleware, db, response, errors, helpers, 12 route modules, 3 service modules).

**Volume**: 340 → 340 lines (no sections/paragraphs added or removed; all edits are in-paragraph inserts or revisions). Characters 65,292 → 71,536 (**+6,183**). 17 paragraphs touched.

**Counts**: 39 ambiguity-pins, 8 mismatch-revisions.

**Change log** (`{section} — {insert|revise} — {ambiguity|mismatch} — {what} — {impl ref}`):

- §2.1 — insert — ambiguity — missing `X-User-ID` tolerated, treated as empty string — implementation/middleware.py:24
- §2.1 — insert — ambiguity — single-resource reads are not ownership-scoped (any role may read any id) — implementation/routes/loans.py:97-103 (same pattern in all GET-by-id routes)
- §2.3 — insert — ambiguity — limit/offset clamped to bounds, unparseable values fall back to defaults — implementation/routes/helpers.py:53-64
- §2.3 — insert — ambiguity — `has_more` = `offset + len(page) < total_count`; equal `created_at` ties keep insertion order — implementation/response.py:28, helpers.py:67
- §2.4 — insert — ambiguity — all server timestamps (`api_request_timestamp`, `created_at`, `updated_at`) read the logical clock, always rendered `.000Z` — implementation/db.py:17-18, response.py:19
- §2.5 — insert — ambiguity — half-up = ties away from zero in either sign (negative pools) — implementation/services/calculations.py:12-14
- §2.6 — revise — **mismatch** — OCC is an equality check ("does not equal current version"), not "has advanced beyond" — implementation/routes/loans.py:211, pledges.py:140
- §2.6 — insert — ambiguity — OCC comparison runs after existence/state, before remaining payload validation and business gates — loans.py:204-217, pledges.py:129-143
- §2.6 — insert — ambiguity — derived-field recomputation (reads, price marks, pledge post/release) does not bump loan `version` — pledges.py:82-83/211-212, securities.py:116-119
- §2.7 item 3 — insert — ambiguity — path resolution precedes ownership evaluation (404 before scoping) — loans.py:133-141
- §2.7 item 4 — insert — ambiguity — extra body fields ignored, never rejected, on every endpoint — helpers.py:8-24 and all route bodies
- §2.7 item 7 — revise — **mismatch** — borrower/owner gates also block direct loan creation; position-not-OPEN gate added — implementation/routes/loans.py:49-56
- §2.10 — revise — **mismatch** — occupancy window anchored at the loan's reservation (creation) date, fixed as clock advances — implementation/services/calculations.py:213-230
- §2.10 — insert — ambiguity — open-term windows evaluated over a 3650-day horizon — calculations.py:176-179, 228-230
- §2.12 — insert — ambiguity — `loans_accrued` counts only loans whose fee/rebate entry actually posted; reinvestment accruals uncounted in summary — implementation/services/ops.py:56-65, 85-109
- §2.12 — insert — ambiguity — malformed `period` → `ERR_VALIDATION`; close-created entries carry the close run's clock date as `accrual_date` — implementation/routes/ops_reports.py:57-58, ops.py:249/257/270/278
- §3.1 — insert — ambiguity — duplicate symbol → `ERR_VALIDATION`; strictly positive opening/marked price; halt only from `LENDABLE`, resume only from `HALTED` (`ERR_INVALID_STATE`) — implementation/routes/securities.py:27, 30-32, 76-77, 87-88, 101-102
- §3.2 — insert — ambiguity — strictly positive `credit_limit_cents`; `min_fee_bps` non-negative integer — owners_borrowers.py:130, positions_requests.py:33-34
- §3.2 — revise — **mismatch** — position/owner gate enumerations extended to direct loan creation (matching §2.7/§3.4) — loans.py:51-56
- §3.3 — insert — ambiguity — `max_rate_bps` non-negative — positions_requests.py:130-131
- §3.3 — insert — ambiguity — explicit-position nomination failure mapping (`ERR_VALIDATION`/`ERR_POSITION_SUSPENDED`/`ERR_OWNER_SUSPENDED`/`ERR_NO_INVENTORY`/`ERR_FORWARD_CAPACITY_EXCEEDED`) — positions_requests.py:282-295
- §3.3 — insert — ambiguity — request cancellation defined only from `SUBMITTED`/`MATCHED` — positions_requests.py:194-195
- §3.4 — revise — **mismatch** — direct create enforces full gate battery (halt, owner ACTIVE, borrower ACTIVE, position OPEN) before capacity; cross-reference checks run after the four FK references resolve — loans.py:37-61
- §3.4 — insert — ambiguity — proposals carry computed economics from creation (market/required valued at current price, posted/uninvested zero, `original_price_cents` null, `margin_status` CURRENT) — loans.py:63-94, calculations.py:304-324
- §3.4 — insert — ambiguity — amendment fields optional; absent-or-null left unchanged; a set term cannot be removed — loans.py:220-226
- §3.4 — insert — ambiguity — settlement-cured margin calls carry `note: "settled"` (field otherwise absent) — services/state_machines.py:183-186
- §3.5 — insert — ambiguity — pledge type independent of loan `collateral_type` — implementation/routes/pledges.py:42-85
- §3.5 — insert — ambiguity — release requires an `ACTIVE` pledge, checked before loan state — pledges.py:188-194
- §3.5 — revise — ambiguity — a past-due `OPEN` call is escalated instead of refreshed; `ESCALATED` calls keep the amount carried into escalation — ops.py:141-151
- §3.6 — insert — ambiguity — `stated_yield_bps` non-negative; `realized_income_cents` null until unwind; opening a tranche bumps loan version, marking/unwinding do not; zero computed income posts no entry — implementation/routes/reinvestments.py:36-37, 52-59, 102-119, ops.py:100-109
- §3.7 — revise — **mismatch** — completion also lands from `FAILED` when late deliveries bring `delivered_quantity` to `quantity` — state_machines.py:144-146, 230-234
- §3.8 — insert — ambiguity — default cascade moves `OPEN`/`ESCALATED` margin calls to `DEFAULTED`; desk-initiated (request-less) proposals survive a borrower default with reservations intact; a zero indemnity shortfall posts no entry — state_machines.py:272-299, 342-355
- §3.9 — revise — **mismatch** — `REVENUE_SPLIT_AGENT` entry is attributed (`owner_id`) to the owner whose pool was split — ops.py:274-281
- §3.9 — insert — ambiguity — exact fee uses each day's quantity/price/rate as of that day's accrual; `FEE_TRUE_UP` posts even when zero — ops.py:46-55, 252-259
- §3.9 — revise — **mismatch** — owners whose net pool, owner share, and agent share are all zero receive no split entries — ops.py:263-265

**Deliberately not pinned** (impl-internal, unobservable, or unreachable through the API): the 405→404 handler and 500 fallback in app.py; the `effective_limit_cents <= 0` sentinel (unreachable — limits are validated positive); stored-vs-recomputed drift of position `quantity_on_loan` between reads (reads always recompute per §3.2's definition); ledger-entry `note` strings (PRD declares the field free-form).
