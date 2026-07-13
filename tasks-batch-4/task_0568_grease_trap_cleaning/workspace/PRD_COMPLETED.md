# FOG Compliance Service API — Product Requirements Document

## 1. Introduction

Commercial kitchens generate fats, oils, and grease (FOG) that municipalities regulate aggressively: grease traps must be pumped out on a schedule, exhaust hoods must be cleaned and certified to NFPA 96, and every food-service site must periodically demonstrate compliance to its local jurisdiction. This API is the system of record for a cleaning contractor that services those establishments end to end — it holds the customer and site directory, tracks each piece of serviceable equipment and when it is next due, dispatches technicians on routed work orders, captures the field artifacts (pump-out manifests and hood-cleaning certificates) that prove the work was done, files FOG-compliance reports to municipalities, and drives recurring billing.

The platform exists to keep three otherwise-independent obligations in lockstep: a site's real-time compliance grade, the field work that restores it, and the money owed for that work. Because a lapse in any one of these can trigger regulatory or financial consequences, the system treats them as a single reconciled whole — completing a service refreshes the equipment schedule, which re-grades the site, which can lift a compliance-driven account suspension. This document specifies the entities, their state machines, the calculations that value work and grade compliance, the validation ladder that guards every mutation, and the endpoints through which the five operator roles interact with the system.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts that hold across every endpoint: authentication, response shape, pagination, common resource properties, the logical clock, monetary precision, concurrency control, cross-entity reconciliation, nested retrieval, and the order in which validations run.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the principal's operational capacity. If `X-User-Role` is missing or is not one of the roles enumerated below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is recognized but is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly five roles:

- **`Admin`** — manages accounts, sites, equipment, service contracts, technicians, and the logical clock. When `X-User-Role` is `Admin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- **`Dispatcher`** — creates and routes work orders. When `X-User-Role` is `Dispatcher`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- **`Technician`** — performs field services and files manifests and certificates. When `X-User-Role` is `Technician`, `X-User-ID` is the `id` of the acting `Technician` entity. Ownership checks compare a work order's `technician_id` to `X-User-ID`: a technician may start or complete only a work order assigned to that technician, and a mismatch is rejected with `ERR_FORBIDDEN`.
- **`ComplianceOfficer`** — prepares, files, and dispositions FOG-compliance reports. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- **`BillingClerk`** — generates invoices and records payments. When `X-User-Role` is `BillingClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.

The authoritative mapping of role to operation is the endpoint table in §4; the narrative of §3 describes who performs each action.

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

