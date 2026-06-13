# Staffing Agency Placement API — Product Requirements Document

## 1. Introduction

This document specifies the Staffing Agency Placement API, the system of record for a full-service staffing agency that places workers with employer clients across temporary, temp-to-perm, and direct-hire engagements. The platform follows a candidate from the agency's talent pool, through a multi-stage submission and interview pipeline against a client's open requisition, into a live placement, and onward through weekly time capture, client billing, assignment end, redeployment, and — where the engagement converts to a permanent hire — a conversion fee.

Two concerns dominate the design. The first is workflow orchestration: requisitions, submissions, interviews, placements, timesheets, and invoices each carry their own lifecycle, and a single operator action frequently cascades across several of them — placing a candidate fills a seat on a job order, takes the candidate off the market, and may instantly close the order to other applicants. The second is financial reconciliation: every placement projects a forward-looking weekly margin and client credit exposure, while approved timesheets and issued invoices reconcile that projection against realized, cents-exact amounts. The agency extends credit to its clients, so the system must continuously police each client's total exposure against a contractual limit, and it must compute pay, bill, margin, discounts, fees, and conversion fees to the cent.

The intended operators are the agency's **Recruiter** and **AccountManager** staff, alongside self-service **Client** (employer) and **Candidate** (worker) actors. The remainder of this document defines the global contracts every endpoint honors (Section 2), the business logic and lifecycle rules that the engine enforces (Section 3), the endpoint surface (Section 4), and the catalogue of machine-readable error identifiers (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the capacity in which they act. If either header is absent, or if `X-User-Role` is not one of the recognized role names, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 401).

The system recognizes exactly four roles, spelled precisely as follows: `Recruiter`, `AccountManager`, `Client`, and `Candidate`. Each role is authorized for a specific set of operations, enumerated in the endpoint table of Section 4. When an authenticated caller attempts an operation their role is not permitted to perform — or when an entity-backed actor targets a resource it does not own — the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The two agency-side roles are operator identities not tied to any persisted entity. When `X-User-Role` is `Recruiter`, `X-User-ID` is an opaque operator identifier; the server may record it for audit purposes but never compares it to any entity's `id`. The same holds when `X-User-Role` is `AccountManager`: `X-User-ID` is an opaque operator identifier not bound to a stored entity, and the server does not compare it to any entity's `id`.

