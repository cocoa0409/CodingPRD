# Travel Reimburse API — Product Requirements Document

## 1. Introduction

Corporate travel reimbursement is one of the most paperwork-heavy operations inside a mid-sized enterprise. A single business trip touches the line manager, the department head, the finance officer, sometimes the general manager, the corporate booking platform, the tax authority, the bank, and ultimately the audit team — and each of those parties expects a different artifact at a different time. When any of those handoffs goes wrong, the cost is concrete: trips get booked outside policy, invoices get reimbursed twice, expense caps drift quietly out of sync with the published standard, and finance closes the month with a stack of suspended forms whose history nobody can fully reconstruct.

This document specifies a Travel Reimbursement API that drives the entire lifecycle from initial application through to the bank-confirmed payment, with the explicit goal of making every approval, every booked segment, every verified invoice, and every paid amount fully auditable and replayable. The service is built around three intertwined approval chains — for travel applications, for reimbursement forms, and (implicitly) for payment execution — that share a common pattern: every chain step is computed from declarative inputs, pinned at submission time, and progressed by signed actions that leave behind immutable audit records. The system mediates between five external systems (the corporate booking platform, the tax authority, the electronic-invoice service, the banking gateway, and the downstream finance ledger) without letting any of them dictate internal state; every state change is the result of an explicit API call, and every external call is observable in the audit stream.

