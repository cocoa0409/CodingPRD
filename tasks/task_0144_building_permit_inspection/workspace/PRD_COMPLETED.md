# Building Permit & Inspection API — Product Requirements Document

## 1. Introduction

Municipal building departments live and die by the integrity of a single chain of custody: a project must be reviewed before it is permitted, permitted before it is built, inspected before it is occupied, and accounted for at every step. This API models that chain of custody for a jurisdiction's permit-and-inspection authority. It governs the full arc of a construction project — from the moment an owner or their agent files a permit application, through iterative plan review and correction cycles, valuation-driven fee assessment and payment, field inspection scheduling against inspector availability, the issuance of a certificate of occupancy, and the eventual closeout, renewal, or expiration of the permit.

The domain is deliberately unforgiving about *who* may act and *when*. A plan reviewer who signs off on a design must not also be the field inspector who clears the finished building; a contractor whose license has lapsed or whose surety bond is unverified cannot have a permit issued in their name; and a stop-work order, once posted, freezes field activity regardless of where the paperwork stands. These are not incidental rules — they are the regulatory backbone of the system, and the API exists to make them enforceable, auditable, and impossible to circumvent through ordinary request sequences. Every consequential change a permit undergoes is recorded as an immutable audit event, so the department can reconstruct exactly what happened and in what order.

This document specifies the complete behavioral contract: the resources, their lifecycles, the fee mathematics, the validation and concurrency rules, and the precise error semantics an implementation must honor.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and structural conventions that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly five roles: `Applicant`, `PermitClerk`, `PlanReviewer`, `Inspector`, and `BuildingOfficial`. A request that omits either header, or that presents an `X-User-Role` value outside this set, is rejected with `ERR_UNAUTHENTICATED`. A syntactically valid request whose role is not authorized for the requested operation is rejected with `ERR_FORBIDDEN_ROLE`.

The five roles divide into two identity models. When `X-User-Role` is `PlanReviewer`, `X-User-ID` is the `id` of the acting `PlanReviewer` entity; ownership checks on any resource that references a `PlanReviewer` compare that resource's reviewer foreign key to `X-User-ID`. Likewise, when `X-User-Role` is `Inspector`, `X-User-ID` is the `id` of the acting `Inspector` entity, and ownership checks on any resource that references an `Inspector` compare the resource's inspector foreign key to `X-User-ID`. These two are the segregation-of-duties anchors: the system must be able to tell, from the headers alone, which credentialed individual performed each design approval and each field sign-off.

The remaining three roles carry opaque identities. When `X-User-Role` is `Applicant`, `PermitClerk`, or `BuildingOfficial`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record such an identifier in an audit detail, but it does not compare it to any entity's `id` for ownership purposes.

`BuildingOfficial` is the configuring authority: it registers jurisdictions, inspectors, and plan reviewers, posts and lifts stop-work orders, runs the expiration sweep, finalizes permits, revokes certificates, and drives the test clock. `PermitClerk` is counter staff that may register contractors, create permits on an applicant's behalf, record payments, schedule inspections, resolve corrections, and — exclusively — issue and renew permits. `Applicant` is the owner or agent who files permits, withdraws and resubmits them, pays fees, schedules and cancels inspections, and — exclusively among the operator-style roles — resolves correction notices. `PlanReviewer` opens reviews, attaches correction notices, and decides reviews. `Inspector` publishes its own availability slots and records inspection results.

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

List endpoints accept two query parameters. `limit` caps the number of records returned; it defaults to 10, may be no smaller than 1, and may be no larger than 100 — a supplied `limit` below 1 is clamped up to 1 and one above 100 is clamped down to 100, rather than rejected, while a non-integer `limit` is rejected with `ERR_INVALID_REQUEST`. `offset` skips a number of leading records and defaults to 0; a negative `offset` is clamped to 0 and a non-integer `offset` is rejected with `ERR_INVALID_REQUEST`. Unless a specific endpoint states otherwise, list results are ordered by their creation timestamp in ascending order — that is, oldest first. Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `total_count` reflects the full size of the filtered collection before the page window is applied and `has_more` indicates whether records remain beyond the current page.

### 2.4. Common Resource Properties and Versioning

Every resource is assigned a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp recorded as an ISO 8601 UTC instant with three fractional digits. Most resources additionally carry an `updated_at` timestamp, refreshed on every mutation to the same ISO 8601 UTC format, and an integer `version` that begins at its initial value on creation and increases by one with each mutation of the resource.

Two resource kinds are deliberately leaner. A `FeePayment` is append-only — once recorded it is never edited — and a `PermitEvent` is an immutable audit record. Both therefore carry only `id` and `created_at`; neither exposes `updated_at` nor `version`. Every other resource in the system carries the full set of `id`, `created_at`, `updated_at`, and `version`.

Whenever the specification below says a transition or recompute "bumps the version," it means the `PermitApplication` (or other mutated resource) has its `version` incremented by one and its `updated_at` refreshed. Derived fields recomputed on a `PermitApplication` — such as the fee fields, `amount_paid`, and `balance_due` — are part of the resource's state, and any operation that changes them is a mutation that advances `version` and `updated_at`.

### 2.5. Nested Resource Retrieval and Existence Ordering

