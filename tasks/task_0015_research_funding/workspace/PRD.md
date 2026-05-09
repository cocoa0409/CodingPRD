# Research Funding API — Product Requirements Document

## 1. Introduction

University research operations sit at the intersection of academic ambition and fiduciary discipline. A principal investigator drafts a proposal and prepares a category-level budget; peer reviewers weigh in; a research administration office decides whether the work goes forward; once approved, the project enters an active operating life of reimbursements, mid-flight budget reallocations, and compliance pre-screening; and finally a closing audit reconciles deliverables, computes execution rates, settles residual funds, and triggers a final indirect-cost allocation. Each of these phases is governed by funding-agency rules that vary by source — a national grant cannot be treated like an enterprise commission, and an internal seed fund follows different residual-fund conventions still.

This document defines the REST API for that workflow. It specifies the shape of every resource, the state machines that govern lifecycle transitions, the calculations that drive budget execution rates and indirect-cost allocations, the validation rules layered on top of submissions and approvals, and the role-based segregation of duties between principal investigators, department approvers, finance officers, research administrators, audit officers, and peer reviewers. The system is event-driven: budget mutations and reimbursement state changes append rows to an immutable audit log, and the close of an audit cascades through the project record into a single global indirect-cost recalculation. Implementations must honor every threshold, every priority order, and every concurrency guarantee expressed in this document — these are the contract surface against which conformance is measured.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must include two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the user's role. If either header is missing or empty, the request is rejected with `ERR_MISSING_USER_CONTEXT` (HTTP 400). If the role is well-formed but lacks permission for the requested operation under the role-based access control matrix, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The system recognizes the following roles, spelled exactly as shown:

- `PrincipalInvestigator` — owns a project record. The principal investigator drafts and submits projects, drafts and submits budget adjustments and reimbursements, performs the first-stage `pi-approve` and `rework` on reimbursements, and submits closing audits.
- `DepartmentApprover` — performs department-level approvals on budget adjustments and reimbursements, and (jointly with `FinanceOfficer`) may reject either.
- `FinanceOfficer` — performs finance-level approvals on budget adjustments, finance-approves reimbursements, marks reimbursements as paid, runs indirect-cost allocations, and (jointly with `DepartmentApprover`) may reject adjustments and reimbursements. Finance officers may also read audit logs.
- `ResearchAdmin` — approves, rejects, and activates projects; creates and patches compliance rules.
- `AuditOfficer` — flags closing audits for rectification, closes audits, and reads audit logs.
- `PeerReviewer` — appends peer reviews on projects.
- `TestDriver` — a test-only role used to advance the system clock and synthesize external events. It is never used in production.
- `Any` — a label used in the endpoint table to mean "any of the above authenticated roles is permitted to read".

For every role above, `X-User-ID` is an opaque operator identifier and is not tied to any persisted entity row. The server may record it (for example, as the `actor_id` written on each `AuditLog` row, as the `principal_investigator_id` captured at project creation, or as the `reviewer_id` on a peer review submission), but it does not compare `X-User-ID` to any entity's `id`. Ownership checks instead compare `X-User-ID` to a foreign-key field captured earlier on the resource: the `principal_investigator_id` on a project is the canonical example, and the corresponding rejection on an owner-only operation is `ERR_NOT_PROJECT_OWNER` (HTTP 403).

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 100,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
- The `error_id` is a unique, machine-readable string that identifies the specific error.
- The `message` provides a human-readable explanation of what went wrong.

### 2.3. Pagination

List endpoints accept two optional query parameters: `limit` and `offset`. The default value of `limit` is 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0, with a minimum of 0 and no fixed upper bound (subject to data set size). A `limit` outside the inclusive range from 1 to 100, or an `offset` strictly less than 0, is rejected with `ERR_INVALID_PAGINATION_PARAMETERS` (HTTP 400). Results are sorted by `created_at` ascending unless an endpoint explicitly states otherwise. Each list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object: `total_count` is the total number of records matching the filter, and `has_more` is true exactly when more records exist beyond the current page.

### 2.4. Common Resource Properties