The two self-service roles are entity-backed. When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Client`; ownership checks compare the targeted resource back to that client through its chain of references — a `Client` may act only on job orders whose `client_id` equals `X-User-ID`, and on the submissions, interviews, placements, timesheets, and invoices reachable from those job orders. When `X-User-Role` is `Candidate`, `X-User-ID` is the `id` of the acting `Candidate`; a `Candidate` may act only on placements whose `candidate_id` equals `X-User-ID`, and on the timesheets of those placements. An ownership violation for either entity-backed role surfaces as `ERR_UNAUTHORIZED`.

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

Endpoints that return a list of resources accept two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, may be no smaller than 1, and may be no larger than 100. The `offset` parameter is the number of items to skip from the front of the result set; when omitted it defaults to 0.

Unless an endpoint states otherwise, list results are sorted by their creation timestamp (`created_at`) in ascending order. The `meta` object of a list response carries the `limit`, `offset`, `total_count`, and `has_more` fields, where `total_count` is the number of matching items before pagination and `has_more` indicates whether further items remain beyond the current page.

### 2.4. Common Resource Properties and the Version Counter

Most resources in this system are mutable and carry a standard set of system-managed fields: an `id` formatted as a server-minted UUID with no type prefix; a `created_at` ISO 8601 UTC timestamp with three fractional digits, fixed at creation; an `updated_at` ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation; and a `version` integer that begins at 1 on creation and increments by one with each mutation. The mutable resources are `Client`, `Candidate`, `JobOrder`, `Submission`, `Interview`, `Placement`, `Timesheet`, `Invoice`, and `ConversionFee`.

Two resource types are immutable configuration or ledger records and therefore carry only `id` and `created_at`; they have neither an `updated_at` nor a `version` field. These are the `Skill` catalog entry and the `InvoiceLineItem`. A `Skill` is a fixed catalog row, and a line item is frozen at the moment it is added to an invoice.

A subtle but important rule governs derived fields. When the system recomputes a read-only field on an already-existing resource as a side effect of some other action — for example refreshing a client's `open_exposure_cents` when a placement starts, or accumulating a placement's `actual_margin_cents` when a timesheet is approved — that recomputation counts as a mutation of the holding resource: its `updated_at` is refreshed and its `version` is incremented.

### 2.5. Nested Resource Retrieval and Existence Ordering

The entity model is predominantly flat: resources reference one another by foreign keys carried in request bodies rather than through deep ownership URLs. A handful of paths do nest a child collection beneath a parent — interviews beneath a submission, timesheets beneath a placement, and line items beneath an invoice. For any such path, the system validates the identifiers left to right: the parent identifier must resolve to an existing resource before the child is considered. A request naming a submission, placement, or invoice that does not exist is rejected with that parent's not-found error before any child lookup occurs.

This left-to-right discipline generalizes to every write: each resource `id` appearing in the path and each foreign key carried in the body is verified to exist, in path-then-body order, and the first unresolved reference yields the corresponding not-found error — `ERR_CLIENT_NOT_FOUND`, `ERR_SKILL_NOT_FOUND`, `ERR_CANDIDATE_NOT_FOUND`, `ERR_JOB_ORDER_NOT_FOUND`, `ERR_SUBMISSION_NOT_FOUND`, `ERR_INTERVIEW_NOT_FOUND`, `ERR_PLACEMENT_NOT_FOUND`, `ERR_TIMESHEET_NOT_FOUND`, or `ERR_INVOICE_NOT_FOUND` — each returned with HTTP 404.

### 2.6. Request Validation Order

The system applies validation in a fixed priority order so that the same failure always produces the same error. Authentication comes first: a missing or invalid user context header (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, HTTP 401) is detected before anything else. Authorization is second: a role not permitted for the operation, or an entity-backed actor that does not own the target, yields `ERR_UNAUTHORIZED` (HTTP 403). Existence is third: any unresolved path id or body foreign key produces the matching not-found error (HTTP 404), evaluated left to right as described above. Request well-formedness is fourth: a body missing a required field, carrying a wrong-typed field, presenting an enum value out of range, or violating a structural constraint is rejected with `ERR_VALIDATION` (HTTP 422). Only after these four layers pass does the system evaluate state-machine and business rules.

The structural checks folded into the fourth layer include: an interview's `scheduled_end` must be strictly after its `scheduled_start`; a placement's `end_date` must be strictly after its `start_date`; a timesheet's `week_end` must be strictly after its `week_start`; `hours` must be strictly greater than 0; `openings` must be at least 1; a `standard_weekly_hours` value, when supplied, must be at least 1; a client's `conversion_fee_pct` must be greater than 0 and at most 1; and the `target_status`, `target_assignment_status`, or `outcome` carried by a transition request must be one of the defined values for that resource. Any of these produces `ERR_VALIDATION`.

### 2.7. Monetary Precision and Rounding

All monetary quantities are stored and returned as integer cents. Where a calculation multiplies an integer cent amount by an integer count of hours (for example a placement's projected weekly bill and projected weekly margin), the product is exact and no rounding is required. Where a calculation multiplies by a non-integer factor — an overtime multiplier, a discount tier rate, a processing-fee rate, or a conversion-fee rate — the result is rounded to whole cents using the round-half-up convention, in which a fractional remainder of exactly one-half rounds upward. The specific point at which rounding is applied within each multi-step formula is pinned in Section 3 and must be followed exactly, because rounding at the wrong step changes the final cent.

### 2.8. Optimistic Concurrency on Placement Creation

Creating a placement is the one write in this system guarded by optimistic concurrency control, because two placements created against the same requisition compete for a finite number of openings. A placement-creation request must carry `expected_job_order_version`, a non-optional field holding the `version` of the target job order as the client last observed it. The server compares this value to the job order's current `version`. If they differ — meaning another writer has created a placement against the same order since the client last read it, legitimately raising the order's `filled_count` and bumping its `version`, so the requesting client's view of how many openings remain is stale — the create is rejected with `ERR_STALE_JOB_ORDER_VERSION` (HTTP 412). This prevents a client from filling a seat against an order whose remaining-openings count it has not actually observed. No other endpoint accepts a version field, and no other write performs a version check.

### 2.9. Client Credit and Exposure Principles

The agency extends each client a credit line, recorded as `credit_limit_cents`, that bounds the client's total exposure. Two read-only figures, recomputed and stored on the `Client` record, make up that exposure. The `open_exposure_cents` figure is forward-looking: it is the sum of `projected_weekly_bill_cents` across the client's placements whose `assignment_status` is `ACTIVE`, and it is recomputed whenever such a placement is created, started, or ended. The `outstanding_balance_cents` figure is realized: it is the sum of `total_cents` across the client's invoices whose `status` is `ISSUED`, and it is recomputed whenever an invoice is issued, paid, or voided. These two figures diverge in practice because the projection uses planned `standard_weekly_hours` while issued invoices reflect the realized hours actually worked. Both are evaluated together at placement creation as the credit gate described in Section 3.

### 2.10. Cascading Side Effects and Status Reconciliation

A single operator action commonly mutates several resources at once, and the system applies every secondary effect, not merely the primary transition. Placing a candidate, for instance, transitions a submission, may transition the candidate, increments and may transition the job order, recomputes client exposure, and — for a direct hire — creates a conversion fee, all within the one create. Whenever the system advances `filled_count` to equal a job order's `openings`, the order is automatically driven to `FILLED` and its still-open submissions are swept to `REJECTED`; whenever an active placement ends and drops `filled_count` below `openings`, a `FILLED` order automatically returns to `OPEN` so the seat can be backfilled. Each such automatic transition is a real mutation of the affected resource, refreshing its `updated_at` and incrementing its `version`. The precise cascade chains are detailed in Section 3.

## 3. Business Logic & Workflows

### 3.1. Clients, the Skill Catalog, and the Candidate Pool

An `AccountManager` opens the system by registering a **Client** — the employer the agency will staff. A client is created with a company `name` and a `credit_limit_cents`, the maximum total exposure the agency will extend to that client measured in cents. The request may optionally supply `conversion_fee_pct`, the rate, expressed as a fraction of first-year salary, that the agency charges for direct-hire placements and temp-to-perm conversions; this value must be greater than 0 and at most 1, and when omitted it defaults to 0.20, that is, twenty percent. A newly created client begins with `status` of `ACTIVE`, with `outstanding_balance_cents` and `open_exposure_cents` both at zero. An `AccountManager` may later suspend a client, moving its `status` from `ACTIVE` to `SUSPENDED`; while a client is `SUSPENDED` the agency will neither bring its job orders to the open market nor create placements against it. Reads of a client return its live `outstanding_balance_cents` and `open_exposure_cents` alongside its stored fields.

The agency maintains a **Skill** catalog, an immutable reference table of competencies. Either a `Recruiter` or an `AccountManager` may add a catalog entry, supplying a `code` and a `category`. The code is uppercased before it is stored — so a submission of "java" persists as "JAVA" — and it must be unique across the catalog; an attempt to register a code that already exists (after uppercasing) is rejected with `ERR_SKILL_CODE_DUPLICATE`. The category must be one of `TECH`, `CLINICAL`, `INDUSTRIAL`, or `CLERICAL`.

A `Recruiter` builds the talent pool by registering a **Candidate** with a `full_name`, an array of `skill_codes`, and a `base_pay_rate_cents` representing the worker's expected hourly pay rate in cents per hour. Every code in `skill_codes` must reference an existing entry in the skill catalog; a code with no matching catalog entry is rejected as a missing skill reference. A candidate is created in `status` `AVAILABLE`. From `AVAILABLE`, a `Recruiter` may deactivate the candidate, moving `status` to `INACTIVE`; this deactivation is permitted only while the candidate is `AVAILABLE`, and an attempt to deactivate a candidate not in that state is rejected with `ERR_CANDIDATE_NOT_AVAILABLE`. The candidate's other status value, `ON_ASSIGNMENT`, is reached and left automatically as placements begin and end, as described in Section 3.4.

### 3.2. Job Orders and Their Lifecycle

A requisition is captured as a **JobOrder**, created by an `AccountManager` against a client by supplying the `client_id`, a role `title`, an `employment_type`, a `required_skill_code`, a count of `openings`, an hourly `bill_rate_cents` charged to the client, and a `target_pay_rate_cents` offered to the placed worker. The `employment_type` is one of `TEMP`, `TEMP_TO_PERM`, or `DIRECT`, and it fixes the kind of placement this order will produce. The optional `annual_salary_cents` field records the first-year salary that serves as the conversion-fee base for `DIRECT` orders, in cents per year; it defaults to 0 and is left at 0 for pure temporary orders. The `required_skill_code` must reference an existing catalog skill, and `openings` must be at least 1. A job order is created in `status` `DRAFT` with a `filled_count` of 0, and `filled_count` is thereafter a read-only count of this order's placements whose `assignment_status` is `ACTIVE`.

The job order lifecycle is driven by the `AccountManager` through status transitions and, in two cases, by the system automatically. From `DRAFT`, the order may be opened to the market, advancing to `OPEN`; opening requires the order to currently be `DRAFT` (otherwise `ERR_JOB_ORDER_NOT_DRAFT`) and additionally requires the owning client to be `ACTIVE` (otherwise `ERR_CLIENT_SUSPENDED`). An `OPEN` order may be paused, moving to `ON_HOLD`, which requires the order to currently be `OPEN` (otherwise `ERR_JOB_ORDER_NOT_OPEN`); an `ON_HOLD` order may be resumed back to `OPEN`, which requires it to currently be `ON_HOLD` (otherwise `ERR_JOB_ORDER_NOT_ON_HOLD`). This hold-and-resume forms a cycle between `OPEN` and `ON_HOLD`. From `DRAFT`, the order may instead be cancelled, advancing to `CANCELLED`, which likewise requires the order to be `DRAFT` (otherwise `ERR_JOB_ORDER_NOT_DRAFT`).

Closing an order is permitted from either `OPEN` or `ON_HOLD`, driving it to `CLOSED`; a close attempt from any other state is rejected with `ERR_JOB_ORDER_NOT_CLOSEABLE`. Closing an order carries a cascade: every one of its submissions still in an open pipeline state — that is, every submission whose status is `SUBMITTED`, `CLIENT_REVIEW`, `INTERVIEWING`, or `OFFER_EXTENDED` — is automatically rejected, with `rejection_reason` set to the literal `ORDER_CLOSED`. The `CLOSED` and `CANCELLED` states are terminal.

The two system-driven job-order transitions concern seat-filling and are described where they originate. When a placement raises `filled_count` to equal `openings`, an `OPEN` order is automatically driven to `FILLED`; when an active placement ends and lowers `filled_count` below `openings`, a `FILLED` order is automatically returned to `OPEN`. These are detailed in Section 3.4.

### 3.3. The Submission and Interview Pipeline

A `Recruiter` advances a candidate toward a placement by creating a **Submission** that ties a candidate to a job order. The create supplies `job_order_id`, `candidate_id`, and `submitted_pay_rate_cents` — the hourly pay rate proposed for this candidate on this particular order, in cents per hour. At submission time the system enforces a skill match: the candidate must hold the job order's `required_skill_code` among their `skill_codes`, and a candidate who does not is rejected with `ERR_SKILL_MISMATCH`. A submission is created in `status` `SUBMITTED`.

From `SUBMITTED`, the `Recruiter` hands the candidate to the employer by advancing the submission to `CLIENT_REVIEW`; this requires the submission to currently be `SUBMITTED` (otherwise `ERR_SUBMISSION_BAD_STATE`) and the job order to be `OPEN` (otherwise `ERR_JOB_ORDER_NOT_OPEN`). The employer then engages: a `Client` schedules an **Interview** against a submission in `CLIENT_REVIEW`, which advances the submission to `INTERVIEWING`. Scheduling an interview requires the submission to currently be `CLIENT_REVIEW` (otherwise `ERR_SUBMISSION_BAD_STATE`) and the job order to be `OPEN` (otherwise `ERR_JOB_ORDER_NOT_OPEN`). The create supplies a `scheduled_start` and a `scheduled_end`, both ISO 8601 UTC instants, where the end must fall strictly after the start; the new interview begins with `outcome` `PENDING`, and the submission moves from `CLIENT_REVIEW` to `INTERVIEWING` as the side effect of this creation.

A `Client` records an interview's result by setting its `outcome` to `PASSED` or `FAILED`; this is permitted only while the interview's `outcome` is `PENDING`, and recording against an already-resolved interview is rejected with `ERR_INTERVIEW_BAD_STATE`. With the interview resolved, the `Client` may extend an offer, advancing the submission from `INTERVIEWING` to `OFFER_EXTENDED`. Extending an offer requires the submission to currently be `INTERVIEWING` (otherwise `ERR_SUBMISSION_BAD_STATE`), requires that at least one interview for this submission has an `outcome` of `PASSED` (otherwise `ERR_NO_PASSED_INTERVIEW`), and requires the job order to be `OPEN` (otherwise `ERR_JOB_ORDER_NOT_OPEN`).

The pipeline also supports early exits. A `Client` may reject a submission from any of the client-side review states — `CLIENT_REVIEW`, `INTERVIEWING`, or `OFFER_EXTENDED` — driving it to `REJECTED`; a rejection attempt from outside that set is rejected with `ERR_SUBMISSION_BAD_STATE`, and a free-text `rejection_reason` may accompany the request. In parallel, a `Recruiter` may withdraw a submission from `SUBMITTED`, `CLIENT_REVIEW`, or `INTERVIEWING`, driving it to `WITHDRAWN`; a withdraw attempt from outside that set is likewise rejected with `ERR_SUBMISSION_BAD_STATE`. The terminal submission states are `PLACED`, `REJECTED`, and `WITHDRAWN`; the move to `PLACED` happens only as a side effect of placement creation, covered next.

### 3.4. Placement Creation and the Fill Cascade

A `Recruiter` converts a successful pipeline into a **Placement** from a submission that has reached `OFFER_EXTENDED`. The create supplies the `submission_id` it is built from, a `start_date`, an `end_date`, and the `expected_job_order_version` for the optimistic-concurrency check; it may optionally supply `standard_weekly_hours` and a `predecessor_placement_id`. The `standard_weekly_hours` field is the planned weekly hours used for the projected-margin calculation; it must be at least 1 and defaults to 40 when omitted. The `predecessor_placement_id` is set only when this placement is a redeployment of an earlier ended placement, and it references that prior placement. The `end_date` must fall strictly after the `start_date`.

Several preconditions guard the create, and they are evaluated in the following order so that the same failing request always yields the same error. First, the submission must be `OFFER_EXTENDED`; otherwise `ERR_SUBMISSION_NOT_OFFER_EXTENDED`. Then the job order must be `OPEN`; otherwise `ERR_JOB_ORDER_NOT_OPEN`. Then the candidate must not be `INACTIVE`; otherwise `ERR_CANDIDATE_INACTIVE`. Note that a candidate already `ON_ASSIGNMENT` from a non-overlapping placement may still take a concurrent placement — only an `INACTIVE` candidate is barred. Then the new placement's date range must not overlap any existing placement of the same candidate that is `ACTIVE` or `PENDING_START`; otherwise `ERR_PLACEMENT_DATE_OVERLAP`. This overlap test treats each date range as a closed interval, so two ranges that merely share an endpoint do conflict. Then the job order must have a remaining opening, that is its `filled_count` must be strictly less than its `openings`; otherwise `ERR_NO_OPENINGS_REMAINING`. Then the optimistic-concurrency check applies: `expected_job_order_version` must equal the job order's current `version`; otherwise `ERR_STALE_JOB_ORDER_VERSION`. Finally the credit gate applies, as described below; a breach yields `ERR_CREDIT_LIMIT_EXCEEDED`.

The credit gate projects the client's exposure as if this placement were already active. The system adds three quantities — the client's current `open_exposure_cents`, the new placement's own projected weekly bill, and the client's current `outstanding_balance_cents` — and the create is permitted only when that sum is at most the client's `credit_limit_cents`. Equality is allowed: a sum exactly equal to the limit passes. A sum strictly above the limit is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`.

