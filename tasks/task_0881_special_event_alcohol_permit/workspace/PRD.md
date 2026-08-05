# Special-Event Alcohol Permit API — Product Requirements Document

## 1. Introduction

Municipalities that license the temporary sale and service of alcohol at fairs, festivals, galas, and pop-up events must reconcile a genuinely multi-party process: an event organizer assembles a package of supporting documents, several independent public-safety agencies sign off in parallel, a licensing clerk shepherds the file through review and issuance, and a field inspector confirms conditions on the ground before the doors open. This API is the system of record for that entire journey — from the first draft application through multi-agency review, permit issuance, on-site inspection, and the final post-event financial reconciliation.

The platform deliberately separates the people who *advocate* for an event (the organizer), the agencies that *evaluate* its risk (police, fire, and the alcohol board), the clerk who *administers* the file, and the inspector who *verifies* it in the field. Segregation of these duties is a first-class requirement: the clerk who ultimately approves an application must be independent of every agency reviewer who signed it, and an inspector may only record a result for an inspection assigned to them. Woven through the workflow is a strict fiscal ledger that tracks permit fees, a refundable security deposit, violation fines, payments, and refunds so that every application carries an auditable, always-current balance.

Because event dates, venue capacity, insurance coverage, security staffing, and server training all interact, the system computes fees and staffing requirements from live figures at submission time and then *reconciles* them against observed actuals once the event is over. This document specifies the complete contract: the resources, their state machines, the calculations, the validation ordering, and the role-based access rules that together make the process auditable and fair.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All resource collections are mounted under the top-level `/permits` prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing or empty, the request is rejected with `ERR_UNAUTHENTICATED`. If the supplied role is present but is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly four roles, spelled precisely as follows: `Applicant`, `PermitClerk`, `AgencyReviewer`, and `Inspector`.

- An `Applicant` is the event organizer. They create and submit applications, resubmit after revisions, attach servers, insurance policies, and security plans, record payments, contest violations, and file the post-event report.
- A `PermitClerk` is licensing-authority staff who administer venues and inspectors, open and steer the review workflow, verify servers, accept insurance, approve security plans, schedule inspections, issue and close permits, and resolve contested violations.
- An `AgencyReviewer` is an agency representative (police, fire, or alcohol board) who records signoff decisions on agency reviews.
- An `Inspector` is a field inspector who records inspection results and issues violations.

For the `Applicant`, `PermitClerk`, and `AgencyReviewer` roles, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record it where a workflow captures the actor — for example, an agency reviewer's identifier is stored as `recorded_by` on the `AgencyReview` they decide — but it is never compared to any entity's `id`. For the `Inspector` role, `X-User-ID` is the `id` of the acting `Inspector` entity; ownership checks compare a resource's inspector foreign key to `X-User-ID`. Specifically, when an inspector records an inspection result, their `X-User-ID` must equal the inspection's `inspector_id`, and a mismatch is rejected with `ERR_INSPECTOR_MISMATCH`.

All read (GET) endpoints are available to all four roles, and every role may set the logical clock (see §4). Write operations are restricted to the roles named in the endpoint table of §4.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order.

Every list response echoes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties

Most resources expose a common set of system-managed fields:

- `id` — a unique, server-minted UUID with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was last modified. It is refreshed on every mutation.
- `version` — an integer that starts at 1 on creation and increments by 1 on every mutation of the resource. It is the anchor for optimistic concurrency control.

`PermitApplication`, `Venue`, `Inspector`, `EventServer`, `InsurancePolicy`, `SecurityPlan`, `AgencyReview`, `Inspection`, `Violation`, and `PostEventReport` all carry the full set above. The one exception is the `LedgerEntry`, which is an append-only audit record: it carries only `id` and `created_at`. A `LedgerEntry` has no `updated_at` and no `version`, and it is never mutated once written.

Whenever a computed field on a `PermitApplication` changes — for example its `balance_due_cents`, its review counts, or its `deposit_status` — that change counts as a mutation of the application: it refreshes `updated_at` and, except where a dedicated optimistic-concurrency rule already governs the increment, advances `version`.

### 2.5. Nested Resource Retrieval and Existence Ordering

