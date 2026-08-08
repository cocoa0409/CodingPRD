# Guardian-ad-Litem & CASA Volunteer Management API — Product Requirements Document

## 1. Introduction

Court-appointed advocacy programs depend on a small corps of trained, thoroughly vetted volunteers who stand in for children navigating the dependency and permanency process. This API is the system of record for that program: it tracks a volunteer from initial prospect through screening, background clearance, training, and swearing-in; appoints sworn volunteers to children's cases; and records the visits, court reports, hearings, and reimbursements that flow from each appointment. The overriding concern is auditable compliance — every eligibility gate, every review by a staff supervisor, and every dollar of reimbursement must be defensible after the fact.

The domain is intentionally cross-cutting rather than a single ownership tree. Volunteers, Supervisors, and Cases are independent roots joined through junction and reference records; a single administrative action (deactivating a volunteer, closing a case) can ripple across several of those roots at once. Because the same case can be reassigned, reports revised, and expenses approved or reversed, the system emphasizes conserved counters, immediate reconciliation of derived fields, and optimistic concurrency so that no actor overwrites work performed on a view of the case they never observed. Segregation of duties is foundational: the volunteer who authors a report can never be the person who reviews it, and only the case's own supervisor may act on that case's reports and expenses.

This document specifies the global contract (Section 2), the business logic and workflows across the volunteer, case, report, hearing, and expense lifecycles (Section 3), the endpoint surface (Section 4), and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules that apply to every endpoint unless a later section states an explicit exception.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. When either header is missing or does not carry a recognized value, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. The system recognizes exactly three roles, spelled precisely as `ProgramAdmin`, `Supervisor`, and `Volunteer`. When a caller holds a valid role but that role — or the ownership relationship it implies — does not permit the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `ProgramAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it against any entity's `id`. When `X-User-Role` is `Supervisor`, `X-User-ID` is the `id` of the acting `Supervisor`; ownership checks on any case-scoped operation compare the case's `supervisor_id` to `X-User-ID`, so a supervisor may review reports, approve expenses, schedule hearings, appoint volunteers, and close a case only when that case's `supervisor_id` equals their own identifier. When `X-User-Role` is `Volunteer`, `X-User-ID` is the `id` of the acting `Volunteer`; ownership checks compare the volunteer foreign key on the addressed resource (for example the `author_volunteer_id` on a court report, or the `volunteer_id` on an expense claim or visit) to `X-User-ID`.

The reviewing `Supervisor` and the authoring `Volunteer` are always disjoint principals — this segregation of duties is enforced structurally, because report review and expense approval are `Supervisor`-only capabilities while report authoring and expense submission are `Volunteer`-only capabilities.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, list responses are sorted by `created_at` in ascending order. Every list response echoes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object.

### 2.4. Common Resource Properties

Most resources carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recorded at creation, read from the logical clock (Section 2.5) rather than wall-clock time. The `updated_at` field is an ISO 8601 UTC timestamp, likewise read from the logical clock, refreshed on every mutation, and the `version` field is an integer that begins at 1 and increments by one on every mutation of the resource. `Volunteer`, `Supervisor`, `Case`, `CaseAssignment`, `Visit`, `Hearing`, `CourtReport`, `BackgroundCheck`, and `ExpenseClaim` all carry the full set of these fields.

Two resources are immutable audit entries and therefore carry only `id` and `created_at` — they have neither `updated_at` nor `version`. A `ReviewNote` records a single review event, and a `TrainingRecord` records a single completed training module; once written, neither is modified.

### 2.5. The Logical Clock

All time-dependent behavior is evaluated against a server logical clock rather than wall-clock time. On startup the clock reads exactly `2026-05-01T00:00:00Z`, and before any client sets it the clock holds that default and never falls back to real time. An administrative test-driving capability accepts a `to_iso8601` instant and advances the clock to it, echoing the new value as `current_utc`. All datetime computations in this document — background expiry, report lead-time, swear-in timing, visit intervals, hearing buffers, and compliance month windows — read "now" from this logical clock.

### 2.6. Optimistic Concurrency on Case Appointments

Appointing a volunteer to a case is guarded by optimistic concurrency control on the parent `Case`. The appointment request must carry `expected_case_version`, which is a required (non-optional) field holding the `version` of the target `Case` that the client last observed. If that value does not equal the case's current `version`, the appointment is rejected with `ERR_STALE_CASE_VERSION` at HTTP status 412. Because a new appointment legitimately supersedes any prior active appointment, a client whose `expected_case_version` lags the case's current `version` has acted on a stale view of the case's assignment state and must re-read before retrying. No other endpoint takes a version field; appointment creation is the only optimistically-concurrent write.

### 2.7. Conserved Counters, Ledgers, and Monetary Precision

Several fields are read-only derived quantities that the system reconciles immediately as underlying rows change, and they are conserved: a mutation and its compensating reversal leave the counter exactly as it began.

A volunteer's `active_case_count` is the number of that volunteer's `CaseAssignment` rows whose `status` is `ACTIVE`. It starts at 0, never falls below 0, increases by one when an appointment is created, and decreases by one whenever one of that volunteer's active assignments ends (by manual end, supersession, case close, or the deactivation cascade). An appointment followed by its compensating end returns the counter to its starting value.

A case's `reimbursement_committed_cents` is the sum of `final_reimbursement_cents` across that case's `ExpenseClaim` rows whose `status` is `APPROVED` or `PAID`. It starts at 0, increases by a claim's final amount at approval, and decreases by that same amount if the approved claim is later voided; approving and then voiding the same claim leaves it unchanged. All monetary amounts are integer cents; the mileage products described in Section 3.7 are rounded half up before being combined.

### 2.8. Cascading State Propagation and Hierarchical Consistency

Because entities are joined by foreign keys rather than owned in a tree, a single operation frequently mutates several resources at once. Whenever the system automatically transitions a related resource, that resource independently refreshes its own `updated_at` and increments its own `version`; likewise the primary resource of the operation refreshes `updated_at` and, where the state machine specifies, increments `version`. The deactivation and resignation cascades (Section 3.9), the case-close cascade (Section 3.8), and the supersession of a prior appointment (Section 3.3) are the principal multi-resource effects; each is specified in full where its workflow lives. Derived-field recomputation (for example a volunteer's `background_status` and `background_expiry_date`, or a case's `contact_compliance_pct`) is likewise treated as an immediate reconciliation.

### 2.9. Nested Resource Retrieval and Existence Ordering

Many paths address a child resource beneath a parent (a visit or hearing or assignment beneath a case, a background check beneath a volunteer). For such requests the system validates identifiers left to right and rejects on the first identifier that does not resolve, using the not-found error for that resource: `ERR_VOLUNTEER_NOT_FOUND`, `ERR_SUPERVISOR_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`, `ERR_HEARING_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_BACKGROUND_CHECK_NOT_FOUND`, or `ERR_EXPENSE_CLAIM_NOT_FOUND`. An assignment identifier that does not belong to the named case resolves to `ERR_ASSIGNMENT_NOT_FOUND`.

### 2.10. Validation Priority Ordering

When more than one condition could reject a request, the system evaluates them in a fixed priority order so that the returned error is deterministic:

1. **Header authentication** — `X-User-ID` and `X-User-Role` present and valid, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400).
2. **Role and ownership authorization** — the acting role is permitted and, for case-scoped actions, the acting supervisor equals the case's `supervisor_id` or the acting volunteer owns the addressed resource, else `ERR_UNAUTHORIZED` (403).
3. **Existence** — every path and body identifier resolves, else the appropriate not-found error (404).
4. **State** — the target and related resources are in a state that permits the operation, else `ERR_INVALID_STATE`, `ERR_CASE_CLOSED`, `ERR_HEARING_NOT_SCHEDULED`, or `ERR_VOLUNTEER_NOT_ACTIVE` (409).
5. **Temporal and interval** — report lead-time, per-volunteer visit overlap, and per-case hearing buffer, else `ERR_REPORT_DEADLINE_PASSED`, `ERR_VISIT_OVERLAP`, or `ERR_HEARING_BUFFER_CONFLICT` (409).
6. **Referential integrity** — the acting volunteer is the case's active-assignment volunteer for visit logging, and a report's hearing belongs to the report's case, else `ERR_NOT_ASSIGNED_VOLUNTEER` or `ERR_HEARING_CASE_MISMATCH` (409).
7. **Eligibility and compliance** — background clearance and training completion, else `ERR_BACKGROUND_EXPIRED` or `ERR_TRAINING_INCOMPLETE` (422).
8. **Caseload capacity** — the appointment target is below its caseload cap, else `ERR_CASELOAD_EXCEEDED` (409).
9. **Fiscal budget** — an expense approval stays within the case budget, else `ERR_EXPENSE_EXCEEDS_BUDGET` (402).
10. **Field validity and concurrency** — required fields present, enums valid, ordering and sign constraints satisfied, and `expected_case_version` matching, else `ERR_VALIDATION` (400) or `ERR_STALE_CASE_VERSION` (412).

The importance of ordering is concrete: because state precedes eligibility, a report submitted against a hearing that is not `SCHEDULED` surfaces as `ERR_HEARING_NOT_SCHEDULED` before any lead-time check; because eligibility precedes the caseload cap, a swear-in that is both training-short and background-expired surfaces the background failure first; and because a closed case fails the state tier, an expense against a `CLOSED` case surfaces `ERR_CASE_CLOSED` before any budget arithmetic.

## 3. Business Logic & Workflows

### 3.1. Volunteer Onboarding: From Prospect to Sworn Advocate

A `ProgramAdmin` registers a prospective advocate by supplying a `full_name`, an `email` (which must be unique among volunteers; a duplicate is an `ERR_VALIDATION`), and a `home_zip` used later as mileage context. An optional `max_caseload` sets how many simultaneous active appointments the volunteer may hold; when omitted it defaults to 2. A newly registered volunteer starts in `PROSPECT` status, with `active_case_count` at 0, `background_status` at `NONE`, `sworn_in_at` and `deactivation_reason` and `background_expiry_date` null, and `training_hours_total` at 0.

Screening begins when a `ProgramAdmin` starts screening on a volunteer, moving `PROSPECT → SCREENING`; if the volunteer is not in `PROSPECT` the request fails with `ERR_INVALID_STATE`. The advance from `SCREENING` to `TRAINING` is never requested directly — it happens automatically as a side effect when the volunteer's most recent background check clears (Section 3.2). Training completion is logged one module at a time: a `ProgramAdmin` or the volunteer themselves records a `TrainingRecord` (a `Volunteer` caller may record only against their own `id`, else `ERR_UNAUTHORIZED`) carrying a `module_name`, the credited `hours` (which must be greater than 0, else `ERR_VALIDATION`), and a `completed_at` instant. Each new record causes the volunteer's read-only `training_hours_total` to be recomputed as the sum of `hours` over all that volunteer's training records.

Swearing in advances `TRAINING → ACTIVE` and is performed by a `ProgramAdmin`. Three gates apply in this order. The volunteer must currently be in `TRAINING`, else `ERR_INVALID_STATE`. The volunteer's `background_status` must be `CLEARED` with the logical clock strictly before `background_expiry_date`, else `ERR_BACKGROUND_EXPIRED`. Finally, `training_hours_total` must be at least 30 hours, else `ERR_TRAINING_INCOMPLETE` — the boundary is inclusive, so exactly 30 hours passes while 29 fails. On success the volunteer's `sworn_in_at` is set to the current clock instant.

### 3.2. Background Checks and Clearance Validity

A `ProgramAdmin` orders a background check on a volunteer by supplying a `check_type` of either `STATE_ONLY` or `STATE_AND_FEDERAL`; the new check begins in `PENDING`, recorded against its owning volunteer via `volunteer_id`. A pending check is resolved one of two ways by a `ProgramAdmin`. Clearing it advances `PENDING → CLEARED`: the check's `cleared_at` is stamped with the current clock instant, and its read-only `expiry_date` is computed as `cleared_at` plus 365 days. If the owning volunteer is in `SCREENING` and this is that volunteer's newest check, clearing also drives the automatic `SCREENING → TRAINING` transition and recomputes the volunteer's `background_status` to `CLEARED` along with `background_expiry_date`. Flagging a pending check instead advances `PENDING → FLAGGED` and records the supplied `reason` into `flag_reason`; a flagged check is terminal. Clearing or flagging a check that is not `PENDING` fails with `ERR_INVALID_STATE`.

A volunteer's `background_status` is a read-only field derived from that volunteer's most recent background check, taking the values `NONE`, `PENDING`, `CLEARED`, `FLAGGED`, or `EXPIRED`; `background_expiry_date` mirrors the `expiry_date` of the most recent `CLEARED` check and is null when there is none. Expiry is evaluated lazily on access: whenever a cleared check is read and the logical clock has reached or passed its `expiry_date`, the check is treated as `EXPIRED` (advancing `CLEARED → EXPIRED`) and the owning volunteer's `background_status` is recomputed to `EXPIRED`. An expired background gates both swearing-in and visit logging.

### 3.3. Case Intake and Volunteer Appointment

A `ProgramAdmin` opens a case for a child by providing the de-identified `child_initials`, the child's `child_dob` as an ISO date, a `jurisdiction` code, and the `supervisor_id` of the staff supervisor who will own review and approval on the case. An optional `reimbursement_budget_cents` sets the total reimbursement available to volunteers on the case; when omitted it defaults to 20000. The case opens in `INTAKE` with `reimbursement_committed_cents` at 0 and `outcome` null. Supervisors themselves are created by a `ProgramAdmin` with a `full_name` and a unique `email`, and always carry `status` `ACTIVE`.

The case's owning `Supervisor` appoints a volunteer, advancing the case `INTAKE → ASSIGNED` (or `UNASSIGNED → ASSIGNED`). The request names the `volunteer_id` and carries `expected_case_version`. Appointment enforces, in the global order: the case is in `INTAKE` or `UNASSIGNED`, else `ERR_INVALID_STATE`; the target volunteer's `status` is `ACTIVE`, else `ERR_VOLUNTEER_NOT_ACTIVE`; the target volunteer's `active_case_count` is strictly below their `max_caseload`, else `ERR_CASELOAD_EXCEEDED`; and `expected_case_version` equals the case's current `version`, else `ERR_STALE_CASE_VERSION`. On success a new `CaseAssignment` is created with `status` `ACTIVE` and `case_id` set to the case; any prior `ACTIVE` assignment on the case is moved `ACTIVE → ENDED` with `ended_reason` `SUPERSEDED`; the appointed volunteer's `active_case_count` is incremented by one; and the case's `version` is incremented by one. A superseded volunteer's own `active_case_count` is decremented by one as their assignment ends.

The owning supervisor may also end an active assignment directly, moving the case `ASSIGNED → UNASSIGNED`. This requires the case to be `ASSIGNED` and the target assignment to be `ACTIVE`, each otherwise yielding `ERR_INVALID_STATE`. The assignment moves `ACTIVE → ENDED` with `ended_reason` `MANUAL_END`, the volunteer's `active_case_count` is decremented by one, and the case's `version` is incremented by one. An optional `reason` may accompany the request. Every assignment records its terminal `ended_reason`, which is one of `SUPERSEDED`, `MANUAL_END`, `CASE_CLOSED`, or `VOLUNTEER_DEACTIVATED` depending on the path by which it ended.

### 3.4. Logging Visits and Contacts

Only the volunteer currently appointed to a case may log a contact on it. A `Volunteer` logs a visit by supplying a `contact_type` — one of `IN_PERSON`, `VIDEO`, `PHONE`, or `COLLATERAL` — a `contact_start` and a `contact_end` (which must be strictly after `contact_start`, else `ERR_VALIDATION`), an optional `miles` figure for round-trip driving that defaults to 0 and must be at least 0, and optional free-text `notes`. The logged visit begins in `LOGGED`, its `case_id` is the case, its `volunteer_id` is set to the case's currently-active-assignment volunteer at log time, and its read-only `duration_minutes` is computed as the whole number of minutes between `contact_start` and `contact_end`.

Two gates precede the write. The acting volunteer must be the case's active-assignment volunteer, else `ERR_NOT_ASSIGNED_VOLUNTEER`. The acting volunteer's `background_status` must be `CLEARED` and not past expiry, else `ERR_BACKGROUND_EXPIRED`. A further temporal gate prevents double-booking the volunteer's calendar: treating each of that volunteer's `LOGGED` visits across all of their cases as the half-open interval running from its `contact_start` up to but not including its `contact_end`, the new visit is rejected with `ERR_VISIT_OVERLAP` if there exists such a logged visit whose interval and the new one overlap — that is, when the new `contact_start` is before the existing visit's `contact_end` and the existing visit's `contact_start` is before the new `contact_end`. Exact adjacency, where one interval's end equals the other's start, does not overlap and is allowed; voided visits are ignored entirely.

A logged visit may be voided by the case's supervisor or by the volunteer, moving `LOGGED → VOIDED` and optionally recording a `reason`. A voided visit no longer counts toward compliance.

### 3.5. Hearings and the Court Calendar

The case's supervisor schedules hearings. A hearing carries a `hearing_type` of `STATUS`, `REVIEW`, `PERMANENCY`, or `ADJUDICATION` and a `scheduled_at` instant, and opens in `SCHEDULED`. Its read-only `report_due_date` — the court-report filing deadline — is computed as `scheduled_at` minus 3 days. The case's hearing calendar enforces a symmetric buffer: treating each still-`SCHEDULED` hearing on the case as a point event at its `scheduled_at`, a new hearing is rejected with `ERR_HEARING_BUFFER_CONFLICT` if the absolute gap between the new `scheduled_at` and any existing scheduled hearing's `scheduled_at` is less than 7 days. Exactly 7 days apart is allowed, and hearings that are `HELD`, `CONTINUED`, or `CANCELLED` no longer occupy the calendar.

A scheduled hearing is resolved by the supervisor into one of three terminal states: holding it moves `SCHEDULED → HELD`, continuing (postponing) it moves `SCHEDULED → CONTINUED`, and cancelling it moves `SCHEDULED → CANCELLED`. Each requires the hearing to be `SCHEDULED`, otherwise `ERR_INVALID_STATE`. Cancellation may also arrive as a cascade when the case closes (Section 3.8).

### 3.6. Court Reports: Authoring, Review, and the Revision Loop

Any caller in the `Volunteer` role drafts a court report for a specific hearing on the case — the system records authorship but does not verify that the author is the case's currently appointed volunteer — supplying the `hearing_id`, a `content_summary` narrative of the child's situation, and a `recommendation` to the court. The report opens in `DRAFT`, its `case_id` is the case, and its `author_volunteer_id` is set to the acting volunteer; `reviewer_supervisor_id` is null and `revision_count` is 0 until changed. The referenced hearing must belong to the report's own case, else `ERR_HEARING_CASE_MISMATCH`.

The author submits the draft for review, advancing `DRAFT → SUBMITTED`. Submission requires the report to be in `DRAFT` (else `ERR_INVALID_STATE`), the linked hearing to still be `SCHEDULED` (else `ERR_HEARING_NOT_SCHEDULED`), and the filing deadline to be intact — the logical clock must be at or before `scheduled_at` minus 3 days, meaning the report is submitted at least 3 days before the hearing; a later submission fails with `ERR_REPORT_DEADLINE_PASSED`. The boundary is inclusive: submitting at exactly the due instant is allowed. On success `submitted_at` is stamped with the current clock instant.

Review is performed only by the case's own supervisor; an attempt by any other supervisor is `ERR_UNAUTHORIZED`. The reviewer supplies a `decision` of either `APPROVE` or `RETURN`, with optional `comments`, and the report must be `SUBMITTED` or the action fails with `ERR_INVALID_STATE`. An approval advances `SUBMITTED → APPROVED`; a return advances `SUBMITTED → RETURNED`. In both cases the report's `reviewer_supervisor_id` is set to the acting supervisor and a new immutable `ReviewNote` is appended, carrying the same `decision`, the reviewer's `supervisor_id`, the `report_id`, and the optional `comments`. A returned report goes back to its author, who revises it, advancing `RETURNED → DRAFT`; only the original author may revise (the acting volunteer must equal `author_volunteer_id`, else `ERR_UNAUTHORIZED`), the report must be `RETURNED` (else `ERR_INVALID_STATE`), the `content_summary` and `recommendation` may optionally be updated, and each revision increments the read-only `revision_count` by one. An approved report is filed with the court by the case's supervisor, advancing `APPROVED → FILED`, which likewise requires the report be `APPROVED` and the actor be the case's supervisor.

`VOIDED` is a further terminal state reached only by cascade: it is never requested directly. When a volunteer is deactivated or resigns from active status, that cascade voids the affected cases' reports that are still in `DRAFT` or `RETURNED` (Section 3.9).

### 3.7. Expense Claims and Two-Stage Reimbursement

A `Volunteer` submits a mileage-and-expense claim against a case, naming the `case_id`, the reimbursement `period_month` as `YYYY-MM`, the `total_miles` claimed (at least 0), and an optional `other_expense_cents` for non-mileage out-of-pocket costs (at least 0, default 0). Negative miles or negative cents are `ERR_VALIDATION`. The claim opens in `SUBMITTED`, recorded against the acting `volunteer_id`.

At submission the system pins a **provisional** estimate into the read-only `estimated_reimbursement_cents`. The provisional figure applies a flat rate of 50 cents per mile with no caps: it is the product of `total_miles` and 50 cents, rounded half up to whole cents, plus the full `other_expense_cents` unchanged.

The case's supervisor approves or rejects a submitted claim, and only the case's own supervisor may do so (else `ERR_UNAUTHORIZED`). Approval requires the claim to be `SUBMITTED` (else `ERR_INVALID_STATE`), the referenced case not to be `CLOSED` (else `ERR_CASE_CLOSED`), and the budget to accommodate the claim (else `ERR_EXPENSE_EXCEEDS_BUDGET`). At approval the system pins the **final** amount into the read-only `final_reimbursement_cents` using a tiered, capped calculation evaluated in a fixed order: first the mileage component is the first 100 miles at 50 cents each plus every mile beyond 100 at 35 cents each, with that mileage sum rounded half up to whole cents; then the other-expense component is `other_expense_cents` but no more than 5000 cents; then those two are summed; and finally the whole is capped at 15000 cents. The budget gate compares the case's `reimbursement_committed_cents` plus this claim's `final_reimbursement_cents` against the case's `reimbursement_budget_cents`, and the approval is refused if that sum would exceed the budget. On a successful approval the claim advances `SUBMITTED → APPROVED` and the case's `reimbursement_committed_cents` increases by the pinned final amount.

Rejecting a submitted claim advances `SUBMITTED → REJECTED` and records an optional `reason`; because a rejected claim never entered the ledger, committed reimbursement is unchanged. An approved claim is marked paid by any supervisor (unlike approval, rejection, and voiding, payment does not check case ownership) or a `ProgramAdmin`, advancing `APPROVED → PAID` with no change to committed reimbursement — the money remains committed, now disbursed. An approved claim may instead be voided by the case's supervisor, advancing `APPROVED → VOIDED` and decreasing the case's `reimbursement_committed_cents` by the claim's `final_reimbursement_cents`, which restores the conserved budget exactly.

### 3.8. Case Closure, Outcomes, and Contact Compliance

A case's `contact_compliance_pct` is a read-only, one-decimal percentage recomputed live whenever the case is read. It is built month by month. The relevant months are the calendar months from the month of the case's earliest `CaseAssignment` (by its `created_at`) through the current clock month, inclusive; the count of those months is the required-months denominator. When the case has no `CaseAssignment` at all, `contact_compliance_pct` is `0.0`. For each such month, the system counts the case's `LOGGED` visits whose `contact_start` falls in that month and whose `contact_type` belongs to the variant's qualifying set, then computes that month's score as the smaller of 1.0 and the count divided by the monthly standard of 3 qualifying contacts, rounded half up to two decimals. The compliance percentage is the sum of the per-month scores divided by the number of required months, multiplied by 100, and rounded half up to one decimal. The rounding order is fixed and material: each month score is rounded to two decimals first, only then are the month scores summed, divided by the month count, multiplied by 100, and rounded to one decimal — rounding the raw ratios only at the end would produce a different number and is not used. In the live **standard** variant that feeds `contact_compliance_pct`, the qualifying contact types are `IN_PERSON` and `VIDEO`.

The case's owning supervisor closes the case with a permanency `outcome` of `REUNIFICATION`, `ADOPTION`, `GUARDIANSHIP`, or `APPEAL`, advancing the case to `CLOSED` from either `ASSIGNED` or `UNASSIGNED` (any other state is `ERR_INVALID_STATE`). Closure requires that at least one `Visit` with status `LOGGED` exists on the case, else `ERR_NO_VISITS_LOGGED`. On close the `outcome` is recorded; the read-only `audit_compliance_pct` is pinned using the **strict** variant of the same compliance calculation — identical in every respect except that only `IN_PERSON` contacts qualify, so `VIDEO`, `PHONE`, and `COLLATERAL` visits do not count; this field is null until the case is closed. Closure also ends any still-`ACTIVE` assignment on the case, moving it `ACTIVE → ENDED` with `ended_reason` `CASE_CLOSED` and decrementing that volunteer's `active_case_count` by one; cancels every hearing on the case still in `SCHEDULED`, moving each `SCHEDULED → CANCELLED`; and increments the case's `version` by one.

### 3.9. Volunteer Deactivation, Resignation, and the Three-Level Cascade

A `ProgramAdmin` deactivates an active volunteer, advancing `ACTIVE → INACTIVE`; the volunteer must be `ACTIVE`, else `ERR_INVALID_STATE`, and an optional `reason` is recorded into `deactivation_reason`. Deactivation triggers a three-level cascade. At the first level, every `CaseAssignment` of this volunteer whose `status` is `ACTIVE` is moved `ACTIVE → ENDED` with `ended_reason` `VOLUNTEER_DEACTIVATED`, and the volunteer's `active_case_count` is decremented accordingly to 0. At the second level, each case whose active assignment just ended and which was in `ASSIGNED` is moved `ASSIGNED → UNASSIGNED`. At the third level, for each case now `UNASSIGNED`, every `CourtReport` still in `DRAFT` or `RETURNED` is moved to `VOIDED`.

Resignation, also performed by a `ProgramAdmin`, advances a volunteer to `RESIGNED` from either `ACTIVE` or `INACTIVE`; any other starting status is `ERR_INVALID_STATE`, and `RESIGNED` is terminal. When a volunteer resigns from `ACTIVE`, the same three-level cascade as deactivation runs; when a volunteer resigns from `INACTIVE`, there are no active assignments to unwind and no cascade occurs.

## 4. Endpoint Definitions

Operations that create a new resource — registering a volunteer, creating a supervisor or case, ordering a background check, logging a visit, scheduling a hearing, drafting a report, recording a training module, or submitting an expense claim, and creating a case assignment — return `201 Created`. All other operations, including state transitions on existing resources and reads, return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | ProgramAdmin |
| POST | `/volunteers` | Register a prospective volunteer | ProgramAdmin |
| GET | `/volunteers` | List volunteers | ProgramAdmin, Supervisor |
| GET | `/volunteers/{id}` | Get a volunteer (background re-evaluated on read) | ProgramAdmin, Supervisor, Volunteer |
| POST | `/volunteers/{id}/start-screening` | Begin screening (PROSPECT→SCREENING) | ProgramAdmin |
| POST | `/volunteers/{id}/swear-in` | Swear in a trained, cleared volunteer (TRAINING→ACTIVE) | ProgramAdmin |
| POST | `/volunteers/{id}/deactivate` | Deactivate a volunteer (ACTIVE→INACTIVE) with cascade | ProgramAdmin |
| POST | `/volunteers/{id}/resign` | Resign a volunteer (ACTIVE/INACTIVE→RESIGNED) | ProgramAdmin |
| GET | `/volunteers/{id}/assignments` | List a volunteer's case assignments | ProgramAdmin, Supervisor, Volunteer |
| GET | `/volunteers/{id}/visits` | List visits logged by a volunteer | ProgramAdmin, Supervisor, Volunteer |
| GET | `/volunteers/{id}/training-records` | List a volunteer's training records | ProgramAdmin, Supervisor, Volunteer |
| POST | `/volunteers/{id}/training-records` | Record completion of a training module | ProgramAdmin, Volunteer |
| GET | `/volunteers/{id}/background-checks` | List a volunteer's background checks | ProgramAdmin, Supervisor |
| POST | `/volunteers/{id}/background-checks` | Order a background check | ProgramAdmin |
| POST | `/background-checks/{id}/clear` | Clear a pending check (PENDING→CLEARED) | ProgramAdmin |
| POST | `/background-checks/{id}/flag` | Flag a pending check (PENDING→FLAGGED) | ProgramAdmin |
| POST | `/supervisors` | Create a staff supervisor | ProgramAdmin |
| GET | `/supervisors/{id}` | Get a supervisor | ProgramAdmin, Supervisor |
| GET | `/supervisors/{id}/review-notes` | List review notes authored by a supervisor | ProgramAdmin, Supervisor |
| POST | `/cases` | Open a case for a child | ProgramAdmin |
| GET | `/cases` | List cases, optionally filtered by supervisor | ProgramAdmin, Supervisor |
| GET | `/cases/{id}` | Get a case (contact_compliance_pct computed live) | ProgramAdmin, Supervisor, Volunteer |
| POST | `/cases/{id}/assignments` | Appoint a volunteer (OCC on Case.version) | Supervisor |
| GET | `/cases/{id}/assignments` | List the case's assignments | ProgramAdmin, Supervisor, Volunteer |
| POST | `/cases/{id}/assignments/{assignmentId}/end` | End an active assignment (ASSIGNED→UNASSIGNED) | Supervisor |
| POST | `/cases/{id}/close` | Close the case with a permanency outcome | Supervisor |
| POST | `/cases/{id}/visits` | Log a visit/contact on the case | Volunteer |
| GET | `/cases/{id}/visits` | List the case's visits | ProgramAdmin, Supervisor, Volunteer |
| POST | `/cases/{id}/hearings` | Schedule a hearing on the case | Supervisor |
| GET | `/cases/{id}/hearings` | List the case's hearings | ProgramAdmin, Supervisor, Volunteer |
| POST | `/cases/{id}/court-reports` | Create a draft court report for a hearing | Volunteer |
| POST | `/hearings/{id}/hold` | Mark a hearing held (SCHEDULED→HELD) | Supervisor |
| POST | `/hearings/{id}/continue` | Continue a hearing (SCHEDULED→CONTINUED) | Supervisor |
| POST | `/hearings/{id}/cancel` | Cancel a hearing (SCHEDULED→CANCELLED) | Supervisor |
| GET | `/court-reports/{id}` | Get a court report | ProgramAdmin, Supervisor, Volunteer |
| GET | `/court-reports` | List/filter court reports | ProgramAdmin, Supervisor |
| GET | `/court-reports/{id}/review-notes` | List review notes for a report | ProgramAdmin, Supervisor, Volunteer |
| POST | `/court-reports/{id}/submit` | Submit a draft for review (DRAFT→SUBMITTED) | Volunteer |
| POST | `/court-reports/{id}/review` | Review a submitted report (→APPROVED/→RETURNED) | Supervisor |
| POST | `/court-reports/{id}/revise` | Revise a returned report (RETURNED→DRAFT) | Volunteer |
| POST | `/court-reports/{id}/file` | File an approved report (APPROVED→FILED) | Supervisor |
| POST | `/visits/{id}/void` | Void a logged visit (LOGGED→VOIDED) | Supervisor, Volunteer |
| POST | `/expense-claims` | Submit a mileage/expense claim | Volunteer |
| GET | `/expense-claims/{id}` | Get an expense claim | ProgramAdmin, Supervisor, Volunteer |
| GET | `/expense-claims` | List/filter expense claims | ProgramAdmin, Supervisor |
| POST | `/expense-claims/{id}/approve` | Approve a submitted claim (SUBMITTED→APPROVED) | Supervisor |
| POST | `/expense-claims/{id}/reject` | Reject a submitted claim (SUBMITTED→REJECTED) | Supervisor |
| POST | `/expense-claims/{id}/pay` | Mark an approved claim paid (APPROVED→PAID) | Supervisor, ProgramAdmin |
| POST | `/expense-claims/{id}/void` | Void an approved claim (APPROVED→VOIDED) | Supervisor |

The `GET /volunteers` endpoint accepts a `status` filter alongside `limit` and `offset`; `GET /volunteers/{id}/assignments`, `GET /volunteers/{id}/visits`, `GET /volunteers/{id}/background-checks`, `GET /cases/{id}/assignments`, `GET /cases/{id}/visits`, and `GET /cases/{id}/hearings` likewise accept `status`. `GET /cases` accepts `supervisor_id` and `status`. `GET /court-reports` accepts `case_id`, `hearing_id`, `author_volunteer_id`, `reviewer_supervisor_id`, and `status`. `GET /expense-claims` accepts `volunteer_id`, `case_id`, and `status`. All list endpoints accept `limit` and `offset`.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_VALIDATION` | 400 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VOLUNTEER_NOT_FOUND` | 404 |
| `ERR_SUPERVISOR_NOT_FOUND` | 404 |
| `ERR_CASE_NOT_FOUND` | 404 |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_VISIT_NOT_FOUND` | 404 |
| `ERR_HEARING_NOT_FOUND` | 404 |
| `ERR_REPORT_NOT_FOUND` | 404 |
| `ERR_BACKGROUND_CHECK_NOT_FOUND` | 404 |
| `ERR_EXPENSE_CLAIM_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CASE_CLOSED` | 409 |
| `ERR_VOLUNTEER_NOT_ACTIVE` | 409 |
| `ERR_HEARING_NOT_SCHEDULED` | 409 |
| `ERR_REPORT_DEADLINE_PASSED` | 409 |
| `ERR_VISIT_OVERLAP` | 409 |
| `ERR_HEARING_BUFFER_CONFLICT` | 409 |
| `ERR_NOT_ASSIGNED_VOLUNTEER` | 409 |
| `ERR_HEARING_CASE_MISMATCH` | 409 |
| `ERR_BACKGROUND_EXPIRED` | 422 |
| `ERR_TRAINING_INCOMPLETE` | 422 |
| `ERR_CASELOAD_EXCEEDED` | 409 |
| `ERR_NO_VISITS_LOGGED` | 409 |
| `ERR_EXPENSE_EXCEEDS_BUDGET` | 402 |
| `ERR_STALE_CASE_VERSION` | 412 |
