# Coding Bootcamp ISA API — Product Requirements Document

## 1. Introduction

This document specifies a back-office platform for a coding bootcamp that finances tuition through Income Share Agreements (ISAs). The product spans the full student journey — from application and admission into a dated cohort, through enrollment, attendance and curriculum progress tracking, graduation, and ultimately the servicing of the income-share obligation that funds the program. Two financial worlds meet here: an admissions funnel that conserves a fixed number of seats per cohort, and a long-running repayment ledger that accrues monthly obligations against a student's verified income, subject to a share percentage, a lifetime cap, a fixed term, and an income floor below which nothing is owed.

The platform also carries regulatory weight. Bootcamps that publish under the Council on Integrity in Results Reporting (CIRR) standard must report job-placement outcomes against carefully defined denominators and time windows, and the system computes those placement rates from the same enrollment and outcome data it uses operationally. Around the ISA itself sit the human-facing complications the staff must service every day: deferments when a graduate loses employment or earns below the floor, refunds when a student withdraws (with a cooling-off grace period), scholarships that retroactively lower the repayment cap, and deposits that are either returned or forfeited depending on how the enrollment ends. The requirements below describe every entity, every state transition, every monetary calculation, and every guardrail the implementation must honor.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers identifying the caller: `X-User-ID`, an identifier for the acting user, and `X-User-Role`, which names the operational capacity under which the call is made. If the `X-User-Role` header is absent or names a role the system does not recognize, the request is rejected with `ERR_UNAUTHENTICATED`. When the role is recognized but is not permitted to perform the requested operation under the access matrix, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly four roles, spelled precisely as `AdmissionsOfficer`, `ServicingOfficer`, `ComplianceOfficer`, and `Student`. The `AdmissionsOfficer` runs the admission funnel and cohort lifecycle — applications, admission decisions, enrollment, attendance recording, scholarships, and withdrawals or dismissals. The `ServicingOfficer` services live ISA contracts: filing income reports, collecting and adjusting payments, and managing deferments. The `ComplianceOfficer` owns the refund-approval surface and all CIRR job-placement reporting. The `Student` acts on their own funnel and ISA — applying, withdrawing, filing income, and requesting deferment.

For all four roles, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record it for audit purposes but does not compare it against any entity's `id`; ownership in this system is expressed structurally through foreign-key references between resources rather than by matching the caller's id to a stored field. In particular, the `Student` role does not narrow visibility to a single student's own records at the data layer — authorization is decided purely by whether the role appears in the operation's authorized set.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, must be at least 1, and must not exceed 100. The `offset` parameter is the number of items to skip from the front of the result set; it defaults to 0 and may not be negative. A `limit` above 100, a `limit` below 1, or a negative `offset` is rejected with `ERR_VALIDATION`.

Unless an endpoint states otherwise, list results are sorted by their creation timestamp (`created_at`) in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Most resources in this system are mutable and carry a standard set of system-managed fields. Each such resource has an `id` — a server-minted UUID with no type prefix — and a `created_at` timestamp recorded as an ISO 8601 UTC value with three fractional digits. Mutable resources additionally carry an `updated_at` timestamp, refreshed on every change to the resource, and a `version` integer that begins at `1` on creation and increments by one on each mutation. The mutable resources are Cohort, Applicant, Enrollment, ISAContract, Scholarship, Deposit, IncomeReport, Payment, DefermentRequest, RefundRequest, PlacementOutcome, and CIRRReport.

The single exception is the AttendanceRecord, which is an append-only event log entry. An AttendanceRecord carries only `id` and `created_at`; it has neither an `updated_at` field nor a `version` field, because once written it is never modified.

### 2.5. Mutation Semantics, Cascades, and Derived-Field Consistency

A great deal of this system's behavior is indirect: a single client action frequently mutates several resources at once. Whenever the server changes any persisted field of a mutable resource — whether at the client's direct request or as an automatic consequence of another operation — it refreshes that resource's `updated_at` and increments its `version`. This applies equally to derived fields. When a payment settlement changes an `ISAContract`'s `amount_paid_cents`, or a scholarship application recomputes its `cap_cents`, the contract is a mutated resource and its `version` advances accordingly.

Several invariants must hold at all times. On a Cohort, `seats_committed` plus `seats_available` always equals `capacity`, where `seats_committed` is the count of that cohort's enrollments whose `status` is `ENROLLED`, `ACTIVE`, or `GRADUATED`, and `seats_available` is `capacity` minus `seats_committed`. On an ISAContract, `amount_paid_cents` plus `remaining_cap_cents` always equals `cap_cents`; `amount_paid_cents` is the sum of the `amount_cents` of that contract's payments whose collection has settled, `payments_made_count` is the count of those settled payments, and `remaining_cap_cents` is `cap_cents` minus `amount_paid_cents`. These derived fields are reconciled immediately as the underlying payment ledger changes — the system never serves a contract whose ledger fields disagree with its payment rows.

### 2.6. Nested Resource Retrieval and Left-to-Right Validation

