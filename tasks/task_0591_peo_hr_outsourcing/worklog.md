# Worklog — task_0591_peo_hr_outsourcing

## Step 1: Create task directory — 2026-07-11T14:02:45.000Z

Skipped index scan per orchestrator instruction. Task directory `./tasks/task_0591_peo_hr_outsourcing` (with `workspace/`) was pre-created and reserved.

## Step 2: Generate scaffold (Expert difficulty) — 2026-07-11T14:02:45.000Z

The scaffold is complete and lints clean.

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_0591_peo_hr_outsourcing/SCAFFOLD.yaml
  Difficulty design:  tasks/task_0591_peo_hr_outsourcing/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_0591_peo_hr_outsourcing/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    49
  §1.1 entities declared:     15
  §1.8 instances scanned:     18
  §1.9 instances scanned:     43
  Calls scanned (§1.8+§1.9):  671

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## What was generated

Three files in `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0591_peo_hr_outsourcing/`.

**Complexity profile (Expert):** primary archetype compliance/audit + secondary ledger reconciliation; layers = dual-variant calculation, cascading side effects, rate/threshold triggers, optimistic concurrency, derived-field reconciliation; topology `graph`; state-machine shape `parallel`; role model `segregation_of_duties`; consistency `immediate`.

**SCAFFOLD.yaml (§1.0–§1.7)**
- **15 entities**: ClientCompany, WorksiteEmployee, OnboardingPacket, WorkersCompPolicy, WcClassCode, BenefitPlan, OpenEnrollmentWindow, BenefitEnrollment, PayrollRun, PayrollLine, TaxFiling, ComplianceFiling, HrTicket, ClientInvoice, InvoiceLine.
- **10 state machines** incl. two non-linear ones on different entities: PayrollRun carries *parallel* dimensions (`processing_status` × `funding_status`, with a FAILED→DEBIT_PENDING funding cycle), OnboardingPacket and HrTicket are *cyclic*, ClientCompany cycles ACTIVE↔SUSPENDED.
- **2 concurrency rules** (OCC only): `packet-create-stale-employee` (WorksiteEmployee.version, supersede semantics) and `invoice-payment-stale-invoice` (ClientInvoice.version, repeatable payments).
- **10 calculations**, 3 of them dual-variant across different domains: `wc_premium` (ESTIMATED vs AUDITED), `benefit_premium_rating` (COMPOSITE vs AGE_BANDED), `tax_filing_aggregate` (CASH vs ACCRUAL). Plus `payroll_line_taxes` (SS/FUTA wage-base caps, additional-Medicare threshold, round-per-line-then-sum pinned), `admin_fee` (tier → min/max collar → conditional delinquency surcharge), `aca_fte_count`, `client_outstanding_balance`, `benefit_pool_status`, `client_invoice_totals`, `employee_ytd_accumulators`.
- **27 validation rows** (priority 1 → 81), **49 endpoints** (incl. `POST /_clock/set_current_utc` with fixed default `2026-05-01T00:00:00Z`), **41 error codes**, **6 roles** (PeoAdmin / PayrollSpecialist / HrAdvisor opaque; ClientAdmin → entity_backed:ClientCompany; Employee → entity_backed:WorksiteEmployee; Anonymous for the 401 boundary).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** — 9 rules × 2 = **18 instances**, e.g. WC estimated-vs-audited (3000 vs 2500 cents) and pool composite-vs-age-banded (90000 vs 92000); admin-fee mode (a) vs per-line-tax-rounding mode (b) (16500, not 16501); depth-4 cascades from approve (run→invoice→lines→client ledger = 246510) and from terminate (employee→enrollment→seat count→pool_status FULL→AT_RISK); state-vs-fiscal and temporal-vs-constraint priority conflicts; SS wage-base exactly-at-cap (ss tax 0) and ACA ALE exactly-50-FTE boundaries on different endpoints; half-open coverage adjacency vs closed pay-period touching; void-restores-balance and cancel-restores-seats invariants.

**SCAFFOLD_CORNER_DESIGN.yaml** — **46 instances** across 9 guide sections (3 `excluded_because` stubs pointing at §1.8 instances): defaults/not-found/required-fields/enums/pagination, invalid & terminal transitions, packet revision limit, HR-ticket full cycle, suspension→reactivation, clock-driven enrollment activation, pre-tax deduction math, experience-mod scaling, CASH/ACCRUAL divergence, all error triggers, RBAC/ownership denials, and both OCC stale-version 412s.

All formula-derived assertion values were computed in Python against the declared constants and written as literals.

## Step 3: Copy shared files — 2026-07-11T14:02:45.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0591_peo_hr_outsourcing/workspace/INSTRUCTION.md`.
