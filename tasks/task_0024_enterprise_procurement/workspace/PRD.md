# Enterprise Procurement API — Product Requirements Document

## 1. Introduction

Procurement at scale is a tug-of-war between commercial leverage and internal control. Buyers want to move quickly to lock in the best supplier; finance wants every committed dollar reconciled to a budget line; legal wants every signed clause traceable; and the executives who sign off on large spends want a clean audit trail when regulators come knocking. In practice, these constituencies live in different systems — sourcing tools, ERP modules, contract repositories, banking portals — and the seams between them are where money gets lost, contracts get signed twice, and approvers stamp purchase orders that they themselves later try to pay.

This document specifies an end-to-end procurement service that absorbs every link of that chain into a single state-machine-driven API. A request begins life as a free-text **Requirement** filed against a **BudgetAccount**, gathers competing **Quotes** from a vetted **Supplier** roster, is awarded into a **PurchaseOrder** whose dollar amount routes it through an amount-tiered **ApprovalStep** chain, is wrapped in a versioned **Contract** with payment terms, and finally settles through delivery **Receipts**, supplier **Invoices**, and bank-executed **Payments** — all while emitting an immutable **AuditLogEntry** trail for every approval and contract action. The system mediates concurrency at every junction (parallel approvers, racing awards, simultaneous payments, double-signatures), enforces segregation-of-duties across the approval-then-payment seam, and supplies test-driving endpoints so timeouts, escalations, and supplier deliveries can be reproduced deterministically.

The audience for this document is the engineer implementing the service. The narrative is organized so that each business actor's view is contiguous, while the cross-cutting rules — money conservation, role separation, version pinning, three-way invoice matching — are surfaced wherever they bear on a workflow.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two authentication headers: `X-User-ID` (the acting user's identifier) and `X-User-Role` (the acting role). If either header is missing or empty, the request is rejected with `ERR_AUTH_REQUIRED` and HTTP 401. If the role string is unrecognized — or if a role expected to correspond to a stored entity cannot be resolved to one — the request is rejected with `ERR_FORBIDDEN` and HTTP 403. After the role itself is recognized, the role-based access matrix is consulted; if the role is not authorized for the endpoint, the same `ERR_FORBIDDEN` (HTTP 403) is returned.

Nine roles are recognized, spelled exactly as follows: `Requester`, `Buyer`, `DepartmentHead`, `FinanceApprover`, `LegalApprover`, `GeneralManager`, `Inspector`, `Supplier`, and `PlatformAdmin`.

For every role except `Supplier`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record it in audit fields (for example, in `AuditLogEntry.actor_user_id`, in `ApprovalStep.assignee_user_id` and `ApprovalStep.original_assignee_user_id`, or in `Requirement.requester_id` when a `Requester` first creates a requirement) but it does not compare these values to an entity's `id`. Specifically: when `X-User-Role` is `Requester`, `Buyer`, `DepartmentHead`, `FinanceApprover`, `LegalApprover`, `GeneralManager`, `Inspector`, or `PlatformAdmin`, the corresponding `X-User-ID` is treated as opaque.

The `Supplier` role is entity-backed. When `X-User-Role` is `Supplier`, `X-User-ID` is the `id` of the acting `Supplier` entity; ownership checks on any resource that references a `Supplier` (notably an invoice referencing `supplier_id`, or a contract whose `purchase_order_id` resolves to a PO with a particular `supplier_id`) compare the resource's foreign-key field to `X-User-ID`.

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

List endpoints accept two pagination query parameters, `limit` and `offset`. The default `limit` is 10; the minimum is 1; the maximum is 100. The default `offset` is 0; it must be greater than or equal to 0. Values outside these bounds are rejected with `ERR_INVALID_PAGINATION` (HTTP 400). Lists are returned sorted by `created_at` ascending. The `meta` object on a list response includes `limit`, `offset`, `total_count` (the unfiltered match count for the supplied filters), and `has_more` (a boolean indicating whether further pages remain after the current window).

### 2.4. Common Resource Properties and Optimistic Concurrency

Every primary resource carries an `id` that is a server-minted UUID with no type prefix, and a `created_at` timestamp issued in ISO 8601 UTC with three fractional digits. Resources whose lifecycles include amendments — `BudgetAccount`, `Supplier`, `Requirement`, `Quote`, `PurchaseOrder`, `Contract`, `ClauseTemplate`, `Receipt`, `Payment`, `Invoice` — additionally carry `updated_at` (the timestamp of the most recent mutation, in the same ISO 8601 UTC format) and `version` (an integer that starts at 1 and increments by 1 on every mutation). Several auxiliary resources — `ApprovalStep`, `ContractVersion`, `PaymentSchedule`, and `AuditLogEntry` — carry only `id` and `created_at`; both `updated_at` and `version` are absent on these entities, because they are append-only views of decisions taken on their parent.

Optimistic concurrency control governs every mutation that accepts a `version` value in its request body. When the request body includes `version`, the server compares it to the current stored `version` of the target resource: a mismatch yields `ERR_VERSION_CONFLICT` (HTTP 409) and the mutation is not applied. When the request body omits `version`, the optimistic check is skipped and the mutation proceeds against whatever the current state is. Either way, every successful mutation increments the resource's `version` by 1 and refreshes its `updated_at`.

### 2.5. Money, Precision, and Rounding

All monetary amounts move through the system as integer cents. Fields with `_amount_cents` suffixes — `total_amount_cents` on `BudgetAccount`, `committed_amount_cents`, `spent_amount_cents`, `estimated_unit_price_cents`, `estimated_total_cents`, `unit_price_cents` on `Quote`, `total_amount_cents` and `amount_cents` on `PurchaseOrder` and `Payment` and `PaymentSchedule`, `invoiced_amount_cents`, `tax_amount_cents` — are all integers. No fractional cents are ever stored. Where a calculation produces a fractional figure, the rounding rule is round-half-up to the indicated precision; quote scores and the supplier rating average are rounded to 2 decimal places, the expected tax amount is rounded half-up to the nearest whole cent, and installment cents that do not divide evenly are absorbed into the last installment as described in §3.

### 2.6. Hierarchical Consistency and Cascading Side Effects

Many state transitions in this system mutate more than one entity. When the final required `ApprovalStep` on a purchase order transitions to `APPROVED`, the parent purchase order itself transitions from `PENDING_APPROVAL` to `APPROVED`, its `approved_at` is set to the current time, and its parent `Requirement` transitions to `APPROVED`. When any single step on the same purchase order transitions to `REJECTED`, the purchase order moves to `REJECTED`, the parent `Requirement` moves to `REJECTED`, every other `PENDING` step on the same purchase order moves to `SKIPPED`, and the budget commitment recorded on the bound `BudgetAccount` is released. When a contract transitions from `AWAITING_SIGNATURE` to `EXECUTED`, the bound purchase order cascades from `APPROVED` to `CONTRACTED`. When the cumulative accepted quantity on a purchase order's receipts reaches the requirement's requested quantity, the purchase order cascades to `FULFILLED`. Every such cascade increments `version` and refreshes `updated_at` on every mutated entity that carries those fields.

