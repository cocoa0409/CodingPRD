# Broker Price Opinion Valuation API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Broker Price Opinion & Valuation Services API, a vendor-side platform that manages the full lifecycle of real-estate valuation work — from the moment a lending client places an order for a broker price opinion or a licensed appraisal, through dispatch to a state-licensed broker, comparable selection and photo evidence collection, quality control review and revision cycles, and finally payout settlement and volume forecasting.

The business problem this system solves is twofold. On the compliance side, U.S. states differ sharply in whether a non-appraisal BPO product may be issued at all, and many states require a full appraisal license whenever an interior inspection is performed; a vendor that dispatches the wrong license kind into the wrong state exposes itself and its clients to regulatory action, so licensing, geography, and inspection-level rules are enforced as hard preconditions rather than advisory checks. On the operations side, turnaround time, report quality, and revision behavior are the three axes on which clients score their vendors, so the system maintains a continuously recomputed broker composite score, enforces per-client SLA clocks measured in hours, and retains a contractual late-penalty stream (expressed in basis points per calendar day) that nets against broker payout at completion.

The API is mounted under the `/bpo` prefix and is consumed by eight distinct operator roles spanning the client's own administrators, the vendor's dispatch desk, the broker panel, QC review, billing, compliance, and platform administration. Every mutating operation is designed to be auditable: state transitions are explicit, money is tracked in integer cents, and a logical-clock test-driving capability allows every time-dependent rule (SLA due timestamps, lateness, revision windows, forecast windows, composite-score windows) to be exercised deterministically.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. A request missing either header, or carrying an empty value for either, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are present but the named role is not permitted to invoke the target endpoint, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly eight roles, spelled as follows: `PlatformAdmin`, `ClientAdmin`, `OperationsManager`, `DispatchCoordinator`, `Broker`, `QCReviewer`, `BillingClerk`, and `ComplianceOfficer`.

Two of these roles are entity-backed, meaning `X-User-ID` is not just a label but the primary key of a persisted resource, and ownership checks compare it directly to foreign keys on other resources:

- When `X-User-Role` is `ClientAdmin`, `X-User-ID` is the `id` of the acting `ClientAccount`; ownership checks on any resource that references a `ClientAccount` compare the resource's foreign-key field to `X-User-ID`.
- When `X-User-Role` is `Broker`, `X-User-ID` is the `id` of the acting `Broker`; ownership checks on any resource that references a `Broker` compare the resource's foreign-key field to `X-User-ID`. Broker-scoped actions such as accepting an assignment, declining it, submitting a report, uploading photo evidence, or resubmitting a revision all enforce this ownership check, and a mismatch is rejected with `ERR_FORBIDDEN` (HTTP 403).

The remaining six roles are opaque: `PlatformAdmin`, `OperationsManager`, `DispatchCoordinator`, `QCReviewer`, `BillingClerk`, and `ComplianceOfficer`. For each of these, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `reviewer_id` on a `QCReview` row where a verdict transition writes it — but does not compare it to any entity's `id`. One important exception to that non-comparison rule exists for segregation of duties: when a `QCReviewer` records a verdict, the reviewer's opaque `X-User-ID` must not equal the opaque identity derived from the assigned broker, a rule detailed in §2.8 and §3.5.

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

Requests to an undefined path, or to a defined path under an unsupported method, are rejected in this same envelope with `ERR_NOT_FOUND` (HTTP 404). An unexpected internal failure is surfaced in the same envelope with `ERR_INTERNAL` (HTTP 500).

---

### 2.3. Pagination

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0. A non-integer value for either parameter, a `limit` outside 1 to 100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order; resources sharing an identical creation timestamp are ordered by insertion (creation) sequence.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true if and only if `offset` + `limit` is strictly less than `total_count`.

### 2.4. Common Resource Properties

Most resources in the system carry a standard set of system-managed fields:

- `id` (string): A unique, server-generated identifier for the resource, formatted as a UUID with no type prefix.
- `created_at` (string): An ISO 8601 timestamp in UTC with three fractional digits, indicating when the resource was first created.
- `updated_at` (string): An ISO 8601 UTC timestamp indicating when the resource was last modified. This field is refreshed upon any change to the resource.
- `version` (integer): A system-managed integer that increments by exactly 1 with every modification to the resource, including every state transition. This field underpins optimistic concurrency control.

Three resource types deliberately deviate from this convention. `PhotoEvidence` rows, `QCRevisionRequest` rows, and `VolumeForecast` rows carry only `id` and `created_at`; both `updated_at` and `version` are absent on these three types, because each is an append-only evidentiary or analytical record rather than a mutable workflow entity.

### 2.5. Monetary Values, Units, and Precision

All monetary values within the system are represented as integer cents — never as floating-point dollars. The gross fee agreed with the client on an order, the sale price of a comparable property, the signed adjustment applied to a comparable, and every fee line amount are all integer-cent fields. When a calculation produces a fractional cent result, the result is rounded half-up to the nearest whole cent at the point the value is finalized.

Two non-monetary quantities have their own precision rules. Comparable distances, expressed in miles, are stored as numbers rounded half-up to two decimal places. The broker composite score is a number held to exactly two decimal places, rounded half-up, and clamped to the inclusive range 0 to 100. Timestamps are ISO 8601 UTC; SLA due timestamps are computed at second precision with no rounding.

### 2.6. Optimistic Concurrency Control

The system uses optimistic concurrency control on exactly two write operations, and on no others. Endpoints not listed here do not accept a version field at all.

First, dispatching a valuation order requires the request body to carry `expected_order_version`, set to the value of the order's `version` the client last observed. If the order's current `version` does not match — for example because another dispatcher legitimately dispatched the same order moments earlier, which itself increments `version` — the dispatch is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on a stale view of the order.

Second, approving a payout batch requires the request body to carry `expected_batch_version`, set to the value of the batch's `version` the clerk last observed. If the batch's current `version` has advanced since that observation, the approval is rejected with `ERR_STALE_VERSION` (HTTP 412). This is the serialization point that prevents two stale views from double-snapshotting the batch total.

On both endpoints, an `expected_*_version` field that is missing or not an integer is rejected with `ERR_INVALID_REQUEST` (HTTP 400), raised at the same point in the validation priority order as the version match itself (priority 28).

### 2.7. Hierarchical Validation and Cascading Consistency

