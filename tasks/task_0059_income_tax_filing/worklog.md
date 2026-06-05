# Worklog — task_0059_income_tax_filing

## Step 1: Create task directory — 2026-05-30T15:55:00Z

Created `tasks/task_0059_income_tax_filing/` and `tasks/task_0059_income_tax_filing/workspace/`.

## Step 2: Generate scaffold — 2026-05-30T16:14:00Z

Generated three lint-clean scaffold artifacts for **task_0059_income_tax_filing** at **Expert** difficulty: `SCAFFOLD.yaml` (§1.0–§1.7), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8), `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9).

**Complexity profile**: Ledger-reconciliation primary (two valid tax algorithms diverge) + Compliance/audit secondary; hybrid topology; cyclic state-machine shape; segregation-of-duties roles; immediate consistency. Layers: optimistic concurrency, dual-variant calculation, cascading side effects, rate/threshold triggers.

**Scaffold contents**:
- **9 entities**: Taxpayer, TaxReturn (aggregate root), IncomeDocument (W-2/1099 variants), Schedule (A/B/C/D/E), Dependent, CreditClaim (EITC/CTC/AOTC), EstimatedTaxPayment, EFilingSubmission, AmendedReturn (1040X, self-referential to TaxReturn).
- **3 state machines**: TaxReturn (cyclic — REJECTED→DRAFT revision loop, READY↔DRAFT, FILED→AMENDED), EFilingSubmission (branching TRANSMITTED→{ACCEPTED,REJECTED}), AmendedReturn (guarded DRAFT→FILED). Plus 2 OCC concurrency rules (stale-version on efile-create and amend-create).
- **4 calculations**: compute_return_tax (tiered brackets, standard-vs-itemized variants, round-per-tier-then-sum pinned), compute_credit_allowance (CTC/AOTC/EITC with phase-outs, two-step floor order pinned), compute_capital_gain (Schedule D net with loss limit), compute_underpayment_penalty (current-year vs prior-year safe-harbor variants).
- **16 validations** (priority-ordered), **27 endpoints**, **18 error codes**, **3 roles** (Taxpayer entity-backed, Preparer entity-backed, IrsGateway opaque).

**Difficulty design**: 9 rule_ids × 2 instances = **18 instances**, all formula-derived asserts pre-computed as exact integer-cent literals.

**Corner design**: **42 instances** (38 active test recipes + 4 `excluded_because:` stubs pointing to §1.8 instances).

**Lint**: clean — all §1.8/§1.9 calls conform to §1.5 and all FKs have reverse-reachability GETs.

## Step 3: Copy shared files — 2026-05-30T16:15:13Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-05-30T16:22:00Z

Generated `workspace/PRD.md`. Structure: 5 top-level sections, 16 subsections, ~226 lines.
- §1 Introduction (ledger-reconciliation + compliance-workflow framing)
- §2 Global Specs (9 subsections: RBAC all 3 roles, §2.2 envelope, pagination, common props, monetary/cents/rounding, nested retrieval & existence ordering, hierarchical consistency & compute-invalidation, OCC both write endpoints + ERR_STALE_RETURN_VERSION/412, validation ordering priority 1–16)
- §3 Business Logic (7 subsections: lifecycle, dual-variant compute with pinned round-per-tier-then-sum + AOTC floor-then-percent order, e-file reject/reopen loop, amendment 3-hop cascade, conserved-quantity invariants)
- §4 endpoint table (27 endpoints), §5 error catalogue (16 errors).

Hard Contracts: Contract 1 (Field-Name Coverage, 65 identifiers) PASS; Contract 2 (Rule Coverage) PASS; Contract 3 (§3 Path Purity) PASS. Neither design-index file was read.

## Step 5: Generate unit tests — 2026-05-30T16:42:00Z

test_helpers/ (9 files): types.py, api_client.py (27 endpoints), api_errors.py (16 errors + HTTP map), assertions.py (+ assert_balance_due_ledger_reconciles), factories.py, constants.py, test_users.py (Taxpayer/Preparer entity_backed identity threading), fixtures.py (tiered chains), __init__.py.
test_suite/: conftest.py + 5 test files, **74 tests**:
- test_01_tax_computation.py (15), test_02_estimated_tax_status.py (4), test_03_filing_lifecycle.py (22), test_04_validations.py (15), test_05_entities_rbac_concurrency.py (18).
Coverage: Queue A (Difficulty) all 18 instances (≥2 tests each); Queue B (Corner) all 38 non-stub instances (≥1 test each); 4 excluded_because stubs correctly not translated. No instances skipped. 110 PRD citations verified verbatim. Every docstring has exactly one Design: tag; no skip/xfail.

## Step 6: Generate implementation — 2026-05-30T16:42:00Z

Built Python + Flask in-memory REST API in workspace/implementation/.
Files: start.sh (reads $PORT default 10000, installs deps, exec python3 app.py), requirements.txt (Flask 3.0.3), app.py, db.py (in-memory Store, UUID ids, created_at/updated_at/version, ms ISO timestamps), errors.py, response.py, middleware.py (auth), util.py, serialize.py, services/compute.py (tax engine), services/common.py, routes/ (taxpayers, tax_returns, children, estimated_payments, efilings, amended_returns).
Key logic: marginal bracket tax (round-per-tier-then-sum), standard/itemized variants, Schedule D loss cap (−$3,000), CTC/AOTC/EITC with AOTC phase-out + floor-then-40% order, safe-harbor (current vs prior-year 100/110%), 8% underpayment penalty, OCC (expected_return_version → ERR_STALE_RETURN_VERSION 412), READY→DRAFT compute invalidation, reject-and-reopen payment-neutral loop, 3-hop amendment cascade with balance-due identity, half-open vs closed interval overlap, RBAC/ownership.
Storage in-memory only (no SQLite/disk, no seeding). start.sh reads $PORT, binds 0.0.0.0, foreground via exec.

## Step 7: Run tests and iterate — 2026-05-31T00:55:00Z

The first long-lived diagnostic subagent flaked under heavy host contention (3 sibling /prd-bench-entrance pipelines — tasks 0056/0057/0058 — running concurrent 8-way sweeps on the same machine) and exited without writing results. Orchestrator drove the loop directly instead.

- Single probe round: **74/74 passed**.
- Mandated 8-round parallel stability sweep: **all 8 rounds 74/74 green** (results.1.json … results.8.json), zero flakiness across rounds.

**Iterations run:** 0 beyond baseline. The implementation passed clean on the very first full 8-round sweep.
**Tests deleted:** 0.
**Fixes applied to test_helpers/:** 0.
**Fixes applied to test_suite/:** 0.
**Fixes applied to implementation/:** 0.

PRD.md already uniquely determined every behavior the 74-test suite exercises.

## Step 8: Finalize PRD — SKIPPED — 2026-05-31T00:55:00Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite fixes, 0 test_helpers fixes, 0 implementation fixes. No `PRD_FINALIZED.md` produced. Step 9 starts from `PRD.md`.

## Step 9: Complete PRD — 2026-05-31T01:18:00Z

Produced `workspace/PRD_COMPLETED.md` from `PRD.md` (no PRD_FINALIZED.md since Step 8 skipped).
Line counts: PRD.md 225 lines / 39,315 chars → PRD_COMPLETED.md 225 lines / 42,069 chars (Δ +2,754 chars, all inline; no new lines/sections).
Counts: **8 ambiguity-pins, 2 mismatch-revisions** (10 edits).
- §2.1 RBAC — insert — ambiguity — create-TaxReturn/AmendedReturn body taxpayer_id ≠ X-User-ID → ERR_NOT_RESOURCE_OWNER (after FK checks); list endpoints owner-scoped.
- §2.6 — insert — ambiguity — ERR_RETURN_NOT_FOUND also covers unresolved Taxpayer/EstimatedTaxPayment id and unrecognized routes.
- §2.7 — revise — ambiguity — recording EstimatedTaxPayment bumps version/updated_at but does NOT reset READY→DRAFT.
- §3.1 — insert — ambiguity — duplicate email → ERR_INVALID_REQUEST (422).
- §3.2 — revise — mismatch — qualified_dividends_cents ≤ box_amount_cents (≥0) validation runs for all doc_types; value used at compute only if 1099-DIV.
- §3.5 — insert — ambiguity — compute only from DRAFT/READY; FILED/REJECTED/AMENDED → ERR_INVALID_STATE before income-doc/Sched A checks.
- §3.6 — insert — ambiguity — reopen from non-REJECTED → ERR_INVALID_STATE before edits; field-only PATCH allowed from any status, never changes status, always bumps version.
- §3.7 — insert — ambiguity — amendment-create validation order: original-filed → OCC version → correction-window overlap.
- §3.7 — insert — ambiguity — safe_harbor_used literal values "current_year"/"prior_year".
- §3.7 — revise — mismatch — penalty exposed only via GET estimated-tax-status, not at e-file; e-file freezes only snapshot_balance_due_cents, persists no penalty.

## Pipeline complete — 2026-05-31T01:18:00Z

All steps done. Final state: 74/74 tests pass across all 8 stability rounds. Artifacts: SCAFFOLD.yaml + 2 design indices, PRD.md, PRD_COMPLETED.md (Step 8 skipped), test_helpers/ (9 files), test_suite/ (5 files, 74 tests), workspace/implementation/ (Flask in-memory API).