### 2.7. Nested Resource Retrieval and Path Validation

Several endpoints take more than one path parameter — for example, the comparison-table view at `/requirements/{id}/quotes/comparison-table`, the per-PO step listing at `/purchase-orders/{id}/approval-steps`, the receipt creation at `/purchase-orders/{id}/receipts`, and the schedule view at `/purchase-orders/{id}/payment-schedule`. Path parameters are validated left-to-right: the outer `id` is resolved first, and only if it exists is any inner `id` resolved. When any path-resource is absent, the response is `ERR_NOT_FOUND` (HTTP 404). Existence is checked before any role check that depends on the resource's contents.

### 2.8. Validation Priority Ordering

When several rules might fire on the same call, they are evaluated in this fixed order, and the first one that fails is the only one reported.

1. The authentication headers `X-User-ID` and `X-User-Role` are present and non-empty (`ERR_AUTH_REQUIRED`, 401).
2. The supplied role is recognized, and for entity-backed roles a corresponding user record exists (`ERR_FORBIDDEN`, 403).
3. Path-parameter resources exist, validated left-to-right (`ERR_NOT_FOUND`, 404).
4. The acting role is allowed by the role-based access matrix for this endpoint (`ERR_FORBIDDEN`, 403).
5. The target resource is in a state that permits the requested transition (`ERR_INVALID_STATE`, 409).
6. On quote creation, the supplier is `QUALIFIED`, the requirement category is among the supplier's qualification categories, and the supplier's qualification has not yet expired (`ERR_SUPPLIER_NOT_QUALIFIED`, 422).
7. On approval-step approve or reject, segregation of duties: no other `ApprovalStep` on the same purchase order has been decided by the same `X-User-ID` (`ERR_SEGREGATION_OF_DUTIES`, 422).
8. On payment approve, segregation of duties: the `FinanceApprover` approving this payment has not previously decided any `ApprovalStep` on the parent purchase order (`ERR_SEGREGATION_OF_DUTIES`, 422).
9. On approval actions, the step's `deadline_at` is strictly greater than the current time (`ERR_APPROVAL_DEADLINE_PASSED`, 409).
10. On serial approval-step approve, every preceding `SERIAL` step on the same purchase order is in `APPROVED` or `SKIPPED` (`ERR_PREDECESSOR_NOT_DECIDED`, 409).
11. On requirement award, the requirement has at least 3 quotes in `SHORTLISTED`, the awarded `awarded_quote_id` is among them, and `justification` is non-empty (`ERR_INSUFFICIENT_QUOTES`, 422).
12. On receipt inspect or accept, the `delivery_note_no` matches a delivery-note record posted to this purchase order via the supplier-delivery sync, and the receipt's `accepted_quantity` does not exceed `received_quantity` (`ERR_DELIVERY_NOTE_MISMATCH`, 422).
13. On receipt accept, the cumulative accepted quantity across all receipts on the purchase order does not exceed the requirement's requested `quantity` (`ERR_OVER_RECEIPT`, 422).
14. On requirement award, the budget account's `committed_amount_cents` plus the new purchase order's `total_amount_cents` does not exceed the budget account's `total_amount_cents` (`ERR_BUDGET_WOULD_EXCEED`, 422).
15. On invoice match, the declared tax rate is among the allowed tax rates and the supplied `tax_amount_cents` is within the tax tolerance of the computed expected tax (`ERR_TAX_NONCOMPLIANT`, 422).
16. On invoice match, the quantity and amount three-way deltas are within tolerance (`ERR_THREE_WAY_MATCH_FAILED`, 422).
17. On requirement create or update, `expected_delivery_date` is at least one day after `created_at` (`ERR_DELIVERY_DATE_TOO_EARLY`, 422).
18. On any mutation that accepts `version`, the supplied value matches the stored value (`ERR_VERSION_CONFLICT`, 409).
19. On any list endpoint, `limit` is between 1 and 100 inclusive and `offset` is at least 0 (`ERR_INVALID_PAGINATION`, 400).
20. Schema/type validation of inputs (required fields present, enum values from the declared set, well-formed payload) (`ERR_VALIDATION`, 400).

This priority is observable: when, for example, an approval action arrives on a step whose deadline has passed and whose predecessor has not yet been decided, the response is `ERR_APPROVAL_DEADLINE_PASSED`, not `ERR_PREDECESSOR_NOT_DECIDED`.

### 2.9. Concurrency and Serialization Guarantees

Several pairs of operations might race on the same resource. In every case, exactly one operation lands and the loser receives a specific error, not a generic conflict.

When two approvers simultaneously approve the same `ApprovalStep`, first-writer-wins on the step's status flip from `PENDING` to `APPROVED`; the second attempt finds the step no longer `PENDING` and is rejected with `ERR_INVALID_STATE`. The same outcome — `ERR_INVALID_STATE` — applies when one user approves while another rejects the same step at the same instant: the loser's transition is no longer valid because the step has already left `PENDING`.

When two buyers attempt to award the same requirement at the same instant, first-writer-wins on the requirement's status flip from `IN_SOURCING` to `AWARDED` and at most one purchase order is created; the loser receives `ERR_REQUIREMENT_ALREADY_AWARDED` (HTTP 409). When two contract creations are attempted on the same approved purchase order, the unique index on `Contract.purchase_order_id` admits only one; the loser receives `ERR_CONTRACT_ALREADY_EXISTS` (HTTP 409). When two payments are applied against the same `PaymentSchedule` entry, first-writer-wins on the schedule entry's flip from `PENDING` to `APPLIED` and the loser receives `ERR_PAYMENT_ALREADY_APPLIED` (HTTP 409). When two signatures from the same role are recorded on the same contract concurrently, the unique constraint on the pair of contract `id` and signature role admits only one; the loser receives `ERR_SIGNATURE_ALREADY_COLLECTED` (HTTP 409).

A budget commitment race is governed by compare-and-swap on `BudgetAccount.committed_amount_cents`. When two purchase-order awards would each fit individually but together would push committed beyond the account's `total_amount_cents`, the first commitment lands and the second is rejected with `ERR_BUDGET_WOULD_EXCEED` (HTTP 422).

### 2.10. Money Conservation Across Budget Accounts