For any request whose URL contains nested resource identifiers, the system validates existence strictly left-to-right along the path — client, order, QC review, revision, broker, batch, or forecast as applicable. The request is rejected immediately with `ERR_NOT_FOUND` (HTTP 404) at the first path segment whose identifier does not resolve to an existing resource, before any later segment is examined. The same `ERR_NOT_FOUND` rejection applies when a body-referenced foreign key — such as `property_id`, `source_property_id`, or `broker_id` — does not resolve to an existing resource; body references are checked after path references.

State transitions on a parent entity frequently cascade to children and to cross-aggregate counters. When a broker is suspended, every order assigned to that broker that is still in `DISPATCHED` reverts to `READY_FOR_DISPATCH` and has its `assigned_broker_id` and `sla_due_at` cleared, while orders already in `IN_PROGRESS`, `REPORT_SUBMITTED`, `QC_REVIEW`, or `REVISION_REQUESTED` remain in place but the broker becomes ineligible for new dispatch. When a broker is terminated, every `BrokerLicense` row belonging to that broker transitions to `REVOKED`. When an order is cancelled, all of its `DRAFT` comparable rows and `DRAFT` fee line rows are cancelled with it, each taking `status` `CANCELLED`. Each of these mutations independently refreshes the affected entity's `updated_at` and increments its `version` by 1.

### 2.8. Segregation of Duties in Quality Control

The quality control workflow enforces a strict segregation-of-duties rule: the person who performed the valuation work must never be the person who renders a verdict on it. When a `QCReviewer` records a verdict on an order, the reviewer's `X-User-ID` (an opaque identifier) is compared against the opaque identity derived from the order's assigned broker; that derived identity comprises the broker's `id` and the broker's `broker_code`, and a reviewer `X-User-ID` equal to either one triggers the rule. If the two coincide, the verdict is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The attempt is not silently dropped: the system records the attempt on the resulting state by marking the review's read-only `is_segregation_violation` flag true for audit purposes — true if and only if the reviewer's opaque id equals the assigned broker's derived opaque id — even though the verdict itself is refused.

### 2.9. Validation Priority Order

When multiple validation rules could reject the same request, the system evaluates them in a fixed priority order so that the surfaced error is deterministic. The order, from first-evaluated to last-evaluated, is:

1. Authentication: presence and non-emptiness of `X-User-Role` and `X-User-ID` (`ERR_UNAUTHENTICATED`).
2. Authorization: the role is permitted to invoke this endpoint (`ERR_UNAUTHORIZED`).
3. Path existence: path-referenced resources exist, validated left-to-right (`ERR_NOT_FOUND`).
4. Body existence: body-referenced foreign-key resources exist (`ERR_NOT_FOUND`).
5. State legality: the target resource is in a state from which this transition is permitted (`ERR_INVALID_STATE`).
6. Segregation of duties on QC verdicts (`ERR_SEGREGATION_OF_DUTIES`).
7. State-level BPO licensing compatibility — `bpo_permitted`, `appraisal_required_for_interior`, and `license_kind` coverage (`ERR_LICENSE_NOT_VALID_FOR_STATE`).
8. Inspection-level versus product-kind compatibility at submit (`ERR_INTERIOR_REQUIRES_APPRAISAL`).
9. BPO product permissibility in the subject property's state (`ERR_BPO_NOT_PERMITTED`).
10. Comparable-count floor at report submission (`ERR_INSUFFICIENT_COMPARABLES`).
11. Photo-evidence minimum at report submission (`ERR_INSUFFICIENT_PHOTOS`).
12. Fee reconciliation at report submission (`ERR_FEE_RECONCILE_MISMATCH`).
13. Comparable adjustment cap (`ERR_ADJUSTMENT_EXCEEDS_CAP`).
14. Comparable distance floor (`ERR_COMPARABLE_RADIUS_VIOLATION`).
15. Broker capacity at dispatch (`ERR_BROKER_CAPACITY_FULL`).
16. Order not already assigned at dispatch (`ERR_ORDER_ALREADY_DISPATCHED`).
17. No other open QC cycle on the order when opening one (`ERR_QC_CYCLE_ALREADY_OPEN`).
18. Verdict targets the latest QC cycle (`ERR_QC_CYCLE_STALE`).
19. Revision request is open at resubmission (`ERR_REVISION_NOT_OPEN`).
20. No open revision request remains at completion (`ERR_OPEN_REVISION_EXISTS`).
21. Payout batch is non-empty at approval (`ERR_EMPTY_BATCH`).
22. All contributing orders are completed at disbursement (`ERR_ORDER_NOT_COMPLETED`).
23. Broker has no open orders at termination (`ERR_OPEN_ORDERS_EXIST`).
24. Broker has no overdue open revision at reinstatement (`ERR_OVERDUE_REVISION_BLOCKS_REINSTATE`).
25. Broker holds at least one active license at activation (`ERR_NO_ACTIVE_LICENSE`).
26. Subject property is registered (`ERR_PROPERTY_NOT_REGISTERED`).
27. State regulation is active for the subject's state (`ERR_STATE_REGULATION_SUSPENDED`).
28. Optimistic concurrency version match (`ERR_STALE_VERSION`).
29. Request body fields conform to declared types, ranges, enum sets, and string patterns (`ERR_INVALID_REQUEST`); a request body that is not a JSON object at all is rejected the same way.
30. Ownership of entity-backed resources (`ERR_FORBIDDEN`).

One check not itemized above is the dispatch-time requirement that the target broker be `ACTIVE` (`ERR_BROKER_NOT_ACTIVE`): it is evaluated immediately after state legality (priority 5) and before state-level licensing compatibility (priority 7).

So, for example, a QC verdict attempted by the assigned broker on a stale cycle surfaces `ERR_SEGREGATION_OF_DUTIES` (priority 6), not the stale-cycle error (priority 18), because segregation is evaluated first; and a dispatch request carrying a stale version for an order whose target broker is over capacity surfaces `ERR_BROKER_CAPACITY_FULL` (priority 15) before the version check (priority 28) is reached.

### 2.10. Logical Clock

All time-dependent behavior in the system — SLA due timestamps, lateness computation, late-fee accrual, revision due windows, forecast windows, and the composite-score rolling window — reads from a single server-side logical UTC clock. At startup the logical clock reads 2026-08-01T00:00:00Z. A `PlatformAdmin` may advance the logical clock to a supplied `to_iso8601` instant through an admin-only test-driving capability; the clock may be set to any supplied instant, forward or backward, and the endpoint returns `200 OK` with an empty `data` object. Every calculation named above must honor this logical clock rather than the host wall clock.

