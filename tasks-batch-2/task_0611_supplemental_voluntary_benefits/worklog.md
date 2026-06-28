# Worklog — task_0611_supplemental_voluntary_benefits

## Step 1: Create Task Directory — 2026-06-21T17:22:05.000Z

Created `tasks/task_0611_supplemental_voluntary_benefits/` with `workspace/` subdirectory at the pre-allocated path (auto-indexing skipped per orchestrator instruction; 5 sibling pipelines running in parallel).

## Step 2: Generate Scaffold (Expert band) — 2026-06-21T17:42:55.000Z

All three scaffold artifacts are complete, internally consistent, and pass `scaffold_lint.py` cleanly at the Expert band.

## Summary

Generated the full scaffold for **task_0611_supplemental_voluntary_benefits** (Aflac-style supplemental & voluntary benefits) at the **Expert** difficulty band. All three files written and lint-clean.

**Files written** (all at `/home/ubuntu/github/CodingPRD/tasks/task_0611_supplemental_voluntary_benefits/`):
- `SCAFFOLD.yaml` (§1.0–§1.7, no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

**Complexity profile:** primary archetype *ledger reconciliation* + secondary *compliance/audit*; **flat** entity topology (peer collections under `/benefits` linked by FKs); **parallel** state-machine shape; role model *peer_roles*; consistency *immediate*.

**Entities (12):** Employer, PlanProduct, BenefitScheduleItem, EnrollmentPeriod, Employee, DisbursementAccount, Enrollment, PayrollDeduction, Claim, Disbursement, PortabilityConversion, Section125Election.

**State machines (6):**
- **Enrollment** — *parallel* dimensions: lifecycle (PENDING→ACTIVE→TERMINATED→PORTED / DECLINED) × funding (UNFUNDED↔CURRENT↔LAPSED, *cyclic*).
- **Claim** — *branching-with-revert* (SUBMITTED→UNDER_REVIEW→{APPROVED,DENIED}; APPROVED→{PAID,VOIDED,UNDER_REVIEW reopen}).
- **Disbursement** (INITIATED→SETTLED→RETURNED), **PlanProduct**, **EnrollmentPeriod** (linear), **Section125Election** (LOCKED→REVOKED on qualifying-life-event cascade).

**Key calculations (6):** `premium_assessment` (GI vs EOI dual variant), `deduction_conversion` (tiered floor by pay frequency), `claim_adjudication` (provisional vs adjudicated dual variant; waterfall cap/lifetime limiting; wellness bypass), `portability_premium` (load-up on product base), `lapse_evaluation` (3-consecutive-FAILED threshold), `employee_total_deduction` (aggregation).

**Validations / errors:** 16 ordered validation rules; **24 error codes** (all referenced ≥2×).

**Endpoints:** **50** (flat collections + action endpoints + reverse-reachability GETs + `/_clock/set_current_utc` test-driving endpoint with mandatory `2026-01-01T00:00:00Z` default).

**Roles (5):** BenefitsAdmin, ClaimsAdjuster (both `opaque`), Employee (`entity_backed:Employee`), Payroll, System.

**Concurrency:** 1 OCC rule (`port-create-stale-enrollment`, 412 on stale `expected_enrollment_version`).

**Design coverage:** §1.8 = 9 rules × 2 = **18 difficulty instances**; §1.9 = **30 active corner instances + 3 excluded_because stubs** across all 9 claim-extraction sections.

**Verification:** `scaffold_lint.py` → `VERDICT: clean lint` (564 calls scanned, 0 violations).

## Step 3: Copy Shared Files — 2026-06-21T17:42:55.000Z

Copied `INSTRUCTION.md` → `tasks/task_0611_supplemental_voluntary_benefits/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-21T17:48:19.000Z

Generated `workspace/PRD.md` from `SCAFFOLD.yaml` (270 lines). Neither design file was read.

**Section list:**
- §1 Introduction (employer/carrier/employee tri-party; ledger-reconciliation + compliance themes; logical-clock determinism)
- §2 Global Specs: 2.1 RBAC (5 roles), 2.2 Response Structure, 2.3 Pagination, 2.4 Identity/Timestamps/Versioning, 2.5 Logical Clock, 2.6 Monetary Precision/Basis-Point, 2.7 Cross-Aggregate Referential Consistency, 2.8 Parallel State Dimensions, 2.9 OCC on Portability, 2.10 Validation Ordering (priority 1–16)
- §3 Business Logic & Workflows (10 lifecycle subsections)
- §4 Endpoint Definitions (4-column, 51 endpoints)
- §5 Error Code Catalogue (2-column, 24 error IDs)

**Hard Contracts:** Contract 1 (Field-Name Coverage) 54/54 entity fields + 42/42 inputs + 12/12 path params — 0 missing. Contract 2 (Rule Coverage) all 24 errors, all transitions, all 6 calculations, cascades/compensations, OCC rule, validation ordering — 0 missing. Contract 3 (§3 Path Purity) 343 backtick tokens, 0 violations.

Confirmation: neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was read.

## Step 5: Generate Unit Tests — 2026-06-21T17:58:48.000Z

Generated test infrastructure following the design-index-only contract.

**Test counts:** 7 test files (`test_01`–`test_07`) + `conftest.py`. **66 tests total**, each carrying exactly one verbatim `Design:` tag.
- Queue A (Difficulty): 36 tests — all 18 difficulty instances covered ×2 each.
- Queue B (Corner): 30 tests — all 30 non-stub corner instances covered ×1 each.

**Instances skipped:** 3 corner stubs (`excluded_because:`) correctly not translated; cross-refs resolve to real difficulty instances (reopen_paid_claim → claim_branch_revert; premium_variants_diverge → premium_gi_vs_eoi; get_disbursements_filtered_by_claim → disburse_cascades). **No PRD-filter skips** — every non-stub instance passed the two-condition filter.

**test_helpers/ files:** `__init__.py`, `types.py` (BenefitScheduleItem omits version/updated_at), `api_client.py`, `api_errors.py` (24-error catalog), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (Employee entity_backed; 4 opaque roles), `fixtures.py` (5-tier composite setup). All 66 tests collect cleanly; no skip/xfail markers.

## Step 6: Generate Implementation — 2026-06-21T17:58:48.000Z

Built Python + Flask implementation in `workspace/implementation/` (18 files).

**Files:** `start.sh`, `requirements.txt`, `app.py`, `clock.py`, `db.py`, `errors.py`, `response.py`, `middleware.py`, `validation.py`, `calculations.py`, `serializers.py`, `services.py`, `routes/` (clock, employers, plan_products, enrollment_periods, employees, enrollments, claims).

**Endpoints:** 50 route handlers covering all 49 PRD endpoint-table rows.

**State machines:** parallel Enrollment dimensions (lifecycle PENDING→ACTIVE→TERMINATED→PORTED/DECLINED × funding UNFUNDED↔CURRENT↔LAPSED via `_recompute_funding`, 3-consecutive-FAILED lapse); Claim branching-with-revert (reopen/void/return all credit benefit_paid_cents back, wellness excluded); Section125 lock/revoke cascade.

**Calculations:** isolated in `calculations.py` using Decimal (bps half-up, deductions floor); adjudication caps non-wellness at remaining annual room, wellness uncapped/off-ledger.

**Validation precedence (§2.10):** auth(1)→forbidden(2)→not_found(3)→reference_mismatch(4)→state(5)→section125(6)→event_before_coverage(7)→event_not_covered(8)→account_not_verified(9)→lifetime_max(10)→benefit_exhausted(11)→not_funded(12)→already_ported(13)→stale_version(14,412)→duplicate(15)→invalid_request(16).

**start.sh:** reads `$PORT` (default 10000), binds `0.0.0.0`, foreground via `exec`, in-memory dict storage only. Verified boots clean with empty store.

## Step 7: Run Tests and Iterate — 2026-06-21T18:20:01.000Z

The workspace is clean and the task is complete. All tests pass across three consecutive 8-round parallel stability sweeps (plus an orchestrator-run confirming 8-round sweep: 8/8 rounds 66/66).

## Summary

**Iterations run:** 4 sweep iterations (1 baseline + 3 confirmation). The baseline exposed one consistent logic failure plus load-induced flakiness; after fixes, three back-to-back 8-round sweeps (24 rounds, 1584 test executions) were all 66/66 green.

**Tests deleted:** None. Every assertion traced verbatim to PRD prose and was uniquely derivable.

**Fixes applied to `test_helpers/`:** None. The fixtures, factories, and role-header helpers were all PRD-faithful.

**Fixes applied to `implementation/`:**

1. `routes/enrollments.py` — `create_enrollment()`: Removed an unwarranted `ERR_SECTION125_INACTIVE` check at enrollment **creation** time. This was a real bug: PRD §3.5 (creating an enrollment) imposes no Section-125 active-plan gate — the `pretax` flag is merely recorded — while PRD §3.6 places the gate solely at **activation**. The spurious creation-time check made the setup of `test_pretax_activate_blocked_when_section125_inactive` fail (the test needs a pretax PENDING enrollment on an inactive-§125 employer in order to then assert the gate fires at activation). The check correctly remains at activation. This was the only failure consistent across all 8 baseline rounds.

2. `app.py` + `requirements.txt` + `start.sh` — Switched the foreground server from the Werkzeug development server to **waitress** (with a Werkzeug fallback if waitress is unimportable). The remaining baseline failures were pure infrastructure flakiness ("API server could not be restarted before <test>" and "RemoteDisconnected / Connection reset by peer"), randomly scattered across different tests every round — the signature of the dev server being too slow/fragile to bind within the runner's 15s per-test restart window under the 8× concurrent peak load. Waitress boots to responding in ~0.26s and serves robustly under the rapid kill/restart cadence. Also: `start.sh` now gates the dependency-install behind a one-time marker file (avoiding an extra `python3 -c "import ..."` interpreter spawn on every per-test reboot), and `app.py` silences the werkzeug access log. Storage remains in-memory only; no entity data is seeded at startup.

**Key finding:** The lone genuine logic defect was a misplaced PRD-priority-6 check (Section 125) applied one workflow step too early. All other instability was environmental and resolved by hardening the boot/serve path, not by touching test logic.

## Step 8: Finalize PRD — 2026-06-21T18:21:58.000Z

PRD_FINALIZED.md created as a verbatim copy of PRD.md. **Line counts:** PRD.md = 270, PRD_FINALIZED.md = 270. **Delta: 0 lines (0%) — no edits.**

**Rationale:** The two `<step_7_diff>` items produce neither PRD silence nor PRD/impl mismatch:
- Item 1 (`create_enrollment()` Section-125 check removal): the fix made the implementation conform to an *already-correct, unambiguous* PRD (§3.5 records `pretax` flag with no gate; §3.6 places the gate solely at activation). PRD already uniquely determines this — nothing to pin.
- Item 2 (waitress / install marker / access-log): infrastructure-only, no behavioral PRD impact; not patched per method.

**Pre-edit search log:** Subject = Section-125 gate + `pretax` flag across enrollment lifecycle. Enumerated/read create_enrollment (no gate, flag recorded), activate_enrollment (gate at routes/enrollments.py:171-172; LOCKED Section125Election created), terminate cascade, Section125 read endpoints. All consistent with existing §3.5/§3.6/§2.10 prose. No wording adjustment — no edit made. PRD_FINALIZED.md verified byte-identical to PRD.md via diff.

## Step 9: Complete PRD — 2026-06-21T18:29:31.000Z

PRD_COMPLETED.md produced via full PRD-vs-implementation completeness scan.

**Source vs. completed:** PRD_FINALIZED.md = 270 lines / 42,915 chars; PRD_COMPLETED.md = 270 lines / 46,616 chars. Char delta **+3,701**; line count unchanged (all in-paragraph edits, no new sections).

**Counts:** 13 lines revised — **9 ambiguity-pins, 4 mismatch-revisions**.

**Per change:**
- §2.4 — insert — ambiguity — `created_at`/`updated_at` minted from logical clock; `version` begins at 1 — db.py:32-40,62-69
- §2.5 — insert — ambiguity — missing/non-ISO `to_iso8601` → `ERR_INVALID_REQUEST`; success 200 empty data — routes/clock_route.py:22-30
- §2.7 — revise — mismatch — claimed-event-not-resolving → `ERR_EVENT_NOT_COVERED` (only account-to-enrollee mismatch is `ERR_REFERENCE_MISMATCH`) — routes/claims.py:50-65
- §2.8 — revise — mismatch — employee-aggregate recompute driven by activation/termination, not funding lapse — routes/enrollments.py:277-306, services.py:118-141
- §2.8 — insert — mismatch — payroll posting bumps enrollment `version`/`updated_at` only when `funding_status` changes value — routes/enrollments.py:302-306
- §2.10 — insert — ambiguity — required-body-field validation runs inline; unlisted 409 gates placed at state-eligibility slots — routes/* (enrollments.py:33-77, claims.py:35-46, plan_products.py:96-117)
- §3.2 — insert — ambiguity — DRAFT-state check precedes schedule-empty check on open — routes/plan_products.py:96-100
- §3.3 — insert — ambiguity — `gi_window_end ≤ gi_window_start` → `ERR_INVALID_REQUEST`, before employer existence — routes/enrollment_periods.py:44-49
- §3.4 — insert — ambiguity — duplicate email among EMPLOYED staff → `ERR_INVALID_REQUEST` — routes/employees.py:40-44
- §3.4 — revise — mismatch — total deduction recomputed on activate/terminate only; sums lifecycle-ACTIVE enrollments irrespective of funding_status — services.py:77-86
- §3.4 — insert — ambiguity — `account_last4` required non-empty string, no format check; routing format check precedes employee existence — routes/employees.py:113-122
- §3.6 — insert — ambiguity — Section125Election `plan_year_label` = year of `benefit_year_start` (fallback `enrolled_at`); `qualifying_event` init null — routes/enrollments.py:181-206
- §3.8 — insert — ambiguity — claim carries `denial_reason`, init null at filing — routes/claims.py:79
- §3.9 — insert — ambiguity — voiding does not zero `approved_cents` (retained on VOIDED record) — routes/claims.py:235-244
- §3.10 — insert — ambiguity — conversion records and echoes `expected_enrollment_version` — routes/enrollments.py:341-347

**Notable resolution:** §2.7's "covered event must resolve … `ERR_REFERENCE_MISMATCH`" conflicted with §3.8/§2.10's `ERR_EVENT_NOT_COVERED`; impl uses the latter, so §2.7 revised toward impl.

---

## Pipeline Complete — 2026-06-21T18:29:31.000Z

Final state: 66/66 tests pass across an orchestrator-confirmed 8-round parallel sweep (8/8 rounds green, results.{1..8}.json persisted). All 9 steps complete. Task at Expert difficulty band.
