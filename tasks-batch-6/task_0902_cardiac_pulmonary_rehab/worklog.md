# Worklog — task_0902_cardiac_pulmonary_rehab

## Step 1: Create task directory — 2026-08-02

Task directory tasks/task_0902_cardiac_pulmonary_rehab/ pre-created; created workspace/ subdirectory. Index scan skipped per instruction.

## Step 2: Generate scaffold — 2026-08-02

All three files complete, lint verdict clean. Expert. Primary archetype quota/allocation (36-session cap + insurance visit-limit dual pools) + secondary ledger-reconciliation (billing). Flat topology, cyclic state machines, peer-role RBAC, immediate consistency. Layers: OCC, cascading side-effects, dual-variant calc, rate/threshold triggers.

Scale: 12 entities — Patient, Physician, Clinician, MonitoringStation, Referral, RehabProgram, InsuranceAuthorization, RehabSession, CarePlanItem (education & goal merged), OutcomeAssessment (6MWT), BillingClaim, MaintenanceProgram. 52 endpoints (incl. /_clock/set_current_utc, default 2026-05-01T00:00:00Z) — flat under /rehab, every FK has a filtered-list reverse-reachability GET. ~45 error codes, 4 roles (ReferringPhysician/Clinician entity-backed; RehabCoordinator/BillingSpecialist opaque), 12 ordered validations.

State machines (7): RehabProgram (DRAFT→ACTIVE↔ON_HOLD→DISCHARGED/WITHDRAWN), RehabSession (cyclic SCHEDULED↔MISSED, COMPLETED→VOIDED), BillingClaim (cyclic SUBMITTED→DENIED→SUBMITTED, →VOID), Referral, InsuranceAuthorization, OutcomeAssessment, CarePlanItem, MaintenanceProgram. One OCC concurrency rule (session-create stale program version, 412).

Key calculations (7): session_billed_amount (tiered multiplier × conditional telemetry surcharge, min-cap 20000 — mode a); claim_reimbursement (estimated vs adjudicated dual-variant, billing domain); six_minute_walk_improvement (provisional vs verified dual-variant, clinical domain); patient_statement_total (round-per-claim-then-sum, mode b); session_capacity_accounting (forward vs chronological); adverse_vitals_check (SpO2<85 / RPE≥18 thresholds); maintenance_tier (improvement <10% → INTENSIVE).

Difficulty design (§1.8): 18 instances = 9 rules × 2. Corner design (§1.9): 27 active instances + 9 excluded_because stubs. All three files parse; scaffold_lint.py → clean lint (580 calls). Two accommodations: authorized_session_cap overridable input (default 36); POST /rehab/sessions requires program ACTIVE.

## Step 3: Copy INSTRUCTION.md — 2026-08-02

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-02

PRD complete at workspace/PRD.md, 318 lines. 5 top-level sections; 10 §2 subsections; 8 §3 subsections. 52 endpoints in §4 table (incl /_clock/set_current_utc), 47 error codes in §5 table — both match scaffold. Hard contracts all PASS (field-name coverage 78/78, rule coverage, §3 path purity 0 leaks).

Constants surfaced: MAX_CONSECUTIVE_MISSED undeclared in scaffold → surfaced as 3; VERIFIED consistent with corner design (three_consecutive_missed_sessions_hold_program, count==3). CLINICIAN_TURNOVER_BUFFER_MINUTES derived as 15 from validation note; VERIFIED consistent with difficulty design (clinician_turnover_buffer_overlap, =15). No SCAFFOLD/PRD pre-patch required — both values already correct.

## Step 5: Generate unit tests — 2026-08-02

63 tests total, all collect cleanly. test_helpers/ (9 files) + test_suite/ (conftest + 7 domain files). Queue A (Difficulty): 18/18 instances × 2 = 36 tests. Queue B (Corner): 27/27 non-stub instances × 1 = 27 tests; 9 excluded_because stubs correctly not translated. No instances skipped — all had verbatim PRD coverage + unique derivability. All tests carry exactly one verbatim Design: tag; 37 distinctive citations grep-confirmed in PRD.md; no scaffold leakage, no skip/xfail.

## Step 6: Generate implementation — 2026-08-02

