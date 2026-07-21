# Worklog — task_1064_rent_reporting_credit

## Step 1: Create task directory — 2026-07-21T03:22:00.000Z

Pre-assigned. task_name = task_1064_rent_reporting_credit, task_dir = tasks/task_1064_rent_reporting_credit. workspace/ existed. Step 1 treated as done.

## Step 2: Generate scaffold — 2026-07-21T03:54:00.000Z

All three artifacts complete and validated (SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml). yaml.safe_load OK on all three.

**Domain:** Rent-Reporting & Rent-to-Credit Service (Expert). Archetype: Compliance/audit + Ledger reconciliation; flat topology, cyclic state machines, segregation-of-duties role model, immediate consistency.

**Counts:**
- Entities: 11 (Tenant, Landlord, SubscriptionPlan, Enrollment, Lease, RentPayment, ReportedItem, Dispute, BackReportRequest, Invoice, ScoreSnapshot)
- Endpoints: 39 (20 POST, 10 single GET, 8 list/sub-resource GET, 1 computed read credit-summary; includes /api/_clock/set_current_utc test-driver, default 2026-07-01T00:00:00Z)
- Errors: 27 · Roles: 5 (Tenant, Landlord entity-backed; ComplianceAnalyst, ComplianceOfficer, PlatformAdmin opaque)
- State machines: 6 · Calculations: 5 · Validations: 18 (priority-ordered) · Concurrency rules: 1 (OCC)
- §1.8: 18 difficulty instances (2 per rule × 9). §1.9: 32 corner instances (26 active + 6 excluded stubs).
- scaffold_lint.py: VERDICT clean lint — 379 recipe calls conform to §1.5, all 15 FKs reverse-reachable.

**Notable design decisions:**
- OCC race is payment-record-stale-lease: recording a RentPayment carries expected_lease_version; the write bumps Lease.version, so a strictly-sequential stale-version write deterministically 412s.
- Rule-1 dual-variant spans two domains: tenant_on_time_rate (as_paid 67 vs as_reported 100) on Tenant credit, and cancellation_settlement (prorated 1015 vs accrual 0) on Enrollment billing.
- Rule-2 modes differ: back_report_fee = nested min/max (mode a); cancellation_settlement = pinned eval-order split earned/refund summing to paid (mode c).
- Depth-4 cascade: cancel → lease TERMINATED → item RETRACTED → tenant rate recompute.
- Two priority conflicts on distinct category pairs: {state≻business_temporal} on dispute filing; {business_constraint≻business_fiscal} on back-report approval.
- Removed a dead error mid-generation: ERR_DISPUTE_ALREADY_OPEN was unreachable — dropped from errors, validations, state-machine precondition.

**Constants (all declared inline, none undeclared):** GRACE_DAYS=5, DISPUTE_WINDOW_DAYS=90, DISPUTE_INVESTIGATION_DAYS=30, BACK_REPORT_MAX_MONTHS=24, BACK_REPORT_PER_MONTH_CENTS=200, BACK_REPORT_FEE_CAP_CENTS=3000; plan back_reporting_included_months is a per-plan input. Formula-derived asserts computed in code (earned 484 / refund 1015 / fee 400 / rate 67).

## Step 3: Copy INSTRUCTION.md — 2026-07-21T03:55:30.000Z

Copied ./INSTRUCTION.md → tasks/task_1064_rent_reporting_credit/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-07-21T03:56:00.000Z

Generated workspace/PRD.md (260 lines). Documented counts all match scaffold: 11 entities, 39 endpoints (§4 table has exactly 39 rows), 27 errors, 5 roles.

Sections: §1 Introduction; §2 Global Specs (2.1 RBAC, 2.2 Response Structure verbatim, 2.3 Pagination, 2.4 Common Properties & Logical Clock, 2.5 Monetary Precision, 2.6 OCC on Rent-Payment Recording, 2.7 Cascading Consistency & Denormalized Statistics, 2.8 Segregation of Duties, 2.9 Existence Validation & Request-Validation Order); §3 Business Logic (3.1 Onboarding, 3.2 Enrolment/Invoicing/Activation, 3.3 Leases & Verification, 3.4 Recording Rent Payments, 3.5 Furnishing Tradelines, 3.6 Back-Reporting, 3.7 Disputes/Investigation/Correction, 3.8 Cancellation/Settlement/Cascade, 3.9 Credit Summary & Score Tracking); §4 Endpoint Definitions; §5 Error Code Catalogue.

Hard Contracts all PASS: Field-Name Coverage (67 identifiers, 0 missing), Rule Coverage (validation priority chain, OCC expected_lease_version→ERR_STALE_VERSION 412, all state transitions incl. depth-≥3 cancel→terminate→retract→recompute cascade, all 5 calcs, SoD, correction supersede-chain), §3 Path Purity (325 tokens, 0 violations).