Several read endpoints address a child collection through a parent's identifier — for example, listing the enrollments under a cohort, the payments under an ISA contract, or the attendance records under an enrollment. For any request whose path names more than one resource, the server validates the identifiers from left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier in the path that does not resolve to an existing row, before considering anything to its right. The same left-to-right existence discipline applies to identifiers supplied in a request body: a create whose body references a non-existent parent is a `ERR_NOT_FOUND`, evaluated before deeper business rules run.

### 2.7. Monetary Precision and Rounding

All monetary amounts are integers denominated in whole cents; there are no fractional cents anywhere in the system. Wherever a calculation produces a non-integer cent value — multiplying an income by a share fraction, prorating tuition, or computing an administrative fee — the result is rounded to the nearest whole cent using the round-half-up rule (a value exactly halfway between two cents rounds up to the larger). The CIRR placement rate is the sole non-cent quantity: it is a fraction rounded to four decimal places, also using round-half-up. The exact order in which rounding is applied within each multi-step calculation is pinned and is described with that calculation in Section 3; rounding order is never left to implementer discretion.

### 2.8. Validation Ordering

When several checks could reject the same request, they are evaluated in a fixed precedence so that the returned `error_id` is deterministic. Authentication comes first: a missing or unrecognized role yields `ERR_UNAUTHENTICATED`. Authorization comes next: a recognized role lacking permission for the operation yields `ERR_FORBIDDEN`. Then existence: every path or body resource id must resolve to an existing row (validated left to right per Section 2.6), failing with `ERR_NOT_FOUND`. Then request shape: list endpoints validate pagination bounds (`ERR_VALIDATION`), and write endpoints validate that the body is well-formed — required fields present, enum values legal, numeric ranges respected — failing with `ERR_INVALID_REQUEST`. Then state: a transition attempted from a state in which it is not defined yields `ERR_INVALID_STATE`. Then the optimistic-concurrency check on scholarship application yields `ERR_STALE_VERSION`. Only after all of these do the domain-specific business rules described in Section 3 run; among those, each rule's own narrative states the conditions under which it fires, and where two business rules guard one operation their relative order is stated alongside them.

### 2.9. Optimistic Concurrency on Scholarship Application

