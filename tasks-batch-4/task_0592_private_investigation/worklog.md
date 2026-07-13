# Worklog — task_0592_private_investigation

## Step 1: Create task directory — 2026-07-11T00:00:00.000Z

Task directory `./tasks/task_0592_private_investigation` (with `workspace/`) was pre-created and reserved by the invoker. Index-scanning skipped per instructions; no directory created or renamed.

## Step 2: Generate scaffold (Expert difficulty) — 2026-07-11T22:02:00.000Z

Lint is clean on the first run. Here is the verdict block verbatim:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_0592_private_investigation/SCAFFOLD.yaml
  Difficulty design:  tasks/task_0592_private_investigation/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_0592_private_investigation/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    62
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     45
  Calls scanned (§1.8+§1.9):  698

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## What was generated

Three files under `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0592_private_investigation/`:
- `SCAFFOLD.yaml` (§1.0–§1.7, no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

**Complexity profile (Expert):** primary archetype `compliance_audit` + secondary `temporal_windowing`; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers; topology `flat`; shape `cyclic`; role model `segregation_of_duties`; consistency `immediate`.

**Surface:** 14 entities (Client, Case, RetainerLedgerEntry, Investigator, License, Assignment, SurveillanceSession, EvidenceItem, CustodyEvent, SkipTraceSearch, InvestigationReport, ExpenseEntry, Invoice, CourtTestimony) · 9 state machines · 6 calculations · 34 validations · 62 endpoints · 45 errors · 5 roles (CaseManager, Investigator[entity_backed], ComplianceOfficer, ClientContact[entity_backed], PlatformAdmin) · 2 OCC rules (both on `Case.version`: report-create-supersede and invoice-create-supersede, 412 `ERR_STALE_CASE_VERSION`).

**Key mechanics:** Case cycle ACTIVE⇄SUSPENDED driven by the retainer-posture recompute; report revision cycle PEER_REVIEW→REVISION_REQUESTED→PEER_REVIEW; EvidenceItem parallel dimensions (custody_state × redaction_state on one row); two depth-3 cascades from different triggers (case close → assignment release → session abort → evidence seal; expense approve → DRAW → case suspend → search denial); dual-variant `invoice_totals` (PROVISIONAL 38124 vs FINAL 32724 on identical data) and `redaction_score` (AUTHOR_SELF 17 vs COMPLIANCE 50); pinned per-line rounding (labor 25000, not 24999) and a subtotal-keyed admin-fee tier; two overlap semantics on different resources (half-open no-buffer session overlap on the Investigator vs closed-interval 120-minute buffer on the Case); two conserved quantities (retainer cents, billable minutes). Logical clock `/_clock/set_current_utc` with the mandated `2026-05-01T00:00:00Z` default.

**§1.8:** 9 rule_ids × 2 = 18 instances, every formula-derived assert pre-computed as a literal.
**§1.9:** 51 instances across 9 sections (entities 7, state_machines 10, calculations 4, validations 14, endpoints 1, rbac 4, cross_cutting_layers 3, errors 7, consistency_model 1), of which 6 are `excluded_because` stubs citing §1.8 instances by name.

**One deliberate deviation to flag:** endpoint count (62) and error count (45) exceed the Expert guideline bands (20–32 / 18–30). The scenario mandates eight distinct subdomains (intake/retainer, assignment/licensing, surveillance/evidence chain, skip-trace, reporting, expense/hourly billing, redaction, court scheduling), and each declared state needed a reachable path from empty-DB (per §1.5 testability-completeness). I kept per-entity 404s and used filtered-list reverse-reachability GETs to keep the read surface as small as possible; no endpoint exists purely to pad the count.

## Step 3: Copy shared files — 2026-07-11T22:03:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0592_private_investigation/workspace/INSTRUCTION.md`.
