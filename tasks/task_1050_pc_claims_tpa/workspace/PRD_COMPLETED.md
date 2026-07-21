# Pc Claims Tpa API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Property & Casualty Third-Party Claims Administration (TPA) platform. A TPA acts on behalf of insurance carriers (referred to throughout as client accounts) to administer the full life of a first-party claim: intake and adjuster assignment, case-reserve setting, vendor and litigation management, indemnity payment and subrogation recovery, fraud referral, and periodic bordereaux reporting back to the carrier. The system is fundamentally a financial ledger over claims — every reserve adjustment, payment, invoice, and recovery must reconcile precisely against per-claim and per-account roll-up totals, and every disbursement is gated by policy limits, adjuster authority, and segregation-of-duties controls.

The design goal is a system where money never moves without the right person, the right state, and the right amount all lining up at once. Adjusters request; managers approve over-authority work; a separate finance function issues cash. Fraud investigators can freeze a claim independently of the adjusting workflow, litigation and subrogation can hold a claim open, and a claim can be reopened after closure when new information develops. Because several of these actors may be reading and writing the same claim, the platform relies on optimistic concurrency control to reject writes made against a stale view of a claim. All timestamps are governed by a server-controlled logical clock rather than wall-clock time, so that acknowledgement deadlines and policy expiry are deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the operational capacity under which the request is made. A request missing either header, or presenting a role that is not one of the recognized roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly five roles: `Adjuster`, `ClaimsManager`, `FinanceOfficer`, `SiuInvestigator`, and `Vendor`.

Two of these roles are **entity-backed**, meaning their `X-User-ID` is tied to a persisted record. When `X-User-Role` is `Adjuster`, `X-User-ID` is the `id` of the acting `Adjuster` record; ownership checks on any resource that references an adjuster compare that resource's adjuster foreign key to `X-User-ID`. When `X-User-Role` is `Vendor`, `X-User-ID` is the `id` of the acting `Vendor` record; a vendor may submit an expense invoice only against an assignment whose vendor is itself — that is, the assignment's copied `vendor_id` must equal `X-User-ID`, otherwise the submission is rejected with `ERR_UNAUTHORIZED`.

The other three roles are **opaque operator identifiers** not tied to any persisted entity. When `X-User-Role` is `ClaimsManager`, `FinanceOfficer`, or `SiuInvestigator`, `X-User-ID` is an operator identifier that the server may record (for example, the posting role is captured as `actor_role` on a reserve change, and the approving role is captured as `approved_by_role` on a payment or vendor invoice) but does not compare to any entity's `id`. Disposition of a fraud referral is restricted to `SiuInvestigator`.

The role authorized for each individual endpoint is enumerated in the §4 endpoint table; the business narrative in §3 states which role drives each state transition.

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

---

### 2.3. Pagination

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order, with ties on `created_at` broken by ascending creation sequence (insertion order). Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

Most list endpoints also accept reverse-lookup filters, described alongside the workflows they serve in §3; these filter parameters are combined conjunctively with pagination.

### 2.4. The Logical Clock and Common Resource Properties

The platform never reads wall-clock time. Instead it maintains a single server-side logical clock. Before any client sets it, the clock reads `2026-07-01T00:00:00Z` and it never falls back to real time. An administrative test-driving capability sets the clock to a supplied `to_iso8601` instant; all five roles may invoke it. Every timestamp the system stamps — the acknowledgement time of a claim, the issuance time of a payment, policy-status evaluation — is read from this clock.

Most resources carry a common set of system-managed fields: `id` is a server-minted UUID with no type prefix; `created_at` is the ISO 8601 UTC creation timestamp with three fractional digits; `updated_at` is the ISO 8601 UTC timestamp of the last modification (both `created_at` and `updated_at` are read from the server logical clock, not wall-clock time); and `version` is an integer that starts at 1 on creation and increments on every mutation of the resource (subject to the claim-specific refinements in §2.6). The `version` field is the basis of optimistic concurrency control described in §2.6.

One resource is deliberate in **not** carrying the full common set. A `ReserveChange` is an append-only event record: it carries only `id` and `created_at`. It has neither `updated_at` nor `version`, because once posted it is never modified.

### 2.5. Monetary Precision and Rounding

All monetary quantities are stored and computed as **integer cents**; the only exception is bordereaux totals, which are expressed in **whole dollars** (also as integers). Wherever a computation produces a fractional cent or a fractional dollar — a mileage reimbursement, an IBNR floor, a pro-rata recovery split, a cents-to-dollars conversion — the result is rounded using the **round half up** convention (a value exactly halfway between two integers rounds to the larger magnitude). Where a formula multiplies then sums (for example vendor invoice line items, or per-claim dollar conversions in a bordereau), each product or per-item conversion is rounded **before** the summation; the system never sums raw cents and rounds once at the end. The specific rounding order for each calculation is pinned in the §3 narrative that defines it.

### 2.6. Optimistic Concurrency Control on Claims

