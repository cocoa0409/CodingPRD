# Worklog — task_0071_solar_panel_install_financing

## Step 1: Create task directory — 2026-05-31T15:37:25Z

Created `tasks/task_0071_solar_panel_install_financing/` and `workspace/` subdirectory. Scenario: Solar Panel Installation & Financing. Difficulty: Expert.

## Step 2: Generate scaffold — 2026-05-31T15:55:55Z

All three files generated and the linter passes clean.

Generated the full scaffold package for **task_0071_solar_panel_install_financing** at **Expert** difficulty, written purely from the scenario + skill spec (no sibling tasks consulted). `scaffold_lint.py` reports **VERDICT: clean lint** (614 calls scanned across §1.8/§1.9, all conform to §1.5; all FKs reverse-reachable).

**Files**: SCAFFOLD.yaml (§1.0–§1.7), SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8), SCAFFOLD_CORNER_DESIGN.yaml (§1.9).

**Complexity profile**: workflow_orchestration + ledger_reconciliation; flat topology; branching/cyclic state machines; peer_roles; immediate consistency. Layers: dual-variant calc, cascading side effects, rate/threshold triggers, OCC, derived-field reconciliation.

**Entities (12)**: Homeowner, SolarInstaller, Utility, SrecBroker, Project, FinancingPlan, SREC, SrecSale, NetMeterPeriod, WarrantyPolicy (immutable, common_fields:false), WarrantyClaim, InterconnectionApplication.

**State machines (6)**: Project (cyclic — FAILED_INSPECTION→REMEDIATION→INSTALLED, branches at financing model and inspect PASS/FAIL), FinancingPlan (DRAFT→ACTIVE→TERMINATED), InterconnectionApplication (FILED→…→PTO_GRANTED, with compensating APPROVED→withdraw→REJECTED), SREC (MINTED→LISTED→SOLD→RETIRED), NetMeterPeriod (OPEN→SETTLED, chronological), WarrantyClaim (cyclic SUBMITTED↔INFO_REQUESTED).

**Key calculations (7)**: size_system, estimate_production, itc_credit (30% federal + state adder capped 40%; HOMEOWNER vs FINANCIER attribution), financing_monthly_payment (LOAN amortization / LEASE fixed / PPA production-based), srec_sale_settlement (sweep + sum-then-round fee — 5617¢ not 5615¢), net_metering_settlement (full-retail vs net-billing variant; kWh bank carryover), production_shortfall_eval. Two OCC concurrency rules (srec-sale and financing-activate, both on Project.version, 412).

**Difficulty**: 9 rules × 2 = 18 instances. **Corner**: 32 active + 3 excluded_because stubs spanning all 9 claim-extraction-guide sections. All formula-derived asserts computed in Python and written as literals.

Added closed-interval claim-window-overlap rule on WarrantyClaim (ERR_CLAIM_WINDOW_OVERLAP) and an interconnection withdraw action so Rules 8 & 9 could be satisfied on distinct entities.

## Step 3: Copy INSTRUCTION.md — 2026-05-31T15:55:55Z

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-05-31T16:00:24Z

PRD generated at workspace/PRD.md. 270 lines, 5 top-level sections (§1 Introduction, §2 Global Specifications, §3 Business Logic & Workflows, §4 Endpoint Definitions, §5 Error Code Catalogue) with 19 subsections.

Domains: full solar lifecycle — sunlight assessment, design with roof/usage system sizing, federal ITC with state adders, three financing models (PPA/Lease/Loan) with model-specific monthly-payment math, permitting/installation/inspection/remediation loop, cross-entity PTO grant driving project operational + minting warranty, utility interconnection with conserved feeder-headroom ledger (approve decrement / withdraw compensating restore), monthly net-metering settlement with kWh bank and full-retail-vs-net-billing fork, SREC mint/list/sweep-sale with sum-then-round broker fee, warranty production-shortfall evaluation.

Hard Contracts all PASS (field coverage, rule coverage, path purity §3). Withheld design files not opened.

## Step 5: Generate unit tests — 2026-05-31T16:14:31Z

Generated complete test infrastructure. test_helpers/ (9 files) + test_suite/ (conftest + 7 domain files).

**69 tests total**, all collect/compile cleanly. Queue A (Difficulty): 18 instances × ≥2 tests = 37 tests (all 18 instances across 9 rules covered ≥2×). Queue B (Corner): 32 tests — every non-stub corner instance covered once. Skipped: 3 excluded_because stubs (no test_recipe; assertions owned by cited instances). No PRD-coverage/two-reader gaps forced any non-stub skip.

Quality: every docstring carries verbatim PRD citations + exactly one Design: tag; precedence-pair tests cite PRD §2.9; no skip/xfail; no scaffold leakage; literals copied from design indices.

## Step 6: Generate implementation — 2026-05-31T16:14:31Z

Generated complete Python + Flask implementation in workspace/implementation/. In-memory only (db.py dicts), no seeded data.

