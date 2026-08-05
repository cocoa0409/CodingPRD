# Worklog — task_0869_municipal_combined_utility_billing

## Step 1: Create task directory — 2026-07-27T16:28:58.000Z

Created ./tasks/task_0869_municipal_combined_utility_billing/ and workspace/ subdir (pre-assigned folder; Step 1 next-index scan skipped). Verified ./INSTRUCTION.md exists for Step 3 copy.

## Step 2: Generate scaffold — 2026-07-27T16:58:00.000Z

All three files complete, parse cleanly (yaml.safe_load OK), pass scaffold_lint.py.
- SCAFFOLD.yaml (§1.0–§1.7), SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8, 18 instances), SCAFFOLD_CORNER_DESIGN.yaml (§1.9, 32 instances incl. 3 excluded_because stubs).

Scale (Expert):
- Entities: 13 (RateSchedule, Account, Meter, MeterReading, Bill, Payment, BudgetBillingPlan, Deposit, PaymentArrangement, Adjustment, ShutoffOrder, LienTransfer, MoratoriumWindow)
- Endpoints: 42 (incl. POST /_clock/set_current_utc, startup default 2026-05-01T00:00:00Z)
- State machines: 8 (Account, Bill, PaymentArrangement, Adjustment, ShutoffOrder, LienTransfer, Deposit, BudgetBillingPlan)
- Calculations: 9; Errors: 24; Roles: 6
- Difficulty: 9 rules × 2 = 18; corner: 32; 53 unique instance names; 270 recipe calls conform §1.5.

Notable Expert design choices:
- primary pricing_engine + secondary ledger_reconciliation; entity_topology hybrid, state_machine_shape parallel, role_model segregation_of_duties.
- Dual-variant calcs: Bill estimated-vs-actual read (2890 vs 4640); leak-relief SEWER_RELIEF vs TIER_REPRICE (1625 vs 647 for identical 6500-gal excess).
- Combinatorial formulas 2 modes: tiered marginal water + assistance discount (mode a) vs pinned round-per-line-then-sum (mode b: 4758 vs 4757).
- Non-linear SMs: PaymentArrangement cyclic (ACTIVE↔DEFAULTED); Bill parallel axes (payment_status × collection_status).
- Transitive cascades depth 3: arrangement default → account DELINQUENT → bills DELINQUENT → auto-CASCADE shutoff; finalize → final bill → deposit applied → refund payment.
- SoD (Adjustment requester ≠ approver, opaque X-User-ID) and OCC (arrangement create supersede on Account.version, ERR_STALE_VERSION 412).
- Temporal overlap: Bill half-open [start,end) adjacency-allowed vs MoratoriumWindow closed [start,end] adjacency-conflict.
- Two compensating invariants: deposit cash (amount == applied + refunded) and account receivable (payment reversal restores balance).
- Boundary precision: water tier at exactly 6000 gal (2890) vs 6001 (2891); delinquency grace at exactly 21 days.
- Removed 3 enum-closure dead-ends (PaymentArrangement COMPLETED, MoratoriumWindow LIFTED, LienTransfer CANCELLED).

## Step 3: Copy INSTRUCTION.md — 2026-07-27T16:59:00.000Z

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-07-27T17:07:00.000Z

PRD.md generated (267 lines). §1 Intro, §2 Global Specs (11 subsections), §3 Business Logic (9 workflows), §4 Endpoint table (42), §5 Error catalogue (24). Contracts 1/2/3 all PASS.
- Constants pinned (all declared in scaffold, no Zero-Silence gaps): NET_DUE_DAYS=20, DELINQUENCY_GRACE_DAYS=21, LIEN_MIN_ARREARS_CENTS=10000, water tiers 315/500/800 @6000/12000/∞, electric 12000/18000 @500/∞, SEWER_RATE=250, SEWER_CAP_UNITS=10000, WATER_TIER1_RATE=315.
- Interpretive decisions: (a) bill uses active rate schedule for service_type with latest effective_date ≤ period_start; (b) MoratoriumWindow closed-interval overlap = shared any day incl. adjacency, contrasted w/ half-open bill period.

## Step 6: Generate implementation — 2026-07-27T17:30:00.000Z

