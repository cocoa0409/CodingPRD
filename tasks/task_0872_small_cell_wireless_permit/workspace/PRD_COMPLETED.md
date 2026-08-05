# Small-Cell & Wireless Facility Permit API — Product Requirements Document

## 1. Introduction

Wireless carriers deploying small-cell networks must place hundreds of low-power radio nodes on poles and other vertical assets that sit inside the public right-of-way (ROW). Each placement triggers a municipal review that blends engineering judgment, aesthetic and historic-district sensitivity, statutory "shot-clock" deadlines borrowed from federal telecommunications rules, and a recurring rental obligation for occupying public land. This API is the system of record for that process. It governs the full arc of a permit: a provider registers and executes a master license agreement, files a batch application listing one or more proposed nodes, submits the batch to start the clock, and then shepherds each node through two independent review dimensions before a single authority renders a batch-wide decision.

The system is deliberately built around segregation of duties and immediate consistency. The official who decides an application must never be one of the reviewers who examined its nodes, and every side effect — a reserved collocation slot, a provisional fee, a prorated rental, a refund — is applied synchronously as its triggering event is recorded. Because deadlines, moratoria, and proration all depend on time, the server runs on an explicit logical clock rather than wall-clock time, so that automated evaluators can reproduce every temporal decision exactly. The remainder of this document specifies the global contracts every endpoint honors (Section 2) and the business workflows that move applications, nodes, invoices, rentals, and appeals through their lifecycles (Section 3).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request missing either header, or presenting an `X-User-Role` that is not one of the recognized roles, is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes six roles, spelled exactly as follows: `Applicant`, `ROWReviewer`, `AestheticReviewer`, `Approver`, `Inspector`, and `PlatformAdmin`. Their duties are disjoint. An `Applicant` is a wireless provider that owns its applications, nodes, payments, and appeals. A `ROWReviewer` runs completeness determinations and design-standard reviews. An `AestheticReviewer` runs aesthetic and historic-district reviews. An `Approver` issues batch and appeal decisions. An `Inspector` records physical inspections and activates permitted nodes. A `PlatformAdmin` seeds providers, structures, and segments, runs deadline sweeps and rental renewals, and controls the logical clock.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting `Applicant`; ownership checks on any resource that references an applicant compare the resource's `applicant_id` (directly, or through the owning application) to `X-User-ID`, and an applicant may only act on and read its own applications, nodes, invoices, rentals, and appeals. When `X-User-Role` is any of `ROWReviewer`, `AestheticReviewer`, `Approver`, `Inspector`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — as `reviewer_user_id` on a review record, `inspector_user_id` on an inspection, or `decided_by_user_id` on an appeal — but it does not compare that identifier to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific workflow states otherwise, list endpoints return resources sorted by their creation timestamp in ascending order. Every list response echoes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Most resources carry a standard set of system-managed fields. Every resource has an `id` — a server-minted UUID with no type prefix — and a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits recording when the resource was first created. Resources that can be mutated after creation additionally carry an `updated_at` timestamp, refreshed on every change, and a `version`, an integer that begins at 1 and increments by one on each mutation. The applicant record, the support structure, the permit application, the node, the fee invoice, the recurring rental, and the appeal all carry `updated_at` and `version`.

Five resource kinds are immutable audit records that carry only `id` and `created_at`; they have neither `updated_at` nor `version`. These are the ROW segment, the node review record, the inspection record, the payment record, and the incompleteness notice. Whenever a mutation touches a versioned resource — including a change to a computed field such as a structure's slot counts or an invoice's outstanding balance — the server refreshes that resource's `updated_at` and increments its `version` by one.

### 2.5. Nested Resource Retrieval and Existence Validation

Many endpoints address a resource through a path that names one or more identifiers. The server validates those identifiers left to right and rejects the request at the first identifier that does not resolve, returning the not-found error specific to that resource kind: `ERR_APPLICANT_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_NODE_NOT_FOUND`, `ERR_SUPPORT_STRUCTURE_NOT_FOUND`, `ERR_ROW_SEGMENT_NOT_FOUND`, `ERR_FEE_INVOICE_NOT_FOUND`, `ERR_RENTAL_NOT_FOUND`, or `ERR_APPEAL_NOT_FOUND`. A create or transition request whose body references a foreign entity that does not exist is likewise rejected with that entity's not-found error — for example, adding a node whose `support_structure_id` does not resolve yields `ERR_SUPPORT_STRUCTURE_NOT_FOUND`, and one whose `row_segment_id` does not resolve yields `ERR_ROW_SEGMENT_NOT_FOUND`.