List endpoints accept two query parameters, `limit` and `offset`. `limit` is the maximum number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` is the number of items to skip and defaults to 0, with a minimum of 0. A `limit` outside the range 1 through 100, or a negative `offset`, is rejected with `ERR_PAGINATION_INVALID` (HTTP 400).

Unless otherwise stated, list endpoints return resources sorted by their `created_at` timestamp in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object.

### 2.4. Common Resource Properties and Identifiers

Every primary resource in this system — `Customer`, `Site`, `Equipment`, `ServiceContract`, `Technician`, `WorkOrder`, `PumpOutManifest`, `HoodCertificate`, `ComplianceReport`, and `Invoice` — carries a standard set of system-managed fields:

- `id`: a server-minted UUID with no type prefix, unique across the system.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits, set when the resource is first created.
- `updated_at`: an ISO 8601 UTC timestamp, refreshed on every mutation of the resource, including mutations to its computed fields.
- `version`: an integer that starts at 1 and increments by 1 on every mutation. It is the basis for the optimistic-concurrency check described in §2.7.

All ten entity types carry all four common fields. Identifier references between resources — a site's `customer_id`, an equipment's `site_id`, a work order's `equipment_id`, and so on — are plain string UUIDs pointing at another resource's `id`.

### 2.5. The Logical Service Clock

All time-relative derivations in this system — whether a piece of equipment is overdue, a certificate's expiry, the completion timestamp stamped on a finished work order — are measured against a **logical clock** rather than wall-clock time. On server startup the logical clock reads `2026-05-01T00:00:00Z`, and it never falls back to wall-clock time. An `Admin` may advance or set the clock by supplying a `to_iso8601` instant; this is a test-driving capability that carries no state transition of its own. When the clock moves, each equipment's `service_state` and each site's `compliance_status` and `projected_compliance_status` are re-derived on read against the new "now", and the equipment fields `next_service_due_at`, `last_service_at`, a work order's `completed_at`, and a certificate's `issued_at` and `valid_until` are all interpreted relative to this clock.

### 2.6. Monetary Precision and Rounding

All monetary amounts — `credit_limit_cents`, `base_rate_cents`, `service_fee_cents`, `emergency_surcharge_cents`, `disposal_fee_cents`, `subtotal_cents`, `tax_cents`, `total_amount_cents`, `provisional_total_cents`, `amount_paid_cents`, and `outstanding_balance_cents` — are integers denominated in cents and are computed with exact integer arithmetic. Where a calculation produces a fractional cent (the FOG surcharge on a disposal fee, or per-line invoice tax), the result is rounded **half up** to the nearest whole cent. Rounding is applied at the specific points named in §3; unless a step explicitly rounds, intermediate sums remain exact.

### 2.7. Optimistic Concurrency Control

Creating an `Invoice` is guarded by optimistic concurrency against its parent `Customer`. The create request must include a non-optional `expected_customer_version` field carrying the client's last observed `version` of that customer. If `expected_customer_version` is omitted, the request is rejected with `ERR_VERSION_REQUIRED` (HTTP 400). If it is present but does not equal the customer's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

This matters because a newly created invoice supersedes any prior `DRAFT` invoice for the same billing period — the prior draft is automatically voided — and creating an invoice itself advances the customer's `version`. If another writer has already created or superseded an invoice and thereby advanced the customer's `version` since this client last read it, the stale-version rejection prevents the client from overwriting an invoice it never observed. No other endpoint takes a version field; only invoice creation participates in this check.

### 2.8. Cross-Entity Reconciliation and Cascades

The system maintains immediate consistency across the customer → site → equipment hierarchy and the billing ledger. Several operations mutate more than one entity in a single transaction; each secondary mutation independently refreshes the affected resource's `updated_at` and increments its `version`.

The central reconciliation chain begins when a piece of equipment's service schedule changes. Whenever `last_service_at` and `next_service_due_at` are recomputed for an equipment, that equipment's `service_state` is re-derived, then the owning site's `compliance_status` and `projected_compliance_status` are re-graded (the site's `updated_at` and `version` advance only when this re-grade actually changes its `compliance_status` or `projected_compliance_status`), and then — if the re-grade changes whether the site is `NON_COMPLIANT` — the owning customer's `account_status` is reconciled. A customer with at least one owned site graded `NON_COMPLIANT` is moved to `SUSPENDED`; a `SUSPENDED` customer whose owned sites are all no longer `NON_COMPLIANT` is moved back to `ACTIVE`. These `account_status` transitions happen only by cascade, never by a direct request.

Site compliance is also reconciled when a compliance report is accepted, when a pump-out manifest is created or voided, and when new equipment is added to a site. The billing ledger reconciles on invoice issue, payment, and void, as described in §2.9 and §3.7.

### 2.9. The Outstanding-Balance Ledger

Each customer's `outstanding_balance_cents` is a conserved quantity equal to the sum of `total_amount_cents` over that customer's invoices currently in `ISSUED` status. Three events move it, and each also increments the customer's `version` by 1: issuing an invoice adds that invoice's `total_amount_cents` to the balance; recording full payment removes the invoice from the `ISSUED` set and therefore subtracts its `total_amount_cents`; voiding an issued invoice subtracts its `total_amount_cents`, exactly reversing the debit that issuing applied. The system guarantees that for any single invoice, an issue followed by a void leaves `outstanding_balance_cents` unchanged.

### 2.10. Nested and Filtered Retrieval

Sub-resource collections are reached through their parent's path — a customer's sites and contracts, a site's equipment and compliance reports, an equipment's work orders, a work order's manifests and certificates. For any request whose path names more than one resource identifier, existence is validated left to right, and the first identifier that does not resolve produces `ERR_NOT_FOUND` (HTTP 404) before any later identifier or body reference is examined. Body foreign-key references (for example a work order's `site_id` and `equipment_id`, or a manifest's `work_order_id`) are likewise required to resolve, failing with `ERR_NOT_FOUND` when they do not.

The work-order list supports filtering by `site_id`, `equipment_id`, `technician_id`, `contract_id`, and `status`; the invoice list supports filtering by `customer_id`, `contract_id`, and `status`. All filters combine with the pagination parameters of §2.3.

### 2.11. Validation Order and Error Precedence

When a single request could fail several checks, the system evaluates them in a fixed priority order and returns the first failure. The order is:

1. **Authentication** — a present, recognized `X-User-Role`; otherwise `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the role is permitted for the operation, and an entity-backed `Technician` owns the work order it acts on for start and complete; otherwise `ERR_FORBIDDEN` (403).
3. **Existence** — all path identifiers and body foreign keys resolve (left to right); otherwise `ERR_NOT_FOUND` (404).
4. **Request shape** — required fields present, enum values in range, and window/period ordering valid; otherwise `ERR_VALIDATION` (400) for general shape problems, `ERR_PAGINATION_INVALID` (400) for bad pagination, and `ERR_REPORT_PERIOD_INVALID` (422) specifically when a compliance report's or invoice's `period_end` is not strictly after its `period_start`.
5. **From-state** — the target resource is in a legal state for the requested transition; otherwise `ERR_INVALID_STATE` (409).
6. **Referential type integrity** — a manifest's work order is `GREASE_TRAP` and a certificate's work order is `HOOD` (`ERR_EQUIPMENT_TYPE_MISMATCH`, 422), and a manifest's `disposal_facility_permit` is well-formed (`ERR_DISPOSAL_FACILITY_INVALID`, 422).
7. **Safety** — NFPA 96 certification rules on hood dispatch and completion (`ERR_TECHNICIAN_NOT_CERTIFIED`, 422; and `ERR_CLEANLINESS_FAILED`, 422, at completion).
8. **Equipment service buffer** — the 24-hour spacing rule on new work orders (`ERR_EQUIPMENT_SERVICE_TOO_SOON`, 409).
9. **Technician schedule** — no overlapping active assignment (`ERR_TECHNICIAN_SCHEDULE_CONFLICT`, 409).
10. **Equipment availability** — the equipment is `ACTIVE` at dispatch (`ERR_EQUIPMENT_DECOMMISSIONED`, 409).
11. **Completion artifacts** — the required manifest or certificate exists (`ERR_MANIFEST_REQUIRED` / `ERR_CERTIFICATE_REQUIRED`, 422).
12. **Billable activity** — at least one billable line exists at issue (`ERR_NO_BILLABLE_ACTIVITY`, 422).
13. **Fiscal standing** — the customer is not `CLOSED` (`ERR_CUSTOMER_CLOSED`, 409) and the credit limit is respected (`ERR_CREDIT_LIMIT_EXCEEDED`, 402).
14. **Optimistic concurrency** — `expected_customer_version` matches on invoice creation (`ERR_STALE_VERSION`, 412).