Several operations address a resource through a path that names a parent and then acts on it — for example, recording a payment against a specific permit, or scheduling an inspection under a specific permit. When a request references resource identifiers, the system validates their existence left to right, rejecting at the first identifier that does not resolve to a stored resource. Each resource kind has its own not-found error: a missing permit yields `ERR_PERMIT_NOT_FOUND`, a missing contractor `ERR_CONTRACTOR_NOT_FOUND`, a missing jurisdiction `ERR_JURISDICTION_NOT_FOUND`, a missing plan review `ERR_REVIEW_NOT_FOUND`, a missing correction notice `ERR_CORRECTION_NOT_FOUND`, a missing inspection `ERR_INSPECTION_NOT_FOUND`, a missing inspection slot `ERR_SLOT_NOT_FOUND`, a missing stop-work order `ERR_SWO_NOT_FOUND`, and a missing certificate of occupancy `ERR_CO_NOT_FOUND`. A handful of resource kinds have no dedicated not-found error in the catalogue and reuse the nearest one: fetching an inspector that does not resolve yields `ERR_INSPECTION_NOT_FOUND`, fetching a plan reviewer that does not resolve — including the `reviewer_id` referenced when opening a review — yields `ERR_REVIEW_NOT_FOUND`, and fetching a fee payment that does not resolve yields `ERR_PERMIT_NOT_FOUND`. Existence checks (priority three) run after authentication and authorization but before any body-shape, state, or business validation.

### 2.6. Request Validation Order

When a single request could fail several checks, the order in which the system evaluates them is fixed, and the first failure is the one reported. The ordering, from highest precedence to lowest, is: first authentication of the headers (`ERR_UNAUTHENTICATED`); then role authorization (`ERR_FORBIDDEN_ROLE`); then existence of every referenced resource, left to right (the resource-specific not-found errors above); then body well-formedness — required fields present, correctly typed, and any enum-valued field carrying a value from its declared set (`ERR_INVALID_REQUEST`); then uniqueness constraints on creation (`ERR_DUPLICATE_LICENSE`); then the target's state suitability for the requested transition (`ERR_INVALID_STATE`); then the optimistic-concurrency version check on the two version-guarded operations (`ERR_STALE_PERMIT_VERSION`); and finally the domain-specific business rules. Among the business rules themselves the relative order is: the assigned-reviewer ownership check (`ERR_NOT_ASSIGNED_REVIEWER`), the segregation-of-duties check (`ERR_SEGREGATION_OF_DUTIES`), the contractor verification check (`ERR_CONTRACTOR_UNVERIFIED`), the active-stop-work gate (`ERR_WORK_STOPPED`), the open-corrections gate (`ERR_OPEN_CORRECTIONS`), the rough-before-final gate (`ERR_ROUGH_NOT_PASSED`), the slot-window containment check (`ERR_OUTSIDE_SLOT_WINDOW`), the inspector double-booking check (`ERR_INSPECTOR_DOUBLE_BOOKED`), the slot-capacity check (`ERR_SLOT_CAPACITY_FULL`), the zero-balance gate (`ERR_BALANCE_DUE`), and the certificate-present gate (`ERR_NO_CERTIFICATE`). A check earlier in this order masks a later one when both would fail.

### 2.7. Cascades, Reconciliation, and Audit Trail

Many operations in this domain mutate more than the resource named in the request. When a permit expires or a stop-work order is posted, every still-scheduled inspection for that permit is cancelled, and each cancellation frees the capacity it had consumed on its inspection slot. When a stop-work order is posted, any standing certificate of occupancy for the permit is also revoked. These secondary effects are not optional: an implementation that performs the primary state change but omits a cascade has not satisfied the contract. Each such cascade is a mutation of the affected resource that refreshes its `updated_at` and, where the resource carries one, advances its `version`.

The system keeps an append-only audit log of `PermitEvent` records. Every `PermitApplication` lifecycle transition appends an event, as do stop-work issuance and lifting, certificate issuance and revocation, and inspection results. Each `PermitEvent` records the `permit_id` it pertains to, an `event_type` drawn from the audit vocabulary, and a human-readable `detail`. The recognized `event_type` values are `SUBMITTED`, `REVIEW_OPENED`, `CORRECTIONS_REQUIRED`, `RESUBMITTED`, `APPROVED`, `ISSUED`, `INSPECTION_SCHEDULED`, `INSPECTION_PASSED`, `INSPECTION_FAILED`, `STOP_WORK_ISSUED`, `STOP_WORK_LIFTED`, `CO_ISSUED`, `CO_REVOKED`, `RENEWED`, `EXPIRED`, and `WITHDRAWN`.

### 2.8. Monetary Precision and Rounding

All monetary quantities — assessed valuations, fees, payments, and balances — are carried as numbers and rounded to exactly two decimal places using the round-half-up convention (a value exactly halfway between two representable amounts rounds up, away from zero). Where a calculation prescribes a specific rounding order, that order is binding and is spelled out in the relevant business-logic subsection; the general rule is that each named component is rounded before it is combined with another, rather than rounding only the final sum. Datetime fields are carried as ISO 8601 UTC instants at millisecond resolution.