workspace/implementation/: app.py (~1100 lines, self-contained), requirements.txt (flask==3.0.3), start.sh (reads $PORT, binds 0.0.0.0, foreground, exec python3 app.py). 52 @app.route decorators (matches 52 PRD endpoints). In-memory dicts, no seeding. ast.parse OK; 63 tests collect with PYTHONPATH=.

Key: Referral→Program(DRAFT→ACTIVE↔ON_HOLD→DISCHARGED/WITHDRAWN); session OCC (expected_program_version, 412); §2.10 scheduling precedence (OCC→state→telemetry→station half-open→clinician 15-min buffer→time-range→36-cap); adverse-vitals auto-hold (SpO2<85 strict / RPE≥18); 3-consecutive-missed auto-hold + cascade cancel; billing tiered session_billed_amount + estimated/adjudicated + deny→resubmit→void + visit-limit auto-EXHAUSTED + round-per-claim-then-sum statement; 6MWT provisional/verified (round-half-up 1dp); maintenance tier (INTENSIVE if <10.0, allowance 4/8).

PRD ambiguities impl resolved: program.version bumps only on capacity/lifecycle mutations (not billing); clinician ownership on complete/mark-missed; claim requires COMPLETED session but auth-APPROVED not hard-blocked (no error code); list out-of-range limit/offset → ERR_VALIDATION; input datetimes echoed verbatim, system timestamps canonical ...000Z.

## Step 7: Test and iterate — 2026-08-02

CLEAN FIRST-SWEEP PASS. All 8 rounds green (63/63 passed, 0 failed, 0 errors, 0 skipped). Iterations run: 1 (single 8-round sweep, run as 2 waves of 4 per saturation guidance). Tests deleted: none. Fixes to test_helpers/: none. Fixes to implementation/: none. On-disk results.1-8.json all verified 63/63. sweep.sh created at workspace/sweep.sh for reuse.

## Step 8: Finalize PRD — SKIPPED — 2026-08-02

Skipped per skip-condition: Step 7 exited on first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, 0 implementation/ fixes. PRD.md already determined every behavior the implementation exhibits. No PRD_FINALIZED.md produced.

## Step 9: Complete PRD — 2026-08-02

PRD_COMPLETED.md produced (started from PRD.md since Step 8 skipped). PRD.md 318 lines/41827 chars → PRD_COMPLETED.md 318 lines/43422 chars (+1595, all inline). 4 mismatch-revisions + 4 ambiguity-pins:
- §2.4 — insert — mismatch — program updated_at/version bump only on lifecycle + session create/complete/miss/void; reschedule & auth/claim ops recompute lazily on read without bumping. (app.py:1046,1100-1102,1191-1194)
- §2.9 — revise — mismatch — total_reimbursed_cents: adjudicated for paid, zero for denied, estimate otherwise (identity billed==reimbursed+patient_responsibility). (app.py:303-308)
- §3.3 — insert — ambiguity — EXHAUSTED derived only from otherwise-APPROVED auth; PENDING never shown EXHAUSTED; reverts to APPROVED when void drops visits_billed below limit. (app.py:399-404)
- §3.6 — insert — ambiguity — assessment_type only SIX_MINUTE_WALK else ERR_INVALID_ENUM. (app.py:44,1257)
- §3.6 — insert — ambiguity — improvement_meters/pct null for BASELINE & DISCHARGE w/o finalized baseline; most-recent finalized baseline used; baseline distance 0 → pct null, meters raw diff. (app.py:451-491)
- §3.7 — revise — mismatch — claim creation: no APPROVED check (existence+same-program+visits-available only); claim may be created vs PENDING auth. (app.py:1308-1327)
- §3.7 — revise — mismatch — denial_reason optional on DENIED, not required. (app.py:1401)
- §3.8 — insert — ambiguity — multiple FINALIZED DISCHARGE outcomes → most-recent drives tier; null improvement_pct → STANDARD. (app.py:883-888)

## PIPELINE COMPLETE — 2026-08-02

task_0902_cardiac_pulmonary_rehab: Expert, 63/63 tests green x8 rounds, CLEAN first-sweep (0 fixes). 12 entities, 52 endpoints, 8 state machines, 7 calculations. Step 8 skipped; Step 9 = 8 pins/revisions.