Applying a scholarship is the one operation in this system that is guarded by optimistic concurrency control, because a scholarship rewrites the linked ISA contract's repayment cap and supersedes any prior award on the same enrollment. The request to apply a scholarship must carry an `expected_enrollment_version` field — it is mandatory, not optional — holding the `version` of the target enrollment as the client last observed it. The server compares that value against the enrollment's current `version`. If another writer has already applied a scholarship to the same enrollment (legitimately superseding the prior award and incrementing the enrollment's `version`), the submitting client's view is stale, and its create is rejected with `ERR_STALE_VERSION` at HTTP 412, preventing it from silently overwriting a cap recomputation it never saw. No other endpoint accepts or requires a version field.

### 2.10. A Server-Controlled Clock for Time-Gated Transitions

Because cohort transitions and refund grace periods are gated on calendar dates, the system maintains a single logical "current" UTC instant that test harnesses can advance deliberately. An administrative capability accepts a target instant and sets the server's current clock to it; thereafter all time comparisons — whether a cohort's start lies in the future, whether instruction may begin, whether a cohort may graduate, and whether a cooling-off refund is still in its window — are measured against that clock rather than wall time.

## 3. Business Logic & Workflows

### 3.1. Founding and Advancing a Cohort

A `AdmissionsOfficer` opens the system by creating a **Cohort**, supplying its `name`, its `track` (one of `FULLSTACK`, `DATA`, or `CYBER`), a `capacity` of at least one seat, a `tuition_sticker_cents` sticker price of zero or more, a `start_date` and an `end_date` (which must fall after the start), and a `cirr_period_label` such as a half-year reporting tag. A freshly created cohort begins life in `PLANNING` with `seats_committed` at zero and `seats_available` equal to its `capacity`.

A cohort walks a fixed path: `PLANNING → OPEN → RUNNING → GRADUATED → ARCHIVED`. Opening a cohort moves it from `PLANNING` to `OPEN` and is permitted only when its `start_date` is still in the future relative to the current clock; an attempt to open a cohort whose start has already passed is rejected with `ERR_COHORT_TIMING`. Once `OPEN`, the cohort accepts admissions. Starting instruction advances the cohort from `OPEN` to `RUNNING` and requires that the current clock has reached or passed `start_date`; otherwise it too fails with `ERR_COHORT_TIMING`. When a cohort starts, every enrollment in that cohort currently in `ENROLLED` transitions to `ACTIVE` as a cascade, which enables attendance and progress recording for those students; ISA-financed enrollments keep their ISA contract in `PENDING` for now.

Graduating a cohort moves it from `RUNNING` to `GRADUATED` and requires the current clock to have reached or passed `end_date`, again guarded by `ERR_COHORT_TIMING`. This is a consequential cascade: every `ACTIVE` enrollment whose `progress_pct` has reached 100 or more transitions to `GRADUATED`, and for each such graduating enrollment that chose ISA financing, its `PENDING` ISA contract is activated to `ACTIVE`. Finally, archiving moves a cohort from `GRADUATED` to `ARCHIVED`, freezing it against any further admissions or enrollment changes; archiving is permitted only when no ISA contract belonging to that cohort remains in `PENDING`. Each of these four lifecycle steps is reserved to the `AdmissionsOfficer`, and any attempt to drive a cohort through a transition not defined from its present state is an `ERR_INVALID_STATE`.

### 3.2. The Admission Funnel: Applicants and Seats

Prospective students enter as **Applicants**. An application — which a `Student` may submit on their own behalf, or an `AdmissionsOfficer` may file — carries the `cohort_id` of the cohort applied to, the applicant's `full_name`, their `email` (stored as supplied; the system does not enforce any uniqueness constraint on it, so two applicants in the same cohort may share an `email`), and a self-reported `reported_prior_income_cents` figure of zero or more. A new applicant starts in `APPLIED`. Its lifecycle is `APPLIED → ADMITTED → ENROLLED`, with side exits to `REJECTED` from `APPLIED` and to `WITHDRAWN_APP` from `ADMITTED`.

Admitting an applicant moves it from `APPLIED` to `ADMITTED`, stamps `admitted_at` with the decision time, and is allowed only when the target cohort is `OPEN` and has at least one seat available; if the cohort is not `OPEN` the admission is rejected with `ERR_INVALID_STATE` (this not-`OPEN` check precedes the seat check), and if the cohort is `OPEN` but has no free seat the admission is rejected with `ERR_COHORT_FULL`. Rejecting an applicant moves it from `APPLIED` to `REJECTED`, removing them from the funnel. An admitted applicant who never enrolls can be withdrawn to `WITHDRAWN_APP`, but only while no enrollment yet exists for them; this exit consumes no seat. Admission, rejection, and pre-enrollment withdrawal are `AdmissionsOfficer` actions, though a `Student` may also withdraw their own admitted application. A seat is not actually committed at admission — the reservation happens at enrollment, described next.

### 3.3. Enrollment, Deposits, and Opening an ISA

Enrolling an admitted applicant is the pivot of the whole system and is performed by an `AdmissionsOfficer`. The enrollment request names the `applicant_id` of the admitted applicant, a `financing_choice` of either `ISA` or `UPFRONT`, a `deposit_amount_cents` figure, and — only when the financing choice is `ISA` — the four ISA terms: `isa_income_share_pct`, `isa_cap_cents`, `isa_term_months`, and `isa_income_threshold_cents`. Enrollment is allowed only when the applicant is `ADMITTED` and the cohort still has a seat free; a full cohort rejects the enrollment with `ERR_COHORT_FULL`.

A successful enrollment does several things at once. The applicant transitions `ADMITTED → ENROLLED`. A new **Enrollment** resource is created in `ENROLLED` status, copying the applicant's cohort into its own `cohort_id`, recording its `applicant_id` and `financing_choice`, and stamping `enrolled_at` (which later anchors the refund cooling-off window). The owning cohort's `seats_committed` increases by one, conserving the seat. A **Deposit** is created in `HELD` status holding `amount_cents` equal to the supplied deposit, with `refunded_amount_cents` sitting at zero until a refund or forfeiture resolves it. And if the financing choice was `ISA`, an **ISAContract** is created in `PENDING` status linked to this enrollment by its `enrollment_id`, carrying the share fraction in `income_share_pct`, the lifetime ceiling in `cap_cents`, the maximum number of monthly payments in `term_months`, and the monthly income floor in `income_threshold_cents`. The ISA's `income_share_pct` must be greater than zero and at most one half; `cap_cents` and `income_threshold_cents` must be zero or more; `term_months` must be at least one. The enrollment surfaces the linked contract's status through a mirrored `isa_status` field, which is null for `UPFRONT` enrollments that have no contract.

An enrollment runs `ENROLLED → ACTIVE → {GRADUATED | DISMISSED | WITHDRAWN}`. The `ENROLLED → ACTIVE` step happens automatically when the owning cohort starts (Section 3.1), not by direct request.

### 3.4. Attendance, Progress, and the Path to Graduation

Once an enrollment is `ACTIVE`, the `AdmissionsOfficer` records session events. Each **AttendanceRecord** names its `enrollment_id`, the `session_date` of the session, a `present` boolean for whether the student attended, and a `cumulative_progress_pct` capturing curriculum completion at that session, which must lie between 0 and 100 inclusive. Recording a session refreshes two computed fields on the enrollment. The `attendance_pct` is one hundred times the number of present sessions divided by the total number of recorded sessions, and is zero when no sessions have been recorded. The `progress_pct` is the `cumulative_progress_pct` of the most recently created attendance record, again zero when none exist.

Graduation can reach an enrollment two ways. The cohort-wide cascade described in Section 3.1 graduates every qualifying `ACTIVE` enrollment at once. Alternatively, the `AdmissionsOfficer` may directly graduate a single `ACTIVE` enrollment, moving it `ACTIVE → GRADUATED`; this direct route is guarded by the requirement that the enrollment's `progress_pct` has reached 100 or more, and an attempt below that bar is rejected with `ERR_PROGRESS_INCOMPLETE`. By either path, graduating an ISA-financed enrollment activates its linked `PENDING` ISA contract to `ACTIVE` as a cross-entity cascade — the moment at which income reporting and payment collection become possible and the contract's `remaining_cap_cents` is set equal to its `cap_cents`. A graduate still counts toward `seats_committed`.

Two darker exits also leave the `ACTIVE` state. Dismissing an enrollment for poor attendance moves it `ACTIVE → DISMISSED`, but is justified only when the enrollment's `attendance_pct` is below 50; a dismissal attempted at or above 50 percent attendance is rejected with `ERR_DISMISSAL_NOT_JUSTIFIED`. A dismissal releases the seat (decrementing the cohort's `seats_committed` by one), voids any linked `PENDING` ISA contract to `VOIDED`, and forfeits the deposit by moving it `HELD → FORFEITED`. Both dismissal and direct graduation are `AdmissionsOfficer` operations.