When all preconditions pass, the placement is created and a chain of side effects fires. The submission advances from `OFFER_EXTENDED` to `PLACED`. The placement copies several fields from its sources: its `job_order_id` and `candidate_id` are copied from the submission, its `placement_type` is copied from the job order's `employment_type`, its `bill_rate_cents` is copied from the job order, and its `pay_rate_cents` is copied from the submission's `submitted_pay_rate_cents`. The candidate, if currently `AVAILABLE`, transitions to `ON_ASSIGNMENT`; a candidate already `ON_ASSIGNMENT` stays there. The placement's `assignment_status` begins at `PENDING_START` for `TEMP` and `TEMP_TO_PERM` placements, while a `DIRECT` placement is born already `ENDED` because a direct hire involves no temporary assignment period. Its `conversion_status` begins at `NONE` in all cases.

The fill cascade then runs against the job order. The order's `filled_count` is increased by one and its `version` is incremented by one. If this brings `filled_count` to equal `openings`, the order transitions from `OPEN` to `FILLED`, and that transition in turn sweeps every still-open submission on the order — those whose status is `SUBMITTED`, `CLIENT_REVIEW`, `INTERVIEWING`, or `OFFER_EXTENDED` — to `REJECTED` with `rejection_reason` set to the literal `ORDER_FILLED`. Finally, the client's `open_exposure_cents` is recomputed. (For a `DIRECT` placement, which is created already `ENDED`, the placement contributes nothing to active exposure; a `DIRECT` placement also triggers an immediate conversion fee, described in Section 3.7.)