Every resource carries a server-minted `id` formatted as a UUID with no type prefix. Mutable resources additionally carry `created_at`, `updated_at`, and `version`: `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits, and `version` is a non-negative integer that starts at 1 on creation and increments by exactly 1 on every server-side mutation that changes the resource's persisted fields. Two of the entities — `PeerReview`, `IndirectCostAllocation`, and `AuditLog` — are immutable append-only records and therefore carry only `id` and `created_at`; they do not have `updated_at` or `version`. (For `AuditLog`, the event time is additionally exposed as `occurred_at`, alongside `created_at`.)

### 2.5. Optimistic Concurrency Control

Endpoints that mutate a resource accept an optional `version` field in their request body. When a client supplies `version`, the server compares it to the current persisted version of the target resource: if they match, the mutation proceeds and `version` increments by 1; if they differ, the request is rejected with `ERR_STALE_BUDGET_VERSION` (HTTP 409) for budget-pinned operations, or with the resource-state errors described in §3 for other contention scenarios. When `version` is omitted from the body, the optimistic check is skipped. The OCC mechanism is reused inside the budget-adjustment workflow: at submission time, the system captures `pinned_budget_versions` — a map from each affected `BudgetItem` `id` to that item's current `version` — and re-checks these pins at finance approval to catch any intervening mutation.

### 2.6. Nested Resource Path Validation

Several endpoints take more than one path identifier (for example, peer reviews and budget items are nested under a project). Path identifiers are resolved left-to-right against the database. If any segment fails to resolve to an existing row, the request is rejected with the appropriate not-found error for that resource — `ERR_PROJECT_NOT_FOUND`, `ERR_BUDGET_ITEM_NOT_FOUND`, `ERR_BUDGET_ADJUSTMENT_NOT_FOUND`, `ERR_REIMBURSEMENT_NOT_FOUND`, `ERR_CLOSING_AUDIT_NOT_FOUND`, `ERR_COMPLIANCE_RULE_NOT_FOUND`, `ERR_ALLOCATION_RUN_NOT_FOUND`, or `ERR_PEER_REVIEW_NOT_FOUND` — all returning HTTP 404. Resolution stops at the first segment that fails.

### 2.7. Validation Priority

Many endpoints layer multiple validation rules. The system evaluates these in a fixed priority order so that the surfaced error is deterministic: first, header presence (rejecting with `ERR_MISSING_USER_CONTEXT`); then RBAC (`ERR_INSUFFICIENT_PERMISSIONS`); then path-id existence (returning the appropriate not-found error); then state-machine eligibility (`ERR_INVALID_STATE` and the state-specific variants such as `ERR_PROJECT_NOT_ACTIVE`, `ERR_PROJECT_NOT_CLOSING`, `ERR_PROJECT_NOT_YET_STARTED`, `ERR_BUDGET_NOT_APPROVED`, and `ERR_OPEN_REIMBURSEMENTS_EXIST`); then business safety checks in this order — invoice authenticity (`ERR_INVOICE_NOT_AUTHENTIC`), attachment completeness (`ERR_ATTACHMENTS_INCOMPLETE`), and compliance pre-screen blocks (`ERR_COMPLIANCE_BLOCK`); then business referential integrity, starting with category match (`ERR_CATEGORY_MISMATCH`); then business constraints, beginning with the zero-sum check (`ERR_ADJUSTMENT_NOT_ZERO_SUM`), then the per-line non-negativity check (`ERR_NEGATIVE_BUDGET`), then the rework-count cap (`ERR_REWORK_LIMIT_EXCEEDED`), then the peer-review consensus check (`ERR_REVIEW_CONSENSUS_NOT_MET`); then business temporal checks (`ERR_PROJECT_NOT_YET_STARTED` for project lifecycle and `ERR_INVOICE_DATE_OUT_OF_RANGE` for reimbursement creation); then version pinning (`ERR_STALE_BUDGET_VERSION`); then fiscal capacity (`ERR_BUDGET_INSUFFICIENT`); and finally the audit-related and uniqueness checks (`ERR_DELIVERABLES_INCOMPLETE`, `ERR_RESIDUAL_ACTION_NOT_ALLOWED`, `ERR_FINDINGS_NOT_RECTIFIED`, `ERR_DUPLICATE_INVOICE_NUMBER`, and the pagination bounds check `ERR_INVALID_PAGINATION_PARAMETERS`). Generic input-shape errors surface as `ERR_INVALID_INPUT` (HTTP 400). Whenever two checks could both fail, the lower-priority error must not mask the higher-priority one — so, for instance, an unauthenticated request with a malformed body returns `ERR_MISSING_USER_CONTEXT` rather than `ERR_INVALID_INPUT`.

### 2.8. Precision and Rounding

Monetary amounts (`requested_amount`, `approved_amount`, `spent_amount`, `remaining_amount`, `total_budget`, `total_reimbursed`, `indirect_cost_amount`, `allocated_amount`, and the reimbursement `amount`) are recorded in CNY to two decimal places, rounded half-up at the point of each calculation. The execution-rate fields `budget_execution_rate` and `forward_execution_rate` are recorded to four decimal places, rounded half-up. The `allocation_rate` field on an indirect-cost allocation is recorded to four decimal places, rounded half-up. The minted `project_code` is exact and is never rounded.

### 2.9. Cascade and Side-Effect Discipline

Several operations mutate more than one resource. Whenever a side effect changes a persisted field on a resource, the resource's `updated_at` advances to the time of the operation and its `version` increments by exactly 1. When a single operation produces a chain of mutations — for example, finance-approving a budget adjustment writes new `approved_amount` values across multiple `BudgetItem` rows and refreshes `total_budget` on the parent project — every affected `BudgetItem` advances independently (each gets its own version bump and `updated_at` refresh) and the project record likewise advances. Closing-audit close cascades into the project record (transitioning it to `CLOSED`) and into a fresh indirect-cost allocation snapshot for the project; both downstream effects are part of the same atomic operation.

### 2.10. Auditability

Mutations on budget items, budget adjustments, and reimbursements are recorded in append-only `AuditLog` rows. The `subject_type` is one of `BUDGET_ITEM`, `BUDGET_ADJUSTMENT`, or `REIMBURSEMENT`, and `subject_id` references the row. The `action` is one of `CREATE`, `UPDATE`, `APPROVE`, `REJECT`, `REWORK`, `PAY`, `LOCK`, or `ADJUST`. Each row captures the acting user as `actor_role` and `actor_id` (copied from `X-User-Role` and `X-User-ID` at the time of the event), the field-level pre-image as `before_snapshot`, the field-level post-image as `after_snapshot`, and the event time as `occurred_at` (ISO 8601 UTC, three fractional digits).

### 2.11. Funding-Source Enumerations and Categories

The `funding_source` of a project is one of `NATIONAL`, `PROVINCIAL`, `ENTERPRISE`, or `INTERNAL`. Budget categories — used as both `BudgetItem.category` and reimbursement `expense_category` — are `PERSONNEL`, `EQUIPMENT`, `MATERIALS`, `TRAVEL`, `CONFERENCE`, and `OUTSOURCING`. A peer review's `recommendation` is one of `APPROVE`, `REJECT`, or `REVISE`. A closing audit's `residual_fund_action` is one of `RETURN`, `REALLOCATE`, or `CARRYOVER`, with the permitted set varying by funding source as described in §3.7. An indirect-cost allocation's `allocation_base` is one of `DIRECT_COST`, `PERSONNEL_COST`, or `FLOOR_AREA`. A compliance rule's `severity` is one of `BLOCK`, `ESCALATE`, or `WARN`, and its `applies_to_funding_source` and `applies_to_category` accept the corresponding source/category enumerations plus the wildcard `ALL`. Audit findings carry a `severity` of `LOW`, `MEDIUM`, or `HIGH`.

## 3. Business Logic & Workflows

### 3.1. Project Initiation, Peer Review, and Approval

A research project begins life when a principal investigator drafts a proposal. Project creation accepts a `title` (between 1 and 200 characters), a `principal_investigator_id` (which must equal the calling `X-User-ID` at creation), a `department_id`, a `funding_source` chosen from the four enumerated sources, a `proposal_text` carrying the abstract, a `requested_amount` representing the requested total funding in CNY (non-negative, two decimal places), and the `planned_start_date` and `planned_end_date` expressed as Unix epoch seconds. The new project lands in `DRAFT` status with no `project_code` yet — the code is null until approval.

While the project is in `DRAFT`, the principal investigator may also append `BudgetItem` rows under the project. Each item names a `category` and a `requested_amount` (CNY, two decimal places, strictly greater than zero). Items created at this stage start in `PENDING` state with `approved_amount` not yet set. Adding budget items is only permitted while the project is in `DRAFT`; once the project leaves draft, the budget composition is fixed except via the formal adjustment workflow.

Submitting the project for review advances `status` from `DRAFT` to `UNDER_REVIEW`. Submission is restricted to the project's principal investigator: `X-User-ID` must equal `principal_investigator_id`, otherwise the request is rejected with `ERR_NOT_PROJECT_OWNER`. Submission additionally enforces three input-shape preconditions: `proposal_text` must be at least 200 characters long (otherwise `ERR_PROPOSAL_TOO_SHORT`), `planned_end_date` must be strictly greater than `planned_start_date` (otherwise `ERR_INVALID_DATE_RANGE`), and `planned_start_date` must be at or after the current server time (otherwise `ERR_START_IN_PAST`).

Once the project is `UNDER_REVIEW`, peer reviewers may append review records. Each review captures the `reviewer_id` (the `X-User-ID` of the acting reviewer), a `score` ranging from 0 to 100, a `recommendation` of `APPROVE`, `REJECT`, or `REVISE`, and free-text `comments`. Peer reviews are immutable once written.

Approval by a `ResearchAdmin` advances `UNDER_REVIEW → APPROVED`. The decision requires that at least three peer reviews exist for the project (otherwise `ERR_INSUFFICIENT_REVIEWS`), and that the count of reviews with `recommendation` set to `APPROVE` is strictly greater than the count of reviews with `recommendation` set to `REJECT` (otherwise `ERR_REVIEW_CONSENSUS_NOT_MET`). On approval, the system mints `project_code` and writes it to the project. The code is composed by extracting the four-digit calendar year from the current UTC time, mapping the project's `funding_source` to a three-letter abbreviation — `NATIONAL` to `NTL`, `PROVINCIAL` to `PRV`, `ENTERPRISE` to `ENT`, and `INTERNAL` to `INT` — and appending a four-digit zero-padded sequence number that increases monotonically per (year, source) pair starting at 0001. The three components are joined by hyphens, yielding strings such as `2026-NTL-0007`. The sequence counter is allocated under a per-(year, source) lock; if two project approvals race for the same (year, source) and the retry budget is exhausted, the loser receives `ERR_PROJECT_CODE_COLLISION`. Approval also transitions every `BudgetItem` of the project from `PENDING` to `APPROVED`, copying each item's `requested_amount` into its `approved_amount`, refreshes the project's `total_budget` to the sum of those approved amounts, and appends one `AuditLog` row per approved budget item with `action` set to `APPROVE`.

Rejection by a `ResearchAdmin` advances `UNDER_REVIEW → REJECTED`. Rejection still requires at least three peer reviews (otherwise `ERR_INSUFFICIENT_REVIEWS`), but no consensus check is applied. On rejection, all `BudgetItem` rows remain in `PENDING` — that is their terminal state for a rejected project — and no project code is minted.

Activation by a `ResearchAdmin` advances `APPROVED → ACTIVE`. The activation precondition is temporal: the current server time must be at or after `planned_start_date`, otherwise the request is rejected with `ERR_PROJECT_NOT_YET_STARTED`. The same error code is used when a too-early submit is attempted, since both endpoints share this temporal check.

### 3.2. Active Operations: Budget Adjustments

Once a project is in `ACTIVE`, its principal investigator may file a `BudgetAdjustment` to reallocate funds between budget items. The adjustment payload carries the target `project_id`, an array of `line_changes` — each entry naming a `budget_item_id` and a `delta_amount` (positive for an increase, negative for a decrease) — and a free-text `justification`. The adjustment is created in `DRAFT` with all of `pi_decision`, `dept_decision`, and `finance_decision` set to `PENDING`.

Submitting the adjustment for review advances `DRAFT → UNDER_REVIEW`. Submission performs four checks. First, the parent project's `status` must be `ACTIVE`, otherwise the request is rejected with `ERR_PROJECT_NOT_ACTIVE`. Second, the deltas across `line_changes` must sum to zero within an absolute tolerance of 0.01 CNY (the rule is a zero-sum reallocation; otherwise the request is rejected with `ERR_ADJUSTMENT_NOT_ZERO_SUM`). Third, for each line, the affected `BudgetItem`'s current `approved_amount` plus the proposed `delta_amount` must be at or above zero (otherwise `ERR_NEGATIVE_BUDGET`). Fourth, `justification` must be at least 20 characters long (otherwise `ERR_JUSTIFICATION_TOO_SHORT`). On a successful submission the adjustment's `status` advances to `UNDER_REVIEW`, `pi_decision` is set to `APPROVED`, and the system captures a snapshot of every affected budget item's current `version` into `pinned_budget_versions` — a map keyed by `budget_item_id`. The pinned versions are the optimistic-concurrency anchor for the rest of the adjustment workflow.

A `DepartmentApprover` then reviews the adjustment. Department approval keeps `status` at `UNDER_REVIEW` (a self-loop) and sets `dept_decision` to `APPROVED`. The precondition is that `dept_decision` is currently `PENDING` — a second department approval against an already-decided adjustment is rejected with `ERR_ALREADY_DECIDED`. The same code covers the race in which two department approvers act simultaneously on the same adjustment: at most one wins, and the loser receives `ERR_ALREADY_DECIDED`.

Finance approval by a `FinanceOfficer` is the commit point: it advances `UNDER_REVIEW → APPROVED` and mutates the underlying budget. Finance approval requires that `dept_decision` already equals `APPROVED` (otherwise `ERR_DEPT_DECISION_PENDING`), that for every line the current `BudgetItem.version` still equals the value pinned in `pinned_budget_versions[budget_item_id]` (otherwise `ERR_STALE_BUDGET_VERSION`), and that a per-line agency-rule revalidation passes (otherwise `ERR_AGENCY_RULE_VIOLATION`). On commit, each line's `delta_amount` is applied to the matching `BudgetItem`'s `approved_amount`; each affected `BudgetItem`'s `version` increments by 1 and its `updated_at` is refreshed; the parent project's `total_budget` is recomputed from the new approved amounts; one `AuditLog` row is appended per affected line with `subject_type` set to `BUDGET_ITEM` and the field-level before/after snapshots; and one additional `AuditLog` row is appended with `subject_type` set to `BUDGET_ADJUSTMENT` and `action` set to `ADJUST`. Two simultaneous finance-approvals racing on the same adjustment serialize on `BudgetAdjustment.status`: at most one finance-approve succeeds, and the loser receives `ERR_ALREADY_DECIDED`. A different race occurs when a finance-approve and a separate adjustment touching the same `BudgetItem` commit nearly simultaneously — whichever commits second finds that its pinned version no longer matches the current `BudgetItem.version` and is rejected with `ERR_STALE_BUDGET_VERSION`.

Either a `DepartmentApprover` or a `FinanceOfficer` may reject the adjustment from `UNDER_REVIEW`, advancing it to `REJECTED`. Rejection sets the deciding role's `*_decision` field to `REJECTED` and performs no mutation to any `BudgetItem`. The reject endpoint accepts a body field `rejection_reason`, which is required and surfaced via `ERR_REJECTION_REASON_REQUIRED` when missing or empty.

### 3.3. Active Operations: Reimbursements and the Reject–Rework Loop

Reimbursements are the throughput pathway through which a project actually consumes its budget. The principal investigator drafts a reimbursement under a project (`project_id`) and ties it to a specific `BudgetItem` (`budget_item_id`), naming the `expense_category`, the `amount` (CNY, two decimals, strictly greater than zero), the `invoice_number`, the `invoice_date` (Unix epoch seconds), the client-supplied authenticity flag `invoice_authenticated`, the array of `attachments` (each having a `filename` and a `kind`), and the `vendor_id`. Three creation-time invariants are enforced. The `expense_category` must equal the linked `BudgetItem`'s `category` (otherwise `ERR_CATEGORY_MISMATCH`). The `invoice_number` must be unique within the parent project, compared case-insensitively (otherwise `ERR_DUPLICATE_INVOICE_NUMBER`). The `invoice_date` must lie within the inclusive range from the project's `planned_start_date` up to the current server time (otherwise `ERR_INVOICE_DATE_OUT_OF_RANGE`). The new record lands in `DRAFT` with `rework_count` set to 0, `rejection_reason` null, and all three of `pi_decision`, `dept_decision`, and `finance_decision` set to `PENDING`.

Submitting the reimbursement advances `DRAFT → SUBMITTED`. Submission requires that the parent project is `ACTIVE` (otherwise `ERR_PROJECT_NOT_ACTIVE`) and that the linked `BudgetItem`'s `status` is `APPROVED` (otherwise `ERR_BUDGET_NOT_APPROVED`). The category-match invariant applies again at submit time, in case the linked budget item changed identity — the surfaced code is `ERR_CATEGORY_MISMATCH`. The `invoice_authenticated` flag must be true — a falsy value is treated as a `BLOCK`-severity safety violation and rejected with `ERR_INVOICE_NOT_AUTHENTIC`. The `attachments` array must contain at least one entry whose `kind` is `INVOICE` and at least one entry whose `kind` is `RECEIPT`; if either kind is absent, the request is rejected with `ERR_ATTACHMENTS_INCOMPLETE`. The `rework_count` must be at most 3 (any submission attempt with `rework_count` already at 4 or higher is rejected with `ERR_REWORK_LIMIT_EXCEEDED`).

Submission also runs the **compliance pre-screen** described in §3.4. If the pre-screen produces any finding with `severity` set to `BLOCK`, the submission rolls back to `DRAFT` and the request is rejected with `ERR_COMPLIANCE_BLOCK`. Otherwise, the produced findings (each carrying a `rule_id` and a `severity`) are written to `compliance_findings` on the reimbursement, the `status` advances to `SUBMITTED`, and `rejection_reason` is cleared (set to null).

PI approval by the project's principal investigator advances `SUBMITTED → UNDER_REVIEW`. The acting `X-User-ID` must equal the project's `principal_investigator_id` (otherwise `ERR_NOT_PROJECT_OWNER`). Additionally, the reimbursement's `compliance_findings` must not contain any `ESCALATE`-severity finding that lacks a sole-source justification override; otherwise the request is rejected with `ERR_ESCALATION_PENDING`. On success, `pi_decision` is set to `APPROVED`.

Department approval by a `DepartmentApprover` keeps `status` at `UNDER_REVIEW` (self-loop) and sets `dept_decision` to `APPROVED`. The precondition is that `pi_decision` already equals `APPROVED`; otherwise the request is rejected with `ERR_PI_DECISION_PENDING`.

Finance approval by a `FinanceOfficer` advances `UNDER_REVIEW → APPROVED` and sets `finance_decision` to `APPROVED`. It requires that `dept_decision` already equals `APPROVED` (otherwise `ERR_DEPT_DECISION_PENDING`) and — critically — that the linked `BudgetItem`'s `remaining_amount` is at or above the reimbursement's `amount` (otherwise `ERR_BUDGET_INSUFFICIENT`, HTTP 402). The fiscal capacity check is the synchronization point against budget adjustments: when a reimbursement finance-approve and a budget-adjustment finance-approve both target the same `BudgetItem`, optimistic concurrency on `BudgetItem.version` ensures that whichever transaction commits second revalidates `remaining_amount`; if the second writer's required amount would now exceed the just-recomputed `remaining_amount`, it is rejected with `ERR_BUDGET_INSUFFICIENT`.

Marking the reimbursement paid by a `FinanceOfficer` advances `APPROVED → PAID`. This is the terminal happy-path transition. On commit, the reimbursement's `amount` is added to the linked `BudgetItem`'s `spent_amount`, the item's `remaining_amount` is recomputed (it equals `approved_amount` minus `spent_amount`), the item's `version` increments by 1, and its `updated_at` is refreshed. The same amount is added to the parent project's `total_reimbursed`. Two `AuditLog` rows are appended: one with `subject_type` set to `REIMBURSEMENT` and `action` set to `PAY`, and one with `subject_type` set to `BUDGET_ITEM` and `action` set to `UPDATE` capturing the spent-amount delta. Two simultaneous mark-paid calls on the same reimbursement serialize on `Reimbursement.status`: at most one PAID transition succeeds, and the loser receives `ERR_INVALID_STATE`.

Rejection from review forms the project's reject-rework loop. The principal investigator may explicitly reset a `SUBMITTED` reimbursement to `DRAFT` via the rework path — this is allowed only while `rework_count` is strictly less than 3 (otherwise `ERR_REWORK_LIMIT_EXCEEDED`); on success, `status` returns to `DRAFT`, `rework_count` increments by 1, and all three of `pi_decision`, `dept_decision`, and `finance_decision` are reset to `PENDING`. Either a `DepartmentApprover` or a `FinanceOfficer` may reject from `UNDER_REVIEW`. Rejection requires that `rework_count` is strictly less than 3 (otherwise `ERR_REWORK_LIMIT_EXCEEDED`) and that the request body carries a non-empty `rejection_reason` (otherwise `ERR_REJECTION_REASON_REQUIRED`); on success, `status` returns to `DRAFT` (the rejection-rework cycle is `DRAFT → SUBMITTED → UNDER_REVIEW → DRAFT`), the deciding role's `*_decision` is set to `REJECTED`, `rework_count` increments by 1, and `rejection_reason` is recorded from the body. When `rework_count` reaches 3 and a further reject is attempted from `UNDER_REVIEW`, the system performs the terminal automatic transition `UNDER_REVIEW → REJECTED`.

Beginning the closing of a project is also gated by reimbursement state. The transition `ACTIVE → CLOSING` is initiated by the project's principal investigator (the acting `X-User-ID` must equal `principal_investigator_id`, otherwise `ERR_NOT_PROJECT_OWNER`); it requires that no reimbursement under the project remains in `SUBMITTED` or `UNDER_REVIEW`, otherwise the request is rejected with `ERR_OPEN_REIMBURSEMENTS_EXIST`. On commit, the project's `status` advances to `CLOSING` and every `BudgetItem` belonging to the project transitions to `LOCKED` — no further `BudgetAdjustment` and no further `Reimbursement` may be created against the project once locked.

### 3.4. Compliance Pre-Screen

The compliance pre-screen runs as part of reimbursement submission. It evaluates the reimbursement against every active `ComplianceRule` (those with `active` set to true) whose `applies_to_funding_source` matches the parent project's `funding_source` (or is `ALL`) and whose `applies_to_category` matches the reimbursement's `expense_category` (or is `ALL`). Each rule is identified by a short `rule_code` (such as `PER_DIEM_CAP`, `EQUIP_THRESHOLD`, `COI`, or `SOLE_SOURCE_JUSTIFICATION`) and carries a JSON object of `parameters` plus a `severity` of `BLOCK`, `ESCALATE`, or `WARN`. A `BLOCK` finding rejects the submission outright; an `ESCALATE` finding is appended to the reimbursement's `compliance_findings` and must be cleared (via a sole-source justification override) before PI approval; a `WARN` finding is logged only.

Three concrete screens are mandated:

- **Per-diem standard.** Applied to reimbursements whose `expense_category` is `TRAVEL`. The matching rule (`rule_code` `PER_DIEM_CAP`) supplies a `daily_cap` parameter. If the reimbursement's `amount` is strictly greater than the daily cap, an `ESCALATE`-severity finding is appended to `compliance_findings` with `rule_id` set to `PER_DIEM_CAP`. Equality with the cap (an `amount` exactly equal to `daily_cap`) is allowed — only strictly-greater amounts trigger the finding.
- **Equipment threshold.** Applied to reimbursements whose `expense_category` is `EQUIPMENT`. The matching rule (`rule_code` `EQUIP_THRESHOLD`) supplies a `threshold_amount` parameter. If the reimbursement's `amount` is at or above the threshold, an `ESCALATE`-severity finding is appended with `rule_id` set to `EQUIP_THRESHOLD`. Note the boundary direction differs from the per-diem rule: the equipment screen fires on greater-than-or-equal, so a reimbursement exactly at the threshold escalates.
- **Conflict-of-interest.** Applied to reimbursements regardless of category. If the reimbursement's `vendor_id` equals the parent project's `principal_investigator_id`, or if the `vendor_id` equals the project's `department_id`, a `BLOCK`-severity finding is appended with `rule_id` set to `COI`, and the submission is rejected with `ERR_COMPLIANCE_BLOCK`.
- **Sole-source justification.** A separate rule (`rule_code` `SOLE_SOURCE_JUSTIFICATION`) is the override channel for `ESCALATE` findings: when present and resolved on the reimbursement, it clears the gating effect at PI approval. An unresolved `ESCALATE` finding without such an override produces `ERR_ESCALATION_PENDING` at PI approval.

A `ResearchAdmin` may add new compliance rules by supplying `rule_code`, `applies_to_funding_source`, `applies_to_category`, `parameters`, `severity`, and an optional `active` flag (defaulting to true). The same role may patch an existing rule — toggling `active`, raising or lowering `severity`, or rewriting `parameters` — but every patch must include a `version` for the optimistic-concurrency check; on a successful patch, `version` increments by 1.

### 3.5. Closing Audit

When a project enters `CLOSING`, its principal investigator prepares a `ClosingAudit`. The audit is created with the parent `project_id`, the array of `deliverables` (each having a `title`, a `kind`, and a `url`), the chosen `residual_fund_action`, and the array of `audit_findings` (each having a `finding_id`, a `severity` of `LOW`, `MEDIUM`, or `HIGH`, a `description`, and a boolean `rectified` flag). At most one closing audit exists per project. The audit lands in `DRAFT`.

Submitting the audit advances `DRAFT → SUBMITTED`. Submission requires that the parent project is in `CLOSING` (otherwise `ERR_PROJECT_NOT_CLOSING`), that the `deliverables` array contains at least one entry whose `kind` is `REPORT` and at least one entry whose `kind` is `DATASET` (otherwise `ERR_DELIVERABLES_INCOMPLETE`), and that the chosen `residual_fund_action` is permitted by the funding-source residual-fund policy in §3.7 (otherwise `ERR_RESIDUAL_ACTION_NOT_ALLOWED`). Successful submission computes both the chronological `budget_execution_rate` and the forward-looking `forward_execution_rate` described in §3.6 and writes them onto the audit.

When the audit contains at least one `audit_findings` entry of `HIGH` severity, an `AuditOfficer` may flag the audit for rectification, advancing `SUBMITTED → RECTIFICATION_REQUIRED`. The flag-rectification endpoint requires that at least one such `HIGH`-severity entry exists; absence yields `ERR_NO_HIGH_FINDINGS`. The principal investigator then resubmits, advancing `RECTIFICATION_REQUIRED → SUBMITTED`. Resubmission requires that every `audit_findings` entry whose `severity` is `HIGH` has `rectified` set to true (otherwise `ERR_HIGH_FINDINGS_NOT_RECTIFIED`).

Closing the audit by an `AuditOfficer` advances `SUBMITTED → CLOSED`. Closure requires that every `audit_findings` entry whose `severity` is either `MEDIUM` or `HIGH` has `rectified` set to true; if any such entry remains unrectified, the request is rejected with `ERR_FINDINGS_NOT_RECTIFIED` (note that `LOW`-severity findings need not be rectified for closure to succeed). On commit, the audit's `status` is set to `CLOSED`, the parent project automatically cascades from `CLOSING` to `CLOSED` as part of the same operation, a final `IndirectCostAllocation` snapshot is written for the project, and the project's `indirect_cost_amount` is set to the resulting `allocated_amount`. The audit's `closing_findings_count` field on the project is the count of `audit_findings` on the latest audit and is zero until the first audit submission.

### 3.6. Execution Rates

A closing audit exposes two execution-rate fields, both computed at submission time and refreshed on each subsequent transition that re-derives them.

The chronological rate, `budget_execution_rate`, is computed as follows. The numerator is the sum of `Reimbursement.amount` across every reimbursement under the project whose `status` is `PAID`. The denominator is the sum of `BudgetItem.approved_amount` across every budget item under the project as of audit submission time (the post-adjustment approved amounts, not the originally requested amounts). When the denominator is zero, `budget_execution_rate` is recorded as 0.0000. Otherwise the rate is the numerator divided by the denominator, rounded half-up to four decimal places.

The forward-looking rate, `forward_execution_rate`, follows the same skeleton with one substitution in the numerator: in addition to `PAID` reimbursements, the numerator also includes the `amount` of every reimbursement whose `status` is `SUBMITTED`, `UNDER_REVIEW`, or `APPROVED`. The denominator and the rounding rule are identical. As a worked illustration, a project with one paid reimbursement of 1000 CNY, one under-review reimbursement of 500 CNY, and a denominator of 2000 CNY has `budget_execution_rate` equal to 0.5000 and `forward_execution_rate` equal to 0.7500.

### 3.7. Residual-Fund Policy

The residual-fund policy maps `funding_source` and `residual_fund_action` (and, for one branch, the chronological `budget_execution_rate`) to a permission decision. The mapping is, exhaustively:

- For a `NATIONAL` project: `RETURN` is permitted; `REALLOCATE` is not permitted; `CARRYOVER` is permitted only when `budget_execution_rate` is at or above 0.95.
- For a `PROVINCIAL` project: `RETURN` is permitted; `REALLOCATE` is not permitted; `CARRYOVER` is permitted only when `budget_execution_rate` is at or above 0.90.
- For an `ENTERPRISE` project: `RETURN` is not permitted; `REALLOCATE` is permitted; `CARRYOVER` is always permitted.
- For an `INTERNAL` project: `RETURN` is permitted; `REALLOCATE` is permitted; `CARRYOVER` is always permitted.

When the chosen `residual_fund_action` is not permitted under this mapping, the audit submission is rejected with `ERR_RESIDUAL_ACTION_NOT_ALLOWED`.

### 3.8. Indirect-Cost Allocation

Indirect cost is the share of project funds attributable to overhead, recovered to a global pool and allocated back across active and closing projects. Allocation runs are launched by a `FinanceOfficer`. A run accepts an `allocation_base` — one of `DIRECT_COST`, `PERSONNEL_COST`, or `FLOOR_AREA` — and an optional `project_id`. When `project_id` is omitted, the periodic-recalculation variant runs across every project whose `status` is `ACTIVE` or `CLOSING`, appending one `IndirectCostAllocation` row per project under a single shared `allocation_run_id`. When `project_id` is supplied, the run is scoped to a single project and uses the previous run's pool remainder as the ceiling — this is the same code path the closing-audit close cascade exercises automatically for a single project.

For each in-scope project, the allocation proceeds in three steps.

**Step 1 — Base value.** The `base_value` is pinned according to the chosen `allocation_base`:

- `DIRECT_COST`: the sum of `Reimbursement.amount` across the project's reimbursements whose `status` is `PAID` and whose linked `BudgetItem.category` is anything other than `OUTSOURCING`.
- `PERSONNEL_COST`: the sum of `Reimbursement.amount` across the project's reimbursements whose `status` is `PAID` and whose linked `BudgetItem.category` is `PERSONNEL`.
- `FLOOR_AREA`: the project's floor area in square metres, supplied as a run-time input on the project record (default 100 when absent).

**Step 2 — Allocation rate.** The `allocation_rate` is read from a fixed table indexed by the project's `funding_source` and the run's `allocation_base`:

- `NATIONAL` project: 0.20 with `DIRECT_COST`, 0.25 with `PERSONNEL_COST`, 0.15 with `FLOOR_AREA`.
- `PROVINCIAL` project: 0.15, 0.18, and 0.12 in the same order.
- `ENTERPRISE` project: 0.10, 0.12, and 0.08.
- `INTERNAL` project: 0.05, 0.06, and 0.04.

A threshold tier reduces this rate. If the project's `total_budget` is strictly greater than 1,000,000 CNY, the rate is decreased by 0.02 — but never below zero (the rate is the maximum of zero and the table value minus 0.02). The resulting rate is recorded to four decimal places.

**Step 3 — Sharing and waterfall remainder.** The raw indirect amount for the project is its `base_value` multiplied by the resolved `allocation_rate`. Across all projects in the run, the sum of these raw amounts is capped at a global pool ceiling of 5,000,000 CNY (`GLOBAL_INDIRECT_POOL`). When the sum of raw amounts is at or below the pool ceiling, every project receives its raw amount in full as `allocated_amount`. When the sum exceeds the ceiling, the capped pool is distributed across projects in descending order of raw amount, with ties broken by lexicographic `project_id` ascending; each project receives the smaller of its raw amount and the pool's remaining capacity (`shared_share` records each project's share weight relative to this distribution). Any rounding remainder accrues to the first project in the descending order — that is, the one with the largest raw amount. The final `allocated_amount` is rounded half-up to two decimal places.

After the run, every affected project has its `indirect_cost_amount` field refreshed to the latest allocated amount written for it.

### 3.9. Test-Driving Capabilities

Two endpoints are provided for test orchestration only and should never be invoked in production. A `TestDriver` may advance the server clock by supplying a `target_iso` ISO 8601 UTC instant — the new clock value must be at or after the current clock value, and subsequent `now()`-dependent transitions (project activation, project submission, reimbursement creation) reflect the new clock. A `TestDriver` may also synthesize an external event for finance, procurement, HR, or funding-agency synchronization by supplying an `event_type` and a `payload`; the call is a production no-op but appends an `AuditLog` row capturing the synthetic event.

## 4. Endpoint Definitions

The conventions are: a successful call that creates a new resource returns HTTP 201; a successful call that reads or modifies an existing resource returns HTTP 200; error statuses follow the Error Code Catalogue in §5. The table below lists method, path, the operation's purpose, and the authorized role(s); request and response shapes are reconstructed from the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/projects` | Create a project draft | `PrincipalInvestigator` |
| GET | `/projects` | List projects (filter by status, funding_source) | `Any` |
| GET | `/projects/{projectId}` | Get a project | `Any` |
| POST | `/projects/{projectId}/submit` | Submit a project for review | `PrincipalInvestigator` |
| POST | `/projects/{projectId}/approve` | Approve a project (mints code, approves budget items) | `ResearchAdmin` |
| POST | `/projects/{projectId}/reject` | Reject a project | `ResearchAdmin` |
| POST | `/projects/{projectId}/activate` | Activate a project | `ResearchAdmin` |
| POST | `/projects/{projectId}/begin-closing` | Move project to closing; locks all budget items | `PrincipalInvestigator` |
| POST | `/projects/{projectId}/peer-reviews` | Append an immutable peer review | `PeerReviewer` |
| GET | `/projects/{projectId}/peer-reviews` | List peer reviews for a project | `Any` |
| POST | `/projects/{projectId}/budget-items` | Add a budget item (only while project DRAFT) | `PrincipalInvestigator` |
| GET | `/projects/{projectId}/budget-items` | List budget items for a project | `Any` |
| GET | `/budget-items/{budgetItemId}` | Get a budget item | `Any` |
| POST | `/budget-adjustments` | Create a budget-adjustment draft | `PrincipalInvestigator` |
| GET | `/budget-adjustments` | List budget adjustments | `Any` |
| GET | `/budget-adjustments/{adjustmentId}` | Get a budget adjustment | `Any` |
| POST | `/budget-adjustments/{adjustmentId}/submit` | Submit for department/finance review | `PrincipalInvestigator` |
| POST | `/budget-adjustments/{adjustmentId}/dept-approve` | Department approval | `DepartmentApprover` |
| POST | `/budget-adjustments/{adjustmentId}/finance-approve` | Finance approval (commits deltas) | `FinanceOfficer` |
| POST | `/budget-adjustments/{adjustmentId}/reject` | Reject (department or finance) | `DepartmentApprover`, `FinanceOfficer` |
| POST | `/reimbursements` | Create a reimbursement draft | `PrincipalInvestigator` |
| GET | `/reimbursements` | List reimbursements | `Any` |
| GET | `/reimbursements/{reimbursementId}` | Get a reimbursement | `Any` |
| POST | `/reimbursements/{reimbursementId}/submit` | Submit reimbursement (runs compliance pre-screen) | `PrincipalInvestigator` |
| POST | `/reimbursements/{reimbursementId}/pi-approve` | PI approves | `PrincipalInvestigator` |
| POST | `/reimbursements/{reimbursementId}/dept-approve` | Department approves | `DepartmentApprover` |
| POST | `/reimbursements/{reimbursementId}/finance-approve` | Finance approves | `FinanceOfficer` |
| POST | `/reimbursements/{reimbursementId}/mark-paid` | Mark reimbursement paid (debits budget item) | `FinanceOfficer` |
| POST | `/reimbursements/{reimbursementId}/reject` | Reject (department or finance); back to DRAFT or terminal | `DepartmentApprover`, `FinanceOfficer` |
| POST | `/reimbursements/{reimbursementId}/rework` | PI moves SUBMITTED back to DRAFT | `PrincipalInvestigator` |
| POST | `/closing-audits` | Create a closing audit (one per project) | `PrincipalInvestigator` |
| GET | `/closing-audits/{auditId}` | Get a closing audit | `Any` |
| POST | `/closing-audits/{auditId}/submit` | Submit audit (computes execution rates) | `PrincipalInvestigator` |
| POST | `/closing-audits/{auditId}/flag-rectification` | Flag for rectification when HIGH findings exist | `AuditOfficer` |
| POST | `/closing-audits/{auditId}/resubmit` | PI resubmits after rectifying HIGH findings | `PrincipalInvestigator` |
| POST | `/closing-audits/{auditId}/close` | Close audit; cascades project to CLOSED + indirect cost run | `AuditOfficer` |
| POST | `/compliance-rules` | Create a compliance rule | `ResearchAdmin` |
| GET | `/compliance-rules` | List compliance rules | `Any` |
| PATCH | `/compliance-rules/{ruleId}` | Patch a compliance rule (active flag, severity, parameters) | `ResearchAdmin` |
| POST | `/allocation-runs` | Run periodic indirect-cost recalculation | `FinanceOfficer` |
| GET | `/allocation-runs/{runId}` | Read an allocation-run snapshot | `Any` |
| GET | `/audit-logs` | List audit logs (filter by subject_type, subject_id) | `AuditOfficer`, `FinanceOfficer` |
| POST | `/_clock/advance` | Test-only: advance the system clock to a target ISO instant | `TestDriver` |
| POST | `/_events/emit` | Test-only: synthesize an external synchronization event | `TestDriver` |