The committed-and-spent ledger on every `BudgetAccount` obeys an invariant: at any quiescent moment, `committed_amount_cents` equals the sum of `total_amount_cents` of every purchase order bound to the account that is in `APPROVED`, `CONTRACTED`, or `FULFILLED`, minus the sum of `amount_cents` of every payment in `EXECUTED`. Forward-direction commitment occurs at award time: the new purchase order's `total_amount_cents` is added to `committed_amount_cents`. Compensating release occurs on rejection or cancellation: the same amount is subtracted. On payment execution, the executed amount is moved from `committed_amount_cents` (subtracted) to `spent_amount_cents` (added). On purchase-order close, any residual commitment — that is, `total_amount_cents` minus the sum of executed payment amounts — is released from `committed_amount_cents`. Every arithmetic operation here is in integer cents.

### 2.11. Audit Logging

Approval-chain decisions and contract-lifecycle events are recorded in an append-only audit log. Specifically, an `AuditLogEntry` is appended whenever an `ApprovalStep` is approved (`action` = `APPROVAL_STEP_APPROVE`), rejected (`APPROVAL_STEP_REJECT`), delegated (`APPROVAL_STEP_DELEGATE`), or escalated by a deadline crossing (`APPROVAL_STEP_ESCALATE`); whenever a new contract version snapshot is written (`CONTRACT_VERSION_CREATED`); whenever a contract signature is recorded — one entry per signature — (`CONTRACT_SIGNED`); and whenever a contract is amended (`CONTRACT_AMENDED`). Each entry captures the acting user via `actor_user_id` and `actor_role`, the touched `entity_type` and `entity_id`, the discrete `action`, and an action-specific `payload` (for example, `{from_user, to_user, reason}` on a delegation). The submission of a draft requirement, the addition of a quote, the creation of a receipt, the application of a payment, and similar non-approval actions do **not** generate audit entries.

## 3. Business Logic & Workflows

### 3.1. Budget Setup and Supplier Onboarding

Every procurement event must trace to money that has been authorized for spend, and to a counterparty that the legal team has cleared to receive it. A `FinanceApprover` therefore opens the cycle by creating a `BudgetAccount`, supplying a `code` that follows the strict pattern of the literal prefix `BA-`, four digits, a hyphen, an uppercase letter group, another hyphen, and a final uppercase letter group (for example, `BA-2026-IT-CAPEX`); the same `code` may not appear on two accounts. The payload includes the owning `department`, the `fiscal_year`, and a `total_amount_cents` that must be at least zero. The account is created in `ACTIVE` status, with `committed_amount_cents` and `spent_amount_cents` both initialized to 0; the lifecycle states the account can take are `ACTIVE`, `FROZEN`, and `CLOSED`.

Onto this foundation a `Buyer` registers each prospective `Supplier` with its `legal_name` (unique), `tax_id` (unique), an array of `qualification_categories` describing the procurement categories it can serve, a `qualification_expires_at` deadline, and a `bank_account_id` returned by the bank-system synchronization for downstream payment routing. The supplier is created with `qualification_status` set to `PROVISIONAL`, and its `rating_avg` initialized to 0. A `LegalApprover` later promotes the supplier to `QUALIFIED` after due diligence; the alternative terminal status `BLACKLISTED` is reserved for suppliers that are removed from the active roster. Once the qualification deadline passes, the supplier may still exist in `QUALIFIED` status but new quotes against the supplier's name will be refused (see §3.2).

### 3.2. Requirement Capture and Quote Collection

A `Requester` opens a procurement event by drafting a `Requirement`. The submission carries a `category` chosen from `IT_HARDWARE`, `IT_SOFTWARE`, `OFFICE_SUPPLIES`, `PROFESSIONAL_SERVICES`, `MARKETING`, and `CAPEX_EQUIPMENT`; a free-form `specification`; an integer `quantity` of at least 1; a `unit` of measure (such as unit, license, or hour); an `expected_delivery_date`; the `budget_account_id` to charge against; an `estimated_unit_price_cents` of at least zero used to size the request; and an optional `attachment_uri` pointing at a spec sheet or supporting document. The server stamps the originating user into `requester_id` from `X-User-ID`, computes `estimated_total_cents` as the requested `quantity` multiplied by `estimated_unit_price_cents`, and places the requirement in `DRAFT`. The expected delivery date is required to be at least one day after the requirement's `created_at` — meaning the date must be greater than or equal to `created_at` plus one day; a same-day or earlier date is rejected with `ERR_DELIVERY_DATE_TOO_EARLY`. The same temporal check applies to any patch-style update of the requirement.

Submitting the draft advances the requirement from `DRAFT` to `SUBMITTED`. Submission requires that the bound `BudgetAccount` exists and is in `ACTIVE` status (otherwise the transition is refused as `ERR_INVALID_STATE`) and that the expected delivery temporal rule still holds. While the requirement is in `DRAFT` or `SUBMITTED`, the originating requester may also cancel it, which transitions it directly to the terminal `CANCELLED` state with no side effects.

A `Buyer` then begins quote collection by adding supplier quotes to the requirement. Each quote carries `supplier_id`, `unit_price_cents` (at least 1), `lead_time_days` (at least 0), and a `technical_score` between 0 and 100 inclusive expressed to two decimals. On every quote create, the server checks three referential rules together as one atomic gate before the quote is persisted: the `Supplier`'s `qualification_status` is `QUALIFIED`, the requirement's `category` appears in the supplier's `qualification_categories`, and the supplier's `qualification_expires_at` is strictly later than the current time. Failure on any of the three is a single error: `ERR_SUPPLIER_NOT_QUALIFIED`. The first valid quote on a `SUBMITTED` requirement transitions the requirement from `SUBMITTED` to `IN_SOURCING`. Each quote is created in `SUBMITTED` status; the lifecycle of a quote spans `SUBMITTED`, `SHORTLISTED`, `AWARDED`, `REJECTED`, and `EXPIRED`.

Whenever a new quote is added to the pool, the commercial scoring across the full pool is recomputed in place — earlier `composite_score` values stored on sibling quotes are overwritten with the new pool-relative values. Pool-relative scoring works as follows. The eligible pool is every quote on the same requirement currently in `SUBMITTED` status; quotes in `EXPIRED` are excluded. The minimum and maximum `unit_price_cents` across the pool are taken. If they are equal — a degenerate single-quote pool, or a pool where every supplier quoted the same number — every quote in the pool is given a `commercial_score` of 100.00. Otherwise, each quote's `commercial_score` is the maximum price minus that quote's `unit_price_cents`, divided by the maximum minus the minimum, multiplied by 100, then rounded half-up to two decimal places. The `composite_score` then combines the technical and commercial sides with weights pinned at `W_TECH` of 0.40 and `W_COMM` of 0.60: each quote's `composite_score` is its `technical_score` multiplied by 0.40, plus its `commercial_score` multiplied by 0.60, with the rounding applied once after the weighted sum (not term-by-term) to two decimal places.