Because this order is total, an earlier failure always masks a later one — for example, an unauthenticated caller receives `ERR_UNAUTHENTICATED` even if the body is also malformed, and a work order in the wrong from-state receives `ERR_INVALID_STATE` before any safety or schedule check runs.

## 3. Business Logic & Workflows

### 3.1. Customer Accounts and Service Contracts

An `Admin` opens the relationship by creating a `Customer`, supplying the establishment's `business_name` and a `billing_email`; an optional `credit_limit_cents` sets the ceiling on outstanding balance before new invoices are blocked, defaulting to 500000 cents when omitted. A new customer begins in `account_status` `ACTIVE` with `outstanding_balance_cents` of 0 and `version` 1. The `account_status` enumeration is `ACTIVE`, `SUSPENDED`, and `CLOSED`. As described in §2.8, `SUSPENDED` is reached and released only by compliance cascade; it is never set directly.

Closing an account is an `Admin` action that moves the customer to the terminal `CLOSED` state. It is permitted from either `ACTIVE` or `SUSPENDED`, but only when `outstanding_balance_cents` equals 0; a close attempt against a customer with any outstanding balance is rejected with `ERR_INVALID_STATE`. Once `CLOSED`, the account is terminal.

Recurring billing terms live on a `ServiceContract`, created by an `Admin` against a customer via its `customer_id`. A contract carries a `billing_cycle` of either `MONTHLY` or `QUARTERLY`, a `base_rate_cents` recurring fee per period, and a `tax_rate_bps` tax rate expressed in basis points (for example, 825 means 8.25 percent). A contract is created in `DRAFT`. An `Admin` drives its lifecycle by supplying a target `to_status`: `DRAFT` advances to `ACTIVE`; an `ACTIVE` contract may be suspended to `SUSPENDED` and a `SUSPENDED` contract reactivated to `ACTIVE`; and an `ACTIVE` contract may be cancelled to the terminal `CANCELLED` state. A contract's base-rate line participates in billing only while the contract is `ACTIVE`, as detailed in §3.7.

