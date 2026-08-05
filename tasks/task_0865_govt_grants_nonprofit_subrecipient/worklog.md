# Worklog — task_0865_govt_grants_nonprofit_subrecipient

## Step 1: Create task directory — 2026-07-27T00:00:00.000Z

Created tasks/task_0865_govt_grants_nonprofit_subrecipient/ and workspace/. Pre-assigned folder, index scan skipped.

## Step 2: Generate scaffold — 2026-07-27T00:00:00.000Z

task_0865_govt_grants_nonprofit_subrecipient — scaffold generated. Domain: Government Grants-to-Nonprofits & Subrecipient Monitoring (Expert). Archetype: Compliance/audit + Ledger reconciliation; flat FK topology; cyclic state machines; segregation-of-duties RBAC.

Files: SCAFFOLD.yaml (§1.0–§1.7); SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8 — 18 instances); SCAFFOLD_CORNER_DESIGN.yaml (§1.9 — 21 active + 3 excluded stubs).

Scale: 12 entities · 48 endpoints · 36 errors · 6 calculations · 6 state machines · 4 roles · 1 OCC rule.
Entities: Nonprofit, NOFO, Application, PanelReview, Subaward, BudgetLine, Drawdown, RiskAssessment, MonitoringVisit, PerformanceReport, SingleAudit, Finding.
State machines (4 non-linear): Application (revision cycle REVISION_REQUESTED→SUBMITTED), Subaward (ACTIVE↔SUSPENDED cycle + closeout/terminate branches), Drawdown (RETURNED→SUBMITTED cycle), Finding (CAP_SUBMITTED→OPEN cycle); plus linear MonitoringVisit and SingleAudit.
Calculations: indirect_cost_recovery (dual-variant DE_MINIMIS vs NEGOTIATED + MTDC exclusion/cap — combinatorial mode a), drawdown_reimbursable (dual-variant provisional vs final), subaward_federal_share (per-line rounding — combinatorial mode b), risk_score (weighted/tiered), single_audit_requirement ($750k threshold), budget_balance (exact-equality gate).
Roles (SoD): ProgramOfficer (opaque), Panelist (opaque), GrantsManager (opaque, four-eyes: risk-assessor cannot approve that subaward's drawdowns), Subrecipient (entity_backed:Nonprofit).
Difficulty design: all nine §0.5 rules covered with 2 instances each (18) — depth-4 cascade (critical finding → suspend → return drawdown → release obligation), two conserved-quantity invariants (obligation ledger, NOFO pool), two interval-overlap semantics (half-open monitor visits vs closed/30-day-buffer subaward periods).
Verification: all three YAML files yaml.safe_load clean; scaffold_lint.py VERDICT clean lint (457 calls, all FKs reverse-reachable). Note: logical-clock endpoint POST /_clock/set_current_utc default 2026-05-01T00:00:00Z; recipes use literal ISO dates but impl must honor default-clock contract for deadline logic.

## Step 3: Copy shared files — 2026-07-27T00:00:00.000Z

Copied INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-07-27T00:00:00.000Z

Output: workspace/PRD.md (284 lines). §1 Intro; §2 Global Specs (12 subsections incl. RBAC/role-identity, envelope, pagination, common props, nested-path validation, money precision/per-line rounding, cascading consistency, OCC on drawdown create, pool/obligation conservation invariants, SoD, validation ordering ladder, logical clock); §3 Business Logic (9 subsections); §4 endpoint table (48/48); §5 error table (36 IDs).
Hard-contract reports all PASS: field-name coverage (84 names, 0 missing; 36 errors; 22 states), rule coverage (validation ladder, OCC ERR_STALE_VERSION 412, all transitions/cascades/6 calcs), §3 path purity (0 methods/paths). Constants embedded w/ unit conversions ($25k=2.5M cents MTDC cap; $750k=75M cents single-audit; $500k=50M cents size cutoff; 0.10 de-minimis; 30-day gap; 3-review quorum). Award gates ordered period-overlap→max-award→pool. Half-open monitor-visit overlap vs closed gap-widened award-period overlap contrasted.

## Step 6: Generate implementation — 2026-07-27T00:00:00.000Z

workspace/implementation/: app.py (~1050 lines single-file Flask, in-memory dicts, no seeding), requirements.txt (flask==3.0.3), start.sh (guarded pip, exec python3, 0.0.0.0:$PORT default 10000, foreground). 48 endpoints.
Envelope: meta{api_request_id req_..., api_request_timestamp}, response_type, data; lists add limit/offset/total_count/has_more; error {error_id,message}. Logical clock default 2026-05-01T00:00:00Z; created_at/updated_at/api_request_timestamp via one now_iso() renderer in .123Z form; domain datetime inputs echoed verbatim. str(uuid4()) dashed ids; Connection: close after_request. Validation order per §2.11 (auth→authz→existence→ownership→state→business→field-shape last, OCC before field). Money Decimal ROUND_HALF_UP; federal share per-line-then-sum; indirect once after MTDC×rate (EQUIPMENT excluded, CONTRACTUAL capped 2.5M); DE_MINIMIS fixed 0.10. Ledger conservation eager side-effects; every mutation bumps version+updated_at. PanelReview/BudgetLine light (id,created_at). OCC drawdown create via expected_subaward_version; provisional vs final via _available_at_submit; SoD four-eyes drawdown approve; cascades suspend/close/terminate/CRITICAL-finding→auto-suspend. Sort by (created_at,_seq). Judgment call: monitoring conduct on non-ACTIVE/SUSPENDED subaward → ERR_INVALID_SUBAWARD_STATE 409.

## Step 5: Generate unit tests — 2026-07-27T00:00:00.000Z

test_helpers/: types.py (12 TypedDicts, PanelReview/BudgetLine append-only id+created_at), api_client.py (48 methods), api_errors.py (37 IDs+HTTP map), constants.py, factories.py, assertions.py, test_users.py (opaque PO/Panelist/GrantsManager + entity_backed Subrecipient make_subrecipient_headers), fixtures.py (nonprofit→NOFO→scored-app→award→budget-lines→activate preamble + drawdown/visit/finding helpers), __init__.py.
test_suite/: conftest.py + 8 files. 57 tests total. Queue A (Difficulty) 36 (18 instances ×2). Queue B (Corner) 21 (21 non-stub ×1). Skipped: 3 excluded_because stubs. 57/57 collect clean; every test one Design: tag resolving to real instance; verbatim PRD substring per docstring; no scaffold leakage.
Adjudication: corner negotiated_rate_over_cap_rejected_on_submit — PRD §3.2 puts ERR_INDIRECT_RATE_OVER_CAP at application creation, so test asserts at creation (uniquely-derivable reading).

## Step 7: Test and iterate — 2026-07-27T00:00:00.000Z

CLEAN FIRST-SWEEP PASS. Iterations run: 1 (single 8-round parallel sweep). All 8 rounds passed 57/57 (0 failed, 0 errors, 0 skipped); no flakiness. Tests deleted: none. test_helpers/ fixes: none. implementation/ fixes: none. Verified results.{1..8}.json all 57/57.

## Step 8: Finalize PRD — 2026-07-27T00:00:00.000Z

SKIPPED. Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, 0 implementation/ fixes. PRD.md already determined every behavior the implementation exhibits; no PRD_FINALIZED.md produced.

## Step 9: Complete PRD — 2026-07-27T00:00:00.000Z

Output: workspace/PRD_COMPLETED.md. Source PRD.md 284 → 284 lines (all inline), char delta +673 (41,412→42,085). 9 changes: 9 ambiguity-pins, 0 mismatch-revisions.
Pins: §3.1 duplicate uei→ERR_VALIDATION; §3.3 review on non-UNDER_REVIEW app→ERR_INVALID_APPLICATION_STATE; §3.4 non-terminal subaward = not CLOSED/TERMINATED for overlap gate; §3.4 award returns updated Application in data (Subaward fetched separately); §3.8 conduct on non-ACTIVE/SUSPENDED→ERR_INVALID_SUBAWARD_STATE; §3.8 conduct returns MonitoringVisit (Finding separate side effect); §4 drawdowns/monitoring-visits/findings list status filter documented.
Left unchanged (already uniquely pinned & matched impl): calc disciplines (MTDC EQUIPMENT-excluded/CONTRACTUAL-capped 2.5M, per-line round-then-sum, risk bands, audit thresholds), §2.11 validation order, cascade/obligation ledger, OCC drawdown create, SoD, §2.3 pagination clamping.

## Pipeline complete — 2026-07-27T00:00:00.000Z

All 9 steps done. Clean first-sweep pass 57/57 × 8 rounds, 0 fixes/0 deletions. Artifacts: SCAFFOLD.yaml (+DIFFICULTY/CORNER designs), workspace/PRD.md, PRD_COMPLETED.md (Step 8 skipped, no PRD_FINALIZED.md), test_helpers/, test_suite/ (57 tests), workspace/implementation/ (48 endpoints).

