# Worklog — task_0284_private_disability_income_insurance

## Step 1: Create task directory — 2026-06-10T00:00:00.000Z

Created `tasks/task_0284_private_disability_income_insurance/` and `workspace/` subdirectory. Index 0284 is PRE-ASSIGNED/RESERVED (not auto-scanned) to avoid collision with concurrent runs. Scenario: Private Disability Income Insurance (occupation class/risk, benefit amount & period, elimination/waiting period, own-occ vs any-occ, residual/partial benefit, COLA rider, claim & continued-disability proof, offset SSDI/workers comp). Difficulty: Expert.

## Step 2: Generate scaffold (Expert) — 2026-06-10T00:00:00.000Z

Generated SCAFFOLD.yaml (1094 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1280 lines), SCAFFOLD_CORNER_DESIGN.yaml (1592 lines). All pass scaffold_lint.py with VERDICT: clean lint (515 calls scanned across §1.8+§1.9, all FK reverse-reachability satisfied).

Design decisions:
- Archetype: Ledger reconciliation (primary) + Compliance/audit (secondary). Topology: flat (api_prefix /disability; peer collections + shallow Claim sub-resources) — chosen so the lint's FK reverse-reachability check derives collection segments from two-segment single-resource GETs. Claim sub-resource path placeholder is `{id}` (lint hardcodes `{id}`).
- State-machine shape: parallel — Claim cyclic (UNDER_REVIEW↔PENDING_INFO revision loop + APPROVED↔SUSPENDED); Policy carries two independent dimensions (lifecycle_status × premium_status).
- Layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, scheduled_actions. Role model: peer_roles.

SCAFFOLD.yaml counts: 10 entities (Insurer, OccupationClass, Policyholder, Policy, Claim, IncomeReport, DisabilityProof, BenefitPeriod, OffsetAward, ClaimLedger); 4 state machines; 5 calculations (residual_benefit_factor, gross_benefit_cents, net_benefit_cents, claim_ledger_totals, claim_window_months); 13 ordered validations; 44 endpoints (incl. /clock/advance test driver); 35 error codes; 4 roles; 1 concurrency rule (OCC on Claim.version for IncomeReport supersede, 412).

Key mechanics: dual-variant residual factor (proportionate vs presumptive-total at 0.20/0.80 income-loss thresholds), COLA-compounded gross with min() cap at 2.0×, offset waterfall with pinned evaluation order and max(0,…) floor, provisional-vs-final offset reconciliation booking overpayment via final_monthly_offset_cents, benefit-month exhaustion. Half-open BenefitPeriod months (touching allowed) vs closed OffsetAward windows (touching collides) — two distinct interval semantics.

§1.8: 9 difficulty rules × 2 = 18 instances, literal-pinned asserts. §1.9: 33 active corner instances + 6 excluded_because stubs across entities, state machines, calculations, validations, endpoints, errors, RBAC, OCC, consistency model.

## Step 3: Copy INSTRUCTION.md — 2026-06-10T00:00:00.000Z

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-06-10T00:00:00.000Z

Generated workspace/PRD.md (307 lines, prose PRD for Private Disability Income Insurance API at /disability). Read SCAFFOLD.yaml only; both design YAMLs withheld (not opened).

Section structure: §1 Introduction; §2 Global Specs (10 subsections: RBAC, Response Structure, Pagination, Deterministic Insurer Clock, Common Resource Properties, Precision/Rounding/Monetary, OCC on Income Recertification, Validation Ordering & Nested-Resource Resolution, Field-Shape Validation, Cascades/Conservation/Hierarchical Consistency); §3 Business Logic (12 subsections, lifecycle+cross-cutting); §4 endpoint table (43 endpoints, 4 columns); §5 error table (35 errors, 2 columns).

Rendered: 10 entities (Insurer, OccupationClass, Policyholder, Policy [parallel lifecycle_status × premium_status], Claim [cyclic], IncomeReport, DisabilityProof [common_fields:false — only id+created_at], BenefitPeriod, OffsetAward, ClaimLedger). State machines: Policy lifecycle+premium axes; Claim full cycle (DRAFT…APPROVED↔SUSPENDED, BENEFIT_EXHAUSTED/CLOSED/DENIED); BenefitPeriod ACCRUED→REVERSED; OffsetAward ESTIMATED→FINALIZED→VOID. Calculations: residual_benefit_factor (proportionate & presumptive-total, MIN_LOSS_RATIO 0.20, PRESUMED_TOTAL_RATIO 0.80, tie-break by created_at); gross_benefit_cents (COLA compounding capped 2.0, two half-up roundings); net_benefit_cents waterfall (pinned order, WORKERS_COMP-before-SSDI, floor 0); claim_ledger_totals; claim_window_months (ceil over 30 days/month, PROOF_INTERVAL_MONTHS 3). Validations priorities 1–13 (offset priority-6 parent-state gate before priority-8 overlap called out). OCC rule: income-report write requires expected_claim_version matching claim version → ERR_STALE_CLAIM_VERSION (412).