### 3.5. The Assignment Axis, Assignment End, and Redeployment

A placement carries two independent status axes. The `assignment_status` axis tracks the temporary engagement, while the `conversion_status` axis (Section 3.7) tracks any perm conversion; neither dictates the other until a conversion forces the assignment to close.

For a `TEMP` or `TEMP_TO_PERM` placement, a `Recruiter` starts the engagement by advancing `assignment_status` from `PENDING_START` to `ACTIVE`; this requires the placement to currently be `PENDING_START` (otherwise `ERR_PLACEMENT_NOT_PENDING_START`) and applies only to `TEMP` and `TEMP_TO_PERM` placements, since `DIRECT` placements are created already `ENDED`. Starting the engagement recomputes the client's `open_exposure_cents`, because the placement's `projected_weekly_bill_cents` now counts toward active exposure.

A `Recruiter` ends an `ACTIVE` engagement by advancing `assignment_status` from `ACTIVE` to `ENDED`; this requires the placement to currently be `ACTIVE` (otherwise `ERR_PLACEMENT_NOT_ACTIVE`). Ending an assignment fires three side effects in concert. First, the client's `open_exposure_cents` is recomputed, removing this placement's projected weekly bill. Second, the job order's `filled_count` is decreased by one, and if that drops it below `openings` while the order is `FILLED`, the order automatically returns from `FILLED` to `OPEN` so the seat can be refilled. Third, the candidate is checked: if they now have no remaining placements whose `assignment_status` is `ACTIVE`, the candidate transitions from `ON_ASSIGNMENT` back to `AVAILABLE`. This ending is precisely the redeployment enabler — the candidate frees up and the seat re-opens, so a fresh placement can be created against the re-opened order, optionally carrying the ended placement's id in `predecessor_placement_id` to record the redeployment chain.