### 3.2. Sites, Equipment, and the Service Schedule

Under a customer sits one or more `Site` records, each created by an `Admin` with the owning `customer_id`, a physical `address`, the `municipality_code` of the jurisdiction it reports FOG compliance to, and its municipal `permit_number`. A brand-new site with no equipment grades as `COMPLIANT`. A site exposes three computed fields: `compliance_status`, its forward-looking twin `projected_compliance_status`, and `last_certified_at`, the decision timestamp of the site's most recent accepted compliance report (null if none has ever been accepted).

Serviceable assets are `Equipment` records, created by an `Admin` against a site via `site_id`. Each has an `equipment_type` of `GREASE_TRAP` or `HOOD`, a `capacity_gallons` figure (the grease-trap capacity in gallons; informational for a hood), and a `nominal_frequency_days` scheduled service interval. Equipment starts in `status` `ACTIVE`; the only other status, `DECOMMISSIONED`, is terminal. Because a freshly created piece of equipment has never been serviced, it lands with a `service_state` of `OVERDUE`, and adding it re-grades the owning site's compliance. An `Admin` may decommission equipment, moving it to `DECOMMISSIONED`, but only when no work order in `SCHEDULED`, `DISPATCHED`, or `IN_PROGRESS` references it; otherwise the request is rejected with `ERR_INVALID_STATE`.

Equipment tracks its own service history through computed fields. `last_service_at` is the `completed_at` of the most recent `COMPLETED` work order for that equipment, or null if it has never been serviced. `next_service_due_at` is `last_service_at` plus `nominal_frequency_days`; when there is no service history it is null and the equipment is treated as overdue. From these, the `service_state` is derived against the logical clock: the equipment is `OVERDUE` when `next_service_due_at` is null or lies strictly before now; otherwise it is `DUE_SOON` when `next_service_due_at` falls strictly within the next 7 days; otherwise it is `CURRENT`. Equipment also accumulates `lifetime_pumped_gallons`, the sum of `volume_gallons` across its work orders' manifests that are in `RECORDED` status.

A site's compliance grade is a threshold over its `ACTIVE` equipment only — decommissioned equipment is excluded. Let the overdue count be the number of `ACTIVE` equipment at the site whose `next_service_due_at` is null or lies strictly before now, and let the due-soon count over a horizon be the number of `ACTIVE` equipment whose `next_service_due_at` is at or after now and strictly before now plus that horizon. The grade is `NON_COMPLIANT` when the overdue count is greater than zero; otherwise `AT_RISK` when the due-soon count is greater than zero; otherwise `COMPLIANT`. The `compliance_status` uses a 7-day due-soon horizon (the near-term, as-of view), while `projected_compliance_status` uses a 30-day horizon (the forward-looking view) — so a piece of equipment due in, say, 20 days grades the site `AT_RISK` under the projected view but `COMPLIANT` under the as-of view. All comparisons are made against the logical clock as exact instants (each `next_service_due_at` is `last_service_at` plus exactly `nominal_frequency_days` × 24 hours, and each horizon is exactly 7 or 30 × 24 hours from now, compared instant-to-instant rather than truncated to whole days).

### 3.3. Dispatching and Executing Work Orders

Field work is organized as a `WorkOrder`, created by a `Dispatcher` with the target `site_id` and `equipment_id`, a `service_type` of `SCHEDULED` or `EMERGENCY`, and a service window given by `planned_start` and `planned_end` (both ISO 8601 UTC, with `planned_end` required to be strictly after `planned_start`, else `ERR_VALIDATION`). An optional `contract_id` links the order to a service contract for billing — it may be null for emergency work — and an optional `priority` of `ROUTINE` or `URGENT` defaults to `ROUTINE`. On creation the order is `SCHEDULED`, its `technician_id` is null, and its `actual_hours` is null. At creation the system also fixes the order's billable value: `service_fee_cents` is 12500 for a `GREASE_TRAP` order and 17500 for a `HOOD` order, and `emergency_surcharge_cents` is 8000 when `service_type` is `EMERGENCY` and 0 otherwise.

Creating a work order enforces an equipment service buffer: the new window must be separated by at least 24 hours from the window of every other non-`CANCELLED` work order on the same equipment. Adjacency is forbidden — a gap of less than 24 hours, including touching or overlapping windows, is rejected with `ERR_EQUIPMENT_SERVICE_TOO_SOON`.

