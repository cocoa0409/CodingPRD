# Worklog — task_1067_flexible_rent_splitting

## Step 1: Create task directory — 2026-07-21T10:57:28.000Z

Directory `tasks/task_1067_flexible_rent_splitting/` and its `workspace/` subdir were pre-assigned and already existed. No index scan performed. Difficulty parameter: Expert. Scenario: Flexible-Rent & Rent-Splitting Platform.

## Step 2: Generate scaffold — 2026-07-21T11:22:00.000Z

All three artifacts complete, parse cleanly (yaml.safe_load OK for all three), pass scaffold_lint.py clean.

Counts:
- Entities: 11 — Property, Renter, Application, BillingCycle, Installment, Remittance, AutopayMandate, DelinquencyCase, RecoveryAction (event), Reminder (event), LedgerEntry (event). Flat topology, FK-linked.
- Endpoints: 43 (incl. POST /_clock/set_current_utc, default clock 2026-07-01T00:00:00Z)
- Errors: 28
- Roles: 6 — PlatformAdmin, Underwriter, CollectionsAgent, CollectionsManager (opaque); Renter (entity_backed:Renter), PropertyManager (entity_backed:Property). SoD model.
- State machines: 6 — Application (branching), AutopayMandate (ACTIVE<->PAUSED), BillingCycle (branching+compensation), Installment (SCHEDULED<->FAILED retry), Remittance (linear+compensation), DelinquencyCase (recovery cycle).
- Calculations: 6 — underwriting_risk_score, installment_schedule, flex_fee (dual-variant), delinquency_payoff (dual-variant), late_fee_accrual, cycle_repaid_amount.
- Concurrency rules: 1 — OCC on BillingCycle.version at /reschedule (CREATE-with-supersede).

Difficulty: SCAFFOLD_DIFFICULTY_DESIGN 18 instances (9 rules x2); SCAFFOLD_CORNER_DESIGN 31 instances (30 active + 1 excluded stub).

Undeclared constants: NONE. All calc constants live in calculations[].constants (DEFER_DAILY_BPS 30, GRACE_DAYS 5, SETTLEMENT_ADMIN_FEE 1500, MAX_DEFER_DAYS 25, MIN_INSTALLMENT_GAP_DAYS 5, fee tiers/weights); state-machine/validation thresholds pinned inline (MAX_ATTEMPTS 3, PROMISE_MAX_DAYS 14, RECOVERY_MIN_DAYS 30). No pre-patch needed.

## Step 3: Copy INSTRUCTION.md — 2026-07-21T11:27:06.000Z

Copied ./INSTRUCTION.md → tasks/task_1067_flexible_rent_splitting/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-07-21T11:37:00.000Z

PRD.md generated: 291 lines. Endpoints in §4 table: 43/43. Errors in §5: 28/28. All 3 hard contracts PASS (Field-Name Coverage 65/65, Rule Coverage all entities/state-machines/calcs/OCC/SoD/cascades, §3 Path Purity 0 violations). Design/corner YAML NOT opened. Dual-variant flex fee (provisional/final) and delinquency payoff (reinstatement/settlement) rendered as prose; OCC via expected_cycle_version + ERR_STALE_CYCLE_VERSION/412.

## Step 5: Generate unit tests — 2026-07-21T11:52:00.000Z

6 test files under test_suite/ (+conftest.py), 67 tests total, all collected cleanly by pytest.
test_helpers/ (9 files): __init__, types (11 entity TypedDicts; append-only RecoveryAction/Reminder/LedgerEntry omit updated_at/version), api_client, api_errors (28 IDs + status map), assertions, factories, constants, test_users (opaque roles + make_renter/property_manager_headers + agent/manager SoD builders), fixtures (create_enrolled_renter, create_declined_renter, create_scheduled_cycle, create_remitted_cycle, create_delinquent_case, open_outreach_case).
Coverage: Queue A (Difficulty) 18/18 translated, 0 skipped (37 tests). Queue B (Corner) 30/30 non-stub translated, 0 skipped (30 tests). 1 corner stub (late_fee_grace_boundary_covered_by_difficulty) correctly not translated. 67 Design tags / 67 tests, no dangling. Two validation-priority instances KEPT (PRD §2.9 states priority order → uniquely derivable). No skip/xfail.

## Step 6: Generate implementation — 2026-07-21T11:52:00.000Z

14 modules in workspace/implementation/. Route count: 43 (verified via URL map == scaffold/PRD endpoint table; partial-write guard PASS). ast.parse clean (0 syntax errors).
Files: start.sh (reads $PORT default 10000, binds 0.0.0.0, foreground exec python3 app.py), requirements.txt (flask==3.0.3), app.py (factory, blueprints, /_clock/set_current_utc, ApiError handler), core.py (in-memory DB, logical clock, helpers, auth, validators, pagination), calc.py (underwriting score/band/limit, flex-fee provisional+final, installment waterfall, constants), domain.py (ledger append, reminder emit, repaid/outstanding/net-remitted recompute), serial.py (per-entity serializers incl. live delinquency payoff), routes_property/renter/autopay/cycle/cycle_actions/installment/remittance/delinquency.
Storage: in-memory dicts keyed by UUID, wiped on boot; no seeding/preloading (grep-confirmed); no SQLite/file persistence. Logical clock defaults 2026-07-01T00:00:00Z.