Hard Contracts mechanically verified: Contract 1 (Field-Name Coverage) 54/54 PASS; Contract 2 (Rule Coverage, all 35 errors reachable) PASS; Contract 3 (§3 Path Purity, 351 tokens, 0 paths/methods) PASS.

Notable scattering: next_proof_due_month introduced at filing (§3.4, default 0), set at approval (§3.6), advanced by proofs (§3.6) — across 3 subsections. Offset OCC expected_claim_version belongs to income-report write, not offset create. Constants in narrative (three months, 30 days per month, never more than double). Conservation invariant abstract in §2.10, concrete in reversal/benefit-void/offset-void cascades.

## Step 5: Generate unit tests — 2026-06-10T00:00:00.000Z

Generated test infrastructure under design-index-only contract. Test files: 6 (+conftest.py), 69 tests total.
- test_01_policy_setup.py (13): policy creation/system-fields, field-shape validation, not-found, listing/pagination, clock advance, RBAC+auth
- test_02_claim_lifecycle.py (13): review cycle, parallel policy dimensions, invalid transitions, terminal lockdown, activation/termination cascades, premium guards, OCC supersede
- test_03_benefit_calculations.py (9): residual-factor variants, COLA-compounded gross, net waterfall, offset summation, residual zero-benefit boundary, immediate consistency
- test_04_accrual_and_offsets.py (9): accrual gating (proof currency, residual report), temporal-overlap semantics, offset finalize guard, benefit-period void
- test_05_cascades_and_invariants.py (9): transitive cascades, conservation invariants, cross-entity state deps, validation-priority conflicts, elimination >= boundary
- test_06_difficulty_supplemental.py (16): second distinct-facet test per difficulty instance

Coverage: Queue A (§1.8 Difficulty) 18/18 instances all ≥2 tests → 36 tests; Queue B (§1.9 Corner) 33/33 non-stub instances all ≥1 test → 33 tests; 6 excluded_because stubs NOT translated. Instances SKIPPED under PRD-first filter: 0 (every non-stub instance had verbatim PRD coverage + uniquely-derivable outcomes).

test_helpers/ files (9): __init__.py, types.py (DisabilityProof omits updated_at/version per common_fields:false), api_client.py, api_errors.py (35-error catalog), assertions.py, factories.py, constants.py, test_users.py (make_policyholder_headers entity-backed builder), fixtures.py (5 tiers). Audits passed: 85 PRD citations verbatim-match; single Design: tag per test; no skip/xfail; all files byte-compile; imports resolve; framework signatures confirmed against installed prd_bench_local_runner.testing.

## Step 6: Generate implementation — 2026-06-10T00:00:00.000Z

Built Python + Flask implementation in workspace/implementation/. Files: start.sh (guarded launcher, reads $PORT default 10000, binds 0.0.0.0, exec python3 app.py foreground), requirements.txt (flask==3.0.3), db.py (in-memory Store singleton, dicts keyed by id, new_id(), utc_now_iso() ms precision, monotonic _seq counter for tie-breaks, NO seeding), errors.py (ApiError + 35 codes), response.py (fixed envelope), middleware.py (auth + require_role), calc.py (Decimal calcs), services.py (entity views, touch(), income-report effective-basis, offset resolution, pricing, ledger, conserved benefit_months_consumed), app.py (44 routes).

Mechanics: Policy parallel dims (lifecycle × premium); Claim cyclic; BenefitPeriod ACCRUED→REVERSED; OffsetAward ESTIMATED→FINALIZED→VOID (each transition bumps version). Dual-variant residual factor (presumptive-total when OWN_OCC and coverage_month < own_occ_expiry; proportionate otherwise), COLA compounding with 2.0× cap, offset waterfall WORKERS_COMP-before-SSDI floor 0. Money integer cents; ratios Decimal 4dp half-up. OCC expected_claim_version on income-report create → ERR_STALE_CLAIM_VERSION 412. Cascades: lapse, terminate, reverse compensation, offset finalize/void re-pricing, benefit-period void — each child gets own version/updated_at bump. Validation priority order auth(1)→role+ownership(2)→path existence(3)→body-FK(4)→OCC(5)→state-gate(6)→business(7-13), FK resolution ahead of field-shape range/cap checks.