### 2.9. Optimistic Concurrency Control on Issuance and Renewal

Two permit operations are guarded against acting on a stale view of the permit: issuing an approved permit and renewing an expired one. Each requires the caller to supply `expected_permit_application_version`, carrying the `version` of the `PermitApplication` the caller last observed. This field is mandatory on these two operations and is not accepted — and has no effect — on any other endpoint.

For issuance, the request must carry `expected_permit_application_version` equal to the target permit's current `version`. If another clerk has already advanced the permit's version since the caller last read it — for instance by legitimately driving the permit from `APPROVED` to `ISSUED`, which bumps the version — the stale request is rejected with `ERR_STALE_PERMIT_VERSION` (HTTP 412) rather than attempting a second issuance. Renewal behaves identically: its `expected_permit_application_version` must match the permit's current `version`, and a mismatch — for instance because another clerk already renewed the permit, moving it from `EXPIRED` to `ISSUED`, adding a renewal fee, and bumping the version — is rejected with `ERR_STALE_PERMIT_VERSION` (HTTP 412), so the renewal fee can never be applied twice. This rejection is framed entirely in terms of the observed-versus-current version: it does not depend on requests arriving together, and it fires whenever the supplied version no longer matches.

### 2.10. Contractor Verification Posture

A contractor's eligibility to have permits issued or renewed is summarized by a derived `verification_status`, recomputed whenever the contractor is read and evaluated as a precondition of both issuance and renewal. The status is `VERIFIED` only when both of two independent legs hold, and `FAILED` otherwise. The license leg holds when `license_status` is `ACTIVE` and the current clock instant is strictly before `license_expiry` — a contractor whose clock has reached or passed `license_expiry` fails the license leg even if the status still reads `ACTIVE`, and so does any contractor whose `license_status` is `SUSPENDED` or `EXPIRED`. The bond leg holds when `bond_status` is `VERIFIED` and `bond_amount` is at least the required bond floor of $15,000; a bond of exactly $15,000 satisfies the floor, while any lesser amount, or a `bond_status` of `UNVERIFIED` or `REVOKED`, fails the bond leg. The two legs are evaluated independently — either one failing drives `verification_status` to `FAILED` regardless of the other — and only when both hold does the contractor read `VERIFIED`.

## 3. Business Logic & Workflows

### 3.1. Configuring the Reference Data: Jurisdictions, Contractors, and Personnel

Before any permit can be filed, a `BuildingOfficial` establishes the jurisdiction that supplies the fee schedule. A jurisdiction is created with a `name`, a `code_edition` label such as the adopted building-code edition, and a set of fee parameters: `valuation_fee_rate_per_1000`, the dollars of base fee charged per $1,000 of valuation; `square_foot_rate`, the construction value imputed per square foot; `plan_review_fee_pct`, the plan-review surcharge expressed as a fraction of the base fee; and `minimum_permit_fee`, the floor applied to the base fee. All four of these must be zero or greater. Two further parameters are optional at creation: `renewal_fee_pct`, the renewal charge as a fraction of the original total fee, which defaults to 0.5 when omitted; and `permit_valid_days`, the number of days a permit stays valid from issuance, which must be at least 1 and defaults to 180 when omitted.

A contractor is registered with a `business_name`, a `license_number`, a `license_expiry` instant, and a `bond_amount`. The `license_number` must be unique across all contractors — a collision is rejected with `ERR_DUPLICATE_LICENSE`. Two fields are optional and carry defaults: `license_status`, one of `ACTIVE`, `SUSPENDED`, or `EXPIRED`, defaulting to `ACTIVE`; and `bond_status`, one of `VERIFIED`, `UNVERIFIED`, or `REVOKED`, defaulting to `UNVERIFIED`. The `bond_amount` must be zero or greater. The derived `verification_status` is computed at registration from these inputs per the verification posture described above. A contractor's standing may later be amended — adjusting `license_status`, `license_expiry`, `bond_amount`, or `bond_status` in any combination — and each such amendment triggers a fresh recomputation of `verification_status`.

Field and review personnel are registered by a `BuildingOfficial`. An inspector carries a `full_name` and a `badge_number` that must be unique across inspectors; a plan reviewer carries a `full_name` and a `cert_number` that must be unique across plan reviewers. In both cases a duplicate identifier is rejected with `ERR_DUPLICATE_LICENSE`. These two entities back the `Inspector` and `PlanReviewer` roles respectively, so their `id` values are exactly the `X-User-ID` values those credentialed users present.

### 3.2. Filing a Permit and Assessing Its Fee

An `Applicant`, or a `PermitClerk` acting on their behalf, files a permit by naming the `jurisdiction_id` and `contractor_id` it belongs to, the `work_class` — one of `NEW_CONSTRUCTION`, `ADDITION`, `ALTERATION`, or `REPAIR` — and the `fee_method`, which selects how the fee is computed and is one of `VALUATION` or `SQUARE_FOOT`. Two further inputs are conditional: `declared_valuation`, the owner-declared project value used under the valuation method, and `floor_area_sqft`, the conditioned floor area used under the square-foot method. Each defaults to 0 and each must be zero or greater. A freshly filed permit enters `status` `SUBMITTED`, takes `work_status` `NOT_STARTED`, and has its first audit event appended with `event_type` `SUBMITTED`.