### 3.5. Withdrawal and the Refund Workflow

Withdrawal can occur from either `ENROLLED` or `ACTIVE`, in both cases moving the enrollment to `WITHDRAWN`. A `Student` may withdraw their own enrollment, as may an `AdmissionsOfficer`. The withdrawal request optionally carries a `refund_reason`, which when supplied must be one of the RefundRequest reasons `COOLING_OFF`, `WITHDRAWAL`, or `DISMISSAL_APPEAL` (any other value is rejected with `ERR_INVALID_REQUEST`) and is copied verbatim onto the opened request's `reason`. Withdrawing releases the seat by decrementing `seats_committed`, voids any linked `PENDING` ISA contract to `VOIDED`, and opens a **RefundRequest** in `PENDING` status against the withdrawing enrollment. A withdrawal from `ENROLLED` may be characterized as a cooling-off or a withdrawal refund, whereas a withdrawal from `ACTIVE` produces a withdrawal-reason refund; when `refund_reason` is omitted the opened request's `reason` defaults to `COOLING_OFF` for a withdrawal from `ENROLLED` and to `WITHDRAWAL` for a withdrawal from `ACTIVE`.

A RefundRequest names its `enrollment_id`, a `reason` of `COOLING_OFF`, `WITHDRAWAL`, or `DISMISSAL_APPEAL`, and a system-stamped `requested_at` that drives the cooling-off boundary. It carries two computed money fields — `gross_refund_cents` and `net_refund_cents` — that remain to be filled until the request is resolved. Its lifecycle is `PENDING → {APPROVED | REJECTED}`, owned by the `ComplianceOfficer`.

Approving a refund computes the amounts (Section 3.6) and is gated by two checks. First, if the reason is `COOLING_OFF`, the time elapsed between the request's `requested_at` and the enrollment's `enrolled_at` must be 14 days or fewer, counting the fourteenth day as still inside the window; a cooling-off request filed after that grace period expires is rejected with `ERR_COOLING_OFF_EXPIRED`. Second, the deposit linked to the refund's enrollment must still be `HELD`; if that deposit has already been refunded, forfeited, or otherwise resolved, approval is rejected with `ERR_DEPOSIT_ALREADY_RESOLVED`. Of these two business checks, the cooling-off timing is evaluated before the deposit-state check. On approval, the request moves `PENDING → APPROVED`, the gross and net amounts are computed and recorded, and the linked deposit transitions `HELD → REFUNDED` with its `refunded_amount_cents` set to the refunded sum — specifically the request's `net_refund_cents` (the gross less the administrative fee), not the gross; the seat was already released by the withdrawal that opened the request. Rejecting a refund instead moves it `PENDING → REJECTED` and forfeits the deposit, moving it `HELD → FORFEITED` with `refunded_amount_cents` left at zero.

### 3.6. Computing a Refund

The refund amount is built from two independently rounded lines that are then summed, after which a rounded administrative fee is deducted — the order is pinned and must not be collapsed into a single rounding step.

The first line is the deposit refund. For a `COOLING_OFF` reason, the deposit line is the full deposit `amount_cents`. For any other reason, the deposit line retains ten percent of the deposit: it is the deposit `amount_cents` multiplied by the quantity one minus ten percent (that is, by ninety percent), rounded half-up to whole cents. The second line is the unused-tuition proration. For a `COOLING_OFF` reason this tuition line is zero, since no instruction has been consumed. For any other reason, the tuition line is the cohort's `tuition_sticker_cents` multiplied by the unconsumed fraction of the curriculum — that is, by one minus the enrollment's `progress_pct` divided by 100 — and then multiplied by a proration weight of one half, with the whole product rounded half-up to whole cents.

The `gross_refund_cents` is the sum of those two independently rounded lines. The administrative fee is the `gross_refund_cents` multiplied by five percent, rounded half-up to whole cents. The `net_refund_cents` is the `gross_refund_cents` minus that rounded administrative fee. The administrative fee applies to the gross even in the cooling-off case, where the gross consists solely of the full deposit.

### 3.7. Scholarships and the Repayment Cap

A scholarship retroactively lowers the cost of an ISA. The `AdmissionsOfficer` applies a **Scholarship** to an enrollment, naming its `enrollment_id`, a `kind` of `DEI`, `MERIT`, or `NEED`, and a `cap_reduction_pct` strictly greater than zero and at most one. A scholarship begins in `APPLIED`. Because applying one rewrites financial state, the request must carry `expected_enrollment_version` matching the enrollment's current `version`, and a mismatch is refused with `ERR_STALE_VERSION` as described in Section 2.9.