Constants stated: GRACE_DAYS=5, back-report 200 cents/month, fee cap 3000 cents, max 24 months, clock default 2026-07-01T00:00:00Z.

**Undeclared-constant flag + ORCHESTRATOR ADJUDICATION (no pre-patch needed):** SCAFFOLD.yaml references DISPUTE_WINDOW_DAYS and DISPUTE_INVESTIGATION_DAYS symbolically but declares NO numeric value (scaffold-gen's "all declared" summary claim was inaccurate). PRD-gen defaulted both to 30; design intent (DIFFICULTY line 633) is DISPUTE_WINDOW_DAYS=90. Verified both are **test-non-divergent**: (1) the only numeric window recipe is `item_not_disputable_state_beats_dispute_window_temporal` which asserts ERR_ITEM_NOT_DISPUTABLE (state precedence) NEVER ERR_DISPUTE_WINDOW_CLOSED — invariant to 30-vs-90 since clock is past both; (2) no recipe asserts ERR_DISPUTE_WINDOW_CLOSED standalone; (3) `investigation_deadline` is never asserted in either design file. Left PRD at 30; impl follows PRD, tests pass, Step 9 pins the private choice. No SCAFFOLD/PRD patch applied.

## Step 5: Generate unit tests — 2026-07-21T04:12:00.000Z

60 tests across 8 files: test_01_onboarding(6), test_02_leases(7), test_03_rent_payments_occ(6), test_04_furnishing(5), test_05_disputes(13), test_06_backreporting(8), test_07_cancellation(9), test_08_credit_summary(6). All collect under pytest; helpers+suite byte-compile.

Coverage: Queue A (§1.8) 18 instances → 17 translated (2 tests each = 34), 1 skipped. Queue B (§1.9) 26 non-stub → all 26 translated (1 each). 6 excluded stubs not translated (cross-refs resolve to real §1.8).

**The one skip:** `priority_pair_validation_conflict / period_covered_constraint_beats_invoice_unpaid_fiscal` (validations pri 14 vs 19). Asserts ERR_PERIOD_ALREADY_COVERED beats ERR_INVOICE_UNPAID, but PRD §3.6 prose lists checks enrollment-ACTIVE → invoice-PAID → period-covered; under §2.9 a faithful reader returns ERR_INVOICE_UNPAID first → not uniquely derivable. Gap left as gap. Sibling `item_not_disputable_state_beats_dispute_window_temporal` kept (PRD prose order agrees with asserted winner).

Dispute-window constants honored PRD-first: no test asserts ERR_DISPUTE_WINDOW_CLOSED or investigation_deadline; item-not-disputable test sets clock to 2026-10-15 (window closed under both 30 and 90) and asserts only the state error.

69 PRD citations verified verbatim; every test carries exactly one Design: tag. test_helpers: __init__, types, api_client, api_errors, assertions, factories, constants, test_users, fixtures.

## Step 6: Generate implementation — 2026-07-21T04:12:00.000Z

Complete Flask impl at workspace/implementation/. 39 routes registered (matches scaffold). All .py pass ast.parse. In-memory dicts only, nothing seeded.

Files: start.sh (foreground, $PORT, 0.0.0.0, exec python3 app.py), requirements.txt, app.py (blueprints+error handlers), store.py (in-memory dicts, logical clock default 2026-07-01, touch()/version++), common.py (error→HTTP map, envelope, pagination, auth, validators), calc.py (on-time status, both rate variants+recompute, back-report fee, prorated settlement, latest-score-by-bureau, cancel cascade), routes/ (12 modules).

Verified end-to-end (smoke): auth/RBAC, OCC 412, lease verification, furnishing, proration (refund 1015/earned 484), SoD 409, dispute→correction with superseding item + rate recompute, as_paid vs as_reported, back-report fee (billable 1→fee 200), INVOICE_UNPAID gating, deep cancel cascade (lease TERMINATED→items RETRACTED→stats 0/null), clock-backward rejection.

PRD ambiguities resolved (concrete choices): (1) ownership vs existence ordering — role-perm pre-existence 403, direct self-id ownership pre-existence when field present+mismatched, load-dependent ownership post-existence; missing FK → ERR_INVALID_REQUEST. (2) tenant email dup → ERR_INVALID_REQUEST 400. (3) SUBSCRIPTION invoice period_month = current clock month. (4) "the tenant's enrollment" = prefer ACTIVE, then PENDING_PAYMENT, then latest non-cancelled. (5) list scoping auto-restricts to owned; operators/PlatformAdmin see all. (6) stat recompute bumps version/updated_at; filing dispute does not recompute. (7) pagination clamps limit[1,100]/offset≥0, non-int → ERR_INVALID_REQUEST. (8) api_request_timestamp uses logical clock.

## Step 7: Test + fix loop — 2026-07-21T04:30:00.000Z

All 8 rounds pass 60/60 (2-wave sweep). NOT a clean first sweep (1 impl fix).

Iterations run: 2 (initial sweep → 1 fix batch → confirming sweep).
Tests deleted: None.
Fixes to test_helpers/: None.
Fixes to implementation/:
- routes/disputes.py, resolve_dispute + _create_superseding: made corrected_amount_cents (and corrected_on_time) OPTIONAL on POST /api/disputes/{id}/resolve instead of hard-requiring corrected_amount_cents. When omitted, the superseding tradeline inherits the original item's value for that field.

Diagnosis: all 6 failures deterministic (8/8), all in resolve-corrected flow, all 400 ERR_INVALID_REQUEST "missing or non-integer field: corrected_amount_cents". Tests resolve a PAID_ON_TIME dispute with only {resolution:CORRECTED, corrected_on_time:true} and never assert the superseding item's amount. SCAFFOLD line 1108 marks input as [resolution, corrected_on_time?, corrected_amount_cents?, note?] (both optional); PRD §3.7 does not mandate the amount → DEFAULT-VALUE-SILENCE / optional-input → STEP 3 impl fix (inherit original on omission), not a test change.

Final sweep: all 8 rounds passed 60/60.

## Step 8: Finalize PRD — 2026-07-21T04:35:00.000Z

Created workspace/PRD_FINALIZED.md (ran because Step 7 had 1 impl fix). PRD.md=260 lines, PRD_FINALIZED.md=260 lines (0% delta; 2 in-place §3.7 prose revisions, no lines added).

Changes:
- §3.7 — revise — "the corrected values corrected_on_time and corrected_amount_cents" → "optional corrected values (each may be omitted or sent as null)" — routes/disputes.py:114-127 (resolve_dispute).
- §3.7 — revise — added: "when a corrected value is omitted or null, the superseding tradeline inherits that field's value from the original" — routes/disputes.py:152-156 (_create_superseding).

NO-NEW-MISMATCH verified: calc.py recompute reads only item["on_time"] (always populated corrected-or-inherited); amount_reported_cents doesn't feed rate calc; UPHELD/_reinstate_item path untouched. No other impl path mis-described.

## Step 9: Complete PRD — 2026-07-21T04:40:00.000Z

Created workspace/PRD_COMPLETED.md from PRD_FINALIZED.md. 260→260 lines, 37957→41810 chars (+3853). 15 ambiguity-pins + 1 mismatch-revision (§2.9 validation-order interleave). All in-paragraph, no new sections.

Pins: §2.2 api_request_timestamp=logical clock; §2.3 pagination clamp + non-int→ERR_INVALID_REQUEST, tie-break by creation order, list owner-scoping; §2.9 missing/blank/wrong-type FK→ERR_INVALID_REQUEST, ownership/existence interleave (role-perm+self-id ownership pre-existence, load-dependent ownership post-existence, 404 before 403); §2.7 recompute bumps updated_at/version even if unchanged, filing dispute doesn't recompute; §3.1 dup email→ERR_INVALID_REQUEST; §3.2 SUBSCRIPTION invoice period_month=current clock month, pay non-DUE→ERR_INVALID_STATE; §3.5 enrollment selection order (ACTIVE→PENDING_PAYMENT→latest non-CANCELLED→latest), amount_reported_cents from amount_paid_cents, retract only from REPORTED; §3.6 completion draws earliest RECORDED payment/month + skips monthless, decide from PENDING/complete from APPROVED; §3.7 investigate/resolve/withdraw state guards; §3.8 re-cancel CANCELLED→ERR_INVALID_STATE.

Verified in code: DISPUTE_WINDOW_DAYS=30 and DISPUTE_INVESTIGATION_DAYS=30 (store.py) match PRD "thirty-day" prose — no change. Grace=5, back-report 200¢/cap 3000¢/max 24mo also match.

## PIPELINE COMPLETE — 2026-07-21T04:40:00.000Z

task_1064_rent_reporting_credit finished Steps 2–9. Final: 60/60 tests × 8 rounds. NOT a clean first sweep (1 impl fix: corrected_amount_cents/corrected_on_time optional on dispute resolve; 0 deletions, 0 test fixes). Step 8 ran (2 §3.7 revisions), Step 9 = 15 pins + 1 mismatch. 11 entities / 39 endpoints / 27 errors / 5 roles / 6 state machines / 5 calcs. Test-gen skipped 1 §1.8 instance (period_covered vs invoice_unpaid priority — PRD prose order not uniquely derivable). No constant pre-patching (DISPUTE_WINDOW/INVESTIGATION left at PRD default 30, test-non-divergent).