At filing time — and on any later recompute of the fee — the system first establishes the `assessed_valuation`, the figure the fee is actually charged against. Under the valuation method the assessed valuation is the `declared_valuation` taken verbatim. Under the square-foot method the assessed valuation is instead imputed as the `floor_area_sqft` multiplied by the jurisdiction's `square_foot_rate`, and the `declared_valuation` is ignored entirely. The result is rounded to two decimal places, round half up.

From the assessed valuation the system derives the `base_permit_fee` using a progressive, marginal-tier schedule — each band of valuation is charged at its own rate, rather than the whole valuation being charged at a single rate. Let the jurisdiction's `valuation_fee_rate_per_1000` be the base per-thousand rate. The first $50,000 of assessed valuation forms the first tier and is charged at the full base rate. The portion of valuation above $50,000 and up to $500,000 — at most $450,000 of value — forms the second tier and is charged at 80 percent of the base rate. Any valuation above $500,000 forms the third tier and is charged at 60 percent of the base rate. For each tier, the dollars of fee are the tier's dollars of valuation divided by 1,000, multiplied by the base per-thousand rate, multiplied by that tier's multiplier (1.00, 0.80, and 0.60 respectively); the three tier contributions are summed to form a raw fee. That raw fee is rounded to two decimal places, round half up, and then the jurisdiction's `minimum_permit_fee` floor is applied — the base permit fee is the greater of the rounded raw fee and the minimum, with the floor applied only after the rounding.

The `plan_review_fee` surcharge is then computed from the already-rounded base permit fee: it is the base permit fee multiplied by the jurisdiction's `plan_review_fee_pct`, rounded to two decimal places, round half up. The `total_permit_fee` is the sum of the rounded base permit fee and the rounded plan-review surcharge, itself rounded to two decimal places. This per-component rounding order is binding: round the base, round the surcharge of the rounded base, then sum — do not compute the total as a single rounding of the base scaled by one plus the percentage.

### 3.3. Paying the Fee and Tracking the Balance

Payments are recorded against a permit as append-only `FeePayment` records. A payment names an `amount`, which must be strictly greater than zero — a non-positive amount is rejected with `ERR_INVALID_REQUEST` — and carries a `payment_status` of either `CLEARED` or `VOID`, defaulting to `CLEARED` when omitted. The permit's `amount_paid` is the sum of the `amount` of every `FeePayment` for that permit whose `payment_status` is `CLEARED`; payments marked `VOID` are excluded from the total. The figure is maintained to two decimal places, round half up, and is recomputed whenever a payment is recorded and before any balance check.

The permit's `balance_due` is the `total_permit_fee` plus any `accrued_renewal_fees` minus the `amount_paid`, rounded to two decimal places, round half up. The `accrued_renewal_fees` field starts at 0 and accumulates renewal charges as the permit is renewed. A `balance_due` of exactly zero is what gates issuance and finalization; a positive balance blocks both, while a negative balance — an overpayment — does not block. Recording a payment is a mutation of the permit that recomputes `amount_paid` and `balance_due` and refreshes the permit's audit-relevant state accordingly.

### 3.4. Plan Review: The Correction Cycle

Once a permit is on file, a `PlanReviewer` opens plan review on it, supplying the `reviewer_id` who will own the review. Opening a review is permitted only while the permit's `status` is `SUBMITTED` and only when no `OPEN` plan review already exists for that permit; otherwise the attempt is rejected with `ERR_INVALID_STATE`. Opening a review moves the permit from `SUBMITTED` to `UNDER_REVIEW`, creates a `PlanReview` whose `review_status` is `OPEN`, whose `decision` is `PENDING`, and whose `cycle_number` captures the permit's current `review_cycle`; it appends a `REVIEW_OPENED` audit event and bumps the permit's version.

The reviewer who owns a review then decides it, and the decision forks. The acting `PlanReviewer` must be the review's own `reviewer_id`; a decision attempted by any other reviewer is rejected with `ERR_NOT_ASSIGNED_REVIEWER`. A decision may be entered only while the review's `review_status` is `OPEN` and the permit's `status` is `UNDER_REVIEW`. On the `APPROVED` branch, the review's `decision` becomes `APPROVED`, its `review_status` becomes `COMPLETED`, the permit advances from `UNDER_REVIEW` to `APPROVED`, the permit's `approving_reviewer_id` is set to this review's `reviewer_id` — the record that later powers the segregation-of-duties check — an `APPROVED` audit event is appended, and the permit's version is bumped. The `APPROVED` branch is permitted only when the permit's `open_correction_count` is zero; an approval attempted while corrections remain open is rejected with `ERR_OPEN_CORRECTIONS`.

On the `CORRECTIONS` branch, the reviewer must have attached at least one open correction notice to the review; a corrections decision with no open notice on that review is rejected with `ERR_OPEN_CORRECTIONS`. When valid, the review's `decision` becomes `CORRECTIONS` and its `review_status` becomes `COMPLETED`, the permit moves from `UNDER_REVIEW` to `CORRECTIONS_REQUIRED`, the permit's `open_correction_count` is recomputed from the open correction notices, a `CORRECTIONS_REQUIRED` audit event is appended, and the permit's version is bumped. The two branches are symmetric in form but divergent in effect: approval clears the way to issuance, while a corrections decision blocks it until every cited item is resolved.