Applying a scholarship has two effects. Any prior scholarship still in `APPLIED` on the same enrollment is superseded, transitioning `APPLIED → SUPERSEDED` so that it stops contributing to the cap reduction; the newest award's `cap_reduction_pct` governs going forward. The linked ISA contract's `cap_cents` is recomputed to reflect the reduction — it is set to the contract's original cap at enrollment (the cap before any scholarship was applied) multiplied by the quantity one minus the newest award's `cap_reduction_pct`, rounded half-up to whole cents; because the recompute always starts from that original base cap rather than the already-reduced cap, successive awards do not compound and the newest award's reduction alone governs the resulting `cap_cents`, and the enrollment's `version` is incremented by one — the very increment that makes a concurrent writer's `expected_enrollment_version` stale.

### 3.8. Servicing the ISA: Income Reports and Monthly Obligations

Once an ISA contract is `ACTIVE`, the obligation accrues month by month from filed income. A `ServicingOfficer`, or the `Student` themselves, files an **IncomeReport** naming the `isa_contract_id` it covers, a `period_start` (the first day of the monthly period, inclusive), a `period_end` (the first day of the following month, exclusive — so the period is the half-open interval from start up to but not including end), a verified `gross_income_cents` of zero or more, and an `employment_status` of `EMPLOYED`, `UNEMPLOYED`, or `UNDEREMPLOYED`. A report's monthly period may not overlap an existing report for the same contract; an overlapping half-open period is rejected with `ERR_INCOME_PERIOD_OVERLAP`.

Filing a report computes the obligation for that period and stamps it onto `obligation_cents`, following a strictly ordered rule. If the contract is currently `DEFERRED`, the obligation is zero — no obligation accrues while deferred. Otherwise, if the reported `gross_income_cents` is at or below the contract's `income_threshold_cents`, the obligation is zero; the floor is inclusive, so income exactly equal to the threshold owes nothing. Otherwise, if the contract's `payments_made_count` has already reached or exceeded its `term_months`, the term is exhausted and the obligation is zero. Only when none of those apply does a positive obligation arise: the system multiplies `gross_income_cents` by `income_share_pct` and rounds that product half-up to whole cents (the multiply happens first and the share fraction is never rounded on its own), then clamps the result to the contract's current `remaining_cap_cents` so the obligation is the smaller of the rounded share and the remaining cap. This clamp guarantees `amount_paid_cents` can never overshoot `cap_cents`.

When the computed `obligation_cents` is greater than zero, the report spawns a **Payment** in `PENDING` collection status, and the report's `payment_id` back-pointer is set to that payment; when the obligation is zero, no payment is created and `payment_id` stays null. The payment that results records the `isa_contract_id` of the contract being paid down, the `income_report_id` of the report that generated it, and an `amount_cents` equal to the report's `obligation_cents` at creation time.

### 3.9. Collecting, Failing, Retrying, and Reversing Payments

A **Payment** carries two independent status dimensions plus a rollup. Its `collection_status` runs `PENDING → {SETTLED | FAILED}`, with `FAILED → PENDING` available on retry. Its `refund_status` is a separate dimension, `NONE → REFUNDED`, meaningful only on a settled payment. The exposed `status` is a computed rollup: it mirrors `collection_status` as `PENDING`, `FAILED`, or `SETTLED`, unless `refund_status` is `REFUNDED`, in which case the rollup reads `REVERSED`. All payment lifecycle actions belong to the `ServicingOfficer`.

Settling a payment moves its `collection_status` from `PENDING` to `SETTLED`, but only when the linked ISA contract is `ACTIVE` — a `DEFERRED` contract blocks settlement, and an attempt against a contract not in `ACTIVE` is an `ERR_INVALID_STATE`. Settlement is where the ledger advances: the contract's `amount_paid_cents` increases by the payment's `amount_cents` and `remaining_cap_cents` is recomputed. Settlement may then cascade the contract to a terminal state. If after settlement `amount_paid_cents` has reached or exceeded `cap_cents`, the contract transitions `ACTIVE → COMPLETED`, no further payments are owed, `remaining_cap_cents` becomes zero, and the linked enrollment's `isa_status` mirrors the completion. If instead `payments_made_count` has reached or exceeded `term_months` after settlement while `amount_paid_cents` is still below `cap_cents`, the contract transitions `ACTIVE → SETTLED_TERM`, owing nothing further even though the cap was never reached, with `remaining_cap_cents` frozen at the residual. The cap-reached branch and the term-reached branch are checked against the post-settlement ledger, and the cap-reached condition takes precedence when both could apply.

Failing a payment moves its `collection_status` from `PENDING` to `FAILED` with no ledger change, marking it uncollected. Retrying returns a failed payment from `FAILED` back to `PENDING` for re-collection, and is permitted only while the linked contract is `ACTIVE`. Refunding reverses a settled collection: it requires the payment's `collection_status` to be `SETTLED` and its `refund_status` to be `NONE`, sets `refund_status` to `REFUNDED` so the rollup `status` becomes `REVERSED`, and applies a compensating reversal to the ledger by subtracting the payment's `amount_cents` from the contract's `amount_paid_cents`. If that reversal lands on a contract that had reached `COMPLETED` or `SETTLED_TERM`, the contract reverts to `ACTIVE`.