### 3.6. Weekly Time Capture, Pay, Bill, and Margin

Once a placement is `ACTIVE`, weekly **Timesheets** capture the hours worked. A `Candidate` or a `Recruiter` creates a timesheet supplying the `placement_id`, the `week_start`, the `week_end`, and the `hours` worked. A timesheet week is a half-open interval running from `week_start` inclusive to `week_end` exclusive, and `week_end` must fall strictly after `week_start`; `hours` must be strictly greater than 0; and the placement must be `ACTIVE` (otherwise `ERR_PLACEMENT_NOT_ACTIVE`). A new timesheet's half-open week must not overlap the half-open week of any non-`REJECTED` timesheet on the same placement; because the weeks are half-open, two weeks that meet exactly at a shared boundary are adjacent rather than overlapping and are allowed, while any interior overlap is rejected with `ERR_TIMESHEET_WEEK_OVERLAP`. A timesheet is created in `status` `DRAFT`.

Each timesheet computes three read-only money fields at creation, and recomputes them on revision: `pay_cents`, `bill_cents`, and `margin_cents`. Both pay and bill recognize overtime above a forty-hour threshold. The regular portion of the week is the lesser of the hours worked and 40; the overtime portion is whatever exceeds 40, or zero if the worked hours do not exceed 40. Overtime applies strictly above the threshold, so a week of exactly 40.0 hours yields zero overtime hours.

For pay, the candidate's `pay_rate_cents` (copied from the placement) applies to the regular portion, and one and one-half times that pay rate applies to the overtime portion; the regular component and the overtime component are summed first and the total is then rounded half-up to whole cents. For bill, the placement's `bill_rate_cents` applies to the regular portion, and one and one-half times that bill rate applies to the overtime portion; again the two components are summed first and the total is then rounded half-up to whole cents. The week's `margin_cents` is the `bill_cents` minus the `pay_cents`.