## 3. Business Logic & Workflows

### 3.1. Client Onboarding and Commercial Terms

A `PlatformAdmin` registers each lending client as a `ClientAccount`, supplying a `client_code` that is globally unique and matches the pattern of 3 to 12 uppercase alphanumeric characters — registering a duplicate `client_code` is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — plus a human-readable `display_name`. The commercial heart of the account is the service-level agreement: `sla_hours_standard` is the standard turnaround commitment in whole hours and must be at least 24 and at most 240, while `sla_hours_rush` is the rush turnaround commitment in whole hours and must be at least 4 and strictly less than `sla_hours_standard`. Three optional fields tune the financial and scorecard relationship: `late_penalty_bps_per_day` is the late fee charged back to the vendor, expressed in basis points of the order fee per calendar day past SLA, ranging from 0 to 2000 and defaulting to 250 when omitted; `scorecard_weight_turnaround`, `scorecard_weight_quality`, and `scorecard_weight_revision` are the weights (each between 0 and 1) applied to the turnaround, quality, and revision-rate components of the broker scorecard for this client's orders, defaulting to 0.5, 0.3, and 0.2 respectively. A client account's `status` begins as `ACTIVE` and may later move to `SUSPENDED` or `TERMINATED`.

A client account may be listed (with an optional `status` query filter) and retrieved by `PlatformAdmin`, `OperationsManager`, and `BillingClerk`; a `ClientAdmin` may retrieve only its own account record, identified by the `X-User-ID` matching the account's `id`, with any other account rejected `ERR_FORBIDDEN` (HTTP 403).

### 3.2. State Regulations and Property Registration

Valuation law varies by state, and the system models that variation explicitly. A `ComplianceOfficer` maintains a `StateRegulation` row per state, keyed by a unique `state_code` of two uppercase letters. Each row records whether non-appraisal BPO reports may be issued in that state via `bpo_permitted`, and whether interior-inspection orders must be performed by an appraisal-licensed broker via `appraisal_required_for_interior`. Two optional distance parameters govern comparable selection geography: `min_driveby_radius_miles` is the minimum radius in miles within which a comparable must sit to count toward the drive-by minimum, defaulting to 1.0, and `min_interior_radius_miles` is the corresponding minimum radius for interior-inspection comparables, defaulting to 0.5. A regulation row's `status` is `ACTIVE` by default and may be moved to `SUSPENDED`, which freezes new order activity for that state as described below. Posting a regulation for a `state_code` that already has a row replaces that row in place under its existing `id`: `bpo_permitted` and `appraisal_required_for_interior` are overwritten, either radius field omitted from the request keeps its prior value, and `status` is reset to `ACTIVE`; the replace returns `201 Created` with the updated row. Regulations are readable by `ComplianceOfficer`, `PlatformAdmin`, `OperationsManager`, and `DispatchCoordinator`, and the list endpoint supports an optional `status` query filter.

Properties are the subjects of valuation. Either an `OperationsManager` or a `ClientAdmin` registers a `Property` with its `street_address`, `city`, a two-uppercase-letter `state_code`, and `postal_code`, together with physical attributes: `living_area_sqft` (gross living area in square feet, greater than 0), `lot_area_sqft` (lot area in square feet, greater than 0), `year_built` (between 1700 and 2100 inclusive), and `property_type`, one of `SINGLE_FAMILY`, `CONDO`, `TOWNHOME`, `MULTI_FAMILY`, or `MANUFACTURED`. A property's `status` begins as `REGISTERED` and may later be `ARCHIVED`. Properties are listable with optional filters on `state_code` and `status`, and are readable by `OperationsManager`, `ClientAdmin`, `DispatchCoordinator`, and `Broker`. Anyone auditing reuse can also list, for a given property, every comparable row across all orders that references that property as its source — a reverse lookup available to `OperationsManager`, `DispatchCoordinator`, `Broker`, `QCReviewer`, and `PlatformAdmin`, with an optional `status` query filter.

### 3.3. Broker Onboarding, Licensing, and the Composite Score

The broker panel is the vendor's delivery workforce, and its membership is gated by compliance. A `ComplianceOfficer` onboards a `Broker` with a globally unique `broker_code` (3 to 12 uppercase alphanumeric characters; a duplicate `broker_code` is rejected with `ERR_INVALID_REQUEST`, HTTP 400), the broker's legal `full_name`, a contact `email` (required, but uniqueness is not enforced — duplicate emails are accepted), and `max_concurrent_orders`, the maximum number of orders the broker may hold in `DISPATCHED` or `IN_PROGRESS`-family states at once, ranging from 1 to 50. A newly onboarded broker starts in `PENDING_ONBOARDING` status with a `composite_score` of 100.00. The broker list endpoint supports an optional `status` query filter, and a caller in the `Broker` role may retrieve only its own broker record — and likewise only its own license list and photo list — with any other broker's resources rejected `ERR_FORBIDDEN` (HTTP 403).

Licenses are attached to the broker per state. Each `BrokerLicense` row records the `state_code` it covers, the `license_kind` — either `BPO` or `APPRAISAL`, describing the kinds of valuation the broker may perform in that state — the issuing body's `license_number`, and the license `expires_on` timestamp as an ISO 8601 UTC date-time. A license's `status` begins `ACTIVE` and may become `EXPIRED` or `REVOKED`. Licenses are listed per broker with an optional `status` query filter, and a broker's uploaded photo evidence is likewise listable by broker, with an optional `photo_kind` filter, to `ComplianceOfficer`, `PlatformAdmin`, `OperationsManager`, `DispatchCoordinator`, `Broker`, and `QCReviewer`.

Activation is the first lifecycle gate: moving a broker from `PENDING_ONBOARDING` to `ACTIVE` requires that the broker hold at least one `BrokerLicense` row whose `status` is `ACTIVE` and whose `expires_on` is strictly in the future; otherwise the activation is rejected with `ERR_NO_ACTIVE_LICENSE`.