Because reserve changes, payments, and subrogation recoveries all mutate the same claim and may be issued by different actors, three write operations require the client to prove it is acting on a current view of the claim. Each such request must carry `expected_claim_version` as a mandatory field holding the `version` of the target claim as the client last observed it. If `expected_claim_version` does not equal the claim's current `version`, the write is rejected with `ERR_STALE_VERSION` (HTTP 412), because another writer has advanced the claim since the client read it and proceeding would overwrite work the client never saw.

- Requesting an indemnity payment supplies `expected_claim_version`; a new payment legitimately succeeds against any open claim, so a mismatch here is a stale-version conflict rather than a state error. On success the claim's `version` advances by one.
- Posting a reserve change supplies `expected_claim_version`; on success the claim's `version` advances by one. A prior reserve change or payment creation that bumped the claim will therefore invalidate a stale value.
- Recording a subrogation recovery supplies `expected_claim_version`; the same stale-version rejection applies. Unlike the two operations above, a recorded recovery checks the version but does **not** advance it.

Endpoints not in this list do not take a version field. Separately, a claim's `version` also advances on every lifecycle transition posted through `/claims/{id}/transition` (`ASSIGNED → INVESTIGATING`, `INVESTIGATING → EVALUATED`, `EVALUATED → CLOSED`, reopen, and cancellation). It does **not** advance on the first-assignment acknowledgement, on payment approval, issuance, or void, on vendor-invoice approval, payment, or void, or on an SIU status change; those side effects refresh the claim's `updated_at` only.

### 2.6.1. Segregation of Duties and Approval Authority

Financial control is enforced by separating who may request, approve, and disburse. An `Adjuster` requests indemnity payments and posts reserve changes within an authority limit. A `ClaimsManager` approves payments that exceed adjuster authority. A `FinanceOfficer` — and only a `FinanceOfficer` — issues approved payments, pays approved vendor invoices, records subrogation recoveries, and voids issued payments. This division is why several transitions name a single permitted role even though the surrounding workflow involves several.

### 2.7. Cascading Consistency and Account Roll-Ups

Operations frequently mutate more than one resource. When they do, every secondary effect is part of the operation's contract, not an optional side effect. Closing a claim, cancelling an assignment, and voiding an invoice each cascade into dependent records, and every such cascade also refreshes the affected resource's `updated_at` and increments its `version`. The exact cascades are stated in the §3 workflows.

Two levels of derived totals are kept continuously reconciled. On each claim, `gross_incurred_cents` and `net_incurred_cents` are recomputed after any event that touches its reserve, paid, or recovered buckets. At the account level, three roll-up totals — `open_case_reserve_total_cents`, `gross_incurred_total_cents`, and `recovered_total_cents` — are recomputed after any claim reserve, paid, or recovered mutation, any claim status change, and any claim cancellation. The account roll-up is defined precisely in §3.9.

### 2.8. Request Validation Order

When a request could fail more than one check, the checks are evaluated in a fixed priority order and the first failure determines the error returned. This ordering is a hard contract because it decides which error surfaces when several are simultaneously true:

1. **Authentication** — `X-User-ID` and `X-User-Role` present and the role recognized, else `ERR_UNAUTHENTICATED`.
2. **Authorization** — the acting role is permitted for the operation (including the vendor-owns-assignment rule for invoice submission and the `SiuInvestigator`-only rule for referral disposition), else `ERR_UNAUTHORIZED`.
3. **Existence** — every `id` in the path and every foreign key in the body resolves to an existing resource, checked left to right, else `ERR_NOT_FOUND`.
4. **Request well-formedness** — required fields present, enum values legal, and the field-level constraints in §3 (positive amounts, non-zero deltas, ordered time windows), else `ERR_INVALID_REQUEST`.
5. **State legality** — the target resource is in a legal from-state for the requested transition, and the claim is open where required, else one of `ERR_INVALID_STATE`, `ERR_CLAIM_NOT_OPEN`, `ERR_PAYMENT_PENDING`, `ERR_LITIGATION_OPEN`, or `ERR_SUBROGATION_OPEN`.
6. **Concurrency** — `expected_claim_version` matches the claim's current `version`, else `ERR_STALE_VERSION`.
7. **Referential business rules** — policy active, vendor credentialed, assignee shape correct, yielding `ERR_POLICY_INACTIVE`, `ERR_VENDOR_NOT_CREDENTIALED`, or `ERR_ASSIGNEE_MISMATCH`.
8. **Fraud safety** — the claim is not on an SIU hold when issuing a payment or paying an invoice, else `ERR_SIU_HOLD_ACTIVE`.
9. **Scheduling** — the inspection window does not conflict with another active assignment, else `ERR_ASSIGNMENT_WINDOW_CONFLICT`.
10. **Capacity and approval authority** — adjuster under capacity, and manager approval where required, yielding `ERR_ADJUSTER_CAPACITY` or `ERR_APPROVAL_AUTHORITY_REQUIRED`.
11. **Fiscal limits** — coverage, expense, and reserve-authority ceilings, yielding `ERR_COVERAGE_LIMIT_EXCEEDED`, `ERR_EXPENSE_LIMIT_EXCEEDED`, or `ERR_RESERVE_AUTHORITY_EXCEEDED`.