A `Dispatcher` routes a `SCHEDULED` order by supplying a target `to_status` of `DISPATCHED` together with a `technician_id`, which advances the order `SCHEDULED → DISPATCHED` and records the assignment. Dispatch runs three guards: the referenced `Equipment` must be `ACTIVE`, or the order is rejected with `ERR_EQUIPMENT_DECOMMISSIONED`; the referenced `Technician` must exist and, when the equipment is a `HOOD`, must have `certification_level` `NFPA96_CERTIFIED`, or the order is rejected with `ERR_TECHNICIAN_NOT_CERTIFIED`; and the assigned technician must have no other `DISPATCHED` or `IN_PROGRESS` order whose window overlaps this one. Overlap is evaluated on the half-open interval from `planned_start` up to `planned_end`, so two windows that merely touch at an endpoint (a gap of exactly zero) do not conflict, whereas any true overlap is rejected with `ERR_TECHNICIAN_SCHEDULE_CONFLICT`. Per §2.11 these are evaluated after the from-state check and in the order safety, then schedule, then equipment availability.

A `Dispatcher` may recall a dispatched order by requesting `to_status` `SCHEDULED`, which moves it `DISPATCHED → SCHEDULED` and clears `technician_id` back to null. A `Dispatcher` may also cancel an order to the terminal `CANCELLED` state from either `SCHEDULED` or `DISPATCHED`; cancelling from `DISPATCHED` clears the assigned `technician_id`.

The assigned technician begins the visit by requesting `to_status` `IN_PROGRESS`, advancing the order `DISPATCHED → IN_PROGRESS`; this is permitted only when the acting technician owns the order (its `technician_id` equals `X-User-ID`), else `ERR_FORBIDDEN`. Completion is a distinct action performed by the owning technician, who reports `actual_hours`. Completion moves the order `IN_PROGRESS → COMPLETED`, but only after the completion-artifact check: a `GREASE_TRAP` order requires an existing `RECORDED` pump-out manifest referencing it, absent which it is rejected with `ERR_MANIFEST_REQUIRED`; a `HOOD` order requires an existing hood certificate referencing it whose `cleanliness_grade` is not `FAILING`, rejected with `ERR_CERTIFICATE_REQUIRED` when there is no certificate and with `ERR_CLEANLINESS_FAILED` when the certificate grade is `FAILING`.

On completion the order's `completed_at` is stamped with the logical-clock now, and the reconciliation cascade of §2.8 fires: the equipment's `last_service_at` is set to that `completed_at` and its `next_service_due_at` recomputed; then the equipment's `service_state` and the owning site's `compliance_status` and `projected_compliance_status` are re-graded; then, if the owning customer is `SUSPENDED` and now has no `NON_COMPLIANT` site, that customer's `account_status` returns to `ACTIVE`.

### 3.4. Pump-Out Manifests and FOG Measurement

After servicing a grease trap, the owning technician files a `PumpOutManifest` against the completed work by supplying its `work_order_id`, the receiving `disposal_facility_name`, that facility's `disposal_facility_permit`, a `hazmat_certified` boolean, the pumped `volume_gallons`, and the measured `fog_percentage`. The referenced work order must belong to `GREASE_TRAP` equipment, or the filing is rejected with `ERR_EQUIPMENT_TYPE_MISMATCH`; and `disposal_facility_permit` must be non-empty and begin with the prefix `FAC-`, or it is rejected with `ERR_DISPOSAL_FACILITY_INVALID`. On acceptance the server mints a `manifest_number` (a unique string beginning with the prefix `MFT-`), sets `status` to `RECORDED`, adds `volume_gallons` to the equipment's `lifetime_pumped_gallons`, and re-grades the owning site's compliance.

Two computed values are set at filing time. The `compliance_flag` applies the 25 percent FOG rule: it is `COMPLIANT` when `fog_percentage` is strictly below 25.0 and `NON_COMPLIANT` when `fog_percentage` is 25.0 or greater — a reading of 24.99 is compliant, 25.00 is a breach. The `disposal_fee_cents` is a marginal tiered charge over the pumped volume plus two possible additions. The gallons cost charges the first 500 gallons at 40 cents per gallon, each gallon above 500 and up to 1500 at 35 cents per gallon, and each gallon above 1500 at 30 cents per gallon. A FOG surcharge is then added only when `fog_percentage` is at least 25.0: it equals 20 percent of the gallons cost, rounded half up to a whole cent (this is the only rounding step in the fee). Finally, when `hazmat_certified` is true, a flat handling fee of 5000 cents is added; when false, nothing is added. The `disposal_fee_cents` is the sum of the gallons cost, the FOG surcharge, and the hazmat flat fee. For example, 2000 gallons at a 25.0 percent reading from a hazmat-certified facility yields a gallons cost of 500×40 + 1000×35 + 500×30 = 70000, a surcharge of 20 percent of 70000 = 14000, and a hazmat fee of 5000, for a total of 89000 cents.