Files: start.sh, requirements.txt, app.py, db.py, response.py, errors.py, middleware.py, services/common.py, services/calc.py, routes/{participants,projects,financing,interconnection,srecs,netmeter,warranty}.py.

All 50+ PRD §4 endpoints. calc.py: size_system, estimate_production, itc_credit, financing_monthly_payment (3-variant), srec_sale_settlement (sum-then-round), net_metering_settlement (2-variant + bank carryforward), production_shortfall_eval — all Decimal. State machines in route modules: Project (11-state branching + remediation loop + cascade cancel→plan-terminate), FinancingPlan, InterconnectionApplication (feeder ledger + cross-entity grant-pto→OPERATIONAL + warranty mint), SREC, NetMeterPeriod, WarrantyClaim (cyclic).

Verified: validation precedence, OCC 412 on activate + srec-sales, half-open period overlap vs closed-interval claim overlap, cascade version bumps, full happy path. Note: grant-pto mints WarrantyPolicy with server default production_guarantee_pct 0.85 (scaffold value), since neither endpoint input nor PRD provides it as request input.

## Step 7: Test + fix loop — 2026-05-31T16:18:31Z

All 8 rounds pass cleanly (69/69 each).

**Iterations run:** 2 (1 diagnostic sweep + 1 confirmation sweep).

**Failing tests (union across 8 rounds):**
- test_non_owner_cancel_operational_fails_ownership_first and test_non_owner_cancel_returns_403_not_409 — failed all 8 rounds (real logic bug).
- test_approve_zero_shortfall_rejected — failed only round 2 with ConnectionError: BadStatusLine on unrelated endpoint (transient server hiccup, passed other 7 rounds + confirmation sweep).

**Tests deleted:** None. Both ownership-precedence tests passed STEP 1 (PRD verbatim-covers + uniquely determines) and STEP 2 (faithful). PRD.md line 102 states precedence verbatim: ownership (ERR_NOT_RESOURCE_OWNER) before state (ERR_INVALID_STATE).

**Fixes applied to test_helpers/:** None.

**Fixes applied to implementation/:**
- routes/projects.py, cancel() — reordered guards so ownership check (ERR_NOT_RESOURCE_OWNER, 403) runs before state check (ERR_INVALID_STATE, 409), matching PRD-mandated precedence. Previously a non-owner cancelling an operational project got 409 instead of 403.

**Final result:** All 8 parallel rounds pass 69/69.

## Step 8: Finalize PRD — 2026-05-31T16:19:39Z

PRD_FINALIZED.md created as exact copy of PRD.md, no edits. PRD.md = 270, PRD_FINALIZED.md = 270 (0% delta).

The only logic fix (cancel() guard reorder) conforms to precedence already pinned verbatim in PRD §2.9 (ownership ERR_NOT_RESOURCE_OWNER before state ERR_INVALID_STATE). Pure impl bug, not a PRD silence/mismatch — no edit warranted.

Pre-edit search flagged for Step 9: complete_install() and start_remediation() in routes/projects.py order state before ownership (reverse of cancel()), which may diverge from §2.9's universal ordering. Subagent left §2.9 untouched to avoid a false universal claim; Step 9 should examine this.

## Step 9: Complete PRD — 2026-05-31T16:22:47Z

PRD_COMPLETED.md produced. Source PRD_FINALIZED.md (270 lines, 40213 chars) vs PRD_COMPLETED.md (270 lines, 40868 chars); +655 chars. All in-paragraph; no new sections. Counts: 2 ambiguity-pins, 2 mismatch-revisions.

Changes:
- §2.1 — insert — ambiguity — unrecognized X-User-Role (not just missing header) yields ERR_UNAUTHENTICATED (401), not ERR_FORBIDDEN_ROLE — middleware.py:12-13
- §2.9 — revise — mismatch — PRD declared universal ownership-then-state precedence; pinned the two exceptions where state is checked before ownership: complete-install and start-remediation — routes/projects.py:183-185, 214-216; confirmed cancel (projects.py:228-230) and activate (financing.py:120-125) keep ownership-before-state. (This resolves the Step 8 flag.)
- §3.4 — revise — mismatch — PRD said activation "recomputes this attribution onto the project"; impl stores itc_beneficiary on the financing plan and only re-derives project itc_credit_cents — financing.py:148-157; project has no itc_beneficiary field
- §3.6 — insert — ambiguity — pinned minted production_guarantee_pct default of 0.85 — interconnection.py:158

Deliberately left unchanged: OCC-vs-business-check ordering in activate/create_sale, model/term-range vs FINANCING_FIELDS_MISSING ordering (framed loosely by §2.8/§2.9, not divergent behavior); net-metering surplus-floor and no-plan owner_type fallback (unreachable no-ops).

## Pipeline complete — 2026-05-31T16:22:47Z

All 9 steps done. Final state: 69/69 tests pass across all 8 parallel rounds. Artifacts present: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, worklog.md, test_helpers/, test_suite/, workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}.