Foreign keys referenced in a body are resolved as part of step 3 in the order they appear.

## 3. Business Logic & Workflows

### 3.1. Standing Data: Accounts, Policies, Adjusters, and Vendors

A `ClaimsManager` establishes the standing data the rest of the system references. A **client account** represents a carrier and is created with a `name`, a unique `account_code`, and a `reserve_authority_default_cents` that serves as the fallback single-payment auto-approval authority applied to any adjuster who lacks an explicit limit of their own. Two service-level parameters may be supplied or defaulted: `sla_ack_hours` (hours from a claim's report within which it must be acknowledged, default 24) and `sla_contact_hours` (hours within which claimant contact must occur, default 72; this is a reporting parameter only and gates no transition). On creation the account's three roll-up totals — `open_case_reserve_total_cents`, `gross_incurred_total_cents`, and `recovered_total_cents` — all begin at zero. Accounts can be listed and fetched by any role.

A **policy** is created under an account, carrying `client_account_id`, a `policy_number`, a `coverage_limit_cents` (the per-claim indemnity ceiling), an optional `deductible_cents` (default 0), a `per_claim_expense_limit_cents` (the ceiling for vendor/ALAE expense on a claim), an `effective_date`, and an `expiration_date`. A policy's `status` is not stored input; it is derived from the logical clock — a policy reads `ACTIVE` while the current clock instant is before its `expiration_date`, and `EXPIRED` once the clock reaches or passes it. Policies may be listed with reverse-lookup filters `client_account_id` and `status`.

An **adjuster** is created with a `name`, an `email`, an `authority_limit_cents` (the largest single indemnity payment this adjuster may auto-approve, inclusive), and an optional `max_open_claims` (default 50). Its `open_claim_count` — the number of claims currently assigned to this adjuster that are in an open status — starts at zero and is maintained by the system as claims are assigned, closed, and reopened.

A **vendor** is created with a `name`, a `vendor_type` (one of `INDEPENDENT_ADJUSTER`, `APPRAISER`, `CONTRACTOR`, or `DEFENSE_ATTORNEY`), and a `credentialed_coverages` array listing the coverage categories (`PROPERTY`, `AUTO`, `LIABILITY`, `WORKERS_COMP`) the vendor is qualified to service. Vendors may be listed filtered by `vendor_type`.

### 3.2. Claim Intake and the Acknowledgement SLA

An `Adjuster` or a `ClaimsManager` opens a claim against a policy. Intake supplies `policy_id`, `coverage_type` (one of `PROPERTY`, `AUTO`, `LIABILITY`, `WORKERS_COMP`), a `loss_date`, a `reported_date`, a `claimant_name`, and a `description`. The claim's `client_account_id` is copied from the policy rather than supplied. Intake is permitted only while the policy is `ACTIVE`; against an expired policy it is rejected with `ERR_POLICY_INACTIVE`. A new claim enters `INTAKE` status with a fraud posture `siu_status` of `NONE`; its `assigned_adjuster_id` is null, all of its monetary buckets — `indemnity_reserve_cents`, `expense_reserve_cents`, `paid_indemnity_cents`, `paid_expense_cents`, `recovered_cents`, `recovered_indemnity_cents`, `recovered_expense_cents` — start at zero, and its `ack_at` is null.

At intake the system computes the acknowledgement deadline `sla_ack_due` as the claim's `reported_date` plus the owning account's `sla_ack_hours` (a count of hours). Acknowledgement itself does not happen at intake; it happens when the claim is first assigned (§3.3). The compliance flag `sla_ack_met` remains null until the claim is acknowledged. Once `ack_at` is set, `sla_ack_met` is true exactly when `ack_at` is set and is at or before `sla_ack_due`; an acknowledgement landing precisely on the deadline counts as met, because the upper bound is inclusive.

Each claim also maintains two derived incurred figures. `gross_incurred_cents` is the sum of the two paid buckets (`paid_indemnity_cents` plus `paid_expense_cents`) plus the two outstanding case reserves (`indemnity_reserve_cents` plus `expense_reserve_cents`). `net_incurred_cents` is `gross_incurred_cents` less `recovered_cents`. Both are recomputed after any reserve change, any payment issuance or void, any vendor-invoice payment or void, any subrogation recovery, and at claim closure. Claims can be listed with reverse-lookup filters `policy_id`, `client_account_id`, `assigned_adjuster_id`, `status`, and `coverage_type`.

A claim advances through its lifecycle by state transition; every transition request — for claims and for every other resource with a lifecycle — names its target status in a `to_status` field, and the same status enumeration values defined here are the legal targets. Claim transitions are driven by an `Adjuster` (or a `ClaimsManager` for reopen and cancel). From `INTAKE` the first adjuster assignment moves it to `ASSIGNED` (§3.3). An adjuster then advances `ASSIGNED → INVESTIGATING`, `INVESTIGATING → EVALUATED`, and finally `EVALUATED → CLOSED` (§3.9). A `ClaimsManager` may take a `CLOSED` claim to `REOPENED`, from which an adjuster may go `REOPENED → EVALUATED` or `REOPENED → CLOSED`. A claim in `INTAKE` may be `CANCELLED` by a `ClaimsManager` under the conditions in §3.9. The legal statuses are `INTAKE`, `ASSIGNED`, `INVESTIGATING`, `EVALUATED`, `CLOSED`, `REOPENED`, and `CANCELLED`; `CANCELLED` is terminal, whereas `CLOSED` is reopenable and therefore not terminal. Any transition requested from a state that does not permit it is rejected with `ERR_INVALID_STATE`.

### 3.3. Assignments, Inspection Windows, and Capacity

An `Adjuster` or `ClaimsManager` assigns work by creating an assignment referencing `claim_id`, an `assignee_type` of either `ADJUSTER` or `VENDOR`, a `scope` describing the work, and an inspection window bounded by `inspection_start` and `inspection_end`. When `assignee_type` is `ADJUSTER`, `adjuster_id` is required and `vendor_id` must be absent; when `assignee_type` is `VENDOR`, `vendor_id` is required and `adjuster_id` must be absent. A body violating this shape is rejected with `ERR_ASSIGNEE_MISMATCH`. The window must be ordered — `inspection_end` strictly after `inspection_start` — or the request fails well-formedness with `ERR_INVALID_REQUEST`. A newly created assignment is `ACTIVE`.

Two guards apply at creation. First, if a vendor is being assigned, the vendor's `credentialed_coverages` must include the claim's `coverage_type`; otherwise the assignment is rejected with `ERR_VENDOR_NOT_CREDENTIALED`. Second, the new inspection window must not conflict with another `ACTIVE` assignment on the **same assignee**. The conflict test differs by assignee type: for an adjuster, a travel buffer of 60 minutes applies as adjacency — two adjuster windows conflict when they overlap or when the gap separating them is less than 60 minutes, and only windows separated by 60 minutes or more are permitted; for a vendor, no buffer applies and two windows conflict only when their half-open intervals from `inspection_start` up to but not including `inspection_end` actually overlap, so windows that merely touch at an endpoint (one ending exactly when the next begins) are allowed. A conflict yields `ERR_ASSIGNMENT_WINDOW_CONFLICT`.

The **first** `ACTIVE` adjuster assignment created for a claim acknowledges the claim: the system moves the claim `INTAKE → ASSIGNED`, provided the policy is still `ACTIVE` (otherwise `ERR_POLICY_INACTIVE`). That transition sets the claim's `assigned_adjuster_id` to the new assignment's `adjuster_id`, stamps `ack_at` with the current clock time, recomputes `sla_ack_due` and `sla_ack_met`, and increments the assigned adjuster's `open_claim_count`. Before that transition can complete, the assigned adjuster must be under capacity: if the adjuster already holds `max_open_claims` open claims the assignment is rejected with `ERR_ADJUSTER_CAPACITY`. Vendor assignments and any subsequent adjuster assignments do not re-acknowledge the claim.

An `Adjuster` completes an assignment by advancing `ACTIVE → COMPLETED`, or cancels one by advancing `ACTIVE → CANCELLED`. Cancelling an assignment — whether requested directly or performed by the system during claim closure — cascades: every vendor invoice on that assignment whose status is `SUBMITTED` or `APPROVED` is voided (each such void running its own release cascade described in §3.6). Assignments carry statuses `ACTIVE`, `COMPLETED`, and `CANCELLED`, the latter two terminal. Assignments may be listed with reverse-lookup filters `claim_id`, `adjuster_id`, `vendor_id`, and `status`.

### 3.4. Case Reserves and Adjuster Authority

Reserves are the TPA's forward-looking estimate of what a claim will ultimately cost, split into an indemnity (loss) bucket and an expense (ALAE) bucket. A reserve change is posted against an open claim by an `Adjuster` or a `ClaimsManager` and records `claim_id`, a `reserve_type` of `INDEMNITY` or `EXPENSE`, a signed `delta_cents` (which may be negative but must be non-zero, else `ERR_INVALID_REQUEST`), a `reason`, and `expected_claim_version`. The claim must be in an open status — `ASSIGNED`, `INVESTIGATING`, `EVALUATED`, or `REOPENED` — or the post is rejected with `ERR_CLAIM_NOT_OPEN`.

Applying a change adds `delta_cents` to the named bucket, with the resulting bucket floored at zero (a negative delta can never drive a reserve below zero). The event captures the post-change values in `resulting_indemnity_reserve_cents` and `resulting_expense_reserve_cents`, records the posting role in `actor_role`, advances the claim's `version` by one, and recomputes both the claim's `gross_incurred_cents` and the account roll-up. Reserve changes are append-only and may be listed with filters `claim_id` and `reserve_type`.

Authority is enforced on adjuster-posted changes only. After applying the delta, if the acting principal is an `Adjuster`, the claim's total case reserve — the sum of `indemnity_reserve_cents` and `expense_reserve_cents` after the change — must not exceed that adjuster's `authority_limit_cents`; if it would, the change is rejected with `ERR_RESERVE_AUTHORITY_EXCEEDED`. Changes posted by a `ClaimsManager` are not subject to any reserve-authority ceiling.

### 3.5. Indemnity Payments: Request, Approval, Issuance, and Void

Paying a claimant is a three-actor workflow reflecting segregation of duties. An `Adjuster` or `ClaimsManager` requests a payment against an open claim, supplying `claim_id`, a `payment_type` of `INDEMNITY`, a `payee_type` of `CLAIMANT`, a `payee_name`, an `amount_cents` that must be greater than zero, and `expected_claim_version`. The claim must be open (`ERR_CLAIM_NOT_OPEN` otherwise) and the version must match (`ERR_STALE_VERSION` otherwise). A new payment enters `PENDING_APPROVAL`. At creation the system computes `requires_manager_approval`: it is true exactly when `amount_cents` is strictly greater than the creating adjuster's `authority_limit_cents`, and false when the amount equals or is below that limit (an amount equal to the limit is within authority); a payment created by a `ClaimsManager` rather than an adjuster always has `requires_manager_approval` false. Creating a payment advances the claim's `version` by one.

Approval moves the payment `PENDING_APPROVAL → APPROVED` and requires the claim to still be open (`ERR_CLAIM_NOT_OPEN`). Who may approve depends on the routing flag: when `requires_manager_approval` is false an `Adjuster` may approve as well as a `ClaimsManager`; when it is true only a `ClaimsManager` may, and an attempt by any other role is rejected with `ERR_APPROVAL_AUTHORITY_REQUIRED`. Approval records `approved_by_role`. Alternatively a `ClaimsManager` may reject a pending payment, moving it `PENDING_APPROVAL → REJECTED`, which is terminal.

Issuance is the disbursement of cash and is reserved to a `FinanceOfficer`, moving the payment `APPROVED → ISSUED`. Four conditions guard it, in the standard order: the claim must be open (`ERR_CLAIM_NOT_OPEN`); the policy must be `ACTIVE` (`ERR_POLICY_INACTIVE`); the claim must not be on an SIU hold, i.e. `siu_status` must not be `HELD` (`ERR_SIU_HOLD_ACTIVE`); and the payment must fit within coverage — specifically `amount_cents` plus the claim's current `paid_indemnity_cents`, less the policy's `deductible_cents`, must be no greater than the policy's `coverage_limit_cents`, or the issuance is rejected with `ERR_COVERAGE_LIMIT_EXCEEDED`. On issuance the system adds `amount_cents` to `paid_indemnity_cents`, reduces `indemnity_reserve_cents` by `amount_cents` floored at zero (releasing reserve as it converts to paid), stamps `issued_at` with the clock, records `approved_by_role`, and recomputes the claim's incurred figures and the account roll-up.

A `FinanceOfficer` may void a payment either from `APPROVED` (no financial effect) or from `ISSUED`. Voiding an issued payment is a compensating reversal: it subtracts `amount_cents` back out of `paid_indemnity_cents`, restores `amount_cents` to `indemnity_reserve_cents` (undoing the reserve release performed at issuance), and recomputes the claim's incurred figures and the account roll-up. Payment statuses are `PENDING_APPROVAL`, `APPROVED`, `REJECTED`, `ISSUED`, and `VOID`, with `REJECTED` and `VOID` terminal. Payments may be listed with filters `claim_id` and `status`.

### 3.6. Vendor Invoices and Expense Control

Expense (ALAE) enters the ledger through vendor invoices. Only a `Vendor` submits one, and only against an assignment it owns — the assignment's copied `vendor_id` must equal the submitter's `X-User-ID`, else `ERR_UNAUTHORIZED`. Submission carries `claim_id`, `assignment_id`, `hours`, an optional `miles` (default 0), and optional `materials_cents` (default 0); the invoice's own `vendor_id` is copied from the assignment. The billed `amount_cents` is computed at submission from a tiered hourly rate keyed on the assignment's vendor type: an `INDEPENDENT_ADJUSTER` bills 12000 cents per hour, an `APPRAISER` 15000 cents per hour, a `DEFENSE_ATTORNEY` 35000 cents per hour, and a `CONTRACTOR` 0 cents per hour. The labor component is `hours` multiplied by that rate, rounded half up; the mileage component is `miles` multiplied by 55 cents, rounded half up; these two rounded components are then added to `materials_cents` to form a subtotal. The final `amount_cents` is that subtotal, but never less than a 5000-cent minimum and never more than a 2,000,000-cent cap — a subtotal below 5000 is raised to 5000, and one above 2,000,000 is lowered to 2,000,000. A submitted invoice starts in `SUBMITTED`.

A `ClaimsManager` approves an invoice, moving it `SUBMITTED → APPROVED`, but only if it fits the claim's expense budget: `amount_cents` plus the claim's `paid_expense_cents` plus its `expense_reserve_cents` must be no greater than the policy's `per_claim_expense_limit_cents`, else `ERR_EXPENSE_LIMIT_EXCEEDED`. Approval earmarks the expense by adding `amount_cents` to `expense_reserve_cents`, records `approved_by_role`, and recomputes the account roll-up. A `ClaimsManager` may instead reject it (`SUBMITTED → REJECTED`).

A `FinanceOfficer` pays an approved invoice, moving it `APPROVED → PAID`, provided the claim is open (`ERR_CLAIM_NOT_OPEN`) and not on an SIU hold, meaning `siu_status` is not `HELD` (`ERR_SIU_HOLD_ACTIVE`). Payment adds `amount_cents` to `paid_expense_cents`, reduces `expense_reserve_cents` by `amount_cents` floored at zero (converting the earmark to paid), and recomputes the claim's incurred figures and the account roll-up. An approved invoice may instead be voided by a `FinanceOfficer`; a void — whether requested directly or triggered by the cascade when the parent assignment is cancelled — releases the earmark by subtracting `amount_cents` from `expense_reserve_cents` and recomputes the claim's `gross_incurred_cents` and the account roll-up. A `SUBMITTED` invoice can also be voided by the system through that same assignment-cancellation cascade; because a `SUBMITTED` invoice never earmarked any reserve, voiding it releases nothing and has no financial effect. Invoice statuses are `SUBMITTED`, `APPROVED`, `REJECTED`, `PAID`, and `VOID`, with `REJECTED`, `PAID`, and `VOID` terminal. Invoices may be listed with filters `claim_id`, `vendor_id`, `assignment_id`, and `status`.

### 3.7. Litigation, Subrogation, and Recovery Allocation

When a claim goes to law, a `ClaimsManager` opens a litigation case referencing `claim_id`, an optional `defense_vendor_id` naming assigned defense counsel, and a `venue`. A litigation case begins `OPEN` and is advanced only by a `ClaimsManager`: from `OPEN` it may go to `IN_SUIT` or `DISMISSED`; from `IN_SUIT` it may go to `SETTLED`, `DISMISSED`, or `JUDGMENT`. The terminal statuses are `SETTLED`, `DISMISSED`, and `JUDGMENT`; while a case remains `OPEN` or `IN_SUIT` it is non-terminal and blocks claim closure (§3.9). Litigation cases may be listed with filters `claim_id`, `defense_vendor_id`, and `status`.

Subrogation is the pursuit of recovery from an at-fault third party. An `Adjuster` or `ClaimsManager` opens a subrogation case with `claim_id`, an `at_fault_party`, and a `demand_cents` that must be greater than zero. It begins `OPEN`; an adjuster advances it `OPEN → DEMAND_SENT` and `DEMAND_SENT → NEGOTIATING`, and from any of `OPEN`, `DEMAND_SENT`, or `NEGOTIATING` may instead close it as `CLOSED_NO_RECOVERY`. The recovery itself — `NEGOTIATING → RECOVERED` — is reserved to a `FinanceOfficer` and carries `recovered_cents` (which must be greater than zero, else `ERR_INVALID_REQUEST`), an `allocation_method` of either `PRO_RATA` or `INDEMNITY_FIRST` (any other value is `ERR_INVALID_REQUEST`), and `expected_claim_version` for the stale-version check. Recording a recovery stores `recovered_cents` and `allocation_method` on the subrogation case, then posts the gross recovery to the claim and allocates it across the claim's two recovery buckets. Subrogation statuses are `OPEN`, `DEMAND_SENT`, `NEGOTIATING`, `RECOVERED`, and `CLOSED_NO_RECOVERY`, with `RECOVERED` and `CLOSED_NO_RECOVERY` terminal; a subrogation case that is `OPEN`, `DEMAND_SENT`, or `NEGOTIATING` blocks claim closure. These cases may be listed with filters `claim_id` and `status`.

The allocation splits the recovery amount between indemnity and expense according to the chosen method, against the claim's current paid buckets. Let the recovery amount be the recorded `recovered_cents`, and let the base be the sum of the claim's `paid_indemnity_cents` and `paid_expense_cents`. Under `PRO_RATA`: if the base is zero, the entire recovery is allocated to indemnity and none to expense; otherwise the indemnity share is the recovery amount multiplied by `paid_indemnity_cents` divided by the base, rounded half up, and the expense share is the remainder (the recovery amount less the indemnity share). Under `INDEMNITY_FIRST`: the indemnity share is the lesser of the recovery amount and `paid_indemnity_cents`, and the expense share is whatever remains. The computed indemnity share is added to the claim's `recovered_indemnity_cents`, the expense share to `recovered_expense_cents`, and the full recovery amount to `recovered_cents`. The claim's `net_incurred_cents` is then recomputed and the account roll-up refreshed. The two methods diverge only when both paid buckets are non-zero.

### 3.8. SIU Fraud Referrals and Holds

Fraud handling runs alongside adjusting and can freeze disbursements without stopping the adjusting workflow. An `Adjuster`, `ClaimsManager`, or `SiuInvestigator` refers a claim to the Special Investigations Unit with `claim_id`, a `reason`, and an optional `place_hold` flag (default true). Creating a referral with `place_hold` true immediately sets the claim's `siu_status` to `HELD`. A referral begins `OPEN` and may be listed with filters `claim_id` and `status`.

Disposition belongs solely to a `SiuInvestigator`. Clearing a referral (`OPEN → CLEARED`) lifts any hold: if the claim's `siu_status` is currently `HELD`, it is set to `CLEARED`, which re-permits payment issuance and invoice payment. Confirming a referral (`OPEN → CONFIRMED`) sets the claim's `siu_status` to `CONFIRMED` and leaves the hold in force. The referral's own terminal statuses are `CLEARED` and `CONFIRMED`. A claim's `siu_status` values are `NONE`, `HELD`, `CLEARED`, and `CONFIRMED`; while it is `HELD`, issuing a payment or paying a vendor invoice is blocked with `ERR_SIU_HOLD_ACTIVE`, and a claim that is `HELD` cannot be closed.

### 3.9. Claim Closure, Cancellation, Reopening, and Reporting

Closing a claim is the reconciliation point where reserves are released and the open population shrinks. An `Adjuster` closes a claim from `EVALUATED` (or from `REOPENED`, which follows the identical rules). Four preconditions guard closure: every litigation case on the claim must be terminal — `SETTLED`, `DISMISSED`, or `JUDGMENT` — otherwise `ERR_LITIGATION_OPEN`; no subrogation case may be `OPEN`, `DEMAND_SENT`, or `NEGOTIATING`, otherwise `ERR_SUBROGATION_OPEN`; no payment may be `PENDING_APPROVAL` or `APPROVED`, otherwise `ERR_PAYMENT_PENDING`; and the claim's `siu_status` must not be `HELD`, otherwise `ERR_SIU_HOLD_ACTIVE`. When those pass, closure cascades: every `ACTIVE` assignment on the claim is cancelled (each firing its own vendor-invoice void cascade from §3.3 and §3.6), both `indemnity_reserve_cents` and `expense_reserve_cents` are set to zero, the claim's `gross_incurred_cents` and `net_incurred_cents` are recomputed, the assigned adjuster's `open_claim_count` is decremented, and the account roll-up is refreshed.

A `ClaimsManager` may cancel a claim, but only from `INTAKE` and only if nothing financial has attached: no assignment may exist for the claim and no payment may exist for it; either condition present rejects the cancellation with `ERR_INVALID_STATE`. Cancellation refreshes the account roll-up. A `ClaimsManager` may also reopen a `CLOSED` claim (`CLOSED → REOPENED`); reopening returns the claim to the open population, so it increments the assigned adjuster's `open_claim_count` and refreshes the account roll-up.

The account roll-up recomputed by all these operations is defined as follows over the claims of a single account. `open_case_reserve_total_cents` is the sum of each open claim's `indemnity_reserve_cents` plus `expense_reserve_cents`, counting only claims whose status is `INTAKE`, `ASSIGNED`, `INVESTIGATING`, `EVALUATED`, or `REOPENED`. `gross_incurred_total_cents` is the sum of `gross_incurred_cents` over the account's claims whose status is not `CANCELLED`. `recovered_total_cents` is the sum of `recovered_cents` over the account's claims whose status is not `CANCELLED`.

Any role may pull a per-claim financial snapshot, which surfaces both the provisional and the developed view of incurred. It returns `paid_total_cents` (the two paid buckets combined), `outstanding_reserve_cents` (the two case reserves combined), `gross_incurred_provisional_cents` (paid total plus the case reserves exactly as set — the same basis stored in the claim's `gross_incurred_cents`), `gross_incurred_developed_cents`, and `net_incurred_cents`. The **developed** basis applies an incurred-but-not-reported tail: the developed outstanding is the greater of the set case reserves and 15 percent of the paid total (that product rounded half up), and the developed gross incurred is the paid total plus that developed outstanding. The developed figure therefore diverges from the provisional figure precisely when the IBNR floor exceeds the case reserves actually set.

Finally, a `ClaimsManager` or `FinanceOfficer` runs a bordereau for an account over a reporting period, supplying `client_account_id`, a `period_start`, a `period_end` (which must be strictly after `period_start`), and a `basis` of `PROVISIONAL` or `DEVELOPED`. The in-scope claims are those of the account whose status is not `CANCELLED` and whose `reported_date` falls in the half-open interval from `period_start` up to but not including `period_end`. The report records `total_claim_count` as the number of in-scope claims. For each in-scope claim the system converts its incurred to whole dollars — using the developed gross incurred when the basis is `DEVELOPED` and the provisional `gross_incurred_cents` when the basis is `PROVISIONAL`, dividing by 100 and rounding half up — and separately converts its paid total (`paid_indemnity_cents` plus `paid_expense_cents`, divided by 100, rounded half up) and its `recovered_cents` (divided by 100, rounded half up). These per-claim dollar figures are summed to yield `total_incurred_dollars`, `total_paid_dollars`, and `total_recovered_dollars`. The rounding order is pinned: each claim is rounded to whole dollars first and the rounded per-claim figures are then summed — the system never sums raw cents and rounds once. Bordereaux may be listed with filters `client_account_id` and `basis`.

## 4. Endpoint Definitions

New, stand-alone resource creations return `201 Created`. State transitions, other modifications, list and fetch reads, and the logical-clock capability return `200 OK`. "Any" in the authorized-role column denotes all five roles (`Adjuster`, `ClaimsManager`, `FinanceOfficer`, `SiuInvestigator`, `Vendor`).

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | Any |
| POST | `/client-accounts` | Create a client (carrier) account | ClaimsManager |
| GET | `/client-accounts/{id}` | Fetch a client account | Any |
| GET | `/client-accounts` | List client accounts | Any |
| POST | `/policies` | Create a policy under an account | ClaimsManager |
| GET | `/policies/{id}` | Fetch a policy | Any |
| GET | `/policies` | List policies (filter by account, status) | Any |
| POST | `/adjusters` | Create an adjuster | ClaimsManager |
| GET | `/adjusters/{id}` | Fetch an adjuster | Any |
| GET | `/adjusters` | List adjusters | Any |
| POST | `/vendors` | Create a vendor | ClaimsManager |
| GET | `/vendors/{id}` | Fetch a vendor | Any |
| GET | `/vendors` | List vendors (filter by type) | Any |
| POST | `/claims` | Open a claim (intake) | Adjuster, ClaimsManager |
| GET | `/claims/{id}` | Fetch a claim | Any |
| GET | `/claims` | List/filter claims | Any |
| POST | `/claims/{id}/transition` | Advance claim lifecycle | Adjuster, ClaimsManager |
| GET | `/claims/{id}/financials` | Computed financial snapshot | Any |
| POST | `/assignments` | Assign an adjuster or vendor with an inspection window | Adjuster, ClaimsManager |
| GET | `/assignments/{id}` | Fetch an assignment | Any |
| GET | `/assignments` | List/filter assignments | Any |
| POST | `/assignments/{id}/transition` | Complete or cancel an assignment | Adjuster, ClaimsManager |
| POST | `/reserve-changes` | Post a case reserve adjustment (OCC on the claim) | Adjuster, ClaimsManager |
| GET | `/reserve-changes/{id}` | Fetch a reserve change | Any |
| GET | `/reserve-changes` | List reserve changes (filter by claim, type) | Any |
| POST | `/payments` | Request an indemnity payment (OCC on the claim) | Adjuster, ClaimsManager |
| GET | `/payments/{id}` | Fetch a payment | Any |
| GET | `/payments` | List payments (filter by claim, status) | Any |
| POST | `/payments/{id}/transition` | Approve/reject/issue/void a payment | Adjuster, ClaimsManager, FinanceOfficer |
| POST | `/vendor-invoices` | Vendor submits an expense invoice against an assignment | Vendor |
| GET | `/vendor-invoices/{id}` | Fetch a vendor invoice | Any |
| GET | `/vendor-invoices` | List vendor invoices | Any |
| POST | `/vendor-invoices/{id}/transition` | Approve/reject/pay a vendor invoice | ClaimsManager, FinanceOfficer |
| POST | `/litigation-cases` | Open a litigation record for a claim | ClaimsManager |
| GET | `/litigation-cases/{id}` | Fetch a litigation case | Any |
| GET | `/litigation-cases` | List litigation cases | Any |
| POST | `/litigation-cases/{id}/transition` | Advance litigation status | ClaimsManager |
| POST | `/subrogation-cases` | Open a subrogation pursuit for a claim | Adjuster, ClaimsManager |
| GET | `/subrogation-cases/{id}` | Fetch a subrogation case | Any |
| GET | `/subrogation-cases` | List subrogation cases | Any |
| POST | `/subrogation-cases/{id}/transition` | Advance subrogation; RECOVERED posts recovery (OCC on the claim) | Adjuster, ClaimsManager, FinanceOfficer |
| POST | `/siu-referrals` | Refer a claim to SIU (fraud) | Adjuster, ClaimsManager, SiuInvestigator |
| GET | `/siu-referrals/{id}` | Fetch an SIU referral | Any |
| GET | `/siu-referrals` | List SIU referrals | Any |
| POST | `/siu-referrals/{id}/transition` | Clear or confirm an SIU referral | SiuInvestigator |
| POST | `/bordereau-reports` | Generate a period bordereau for an account | ClaimsManager, FinanceOfficer |
| GET | `/bordereau-reports/{id}` | Fetch a bordereau report | Any |
| GET | `/bordereau-reports` | List bordereau reports | Any |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CLAIM_NOT_OPEN` | 409 |
| `ERR_PAYMENT_PENDING` | 409 |
| `ERR_LITIGATION_OPEN` | 409 |
| `ERR_SUBROGATION_OPEN` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_POLICY_INACTIVE` | 409 |
| `ERR_VENDOR_NOT_CREDENTIALED` | 409 |
| `ERR_ASSIGNEE_MISMATCH` | 422 |
| `ERR_SIU_HOLD_ACTIVE` | 403 |
| `ERR_ASSIGNMENT_WINDOW_CONFLICT` | 409 |
| `ERR_ADJUSTER_CAPACITY` | 409 |
| `ERR_APPROVAL_AUTHORITY_REQUIRED` | 403 |
| `ERR_COVERAGE_LIMIT_EXCEEDED` | 422 |
| `ERR_EXPENSE_LIMIT_EXCEEDED` | 422 |
| `ERR_RESERVE_AUTHORITY_EXCEEDED` | 422 |
