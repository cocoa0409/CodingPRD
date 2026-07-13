# Worklog — task_0595_architecture_firm

Scenario: Architecture Firm Project Management: project phase (SD/DD/CD/CA) & milestone, fee (% of construction/hourly) & contract, drawing/RFI/submittal log, consultant coordination, time/expense & billing, code/permit review, change & additional service, construction-admin field report

Difficulty: Expert (passed to prd-bench-scaffold-generator only).

## Step 1: Create task directory — 2026-07-11T18:25:00.000Z

Created `tasks/task_0595_architecture_firm/` and `tasks/task_0595_architecture_firm/workspace/` (pre-assigned ID; no scan of tasks/).

## Step 2: Generate scaffold — 2026-07-11T18:30:00.000Z

Lint is clean. Done.

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.

Coverage
  §1.5 endpoints declared:    49
  §1.1 entities declared:     14
  §1.8 instances scanned:     19
  §1.9 instances scanned:     54 (active; 5 further excluded_because stubs)
  Calls scanned (§1.8+§1.9):  800
```

## What was generated

All three files under `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0595_architecture_firm/`.

**SCAFFOLD.yaml** (§1.0–§1.7)
- **Profile**: `workflow_orchestration` × `ledger_reconciliation`; layers = OCC, cascading side effects, dual-variant calc, derived-field reconciliation; shape `cyclic`; role model `segregation_of_duties`; `api_prefix: "/"` (flat creation surface, FKs in bodies).
- **14 entities**: Project, Contract, Phase (absorbs the milestone), StaffMember, ConsultantFirm, TimeEntry, Expense, Drawing, RFI, Submittal, ChangeOrder, Invoice, PermitReview, FieldReport (`common_fields: false`, append-only).
- **13 state machines**, incl. 3 cycles (Submittal revise-and-resubmit, RFI clarification bounded at 2 rounds, PermitReview comments↔resubmit), Invoice **parallel dimensions** (`status` × `payment_status`), ChangeOrder **fork** (CLIENT_APPROVED / CLIENT_REJECTED), TimeEntry approve↔reverse.
- **2 concurrency rules** (OCC on `Contract.version`): `POST /invoices` and `POST /change-orders/{id}/execute`, both `expected_contract_version` → 412.
- **7 calculations**: `contract_fee_earned` (PERCENT-of-construction vs HOURLY-with-NTE — dual variant, money domain), `submittal_review_due` (CALENDAR vs BUSINESS days — dual variant, schedule domain), `phase_fee_allocation` (rounding order pinned, last phase absorbs remainder), `invoice_totals` (retainage tier keyed on cumulative-after-this-invoice, 7-step order pinned), `project_labor_rollup`, `rfi_rollup`, `time_entry_amounts`.
- **15 ordered validations**, **45 errors**, **5 roles** (PrincipalArchitect/ClientRep opaque; ProjectManager/StaffArchitect → StaffMember; ConsultantRep → ConsultantFirm), **49 endpoints** incl. `POST /_clock/set_current_utc` (default clock `2026-05-01T00:00:00Z`).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** — 9 rule_ids, **19 instances** (2 each, 3 for `non_linear_state_machine`). All formula-derived asserts are literals computed in Python (e.g. allocation 1800772/1800772/3600463/3600462 = 10802469; invoice gross 3310000 → retainage 331000 → net 2979000; business-day due 2026-06-19T09:00:00Z).

**SCAFFOLD_CORNER_DESIGN.yaml** — 9 sections (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_complexity_layers, consistency_model), **59 instances** of which 5 are `excluded_because` stubs pointing at §1.8 instances.

**Deviations worth flagging**: endpoint count (49) and error count (45) sit above the Expert bands (20–32 / 18–30). Both are driven by the scenario's 14 mandated domain concepts — each child entity needs a create + a reverse-reachability GET pair, and each gets its own 404 code. Entity count (14), calc variants, and state-machine count are all inside the Expert band.

## Step 3: Copy shared files — 2026-07-11T18:30:28.000Z

Copied `INSTRUCTION.md` → `tasks/task_0595_architecture_firm/workspace/INSTRUCTION.md`.
