# Worklog — task_0594_facilities_mgmt

Scenario: Facilities / Integrated Building Management (CBRE style): building/asset & space, work-order & preventive-maintenance, vendor dispatch & SLA, soft-services (janitorial/security) coordination, energy/utility & sustainability, lease/occupancy & chargeback, capital project, KPI dashboard
Difficulty: Expert

## Step 1: Create task directory — 2026-07-11T18:29:30.000Z

Created `tasks/task_0594_facilities_mgmt/` and `tasks/task_0594_facilities_mgmt/workspace/` (directory pre-allocated by the user; no index scan performed).

## Step 2: Generate scaffold — 2026-07-11T18:29:30.000Z

All three artifacts are generated and the linter is clean.

## Lint verdict (verbatim)
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_0594_facilities_mgmt/SCAFFOLD.yaml
  Difficulty design:  tasks/task_0594_facilities_mgmt/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_0594_facilities_mgmt/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    51
  §1.1 entities declared:     13
  §1.8 instances scanned:     22
  §1.9 instances scanned:     42
  Calls scanned (§1.8+§1.9):  502

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## What was generated (Expert band)

**`SCAFFOLD.yaml`** — profile: posture-driven gating × workflow orchestration; layers = OCC, cascading side effects, dual-variant calc, rate/threshold triggers; role model = segregation of duties; api_prefix `/fm`.