Correction notices are authored against an open review. A `PlanReviewer` attaches a notice to a review whose `review_status` is `OPEN` — attaching to a review that is not open is rejected with `ERR_INVALID_STATE` — providing the `code_section` cited and a `description` of what must be corrected. The notice records its parent `plan_review_id` and `permit_id`, enters `item_status` `OPEN`, and increments the permit's `open_correction_count`. The `Applicant`, or a `PermitClerk`, later resolves a notice; resolution is permitted only while the notice's `item_status` is `OPEN` and the parent permit's `status` is `CORRECTIONS_REQUIRED`. Resolving a notice sets its `item_status` to `RESOLVED`, decrements the permit's `open_correction_count`, and bumps the permit's version.

When all corrections are cleared, the applicant resubmits, re-entering review. Resubmission is permitted only while the permit's `status` is `CORRECTIONS_REQUIRED` and its `open_correction_count` is zero — that is, every correction notice on the latest review has been resolved; a resubmission with any open correction remaining is rejected with `ERR_OPEN_CORRECTIONS`. Resubmitting increments the permit's `review_cycle` by one, opens a fresh `PlanReview` (with `review_status` `OPEN`, `decision` `PENDING`, `cycle_number` equal to the new `review_cycle`, and `reviewer_id` left null since the resubmit names no reviewer), moves the permit from `CORRECTIONS_REQUIRED` back to `UNDER_REVIEW`, appends a `RESUBMITTED` audit event, and bumps the version. This is the cyclic heart of the workflow: a permit may loop `UNDER_REVIEW` → `CORRECTIONS_REQUIRED` → `UNDER_REVIEW` as many times as review demands.

### 3.5. Withdrawing a Permit

Before a permit is ever issued, the applicant — or a clerk on their behalf — may withdraw it outright. Withdrawal is allowed from any pre-issuance status: `SUBMITTED`, `UNDER_REVIEW`, `CORRECTIONS_REQUIRED`, or `APPROVED`. It is not allowed once the permit reaches `ISSUED`; an attempt from `ISSUED` or any later status is rejected with `ERR_INVALID_STATE`. Withdrawing completes any still-open plan review (its `review_status` becomes `COMPLETED`), moves the permit to the terminal `WITHDRAWN` status, appends a `WITHDRAWN` audit event, and bumps the version.

### 3.6. Issuance, Expiration, and Renewal

A `PermitClerk` issues an approved permit, and issuance is the most heavily gated transition in the system. It is permitted only while the permit's `status` is `APPROVED`. The caller must supply `expected_permit_application_version` matching the permit's current `version`, or the request is rejected with `ERR_STALE_PERMIT_VERSION`. The permit's `balance_due` must be exactly zero, or the request is rejected with `ERR_BALANCE_DUE`. The referenced contractor's `verification_status` must be `VERIFIED` — license active and current and bond verified and sufficient — or the request is rejected with `ERR_CONTRACTOR_UNVERIFIED`. When all gates pass, the permit advances from `APPROVED` to `ISSUED`: `issued_at` is set to the current clock instant, `expires_at` is set to `issued_at` plus the jurisdiction's `permit_valid_days` days, `work_status` becomes `ACTIVE`, an `ISSUED` audit event is appended, and the version is bumped.

A permit expires once its validity window elapses. The expiration is driven by a system sweep that a `BuildingOfficial` invokes after advancing the clock past the permit's `expires_at`. Expiration is permitted only while the permit's `status` is `ISSUED`, only when the current clock instant is at or after `expires_at`, and only when no certificate of occupancy with `co_status` `ISSUED` exists for the permit; each of these three preconditions failing — a status other than `ISSUED`, a clock not yet at `expires_at`, or a standing issued certificate — is reported with `ERR_INVALID_STATE`. When it fires, the permit moves from `ISSUED` to `EXPIRED`, its `work_status` is set to `STOPPED`, every inspection for the permit still in `SCHEDULED` status is cancelled — each cancellation freeing the capacity it held on its slot — an `EXPIRED` audit event is appended, and the version is bumped.

An expired permit may be renewed by a `PermitClerk`, returning it to active service. Renewal is permitted only while the permit's `status` is `EXPIRED`, requires `expected_permit_application_version` matching the permit's current `version` (else `ERR_STALE_PERMIT_VERSION`), and requires the contractor's `verification_status` to still be `VERIFIED` (else `ERR_CONTRACTOR_UNVERIFIED`). Renewal computes a renewal charge equal to the `total_permit_fee` multiplied by the jurisdiction's `renewal_fee_pct`, rounded to two decimal places, round half up, and adds that charge to `accrued_renewal_fees` (which feeds back into `balance_due`). It then resets `issued_at` to the current clock and `expires_at` to that instant plus `permit_valid_days` days, sets `work_status` back to `ACTIVE`, appends a `RENEWED` audit event, and bumps the version. The permit thus cycles `ISSUED` → `EXPIRED` → `ISSUED` across renewals.

### 3.7. Scheduling Inspections Against Inspector Availability