A `RECORDED` manifest may be voided by the owning technician or by a `ComplianceOfficer`; voiding moves its `status` to `VOIDED` and, as a compensating action, subtracts its `volume_gallons` back out of the equipment's `lifetime_pumped_gallons`, conserving that lifetime total across a record-then-void pair. Voiding a manifest that is already `VOIDED` is rejected with `ERR_MANIFEST_ALREADY_VOIDED`.

### 3.5. NFPA 96 Hood Certification

After cleaning an exhaust hood, the technician issues a `HoodCertificate` against the hood work order via its `work_order_id`, recording the NFPA 96 inspection result as a `cleanliness_grade` of `BARE_METAL_CLEAN`, `ACCEPTABLE`, or `FAILING`. The acting technician must hold `certification_level` `NFPA96_CERTIFIED`, else `ERR_TECHNICIAN_NOT_CERTIFIED`; only such technicians may complete hood work and file these certificates. The referenced work order must belong to `HOOD` equipment, or the request is rejected with `ERR_EQUIPMENT_TYPE_MISMATCH`. On issuance the server mints a `sticker_number` (a unique string beginning with the prefix `NFPA96-`), stamps `issued_at` with the logical-clock now, and sets `valid_until` to `issued_at` plus the equipment's `nominal_frequency_days`. As noted in §3.3, a hood order can be completed only when a certificate exists and its grade is not `FAILING`.

A `Technician` is created by an `Admin` with a `full_name` and a `certification_level` of either `BASIC` or `NFPA96_CERTIFIED`, and begins in `status` `AVAILABLE`; the other status value is `INACTIVE`. The technician's `id` is the identity that the `Technician` role authenticates as and against which work-order ownership is checked.

### 3.6. Municipal FOG-Compliance Reporting

A `ComplianceOfficer` prepares a `ComplianceReport` for a site by supplying the `site_id`, the `municipality_code` the report is filed to, and the reporting window `period_start` (inclusive) and `period_end` (exclusive), where `period_end` must be strictly after `period_start`, else `ERR_REPORT_PERIOD_INVALID`. A drafted report starts in `DRAFT` and computes two aggregates over the site's activity: `pumped_gallons_total`, the sum of `volume_gallons` across the site's `RECORDED` manifests whose associated work-order completion falls within the window (at or after `period_start` and before `period_end`), and `included_manifest_count`, the number of such `RECORDED` manifests.

The officer submits a `DRAFT` report, advancing it `DRAFT → SUBMITTED`, at which point `pumped_gallons_total` and `included_manifest_count` are frozen. Submission is blocked when the site's `compliance_status` is `NON_COMPLIANT`, in which case it is rejected with `ERR_INVALID_STATE` — a site cannot file to its municipality while out of compliance.

The officer records the municipality's decision on a `SUBMITTED` report by supplying a `decision` of `ACCEPTED` or `REJECTED`, optionally with a `decision_note`. Recording `ACCEPTED` moves the report `SUBMITTED → ACCEPTED` (a terminal state) and cascades: the site's `last_certified_at` is set to the logical-clock now and its `compliance_status` is recomputed, and then, if the owning customer is `SUSPENDED` and now has no `NON_COMPLIANT` site, that customer's `account_status` returns to `ACTIVE`. Recording `REJECTED` moves the report `SUBMITTED → REJECTED`. A `REJECTED` report can be reopened for revision, moving it `REJECTED → DRAFT`, from which it can be corrected and re-submitted — a cyclic revision loop. A `DRAFT` report may instead be cancelled by requesting `to_status` `CANCELLED`, moving it to the terminal `CANCELLED` state.

### 3.7. Recurring Billing and Invoicing

A `BillingClerk` raises an `Invoice` for a customer by supplying the `customer_id`, the billing window `period_start` (inclusive) and `period_end` (exclusive) — with `period_end` strictly after `period_start`, else `ERR_REPORT_PERIOD_INVALID` — an optional `contract_id` supplying the base-rate and tax terms, and the `expected_customer_version` required by the optimistic-concurrency rule of §2.7. A new invoice is created in `DRAFT`, computes a `provisional_total_cents`, increments the customer's `version` by 1, and auto-voids any prior `DRAFT` invoice for the same customer and period.