## 5. Error Code Catalogue

Trigger conditions for every error are described in §2 and §3 narratives.

| Error ID | HTTP Status |
|---|---|
| `ERR_MISSING_USER_CONTEXT` | 400 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_NOT_PROJECT_OWNER` | 403 |
| `ERR_PROJECT_NOT_FOUND` | 404 |
| `ERR_BUDGET_ITEM_NOT_FOUND` | 404 |
| `ERR_BUDGET_ADJUSTMENT_NOT_FOUND` | 404 |
| `ERR_REIMBURSEMENT_NOT_FOUND` | 404 |
| `ERR_CLOSING_AUDIT_NOT_FOUND` | 404 |
| `ERR_COMPLIANCE_RULE_NOT_FOUND` | 404 |
| `ERR_ALLOCATION_RUN_NOT_FOUND` | 404 |
| `ERR_PEER_REVIEW_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PROJECT_NOT_ACTIVE` | 409 |
| `ERR_PROJECT_NOT_CLOSING` | 409 |
| `ERR_PROJECT_NOT_YET_STARTED` | 409 |
| `ERR_BUDGET_NOT_APPROVED` | 409 |
| `ERR_OPEN_REIMBURSEMENTS_EXIST` | 409 |
| `ERR_ALREADY_DECIDED` | 409 |
| `ERR_PI_DECISION_PENDING` | 409 |
| `ERR_DEPT_DECISION_PENDING` | 409 |
| `ERR_INSUFFICIENT_REVIEWS` | 409 |
| `ERR_REVIEW_CONSENSUS_NOT_MET` | 409 |
| `ERR_REWORK_LIMIT_EXCEEDED` | 409 |
| `ERR_HIGH_FINDINGS_NOT_RECTIFIED` | 409 |
| `ERR_FINDINGS_NOT_RECTIFIED` | 409 |
| `ERR_NO_HIGH_FINDINGS` | 409 |
| `ERR_DUPLICATE_INVOICE_NUMBER` | 409 |
| `ERR_PROJECT_CODE_COLLISION` | 409 |
| `ERR_STALE_BUDGET_VERSION` | 409 |
| `ERR_PROPOSAL_TOO_SHORT` | 422 |
| `ERR_INVALID_DATE_RANGE` | 422 |
| `ERR_START_IN_PAST` | 422 |
| `ERR_ADJUSTMENT_NOT_ZERO_SUM` | 422 |
| `ERR_NEGATIVE_BUDGET` | 422 |
| `ERR_JUSTIFICATION_TOO_SHORT` | 422 |
| `ERR_INVOICE_NOT_AUTHENTIC` | 422 |
| `ERR_ATTACHMENTS_INCOMPLETE` | 422 |
| `ERR_CATEGORY_MISMATCH` | 422 |
| `ERR_INVOICE_DATE_OUT_OF_RANGE` | 422 |
| `ERR_COMPLIANCE_BLOCK` | 422 |
| `ERR_ESCALATION_PENDING` | 422 |
| `ERR_AGENCY_RULE_VIOLATION` | 422 |
| `ERR_BUDGET_INSUFFICIENT` | 402 |
| `ERR_DELIVERABLES_INCOMPLETE` | 422 |
| `ERR_RESIDUAL_ACTION_NOT_ALLOWED` | 422 |
| `ERR_REJECTION_REASON_REQUIRED` | 422 |
| `ERR_INVALID_PAGINATION_PARAMETERS` | 400 |
| `ERR_INVALID_INPUT` | 400 |