### 2.6. Optimistic Concurrency Control

Two write operations require the client to prove it is acting on a current view of a shared parent, using optimistic concurrency control. In each case the request carries an expected-version field; if it does not equal the parent's current `version`, the write is rejected with `ERR_STALE_VERSION` (HTTP 412), and no side effects are applied.

First, recording a design-standard review requires `expected_support_structure_version` to match the current `version` of the referenced support structure. Because a design pass reserves a physical slot and advances the structure's version, a reviewer whose `expected_support_structure_version` is behind the structure's current version is working from a stale view of remaining capacity, and the review is rejected with `ERR_STALE_VERSION`. Second, recording a payment requires `expected_fee_invoice_version` to match the invoice's current `version`; if another writer has already posted a payment and advanced the invoice version, the stale payment is rejected with `ERR_STALE_VERSION`. Both fields are mandatory on their respective operations. Endpoints other than these two do not accept a version field and perform no concurrency check.

### 2.7. Collocation Slot Accounting and Structure Consistency

A support structure exposes its capacity through four numbers. Its `max_collocations` is the total number of small-cell slots the structure can physically host, fixed at creation and never below 1. Its `reserved_collocations` counts slots held by nodes whose design review has passed but which are not yet activated — a reservation is created the instant a node's design review passes and persists while the node is `IN_REVIEW` with a passed design (aesthetic still pending), `APPROVED`, or `PERMITTED` — and its `active_collocations` counts slots occupied by nodes that have been activated. The computed `available_collocations` is always `max_collocations` minus `reserved_collocations` minus `active_collocations`. Both `reserved_collocations` and `active_collocations` start at 0.

These counters move only through the side effects described in Section 3: a design pass reserves a slot, a rejection or withdrawal releases a reservation, and activation converts a reservation into an active occupancy. Every such counter change is a mutation of the support structure and therefore refreshes its `updated_at` and increments its `version`. A structure's `status` is either `ACTIVE` or `RETIRED`, beginning `ACTIVE`; its `structure_type` is one of `EXISTING_UTILITY`, `EXISTING_MUNICIPAL`, or `NEW_POLE`, where the two existing kinds are pre-existing poles that a collocation reuses and a new pole is proposed construction; and its `in_design_district` classification is one of `NONE`, `STANDARD`, or `HISTORIC`, defaulting to `NONE`. A `location_desc` may be supplied to describe where the structure stands.

### 2.8. Monetary Precision and Fee Rounding

All monetary amounts in the system are integers denominated in cents: application fees, payments, refunds, and ROW rentals. Wherever a rule multiplies a base amount by a rate — the technology surcharge on an application fee, or the proration factor on a rental — the result is rounded to a whole number of cents using the round-half-up convention (a value exactly halfway between two cents rounds up to the larger cent). The application-fee calculation is especially sensitive to rounding order: each node's surcharged fee is rounded to whole cents first, and only then are the per-node amounts summed. Rounding the sum instead of the parts would differ by a cent on some batches and is not permitted.

### 2.9. The Logical Clock and Temporal Reckoning

The server keeps a logical clock that supplies every timestamp and drives every time-based rule: submission time, tolling durations, shot-clock deadlines, pavement moratoria, and rental proration. At startup the clock reads exactly `2026-05-01T00:00:00Z` and never falls back to wall-clock time; before any client advances it, that default is the current instant. A `PlatformAdmin` may move the clock forward by supplying a target instant as `to_iso8601`. All datetime values the system stores or computes are rendered as ISO 8601 UTC with three fractional digits.

### 2.10. Validation Ordering and Error Precedence