An invoice values a set of billable **lines**. There is a base-rate line equal to the contract's `base_rate_cents`, included only when the contract is `ACTIVE` and its `base_rate_cents` is greater than zero. There is then one line per included work order — a work order is selected solely by its owning customer (via its site) together with the period-and-status rules below, independent of the invoice's `contract_id` — each valued at that order's `service_fee_cents` plus its `emergency_surcharge_cents`. The `subtotal_cents` is the sum of all line amounts. Tax is computed per line and then summed: for each line, the line tax is the line amount multiplied by the tax rate (the contract's `tax_rate_bps` divided by 10000), rounded half up to a whole cent; `tax_cents` is the sum of these per-line rounded taxes — each line is rounded first, then the rounded taxes are summed, never summed then rounded. The `total_amount_cents` is `subtotal_cents` plus `tax_cents`. For instance, two work-order lines of 12500 each at a `tax_rate_bps` of 825 produce a per-line tax of round-half-up(1031.25) = 1031 each, so `tax_cents` is 2062, `subtotal_cents` is 25000, and `total_amount_cents` is 27062 — whereas summing before rounding would have yielded 2063.

The two computed valuations differ in which work orders they include. The provisional valuation, stored in `provisional_total_cents` at draft creation, is forward-looking: it counts work orders whose status is `SCHEDULED`, `DISPATCHED`, `IN_PROGRESS`, or `COMPLETED` and whose `planned_start` falls at or after `period_start` and before `period_end`. The final valuation, frozen into `subtotal_cents`, `tax_cents`, and `total_amount_cents` at issue, is chronological: it counts only work orders whose status is `COMPLETED` and whose `completed_at` falls at or after `period_start` and before `period_end`.

Issuing a `DRAFT` invoice moves it `DRAFT → ISSUED` and freezes the final amount. Issue is blocked in three ways, evaluated per the §2.11 order: the invoice must have at least one billable line — with no completed work and no positive base rate there is nothing to bill, and the issue is rejected with `ERR_NO_BILLABLE_ACTIVITY`; the customer must not be `CLOSED`, else `ERR_CUSTOMER_CLOSED`; and the customer's `outstanding_balance_cents` plus this invoice's `total_amount_cents` must not exceed the customer's `credit_limit_cents`, else `ERR_CREDIT_LIMIT_EXCEEDED`. On success, `total_amount_cents` is added to `outstanding_balance_cents` and the customer's `version` increments.