Every broker carries a read-only `composite_score`, a number between 0 and 100 recomputed on every QC verdict, every order completion, every revision resolved late, and every broker decline. The score blends three components measured over a rolling window of the trailing 90 days — inclusive of both endpoints, the instant exactly 90 days before now and now itself. Window membership is determined by each record's own activity timestamp: completed orders by `completed_at`, QC verdicts by the review's `reviewed_at`, revision requests by their `created_at`, and declines by the instant the decline was recorded. The turnaround component is 1 minus the ratio of late-completed orders to total completed orders in the window, with the ratio capped at 1 and an empty denominator treated as 1. The quality component is the mean verdict value across QC verdicts in the window, where an `APPROVE` verdict counts 1.0, a `REVISE` counts 0.5, and a `REJECT` counts 0.0, and an empty verdict set yields a quality component of 1. The revision component is 1 minus the ratio of revision requests in the window to completed orders in the window, again capped at 1 with an empty denominator treated as 1. Each component is weighted: for the global view used in suspension decisions, components are pooled across all clients and the weights are the order-count-weighted averages of each contributing client's `scorecard_weight_turnaround`, `scorecard_weight_quality`, and `scorecard_weight_revision`, where a client contributes once per order of this broker that shows in-window scoring activity — an in-window completion, an in-window verdict, or an in-window revision request — and where the default weights 0.5, 0.3, and 0.2 apply when no order contributes. Only this global pooled view is computed and stored as the broker's `composite_score`; no separate per-client scorecard view is computed or exposed. The weighted sum is multiplied by 100, each decline in the window then subtracts 1.0 point after weighting, and the result is rounded half-up to two decimal places and clamped to the inclusive range 0 to 100.

Suspension and termination close the loop. A `ComplianceOfficer` may suspend any `ACTIVE` broker — the API enforces no precondition beyond `ACTIVE` status: the composite-score-below-50.0 criterion is a business guideline for when to suspend, not an enforced gate, and no override flag or score check is performed; suspension moves the broker to `SUSPENDED`, reverts every order assigned to that broker that is still in `DISPATCHED` back to `READY_FOR_DISPATCH` with its `assigned_broker_id` and `sla_due_at` cleared, and leaves orders already in `IN_PROGRESS`, `REPORT_SUBMITTED`, `QC_REVIEW`, or `REVISION_REQUESTED` in place while blocking any new dispatch to that broker. A suspended broker may be reinstated to `ACTIVE`, but only if no order assigned to the broker sits in `REVISION_REQUESTED` with a revision request whose `outcome` is still `OPEN` and whose `due_at` has already passed; such an overdue open revision blocks reinstatement with `ERR_OVERDUE_REVISION_BLOCKS_REINSTATE`. Termination, from either `ACTIVE` or `SUSPENDED`, is allowed only when the broker has no order in `DISPATCHED`, `IN_PROGRESS`, `REPORT_SUBMITTED`, `QC_REVIEW`, `REVISION_REQUESTED`, or `ACCEPTED` — open work blocks termination with `ERR_OPEN_ORDERS_EXIST` — and on termination every `BrokerLicense` row for the broker transitions to `REVOKED`.

### 3.4. Order Intake, Compliance Submission, and Dispatch

An order is born when a `ClientAdmin` or `OperationsManager` creates a `ValuationOrder` with a payload containing the `property_id` of the subject property, the `order_kind` (either `BPO` or `APPRAISAL`, the valuation product ordered), the `inspection_level` (`DRIVE_BY` or `INTERIOR`), an optional `priority` (`STANDARD` or `RUSH`, defaulting to `STANDARD`), the `agreed_fee_cents` gross fee negotiated with the client as integer cents between 100 and 1,000,000 inclusive, and the `client_id` of the ordering account. A `ClientAdmin` may create orders only for its own account — the payload's `client_id` must equal `X-User-ID`, else `ERR_FORBIDDEN` — while an `OperationsManager` may create for any account. The order begins in `INTAKE` with `payment_status` `UNBILLED`, a `revision_count` of 0, and `assigned_broker_id` empty. Even at creation, the subject property must be in `REGISTERED` status — rejection is `ERR_PROPERTY_NOT_REGISTERED` — and the state regulation row for the property's state must exist and be `ACTIVE`; a missing or non-`ACTIVE` regulation row alike is rejected with `ERR_STATE_REGULATION_SUSPENDED`. Both checks repeat at submission.

Moving from `INTAKE` to `READY_FOR_DISPATCH` is the compliance gateway, performed by a `ClientAdmin` submitting an order of its own account — the caller's `X-User-ID` must equal the order's `client_id`, else `ERR_FORBIDDEN`, and this ownership check is evaluated last per the fixed priority order. Submission applies the product-legality rules before re-verifying the registration checks: first, if the `inspection_level` is `INTERIOR` while the state's `appraisal_required_for_interior` is true, the `order_kind` must be `APPRAISAL`, else the submission fails with `ERR_INTERIOR_REQUIRES_APPRAISAL`; second, if `order_kind` is `BPO`, the state's `bpo_permitted` must be true or the submission fails with `ERR_BPO_NOT_PERMITTED`. Only then are the property-`REGISTERED` and regulation-`ACTIVE` checks re-verified, followed by the fee floor: the `agreed_fee_cents` must be at least 100, with violations rejected as `ERR_INVALID_REQUEST`. A successful submission also validates the comparable-count floor against state minimums as a no-op placeholder — the real enforcement re-occurs at report submission — and increments the order's `version`.

Dispatch is the `DispatchCoordinator`'s exclusive act, transitioning the order from `READY_FOR_DISPATCH` to `DISPATCHED` with a payload containing the chosen `broker_id` and the OCC field `expected_order_version`. The dispatch validates, in the system's fixed priority order: the order must be in `READY_FOR_DISPATCH` (`ERR_INVALID_STATE`); the selected broker's `status` must be `ACTIVE` (`ERR_BROKER_NOT_ACTIVE`); the broker must hold an `ACTIVE` license for the subject property's state whose `license_kind` covers the `order_kind` — an `APPRAISAL` license covers both `APPRAISAL` and `BPO` orders, while a `BPO` license covers only `BPO` orders — and whose `expires_on` is strictly in the future (`ERR_LICENSE_NOT_VALID_FOR_STATE`); the broker's count of orders in `DISPATCHED`, `IN_PROGRESS`, `REPORT_SUBMITTED`, `QC_REVIEW`, or `REVISION_REQUESTED` must be strictly below their `max_concurrent_orders` (`ERR_BROKER_CAPACITY_FULL`); the order must not already carry an `assigned_broker_id` (`ERR_ORDER_ALREADY_DISPATCHED`); and `expected_order_version` must match the order's current `version` (`ERR_STALE_VERSION`). On success the order's `assigned_broker_id` is set to the chosen broker, the SLA clock starts: `sla_due_at` is set to the dispatch instant plus `sla_hours_standard` hours if the `priority` is `STANDARD`, or plus `sla_hours_rush` hours if the `priority` is `RUSH`, both drawn from the owning `ClientAccount`; and the broker's open-order count is incremented. The order's `version` increments.

