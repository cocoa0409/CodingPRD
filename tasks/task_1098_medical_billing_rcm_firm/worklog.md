# Worklog — task_1098_medical_billing_rcm_firm

## Step 1: Create task directory — 2026-07-24T11:58:00.000Z

Created `tasks/task_1098_medical_billing_rcm_firm/` and `workspace/` (pre-assigned folder; Step 1 directory scan skipped per instructions). Target difficulty: Expert.

## Step 2: Generate scaffold — 2026-07-24T12:27:00.000Z

Scaffold subagent stalled twice mid-stream (API "Response stalled"); resumed via SendMessage both times off on-disk state (never restarted). First resume wrote SCAFFOLD.yaml + DIFFICULTY + a thin 7-instance corner; second resume expanded corner to 31 instances. Orchestrator post-fix: quoted nested-bracket `grounds:` subscripts (`errors[ERR_X]`) in SCAFFOLD_CORNER_DESIGN.yaml so yaml.safe_load succeeds. All 3 files parse cleanly.

Subagent final summary (verbatim):

All three scaffold files are complete, parse cleanly, pass `scaffold_lint.py` (VERDICT: clean lint), and hit every Expert target.

Task: `task_1098_medical_billing_rcm_firm` — Outsourced Medical Billing & RCM Firm, designed at **Expert** difficulty.

### Counts
- Entities: 13 (Practice, Payer, Provider, PayerEnrollment, FeeSchedule, FeeScheduleLine, Claim, ClaimLine, Denial, Appeal, RemittanceAdvice, PaymentPosting, PatientStatement)
- State machines: 8 — cyclic: **Claim** (DENIED→APPEALED→DENIED across appeal rounds) and **Provider** (APPROVED→EXPIRED→SUBMITTED re-credentialing loop); branching: **Appeal** (SUBMITTED→{OVERTURNED, UPHELD} divergent side-effects) and PatientStatement
- Calculations: 6 (patient_responsibility, claim_ledger_reconciliation, practice_billing_fee, remittance_allocation, statement_aging_bucket, practice_kpi)
- Validations: 28 (ordered auth→existence→state→safety→referential→temporal→constraint→fiscal→OCC)
- Endpoints: 63 (`/rcm` prefix; includes `/_clock/set_current_utc` default `2026-05-01T00:00:00Z`)
- Errors: 31
- Roles: 7 — segregation_of_duties; 6 firm-operator roles + `entity_backed:Practice` PracticeUser
- Difficulty design: 9 rules × 2 = **18** instances; Corner design: **31** instances across 8 sections

### Notable Expert features
- Ledger reconciliation: provisional (scrub-time) vs realized (ERA-posting) reimbursement.
- Dual-variant across domains: expected_reimbursement on Claim vs charge-based/collection-based commission on Practice.
- Combinatorial formulas: 4-input nested min/max patient-responsibility cap; pinned round-per-claim-then-sum billing fee (126 not 125).
- Depth-3 cascade: posting → claim ledger → Claim ACCEPTED→PAID → Practice collected/AR; plus depth-2 appeal→denial→claim.
- Two conservation invariants: remittance pool (total = allocated + unallocated) and per-claim ledger identity, both restored on posting reversal.
- Two interval semantics: closed-closed FeeSchedule overlap vs half-open PayerEnrollment.
- OCC versioning on Claim.version (payment posting) and Practice.version (fee-schedule activation) → ERR_STALE_VERSION (412).
- Segregation of duties: same X-User-ID cannot both scrub and submit a claim.
- Boundary precision (inclusive 90-day timely filing, day-90 vs day-91 aging, zero-balance statement).

One fix during generation: added `GET /rcm/payers/{id}/claims` to close a Claim.payer_id FK reverse-reachability gap.

## Step 3: Copy INSTRUCTION.md — 2026-07-24T12:27:30.000Z