An `Inspector`, or a `BuildingOfficial`, publishes availability as an `InspectionSlot`, naming the `inspector_id` it belongs to — the slot simply records this `inspector_id` and does not subject it to an existence check, so slot creation never raises a not-found error on the `inspector_id` (there is no inspector not-found error in the catalogue) — a `window_start` (inclusive) and `window_end` (exclusive) bounding the availability window, and a `max_inspections` aggregate capacity that must be at least 1 and defaults to 1 when omitted; the window end must be strictly after the window start. The slot tracks a derived `booked_count`: the number of `Inspection` rows referencing the slot whose `inspection_status` is `SCHEDULED`, `PASSED`, or `FAILED`. A `CANCELLED` inspection does not count toward the booked count, which is how a cancellation frees capacity.

An `Applicant`, or a `PermitClerk`, schedules an inspection against a permit and a slot, supplying the `slot_id`, the `inspection_type` — one of `ROUGH` or `FINAL` — and the requested interval as `scheduled_start` (inclusive) and `scheduled_end` (exclusive), where the end must be strictly after the start. The new inspection copies its `inspector_id` from the chosen slot, enters `inspection_status` `SCHEDULED`, increments the slot's `booked_count`, and appends an `INSPECTION_SCHEDULED` audit event. Scheduling is subject to a chain of checks. The parent permit's `status` must be `ISSUED`; scheduling against a permit in any other status is rejected with `ERR_INVALID_STATE`. A `FINAL` inspection may not be scheduled unless a `PASSED` `ROUGH` inspection already exists for the permit; absent one, the request is rejected with `ERR_ROUGH_NOT_PASSED`. The requested interval must lie entirely within the chosen slot's window — its start at or after `window_start` and its end at or before `window_end` — or it is rejected with `ERR_OUTSIDE_SLOT_WINDOW`. The slot's inspector must not already hold an inspection whose interval overlaps the requested one — considering every inspection that names this inspector (across all of that inspector's slots) whose `inspection_status` is `SCHEDULED`, `PASSED`, or `FAILED`, while a `CANCELLED` inspection is ignored and its interval is free to reuse; overlap is judged on half-open intervals, so two intervals that merely touch at an endpoint do not overlap, while any genuine overlap is rejected with `ERR_INSPECTOR_DOUBLE_BOOKED`. Finally, the slot's `booked_count` must be strictly less than its `max_inspections` before another booking is added; a full slot is rejected with `ERR_SLOT_CAPACITY_FULL`.

A scheduled inspection may be cancelled by the `Applicant` or a `PermitClerk` while it is still `SCHEDULED`. Cancellation sets `inspection_status` to `CANCELLED` and decrements the slot's `booked_count`, returning the slot to the capacity it had before the booking — the same compensation the expiration and stop-work cascades rely on.

### 3.8. Recording Inspection Results and Issuing the Certificate

An `Inspector` records the result of a scheduled inspection by supplying an `outcome` of either `PASS` or `FAIL`, and the outcome forks. A result may be entered only while the inspection's `inspection_status` is `SCHEDULED` and the parent permit's `status` is `ISSUED`. It is further gated on field activity: if an `ACTIVE` stop-work order stands against the permit — equivalently, the permit's `work_status` is `STOPPED` — no result may be recorded, and the attempt is rejected with `ERR_WORK_STOPPED`.

On a `PASS` outcome, the inspection's `inspection_status` becomes `PASSED` and an `INSPECTION_PASSED` audit event is appended. A `FINAL` inspection carries two extra gates before it may pass: a `PASSED` `ROUGH` inspection must already exist for the permit (else `ERR_ROUGH_NOT_PASSED`), and the acting inspector's `id` must differ from the permit's `approving_reviewer_id` — the plan reviewer who approved the design may not also field-sign the final inspection, and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES`. When a `FINAL` inspection passes, the system cascades the creation of a `CertificateOfOccupancy`: the new certificate records the `permit_id`, sets its `final_inspection_id` to the passing inspection, takes `co_type` `FINAL` and `co_status` `ISSUED`, and its creation appends a `CO_ISSUED` audit event. This certificate is what later unlocks finalization.

On a `FAIL` outcome, the inspection's `inspection_status` becomes `FAILED` and an `INSPECTION_FAILED` audit event is appended. A failed inspection is not terminal: the applicant may schedule a fresh inspection of the same type to try again. There is no segregation-of-duties or rough-precedence gate on recording a failure beyond the scheduled-state and issued-permit conditions; those extra gates apply to a `FINAL` pass.

### 3.9. Stop-Work Orders and Certificate Revocation

A `BuildingOfficial` halts field activity by posting a `StopWorkOrder` against a permit, naming the `reason` work was stopped. A stop-work order may be posted only while the permit's `status` is `ISSUED` and its `work_status` is `ACTIVE`; otherwise the attempt is rejected with `ERR_INVALID_STATE`. Posting the order creates a `StopWorkOrder` with `order_status` `ACTIVE`, drives the permit's `work_status` from `ACTIVE` to `STOPPED`, cancels every inspection for the permit still in `SCHEDULED` status — each cancellation freeing its slot's capacity — revokes any standing certificate of occupancy for the permit (its `co_status` moving from `ISSUED` to `REVOKED`, with a `CO_REVOKED` audit event), and appends a `STOP_WORK_ISSUED` audit event. While such an order stands, result entry and finalization are both blocked with `ERR_WORK_STOPPED`.

The same official lifts a stop-work order once the cause is cleared. Lifting is permitted only while the order's `order_status` is `ACTIVE`. Lifting sets the order's `order_status` to `LIFTED`, appends a `STOP_WORK_LIFTED` audit event, and — provided no other stop-work order for the permit remains `ACTIVE` — returns the permit's `work_status` to `ACTIVE`. A certificate of occupancy may also be revoked directly by a `BuildingOfficial`; revocation is permitted only while the certificate's `co_status` is `ISSUED`, sets it to `REVOKED`, and appends a `CO_REVOKED` audit event.

### 3.10. Closing Out the Permit

The final act in a permit's life is closeout, performed by a `BuildingOfficial`. Finalization is permitted only while the permit's `status` is `ISSUED`. It requires that the permit's `work_status` not be `STOPPED` — an active stop-work order blocks closeout with `ERR_WORK_STOPPED`. It then requires the permit's `balance_due` to be exactly zero, or the attempt is rejected with `ERR_BALANCE_DUE`. And finally it requires a standing certificate of occupancy: a `CertificateOfOccupancy` with `co_status` `ISSUED` must exist for the permit, or the attempt is rejected with `ERR_NO_CERTIFICATE` — consistent with the §2.6 ordering, the zero-balance gate is evaluated before the certificate-present gate, so a permit with both a positive balance and no certificate reports `ERR_BALANCE_DUE`. When all conditions hold, the permit moves from `ISSUED` to the terminal `FINALED` status, a closeout audit event with `event_type` `ISSUED` is appended (closeout reuses the `ISSUED` event vocabulary rather than introducing a distinct closeout type), and the version is bumped; the permit's `work_status` is left as it stands. `FINALED` and `WITHDRAWN` are the two terminal resting states of a permit.

### 3.11. Reading the Record and Driving the Clock

Every resource is independently fetchable by its identifier, and the major collections are listable with filters. Permits may be filtered by `contractor_id`, `jurisdiction_id`, `approving_reviewer_id`, or `status`; payments by `permit_id`; plan reviews by `permit_id` or `reviewer_id`; correction notices by `plan_review_id` or `permit_id`; inspection slots by `inspector_id`; inspections by `permit_id`, `slot_id`, or `inspector_id`; stop-work orders by `permit_id`; and certificates by `permit_id` or `final_inspection_id`. A permit's audit trail is retrieved as its ordered list of `PermitEvent` records. All list endpoints honor the `limit` and `offset` pagination parameters and the ascending-creation-order default.

Because expiration and contractor currency turn on the passage of time, the system exposes an administrative, test-driving clock that only a `BuildingOfficial` may drive. One capability sets the server's current UTC clock to a fixed instant supplied as `to_iso8601`; another advances the clock forward by a supplied number of `days`. These exist so that time-dependent behavior — a license lapsing past its `license_expiry`, a permit crossing its `expires_at` — can be exercised deterministically.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify or transition an existing resource, and all read operations, return `200 OK`. The two clock capabilities return `200 OK`. The table below is a routing summary only; the request payloads, response shapes, and side effects of each operation are specified in the business-logic narratives of §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/jurisdictions` | Create a jurisdiction (fee schedule reference) | BuildingOfficial |
| GET | `/jurisdictions/{id}` | Fetch a jurisdiction | BuildingOfficial, PermitClerk, Applicant, PlanReviewer, Inspector |
| POST | `/contractors` | Register a contractor with license and bond data | PermitClerk, BuildingOfficial |
| GET | `/contractors/{id}` | Fetch a contractor with derived verification status | PermitClerk, BuildingOfficial, Applicant |
| PATCH | `/contractors/{id}` | Update a contractor's license/bond standing (re-verify) | PermitClerk, BuildingOfficial |
| POST | `/inspectors` | Register an inspector | BuildingOfficial |
| GET | `/inspectors/{id}` | Fetch an inspector | BuildingOfficial, PermitClerk, Applicant, Inspector |
| POST | `/plan-reviewers` | Register a plan reviewer | BuildingOfficial |
| GET | `/plan-reviewers/{id}` | Fetch a plan reviewer | BuildingOfficial, PermitClerk, Applicant, PlanReviewer |
| POST | `/permits` | Submit a permit application; computes fees | Applicant, PermitClerk |
| GET | `/permits/{id}` | Fetch a permit with computed fee and balance fields | Applicant, PermitClerk, BuildingOfficial, PlanReviewer, Inspector |
| GET | `/permits` | List permits (filter by contractor, jurisdiction, approving reviewer, status) | Applicant, PermitClerk, BuildingOfficial, PlanReviewer, Inspector |
| POST | `/permits/{id}/withdraw` | Withdraw a pre-issuance permit | Applicant, PermitClerk |
| POST | `/permits/{id}/resubmit` | Resubmit a corrected permit, re-entering plan review | Applicant, PermitClerk |
| POST | `/permits/{id}/issue` | Issue an approved permit (version-guarded) | PermitClerk |
| POST | `/permits/{id}/renew` | Renew an expired permit (version-guarded) | PermitClerk |
| POST | `/permits/{id}/expire` | System sweep: expire an issued permit past its validity | BuildingOfficial |
| POST | `/permits/{id}/finalize` | Close out an issued permit | BuildingOfficial |
| POST | `/permits/{id}/payments` | Record a fee payment toward a permit | Applicant, PermitClerk |
| GET | `/payments/{id}` | Fetch a single fee payment | Applicant, PermitClerk, BuildingOfficial |
| GET | `/payments` | List fee payments (filter by permit) | Applicant, PermitClerk, BuildingOfficial |
| POST | `/permits/{id}/reviews` | Open a plan review on a permit | PlanReviewer |
| GET | `/reviews/{id}` | Fetch a plan review | PlanReviewer, PermitClerk, BuildingOfficial, Applicant |
| GET | `/reviews` | List plan reviews (filter by permit or reviewer) | PlanReviewer, PermitClerk, BuildingOfficial, Applicant |
| POST | `/reviews/{id}/decide` | Decide a review APPROVED or CORRECTIONS | PlanReviewer |
| POST | `/reviews/{id}/correction-notices` | Attach a correction notice to an open review | PlanReviewer |
| GET | `/correction-notices/{id}` | Fetch a single correction notice | PlanReviewer, PermitClerk, BuildingOfficial, Applicant |
| GET | `/correction-notices` | List correction notices (filter by review or permit) | PlanReviewer, PermitClerk, BuildingOfficial, Applicant |
| POST | `/correction-notices/{id}/resolve` | Mark a correction notice resolved | Applicant, PermitClerk |
| POST | `/inspection-slots` | Publish an inspector availability window | BuildingOfficial, Inspector |
| GET | `/inspection-slots/{id}` | Fetch a slot with derived booked count | BuildingOfficial, Inspector, Applicant, PermitClerk |
| GET | `/inspection-slots` | List inspection slots (filter by inspector) | BuildingOfficial, Inspector, Applicant, PermitClerk |
| POST | `/permits/{id}/inspections` | Schedule a ROUGH or FINAL inspection into a slot | Applicant, PermitClerk |
| GET | `/inspections/{id}` | Fetch an inspection | Applicant, PermitClerk, BuildingOfficial, Inspector |
| GET | `/inspections` | List inspections (filter by permit, slot, or inspector) | Applicant, PermitClerk, BuildingOfficial, Inspector |
| POST | `/inspections/{id}/result` | Record a PASS or FAIL result | Inspector |
| POST | `/inspections/{id}/cancel` | Cancel a scheduled inspection | Applicant, PermitClerk |
| POST | `/permits/{id}/stop-work-orders` | Issue a stop-work order | BuildingOfficial |
| GET | `/stop-work-orders/{id}` | Fetch a single stop-work order | BuildingOfficial, PermitClerk, Applicant |
| GET | `/stop-work-orders` | List stop-work orders (filter by permit) | BuildingOfficial, PermitClerk, Applicant |
| POST | `/stop-work-orders/{id}/lift` | Lift an active stop-work order | BuildingOfficial |
| GET | `/certificates/{id}` | Fetch a certificate of occupancy | BuildingOfficial, PermitClerk, Applicant |
| GET | `/certificates` | List certificates (filter by permit or final inspection) | BuildingOfficial, PermitClerk, Applicant |
| POST | `/certificates/{id}/revoke` | Revoke an issued certificate of occupancy | BuildingOfficial |
| GET | `/permits/{id}/events` | List a permit's append-only audit events | BuildingOfficial, PermitClerk, Applicant, PlanReviewer, Inspector |
| POST | `/_clock/set_current_utc` | Test-driving: set the server clock to a fixed instant | BuildingOfficial |
| POST | `/_clock/advance` | Test-driving: advance the server clock by a number of days | BuildingOfficial |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_ASSIGNED_REVIEWER` | 403 |
| `ERR_PERMIT_NOT_FOUND` | 404 |
| `ERR_CONTRACTOR_NOT_FOUND` | 404 |
| `ERR_JURISDICTION_NOT_FOUND` | 404 |
| `ERR_REVIEW_NOT_FOUND` | 404 |
| `ERR_CORRECTION_NOT_FOUND` | 404 |
| `ERR_INSPECTION_NOT_FOUND` | 404 |
| `ERR_SLOT_NOT_FOUND` | 404 |
| `ERR_SWO_NOT_FOUND` | 404 |
| `ERR_CO_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_DUPLICATE_LICENSE` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_PERMIT_VERSION` | 412 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_CONTRACTOR_UNVERIFIED` | 409 |
| `ERR_WORK_STOPPED` | 409 |
| `ERR_OPEN_CORRECTIONS` | 409 |
| `ERR_ROUGH_NOT_PASSED` | 409 |
| `ERR_OUTSIDE_SLOT_WINDOW` | 409 |
| `ERR_INSPECTOR_DOUBLE_BOOKED` | 409 |
| `ERR_SLOT_CAPACITY_FULL` | 409 |
| `ERR_BALANCE_DUE` | 409 |
| `ERR_NO_CERTIFICATE` | 409 |