### 3.10. Deferments

When a graduate cannot pay, the `ServicingOfficer` — or the `Student` — opens a **DefermentRequest** against an ISA contract, naming its `isa_contract_id`, a `reason` of `UNEMPLOYMENT` or `INCOME_FLOOR`, and a closed coverage interval given by `period_start` (the first day deferment takes effect, inclusive) and `period_end` (the last day it covers, inclusive). A request begins in `REQUESTED` and runs `REQUESTED → {APPROVED | DENIED}`, with `APPROVED → ENDED` available afterward. Deferment decisions are `ServicingOfficer` actions.

Approving a deferment is the most heavily guarded transition in the servicing flow, and its preconditions are evaluated in order. The linked ISA contract must be `ACTIVE`; otherwise the approval is an `ERR_INVALID_STATE`. Then the reason must be supported by the latest income report for the contract: an `UNEMPLOYMENT` deferment requires that the most recent IncomeReport has `employment_status` equal to `UNEMPLOYED`, and an `INCOME_FLOOR` deferment requires that the most recent report's `gross_income_cents` is at or below the contract's `income_threshold_cents`; a reason the latest report does not support is rejected with `ERR_DEFERMENT_INELIGIBLE`. Finally, the requested window must not overlap any prior deferment window for the same contract that was ever approved — whether it is still `APPROVED` or has since `ENDED` — and the overlap test treats the intervals as closed and includes a one-day buffer on each side, so a span stays reserved even after it ends; a colliding window is rejected with `ERR_DEFERMENT_OVERLAP`. On approval the request moves `REQUESTED → APPROVED` and the contract cascades `ACTIVE → DEFERRED`, after which no new payment obligation accrues for periods inside the window and the term clock effectively pauses.

Denying a deferment moves the request `REQUESTED → DENIED` with no effect on the contract. Ending an approved deferment moves the request `APPROVED → ENDED` and requires the contract to be `DEFERRED`; it cascades the contract `DEFERRED → ACTIVE`, resuming payment obligations for periods after the window. This `ACTIVE ↔ DEFERRED` loop may repeat over the life of a contract.

### 3.11. The Dual-View ISA Ledger: Actual vs. Projected Payoff

An ISA contract exposes two different answers to "how much will this be paid." The chronological-actual view is simply `amount_paid_cents` — the running sum of payments actually settled so far, which lags reality. The forward-looking view is `projected_payoff_cents`, a computed estimate of the eventual total assuming the student's latest reported income repeats every remaining month. A computed read also exposes both views and accepts an optional `variant` selector to choose between the projected and the chronological figure. The read's response always carries both fields — `amount_paid_cents` (the chronological-actual figure) and `projected_payoff_cents` (the headline figure the `variant` selects); the selector only changes which value is placed in `projected_payoff_cents`, never the `amount_paid_cents` field. A `variant` of `PROJECTED`, or the selector omitted entirely (the default), places the forward-looking projection in `projected_payoff_cents`; a `variant` of `CHRONOLOGICAL` or `ACTUAL` instead places the chronological `amount_paid_cents` value in `projected_payoff_cents`. Any other variant value is treated as the default (projected).

The projection is computed as follows. The system identifies the latest income report for the contract, ordering by `period_start` descending and breaking ties by `created_at` descending. If there is no income report at all, or the contract is in `COMPLETED`, `SETTLED_TERM`, or `VOIDED`, the projection is just `amount_paid_cents`. Otherwise, a per-month figure is formed: the latest report's `gross_income_cents` multiplied by `income_share_pct`, rounded half-up to whole cents, then bounded below by zero and above by `cap_cents` — that is, the per-month amount is the larger of zero and the smaller of the rounded share and `cap_cents`. The number of remaining months is `term_months` minus `payments_made_count`. The projection is then `amount_paid_cents` plus the per-month figure times the remaining months, with the whole sum capped at `cap_cents` — the projection is the smaller of `cap_cents` and that running total, so it can reach the cap early. The projected figure is always at least the chronological `amount_paid_cents`.

### 3.12. CIRR Placement Reporting

After graduation, the `ComplianceOfficer` records job outcomes and publishes placement statistics. A **PlacementOutcome** describes a single graduate, naming its `enrollment_id`, a `category` drawn from `EMPLOYED_IN_FIELD`, `EMPLOYED_OUT_OF_FIELD`, `SELF_EMPLOYED`, `CONTINUED_EDUCATION`, `STILL_SEEKING`, or `OUT_OF_PROGRAM`, a `reported_at` date relative to graduation, and optionally an `annual_salary_cents` starting salary and a `placement_days` count of days from graduation to placement. An outcome may only be reported for a `GRADUATED` enrollment; reporting one for a non-graduate is rejected with `ERR_OUTCOME_NOT_GRADUATE`. When the category is `EMPLOYED_IN_FIELD` or `EMPLOYED_OUT_OF_FIELD`, the `annual_salary_cents` is required, and an employed outcome missing it is rejected with `ERR_SALARY_REQUIRED`.