A timesheet moves through its own lifecycle. A `Candidate` submits a `DRAFT` timesheet, advancing it to `SUBMITTED`; this requires it to currently be `DRAFT` (otherwise `ERR_TIMESHEET_BAD_STATE`). A `Client` then either approves or rejects a `SUBMITTED` timesheet — both transitions require it to currently be `SUBMITTED` (otherwise `ERR_TIMESHEET_BAD_STATE`). Approval advances it to `APPROVED`; rejection advances it to `REJECTED`. A `REJECTED` timesheet may be revised by a `Candidate` back to `DRAFT`, which requires it to currently be `REJECTED` (otherwise `ERR_TIMESHEET_BAD_STATE`); the revise request may carry a new `hours` value, and when it does, the timesheet's `pay_cents`, `bill_cents`, and `margin_cents` are recomputed. This rejection-and-revision forms a cycle through `SUBMITTED`, `REJECTED`, and `DRAFT`. The terminal timesheet state is `INVOICED`, reached only as a system side effect when an invoice carrying the timesheet is issued (Section 3.8).

Approving a timesheet reconciles the placement's realized margin. On the `SUBMITTED → APPROVED` transition, the just-approved timesheet's `margin_cents` is added to the placement's `actual_margin_cents`. That field is the cumulative final margin across this placement's timesheets in `APPROVED` or `INVOICED` status, accumulated in chronological order of `week_start` ascending with ties broken by the timesheet's `created_at` ascending; it starts at 0. Because the margin is counted once at approval, a later sweep onto an invoice does not add it again.

By contrast, the placement's two projected figures are fixed at creation from the planned weekly hours and the copied rates. The `projected_weekly_bill_cents` is the placement's `bill_rate_cents` multiplied by its `standard_weekly_hours`, and the `projected_weekly_margin_cents` is the difference between `bill_rate_cents` and `pay_rate_cents` multiplied by `standard_weekly_hours`. For a `DIRECT` placement both projected figures are 0, since there is no hourly billing. The projected weekly bill is the quantity that feeds the client's active exposure while the placement is `ACTIVE`; the actual margin and the projected margin diverge whenever realized hours differ from the planned `standard_weekly_hours`.

### 3.7. Temp-to-Perm Conversion and Direct-Hire Fees

The `conversion_status` axis runs independently of the assignment axis until a conversion closes the assignment. An `AccountManager` converts an eligible temp-to-perm placement, which creates a **ConversionFee** and advances `conversion_status` from `NONE` to `CONVERTED`. The convert request supplies the `annual_salary_cents` to be used as the fee base — the agreed first-year salary in cents per year — and an optional `waive` flag. Conversion requires the placement's `placement_type` to be `TEMP_TO_PERM` (otherwise `ERR_PLACEMENT_NOT_CONVERTIBLE`), requires its `conversion_status` to be `NONE` (otherwise `ERR_PLACEMENT_ALREADY_CONVERTED`), and requires its `assignment_status` to be `ACTIVE` (otherwise `ERR_PLACEMENT_NOT_ACTIVE`).

Converting fires three effects. A conversion fee is created, in `status` `BILLED` ordinarily, or in `status` `WAIVED` when the request sets `waive` to true. The `conversion_status` moves to `CONVERTED`. And the temporary engagement closes: the placement's `assignment_status` moves from `ACTIVE` to `ENDED`, which triggers the very same assignment-end side effects described in Section 3.5 — exposure recompute, `filled_count` decrement with a possible `FILLED → OPEN` reopen, and the candidate's possible return to `AVAILABLE`.

A `DIRECT` placement does not go through the convert endpoint; instead, a conversion fee is created automatically at the moment the `DIRECT` placement is created. That auto-created fee uses the job order's `annual_salary_cents` as its base and is created in `status` `BILLED`. Every conversion fee records the `placement_id` it bills against and copies the `client_id` from that placement's job order; its computed `fee_cents` is read-only.

The fee itself is computed as follows. The base is the `annual_salary_cents` — taken from the convert request for a temp-to-perm conversion, or from the job order's `annual_salary_cents` for a direct hire. An effective rate is then derived. For a `DIRECT` placement the effective rate is simply the client's `conversion_fee_pct`. For a `TEMP_TO_PERM` placement the effective rate is the client's `conversion_fee_pct` multiplied by a tenure factor that rewards long temp tenure: the tenure factor is 1.0 when the candidate has worked fewer than 13 weeks, and 0.5 when they have worked 13 weeks or more, where weeks worked is the count of the placement's timesheets in `APPROVED` or `INVOICED` status. The raw fee is the base multiplied by the effective rate, rounded half-up to whole cents. That raw fee is then clamped into a band: the final `fee_cents` is at least 250000 cents and at most 5000000 cents — that is, the raw fee is first floored at the minimum of 250000 and then capped at the maximum of 5000000, with the rounding performed before the clamp.

### 3.8. Invoicing, Issue, Payment, and Void