Buyers can review the comparison-table view, which lists each quote with `technical_score`, `commercial_score`, and `composite_score` so the selection can be defended. The buyer then designates the `SHORTLISTED` set by submitting a `quote_ids` array; each named quote moves from `SUBMITTED` to `SHORTLISTED`. The shortlist call also re-runs the pool-relative scoring across the full pool, so that the scores stored on shortlisted quotes are consistent with the latest pool composition. A precondition for shortlisting any individual quote is that its supplier remains in `qualification_status` `QUALIFIED` at shortlist time.

If the test clock advances past a supplier's `qualification_expires_at`, every quote of that supplier currently in `SUBMITTED` is moved to `EXPIRED` by the system as part of the clock-advance sweep. Expired quotes are not eligible for shortlisting or award.

### 3.3. Award, Tier Routing, and Approval

Awarding finalizes the sourcing decision and conjures the purchase order. The buyer submits the chosen `awarded_quote_id` together with a non-empty `justification` string explaining the selection. The server enforces three things together: there must be at least 3 quotes in `SHORTLISTED` status on this requirement; the awarded quote's id must be among that shortlisted set; and `justification` must be non-empty. Any of these three failing is reported as `ERR_INSUFFICIENT_QUOTES`. On success, the awarded quote transitions to `AWARDED`, every other shortlisted quote on the same requirement transitions from `SHORTLISTED` to `REJECTED` (the system writes these sibling rejections, not the buyer), and the requirement transitions through `AWARDED` into `IN_APPROVAL`.

A `PurchaseOrder` is created at this point in `PENDING_APPROVAL`. Its `total_amount_cents` is the awarded quote's `unit_price_cents` multiplied by the requirement's `quantity`, pinned at PO creation; its `requirement_id`, `awarded_quote_id`, `supplier_id`, and `budget_account_id` are stamped from the requirement and the awarded quote. The system also writes `approval_started_at` and leaves `approved_at` null until the chain completes.

Before any approval step is generated, the system verifies that adding the new purchase order's `total_amount_cents` to the bound `BudgetAccount`'s current `committed_amount_cents` would not push the total past the account's `total_amount_cents`. If the sum would exceed, the award is rejected with `ERR_BUDGET_WOULD_EXCEED` and no purchase order is created. Otherwise, `committed_amount_cents` is increased by the purchase order's `total_amount_cents` and the commitment is recorded.

The purchase order's `tier` is then assigned from its `total_amount_cents` against three thresholds, expressed in integer cents: `TIER1_MAX_CENTS` is 500,000 cents (five thousand dollars), `TIER2_MAX_CENTS` is 5,000,000 cents (fifty thousand dollars), and `TIER3_MAX_CENTS` is 50,000,000 cents (five hundred thousand dollars). A purchase-order total strictly less than `TIER1_MAX_CENTS` is `TIER_1`; a total at least `TIER1_MAX_CENTS` and strictly less than `TIER2_MAX_CENTS` is `TIER_2`; a total at least `TIER2_MAX_CENTS` and strictly less than `TIER3_MAX_CENTS` is `TIER_3`; a total at least `TIER3_MAX_CENTS` is `TIER_4`. Each tier corresponds to a distinct routing of `ApprovalStep` records, each carrying `purchase_order_id`, a `stage` (drawn from `DEPARTMENT_HEAD`, `FINANCE`, `LEGAL`, and `GENERAL_MANAGER`), an `assignee_role` (drawn from `DepartmentHead`, `FinanceApprover`, `LegalApprover`, and `GeneralManager`), an `assignee_user_id` and an `original_assignee_user_id` (initially the same), a `mode` of either `SERIAL` or `PARALLEL`, a `status` initialized to `PENDING`, and a `deadline_at` set to 72 hours after step activation.

`TIER_1` produces a single serial chain of length one: a `DEPARTMENT_HEAD` step. `TIER_2` produces a serial chain of two steps: `DEPARTMENT_HEAD`, then `FINANCE`. `TIER_3` produces three logical positions: a `DEPARTMENT_HEAD` step first; then a `FINANCE` step and a `LEGAL` step that run in `PARALLEL` (both must reach `APPROVED` before the next position activates); then a `GENERAL_MANAGER` step. `TIER_4` has the same shape as `TIER_3` — `DEPARTMENT_HEAD`, then `FINANCE` and `LEGAL` in parallel, then `GENERAL_MANAGER` — with the additional rule that on a `TIER_4` purchase order the final `GENERAL_MANAGER` step's `decision_comment` is required (an approval submitted with an empty `decision_comment` on that step is rejected).

An approver acts on a step by approving or rejecting it; both calls accept an optional `decision_comment`. To act, the caller's `X-User-ID` must equal the step's current `assignee_user_id` (or be a delegate of the original assignee, see below), the step's `deadline_at` must be strictly later than the current time, and — for a serial step — every preceding `SERIAL` step on the same purchase order must already be in `APPROVED` or `SKIPPED`. Crucially, no two steps on the same purchase order may be decided by the same `X-User-ID` — this is the segregation-of-duties check that precedes any other step-level rule once authorization has been granted; a violator receives `ERR_SEGREGATION_OF_DUTIES`. A serial step approve attempted before its predecessor has cleared returns `ERR_PREDECESSOR_NOT_DECIDED`. An approve or reject attempted after the deadline returns `ERR_APPROVAL_DEADLINE_PASSED`. On approval, the step writes its `decided_at`, an `AuditLogEntry` with action `APPROVAL_STEP_APPROVE` is appended, and if this is the final remaining `PENDING` step on the purchase order, the cascade fires: the purchase order transitions from `PENDING_APPROVAL` to `APPROVED`, its `approved_at` is set to the current time, and the parent requirement transitions to `APPROVED`. On rejection, the cascade is opposite and total: the step writes its `decided_at`, an `AuditLogEntry` with action `APPROVAL_STEP_REJECT` is appended, the purchase order moves to `REJECTED`, the parent requirement moves to `REJECTED`, every other `PENDING` step on the same purchase order moves to `SKIPPED`, and the budget commitment is released — `committed_amount_cents` is decremented by the purchase order's `total_amount_cents`.

### 3.4. Delegation, Timeout, and Escalation

Approvers who cannot act in time can delegate to a peer in the same role. Delegating supplies a `target_user_id` of a user with the same `assignee_role` as the step. The delegation may only be issued by the user who currently holds the step (`assignee_user_id` equals `X-User-ID`); if the target user does not match the step's required role the call is rejected with `ERR_DELEGATE_INVALID_ROLE`. The step remains in `PENDING`; only `assignee_user_id` is rewritten to the target, while `original_assignee_user_id` is preserved so the audit trail and any later "delegate chain matches" check can still resolve back to the originator. An `AuditLogEntry` with action `APPROVAL_STEP_DELEGATE` is appended.