When more than one rule could reject a request, the checks run in a fixed order so that the returned error is deterministic. Authentication is evaluated first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_UNAUTHORIZED`), then existence of every resource named in the path (the entity-specific not-found errors of Section 2.5), then whether the target resource is in a legal from-state for the requested transition (`ERR_INVALID_STATE`). Only after those universal gates do endpoint-specific business rules run.

Among the business rules, the following relative precedence holds where several apply to the same endpoint. On a batch decision, the four-eyes segregation check (`ERR_SEGREGATION_OF_DUTIES`) is evaluated before the check that no node is still under review (`ERR_NODES_PENDING_REVIEW`). On a submission, the master-agreement requirement (`ERR_MASTER_AGREEMENT_REQUIRED`) is evaluated before the node-completeness requirement (`ERR_NO_NODES`). On a design review, structure activeness (`ERR_STRUCTURE_NOT_ACTIVE`) is checked first, then the pavement moratorium for a new pole (`ERR_PAVEMENT_MORATORIUM`), then remaining capacity (`ERR_STRUCTURE_CAPACITY_EXCEEDED`), and the optimistic-concurrency check (`ERR_STALE_VERSION`) is applied against the structure version as part of the same operation. On activation, the passing-inspection requirement (`ERR_INSPECTION_NOT_PASSED`) precedes the paid-in-full requirement (`ERR_INVOICE_UNPAID`). A malformed body — a missing required field, an invalid enum member, or a non-positive integer where a positive one is required — is rejected with `ERR_INVALID_REQUEST`.

## 3. Business Logic & Workflows

### 3.1. Provider Onboarding and Infrastructure Seeding

Before any permit can move, the platform must know the provider and the physical world it is building in. A `PlatformAdmin` registers a wireless provider by supplying its `company_name` and `contact_email`; the new applicant record is created with a `certification_status` of `REGISTERED` (the only standing this benchmark uses), with `master_agreement_signed` set to false and `master_agreement_signed_at` left null. Executing the ROW master license agreement is an applicant-only act on the provider's own record: it sets `master_agreement_signed` to true and stamps `master_agreement_signed_at` with the current clock value, advancing the applicant's version. No application may be submitted until this agreement is in force.

Support structures and right-of-way segments are the shared infrastructure that nodes attach to. A support structure is created with its `structure_type`, its `max_collocations`, and optionally a `location_desc` and an `in_design_district` classification; new poles proposed by a provider may be created by either a `PlatformAdmin` or an `Applicant`, while other seeding is administrative. A right-of-way segment is created by a `PlatformAdmin` with a descriptive `name`, a `corridor_code`, and optionally a `last_paved_at` timestamp, a `moratorium_months` window, and an `in_historic_district` flag. When `last_paved_at` is omitted it is null, meaning the segment has never been paved and imposes no moratorium; `moratorium_months` defaults to 36 whole months; and `in_historic_district` defaults to false. A segment lying in a historic district forces aesthetic review on any node placed there. Nodes attached to a structure or sitting in a segment can be listed through the structure's node list and the segment's node list respectively.

A `PlatformAdmin` may retire a support structure, but only while it is `ACTIVE` and only when it holds no slots at all — both `reserved_collocations` and `active_collocations` must be exactly 0. A retirement request against a structure that is not `ACTIVE`, or that still holds any slot, is rejected with `ERR_INVALID_STATE`. Retirement sets `status` to `RETIRED` and advances the structure's version. A retired structure can no longer host design reviews.

### 3.2. Assembling and Submitting a Batch Application

An `Applicant` opens a batch by creating a permit application, optionally naming it with a `project_name`; the new application's `applicant_id` is taken from `X-User-ID`, and it begins life in `DRAFT`. While the application is still `DRAFT`, the applicant adds nodes to it, one per proposed small-cell site. Each node names the batch it belongs to via `application_id`, the pole it attaches to via `support_structure_id`, the segment it sits in via `row_segment_id`, its `facility_type` — either `COLLOCATION` for reuse of an existing pole or `NEW_POLE` for new construction — and a `proposed_construction_date`; a `location_desc` is optional. A node starts in `PROPOSED`, with `design_review_status` of `PENDING` and `aesthetic_review_status` of `PENDING`. Adding a node to an application that is not in `DRAFT` is rejected with `ERR_INVALID_STATE`. The application also surfaces a computed `node_count` covering its child nodes of any status.

Submitting the batch is an applicant-only act that starts the regulatory clock. The submission is refused unless the acting applicant owns the application, the provider's `master_agreement_signed` is true (otherwise `ERR_MASTER_AGREEMENT_REQUIRED`), and the batch contains at least one node with every node fully specified — each carrying its support structure, its segment, and its construction date (otherwise `ERR_NO_NODES`). On success, the application moves from `DRAFT` to `SUBMITTED` and several things happen at once: `submitted_at` is set to the current clock; `shot_clock_base_days` and `shot_clock_deadline` are computed as described in Section 2.9 and below; a provisional fee invoice is raised; every node advances from `PROPOSED` to `IN_REVIEW`; and for each node whose segment is not in a historic district and whose structure's design district is `NONE`, the node's `aesthetic_review_status` is set to `WAIVED` because no aesthetic review is required. Submission advances the application's version.

The shot clock's length depends on the mix of nodes. The `shot_clock_base_days` is 60 days when every node in the batch is a collocation, and 90 days when any node is a new pole — a single new pole forces the longer federal clock. The `shot_clock_deadline` is `submitted_at` plus that base number of days plus any accumulated tolling days (initially zero). The first-submission `submitted_at` is captured once and is not reset by the completeness cycle described next.

### 3.3. Completeness Review and the Tolling Cycle

Once submitted, an application awaits a completeness determination from a `ROWReviewer`. The reviewer records a determination carrying a `complete` flag and, when incomplete, an optional `deficiencies` description. A determination of not-complete moves the application from `SUBMITTED` to `INCOMPLETE` and creates an incompleteness notice whose `issued_at` is the current clock and whose `cured_at` is null; from this instant the shot clock is effectively paused because the eventual cure duration will be added back to the deadline. A determination of complete instead moves the application from `SUBMITTED` to `UNDER_REVIEW`, leaving the nodes in `IN_REVIEW` so that substantive design and aesthetic review may proceed. Advancing an application that is not in `SUBMITTED` through completeness review is rejected with `ERR_INVALID_STATE`, and the transition advances the application's version.

Curing is the applicant's response to an incompleteness notice, moving the application from `INCOMPLETE` back to `SUBMITTED`. The cure is refused unless the acting applicant owns the application, the application is currently `INCOMPLETE`, and the latest incompleteness notice is still open (its `cured_at` is null). On cure, that latest notice's `cured_at` is set to the current clock and its `toll_days` is set to the elapsed time from `issued_at` to `cured_at`, expressed in days as the exact elapsed duration (elapsed seconds divided by 86,400, so it may be fractional); that same quantity is added to the application's `toll_days_accumulated`; and the `shot_clock_deadline` is recomputed as `submitted_at` plus `shot_clock_base_days` days plus the running `toll_days_accumulated`. The incompleteness notices of an application can be listed. Because `submitted_at` is preserved across the loop, repeated incompleteness-and-cure cycles simply push the deadline out by the total time the application spent waiting to be cured. Curing advances the application's version.

### 3.4. Parallel Node Review: Design and Aesthetic Dimensions

Each node under an `UNDER_REVIEW` application is examined along two independent dimensions that fork and then join. The design-standard dimension is owned by a `ROWReviewer`, who records an `outcome` of `PASS` or `FAIL` along with the mandatory `expected_support_structure_version` and optional `findings`. This creates a review record whose `node_id` points at the node and whose `review_type` is `DESIGN_STANDARD`, stamps its `reviewer_user_id` from `X-User-ID`, sets the node's `design_review_status` to the recorded outcome, and advances the structure's version. A design review is admissible only when the node is `IN_REVIEW`, its parent application is `UNDER_REVIEW`, and the referenced support structure is `ACTIVE`; a review against a retired structure is rejected with `ERR_STRUCTURE_NOT_ACTIVE`.

A passing design outcome carries three further conditions before it takes effect. The structure must have room: the sum of its `reserved_collocations` and `active_collocations` must be strictly less than its `max_collocations`, otherwise the pass is rejected with `ERR_STRUCTURE_CAPACITY_EXCEEDED`. For a new-pole node, the `proposed_construction_date` must not fall within the segment's pavement moratorium — the half-open window running from `last_paved_at` up to but not including `last_paved_at` plus `moratorium_months` months — otherwise it is rejected with `ERR_PAVEMENT_MORATORIUM`; a segment with a null `last_paved_at` imposes no such window. And `expected_support_structure_version` must match the structure's current version, as described in Section 2.6, otherwise `ERR_STALE_VERSION`. When a design pass clears all of these, the structure's `reserved_collocations` is increased by one, holding a slot for the node.

The aesthetic-and-historic dimension is owned by an `AestheticReviewer`, who records an `outcome` of `PASS` or `FAIL` with an optional `concealment_required` flag and optional `findings`. This creates a review record with a `review_type` of `AESTHETIC_HISTORIC` and sets the node's `aesthetic_review_status` to the outcome. An aesthetic review is admissible only when the node is `IN_REVIEW`, the parent application is `UNDER_REVIEW`, and the node's `aesthetic_review_status` is still `PENDING`; a node whose aesthetic dimension was auto-waived at submission needs no such review.

After either dimension is recorded, the system evaluates the fork-join. A node joins to `APPROVED` only when its `design_review_status` is `PASS` and its `aesthetic_review_status` is either `PASS` or `WAIVED`. A node joins to `REJECTED` as soon as either dimension is `FAIL`; if that node had already reserved a slot from a prior design pass, the rejection releases it by decrementing the structure's `reserved_collocations`. A node's review records can be listed for audit.

### 3.5. The Batch Decision and Four-Eyes Segregation

When node review is complete, an `Approver` renders a single decision for the whole batch, optionally attaching `decision_notes`. Two guards run first. The four-eyes segregation of duties requires that the acting approver's `X-User-ID` not appear as the `reviewer_user_id` of any review record under this application; an approver who reviewed any node of the batch is blocked with `ERR_SEGREGATION_OF_DUTIES`. The decision also requires that no node is still `IN_REVIEW`; a premature decision is rejected with `ERR_NODES_PENDING_REVIEW`. The application must itself be `UNDER_REVIEW`.

The outcome is derived automatically from the nodes rather than chosen by the approver. If every node is `APPROVED` — equivalently, every node's `design_review_status` is `PASS` and its `aesthetic_review_status` is `PASS` or `WAIVED` — the application moves to `GRANTED`. If at least one node is `APPROVED` and at least one is `REJECTED`, it moves to `PARTIALLY_GRANTED`. If every node is `REJECTED`, it moves to `DENIED`. In all three cases `decided_at` is set to the current clock and the application's version advances. On a full grant, each `APPROVED` node advances to `PERMITTED`. On a partial grant, each `APPROVED` node advances to `PERMITTED` while each `REJECTED` node advances to `DENIED`, and every node that moves to `DENIED` releases its reserved slot by decrementing `reserved_collocations`. On a denial, every node advances from `REJECTED` to `DENIED` and releases its reserved slot.

The decision also finalizes money. For each node that ends in `PERMITTED`, the system creates a recurring ROW rental in `PENDING` status with its estimated amount computed against `decided_at`, as detailed in Section 3.7. The fee invoice is recomputed to its final variant: on a full grant it covers all permitted nodes; on a partial grant it covers only the permitted nodes, and if the net amount already collected (payments captured minus refunds captured) exceeds the newly assessed amount, a refund is created for the excess; on a denial the assessed amount is zero, so any net amount collected is refunded in full and the invoice moves to `REFUNDED`.

### 3.6. Shot-Clock Expiry and Deemed Grants

If an authority sits on an application past its deadline, the applicant is protected by a deemed grant. A `PlatformAdmin` may ask the system to evaluate the deadline of an undecided application — one currently in `SUBMITTED`, `INCOMPLETE`, or `UNDER_REVIEW`. The deemed grant only fires when the current clock is strictly past the `shot_clock_deadline`; at a clock exactly equal to the deadline the request is refused with `ERR_SHOT_CLOCK_NOT_EXPIRED`. When the clock has strictly passed the deadline, the application moves to `DEEMED_GRANTED`: `decided_at` is set to the current clock, every node that is not already `REJECTED`, `DENIED`, or `WITHDRAWN` advances to `PERMITTED`, a `PENDING` recurring rental is created for each such permitted node using `decided_at` as the estimate reference, and the fee invoice is recomputed to its final variant over the permitted nodes. The application's version advances.

### 3.7. Fees, Payments, and Recurring ROW Rentals

Every submitted application carries exactly one fee invoice, retrievable as a zero-or-one list. At submission the invoice is raised with `fee_variant` of `PROVISIONAL`, `status` of `OPEN`, and `assessed_amount_cents` computed over all filed nodes; at decision it is recomputed to `FINAL` over the surviving permitted nodes. The application fee is a per-node sum. Each node's base fee is 95,066 cents for a new pole and 47,533 cents for a collocation. To that base a ROW administrative technology surcharge of 8.25 percent is applied, and the surcharged per-node fee is rounded half-up to whole cents. The invoice's `assessed_amount_cents` is the sum of those individually rounded per-node fees — each node rounded before summation, per Section 2.8. The provisional variant counts every filed node; the final variant counts only nodes ending in `PERMITTED`, so denied or withdrawn nodes drop out and can lower the total.

An invoice also tracks `paid_amount_cents` (the gross sum of captured payments), `refunded_amount_cents` (the gross sum of captured refunds), and a computed `outstanding_amount_cents` equal to `assessed_amount_cents` minus `paid_amount_cents` plus `refunded_amount_cents`. An `Applicant` records a payment against the invoice — the payment's `fee_invoice_id` identifies that invoice — by supplying `amount_cents`, an optional `payment_type` that defaults to `PAYMENT`, and the mandatory `expected_fee_invoice_version`. The amount must be a positive number of cents that does not exceed the current outstanding balance, otherwise `ERR_INVALID_PAYMENT_AMOUNT`; and the version must match, otherwise `ERR_STALE_VERSION`. A recorded payment is captured immediately: its `status` is `CAPTURED`, the invoice's `paid_amount_cents` grows by the amount, the outstanding balance is recomputed, and when the outstanding balance reaches zero the invoice status becomes `PAID`. Recording a payment advances the invoice's version. Refund payments, which carry `payment_type` of `REFUND`, are created by the system during partial grants, denials, and withdrawals rather than by the applicant. The payments on an invoice can be listed.

Each permitted node accrues a recurring ROW rental for occupying public land. A rental's `estimated_amount_cents` is set provisionally at grant and its `actual_amount_cents` at activation; it also records the `billing_year`, a half-open `period_start` (inclusive) and `period_end` (exclusive), and moves through `PENDING`, `ACTIVE`, `EXPIRED`, and `VOID`. The rental amount prorates a full annual charge of 27,000 cents per node over the remaining part of the reference date's calendar year. Concretely: take the calendar year of the reference date; let the number of days in that year be its actual length (365, or 366 in a leap year); count the remaining days as the number of days from the reference date's calendar date through December 31 inclusive of both endpoints; then the amount is 27,000 multiplied by remaining days divided by days in year, rounded half-up to whole cents. The estimate variant uses the application's `decided_at` as the reference (or, for a rental created when an appeal is overturned, the current clock). The actual variant, computed at activation, uses the activation clock as the reference; because activation happens on or after the decision, fewer days remain and the actual amount is never greater than the estimate.

A `PlatformAdmin` may renew an `ACTIVE` rental into a new period by supplying `period_start` and `period_end`. The requested half-open interval must not overlap any non-`VOID` rental of the same node, though intervals that merely touch at an endpoint are allowed; an overlap is rejected with `ERR_RENTAL_PERIOD_OVERLAP`. On renewal the current rental moves to `EXPIRED` and a new `ACTIVE` rental is created for the requested period, with its `billing_year` set to the calendar year of `period_start`, its `actual_amount_cents` prorated using `period_start` as the reference date per the formula above, and its `estimated_amount_cents` set to 0; this new `ACTIVE` rental is the resource returned, with `201 Created`. A node's rentals can be listed.

### 3.8. Inspection and Activation

Before a permitted node can be switched on, it must be physically inspected. An `Inspector` records an inspection carrying an `outcome` of `PASS` or `FAIL`, optionally with a `scheduled_start`, a `scheduled_end`, and free-text `notes`; the record captures the `inspector_user_id` from `X-User-ID`. A node may accumulate several inspections; a node's inspections can be listed.

Activation is the terminal step that brings a node into service, performed by an `Inspector`. It is admissible only when the node is `PERMITTED`, its latest inspection outcome is `PASS` (otherwise `ERR_INSPECTION_NOT_PASSED`), and the application's fee invoice is fully paid with an `outstanding_amount_cents` of zero (otherwise `ERR_INVOICE_UNPAID`). On activation the node advances from `PERMITTED` to `ACTIVATED` and its version advances. Its `PENDING` rental moves to `ACTIVE` with `actual_amount_cents` computed against the activation clock, `period_start` set to the current clock, `period_end` set to January 1 of the following year, and `billing_year` set to the current calendar year. The structure accounting also shifts: `reserved_collocations` is decremented by one and `active_collocations` is incremented by one, converting the held reservation into an active occupancy.

### 3.9. Withdrawal, Denial, and Appeals

An `Applicant` may withdraw or surrender its own application from any of `DRAFT`, `SUBMITTED`, `INCOMPLETE`, `UNDER_REVIEW`, `GRANTED`, or `PARTIALLY_GRANTED`, moving it to `WITHDRAWN`. Withdrawal cascades: every non-terminal node — that is, every node not already `ACTIVATED`, `DENIED`, or `WITHDRAWN` — moves to `WITHDRAWN`; each withdrawn node that held a reserved slot releases it by decrementing `reserved_collocations`; each withdrawn node's `PENDING` rental moves to `VOID`; and if a fee invoice exists and its net collected amount (payments minus refunds) is positive, a refund for the full net is created and the invoice moves to `REFUNDED`. The application's version advances.

When an application is `DENIED` or `PARTIALLY_GRANTED`, its owner may appeal it, supplying the `grounds` for the appeal; filing moves the application to `UNDER_APPEAL` and creates an appeal in `FILED` status. Appealing an application in any other state is rejected with `ERR_APPEAL_NOT_ALLOWED`. The appeals of an application can be listed.

An `Approver` decides a filed appeal by supplying an `uphold` flag and optional `decision_notes`, subject to the same four-eyes rule as a batch decision: the deciding approver must not be the `reviewer_user_id` of any review under this application, or the decision is blocked with `ERR_SEGREGATION_OF_DUTIES`. Deciding not to uphold overturns the denial: the appeal moves to `OVERTURNED` with its `decided_by_user_id` set from `X-User-ID`, the application moves from `UNDER_APPEAL` to `APPEAL_GRANTED`, each previously `DENIED` node advances to `PERMITTED` and receives a new `PENDING` recurring rental estimated against the current clock, and the fee invoice is recomputed to its final variant over the enlarged permitted set. Deciding to uphold sustains the denial: the appeal moves to `UPHELD` with its `decided_by_user_id` recorded, and the application moves to `APPEAL_DENIED`. Either appeal decision advances the appeal's version. The states `GRANTED`, `DEEMED_GRANTED`, `WITHDRAWN`, `APPEAL_GRANTED`, and `APPEAL_DENIED` are terminal for an application.

## 4. Endpoint Definitions

Operations that create a brand-new resource return `201 Created`; operations that modify or transition an existing resource return `200 OK`. The specific request and response bodies for each endpoint are described in the Section 3 narratives; the table below lists only the method, path, purpose, and authorized roles.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/applicants` | Register a wireless provider | PlatformAdmin |
| GET | `/applicants/{id}` | Fetch an applicant | PlatformAdmin, Applicant |
| POST | `/applicants/{id}/sign-master-agreement` | Execute the ROW master license agreement | Applicant |
| POST | `/support-structures` | Create a support structure | PlatformAdmin, Applicant |
| GET | `/support-structures/{id}` | Fetch a support structure | PlatformAdmin, Applicant, ROWReviewer |
| POST | `/support-structures/{id}/retire` | Retire an ACTIVE structure holding no slots | PlatformAdmin |
| GET | `/support-structures/{id}/nodes` | List nodes attached to this structure | PlatformAdmin, Applicant, ROWReviewer |
| POST | `/row-segments` | Create a right-of-way segment | PlatformAdmin |
| GET | `/row-segments/{id}` | Fetch a ROW segment | PlatformAdmin, Applicant, ROWReviewer |
| GET | `/row-segments/{id}/nodes` | List nodes in this segment | PlatformAdmin, Applicant, ROWReviewer |
| POST | `/applications` | Create a draft batch application | Applicant |
| GET | `/applications/{id}` | Fetch an application | PlatformAdmin, Applicant, ROWReviewer, AestheticReviewer, Approver, Inspector |
| GET | `/applications` | List applications, optionally filtered | PlatformAdmin, Applicant |
| POST | `/applications/{id}/nodes` | Add a node to a DRAFT application | Applicant |
| GET | `/applications/{id}/nodes` | List nodes of an application | PlatformAdmin, Applicant, ROWReviewer, AestheticReviewer, Approver, Inspector |
| GET | `/nodes/{id}` | Fetch a node | PlatformAdmin, Applicant, ROWReviewer, AestheticReviewer, Approver, Inspector |
| POST | `/applications/{id}/submit` | Submit the batch; start the shot clock and assess the provisional fee | Applicant |
| POST | `/applications/{id}/completeness-review` | Record a completeness determination | ROWReviewer |
| GET | `/applications/{id}/incompleteness-notices` | List incompleteness notices | PlatformAdmin, Applicant, ROWReviewer |
| POST | `/applications/{id}/cure` | Cure the latest incompleteness notice | Applicant |
| POST | `/nodes/{id}/design-review` | Record the ROW/design-standard review (OCC on structure) | ROWReviewer |
| POST | `/nodes/{id}/aesthetic-review` | Record the aesthetic/historic review | AestheticReviewer |
| GET | `/nodes/{id}/reviews` | List a node's review records | PlatformAdmin, Applicant, ROWReviewer, AestheticReviewer, Approver |
| POST | `/applications/{id}/decision` | Issue the batch decision (four-eyes SoD) | Approver |
| POST | `/applications/{id}/evaluate-deadline` | Deem granted if the shot clock has strictly expired | PlatformAdmin |
| POST | `/nodes/{id}/inspection` | Record a physical inspection | Inspector |
| GET | `/nodes/{id}/inspections` | List a node's inspections | PlatformAdmin, Applicant, Inspector |
| POST | `/nodes/{id}/activate` | Activate a permitted, inspected, fully-paid node | Inspector |
| GET | `/nodes/{id}/rentals` | List a node's ROW rentals | PlatformAdmin, Applicant, Inspector |
| POST | `/rentals/{id}/renew` | Roll an ACTIVE rental into the next period | PlatformAdmin |
| POST | `/fee-invoices/{id}/payments` | Record a payment against an invoice (OCC on invoice) | Applicant |
| GET | `/fee-invoices/{id}` | Fetch an invoice | PlatformAdmin, Applicant |
| GET | `/fee-invoices/{id}/payments` | List payments on an invoice | PlatformAdmin, Applicant |
| GET | `/applications/{id}/fee-invoice` | Fetch the application's invoice as a list | PlatformAdmin, Applicant |
| POST | `/applications/{id}/appeal` | Appeal a denial or partial grant | Applicant |
| GET | `/applications/{id}/appeals` | List appeals of an application | PlatformAdmin, Applicant, Approver |
| POST | `/appeals/{id}/decision` | Overturn or uphold an appeal (four-eyes SoD) | Approver |
| POST | `/applications/{id}/withdraw` | Withdraw or surrender an application | Applicant |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_APPLICANT_NOT_FOUND` | 404 |
| `ERR_APPLICATION_NOT_FOUND` | 404 |
| `ERR_NODE_NOT_FOUND` | 404 |
| `ERR_SUPPORT_STRUCTURE_NOT_FOUND` | 404 |
| `ERR_ROW_SEGMENT_NOT_FOUND` | 404 |
| `ERR_FEE_INVOICE_NOT_FOUND` | 404 |
| `ERR_RENTAL_NOT_FOUND` | 404 |
| `ERR_APPEAL_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_MASTER_AGREEMENT_REQUIRED` | 422 |
| `ERR_NO_NODES` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_NODES_PENDING_REVIEW` | 409 |
| `ERR_STRUCTURE_NOT_ACTIVE` | 409 |
| `ERR_PAVEMENT_MORATORIUM` | 409 |
| `ERR_STRUCTURE_CAPACITY_EXCEEDED` | 409 |
| `ERR_RENTAL_PERIOD_OVERLAP` | 409 |
| `ERR_INSPECTION_NOT_PASSED` | 409 |
| `ERR_INVOICE_UNPAID` | 402 |
| `ERR_INVALID_PAYMENT_AMOUNT` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SHOT_CLOCK_NOT_EXPIRED` | 409 |
| `ERR_APPEAL_NOT_ALLOWED` | 409 |