An `AccountManager` bills a client by creating an **Invoice** against a `client_id`. An invoice is created in `status` `DRAFT` with all of its money fields — `subtotal_cents`, `volume_discount_cents`, `processing_fee_cents`, and `total_cents` — at zero. The manager then attaches work to the invoice by adding **InvoiceLineItems**, each billing exactly one timesheet. A line item is added by supplying the `timesheet_id`; the referenced timesheet must be in `status` `APPROVED` (otherwise `ERR_TIMESHEET_NOT_APPROVED`), and its placement must belong to the same client as the invoice (otherwise `ERR_TIMESHEET_CLIENT_MISMATCH`). When the line is created, its `line_total_cents` is copied from the timesheet's `bill_cents` at that moment, and the invoice's totals are recomputed. Each line item records the `invoice_id` it belongs to.

Invoice totals are computed in a pinned five-step order, because the discount and fee depend on one another's place in the sequence. First, the `subtotal_cents` is the sum of `line_total_cents` across the invoice's line items; since each line total was already rounded to whole cents when it was copied from its timesheet, this is a sum of already-rounded per-line amounts, not a rounding of the raw sum. Second, the `volume_discount_cents` is the subtotal multiplied by a volume tier rate, rounded half-up to whole cents. The tier rate is selected from the subtotal by inclusive lower boundaries: a subtotal below 500000 cents earns no discount (a rate of zero); a subtotal of at least 500000 cents and below 2000000 cents earns three percent; and a subtotal of at least 2000000 cents earns six percent. Third, the discounted amount is the subtotal minus the volume discount. Fourth, the `processing_fee_cents` is that discounted amount multiplied by a processing-fee rate of one and one-half percent, rounded half-up to whole cents — note the fee is keyed on the post-discount amount, which is why the evaluation order is pinned. Fifth, the `total_cents` is the subtotal minus the volume discount plus the processing fee.

An `AccountManager` issues a `DRAFT` invoice, advancing its `status` to `ISSUED`; issuing requires the invoice to currently be `DRAFT` (otherwise `ERR_INVOICE_BAD_STATE`) and requires it to carry at least one line item (otherwise `ERR_INVOICE_EMPTY`). Issuing fires two side effects: each timesheet referenced by the invoice's line items transitions from `APPROVED` to `INVOICED` and has its `invoice_id` set to this invoice; and the client's `outstanding_balance_cents` is increased by the invoice's `total_cents`. From `ISSUED`, the manager may mark the invoice `PAID`, which requires it to currently be `ISSUED` (otherwise `ERR_INVOICE_BAD_STATE`) and decreases the client's `outstanding_balance_cents` by the invoice's `total_cents`.

From `ISSUED`, the manager may instead void the invoice, advancing its `status` to `VOID`, which likewise requires it to currently be `ISSUED` (otherwise `ERR_INVOICE_BAD_STATE`). Voiding is a compensating reversal of the issue: the client's `outstanding_balance_cents` is decreased by the invoice's `total_cents`, leaving the balance equal to the sum of the remaining issued invoices' totals; and every timesheet the invoice referenced reverts from `INVOICED` back to `APPROVED` with its `invoice_id` cleared, so it becomes re-billable. Because each approved timesheet's margin was counted into the placement's `actual_margin_cents` at approval time, neither issuing nor voiding an invoice changes that figure. The `PAID` and `VOID` states are terminal for an invoice.

## 4. Endpoint Definitions