When the test clock advances past a step's `deadline_at`, the system runs an escalation sweep. Each `PENDING` step whose `deadline_at` is now at or before the current time transitions to `ESCALATED`: the step's `assignee_user_id` is rewritten to a `GeneralManager` user (the escalation target by stage routing), the step's `deadline_at` is extended to 24 hours after the moment of escalation, and an `AuditLogEntry` with action `APPROVAL_STEP_ESCALATE` is appended. From `ESCALATED`, only a `GeneralManager` may approve or reject — the step still flows through the same cascade afterwards, so a `GeneralManager` approval on an `ESCALATED` step still fires the same final-step cascade as a normal `PENDING → APPROVED` transition and a `GeneralManager` rejection on an `ESCALATED` step still tears the purchase order down to `REJECTED` with the same sibling-`SKIPPED` and budget-release effects. A sibling-rejection cascade or a purchase-order cancellation moves all other `PENDING` steps directly to `SKIPPED` without touching their assignee or deadline.

### 3.5. Rework, Cancellation, and Race Outcomes

A rejected requirement is not a dead end. The originating requester may rework a `REJECTED` requirement back to `DRAFT`; this clears `justification` and leaves any quotes already created on the requirement in their existing `REJECTED` state — they are not resurrected. The buyer may also cancel a purchase order while approval is still pristine: cancellation is permitted only when no `ApprovalStep` on the purchase order has its `decided_at` set, in which case the purchase order moves to `CANCELLED`, every `ApprovalStep` on the order moves to `SKIPPED`, and the budget commitment is released by subtracting the purchase order's `total_amount_cents` from `committed_amount_cents`.

When two buyers race to award the same requirement, the first writer flips the requirement from `IN_SOURCING` to `AWARDED` and the loser receives `ERR_REQUIREMENT_ALREADY_AWARDED`. When two approvers race to act on the same step, the first writer flips the step away from `PENDING` and any later actor — whether attempting an approve against an already-approved step, a reject against an already-rejected step, an approve against a rejected step, or a reject against an approved step — gets `ERR_INVALID_STATE`.

### 3.6. Contract Drafting, Review, Versioning, and Signature

Once a purchase order is `APPROVED`, a `Buyer` drafts a `Contract` against it. The draft carries `purchase_order_id` (unique across contracts — only one contract per purchase order), an ordered `clause_template_ids` array composing the body, the chosen `payment_terms_type` (one of `ADVANCE`, `ON_DELIVERY`, `NET_N_DAYS`, `INSTALLMENT`), a `payment_terms_params` object whose shape depends on the type (for example, `{net_days: 30}` for `NET_N_DAYS`, or `{schedule: [{percent: 30, offset_days: 0}, {percent: 70, offset_days: 30}]}` for `INSTALLMENT`), and a `parties_required` array enumerating the roles whose signatures are needed (typically `Buyer` and `Supplier`). The contract is created in `DRAFTING`, its `current_version` initialized to 1, its `signatures` array empty, and an immediate `ContractVersion` snapshot v1 is written capturing `clause_template_ids_snapshot`, `payment_terms_snapshot`, and the originating `change_reason`. If two creations race on the same `purchase_order_id`, the unique constraint admits one; the loser receives `ERR_CONTRACT_ALREADY_EXISTS`.

Each `ClauseTemplate` is created up-front by a `LegalApprover` with a unique `code`, a human-readable `title`, the legal `body` text, and a `category` chosen from `PAYMENT`, `DELIVERY`, `WARRANTY`, `IP`, `CONFIDENTIALITY`, and `TERMINATION`; the `is_active` flag defaults to true. The buyer submits the contract for review, which requires that the bound purchase order is in `APPROVED`, that `clause_template_ids` is non-empty, and that every referenced `ClauseTemplate` has its `is_active` flag set to true (an inactive template anywhere in the list is rejected with `ERR_CLAUSE_TEMPLATE_INACTIVE`). On submit-for-review, the contract transitions from `DRAFTING` to `IN_REVIEW`. A `LegalApprover` may finalize the review (transitioning the contract from `IN_REVIEW` to `AWAITING_SIGNATURE`) or the `Buyer` may amend it back to `DRAFTING`; an amendment from `IN_REVIEW` requires a non-empty `change_reason`, increments `current_version` by 1, writes a new `ContractVersion` snapshot for the new version capturing the latest `clause_template_ids`, `payment_terms_type`, and `payment_terms_params`, and appends an `AuditLogEntry` with action `CONTRACT_AMENDED`. Each newly created `ContractVersion` writes its `version_number` (sequential starting at 1), `contract_id`, `clause_template_ids_snapshot`, `payment_terms_snapshot`, and the supplied `change_reason`, and triggers an `AuditLogEntry` with action `CONTRACT_VERSION_CREATED` at version-snapshot time.

In `AWAITING_SIGNATURE`, parties record signatures. A signature call from the `Buyer` or `Supplier` party supplies a `role` (`Buyer` or `Supplier`) and a `signature_ref` and the server appends the signature with the acting `user_id` from `X-User-ID` and the current time as `signed_at`. A `Supplier` party's `X-User-ID` must equal the `supplier_id` of the purchase order behind the contract — the entity-backed identity check from §2.1. Two signatures from the same role on the same contract are not allowed; the loser receives `ERR_SIGNATURE_ALREADY_COLLECTED`. An `AuditLogEntry` with action `CONTRACT_SIGNED` is appended for every signature recorded.

Two outcomes are possible from `AWAITING_SIGNATURE`. If the buyer amends instead — and either no signatures have yet been collected, or all collected signatures are invalidated by the amendment — the contract reverts to `DRAFTING`, `current_version` is incremented, the existing `signatures` array is cleared, and an `AuditLogEntry` with action `CONTRACT_AMENDED` is appended. Otherwise, the moment the final signature lands such that every role in `parties_required` has a corresponding entry in `signatures`, the contract transitions from `AWAITING_SIGNATURE` to `EXECUTED`, the bound purchase order cascades from `APPROVED` to `CONTRACTED`, and the payment schedule generation fires.

A `GeneralManager` may terminate an `EXECUTED` contract with a supplied `reason`; termination requires the bound purchase order to be in `CONTRACTED` or `FULFILLED`, moves the contract to `TERMINATED`, cancels every `PENDING` `PaymentSchedule` entry on that purchase order, and releases the budget commitment for the unpaid balance — that is, `committed_amount_cents` is decremented by the unpaid balance.