A `BillingClerk` records payment on an `ISSUED` invoice by supplying `amount_cents`, which must exactly equal the invoice's `total_amount_cents`, else `ERR_VALIDATION`. Recording payment moves the invoice `ISSUED → PAID` (terminal), sets `amount_paid_cents` to the paid amount, subtracts `total_amount_cents` from the customer's `outstanding_balance_cents`, and increments the customer's `version`. Alternatively, an `ISSUED` invoice may be voided, moving it `ISSUED → VOID` (terminal) and subtracting `total_amount_cents` from `outstanding_balance_cents` to exactly reverse the issue debit, again incrementing the customer's `version`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that fetch, list, or modify an existing resource — including all state transitions and the logical-clock control — return `200 OK`. Every request is subject to the authentication, authorization, and validation rules of §2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customers` | Create a customer account | Admin |
| GET | `/customers/{id}` | Fetch a customer (read current version for OCC) | Admin, Dispatcher, Technician, ComplianceOfficer, BillingClerk |
| GET | `/customers/{id}/sites` | List sites owned by a customer | Admin, Dispatcher, Technician, ComplianceOfficer, BillingClerk |
| GET | `/customers/{id}/contracts` | List service contracts owned by a customer | Admin, BillingClerk |
| POST | `/customers/{id}/close` | Close a customer account (requires zero outstanding balance) | Admin |
| POST | `/sites` | Create a site under a customer | Admin |
| GET | `/sites/{id}` | Fetch a site (includes computed compliance) | Admin, Dispatcher, Technician, ComplianceOfficer, BillingClerk |
| GET | `/sites/{id}/equipment` | List equipment at a site | Admin, Dispatcher, Technician, ComplianceOfficer, BillingClerk |
| GET | `/sites/{id}/compliance-reports` | List compliance reports for a site | Admin, ComplianceOfficer |
| POST | `/equipment` | Create equipment at a site | Admin |
| GET | `/equipment/{id}` | Fetch equipment | Admin, Dispatcher, Technician, ComplianceOfficer, BillingClerk |
| GET | `/equipment/{id}/work-orders` | List work orders for a piece of equipment | Admin, Dispatcher, Technician |
| POST | `/equipment/{id}/decommission` | Decommission equipment (no open work orders) | Admin |
| POST | `/service-contracts` | Create a service contract | Admin |
| GET | `/service-contracts/{id}` | Fetch a service contract | Admin, BillingClerk |
| POST | `/service-contracts/{id}/transition` | Transition a contract (ACTIVE / SUSPENDED / CANCELLED) | Admin |
| POST | `/technicians` | Create a technician | Admin |
| GET | `/technicians/{id}` | Fetch a technician | Admin, Dispatcher, Technician |
| POST | `/work-orders` | Create a work order (enforces 24h equipment buffer) | Dispatcher |
| GET | `/work-orders/{id}` | Fetch a work order | Admin, Dispatcher, Technician, ComplianceOfficer, BillingClerk |
| GET | `/work-orders` | List work orders (filterable) | Admin, Dispatcher, Technician, BillingClerk |
| GET | `/work-orders/{id}/pump-out-manifests` | List manifests for a work order | Admin, Dispatcher, Technician, ComplianceOfficer |
| GET | `/work-orders/{id}/hood-certificates` | List certificates for a work order | Admin, Dispatcher, Technician, ComplianceOfficer |
| POST | `/work-orders/{id}/transition` | Transition a work order (dispatch / recall / start / cancel) | Dispatcher, Technician |
| POST | `/work-orders/{id}/complete` | Complete an in-progress work order | Technician |
| POST | `/pump-out-manifests` | File a pump-out manifest against a grease-trap order | Technician |
| POST | `/pump-out-manifests/{id}/void` | Void a recorded manifest | Technician, ComplianceOfficer |
| POST | `/hood-certificates` | Issue an NFPA 96 hood certificate | Technician |
| POST | `/compliance-reports` | Draft a FOG-compliance report | ComplianceOfficer |
| POST | `/compliance-reports/{id}/submit` | Submit a draft report to the municipality | ComplianceOfficer |
| POST | `/compliance-reports/{id}/record-decision` | Record the municipal decision (ACCEPTED / REJECTED) | ComplianceOfficer |
| POST | `/compliance-reports/{id}/revise` | Return a rejected report to draft | ComplianceOfficer |
| POST | `/compliance-reports/{id}/transition` | Cancel a draft report | ComplianceOfficer |
| POST | `/invoices` | Create a draft invoice (OCC on customer version) | BillingClerk |
| GET | `/invoices/{id}` | Fetch an invoice | Admin, BillingClerk |
| GET | `/invoices` | List invoices (filterable) | Admin, BillingClerk |
| POST | `/invoices/{id}/issue` | Issue a draft invoice (freezes amount, debits balance) | BillingClerk |
| POST | `/invoices/{id}/record-payment` | Record full payment on an issued invoice | BillingClerk |
| POST | `/invoices/{id}/void` | Void an issued invoice (reverses the debit) | BillingClerk |
| POST | `/_clock/set_current_utc` | Set the logical clock | Admin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_VERSION_REQUIRED` | 400 |
| `ERR_EQUIPMENT_DECOMMISSIONED` | 409 |
| `ERR_CUSTOMER_CLOSED` | 409 |
| `ERR_TECHNICIAN_NOT_CERTIFIED` | 422 |
| `ERR_CLEANLINESS_FAILED` | 422 |
| `ERR_TECHNICIAN_SCHEDULE_CONFLICT` | 409 |
| `ERR_EQUIPMENT_SERVICE_TOO_SOON` | 409 |
| `ERR_MANIFEST_REQUIRED` | 422 |
| `ERR_CERTIFICATE_REQUIRED` | 422 |
| `ERR_EQUIPMENT_TYPE_MISMATCH` | 422 |
| `ERR_DISPOSAL_FACILITY_INVALID` | 422 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 |
| `ERR_NO_BILLABLE_ACTIVITY` | 422 |
| `ERR_MANIFEST_ALREADY_VOIDED` | 409 |
| `ERR_REPORT_PERIOD_INVALID` | 422 |
| `ERR_PAGINATION_INVALID` | 400 |