## Step 7: Test and iterate loop — 2026-07-21T12:03:00.000Z

Iterations run: 2 (baseline sweep found 2 consistent failures; 1 fix; confirming sweep clean). All 8 rounds pass 67/67. Deterministic (no flakiness).

Tests deleted: NONE.

Fixes to test_suite/ (no test_helpers or implementation changes):
- test_05_delinquency_recovery.py, helper _recovery_reoutreach — three validate_success(api.record_recovery_action(...)) calls used default expected_status=200, but PRD §205 states verbatim "Endpoints that create a new resource return HTTP 201." The recovery-action endpoint (POST /api/delinquency-cases/{id}/recovery-actions) creates a new append-only recovery-action record (PRD §3.8), so the PRD-faithful impl correctly returns 201. Added `, 201` to the three creating calls (OUTREACH, PROMISE_SET, round-2 OUTREACH). Test-suite assertion bug; fix makes test MORE faithful to PRD. Affected tests: test_recovery_cycle_reoutreach_status_and_round, test_recovery_cycle_accrued_late_fee (both failed at shared helper — common upstream setup bug). Implementation correct throughout.

Fixes to implementation/: NONE.

Final sweep: all 8 rounds passed 67/67 (total = 67).

## Step 8: Finalize PRD — 2026-07-21T12:10:00.000Z

0-edit outcome (ran, not skipped, because Step 7 had 1 test_suite/ fix). PRD_FINALIZED.md byte-identical to PRD.md (291 lines, cmp confirms). No changes.
Verification: the sole Step 7 item was a test-suite assertion bug (record_recovery_action expected 200→201). PRD.md §205 already states verbatim "Endpoints that create a new resource return HTTP 201..."; recovery-action endpoint (routes_delinquency.py POST .../recovery-actions) creates an append-only record and already returns 201. PRD already uniquely determines the behavior → nothing to pin.

## Step 9: Complete PRD — 2026-07-21T12:24:00.000Z

PRD_COMPLETED.md produced as minimal inline patch over PRD_FINALIZED.md. Both 291 lines; 45,432 → 48,559 chars (+3,127). 13 edits (12 ambiguity-pins + mismatch-revisions), all in-paragraph, no new sections.
Changes:
- §2.3 insert — pagination clamps: limit→[1,100], negative offset→0, non-int→ERR_VALIDATION (core.py:264-271)
- §2.8 insert — OCC version check after body+domain-range checks; domain error wins over ERR_STALE_CYCLE_VERSION (routes_cycle_actions.py:54-76)
- §3.2 revise — duplicate renter email within property → ERR_VALIDATION 400 (routes_renter.py:44-46)
- §3.3 revise — activate mandate w/o method_ref → ERR_VALIDATION 400 (routes_autopay.py:67-73)
- §3.4 insert — create-cycle check order enrolled→mode→duplicate→limit (routes_cycle.py:98-119)
- §3.4 revise — reschedule due_offsets_days precedence: sorted asc, split_count=len, floor+remainder, earliest=IMMEDIATE rest SPLIT, gap on sorted (routes_cycle_actions.py:54-93)
- §3.6 insert — charge outcome default omitted→success; FAIL/FAILURE/FAILED/DECLINE/DECLINED→fail; else success (routes_installment.py:10-11,64)
- §3.6 revise — deferral replacement sequence_no = max existing +1 (routes_installment.py:110-118)
- §3.8 revise (mismatch) — case principal_outstanding_cents re-derived live on read, not frozen snapshot (serial.py:82-87)
- §3.8 insert — assess-delinquency only on REMITTED; no overdue-unpaid or outstanding≤0 → ERR_INVALID_STATE 409 (routes_cycle_actions.py:213-222)
- §3.8 insert — assess-case requires PROMISE_TO_PAY; else → ERR_INVALID_STATE 409 (routes_delinquency.py:124-129)
- §3.9 revise — cycle summary exposes both payoff figures always, accrued=0 when no case (serial.py:48-55)
- §3.9 revise — resolve with remaining principal → ERR_NO_OUTSTANDING_BALANCE 422 (routes_delinquency.py:180-181)
- §3.9 insert (mismatch) — charge-off guards SoD→recovery-period→balance per §2.9, contradicting prose "First/Second/Third" (routes_delinquency.py:149-158)
Note: §3.6 installment-waiver (WAIVED) prose has no endpoint in §4 table or impl → dead prose, left unchanged per no-invented-behavior.

## PIPELINE COMPLETE — 2026-07-21T12:29:00.000Z

All 9 steps done. Final artifact set present. Final 8-round sweep all-green (67/67 × 8). PRD_COMPLETED.md exists.