- **13 entities**: Building, Space, Asset, PMPlan, Vendor, WorkOrder, Dispatch, SoftServiceShift, UtilityReading (immutable event, `common_fields: false`), Lease, LeaseAllocation, ChargebackStatement, CapitalProject.
- **10 state machines** (4 non-linear on different entities): Building posture OPEN↔RESTRICTED↔FROZEN (compound/derived), WorkOrder **status** (PENDING_QA→IN_PROGRESS rework cycle) × WorkOrder **billing_status** (parallel dimension: PENDING/INVOICED/SETTLED_CHARGEBACK/WAIVED), Dispatch (branching OFFERED→{ACCEPTED, DECLINED, CANCELLED} + COMPLETED→ACCEPTED cycle), Asset (IN_SERVICE↔OUT_OF_SERVICE→RETIRED), PMPlan (ACTIVE↔SUSPENDED→RETIRED), ChargebackStatement (ISSUED↔DISPUTED cycle), SoftServiceShift, Lease, CapitalProject (approve/reject fork).
- **11 calculations**: work_order_billable_amount (provisional vs final_settlement — dual variant #1), vendor_performance_score (rolling_window vs lifetime — dual variant #2, different domain), chargeback_statement_total (round-per-line-then-sum, pinned), capital_project_budget (contingency tier keyed on base_cost — pinned evaluation order), sla_evaluation, building_operating_posture, pm_compliance_state, pm_overdue_promotion, asset_condition_score, building_kpi_dashboard, space_share_conservation.
- **2 OCC concurrency rules** (both CREATE-with-supersede): dispatch-create-stale-work-order, statement-create-stale-lease (412 `ERR_STALE_VERSION`).
- **19 validation priorities**, **51 endpoints** (incl. `POST /fm/buildings/{id}/ops-run` epoch checkpoint, `GET /fm/buildings/{id}/kpi`, and `POST /fm/_clock/set_current_utc` with the mandatory `2026-05-01T00:00:00Z` startup default), **43 errors**, **6 roles** (PlatformAdmin, FacilityManager, VendorTech `entity_backed:Vendor`, FinanceController, TenantRep `entity_backed:Lease`, SustainabilityAnalyst).

**`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** — 9 rule_ids, **22 instances** (≥2 each): dual-variant (WorkOrder cost 960.00 vs 1410.00; Vendor rolling 100.00 vs lifetime 90.00), combinatorial modes (b) per-line rounding 2066.66-vs-2066.67, (c) contingency 104500.00-vs-101650.00, (a) after-hours/cap/tier 4935.00; cycles on WorkOrder and Statement; depth-4 cascade (complete→strike→SUSPENDED→cancel other OFFERED dispatch→order back to NEW) and depth-3 cascade (asset failure→FROZEN→suspend PM plans + cancel shifts); 3 priority conflicts across distinct category pairs (state/temporal, safety/fiscal, referential/constraint); boundaries (inclusive SLA deadline, empty-set KPI = 100.00, RESTRICTED at exactly 2 open P1); cross-entity deps (WO→Building, Dispatch→Vendor, Statement→Lease); overlaps on **different resources with different geometry** (Vendor half-open shifts vs Space closed-interval + aggregate ≤100% capacity); two conserved quantities (capital funds; occupancy share).

**`SCAFFOLD_CORNER_DESIGN.yaml`** — 7 sections (entities, state_machines, calculations, validations, rbac, cross_cutting_layers, consistency_model), **49 instances** = 42 executable + 7 `excluded_because` stubs pointing at §1.8 instances. All formula-derived assertions are pinned literals computed against the declared formulas.

## Step 3: Copy shared files — 2026-07-11T18:29:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0594_facilities_mgmt/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-11T18:40:00.000Z

PRD generated at `workspace/PRD.md`. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced.

## Document

**420 lines.** Title: *Integrated Facilities Management API — Product Requirements Document*.

- **§1 Introduction** — 3 paragraphs (business-pain angle: disconnected FM tooling → one coherent building object).
- **§2 Global Specifications** — 10 domain-derived subsections: 2.1 RBAC · 2.2 API Response Structure (verbatim from `section-2.2-response-structure.md`) · 2.3 Pagination · 2.4 Resource Identity, Timestamps and the Logical Clock · 2.5 Path Resolution and Referential Integrity · 2.6 The Order in Which a Request Is Judged · 2.7 Optimistic Concurrency on Work Orders and Leases · 2.8 Operating Posture: the Building-Level Gate · 2.9 Money, Measurement and Rounding · 2.10 Conserved Quantities.
- **§3 Business Logic** — 9 subsections, grouped by lifecycle-then-cross-cutting: Portfolio Foundations (buildings/spaces/assets/PM plans) · Vendors, Trades and Standing · Capital Projects and the Funding Ledger · Raising Work Orders · Dispatch, SLA and the Completion Cascade · QA, Closure and Recovery · Soft-Service Coordination · The Operational Epoch · Occupancy, Utilities, Tenant Chargeback and the Building KPI Surface.
- **§4** — 51-row endpoint table, 4 columns. **§5** — 43-row error table, 2 columns. Document ends at §5 (no audit footer).

## Hard Contract Reports

```
Field coverage check:
- entities[].fields: 103 required, 103 present, 0 missing
- endpoints[].request_body: 60 required, 60 present, 0 missing
- endpoints[].query_params: 18 required, 18 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 19 checked, 19 expressed in prose (§2.6 renders the full 19-step first-failure-wins ladder), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (dispatch-create/`expected_work_order_version` and statement-create/`expected_lease_version`, each with ERR_STALE_VERSION + 412), 0 missing
- state_machines[].transitions: 48 checked across 10 machines, 48 fully expressed, 0 missing
- calculations[]: 11 checked, 11 fully expressed (no pseudocode; all constants embedded in business context — 80.00 standard rate, 1.5x after-hours, 12h cap, 150.00 min call-out, P1/P2 surcharges, parts tiers, 0.10/0.15/0.25 SLA penalties, 0.4/0.3/0.3 score weights, 3-dispatch window, 2/3 strike ladder, 1000h/5pt/12pt decay, score-20 retirement, contingency tiers, posture thresholds 1 and 2, PM defaults 3h/200.00), 0 missing
- validations[] conditions: 19 checked, 19 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 30 checked, 30 expressed, 0 missing
- entities[].fields[] structured content: 103 checked, 103 reconstructible from prose (incl. UtilityReading's common_fields:false — no updated_at/version), 0 missing
- sibling-branch symmetry: 6 groups checked (APPROVE|REJECT; accept|decline|supersede; QA PASS|FAIL; provisional|final settlement; rolling|lifetime score; FROZEN→OPEN|FROZEN→RESTRICTED), 6 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 718
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Also verified: all 6 role names and all 48 state strings appear verbatim; all 43 error IDs appear in §2/§3 prose; zero fuzzy/approximating words; §2.2 is byte-identical to the canonical source.