Operations that create a new resource return HTTP `201 Created`. Operations that retrieve a resource or modify an existing one — including all status and assignment transitions, suspension, and conversion — return HTTP `200 OK`. Request bodies, response payloads, and the side effects of each operation are described in the Section 3 narratives; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/staffing/clients` | Create a client | AccountManager |
| GET | `/staffing/clients/{id}` | Get a client (with computed exposure and balance) | AccountManager, Recruiter, Client |
| POST | `/staffing/clients/{id}/suspend` | Suspend a client | AccountManager |
| POST | `/staffing/skills` | Create a skill catalog entry | Recruiter, AccountManager |
| GET | `/staffing/skills/{id}` | Get a skill | AccountManager, Recruiter |
| POST | `/staffing/candidates` | Create a candidate | Recruiter |
| GET | `/staffing/candidates/{id}` | Get a candidate | Recruiter, AccountManager, Candidate |
| PATCH | `/staffing/candidates/{id}` | Deactivate an available candidate | Recruiter |
| POST | `/staffing/job-orders` | Create a job order (DRAFT) | AccountManager |
| GET | `/staffing/job-orders` | List job orders (filter by client_id, status) | AccountManager, Recruiter, Client |
| GET | `/staffing/job-orders/{id}` | Get a job order (with computed filled_count) | AccountManager, Recruiter, Client |
| PATCH | `/staffing/job-orders/{id}` | Job-order lifecycle transition | AccountManager |
| POST | `/staffing/submissions` | Submit a candidate to a job order | Recruiter |
| GET | `/staffing/submissions` | List submissions (filter by job_order_id, candidate_id, status) | AccountManager, Recruiter, Client |
| GET | `/staffing/submissions/{id}` | Get a submission | AccountManager, Recruiter, Client |
| PATCH | `/staffing/submissions/{id}` | Submission pipeline transition | Recruiter, Client |
| POST | `/staffing/submissions/{id}/interviews` | Schedule an interview (advances submission to INTERVIEWING) | Client |
| GET | `/staffing/submissions/{id}/interviews` | List interviews for a submission | AccountManager, Recruiter, Client |
| PATCH | `/staffing/interviews/{id}` | Record an interview outcome | Client |
| POST | `/staffing/placements` | Place a candidate from an OFFER_EXTENDED submission | Recruiter |
| GET | `/staffing/placements` | List placements (filter by job_order_id, candidate_id, submission_id, predecessor_placement_id, assignment_status) | AccountManager, Recruiter, Client, Candidate |
| GET | `/staffing/placements/{id}` | Get a placement (with computed margins and both status axes) | AccountManager, Recruiter, Client, Candidate |
| GET | `/staffing/placements/{id}/timesheets` | List timesheets for a placement | AccountManager, Recruiter, Client, Candidate |
| PATCH | `/staffing/placements/{id}` | Assignment-status transition (start / end) | Recruiter |
| POST | `/staffing/placements/{id}/convert` | Convert a temp-to-perm placement to direct hire | AccountManager |
| POST | `/staffing/timesheets` | Create a draft timesheet for an ACTIVE placement | Candidate, Recruiter |
| GET | `/staffing/timesheets` | List timesheets (filter by placement_id, invoice_id, status) | AccountManager, Recruiter, Client, Candidate |
| GET | `/staffing/timesheets/{id}` | Get a timesheet | AccountManager, Recruiter, Client, Candidate |
| PATCH | `/staffing/timesheets/{id}` | Timesheet transition (submit / approve / reject / revise) | Candidate, Client |
| POST | `/staffing/invoices` | Create a draft invoice for a client | AccountManager |
| GET | `/staffing/invoices` | List invoices (filter by client_id, status) | AccountManager, Client |
| GET | `/staffing/invoices/{id}` | Get an invoice (with computed subtotal, discount, fee, total) | AccountManager, Client |
| GET | `/staffing/invoices/{id}/line-items` | List line items for an invoice | AccountManager, Client |
| POST | `/staffing/invoices/{id}/line-items` | Add a line item billing one APPROVED timesheet | AccountManager |
| PATCH | `/staffing/invoices/{id}` | Invoice lifecycle transition (issue / pay / void) | AccountManager |
| GET | `/staffing/conversion-fees` | List conversion fees (filter by placement_id, client_id) | AccountManager, Client |
| GET | `/staffing/conversion-fees/{id}` | Get a conversion fee (with computed fee_cents) | AccountManager, Client |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_CLIENT_NOT_FOUND` | 404 Not Found |
| `ERR_SKILL_NOT_FOUND` | 404 Not Found |
| `ERR_CANDIDATE_NOT_FOUND` | 404 Not Found |
| `ERR_JOB_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_SUBMISSION_NOT_FOUND` | 404 Not Found |
| `ERR_INTERVIEW_NOT_FOUND` | 404 Not Found |
| `ERR_PLACEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_TIMESHEET_NOT_FOUND` | 404 Not Found |
| `ERR_INVOICE_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 422 Unprocessable Entity |
| `ERR_SKILL_CODE_DUPLICATE` | 409 Conflict |
| `ERR_CLIENT_SUSPENDED` | 409 Conflict |
| `ERR_JOB_ORDER_NOT_DRAFT` | 409 Conflict |
| `ERR_JOB_ORDER_NOT_OPEN` | 409 Conflict |
| `ERR_JOB_ORDER_NOT_ON_HOLD` | 409 Conflict |
| `ERR_JOB_ORDER_NOT_CLOSEABLE` | 409 Conflict |
| `ERR_CANDIDATE_NOT_AVAILABLE` | 409 Conflict |
| `ERR_CANDIDATE_INACTIVE` | 409 Conflict |
| `ERR_SUBMISSION_BAD_STATE` | 409 Conflict |
| `ERR_SUBMISSION_NOT_OFFER_EXTENDED` | 409 Conflict |
| `ERR_NO_PASSED_INTERVIEW` | 409 Conflict |
| `ERR_INTERVIEW_BAD_STATE` | 409 Conflict |
| `ERR_PLACEMENT_NOT_PENDING_START` | 409 Conflict |
| `ERR_PLACEMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_PLACEMENT_NOT_CONVERTIBLE` | 409 Conflict |
| `ERR_PLACEMENT_ALREADY_CONVERTED` | 409 Conflict |
| `ERR_TIMESHEET_BAD_STATE` | 409 Conflict |
| `ERR_INVOICE_BAD_STATE` | 409 Conflict |
| `ERR_INVOICE_EMPTY` | 409 Conflict |
| `ERR_TIMESHEET_NOT_APPROVED` | 409 Conflict |
| `ERR_TIMESHEET_CLIENT_MISMATCH` | 409 Conflict |
| `ERR_STALE_JOB_ORDER_VERSION` | 412 Precondition Failed |
| `ERR_SKILL_MISMATCH` | 409 Conflict |
| `ERR_PLACEMENT_DATE_OVERLAP` | 409 Conflict |
| `ERR_TIMESHEET_WEEK_OVERLAP` | 409 Conflict |
| `ERR_NO_OPENINGS_REMAINING` | 409 Conflict |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 Payment Required |