`cp INSTRUCTION.md workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-24T12:36:00.000Z

PRD.md written (329 lines). Design/corner files withheld. Subagent summary (verbatim):

Structure — 5 top-level sections, 18 subsections. Endpoints documented: 63 — exactly matches scaffold's 63. Zero-Silence Rule applied; all three hard contracts pass (field coverage — `fee_schedule_id`/`denial_id` added on re-check; rule coverage — all state transitions incl. cyclic re-credentialing + DENIED↔APPEALED loop, 5 calculations rendered as reconstruction-passing prose incl. round-half-up coinsurance, 7-step ledger identity, dual-variant charge/collection commission with per-claim rounding, remittance conservation, aging buckets with inclusive lower boundaries, both OCC rules (ERR_STALE_VERSION 412), validation priority ordering at scrub+submit, all cascades; §3 path purity pass; all 31 error IDs in narrative).

## Step 5: Generate unit tests — 2026-07-24T12:52:00.000Z

64 test functions across 8 files (+conftest); 9 test_helpers files. Queue A (Difficulty): 36 tests (all 18 non-stub instances ×2). Queue B (Corner): 28 tests (28 non-stub instances ×1). Skipped: 3 `excluded_because` corner stubs (cross-referenced to owning difficulty instances). No PRD-coverage/derivability drops. One design inconsistency resolved: `zero_patient_balance_statement_send_rejected` had `coinsurance_pct: 0.20` contradicting its own asserted `statement_amount_cents==0`; fixture built with `coinsurance_pct=0` to faithfully realize the zero-balance outcome. Every docstring carries verbatim PRD citation + one `Design:` tag.

## Step 6: Generate implementation — 2026-07-24T12:52:30.000Z

Python+Flask in workspace/implementation/ (app.py, helpers.py, logic.py, serializers.py, store.py, requirements.txt, start.sh). 62 endpoints (all PRD §4 incl. `/_clock/set_current_utc`). In-memory dicts only (no seeding — grep-confirmed). start.sh reads $PORT (default 10000), binds 0.0.0.0, foreground, guarded pip install. Single `render_dt` (`.mmmZ`) for all timestamps honoring logical clock; dashed `str(uuid4())` ids. Verified end-to-end: dual-variant reimbursement (7600 provisional vs 7000 realized), ledger conservation, OCC on posting + fee-schedule activate (ERR_STALE_VERSION 412), aging boundaries (day90 vs day91), denial/appeal cycle, SoD 403, timely-filing 422, credential auto-expire, overlap 409.

NOTE: impl reports 62 endpoints vs PRD/scaffold 63 — Step 7 will surface any genuinely missing route as a test failure.

## Step 7: Test and iterate — 2026-07-24T13:00:00.000Z

Clean 8-round parallel sweep: **64/64 passed in all 8 rounds**. Iterations: 2 (diagnostic sweep + 1 fix + confirming sweep).

Tests deleted: NONE. test_helpers/ fixes: NONE.

implementation/ fixes (1):
- `logic.py` `recompute_claim_ledger` (added `all_postings_of` helper) — `test_reversal_restores_claim_ledger_values` failed: `outstanding_balance_cents` returned 8000 vs 10000 after a posting reversal. Ledger keyed `patient_responsibility_cents` off POSTED-only postings, so after reversal PR reverted to provisional scrub estimate (2000). PRD §3.6 step 5: PR is provisional "until **any posting exists**, after which it is the final ERA value" — a reversed posting still exists, so PR must stay at the latest posting's ERA value (0). Fixed PR selection to use latest of ALL postings (POSTED or REVERSED) by created_at, falling back to provisional only when no posting ever created.

Note: initial "63/64 all-failing" appearance was a subagent summary-script artifact (used nonexistent `outcome` key; JSON uses `status`) — exactly one real bug. Endpoint 62-vs-63 note surfaced no missing route.

NOT clean (1 impl fix) → Step 8 runs.

## Step 8: Finalize PRD — 2026-07-24T13:04:00.000Z

PRD_FINALIZED.md produced (329 lines, ~0% line delta; in-line wording change only). Single pinning edit tracing to the Step 7 fix:
- §3.6 step 5 (claim ledger identity) — revise — made "any posting exists" boundary explicit: provisional scrub figure applies only until a posting has EVER been created (all statuses, so a REVERSED posting still qualifies); thereafter PR = ERA value of the claim's LATEST posting by created_at (ties → greater id), whether POSTED or REVERSED; provisional is fallback only when no posting ever existed. impl: logic.py:78-83. NO-NEW-MISMATCH search confirmed all 4 monetary recompute callsites funnel through recompute_claim_ledger (scrub, posting-create, reversal, statement recompute); statement-open reads already-recomputed PR; KPI reads outstanding/insurance_paid not PR.

## Step 9: Complete PRD — 2026-07-24T13:11:00.000Z

PRD_COMPLETED.md produced (329 lines; 50,578 → 52,978 chars, +2,400). 11 edits: 6 mismatch-revisions + 5 ambiguity-pins. No new sections. Highlights:
- §2.9 — collected_ytd_cents is cumulative insurance-paid (no calendar-year filter); expected_reimbursement_cents frozen at scrub (NOT re-derived by ledger recompute); practice AR/collected refresh advances updated_at only on change, never bumps version.
- §2.3 — list ordering ties broken by ascending id.
- §3.1 — fee-schedule activate zero-lines → ERR_VALIDATION; overlap check before OCC; supersede targets any prior ACTIVE with non-null end_date strictly < effective_date; practice-activate target_status enum/transition errors.
- §3.2 — enrollment decision enum APPROVE/REJECT; approve expiration must be strictly after clock; activate when provider not APPROVED → ERR_INVALID_STATE.
- §3.4 — close endpoint authorizes both Biller and Coder for all 3 branches.
- §3.5 — appeal outcome enum OVERTURN/UPHOLD/WITHDRAW; overturn recovered_amount_cents defaults 0.
- §3.6 — posting over-allocation check before OCC.
- §3.7 — send-statement with amount ≤ 0 → ERR_INVALID_STATE (409); record-payment leaves ledger unchanged, advances updated_at without version bump.
Already-pinned (no change): envelope, pagination defaults, round-half-up, 6 calcs + ordering, dual-variant commission, OCC fields, closed-closed vs half-open intervals, aging boundaries, timely-filing/appeal-window inclusivity, cascades, SoD, .mmmZ logical-clock timestamps.

## PIPELINE COMPLETE — 2026-07-24T13:11:30.000Z

Expert task task_1098_medical_billing_rcm_firm GREEN: 64/64 tests across all 8 stability rounds. Final PRD = PRD_COMPLETED.md. NOT clean (1 impl ledger fix: PR selection over all postings incl. REVERSED).