Notable: benefit_fraction frozen at accrual (feeds conserved benefit_months_consumed); only offset_applied/net re-priced on offset changes. Overpayment balance maintained incrementally. Monotonic _seq for created_at tie-breaks. DisabilityProof only id/created_at. All flows smoke-tested with no server errors.

## Step 7: Run tests and iterate — 2026-06-10T00:00:00.000Z

Iterations run: 1 (the initial 8-round parallel stability sweep). Result: CLEAN PASS. All 8 concurrent rounds reported passed=69, failed=0, errors=0, skipped=0, total=69. No flakiness surfaced — every one of the 69 tests passed in all 8 rounds. (Orchestrator independently re-verified all 8 results.{1..8}.json: round N total=69 passed=69 failed/error=0 for N=1..8.)

Tests deleted: None (no test failed the PRD coverage or unique-derivability checks because no test failed at all).
Fixes applied to test_helpers/: None required.
Fixes applied to implementation/: None required.

The implementation already passes the full suite deterministically under per-test-server isolation with 8x concurrent load. 8 results.{i}.json files remain in implementation/ as evidence.

## Step 8: Finalize PRD — SKIPPED — 2026-06-10T00:00:00.000Z

SKIPPED per skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, and 0 implementation/ fixes (zero iterations beyond baseline). PRD.md already determined every behavior the implementation exhibits at the Step 7 fix sites, so no PRD_FINALIZED.md is produced. Step 9 will start from PRD.md.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-06-10T00:00:00.000Z

Produced workspace/PRD_COMPLETED.md by cp from PRD.md (no PRD_FINALIZED.md existed), then applied 3 minimal in-paragraph edits. Implementation walked exhaustively (app.py routes + validation order, calc.py formulas, services.py views/cascades, db.py, errors.py, middleware.py, response.py); vast majority of behaviors already uniquely pinned by PRD prose.

Counts: lines 307 → 307 (unchanged); chars 47,900 → 48,711 (+811). Ambiguity-pins: 2. Mismatch-revisions: 1.

Changes:
- §2.5 — insert — ambiguity — DisabilityProof "carries only id and created_at"; pinned that its serialized read also surfaces data fields claim_id, attestation_month, still_disabled, and computed accepted — services.py:235-241 (disability_proof_view).
- §3.3 — revise — mismatch — PRD's first-leg prose implied a miss while not CURRENT yields ERR_PREMIUM_NOT_CURRENT, but the miss endpoint dispatches on current premium status: CURRENT→GRACE (gated on ACTIVE), GRACE→DEFAULT, miss while already DEFAULT rejected with ERR_PREMIUM_NOT_IN_GRACE — app.py:457-483 (premium_miss).
- §3.12 — insert — ambiguity — claim ledger described as single sub-resource read; pinned that the ledger read is a paginated list endpoint (honors limit/offset, response_type "array" with pagination meta), data array holds the single ledger when present or empty when claim never approved — app.py:1070-1079 (get_claim_ledger).

Behaviors checked and already pinned (no change): validation-priority ordering + per-type not-found errors (§2.8); two half-up roundings + 2.0 cap (§3.10); residual proportionate vs presumptive-total 0.20/0.80 (§3.9); would-exceed equality-permitted exhaustion + BENEFIT_EXHAUSTED (§3.9); income-report supersede + OCC version gate (§2.7/§3.8); offset touching-collision + WORKERS_COMP-before-SSDI (§3.10/§3.11); finalize/void overpayment-delta conservation (§3.11); lapse/termination cascades (§3.3); proof-cadence advance 3 months + accepted-flag (§3.6); ledger summation ordering (§3.12).

## Pipeline complete — 2026-06-10T00:00:00.000Z

All 9 steps done. Final state: 69/69 tests pass across all 8 parallel stability rounds under per-test-server isolation. Artifacts: SCAFFOLD.yaml (+ DIFFICULTY/CORNER design), workspace/PRD.md, workspace/PRD_COMPLETED.md (PRD_FINALIZED.md absent — Step 8 skipped), workspace/implementation/ (Flask, in-memory), test_helpers/ + test_suite/ (69 tests).