### 3.7. Payment Schedule Generation

The payment schedule is generated at the moment the contract enters `EXECUTED`, using `total` taken from the purchase order's `total_amount_cents` (pinned at PO creation), the contract's effective execution time as the schedule's "now", and the requirement's `expected_delivery_date` (pinned at requirement submission) as the delivery anchor. Each generated `PaymentSchedule` row carries a `purchase_order_id`, a `contract_id`, an `installment_no` numbered from 1, a `due_date`, an `amount_cents`, and a `status` initialized to `PENDING`. Schedules can take `PENDING`, `APPLIED`, `EXECUTED`, or `CANCELLED`.

For `payment_terms_type` of `ADVANCE`, exactly one row is generated: `installment_no` 1, `amount_cents` equal to `total`, `due_date` equal to the schedule's now. For `ON_DELIVERY`, one row: `installment_no` 1, `amount_cents` equal to `total`, `due_date` equal to the requirement's `expected_delivery_date`. For `NET_N_DAYS`, the `payment_terms_params.net_days` value is read; one row is generated with `installment_no` 1, `amount_cents` equal to `total`, and `due_date` equal to the requirement's `expected_delivery_date` plus that many days. For `INSTALLMENT`, the `payment_terms_params.schedule` array provides a list of items with `percent` and `offset_days`; the percentages must sum to exactly 100. The system walks the array in declared order; for every item except the last, the installment's `amount_cents` is the integer floor of `total` multiplied by `percent` divided by 100; for the last item, the installment's `amount_cents` is `total` minus the running sum of the prior allocations, so the cents remainder lands on the last installment. Each installment's `due_date` is the schedule's now plus the item's `offset_days`. The post-condition is that the sum of `amount_cents` over the generated schedule equals `total` exactly — no installment-level rounding can leak cents.

### 3.8. Goods Receipt and Acceptance

Once the purchase order is in `CONTRACTED`, the supplier delivers and an `Inspector` (or, in shared cases, a `Buyer`) records a `Receipt` against the purchase order. Each receipt carries the supplier-supplied `delivery_note_no`, an integer `received_quantity` of at least 1, an integer `accepted_quantity` of at least 0 and not exceeding `received_quantity`, and a `quality_rating` between 0 and 100 inclusive. The system computes `rejected_quantity` as `received_quantity` minus `accepted_quantity`. Each receipt starts in `DRAFT`.

The inspector advances the receipt to `INSPECTING` once it is being matched against a delivery-note record. Two preconditions hold: the bound purchase order is in `CONTRACTED`, and the receipt's `delivery_note_no` matches a delivery-note number recorded against the purchase order via the supplier-delivery synchronization — that is, an identical `delivery_note_no` was previously posted by the platform-admin supplier-delivery event for that same `purchase_order_id`. A mismatch — either no matching delivery-note record, or `accepted_quantity` greater than `received_quantity` — yields `ERR_DELIVERY_NOTE_MISMATCH`.

From `INSPECTING`, three outcomes are possible. A full acceptance — `accepted_quantity` equal to `received_quantity` and `quality_rating` at least 60 — moves the receipt to `ACCEPTED`. A partial acceptance — `accepted_quantity` strictly greater than 0 and strictly less than `received_quantity`, with `quality_rating` at least 60 — moves the receipt to `PARTIALLY_ACCEPTED`. The third outcome, rejection, applies when either `accepted_quantity` is 0 or the `quality_rating` is strictly less than 60; the receipt moves to `REJECTED`. Both `ACCEPTED` and `PARTIALLY_ACCEPTED` snapshot a `cumulative_accepted_after` value pinned to the running sum of `accepted_quantity` across previously-accepted receipts on this purchase order plus this receipt's own accepted quantity; if `cumulative_accepted_after` would exceed the requirement's `quantity`, the accept call is rejected with `ERR_OVER_RECEIPT`. When `cumulative_accepted_after` equals the requirement's `quantity`, the parent purchase order cascades from `CONTRACTED` to `FULFILLED`. Both accepted and partially-accepted receipts also recompute the supplier's `rating_avg`: it is the sum of `quality_rating` over every receipt of this supplier whose status is `ACCEPTED` or `PARTIALLY_ACCEPTED`, divided by the count of those receipts, rounded half-up to two decimal places. Receipts in `DRAFT`, `INSPECTING`, `REJECTED`, or `RETURNED` are excluded from that average.

A rejected receipt may be returned to the supplier; this moves it from `REJECTED` to `RETURNED` and is the receipt's terminal step on the goods-rejection branch.

### 3.9. Invoice Three-Way Match and Tax Compliance

