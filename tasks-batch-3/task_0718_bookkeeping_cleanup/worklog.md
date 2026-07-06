# Worklog — task_0718_bookkeeping_cleanup

## Step 1: Task directory (pre-assigned) — bash-only

Directory `tasks/task_0718_bookkeeping_cleanup/` and its `workspace/` subdir already existed (pre-assigned). Skipped index scan per orchestrator instructions.

## Step 2: Generate scaffold (Expert) — subagent

Generated 3 scaffold artifacts at Expert difficulty:
- SCAFFOLD.yaml (1468 lines): scenario, entities, state_machines, calculations, endpoints (~52 role-tagged endpoint lines), errors, roles (EngagementManager, Bookkeeper, Reviewer, TaxPreparer).
- SCAFFOLD_DIFFICULTY_DESIGN.yaml (1065 lines): 9 depth rule_ids — dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant.
- SCAFFOLD_CORNER_DESIGN.yaml (1280 lines): 9 breadth sections — entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_complexity_layers, consistency_model.

Verbatim subagent summary:
> I generated all three scaffold artifacts for `task_0718_bookkeeping_cleanup` at **Expert** difficulty, validated with a clean `scaffold_lint.py` run (`VERDICT: clean lint` — 422 calls scanned across §1.8/§1.9, all conform to §1.5, all FKs reverse-reachable).
>
> **Files written**: SCAFFOLD.yaml (§1.0–§1.7), SCAFFOLD_DIFFICULTY_DESIGN.yaml (single key `scaffold_difficulty_design`), SCAFFOLD_CORNER_DESIGN.yaml (single key `scaffold_corner_design`).
>
> **Design profile**: Ledger-reconciliation + compliance-audit archetype, flat topology, parallel state-machine shape, segregation-of-duties role model.
>
> **Counts (Expert band satisfied)**:
> - Entities: 13 — Client, CleanupEngagement, ScopeEstimate, LedgerAccount, LedgerEntry, BankStatement, ReconciliationItem, Phase, PhaseInvoice, TaxPackage, ServicePlan, Exception, CompletionReport
> - Endpoints: 61 (34 POST business/action + 27 GET reads)
> - Error codes: 29
> - Calculations: 7, with 3 dual-variant — `taxable_income` (cash vs accrual), `scope_volume_estimate` (forward vs actual-reconstructed), plus tiered `fixed_price_quote`, `phase_billing_split` (residual rounding), `readiness_score`, `recon_difference`, `service_proration`
> - State machines: 9, including 2 parallel dimensions on CleanupEngagement (workflow_status × billing_status), a cyclic Exception machine (OPEN↔WAITING_DOCS), and a branching BankStatement machine
> - Concurrency: 1 OCC rule on `CleanupEngagement.version` (scope-accept supersede)
>
> **Design files**: 18 difficulty instances (9 rules × 2) + 30 active corner instances + 3 `excluded_because` stubs. All 51 instance names unique; all stub references resolve. All formula-derived asserts computed in code and pinned as literals (estimate 1518, fixed price 90540, phase split 30177/30177/30186, accrual income 510000 vs cash 420000, readiness 42, proration 21000, recon-tolerance inclusive boundary at ±100).
>
> One semantic bug caught and fixed: the cash-basis corner instance originally settled the wrong ledger entry, so its asserted 420000 wouldn't have held — rewritten to match the income (500000) and expense (80000) entries directly via reconciliation items, leaving the 120000/30000 entries unsettled.

## Step 3: Copy INSTRUCTION.md — bash-only

