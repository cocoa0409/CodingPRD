# Worklog — task_0086_unemployment_insurance_benefit

Scenario: Unemployment Insurance Benefit Application: base period wage calculation, weeks of eligibility, weekly certification (Work Search Log), employer charge (Experience Rate), Overpayment recovery, appeal, Pandemic emergency extension

Difficulty: Expert (passed to Step 2 / scaffold-generator only)

## Step 1: Create task directory — 2026-06-01T02:41:21.000Z

Skipped auto-index scan per orchestrator instructions; task directory `tasks/task_0086_unemployment_insurance_benefit/` was pre-assigned and reserved. Verified it exists with an empty `workspace/` subdirectory.

## Step 2: Generate scaffold (Expert difficulty) — 2026-06-01T03:08:30.000Z

Generated three Expert-difficulty scaffold artifacts at `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0086_unemployment_insurance_benefit/`:

**SCAFFOLD.yaml** (§1.0–§1.7)
- **Complexity profile**: primary archetype *Ledger reconciliation* + secondary *Compliance/audit*; layers = optimistic concurrency, cascading side effects, dual-variant calculation, rate/threshold triggers, derived-field reconciliation. Topology *flat*; state-machine shape *cyclic*; role model *segregation_of_duties*; consistency *immediate*.
- **12 entities**: Employer, Claimant, WageRecord, Claim, Determination, WeeklyCertification, WorkSearchContact, EmployerCharge, Overpayment, OverpaymentRecovery, Appeal, EmergencyExtensionProgram.
- **5 state machines**: Claim (compound + cyclic EXHAUSTED↔MONETARILY_ELIGIBLE via extension), WeeklyCertification (parallel adjudication × payment axes), Appeal (cyclic REMANDED↔UNDER_REVIEW), Overpayment, EmployerCharge (compensation on relieve).
- **2 concurrency rules** (OCC on Claim.version for apply-extension; on Overpayment.version for recoveries).
- **8 calculations**: base_period_wage_total (STANDARD vs ALTERNATE), monetary_qualification, weekly_benefit_amount (tiered/clamped), maximum_benefit_amount (duration- vs wage-capped), weekly_payable_amount (earnings disregard), employer_charge_allocation (largest-remainder waterfall), overpayment_penalty (fraud), extension_eligibility. All literals computed and verified in code.
- **17 validations** (priority-ordered), **54 endpoints** (incl. 2 test-driving hooks: `/_ledger/set_claim_balance`, `/_clock/set_current_utc`), **21 error codes**, **8 roles** (Anonymous, ProgramAdmin, Claimant, Adjudicator, BenefitPaymentOfficer, Employer, AppealsClerk, Referee). Top-level `constants:` block pins MIN_WORK_SEARCH_CONTACTS=3, MAX_REMANDS=2, APPEAL_WINDOW_DAYS=30.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** (§1.8): all 9 Difficulty Rules, **2 instances each = 18 total**, each grounded in §1.1–§1.6 with structured `setup_api_calls`/`trigger`/`assert` chains and pre-computed literal assertions.

**SCAFFOLD_CORNER_DESIGN.yaml** (§1.9): **50 instances across 9 sections** (40 active test recipes + 10 `excluded_because` stubs pointing at named §1.8 instances).

**Verification**: all three files parse; `scaffold_lint.py` returns `VERDICT: clean lint`; no forbidden race vocabulary; instance names unique across both design files; all stub references resolve. Modeling notes: appeal timeliness depends on determination issuance time, so appeal recipes pin the clock via `/_clock/set_current_utc`; the EXHAUSTED-at-zero boundary is structurally unreachable in <13 real pay calls, so a `/_ledger/set_claim_balance` hook keeps that fixture tractable.

Files: SCAFFOLD.yaml (1769 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1147 lines), SCAFFOLD_CORNER_DESIGN.yaml (1756 lines).

## Step 3: Copy shared files — 2026-06-01T03:08:53.000Z

