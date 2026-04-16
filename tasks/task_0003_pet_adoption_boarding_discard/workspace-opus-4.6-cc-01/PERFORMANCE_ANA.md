# Performance Analysis: workspace-opus-4.6-cc-01

**Result: 90/252 (35.7%)**

## Root Causes

### 1. VaccinationRecord field name mismatch — 158 failures (97.5%)

The implementation requires `vaccine_type`. The test suite sends `vaccine_name`. The PRD uses prose ("RABIES vaccination", "vaccination requirements") without explicit JSON field names, so the model inferred a plausible synonym that doesn't match the test contract.

Since vaccination compliance gates `AVAILABLE` status — the prerequisite for all adoption and boarding workflows — this single mismatch cascades through the entire dependency graph. 158 of 162 failures die at setup.

### 2. VaccinationRecord entity incomplete — masked by #1

Tests also expect `batch_number`, `veterinarian_name`, and computed `is_valid` on responses. The implementation stores none of these — it accepts only 4 fields and derives `administered_by` from the auth header instead of accepting explicit `veterinarian_name` input.

### 3. Further field-name divergences — masked by #1

| Entity | Test expects | Impl uses |
|---|---|---|
| ComplianceHold | `hold_type` (enum) | absent |
| FeeInvoice | `reference_type` | `invoice_type` |
| FeeInvoice | `tax_amount` | `tax` |
| FeeInvoice | `discount_amount` | `discount` |
| ComplianceHold | `imposed_by` | `placed_by` |

## Model Weaknesses

**Synonym substitution over literal fidelity.** The PRD describes entities in prose without JSON schemas. The model inferred semantically reasonable names (`vaccine_type`, `invoice_type`, `tax`) that diverge from test expectations (`vaccine_name`, `reference_type`, `tax_amount`). In black-box testing, semantic equivalence is irrelevant — only exact names pass.

**Opinionated field pruning.** The model dropped fields it judged unnecessary (`batch_number`, `hold_type`, `is_valid`) and replaced an explicit input (`veterinarian_name`) with implicit auth-header derivation. Engineering judgment overriding spec compliance.

**No critical-path self-verification.** VaccinationRecord is the root of the dependency graph. A single mental walkthrough — create record, check compliance, make available — would have caught this before it cascaded to 158 failures.

## What Passed

90 tests on paths bypassing vaccination: Shelter/Animal/Adopter CRUD, FeeSchedule CRUD, RBAC, SQL injection, mass assignment. Business logic is largely correct — failure is at the interface contract layer.