Each outcome computes a `cirr_eligible` boolean. An outcome counts toward CIRR when two conditions both hold: its category is a countable placement — one of `EMPLOYED_IN_FIELD`, `EMPLOYED_OUT_OF_FIELD`, or `SELF_EMPLOYED` — and it was placed within the reporting window, meaning `placement_days` is present and is 180 or fewer. An outcome that is not a countable category, or whose `placement_days` is absent or exceeds 180, is not eligible.

A **CIRRReport** rolls these outcomes up for a cohort. The `ComplianceOfficer` creates one in `DRAFT` naming the `cohort_id` and a `denominator_basis` of either `GRADUATES_ONLY` or `ALL_ENROLLED`. The report derives several counts over the cohort: `graduates_count` is the number of enrollments whose `status` is `GRADUATED`; `enrolled_count` is the number of enrollments whose `status` is `ACTIVE`, `GRADUATED`, `DISMISSED`, or `WITHDRAWN`; and `placed_count` is the number of placement outcomes that are `cirr_eligible` for graduates in this cohort. The `placement_rate` is `placed_count` divided by a denominator chosen by `denominator_basis` — `graduates_count` under `GRADUATES_ONLY`, or `enrolled_count` under `ALL_ENROLLED` — rounded to four decimal places using round-half-up; when the chosen denominator is zero the rate is defined as zero. Because the same `placed_count` is divided by a larger denominator under `ALL_ENROLLED`, that basis yields a lower rate for identical placements.

Publishing a report moves it `DRAFT → PUBLISHED` and freezes `graduates_count`, `enrolled_count`, `placed_count`, and `placement_rate` at publish time. A report may be published only when its cohort's `status` is `GRADUATED` or `ARCHIVED`; an attempt to publish before graduation is an `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