A `Supplier` submits an `Invoice` against the purchase order, supplying `purchase_order_id`, `supplier_id` (which must equal the purchase order's `supplier_id`), `invoice_no` (unique per `supplier_id`), `invoice_date`, `invoiced_quantity` (at least 1), `invoiced_amount_cents` (at least 1), `tax_amount_cents` (at least 0), and `tax_rate_declared` (between 0 and 1 inclusive). The invoice begins in `SUBMITTED`.

A `FinanceApprover` runs the three-way match. The match draws on receipts on the purchase order whose status is `ACCEPTED` or `PARTIALLY_ACCEPTED`; receipts in `DRAFT`, `INSPECTING`, `REJECTED`, or `RETURNED` are excluded. The received quantity is the sum of `accepted_quantity` over the qualifying receipts. The pro-rata received amount is the received quantity multiplied by the purchase order's `total_amount_cents`, divided by the requirement's `quantity`. The quantity-delta percentage is the absolute difference between `invoiced_quantity` and the received quantity, divided by the received quantity. The amount-delta percentage is the absolute difference between `invoiced_amount_cents` and the pro-rata received amount, divided by the pro-rata received amount. The expected tax in cents is `invoiced_amount_cents` minus the result of `invoiced_amount_cents` divided by one plus `tax_rate_declared`, rounded half-up to the nearest whole cent. The tax delta in cents is the absolute difference between `tax_amount_cents` and that expected tax.

The quantity match passes when the quantity-delta percentage is at most `QTY_TOLERANCE_PCT`, which is 0.02 (two percent). The amount match passes when the amount-delta percentage is at most `AMT_TOLERANCE_PCT`, which is 0.01 (one percent). Tax compliance requires both that the tax delta is at most `TAX_TOLERANCE_CENTS`, which is one cent, and that `tax_rate_declared` is one of the values in `ALLOWED_TAX_RATES`: 0.06, 0.09, or 0.13. The overall three-way match passes when quantity, amount, and tax compliance all pass; the invoice transitions from `SUBMITTED` to `MATCHED` and `matching_result` is populated as an object containing `quantity_match`, `amount_match`, `tax_compliant`, and a `deltas` sub-object capturing the underlying numbers. If any of the three component checks fails the invoice transitions to `EXCEPTION` instead, `matching_result` is populated with the deltas, and one of two errors is reported: a tax-side failure — `tax_rate_declared` not in the allowed set, or `tax_amount_cents` outside the tolerance — surfaces as `ERR_TAX_NONCOMPLIANT`, and a quantity-or-amount tolerance failure surfaces as `ERR_THREE_WAY_MATCH_FAILED`. (Per §2.8, the tax check is evaluated before the quantity-and-amount check, so a tax-noncompliant invoice that also blows the quantity tolerance is reported as `ERR_TAX_NONCOMPLIANT`.)

A `GeneralManager` may override an `EXCEPTION` invoice. The override supplies a `justification`; on success the invoice moves from `EXCEPTION` to `MATCHED`, the existing `matching_result` is augmented with an `override_by` field naming the overriding manager, and the override forces the matched outcome regardless of the underlying tolerances. A `FinanceApprover` may instead reject an `EXCEPTION` invoice with a `reason`, moving it to the terminal `REJECTED`.

A `MATCHED` invoice is approved by a `FinanceApprover` only if its `matching_result.tax_compliant` is true (a manager-overridden invoice is treated as tax-compliant by virtue of the override flag). On approval the invoice moves to `APPROVED`. The invoice transitions to `PAID` automatically once every `Payment` bound to it has reached `EXECUTED`.

### 3.10. Payment Application, Approval, and Execution

A `FinanceApprover` applies a payment by binding a `payment_schedule_id` to an `invoice_id`. The invoice must be in `APPROVED` and the schedule entry must be in `PENDING`. On creation the payment is in `APPLIED`, its `amount_cents` mirrors the schedule entry's `amount_cents` (and is immutable thereafter), and the schedule entry transitions from `PENDING` to `APPLIED`. Two payments racing on the same schedule entry serialize via the entry's `PENDING → APPLIED` flip; the loser receives `ERR_PAYMENT_ALREADY_APPLIED`.

A different `FinanceApprover` then approves the payment. The approving user must not have decided any `ApprovalStep` on the parent purchase order; this is the second arm of segregation-of-duties — finance-side approval-then-payment must be split across two distinct people. A violation surfaces as `ERR_SEGREGATION_OF_DUTIES`. The payment moves from `APPLIED` to `APPROVED`. An `APPLIED` payment can also be cancelled by a `FinanceApprover`; cancellation moves the payment to `CANCELLED` and rolls the bound schedule entry from `APPLIED` back to `PENDING`, making it eligible for re-application.

A `PlatformAdmin` executes the payment via the bank-system synchronization. Successful execution moves the payment from `APPROVED` to `EXECUTED`, sets the payment's `bank_reference` from the bank's response, advances the schedule entry from `APPLIED` to `EXECUTED`, increases the bound budget account's `spent_amount_cents` by the payment's `amount_cents`, and decreases the bound budget account's `committed_amount_cents` by the same amount. A bank-side failure moves the payment from `APPROVED` to `FAILED` and rolls the schedule entry from `APPLIED` back to `APPLIED` (re-applicable for a fresh attempt).

Once every `PaymentSchedule` entry on the purchase order is in `EXECUTED` or `CANCELLED`, and every `Invoice` for the purchase order is in `APPROVED` or `PAID`, the purchase order cascades from `FULFILLED` to `CLOSED`. On close, any residual commitment — the purchase order's `total_amount_cents` minus the sum of executed payment amounts — is released from the bound budget account's `committed_amount_cents`, and `spent_amount_cents` is reconciled to the executed-payment total.

### 3.11. Test-Driving Capabilities

Two operational endpoints exist to make timing- and integration-dependent transitions reproducible. An admin-only test-driving capability advances the logical clock to a supplied `to` instant; on advance, every `ApprovalStep` whose `deadline_at` is at or before the new clock time and whose status is `PENDING` is transitioned to `ESCALATED` (with the associated assignee rewrite, deadline extension to 24 hours past the new clock, and audit append described in §3.4), and every `Quote` of a supplier whose `qualification_expires_at` is at or before the new clock and whose status is `SUBMITTED` is transitioned to `EXPIRED`. A second admin-only capability records a supplier-delivery event for a particular `purchase_order_id` with a supplied `delivery_note_no` and `declared_quantity`, registering the delivery-note record that subsequent receipt inspections must match against.

## 4. Endpoint Definitions

The endpoint table below summarizes the API surface. A new resource creation returns HTTP 201; modifications, retrievals, and listings return HTTP 200. Request bodies, response payloads, side effects, and validation conditions are intentionally omitted from this table — the reader reconstructs them from §3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/advance` | Advance the test clock; runs deadline-escalation and quote-expiry sweeps | PlatformAdmin |
| POST | `/_events/supplier-delivery` | Record a supplier delivery-note event against a purchase order | PlatformAdmin |
| POST | `/budget-accounts` | Create a budget account | FinanceApprover |
| GET | `/budget-accounts/{id}` | Retrieve a budget account | FinanceApprover, Buyer, Requester, DepartmentHead, GeneralManager |
| GET | `/budget-accounts` | List budget accounts with filters | FinanceApprover, Buyer, Requester, DepartmentHead, GeneralManager |
| POST | `/suppliers` | Register a supplier (provisional) | Buyer |
| POST | `/suppliers/{id}/qualify` | Promote supplier to QUALIFIED | LegalApprover |
| GET | `/suppliers/{id}` | Get supplier | Buyer, FinanceApprover, LegalApprover, GeneralManager |
| GET | `/suppliers` | List suppliers | Buyer, FinanceApprover, LegalApprover |
| POST | `/requirements` | Submit a requirement (DRAFT) | Requester |
| POST | `/requirements/{id}/submit` | Submit a DRAFT requirement | Requester |
| POST | `/requirements/{id}/quotes` | Add a supplier quote | Buyer |
| POST | `/requirements/{id}/shortlist` | Designate the SHORTLISTED set | Buyer |
| POST | `/requirements/{id}/award` | Award an awarded_quote_id; create PO and approval steps | Buyer |
| POST | `/requirements/{id}/rework` | Move a REJECTED requirement back to DRAFT | Requester |
| POST | `/requirements/{id}/cancel` | Cancel a DRAFT or SUBMITTED requirement | Requester |
| GET | `/requirements/{id}` | Get a requirement | Requester, Buyer, FinanceApprover, DepartmentHead, GeneralManager, LegalApprover |
| GET | `/requirements` | List requirements with filters | Requester, Buyer, FinanceApprover, DepartmentHead, GeneralManager, LegalApprover |
| GET | `/requirements/{id}/quotes/comparison-table` | Compare-table view of quotes | Buyer, FinanceApprover, GeneralManager |
| GET | `/quotes/{id}` | Get a quote | Buyer, FinanceApprover |
| GET | `/purchase-orders/{id}` | Get a PO | Buyer, Requester, FinanceApprover, DepartmentHead, GeneralManager, LegalApprover |
| POST | `/purchase-orders/{id}/cancel` | Cancel an as-yet-undecided PO | Buyer |
| GET | `/purchase-orders` | List POs | Buyer, FinanceApprover, GeneralManager |
| GET | `/purchase-orders/{id}/approval-steps` | List approval steps for a PO | Buyer, FinanceApprover, DepartmentHead, GeneralManager, LegalApprover |
| POST | `/approval-steps/{id}/approve` | Approve a PENDING or ESCALATED step | DepartmentHead, FinanceApprover, LegalApprover, GeneralManager |
| POST | `/approval-steps/{id}/reject` | Reject a PENDING or ESCALATED step | DepartmentHead, FinanceApprover, LegalApprover, GeneralManager |
| POST | `/approval-steps/{id}/delegate` | Delegate the step to another user with the same role | DepartmentHead, FinanceApprover, LegalApprover, GeneralManager |
| POST | `/contracts` | Create a contract draft tied to an APPROVED PO | Buyer |
| POST | `/contracts/{id}/submit-for-review` | Move contract from DRAFTING to IN_REVIEW | Buyer |
| POST | `/contracts/{id}/finalize-review` | Legal finalizes review; contract → AWAITING_SIGNATURE | LegalApprover |
| POST | `/contracts/{id}/amend` | Amend contract; bumps version; clears signatures if AWAITING_SIGNATURE | Buyer |
| POST | `/contracts/{id}/sign` | Record a party signature | Buyer, Supplier |
| POST | `/contracts/{id}/terminate` | Terminate an executed contract | GeneralManager |
| GET | `/contracts/{id}` | Get a contract | Buyer, Supplier, LegalApprover, FinanceApprover, GeneralManager |
| GET | `/contracts/{id}/versions` | List contract version snapshots | Buyer, Supplier, LegalApprover, FinanceApprover, GeneralManager |
| POST | `/clause-templates` | Create a clause template | LegalApprover |
| GET | `/clause-templates` | List clause templates | LegalApprover, Buyer |
| POST | `/purchase-orders/{id}/receipts` | Record a delivery receipt | Inspector, Buyer |
| POST | `/receipts/{id}/inspect` | Move receipt into INSPECTING | Inspector |
| POST | `/receipts/{id}/accept` | Accept (full or partial) the receipt | Inspector |
| POST | `/receipts/{id}/reject` | Reject the receipt | Inspector |
| POST | `/receipts/{id}/return` | Initiate return-to-supplier on a REJECTED receipt | Inspector |
| POST | `/invoices` | Submit an invoice | Supplier |
| POST | `/invoices/{id}/match` | Run three-way match | FinanceApprover |
| POST | `/invoices/{id}/override` | Override an EXCEPTION invoice | GeneralManager |
| POST | `/invoices/{id}/approve` | Approve a MATCHED invoice | FinanceApprover |
| POST | `/invoices/{id}/reject` | Reject an EXCEPTION invoice | FinanceApprover |
| GET | `/invoices/{id}` | Get an invoice | Buyer, FinanceApprover, Supplier, GeneralManager |
| GET | `/purchase-orders/{id}/payment-schedule` | Get the generated payment schedule for a PO | Buyer, FinanceApprover, GeneralManager, Supplier |
| POST | `/payments` | Apply a payment against a schedule entry and an APPROVED invoice | FinanceApprover |
| POST | `/payments/{id}/approve` | Approve the applied payment | FinanceApprover |
| POST | `/payments/{id}/execute` | Execute payment via bank sync | PlatformAdmin |
| POST | `/payments/{id}/cancel` | Cancel an APPLIED payment | FinanceApprover |
| GET | `/audit-log` | Query the audit log with filters | GeneralManager, FinanceApprover, LegalApprover |

## 5. Error Code Catalogue

Trigger conditions for each error are stated in the relevant §2 or §3 narrative.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_AUTH_REQUIRED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_VERSION_CONFLICT` | 409 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_PAGINATION` | 400 |
| `ERR_SUPPLIER_NOT_QUALIFIED` | 422 |
| `ERR_INSUFFICIENT_QUOTES` | 422 |
| `ERR_REQUIREMENT_ALREADY_AWARDED` | 409 |
| `ERR_BUDGET_WOULD_EXCEED` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 422 |
| `ERR_PREDECESSOR_NOT_DECIDED` | 409 |
| `ERR_APPROVAL_DEADLINE_PASSED` | 409 |
| `ERR_DELIVERY_NOTE_MISMATCH` | 422 |
| `ERR_OVER_RECEIPT` | 422 |
| `ERR_THREE_WAY_MATCH_FAILED` | 422 |
| `ERR_TAX_NONCOMPLIANT` | 422 |
| `ERR_DELIVERY_DATE_TOO_EARLY` | 422 |
| `ERR_CONTRACT_ALREADY_EXISTS` | 409 |
| `ERR_PAYMENT_ALREADY_APPLIED` | 409 |
| `ERR_SIGNATURE_ALREADY_COLLECTED` | 409 |
| `ERR_DELEGATE_INVALID_ROLE` | 422 |
| `ERR_CLAUSE_TEMPLATE_INACTIVE` | 422 |

---

## Hard Contract Reports

```
Field coverage check:
- entities[].fields + endpoints[].request_body + query_params + path_params (deduplicated): 95 required, 95 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 20 checked, 20 expressed in prose (§2.8 priority list), 0 missing
- concurrency_rules[] with error_id: 7 checked, 7 expressed (§2.9), 0 missing
- state_machines[].transitions: 41 checked, 41 fully expressed (§3.2–§3.10), 0 missing
- calculations[]: 6 checked, 6 fully expressed (§3.2 quote scoring, §3.3 tier assignment, §3.7 schedule generation, §3.8 supplier rating, §3.9 three-way match, §2.10 budget commitment), 0 missing
- validations[] conditions: 20 checked, 20 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: all checked, all expressed, 0 missing
- entities[].fields[] structured content: 110 checked, 110 reconstructible from prose, 0 missing
- sibling-branch symmetry: TIER_1/2/3/4 routings, ACCEPTED/PARTIALLY_ACCEPTED/REJECTED outcomes, ADVANCE/ON_DELIVERY/NET_N_DAYS/INSTALLMENT terms, MATCHED/EXCEPTION outcomes, opaque-vs-entity-backed identity, all checked at equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 599
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```