The reader of this PRD is the engineer who will implement the service. Wherever the document says "rounded half up to two decimal places" or "the loser receives `ERR_INVOICE_ALREADY_ATTACHED`", that is a contract, not a guideline.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API MUST carry two custom headers that together identify the caller: `X-User-ID` and `X-User-Role`. The first is the unique identifier of the calling principal; the second is the role under which the principal is acting on this particular request. If either header is missing or empty, the request is rejected with `ERR_AUTH_MISSING` (HTTP 401). If both headers are present but the role is not permitted to invoke the endpoint per the matrix below, the request is rejected with `ERR_FORBIDDEN` (HTTP 403). When the role and endpoint match but the caller is not the *specific* approver expected at the current chain step (or is not the applicant's supervisor where supervisory ownership is required), the rejection is `ERR_NOT_CURRENT_APPROVER` (HTTP 403).

The system recognises exactly six roles, each spelled as a single CamelCase token: `Applicant`, `Supervisor`, `DeptHead`, `Finance`, `GeneralManager`, and `Admin`.

The first five roles — `Applicant`, `Supervisor`, `DeptHead`, `Finance`, and `GeneralManager` — are **entity-backed by `Employee`**. When `X-User-Role` is any of those five values, `X-User-ID` is the `id` of the acting `Employee`; ownership checks on any resource that references an `Employee` compare the resource's foreign-key field to `X-User-ID`. Concretely, ownership of a `TravelApplication`, `Invoice`, or `ReimbursementForm` is decided by comparing the resource's `applicant_id` to `X-User-ID`; supervisory ownership of an applicant's submission is decided by comparing the resource's owning employee's `supervisor_id` to `X-User-ID`.

When `X-User-Role` is `Admin`, `X-User-ID` is an **opaque** operator identifier not tied to any persisted `Employee` row. The server may record it (for example, as `actor_id` on an `AuditLog` entry where a state transition writes it) but does not compare it to any entity's `id`.

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

All list endpoints accept the two query parameters `limit` and `offset`. The default `limit` is 10, the minimum is 1, and the maximum is 100; out-of-range values are rejected with `ERR_VALIDATION`. The default `offset` is 0; negative offsets are rejected with `ERR_VALIDATION`. List results are ordered by `created_at` ascending unless the endpoint description in §4 explicitly states a different ordering. The `meta` block on a list response carries `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset + limit < total_count`.

### 2.4. Common Resource Properties

Every resource minted by the system carries an `id` field whose value is a server-generated UUID with no type prefix; clients MUST NOT supply `id` on create. Most resources additionally carry `created_at`, `updated_at`, and `version`. The `created_at` and `updated_at` values are ISO 8601 UTC timestamps with exactly three fractional digits, and `version` is a monotonically increasing integer starting at 1 that is incremented by 1 every time any persisted field of the resource is modified. Three resources are intentionally lighter: `ExpenseStandard`, `ApprovalRecord`, and `AuditLog` are write-once history rows — they carry only `id` and `created_at`, and they do not expose `updated_at` or `version`. The `version` field on `ExpenseStandard` is a separate, business-meaningful **standard version** (not the OCC counter) supplied by the admin at creation and immutable for the lifetime of that row.

### 2.5. Optimistic Concurrency Control

The two endpoints that edit mutable text-style fields on existing resources — the edit operations against a draft `TravelApplication` and a draft `ReimbursementForm` — both accept an optional `version` field in the request body. When supplied, the server compares it to the resource's current `version`; a mismatch is rejected with `ERR_VERSION_CONFLICT` (HTTP 409). Omitting `version` from the request body skips the check entirely, and the edit proceeds. The OCC counter is the only meaning of `version` on `TravelApplication`, `ReimbursementForm`, `Payment`, `ItinerarySegment`, `Employee`, and `Invoice`; on `ExpenseStandard`, by contrast, `version` refers to the published standard's generation number and is never used for OCC.

### 2.6. Hierarchical Consistency and Nested Resource Retrieval

Several endpoints address sub-resources via nested paths, for example reaching a particular `ItinerarySegment` (whose path-parameter name is `segId`) through its owning `TravelApplication`, or a `ReimbursementItem` (whose path-parameter name is `itemId`) through its owning `ReimbursementForm`. Path parameters are validated **left-to-right**: the outer id is checked for existence first, then the inner id; both must exist *and* the inner resource must in fact belong to the outer one. Any failure along that chain is `ERR_NOT_FOUND` (HTTP 404). Whenever a mutation lands on a child resource, the parent's `updated_at` is refreshed and, where the parent has a `version` field, that field is incremented by 1; conversely, mutations that cascade from parent to child also bump the child's `updated_at` and `version`. The detailed cascade semantics — for example, that booking a new segment can transition a `TravelApplication` from `APPROVED` to `BOOKING_LOCKED`, or that successful payment of a form cascades attached `Invoice` rows from `ATTACHED` to `CONSUMED` — are described in §3 where they belong narratively.

### 2.7. Monetary Precision and Rounding

All monetary amounts are denominated in CNY and stored as numbers with two decimal places. Whenever an arithmetic step in this document produces a fractional value, that value is rounded to two decimal places using the **round-half-up** rule (i.e. 0.005 rounds up to 0.01, 1.235 rounds to 1.24). The convention is applied per-item before any sum: when a reimbursement form's total is computed, the individual item amounts are rounded to two decimal places **first**, and the form-level totals are the sum of those already-rounded item amounts. The payment batch total similarly sums already-rounded form totals.

### 2.8. Validation Priority Order

When a single request would fail multiple validations, the system reports the highest-priority failure first. The priority order is:

1. Header authentication — `ERR_AUTH_MISSING` for the missing-headers case.
2. Role permission — `ERR_FORBIDDEN` for an authorised header but a disallowed endpoint.
3. Path existence — `ERR_NOT_FOUND` for any unknown id in the URL, evaluated left-to-right.
4. Body reference resolution — `ERR_REFERENCE_INVALID` when an in-body foreign key (the `applicant_id` on a new `TravelApplication`, the `application_id` on a new `ReimbursementForm`, the `form_id` on a new `ReimbursementItem`, the `invoice_id` on a new `ReimbursementItem`, or a `matched_segment_id` that does not point to a segment under the same application) cannot be resolved.
5. State legality — `ERR_INVALID_STATE` when the target entity is not in a state that admits the requested transition per §3.
6. Approval chain step — `ERR_NOT_CURRENT_APPROVER` when the acting role is wrong for the current chain step, or when a `Supervisor` acts on a subordinate whose `supervisor_id` does not match `X-User-ID`.
7. Business constraints, in the order required by their domain — itinerary policy eligibility (`ERR_OPTION_NOT_ELIGIBLE`), then segment-within-trip (`ERR_SEGMENT_OUTSIDE_TRIP`), then non-hotel segment time overlap (`ERR_SEGMENT_TIME_OVERLAP`), then hotel night overlap (`ERR_HOTEL_NIGHT_OVERLAP`), then invoice duplication (`ERR_INVOICE_DUPLICATE`), then reimbursement-item invoice matching (`ERR_INVOICE_NOT_MATCHED`), then invoice verification state (`ERR_INVOICE_NOT_VERIFIED`), then budget overrun (`ERR_BUDGET_OVERRUN`), then the general-manager-required check at the finance step on a form requiring special approval (`ERR_GM_APPROVAL_REQUIRED`), then payment-amount immutability (`ERR_PAYMENT_AMOUNT_MISMATCH`), then payment retry exhaustion (`ERR_PAYMENT_RETRY_EXHAUSTED`).
8. Body schema validation — `ERR_VALIDATION` for required-field omissions, type mismatches, invalid enum values, negative numbers where non-negative is required, and malformed ISO 8601 timestamps.
9. Optimistic concurrency — `ERR_VERSION_CONFLICT` for the OCC `version` mismatch.

The validation-priority ordering matters at compose time: if an approval action arrives from an unauthenticated client *and* targets a non-existent application *and* would be against the chain step anyway, the client sees `ERR_AUTH_MISSING` only.

### 2.9. Idempotency on OCR

The OCR step on an `Invoice` is the one endpoint in the system that explicitly supports request-level idempotency. The client supplies an `Idempotency-Key` header; replaying the same key against the same invoice id returns the exact response of the first call, leaving `ocr_status` unchanged from the first call's outcome. If the same key is presented with a different request payload (or against a non-idempotent endpoint), the request is rejected with `ERR_IDEMPOTENT_REPLAY` (HTTP 409).

### 2.10. External-System Synchronisation Stream

Five state transitions trigger asynchronous-style notifications to external systems: tax-authority verification (target: electronic-invoice), itinerary changes and cancellations (target: corporate booking platform), trip completion (target: corporate booking platform), payment success (target: banking), and reimbursement posting (target: finance system). Each such event is recorded as an `AuditLog` row whose `event_type` is `EXTERNAL_SYNC` (or `PAYMENT_EVENT` for the bank-side cash movement) and whose `payload` carries a JSON snapshot of the fields relevant at the moment of emission.

## 3. Business Logic & Workflows

### 3.1. Reference Data: Employees and Expense Standards

The system is bootstrapped by an `Admin` who registers each `Employee` with their `full_name`, `employee_level` (one of `STAFF`, `MANAGER`, `DIRECTOR`, `EXECUTIVE`), `department_id`, and `supervisor_id`. Newly registered employees are created with `status` set to `ACTIVE` by default; only employees in `ACTIVE` may file applications, and any attempt to act as an applicant whose `Employee.status` is `INACTIVE` is rejected at the submit step.

Expense standards are the second piece of reference data and the trickiest. An `ExpenseStandard` row is keyed by the triple (`version`, `city_tier`, `employee_level`), with `city_tier` drawn from the enum `TIER_1`, `TIER_2`, `TIER_3`, `OVERSEAS`. Each row carries three caps — `lodging_daily_cap` (per-night), `per_diem_amount` (per-day meal and incidentals), and `transportation_daily_cap` (per-day ground transport) — and a `holiday_multiplier` (default `1.00`, typical value something like `1.30`) that scales **all three caps** on declared-holiday dates. Each row is bounded in time by `effective_from` (the moment it becomes active) and `effective_to` (the moment it expires, or null for an open-ended row). When an admin publishes a new row for an existing (`city_tier`, `employee_level`) bucket, the system **auto-closes** the prior open row in the same bucket — that is, the prior row's `effective_to` is set to the new row's `effective_from`. The new row's `effective_from` MUST be strictly later than any previous row's `effective_from` for the same bucket. The system's set of declared holidays for the year is fixed as `2025-01-01`, `2025-05-01`, and `2025-10-01`.

When an applicant later submits a travel application, the server pins the *currently active* standard version — i.e. the row whose half-open window `[effective_from, effective_to)` contains the moment of submit — onto the application's `standard_version_pinned`. Reimbursement caps later in the trip will be computed against that pinned version even if a newer standard is published in the interim. If, at submit time, no such row exists for the applicable (`city_tier`, `employee_level`), the submit fails with `ERR_NO_ACTIVE_STANDARD`.

### 3.2. Filing a Travel Application

The applicant initiates a trip by creating a `TravelApplication` in `DRAFT`. The creation payload carries the trip's `destination_city`, its `destination_tier` (`TIER_1`, `TIER_2`, `TIER_3`, or `OVERSEAS`), the `travel_scope` (`DOMESTIC` or `OVERSEAS`), a free-text `purpose`, the planned bounds `planned_start` and `planned_end`, an `estimated_budget`, and an optional `urgent` flag defaulting to `false`. While the application is still in `DRAFT`, the applicant may freely edit those same fields. Edits accept an optional `version` field for optimistic concurrency control as described in §2.5.

Submission transitions the application from `DRAFT` to `SUBMITTED`, and is permitted only when the applicant matches the row's `applicant_id`, the `planned_end` is strictly after `planned_start`, the `estimated_budget` is at least zero, and the acting applicant's `Employee.status` is `ACTIVE`. At the moment of submit, two important computations happen and their results are pinned onto the application for the remainder of its life.

The first computation is the **required approval chain**, which is materialised on the application's `required_chain` field as an ordered list. The chain is built as follows. Start the chain with the single step `SUPERVISOR`. If `estimated_budget` is strictly greater than 5,000 CNY or `travel_scope` equals `OVERSEAS`, append `DEPT_HEAD` to the chain. Append `FINANCE` next. If `estimated_budget` is strictly greater than 30,000 CNY or `travel_scope` equals `OVERSEAS`, append `GM` to the chain. Finally, if `urgent` is `true` *and* `travel_scope` is `DOMESTIC`, drop `DEPT_HEAD` from the chain if it is present — note that an urgent trip whose scope is `OVERSEAS` keeps the full chain because expedited routing only fires for domestic trips. Once written, `required_chain` is immutable for the rest of the application's lifecycle.

The second computation is `standard_version_pinned`, as described in §3.1.

After submission, the chain advances one step at a time. Each step is invoked as an approval action by a specific role: a `Supervisor` (whose `Employee.id` must equal the applicant's `supervisor_id`) advances `SUBMITTED → SUPERVISOR_APPROVED`; a `DeptHead`, if present in the chain, advances `SUPERVISOR_APPROVED → DEPT_HEAD_APPROVED`; a `Finance` officer advances from whichever of `SUPERVISOR_APPROVED` or `DEPT_HEAD_APPROVED` the chain is currently in to `FINANCE_APPROVED`; a `GeneralManager`, if present in the chain, advances `FINANCE_APPROVED → GM_APPROVED`. Each approval may carry an optional `comment` and writes one `ApprovalRecord` row capturing the `subject_type` (`TRAVEL_APPLICATION`), `subject_id`, the `actor_id`, the `actor_role`, the `action` (`APPROVE`), the `comment`, and both the `from_status` and `to_status`. The application reaches the global `APPROVED` state in one of two ways: either `FINANCE` is the last step of the chain (no GM required), in which case the finance approval directly transitions the application from `FINANCE_APPROVED` to `APPROVED`; or `GM` is the last step, in which case the system auto-transitions from `GM_APPROVED` to `APPROVED` immediately after the GM approval lands. The transition into `APPROVED` opens the booking window.

A rejection at any chain step is a terminal move: an approver in the current step calls reject, supplying a `rejection_reason`, and the application transitions to `REJECTED`. Specifically, reject is valid from `SUBMITTED`, `SUPERVISOR_APPROVED`, `DEPT_HEAD_APPROVED`, and `FINANCE_APPROVED`; the rejection writes one `ApprovalRecord` with `action` equal to `REJECT` and the `comment` set to the supplied `rejection_reason`. Reject is **not** a valid transition out of `APPROVED`, `BOOKING_LOCKED`, `COMPLETED`, `CANCELLED`, or `REJECTED`; any such attempt is `ERR_INVALID_STATE`.

A simultaneity hazard exists at every step: two approvers (or the same approver under retry) in the same chain step click approve on the same application at the same time. Exactly one transition succeeds; the loser sees the application already in the *next* status, and receives `ERR_INVALID_STATE` (HTTP 409). The serialisation guarantee is first-writer-wins on the application's `status` using the OCC `version`.

The applicant may cancel the application in two situations: while it is still in `DRAFT` (a trivial cancellation, no preconditions other than ownership), or after it has reached `APPROVED` but **before** any `ItinerarySegment` with `status` `ACTIVE` exists under it. Cancel from any other state (notably `BOOKING_LOCKED`, where bookings are already in place) is `ERR_INVALID_STATE`.

### 3.3. Booking the Itinerary

Once the application is `APPROVED`, the applicant books the trip one segment at a time. Each `ItinerarySegment` carries the parent's `application_id`, a `segment_type` from `FLIGHT`, `TRAIN`, `HOTEL`, or `CAR`, an `option_code` returned by the corporate booking platform, a `start_at` and `end_at`, and a `cost` in CNY as quoted by the platform. Newly booked segments are created with `status` set to `ACTIVE` and `prior_segment_id` set to null.

The *first* successful booking against an `APPROVED` application transitions the application from `APPROVED` to `BOOKING_LOCKED`; subsequent bookings, changes, and cancellations all happen with the application in `BOOKING_LOCKED` and the application self-transitions back to `BOOKING_LOCKED` after each mutation. Every successful create / change / cancel against the itinerary recomputes the application's `total_booked_cost` as the sum of the `cost` of all segments under the application whose `status` is `ACTIVE`. The recomputation is rounded to two decimal places using round-half-up.

A new segment is admissible only when every one of the following holds, evaluated in the order listed:

1. **Policy eligibility.** The submitted `option_code` MUST appear in the policy-eligible option set for the pair (`segment_type`, applicant's `employee_level`); otherwise the booking is rejected with `ERR_OPTION_NOT_ELIGIBLE`. The eligible option set is maintained by the test harness for the (`segment_type`, `employee_level`) pair.
2. **Segment within trip bounds.** Both `start_at` and `end_at` MUST lie within the closed interval `[planned_start, planned_end]` of the application; otherwise `ERR_SEGMENT_OUTSIDE_TRIP`.
3. **Non-overlap among transport segments.** Two `ACTIVE` segments under the same application whose `segment_type` is in `FLIGHT`, `TRAIN`, or `CAR` MUST NOT have time intervals that strictly overlap. Equal endpoints (one segment ending at exactly the moment the next begins) are permitted. A violation is `ERR_SEGMENT_TIME_OVERLAP`.
4. **Non-overlap among hotel nights.** Two `ACTIVE` `HOTEL` segments under the same application MUST NOT have overlapping `[start_at, end_at)` night intervals; that interval is half-open, so checkout day may equal next check-in day. A violation is `ERR_HOTEL_NIGHT_OVERLAP`.
5. **Budget pre-allocation.** The recomputed `total_booked_cost` after this insert MUST NOT exceed the application's `estimated_budget` multiplied by the budget overrun factor of `1.20`; otherwise the insert is rejected with `ERR_BUDGET_OVERRUN`. The same check is applied on change.

Change is a record-preserving replacement: the old `ItinerarySegment` row is moved from `ACTIVE` to `CHANGED`, and a new row is inserted in `ACTIVE` with its `prior_segment_id` set to the id of the row it superseded. Every business-constraint check listed above is re-evaluated against the post-replacement state. Change also emits an `EXTERNAL_SYNC` audit event to the corporate booking platform.

Cancel is simpler: the `ItinerarySegment` moves from `ACTIVE` to `CANCELLED`, `total_booked_cost` is recomputed, and an `EXTERNAL_SYNC` audit event is emitted to the corporate booking platform. There is no budget check on cancel because cancellation can only decrease the total.

For any of the three itinerary operations (book, change, cancel), the segment must currently be in `ACTIVE` for change and cancel to apply; an attempt to change a `CHANGED` or `CANCELLED` row is `ERR_INVALID_STATE`.

### 3.4. Forward Budget Projection

At any point after a `TravelApplication` has bookings, the applicant or a finance officer may request a forward-looking estimate of how much of the trip will actually be reimbursable. The projection runs against the **currently active** `ExpenseStandard` — the row whose half-open window `[effective_from, effective_to)` contains the present moment — not the version pinned on the application. It walks every `ItinerarySegment` whose `status` is `ACTIVE` under the application, and for each one computes a projected item cap.

For segments whose `segment_type` is `FLIGHT`, `TRAIN`, or `CAR`, the unit cap is the row's `transportation_daily_cap`, multiplied by the planned days in the segment computed as the number of hours between `start_at` and `end_at` divided by 24 and rounded **up** to the next whole number (i.e. ceiling). For segments whose `segment_type` is `HOTEL`, the unit cap is the row's `lodging_daily_cap`, multiplied by the integer number of nights between `start_at` and `end_at`. The row from which `transportation_daily_cap` and `lodging_daily_cap` are read is keyed by (`city_tier` equal to the application's `destination_tier`, `employee_level` equal to the applicant's `employee_level`).

If any day of the application's planned interval `[planned_start, planned_end]` falls on a declared holiday (`2025-01-01`, `2025-05-01`, or `2025-10-01`), all caps for those days are multiplied by the row's `holiday_multiplier`.

After computing the per-item cap, the projected reimbursable contribution of each segment is the lesser of the segment's `cost` and the item cap; the projection then sums those per-segment contributions, rounding each to two decimal places using round-half-up before summing.

### 3.5. Trip Completion and Cancellation After Booking

Once the trip is actually over — concretely, once the server's clock has reached or passed the maximum `end_at` among the application's `ACTIVE` segments — the applicant marks the trip complete. Completion transitions the application from `BOOKING_LOCKED` to `COMPLETED` and emits an `EXTERNAL_SYNC` audit entry to the corporate booking platform with the event `TRIP_COMPLETED`. If invoked too early (the trip has not yet ended), the completion is rejected with `ERR_INVALID_STATE`. Cancellation of an application that is already in `BOOKING_LOCKED` is not permitted; the only post-`APPROVED` cancellation path is from `APPROVED` with no `ACTIVE` segments yet, as described in §3.2.

### 3.6. Invoice Lifecycle: Upload, OCR, Tax Verification, and Matching

Invoices have their own lifecycle that runs partly in parallel with the trip. An applicant uploads an `Invoice` for their `applicant_id`, supplying the `invoice_number`, the `invoice_code`, the `category` (one of `LODGING`, `PER_DIEM`, `TRANSPORTATION`, `OTHER`), and optionally the `amount` and `invoice_date` if those are already known. The freshly uploaded invoice has `ocr_status` set to `PENDING_OCR`, `matched_segment_id` null, and `rejection_reason` null.

The OCR step transitions the invoice from `PENDING_OCR` to `OCR_RECOGNIZED`. Where the upload did not provide `amount`, `invoice_date`, or `category`, the OCR result fills them in. This endpoint supports idempotency: re-posting the same `Idempotency-Key` against the same invoice id returns the previous result and leaves `ocr_status` unchanged, as described in §2.9.

Tax verification transitions the invoice from `OCR_RECOGNIZED` to either `TAX_VERIFIED` (success) or `REJECTED` (failure). Two preconditions guard the success path: no other `Invoice` may currently exist with the same combination of `invoice_code` and `invoice_number` whose `ocr_status` is in `TAX_VERIFIED`, `ATTACHED`, or `CONSUMED`, and the invoice's `amount` must be strictly greater than zero. A duplicate is rejected with `ERR_INVOICE_DUPLICATE` (HTTP 409). The duplicate check, more broadly, also applies at upload: an `Invoice` whose (`invoice_code`, `invoice_number`) collides with any other invoice not in `REJECTED` is itself rejected with `ERR_INVOICE_DUPLICATE`. On the failure path — for example, when the tax-authority lookup returns INVALID, or when duplicate detection fires — the invoice moves to `REJECTED` and the `rejection_reason` is populated by the system. A successful tax verification emits an `EXTERNAL_SYNC` audit event whose target is the electronic-invoice service.

An invoice in `TAX_VERIFIED` is ready to be attached to a reimbursement form (see §3.7); the attach transition moves it from `TAX_VERIFIED` to `ATTACHED`. The reverse transition — `ATTACHED` back to `TAX_VERIFIED` — happens in exactly two situations: when the applicant removes the item from a draft form, or when a reject-and-correct action against a form sends the form back to `DRAFT`. Finally, an invoice is `CONSUMED` (the only terminal-by-success state for an invoice) exactly when the parent reimbursement form's payment reaches `SUCCESS`.

The duplicate-attach hazard appears when two different `ReimbursementForm`s race to attach the same `TAX_VERIFIED` invoice. At most one attach succeeds; the loser sees `Invoice.ocr_status` already at `ATTACHED` and receives `ERR_INVOICE_ALREADY_ATTACHED` (HTTP 409). The serialisation guarantee is first-writer-wins on the invoice's `ocr_status`.

The OCR idempotency hazard appears when the applicant submits OCR twice with the same `Idempotency-Key`. The second request returns the first request's response without re-running OCR; `ocr_status` is unchanged from the first call's outcome. If the same key is replayed with a different payload, the response is `ERR_IDEMPOTENT_REPLAY` (HTTP 409).

### 3.7. Reimbursement Form: Items, Submission, and Approval

After the trip enters `BOOKING_LOCKED` (i.e. the applicant has at least one `ACTIVE` segment) — and indeed once it has reached `COMPLETED` — the applicant assembles a `ReimbursementForm`. Creating the form requires only the parent `application_id`; the form is created in `DRAFT` with `applicant_id` mirrored from the application, `correction_round` initialised to zero, and all four computed totals (`total_claimed`, `total_reimbursable`, `total_self_paid`) initialised to zero. The form's `applicant_id` MUST equal the parent application's `applicant_id`.

Items are then attached one at a time. Each `ReimbursementItem` carries the parent `form_id`, an `invoice_id` referencing an `Invoice` whose `ocr_status` is currently `TAX_VERIFIED`, an item `category` (`LODGING`, `PER_DIEM`, `TRANSPORTATION`, or `OTHER`), the `covered_days` (the number of policy-eligible days the item covers, used to compute its cap), the `claimed_amount`, and — for items whose `category` is `LODGING` or `TRANSPORTATION` — a `matched_segment_id` pointing to the `ItinerarySegment` whose date window encloses the invoice and whose `segment_type` is compatible. Specifically, an invoice attached as `LODGING` must match a `HOTEL` segment; an invoice attached as `TRANSPORTATION` must match a `FLIGHT`, `TRAIN`, or `CAR` segment; the segment must belong to the same application; the segment's `status` must be `ACTIVE`; and the invoice's `invoice_date` must satisfy `start_at` ≤ `invoice_date` ≤ `end_at`. A `matched_segment_id` is required for `LODGING` and `TRANSPORTATION` items and is nullable for `PER_DIEM` and `OTHER`. The error code for any failure of segment matching or category–segment-type compatibility is `ERR_INVOICE_NOT_MATCHED`. The error code for an attached invoice that is not currently in `TAX_VERIFIED` is `ERR_INVOICE_NOT_VERIFIED`. Successfully attaching an item moves the underlying `Invoice` from `TAX_VERIFIED` to `ATTACHED`. Removing an item from a draft form moves the underlying `Invoice` from `ATTACHED` back to `TAX_VERIFIED`. Both operations refresh the form's three computed totals.

Submission of the form recomputes the form-level totals once more using the rules described in §3.8 and transitions the form from `DRAFT` to `SUBMITTED`. Submission is admissible only when the parent application's `status` is `BOOKING_LOCKED` or `COMPLETED`, at least one `ReimbursementItem` exists, and every attached `Invoice` has `ocr_status` equal to `ATTACHED`. If the freshly computed totals make `requires_special_approval` true (i.e. `total_self_paid` is strictly greater than zero and `special_approval_granted` is false), the form still flows through the chain but is now committed to needing GM approval before it can reach `APPROVED`.

From there, the form walks an approval chain that always has the same four-role shape: `Supervisor` (whose `Employee.id` must equal the applicant's `supervisor_id`) advances `SUBMITTED → SUPERVISOR_APPROVED`; `DeptHead` advances `SUPERVISOR_APPROVED → DEPT_APPROVED`; `Finance` advances `DEPT_APPROVED → FINANCE_APPROVED`. At the `FINANCE_APPROVED` state two outcomes are possible. If the form's `requires_special_approval` is false, `Finance` may directly transition the form to `APPROVED`; this is the simple finance-approves path. If the form's `requires_special_approval` is true, `Finance` MUST advance the form to `GM_APPROVED` and a `GeneralManager` then issues the final approval, which sets `special_approval_granted` to true and, via a system auto-transition, lands the form in `APPROVED`. Any attempt by `Finance` to move a form whose `requires_special_approval` is true directly to `APPROVED` is rejected with `ERR_GM_APPROVAL_REQUIRED`. The two paths share the same effects on `ApprovalRecord`: every approve writes one row with the appropriate `actor_role`, `action` equal to `APPROVE`, optional `comment`, and the `from_status`/`to_status` pair. The two terminal-from-approval `from`–`to` pairs (`FINANCE_APPROVED → APPROVED` for the no-special-approval form, and `GM_APPROVED → APPROVED` for the special-approval form) are equally legitimate; both open the form for payment in §3.9.

Reject on a reimbursement form has two flavours, distinguished by the request's `correction` flag. A reject with `correction` set to `true` returns the form from any of `SUBMITTED`, `SUPERVISOR_APPROVED`, `DEPT_APPROVED`, or `FINANCE_APPROVED` to `DRAFT`, increments `correction_round` by 1, reverts every attached `Invoice` from `ATTACHED` back to `TAX_VERIFIED`, and writes one `ApprovalRecord` whose `action` is `REJECT` and whose `comment` carries the supplied `rejection_reason`. A reject with `correction` set to `false` terminates the form: it transitions from `SUBMITTED` to `REJECTED` and writes the same `ApprovalRecord`, but does not revert invoices or increment the correction counter. Both flavours require a non-empty `rejection_reason`.

### 3.8. Final Reimbursable Calculation at Form Submission

When a `ReimbursementForm` is submitted, the system performs a final settlement of every item using the **pinned** `ExpenseStandard` version — that is, the `standard_version_pinned` captured on the parent `TravelApplication` at its own submit — and **not** the version currently active in the published-standards table. Items are processed in order of ascending `invoice_date` (i.e. the date on the invoice), with ties broken by the item's `created_at` ascending; this chronological ordering is what governs the term "chronological" in the settlement rule below.

For each item, the system locates the per-unit cap as follows. The applicable `ExpenseStandard` row is keyed by the triple (`version` equal to `standard_version_pinned`, `city_tier` equal to the parent application's `destination_tier`, `employee_level` equal to the applicant's `employee_level`); if the application's `travel_scope` is `OVERSEAS`, the `city_tier` lookup is forced to `OVERSEAS` regardless of `destination_tier` — overseas trips always read the `OVERSEAS` row. From that row, the per-unit cap is taken from the field that matches the item's `category`: `lodging_daily_cap` for `LODGING`, `per_diem_amount` for `PER_DIEM`, `transportation_daily_cap` for `TRANSPORTATION`. (Items of category `OTHER` have no standard-driven cap; their `standard_cap_applied` is taken as the `claimed_amount` itself, so they are fully reimbursable up to the claim.) If any day of the item's coverage window — derived from the item's `covered_days` against the matched segment's date range (or, for `PER_DIEM`, the trip's planned range) — falls on a declared holiday (`2025-01-01`, `2025-05-01`, or `2025-10-01`), the per-unit cap is multiplied by the row's `holiday_multiplier`.

Each item's `standard_cap_applied` is then set to the per-unit cap multiplied by the item's `covered_days`, rounded to two decimal places using round-half-up. The item's `reimbursable_amount` is the lesser of `claimed_amount` and `standard_cap_applied`. The item's `self_paid_amount` is the greater of zero and (`claimed_amount` minus `standard_cap_applied`); a non-negative quantity by construction. Per-item rounding happens **before** the form-level sums are taken: `total_claimed` is the sum of every item's `claimed_amount`, `total_reimbursable` is the sum of every item's already-rounded `reimbursable_amount`, and `total_self_paid` is the sum of every item's already-rounded `self_paid_amount`. The form's `requires_special_approval` field is set to true exactly when `total_self_paid` is strictly greater than zero **and** `special_approval_granted` is currently false; otherwise it is false.

The `standard_cap_applied` value persists on the item even if a newer `ExpenseStandard` is later published — its purpose is to preserve the audit-trail rationale for the reimbursable amount at the moment of settlement.

### 3.9. Payment Batches, Execution, and the Bank Callback

Once a `ReimbursementForm` is in `APPROVED`, a `Finance` officer schedules its payment. Payments are created through a batch endpoint that accepts a list of `form_ids` and a `channel` (one of `BANK_TRANSFER`, `CORPORATE_CARD_REFUND`, or `INTERNAL_WALLET`) in the request body. The server enumerates the forms, sorts them by (`applicant_id` ascending, then `created_at` ascending), and creates one `Payment` per form. Every `Payment` created in a single batch call shares a single server-assigned `batch_id`, and each payment's `amount` is pinned at creation time to the parent form's `total_reimbursable`. Each payment is created in `PENDING` with `attempt_count` zero, `external_ref` null, and `failure_reason` null.

The batch endpoint rejects the *entire* call with `ERR_INVALID_BATCH` if the request body contains duplicate `form_ids`, references any unknown `form_ids`, or includes any form whose `status` is not `APPROVED`. The `Payment.amount`-versus-form-`total_reimbursable` invariant is enforced at every checkpoint thereafter: if the form mutates underneath such that the two no longer agree at execute time, the execute fails with `ERR_PAYMENT_AMOUNT_MISMATCH`.

Execution moves the payment from `PENDING` to `EXECUTING` (or from `RETRYING` to `EXECUTING` on a retry); each execute increments `attempt_count` by 1. Execution requires the parent form to still be in `APPROVED` and the payment's `amount` to be strictly greater than zero. Two `Finance` officers clicking execute on the same `PENDING` payment race: exactly one `attempt_count` increment succeeds, and the loser sees the payment already `EXECUTING` and receives `ERR_INVALID_STATE` (HTTP 409). The serialisation guarantee is first-writer-wins on the payment's `status` using the OCC `version`.

The banking system replies via a callback simulated by the result endpoint, whose request body carries the `outcome` (`SUCCESS` or `FAILED`), an optional `external_ref` (populated on success), and an optional `failure_reason` (populated on failure). A `SUCCESS` outcome transitions the payment from `EXECUTING` to `SUCCESS`, sets `external_ref`, and cascades two further state changes: the parent `ReimbursementForm` transitions from `APPROVED` to `PAID`, and every `Invoice` that any of the form's `ReimbursementItem`s reference (via `invoice_id`) transitions from `ATTACHED` to `CONSUMED`. The payment-success cascade also writes an `AuditLog` whose `event_type` is `PAYMENT_EVENT` and whose `payload` carries the form's id, `amount`, and `channel`, and emits an `EXTERNAL_SYNC` audit event to the finance system with the event `REIMBURSEMENT_POSTED`, plus one to the banking system with the event `PAID`. A `FAILED` outcome transitions the payment from `EXECUTING` to `FAILED` and sets `failure_reason`.

Retry transitions a `FAILED` payment to `RETRYING` provided that `attempt_count` is strictly less than the maximum of 3 attempts; a retry against a payment whose `attempt_count` has already reached 3 is rejected with `ERR_PAYMENT_RETRY_EXHAUSTED`. From `RETRYING`, the next execute returns the payment to `EXECUTING` (and bumps `attempt_count`). If the third execute also lands a `FAILED`, the payment is terminal at `FAILED`, and the parent `ReimbursementForm` cascades from `APPROVED` to its own terminal state `FAILED`; an `AuditLog` records the cascade.

### 3.10. Audit Trail and Approval History

Two read-only streams are exposed to support investigations and reporting. The approval-records stream lists every `ApprovalRecord` row — that is, every approve and every reject ever issued against either a `TRAVEL_APPLICATION` or a `REIMBURSEMENT_FORM` — and supports filtering by `subject_type`, `subject_id`, and `actor_id`. The audit-log stream lists every `AuditLog` row, regardless of whether its `event_type` is `APPROVAL_ACTION`, `PAYMENT_EVENT`, or `EXTERNAL_SYNC`, and supports filtering by `subject_type`, `subject_id`, `event_type`, and `since` (a lower-bound timestamp). Both streams support pagination as described in §2.3.

The `Admin` role additionally has three test-harness capabilities. The first advances the logical clock by a supplied integer `seconds` (used to drive the trip-completion precondition that the server's clock has reached the maximum `end_at`, and to drive `ExpenseStandard` version rollover). The second pins the outcome of the next tax-authority verification on a specific invoice, taking an `invoice_id` and a `verdict` of either `VALID` or `INVALID`. The third seeds the policy-eligible option set for a given (`segment_type`, `employee_level`) by writing a list of `option_codes`. These three endpoints exist solely to make the system testable; they have no business meaning.

## 4. Endpoint Definitions

All endpoints share the response envelope from §2.2 and the validation priority from §2.8. Operations that create a new resource return HTTP 201; operations that modify, delete, or merely fetch a resource return 200 (with the single exception of removing a reimbursement item, which returns 204 with an empty body). Errors are returned with the HTTP status listed in §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /employees | Register an `Employee` (admin bootstrap). | Admin |
| GET | /employees/{id} | Fetch an `Employee`. | Admin, Applicant, Supervisor, DeptHead, Finance, GeneralManager |
| POST | /expense-standards | Publish a new `ExpenseStandard` row. Auto-closes prior open row for same (`city_tier`, `employee_level`). | Admin |
| GET | /expense-standards | List `ExpenseStandard` rows; filter by `version`, `city_tier`, `employee_level`. | Admin, Finance, Applicant |
| POST | /travel-applications | Create a draft `TravelApplication`. | Applicant |
| GET | /travel-applications/{id} | Fetch a `TravelApplication`. | Applicant, Supervisor, DeptHead, Finance, GeneralManager, Admin |
| PATCH | /travel-applications/{id} | Edit a draft `TravelApplication` (OCC via `version`). | Applicant |
| POST | /travel-applications/{id}/submit | Submit a draft application; computes `required_chain` and pins `standard_version_pinned`. | Applicant |
| POST | /travel-applications/{id}/approve | Approve the current chain step. | Supervisor, DeptHead, Finance, GeneralManager |
| POST | /travel-applications/{id}/reject | Reject the current chain step. | Supervisor, DeptHead, Finance, GeneralManager |
| POST | /travel-applications/{id}/itineraries | Book a new `ItinerarySegment`. | Applicant |
| GET | /travel-applications/{id}/itineraries | List segments under an application; filter by `status`. | Applicant, Supervisor, DeptHead, Finance, GeneralManager, Admin |
| POST | /travel-applications/{id}/itineraries/{segId}/change | Replace an `ACTIVE` segment with a new one. | Applicant |
| POST | /travel-applications/{id}/itineraries/{segId}/cancel | Cancel an `ACTIVE` segment. | Applicant |
| GET | /travel-applications/{id}/budget-projection | Forward-looking reimbursable estimate (currently-active standard). | Applicant, Finance |
| POST | /travel-applications/{id}/complete | Mark a `BOOKING_LOCKED` trip `COMPLETED`. | Applicant |
| POST | /travel-applications/{id}/cancel | Cancel a `DRAFT`, or an `APPROVED`-with-no-bookings, application. | Applicant |
| POST | /invoices | Upload an `Invoice` (`PENDING_OCR`). | Applicant |
| POST | /invoices/{id}/ocr | Run OCR on an invoice. Idempotent via `Idempotency-Key`. | Applicant |
| POST | /invoices/{id}/verify-tax | Run tax-authority verification; triggers duplicate detection. | Applicant, Finance |
| GET | /invoices/{id} | Fetch an `Invoice`. | Applicant, Finance, Admin |
| POST | /reimbursement-forms | Create a draft `ReimbursementForm` bound to a `TravelApplication`. | Applicant |
| POST | /reimbursement-forms/{id}/items | Attach a `ReimbursementItem` (and its `Invoice`) to a draft form. | Applicant |
| DELETE | /reimbursement-forms/{id}/items/{itemId} | Remove an item from a draft form (returns 204). | Applicant |
| POST | /reimbursement-forms/{id}/submit | Submit the form; runs final-settlement recompute. | Applicant |
| POST | /reimbursement-forms/{id}/approve | Approve the current chain step. | Supervisor, DeptHead, Finance, GeneralManager |
| POST | /reimbursement-forms/{id}/reject | Reject the current step; `correction` flag returns to `DRAFT` or terminates. | Supervisor, DeptHead, Finance, GeneralManager |
| GET | /reimbursement-forms/{id} | Fetch a `ReimbursementForm` (with computed totals). | Applicant, Supervisor, DeptHead, Finance, GeneralManager, Admin |
| POST | /payments/batches | Create a batch of `Payment`s — one per `APPROVED` form. | Finance |
| POST | /payments/{id}/execute | Execute (or re-execute) a payment. | Finance |
| POST | /payments/{id}/result | Banking-callback simulation: post `SUCCESS` or `FAILED`. | Finance, Admin |
| POST | /payments/{id}/retry | Move `FAILED → RETRYING` if `attempt_count` < 3. | Finance |
| GET | /payments/{id} | Fetch a `Payment` with `status` and `attempt_count`. | Finance, Applicant, Admin |
| GET | /payments | List payments; filter by `batch_id`, `status`, `form_id`. | Finance, Admin |
| GET | /audit-logs | Stream `AuditLog` entries; filter by `subject_type`, `subject_id`, `event_type`, `since`. | Admin, Finance |
| GET | /approval-records | List `ApprovalRecord` rows; filter by `subject_type`, `subject_id`, `actor_id`. | Admin, Finance, Applicant |
| POST | /_clock/advance | Test-only: advance server clock by `seconds`. | Admin |
| POST | /_external/invoice-verify-result | Test-only: pin the next tax-verify `verdict` for a specific `invoice_id`. | Admin |
| POST | /_external/booking-options | Test-only: seed eligible `option_codes` for (`segment_type`, `employee_level`). | Admin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_AUTH_MISSING | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_CURRENT_APPROVER | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_REFERENCE_INVALID | 422 |
| ERR_INVALID_STATE | 409 |
| ERR_VERSION_CONFLICT | 409 |
| ERR_VALIDATION | 422 |
| ERR_NO_ACTIVE_STANDARD | 422 |
| ERR_OPTION_NOT_ELIGIBLE | 422 |
| ERR_SEGMENT_OUTSIDE_TRIP | 422 |
| ERR_SEGMENT_TIME_OVERLAP | 422 |
| ERR_HOTEL_NIGHT_OVERLAP | 422 |
| ERR_BUDGET_OVERRUN | 422 |
| ERR_INVOICE_DUPLICATE | 409 |
| ERR_INVOICE_NOT_VERIFIED | 422 |
| ERR_INVOICE_NOT_MATCHED | 422 |
| ERR_INVOICE_ALREADY_ATTACHED | 409 |
| ERR_IDEMPOTENT_REPLAY | 409 |
| ERR_GM_APPROVAL_REQUIRED | 422 |
| ERR_PAYMENT_AMOUNT_MISMATCH | 422 |
| ERR_PAYMENT_RETRY_EXHAUSTED | 422 |
| ERR_INVALID_BATCH | 422 |