Operations that create a brand-new resource return `201 Created`; operations that read a resource or drive a state transition on an existing resource return `200 OK`. The administrative clock-setting capability returns `200 OK`. The request body, response body, and side effects of each operation are described in the Section 3 narratives above; the table below is only a routing and authorization summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/cohorts` | Create a cohort | AdmissionsOfficer |
| GET | `/cohorts/{id}` | Get a cohort | AdmissionsOfficer, ServicingOfficer, ComplianceOfficer, Student |
| GET | `/cohorts` | List cohorts | AdmissionsOfficer, ServicingOfficer, ComplianceOfficer, Student |
| POST | `/cohorts/{id}/open` | Open a cohort for admissions | AdmissionsOfficer |
| POST | `/cohorts/{id}/start` | Start instruction; cascade enrollments to active | AdmissionsOfficer |
| POST | `/cohorts/{id}/graduate` | Graduate the cohort; cascade qualifying enrollments and ISA activation | AdmissionsOfficer |
| POST | `/cohorts/{id}/archive` | Archive a graduated cohort | AdmissionsOfficer |
| GET | `/cohorts/{id}/enrollments` | List enrollments for a cohort | AdmissionsOfficer, ServicingOfficer, ComplianceOfficer |
| GET | `/cohorts/{id}/cirr-reports` | List CIRR reports for a cohort | ComplianceOfficer |
| POST | `/applicants` | Submit an application to a cohort | AdmissionsOfficer, Student |
| GET | `/applicants/{id}` | Get an applicant | AdmissionsOfficer, Student |
| GET | `/applicants` | List applicants, filterable by cohort | AdmissionsOfficer |
| POST | `/applicants/{id}/admit` | Admit an applicant | AdmissionsOfficer |
| POST | `/applicants/{id}/reject` | Reject an applicant | AdmissionsOfficer |
| POST | `/applicants/{id}/withdraw` | Withdraw an admitted applicant before enrolling | AdmissionsOfficer, Student |
| POST | `/enrollments` | Enroll an admitted applicant | AdmissionsOfficer |
| GET | `/enrollments/{id}` | Get an enrollment | AdmissionsOfficer, ServicingOfficer, ComplianceOfficer, Student |
| GET | `/enrollments` | List enrollments, filterable by applicant | AdmissionsOfficer, ServicingOfficer, ComplianceOfficer |
| POST | `/enrollments/{id}/graduate` | Directly graduate a single active enrollment | AdmissionsOfficer |
| POST | `/enrollments/{id}/dismiss` | Dismiss an enrollment for attendance | AdmissionsOfficer |
| POST | `/enrollments/{id}/withdraw` | Withdraw an enrollment; voids pending ISA and opens a refund | AdmissionsOfficer, Student |
| GET | `/enrollments/{id}/attendance` | List attendance records for an enrollment | AdmissionsOfficer, ServicingOfficer |
| POST | `/attendance-records` | Record a session attendance/progress event | AdmissionsOfficer |
| POST | `/scholarships` | Apply a scholarship to an enrollment | AdmissionsOfficer |
| GET | `/scholarships/{id}` | Get a scholarship | AdmissionsOfficer, ComplianceOfficer |
| GET | `/scholarships` | List scholarships, filterable by enrollment | AdmissionsOfficer, ComplianceOfficer |
| GET | `/deposits/{id}` | Get a deposit | AdmissionsOfficer, ComplianceOfficer, Student |
| GET | `/deposits` | List deposits, filterable by enrollment | AdmissionsOfficer, ComplianceOfficer |
| GET | `/isa-contracts/{id}` | Get an ISA contract with its current ledger | ServicingOfficer, ComplianceOfficer, Student |
| GET | `/isa-contracts` | List ISA contracts, filterable by enrollment | ServicingOfficer, ComplianceOfficer |
| GET | `/isa-contracts/{id}/projection` | Computed read: projected payoff vs chronological actual | ServicingOfficer, ComplianceOfficer, Student |
| GET | `/isa-contracts/{id}/payments` | List payments for a contract | ServicingOfficer, ComplianceOfficer, Student |
| GET | `/isa-contracts/{id}/income-reports` | List income reports for a contract | ServicingOfficer, ComplianceOfficer, Student |
| GET | `/isa-contracts/{id}/deferment-requests` | List deferment requests for a contract | ServicingOfficer, ComplianceOfficer, Student |
| POST | `/income-reports` | File a monthly income report; may create a payment | ServicingOfficer, Student |
| GET | `/income-reports/{id}` | Get an income report | ServicingOfficer, ComplianceOfficer, Student |
| GET | `/payments/{id}` | Get a payment | ServicingOfficer, ComplianceOfficer, Student |
| GET | `/payments` | List payments, filterable by income report | ServicingOfficer, ComplianceOfficer |
| POST | `/payments/{id}/settle` | Settle a pending payment; updates ISA ledger | ServicingOfficer |
| POST | `/payments/{id}/fail` | Mark a pending payment as failed | ServicingOfficer |
| POST | `/payments/{id}/retry` | Return a failed payment to pending | ServicingOfficer |
| POST | `/payments/{id}/refund` | Refund a settled payment; compensating ledger reversal | ServicingOfficer |
| POST | `/deferment-requests` | Request a deferment on an ISA contract | ServicingOfficer, Student |
| GET | `/deferment-requests/{id}` | Get a deferment request | ServicingOfficer, ComplianceOfficer, Student |
| POST | `/deferment-requests/{id}/approve` | Approve a deferment; pauses the contract | ServicingOfficer |
| POST | `/deferment-requests/{id}/deny` | Deny a deferment | ServicingOfficer |
| POST | `/deferment-requests/{id}/end` | End an approved deferment; resumes the contract | ServicingOfficer |
| GET | `/refund-requests/{id}` | Get a refund request | ComplianceOfficer, AdmissionsOfficer, Student |
| GET | `/refund-requests` | List refund requests, filterable by enrollment | ComplianceOfficer, AdmissionsOfficer |
| POST | `/refund-requests/{id}/approve` | Approve a refund; computes amounts and refunds the deposit | ComplianceOfficer |
| POST | `/refund-requests/{id}/reject` | Reject a refund; forfeits the deposit | ComplianceOfficer |
| POST | `/placement-outcomes` | Report a CIRR placement outcome for a graduate | ComplianceOfficer |
| GET | `/placement-outcomes/{id}` | Get a placement outcome | ComplianceOfficer |
| GET | `/placement-outcomes` | List placement outcomes, filterable by enrollment | ComplianceOfficer |
| POST | `/cirr-reports` | Create a draft CIRR report for a cohort | ComplianceOfficer |
| GET | `/cirr-reports/{id}` | Get a CIRR report | ComplianceOfficer |
| POST | `/cirr-reports/{id}/publish` | Publish a CIRR report (freezes computed counts) | ComplianceOfficer |
| POST | `/_clock/set_current_utc` | Test-driving: set the server's current UTC clock | AdmissionsOfficer, ServicingOfficer, ComplianceOfficer |

The list endpoints accept the optional query parameters noted in their descriptions. Cohort listing accepts `status`; applicant listing accepts `cohort_id` and `status`; enrollment listing accepts `applicant_id`, `cohort_id`, and `status`; scholarship, deposit, ISA-contract, refund-request, and placement-outcome listings accept their respective filters and, for the first four, `status`; payment listing accepts `income_report_id`, `isa_contract_id`, and `collection_status`. All list endpoints additionally accept `limit` and `offset`. The clock-setting capability takes a single `to_iso8601` instant in its body, and the projection read accepts an optional `variant` selector.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_COHORT_TIMING` | 409 |
| `ERR_COHORT_FULL` | 409 |
| `ERR_COOLING_OFF_EXPIRED` | 409 |
| `ERR_DEPOSIT_ALREADY_RESOLVED` | 409 |
| `ERR_DISMISSAL_NOT_JUSTIFIED` | 409 |
| `ERR_PROGRESS_INCOMPLETE` | 409 |
| `ERR_DEFERMENT_INELIGIBLE` | 409 |
| `ERR_DEFERMENT_OVERLAP` | 409 |
| `ERR_INCOME_PERIOD_OVERLAP` | 409 |
| `ERR_SALARY_REQUIRED` | 400 |
| `ERR_OUTCOME_NOT_GRADUATE` | 409 |
| `ERR_VALIDATION` | 422 |