Copied `INSTRUCTION.md` (1424 bytes) into `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-01T03:15:21.000Z

Generated `workspace/PRD.md` (302 lines, ~50KB) from `SCAFFOLD.yaml` only. Confirmed neither design YAML was read.

**Section list:**
- §1 Introduction (ledger-reconciliation + compliance/appeals framing)
- §2 Global Specifications & System-Wide Principles: 2.1 RBAC (8 roles), 2.2 API Response Structure (byte-identical to source), 2.3 Pagination, 2.4 Common Resource Properties & Audit Trail (WageRecord/WorkSearchContact = id+created_at only), 2.5 Nested Retrieval & Referential Integrity, 2.6 Optimistic Concurrency Control (both OCC rules), 2.7 Monetary Values/Cents/Rounding, 2.8 Derived-Balance Reconciliation, 2.9 Segregation of Duties & Operator Identity, 2.10 Validation Ordering (priority 1–17)
- §3 Business Logic & Workflows (10 lifecycle subsections incl. 3.5.1 payable amount, 3.5.2 employer-charge allocation)
- §4 Endpoint Definitions (4-column table, 54 endpoints)
- §5 Error Code Catalogue (2-column table, 21 errors)

**Hard Contract reports:** Contract 1 (field coverage) PASS — 73/73 present; Contract 2 (rule coverage) PASS — validations/OCC/state-machines/calculations/side-effects/sibling-branch symmetry all 0 missing; Path purity (§3) PASS — 0 path/method tokens in 428 backtick tokens.

## Step 5: Generate unit tests — 2026-06-01T03:30:53.000Z

**Test files:** 8 (`test_01_monetary_determination.py` … `test_08_crud_rbac_lifecycle.py`) plus `conftest.py`.

**Test functions emitted:** 76 total
- **Queue A (Difficulty):** 36 tests — all 18 instances across the 9 rules covered by ≥2 tests each.
- **Queue B (Corner):** 40 tests — all 40 non-stub instances covered by ≥1 test each. The 10 `excluded_because:` stubs correctly NOT translated; cross-references all resolve to real Queue-A instances.

**Verification (all clean):** every docstring ends with exactly one `Design:` tag (76/76); no untagged/dual-tagged/orphan tags; all 101 quoted PRD citations verbatim-match `PRD.md`; no skip/skipif/xfail; no scaffold-leakage strings; all files compile; 76 tests collect with zero errors.

**test_helpers/ files:** `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`.

**Instances skipped:** None skipped entirely. One partial-assertion narrowing flagged: `Corner/state_machines/extension_apply_restores_balance_cyclic` — instance asserts `remaining_balance_cents == 65000` after apply-extension, but PRD §2.8 (`remaining_balance = MBA − Σ(paid weeks)`, paid=5000) uniquely derives 125000, not 65000. Test generated asserting only PRD-derivable outcomes (status `MONETARILY_ELIGIBLE`, `extension_weeks_granted == 13`, `maximum_benefit_amount_cents == 130000`); dropped the contradictory `remaining_balance_cents == 65000` assertion. Corner-design/PRD mismatch on the literal, not a test gap.

## Step 6: Generate implementation — 2026-06-01T03:30:53.000Z

Complete Python + Flask implementation in `workspace/implementation/`. **54 endpoints** (full PRD §4 table incl. `/_ledger` and `/_clock` hooks).

**File list:** `start.sh`, `requirements.txt` (flask==3.0.3), `app.py` (factory + blueprints + error handlers), `db.py` (12 in-memory dicts keyed by UUID + stamp/touch), `clock.py` (server clock + `/_clock` override), `response.py` (envelope helpers), `errors.py` (ApiError + 21 error IDs), `middleware.py` (X-User-ID/X-User-Role auth + role checks), `validate.py` (parsing, pagination, OCC, round_half_up, serialization); `routes/`: parties, claims, determinations, weekly, overpayments, appeals, admin; `services/`: calculations (8 rules), claim_logic (monetary recompute + base-period selection).

**Launch:** `start.sh` is foreground bash — `set -euo pipefail`, cd to own dir, guarded install (`if ! python3 -c "import flask"`) to avoid per-reboot pip contention, then `exec python3 app.py`. `app.py` reads `$PORT` (default 10000), binds `0.0.0.0`, threaded. In-memory only, empty on every boot, no seeding/disk persistence (verified).

**PRD ambiguities resolved (noted interpretations):**
1. NONMONETARY determination outcome: PRD pins ALLOWED/DENIED for monetary only; NONMONETARY left `outcome=PENDING`, `is_appealable=true`, no claim transition. Reversal still marks `REVERSED`/non-appealable, no auto re-pay (§3.7).
2. `ERR_EXTENSION_ALREADY_APPLIED` vs `ERR_INVALID_STATE` ordering: §2.10 state check (priority 7, must be EXHAUSTED) precedes already-applied rule; already-applied 409 only reachable when claim re-exhausts after an extension (still-EXHAUSTED), where code surfaces `ERR_EXTENSION_ALREADY_APPLIED`.
3. Reversal cascade status flip unconditional: reversing a DENIED MONETARY determination flips claim to `MONETARILY_ELIGIBLE` and re-runs calcs; if recalc yields NONE, monetary fields stay 0 but status still MONETARILY_ELIGIBLE per literal prose.
4. Charge-allocation creation order: PRD pins leftover-cent tie-break but not EmployerCharge row creation order; rows created in created_at-then-insertion-seq employer order for stable deterministic stamps.

## Step 7: Run tests and iterate — 2026-06-01T03:39:47.000Z

**Iterations run:** 2 (1 diagnostic baseline + 1 fix-and-confirm). Final sweep: all 8 parallel rounds green, 76/76 each. (Orchestrator independently re-ran the 8-round sweep at 03:40 UTC to confirm and to regenerate the final `results.{1..8}.json` artifacts — all 8 rounds passed=76 failed=0 total=76.)

**Root cause (single upstream fixture bug, masquerading as 11 independent failures):** The test suite repeatedly used wage profiles that do not satisfy PRD §3.2's three-part monetary qualification test — specifically single-quarter profiles `[("2025-Q4", 130000)]` (fails the `base_total ≥ 260,000` floor) and `[("2025-Q4", 780000)]` (fails the third sub-test `2×total ≥ 3×high_quarter`, the single-quarter concentration guard). A PRD-faithful implementation correctly denies these as `MONETARILY_INELIGIBLE`, cascading into "Setup step failed: Claim is not MONETARILY_ELIGIBLE" 409s across 8 downstream tests and direct status/error mismatches in 3 others. STEP 2 test-vs-PRD consistency bug, not an implementation bug — `services/calculations.py` qualification logic matches PRD §3.2 exactly.

**Tests deleted:** None. Every failing test asserted a PRD-covered, uniquely-derivable rule; all repairable by correcting the fixture/setup to construct a PRD-qualifying precondition.

**Fixes applied to `test_helpers/`:**
- `fixtures.py` — `make_exhausted_claim`: default wage profile changed from non-qualifying single quarter `[("2025-Q4", 130000)]` to qualifying two-quarter `[("2025-Q4", 130000), ("2025-Q3", 130000)]` (total 260000 ≥ floor, hq 130000, 2×total ≥ 3×hq), so the claim reaches `MONETARILY_ELIGIBLE` before the balance hook drives it to EXHAUSTED.

**Fixes applied to `test_suite/` (all setup-faithfulness corrections, no assertion weakening):**
- `test_01` — `test_monetary_fields_visible_immediately_after_determination`: single `2025-Q4=780000` → two-quarter `Q4+Q3=130000` each (qualifies, WBA 5000); fixed contradictory comment.
- `test_02` — `test_claim_exhausts_at_exactly_zero`, `test_claim_stays_eligible_when_balance_above_zero`: single-quarter → two-quarter qualifying profile (WBA 5000 unchanged, literals unchanged).
- `test_03` — `test_assign_after_dismiss_is_invalid_state`: appeal `filed_date` `2026-06-01` (untimely → `ERR_UNTIMELY`, never SUBMITTED) → `2026-04-20` (timely, ≤ deadline 2026-05-10); DISMISSED reached via clerk dismissing a timely SUBMITTED appeal, post-dismiss assign correctly returns `ERR_INVALID_STATE`.
- `test_06` — `test_adjudicate_eligible_succeeds_once_claim_is_eligible`: single `780000` → two-quarter qualifying profile.
- `test_07` — five tests: `test_apply_extension_restores_eligibility_and_grows_mba` (profile fixed; corrected MBA assertion from underivable 130000 to PRD-derivable `130000 + 13×5000 = 195000`), `test_apply_extension_outside_window_rejected`, `test_apply_extension_stale_claim_version_rejected`, `test_adjudicate_eligible_not_able_available_rejected`, `test_work_search_insufficient_rejected`, `test_pay_against_exhausted_balance_rejected`: all switched to two-quarter qualifying profile.

**Fixes applied to `implementation/`:** None. Implementation was already PRD-faithful; touching it would have meant weakening a PRD-required qualification check to accommodate non-qualifying fixtures (forbidden by cardinal rules).

## Step 8: Finalize PRD — 2026-06-01T03:44:13.000Z

Not skipped (Step 7 had nonzero test_helpers/ + test_suite/ fixes, so the all-four-zero skip condition did not apply).

**Result:** `PRD_FINALIZED.md` created via the step-0 copy and is **byte-identical to PRD.md** (302 lines each, 0% delta, `diff` empty). No edits were warranted.

**Rationale:** Every `<step_7_diff>` item was a fixture/setup faithfulness correction, not a PRD silence or PRD/impl mismatch. Each was traced to impl behavior that PRD already uniquely determines:
- §3.2 monetary qualification (test_01/02/06/07 + fixtures.py) — PRD.md:147 pins all three sub-tests incl. `2×total ≥ 3×high_quarter`; matches `services/calculations.py:84-114`. Pure fixture bug.
- §3.6 MBA growth on extension (test_07, MBA=195000) — PRD.md:157/185 pins base MBA + `extension_weeks_granted × WBA` without re-rounding; matches `routes/claims.py:153`, `services/calculations.py:145-148`.
- §2.8 remaining_balance recompute (Step 5 note, 125000 not 65000) — PRD.md:115 pins `MBA − Σ(payable of paid weeks)`; matches `routes/claims.py:161-167`. Dropped literal was a test bug.
- §3.7 appeal timeliness / assign-after-dismiss (test_03) — PRD.md:191/193 pins 30-day deadline, untimely→ERR_UNTIMELY, dismiss from SUBMITTED, assign from SUBMITTED/REMANDED only; matches `routes/appeals.py`.

Pre-edit search: no edits committed; enumerated subjects (monetary qualification, WBA/MBA derivation, extension apply, remaining-balance recompute, appeal state machine) all consistent with existing PRD prose. Valid "PRD already fully determines behavior" outcome.

## Step 9: Complete PRD — 2026-06-01T03:49:03.000Z

Full PRD-vs-implementation completeness scan starting from `PRD_FINALIZED.md`.

**Source vs completed:** `PRD_FINALIZED.md` 302 lines / 50,086 chars → `PRD_COMPLETED.md` 302 lines / 52,110 chars (char delta +2,024; line count unchanged — all edits in-paragraph inserts/revisions, no new sections).

**Counts:** 7 changes — 6 ambiguity-pins, 1 mismatch-revision.

**Per-change bullets:**
- §2.1 (RBAC) — insert — ambiguity — present-but-unrecognized `X-User-Role` → `ERR_UNAUTHENTICATED` before any role check; "missing" includes blank — `middleware.py:42-45`
- §3.2 (Monetary Determination) — revise — mismatch+ambiguity — pinned NONMONETARY behavior (no state precondition, no calc, both wage figures 0, no claim transition, `outcome` PENDING) and corrected `is_appealable`: true on creation regardless of outcome, false only on reversal; `appeal_deadline_date` always set for both types — `determinations.py:40-83`
- §3.5 (Weekly Certification) — insert — ambiguity — `work_search_waived` boolean defaulting to false, persisted and returned — `weekly.py:73-91`
- §3.5.2 (Charge Allocation) — insert — ambiguity — deterministic charge-creation order (charged employer's `created_at` ascending, then insertion order), governing charges' own `created_at` and default list ordering — `weekly.py:293-307`
- §3.8 (Overpayments/Recovery) — insert — ambiguity — `weekly_certification_id` required for OFFSET recovery (`ERR_INVALID_REQUEST` if absent); when supplied under either method must resolve to existing cert (`ERR_NOT_FOUND`) — `overpayments.py:86-95`
- §3.9 (Charge Protest/Relief) — insert — ambiguity — protest by non-owning employer → `ERR_FORBIDDEN_ROLE`, evaluated after charge existence (`ERR_NOT_FOUND`) but before POSTED state check — `weekly.py:349-352`
- §3.10 (Admin Test Hooks) — insert — ambiguity — `set_claim_balance` error codes/ordering: negative → `ERR_INVALID_REQUEST`; non-MONETARILY_ELIGIBLE → `ERR_INVALID_STATE` (after field-shape, before at-most-maximum check); above max → `ERR_INVALID_REQUEST` — `claims.py:205-211`

Implementation otherwise matched the finalized PRD on all major behaviors (base-period selection order, WBA/MBA formulas+rounding, earnings disregard, largest-remainder allocation tie-breaks, OCC required/optional/generic split, reversal cascade, validation ordering, derived-balance reconciliation).

---

## Pipeline complete

All 9 steps done. Final state: 76/76 tests pass across all 8 parallel stability rounds. Task tree contains SCAFFOLD (+ 2 design YAMLs), PRD.md / PRD_FINALIZED.md / PRD_COMPLETED.md, test_helpers/, test_suite/ (8 files, 76 tests), workspace/implementation/ (Flask, in-memory, 54 endpoints), and results.{1..8}.json (all passing).