Complete Flask impl in workspace/implementation/: app.py (~1050 lines single module), requirements.txt (Flask 3.0.3), start.sh (exec, $PORT, 0.0.0.0 foreground). All 42 endpoints wired.
Safeguards: in-memory dicts only, no seeding, store wiped each boot; logical clock default 2026-05-01T00:00:00Z; created_at/updated_at echo clock string verbatim (.500Z not reformatted); client timestamps echoed as-sent; dashed UUIDs; Connection: close; Decimal/ROUND_HALF_UP money.
PRD ambiguities resolved:
- Account version bumps only on create=1, assistance +1, arrangement-create +1, finalize +1; other mutations refresh updated_at/recompute without bump (keeps OCC predictable).
- Levelization true-up via internal _levelization_cents accumulator folded into current_balance_cents.
- Deposit refund modeled as system Payment (method=CHECK, empty allocation), issued when refunded_cents>0.
- mark-delinquent precedence: collection≠CURRENT→ERR_INVALID_STATE, then PAID→ERR_BILL_ALREADY_PAID, then grace→ERR_NOT_YET_DELINQUENT.
- shutoff execute precedence: SCHEDULED→ERR_INVALID_STATE, moratorium→ERR_MORATORIUM_ACTIVE (pri 5), delinquent balance→ERR_NO_DELINQUENT_BALANCE (pri 6).
- lien certify performs PENDING→CERTIFIED→TRANSFERRED in one call.
- Customer ownership checked after existence (404 missing, 403 ERR_UNAUTHORIZED wrong owner).
- Leak/sewer rates from account's effective schedule w/ PRD constants (315/250) fallback.

## Step 5: Generate unit tests — 2026-07-27T17:44:00.000Z

test_helpers/ (9 files): types.py (13 entity TypedDicts, MeterReading omits updated_at/version), api_client.py (42 endpoint methods), api_errors.py (24 errors + HTTP map), assertions.py (+assert_deposit_conservation), factories.py, constants.py, test_users.py (operator + customer header builders), fixtures.py, __init__.py.
test_suite/ (9 files + conftest.py): 68 test functions.
Coverage: Difficulty all 18 instances ×≥2 = 36 tests; Corner all 32 non-stub ×≥1 = 32 tests; 3 excluded_because stubs NOT translated. Every test has one verbatim Design: tag; every PRD citation survives literal grep. Instances skipped: none.
Notable adjudication: payment_reversal_restores_account_receivable — PRD §3.5 internally ambiguous on reversed bill payment_status; tests assert only uniquely-derivable facts (payment REVERSED, balance restored 4640, amount_paid unwound 0), avoid asserting payment_status.

## Step 7: Test-and-fix loop — 2026-07-27T17:52:00.000Z

CLEAN FIRST-SWEEP PASS. 1 iteration (single 8-round parallel sweep). 68/68 passing in ALL 8 rounds (each results.{1..8}.json reports 68/68 passed, 0 failed, 0 errors).
- Tests deleted: none. test_helpers/ fixes: none. implementation/ fixes: none.
- Recurring-bug safeguards already in place: verbatim timestamp echo incl .500Z, dashed UUIDs, Connection: close, in-memory-only store no seeding, Decimal/ROUND_HALF_UP money.
- Sweep script: workspace/sweep.sh.

## Step 8: Finalize PRD — SKIPPED — 2026-07-27T17:52:30.000Z

Skipped per skip-condition: Step 7 exited clean on first sweep with 0 deletions, 0 test_suite fixes, 0 test_helpers fixes, 0 implementation fixes. PRD.md already determined every implementation behavior. No PRD_FINALIZED.md produced.

## Step 9: Complete PRD scan — 2026-07-27T17:57:00.000Z

PRD_COMPLETED.md produced from PRD.md (Step 8 skipped, no PRD_FINALIZED.md). 266 lines/43,280 chars → 266 lines/44,203 chars (+923 chars, all inline). 6 changes: 5 ambiguity-pins, 1 mismatch-revision.
- §2.3 Pagination — insert — non-integer limit/offset & negative offset → ERR_VALIDATION (app.py:408-420).
- §3.1 Rate Schedules — insert — tie on latest effective_date → most recently created governs (app.py:261-262).
- §3.5 Payments/Reversal — insert — reversal restores payment-status+receivable only; no re-delinquate/no revert account/shutoff recovery (app.py:951-964).
- §3.7 record-missed — insert — auto CASCADE shutoff reason=ARRANGEMENT_DEFAULT, scheduled_date=current clock (app.py:1137-1145).
- §3.7 reinstate — revise (mismatch) — "covers arrears" → total_arranged_cents >= delinquent_balance_cents, recovery only from DELINQUENT (app.py:1170).
- §3.9 Finalization — insert — refund payment POSTED method=CHECK empty allocation payment_date=clock; finalize returns final bill HTTP 201 (app.py:617-628,641).

## Pipeline complete — 2026-07-27T17:57:30.000Z

CLEAN FIRST-SWEEP PASS. All 8 rounds 68/68. Artifacts: SCAFFOLD.yaml + 2 design indices, PRD.md, PRD_COMPLETED.md, test_helpers/ (9), test_suite/ (68 tests), implementation/ (app.py/requirements.txt/start.sh), sweep.sh, worklog.md.