The assigned broker then faces a binary choice. Accepting the order — allowed only when the caller's `X-User-ID` equals the order's `assigned_broker_id`, else `ERR_FORBIDDEN`, and only while the order is `DISPATCHED`, else `ERR_INVALID_STATE` — moves it to `IN_PROGRESS` and starts the inspection clock used for SLA scoring. Declining returns the order to `READY_FOR_DISPATCH`: the `assigned_broker_id` and `sla_due_at` are cleared, the broker's open-order count is decremented, and the broker's decline count is incremented, feeding the decline penalty in the composite score.

A client may cancel an order at any of three points — `INTAKE`, `READY_FOR_DISPATCH`, or `DISPATCHED` — through a `ClientAdmin` cancellation, again restricted to the owning account (`X-User-ID` must equal the order's `client_id`, else `ERR_FORBIDDEN`); an order in any other state rejects the attempt with `ERR_INVALID_STATE`. Cancellation moves the order to `CANCELLED` and cancels every `DRAFT` comparable and every `DRAFT` fee line on it, each taking `status` `CANCELLED`. Cancelling from `DISPATCHED` additionally clears the `assigned_broker_id` and `sla_due_at` and decrements the broker's open-order count, but deliberately does not increment the broker's decline count — a cancellation is not a decline.

### 3.5. Field Work: Comparables, Photo Evidence, and Fee Lines

While an order is in progress, the assigned broker assembles the evidentiary record. Field work — adding comparables, uploading photos, and adding fee lines — is permitted in any non-terminal order state (anything but `COMPLETED`, `CANCELLED`, or `REJECTED`); attempts on a terminal order are rejected with `ERR_INVALID_STATE`. Comparables are added to the order by a `Broker` or `OperationsManager` with a payload containing the `source_property_id` of the comparable property, its `sale_price_cents` (integer cents, greater than 0), its `sale_date`, the `distance_miles` from the subject property (between 0.01 and 100.00, rounded half-up to two decimals), and the signed `adjustment_cents` applied to align the comparable with the subject. Comparable creation, selection, and rejection enforce no assigned-broker ownership check: any caller in an authorized role may perform them. Each comparable row starts in `DRAFT` status, and its read-only `adjusted_value_cents` is always the sum of `sale_price_cents` and `adjustment_cents`.

Every comparable, photo, fee line, QC review, and revision request row carries an `order_id` tying it back to its parent order, set by the system from the order under which the row was created.

Two hard constraints guard comparable integrity, enforced both at creation and again when a comparable is marked `SELECTED`. First, the adjustment cap: the absolute value of `adjustment_cents` must not exceed 25 percent of `sale_price_cents`, with the cap itself computed in integer cents rounded half-up; a breach is rejected with `ERR_ADJUSTMENT_EXCEEDS_CAP`. Second, the adjusted value must remain positive — if `sale_price_cents` plus `adjustment_cents` is zero or less, the rejection is `ERR_ADJUSTMENT_NONPOSITIVE`. Geography applies too: `distance_miles` must be at least the state regulation's `min_driveby_radius_miles` for a `DRIVE_BY` order, or its `min_interior_radius_miles` for an `INTERIOR` order, else `ERR_COMPARABLE_RADIUS_VIOLATION`. A comparable may be marked `SELECTED` by the broker only from `DRAFT` status (which revalidates the cap and radius), or `REJECTED` by the broker or a `QCReviewer` from either `DRAFT` or `SELECTED` status; either transition attempted on a comparable in any other status is rejected with `ERR_INVALID_STATE`. Comparables are listable per order with an optional `status` filter.

Photo evidence is uploaded by the assigned broker — `ERR_FORBIDDEN` if another identity attempts it — with each row carrying a `photo_kind` (one of `FRONT`, `REAR`, `STREET`, `INTERIOR_LIVING`, `INTERIOR_KITCHEN`, `INTERIOR_BATH`, `DEFECT`, or `OTHER`), a `file_url`, and a `captured_at` timestamp that must be on or after the order's creation and not in the future. The uploading broker's identity is stamped onto the row's `uploaded_by_broker_id` from `X-User-ID`. Photo rows are evidentiary: they carry `id` and `created_at` only, with no `updated_at` or `version`. An order's photo list supports an optional `photo_kind` query filter.

Fee lines build the financial reconciliation. A `Broker`, `OperationsManager`, or `BillingClerk` adds a `FeeLine` with a `fee_kind` (`BASE`, `RUSH_SURCHARGE`, `INTERIOR_SURCHARGE`, `APPRAISAL_SURCHARGE`, `TRAVEL`, or `MISC`), a `description` string (required, but may be empty), and a signed `amount_cents` that may be negative to represent credits. Fee lines begin `DRAFT`; a `BillingClerk` or `OperationsManager` may confirm one (`DRAFT` to `CONFIRMED`) or cancel a draft one, and — unlike creation, which requires a non-terminal order — confirmation and cancellation apply regardless of the parent order's state. An order's fee-line list supports an optional `status` query filter.

### 3.6. Report Submission and the Quality Control Cycle

Report submission moves the order from `IN_PROGRESS` to `REPORT_SUBMITTED` and is the assigned broker's act (`ERR_FORBIDDEN` otherwise). Submission enforces three floors, in the system's priority order. The comparable-count floor requires the count of `SELECTED` comparables on the order to meet the state minimum — 3 for a `DRIVE_BY` order, 4 for an `INTERIOR` order — else `ERR_INSUFFICIENT_COMPARABLES`. The photo-evidence minimum requires, for a `DRIVE_BY` order, at least 2 photo rows whose `photo_kind` is `FRONT` or `STREET`, and for an `INTERIOR` order, at least 3 photo rows covering one each of `INTERIOR_LIVING`, `INTERIOR_KITCHEN`, and `INTERIOR_BATH` — else `ERR_INSUFFICIENT_PHOTOS`. Fee reconciliation requires the sum of `amount_cents` across all fee lines whose `status` is not `CANCELLED` to equal the order's `agreed_fee_cents` exactly, else `ERR_FEE_RECONCILE_MISMATCH`. On successful submission the system recomputes `adjusted_value_cents` for every `SELECTED` comparable and increments the order's `version`.

Quality control then proceeds in numbered cycles. A `QCReviewer` opens a cycle, moving the order from `REPORT_SUBMITTED` to `QC_REVIEW`; if any cycle is already open for the order — a cycle is open from the moment it is created until a verdict is recorded on it — the attempt is rejected with `ERR_QC_CYCLE_ALREADY_OPEN`. Opening creates a `QCReview` row whose `cycle_index` is 1 for the first review on the order, or one greater than the maximum prior `cycle_index`. The reviewer is recorded as the opaque `reviewer_id`, QC reviews are listable per order and retrievable individually, and the revision requests produced by a given review are listable through a reverse lookup on `qc_review_id`.

Recording a verdict is the pivotal act, with three branches sharing two common preconditions: the targeted review's `cycle_index` must equal the latest cycle for the order (`ERR_QC_CYCLE_STALE`), and the segregation-of-duties rule of §2.8 must pass (`ERR_SEGREGATION_OF_DUTIES`). Every verdict carries the `verdict` value, a `defects_found` count of 0 or more, and free-text `notes` (a required string that may be empty), and every verdict stamps the review's read-only `reviewed_at` to the current instant. A successful verdict returns the updated `QCReview`.

- An `APPROVE` verdict requires `defects_found` to be exactly 0 (`ERR_INVALID_REQUEST` otherwise). It moves the order to `ACCEPTED` and triggers a broker `composite_score` recompute in which this order contributes a quality value of 1.0, weighted by the client's `scorecard_weight_quality`.
- A `REVISE` verdict requires `defects_found` of at least 1 (`ERR_INVALID_REQUEST` otherwise). It moves the order to `REVISION_REQUESTED`, creates a `QCRevisionRequest` row whose `cycle_index` matches the review's, whose `due_at` is the verdict instant plus the revision window of 72 hours, and whose `outcome` starts `OPEN`; increments the order's `revision_count`; and stamps `reviewed_at`.
- A `REJECT` verdict requires `defects_found` of at least 3 (`ERR_INVALID_REQUEST` otherwise). It moves the order to the terminal `REJECTED` state, triggers a `composite_score` recompute in which this order contributes a quality value of 0.0, decrements the broker's open-order count, and cancels every `DRAFT` fee line on the order while leaving `CONFIRMED` fee lines in place for audit.

Each verdict increments the order's `version`. A revision request is itself an append-only record carrying `id` and `created_at` only, plus a free-text `reason` copied from the verdict's `notes`; its `resolved_at` stays empty until the broker resubmits.

### 3.7. Revision, Completion, and Late-Fee Settlement

When an order sits in `REVISION_REQUESTED`, the assigned broker resubmits, moving it back to `REPORT_SUBMITTED`. Resubmission requires the caller's `X-User-ID` to match the order's `assigned_broker_id` (`ERR_FORBIDDEN`) and the targeted revision request's `outcome` to be `OPEN` (`ERR_REVISION_NOT_OPEN`). On resubmission the request's `resolved_at` is set to the current instant, and its `outcome` becomes `RESOLVED_ON_TIME` if that instant is on or before its `due_at`, or `RESOLVED_LATE` otherwise; a late resolution triggers a broker `composite_score` recompute with the turnaround component degraded. The order's `version` increments, the order re-enters the QC cycle from `REPORT_SUBMITTED`, and the resubmission response returns the updated `QCRevisionRequest`. Revision-request listings — both per order and per QC review — support an optional `outcome` query filter.

Completion is the `OperationsManager`'s exclusive act, moving an `ACCEPTED` order to `COMPLETED`. Completion is refused with `ERR_INVALID_STATE` unless the order is `ACCEPTED`, and refused with `ERR_OPEN_REVISION_EXISTS` while any revision request on the order remains `OPEN`. Completion stamps `completed_at` to the current instant and settles the late-fee arithmetic. The read-only `days_late` is 0 when the order completed on or before its `sla_due_at`; otherwise it is the elapsed seconds between `sla_due_at` and `completed_at` divided by 86,400 (the number of seconds in a day), rounded half-up to a whole day count. If `days_late` is 0, the `late_penalty_cents` is 0. Otherwise the raw penalty is the order's `agreed_fee_cents` multiplied by the owning client's `late_penalty_bps_per_day` (at most 2000 basis points per day) multiplied by `days_late`, divided by 10,000; the `late_penalty_cents` is that raw penalty rounded half-up to whole cents, capped so it never exceeds `agreed_fee_cents`. The read-only `net_payable_cents` is then `agreed_fee_cents` minus `late_penalty_cents`, floored at 0. The read-only `is_rush_breach` flag is true if and only if the order's `priority` is `RUSH` and `completed_at` is after `sla_due_at`. Completion also decrements the broker's open-order count, triggers a `composite_score` recompute driven by `is_rush_breach` and `days_late`, and increments the order's `version`. The order's terminal states are `COMPLETED`, `CANCELLED`, and `REJECTED`.

### 3.8. Payout Batches and Volume Forecasting

Broker compensation is settled in batches. A `BillingClerk` opens a `PayoutBatch` by supplying the recipient `broker_id` and a period: `period_start` is the inclusive ISO 8601 UTC start and `period_end` the exclusive end, which must be strictly after `period_start`. On creation the system computes two read-only aggregates: `total_payable_cents`, the sum of `net_payable_cents` across orders in `COMPLETED` whose `completed_at` falls within the half-open period and whose `assigned_broker_id` is the recipient — with each order's contribution rounded to integer cents before summation (a round-per-line rule); and `order_count`, the number of contributing orders. A client-facing invoice display may instead sum net amounts at full precision and round only at presentation; that read-only display can differ from the round-per-line total by up to the number of orders minus one cents, and the round-per-line figure is the authoritative one for payout. A batch starts `OPEN` and is listable with optional `broker_id` and `status` filters.

Approval requires the OCC field `expected_batch_version` and at least one contributing order, else `ERR_EMPTY_BATCH`; approval snapshots `total_payable_cents` so it is never recomputed again, and moves the batch to `APPROVED`. Disbursement requires every contributing order to still be in `COMPLETED` — a contributing order that is not is rejected with `ERR_ORDER_NOT_COMPLETED` — and on success sets each contributing order's `payment_status` to `PAID`, moving the batch to the terminal `DISBURSED`. A batch still `OPEN` may instead be voided, moving it to the terminal `VOIDED`; voiding carries no preconditions. Order payment status more broadly spans `UNBILLED`, `INVOICED`, `PAID`, `PARTIALLY_PAID`, and `WAIVED`, though disbursement in this system always marks `PAID`.

Finally, order-volume planning is served by the `VolumeForecast`. An `OperationsManager` or `PlatformAdmin` generates a forecast by supplying a `state_code` and a `forecast_month` in `YYYY-MM` form. The prediction is a volume-weighted moving average over the trailing three calendar months of completed orders in the same state: letting the most recent completed month before `forecast_month` contribute count c1, the month before that c2, and the month before that c3, the predicted order count is three times c1 plus two times c2 plus one times c3, all divided by 6, rounded half-up to a whole count. The window runs from the first day of the month three months before `forecast_month` up to but excluding the first day of `forecast_month`, and only orders whose `completed_at` falls in that window and whose property's `state_code` matches the forecast's contribute. The resulting row stores the read-only `predicted_order_count`, a system-stamped `model_version` identifier such as `VWMA-3m-v1`, and the read-only `generated_at` timestamp; like other analytical records it carries only `id` and `created_at`. Forecasts are listable with optional `state_code` and `forecast_month` filters.

Orders, finally, are listable by `PlatformAdmin`, `OperationsManager`, `DispatchCoordinator`, `BillingClerk`, `QCReviewer`, `ClientAdmin`, and `Broker`, with optional filters on `fulfillment_status`, `payment_status`, `client_id`, `assigned_broker_id`, and `property_id`; the fulfillment lifecycle as a whole spans `INTAKE`, `READY_FOR_DISPATCH`, `DISPATCHED`, `IN_PROGRESS`, `REPORT_SUBMITTED`, `QC_REVIEW`, `REVISION_REQUESTED`, `ACCEPTED`, `COMPLETED`, `CANCELLED`, and `REJECTED`.

## 4. Endpoint Definitions

Operations that create a new resource — a client account, a state regulation, a property, a broker, a license, an order, a comparable, a photo, a fee line, a QC review cycle, a payout batch, or a volume forecast — return a `201 Created` status code. Operations that modify an existing resource, including every state transition (submit, dispatch, accept, decline, cancel, select, reject, confirm, report, verdict, resubmit, complete, approve, disburse, void, activate, suspend, reinstate, terminate), return a `200 OK` status code. List and single-resource retrievals return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/bpo/client-accounts` | Register a new client account | PlatformAdmin |
| GET | `/bpo/client-accounts` | List client accounts with pagination | PlatformAdmin, OperationsManager, BillingClerk |
| GET | `/bpo/client-accounts/{id}` | Get a single client account | PlatformAdmin, OperationsManager, BillingClerk, ClientAdmin |
| POST | `/bpo/state-regulations` | Create or replace a state regulation row | ComplianceOfficer |
| GET | `/bpo/state-regulations` | List state regulations | ComplianceOfficer, PlatformAdmin, OperationsManager, DispatchCoordinator |
| GET | `/bpo/state-regulations/{state_code}` | Get a single state regulation | ComplianceOfficer, PlatformAdmin, OperationsManager, DispatchCoordinator |
| POST | `/bpo/properties` | Register a property | OperationsManager, ClientAdmin |
| GET | `/bpo/properties` | List properties | OperationsManager, ClientAdmin, DispatchCoordinator, Broker |
| GET | `/bpo/properties/{id}` | Get a property | OperationsManager, ClientAdmin, DispatchCoordinator, Broker |
| GET | `/bpo/properties/{id}/comparables` | List comparables referencing this property | OperationsManager, DispatchCoordinator, Broker, QCReviewer, PlatformAdmin |
| POST | `/bpo/brokers` | Onboard a new broker | ComplianceOfficer |
| GET | `/bpo/brokers` | List brokers | ComplianceOfficer, PlatformAdmin, OperationsManager, DispatchCoordinator, BillingClerk |
| GET | `/bpo/brokers/{id}` | Get a broker | ComplianceOfficer, PlatformAdmin, OperationsManager, DispatchCoordinator, BillingClerk, Broker |
| POST | `/bpo/brokers/{id}/activate` | Activate a broker (requires at least one ACTIVE license) | ComplianceOfficer |
| POST | `/bpo/brokers/{id}/suspend` | Suspend a broker (reverts their DISPATCHED orders) | ComplianceOfficer |
| POST | `/bpo/brokers/{id}/reinstate` | Reinstate a suspended broker | ComplianceOfficer |
| POST | `/bpo/brokers/{id}/terminate` | Terminate a broker (no open orders allowed) | ComplianceOfficer |
| POST | `/bpo/brokers/{id}/licenses` | Attach a state license to a broker | ComplianceOfficer |
| GET | `/bpo/brokers/{id}/licenses` | List a broker's licenses | ComplianceOfficer, PlatformAdmin, OperationsManager, DispatchCoordinator, Broker |
| GET | `/bpo/brokers/{id}/photos` | List photo evidence uploaded by this broker | ComplianceOfficer, PlatformAdmin, OperationsManager, DispatchCoordinator, Broker, QCReviewer |
| POST | `/bpo/valuation-orders` | Create a new valuation order (in INTAKE) | ClientAdmin, OperationsManager |
| GET | `/bpo/valuation-orders` | List valuation orders | PlatformAdmin, OperationsManager, DispatchCoordinator, BillingClerk, QCReviewer, ClientAdmin, Broker |
| GET | `/bpo/valuation-orders/{id}` | Get a single valuation order | PlatformAdmin, OperationsManager, DispatchCoordinator, BillingClerk, QCReviewer, ClientAdmin, Broker |
| POST | `/bpo/valuation-orders/{id}/submit` | Transition order INTAKE → READY_FOR_DISPATCH | ClientAdmin |
| POST | `/bpo/valuation-orders/{id}/dispatch` | Transition order READY_FOR_DISPATCH → DISPATCHED, assigns broker | DispatchCoordinator |
| POST | `/bpo/valuation-orders/{id}/accept` | Broker accepts a dispatched order | Broker |
| POST | `/bpo/valuation-orders/{id}/decline` | Broker declines a dispatched order | Broker |
| POST | `/bpo/valuation-orders/{id}/cancel` | Client cancels an order in INTAKE/READY_FOR_DISPATCH/DISPATCHED | ClientAdmin |
| POST | `/bpo/valuation-orders/{id}/comparables` | Add a comparable to an order (DRAFT) | Broker, OperationsManager |
| GET | `/bpo/valuation-orders/{id}/comparables` | List comparables for an order | Broker, OperationsManager, QCReviewer, DispatchCoordinator, PlatformAdmin |
| POST | `/bpo/valuation-orders/{id}/comparables/{comp_id}/select` | Mark a comparable as SELECTED | Broker |
| POST | `/bpo/valuation-orders/{id}/comparables/{comp_id}/reject` | Mark a comparable as REJECTED | Broker, QCReviewer |
| POST | `/bpo/valuation-orders/{id}/photos` | Upload a photo evidence row | Broker |
| GET | `/bpo/valuation-orders/{id}/photos` | List photo evidence for an order | Broker, OperationsManager, QCReviewer, DispatchCoordinator, PlatformAdmin |
| POST | `/bpo/valuation-orders/{id}/fee-lines` | Add a fee line (DRAFT) | Broker, OperationsManager, BillingClerk |
| GET | `/bpo/valuation-orders/{id}/fee-lines` | List fee lines for an order | Broker, OperationsManager, BillingClerk, QCReviewer, PlatformAdmin, ClientAdmin |
| POST | `/bpo/valuation-orders/{id}/fee-lines/{fee_id}/confirm` | Confirm a fee line (DRAFT → CONFIRMED) | BillingClerk, OperationsManager |
| POST | `/bpo/valuation-orders/{id}/fee-lines/{fee_id}/cancel` | Cancel a DRAFT fee line | BillingClerk, OperationsManager |
| POST | `/bpo/valuation-orders/{id}/report` | Submit report (IN_PROGRESS → REPORT_SUBMITTED) | Broker |
| POST | `/bpo/valuation-orders/{id}/qc/open` | Open a QC review cycle | QCReviewer |
| GET | `/bpo/valuation-orders/{id}/qc` | List QC reviews for an order | QCReviewer, OperationsManager, PlatformAdmin, Broker |
| GET | `/bpo/qc-reviews/{id}` | Get a single QC review by id | QCReviewer, OperationsManager, PlatformAdmin |
| GET | `/bpo/qc-reviews/{id}/revisions` | List revision requests produced by this QC review | QCReviewer, OperationsManager, PlatformAdmin, Broker |
| POST | `/bpo/valuation-orders/{id}/qc/{qc_id}/verdict` | Record QC verdict (APPROVE/REVISE/REJECT) | QCReviewer |
| GET | `/bpo/valuation-orders/{id}/revisions` | List revision requests for an order | QCReviewer, OperationsManager, Broker, PlatformAdmin |
| POST | `/bpo/valuation-orders/{id}/revision/{rev_id}/resubmit` | Broker resubmits a revision (REVISION_REQUESTED → REPORT_SUBMITTED) | Broker |
| POST | `/bpo/valuation-orders/{id}/complete` | Complete an accepted order (computes late fee and net payable) | OperationsManager |
| POST | `/bpo/payout-batches` | Open a payout batch for a broker + period | BillingClerk |
| GET | `/bpo/payout-batches` | List payout batches | BillingClerk, OperationsManager, PlatformAdmin, Broker |
| GET | `/bpo/payout-batches/{id}` | Get a payout batch | BillingClerk, OperationsManager, PlatformAdmin, Broker |
| POST | `/bpo/payout-batches/{id}/approve` | Approve a payout batch (OCC-guarded) | BillingClerk |
| POST | `/bpo/payout-batches/{id}/disburse` | Disburse a payout batch (marks contributing orders PAID) | BillingClerk |
| POST | `/bpo/payout-batches/{id}/void` | Void an open payout batch | BillingClerk |
| POST | `/bpo/volume-forecasts` | Generate a volume forecast for a state+month | OperationsManager, PlatformAdmin |
| GET | `/bpo/volume-forecasts` | List volume forecasts | OperationsManager, PlatformAdmin |
| POST | `/_clock/set_current_utc` | Test-driving endpoint: set the server's logical UTC clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_LICENSE_NOT_VALID_FOR_STATE` | 422 |
| `ERR_BPO_NOT_PERMITTED` | 422 |
| `ERR_INTERIOR_REQUIRES_APPRAISAL` | 422 |
| `ERR_STATE_REGULATION_SUSPENDED` | 409 |
| `ERR_PROPERTY_NOT_REGISTERED` | 409 |
| `ERR_INSUFFICIENT_COMPARABLES` | 422 |
| `ERR_INSUFFICIENT_PHOTOS` | 422 |
| `ERR_FEE_RECONCILE_MISMATCH` | 422 |
| `ERR_ADJUSTMENT_EXCEEDS_CAP` | 422 |
| `ERR_ADJUSTMENT_NONPOSITIVE` | 422 |
| `ERR_COMPARABLE_RADIUS_VIOLATION` | 422 |
| `ERR_BROKER_CAPACITY_FULL` | 409 |
| `ERR_ORDER_ALREADY_DISPATCHED` | 409 |
| `ERR_QC_CYCLE_ALREADY_OPEN` | 409 |
| `ERR_QC_CYCLE_STALE` | 409 |
| `ERR_REVISION_NOT_OPEN` | 409 |
| `ERR_OPEN_REVISION_EXISTS` | 409 |
| `ERR_EMPTY_BATCH` | 409 |
| `ERR_ORDER_NOT_COMPLETED` | 409 |
| `ERR_OPEN_ORDERS_EXIST` | 409 |
| `ERR_OVERDUE_REVISION_BLOCKS_REINSTATE` | 409 |
| `ERR_NO_ACTIVE_LICENSE` | 409 |
| `ERR_BROKER_NOT_ACTIVE` | 409 |
| `ERR_INTERNAL` | 500 |