Copied `./INSTRUCTION.md` → `tasks/task_0718_bookkeeping_cleanup/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — subagent

Generated `workspace/PRD.md` (268 lines, ~41 KB) from SCAFFOLD.yaml only (both design indices withheld). Sections: Introduction; Global Specs (RBAC, response/error format, pagination, common mutation semantics, nested-resource path validation, validation ordering, derived engagement aggregates, readiness scoring, monetary precision/rounding, optimistic concurrency on scope acceptance); Business Logic & Workflows (clients/engagement creation, scoping & forward volume estimation, ledger reconstruction accounts/entries, advancing to reconciliation, bank/credit reconciliation, exception tracking, quoting & phase billing, books-to-tax handoff, completion & ongoing-service conversion); Endpoint Definitions; Error Code Catalogue.

Verbatim subagent summary:
> PRD generated at `workspace/PRD.md`. Document: 268 lines, ends cleanly at §5 (no audit footer).
> Sections: §1 Introduction; §2 Global Specs (10 subsections: Access Control + segregation of duties; Response Structure verbatim §2.2; Pagination; Common Resource Properties; Nested Retrieval; Validation Ordering; Derived Engagement Aggregates; Readiness Scoring; Monetary Precision; OCC on scope acceptance); §3 Business Logic (9 subsections); §4 Endpoint table (51 endpoints); §5 Error table (29 error codes).
> Documented: 13 entities; 51 endpoints; 29 error codes; 4 roles (all identity: opaque); parallel workflow_status × billing_status machines + LedgerAccount/LedgerEntry/BankStatement/Phase/Exception/TaxPackage/ServicePlan machines; all 6 calculations; 15 priority-ordered validations.
> Hard Contracts — all PASS: Field coverage (59/59 entity fields, 41/41 request/query/path), Rule coverage (validations ordering, OCC, state transitions, calculations, side_effects all 0 missing), Path purity (406 backtick tokens, 0 paths/methods leaked into §3).
> One note: initial checker falsely flagged fields due to triple-backtick fences in §2.2 JSON; after stripping fenced blocks only `statement_id` was genuinely missing, added to §3.5.

## Step 5: Generate unit tests — subagent

Verbatim subagent summary:
> Generated complete test infrastructure for `task_0718_bookkeeping_cleanup`.
> Stage 1 — test_helpers/ (9 files): types.py, api_errors.py (29 error IDs + HTTP map), api_client.py (one method per endpoint), constants.py, factories.py, assertions.py, test_users.py (4 opaque roles + per-role builders for segregation-of-duties), fixtures.py (5-tier composite chains: scoping → reconstruction → reconciliation → bank-reconciled → quoted/phased/invoiced), __init__.py barrel.
> Stage 2 — test_suite/ (conftest + 4 files): 65 test functions — test_01_calculations.py, test_02_reconciliation.py, test_03_workflow_billing.py, test_04_entities_rbac.py
> Coverage: Queue A (Difficulty) 18 instances × exactly 2 tests = 36 tests (all 9 rules × 2 instances, ≥2 tests each). Queue B (Corner) 29 tests, one per non-stub instance. The 3 excluded_because stubs not translated.
> Instances skipped (1): Corner/endpoints/get_completion_report_404_until_completed — fails unique derivability (PRD never specifies empty-array-vs-404 for not-yet-completed engagement; a faithful reader could return 404). Gap left as gap.
> All test docstrings carry verbatim PRD citations ending with exactly one Design: Difficulty/... or Design: Corner/... tag. All 65 tests collect/compile cleanly.

## Step 6: Generate implementation — subagent

Verbatim subagent summary:
> Generated a complete Python + Flask in-memory REST API at workspace/implementation/.
> Files: start.sh (foreground, reads $PORT default 10000, binds 0.0.0.0, guards pip install, execs server), requirements.txt (Flask 3.0.3), app.py (routes, error handlers, derived-field recompute, serializers, taxable-income), calc.py (Decimal/ROUND_HALF_UP money calcs), db.py (in-memory dicts, UUID/timestamp/version stamping, touch()), errors.py, response.py, middleware.py.
> Endpoints: ~55 routes — clients, engagements (lifecycle + computed reads incl volume-actuals), scope estimates (OCC accept), ledger accounts (categorize/mark-reconciled/exclude), ledger entries (post/reverse), bank statements (finalize), reconciliation items, phases/invoices (generate/invoice/pay), tax packages (build/handoff/amend), service plans, exceptions (cyclic OPEN↔WAITING_DOCS, resolve/waive), completion report, plus flat reverse-FK reads.
> State/storage: in-memory only — no SQLite, no disk. Store starts empty every boot (no seeding); every entity created via API. RLock guards mutations; each mutation refreshes updated_at + bumps version.
> Fidelity: exact meta/response_type/data envelope; X-User-ID/X-User-Role headers + 4 roles; validation priority order (header → role → segregation-of-duties BEFORE existence → not-found left-to-right → invalid-request → invalid-state → business rules); OCC on expected_engagement_version (412); parallel workflow_status × billing_status with auto-settle bubble-up; CASH vs ACCRUAL taxable income; tiered marginal pricing; phase waterfall with remainder on last phase; recon tolerance inclusive 100-cent boundary + auto-created BLOCKING UNRECONCILED_DIFF exception; pagination limit(10/1-100)/offset/total_count/has_more sorted by created_at asc.
> Verification: smoke-tested full lifecycle + edge cases; all correct (quote 127800, CASH net income 0 for unsettled income, proration 15000).

## Step 7: Run tests and iterate to PASS — subagent

Verbatim subagent summary:
> All 8 parallel rounds pass cleanly (63/63 each). Test count dropped from 65 to 63 because two non-PRD-derivable tests were deleted.
>
> Iterations run: 2 (one diagnostic sweep surfaced 6 stable failures across all 8 rounds, then one fix sweep came back clean 63/63 × 8).
>
> Tests deleted (PRD-silence / non-unique-derivability — STEP 1b COMPUTED-FIELD-SILENCE):
> - test_reverse_entry_balance_returns_to_zero_on_credit_normal (test_02_reconciliation.py)
> - test_reverse_entry_conserves_account_balance (test_02_reconciliation.py)
> Both asserted that after reversing the only posted entry on an account, book_balance_cents == 0. PRD 3.3 defines book balance from "posted entries" and reversing moves the entry POSTED→REVERSED. A faithful reader excludes the reversed original → balance = −(amount), not 0. Not uniquely determined → deleted. Sibling test_reverse_entry_creates_opposite_posting (status/side/amount/reversed_entry_id, all verbatim PRD 3.3) kept and passes.
>
> Fixes applied to test_helpers / test_suite setup (STEP 2 — fixture violated a PRD precondition):
> - test_suite/test_01_calculations.py, helper _build_accrual_engagement_with_income_expense: captured v0 = eng["version"] BEFORE start-scoping, then accepted scope estimate with stale version. Per PRD 2.10 expected_engagement_version must be the last-observed version; start-scoping is a mutation that increments version (PRD 2.4). Fixed to capture v0 from the start_scoping response. Root cause of 3 test_01 setup failures with ERR_STALE_ENGAGEMENT_VERSION.
>
> Fixes applied to implementation (STEP 3):
> - workspace/implementation/app.py, accept_scope_estimate: reordered precondition checks so expected_engagement_version (STALE, 412) is evaluated BEFORE workflow_status != SCOPING (INVALID_STATE). PRD 2.10's worked example describes the competing-acceptance scenario as yielding ERR_STALE_ENGAGEMENT_VERSION; after the first accept the engagement has left SCOPING, so prior ordering shadowed the stale error with ERR_INVALID_STATE. Fixed test_stale_engagement_version_on_scope_accept. Estimate-not-PROPOSED check (PRD 3.2) preserved ahead of both.
>
> Final state: 63/63 tests passing across all 8 parallel rounds, no flakiness.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — subagent

**File deltas (PRD_FINALIZED.md → PRD_COMPLETED.md):**
- Line count: 268 → 268 (all edits were in-paragraph; no lines added)
- Char count: 41,506 → 42,970 (+1,464 chars)

**Counts:** 5 ambiguity-pins, 1 mismatch-revision.

**Per-change:**
- **§2.7 Derived Engagement Aggregates** — insert — ambiguity — pinned the `recon_status` aggregation rule (PRD only said "aggregated from the outcomes"): `OUT_OF_BALANCE` iff a `RECONCILING` statement plus an open `UNRECONCILED_DIFF` exception exist; else `PENDING` iff any non-`EXCLUDED` bank account lacks a `RECONCILED` statement; else `IN_BALANCE` — `app.py:303-327` (`compute_recon_status`).
- **§3.1 Clients and Engagement Creation** — insert — ambiguity — pinned the fresh engagement's initial derived-field values, notably `recon_status` starting at `IN_BALANCE` (not `PENDING`) and the four counts/score at zero — `app.py:625-629`.
- **§3.3 Reconstructing the Ledger** — insert — ambiguity — pinned the `book_balance_cents` sign convention (`+amount_cents` when `side == normal_side`, else `-`; only `POSTED` entries contribute) — `app.py:269-281` (`account_book_balance`).
- **§3.5 Bank and Credit Reconciliation** — insert — ambiguity — pinned `variance = actual_txn_volume − estimated_txn_volume` and that the volume-actuals read is a bare 3-field object with no `id`/timestamps/`version` — `app.py:660-679` (`volume_actuals`).
- **§3.7 Quoting and Phase Billing** — insert — ambiguity — pinned that the quoted fixed price is stored/exposed on the engagement as `fixed_price_cents`, null before quoting — `app.py:383, 630, 723`.
- **§4 Endpoint Definitions (completion-report row)** — revise — mismatch — PRD described a singular "Get the engagement's CompletionReport"; impl returns a paginated **array** envelope (`response_type` "array"), revised to match — `app.py:1835-1843` (`get_completion_report`).

Tests were used only as auxiliary cross-reference (constants, entity-shape assertions confirming `fixed_price_cents`/`recon_status`/array completion-report); the implementation was the alignment target throughout. No new sections or paragraphs were added; every change is an in-paragraph insert or revision.