Requests that reference resources by identifier are validated left to right, path identifiers before body foreign keys. If any referenced resource does not exist, the request is rejected with the not-found error specific to that resource — `ERR_APPLICATION_NOT_FOUND`, `ERR_VENUE_NOT_FOUND`, `ERR_INSPECTOR_NOT_FOUND`, `ERR_SERVER_NOT_FOUND`, `ERR_INSURANCE_NOT_FOUND`, `ERR_SECURITY_PLAN_NOT_FOUND`, `ERR_AGENCY_REVIEW_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`, or `ERR_REPORT_NOT_FOUND` — with the first missing identifier in evaluation order determining which error surfaces. The path is always checked before the body.

### 2.6. Monetary Precision and Rounding

All monetary amounts are integer cents. Where a calculation multiplies by a non-integer rate or surcharge, each line item is individually rounded to whole cents using the round-half-up convention, and only the already-rounded line items are summed; the sum itself is not rounded again. Guard counts and attendance figures are whole integers. Any rounding described in §3 uses round-half-up unless stated otherwise.

### 2.7. Optimistic Concurrency Control

Two write operations against a `PermitApplication` are guarded by optimistic concurrency, because the application aggregate is a shared object that several actors mutate. Both require the caller to submit `expected_application_version`, carrying the `version` of the application the caller last observed. If that value does not equal the application's current `version`, the write is rejected with `ERR_STALE_VERSION` (HTTP 412), and the caller must re-read the application before retrying.

- When an agency reviewer records a decision, the decision request must carry `expected_application_version` equal to the target application's current `version`. Because a different agency recording its own still-pending review legitimately advances the shared application (its approved or rejected counts, and therefore its `version`), a decision that carries a pre-advance version is stale and is rejected with `ERR_STALE_VERSION`.
- When an applicant records a payment, the payment request must carry `expected_application_version` equal to the application's current `version`. Because a prior payment or a fee reconciliation legitimately changes `balance_due_cents` and advances `version`, a payment carrying a pre-advance version is stale and is rejected with `ERR_STALE_VERSION`.

Only these two operations take a version field. No other endpoint accepts or requires `expected_application_version`.

### 2.8. Cascading State Propagation and Consistency

Several operations mutate more than one resource in a single atomic step; the secondary effects are as binding as the primary transition.

When a clerk sends an application back for revisions, every `AgencyReview` on that application that is not already `PENDING` is reset to `PENDING`, and each reset review has its `conditions` and `recorded_by` cleared; the application's review counts are recomputed so that `pending_review_count` equals `total_review_count`, `approved_review_count` and `rejected_review_count` return to zero, and `has_conditions` returns to false.

When a scheduled inspection is recorded as failed and its parent application is `APPROVED`, the application cascades to `REVOKED`: the system forfeits the held or paid portion of the deposit by appending a `DEPOSIT_FORFEIT` ledger entry for the smaller of `deposit_cents` and the amount of deposit actually paid, sets `deposit_status` to `FORFEITED`, and recomputes `balance_due_cents` from the new ledger total.

When a post-event report is filed, the application cascades from `PERMIT_ISSUED` to `EVENT_COMPLETE`: the permit fee is reconciled from the report's actuals, a `FEE_ADJUSTMENT` ledger entry is posted for the difference, and `balance_due_cents` is recomputed.

### 2.9. Validation Ordering

When several checks apply to one request, they are evaluated in a fixed priority order so that the surfaced error is deterministic:

1. Authentication — both headers present and non-empty, else `ERR_UNAUTHENTICATED`.
2. Authorization — the role may perform the operation, else `ERR_UNAUTHORIZED`.
3. Existence — all path and body-referenced resources exist (path before body), else the appropriate not-found error.
4. State — the target or parent resource is in the correct state for the operation, else the state-specific conflict error (for example `ERR_APPLICATION_NOT_DRAFT`, `ERR_APPLICATION_NOT_SUBMITTED`, `ERR_APPLICATION_NOT_UNDER_REVIEW`, `ERR_APPLICATION_NOT_APPROVED`, `ERR_REVIEW_NOT_PENDING`, `ERR_INSPECTION_NOT_SCHEDULED`, `ERR_VIOLATION_NOT_CONTESTABLE`, or the generic `ERR_INVALID_STATE`).
5. Optimistic concurrency — `expected_application_version` matches, else `ERR_STALE_VERSION`.
6. Business referential integrity — required linked resources are present and in their required states (all reviews approved, all servers verified, insurance accepted, security approved, inspection passed, required documents present).
7. Business safety thresholds — server certificate valid and unexpired, guard count sufficient, insurance coverage sufficient.
8. Business temporal rules — submission lead time, venue interval overlap, inspector buffer overlap, insurance dates spanning the event, event ended before reporting.
9. Segregation of duties on approval.
10. Fiscal rules — balance fully paid before issuance, deny requires a rejected review, positive payment amount, unresolved violations block close.

Field-shape problems (a missing or wrongly typed body field, or an attendance figure that exceeds the venue's occupancy limit at submit) surface as `ERR_VALIDATION`; an enum field whose value is outside its allowed set surfaces as `ERR_INVALID_ENUM`; an inverted date range surfaces as `ERR_INVALID_DATE_RANGE`.

## 3. Business Logic & Workflows

### 3.1. Reference Registries: Venues and Inspectors

Before any application can proceed, a `PermitClerk` establishes the reference registries. A **Venue** is created with a `name`, an `address`, an `occupancy_limit` (the maximum lawful occupancy per fire code), and an optional `indoor` flag that defaults to true when omitted. The `occupancy_limit` is doubly important downstream: it is the ceiling against which projected attendance is validated, and it participates in security-staffing math.

An **Inspector** is created with a `name`, a `badge_number`, and an `agency` drawn from `POLICE`, `FIRE`, `ALCOHOL_BOARD`, or `HEALTH`. An inspector's `id` is what a person acting in the `Inspector` role presents as their `X-User-ID`, which is why inspection results and violations can be tied back to a specific badge.

### 3.2. Drafting an Application and Attaching Supporting Documents

An `Applicant` opens the process by creating a draft application. The creation payload supplies the `venue_id` of the booked venue, the `organizer_name` of the sponsoring organization, a human-readable `event_name`, the `event_start` and `event_end` instants (ISO 8601 UTC, with `event_end` required to be strictly after `event_start`), the `alcohol_service_hours` during which alcohol will be served, the `expected_attendance` (projected peak attendance), and the `requested_sales_limit_cents` capping gross alcohol sales. A newly created application begins in `DRAFT` with `balance_due_cents` at zero, `deposit_status` of `NONE`, a null `permit_number`, and all review counts at zero. The application's `status`, `permit_fee_cents`, `fee_basis`, `deposit_cents`, and `has_conditions` are system- or system-computed and are never supplied by the client.

While the application is in `DRAFT`, the applicant attaches the three mandatory document types, each referencing its owning application by `application_id`:

- An **Event Server** records a person who will serve alcohol: `full_name`, the training `cert_number`, the `training_provider` (`TIPS`, `SERVSAFE_ALCOHOL`, or `STATE_APPROVED`), the `cert_issued_date`, and the `cert_expiry_date`. A newly added server is `PENDING`.
- An **Insurance Policy** records liability coverage: `insurer_name`, the `coverage_cents` amount, the `effective_date`, and the `expiry_date`. A newly submitted policy is `SUBMITTED`.
- A **Security Plan** commits staffing: `planned_guard_count`, an optional `has_medical_staff` flag defaulting to false, and a free-text `plan_summary`. The plan also carries a computed `required_guard_count`, populated when the plan is created and again whenever the application is submitted. A newly submitted plan is `SUBMITTED`.

### 3.3. Submission: Fee Estimation, the Deposit, and the Gatekeeping Checks

Submitting a draft is the applicant's most consequential action, advancing the application from `DRAFT` to `SUBMITTED`. Submission is refused unless the application is currently `DRAFT` (`ERR_APPLICATION_NOT_DRAFT`) and every gatekeeping condition below holds:

- The event window is coherent — `event_end` must be strictly after `event_start`, else `ERR_INVALID_DATE_RANGE`.
- At least one event server, at least one insurance policy, and at least one security plan already exist for the application, else `ERR_MISSING_REQUIRED_DOCUMENTS`.
- The projected `expected_attendance` must not exceed the booked venue's `occupancy_limit`; an over-occupancy submission is rejected with `ERR_VALIDATION`.
- Submission must be timely. The current logical clock must be at or before the event start minus the minimum submission lead time of 14 days; a submission any later than 14 days before `event_start` is rejected with `ERR_SUBMISSION_TOO_LATE`.
- The venue must be free. No other application for the same `venue_id` that is currently in `SUBMITTED`, `UNDER_REVIEW`, `REVISIONS_REQUESTED`, `APPROVED`, or `PERMIT_ISSUED` may have an event interval that overlaps this one, where each interval is treated as half-open from `event_start` up to but not including `event_end`. An overlap is rejected with `ERR_VENUE_DOUBLE_BOOKED`.

Once these pass, submission computes the estimated permit fee and assesses the deposit. The **permit fee** is built from three line items that are each rounded to whole cents half-up and then summed. The base line is a flat fifty dollars, i.e. 5,000 cents. The attendance line is the attendance multiplied by a per-attendee surcharge of 37.5 cents, rounded half-up. The sales line is the sales figure multiplied by a surcharge rate of 0.0125 (one and a quarter percent), rounded half-up. At submission the estimated variant uses the requested figures — `expected_attendance` for attendance and `requested_sales_limit_cents` for sales — and the result is written to `permit_fee_cents` with `fee_basis` set to `ESTIMATED`. The refundable security **deposit** is a flat 20,000 cents, written to `deposit_cents`.

Submission then posts two ledger entries against the application: a `FEE` entry for the computed permit fee and a `DEPOSIT` entry for the deposit, both as positive debits. It recomputes `balance_due_cents` as the signed sum of every ledger entry, and it recomputes the security plan's `required_guard_count`.

### 3.4. Verifying Servers, Insurance, and Security — the Safety Thresholds

A `PermitClerk` independently clears each supporting document. These operations may run while the application is under review and are the safety gates behind final approval.

**Verifying a server** advances an `EventServer` from `PENDING` to `VERIFIED`. The server must currently be `PENDING` (else `ERR_INVALID_STATE`), its `training_provider` must be one of the three accredited providers, and its `cert_expiry_date` must be on or after the application's `event_end`; a certificate that expires before the event ends is rejected with `ERR_CERT_EXPIRED`.

**Accepting an insurance policy** advances an `InsurancePolicy` from `SUBMITTED` to `ACCEPTED`. The policy must be `SUBMITTED` (else `ERR_INVALID_STATE`). Its `coverage_cents` must meet or exceed the coverage required for the application's attendance tier, else `ERR_INSUFFICIENT_COVERAGE`: an `expected_attendance` below 100 requires at least 100,000,000 cents of coverage (one million dollars); attendance from 100 up to but not including 500 requires at least 200,000,000 cents (two million dollars); attendance of 500 or more requires at least 500,000,000 cents (five million dollars). The policy dates must span the event — its `effective_date` at or before `event_start` and its `expiry_date` at or after `event_end` — else `ERR_INSURANCE_DATES_INVALID`.

**Approving a security plan** advances a `SecurityPlan` from `SUBMITTED` to `APPROVED`. The plan must be `SUBMITTED` (else `ERR_INVALID_STATE`), and its `planned_guard_count` must meet or exceed the required guard count, else `ERR_INSUFFICIENT_SECURITY`. Approval recomputes and stores `required_guard_count`. The **required guard count** is derived from three inputs. Start with a base of the attendance divided by 75 attendees per guard, rounded up to the next whole guard. Add one guard when the event's `alcohol_service_hours` exceeds 5 hours. Add one more guard when the `expected_attendance` is at least ninety percent of the venue's `occupancy_limit` (the ninety-percent boundary is inclusive). Finally, take the greater of that running total and a floor of 2 guards; the result is the required number of guards.

### 3.5. Multi-Agency Review and the Revision Cycle

Once documents are attached and the application is `SUBMITTED`, a `PermitClerk` opens review, advancing the application from `SUBMITTED` to `UNDER_REVIEW` (else `ERR_APPLICATION_NOT_SUBMITTED`). Opening review creates one `AgencyReview` row, each `PENDING`, for each of the three required agencies — police, fire, and the alcohol board — so that `total_review_count` becomes 3. Correspondingly `pending_review_count` is set to 3 while `approved_review_count` and `rejected_review_count` are set to zero. Each `AgencyReview` carries its `application_id`, its `agency`, its `status`, an optional `conditions` text, and the `recorded_by` identifier of the reviewer who decided it.

An `AgencyReviewer` records a decision on a still-`PENDING` review while its parent application is `UNDER_REVIEW`. The decision request carries a `decision` of `APPROVE`, `APPROVE_WITH_CONDITIONS`, or `REJECT`, an optional `conditions` text, and the OCC field `expected_application_version`. The review must be `PENDING` (else `ERR_REVIEW_NOT_PENDING`), the application must be `UNDER_REVIEW` (else `ERR_APPLICATION_NOT_UNDER_REVIEW`), and the version must match (else `ERR_STALE_VERSION`).

- An `APPROVE` decision moves the review to `APPROVED`, stores the reviewer's identifier in `recorded_by`, increments the application's `approved_review_count` by one and decrements `pending_review_count` by one, and advances the application's `version` by one.
- An `APPROVE_WITH_CONDITIONS` decision moves the review to `APPROVED_WITH_CONDITIONS`. It behaves exactly like `APPROVE` for quorum purposes — it too increments `approved_review_count` by one and decrements `pending_review_count` by one and advances the application's `version` by one, and it too records the reviewer — but it additionally requires a non-empty `conditions` text (else `ERR_VALIDATION`), stores that text on the review, and sets the application's `has_conditions` to true.
- A `REJECT` decision moves the review to `REJECTED`, stores the reviewer's identifier in `recorded_by`, increments `rejected_review_count` by one and decrements `pending_review_count` by one, and advances the application's `version` by one.

A clerk may send the file back by requesting revisions, moving the application from `UNDER_REVIEW` to `REVISIONS_REQUESTED` (else `ERR_APPLICATION_NOT_UNDER_REVIEW`); as described in §2.8 this resets every non-`PENDING` review back to `PENDING` and zeroes the approval and rejection counts. The applicant then resubmits, moving the application from `REVISIONS_REQUESTED` back to `UNDER_REVIEW` (the application must be `REVISIONS_REQUESTED`, else `ERR_INVALID_STATE`), closing the revision loop. This cycle may repeat.

### 3.6. Approval, Denial, Inspection, and Issuance

When every signoff is in, a `PermitClerk` approves the application, moving it from `UNDER_REVIEW` to `APPROVED`. Approval enforces a strict battery of checks, and the segregation-of-duties rule is central: the application must be `UNDER_REVIEW` (else `ERR_APPLICATION_NOT_UNDER_REVIEW`); `approved_review_count` must equal `total_review_count`, meaning every agency review is `APPROVED` or `APPROVED_WITH_CONDITIONS` (else `ERR_REVIEWS_NOT_ALL_APPROVED`); all event servers must be `VERIFIED` (else `ERR_SERVERS_NOT_ALL_VERIFIED`); at least one insurance policy must be `ACCEPTED` (else `ERR_INSURANCE_NOT_ACCEPTED`); at least one security plan must be `APPROVED` (else `ERR_SECURITY_PLAN_NOT_APPROVED`); and the approving clerk's `X-User-ID` must not equal the `recorded_by` of any `AgencyReview` on this application (else `ERR_SEGREGATION_OF_DUTIES`), so that the person who signed as an agency cannot also be the person who approves the permit.

Alternatively, when at least one agency has rejected, a clerk may deny the application, moving it from `UNDER_REVIEW` to `DENIED`. Denial requires `rejected_review_count` to be at least one (else `ERR_NO_REJECTED_REVIEW`). On denial, the system makes the organizer whole: for every prior `PAYMENT` ledger entry it appends a compensating `REFUND` ledger entry that negates it, recomputes `balance_due_cents`, sets `deposit_status` back to `NONE`, and marks the application `DENIED`.

An approved application must pass a field inspection before issuance. A `PermitClerk` schedules an **Inspection** by supplying the `application_id`, the `inspector_id`, and the `scheduled_start` and `scheduled_end` of the inspection window, where `scheduled_end` must be strictly after `scheduled_start` (else `ERR_INVALID_DATE_RANGE`). The scheduling is refused if the named inspector already has another inspection whose window falls within 60 minutes of the requested window — that is, the two windows are less than an hour apart — in which case the request is rejected with `ERR_INSPECTOR_UNAVAILABLE`. A new inspection begins `SCHEDULED`.

The assigned `Inspector` records the outcome, supplying a `result` of `PASSED` or `FAILED`. The inspection must be `SCHEDULED` (else `ERR_INSPECTION_NOT_SCHEDULED`), and the recording inspector's `X-User-ID` must equal the inspection's `inspector_id` (else `ERR_INSPECTOR_MISMATCH`); the acting identifier is stored in the inspection's `recorded_by`. A `PASSED` result simply advances the inspection to `PASSED`. A `FAILED` result advances the inspection to `FAILED` and, when the parent application is `APPROVED`, cascades it to `REVOKED` with the deposit forfeiture described in §2.8.

Finally, a `PermitClerk` issues the permit, moving the application from `APPROVED` to `PERMIT_ISSUED`. Issuance requires the application to be `APPROVED` (else `ERR_APPLICATION_NOT_APPROVED`), at least one inspection for the application to have result `PASSED` (else `ERR_INSPECTION_NOT_PASSED`), and `balance_due_cents` to be exactly zero (else `ERR_OUTSTANDING_BALANCE`). On issuance the system assigns a `permit_number`, sets `deposit_status` to `HELD`, and marks the application `PERMIT_ISSUED`.

### 3.7. Paying the Balance

At any point the applicant can pay down the outstanding balance. A payment request carries a positive `amount_cents` and the OCC field `expected_application_version`. The amount must be strictly greater than zero, else `ERR_INVALID_PAYMENT_AMOUNT`. Provided the supplied version matches the application's current `version` (else `ERR_STALE_VERSION`), the system appends a `PAYMENT` ledger entry carrying the negative of the amount, recomputes `balance_due_cents`, and advances the application's `version` by one. This is how an organizer drives the balance to zero ahead of issuance.

### 3.8. Inspections in the Field: Violations and Fines

During or around an inspection, the assigned `Inspector` may issue a **Violation** against that inspection. The payload names the `inspection_id`, a `severity` of `MINOR`, `MAJOR`, or `CRITICAL`, and a free-text `description`. The system copies the owning `application_id` from the parent inspection onto the violation and sets its `status` to `ISSUED`.

Issuing a violation computes its fine. The base fine is 2,500 cents for a `MINOR` violation, 10,000 cents for a `MAJOR` violation, and 25,000 cents for a `CRITICAL` violation. The system counts the prior qualifying violations of the same application — those whose `status` is `ISSUED`, `CONTESTED`, or `UPHELD` and that were created strictly before this one. If there are no such prior violations, the fine equals the base and the `penalty_variant` is `STANDARD`. Otherwise this is a repeat offense: the fine is the base multiplied by a repeat multiplier of 1.5, rounded half-up to whole cents, and the `penalty_variant` is `REPEAT`. The computed amount is written to `fine_cents`, and a `FINE` ledger entry for that amount (a positive debit) is appended and `balance_due_cents` recomputed.

An `Applicant` may contest an issued violation, moving it from `ISSUED` to `CONTESTED`; the violation must be `ISSUED`, else `ERR_VIOLATION_NOT_CONTESTABLE`. A `PermitClerk` then resolves a contested violation by supplying a `decision`. The violation must be `CONTESTED`, else `ERR_INVALID_STATE`. An `UPHELD` decision moves it to `UPHELD` and leaves the original `FINE` ledger entry standing. A `DISMISSED` decision moves it to `DISMISSED` and appends a compensating `FINE_REVERSAL` ledger entry for the negative of the fine, recomputing `balance_due_cents`.

### 3.9. Closeout: Post-Event Reconciliation and the Deposit Refund

After the event has ended, the `Applicant` files a **Post-Event Report**. The payload names the `application_id`, the observed `actual_attendance`, the `gross_sales_cents` of actual alcohol sales, and an optional `incident_count` of reportable incidents that defaults to zero. A report may only be filed once the logical clock has reached or passed the application's `event_end`, else `ERR_EVENT_NOT_ENDED`. Filing creates the report in `FILED` status and cascades the application from `PERMIT_ISSUED` to `EVENT_COMPLETE`.

The cascade reconciles the fee. The permit fee is recomputed with the identical three-line formula from §3.3, but the reconciled variant substitutes the report's actuals — `actual_attendance` for attendance and `gross_sales_cents` for sales. The recomputed amount is written to the report's `reconciled_fee_cents` and to the application's `permit_fee_cents`, and `fee_basis` becomes `RECONCILED`. A `FEE_ADJUSTMENT` ledger entry is posted for the difference between the reconciled fee and the previous `permit_fee_cents` (which may be negative), and `balance_due_cents` is recomputed.

The final act is closeout by a `PermitClerk`, moving the application from `EVENT_COMPLETE` to `CLOSED`. Close requires the application to be `EVENT_COMPLETE` (else `ERR_INVALID_STATE`) and no violation on the application to be in `ISSUED` or `CONTESTED` — every violation must have reached `UPHELD` or `DISMISSED` — else `ERR_UNRESOLVED_VIOLATIONS`. Closeout settles the deposit through a waterfall. The deductions are a cleanup fee of 15,000 cents when the report's `incident_count` is greater than zero, plus the sum of `fine_cents` across all of the application's `UPHELD` violations. The refunded amount is the greater of zero and `deposit_cents` minus the deductions; the forfeited amount is `deposit_cents` minus the refunded amount, so that the refunded and forfeited portions always sum exactly to `deposit_cents`. When the refunded amount is positive, the system appends a `DEPOSIT_REFUND` ledger entry carrying the negative of the refunded portion; when the forfeited amount is positive, it appends a `DEPOSIT_FORFEIT` ledger entry for the withheld portion. The application's `deposit_status` becomes `REFUNDED` when the full deposit is refunded and `FORFEITED` otherwise, the report's `status` advances to `ACCEPTED`, `balance_due_cents` is recomputed, and the application is `CLOSED`.

The application's `balance_due_cents` is throughout a read-only signed sum of every `LedgerEntry.amount_cents` for the application, where each entry carries an `entry_type` (one of `FEE`, `FEE_ADJUSTMENT`, `DEPOSIT`, `FINE`, `FINE_REVERSAL`, `PAYMENT`, `REFUND`, `DEPOSIT_REFUND`, or `DEPOSIT_FORFEIT`), a signed `amount_cents`, and a human-readable `memo`. Debits owed are positive and credits paid or refunded are negative.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including all state-transition actions — return `200 OK`. The logical-clock endpoint is an administrative test-driving capability that advances the server's logical clock to a supplied `to_iso8601` instant; its startup default is `2026-05-01T00:00:00Z`, which is at or before every default fixture date, and before any call the clock reads exactly this default and never falls back to wall-clock time.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/permits/venues` | Create a venue | PermitClerk |
| GET | `/permits/venues/{id}` | Get a venue | Applicant, PermitClerk, AgencyReviewer, Inspector |
| POST | `/permits/inspectors` | Create an inspector | PermitClerk |
| GET | `/permits/inspectors/{id}` | Get an inspector | Applicant, PermitClerk, AgencyReviewer, Inspector |
| POST | `/permits/applications` | Create a draft permit application | Applicant |
| GET | `/permits/applications` | List applications (filter by `venue_id` or `status`) | Applicant, PermitClerk, AgencyReviewer, Inspector |
| GET | `/permits/applications/{id}` | Get an application | Applicant, PermitClerk, AgencyReviewer, Inspector |
| POST | `/permits/applications/{id}/submit` | Submit a draft application | Applicant |
| POST | `/permits/applications/{id}/open-review` | Open multi-agency review | PermitClerk |
| POST | `/permits/applications/{id}/request-revisions` | Send application back for revisions | PermitClerk |
| POST | `/permits/applications/{id}/resubmit` | Resubmit after revisions | Applicant |
| POST | `/permits/applications/{id}/approve` | Approve application | PermitClerk |
| POST | `/permits/applications/{id}/deny` | Deny application | PermitClerk |
| POST | `/permits/applications/{id}/issue-permit` | Issue the temporary permit | PermitClerk |
| POST | `/permits/applications/{id}/close` | Close application after report | PermitClerk |
| POST | `/permits/applications/{id}/payments` | Record a payment (OCC-guarded) | Applicant |
| POST | `/permits/servers` | Add an event server | Applicant |
| GET | `/permits/servers` | List servers (filter by `application_id`) | Applicant, PermitClerk, AgencyReviewer, Inspector |
| GET | `/permits/servers/{id}` | Get a server | Applicant, PermitClerk, AgencyReviewer, Inspector |
| POST | `/permits/servers/{id}/verify` | Verify a server's training cert | PermitClerk |
| POST | `/permits/insurance-policies` | Submit an insurance policy | Applicant |
| GET | `/permits/insurance-policies` | List insurance policies (filter by `application_id`) | Applicant, PermitClerk, AgencyReviewer, Inspector |
| GET | `/permits/insurance-policies/{id}` | Get an insurance policy | Applicant, PermitClerk, AgencyReviewer, Inspector |
| POST | `/permits/insurance-policies/{id}/accept` | Accept an insurance policy | PermitClerk |
| POST | `/permits/security-plans` | Submit a security plan | Applicant |
| GET | `/permits/security-plans` | List security plans (filter by `application_id`) | Applicant, PermitClerk, AgencyReviewer, Inspector |
| GET | `/permits/security-plans/{id}` | Get a security plan | Applicant, PermitClerk, AgencyReviewer, Inspector |
| POST | `/permits/security-plans/{id}/approve` | Approve a security plan | PermitClerk |
| GET | `/permits/agency-reviews` | List agency reviews (filter by `application_id`) | Applicant, PermitClerk, AgencyReviewer, Inspector |
| GET | `/permits/agency-reviews/{id}` | Get an agency review | Applicant, PermitClerk, AgencyReviewer, Inspector |
| POST | `/permits/agency-reviews/{id}/decide` | Record an agency decision (OCC-guarded) | AgencyReviewer |
| POST | `/permits/inspections` | Schedule an inspection | PermitClerk |
| GET | `/permits/inspections` | List inspections (filter by `application_id` or `inspector_id`) | Applicant, PermitClerk, AgencyReviewer, Inspector |
| GET | `/permits/inspections/{id}` | Get an inspection | Applicant, PermitClerk, AgencyReviewer, Inspector |
| POST | `/permits/inspections/{id}/record-result` | Record inspection result | Inspector |
| POST | `/permits/violations` | Issue a violation against an inspection | Inspector |
| GET | `/permits/violations` | List violations (filter by `inspection_id`) | Applicant, PermitClerk, AgencyReviewer, Inspector |
| GET | `/permits/violations/{id}` | Get a violation | Applicant, PermitClerk, AgencyReviewer, Inspector |
| POST | `/permits/violations/{id}/contest` | Contest a violation | Applicant |
| POST | `/permits/violations/{id}/resolve` | Resolve a contested violation | PermitClerk |
| GET | `/permits/ledger-entries` | List ledger entries (filter by `application_id`) | Applicant, PermitClerk, AgencyReviewer, Inspector |
| GET | `/permits/ledger-entries/{id}` | Get a ledger entry | Applicant, PermitClerk, AgencyReviewer, Inspector |
| POST | `/permits/reports` | File a post-event report | Applicant |
| GET | `/permits/reports` | List reports (filter by `application_id`) | Applicant, PermitClerk, AgencyReviewer, Inspector |
| GET | `/permits/reports/{id}` | Get a report | Applicant, PermitClerk, AgencyReviewer, Inspector |
| POST | `/_clock/set_current_utc` | Set the server logical clock | Applicant, PermitClerk, AgencyReviewer, Inspector |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_ENUM` | 422 |
| `ERR_INVALID_DATE_RANGE` | 400 |
| `ERR_APPLICATION_NOT_FOUND` | 404 |
| `ERR_VENUE_NOT_FOUND` | 404 |
| `ERR_INSPECTOR_NOT_FOUND` | 404 |
| `ERR_SERVER_NOT_FOUND` | 404 |
| `ERR_INSURANCE_NOT_FOUND` | 404 |
| `ERR_SECURITY_PLAN_NOT_FOUND` | 404 |
| `ERR_AGENCY_REVIEW_NOT_FOUND` | 404 |
| `ERR_INSPECTION_NOT_FOUND` | 404 |
| `ERR_VIOLATION_NOT_FOUND` | 404 |
| `ERR_REPORT_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_APPLICATION_NOT_DRAFT` | 409 |
| `ERR_APPLICATION_NOT_SUBMITTED` | 409 |
| `ERR_APPLICATION_NOT_UNDER_REVIEW` | 409 |
| `ERR_APPLICATION_NOT_APPROVED` | 409 |
| `ERR_REVIEW_NOT_PENDING` | 409 |
| `ERR_INSPECTION_NOT_SCHEDULED` | 409 |
| `ERR_VIOLATION_NOT_CONTESTABLE` | 409 |
| `ERR_MISSING_REQUIRED_DOCUMENTS` | 422 |
| `ERR_REVIEWS_NOT_ALL_APPROVED` | 409 |
| `ERR_SERVERS_NOT_ALL_VERIFIED` | 409 |
| `ERR_INSURANCE_NOT_ACCEPTED` | 409 |
| `ERR_SECURITY_PLAN_NOT_APPROVED` | 409 |
| `ERR_INSPECTION_NOT_PASSED` | 409 |
| `ERR_CERT_EXPIRED` | 422 |
| `ERR_INSUFFICIENT_SECURITY` | 422 |
| `ERR_INSUFFICIENT_COVERAGE` | 422 |
| `ERR_INSURANCE_DATES_INVALID` | 422 |
| `ERR_SUBMISSION_TOO_LATE` | 409 |
| `ERR_VENUE_DOUBLE_BOOKED` | 409 |
| `ERR_INSPECTOR_UNAVAILABLE` | 409 |
| `ERR_EVENT_NOT_ENDED` | 409 |
| `ERR_OUTSTANDING_BALANCE` | 402 |
| `ERR_NO_REJECTED_REVIEW` | 409 |
| `ERR_INVALID_PAYMENT_AMOUNT` | 400 |
| `ERR_UNRESOLVED_VIOLATIONS` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_INSPECTOR_MISMATCH` | 403 |
| `ERR_STALE_VERSION` | 412 |
</content>
</invoke>
